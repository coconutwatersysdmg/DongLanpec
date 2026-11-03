# -*- coding: utf-8 -*-
"""折流/支持板间距首次确认、首次保存的回归测试。"""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import (
    QApplication,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from modules.buguan.buguan_ziyong import My_Piping as piping


class _RestoredLayoutEditor:
    has_piped = False
    current_centers = [(0.0, 0.0), (32.0, 0.0)]
    input_json = {"LB_Tubeform": "2.1"}

    @staticmethod
    def get_selected_tube_pass_form():
        return "2.1"

    @staticmethod
    def get_tube_pass_count():
        return "2"


class _BaffleDialogHost(QMainWindow):
    def __init__(self):
        super().__init__()
        self.heat_exchanger = "BEM"
        self.param_table = QTableWidget(0, 4, self)
        params = [
            ("公称直径 DN", "600", "mm"),
            ("壳体内直径 Dis", "600", "mm"),
            ("折流/支持板外径", "570", "mm"),
            ("折流/支持板间距", "200", "mm"),
            ("折流板类型", "单弓形", ""),
            ("折流板切口方向", "水平上下", ""),
            ("折流板要求切口率", "25", "%"),
            ("折流板切口与中心线间距a", "142.5", "mm"),
        ]
        self.param_table.setRowCount(len(params))
        for row, (name, value, unit) in enumerate(params):
            self.param_table.setItem(row, 1, QTableWidgetItem(name))
            self.param_table.setItem(row, 2, QTableWidgetItem(value))
            self.param_table.setItem(row, 3, QTableWidgetItem(unit))

    @staticmethod
    def _calc_table8_default_baffle_od(dn_value=None, dis_value=None):
        return 570.0

    def value_of(self, param_name):
        for row in range(self.param_table.rowCount()):
            name_item = self.param_table.item(row, 1)
            if name_item and name_item.text() == param_name:
                return self.param_table.item(row, 2).text()
        return None


class BaffleSpacingFirstSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_restored_layout_is_marked_piped_before_parameter_save(self):
        editor = _RestoredLayoutEditor()

        ready = piping.TubeLayoutEditor._ensure_tube_pass_layout_before_save(editor)

        self.assertTrue(ready)
        self.assertTrue(editor.has_piped)

    def test_dialog_ok_commits_active_spacing_editor_on_first_click(self):
        host = _BaffleDialogHost()

        def edit_spacing_and_click_ok(dialog):
            dialog.show()
            self.app.processEvents()
            table = dialog.findChild(QTableWidget)
            spacing_row = next(
                row
                for row in range(table.rowCount())
                if table.item(row, 0).text() == "折流/支持板间距"
            )
            value_item = table.item(spacing_row, 1)
            table.setCurrentCell(spacing_row, 1)
            table.editItem(value_item)
            self.app.processEvents()
            editor = self.app.focusWidget()
            self.assertIsInstance(editor, QLineEdit)
            editor.setText("350")

            ok_button = next(
                button
                for button in dialog.findChildren(QPushButton)
                if button.text() == "确定"
            )
            ok_button.click()
            self.app.processEvents()
            return 0

        try:
            with patch.object(piping.QDialog, "exec_", edit_spacing_and_click_ok):
                piping.TubeLayoutEditor.show_baffle_info(host)

            self.assertEqual(host.value_of("折流/支持板间距"), "350")
        finally:
            host.close()
            host.deleteLater()


if __name__ == "__main__":
    unittest.main()
