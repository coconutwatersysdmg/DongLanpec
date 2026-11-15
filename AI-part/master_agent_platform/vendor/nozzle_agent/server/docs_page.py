# -*- coding: utf-8 -*-
"""`/docs` 页面：从 `static/index.html` 读，读一次缓存住。

放成独立 html 而不是 Python 里的长字符串：那边要同时伺候 Python 的转义和
JS 的转义，改一个引号就炸；单独一个文件可以直接用浏览器打开看效果。
"""
from __future__ import annotations

from pathlib import Path

_PATH = Path(__file__).resolve().parent / "static" / "index.html"
_cache: str = ""
_mtime: float = -1.0


def page() -> str:
    """读取页面，按文件修改时间失效缓存。

    不用进程级永缓存：交付之后对方改文案是常事，改完还要重启服务很别扭。
    读一个 15KB 文件的开销远小于一次启动。
    """
    global _cache, _mtime
    stamp = _PATH.stat().st_mtime
    if _cache and stamp == _mtime:
        return _cache
    _cache = _PATH.read_text(encoding="utf-8")
    _mtime = stamp
    return _cache
