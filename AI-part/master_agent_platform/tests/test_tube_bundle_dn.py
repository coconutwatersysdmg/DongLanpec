import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QComboBox
BASE = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(BASE),
    str(BASE / "ui_vendor"),
    str(BASE / "ui_vendor" / "tube_agent"),
]

from evidence_runtime import with_condition_input_dn
from bundle.engine import LayoutError, LayoutResult, build_input
from bundle.page import TubeLayoutPage
from bundle.params import PARAM_ORDER
from platform_core.ui_theme import scale_legacy_page
from session import DesignSession
from window import apply_extracted_parameters
from unittest.mock import patch


class TubeBundleDnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_current_condition_dn_overrides_saved_value_and_prefers_tube_side(self):
        upstream = {
            "公称直径": {"value": "900", "unit": "mm", "source": "设计数据表"},
        }
        data = {
            "conditions": {
                "design_rows": [
                    {"param": "公称直径*", "side": "shell", "value": "800", "unit": "mm"},
                    {"param": "公称直径*", "side": "tube", "value": "700", "unit": "mm"},
                ]
            }
        }

        result = with_condition_input_dn(upstream, data)

        self.assertEqual(result["公称直径"]["value"], "700")
        self.assertEqual(result["公称直径"]["source"], "条件输入")

    def test_empty_condition_dn_preserves_saved_data(self):
        upstream = {"公称直径": {"value": "900", "source": "设计数据表"}}
        data = {"conditions": {"design_rows": [
            {"param": "公称直径*", "side": "tube", "value": ""}
        ]}}

        self.assertEqual(with_condition_input_dn(upstream, data), upstream)

    def test_missing_dn_does_not_fall_back_to_session_or_engine_defaults(self):
        session = DesignSession(None, {"产品ID": "P1"}, {}, None)
        self.assertIsNone(session.dn())
        self.assertEqual(session.header_text(), "P1 · AEU · DN待补录")
        with self.assertRaisesRegex(LayoutError, "公称直径 DN"):
            build_input({}, "AEU", {"公称直径 DN": "1200"})

    def test_engine_uses_explicit_dn_instead_of_default(self):
        result = build_input(
            {"公称直径 DN": {"value": "800"}},
            "AEU",
            {"公称直径 DN": "1200"},
        )

        self.assertEqual(float(result["LB_DN"]), 800.0)

    def test_tube_pdf_extraction_cannot_override_condition_dn(self):
        parameters = {
            "公称直径 DN": {"value": "400", "source": "条件输入"},
            "换热管外径 do": {"value": "25", "source": "布管参数表"},
        }

        apply_extracted_parameters(parameters, {
            "公称直径 DN": {"value": "900"},
            "换热管外径 do": {"value": "19"},
        })

        self.assertEqual(parameters["公称直径 DN"]["value"], "400")
        self.assertEqual(parameters["公称直径 DN"]["source"], "条件输入")
        self.assertEqual(parameters["换热管外径 do"]["value"], "19")

    def test_layout_uses_three_to_five_to_two_column_stretch(self):
        page = TubeLayoutPage({}, "AEU")
        try:
            page.resize(1100, 500)
            page.show()
            self.app.processEvents()
            self.assertGreaterEqual(page.view.width(), 520)
            self.assertLessEqual(page.right_frame.width(), 230)

            page.resize(1600, 800)
            self.app.processEvents()
            self.assertEqual(
                [page.body_layout.stretch(index) for index in range(3)],
                [30, 50, 20],
            )
            widths = [frame.width() for frame in (
                page.left_frame, page.center_frame, page.right_frame
            )]
            for actual, expected in zip(widths, (0.3, 0.5, 0.2)):
                self.assertAlmostEqual(actual / sum(widths), expected, delta=0.01)
        finally:
            page.close()

    def test_table_combos_remain_compact_after_pipe_button_click(self):
        with patch("bundle.page.engine.compute", side_effect=LayoutError("test")):
            page = TubeLayoutPage({"公称直径 DN": {"value": "900"}}, "AEU")
            try:
                page.resize(1100, 500)
                scale_legacy_page(page, 1.3)
                page.show()
                self.app.processEvents()
                page.pipe_button.click()
                self.app.processEvents()

                for row, name in enumerate(PARAM_ORDER):
                    editor = page._editors[name]
                    if not isinstance(editor, QComboBox):
                        continue
                    cell = page.param_table.visualRect(
                        page.param_table.model().index(row, 2)
                    )
                    if cell.isEmpty():
                        continue
                    self.assertTrue(cell.contains(editor.geometry()), name)
                    self.assertLessEqual(
                        editor.height(), round(cell.height() * 0.7), name
                    )
            finally:
                page.close()

    def test_outer_envelope_radius_comes_from_calculated_dn(self):
        page = TubeLayoutPage({}, "AEU")
        try:
            result = LayoutResult(
                input_json={"LB_DN": "800", "LB_Di": "700", "LB_DL": "600"},
                raw={},
                master_centers=[],
            )
            self.assertEqual(page._envelope_radii(result)["外圆"], 400)
        finally:
            page.close()

    def test_graph_refits_inside_the_enlarged_center_view(self):
        page = TubeLayoutPage({}, "AEU")
        try:
            page.resize(1100, 500)
            scale_legacy_page(page, 1.3)
            page.show()
            page.result = LayoutResult(
                input_json={"LB_DN": "900", "LB_Di": "800", "LB_DL": "700"},
                raw={},
                master_centers=[],
            )
            page.rebuild_scene()
            self.app.processEvents()

            viewport = page.view.viewport().rect()
            scene_bounds = page.view.mapFromScene(page.scene.sceneRect()).boundingRect()
            self.assertTrue(viewport.contains(scene_bounds))
            outer_diameter = page.result.big_r_wai * 2 * page.view.transform().m11()
            self.assertGreaterEqual(
                outer_diameter, 0.75 * min(viewport.width(), viewport.height())
            )
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
