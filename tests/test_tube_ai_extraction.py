import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from modules.buguan.buguan_ziyong.ai_assistant.extraction import (
    SAMPLE_TEXT, SAMPLE_RESPONSE, validate_extraction, preview_layout,
)
from modules.buguan.buguan_ziyong.ai_assistant.api_client import APIConfig, CompatibleChatClient


class ExtractionTests(unittest.TestCase):
    def test_extracts_literal_values_and_real_algorithm_preview(self):
        result = validate_extraction(SAMPLE_RESPONSE, SAMPLE_TEXT)
        self.assertEqual(result['parameters']['公称直径 DN'], 1300)
        self.assertEqual(result['parameters']['布管限定圆 DL'], 1284)
        preview = preview_layout(result)
        self.assertGreater(len(preview['centers']), 0)
        self.assertEqual(preview['tube_count'], len(preview['centers']))
        self.assertEqual(preview['parameters']['换热管外径 do'], '25')

    def test_missing_values_are_not_filled_from_sample(self):
        result = validate_extraction({'parameters': [], 'unresolved': []}, '先设计一台换热器')
        self.assertEqual(result['parameters'], {})
        self.assertIn('换热管外径 do', result['missing'])
        with self.assertRaisesRegex(ValueError, '缺少'):
            preview_layout(result)

    def test_unknown_duplicate_and_fabricated_evidence_are_rejected(self):
        for rows in (
            [{'name': '执行SQL', 'value': 'delete', 'unit': '', 'evidence': '测试'}],
            [{'name': '公称直径 DN', 'value': 1300, 'unit': 'mm', 'evidence': '不存在'}],
            [{'name': '公称直径 DN', 'value': 1300, 'unit': 'mm', 'evidence': '1300'}] * 2,
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                validate_extraction({'parameters': rows, 'unresolved': []}, '测试1300')

    def test_bad_numbers_units_and_enum_are_rejected(self):
        for name, value, unit in (
            ('换热管外径 do', True, 'mm'), ('换热管外径 do', float('nan'), 'mm'),
            ('换热管外径 do', 89, 'mm'), ('管程程数', 2.5, ''),
            ('换热管外径 do', 25, 'cm'), ('换热管排列方式', '随便', ''),
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_extraction({'parameters': [{'name': name, 'value': value,
                    'unit': unit, 'evidence': '原文'}], 'unresolved': []}, '原文')

    def test_pitch_conflict_is_reported_and_blocks_preview(self):
        raw = json.loads(json.dumps(SAMPLE_RESPONSE, ensure_ascii=False))
        for row in raw['parameters']:
            if row['name'] == '换热管中心距 S':
                row['value'] = 20
        result = validate_extraction(raw, SAMPLE_TEXT)
        self.assertTrue(result['issues'])
        with self.assertRaisesRegex(ValueError, '中心距'):
            preview_layout(result)

    def test_multi_pass_without_partition_gap_is_not_silently_defaulted(self):
        raw = json.loads(json.dumps(SAMPLE_RESPONSE, ensure_ascii=False))
        raw['parameters'] = [p for p in raw['parameters']
                             if p['name'] != '分程隔板两侧相邻管中心距（竖直）']
        result = validate_extraction(raw, SAMPLE_TEXT)
        with self.assertRaisesRegex(ValueError, '分程隔板'):
            preview_layout(result)

    def test_partition_gap_smaller_than_tube_diameter_blocks_overlapping_holes(self):
        raw = json.loads(json.dumps(SAMPLE_RESPONSE, ensure_ascii=False))
        for row in raw['parameters']:
            if row['name'] == '分程隔板两侧相邻管中心距（竖直）':
                row['value'], row['evidence'] = 10, '间距10毫米'
        result = validate_extraction(raw, SAMPLE_TEXT + '间距10毫米')
        with self.assertRaisesRegex(ValueError, '分程隔板'):
            preview_layout(result)


class BailianClientTests(unittest.TestCase):
    def setUp(self):
        self.client = CompatibleChatClient(APIConfig(
            base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
            api_key='unit-test-key', model='qwen-plus'))

    def test_json_mode_and_local_validation_and_usage(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                return json.dumps({'choices': [{'finish_reason': 'stop', 'message': {
                    'content': json.dumps(SAMPLE_RESPONSE, ensure_ascii=False)}}],
                    'usage': {'prompt_tokens': 123, 'completion_tokens': 45}}).encode()
        requests = []
        def send(req, timeout):
            requests.append(req)
            return Response()
        with patch('urllib.request.urlopen', side_effect=send):
            result = self.client.extract_parameters(SAMPLE_TEXT)
        payload = json.loads(requests[0].data)
        self.assertEqual(payload['response_format'], {'type': 'json_object'})
        self.assertFalse(payload['enable_thinking'])
        self.assertEqual(result['parameters']['换热管外径 do'], 25)
        self.assertEqual(result['usage']['prompt_tokens'], 123)
        self.assertNotIn('api_key', result)

    def test_unsafe_api_address_is_refused_before_network(self):
        for base in ('http://dashscope.aliyuncs.com/v1', 'https://example.com/v1'):
            client = CompatibleChatClient(APIConfig(base, 'unit-test-key', 'qwen-plus'))
            with self.subTest(base=base), self.assertRaises(ValueError):
                client.extract_parameters('测试')

    def test_http_error_does_not_echo_key_or_server_body(self):
        error = HTTPError('https://example.com', 401, 'unit-test-key', {}, None)
        with patch('urllib.request.urlopen', side_effect=error):
            with self.assertRaisesRegex(RuntimeError, '401') as caught:
                self.client.extract_parameters(SAMPLE_TEXT)
        self.assertNotIn('unit-test-key', str(caught.exception))
        self.assertNotIn('unit-test-key', repr(self.client.config))


if __name__ == '__main__':
    unittest.main()
