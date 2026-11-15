# -*- coding: utf-8 -*-
"""
管壳式换热器数据表「结构材料」行名 → 产品活动库元件名。

键统一成「去空格 + 短横/长横归一」后查找；值为产品侧元件名列表（一对多拆写）。
空列表 = 本期跳过。
"""

from __future__ import annotations

from typing import Dict, List, Tuple


# 原始映射（数据表常见写法）
_RAW_MAP: Dict[str, List[str]] = {
    # 壳程 / 管程筒体封头
    # 壳体圆筒：常规；BKU 等型式活动库常拆成大/小端圆筒
    "壳程-壳体": ["壳体圆筒", "壳体大端圆筒", "壳体小端圆筒"],
    "壳程—壳体": ["壳体圆筒", "壳体大端圆筒", "壳体小端圆筒"],
    "壳程壳体": ["壳体圆筒", "壳体大端圆筒", "壳体小端圆筒"],
    "壳程-封头": ["壳体封头"],
    "壳程—封头": ["壳体封头"],
    "管程-壳体": ["管箱圆筒"],
    "管程—壳体": ["管箱圆筒"],
    "管程壳体": ["管箱圆筒"],
    "管程-封头": ["管箱封头"],
    "管程—封头": ["管箱封头"],
    # 壳体法兰（管箱侧：活动库常见「壳体法兰」或「管箱侧法兰」）
    "壳体法兰-管箱侧": ["壳体法兰", "管箱侧法兰"],
    "壳体法兰—管箱侧": ["壳体法兰", "管箱侧法兰"],
    "壳体法兰-外头盖侧": ["外头盖侧法兰"],
    "壳体法兰—外头盖侧": ["外头盖侧法兰"],
    # 管箱法兰
    "管箱法兰-壳程侧": ["管箱法兰"],
    "管箱法兰—壳程侧": ["管箱法兰"],
    "管箱法兰-封头侧": ["外头盖侧法兰"],
    "管箱法兰—封头侧": ["外头盖侧法兰"],
    "管箱法兰-管箱法兰盖": ["管箱平盖"],
    "管箱法兰—管箱法兰盖": ["管箱平盖"],
    "管箱法兰盖": ["管箱平盖"],
    # 外头盖
    "外头盖-壳体": ["外头盖圆筒"],
    "外头盖—壳体": ["外头盖圆筒"],
    "外头盖-封头": ["外头盖封头"],
    "外头盖—封头": ["外头盖封头"],
    "外头盖-法兰": ["外头盖法兰"],
    "外头盖—法兰": ["外头盖法兰"],
    # 管板 / 管束
    "固定管板": ["固定管板"],
    "浮头管板": ["浮动管板"],
    "换热管": ["换热管", "U形换热管"],
    "膨胀节": ["膨胀节"],
    "浮头法兰": ["浮头法兰"],
    "钩圈": ["钩圈"],
    "浮头盖封头": ["球冠形封头"],
    "浮头盖浮头": ["球冠形封头"],
    # 紧固件 → 设备法兰紧固件（产品侧常为父级/合并名）
    "螺栓/螺柱-壳体": ["设备法兰紧固件"],
    "螺栓/螺柱—壳体": ["设备法兰紧固件"],
    "螺栓/螺柱-浮头": ["设备法兰紧固件"],
    "螺栓/螺柱—浮头": ["设备法兰紧固件"],
    "螺母-壳体": ["设备法兰紧固件"],
    "螺母—壳体": ["设备法兰紧固件"],
    "螺母-浮头": ["设备法兰紧固件"],
    "螺母—浮头": ["设备法兰紧固件"],
    # 管口类
    "接管-壳程": ["管口"],
    "接管—壳程": ["管口"],
    "接管-管程": ["管口"],
    "接管—管程": ["管口"],
    "接管法兰-壳程": ["管口"],
    "接管法兰—壳程": ["管口"],
    "接管法兰-管程": ["管口"],
    "接管法兰—管程": ["管口"],
    "补强圈-壳程": ["管口"],
    "补强圈—壳程": ["管口"],
    "补强圈-管程": ["管口"],
    "补强圈—管程": ["管口"],
    # 垫片（一对多）
    "垫片-壳程侧/外头盖": ["管箱侧垫片", "外头盖垫片"],
    "垫片—壳程侧/外头盖": ["管箱侧垫片", "外头盖垫片"],
    "垫片-管程侧/管箱头盖": ["管箱垫片", "外头盖垫片"],
    "垫片—管程侧/管箱头盖": ["管箱垫片", "外头盖垫片"],
    "垫片-浮头": [],  # 本期跳过
    "垫片—浮头": [],
    # 管束附件
    "折流板/支持板": ["折流板"],
    "旁路挡板": ["旁路挡板"],
    "定距管": ["定距管"],
    "拉杆/螺母": ["拉杆"],
    "滑板": ["滑道"],
    "堰板": ["堰板"],
    "支座/支座垫板": [],  # 本期跳过
}


def normalize_dds_key(name: str) -> str:
    """数据表行名归一：空白去掉，长横统一为短横，去前导破折号。"""
    s = (name or "").strip()
    s = s.replace("—", "-").replace("–", "-").replace("－－", "-")
    s = s.replace(" ", "").replace("\u3000", "")
    # 「——封头」类续行：去掉多余前导 -
    while s.startswith("-"):
        s = s[1:]
    return s


# 归一后查找表
DDS_ALIAS_MAP: Dict[str, List[str]] = {}
for _k, _v in _RAW_MAP.items():
    DDS_ALIAS_MAP[normalize_dds_key(_k)] = list(_v)


# 续行补全：页上写成「——封头」时，需结合上一主行前缀
_CONTINUATION_PREFIX: Dict[str, str] = {
    "封头": "",  # 需上下文：壳程/管程/外头盖
}


def resolve_dds_targets(raw_label: str) -> Tuple[List[str], bool]:
    """
    返回 (产品元件名列表, skipped)。
    skipped=True 表示映射表明确跳过；空且 skipped=False 表示未登记。
    """
    key = normalize_dds_key(raw_label)
    if not key:
        return [], False
    if key in DDS_ALIAS_MAP:
        targets = DDS_ALIAS_MAP[key]
        if not targets:
            return [], True
        return list(targets), False
    # 兼容「壳体法兰管箱侧」无短横
    for k, v in DDS_ALIAS_MAP.items():
        if k.replace("-", "") == key.replace("-", ""):
            if not v:
                return [], True
            return list(v), False
    return [], False


def expand_continuation(prev_main: str, cont_label: str) -> str:
    """
    将「——封头」「——外头盖侧」等续行拼成完整键。
    prev_main 例：壳体法兰、管程、外头盖、垫片。
    """
    main = normalize_dds_key(prev_main)
    cont = normalize_dds_key(cont_label)
    if not cont:
        return main
    if not main:
        return cont
    # 续行本身已是完整键
    if resolve_dds_targets(cont)[0] or resolve_dds_targets(cont)[1]:
        # 若 cont 单独能命中且含主前缀感，仍优先拼接更稳
        pass
    # 主行取首段（到第一段功能名）
    # 壳程 / 管程 / 外头盖 / 壳体法兰 / 管箱法兰 / 垫片 / 螺栓/螺柱 / 螺母 / 接管 / 接管法兰 / 补强圈
    return f"{main}-{cont}" if cont not in main else main


def all_dds_labels() -> List[str]:
    """供 LLM prompt 使用的中文标签列表（去重）。"""
    seen = set()
    out: List[str] = []
    for k in _RAW_MAP:
        nk = normalize_dds_key(k)
        if nk and nk not in seen:
            seen.add(nk)
            out.append(nk)
    return out
