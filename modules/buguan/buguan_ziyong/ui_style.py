"""布管界面弹窗/按钮样式总控（按钮与项目管理 guanli_new.ui 完全一致）。

用法::
    from modules.buguan.buguan_ziyong.ui_style import StyledMessageBox as QMessageBox
    from modules.buguan.buguan_ziyong.ui_style import StyledDialog as QDialog
"""

from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton


# 与 modules/chanpinguanli/guanli_new.ui / ui_style.CHANPINGUANLI_BUTTON_QSS 完全一致，勿擅自改大
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


# 弹窗内容略放大便于阅读；按钮仍复用上面的项目管理原尺寸样式
BUGUAN_DIALOG_QSS = """
QDialog, QMessageBox {
    background-color: #ffffff;
    color: #000000;
    font-size: 16px;
}

QMessageBox QLabel {
    background: transparent;
    color: #000000;
    font-size: 16px;
    min-width: 320px;
}

QDialog QLabel {
    background: transparent;
    color: #000000;
    font-size: 16px;
}

QDialog QComboBox {
    background-color: #ffffff;
    border: 1px solid #b8c8e0;
    border-radius: 0px;
    padding: 4px 8px;
    min-height: 28px;
    font-size: 16px;
}

QDialog QComboBox QAbstractItemView {
    font-size: 16px;
}

QDialog QLineEdit {
    background-color: #ffffff;
    border: 1px solid #b8c8e0;
    border-radius: 0px;
    padding: 4px 8px;
    min-height: 28px;
    font-size: 16px;
}
""" + BUGUAN_BUTTON_QSS


_BUTTON_CN_LABELS = {
    QMessageBox.Ok: "确认",
    QMessageBox.Yes: "是",
    QMessageBox.No: "否",
    QMessageBox.Cancel: "取消",
    QMessageBox.Abort: "中止",
    QMessageBox.Retry: "重试",
    QMessageBox.Ignore: "忽略",
    QMessageBox.Close: "关闭",
}


def apply_buguan_font(widget):
    """与项目管理一致：继承应用当前实际字体，不额外放大。"""
    widget.setFont(QApplication.font())
    return widget


def apply_buguan_button_style(button):
    """给单个按钮套用与产品管理保存按钮一致的样式。"""
    if button is None:
        return button
    button.setStyleSheet(BUGUAN_BUTTON_QSS)
    return button


def apply_buguan_dialog_style(dialog):
    """为 QMessageBox / QDialog 等弹窗应用布管统一视觉样式。"""
    apply_buguan_font(dialog)
    dialog.setStyleSheet(BUGUAN_DIALOG_QSS)
    return dialog


def localize_messagebox_buttons(msg_box):
    """将标准按钮文案改为中文（若该标准按钮存在）。"""
    for std, label in _BUTTON_CN_LABELS.items():
        btn = msg_box.button(std)
        if btn is not None:
            btn.setText(label)
    return msg_box


class StyledDialog(QDialog):
    """布管参数/提示类弹窗总控。直接 `as QDialog` 替换即可。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_buguan_dialog_style(self)

    def exec_(self):
        apply_buguan_dialog_style(self)
        return super().exec_()


class StyledMessageBox(QMessageBox):
    """
    布管消息框总控。

    兼容 QMessageBox.warning / information / critical / question，
    以及 `QMessageBox()` 直接构造；返回值与原生一致。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_buguan_dialog_style(self)

    @staticmethod
    def _exec_standard(parent, icon, title, text, buttons, defaultButton):
        box = StyledMessageBox(parent)
        box.setIcon(icon)
        box.setWindowTitle("" if title is None else str(title))
        box.setText("" if text is None else str(text))
        box.setStandardButtons(buttons)
        if defaultButton != QMessageBox.NoButton:
            box.setDefaultButton(defaultButton)
        localize_messagebox_buttons(box)
        apply_buguan_dialog_style(box)
        return box.exec_()

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
        apply_buguan_dialog_style(self)
        return super().exec_()
