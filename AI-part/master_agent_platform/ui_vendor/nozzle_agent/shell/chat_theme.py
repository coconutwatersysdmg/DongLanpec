# -*- coding: utf-8 -*-
"""
聊天界面配色与样式。

风格对齐「项目管理 Agent」那一版：通体白底、侧栏极浅灰、1 px 细线、
字小而密、只有一处蓝色（发送按钮与当前项）。不做渐变、不做投影、
不做彩色头像圈——越少装饰，越像工具而不是玩具。
"""

# ---------------------------------------------------------------- 基础色
BG = "#ffffff"            # 主区背景（纯白，和侧栏靠一条线分开）
SIDEBAR_BG = "#fbfbfc"    # 左侧会话栏
CARD_BG = "#ffffff"
BORDER = "#e8eaed"
BORDER_SOFT = "#f0f1f3"

TEXT = "#1f2328"
TEXT_MUTED = "#6e7681"
TEXT_FAINT = "#a1a7b0"

ACCENT = "#2563eb"
ACCENT_HOVER = "#1d4ed8"
ACCENT_SOFT = "#eef4ff"

USER_BUBBLE = "#f5f6f8"
USER_BORDER = "#f0f1f3"

OK = "#1f2328"            # 结论不再用绿色，统一正文色，靠字重区分
WARN = "#b45309"
ERR = "#c0392b"

CHIP_BG = "#f5f6f8"
CHIP_BG_OK = "#f5f6f8"
CHIP_BG_INHERIT = "#f5f6f8"

FONT = '"Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", sans-serif'

# ---------------------------------------------------------------- QSS
APP_QSS = f"""
QWidget {{
    font-family: {FONT};
    font-size: 12px;
    color: {TEXT};
}}
QMainWindow, #Central {{
    background: {BG};
}}

/* ---------------- 左侧会话栏 ---------------- */
#Sidebar {{
    background: {SIDEBAR_BG};
    border-right: 1px solid {BORDER};
}}
#BrandLabel {{
    font-size: 13px;
    font-weight: 600;
    color: {TEXT};
}}
#BrandSub {{
    font-size: 9px;
    color: {TEXT_FAINT};
    letter-spacing: 1px;
}}
#PrimaryBtn {{
    text-align: left;
    padding: 6px 10px;
    border: 1px solid {BORDER};
    border-radius: 6px;
    background: {CARD_BG};
    color: {TEXT};
    font-size: 12px;
}}
#PrimaryBtn:hover {{
    background: #f6f8fb;
    border-color: #d8dce2;
}}
#PrimaryBtn:pressed {{
    background: #eef1f6;
}}
QPushButton#GhostLink {{
    text-align: left;
    padding: 4px 10px;
    border: none;
    outline: none;
    border-radius: 6px;
    background: transparent;
    color: #374151;
    font-size: 12px;
}}
QPushButton#GhostLink:hover {{
    background: #f1f2f4;
}}
QPushButton#GhostLink:pressed, QPushButton#GhostLink:focus {{
    background: transparent;
}}
#SectionLabel {{
    color: {TEXT_FAINT};
    font-size: 11px;
    padding: 4px 2px 2px 2px;
}}
#SessionList {{
    background: transparent;
    border: none;
    outline: none;
}}
#SessionList::item {{
    padding: 5px 8px;
    border-radius: 5px;
    color: #374151;
    margin: 1px 0px;
    font-size: 12px;
}}
#SessionList::item:hover {{
    background: #f1f2f4;
}}
#SessionList::item:selected {{
    background: {ACCENT_SOFT};
    color: {ACCENT};
}}
#SidebarFoot {{
    color: {TEXT_FAINT};
    font-size: 10px;
    border-top: 1px solid {BORDER_SOFT};
    padding-top: 8px;
}}

/* ---------------- 顶部标题 ---------------- */
#TopBar {{
    background: {BG};
}}
#ChatTitle {{
    font-size: 13px;
    font-weight: 600;
    color: {TEXT};
}}
#ChatSub {{
    font-size: 10px;
    color: {TEXT_FAINT};
}}
#GhostBtn {{
    border: 1px solid transparent;
    border-radius: 5px;
    background: transparent;
    color: {TEXT_FAINT};
    padding: 4px 8px;
    font-size: 11px;
}}
#GhostBtn:hover {{
    background: #f3f4f6;
    color: {TEXT_MUTED};
}}

/* ---------------- 消息区 ---------------- */
#ChatScroll {{
    background: {BG};
    border: none;
}}
#MsgArea {{
    background: {BG};
}}
#UserBubble {{
    background: {USER_BUBBLE};
    border: 1px solid {USER_BORDER};
    border-radius: 8px;
}}
#UserName {{
    font-size: 10px;
    font-weight: 600;
    color: {TEXT_MUTED};
}}
#AgentName {{
    font-size: 10px;
    font-weight: 400;
    color: {TEXT_FAINT};
}}
#AgentBody {{
    color: {TEXT};
}}

/* ---------------- 代码块（结构化结果）---------------- */
#CodeBlock {{
    background: #fbfbfc;
    border: 1px solid {BORDER};
    border-radius: 7px;
}}
#CodeHead {{
    background: #f7f8f9;
    border-bottom: 1px solid {BORDER};
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}
#CodeKind {{
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 10px;
    color: #4b5563;
    background: #ffffff;
    border: 1px solid #e5e7ea;
    border-radius: 4px;
    padding: 0px 5px;
}}
#CodeMeta {{
    font-size: 10px;
    color: {TEXT_FAINT};
}}
#CodeBtn {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    color: {TEXT_MUTED};
    font-size: 10px;
    padding: 1px 7px;
}}
#CodeBtn:hover {{
    background: #eceef1;
    color: {TEXT};
}}
#CodeBody {{
    background: transparent;
    border: none;
    color: #3b4149;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
    selection-background-color: #d8e6fd;
    selection-color: {TEXT};
}}

/* ---------------- 空状态 ---------------- */
#WelcomeTitle {{
    font-size: 16px;
    font-weight: 600;
    color: {TEXT};
}}
#WelcomeSub {{
    font-size: 12px;
    color: {TEXT_MUTED};
}}
#SuggestionCard {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    text-align: left;
    padding: 8px 10px;
    color: #3b4149;
    font-size: 12px;
}}
#SuggestionCard:hover {{
    border-color: #cfd8e6;
    background: #fafbfd;
}}

/* ---------------- 输入区 ---------------- */
#Composer {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
#Composer:focus-within {{
    border-color: #c7d3e6;
}}
#Composer[dragActive="true"] {{
    border: 1px solid {ACCENT};
    background: #f7faff;
}}
#AttachBtn {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 5px;
    color: {TEXT_FAINT};
    font-size: 15px;
    padding: 0;
}}
#AttachBtn:hover {{
    background: #f1f2f4;
    color: {TEXT_MUTED};
}}
#AttachBtn:disabled {{
    color: #d3d7dc;
}}
#ChatInput {{
    background: transparent;
    border: none;
    color: {TEXT};
    font-size: 12px;
    padding: 1px 2px;
    selection-background-color: #d8e6fd;
    selection-color: {TEXT};
}}
#SendBtn {{
    background: {ACCENT};
    color: #ffffff;
    border: none;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 500;
    padding: 5px 16px;
}}
#SendBtn:hover {{
    background: {ACCENT_HOVER};
}}
#SendBtn:disabled {{
    background: #e6e8ec;
    color: #a9aeb6;
}}
#HintLabel {{
    color: {TEXT_FAINT};
    font-size: 10px;
}}
#StopBtn {{
    border: 1px solid {BORDER};
    border-radius: 5px;
    background: {CARD_BG};
    color: {TEXT_MUTED};
    padding: 3px 9px;
    font-size: 11px;
}}
#StopBtn:hover {{
    background: #f3f4f6;
}}

/* ---------------- 滚动条 ---------------- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px 2px 2px 0px;
}}
QScrollBar::handle:vertical {{
    background: #dcdfe4;
    border-radius: 4px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{
    background: #c3c8d0;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    height: 0px;
}}
QSplitter::handle {{
    background: {BORDER};
    width: 1px;
}}
"""
