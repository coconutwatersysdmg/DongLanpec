# -*- coding: utf-8 -*-
"""折流板弹窗打开时“切口与中心线间距a”初始化计算的回归测试。"""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QTableWidget,
    QTableWidgetItem,
)

from modules.buguan.buguan_ziyong import My_Piping as piping


class _BaffleHost(QMainWindow):
    """模拟已经建好产品、主参数表里有值的主界面。"""

    def __init__(self, a_value, od_value="1493.0", rate_value="25", dis_value="1800"):
        super().__init__()
        self.heat_exchanger = "BEM"
        self.param_table = QTableWidget(0, 4, self)
        params = [
            ("公称直径 DN", "1500", "mm"),
            ("壳体内直径 Dis", dis_value, "mm"),
            ("折流/支持板外径", od_value, "mm"),
            ("折流/支持板间距", "200", "mm"),
            ("折流板类型", "单弓形", ""),
            ("折流板切口方向", "水平上下", ""),
            ("折流板要求切口率", rate_value, "%"),
            ("折流板切口与中心线间距a", a_value, "mm"),
        ]
        self.param_table.setRowCount(len(params))
        for row, (name, value, unit) in enumerate(params):
            self.param_table.setItem(row, 1, QTableWidgetItem(name))
            self.param_table.setItem(row, 2, QTableWidgetItem(value))
            self.param_table.setItem(row, 3, QTableWidgetItem(unit))


class BaffleSpacingDialogInitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _open_dialog_and_read_a(self, a_value, **kwargs):
        host = _BaffleHost(a_value, **kwargs)
        result = {}

        def fake_exec(dialog):
            dialog.show()
            self.app.processEvents()
            table = dialog.findChild(QTableWidget)
            for row in range(table.rowCount()):
                name_item = table.item(row, 0)
                if name_item and name_item.text().strip() == "折流板切口与中心线间距a":
                    value_item = table.item(row, 1)
                    result["a"] = value_item.text().strip() if value_item else None
                    break
            dialog.accept()
            return 0

        try:
            with patch.object(piping.QDialog, "exec_", fake_exec):
                piping.TubeLayoutEditor.show_baffle_info(host)
        finally:
            host.close()
            host.deleteLater()
        return result.get("a")

    def test_expired_a_is_recalculated_from_baffle_od(self):
        # 甲方场景：外径 1493、切口率 25%，主表里 a 却是旧值 284.5。
        # 1493/2 - 25%*1493 = 373.25 -> 373.2
        self.assertEqual(self._open_dialog_and_read_a("284.5"), "373.2")

    def test_integer_a_is_kept_as_entered(self):
        # 历史行为：用户手工填的整数 a 不能被重算成 404.9 这类小数。
        self.assertEqual(self._open_dialog_and_read_a("405"), "405")

    def test_empty_a_is_filled_using_baffle_od_not_dis(self):
        # 主表 a 为空时，公式基数必须是外径而非壳体内直径 Dis（这里 Dis=1800 故意不同）。
        self.assertEqual(self._open_dialog_and_read_a(""), "373.2")

    def test_self_consistent_a_is_kept(self):
        # 已经是正确值的小数保持不变，不产生 373.2 -> 373.2 的抖动。
        self.assertEqual(self._open_dialog_and_read_a("373.2"), "373.2")


if __name__ == "__main__":
    unittest.main()
