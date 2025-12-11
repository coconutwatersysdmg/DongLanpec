from PyQt5.QtWidgets import QGraphicsView
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QMouseEvent

class CustomGraphicsView(QGraphicsView):
    pointClicked = pyqtSignal(float, float)  # 自定义信号 (x, y)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            # 将视图坐标转为场景坐标
            pos = self.mapToScene(event.pos())
            x, y = pos.x(), pos.y()
            print(f"点击坐标：({x:.2f}, {y:.2f})")  # 可选打印
            self.pointClicked.emit(x, y)  # 发出信号

        super().mousePressEvent(event)
