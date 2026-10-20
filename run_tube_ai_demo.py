# -*- coding: utf-8 -*-
"""Standalone demo. No database, project account or engineering DLL required."""
import argparse
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="管束参数抽取Demo")
    parser.add_argument("--sample", action="store_true", help="打开固定样例，不联网")
    parser.add_argument("--screenshot", help="保存样例预览截图并退出，不联网")
    args = parser.parse_args()
    if args.screenshot:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtCore import QTimer
    from PyQt5.QtGui import QFont, QFontDatabase
    from PyQt5.QtWidgets import QApplication, QMainWindow
    from modules.buguan.buguan_ziyong.ai_assistant.extraction_panel import ExtractionPanel
    from modules.buguan.buguan_ziyong.ai_assistant.extraction import SAMPLE_TEXT

    class DemoWindow(QMainWindow):
        def closeEvent(self, event):
            if self.centralWidget().is_busy:
                self.centralWidget().status.setText("请求仍在进行，返回或超时后即可关闭。")
                event.ignore()
            else:
                super().closeEvent(event)

    app = QApplication(sys.argv[:1])
    if args.screenshot and os.name == "nt":
        # Windows offscreen插件不自动枚举系统字体，截图时显式加载。
        font_file = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts" / "msyh.ttc"
        if font_file.exists():
            QFontDatabase.addApplicationFont(str(font_file))
    app.setFont(QFont("Microsoft YaHei", 10))
    window = DemoWindow()
    window.setWindowTitle("东蓝管束 · AI参数抽取Demo（阿里云百炼）")
    window.resize(1160, 900)
    panel = ExtractionPanel()
    window.setCentralWidget(panel)
    window.show()
    if args.sample or args.screenshot:
        panel.input.setPlainText(SAMPLE_TEXT)
        panel.mode.setCurrentIndex(1)
        panel.extract()
        panel.preview()
    if args.screenshot:
        def save():
            target = Path(args.screenshot).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            if not window.grab().save(str(target)):
                app.exit(1)
                return
            print("Sample preview screenshot:", target)
            app.quit()
        QTimer.singleShot(150, save)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
