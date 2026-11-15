from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import fitz
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run as platform_ui
from test_batch_products import SimulatedOrchestrator


class ReviewUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agent_review_ui_")
        root = Path(self.temp.name)
        source = root / "products.pdf"
        with fitz.open() as doc:
            for _ in range(3): doc.new_page()
            doc.save(source)
        self.engine = SimulatedOrchestrator(root / "workspace")
        self.result = self.engine.run([source])
        self.window = platform_ui.MainWindow()
        self.window.on_complete(self.result)

    def tearDown(self):
        if self.window.worker is not None:
            self.window.worker.cancelled.set()
            self.window.worker.wait(10000)
            self.app.processEvents()
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def submit(self, value):
        self.window.review_editors[0][2].setText(value)
        with patch.object(platform_ui, "Orchestrator", lambda *a, **k: self.engine):
            self.window.submit_review.click()
            deadline = time.monotonic() + 10
            while self.window.worker is not None and time.monotonic() < deadline:
                self.app.processEvents()
                QTest.qWait(20)
        self.assertIsNone(self.window.worker)

    def test_window_lists_all_products_and_only_required_manual_fields(self):
        text = self.window.report.toPlainText()
        self.assertIn("已逐台处理：3 个", text)
        self.assertIn("BFU", text)
        self.assertIn("单腔型", text)
        self.assertNotIn("首个指定", text)
        self.assertEqual(len(self.window.review_editors), 1)
        self.assertEqual(self.window.review_tree.topLevelItemCount(), 1)

    def test_manual_value_submission_really_reruns_review(self):
        self.submit("2.5")
        self.assertEqual(self.window.last_result["manual_review_count"], 0)
        self.assertEqual(self.window.review_editors, [])
        self.assertIn("全部产品已完成本轮自动审核", self.window.state.text())

    def test_invalid_manual_value_keeps_queue_and_allows_retry(self):
        self.submit("-1")
        self.assertEqual(self.window.last_result["manual_review_count"], 1)
        self.assertIn("未通过校验", self.window.report.toPlainText())
        self.submit("2.5")
        self.assertEqual(self.window.last_result["manual_review_count"], 0)

    def test_automatic_recheck_button_keeps_unanswered_required_fields(self):
        with patch.object(platform_ui, "Orchestrator", lambda *a, **k: self.engine):
            self.window.recheck_button.click()
            deadline = time.monotonic() + 10
            while self.window.worker is not None and time.monotonic() < deadline:
                self.app.processEvents()
                QTest.qWait(20)
        self.assertIsNone(self.window.worker)
        self.assertEqual(self.window.last_result["manual_review_count"], 1)
        self.assertTrue(all(len(p["review_rounds"]) == 4 for p in self.window.last_result["products"]))


if __name__ == "__main__": unittest.main()
