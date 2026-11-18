"""Message and recent-task layout for the chat workspace."""
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QColor, QFont, QFontMetrics
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy, QStyle,
                             QStyledItemDelegate, QVBoxLayout, QWidget)


USER_MESSAGE_WIDTH = 650


class UserMessageText(QLabel):
    def sizeHint(self):
        metrics = self.fontMetrics()
        longest_line = max((metrics.horizontalAdvance(line) for line in self.text().splitlines()), default=0)
        width = min(longest_line+2, USER_MESSAGE_WIDTH-34)
        return QSize(width, self.heightForWidth(width))


def message_row(role, text):
    user = role == 'user'
    frame = QFrame()
    frame.setObjectName('userBubble' if user else 'assistantMessage')
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 12 if user else 6, 16, 12)
    layout.setSpacing(5)
    if not user:
        author = QLabel('工程 Agent')
        author.setObjectName('messageAuthor')
        layout.addWidget(author)
    label = UserMessageText(text) if user else QLabel(text)
    label.setObjectName('messageText')
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
    layout.addWidget(label)
    if not user:
        return frame
    frame.setMaximumWidth(USER_MESSAGE_WIDTH)
    lane = QWidget()
    alignment = QHBoxLayout(lane)
    alignment.setContentsMargins(0, 0, 0, 0)
    alignment.addStretch(1)
    alignment.addWidget(frame)
    return lane


class RecentChatDelegate(QStyledItemDelegate):
    """Elide the title by pixels and keep its status on a separate line."""
    def sizeHint(self, option, index):
        return QSize(1, option.fontMetrics.height()*2 + 18)

    def paint(self, painter, option, index):
        rect = option.rect.adjusted(0, 2, -1, -2)
        selected = bool(option.state & QStyle.State_Selected)
        painter.save()
        if selected or option.state & QStyle.State_MouseOver:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor('#dfe8ff' if selected else '#e6ebf5'))
            painter.setRenderHint(painter.Antialiasing)
            painter.drawRoundedRect(rect, 9, 9)
        title_font = QFont(option.font)
        title_font.setBold(selected)
        title_metrics = QFontMetrics(title_font)
        info = rect.adjusted(10, 0, -10, 0)
        title_y = rect.top() + (rect.height()-2*option.fontMetrics.height())//2 + title_metrics.ascent()
        painter.setPen(QColor('#20365e' if selected else '#24324b'))
        painter.setFont(title_font)
        painter.drawText(info.left(), title_y,
                         title_metrics.elidedText(str(index.data() or ''), Qt.ElideRight, info.width()))
        painter.setPen(QColor('#64748b'))
        painter.setFont(option.font)
        painter.drawText(info.left(), title_y + option.fontMetrics.height(),
                         option.fontMetrics.elidedText(str(index.data(Qt.UserRole+1) or ''), Qt.ElideRight, info.width()))
        painter.restore()
