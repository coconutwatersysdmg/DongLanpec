# -*- coding: utf-8 -*-
"""布管参数表头显示文案的回归测试。"""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QMainWindow, QStackedWidget

from modules.buguan.buguan_ziyong import My_Piping as piping


class HeaderEditor(piping.TubeLayoutEditor):
    """只创建布管页面，跳过数据库加载及与表头无关的计算。"""

    def __init__(self):
        QMainWindow.__init__(self)
        self.stacked_widget = QStackedWidget()
        self.global_centers = []
        self._current_centers = []
        self.del_centers = []

    def update_screw_ring_button_state(self):
        pass

    def update_toolbar_layout_mode(self):
        pass

    def update_total_lagan_count(self):
        pass

    def update_cross_pipe_button_state(self):
        pass

    def bind_table_selection_handler(self):
        pass

    def enable_scene_click_capture(self):
        pass

    def on_row_selection_changed(self):
        pass


class TubeLayoutHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_main_parameter_table_uses_full_parameter_name_header(self):
        editor = HeaderEditor()
        try:
            with patch.object(piping.QTimer, "singleShot", return_value=None):
                editor.create_tube_layout_page()
            self.assertEqual(editor.param_table.horizontalHeaderItem(1).text(), "参数名称")
        finally:
            editor.close()
            editor.deleteLater()

    def test_preview_parameter_table_uses_full_parameter_name_header(self):
        dialog = piping.PreviewDialog([])
        try:
            self.assertEqual(dialog.table.horizontalHeaderItem(1).text(), "参数名称")
        finally:
            dialog.close()
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
