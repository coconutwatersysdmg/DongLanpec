"""布管左侧参数表样式：供管板连接、管板型式等页复用。"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPen, QPainter
from PyQt5.QtWidgets import QStyledItemDelegate, QLineEdit, QStyle

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
    border: 1px solid #dcdfe6;
    border-radius: 4px;
    padding: 2px 28px 2px 10px;
    background-color: #ffffff;
    color: #303133;
    font-size: 10pt;
    min-height: 24px;
}
QTableWidget QComboBox QAbstractItemView {
    color: #303133;
    selection-background-color: #e3f2fd;
    selection-color: #212121;
}
QTableWidget QComboBox QLineEdit {
    color: #303133;
    selection-background-color: #b3d7ff;
    selection-color: #212121;
}
QTableWidget QComboBox:disabled {
    background-color: #f5f7fa;
    color: #969696;
}
"""


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
