from PyQt5.QtWidgets import QUndoCommand, QTableWidgetItem

class CellEditCommand(QUndoCommand):
    def __init__(self, table, row, col, old_value, new_value):
        super().__init__(f"Edit ({row},{col})")
        self.table = table
        self.row = row
        self.col = col
        self.old_value = old_value
        self.new_value = new_value

    def undo(self):
        self.table.blockSignals(True)
        item = self.table.item(self.row, self.col)
        if item is None:
            item = QTableWidgetItem()
            self.table.setItem(self.row, self.col, item)
        item.setText(self.old_value)
        self.table.blockSignals(False)

    def redo(self):
        self.table.blockSignals(True)
        item = self.table.item(self.row, self.col)
        if item is None:
            item = QTableWidgetItem()
            self.table.setItem(self.row, self.col, item)
        item.setText(self.new_value)
        self.table.blockSignals(False)
