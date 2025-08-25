from PyQt5.QtCore import QObject, QEvent
from PyQt5.QtWidgets import QComboBox

class NoWheelComboBoxFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            return True  # 阻止滚轮事件
        return super().eventFilter(obj, event)
