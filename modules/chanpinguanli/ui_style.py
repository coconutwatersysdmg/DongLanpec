"""项目管理及其关联页面共用的按钮、弹窗样式。"""

from PyQt5.QtWidgets import QApplication, QMessageBox, QPushButton


# 与 guanli_new.ui 中的 QPushButton 样式保持一致。
CHANPINGUANLI_BUTTON_QSS = """
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


CHANPINGUANLI_DIALOG_QSS = """
QDialog, QMessageBox {
    background-color: #ffffff;
    color: #000000;
    font-size: 14px;
}

QMessageBox QLabel {
    background: transparent;
    color: #000000;
    font-size: 14px;
    min-width: 280px;
}
""" + CHANPINGUANLI_BUTTON_QSS


def apply_chanpinguanli_font(widget):
    """与项目管理 main2.py 一致，继承应用当前实际字体。"""
    widget.setFont(QApplication.font())
    return widget


def apply_chanpinguanli_dialog_style(dialog):
    """为 QMessageBox、QDialog 等弹窗应用项目管理视觉样式。"""
    apply_chanpinguanli_font(dialog)
    dialog.setStyleSheet(CHANPINGUANLI_DIALOG_QSS)
    return dialog


def show_chanpinguanli_message(parent, icon, title, text, button_text="确认"):
    """显示项目管理风格的单按钮消息框。"""
    msg_box = QMessageBox(parent)
    msg_box.setWindowTitle(title)
    msg_box.setText(str(text))
    msg_box.setIcon(icon)

    confirm_button = QPushButton(button_text)
    msg_box.addButton(confirm_button, QMessageBox.AcceptRole)
    apply_chanpinguanli_dialog_style(msg_box)
    msg_box.exec_()
