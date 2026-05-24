"""布管左侧参数表样式：供管板连接、管板型式等页复用。"""
import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPen, QPainter
from PyQt5.QtWidgets import QStyledItemDelegate, QLineEdit, QStyle


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

        painter.setBrush(QColor("#f5f7fa" if not editable else "#ffffff"))
        painter.setPen(QPen(QColor("#dcdfe6"), 1))
        painter.drawRoundedRect(box_rect, 4, 4)

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
