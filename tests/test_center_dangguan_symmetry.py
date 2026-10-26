# -*- coding: utf-8 -*-
"""中间挡管在新增多管程下的对称添加回归测试。"""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QGraphicsScene

from modules.buguan.buguan_ziyong import My_Piping as piping
from modules.buguan.buguan_ziyong.component import center_dangguan


class CenterDangguanEditor:
    """只保留 on_center_block_click 通用管程路径需要的编辑器行为。"""

    def __init__(self, tube_pass_count, axis, tube_pass_form_value=None):
        self.tube_pass_count = tube_pass_count
        self.tube_pass_form_value = tube_pass_form_value
        self.heat_exchanger = "AEU"
        self.isSymmetry = True
        self.selected_centers = (
            [(1, 1), (-1, 1)]
            if axis == "x"
            else [(1, 1), (1, 2)]
        )
        self.global_centers = [
            (10.0, 10.0),
            (-10.0, 10.0),
            (10.0, -10.0),
            (-10.0, -10.0),
        ]
        self.current_centers = list(self.global_centers)
        self.full_sorted_current_centers_up = [
            [(10.0, 10.0), (-10.0, 10.0)]
        ]
        self.full_sorted_current_centers_down = [
            [(10.0, -10.0), (-10.0, -10.0)]
        ]
        self.sorted_current_centers_up = list(self.full_sorted_current_centers_up)
        self.sorted_current_centers_down = list(self.full_sorted_current_centers_down)
        self.center_dangguan = []
        self.center_dangguan_num = 0
        self.selected_center_dangguan = []
        self.graphics_scene = QGraphicsScene()
        self.graphics_view = None
        self.operations = []
        self.r = 5.0
        self.min_distance_row = 100.0
        self.min_distance_col = 100.0

    def _has_selected_converted_lagan(self):
        return False

    def get_tube_pass_count(self):
        return self.tube_pass_count

    def begin_center_dangguan_batch(self):
        self._cdg_batch_active = True
        self._cdg_batch_coords = []
        self._cdg_batch_items = []
        self._cdg_batch_failed = False

    def group_centers_by_y(self, _centers):
        return (
            [[(10.0, 10.0), (-10.0, 10.0)]],
            [[(10.0, -10.0), (-10.0, -10.0)]],
        )

    def selected_to_current_coords(self, selected):
        mapping = {
            (1, 1): (10.0, 10.0),
            (-1, 1): (10.0, -10.0),
            (1, 2): (-10.0, 10.0),
            (-1, 2): (-10.0, -10.0),
        }
        return [mapping[tuple(coord)] for coord in selected]

    def actual_to_selected_coords(self, actual):
        mapping = {
            (10.0, 10.0): (1, 1),
            (10.0, -10.0): (-1, 1),
            (-10.0, 10.0): (1, 2),
            (-10.0, -10.0): (-1, 2),
        }
        return mapping.get((float(actual[0]), float(actual[1])))

    def judge_linkage_y(self, selected):
        return piping.TubeLayoutEditor.judge_linkage_y(self, selected)

    def judge_linkage_x(self, selected):
        return piping.TubeLayoutEditor.judge_linkage_x(self, selected)

    def get_y_pair_by_W(self):
        return 30.0

    def get_getiao(self):
        return "30"

    def clear_selection_highlight(self):
        self.selection_cleared = True


class CenterDangguanSymmetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_two_pass_layout_keeps_existing_symmetric_pair_behavior(self):
        editor = CenterDangguanEditor("2", "x")
        drawn_coords = []

        with (
            patch.object(
                center_dangguan,
                "prompt_center_dangguan_params",
                return_value=True,
            ),
            patch.object(
                center_dangguan,
                "draw_center_dangguan_at_position",
                side_effect=lambda coord, _editor: drawn_coords.append(coord),
            ),
        ):
            piping.TubeLayoutEditor.on_center_block_click(editor)

        self.assertEqual(drawn_coords, [(10.0, 0), (-10.0, 0)])

    def test_four_and_six_pass_special_forms_keep_symmetric_pair_behavior(self):
        cases = (
            ("4", "4.2", "x", [(10.0, 0.0), (-10.0, 0.0)]),
            ("6", "6.2", "y", [(0.0, 10.0), (0.0, -10.0)]),
        )
        for tube_pass_count, form, axis, expected_coords in cases:
            with self.subTest(tube_pass_count=tube_pass_count, form=form):
                editor = CenterDangguanEditor(tube_pass_count, axis, form)

                with patch.object(
                    center_dangguan,
                    "prompt_center_dangguan_params",
                    return_value=True,
                ):
                    piping.TubeLayoutEditor.on_center_block_click(editor)

                self.assertCountEqual(editor.center_dangguan, expected_coords)

    def test_new_multi_pass_layouts_add_the_symmetric_center_dangguan_pair(self):
        for tube_pass_count in ("8", "10", "12"):
            for axis in ("x", "y"):
                with self.subTest(tube_pass_count=tube_pass_count, axis=axis):
                    editor = CenterDangguanEditor(tube_pass_count, axis)

                    with patch.object(
                        center_dangguan,
                        "prompt_center_dangguan_params",
                        return_value=True,
                    ):
                        piping.TubeLayoutEditor.on_center_block_click(editor)

                    expected_coords = (
                        [(10.0, 0.0), (-10.0, 0.0)]
                        if axis == "x"
                        else [(0.0, 10.0), (0.0, -10.0)]
                    )
                    self.assertCountEqual(editor.center_dangguan, expected_coords)


if __name__ == "__main__":
    unittest.main()
