"""启动等待回归：真实卡住的探测子进程不能拖住生成线程。"""

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import MagicMock, patch

from modules.TwoD import TwoD_peizhi as cad
from modules.TwoD import autocad_startup_probe as probe


class StartupTests(unittest.TestCase):
    def process_running_in(self, identity):
        current = ("current-user-sid", 100, 1)
        proc = MagicMock()
        proc.info = {"pid": 12345, "name": "acad.exe"}
        with patch.object(cad.psutil, "process_iter", return_value=[proc]), \
                patch.object(cad, "_process_logon_identity", side_effect=[current, identity]):
            return cad._autocad_process_running()

    def test_another_users_cad_does_not_prevent_cold_start(self):
        self.assertFalse(self.process_running_in(("test-user-sid", 100, 1)))

    def test_same_username_in_another_logon_does_not_prevent_cold_start(self):
        self.assertFalse(self.process_running_in(("current-user-sid", 200, 1)))

    def test_another_desktop_session_does_not_prevent_cold_start(self):
        self.assertFalse(self.process_running_in(("current-user-sid", 100, 2)))

    def test_only_current_user_and_logon_cad_is_reused(self):
        self.assertTrue(self.process_running_in(("current-user-sid", 100, 1)))

    def test_unreadable_process_does_not_prevent_cold_start(self):
        proc = MagicMock()
        proc.info = {"pid": 12345, "name": "acad.exe"}
        with patch.object(cad.psutil, "process_iter", return_value=[proc]), \
                patch.object(cad, "_process_logon_identity", side_effect=[
                    ("current-user-sid", 100, 1), cad.pywintypes.error(5, "OpenProcess", "拒绝访问")]):
            self.assertFalse(cad._autocad_process_running())

    def test_document_interface_readable_is_not_enough_when_cad_is_busy(self):
        app = MagicMock()
        app.Visible = True
        app.Documents.Count = 1
        app.GetAcadState.return_value.IsQuiescent = False
        self.assertFalse(probe.check_ready(app, lambda message: None))
        app.ActiveDocument.GetVariable.assert_not_called()

    def test_rejected_idle_check_cannot_be_treated_as_ready(self):
        app = MagicMock()
        app.Visible = True
        app.Documents.Count = 1
        app.GetAcadState.side_effect = RuntimeError("COM 调用被拒绝")
        app.ActiveDocument.GetVariable.return_value = ""
        with self.assertRaisesRegex(RuntimeError, "被拒绝"):
            probe.check_ready(app, lambda message: None)
        app.ActiveDocument.GetVariable.assert_not_called()

    def test_ready_probe_requires_window_documents_and_idle(self):
        app = MagicMock()
        app.Visible = False
        app.Documents.Count = 0
        app.GetAcadState.return_value.IsQuiescent = True
        stages = []
        self.assertTrue(probe.check_ready(app, stages.append))
        self.assertTrue(app.Visible)
        self.assertEqual(len(stages), 3)

    def test_cold_start_uses_registered_exe_once_without_dispatch(self):
        server = [("AutoCAD.Application.24", r"D:\cad\AutoCAD 2021\acad.exe")]
        app = object()
        with patch.object(cad, "registered_autocad_servers", return_value=server), \
                patch.object(cad, "_autocad_process_running", return_value=False), \
                patch.object(cad.os.path, "isfile", return_value=True), \
                patch.object(cad.subprocess, "Popen") as launch, \
                patch.object(cad, "_wait_cad_startup_probe", return_value=server[0][0]) as wait, \
                patch.object(cad.win32com.client, "GetActiveObject", return_value=app), \
                patch.object(cad.win32com.client, "Dispatch") as dispatch:
            self.assertIs(cad.get_autocad_instance(timeout=180), app)
        launch.assert_called_once()
        self.assertEqual(Path(launch.call_args.args[0][0]).name, "acad.exe")
        wait.assert_called_once_with(["AutoCAD.Application.24"], 180)
        dispatch.assert_not_called()

    def test_existing_cad_is_attached_without_launching_another_instance(self):
        with patch.object(cad, "_autocad_process_running", return_value=True), \
                patch.object(cad, "_attach_running_autocad", return_value="existing") as attach, \
                patch.object(cad.subprocess, "Popen") as launch:
            self.assertEqual(cad.get_autocad_instance(), "existing")
        launch.assert_not_called()
        attach.assert_called_once_with(timeout=180)

    def test_failed_readiness_stops_before_path_fallback_or_another_launch(self):
        with patch.object(cad, "try_start_autocad_com", side_effect=RuntimeError("启动超时")), \
                patch.object(cad, "choose_cad_exe") as choose:
            with self.assertRaisesRegex(RuntimeError, "启动超时"):
                cad.get_autocad_instance()
        choose.assert_not_called()

    def test_generation_session_reuses_instance_and_drops_it_on_exit(self):
        app = object()
        with patch.object(cad, "try_start_autocad_com", return_value=app) as start:
            with cad.cad_startup_feedback(lambda message: None, lambda: False):
                for _ in range(10):
                    self.assertIs(cad.get_autocad_instance(), app)
            self.assertIsNone(getattr(cad._CAD_STARTUP_LOCAL, "acad", None))
        start.assert_called_once()

    def run_probe_child(self, code, timeout=1, cancelled=lambda: False):
        real_popen = subprocess.Popen
        processes = []

        def launch_probe(command, **options):
            process = real_popen([sys.executable, "-c", code, *command[-2:]], **options)
            processes.append(process)
            return process

        messages = []
        started = time.monotonic()
        try:
            with cad.cad_startup_feedback(messages.append, cancelled), \
                    patch.object(cad.subprocess, "Popen", side_effect=launch_probe):
                return cad._wait_cad_startup_probe(["AutoCAD.Application.24"], timeout)
        finally:
            self.assertLess(time.monotonic() - started, 3)
            self.assertEqual(len(processes), 1)
            self.assertIsNotNone(processes[0].poll())

    def test_hung_probe_is_terminated_at_deadline(self):
        # 用真正子进程模拟 COM 永远不返回，而非只模拟循环次数。
        with self.assertRaisesRegex(RuntimeError, "超过 0.4 秒.*生成已停止"):
            self.run_probe_child("import time; time.sleep(30)", timeout=0.4)

    def test_cancel_interrupts_a_hung_probe(self):
        checks = [0]

        def cancelled():
            checks[0] += 1
            return checks[0] >= 2

        with self.assertRaisesRegex(RuntimeError, "用户取消生成"):
            self.run_probe_child("import time; time.sleep(30)",
                                 timeout=180, cancelled=cancelled)

    def test_readiness_result_finishes_wait_and_cleans_up_probe(self):
        result = {"stage": "CAD 已就绪", "ready": True, "progid": "AutoCAD.Application.24"}
        code = ("import sys,time; f=open(sys.argv[2],'w'); f.write(" +
                repr(json.dumps(result) + "\n") + "); f.close(); time.sleep(30)")
        self.assertEqual(self.run_probe_child(code, timeout=2), "AutoCAD.Application.24")

    def test_windowed_worker_uses_files_when_standard_streams_are_unavailable(self):
        app = MagicMock()
        app.Visible = True
        app.Documents.Count = 1
        app.GetAcadState.return_value.IsQuiescent = True
        with TemporaryDirectory(prefix="cad-probe-test-") as folder:
            source, events = Path(folder) / "input.json", Path(folder) / "events.jsonl"
            source.write_text(json.dumps({"progids": ["AutoCAD.Application.24"]}), encoding="utf-8")
            with patch.object(cad.win32com.client, "GetActiveObject", return_value=app), \
                    patch.object(probe.time, "sleep"), patch.object(sys, "stdin", None), \
                    patch.object(sys, "stdout", None):
                self.assertEqual(probe.main([str(source), str(events)]), 0)
            result = json.loads(events.read_text(encoding="utf-8").splitlines()[-1])
            self.assertTrue(result["ready"])

    def test_busy_cad_stops_before_opening_first_drawing(self):
        with patch.object(cad, "must_exist_file", return_value=True), \
                patch.object(cad, "get_autocad_instance", return_value=MagicMock()) as connect, \
                patch.object(cad, "wait_cad_idle", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "停止打开图纸"):
                cad.open_drawing_with_wait("first.dwg")
        connect.return_value.Documents.Open.assert_not_called()

    def test_unloaded_document_is_not_returned_as_success(self):
        app = MagicMock()
        app.Documents.Count = 0
        with patch.object(cad, "must_exist_file", return_value=True), \
                patch.object(cad, "get_autocad_instance", return_value=app), \
                patch.object(cad, "wait_cad_idle", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "未完成加载"):
                cad.open_drawing_with_wait("first.dwg", timeout=0)

    def test_wait_scope_remains_active_until_probe_cleanup_finishes(self):
        states = []
        with cad.cad_startup_feedback(lambda message: None, lambda: False, states.append):
            with cad._cad_probe_wait_scope():
                self.assertEqual(states, [True])
        self.assertEqual(states, [True, False])

    def test_probe_entrypoint_precedes_gui_and_database_imports(self):
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertLess(source.index(WORKER_FLAG := "--autocad-startup-probe"), source.index("from PyQt5"))
        self.assertEqual(WORKER_FLAG, probe.WORKER_FLAG)


if __name__ == "__main__":
    unittest.main()
