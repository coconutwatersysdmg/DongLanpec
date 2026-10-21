# -*- coding: utf-8 -*-
"""滑道高度/厚度预定义关联的回归测试。"""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QLineEdit

from modules.buguan.buguan_ziyong import predefined_config
from modules.buguan.buguan_ziyong.component import slipway


MALFORMED_HEADER_VALUE = """[
    ['热交换器公称直径mm', '管束质量kg', 最小厚度mm: 非合金钢、低合金钢, 最小厚度mm: 高合金钢, 高度mm],
    [325, 500, 6, 4, 30],
    [800, 4000, 10, 7, 40]
]"""


class SlipwayPredefinedParserTests(unittest.TestCase):
    def test_database_value_with_unquoted_header_still_parses_numeric_rows(self):
        table = predefined_config._parse_slipway_size_table(MALFORMED_HEADER_VALUE)

        self.assertEqual(
            table,
            {
                325.0: {
                    "thickness_carbon": 6.0,
                    "thickness_high": 4.0,
                    "height": 30.0,
                },
                800.0: {
                    "thickness_carbon": 10.0,
                    "thickness_high": 7.0,
                    "height": 40.0,
                },
            },
        )

    def test_well_formed_list_input_remains_supported(self):
        table = predefined_config._parse_slipway_size_table(
            [["表头", "质量", "碳钢厚度", "高合金厚度", "高度"], [500, 1500, 8, 5, 30]]
        )

        self.assertEqual(table[500.0]["thickness_carbon"], 8.0)
        self.assertEqual(table[500.0]["thickness_high"], 5.0)
        self.assertEqual(table[500.0]["height"], 30.0)


class _Editor:
    def __init__(self, baffle_diameter=200, recommended=None):
        self.baffle_diameter = baffle_diameter
        self.recommended = recommended or {"height": 30.0, "thickness": 6.0}

    def get_baffle_diameter(self):
        return self.baffle_diameter

    def _get_slideway_predefined_defaults(self):
        return dict(self.recommended)


class SlipwayDialogValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_inputs(self, height, thickness):
        return {
            "滑道高度": QLineEdit(str(height)),
            "滑道厚度": QLineEdit(str(thickness)),
        }

    def test_height_must_not_exceed_half_baffle_diameter(self):
        inputs = self.make_inputs(101, 6)
        with patch.object(slipway.QMessageBox, "warning") as warning:
            accepted = slipway._validate_plate_slipway_inputs(
                _Editor(baffle_diameter=200), None, inputs,
                {"滑道高度": "30", "滑道厚度": "6"},
            )

        self.assertFalse(accepted)
        self.assertEqual(inputs["滑道高度"].text(), "30")
        warning.assert_called_once_with(
            None, "输入错误", "您输入的数值小于0或已超限，请重新输入！"
        )

    def test_thickness_must_be_greater_than_zero(self):
        inputs = self.make_inputs(30, 0)
        with patch.object(slipway.QMessageBox, "warning") as warning:
            accepted = slipway._validate_plate_slipway_inputs(
                _Editor(), None, inputs,
                {"滑道高度": "30", "滑道厚度": "6"},
            )

        self.assertFalse(accepted)
        self.assertEqual(inputs["滑道厚度"].text(), "6")
        warning.assert_called_once_with(
            None, "输入错误", "您输入的数值小于0，请重新输入！"
        )

    def test_non_finite_values_are_rejected(self):
        inputs = self.make_inputs("nan", 6)
        with patch.object(slipway.QMessageBox, "warning"):
            accepted = slipway._validate_plate_slipway_inputs(
                _Editor(), None, inputs,
                {"滑道高度": "30", "滑道厚度": "6"},
            )

        self.assertFalse(accepted)
        self.assertEqual(inputs["滑道高度"].text(), "30")

    def test_rejecting_below_predefined_height_clears_height(self):
        inputs = self.make_inputs(20, 6)
        with patch.object(
            slipway.QMessageBox, "question", return_value=slipway.QMessageBox.No
        ):
            accepted = slipway._validate_plate_slipway_inputs(
                _Editor(), None, inputs,
                {"滑道高度": "30", "滑道厚度": "6"},
            )

        self.assertFalse(accepted)
        self.assertEqual(inputs["滑道高度"].text(), "")

    def test_accepting_below_predefined_values_keeps_user_input(self):
        editor = _Editor()
        inputs = self.make_inputs(20, 5)
        with patch.object(
            slipway.QMessageBox, "question", return_value=slipway.QMessageBox.Yes
        ):
            accepted = slipway._validate_plate_slipway_inputs(
                editor, None, inputs,
                {"滑道高度": "30", "滑道厚度": "6"},
            )

        self.assertTrue(accepted)
        self.assertEqual(inputs["滑道高度"].text(), "20")
        self.assertEqual(inputs["滑道厚度"].text(), "5")
        self.assertFalse(hasattr(editor, "_last_valid_slideway_height_text"))
        self.assertFalse(hasattr(editor, "_last_valid_slipway_thickness_text"))

        slipway._remember_accepted_plate_slipway_inputs(editor, inputs)
        self.assertEqual(editor._last_valid_slideway_height_text, "20")
        self.assertEqual(editor._last_valid_slipway_thickness_text, "5")


if __name__ == "__main__":
    unittest.main()
