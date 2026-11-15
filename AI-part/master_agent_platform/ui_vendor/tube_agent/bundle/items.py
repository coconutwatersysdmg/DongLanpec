"""布管图形项：从正式程序 My_Piping.py 的图形类抽取。

对应关系（正式程序 -> 本文件）：
    ClickableCircleItem      -> TubeItem / RodItem / BlockTubeItem
    ClickableRectItem        -> ComponentRectItem（旁路挡板、中间挡板、防冲板、滑道）
    ClickableRadialHoleItem  -> RadialHoleItem
选中样式保持正式程序原值：金色边框 RGB(255,215,0)、淡蓝填充 RGB(173,216,230)。
"""
from __future__ import annotations

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QPainterPath, QPen
from PyQt5.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsEllipseItem, QGraphicsRectItem

TUBE_PEN_COLOR = QColor(0, 0, 80)          # 换热管：深蓝（正式程序 draw_layout）
ROD_COLOR = QColor(255, 0, 0)              # 拉杆：红（正式程序 build_lagan red_pen/red_brush）
SIDE_ROD_COLOR = QColor(200, 0, 0)         # 自由拉杆：深红
BLOCK_TUBE_COLOR = QColor(128, 128, 128)   # 中间挡管：灰
CENTER_BAFFLE_COLOR = QColor(128, 0, 128)  # 中间挡板：紫
BYPASS_COLOR = QColor(0, 128, 0)           # 旁路挡板：绿
SLIDE_COLOR = QColor(0, 160, 60)           # 滑道：绿
IMPINGE_COLOR = QColor(70, 110, 180)       # 防冲板：蓝灰
IMPINGE_PEN_COLOR = QColor(0, 0, 139)      # 防冲板轮廓线：深蓝（正式程序 QColor(0,0,139)）
SELECTED_PEN_COLOR = QColor(255, 215, 0)
SELECTED_FILL = QColor(173, 216, 230)


class _Selectable:
    """正式程序里每个图元都靠自身 is_selected + editor.selected_* 列表记录选中。"""

    item_kind = "item"

    def _init_selectable(self, controller):
        self.controller = controller
        self.is_selected = False
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)  # 选中由 controller 统一管理
        self.setAcceptedMouseButtons(Qt.LeftButton)

    def apply_selected(self, selected: bool) -> None:
        self.is_selected = bool(selected)
        self.update()

    def mousePressEvent(self, event):  # noqa: N802 - Qt API
        if event.button() == Qt.LeftButton and self.controller is not None:
            self.controller.item_clicked(self, event.modifiers())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802 - Qt API
        if (
            event.button() == Qt.LeftButton
            and self.controller is not None
            and getattr(self, "component_index", None) is not None
        ):
            self.controller.item_double_clicked(self)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class TubeItem(_Selectable, QGraphicsEllipseItem):
    """换热管孔。坐标与半径来自正式程序布管接口返回值。

    布管接口的 y 向上，Qt 场景的 y 向下；正式程序绘制时统一 `_add(x, -y)`
    （My_Piping.py 28409 行），这里同样只翻转绘制位置，`self.center` 保留原始坐标，
    选中/写库/数量表联动都用原值。
    """

    item_kind = "tube"

    def __init__(self, center, radius, controller=None):
        cx, cy = float(center[0]), -float(center[1])
        rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        super().__init__(rect)
        self.center = (float(center[0]), float(center[1]))
        self.radius = float(radius)
        self.base_pen = QPen(TUBE_PEN_COLOR)
        self.base_pen.setWidthF(1.0)
        self.setPen(self.base_pen)
        self.setBrush(QBrush(Qt.NoBrush))
        self.setZValue(0)
        self._init_selectable(controller)
        self.setToolTip(f"换热管 ({self.center[0]:.2f}, {self.center[1]:.2f})")

    def paint(self, painter, option, widget=None):  # noqa: N802 - Qt API
        if self.is_selected:
            pen = QPen(SELECTED_PEN_COLOR)
            pen.setWidthF(2.4)
            painter.setPen(pen)
            painter.setBrush(QBrush(SELECTED_FILL))
        else:
            painter.setPen(self.base_pen)
            painter.setBrush(QBrush(Qt.NoBrush))
        painter.drawEllipse(self.rect())


class GhostTubeItem(TubeItem):
    """已删除的管孔：虚线圆圈 + 小叉，样式照正式程序在“被删除的换热管位置”
    补画的提示圆（My_Piping.py 31410 行），既能看见删了哪儿，也能再点选它恢复。
    """

    item_kind = "tube"
    GHOST_COLOR = QColor(214, 96, 96)

    def __init__(self, center, radius, controller=None):
        super().__init__(center, radius, controller)
        pen = QPen(self.GHOST_COLOR)
        pen.setWidthF(1.1)
        pen.setStyle(Qt.DashLine)
        self.base_pen = pen
        self.setZValue(-0.5)
        self.setToolTip(
            f"已删除的换热管孔 ({self.center[0]:.2f}, {self.center[1]:.2f})，点一下可选中恢复"
        )

    def paint(self, painter, option, widget=None):  # noqa: N802 - Qt API
        super().paint(painter, option, widget)
        cx, cy = self.rect().center().x(), self.rect().center().y()
        r = self.radius
        if self.is_selected:
            pen = QPen(SELECTED_PEN_COLOR)
            pen.setWidthF(1.8)
        else:
            pen = QPen(QColor(190, 90, 90, 190))
            pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(QBrush(Qt.NoBrush))
        painter.drawLine(QPointF(cx - r * 0.7, cy - r * 0.7), QPointF(cx + r * 0.7, cy + r * 0.7))
        painter.drawLine(QPointF(cx - r * 0.7, cy + r * 0.7), QPointF(cx + r * 0.7, cy - r * 0.7))


class RodItem(_Selectable, QGraphicsEllipseItem):
    """拉杆 / 自由拉杆（正式程序 red filled circle）。"""

    item_kind = "rod"

    def __init__(self, center, radius, controller=None, free=False):
        cx, cy = float(center[0]), -float(center[1])
        rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        super().__init__(rect)
        self.center = (float(center[0]), float(center[1]))
        self.radius = float(radius)
        self.free = bool(free)
        self.item_kind = "free_rod" if free else "rod"
        color = SIDE_ROD_COLOR if free else ROD_COLOR
        self.base_pen = QPen(color)
        self.base_pen.setWidthF(1.2)
        self.base_brush = QBrush(color)
        self.setBrush(self.base_brush)
        self.setPen(self.base_pen)
        self.setZValue(6)
        self._init_selectable(controller)
        self.setToolTip(("自由拉杆" if free else "拉杆") + f" ({self.center[0]:.1f}, {self.center[1]:.1f})")

    def paint(self, painter, option, widget=None):  # noqa: N802 - Qt API
        if self.is_selected:
            pen = QPen(SELECTED_PEN_COLOR)
            pen.setWidthF(2.4)
            painter.setPen(pen)
            painter.setBrush(QBrush(SELECTED_FILL))
        else:
            painter.setPen(self.base_pen)
            painter.setBrush(self.base_brush)
        painter.drawEllipse(self.rect())


class BlockTubeItem(RodItem):
    """中间挡管（正式程序灰色小圆，可由中间挡管按钮再次放置恢复）。"""

    def __init__(self, center, radius, controller=None):
        super().__init__(center, radius, controller, free=False)
        self.item_kind = "block_tube"
        pen = QPen(BLOCK_TUBE_COLOR)
        pen.setWidthF(1.2)
        self.base_pen = pen
        self.base_brush = QBrush(BLOCK_TUBE_COLOR)
        self.setPen(pen)
        self.setBrush(self.base_brush)
        self.setToolTip(f"中间挡管 ({self.center[0]:.1f}, {self.center[1]:.1f})")


class ComponentRectItem(_Selectable, QGraphicsRectItem):
    """矩形类元件：旁路挡板、中间挡板、防冲板、滑道。"""

    def __init__(self, rect, controller=None, kind="component", label="元件", color=None):
        super().__init__(rect)
        self.item_kind = kind
        self.label = label
        color = color or BYPASS_COLOR
        self.base_pen = QPen(color)
        self.base_pen.setWidthF(1.4)
        fill = QColor(color)
        fill.setAlpha(90)
        self.base_brush = QBrush(fill)
        self.setPen(self.base_pen)
        self.setBrush(self.base_brush)
        # 元件画在轴线（z=15）之上、壳体圆（z=20）之下，避免被坐标轴盖住
        self.setZValue(16)
        self._init_selectable(controller)
        center = rect.center()
        self.center = (float(center.x()), float(center.y()))
        self.setToolTip(f"{label} 中心({self.center[0]:.1f}, {self.center[1]:.1f})")

    def paint(self, painter, option, widget=None):  # noqa: N802 - Qt API
        if self.is_selected:
            pen = QPen(SELECTED_PEN_COLOR)
            pen.setWidthF(2.4)
            painter.setPen(pen)
            painter.setBrush(QBrush(SELECTED_FILL))
        else:
            painter.setPen(self.base_pen)
            painter.setBrush(self.base_brush)
        painter.drawRect(self.rect())


class SlideItem(ComponentRectItem):
    """滑道（绿）：正式程序按 滑道高度/厚度/夹角/方位角 绘制。"""

    def __init__(self, rect, controller=None):
        super().__init__(rect, controller, kind="slide", label="滑道", color=SLIDE_COLOR)


class FoldedPlateItem(_Selectable, QGraphicsPathItem):
    """防冲板（圆弧形 / 焊接式）：A-P-Q-B 折边轮廓，线宽 = 防冲板厚度。

    正式程序用 `QPainterPath` + 宽度 = 板厚的 pen 画这条折线（不填充），
    这里保持一致，因此图形上看到的是“有厚度的折边板”而不是一个矩形。
    """

    def __init__(self, path, controller=None, kind="impingement_folded", label="防冲板",
                 thickness=10.0, color=None):
        super().__init__(path)
        self.item_kind = kind
        self.label = label
        self.thickness = float(thickness or 1.0)
        color = color or IMPINGE_PEN_COLOR
        pen = QPen(color)
        pen.setWidthF(max(self.thickness, 1.0))
        pen.setCapStyle(Qt.FlatCap)
        pen.setJoinStyle(Qt.MiterJoin)
        self.base_pen = pen
        self.setPen(pen)
        self.setBrush(QBrush(Qt.NoBrush))
        # 与矩形类元件一致：盖住坐标轴（z=15）、在壳体圆（z=20）之下
        self.setZValue(16)
        self._init_selectable(controller)
        box = path.boundingRect()
        self.center = (float(box.center().x()), float(box.center().y()))
        self.setToolTip(f"{label}（轮廓线宽 = 板厚 {self.thickness:g} mm）")

    def paint(self, painter, option, widget=None):  # noqa: N802 - Qt API
        if self.is_selected:
            pen = QPen(SELECTED_PEN_COLOR)
            pen.setWidthF(max(self.thickness, 1.0) + 2.0)
            pen.setCapStyle(Qt.FlatCap)
            painter.setPen(pen)
            painter.setBrush(QBrush(Qt.NoBrush))
        else:
            painter.setPen(self.base_pen)
            painter.setBrush(QBrush(Qt.NoBrush))
        painter.drawPath(self.path())


class RadialHoleItem(_Selectable, QGraphicsPathItem):
    """径向开孔：沿半径方向的切线开口（正式程序 ClickableRadialHoleItem 同色）。"""

    item_kind = "radial_hole"

    def __init__(self, path, controller=None):
        super().__init__(path)
        self.setBrush(QBrush(QColor(160, 160, 160, 160)))
        self.setPen(QPen(Qt.NoPen))
        self.setZValue(30)
        self._init_selectable(controller)
        self.setToolTip("径向开孔")
