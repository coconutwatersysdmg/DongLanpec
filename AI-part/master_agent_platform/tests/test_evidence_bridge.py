from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import fitz

from test_batch_products import SimulatedOrchestrator
from platform_core.evidence_merge import merge_payload
from platform_core.fabric import digest
from platform_core.private_database import atomic_json


class EvidenceBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="original_ui_bridge_")
        self.home = Path(self.temp.name)
        source = self.home / "products.pdf"
        with fitz.open() as doc:
            for _ in range(3): doc.new_page()
            doc.save(source)
        self.engine = SimulatedOrchestrator(self.home / "workspace")
        self.engine._mirror_evidence = lambda module, data: None
        self.summary = self.engine.run([source])
        self.product = self.summary["products"][0]
        self.path = Path(self.product["draft_path"]).parent / "draft-product.json"
        self.data = json.loads(self.path.read_text(encoding="utf-8"))
        self.session = self.engine.fabric.home / "evidence_sessions" / "test"
        self.session.mkdir(parents=True)
        atomic_json(self.session / "context.json", dict(run_id=self.summary["run_id"], module="conditions", products={self.product["id"]: {}}))

    def tearDown(self): self.temp.cleanup()

    def event(self, **overrides):
        payload = deepcopy(self.data["conditions"])
        payload["design_rows"][0]["value"] = "2.5"
        value = dict(schema="donglanpec.original-ui-update/1", id="native-edit", run_id=self.summary["run_id"],
            product_id=self.product["id"], module="conditions", expected_sha256=digest(self.path),
            context=str(self.session / "context.json"), payload=dict(confirmed=True, conditions=payload))
        value.update(overrides)
        path = self.session / "update.json"
        atomic_json(path, value)
        return path

    def test_confirmed_edit_roundtrip_retains_evidence_and_other_products(self):
        event = self.event()
        result = self.engine.import_evidence(event)
        self.assertEqual(len(result["products"]), 3)
        self.assertEqual(result["manual_review_count"], 0)
        self.assertEqual(result["products"][1:], self.summary["products"][1:])
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["conditions"]["design_rows"][0]["value"], "2.5")
        self.assertEqual(data["conditions"]["design_rows"][0]["review_origin"], "human")
        self.assertTrue(data["evidence_workbenches"]["conditions"][0]["confirmed"])
        import zipfile
        with zipfile.ZipFile(result["products"][0]["draft_path"]) as archive:
            self.assertIn("evidence/native-edit.json", archive.namelist())
        again = self.engine.import_evidence(event)
        self.assertEqual(len(json.loads(self.path.read_text(encoding="utf-8"))["evidence_workbenches"]["conditions"]), 1)
        self.assertEqual(again["manual_review_count"], 0)

    def test_stale_version_and_changed_event_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "已变化"):
            self.engine.import_evidence(self.event(expected_sha256="old"))
        event = self.event()
        self.engine.import_evidence(event)
        value = json.loads(event.read_text(encoding="utf-8"))
        value["payload"]["conditions"]["design_rows"][0]["value"] = "3.0"
        atomic_json(event, value)
        with self.assertRaisesRegex(ValueError, "相同回流ID"):
            self.engine.import_evidence(event)

    def test_unconfirmed_work_is_evidence_and_cannot_apply_values(self):
        value = deepcopy(self.data["conditions"])
        value["design_rows"][0]["value"] = "9.9"
        self.engine.import_evidence(self.event(payload=dict(confirmed=False, conditions=value)))
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["conditions"]["design_rows"][0]["value"], "")
        self.assertTrue(data["review"]["manual_review"])

    def test_invalid_required_value_returns_to_manual_review(self):
        value = deepcopy(self.data["conditions"])
        value["design_rows"][0]["value"] = "-8"
        result = self.engine.import_evidence(self.event(payload=dict(confirmed=True, conditions=value)))
        self.assertTrue(result["products"][0]["manual_review"])

    def test_nozzle_add_delete_and_duplicate_detection(self):
        payload = dict(confirmed=True, native_rows=[{"管口代号": "NEW", "公称尺寸": "80"}])
        changed = merge_payload(self.data, "nozzles", payload, {"id": "edit"})
        self.assertEqual([r["code"] for r in changed["nozzles"]["data"]["nozzles"]], ["NEW"])
        payload["native_rows"] *= 2
        with self.assertRaisesRegex(ValueError, "重复"):
            merge_payload(self.data, "nozzles", payload, {"id": "edit"})

    def test_project_scope_edit_retains_proposal_without_wrong_template(self):
        candidate = dict(self.data["product"], _platform_product_id=self.product["id"], 产品型式="BES", 产品名称="Edited")
        changed = merge_payload(self.data, "project", dict(confirmed=True, products=[candidate]), {"id": "edit"})
        self.assertEqual(changed["product"]["产品型式"], "BKU")
        self.assertEqual(changed["product"]["产品名称"], "Edited")
        self.assertEqual(changed["project_proposals"]["products"][0]["产品型式"], "BES")
        self.assertIn("UI_PRODUCT_SCOPE_CHANGED", [c["code"] for c in changed["capabilities"]])

    def test_evidence_path_and_context_must_match(self):
        event = self.event(module="nozzles")
        with self.assertRaisesRegex(ValueError, "不匹配"):
            self.engine.import_evidence(event)
        elsewhere = self.home / "update.json"
        elsewhere.write_bytes(event.read_bytes())
        with self.assertRaisesRegex(ValueError, "仅接收"):
            self.engine.import_evidence(elsewhere)

    def test_acknowledgement_belongs_to_submitted_product_after_switch(self):
        from platform_core.ui_runtime_support import UiContext
        config = self.home / "private.json"
        atomic_json(config, {})
        products = {p["id"]: dict(path=str(Path(p["draft_path"]).parent / "draft-product.json"), sha256=p["draft_data_sha256"])
                    for p in self.summary["products"]}
        context_path = self.session / "context.json"
        atomic_json(context_path, dict(session=str(self.session), private_config=str(config), product_id=self.product["id"],
            products=products, module="conditions", run_id=self.summary["run_id"]))
        context = UiContext(context_path)
        event_id = context.publish(dict(confirmed=False))
        other = self.summary["products"][1]["id"]
        context.select(other)
        other_version = context.expected[other]
        atomic_json(self.session / "ack.json", dict(id=event_id, ok=True, sha256="accepted-version"))
        self.assertTrue(context.acknowledge()["ok"])
        self.assertEqual(context.expected[self.product["id"]], "accepted-version")
        self.assertEqual(context.expected[other], other_version)

    def test_confirmed_material_changes_only_apply_valid_mapped_candidates(self):
        data = deepcopy(self.data)
        data["elements"] = dict(intents=[dict(raw_name="壳体", 材料牌号=""), dict(raw_name="管板", 材料牌号="")])
        state = dict(product_id=self.product["id"], applied=True, changes=[
            dict(ok=True, mapped=[dict(element_id=1)], intent=dict(raw_name="壳体"), new_values={"材料牌号": "Q345R"}),
            dict(ok=False, mapped=[dict(element_id=2)], intent=dict(raw_name="管板"), new_values={"材料牌号": "INVALID"})])
        result = merge_payload(data, "elements", dict(confirmed=True, state=state), {"id": "material-edit"})
        self.assertEqual(result["elements"]["intents"][0]["材料牌号"], "Q345R")
        self.assertEqual(result["elements"]["intents"][1]["材料牌号"], "")

    def test_source_form_is_retained_as_warning_without_weakening_other_errors(self):
        from platform_core.project_ui_adapter import source_identity_validator
        def validate(data):
            return [dict(field="产品型式", reason="型式不属于产品类型", suggest_value="BEU"),
                    dict(field="产品名称", reason="名称过长")], []
        review = source_identity_validator(validate, [{"产品类型": "管壳式热交换器", "产品型式": "BFU"}])
        errors, warnings = review({"产品类型": "管壳式热交换器", "产品型式": "BFU"})
        self.assertEqual([e["field"] for e in errors], ["产品名称"])
        self.assertEqual(warnings[0]["value"], "BFU")
        errors, warnings = review({"产品类型": "管壳式热交换器", "产品型式": "TYPO"})
        self.assertEqual(len(errors), 2)


if __name__ == "__main__": unittest.main()
