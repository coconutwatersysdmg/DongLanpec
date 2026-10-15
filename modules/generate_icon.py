"""Code-drawn icon shared by generation buttons."""

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def _sparkle_path(cx, cy, radius):
    inner = radius * 0.28
    path = QPainterPath(QPointF(cx, cy - radius))
    path.lineTo(cx + inner, cy - inner)
    path.lineTo(cx + radius, cy)
    path.lineTo(cx + inner, cy + inner)
    path.lineTo(cx, cy + radius)
    path.lineTo(cx - inner, cy + inner)
    path.lineTo(cx - radius, cy)
    path.lineTo(cx - inner, cy - inner)
    path.closeSubpath()
    return path


def make_generate_icon(size=32):
    """Create a unique magic-wand icon for generation actions."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    scale = size / 32.0
    color = QColor("#282636")
    painter.setPen(QPen(color, 2.6 * scale, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.drawLine(QPointF(6 * scale, 26 * scale), QPointF(21 * scale, 11 * scale))
    painter.drawLine(QPointF(17.5 * scale, 10.5 * scale), QPointF(21.5 * scale, 14.5 * scale))

    painter.setPen(QPen(color, 1.25 * scale, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.drawPath(_sparkle_path(24 * scale, 6.5 * scale, 3.8 * scale))
    painter.drawPath(_sparkle_path(8 * scale, 7.5 * scale, 2.4 * scale))
    painter.drawPath(_sparkle_path(25 * scale, 21.5 * scale, 2.5 * scale))
    painter.end()

    return QIcon(pixmap)
