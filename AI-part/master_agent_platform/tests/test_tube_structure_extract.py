import tempfile
from pathlib import Path
import unittest

import fitz

from platform_core.evidence_data import EvidenceData
from platform_core.fabric import Fabric
from vendor.tube_agent.bundle.structure_extract import extract_structure_parameters


class TubeStructureExtractTests(unittest.TestCase):
    def test_structure_extraction_context_does_not_require_knowledge_chunks(self):
        context = Fabric.retrieve_context({"chunks": [{"text": "管束布管参数"}]}, "tube_structure")

        self.assertEqual(context["retrieved"], 0)
        self.assertEqual(context["total_excerpt_chunks"], 1)

    def test_extracts_text_fields_and_keeps_compound_shell_diameter_unmapped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "structure.pdf"
            with fitz.open() as document:
                page = document.new_page()
                page.insert_text((30, 150), "Structure parameters")
                page.insert_text((30, 180), "Shell I. D.")
                page.insert_text((200, 180), "1300/2000")
                page.insert_text((30, 205), "Tube bundle limited diameter")
                page.insert_text((200, 205), "1300")
                page.insert_text((30, 230), "Tube/shell pass quantities")
                page.insert_text((200, 230), "2 / 1")
                document.save(path)

            result = extract_structure_parameters(path, original_page_start=24)

        fields = {field["id"]: field for field in result["fields"]}
        self.assertEqual(result["source"]["page"], 24)
        self.assertEqual(fields["shell_id"]["value"], "1300/2000")
        self.assertEqual(fields["bundle_limit_diameter"]["value"], "1300")
        self.assertEqual(fields["pass_counts"]["value"], "2 / 1")
        self.assertEqual(result["mapped_parameters"]["布管限定圆 DL"]["value"], "1300")
        self.assertEqual(result["mapped_parameters"]["管程程数"]["value"], "2")
        self.assertEqual(result["mapped_parameters"]["壳程程数"]["value"], "1")
        shell_mapping = next(row for row in result["mapping_rows"] if row["source"] == "壳体内径")
        self.assertEqual(shell_mapping["status"], "ambiguous")

    def test_mapped_values_overlay_matching_defaults_without_changing_units(self):
        data = {
            "foundation": {
                "tube_defaults": [
                    {"参数名": "换热管外径 do", "参数值": "25", "单位": "mm"},
                    {"参数名": "拉杆直径", "参数值": "20", "单位": "mm"},
                ]
            },
            "tube_structure": {
                "mapped_parameters": {
                    "换热管外径 do": {"value": "19", "unit": "mm"},
                    "拉杆直径": {"value": None, "unit": "mm"},
                }
            },
        }

        rows = EvidenceData._tube_default_rows(data)

        self.assertEqual(rows[0], {"参数名": "换热管外径 do", "参数值": "19", "单位": "mm"})
        self.assertEqual(rows[1], {"参数名": "拉杆直径", "参数值": "20", "单位": "mm"})
        self.assertEqual(data["foundation"]["tube_defaults"][0]["参数值"], "25")


if __name__ == "__main__":
    unittest.main()
