"""管束设计 Agent 主窗口：聊天式界面 + 四个正式 Tab 的预览卡片。

界面沿用 Demo 原有简洁聊天风格：用户消息靠右、AI 回复靠左、Enter 发送、
Shift+Enter 换行。左侧导航使用正式程序的四个 Tab 名称，点击后在聊天区域
展开该 Tab 的预览（管板型式/布管/管-板连接/轴向设计），预览底部只有一个“保留”。

除参数修改外，用户还可以让 AI 布置布管元件：AI 只给“元件 + 数量 + 选孔规则 +
元件参数”，界面渲染成 `PlacementPlanCard` 供用户过目，确认后才由
`TubeLayoutPage.apply_placement_plan()` 按真实布管结果算出落点并画到图上。
"""
from __future__ import annotations

import json
import re
from copy import deepcopy

from PyQt5.QtCore import QPoint, QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ai_support.api_client import CANONICAL_FIELDS, FIELD_ALIASES, DeepSeekClient
from bundle.page import COMPONENT_LABEL, TubeLayoutPage
from bundle.placement import (
    HOLE_REGIONS,
    KIND_LABEL,
    OPTION_FIELDS,
    HoleOp,
    PlacementItem,
    UIAction,
    normalize_kind,
    normalize_region,
    parse_hole_ops,
    parse_ui_actions,
)


def is_immediate_local_control(text: str) -> bool:
    """只有无需模型理解的确认/回退指令才允许在 Agent 前本地执行。"""
    compact = re.sub(r"\s+", "", str(text or ""))
    exact = {
        "撤销", "撤回", "保留", "保留当前方案", "确认保留",
        "确认布置", "确认方案", "执行方案", "按这个布置", "就按这个布置",
        "放弃方案", "取消方案", "不布置了", "使用推荐值", "采用推荐值",
    }
    return (
        compact in exact
        or compact.startswith("保留当前")
        or ("为什么" in compact and "不通过" in compact)
    )
from bundle.stages import AxialStage, SheetFormStage, TubeConnectionStage
from bundle.widgets import RightAlignedComboBox
from db.production import DatabaseUnavailable, ProductionRepository, SaveFailed
from models import STAGES
from session import DesignSession
from settings import load_settings, settings_dialog


class TaskThread(QThread):
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            result = self.fn()
            if not self.isInterruptionRequested():
                self.result_ready.emit(result)
        except Exception as exc:  # noqa: BLE001 - 交给界面显示
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))


class MessageInput(QPlainTextEdit):
    send_requested = pyqtSignal()

    MIN_HEIGHT = 46
    MAX_HEIGHT = 132

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.textChanged.connect(self._autosize)
        self.setFixedHeight(self.MIN_HEIGHT)

    def _autosize(self):
        if self.viewport().width() < 120:
            return
        metrics = self.fontMetrics()
        usable = max(120, self.viewport().width() - 6)
        lines = 0
        block = self.document().begin()
        while block.isValid():
            advance = metrics.horizontalAdvance(block.text() or " ")
            lines += max(1, -(-advance // usable))
            block = block.next()
        needed = 14 + lines * (metrics.height() + 3)
        target = max(self.MIN_HEIGHT, min(self.MAX_HEIGHT, needed))
        if target != self.height():
            self.setFixedHeight(target)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._autosize()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
            event.accept()
            self.send_requested.emit()
            return
        super().keyPressEvent(event)


class ChatTranscript(QScrollArea):
    """Widget-backed transcript so message alignment is not dependent on rich-text CSS support."""

    MAX_TEXT_WIDTH = 1000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.message_rows = []
        self._messages = []
        self._transient_label: QLabel | None = None
        self._stick_bottom = True
        self._content = QWidget()
        self._content.setObjectName("chatContent")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(0, 6, 0, 6)
        self._layout.setSpacing(18)
        self._layout.addStretch()
        self.setWidget(self._content)
        # 消息/卡片的高度是布局完成之后才定的，插完立刻滚不一定到底；
        # 这里跟着滚动条范围变化走：只要用户本来就在底部，就一直贴着最新一条。
        bar = self.verticalScrollBar()
        bar.rangeChanged.connect(self._on_range_changed)
        bar.valueChanged.connect(self._on_value_changed)

    def _on_range_changed(self, _minimum: int, maximum: int) -> None:
        if self._stick_bottom:
            self.verticalScrollBar().setValue(maximum)

    def _on_value_changed(self, value: int) -> None:
        bar = self.verticalScrollBar()
        self._stick_bottom = value >= bar.maximum() - 4

    def append_message(self, role: str, text: str, transient: bool = False) -> QLabel:
        role = "user" if role == "user" else "assistant"
        row = QWidget()
        row.setObjectName("chatRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        message = QFrame()
        message.setProperty("chatRole", role)
        message.setObjectName("userMessage" if role == "user" else "assistantMessage")
        message.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        body = QVBoxLayout(message)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(5)

        if role == "assistant":
            message.setMaximumWidth(self.MAX_TEXT_WIDTH + 34)
            message.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            head = QHBoxLayout()
            head.setContentsMargins(0, 0, 0, 0)
            head.setSpacing(8)
            avatar = QLabel("AI")
            avatar.setObjectName("assistantAvatar")
            avatar.setAlignment(Qt.AlignCenter)
            avatar.setFixedSize(24, 24)
            name = QLabel("管束助手")
            name.setObjectName("assistantName")
            head.addWidget(avatar, 0, Qt.AlignVCenter)
            head.addWidget(name, 0, Qt.AlignVCenter)
            head.addStretch()
            body.addLayout(head)
            content = QLabel(str(text))
            content.setObjectName("chatMessageText")
            content.setWordWrap(True)
            content.setMaximumWidth(self.MAX_TEXT_WIDTH)
            content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            content.setTextInteractionFlags(Qt.TextSelectableByMouse)
            body.addWidget(content)
            row_layout.addWidget(message, 1)
            row_layout.addStretch(0)
        else:
            message.setMaximumWidth(560)
            message.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            name = QLabel("你")
            name.setObjectName("userName")
            name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            bubble = QFrame()
            bubble.setObjectName("userBubble")
            bubble_layout = QVBoxLayout(bubble)
            bubble_layout.setContentsMargins(14, 9, 14, 10)
            bubble_layout.setSpacing(0)
            content = QLabel(str(text))
            content.setObjectName("chatMessageText")
            content.setWordWrap(True)
            content.setMaximumWidth(510)
            # 让短句不折行：按文字实际宽度给最小宽度，超过 510 才换行
            natural = content.fontMetrics().horizontalAdvance(str(text).split("\n")[0]) + 16
            content.setMinimumWidth(min(510, max(60, natural)))
            content.setTextInteractionFlags(Qt.TextSelectableByMouse)
            bubble_layout.addWidget(content)
            body.addWidget(name, 0, Qt.AlignRight)
            body.addWidget(bubble)
            row_layout.addStretch()
            row_layout.addWidget(message, 0, Qt.AlignRight | Qt.AlignTop)

        self._layout.insertWidget(self._layout.count() - 1, row)
        self.message_rows.append(row)
        self._messages.append((role, str(text)))
        # 只有“操作反馈”类消息可以就地替换；普通对话/卡片之后再来状态提示就另起一条
        self._transient_label = content if transient and role == "assistant" else None
        QTimer.singleShot(0, self._scroll_to_bottom)
        return content

    def update_transient(self, text: str) -> bool:
        """把最新一条状态提示改成新文本（不新增气泡），成功返回 True。"""
        if self._transient_label is None:
            return False
        self._transient_label.setText(str(text))
        if self._messages:
            role, _ = self._messages[-1]
            self._messages[-1] = (role, str(text))
        return True

    def append_widget(self, widget: QWidget) -> None:
        self._transient_label = None
        self._layout.insertWidget(self._layout.count() - 1, widget)
        self.message_rows.append(widget)
        QTimer.singleShot(0, lambda w=widget: self._reveal(w))

    def _reveal(self, widget: QWidget, retry: bool = True) -> None:
        """新卡片：比视口高就从卡片顶部开始看，否则照常滚到最新一条。"""
        if widget.height() > self.viewport().height() - 16:
            self._stick_bottom = False
            top = widget.mapTo(self._content, QPoint(0, 0)).y()
            self.verticalScrollBar().setValue(max(0, top - 4))
        else:
            self._scroll_to_bottom()
        # 插入时控件还没完成布局（高度可能是 0），下一轮事件循环再按真实高度决定一次
        if retry:
            QTimer.singleShot(0, lambda w=widget: self._reveal(w, retry=False))

    def remove_widget(self, widget: QWidget | None) -> None:
        if widget is None:
            return
        if widget in self.message_rows:
            self.message_rows.remove(widget)
        self._layout.removeWidget(widget)
        widget.setParent(None)
        widget.deleteLater()

    def _scroll_to_bottom(self) -> None:
        self._stick_bottom = True
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def scroll_to(self, widget: QWidget) -> None:
        # 直接滚到底：预览卡片高度≈可视高度，滚到底即可完整看到卡片与“保留”
        self._scroll_to_bottom()
        QTimer.singleShot(0, self._scroll_to_bottom)

    def clear(self) -> None:
        for row in self.message_rows:
            self._layout.removeWidget(row)
            row.deleteLater()
        self.message_rows.clear()
        self._messages.clear()
        self._transient_label = None
        self._stick_bottom = True

    def toPlainText(self) -> str:
        labels = {"user": "你", "assistant": "管束助手"}
        return "\n".join(f"{labels[role]}\n{text}" for role, text in self._messages)


class PreviewCard(QFrame):
    """聊天区域内的阶段预览卡片。"""

    def __init__(self, stage: str, page: QWidget, approved: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("previewCard")
        self.setMinimumHeight(320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel(stage)
        title.setObjectName("sectionTitle")
        head.addWidget(title)
        head.addSpacing(8)
        self.badge = QLabel("已保留" if approved else "草稿 · 检查后点“保留”")
        self.badge.setObjectName("statusBadge" if not approved else "keptBadge")
        head.addWidget(self.badge)
        head.addStretch()
        layout.addLayout(head)
        self.page = page
        layout.addWidget(page, 1)


class PlanTubeRef(QWidget):
    """方案卡里的一个参照管：行号/列号可改，坐标跟着实时更新。

    正式程序里布置防冲板/中间挡板/中间挡管，输入就是“选哪两根换热管”；
    这里把“第几行第几列”做成可编辑项，改完立刻换算成绝对坐标显示，
    填了不存在的管孔会标红并禁止确认。
    """

    edited = pyqtSignal()

    def __init__(self, ref: dict, tag: str = "", parent=None):
        super().__init__(parent)
        self._ref = dict(ref or {})
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)
        self.tag_label = QLabel(tag)
        self.tag_label.setObjectName("planRefTag")
        self.tag_label.setFixedWidth(62)
        line.addWidget(self.tag_label)
        line.addWidget(self._hint("行"))
        self.row_edit = self._number_edit(self._ref.get("row", 1))
        line.addWidget(self.row_edit)
        line.addWidget(self._hint("列"))
        self.col_edit = self._number_edit(self._ref.get("col", 1))
        line.addWidget(self.col_edit)
        arrow = QLabel("→")
        arrow.setObjectName("planCellMuted")
        line.addWidget(arrow)
        self.coord_label = QLabel(self._coord_text())
        self.coord_label.setObjectName("planCoord")
        line.addWidget(self.coord_label, 1)
        box.addLayout(line)
        self.error_label = QLabel("")
        self.error_label.setObjectName("planError")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        box.addWidget(self.error_label)
        for edit in (self.row_edit, self.col_edit):
            edit.textEdited.connect(lambda *_: self.edited.emit())

    @staticmethod
    def _hint(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("planCellMuted")
        return label

    @staticmethod
    def _number_edit(value) -> QLineEdit:
        edit = QLineEdit(str(value))
        edit.setObjectName("planCellEdit")
        edit.setAlignment(Qt.AlignCenter)
        edit.setFixedWidth(46)
        return edit

    def _coord_text(self) -> str:
        return f"({float(self._ref.get('x', 0)):.1f}, {float(self._ref.get('y', 0)):.1f})"

    def tag(self) -> str:
        return self.tag_label.text()

    def value(self) -> tuple[int, int] | None:
        try:
            return int(self.row_edit.text().strip()), int(self.col_edit.text().strip())
        except (TypeError, ValueError):
            return None

    def set_ref(self, ref: dict) -> None:
        """用程序解析出的真实管孔回填坐标（行/列保留用户输入）。"""
        if not ref:
            return
        self._ref = dict(ref)
        self.coord_label.setText(self._coord_text())

    def set_error(self, message: str = "") -> None:
        if message:
            style = "QLineEdit{background:#fff5f5;border:1px solid #d04b4b;border-radius:5px;padding:2px 4px;}"
            self.coord_label.setText("—")
        else:
            style = ""
            self.coord_label.setText(self._coord_text())
        for edit in (self.row_edit, self.col_edit):
            edit.setStyleSheet(style)
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))

    def set_message(self, message: str) -> None:
        """只提示、不标红（例如两根管不在同一排）。"""
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))

    def set_editable(self, editable: bool) -> None:
        for edit in (self.row_edit, self.col_edit):
            edit.setReadOnly(not editable)
            edit.setEnabled(editable)


class PlanParamField(QWidget):
    """方案卡里的一个元件参数（数值输入或下拉选择），可编辑。"""

    edited = pyqtSignal()

    def __init__(self, spec: dict, parent=None):
        super().__init__(parent)
        self.name = str(spec.get("name", ""))
        self._kind = str(spec.get("kind", "number"))
        self._locked = bool(spec.get("locked"))
        # 形式（防冲板形式/滑道形式…）：改了要连方案内容一起换
        self.is_form = bool(spec.get("form"))
        value = str(spec.get("value", "") or "")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        label = QLabel(str(spec.get("short") or self.name))
        label.setObjectName("planCellMuted")
        label.setToolTip(self.name)
        row.addWidget(label)
        if self._locked:
            self.editor: QWidget = QLabel(value or "—")
            self.editor.setObjectName("planLockedValue")
            row.addWidget(self.editor)
        elif self._kind == "choice" and spec.get("options"):
            combo = RightAlignedComboBox()
            combo.setObjectName("planCellCombo")
            for option in spec.get("options") or []:
                combo.addItem(str(option), str(option))
            widest = max(
                (combo.fontMetrics().horizontalAdvance(combo.itemText(i))
                 for i in range(combo.count())),
                default=0,
            )
            # 右对齐文字还要给下拉箭头和两层样式内边距留空间；固定 112px 会裁掉首字。
            combo.setMinimumWidth(max(136, widest + 72))
            index = combo.findData(value)
            if index < 0 and value:
                combo.addItem(value, value)
                index = combo.count() - 1
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.currentIndexChanged.connect(lambda *_: self.edited.emit())
            self.editor = combo
            row.addWidget(combo)
        else:
            edit = QLineEdit(value)
            edit.setObjectName("planCellEdit")
            edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            edit.setFixedWidth(66)
            edit.textEdited.connect(lambda *_: self.edited.emit())
            self.editor = edit
            row.addWidget(edit)
        unit = str(spec.get("unit", "") or "")
        unit_label = QLabel(unit)
        unit_label.setObjectName("planCellMuted")
        unit_label.setMinimumWidth(16)
        row.addWidget(unit_label)
        row.addStretch()
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self.setToolTip(self.name)

    @property
    def is_locked(self) -> bool:
        return self._locked

    def value(self) -> str | None:
        """返回参数文本；数值型为空或填了非数字返回 None（卡片会标红）。"""
        if self._locked:
            return None
        if isinstance(self.editor, QComboBox):
            return str(self.editor.currentData() or self.editor.currentText()).strip()
        text = self.editor.text().strip()
        try:
            float(text)
        except ValueError:
            return None
        return text

    def set_error(self, on: bool) -> None:
        if not isinstance(self.editor, QLineEdit):
            return
        self.editor.setStyleSheet(
            "QLineEdit{background:#fff5f5;border:1px solid #d04b4b;border-radius:5px;padding:2px 4px;}"
            if on else ""
        )

    def set_editable(self, editable: bool) -> None:
        self.editor.setEnabled(editable and not self._locked)


class PlacementPlanCard(QFrame):
    """AI 元件布置方案：先给用户过目/改参数，确认后才在布管图上落地。

    卡片本身就是正式程序里那个“选管 + 参数”弹窗的可编辑版：选中的换热管按
    “第几行第几列”给出来可以改，元件参数也直接改，改完图上高亮同步。
    """

    confirm_requested = pyqtSignal(object)
    discard_requested = pyqtSignal(object)

    def __init__(self, items, preview: dict, page=None, parent=None):
        super().__init__(parent)
        self.setObjectName("planCard")
        self.items = list(items)
        self._page = page
        self._preview = preview or {}
        self._blocks: list[dict] = []
        self._syncing = False
        self.setMaximumWidth(ChatTranscript.MAX_TEXT_WIDTH + 34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 10)
        root.setSpacing(7)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("布管 · 元件布置方案")
        title.setObjectName("planTitle")
        head.addWidget(title)
        self.badge = QLabel("待确认")
        self.badge.setObjectName("statusBadge")
        head.addWidget(self.badge)
        head.addStretch()
        root.addLayout(head)

        self.body = QFrame()
        self.body.setObjectName("planTable")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(12, 8, 12, 8)
        self.body_layout.setSpacing(7)
        root.addWidget(self.body)

        # 提示与按钮同一行：卡片矮一点，聊天区里能整张看完（按钮不会被挤到屏幕外）
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        self.hint = QLabel("")
        self.hint.setObjectName("planHint")
        self.hint.setWordWrap(True)
        self.actions.addWidget(self.hint, 1)
        self.discard_button = QPushButton("放弃")
        self.discard_button.setObjectName("planGhost")
        self.discard_button.setCursor(Qt.PointingHandCursor)
        self.confirm_button = QPushButton("确认布置")
        self.confirm_button.setObjectName("planPrimary")
        self.confirm_button.setCursor(Qt.PointingHandCursor)
        self.discard_button.clicked.connect(lambda: self.discard_requested.emit(self))
        self.confirm_button.clicked.connect(lambda: self.confirm_requested.emit(self))
        self.actions.addWidget(self.discard_button)
        self.actions.addWidget(self.confirm_button)
        root.addLayout(self.actions)

        self._build_body()
        self._sync()

    # ---------------------------------------------------------------- 卡片内容
    def _build_body(self) -> None:
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._blocks = []
        rows = self._preview.get("rows", [])
        for row, item in zip(rows, self.items):
            block = QFrame()
            block.setObjectName("planBlock")
            box = QVBoxLayout(block)
            box.setContentsMargins(10, 6, 10, 6)
            box.setSpacing(4)

            title_line = QHBoxLayout()
            title_line.setSpacing(8)
            name = QLabel(str(row.get("label", "")))
            name.setObjectName("planCellStrong")
            title_line.addWidget(name)
            count = QLabel(f"× {row.get('count', 1)}")
            count.setObjectName("planCellMuted")
            title_line.addWidget(count)
            title_line.addStretch()
            box.addLayout(title_line)

            entry = {
                "item": item,
                "label": str(row.get("label", "")),
                "mode": str(row.get("ref_mode", "none")),
                "refs": [],
                "params": [],
                "seed_edited": False,
            }

            mode = entry["mode"]
            if mode in {"pair", "seed"}:
                refs = row.get("refs") or []
                pair_total = max(len(refs) // 2, 1)
                grid = QGridLayout()
                grid.setContentsMargins(0, 0, 0, 0)
                grid.setHorizontalSpacing(18)
                grid.setVerticalSpacing(4)
                per_line = 2 if mode == "pair" else 1
                for index, ref in enumerate(refs):
                    if mode == "seed":
                        tag = "种子管"
                    elif pair_total == 1:
                        tag = f"参照管 {index + 1}"
                    else:
                        tag = f"{index // 2 + 1}-{index % 2 + 1}"
                    editor = PlanTubeRef(ref, tag)
                    editor.edited.connect(
                        lambda e=editor, ent=entry: self._on_ref_edited(ent, e)
                    )
                    entry["refs"].append(editor)
                    grid.addWidget(editor, index // per_line, index % per_line)
                box.addLayout(grid)
                if mode == "seed":
                    expanded = len(row.get("tubes") or [])
                    note = QLabel(f"按对称展开后共 {expanded} 根")
                    note.setObjectName("planCellMuted")
                    box.addWidget(note)
            elif mode == "text" and row.get("anchors"):
                detail = QLabel(str(row.get("anchors")))
                detail.setObjectName("planCellMuted")
                detail.setWordWrap(True)
                box.addWidget(detail)
            else:
                detail = QLabel("不选管：按下面的参数定位")
                detail.setObjectName("planCellMuted")
                box.addWidget(detail)

            param_specs = row.get("param_rows") or []
            if param_specs:
                fields: list[PlanParamField] = []
                for spec in param_specs:
                    field = PlanParamField(spec)
                    field.edited.connect(
                        lambda f=field, ent=entry: self._on_param_edited(ent, f)
                    )
                    entry["params"].append(field)
                    fields.append(field)
                for start in range(0, len(fields), 3):
                    line = QHBoxLayout()
                    line.setContentsMargins(0, 0, 0, 0)
                    line.setSpacing(20)
                    for field in fields[start:start + 3]:
                        line.addWidget(field)
                    line.addStretch()
                    box.addLayout(line)

            self._blocks.append(entry)
            self.body_layout.addWidget(block)

    def _on_ref_edited(self, entry: dict, editor: PlanTubeRef) -> None:
        if entry["mode"] == "seed":
            entry["seed_edited"] = True
        self._sync()

    def _on_param_edited(self, entry: dict, field: PlanParamField) -> None:
        """参数改动：普通数值照旧实时预览；改“形式”则整块方案内容跟着换。"""
        if not field.is_form:
            self._sync()
            return
        item = entry["item"]
        value = field.value()
        if value:
            item.overrides[field.name] = value
            # 形式本身也是“方案的选择”，一并记进方案，落位时写回参数表
            item.options[field.name] = value
        # 形式一换：参数列表、要不要参照管、删几个干涉管全都不一样了，整块重建
        QTimer.singleShot(0, self._rebuild_after_form_change)

    def _rebuild_after_form_change(self) -> None:
        if self._page is None:
            return
        self._preview = self._page.preview_placement(self.items)
        self._build_body()
        self._sync()

    # ---------------------------------------------------------------- 同步校验
    def _sync(self) -> None:
        """把卡片上的编辑结果写回方案，再让程序重算落点并在图上重新高亮。"""
        if self._syncing or self._page is None:
            return
        self._syncing = True
        try:
            problems: list[str] = []
            pos_rows, neg_rows = self._page.row_limits()
            for entry in self._blocks:
                item = entry["item"]
                anchors: list = []
                ref_ok = True
                for editor in entry["refs"]:
                    value = editor.value()
                    center = None
                    if value is not None:
                        center = self._page.center_for_row_col(*value)
                    if center is None:
                        hint = (
                            f"没有这个管孔（行 {value[0]}、列 {value[1]}）"
                            if value is not None else "行号和列号都要填整数"
                        )
                        editor.set_error(
                            f"{hint}；行 1~{max(pos_rows, 1)} 或 {-max(neg_rows, 1)}~-1"
                        )
                        problems.append(f"{entry['label']}：参照管要重新填")
                        ref_ok = False
                        continue
                    editor.set_error("")
                    anchors.append(center)

                if entry["mode"] == "pair":
                    item.anchors = anchors
                elif entry["mode"] == "seed" and entry["seed_edited"] and anchors:
                    item.anchors = anchors[:1]

                overrides: dict = {}
                for field in entry["params"]:
                    if field.is_locked:
                        continue
                    text = field.value()
                    if text is None:
                        field.set_error(True)
                        problems.append(f"{entry['label']}：{field.name} 要填数字")
                        continue
                    field.set_error(False)
                    if text != "":
                        overrides[field.name] = text
                item.overrides = overrides

                error = self._page.validate_anchors(item) if ref_ok else None
                if error:
                    problems.append(f"{entry['label']}：{error}")
                    if entry["refs"]:
                        entry["refs"][-1].set_message(error)

            self._preview = self._page.preview_placement(self.items)
            if not problems:
                self._refresh_ref_coords()
            self._refresh_hint(problems)
        finally:
            self._syncing = False

    def _refresh_ref_coords(self) -> None:
        rows = self._preview.get("rows", [])
        for entry, row in zip(self._blocks, rows):
            refs = row.get("refs") or []
            for editor, ref in zip(entry["refs"], refs):
                editor.set_ref(ref)

    def _refresh_hint(self, problems: list[str]) -> None:
        holes = self._preview.get("holes", 0)
        occupying = self._preview.get("occupying", 0)
        deletes = self._preview.get("deletes", 0)
        remaining = self._preview.get("remaining", holes)
        text = f"确认后按卡片参数布置（{holes} 孔）"
        parts = []
        if occupying:
            parts.append(f"占用 {occupying}")
        if deletes:
            parts.append(f"删干涉管 {deletes}")
        if parts:
            parts.append(f"剩 {remaining}")
            text += "：" + "、".join(parts)
        self.hint.setText(text + "。")
        if problems:
            self.hint.setText(text + "。请先改好：" + "；".join(dict.fromkeys(problems)))
        self.confirm_button.setEnabled(not problems)
        self.badge.setText("有待修正" if problems else "待确认")

    def _set_editable(self, editable: bool) -> None:
        for entry in self._blocks:
            for editor in entry["refs"]:
                editor.set_editable(editable)
            for field in entry["params"]:
                field.set_editable(editable)

    def _restyle_badge(self) -> None:
        style = self.badge.style()
        style.unpolish(self.badge)
        style.polish(self.badge)
        self.badge.update()

        style = self.badge.style()
        style.unpolish(self.badge)
        style.polish(self.badge)
        self.badge.update()

    def mark_applied(self, result: dict) -> None:
        ok = bool(result.get("ok"))
        self.badge.setText("已布置" if ok else "未能布置")
        self.badge.setObjectName("keptBadge" if ok else "planFailedBadge")
        self._restyle_badge()
        self._set_editable(False)
        for button in (self.confirm_button, self.discard_button):
            button.setEnabled(False)
            button.hide()

        lines = []
        for row in result.get("rows", []):
            text = f"{row['label']} × {row['placed']}"
            if row.get("skipped"):
                text += f"（{row['skipped']} 个未布置：{row.get('detail') or '位置不足'}）"
            elif row.get("detail"):
                text += f"（{row['detail']}）"
            lines.append(text)
        if result.get("occupied"):
            text = (
                f"已布置：{'；'.join(lines)}。占用 {result['occupied']} 个管孔，"
                f"剩 {result.get('holes_after', 0)} 个。"
            )
        else:
            text = f"已布置：{'；'.join(lines) or result.get('message', '')}"
        done = QLabel(text)
        done.setObjectName("planResult")
        done.setWordWrap(True)
        self.layout().insertWidget(self.layout().count() - 1, done)

    def mark_discarded(self) -> None:
        self.badge.setText("已放弃")
        self.badge.setObjectName("planMutedBadge")
        self._restyle_badge()
        self._set_editable(False)
        for button in (self.confirm_button, self.discard_button):
            button.setEnabled(False)
            button.hide()
        done = QLabel("方案已放弃，布管图没有改动。")
        done.setObjectName("planResultMuted")
        done.setWordWrap(True)
        self.layout().insertWidget(self.layout().count() - 1, done)


class HolePlanCard(QFrame):
    """换热管增删方案卡（“删除离隔板槽最近的 2 排换热管”这类要求）。

    和元件方案卡一样：AI 只给“删哪一片、几根”，真正落到哪些管孔由程序按当前
    布管结果算，卡片上把算出来的管孔列给用户，点“确认执行”才动图。
    """

    confirm_requested = pyqtSignal(object)
    discard_requested = pyqtSignal(object)

    def __init__(self, ops, preview: dict, page=None, parent=None):
        super().__init__(parent)
        self.setObjectName("planCard")
        self.ops = list(ops)
        self._page = page
        self._preview = preview or {}
        self.setMaximumWidth(ChatTranscript.MAX_TEXT_WIDTH + 34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 10)
        root.setSpacing(7)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("布管 · 换热管调整方案")
        title.setObjectName("planTitle")
        head.addWidget(title)
        self.badge = QLabel("待确认")
        self.badge.setObjectName("statusBadge")
        head.addWidget(self.badge)
        head.addStretch()
        root.addLayout(head)

        body = QFrame()
        body.setObjectName("planTable")
        box = QVBoxLayout(body)
        box.setContentsMargins(12, 8, 12, 8)
        box.setSpacing(6)
        for row in self._preview.get("rows", []):
            line = QHBoxLayout()
            line.setSpacing(8)
            name = QLabel(str(row.get("label", "调整换热管")))
            name.setObjectName("planCellStrong")
            line.addWidget(name)
            amount = QLabel(f"× {row.get('count', 0)}")
            amount.setObjectName("planCellMuted")
            line.addWidget(amount)
            where = QLabel(str(row.get("where", "")))
            where.setObjectName("planCellMuted")
            line.addWidget(where)
            line.addStretch()
            box.addLayout(line)
            refs = "、".join(
                f"行{ref.get('row')}列{ref.get('col')}" for ref in row.get("refs") or []
            )
            if row.get("more"):
                refs += f" 等（另有 {row['more']} 根）"
            detail = QLabel(refs or "这个范围内没有可调整的换热管")
            detail.setObjectName("planCellMuted")
            detail.setWordWrap(True)
            box.addWidget(detail)
        problems = list(self._preview.get("problems") or [])
        if problems:
            shown = "；".join(problems[:6])
            if len(problems) > 6:
                shown += f" 等 {len(problems)} 处"
            warn = QLabel(f"没落上的：{shown}")
            warn.setObjectName("planFailedBadge")
            warn.setWordWrap(True)
            box.addWidget(warn)
        root.addWidget(body)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        self.hint = QLabel("")
        self.hint.setObjectName("planHint")
        self.hint.setWordWrap(True)
        self.actions.addWidget(self.hint, 1)
        self.discard_button = QPushButton("放弃")
        self.discard_button.setObjectName("planGhost")
        self.discard_button.setCursor(Qt.PointingHandCursor)
        self.confirm_button = QPushButton("确认执行")
        self.confirm_button.setObjectName("planPrimary")
        self.confirm_button.setCursor(Qt.PointingHandCursor)
        self.discard_button.clicked.connect(lambda: self.discard_requested.emit(self))
        self.confirm_button.clicked.connect(lambda: self.confirm_requested.emit(self))
        self.actions.addWidget(self.discard_button)
        self.actions.addWidget(self.confirm_button)
        root.addLayout(self.actions)

        self._refresh_hint()

    def _refresh_hint(self) -> None:
        holes = int(self._preview.get("holes", 0))
        remaining = int(self._preview.get("remaining", holes))
        total = int(self._preview.get("total", 0))
        delete = sum(row["count"] for row in self._preview.get("rows", []) if row["op"] == "delete")
        restore = total - delete
        parts = []
        if delete:
            parts.append(f"删除 {delete} 根")
        if restore:
            parts.append(f"恢复 {restore} 根")
        text = f"确认后按卡片执行：{'、'.join(parts) or '没有改动'}（当前 {holes} 孔）"
        if total:
            text += f"，执行后 {remaining} 孔。"
        self.hint.setText(text)
        self.confirm_button.setEnabled(total > 0)

    def mark_applied(self, result: dict) -> None:
        ok = bool(result.get("ok"))
        self.badge.setText("已执行" if ok else "未能执行")
        self.badge.setObjectName("keptBadge" if ok else "planFailedBadge")
        style = self.badge.style()
        style.unpolish(self.badge)
        style.polish(self.badge)
        for button in (self.confirm_button, self.discard_button):
            button.setEnabled(False)
            button.hide()
        lines = [
            f"{row['label']} {row['changed']} 根（{row['where']}）"
            for row in result.get("rows", [])
        ]
        if ok:
            text = (
                f"已执行：{'；'.join(lines)}。当前 {result.get('holes_after', 0)} 个换热管孔。"
            )
        else:
            text = result.get("message") or "没有可调整的换热管，布管图未变。"
        done = QLabel(text)
        done.setObjectName("planResult" if ok else "planResultMuted")
        done.setWordWrap(True)
        self.layout().insertWidget(self.layout().count() - 1, done)

    def mark_discarded(self) -> None:
        self.badge.setText("已放弃")
        self.badge.setObjectName("planMutedBadge")
        style = self.badge.style()
        style.unpolish(self.badge)
        style.polish(self.badge)
        for button in (self.confirm_button, self.discard_button):
            button.setEnabled(False)
            button.hide()
        done = QLabel("方案已放弃，布管图没有改动。")
        done.setObjectName("planResultMuted")
        done.setWordWrap(True)
        self.layout().insertWidget(self.layout().count() - 1, done)


class HoleCoordinateCard(QFrame):
    """换热管坐标表：把“所有换热管的绝对坐标”摊在对话里，可一键复制成表格。

    坐标不是模型编的，是程序从真实布管结果里取的（行号/列号按满布管孔编号）。
    """

    def __init__(self, rows: list[dict], title: str = "换热管坐标（绝对坐标）", parent=None):
        super().__init__(parent)
        self.setObjectName("planCard")
        self.setMaximumWidth(ChatTranscript.MAX_TEXT_WIDTH + 34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._rows = list(rows)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 10)
        root.setSpacing(7)

        head = QHBoxLayout()
        head.setSpacing(8)
        label = QLabel(f"{title} · 共 {len(self._rows)} 个")
        label.setObjectName("planTitle")
        head.addWidget(label)
        head.addStretch()
        self.copy_button = QPushButton("复制全部")
        self.copy_button.setObjectName("planGhost")
        self.copy_button.setCursor(Qt.PointingHandCursor)
        self.copy_button.clicked.connect(self._copy_all)
        head.addWidget(self.copy_button)
        root.addLayout(head)

        table = QTableWidget(len(self._rows), 5)
        table.setHorizontalHeaderLabels(["行号", "列号", "X (mm)", "Y (mm)", "状态"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setMaximumHeight(240)
        table.horizontalHeader().setStretchLastSection(True)
        for index, row in enumerate(self._rows):
            values = [
                str(row.get("row", "")), str(row.get("col", "")),
                f"{float(row.get('x', 0)):.2f}", f"{float(row.get('y', 0)):.2f}",
                str(row.get("state", "")),
            ]
            for column, text in enumerate(values):
                table.setItem(index, column, QTableWidgetItem(text))
        table.resizeColumnsToContents()
        for column, width in ((0, 56), (1, 56), (2, 88), (3, 88)):
            table.setColumnWidth(column, width)
        root.addWidget(table)
        self.table = table

    def _copy_all(self) -> None:
        lines = ["行号\t列号\tX\tY\t状态"]
        for row in self._rows:
            lines.append(
                f"{row.get('row')}\t{row.get('col')}\t"
                f"{float(row.get('x', 0)):.2f}\t{float(row.get('y', 0)):.2f}\t{row.get('state', '')}"
            )
        QApplication.clipboard().setText("\n".join(lines))
        self.copy_button.setText("已复制")


class ComponentCoordinateCard(QFrame):
    """元件数据字典表：说“输出所有拉杆坐标”就给拉杆，不再拿换热管糊弄。

    列是“元件 / 规格·形式 / 落位（行号列号）/ X / Y / 备注”，数据全部来自
    图上真实布置的元件（`page.component_coordinates`），模型编不出来。
    """

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("planCard")
        self.setMaximumWidth(ChatTranscript.MAX_TEXT_WIDTH + 34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._rows = list(data.get("rows") or [])
        self.label = str(data.get("label") or "全部元件")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 10)
        root.setSpacing(7)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel(f"{self.label}数据（绝对坐标） · 共 {len(self._rows)} 个")
        title.setObjectName("planTitle")
        head.addWidget(title)
        head.addStretch()
        self.copy_button = QPushButton("复制全部")
        self.copy_button.setObjectName("planGhost")
        self.copy_button.setCursor(Qt.PointingHandCursor)
        self.copy_button.clicked.connect(self._copy_all)
        head.addWidget(self.copy_button)
        root.addLayout(head)

        table = QTableWidget(len(self._rows), 5)
        table.setHorizontalHeaderLabels(["元件", "规格 / 形式", "落位", "X (mm)", "Y (mm)"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        # 表高按行数给足，别让最后一行被自己的滚动条挡住
        row_height = 46
        table.setFixedHeight(min(300, row_height * (len(self._rows) + 1) + 12))
        table.setWordWrap(False)
        # 固定列宽，最后一列不再被拉伸（否则 Y 列会吃掉半个卡片、把规格挤成省略号）
        table.horizontalHeader().setStretchLastSection(False)
        for index, row in enumerate(self._rows):
            where = ""
            if row.get("row") not in ("", None):
                where = f"行{row.get('row')} 列{row.get('col')}"
            values = [
                str(row.get("name", "")),
                str(row.get("spec", "")),
                where,
                f"{float(row.get('x', 0)):.2f}",
                f"{float(row.get('y', 0)):.2f}",
            ]
            for column, text in enumerate(values):
                cell = QTableWidgetItem(text)
                cell.setToolTip(text)
                table.setItem(index, column, cell)
        # 列宽合计 ~560，正好落在聊天区宽度内（再宽右侧会被裁掉）
        for column, width in ((0, 84), (1, 176), (2, 116), (3, 92), (4, 92)):
            table.setColumnWidth(column, width)
        root.addWidget(table)
        self.table = table

    def _copy_all(self) -> None:
        lines = ["元件\t规格/形式\t落位\tX\tY"]
        for row in self._rows:
            where = ""
            if row.get("row") not in ("", None):
                where = f"行{row.get('row')}列{row.get('col')}"
            lines.append(
                f"{row.get('name')}\t{row.get('spec')}\t{where}\t"
                f"{float(row.get('x', 0)):.2f}\t{float(row.get('y', 0)):.2f}"
            )
        QApplication.clipboard().setText("\n".join(lines))
        self.copy_button.setText("已复制")


def apply_extracted_parameters(parameters: dict, extracted: dict) -> None:
    condition_fields = {"公称直径", "公称直径 DN", "DN"}
    for name, row in (extracted or {}).items():
        if name in condition_fields:
            continue
        value = row.get("value")
        if name in parameters and value not in (None, ""):
            parameters[name]["value"] = str(value)
            parameters[name]["source"] = "输入文件提取"


class DesignWindow(QMainWindow):
    def __init__(self, repository=None):
        super().__init__()
        self._owns_repository = repository is None
        self.repository = repository or ProductionRepository()
        self.config = load_settings()
        self.session: DesignSession | None = None
        self.pages: dict[int, QWidget] = {}
        self._initial_stage = 0
        self.card: PreviewCard | None = None
        self.inline_card: PreviewCard | None = None
        self._preview_pane_fullscreen = False
        self.worker = None
        self._worker_callback = None
        self._worker_cancelled = False
        self.chat_history: list[dict] = []
        self.placement_cards: list[PlacementPlanCard] = []
        self.hole_cards: list[HolePlanCard] = []
        self._last_user_text = ""
        self.db_status = "未连接"
        # 离屏截图/自动验收用：跳过模态弹窗，并且绝不真正写库
        self.headless = False
        self.setWindowTitle("管束设计 AI AGENT")
        self.setFont(QFont("Microsoft YaHei UI", 10))
        # 窗口铺满可用桌面：对话是主界面，越大越好（启动时还会 showMaximized）
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        width, height = 1600, 980
        if available is not None:
            width = int(available.width() * 0.94)
            height = int(available.height() * 0.94)
        self.resize(max(width, 1200), max(height, 760))
        self.setMinimumSize(1180, 740)
        # 预览区保底：够放布管页的表格+画布；小屏幕上按比例让位给对话
        avail_h = available.height() if available is not None else 1040
        self._preview_floor = max(320, min(430, int(avail_h * 0.50)))
        self._build_ui()
        self._apply_style()
        self._check_database()
        self.append_chat(
            "assistant",
            "你好，我是管束设计助手。\n"
            "正在读取数据库并生成设计草稿……",
        )

    def _apply_default_split(self) -> None:
        """预览给够用就行，剩下的全给对话（对话是主界面）。"""
        total = max(self.splitter.height(), 760)
        floor = min(self._preview_floor, int(total * 0.55))
        preview = max(int(total * 0.46), floor)
        preview = min(preview, max(total - 280, 300))
        self.splitter.setSizes([preview, total - preview])

    # ------------------------------------------------------------------ 布局
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(288)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(16, 20, 16, 14)
        sidebar_layout.setSpacing(2)

        brand = QLabel("管束设计")
        brand.setObjectName("sidebarTitle")
        sidebar_layout.addWidget(brand)
        subtitle = QLabel("AI AGENT")
        subtitle.setObjectName("sidebarSubtitle")
        sidebar_layout.addWidget(subtitle)
        sidebar_layout.addSpacing(16)

        self.start_design_button = QPushButton("开始管束设计")
        self.start_design_button.setObjectName("primarySideButton")
        self.start_design_button.setCursor(Qt.PointingHandCursor)
        self.start_design_button.clicked.connect(self.start_design)
        sidebar_layout.addWidget(self.start_design_button)

        for text, slot in (("新建对话", self.clear_chat), ("选择产品", self.open_product_list)):
            button = QPushButton(text)
            button.setObjectName("sideAction")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(slot)
            sidebar_layout.addWidget(button)

        stage_label = QLabel("设计阶段")
        stage_label.setObjectName("sidebarSection")
        sidebar_layout.addWidget(stage_label)
        self.stage_buttons: list[QPushButton] = []
        for index, text in enumerate(STAGES):
            button = QPushButton(text)
            button.setObjectName("stageButton")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, i=index: self.open_stage(i))
            button.setEnabled(False)
            self.stage_buttons.append(button)
            sidebar_layout.addWidget(button)

        sidebar_layout.addStretch()
        tools = QHBoxLayout()
        tools.setSpacing(2)
        settings_button = QPushButton("AI 设置")
        settings_button.setObjectName("tinyAction")
        settings_button.setCursor(Qt.PointingHandCursor)
        settings_button.clicked.connect(self.open_settings)
        tools.addWidget(settings_button)
        tools.addStretch()
        sidebar_layout.addLayout(tools)
        sidebar_layout.addSpacing(6)
        self.model_label = QLabel("")
        self.model_label.setObjectName("footerLabel")
        sidebar_layout.addWidget(self.model_label)
        self._refresh_model_label()
        root_layout.addWidget(self.sidebar)

        self.main_panel = QFrame()
        self.main_panel.setObjectName("mainPanel")
        main_layout = QVBoxLayout(self.main_panel)
        main_layout.setContentsMargins(28, 16, 28, 12)
        main_layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.chat_title = QLabel("管束设计对话")
        self.chat_title.setObjectName("mainTitle")
        header.addWidget(self.chat_title)
        header.addStretch()
        self.clear_chat_button = QPushButton("清空对话")
        self.clear_chat_button.setObjectName("headerAction")
        self.clear_chat_button.setCursor(Qt.PointingHandCursor)
        self.clear_chat_button.clicked.connect(self.clear_chat)
        header.addWidget(self.clear_chat_button)
        main_layout.addLayout(header)

        # 图形化界面固定在界面上方，只有下方对话区滚动
        self.preview_host = QFrame()
        self.preview_host.setObjectName("previewHost")
        self.preview_layout = QVBoxLayout(self.preview_host)
        self.preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_layout.setSpacing(0)
        # 还没开始设计时整块预览区不占位，开始后才出现
        self.preview_host.hide()

        self.conversation = ChatTranscript()
        self.conversation.setObjectName("conversation")
        self.conversation.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.conversation.setMinimumHeight(260)

        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setObjectName("mainSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.preview_host)
        self.splitter.addWidget(self.conversation)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        # 预览区保底高度：低于这个值布管页的表格/画布会挤在一起
        self.preview_host.setMinimumHeight(self._preview_floor)
        self._apply_default_split()
        main_layout.addWidget(self.splitter, 1)

        composer_wrap = QWidget()
        self.composer_wrap = composer_wrap
        wrap_layout = QVBoxLayout(composer_wrap)
        wrap_layout.setContentsMargins(0, 8, 0, 0)
        wrap_layout.setSpacing(7)
        composer = QFrame()
        composer.setObjectName("composer")
        composer_layout = QHBoxLayout(composer)
        composer_layout.setContentsMargins(16, 8, 10, 8)
        composer_layout.setSpacing(8)
        self.prompt = MessageInput()
        self.prompt.setObjectName("composerInput")
        self.prompt.setPlaceholderText("描述你要做的操作，例如“换热管中心距改成34毫米”“重新布管，尽量多布”…")
        self.prompt.setFont(QFont("Microsoft YaHei UI", 11))
        self.prompt.setFrameShape(QFrame.NoFrame)
        self.prompt.send_requested.connect(self.send_note)
        composer_layout.addWidget(self.prompt, 1)
        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("sendButton")
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.clicked.connect(self.send_note)
        composer_layout.addWidget(self.send_button, 0, Qt.AlignBottom)
        wrap_layout.addWidget(composer)
        main_layout.addWidget(composer_wrap)
        root_layout.addWidget(self.main_panel, 1)

    def _refresh_model_label(self):
        if not hasattr(self, "model_label"):
            return
        if self.config.configured:
            self.model_label.setText(f"DeepSeek · {self.config.model}")
        else:
            self.model_label.setText("离线模式 · 未配置 DeepSeek")

    def _check_database(self):
        try:
            ok, message = self.repository.ping()
        except DatabaseUnavailable as exc:
            ok, message = False, str(exc)
        self.db_status = message
        self.db_ready = ok

    def _apply_style(self):
        self.setStyleSheet("""
        QMainWindow, QWidget { background:#ffffff; color:#1f2329; font-family:'Microsoft YaHei UI'; font-size:10.5pt; }
        #sidebar { background:#fafafa; border-right:1px solid #ececea; }
        #sidebar QLabel { background:transparent; }
        #sidebarTitle { font-size:15pt; font-weight:600; color:#1b1e23; padding:2px 6px 0 6px; }
        #sidebarSubtitle { color:#a2a6ad; font-size:9pt; padding:2px 6px 0 6px; }
        #sidebarSection { color:#a2a6ad; font-size:9pt; padding:16px 8px 6px 8px; }
        #footerLabel { color:#a8acb3; font-size:8.5pt; padding:1px 6px; }
        #mainPanel { background:#ffffff; }
        #mainTitle { font-size:14pt; font-weight:600; color:#1b1e23; padding:2px 0 10px 0; }
        #sectionTitle { font-size:13pt; font-weight:600; padding:2px 0 4px 0; }
        #conversation, #chatContent, #chatRow { background:#ffffff; border:none; }
        #assistantMessage, #userMessage { background:transparent; border:none; }
        #assistantAvatar { background:#eef4ff; color:#3b6fd4; border-radius:9px; font-size:8pt; font-weight:700; }
        #assistantName { color:#4a76cf; font-size:9pt; font-weight:600; }
        #userName { color:#a9b2c0; font-size:9pt; padding:0 6px 0 0; }
        #chatMessageText { color:#22262c; font-size:10.5pt; }
        #userBubble { background:#eaf1fe; border:none; border-radius:14px; }
        #userBubble QLabel { background:transparent; border:none; }
        #composer { background:#ffffff; border:1px solid #e2e3e6; border-radius:16px; }
        #composer:hover { border-color:#cfd6e2; }
        #composerInput { background:transparent; border:none; color:#1f2329; font-size:10.5pt; padding:5px 2px; }
        #shortcutHint { color:#a8acb3; font-size:8.5pt; }
        #previewCard { background:#ffffff; border:1px solid #e6e5e2; border-radius:16px; }
        #previewHost { background:#ffffff; border:1px solid #e8e8e5; border-radius:16px; }
        #previewHint { color:#9aa1ab; font-size:8.5pt; padding:0 6px 4px 6px; }
        #mainSplitter::handle { background:#f0efec; height:8px; }
        #mainSplitter::handle:hover { background:#e2e1dd; }
        #planCard { background:#ffffff; border:1px solid #e6e5e2; border-radius:16px; }
        #planTitle { font-size:11.5pt; font-weight:600; color:#1b1e23; }
        #planTable { background:#fafbfc; border:1px solid #eef0f3; border-radius:10px; }
        #planHead { color:#9aa1ab; font-size:9pt; }
        #planCell { color:#2b2f36; font-size:10pt; }
        #planCellStrong { color:#1b1e23; font-size:10pt; font-weight:600; }
        #planCellMuted { color:#6b7280; font-size:9.5pt; }
        #planBlock { background:#ffffff; border:1px solid #eef0f3; border-radius:9px; }
        #planRefTag { color:#5b6068; font-size:9.5pt; }
        #planCoord { color:#2458b8; font-size:9.5pt; }
        #planError { color:#b04a42; font-size:8.5pt; }
        #planCellEdit { background:#ffffff; border:1px solid #e2e3e6; border-radius:5px; padding:2px 4px; font-size:9.5pt; }
        #planCellEdit:focus { border-color:#2f6fe4; }
        #planCellCombo { background:#ffffff; border:1px solid #e2e3e6; border-radius:5px; padding:1px 16px 1px 4px; font-size:9.5pt; }
        #planCellCombo:hover { border-color:#c9d8ea; }
        #planLockedValue { color:#4a4f57; font-size:9.5pt; font-weight:600; }
        #planHint { color:#8f949c; font-size:9pt; }
        #planResult { color:#256b3a; font-size:10pt; }
        #planResultMuted { color:#8f949c; font-size:9.5pt; }
        #planPrimary { background:#2f6fe4; color:#ffffff; border:none; border-radius:9px; padding:8px 18px; font-weight:600; }
        #planPrimary:hover { background:#2a63cc; }
        #planPrimary:disabled { background:#e8eefb; color:#a9b8d4; }
        #planGhost { background:#ffffff; border:1px solid #e2e3e6; border-radius:9px; padding:8px 16px; color:#5f646c; }
        #planGhost:hover { background:#f5f7fa; }
        #planMutedBadge { background:#f2f3f5; color:#8f949c; border:1px solid #e6e7ea; border-radius:10px; padding:3px 9px; font-size:9pt; }
        #planFailedBadge { background:#fdf1f0; color:#a1443c; border:1px solid #e9c3bf; border-radius:10px; padding:3px 9px; font-size:9pt; }
        #statusBadge { background:#fff4d6; color:#805b10; border:1px solid #e1c36d; border-radius:10px; padding:3px 9px; font-size:9pt; }
        #keptBadge { background:#eaf7ee; color:#256b3a; border:1px solid #b7dfc4; border-radius:10px; padding:3px 9px; font-size:9pt; }
        QPushButton { background:#ffffff; border:1px solid #e2e3e6; border-radius:9px; padding:8px 14px; font-size:10pt; color:#2b2f36; }
        QPushButton:hover { background:#f5f7fa; border-color:#d5d9e0; }
        QPushButton:disabled { color:#b6bac1; background:#f7f7f6; border-color:#eeeeec; }
        #primarySideButton { text-align:left; background:#ffffff; border:1px solid #e3e4e7; border-radius:10px; padding:10px 13px; font-size:10.5pt; color:#2b2f36; }
        #primarySideButton:hover { background:#f4f8ff; border-color:#c9dbfb; color:#2458b8; }
        #sideAction { text-align:left; border:none; background:transparent; color:#5f646c; padding:8px 11px; border-radius:8px; }
        #sideAction:hover { background:#f0f1f3; color:#1b1e23; }
        #stageButton { text-align:left; border:none; background:transparent; color:#5f646c; padding:8px 11px; border-radius:8px; }
        #stageButton:hover { background:#f0f1f3; }
        #stageButton:disabled { color:#c5c8cd; background:transparent; }
        #tinyAction { border:none; background:transparent; color:#8f949c; padding:5px 7px; font-size:9pt; }
        #tinyAction:hover { color:#2458b8; background:#f1f5fd; border-radius:7px; }
        #headerAction { border:none; background:transparent; color:#8f949c; padding:6px 10px; border-radius:8px; }
        #headerAction:hover { color:#2458b8; background:#f1f5fd; }
        #sendButton { background:#2f6fe4; color:#ffffff; border:none; border-radius:10px; padding:9px 22px; font-weight:600; }
        #sendButton:hover { background:#2a63cc; }
        QTableWidget { background:#ffffff; border:1px solid #e6e5e2; border-radius:8px; alternate-background-color:#fbfbfa; gridline-color:#f0efec; }
        QHeaderView::section { background:#f7f7f5; color:#5b6068; padding:6px; border:none; border-right:1px solid #efeeec; border-bottom:1px solid #e6e5e2; font-size:9pt; font-weight:600; }
        QScrollBar:vertical { background:transparent; width:10px; margin:2px; }
        QScrollBar::handle:vertical { background:#dcdcd9; border-radius:5px; min-height:32px; }
        QScrollBar::handle:vertical:hover { background:#c9c9c5; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
        """)

    def append_chat(self, role, message):
        text = str(message)
        self.chat_history.append({"role": role, "content": text})
        self.conversation.append_message(role, text)

    _IMPORTANT_WORDS = ("失败", "错误", "不能", "冲突", "无效", "不存在", "无法")

    def notify(self, message):
        """操作反馈（选中行、布置元件、撤销……）只保留最新一条，避免连续操作刷屏。"""
        text = str(message)
        if not any(word in text for word in self._IMPORTANT_WORDS):
            if self.conversation.update_transient(text):
                if self.chat_history and self.chat_history[-1].get("transient"):
                    self.chat_history[-1]["content"] = text
                return
        self.chat_history.append({"role": "assistant", "content": text, "transient": True})
        self.conversation.append_message("assistant", text, transient=True)

    # ------------------------------------------------------------------ 启动流程
    def start_design(self):
        self._boot_session()

    def _boot_session(self, product_id: str | None = None):
        try:
            products = self.repository.list_products(80)
        except DatabaseUnavailable as exc:
            self.append_chat(
                "assistant",
                "无法连接正式数据库，未生成任何草稿：\n"
                f"{exc}\n"
                "排查：1) 确认本机 MySQL 已启动并监听 3306；2) 账号密码与正式程序 "
                "modules/buguan/buguan_ziyong/database_utils.py 一致（默认 root/123456）；"
                "3) 确认存在“产品设计活动库”。修好后重新点“开始管束设计”。",
            )
            return
        if not products:
            self.append_chat("assistant", "正式数据库里还没有产品记录，请先在正式程序中创建产品。")
            return
        if product_id is None:
            product_id = products[0]["产品ID"]
        try:
            product = self.repository.product(product_id)
            upstream = self.repository.upstream(product_id)
            params = self.repository.layout_params(product_id)
            defaults = self.repository.layout_defaults(product["产品型式"])
            config_rows = self.repository.center_distance_table()
            sheet_rows = self.repository.sheet_form("a")
        except (DatabaseUnavailable, Exception) as exc:  # noqa: BLE001
            self.append_chat("assistant", f"读取正式数据库失败：{exc}\n未生成草稿，请检查数据库后重试。")
            return

        params = self._merge_defaults(params, defaults, upstream)
        session = DesignSession(self.repository, product, upstream, self)
        if session.dn() is None:
            self.session = None
            self.pages.clear()
            self._clear_preview()
            self._clear_inline_card()
            self.append_chat(
                "assistant",
                "条件输入和已保存设计数据中都没有有效的公称直径；已停止启动管束设计，"
                "不会使用布管默认 DN。请先补齐条件输入后重试。",
            )
            return
        self.session = session
        self.session.stage_changed.connect(self._on_stage_changed)
        self.pages.clear()
        self._clear_preview()
        self._clear_inline_card()
        self.config_rows = config_rows
        self.sheet_rows = sheet_rows
        self.defaults = defaults
        self.chat_title.setText(self.session.header_text())

        # 管板型式页（含 R2 等结构尺寸）先建好，布管页才能拿到 DL 联动值
        sheet_page = self._build_sheet_page()
        self.pages[0] = sheet_page
        sheet_payload = sheet_page.to_payload()

        # 正式程序 My_Piping：BEM/NEN/AEM/NEN(H) 打开就停在“管板型式”，
        # 其余型式停在“布管”（`self.header.setCurrentIndex(0/1)`）
        self._initial_stage = self._pick_initial_stage()
        self._render_stage(self._initial_stage)

    def _pick_initial_stage(self) -> int:
        """正式程序 `My_Piping` 的初始 Tab：BEM/NEN/AEM/NEN(H) → 管板型式，其余 → 布管。"""
        product = str(getattr(self.session, "product_type", "") or "").strip().upper()
        return 0 if product in {"BEM", "NEN", "AEM", "NEN(H)"} else 1

    def _merge_defaults(self, params: dict, defaults: dict, upstream: dict) -> dict:
        merged: dict[str, dict] = {}
        for name, row in (params or {}).items():
            value = row.get("value")
            merged[name] = {
                "value": value,
                "unit": row.get("unit", ""),
                "source": "布管参数表" if str(value or "").strip() else "程序默认值",
            }
        for name, value in (defaults or {}).items():
            if name in {"公称直径", "公称直径 DN", "DN"}:
                continue
            if name not in merged or not str(merged[name].get("value") or "").strip():
                merged[name] = {"value": value, "unit": merged.get(name, {}).get("unit", ""), "source": "程序默认值"}
        # 前序模块数据优先：公称直径、是否以外径为基准
        dn = upstream.get("公称直径") or upstream.get("公称直径 DN")
        if dn and str(dn.get("value", "")).strip():
            merged["公称直径 DN"] = {
                "value": str(dn["value"]).strip(),
                "unit": dn.get("unit") or "mm",
                "source": dn.get("source") or "设计数据表",
            }
        basis = upstream.get("是否以外径为基准")
        if basis and str(basis.get("value", "")).strip() in {"是", "否"}:
            merged["是否以外径为基准"] = {"value": str(basis["value"]).strip(), "unit": "", "source": "通用数据表"}
        return merged

    # ------------------------------------------------------------------ 页面构建
    def _sheet_form_values(self) -> dict:
        page = self.pages.get(0)
        if isinstance(page, SheetFormStage):
            return {definition.name: definition.value for definition in page.defs}
        return {}

    def _build_sheet_page(self) -> SheetFormStage:
        existing = self.pages.get(0)
        if isinstance(existing, SheetFormStage):
            return existing
        page = SheetFormStage(
            self.repository, self.session.product_type, self.session.dn(),
        )
        page.keep_requested.connect(lambda: self.keep_current("管板型式"))
        page.parameters_changed.connect(lambda _values: self._on_stage_edited("管板型式"))
        return page

    def _build_layout_page(self) -> TubeLayoutPage:
        existing = self.pages.get(1)
        if isinstance(existing, TubeLayoutPage):
            return existing
        sheet_values = self._sheet_form_values()
        params = self._merge_defaults(
            self.repository.layout_params(self.session.product_id),
            self.defaults,
            self.session.upstream,
        )
        # 管板型式 → 布管：DL 由 DN 与 R2 决定
        if sheet_values:
            params.setdefault("布管限定圆 DL", {"value": "", "unit": "", "source": "联动计算"})
            params["布管限定圆 DL"]["value"] = self.session.layout_linkage(
                {"R2": sheet_values.get("R2", 8.0)}
            )["布管限定圆 DL"]
            params["布管限定圆 DL"]["source"] = "联动计算"
        apply_extracted_parameters(
            params, getattr(self, "_platform_extracted_parameters", {})
        )
        page = TubeLayoutPage(
            params,
            self.session.product_type,
            self.defaults,
            center_distance_rows=self.config_rows,
            sheet_form=sheet_values,
        )
        page.headless = self.headless
        page.keep_requested.connect(lambda: self.keep_current("布管"))
        page.status_message.connect(self.notify)
        page.state_changed.connect(lambda _info: self._on_stage_edited("布管"))
        page.pane_fullscreen_requested.connect(self.set_preview_pane_fullscreen)
        return page

    def _build_connection_page(self) -> TubeConnectionStage:
        existing = self.pages.get(2)
        if isinstance(existing, TubeConnectionStage):
            return existing
        page = TubeConnectionStage(self.repository)
        page.keep_requested.connect(lambda: self.keep_current("管-板连接"))
        page.parameters_changed.connect(lambda _values: self._on_stage_edited("管-板连接"))
        return page

    def _build_axial_page(self) -> AxialStage:
        existing = self.pages.get(3)
        if isinstance(existing, AxialStage):
            return existing
        layout_page = self.pages.get(1)
        length = 4500.0
        spacing = 200.0
        if isinstance(layout_page, TubeLayoutPage):
            try:
                length = float(layout_page.parameters["换热管公称长度 LN"]["value"])
            except (KeyError, TypeError, ValueError):
                pass
            try:
                spacing = float(layout_page.parameters["折流/支持板间距"]["value"])
            except (KeyError, TypeError, ValueError):
                pass
        connection = self.pages.get(2)
        thickness = 60.0
        if isinstance(connection, TubeConnectionStage):
            try:
                thickness = float(connection.values().get("管板厚度 δt", 60) or 60)
            except (TypeError, ValueError):
                pass
        page = AxialStage(length, spacing, thickness)
        page.keep_requested.connect(lambda: self.keep_current("轴向设计"))
        page.parameters_changed.connect(lambda _values: self._on_stage_edited("轴向设计"))
        return page

    def _ensure_page(self, index: int) -> QWidget:
        builders = {
            0: self._build_sheet_page,
            1: self._build_layout_page,
            2: self._build_connection_page,
            3: self._build_axial_page,
        }
        page = self.pages.get(index) or builders[index]()
        self.pages[index] = page
        if page.parent() is None:
            page.setParent(None)
        return page

    def _clear_preview(self) -> None:
        """把当前预览卡片卸下，同时保住页面对象，避免随卡片一起被销毁。"""
        if self._preview_pane_fullscreen:
            self.set_preview_pane_fullscreen(False)
        if self.card is None:
            return
        page = self.card.page
        self.card.layout().removeWidget(page)
        page.setParent(None)
        self.preview_layout.removeWidget(self.card)
        self.card.setParent(None)
        self.card.deleteLater()
        self.card = None

    def _clear_inline_card(self) -> None:
        """移除对话中的参数审核卡，但保留页面对象供来回切换。"""
        if self.inline_card is None:
            return
        page = self.inline_card.page
        self.inline_card.layout().removeWidget(page)
        page.setParent(None)
        self.conversation.remove_widget(self.inline_card)
        self.inline_card = None

    def set_preview_pane_fullscreen(self, enabled: bool) -> None:
        """让整个上方设计预览窗格占满右侧工作区。"""
        enabled = bool(enabled)
        if not enabled and self.card is not None and isinstance(self.card.page, TubeLayoutPage):
            self.card.page.set_pane_fullscreen(False, notify=False)
        self._preview_pane_fullscreen = enabled
        self.conversation.setVisible(not enabled)
        self.composer_wrap.setVisible(not enabled)
        if enabled:
            self.preview_host.show()
            self.splitter.setSizes([max(self.splitter.height(), 760), 0])
        else:
            self.conversation.show()
            self.composer_wrap.show()
            if self.preview_host.isVisible():
                self._apply_default_split()

    def _render_stage(self, index: int) -> None:
        if self.session is None:
            return
        page = self._ensure_page(index)
        self._clear_preview()
        self._clear_inline_card()
        stage = STAGES[index]
        if index in {0, 2}:
            self.preview_host.hide()
            self.inline_card = PreviewCard(stage, page, approved=self.session.approved[index])
            self.conversation.append_widget(self.inline_card)
        else:
            self.card = PreviewCard(stage, page, approved=self.session.approved[index])
            self.preview_layout.addWidget(self.card, 1)
            if self.preview_host.isHidden():
                self.preview_host.show()
                self._apply_default_split()
        self.session.current_index = index
        self._refresh_stage_buttons()

    def _on_stage_changed(self, index: int) -> None:
        self._refresh_stage_buttons()

    def _refresh_stage_buttons(self) -> None:
        if self.session is None:
            for button in self.stage_buttons:
                button.setEnabled(False)
                button.setStyleSheet("")
            return
        for index, button in enumerate(self.stage_buttons):
            # 与源程序 QTabWidget 一致：会话建立后四个 Tab 始终都能直接进入。
            button.setEnabled(True)
            if index == self.session.current_index:
                button.setStyleSheet(
                    "background:#eaf1fe;color:#2458b8;border:none;border-radius:8px;"
                    "padding:8px 11px;font-weight:600;text-align:left;"
                )
            elif self.session.approved[index]:
                button.setStyleSheet(
                    "background:transparent;color:#256b3a;border:none;border-radius:8px;"
                    "padding:8px 11px;text-align:left;"
                )
            else:
                button.setStyleSheet(
                    "background:transparent;color:#5f646c;border:none;border-radius:8px;"
                    "padding:8px 11px;text-align:left;"
                )

    def open_stage(self, index: int) -> None:
        if self.session is None:
            self.append_chat("assistant", "请先点击“开始管束设计”。")
            return
        if not 0 <= index < len(STAGES):
            return
        self._render_stage(index)

    def _on_stage_edited(self, stage: str) -> None:
        """已保留页面被修改时，只撤销本页确认；其它 Tab 仍可直接使用。"""
        if self.session is None:
            return
        index = STAGES.index(stage)
        if not self.session.approved[index]:
            return
        self.session.invalidate_stage(stage)
        self.append_chat(
            "assistant",
            f"检测到“{stage}”已修改，本页需要重新检查并保留。",
        )
        self._refresh_stage_buttons()

    # ------------------------------------------------------------------ 保留
    def keep_current(self, stage: str) -> None:
        if self.session is None:
            return
        index = STAGES.index(stage)
        page = self.pages.get(index)
        if page is None:
            return
        allowed, reason = self.session.can_keep(stage)
        if not allowed:
            if not self.headless:
                QMessageBox.information(self, "尚不能保留", reason)
            self.append_chat("assistant", reason)
            return
        issues = page.run_validation() if hasattr(page, "run_validation") else page.validate()
        if issues:
            if hasattr(page, "set_issues"):
                page.set_issues(issues)
            detail = "\n".join(
                f"• {item['field']}：{item['message']}"
                + (f"（推荐 {item['recommended']}）" if item.get("recommended") is not None else "")
                for item in issues
            )
            self.append_chat("assistant", f"“{stage}”有 {len(issues)} 项没通过校验，尚未写库：\n{detail}")
            return
        if not self.headless:
            if not self._confirm_keep(stage):
                return
        payload = page.to_payload()
        self.session.mark_kept(stage, payload)
        self._sync_downstream(stage)
        if self.session.complete:
            self.final_save()
            return
        self.append_chat("assistant", "数据保存成功")
        self._render_stage(self.session.current_index)

    def _build_keep_box(self, stage: str):
        """保留确认弹窗（按钮就是 是 / 否；文案不出现 Tab 这类界面术语）。"""
        from bundle.widgets import ConfirmDialog

        return ConfirmDialog(
            "确认保留",
            f"确认保留“{stage}”的当前内容吗？",
            "保留后可继续检查其他页面。",
            parent=self,
        )

    def _confirm_keep(self, stage: str) -> bool:
        dialog = self._build_keep_box(stage)
        return dialog.exec_() == QDialog.Accepted

    def _sync_downstream(self, stage: str) -> None:
        if stage == "管板型式":
            layout_page = self.pages.get(1)
            if isinstance(layout_page, TubeLayoutPage):
                sheet_payload = self.session.payloads.get("管板型式", {})
                linkage = self.session.layout_linkage(sheet_payload)
                layout_page.sheet_form = {d.name: d.value for d in self.pages[0].defs}
                layout_page.set_parameter(
                    "布管限定圆 DL", linkage["布管限定圆 DL"], "联动计算", run_linkage=False
                )
                # 保留时只给用户一条“数据保存成功”；联动重算在后台完成。
                layout_page.recompute(reason="")
        elif stage == "布管":
            axial = self.pages.get(3)
            layout_payload = self.session.payloads.get("布管", {})
            if isinstance(axial, AxialStage):
                parameters = layout_payload.get("parameters", {})
                length = parameters.get("换热管公称长度 LN", {}).get("value", "")
                spacing = parameters.get("折流/支持板间距", {}).get("value", "")
                if length:
                    axial.set_value("换热管公称长度 LN", length)
                if spacing:
                    axial.set_value("折流板间距", spacing)

    def final_save(self) -> None:
        if self.session is None or not self.session.complete:
            return
        plan = self.session.preview_statements()
        head = [
            f"产品 {self.session.product_id}（{self.session.product_type}）四个阶段已全部保留。",
            "即将在单个事务中写入正式数据库：",
            "• 产品设计活动表_管板形式表",
            "• 产品设计活动表_布管参数表（65 项）",
            "• 产品设计活动表_布管元件表（拉杆/挡板/滑道等坐标）",
            "• 产品设计活动表_布管输入表 / 布管结果表",
            "• 产品设计活动表_布管数量表（水平或竖直 + 显示）",
            "• 产品设计活动表_管板连接表",
            f"共 {len(plan)} 条 SQL。失败会自动回滚。",
        ]
        if self.headless:
            # 自动验收/截图模式只展示计划，绝不写正式库
            self.append_chat(
                "assistant",
                "\n".join(head) + "\n\n（当前为自动验收模式，只生成写库计划，未提交到数据库。）",
            )
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("写入正式数据库")
        dialog.setText("\n".join(head))
        dialog.setDetailedText("\n".join(plan[:80]))
        dialog.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        dialog.button(QMessageBox.Ok).setText("确认写入")
        dialog.button(QMessageBox.Cancel).setText("暂不写入")
        if dialog.exec_() != QMessageBox.Ok:
            self.append_chat("assistant", "已取消写入，草稿仍保留在本次对话中，数据库未改变。")
            return
        try:
            result = self.session.save()
        except (SaveFailed, DatabaseUnavailable) as exc:
            self.append_chat(
                "assistant",
                f"写库失败，已回滚，数据库未产生部分写入：{exc}\n"
                "请检查数据库连接/表结构后重新点击“保留”所属流程，或联系管理员。",
            )
            return
        except Exception as exc:  # noqa: BLE001
            self.append_chat("assistant", f"写库异常并已回滚：{exc}")
            return
        self.append_chat(
            "assistant",
            "数据保存成功",
        )
        self._refresh_stage_buttons()

    # ------------------------------------------------------------------ 对话
    def send_note(self):
        text = self.prompt.toPlainText().strip()
        if not text:
            return
        self.prompt.clear()
        if self.worker is not None and self.worker.isRunning():
            self.append_chat("assistant", "上一条要求还在处理中，请稍候。")
            return
        self.append_chat("user", text)
        self._last_user_text = text
        if self.session is None:
            self.append_chat("assistant", "请先点击左侧“开始管束设计”，读取数据库并生成草稿后才能修改。")
            return
        if self.config.configured:
            # 配置模型后，开放式要求必须交给 Agent 结合当前图形选择工具；
            # 只有“确认/放弃/保留”等无需理解的控制命令立即本地执行。
            if is_immediate_local_control(text) and self._handle_local_command(text):
                return
            client = DeepSeekClient(self.config)
            # 状态提示（已选中第 N 行……）不进入模型上下文，避免占满 token
            history = [
                {"role": item["role"], "content": item["content"]}
                for item in self.chat_history[:-1]
                if not item.get("transient")
            ]
            context = self._ai_context()
            layout_state = self._layout_state()
            stage = self.session.current_stage
            self.send_button.setEnabled(False)
            self._start_worker(
                lambda: client.chat(history, context, stage, text, layout_state),
                self._handle_ai_result,
            )
            return
        if self._handle_local_command(text):
            return
        self.append_chat(
            "assistant",
            "离线模式只识别明确的操作（例如“换热管中心距改成34毫米”“重新布管，尽量多布”"
            "“外围对称布置8根拉杆”“删除离隔板槽最近的两排换热管”“恢复刚才删除的换热管”"
            "“保留当前方案”“把刚才的修改撤销”）。"
            "如需自由问答，请在 AI 设置中填写 DeepSeek API Key。",
        )

    def _layout_state(self) -> dict:
        """给模型看的布管现状：管孔数、已布置元件统计——只读快照，不含坐标。"""
        page = self.pages.get(1)
        if not isinstance(page, TubeLayoutPage):
            return {}
        counts: dict[str, int] = {}
        for component in page.components:
            label = COMPONENT_LABEL.get(component.get("kind"), "元件")
            counts[label] = counts.get(label, 0) + 1
        names: set[str] = set()
        for kind in KIND_LABEL:
            names.update(OPTION_FIELDS.get(kind, ()))
        values = {}
        for name in names:
            text = page.parameters.get(name, {}).get("value")
            if str(text or "").strip():
                values[name] = str(text).strip()
        return {
            "hole_count": len(page.current_centers()),
            "selected_holes": len(page.selected),
            "placed_components": counts,
            "product_type": page.product_type,
            "current_values": values,
            # 给 Agent 看真实布管字符图；模型据此选行列号，程序再查表和校验。
            "plan_view": page.plan_view_text(),
        }

    def _ai_context(self) -> dict:
        context: dict[str, dict] = {}
        if self.session is None:
            return context
        for index, stage in enumerate(STAGES):
            page = self.pages.get(index)
            if page is None:
                continue
            if isinstance(page, TubeLayoutPage):
                context[stage] = {
                    name: {
                        "value": data.get("value"),
                        "unit": data.get("unit", ""),
                        "editable": name != "布管限定圆 DL",
                    }
                    for name, data in page.parameters.items()
                }
            else:
                context[stage] = {
                    definition.name: {
                        "value": definition.value,
                        "unit": definition.unit,
                        "editable": definition.kind != "readonly",
                    }
                    for definition in page.defs
                }
        return context

    # ---------------- 本地命令（不依赖 API Key）----------------
    def _handle_local_command(self, text: str) -> bool:
        page = self.pages.get(self.session.current_index) if self.session else None
        layout_page = self.pages.get(1)
        compact = re.sub(r"\s+", "", text)

        if any(word in compact for word in ("撤销", "撤回")):
            if isinstance(layout_page, TubeLayoutPage):
                layout_page.undo()
                self.append_chat("assistant", "已撤销上一步布管操作。")
            else:
                self.append_chat("assistant", "当前页没有可撤销的操作。")
            return True

        if compact in {"保留", "保留当前方案", "确认保留"} or "保留当前" in compact:
            self.keep_current(self.session.current_stage)
            return True

        if compact in {"确认布置", "确认方案", "执行方案", "按这个布置", "就按这个布置"}:
            pending = [card for card in self.placement_cards if card.badge.text() == "待确认"]
            if pending:
                self._confirm_placement(pending[-1])
            else:
                holes = [card for card in self.hole_cards if card.badge.text() == "待确认"]
                if holes:
                    self._confirm_hole_card(holes[-1])
                else:
                    self.append_chat("assistant", "当前没有待确认的布置方案。")
            return True

        if compact in {"放弃方案", "取消方案", "不布置了"}:
            pending = [card for card in self.placement_cards if card.badge.text() == "待确认"]
            if pending:
                self._discard_placement(pending[-1])
            else:
                holes = [card for card in self.hole_cards if card.badge.text() == "待确认"]
                if holes:
                    self._discard_hole_card(holes[-1])
                else:
                    self.append_chat("assistant", "当前没有待确认的布置方案。")
            return True

        if "使用推荐值" in compact or "采用推荐" in compact:
            if isinstance(page, TubeLayoutPage) and page.issues:
                issue = next((i for i in page.issues if i.get("recommended") is not None), None)
                if issue:
                    page.apply_recommendation(issue["field"], issue["recommended"])
                    self.append_chat("assistant", f"已采用推荐值：{issue['field']} = {issue['recommended']}。")
                    return True
            self.append_chat("assistant", "当前没有问题项需要采用推荐值。")
            return True

        ui_action = self._parse_ui_words(compact)
        if ui_action is not None:
            notes = self._run_ui_actions([ui_action])
            self.append_chat("assistant", "\n".join(notes) or "已执行。")
            return True

        if isinstance(layout_page, TubeLayoutPage):
            if any(word in compact for word in ("重新布管", "尽量多布", "多布")):
                target = None
                match = re.search(r"至少(\d+)根", compact)
                if match:
                    target = int(match.group(1))
                outcome = layout_page.max_tubes(target)
                if outcome.get("ok"):
                    self.append_chat(
                        "assistant",
                        f"已按正式程序布管接口重新计算：中心距 S={outcome['S']:g}，"
                        f"共 {outcome['count']} 个管孔。"
                        + ("已满足数量要求。" if target and outcome["count"] >= target else ""),
                    )
                else:
                    self.append_chat("assistant", outcome.get("message", "布管未成功。"))
                return True

            hole_op = self._parse_hole_words(compact)
            if hole_op is not None:
                self.append_chat(
                    "assistant",
                    f"我按“{hole_op.label}｜{hole_op.describe()}”算了一版方案，"
                    "请先过目；确认后直接在布管图上执行。",
                )
                self._show_hole_card([hole_op])
                return True

            item = self._parse_placement_words(compact)
            if item is not None:
                self.append_chat(
                    "assistant",
                    f"我按“{item.label} × {item.count}”生成了一版布置方案，请先过目；"
                    "确认后我直接在布管图上布置。",
                )
                self._show_placement_card([item])
                return True
        if "为什么" in compact and "不通过" in compact:
            issues = page.validation_issues() if hasattr(page, "validation_issues") else []
            if issues:
                detail = "\n".join(
                    f"• {item['field']}：{item['message']}"
                    + (f"（推荐 {item['recommended']}）" if item.get("recommended") is not None else "")
                    for item in issues
                )
                self.append_chat("assistant", f"当前不通过的原因：\n{detail}")
            else:
                self.append_chat("assistant", "当前页参数校验全部通过，没有阻塞项。")
            return True

        return self._handle_parameter_sentence(text)

    # 离线也能布置元件：把“4 根螺纹拉杆、直径 16，均布在靠近壳壁的管孔上”解析成方案
    _PLACEMENT_WORDS = (
        ("自由拉杆", "free_rod"),
        ("中间挡管", "block_tube"),
        ("旁路挡板", "bypass"),
        ("中间挡板", "center_baffle"),
        ("滑道", "slide"),
        ("防冲板", "impingement"),
        ("吊环螺钉", "screw_ring"),
        ("折流板", "baffle"),
        ("拉杆", "rod"),
    )
    _PLACEMENT_VERBS = ("布置", "摆放", "摆", "放", "增加", "加", "均布", "设置", "安装", "来")

    # 离线也能删/补换热管：“删除离隔板槽最近的两行换热管”直接算成方案
    _CN_NUMBERS = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
                   "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

    def _parse_hole_words(self, compact: str) -> HoleOp | None:
        """把自然语言里的“删/补换热管”解析成 HoleOp（只给区域，坐标由程序算）。"""
        if not any(word in compact for word in ("换热管", "管孔", "管子")):
            return None
        # “把拉杆恢复为换热管”里的“换热管”是目标类型，不是要增删换热管
        if self._kind_from_text(compact) and any(
            word in compact
            for word in ("恢复为换热管", "转为换热管", "还原为换热管", "变回换热管", "改回换热管")
        ):
            return None
        if any(word in compact for word in ("怎么", "如何", "为什么", "吗", "？", "?")):
            return None
        restore = any(word in compact for word in ("恢复", "还原", "补回", "补上", "加回"))
        delete = any(word in compact for word in ("删除", "删掉", "去掉", "清除", "移除", "删"))
        if not (restore or delete):
            return None
        # “恢复刚才删除的换热管”里也有“删除”二字，恢复优先
        op = "restore" if restore else "delete"

        region = ""
        if "隔板槽" in compact or "分程隔板" in compact or "槽" in compact:
            region = "groove"
        elif "壳壁" in compact or "最外" in compact or "外圈" in compact or "外缘" in compact:
            region = "near_shell"
        elif "中心" in compact or "圆心" in compact:
            region = "center"
        elif "上方" in compact or "顶部" in compact or "顶上" in compact:
            region = "top"
        elif "下方" in compact or "底部" in compact:
            region = "bottom"
        elif "左侧" in compact or "左边" in compact:
            region = "left"
        elif "右侧" in compact or "右边" in compact:
            region = "right"
        elif "选中" in compact:
            region = "selected"
        if not region:
            # 没指定位置：恢复就是把删掉的都还原，删除默认从隔板槽两侧起
            region = "any" if op == "restore" else "groove"

        rows = 1
        match = re.search(r"([0-9]+|[一二两三四五六七八九十])\s*(?:排|行|列|圈)", compact)
        if match:
            token = match.group(1)
            rows = int(token) if token.isdigit() else self._CN_NUMBERS.get(token, 1)

        count = 0
        match = re.search(r"([0-9]+)\s*(?:根|个|孔)", compact)
        if match:
            count = int(match.group(1))
        return HoleOp(op=op, region=region, count=count, rows=max(1, rows))

    def _parse_placement_words(self, compact: str) -> PlacementItem | None:
        # 纯咨询（“拉杆一般怎么布置？”）不生成方案，避免把提问当成指令
        if any(word in compact for word in ("怎么", "如何", "为什么", "吗", "？", "?")):
            return None
        for word, kind in self._PLACEMENT_WORDS:
            if word not in compact:
                continue
            if not any(verb in compact for verb in self._PLACEMENT_VERBS):
                continue

            options: dict = {}
            if kind in {"rod", "free_rod"}:
                if "螺纹" in compact:
                    options["拉杆形式"] = "螺纹拉杆"
                elif "焊接" in compact:
                    options["拉杆形式"] = "焊接拉杆"
                diameter = re.search(r"直径\s*(?:为|是|=|:)?\s*(\d+(?:\.\d+)?)", compact) \
                    or re.search(r"φ\s*(\d+(?:\.\d+)?)", compact)
                if diameter:
                    options["拉杆直径"] = diameter.group(1)
            elif kind == "slide":
                if "圆钢" in compact:
                    options["滑道形式"] = "圆钢滑道"
                elif "板式" in compact:
                    options["滑道形式"] = "板式滑道"
            elif kind == "impingement":
                if "焊接" in compact:
                    options["防冲板形式"] = "焊接式"
                    kind = "impingement_folded"
                elif "圆弧" in compact:
                    options["防冲板形式"] = "圆弧形"
                elif "平板" in compact:
                    options["防冲板形式"] = "平板形"

            match = re.search(r"(\d+)\s*(?:根|块|个|条|颗|件)", compact)
            if match:
                count = int(match.group(1))
            elif any(word in compact for word in ("几", "若干", "一些")):
                count = 4
            else:
                count = 1

            if "外围" in compact or "对称" in compact:
                region = "edge_symmetric"
            elif "最外" in compact or "外圈" in compact or "轮廓" in compact:
                region = "outline"
            elif "壳壁" in compact:
                region = "near_shell"
            elif "上方" in compact or "顶部" in compact or "顶上" in compact:
                region = "top"
            elif "下方" in compact or "底部" in compact:
                region = "bottom"
            elif "左侧" in compact or "左边" in compact:
                region = "left"
            elif "右侧" in compact or "右边" in compact:
                region = "right"
            elif "均布" in compact or "均分" in compact:
                region = "uniform"
            else:
                region = "any"

            return PlacementItem(
                kind=kind,
                count=count,
                region=normalize_region(region, kind),
                options=options,
            )
        return None

    def _handle_parameter_sentence(self, text: str) -> bool:
        """把“换热管中心距改成34毫米”这类句子落到对应 Tab 的参数上。"""
        aliases: dict[str, list[str]] = {}
        for alias, canonical in FIELD_ALIASES.items():
            aliases.setdefault(canonical, []).append(alias)
        candidates: list[tuple[int, str, str, str]] = []
        for index, stage in enumerate(STAGES):
            page = self.pages.get(index)
            if page is None:
                continue
            if isinstance(page, TubeLayoutPage):
                for name in page.parameters:
                    names = [name] + aliases.get(name, [])
                    candidates.append((max(len(n) for n in names), stage, name, "layout"))
            else:
                for definition in page.defs:
                    names = [definition.name] + aliases.get(definition.name, [])
                    candidates.append((max(len(n) for n in names), stage, definition.name, "stage"))
        candidates.sort(reverse=True)
        for _length, stage, name, kind in candidates:
            matched = next((alias for alias in sorted([name] + aliases.get(name, []), key=len, reverse=True)
                            if alias and alias in text), None)
            if not matched:
                continue
            suffix = text.split(matched, 1)[1]
            page = self.pages.get(STAGES.index(stage))
            number = re.search(r"(-?\d+(?:\.\d+)?)", suffix)
            value = None
            if kind == "layout":
                options = self._layout_options(page, name)
                if options:
                    value = next((option for option in options if option in suffix), None)
                if value is None and number:
                    value = number.group(1)
            else:
                options = next((d.options for d in page.defs if d.name == name), ())
                if options:
                    value = next((option for option in options if option in suffix), None)
                if value is None and number:
                    value = number.group(1)
            if value is None:
                continue
            self._apply_parameter(stage, name, value)
            return True
        return False

    @staticmethod
    def _layout_options(page: TubeLayoutPage, name: str) -> tuple[str, ...]:
        from bundle.params import spec_for
        return spec_for(name, page.product_type, page.parameters).options

    def _apply_parameter(self, stage: str, name: str, value) -> None:
        page = self.pages.get(STAGES.index(stage))
        if isinstance(page, TubeLayoutPage):
            old = page.parameters.get(name, {}).get("value")
            changed = page.set_parameter(name, str(value), "AI 对话修改")
            page.recompute(reason=f"修改 {name}")
            self.append_chat(
                "assistant",
                f"已把“{stage}｜{name}”从 {old} 改为 {value}，并按正式程序接口重新布管"
                f"（当前 {len(page.current_centers())} 个管孔）。尚未写库。",
            )
        else:
            old = next((d.value for d in page.defs if d.name == name), None)
            page.set_value(name, value)
            page.refresh_preview()
            self.append_chat("assistant", f"已把“{stage}｜{name}”从 {old} 改为 {value}。尚未写库。")
        self._on_stage_edited(stage)

    # ---------------- 模型结果 ----------------
    def _handle_ai_result(self, result) -> None:
        if self.session is None:
            return
        result = result if isinstance(result, dict) else {}
        reply = str(result.get("reply", "")).strip()
        actions = result.get("actions", []) or []
        applied, rejected = [], []
        for action in actions:
            stage = str(action.get("stage", "")).strip()
            parameter = str(action.get("parameter", "")).strip()
            if stage not in STAGES or parameter not in CANONICAL_FIELDS.get(stage, set()):
                rejected.append(f"{stage}｜{parameter}：不属于该阶段的参数")
                continue
            page = self._ensure_page(STAGES.index(stage))
            try:
                if isinstance(page, TubeLayoutPage):
                    page.set_parameter(parameter, action.get("value"), "AI 对话修改")
                    page.recompute(reason=f"修改 {parameter}")
                else:
                    page.set_value(parameter, action.get("value"))
                    page.refresh_preview()
                applied.append(f"{stage}｜{parameter} = {action.get('value')}")
                self._on_stage_edited(stage)
            except Exception as exc:  # noqa: BLE001
                rejected.append(f"{stage}｜{parameter}：{exc}")
        lines = [reply or "我已检查这条要求。"]
        if applied:
            lines.append("\n已更新草稿（未写库）：")
            lines.extend(f"• {item}" for item in applied)
        if rejected:
            lines.append("\n未执行：")
            lines.extend(f"• {item}" for item in rejected)

        items: list[PlacementItem] = []
        placement_rejected = list(result.get("placement_rejected") or [])
        for raw in result.get("placements", []) or []:
            if not isinstance(raw, dict):
                continue
            kind = normalize_kind(raw.get("kind"))
            if kind is None:
                raw_kind = str(raw.get("kind") or "").strip()
                if raw_kind:
                    placement_rejected.append(f"不认识的元件「{raw_kind}」")
                continue
            try:
                items.append(PlacementItem(
                    kind=kind,
                    count=int(raw.get("count", 1) or 1),
                    region=normalize_region(raw.get("region"), kind),
                    options=dict(raw.get("options") or {}),
                    note=raw.get("note", ""),
                ))
            except (TypeError, ValueError):
                continue
        if items:
            lines.append("\n方案已生成，图上已高亮选中的换热管，确认后布置。")
        if placement_rejected:
            lines.append("\n方案中未采纳的部分：")
            lines.extend(f"• {item}" for item in placement_rejected)

        # 换热管增删：模型只给“哪一片、几根”，管孔由程序按当前布管结果算
        hole_ops, parsed_hole_rejected = parse_hole_ops(result.get("hole_ops", []) or [])
        hole_rejected = list(result.get("hole_rejected") or []) + parsed_hole_rejected
        if hole_ops:
            lines.append("\n换热管调整方案已生成，图上已圈出要处理的管孔，确认后执行。")
        if hole_rejected:
            lines.append("\n换热管调整未采纳的部分：")
            lines.extend(f"• {item}" for item in hole_rejected)

        # 界面操作：用户能点的按钮，模型同样可以让我点（清空选中、全选、切阶段…）
        ui_actions, ui_rejected = parse_ui_actions(result.get("ui_actions", []))
        ui_notes = self._run_ui_actions(ui_actions) if ui_actions else []
        if ui_notes:
            lines.append("\n界面操作：")
            lines.extend(f"• {item}" for item in ui_notes)
        if ui_rejected:
            lines.append("\n界面操作未采纳的部分：")
            lines.extend(f"• {item}" for item in ui_rejected)

        self.append_chat("assistant", "\n".join(lines))
        if hole_ops:
            self._show_hole_card(hole_ops)
        if items:
            self._show_placement_card(items)

    # ---------------- 元件布置方案（先过目，再落地）----------------
    def _show_placement_card(self, items: list[PlacementItem]) -> None:
        """把方案渲染成卡片；图形此时还没有任何改动。"""
        page = self.pages.get(1)
        if not isinstance(page, TubeLayoutPage):
            if self.session is None:
                self.append_chat("assistant", "请先点击“开始管束设计”。")
                return
            page = self._ensure_page(1)
        preview = page.preview_placement(items)
        card = PlacementPlanCard(items, preview, page=page)
        card.confirm_requested.connect(self._confirm_placement)
        card.discard_requested.connect(self._discard_placement)
        self.placement_cards.append(card)
        self.conversation.append_widget(card)

    def _placement_page(self) -> TubeLayoutPage | None:
        page = self.pages.get(1)
        return page if isinstance(page, TubeLayoutPage) else None

    def _confirm_placement(self, card: PlacementPlanCard) -> None:
        page = self._placement_page()
        if page is None:
            card.mark_applied({"ok": False, "rows": [], "message": "布管页尚未生成"})
            return
        result = page.apply_placement_plan(card.items)
        card.mark_applied(result)
        if not result.get("ok"):
            return
        # 布置改动了布管内容：只撤销“布管”本页的已保留状态。
        self._on_stage_edited("布管")
        # 让用户直接看到图形结果：当前不在布管页就切过去
        if self.session is not None and self.session.current_index != 1:
            self.open_stage(1)
        elif self.card is not None:
            # 图形就在上方固定预览区，把下方对话滚到底即可
            self.conversation._scroll_to_bottom()
        self.notify(
            f"方案已落地：共布置 {sum(row['placed'] for row in result['rows'])} 个元件，"
            f"当前 {result.get('holes_after', 0)} 个换热管孔"
        )

    def _discard_placement(self, card: PlacementPlanCard) -> None:
        card.mark_discarded()
        page = self._placement_page()
        if page is not None:
            # 方案作废，把图上高亮的参照管也取消掉
            page.select_centers([])
        self.notify("已放弃这版布置方案，布管图没有改动")

    # ---------------- 换热管增删方案（先过目，再执行）----------------
    def _show_hole_card(self, ops) -> None:
        page = self.pages.get(1)
        if not isinstance(page, TubeLayoutPage):
            if self.session is None:
                self.append_chat("assistant", "请先点击“开始管束设计”。")
                return
            page = self._ensure_page(1)
        preview = page.preview_hole_ops(ops)
        card = HolePlanCard(ops, preview, page=page)
        card.confirm_requested.connect(self._confirm_hole_card)
        card.discard_requested.connect(self._discard_hole_card)
        self.hole_cards.append(card)
        self.conversation.append_widget(card)

    def _confirm_hole_card(self, card: HolePlanCard) -> None:
        page = self._placement_page()
        if page is None:
            card.mark_applied({"ok": False, "rows": [], "message": "布管页尚未生成"})
            return
        result = page.apply_hole_ops(card.ops)
        card.mark_applied(result)
        if not result.get("ok"):
            return
        self._on_stage_edited("布管")
        if self.session is not None and self.session.current_index != 1:
            self.open_stage(1)
        elif self.card is not None:
            self.conversation._scroll_to_bottom()
        self.notify(
            f"换热管已更新：当前 {result.get('holes_after', 0)} 个换热管孔"
        )

    def _discard_hole_card(self, card: HolePlanCard) -> None:
        card.mark_discarded()
        page = self._placement_page()
        if page is not None:
            page.select_centers([])
        self.notify("已放弃这版换热管调整方案，布管图没有改动")

    # ---------------- 界面操作（用户能点的按钮，Agent 都能按）----------------
    def _ui_action_page(self) -> TubeLayoutPage | None:
        page = self._placement_page()
        if page is None and self.session is not None:
            candidate = self._ensure_page(1)
            if isinstance(candidate, TubeLayoutPage):
                page = candidate
        return page

    def _run_ui_actions(self, actions) -> list[str]:
        """执行一串界面动作；返回给人看的执行说明（逐条）。"""
        notes: list[str] = []
        page = self._ui_action_page()
        for action in actions or []:
            name = getattr(action, "name", "")
            region = getattr(action, "region", "") or ""
            rows = int(getattr(action, "rows", 1) or 1)
            count = int(getattr(action, "count", 0) or 0)

            if name == "clear_selection":
                if page is None:
                    notes.append("还没有布管图，无需取消选中。")
                else:
                    had = len(page.selected)
                    page.clear_selection()
                    notes.append(f"已取消全部选中（原先选中 {had} 个）。")
                continue
            if name == "select_all":
                if page is None:
                    notes.append("当前还没有布管图。")
                else:
                    centers = page.current_centers()
                    page.select_centers(centers)
                    notes.append(f"已选中全部 {len(centers)} 个换热管。")
                continue
            if name == "select_region":
                if page is None:
                    notes.append("当前还没有布管图。")
                else:
                    centers = page.select_region(region or "near_shell", rows, count)
                    where = HOLE_REGIONS.get(region or "near_shell", region or "指定区域")
                    notes.append(f"已选中{where}的 {len(centers)} 个管孔。")
                continue
            if name == "select_tubes":
                if page is None:
                    notes.append("当前还没有布管图。")
                else:
                    tubes = list(getattr(action, "tubes", []) or [])
                    centers, problems = page.centers_for_refs(tubes, "select")
                    if centers:
                        page.select_centers(centers)
                    note = f"已按行列号选中 {len(centers)} 个管孔。"
                    if problems:
                        note += "没落上的：" + "；".join(problems[:4])
                    notes.append(note)
                continue
            if name == "select_removed":
                if page is None:
                    notes.append("还没有布管图。")
                else:
                    centers = page.removed_centers()
                    page.select_centers(centers)
                    notes.append(f"已选中 {len(centers)} 个已删除的管孔（可以说“恢复选中的换热管”）。")
                continue
            if name == "invert_selection":
                if page is None:
                    notes.append("还没有布管图。")
                else:
                    alive = set(page.current_centers())
                    rest = sorted(alive - set(page.selected), key=lambda c: (-c[1], c[0]))
                    page.select_centers(rest)
                    notes.append(f"已反选，当前选中 {len(rest)} 个。")
                continue
            if name in {"delete_selected", "restore_selected"}:
                if page is None:
                    notes.append("还没有布管图。")
                    continue
                op = HoleOp(
                    op="restore" if name == "restore_selected" else "delete",
                    region="selected",
                )
                self._show_hole_card([op])
                notes.append("已生成换热管调整方案，点“确认执行”后就动图。")
                continue
            if name == "delete_components":
                if page is None:
                    notes.append("还没有布管图。")
                else:
                    page.delete_selected()
                    notes.append("已删除选中的内容（元件/管孔）。")
                continue
            if name == "undo":
                if page is None:
                    notes.append("还没有可撤销的操作。")
                else:
                    page.undo()
                    notes.append("已撤销上一步。")
                continue
            if name == "redraw":
                if page is None:
                    notes.append("还没有布管图。")
                else:
                    page.recompute(reason="按你的要求重新布管")
                    notes.append(f"已重新布管，当前 {len(page.current_centers())} 个管孔。")
                continue
            if name == "max_tubes":
                if page is None:
                    notes.append("还没有布管图。")
                else:
                    outcome = page.max_tubes(count or None)
                    notes.append(
                        f"已按最大数量重新布管：S={outcome.get('S', 0):g}，"
                        f"共 {outcome.get('count', 0)} 个管孔。"
                        if outcome.get("ok") else outcome.get("message", "布管未成功。")
                    )
                continue
            if name in {"fit", "zoom_in", "zoom_out"}:
                if page is None:
                    notes.append("还没有布管图。")
                else:
                    if name == "fit":
                        page.view.fit_all()
                        notes.append("已让布管图适应窗口。")
                    else:
                        factor = 1.15 if name == "zoom_in" else 1 / 1.15
                        page.view.scale(factor, factor)
                        notes.append("已放大布管图。" if name == "zoom_in" else "已缩小布管图。")
                continue
            if name == "switch_stage":
                stage = str(getattr(action, "stage", "") or "").strip()
                if self.session is None:
                    notes.append("请先点击左侧“开始管束设计”。")
                elif stage in STAGES:
                    self.open_stage(STAGES.index(stage))
                    notes.append(f"已切到“{stage}”。")
                else:
                    notes.append(f"没有叫“{stage}”的阶段，可选：{'、'.join(STAGES)}。")
                continue
            if name == "keep_stage":
                if self.session is None:
                    notes.append("请先点击左侧“开始管束设计”。")
                else:
                    stage = str(getattr(action, "stage", "") or "").strip()
                    stage = stage if stage in STAGES else self.session.current_stage
                    self.keep_current(stage)
                    notes.append(f"已按“保留”处理“{stage}”。")
                continue
            if name == "dump_holes":
                if page is None:
                    notes.append("当前还没有布管结果。")
                else:
                    rows_data = page.hole_coordinates()
                    self.conversation.append_widget(HoleCoordinateCard(rows_data))
                    notes.append(f"已列出全部 {len(rows_data)} 个管孔的绝对坐标，可直接复制成表格。")
                continue
            if name in {"dump_components", "remove_components", "convert_to_tube"}:
                if page is None:
                    notes.append("当前还没有布管结果。")
                    continue
                kind = str(getattr(action, "kind", "") or "")
                if name == "dump_components":
                    data = page.component_coordinates(kind)
                    if not data["rows"]:
                        notes.append(
                            f"图上还没有{data['label']}。" if kind else "图上还没有布置任何元件。"
                        )
                    else:
                        self.conversation.append_widget(ComponentCoordinateCard(data))
                        notes.append(
                            f"已列出{data['label']} {len(data['rows'])} 个："
                            "规格 / 形式、所在行列号、绝对坐标都在表里，可一键复制。"
                        )
                    continue
                outcome = page.remove_components(kind)
                if outcome.get("ok"):
                    notes.append(
                        f"{outcome['message']}，当前 {outcome['holes']} 个换热管孔。"
                    )
                else:
                    notes.append(outcome.get("message", "没有可删除的元件。"))
                continue
            if name == "set_symmetry":
                if page is None:
                    notes.append("还没有布管图。")
                else:
                    on = str(getattr(action, "value", "") or "").strip().lower() not in {
                        "关", "off", "false", "0", "否", "不"
                    }
                    page.set_symmetry(on)
                    notes.append("已勾上“对称分布”。" if on else "已取消“对称分布”。")
                continue
            if name == "restore_all":
                if page is None:
                    notes.append("还没有布管图。")
                else:
                    page.restore_tubes()
                    notes.append(f"已恢复全部，当前 {len(page.current_centers())} 个换热管孔。")
                continue
            if name == "clear_chat":
                self.clear_chat()
                notes.append("对话已清空。")
                continue
            if name == "start_design":
                self.start_design()
                notes.append("已开始管束设计：读取正式库前序数据并生成草稿。")
                continue
            notes.append(f"没有实现的操作：{name}")
        self.conversation._scroll_to_bottom()
        return notes

    # 离线也认这些界面操作（和模型给的 ui_actions 走同一条执行路径）
    def _kind_from_text(self, compact: str) -> str:
        """句子里提到的元件类型（“自由拉杆”先于“拉杆”，按 _PLACEMENT_WORDS 的顺序）。"""
        for word, kind in self._PLACEMENT_WORDS:
            if word in compact:
                return kind
        return ""

    def _parse_ui_words(self, compact: str) -> UIAction | None:
        if any(word in compact for word in ("取消全选", "清空选中", "取消选中", "全部取消选中")):
            return UIAction(name="clear_selection")
        if "反选" in compact:
            return UIAction(name="invert_selection")
        if any(word in compact for word in ("全选", "选中全部", "全部选中")):
            return UIAction(name="select_all")

        # 元件类：要的是拉杆就给拉杆的数据字典，不再是换热管表；
        # “把拉杆恢复为换热管”= 删掉拉杆并把孔还回去（源程序里拉杆本来就占一个管孔）。
        element = self._kind_from_text(compact)
        if element and any(word in compact for word in ("恢复为换热管", "转为换热管", "还原为换热管",
                                                         "变回换热管", "改回换热管", "恢复成换热管")):
            return UIAction(name="convert_to_tube", kind=element)
        if element and any(word in compact for word in ("删除", "删掉", "去掉", "清除", "清掉", "移除", "取消")):
            if "换热管" not in compact and "管孔" not in compact:
                return UIAction(name="remove_components", kind=element)
        if "元件" in compact and any(word in compact for word in ("删除", "删掉", "清空", "去掉")):
            return UIAction(name="remove_components")

        if "坐标" in compact or "数据字典" in compact or "元件数据" in compact:
            if element:
                return UIAction(name="dump_components", kind=element)
            return UIAction(name="dump_holes")
        if "撤销" in compact:
            return UIAction(name="undo")
        if "重绘" in compact or ("重新布管" in compact and "多布" not in compact):
            return UIAction(name="redraw")
        if "全屏" in compact or "适应窗口" in compact:
            return UIAction(name="fit")
        if "放大" in compact:
            return UIAction(name="zoom_in")
        if "缩小" in compact:
            return UIAction(name="zoom_out")
        if any(word in compact for word in ("选中已删除", "选中已删掉的", "选中删掉的")):
            return UIAction(name="select_removed")
        if "对称分布" in compact and any(
            word in compact for word in ("关", "取消", "打开", "开", "勾", "不")
        ):
            off = any(word in compact for word in ("关", "取消", "去掉"))
            return UIAction(name="set_symmetry", value="关" if off else "开")
        if any(word in compact for word in ("恢复全部", "全部恢复", "把所有删掉的都恢复")):
            return UIAction(name="restore_all")
        wants_select = "选中" in compact or (
            "选择" in compact
            and not any(verb in compact for verb in self._PLACEMENT_VERBS)
        )
        if wants_select and any(
            word in compact for word in ("最外", "外圈", "壳壁", "隔板槽", "中心", "上方", "下方", "左侧", "右侧")
        ):
            region = "near_shell"
            for word, value in (
                ("隔板槽", "groove"), ("壳壁", "near_shell"), ("最外", "near_shell"),
                ("外圈", "near_shell"), ("中心", "center"), ("上方", "top"),
                ("下方", "bottom"), ("左侧", "left"), ("右侧", "right"),
            ):
                if word in compact:
                    region = value
                    break
            rows = 1
            match = re.search(r"([0-9]+|[一二两三四五六七八九十])\s*圈", compact)
            if match:
                token = match.group(1)
                rows = int(token) if token.isdigit() else self._CN_NUMBERS.get(token, 1)
            return UIAction(name="select_region", region=region, rows=max(1, rows))
        return None

    def _start_worker(self, fn, callback):
        self._worker_cancelled = False
        self._worker_callback = callback
        self.worker = TaskThread(fn, self)
        self.worker.result_ready.connect(self._worker_result)
        self.worker.failed.connect(self._worker_error)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _worker_result(self, result):
        if not self._worker_cancelled and self._worker_callback:
            self._worker_callback(result)

    def _worker_error(self, message):
        if self._worker_cancelled:
            return
        self.append_chat("assistant", f"这条要求没处理成功：{message}\n参数没有被修改，重新发送一次即可。")

    def _worker_finished(self):
        self.send_button.setEnabled(True)
        if self.worker is not None:
            self.worker.deleteLater()
        self.worker = None
        self._worker_callback = None

    # ------------------------------------------------------------------ 其他
    def open_settings(self):
        self.config = settings_dialog(self, self.config)
        self._refresh_model_label()
        self.append_chat("assistant", "AI 设置已更新。" if self.config.configured else "当前为离线模式。")

    def open_product_list(self):
        try:
            products = self.repository.list_products(80)
        except DatabaseUnavailable as exc:
            self.append_chat("assistant", f"读取产品列表失败：{exc}")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("选择产品（正式数据库）")
        dialog.resize(720, 480)
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        for product in products:
            listing.addItem(
                f"{product['产品ID']}  {product['产品型式']}  {product['产品类型']}"
            )
            listing.item(listing.count() - 1).setData(Qt.UserRole, product["产品ID"])
        layout.addWidget(listing)
        buttons = QHBoxLayout()
        buttons.addStretch()
        confirm = QPushButton("载入该产品")
        cancel = QPushButton("关闭")
        buttons.addWidget(confirm)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        if products:
            listing.setCurrentRow(0)

        def choose():
            item = listing.currentItem()
            if item is None:
                return
            dialog.accept()
            self._boot_session(item.data(Qt.UserRole))

        confirm.clicked.connect(choose)
        cancel.clicked.connect(dialog.reject)
        dialog.exec_()

    def clear_chat(self):
        if self.worker is not None and self.worker.isRunning():
            self.append_chat("assistant", "当前要求仍在处理中，完成后再新建对话。")
            return
        self._clear_preview()
        self._clear_inline_card()
        self.conversation.clear()
        self.chat_history = []
        self.placement_cards = []
        self.hole_cards = []
        for page in self.pages.values():
            page.setParent(None)
            page.deleteLater()
        self.pages.clear()
        self.preview_host.hide()
        self.session = None
        self._refresh_stage_buttons()
        self.append_chat("assistant", "对话已清空。点击左侧“开始管束设计”重新读取数据库。")

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self._worker_cancelled = True
            event.ignore()
            return
        super().closeEvent(event)
