# -*- coding: utf-8 -*-
"""
直接加载正式项目的 pipe_attachment_define.ui，并复刻它的运行期表头。

为什么不能"光靠 .ui"就完事
--------------------------------------------------
.ui 里只有骨架：两张空表（tableWidget_pipe_title / tableWidget_pipe）、
一排按钮、一个 tab。真正决定"长什么样"的是 dynamically_adjust_ui.py 里
setup_tableWidget_pipe_title_freeze() 那 150 行：三级合并表头、单位下拉、
行高 30/65/0、列宽表（19 列，总宽约 2695px）。

那份代码在 import 阶段就会连 MySQL、读产品库，不能直接复用。
所以这里把"表头构建 + 列宽"的逻辑按原样搬过来（常量逐条对齐），
.ui 本身仍然是原文件只读加载 —— 正式项目改界面，这个 Demo 跟着变。
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from PyQt5 import uic
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QLabel, QPushButton,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from agent import spec

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

# 允许用环境变量指向别处的正式项目副本（演示机没有 D 盘时用）
UI_DIR = os.environ.get(
    "DL_UI_DIR", os.path.join(PROJECT_ROOT, "modules", "guankoudingyi", "ui")
)
RES_DIR = os.path.abspath(os.path.join(UI_DIR, "..", "resource"))

UI_EXCHANGER = "pipe_attachment_define.ui"
UI_CONTAINER = "pipe_attachment_define_container.ui"

# 二级表头换行（与正式项目 PIPE_HEADER_DISPLAY_LINES 一致）
HEADER_DISPLAY_LINES = {
    "密封面型式": "密封面\n型式",
    "管口所属元件": "管口所属\n元件",
    "轴向定位基准": "轴向定位\n基准",
    "轴向定位距离": "轴向定位\n距离",
}

# 列宽（与正式项目 get_pipe_min_column_widths 一致）
MIN_WIDTHS = {
    0: 80, 1: 110, 2: 165, 3: 165, 4: 110, 5: 250, 6: 130, 7: 125, 8: 110,
    9: 160, 10: 170, 11: 140, 12: 140, 13: 135, 14: 135, 15: 135, 16: 140,
}


class NoWheelComboBox(QComboBox):
    """表头单位下拉：禁止滚轮误改（与正式项目的 NoWheelComboBox 同义）。"""

    def wheelEvent(self, event):  # noqa: N802
        event.ignore()


def _rewrite_icon_urls(widget: QWidget) -> int:
    """.ui 里附件按钮的图标写成 url(:/icons/xxx.png)，需要注册 pic_rc 资源。

    那份 pic_rc.py 是正式项目用别的 PyQt 版本编译的，直接 qRegisterResourceData
    会让当前解释器段错误（实测 5.15 与 5.12 的 rcc 格式不兼容）。
    所以这里不注册资源，而是把 url(:/icons/a.png) 就地改写成磁盘上的真实路径。
    """
    pattern = re.compile(r"url\(\s*:/icons/([^)]+?)\s*\)")
    fixed = 0
    for child in [widget] + widget.findChildren(QWidget):
        qss = child.styleSheet()
        if not qss or ":/icons/" not in qss:
            continue

        def repl(match, _child=child):
            name = match.group(1)
            path = os.path.join(RES_DIR, name).replace("\\", "/")
            return f'url("{path}")' if os.path.exists(path) else match.group(0)

        new_qss = pattern.sub(repl, qss)
        if new_qss != qss:
            child.setStyleSheet(new_qss)
            fixed += 1
    return fixed


def _load_ui(path: str, widget: QWidget) -> None:
    """加载 .ui。图标是相对路径，必须在 ui 目录下解析，故临时切 cwd。"""
    old = os.getcwd()
    os.chdir(os.path.dirname(path))
    try:
        uic.loadUi(path, widget)
    finally:
        os.chdir(old)


class NozzleDefineShell(QWidget):
    """管口定义界面外壳（左侧表格 + 中间示意图），接口供 Agent 写入。"""

    rowSelected = pyqtSignal(str)
    unitsChanged = pyqtSignal(str, str, str)
    deleteRequested = pyqtSignal()
    upRequested = pyqtSignal()
    downRequested = pyqtSignal()
    copyRequested = pyqtSignal()
    overviewRequested = pyqtSignal()
    ioRequested = pyqtSignal(str)     # "导入" / "导出" / "保存"

    def __init__(self, is_container: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.is_container_product = bool(is_container)
        ui_file = UI_CONTAINER if self.is_container_product else UI_EXCHANGER
        ui_path = os.path.join(UI_DIR, ui_file)
        if not os.path.exists(ui_path):
            raise FileNotFoundError(
                f"找不到正式界面文件：{ui_path}\n"
                f"可通过环境变量 DL_UI_DIR 指向 modules/guankoudingyi/ui 目录。"
            )
        _load_ui(ui_path, self)
        _rewrite_icon_urls(self)

        self.combo_nominal_size_type = None
        self.combo_pressure_level_type = None
        self.combo_weld_end_spec_type = None
        self._rows: List[Dict[str, Any]] = []
        self._highlight = ""

        self._relax_minimums()
        self._build_title_table()
        self._build_main_table()
        self._install_sketch()
        self._apply_attachment_tab_policy()
        self._wire_buttons()
        self.resize(1240, 860)

    # ------------------------------------------------------------ 基础调整
    def _relax_minimums(self):
        """.ui 把最小宽度写死 1177，放进分割器会顶到屏幕外，这里只放宽宽度下限。

        高度、字体、边框、按钮样式一律不动 —— 视觉与正式界面保持一致。
        """
        for name in ("tabWidget", "widget_control"):
            w = getattr(self, name, None)
            if w is not None:
                w.setMinimumWidth(940)

    def _install_sketch(self):
        from .sketch import ExchangerSketch

        host = getattr(self, "widget_control", None)
        if host is None:
            return
        layout = host.layout()
        if layout is None:
            layout = QVBoxLayout(host)
            layout.setContentsMargins(0, 0, 0, 0)
        self.sketch = ExchangerSketch(host)
        layout.addWidget(self.sketch)

    def _apply_attachment_tab_policy(self):
        tw = getattr(self, "tabWidget", None)
        if tw is None:
            return
        for i in range(tw.count()):
            if (tw.tabText(i) or "").strip() == "附件定义":
                tw.setTabEnabled(i, False)
                tw.setTabToolTip(i, "Demo 只演示「管口定义」，附件定义未接入")

    # ------------------------------------------------------------ 冻结表头
    def _build_title_table(self):
        t = self.tableWidget_pipe_title
        t.setStyleSheet(
            "QTableView {"
            " border-top: 1px solid palette(mid);"
            " border-left: 1px solid palette(mid);"
            " border-right: 1px solid palette(mid);"
            " border-bottom: none;"
            " gridline-color: palette(midlight); }"
        )
        t.setSelectionMode(QAbstractItemView.NoSelection)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)

        level1 = [
            "序号", "管口代号", "管口功能", "管口用途", "公称尺寸",
            "法兰规格", "管口位置", "管口附件", "管口载荷",
        ]
        level2 = {
            "法兰规格": ["法兰标准", "压力等级", "法兰型式", "密封面型式", "焊端规格"],
            "管口位置": self._position_subheaders(),
        }
        unit_options = {
            "公称尺寸": ["DN", "NPS"],
            "压力等级": ["Class", "PN"],
            "焊端规格": ["mm", "Sch"],
        }

        header_map: List[tuple] = []
        for h1 in level1:
            if h1 in level2:
                for h2 in level2[h1]:
                    header_map.append((h1, h2))
            else:
                header_map.append((h1, ""))

        t.setColumnCount(len(header_map))
        t.setRowCount(3)

        col = 0
        for h1 in level1:
            if h1 == "公称尺寸":
                t.setSpan(0, col, 3, 1)
                # 这个格子稍后要放「标签 + 单位下拉」控件；item 留空，
                # 否则表格会再画一遍文字，和控件里的标签叠成双影。
                item = QTableWidgetItem("")
                item.setTextAlignment(Qt.AlignCenter)
                t.setItem(0, col, item)
                col += 1
            elif h1 in level2:
                span = len(level2[h1])
                t.setSpan(0, col, 1, span)
                item = QTableWidgetItem(h1)
                item.setTextAlignment(Qt.AlignCenter)
                t.setItem(0, col, item)
                col += span
            else:
                t.setSpan(0, col, 3, 1)
                item = QTableWidgetItem(h1)
                item.setTextAlignment(Qt.AlignCenter)
                t.setItem(0, col, item)
                col += 1

        for i, (h1, h2) in enumerate(header_map):
            key = h2 or h1
            if key == "公称尺寸":
                widget = QWidget()
                lay = QVBoxLayout(widget)
                lay.setContentsMargins(2, 2, 2, 2)
                lay.setSpacing(2)
                label = QLabel(key)
                label.setAlignment(Qt.AlignCenter)
                label.setStyleSheet("font-size: 12pt;")
                # 12pt 字实际需要 ~26px，布局算出的 20px 会把字切掉，这里补足高度
                label.setMinimumHeight(26)
                combo = NoWheelComboBox()
                combo.addItems(unit_options[key])
                combo.setStyleSheet("QComboBox { font-size: 10pt; }")
                self.combo_nominal_size_type = combo
                lay.addStretch()
                lay.addWidget(label)
                lay.addWidget(combo)
                lay.addStretch()
                t.setCellWidget(0, i, widget)
            elif key in unit_options:
                t.setSpan(1, i, 2, 1)
                widget = QWidget()
                lay = QVBoxLayout(widget)
                lay.setContentsMargins(1, 1, 1, 1)
                lay.setSpacing(1)
                label = QLabel(key)
                label.setAlignment(Qt.AlignCenter)
                label.setStyleSheet("font-size: 12pt;")
                # 12pt 字实际需要 ~26px，布局算出的 20px 会把字切掉，这里补足高度
                label.setMinimumHeight(26)
                combo = NoWheelComboBox()
                combo.addItems(unit_options[key])
                combo.setStyleSheet("QComboBox { font-size: 10pt; }")
                if key == "压力等级":
                    self.combo_pressure_level_type = combo
                elif key == "焊端规格":
                    self.combo_weld_end_spec_type = combo
                lay.addWidget(label)
                lay.addWidget(combo)
                t.setCellWidget(1, i, widget)
            else:
                t.setSpan(1, i, 2, 1)
                item = QTableWidgetItem(HEADER_DISPLAY_LINES.get(key, key))
                item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
                t.setItem(1, i, item)

        t.setRowHeight(0, 30)
        t.setRowHeight(1, 65)
        t.setRowHeight(2, 0)

        dpi = t.logicalDpiY() / 96.0
        t.setFixedHeight(t.horizontalHeader().height() + 30 + 65 + int(6 * dpi))

        for combo in (self.combo_nominal_size_type,
                      self.combo_pressure_level_type,
                      self.combo_weld_end_spec_type):
            if combo is not None:
                combo.currentIndexChanged.connect(self._on_unit_changed)

    def _position_subheaders(self) -> List[str]:
        headers = [
            "管口所属元件", "轴向定位基准", "轴向定位距离",
            "轴向夹角(°)", "周向方位(°)", "偏心距(mm)", "外伸高度",
        ]
        if self.is_container_product:
            headers.append("内伸高度")
        return headers

    # ------------------------------------------------------------ 主表
    def _build_main_table(self):
        t = self.tableWidget_pipe
        t.setStyleSheet(
            "QTableView {"
            " border-top: none;"
            " border-left: 1px solid palette(mid);"
            " border-right: 1px solid palette(mid);"
            " border-bottom: 1px solid palette(mid);"
            " gridline-color: palette(midlight); }"
        )
        t.horizontalHeader().setVisible(False)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setColumnCount(self.tableWidget_pipe_title.columnCount())
        t.setWordWrap(False)
        t.setTextElideMode(Qt.ElideRight)
        t.setSelectionBehavior(QAbstractItemView.SelectItems)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
        t.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        t.verticalScrollBar().setSingleStep(max(1, int(t.verticalHeader().defaultSectionSize() / 3)))
        t.cellClicked.connect(self._on_cell_clicked)
        # 表头是另一张表，横向滚动必须跟着主表走，否则表头和数据会错位
        title = self.tableWidget_pipe_title
        title.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        t.horizontalScrollBar().valueChanged.connect(title.horizontalScrollBar().setValue)
        self._apply_widths()

    def _apply_widths(self):
        main, title = self.tableWidget_pipe, self.tableWidget_pipe_title
        widths = dict(MIN_WIDTHS)
        if self.is_container_product:
            widths[17] = 160
            widths[18] = 185
            widths[19] = 110
        else:
            widths[17] = 185
            widths[18] = 110

        for c in range(main.columnCount()):
            w = widths.get(c, 90)
            main.setColumnWidth(c, w)
            title.setColumnWidth(c, w)
        for c in range(main.columnCount()):
            main.resizeColumnToContents(c)
            title.resizeColumnToContents(c)
            w = max(main.columnWidth(c), title.columnWidth(c), widths.get(c, 90))
            main.setColumnWidth(c, w)
            title.setColumnWidth(c, w)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if not getattr(self, "_widths_done", False):
            self._widths_done = True
            self._apply_widths()

    # ------------------------------------------------------------ 按钮
    def _wire_buttons(self):
        handlers = {
            "导入": lambda: self.ioRequested.emit("导入"),
            "导出": lambda: self.ioRequested.emit("导出"),
            "保存": lambda: self.ioRequested.emit("保存"),
            "管口总览表": self.overviewRequested.emit,
            "管口复制": self.copyRequested.emit,
            "管口删除": self.deleteRequested.emit,
            "管口上移": self.upRequested.emit,
            "管口下移": self.downRequested.emit,
        }
        for btn in self.findChildren(QPushButton):
            text = (btn.text() or "").strip()
            if text in handlers:
                try:
                    btn.clicked.disconnect()
                except TypeError:
                    pass
                btn.clicked.connect(handlers[text])

    # ------------------------------------------------------------ 数据写入
    def set_rows(self, rows: List[Dict[str, Any]],
                 issues: Optional[Dict[int, List[Any]]] = None,
                 select_code: str = ""):
        self._rows = list(rows)
        issues = issues or {}
        self._last_issues = issues
        table = self.tableWidget_pipe
        field_col = self._field_columns()

        table.setUpdatesEnabled(False)
        table.setRowCount(len(self._rows) + 1)   # 末尾留一行空行，与正式界面一致

        for r, row in enumerate(self._rows):
            bad = {}
            for issue in issues.get(r, []):
                if issue.level == "info":       # info 只进悬浮提示，不占单元格
                    continue
                col = field_col.get(issue.field)
                if col is not None and col not in bad:
                    bad[col] = issue

            for c in range(table.columnCount()):
                if c == 0:
                    text = str(r + 1)
                else:
                    text = self._cell_text(row, c)
                item = table.item(r, c)
                if item is None:
                    item = QTableWidgetItem()
                    table.setItem(r, c, item)
                item.setText(text)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                item.setTextAlignment(self._alignment(c))
                issue = bad.get(c)
                keys = self._column_keys()
                pending = set(row.get("_pending") or [])
                emptied = (issue is None and text == "" and c > 0
                           and c < len(keys) and keys[c] in pending)
                if emptied:
                    # 上次填的值不合法被清空：格子留红，提示这里还要补
                    item.setBackground(_brush("#fdecec"))
                    item.setForeground(_brush("#b91c1c"))
                    item.setToolTip(f"{keys[c]}：上次输入的值不合法已被清空，需要重新给出")
                    continue
                if issue is None:
                    item.setBackground(_brush("#ffffff"))
                    item.setForeground(_brush("#000000"))
                elif issue.level == "error":
                    item.setBackground(_brush("#fdecec"))
                    item.setForeground(_brush("#b91c1c"))
                elif issue.level == "warning":
                    item.setBackground(_brush("#fff8e1"))
                    item.setForeground(_brush("#8a5a00"))
                else:
                    # info 级只在悬浮提示里说，不染色
                    item.setBackground(_brush("#ffffff"))
                    item.setForeground(_brush("#000000"))
                item.setToolTip(self._tooltip(row, issues.get(r, [])))

        # 末尾空行：清空内容，保持表格下端与正式界面一样"有一行待输入"
        blank = len(self._rows)
        for c in range(table.columnCount()):
            item = table.item(blank, c)
            if item is None:
                item = QTableWidgetItem()
                table.setItem(blank, c, item)
            item.setText("")
            item.setBackground(_brush("#ffffff"))
            item.setToolTip("")
            item.setFlags(Qt.ItemIsEnabled)

        table.setUpdatesEnabled(True)
        if select_code:
            self.select_code(select_code)
        self._refresh_sketch(select_code)

    def _field_columns(self) -> Dict[str, int]:
        mapping = {
            "管口代号": 1, "管口功能": 2, "管口用途": 3, "公称尺寸": 4, "尺寸单位": 4,
            "法兰标准": 5, "压力等级": 6, "压力等级类型": 6, "法兰型式": 7,
            "密封面型式": 8, "焊端规格": 9, "焊端规格单位": 9, "管口所属元件": 10,
            "轴向定位基准": 11, "轴向定位距离": 12, "轴向夹角": 13,
            "周向方位(°)": 14, "偏心距": 15, "外伸高度": 16,
        }
        if self.is_container_product:
            mapping["内伸高度"] = 17
        return mapping

    def _column_keys(self) -> List[str]:
        keys = [
            "序号", "管口代号", "管口功能", "管口用途", "公称尺寸",
            "法兰标准", "压力等级", "法兰型式", "密封面型式", "焊端规格",
            "管口所属元件", "轴向定位基准", "轴向定位距离", "轴向夹角",
            "周向方位(°)", "偏心距", "外伸高度",
        ]
        if self.is_container_product:
            keys.append("内伸高度")
        keys += ["管口附件", "管口载荷"]
        return keys

    def _cell_text(self, row: Dict[str, Any], col: int) -> str:
        keys = self._column_keys()
        if col >= len(keys):
            return ""
        key = keys[col]
        if key in ("管口附件", "管口载荷"):
            return ""
        val = row.get(key)
        if val in (None, ""):
            return ""
        if isinstance(val, float) and val == int(val):
            val = int(val)
        # 公称尺寸按表头单位显示：DN 10 ↔ NPS 3/8
        if key == "公称尺寸":
            return self._size_text(val, str(row.get("尺寸单位") or "DN"))
        # 法兰型式 / 密封面型式在项目里就是代号（WN、RF、MF），不做中文替换
        return str(val)

    @staticmethod
    def _size_text(val: Any, unit: str) -> str:
        text = str(val).strip()
        if unit.upper() == "NPS":
            if text.replace(".", "", 1).isdigit():
                return spec.DN_TO_NPS.get(("%g" % float(text)), text)
            return text
        if text.replace(".", "", 1).isdigit():
            return "%g" % float(text)
        return str(spec.NPS_TO_DN.get(text, text))

    @staticmethod
    def _alignment(col: int):
        center_cols = {0, 1, 4, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17}
        if col in center_cols:
            return Qt.AlignCenter
        return Qt.AlignLeft | Qt.AlignVCenter

    def _tooltip(self, row: Dict[str, Any], issues: List[Any]) -> str:
        lines = [f"管口 {row.get('管口代号') or '(待补)'}"]
        for key in ("管口功能", "管口用途", "管口所属元件", "轴向定位基准",
                    "轴向定位距离", "轴向夹角", "周向方位(°)", "偏心距",
                    "外伸高度", "内伸高度", "尺寸单位", "压力等级类型", "焊端规格单位"):
            val = row.get(key)
            if val not in (None, ""):
                lines.append(f"{key}：{val}")
        if issues:
            lines.append("—" * 10)
            for i in issues:
                mark = "✗" if i.level == "error" else "!"
                lines.append(f"{mark} {i.field}：{i.message}")
                if i.suggestion:
                    lines.append(f"    建议：{i.suggestion}")
        return "\n".join(lines)

    # ------------------------------------------------------------ 选中与单位
    def _on_cell_clicked(self, row: int, _col: int):
        if 0 <= row < len(self._rows):
            code = str(self._rows[row].get("管口代号") or "")
            self._highlight = code
            self._refresh_sketch(code)
            self.rowSelected.emit(code)

    def select_code(self, code: str):
        if not code:
            return
        for r, row in enumerate(self._rows):
            if str(row.get("管口代号") or "").upper() == code.upper():
                self.tableWidget_pipe.setCurrentCell(r, 1)
                self._highlight = code
                break

    def set_units(self, nominal: str = "", pressure: str = "", weld: str = ""):
        for combo, value in (
            (self.combo_nominal_size_type, nominal),
            (self.combo_pressure_level_type, pressure),
            (self.combo_weld_end_spec_type, weld),
        ):
            if combo is None or not value:
                continue
            idx = combo.findText(value)
            if idx >= 0 and idx != combo.currentIndex():
                combo.blockSignals(True)
                combo.setCurrentIndex(idx)
                combo.blockSignals(False)

    def current_units(self) -> Dict[str, str]:
        return {
            "nominal": self.combo_nominal_size_type.currentText() if self.combo_nominal_size_type else "DN",
            "pressure": self.combo_pressure_level_type.currentText() if self.combo_pressure_level_type else "PN",
            "weld": self.combo_weld_end_spec_type.currentText() if self.combo_weld_end_spec_type else "Sch",
        }

    def _on_unit_changed(self, _index: int):
        units = self.current_units()
        # 表头单位下拉是"整张表的视角"，切换后每一行都跟着走
        for r in self._rows:
            r["尺寸单位"] = units["nominal"]
            r["压力等级类型"] = units["pressure"]
            r["焊端规格单位"] = units["weld"]
        selected = self.selected_code()
        if self._rows:
            self.set_rows(self._rows, getattr(self, "_last_issues", None), selected)
        self.unitsChanged.emit(units["nominal"], units["pressure"], units["weld"])

    def _refresh_sketch(self, code: str = ""):
        sketch = getattr(self, "sketch", None)
        if sketch is not None:
            sketch.set_data(self._rows, code)

    # ------------------------------------------------------------ 选中信息
    def selected_code(self) -> str:
        row = self.tableWidget_pipe.currentRow()
        if 0 <= row < len(self._rows):
            return str(self._rows[row].get("管口代号") or "")
        return ""


def _brush(color: str) -> QBrush:
    return QBrush(QColor(color))
