# -*- coding: utf-8 -*-
"""独立演示和管束助手共用的参数抽取界面。"""
from __future__ import annotations

import json
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, QEvent, pyqtSignal
from PyQt5.QtGui import QColor, QPen
from PyQt5.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QTextEdit, QPlainTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QTabWidget, QGraphicsView, QGraphicsScene, QFileDialog,
    QMessageBox, QDialogButtonBox, QAbstractItemView, QApplication,
)

from .api_client import APIConfig, CompatibleChatClient
from .extraction import SAMPLE_TEXT, SAMPLE_RESPONSE, validate_extraction, preview_layout

_ACTIVE_WORKERS = set()


def _finish_worker(worker):
    _ACTIVE_WORKERS.discard(worker)
    worker.deleteLater()


def _wait_for_workers():
    # QApplication.quit绕过窗口Close事件时，仍需让网络线程结束后再销毁。
    for worker in tuple(_ACTIVE_WORKERS):
        worker.wait()


class BailianSettings(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("百炼设置 · 密钥仅本次运行有效")
        self.resize(650, 270)
        config = APIConfig.load()
        root = QVBoxLayout(self)
        note = QLabel("在百炼控制台复制 API Key 到这里。密钥仅保留在内存，关闭程序后需重新输入。\n"
                      "Base URL 的地域须与密钥一致；支持控制台业务空间专属域名。")
        note.setWordWrap(True)
        root.addWidget(note)
        form = QFormLayout()
        self.base_url = QLineEdit(config.base_url)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItems(["qwen-plus", "qwen-flash"])
        self.model.setCurrentText(config.model)
        self.key = QLineEdit(config.api_key)
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("粘贴百炼 API Key；不要粘贴阿里云 AccessKey")
        form.addRow("Base URL", self.base_url)
        form.addRow("模型名称", self.model)
        form.addRow("API Key", self.key)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存设置（不调用API）")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _save(self):
        config = APIConfig(self.base_url.text().strip(), self.key.text().strip(),
                           self.model.currentText().strip())
        try:
            config.endpoint()
            if not config.configured:
                raise ValueError("请填写地址、模型和API Key")
            # 只持久化非敏感选项；密钥不写入文件。
            config.save_public_settings()
            config.use_for_session()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "设置未保存", str(exc))
            return
        self.accept()


class ExtractionWorker(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, config, text, parent=None):
        super().__init__(parent)
        self.config, self.text = config, text

    def run(self):
        try:
            self.succeeded.emit(CompatibleChatClient(self.config).extract_parameters(self.text))
        except (ValueError, RuntimeError) as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("请求处理失败，请检查输入和设置。密钥未写入日志。")


class ExtractionPanel(QWidget):
    def __init__(self, parent=None, context_provider=None):
        super().__init__(parent)
        self.context_provider = context_provider
        self.result = None
        self.worker = None
        self._request_context = None
        self._request_text = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        title = QLabel("管束参数抽取 Demo")
        title.setStyleSheet("font-size:22px;font-weight:600;color:#17365D;")
        root.addWidget(title)
        note = QLabel("① 输入设计描述  →  ② 百炼抽取参数  →  ③ 本地检查  →  ④ 原算法试算\n"
                      "只预览与导出，不回填产品、不写数据库。DL等工程数值必须在描述中明确给出。")
        note.setWordWrap(True)
        root.addWidget(note)
        controls = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["百炼真实解析", "固定样例演示（不联网）"])
        controls.addWidget(self.mode)
        self.settings_button = QPushButton("百炼设置")
        self.settings_button.clicked.connect(self.open_settings)
        controls.addWidget(self.settings_button)
        self.sample_button = QPushButton("填入示例描述")
        self.sample_button.clicked.connect(lambda: self.input.setPlainText(SAMPLE_TEXT))
        controls.addWidget(self.sample_button)
        controls.addStretch()
        root.addLayout(controls)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("用自己的话描述参数，例如：AEU，DN1300，2管程，换热管外径25毫米，管长4.5米……")
        self.input.setMinimumHeight(95)
        self.input.setMaximumHeight(140)
        self.input.textChanged.connect(self._invalidate)
        root.addWidget(self.input)
        actions = QHBoxLayout()
        self.extract_button = QPushButton("开始抽取（调用1次API）")
        self.extract_button.setStyleSheet("background:#1F5D85;color:white;padding:8px 18px;")
        self.extract_button.clicked.connect(self.extract)
        actions.addWidget(self.extract_button)
        self.preview_button = QPushButton("本地布管试算（不调用API）")
        self.preview_button.setEnabled(False)
        self.preview_button.clicked.connect(self.preview)
        actions.addWidget(self.preview_button)
        self.export_button = QPushButton("导出JSON")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_json)
        actions.addWidget(self.export_button)
        actions.addStretch()
        root.addLayout(actions)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.output_tabs = QTabWidget()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["参数名", "抽取值", "单位", "原文依据", "当前页面值（只读对照）"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.output_tabs.addTab(self.table, "结构化参数")
        self.json_view = QPlainTextEdit()
        self.json_view.setReadOnly(True)
        self.output_tabs.addTab(self.json_view, "JSON")
        self.view = QGraphicsView()
        self.output_tabs.addTab(self.view, "布管预览")
        root.addWidget(self.output_tabs, 1)
        self.checks = QTextEdit()
        self.checks.setReadOnly(True)
        self.checks.setMaximumHeight(110)
        root.addWidget(self.checks)
        self.status = QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.refresh_config_status()

    @property
    def is_busy(self):
        return self.worker is not None

    def context(self):
        return self.context_provider() if self.context_provider else {}

    def refresh_config_status(self):
        ready = APIConfig.load().configured
        self.status.setText("百炼已配置。点击开始抽取才会联网；请求仅发送输入的描述及字段约定。"
                            if ready else "尚未配置百炼。可先选择固定样例演示；真实解析请点击“百炼设置”。")

    def open_settings(self):
        if BailianSettings(self).exec_() == QDialog.Accepted:
            self.refresh_config_status()

    def _mode_changed(self):
        self._invalidate()
        self.extract_button.setText("开始抽取（调用1次API）" if self.mode.currentIndex() == 0
                                    else "展示固定样例（不联网）")

    def _invalidate(self):
        self.result = None
        self.preview_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.table.setRowCount(0)
        self.json_view.clear()
        self.checks.clear()
        self.view.setScene(None)
        if hasattr(self, "status"):
            self.status.setText("输入或模式已变化，请重新抽取。")

    def extract(self):
        if self.is_busy:
            return
        text = self.input.toPlainText().strip()
        self._invalidate()
        if self.mode.currentIndex() == 1:
            if text != SAMPLE_TEXT:
                self.status.setText("固定样例不解析任意输入。请点击“填入示例描述”，或切换百炼真实解析。")
                return
            result = validate_extraction(SAMPLE_RESPONSE, text)
            result.update({"source_text": text, "mode": "固定样例演示（不联网，不是真实AI响应）",
                           "model": None, "usage": {}})
            self.display_result(result)
            return
        config = APIConfig.load()
        if not config.configured:
            self.status.setText("请先点击“百炼设置”，粘贴密钥后再开始抽取。")
            return
        if not text or len(text) > 12000:
            self.status.setText("请输入1到12000字的设计描述。")
            return
        self._request_text, self._request_context = text, self.context()
        app = QApplication.instance()
        if not getattr(app, '_tube_ai_shutdown_connected', False):
            app.aboutToQuit.connect(_wait_for_workers)
            app._tube_ai_shutdown_connected = True
        # 网络任务由应用拥有，父产品窗口被销毁时不会销毁运行中的QThread。
        self.worker = ExtractionWorker(config, text, app)
        _ACTIVE_WORKERS.add(self.worker)
        worker = self.worker
        worker.finished.connect(lambda: _finish_worker(worker))
        ancestor = self
        while ancestor is not None:
            ancestor.installEventFilter(self)
            ancestor = ancestor.parentWidget()
        self.worker.succeeded.connect(self._received)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self.extract_button.setEnabled(False)
        self.settings_button.setEnabled(False)
        self.mode.setEnabled(False)
        self.sample_button.setEnabled(False)
        self.status.setText("正在请求百炼，最长等待45秒；界面仍可操作。不会自动重试。")
        self.worker.start()

    def _received(self, result):
        if self.input.toPlainText().strip() != self._request_text or self.context() != self._request_context:
            self.status.setText("请求期间描述或产品页面已变化，旧结果已丢弃，请重新抽取。")
            return
        self.display_result(result)

    def _failed(self, message):
        self.status.setText(message)

    def _finished(self):
        self.worker = None
        self.extract_button.setEnabled(True)
        self.settings_button.setEnabled(True)
        self.mode.setEnabled(True)
        self.sample_button.setEnabled(True)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Close and self.is_busy:
            self.status.setText("百炼请求仍在进行，请等待返回或超时后再关闭产品窗口。")
            event.ignore()
            return True
        return super().eventFilter(watched, event)

    def display_result(self, result):
        self.result = result
        current = self.context().get("parameters", {})
        self.table.setRowCount(len(result["evidence"]))
        for row, item in enumerate(result["evidence"]):
            values = [item["name"], item["value"], item["unit"], item["evidence"], current.get(item["name"], "—")]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))
        self._update_json()
        lines = ["本地检查（仅本Demo覆盖的字段与关系，不是完整规范校核）："]
        lines += ["冲突：" + item for item in result["issues"]]
        lines += ["待澄清：" + item["text"] + " — " + item["reason"] for item in result["unresolved"]]
        if result["missing"]:
            lines.append("试算待补充：" + "、".join(result["missing"]))
        if not result["issues"] and not result["unresolved"]:
            lines.append("已抽取字段的类型、单位、原文引用及已覆盖关系检查未发现问题；请人工核对语义。")
        self.checks.setPlainText("\n".join(lines))
        self.preview_button.setEnabled(True)
        self.export_button.setEnabled(True)
        usage = result.get("usage", {})
        self.status.setText(f"{result['mode']} · 抽取{len(result['parameters'])}项 · "
                            f"输入token={usage.get('prompt_tokens', '—')} / 输出token={usage.get('completion_tokens', '—')}")
        self.output_tabs.setCurrentIndex(0)

    def _update_json(self):
        self.json_view.setPlainText(json.dumps(self.result, ensure_ascii=False, indent=2, allow_nan=False))

    def preview(self):
        if self.result is None:
            return
        try:
            packed = preview_layout(self.result)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        scene = QGraphicsScene(self.view)
        diameter = float(self.result['parameters']['布管限定圆 DL'])
        d = float(self.result['parameters']['换热管外径 do'])
        scene.addEllipse(-diameter / 2, -diameter / 2, diameter, diameter, QPen(QColor('#73879B')))
        for x, y in packed['centers']:
            scene.addEllipse(x-d/2, y-d/2, d, d, QPen(QColor('#345D85')))
        scene.setSceneRect(-diameter*.54, -diameter*.54, diameter*1.08, diameter*1.08)
        old_scene = self.view.scene()
        self.view.setScene(scene)
        if old_scene is not None:
            old_scene.deleteLater()
        self.output_tabs.setCurrentIndex(2)
        self.view.fitInView(scene.sceneRect(), Qt.KeepAspectRatio)
        self.result['preview'] = {"tube_hole_count": packed['tube_count'], "note": packed['note']}
        self._update_json()
        self.status.setText(f"原算法试算：{packed['tube_count']}个管孔。{packed['note']}")

    def export_json(self):
        if self.result is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出结构化参数", "管束参数抽取.json", "JSON (*.json)")
        if path:
            try:
                Path(path).write_text(json.dumps(self.result, ensure_ascii=False, indent=2,
                                                allow_nan=False), encoding="utf-8")
                self.status.setText("JSON已导出（包含原始描述与抽取结果，不包含API Key）。")
            except OSError:
                self.status.setText("导出失败，请换一个可写目录。")
