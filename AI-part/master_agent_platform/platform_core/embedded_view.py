"""Coordinate the owning Qt window with its native host, including DPI and minimums."""
import math
import json

from PyQt5.QtCore import QObject, QEvent, QTimer, QSize, QSaveFile, QIODevice
from PyQt5.QtGui import QWindow
from .ui_theme import MIN_UI_SCALE, MAX_UI_SCALE

PROTOCOL = 'donglanpec.embedded-module/1'


def host_minimum(metrics, host_dpr, fallback=(520, 360)):
    """Translate the child's logical minimum through physical pixels to host units."""
    try:
        child_dpr = float(metrics['dpr'])
        scale = float(host_dpr)
        width, height = metrics['minimum']
        if not all(math.isfinite(float(x)) for x in (child_dpr, scale, width, height)):
            raise ValueError('non-finite view dimensions')
        if not (.25 <= child_dpr <= 8 and .25 <= scale <= 8 and 0 < width < 20000 and 0 < height < 20000):
            raise ValueError('invalid view dimensions')
        return QSize(max(fallback[0], math.ceil(width*child_dpr/scale)),
                     max(fallback[1], math.ceil(height*child_dpr/scale)))
    except (KeyError, TypeError, ValueError, OverflowError): return QSize(*fallback)


class EmbeddedModuleView(QObject):
    """Keep the child process's Qt hierarchy aware of its actual native parent."""
    def __init__(self, window, tabs, notify):
        super().__init__(window)
        self.window, self.tabs, self.notify = window, tabs, notify
        self.native_parent = None
        self.previous = None
        self.effective_scale = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.report)
        window.installEventFilter(self)
        tabs.installEventFilter(self)

    def attach(self, handle):
        parent = QWindow.fromWinId(int(handle))
        if parent is None: raise RuntimeError('无法取得模块宿主窗口。')
        # Updating only the host's foreign wrapper leaves the owning process
        # treating this as a top-level window, with stale DPI and frame metrics.
        self.native_parent = parent
        handle = self.window.windowHandle()
        handle.setParent(parent)
        handle.screenChanged.connect(lambda screen: self.schedule())
        self.window.move(0, 0)
        self.schedule()

    def sync_viewport(self, value, apply_scale):
        try:
            width, height = value['size']
            host_dpr, user_scale = float(value['dpr']), float(value['scale'])
            if not (0 < width < 32768 and 0 < height < 32768 and .25 <= host_dpr <= 8
                    and MIN_UI_SCALE <= user_scale <= MAX_UI_SCALE):
                return False
        except (KeyError, TypeError, ValueError): return False
        ratio = host_dpr/self.window.devicePixelRatioF()
        effective = user_scale*ratio
        if self.effective_scale is None or abs(effective-self.effective_scale)>.001:
            apply_scale(effective)
            self.effective_scale = effective
        target = QSize(round(width*ratio), round(height*ratio))
        target = target.expandedTo(self.window.minimumSizeHint()).expandedTo(self.window.minimumSize())
        if self.window.size() != target: self.window.resize(target)
        self.schedule()
        return True

    def metrics(self):
        minimum = self.window.minimumSizeHint().expandedTo(self.window.minimumSize())
        handle = self.window.windowHandle()
        return dict(protocol=PROTOCOL, minimum=[minimum.width(), minimum.height()],
            size=[self.window.width(), self.window.height()],
            content_size=[self.tabs.width(), self.tabs.height()],
            dpr=self.window.devicePixelRatioF(), font_points=self.window.font().pointSizeF(),
            top_level=handle.isTopLevel() if handle else True)

    def schedule(self): self.timer.start(60)

    def report(self):
        value = self.metrics()
        if value != self.previous:
            self.previous = value
            self.notify(value)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Resize, QEvent.LayoutRequest, QEvent.FontChange, QEvent.Show):
            self.schedule()
        return False


class EmbeddedHostViewport(QObject):
    """Publish the host viewport without a second foreign-window geometry owner."""
    def __init__(self, container, path, get_scale, on_error):
        super().__init__(container)
        self.container, self.path = container, path
        self.get_scale, self.on_error = get_scale, on_error
        self.previous, self.error = None, None
        self.pending = QTimer(self)
        self.pending.setSingleShot(True)
        self.pending.timeout.connect(self.publish)
        self.heartbeat = QTimer(self)
        self.heartbeat.timeout.connect(self.publish)
        self.heartbeat.start(180)
        container.installEventFilter(self)

    def publish(self):
        value = dict(protocol=PROTOCOL, size=[self.container.width(), self.container.height()],
            dpr=self.container.devicePixelRatioF(), scale=self.get_scale())
        if value == self.previous or min(value['size']) <= 0: return
        try:
            data = json.dumps(value).encode('utf-8')
            target = QSaveFile(str(self.path))
            if not target.open(QIODevice.WriteOnly): raise OSError(target.errorString())
            if target.write(data) != len(data):
                error = target.errorString()
                target.cancelWriting()
                raise OSError(error)
            if not target.commit(): raise OSError(target.errorString())
        except OSError as exc:
            if str(exc) != self.error: self.on_error('模块显示尺寸同步暂未完成：'+str(exc))
            self.error = str(exc)
            return
        self.previous, self.error = value, None

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Resize, QEvent.Show): self.pending.start(0)
        return False
