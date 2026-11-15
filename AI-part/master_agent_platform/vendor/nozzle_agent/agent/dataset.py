# -*- coding: utf-8 -*-
"""
权威取值数据源。

取值来自正式项目 `元件库`（只读导出），保证 Demo 下拉里的每一个值、每一条
联动规则都和线上一致：
    - 公称压力类型标准对应表  → 压力类型 → 法兰标准
    - 管口压力等级表          → 法兰标准 + 压力类型 → 压力等级
    - 管口关系对应表(795 行)  → 法兰标准 + 压力等级 + 法兰型式 + 密封面型式 的合法组合
    - 公称尺寸表              → DN / NPS / OD
    - 焊端规格类型表          → Sch 取值
    - 管口默认表              → 管口功能等

刷新：python tools/export_ref.py
"""

import json
import os
from typing import Dict, List, Optional

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data", "pipe_ref.json")

_FALLBACK = {
    "pressure_types": ["Class", "PN"],
    "standards": {
        "Class": ["HG/T 20615-2009", "HG/T 20623-2009(A)", "HG/T 20623-2009(B)",
                  "SH/T 3406-2022", "SH/T 3406-2022(A)", "SH/T 3406-2022(B)"],
        "PN": ["HG/T 20592(A)-2009", "HG/T 20592(B)-2009"],
    },
    "pressure_levels": {},
    "relations": [],
    "flange_types": ["SO", "WN", "LWN", "IF", "SW", "Th", "LF/SE", "BL", "PL",
                     "PJ/SE", "PJ/RJ", "BL(S)", "LJ", "PT"],
    "sealing_faces": ["RF", "FM", "M", "T", "G", "FF", "RJ", "MF", "TG"],
    "dn": ["10", "15", "20", "25", "32", "40", "50", "65", "80", "100", "125",
           "150", "200", "250", "300", "350", "400", "450", "500", "600"],
    "nps": [], "dn_nps": {}, "nps_dn": {}, "od": {},
    "sch": ["5S", "10s", "40s", "80s", "10", "20", "30", "40", "60", "80",
            "100", "120", "140", "160", "STD", "XS", "XXS"],
    "functions": ["管程入口", "管程出口", "壳程入口", "壳程出口", "排液口", "排气口"],
    "elements": [], "position_bases": [],
    "defaults": {"pressure_type": "Class",
                 "Class": {"法兰标准": "HG/T 20615-2009", "压力等级": "150"},
                 "PN": {"法兰标准": "HG/T 20592(A)-2009", "压力等级": "10"},
                 "焊端规格": "程序推荐"},
    "meta": {},
}


class RefData:
    """管口字段的权威取值集合。单例使用，见模块底部 ref()。"""

    def __init__(self, path: Optional[str] = None):
        self.path = path or _DATA
        self.raw: Dict = {}
        self.meta: Dict = {}
        self._load()

    # ------------------------------------------------------------ 载入
    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.raw = json.load(f)
            except Exception:
                self.raw = {}
        if not self.raw:
            self.raw = dict(_FALLBACK)
            self.raw["meta"] = {"source": "内置兜底（未找到 data/pipe_ref.json）"}
        self.meta = self.raw.get("meta") or {}

        self.pressure_types: List[str] = self.raw.get("pressure_types") or ["Class", "PN"]
        self._standards: Dict[str, List[str]] = self.raw.get("standards") or {}
        self._levels: Dict[str, List[str]] = self.raw.get("pressure_levels") or {}
        self._relations: List[List[str]] = self.raw.get("relations") or []
        self._rel_set = {tuple(r) for r in self._relations}

        self.dn_list: List[str] = [str(x) for x in (self.raw.get("dn") or [])]
        self.nps_list: List[str] = [str(x) for x in (self.raw.get("nps") or [])]
        self.dn_nps: Dict[str, str] = self.raw.get("dn_nps") or {}
        self.nps_dn: Dict[str, str] = self.raw.get("nps_dn") or {}
        self.od: Dict[str, str] = self.raw.get("od") or {}
        self.sch_list: List[str] = [str(x) for x in (self.raw.get("sch") or [])]
        self.functions: List[str] = self.raw.get("functions") or _FALLBACK["functions"]
        self.elements: List[str] = self.raw.get("elements") or []
        self.position_bases: List[str] = self.raw.get("position_bases") or []
        self.defaults: Dict = self.raw.get("defaults") or _FALLBACK["defaults"]

        # 全量取值（关系表里出现过的，顺序即项目下拉顺序）
        self.flange_type_all: List[str] = self.raw.get("flange_types") or _FALLBACK["flange_types"]
        self.sealing_face_all: List[str] = self.raw.get("sealing_faces") or _FALLBACK["sealing_faces"]

    # ------------------------------------------------------------ 查询
    def standards(self, pressure_type: str = "") -> List[str]:
        if pressure_type:
            return list(self._standards.get(pressure_type, []))
        out = []
        for pt in self.pressure_types:
            out.extend(self._standards.get(pt, []))
        return out

    def levels(self, standard: str = "", pressure_type: str = "") -> List[str]:
        """指定标准下的压力等级（值形如 '150' / '16'）。"""
        if standard:
            key = f"{standard}|{pressure_type}" if pressure_type else ""
            if key and key in self._levels:
                return list(self._levels[key])
            # 标准名对不上时，退回该压力类型的全部等级
            if pressure_type:
                merged = []
                for k, v in self._levels.items():
                    if k.endswith("|" + pressure_type):
                        for x in v:
                            if x not in merged:
                                merged.append(x)
                return merged
        if pressure_type:
            merged = []
            for k, v in self._levels.items():
                if k.endswith("|" + pressure_type):
                    for x in v:
                        if x not in merged:
                            merged.append(x)
            return merged
        return []

    def _related(self, pressure_type="", standard="", pressure="") -> List[List[str]]:
        out = []
        for r in self._relations:
            if len(r) < 5:
                continue
            if pressure_type and r[4] != pressure_type:
                continue
            if standard and r[0] != standard:
                continue
            if pressure and str(r[1]) != str(pressure):
                continue
            out.append(r)
        return out

    def flange_types(self, pressure_type="", standard="", pressure="") -> List[str]:
        rows = self._related(pressure_type, standard, pressure)
        if not rows:
            return list(self.flange_type_all)
        out = []
        for r in rows:
            if r[2] not in out:
                out.append(r[2])
        return out

    def sealing_faces(self, pressure_type="", standard="", pressure="", flange_type="") -> List[str]:
        rows = self._related(pressure_type, standard, pressure)
        if flange_type:
            rows = [r for r in rows if r[2] == flange_type] or rows
        if not rows:
            return list(self.sealing_face_all)
        out = []
        for r in rows:
            if r[3] not in out:
                out.append(r[3])
        return out

    def combo_exists(self, standard, pressure, flange_type, face, pressure_type) -> bool:
        """完全对齐 管口关系对应表：这个组合在项目里能不能选得出来。"""
        if not self._relations:
            return True
        return (str(standard), str(pressure), str(flange_type), str(face),
                str(pressure_type)) in self._rel_set

    def combo_hints(self, standard, pressure, flange_type, face, pressure_type) -> Dict[str, List[str]]:
        """组合不成立时，给出「保持其它三项、只换该项」的可行值。"""
        def _fix(idx, kwargs):
            base = dict(pressure_type=pressure_type, standard=standard,
                        pressure=pressure, flange_type=flange_type)
            base.update(kwargs)
            rows = self._related(base.get("pressure_type", ""), base.get("standard", ""),
                                 base.get("pressure", ""))
            if idx == 2:
                return [r[2] for r in rows if r[3] == face] or []
            if idx == 3:
                return [r[3] for r in rows if r[2] == flange_type] or []
            if idx == 1:
                return [r[1] for r in rows if r[2] == flange_type and r[3] == face] or []
            return []

        return {
            "法兰型式": _fix(2, {"face": face}),
            "密封面型式": _fix(3, {}),
            "压力等级": _fix(1, {"flange_type": flange_type}),
        }

    # ------------------------------------------------------------ 公称尺寸
    def sizes(self, unit: str = "DN") -> List[str]:
        return list(self.nps_list if str(unit).upper() == "NPS" else self.dn_list)

    def dn_numbers(self) -> List[float]:
        out = []
        for x in self.dn_list:
            try:
                out.append(float(x))
            except ValueError:
                continue
        return out

    def nearest_dn(self, value: float) -> Optional[str]:
        nums = self.dn_numbers()
        if not nums:
            return None
        best = min(nums, key=lambda x: abs(x - value))
        return ("%g" % best)

    def neighbors(self, value: float) -> List[str]:
        nums = self.dn_numbers()
        if not nums:
            return []
        try:
            idx = nums.index(float(value))
        except ValueError:
            return [self.nearest_dn(value)] if self.nearest_dn(value) else []
        out = []
        if idx > 0:
            out.append("%g" % nums[idx - 1])
        if idx < len(nums) - 1:
            out.append("%g" % nums[idx + 1])
        return out

    # ------------------------------------------------------------ 说明
    def source_text(self) -> str:
        src = self.meta.get("source") or "内置兜底"
        when = self.meta.get("exported_at") or ""
        n = self.meta.get("relations") or len(self._relations)
        return f"{src}｜{n} 条组合" + (f"｜{when} 导出" if when else "")

    def summary(self) -> Dict[str, int]:
        return {
            "法兰标准": sum(len(v) for v in self._standards.values()),
            "压力等级": sum(len(v) for v in self._levels.values()),
            "法兰型式": len(self.flange_type_all),
            "密封面": len(self.sealing_face_all),
            "公称尺寸": len(self.dn_list),
            "焊端规格": len(self.sch_list),
            "组合": len(self._relations),
        }


_REF: Optional[RefData] = None


def ref(path: Optional[str] = None) -> RefData:
    global _REF
    if _REF is None or path:
        _REF = RefData(path)
    return _REF
