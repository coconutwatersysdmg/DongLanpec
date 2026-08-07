#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
换热管外径 do 与名义孔桥宽度对照表。
布管（滑道/挡板等）通过 get_nominal_bridge_width 读取。
"""

# key: 换热管外径 do (mm)；value: 名义孔桥宽度 (mm)
NOMINAL_BRIDGE_WIDTH_MAP = {
    10: 3.82,
    12: 3.82,
    14: 4.75,
    16: 5.75,
    19: 5.75,
    20: 5.75,
    25: 6.75,
    30: 7.65,
    32: 7.60,
    35: 8.60,
    38: 9.55,
    45: 11.50,
    50: 13.45,
    55: 14.35,
    57: 14.35,
}


def get_nominal_bridge_width(d):
    """
    按换热管外径查名义孔桥宽度。
    未命中表时返回 0。
    """
    try:
        if d is None:
            return 0.0
        key = int(round(float(d)))
    except (TypeError, ValueError):
        return 0.0
    return float(NOMINAL_BRIDGE_WIDTH_MAP.get(key, 0))
