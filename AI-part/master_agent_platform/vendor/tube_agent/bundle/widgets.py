"""布管页复用的小部件：带示意图的分程形式下拉框、元件参数确认弹窗。

两件东西都对标正式程序：
- `TubePassFormComboBox` 对应 My_Piping.TubePassFormComboBox：闭合态直接把
  `static/TubePattern/<标识>.png` 按单元格大小等比缩放绘制，不再显示 "2.1"
  这样的数字；展开后下拉项同样是示意图（比正式程序放得更大，便于辨认）。
- `ComponentParamDialog` 对应正式程序各元件的“××参数设置”弹窗：左侧参数表里
  隐藏的元件参数（滑道/防冲板/中间挡板/吊环螺钉/旁路挡板/拉杆…）在布置元件时
  由弹窗让用户确认，确认后才写回参数表并落图。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPalette,
    QPixmap,
)
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyleOptionComboBox,
    QVBoxLayout,
    QWidget,
)


class TubePassFormComboBox(QComboBox):
    """管程分程形式：闭合态自绘示意图，下拉列表按大图显示。"""

    PIXMAP_ROLE = Qt.UserRole + 200
    POPUP_WIDTH = 460

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(False)
        self.setMinimumHeight(22)
        view = QListView()
        view.setSpacing(2)
        view.setStyleSheet("QListView::item{padding:2px 4px;}")
        self.setView(view)
        # 与参数表其它下拉框同款：白底、1px #CCCCCC、右侧灰色三角
        self.setStyleSheet(
            "QComboBox{border:1px solid #CCCCCC;background:#ffffff;"
            "padding:0px;padding-right:18px;}"
            "QComboBox::drop-down{subcontrol-origin:padding;"
            "subcontrol-position:top right;width:14px;border:none;background:transparent;}"
            f"QComboBox::down-arrow{{image:url({combo_arrow_url()});"
            "width:10px;height:6px;}"
        )

    # ---- 绘制 ----
    def _preview_rect(self):
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        field_rect = self.style().subControlRect(
            QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxEditField, self
        )
        return field_rect.adjusted(2, 2, -2, -2)

    def _current_pixmap(self) -> QPixmap | None:
        index = self.currentIndex()
        if index < 0:
            return None
        pixmap = self.itemData(index, self.PIXMAP_ROLE)
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            return pixmap
        icon = self.itemIcon(index)
        if icon.isNull():
            return None
        sizes = icon.availableSizes()
        return icon.pixmap(sizes[0]) if sizes else icon.pixmap(QSize(460, 104))

    def paintEvent(self, event):  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.currentText = ""
        option.currentIcon = QIcon()
        self.style().drawComplexControl(QStyle.CC_ComboBox, option, painter, self)
        pixmap = self._current_pixmap()
        if pixmap is None:
            return
        target = self._preview_rect()
        if target.width() <= 0 or target.height() <= 0:
            return
        scaled = pixmap.scaled(target.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter.drawPixmap(
            target.x(), target.y() + (target.height() - scaled.height()) // 2, scaled
        )

    # ---- 弹窗大图 ----
    def _refresh_popup_icons(self) -> None:
        icon_size = QSize(self.POPUP_WIDTH, 60)
        for index in range(self.count()):
            pixmap = self.itemData(index, self.PIXMAP_ROLE)
            if not isinstance(pixmap, QPixmap) or pixmap.isNull():
                continue
            height = max(int(self.POPUP_WIDTH * pixmap.height() / max(pixmap.width(), 1)), 20)
            scaled = pixmap.scaled(
                QSize(self.POPUP_WIDTH, height), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.setItemIcon(index, QIcon(scaled))
            icon_size = scaled.size()
        view = self.view()
        if view is not None:
            view.setIconSize(icon_size)
            view.setMinimumWidth(icon_size.width() + 16)
            view.setGridSize(QSize(icon_size.width() + 10, icon_size.height() + 8))

    def showPopup(self):  # noqa: N802 - Qt API
        self._refresh_popup_icons()
        super().showPopup()


class RightAlignedComboBox(QComboBox):
    """参数值右对齐的下拉框（正式程序参数表里“参数值”整列都是右对齐）。

    QComboBox 非可编辑时由样式绘制文字，Qt 没有给“闭合态文字对齐”的接口，
    所以这里改成“只读 lineEdit + 右对齐”，下拉箭头、弹窗行为保持不变。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        line = self.lineEdit()
        if line is not None:
            line.setReadOnly(True)
            line.setFrame(False)
            line.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            line.setStyleSheet(
                "QLineEdit{background:transparent;border:none;color:#1f2329;"
                "padding:0 16px 0 0;}"
            )

    def mousePressEvent(self, event):  # noqa: N802 - Qt API
        # 只读 lineEdit 不会自己弹下拉，这里补上，点整块区域都能选；
        # 可编辑下拉保持原生行为，否则点一下就没法手工输入了。
        line = self.lineEdit()
        if event.button() == Qt.LeftButton and line is not None and line.isReadOnly():
            self.showPopup()
            event.accept()
            return
        super().mousePressEvent(event)


# ---------------------------------------------------------------- 参数表下拉框
# 照搬正式程序 modules/buguan/buguan_ziyong/buguan_param_table_style.py：
# 白底、1px #CCCCCC 直角边框、10pt、右侧 14px 透明箭头区 + 灰色 SVG 三角，
# 弹窗白底 #CCCCCC 边框、选中行 #d9e6f7；禁用时 #f5f7fa 底 + #969696 字。
PARAM_COMBO_BORDER = "#CCCCCC"
PARAM_COMBO_TEXT = "#1f1f1f"
PARAM_COMBO_SELECTION = "#d9e6f7"
PARAM_COMBO_DISABLED_BG = "#f5f7fa"
PARAM_COMBO_DISABLED_TEXT = "#969696"
_COMBO_ARROW_SVG = (Path(__file__).resolve().parents[1] / "assets" / "combo_arrow_gray.svg")
_ARROW_URL_CACHE: str | None = None


def combo_arrow_url() -> str:
    """QSS url() 用的箭头路径。

    QSS 的 url() 不认非 ASCII 路径，而这个 Demo 可能被放在“管束AI方案”这种
    中文目录下，直接写 assets 路径箭头会消失。所以复制一份到临时目录（纯 ASCII）
    再用；复制失败就退回原路径。
    """
    global _ARROW_URL_CACHE
    if _ARROW_URL_CACHE:
        return _ARROW_URL_CACHE
    path = _COMBO_ARROW_SVG.as_posix()
    try:
        if not _COMBO_ARROW_SVG.exists():
            _ARROW_URL_CACHE = path
            return path
        if path.isascii():
            _ARROW_URL_CACHE = path
            return path
        import shutil
        import tempfile

        cached = Path(tempfile.gettempdir()) / "donglanpec_combo_arrow_gray.svg"
        if (
            not cached.exists()
            or cached.stat().st_mtime < _COMBO_ARROW_SVG.stat().st_mtime
        ):
            shutil.copyfile(_COMBO_ARROW_SVG, cached)
        _ARROW_URL_CACHE = cached.as_posix()
    except Exception:
        _ARROW_URL_CACHE = path
    return _ARROW_URL_CACHE


def param_combo_stylesheet(disabled: bool = False, border: str | None = None) -> str:
    """正式程序 get_param_combo_stylesheet() 的同款实现（border 可给校验红框）。"""
    arrow = combo_arrow_url()
    line_color = border or PARAM_COMBO_BORDER
    base = (
        f"background-color: #ffffff;border: 1px solid {line_color};"
        f"color: {PARAM_COMBO_TEXT};font-size: 10pt;min-height: 22px;"
        "padding: 1px 16px 1px 4px;"
    )
    popup = (
        "QComboBox::drop-down{subcontrol-origin:padding;subcontrol-position:top right;"
        "width:14px;border:none;background:transparent;}"
        f"QComboBox::down-arrow{{image:url({arrow});width:10px;height:6px;}}"
        "QComboBox QAbstractItemView{background-color:#ffffff;"
        f"border:1px solid {PARAM_COMBO_BORDER};color:{PARAM_COMBO_TEXT};"
        f"selection-background-color:{PARAM_COMBO_SELECTION};"
        f"selection-color:{PARAM_COMBO_TEXT};outline:0;}}"
        "QComboBox QLineEdit{border:none;background:transparent;padding:0;margin:0;"
        f"color:{PARAM_COMBO_TEXT};selection-background-color:{PARAM_COMBO_SELECTION};"
        f"selection-color:{PARAM_COMBO_TEXT};}}"
    )
    if disabled:
        return (
            f"QComboBox{{{base}background-color:{PARAM_COMBO_DISABLED_BG};"
            f"color:{PARAM_COMBO_TEXT if border else PARAM_COMBO_DISABLED_TEXT};}}"
            f"{popup}"
        )
    return f"QComboBox{{{base}}}{popup}"


def apply_param_combo_style(
    combo: QComboBox, disabled: bool = False, border: str | None = None
) -> None:
    """套样式 + 修调色板（正式程序同名函数），避免选中整行时文字变白。"""
    if not isinstance(combo, QComboBox):
        return
    combo.setStyleSheet(param_combo_stylesheet(disabled=disabled, border=border))
    text_color = QColor(
        PARAM_COMBO_TEXT if (border or not disabled) else PARAM_COMBO_DISABLED_TEXT
    )
    palette = combo.palette()
    for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        palette.setColor(group, QPalette.Text, text_color)
        palette.setColor(group, QPalette.ButtonText, text_color)
        palette.setColor(group, QPalette.WindowText, text_color)
        if group != QPalette.Disabled:
            palette.setColor(group, QPalette.Highlight, QColor(PARAM_COMBO_SELECTION))
            palette.setColor(group, QPalette.HighlightedText, QColor(PARAM_COMBO_TEXT))
    combo.setPalette(palette)
    line = combo.lineEdit()
    if line is not None:
        line.setStyleSheet(
            "border:none;background:transparent;padding:0;margin:0;"
            f"color:{PARAM_COMBO_TEXT};"
            f"selection-background-color:{PARAM_COMBO_SELECTION};"
            f"selection-color:{PARAM_COMBO_TEXT};"
        )


class ParamComboBox(QComboBox):
    """参数表里的下拉框：禁用滚轮（正式程序 NoWheelComboBox），样式照搬参数表。

    editable=True 时就是“下拉列表 + 手工输入”两用（换热管外径 do、公称长度 LN
    在正式程序里就是这么做的）。文字默认右对齐——参数值列整列右对齐。
    """

    def __init__(self, parent=None, editable: bool = False):
        super().__init__(parent)
        self.setEditable(True)               # 用只读 lineEdit 实现右对齐
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setFocusPolicy(Qt.StrongFocus)
        line = self.lineEdit()
        if line is not None:
            line.setReadOnly(not editable)
            line.setFrame(False)
            line.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        apply_param_combo_style(self, disabled=False)

    def wheelEvent(self, event):  # noqa: N802 - Qt API
        event.ignore()                        # 正式程序：滚轮不切选项

    def mousePressEvent(self, event):  # noqa: N802 - Qt API
        line = self.lineEdit()
        if event.button() == Qt.LeftButton and line is not None and line.isReadOnly():
            self.showPopup()
            event.accept()
            return
        super().mousePressEvent(event)


@dataclass
class ParamField:
    """弹窗中的一个参数行。"""

    name: str
    kind: str = "number"                 # number / combo / readonly
    options: tuple[str, ...] = ()
    unit: str = ""
    minimum: float | None = None
    maximum: float | None = None
    visible: Callable[[dict], bool] | None = None
    tip: str = ""


class ConfirmDialog(QDialog):
    """是 / 否 二选一确认框（保留确认等弹窗用，按钮就是中文“是”“否”）。

    不用 QMessageBox：一是原生按钮文案在不同系统上会退回 Yes/No，
    二是它的版式和程序里别的弹窗不统一。
    """

    def __init__(self, title: str, text: str, detail: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(360)
        self.setStyleSheet("QDialog{background:#ffffff;}")

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(10)
        icon = QLabel("?")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(26, 26)
        icon.setStyleSheet(
            "QLabel{background:#2f6fe4;color:#ffffff;border-radius:13px;"
            "font-size:13pt;font-weight:600;}"
        )
        head.addWidget(icon, 0, Qt.AlignTop)
        message = QLabel(text)
        message.setWordWrap(True)
        message.setStyleSheet("QLabel{color:#1f2329;font-size:10.5pt;}")
        head.addWidget(message, 1)
        root.addLayout(head)

        if detail:
            hint = QLabel(detail)
            hint.setWordWrap(True)
            hint.setContentsMargins(36, 0, 0, 0)
            hint.setStyleSheet("QLabel{color:#8a9099;font-size:9.5pt;}")
            root.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch()
        self.no_button = QPushButton("否")
        self.yes_button = QPushButton("是")
        for button in (self.no_button, self.yes_button):
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumWidth(78)
            button.setStyleSheet(
                "QPushButton{background:#fff;border:1px solid #dcdde0;border-radius:7px;"
                "padding:6px 18px;color:#1f2329;}"
                "QPushButton:hover{background:#f5f7fa;}"
            )
        self.yes_button.setDefault(True)
        self.yes_button.setStyleSheet(
            "QPushButton{background:#2f6fe4;color:#fff;border:none;border-radius:7px;"
            "padding:6px 20px;font-weight:600;}"
            "QPushButton:hover{background:#2a63cc;}"
        )
        self.no_button.clicked.connect(self.reject)
        self.yes_button.clicked.connect(self.accept)
        buttons.addWidget(self.no_button)
        buttons.addWidget(self.yes_button)
        root.addLayout(buttons)


class ComponentParamDialog(QDialog):
    """布置元件前的参数确认弹窗（正式程序同名弹窗的等价实现）。

    版式按 Demo 的整体风格重做：白底、细边框输入框、右对齐数值、主按钮蓝色，
    不再用 QFormLayout 默认那套“灰标签 + 高高低低的控件”的旧面孔。
    """

    LABEL_WIDTH = 112          # 最小标签列宽；实际按最长参数名撑开，绝不截断
    LABEL_MAX_WIDTH = 260

    def __init__(self, title: str, fields: list[ParamField], values: dict,
                 hint: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        # 去掉标题栏那个没用的“?”帮助按钮
        self.setWindowFlags(
            (self.windowFlags() | Qt.WindowCloseButtonHint)
            & ~Qt.WindowContextHelpButtonHint
        )
        self.setMinimumWidth(430)
        self.setStyleSheet(
            "QDialog{background:#ffffff;}"
            "QLabel{background:transparent;}"
        )
        self._fields = fields
        self._editors: dict[str, QWidget] = {}
        self._rows: dict[str, QWidget] = {}
        self._labels: dict[str, QWidget] = {}

        # 标签列宽按最长参数名算：固定 112 会把“折流板切口方向”这类长名字截掉
        label_font = QFont(self.font())
        label_font.setPointSize(10)
        metrics = QFontMetrics(label_font)
        widest = max(
            (metrics.horizontalAdvance(str(spec.name)) for spec in fields),
            default=self.LABEL_WIDTH,
        )
        self.label_width = max(
            self.LABEL_WIDTH, min(int(widest) + 10, self.LABEL_MAX_WIDTH)
        )
        # 弹窗整体宽度也要跟着放，否则标签放不下又会把输入框挤扁
        self.setMinimumWidth(max(430, self.label_width + 300))

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(12 if hint else 14)

        if hint:
            hint_label = QLabel(hint)
            hint_label.setWordWrap(True)
            hint_label.setStyleSheet(
                "QLabel{background:#f6f8fb;border:1px solid #eef1f6;border-radius:8px;"
                "color:#5b6472;font-size:9pt;padding:9px 11px;}"
            )
            root.addWidget(hint_label)

        form_host = QWidget()
        grid = QGridLayout(form_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(11)
        grid.setColumnMinimumWidth(0, self.label_width)
        grid.setColumnStretch(1, 1)
        for row_index, spec in enumerate(fields):
            label = QLabel(f"{spec.name}")
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            label.setFont(label_font)
            label.setMinimumWidth(self.label_width)
            label.setStyleSheet("QLabel{color:#3d4653;font-size:10pt;}")
            self._labels[spec.name] = label

            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(7)
            value = "" if values.get(spec.name) is None else str(values.get(spec.name))
            editor = self._make_editor(spec, value)
            row.addWidget(editor, 1)
            if spec.unit:
                unit = QLabel(spec.unit)
                unit.setMinimumWidth(18)
                unit.setStyleSheet("QLabel{color:#9aa1ab;font-size:9.5pt;}")
                row.addWidget(unit, 0, Qt.AlignVCenter)
            if spec.tip:
                container.setToolTip(spec.tip)
            self._editors[spec.name] = editor
            self._rows[spec.name] = container
            grid.addWidget(label, row_index, 0)
            grid.addWidget(container, row_index, 1)
        # 多出来的高度留给最后一行空白行，别把最后一行控件拉高（单位会往下跑）
        grid.setRowStretch(len(fields), 1)
        root.addWidget(form_host)

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("QFrame{background:#f0f1f3;border:none;}")
        root.addWidget(line)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch()
        cancel = QPushButton("取消")
        confirm = QPushButton("确定")
        confirm.setDefault(True)
        for button in (cancel, confirm):
            button.setCursor(Qt.PointingHandCursor)
            button.setMinimumSize(84, 34)
        cancel.setStyleSheet(
            "QPushButton{background:#ffffff;border:1px solid #dfe2e7;border-radius:8px;"
            "color:#4b5563;font-size:10pt;}"
            "QPushButton:hover{background:#f5f7fa;border-color:#cfd6e2;}"
        )
        confirm.setStyleSheet(
            "QPushButton{background:#2f6fe4;color:#ffffff;border:none;border-radius:8px;"
            "padding:7px 22px;font-size:10pt;font-weight:600;}"
            "QPushButton:hover{background:#2a63cc;}"
        )
        cancel.clicked.connect(self.reject)
        confirm.clicked.connect(self._on_confirm)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        root.addLayout(buttons)

        for spec in fields:
            editor = self._editors[spec.name]
            if isinstance(editor, QComboBox):
                editor.currentIndexChanged.connect(self._apply_visibility)
        self._apply_visibility()

    @staticmethod
    def _make_editor(spec: ParamField, value: str) -> QWidget:
        """输入控件：样式照搬正式程序弹窗（ui_style.py 的 QDialog QLineEdit/QComboBox）。"""
        base = (
            "QLineEdit{background:#ffffff;border:1px solid #CCCCCC;border-radius:0px;"
            "color:#1f1f1f;font-size:10pt;min-height:22px;padding:0px 4px;}"
            # 与同排输入框等高（min-height 20 + 上下边框 = 24），源程序是 22/22 略高 2px
            "QComboBox{background:#ffffff;border:1px solid #CCCCCC;border-radius:0px;"
            "color:#1f1f1f;font-size:10pt;min-height:22px;padding:0px 16px 0px 4px;}"
            "QComboBox::drop-down{subcontrol-origin:padding;subcontrol-position:top right;"
            "width:14px;border:none;background:transparent;}"
            f"QComboBox::down-arrow{{image:url({combo_arrow_url()});width:10px;height:6px;}}"
            "QComboBox QAbstractItemView{background:#ffffff;border:1px solid #CCCCCC;"
            "selection-background-color:#d9e6f7;selection-color:#1f1f1f;outline:0;}"
            "QComboBox QLineEdit{border:none;background:transparent;}"
        )
        if spec.kind == "combo":
            editor = RightAlignedComboBox()
            editor.addItems(list(spec.options))
            index = editor.findText(value)
            editor.setCurrentIndex(index if index >= 0 else 0)
            editor.setMinimumWidth(190)
            editor.setStyleSheet(base)
            return editor
        editor = QLineEdit(value)
        editor.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if spec.kind == "readonly":
            editor.setReadOnly(True)
            editor.setStyleSheet(
                "QLineEdit{background:#f5f7fa;border:1px solid #CCCCCC;border-radius:0px;"
                "padding:0px 4px;color:#969696;font-size:10pt;min-height:22px;}"
            )
            return editor
        editor.setStyleSheet(base)
        return editor

    # ---- 显隐 / 校验 ----
    def _values_now(self) -> dict:
        result = {}
        for name, editor in self._editors.items():
            if isinstance(editor, QComboBox):
                result[name] = editor.currentText().strip()
            elif isinstance(editor, QLineEdit):
                result[name] = editor.text().strip()
        return result

    def _apply_visibility(self) -> None:
        current = self._values_now()
        for spec in self._fields:
            container = self._rows.get(spec.name)
            if container is None or spec.visible is None:
                continue
            visible = bool(spec.visible(current))
            container.setVisible(visible)
            label = self._labels.get(spec.name)
            if label is not None:
                label.setVisible(visible)
        self.adjustSize()

    def values(self) -> dict:
        return self._values_now()

    def _on_confirm(self) -> None:
        values = self._values_now()
        for spec in self._fields:
            if spec.kind != "number":
                continue
            if not self._rows[spec.name].isVisible():
                continue
            text = values.get(spec.name, "")
            if text == "":
                QMessageBox.warning(self, "输入错误", f"“{spec.name}”不能为空。")
                return
            try:
                number = float(text)
            except ValueError:
                QMessageBox.warning(self, "输入错误", f"“{spec.name}”必须填写数字。")
                return
            if spec.minimum is not None and number < spec.minimum:
                QMessageBox.warning(
                    self, "输入错误", f"“{spec.name}”不能小于 {spec.minimum:g}。"
                )
                return
            if spec.maximum is not None and number > spec.maximum:
                QMessageBox.warning(
                    self, "输入错误", f"“{spec.name}”不能大于 {spec.maximum:g}。"
                )
                return
        self.accept()


def ask_component_params(title: str, fields: list[ParamField], values: dict,
                         hint: str = "", parent=None) -> dict | None:
    """弹窗取参数；用户取消返回 None。"""
    dialog = ComponentParamDialog(title, fields, values, hint=hint, parent=parent)
    if dialog.exec_() != QDialog.Accepted:
        return None
    return dialog.values()
