from PyQt5.QtWidgets import QApplication, QTableWidget, QTableWidgetItem, QWidget, QVBoxLayout
from PyQt5.QtCore import Qt
import sys

class EditableTableDemo(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("垫片宽度配置表测试")
        self.resize(500, 300)

        self.table = QTableWidget()
        layout = QVBoxLayout()
        layout.addWidget(self.table)
        self.setLayout(layout)

        self.init_table()

    def init_table(self):
        data = [
            ["≤500", "10", "12"],
            ["≤700", "15", "18"],
            ["≤1200", "20", "22"],
            ["≤2000", "25", "28"],
            ["≤2600", "30", "35"],
            ["≤3000", "40", "45"]
        ]
        headers = ["col_0", "col_1", "col_2"]
        editable_conditions = ["≤700", "≤1200", "≤2000", "≤2600"]

        self.table.setRowCount(len(data))
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)

        for row_idx, row_data in enumerate(data):
            is_editable_row = row_data[0] in editable_conditions
            for col_idx, val in enumerate(row_data):
                item = QTableWidgetItem(val)
                if is_editable_row and col_idx in [1, 2]:
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                else:
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                self.table.setItem(row_idx, col_idx, item)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = EditableTableDemo()
    win.show()
    sys.exit(app.exec_())
