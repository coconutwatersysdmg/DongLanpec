# -*- coding: utf-8 -*-
"""
待确认值弹窗

一张可编辑表格，四列：字段 / 值 / 状态与建议 / 解析依据

「解析依据」列按文件类型分流：
  PDF          → 「第 N 页（共 M 页）」+「点击查看」按钮
                 点开是整页截图，红框圈出该值的位置，可缩放
  Word/Excel   → 「第 N 段（共 M 段）」+ 原文片段
  对话输入     → 「— 对话输入，无文件依据」
  定位不到     → 「未在原文定位到」（标橙，提示重点核对）
  值被手工改过 → 位置前加 ✎，提醒依据已不对应新值

行为：
- 打开即校验，不合法的值标红并给出建议值，必填缺失的留空标黄
- 用户改完即时重新校验（350ms 防抖），「确认」只在无错误且无必填缺失时可用
- 「采用全部建议」把系统建议一次性填进去，用户仍可手工改
"""
import os
import sys

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QPixmap, QPainter, QPen
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QPushButton, QScrollArea, QWidget, QAbstractItemView,
    QCheckBox
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import evidence
import schema
import ui_msg

COLOR_OK = "#3B6D11"
COLOR_WARN = "#854F0B"
COLOR_ERR = "#A32D2D"
COLOR_MUTED = "#888888"

BG_ERR = "#FCEBEB"      # 不合法：标红
BG_MISSING = "#FAEEDA"  # 必填缺失：留空但标黄
BG_WHITE = "#FFFFFF"

COL_FIELD, COL_VALUE, COL_STATUS, COL_EVIDENCE = 0, 1, 2, 3


class EvidenceViewer(QDialog):
    """
    解析依据截图窗：整页渲染 + 红框标出值的位置，支持缩放。

    PDF 表格的字通常很小，缩到窗口宽度会看不清，
    所以给了「缩小 / 适应宽度 / 放大」，放大时按更高 DPI 重新渲染，
    不是把已有位图拉大（那样会糊）。
    """

    MIN_DPI, MAX_DPI = 60, 400

    def __init__(self, source_path, page_no, rect, field, value,
                 snippet="", parent=None, note=""):
        super().__init__(parent)
        self._path = source_path
        self._page = int(page_no)
        self._rect = rect
        self._dpi = 0
        self._fitted = False

        self.setWindowTitle("解析依据 — %s" % field)
        self.resize(900, 740)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        head = QLabel("字段「%s」　=　%s" % (field, value))
        head.setWordWrap(True)
        head.setStyleSheet("font-size:15px;font-weight:600;color:#222;")
        root.addWidget(head)

        if note:
            extra = QLabel(note)
            extra.setWordWrap(True)
            extra.setStyleSheet("font-size:13px;color:%s;background:#FBF1DE;"
                                "border-radius:5px;padding:5px 8px;" % COLOR_WARN)
            root.addWidget(extra)

        self.lbl_loc = QLabel("")
        self.lbl_loc.setStyleSheet("font-size:14px;color:#444;")
        root.addWidget(self.lbl_loc)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setStyleSheet(
            "QScrollArea{border:1px solid #e5e5e0;border-radius:6px;background:#f0f0ec;}")
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        self.scroll.setWidget(self.image)
        root.addWidget(self.scroll, 1)

        bar = QHBoxLayout()
        bar.setSpacing(8)

        self.lbl_snip = QLabel(("原文片段：%s" % snippet) if snippet else "")
        self.lbl_snip.setWordWrap(True)
        self.lbl_snip.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_snip.setStyleSheet("font-size:13px;color:#444;")
        bar.addWidget(self.lbl_snip, 1)

        for text, slot in (("缩小", lambda: self._zoom(1 / 1.25)),
                           ("适应宽度", self._fit),
                           ("放大", lambda: self._zoom(1.25))):
            b = QPushButton(text)
            b.setMinimumHeight(30)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                "QPushButton{background:#f0f0ec;color:#444;border:1px solid #d5d5d0;"
                "border-radius:6px;padding:0 14px;font-size:14px;}"
                "QPushButton:hover{background:#e5e5e0;}")
            b.clicked.connect(slot)
            bar.addWidget(b)

        close = QPushButton("关闭")
        close.setMinimumHeight(30)
        close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet(
            "QPushButton{background:#3B6D11;color:#fff;border:none;border-radius:6px;"
            "padding:0 20px;font-size:14px;font-weight:600;}"
            "QPushButton:hover{background:#27500A;}")
        close.clicked.connect(self.accept)
        bar.addWidget(close)

        root.addLayout(bar)

    def showEvent(self, event):
        super().showEvent(event)
        # 首次显示后才能拿到真实的 viewport 宽度
        if not self._fitted:
            self._fitted = True
            QTimer.singleShot(0, self._fit)

    def _zoom(self, factor):
        base = self._dpi or 120
        self._render(base * factor)

    def _fit(self):
        size = evidence.page_size(self._path, self._page)
        if not size:
            return self._render(130)
        avail = max(320, self.scroll.viewport().width() - 8)
        self._render(int(avail * 72.0 / max(1.0, size[0])))

    def _render(self, dpi):
        dpi = max(self.MIN_DPI, min(self.MAX_DPI, int(dpi)))
        data = evidence.render_pdf_page(self._path, self._page, dpi)
        if not data:
            self.image.setText("截图渲染失败")
            return
        pm = QPixmap()
        if not pm.loadFromData(data):
            self.image.setText("截图加载失败")
            return

        if self._rect:
            sr = evidence.scale_rect(self._rect, dpi)
            painter = QPainter(pm)
            pen = QPen(QColor("#E24B4A"))
            pen.setWidth(3)
            painter.setPen(pen)
            painter.drawRect(int(sr[0]) - 3, int(sr[1]) - 3,
                             int(sr[2] - sr[0]) + 6, int(sr[3] - sr[1]) + 6)
            painter.end()

        self._dpi = dpi
        self.image.setPixmap(pm)
        self.image.resize(pm.size())
        self.lbl_loc.setText(
            "第 %d 页 · %d DPI　%s"
            % (self._page, dpi,
               "红框标出的就是这个值" if self._rect else "这一页里有这个值，但未能精确定位位置"))


class ConfirmDialog(QDialog):
    """
    用法：
        dlg = ConfirmDialog(data, source_path=..., source_text=..., file_name=...)
        if dlg.exec_() == QDialog.Accepted:
            data = dlg.result_data
    """

    def __init__(self, data, source_path=None, source_text=None,
                 file_name=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("待确认值 — 请核对后确认")
        # QDialog 默认只有「?」和关闭按钮，没有最小化/最大化（Windows）。
        # 去掉上下文帮助「?」，加上最小化/最大化，方便拉大看长表格。
        self.setWindowFlags(
            (self.windowFlags() | Qt.WindowMinMaxButtonsHint)
            & ~Qt.WindowContextHelpButtonHint)
        self.resize(1080, 780)

        # 只保留已知字段，且值统一成字符串
        self.data = {}
        for spec in schema.ALL_FIELDS:
            k = spec["key"]
            v = data.get(k)
            self.data[k] = "" if v is None else str(v).strip()
        # 图号前缀默认 A01、设计版次默认 1（不从文件抽，但给个起点）
        schema.apply_defaults(self.data)

        # 记下抽取值，用来判断用户有没有手工改过（改了之后原文依据就不对应了）
        self._origin = dict(self.data)
        # 每个字段「原抽取值」的定位结果。值被改过、新值在原文里找不到时，
        # 还能把用户带回原值所在的那一页对照（比如「管壳式换热器」→建议值「管壳式热交换器」）
        self._origin_ev = {}
        # 依据列当前渲染的是哪个值，避免重复重建单元格控件
        self._ev_shown = {}

        self.result_data = None
        self._source_path = source_path
        self._source_text = source_text or ""
        self._file_name = file_name or ""

        self.errors = []
        self.warnings = []
        self.missing = []

        self._loading = True          # 建表期间屏蔽 itemChanged
        # 默认隐藏空着的可选字段（总包方/部门/编号），勾上就全部显示，方便补填
        self._show_empty = False
        self._validate_timer = QTimer(self)
        self._validate_timer.setSingleShot(True)
        self._validate_timer.timeout.connect(self._revalidate)

        self._build_ui()
        self._fill_rows()
        self._revalidate()
        self._loading = False

        # 默认选中第一个有问题的字段，用户一进来就看见该看的地方
        self._focus_first_problem()

    # ---------------- UI ----------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        head = QLabel(self._head_text())
        head.setWordWrap(True)
        head.setStyleSheet("font-size:14px;color:#444;background:#f5f5f2;"
                           "border-radius:6px;padding:6px 10px;")
        root.addWidget(head)

        tip_row = QHBoxLayout()
        tip_row.setContentsMargins(0, 0, 0, 0)
        tip_row.setSpacing(10)

        tip = QLabel("表头带 ★ 的是必填项　·　「值」列可直接双击修改，改完自动重新校验")
        tip.setStyleSheet("font-size:13px;color:%s;" % COLOR_MUTED)
        tip_row.addWidget(tip)
        tip_row.addStretch()

        # 总包方/所属部门/项目编号/产品编号 空着时默认不显示，
        # 勾上就能看到并手工补填
        self.chk_empty = QCheckBox("显示空字段")
        self.chk_empty.setCursor(Qt.PointingHandCursor)
        self.chk_empty.setStyleSheet("QCheckBox{font-size:13px;color:#555;}")
        self.chk_empty.setToolTip(
            "勾选后显示「工程总包方 / 所属部门 / 项目编号 / 产品编号」，\n"
            "这几个字段在文件里没有值时默认隐藏。")
        self.chk_empty.toggled.connect(self._toggle_show_empty)
        tip_row.addWidget(self.chk_empty)

        root.addLayout(tip_row)

        root.addWidget(self._build_table(), 1)

        # 底部：统计 + 操作
        bar = QHBoxLayout()
        self.summary = QLabel("")
        self.summary.setStyleSheet("font-size:14px;")
        bar.addWidget(self.summary)
        bar.addStretch()

        self.btn_suggest = QPushButton("采用全部建议")
        self.btn_suggest.setMinimumHeight(36)
        self.btn_suggest.setCursor(Qt.PointingHandCursor)
        self.btn_suggest.setStyleSheet(
            "QPushButton{background:#f0f0ec;color:#333;border:1px solid #d5d5d0;"
            "border-radius:8px;padding:0 16px;}"
            "QPushButton:hover{background:#e5e5e0;}"
            "QPushButton:disabled{color:#aaa;}")
        self.btn_suggest.clicked.connect(self._apply_suggestions)
        bar.addWidget(self.btn_suggest)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setMinimumHeight(36)
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setStyleSheet(
            "QPushButton{background:#f0f0ec;color:#444;border:1px solid #d5d5d0;"
            "border-radius:8px;padding:0 18px;}"
            "QPushButton:hover{background:#e5e5e0;}")
        self.btn_cancel.clicked.connect(self.reject)
        bar.addWidget(self.btn_cancel)

        self.btn_ok = QPushButton("确认")
        self.btn_ok.setMinimumHeight(36)
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        self.btn_ok.setStyleSheet(
            "QPushButton{background:#3B6D11;color:#fff;border:none;border-radius:8px;"
            "padding:0 24px;font-weight:600;}"
            "QPushButton:hover{background:#27500A;}"
            "QPushButton:disabled{background:#b0b0aa;}")
        self.btn_ok.clicked.connect(self._on_ok)
        bar.addWidget(self.btn_ok)

        root.addLayout(bar)

    def _head_text(self):
        if self._file_name:
            return ("来源文件：%s　　值可以直接改；「解析依据」列标明每个值的出处，"
                    "PDF 可点开看原文截图并核对位置。" % self._file_name)
        return "来源：对话输入（无文件依据）　　「值」列可以直接修改。"

    def _build_table(self):
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["字段", "值（可直接修改）", "状态 / 建议", "解析依据"])
        # 表格正文 11pt：默认继承系统 9pt，看久了很费眼
        self.table.setFont(QFont("Microsoft YaHei", 11))
        self.table.horizontalHeader().setFont(QFont("Microsoft YaHei", 11))
        hh = self.table.horizontalHeader()
        # 字段列固定宽度，别用 ResizeToContents——11pt 下自适应会撑到 260px，
        # 把「值」列挤得没法看
        hh.setSectionResizeMode(COL_FIELD, QHeaderView.Fixed)
        self.table.setColumnWidth(COL_FIELD, 132)
        hh.setSectionResizeMode(COL_VALUE, QHeaderView.Stretch)
        hh.setSectionResizeMode(COL_STATUS, QHeaderView.Fixed)
        self.table.setColumnWidth(COL_STATUS, 128)
        hh.setSectionResizeMode(COL_EVIDENCE, QHeaderView.Fixed)
        self.table.setColumnWidth(COL_EVIDENCE, 330)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        # 只选中单个格子：整行高亮会盖住「不合法标红 / 必填标黄」，
        # 而那两色正是用户最需要看到的信息。
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            "QTableWidget{border:1px solid #e5e5e0;border-radius:6px;"
            "alternate-background-color:#fafaf8;}"
            "QTableWidget::item{padding:2px 4px;}"
            # 半透明叠加，底下的红/黄底仍透得出来
            "QTableWidget::item:selected{background:rgba(43,108,200,45);color:#222;}")
        self.table.itemChanged.connect(self._on_item_changed)
        return self.table

    # ---------------- 表格填充与校验 ----------------

    def _fill_rows(self):
        self.table.setRowCount(0)
        self._ev_shown = {}          # 行都重建了，依据缓存必须一起清
        for spec in schema.ALL_FIELDS:
            k = spec["key"]
            # 总包方 / 所属部门 / 项目编号 / 产品编号：文件里没有就整行不显示
            # （勾了「显示空字段」则全部显示）
            if not self._show_empty and not schema.should_show(k, self.data.get(k)):
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)

            it0 = QTableWidgetItem(("★ " if spec["required"] else "") + k)
            it0.setFlags(it0.flags() & ~Qt.ItemIsEditable)
            it0.setData(Qt.UserRole, k)
            it0.setTextAlignment(Qt.AlignCenter)

            it1 = QTableWidgetItem(self.data.get(k, ""))
            it1.setForeground(QColor("#222"))

            it2 = QTableWidgetItem("")
            it2.setFlags(it2.flags() & ~Qt.ItemIsEditable)
            it2.setTextAlignment(Qt.AlignCenter)

            self.table.setItem(row, COL_FIELD, it0)
            self.table.setItem(row, COL_VALUE, it1)
            self.table.setItem(row, COL_STATUS, it2)

    def _toggle_show_empty(self, checked):
        """
        勾选/取消「显示空字段」：整表重建。

        _fill_rows 会清空表格和依据缓存，所以重建后必须 _revalidate 一次，
        否则状态列和依据列会是空的。
        """
        self._show_empty = bool(checked)
        if not hasattr(self, "table"):
            return
        self._loading = True
        self._fill_rows()
        self._loading = False
        self._revalidate()

    def _row_of(self, field):
        for r in range(self.table.rowCount()):
            it = self.table.item(r, COL_FIELD)
            if it and it.data(Qt.UserRole) == field:
                return r
        return -1

    def _on_item_changed(self, item):
        if self._loading or item.column() != COL_VALUE:
            return
        row = item.row()
        name_item = self.table.item(row, COL_FIELD)
        if not name_item:
            return
        field = name_item.data(Qt.UserRole)
        self.data[field] = (item.text() or "").strip()
        # 防抖：连续输入时不要每次按键都查库校验
        self._validate_timer.start(350)

    def _revalidate(self):
        self.errors, self.warnings = schema.validate(self.data)
        required_missing = [s["key"] for s in schema.ALL_FIELDS
                            if s["required"] and not (self.data.get(s["key"]) or "").strip()]
        self.missing = required_missing
        self._mark_rows()
        self._refresh_evidence()
        self._update_footer()

    def _mark_rows(self):
        err_map = {e["field"]: e for e in self.errors}
        warn_map = {w["field"]: w for w in self.warnings}
        missing_set = set(self.missing)

        self._loading = True
        for r in range(self.table.rowCount()):
            name_item = self.table.item(r, COL_FIELD)
            val_item = self.table.item(r, COL_VALUE)
            st_item = self.table.item(r, COL_STATUS)
            if not (name_item and val_item and st_item):
                continue
            field = name_item.data(Qt.UserRole)
            value = (self.data.get(field) or "").strip()

            bg = BG_WHITE
            fg = QColor("#222")
            st_fg = QColor(COLOR_MUTED)
            text = "—"

            if field in err_map:
                e = err_map[field]
                bg = BG_ERR
                fg = QColor(COLOR_ERR)
                st_fg = QColor(COLOR_ERR)
                sv = e.get("suggest_value")
                text = ("不合法 → %s" % sv) if sv else "不合法"
                st_item.setToolTip(e.get("reason") or "")
                val_item.setToolTip(e.get("reason") or "")
            elif field in missing_set:
                bg = BG_MISSING
                fg = QColor("#222")
                st_fg = QColor(COLOR_WARN)
                text = "必填未填"
                st_item.setToolTip("必填项，请填写")
                val_item.setToolTip("必填项，请填写")
            elif field in warn_map:
                st_fg = QColor(COLOR_WARN)
                text = "提醒"
                st_item.setToolTip(warn_map[field].get("reason") or "")
                val_item.setToolTip(warn_map[field].get("reason") or "")
            elif value:
                st_fg = QColor(COLOR_OK)
                text = "✓"
                st_item.setToolTip("")
                val_item.setToolTip("")
            else:
                text = "未填"
                st_item.setToolTip("")
                val_item.setToolTip("")

            val_item.setBackground(QColor(bg))
            val_item.setForeground(fg)
            st_item.setText(text)
            st_item.setForeground(st_fg)
        self._loading = False

    def _update_footer(self):
        n_err = len(self.errors)
        n_miss = len(self.missing)
        n_warn = len(self.warnings)
        n_filled = len([1 for v in self.data.values() if v])

        parts = ["已填 %d 项" % n_filled]
        if n_err:
            parts.append("%d 处不合法" % n_err)
        if n_miss:
            parts.append("%d 项必填未填" % n_miss)
        if n_warn:
            parts.append("%d 条提醒" % n_warn)
        if not n_err and not n_miss:
            parts.append("可以确认")

        self.summary.setText("　·　".join(parts))
        self.summary.setStyleSheet(
            "font-size:14px;font-weight:600;color:%s;"
            % (COLOR_OK if (not n_err and not n_miss) else COLOR_ERR if n_err else COLOR_WARN))

        n_suggest = len([e for e in self.errors if e.get("suggest_value")])
        self.btn_suggest.setEnabled(n_suggest > 0)
        self.btn_suggest.setText(
            "采用全部建议（%d）" % n_suggest if n_suggest else "采用全部建议")

        self.btn_ok.setEnabled(not n_err and not n_miss)

    def _apply_suggestions(self):
        applied = 0
        self._loading = True
        for e in self.errors:
            sv = e.get("suggest_value")
            if not sv:
                continue
            field = e["field"]
            self.data[field] = sv
            r = self._row_of(field)
            if r >= 0:
                it = self.table.item(r, COL_VALUE)
                if it:
                    it.setText(sv)
            applied += 1
        self._loading = False
        if applied:
            self._revalidate()

    def _focus_first_problem(self):
        targets = [e["field"] for e in self.errors] + list(self.missing)
        if not targets:
            if self.table.rowCount():
                self.table.setCurrentCell(0, COL_VALUE)
            return
        r = self._row_of(targets[0])
        if r >= 0:
            self.table.setCurrentCell(r, COL_VALUE)

    # ---------------- 解析依据（表格内一列） ----------------

    def _refresh_evidence(self):
        """值变了才重建依据单元格，避免每次校验都重扫一遍原文。"""
        for spec in schema.ALL_FIELDS:
            k = spec["key"]
            v = (self.data.get(k) or "").strip()
            if self._ev_shown.get(k) == v:
                continue
            self._ev_shown[k] = v

            info = self._locate(k, v)
            # 第一次生成的就是「原抽取值」的依据，留一份给后面改值时对照
            if k not in self._origin_ev:
                self._origin_ev[k] = info

            row = self._row_of(k)
            if row < 0:
                continue
            widget, height = self._make_evidence_widget(k, info)
            self.table.setCellWidget(row, COL_EVIDENCE, widget)
            self.table.setRowHeight(row, height)

    def _locate(self, field, value):
        if not value or (not self._source_path and not self._source_text):
            return {"kind": "none", "page": None, "rect": None,
                    "location": "", "snippet": ""}
        # 人工填写字段（图号前缀 / 设计版次）是默认值或手填的，原文没有出处；
        # 去搜「A01」「1」这种短值只会框错位置，直接不给依据
        if field in schema.MANUAL_FIELDS:
            return {"kind": "none", "page": None, "rect": None,
                    "location": "", "snippet": ""}
        return evidence.locate(self._source_path, self._source_text, value)

    def _make_evidence_widget(self, field, info):
        val = (self.data.get(field) or "").strip()
        origin = (self._origin.get(field) or "").strip()
        changed = bool(origin) and val != origin

        box = QWidget()
        outer = QVBoxLayout(box)
        outer.setContentsMargins(6, 2, 4, 2)
        outer.setSpacing(0)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)

        loc = QLabel()
        loc.setTextInteractionFlags(Qt.TextSelectableByMouse)
        top.addWidget(loc, 1)

        def add_snippet(text, tip=None):
            lab = QLabel(text)
            lab.setStyleSheet("font-size:12px;color:#767676;")
            lab.setToolTip(tip or text)
            outer.addWidget(lab)

        def add_button(rect_page, qrect, snippet, note=""):
            """PDF 才给按钮：点开是那一页的截图 + 红框。"""
            btn = QPushButton("点击查看")
            btn.setFixedHeight(22)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton{background:#eef2ea;color:%s;border:1px solid #c9d6bd;"
                "border-radius:5px;padding:0 8px;font-size:13px;}"
                "QPushButton:hover{background:#e0e8d8;}" % COLOR_OK)
            btn.clicked.connect(
                lambda _, p=rect_page, r=qrect, s=snippet, n=note:
                self._open_viewer(field, p, r, s, n))
            top.addWidget(btn, 0)

        # 1) 字段本身空着，没有可对照的原文
        if not val:
            loc.setText("—")
            loc.setStyleSheet("font-size:13px;color:%s;" % COLOR_MUTED)
            outer.addLayout(top)
            return box, 40

        # 1.5) 人工填写字段（图号前缀 / 设计版次）有默认值，但原文里没有出处，
        #      依据列留空即可，别显示成"系统整理后的写法"
        if field in schema.MANUAL_FIELDS:
            loc.setText("—")
            loc.setStyleSheet("font-size:13px;color:%s;" % COLOR_MUTED)
            outer.addLayout(top)
            return box, 40

        # 2) 对话输入，本来就没有文件依据
        if not self._source_path and not self._source_text:
            loc.setText("—　对话输入，无文件依据")
            loc.setStyleSheet("font-size:13px;color:%s;" % COLOR_MUTED)
            outer.addLayout(top)
            return box, 40

        kind = info.get("kind")
        snippet = info.get("snippet") or ""

        # 3) 原文里定位不到
        if kind == "none":
            if changed:
                # 值被改过、新值原文没有：把用户带回原值那一页，仍可对照
                old = self._origin_ev.get(field) or {}
                loc.setText("✎ 已修改 · 原文无此写法")
                loc.setStyleSheet("font-size:13px;color:%s;" % COLOR_WARN)
                loc.setToolTip("当前值在原文里找不到。点「点击查看」可看原值「%s」所在的位置。" % origin)
                if old.get("kind") == "pdf" and old.get("page"):
                    add_button(old.get("page"), old.get("rect"), old.get("snippet") or "",
                               note="红框处是原文的写法「%s」。当前值已被改成「%s」，"
                                    "所以按当前值在原文里查不到——截图给的是原值的位置。"
                                    % (origin, val))
                    outer.addLayout(top)
                    return box, 44
                outer.addLayout(top)
                if old.get("location"):
                    add_snippet("原值依据：" + old["location"])
                    return box, 58
                return box, 40
            loc.setText("未在原文定位到")
            loc.setStyleSheet("font-size:13px;color:%s;" % COLOR_WARN)
            loc.setToolTip("这个值在送模型的原文里搜不到，可能是模型改写或推断出来的，请重点核对。")
            outer.addLayout(top)
            return box, 40

        prefix = "✎ " if changed else ""
        loc.setText(prefix + (info.get("location") or ""))
        loc.setStyleSheet("font-size:13px;color:#444;")
        if changed:
            loc.setToolTip("该值已被修改，这里显示的是新值在原文中的位置。")

        # 4) PDF：位置 + 「点击查看」按钮
        if kind == "pdf":
            add_button(info.get("page"), info.get("rect"), snippet)
            outer.addLayout(top)
            if snippet:
                add_snippet(snippet)
                return box, 58
            return box, 44

        # 5) Word / Excel / 文本：位置 + 原文片段
        outer.addLayout(top)
        if snippet:
            short = snippet if len(snippet) <= 30 else snippet[:30] + "…"
            add_snippet(short, snippet)
            return box, 58
        return box, 44

    def _open_viewer(self, field, page, rect, snippet, note=""):
        if not page:
            ui_msg.info(
                self, "没有截图",
                "这个值没能定位到具体的 PDF 页，无法截图。\n"
                "可能该文件不是 PDF，或值被模型改写过了。")
            return
        val = (self.data.get(field) or "").strip()
        dlg = EvidenceViewer(self._source_path, page, rect, field, val, snippet, self, note)
        dlg.exec_()

    # ---------------- 确认 ----------------

    def _on_ok(self):
        if self.errors or self.missing:
            ui_msg.warn(
                self, "还不能确认",
                "还有 %d 处不合法、%d 项必填未填，请先处理完。"
                % (len(self.errors), len(self.missing)))
            return
        self.result_data = dict(self.data)
        self.accept()
