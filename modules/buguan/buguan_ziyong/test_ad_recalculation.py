"""重新打开本地布管后，Ad 仍应按当前管孔重算。"""

import unittest
from types import SimpleNamespace

from modules.buguan.buguan_ziyong import piping_calculations
from modules.buguan.buguan_ziyong.tube_pass.ad_calculation import (
    build_ad_kwargs_from_editor,
)
from modules.buguan.buguan_ziyong.tube_pass.core_calculation import compute_centers


SAVED_INPUT = {
    "local_tube_pass": "True",
    "Cat": "8a",
    "D": "320",
    "Snv": "44",
    "Snh": "50",
    "Wx0": "60",
    "Wx1": "0",
    "Wy0": "70",
    "Wy1": "0",
    "Wy2": "0",
    "S": "32",
    "d": "25",
    "Layout": "S",
    "Arr": "45",
    "Cut": "HUD",
}


class SavedInputCursor:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, args):
        self.connection.queries.append((sql, args))

    def fetchall(self):
        return [
            {"key": key, "value": value}
            for key, value in self.connection.saved_input.items()
        ]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class SavedInputConnection:
    def __init__(self, saved_input):
        self.saved_input = saved_input
        self.queries = []

    def cursor(self):
        return SavedInputCursor(self)


class AdRecalculationTests(unittest.TestCase):
    def setUp(self):
        input_values = dict(SAVED_INPUT)
        compute_kwargs = {
            key: float(input_values[key])
            for key in ("D", "Snv", "Snh", "Wx0", "Wx1", "Wy0", "Wy1", "Wy2", "S", "d")
        }
        compute_kwargs.update(Cat="8a", Layout="S", Arr=45, Cut="HUD")
        self.raw = compute_centers(**compute_kwargs)
        self.connection = SavedInputConnection(input_values)
        self.editor = SimpleNamespace(
            productID="PD-AD-RELOAD",
            tube_pass_form_value="8a.1",
            current_centers=list(self.raw["XY"]),
            left_data_pd={
                "换热管中心距 S": "32",
                "分程隔板两侧相邻管中心距（竖直）": "44",
                "分程隔板两侧相邻管中心距（水平）": "50",
                "换热管排列方式": "转角正方形",
                "折流板切口方向": "水平上下",
            },
            _active_sql_conn=self.connection,
        )

    def test_reload_recovers_partition_values_from_saved_layout_input(self):
        kwargs = build_ad_kwargs_from_editor(self.editor)

        self.assertIsNotNone(kwargs)
        self.assertEqual(kwargs["RowAmax"], self.raw["RowAmax"])
        self.assertEqual(kwargs["ColAmax"], self.raw["ColAmax"])
        self.assertEqual(kwargs["XY"], [tuple(p) for p in self.editor.current_centers])
        self.assertEqual(self.connection.queries[0][1], ("PD-AD-RELOAD",))

    def test_repeated_save_recalculates_after_tube_is_removed(self):
        first_results = {}
        piping_calculations.apply_ad_to_calc_results(self.editor, first_results)
        self.editor.current_centers = self.editor.current_centers[1:]
        second_results = {}
        piping_calculations.apply_ad_to_calc_results(self.editor, second_results)

        self.assertNotEqual(first_results["管板分程处面积Ad"], "0")
        self.assertNotEqual(second_results["管板分程处面积Ad"], "0")
        self.assertNotEqual(
            first_results["管板分程处面积Ad"],
            second_results["管板分程处面积Ad"],
        )


if __name__ == "__main__":
    unittest.main()
