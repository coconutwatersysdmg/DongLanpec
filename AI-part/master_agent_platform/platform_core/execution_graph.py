"""Movable, persistent product trees with recorded task and review edges."""
import hashlib
import json
import math
import sqlite3
import threading

from PyQt5.QtCore import Qt, QPointF, QTimer, QSaveFile, QIODevice, QLockFile
from PyQt5.QtGui import QColor, QBrush, QPen, QFont, QFontMetrics, QPainter, QPainterPath, QPolygonF
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QGraphicsScene, QGraphicsView, QGraphicsRectItem, QGraphicsTextItem, QGraphicsPathItem,
    QGraphicsPolygonItem, QGraphicsSimpleTextItem, QSplitter, QPlainTextEdit, QTreeWidget,
    QTreeWidgetItem, QCheckBox)

from .fabric import Fabric
from .graph_model import execution_graph, review_cycles
from .run_view import duration
from .ui_theme import FlowLayout

COLORS = {"running": ("#eff6ff", "#2563eb"), "failed": ("#fff1f2", "#e11d48"),
          "processing_failed": ("#fff1f2", "#e11d48"), "cancelled": ("#f1f5f9", "#64748b"),
          "needs_manual_review": ("#fffbeb", "#d97706")}
STATES = {"running": "运行中", "failed": "失败", "processing_failed": "失败", "cancelled": "已停止",
          "succeeded": "完成", "reviewed": "已复核", "reviewed_with_deferred": "有暂缓项", "needs_manual_review": "待审核"}
_LAYOUT_WRITE_LOCK = threading.Lock()


def write_layout(path, value):
    # Wait for local writers without holding the GIL inside QLockFile.tryLock.
    with _LAYOUT_WRITE_LOCK:
        _write_layout(path, value)


def _write_layout(path, value):
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(path)+".lock")
    if not lock.tryLock(500): raise OSError("布局文件正被其它窗口使用或目录不可写，请稍后重试。")
    try:
        data = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
        target = QSaveFile(str(path))
        if not target.open(QIODevice.WriteOnly): raise OSError(target.errorString())
        if target.write(data) != len(data):
            error = target.errorString()
            target.cancelWriting()
            raise OSError(error)
        if not target.commit(): raise OSError(target.errorString())
    finally: lock.unlock()


class GraphNode(QGraphicsRectItem):
    def __init__(self, owner, data):
        scale = owner.ui_scale
        super().__init__(0, 0, 260*scale, 142*scale)
        self.owner, self.record = owner, data
        fill, line = COLORS.get(data.get("state"), ("#f0fdf9", "#34a68a"))
        if data['kind'] == 'run': fill, line = '#eef1ff', '#7180e9'
        elif data['kind'] == 'product': fill, line = '#eff7ff', '#7ba4d2'
        if data["kind"] in ("cycle", "review-stage"): fill, line = "#faf5ff", "#a879ce"
        self.setBrush(QBrush(QColor(fill)))
        self.setPen(QPen(QColor(line), 1.25))
        self.setFlags(self.ItemIsMovable | self.ItemIsSelectable | self.ItemSendsGeometryChanges)
        self.setData(0, data["id"])
        self.setToolTip(data["title"]+'\n执行者：'+data.get('executor_label', '')+'\n调度：'+data.get('controller', '')
            +"\n拖动调整位置"+("；双击展开或折叠" if data["children"] else ""))
        font = QFont("Microsoft YaHei")
        font.setPixelSize(round(17*scale))
        font.setBold(True)
        title = QGraphicsTextItem(QFontMetrics(font).elidedText(data["title"], Qt.ElideRight, round(236*scale)), self)
        title.setFont(font)
        title.setDefaultTextColor(QColor("#173455"))
        title.setPos(10*scale, 6*scale)
        font = QFont("Microsoft YaHei")
        font.setPixelSize(round(14*scale))
        agent = QGraphicsTextItem(QFontMetrics(font).elidedText(data.get('executor_label', ''), Qt.ElideRight, round(236*scale)), self)
        agent.setFont(font)
        agent.setDefaultTextColor(QColor('#6366c9'))
        agent.setPos(10*scale, 37*scale)
        body = QGraphicsTextItem(data.get("body", ""), self)
        body.setFont(font)
        body.setTextWidth(236*scale)
        body.setDefaultTextColor(QColor("#52627a"))
        body.setPos(10*scale, 67*scale)
        text = STATES.get(data.get("state"), "已记录")
        if "duration_seconds" in data: text += " · "+duration(data.get("duration_seconds"))
        elif data["children"]: text += " · "+("− 折叠" if data["id"] in owner.expanded else "+ 展开")
        footer = QGraphicsTextItem(text, self)
        footer.setFont(font)
        footer.setDefaultTextColor(QColor("#60738b"))
        footer.setPos(10*scale, 108*scale)
        for item in (title, agent, body, footer): item.setAcceptedMouseButtons(Qt.NoButton)

    def paint(self, painter, option, widget=None):
        painter.setBrush(self.brush())
        pen = QPen(self.pen())
        if self.isSelected(): pen.setWidthF(2.4)
        painter.setPen(pen)
        painter.drawRoundedRect(self.rect(), 10*self.owner.ui_scale, 10*self.owner.ui_scale)

    def itemChange(self, change, value):
        if change == self.ItemPositionHasChanged and hasattr(self, "owner"):
            self.owner.node_moved(self.record["id"], self.pos())
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        if self.record["children"]:
            self.owner.queue_toggle(self.record["id"])
            event.accept()
        else: super().mouseDoubleClickEvent(event)


class GraphEdge(QGraphicsPathItem):
    def __init__(self, source, target, data):
        super().__init__()
        self.source, self.target, self.record = source, target, data
        self.setZValue(-2)
        self.setAcceptedMouseButtons(Qt.NoButton)
        kind = data["kind"]
        color = "#a77ac7" if kind in ("feedback", "review-input") else "#a9b5c7" if kind in ("execution", "legacy") else "#8daed4"
        pen = QPen(QColor(color), 1.7 if kind == "feedback" else 1.15)
        if kind in ("feedback", "legacy"): pen.setStyle(Qt.DashLine)
        self.setPen(pen)
        self.arrow = QGraphicsPolygonItem(self)
        self.arrow.setAcceptedMouseButtons(Qt.NoButton)
        self.arrow.setPen(QPen(QColor(color)))
        self.arrow.setBrush(QBrush(QColor(color)))
        self.label = QGraphicsSimpleTextItem(data.get("label", ""), self)
        self.label.setAcceptedMouseButtons(Qt.NoButton)
        font = QFont("Microsoft YaHei")
        font.setPixelSize(round(13*source.owner.ui_scale))
        self.label.setFont(font)
        self.label.setBrush(QBrush(QColor(color)))
        self.update_path()

    def update_path(self):
        a, b = self.source.pos(), self.target.pos()
        width, height = self.source.rect().width(), self.source.rect().height()
        target_width, target_height = self.target.rect().width(), self.target.rect().height()
        start, end = a+QPointF(width, height/2), b+QPointF(0, target_height/2)
        path = QPainterPath(start)
        kind = self.record["kind"]
        if kind == "feedback":
            start, end = a+QPointF(width, height*.75), b+QPointF(target_width, target_height*.75)
            path = QPainterPath(start)
            right = max(a.x()+width, b.x()+target_width)+100
            path.cubicTo(QPointF(right, start.y()), QPointF(right, end.y()), end)
        elif abs(a.x()-b.x()) < 20:
            if kind == "hierarchy":
                start, end = a+QPointF(0, height*.76), b+QPointF(0, target_height*.28)
                path = QPainterPath(start)
                path.cubicTo(start-QPointF(30, 0), end-QPointF(30, 0), end)
            else:
                end = b+QPointF(target_width, target_height*.35)
                path.cubicTo(start+QPointF(45, 0), end+QPointF(45, 0), end)
        else:
            middle = (start.x()+end.x())/2
            path.lineTo(middle, start.y())
            path.lineTo(middle, end.y())
            path.lineTo(end)
        self.setPath(path)
        previous = path.pointAtPercent(.985)
        direction = math.atan2(end.y()-previous.y(), end.x()-previous.x())
        left = end-QPointF(8*math.cos(direction-.45), 8*math.sin(direction-.45))
        right = end-QPointF(8*math.cos(direction+.45), 8*math.sin(direction+.45))
        self.arrow.setPolygon(QPolygonF([end, left, right]))
        middle = path.pointAtPercent(.5)
        self.label.setPos(middle+QPointF(5, -17))


class GraphView(QGraphicsView):
    def __init__(self, scene, owner):
        super().__init__(scene)
        self.owner = owner

    def mousePressEvent(self, event):
        self.owner.dragging = True
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.owner.dragging = True
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        try: super().mouseReleaseEvent(event)
        finally:
            self.owner.dragging = False
            self.owner.queue_update(refresh=True)

    def hideEvent(self, event):
        active = self.owner.dragging
        self.owner.dragging = False
        if active: self.owner.queue_update()
        super().hideEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self.scale(1.15 if event.angleDelta().y() > 0 else 1/1.15, 1.15 if event.angleDelta().y() > 0 else 1/1.15)
            self.owner.update_zoom()
            event.accept()
        else: super().wheelEvent(event)


class ExecutionPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.run_id, self.fabric, self.fingerprint = None, None, None
        self.tasks, self.nodes, self.node_items, self.edges = {}, {}, {}, []
        self.positions, self.expanded = {}, set()
        self.dragging, self.rendering, self.layout_loaded = False, False, False
        self.pending_refresh, self.pending_render = False, False
        self.pending_action, self.pending_toggles = None, []
        self.notice_kind = None
        self.stopped = False
        self.ui_scale = 1.0
        self.value = {}
        layout = QVBoxLayout(self)
        row = FlowLayout()
        self.heading = QLabel("实际执行路径")
        self.heading.setObjectName("sectionTitle")
        row.addWidget(self.heading)
        self.filter = QComboBox()
        self.filter.addItem("全部产品", "")
        self.filter.currentIndexChanged.connect(lambda: self.refresh(True))
        row.addWidget(self.filter)
        self.zoom_label = QLabel('100%')
        row.addWidget(self.zoom_label)
        for text, callback in (("−", lambda: self.zoom(.8)), ("+", lambda: self.zoom(1.25)),
                               ('1:1', self.actual_size), ("适应窗口", self.fit), ("恢复树形", self.restore_tree),
                               ('产品目录', self.toggle_navigator)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        self.timing = QLabel("尚无任务回执")
        layout.addWidget(self.timing)
        options = FlowLayout()
        self.dependencies = QCheckBox("显示调用依赖")
        self.dependencies.toggled.connect(lambda: self.render())
        options.addWidget(self.dependencies)
        for text, callback in (("展开全部", self.expand_all), ("收起产品", self.collapse_products)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            options.addWidget(button)
        self.legend = QLabel("蓝线：分组树　紫线：真实审核回环")
        self.legend.setObjectName("muted")
        options.addWidget(self.legend)
        self.details_toggle = QCheckBox('节点详情')
        self.details_toggle.setToolTip('先选择节点，再展开查看 Agent、任务回执和审核依据')
        self.details_toggle.toggled.connect(lambda visible: self.details.setVisible(visible))
        options.addWidget(self.details_toggle)
        layout.addLayout(options)
        policy = QLabel("当前为有界复核：回查原文 → 默认值与字段校验 → 返回条件数据；保存修改或人工补充后可再次复核。")
        policy.setObjectName("muted")
        policy.setWordWrap(True)
        layout.addWidget(policy)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet("color:#b45309;")
        self.notice.hide()
        layout.addWidget(self.notice)
        split = self.detail_splitter = QSplitter(Qt.Vertical)
        horizontal = self.canvas_splitter = QSplitter(Qt.Horizontal)
        for splitter in (split, horizontal):
            splitter.setHandleWidth(8)
            splitter.setChildrenCollapsible(False)
        self.navigator = QTreeWidget()
        self.navigator.setHeaderLabels(["产品 / 模块"])
        self.navigator.setMinimumWidth(170)
        self.navigator.setMaximumWidth(245)
        self.navigator.itemClicked.connect(self.navigate_item)
        horizontal.addWidget(self.navigator)
        self.scene = QGraphicsScene(self)
        self.scene.selectionChanged.connect(self.selection)
        self.view = GraphView(self.scene, self)
        self.view.setMinimumSize(240, 180)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        self.view.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.view.setBackgroundBrush(QColor("#f8fafc"))
        horizontal.addWidget(self.view)
        horizontal.setSizes([200, 800])
        split.addWidget(horizontal)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("拖动节点可保存布局；双击分组可展开。点击节点查看调用依据、复核轮次和实际耗时。")
        split.addWidget(self.details)
        self.details.setMinimumHeight(75)
        self.details.hide()
        split.setSizes([490, 140])
        layout.addWidget(split, 1)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.flush_layout)
        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.drain_updates)

    def set_ui_scale(self, scale):
        self.ui_scale = scale
        self.render()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'navigator') and not getattr(self, 'navigator_chosen', False):
            self.navigator.setVisible(self.width() >= 1180)

    def toggle_navigator(self):
        self.navigator_chosen = True
        self.navigator.setVisible(self.navigator.isHidden())

    def update_zoom(self):
        self.zoom_label.setText(f'{self.view.transform().m11()*100:.0f}%')

    def zoom(self, factor):
        current = self.view.transform().m11()
        target = max(.25, min(2.5, current*factor))
        self.view.scale(target/current, target/current)
        self.update_zoom()

    def actual_size(self):
        self.view.resetTransform()
        self.update_zoom()

    def queue_update(self, refresh=False):
        if self.stopped: return
        self.pending_refresh |= refresh
        if hasattr(self, "update_timer") and not self.dragging:
            self.update_timer.start(0)

    def queue_toggle(self, identity):
        self.pending_toggles.append(identity)
        self.queue_update()

    def show_notice(self, kind, message):
        self.notice_kind = kind
        self.notice.setText(message)
        self.notice.show()

    def clear_notice(self, kind):
        if self.notice_kind == kind:
            self.notice_kind = None
            self.notice.clear()
            self.notice.hide()

    def drain_updates(self):
        if self.dragging or self.rendering or self.stopped: return
        try: self.apply_updates()
        except (OSError, ValueError, sqlite3.DatabaseError) as exc:
            self.show_notice("refresh", "执行图暂未刷新，已有结果仍保留："+str(exc))

    def apply_updates(self):
        action, self.pending_action = self.pending_action, None
        if action:
            if action[0] == "clear": self.clear()
            else: self.bind(*action[1:])
        toggles, self.pending_toggles = self.pending_toggles, []
        for identity in toggles:
            if identity in self.nodes and self.nodes[identity]["children"]:
                if identity in self.expanded: self.expanded.remove(identity)
                else: self.expanded.add(identity)
                self.pending_render = True
                self.save_timer.start(350)
        refresh, render = self.pending_refresh, self.pending_render
        self.pending_refresh, self.pending_render = False, False
        try:
            if refresh: self.refresh(force=render)
            elif render: self.render()
            self.update_bounds()
            self.clear_notice("refresh")
        except (OSError, ValueError, sqlite3.DatabaseError) as exc:
            self.show_notice("refresh", "执行图暂未刷新，已有结果仍保留："+str(exc))

    def bind(self, workspace, run_id):
        if self.dragging:
            self.pending_action = ("bind", workspace, run_id)
            return
        if self.run_id != run_id or not self.fabric or str(self.fabric.home) != str(workspace):
            self.flush_layout()
            self.pending_toggles = []
            self.fabric, self.run_id = Fabric(workspace), run_id
            self.fingerprint, self.positions, self.expanded = None, {}, set()
            self.layout_loaded = False
            self.load_layout()
            self.view.resetTransform()
            self.update_zoom()
            self.filter.blockSignals(True)
            self.filter.setCurrentIndex(0)
            self.filter.blockSignals(False)
        self.refresh()

    def layout_path(self):
        return self.fabric.home / "graph_layouts" / (self.run_id+".json")

    def load_layout(self):
        path = self.layout_path()
        if not path.is_file(): return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.positions = {k: v for k, v in data.get("positions", {}).items() if isinstance(v, list) and len(v) == 2
                              and all(isinstance(x, (int, float)) and math.isfinite(x) and abs(x) < 1e6 for x in v)}
            self.expanded = set(data.get("expanded", []))
            self.layout_loaded = True
        except (OSError, ValueError, TypeError): pass

    def flush_layout(self):
        self.save_timer.stop()
        if not self.fabric or not self.run_id or not self.nodes: return
        # QSaveFile uses a distinct temporary file for each writer. Two platform
        # windows must not race over the same fixed '.partial' filename.
        try:
            write_layout(self.layout_path(), dict(schema="donglanpec.execution-layout/1", positions=self.positions,
                expanded=sorted(self.expanded)))
        except (OSError, RuntimeError) as exc:
            self.show_notice("save", "布局暂未保存，当前拖动仍然有效："+str(exc))
            return False
        self.clear_notice("save")
        return True

    def stop_updates(self):
        self.stopped = True
        self.save_timer.stop()
        self.update_timer.stop()

    def clear(self):
        if self.dragging:
            self.pending_action = ("clear",)
            return
        self.flush_layout()
        self.update_timer.stop()
        self.pending_refresh, self.pending_render = False, False
        self.pending_action, self.pending_toggles = None, []
        self.run_id, self.fabric, self.fingerprint = None, None, None
        self.tasks, self.nodes, self.node_items, self.edges, self.value = {}, {}, {}, [], {}
        self.positions, self.expanded = {}, set()
        self.filter.blockSignals(True)
        self.filter.clear()
        self.filter.addItem("全部产品", "")
        self.filter.blockSignals(False)
        self.navigator.clear()
        self.scene.clear()
        self.details.clear()
        self.view.resetTransform()
        self.timing.setText("尚无任务回执")

    def refresh(self, force=False):
        if self.dragging:
            self.pending_refresh = True
            return
        if not self.fabric or not self.run_id: return
        value = self.fabric.execution(self.run_id)
        cycles = sum(len(review_cycles(r)) for r in value.get("reviews", []))
        self.timing.setText(("执行累计 "+duration(value["elapsed_seconds"]) if value["sessions"] else "任务耗时合计 "+duration(value["task_seconds"]))
                           +f"　｜　{len(value['tasks'])} 次调用　｜　{cycles} 轮有界复核")
        fingerprint = hashlib.sha256(json.dumps(dict(tasks=value["tasks"], reviews=value.get("reviews"), products=value.get("products")),
            ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        if not force and fingerprint == self.fingerprint: return
        self.fingerprint, self.value = fingerprint, value
        self.tasks = {t["id"]: t for t in value["tasks"]}
        full = execution_graph(value)
        selected = self.filter.currentData()
        self.filter.blockSignals(True)
        self.filter.clear()
        self.filter.addItem("全部产品", "")
        for p in full["products"]: self.filter.addItem(p.get("tag") or p["id"], p["id"])
        self.filter.setCurrentIndex(max(0, self.filter.findData(selected)))
        self.filter.blockSignals(False)
        if not self.layout_loaded and full["nodes"]:
            self.expanded = {"run"}
            if full["products"]: self.expanded.add("product:"+full["products"][0]["id"])
            self.layout_loaded = True
        self.populate_navigator(full)
        self.render()

    def populate_navigator(self, full):
        self.navigator.clear()
        root = QTreeWidgetItem(self.navigator, [f"本次任务 · {len(full['products'])} 个产品"])
        root.setData(0, Qt.UserRole, ("", None))
        root.setExpanded(True)
        for product in full["products"]:
            item = QTreeWidgetItem(root, [" · ".join(str(product.get(k) or "") for k in ("tag", "form")).strip(" ·") or product["id"]])
            item.setToolTip(0, product.get("name") or product.get("tag") or product["id"])
            item.setData(0, Qt.UserRole, (product["id"], None))
            for node in full["nodes"].values():
                if node["kind"] == "module" and node.get("product_id") == product["id"]:
                    child = QTreeWidgetItem(item, [node["title"]+" · "+str(len(node["children"]))])
                    child.setData(0, Qt.UserRole, (product["id"], node["id"]))

    def navigate_item(self, item, column):
        identity, module = item.data(0, Qt.UserRole) or ("", None)
        self.filter.setCurrentIndex(max(0, self.filter.findData(identity)))
        if identity:
            self.expanded.update({"run", "product:"+identity})
            self.render()
        if module:
            self.expanded.update({"run", "product:"+identity, module})
            self.render()
            if module in self.node_items:
                self.node_items[module].setSelected(True)
                self.view.centerOn(self.node_items[module])

    def visible_ancestor(self, identity):
        while identity and identity not in self.node_items:
            identity = self.nodes[identity]["parent"]
        return identity

    def render(self):
        if self.dragging or self.rendering:
            self.pending_render = True
            return
        horizontal, vertical = self.view.horizontalScrollBar().value(), self.view.verticalScrollBar().value()
        graph = execution_graph(self.value, self.filter.currentData() or "")
        self.nodes = graph["nodes"]
        self.rendering = True
        self.node_items, self.edges = {}, []
        self.scene.clear()
        if not self.nodes:
            self.scene.addText("执行后将显示真实调用和审核记录。")
            self.rendering = False
            return
        def visit(identity, depth, row):
            node = self.nodes[identity]
            item = GraphNode(self, node)
            self.scene.addItem(item)
            self.node_items[identity] = item
            item.setPos(*self.positions.get(identity, [24+depth*304*self.ui_scale, 24+row*166*self.ui_scale]))
            used = 0
            if identity in self.expanded:
                for child in node["children"]: used += visit(child, depth+1, row+used)
            return max(1, used)
        root = GraphNode(self, self.nodes["run"])
        self.scene.addItem(root)
        self.node_items["run"] = root
        root.setPos(*self.positions.get("run", [24, 24]))
        if "run" in self.expanded:
            product_row, shared_row = 0, 1
            for child in self.nodes["run"]["children"]:
                if self.nodes[child]["kind"] == "product": product_row += visit(child, 1, product_row)
                else:
                    visit(child, 0, shared_row)
                    shared_row += 1
        seen, feedbacks = set(), {}
        for edge in graph["edges"]:
            if edge["kind"] in ("execution", "legacy") and not self.dependencies.isChecked(): continue
            source, target = self.visible_ancestor(edge["source"]), self.visible_ancestor(edge["target"])
            if not source or not target or source == target: continue
            if edge["kind"] == "hierarchy" and (source != edge["source"] or target != edge["target"]): continue
            key = (source, target, edge["kind"])
            if edge["kind"] == "feedback":
                prior = feedbacks.setdefault(key, dict(edge, source=source, target=target, cycles=0, accepted=0))
                prior["cycles"] += 1
                prior["accepted"] += edge.get("accepted", 0)
                continue
            if key in seen: continue
            seen.add(key)
            item = GraphEdge(self.node_items[source], self.node_items[target], edge)
            self.scene.addItem(item)
            self.edges.append(item)
        for edge in feedbacks.values():
            edge["label"] = f"{edge['cycles']} 轮复核 · "+(f"采纳 {edge['accepted']} 项" if edge["accepted"] else "无新增值")
            item = GraphEdge(self.node_items[edge["source"]], self.node_items[edge["target"]], edge)
            self.scene.addItem(item)
            self.edges.append(item)
        self.update_bounds()
        self.rendering = False
        self.view.horizontalScrollBar().setValue(horizontal)
        self.view.verticalScrollBar().setValue(vertical)

    def update_bounds(self):
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-18, -18, 38, 38))

    def node_moved(self, identity, pos):
        if self.rendering or self.stopped: return
        self.positions[identity] = [pos.x(), pos.y()]
        for edge in self.edges:
            if identity in (edge.source.record["id"], edge.target.record["id"]): edge.update_path()
        if not self.dragging: self.update_bounds()
        self.save_timer.start(350)

    def toggle(self, identity):
        if identity in self.expanded: self.expanded.remove(identity)
        else: self.expanded.add(identity)
        self.render()
        self.save_timer.start(350)

    def expand_all(self):
        self.expanded = {k for k, n in self.nodes.items() if n["children"]}
        self.render()
        self.save_timer.start(350)

    def collapse_products(self):
        self.expanded = {"run"}
        self.render()
        self.save_timer.start(350)

    def restore_tree(self):
        self.positions = {}
        self.expanded = {"run"}
        product = next((n["id"] for n in self.nodes.values() if n["kind"] == "product"), None)
        if product: self.expanded.add(product)
        self.view.resetTransform()
        self.update_zoom()
        self.render()
        self.view.horizontalScrollBar().setValue(self.view.horizontalScrollBar().minimum())
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().minimum())
        self.save_timer.start(350)

    def fit(self):
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self.update_zoom()

    def selection(self):
        if self.rendering: return
        for item in self.scene.selectedItems():
            node = self.nodes.get(item.data(0))
            if node:
                self.details.setPlainText('执行者：'+node.get('executor_label', '')+'\n调度者：'+node.get('controller', '')
                    +'\n模块归属与调用记录如下：\n\n'+json.dumps(node.get("details"), ensure_ascii=False, indent=2))
                break
