import unittest
import fire_rs.firemodel.propagation as propagation
from fire_rs.geodata.geo_data import TimedPoint


class TestPropagation(unittest.TestCase):


    def setUp(self):
        self.test_area = [[480060.0, 485060.0], [6210074.0, 6215074.0]]
        self.ignition_point = TimedPoint(480060+800, 6210074+2500, 0)

    def test_propagate(self):
        env = propagation.Environment(self.test_area, wind_speed=4.11, wind_dir=0)
        prop = propagation.propagate_from_points(env, [self.ignition_point], horizon=3*3600)
        # prop.plot(blocking=True)

    def test_propagate_full(self):
        env = propagation.Environment(self.test_area, wind_speed=4.11, wind_dir=0)
        prop = propagation.propagate_from_points(env, [self.ignition_point])
        prop.plot(blocking=True)
