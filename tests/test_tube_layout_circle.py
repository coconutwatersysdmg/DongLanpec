# -*- coding: utf-8 -*-
"""Exercise DL loading and diameter changes without writing to a product database."""
import contextlib
import io
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTabWidget, QWidget,
)

from modules.buguan.buguan_ziyong import My_Piping as piping
from modules.buguan.buguan_ziyong.sheet_form_page import SheetFormPage


class ProductConnection:
    """Read-only database fixture with the U-tube defaults found in the component DB."""
    open = True

    def __init__(self, diameter="1300", saved_di="1144", saved_dl="1128.0"):
        self.diameter = diameter
        self.params = [
            {"参数名": name, "参数值": value, "单位": "mm"}
            for name, value in (
                ("是否以外径为基准", "否"), ("公称直径 DN", "1200"),
                ("壳体内直径 Dis", saved_di), ("管箱内直径 Dit", saved_di),
                ("布管限定圆 DL", saved_dl), ("换热管外径 do", "25"),
                ("换热管排列方式", "转角正方形"),
            )
        ]

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, query, args=None):
        if not query.lstrip().upper().startswith("SELECT"):
            raise AssertionError("Regression tests must not modify product data")
        self.result = []
        if "SELECT 产品型式" in query:
            self.result = [{"产品型式": "AEU"}]
        elif "FROM 产品设计活动表_布管参数表" in query:
            self.result = self.params
        elif "FROM 产品设计活动表_设计数据表" in query:
            self.result = [{"壳程数值": self.diameter, "管程数值": self.diameter}]
        elif "FROM 产品设计活动表_通用数据表" in query:
            self.result = [{"数值": "否"}]

    def fetchone(self):
        return self.result[0] if self.result else None

    def fetchall(self):
        return self.result

    def close(self):
        pass


class CircleEditor(piping.TubeLayoutEditor):
    """Keep real loading/formula methods; omit unrelated drawing and database work."""
    def __init__(self):
        QMainWindow.__init__(self)
        self.productID = "circle-regression"
        self.heat_exchanger = "AEU"
        self.param_table = QTableWidget(0, 4)
        self.original_param_values = {}
        self.modified_rows = set()
        self.header = QTabWidget()
        self.stacked_widget = QStackedWidget()
        for _ in range(4):
            self.header.addTab(QWidget(), "test")
            self.stacked_widget.addWidget(QWidget())
        for name in (
            "update_cross_pipe_button_state", "update_screw_ring_button_state",
            "hide_specific_params", "initial_operation", "load_initial_tube_num",
            "update_total_holes_count", "update_diameter_visibility_by_outer_flag",
            "renumber_visible_rows", "update_lagan_standard_from_params",
            "setup_parameter_listeners", "update_baffle_diameter",
            "update_tube_center_distance", "update_divider_position_and_size",
        ):
            setattr(self, name, lambda *args, **kwargs: None)

    def setup_parameters(self, params, **kwargs):
        self.param_table.setRowCount(len(params))
        for row, param in enumerate(params):
            self.param_table.setItem(row, 1, QTableWidgetItem(param["参数名"]))
            self.param_table.setItem(row, 2, QTableWidgetItem(str(param["参数值"])))

    def value(self, name):
        for row in range(self.param_table.rowCount()):
            if self.param_table.item(row, 1).text() == name:
                return float(self.param_table.item(row, 2).text())
        raise AssertionError(f"Missing parameter: {name}")


class TubeLayoutCircleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = CircleEditor()
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()

    def tearDown(self):
        QTest.qWait(220)
        self.editor.close()
        self.editor.deleteLater()
        self.output.__exit__(None, None, None)

    def load_product(self, **kwargs):
        with patch.object(piping, "create_product_connection",
                          side_effect=lambda: ProductConnection(**kwargs)):
            self.editor.load_initial_data()
            QTest.qWait(220)

    def test_aeu_load_recalculates_copied_dl_when_design_diameter_changes(self):
        self.load_product()
        self.assertEqual(self.editor.value("公称直径 DN"), 1300)
        self.assertEqual(self.editor.value("壳体内直径 Dis"), 1300)
        self.assertEqual(self.editor.value("布管限定圆 DL"), 1284)

    def test_unchanged_diameter_preserves_saved_custom_dl(self):
        self.load_product(diameter="1200", saved_di="1200", saved_dl="1100")
        self.assertEqual(self.editor.value("布管限定圆 DL"), 1100)

    def test_dn_alignment_recalculates_dl_despite_loading_preservation_flags(self):
        self.editor.setup_parameters(ProductConnection().params)
        self.editor.param_table.item(1, 2).setText("1300")
        self.editor._suppress_open_s_dl_autoupdate = True
        self.editor._user_override_tube_layout_circle_dl = True
        self.editor.update_DN_Di()
        QTest.qWait(220)
        self.assertEqual(self.editor.value("布管限定圆 DL"), 1284)

    def test_numeric_format_change_does_not_discard_custom_dl(self):
        self.editor.setup_parameters(
            ProductConnection(saved_di="1300", saved_dl="1200").params
        )
        self.editor.param_table.item(1, 2).setText("1300.0")
        self.editor._user_override_tube_layout_circle_dl = True
        self.editor.update_DN_Di()
        QTest.qWait(220)
        self.assertEqual(self.editor.value("布管限定圆 DL"), 1200)
        self.assertTrue(self.editor._user_override_tube_layout_circle_dl)

    def test_outer_diameter_base_keeps_actual_inner_diameter(self):
        self.editor.setup_parameters(ProductConnection().params)
        self.editor.param_table.item(0, 2).setText("是")
        self.editor.param_table.item(1, 2).setText("1300")
        self.editor.update_DN_Di()
        self.assertEqual(self.editor.value("壳体内直径 Dis"), 1144)
        self.assertEqual(self.editor.value("布管限定圆 DL"), 1128)

    def test_dn_alignment_keeps_selected_plate_node_constraint(self):
        self.editor.setup_parameters(ProductConnection().params)
        self.editor.param_table.item(1, 2).setText("1300")
        self.editor.param_table.setRowHidden(2, True)
        self.editor.param_table.setRowHidden(3, True)
        self.editor.is_suitable_tube_sheet = True
        self.editor.tube_sheet_params_snapshot = {
            "plate_type": "e_a", "main_category": "e", "node_name": "a",
            "params": [("d3", "100")],
        }
        self.editor._user_override_tube_layout_circle_dl = True
        self.editor.update_DN_Di()
        QTest.qWait(220)
        self.assertEqual(self.editor.value("布管限定圆 DL"), 1100)

    def test_aeu_default_plate_association_uses_a_type(self):
        self.assertEqual(SheetFormPage._resolve_plate_type_rule(None, "AEU"), ("a", True))

    def test_e_g_node_links_r2_and_recalculates_after_parameter_edit(self):
        self.editor.heat_exchanger = "AEM"
        self.editor.setup_parameters(ProductConnection(
            diameter="700", saved_di="700", saved_dl="684"
        ).params)
        self.editor.param_table.item(1, 2).setText("700")
        class Page:
            radius = "12"
            def get_current_tube_form_data(page):
                return [("管板类型", "e_g"), ("R1", "12"), ("R2", page.radius),
                        ("h1", "1.5"), ("h2", "60"), ("α", "2"), ("p", "3"), ("e", "0.5")]
        page = Page()
        self.editor.sheet_form_page = page
        self.editor._sync_tube_sheet_snapshot_and_update_dl()
        self.assertTrue(self.editor.is_suitable_tube_sheet)
        self.assertEqual(self.editor.value("布管限定圆 DL"), 676)
        page.radius = "15"
        self.editor._sync_tube_sheet_snapshot_and_update_dl()
        self.assertEqual(self.editor.value("布管限定圆 DL"), 670)

    def test_e_g_constraint_honors_other_clearance_and_manual_dl(self):
        self.editor.heat_exchanger = "AEM"
        self.editor.setup_parameters(ProductConnection(saved_di="700", saved_dl="650").params)
        self.editor.param_table.item(1, 2).setText("700")
        self.editor.is_suitable_tube_sheet = True
        self.editor.tube_sheet_params_snapshot = {
            "plate_type": "e_g", "main_category": "e", "node_name": "g",
            "params": [("R2", "2")],
        }
        self.editor.update_tube_layout_circle_dl()
        self.assertEqual(self.editor.value("布管限定圆 DL"), 684)
        self.editor._user_override_tube_layout_circle_dl = True
        self.editor.param_table.item(4, 2).setText("650")
        self.editor.update_tube_layout_circle_dl()
        self.assertEqual(self.editor.value("布管限定圆 DL"), 650)

    def test_explicit_plate_edit_releases_loaded_dl_but_tab_refresh_preserves_it(self):
        self.editor.heat_exchanger = "AEM"
        self.editor.setup_parameters(ProductConnection(saved_di="700", saved_dl="684").params)
        self.editor.param_table.item(1, 2).setText("700")
        class Page:
            plate = "e_g"
            def get_current_tube_form_data(page):
                return [("管板类型", page.plate), ("R2", "12")]
        page = Page()
        self.editor.sheet_form_page = page
        self.editor._suppress_open_s_dl_autoupdate = True
        self.editor._user_override_tube_layout_circle_dl = True
        self.editor._sync_tube_sheet_snapshot_and_update_dl()
        self.assertEqual(self.editor.value("布管限定圆 DL"), 684)
        self.editor._sync_tube_sheet_snapshot_and_update_dl(parameters_changed=True)
        self.assertEqual(self.editor.value("布管限定圆 DL"), 676)
        page.plate = "a_a"
        self.editor._sync_tube_sheet_snapshot_and_update_dl(parameters_changed=True)
        self.assertFalse(self.editor.is_suitable_tube_sheet)
        self.assertEqual(self.editor.value("布管限定圆 DL"), 684)

    def test_nen_c_node_uses_distance_three_instead_of_angle_thirty(self):
        self.editor.heat_exchanger = "NEN"
        self.editor.setup_parameters(ProductConnection(saved_di="1200", saved_dl="1100").params)
        self.editor.is_suitable_tube_sheet = True
        for params in (
            list(zip("abcdefgh", ("60", "2", "2", "1", "30", "2", "4", "3"))),
            [("α1", "60"), ("b", "2"), ("p1", "2"), ("d1", "1"),
             ("α2", "30"), ("R", "2"), ("n", "4"), ("e", "3")],
        ):
            with self.subTest(params=params):
                self.editor.tube_sheet_params_snapshot = {
                    "plate_type": "b_c", "main_category": "b", "node_name": "c", "params": params,
                }
                self.editor.update_tube_layout_circle_dl()
                # min(1200 - 4*(1+sqrt(17)) - 6, 1200 - 16), rounded to 0.1 mm.
                self.assertEqual(self.editor.value("布管限定圆 DL"), 1173.5)

    def test_nen_e_node_uses_two_l_minus_q_formula(self):
        self.editor.heat_exchanger = "NEN"
        self.editor.setup_parameters(ProductConnection(saved_di="1200", saved_dl="1100").params)
        self.editor.is_suitable_tube_sheet = True
        self.editor.tube_sheet_params_snapshot = {
            "plate_type": "b_e", "main_category": "b", "node_name": "e",
            "params": [("R2", "2"), ("e", "3"), ("R4", "2"),
                       ("d2", "20"), ("α", "45")],
        }

        self.editor.update_tube_layout_circle_dl()

        # min(1190, 1216.3..., 1184) = 1184; q-l would incorrectly produce 1148.3.
        self.assertEqual(self.editor.value("布管限定圆 DL"), 1184)

    def test_other_supported_plate_nodes_use_renamed_formula_parameters(self):
        self.editor.setup_parameters(ProductConnection(saved_di="1200", saved_dl="1100").params)
        self.editor.is_suitable_tube_sheet = True
        cases = (
            ("NEN", "b_a", {"x1": "1", "x2": "1", "α": "60"}, 1184),
            ("NEN", "b_d", {"e": "3", "R3": "10", "R2": "12"}, 1170),
            ("NEN", "b_h", {"e": "3", "R3": "10", "R5": "12"}, 1170),
            ("AEM", "e_a", {"d3": "20"}, 1160),
            ("AEM", "e_b", {"b": "20", "e": "3", "R1": "2"}, 1154),
            ("BEM", "e_c", {"b": "20", "e": "3", "R1": "2"}, 1154),
            ("AEM", "e_d", {"b": "2", "d1": "1", "e": "3", "α1": "45", "α2": "45"}, 1182.3),
            ("BEM", "e_e", {"b": "2", "d2": "1", "e": "3", "α1": "45", "α2": "45"}, 1182.3),
            ("BEM", "e_f", {"R1": "10", "e": "3"}, 1154),
        )
        for hx, plate, params, expected in cases:
            with self.subTest(hx=hx, plate=plate):
                self.editor.heat_exchanger = hx
                main, node = plate.split("_")
                self.editor.tube_sheet_params_snapshot = {
                    "plate_type": plate, "main_category": main, "node_name": node,
                    "params": list(params.items()),
                }
                self.editor.update_tube_layout_circle_dl()
                self.assertEqual(self.editor.value("布管限定圆 DL"), expected)


if __name__ == "__main__":
    unittest.main()
