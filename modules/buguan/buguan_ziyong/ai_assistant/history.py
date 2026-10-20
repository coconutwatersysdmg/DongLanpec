# -*- coding: utf-8 -*-
"""面向助手一键操作的轻量撤销栈。"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class _UndoEntry:
    label: str
    restore: Callable[[], None]


class UndoHistory:
    def __init__(self, limit: int = 20):
        if limit <= 0:
            raise ValueError("撤销步数必须大于 0")
        self._entries = deque(maxlen=int(limit))

    @property
    def labels(self):
        return tuple(entry.label for entry in self._entries)

    @property
    def can_undo(self) -> bool:
        return bool(self._entries)

    def push(self, label: str, restore: Callable[[], None]):
        if not callable(restore):
            raise TypeError("restore 必须可调用")
        self._entries.append(_UndoEntry(str(label), restore))

    def undo(self) -> Optional[str]:
        if not self._entries:
            return None
        entry = self._entries.pop()
        entry.restore()
        return entry.label

    def clear(self):
        self._entries.clear()
