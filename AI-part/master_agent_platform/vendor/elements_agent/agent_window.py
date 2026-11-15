# -*- coding: utf-8 -*-
"""
元件定义 Agent 独立窗口：参考项目管理 / 管束 Agent 的简洁侧栏 + 对话布局。
"""

from __future__ import annotations

import html
import os
import re
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtGui import QFont, QTextCursor, QDragEnterEvent, QDropEvent
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from elements_agent.confirm_dialog import show_confirm_dialog
from elements_agent.graph import apply_pipeline, run_pipeline
from elements_agent.llm.provider import (
    active_backend,
    chat_completion,
    llm_available,
)
from elements_agent.models import AgentState
from elements_agent.product_picker import pick_product

_DOC_EXTS = {".pdf", ".doc", ".docx", ".xlsx", ".xls", ".csv", ".txt"}

APP_QSS = """
QMainWindow, QWidget#Root {
  background:#f5f6f8; color:#1f2329;
  font-family:"Microsoft YaHei UI","Segoe UI",sans-serif;
}
QFrame#Side {
  background:#ffffff; border-right:1px solid #eceef2;
}
QLabel#SideBrand {
  font-size:15pt; font-weight:700; color:#1f2329; padding:2px 0;
}
QLabel#SideCap {
  font-size:9.5pt; color:#8a9199; margin-top:10px; margin-bottom:4px;
}
QPushButton#SidePrimary {
  background:#2f6bff; color:#fff; border:none; border-radius:10px;
  padding:12px 14px; font-size:11.5pt; font-weight:600; text-align:center;
}
QPushButton#SidePrimary:hover { background:#2458d6; }
QPushButton#SideGhost {
  background:#fff; color:#1f2329; border:1px solid #e5e6eb; border-radius:10px;
  padding:10px 12px; font-size:10.5pt; text-align:left;
}
QPushButton#SideGhost:hover { border-color:#2f6bff; color:#2f6bff; }
QListWidget#History, QListWidget#Steps {
  background:transparent; border:none; outline:none; font-size:10.5pt;
}
QListWidget#History::item {
  padding:9px 10px; border-radius:8px; margin:2px 0; color:#4e5969;
}
QListWidget#History::item:selected { background:#eef3ff; color:#2f6bff; }
QListWidget#Steps::item {
  padding:8px 10px; border-radius:8px; margin:2px 0; color:#8a9199;
}
QListWidget#Steps::item:selected {
  background:#eef3ff; color:#2f6bff; font-weight:600;
}
QLabel#ChatHead { font-size:13pt; font-weight:600; color:#1f2329; }
QLabel#ProductPill {
  background:#f2f4f7; color:#4e5969; border-radius:8px;
  padding:6px 10px; font-size:10pt;
}
QTextBrowser#ChatView {
  background:#ffffff; border:1px solid #eceef2; border-radius:14px;
  padding:14px 16px; font-size:11.5pt;
}
QFrame#Composer {
  background:#ffffff; border:1px solid #e5e6eb; border-radius:14px;
}
QFrame#Composer[dragging="true"] {
  border:2px dashed #2f6bff; background:#f5f8ff;
}
QTextEdit#Input {
  background:transparent; border:none; padding:10px 8px;
  font-size:11.5pt; min-height:44px;
}
QPushButton#Primary {
  background:#2f6bff; color:#fff; border:none; border-radius:10px;
  padding:10px 18px; font-size:11.5pt; font-weight:600; min-width:84px;
}
QPushButton#Primary:hover { background:#2458d6; }
QPushButton#Primary:disabled { background:#a8b8e8; }
QPushButton#Ghost {
  background:transparent; color:#8a9199; border:none; padding:4px 8px; font-size:10pt;
}
QPushButton#Ghost:hover { color:#2f6bff; }
QLabel#Foot { color:#8a9199; font-size:9pt; }
"""

_STEPS = ("选产品", "上传标书", "抽取校验", "确认写入")


@dataclass
class ChatSession:
    title: str
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%H:%M"))
    html_parts: List[str] = field(default_factory=list)
    tender_paths: List[str] = field(default_factory=list)
    messages: List[dict] = field(default_factory=list)


class DropComposer(QFrame):
    def __init__(self, owner: "ElementDefineAgentWindow"):
        super().__init__()
        self.owner = owner
        self.setObjectName("Composer")
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("dragging", True)
            self.style().unpolish(self)
            self.style().polish(self)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setProperty("dragging", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent):
        self.setProperty("dragging", False)
        self.style().unpolish(self)
        self.style().polish(self)
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        if paths:
            self.owner.add_tender_paths(paths)
        event.acceptProposedAction()


class ElementDefineAgentWindow(QMainWindow):
    def __init__(self, product_id: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("元件定义材料助手")
        self.resize(1180, 760)
        self.setMinimumSize(960, 620)
        self.setFont(QFont("Microsoft YaHei UI", 10))
        self.setStyleSheet(APP_QSS)
        self.setAcceptDrops(True)

        self._pending: Optional[AgentState] = None
        self._selected_product_id = (product_id or "").strip()
        self._selected_product_label = ""
        self._selected_project_folder = ""
        self._tender_paths: List[str] = []
        self._last_tender_dir = ""
        self._sessions: List[ChatSession] = []
        self._session_index = -1
        self._step_index = 0

        self._build_ui()
        if self._selected_product_id:
            self._set_product_display(self._selected_product_id, self._selected_product_id)
            self._set_step(1)
        self.on_new_chat(initial=True)
        # 启动时自检 PDF 后端，避免「换解释器后抽不出」不好排查
        try:
            from elements_agent.pdf_backend import fitz_available
            import sys as _sys

            ok, info = fitz_available()
            if not ok:
                self._append_ai(
                    f"PDF 引擎未就绪（将无法读数据表）。当前解释器：`{_sys.executable}`\n{info}"
                )
        except Exception:
            pass

    def _build_ui(self):
        root = QWidget(self)
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        outer.addWidget(splitter)

        # —— 左侧 ——
        side = QFrame()
        side.setObjectName("Side")
        side.setMinimumWidth(228)
        side.setMaximumWidth(280)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 16, 14, 12)
        sl.setSpacing(6)

        brand = QLabel("元件定义")
        brand.setObjectName("SideBrand")
        sl.addWidget(brand)

        self.btn_extract = QPushButton("开始抽取材料")
        self.btn_extract.setObjectName("SidePrimary")
        self.btn_extract.clicked.connect(self.on_start_extract)
        sl.addWidget(self.btn_extract)

        self.btn_pick_product = QPushButton("选择产品")
        self.btn_pick_product.setObjectName("SideGhost")
        self.btn_pick_product.clicked.connect(self.on_pick_product)
        sl.addWidget(self.btn_pick_product)

        self.btn_pick_files = QPushButton("上传标书")
        self.btn_pick_files.setObjectName("SideGhost")
        self.btn_pick_files.clicked.connect(self.on_pick_tender)
        sl.addWidget(self.btn_pick_files)

        self.btn_new = QPushButton("新建对话")
        self.btn_new.setObjectName("SideGhost")
        self.btn_new.clicked.connect(lambda: self.on_new_chat(False))
        sl.addWidget(self.btn_new)

        cap1 = QLabel("抽取流程")
        cap1.setObjectName("SideCap")
        sl.addWidget(cap1)
        self.steps = QListWidget()
        self.steps.setObjectName("Steps")
        for s in _STEPS:
            self.steps.addItem(QListWidgetItem(s))
        self.steps.setCurrentRow(0)
        self.steps.setFixedHeight(148)
        sl.addWidget(self.steps)

        cap2 = QLabel("历史对话")
        cap2.setObjectName("SideCap")
        sl.addWidget(cap2)
        self.history = QListWidget()
        self.history.setObjectName("History")
        self.history.currentRowChanged.connect(self._on_history_changed)
        sl.addWidget(self.history, 1)

        self.lbl_model = QLabel(f"DeepSeek · {active_backend().split(':')[-1]}")
        self.lbl_model.setObjectName("Foot")
        sl.addWidget(self.lbl_model)
        splitter.addWidget(side)

        # —— 右侧 ——
        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(18, 14, 18, 12)
        ml.setSpacing(8)

        head = QHBoxLayout()
        self.lbl_chat_head = QLabel("元件定义录入")
        self.lbl_chat_head.setObjectName("ChatHead")
        head.addWidget(self.lbl_chat_head, 1)
        self.lbl_product = QLabel("未选产品")
        self.lbl_product.setObjectName("ProductPill")
        head.addWidget(self.lbl_product)
        self.btn_clear = QPushButton("清空对话")
        self.btn_clear.setObjectName("Ghost")
        self.btn_clear.clicked.connect(self.on_clear_current)
        head.addWidget(self.btn_clear)
        ml.addLayout(head)

        self.chat_view = QTextBrowser()
        self.chat_view.setObjectName("ChatView")
        self.chat_view.setOpenExternalLinks(False)
        ml.addWidget(self.chat_view, 1)

        self.composer = DropComposer(self)
        row = QHBoxLayout(self.composer)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(8)
        self.edit_input = QTextEdit()
        self.edit_input.setObjectName("Input")
        self.edit_input.setPlaceholderText("描述要抽取的内容，或把标书拖进来…")
        self.edit_input.setAcceptRichText(False)
        self.edit_input.setMaximumHeight(88)
        self.edit_input.installEventFilter(self)
        self.btn_send = QPushButton("发送")
        self.btn_send.setObjectName("Primary")
        self.btn_send.clicked.connect(self.on_send)
        row.addWidget(self.edit_input, 1)
        row.addWidget(self.btn_send, 0, Qt.AlignBottom)
        ml.addWidget(self.composer)

        tip = QLabel("Enter 发送 · Shift+Enter 换行 · 支持拖拽文件")
        tip.setObjectName("Foot")
        ml.addWidget(tip)

        splitter.addWidget(main)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

    def eventFilter(self, obj, event):
        if obj is getattr(self, "edit_input", None) and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (
                event.modifiers() & Qt.ShiftModifier
            ):
                self.on_send()
                return True
        return super().eventFilter(obj, event)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        if paths:
            self.add_tender_paths(paths)
        event.acceptProposedAction()

    def _set_step(self, idx: int):
        self._step_index = max(0, min(idx, len(_STEPS) - 1))
        self.steps.setCurrentRow(self._step_index)

    # —— 会话 ——
    def on_new_chat(self, initial: bool = False):
        sess = ChatSession(title="新对话")
        self._sessions.append(sess)
        self._session_index = len(self._sessions) - 1
        self._tender_paths = []
        self._pending = None
        if not self._selected_product_id:
            self._set_step(0)
        else:
            self._set_step(1)
        self.history.addItem(QListWidgetItem(f"{sess.created_at}  {sess.title}"))
        self.history.setCurrentRow(self._session_index)
        self._render_session()
        self._append_ai_card(
            "材料助手",
            "读数据表「结构材料」或采购清单，映射元件并反推材料四字段。",
            [
                "选择产品 → 上传管壳式换热器数据表 PDF",
                "点「开始抽取材料」，核对后写入",
                "也可直接说：管箱圆筒用 Q345R",
            ],
        )

    def on_clear_current(self):
        sess = self._current_session()
        if not sess:
            return
        sess.html_parts = []
        sess.messages = []
        self._render_session()
        self._append_ai("对话已清空。")

    def _on_history_changed(self, row: int):
        if row < 0 or row >= len(self._sessions):
            return
        self._session_index = row
        sess = self._sessions[row]
        self._tender_paths = list(sess.tender_paths)
        self._render_session()

    def _current_session(self) -> Optional[ChatSession]:
        if 0 <= self._session_index < len(self._sessions):
            return self._sessions[self._session_index]
        return None

    def _render_session(self):
        sess = self._current_session()
        if not sess:
            self.chat_view.setHtml("")
            return
        self.lbl_chat_head.setText(
            sess.title if sess.title != "新对话" else "元件定义录入"
        )
        self.chat_view.setHtml(
            "".join(sess.html_parts)
            or "<p style='color:#8a9199;font-size:11pt;'>开始对话吧</p>"
        )
        self.chat_view.moveCursor(QTextCursor.End)

    def _append_user(self, text: str):
        sess = self._current_session()
        if not sess:
            return
        sess.messages.append({"role": "user", "text": text})
        bubble = (
            f'<div style="margin:10px 0;text-align:right;">'
            f'<span style="display:inline-block;background:#eef3ff;color:#1f2329;'
            f'padding:8px 12px;border-radius:12px 12px 2px 12px;max-width:72%;'
            f'text-align:left;font-size:11.5pt;">{html.escape(text).replace(chr(10), "<br>")}'
            f"</span></div>"
        )
        sess.html_parts.append(bubble)
        if sess.title == "新对话":
            sess.title = (text[:22] + "…") if len(text) > 22 else text
            item = self.history.item(self._session_index)
            if item:
                item.setText(f"{sess.created_at}  {sess.title}")
        self._render_session()

    def _append_ai(self, text: str):
        sess = self._current_session()
        if not sess:
            return
        sess.messages.append({"role": "assistant", "text": text})
        body = self._md_lite(text)
        block = (
            f'<div style="margin:12px 0;max-width:88%;">'
            f'<div style="color:#2f6bff;font-size:10pt;margin-bottom:4px;">'
            f'<b>AI</b> · 材料助手</div>'
            f'<div style="font-size:11.5pt;line-height:1.55;color:#1f2329;">{body}</div>'
            f"</div>"
        )
        sess.html_parts.append(block)
        self._render_session()

    def _append_ai_card(self, title: str, lead: str, bullets: List[str]):
        items = "".join(
            f"<div style='margin:4px 0;color:#4e5969;'>· {html.escape(b)}</div>"
            for b in bullets
        )
        card = (
            f"<div style='margin:8px 0;padding:12px 14px;background:#f7f8fa;"
            f"border:1px solid #eef0f3;border-radius:12px;max-width:520px;'>"
            f"<div style='font-weight:600;font-size:12pt;margin-bottom:6px;'>"
            f"{html.escape(title)}</div>"
            f"<div style='color:#646a73;font-size:11pt;margin-bottom:8px;'>"
            f"{html.escape(lead)}</div>{items}</div>"
        )
        sess = self._current_session()
        if not sess:
            return
        sess.messages.append({"role": "assistant", "text": lead})
        block = (
            f'<div style="margin:12px 0;">'
            f'<div style="color:#2f6bff;font-size:10pt;margin-bottom:4px;">'
            f'<b>AI</b> · 材料助手</div>{card}</div>'
        )
        sess.html_parts.append(block)
        self._render_session()

    def _md_lite(self, text: str) -> str:
        s = html.escape(text or "")
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(
            r"`([^`]+)`",
            r"<code style='background:#f2f3f5;padding:1px 4px;border-radius:4px;'>\1</code>",
            s,
        )
        return s.replace("\n", "<br>")

    # —— 产品 / 文件 ——
    def _set_product_display(self, product_id: str, label: str = ""):
        self._selected_product_id = (product_id or "").strip()
        self._selected_product_label = (label or product_id or "").strip()
        short = self._selected_product_label
        if len(short) > 42:
            short = short[:40] + "…"
        self.lbl_product.setText(short or "未选产品")

    def _current_product_id(self) -> str:
        return (self._selected_product_id or "").strip()

    def on_pick_product(self):
        picked = pick_product(
            self,
            project_folder=self._selected_project_folder,
            current_product_id=self._selected_product_id,
        )
        if not picked:
            return
        pid = str(picked.get("产品ID") or "").strip()
        if not pid:
            QMessageBox.warning(self, "提示", "未获得产品ID")
            return
        folder = str(picked.get("_folder") or "").strip()
        if folder:
            self._selected_project_folder = folder
        name = str(picked.get("产品名称") or "").strip()
        tag = str(picked.get("设备位号") or "").strip()
        bits = [x for x in (name, tag) if x]
        label = f"{pid}" + (f" · {' · '.join(bits)}" if bits else "")
        self._set_product_display(pid, label)
        self._set_step(1 if not self._tender_paths else 2)
        self._append_ai(f"已选产品：**{pid}**")

    def on_pick_tender(self):
        start = self._last_tender_dir or ""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择标书（可多选）",
            start,
            "全部文件 (*.*);;Excel (*.xlsx *.xls);;PDF (*.pdf);;Word (*.doc *.docx)",
        )
        if files:
            self.add_tender_paths(files)
            return
        folder = QFileDialog.getExistingDirectory(self, "或选择文件夹", start)
        if folder:
            self.add_tender_paths([folder])

    def add_tender_paths(self, paths: List[str]):
        added = []
        for p in paths:
            p = os.path.abspath((p or "").strip())
            if not p:
                continue
            if os.path.isdir(p) or os.path.isfile(p):
                if p not in self._tender_paths:
                    self._tender_paths.append(p)
                    added.append(p)
                self._last_tender_dir = (
                    os.path.dirname(p) if os.path.isfile(p) else p
                )
        sess = self._current_session()
        if sess:
            sess.tender_paths = list(self._tender_paths)
            if added and sess.title == "新对话":
                sess.title = os.path.basename(added[0].rstrip("\\/"))[:28]
                item = self.history.item(self._session_index)
                if item:
                    item.setText(f"{sess.created_at}  {sess.title}")
        if added:
            self._set_step(2 if self._selected_product_id else 1)
            names = "、".join(
                os.path.basename(x.rstrip("\\/")) for x in added[:3]
            )
            more = f" 等{len(added)}个" if len(added) > 3 else ""
            tip = ""
            if any(
                "数据表" in os.path.basename(p) or "DDS" in os.path.basename(p).upper()
                for p in added
            ):
                tip = "（将解析「结构材料」）"
            self._append_ai(f"已添加：**{names}{more}**{tip}")

    def on_start_extract(self):
        """侧栏主按钮：有文件则直接抽取，否则引导选文件。"""
        if not self._current_product_id():
            self._append_ai("请先选择产品。")
            self.on_pick_product()
            return
        if not self._tender_paths:
            self._append_ai("请先上传标书，或把文件拖到输入框。")
            self.on_pick_tender()
            return
        self.edit_input.setPlainText("开始抽取")
        self.on_send()

    # —— 发送 ——
    def on_send(self):
        text = (self.edit_input.toPlainText() or "").strip()
        if not text and not self._tender_paths:
            return
        self.edit_input.clear()
        self._append_user(text or "开始抽取")

        if text and self._is_chitchat(text) and not self._looks_like_extract(text):
            self._reply_chitchat(text)
            return

        if not self._current_product_id():
            self._append_ai("请先选择产品。")
            self.on_pick_product()
            return

        if (
            self._tender_paths
            or self._looks_like_extract(text)
            or self._looks_like_material_cmd(text)
        ):
            self._run_extract_flow(text)
            return
        self._reply_chitchat(text)

    def _is_chitchat(self, text: str) -> bool:
        t = text.strip().lower()
        keys = ("你好", "您好", "在吗", "你是谁", "帮助", "help", "怎么用", "功能")
        return len(t) <= 20 and any(k in t for k in keys)

    def _looks_like_extract(self, text: str) -> bool:
        return any(
            k in (text or "")
            for k in ("抽取", "提取", "解析", "开始", "分析", "只要")
        )

    def _looks_like_material_cmd(self, text: str) -> bool:
        return bool(
            re.search(r"(用|改为|改成|换成|材料)", text or "")
            and re.search(r"[A-Za-z0-9]{2,}|牌号|钢板|钢管", text or "")
        )

    def _reply_chitchat(self, text: str):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if llm_available():
                ans = chat_completion(
                    "你是元件定义材料助手。用一两句中文简洁回答，引导选产品、上传标书、抽取确认。",
                    text,
                    timeout=40.0,
                )
                if ans:
                    self._append_ai(ans.strip()[:280])
                    return
            self._append_ai("选产品 → 上传标书 → 开始抽取。确认表通过后才会写库。")
        finally:
            QApplication.restoreOverrideCursor()

    def _run_extract_flow(self, user_text: str):
        self.btn_send.setEnabled(False)
        self.btn_extract.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        state = None
        try:
            self._set_step(2)
            state = run_pipeline(
                self._current_product_id(),
                user_text,
                extra_paths=list(self._tender_paths),
            )
            self._pending = state
            n = len(state.changes or [])
            ok_n = sum(
                1
                for ch in (state.changes or [])
                if ch.ok and ch.mapped and not ch.ambiguous and not ch.unmatched
            )
            if state.error and not n:
                self._append_ai(f"未抽出结果：{state.error}")
            else:
                self._append_ai_card(
                    "抽取完成",
                    f"候选 {n} 条 · 合法 {ok_n} 条 · {state.parse_source or '-'}",
                    ["请在待确认表中核对后写入"],
                )
        except Exception as e:
            self._pending = None
            self._append_ai(f"分析失败：{e}")
            QMessageBox.critical(self, "错误", f"分析失败：{e}")
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_send.setEnabled(True)
            self.btn_extract.setEnabled(True)

        if not state or not state.changes:
            return

        self._set_step(3)
        accepted, state = show_confirm_dialog(self, state)
        if not accepted:
            self._append_ai("已取消，未写入。")
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            applied = apply_pipeline(state, allow_partial=True)
            self._pending = applied
            if applied.applied:
                self._set_step(3)
                written = sum(
                    1
                    for line in (applied.report_lines or [])
                    if line.startswith("已更新")
                )
                self._append_ai(f"已写入活动库（约 {written or '若干'} 项）。打开「元件定义」可查看。")
            else:
                self._append_ai("写入未成功，请查看校验说明后重试。")
        except Exception as e:
            self._append_ai(f"写入失败：{e}")
            QMessageBox.critical(self, "错误", f"写入失败：{e}")
        finally:
            QApplication.restoreOverrideCursor()


def launch_agent_window(product_id: str = "") -> int:
    try:
        from elements_agent.local_config import apply_secrets_to_environ

        apply_secrets_to_environ()
    except Exception:
        pass

    app = QApplication.instance()
    owns = app is None
    if owns:
        app = QApplication([])
        app.setApplicationName("ElementDefineAgent")
        app.setStyle("Fusion")
        app.setFont(QFont("Microsoft YaHei UI", 10))

    win = ElementDefineAgentWindow(product_id=product_id)
    win.show()
    win.raise_()
    win.activateWindow()
    return app.exec_() if owns else 0
