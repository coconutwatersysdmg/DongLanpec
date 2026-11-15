"""Unified visual components backed by persisted task and data-space records."""
from __future__ import annotations

import json
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem, QTabWidget, QTextBrowser)

from .fabric import Fabric
from .run_view import space_snapshot


from .execution_graph import ExecutionPanel


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

    def clear(self):
        self.snapshot = None
        self.stats.setText("输入文件与知识资料将在这里形成产品关联和分发记录。")
        for tree in (self.resources, self.catalog, self.fields): tree.clear()
        self.knowledge.clear()
        self.tabs.setCurrentIndex(0)

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
