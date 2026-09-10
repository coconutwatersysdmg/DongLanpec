from PyQt5.QtWidgets import QItemDelegate
from PyQt5.QtGui import QColor
from PyQt5.QtCore import QRect, Qt, QEvent

class DesignDataDelegate(QItemDelegate):
    """
    作用:
        表格渲染的自定义代理。专门用于“条件输入”模块中的“参数名称”列。
        当参数名称包含“设计压力*”时，它会在单元格右侧手绘出一个“多工况...”的徽章（Badge），
        并在用户点击该徽章时拦截事件，呼出多工况数据配置的弹窗。
    """

    def paint(self, painter, option, index):
        """
        作用:
            重写底层绘图逻辑。首先调用父类方法绘制默认的文本，
            然后判断当前是否为“设计压力*”行，并根据当前设备是否已填充过“工况2/3”的数据，
            动态改变手绘徽章的颜色（深蓝色代表有数据，浅灰色代表无数据）。
        """
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
        """
        作用:
            事件拦截器。监听鼠标左键释放事件（MouseButtonRelease），
            判断鼠标坐标是否精准落在手绘的“多工况”徽章矩形区域内。
            若是，则阻断事件冒泡，并向外层 Viewer 发送弹窗指令。
        """
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
