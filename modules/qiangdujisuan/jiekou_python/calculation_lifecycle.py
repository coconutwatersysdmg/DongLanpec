"""保留正在收尾的计算线程，直到其退出并释放数据库配置锁。"""

from PyQt5.QtCore import QThread
from modules.qiangdujisuan.jiekou_python.calculation_process import CalculationControl


_active_threads = set()


def active_calculations(kind=None):
    return [thread for thread in tuple(_active_threads)
            if thread.isRunning() and (kind is None or thread.kind == kind)]


class CancellableCalculationThread(QThread):
    kind = "product"

    def __init__(self):
        # 不挂在页面下：页面关闭后，线程仍需短暂执行 finally 释放锁及连接。
        super().__init__()
        self.control = CalculationControl()
        self.finished.connect(self._release)

    def start(self, priority=QThread.InheritPriority):
        _active_threads.add(self)
        try:
            super().start(priority)
        except Exception:
            _active_threads.discard(self)
            raise

    def cancel(self):
        self.control.cancel()

    def _release(self):
        _active_threads.discard(self)
