# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QBrush, QPen
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class TubeAssistantPanel(QDialog):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("管束方案助手")
        self.setModal(False)
        self.resize(880, 680)
        self.setStyleSheet(
            "QDialog{background:#F3F6F8;} QLabel{color:#243746;}"
            "QPushButton{padding:7px 13px;} QTabWidget::pane{border:1px solid #B8C4CE;}"
        )
        root = QVBoxLayout(self)
        banner = QLabel("工程算法负责计算与校验；助手只生成候选，选中后才应用。")
        banner.setStyleSheet("background:#E4EDF4;border-left:4px solid #1F5D85;padding:10px;font-weight:600;")
        root.addWidget(banner)

        request_row = QHBoxLayout()
        self.request_text = QTextEdit()
        self.request_text.setMaximumHeight(70)
        self.request_text.setPlaceholderText("以后配置 API 后可输入：尽量多布管；或在上部对称布置 4 个拉杆")
        request_row.addWidget(self.request_text, 1)
        parse_button = QPushButton("AI 解析需求")
        parse_button.setToolTip("只把自然语言转换成白名单选项，不直接修改设计")
        parse_button.clicked.connect(self._parse_request)
        request_row.addWidget(parse_button)
        root.addLayout(request_row)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_tube_tab(), "布管方案")
        self.tabs.addTab(self._build_component_tab(), "元件方案")
        root.addWidget(self.tabs, 1)

        self.status = QLabel("API 未配置：当前可直接使用结构化选项和本地工程算法。")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("padding:8px;color:#52697A;")
        root.addWidget(self.status)

    def _build_tube_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("目标"))
        self.goal = QComboBox()
        self.goal.addItems(["尽量多布", "至少管数", "至多管数", "尽量少布"])
        controls.addWidget(self.goal)
        self.target = QSpinBox()
        self.target.setRange(0, 99999)
        self.target.setValue(300)
        controls.addWidget(self.target)
        self.goal.currentTextChanged.connect(
            lambda text: self.target.setEnabled(text in ("至少管数", "至多管数"))
        )
        self.target.setEnabled(False)
        generate = QPushButton("生成候选")
        generate.clicked.connect(self._generate_tubes)
        controls.addWidget(generate)
        controls.addStretch()
        layout.addLayout(controls)

        self.tube_table = QTableWidget(0, 4)
        self.tube_table.setHorizontalHeaderLabels(["候选", "布置方式", "程序管数", "说明"])
        self.tube_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.tube_table.setSelectionMode(QTableWidget.SingleSelection)
        self.tube_table.horizontalHeader().setStretchLastSection(True)
        self.tube_table.itemSelectionChanged.connect(self._preview_tube)
        layout.addWidget(self.tube_table, 1)

        self.tube_preview = QGraphicsView()
        self.tube_preview.setMinimumHeight(230)
        layout.addWidget(self.tube_preview)
        apply_button = QPushButton("一键填充参数并布管")
        apply_button.setStyleSheet("background:#1F6F54;color:white;font-weight:600;")
        apply_button.clicked.connect(self._apply_tube)
        layout.addWidget(apply_button, alignment=Qt.AlignRight)
        return page

    def _build_component_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.component = QComboBox()
        self.component.addItem("拉杆")
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 64)
        self.quantity.setValue(4)
        self.region = QComboBox()
        self.region.addItems(["外围对称", "上部", "下部", "左侧", "右侧"])
        form.addRow("元件", self.component)
        form.addRow("数量", self.quantity)
        form.addRow("大致位置", self.region)
        layout.addLayout(form)
        generate = QPushButton("生成元件候选")
        generate.clicked.connect(self._generate_components)
        layout.addWidget(generate, alignment=Qt.AlignLeft)
        self.component_table = QTableWidget(0, 3)
        self.component_table.setHorizontalHeaderLabels(["候选", "位置数", "说明"])
        self.component_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.component_table.setSelectionMode(QTableWidget.SingleSelection)
        self.component_table.horizontalHeader().setStretchLastSection(True)
        self.component_table.itemSelectionChanged.connect(self._preview_component)
        layout.addWidget(self.component_table, 1)
        self.component_preview = QGraphicsView()
        self.component_preview.setMinimumHeight(230)
        layout.addWidget(self.component_preview)
        apply_button = QPushButton("一键布置拉杆")
        apply_button.setStyleSheet("background:#9B5B15;color:white;font-weight:600;")
        apply_button.clicked.connect(self._apply_component)
        layout.addWidget(apply_button, alignment=Qt.AlignRight)
        return page

    def refresh_context(self):
        count = len(getattr(self.parent(), "current_centers", []) or [])
        self.set_status(f"当前有效管孔：{count}。API 未配置，本地推荐功能可用。")

    def set_status(self, text):
        self.status.setText(str(text))

    def _fill_table(self, table, rows):
        table.setRowCount(len(rows))
        for row_index, values in enumerate(rows):
            for col_index, value in enumerate(values):
                table.setItem(row_index, col_index, QTableWidgetItem(str(value)))
        if rows:
            table.selectRow(0)

    def _generate_tubes(self):
        try:
            target = self.target.value() if self.target.isEnabled() else None
            candidates = self.controller.generate_tubes(self.goal.currentText(), target)
            self._fill_table(
                self.tube_table,
                [(c.name, c.layout, c.tube_count, c.explanation) for c in candidates],
            )
            self.set_status(f"已用原有布管算法生成 {len(candidates)} 个候选方案。")
        except Exception as exc:
            QMessageBox.warning(self, "无法生成", str(exc))

    def _parse_request(self):
        try:
            parsed = self.controller.parse_natural_language(self.request_text.toPlainText())
            if parsed["intent"] == "tube":
                self.tabs.setCurrentIndex(0)
                self.goal.setCurrentText(parsed["goal_mode"])
                if "target_count" in parsed:
                    self.target.setValue(parsed["target_count"])
                self._generate_tubes()
            else:
                self.tabs.setCurrentIndex(1)
                self.quantity.setValue(parsed["quantity"])
                self.region.setCurrentText(parsed["region"])
                self._generate_components()
        except Exception as exc:
            QMessageBox.information(self, "AI 解析暂不可用", str(exc))

    def _generate_components(self):
        try:
            candidates = self.controller.generate_components(self.quantity.value(), self.region.currentText())
            self._fill_table(
                self.component_table,
                [(c.name, len(c.centers), c.explanation) for c in candidates],
            )
            self.set_status(f"已从当前管孔生成 {len(candidates)} 个拉杆候选方案。")
        except Exception as exc:
            QMessageBox.warning(self, "无法生成", str(exc))

    def _draw_points(self, view, base_points, selected_points=()):
        scene = QGraphicsScene(view)
        all_points = list(base_points)
        if not all_points:
            view.setScene(scene)
            return
        radius = max(max(abs(x), abs(y)) for x, y in all_points) or 1
        dot = max(radius / 100.0, 1.2)
        scene.addEllipse(-radius, -radius, radius * 2, radius * 2, QPen(QColor("#6F7F89")))
        selected = {(round(x, 6), round(y, 6)) for x, y in selected_points}
        for x, y in all_points:
            active = (round(x, 6), round(y, 6)) in selected
            color = QColor("#D1493F" if active else "#274C77")
            scene.addEllipse(x - dot, y - dot, dot * 2, dot * 2, QPen(color), QBrush(color))
        scene.setSceneRect(-radius * 1.1, -radius * 1.1, radius * 2.2, radius * 2.2)
        view.setScene(scene)
        view.fitInView(scene.sceneRect(), Qt.KeepAspectRatio)

    def _preview_tube(self):
        row = self.tube_table.currentRow()
        if 0 <= row < len(self.controller._tube_candidates):
            candidate = self.controller._tube_candidates[row]
            self._draw_points(self.tube_preview, candidate.centers)

    def _preview_component(self):
        row = self.component_table.currentRow()
        if 0 <= row < len(self.controller._component_candidates):
            candidate = self.controller._component_candidates[row]
            base = getattr(self.parent(), "current_centers", []) or []
            self._draw_points(self.component_preview, base, candidate.centers)

    def _apply_tube(self):
        row = self.tube_table.currentRow()
        if not (0 <= row < len(self.controller._tube_candidates)):
            QMessageBox.information(self, "提示", "请先生成并选择一个布管方案。")
            return
        try:
            candidate = self.controller._tube_candidates[row]
            self.controller.apply_tube_candidate(candidate)
            self.set_status(f"已应用 {candidate.name}（{candidate.layout}），可点击主界面的撤销按钮恢复。")
        except Exception as exc:
            QMessageBox.warning(self, "应用失败", str(exc))

    def _apply_component(self):
        row = self.component_table.currentRow()
        if not (0 <= row < len(self.controller._component_candidates)):
            QMessageBox.information(self, "提示", "请先生成并选择一个拉杆方案。")
            return
        try:
            candidate = self.controller._component_candidates[row]
            self.controller.apply_component_candidate(candidate)
            self.set_status(f"已应用 {candidate.name}，可点击主界面的撤销按钮恢复。")
        except Exception as exc:
            QMessageBox.warning(self, "应用失败", str(exc))
