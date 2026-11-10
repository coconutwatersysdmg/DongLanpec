# -*- coding: utf-8 -*-
"""平板形防冲板外移法向回归测试。

法向必须始终指向背离坐标原点（筒体中心）的一侧：
上半圆等价于旧的“屏幕上方”；下半圆镜像到参照管下方（外侧）。
"""

import math
import unittest

from modules.buguan.buguan_ziyong.component import impingement_plate


class FlatImpingementPlateOrientationTests(unittest.TestCase):
    def _select_normal(self, point1, point2):
        select = getattr(
            impingement_plate,
            "select_flat_plate_outward_normal",
            None,
        )
        self.assertIsNotNone(select)
        return select(point1, point2)

    def test_cardinal_positions_point_away_from_origin(self):
        cases = (
            ((-50.0, -100.0), (50.0, -100.0), (0.0, -1.0)),  # 上半圆：向上
            ((-50.0, 100.0), (50.0, 100.0), (0.0, 1.0)),  # 下半圆：向下镜像
            ((-100.0, -50.0), (-100.0, 50.0), (-1.0, 0.0)),  # 左侧：向左
            ((100.0, -50.0), (100.0, 50.0), (1.0, 0.0)),  # 右侧：向右
        )

        for point1, point2, expected in cases:
            with self.subTest(point1=point1, point2=point2):
                nx, ny = self._select_normal(point1, point2)
                self.assertAlmostEqual(nx, expected[0])
                self.assertAlmostEqual(ny, expected[1])

    def test_shifted_mid_always_farther_from_origin(self):
        cases = (
            ((-50.0, -100.0), (50.0, -100.0)),
            ((-50.0, 100.0), (50.0, 100.0)),
            ((-100.0, -50.0), (-100.0, 50.0)),
            ((100.0, -50.0), (100.0, 50.0)),
            ((-80.0, 60.0), (-20.0, 90.0)),  # 斜向：左下象限
            ((30.0, -90.0), (90.0, -40.0)),  # 斜向：右上象限
        )

        for point1, point2 in cases:
            with self.subTest(point1=point1, point2=point2):
                nx, ny = self._select_normal(point1, point2)
                mx = (point1[0] + point2[0]) / 2.0
                my = (point1[1] + point2[1]) / 2.0
                original = math.hypot(mx, my)
                shifted = math.hypot(mx + nx * 30.0, my + ny * 30.0)
                self.assertGreater(shifted, original)

    def test_bottom_half_mirrors_top_half(self):
        top_nx, top_ny = self._select_normal((-50.0, -100.0), (50.0, -100.0))
        bottom_nx, bottom_ny = self._select_normal((-50.0, 100.0), (50.0, 100.0))

        self.assertAlmostEqual(top_nx, bottom_nx)
        self.assertAlmostEqual(top_ny, -bottom_ny)

    def test_reversing_selected_points_keeps_the_same_direction(self):
        forward = self._select_normal((-50.0, 100.0), (50.0, 100.0))
        reversed_points = self._select_normal((50.0, 100.0), (-50.0, 100.0))

        self.assertAlmostEqual(forward[0], reversed_points[0])
        self.assertAlmostEqual(forward[1], reversed_points[1])


if __name__ == "__main__":
    unittest.main()
