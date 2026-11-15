# -*- coding: utf-8 -*-
"""分析预览弹出框（抽取结果摘要，确认后进入待确认表）。"""

from __future__ import annotations

from typing import List, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from elements_agent.models import AgentState


class PreviewDialog(QDialog):
    def __init__(self, state: AgentState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("分析预览 — 元件定义 Agent")
        self.resize(900, 640)
        self.setMinimumSize(720, 480)
        self.setFont(QFont("Microsoft YaHei UI", 11))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        title = QLabel("Agent · 分析预览")
        title.setStyleSheet("font-size:16pt; font-weight:700; color:#2f6bff;")
        lay.addWidget(title)

        meta = QLabel(
            f"产品：{state.product_id or '（未选）'}　"
            f"模式：{state.mode or '-'}　"
            f"解析：{state.parse_source or '-'}"
        )
        meta.setStyleSheet("color:#8a9199; font-size:11pt;")
        meta.setWordWrap(True)
        lay.addWidget(meta)

        self.view = QTextBrowser()
        self.view.setStyleSheet(
            "QTextBrowser{background:#f7f8fa;border:1px solid #eef0f3;"
            "border-radius:10px;padding:12px;font-family:Consolas,'Microsoft YaHei UI';"
            "font-size:12pt;color:#2b2f36;}"
        )
        lines = list(state.report_lines or [])
        if state.error:
            lines = [f"错误：{state.error}"] + lines
        body = "<br>".join(_esc(x) for x in lines)
        self.view.setHtml(
            f'<div style="line-height:1.65; white-space:pre-wrap;">{body}</div>'
        )
        lay.addWidget(self.view, 1)

        tip = QLabel(
            "点「下一步：待确认表」可编辑抽取结果并写入；点「关闭」仅保留对话记录、不写库。"
            if (state.changes and any(ch.ok for ch in state.changes))
            else "当前没有可写入的合法项。可关闭后补充文字指导或更换标书再抽。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#646a73; font-size:11pt;")
        lay.addWidget(tip)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.reject)
        self.btn_next = QPushButton("下一步：待确认表")
        self.btn_next.setStyleSheet(
            "QPushButton{background:#2f6bff;color:#fff;border:none;border-radius:8px;"
            "padding:10px 18px;font-weight:600;}"
            "QPushButton:hover{background:#2458d6;}"
            "QPushButton:disabled{background:#a8b8e8;}"
        )
        has_ok = any(
            ch.ok and ch.mapped and not ch.ambiguous and not ch.unmatched
            for ch in (state.changes or [])
        )
        # 有变更行（含不合法）也允许进入确认表查看/改
        can_next = bool(state.changes)
        self.btn_next.setEnabled(can_next)
        if not can_next:
            self.btn_next.setToolTip("没有可核对的抽取结果")
        elif not has_ok:
            self.btn_next.setToolTip("结果可能不合法，仍可进入表中修改后重校验")
        self.btn_next.clicked.connect(self.accept)
        row.addWidget(self.btn_close)
        row.addWidget(self.btn_next)
        lay.addLayout(row)


def _esc(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def show_preview_dialog(parent, state: AgentState) -> bool:
    """弹出分析预览；用户点「下一步」返回 True。"""
    dlg = PreviewDialog(state, parent)
    return dlg.exec_() == QDialog.Accepted
