from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt, QEvent, QObject, QTimer
from PyQt5.QtWidgets import QWidget, QToolButton, QTabWidget, QSizePolicy, QAbstractButton


class PlusTabManager(QObject):
    """
    '+' 管理：
      - 空间够：作为最后一个页签
      - 空间不够：右上角 corner 按钮
    关键修复：
      1) 首帧/大窗口启动时强制同步状态，避免角落 '+' 残留
      2) 任何时刻只保留一个 '+'
      3) corner 形态为 QTabBar 右侧预留 margin，防止重叠 & 点不动
      4) 扣除滚动箭头宽度参与判定
    """
    def __init__(self, tw: QTabWidget, on_add_from_src):
        super().__init__(tw)
        self.tw = tw
        self.on_add_from_src = on_add_from_src

        self._plus_as_tab = True
        self._plus_tab_index = -1
        self._adding = False
        self._ready = False
        self._reserved_margin = False
        self._orig_tabbar_stylesheet = tw.tabBar().styleSheet()

        bar = self.tw.tabBar()

        # 先断开旧连接 & 清理历史 '+'
        try:
            bar.tabBarClicked.disconnect(self._on_tabbar_clicked)
        except Exception:
            pass
        self._remove_all_plus_tabs()

        # 作为页签的 '+'
        self._plus_tab_index = self.tw.addTab(QWidget(), "+")
        bar.tabBarClicked.connect(self._on_tabbar_clicked)

        # 角落按钮 '+'
        self._btn = QToolButton(self.tw)
        self._btn.setText("+")
        self._btn.setAutoRaise(True)
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.clicked.connect(self._on_corner_plus_clicked)
        self.tw.setCornerWidget(self._btn, Qt.TopRightCorner)
        self._btn.hide()  # 默认隐藏

        # 监听变化
        self.tw.installEventFilter(self)
        bar.installEventFilter(self)

        # 多次延迟确保首帧同步（prefer_tab=True 避免初始放大时出现 corner 残影）
        for t in (0, 30, 80, 160, 260):
            QTimer.singleShot(t, lambda: self._force_sync(prefer_tab=True))

    # ---------- 基础工具 ----------
    def _remove_all_plus_tabs(self):
        for i in range(self.tw.count() - 1, -1, -1):
            if self.tw.tabText(i) == "+":
                self.tw.removeTab(i)

    def _ensure_single_plus(self):
        """保证只存在一种形态的 '+'。"""
        if self._plus_as_tab:
            self._btn.hide()
            # 页签里必须有 '+'
            has_plus = any(self.tw.tabText(i) == "+" for i in range(self.tw.count()))
            if not has_plus:
                self._plus_tab_index = self.tw.addTab(QWidget(), "+")
        else:
            # corner 形态必须移除所有 '+'
            self._remove_all_plus_tabs()
            self._btn.show()
            self._btn.raise_()

    def _scroll_buttons_width(self):
        w = 0
        for btn in self.tw.tabBar().findChildren(QtWidgets.QAbstractButton):
            if btn.isVisible():
                w += btn.width()
        return w

    def _plus_tab_width(self):
        fm = self.tw.tabBar().fontMetrics()
        return fm.horizontalAdvance("+") + 24

    def _reserve_corner_space(self, enable: bool):
        bar = self.tw.tabBar()
        if enable and not self._reserved_margin:
            pad = max(self._btn.width(), self._plus_tab_width()) + 6
            bar.setStyleSheet(self._orig_tabbar_stylesheet + f" QTabBar{{margin-right:{pad}px;}}")
            self._reserved_margin = True
        elif not enable and self._reserved_margin:
            bar.setStyleSheet(self._orig_tabbar_stylesheet)
            self._reserved_margin = False

    # ---------- 事件 ----------
    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Show, QEvent.ShowToParent, QEvent.Resize, QEvent.LayoutRequest, QEvent.Polish):
            QTimer.singleShot(0, self.update_mode)
        return False

    # ---------- 对外同步 ----------
    def _force_sync(self, prefer_tab: bool = False):
        """
        强制把当前形态与空间判定对齐。
        prefer_tab=True 可用于应用启动(初次很宽)强制回页签形态，避免角落 '+' 残留。
        """
        bar = self.tw.tabBar()
        if not (self.tw.isVisible() and bar.isVisible() and bar.width() > 0):
            return

        # 这里先根据 prefer_tab “纠偏”，再走一次正常判定
        if prefer_tab:
            self._plus_as_tab = True
            self._reserve_corner_space(False)
            self._btn.hide()
            self._ensure_single_plus()

        self._ready = True
        self.update_mode()

    # ---------- 判定/切换 ----------
    def update_mode(self):
        bar = self.tw.tabBar()
        w = bar.width()
        if not self._ready:
            if self.tw.isVisible() and bar.isVisible() and w > 0:
                self._ready = True
            else:
                return

        # 实际可用宽度（扣掉滚动箭头）
        visible_w = max(1, w - self._scroll_buttons_width())

        # 不含 '+' 的总宽
        total_no_plus = 0
        for i in range(bar.count()):
            if self._plus_as_tab and self.tw.tabText(i) == "+":
                continue
            total_no_plus += bar.tabSizeHint(i).width()

        need_with_plus = total_no_plus + self._plus_tab_width()

        # 目标形态
        want_corner = (need_with_plus > visible_w - 4)

        if want_corner and self._plus_as_tab:
            # 切到 corner
            self._plus_as_tab = False
            self._reserve_corner_space(True)
            self._ensure_single_plus()
        elif (not want_corner) and (not self._plus_as_tab):
            # 切回页签
            self._plus_as_tab = True
            self._reserve_corner_space(False)
            self._ensure_single_plus()

        # corner 形态保持按钮尺寸与层级
        if not self._plus_as_tab:
            self._btn.setFixedHeight(bar.sizeHint().height())
            self._btn.raise_()

    # ---------- 点击 ----------
    def _on_tabbar_clicked(self, index: int):
        if not self._plus_as_tab:
            return
        if index < 0 or self.tw.tabText(index) != "+":
            return
        self._create_from_current()

    def _on_corner_plus_clicked(self):
        self._create_from_current()

    def _create_from_current(self):
        if self._adding:
            return
        self._adding = True
        try:
            tw = self.tw
            if tw.count() == 0:
                return
            cur = tw.currentIndex()
            if cur < 0:
                cur = 0
            # 若当前在 '+' 页签上，取其前一个
            if self._plus_as_tab and self.tw.tabText(cur) == "+":
                cur = max(0, self.tw.count() - 2)
            src_idx = cur
            src_name = self.tw.tabText(src_idx)

            self.on_add_from_src(src_idx, src_name)

            # 页签形态下，'+' 必须仍在最后
            if self._plus_as_tab:
                self._remove_all_plus_tabs()
                self._plus_tab_index = self.tw.addTab(QWidget(), "+")
        finally:
            self._adding = False
            QTimer.singleShot(0, self.update_mode)

    # ---------- 批量变更后 ----------
    def refresh_after_model_change(self):
        # 重置，并尽快把 '+' 切回页签以避免 corner 残留
        self._ready = False
        self._force_sync(prefer_tab=True)

    def ensure_plus_tab_mode(self):
        self._force_sync(prefer_tab=True)







