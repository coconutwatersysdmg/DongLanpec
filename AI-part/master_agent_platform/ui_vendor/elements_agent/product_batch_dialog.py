# -*- coding: utf-8 -*-
"""批量建产品壳 · 人工确认门。"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from elements_agent.nodes.select_product import batch_create_product_shells


class BatchCreateProductDialog(QDialog):
    def __init__(self, parent=None, default_name: str = "", default_count: int = 1):
        super().__init__(parent)
        self.setWindowTitle("批量建产品")
        self.resize(480, 260)
        self.setFont(QFont("Microsoft YaHei UI", 11))
        self._created: List[Dict[str, str]] = []

        lay = QVBoxLayout(self)
        tip = QLabel(
            "按位号台数创建活动库产品壳（最小字段）。"
            "元件材料模板需后续在产品定义中初始化。"
        )
        tip.setWordWrap(True)
        lay.addWidget(tip)

        form = QFormLayout()
        self.ed_project = QLineEdit()
        self.ed_project.setPlaceholderText("项目ID")
        self.ed_name = QLineEdit(default_name or "新产品")
        self.ed_tag = QLineEdit()
        self.ed_tag.setPlaceholderText("位号前缀，可空")
        self.sp_count = QSpinBox()
        self.sp_count.setRange(1, 200)
        self.sp_count.setValue(max(1, int(default_count or 1)))
        form.addRow("项目ID", self.ed_project)
        form.addRow("产品名称", self.ed_name)
        form.addRow("位号前缀", self.ed_tag)
        form.addRow("台数", self.sp_count)
        lay.addLayout(form)

        row = QHBoxLayout()
        row.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("创建")
        btn_ok.clicked.connect(self._on_ok)
        row.addWidget(btn_cancel)
        row.addWidget(btn_ok)
        lay.addLayout(row)

    def _on_ok(self):
        project_id = self.ed_project.text().strip()
        name = self.ed_name.text().strip() or "新产品"
        if not project_id:
            QMessageBox.warning(self, "提示", "请填写项目ID")
            return
        created, logs = batch_create_product_shells(
            project_id=project_id,
            base_name=name,
            count=int(self.sp_count.value()),
            tag_prefix=self.ed_tag.text().strip(),
        )
        self._created = created
        QMessageBox.information(self, "结果", "\n".join(logs) or "无结果")
        if created:
            self.accept()

    def created_products(self) -> List[Dict[str, str]]:
        return list(self._created)


def show_batch_create_dialog(
    parent=None, default_name: str = "", default_count: int = 1
) -> Tuple[bool, List[Dict[str, str]]]:
    dlg = BatchCreateProductDialog(
        parent, default_name=default_name, default_count=default_count
    )
    ok = dlg.exec_() == QDialog.Accepted
    return ok, dlg.created_products()
