import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
from platform_core.fabric import Fabric
import run


class DatabaseStartupUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='database_startup_ui_')
        self.window = run.MainWindow()
        self.window.workspace = Path(self.temp.name) / 'workspace'
        self.window.fabric = Fabric(self.window.workspace)
        self.window.module_panel.workspace = self.window.workspace

    def wait(self, condition):
        deadline = time.monotonic()+4
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(20)
        self.assertTrue(condition())

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def test_database_preparation_gates_send_until_ready(self):
        gate = threading.Event()
        def initialize(*args):
            gate.wait(2)
            return dict(port=13318)
        with patch('platform_core.bundled_database.ensure_database', side_effect=initialize):
            self.window.prepare_database()
            self.assertFalse(self.window.begin.isEnabled())
            gate.set()
            self.wait(lambda: self.window.database_worker is None)
        self.assertTrue(self.window.begin.isEnabled())
        self.assertIn('已就绪', self.window.data_badge.text())

    def test_preparation_failure_is_displayed_in_the_conversation(self):
        with patch('platform_core.bundled_database.ensure_database', side_effect=RuntimeError('自带数据库文件校验失败：seed/test.gz')):
            self.window.prepare_database()
            self.wait(lambda: self.window.database_worker is None)
        self.assertIn('未完成', self.window.data_badge.text())
        self.assertTrue(any('seed/test.gz' in m['text'] for m in self.window.messages))

    def test_failed_run_summary_exposes_the_actual_error(self):
        identity = self.window.fabric.create_run({})
        result = dict(run_id=identity, status='failed', products=[], error='独立数据库启动失败：请查看 server.log',
                      run_directory=str(self.window.workspace / 'runs' / identity))
        self.window.fabric.finish(identity, 'failed', result)
        self.window.on_complete(result)
        self.assertIn(result['error'], self.window.report.toPlainText())

    def test_exit_waits_for_database_initialization_to_finish(self):
        gate = threading.Event()
        def initialize(*args):
            gate.wait(2)
            return dict(port=13319)
        self.window.show()
        with patch('platform_core.bundled_database.ensure_database', side_effect=initialize):
            self.window.prepare_database()
            self.window.close()
            self.assertTrue(self.window.close_after_database)
            gate.set()
            self.wait(lambda: self.window.database_worker is None and not self.window.isVisible())


if __name__ == '__main__': unittest.main()
