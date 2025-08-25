from PyQt5.QtWidgets import QLineEdit
from PyQt5.QtCore import Qt

class RenamableLineEdit(QLineEdit):
    def __init__(self, old_label, confirm_callback, parent=None):
        super().__init__(old_label, parent)
        self.old_label = old_label
        self.confirm_callback = confirm_callback
        self._confirmed = False

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Enter, Qt.Key_Return):
            self._confirmed = True
            self.confirm_callback(self.text().strip())
            self.deleteLater()
        elif event.key() == Qt.Key_Escape:
            self.deleteLater()
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event):
        if not self._confirmed:
            self.deleteLater()
        super().focusOutEvent(event)
