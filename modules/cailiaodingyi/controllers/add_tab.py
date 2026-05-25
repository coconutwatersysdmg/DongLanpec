from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt, QEvent, QObject, QTimer
from PyQt5.QtWidgets import QWidget, QToolButton, QTabWidget, QAbstractButton, QTabBar


_TAB_BAR_LEFT_ALIGN_QSS = "QTabWidget::tab-bar { alignment: left; }"

_TO_CORNER_OVERFLOW = 12   # 统一阈值：need > avail + 此值 → corner
_MIN_BAR_WIDTH = 48
_UPDATE_DEBOUNCE_MS = 80


class PlusTabManager(QObject):
    """
    '+' 管理：
      - 空间够：作为最后一个页签
      - 空间不够：右上角 corner 按钮
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
        self._switching = False
        self._orig_tabbar_stylesheet = tw.tabBar().styleSheet()

        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(_UPDATE_DEBOUNCE_MS)
        self._update_timer.timeout.connect(self._update_mode_impl)

        self._configure_tab_bar()

        bar = self.tw.tabBar()
        try:
            bar.tabBarClicked.disconnect(self._on_tabbar_clicked)
        except Exception:
            pass
        self._remove_all_plus_tabs()

        self._plus_tab_index = self.tw.addTab(QWidget(), "+")
        bar.tabBarClicked.connect(self._on_tabbar_clicked)

        self._btn = QToolButton(self.tw)
        self._btn.setText("+")
        self._btn.setAutoRaise(True)
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.clicked.connect(self._on_corner_plus_clicked)
        self.tw.setCornerWidget(self._btn, Qt.TopRightCorner)
        self._btn.hide()

        self.tw.installEventFilter(self)
        bar.installEventFilter(self)

        for t in (0, 50, 150, 300):
            QTimer.singleShot(t, lambda: self._force_sync(prefer_tab=True))

    def _configure_tab_bar(self):
        tw = self.tw
        bar = tw.tabBar()
        bar.setExpanding(False)
        bar.setElideMode(Qt.ElideNone)
        if self._plus_as_tab:
            bar.setUsesScrollButtons(False)

        ss = tw.styleSheet() or ""
        if _TAB_BAR_LEFT_ALIGN_QSS.strip() not in ss:
            tw.setStyleSheet((ss + "\n" + _TAB_BAR_LEFT_ALIGN_QSS).strip())

    def _layout_ready(self, bar) -> bool:
        if not (self.tw.isVisible() and bar.isVisible()):
            return False
        return max(bar.width(), self.tw.width(), 0) >= _MIN_BAR_WIDTH

    def _corner_reserve_width(self) -> int:
        if not self._reserved_margin:
            return 0
        return max(self._btn.width(), self._plus_tab_width()) + 6

    def _remove_all_plus_tabs(self):
        for i in range(self.tw.count() - 1, -1, -1):
            if self.tw.tabText(i).strip() in {"+", "＋"}:
                self.tw.removeTab(i)

    def _ensure_single_plus(self):
        if self._plus_as_tab:
            try:
                self.tw.setCornerWidget(None, Qt.TopRightCorner)
            except Exception:
                pass
            self._btn.hide()
            self.tw.tabBar().setUsesScrollButtons(False)
            has_plus = any(self.tw.tabText(i).strip() in {"+", "＋"} for i in range(self.tw.count()))
            if not has_plus:
                self._plus_tab_index = self.tw.addTab(QWidget(), "+")
        else:
            self._remove_all_plus_tabs()
            try:
                self.tw.setCornerWidget(self._btn, Qt.TopRightCorner)
            except Exception:
                pass
            self._btn.show()
            self._btn.raise_()
            self.tw.tabBar().setUsesScrollButtons(True)

    def _plus_tab_width(self):
        fm = self.tw.tabBar().fontMetrics()
        return fm.horizontalAdvance("+") + 28

    def _text_tab_width(self, bar, index: int) -> int:
        text = (self.tw.tabText(index) or "").strip()
        if text in {"+", "＋"}:
            return 0
        fm = bar.fontMetrics()
        w = fm.horizontalAdvance(text) + 28
        for side in (QTabBar.LeftSide, QTabBar.RightSide):
            btn = bar.tabButton(index, side)
            if btn and btn.isVisible():
                w += btn.width()
        return w

    def _need_width_for_plus_tab(self, bar) -> int:
        total = 0
        for i in range(bar.count()):
            t = self.tw.tabText(i).strip()
            if t in {"+", "＋"}:
                continue
            total += self._text_tab_width(bar, i)
        if total <= 0:
            return self._plus_tab_width()
        return total + self._plus_tab_width() + 12

    def _avail_for_decision(self, bar) -> int:
        """
        判断可用宽度。
        不扣滚动条：滚动条是 corner 形态的结果，扣掉会导致删 tab 后仍误判放不下。
        corner 时已预留的 margin-right 要扣除。
        """
        w = max(bar.width(), self.tw.width(), _MIN_BAR_WIDTH)
        w -= self._corner_reserve_width()
        return max(_MIN_BAR_WIDTH, w)

    def _last_real_tab_index(self, bar) -> int:
        last = -1
        for i in range(bar.count()):
            if self.tw.tabText(i).strip() not in {"+", "＋"}:
                last = i
        return last

    def _geom_fits_plus_tab(self, bar) -> bool:
        """按末 tab 实际右边界判断：能否在后方再接 '+' 页签。"""
        last = self._last_real_tab_index(bar)
        if last < 0:
            return True
        rect = bar.tabRect(last)
        if not rect.isValid() or rect.width() <= 0:
            return False
        avail = self._avail_for_decision(bar)
        return rect.right() + self._plus_tab_width() + 8 <= avail

    def _want_corner_mode(self, bar) -> bool:
        if not self._layout_ready(bar):
            return False

        # 几何上能放下 → 一定回到/保持页签形态（解决 7→6 删 tab 后仍卡 corner）
        if self._geom_fits_plus_tab(bar):
            return False

        avail = self._avail_for_decision(bar)
        need = self._need_width_for_plus_tab(bar)
        return need > avail + _TO_CORNER_OVERFLOW

    def _reserve_corner_space(self, enable: bool):
        bar = self.tw.tabBar()
        if enable and not self._reserved_margin:
            pad = self._corner_reserve_width() or (self._plus_tab_width() + 6)
            bar.setStyleSheet(self._orig_tabbar_stylesheet + f" QTabBar{{margin-right:{pad}px;}}")
            self._reserved_margin = True
        elif not enable and self._reserved_margin:
            bar.setStyleSheet(self._orig_tabbar_stylesheet)
            self._reserved_margin = False

    def eventFilter(self, obj, ev):
        if self._switching:
            return False
        if ev.type() in (QEvent.Show, QEvent.ShowToParent, QEvent.Resize, QEvent.LayoutRequest, QEvent.Polish):
            self.update_mode()
        return False

    def update_mode(self):
        self._update_timer.start()

    def _force_sync(self, prefer_tab: bool = False):
        bar = self.tw.tabBar()
        if not self.tw.isVisible():
            return

        if prefer_tab:
            self._plus_as_tab = True
            self._reserve_corner_space(False)
            self._btn.hide()
            self._ensure_single_plus()

        if not self._layout_ready(bar):
            return

        self._ready = True
        self._update_mode_impl()

    def _apply_mode(self, want_corner: bool):
        if want_corner == (not self._plus_as_tab):
            return

        self._switching = True
        try:
            if want_corner:
                self._plus_as_tab = False
                self._reserve_corner_space(True)
                self._ensure_single_plus()
            else:
                self._plus_as_tab = True
                self._reserve_corner_space(False)
                self._ensure_single_plus()
        finally:
            self._switching = False

        if not self._plus_as_tab:
            bar = self.tw.tabBar()
            self._btn.setFixedHeight(bar.sizeHint().height())
            self._btn.raise_()

    def _update_mode_impl(self):
        if self._switching or self._adding:
            return

        bar = self.tw.tabBar()
        if not self._layout_ready(bar):
            return

        if not self._ready:
            self._ready = True

        self._apply_mode(self._want_corner_mode(bar))

    def _on_tabbar_clicked(self, index: int):
        if not self._plus_as_tab:
            return
        if index < 0 or self.tw.tabText(index).strip() not in {"+", "＋"}:
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
            if self._plus_as_tab and tw.tabText(cur).strip() in {"+", "＋"}:
                cur = max(0, tw.count() - 2)
            src_idx = cur
            src_name = tw.tabText(src_idx)

            self.on_add_from_src(src_idx, src_name)

            if self._plus_as_tab:
                self._remove_all_plus_tabs()
                self._plus_tab_index = tw.addTab(QWidget(), "+")
        finally:
            self._adding = False
            QTimer.singleShot(0, self.update_mode)

    def refresh_after_model_change(self):
        self._ready = False
        self._configure_tab_bar()
        n_real = sum(
            1 for i in range(self.tw.count())
            if self.tw.tabText(i).strip() not in {"+", "＋"}
        )
        self._force_sync(prefer_tab=(n_real <= 2))
        # 删 tab 后布局需一帧稳定（尤其从 corner 回到页签形态）
        QTimer.singleShot(100, self.update_mode)

    def ensure_plus_tab_mode(self):
        self.update_mode()
