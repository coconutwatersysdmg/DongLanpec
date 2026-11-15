import argparse
import os
from pathlib import Path
import sys

# 控制台输出统一 UTF-8（取代原 .cmd 启动器里的 PYTHONUTF8=1）
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# 无论从哪个目录双击/运行，都以本文件所在目录为工作目录
os.chdir(Path(__file__).resolve().parent)


def _install_font(app):
    from PyQt5.QtGui import QFont, QFontDatabase

    if os.name == "nt":
        fonts_dir = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"
        for filename in ("msyh.ttc", "msyhbd.ttc"):
            path = fonts_dir / filename
            if path.exists():
                QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Microsoft YaHei UI", 10))


def main():
    parser = argparse.ArgumentParser(description="管束设计 AI AGENT")
    parser.add_argument("--screenshot", help="离屏渲染界面截图并保存到该路径，随后退出")
    parser.add_argument("--stage", type=int, default=None, help="截图前展开的 Tab 序号 0-3")
    parser.add_argument("--product", default=None, help="指定要载入的产品ID")
    parser.add_argument("--width", type=int, default=1920, help="截图窗口宽度")
    parser.add_argument("--height", type=int, default=1040, help="截图窗口高度")
    args = parser.parse_args()

    if args.screenshot:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    _install_font(app)

    from window import DesignWindow

    window = DesignWindow()
    if args.screenshot:
        window.resize(args.width, args.height)
        window.show()
    else:
        # 正常启动直接铺满屏幕：对话是主界面，越大越好（仍可点右上角还原）
        window.showMaximized()
        # 一运行直接进入管束设计：自动读取数据库并生成草稿，
        # 不再要求先点左侧“开始管束设计”（按钮保留，用于修复数据库后重试）。
        QTimer.singleShot(0, window.start_design)

    if args.screenshot:
        # 离屏截图不需要事件循环：同步载入会话、展开 Tab、抓图后立即退出。
        from models import STAGES

        window.headless = True  # 跳过模态确认框，且只生成写库计划、不写正式库
        for _ in range(3):
            app.processEvents()
        if args.stage is None:
            # 未指定 Tab：截取初始聊天界面（不建会话）
            path = Path(args.screenshot).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            ok = window.grab().save(str(path))
            print(f"screenshot: {path}（初始聊天界面）ok={ok}")
            return 0 if ok else 1
        stage = max(0, min(len(STAGES) - 1, args.stage))
        try:
            window._boot_session(args.product)
            for index in range(stage):
                window.open_stage(index)
                window.keep_current(STAGES[index])
                app.processEvents()
            window.open_stage(stage)
        except Exception as exc:  # noqa: BLE001
            print(f"[screenshot] 载入会话失败：{type(exc).__name__}: {exc}")
        for _ in range(5):
            app.processEvents()
        # 滚到卡片底部，保证截图里能看到唯一的“保留”按钮
        window.conversation._scroll_to_bottom()
        app.processEvents()
        path = Path(args.screenshot).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        pixmap = window.grab()
        ok = pixmap.save(str(path))
        print(f"screenshot: {path} ({pixmap.width()}x{pixmap.height()}) ok={ok}")
        if window.session is not None:
            print(f"session: {window.session.header_text()}")
            print(f"stage: {STAGES[stage]}")
        return 0 if ok else 1

    app.processEvents()
    QTimer.singleShot(0, lambda: None)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
