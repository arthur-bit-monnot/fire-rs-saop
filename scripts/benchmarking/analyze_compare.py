#!/usr/bin/env python3

# Copyright (c) 2017, CNRS-LAAS
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

"""Compare several benchmarks"""

import datetime
import functools
import json
import os
import os.path
import typing as t

import matplotlib
import matplotlib.pyplot
import matplotlib.axes
import numpy as np
import pandas as pd

from collections.abc import OrderedDict


class BenchmarkRun:
    def __init__(self, b_date: 'str', base_folder: 'str'):
        self._date = datetime.datetime.strptime(b_date, "%Y-%m-%d--%H:%M:%S")
        self._date_str = b_date
        self._base_folder = base_folder
        self._full_path = os.path.join(self._base_folder, self._date_str)
        self._metadata_keys, self._metadata_values = zip(
            *self._read_metadata(self._full_path, sorted(os.listdir(self._full_path),
                                                         key=lambda x: int(
                                                             os.path.splitext(x)[0]))))
        self._metadata_keys = {v: i for i, v in enumerate(self._metadata_keys)}

        metadata = []
        self._utility_history = []
        for v in self._metadata_values:
            fields = {
                "configuration_name": v["configuration"]["vns"]["configuration_name"],
                "benchmark_id": v["benchmark_id"],
                "utility": v["plan"]["utility"],
                "planning_time": v["planning_time"]
            }
            metadata.append(fields)

            self._utility_history.append(pd.DataFrame.from_records(np.array(v["utility_history"]),
                                                                   columns=["time", "utility"]))
        self._metadata_df = pd.DataFrame.from_records(metadata)

    @property
    def raw_metadata(self, item=None) -> 't.List[t.Dict]':
        if item is None:
            return self._metadata_values
        else:
            if isinstance(item, int):
                return self._metadata_values[item]
            elif isinstance(item, str):
                return self._metadata_values[self._metadata_keys[item]]

    @property
    def date(self) -> 'datetime.datetime':
        return self._date

    @property
    def date_str(self) -> 'str':
        return self._date_str

    @property
    def n_instances(self) -> 'int':
        return len(self._metadata_df)

    @property
    def summary(self) -> 'pd.DataFrame':
        return self._metadata_df

    @property
    def utility_history(self) -> 't.List[pd.DataFrame]':
        return self._utility_history

    @staticmethod
    def _read_metadata(base_path, file_path_list: 't.List[str]'):
        for file_path in file_path_list:
            if not file_path.endswith(".json"):
                continue
            with open(os.path.join(base_path, file_path), 'r') as f:
                # Return pair filename w/o extension and json content
                yield os.path.splitext(os.path.split(file_path)[1])[0], json.load(f)


class BenchmarkScenario:
    SCENARIO_FILENAME = 'scenarios.dump'

    def __init__(self, name, path):
        self._name = name
        self._path = path

        # self._scenario = pickle.load(
        #     open(os.path.join(self._path, BenchmarkScenario.SCENARIO_FILENAME), 'rb'))
        # assert isinstance(self._scenario, fire_rs.planning.benchmark.Scenario)

        self._runs_values = tuple(BenchmarkRun(fd, os.path.join(path)) for fd in
                                  sorted(os.listdir(path)) if
                                  fd != BenchmarkScenario.SCENARIO_FILENAME)
        self._run_str_keys = {v.date_str: i for i, v in enumerate(self._runs_values)}
        self._run_date_keys = {v.date: i for i, v in enumerate(self._runs_values)}

    def __getitem__(self, item):
        if isinstance(item, int):
            return self._runs_values[item]
        elif isinstance(item, str):
            return self._runs_values[self._run_str_keys[item]]

    @property
    def runs(self):
        return self._runs_values

    @property
    def name(self):
        return self._name

    @property
    def path(self):
        return self._path

    # @property
    # def scenario(self):
    #     return self.scenario


class Benchmark:
    _BENCHMARK_PREFIX = "saop"
    _DATA_FOLDER = "data"
    _NOT_A_BENCHMARK = {"dem", "wind", "landcover"}

    def __init__(self, base_path: 'str', git_hash: 'str', name=""):
        self._git_hash = git_hash
        self._name = name
        self._relative_path = "_".join((Benchmark._BENCHMARK_PREFIX, self._git_hash))
        self._base_path = base_path
        path = os.path.join(self.full_path, Benchmark._DATA_FOLDER)
        self._scen_values = tuple(
            BenchmarkScenario(fd, os.path.join(path, fd)) for fd in os.listdir(path) if
            fd not in Benchmark._NOT_A_BENCHMARK)
        self._scen_keys = {bs.name: i for i, bs in enumerate(self._scen_values)}

    def __getitem__(self, item):
        if isinstance(item, int):
            return self._scen_values[item]
        elif isinstance(item, str):
            return self._scen_values[self._scen_keys[item]]

    @property
    def name(self):
        return self._name

    @property
    def scenarios(self) -> 't.Sequence[BenchmarkScenario]':
        return self._scen_values

    @property
    def full_path(self) -> 'str':
        return os.path.join(self._base_path, self._relative_path)

    @property
    def relative_path(self) -> 'str':
        return self._relative_path

    @property
    def git_hash(self) -> 'str':
        return self._git_hash


class BenchmarkRunStats:

    def __init__(self, some_run: 'BenchmarkRun'):
        self._b_run = some_run  # type: 'BenchmarkRun'

    def plot_utility_vs_time(self, ax: 'matplotlib.axes.Axes', normalize=False, max=None):
        for i, v in enumerate(self._b_run.utility_history):
            data = v.values.copy()
            if normalize:
                if max is not None:
                    data[:, 1] /= data[:, 1].max()
                else:
                    data[:, 1] /= max[i]
            data[:, 0] = np.arange(0, len(data[:, 0]))
            BenchmarkRunStats._plot_utility_time(data, ax)

    def plot_utility_vs_iterations(self, ax: 'matplotlib.axes.Axes', normalize=False, max=None):
        for i, v in enumerate(self._b_run.utility_history):
            data = v.values.copy()
            if normalize:
                if max is not None:
                    data[:, 1] /= data[:, 1].max()
                else:
                    data[:, 1] /= max[i]
            data[:, 0] = np.arange(0, len(data[:, 0]))
            BenchmarkRunStats._plot_utility_iterations(data, ax)

    def utility_histogram(self, ax: 'matplotlib.axes.Axes', max=None, **kwargs):
        ut = self._b_run.summary["utility"].copy()
        if max is None:
            ut /= ut.max()
        else:
            ut /= max
        ax.hist(ut, range=(0., 1.), **kwargs)

    @staticmethod
    def _plot_utility_time(time_utilites: 'np.ndarray', ax: 'matplotlib.axes.Axes'):
        ax.plot(time_utilites[:, 0], time_utilites[:, 1])
        ax.set_xlabel("Time")
        ax.set_ylabel("Utility")

    @staticmethod
    def _plot_utility_iterations(iteration_utilites: 'np.ndarray', ax: 'matplotlib.axes.Axes'):
        ax.plot(iteration_utilites[:, 0], iteration_utilites[:, 1])
        ax.set_xlabel("Improvement #")
        ax.set_ylabel("Utility")

    @property
    def benchmark_run(self) -> 'BenchmarkRun':
        return self._b_run


class BenchmarkRunComparator:
    def __init__(self, benchmarks: 't.Sequence[BenchmarkRun]', labels: 't.Sequence[str]'):
        self.b_run_stats = tuple(BenchmarkRunStats(b) for b in benchmarks)
        self._labels = labels

        self._final_utilities = np.array(
            [brs.benchmark_run.summary["utility"].values for brs in self.b_run_stats])
        self._worst_utilities = self._final_utilities.max(axis=0)

    def plot_utility_vs_iterations(self, ax_seq: 't.Sequence[matplotlib.axes.Axes]'):
        for (b, ax) in zip(self.b_run_stats, ax_seq):
            b.plot_utility_vs_iterations(ax, normalize=True, max=self._worst_utilities)

    def plot_utility_vs_time(self, ax_seq: 't.Sequence[matplotlib.axes.Axes]'):
        for (b, ax) in zip(self.b_run_stats, ax_seq):
            b.plot_utility_vs_time(ax, normalize=True, max=self._worst_utilities)

    def utility_boxplot(self, ax: 'matplotlib.axes.Axes'):
        utilities = [
            brs.benchmark_run.summary["utility"] / np.max(self._worst_utilities)
            for brs in self.b_run_stats]
        ax.boxplot(utilities, labels=self._labels)

    def utility_histogram_stacked(self, ax):
        for b in self.b_run_stats:
            b.utility_histogram(ax, max=np.max(self._worst_utilities), alpha=0.66)


if __name__ == '__main__':
    workdir = dir_path = os.path.dirname(os.path.realpath(__file__))
    ben_new = Benchmark(workdir, '7a7598fc4cae1ab28235b035503aab6dfa097ad5', name="new")
    ben_old_with_obsfull = Benchmark(workdir, '5bff6e68c98061ec63077d0b6288fd0b3aad268e',
                                     name="old_obsfull")
    ben_old = Benchmark(workdir, '86fbaa6243a6e9f94ffcf2a4e0064ef9ced30956', name="old")

    brc = BenchmarkRunComparator((ben_old.scenarios[0].runs[1],
                                  ben_old_with_obsfull.scenarios[0].runs[1],
                                  ben_new.scenarios[0].runs[1]),
                                 (ben_old.name,
                                  ben_old_with_obsfull.name,
                                  ben_new.name))

    xscale = 'log'
    yscale = 'log'

    y_lim = (0.001, 100)
    x_lim = (1, 100)

    figure = matplotlib.pyplot.figure()
    ax_old = figure.add_subplot(131, xscale=xscale, yscale=yscale)
    ax_old.set_ylim(*y_lim)
    ax_old.set_xlim(*x_lim)
    ax_old_with_obsfull = figure.add_subplot(132, xscale=xscale, yscale=yscale)
    ax_old_with_obsfull.set_ylim(*y_lim)
    ax_old_with_obsfull.set_xlim(*x_lim)
    ax_new = figure.add_subplot(133, xscale=xscale, yscale=yscale)
    ax_new.set_ylim(*y_lim)
    ax_new.set_xlim(*x_lim)
    brc.plot_utility_vs_iterations((ax_old, ax_old_with_obsfull, ax_new))
    figure.show()

    figure_boxplot = matplotlib.pyplot.figure()
    ax_boxplot = figure_boxplot.gca()
    ax_boxplot.set_title("Normalized utility distribution")
    brc.utility_boxplot(ax_boxplot)
    figure_boxplot.show()

    figure_hist = matplotlib.pyplot.figure()
    ax_hist = figure_hist.gca()
    ax_hist.set_title("Utility distribution")
    brc.utility_histogram_stacked(ax_hist)
    figure_hist.show()

    print("eee")
