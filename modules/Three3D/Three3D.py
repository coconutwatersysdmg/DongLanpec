from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

def show_dev_placeholder():
    """显示‘功能开发中’的占位界面"""
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setAlignment(Qt.AlignCenter)

    title = QLabel("🧩 模型创建功能正在开发中……")
    title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
    title.setAlignment(Qt.AlignCenter)

    subtitle = QLabel("敬请期待完整的三维模型构建与渲染模块！")
    subtitle.setFont(QFont("Microsoft YaHei", 11))
    subtitle.setAlignment(Qt.AlignCenter)

    layout.addWidget(title)
    layout.addWidget(subtitle)
    return widget
