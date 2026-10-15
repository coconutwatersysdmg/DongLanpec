"""接管圈号应在尺寸区域外；径向和端视管口共同避让。"""

import math
import unittest
from unittest.mock import MagicMock, patch

from modules.TwoD import container_main_view as view


def nozzle(code, x, angle=0.0, height=750.0, axial_angle=0.0):
    end_on = angle in (90.0, 270.0)
    return view.NozzleSpec(
        code=code, function="", owner="容器圆筒", owner_kind="cylinder",
        axial_reference="", axial_x=x, position_distance=x, axial_angle=axial_angle,
        circumferential_angle=angle, side=0 if end_on else (1 if angle == 0 else -1),
        projection="end_on" if end_on else "radial", eccentricity=0.0,
        position_source="test", outside_diameter=114.3, outside_length=167.0,
        total_outside_height=height, flange_diameter=230.0, flange_height=77.0,
    )


class NozzleLabelLayoutTests(unittest.TestCase):
    text_height = 35.35
    label_radius = 26.26
    saddle_bottom = -666.6

    def layout(self, nozzles, xs=None):
        head = view.HeadSpec("封头", "ellipse_head", 250.0, 1010.0, 1000.0, 5.0)
        data = view.ContainerMainViewData(
            head, head, 1200.0, 1010.0, 1000.0, 5.0, 600.0, 222.2, 161.6, tuple(nozzles),
        )
        xs = tuple(xs if xs is not None else (n.axial_x for n in nozzles))
        geometries = {index: view._radial_nozzle_geometry(n, xs[index], 505.0)
                      for index, n in enumerate(nozzles) if n.projection == "radial"}
        levels = view._main_view_dimension_levels(
            data, geometries, self.saddle_bottom, self.text_height, self.label_radius,
        )
        centers = view._layout_main_view_nozzle_labels(
            data, xs, geometries,
            levels[0] + self.text_height * 2.0 + self.label_radius * 1.7,
            levels[3] - self.text_height * 2.0 - self.label_radius * 1.7,
            self.label_radius,
        )
        return data, xs, geometries, levels, centers

    def test_upper_radial_and_end_on_labels_are_outside_dimension_text(self):
        _, _, _, levels, centers = self.layout([
            nozzle("N1", 500.0), nozzle("N2", 700.0, height=700.0), nozzle("N3", 900.0, angle=90.0),
        ])
        for _, y in centers.values():
            self.assertGreater(y - self.label_radius, levels[0] + self.text_height * 2.0)

    def test_lower_labels_are_outside_nozzle_saddle_and_total_length_dimensions(self):
        _, _, _, levels, centers = self.layout([
            nozzle("N1", 500.0, angle=180.0), nozzle("N2", 700.0, angle=270.0),
        ])
        for _, y in centers.values():
            self.assertLess(y + self.label_radius, levels[3] - self.text_height * 2.0)
        self.assertLess(levels[3], levels[2])
        self.assertLess(levels[2], levels[1])

    def test_mixed_projection_and_adjacent_station_labels_do_not_overlap(self):
        _, _, _, _, centers = self.layout([
            nozzle("N1", 500.0), nozzle("N2", 500.0, angle=90.0),
            nozzle("N3", 510.0), nozzle("N4", 510.0, angle=90.0),
        ], xs=[500.0, 500.0, 520.0, 520.0])
        for left, (x, y) in centers.items():
            for right, (rx, ry) in centers.items():
                if left < right:
                    self.assertGreaterEqual(math.hypot(x - rx, y - ry), self.label_radius * 2.55 - 1e-6)
        self.assertGreater(centers[0][1], centers[1][1])

    def test_circle_radius_and_leader_anchor_are_preserved_for_sloped_nozzle(self):
        data, _, geometries, _, centers = self.layout([nozzle("N1", 500.0, axial_angle=30.0)])
        ms = MagicMock()
        with patch.object(view, "_point", side_effect=lambda *coords: coords), \
                patch.object(view, "_add_nozzle_label_text") as text:
            center = view._add_nozzle_label(ms, data.nozzles[0], geometries[0], self.label_radius,
                                            label_center=centers[0])
        self.assertEqual(center, centers[0])
        geometry = geometries[0]
        start, end = ms.AddLine.call_args.args
        self.assertEqual(start, (geometry.outer_x, geometry.outer_y, 0))
        self.assertAlmostEqual(math.hypot(end[0] - center[0], end[1] - center[1]), self.label_radius)
        self.assertEqual(ms.AddCircle.call_args.args[1], self.label_radius)
        self.assertEqual(text.call_args.args[2], center)

    def test_end_on_geometry_stays_in_place_when_label_moves_outside(self):
        data, xs, _, _, centers = self.layout([nozzle("N1", 500.0, angle=90.0)])
        ms = MagicMock()
        with patch.object(view, "_point", side_effect=lambda *coords: coords), \
                patch.object(view, "_add_nozzle_label_text"):
            center = view._draw_end_on_nozzle(ms, data.nozzles[0], xs[0], 505.0,
                                              self.text_height, self.label_radius,
                                              label_center=centers[0])
        self.assertEqual(center, centers[0])
        self.assertEqual(ms.AddCircle.call_args_list[0].args[0], (xs[0], 0.0, 0))
        self.assertEqual(ms.AddCircle.call_args_list[0].args[1], 115.0)
        self.assertEqual(ms.AddCircle.call_args_list[-1].args[0], (*centers[0], 0))

    def test_dimension_levels_preserve_nozzle_and_saddle_rows_with_extra_shell_length_row(self):
        _, _, _, levels, _ = self.layout([
            nozzle("N1", 500.0, height=800.0), nozzle("N2", 700.0, angle=180.0, height=750.0),
        ])
        top = 800.0 + self.label_radius * 5.8 + self.text_height * 2.0
        bottom = min(self.saddle_bottom, -750.0 - self.label_radius * 5.8) - self.text_height * 2.0
        saddle = bottom - self.text_height * 2.7
        total = saddle - self.text_height * 5.6
        self.assertEqual(levels, (top, bottom, saddle, total))


if __name__ == "__main__":
    unittest.main()
