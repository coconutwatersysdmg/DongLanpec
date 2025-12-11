from PyQt5 import QtWidgets, QtCore, QtGui


class CustomHeaderView(QtWidgets.QHeaderView):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setDefaultAlignment(QtCore.Qt.AlignCenter)

    def paintSection(self, painter, rect, logicalIndex):
        painter.save()

        # 背景填充色
        painter.fillRect(rect, QtGui.QColor("#F2F2F2"))

        # 绘制文字
        text = self.model().headerData(logicalIndex, self.orientation(), QtCore.Qt.DisplayRole)
        painter.setPen(QtGui.QPen(QtCore.Qt.black))

        # 设置字体为加粗← 新增的代码(统一界面需求用)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)

        painter.drawText(rect, QtCore.Qt.AlignCenter, str(text))

        # 底部分隔线
        pen = QtGui.QPen(QtGui.QColor("#CCCCCC"))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())

        # 列之间竖线
        if logicalIndex != self.model().columnCount() - 1:
            painter.drawLine(rect.topRight(), rect.bottomRight())

        painter.restore()