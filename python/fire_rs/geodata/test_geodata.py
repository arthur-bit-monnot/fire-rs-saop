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

import unittest

import gdal
import numpy as np

from fire_rs.geodata.geo_data import GeoData, Area


class WorldTest(unittest.TestCase):

    def setUp(self):
        self.gd = GeoData(np.array([[11, 12], [21, 22]]), 0, 0, 1, 1)

    def test_access(self):
        self.assertEqual(self.gd.data[0, 0], 11)
        self.assertEqual(self.gd.data[1, 1], 22)
        self.assertEqual(self.gd.data[0, 1], 12)
        self.assertEqual(self.gd.data[1, 0], 21)

    def test_right_append(self):
        gd_right = GeoData(np.array([[31, 32], [41, 42]]), 2, 0, 1, 1)
        res = self.gd.append_right(gd_right)
        self.assertEqual(res.data[0, 0], 11)
        self.assertEqual(res.data[1, 1], 22)
        self.assertEqual(res.data[0, 1], 12)
        self.assertEqual(res.data[1, 0], 21)
        self.assertEqual(res.data[3, 0], 41)
        self.assertEqual(res.data.shape, (4, 2))

    def test_bottom_append(self):
        gd_right = GeoData(np.array([[31, 32], [41, 42]]), 0, 2, 1, 1)
        res = self.gd.append_bottom(gd_right)
        self.assertEqual(res.data.shape, (2, 4))

    def test_split(self):
        res = self.gd.split(2, 2)
        assert all([(1, 1) == t.data.shape for t in res])

        # recreate initial array from the split ones
        combined = res[0].append_right(res[1]).append_bottom(res[2].append_right(res[3]))
        np.testing.assert_allclose(self.gd.data, combined.data)

    def test_subset(self):
        res = self.gd.subset(Area(1, 1, 0, 1))
        self.assertEqual(res.data.shape, (1, 2))


if __name__ == '__main__':
    gdal.UseExceptions()
    unittest.main()
