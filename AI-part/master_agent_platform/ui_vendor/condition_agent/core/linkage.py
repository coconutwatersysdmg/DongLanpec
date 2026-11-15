# -*- coding: utf-8 -*-
"""跨表联动 —— 能从主项目 import 的原版逻辑一律直接 import，不自己重写。

复用清单（出处 modules/condition_input/funcs/funcs_cdt_input.py）：
  · update_trail_table_side_only          焊接接头系数 → 检测数据三段。
        agent 检测数据表的列布局刻意与原版一致（2..4=壳程 等级/比例/合格，
        5..7=管程；首个数据行 = A，B·R.T. 行），原版函数可直接吃这张表。
        调用前必须给表设 trail_header_rows=0（原版靠它定位首个数据行，
        agent 表没有嵌入表头行）。
  · compute_trail_default_grade           检测比例 → 技术等级/合格级别（纯函数）。
  · _determine_diameter_series / _get_outer_diameter_from_mapping /
    _get_outer_diameter_formula / _calculate_outer_diameter_by_formula
                                          外径自动填充的配置库取数四件套
                                          （user_config 2.2.11.x，自带 DB 连接）。
import 失败（脱离主项目跑纯逻辑测试）时用本地同款映射兜底，接口不变；
绝热类型联动在原版是内嵌在 cellChanged 大 handler 里的，没有独立函数可调，
由 confirm_dialog 按同样规则实现（清空/恢复 绝热材料·厚度·密度）。
"""
import os
import re
import sys

# 主项目根目录（condition_agent/ 的上一级）。agent 的启动脚本只把
# condition_agent/ 加进 sys.path，不带这行的话 modules.* 找不到，
# 会一直走无配置库的兜底映射（2026-11-10 linkage_test 实测踩到）。
_PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

# 原版 update_trail_table_side_only 里的 factor_map（仅 import 失败时兜底）
_WELD_FACTOR_MAP = {
    "1": ("AB", "100", "Ⅱ"),
    "1.0": ("AB", "100", "Ⅱ"),
    "0.9": ("AB", "100", "Ⅱ"),
    "0.85": ("AB", "≥20", "Ⅲ"),
    "0.8": ("AB", "≥20", "Ⅲ"),
}

# 原版 TRAIL_RATIO_GRADE_TABLE（仅 import 失败时兜底）
_RATIO_GRADE_TABLE = {
    "R.T.": [("100", "AB", "Ⅱ"), ("1", "AB", "Ⅲ")],
    "D.R.": [("100", "AB", "Ⅱ"), ("1", "AB", "Ⅲ")],
    "C.R.": [("100", "AB", "Ⅱ"), ("1", "AB", "Ⅲ")],
    "U.T.": [("100", "B", "Ⅰ"), ("1", "B", "Ⅱ")],
    "U.I.T.": [("100", "B", "Ⅰ"), ("1", "B", "Ⅱ")],
    "TOFD": [("100", "B", "Ⅰ"), ("1", "B", "Ⅱ")],
    "PAUT": [("100", "B", "Ⅰ"), ("1", "B", "Ⅱ")],
    "M.T.": [("100", "/", "Ⅰ")],
    "P.T.": [("100", "/", "Ⅰ")],
    "M.T.[FB]": [("100", "/", "Ⅰ")],
}

try:
    from modules.condition_input.funcs.funcs_cdt_input import (
        update_trail_table_side_only as _orig_update_trail,
        compute_trail_default_grade as _orig_grade,
        _determine_diameter_series as _orig_series,
        _get_outer_diameter_from_mapping as _orig_mapping,
        _get_outer_diameter_formula as _orig_formula,
        _calculate_outer_diameter_by_formula as _orig_calc,
    )
    HAS_ORIG = True
except Exception:      # 脱离主项目环境（纯逻辑测试等）——用本地同款映射
    HAS_ORIG = False


# ------------------------------------------------------------------
# 焊接接头系数 → 检测数据
# ------------------------------------------------------------------

def apply_weld_factor(ndt_table, side, factor_val):
    """
    焊接接头系数改值 → 检测数据表 R.T. 行对应侧三段（技术等级/检测比例/合格级别）。
    side: "壳程" / "管程"（原版接口就是中文侧名）。直接写 QTableWidget 单元格。
    返回 True=已联动；False=系数不在映射表（原版就是静默跳过）。
    """
    factor_val = str(factor_val or "").strip()
    if HAS_ORIG:
        _orig_update_trail(ndt_table, side, factor_val, None)
        return factor_val in _WELD_FACTOR_MAP
    vals = _WELD_FACTOR_MAP.get(factor_val)
    if not vals:
        return False
    cols = {"壳程": (2, 3, 4), "管程": (5, 6, 7)}[side]
    from PyQt5.QtWidgets import QTableWidgetItem
    for col, val in zip(cols, vals):
        it = ndt_table.item(0, col)
        if it is None:
            it = QTableWidgetItem()
            ndt_table.setItem(0, col, it)
        it.setText(val)
    return True


def grade_for_ratio(method, ratio):
    """
    检测比例 → (技术等级, 合格级别)。查不到返回 ("", "")。
    与原版口径一致：比例数字 >= 档位下限即命中（"≥20" 解析成 20，归 1–99% 档）。
    """
    method = (method or "").strip()
    ratio = (ratio or "").strip()
    if not method or not ratio:
        return "", ""
    try:
        num = float(re.sub(r"[^\d.]", "", ratio))
    except ValueError:
        return "", ""
    if HAS_ORIG:
        return (_orig_grade(method, ratio, "技术等级") or "",
                _orig_grade(method, ratio, "合格级别") or "")
    for limit, grade, qualify in _RATIO_GRADE_TABLE.get(method, []):
        try:
            if num >= float(re.sub(r"[^\d.]", "", limit)):
                return grade, qualify
        except ValueError:
            continue
    return "", ""


# ------------------------------------------------------------------
# 外径自动填充（配置库映射表 / 公式）
# ------------------------------------------------------------------

def compute_outer(dn, series_ui=""):
    """
    公称直径 DN → (外径值 str, 外径系列 str)。
    口径对齐原版 autofill_outer_diameter（funcs_cdt_input.py:894）：
      · 界面已有外径系列 → 优先用界面的；空的 → 配置库默认系列
      · 映射表命中 → 直接用映射值
      · 没命中 → 系列显示 "-"（公式态），外径按配置库公式计算
      · 界面系列为 "-" 时：用默认系列查表，命中后恢复默认系列显示
    系列为 "-" 表示该 DN 不在映射表里，外径是公式计算态。
    dn 为空 → ("—", None)；配置库取不到 → (None, None)（不动界面）。
    """
    if not HAS_ORIG:
        return None, None
    if dn is None:
        return "—", None
    series_ui = (series_ui or "").strip()
    default_series = _orig_series()
    if series_ui and series_ui != "-":
        lookup = series_ui
    else:
        lookup = default_series or "公制系列"
        if not default_series:
            return "—", None
    outer = _orig_mapping(dn, lookup)
    if outer:
        # 公式态（系列为"-"）查表命中 → 恢复成实际系列显示（原版口径）
        return str(outer), lookup
    formula = _orig_formula()
    if not formula:
        return None, None
    val = _orig_calc(dn, formula)
    if val is None:
        return None, None
    return str(int(val)), "-"


def parse_dn(text):
    """公称直径文本 → int；解析不出返回 None（对齐原版 _parse_int_safe 的用途）。"""
    m = re.search(r"\d+(?:\.\d+)?", str(text or ""))
    if not m:
        return None
    try:
        return int(float(m.group(0)))
    except ValueError:
        return None
