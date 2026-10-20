# -*- coding: utf-8 -*-
import unittest

from modules.buguan.buguan_ziyong.ai_assistant.core import (
    TubeGoal,
    generate_component_candidates,
    generate_tube_candidates,
)


BASE_PARAMS = {
    "布管限定圆 DL": "400",
    "换热管外径 do": "19",
    "换热管中心距 S": "25",
    "公称直径 DN": "500",
    "换热管排列方式": "正三角形",
    "换热管布置方式": "对中",
    "分程隔板两侧相邻管中心距（竖直）": "30",
    "分程隔板两侧相邻管中心距（水平）": "30",
}


class TubeCandidateTests(unittest.TestCase):
    def test_generates_distinct_engine_calculated_candidates(self):
        candidates = generate_tube_candidates(
            BASE_PARAMS, "1", TubeGoal(mode="尽量多布")
        )

        self.assertGreaterEqual(len(candidates), 2)
        self.assertEqual({item.layout for item in candidates}, {"对中", "跨中"})
        self.assertTrue(all(item.tube_count == len(item.centers) for item in candidates))
        self.assertGreaterEqual(candidates[0].tube_count, candidates[-1].tube_count)

    def test_minimum_goal_explains_whether_each_candidate_meets_target(self):
        candidates = generate_tube_candidates(
            BASE_PARAMS, "1", TubeGoal(mode="至少管数", target_count=180)
        )

        self.assertTrue(all("180" in item.explanation for item in candidates))
        self.assertTrue(all(isinstance(item.meets_goal, bool) for item in candidates))


class ComponentCandidateTests(unittest.TestCase):
    def setUp(self):
        self.centers = [
            (-100.0, 0.0),
            (100.0, 0.0),
            (0.0, -100.0),
            (0.0, 100.0),
            (-70.0, -70.0),
            (70.0, 70.0),
            (-70.0, 70.0),
            (70.0, -70.0),
        ]

    def test_symmetric_rod_candidate_uses_existing_tube_centers(self):
        plans = generate_component_candidates(
            self.centers, component="拉杆", quantity=4, region="外围对称"
        )

        self.assertGreaterEqual(len(plans), 1)
        allowed = set(self.centers)
        self.assertTrue(all(set(plan.centers) <= allowed for plan in plans))
        self.assertTrue(all(len(plan.centers) == 4 for plan in plans))

    def test_region_candidate_respects_requested_side(self):
        plans = generate_component_candidates(
            self.centers, component="拉杆", quantity=2, region="上部"
        )

        self.assertGreaterEqual(len(plans), 1)
        self.assertTrue(all(y < 0 for _, y in plans[0].centers))

    def test_rejects_component_type_without_real_apply_support(self):
        with self.assertRaisesRegex(ValueError, "目前仅支持拉杆"):
            generate_component_candidates(
                self.centers, component="防冲板", quantity=1, region="上部"
            )


if __name__ == "__main__":
    unittest.main()
