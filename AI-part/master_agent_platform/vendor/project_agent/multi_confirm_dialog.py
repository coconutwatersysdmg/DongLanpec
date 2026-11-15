# -*- coding: utf-8 -*-
"""
多产品待确认弹窗

【和 confirm_dialog 的分工】
confirm_dialog  处理「一个产品」：对话输入、或只识别出一台设备
本模块           处理「一份项目文件里有多台设备」：纵向罗列，每组一台

【界面结构（用户选定的"纵向罗列 + 分组标题"）】
  ┌ 项目信息 ──────────────────────────────┐   ← 分组标题（跨 4 列）
  │ ★项目名称 │ … │ 状态 │ 依据            │
  │  项目编号 │ … │      │                 │
  │  …                                     │
  ├ 产品 1 / 共 11　OST-E-1901　常温脱硫塔入口丙烷冷却器 ─┤
  │ ★产品名称 │ … │      │ 第 3 页 [点击查看] │
  │  …（8 行）                              │
  ├ 产品 2 / 共 11　OST-E-1903A/B　脱烃塔入口换热器（2 台）┤
  │  …                                     │
  └────────────────────────────────────────┘

【依据为什么要按页定位】
同一台设备的位号在 PDF 目录页也出现，若全文搜索会定位到目录页。
本模块统一用 evidence.locate_on_page()，只看这台设备自己的数据表页。

【增删】
底部「删除当前产品」「新增产品」。删除以 cursor 所在行判断属于哪个产品组，
至少保留一个产品；新增时把类型/阶段/版次继承自第一台，省得重复填。
"""
import os
import sys

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QPushButton, QWidget, QAbstractItemView, QCheckBox
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import evidence
import schema
import ui_msg
from confirm_dialog import (
    EvidenceViewer,
    COLOR_OK, COLOR_WARN, COLOR_ERR, COLOR_MUTED,
    BG_ERR, BG_MISSING, BG_WHITE,
    COL_FIELD, COL_VALUE, COL_STATUS, COL_EVIDENCE,
)

BG_GROUP_PROJECT = "#E8EEF4"   # 项目组标题：浅蓝灰
BG_GROUP_PRODUCT = "#FAF3E4"   # 产品组标题：浅米黄
FG_GROUP = "#2C3E50"

# 新建产品时，这些字段从第一台继承，避免用户重复填同样的值
INHERIT_FIELDS = ("产品类型", "设计阶段", "设计版次")


class MultiProductDialog(QDialog):
    """
    用法：
        dlg = MultiProductDialog(project, products, evidence_map, source_path=..., file_name=...)
        if dlg.exec_() == QDialog.Accepted:
            project, products = dlg.result_project, dlg.result_products
    """

    def __init__(self, project, products, evidence_map=None,
                 source_path=None, file_name=None, notes=None,
                 source_files=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("待确认值 — 多产品核对")
        # QDialog 在 Windows 上默认只给「?」和关闭按钮，没有最小化/最大化。
        # 这个表有十几台设备、很长，用户经常要拉大看，所以：
        # 去掉上下文帮助按钮「?」，加上最小化/最大化。
        self.setWindowFlags(
            (self.windowFlags() | Qt.WindowMinMaxButtonsHint)
            & ~Qt.WindowContextHelpButtonHint)
        self.resize(1180, 820)

        # 只保留已知字段，值统一成字符串
        self.project = self._norm(project, schema.PROJECT_FIELDS)
        self.products = [self._norm(p, schema.PRODUCT_FIELDS) for p in (products or [])]
        if not self.products:
            self.products = [self._norm({}, schema.PRODUCT_FIELDS)]

        # 抽取值快照：判断用户是否改过，改过后依据要提示"已修改"
        self._origin = [dict(p) for p in self.products]
        self._origin_project = dict(self.project)

        ev = evidence_map or {}
        self._ev_project = ev.get("project") or {}
        self._ev_products = list(ev.get("products") or [])
        while len(self._ev_products) < len(self.products):
            self._ev_products.append({})
        self._ev_shown = {}          # (gidx, field) -> 上次渲染的值

        self._source_path = source_path
        self._file_name = file_name or ""
        # 文件名 → 真实路径。一个项目往往要好几个文件才凑齐字段：
        # 数据表 PDF 给设备，任务书给业主/部门，项目记录表给总包方。
        # 依据列要能指回"这个值来自哪个文件"。
        self._source_files = dict(source_files or {})
        if source_path:
            self._source_files.setdefault(os.path.basename(source_path), source_path)
        self._notes = notes or []

        self.result_project = None
        self.result_products = None

        self._row_map = {}           # 行号 -> ("group", gidx) 或 ("field", gidx, 字段)
        self._loading = True
        # 默认隐藏空着的可选字段（总包方/部门/编号），勾上就全部显示出来，
        # 方便用户在这些字段上手工补填
        self._show_empty = False
        self._validate_timer = QTimer(self)
        self._validate_timer.setSingleShot(True)
        self._validate_timer.timeout.connect(self._revalidate)

        self._build_ui()
        self._rebuild()
        self._loading = False
        self._revalidate()
        self._focus_first_problem()

    # ---------------- 数据 ----------------

    @staticmethod
    def _norm(data, specs):
        out = {}
        for spec in specs:
            k = spec["key"]
            v = (data or {}).get(k)
            out[k] = "" if v is None else str(v).strip()
        # 下划线开头的是内部字段（_qty 台数、_page 来源页），
        # 不在 schema 里，但标题行和合计要用，不能被过滤掉
        for k, v in (data or {}).items():
            if k.startswith("_"):
                out[k] = v
        # 默认值（图号前缀 A01、设计版次 1）只给本组字段，
        # 传 specs 就是为了别把产品字段塞进项目字典里
        schema.apply_defaults(out, specs)
        return out

    def _sync_from_table(self):
        """把表格里的编辑同步回 self.project / self.products。"""
        for row, ref in self._row_map.items():
            if ref[0] != "field":
                continue
            _, gidx, field = ref
            # 增删产品后 _row_map 里可能还留着已删产品的旧索引，越界就跳过
            if gidx >= len(self.products):
                continue
            item = self.table.item(row, COL_VALUE)
            if item is None:
                continue
            val = (item.text() or "").strip()
            if gidx < 0:
                self.project[field] = val
            else:
                self.products[gidx][field] = val

    # ---------------- UI ----------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(9)

        head = QLabel(self._head_text())
        head.setWordWrap(True)
        head.setStyleSheet("font-size:14px;color:#444;background:#f5f5f2;"
                           "border-radius:6px;padding:6px 10px;")
        root.addWidget(head)

        tip_row = QHBoxLayout()
        tip_row.setContentsMargins(0, 0, 0, 0)
        tip_row.setSpacing(10)

        tip = QLabel("带 ★ 的是必填项　·　「值」列可双击修改，改完自动重新校验　·　"
                     "红底＝不合法，黄底＝必填未填")
        tip.setStyleSheet("font-size:13px;color:%s;" % COLOR_MUTED)
        tip_row.addWidget(tip)
        tip_row.addStretch()

        # 总包方/所属部门/项目编号/产品编号 空着时默认不显示，
        # 勾上这个就能看到并手工填
        self.chk_empty = QCheckBox("显示空字段")
        self.chk_empty.setCursor(Qt.PointingHandCursor)
        self.chk_empty.setStyleSheet("QCheckBox{font-size:13px;color:#555;}")
        self.chk_empty.setToolTip(
            "勾选后显示「工程总包方 / 所属部门 / 项目编号 / 产品编号」，\n"
            "这几个字段在文件里没有值时默认隐藏，勾上就能在这里手工补填。")
        self.chk_empty.toggled.connect(self._toggle_show_empty)
        tip_row.addWidget(self.chk_empty)

        root.addLayout(tip_row)

        root.addWidget(self._build_table(), 1)

        bar = QHBoxLayout()
        self.summary = QLabel("")
        self.summary.setStyleSheet("font-size:14px;")
        bar.addWidget(self.summary)
        bar.addStretch()

        self.btn_add = self._mk_btn("新增产品", "#f0f0ec", "#333")
        self.btn_add.clicked.connect(self._add_product)
        bar.addWidget(self.btn_add)

        self.btn_del = self._mk_btn("删除当前产品", "#f0f0ec", "#333")
        self.btn_del.clicked.connect(self._del_product)
        bar.addWidget(self.btn_del)

        self.btn_suggest = self._mk_btn("采用全部建议", "#f0f0ec", "#333")
        self.btn_suggest.clicked.connect(self._apply_suggestions)
        bar.addWidget(self.btn_suggest)

        self.btn_cancel = self._mk_btn("取消", "#f0f0ec", "#444", pad=18)
        self.btn_cancel.clicked.connect(self.reject)
        bar.addWidget(self.btn_cancel)

        self.btn_ok = self._mk_btn("确认全部", "#3B6D11", "#fff", pad=24, bold=True)
        self.btn_ok.clicked.connect(self._on_ok)
        bar.addWidget(self.btn_ok)

        root.addLayout(bar)

    @staticmethod
    def _mk_btn(text, bg, fg, pad=16, bold=False):
        b = QPushButton(text)
        b.setMinimumHeight(36)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(
            "QPushButton{background:%s;color:%s;border:1px solid #d5d5d0;"
            "border-radius:8px;padding:0 %dpx;%s}"
            "QPushButton:hover{background:#e5e5e0;}"
            "QPushButton:disabled{color:#aaa;}"
            % (bg, fg, pad, "font-weight:600;" if bold else ""))
        return b

    def _head_text(self):
        n = len(self.products)
        total = sum(int(p.get("_qty") or 1) for p in self.products)
        base = "来源文件：%s　　" % self._file_name if self._file_name else ""
        s = "%s识别到 %d 个产品（合计 %d 台设备）" % (base, n, total)
        if self._notes:
            s += "\n提醒：" + "；".join(self._notes[:2])
        return s

    def _build_table(self):
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["字段", "值（可直接修改）", "状态 / 建议", "解析依据"])
        # 表格正文用 11pt：默认继承系统 9pt，一屏 11 台设备的字段看着很吃力
        self.table.setFont(QFont("Microsoft YaHei", 11))
        self.table.horizontalHeader().setFont(QFont("Microsoft YaHei", 11))
        hh = self.table.horizontalHeader()
        # 字段列固定宽度：字号 11pt 时「★ 产品名称」约 105px，
        # 用 ResizeToContents 会撑到 260px 把「值」列挤窄，固定 132px 够用
        hh.setSectionResizeMode(COL_FIELD, QHeaderView.Fixed)
        self.table.setColumnWidth(COL_FIELD, 132)
        hh.setSectionResizeMode(COL_VALUE, QHeaderView.Stretch)
        hh.setSectionResizeMode(COL_STATUS, QHeaderView.Fixed)
        self.table.setColumnWidth(COL_STATUS, 128)
        hh.setSectionResizeMode(COL_EVIDENCE, QHeaderView.Fixed)
        self.table.setColumnWidth(COL_EVIDENCE, 330)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(False)
        self.table.setStyleSheet(
            "QTableWidget{border:1px solid #e5e5e0;border-radius:6px;}"
            "QTableWidget::item{padding:2px 4px;}"
            # 半透明叠加，底下的红/黄底仍透得出来
            "QTableWidget::item:selected{background:rgba(43,108,200,45);color:#222;}")
        self.table.itemChanged.connect(self._on_item_changed)
        # 切换当前行时更新底部「删除当前产品」的可用状态
        self.table.currentCellChanged.connect(lambda *_: self._update_footer())
        return self.table

    # ---------------- 重建表格 ----------------

    def _rebuild(self, resync=True):
        """
        整表重建。增删产品、或初始化时调用。

        resync=True  先从表格回收用户已改的值（初始化后可忽略，增删前自己调过）
        resync=False 数据刚被程序改过（删产品、采用建议），不能再用旧表格覆盖回来
        """
        if resync:
            self._sync_from_table()
        self._loading = True

        self.table.setRowCount(0)
        self._row_map = {}
        self._ev_shown = {}
        self.table.clearSpans()

        # 1) 项目信息组
        self._add_group_row("项目信息（整个项目共用一份，不随产品重复）",
                            BG_GROUP_PROJECT, -1)
        for spec in schema.PROJECT_FIELDS:
            # 总包方 / 所属部门 / 项目编号 初次设计常常还没有，
            # 空着就不占一行（勾了「显示空字段」则照常显示）
            if not self._show_empty and not schema.should_show(
                    spec["key"], self.project.get(spec["key"])):
                continue
            self._add_field_row(-1, spec)

        # 2) 每个产品一组
        n = len(self.products)
        for i, prod in enumerate(self.products):
            self._add_group_row(self._product_title(i, prod, n), BG_GROUP_PRODUCT, i)
            for spec in schema.PRODUCT_FIELDS:
                if not self._show_empty and not schema.should_show(
                        spec["key"], prod.get(spec["key"])):
                    continue
                self._add_field_row(i, spec)

        self._loading = False

    def _toggle_show_empty(self, checked):
        """
        勾选/取消「显示空字段」：整表重建。

        _rebuild() 默认 resync=True 会先把表格里已改的值收回数据里，
        所以切换显示不会丢用户刚敲的内容。
        """
        self._show_empty = bool(checked)
        if not hasattr(self, "table"):
            return
        self._rebuild()
        self._revalidate()

    def _product_title(self, i, prod, n):
        tag = prod.get("设备位号") or "未识别位号"
        name = prod.get("产品名称") or "未识别名称"
        qty = int(prod.get("_qty") or 1)
        qty_s = "　共 %d 台" % qty if qty > 1 else ""
        # 这台设备在原 PDF 里占哪几页。后续模块（条件输入等）就靠这个范围只读自己那段，
        # 所以必须让用户在核对时能看见，切错了整条链都会错。
        ps, pe = prod.get("_page_start"), prod.get("_page_end")
        if ps and pe:
            page_s = "　原文 P%s" % (ps if ps == pe else "%s-%s" % (ps, pe))
        else:
            page_s = ""
        return "产品 %d / 共 %d　　%s　　%s%s%s" % (i + 1, n, tag, name, qty_s, page_s)

    def _add_group_row(self, text, bg, gidx):
        row = self.table.rowCount()
        self.table.insertRow(row)
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsEnabled)          # 不可编辑、不可选中
        f = QFont()
        f.setBold(True)
        item.setFont(f)
        item.setBackground(QColor(bg))
        item.setForeground(QColor(FG_GROUP))
        self.table.setItem(row, 0, item)
        self.table.setSpan(row, 0, 1, 4)
        self.table.setRowHeight(row, 38)
        self._row_map[row] = ("group", gidx)

    def _add_field_row(self, gidx, spec):
        k = spec["key"]
        row = self.table.rowCount()
        self.table.insertRow(row)

        src = self.project if gidx < 0 else self.products[gidx]

        it0 = QTableWidgetItem(("★ " if spec["required"] else "") + k)
        it0.setFlags(it0.flags() & ~Qt.ItemIsEditable)
        it0.setTextAlignment(Qt.AlignCenter)
        it0.setData(Qt.UserRole, k)

        it1 = QTableWidgetItem(src.get(k, ""))
        it1.setForeground(QColor("#222"))

        it2 = QTableWidgetItem("")
        it2.setFlags(it2.flags() & ~Qt.ItemIsEditable)
        it2.setTextAlignment(Qt.AlignCenter)

        self.table.setItem(row, COL_FIELD, it0)
        self.table.setItem(row, COL_VALUE, it1)
        self.table.setItem(row, COL_STATUS, it2)
        self.table.setRowHeight(row, 44)
        self._row_map[row] = ("field", gidx, k)

    # ---------------- 编辑与校验 ----------------

    def _on_item_changed(self, item):
        if self._loading or item.column() != COL_VALUE:
            return
        row = item.row()
        ref = self._row_map.get(row)
        if not ref or ref[0] != "field":
            return
        _, gidx, field = ref
        val = (item.text() or "").strip()
        if gidx < 0:
            self.project[field] = val
        else:
            self.products[gidx][field] = val
        self._validate_timer.start(350)

    def _revalidate(self):
        self._err_map = {}      # (gidx, field) -> error dict
        self._warn_map = {}     # (gidx, field) -> warning dict
        self._miss_set = set()  # (gidx, field)

        # 项目级：只跑长度校验（产品字段全空，schema 不会误报）
        self._collect(0, -1, self.project)

        for i, prod in enumerate(self.products):
            self._collect(i + 1, i, prod)

        self._mark_rows()
        self._refresh_evidence()
        self._update_footer()

    def _collect(self, _seq, gidx, data):
        # skip_duplicate=True：十几台设备逐个查同名校验会卡顿，留到落库前统一查
        errs, warns = schema.validate(data, skip_duplicate=True)
        for e in errs:
            self._err_map[(gidx, e["field"])] = e
        for w in warns:
            self._warn_map[(gidx, w["field"])] = w
        for spec in (schema.PROJECT_FIELDS if gidx < 0 else schema.PRODUCT_FIELDS):
            if spec["required"] and not (data.get(spec["key"]) or "").strip():
                self._miss_set.add((gidx, spec["key"]))

    def _mark_rows(self):
        self._loading = True
        for row, ref in self._row_map.items():
            if ref[0] != "field":
                continue
            _, gidx, field = ref
            name_item = self.table.item(row, COL_FIELD)
            val_item = self.table.item(row, COL_VALUE)
            st_item = self.table.item(row, COL_STATUS)
            if not (name_item and val_item and st_item):
                continue

            key = (gidx, field)
            bg, fg, st_fg, text = BG_WHITE, QColor("#222"), QColor(COLOR_MUTED), "—"

            if key in self._err_map:
                e = self._err_map[key]
                bg, fg, st_fg = BG_ERR, QColor(COLOR_ERR), QColor(COLOR_ERR)
                sv = e.get("suggest_value")
                text = ("不合法 → %s" % sv) if sv else "不合法"
                st_item.setToolTip(e.get("reason") or "")
                val_item.setToolTip(e.get("reason") or "")
            elif key in self._miss_set:
                bg, fg, st_fg = BG_MISSING, QColor(COLOR_WARN), QColor(COLOR_WARN)
                text = "必填未填"
                st_item.setToolTip("该项必填，请填写后再确认")
                val_item.setToolTip("该项必填，请填写后再确认")
            elif key in self._warn_map:
                w = self._warn_map[key]
                fg, st_fg = QColor(COLOR_WARN), QColor(COLOR_WARN)
                text = "注意"
                st_item.setToolTip(w.get("reason") or "")
                val_item.setToolTip(w.get("reason") or "")
            else:
                st_item.setToolTip("")

            val_item.setBackground(QColor(bg))
            val_item.setForeground(fg)
            st_item.setText(text)
            st_item.setForeground(st_fg)
        self._loading = False

    def _update_footer(self):
        n_err = len(self._err_map)
        n_miss = len(self._miss_set)
        n_warn = len(self._warn_map)

        parts = ["%d 个产品 · 合计 %d 台" % (len(self.products),
                                          sum(int(p.get("_qty") or 1) for p in self.products))]
        if n_err:
            parts.append("%d 处不合法" % n_err)
        if n_miss:
            parts.append("%d 项必填未填" % n_miss)
        if n_warn:
            parts.append("%d 处需注意" % n_warn)
        if not (n_err or n_miss):
            parts.append("可以确认")

        self.summary.setText("　·　".join(parts))
        color = COLOR_ERR if n_err else (COLOR_WARN if n_miss else COLOR_OK)
        self.summary.setStyleSheet("font-size:14px;color:%s;" % color)

        self.btn_ok.setEnabled(not n_err and not n_miss)
        self.btn_suggest.setEnabled(bool(n_err))
        # 至少留一个产品，只剩一个时不允许删
        self.btn_del.setEnabled(len(self.products) > 1)

    # ---------------- 依据列 ----------------

    def _refresh_evidence(self):
        for row, ref in self._row_map.items():
            if ref[0] != "field":
                continue
            _, gidx, field = ref
            val = (self.project if gidx < 0 else self.products[gidx]).get(field, "")
            if self._ev_shown.get((gidx, field)) == val:
                continue
            self._ev_shown[(gidx, field)] = val

            info = self._locate(gidx, field, val)
            widget, height = self._make_evidence_widget(gidx, field, info)
            self.table.setCellWidget(row, COL_EVIDENCE, widget)
            if height > self.table.rowHeight(row):
                self.table.setRowHeight(row, height)

    def _locate(self, gidx, field, value):
        empty = {"kind": "none", "page": None, "rect": None,
                 "location": "", "snippet": ""}
        if not value:
            return empty

        # 优先用抽取时记下的「来源文件 + 页码」，这是最准的定位
        ev = self._ev_project if gidx < 0 else (
            self._ev_products[gidx] if gidx < len(self._ev_products) else {})
        recorded = ev.get(field) or {}

        # 人工填写字段（图号前缀 / 设计版次）的值是默认值或用户手填，
        # 原文里没有它的出处。硬去搜「A01」「1」这种短值只会框到别的地方，
        # 所以没有记录来源时直接留空。
        if field in schema.MANUAL_FIELDS and not recorded:
            return empty

        src_name = recorded.get("file") or ""
        page = recorded.get("page")

        # 按字段自己的来源文件找路径，而不是一律用主文件：
        # 业主名称来自 xlsx，却拿 PDF 去搜，就会误报"原文无此写法"
        path = self._source_files.get(src_name) if src_name else None
        if not path:
            path = self._source_path

        # 值可能是程序归一后的写法（如「详细设计」对应原文「详细工程设计」），
        # 用原文写法去定位，红框才能落在真正的位置上
        target = recorded.get("original") or value

        # 表格里的短值（如版次「0」）：按「行锚点 + 列表头」交叉定位到那一格。
        # 这类值全文搜索会命中最前面那个，框错地方。
        anchor = recorded.get("anchor")
        column = recorded.get("column")
        if anchor and column and page and path:
            got = evidence.locate_table_cell(path, page, anchor, column, target)
            if got:
                if recorded.get("snippet"):
                    got["snippet"] = recorded["snippet"]
                return got

        if page and path:
            got = evidence.locate_on_page(path, page, target)
            if got.get("kind") == "pdf":
                if recorded.get("original") and recorded["original"] != value:
                    got["snippet"] = "原文写法：%s" % recorded["original"]
                elif recorded.get("snippet"):
                    # 抽取时记下的片段比"页面上第一个命中值附近"更准，
                    # 比如版次「0」满页都是，靠它才能看出是目录表格里的那一列
                    got["snippet"] = recorded["snippet"]
                return got

        if src_name and path and src_name != os.path.basename(self._source_path or ""):
            # 来自另一个文件（表格类），没有页码可给，直接标明出处
            return {"kind": "text", "page": None, "rect": None,
                    "location": "来自 %s" % src_name,
                    "snippet": recorded.get("snippet") or ""}

        if path:
            return evidence.locate(path, "", value)
        if recorded.get("snippet"):
            return {"kind": "text", "page": None, "rect": None,
                    "location": "来自 %s" % (src_name or "原文"),
                    "snippet": recorded["snippet"]}
        return empty

    def _make_evidence_widget(self, gidx, field, info):
        val = (self.project if gidx < 0 else self.products[gidx]).get(field, "").strip()
        origin = (self._origin_project if gidx < 0 else
                  (self._origin[gidx] if gidx < len(self._origin) else {})).get(field, "").strip()
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

        def add_snippet(text):
            lab = QLabel(text)
            lab.setStyleSheet("font-size:12px;color:#767676;")
            lab.setToolTip(text)
            outer.addWidget(lab)

        if not val:
            loc.setText("—")
            loc.setStyleSheet("font-size:13px;color:%s;" % COLOR_MUTED)
            outer.addLayout(top)
            return box, 38

        # 人工填写字段（图号前缀 / 设计版次）有默认值，但原文里没有出处，
        # 依据列留空即可，别显示成"系统整理后的写法"
        if field in schema.MANUAL_FIELDS:
            loc.setText("—")
            loc.setStyleSheet("font-size:13px;color:%s;" % COLOR_MUTED)
            outer.addLayout(top)
            return box, 38

        kind = info.get("kind")
        snippet = info.get("snippet") or ""

        if kind == "none":
            # 抽到了值，但原文里搜不到这个字符串。
            # 常见两种：①代码把「详细工程设计」归一成库里的「详细设计」
            #          ②代码按数据表标题判定产品类型，原文并没有这四个字
            # 都不是模型编造，所以文案要说清楚是"系统整理"，不能让用户以为出错
            if changed:
                loc.setText("✎ 已修改 · 原文无此写法")
                loc.setToolTip("当前值是你改的，在原文里找不到对应字符串。")
            else:
                loc.setText("系统整理后的写法，原文无此字符串")
                loc.setToolTip("这个值是程序按原文内容归一到系统标准写法得到的，"
                               "不是模型编造；原文的实际写法见左侧或对应页码。")
            loc.setStyleSheet("font-size:13px;color:%s;" % COLOR_WARN)
            outer.addLayout(top)
            return box, 38

        prefix = "✎ " if changed else ""
        loc.setText(prefix + (info.get("location") or ""))
        loc.setStyleSheet("font-size:13px;color:#444;")
        if changed:
            loc.setToolTip("该值已被修改，显示的是新值在原文中的位置。")

        if kind == "pdf":
            btn = QPushButton("点击查看")
            btn.setFixedHeight(26)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton{background:#eef2ea;color:%s;border:1px solid #c9d6bd;"
                "border-radius:5px;padding:0 8px;font-size:13px;}"
                "QPushButton:hover{background:#e0e8d8;}" % COLOR_OK)
            page, rect = info.get("page"), info.get("rect")
            btn.clicked.connect(
                lambda _, g=gidx, f=field, p=page, r=rect, s=snippet:
                self._open_viewer(g, f, p, r, s))
            top.addWidget(btn, 0)
            outer.addLayout(top)
            if snippet:
                add_snippet(snippet[:60])
                return box, 58
            return box, 42

        outer.addLayout(top)
        if snippet:
            add_snippet(snippet[:60])
            return box, 56
        return box, 38

    def _open_viewer(self, gidx, field, page, rect, snippet, note=""):
        if not page:
            return
        src = self.project if gidx < 0 else self.products[gidx]
        dlg = EvidenceViewer(self._source_path, page, rect, field,
                            src.get(field, ""),
                            snippet=snippet, note=note, parent=self)
        dlg.exec_()

    # ---------------- 操作 ----------------

    def _current_gidx(self):
        """当前光标所在行属于哪个产品组。返回 -1=项目组，None=无法判断。"""
        row = self.table.currentRow()
        ref = self._row_map.get(row)
        if not ref:
            return None
        return ref[1]

    def _add_product(self):
        self._sync_from_table()
        base = self.products[0] if self.products else {}
        newp = self._norm({}, schema.PRODUCT_FIELDS)
        for k in INHERIT_FIELDS:
            v = (base.get(k) or "").strip()
            if v:
                newp[k] = v
        newp["_page"] = None
        self.products.append(newp)
        self._origin.append(dict(newp))
        self._ev_products.append({})
        self._rebuild(resync=False)
        self._revalidate()
        # 滚动到新产品组
        self.table.scrollToBottom()

    def _del_product(self):
        if len(self.products) <= 1:
            ui_msg.info(self, "提示", "至少要保留一个产品。")
            return
        gidx = self._current_gidx()
        if gidx is None or gidx < 0:
            ui_msg.info(
                self, "提示",
                "请先把光标点在某台设备的字段行上，再点「删除当前产品」。")
            return
        tag = self.products[gidx].get("设备位号") or "产品 %d" % (gidx + 1)
        if not ui_msg.ask(
                self, "确认删除",
                "确定从本次录入里删除「%s」吗？" % tag,
                ok_text="确认删除", cancel_text="取消",
                detail="只是不在这次建库里包含它，不会影响已有数据。"):
            return
        self.products.pop(gidx)
        self._origin.pop(gidx)
        if gidx < len(self._ev_products):
            self._ev_products.pop(gidx)
        self._rebuild(resync=False)
        self._revalidate()

    def _apply_suggestions(self):
        self._sync_from_table()
        applied = 0
        for (gidx, field), e in list(self._err_map.items()):
            sv = e.get("suggest_value")
            if not sv:
                continue
            if gidx < 0:
                self.project[field] = sv
            else:
                self.products[gidx][field] = sv
            applied += 1
        if not applied:
            ui_msg.info(self, "提示", "当前没有可自动采用的建议值。")
            return
        # 数据刚被改成建议值，重建时不能再从旧表格同步回来
        self._rebuild(resync=False)
        self._revalidate()

    def _focus_first_problem(self):
        """
        定位到第一个问题的字段，但滚动位置给到**它所在组的标题行**。
        只滚到字段行会把组标题（「产品 2 / 共 11　OST-E-1903A/B…」）挤出视口，
        用户看到半截内容会以为少了东西。
        """
        problem_row, group_row = None, None
        for row, ref in sorted(self._row_map.items()):
            if ref[0] != "field":
                continue
            _, gidx, field = ref
            if (gidx, field) in self._err_map or (gidx, field) in self._miss_set:
                problem_row = row
                for r2 in sorted(self._row_map):
                    rf = self._row_map[r2]
                    if rf[0] == "group" and rf[1] == gidx:
                        group_row = r2
                        break
                break

        if problem_row is None:
            self.table.scrollToTop()
            if self.table.rowCount():
                self.table.setCurrentCell(1, COL_VALUE)
            return

        self.table.setCurrentCell(problem_row, COL_VALUE)
        anchor = group_row if group_row is not None else problem_row
        item = self.table.item(anchor, COL_FIELD)
        if item:
            self.table.scrollToItem(item, QAbstractItemView.PositionAtTop)

    def _on_ok(self):
        self._sync_from_table()
        self._revalidate()
        if self._err_map or self._miss_set:
            ui_msg.warn(
                self, "还不能确认",
                "还有 %d 处不合法、%d 项必填未填，请改完再确认。"
                % (len(self._err_map), len(self._miss_set)))
            self._focus_first_problem()
            return
        self.result_project = dict(self.project)
        self.result_products = [dict(p) for p in self.products]
        self.accept()
