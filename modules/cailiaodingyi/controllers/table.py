from PyQt5 import QtWidgets, QtCore, QtGui


# 与 paradefine_newui.ui 中详细定义表保持一致（表头走 QSS，不走 CustomHeaderView 旧自绘）
PARAM_DETAIL_TABLE_QSS = """
QTableWidget {
    background-color: #ffffff;
    alternate-background-color: #f7f9fc;
    border: 1px solid #CCCCCC;
    gridline-color: #CCCCCC;
    color: #1f1f1f;
    selection-background-color: #d9e6f7;
    selection-color: #1f1f1f;
}
QHeaderView::section {
    background-color: #f3f5f8;
    color: #1f1f1f;
    border: 1px solid #CCCCCC;
    padding: 4px 6px;
    font-weight: 600;
}
"""


def setup_param_detail_table(table, *, use_custom_header=False, stretch_columns=True, header_height=None):
    """
    给动态创建的详细定义表套上与普通元件一致的新 UI 样式。

    注意：普通元件 tableWidget_para 的表头实际由 Form QSS（#f3f5f8）绘制；
    若再装 CustomHeaderView，会走 paintSection 旧自绘色，表头就会仍像旧 UI。
    因此默认不装 CustomHeaderView，只套与 paradefine_newui.ui 一致的 QSS。
    """
    if table is None:
        return table

    if use_custom_header:
        try:
            table.setHorizontalHeader(CustomHeaderView(QtCore.Qt.Horizontal, table))
        except Exception:
            pass
    else:
        # 确保不是残留的 CustomHeaderView（否则仍会旧色自绘）
        header = table.horizontalHeader()
        if isinstance(header, CustomHeaderView):
            table.setHorizontalHeader(QtWidgets.QHeaderView(QtCore.Qt.Horizontal, table))

    table.setStyleSheet(PARAM_DETAIL_TABLE_QSS)
    table.setAlternatingRowColors(False)
    table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    table.setEditTriggers(QtWidgets.QAbstractItemView.SelectedClicked)
    table.verticalHeader().setVisible(False)

    header = table.horizontalHeader()
    header.setStyleSheet("")  # 避免旧的 header 局部 QSS 覆盖 Form 风格
    if stretch_columns:
        for i in range(max(table.columnCount(), 1)):
            header.setSectionResizeMode(i, QtWidgets.QHeaderView.Stretch)
    header.setDefaultAlignment(QtCore.Qt.AlignCenter)
    if header_height:
        header.setFixedHeight(header_height)
    else:
        # 取消此前固定 35 的旧高度，与普通元件表头高度一致
        try:
            header.setMinimumHeight(0)
            header.setMaximumHeight(16777215)
        except Exception:
            pass

    # Tab 仅落在可输入单元格（参数名称/单位/只读格自动跳过）
    try:
        from modules.cailiaodingyi.controllers.style import install_editable_only_tab
        install_editable_only_tab(table, mode="editable")
    except Exception:
        pass
    return table


def highlight_param_detail_selection(table):
    """
    选中行高亮：未选中单元格刷 #d0e7ff，与普通元件 on_param_table_selection_changed 一致。
    供动态详细定义表在 itemSelectionChanged 时调用。
    """
    if table is None:
        return
    selected_items = table.selectedItems()
    selected_cells = {(item.row(), item.column()) for item in selected_items}
    selected_rows = {row for row, _ in selected_cells}

    for r in range(table.rowCount()):
        for c in range(table.columnCount()):
            item = table.item(r, c)
            if not item:
                continue
            if (r, c) in selected_cells:
                continue
            item.setBackground(QtGui.QColor("#ffffff"))

    for row in selected_rows:
        for col in range(table.columnCount()):
            if (row, col) in selected_cells:
                continue
            item = table.item(row, col)
            if item:
                item.setBackground(QtGui.QColor("#d0e7ff"))


def install_param_detail_selection_highlight(table):
    """给动态详细定义表挂上选中高亮（避免重复连接）。"""
    if table is None:
        return
    if getattr(table, "_param_detail_sel_hl_installed", False):
        return

    def _on_sel_changed():
        highlight_param_detail_selection(table)

    try:
        table.itemSelectionChanged.connect(_on_sel_changed)
        table._param_detail_sel_hl_installed = True
    except Exception:
        pass


class CustomHeaderView(QtWidgets.QHeaderView):
    """表头：可选 Excel 式筛选箭头，仅点击箭头触发筛选。"""

    filterArrowClicked = QtCore.pyqtSignal(int)

    # 箭头可点区域宽度（像素）
    ARROW_HIT_WIDTH = 18

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setDefaultAlignment(QtCore.Qt.AlignCenter)
        self._show_filter_arrows = False
        self._hover_section = -1
        self.setMouseTracking(True)

    def setShowFilterArrows(self, enabled: bool):
        self._show_filter_arrows = bool(enabled)
        self.viewport().update()

    def showFilterArrows(self) -> bool:
        return self._show_filter_arrows

    def _arrow_rect(self, section_rect: QtCore.QRect) -> QtCore.QRect:
        w = self.ARROW_HIT_WIDTH
        return QtCore.QRect(
            section_rect.right() - w + 1,
            section_rect.top(),
            w,
            section_rect.height(),
        )

    def _section_at_pos(self, pos: QtCore.QPoint) -> int:
        return self.logicalIndexAt(pos)

    def _is_on_filter_arrow(self, pos: QtCore.QPoint) -> int:
        """若点击落在筛选箭头上，返回逻辑列号；否则返回 -1。"""
        if not self._show_filter_arrows:
            return -1
        logical = self._section_at_pos(pos)
        if logical < 0:
            return -1
        # 避开列宽拖拽热区
        if self.orientation() == QtCore.Qt.Horizontal:
            visual = self.visualIndex(logical)
            x = self.sectionViewportPosition(logical)
            section_w = self.sectionSize(logical)
            # 右侧约 3px 留给 resize handle
            if pos.x() >= x + section_w - 3:
                return -1
            section_rect = QtCore.QRect(x, 0, section_w, self.height())
        else:
            return -1
        if self._arrow_rect(section_rect).contains(pos):
            return logical
        return -1

    def paintSection(self, painter, rect, logicalIndex):
        painter.save()

        # 与 paradefine_newui.ui 表头色一致
        painter.fillRect(rect, QtGui.QColor("#f3f5f8"))

        # 绘制文字
        text = self.model().headerData(logicalIndex, self.orientation(), QtCore.Qt.DisplayRole)
        painter.setPen(QtGui.QPen(QtGui.QColor("#1f1f1f")))

        font = painter.font()
        font.setBold(True)
        painter.setFont(font)

        text_rect = QtCore.QRect(rect)
        if self._show_filter_arrows:
            # 给右侧箭头留空，避免汉字与箭头重叠
            text_rect.setRight(rect.right() - self.ARROW_HIT_WIDTH)

        painter.drawText(text_rect, QtCore.Qt.AlignCenter, str(text))

        # Excel 式下拉箭头
        if self._show_filter_arrows:
            arrow_area = self._arrow_rect(rect)
            cx = arrow_area.center().x()
            cy = arrow_area.center().y()
            # 悬停时箭头略深
            color = QtGui.QColor("#333333") if logicalIndex == self._hover_section else QtGui.QColor("#666666")
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QBrush(color))
            size = 4
            points = [
                QtCore.QPoint(cx - size, cy - size // 2),
                QtCore.QPoint(cx + size, cy - size // 2),
                QtCore.QPoint(cx, cy + size // 2 + 1),
            ]
            painter.drawPolygon(QtGui.QPolygon(points))

        # 底部分隔线
        pen = QtGui.QPen(QtGui.QColor("#CCCCCC"))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())

        # 列之间竖线
        if self.model() and logicalIndex != self.model().columnCount() - 1:
            painter.drawLine(rect.topRight(), rect.bottomRight())

        painter.restore()

    def mouseMoveEvent(self, event):
        if self._show_filter_arrows:
            logical = self._is_on_filter_arrow(event.pos())
            prev = self._hover_section
            self._hover_section = logical
            if logical >= 0:
                self.viewport().setCursor(QtCore.Qt.PointingHandCursor)
            else:
                self.viewport().unsetCursor()
            if prev != self._hover_section:
                self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hover_section >= 0:
            self._hover_section = -1
            self.viewport().unsetCursor()
            self.viewport().update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if (
            self._show_filter_arrows
            and event.button() == QtCore.Qt.LeftButton
        ):
            logical = self._is_on_filter_arrow(event.pos())
            if logical >= 0:
                self.filterArrowClicked.emit(logical)
                event.accept()
                return
        super().mousePressEvent(event)
