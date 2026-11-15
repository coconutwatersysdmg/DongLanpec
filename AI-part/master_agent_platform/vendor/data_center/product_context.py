"""Read the host's local product-selection protocol; never import the host app."""
import json
import math
import os
from pathlib import Path
import time

from PyQt5.QtCore import QObject, QTimer, pyqtSignal


def context_path():
    override = os.environ.get('DONGLANPEC_PRODUCT_CONTEXT')
    if override:
        return Path(override).expanduser().resolve()
    return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local') / 'DongLanpec/context/active_product.json'


def read_context(path=None, *, clock=time.time):
    path = Path(path) if path else context_path()
    try:
        with path.open('rb') as stream:
            raw = stream.read(16385)
        if len(raw) > 16384:
            raise ValueError('context too large')
        data = json.loads(raw.decode('utf-8'))
        if not isinstance(data, dict) or data.get('schema') != 'donglanpec.product-context/1' or data.get('source') != 'DongLanpec':
            raise ValueError('unknown protocol')
        stamp = data.get('updated')
        if type(stamp) not in (int, float) or not math.isfinite(stamp) or not -2 <= clock() - stamp <= 5:
            return None, '主系统通知已过期'
        if data.get('active') is not True:
            return None, '主系统已退出'
        if not isinstance(data.get('session'), str) or not data['session']:
            raise ValueError('missing session')
        for key in ('project_id', 'product_id', 'product_name'):
            if not isinstance(data.get(key, ''), str) or len(data.get(key, '')) > 512:
                raise ValueError('invalid selection')
        return data, '已连接主系统'
    except FileNotFoundError:
        return None, '等待主系统产品通知'
    except (OSError, ValueError, TypeError):
        return None, '主系统通知暂不可读'


class ProductContextMonitor(QObject):
    changed = pyqtSignal(object, str)

    def __init__(self, parent=None, path=None):
        super().__init__(parent)
        self.path, self.last = path, None
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.poll)

    def start(self):
        self.timer.start()
        QTimer.singleShot(0, self.poll)

    def poll(self):
        data, status = read_context(self.path)
        key = (data.get('session'), data.get('project_id'), data.get('product_id'), data.get('product_name')) if data else None
        key = key, status
        if key != self.last:
            self.last = key
            self.changed.emit(data, status)
