"""真实子进程异常日志：UTF-8 和 Windows 系统编码均应保留中文。"""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modules.qiangdujisuan.jiekou_python import calculation_process as calculation


class CalculationLogEncodingTests(unittest.TestCase):
    def assert_crash_message(self, encoding):
        message = "未能加载计算依赖 ClosedXML，系统找不到指定的文件。"
        raw = message.encode(encoding)
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "crash_worker.py"
            script.write_text("import sys\nsys.stdout.buffer.write(bytes.fromhex(" + repr(raw.hex()) + "))\nsys.exit(7)\n", encoding="utf-8")
            with patch.object(calculation, "_worker_command", return_value=[sys.executable, str(script)]):
                with self.assertRaises(RuntimeError) as result:
                    calculation.run_integrated_calculation("{}", timeout=10)
        self.assertIn("DLL 计算进程异常退出（7）", str(result.exception))
        self.assertIn(message, str(result.exception))
        self.assertNotIn("\ufffd", str(result.exception))

    def test_utf8_worker_crash_preserves_chinese(self):
        self.assert_crash_message("utf-8")

    @unittest.skipUnless(os.name == "nt", "Windows CLR system-code-page output")
    def test_windows_clr_crash_preserves_chinese(self):
        self.assert_crash_message("mbcs")


if __name__ == "__main__":
    unittest.main()
