"""支持板切口参数保存规则的回归测试。"""

import unittest
from unittest.mock import patch

from modules.buguan.buguan_ziyong import My_Piping as piping


class _FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, _sql):
        pass


class _FakeConnection:
    open = True

    def cursor(self):
        return _FakeCursor()

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.open = False


class _Editor:
    productID = "SUPPORT-PLATE-001"
    heat_exchanger = "AES"
    tube_pass_form_value = "2.1"
    impingement_plate_thick = 200
    _normalize_support_plate_cut_params = staticmethod(
        piping.TubeLayoutEditor._normalize_support_plate_cut_params
    )

    @staticmethod
    def _read_param_table_value(_param_name):
        return ""


class SupportPlateSaveNormalizationTests(unittest.TestCase):
    def test_support_plate_saves_zero_cut_rate_and_radius_as_cut_distance(self):
        tube_data = [
            {"参数名": "管程程数", "参数值": "2", "单位": ""},
            {"参数名": "壳程程数", "参数值": "2", "单位": ""},
            {"参数名": "折流板类型", "参数值": "支持板", "单位": ""},
            {"参数名": "折流/支持板外径", "参数值": "569", "单位": "mm"},
            {"参数名": "折流板切口方向", "参数值": "水平上下", "单位": ""},
            {"参数名": "折流板要求切口率", "参数值": "25", "单位": "%"},
            {
                "参数名": "折流板切口与中心线间距a",
                "参数值": "100",
                "单位": "mm",
            },
        ]

        with patch.object(
            piping, "create_product_connection", return_value=_FakeConnection()
        ):
            statements = piping.TubeLayoutEditor.build_sql_for_tube(
                _Editor(), tube_data
            )

        saved_sql = "\n".join(statements)
        self.assertIn(
            "VALUES ('SUPPORT-PLATE-001', '折流板要求切口率', '0', '%')",
            saved_sql,
        )
        self.assertIn(
            "VALUES ('SUPPORT-PLATE-001', '折流板切口与中心线间距a', '284.5', 'mm')",
            saved_sql,
        )
        self.assertIn(
            "VALUES ('SUPPORT-PLATE-001', '折流板切口方向', '水平上下', NULL)",
            saved_sql,
        )


if __name__ == "__main__":
    unittest.main()
