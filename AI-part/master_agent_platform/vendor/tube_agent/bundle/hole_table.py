"""右侧“管孔数量分布”表：沿用正式程序 hole_distribution_table 的行为。

- 表头按“按行/按列”切换：`至水平中心线行号 / 管孔数量(上) / 管孔数量(下)`
  或 `至竖直中心线列号 / 管孔数量(左) / 管孔数量(右)`。
- 点击任意单元格 → 整行选中（正式程序 on_row_selection_changed 的整行选中）。
- 选中行背景使用正式程序相同的淡蓝色 RGB(173,216,230)。
- 表格只读，行高亮与图形选中双向同步。
"""
from __future__ import annotations

from PyQt5.QtCore import QEvent, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

ROW_HIGHLIGHT = QColor(173, 216, 230)  # 正式程序整行高亮色
HEADERS_BY_ROW = ("至水平中心线行号", "管孔数量(上)", "管孔数量(下)")
HEADERS_BY_COL = ("至竖直中心线列号", "管孔数量(左)", "管孔数量(右)")


class HoleDistributionTable(QWidget):
    rows_selected = pyqtSignal(list)      # 选中行下标列表
    arrangement_changed = pyqtSignal(bool)  # True=按行

    def __init__(self, parent=None):
        super().__init__(parent)
        self.by_row = True
        self._updating = False
        self._rows: list[tuple[int, int]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        title = QLabel("管孔数量分布")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-weight:600; font-size:10.5pt; color:#1f2329;")
        root.addWidget(title)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        self.total_label = QLabel("总管孔数量: 0")
        self.total_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.total_label.setStyleSheet("font-weight:600; color:#1f2329;")
        top.addWidget(self.total_label, 1)
        self.arrange_button = QPushButton("按行")
        self.arrange_button.setCursor(Qt.PointingHandCursor)
        self.arrange_button.setFixedSize(66, 26)
        self.arrange_button.setStyleSheet(
            "QPushButton{background:#ffffff;border:1px solid #dcdfe6;border-radius:6px;"
            "padding:0;font-size:9pt;color:#333;}"
            "QPushButton:hover{background:#f2f6fd;border-color:#c9dbfb;}"
        )
        self.arrange_button.clicked.connect(self.toggle_arrangement)
        top.addWidget(self.arrange_button)
        root.addLayout(top)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(HEADERS_BY_ROW)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        # 支持 Ctrl 点选 / Shift 连选多行（多行合并选中对应多个排的管孔）
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(24)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setMinimumSectionSize(46)
        # 选中行用正式程序的淡蓝底 + 深色字，避免系统蓝色高亮盖掉整行标识
        self.table.setStyleSheet(
            "QTableWidget::item:selected{background:#add8e6;color:#1f2329;}"
        )
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        # 正式程序 on_table_right_click：表格右键 = 取消选中（取消筛选）
        self.table.installEventFilter(self)
        self.table.viewport().installEventFilter(self)
        root.addWidget(self.table, 1)

        self.selected_label = QLabel("当前选中换热管：0 个")
        self.selected_label.setAlignment(Qt.AlignCenter)
        self.selected_label.setStyleSheet("color:#2458b8; font-weight:600;")
        root.addWidget(self.selected_label)

    # ---------- 数据 ----------
    def set_data(self, rows: list[list[tuple[float, float]]],
                 rows_neg: list[list[tuple[float, float]]] | None = None,
                 total: int | None = None) -> None:
        """rows/rows_neg：按行时是上/下两组；按列时是右/左两组。"""
        self._updating = True
        try:
            neg = rows_neg or []
            count = max(len(rows), len(neg))
            resized = count != self.table.rowCount()
            self.table.setRowCount(count)
            self._rows = []
            for index in range(count):
                a = len(rows[index]) if index < len(rows) else 0
                b = len(neg[index]) if index < len(neg) else 0
                self._rows.append((a, b))
                values = (str(index + 1), str(a), str(b))
                for col, text in enumerate(values):
                    item = self.table.item(index, col)
                    if item is None:
                        item = QTableWidgetItem(text)
                        item.setTextAlignment(Qt.AlignCenter)
                        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                        self.table.setItem(index, col, item)
                    else:
                        item.setText(text)
            if resized:
                # 行数变了（重新布管、按行/按列切换），旧的选中行已无意义
                self.table.clearSelection()
        finally:
            self._updating = False
        if total is not None:
            self.total_label.setText(f"总管孔数量: {total}")

    def set_total(self, total: int) -> None:
        self.total_label.setText(f"总管孔数量: {total}")

    def set_selected_count(self, count: int) -> None:
        self.selected_label.setText(f"当前选中换热管：{count} 个")

    def toggle_arrangement(self) -> None:
        self.by_row = not self.by_row
        self.arrange_button.setText("按行" if self.by_row else "按列")
        headers = HEADERS_BY_ROW if self.by_row else HEADERS_BY_COL
        self.table.setHorizontalHeaderLabels(headers)
        self.arrangement_changed.emit(self.by_row)

    # ---------- 选择 ----------
    def eventFilter(self, obj, event):  # noqa: N802 - Qt API
        if (
            obj in (self.table, self.table.viewport())
            and event.type() == QEvent.MouseButtonPress
            and event.button() == Qt.RightButton
        ):
            self.clear_selection()
            self._on_selection_changed()
            return True
        return super().eventFilter(obj, event)

    def clear_selection(self) -> None:
        self._updating = True
        try:
            self.table.clearSelection()
            for row in range(self.table.rowCount()):
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    if item is not None:
                        item.setBackground(QBrush(Qt.NoBrush))
        finally:
            self._updating = False

    def _on_selection_changed(self) -> None:
        if self._updating:
            return
        indexes = self.table.selectedIndexes()
        selected_rows = sorted({index.row() for index in indexes})
        self._paint_rows(selected_rows)
        # 空列表也要发：Ctrl 取消最后一行时图形中的选中要一起清掉
        self.rows_selected.emit(selected_rows)

    def _paint_rows(self, rows: list[int]) -> None:
        self._updating = True
        try:
            for row in range(self.table.rowCount()):
                brush = QBrush(ROW_HIGHLIGHT) if row in rows else QBrush(Qt.NoBrush)
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    if item is not None:
                        item.setBackground(brush)
        finally:
            self._updating = False

    def highlight_for_selection(self, highlighted_rows: list[int]) -> None:
        """图形选中变化 → 表格高亮对应行（不改变表格的选中行，避免来回触发）。"""
        self._paint_rows(highlighted_rows)

    def visible_row_numbers(self) -> list[int]:
        return list(range(self.table.rowCount()))
