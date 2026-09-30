import os
import re

from PyQt5.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPixmap
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


def _make_structure_tree_icon(size: int = 18) -> QIcon:
    """
    项目管理 icons 中无树形资源，按同色描边（#282836）绘制层级树：
    根节点 + 左右两个子节点。
    """
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    color = QColor(40, 38, 54)
    pen = QPen(color, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    # 坐标按 18x18 设计，缩放到实际 size
    s = size / 18.0
    root = QRectF(6.5 * s, 1.5 * s, 5 * s, 5 * s)
    left = QRectF(1.5 * s, 11.5 * s, 5 * s, 5 * s)
    right = QRectF(11.5 * s, 11.5 * s, 5 * s, 5 * s)
    painter.drawRoundedRect(root, 1.2 * s, 1.2 * s)
    painter.drawRoundedRect(left, 1.2 * s, 1.2 * s)
    painter.drawRoundedRect(right, 1.2 * s, 1.2 * s)

    # 根 → 分支：竖线到中线，再左右连到子节点
    mid_y = 9.2 * s
    root_cx = root.center().x()
    painter.drawLine(QPointF(root_cx, root.bottom()), QPointF(root_cx, mid_y))
    painter.drawLine(QPointF(left.center().x(), mid_y), QPointF(right.center().x(), mid_y))
    painter.drawLine(QPointF(left.center().x(), mid_y), QPointF(left.center().x(), left.top()))
    painter.drawLine(QPointF(right.center().x(), mid_y), QPointF(right.center().x(), right.top()))
    painter.end()
    return QIcon(pm)


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


def apply_structure_batch_button_icons(structure_button=None, batch_button=None):
    """
    零部件预览表工具栏按钮图标：
    - 结构树：代码绘制层级树（项目管理 icons 无对应资源）
    - 批量替换：复用项目管理「修改.png」
    """
    structure_icon = _make_structure_tree_icon(_ICON_SIZE.width())
    batch_icon = _load_chanpinguanli_icon("修改.png")
    if structure_button is not None:
        structure_button.setIcon(structure_icon)
        structure_button.setIconSize(_ICON_SIZE)
    if batch_button is not None:
        batch_button.setIcon(batch_icon)
        batch_button.setIconSize(_ICON_SIZE)


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


class EditableOnlyTabFilter(QObject):
    """
    仅处理 Tab / Shift+Tab：只在可输入单元格间跳转。
    不改动 Enter / 方向键等其它行为。

    mode:
      - "editable"：跳到下一个可输入单元格（参数值等）
      - "none"：表内不用 Tab 换格；可配合 jump_to_getter，一键跳进右侧详细表
    """

    def __init__(self, table, mode="editable", jump_to_getter=None):
        super().__init__(table)
        self.table = table
        self.mode = mode  # "editable" | "none"
        self.jump_to_getter = jump_to_getter  # callable -> QTableWidget | None

    def _focus_in_this_table(self) -> bool:
        w = QApplication.focusWidget()
        if w is None:
            return False
        t = self.table
        if w is t or w is t.viewport():
            return True
        p = w.parent()
        while p is not None:
            if p is t or p is t.viewport():
                return True
            p = p.parent()
        return False

    def _is_tabbable(self, row: int, col: int) -> bool:
        t = self.table
        if row < 0 or col < 0 or row >= t.rowCount() or col >= t.columnCount():
            return False
        if t.isRowHidden(row) or t.isColumnHidden(col):
            return False

        # ReadOnlyDelegate：不可弹出编辑器 → 不参与 Tab
        try:
            idx = t.model().index(row, col) if t.model() is not None else None
            delegate = t.itemDelegateForRow(row)
            if delegate is None and idx is not None:
                delegate = t.itemDelegate(idx)
            if delegate is not None and type(delegate).__name__ == "ReadOnlyDelegate":
                return False
        except Exception:
            pass

        w = t.cellWidget(row, col)
        if w is not None:
            return bool(w.isEnabled() and w.isVisible())
        it = t.item(row, col)
        if it is None:
            return False
        flags = it.flags()
        if not (flags & Qt.ItemIsEnabled):
            return False
        return bool(flags & Qt.ItemIsEditable)

    def _iter_cells(self, start_row, start_col, forward=True):
        t = self.table
        rows = t.rowCount()
        cols = t.columnCount()
        if rows <= 0 or cols <= 0:
            return
        total = rows * cols
        idx0 = start_row * cols + start_col
        for step in range(1, total + 1):
            if forward:
                idx = (idx0 + step) % total
            else:
                idx = (idx0 - step) % total
            yield divmod(idx, cols)

    def _find_next_tabbable(self, row, col, forward=True):
        for r, c in self._iter_cells(row, col, forward=forward):
            if self._is_tabbable(r, c):
                return r, c
        return None

    def _find_first_tabbable(self):
        t = self.table
        for r in range(t.rowCount()):
            for c in range(t.columnCount()):
                if self._is_tabbable(r, c):
                    return r, c
        return None

    def _close_editor_quietly(self):
        t = self.table
        if t.state() != t.EditingState:
            return
        try:
            t.setFocus(Qt.OtherFocusReason)
        except Exception:
            pass

    def _jump_into_target_table(self) -> bool:
        getter = self.jump_to_getter
        if not callable(getter):
            return False
        try:
            target = getter()
        except Exception:
            target = None
        if target is None:
            return False
        return focus_first_editable_cell(target)

    def eventFilter(self, obj, event):
        if event.type() != QEvent.KeyPress:
            return super().eventFilter(obj, event)

        key = event.key()
        if key not in (Qt.Key_Tab, Qt.Key_Backtab):
            return super().eventFilter(obj, event)

        forward = key != Qt.Key_Backtab and not bool(event.modifiers() & Qt.ShiftModifier)

        # 应用级过滤：只处理焦点在本表（含编辑器）的情况
        in_table = self._focus_in_this_table() or obj in (self.table, self.table.viewport())
        if not in_table:
            return super().eventFilter(obj, event)

        # 左侧预览表：第一次 Tab 直接进入右侧详细定义可输入格
        if self.mode == "none":
            if forward and self._jump_into_target_table():
                return True
            # Shift+Tab 或找不到右侧表：交给默认焦点链
            return False

        cur = self.table.currentIndex()
        row = cur.row() if cur.isValid() else 0
        col = cur.column() if cur.isValid() else 0
        if row < 0:
            row = 0
        if col < 0:
            col = 0

        self._close_editor_quietly()
        nxt = self._find_next_tabbable(row, col, forward=forward)
        if nxt is None:
            return True
        nr, nc = nxt
        self.table.setCurrentCell(nr, nc)
        return True


def focus_first_editable_cell(table) -> bool:
    """把焦点落到表内第一个可输入单元格。"""
    if table is None:
        return False
    flt = getattr(table, "_editable_only_tab_filter", None)
    try:
        table.setFocus(Qt.TabFocusReason)
    except Exception:
        try:
            table.setFocus()
        except Exception:
            return False

    target = None
    if flt is not None and hasattr(flt, "_find_first_tabbable"):
        target = flt._find_first_tabbable()
    else:
        # 兜底：按 ItemIsEditable 扫描
        for r in range(table.rowCount()):
            for c in range(table.columnCount()):
                if table.isRowHidden(r) or table.isColumnHidden(c):
                    continue
                it = table.item(r, c)
                if it and (it.flags() & Qt.ItemIsEnabled) and (it.flags() & Qt.ItemIsEditable):
                    target = (r, c)
                    break
            if target:
                break
    if target is None:
        return False
    table.setCurrentCell(target[0], target[1])
    return True


def skip_tab_bar_focus(tab_widget):
    """页签标题（PNO.1 / + 等）不进 Tab 焦点链，点击仍可切换。"""
    if tab_widget is None:
        return
    try:
        from PyQt5.QtWidgets import QTabBar
        bar = tab_widget.tabBar() if hasattr(tab_widget, "tabBar") else None
        if bar is not None:
            bar.setFocusPolicy(Qt.NoFocus)
        # TabWidget 自身不抢 Tab；子表格仍可聚焦
        tab_widget.setFocusPolicy(Qt.NoFocus)
    except Exception:
        pass


def install_editable_only_tab(table, *, mode="editable", jump_to_getter=None):
    """
    给 QTableWidget 安装“Tab 仅可输入格”行为（可重复调用，只装一次）。
    mode="editable"：详细定义表；mode="none"：左侧零部件预览表。
    jump_to_getter：mode=none 时，Tab 跳转到的目标表获取函数。
    """
    if table is None:
        return None
    existing = getattr(table, "_editable_only_tab_filter", None)
    if existing is not None:
        try:
            existing.mode = mode
            if jump_to_getter is not None:
                existing.jump_to_getter = jump_to_getter
        except Exception:
            pass
        return existing

    flt = EditableOnlyTabFilter(table, mode=mode, jump_to_getter=jump_to_getter)
    table.installEventFilter(flt)
    try:
        table.viewport().installEventFilter(flt)
    except Exception:
        pass
    try:
        table.setTabKeyNavigation(False)
    except Exception:
        pass

    app = QApplication.instance()
    if app is not None:
        app.installEventFilter(flt)

    table._editable_only_tab_filter = flt
    return flt
