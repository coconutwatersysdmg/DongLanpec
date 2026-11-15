"""正式程序 modules/buguan/buguan_ziyong/json_process.py 的本地副本。

只去掉 `__main__` 演示代码，解析逻辑与正式程序保持一致。
"""
from __future__ import annotations

import json
from typing import Dict


def parse_heat_exchanger_json(json_str: str) -> Dict:
    """解析换热器布管 json 字符串，提取小圆（换热管）和大圆（壳体）信息。"""
    data = json.loads(json_str)
    centers = []
    small_r = 25
    for group in data.get("TubesParam", []):
        for tube in group.get("ScriptItem", []):
            pt = tube.get("CenterPt", {})
            x, y = pt.get("X"), pt.get("Y")
            if x is not None and y is not None:
                centers.append((x, y))

    dns = data.get("DNs", {}) or {}
    dls = data.get("DLs", {}) or {}
    big_r_wai = float(dns.get("R") or 0) / 2
    big_r_nei = float(dls.get("R") or 0) / 2

    dummy_tubes = []
    for item in data.get("DummyTubesParam", []) or []:
        pt = item.get("CenterPt", {})
        x, y = pt.get("X"), pt.get("Y")
        if x is not None and y is not None:
            dummy_tubes.append((x, y))

    tie_rods = []
    for item in data.get("TieRodsParam", []) or []:
        pt = item.get("CenterPt", {})
        x, y = pt.get("X"), pt.get("Y")
        if x is not None and y is not None:
            tie_rods.append((x, y))

    return {
        "small_r": small_r,
        "big_r_wai": big_r_wai,
        "big_r_nei": big_r_nei,
        "centers": centers,
        "dummy_tubes": dummy_tubes,
        "tie_rods": tie_rods,
        "raw": data,
    }
