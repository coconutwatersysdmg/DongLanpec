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


class StyledMessageBox(QMessageBox):
    """
    布管提示/警告总控。

    原生 QMessageBox + 蓝色问号图标；
    按钮文案中文「确认/取消」，外观用 BUGUAN_DIALOG_BUTTON_QSS（与参数弹窗一致）。
    返回值与原生标准按钮一致，便于现有 `== QMessageBox.Yes` 判断。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @staticmethod
    def _exec_standard(parent, icon, title, text, buttons, defaultButton):
        """
        用原生 QMessageBox 弹出，保留系统蓝色问号图标。
        对齐 modules.chanpinguanli.project_confirm_btn.show_confirm_dialog。
        """
        # 警告/提示/询问统一用 Question（蓝底白问号）
        if icon in (QMessageBox.Warning, QMessageBox.Question, QMessageBox.Information):
            use_icon = QMessageBox.Question
        else:
            use_icon = icon

        box = QMessageBox(parent)
        box.setIcon(use_icon)
        box.setWindowTitle("" if title is None else str(title))
        box.setText("" if text is None else str(text))

        try:
            flags = int(buttons)
        except Exception:
            flags = int(QMessageBox.Ok)

        has_yes = bool(flags & int(QMessageBox.Yes))
        has_no = bool(flags & int(QMessageBox.No))
        has_ok = bool(flags & int(QMessageBox.Ok))
        has_cancel = bool(flags & int(QMessageBox.Cancel))

        created = []  # (return_std, button)

        # 确认类：Yes 或 仅 Ok
        if has_yes or has_ok:
            btn_yes = QPushButton("确认")
            box.addButton(btn_yes, QMessageBox.YesRole)
            # 有 Yes 时返回 Yes（兼容 reply == QMessageBox.Yes）；仅 Ok 时返回 Ok
            created.append((QMessageBox.Yes if has_yes else QMessageBox.Ok, btn_yes))

        # 取消类：No 或 Cancel
        if has_no or has_cancel:
            btn_no = QPushButton("取消")
            box.addButton(btn_no, QMessageBox.NoRole)
            created.append((QMessageBox.No if has_no else QMessageBox.Cancel, btn_no))

        # 其它标准按钮
        extra = (
            (QMessageBox.Retry, "重试", QMessageBox.AcceptRole),
            (QMessageBox.Ignore, "忽略", QMessageBox.AcceptRole),
            (QMessageBox.Abort, "中止", QMessageBox.RejectRole),
            (QMessageBox.Close, "关闭", QMessageBox.RejectRole),
        )
        for std, label, role in extra:
            if flags & int(std):
                btn = QPushButton(label)
                box.addButton(btn, role)
                created.append((std, btn))

        if not created:
            btn_yes = QPushButton("确认")
            box.addButton(btn_yes, QMessageBox.YesRole)
            created.append((QMessageBox.Ok, btn_yes))

        # 按钮外观与参数弹窗确定/取消一致（不要用系统纯文字分隔按钮）
        for _, btn in created:
            apply_buguan_dialog_button_style(btn)

        # 默认按钮
        default = defaultButton
        if default == QMessageBox.NoButton:
            default = created[0][0]
        for ret, btn in created:
            if ret == default or (
                default in (QMessageBox.Ok, QMessageBox.Yes)
                and ret in (QMessageBox.Ok, QMessageBox.Yes)
            ):
                box.setDefaultButton(btn)
                break

        box.exec_()
        clicked = box.clickedButton()
        for ret, btn in created:
            if clicked is btn:
                return ret
        return QMessageBox.Cancel

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
        # 直接构造的场景：补蓝色问号 + 中文按钮，不套自定义灰白 QSS（以免盖掉系统图标）
        try:
            if self.icon() in (
                QMessageBox.NoIcon,
                QMessageBox.Warning,
                QMessageBox.Information,
            ):
                self.setIcon(QMessageBox.Question)
        except Exception:
            pass
        localize_messagebox_buttons(self)
        # 手动 addButton 的自定义按钮也尽量中文化，并统一按钮样式
        try:
            for btn in self.buttons():
                t = btn.text().strip()
                if t in ("OK", "&OK", "Ok"):
                    btn.setText("确认")
                elif t in ("Yes", "&Yes"):
                    btn.setText("确认")
                elif t in ("No", "&No"):
                    btn.setText("取消")
                elif t in ("Cancel", "&Cancel"):
                    btn.setText("取消")
                apply_buguan_dialog_button_style(btn)
        except Exception:
            pass
        return super().exec_()
