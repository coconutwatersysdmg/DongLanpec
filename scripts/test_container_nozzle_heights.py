"""主视图逐管口标注；A 向相同外伸投影合并，不同端点保留。"""
import math
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from modules.TwoD import container_main_view as view


def nozzle(code, x, angle=0, height=750):
    end_on = angle in (90, 270)
    return view.NozzleSpec(code=code, function="", owner="容器圆筒", owner_kind="cylinder",
                           axial_reference="", axial_x=x, position_distance=x, axial_angle=0,
                           circumferential_angle=angle, side=0 if end_on else (1 if angle == 0 else -1),
                           projection="end_on" if end_on else "radial", eccentricity=0,
                           position_source="test", outside_diameter=114.3, outside_length=167,
                           total_outside_height=height, flange_diameter=230, flange_height=77)


class NozzleHeightTests(unittest.TestCase):
    height = 35.35

    def test_equal_height_nozzles_are_all_dimensioned_with_their_own_face(self):
        pipes = [nozzle("N1", 700), nozzle("N2", 900), nozzle("N3", 1100, angle=180)]
        data = SimpleNamespace(nozzles=pipes)
        geometries = {i: view._radial_nozzle_geometry(n, n.axial_x, 505) for i, n in enumerate(pipes)}
        with patch.object(view, "_add_aligned_dimension") as draw:
            view._draw_radial_nozzle_height_dimensions(None, data, geometries, self.height)
        self.assertEqual(draw.call_count, 3)
        self.assertEqual({call.args[1] for call in draw.call_args_list}, {(700, 0), (900, 0), (1100, 0)})
        self.assertEqual({call.args[2] for call in draw.call_args_list}, {(700, 750), (900, 750), (1100, -750)})
        self.assertTrue(all(call.args[4] == "750±3" for call in draw.call_args_list))

    def test_height_lines_avoid_all_flanges_and_each_other(self):
        pipes = [nozzle("N1", 700), nozzle("N2", 900), nozzle("N3", 905)]
        data = SimpleNamespace(nozzles=pipes)
        geometries = {i: view._radial_nozzle_geometry(n, n.axial_x, 505) for i, n in enumerate(pipes)}
        positions = view._radial_height_dimension_positions(data, geometries, self.height)
        self.assertEqual(len(positions), 3)
        for x in positions.values():
            for pipe in pipes:
                half = max(pipe.flange_diameter, pipe.outside_diameter) / 2
                self.assertGreaterEqual(abs(x - pipe.axial_x), half + self.height * .5 - 1e-6)
        xs = sorted(positions.values())
        self.assertTrue(all(b - a >= self.height * 1.6 - 1e-6 for a, b in zip(xs, xs[1:])))

    def test_opposite_side_dimensions_remain_separate_without_nozzle_codes(self):
        pipes = [nozzle("N7", 700, angle=90, height=700),
                 nozzle("N8", 900, angle=90, height=700), nozzle("N10", 1100, angle=270, height=700)]
        data = SimpleNamespace(nozzles=pipes)
        layout = SimpleNamespace(center_x=6000, center_y=0, outside_radius=505)
        geometries = [view._side_nozzle_geometry(n, layout) for n in pipes]
        with patch.object(view, "_add_aligned_dimension") as draw:
            bottom = view._draw_side_nozzle_height_dimensions(None, data, layout, geometries, -727, self.height)
        self.assertEqual(draw.call_count, 2)
        self.assertEqual([c.args[4] for c in draw.call_args_list], ["700±3", "700±3"])
        for call in draw.call_args_list:
            self.assertAlmostEqual(math.dist(call.args[1], call.args[2]), 700)
            self.assertLess(call.args[3][1], -727)
            self.assertLess(bottom, call.args[3][1] - self.height)

    def test_same_side_and_height_share_one_dimension_even_at_different_axial_stations(self):
        pipes = [nozzle("N7", 700, angle=90, height=700),
                 nozzle("N8", 900, angle=90, height=700), nozzle("N10", 1100, angle=90, height=700)]
        layout = SimpleNamespace(center_x=6000, center_y=0, outside_radius=505)
        geometries = [view._side_nozzle_geometry(n, layout) for n in pipes]
        with patch.object(view, "_add_aligned_dimension") as draw:
            bottom = view._draw_side_nozzle_height_dimensions(None, SimpleNamespace(nozzles=pipes),
                                                            layout, geometries, -727, self.height)
        self.assertEqual(draw.call_count, 1)
        self.assertEqual(draw.call_args.args[4], "700±3")
        self.assertAlmostEqual(math.dist(draw.call_args.args[1], draw.call_args.args[2]), 700)
        self.assertAlmostEqual(bottom, -727-self.height*3.8)

    def test_different_height_or_eccentricity_is_not_merged(self):
        base = nozzle("N7", 700, angle=90, height=700)
        layout = SimpleNamespace(center_x=6000, center_y=0, outside_radius=505)
        for change in ({"total_outside_height": 750}, {"eccentricity": 100}):
            pipes = [base, replace(base, code="N8", axial_x=900), replace(base, code="N10", **change)]
            geometries = [view._side_nozzle_geometry(n, layout) for n in pipes]
            with self.subTest(change=change), patch.object(view, "_add_aligned_dimension") as draw:
                view._draw_side_nozzle_height_dimensions(None, SimpleNamespace(nozzles=pipes),
                                                        layout, geometries, -727, self.height)
                self.assertEqual(draw.call_count, 2)
                self.assertTrue(all("N" not in c.args[4] for c in draw.call_args_list))

    def test_eccentric_side_nozzle_value_and_actual_face_use_same_centerline(self):
        pipe = replace(nozzle("N7", 700, angle=90, height=700), eccentricity=100)
        layout = SimpleNamespace(center_x=6000, center_y=0, outside_radius=505)
        geometry = view._side_nozzle_geometry(pipe, layout)
        with patch.object(view, "_add_aligned_dimension") as draw:
            view._draw_side_nozzle_height_dimensions(None, SimpleNamespace(nozzles=[pipe]),
                                                    layout, [geometry], -727, self.height)
        self.assertAlmostEqual(draw.call_args.args[1][0], 6000)
        self.assertAlmostEqual(draw.call_args.args[1][1], -100)
        self.assertAlmostEqual(draw.call_args.args[2][0], 6700)
        self.assertAlmostEqual(draw.call_args.args[2][1], -100)
        self.assertEqual(draw.call_args.args[4], "700±3")

    def test_head_nozzles_have_true_axial_extension_dimensions(self):
        for owner in ("front_head", "rear_head"):
            pipe = replace(nozzle("N1", 0), owner_kind=owner, projection="head")
            data = SimpleNamespace(cylinder_outside_diameter=1010)
            layout = SimpleNamespace(front_length=291, cylinder_end_x=4331, rear_length=287)
            with self.subTest(owner=owner), patch.object(view, "_point", side_effect=lambda *p: p), \
                    patch.object(view, "_insert_oriented_component"), \
                    patch.object(view, "_add_nozzle_label_text"), \
                    patch.object(view, "_add_aligned_dimension") as draw:
                view._draw_head_nozzle(MagicMock(), pipe, {"nozzle": "body", "nozzle_flange": "flange"},
                                       data, layout, 26.26)
            self.assertEqual(draw.call_count, 1)
            self.assertAlmostEqual(math.dist(draw.call_args.args[1], draw.call_args.args[2]), 244)
            self.assertEqual(draw.call_args.args[4], "N1 外伸 244±3")


if __name__ == "__main__":
    unittest.main()
