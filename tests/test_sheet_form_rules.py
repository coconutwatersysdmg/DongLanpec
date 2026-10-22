"""管板型式限制及新旧参数代号的回归测试，不连接真实数据库。"""
import contextlib
import io
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QWidget
from modules.buguan.buguan_ziyong import sheet_form_page as forms


LEGACY_C = dict(zip("abcdefgh", ("60", "2", "2", "1", "30", "2", "4", "3")))


class SheetFormRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        # 本组专门检查延迟恢复之前的状态，避免计时器在控件销毁后触发。
        timer = patch.object(forms.QTimer, "singleShot", return_value=None)
        timer.start()
        self.addCleanup(timer.stop)
        self.parent = QWidget()
        self.parent.productID = "sheet-rule-test"
        self.parent.heat_exchanger = "NEN"
        self.db = patch.object(forms.SheetFormPage, "_get_heat_exchanger_from_product_db",
                               side_effect=lambda pid: self.parent.heat_exchanger)
        self.db.start()
        self.params = patch.object(forms, "get_plate_form_params", return_value={"e": "3"})
        self.params.start()
        self.page = None

    def tearDown(self):
        if self.page is not None:
            self.page.close()
            self.page.deleteLater()
        self.parent.deleteLater()
        self.params.stop()
        self.db.stop()
        self.output.__exit__(None, None, None)

    def test_fixed_products_are_locked_before_delayed_restore(self):
        for hx, index in (("AES", 0), ("BES", 0), ("AKU", 0), ("BKU", 0),
                          ("NEN", 1), ("NEN(H)", 1), ("AEM", 4), ("BEM", 4)):
            with self.subTest(hx=hx):
                self.parent.heat_exchanger = hx
                page = forms.SheetFormPage(self.parent)
                try:
                    self.assertEqual(page.sheet_form_connection_type_combo.currentIndex(), index)
                    self.assertFalse(page.sheet_form_connection_type_combo.isEnabled())
                    self.assertTrue(page.image_scroll_area.isEnabled())
                finally:
                    page.deleteLater()

    def test_fixed_product_rejects_wrong_type_but_allows_node_changes(self):
        self.page = forms.SheetFormPage(self.parent)
        self.page._apply_plate_type_rule()
        self.page._handle_image_click(None, 2)
        self.assertEqual(dict(self.page.get_current_tube_form_data())["管板类型"], "b_c")
        self.page.sheet_form_connection_type_combo.setCurrentIndex(0)
        self.assertEqual(self.page.sheet_form_connection_type_combo.currentIndex(), 1)
        self.assertEqual(dict(self.page.get_current_tube_form_data())["管板类型"], "b_c")
        self.page._handle_image_click(None, 3)
        self.assertEqual(dict(self.page.get_current_tube_form_data())["管板类型"], "b_d")

    def test_u_tube_products_allow_type_changes_after_toggle(self):
        for hx in ("AEU", "BEU"):
            self.parent.heat_exchanger = hx
            self.page = forms.SheetFormPage(self.parent)
            self.page._apply_plate_type_rule()
            self.page._on_sheet_form_toggle_readonly(False)
            self.assertFalse(self.page.sheet_form_connection_type_combo.isEnabled())
            self.page._on_sheet_form_toggle_readonly(True)
            self.page.sheet_form_connection_type_combo.setCurrentIndex(1)
            self.assertTrue(self.page.sheet_form_connection_type_combo.isEnabled())
            self.assertTrue(self.page.sheet_form_current_images[0].endswith("b_a.png"))
            self.page.deleteLater()
            self.page = None

    def test_legacy_c_keeps_angle_and_distance_separate(self):
        actual = forms._normalize_plate_form_params("b_c", LEGACY_C)
        self.assertEqual(actual["α2"], "30")
        self.assertEqual(actual["e"], "3")
        self.assertEqual(actual["n"], "4")
        self.assertEqual(LEGACY_C["e"], "30")

    def test_legacy_e_b_does_not_reuse_old_b_as_new_b(self):
        legacy = dict(zip(("a", "b", "c", "d", "e", "f", "g", "h", "j", "K"),
                          ("2", "1", "1", "2", "2", "2", "1", "30", "3", "δ")))
        actual = forms._normalize_plate_form_params("e_b", legacy)
        self.assertEqual(actual["b"], "2")
        self.assertEqual(actual["d1"], "1")
        self.assertEqual(actual["e"], "3")

    def test_legacy_e_g_uses_component_database_symbol_layout(self):
        legacy = {
            "a": "12", "b": "12", "c1": "1.5", "c2": "25",
            "d": "60", "e": "2", "f": "3",
        }

        actual = forms._normalize_plate_form_params("e_g", legacy)

        self.assertEqual(
            {key: actual[key] for key in ("R1", "R2", "h1", "h2", "α", "p", "e")},
            {"R1": "12", "R2": "12", "h1": "1.5", "h2": "25",
             "α": "60", "p": "2", "e": "3"},
        )

    def test_canonical_custom_values_are_preserved(self):
        canonical = {"α1": "60", "b": "2", "p1": "2", "d1": "1", "α2": "30",
                     "R": "2", "n": "4", "e": "5", "p2": "2", "d2": "1"}
        self.assertEqual(forms._normalize_plate_form_params("b_c", canonical), canonical)

    def test_editing_node_parameter_synchronizes_parent_snapshot(self):
        self.parent.heat_exchanger = "AEM"
        self.page = forms.SheetFormPage(self.parent)
        self.page._handle_image_click(None, 6)
        changes = []
        self.parent._sync_tube_sheet_snapshot_and_update_dl = lambda **kwargs: changes.append(
            dict(self.page.get_current_tube_form_data()))
        table = self.page.sheet_form_param_table
        for row in range(table.rowCount()):
            if table.item(row, 0).data(forms.Qt.UserRole) == "R2":
                table.item(row, 1).setText("15")
                break
        else:
            self.fail("e_g节点缺少R2参数")
        self.assertTrue(changes, "编辑管板参数后必须同步父窗口")
        self.assertEqual(changes[-1]["R2"], "15")

    def test_e_f_r1_uses_the_diameter_selected_by_outer_base_flag(self):
        self.parent.heat_exchanger = "BEM"
        self.page = forms.SheetFormPage(self.parent)
        forms.get_plate_form_params.return_value = {
            "R1": "18", "h": "10", "α": "60", "p": "2", "e": "0",
        }
        self.page.DN = 1200.0
        self.page.Di = 1144.0
        self.page.DL = 1100.0

        for outer_flag, expected in (("否", "25.000"), ("是", "11.000")):
            with self.subTest(outer_flag=outer_flag):
                self.page.use_outer_diameter_base = outer_flag
                self.page._handle_image_click(None, 5)
                current = dict(self.page.get_current_tube_form_data())
                self.assertEqual(current["管板类型"], "e_f")
                self.assertEqual(current["R1"], expected)


if __name__ == "__main__":
    unittest.main()
