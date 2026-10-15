"""真实子进程 + Qt 页面生命周期回归；不写业务数据库。"""

import ast
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5 import QtWidgets, sip
from PyQt5.QtCore import QCoreApplication, QEvent, QTimer
from modules.qiangdujisuan.jiekou_python import calculation_process as process
from modules.qiangdujisuan.jiekou_python.calculation_lifecycle import active_calculations
from modules.qiangdujisuan.jiekou_python import jisuanjiemian as ui
from modules.qiangdujisuan.jiekou_python.calculation_file_tester import CalculationFileTestViewer
from modules.yudingyi import product_config as config
from modules.chanpinguanli import bianl


class CancellationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def wait_for(self, predicate, seconds=5):
        until = time.monotonic() + seconds
        while not predicate():
            self.app.processEvents()
            if time.monotonic() >= until:
                self.fail('Timed out waiting for calculation lifecycle')
            time.sleep(0.01)
        self.app.processEvents()

    @contextmanager
    def worker(self, delay=10):
        """启动会写 PID 的真实子进程，正常完成时返回最小 DLL JSON。"""
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            script = folder / 'worker.py'
            script.write_text('''import json,os,sys,time
from pathlib import Path
Path(sys.argv[2]).write_text(str(os.getpid()))
time.sleep(float(sys.argv[3]))
result = {'Logs': [], 'DictOutDatas': {'test': {'IsSuccess': True, 'Datas': []}}}
Path(sys.argv[1]).write_text(json.dumps({'ok': True, 'result': json.dumps(result)}), encoding='utf-8')
''', encoding='utf-8')
            children = []
            pid_files = []
            popen = process.subprocess.Popen
            def command(inp, out, root):
                pid_file = folder / f'pid{len(pid_files)}.txt'
                pid_files.append(pid_file)
                return [sys.executable, str(script), str(out), str(pid_file), str(delay)]
            def launch(*args, **kwargs):
                child = popen(*args, **kwargs)
                children.append(child)
                return child
            with patch.object(process, '_worker_command', command), patch.object(process.subprocess, 'Popen', launch):
                try:
                    yield children, pid_files
                finally:
                    for thread in active_calculations():
                        thread.cancel()
                    for thread in active_calculations():
                        self.assertTrue(thread.wait(5000))
                    for child in children:
                        if child.poll() is None:
                            child.kill()
                        child.wait(timeout=5)
                    self.app.processEvents()

    @contextmanager
    def product_viewer(self, delay=10):
        released = []
        entered = []
        @contextmanager
        def configuration(product_id, fallback=None):
            entered.append(product_id)
            try:
                yield 'A'
            finally:
                released.append(product_id)
        def calculate(thread):
            process.run_integrated_calculation('{}')
            thread.control.check()
            thread.finished_signal.emit({'Logs': [], 'DictOutDatas': {}})
        plan = config.ConfigPlan('one', 'A', 'A', 'hash', False)
        with self.worker(delay) as runtime, \
             patch.object(config, 'calculation_config', configuration), \
             patch.object(config, 'inspect_calculation_config', return_value=plan), \
             patch.object(ui.CalculationThread, '_calculate', calculate), \
             patch.object(ui, 'product_id', 'one'), \
             patch.object(bianl, 'product_table', None):
            viewer = ui.JisuanResultViewer(auto_calculate=False, require_project=False)
            viewer._display_result_impl = Mock()
            try:
                yield viewer, runtime, entered, released
            finally:
                if not sip.isdeleted(viewer):
                    viewer.stop_calculation()
                    viewer.close()

    def test_cancel_before_launch_never_creates_process(self):
        control = process.CalculationControl()
        control.cancel()
        with patch.object(process.subprocess, 'Popen') as popen:
            with self.assertRaises(process.CalculationCancelled):
                process.run_integrated_calculation('{}', control=control)
        popen.assert_not_called()

    def test_close_viewer_kills_child_and_releases_configuration(self):
        with self.product_viewer() as (viewer, (children, pids), entered, released):
            viewer.load_result()
            self.wait_for(lambda: pids and pids[0].exists())
            viewer.close()
            self.wait_for(lambda: not active_calculations('product'))
            self.assertIsNotNone(children[0].poll())
            self.assertEqual(released, ['one'])
            viewer._display_result_impl.assert_not_called()
            self.assertFalse(viewer.timer.isActive())

    def test_restart_waits_for_old_cleanup_and_uses_latest_selected_product(self):
        with self.product_viewer() as (viewer, (children, pids), entered, released):
            viewer.load_result()
            self.wait_for(lambda: pids and pids[0].exists())
            first = viewer.thread
            with patch.object(ui, 'product_id', 'two'):
                viewer.load_result()
            self.wait_for(lambda: len(pids) == 2 and pids[1].exists())
            self.assertIsNotNone(children[0].poll())
            self.assertFalse(first.isRunning())
            self.assertEqual(entered, ['one', 'two'])
            self.assertEqual(released, ['one'])
            self.assertEqual(viewer.thread.product_id, 'two')
            self.assertNotEqual(children[0].pid, children[1].pid)

    def test_repeated_restart_has_only_one_live_child(self):
        with self.product_viewer() as (viewer, (children, pids), entered, released):
            viewer.load_result()
            self.wait_for(lambda: pids and pids[0].exists())
            for i in range(3):
                viewer.load_result()
                self.wait_for(lambda: len(pids) == i + 2 and pids[-1].exists())
                self.assertEqual(sum(child.poll() is None for child in children), 1)
            self.assertEqual(len(released), 3)

    def test_close_pending_restart_does_not_spawn_again(self):
        with self.product_viewer() as (viewer, (children, pids), entered, released):
            viewer.load_result()
            self.wait_for(lambda: pids and pids[0].exists())
            viewer.load_result()
            viewer.close()
            self.wait_for(lambda: not active_calculations())
            self.assertFalse(viewer._restart_timer.isActive())
            self.assertTrue(all(child.poll() is not None for child in children))

    def test_queued_old_result_is_ignored_after_restart(self):
        with self.product_viewer(delay=0.02) as (viewer, runtime, entered, released):
            viewer.load_result()
            # 不泵 Qt 消息：旧结果信号已经排队，再发起新任务。
            self.assertTrue(viewer.thread.wait(5000))
            viewer.load_result()
            self.app.processEvents()
            viewer._display_result_impl.assert_not_called()
            self.wait_for(lambda: viewer._display_result_impl.call_count == 1)

    def test_cancel_during_preparation_prevents_later_dll_launch(self):
        ready = threading.Event()
        proceed = threading.Event()
        def prepare(thread):
            ready.set()
            proceed.wait(3)
            process.run_integrated_calculation('{}')
        with self.product_viewer() as (viewer, (children, pids), entered, released), \
             patch.object(ui.CalculationThread, '_calculate', prepare):
            viewer.load_result()
            self.wait_for(ready.is_set)
            viewer.close()
            proceed.set()
            self.wait_for(lambda: not active_calculations())
            self.assertFalse(children)
            self.assertEqual(released, ['one'])

    def test_main_close_tab_stops_worker_before_deleting_page(self):
        # 执行真实 close_tab 方法，避开导入 main.py 时的 MySQL/登录初始化。
        tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8-sig'))
        window_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'MainWindow')
        method = next(node for node in window_class.body if isinstance(node, ast.FunctionDef) and node.name == 'close_tab')
        namespace = {'QtWidgets': QtWidgets}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(ROOT / 'main.py'), 'exec'), namespace)
        with self.product_viewer() as (viewer, (children, pids), entered, released):
            viewer.load_result()
            self.wait_for(lambda: pids and pids[0].exists())
            tabs = QtWidgets.QTabWidget()
            tabs.addTab(viewer, '设计运算')
            host = SimpleNamespace(tab_widget=tabs, jisuan_viewer=viewer,
                                   _tip_timer=QTimer(), on_tab_changed=lambda i: None)
            tabs.currentChanged.connect(host.on_tab_changed)
            namespace['close_tab'](host, 0)
            self.assertEqual(tabs.count(), 0)
            self.assertIsNone(host.jisuan_viewer)
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.assertTrue(sip.isdeleted(viewer))
            self.wait_for(lambda: not active_calculations())
            self.assertIsNotNone(children[0].poll())

    def test_main_reopening_tab_stops_old_process_and_starts_new_page(self):
        tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8-sig'))
        window_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'MainWindow')
        method = next(node for node in window_class.body if isinstance(node, ast.FunctionDef) and node.name == 'open_tab')
        namespace = {'check_product_definition_status': lambda pid: True}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(ROOT / 'main.py'), 'exec'), namespace)
        with self.product_viewer() as (viewer, (children, pids), entered, released):
            viewer.load_result()
            self.wait_for(lambda: pids and pids[0].exists())
            first_thread = viewer.thread
            tabs = QtWidgets.QTabWidget()
            tabs.addTab(viewer, '设计运算')
            host = SimpleNamespace(tab_widget=tabs, last_confirmed_product_id='one',
                                   check_prerequisites_in_db=lambda pid: True,
                                   refresh_all_tabs_readonly_state=lambda: None)
            new_page = ui.JisuanResultViewer(auto_calculate=False, require_project=False)
            new_page._display_result_impl = Mock()
            try:
                with patch.object(bianl, 'current_project_id', 'project'), \
                     patch.object(bianl, 'current_product_id', 'one'), \
                     patch.dict(sys.modules, {'modules.condition_input.view': SimpleNamespace(check_project_and_product=lambda: (True, ''))}):
                    namespace['open_tab'](host, '设计运算', new_page)
                self.wait_for(lambda: len(pids) == 2 and pids[1].exists())
                self.assertFalse(first_thread.isRunning())
                self.assertIsNotNone(children[0].poll())
                self.assertEqual(tabs.count(), 1)
                self.assertIs(tabs.currentWidget(), new_page)
                self.assertEqual(released, ['one'])
            finally:
                new_page.close()

    def test_file_calculation_restart_and_close_kill_their_children(self):
        with self.worker() as (children, pids):
            viewer = CalculationFileTestViewer()
            viewer.input_payload = {}
            viewer.start_calculation()
            self.wait_for(lambda: pids and pids[0].exists())
            viewer.start_calculation()
            self.wait_for(lambda: len(pids) == 2 and pids[1].exists())
            self.assertIsNotNone(children[0].poll())
            viewer.close()
            self.wait_for(lambda: not active_calculations())
            self.assertIsNotNone(children[1].poll())


if __name__ == '__main__':
    unittest.main(verbosity=2)
