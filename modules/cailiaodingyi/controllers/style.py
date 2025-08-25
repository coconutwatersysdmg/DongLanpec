from PyQt5.QtCore import QEvent, QObject, Qt

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
