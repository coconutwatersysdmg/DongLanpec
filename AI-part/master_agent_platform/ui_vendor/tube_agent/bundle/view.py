"""布管图形视图：沿用正式程序 ZoomableGraphicsView 的交互习惯。

- Ctrl + 滚轮缩放（正式程序同款，普通滚轮仍用于滚动/平移）。
- 左键在空白处拖动 = 框选换热管（框选后右侧数量表同步）。
- 中键 / Shift+右键拖动 = 平移视图。
- 右键 = 取消筛选（清空表格选中行与图形选中，正式程序 handle_global_right_click）。
- 单击图元 = 选中/取消选中，选中状态由页面统一维护。
"""
from __future__ import annotations

from PyQt5.QtCore import QPoint, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QPainter, QPen
from PyQt5.QtWidgets import QGraphicsScene, QGraphicsView, QRubberBand


class LayoutGraphicsView(QGraphicsView):
    rubber_band_finished = pyqtSignal(object)  # QRectF（场景坐标）
    clear_selection_requested = pyqtSignal()   # 右键：取消筛选/选中

    ZOOM_FACTOR = 1.1

    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.zoom_factor = self.ZOOM_FACTOR
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setBackgroundBrush(QBrush(QColor("#ffffff")))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._rubber = QRubberBand(QRubberBand.Rectangle, self)
        self._origin = QPoint()
        self._banding = False
        self._panning = False
        self._pan_origin = QPoint()
        self._auto_fit = True
        self._fitting = False

    # ---- 缩放（正式程序同款）----
    def wheelEvent(self, event):  # noqa: N802 - Qt API
        if event.modifiers() & Qt.ControlModifier:
            self._auto_fit = False
            if event.angleDelta().y() > 0:
                self.scale(self.zoom_factor, self.zoom_factor)
            else:
                self.scale(1 / self.zoom_factor, 1 / self.zoom_factor)
            event.accept()
            return
        super().wheelEvent(event)

    def resizeEvent(self, event):  # noqa: N802 - Qt API
        super().resizeEvent(event)
        if self._auto_fit and not self._fitting:
            QTimer.singleShot(0, self.fit_all)

    def showEvent(self, event):  # noqa: N802 - Qt API
        super().showEvent(event)
        if self._auto_fit and not self._fitting:
            QTimer.singleShot(0, self.fit_all)

    def fit_all(self, margin: float = 12.0) -> None:
        self._auto_fit = True
        self._fitting = False
        scene = self.scene()
        if scene is None:
            return
        rect = scene.sceneRect()
        if rect.isNull() or rect.isEmpty():
            rect = scene.itemsBoundingRect()
        if not rect.isEmpty():
            self.fitInView(rect.adjusted(-margin, -margin, margin, margin), Qt.KeepAspectRatio)

    # ---- 框选 / 平移 ----
    def mousePressEvent(self, event):  # noqa: N802 - Qt API
        if event.button() == Qt.MiddleButton or (
            event.button() == Qt.RightButton and event.modifiers() & Qt.ShiftModifier
        ):
            self._panning = True
            self._auto_fit = False
            self._pan_origin = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.RightButton:
            # 正式程序：图形/页面空白处右键 = 取消筛选，不再只是平移
            self.clear_selection_requested.emit()
            event.accept()
            return
        if event.button() == Qt.LeftButton and self.itemAt(event.pos()) is None:
            self._banding = True
            self._origin = event.pos()
            self._rubber.setGeometry(QRect(self._origin, self._origin).normalized())
            self._rubber.show()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt API
        if self._panning:
            delta = event.pos() - self._pan_origin
            self._pan_origin = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        if self._banding:
            self._rubber.setGeometry(QRect(self._origin, event.pos()).normalized())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt API
        if self._panning:
            self._panning = False
            self.unsetCursor()
            event.accept()
            return
        if self._banding and event.button() == Qt.LeftButton:
            self._banding = False
            rect = self._rubber.geometry()
            self._rubber.hide()
            if rect.width() > 4 and rect.height() > 4:
                polygon = self.mapToScene(rect)
                self.rubber_band_finished.emit(polygon.boundingRect())
            event.accept()
            return
        super().mouseReleaseEvent(event)
