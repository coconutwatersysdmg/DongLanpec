"""布管图形项：从正式程序 My_Piping.py 的图形类抽取。

对应关系（正式程序 -> 本文件）：
    ClickableCircleItem      -> TubeItem / RodItem / BlockTubeItem
    ClickableRectItem        -> ComponentRectItem（旁路挡板、中间挡板、防冲板、滑道）
    ClickableRadialHoleItem  -> RadialHoleItem

【选中样式严格分成两套，完全照正式程序，不要合并】（用户 2026-11-22 反馈）
  1) 换热管 / 已删除管孔 / 普通拉杆：选中 = 淡蓝实心圆，无金色边框。
     正式程序 `My_Piping._add_abs_selection_marker`(24665)：
         pen = QPen(Qt.NoPen); brush = QBrush(QColor(173, 216, 230))
     普通拉杆 `ClickableCircleItem.mousePressEvent`(1014) 选中直接画在拉杆上，
     也是淡蓝实心（不叠金边）。
  2) 元件（防冲板 / 旁路挡板 / 滑道 / 中间挡板 / 中间挡管 / 吊环螺钉）：
     选中 = 仅把边框换成金色 `QPen(QColor(255,215,0), 3, ...)`，**填充保持原样**。
     正式程序 `ClickableRectItem.mousePressEvent`(742) 只 `setPen(selected_pen)`，
     从不改 brush —— 所以选一个防冲板只描金边，不会把一片圆涂成金色。
"""
from __future__ import annotations

import math

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QPainterPath, QPen
from PyQt5.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsEllipseItem, QGraphicsRectItem

# 元件颜色/画法严格对齐正式程序（DongLanpec/modules/buguan/buguan_ziyong/component/）：
#   拉杆 lagan.py / free_lagan.py       -> Qt.red 实心, pen width 2(自由拉杆 1), z=20
#   中间挡管 center_dangguan.py         -> QColor(128,0,128) 紫色空心圆, pen width 3, z=10
#   旁路挡板 side_dangban.py            -> Qt.blue 实心矩形 (显示高度=厚度*3), z=10
#   中间挡板 center_dangban.py          -> QColor(128,0,128) 紫色实心多边形, z=10
#   滑道 slipway.py                     -> QColor(0,100,0) 深绿实心无边框 (板式多边形/圆钢圆), z=20
#   防冲板 impingement_plate.py         -> QColor(0,0,139) 深蓝单线不填充, pen width=板厚
TUBE_PEN_COLOR = QColor(0, 0, 80)          # 换热管 / 已删除管孔：深蓝空心（正式程序 draw_layout 22383、build_huanreguan 33877）
ROD_COLOR = QColor(255, 0, 0)              # 拉杆：Qt.red 实心（lagan.py）
SIDE_ROD_COLOR = QColor(255, 0, 0)         # 自由拉杆：也是 Qt.red（free_lagan.py）
BLOCK_TUBE_COLOR = QColor(128, 0, 128)     # 中间挡管：紫色空心圆（center_dangguan.py）
CENTER_BAFFLE_COLOR = QColor(128, 0, 128)  # 中间挡板：紫色实心（center_dangban.py）
BYPASS_COLOR = QColor(0, 0, 255)           # 旁路挡板：Qt.blue 实心（side_dangban.py）
SLIDE_COLOR = QColor(0, 100, 0)            # 滑道：深绿实心无边框（slipway.py）
IMPINGE_COLOR = QColor(70, 110, 180)       # 防冲板：蓝灰
IMPINGE_PEN_COLOR = QColor(0, 0, 139)      # 防冲板轮廓线：深蓝（正式程序 QColor(0,0,139)）
SELECTED_PEN_COLOR = QColor(255, 215, 0)   # 仅元件选中描金边用
SELECTED_FILL = QBrush(QColor(173, 216, 230))  # 仅管类选中淡蓝实心用


def _paint_circle_selected(painter, rect) -> None:
    """管类（换热管/已删管孔/普通拉杆）选中：淡蓝实心圆，无金色边框。"""
    painter.setPen(QPen(Qt.NoPen))
    painter.setBrush(SELECTED_FILL)
    painter.drawEllipse(rect)


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
            # 正式程序 _add_abs_selection_marker：淡蓝实心圆，无金边
            _paint_circle_selected(painter, self.rect())
        else:
            painter.setPen(self.base_pen)
            painter.setBrush(QBrush(Qt.NoBrush))
            painter.drawEllipse(self.rect())


class GhostTubeItem(TubeItem):
    """已被删除的换热管孔：照正式程序 delete_centers（My_Piping.py:19104）
    用**白色实心圆**（QPen/QBrush 都是 QColor(255,255,255)、pen 宽 3）把孔盖掉，
    看起来这里就没有管孔——正式程序从不画"已删管"的标记圆，用户明确要求一致。
    仍可点选恢复，选中时同管类 = 淡蓝实心圆、无金边。
    """

    item_kind = "tube"

    def __init__(self, center, radius, controller=None):
        super().__init__(center, radius, controller)
        pen = QPen(QColor(255, 255, 255))   # 源程序白色 pen
        pen.setWidthF(3.0)                   # 源程序 delete_centers 宽 3
        self.base_pen = pen
        self.base_brush = QBrush(QColor(255, 255, 255))  # 白色实心覆盖
        # 必须盖在圆心连线(z=0.5)之上，否则蓝色×穿过白圆，删掉的孔还能看见连线。
        self.setZValue(1.0)
        self.setToolTip(
            f"已删除的换热管孔 ({self.center[0]:.2f}, {self.center[1]:.2f})，点一下可选中恢复"
        )

    def paint(self, painter, option, widget=None):  # noqa: N802 - Qt API
        if self.is_selected:
            _paint_circle_selected(painter, self.rect())
        else:
            painter.setPen(self.base_pen)
            painter.setBrush(self.base_brush)
            painter.drawEllipse(self.rect())


class RodItem(_Selectable, QGraphicsEllipseItem):
    """拉杆 / 自由拉杆（正式程序 red filled circle）。选中按管类：淡蓝实心、无金边。"""

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
        # 正式程序：普通拉杆 pen width=2（lagan.py:114），自由拉杆 width=1（free_lagan.py:288）
        self.base_pen.setWidthF(1.0 if free else 2.0)
        self.base_brush = QBrush(color)
        self.setBrush(self.base_brush)
        self.setPen(self.base_pen)
        self.setZValue(20)
        self._init_selectable(controller)
        self.setToolTip(("自由拉杆" if free else "拉杆") + f" ({self.center[0]:.1f}, {self.center[1]:.1f})")

    def paint(self, painter, option, widget=None):  # noqa: N802 - Qt API
        if self.is_selected:
            # 正式程序普通拉杆选中：淡蓝实心（直接画在拉杆本体上，无金边）
            _paint_circle_selected(painter, self.rect())
        else:
            painter.setPen(self.base_pen)
            painter.setBrush(self.base_brush)
            painter.drawEllipse(self.rect())


class BlockTubeItem(RodItem):
    """中间挡管：正式程序 center_dangguan.py:164-183 = 紫色空心圆，pen width=3，NoBrush，z=10。

    属于"元件"，选中只描金边、填充保持空心（不涂淡蓝）。
    """

    def __init__(self, center, radius, controller=None):
        super().__init__(center, radius, controller, free=False)
        self.item_kind = "block_tube"
        pen = QPen(BLOCK_TUBE_COLOR)       # QColor(128,0,128) 紫
        pen.setWidthF(3.0)                 # 正式程序 width=3
        self.base_pen = pen
        self.base_brush = QBrush(Qt.NoBrush)   # 空心，不填充
        self.setPen(pen)
        self.setBrush(self.base_brush)
        self.setZValue(10)
        self.setToolTip(f"中间挡管 ({self.center[0]:.1f}, {self.center[1]:.1f})")

    def paint(self, painter, option, widget=None):  # noqa: N802 - Qt API
        if self.is_selected:
            pen = QPen(SELECTED_PEN_COLOR)   # 元件选中：仅金色边框
            pen.setWidthF(3.6)
            painter.setPen(pen)
            painter.setBrush(QBrush(Qt.NoBrush))   # 保持空心，不涂淡蓝
        else:
            painter.setPen(self.base_pen)
            painter.setBrush(QBrush(Qt.NoBrush))
        painter.drawEllipse(self.rect())


class ComponentRectItem(_Selectable, QGraphicsRectItem):
    """矩形类元件：旁路挡板、中间挡板、防冲板、滑道。

    选中只描金色边框，填充保持原样——正式程序 ClickableRectItem 选中从不改 brush，
    否则选一个防冲板会把整片圆涂成金色（用户 2026-11-22 明确反馈不对）。
    """

    def __init__(self, rect, controller=None, kind="component", label="元件", color=None):
        super().__init__(rect)
        self.item_kind = kind
        self.label = label
        color = color or BYPASS_COLOR
        self.base_pen = QPen(color)
        self.base_pen.setWidthF(1.4)

        # 严格对齐正式程序各元件的填充：
        # · 旁路挡板 side_dangban.py:1085-1120 —— Qt.blue 实心矩形
        # · 中间挡板 center_dangban.py:1164-1209 —— QColor(128,0,128) 紫色实心
        # · 滑道 slipway.py:1522-1526 —— 深绿实心 + NoPen 无边框
        if kind == "slide":
            self.base_pen = QPen(Qt.NoPen)
            self.base_brush = QBrush(QColor(color))       # 深绿实心
            z = 20
        elif kind == "bypass":
            self.base_brush = QBrush(QColor(color))       # 蓝实心
            z = 10
        elif kind == "center_baffle":
            self.base_brush = QBrush(QColor(color))       # 紫实心
            z = 10
        else:
            fill = QColor(color)
            fill.setAlpha(90)
            self.base_brush = QBrush(fill)                # 其他（防冲板等）保持半透明
            z = 16
        self.setPen(self.base_pen)
        self.setBrush(self.base_brush)
        self.setZValue(z)
        self._init_selectable(controller)
        center = rect.center()
        self.center = (float(center.x()), float(center.y()))
        self.setToolTip(f"{label} 中心({self.center[0]:.1f}, {self.center[1]:.1f})")

    def paint(self, painter, option, widget=None):  # noqa: N802 - Qt API
        if self.is_selected:
            pen = QPen(SELECTED_PEN_COLOR)   # 仅描金边
            pen.setWidthF(3)
            painter.setPen(pen)
            painter.setBrush(self.base_brush)   # 填充保持不变
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
    这里保持一致。选中只把折线描成金色，不改填充（本来就 NoBrush）。
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
        # 先画防冲板本体（深蓝、宽 = 板厚），选中时也要保留，不能被选中色整条替换：
        # 用户 2026-11-22 反馈"选中一个防冲板变成全部涂成金色"就是本体被顶掉导致的。
        painter.setPen(self.base_pen)
        painter.setBrush(QBrush(Qt.NoBrush))
        painter.drawPath(self.path())
        if self.is_selected:
            # 正式程序 selected_pen = QPen(QColor(255,215,0), 3, SolidLine, RoundCap, RoundJoin)：
            # 叠加在原件之上的**固定 3px 细金线**选中标记，而不是把板厚宽的本体换成金色。
            pen = QPen(SELECTED_PEN_COLOR)
            pen.setWidthF(3.0)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(QBrush(Qt.NoBrush))
            painter.drawPath(self.path())


class RadialHoleItem(_Selectable, QGraphicsPathItem):
    """径向开孔：沿半径方向的切线开口（正式程序 ClickableRadialHoleItem 选中=金色边框，透明填充）。"""

    item_kind = "radial_hole"

    def __init__(self, path, controller=None):
        super().__init__(path)
        self.setBrush(QBrush(QColor(160, 160, 160, 160)))
        self.setPen(QPen(Qt.NoPen))
        self.setZValue(30)
        self._init_selectable(controller)
        self.setToolTip("径向开孔")

    def paint(self, painter, option, widget=None):  # noqa: N802 - Qt API
        if self.is_selected:
            pen = QPen(SELECTED_PEN_COLOR)
            pen.setWidthF(3)
            painter.setPen(pen)
            painter.setBrush(QBrush(Qt.NoBrush))
        else:
            painter.setPen(QPen(Qt.NoPen))
            painter.setBrush(QBrush(QColor(160, 160, 160, 160)))
        painter.drawPath(self.path())


class ScrewRingItem(_Selectable, QGraphicsEllipseItem):
    """吊环螺钉：源程序 screw_ring.py:1552-1611 = 蓝色空心圆 + 圆内 3 横 3 竖井字弦。

    属于元件，选中只描金边、填充保持空心。
    """

    item_kind = "screw_ring"
    COLOR = QColor(0, 102, 204)

    def __init__(self, center, radius, controller=None):
        cx, cy = float(center[0]), -float(center[1])
        super().__init__(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
        self.center = (float(center[0]), float(center[1]))
        self.radius = float(radius)
        self.base_pen = QPen(self.COLOR)
        self.base_pen.setWidthF(2.0)
        self.setPen(self.base_pen)
        self.setBrush(QBrush(Qt.NoBrush))
        self.setZValue(5)
        self._init_selectable(controller)
        self.setToolTip(f"吊环螺钉 ({self.center[0]:.1f}, {self.center[1]:.1f})")

    def paint(self, painter, option, widget=None):  # noqa: N802 - Qt API
        pen = QPen(SELECTED_PEN_COLOR) if self.is_selected else QPen(self.base_pen)
        pen.setWidthF(3 if self.is_selected else 2.0)
        painter.setPen(pen)
        painter.setBrush(QBrush(Qt.NoBrush))
        rect = self.rect()
        painter.drawEllipse(rect)
        # 圆内 3 横 3 竖弦（源程序 screw_ring.py）
        chord_pen = QPen(pen)
        chord_pen.setWidthF(1.0)
        painter.setPen(chord_pen)
        cx, cy = rect.center().x(), rect.center().y()
        r = self.radius
        for f in (-0.5, 0.0, 0.5):
            dy = math.sqrt(max(r * r - (f * r) ** 2, 0.0)) if f else r
            painter.drawLine(QPointF(cx - f * r, cy - dy), QPointF(cx - f * r, cy + dy))
            painter.drawLine(QPointF(cx - dy, cy - f * r), QPointF(cx + dy, cy - f * r))
