from PyQt5 import QtWidgets, QtCore, QtGui


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

        # 背景填充色
        painter.fillRect(rect, QtGui.QColor("#F2F2F2"))

        # 绘制文字
        text = self.model().headerData(logicalIndex, self.orientation(), QtCore.Qt.DisplayRole)
        painter.setPen(QtGui.QPen(QtCore.Qt.black))

        # 设置字体为加粗← 新增的代码(统一界面需求用)
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
