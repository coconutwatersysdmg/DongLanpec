# -*- coding: utf-8 -*-
"""
产品选择：模仿项目管理「打开项目」——选项目文件夹 → 读 id.csv → 列出该项目下产品。
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

_LAST_PATH_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "_last_project_path.txt",
)

PICKER_QSS = """
QDialog {
    background: #f5f6f8;
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
}
QLabel#Title {
    font-size: 16pt;
    font-weight: 700;
    color: #1f2329;
}
QLabel#Meta {
    font-size: 11pt;
    color: #646a73;
}
QTableWidget {
    background: #ffffff;
    border: 1px solid #e5e6eb;
    font-size: 11pt;
    gridline-color: #eef0f3;
    selection-background-color: #d6e4ff;
    selection-color: #1f2329;
}
QHeaderView::section {
    background: #f7f8fa;
    color: #4e5969;
    padding: 8px;
    border: none;
    border-bottom: 1px solid #e5e6eb;
    font-weight: 600;
}
QPushButton#Primary {
    background: #2f6bff;
    color: #fff;
    border: none;
    border-radius: 8px;
    padding: 8px 18px;
    font-size: 12pt;
    min-height: 36px;
}
QPushButton#Primary:hover { background: #2458d6; }
QPushButton#Primary:disabled { background: #a8b8e8; }
QPushButton#Secondary {
    background: #f2f3f5;
    color: #1f2329;
    border: 1px solid #e5e6eb;
    border-radius: 8px;
    padding: 8px 18px;
    font-size: 12pt;
    min-height: 36px;
}
"""


def _get_last_path() -> str:
    try:
        if os.path.exists(_LAST_PATH_FILE):
            with open(_LAST_PATH_FILE, "r", encoding="utf-8") as f:
                p = f.read().strip()
            if p and os.path.isdir(p):
                return p
    except Exception:
        pass
    return ""


def _save_last_path(path: str) -> None:
    try:
        with open(_LAST_PATH_FILE, "w", encoding="utf-8") as f:
            f.write(path or "")
    except Exception:
        pass


def load_project_from_folder(folder_path: str) -> Tuple[Optional[dict], List[dict], str]:
    """
    打开项目文件夹：读 id.csv → 查项目 → 查产品列表。
    返回 (project_info, products, error_message)
    """
    folder_path = os.path.normpath(os.path.abspath(folder_path or ""))
    if not folder_path or not os.path.isdir(folder_path):
        return None, [], "请选择有效的项目文件夹"

    csv_path = os.path.join(folder_path, "id.csv")
    if not os.path.exists(csv_path):
        return None, [], f"未找到 id.csv（请选择项目管理生成的项目根目录）\n{csv_path}"

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            project_id = f.read().strip()
    except Exception as e:
        return None, [], f"读取 id.csv 失败：{e}"

    if not project_id:
        return None, [], "id.csv 为空，无法获取项目ID"

    try:
        from modules.chanpinguanli.common_usage import (
            get_mysql_connection_product,
            get_mysql_connection_project,
        )
    except Exception as e:
        return None, [], f"无法连接项目管理数据库模块：{e}"

    try:
        conn = get_mysql_connection_project()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM 项目需求表 WHERE 项目ID = %s", (project_id,))
                project_info = cur.fetchone()
        finally:
            conn.close()
    except Exception as e:
        return None, [], f"查询项目失败：{e}"

    if not project_info:
        return None, [], f"未找到项目信息（项目ID={project_id}）"

    try:
        conn = get_mysql_connection_product()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 产品ID, 产品名称, 设备位号, 产品编号, 产品类型, 产品型式, 设计阶段
                    FROM 产品需求表
                    WHERE 项目ID = %s
                    ORDER BY 产品ID
                    """,
                    (project_id,),
                )
                products = list(cur.fetchall() or [])
        finally:
            conn.close()
    except Exception as e:
        return None, [], f"查询产品列表失败：{e}"

    # 规范化 dict
    norm_products: List[dict] = []
    for p in products:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("产品ID") or "").strip()
        if not pid:
            continue
        norm_products.append(
            {
                "产品ID": pid,
                "产品名称": str(p.get("产品名称") or "").strip(),
                "设备位号": str(p.get("设备位号") or "").strip(),
                "产品编号": str(p.get("产品编号") or "").strip(),
                "产品类型": str(p.get("产品类型") or "").strip(),
                "产品型式": str(p.get("产品型式") or "").strip(),
                "设计阶段": str(p.get("设计阶段") or "").strip(),
            }
        )

    info = dict(project_info)
    info["项目ID"] = project_id
    info["_folder"] = folder_path
    return info, norm_products, ""


class ProductPickerDialog(QDialog):
    """选项目文件夹 → 选产品。再次打开时自动载入上次项目，可直接换产品。"""

    def __init__(
        self,
        parent=None,
        *,
        initial_folder: str = "",
        current_product_id: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle("选择产品")
        self.resize(900, 560)
        self.setMinimumSize(720, 420)
        self.setStyleSheet(PICKER_QSS)
        self.setFont(QFont("Microsoft YaHei UI", 11))

        self._project_info: Optional[dict] = None
        self._products: List[dict] = []
        self.selected_product: Optional[Dict[str, str]] = None
        self._initial_folder = (initial_folder or "").strip() or _get_last_path()
        self._current_product_id = (current_product_id or "").strip()

        self._build_ui()
        # 已有上次项目路径时：自动载入产品列表，无需再选文件夹
        if self._initial_folder and os.path.isdir(self._initial_folder):
            self._apply_folder(self._initial_folder, remember=False)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        title = QLabel("选择产品")
        title.setObjectName("Title")
        layout.addWidget(title)

        tip = QLabel(
            "若已打开过项目，下方会直接列出该项目产品，点选即可切换。"
            "换项目时再点「浏览项目文件夹…」，选择含 id.csv 的项目根目录。"
        )
        tip.setObjectName("Meta")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        row = QHBoxLayout()
        self.btn_browse = QPushButton("浏览项目文件夹…")
        self.btn_browse.setObjectName("Secondary")
        self.btn_browse.clicked.connect(self.on_browse)
        self.lbl_project = QLabel("尚未选择项目")
        self.lbl_project.setObjectName("Meta")
        self.lbl_project.setWordWrap(True)
        row.addWidget(self.btn_browse)
        row.addWidget(self.lbl_project, 1)
        layout.addLayout(row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["产品名称", "设备位号", "产品编号", "类型", "型式", "产品ID"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.doubleClicked.connect(self._accept_current)
        layout.addWidget(self.table, 1)

        foot = QHBoxLayout()
        self.lbl_count = QLabel("")
        self.lbl_count.setObjectName("Meta")
        foot.addWidget(self.lbl_count)
        foot.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("Secondary")
        btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("确定")
        self.btn_ok.setObjectName("Primary")
        self.btn_ok.setEnabled(False)
        self.btn_ok.clicked.connect(self._accept_current)
        foot.addWidget(btn_cancel)
        foot.addWidget(self.btn_ok)
        layout.addLayout(foot)

        self.table.itemSelectionChanged.connect(self._on_sel_changed)

    def on_browse(self):
        start = self._initial_folder or _get_last_path()
        folder = QFileDialog.getExistingDirectory(self, "选择项目文件夹", start)
        if not folder:
            return
        self._apply_folder(folder, remember=True)

    def _apply_folder(self, folder: str, *, remember: bool = True) -> bool:
        project_info, products, err = load_project_from_folder(folder)
        if err:
            QMessageBox.warning(self, "无法打开项目", err)
            return False
        if remember:
            _save_last_path(folder)
        self._initial_folder = folder
        self._project_info = project_info
        self._products = products
        name = str(project_info.get("项目名称") or "").strip()
        pid = str(project_info.get("项目ID") or "").strip()
        self.lbl_project.setText(f"项目：{name or '(未命名)'}　　ID：{pid}\n路径：{folder}")
        self._fill_table()
        self.lbl_count.setText(f"共 {len(products)} 个产品（可直接点选切换）")
        return True

    def _fill_table(self):
        self.table.setRowCount(len(self._products))
        select_row = 0
        for r, p in enumerate(self._products):
            vals = [
                p.get("产品名称", ""),
                p.get("设备位号", ""),
                p.get("产品编号", ""),
                p.get("产品类型", ""),
                p.get("产品型式", ""),
                p.get("产品ID", ""),
            ]
            for c, text in enumerate(vals):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if c == 5:
                    item.setData(Qt.UserRole, p)
                self.table.setItem(r, c, item)
            if self._current_product_id and p.get("产品ID") == self._current_product_id:
                select_row = r
        if self._products:
            self.table.selectRow(select_row)
            self.table.scrollToItem(self.table.item(select_row, 0))
            self.btn_ok.setEnabled(True)
        else:
            self.btn_ok.setEnabled(False)

    def _on_sel_changed(self):
        self.btn_ok.setEnabled(bool(self.table.selectionModel().selectedRows()))

    def _accept_current(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "提示", "请先选中一个产品")
            return
        r = rows[0].row()
        item = self.table.item(r, 5)
        data = item.data(Qt.UserRole) if item else None
        if not isinstance(data, dict) or not data.get("产品ID"):
            QMessageBox.warning(self, "提示", "无法读取产品ID")
            return
        self.selected_product = dict(data)
        if self._project_info:
            self.selected_product["项目ID"] = str(self._project_info.get("项目ID") or "")
            self.selected_product["项目名称"] = str(self._project_info.get("项目名称") or "")
            self.selected_product["_folder"] = str(self._project_info.get("_folder") or self._initial_folder or "")
        elif self._initial_folder:
            self.selected_product["_folder"] = self._initial_folder
        self.accept()


def pick_product(
    parent=None,
    *,
    project_folder: str = "",
    current_product_id: str = "",
) -> Optional[Dict[str, str]]:
    """弹出选择器；确定返回产品 dict（含 产品ID / _folder），取消返回 None。"""
    dlg = ProductPickerDialog(
        parent,
        initial_folder=project_folder,
        current_product_id=current_product_id,
    )
    if dlg.exec_() != QDialog.Accepted:
        return None
    return dlg.selected_product
