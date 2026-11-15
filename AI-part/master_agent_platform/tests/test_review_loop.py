from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from platform_core.review_loop import ReviewLoop, missing


def product(rows, templates=()):
    return dict(conditions=dict(design_rows=deepcopy(rows)),
                foundation=dict(condition_requirements=list(templates), snapshot_sha256="test"))


class ReviewLoopTests(unittest.TestCase):
    def test_optional_missing_is_rechecked_then_deferred(self):
        data = product([dict(param="介质名称", side="shell", value="", unit="")])
        calls = []
        review = ReviewLoop().run(data, lambda gaps: calls.append(gaps) or [])
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(review["rounds"]), 2)
        self.assertEqual(review["manual_review"], [])
        self.assertEqual(len(review["deferred"]), 1)
        self.assertEqual(data["conditions"]["design_rows"][0]["value"], "")

    def test_only_unresolved_required_field_needs_manual_review(self):
        data = product([dict(param="设计压力*", side="shell", unit="MPa", value=""),
                        dict(param="介质名称", side="shell", unit="", value="")])
        review = ReviewLoop().run(data, lambda gaps: [])
        self.assertEqual([g["label"] for g in review["manual_review"]], ["设计压力*"])
        self.assertEqual([g["label"] for g in review["deferred"]], ["介质名称"])

    def test_source_recheck_can_resolve_required_value_with_evidence(self):
        data = product([dict(param="设计压力*", side="shell", unit="MPa", value="")])
        candidate = dict(param="设计压力*", side="shell", unit="MPa", value="3.2", page=2, status="found")
        review = ReviewLoop().run(data, lambda gaps: [candidate])
        self.assertEqual(review["manual_review"], [])
        row = data["conditions"]["design_rows"][0]
        self.assertEqual(row["value"], "3.2")
        self.assertEqual(row["review_evidence"]["page"], 2)

    def test_matching_scoped_template_default_can_resolve_required(self):
        data = product([dict(param="设计压力*", side="shell", unit="MPa", value="")],
                       [dict(参数名称="设计压力*", 参数单位="MPa", 壳程数值="2.5", 管程数值="", 设计数据参数ID=1)])
        review = ReviewLoop().run(data, lambda gaps: [])
        self.assertFalse(review["manual_review"])
        self.assertEqual(data["conditions"]["design_rows"][0]["review_origin"], "scoped-template")

    def test_conflicting_sources_are_not_overridden_by_template(self):
        data = product([dict(param="设计压力*", side="shell", unit="MPa", value="")],
                       [dict(参数名称="设计压力*", 参数单位="MPa", 壳程数值="2.5")])
        candidates = [dict(param="设计压力*", side="shell", unit="MPa", value=v, page=1, status="found") for v in ("3.2", "4.0")]
        review = ReviewLoop().run(data, lambda gaps: candidates)
        self.assertEqual(len(review["manual_review"]), 1)
        self.assertEqual(data["conditions"]["design_rows"][0]["value"], "")

    def test_zero_is_not_missing(self):
        self.assertFalse(missing(0))
        data = product([dict(param="腐蚀裕量*", side="shell", unit="mm", value=0)])
        review = ReviewLoop().run(data)
        self.assertEqual(review["gaps"], [])

    def test_invalid_required_zero_cannot_be_automatically_accepted(self):
        data = product([dict(param="设计压力*", side="shell", unit="MPa", value="")])
        review = ReviewLoop().run(data, lambda gaps: [dict(param="设计压力*", side="shell", unit="MPa", value="0", page=1, status="found")])
        self.assertEqual(len(review["manual_review"]), 1)

    def test_invalid_human_answer_is_rejected_without_changing_draft(self):
        data = product([dict(param="设计压力*", side="shell", unit="MPa", value="")])
        ReviewLoop().run(data)
        before = deepcopy(data)
        with self.assertRaisesRegex(ValueError, "未通过校验"):
            ReviewLoop().apply_answers(data, {"conditions:design_rows:0": "-1"})
        self.assertEqual(data, before)

    def test_human_answer_reenters_loop_and_only_closes_its_gap(self):
        data = product([dict(param="设计压力*", side="shell", unit="MPa", value=""),
                        dict(param="设计温度（最高）*", side="shell", unit="℃", value="")])
        ReviewLoop().run(data)
        updated = ReviewLoop().apply_answers(data, {"conditions:design_rows:0": dict(value="3.2", reason="人工核对原文")})
        review = ReviewLoop().run(updated, round_offset=2)
        self.assertEqual([g["label"] for g in review["manual_review"]], ["设计温度（最高）*"])
        self.assertEqual(len(review["rounds"]), 4)
        self.assertEqual(updated["conditions"]["design_rows"][0]["review_origin"], "human")

    def test_required_value_cannot_be_skipped_with_dash(self):
        data = product([dict(param="设计压力*", side="shell", unit="MPa", value="")])
        ReviewLoop().run(data)
        with self.assertRaises(ValueError):
            ReviewLoop().apply_answers(data, {"conditions:design_rows:0": "—"})

    def test_source_tool_failure_is_separate_capability_issue(self):
        data = product([dict(param="介质名称", side="shell", unit="", value="")])
        def broken(gaps): raise RuntimeError("test source unavailable")
        review = ReviewLoop().run(data, broken)
        self.assertEqual(review["manual_review"], [])
        self.assertEqual(len(review["capabilities"]), 1)

    def test_material_requiredness_can_be_declared_without_treating_unknown_as_optional(self):
        data = product([])
        data["elements"] = dict(intents=[dict(raw_name="壳体", 材料类型="", 材料牌号="", 材料标准="", 供货状态="",
                                             required_fields=["材料牌号"])])
        review = ReviewLoop().run(data)
        self.assertEqual([g["label"] for g in review["manual_review"]], ["材料牌号"])
        del data["elements"]["intents"][0]["required_fields"]
        review = ReviewLoop().run(data)
        self.assertTrue(all(g["required"] is None for g in review["deferred"]))


if __name__ == "__main__":
    unittest.main()
