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

    def test_canonical_custom_values_are_preserved(self):
        canonical = {"α1": "60", "b": "2", "p1": "2", "d1": "1", "α2": "30",
                     "R": "2", "n": "4", "e": "5", "p2": "2", "d2": "1"}
        self.assertEqual(forms._normalize_plate_form_params("b_c", canonical), canonical)


if __name__ == "__main__":
    unittest.main()
