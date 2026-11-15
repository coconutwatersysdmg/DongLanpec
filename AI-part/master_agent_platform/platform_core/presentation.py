"""Unified visual components backed by persisted task and data-space records."""
from __future__ import annotations

import json
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QBrush, QFont
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QGraphicsScene, QGraphicsView, QSplitter, QPlainTextEdit,
    QTreeWidget, QTreeWidgetItem, QTabWidget, QTextBrowser)

from .fabric import Fabric
from .run_view import duration, space_snapshot


class ExecutionPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.run_id = None
        self.fabric = None
        self.fingerprint = None
        self.tasks = {}
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.heading = QLabel("实际执行路径")
        self.heading.setObjectName("sectionTitle")
        self.filter = QComboBox()
        self.filter.addItem("全部产品", "")
        self.filter.currentIndexChanged.connect(lambda: self.refresh(True))
        row.addWidget(self.heading, 1)
        row.addWidget(self.filter)
        for text, scale in (("−", .8), ("+", 1.25)):
            button = QPushButton(text)
            button.setFixedWidth(34)
            button.clicked.connect(lambda _, v=scale: self.view.scale(v, v))
            row.addWidget(button)
        layout.addLayout(row)
        self.timing = QLabel("尚无任务回执")
        layout.addWidget(self.timing)
        self.legend = QLabel("蓝色 运行中　绿色 已完成　红色 失败　灰色 已取消　虚线 历史顺序重建")
        self.legend.setObjectName("muted")
        layout.addWidget(self.legend)
        split = QSplitter(Qt.Vertical)
        self.scene = QGraphicsScene(self)
        self.scene.selectionChanged.connect(self.selection)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        self.view.setBackgroundBrush(QColor("#f8fafc"))
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("点击节点查看输入文件、知识检索数、调用时间和回执目录。")
        split.addWidget(self.view)
        split.addWidget(self.details)
        split.setSizes([570, 155])
        layout.addWidget(split, 1)

    def bind(self, workspace, run_id):
        if self.run_id != run_id:
            self.fingerprint = None
        self.fabric, self.run_id = Fabric(workspace), run_id
        self.refresh()

    def refresh(self, force=False):
        if not self.fabric or not self.run_id: return
        value = self.fabric.execution(self.run_id)
        self.timing.setText(("执行会话累计 " + duration(value["elapsed_seconds"]) if value["sessions"] else "历史任务累计 " + duration(value["task_seconds"]) + " · 旧批次未记录整轮耗时")
                            + f"　｜　{len(value['tasks'])} 次实际调用")
        selected = self.filter.currentData()
        products = {t["product_id"]: t["product"] for t in value["tasks"] if t["product_id"]}
        if products != getattr(self, "products", {}):
            self.products = products
            self.filter.blockSignals(True)
            self.filter.clear()
            self.filter.addItem("全部产品", "")
            for key, label in products.items(): self.filter.addItem(label, key)
            self.filter.setCurrentIndex(max(0, self.filter.findData(selected)))
            self.filter.blockSignals(False)
        tasks = [t for t in value["tasks"] if not selected or t["product_id"] in ("", selected)]
        actual_count = len(tasks)
        tasks = [dict(t) for t in tasks]
        if value.get("sources"):
            identity = "space:" + self.run_id
            for task in tasks:
                if not task["product_id"] and not task["dependencies"]:
                    task["dependencies"] = [identity]
            tasks.insert(0, dict(id=identity, label="数据空间托管", product=f"{len(value['sources'])} 份资料 · SHA256", product_id="", state="succeeded",
                duration_seconds=None, dependencies=[], dependency_basis="recorded", receipt_directory=str(self.fabric.home / "runs" / self.run_id / "inputs"),
                input_files=[s["path"] for s in value["sources"]], source_ids=[s["id"] for s in value["sources"]],
                note="来自已落盘的 sources.json；该托管阶段未单独计时。"))
        generation = next((s for s in value["sessions"] if s["operation"] == "generation"), None)
        if generation:
            identity = "session:" + generation["id"]
            for task in tasks:
                if not task["product_id"] and not task["dependencies"]: task["dependencies"] = [identity]
            tasks.insert(0, dict(id=identity, label="主控 Agent 编排", product="本轮多产品任务", product_id="",
                state="running" if generation["state"] == "running" else "cancelled" if generation["state"] == "cancelled" else "failed" if generation["state"] == "failed" else "succeeded",
                duration_seconds=generation["duration_seconds"], dependencies=[], dependency_basis="recorded",
                receipt_directory=str(self.fabric.home / "runs" / self.run_id),
                note="来自真实 generation 执行会话；耗时包含基础数据准备、任务分发和结果打包，不代表工程校核通过。"))
        fingerprint = [(t["id"], t["state"], t["product"], t["label"], int(t["duration_seconds"] or 0)) for t in tasks]
        if not force and fingerprint == self.fingerprint: return
        self.fingerprint = fingerprint
        self.tasks = {t["id"]: t for t in tasks}
        horizontal, vertical = self.view.horizontalScrollBar().value(), self.view.verticalScrollBar().value()
        self.scene.clear()
        if not tasks:
            self.scene.addText("执行后，这里将根据真实任务回执生成路径图。")
            return
        positions, rows, counts = {}, {}, {}
        for task in tasks:
            key = task["product_id"]
            if key not in rows: rows[key] = len(rows)
            column = counts.get(key, 0)
            counts[key] = column + 1
            positions[task["id"]] = (28 + column*228, 24 + rows[key]*136)
        colors = {"succeeded": ("#ecfdf5", "#059669"), "running": ("#eff6ff", "#2563eb"),
                  "failed": ("#fff1f2", "#e11d48"), "cancelled": ("#f1f5f9", "#64748b")}
        states = {"succeeded": "完成", "running": "运行中", "failed": "失败", "cancelled": "已取消"}
        title_font = QFont("Microsoft YaHei")
        title_font.setPixelSize(13)
        title_font.setBold(True)
        body_font = QFont("Microsoft YaHei")
        body_font.setPixelSize(12)
        for task in tasks:
            x, y = positions[task["id"]]
            for parent in task["dependencies"]:
                if parent not in positions: continue
                a, b = positions[parent]
                path = QPainterPath()
                path.moveTo(a+200, b+48)
                path.cubicTo(a+232, b+48, x-22, y+48, x, y+48)
                pen = QPen(QColor("#94a3b8"), 1.4)
                if task["dependency_basis"] == "legacy-order": pen.setStyle(Qt.DashLine)
                edge = self.scene.addPath(path, pen)
                edge.setZValue(-1)
                self.scene.addLine(x-6, y+44, x, y+48, pen)
                self.scene.addLine(x-6, y+52, x, y+48, pen)
            background, border = colors.get(task["state"], ("#ffffff", "#cbd5e1"))
            box = self.scene.addRect(x, y, 200, 96, QPen(QColor(border), 1.2), QBrush(QColor(background)))
            box.setFlag(box.ItemIsSelectable)
            box.setData(0, task["id"])
            box.setToolTip(task["receipt_directory"])
            title = self.scene.addText(task["label"], title_font)
            title.setTextWidth(180)
            title.setPos(x+10, y+8)
            title.setDefaultTextColor(QColor("#172b4d"))
            quality = " · 需审核" if task.get("result_summary", {}).get("validation_state") == "needs_review" else ""
            body = self.scene.addText(task["product"][:23] + "\n" + states.get(task["state"], task["state"]) + quality + " · " + duration(task["duration_seconds"]), body_font)
            body.setTextWidth(180)
            body.setPos(x+10, y+38)
            body.setDefaultTextColor(QColor("#475569"))
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-16, -16, 24, 24))
        self.view.horizontalScrollBar().setValue(horizontal)
        self.view.verticalScrollBar().setValue(vertical)

    def selection(self):
        for item in self.scene.selectedItems():
            task = self.tasks.get(item.data(0))
            if task:
                self.details.setPlainText(json.dumps(task, ensure_ascii=False, indent=2))
                break


class DataSpacePanel(QWidget):
    open_file = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        title = QLabel("数据空间")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.stats = QLabel("输入文件与知识资料将在这里形成产品关联和分发记录。")
        self.stats.setWordWrap(True)
        layout.addWidget(self.stats)
        self.tabs = QTabWidget()
        self.resources = QTreeWidget()
        self.resources.setHeaderLabels(["资源 / 产品", "用途 / 型式", "版本 / 页范围", "状态 / 摘要"])
        self.resources.itemDoubleClicked.connect(self.open_resource)
        self.tabs.addTab(self.resources, "文件与产品关联")
        self.knowledge = QTextBrowser()
        self.tabs.addTab(self.knowledge, "知识与检索")
        self.catalog = QTreeWidget()
        self.catalog.setHeaderLabels(["资源名称", "类型", "当前版本", "托管状态"])
        self.tabs.addTab(self.catalog, "空间资源目录")
        self.fields = QTreeWidget()
        self.fields.setHeaderLabels(["产品 / 模块字段", "当前候选值", "单位 / 来源", "来源页"])
        self.tabs.addTab(self.fields, "结构化数据与基础库")
        layout.addWidget(self.tabs, 1)

    def bind(self, workspace, run_id):
        from html import escape
        fabric = Fabric(workspace)
        data = space_snapshot(fabric, run_id)
        self.snapshot = data
        self.stats.setText(f"{len(data['resources'])} 份本次资料　·　{len(data['products'])} 个产品关联　·　{len(data['datasets'])} 份审核数据集　·　{len(data['knowledge'])} 条知识片段　·　{len(data['queries'])} 次实际分发回执\n文件副本、SHA256、原文页与检索引用均可追溯。双击资源可打开托管副本。")
        self.resources.clear()
        for resource in data["resources"]:
            try: version = "v" + str(fabric.resources.get(resource["id"])["version"])
            except Exception: version = "版本未登记"
            parent = QTreeWidgetItem([resource.get("title", ""), resource["role"], version, resource["sha256"][:18]])
            parent.setData(0, Qt.UserRole, resource.get("managed_path") or resource["path"])
            parent.setToolTip(0, resource.get("managed_path") or resource["path"])
            self.resources.addTopLevelItem(parent)
            for product in data["products"]:
                if product["tag"] in resource["products"]:
                    source = product.get("source") or {}
                    pages = "—".join(str(p) for p in source.get("original_pages", []) if p is not None)
                    child = QTreeWidgetItem([product["tag"], product["form"] or "型式待识别", "原文 " + pages, "知识关联" if resource["id"] in product["knowledge_ids"] else "产品分片"])
                    child.setData(0, Qt.UserRole, source.get("path"))
                    parent.addChild(child)
            parent.setExpanded(True)
        html = ["<h3>知识分发记录</h3><p>以下为实际检索传入数量；是否采用仍以字段来源及校验结果为准。</p>"]
        for query in data["queries"]:
            html.append(f"<p><b>{escape(query['product'])} · {escape(query['agent'])}</b>　{query['chunks']} 条检索片段　<small>{query['task_id'][:12]}</small></p>")
        html.append("<h3>知识片段</h3>")
        for chunk in data["knowledge"]:
            html.append("<p>" + escape(str(chunk.get("text", ""))[:1800]).replace("\n", "<br>") + "</p><hr>")
        self.knowledge.setHtml("".join(html))
        self.catalog.clear()
        scope = {p["id"] for p in data["products"]}
        for resource in fabric.resources.list():
            if resource["product_id"] and resource["product_id"] not in scope: continue
            QTreeWidgetItem(self.catalog, [str(resource.get(k) or "") for k in ("title", "kind", "version", "status")])
        self.fields.clear()
        foundation_root = QTreeWidgetItem(self.fields, ["基础数据副本与适用模板"])
        snapshot_path = fabric.home / "snapshots" / "foundation-snapshot.json"
        if snapshot_path.is_file():
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            QTreeWidgetItem(foundation_root, ["已复制并核对的基础库", "、".join(snapshot.get("foundations", [])), str(len(snapshot.get("tables", [])))+" 张表", snapshot.get("status", "")])
        for row in data["foundations"]:
            QTreeWidgetItem(foundation_root, [str(row["product"]), f"{row['form']} · {row['configuration'] or '配置未记录'}", f"材料模板 {row['material_template_rows']} · 条件模板 {row['condition_template_rows']} · 参数模板 {row['parameter_template_rows']}", str(row.get("snapshot_sha256") or "")[:16]])
        dataset_root = QTreeWidgetItem(self.fields, ["托管的产品审核数据集"])
        for resource in data["datasets"]:
            QTreeWidgetItem(dataset_root, [resource["title"], "v"+str(resource["version"]), resource["id"], resource["status"]])
        groups = {}
        for row in data["structured"]:
            key = (row["product"], row["module"])
            if key not in groups: groups[key] = QTreeWidgetItem(self.fields, [" · ".join(str(k) for k in key)])
            value = row.get("value")
            text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str("" if value is None else value)
            child = QTreeWidgetItem(groups[key], [row["field"], text, " · ".join(str(row.get(k) or "") for k in ("unit", "origin")), str(row.get("page") or "")])
            child.setToolTip(1, text)
        foundation_root.setExpanded(True)
        dataset_root.setExpanded(True)
        for tree in (self.resources, self.catalog): tree.setColumnWidth(0, 320)

    def open_resource(self, item, column):
        value = item.data(0, Qt.UserRole)
        if value: self.open_file.emit(value)
