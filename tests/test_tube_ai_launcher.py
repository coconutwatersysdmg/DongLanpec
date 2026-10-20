"""Run the actual Windows launcher: LF/UTF-8 CMD parsing previously skipped Python."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(os.name == 'nt', 'Windows CMD launcher')
class LauncherTests(unittest.TestCase):
    def run_launcher(self, *args, cwd=None, interpreter=None):
        launcher = Path(__file__).resolve().parents[1] / '启动管束AI演示.cmd'
        env = dict(os.environ, DONG_LANPEC_PYTHON=interpreter or sys.executable, QT_QPA_PLATFORM='offscreen')
        return subprocess.run([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', str(launcher), *args],
                              cwd=cwd, env=env, input='\n', capture_output=True,
                              encoding='utf-8', errors='replace', timeout=20)

    def test_actual_launcher_reaches_python_and_forwards_help(self):
        result = self.run_launcher('--help')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('--sample', result.stdout)
        self.assertNotIn('not recognized', result.stderr)

    def test_actual_launcher_runs_gui_from_other_directory_with_space_in_output(self):
        with tempfile.TemporaryDirectory(prefix='tube demo ') as temp:
            target = Path(temp) / 'preview with spaces.png'
            result = self.run_launcher('--screenshot', str(target), cwd=temp)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(target.exists(), result.stdout + result.stderr)
            self.assertEqual(target.read_bytes()[:8], b'\x89PNG\r\n\x1a\n')

    def test_failure_keeps_diagnostic_and_nonzero_exit_status(self):
        result = self.run_launcher('--help', interpreter='Z:\\missing-python\\python.exe')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('[ERROR]', result.stdout)
        self.assertIn('Keep this window open', result.stdout)


if __name__ == '__main__':
    unittest.main()
