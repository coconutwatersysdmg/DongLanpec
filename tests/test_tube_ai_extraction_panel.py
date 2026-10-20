import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMainWindow
from modules.buguan.buguan_ziyong.ai_assistant import api_client
from modules.buguan.buguan_ziyong.ai_assistant.api_client import APIConfig
from modules.buguan.buguan_ziyong.ai_assistant.extraction import SAMPLE_TEXT, SAMPLE_RESPONSE, validate_extraction
from modules.buguan.buguan_ziyong.ai_assistant.extraction_panel import ExtractionPanel
from modules.buguan.buguan_ziyong.ai_assistant.panel import TubeAssistantPanel


class ExtractionPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = ExtractionPanel()

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()

    def sample(self):
        self.panel.mode.setCurrentIndex(1)
        self.panel.input.setPlainText(SAMPLE_TEXT)
        self.panel.extract()

    def test_sample_is_labeled_and_editing_invalidates_preview(self):
        self.sample()
        self.assertEqual(self.panel.table.rowCount(), 13)
        self.assertIn('不是真实AI', self.panel.result['mode'])
        self.panel.preview()
        self.assertGreater(self.panel.result['preview']['tube_hole_count'], 0)
        self.panel.input.insertPlainText('改动')
        self.assertIsNone(self.panel.result)
        self.assertFalse(self.panel.preview_button.isEnabled())
        self.assertEqual(self.panel.table.rowCount(), 0)

    def test_fixed_sample_never_claims_to_parse_arbitrary_text(self):
        self.panel.mode.setCurrentIndex(1)
        self.panel.input.setPlainText('外径19毫米')
        self.panel.extract()
        self.assertIsNone(self.panel.result)
        self.assertIn('不解析任意输入', self.panel.status.text())

    def test_export_is_valid_json_and_excludes_key(self):
        self.sample()
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'demo.json'
            with patch('PyQt5.QtWidgets.QFileDialog.getSaveFileName', return_value=(str(target), 'JSON')):
                self.panel.export_json()
            result = json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(result['parameters']['公称直径 DN'], 1300)
            self.assertNotIn('api_key', result)

    def test_late_response_after_user_edit_is_discarded(self):
        release = threading.Event()
        config = APIConfig('https://dashscope.aliyuncs.com/compatible-mode/v1', 'unit-test-key', 'qwen-plus')
        def receive(*args):
            release.wait(2)
            result = validate_extraction(SAMPLE_RESPONSE, SAMPLE_TEXT)
            result.update({'mode': '百炼真实解析', 'usage': {}})
            return result
        with patch.object(api_client, '_SESSION_CONFIG', config), patch.object(
                api_client.CompatibleChatClient, 'extract_parameters', side_effect=receive):
            self.panel.input.setPlainText(SAMPLE_TEXT)
            self.panel.extract()
            self.assertTrue(self.panel.is_busy)
            self.panel.input.setPlainText('请求期间已修改')
            release.set()
            deadline = time.monotonic() + 3
            while self.panel.is_busy and time.monotonic() < deadline:
                QTest.qWait(20)
        self.assertFalse(self.panel.is_busy)
        self.assertIsNone(self.panel.result)
        self.assertIn('旧结果已丢弃', self.panel.status.text())
        self.assertTrue(self.panel.extract_button.isEnabled())

    def test_public_settings_do_not_save_secret(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'config.json'
            APIConfig('https://dashscope.aliyuncs.com/compatible-mode/v1', 'unit-test-key',
                      'qwen-plus').save_public_settings(target)
            saved = target.read_text(encoding='utf-8')
            self.assertNotIn('unit-test-key', saved)
            self.assertNotIn('api_key', saved)

    def test_closing_parent_is_blocked_while_request_is_running(self):
        parent = QMainWindow()
        child = ExtractionPanel(parent)
        parent.setCentralWidget(child)
        parent.show()
        release = threading.Event()
        config = APIConfig('https://dashscope.aliyuncs.com/compatible-mode/v1', 'unit-test-key', 'qwen-plus')
        def receive(*args):
            release.wait(2)
            raise RuntimeError('fake response')
        with patch.object(api_client, '_SESSION_CONFIG', config), patch.object(
                api_client.CompatibleChatClient, 'extract_parameters', side_effect=receive):
            child.input.setPlainText('测试')
            child.extract()
            try:
                closed = parent.close()
            finally:
                release.set()
                deadline = time.monotonic() + 3
                while child.is_busy and time.monotonic() < deadline:
                    QTest.qWait(20)
        parent.close()
        parent.deleteLater()
        self.assertFalse(closed)

    def test_old_assistant_parse_selects_matching_candidate_tab(self):
        editor = QMainWindow()
        parsed = {'intent': 'tube', 'goal_mode': '尽量多布'}
        controller = SimpleNamespace(editor=editor, read_params=lambda: {}, tube_pass_cat=lambda: '1',
            parse_natural_language=lambda text: parsed, generate_tubes=lambda *a: [],
            generate_components=lambda *a: [], _tube_candidates=[], _component_candidates=[])
        panel = TubeAssistantPanel(editor, controller)
        panel._parse_request()
        self.assertEqual(panel.tabs.tabText(panel.tabs.currentIndex()), '布管方案')
        parsed.update({'intent': 'component', 'quantity': 4, 'region': '外围对称'})
        panel._parse_request()
        self.assertEqual(panel.tabs.tabText(panel.tabs.currentIndex()), '元件方案')
        panel.close()
        editor.deleteLater()


if __name__ == '__main__':
    unittest.main()
