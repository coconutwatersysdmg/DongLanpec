# -*- coding: utf-8 -*-
"""
待确认核对窗：
  左表 = 产品全部元件 · 当前四字段 vs 抽取四字段
  右侧 = PDF 解析依据（涂色高亮）
"""

from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from elements_agent.graph import revalidate_pipeline
from elements_agent.models import MATERIAL_FIELDS, AgentState, ValidatedChange

DIALOG_QSS = """
QDialog {
  background:#f5f6f8;
  font-family:"Microsoft YaHei UI","Segoe UI",sans-serif;
}
QLabel#DlgTitle { font-size:14pt; font-weight:700; color:#1f2329; }
QLabel#DlgMeta { font-size:10pt; color:#8a9199; }
QLabel#DlgSummary { font-size:10.5pt; color:#4e5969; }
QLabel#EvidenceTitle { font-size:11pt; font-weight:600; color:#1f2329; }
QTableWidget {
  background:#fff; border:1px solid #e5e6eb; border-radius:10px;
  gridline-color:#eef0f3; font-size:10.5pt;
  selection-background-color:#eef3ff; selection-color:#1f2329;
}
QHeaderView::section {
  background:#f7f8fa; color:#4e5969; padding:8px 6px; border:none;
  border-right:1px solid #eef0f3; border-bottom:1px solid #e5e6eb;
  font-size:10.5pt; font-weight:600;
}
QPushButton#ConfirmBtn {
  background:#2f6bff; color:#fff; border:none; border-radius:8px;
  padding:9px 20px; font-size:11pt; font-weight:600; min-width:88px;
}
QPushButton#ConfirmBtn:hover { background:#2458d6; }
QPushButton#ConfirmBtn:disabled { background:#a8b8e8; }
QPushButton#CancelBtn, QPushButton#RevalidateBtn {
  background:#fff; color:#1f2329; border:1px solid #e5e6eb; border-radius:8px;
  padding:9px 14px; font-size:11pt;
}
QPushButton#CancelBtn:hover, QPushButton#RevalidateBtn:hover {
  border-color:#2f6bff; color:#2f6bff;
}
QLabel#EvidenceView {
  background:#fff; border:1px solid #e5e6eb; border-radius:10px; color:#8a9199;
}
"""

_OK_BG = QColor("#e8f8ef")
_BAD_BG = QColor("#fdecc8")
_WARN_BG = QColor("#fff3e0")
_SKIP_BG = QColor("#f7f8fa")
_ERR_FG = QColor("#c45600")
_ERR_CELL = QColor("#ffd6d6")
_HIGHLIGHT = QColor(47, 107, 255, 70)

_FIELD_SHORT = {
    "材料类型": "类型",
    "材料牌号": "牌号",
    "材料标准": "标准",
    "供货状态": "状态",
}

# 元件 / 当前 / 抽取 / 状态 / 原因 / 依据
_COL_RATIOS = (0.12, 0.20, 0.22, 0.08, 0.20, 0.18)


def _status_text(ch: ValidatedChange) -> str:
    if not (ch.new_values or {}) and not (
        ch.intent and any(ch.intent.as_selected().values())
    ):
        return "未抽取"
    if ch.unmatched:
        return "未匹配"
    if ch.ambiguous:
        return "歧义"
    if not ch.ok:
        return "不合法"
    return "将修改"


def _status_brush(ch: ValidatedChange) -> QBrush:
    st = _status_text(ch)
    if st == "将修改":
        return QBrush(_OK_BG)
    if st == "未抽取":
        return QBrush(_SKIP_BG)
    if st == "歧义":
        return QBrush(_WARN_BG)
    return QBrush(_BAD_BG)


def _shorten(text: str, n: int = 56) -> str:
    t = (text or "").strip().replace("\n", " ")
    return t if len(t) <= n else t[: n - 1] + "…"


def _format_fields(values: dict, blank: str = "—") -> str:
    lines = []
    for k in MATERIAL_FIELDS:
        v = (values.get(k) or "").strip() or blank
        lines.append(f"{_FIELD_SHORT.get(k, k)}: {v}")
    return "\n".join(lines)


def _parse_new_values_text(text: str) -> dict:
    out = {k: "" for k in MATERIAL_FIELDS}
    short_to_full = {v: k for k, v in _FIELD_SHORT.items()}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line in ("—", "-"):
            continue
        if ":" in line or "：" in line:
            sep = "：" if "：" in line else ":"
            k, _, v = line.partition(sep)
            k, v = k.strip(), v.strip()
            full = short_to_full.get(k, k)
            if full in MATERIAL_FIELDS:
                out[full] = "" if v in ("（空）", "(空)", "—", "") else v
        elif not out["材料牌号"]:
            out["材料牌号"] = line
    return out


def _evidence_text(ch: ValidatedChange) -> str:
    if ch.intent and ch.intent.evidence:
        return _shorten(ch.intent.evidence.label(), 48)
    return "—"


def _reason_text(ch: ValidatedChange) -> str:
    """不能正常替换/写入的原因（给「原因」列）。"""
    st = _status_text(ch)
    if st == "将修改":
        return "—"
    if st == "未抽取":
        return "数据表未给出该元件材料，或别名未映射"
    if st == "未匹配":
        return _shorten(
            "；".join(ch.reasons) if ch.reasons else "产品中无此元件",
            72,
        )
    if st == "歧义":
        return _shorten(
            "；".join(ch.reasons) if ch.reasons else "匹配到多个元件，需人工指定",
            72,
        )
    # 不合法：优先展示类型冲突说明，去掉「自动补全/本次只改了」噪音
    if ch.reasons:
        preferred = ""
        others = []
        for r in ch.reasons:
            s = (r or "").strip()
            if not s:
                continue
            if "元件允许材料类型表" in s or "不存在「" in s:
                preferred = s
            elif s.startswith("自动补全"):
                continue
            else:
                others.append(s)
        raw = preferred or "；".join(others)
        raw = re.sub(r"（本次只改了[^）]*）", "", raw)
        return _shorten(
            raw.strip("； ") or "材料表中无合法组合，请改抽取材料后重校验",
            120,
        )
    return "材料表校验未通过，请改抽取材料后重校验"


def _render_pdf_page_with_bbox(
    file_path: str,
    page_no: int,
    bbox: Optional[Tuple[float, float, float, float]],
    max_w: int = 520,
) -> QPixmap:
    """渲染 PDF 页并涂色标注 bbox。"""
    if not file_path or not os.path.isfile(file_path) or page_no < 1:
        return QPixmap()
    try:
        from elements_agent.pdf_backend import get_fitz

        fitz = get_fitz()
        doc = fitz.open(file_path)
        try:
            if page_no > doc.page_count:
                return QPixmap()
            page = doc[page_no - 1]
            zoom = 1.6
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
        finally:
            doc.close()

        fmt = QImage.Format_RGBA8888 if pix.alpha else QImage.Format_RGB888
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()
        painter = QPainter(img)
        if bbox:
            x0, y0, x1, y1 = bbox
            rect = (
                int(x0 * zoom),
                int(y0 * zoom),
                int((x1 - x0) * zoom),
                int((y1 - y0) * zoom),
            )
            painter.fillRect(*rect, _HIGHLIGHT)
            pen = QPen(QColor("#2f6bff"))
            pen.setWidth(3)
            painter.setPen(pen)
            painter.drawRect(*rect)
        painter.end()
        pm = QPixmap.fromImage(img)
        if pm.width() > max_w and max_w > 0:
            pm = pm.scaledToWidth(max_w, Qt.SmoothTransformation)
        return pm
    except Exception as e:
        print(f"[confirm] 渲染 PDF 失败: {e}")
        return QPixmap()


class ConfirmMaterialDialog(QDialog):
    def __init__(self, state: AgentState, parent=None):
        super().__init__(parent)
        self.state = state
        self._row_changes: List[Tuple[ValidatedChange, Optional[int]]] = []
        self.setWindowTitle("材料核对 · 抽取对比")
        self.resize(1280, 780)
        self.setMinimumSize(1000, 600)
        self.setStyleSheet(DIALOG_QSS)
        self.setFont(QFont("Microsoft YaHei UI", 10))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._build_ui()
        self._fill_table()
        self._update_summary_and_buttons()
        QTimer.singleShot(0, self._apply_column_widths)
        QTimer.singleShot(50, self._fit_row_heights)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._apply_column_widths)
        QTimer.singleShot(30, self._fit_row_heights)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_column_widths()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("材料核对")
        title.setObjectName("DlgTitle")
        head.addWidget(title)
        head.addStretch(1)
        meta = QLabel(
            f"{self.state.product_id}  ·  绿=可写入 · 灰=未抽取 · 橙=需改"
        )
        meta.setObjectName("DlgMeta")
        head.addWidget(meta)
        layout.addLayout(head)

        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(6)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["元件", "当前材料", "抽取材料（可改）", "状态", "原因", "依据"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setWordWrap(True)
        self.table.setTextElideMode(Qt.ElideRight)
        hh = self.table.horizontalHeader()
        hh.setStretchLastSection(False)
        hh.setMinimumSectionSize(64)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hh.setSectionResizeMode(QHeaderView.Interactive)
        ll.addWidget(self.table, 1)
        splitter.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        ev_title = QLabel("解析依据（PDF 标注）")
        ev_title.setObjectName("EvidenceTitle")
        rl.addWidget(ev_title)
        self.evidence_view = QLabel("选中一行查看标注")
        self.evidence_view.setObjectName("EvidenceView")
        self.evidence_view.setAlignment(Qt.AlignCenter)
        self.evidence_view.setMinimumWidth(360)
        self.evidence_view.setMinimumHeight(420)
        self.evidence_view.setScaledContents(False)
        rl.addWidget(self.evidence_view, 1)
        self.lbl_ev_meta = QLabel("")
        self.lbl_ev_meta.setObjectName("DlgMeta")
        self.lbl_ev_meta.setWordWrap(True)
        rl.addWidget(self.lbl_ev_meta)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        foot = QHBoxLayout()
        self.lbl_summary = QLabel()
        self.lbl_summary.setObjectName("DlgSummary")
        foot.addWidget(self.lbl_summary)
        foot.addStretch(1)

        self.btn_revalidate = QPushButton("重校验")
        self.btn_revalidate.setObjectName("RevalidateBtn")
        self.btn_revalidate.clicked.connect(self._on_revalidate)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("CancelBtn")
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_confirm = QPushButton("确认写入")
        self.btn_confirm.setObjectName("ConfirmBtn")
        self.btn_confirm.clicked.connect(self._on_confirm)

        foot.addWidget(self.btn_revalidate)
        foot.addWidget(self.btn_cancel)
        foot.addWidget(self.btn_confirm)
        layout.addLayout(foot)

        self.table.itemSelectionChanged.connect(self._show_selected_evidence)

    def _apply_column_widths(self):
        w = max(self.table.viewport().width(), 600)
        for i, ratio in enumerate(_COL_RATIOS):
            self.table.setColumnWidth(i, max(64, int(w * ratio)))

    def _fit_row_heights(self):
        self.table.resizeRowsToContents()
        for r in range(self.table.rowCount()):
            self.table.setRowHeight(r, max(self.table.rowHeight(r), 64))

    def _iter_rows(self) -> List[Tuple[ValidatedChange, Optional[int]]]:
        rows: List[Tuple[ValidatedChange, Optional[int]]] = []
        for ch in self.state.changes or []:
            if ch.mapped and not ch.unmatched:
                for i, _ in enumerate(ch.mapped):
                    rows.append((ch, i))
            else:
                rows.append((ch, None))
        # 未抽取的放后面，有抽取的在前
        def _key(item):
            ch, _ = item
            st = _status_text(ch)
            order = {"将修改": 0, "不合法": 1, "歧义": 2, "未匹配": 3, "未抽取": 4}
            return (order.get(st, 9), (ch.mapped[0].element_name if ch.mapped else ""))

        rows.sort(key=_key)
        return rows

    def _fill_table(self):
        self._row_changes = self._iter_rows()
        self.table.setRowCount(len(self._row_changes))
        for r, (ch, mid) in enumerate(self._row_changes):
            if mid is not None and ch.mapped:
                m = ch.mapped[mid]
                name = m.element_name
                old_txt = _format_fields(m.old or {})
                nv = ch.new_values or (
                    ch.intent.as_selected() if ch.intent else {}
                )
                new_txt = _format_fields(nv) if any(nv.values()) else "—"
            else:
                name = (
                    ch.intent.selector_label() if ch.intent else "—"
                )
                if ch.mapped:
                    name = "、".join(x.element_name for x in ch.mapped)
                old_txt = "—"
                nv = ch.new_values or (
                    ch.intent.as_selected() if ch.intent else {}
                )
                new_txt = _format_fields(nv) if any((nv or {}).values()) else "—"

            status = _status_text(ch)
            brush = _status_brush(ch)
            reason = _reason_text(ch)
            basis = _evidence_text(ch)

            for c, text in (
                (0, name),
                (1, old_txt),
                (3, status),
                (4, reason),
                (5, basis),
            ):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setBackground(brush)
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignTop)
                if c == 3:
                    item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
                    colors = {
                        "将修改": QColor("#00a870"),
                        "不合法": _ERR_FG,
                        "歧义": QColor("#d97706"),
                        "未抽取": QColor("#86909c"),
                    }
                    item.setForeground(QBrush(colors.get(status, QColor("#86909c"))))
                if c == 4 and status == "不合法":
                    item.setForeground(QBrush(_ERR_FG))
                self.table.setItem(r, c, item)

            new_item = QTableWidgetItem(new_txt)
            if status != "未抽取":
                new_item.setFlags(new_item.flags() | Qt.ItemIsEditable)
            else:
                new_item.setFlags(new_item.flags() & ~Qt.ItemIsEditable)
            new_item.setBackground(brush)
            new_item.setTextAlignment(Qt.AlignLeft | Qt.AlignTop)
            if ch.field_errors or (
                status == "不合法"
            ):
                new_item.setBackground(QBrush(_ERR_CELL))
                new_item.setForeground(QBrush(_ERR_FG))
            self.table.setItem(r, 2, new_item)

    def _collect_edits_into_state(self):
        for r, (ch, _mid) in enumerate(self._row_changes):
            item = self.table.item(r, 2)
            if item is None:
                continue
            text = item.text().strip()
            if not text or text == "—":
                continue
            ch.new_values = _parse_new_values_text(text)

    def _on_revalidate(self):
        self._collect_edits_into_state()
        # 只重校验有新值的行
        self.state = revalidate_pipeline(self.state)
        self._fill_table()
        self._update_summary_and_buttons()
        self._fit_row_heights()

    def _on_confirm(self):
        self._collect_edits_into_state()
        self.state = revalidate_pipeline(self.state)
        self._fill_table()
        self._update_summary_and_buttons()
        if self._count_ok() <= 0:
            QMessageBox.warning(self, "无法确认", "没有可写入的合法项，请改后重校验。")
            return
        self.accept()

    def _show_selected_evidence(self):
        rows = (
            self.table.selectionModel().selectedRows()
            if self.table.selectionModel()
            else []
        )
        if not rows:
            self.evidence_view.setText("选中一行查看标注")
            self.evidence_view.setPixmap(QPixmap())
            self.lbl_ev_meta.setText("")
            return
        r = rows[0].row()
        if r < 0 or r >= len(self._row_changes):
            return
        ch, _mid = self._row_changes[r]
        ev = ch.intent.evidence if ch.intent else None
        if not ev or not ev.file_path:
            self.evidence_view.setText("本行无 PDF 依据")
            self.evidence_view.setPixmap(QPixmap())
            self.lbl_ev_meta.setText("")
            return
        page = int(ev.page or 1)
        pm = _render_pdf_page_with_bbox(
            ev.file_path,
            page,
            ev.bbox,
            max_w=max(340, self.evidence_view.width() - 16),
        )
        if pm.isNull():
            self.evidence_view.setText(
                f"无法渲染\n{os.path.basename(ev.file_path)} 页{page}"
            )
            self.evidence_view.setPixmap(QPixmap())
        else:
            self.evidence_view.setPixmap(pm)
            self.evidence_view.setText("")
        self.lbl_ev_meta.setText(ev.label() if ev else "")

    def _count_ok(self) -> int:
        n = 0
        for ch in self.state.changes or []:
            if ch.ok and ch.mapped and not ch.ambiguous and not ch.unmatched:
                if ch.new_values or (ch.intent and ch.intent.as_selected()):
                    n += len(ch.mapped)
        return n

    def _count_extracted(self) -> int:
        n = 0
        for ch in self.state.changes or []:
            if ch.new_values or (ch.intent and ch.intent.as_selected()):
                if ch.mapped and not ch.unmatched:
                    n += 1
        return n

    def _update_summary_and_buttons(self):
        ok_n = self._count_ok()
        ext_n = self._count_extracted()
        total = len(self._row_changes)
        self.lbl_summary.setText(
            f"元件 {total} · 已抽取 {ext_n} · 可写 {ok_n}"
        )
        self.btn_confirm.setEnabled(ok_n > 0)


def show_confirm_dialog(parent, state: AgentState) -> Tuple[bool, AgentState]:
    dlg = ConfirmMaterialDialog(state, parent=parent)
    ok = dlg.exec_() == QDialog.Accepted
    return ok, dlg.state
