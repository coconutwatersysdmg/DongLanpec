from __future__ import annotations

from pathlib import Path
import json
import sys
import tempfile
import unittest
import zipfile

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from platform_core.orchestrator import Orchestrator
from platform_core.private_database import atomic_json


class SimulatedOrchestrator(Orchestrator):
    """Deterministic adapters; these tests do not claim real-engine validation."""
    def __init__(self, workspace, invalid_second=False):
        super().__init__(workspace)
        self.invalid_second = invalid_second
        self.forms_seen = []

    def foundation(self, product=None):
        return dict(element_names=[], template_candidates=[{}], parameter_template=[],
                    condition_requirements=[], snapshot_sha256="synthetic",
                    layout_supported=False, product_form=(product or {}).get("产品型式"))

    def task(self, request, product_id="", timeout=240):
        task, directory, fingerprint = self.fabric.begin_task(self.run_id, product_id, request)
        agent = request["agent"]
        if agent == "project":
            products = [dict(设备位号="P"+str(i), 产品名称="Product "+str(i), 产品型式=form,
                产品类型=kind, _file=Path(request["paths"][0]).name, _page_start=i, _page_end=i)
                for i, (form, kind) in enumerate((("BKU", "管壳式热交换器"), ("BFU", "管壳式热交换器"), ("单腔型", "卧式容器")), 1)]
            if self.invalid_second: products[1]["_page_end"] = 100
            result = dict(project={}, products=products)
        elif agent == "conditions":
            result = dict(design_rows=[dict(param="设计压力*", side="shell", value="" if request["tag"] == "P1" else "3.2", unit="MPa", status="found"),
                                      dict(param="介质名称", side="shell", value="", unit="")])
        elif agent == "elements":
            self.forms_seen.append(request["form"])
            result = dict(intents=[])
        elif agent == "nozzles":
            result = dict(data=dict(nozzles=[]))
        elif agent == "review_conditions":
            result = dict(candidates=[])
        else:
            raise AssertionError(agent)
        atomic_json(directory / "response.json", dict(ok=True, data=result))
        self.fabric.end_task(task, fingerprint, "succeeded", result)
        return result


class BatchProductTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agent_batch_test_")
        self.root = Path(self.temp.name)
        self.source = self.root / "three-products.pdf"
        with fitz.open() as doc:
            for _ in range(3): doc.new_page()
            doc.save(self.source)

    def tearDown(self): self.temp.cleanup()

    def test_processes_every_form_and_keeps_product_identity(self):
        engine = SimulatedOrchestrator(self.root / "workspace")
        result = engine.run([self.source])
        self.assertEqual(result["processed_products"], 3)
        self.assertEqual(engine.forms_seen, ["BKU", "BFU", "单腔型"])
        self.assertEqual([p["tag"] for p in result["products"]], ["P1", "P2", "P3"])
        self.assertEqual(result["manual_review_count"], 1)
        self.assertTrue(all(p.get("deferred") for p in result["products"]))
        for p in result["products"]:
            with zipfile.ZipFile(p["draft_path"]) as archive:
                for name in archive.namelist():
                    if name.startswith("receipts/") and name.endswith("request.json"):
                        request = json.loads(archive.read(name))
                        if request["agent"] != "project":
                            text = json.dumps(request)
                            self.assertIn(p["id"], text)
                            for other in result["products"]:
                                if other["id"] != p["id"]: self.assertNotIn(other["id"], text)

    def test_one_bad_product_does_not_drop_later_products(self):
        engine = SimulatedOrchestrator(self.root / "workspace", invalid_second=True)
        result = engine.run([self.source])
        self.assertEqual(result["processed_products"], 3)
        self.assertEqual(result["products"][1]["status"], "processing_failed")
        self.assertEqual(result["products"][2]["tag"], "P3")
        self.assertTrue(result["products"][2].get("draft_path"))

    def test_manual_submission_checks_revision_and_rereviews(self):
        engine = SimulatedOrchestrator(self.root / "workspace")
        result = engine.run([self.source])
        p = result["products"][0]
        answers = {p["id"]: {p["manual_review"][0]["id"]: "2.5"}}
        with self.assertRaisesRegex(ValueError, "已变化"):
            engine.resume_review(result["run_id"], answers, {p["id"]: "stale"})
        updated = engine.resume_review(result["run_id"], answers, {p["id"]: p["draft_data_sha256"]})
        self.assertEqual(updated["manual_review_count"], 0)
        self.assertEqual(updated["processed_products"], 3)
        self.assertGreaterEqual(len(updated["products"][0]["review_rounds"]), 4)
        self.assertTrue(updated["products"][0]["deferred"])

    def test_flat_layout_parameters_cannot_leak_across_products(self):
        engine = SimulatedOrchestrator(self.root / "workspace")
        with self.assertRaisesRegex(ValueError, "按产品位号"):
            engine.run([self.source], tube_parameters={"公称直径 DN": "500"})

    def test_changed_product_source_cannot_accept_old_manual_review(self):
        engine = SimulatedOrchestrator(self.root / "workspace")
        result = engine.run([self.source])
        p = result["products"][0]
        data = json.loads((Path(p["draft_path"]).parent / "draft-product.json").read_text(encoding="utf-8"))
        Path(data["product_source"]["path"]).write_bytes(b"changed source")
        with self.assertRaisesRegex(ValueError, "来源文件已变化"):
            engine.resume_review(result["run_id"], {p["id"]: {p["manual_review"][0]["id"]: "2.5"}},
                                 {p["id"]: p["draft_data_sha256"]})

    def test_deferred_gaps_can_be_rechecked_without_human_answers(self):
        engine = SimulatedOrchestrator(self.root / "workspace")
        result = engine.run([self.source])
        updated = engine.recheck_run(result["run_id"])
        self.assertEqual(updated["processed_products"], 3)
        self.assertEqual(updated["manual_review_count"], 1)
        self.assertTrue(all(len(p["review_rounds"]) == 4 for p in updated["products"]))


if __name__ == "__main__": unittest.main()
