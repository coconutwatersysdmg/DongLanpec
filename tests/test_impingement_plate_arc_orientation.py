# -*- coding: utf-8 -*-
"""圆弧形防冲板局部坐标系方向回归测试。"""

import math
import unittest

from PyQt5.QtCore import QPointF

from modules.buguan.buguan_ziyong.component import impingement_plate


class ArcImpingementPlateOrientationTests(unittest.TestCase):
    def _build_axes(self, point1, point2, clearance=10.0):
        build_axes = getattr(
            impingement_plate,
            "build_arc_local_coordinate_system",
            None,
        )
        self.assertIsNotNone(build_axes)
        return build_axes(QPointF(*point1), QPointF(*point2), clearance)

    def test_equal_radius_bottom_pair_opens_toward_center(self):
        point1 = (-50.0, 100.0)
        point2 = (50.0, 100.0)
        self.assertEqual(math.hypot(*point1), math.hypot(*point2))

        A, B, x_axis, y_axis = self._build_axes(point1, point2)

        self.assertAlmostEqual(x_axis.x(), -1.0)
        self.assertAlmostEqual(x_axis.y(), 0.0)
        self.assertAlmostEqual(y_axis.x(), 0.0)
        self.assertAlmostEqual(y_axis.y(), 1.0)
        self.assertAlmostEqual((A.y() + B.y()) / 2.0, 90.0)

        open_mid = QPointF((A.x() + B.x()) / 2.0, (A.y() + B.y()) / 2.0)
        closed_mid = open_mid + y_axis * 30.0
        self.assertLess(
            math.hypot(open_mid.x(), open_mid.y()),
            math.hypot(closed_mid.x(), closed_mid.y()),
        )

    def test_local_positive_y_points_outward_at_each_cardinal_position(self):
        cases = (
            ((-50.0, -100.0), (50.0, -100.0), (0.0, -1.0)),
            ((-50.0, 100.0), (50.0, 100.0), (0.0, 1.0)),
            ((-100.0, -50.0), (-100.0, 50.0), (-1.0, 0.0)),
            ((100.0, -50.0), (100.0, 50.0), (1.0, 0.0)),
        )

        for point1, point2, expected_y_axis in cases:
            with self.subTest(point1=point1, point2=point2):
                A, B, _x_axis, y_axis = self._build_axes(point1, point2)
                self.assertAlmostEqual(y_axis.x(), expected_y_axis[0])
                self.assertAlmostEqual(y_axis.y(), expected_y_axis[1])

                open_mid = QPointF(
                    (A.x() + B.x()) / 2.0,
                    (A.y() + B.y()) / 2.0,
                )
                closed_mid = open_mid + y_axis * 30.0
                self.assertLess(
                    math.hypot(open_mid.x(), open_mid.y()),
                    math.hypot(closed_mid.x(), closed_mid.y()),
                )

    def test_reversing_selected_points_keeps_the_same_opening_direction(self):
        forward = self._build_axes((-50.0, 100.0), (50.0, 100.0))
        reversed_points = self._build_axes((50.0, 100.0), (-50.0, 100.0))

        for forward_point, reversed_point in zip(forward, reversed_points):
            self.assertAlmostEqual(forward_point.x(), reversed_point.x())
            self.assertAlmostEqual(forward_point.y(), reversed_point.y())


if __name__ == "__main__":
    unittest.main()
