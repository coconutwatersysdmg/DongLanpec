"""U 型管多管程布管计算结果的保存回归测试。"""

import unittest
from unittest.mock import patch

from modules.buguan.buguan_ziyong import piping_calculations


class _FakeCursor:
    def __init__(self):
        self._one = None
        self._many = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        self._one = None
        self._many = []
        if "FROM 产品设计活动表_布管参数表" in sql:
            if params and len(params) > 1:
                param_name = params[1]
            else:
                param_name = next(
                    (
                        name
                        for name in (
                            "管程程数",
                            "管程分程形式",
                            "折流板类型",
                            "换热管排列方式",
                            "换热管外径 do",
                            "折流板切口方向",
                            "A型板切口与中心线间距a",
                            "B型板切口与中心线间距b",
                        )
                        if name in sql
                    ),
                    None,
                )
            values = {
                "换热管中心距 S": "32",
                "分程隔板两侧相邻管中心距（竖直）": "44",
                "分程隔板两侧相邻管中心距（水平）": "50",
                "管程程数": self.connection.tube_pass_count,
                "管程分程形式": self.connection.tube_pass_form,
                "折流板类型": "单弓形折流板",
                "换热管排列方式": "正方形",
                "换热管外径 do": "25",
                "折流板切口方向": "水平上下",
                "A型板切口与中心线间距a": "10",
                "B型板切口与中心线间距b": "20",
            }
            value = values.get(param_name)
            self._one = {"参数值": value} if value is not None else None
        elif "FROM 产品设计活动表_布管结果表" in sql:
            self._one = {"value": "50"}
        elif "FROM 产品设计活动表_布管数量表_水平" in sql:
            self._many = [
                {"管孔数量（上）": "2", "管孔数量（下）": "2", "line_no": 1}
            ]
        elif "FROM 产品设计活动表_布管元件表" in sql:
            self._many = []
        elif "FROM 产品设计活动表_布管数量表_显示" in sql:
            self._many = [
                {"管孔数量（上）": "2", "管孔数量（下）": "2", "line_no": 1}
            ]

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many


class _FakeConnection:
    def __init__(self, tube_pass_count=None, tube_pass_form=None):
        self.tube_pass_count = tube_pass_count
        self.tube_pass_form = tube_pass_form
        self.open = True

    def cursor(self, *_args, **_kwargs):
        cursor = _FakeCursor()
        cursor.connection = self
        return cursor

    def close(self):
        self.open = False


class _Editor:
    productID = "UT-MULTI-PASS"
    current_centers = [(-20.0, -10.0), (-20.0, 10.0), (20.0, -10.0), (20.0, 10.0)]
    current_centers_lagan = list(current_centers)


class UTubeCalcPersistenceTests(unittest.TestCase):
    def test_all_u_product_paths_generate_calc_result_inserts_for_new_pass_counts(self):
        for product_type in ("AEU", "BEU", "AKU", "BKU"):
            for tube_pass_count in ("8", "10", "12"):
                with self.subTest(
                    product_type=product_type, tube_pass_count=tube_pass_count
                ):
                    editor = _Editor()
                    editor.heat_exchanger = product_type
                    connection = _FakeConnection(tube_pass_count)

                    with patch.object(
                        piping_calculations,
                        "apply_ad_to_calc_results",
                        side_effect=lambda _editor, results: results.update(
                            {"管板分程处面积Ad": "123.456"}
                        ),
                    ):
                        statements = piping_calculations.build_sql_for_u_tube_calc(
                            editor, lambda: connection
                        )

                    self.assertIsNotNone(statements)
                    self.assertTrue(statements[0].startswith("DELETE FROM"))
                    inserts = [
                        sql for sql in statements if sql.startswith("INSERT INTO")
                    ]
                    self.assertGreater(len(inserts), 0)
                    self.assertTrue(
                        any("'U型管弯曲直径', '40.0'" in sql for sql in inserts)
                    )
                    self.assertTrue(
                        any(
                            "'沿水平隔板槽一侧的排管根数', '2'" in sql
                            for sql in inserts
                        )
                    )
                    self.assertTrue(
                        any(
                            "'管板分程处面积Ad', '123.456'" in sql
                            for sql in inserts
                        )
                    )

    def test_non_u_product_paths_generate_calc_result_inserts_for_new_pass_forms(self):
        product_types = ("AES", "BES", "AEM", "BEM", "NEN", "NEN(H)")
        for product_type in product_types:
            for tube_pass_form in ("8a.1", "10a.1", "12a.1"):
                with self.subTest(
                    product_type=product_type, tube_pass_form=tube_pass_form
                ):
                    editor = _Editor()
                    editor.heat_exchanger = product_type
                    connection = _FakeConnection(tube_pass_form=tube_pass_form)

                    with patch.object(
                        piping_calculations,
                        "apply_ad_to_calc_results",
                        side_effect=lambda _editor, results: results.update(
                            {"管板分程处面积Ad": "123.456"}
                        ),
                    ):
                        statements = (
                            piping_calculations.build_sql_for_floating_head_calc(
                                editor, lambda: connection
                            )
                        )

                    self.assertIsNotNone(statements)
                    self.assertTrue(statements[0].startswith("DELETE FROM"))
                    inserts = [
                        sql for sql in statements if sql.startswith("INSERT INTO")
                    ]
                    self.assertGreater(len(inserts), 0)
                    self.assertTrue(
                        any(
                            "'管板分程处面积Ad', '123.456'" in sql
                            for sql in inserts
                        )
                    )


if __name__ == "__main__":
    unittest.main()
