# -*- coding: utf-8 -*-
"""
中下部空白区（.ui 里的 widget_control）的占位示意图。

正式项目在这里嵌入 HeatExchangerView，用真实产品参数画换热器本体 + 管口。
那份绘图依赖 MySQL 里的产品记录，Demo 拿不到，所以这里用 QPainter 画一张
简化示意图：壳体、封头、折流板 + 按周向方位挂上去的管口，选中哪一行就高亮哪个管口。
只是"看得见的反馈"，不参与任何计算，也不冒充工程图。
"""
from __future__ import annotations

from typing import Any, Dict, List

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import QWidget

LINE = QColor("#4a5568")
SHELL_FILL = QColor("#f7fafd")
TUBE = QColor("#9ab0d0")
HIGHLIGHT = QColor("#0a7d3b")
MUTED = QColor("#9aa5b1")


class ExchangerSketch(QWidget):
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._rows: List[Dict[str, Any]] = []
        self._highlight = ""
        self.setMinimumHeight(200)
        self.setAutoFillBackground(True)

    def set_data(self, rows: List[Dict[str, Any]], highlight: str = ""):
        self._rows = list(rows or [])
        self._highlight = (highlight or "").upper()
        self.update()

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#ffffff"))

        w, h = self.width(), self.height()
        p.setPen(QPen(MUTED))
        p.setFont(QFont("Microsoft YaHei", 8))
        p.drawText(10, 16, "管口分布示意图（Demo 简化绘制，非工程图）")

        left, right = 70.0, 70.0
        top, bottom = 34.0, 26.0
        area = QRectF(left, top, max(120.0, w - left - right), max(60.0, h - top - bottom))

        length = area.width() * 0.74
        radius = min(area.height() * 0.30, length / 5.4)
        radius = max(radius, 16.0)
        shell = QRectF(area.center().x() - length / 2, area.center().y() - radius, length, radius * 2)

        self._draw_shell(p, shell, radius)
        self._draw_tubes(p, shell, radius)

        if not self._rows:
            p.setPen(QPen(MUTED))
            p.setFont(QFont("Microsoft YaHei", 9))
            p.drawText(shell.adjusted(0, 0, 0, 0), Qt.AlignCenter,
                       "还没有管口 —— 在右侧输入指令，这里的管口会同步出现")
            return

        self._draw_nozzles(p, shell, radius)

    def _draw_shell(self, p: QPainter, shell: QRectF, radius: float):
        p.setPen(QPen(LINE, 1.4))
        p.setBrush(SHELL_FILL)
        p.drawRect(shell)

        # 两端封头（椭圆近似）
        head_w = radius * 0.85
        for rect in (
            QRectF(shell.left() - head_w, shell.top(), head_w * 2, shell.height()),
            QRectF(shell.right() - head_w, shell.top(), head_w * 2, shell.height()),
        ):
            p.drawEllipse(rect)

        # 管板分界线：把管箱与壳体分开
        p.setPen(QPen(LINE, 1.0, Qt.DashLine))
        for x in (shell.left() + shell.width() * 0.09, shell.right() - shell.width() * 0.09):
            p.drawLine(QPointF(x, shell.top()), QPointF(x, shell.bottom()))

        # 固定鞍座
        p.setPen(QPen(LINE, 1.2))
        p.setBrush(QColor("#eef2f7"))
        seat_w = shell.width() * 0.10
        for ratio in (0.22, 0.72):
            x = shell.left() + shell.width() * ratio
            p.drawRect(QRectF(x, shell.bottom(), seat_w, 12))

    def _draw_tubes(self, p: QPainter, shell: QRectF, radius: float):
        p.setPen(QPen(TUBE, 1.0))
        for ratio in (-0.45, -0.15, 0.15, 0.45):
            y = shell.center().y() + radius * ratio
            p.drawLine(QPointF(shell.left() + radius * 0.4, y),
                       QPointF(shell.right() - radius * 0.4, y))

        # 折流板
        p.setPen(QPen(TUBE, 1.6))
        count = 6
        for i in range(count):
            x = shell.left() + shell.width() * (0.20 + 0.60 * i / (count - 1))
            if i % 2 == 0:
                p.drawLine(QPointF(x, shell.top() + radius * 0.18), QPointF(x, shell.bottom() - 4))
            else:
                p.drawLine(QPointF(x, shell.top() + 4), QPointF(x, shell.bottom() - radius * 0.18))

    def _draw_nozzles(self, p: QPainter, shell: QRectF, radius: float):
        # 先按方位分组，同侧均匀排布，避免叠在一起
        groups: Dict[str, List[Dict[str, Any]]] = {"top": [], "bottom": [], "left": [], "right": []}
        for row in self._rows:
            groups[self._side_of(row)].append(row)

        stub = max(22.0, radius * 0.55)
        flange = max(14.0, radius * 0.32)
        head_w = radius * 0.85

        for side, rows in groups.items():
            n = len(rows)
            for i, row in enumerate(rows):
                frac = (i + 1) / (n + 1)
                self._draw_one(p, shell, radius, side, frac, row, stub, flange, head_w)

    @staticmethod
    def _side_of(row: Dict[str, Any]) -> str:
        use = str(row.get("管口用途") or "")
        if "管程" in use:
            # 管程管口开在两端管箱上
            return "left" if ("入口" in use or "进" in use) else "right"
        try:
            angle = float(row.get("周向方位(°)") or 270)
        except (TypeError, ValueError):
            angle = 270.0
        angle %= 360
        # 壳程管口只画在壳体上下，避免和两端管箱的管口挤在一起
        return "top" if 0 < angle < 180 else "bottom"

    def _draw_one(self, p: QPainter, shell: QRectF, radius: float, side: str,
                  frac: float, row: Dict[str, Any], stub: float, flange: float,
                  head_w: float):
        code = str(row.get("管口代号") or "")
        size = row.get("公称尺寸")
        unit = row.get("尺寸单位") or "DN"
        label = f"{code}" if code else ""
        sub = ""
        if size not in (None, ""):
            sub = f"{unit} {size}"

        hot = bool(self._highlight) and code.upper() == self._highlight
        pen = QPen(HIGHLIGHT if hot else LINE, 2.2 if hot else 1.3)
        p.setPen(pen)
        p.setBrush(QColor("#ffffff"))

        if side in ("left", "right"):
            # 管程接管开在两端封头上，从封头顶点往外伸
            x = shell.left() - head_w if side == "left" else shell.right() + head_w
            y = shell.top() + shell.height() * frac
            sign = -1 if side == "left" else 1
            p.drawLine(QPointF(x, y), QPointF(x + sign * stub, y))
            p.drawLine(QPointF(x + sign * stub, y - flange / 2),
                       QPointF(x + sign * stub, y + flange / 2))
            p.drawLine(QPointF(x + sign * stub, y - flange / 2),
                       QPointF(x + sign * stub + sign * 4, y - flange / 2))
            p.drawLine(QPointF(x + sign * stub, y + flange / 2),
                       QPointF(x + sign * stub + sign * 4, y + flange / 2))
            tx = x + sign * (stub + 8)
            self._text(p, tx, y - 4, label, sub, hot, Qt.AlignLeft if sign > 0 else Qt.AlignRight)
            return

        x = shell.left() + shell.width() * frac
        y = shell.top() if side == "top" else shell.bottom()
        sign = -1 if side == "top" else 1
        p.drawLine(QPointF(x, y), QPointF(x, y + sign * stub))
        p.drawLine(QPointF(x - flange / 2, y + sign * stub),
                   QPointF(x + flange / 2, y + sign * stub))
        p.drawLine(QPointF(x - flange / 2, y + sign * stub),
                   QPointF(x - flange / 2, y + sign * (stub + 4)))
        p.drawLine(QPointF(x + flange / 2, y + sign * stub),
                   QPointF(x + flange / 2, y + sign * (stub + 4)))
        ty = y + sign * (stub + 14)
        self._text(p, x, ty, label, sub, hot, Qt.AlignHCenter)

    def _text(self, p: QPainter, x: float, y: float, label: str, sub: str,
              hot: bool, align):
        p.setPen(QPen(HIGHLIGHT if hot else QColor("#1f2937")))
        font = QFont("Microsoft YaHei", 8)
        font.setBold(hot)
        p.setFont(font)
        rect = QRectF(x - 60, y - 12, 120, 16)
        p.drawText(rect, int(align) | int(Qt.AlignVCenter), label)
        if sub:
            p.setPen(QPen(MUTED))
            p.setFont(QFont("Microsoft YaHei", 7))
            p.drawText(QRectF(x - 60, y + 3, 120, 14), int(align) | int(Qt.AlignVCenter), sub)
