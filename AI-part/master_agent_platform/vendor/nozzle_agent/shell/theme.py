# -*- coding: utf-8 -*-
"""
配色与按钮样式：直接对齐 pipe_attachment_define.ui 里写死的 QSS。

正式项目里每个 QPushButton 都带一段内联样式（白色→#e8edf5 竖向渐变、
1px #b8c8e0 边框、0 圆角、黑色字体），这里抽出同一份，供右侧 Agent 面板复用，
避免出现"左边是老界面、右边是现代卡片"的割裂感。
"""

BORDER = "#b8c8e0"
BORDER_LIGHT = "#d5dce8"
PANEL_BG = "#f4f7fb"
CARD_BG = "#ffffff"
TEXT = "#1f2937"
TEXT_MUTED = "#6b7280"
ACCENT = "#1d4ed8"
OK = "#0f766e"
WARN = "#b45309"
ERR = "#b91c1c"

# 与 .ui 中按钮完全一致的渐变写法，只缩小字号/内边距以适配窄侧栏
BUTTON_QSS = """
QPushButton {
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                stop: 0 #ffffff, stop: 1 #e8edf5);
    border: 1px solid #b8c8e0;
    border-radius: 0px;
    color: #000000;
    font-size: 12px;
    padding: 5px 12px;
    text-align: center;
    min-width: 56px;
}
QPushButton:hover {
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                stop: 0 #f0f4fa, stop: 1 #d8e0ed);
    border-color: #9ab0d0;
}
QPushButton:pressed {
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                stop: 0 #e0e6f0, stop: 1 #c8d2e0);
    border-color: #7a90b0;
}
QPushButton:disabled {
    background: #f5f7fa;
    color: #888888;
    border-color: #d0d8e5;
}
"""

# 右侧助手面板整体样式（延续正式界面的浅蓝灰、直角边框风格）
PANEL_QSS = """
QWidget#agentPanel {
    background: #f4f7fb;
    border-left: 1px solid #b8c8e0;
}
QLabel#panelTitle {
    color: #1f2d3d;
    font-size: 13px;
    font-weight: 600;
}
QLabel#panelSubtitle {
    color: #6b7280;
    font-size: 11px;
}
QLabel#unitHint {
    color: #1d4ed8;
    font-size: 11px;
    background: #ffffff;
    border: 1px solid #d5dce8;
    padding: 3px 7px;
}
QTextBrowser#chat {
    background: #ffffff;
    border: 1px solid #b8c8e0;
}
QLineEdit#input {
    background: #ffffff;
    border: 1px solid #b8c8e0;
    padding: 6px 8px;
    font-size: 12px;
    color: #111827;
    selection-background-color: #c7d7f0;
}
QLineEdit#input:focus {
    border-color: #7a90b0;
}
QFrame#hLine {
    background: #d5dce8;
    max-height: 1px;
}
""" + BUTTON_QSS
