"""GB/T 151 自动布置方案：规则计算层单测（不依赖 GUI / fitz）。"""
import sys
import types
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "ui_vendor" / "tube_agent" / "bundle"))

import rule_plan as rp  # noqa: E402


def P(**kw):
    return {k: {"value": str(v)} for k, v in kw.items()}


# ---- 表 7-41 拉杆直径 ----
@pytest.mark.parametrize("do,expected", [
    (10, 10), (12, 10), (14, 10),
    (19, 12), (25, 16), (45, 16), (57, 16),
])
def test_tie_rod_diameter_table_7_41(do, expected):
    params = P(**{"换热管外径 do": do, "拉杆形式": "螺纹拉杆"})
    dm, basis = rp.tie_rod_diameter_mm(params)
    assert dm == expected, basis


def test_welded_tie_rod_uses_tube_od():
    params = P(**{"换热管外径 do": 19, "拉杆形式": "焊接拉杆"})
    dm, _ = rp.tie_rod_diameter_mm(params)
    assert dm == 19


# ---- 表 7-42 拉杆数量 ----
@pytest.mark.parametrize("dn,dm,expected", [
    (900, 16, 6), (900, 12, 10), (900, 10, 12),
    (1500, 16, 10), (2600, 16, 20), (4500, 16, 56), (5500, 16, 74),
])
def test_tie_rod_count_table_7_42(dn, dm, expected):
    count, basis = rp.tie_rod_required_count(dn, dm)
    assert count == expected, basis


def test_tie_rod_count_exceeds_standard_and_diagonal():
    """用户约定：拉杆数量超过标准，四象限 y=±x 对角线附近均匀布置。"""
    params = P(**{
        "换热管外径 do": 25, "公称直径 DN": 900, "拉杆形式": "螺纹拉杆",
        "换热管中心距 S": 32, "折流/支持板间距": 200, "目标换热管数": 1700,
    })
    plan = rp.build_plan(params, "BEM", 1800, 1700)
    rod = next(p for p in plan["placements"] if p["kind"] == "rod")
    assert rod["count"] > plan["summary"]["rod_std_count"]  # 严格超过标准数量
    assert rod["count"] >= 8  # 四象限每象限至少 2 根
    assert rod["region"] == "diagonal"  # y=x / y=-x 对角线附近


# ---- 删管总账 ----
def test_delete_count_reconciles_target():
    params = P(**{
        "换热管外径 do": 25, "公称直径 DN": 900, "拉杆形式": "螺纹拉杆",
        "换热管中心距 S": 32, "折流/支持板间距": 200, "目标换热管数": 1700,
        "折流板厚度": 6,
    })
    plan = rp.build_plan(params, "BEM", 1800, 1700)
    s = plan["summary"]
    assert s["delete_est"] == s["total_holes"] - s["occupying"] - 1700
    # 总账文字必须出现目标数
    assert any("1700" in b for b in plan["basis"])


def test_no_delete_when_target_matches():
    params = P(**{
        "换热管外径 do": 25, "公称直径 DN": 900, "拉杆形式": "螺纹拉杆",
        "换热管中心距 S": 32, "折流/支持板间距": 200,
    })
    plan = rp.build_plan(params, "BEM", 100, 100)
    assert plan["hole_ops"] == []  # 不需要删管


def test_short_target_is_flagged():
    params = P(**{
        "换热管外径 do": 25, "公称直径 DN": 900, "拉杆形式": "螺纹拉杆",
        "换热管中心距 S": 32, "折流/支持板间距": 200,
    })
    plan = rp.build_plan(params, "BEM", 100, 200)  # 目标比满布还多
    assert plan["hole_ops"] == []
    assert any("不足" in b for b in plan["basis"])


# ---- 旁路挡板数量 ----
def test_bypass_pair_count():
    n, basis = rp.bypass_pair_count(200, 32)  # 6.25 个管心距，>6
    assert n >= 1
    n2, _ = rp.bypass_pair_count(150, 32)  # 4.7 <6
    assert n2 == 1


# ---- 提取映射 tube_count ----
def test_tube_count_maps_to_hidden_param():
    sys.modules.setdefault("fitz", types.ModuleType("fitz"))
    sys.path.insert(0, str(BASE / "vendor" / "tube_agent"))
    from bundle import structure_extract as se
    ids = {s[0] for s in se.FIELD_MAPPINGS}
    fields = [{
        "id": i, "name": i,
        "value": ("1700" if i == "tube_count" else None),
        "unit": "根", "status": "found", "page": 24,
        "bbox": None, "snippet": "", "evidence": {},
        "selected_options": [],
    } for i in ids]
    mapped, rows = se._map_parameters(fields, 24)
    assert mapped.get("目标换热管数", {}).get("value") == "1700"
