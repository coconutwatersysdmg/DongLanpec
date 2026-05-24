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
                
                # 0209新修改-多工况输入标识显示
                # ✅ 根据是否有工况2/3数据决定颜色
                has_data = False
                if hasattr(option.widget, "viewer"):
                    viewer = option.widget.viewer
                    if hasattr(viewer, "_has_multi_conditions"):
                        has_data = viewer._has_multi_conditions
                
                # 有数据：较明显的蓝，无数据：非常淡的蓝（更像按钮底色）
                if has_data:
                    bg_color = QColor(220, 235, 255)     # 明显的浅蓝背景
                    text_color = QColor(50, 100, 200)    # 深蓝色文字
                    border_color = QColor(130, 170, 220) # 蓝色边框
                else:
                    bg_color = QColor(245, 248, 252)     # 非常淡的灰蓝色背景（参考截图）
                    text_color = QColor(50, 50, 50)      # 深灰色/近黑色文字
                    border_color = QColor(180, 195, 220) # 灰蓝色边框
                
                rect = option.rect
                # 靠右，宽 65px（去掉省略号后可以窄一点）
                self._badge_rect = QRect(rect.right() - 70, rect.top() + 3, 65, rect.height() - 6)

                # 1. 先画实心背景
                painter.fillRect(self._badge_rect, bg_color)
                
                # 2. 画边框
                painter.setPen(border_color)
                # adjusted(-1, -1) 是为了对齐，或者直接画 rect
                painter.drawRect(self._badge_rect)
                
                # 3. 画文字
                painter.setPen(text_color)
                font = painter.font()
                font.setBold(False)
                font.setPointSize(10) # 稍微大一点，去掉...之后空间够
                painter.setFont(font)
                painter.drawText(self._badge_rect, Qt.AlignCenter, "多工况")
                
                painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.MouseButtonRelease and index.column() == 1:
            cell_text = index.data(Qt.DisplayRole)
            if isinstance(cell_text, str) and "设计压力*" in cell_text:
                # 保持与绘制时的矩形一致
                rect = QRect(option.rect.right() - 70, option.rect.top() + 3, 65, option.rect.height() - 6)
                if rect.contains(event.pos()):  # ✅ 仅点击标识框触发
                    print("[多工况] 点击了多工况标识")
                    # 找到 viewer 调用弹窗
                    if hasattr(option.widget, "viewer"):
                        option.widget.viewer._open_multi_conditions_dialog(index.row(), index.column(), "壳程/管程")
                    return True
        return super().editorEvent(event, model, option, index)
