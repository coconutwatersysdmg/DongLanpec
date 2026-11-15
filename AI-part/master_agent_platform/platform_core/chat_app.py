"""Chat-led engineering platform with integrated module results and data space."""
from __future__ import annotations

import json
from pathlib import Path
import threading
import time
import uuid
import sqlite3
import re
import datetime as dt

from PyQt5.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (QWidget, QMainWindow, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QPushButton, QListWidget, QTextBrowser, QPlainTextEdit, QScrollArea,
    QStackedWidget, QTreeWidget, QTreeWidgetItem, QLineEdit, QFileDialog, QMessageBox, QToolButton)

from .fabric import BASE, Fabric
from .orchestrator import Orchestrator
from .presentation import ExecutionPanel, DataSpacePanel
from .run_view import duration
from .module_panel import ModulePanel


class Worker(QThread):
    message = pyqtSignal(str)
    complete = pyqtSignal(dict)
    failure = pyqtSignal(str)

    def __init__(self, inputs, knowledge, parent=None, review_request=None, goal="", factory=None):
        super().__init__(parent)
        self.inputs, self.knowledge, self.review_request, self.goal = inputs, knowledge, review_request, goal
        self.factory = factory or Orchestrator
        self.cancelled = threading.Event()
        self.engine = None

    def run(self):
        try:
            self.engine = self.factory(BASE / "workspace", self.message.emit, self.cancelled)
            if self.review_request:
                value = self.review_request
                result = self.engine.recheck_run(value["run_id"]) if value.get("automatic") else self.engine.resume_review(value["run_id"], value["answers"], value["expected"])
            else:
                result = self.engine.run(self.inputs, self.knowledge, user_goal=self.goal)
            self.complete.emit(result)
        except Exception as exc: self.failure.emit(str(exc))


class DatabaseWorker(QThread):
    message = pyqtSignal(str)
    complete = pyqtSignal(dict)
    failure = pyqtSignal(str)

    def __init__(self, workspace, parent=None):
        super().__init__(parent)
        self.workspace = workspace

    def run(self):
        try:
            from .bundled_database import ensure_database
            config = ensure_database(self.workspace, self.message.emit)
            self.complete.emit(dict(port=config["port"]))
        except Exception as exc: self.failure.emit(str(exc))


STYLE = """
QWidget{font-family:'Microsoft YaHei';font-size:13px;color:#26354a;}
QMainWindow{background:#fff;} QWidget#sidebar{background:#f5f7fa;border-right:1px solid #e8edf3;}
QLabel#brand{font-size:19px;font-weight:700;color:#16335b;} QLabel#sectionTitle{font-size:20px;font-weight:600;}
QLabel#muted{color:#8390a2;} QLabel#badge{color:#3467a7;background:#edf4ff;padding:5px 10px;border-radius:9px;}
QPushButton{background:#fff;border:1px solid #e0e7ef;border-radius:8px;padding:9px 13px;}
QPushButton:hover{background:#edf4ff;color:#2563eb;border-color:#b6cff7;}
QPushButton:disabled{color:#9ba6b6;background:#f5f7fa;}
QPushButton#nav{text-align:left;background:transparent;border:0;padding:12px 14px;}
QPushButton#send{background:#2563eb;color:#fff;border:0;font-weight:600;}
QFrame#composer{background:#f8fafc;border:1px solid #dfe6ef;border-radius:15px;}
QPlainTextEdit#prompt{border:0;background:transparent;font-size:14px;padding:6px;}
QTextBrowser,QPlainTextEdit,QTreeWidget,QListWidget{background:#fff;border:1px solid #e5ebf2;border-radius:8px;padding:8px;}
QTextBrowser#conversation{border:0;} QFrame#userBubble{background:#edf4ff;border-radius:12px;}
QFrame#assistantBubble{background:#fff;border:1px solid #e8edf4;border-radius:12px;}
QTabWidget::pane{border:1px solid #e5ebf2;border-radius:8px;} QTabBar::tab{padding:9px 14px;background:#f8fafc;}
QTabBar::tab:selected{background:#fff;color:#2563eb;} QComboBox{padding:8px;border:1px solid #dfe6ef;border-radius:7px;background:#fff;}
QScrollArea{border:0;background:#fff;} QWidget#threadSurface{background:#fff;} QGraphicsView{border:1px solid #e5ebf2;border-radius:8px;}
"""


class ChatWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("工程 Agent · 数据空间与产品生成")
        self.resize(1480, 960)
        self.workspace = BASE / "workspace"
        self.fabric = Fabric(self.workspace)
        self.inputs, self.knowledge, self.worker = [], [], None
        self.database_worker, self.close_after_database = None, False
        self.last_result, self.last_output, self.active_run_id = None, None, None
        self.review_editors, self.messages = [], []
        self.bubbles = []
        self.chat_id = uuid.uuid4().hex
        self.started_at = None
        self.elapsed_value = 0
        self.history_ids = []
        self.pending_new_chat = False
        self.current_section = 0
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(230)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 25, 16, 18)
        brand = QLabel("工程 Agent")
        brand.setObjectName("brand")
        side.addWidget(brand)
        subtitle = QLabel("产品数据 · 从输入到审核")
        subtitle.setObjectName("muted")
        side.addWidget(subtitle)
        side.addSpacing(20)
        self.new_chat_button = QPushButton("＋  新建对话")
        self.new_chat_button.clicked.connect(self.new_chat)
        side.addWidget(self.new_chat_button)
        self.nav_buttons = []
        for index, label in enumerate(("对话", "模块结果", "数据空间", "运行记录", "待审核")):
            button = QPushButton(label)
            button.setObjectName("nav")
            button.clicked.connect(lambda _, i=index: self.navigate(i))
            side.addWidget(button)
            self.nav_buttons.append(button)
        side.addSpacing(20)
        label = QLabel("最近任务")
        label.setObjectName("muted")
        side.addWidget(label)
        self.history = QListWidget()
        self.history.setStyleSheet("background:transparent;border:0;padding:0;")
        self.history.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.history.setTextElideMode(Qt.ElideRight)
        self.history.itemClicked.connect(self.select_history)
        side.addWidget(self.history, 1)
        load = QPushButton("载入任务结果")
        load.clicked.connect(self.load_result)
        side.addWidget(load)
        local = QLabel("独立数据空间\n本地规则与模块服务")
        local.setObjectName("muted")
        side.addWidget(local)
        root.addWidget(sidebar)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(28, 18, 28, 20)
        header = QHBoxLayout()
        self.page_title = QLabel("对话")
        self.page_title.setObjectName("sectionTitle")
        header.addWidget(self.page_title, 1)
        self.clock_label = QLabel("尚未运行")
        self.clock_label.setObjectName("muted")
        header.addWidget(self.clock_label)
        self.data_badge = QLabel("数据空间 · 本地托管")
        self.data_badge.setObjectName("badge")
        header.addWidget(self.data_badge)
        body_layout.addLayout(header)
        self.state = QLabel("等待提交文件")
        self.state.setObjectName("muted")
        body_layout.addWidget(self.state)
        self.pages = QStackedWidget()
        body_layout.addWidget(self.pages, 1)
        root.addWidget(body, 1)
        self.build_chat()
        self.module_panel = ModulePanel(self.workspace, self)
        self.evidence = self.module_panel  # internal lifecycle compatibility only
        self.module_panel.updated.connect(self.module_updated)
        self.module_panel.message.connect(self.append_log)
        self.module_panel.busy_changed.connect(self.controls)
        self.module_panel.reply.connect(lambda text: self.bubble("assistant", text[:2400] + ("\n更多结果见模块面板。" if len(text)>2400 else "")))
        self.module_card, self.module_toggle = self.inline_card("模块结果", self.module_panel)
        self.pages.addWidget(QWidget())  # Navigation index remains a chat anchor.
        self.data_space = DataSpacePanel()
        self.data_space.open_file.connect(lambda path: QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
        self.pages.addWidget(self.data_space)
        execution_page = QWidget()
        execution_layout = QVBoxLayout(execution_page)
        execution_layout.setContentsMargins(0, 0, 0, 0)
        self.execution = ExecutionPanel()
        execution_layout.addWidget(self.execution, 1)
        execution_layout.addWidget(QLabel("调用事件"))
        self.log = QTextBrowser()
        self.log.setMaximumHeight(90)
        execution_layout.addWidget(self.log)
        execution_page.setFixedHeight(860)
        self.execution_card, self.execution_toggle = self.inline_card("运行记录", execution_page)
        self.pages.addWidget(QWidget())
        self.build_review()
        self.setStyleSheet(STYLE)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(600)
        self.load_history()
        self.navigate(0)

    def make_orchestrator(self, *args, **kwargs): return Orchestrator(*args, **kwargs)

    def prepare_database(self):
        if self.database_worker or self.worker or self.module_panel.busy: return
        self.data_badge.setText("自带数据库准备中…")
        self.state.setText("正在准备本机独立数据库，首次启动会自动导入基础数据。")
        self.database_worker = DatabaseWorker(self.workspace, self)
        self.database_worker.message.connect(self.append_log)
        self.database_worker.complete.connect(self.database_ready)
        self.database_worker.failure.connect(self.database_failed)
        self.database_worker.finished.connect(self.database_finished)
        self.module_panel.set_busy(True)
        self.controls()
        self.database_worker.start()

    def database_ready(self, result):
        self.data_badge.setText("数据空间与独立库已就绪")
        if not self.last_result:
            self.state.setText("数据库已准备完成，请加入文件并发送任务。")

    def database_failed(self, message):
        self.data_badge.setText("数据库准备未完成")
        self.state.setText("数据库准备未完成 · 具体原因见下方")
        self.welcome.hide()
        self.bubble("assistant", "自带数据库准备未完成："+message)

    def database_finished(self):
        self.database_worker.deleteLater()
        self.database_worker = None
        self.module_panel.set_busy(False)
        self.controls()
        if self.close_after_database: QTimer.singleShot(0, self.close)

    def build_chat(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 0, 4, 0)
        scroll = QScrollArea()
        self.chat_scroll = scroll
        scroll.setWidgetResizable(True)
        conversation = QWidget()
        conversation.setObjectName("threadSurface")
        self.chat_layout = QVBoxLayout(conversation)
        self.chat_layout.setContentsMargins(12, 20, 12, 20)
        self.chat_layout.setSpacing(18)
        self.welcome = QLabel("准备好你的工程文件\n\n描述要整理的产品数据，加入输入文件与知识资料。\n平台会识别全部产品、分发任务，并把必需缺项集中送审。")
        self.welcome.setAlignment(Qt.AlignCenter)
        self.welcome.setStyleSheet("font-size:18px;color:#61728a;padding:38px;")
        self.chat_layout.addWidget(self.welcome)
        self.report = QTextBrowser()
        self.report.setObjectName("conversation")
        self.report.setMinimumHeight(220)
        self.report_frame = QFrame()
        self.report_frame.setObjectName("assistantBubble")
        report_layout = QVBoxLayout(self.report_frame)
        report_title = QLabel("工程 Agent · 任务结果")
        report_title.setStyleSheet("font-weight:600;font-size:14px;padding:5px;")
        report_layout.addWidget(report_title)
        report_layout.addWidget(self.report)
        self.report_frame.hide()
        self.chat_layout.addWidget(self.report_frame)
        self.chat_layout.addStretch()
        scroll.setWidget(conversation)
        layout.addWidget(scroll, 1)
        quick = QHBoxLayout()
        for label, index in (("查看模块结果", 1), ("查看数据空间", 2), ("查看执行图", 3)):
            button = QPushButton(label)
            button.clicked.connect(lambda _, i=index: self.navigate(i))
            quick.addWidget(button)
        quick.addStretch()
        self.open_output = QPushButton("打开结果目录")
        self.open_output.setEnabled(False)
        self.open_output.clicked.connect(self.show_output)
        quick.addWidget(self.open_output)
        layout.addLayout(quick)
        self.attachments = QLabel("尚未选择文件")
        self.attachments.setObjectName("muted")
        self.attachments.setWordWrap(True)
        layout.addWidget(self.attachments)
        composer = QFrame()
        composer.setObjectName("composer")
        compose = QVBoxLayout(composer)
        compose.setContentsMargins(12, 10, 12, 10)
        self.prompt = QPlainTextEdit()
        self.prompt.setObjectName("prompt")
        self.prompt.setPlaceholderText("例如：整理这些输入文件中的全部产品，生成计算前数据，优先自动审核缺项…")
        self.prompt.setMaximumHeight(90)
        compose.addWidget(self.prompt)
        row = QHBoxLayout()
        for label, callback in (("＋ 输入文件", self.add_inputs), ("＋ 知识资料", self.add_knowledge), ("清空附件", self.clear_selection)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        row.addStretch()
        self.cancel = QPushButton("停止")
        self.cancel.clicked.connect(self.cancel_task)
        self.cancel.setEnabled(False)
        row.addWidget(self.cancel)
        self.begin = QPushButton("发送并执行  ↑")
        self.begin.setObjectName("send")
        self.begin.clicked.connect(self.send)
        row.addWidget(self.begin)
        compose.addLayout(row)
        layout.addWidget(composer)
        hint = QLabel("当前输出为可追溯的审核草稿；完整产品包和正式计算输入仍需完成工程规则与映射。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.pages.addWidget(page)

    def inline_card(self, title, content):
        card = QFrame()
        card.setObjectName("assistantBubble")
        layout = QVBoxLayout(card)
        toggle = QToolButton()
        toggle.setText(title)
        toggle.setCheckable(True)
        toggle.setChecked(True)
        toggle.setArrowType(Qt.DownArrow)
        toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toggle.setStyleSheet("font-weight:600;font-size:15px;padding:8px;border:0;")
        def expanded(checked):
            content.setVisible(checked)
            toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        toggle.toggled.connect(expanded)
        layout.addWidget(toggle)
        layout.addWidget(content)
        self.chat_layout.insertWidget(self.chat_layout.count()-1, card)
        card.hide()
        return card, toggle

    def scroll_to_card(self, card):
        QTimer.singleShot(0, lambda: self.chat_scroll.verticalScrollBar().setValue(max(0, card.y()-12)))

    def build_review(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        title = QLabel("必需参数审核")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("只列出自动循环后仍需人工处理的必需参数。其它缺项继续暂缓，保存后重新审核。"))
        self.review_tree = QTreeWidget()
        self.review_tree.setHeaderLabels(["产品 / 参数", "范围", "单位", "审核问题", "审核值"])
        self.review_tree.setColumnWidth(0, 230)
        self.review_tree.setColumnWidth(3, 280)
        layout.addWidget(self.review_tree, 1)
        row = QHBoxLayout()
        self.submit_review = QPushButton("提交审核并继续")
        self.submit_review.setEnabled(False)
        self.submit_review.clicked.connect(self.submit_answers)
        row.addWidget(self.submit_review)
        self.recheck_button = QPushButton("继续自动复查")
        self.recheck_button.setEnabled(False)
        self.recheck_button.clicked.connect(self.recheck_current)
        row.addWidget(self.recheck_button)
        row.addStretch()
        layout.addLayout(row)
        self.pages.addWidget(panel)

    def navigate(self, index):
        self.current_section = index
        self.pages.setCurrentIndex(0 if index in (1, 3) else index)
        self.page_title.setText("对话" if index in (0, 1, 3) else ("对话", "模块结果", "数据空间", "运行记录", "待审核")[index])
        for i, button in enumerate(self.nav_buttons):
            button.setStyleSheet("background:#e8effa;color:#245bac;font-weight:600;" if i == index else "")
        if index == 2 and self.active_run_id:
            self.data_space.bind(self.workspace, self.active_run_id)
        if index in (1, 3):
            card, toggle = (self.module_card, self.module_toggle) if index == 1 else (self.execution_card, self.execution_toggle)
            card.show()
            toggle.setChecked(True)
            if index == 3: self.execution.refresh(True)
            self.scroll_to_card(card)

    def bubble(self, role, text, persist=True):
        frame = QFrame()
        frame.setObjectName("userBubble" if role == "user" else "assistantBubble")
        layout = QVBoxLayout(frame)
        title = QLabel("你" if role == "user" else "工程 Agent")
        title.setStyleSheet("font-weight:600;")
        label = QLabel(text)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(title)
        layout.addWidget(label)
        self.chat_layout.insertWidget(self.chat_layout.count()-1, frame)
        self.bubbles.append(frame)
        self.messages.append(dict(role=role, text=text))
        if persist: self.persist_chat()
        QTimer.singleShot(0, lambda: self.chat_scroll.verticalScrollBar().setValue(self.chat_scroll.verticalScrollBar().maximum()))

    def persist_chat(self):
        from .private_database import atomic_json
        path = self.workspace / "conversations" / (self.chat_id + ".json")
        path.parent.mkdir(exist_ok=True)
        atomic_json(path, dict(id=self.chat_id, run_id=self.active_run_id, messages=self.messages))

    def add_inputs(self):
        values, _ = QFileDialog.getOpenFileNames(self, "加入输入文件", "", "工程文件 (*.pdf *.xlsx *.xlsm)")
        self.inputs = list(dict.fromkeys(self.inputs + values))
        self.update_attachments()

    def add_knowledge(self):
        values, _ = QFileDialog.getOpenFileNames(self, "加入知识资料", "", "知识资料 (*.pdf *.docx *.xlsx *.txt *.json)")
        self.knowledge = list(dict.fromkeys(self.knowledge + values))
        self.update_attachments()

    def update_attachments(self):
        self.attachments.setText("　".join(["输入："+Path(p).name for p in self.inputs] + ["知识："+Path(p).name for p in self.knowledge]) or "尚未选择文件")

    def clear_selection(self):
        if self.worker: return
        self.inputs, self.knowledge = [], []
        self.update_attachments()

    def send(self):
        if self.worker or self.database_worker or self.module_panel.busy or self.pending_new_chat: return
        text = self.prompt.toPlainText().strip() or "整理输入中的全部产品，并继续自动审核。"
        self.welcome.hide()
        self.bubble("user", text)
        self.prompt.clear()
        if self.last_result and any(word in text for word in ("数据空间", "知识库")):
            self.navigate(2)
        elif self.last_result and any(word in text for word in ("执行图", "运行记录", "运行逻辑")):
            self.navigate(3)
        elif self.last_result and self.inputs and any(k in text for k in ("重新生成", "重新处理", "新批次")):
            self.start(text)
        elif self.last_result and self.route_module(text):
            pass
        elif self.last_result and any(word in text for word in ("复查", "审核", "继续")):
            self.recheck_current()
        elif self.inputs:
            self.start(text)
        elif any(word in text for word in ("数据空间", "知识库")):
            self.navigate(2)
        elif any(word in text for word in ("执行图", "运行记录", "运行逻辑")):
            self.navigate(3)
        else:
            self.bubble("assistant", "请加入本次输入文件后发送。已有结果可直接进入模块结果、数据空间或运行记录。当前对话用于提交工程任务和导航，模块专业指令在对应结果面板执行。")

    def route_module(self, text):
        module = None
        if any(k in text for k in ("管口", "外伸高度", "密封面")) or re.search(r"\b[NL]\d+\b", text, re.I): module = "nozzles"
        elif any(k in text for k in ("布管", "管板", "管-板", "轴向", "拉杆", "管间距")): module = "tube_bundle"
        elif any(k in text for k in ("材料", "牌号", "供货", "Q345", "Q355")): module = "elements"
        elif any(k in text for k in ("设计压力", "设计温度", "腐蚀裕量", "公称直径", "条件")): module = "conditions"
        elif any(k in text for k in ("新增产品", "删除选中", "产品清单")): module = "project"
        elif self.current_section == 1: module = self.module_panel.module.currentData()
        if not module: return False
        identity = self.module_panel.product.currentData()
        for product in sorted(self.last_result["products"], key=lambda p: len(p.get("tag") or ""), reverse=True):
            if product.get("tag") and product["tag"].lower() in text.lower():
                identity = product["id"]
                break
        self.module_panel.dispatch_command(text, module, identity)
        self.navigate(1)
        return True

    def start(self, goal=""):
        if not self.inputs or self.worker or self.database_worker or self.module_panel.busy or self.pending_new_chat: return
        self.last_result, self.active_run_id = None, None
        self.report_frame.hide()
        self.execution_card.show()
        self.execution_toggle.setChecked(True)
        self.review_tree.clear()
        self.review_editors = []
        self.log.clear()
        self.state.setText("正在接收输入并建立任务")
        self.bubble("assistant", "已接收任务。将文件纳入数据空间，识别全部产品，再按真实类型和型式分发解析与审核。运行记录会同步生成实际执行路径。")
        self.worker = Worker(list(self.inputs), list(self.knowledge), self, goal=goal, factory=self.make_orchestrator)
        self.connect_worker()

    def connect_worker(self):
        self.started_at = time.monotonic()
        self.elapsed_value = 0
        self.module_panel.set_busy(True)
        self.worker.message.connect(self.append_log)
        self.worker.complete.connect(self.on_complete)
        self.worker.failure.connect(self.on_failure)
        self.worker.finished.connect(self.on_finished)
        self.controls()
        self.worker.start()

    def controls(self, *args):
        busy = self.worker is not None or self.database_worker is not None or self.module_panel.busy or self.pending_new_chat
        self.begin.setEnabled(not busy)
        self.cancel.setEnabled(self.worker is not None)
        self.submit_review.setEnabled(bool(self.review_editors) and not busy)
        self.recheck_button.setEnabled(bool(self.last_result) and not busy)
        self.new_chat_button.setEnabled(not self.pending_new_chat)
        self.history.setEnabled(not busy)
        self.module_panel.closing = self.pending_new_chat
        self.module_panel.refresh_controls()

    def append_log(self, message):
        message = str(message).replace("原界面", "模块").replace("原模块", "模块").replace("原窗口", "模块编辑器")
        self.log.append(message)
        if self.worker or self.database_worker: self.state.setText(message)

    def tick(self):
        if self.started_at is not None:
            self.elapsed_value = time.monotonic()-self.started_at
            self.clock_label.setText("本轮运行 " + duration(self.elapsed_value))
        engine = getattr(self.worker, "engine", None) if self.worker else None
        run_id = getattr(engine, "run_id", None)
        if run_id and self.active_run_id != run_id:
            self.active_run_id = run_id
            self.workspace = engine.fabric.home
            self.fabric = engine.fabric
            self.execution.bind(self.workspace, run_id)
        if self.active_run_id:
            try: self.execution.refresh()
            except (OSError, ValueError, sqlite3.DatabaseError): pass
        self.finish_new_chat()

    def on_complete(self, result):
        previous_run = self.active_run_id
        self.last_result, self.active_run_id = result, result["run_id"]
        self.last_output = result.get("run_directory")
        if self.last_output:
            self.workspace = Path(self.last_output).parent.parent
            self.fabric = Fabric(self.workspace)
            self.module_panel.workspace = self.workspace
        if self.worker is None and previous_run != self.active_run_id:
            self.restore_chat(self.active_run_id)
        self.module_panel.set_summary(result)
        self.execution.bind(self.workspace, self.active_run_id)
        recorded = self.fabric.execution(self.active_run_id)
        if recorded["events"]:
            local = dt.timezone(dt.timedelta(hours=8))
            self.log.setPlainText("\n".join(dt.datetime.fromisoformat(e["created"]).astimezone(local).strftime("%Y-%m-%d %H:%M:%S") + "  " + e["message"] for e in recorded["events"]))
        self.data_space.bind(self.workspace, self.active_run_id)
        count = result.get("manual_review_count", 0)
        status = result.get("status", "")
        if status in ("failed", "processing_failed"):
            self.state.setText("本轮处理失败 · 查看运行记录与保留的结果")
        elif status == "partial_processing_failure":
            self.state.setText("部分产品处理失败 · 其它产品结果已保留")
        elif status == "cancelled":
            self.state.setText("本轮已停止 · 已完成的结果与回执保留")
        else:
            self.state.setText("等待人工审核必需参数" if count else "全部产品已完成本轮自动审核 · 仍有暂缓项及能力限制")
        lines = [f"识别产品：{result.get('discovered_products', 0)} 个；已逐台处理：{result.get('processed_products', len(result.get('products', [])))} 个。",
                 f"必需参数待审核 {count} 项；暂缓缺项 {result.get('deferred_count', 0)} 项。", ""]
        if result.get("error"): lines += ["失败原因："+str(result["error"]), ""]
        self.review_tree.clear()
        self.review_editors = []
        for product in result.get("products", []):
            lines.append(" · ".join([product.get("tag", ""), product.get("name", ""), product.get("form") or "型式待识别"]))
            if product.get("status") == "processing_failed":
                lines.extend("处理失败：" + c.get("message", "") for c in product.get("capabilities", []))
            if product.get("manual_review"):
                parent = QTreeWidgetItem([product.get("tag") or product["id"]])
                self.review_tree.addTopLevelItem(parent)
                for gap in product["manual_review"]:
                    row = QTreeWidgetItem([gap["label"], gap.get("side", ""), gap.get("unit", ""), "；".join(gap.get("errors", [])) or gap["reason"], ""])
                    parent.addChild(row)
                    editor = QLineEdit()
                    editor.setPlaceholderText("填写审核值")
                    self.review_tree.setItemWidget(row, 4, editor)
                    self.review_editors.append((product["id"], gap["id"], editor))
                parent.setExpanded(True)
        lines += ["", "能力说明："] + [c["message"] for c in result.get("capabilities", [])]
        lines += ["", "可在模块结果中继续编辑与校验，在数据空间中查看文件和知识关联，在运行记录中查看真实调用路径。"]
        self.report.setPlainText("\n".join(lines))
        self.report.document().setTextWidth(max(500, self.width()-370))
        self.report.setFixedHeight(min(470, max(220, int(self.report.document().size().height()+24))))
        for card in (self.report_frame, self.module_card, self.execution_card):
            self.chat_layout.removeWidget(card)
            self.chat_layout.insertWidget(self.chat_layout.count()-1, card)
        self.report.show()
        self.report_frame.show()
        self.module_toggle.setText(f"模块结果 · {len(result.get('products', []))} 个产品")
        self.module_card.show()
        self.execution_card.show()
        self.scroll_to_card(self.report_frame)
        self.welcome.hide()
        self.open_output.setEnabled(bool(self.last_output))
        self.nav_buttons[4].setText("待审核" + (f"  {count}" if count else ""))
        if self.started_at is None:
            timing = self.fabric.execution(self.active_run_id)
            self.clock_label.setText("累计执行 " + duration(timing["elapsed_seconds"]) if timing["sessions"] else "任务耗时合计 " + duration(timing["task_seconds"]) if timing["tasks"] else "运行时间未记录")
        self.controls()
        self.persist_chat()
        self.load_history()

    def restore_chat(self, run_id):
        records = []
        for path in (self.workspace / "conversations").glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if value.get("run_id") == run_id and value.get("messages"):
                    records.append((path.stat().st_mtime, value))
            except (OSError, ValueError): continue
        for frame in self.bubbles:
            self.chat_layout.removeWidget(frame)
            frame.deleteLater()
        self.bubbles, self.messages = [], []
        if records:
            value = max(records, key=lambda item: item[0])[1]
            self.chat_id = value["id"]
            for message in value["messages"]:
                self.bubble(message.get("role", "assistant"), str(message.get("text", "")), persist=False)

    def on_failure(self, message):
        self.state.setText("本轮已停止 · 修改和回执仍保留")
        self.report.setPlainText(message)
        self.report.show()
        self.report_frame.show()
        self.append_log(message)

    def on_finished(self):
        if self.started_at is not None:
            self.elapsed_value = time.monotonic()-self.started_at
            self.clock_label.setText("本轮用时 " + duration(self.elapsed_value))
        self.started_at = None
        self.worker.deleteLater()
        self.worker = None
        self.module_panel.set_busy(False)
        self.controls()
        self.tick()

    def submit_answers(self):
        if self.worker or self.database_worker or self.module_panel.busy or self.pending_new_chat or not self.last_result: return
        answers = {}
        for product_id, gap_id, editor in self.review_editors:
            if editor.text().strip(): answers.setdefault(product_id, {})[gap_id] = dict(value=editor.text().strip(), reason="用户在统一审核面板填写")
        if not answers: return
        expected = {p["id"]: p["draft_data_sha256"] for p in self.last_result["products"] if p["id"] in answers}
        self.worker = Worker([], [], self, review_request=dict(run_id=self.last_result["run_id"], answers=answers, expected=expected), factory=self.make_orchestrator)
        self.connect_worker()

    def recheck_current(self):
        if self.worker or self.database_worker or self.module_panel.busy or self.pending_new_chat or not self.last_result: return
        self.worker = Worker([], [], self, review_request=dict(run_id=self.last_result["run_id"], automatic=True), factory=self.make_orchestrator)
        self.connect_worker()

    def cancel_task(self):
        if self.worker:
            self.worker.cancelled.set()
            self.state.setText("正在停止，等待当前任务释放")
            self.cancel.setEnabled(False)

    def module_updated(self, result):
        if self.active_run_id == result["run_id"]:
            self.on_complete(result)
            self.module_panel.status.setText("修改已保存，审核记录和数据空间已更新。")

    def load_history(self):
        self.history.clear()
        self.history_ids = []
        with self.fabric.connection() as conn:
            rows = conn.execute("SELECT id,request,summary FROM runs ORDER BY created DESC LIMIT 40").fetchall()
        for row in rows:
            request, summary = json.loads(row["request"]), json.loads(row["summary"])
            if request.get("purpose"): continue
            title = request.get("user_goal") or (Path(request.get("input_files", ["工程任务"])[0]).name if request.get("input_files") else "工程任务")
            self.history.addItem(title[:23] + "\n" + str(len(summary.get("products", []))) + " 个产品 · " + row["id"][:8])
            self.history_ids.append(row["id"])

    def select_history(self, item):
        if self.worker or self.database_worker or self.module_panel.busy or self.pending_new_chat: return
        index = self.history.row(item)
        if index < 0 or index >= len(self.history_ids): return
        path = self.workspace / "runs" / self.history_ids[index] / "summary.json"
        if path.is_file():
            self.on_complete(json.loads(path.read_text(encoding="utf-8")))
            self.navigate(0)

    def load_result(self):
        if self.worker or self.database_worker or self.module_panel.busy or self.pending_new_chat: return
        path, _ = QFileDialog.getOpenFileName(self, "载入任务结果", str(self.workspace / "runs"), "任务结果 (summary.json)")
        if path:
            try: self.on_complete(json.loads(Path(path).read_text(encoding="utf-8")))
            except Exception as exc: QMessageBox.warning(self, "任务结果", str(exc))

    def show_output(self):
        if self.last_output: QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_output))

    def new_chat(self):
        if self.pending_new_chat: return
        self.persist_chat()
        self.pending_new_chat = True
        self.new_chat_button.setText("正在新建对话…")
        self.module_panel.pending_commands.clear()
        self.controls()
        self.finish_new_chat()

    def finish_new_chat(self):
        if not self.pending_new_chat: return
        if self.database_worker:
            self.state.setText("数据库准备完成后将自动开启新对话。")
            return
        if self.worker:
            self.state.setText("当前任务结束后将自动开启新对话；也可点击停止，已完成结果会保留。")
            return
        if not self.module_panel.request_close_all():
            self.state.setText("正在保留模块草稿并开启新对话；如有依据对话框，请先关闭它。")
            return
        self.pending_new_chat = False
        self.new_chat_button.setText("＋  新建对话")
        self.chat_id, self.messages = uuid.uuid4().hex, []
        for frame in self.bubbles:
            self.chat_layout.removeWidget(frame)
            frame.deleteLater()
        self.bubbles = []
        self.report_frame.hide()
        self.report.clear()
        self.module_card.hide()
        self.execution_card.hide()
        self.welcome.show()
        self.last_result, self.active_run_id, self.last_output = None, None, None
        self.module_panel.reset()
        self.execution.clear()
        self.data_space.clear()
        self.review_tree.clear()
        self.review_editors = []
        self.nav_buttons[4].setText("待审核")
        self.log.clear()
        self.history.clearSelection()
        self.history.setCurrentRow(-1)
        self.started_at, self.elapsed_value = None, 0
        self.open_output.setEnabled(False)
        self.state.setText("等待提交文件")
        self.clock_label.setText("尚未运行")
        self.prompt.clear()
        self.inputs, self.knowledge = [], []
        self.update_attachments()
        self.navigate(0)
        self.bubble("assistant", "新对话已开始。请加入输入文件和本次知识资料。已有任务仍可从最近任务查看。")
        self.controls()

    def closeEvent(self, event):
        if self.database_worker:
            self.close_after_database = True
            self.state.setText("数据库准备完成后自动退出，正在保留当前初始化进度。")
            event.ignore()
        elif self.worker:
            self.worker.cancelled.set()
            self.state.setText("正在停止后台任务，释放后可关闭")
            event.ignore()
        elif not self.module_panel.request_close_all():
            self.state.setText("正在保存模块工作副本，编辑器关闭后可退出")
            event.ignore()
        else:
            self.timer.stop()
            self.module_panel.timer.stop()
            self.execution.flush_layout()
            self.execution.save_timer.stop()
            event.accept()
