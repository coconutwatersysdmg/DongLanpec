# -*- coding: utf-8 -*-
"""平板形防冲板“参照管顶部连线”法向回归测试（对齐全源程序）。

源程序行为：法向固定取 y 分量更小（屏幕上方）的一侧，
**不随参照管位于上/下半圆而镜像**。下半圆时防冲板同样向上平移。
"""

import unittest

from modules.buguan.buguan_ziyong.component import impingement_plate


class FlatImpingementPlateUpNormalTests(unittest.TestCase):
    def _select_normal(self, point1, point2):
        select = getattr(
            impingement_plate,
            "select_flat_plate_up_normal",
            None,
        )
        self.assertIsNotNone(select)
        return select(point1, point2)

    def test_horizontal_chord_always_points_up(self):
        cases = (
            ((-50.0, -100.0), (50.0, -100.0), (0.0, -1.0)),  # 上半圆：向上
            ((-50.0, 100.0), (50.0, 100.0), (0.0, -1.0)),  # 下半圆：同样向上（不镜像）
            ((-50.0, 0.0), (50.0, 0.0), (0.0, -1.0)),  # 过圆心：向上
        )

        for point1, point2, expected in cases:
            with self.subTest(point1=point1, point2=point2):
                nx, ny = self._select_normal(point1, point2)
                self.assertAlmostEqual(nx, expected[0])
                self.assertAlmostEqual(ny, expected[1])

    def test_top_and_bottom_half_are_identical(self):
        top = self._select_normal((-50.0, -100.0), (50.0, -100.0))
        bottom = self._select_normal((-50.0, 100.0), (50.0, 100.0))

        self.assertAlmostEqual(top[0], bottom[0])
        self.assertAlmostEqual(top[1], bottom[1])

    def test_normal_never_points_down(self):
        """法向不允许朝下；竖直连线时 ny==0，由调用处兜底改为 (0, -1)。"""
        cases = (
            ((-100.0, -50.0), (-100.0, 50.0)),  # 竖直连线（左侧）→ 水平法向
            ((100.0, -50.0), (100.0, 50.0)),  # 竖直连线（右侧）→ 水平法向
            ((-80.0, 60.0), (-20.0, 90.0)),  # 斜向：左下
            ((30.0, -90.0), (90.0, -40.0)),  # 斜向：右上
            ((30.0, 90.0), (90.0, 40.0)),  # 斜向：右下
        )

        for point1, point2 in cases:
            with self.subTest(point1=point1, point2=point2):
                nx, ny = self._select_normal(point1, point2)
                self.assertLessEqual(ny, 0.0)
                self.assertAlmostEqual(nx * nx + ny * ny, 1.0)

    def test_reversing_selected_points_keeps_the_same_direction(self):
        forward = self._select_normal((-50.0, 100.0), (50.0, 100.0))
        reversed_points = self._select_normal((50.0, 100.0), (-50.0, 100.0))

        self.assertAlmostEqual(forward[0], reversed_points[0])
        self.assertAlmostEqual(forward[1], reversed_points[1])


if __name__ == "__main__":
    unittest.main()
