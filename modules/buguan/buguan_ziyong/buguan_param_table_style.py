"""布管左侧参数表样式：供管板连接、管板型式等页复用。"""
import os

from PyQt5.QtCore import Qt, QTimer, QPersistentModelIndex, QObject, QEvent
from PyQt5.QtGui import QColor, QPalette, QPen, QPainter
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QStyledItemDelegate,
    QLineEdit,
    QStyle,
)

# 与元件定义 paradefine_newui.ui 中 QComboBox 一致
PARAM_VALUE_BORDER_COLOR = "#CCCCCC"
PARAM_VALUE_TEXT_COLOR = "#1f1f1f"
PARAM_VALUE_SELECTION_BG = "#d9e6f7"
PARAM_COMBO_ARROW_COLOR = "#808080"


def _combo_arrow_stylesheet_url():
    """元件定义同款灰色箭头 SVG，供 QSS url() 使用。"""
    svg_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "cailiaodingyi",
        "ui",
        "combo_arrow_gray.svg",
    )
    return os.path.abspath(svg_path).replace("\\", "/")


def _param_combo_popup_stylesheet():
    """下拉弹出列表与内嵌 QLineEdit 样式（与元件定义一致）。"""
    return (
        "QComboBox::drop-down {"
        "  subcontrol-origin: padding;"
        "  subcontrol-position: top right;"
        "  width: 14px;"
        "  border: none;"
        "  background: transparent;"
        "}"
        f"QComboBox::down-arrow {{"
        f"  image: url({_combo_arrow_stylesheet_url()});"
        "  width: 10px;"
        "  height: 6px;"
        "}"
        "QComboBox QAbstractItemView {"
        "  background-color: #ffffff;"
        "  border: 1px solid #CCCCCC;"
        "  color: #1f1f1f;"
        "  selection-background-color: #d9e6f7;"
        "  selection-color: #1f1f1f;"
        "  outline: 0;"
        "}"
        "QComboBox QLineEdit {"
        "  border: none;"
        "  background: transparent;"
        "  padding: 0;"
        "  margin: 0;"
        "  color: #1f1f1f;"
        "  selection-background-color: #d9e6f7;"
        "  selection-color: #1f1f1f;"
        "}"
    )


def get_param_combo_stylesheet(disabled=False):
    """参数表内嵌 QComboBox 样式（与元件定义下拉框一致）。"""
    base = (
        "background-color: #ffffff;"
        "border: 1px solid #CCCCCC;"
        "color: #1f1f1f;"
        "font-size: 10pt;"
        "min-height: 22px;"
        "padding: 1px 16px 1px 4px;"
    )
    popup = _param_combo_popup_stylesheet()
    if disabled:
        return (
            "QComboBox {"
            f"{base}"
            "background-color: #f5f7fa;"
            "color: #969696;"
            "}"
            f"{popup}"
        )
    return f"QComboBox {{{base}}}{popup}"


def apply_param_combo_widget_style(combo, disabled=False):
    """为参数表 QComboBox 应用元件定义同款样式，并修正选中行后文字变白。"""
    if not isinstance(combo, QComboBox):
        return
    combo.setStyleSheet(get_param_combo_stylesheet(disabled=disabled))
    text_color = QColor("#969696" if disabled else PARAM_VALUE_TEXT_COLOR)
    pal = combo.palette()
    for group in (
        QPalette.Active,
        QPalette.Inactive,
        QPalette.Disabled,
    ):
        pal.setColor(group, QPalette.Text, text_color)
        pal.setColor(group, QPalette.ButtonText, text_color)
        pal.setColor(group, QPalette.WindowText, text_color)
        if group != QPalette.Disabled:
            pal.setColor(group, QPalette.Highlight, QColor(PARAM_VALUE_SELECTION_BG))
            pal.setColor(
                group, QPalette.HighlightedText, QColor(PARAM_VALUE_TEXT_COLOR)
            )
    combo.setPalette(pal)
    le = combo.lineEdit()
    if le is not None:
        le.setStyleSheet(
            "border: none; background: transparent; padding: 0; margin: 0;"
            f"color: {PARAM_VALUE_TEXT_COLOR};"
            f"selection-background-color: {PARAM_VALUE_SELECTION_BG};"
            f"selection-color: {PARAM_VALUE_TEXT_COLOR};"
        )
        le_pal = le.palette()
        for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
            le_pal.setColor(group, QPalette.Text, text_color)
            if group != QPalette.Disabled:
                le_pal.setColor(
                    group, QPalette.HighlightedText, QColor(PARAM_VALUE_TEXT_COLOR)
                )
        le.setPalette(le_pal)


def schedule_combo_show_popup(combo, delay_ms=50):
    """延迟展开下拉列表，避免 table delegate 首次点击时被 mouseRelease 立刻关闭 editor。"""
    if combo is None:
        return

    def _open():
        try:
            if combo.isVisible():
                combo.setFocus(Qt.PopupFocusReason)
                view = combo.view()
                if view is not None and view.isVisible():
                    return
                combo.showPopup()
        except Exception:
            pass

    QTimer.singleShot(delay_ms, _open)


class _ComboAutoPopupFilter(QObject):
    """editor 显示后自动展开下拉（与 schedule_combo_show_popup 双保险）。"""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show and isinstance(obj, QComboBox):
            schedule_combo_show_popup(obj, delay_ms=0)
        return False


def install_combo_auto_popup(combo):
    if combo is None:
        return
    filt = _ComboAutoPopupFilter(combo)
    combo._buguan_auto_popup_filter = filt
    combo.installEventFilter(filt)


def buguan_param_table_combo_editor_event(
    table, event, index, value_column=2, auto_popup=True
):
    """单击参数值列整格即进入编辑（不限箭头区域）。

    返回 None 表示未处理，交回 super；True/False 表示已消费事件。
    """
    if index.column() != value_column:
        return None
    if not (index.flags() & Qt.ItemIsEditable):
        return False
    if event.type() != QEvent.MouseButtonRelease:
        return None
    if event.button() != Qt.LeftButton:
        return False

    persistent = QPersistentModelIndex(index)

    def _open_editor():
        try:
            if table is None or not persistent.isValid():
                return
            table.setCurrentIndex(persistent)
            if table.state() != QAbstractItemView.EditingState:
                table.edit(persistent)
            elif auto_popup:
                ew = table.indexWidget(persistent)
                if isinstance(ew, QComboBox):
                    schedule_combo_show_popup(ew, delay_ms=0)
        except Exception:
            pass

    QTimer.singleShot(0, _open_editor)
    return True


def paint_param_value_box(painter, box_rect, editable):
    """绘制参数值列单元格外框（直角、#CCCCCC 边框）。"""
    painter.setBrush(QColor("#f5f7fa" if not editable else "#ffffff"))
    painter.setPen(QPen(QColor(PARAM_VALUE_BORDER_COLOR), 1))
    painter.drawRect(box_rect)


def paint_param_combo_chevron(painter, box_rect, arrow_w=14):
    """绘制右侧灰色下拉箭头（与 combo_arrow_gray.svg 一致）。"""
    arrow_rect = box_rect.adjusted(box_rect.width() - arrow_w, 0, -4, 0)
    painter.setPen(QPen(QColor(PARAM_COMBO_ARROW_COLOR), 1.2))
    cx = arrow_rect.center().x()
    cy = arrow_rect.center().y()
    painter.drawLine(cx - 4, cy - 2, cx, cy + 2)
    painter.drawLine(cx, cy + 2, cx + 4, cy - 2)


PARAM_TABLE_STYLE_SHEET = """
QTableWidget {
    gridline-color: #d4d4d4;
    background-color: #ffffff;
    border: 1px solid #bdbdbd;
    font-size: 10pt;
    selection-background-color: #e3f2fd;
    selection-color: #212121;
}
QTableWidget::item {
    padding: 4px 6px;
    border-bottom: 1px solid #eeeeee;
}
QTableWidget::item:alternate {
    background-color: #fafafa;
}
QTableWidget::item:selected {
    background-color: #e3f2fd;
    color: #212121;
}
QHeaderView::section {
    background-color: #f2f2f2;
    color: #222222;
    padding: 6px 4px;
    border: none;
    border-bottom: 1px solid #bdbdbd;
    border-right: 1px solid #e0e0e0;
    font-weight: 700;
    font-size: 10pt;
}
QTableWidget QWidget {
    background-color: transparent;
}
QTableWidget QLineEdit {
    border: 1px solid #dcdfe6;
    border-radius: 4px;
    padding: 2px 10px;
    background-color: #ffffff;
    color: #303133;
    font-size: 10pt;
    min-height: 24px;
}
QTableWidget QComboBox {
    border: 1px solid #CCCCCC;
    padding: 1px 16px 1px 4px;
    background-color: #ffffff;
    color: #1f1f1f;
    font-size: 10pt;
    min-height: 22px;
}
QTableWidget QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 14px;
    border: none;
    background: transparent;
}
QTableWidget QComboBox::down-arrow {
    image: url(__COMBO_ARROW_URL__);
    width: 10px;
    height: 6px;
}
QTableWidget QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #CCCCCC;
    color: #1f1f1f;
    selection-background-color: #d9e6f7;
    selection-color: #1f1f1f;
}
QTableWidget QComboBox QLineEdit {
    border: none;
    background: transparent;
    padding: 0;
    margin: 0;
    color: #1f1f1f;
    selection-background-color: #d9e6f7;
    selection-color: #1f1f1f;
}
QTableWidget QComboBox:disabled {
    background-color: #f5f7fa;
    color: #969696;
}
""".replace("__COMBO_ARROW_URL__", _combo_arrow_stylesheet_url())


class ParamValueCellDelegate(QStyledItemDelegate):
    """参数值列：圆角白底边框（与布管左侧参数表一致）。"""

    def __init__(self, value_column=1, parent=None):
        super().__init__(parent)
        self._value_column = value_column

    def paint(self, painter, option, index):
        if index.column() != self._value_column:
            super().paint(painter, option, index)
            return

        table = option.widget
        if table is not None and table.cellWidget(index.row(), index.column()) is not None:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())

        box_rect = option.rect.adjusted(5, 4, -5, -4)
        editable = bool(index.flags() & Qt.ItemIsEditable)

        paint_param_value_box(painter, box_rect, editable)

        text = "" if index.data(Qt.DisplayRole) is None else str(index.data(Qt.DisplayRole))
        painter.setPen(QColor("#969696" if not editable else "#303133"))
        text_rect = box_rect.adjusted(10, 0, -8, 0)
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)
        painter.restore()

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setFrame(False)
        editor.setStyleSheet(
            "QLineEdit {"
            "  border: 1px solid #dcdfe6;"
            "  border-radius: 4px;"
            "  padding: 2px 10px;"
            "  background-color: #ffffff;"
            "  color: #303133;"
            "  font-size: 10pt;"
            "}"
            "QLineEdit:focus {"
            "  border: 1px solid #c0c4cc;"
            "}"
        )
        return editor

    def setEditorData(self, editor, index):
        editor.setText(
            "" if index.data(Qt.DisplayRole) is None else str(index.data(Qt.DisplayRole))
        )

    def setModelData(self, editor, model, index):
        model.setData(index, editor.text(), Qt.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect.adjusted(5, 4, -5, -4))


def apply_buguan_param_table_style(table, value_column_index=1, extra_value_columns=None):
    """将布管左侧参数表的表格与参数值列输入框样式应用到指定表格。

    extra_value_columns: 其它需要圆角输入框样式的列（如元件表的距离、厚度列）。
    """
    if table is None:
        return
    try:
        value_cols = [value_column_index]
        if extra_value_columns:
            for col in extra_value_columns:
                if col not in value_cols:
                    value_cols.append(col)
        table.setAlternatingRowColors(True)
        table.setShowGrid(True)
        try:
            table.verticalHeader().setDefaultSectionSize(34)
        except Exception:
            pass
        for col in value_cols:
            table.setItemDelegateForColumn(
                col,
                ParamValueCellDelegate(value_column=col, parent=table),
            )
        table.setStyleSheet(PARAM_TABLE_STYLE_SHEET)
    except Exception:
        pass
