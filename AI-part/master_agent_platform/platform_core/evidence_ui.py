"""Original module windows hosted by the independent Qt platform."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from PyQt5.QtCore import QEvent, QPoint, QProcess, QProcessEnvironment, QRect, QSize, QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QWindow
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                             QScrollArea, QTabWidget, QVBoxLayout, QWidget)

from .fabric import BASE
from .private_database import atomic_json
from .embedded_view import PROTOCOL, host_minimum, EmbeddedHostViewport
from .ui_theme import WorkspaceComboBox

LABELS = {"project": "项目 / 产品识别", "conditions": "条件输入", "elements": "元件材料定义",
          "nozzles": "管口定义", "tube_bundle": "管束设计"}


class EvidenceJob(QThread):
    complete = pyqtSignal(object)
    failure = pyqtSignal(str)
    message = pyqtSignal(str)

    def __init__(self, workspace, request, parent=None):
        super().__init__(parent)
        self.workspace, self.request = workspace, request

    def run(self):
        try:
            if self.request[0] == "prepare":
                from .evidence_data import EvidenceData
                value = EvidenceData(self.workspace).prepare(*self.request[1:])
            else:
                from .orchestrator import Orchestrator
                value = Orchestrator(self.workspace, self.message.emit).import_evidence(self.request[1])
            self.complete.emit(value)
        except Exception as exc:
            self.failure.emit(str(exc))


class EvidencePanel(QWidget):
    updated = pyqtSignal(dict)
    message = pyqtSignal(str)
    busy_changed = pyqtSignal(bool)

    def __init__(self, workspace, parent=None):
        super().__init__(parent)
        self.workspace = Path(workspace)
        self.summary = None
        self.job = None
        self.external_busy = False
        self.sessions = []
        self.seen = set()
        self.queue = []
        layout = QVBoxLayout(self)
        help_text = QLabel("选择任意产品打开原模块工作台，继续查看依据、编辑、校验及写入。原界面连接平台独立数据副本；点击“保存到平台并继续审核”回流结果。")
        help_text.setWordWrap(True)
        self.help_text = help_text
        layout.addWidget(help_text)
        row = QHBoxLayout()
        self.product = WorkspaceComboBox()
        self.product.setAccessibleName("选择产品")
        self.module = WorkspaceComboBox()
        self.module.setAccessibleName("选择模块")
        for key, label in LABELS.items(): self.module.addItem(label, key)
        self.open_button = QPushButton("打开原模块工作台")
        self.open_button.clicked.connect(self.open_current)
        row.addWidget(self.product, 2)
        row.addWidget(self.module, 1)
        row.addWidget(self.open_button)
        layout.addLayout(row)
        self.status = QLabel("任务结果生成后，可打开对应产品的原模块界面。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.windows = QTabWidget()
        self.windows.setTabsClosable(True)
        self.windows.tabCloseRequested.connect(self.close_tab)
        layout.addWidget(self.windows, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(300)
        self.refresh_controls()

    @property
    def busy(self):
        return self.job is not None

    def set_summary(self, summary):
        selected = self.product.currentData()
        self.summary = summary
        self.product.clear()
        for product in summary.get("products", []):
            if product.get("draft_path"):
                self.product.addItem(" · ".join(str(product.get(k) or "") for k in ("tag", "name", "form")), product["id"])
        index = self.product.findData(selected)
        if index >= 0: self.product.setCurrentIndex(index)
        self.refresh_controls()

    def set_busy(self, value):
        self.external_busy = value
        self.refresh_controls()

    def refresh_controls(self):
        self.open_button.setEnabled(bool(self.summary and self.product.count()) and not self.busy and not self.external_busy)

    def start_job(self, request, success, failure):
        self.job = EvidenceJob(self.workspace, request, self)
        self.job.message.connect(self.message)
        self.job.complete.connect(success)
        self.job.failure.connect(failure)
        self.job.finished.connect(self.job_finished)
        self.busy_changed.emit(True)
        self.refresh_controls()
        self.job.start()

    def job_finished(self):
        self.job.deleteLater()
        self.job = None
        self.busy_changed.emit(False)
        self.refresh_controls()

    def open_current(self):
        if not self.open_button.isEnabled(): return
        for session in self.sessions:
            info = session["info"]
            if (info["run_id"], info["product_id"], info["module"]) == (self.summary["run_id"], self.product.currentData(), self.module.currentData()):
                self.windows.setCurrentWidget(session["page"])
                self.status.setText("已切换到当前打开的原工作台。")
                return
        request = ("prepare", self.summary["run_id"], self.product.currentData(), self.module.currentData())
        self.status.setText("正在准备独立产品上下文和原模块窗口…")
        self.start_job(request, self.launch, self.failed)

    def failed(self, message):
        self.status.setText(message)
        self.message.emit(message)

    def launch(self, path):
        path = Path(path)
        info = json.loads(path.read_text(encoding="utf-8"))
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        placeholder = QLabel("正在载入模块数据与功能…")
        layout.addWidget(placeholder)
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.MergedChannels)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONIOENCODING", "utf-8")
        environment.insert("ENGINEERING_UI_SCALE", str(getattr(self, 'ui_scale', 1.0)))
        process.setProcessEnvironment(environment)
        session = dict(process=process, path=path.parent, page=page, layout=layout, placeholder=placeholder,
                       info=info, buffer=b"", container=None, foreign=None, ready=False)
        self.sessions.append(session)
        product = info["products"][info["product_id"]]["product"]
        module_label = self.module.itemText(self.module.findData(info["module"])) or LABELS[info["module"]]
        index = self.windows.addTab(page, (product.get("设备位号") or "产品") + " · " + module_label)
        self.windows.setCurrentIndex(index)
        process.readyReadStandardOutput.connect(lambda: self.read_output(session))
        process.finished.connect(lambda code, status: self.process_finished(session, code))
        process.errorOccurred.connect(lambda error: self.failed("模块服务启动异常：" + process.errorString()))
        process.start(sys.executable, [str(getattr(self, "runtime", BASE / "evidence_runtime.py")), str(path), "--embed"])

    def read_output(self, session):
        chunk = bytes(session["process"].readAllStandardOutput())
        with (session["path"] / "runtime.log").open("ab") as stream: stream.write(chunk)
        session["buffer"] += chunk
        while b"\n" in session["buffer"]:
            line, session["buffer"] = session["buffer"].split(b"\n", 1)
            text = line.decode("utf-8", errors="replace").strip()
            marker = text.find("@@EVIDENCE@@")
            if marker < 0: continue
            try: value = json.loads(text[marker + len("@@EVIDENCE@@"):])
            except ValueError: continue
            if value["kind"] == "ready":
                session['view_metrics'] = value.get('view') or {}
                self.attach(session, value["handle"])
            elif value["kind"] == "attached":
                session["attached"] = True
                # 子窗口已嵌入并显示，此刻才撤掉占位符，衔接无空白。
                placeholder = session.get("placeholder")
                if placeholder is not None:
                    placeholder.hide()
            elif value['kind'] == 'view-metrics': self.update_view_metrics(session, value)
            elif value["kind"] == "module-result" and hasattr(self, "reply"):
                self.reply.emit(value.get("text", ""))
            elif value["kind"] in ("failed", "operation-error"):
                self.failed(value.get("error") or value.get("message"))

    def attach(self, session, handle):
        if session["ready"]: return
        if os.name == "nt" and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            coordinated = session.get('view_metrics', {}).get('protocol') == PROTOCOL
            foreign = None
            if coordinated:
                container = QWidget(session['page'])
                container.setAttribute(Qt.WA_NativeWindow)
                container.setAttribute(Qt.WA_StyledBackground)
                container.setStyleSheet('background:#f7f9fd;')
            else:
                foreign = QWindow.fromWinId(handle)
                try:
                    foreign.setMinimumSize(QSize(0, 0))
                except Exception:
                    pass
                container = QWidget.createWindowContainer(foreign, session["page"])
            container.setFocusPolicy(Qt.StrongFocus)
            container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            minimum = getattr(self, "embedded_minimum", (520, 360))
            if session.get('view_metrics', {}).get('protocol') == PROTOCOL:
                container.setMinimumSize(host_minimum(session['view_metrics'], self.devicePixelRatioF(), minimum))
            else:
                container.setMinimumSize(*minimum)
            scroll = QScrollArea()
            scroll.setFrameShape(QScrollArea.NoFrame)
            scroll.setStyleSheet('QScrollArea{background:#f7f9fd;border:0;}')
            scroll.setWidgetResizable(True)
            scroll.setWidget(container)
            session["layout"].addWidget(scroll, 1)
            session.update(container=container, foreign=foreign, scroll=scroll)
            if coordinated:
                publisher = EmbeddedHostViewport(container, session['path']/'viewport.json',
                    lambda: getattr(self, 'ui_scale', 1.0), self.failed)
                session['viewport_publisher'] = publisher
                publisher.publish()
            # 占位符延后到子进程 emit "attached"（子窗口已嵌入并显示）时再隐藏，
            # 避免出现「占位消失但子窗口还没 show」的中间空白/闪动。
            # 详见 read_output 里 kind == "attached" 分支。
            # 容器尺寸变化时同步外部窗口几何：最大化/还原后不会再留下旧位置的残影。
            container.installEventFilter(self)
        else:
            session["placeholder"].setText("当前环境不支持窗口嵌入，统一模块编辑器以独立窗口显示；保存结果仍返回本平台。")
        session["ready"] = True
        command = dict(action='attached')
        if session.get('container') and session.get('view_metrics', {}).get('protocol') == PROTOCOL:
            command['parent_handle'] = int(session['container'].winId())
        atomic_json(session["path"] / "command.json", command)
        self.status.setText("模块数据已载入，可继续编辑、校验和保存。")
        self.message.emit("已载入模块：" + LABELS[session["info"]["module"]])

    def eventFilter(self, obj, event):  # noqa: N802 - Qt API
        if event.type() == QEvent.Resize:
            session = next((s for s in self.sessions if s.get("container") is obj), None)
            if session and session.get("foreign") is not None:
                try:
                    session["foreign"].setGeometry(QRect(QPoint(0, 0), obj.size()))
                except Exception:
                    pass
        return super().eventFilter(obj, event)

    def update_view_metrics(self, session, value):
        if value.get('protocol') != PROTOCOL: return
        session['view_metrics'] = value
        container = session.get('container')
        if container is None: return
        minimum = host_minimum(value, self.devicePixelRatioF(), getattr(self, 'embedded_minimum', (1180, 780)))
        if container.minimumSize() != minimum: container.setMinimumSize(minimum)

    def close_tab(self, index):
        page = self.windows.widget(index)
        session = next((s for s in self.sessions if s["page"] is page), None)
        if session:
            if any(s is session for s, path in self.queue) or self.busy:
                self.failed("正在保存或审核，请等待回执后关闭编辑器。")
                return
            atomic_json(session["path"] / "command.json", dict(action="close"))
            self.status.setText("正在保存工作副本并关闭；请先完成当前对话框中的操作。")

    def process_finished(self, session, code):
        self.read_output(session)
        # Detach the foreign handle before deleting its host widgets.
        if session["foreign"]:
            session["foreign"].setParent(None)
        index = self.windows.indexOf(session["page"])
        if index >= 0: self.windows.removeTab(index)
        session["page"].deleteLater()
        self.sessions.remove(session)
        session["process"].deleteLater()
        self.status.setText("原模块窗口已关闭，工作副本保留在会话目录。" if code == 0 else "原模块异常退出，请查看会话 runtime.log。")

    def poll(self):
        for session in list(self.sessions):
            path = session["path"] / "update.json"
            if not path.is_file(): continue
            try: value = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError): continue
            if value["id"] not in self.seen:
                self.seen.add(value["id"])
                self.queue.append((session, path))
        if self.job is not None or self.external_busy or not self.queue: return
        session, path = self.queue.pop(0)
        event = json.loads(path.read_text(encoding="utf-8"))
        def accepted(summary):
            product = next(p for p in summary["products"] if p["id"] == event["product_id"])
            atomic_json(session["path"] / "ack.json", dict(id=event["id"], ok=True, sha256=product["draft_data_sha256"], product_versions={p["id"]: p.get("draft_data_sha256") for p in summary["products"] if p.get("draft_data_sha256")}))
            self.status.setText("模块结果已保存，Agent loop 已复审；其它旧版本编辑器需重新载入后编辑。")
            self.updated.emit(summary)
        def rejected(message):
            atomic_json(session["path"] / "ack.json", dict(id=event["id"], ok=False, error=message))
            self.failed(message)
        self.start_job(("import", path), accepted, rejected)

    def request_close_all(self):
        if self.busy or self.queue: return False
        for session in self.sessions:
            path = session["path"] / "command.json"
            if not path.exists(): atomic_json(path, dict(action="close"))
        return not self.sessions
