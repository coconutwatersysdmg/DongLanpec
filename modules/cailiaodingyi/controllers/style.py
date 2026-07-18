import os
import re

from PyQt5.QtCore import QEvent, QObject, QSize, Qt
from PyQt5.QtGui import QFont, QFontMetrics, QIcon
from PyQt5.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton

# 复用项目管理按钮样式（不修改 ui_style.py）
from modules.chanpinguanli.ui_style import CHANPINGUANLI_BUTTON_QSS as BUTTON_QSS

_CHANPINGUANLI_ICONS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "chanpinguanli", "icons")
)
_ICON_SIZE = QSize(18, 18)


# 弹窗正文对齐项目管理确认框：宋体 + 12pt（ui_style 里 14px 偏小）
DIALOG_QSS = """
QDialog, QMessageBox {
    background-color: #ffffff;
    color: #000000;
    font-family: "宋体", SimSun;
    font-size: 12pt;
}

QMessageBox QLabel {
    background: transparent;
    color: #000000;
    font-family: "宋体", SimSun;
    font-size: 12pt;
    min-width: 480px;
}

QPushButton {
    font-family: "宋体", SimSun;
}
""" + BUTTON_QSS

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _dialog_font():
    """与项目管理弹窗一致：优先宋体，字号至少 12pt。"""
    font = QFont(QApplication.font())
    family = (font.family() or "").strip()
    if family not in ("宋体", "SimSun"):
        font.setFamily("宋体")
    if font.pointSize() > 0 and font.pointSize() < 12:
        font.setPointSize(12)
    elif font.pointSize() <= 0:
        font.setPointSize(12)
    return font


def _plain_dialog_text(text: str) -> str:
    plain = (text or "")
    plain = re.sub(r"<br\s*/?>", "\n", plain, flags=re.IGNORECASE)
    plain = _HTML_TAG_RE.sub("", plain)
    return (
        plain.replace("&nbsp;", " ")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
    )


def _fit_message_box_width(box):
    """按正文最长行加宽，避免字号变大后右侧被裁切。"""
    if not isinstance(box, QMessageBox):
        return
    plain = _plain_dialog_text(box.text())
    # RichText 里常用 <br>，上面已剥标签；再按换行估宽
    lines = [ln for ln in plain.replace("\r", "").split("\n") if ln.strip()] or [plain]
    fm = QFontMetrics(_dialog_font())
    max_line_w = max((fm.horizontalAdvance(ln) for ln in lines), default=0)
    # 图标区 + 边距；上限避免超屏
    screen = QApplication.primaryScreen()
    screen_w = screen.availableGeometry().width() if screen else 1200
    content_w = min(max(max_line_w + 40, 480), max(screen_w - 160, 480))
    box_w = min(content_w + 100, screen_w - 80)

    for label in box.findChildren(QLabel):
        label.setWordWrap(True)
        # 只放宽正文标签，避免图标旁空白异常
        if label.objectName() == "qt_msgbox_label" or label.text() == box.text():
            label.setMinimumWidth(content_w)

    box.setMinimumWidth(box_w)
    box.adjustSize()


def apply_dialog_style(dialog):
    """为 QDialog / QMessageBox 应用与项目管理一致的弹窗样式与字体。"""
    dialog.setFont(_dialog_font())
    dialog.setStyleSheet(DIALOG_QSS)
    _fit_message_box_width(dialog)
    return dialog


def apply_button_style(button):
    """为单个按钮应用与项目管理一致的按钮样式。"""
    if button is not None:
        button.setStyleSheet(BUTTON_QSS)
    return button


def _load_chanpinguanli_icon(filename: str) -> QIcon:
    path = os.path.join(_CHANPINGUANLI_ICONS_DIR, filename)
    return QIcon(path) if os.path.isfile(path) else QIcon()


def apply_confirm_clear_button_icons(confirm_buttons=None, clear_buttons=None):
    """
    详细定义底部按钮图标：
    - 确定：复用项目管理「保存.png」
    - 清空：复用项目管理「删除.png」
    """
    confirm_icon = _load_chanpinguanli_icon("保存.png")
    clear_icon = _load_chanpinguanli_icon("删除.png")
    for btn in confirm_buttons or []:
        if btn is None:
            continue
        btn.setIcon(confirm_icon)
        btn.setIconSize(_ICON_SIZE)
    for btn in clear_buttons or []:
        if btn is None:
            continue
        btn.setIcon(clear_icon)
        btn.setIconSize(_ICON_SIZE)


def exec_message_box(box):
    """样式化后执行 QMessageBox / QDialog。"""
    apply_dialog_style(box)
    return box.exec_()


def _show_styled_message(parent, icon, title, text, button_text="确认"):
    msg_box = QMessageBox(parent)
    msg_box.setWindowTitle(title)
    msg_box.setText(str(text))
    msg_box.setIcon(icon)
    confirm_button = QPushButton(button_text)
    msg_box.addButton(confirm_button, QMessageBox.AcceptRole)
    apply_dialog_style(msg_box)
    msg_box.exec_()


def show_information(parent, title, text, button_text="确认"):
    _show_styled_message(parent, QMessageBox.Information, title, text, button_text)


def show_warning(parent, title, text, button_text="确认"):
    _show_styled_message(parent, QMessageBox.Warning, title, text, button_text)


def show_critical(parent, title, text, button_text="确认"):
    _show_styled_message(parent, QMessageBox.Critical, title, text, button_text)


class ReturnKeyJumpFilter(QObject):
    def __init__(self, table, after_jump_callback=None):
        super().__init__(table)
        self.table = table
        self.after_jump_callback = after_jump_callback

    def eventFilter(self, obj, event):
        # 若正在编辑，放行
        if self.table.state() == self.table.EditingState:
            return False

        if event.type() == QEvent.KeyPress:
            key = event.key()
            current = self.table.currentIndex()
            if not current.isValid():
                return False

            row = current.row()
            col = current.column()
            row_count = self.table.rowCount()

            # ⏎ Enter 或 Return
            if key in (Qt.Key_Return, Qt.Key_Enter):
                next_row = (row + 1) % row_count
                self.table.setCurrentCell(next_row, col)
                if self.after_jump_callback:
                    self.after_jump_callback(next_row, col)
                return True

            # ↑ Up
            elif key == Qt.Key_Up:
                prev_row = (row - 1 + row_count) % row_count
                self.table.setCurrentCell(prev_row, col)
                if self.after_jump_callback:
                    self.after_jump_callback(prev_row, col)
                return True

            # ↓ Down
            elif key == Qt.Key_Down:
                next_row = (row + 1) % row_count
                self.table.setCurrentCell(next_row, col)
                if self.after_jump_callback:
                    self.after_jump_callback(next_row, col)
                return True

        return super().eventFilter(obj, event)
