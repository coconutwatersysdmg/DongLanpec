# -*- coding: utf-8 -*-
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QMainWindow,
    QTableWidget,
    QTableWidgetItem,
)

from modules.buguan.buguan_ziyong.ai_assistant.controller import TubeAssistantController


PARAMS = {
    "公称直径 DN": "500",
    "壳体内直径 Dis": "450",
    "布管限定圆 DL": "400",
    "换热管外径 do": "19",
    "换热管中心距 S": "25",
    "换热管排列方式": "正三角形",
    "换热管布置方式": "对中",
    "分程隔板两侧相邻管中心距（竖直）": "30",
    "分程隔板两侧相邻管中心距（水平）": "30",
    "非布管区域弦高（0°/180°）": "0",
    "非布管区域弦高（90°/270°）": "0",
}


class FakeEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.param_table = QTableWidget(len(PARAMS), 3)
        for row, (name, value) in enumerate(PARAMS.items()):
            self.param_table.setItem(row, 1, QTableWidgetItem(name))
            if name == "换热管布置方式":
                combo = QComboBox()
                combo.addItems(["对中", "跨中", "任意"])
                combo.setCurrentText(value)
                self.param_table.setCellWidget(row, 2, combo)
            else:
                self.param_table.setItem(row, 2, QTableWidgetItem(value))
        self.action_bar = QHBoxLayout()
        self.global_centers = [(-100.0, 0.0), (100.0, 0.0), (0.0, -100.0), (0.0, 100.0)]
        self.current_centers = list(self.global_centers)
        self.current_centers_lagan = list(self.global_centers)
        self.R_wai = 250.0
        self.R_Di = 225.0
        self.R_nei = 200.0
        self.r = 9.5
        self.has_piped = True
        self.lagan_info = []
        self.operations = []
        self.red_dangban_abs = []
        self.center_dangguan_dic = {}
        self.center_dangban_dic = {}
        self.side_dangban_dic = {}
        self.impingement_plate_dic = {}
        self.screw_ring_dic = {}
        self.true_slipway_centers = []
        self.heat_exchanger = "BEM"
        self.draw_calls = []

    def get_selected_tube_pass_form(self):
        return "1"

    def _calculate_piping_layout_local(self, *args):
        if not getattr(self, "_ai_assistant_no_persist", False):
            raise AssertionError("助手应用时必须禁止直接持久化")
        self.global_centers = [(1.0, 2.0), (-1.0, -2.0)]
        self.current_centers = list(self.global_centers)
        self.current_centers_lagan = list(self.global_centers)
        return {"raw": {}}

    def draw_layout(self, *args):
        self.draw_calls.append(args)

    def build_lagan(self, centers, suppress_conflict_warning=False):
        self.lagan_info.extend(centers)

    def _invalidate_axis_cluster_cache(self):
        pass

    def update_tube_nums(self):
        pass

    def update_total_holes_count(self):
        pass

    def update_total_lagan_count(self):
        pass

    def update_cross_pipe_button_state(self):
        pass


class ControllerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = FakeEditor()
        self.controller = TubeAssistantController(self.editor)
        self.controller.install()

    def test_one_click_tube_apply_and_undo(self):
        original = list(self.editor.current_centers)
        candidate = self.controller.generate_tubes("尽量多布")[0]

        self.controller.apply_tube_candidate(candidate)
        self.assertEqual(self.editor.current_centers, [(1.0, 2.0), (-1.0, -2.0)])
        self.assertFalse(self.editor._ai_assistant_no_persist)
        self.assertTrue(self.controller.history.can_undo)

        self.controller.undo()
        self.assertEqual(self.editor.current_centers, original)
        self.assertFalse(self.controller.history.can_undo)

    def test_one_click_component_apply_and_undo(self):
        candidate = self.controller.generate_components(2, "外围对称")[0]
        self.controller.apply_component_candidate(candidate)
        self.assertEqual(len(self.editor.lagan_info), 2)

        self.controller.undo()
        self.assertEqual(self.editor.lagan_info, [])


if __name__ == "__main__":
    unittest.main()
