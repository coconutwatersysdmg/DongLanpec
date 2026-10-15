"""通过文件交换 JSON，每次启动并等待一个全新的 DLL 进程退出。"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar

from modules.qiangdujisuan.jiekou_python.calculation_dll_worker import WORKER_FLAG


class CalculationCancelled(Exception):
    """主动取消，不作为计算错误展示。"""


class CalculationControl:
    def __init__(self):
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._process = None

    @property
    def cancelled(self):
        return self._cancelled.is_set()

    def check(self):
        if self.cancelled:
            raise CalculationCancelled("计算已取消")

    def cancel(self):
        self._cancelled.set()
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                self._process.kill()

    def start_process(self, command, **options):
        # 与 cancel 共用锁，覆盖“刚检查完取消状态就创建进程”的竞争窗口。
        with self._lock:
            self.check()
            self._process = subprocess.Popen(command, **options)
            return self._process

    def release_process(self, process):
        with self._lock:
            if self._process is process:
                self._process = None


_current_control = ContextVar("calculation_control", default=None)


@contextmanager
def calculation_scope(control):
    token = _current_control.set(control)
    try:
        control.check()
        yield
    finally:
        _current_control.reset(token)


def application_root():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def _worker_command(input_path, output_path, root_dir):
    if getattr(sys, "frozen", False):
        command = [sys.executable, WORKER_FLAG]
    else:
        command = [sys.executable, str(Path(__file__).with_name("calculation_dll_worker.py"))]
    return command + [str(input_path), str(output_path), str(root_dir)]


def run_integrated_calculation(compact_json, timeout=None, control=None):
    control = control or _current_control.get() or CalculationControl()
    control.check()
    root_dir = application_root()
    with tempfile.TemporaryDirectory(prefix="donglanpec_calculation_") as temp_dir:
        temp_dir = Path(temp_dir)
        input_path = temp_dir / "input.json"
        output_path = temp_dir / "output.json"
        log_path = temp_dir / "worker.log"
        input_path.write_text(compact_json, encoding="utf-8")
        options = {}
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = subprocess.SW_HIDE
            options["startupinfo"] = startup
        process = None
        try:
            with log_path.open("wb") as log:
                process = control.start_process(
                    _worker_command(input_path, output_path, root_dir),
                    cwd=str(root_dir), stdout=log, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, **options,
                )
                started = time.monotonic()
                while process.poll() is None:
                    control.check()
                    if timeout is not None and time.monotonic() - started >= timeout:
                        raise RuntimeError(f"计算超过 {timeout} 秒，已结束本次 DLL 进程，请检查计算数据。")
                    try:
                        process.wait(timeout=0.05)
                    except subprocess.TimeoutExpired:
                        pass
                control.check()
        finally:
            if process is not None:
                try:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
                finally:
                    control.release_process(process)
        if not output_path.is_file():
            raw_log = log_path.read_bytes()
            try:
                details = raw_log.decode("utf-8")
            except UnicodeDecodeError:
                # CLR 未捕获异常使用 Windows 系统代码页，不能直接按 UTF-8 丢弃中文。
                details = raw_log.decode("mbcs" if os.name == "nt" else "utf-8", errors="replace")
            raise RuntimeError(f"DLL 计算进程异常退出（{process.returncode}）。\n{details[-4000:]}")
        response = json.loads(output_path.read_text(encoding="utf-8"))
        if process.returncode != 0 or not response.get("ok"):
            raise RuntimeError(response.get("error") or f"DLL 计算进程退出码：{process.returncode}")
        control.check()
        return response["result"]
