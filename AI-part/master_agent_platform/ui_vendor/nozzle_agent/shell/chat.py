# -*- coding: utf-8 -*-
"""
对话式界面组件：消息气泡、Agent 回复卡片、输入框、消息流。

这一版不再嵌工业软件界面，只做"提问 - 回答"。
AgentReply 里的结构化信息（识别到的字段、错误、警告）在这里被拆成
人类读得懂的几段，而不是塞进一张表格。
"""
from __future__ import annotations

import os
from typing import List, Optional

from PyQt5.QtCore import QEvent, Qt, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import (
    QDesktopServices, QFont, QFontMetrics, QTextOption,
)
from PyQt5.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QScrollArea, QSizePolicy, QTextBrowser, QVBoxLayout, QWidget,
)

from agent.core import AgentReply
from . import chat_theme as T

MAX_BUBBLE = 820          # 正文最大宽度，超过就换行（参考图正文能铺得比较开）
MONO = '"Cascadia Mono", "Consolas", "JetBrains Mono", monospace'


# ---------------------------------------------------------------- 小工具
def _label(text: str = "", *, size: int = 13, color: str = T.TEXT,
           bold: bool = False, wrap: bool = True, rich: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(wrap)
    lab.setTextFormat(Qt.RichText if rich else Qt.PlainText)
    lab.setStyleSheet(f"color:{color};font-size:{size}px;"
                      + ("font-weight:600;" if bold else ""))
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lab


def _spacer_h() -> QWidget:
    w = QWidget()
    w.setFixedHeight(2)
    w.setStyleSheet("background:transparent;")
    return w


def _chip_html(rows: List[dict], value_color: str = T.TEXT) -> str:
    """把一批字段渲染成"名 值 · 名 值"的一行富文本。"""
    parts = []
    for r in rows:
        name = str(r.get("field") or "")
        val = str(r.get("value") or "")
        parts.append(
            f"<span style='color:{T.TEXT_MUTED};'>{name}</span>"
            f"&nbsp;<b style='color:{value_color};'>{_esc(val)}</b>"
        )
    return "&nbsp;&nbsp;<span style='color:#d5d9e0;'>·</span>&nbsp;&nbsp;".join(parts)


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace("\n", "<br>"))


def _short_name(name: str, keep: int = 22) -> str:
    """文件名太长就掐中间，标题栏放得下才看得清后缀。"""
    if len(name) <= keep:
        return name
    head = keep // 2 - 1
    return name[:head] + "…" + name[-(keep - head):]


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _elide(text: str, width: int = 390) -> str:
    """文件名可能很长，太长就省略中间，别把气泡撑爆。"""
    fm = QFontMetrics(QFont(T.FONT.split(",")[0].strip('" '), 9))
    return fm.elidedText(text, Qt.ElideMiddle, width)


def _local_files(mime) -> List[str]:
    """从拖放数据里取出真实存在的本地文件路径。"""
    if not mime.hasUrls():
        return []
    out: List[str] = []
    for url in mime.urls():
        if url.isLocalFile():
            path = url.toLocalFile()
            if os.path.isfile(path):
                out.append(path)
    return out


# ---------------------------------------------------------------- 用户气泡
class UserMessage(QWidget):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 6, 0, 6)
        outer.setSpacing(0)
        outer.addStretch(1)

        bubble = QFrame()
        bubble.setObjectName("UserBubble")
        bubble.setMaximumWidth(MAX_BUBBLE)
        bubble.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Minimum)
        lay = QVBoxLayout(bubble)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(2)
        # 自动换行的 QLabel 拿不到确定宽度，短句会被压成窄长条；
        # 短消息直接不换行，长消息才按气泡宽度折行。
        lay.addWidget(_label(text, size=13, color=T.TEXT,
                             wrap=len(text) > 46))
        outer.addWidget(bubble)


# ---------------------------------------------------------------- 文件消息
class UserFileMessage(QWidget):
    """用户发来的文件：显示成一张文件卡片，而不是一串 file:/// 路径。"""

    def __init__(self, name: str, size: int = 0, path: str = "", parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        self.path = path
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 6, 0, 6)
        outer.setSpacing(0)
        outer.addStretch(1)

        bubble = QFrame()
        bubble.setObjectName("UserBubble")
        bubble.setMaximumWidth(MAX_BUBBLE)
        bubble.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Minimum)
        lay = QVBoxLayout(bubble)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(6)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(9)

        badge = QLabel("PDF")
        badge.setFixedSize(34, 34)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            "background:#dc2626;color:#ffffff;border-radius:7px;"
            "font-size:9px;font-weight:700;letter-spacing:0.5px;")

        meta = f"{_human_size(size)} · PDF" if size else "PDF"
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        name_label = _label(_elide(name), size=12, color=T.TEXT, bold=True, wrap=False)
        name_label.setToolTip(name)          # 省略的文件名靠悬停看全
        col.addWidget(name_label)
        col.addWidget(_label(meta, size=11, color=T.TEXT_MUTED, wrap=False))

        row.addWidget(badge, 0, Qt.AlignVCenter)
        row.addLayout(col, 1)
        lay.addLayout(row)
        outer.addWidget(bubble)


def _row_meta(r: dict) -> str:
    """把一行管口压成「DN50 · 压力 5.0 · ASME B16.5 · RF」这样一行小字。"""
    parts = []
    if r.get("公称直径"):
        parts.append(f"DN{r['公称直径']}")
    if r.get("公称压力"):
        parts.append(f"压力 {r['公称压力']}")
    if r.get("法兰标准"):
        parts.append(r["法兰标准"])
    if r.get("法兰密封面型式"):
        parts.append(r["法兰密封面型式"])
    if r.get("接管等级"):
        parts.append(f"接管 {r['接管等级']}")
    if r.get("开口外伸高度"):
        parts.append(f"外伸 {r['开口外伸高度']}")
    return " · ".join(parts)


def _doc_head_html(res) -> str:
    """读到了：结论 + 逐行清单（一管口一行，方便和 PDF 对照）。"""
    out = [
        f'<p style="margin:0;font-size:13px;font-weight:600;color:{T.OK};">'
        f'{_esc(res.headline())}</p>',
        f'<p style="margin:3px 0 0 0;font-size:10px;color:{T.TEXT_FAINT};">'
        f'只读结果 · 单元格按原文保留，未做单位换算与取值映射</p>',
    ]

    for r in res.rows:
        out.append(
            f'<p style="margin:9px 0 0 0;font-size:12px;">'
            f'<b style="color:{T.ACCENT};">{_esc(r.get("序号", ""))}</b>'
            f'&nbsp;&nbsp;<b style="color:{T.TEXT};">{_esc(r.get("名称", ""))}</b></p>'
        )
        meta = _row_meta(r)
        if meta:
            out.append(f'<p style="margin:0;font-size:11px;color:{T.TEXT_MUTED};">'
                       f'{_esc(meta)}</p>')
    return "".join(out)


def _doc_tail_html(res) -> str:
    """进表前还要处理的问题 + 收尾说明。"""
    if not res.ok:
        return (
            f'<p style="margin:0;font-size:13px;font-weight:600;color:{T.ERR};">'
            f'{_esc(res.headline())}</p>'
            f'<p style="margin:6px 0 0 0;font-size:12px;color:{T.TEXT};">{_esc(res.error)}</p>'
            f'<p style="margin:6px 0 0 0;font-size:11px;color:{T.TEXT_MUTED};">'
            f'认表的口径：页面上要有标题（管口说明 / 接管表 / Nozzle schedule…）'
            f'或一张「序号 + 名称 + 管口属性」的表。扫描件（整页图片的 PDF）读不出来，得先 OCR。</p>'
        )

    out = []
    if res.notes:
        out.append(f'<p style="margin:14px 0 1px 0;font-size:10px;color:{T.TEXT_FAINT};">'
                   f'进表前还要处理</p>')
        for n in res.notes:
            out.append(f'<p style="margin:0;font-size:11px;color:{T.TEXT_MUTED};">· {_esc(n)}</p>')
    if getattr(res, "json_error", ""):
        out.append(f'<p style="margin:8px 0 0 0;font-size:11px;color:{T.WARN};">'
                   f'{_esc(res.json_error)}</p>')
    out.append(f'<p style="margin:12px 0 0 0;font-size:11px;color:{T.TEXT_FAINT};">'
               f'以上只是读取结果。要写进管口表，得先把这几处对不上项目的取值定下来。</p>')
    return "".join(out)


# ---------------------------------------------------------------- 代码块
class CodeBlock(QFrame):
    """
    结构化结果的代码块：标题栏（类型 / 规模 / 路径）+ 复制 / 保存 / 打开位置。

    对齐 Codex 那种 "```json" 块的观感——浅灰底、等宽字、右上角操作，
    但它是真控件而不是文本，所以能一键复制、一键落盘。

    只显示前十几行（够看清结构），不在这里做内部滚动：
    滚动区里套滚动区，滚轮会打架；要看全文有「复制」和「保存」。
    """

    PREVIEW_LINES = 11

    def __init__(self, text: str, *, kind: str = "json", meta: str = "",
                 path: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("CodeBlock")
        self._text = text or ""
        self._meta = meta
        self.path = path or ""
        self._preview, self._rest = self._make_preview(self._text)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QFrame()
        head.setObjectName("CodeHead")
        head.setFixedHeight(30)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(10, 0, 6, 0)
        hl.setSpacing(6)

        kind_lab = QLabel(kind)
        kind_lab.setObjectName("CodeKind")
        hl.addWidget(kind_lab)

        self.meta_lab = QLabel(meta)
        self.meta_lab.setObjectName("CodeMeta")
        self.meta_lab.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        hl.addWidget(self.meta_lab, 1)

        self.copy_btn = self._btn("复制", "复制内容到剪贴板")
        self.copy_btn.clicked.connect(self._copy)
        hl.addWidget(self.copy_btn)

        self.save_btn = self._btn("保存", "另存为 .json 文件")
        self.save_btn.clicked.connect(self._save)
        hl.addWidget(self.save_btn)

        self.open_btn = self._btn("位置", "打开文件所在文件夹")
        self.open_btn.setEnabled(bool(self.path))
        self.open_btn.clicked.connect(self._reveal)
        hl.addWidget(self.open_btn)

        body = QPlainTextEdit()
        body.setObjectName("CodeBody")
        body.setPlainText(self._preview)
        body.setReadOnly(True)
        body.setFrameShape(QFrame.NoFrame)
        body.setFont(QFont("Consolas", 9))
        body.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        body.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body.document().setDocumentMargin(8)
        self.body = body
        self._fit_w = -1

        lay.addWidget(head)
        lay.addWidget(body)

        self._meta_timer = QTimer(self)
        self._meta_timer.setSingleShot(True)
        self._meta_timer.timeout.connect(lambda: self.meta_lab.setText(self._meta))
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(lambda: self.copy_btn.setText("复制"))

    # ---- 预览文本 ----
    def _make_preview(self, text: str):
        """只留前 N 行，尾部补一句"还有多少行"。返回 (预览文本, 省略行数)。"""
        lines = text.splitlines()
        if len(lines) <= self.PREVIEW_LINES:
            return text, 0
        keep = lines[:self.PREVIEW_LINES]
        rest = len(lines) - len(keep)
        keep.append(f"  … 还有 {rest} 行（完整内容点「复制」或「保存」）")
        return "\n".join(keep), rest

    # ---- 高度：按"折行后的实际行数"算，再留一行余量 ----
    # 不用 QPlainTextDocumentLayout 的 size()（在 QPlainTextEdit 里它报的是视口高度），
    # 也不用 blockCount 直接乘（长行会折行）。等宽字体下用 QFontMetrics 量最稳。
    def _visual_lines(self, avail: int) -> int:
        doc = self.body.document()
        fm = self.body.fontMetrics()
        total = 0
        for i in range(doc.blockCount()):
            text = doc.findBlockByNumber(i).text()
            total += 1 if not text else max(1, -(-fm.horizontalAdvance(text) // avail))
        return max(1, total)

    def _fit(self):
        w = self.body.viewport().width()
        if w <= 20:
            return
        if abs(w - self._fit_w) < 2:
            return
        self._fit_w = w

        line = self.body.fontMetrics().lineSpacing()
        margin = int(self.body.document().documentMargin())
        lines = self._visual_lines(max(1, w - 2 * margin))
        # 多给一行：宁可底部空一点，也不能把最后一行切一半
        self.body.setFixedHeight(line * (lines + 1) + margin)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit()

    # ---- 构造 ----
    def _btn(self, text: str, tip: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("CodeBtn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(tip)
        btn.setFixedHeight(22)
        return btn

    # ---- 动作 ----
    def _copy(self):
        QApplication.clipboard().setText(self._text)
        self.copy_btn.setText("已复制")
        self._copy_timer.start(1800)

    def _save(self):
        default = self.path or os.path.join(os.path.expanduser("~"), "nozzles.json")
        path, _ = QFileDialog.getSaveFileName(
            self, "保存 JSON", default, "JSON 文件 (*.json);;所有文件 (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(self._text)
        except PermissionError:
            self._flash(f"保存失败：{os.path.basename(path)} 正被其他程序占用")
            return
        except OSError as exc:
            self._flash(f"保存失败：{exc.strerror or exc}")
            return
        self.path = path
        self.open_btn.setEnabled(True)
        self._flash(f"已保存 {os.path.basename(path)}")

    def _reveal(self):
        folder = os.path.dirname(self.path)
        if folder and os.path.isdir(folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _flash(self, msg: str, ms: int = 2600):
        self.meta_lab.setText(msg)
        self._meta_timer.start(ms)


class DocMessage(QWidget):
    """AI 侧：一份文件读出来的结果（可读清单 + 结构化 JSON）。"""

    def __init__(self, res, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 10, 0, 10)
        outer.setSpacing(0)

        host = QWidget()
        host.setStyleSheet("background:transparent;")
        host.setMaximumWidth(MAX_BUBBLE + 40)
        host.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        col = QVBoxLayout(host)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        col.addWidget(_label("AI 助手", size=10, color=T.TEXT_FAINT, wrap=False))
        col.addWidget(RichBlock(_doc_head_html(res)))

        json_text = getattr(res, "json_text", "")
        if json_text:
            size = _human_size(len(json_text.encode("utf-8")))
            meta = f"{len(res.rows)} 个管口 · {size}"
            path = getattr(res, "json_path", "")
            if path:
                meta += f" · {_short_name(os.path.basename(path))}"
            block = CodeBlock(json_text, kind="json · 管口清单", meta=meta, path=path)
            if path:
                block.meta_lab.setToolTip(path)
            col.addWidget(block)

        col.addWidget(RichBlock(_doc_tail_html(res)))

        outer.addWidget(host, 100)
        outer.addStretch(1)


# ---------------------------------------------------------------- 富文本块
class RichBlock(QTextBrowser):
    """
    高度自适应的富文本块。

    为什么不用一堆 QLabel 叠 QVBoxLayout：自动换行的 QLabel 在
    QScrollArea 里拿不到确定的宽度，sizeHint 会按"不换行"算，
    结果内容一多就被压扁、文字叠在一起。这里改成让 QTextDocument
    自己排版，再按文档高度 setFixedHeight，高度永远是对的。
    """

    def __init__(self, html: str = "", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("QTextBrowser{background:transparent;border:none;}")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setOpenExternalLinks(False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.document().setDocumentMargin(0)
        self._fit_w = -1
        self.setHtml(html)

    def setRichHtml(self, html: str):
        self._fit_w = -1
        self.setHtml(html)
        self._fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit()

    def _fit(self):
        w = self.viewport().width()
        if w <= 20:
            w = 600                      # 还没布局好时先按这个宽度估
        if abs(w - self._fit_w) < 2:
            return
        self._fit_w = w
        doc = self.document()
        doc.setTextWidth(w)
        self.setFixedHeight(max(18, int(round(doc.size().height())) + 2))


# ---------------------------------------------------------------- 回复卡片
def _group(title: str, body: str, top: int = 10) -> str:
    return (
        f'<p style="margin:{top}px 0 1px 0;font-size:10px;color:{T.TEXT_FAINT};">{title}</p>'
        f'<p style="margin:0;font-size:12px;">{body}</p>'
    )


def _reply_html(reply: AgentReply) -> str:
    # 闲聊（action=chat）不是"操作结果"，用普通正文色，别用绿色成功色
    is_chat = reply.action == "chat"
    color = T.ERR if reply.errors else T.TEXT
    weight = "600"
    out = [f'<p style="margin:0;font-size:13px;font-weight:{weight};color:{color};">'
           f'{_esc(reply.headline or "（无输出）")}</p>']

    inputs = [r for r in reply.recognized if r.get("source") in ("输入", "修改")]
    copied = [r for r in reply.recognized
              if str(r.get("source") or "").startswith("复制自")]
    autos = [r for r in reply.recognized
             if r.get("source") not in ("输入", "修改")
             and not str(r.get("source") or "").startswith("复制自")]

    if inputs:
        out.append(_group("你给出的参数", _chip_html(inputs)))
    if copied:
        base = str(copied[0].get("source") or "").replace("复制自 ", "")
        out.append(_group(f"继承自 {base}", _chip_html(copied, T.OK), top=8))
    if autos:
        shown = autos[:6]
        body = _chip_html(shown, "#4b5563")
        if len(autos) > len(shown):
            body += (f"&nbsp;<span style='color:{T.TEXT_FAINT};'>"
                     f"… 另 {len(autos) - len(shown)} 项</span>")
        out.append(_group("自动补全", body, top=8))

    for title, issues, c in (("不合法，未写入表格", reply.errors, T.ERR),
                             ("需要确认", reply.warnings, T.WARN)):
        if not issues:
            continue
        out.append(f'<p style="margin:10px 0 1px 0;font-size:10px;'
                   f'color:{T.TEXT_FAINT};">{title}</p>')
        for it in issues:
            mark = "✗" if it.level == "error" else "!"
            out.append(
                f'<p style="margin:0;font-size:12px;">'
                f'<span style="color:{c};">{mark}</span> '
                f'<b style="color:{c};">{_esc(it.field)}</b> '
                f'<span style="color:{T.TEXT};">{_esc(it.message)}</span></p>'
            )
            if it.suggestion:
                out.append(f'<p style="margin:0 0 3px 0;font-size:11px;'
                           f'color:{T.TEXT_MUTED};">建议：{_esc(it.suggestion)}</p>')

    if reply.action_text:
        out.append(
            f'<p style="margin:10px 0 0 0;font-size:10px;color:{T.TEXT_FAINT};">执行</p>'
            f'<p style="margin:0;font-size:12px;color:#374151;'
            f'background-color:#eceff4;">&nbsp;{_esc(reply.action_text)}</p>'
        )

    # 闲聊里的引导语是正文，不该像"补充说明"那样淡；操作结果里的备注则可以淡一些
    sub_color = T.TEXT_MUTED if is_chat else T.TEXT_FAINT
    sub_size = 12 if is_chat else 11
    for line in reply.extra_lines:
        out.append(f'<p style="margin:4px 0 0 0;font-size:{sub_size}px;'
                   f'color:{sub_color};">{_esc(line)}</p>')

    return "".join(out)


class ReplyCard(RichBlock):
    """把 AgentReply 渲染成：结论 / 你给的 / 继承的 / 自动补的 / 问题 / 执行结果。"""

    def __init__(self, reply: AgentReply, parent=None):
        super().__init__(_reply_html(reply), parent)


# ---------------------------------------------------------------- Agent 消息
class AgentMessage(QWidget):
    def __init__(self, reply: Optional[AgentReply] = None,
                 text: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 10, 0, 10)
        outer.setSpacing(0)

        # 参考图里助手没有头像圈，只有一行小字「AI 助手」压在正文上方；
        # 少了那个彩色圆点，整块看起来更像文档、不像聊天软件。
        col_host = QWidget()
        col_host.setStyleSheet("background:transparent;")
        col_host.setMaximumWidth(MAX_BUBBLE + 40)
        col_host.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        col = QVBoxLayout(col_host)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        col.addWidget(_label("AI 助手", size=10, color=T.TEXT_FAINT, wrap=False))
        if reply is not None:
            col.addWidget(ReplyCard(reply))
        else:
            col.addWidget(RichBlock(
                f'<p style="margin:0;font-size:13px;line-height:1.75;">{_esc(text or "")}</p>'))

        # 比重 100:1：先把正文拉到最大宽度（MAX_BUBBLE），剩下的空档才留给
        # 右侧。只用 addStretch 会让整块被居中。
        outer.addWidget(col_host, 100)
        outer.addStretch(1)


# ---------------------------------------------------------------- 思考中
class ThinkingMessage(QWidget):
    def __init__(self, text: str = "正在解析", parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 10, 0, 10)
        outer.setSpacing(8)
        self._base = text
        self.text = _label(f"{text}…", size=11, color=T.TEXT_FAINT, wrap=False)
        outer.addWidget(self.text, 0, Qt.AlignTop)
        outer.addStretch(1)

        self._dots = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(320)

    def _tick(self):
        self._dots = (self._dots + 1) % 4
        self.text.setText(self._base + "·" * self._dots)

    def stop(self):
        self._timer.stop()


# ---------------------------------------------------------------- 空状态
class Welcome(QWidget):
    suggestion = pyqtSignal(str)

    SAMPLES = [
        "添加 N1，DN100，Class 300，突面，管程入口",
        "再加 N2，DN80，PN16，RF，壳程入口",
        "按顺序加 N3、N4，参数和 N2 一致",
        "检查所有管口是否合规",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 34, 2, 16)
        lay.setSpacing(6)
        lay.addStretch(1)

        title = _label("管口定义助手", size=16, color=T.TEXT, bold=True, wrap=False)
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        sub = _label("用一句话描述要加的管口，或者直接上传数据表 PDF 让我先识别。",
                     size=12, color=T.TEXT_MUTED)
        sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(sub)
        lay.addSpacing(14)

        box = QWidget()
        box.setStyleSheet("background:transparent;")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(7)
        for text in self.SAMPLES:
            btn = QPushButton(text)
            btn.setObjectName("SuggestionCard")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(34)
            btn.clicked.connect(lambda _=False, t=text: self.suggestion.emit(t))
            bl.addWidget(btn)

        row = QHBoxLayout()
        row.addStretch(1)
        box.setMaximumWidth(420)
        row.addWidget(box, 3)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(2)


# ---------------------------------------------------------------- 输入框
class ChatInput(QFrame):
    submitted = pyqtSignal(str)
    filesDropped = pyqtSignal(list)
    attachClicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Composer")
        self.setAcceptDrops(True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 6, 6)
        lay.setSpacing(8)

        self.attach = QPushButton("＋")
        self.attach.setObjectName("AttachBtn")
        self.attach.setCursor(Qt.PointingHandCursor)
        self.attach.setFixedSize(28, 28)
        self.attach.setToolTip("添加数据表 PDF（也可以直接把文件拖进来）")
        self.attach.clicked.connect(self.attachClicked)

        self.edit = _InputEdit()
        self.edit.setObjectName("ChatInput")
        self.edit.setPlaceholderText("描述你要录入的内容，或拖入数据表 PDF")
        self.edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.edit.setFrameShape(QFrame.NoFrame)
        self.edit.setFixedHeight(self._height_for(1))
        self.edit.setCursorWidth(0)
        self.edit.document().setDocumentMargin(0)
        self.edit.textChanged.connect(self._on_text_changed)
        self.edit.sendRequested.connect(self._emit)
        # 文本框中途拦截拖放会插进一串路径，交给外层 ChatInput 统一处理
        self.edit.setAcceptDrops(False)
        self.edit.viewport().setAcceptDrops(False)

        self.send = QPushButton("发送")
        self.send.setObjectName("SendBtn")
        self.send.setCursor(Qt.PointingHandCursor)
        self.send.setFixedHeight(32)
        self.send.setEnabled(False)
        self.send.clicked.connect(self._emit)

        lay.addWidget(self.attach, 0, Qt.AlignBottom)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.send, 0, Qt.AlignBottom)

    # ---- 拖放：整条输入框都是投放区 ----
    def dragEnterEvent(self, event):
        if _local_files(event.mimeData()):
            event.acceptProposedAction()
            self._set_drag_active(True)
        else:
            super().dragEnterEvent(event)

    def dragLeaveEvent(self, event):
        self._set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        files = _local_files(event.mimeData())
        self._set_drag_active(False)
        if files:
            event.acceptProposedAction()
            self.filesDropped.emit(files)
        else:
            super().dropEvent(event)

    def _set_drag_active(self, on: bool):
        if self.property("dragActive") == on:
            return
        self.setProperty("dragActive", on)
        self.style().unpolish(self)
        self.style().polish(self)

    # ---- 高度随行数增长（1~5 行）----
    def _height_for(self, lines: int) -> int:
        fm = self.edit.fontMetrics()
        return fm.lineSpacing() * lines + 12

    def _on_text_changed(self):
        text = self.edit.toPlainText()
        # 空输入时把光标宽度设 0：否则那根竖线正好压在占位文字的
        # 第一个字上，看起来像文字被裁掉了。
        self.edit.setCursorWidth(1 if text else 0)
        self.send.setEnabled(bool(text.strip()))
        rows = min(max(1, self.edit.document().blockCount()), 5)
        self.edit.setFixedHeight(self._height_for(rows))

    def _emit(self):
        text = self.edit.toPlainText().strip()
        if not text:
            return
        self.edit.clear()
        self.edit.setCursorWidth(0)
        self.edit.setFixedHeight(self._height_for(1))
        self.submitted.emit(text)

    def set_enabled_state(self, on: bool):
        self.edit.setReadOnly(not on)
        self.attach.setEnabled(on)
        self.send.setEnabled(on and bool(self.edit.toPlainText().strip()))

    def focus(self):
        self.edit.setFocus()


class _InputEdit(QPlainTextEdit):
    sendRequested = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)      # Shift+Enter 换行
            else:
                self.sendRequested.emit()
            return
        super().keyPressEvent(event)


# ---------------------------------------------------------------- 消息流
class ChatView(QScrollArea):
    suggestion = pyqtSignal(str)
    filesDropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatScroll")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)

        self.host = QWidget()
        self.host.setObjectName("MsgArea")
        self.lay = QVBoxLayout(self.host)
        self.lay.setContentsMargins(22, 6, 22, 14)
        self.lay.setSpacing(0)
        self.lay.addStretch(1)
        self.setWidget(self.host)

        self.welcome = Welcome()
        self.welcome.suggestion.connect(self.suggestion)
        self.lay.insertWidget(0, self.welcome)

        self._items: List[QWidget] = []
        self.setAcceptDrops(True)
        # QScrollArea 的拖放事件实际落在 viewport 上，不设这个就收不到
        self.viewport().setAcceptDrops(True)

    # ---- 拖放：整块消息区都能接文件 ----
    def viewportEvent(self, event):
        et = event.type()
        if et in (QEvent.DragEnter, QEvent.DragMove):
            if _local_files(event.mimeData()):
                event.acceptProposedAction()
                return True
        elif et == QEvent.Drop:
            files = _local_files(event.mimeData())
            if files:
                event.acceptProposedAction()
                self.filesDropped.emit(files)
                return True
        return super().viewportEvent(event)

    def dragEnterEvent(self, event):
        if _local_files(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        files = _local_files(event.mimeData())
        if files:
            event.acceptProposedAction()
            self.filesDropped.emit(files)
        else:
            super().dropEvent(event)

    # ---- 增删 ----
    def _append(self, w: QWidget):
        self.lay.insertWidget(self.lay.count() - 1, w)
        self._items.append(w)
        self._scroll_bottom()

    def add_user(self, text: str):
        self.welcome.hide()
        self._append(UserMessage(text))

    def add_file(self, name: str, size: int = 0, path: str = ""):
        self.welcome.hide()
        self._append(UserFileMessage(name, size, path))

    def add_doc(self, res):
        self.welcome.hide()
        msg = DocMessage(res)
        self._append(msg)

    def add_agent(self, reply: AgentReply):
        self.welcome.hide()
        self._append(AgentMessage(reply=reply))

    def add_plain(self, text: str):
        self.welcome.hide()
        self._append(AgentMessage(text=text))

    def add_thinking(self, text: str = "正在解析") -> ThinkingMessage:
        self.welcome.hide()
        w = ThinkingMessage(text)
        self._append(w)
        return w

    def remove(self, w: Optional[QWidget]):
        if w is None:
            return
        if isinstance(w, ThinkingMessage):
            w.stop()
        if w in self._items:
            self._items.remove(w)
        self.lay.removeWidget(w)
        w.setParent(None)
        w.deleteLater()

    def clear_all(self):
        for w in list(self._items):
            if isinstance(w, ThinkingMessage):
                w.stop()
            self.lay.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self._items.clear()
        self.welcome.show()

    def empty(self) -> bool:
        return not self._items

    # ---- 滚动 ----
    def _scroll_bottom(self):
        # 富文本块要等 showEvent 才算出真实高度，滚太早会停在半路，所以滚两次
        for delay in (0, 60, 140):
            QTimer.singleShot(delay, self._do_scroll)

    def _do_scroll(self):
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())
