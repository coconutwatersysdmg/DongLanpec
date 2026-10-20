# -*- coding: utf-8 -*-
import unittest

from modules.buguan.buguan_ziyong.ai_assistant.api_client import (
    APIConfig,
    parse_structured_request,
)


class APIClientContractTests(unittest.TestCase):
    def test_empty_config_is_explicitly_disabled(self):
        config = APIConfig(base_url="", api_key="", model="")
        self.assertFalse(config.configured)

    def test_tube_request_only_accepts_whitelisted_fields(self):
        parsed = parse_structured_request(
            '{"intent":"tube","goal_mode":"至少管数","target_count":300,"ignored":"x"}'
        )
        self.assertEqual(
            parsed,
            {"intent": "tube", "goal_mode": "至少管数", "target_count": 300},
        )

    def test_component_request_rejects_unsupported_component(self):
        with self.assertRaisesRegex(ValueError, "目前仅支持拉杆"):
            parse_structured_request(
                '{"intent":"component","component":"防冲板","quantity":1,"region":"上部"}'
            )


if __name__ == "__main__":
    unittest.main()
