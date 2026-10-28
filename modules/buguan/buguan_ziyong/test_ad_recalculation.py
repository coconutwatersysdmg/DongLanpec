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

    def test_reload_uses_saved_geometry_inputs_instead_of_drifted_parameter_table(self):
        """参数表变化后，不得把新参数与历史布管坐标、分区量混算。"""
        self.editor.left_data_pd.update(
            {
                "换热管中心距 S": "31",
                "分程隔板两侧相邻管中心距（竖直）": "40",
                "分程隔板两侧相邻管中心距（水平）": "46",
                "换热管排列方式": "正三角形",
                "折流板切口方向": "垂直左右",
            }
        )

        kwargs = build_ad_kwargs_from_editor(self.editor)

        self.assertIsNotNone(kwargs)
        self.assertEqual(kwargs["S"], 32.0)
        self.assertEqual(kwargs["Snv"], 44.0)
        self.assertEqual(kwargs["Snh"], 50.0)
        self.assertEqual(kwargs["Ang"], 45.0)

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


class RepeatedSaveTests(unittest.TestCase):
    def test_direct_save_after_each_tube_pass_change_uses_new_layout(self):
        from modules.buguan.buguan_ziyong.My_Piping import TubeLayoutEditor
        from modules.buguan.buguan_ziyong.tube_pass.adapter import (
            normalize_local_tube_pass_cat,
        )

        class Header:
            def currentIndex(self):
                return 1

        class SaveHarness:
            save_data = TubeLayoutEditor.save_data

            def __init__(self):
                self.header = Header()
                self.pass_count = "2"
                self.tube_pass_form_value = "2.1"
                self.tube_pass_form_combo = object()
                self.input_json = {"LB_Tubeform": "2.1"}
                self.left_data_pd = {
                    "换热管中心距 S": "32",
                    "分程隔板两侧相邻管中心距（竖直）": "44",
                    "分程隔板两侧相邻管中心距（水平）": "50",
                    "换热管排列方式": "转角正方形",
                    "折流板切口方向": "水平上下",
                }
                self.layout_calls = 0
                self.saved = []
                self.messages = []
                self._set_layout("2.1")
                self.layout_calls = 0

            def _set_layout(self, form):
                cat = normalize_local_tube_pass_cat(form)
                compute_kwargs = {
                    key: float(SAVED_INPUT[key])
                    for key in (
                        "D", "Snv", "Snh", "Wx0", "Wx1", "Wy0", "Wy1", "Wy2", "S", "d"
                    )
                }
                compute_kwargs.update(Cat=cat, Layout="S", Arr=45, Cut="HUD")
                self._local_compute_kwargs = compute_kwargs
                self._local_raw_calc = compute_centers(**compute_kwargs)
                self.current_centers = list(self._local_raw_calc["XY"])
                self.input_json = {"LB_Tubeform": form}

            def get_selected_tube_pass_form(self):
                return self.tube_pass_form_value

            def get_tube_pass_count(self):
                return self.pass_count

            def load_tube_pass_images(self, _combo, pass_count):
                self.tube_pass_form_value = {
                    "4": "4.1",
                    "6": "6.1",
                    "8": "8a.1",
                    "10": "10a.1",
                }[pass_count]

            def on_buguan_bt_click(self):
                self.layout_calls += 1
                self._set_layout(self.tube_pass_form_value)

            def check_before_save(self):
                return True

            def actual_save_operation(self, page_index, silent=False):
                if page_index == 1:
                    results = {}
                    piping_calculations.apply_ad_to_calc_results(self, results)
                    self.saved.append(
                        (len(self.current_centers), results["管板分程处面积Ad"])
                    )

            def _notify_save_success_ui(self, message, auto_clear=True):
                self.messages.append(message)

            def _ensure_tube_pass_layout_before_save(self):
                return TubeLayoutEditor._ensure_tube_pass_layout_before_save(self)

        editor = SaveHarness()
        for pass_count in ("4", "6", "8"):
            editor.pass_count = pass_count
            editor.save_data()

        self.assertEqual(editor.layout_calls, 3)
        self.assertEqual([count for count, _ad in editor.saved], [52, 50, 48])
        self.assertEqual(len({ad for _count, ad in editor.saved}), 3)

        # 管程未改时，直接保存手工删管后的状态，不重新满布。
        editor.current_centers.pop(0)
        editor.save_data()
        self.assertEqual(editor.layout_calls, 3)
        self.assertEqual(editor.saved[-1][0], 47)

        # 自动布管被预检挡住时，不能把旧管孔的结果当作新管程保存。
        editor.pass_count = "10"
        editor.on_buguan_bt_click = lambda: None
        saved_count = len(editor.saved)
        editor.save_data()
        self.assertEqual(len(editor.saved), saved_count)
        self.assertEqual(editor.messages[-1], "管程变更后布管未完成，本次未保存。")


if __name__ == "__main__":
    unittest.main()
