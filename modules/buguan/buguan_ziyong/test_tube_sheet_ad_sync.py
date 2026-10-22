# -*- coding: utf-8 -*-
"""管板分程处面积 Ad 写回元件定义的回归测试。"""
import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QMainWindow

try:
    from modules.buguan.buguan_ziyong import tube_sheet_ad_sync as ad_sync
except ImportError:
    ad_sync = None

from modules.buguan.buguan_ziyong import My_Piping as piping


PARAMETER_NAME = "管板分程处面积 Ad"


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.result = []
        self.rowcount = 0

    def execute(self, query, args=None):
        normalized = " ".join(query.split())
        args = tuple(args or ())
        self.connection.executed.append((normalized, args))
        self.rowcount = 0

        if normalized.startswith("SELECT 元件附加参数ID, 参数值"):
            product_id, element_name, parameter_name = args
            self.result = [
                {
                    "元件附加参数ID": row["元件附加参数ID"],
                    "参数值": row["参数值"],
                }
                for row in self.connection.rows
                if row["产品ID"] == product_id
                and row["元件名称"] == element_name
                and row["参数名称"] == parameter_name
            ]
            return

        if normalized.startswith("UPDATE 产品设计活动表_元件附加参数表"):
            new_value, product_id, parameter_id = args
            for row in self.connection.rows:
                if (
                    row["产品ID"] == product_id
                    and row["元件附加参数ID"] == parameter_id
                ):
                    row["参数值"] = new_value
                    self.rowcount += 1
            self.result = []
            return

        raise AssertionError(f"Unexpected SQL: {normalized}")

    def fetchall(self):
        return list(self.result)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self, value=None):
        self.rows = []
        if value is not None:
            self.rows.append(
                {
                    "元件附加参数ID": 17,
                    "产品ID": "PD-AD-TEST",
                    "元件ID": 8,
                    "元件名称": "固定管板",
                    "参数名称": PARAMETER_NAME,
                    "参数值": value,
                    "参数单位": "mm²",
                }
            )
        self.executed = []
        self.commit_count = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commit_count += 1


class Confirmation:
    def __init__(self, answer):
        self.answer = answer
        self.requests = []

    def __call__(self, calculated_value, user_value):
        self.requests.append((calculated_value, user_value))
        return self.answer


class SaveEditor(piping.TubeLayoutEditor):
    """保留真实布管保存编排，只替换无关的坐标、文件和 SQL 构建工作。"""

    def __init__(self, connection):
        QMainWindow.__init__(self)
        self.productID = "PD-AD-TEST"
        self.has_piped = True
        self.heat_exchanger = "AEU"
        self._current_centers = []
        self.current_centers_lagan = []
        self.slipway_centers = []
        self._test_connection = connection
        self._active_sql_conn = None
        self.executed_sql = []

    def _prune_slipway_centers_overlapping_current(self):
        pass

    def get_current_tube_hole_data(self):
        return []

    def get_current_tube_data(self):
        return []

    def save_current_centers_to_product_json(self):
        pass

    @contextmanager
    def _sql_connection_scope(self):
        previous = self._active_sql_conn
        self._active_sql_conn = self._test_connection
        try:
            yield self._test_connection
        finally:
            self._active_sql_conn = previous

    def execute_sql(self, sql, fetch=False, connection=None):
        self.executed_sql.append(sql)

    def build_sql_for_radial_holes(self):
        return []

    def build_sql_for_tube_hole(self, data):
        return []

    def build_sql_for_tube_hole_present(self, data):
        return []

    def build_sql_for_tube(self, data):
        return []

    def build_sql_for_component(self):
        pass

    def build_sql_for_screw_ring(self):
        pass

    def build_sql_for_cross_pipes(self):
        return []

    def update_buguan_quantity(self):
        pass


class TubeSheetAdSyncTests(unittest.TestCase):
    def sync(self, stored_value, calculated_value, answer=False):
        self.assertIsNotNone(ad_sync, "Ad 同步模块尚未实现")
        connection = FakeConnection(stored_value)
        confirmation = Confirmation(answer)
        result = ad_sync.sync_tube_sheet_ad(
            connection,
            "PD-AD-TEST",
            calculated_value,
            confirmation,
        )
        return result, connection, confirmation

    def test_program_recommendation_is_replaced_without_prompt(self):
        result, connection, confirmation = self.sync("程序推荐", 123.4564)

        self.assertEqual(result, "updated_recommended")
        self.assertEqual(connection.rows[0]["参数值"], "123.456")
        self.assertEqual(confirmation.requests, [])
        self.assertEqual(connection.commit_count, 1)

    def test_exactly_five_percent_keeps_user_value(self):
        result, connection, confirmation = self.sync("95", 100)

        self.assertEqual(result, "kept_within_tolerance")
        self.assertEqual(connection.rows[0]["参数值"], "95")
        self.assertEqual(confirmation.requests, [])
        self.assertEqual(connection.commit_count, 0)

    def test_tolerance_uses_same_three_decimal_value_written_to_component(self):
        result, connection, confirmation = self.sync("95", 100.0004)

        self.assertEqual(result, "kept_within_tolerance")
        self.assertEqual(connection.rows[0]["参数值"], "95")
        self.assertEqual(confirmation.requests, [])

    def test_difference_over_five_percent_keeps_value_when_user_declines(self):
        result, connection, confirmation = self.sync("94.9", 100, answer=False)

        self.assertEqual(result, "kept_by_user")
        self.assertEqual(connection.rows[0]["参数值"], "94.9")
        self.assertEqual(confirmation.requests, [("100.0", "94.9")])
        self.assertEqual(connection.commit_count, 0)

    def test_difference_over_five_percent_updates_when_user_accepts(self):
        result, connection, confirmation = self.sync("106", 100, answer=True)

        self.assertEqual(result, "updated_by_user")
        self.assertEqual(connection.rows[0]["参数值"], "100.0")
        self.assertEqual(confirmation.requests, [("100.0", "106")])
        self.assertEqual(connection.commit_count, 1)

    def test_both_zero_keeps_user_value_without_prompt(self):
        result, connection, confirmation = self.sync("0", 0)

        self.assertEqual(result, "kept_within_tolerance")
        self.assertEqual(connection.rows[0]["参数值"], "0")
        self.assertEqual(confirmation.requests, [])

    def test_zero_calculation_prompts_for_positive_user_value(self):
        result, connection, confirmation = self.sync("10", 0, answer=True)

        self.assertEqual(result, "updated_by_user")
        self.assertEqual(connection.rows[0]["参数值"], "0.0")
        self.assertEqual(confirmation.requests, [("0.0", "10")])

    def test_missing_component_parameter_is_not_inserted(self):
        self.assertIsNotNone(ad_sync, "Ad 同步模块尚未实现")
        connection = FakeConnection()
        confirmation = Confirmation(True)

        result = ad_sync.sync_tube_sheet_ad(
            connection,
            "PD-AD-TEST",
            100,
            confirmation,
        )

        self.assertEqual(result, "missing")
        self.assertEqual(connection.rows, [])
        self.assertEqual(confirmation.requests, [])
        self.assertEqual(connection.commit_count, 0)


class TubeSheetAdSaveIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_successful_tube_layout_save_syncs_calculated_ad_after_calc_sql(self):
        connection = FakeConnection("程序推荐")
        editor = SaveEditor(connection)
        ad_result = {
            "supported": True,
            "message": "ok",
            "Ad": 321.9874,
            "A0": 400.0,
            "A1": 70.0,
            "A2": 8.0126,
            "Ntt": 120,
        }
        try:
            with patch.object(
                piping.piping_calculations,
                "build_sql_for_u_tube_calc",
                return_value=["CALCULATION SQL"],
            ), patch(
                "modules.buguan.buguan_ziyong.tube_pass.ad_calculation.compute_ad_from_editor",
                return_value=ad_result,
            ):
                editor.actual_save_operation(1)

            self.assertEqual(editor.executed_sql, ["CALCULATION SQL"])
            self.assertEqual(connection.rows[0]["参数值"], "321.987")
        finally:
            editor.close()
            editor.deleteLater()

    def test_silent_cascade_save_does_not_sync_component_ad(self):
        connection = FakeConnection("程序推荐")
        editor = SaveEditor(connection)
        ad_result = {
            "supported": True,
            "message": "ok",
            "Ad": 321.9874,
            "A0": 400.0,
            "A1": 70.0,
            "A2": 8.0126,
            "Ntt": 120,
        }
        try:
            with patch.object(
                piping.piping_calculations,
                "build_sql_for_u_tube_calc",
                return_value=["CALCULATION SQL"],
            ), patch(
                "modules.buguan.buguan_ziyong.tube_pass.ad_calculation.compute_ad_from_editor",
                return_value=ad_result,
            ):
                editor.actual_save_operation(1, silent=True)

            self.assertEqual(editor.executed_sql, ["CALCULATION SQL"])
            self.assertEqual(connection.rows[0]["参数值"], "程序推荐")
            self.assertEqual(connection.commit_count, 0)
        finally:
            editor.close()
            editor.deleteLater()

    def test_confirmation_uses_requested_message(self):
        editor = SaveEditor(FakeConnection("94"))
        try:
            with patch.object(
                piping.QMessageBox,
                "question",
                return_value=piping.QMessageBox.No,
            ) as question:
                accepted = editor._confirm_tube_sheet_ad_update("100.0", "94")

            self.assertFalse(accepted)
            self.assertEqual(
                question.call_args.args[2],
                "软件计算“管板分程处面积 Ad”的数值为100.0，"
                "与在元件定义中自定义的数值差距超过5%，是否更新元件定义？",
            )
        finally:
            editor.close()
            editor.deleteLater()


if __name__ == "__main__":
    unittest.main()
