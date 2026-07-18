"""布管界面弹窗/按钮样式总控。

弹窗外观对齐材料定义「批量替换（材料约束）」：
白底、系统字号、#CCCCCC 边框、右下角紧凑确定/取消按钮。

页面级按钮（保存等）仍用项目管理 guanli 样式，见 BUGUAN_BUTTON_QSS。

用法::
    from modules.buguan.buguan_ziyong.ui_style import StyledMessageBox as QMessageBox
    from modules.buguan.buguan_ziyong.ui_style import StyledDialog as QDialog
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


# ---------- 页面级按钮：与项目管理 guanli_new.ui 一致 ----------
BUGUAN_BUTTON_QSS = """
QPushButton {
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                stop: 0 #ffffff, stop: 1 #e8edf5);
    border: 1px solid #b8c8e0;
    border-radius: 0px;
    color: #000000;
    font-size: 17px;
    padding: 8px 20px;
    text-align: center;
    min-width: 65px;
}

QPushButton:hover {
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                stop: 0 #f0f4fa, stop: 1 #d8e0ed);
    border-color: #9ab0d0;
}

QPushButton:pressed {
    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                stop: 0 #e0e6f0, stop: 1 #c8d2e0);
    border-color: #7a90b0;
}

QPushButton:disabled {
    background: #f5f7fa;
    color: #888888;
    border-color: #d0d8e5;
}
"""


# ---------- 弹窗内控件：对齐 paradefine / 批量替换 ----------
BUGUAN_DIALOG_BUTTON_QSS = """
QPushButton {
    background-color: #f8fafc;
    color: #1f1f1f;
    border: 1px solid #CCCCCC;
    border-radius: 0px;
    padding: 3px 12px;
    min-width: 75px;
    min-height: 24px;
}

QPushButton:hover {
    background-color: #edf2f8;
}

QPushButton:pressed {
    background-color: #e2e8f0;
}

QPushButton:disabled {
    background-color: #f5f5f5;
    color: #888888;
    border-color: #DDDDDD;
}

QPushButton:default {
    border: 1px solid #A0A0A0;
}
"""


BUGUAN_DIALOG_QSS = """
QDialog {
    background-color: #ffffff;
    color: #1f1f1f;
}

QDialog QLabel {
    background: transparent;
    color: #1f1f1f;
    border: none;
}

QDialog QComboBox {
    background-color: #ffffff;
    border: 1px solid #CCCCCC;
    border-radius: 0px;
    color: #1f1f1f;
    min-height: 22px;
    padding: 1px 16px 1px 4px;
}

QDialog QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 14px;
    border: none;
    background: transparent;
}

QDialog QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #CCCCCC;
    selection-background-color: #d9e6f7;
    selection-color: #1f1f1f;
}

QDialog QLineEdit {
    background-color: #ffffff;
    border: 1px solid #CCCCCC;
    border-radius: 0px;
    color: #1f1f1f;
    min-height: 22px;
    padding: 0px 4px;
}
""" + BUGUAN_DIALOG_BUTTON_QSS


_BUTTON_CN_LABELS = {
    QMessageBox.Ok: "确定",
    QMessageBox.Yes: "是",
    QMessageBox.No: "否",
    QMessageBox.Cancel: "取消",
    QMessageBox.Abort: "中止",
    QMessageBox.Retry: "重试",
    QMessageBox.Ignore: "忽略",
    QMessageBox.Close: "关闭",
}

_BUTTON_ORDER = (
    QMessageBox.Yes,
    QMessageBox.Ok,
    QMessageBox.Retry,
    QMessageBox.Ignore,
    QMessageBox.No,
    QMessageBox.Abort,
    QMessageBox.Cancel,
    QMessageBox.Close,
)


def apply_buguan_font(widget):
    """继承应用当前实际字体（与批量替换弹窗一致，不强制放大）。"""
    widget.setFont(QApplication.font())
    return widget


def apply_buguan_button_style(button):
    """页面级按钮：项目管理保存按钮样式。"""
    if button is None:
        return button
    button.setStyleSheet(BUGUAN_BUTTON_QSS)
    return button


def apply_buguan_dialog_button_style(button):
    """弹窗内按钮：批量替换同款。"""
    if button is None:
        return button
    button.setStyleSheet(BUGUAN_DIALOG_BUTTON_QSS)
    return button


def apply_buguan_dialog_style(dialog):
    """为自定义 QDialog 应用「批量替换」同款视觉。"""
    apply_buguan_font(dialog)
    dialog.setStyleSheet(BUGUAN_DIALOG_QSS)
    try:
        dialog.setWindowFlags(
            dialog.windowFlags() & ~Qt.WindowContextHelpButtonHint
        )
    except Exception:
        pass
    return dialog


def localize_messagebox_buttons(msg_box):
    for std, label in _BUTTON_CN_LABELS.items():
        btn = msg_box.button(std)
        if btn is not None:
            btn.setText(label)
            apply_buguan_dialog_button_style(btn)
    return msg_box


class StyledDialog(QDialog):
    """布管参数类弹窗总控（外观对齐批量替换）。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_buguan_dialog_style(self)

    def exec_(self):
        apply_buguan_dialog_style(self)
        return super().exec_()


class _BuguanPromptDialog(QDialog):
    """
    提示/警告/询问弹窗。
    布局对齐批量替换：白底、默认边距、正文、右下角按钮。
    """

    def __init__(self, parent, title, text, buttons, defaultButton):
        super().__init__(parent)
        self._result = QMessageBox.Cancel
        self.setModal(True)
        self.setWindowTitle("" if title is None else str(title))
        apply_buguan_dialog_style(self)

        root = QVBoxLayout(self)
        # 接近 Qt 默认 / 批量替换的边距体感
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        msg = QLabel("" if text is None else str(text))
        msg.setWordWrap(True)
        msg.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        msg.setMinimumWidth(280)
        msg.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(msg)

        root.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)

        try:
            flags = int(buttons)
        except Exception:
            flags = int(QMessageBox.Ok)

        created = []
        for std in _BUTTON_ORDER:
            if flags & int(std):
                label = _BUTTON_CN_LABELS.get(std, "确定")
                btn = QPushButton(label)
                apply_buguan_dialog_button_style(btn)
                btn.clicked.connect(lambda _=False, s=std: self._on_click(s))
                btn_row.addWidget(btn)
                created.append((std, btn))

        if not created:
            btn = QPushButton("确定")
            apply_buguan_dialog_button_style(btn)
            btn.clicked.connect(lambda: self._on_click(QMessageBox.Ok))
            btn_row.addWidget(btn)
            created.append((QMessageBox.Ok, btn))

        root.addLayout(btn_row)

        default = defaultButton
        if default == QMessageBox.NoButton and created:
            # 单按钮默认第一个；多按钮时优先确定/是
            default = created[0][0]
            for std, _btn in created:
                if std in (QMessageBox.Ok, QMessageBox.Yes):
                    default = std
                    break
        for std, btn in created:
            if std == default:
                btn.setDefault(True)
                btn.setFocus()
                break

        self.adjustSize()
        self.resize(max(self.width(), 360), max(self.height(), 120))

    def _on_click(self, std_btn):
        self._result = std_btn
        if std_btn in (
            QMessageBox.Yes,
            QMessageBox.Ok,
            QMessageBox.Retry,
            QMessageBox.Ignore,
        ):
            self.accept()
        else:
            self.reject()

    def exec_result(self):
        self.exec_()
        return self._result


class StyledMessageBox(QMessageBox):
    """
    布管消息框总控。
    warning / information / critical / question → 批量替换同款自定义弹窗。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self.setStyleSheet(BUGUAN_DIALOG_QSS)
        except Exception:
            pass

    @staticmethod
    def _exec_standard(parent, icon, title, text, buttons, defaultButton):
        _ = icon
        dlg = _BuguanPromptDialog(parent, title, text, buttons, defaultButton)
        return dlg.exec_result()

    @staticmethod
    def information(
        parent,
        title,
        text,
        buttons=QMessageBox.Ok,
        defaultButton=QMessageBox.NoButton,
    ):
        return StyledMessageBox._exec_standard(
            parent, QMessageBox.Information, title, text, buttons, defaultButton
        )

    @staticmethod
    def warning(
        parent,
        title,
        text,
        buttons=QMessageBox.Ok,
        defaultButton=QMessageBox.NoButton,
    ):
        return StyledMessageBox._exec_standard(
            parent, QMessageBox.Warning, title, text, buttons, defaultButton
        )

    @staticmethod
    def critical(
        parent,
        title,
        text,
        buttons=QMessageBox.Ok,
        defaultButton=QMessageBox.NoButton,
    ):
        return StyledMessageBox._exec_standard(
            parent, QMessageBox.Critical, title, text, buttons, defaultButton
        )

    @staticmethod
    def question(
        parent,
        title,
        text,
        buttons=QMessageBox.Yes | QMessageBox.No,
        defaultButton=QMessageBox.NoButton,
    ):
        return StyledMessageBox._exec_standard(
            parent, QMessageBox.Question, title, text, buttons, defaultButton
        )

    def exec_(self):
        localize_messagebox_buttons(self)
        try:
            self.setStyleSheet(BUGUAN_DIALOG_QSS)
        except Exception:
            pass
        return super().exec_()
