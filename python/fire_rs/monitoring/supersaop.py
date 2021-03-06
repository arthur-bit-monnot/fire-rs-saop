# Copyright (c) 2018, CNRS-LAAS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#  * Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
#  * Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import abc
import itertools
import functools
import json
import logging
import queue
import threading
import typing as ty
import datetime
import uuid

import collections

from collections import namedtuple
from enum import Enum

from osgeo import osr

import numpy as np
# import matplotlib.pyplot as plt

import fire_rs.firemodel.propagation

import fire_rs.geodata.wildfire
import fire_rs.geodata.geo_data as geo_data
# import fire_rs.geodata.display as gdisplay
import fire_rs.planning.new_planning as planning
import fire_rs.firemodel.propagation as propagation
import fire_rs.neptus_interface as nifc

# import fire_rs.planning.display as pdisplay
# import fire_rs.monitoring.ui as ui

supersaop_start_time = datetime.datetime.now()

Alarm = ty.Tuple[datetime.datetime, ty.Sequence[geo_data.TimedPoint]]

Area2D = ty.Tuple[ty.Tuple[float, float], ty.Tuple[float, float]]

DEFAULT_HORIZON = datetime.timedelta(minutes=60)


class AreaGenerator:

    def __init__(self, keypoints: ty.Sequence[float], clearance: ty.Sequence[float]):
        self.area = ((.0, .0), (.0, .0))

    # def recompute_area(self):
    #     """Given some sequences of ignition points and bases, compute reasonable
    #     bounds for a PlanningEnvironment around them"""
    #
    #     def extend_area(area: Area2D, point, clearance):
    #         min_px = min(area[0][0], point[0] - clearance[0])
    #         max_px = max(area[0][1], point[0] + clearance[0])
    #         min_py = min(area[1][0], point[1] - clearance[1])
    #         max_py = max(area[1][1], point[1] + clearance[1])
    #
    #         return (min_px, max_px), (min_py, max_py)
    #
    #     if not self._ignition_pts:
    #         # No alarms, then no area
    #         return
    #
    #     # first alarm, ignited seq, first ignited, x or y
    #     area_temp = self.area
    #
    #     ignition_clear = (2500.0, 2500.0)
    #     for ig in self._ignition_pts:
    #         area = extend_area(area_temp, ig, ignition_clear)
    #
    #     base_clear = (150.0, 150.0)
    #     for base_wp in self.hangar.bases.values():
    #         area = extend_area(area_temp, base_wp, ignition_clear)
    #
    #     self._area = area_temp


class SituationAssessment:
    """Evaluate the current state of a wildfire and provide fire perimeter forecasts"""

    class ObservedWildfire:
        """Store an observed wildfire map updatable from different sources"""

        def __init__(self, elevation: fire_rs.geodata.geo_data.GeoData):
            self._elevation = elevation
            self._cells = {}
            self._geodata = fire_rs.firemodel.propagation.empty_firemap(self._elevation)
            self.last_updated = datetime.datetime.now()

        @property
        def cells(self) -> ty.ItemsView:
            return self._cells.items()

        @property
        def geodata(self) -> fire_rs.geodata.geo_data.GeoData:
            return self._geodata.clone()

        def set_point_ignition(self, ig_pt: geo_data.TimedPoint):
            """Set some position as on fire.

            The current wildfire propagator is not reset.
            """
            c = self._geodata.array_index((ig_pt[0], ig_pt[1]))
            self.set_cell_ignition((c[0], c[1], ig_pt[2]))

        def set_cell_ignition(self, ig_cell: ty.Tuple[int, int, float]):
            """Set some cell on fire
            :param ig_cell: (x_cell, y_cell, time)
            """
            c = (ig_cell[0], ig_cell[1])
            self._cells[c] = ig_cell[2]
            self._geodata['ignition'][c] = ig_cell[2]
            self.last_updated = datetime.datetime.now()

        def clear_observation_cell(self, cell: ty.Tuple[int, int]):
            """Clear some cell that was previously set on fire
            :param cell: (x_cell, y_cell)
            """
            if cell in self._cells:
                del self._cells[cell]
            self._geodata['ignition'][cell] = np.inf
            self.last_updated = datetime.datetime.now()

    class WildfireCurrentAssessment:
        """Evaluate the current state of a wildfire from observations"""

        def __init__(self, environment: fire_rs.firemodel.propagation.Environment,
                     observations: ty.MutableMapping[ty.Tuple[int, int], float],
                     perimeter_time: ty.Optional[datetime.datetime]):
            self._environment = environment
            self._perimeter = None
            self._interpolated = fire_rs.firemodel.propagation.empty_firemap(
                self._environment.raster)
            self._observations = observations

            self.time = perimeter_time
            self._oldest_obs_timestamp = None
            self._newest_obs_timestamp = None

            if self._observations:
                self._oldest_obs_timestamp = min(*self._observations.values(), 2 ** 64 - 1)
                self._newest_obs_timestamp = max(*self._observations.values(), 0.)
                if not perimeter_time:
                    self.time = datetime.datetime.fromtimestamp(self._newest_obs_timestamp)
                self._interpolate()
                try:
                    self._compute_perimeter(self.time.timestamp())
                except Exception as e:
                    self._perimeter = None

        @property
        def geodata(self):
            """Interpolated Wildfire map"""
            return self._interpolated

        @property
        def perimeter(self) -> ty.Optional[fire_rs.geodata.wildfire.Perimeter]:
            if not self._perimeter:
                self._compute_perimeter(self.time.timestamp())
            return self._perimeter

        def _interpolate(self):
            """RBF interpolation"""
            x, y = list(zip(*self._observations.keys()))
            z = np.array(list(self._observations.values()))

            if len(z) > 1:
                # Normalise

                z_min = z.min()
                z_max = z.max()
                z -= z_min
                z /= z_max - z_min

                # Interpolate on normalised ignition time
                array = fire_rs.geodata.wildfire.interpolate(x, y, z, self._interpolated.data.shape,
                                                             function='thin_plate')

                # Denormalise
                array *= z_max - z_min
                array += z_min

                # Filter out extrapolations, because they are not reliable!
                time_span = self._newest_obs_timestamp - self._oldest_obs_timestamp
                # array[array < self._oldest_obs_timestamp-0.1*time_span] = 0
                array[array > self._newest_obs_timestamp+0.05*time_span] = np.inf
                self._interpolated.data["ignition"] = array
            else:
                self._interpolated.data["ignition"][x, y] = z

        def compute_perimeter(self):
            """Compute the perimeter if it has not been computed before"""
            if not self._perimeter:
                self._compute_perimeter(self.time.timestamp())

        def _compute_perimeter(self, threshold: float):
            self._perimeter = fire_rs.geodata.wildfire.Perimeter(self._interpolated, threshold)
            # if len(self._perimeter.cells) < len(self._observations):
            #     for k, v in self._observations.items():
            #         self._perimeter.cells[k] = v
            #         self._perimeter.array[k] = v

    class WildfireCurrentFusionAssessment:
        """Evaluate the current state of a wildfire by fusing a forecast with actual observations"""

        def __init__(self, environment: fire_rs.firemodel.propagation.Environment,
                     observations: ty.MutableMapping[ty.Tuple[int, int], float],
                     predicted_firemap: fire_rs.geodata.geo_data.GeoData,
                     perimeter_time: ty.Optional[datetime.datetime]):
            self._environment = environment
            self._predicted_firemap = predicted_firemap
            self._perimeter = None
            self._assessment = fire_rs.firemodel.propagation.empty_firemap(
                self._environment.raster)
            self._observations = observations

            self._assessment_debug_data

            self.time = perimeter_time
            self._oldest_obs_timestamp = None
            self._newest_obs_timestamp = None

            if self._observations:
                self._oldest_obs_timestamp = min(*self._observations.values(), 2 ** 64 - 1)
                self._newest_obs_timestamp = max(*self._observations.values(), 0.)
                if not perimeter_time:
                    self.time = datetime.datetime.fromtimestamp(self._newest_obs_timestamp)
                self._warping()
                try:
                    self._compute_perimeter(self.time.timestamp())
                except Exception as e:
                    self._perimeter = None

        @property
        def geodata(self):
            """Interpolated Wildfire map"""
            return self._assessment

        @property
        def perimeter(self) -> ty.Optional[fire_rs.geodata.wildfire.Perimeter]:
            if not self._perimeter:
                self._compute_perimeter(self.time.timestamp())
            return self._perimeter

        def _warping(self):
            """Make an assessment by thin-plate spline warping"""

            # Find cell in the predited wildfire map with the same ignition time as in the
            # observed cells
            wg = fire_rs.geodata.wildfire.WildfireGraph(self._predicted_firemap)
            corresponding_cells_in_forecast = [wg.find_parent_or_child_of_time(
                cell, time) for cell, time in self._observations.items()]

            observed_cell_list = list(self._observations.keys())
            warped_map = fire_rs.geodata.wildfire.warp_firemap(
                self._predicted_firemap, corresponding_cells_in_forecast, observed_cell_list)

            self._assessment.data["ignition"] = warped_map.data["ignition"]

        def compute_perimeter(self):
            """Compute the perimeter if it has not been computed before"""
            if not self._perimeter:
                self._compute_perimeter(self.time.timestamp())

        def _compute_perimeter(self, threshold: float):
            self._perimeter = fire_rs.geodata.wildfire.Perimeter(self._assessment,
                                                                 threshold)

    class WildfireFuturePropagation:
        """Evaluate the future state of a wildfire from a known perimeter"""

        def __init__(self, environment: fire_rs.firemodel.propagation.Environment,
                     perimeter: ty.Optional[fire_rs.geodata.wildfire.Perimeter],
                     pending_ignitions: ty.MutableMapping[float, ty.Tuple[int, int]],
                     current_firemap: fire_rs.geodata.geo_data.GeoData,
                     until: datetime.datetime):
            self._environment = environment
            self._perimeter = perimeter
            self._pending_ignitions = pending_ignitions
            self._current_firemap = current_firemap
            self.fire_propagator = fire_rs.firemodel.propagation.FirePropagation(
                self._environment)  # type: fire_rs.firemodel.propagation.FirePropagation
            self.geodata = fire_rs.firemodel.propagation.empty_firemap(self._environment.raster)
            self.until = until
            self.time = datetime.datetime.now()
            if self._perimeter or self._pending_ignitions:
                self._assess_until(self.until)

        def _assess_until(self, until: datetime.datetime):
            """Compute an expected wildfire up to some horizon"""
            if self._perimeter:
                self._pending_ignitions = {**self._pending_ignitions, **self._perimeter.cells}

            # First propagation
            fireprop = fire_rs.firemodel.propagation.FirePropagation(self._environment)

            # Mark burnt cells, so fire do not propagate over them again
            mask = np.where(
                (self._current_firemap.data["ignition"] > 0) & (
                        self._current_firemap.data["ignition"] < np.inf))
            if self._perimeter:
                mask = np.where(self._perimeter.area_array | np.isfinite(self._perimeter.array))

            fireprop.prop_data.data["ignition"][mask] = np.NaN

            for k, v in self._pending_ignitions.items():
                fireprop.set_ignition_cell((k[0], k[1], v))

            fireprop.propagate(until.timestamp())

            # remove pending ignitions
            self._pending_ignitions = {}

            # Store firemap
            self.geodata = fireprop.ignitions()

            # Fuse current and predicted firemaps
            # This removes wrong back propagation obtained from the fire propagator,
            # that doesn't take in account existing base firemaps.
            self.geodata.data["ignition"][mask] = self._current_firemap["ignition"][mask]

            # Update last assessment time
            self.time = datetime.datetime.now()

    def __init__(self, area, logger: logging.Logger, world_paths: ty.Optional[ty.Mapping] = None):
        """Initialize Situation Assessment.

        :param area: Area of interest in projected coordinates
        :param logger: A logging.Logger object
        :param world_paths: (Optional) A mapping with paths to elevation, landcover and wind maps"""
        super().__init__()
        self.logger = logger

        self._empty_area = ((np.inf, -np.inf), (np.inf, -np.inf))  # type: Area2D
        self._area = area  # type: Area2D

        self._surface_wind = (.0, .0)  # (speed, orientation)

        world = None
        if world_paths:
            world = fire_rs.geodata.environment.World(
                **world_paths,
                landcover_to_fuel_remap=fire_rs.geodata.environment.EVERYTHING_FUELMODEL_REMAP)
        self._environment = fire_rs.firemodel.propagation.Environment(
            self.area, wind_speed=self._surface_wind[0], wind_dir=self._surface_wind[
                1], world=world)  # type: ty.Optional[fire_rs.firemodel.propagation.Environment]

        self._observed_wildfire = SituationAssessment.ObservedWildfire(self._environment.raster)
        self._wildfire_current_assessment = SituationAssessment.WildfireCurrentAssessment(
            self._environment, dict(self._observed_wildfire.cells), datetime.datetime.now())
        self._wildfire_future_propagation = SituationAssessment.WildfireFuturePropagation(
            self._environment, None, {},
            fire_rs.firemodel.propagation.empty_firemap(self._environment.raster),
            datetime.datetime.now())

        self._elevation_timestamp = datetime.datetime.now()

    @property
    def surface_wind(self):
        return self._surface_wind

    def set_surface_wind(self, value: ty.Tuple[float, float]):
        """ Set mean surface wind.

        :param value: as (speed km/h, direction)
        """
        self._environment.update_area_wind(value[0], value[1])
        self.logger.debug("Surface wind has been updated to %s", value)

    @property
    def area(self):
        return self._area

    @property
    def observed_wildfire(self):
        """Fused observed wildfire"""
        return self._observed_wildfire

    @property
    def wildfire(self):
        """Estimated fire propagation in the present"""
        return self._wildfire_current_assessment

    @property
    def predicted_wildfire(self):
        """Expected fire propagation in the future"""
        return self._wildfire_future_propagation

    @property
    def elevation(self):
        """Elevation map"""
        return self._environment.raster.slice("elevation")

    @property
    def elevation_timestamp(self):
        """Elevation map timestamp"""
        return self._elevation_timestamp

    def assess_current(self, time: ty.Optional[datetime.datetime] = None):
        """Interpolate observed firemap"""
        if time is None:
            self.logger.info("Assessment of current wildfire state now")
        else:
            self.logger.info("Assessment of current wildfire state at time %s", str(time))
        try:
            self._wildfire_current_assessment = SituationAssessment.WildfireCurrentAssessment(
                self._environment, dict(self._observed_wildfire.cells), perimeter_time=time)
        except IndexError as e:
            self.logger.warning(e)
            self.logger.warning("Cannot make assessment")
            self._wildfire_current_assessment = None

    def assess_until(self, until: datetime.datetime):
        """Compute an expected wildfire simulation from initial observations."""
        if self._wildfire_current_assessment is not None:
            self.logger.info("Assessment of future wildfire state from %s until %s",
                             str(self._wildfire_current_assessment.time), str(until))
            self._wildfire_future_propagation = SituationAssessment.WildfireFuturePropagation(
                self._environment, self._wildfire_current_assessment.perimeter, {},
                self._wildfire_current_assessment.geodata, until)
        else:
            self.logger.info("Assessment of future wildfire state from until %s", str(until))
            if not self._observed_wildfire.cells:
                pass
            self._wildfire_future_propagation = SituationAssessment.WildfireFuturePropagation(
                self._environment, None, dict(self._observed_wildfire.cells),
                self._observed_wildfire.geodata, until)


class ObservationPlanning:
    """Create and manage plans to observe wildfires"""

    TrajectoryConf = namedtuple("TrajectoryConf", ["name", "uav_model", "start_wp", "end_wp",
                                                   "start_time", "max_duration", "wind"])
    # start_wp and end_wp are tuples, start_time is a float
    # wind represents a vector in (x,y) form as a tuple

    TrajType = ty.Tuple[TrajectoryConf, ty.Sequence[
        ty.Tuple[ty.Tuple[float, float, float, float], datetime.datetime, str]]]

    DEFAULT_UAV_MODELS = {'x8-06': planning.UAVModels.x8("06"),
                          'x8-02': planning.UAVModels.x8("02")}

    DEFAULT_VNS_CONFS = planning.VNSConfDB.demo_db()

    def __init__(self, logger: logging.Logger,
                 uav_models: ty.Mapping[
                     str, planning.UAV] = DEFAULT_UAV_MODELS,
                 vns_confs=DEFAULT_VNS_CONFS):
        self.logger = logger
        self.uav_models = uav_models
        self._vns_conf_db = vns_confs

        self._elevation = None  # type: fire_rs.geodata.geo_data.GeoData
        self._wildfire_map = None  # type: fire_rs.geodata.geo_data.GeoData
        self._current_planner = None  # type: fire_rs.planning.new_planning.Planner

    @property
    def current_plan(self):
        return self._current_planner.current_plan

    def set_elevation(self, elevation: fire_rs.geodata.geo_data.GeoData):
        """Replace the current elevation map by a new one"""
        assert "elevation" in elevation.layers
        self._elevation = elevation

    def set_wildfire_map(self, wildfire_map: fire_rs.geodata.geo_data.GeoData):
        """Replace the current wildfire map by a new one"""
        assert "ignition" in wildfire_map.layers
        self._wildfire_map = wildfire_map
        # TODO: Invalidate plan

    def set_initial_plan(self, name: str, traj_conf: ty.Sequence[TrajectoryConf],
                         flight_window: ty.Tuple[float, float]):
        """Set up the planner for an initial plan"""
        tc = [planning.Trajectory(planning.TrajectoryConfig(c.name,
                                                            self.uav_models[c.uav_model],
                                                            planning.Waypoint(*c.start_wp),
                                                            planning.Waypoint(*c.end_wp),
                                                            c.start_time,
                                                            c.max_duration,
                                                            planning.WindVector(*c.wind))) for c in
              traj_conf]
        f_data = planning.make_fire_data(self._wildfire_map, self._elevation)
        tw = planning.TimeWindow(*flight_window)
        utility = planning.make_flat_utility_map(self._wildfire_map, flight_window=tw,
                                                 output_layer="utility")
        the_plan = planning.Plan(name, tc, f_data, tw, utility.as_cpp_raster("utility"))
        self._current_planner = planning.Planner(the_plan, {})

    def set_plan(self, name: str, trajs: ty.Sequence[TrajType],
                 flight_window: ty.Tuple[float, float]):
        """Set up the planner for improving an existing plan"""

        tr = [planning.Trajectory(
            planning.TrajectoryConfig(c[0].name,
                                      self.uav_models[c[0].uav_model],
                                      planning.Waypoint(*c[0].start_wp),
                                      planning.Waypoint(*c[0].end_wp),
                                      c[0].start_time,
                                      c[0].max_duration,
                                      planning.WindVector(*c[0].wind)),
            [planning.TrajectoryManeuver(
                planning.Waypoint(*m[0]), m[1], m[2]) for m in c[1]]) for c in trajs]
        f_data = planning.make_fire_data(self._wildfire_map, self._elevation)
        tw = planning.TimeWindow(*flight_window)
        utility = planning.make_utility_map(self._wildfire_map, flight_window=tw,
                                            output_layer="utility")
        the_plan = planning.Plan(name, tr, f_data, tw, utility)
        self._current_planner = planning.Planner(the_plan, {})

    def compute_plan(self, planning_duration, vns_conf_name: str, after_time=.0,
                     frozen_trajs=[]) -> planning.Plan:
        """Execute the VNS planner for the current plan and return the improved one"""
        self._current_planner.vns_conf = self._vns_conf_db[vns_conf_name]
        return self._current_planner.compute_plan(planning_duration, after_time,
                                                  frozen_trajs).final_plan()

    # class SuperSAOP:
    #     """Supervise a wildifre monitoring mission"""
    #
    #     class State(Enum):
    #         """SuperSAOP operations"""
    #         SA = 0,  # Situation Assessment
    #         OP = 1,  # Observation Planning
    #         MO = 2  # Stop the mission
    #
    #     def __init__(self, hangar: Hangar, logger: logging.Logger, saop_ui=ui.NoUI()):
    #         """"""
    #         self.logger = logger
    #         self.ui = saop_ui
    #         self.hangar = hangar
    #
    #         self.monitoring = True
    #
    #     def main(self, alarm: Alarm):
    #         execution_monitor = ExecutionMonitor(self.logger.getChild("ExecutionMonitor"))
    #         while self.monitoring:
    #             situation_assessment = SituationAssessment(self.hangar,
    #                                                        self.logger.getChild("SituationAssessment"))
    #
    #             observation_planning = ObservationPlanning(self.hangar,
    #                                                        self.logger.getChild("ObservationPlanning"))
    #
    #             environment, firepropagation = situation_assessment.expected_situation(alarm)
    #
    #             # Show wildfire Situation Assessment
    #             alarm_gdd = gdisplay.GeoDataDisplay(*gdisplay.get_pyplot_figure_and_axis(),
    #                                                 environment.raster, frame=(0., 0.))
    #             alarm_gdd.add_extension(pdisplay.TrajectoryDisplayExtension, (None,))
    #             draw_situation(alarm_gdd, alarm, environment, firepropagation, self.hangar)
    #             alarm_gdd.figure.show()
    #             plt.pause(0.001)  # Needed to let matplotlib a chance of showing figures
    #
    #             # Observation Planning
    #             response = observation_planning.respond_to_alarm(
    #                 alarm, expected_situation=(environment, firepropagation))
    #
    #             draw_response(alarm_gdd, response)
    #             plt.pause(0.001)  # Needed to let matplotlib a chance of showing figures
    #
    #             while not execution_monitor.gcs.is_ready():
    #                 plt.pause(0.1)  # Use the matplotlib pause. So at least figures remain responsive
    #
    #             command_outcome = execution_monitor.start_response(response.plan,
    #                                                                response.uav_allocation)
    #
    #             if functools.reduce(lambda a, b: a and b, command_outcome) or True:
    #                 # state_monitor = execution_monitor.monitor_uav_state(self.hangar.vehicles)
    #                 traj_vec, state_vec, res = self.do_monitoring(response, execution_monitor)
    #                 if res == SuperSAOP.MonitoringAction.UNDECIDED:
    #                     self.monitoring = True
    #                 elif res == SuperSAOP.MonitoringAction.REPLAN:
    #                     self.logger.info("Replan triggered")
    #                     self.logger.info("TODO: Change bases of UAVs to their actual position")
    #                     # TODO: Change base of UAV
    #                 elif res == SuperSAOP.MonitoringAction.EXIT:
    #                     self.logger.info("SuperSAOP exit")
    #                     self.monitoring = False
    #             else:
    #                 if not self.ui.question_dialog("The plan couldn't be started. Restart?"):
    #                     self.monitoring = False
    #
    #         self.logger.info("End of monitoring mission for alarm %s", str(alarm))
    #
    #     def do_monitoring(self, response, execution_monitor) -> ty.Tuple[
    #         ty.Tuple[str, nifc.TrajectoryExecutionReport],
    #         ty.Tuple[ty.Tuple[str, int], nifc.UAVStateReport], MonitoringAction]:
    #         # FIXME: monitor all the trajectories not just one
    #         plan_name, traj = response.plan.name(), 0
    #         trajectory_monitor = execution_monitor.monitor_trajectory(plan_name, traj)
    #         uav_state_monitor = execution_monitor.monitor_uav_state(response.uav_allocation.values())
    #
    #         while True:
    #             traj_state_vector = next(trajectory_monitor, None)
    #             uav_state_vector = next(uav_state_monitor, None)
    #             if traj_state_vector is not None:
    #                 state, decision = self.plan_state_and_action(traj_state_vector)
    #                 if decision == SuperSAOP.MonitoringAction.EXIT:
    #                     return traj_state_vector, uav_state_vector, decision
    #                 elif decision == SuperSAOP.MonitoringAction.REPLAN:
    #                     return traj_state_vector, uav_state_vector, decision
    #                 elif decision == SuperSAOP.MonitoringAction.UNDECIDED:
    #                     if state == SuperSAOP.MissionState.FAILED:
    #                         self.logger.warning(
    #                             "Monitoring mission failed. User interaction needed")
    #                         if self.ui.question_dialog("Monitoring mission failed. Recover?"):
    #                             return traj_state_vector, uav_state_vector, SuperSAOP.MonitoringAction.REPLAN
    #                         else:
    #                             return traj_state_vector, uav_state_vector, SuperSAOP.MonitoringAction.EXIT
    #                     elif state == SuperSAOP.MissionState.EXECUTING:
    #                         pass  # SuperSAOP.MonitoringAction.UNDECIDED
    #                     elif state == SuperSAOP.MissionState.ENDED:
    #                         # TODO: If execution ended, REPLAN or EXIT?
    #                         return traj_state_vector, uav_state_vector, SuperSAOP.MonitoringAction.EXIT
    #                 current_mans, decision = self.meneuver_state_and_action(traj_state_vector,
    #                                                                         response.plan)
    #                 if decision != SuperSAOP.MonitoringAction.UNDECIDED:
    #                     return traj_state_vector, uav_state_vector, decision
    #
    #     def meneuver_state_and_action(self, state_dict: ty.Dict[
    #         ty.Tuple[str, int], nifc.TrajectoryExecutionReport], saop_plan) \
    #             -> ty.Tuple[ty.Dict[ty.Tuple[str, int], int], MonitoringAction]:
    #         """Determine the execution state of trajectory maneuvers regarding the original plan
    #
    #         If the execution is lagging with respect to the plan, the mission should be replanned.
    #
    #         Let `m` and `n` two consecutive maneuvers in a trajectory `T`.
    #         Then `t_m` is the start time of maneuver `m` and `t_n` the start time of maneuver `n`.
    #         A UAV is reporting the execution of maneuver `n` at time `t_x`
    #
    #         The plan is being followed if `t_m` < `t_x` <= `t_n` with a 3-minute tolerance
    #
    #         :returns A mapping of the current maneuvers being executed,
    #             and a MonitoringAction.
    #         """
    #         slack = datetime.timedelta(minutes=3)
    #         current_maneuvers = {}
    #         actions = {}
    #
    #         # TODO: Tolerance to be defined
    #         for plan_id, ter in state_dict.items():
    #
    #             if ter.timestamp < datetime.datetime.now().timestamp() - datetime.timedelta(
    #                     seconds=30).seconds:
    #                 # Ignore old TER messages
    #                 continue
    #
    #             action = SuperSAOP.MonitoringAction.UNDECIDED
    #             T = saop_plan.trajectories()[plan_id[1]]
    #             n = int(ter.maneuver)
    #             m = int(ter.maneuver) - 1
    #             t_x = ter.timestamp
    #             t_n = T.start_time(n) if n < len(T) else None
    #             t_m = T.start_time(m) if m >= 0 else None
    #
    #             if t_n is not None and t_x > t_n + slack.seconds:
    #                 # Going slower than expected
    #                 action = SuperSAOP.MonitoringAction.REPLAN
    #                 self.logger.info(
    #                     "Trajectory %s is running slower than expected man(%s) t(%s) > t_%s(%s)",
    #                     str(plan_id), str(n), datetime.datetime.fromtimestamp(t_x), str(n),
    #                     datetime.datetime.fromtimestamp(t_n) + slack)
    #             if t_m is not None and t_x < t_m - slack.seconds:
    #                 # Going faster than expected
    #                 action = SuperSAOP.MonitoringAction.REPLAN
    #                 self.logger.info(
    #                     "Trajectory %s is running faster than expected man(%s) t_x(%s) < t_%s(%s)",
    #                     str(plan_id), str(n), datetime.datetime.fromtimestamp(t_x), str(m),
    #                     datetime.datetime.fromtimestamp(t_m) - slack)
    #
    #             current_maneuvers[plan_id] = n
    #             actions[plan_id] = action
    #
    #         if next(filter(lambda a: a == SuperSAOP.MonitoringAction.REPLAN, actions.values()),
    #                 None) is None:
    #             return current_maneuvers, SuperSAOP.MonitoringAction.UNDECIDED
    #         else:
    #             return current_maneuvers, SuperSAOP.MonitoringAction.REPLAN
    #
    #     def plan_state_and_action(self, state_dict: ty.Dict[
    #         ty.Tuple[str, int], nifc.TrajectoryExecutionReport]) \
    #             -> ty.Tuple[MissionState, MonitoringAction]:
    #         """Determine the state of the mission and decide wether a mission should continue.
    #
    #         A mission is considered
    #             - FAILED if any trajectory state is Blocked or its outcome is Failure
    #             - ENDED: if all trajectory outcomes are Success
    #             - EXECUTING: if all trajectory states are Executing
    #
    #         The next action should be
    #             - UNDECIDED: No decision has been made
    #             - REPLAN: trigger a replan
    #             - EXIT: Stop the mission
    #         """
    #
    #         mission_s_v = {}
    #         for plan_id, ter in state_dict.items():
    #             if ter.state == nifc.TrajectoryExecutionState.Executing:
    #                 mission_s_v[plan_id] = SuperSAOP.MissionState.EXECUTING
    #             elif ter.state == nifc.TrajectoryExecutionState.Ready:
    #                 if ter.last_outcome == nifc.TrajectoryExecutionOutcome.Failure or \
    #                         ter.last_outcome == nifc.TrajectoryExecutionOutcome.Nothing:
    #                     mission_s_v[plan_id] = SuperSAOP.MissionState.FAILED
    #                 if ter.last_outcome == nifc.TrajectoryExecutionOutcome.Success:
    #                     mission_s_v[plan_id] = SuperSAOP.MissionState.ENDED
    #             else:  # nifc.TrajectoryExecutionState.Blocked
    #                 self.logger.critical("UAV %s is blocked. This is a failure")
    #                 return SuperSAOP.MissionState.FAILED, SuperSAOP.MonitoringAction.EXIT
    #
    #         for m_s in mission_s_v.values():
    #             if m_s == SuperSAOP.MissionState.FAILED:
    #                 # If one trajectory failed, the plan is a failure. Leave action undecided
    #                 return SuperSAOP.MissionState.FAILED, SuperSAOP.MonitoringAction.UNDECIDED
    #             elif m_s == SuperSAOP.MissionState.EXECUTING:
    #                 # If one trajectory is still running then the plan is not over yet
    #                 return SuperSAOP.MissionState.EXECUTING, SuperSAOP.MonitoringAction.UNDECIDED
    #         else:
    #             # All the trajectories are over
    #             return SuperSAOP.MissionState.ENDED, SuperSAOP.MonitoringAction.UNDECIDED
    #
    #


class _CoordinateTransformation:

    def __init__(self, src: int, dst: int):
        source = osr.SpatialReference()
        source.ImportFromEPSG(src)

        target = osr.SpatialReference()
        target.ImportFromEPSG(dst)

        self._transform = osr.CoordinateTransformation(source, target)

    def transform(self, *args) -> ty.Tuple[float, float, float]:
        return self._transform.TransformPoint(*args)


class NeptusBridge:
    """Communicate with the UAV ground control software.

    This class gets the current state of the UAV fleet and the completion state
    of trajectories.

    Current status is stored in a couple of dicts. Optionally callback routines
    can be set. Those are called each time a new state report arrives."""

    TrajectoryExecutionState = nifc.TrajectoryExecutionState
    TrajectoryExecutionOutcome = nifc.TrajectoryExecutionOutcome

    def __init__(self, logger: logging.Logger, coordinate_system: int = None):
        """Initialize a Neptus Bridge.

        :param logger: A logging.Logger object
        :param coordinate_system: A projected coordinate system EPSG code
        """
        self.logger = logger

        self.imccomm = nifc.IMCComm(8888)
        self.gcs = None

        self.uav_state = {}
        self.traj_state = {}
        self.firemaps = {}

        self.uav_state_cb = None
        self.traj_state_cb = None
        self.fire_map_cb = None

        self._projected_cs_epsg = geo_data.EPSG_RGF93_LAMBERT93 \
            if coordinate_system is None else coordinate_system
        self._geodetic_cs_epsg = geo_data.EPSG_RGF93

        self.set_coordinate_system(self._projected_cs_epsg)

        self._coor_tran = _CoordinateTransformation(self._geodetic_cs_epsg, self._projected_cs_epsg)

        self.t_imc = threading.Thread(target=self.imccomm.run, daemon=False)
        self.t_gcs = threading.Thread(target=self._create_gcs, daemon=False)

    def start(self):
        """Start the communication with Neptus"""
        self.t_imc.start()
        self.t_gcs.start()

    def set_coordinate_system(self, projected_cs: int, geodetic_cs: int = None):
        """Set the projected coordinate system for UAV locations.

        For Lambert93 and LAEA, the geodetic_cs parameter is not necessary

        :param projected_cs: Projected coordinate system
        :param geodetic_cs: (Optional) Force a geodetic coordinate system
        """
        if projected_cs == geo_data.EPSG_RGF93_LAMBERT93:
            self._projected_cs_epsg = projected_cs
            self._geodetic_cs_epsg = geo_data.EPSG_RGF93
        elif projected_cs == geo_data.EPSG_ETRS89_LAEA:
            self._projected_cs_epsg = projected_cs
            self._geodetic_cs_epsg = geo_data.EPSG_ETRS89
        elif projected_cs == geo_data.EPSG_WGS84_UTM29N:
            self._projected_cs_epsg = projected_cs
            self._geodetic_cs_epsg = geo_data.EPSG_WGS84

        self._coor_tran = _CoordinateTransformation(self._geodetic_cs_epsg, self._projected_cs_epsg)

    def _create_gcs(self):
        """Create GCS object of this class.
        To be runned in a different thread."""
        self.gcs = nifc.GCS(self.imccomm, self.on_trajectory_execution_report,
                            self._on_uav_state_report, self._on_firemap_report,
                            self._projected_cs_epsg)

    def loiter(self, uav: str, plan_name: str, loiter_id: str,
               center: ty.Tuple[float, float, float], radius: float, direction: int,
               duration: float):
        """Loiter somewhere"""
        loiter = fire_rs.planning.new_planning.LoiterManeuver(
            fire_rs.planning.new_planning.Circle(
                fire_rs.planning.new_planning.Position(*center), radius),
            fire_rs.planning.new_planning.CircularDirection(direction), duration)
        print("uav" + str(uav))
        self.gcs.loiter(plan_name, loiter, planning.UAVModels.get(uav).max_air_speed, uav)

    def start_trajectory(self, t: planning.Trajectory, uav: str) -> bool:
        """Execute a SAOP trajectory with neptus 'plan_id' using the vehicle 'uav'"""
        # Start the mission

        command_r = self.gcs.start(t, uav)

        if command_r:
            self.logger.info("Mission %s for %s started", t.name(), uav)
            return True
        else:
            self.logger.error("Start of mission %s failed for %s failed", t.name(), uav)
            return False

    def load_trajectory(self, t: planning.Trajectory, uav: str) -> bool:
        """Load a SAOP trajectory with neptus 'plan_id' for the vehicle 'uav'"""
        command_r = self.gcs.load(t, uav)

        if command_r:
            self.logger.info("Mission %s for %s loaded", t.name(), uav)
            return True
        else:
            self.logger.error("Load of mission %s for %s failed", t.name(), uav)
            return False

    def stop_uav(self, uav):
        # Stop previous trajectory (if any)
        command_r = self.gcs.stop("", uav)
        if command_r:
            self.logger.info("Mission of %s stopped", str(uav))
            return True
        else:
            self.logger.warning("Stop %s failed", str(uav))
            return False

    def set_wind(self, speed: float, direction: float, uav: str):
        if self.gcs.set_wind(speed, direction, uav):
            self.logger.info("Set wind for %s to %s", uav, str((speed, direction)))
        else:
            self.logger.error("Failed to set wind for %s to %s", uav, str((speed, direction)))

    def send_wildfire_contours(self, *drawable_contours):
        if not drawable_contours:
            self.logger.error("No contours to be sent")
        else:
            j_dict = {"wildfire_contours": drawable_contours}
            json_str = json.dumps(j_dict)
            self.gcs.send_device_data_text(json_str)

    def set_trajectory_state_callback(self, fn):
        """Function to be called each time a new Plan Control State is received.
        Keep it short as it blocks the delivery of other messages!!!
        :param fn: a Callable(**kwargs)
        """
        self.traj_state_cb = fn

    def on_trajectory_execution_report(self, ter: nifc.TrajectoryExecutionReport):
        """Method called by the GCS to report about the state of the missions.
        """
        self.traj_state[ter.plan_id] = dict(time=ter.timestamp, plan_id=ter.plan_id, uav=ter.uav,
                                            maneuver=ter.maneuver, maneuver_eta=ter.maneuver_eta,
                                            state=ter.state, last_outcome=ter.last_outcome)
        if self.traj_state_cb:
            self.traj_state_cb(time=ter.timestamp, plan_id=ter.plan_id, uav=ter.uav,
                               maneuver=ter.maneuver, maneuver_eta=ter.maneuver_eta,
                               state=ter.state, last_outcome=ter.last_outcome)

    def set_uav_state_callback(self, fn):
        """Function to be called each time a new Estimated State is received
        Keep it short as it blocks the delivery of other messages!!!
        :param fn: a Callable(**kwargs) (time: float, uav: str,
                                         x: float, y: float, z: float,
                                         phi: float, theta: float, psi: float,
                                         vx: float, vy: float, vz: float)
        x, y and z in ENU frame"""
        self.uav_state_cb = fn

    def _on_uav_state_report(self, usr: nifc.UAVStateReport):
        """Method called by the GCS to report about the state of the UAVs"""
        try:
            x, y, z = self._coor_tran.transform(usr.lon * 180 / np.pi,
                                                usr.lat * 180 / np.pi,
                                                usr.height)
            self.uav_state[usr.uav] = dict(time=usr.timestamp, uav=usr.uav,
                                           x=x, y=y, z=z,
                                           phi=usr.phi, theta=usr.theta, psi=usr.psi,
                                           vx=usr.vx, vy=usr.vy, vz=usr.vz)
            if self.uav_state_cb:
                self.uav_state_cb(time=usr.timestamp, uav=usr.uav,
                                  x=x, y=y, z=usr.height,
                                  phi=usr.phi, theta=usr.theta, psi=usr.psi,
                                  vx=usr.vx, vy=usr.vy, vz=usr.vz)
        except Exception as e:
            self.logger.error(e)

    def set_firemap_callback(self, fn):
        self.fire_map_cb = fn

    def _on_firemap_report(self, fmr: nifc.FireMapReport):
        firemap = geo_data.GeoData.from_cpp_raster(fmr.firemap, "ignition", self._projected_cs_epsg)
        self.firemaps[fmr.uav] = dict(time=fmr.timestamp, uav=fmr.uav, firemap=firemap)
        if self.fire_map_cb:
            self.fire_map_cb(time=fmr.timestamp, uav=fmr.uav, firemap=firemap)
