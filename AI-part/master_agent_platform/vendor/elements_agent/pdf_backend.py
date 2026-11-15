# -*- coding: utf-8 -*-
"""
统一加载 PyMuPDF（fitz）。

优先用当前解释器已安装的包；否则自动把本模块旁的 `_vendor` 加入 sys.path
（内置 cp38-abi3 win_amd64 的 pymupdf），避免「IDE 用了另一个 Python」装不上库。
"""

from __future__ import annotations

import os
import sys
from typing import Any, Tuple


_VENDOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vendor")
_FITZ = None
_LOAD_ERROR = ""


def _ensure_vendor_on_path() -> None:
    if os.path.isdir(_VENDOR_DIR) and _VENDOR_DIR not in sys.path:
        sys.path.insert(0, _VENDOR_DIR)


def get_fitz() -> Any:
    """返回 fitz 模块；失败抛 ImportError（带解释器路径提示）。"""
    global _FITZ, _LOAD_ERROR
    if _FITZ is not None:
        return _FITZ

    errors = []
    for attempt in ("installed", "vendor"):
        if attempt == "vendor":
            _ensure_vendor_on_path()
        try:
            import fitz  # type: ignore

            _FITZ = fitz
            _LOAD_ERROR = ""
            return _FITZ
        except Exception as e:
            errors.append(f"{attempt}: {e}")
        try:
            import pymupdf as fitz  # type: ignore

            _FITZ = fitz
            _LOAD_ERROR = ""
            return _FITZ
        except Exception as e:
            errors.append(f"{attempt}/pymupdf: {e}")

    _LOAD_ERROR = "；".join(errors)
    raise ImportError(
        f"无法加载 PyMuPDF（当前解释器: {sys.executable}）。{_LOAD_ERROR}"
    )


def fitz_available() -> Tuple[bool, str]:
    try:
        get_fitz()
        return True, sys.executable
    except Exception as e:
        return False, str(e)
