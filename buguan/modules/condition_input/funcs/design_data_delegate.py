from PyQt5.QtWidgets import QItemDelegate
from PyQt5.QtGui import QColor
from PyQt5.QtCore import QRect, Qt, QEvent

class DesignDataDelegate(QItemDelegate):
    """自定义代理，为"设计压力*"单元格添加多工况标识，并响应点击"""

    def paint(self, painter, option, index):
        super().paint(painter, option, index)

        if index.column() == 1:  # 参数名称列
            cell_text = index.data(Qt.DisplayRole)
            if isinstance(cell_text, str) and "设计压力*" in cell_text:
                painter.save()
                painter.setPen(QColor(150, 150, 150))
                font = painter.font()
                font.setBold(False)
                font.setPointSize(8)
                painter.setFont(font)

                rect = option.rect
                # ✅ 保持和 paint 一致：靠右 80px 宽
                self._badge_rect = QRect(rect.right() - 85, rect.top() + 2, 80, rect.height() - 4)

                painter.drawText(self._badge_rect, Qt.AlignCenter, "多工况...")
                painter.setPen(QColor(200, 200, 200))
                painter.drawRect(self._badge_rect.adjusted(1, 1, -1, -1))
                painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.MouseButtonRelease and index.column() == 1:
            cell_text = index.data(Qt.DisplayRole)
            if isinstance(cell_text, str) and "设计压力*" in cell_text:
                rect = QRect(option.rect.right() - 85, option.rect.top() + 2, 80, option.rect.height() - 4)
                if rect.contains(event.pos()):  # ✅ 仅点击标识框触发
                    print("[多工况] 点击了多工况标识")
                    # 找到 viewer 调用弹窗
                    if hasattr(option.widget, "viewer"):
                        option.widget.viewer._open_multi_conditions_dialog(index.row(), index.column(), "壳程/管程")
                    return True
        return super().editorEvent(event, model, option, index)
