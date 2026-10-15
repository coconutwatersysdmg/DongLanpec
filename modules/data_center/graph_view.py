from __future__ import annotations

import math

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PyQt5.QtWidgets import QGraphicsItem, QGraphicsObject, QGraphicsPathItem, QGraphicsScene, QGraphicsView

from .models import ACTIVITY_DB, CellRef, display


def pixel_font(size, bold=False):
    font = QFont('Microsoft YaHei UI')
    font.setPixelSize(size)
    font.setBold(bold)
    return font


class FieldNode(QGraphicsObject):
    WIDTH, HEIGHT = 290, 136

    def __init__(self, ref, value, row, focus=False):
        super().__init__()
        self.ref, self.value, self.row, self.focus = ref, value, row, focus
        self.links = []
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges)
        self.concrete = isinstance(ref, CellRef)
        self.writable = self.concrete and ref.column not in dict(ref.keys)
        self.setToolTip(ref.label + '\n' + ('当前值：' + display(value) +
                       ('\n拖动右侧圆点建立取值链路；双击编辑字段。' if self.writable else '\n记录定位标识：可查看来源，不能直接改值或改绑。')
                       if self.concrete else ref.detail[:2500]))
        self.setCursor(Qt.OpenHandCursor)

    def boundingRect(self):
        return QRectF(-8, -6, self.WIDTH + 16, self.HEIGHT + 12)

    def paint(self, p, option, widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        accent = QColor(('#7c3aed' if self.ref.database == ACTIVITY_DB else '#2563eb') if self.concrete else
                        {'input': '#16865c', 'table': '#7c3aed'}.get(self.ref.kind, '#147f8b'))
        p.setPen(QPen(accent if self.isSelected() or self.focus else QColor('#d5deeb'), 2 if self.isSelected() or self.focus else 1))
        p.setBrush(QColor('#ffffff'))
        p.drawRoundedRect(QRectF(0, 0, self.WIDTH, self.HEIGHT), 10, 10)
        p.setPen(Qt.NoPen)
        p.setBrush(accent)
        p.drawRoundedRect(QRectF(12, 13, 5, 19), 2, 2)
        p.setPen(accent)
        p.setFont(pixel_font(12))
        self._text(p, 25, 13, self.ref.database + ((' · 过程数据' if self.ref.database == ACTIVITY_DB else ' · 取值依赖') if self.concrete else ''))
        p.setPen(QColor('#64748b'))
        p.setFont(pixel_font(11))
        context = self.row.get('元件名称') or self.row.get('管口代号') or self.row.get('类别') or ''
        self._text(p, 14, 37, self.ref.table.removeprefix('产品设计活动表_') + (' · ' + str(context) if context else ''))
        p.setFont(pixel_font(14, True))
        p.setPen(QColor('#17243d'))
        name = self.row.get('参数名称') or self.row.get('参数名') or self.row.get('Name') or ''
        self._text(p, 14, 60, (str(name) + ' · ' if name else '') + self.ref.column)
        p.setFont(pixel_font(16, True))
        self._text(p, 14, 86, display(self.value))
        p.setFont(pixel_font(10))
        p.setPen(QColor('#718096'))
        identity = ' · '.join('%s=%s' % (k, display(v)) for k, v in self.ref.keys)
        self._text(p, 14, 111, identity)
        p.setBrush(accent)
        p.setPen(QPen(QColor('white'), 2))
        if self.writable:
            p.drawEllipse(QPointF(0, self.HEIGHT / 2), 5, 5)
            p.drawEllipse(QPointF(self.WIDTH, self.HEIGHT / 2), 6, 6)

    def _text(self, painter, x, y, text):
        text = str(text).replace('\n', ' ')
        text = painter.fontMetrics().elidedText(text, Qt.ElideRight, self.WIDTH - x - 14)
        painter.drawText(QRectF(x, y, self.WIDTH - x - 14, 21), Qt.AlignLeft | Qt.AlignVCenter, text)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            for link in self.links:
                link.update_path()
        return super().itemChange(change, value)


class FieldEdge(QGraphicsPathItem):
    def __init__(self, source, target, edge):
        super().__init__()
        self.source, self.target, self.edge = source, target, edge
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setZValue(-1)
        self.provenance = getattr(edge, 'kind', '') == 'provenance'
        self.setToolTip(('代码依据 · 只读关系\n' if self.provenance else '候选来源，尚未联动\n' if edge.candidate else '已绑定 · 直接取值\n') + edge.evidence[:2500])
        source.links.append(self)
        target.links.append(self)
        self.update_path()

    def update_path(self):
        start = self.source.mapToScene(QPointF(self.source.WIDTH, self.source.HEIGHT / 2))
        end = self.target.mapToScene(QPointF(0, self.target.HEIGHT / 2))
        path = QPainterPath(start)
        distance = max(65, abs(end.x() - start.x()) * .48)
        path.cubicTo(start + QPointF(distance, 0), end - QPointF(distance, 0), end)
        self.setPath(path)

    def paint(self, painter, option, widget=None):
        color = QColor('#2695a0' if self.provenance else '#e29528' if self.edge.candidate else '#437de2')
        if self.isSelected():
            color = QColor('#e44c65')
        self.setPen(QPen(color, 2.2, Qt.DotLine if self.provenance else Qt.DashLine if self.edge.candidate else Qt.SolidLine))
        super().paint(painter, option, widget)
        path = self.path()
        end, near = path.pointAtPercent(.995), path.pointAtPercent(.96)
        angle = math.atan2(end.y() - near.y(), end.x() - near.x())
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(QPolygonF([end,
            end - QPointF(math.cos(angle - .45) * 12, math.sin(angle - .45) * 12),
            end - QPointF(math.cos(angle + .45) * 12, math.sin(angle + .45) * 12)]))


class LineageView(QGraphicsView):
    field_selected = pyqtSignal(object)
    field_edit = pyqtSignal(object)
    edge_selected = pyqtSignal(object)
    link_requested = pyqtSignal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setBackgroundBrush(QColor('#f4f7fb'))
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.nodes = {}
        self.connect_mode = False
        self._source = None
        self._rubber = None
        self.scene().selectionChanged.connect(self._selected)

    def _selected(self):
        for item in self.scene().selectedItems():
            if isinstance(item, FieldNode):
                self.field_selected.emit(item.ref)
                break
            if isinstance(item, FieldEdge):
                self.edge_selected.emit(item.edge)
                break

    def clear_graph(self):
        self._source = self._rubber = None
        self.scene().clear()
        self.nodes = {}

    def show_graph(self, graph, column_spacing=400):
        self.clear_graph()
        levels = {graph.focus: 0}
        # Assign a deterministic upstream/focus/downstream layout even when candidates fan out.
        for _ in range(len(graph.values)):
            changed = False
            for edge in graph.edges:
                if edge.source in levels and edge.target not in levels:
                    levels[edge.target] = levels[edge.source] + 1
                    changed = True
                elif edge.target in levels and edge.source not in levels:
                    levels[edge.source] = levels[edge.target] - 1
                    changed = True
            if not changed:
                break
        groups = {}
        for ref in graph.values:
            groups.setdefault(levels.get(ref, 0), []).append(ref)
        for level, refs in groups.items():
            refs.sort(key=lambda r: r.label)
            for index, ref in enumerate(refs):
                node = FieldNode(ref, graph.values[ref], graph.rows.get(ref, {}), ref == graph.focus)
                node.setPos(level * column_spacing, (index - (len(refs) - 1) / 2) * 174)
                self.scene().addItem(node)
                self.nodes[ref] = node
        for edge in graph.edges:
            if edge.source in self.nodes and edge.target in self.nodes:
                self.scene().addItem(FieldEdge(self.nodes[edge.source], self.nodes[edge.target], edge))
        self.scene().setSceneRect(self.scene().itemsBoundingRect().adjusted(-120, -100, 120, 100))
        self.fit_graph()
        if graph.focus in self.nodes:
            self.nodes[graph.focus].setSelected(True)

    def fit_graph(self):
        self.resetTransform()
        bounds = self.scene().itemsBoundingRect().adjusted(-35, -35, 35, 35)
        if not bounds.isEmpty():
            self.fitInView(bounds, Qt.KeepAspectRatio)
            if self.transform().m11() > 1.15:
                self.resetTransform()
                self.scale(1.15, 1.15)
            elif self.transform().m11() < .55:
                self.resetTransform()
                self.scale(.75, .75)
                focus = next((n for n in self.nodes.values() if n.focus), None)
                if focus:
                    self.centerOn(focus)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        scale = self.transform().m11() * factor
        if .12 <= scale <= 2.8:
            self.scale(factor, factor)
        event.accept()

    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        if event.button() == Qt.LeftButton and isinstance(item, FieldNode):
            local = item.mapFromScene(self.mapToScene(event.pos()))
            at_port = abs(local.x() - item.WIDTH) < 16 and abs(local.y() - item.HEIGHT / 2) < 18
            if item.writable and (self.connect_mode or at_port):
                self._source = item
                self._rubber = self.scene().addPath(QPainterPath(), QPen(QColor('#2563eb'), 2, Qt.DashLine))
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._source is not None:
            path = QPainterPath(self._source.mapToScene(QPointF(self._source.WIDTH, self._source.HEIGHT / 2)))
            path.lineTo(self.mapToScene(event.pos()))
            self._rubber.setPath(path)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._source is not None:
            source = self._source.ref
            if self._rubber:
                self.scene().removeItem(self._rubber)
            target = self.itemAt(event.pos())
            self._source = self._rubber = None
            if isinstance(target, FieldNode) and target.writable and target.ref != source:
                self.link_requested.emit(source, target.ref)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.pos())
        if isinstance(item, FieldNode):
            self.field_edit.emit(item.ref)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
