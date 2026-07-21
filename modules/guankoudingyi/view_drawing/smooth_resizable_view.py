

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt5.QtGui import QPainter, QPixmap
from PyQt5.QtWidgets import QSizePolicy, QSplitter, QWidget


class SmoothScaledCanvas(QWidget):
    """固定设计坐标、自动等比缩放并缓存业务绘图的画布基类。"""

    # 在「标注不被裁切」与「示意图够大」之间折中（过大则等比缩放被压小）
    DESIGN_WIDTH = 1700.0
    DESIGN_HEIGHT = 450.0
    DESIGN_PAD_TOP = 40.0
    VIEW_MARGIN = 2.0
    # 在完整装入的基础上略放大；多出的部分主要吃掉留白，示意图更满一些
    DISPLAY_ZOOM = 1.2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._view_scale = 1.0
        self._view_offset = QPointF(0.0, 0.0)
        self._render_cache = None

    def _calculate_view_transform(self):
        """计算设计坐标到当前控件坐标的等比缩放和居中偏移。"""
        available_width = max(1.0, self.width() - 2 * self.VIEW_MARGIN)
        available_height = max(1.0, self.height() - 2 * self.VIEW_MARGIN)
        scale = min(
            available_width / self.DESIGN_WIDTH,
            available_height / self.DESIGN_HEIGHT,
        ) * self.DISPLAY_ZOOM
        scaled_width = self.DESIGN_WIDTH * scale
        scaled_height = self.DESIGN_HEIGHT * scale
        offset = QPointF(
            (self.width() - scaled_width) / 2.0,
            (self.height() - scaled_height) / 2.0,
        )
        return max(scale, 0.001), offset

    def map_widget_to_design(self, point):
        """将控件坐标换算为业务设计坐标（不含上边距平移）。"""
        scale, offset = self._calculate_view_transform()
        return QPointF(
            (point.x() - offset.x()) / scale,
            (point.y() - offset.y()) / scale - self.DESIGN_PAD_TOP,
        )

    def map_design_to_widget(self, point):
        """将业务设计坐标换算为当前控件坐标。"""
        scale, offset = self._calculate_view_transform()
        return QPointF(
            offset.x() + point.x() * scale,
            offset.y() + (point.y() + self.DESIGN_PAD_TOP) * scale,
        )

    def invalidate_render_cache(self):
        """业务数据变化时使缓存失效；下一帧会自动重建。"""
        self._render_cache = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.white)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        self._view_scale, self._view_offset = self._calculate_view_transform()

        # 复杂业务绘图只在首次显示或数据变化时执行；拖动时仅缩放缓存。
        if self._render_cache is None:
            self._render_cache = QPixmap(int(self.DESIGN_WIDTH), int(self.DESIGN_HEIGHT))
            self._render_cache.fill(Qt.transparent)
            cache_painter = QPainter(self._render_cache)
            cache_painter.setRenderHint(QPainter.Antialiasing)
            # 业务按原坐标绘制，Y 向整体下移；宽度已加宽给右侧代号留白
            cache_painter.translate(0.0, self.DESIGN_PAD_TOP)
            self._draw_design_scene(cache_painter)
            cache_painter.end()

        target_rect = QRectF(
            self._view_offset.x(),
            self._view_offset.y(),
            self.DESIGN_WIDTH * self._view_scale,
            self.DESIGN_HEIGHT * self._view_scale,
        )
        painter.drawPixmap(target_rect, self._render_cache, QRectF(self._render_cache.rect()))

    def _draw_design_scene(self, painter):
        """子类只需实现原始设计坐标下的业务绘图。"""
        raise NotImplementedError


def install_pipe_definition_resizable_view(host):
    """一行安装管口定义页面的上下平滑伸缩布局，并返回分隔器。"""
    existing = getattr(host, "pipe_diagram_splitter", None)
    if isinstance(existing, QSplitter):
        return existing

    main_layout = host.layout()
    upper_widget = host.tabWidget
    lower_widget = host.widget_control
    if main_layout is None:
        raise RuntimeError("管口定义页面缺少最外层布局，无法安装伸缩功能")

    # 保留 Designer 中原控件及内部信号，只调整最外层承载关系。
    main_layout.removeWidget(upper_widget)
    main_layout.removeWidget(lower_widget)

    splitter = QSplitter(Qt.Vertical, host)
    splitter.setObjectName("pipeDiagramSplitter")
    splitter.setChildrenCollapsible(False)
    splitter.setOpaqueResize(True)
    splitter.setHandleWidth(8)
    splitter.setStyleSheet("""
        QSplitter#pipeDiagramSplitter::handle:vertical {
            background-color: #d9dde3;
            margin: 2px 0;
            border-radius: 2px;
        }
        QSplitter#pipeDiagramSplitter::handle:vertical:hover,
        QSplitter#pipeDiagramSplitter::handle:vertical:pressed {
            background-color: #8aa4c0;
        }
    """)

    upper_widget.setMinimumSize(0, 180)
    lower_widget.setMinimumSize(0, 100)
    upper_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    lower_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    splitter.addWidget(upper_widget)
    splitter.addWidget(lower_widget)
    splitter.setStretchFactor(0, 21)
    splitter.setStretchFactor(1, 19)
    splitter.handle(1).setToolTip("上下拖动可调整表格与示意图高度")

    main_layout.insertWidget(0, splitter, 1)
    main_layout.setStretch(0, 1)
    main_layout.setStretch(1, 0)
    host.pipe_diagram_splitter = splitter

    def set_initial_sizes():
        try:
            available_height = max(1, splitter.height() - splitter.handleWidth())
            upper_height = round(available_height * 21 / 40)
            splitter.setSizes([upper_height, available_height - upper_height])
        except RuntimeError:
            # 页面若在首次布局前已关闭，Qt 对象可能已销毁。
            pass

    QTimer.singleShot(0, set_initial_sizes)
    return splitter
