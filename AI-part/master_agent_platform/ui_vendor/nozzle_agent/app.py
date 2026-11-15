# -*- coding: utf-8 -*-
"""
管口定义 Agent · 对话式 Demo

界面就是一个聊天框：左侧会话列表，右侧消息流 + 输入框。
不再嵌 `pipe_attachment_define.ui`，也不再出现工业软件的表头、按钮、示意图。

后端仍然复用 agent/：解析 -> 补全 -> 校验 -> 落表（内存），
只是把结果渲染成对话，而不是写进一张表。
"""
from __future__ import annotations

import os
import re
import sys
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import QSize, Qt, QThread, QUrl, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMainWindow, QPushButton, QShortcut, QVBoxLayout, QWidget,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.core import AgentReply, NozzleAgent          # noqa: E402
from agent.doc_import import DocResult, read_doc        # noqa: E402
from shell import chat_theme as T                       # noqa: E402
from shell.chat import ChatInput, ChatView, _label      # noqa: E402

WINDOW_TITLE = "管口定义 Agent"

_LLM = None          # 懒加载：没有 config.json 就用本地规则引擎，零开销


def get_llm():
    """读 config.json；没配置 / 加载失败就返回 None，交给规则引擎。"""
    global _LLM
    if _LLM is None:
        try:
            from agent.llm import LLMExtractor
            _LLM = LLMExtractor()
        except Exception:
            _LLM = False
    return _LLM or None


def engine_label() -> str:
    llm = get_llm()
    if llm is not None:
        try:
            return llm.label()
        except Exception:
            pass
    return "本地规则引擎"


def path_from_text(text: str) -> Optional[str]:
    """整句就是一个本地文件路径（或 file:/// 链接）时返回该路径。

    这样用户即使把文件当成纯文本粘进来（`file:///D:/xxx.pdf`），也能正确读文件，
    而不是被当成"没识别出要做什么"的一句话。
    """
    t = (text or "").strip().strip('"').strip("'")
    if t.lower().startswith("file:"):
        path = QUrl(t).toLocalFile()
        return path if path and os.path.isfile(path) else None
    if re.match(r"^[A-Za-z]:[\\/].+$", t) and os.path.isfile(t):
        return t
    return None


# ---------------------------------------------------------------- 后台线程
class AgentWorker(QThread):
    """agent.handle 放到线程里，界面不卡（以后接大模型尤其必要）。"""

    done = pyqtSignal(object)

    def __init__(self, agent: NozzleAgent, text: str, parent=None):
        super().__init__(parent)
        self.agent = agent
        self.text = text

    def run(self):
        try:
            reply = self.agent.handle(self.text)
        except Exception as exc:                       # 兜住任何异常，界面不崩
            reply = AgentReply(ok=False, action="noop",
                               headline=f"处理失败：{exc}",
                               action_text="本次未做任何修改")
        self.done.emit(reply)


# ---------------------------------------------------------------- 会话
class DocWorker(QThread):
    """读 PDF 也放线程里：一份 6 页的数据表要几百毫秒，界面别卡住。"""

    done = pyqtSignal(object)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self):
        try:
            res = read_doc(self.path)
        except Exception as exc:
            res = DocResult(path=self.path, error=f"读取失败：{exc}")
        self.done.emit(res)


class Session:
    """一次对话 = 一个独立的管口表状态 + 一串消息。"""

    def __init__(self):
        self.title = "新对话"
        self.agent = NozzleAgent(llm_extractor=get_llm())
        self.messages: List[Dict[str, Any]] = []

    def stats(self) -> str:
        rows = self.agent.rows
        if not rows:
            return "还没有管口"
        bad = sum(1 for r in rows if r.get("状态") == "待修正")
        warn = sum(1 for r in rows if r.get("状态") == "有提示")
        text = f"{len(rows)} 个管口"
        if bad:
            text += f" · {bad} 项待修正"
        elif warn:
            text += f" · {warn} 项待确认"
        else:
            text += " · 全部通过"
        return text


# ---------------------------------------------------------------- 左侧栏
class Sidebar(QFrame):
    newChat = pyqtSignal()
    pickFile = pyqtSignal()
    switched = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(196)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 12, 10, 10)
        lay.setSpacing(2)

        brand = QLabel("管口定义 Agent")
        brand.setObjectName("BrandLabel")
        sub = QLabel("DEEPSEEK · FLASH")
        sub.setObjectName("BrandSub")
        lay.addWidget(brand)
        lay.addWidget(sub)
        lay.addSpacing(10)

        # 主动作：选一份数据表。做成描边按钮，和参考图一致——不抢蓝色，
        # 蓝色只留给发送和当前项。
        self.pick_btn = QPushButton("开始识别产品")
        self.pick_btn.setObjectName("PrimaryBtn")
        self.pick_btn.setCursor(Qt.PointingHandCursor)
        self.pick_btn.setMinimumHeight(30)
        self.pick_btn.clicked.connect(self.pickFile)
        lay.addWidget(self.pick_btn)

        self.new_btn = QPushButton("新建对话")
        self.new_btn.setObjectName("GhostLink")
        self.new_btn.setCursor(Qt.PointingHandCursor)
        self.new_btn.setMinimumHeight(26)
        self.new_btn.clicked.connect(self.newChat)
        lay.addWidget(self.new_btn)
        lay.addSpacing(8)

        section = QLabel("历史对话")
        section.setObjectName("SectionLabel")
        lay.addWidget(section)

        self.list = QListWidget()
        self.list.setObjectName("SessionList")
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setWordWrap(False)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.currentRowChanged.connect(self.switched)
        lay.addWidget(self.list, 1)

        foot = QLabel(f"{engine_label()}\n数据存内存，不上传")
        foot.setObjectName("SidebarFoot")
        foot.setWordWrap(True)
        lay.addWidget(foot)

    def set_sessions(self, titles: List[str], current: int):
        self.list.blockSignals(True)
        self.list.clear()
        for t in titles:
            item = QListWidgetItem(t)
            item.setSizeHint(QSize(0, 26))
            self.list.addItem(item)
        self.list.setCurrentRow(current)
        self.list.blockSignals(False)

    def set_busy(self, busy: bool):
        self.list.setEnabled(not busy)
        self.new_btn.setEnabled(not busy)
        self.pick_btn.setEnabled(not busy)


# ---------------------------------------------------------------- 主窗口
class ChatWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1060, 760)
        self.setMinimumSize(860, 600)

        self.sessions: List[Session] = []
        self.cur = 0
        self.busy = False
        self.thinking: Optional[QWidget] = None
        self._worker: Optional[AgentWorker] = None
        self._doc_worker: Optional[DocWorker] = None

        central = QWidget()
        central.setObjectName("Central")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar()
        self.sidebar.newChat.connect(self._new_chat)
        self.sidebar.pickFile.connect(self._pick_file)
        self.sidebar.switched.connect(self._switch)
        root.addWidget(self.sidebar)

        root.addWidget(self._build_main(), 1)

        self._new_chat()
        for keys, slot in (("Ctrl+N", self._new_chat), ("Ctrl+L", self._clear_chat)):
            sc = QShortcut(QKeySequence(keys), self)
            sc.activated.connect(slot)

    # ------------------------------------------------------------ 主区
    def _build_main(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ---- 顶部 ----
        top = QFrame()
        top.setObjectName("TopBar")
        top.setFixedHeight(58)
        tl = QHBoxLayout(top)
        tl.setContentsMargins(22, 8, 18, 4)
        tl.setSpacing(10)

        self.title = QLabel("新对话")
        self.title.setObjectName("ChatTitle")
        self.subtitle = QLabel("还没有管口")
        self.subtitle.setObjectName("ChatSub")

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        col.addWidget(self.title)
        col.addWidget(self.subtitle)

        clear = QPushButton("清空对话")
        clear.setObjectName("GhostBtn")
        clear.setCursor(Qt.PointingHandCursor)
        clear.clicked.connect(self._clear_chat)

        tl.addLayout(col, 1)
        tl.addWidget(clear, 0, Qt.AlignTop)
        lay.addWidget(top)

        # ---- 消息流 ----
        self.chat = ChatView()
        self.chat.suggestion.connect(self.send)
        self.chat.filesDropped.connect(self.send_files)
        lay.addWidget(self.chat, 1)

        # ---- 输入区 ----
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(22, 4, 22, 10)
        bl.setSpacing(4)

        self.input = ChatInput()
        self.input.setMaximumWidth(10000)
        self.input.submitted.connect(self.send)
        self.input.filesDropped.connect(self.send_files)
        self.input.attachClicked.connect(self._pick_file)
        bl.addWidget(self.input)

        # 提示按参考图分左右：左边状态，右边快捷键
        self.hint_left = _label("等待输入…", size=10, color=T.TEXT_FAINT, wrap=False)
        hint_right = _label("Enter 发送 · Shift+Enter 换行 · Ctrl+N 新建对话",
                            size=10, color=T.TEXT_FAINT, wrap=False)
        hrow = QHBoxLayout()
        hrow.setContentsMargins(2, 0, 2, 0)
        hrow.addWidget(self.hint_left, 0)
        hrow.addStretch(1)
        hrow.addWidget(hint_right, 0)
        bl.addLayout(hrow)
        lay.addWidget(bottom)
        return box

    # ------------------------------------------------------------ 会话
    def _sync_sidebar(self):
        self.sidebar.set_sessions([s.title for s in self.sessions], self.cur)

    def _new_chat(self):
        if self.busy:
            return
        self.sessions.append(Session())
        self.cur = len(self.sessions) - 1
        self._sync_sidebar()
        self._show_current()

    def _switch(self, idx: int):
        if idx < 0 or idx == self.cur:
            return
        if self.busy:                       # 跑到一半不让切，避免回复落错会话
            self.sidebar.set_sessions([s.title for s in self.sessions], self.cur)
            return
        self.cur = idx
        self._show_current()

    def _show_current(self):
        s = self.sessions[self.cur]
        self.chat.clear_all()
        for m in s.messages:
            role = m.get("role")
            if role == "user":
                self.chat.add_user(m["text"])
            elif role == "agent":
                self.chat.add_agent(m["reply"])
            elif role == "file":
                self.chat.add_file(m["text"], m.get("size", 0), m.get("path", ""))
            elif role == "doc":
                self.chat.add_doc(m["doc"])
            else:
                self.chat.add_plain(m["text"])
        bar = self.chat.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.title.setText(s.title)
        self.subtitle.setText(s.stats())
        self.input.focus()

    def _clear_chat(self):
        if self.busy:
            return
        s = self.sessions[self.cur]
        s.messages.clear()
        s.agent.rows.clear()
        s.title = "新对话"
        self._sync_sidebar()
        self._show_current()

    # ------------------------------------------------------------ 文件
    def _pick_file(self):
        if self.busy:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "选择换热器数据表", "", "PDF 数据表 (*.pdf);;所有文件 (*)")
        if path:
            self.send_files([path])

    def send_files(self, paths: List[str]):
        """拖进来 / 选进来的文件走这里：先落一张文件卡片，再后台读表。"""
        if self.busy or not paths:
            return
        path = paths[0]
        name = os.path.basename(path)
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0

        s = self.sessions[self.cur]
        self.chat.add_file(name, size, path)
        s.messages.append({"role": "file", "text": name, "path": path, "size": size})
        if s.title == "新对话":
            s.title = name if len(name) <= 22 else name[:20] + "…"
            self.title.setText(s.title)
            self._sync_sidebar()

        if len(paths) > 1:
            rest = "、".join(os.path.basename(p) for p in paths[1:])
            self.chat.add_plain(f"一次先读一份，其余稍后再拖进来：{rest}")

        self.thinking = self.chat.add_thinking("正在读取数据表")
        self.busy = True
        self.sidebar.set_busy(True)
        self.input.set_enabled_state(False)

        self._doc_worker = DocWorker(path, self)
        self._doc_worker.done.connect(self._on_doc, Qt.QueuedConnection)
        self._doc_worker.start()

    def _on_doc(self, res: DocResult):
        self.chat.remove(self.thinking)
        self.thinking = None

        s = self.sessions[self.cur]
        s.messages.append({"role": "doc", "doc": res})
        self.chat.add_doc(res)
        self.subtitle.setText(s.stats())

        self.busy = False
        self.sidebar.set_busy(False)
        self.input.set_enabled_state(True)
        self.input.focus()

        if self._doc_worker is not None:
            self._doc_worker.deleteLater()
            self._doc_worker = None

    # ------------------------------------------------------------ 发送
    def send(self, text: str):
        text = (text or "").strip()
        if not text or self.busy:
            return

        # 用户可能直接把文件路径（或 file:///... 链接）粘进来，也当成发文件
        as_path = path_from_text(text)
        if as_path:
            self.send_files([as_path])
            return

        s = self.sessions[self.cur]

        self.chat.add_user(text)
        s.messages.append({"role": "user", "text": text})
        if s.title == "新对话":
            s.title = text if len(text) <= 18 else text[:18] + "…"
            self.title.setText(s.title)
            self._sync_sidebar()

        self.thinking = self.chat.add_thinking()
        self.busy = True
        self.sidebar.set_busy(True)
        self.input.set_enabled_state(False)

        self._worker = AgentWorker(s.agent, text, self)
        self._worker.done.connect(self._on_reply, Qt.QueuedConnection)
        self._worker.start()

    def _on_reply(self, reply: AgentReply):
        self.chat.remove(self.thinking)
        self.thinking = None

        s = self.sessions[self.cur]
        s.messages.append({"role": "agent", "reply": reply})
        self.chat.add_agent(reply)
        self.subtitle.setText(s.stats())

        self.busy = False
        self.sidebar.set_busy(False)
        self.input.set_enabled_state(True)
        self.input.focus()

        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    # ------------------------------------------------------------ 关闭
    def closeEvent(self, event):
        for w in (self._worker, self._doc_worker):
            if w is not None and w.isRunning():
                w.wait(1500)
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(WINDOW_TITLE)
    app.setStyle("Fusion")
    app.setStyleSheet(T.APP_QSS)
    win = ChatWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
