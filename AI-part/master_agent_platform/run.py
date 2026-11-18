"""Chat-style independent Agent platform."""
import argparse
import json
from pathlib import Path
import sys
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication
from platform_core.orchestrator import Orchestrator
from platform_core.chat_app import ChatWindow, Worker
from platform_core.ui_theme import enable_high_dpi, apply_theme

BASE = Path(__file__).resolve().parent

class MainWindow(ChatWindow):
    def make_orchestrator(self, *args, **kwargs):
        return Orchestrator(*args, **kwargs)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result")
    parser.add_argument("--screenshot")
    parser.add_argument("--page", choices=("chat", "modules", "space", "execution", "review"), default="chat")
    args = parser.parse_args()
    enable_high_dpi()
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    apply_theme(app, 1.0)
    window = MainWindow()
    if args.result: window.on_complete(json.loads(Path(args.result).read_text(encoding="utf-8")))
    window.navigate(("chat", "modules", "space", "execution", "review").index(args.page))
    window.show()
    if not args.screenshot: QTimer.singleShot(0, window.prepare_database)
    if args.screenshot:
        def capture():
            path = Path(args.screenshot).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            if not window.grab().save(str(path)): raise RuntimeError("截图保存失败")
            app.quit()
        QTimer.singleShot(450, capture)
    return app.exec_()

if __name__ == "__main__": raise SystemExit(main())
