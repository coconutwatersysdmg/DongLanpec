import ast
import json
import math
import os
from copy import copy
from pathlib import Path

import configparser
import re

import chardet
import pandas as pd
import pymysql
import openpyxl
from openpyxl.reader.excel import load_workbook

from modules.chanpinguanli.chanpinguanli_main import product_manager
from modules.condition_input.funcs.db_cnt import get_connection


MATERIAL_START_ROW = 7
MATERIAL_NAME_COL = 2       # B: 名称
MATERIAL_SPEC_COL = 3       # C: 规格型号
MATERIAL_GRADE_COL = 4      # D: 材料
MATERIAL_QUANTITY_COL = 5   # E: 数量
MATERIAL_UNIT_WEIGHT_COL = 15   # O: 毛坯单重
MATERIAL_TOTAL_WEIGHT_COL = 16  # P: 毛坯总重
MATERIAL_FORMED_TOTAL_WEIGHT_COL = 17 # Q: 成型总重
MATERIAL_OVERLAY_WEIGHT_COL = 18      # R: 覆层重量
MATERIAL_SUPPLY_COL = 19              # S: 供货状态
MATERIAL_TYPE_COL = 20                # T: 材料类型
MATERIAL_REMARK_COL = 21              # U: 备注
MATERIAL_FORMED_UNIT_WEIGHT_COL = 24  # X: 生成过程中暂存成型单重
MATERIAL_SPEC_STAGING_COL = 25        # Y: 生成过程中暂存规格型号
MATERIAL_OUTPUT_FONT_NAME = "Calibri"
MATERIAL_WEIGHT_TOTAL_LABEL_COL = 14  # N: 重量统计
MATERIAL_WEIGHT_TOTAL_LABELS = ("重量统计", "总计重量")
MATERIAL_LUG_NAMES = frozenset({
    "吊耳",
    "管箱吊耳",
    "前端管箱吊耳",
    "后端管箱吊耳",
})
MATERIAL_WEIGHT_COLUMNS = (
    MATERIAL_UNIT_WEIGHT_COL,
    MATERIAL_TOTAL_WEIGHT_COL,
    MATERIAL_FORMED_TOTAL_WEIGHT_COL,
    MATERIAL_OVERLAY_WEIGHT_COL,
)
MATERIAL_FIXED_TAIL_NAMES = (
    "钢结构",
    "特殊焊材费",
    "堆焊焊材费",
    "紧固件和密封件",
)
MATERIAL_OUTPUT_COLUMNS = (
    1, MATERIAL_NAME_COL, MATERIAL_SPEC_COL, MATERIAL_GRADE_COL,
    MATERIAL_QUANTITY_COL,
    MATERIAL_UNIT_WEIGHT_COL, MATERIAL_TOTAL_WEIGHT_COL,
    MATERIAL_FORMED_TOTAL_WEIGHT_COL, MATERIAL_OVERLAY_WEIGHT_COL,
    MATERIAL_SUPPLY_COL, MATERIAL_TYPE_COL, MATERIAL_REMARK_COL,
    MATERIAL_FORMED_UNIT_WEIGHT_COL,
    MATERIAL_SPEC_STAGING_COL,
)

_CELL_REFERENCE_RE = re.compile(r"(?<![A-Z0-9_])(\$?[A-Z]{1,3})(\$?)(\d+)")


def find_material_section_end(sheet):
    """返回材料区之后“外购费”标题所在行。"""
    for row_idx in range(MATERIAL_START_ROW, sheet.max_row + 1):
        title = str(sheet.cell(row=row_idx, column=1).value or "").strip()
        if title in {"外购费", "外购外协费"}:
            return row_idx
    raise ValueError("材料清单模板中未找到‘外购费’分区")


def find_material_fixed_tail_start(sheet):
    """返回受保护的材料尾部固定行起始位置；旧模板没有则返回材料区末行。"""
    section_end = find_material_section_end(sheet)
    tail_length = len(MATERIAL_FIXED_TAIL_NAMES)
    for row_idx in range(MATERIAL_START_ROW, section_end - tail_length + 1):
        names = tuple(
            str(sheet.cell(row_idx + offset, MATERIAL_NAME_COL).value or "").strip()
            for offset in range(tail_length)
        )
        if names == MATERIAL_FIXED_TAIL_NAMES:
            return row_idx
    return section_end


def iter_material_rows(sheet):
    return sheet.iter_rows(
        min_row=MATERIAL_START_ROW,
        max_row=find_material_fixed_tail_start(sheet) - 1,
        min_col=1,
        max_col=MATERIAL_SPEC_STAGING_COL,
    )


def iter_material_fixed_tail_rows(sheet):
    tail_start = find_material_fixed_tail_start(sheet)
    return sheet.iter_rows(
        min_row=tail_start,
        max_row=min(
            tail_start + len(MATERIAL_FIXED_TAIL_NAMES) - 1,
            find_material_section_end(sheet) - 1,
        ),
        min_col=1,
        max_col=MATERIAL_REMARK_COL,
    )


def find_material_weight_total_row(sheet):
    """查找模板右侧 N 列预留的“重量统计/总计重量”行。"""
    section_end = find_material_section_end(sheet)
    for row_idx in range(MATERIAL_START_ROW, section_end):
        label = str(
            sheet.cell(row_idx, MATERIAL_WEIGHT_TOTAL_LABEL_COL).value or ""
        ).strip()
        if label in MATERIAL_WEIGHT_TOTAL_LABELS:
            return row_idx
    return None


def _material_output_font(source_font):
    """保留字号/颜色/粗体等属性，并移除模板遗留的中文字符集字体标记。"""
    output_font = copy(source_font)
    output_font.name = MATERIAL_OUTPUT_FONT_NAME
    output_font.charset = None
    output_font.family = 2
    output_font.scheme = None
    return output_font


def write_material_weight_totals(sheet, last_data_row):
    """将 N:R 重量统计放到最后一条生成明细的下一行。"""
    target_row = max(MATERIAL_START_ROW, last_data_row + 1)
    template_row = find_material_weight_total_row(sheet)
    label = "重量统计"

    if template_row is not None:
        existing_label = str(
            sheet.cell(template_row, MATERIAL_WEIGHT_TOTAL_LABEL_COL).value or ""
        ).strip()
        if existing_label:
            label = existing_label

        if template_row != target_row:
            for column in range(
                MATERIAL_WEIGHT_TOTAL_LABEL_COL,
                MATERIAL_OVERLAY_WEIGHT_COL + 1,
            ):
                source = sheet.cell(template_row, column)
                target = sheet.cell(target_row, column)
                if source.has_style:
                    target._style = copy(source._style)
                target.number_format = source.number_format
                target.font = copy(source.font)
                target.alignment = copy(source.alignment)
                target.protection = copy(source.protection)
                target.hyperlink = copy(source.hyperlink)
                target.comment = copy(source.comment)
                _clear_material_cell(source)

    label_cell = sheet.cell(target_row, MATERIAL_WEIGHT_TOTAL_LABEL_COL)
    label_cell.value = label
    label_cell.font = _material_output_font(label_cell.font)
    for column in MATERIAL_WEIGHT_COLUMNS:
        cell = sheet.cell(target_row, column)
        if last_data_row >= MATERIAL_START_ROW:
            column_letter = cell.column_letter
            cell.value = (
                f"=SUM({column_letter}{MATERIAL_START_ROW}:"
                f"{column_letter}{last_data_row})"
            )
        else:
            cell.value = 0
        cell.number_format = "0.00"
        cell.font = _material_output_font(cell.font)

    return target_row


class _LegacyMaterialRow:
    """让原有数量/质量算法继续按旧列索引工作，实际写入新模板列。"""

    _INDEX_MAP = {
        2: MATERIAL_SPEC_STAGING_COL - 1,
        3: MATERIAL_NAME_COL - 1,
        5: MATERIAL_GRADE_COL - 1,
        6: MATERIAL_QUANTITY_COL - 1,
        7: MATERIAL_UNIT_WEIGHT_COL - 1,
        8: MATERIAL_TOTAL_WEIGHT_COL - 1,
        9: MATERIAL_FORMED_UNIT_WEIGHT_COL - 1,
        10: MATERIAL_SUPPLY_COL - 1,
        11: MATERIAL_TYPE_COL - 1,
        12: MATERIAL_REMARK_COL - 1,
    }

    def __init__(self, cells):
        self._cells = cells

    def __getitem__(self, index):
        return self._cells[self._INDEX_MAP.get(index, index)]

    def __len__(self):
        return len(self._cells)


def _shift_formula_references(formula, insert_at, amount):
    if not isinstance(formula, str) or not formula.startswith("="):
        return formula

    def replace(match):
        column, absolute_marker, row_text = match.groups()
        row_number = int(row_text)
        if row_number >= insert_at:
            row_number += amount
        return f"{column}{absolute_marker}{row_number}"

    return _CELL_REFERENCE_RE.sub(replace, formula)


def _shift_formula_references_for_delete(formula, delete_at, amount):
    if not isinstance(formula, str) or not formula.startswith("="):
        return formula

    delete_end = delete_at + amount

    def replace(match):
        column, absolute_marker, row_text = match.groups()
        row_number = int(row_text)
        if row_number >= delete_end:
            row_number -= amount
        return f"{column}{absolute_marker}{row_number}"

    return _CELL_REFERENCE_RE.sub(replace, formula)


def _copy_material_cell(source, target):
    target.value = source.value
    if source.has_style:
        target._style = copy(source._style)
    target.number_format = source.number_format
    target.font = copy(source.font)
    target.alignment = copy(source.alignment)
    target.protection = copy(source.protection)
    target.hyperlink = copy(source.hyperlink)
    target.comment = copy(source.comment)


def _clear_material_cell(cell):
    cell.value = None
    cell.hyperlink = None
    cell.comment = None


def _insert_template_rows(sheet, insert_at, amount=1):
    """在固定模板区前插行，并同步移动合并区域、行高与公式引用。"""
    if amount <= 0:
        return

    formulas = {
        cell.coordinate: cell.value
        for row in sheet.iter_rows()
        for cell in row
        if cell.data_type == "f"
    }
    merged_ranges = [str(cell_range) for cell_range in sheet.merged_cells.ranges]
    for cell_range in list(sheet.merged_cells.ranges):
        if cell_range.max_row >= insert_at:
            sheet.unmerge_cells(str(cell_range))

    row_dimensions = {}
    for row_idx, dimension in list(sheet.row_dimensions.items()):
        if row_idx >= insert_at:
            row_dimensions[row_idx] = {
                "height": dimension.height,
                "hidden": dimension.hidden,
                "outlineLevel": dimension.outlineLevel,
                "collapsed": dimension.collapsed,
            }

    sheet.insert_rows(insert_at, amount)

    for row_idx in row_dimensions:
        if row_idx in sheet.row_dimensions:
            del sheet.row_dimensions[row_idx]
    for old_row, attrs in row_dimensions.items():
        new_dimension = sheet.row_dimensions[old_row + amount]
        for key, value in attrs.items():
            setattr(new_dimension, key, value)

    # 新增的材料行沿用原材料区最后一条生成行的完整样式。
    source_row = max(MATERIAL_START_ROW, insert_at - 1)
    for new_row in range(insert_at, insert_at + amount):
        for column in range(1, MATERIAL_REMARK_COL + 1):
            source = sheet.cell(row=source_row, column=column)
            target = sheet.cell(row=new_row, column=column)
            if source.has_style:
                target._style = copy(source._style)
            target.number_format = source.number_format
            target.font = copy(source.font)
            target.alignment = copy(source.alignment)
            target.protection = copy(source.protection)
        # 新模板生成行的订料系数及总价公式需要随新增行延续。
        sheet.cell(new_row, 9).value = 1
        sheet.cell(new_row, 10).value = f"=E{new_row}*H{new_row}"

    from openpyxl.utils.cell import range_boundaries, get_column_letter

    for merged_range in merged_ranges:
        min_col, min_row, max_col, max_row = range_boundaries(merged_range)
        if max_row < insert_at:
            continue
        if min_row >= insert_at:
            min_row += amount
            max_row += amount
        else:
            max_row += amount
        sheet.merge_cells(
            f"{get_column_letter(min_col)}{min_row}:"
            f"{get_column_letter(max_col)}{max_row}"
        )

    for coordinate, formula in formulas.items():
        from openpyxl.utils.cell import coordinate_from_string

        column, old_row = coordinate_from_string(coordinate)
        new_row = old_row + amount if old_row >= insert_at else old_row
        sheet[f"{column}{new_row}"] = _shift_formula_references(
            formula, insert_at, amount
        )


def _delete_template_rows(sheet, delete_at, amount=1):
    """删除模板固定区之前的空行，并同步上移合并区域、行高与公式。"""
    if amount <= 0:
        return

    delete_end = delete_at + amount
    formulas = {
        cell.coordinate: cell.value
        for row in sheet.iter_rows()
        for cell in row
        if cell.data_type == "f"
    }
    merged_ranges = [str(cell_range) for cell_range in sheet.merged_cells.ranges]
    for cell_range in list(sheet.merged_cells.ranges):
        if cell_range.max_row >= delete_at:
            sheet.unmerge_cells(str(cell_range))

    row_dimensions = {}
    for row_idx, dimension in list(sheet.row_dimensions.items()):
        if row_idx >= delete_at:
            row_dimensions[row_idx] = {
                "height": dimension.height,
                "hidden": dimension.hidden,
                "outlineLevel": dimension.outlineLevel,
                "collapsed": dimension.collapsed,
            }
            del sheet.row_dimensions[row_idx]

    sheet.delete_rows(delete_at, amount)

    for old_row, attrs in row_dimensions.items():
        if old_row < delete_end:
            continue
        new_dimension = sheet.row_dimensions[old_row - amount]
        for key, value in attrs.items():
            setattr(new_dimension, key, value)

    from openpyxl.utils.cell import range_boundaries, get_column_letter

    for merged_range in merged_ranges:
        min_col, min_row, max_col, max_row = range_boundaries(merged_range)
        if max_row < delete_at:
            continue
        if min_row >= delete_end:
            min_row -= amount
            max_row -= amount
        elif max_row < delete_end:
            continue
        else:
            min_row = min(min_row, delete_at)
            max_row -= amount

        if min_row < max_row or min_col < max_col:
            sheet.merge_cells(
                f"{get_column_letter(min_col)}{min_row}:"
                f"{get_column_letter(max_col)}{max_row}"
            )

    for coordinate, formula in formulas.items():
        from openpyxl.utils.cell import coordinate_from_string

        column, old_row = coordinate_from_string(coordinate)
        if delete_at <= old_row < delete_end:
            continue
        new_row = old_row - amount if old_row >= delete_end else old_row
        sheet[f"{column}{new_row}"] = _shift_formula_references_for_delete(
            formula, delete_at, amount
        )


def ensure_material_row_capacity(sheet, target_row):
    fixed_tail_start = find_material_fixed_tail_start(sheet)
    if target_row >= fixed_tail_start:
        _insert_template_rows(
            sheet,
            fixed_tail_start,
            target_row - fixed_tail_start + 1,
        )


def trim_unused_material_rows(sheet):
    """删除生成区末尾空白行，让受保护的固定材料行紧跟生成明细。"""
    fixed_tail_start = find_material_fixed_tail_start(sheet)
    last_data_row = MATERIAL_START_ROW - 1
    for row_idx in range(MATERIAL_START_ROW, fixed_tail_start):
        if sheet.cell(row_idx, MATERIAL_NAME_COL).value not in (None, "", "None"):
            last_data_row = row_idx

    first_unused_row = last_data_row + 1
    unused_count = fixed_tail_start - first_unused_row
    if unused_count > 0:
        _delete_template_rows(sheet, first_unused_row, unused_count)
    return last_data_row


def insert_material_row(sheet, row_idx):
    """在生成材料区插入空记录，不覆盖固定材料尾行及后续模板。"""
    fixed_tail_start = find_material_fixed_tail_start(sheet)
    last_row = fixed_tail_start - 1
    if sheet.cell(last_row, MATERIAL_NAME_COL).value not in (None, "", "None"):
        _insert_template_rows(sheet, fixed_tail_start, 1)
        fixed_tail_start = find_material_fixed_tail_start(sheet)
        last_row = fixed_tail_start - 1

    row_idx = min(max(row_idx, MATERIAL_START_ROW), last_row)
    for source_row in range(last_row - 1, row_idx - 1, -1):
        for column in MATERIAL_OUTPUT_COLUMNS:
            _copy_material_cell(
                sheet.cell(source_row, column),
                sheet.cell(source_row + 1, column),
            )
    for column in MATERIAL_OUTPUT_COLUMNS:
        _clear_material_cell(sheet.cell(row_idx, column))


def remove_unused_nozzle_reinforcement_rings(sheet, json_data):
    """管口计算输出只有明确标记“是”时，才允许保留对应的补强圈。"""
    dict_out = (json_data or {}).get("DictOutDatas") or {}
    allowed_names = set()
    if isinstance(dict_out, dict):
        for section_name, section in dict_out.items():
            if not isinstance(section_name, str) or not section_name.endswith("接管"):
                continue
            datas = section.get("Datas") if isinstance(section, dict) else None
            params = {
                str(item.get("Name") or "").strip(): item.get("Value")
                for item in (datas if isinstance(datas, list) else [])
                if isinstance(item, dict)
            }
            if str(params.get("是否使用补强圈") or "").strip() != "是":
                continue
            owners = {section_name, section_name[:-2]}
            code = str(params.get("接管序号") or params.get("管口号") or "").strip()
            if code:
                owners.add(code)
            for owner in owners:
                if owner:
                    allowed_names.update({
                        f"{owner}补强圈", f"补强圈（{owner}）", f"补强圈({owner})",
                    })

    rows_to_delete = []
    for row in iter_material_rows(sheet):
        name_cell = row[MATERIAL_NAME_COL - 1]
        name = str(name_cell.value or "").strip()
        if "补强圈" not in name:
            continue
        # 汇总行仅在至少一个管口明确使用补强圈时保留。
        if name == "补强圈" and allowed_names:
            continue
        if any(name.startswith(allowed) for allowed in allowed_names):
            continue
        rows_to_delete.append(name_cell.row)
        print(f"🗑️ 删除：{name}（对应管口计算输出‘是否使用补强圈’不为‘是’）")
    remove_material_rows(sheet, rows_to_delete)
    return len(rows_to_delete)


def remove_material_rows(sheet, row_indexes):
    """删除生成记录时仅压缩生成区，固定材料尾行保持完整。"""
    remove_set = {int(row_idx) for row_idx in row_indexes}
    fixed_tail_start = find_material_fixed_tail_start(sheet)
    source_rows = [
        row_idx for row_idx in range(MATERIAL_START_ROW, fixed_tail_start)
        if row_idx not in remove_set
    ]

    for target_row, source_row in zip(
        range(MATERIAL_START_ROW, fixed_tail_start), source_rows
    ):
        if target_row == source_row:
            continue
        for column in MATERIAL_OUTPUT_COLUMNS:
            _copy_material_cell(
                sheet.cell(source_row, column),
                sheet.cell(target_row, column),
            )

    first_empty = MATERIAL_START_ROW + len(source_rows)
    for row_idx in range(first_empty, fixed_tail_start):
        for column in MATERIAL_OUTPUT_COLUMNS:
            _clear_material_cell(sheet.cell(row_idx, column))


def get_value2_huodongku(sql, params=None):
    conn2 = pymysql.connect(
        host="localhost", user="root", password="123456",
        database="产品设计活动库", charset="utf8mb4",
        cursorclass=pymysql.cursors.Cursor
    )
    cursor2 = conn2.cursor()
    cursor2.execute(sql, params or ())
    row = cursor2.fetchone()
    return row[0] if row and row[0] is not None else None


db_config1 = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '产品设计活动库'
}
product_id = None

MATERIAL_LIST_PATCH_VERSION = "2026-09-28-v10-lug-grounding-rules"


def _clean_material_rule_value(value):
    if value in (None, "", "None"):
        return ""
    return str(value).strip()


def _lug_rule_params(lug_rule_map, component_name):
    """按当前名称、管箱吊耳、吊耳的顺序查找吊耳附加参数。"""
    if not isinstance(lug_rule_map, dict):
        return {}

    candidates = [component_name]
    if component_name != "管箱吊耳":
        candidates.append("管箱吊耳")
    if component_name != "吊耳":
        candidates.append("吊耳")

    for candidate in candidates:
        params = lug_rule_map.get(candidate)
        if isinstance(params, dict) and params:
            return params
    return {}


def resolve_lug_material_rule(existing_material, params):
    """返回吊耳最终材料和固定单重；是否带垫板未定义时保持原值。"""
    params = params if isinstance(params, dict) else {}
    lug_material = (
        _clean_material_rule_value(params.get("材料牌号"))
        or _clean_material_rule_value(existing_material)
    )
    backing_material = _clean_material_rule_value(params.get("垫板材料牌号"))
    backing_flag = _clean_material_rule_value(params.get("是否带垫板")).lower()

    if backing_flag in {"是", "1", "true", "yes"}:
        return lug_material, None

    if backing_flag in {"否", "0", "false", "no"}:
        material = "/".join(
            value for value in (lug_material, backing_material) if value
        )
        return material or _clean_material_rule_value(existing_material), 10.0

    return _clean_material_rule_value(existing_material), None


def load_material_lug_rules(product_id):
    """读取吊耳/管箱吊耳的材料牌号、垫板材料牌号和是否带垫板。"""
    if product_id in (None, "", "None"):
        return {}

    connection = None
    try:
        connection = pymysql.connect(
            host="localhost",
            port=3306,
            user="root",
            password="123456",
            database="产品设计活动库",
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
        with connection.cursor() as cursor:
            placeholders = ", ".join(["%s"] * len(MATERIAL_LUG_NAMES))
            cursor.execute(
                f"""
                SELECT 元件名称, 参数名称, 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s
                  AND 元件名称 IN ({placeholders})
                  AND 参数名称 IN ('材料牌号', '垫板材料牌号', '是否带垫板')
                """,
                (product_id, *sorted(MATERIAL_LUG_NAMES)),
            )
            rows = cursor.fetchall() or []
    except Exception as exc:
        print(f"⚠️ 读取吊耳材料规则失败，保留原材料值: {exc}")
        return {}
    finally:
        if connection is not None:
            connection.close()

    result = {}
    for row in rows:
        component_name = _clean_material_rule_value(row.get("元件名称"))
        parameter_name = _clean_material_rule_value(row.get("参数名称"))
        if component_name and parameter_name:
            result.setdefault(component_name, {})[parameter_name] = row.get("参数值")
    return result


def apply_fixed_material_item_rules(sheet, product_id=None, lug_rule_map=None):
    """应用接地装置及吊耳的固定数量、材料和单重规则。"""
    if lug_rule_map is None:
        lug_rule_map = load_material_lug_rules(product_id)

    for row in iter_material_rows(sheet):
        name_cell = row[MATERIAL_NAME_COL - 1]
        component_name = _clean_material_rule_value(name_cell.value)
        if component_name == "接地装置":
            row[MATERIAL_UNIT_WEIGHT_COL - 1].value = 0.8
            continue

        if component_name not in MATERIAL_LUG_NAMES:
            continue

        row[MATERIAL_QUANTITY_COL - 1].value = 2
        params = _lug_rule_params(lug_rule_map, component_name)
        material_cell = row[MATERIAL_GRADE_COL - 1]
        material, unit_weight = resolve_lug_material_rule(
            material_cell.value,
            params,
        )
        if material:
            material_cell.value = material
        if unit_weight is not None:
            row[MATERIAL_UNIT_WEIGHT_COL - 1].value = unit_weight


def _is_effective_component_param_value(value):
    """0/False/“否”视为有效；None、空串、None/null/nan 文本视为空。"""
    if value is None:
        return False
    if isinstance(value, float):
        try:
            if math.isnan(value):
                return False
        except Exception:
            pass
    s = str(value).strip()
    if s == "":
        return False
    return s.lower() not in {"none", "null", "nan"}


def _remove_components_with_all_empty_params(sheet, product_id, json_data=None):
    """
    对材料区所有元件统一执行：
    若附加参数表中存在该元件记录，但所有参数值都为空，则直接从材料区删除。
    圆筒例外地以计算 JSON 的“容器圆筒”为真实参数来源：只要容器圆筒存在有效值就保留。
    在 fill_special_items 之前执行，防止空元件进入特殊质量计算。
    """
    conn = None
    cursor = None
    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 元件名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s
        """, (product_id,))
        param_map = {}
        for r in cursor.fetchall() or []:
            name = str(r.get("元件名称") or "").strip()
            if name:
                param_map.setdefault(name, []).append(r.get("参数值"))
    except Exception as e:
        print(f"⚠️ 全元件空参数预检查失败：{e}")
        return 0
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass

    rows_to_delete = []
    for cells in iter_material_rows(sheet):
        name_cell = cells[MATERIAL_NAME_COL - 1]
        name = str(name_cell.value or "").strip()
        if not name:
            continue
        values = param_map.get(name)

        # 圆筒的真实参数/质量来源是“容器圆筒”；只要该 JSON 段存在有效值，就不能按空附加参数删除。
        if name == "圆筒" and isinstance(json_data, dict):
            container_obj = (json_data.get("DictOutDatas") or {}).get("容器圆筒")
            container_datas = container_obj.get("Datas") if isinstance(container_obj, dict) else None
            if isinstance(container_datas, list) and any(
                isinstance(item, dict) and _is_effective_component_param_value(item.get("Value"))
                for item in container_datas
            ):
                continue

        if values and not any(_is_effective_component_param_value(v) for v in values):
            rows_to_delete.append(name_cell.row)
            print(f"🗑️ 预删除空参数元件：{name}")

    remove_material_rows(sheet, rows_to_delete)
    return len(rows_to_delete)



def on_product_id_changed(new_id):
    print(f"Received new PRODUCT_ID: {new_id}")
    global product_id
    product_id = new_id


# 测试用产品 ID（真实情况中由外部输入）
product_manager.product_id_changed.connect(on_product_id_changed)

# === 精准映射：元件名称 → List[(section, 字段名, 类型)]


# === 数量 & 单重填写逻辑 ===
import os
import json
import openpyxl
import chardet
import configparser
import pymysql


def get_tie_rods_length(product_id, conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 元件数量
        FROM 产品设计活动表_布管元件表
        WHERE 产品ID = %s AND 元件类型 = %s
    """, (product_id, 0))

    rows = cursor.fetchall() or []
    cursor.execute("""
        SELECT 元件数量
        FROM 产品设计活动表_布管元件表
        WHERE 产品ID = %s AND 元件类型 = %s
    """, (product_id, 1))

    rows_1 = cursor.fetchall() or []
    sql = """
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '拉杆' AND 参数名称 = '配套螺母数量'
    """
    cursor.execute(sql, (product_id,))
    luomu_row = cursor.fetchone()
    luomu = None
    if luomu_row:
        luomu = luomu_row.get("参数值")

    # 默认1倍
    luomu_multiplier = 1
    if luomu:
        s = str(luomu).lower().replace("×", "x")
        if "x" in s:
            # 提取x后面的数字
            try:
                luomu_multiplier = int(s.split("x")[-1])
            except ValueError:
                pass
        else:
            try:
                luomu_multiplier = int(s)
            except ValueError:
                pass

    total = 0
    for row in rows:
        val = row[0] if isinstance(row, (tuple, list)) else row.get("元件数量", 0)
        if val is not None:
            try:
                total += int(val)
            except ValueError:
                continue
    for row in rows_1:
        val1 = row[0] if isinstance(row, (tuple, list)) else row.get("元件数量", 0)
        if val1 is not None:
            try:
                total += int(val1)
            except ValueError:
                continue
    luomu_shuliang = luomu_multiplier * total
    return luomu_shuliang


def get_tie_rods_length2(product_id, conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 元件数量
        FROM 产品设计活动表_布管元件表
        WHERE 产品ID = %s AND 元件类型 = %s
    """, (product_id, 0))

    rows = cursor.fetchall() or []
    cursor.execute("""
        SELECT 元件数量
        FROM 产品设计活动表_布管元件表
        WHERE 产品ID = %s AND 元件类型 = %s
    """, (product_id, 1))

    rows_1 = cursor.fetchall() or []
    total = 0
    for row in rows:
        val = row[0] if isinstance(row, (tuple, list)) else row.get("元件数量", 0)
        if val is not None:
            try:
                total += int(val)
            except ValueError:
                continue
    for row in rows_1:
        val1 = row[0] if isinstance(row, (tuple, list)) else row.get("元件数量", 0)
        if val1 is not None:
            try:
                total += int(val1)
            except ValueError:
                continue

    return total


# === 精准映射：元件名称 → List[(section, 字段名, 类型)]
mapping_dict = {
    # 圆筒不拆分；毛坯单重统一取计算 JSON 的“容器圆筒/圆筒重量kg”。
    "圆筒": [("容器圆筒", "圆筒重量kg", "质量")],
    # 通用“封头”后续会在 cunguige.py 拆成前端/后端；这里先把原封头单重写好。
    # 兼容计算结果中两种常见字段名。
    "前端封头": [
        ("前端封头", "椭圆形封头质量 kg", "质量"),
        ("前端封头", "封头质量 kg", "质量"),
        ("前端封头", "封头重量kg", "质量"),
    ],
    "后端封头": [
        ("后端封头", "椭圆形封头质量 kg", "质量"),
        ("后端封头", "封头质量 kg", "质量"),
        ("后端封头", "封头重量kg", "质量"),
    ],
    "管箱封头": [("管箱封头", "椭圆形封头质量 kg", "质量")],
    "管箱圆筒": [("管箱圆筒", "圆筒重量kg", "质量")],
    "外头盖圆筒": [("外头盖圆筒", "圆筒重量kg", "质量")],
    "外头盖封头": [("外头盖封头", "椭圆形封头质量 kg", "质量")],
    "浮头法兰": [("浮头法兰", "腐蚀前管程浮头法兰毛坯重量", "质量")],
    "浮动管板": [("固定管板", "浮动管板重量-毛坯", "质量")],
    "端部圆筒": [("后端管箱圆筒", "圆筒重量kg", "质量")],
    "管箱法兰": [("管箱法兰", "法兰毛坯质量", "质量")],
    "前端管箱圆筒": [("管箱圆筒", "圆筒重量kg", "质量")],
    "后端管箱封头": [("后端管箱封头", "椭圆形封头质量 kg", "质量")],
    "后端管箱圆筒": [("后端管箱圆筒", "圆筒重量kg", "质量")],

    "固定管板": [("固定管板", "管板重量-毛坯（基层）", "质量")],
    "U形换热管": [("固定管板", "换热管根数", "数量")],
    "壳体法兰": [("壳体法兰", "法兰毛坯质量", "质量")],
    "管箱平盖": [("管箱平盖", "法兰毛坯质量", "质量")],
    "前端管箱平盖": [("管箱平盖", "法兰毛坯质量", "质量")],
    "前端管箱头盖法兰": [("头盖法兰", "法兰毛坯质量", "质量")],
    "壳体大端圆筒": [("大端壳体圆筒", "圆筒重量kg", "质量")],
    "壳体小端圆筒": [("小端壳体圆筒", "圆筒重量kg", "质量")],
    "锥壳": [("锥壳", "锥壳质量", "质量")],
    "头盖法兰": [("头盖法兰", "法兰毛坯质量", "质量")],
    "外头盖法兰": [("外头盖法兰", "法兰毛坯质量", "质量")],
    "外头盖侧法兰": [("外头盖侧法兰", "法兰毛坯质量", "质量")],
    "壳体圆筒": [("壳体圆筒", "圆筒重量kg", "质量")],
    "壳体封头": [("壳体封头", "椭圆形封头质量 kg", "质量")],
    "固定鞍座": [("固定鞍座", "鞍式支座质量", "质量")],
    "螺柱（管箱法兰）": [("管箱法兰", "螺栓数量", "数量")],
    "尾部支撑": [("管束", "尾部支撑数量", "数量")],
    "折流板": [("管束", "折流板数量", "数量"), ("管束", "弓形/异形折流板实际数量", "数量"),
               ("管束", "弓形折流板毛坯重量", "质量")],
    "折流板Ⅰ": [("管束", "折流板数量", "数量"), ("管束", "弓形/异形折流板实际数量", "数量"),
                ("管束", "弓形折流板毛坯重量", "质量")],
    "折流板Ⅱ": [("管束", "折流板数量", "数量"), ("管束", "弓形/异形折流板实际数量", "数量"),
                ("管束", "弓形折流板毛坯重量", "质量")],
    "螺柱（壳体法兰）": [("壳体法兰", "螺栓数量", "数量")],
    "螺柱（浮头法兰）": [("浮头法兰", "螺栓数量", "数量")],
    "换热管": [("固定管板", "换热管根数", "数量")],
    "异形折流板": [("浮头管束", "异形折流板毛坯重量", "质量")],
    "弓形折流板": [("浮头管束", "弓形折流板毛坯重量", "质量")],
    "弓形折流板Ⅰ": [("浮头管束", "弓形折流板毛坯重量", "质量")],
    "弓形折流板Ⅱ": [("浮头管束", "弓形折流板毛坯重量", "质量")],
    "支撑板": [("浮头管束", "固定侧支撑板重量", "质量")],
    "支持板": [("浮头管束", "支持板重量", "质量")],
    "内导流筒": [("浮头管束", "固定侧导流筒重量", "质量")],
    "滑道": [("浮头管束", "滑道重量", "质量")],
    "挡管": [("浮头管束", "中间挡管重量", "质量")],
    "防冲板": [("浮头管束", "防冲挡板重量", "质量"),
               ("管束", "防冲挡板重量", "质量")],
    "堵板": [("浮头管束", "堵板重量", "质量")],
    "拉杆": [("浮头管束", "拉杆重量", "质量")],
    "定距管": [("浮头管束", "定距管重量", "质量")],
    "钩圈": [("浮头法兰", "钩圈重量", "质量")],
    "内折流板": [("浮头管束", "内折流板毛坯重量", "质量"), ("管束", "内折流板毛坯重量", "质量")],
    "球冠形封头": [("浮头法兰", "球冠形封头重量", "质量")],

}


def load_json_file(path):
    if not os.path.exists(path):
        print(f"⚠️ JSON 文件不存在: {path}")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def fill_quantity_weight(json_data, sheet):
    updated = 0
    for cells in iter_material_rows(sheet):
        row = _LegacyMaterialRow(cells)
        name_cell = row[3]
        qty_cell = row[6]
        wt_cell = row[7]

        if not name_cell.value:
            continue

        item_name = str(name_cell.value).strip()
        if item_name not in mapping_dict:
            continue

        for section, field_name, data_type in mapping_dict[item_name]:
            datas = json_data.get("DictOutDatas", {}).get(section, {}).get("Datas")
            if not isinstance(datas, list):
                print(f"⚠️ {section} -> Datas 为空或不是列表，已跳过")
                continue

            for item in datas:
                if item.get("Name") == field_name:
                    val = item.get("Value", "")
                    try:
                        val = float(val)
                    except:
                        pass

                    if data_type == "数量":
                        qty_cell.value = val
                    elif data_type == "质量":
                        wt_cell.value = val
                    updated += 1
                    break
        h_val = wt_cell.value
        g_val = qty_cell.value
        if (h_val is not None and h_val != "") and (g_val is None or g_val == ""):
            qty_cell.value = 1

    print(f"✅ 已写入数量/单重，共更新 {updated} 项（含自动补1）")


# ✅ 获取材料密度（依赖两个数据库）
def get_material_density_from_merged(component_name, product_id):
    """
    针对【设备法兰紧固件】类元件：
    - component_name 形如：螺柱（外头盖法兰） / 螺母（管箱平盖）
    - 从【元件附加参数合并表】中读取 材料牌号1 / 2
    - 再去【材料库】查密度
    """

    try:
        import re
        import pymysql

        # ========= 1. 解析 component_name =========
        # 例：螺柱（外头盖法兰）
        m = re.match(r"(螺柱|螺母)[（(](.+?)[）)]", component_name)
        if not m:
            print(f"⚠️ 无法解析紧固件名称: {component_name}")
            return None

        fastener_type = m.group(1)  # 螺柱 / 螺母
        belong_part = m.group(2)  # 外头盖法兰 / 管箱平盖法兰 …

        # 材料牌号字段映射
        material_field = "材料牌号1" if fastener_type == "螺柱" else "材料牌号2"
        type_field = "元件类型1" if fastener_type == "螺柱" else "元件类型2"

        # ========= 2. 查 产品设计活动库（合并表） =========
        conn = pymysql.connect(
            host="localhost",
            user="root",
            password="123456",
            database="产品设计活动库",
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor
        )

        with conn.cursor() as cursor:
            cursor.execute(f"""
                SELECT 参数值
                FROM 产品设计活动表_元件附加参数合并表
                WHERE 产品ID = %s
                  AND 元件ID IN (
                        SELECT 元件ID
                        FROM 产品设计活动表_元件附加参数合并表
                        WHERE 产品ID = %s
                          AND 参数名称 = '元件名称'
                          AND 参数值 = '设备法兰紧固件'
                  )
                  AND (
                        (参数名称 = %s AND 参数值 = %s)
                        OR
                        (参数名称 = '元件所属' AND 参数值 LIKE %s)
                  )
            """, (
                product_id,
                product_id,
                type_field, fastener_type,
                f"%{belong_part}%"
            ))

            rows = cursor.fetchall()
            if not rows:
                return None

            # 再取材料牌号
            cursor.execute(f"""
                SELECT 参数值
                FROM 产品设计活动表_元件附加参数合并表
                WHERE 产品ID = %s
                  AND 元件ID IN (
                        SELECT 元件ID
                        FROM 产品设计活动表_元件附加参数合并表
                        WHERE 产品ID = %s
                          AND 参数名称 = '元件名称'
                          AND 参数值 = '设备法兰紧固件'
                  )
                  AND 参数名称 = %s
                LIMIT 1
            """, (product_id, product_id, material_field))

            row = cursor.fetchone()
            if not row:
                return None

            material = row["参数值"]

        # ========= 3. 查材料库 =========
        conn2 = pymysql.connect(
            host="localhost",
            user="root",
            password="123456",
            database="材料库",
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor
        )

        with conn2.cursor() as cursor2:
            cursor2.execute("""
                SELECT 材料密度
                FROM 材料密度表
                WHERE 材料牌号 = %s
                LIMIT 1
            """, (material,))
            row2 = cursor2.fetchone()
            if row2:
                return float(row2["材料密度"])

    except Exception as e:
        print(f"❌ 获取紧固件材料密度失败: {e}")

    return None


def get_material_density(component_name, product_id):
    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 参数值 FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = %s AND 参数名称 = '材料牌号' LIMIT 1
            """, (product_id, component_name))
            row = cursor.fetchone()
            if row:
                material = row["参数值"]

                conn2 = pymysql.connect(
                    host="localhost", user="root", password="123456",
                    database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
                )
                with conn2.cursor() as cursor2:
                    cursor2.execute("""
                        SELECT 材料密度 FROM 材料密度表 WHERE 材料牌号 = %s LIMIT 1
                    """, (material,))
                    row2 = cursor2.fetchone()
                    if row2:
                        return float(row2["材料密度"])
    except Exception as e:
        print(f"❌ 获取材料密度失败: {e}")
    return None


def calc_yanban_mass(rho, delta, D, h, unit="mm"):
    """
    堰板质量计算公式：

    M = ρ * δ * (D/2)^2 *
        [π - arccos((h - D/2)/(D/2))
         + ((h - D/2)/(D/2)) * sqrt(1 - ((h - D/2)/(D/2))^2)]

    参数：
    rho   : 堰板密度
            如果 unit="mm"，建议 rho 使用 kg/m³
            如果 unit="m"， rho 使用 kg/m³
    delta : 堰板厚度
    D     : 壳体公称直径
    h     : 堰板高度
    unit  : "mm" 或 "m"

    返回：
    M : 堰板质量，单位 kg
    """

    # ===== 空值防崩：任一必要参数缺失时跳过本元件质量计算 =====
    def _to_required_float(value, param_name):
        if value is None:
            print(f"⚠️ 堰板质量计算跳过：{param_name} 为 None")
            return None
        s = str(value).strip()
        if s == "" or s.lower() in ("none", "null", "nan"):
            print(f"⚠️ 堰板质量计算跳过：{param_name} 为空")
            return None
        try:
            return float(s)
        except (TypeError, ValueError):
            print(f"⚠️ 堰板质量计算跳过：{param_name}={value!r} 不是有效数字")
            return None

    rho = _to_required_float(rho, "材料密度")
    delta = _to_required_float(delta, "堰板厚度")
    D = _to_required_float(D, "圆筒公称直径")
    h = _to_required_float(h, "堰板高度")

    if None in (rho, delta, D, h):
        return None

    if D <= 0:
        return 0.0

    if delta <= 0:
        return 0.0

    # 半径
    R = D / 2.0

    # 限制 h 的范围，避免超出 arccos 和 sqrt 的定义域
    if h <= 0:
        area = 0.0
    elif h >= D:
        area = math.pi * R ** 2
    else:
        x = (h - R) / R

        # 防止浮点误差导致 x 超过 [-1, 1]
        x = max(-1.0, min(1.0, x))

        bracket = (
                math.pi
                - math.acos(x)
                + x * math.sqrt(1.0 - x ** 2)
        )

        area = R ** 2 * bracket

    # 体积 = 面积 * 厚度
    volume = area * delta

    # 如果 D、h、delta 用的是 mm，则 volume 是 mm³
    # ρ 如果是 kg/m³，需要乘 1e-9 转换
    if unit == "mm":
        mass = rho * volume * 1e-9
    else:
        mass = rho * volume

    return mass


def fill_special_items(sheet, jisuan_data, product_id):
    import re
    pipe_data = {}
    pipe_input_data = {}
    conn = pymysql.connect(
        host="localhost", user="root", password="123456",
        database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
    )
    cursor = conn.cursor()

    # 读取布管结果表
    sql_result = """
                SELECT `key`, `value` 
                FROM 产品设计活动表_布管结果表
                WHERE 产品ID = %s
            """
    cursor.execute(sql_result, (product_id,))
    rows = cursor.fetchall()
    pipe_data.clear()
    for row in rows:
        pipe_data[row["key"]] = row["value"]
    print("pip_data:", pipe_data)
    # 读取布管输入表
    sql_input = """
                SELECT `key`, `value` 
                FROM 产品设计活动表_布管输入表
                WHERE 产品ID = %s
            """
    cursor.execute(sql_input, (product_id,))
    rows = cursor.fetchall()
    pipe_input_data.clear()
    for row in rows:
        pipe_input_data[row["key"]] = row["value"]
    print("pipe_input_data:", pipe_input_data)
    cursor.close()

    def get_actual_diameter(dh):
        try:
            conn = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT 实际直径 FROM 螺栓直径对应表 WHERE 螺栓公称直径 = %s LIMIT 1
                """, (str(dh),))
                row = cursor.fetchone()
                if row:
                    return float(row["实际直径"])
        except Exception as e:
            print(f"❌ 获取实际直径失败: {e}")
        return None

    def get_ybgd_from_db(product_id):
        conn_yb = None
        try:
            conn_yb = get_connection(**db_config1)
            cursor_yb = conn_yb.cursor()
            sql = """
                SELECT 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = '堰板' AND 参数名称 = '堰板高度h'
            """
            cursor_yb.execute(sql, (product_id,))
            row = cursor_yb.fetchone()
            value = row.get("参数值") if isinstance(row, dict) else None

            if value is None or str(value).strip().lower() in ("", "none", "null", "nan"):
                print("⚠️ 堰板高度为空：跳过堰板重量计算")
                return None

            try:
                return float(value)
            except (TypeError, ValueError):
                print(f"⚠️ 堰板高度不是有效数字 {value!r}：跳过堰板重量计算")
                return None
        except Exception as e:
            print(f"⚠️ 获取堰板高度异常，已跳过：{e}")
            return None
        finally:
            try:
                if conn_yb:
                    conn_yb.close()
            except Exception:
                pass

    def get_ttgd_from_db(product_id):
        try:
            conn = get_connection(**db_config1)
            cursor = conn.cursor()
            sql = """
                SELECT 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管板凸台高度'
            """
            cursor.execute(sql, (product_id,))
            row = cursor.fetchone()
            conn.close()
            if row and "参数值" in row:
                return float(row["参数值"])
        except Exception as e:
            print(f"❌ 获取管板凸台高度失败: {e}")
        return 0  # 默认值为0，避免None参与计算出错

    def get_luozhu_length(data, product_id):
        # 先尝试获取管箱法兰
        dh = get_value(data, "管箱法兰", "螺栓公称直径")
        print(dh, "dh")

        # 如果没有，再尝试头盖法兰
        if dh is None:
            dh = get_value(data, "头盖法兰", "螺栓公称直径")
        print(dh, "dh after fallback")

        # 如果两个都没有，无法继续，dh_val = 0
        try:
            dh_val = int(re.search(r'\d+', str(dh)).group())
        except:
            dh_val = 0
        print(dh_val, "dh_val")

        flange_thk_1 = get_value(data, "管箱法兰", "法兰名义厚度") or 0
        if flange_thk_1 == 0:
            flange_thk_1 = get_value(data, "头盖法兰", "法兰名义厚度") or 0
        print(flange_thk_1, "flange_thk_1")

        gasket_thk_1 = get_value(data, "管箱法兰", "垫片厚度") or 0
        if gasket_thk_1 == 0:
            gasket_thk_1 = get_value(data, "头盖法兰", "垫片厚度") or 0
        print(gasket_thk_1, "gasket_thk_1")

        flange_thk_2 = get_value(data, "壳体法兰", "法兰名义厚度") or 0
        if flange_thk_2 == 0:
            flange_thk_2 = get_value(data, "管箱平盖", "法兰名义厚度") or 0
        print(flange_thk_2, "flange_thk_2")

        gasket_thk_2 = get_value(data, "壳体法兰", "垫片厚度") or 0
        if gasket_thk_2 == 0:
            gasket_thk_2 = get_value(data, "管箱平盖", "垫片厚度") or 0
        print(gasket_thk_2, "gasket_thk_2")

        ttgd = get_ttgd_from_db(product_id) or 0
        print(ttgd, "ttgd")

        value = 20 + 2 * dh_val + flange_thk_1 + gasket_thk_1 + flange_thk_2 + gasket_thk_2 - 2 * ttgd
        value = math.ceil(value / 5) * 5

        return value

    def get_value(data, section, name):
        dict_out = data.get("DictOutDatas") or {}
        for section_name, section_data in dict_out.items():
            if section_name != section:
                continue

            # ✅ 防御：section_data 可能是 None / 非 dict
            if not isinstance(section_data, dict):
                return None

            datas = section_data.get("Datas") or []  # ✅ 防御：Datas 可能是 None
            if not isinstance(datas, list):
                return None

            for item in datas:
                if not isinstance(item, dict):
                    continue
                if item.get("Name") == name:
                    v = item.get("Value", None)
                    if v is None:
                        return None
                    try:
                        return float(v)
                    except:
                        return v
        return None

    def count_valid_items(data, key):
        return len(data.get(key, [])) if isinstance(data.get(key, []), list) else 0

    def calc_slipway_mass(product_id, jisuan_output_data, density):
        # === 建立数据库连接 ===
        try:
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4"
            )
        except Exception as e:
            print(f"❌ 数据库连接失败: {e}")
            return None

        cursor = conn.cursor()

        # === 查询是否布置滑道（元件表） ===
        cursor.execute("""
            SELECT 是否布置滑道
            FROM 产品设计活动表_布管元件表
            WHERE 产品ID = %s
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        if not row:
            print("❌ 未找到是否布置滑道信息")
            return None

        is_slipway = row[0] if isinstance(row, (tuple, list)) else row.get("是否布置滑道")
        if not is_slipway or str(is_slipway) == "0":
            print("✅ 是否布置滑道 = 0，跳过计算")
            return None

        # === 滑道数量（1 → 2 个滑道） ===
        slipway_count = 1

        # === 查询滑道高度、厚度（参数表，按参数名） ===
        cursor.execute("""
            SELECT 参数名, 参数值
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 IN ('滑道高度', '滑道厚度')
        """, (product_id,))
        rows = cursor.fetchall()

        slipway_height, slipway_thick = None, None
        for r in rows:
            name, value = r if isinstance(r, (tuple, list)) else (r["参数名"], r["参数值"])
            if name == "滑道高度":
                slipway_height = value
            elif name == "滑道厚度":
                slipway_thick = value

        # === 转换数值，单位 mm → m ===
        try:
            slipway_height = float(slipway_height) / 1000.0
            slipway_thick = float(slipway_thick) / 1000.0
        except (TypeError, ValueError):
            print("❌ 滑道高度/厚度无效")
            return None

        if not slipway_height or not slipway_thick:
            print("❌ 滑道高度或厚度为 0")
            return None

        # === 从 jisuan_output_data 获取滑道长度 ===
        slipway_length = None
        try:
            dict_out = jisuan_output_data.get("DictOutDatas", {})
            for key in ["管束", "浮头管束"]:
                datas = dict_out.get(key, {}).get("Datas", [])
                for item in datas:
                    if item.get("Name") == "滑道长度":
                        slipway_length = float(item.get("Value", 0)) / 1000
                        break
                if slipway_length:
                    break
        except Exception as e:
            print(f"❌ 获取滑道长度失败: {e}")
            return None

        if not slipway_length:
            print("❌ 滑道长度无效")
            return None

        # === 计算质量 ===
        try:
            volume = slipway_length * slipway_height * slipway_thick  # 单个滑道体积
            mass = volume * density * slipway_count  # 总质量
            return round(mass, 2)
        except Exception as e:
            print(f"❌ 质量计算失败: {e}")
            return None
        finally:
            cursor.close()
            conn.close()

    denisty_huadao = get_material_density("滑道", product_id)
    print("denisty_huadao", denisty_huadao)
    slipway_mass = calc_slipway_mass(product_id, jisuan_data, denisty_huadao)
    print("slipway_mass", slipway_mass)

    def calc_weight(R_mm, thickness_mm, density):
        try:
            R_m = float(R_mm) / 2000  # 直径/2并转米
            t_m = float(thickness_mm) / 1000
            return round(math.pi * R_m ** 2 * t_m * density, 2)
        except Exception as e:
            print(f"❌ 计算质量失败: {e}")
            return None

    def get_param(datas, name, default=0):
        """
        最小修复：当 datas 为 None 或不可迭代时返回 default（默认 "0"）
        """
        if datas is None:
            return default

        try:
            for item in datas:
                if isinstance(item, dict) and item.get("Name") == name:
                    return item.get("Value", default)
        except TypeError:
            # datas 不是可迭代对象
            return default

        return default

    # === 基础数据获取 ===
    def get_bolt_qty(jisuan_data, section_name):
        try:
            datas = jisuan_data.get("DictOutDatas", {}).get(section_name, {}).get("Datas")
            if not isinstance(datas, list):
                return 0  # 防止 None 或其他类型引发错误

            for item in datas:
                if item.get("Name") == "螺栓数量":
                    val = str(item.get("Value", "0")).strip()
                    # 处理带单位的情况，例如 "12.0个"
                    import re
                    m = re.search(r"[\d.]+", val)
                    if m:
                        return int(float(m.group()))
                    return 0
        except Exception:
            return 0
        return 0

    # === 调用 ===
    luozhu_qty = get_bolt_qty(jisuan_data, "管箱法兰")
    luozhu_qty2 = get_bolt_qty(jisuan_data, "管箱平盖")
    luozhu_qty3 = get_bolt_qty(jisuan_data, "浮头法兰")
    luozhu_qty4 = get_bolt_qty(jisuan_data, "外头盖法兰")

    guanshu_datas = jisuan_data.get("DictOutDatas", {}).get("管束", {}).get("Datas", [])
    baffle_R = get_param(guanshu_datas, "折流板/支持板外直径")
    baffle_t = get_param(guanshu_datas, "折流板厚度")
    support_R = get_param(guanshu_datas, "折流板/支持板外直径")
    if support_R == 0:
        support_R = get_param(guanshu_datas, "支持板外直径")
    support_t = get_param(guanshu_datas, "支持板厚度")

    saddle_data = jisuan_data.get("DictOutDatas", {}).get("鞍座", {}).get("Datas", [])
    saddle_mass = get_param(saddle_data, "鞍式支座质量")
    print("saddle_mass", saddle_mass)
    saddle_mass = float(saddle_mass) if saddle_mass not in (None, "", "None") else None

    uhx_data = jisuan_data.get("DictOutDatas", {}).get("固定管板", {}).get("Datas", [])
    uhx_mass = get_param(uhx_data, "单根换热管重量kg")
    uhx_mass = float(uhx_mass) if uhx_mass not in (None, "", "None") else None

    # 使用时
    tie_list1 = get_tie_rods_length2(product_id, conn)
    tie_list = get_tie_rods_length(product_id, conn)
    print("tie_list", tie_list)
    # === 公称直径 DN ===
    dn_value = None

    try:
        conn1 = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        with conn1.cursor() as cursor:
            cursor.execute("""
                SELECT 管程数值 FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s AND 参数名称 = '公称直径*' LIMIT 1
            """, (product_id,))
            row = cursor.fetchone()
            if row and row.get("管程数值"):
                dn_value = float(row["管程数值"])
            print(dn_value)
        conn1.close()
    except:
        pass

    qty = None
    if dn_value:
        try:
            conn2 = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="配置库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            with conn2.cursor() as cursor:
                cursor.execute("SELECT value FROM user_config WHERE id = 2.16")
                row = cursor.fetchone()
                if row:
                    config = eval(row["value"])
                    values = config[1][1:]
                    if dn_value < 800:
                        qty = values[0]
                    elif 800 <= dn_value <= 2000:
                        qty = values[1]
                    else:
                        qty = values[2]
            conn2.close()
        except:
            pass

    def get_slipway_count(product_id):
        conn = None
        cursor = None
        try:
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4"
            )
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 是否布置滑道
                FROM 产品设计活动表_布管元件表
                WHERE 产品ID = %s
                LIMIT 1
            """, (product_id,))
            row = cursor.fetchone()
            if not row:
                return 0  # 未找到数据就认为没有滑道

            is_slipway = row[0]
            if not is_slipway or str(is_slipway) == "0":
                return 0
            elif str(is_slipway) == "1":
                return 2  # 1代表布置，数量为2
            else:
                return 2  # 其他情况默认1个滑道

        except Exception as e:
            print(f"❌ 查询滑道数量失败: {e}")
            return 0
        finally:
            cursor.close()
            conn.close()

    quantity_map = {
        # 圆筒不拆分，数量固定为1。
        "圆筒": 1,
        # 原“封头”代表前后两个封头；cunguige.py 会拆成两行并各自固定为1。
        "封头": 2,
        "拉杆": tie_list1,
        "滑道": get_slipway_count(product_id),
        "定距管": tie_list1,
        "螺母（拉杆）": tie_list,
        "管箱侧垫片": 1,
        "外头盖垫片": 1,
        "前端管箱平盖垫片": 1,
        "固定管板": 1,
        "平盖垫片": 1,
        "管箱垫片": 1,
        "浮头法兰": 1,
        "浮头垫片": 1,
        "球冠形封头": 1,
        "浮动管板": 1,
        "铭牌板": 1,
        "铭牌支架": 1,
        "铭牌": 1,
        "顶板": 1,
        "管箱封头": 1,
        "后端管箱封头": 1,
        "锥壳": 1,
        "堰板": 1,
        "壳体小端圆筒": 1,
        "壳体大端圆筒": 1,
        "管箱法兰": 1,
        "接地装置": 2,
    }

    # ======================================================
    # ✨ 新增逻辑：若产品型式为 NEN → 更新多个元件数量为 2
    # ======================================================

    conn = pymysql.connect(
        host="localhost",
        user="root",
        password="123456",
        database="产品设计活动库",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 产品型式 
        FROM 产品设计活动表
        WHERE 产品ID = %s
    """, (product_id,))
    row = cursor.fetchone()

    if row and row["产品型式"] == "NEN":
        # 需要改为 2 的元件
        nen_items = ["管箱平盖", "平盖垫片", "头盖法兰", "固定管板"]

        for item in nen_items:
            quantity_map[item] = 2
    if row and row["产品型式"] == "BEM":
        em_items = ["管箱封头"]

        for item in em_items:
            quantity_map[item] = 1
        em_items2 = ["固定管板", "管箱法兰", "管箱垫片"]
        for item in em_items2:
            quantity_map[item] = 2
    if row and row["产品型式"] == "AEM":
        em_items = ["固定管板", "管箱法兰", "前端管箱平盖垫片", "管箱垫片"]

        for item in em_items:
            quantity_map[item] = 2

    mass_map = {
        "铭牌板": 0.8,
        "铭牌支架": 1,
        "管箱吊耳": "/",
        "吊耳": "/",
        "管箱垫片": "/",
        "管箱侧垫片": "/",
        "外头盖侧垫片": "/",
        "外头盖垫片": "/",
        "浮头垫片": '/',
        "防松支耳": 0.5,
        "铆钉": 0.02,
        '铭牌': 2,
        "前端管箱吊耳": "/",
        "后端管箱吊耳": "/",

    }
    mass_luozhu = None
    # === 遍历写入 Excel sheet ===
    for cells in iter_material_rows(sheet):
        row = _LegacyMaterialRow(cells)
        name = str(row[3].value).strip()
        print("name:", name)

        # === 1. 数量 ===
        if name in quantity_map:
            row[6].value = quantity_map[name]

        # === 2. 特殊件质量计算 ===
        if name == "滑道":
            if slipway_mass:
                row[7].value = slipway_mass
        elif name == "支撑板":
            row[6].value = 2
        elif name == "拉杆":
            # 数量
            row[6].value = tie_list1
            # === 查询滑道高度、厚度（参数表，按参数名） ===
            conn = None
            cursor = None

            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4"
            )
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 参数名, 参数值
                FROM 产品设计活动表_布管参数表
                WHERE 产品ID = %s AND 参数名 = %s
            """, (product_id, "拉杆直径"))
            rows = cursor.fetchall()

            dh_str = None
            for r in rows:
                name, value = r if isinstance(r, (tuple, list)) else (r["参数名"], r["参数值"])
                if name == "拉杆直径":
                    dh_str = value
            print("直径：", dh_str)
            # 直径
            dh_val = None
            if dh_str:
                try:
                    dh_val = int(str(dh_str).strip())
                except ValueError:
                    # 如果不是纯数字，再用正则匹配
                    match = re.search(r"M(\d+)", str(dh_str))
                    if match:
                        dh_val = int(match.group(1))

            R = dh_val

            # 长度
            dict_out = jisuan_data.get("DictOutDatas", {})
            datas = dict_out.get("管束", {}).get("Datas", []) \
                    or dict_out.get("浮头管束", {}).get("Datas", [])
            H1 = float(get_param(datas, "拉杆长度1")) or 0
            if H1 == 0:
                H1 = float(get_param(datas, "拉杆长度")) or 0
            H2 = float(get_param(datas, "拉杆长度2")) or 0
            H = max(H1, H2)

            # 密度
            density = get_material_density("拉杆", product_id)
            print("R:", R)
            print("H:", H)
            print("density:", density)

            # 质量
            if R and H and density:
                R_m = R / 1000
                H_m = float(H) / 1000
                mass = round((math.pi * R_m ** 2 / 4) * H_m * density, 2)
                row[7].value = mass


        elif name == "螺母（拉杆）":

            row[6].value = quantity_map.get("螺母（拉杆）", 0)

            # === 查询滑道高度、厚度（参数表，按参数名） ===

            cursor.execute("""

                SELECT 参数名, 参数值

                FROM 产品设计活动表_布管参数表

                WHERE 产品ID = %s AND 参数名 = %s

            """, (product_id, "拉杆直径"))
            rows = cursor.fetchall()
            dh_str = None
            for r in rows:
                name_r, value_r = r if isinstance(r, (tuple, list)) else (r["参数名"], r["参数值"])
                if name_r == "拉杆直径":
                    dh_str = value_r
            if dh_str:
                try:
                    dia = "M" + str(int(float(dh_str)))  # 10.0 -> 10
                except ValueError:
                    dia = "M" + str(dh_str)  # 出错时直接用原值
            else:
                dia = "M0"
            if dia:
                try:
                    conn3 = pymysql.connect(
                        host="localhost", user="root", password="123456",
                        database="材料库", charset="utf8mb4",
                        cursorclass=pymysql.cursors.DictCursor
                    )
                    with conn3.cursor() as cursor:
                        cursor.execute("""
                            SELECT `管法兰专用螺母`
                            FROM `螺母近似质量表`
                            WHERE 规格 = %s
                            LIMIT 1
                        """, (str(dia),))
                        row_m = cursor.fetchone()
                        if row_m and row_m.get("管法兰专用螺母"):
                            row[7].value = float(row_m["管法兰专用螺母"])
                    conn3.close()
                except Exception as e:
                    print("❌ 查询螺母质量失败:", e)

        elif name == "定距管":
            uhx_data = jisuan_data.get("DictOutDatas", {}).get("固定管板", {}).get("Datas", [])
            uhx_mass = get_param(uhx_data, "单根换热管重量kg")
            row[7].value = float(uhx_mass) if uhx_mass not in (None, "", "None") else None
        elif name == "堰板":
            uhx_data = jisuan_data.get("DictOutDatas", {}).get("管束", {}).get("Datas", [])
            yb_houdu = get_param(uhx_data, "堰板厚度", default=None)
            yb_gaodu = get_ybgd_from_db(product_id)
            uhx_data2 = jisuan_data.get("DictOutDatas", {}).get("大端壳体圆筒", {}).get("Datas", [])
            yb_D = get_param(uhx_data2, "圆筒公称直径", default=None)
            yb_denisty = get_material_density("堰板", product_id)

            uhx_mass = calc_yanban_mass(yb_denisty, yb_houdu, yb_D, yb_gaodu)
            if uhx_mass is None:
                row[7].value = None
                print("⏭️ 堰板参数不完整，已跳过堰板重量计算")
                continue

            row[7].value = float(uhx_mass)

        elif name == "挡管":
            print("➡ 进入挡管计算分支")  # 🔹 打印进入分支

            # === 1) 数量：直接读取元件数量（元件类型=2） ===
            qty = 0
            try:
                conn_tmp = pymysql.connect(
                    host="localhost",
                    port=3306,
                    user="root",
                    password="123456",
                    database="产品设计活动库",
                    charset="utf8mb4"
                )
                cur_tmp = conn_tmp.cursor()
                cur_tmp.execute(
                    """
                    SELECT 元件数量
                    FROM 产品设计活动表_布管元件表
                    WHERE 产品ID = %s AND 元件类型 = 2
                    """,
                    (product_id,)
                )
                rows = cur_tmp.fetchall() or []

                # 直接求和
                for row_item in rows:
                    val = row_item[0] if isinstance(row_item, (tuple, list)) else row_item.get("元件数量", 0)
                    if val is not None:
                        try:
                            qty += float(val)
                        except ValueError:
                            continue

                print(f"挡管 元件数量: {qty}")

            except Exception as e:
                print(f"❌ 从布管元件表获取挡管(类型2)数量失败: {e}")
            finally:
                try:
                    conn_tmp.close()
                except Exception:
                    pass

            # 写入数量（仍保留 /2 的逻辑）
            row[6].value = qty
            # === 2) 质量算法（保持原逻辑：单根重量，不乘数量） ===
            uhx_data = jisuan_data.get("DictOutDatas", {}).get("固定管板", {}).get("Datas", [])
            uhx_mass = get_param(uhx_data, "单根换热管重量kg")

            try:
                row[7].value = float(uhx_mass) if uhx_mass not in (None, "", "None") else None
                print(f"计算挡管质量(单根): {row[7].value} kg")
            except Exception as e:
                row[7].value = None
                print(f"❌ 计算挡管质量失败: {e}")

        elif name == "分程隔板":
            fencheng = None

            conn1 = pymysql.connect(
                host="localhost",
                port=3306,
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4"
            )
            cursor3 = conn1.cursor()
            cursor3.execute("""
                            SELECT 参数名, 参数值
                            FROM 产品设计活动表_布管参数表
                            WHERE 产品ID = %s AND 参数名 = %s
                        """, (product_id, "管程程数"))
            rows = cursor3.fetchall()

            for r in rows:
                name, value = r if isinstance(r, (tuple, list)) else (r["参数名"], r["参数值"])
                print(name)
                print(value)
                if name == "管程程数":
                    fencheng = str(value).strip()  # 🔹 转成字符串，避免数字/字符串不一致
            print("管程程数：", fencheng)
            # ✅ 判断逻辑
            if fencheng == "1":
                row[6].value = 0
                # TODO: 这里写 1 管程逻辑
            elif fencheng == "2":
                row[6].value = 1

                # TODO: 这里写 2 管程逻辑
            elif fencheng == "4":
                row[6].value = 2

                # TODO: 这里写 4 管程逻辑
            elif fencheng == "6":
                row[6].value = 3

        elif name == "铭牌板":
            row[7].value = 0.8
        elif name == "铭牌":
            row[7].value = 2
        elif name == "铭牌支架":
            row[7].value = 1

        elif name in {"管箱吊耳", "吊耳", "前端管箱吊耳", "后端管箱吊耳", "管箱垫片", "管箱侧垫片", "外头盖侧垫片",
                      "外头盖垫片", "平盖垫片", "前端管箱平盖垫片"}:
            row[7].value = "/"
        elif name == "防冲板":
            print("➡ 进入防冲板计算分支")  # 🔹 打印进入分支

            # === 1) 数量：直接读取元件数量（元件类型=1） ===
            qty = 0
            try:
                conn_tmp = pymysql.connect(
                    host="localhost",
                    port=3306,
                    user="root",
                    password="123456",
                    database="产品设计活动库",
                    charset="utf8mb4"
                )
                cur_tmp = conn_tmp.cursor()
                cur_tmp.execute(
                    """
                    SELECT 元件数量
                    FROM 产品设计活动表_布管元件表
                    WHERE 产品ID = %s AND 元件类型 in (5,6)
                    """,
                    (product_id,)
                )
                rows_tmp = cur_tmp.fetchall() or []

                for r in rows_tmp:
                    val = r[0] if isinstance(r, (tuple, list)) else r.get("元件数量", 0)
                    if val not in (None, '', 'None'):
                        try:
                            qty += float(val)
                        except ValueError:
                            continue
                print(f"防冲板 元件数量: {qty}")

            except Exception as e:
                print(f"❌ 从布管元件表获取防冲板数量失败: {e}")
            finally:
                try:
                    conn_tmp.close()
                except Exception:
                    pass

            # 写入数量到 Excel 行（row 仍为 Excel 行对象）
            row[6].value = qty

            # === 2) 获取防冲板厚度和宽度 ===
            thickness_mm = 0.0
            width_mm_val = 0.0
            try:
                conn_param = pymysql.connect(
                    host="localhost",
                    port=3306,
                    user="root",
                    password="123456",
                    database="产品设计活动库",
                    charset="utf8mb4"
                )
                cur_param = conn_param.cursor()

                # 厚度
                cur_param.execute(
                    "SELECT 参数值 FROM 产品设计活动表_布管参数表 "
                    "WHERE 产品ID=%s AND 参数名=%s LIMIT 1",
                    (product_id, "防冲板厚度")
                )
                row_thick = cur_param.fetchone()
                if row_thick and row_thick[0] not in (None, '', 'None'):
                    try:
                        thickness_mm = float(row_thick[0])
                    except Exception:
                        try:
                            import ast
                            thickness_mm = float(ast.literal_eval(str(row_thick[0])))
                        except Exception:
                            thickness_mm = 0.0
                print(f"厚度 thickness_mm = {thickness_mm}")

                # 宽度
                cur_param.execute(
                    "SELECT 参数值 FROM 产品设计活动表_布管参数表 "
                    "WHERE 产品ID=%s AND 参数名=%s LIMIT 1",
                    (product_id, "防冲板宽度")
                )
                row_width = cur_param.fetchone()
                if row_width and row_width[0] not in (None, '', 'None'):
                    try:
                        width_mm_val = abs(float(row_width[0]))
                    except Exception as e:
                        print(f"转换防冲板宽度失败: {e}")
                        width_mm_val = 0.0
                print(f"宽度 width_mm_val = {width_mm_val}")

            except Exception as e:
                print(f"❌ 读取防冲板参数失败: {e}")
            finally:
                try:
                    conn_param.close()
                except Exception:
                    pass

            # === 3) 获取拉杆长度 ===
            length_m = 0.0
            try:
                conn_len = pymysql.connect(
                    host="localhost",
                    port=3306,
                    user="root",
                    password="123456",
                    database="产品设计活动库",
                    charset="utf8mb4"
                )
                cur_len = conn_len.cursor(pymysql.cursors.DictCursor)
                cur_len.execute(
                    "SELECT Value FROM 产品设计活动表_元件计算结果表 "
                    "WHERE 产品ID=%s AND Name='防冲挡板与入口接管横截面平行的矩形（轴向）边长' LIMIT 1",
                    (product_id,)
                )

                row_len = cur_len.fetchone()
                if row_len and row_len.get("Value") not in (None, '', 'None'):
                    try:
                        size_val = float(str(row_len["Value"]).strip())
                        length_m = size_val
                    except Exception:
                        length_m = 0.0
                print(f"拉杆长度 length_m = {length_m} m")
            except Exception as e:
                print(f"❌ 获取拉杆长度失败: {e}")
            finally:
                try:
                    conn_len.close()
                except Exception:
                    pass

            # === 4) 获取密度 ===
            try:
                density = get_material_density("防冲板", product_id)  # kg/m³
            except Exception:
                density = 0.0
            print(f"防冲板密度 density = {density}")

            # === 5) 计算质量并写入 Excel ===
            if qty > 0 and thickness_mm > 0 and width_mm_val > 0 and length_m > 0:
                try:
                    volume_m3 = (thickness_mm / 1000) * (width_mm_val / 1000) * length_m / 1000  # m³
                    mass = volume_m3 * density
                    row[7].value = round(mass, 2)
                    print(f"计算防冲板质量 mass = {row[7].value} kg")
                except Exception as e:
                    row[7].value = 0.0
                    print(f"❌ 计算防冲板质量失败: {e}")
            else:
                row[7].value = 0.0
                print("条件不满足，防冲板质量置 0")

        elif name == "U形换热管":
            # uhx_data = jisuan_data.get("DictOutDatas", {}).get("固定管板", {}).get("Datas", [])
            # uhx_mass = get_param(uhx_data, "单根换热管重量kg")
            # row[7].value = float(uhx_mass) if uhx_mass not in (None, "", "None") else None
            row[7].value = "见U形管明细工作表"
        elif name == "旁路挡板":
            print("➡ 进入旁路挡板计算分支")  # 🔹 打印进入分支

            # === 1) 数量：直接读取元件数量（元件类型=2） ===
            qty = 0
            try:
                conn_tmp = pymysql.connect(
                    host="localhost",
                    port=3306,
                    user="root",
                    password="123456",
                    database="产品设计活动库",
                    charset="utf8mb4"
                )
                cur_tmp = conn_tmp.cursor()
                cur_tmp.execute(
                    """
                    SELECT 元件数量
                    FROM 产品设计活动表_布管元件表
                    WHERE 产品ID = %s AND 元件类型 = 3
                    """,
                    (product_id,)
                )
                rows = cur_tmp.fetchall() or []

                # 直接求和
                for row_item in rows:
                    val = row_item[0] if isinstance(row_item, (tuple, list)) else row_item.get("元件数量", 0)
                    if val is not None:
                        try:
                            qty += float(val)
                        except ValueError:
                            continue

                print(f"挡管 元件数量: {qty}")

            except Exception as e:
                print(f"❌ 从布管元件表获取挡管(类型2)数量失败: {e}")
            finally:
                try:
                    conn_tmp.close()
                except Exception:
                    pass

            # 写入数量（仍保留 /2 的逻辑）
            row[6].value = qty

            # --- 获取旁路挡板厚度和宽度 ---
            thickness_mm = 0.0
            width_mm_val = 0.0
            try:
                conn = pymysql.connect(
                    host="localhost",
                    port=3306,
                    user="root",
                    password="123456",
                    database="产品设计活动库",
                    charset="utf8mb4"
                )
                cur = conn.cursor()

                # 厚度
                cur.execute(
                    "SELECT 参数值 FROM 产品设计活动表_布管参数表 "
                    "WHERE 产品ID=%s AND 参数名=%s LIMIT 1",
                    (product_id, "旁路挡板厚度")
                )
                row_param = cur.fetchone()
                print(f"数据库查询旁路挡板厚度: {row_param}")
                if row_param and row_param[0] is not None:
                    try:
                        thickness_mm = float(row_param[0])
                    except Exception:
                        try:
                            thickness_mm = float(ast.literal_eval(str(row_param[0])))
                        except Exception:
                            thickness_mm = 0.0
                print(f"厚度 thickness_mm = {thickness_mm}")

                # 宽度
                try:
                    # 从「产品设计活动表_旁路挡板表」读取所有宽度
                    cur.execute(
                        """
                        SELECT 宽度
                        FROM 产品设计活动表_布管旁路挡板表
                        WHERE 产品ID = %s
                        """,
                        (product_id,)
                    )

                    rows = cur.fetchall()
                    print(f"数据库查询旁路挡板宽度 rows: {rows}")

                    width_values = []

                    for row_item in rows:  # ✅ 不再覆盖 Excel 的 row
                        val = row_item[0]

                        if val in (None, "", "None", "程序推荐"):
                            continue

                        try:
                            num = abs(float(val))
                            width_values.append(num)
                            continue
                        except Exception:
                            pass

                        try:
                            parsed = ast.literal_eval(str(val))
                            if isinstance(parsed, (list, tuple)) and parsed:
                                width_values.append(abs(float(parsed[0])))
                            elif isinstance(parsed, (int, float)):
                                width_values.append(abs(float(parsed)))
                        except Exception as e:
                            print(f"旁路挡板宽度解析失败，val={val}, err={e}")

                    width_mm_val = max(width_values) if width_values else 0.0
                    print(f"✅ 旁路挡板最大宽度 width_mm_val = {width_mm_val}")

                except Exception as e:
                    print(f"❌ 读取旁路挡板参数失败: {e}")

            finally:
                conn.close()

            # --- 获取拉杆长度 ---
            pipe_datas = jisuan_data.get("DictOutDatas", {}).get("管束", {}).get("Datas", []) \
                         or jisuan_data.get("DictOutDatas", {}).get("浮头管束", {}).get("Datas", [])
            print(f"管束数据: {pipe_datas}")

            H1 = get_param(pipe_datas, "拉杆长度1") or 0
            if H1 == 0:
                H1 = get_param(pipe_datas, "拉杆长度")
            H2 = get_param(pipe_datas, "拉杆长度2") or 0
            print(f"H1={H1}, H2={H2}")
            try:
                length_m = max(float(H1 or 0), float(H2 or 0)) / 1000.0
            except Exception:
                length_m = 0.0
            print(f"拉杆长度 length_m = {length_m} m")

            # --- 获取密度 ---
            try:
                density = get_material_density("旁路挡板", product_id)  # kg/m³
            except Exception:
                density = 0.0
            print(f"旁路挡板密度 density = {density}")

            # --- 计算第一个挡板质量（单片质量，不乘数量） ---
            if qty > 0 and thickness_mm > 0 and width_mm_val > 0 and length_m > 0:
                try:
                    volume = (thickness_mm / 1000.0) * (width_mm_val / 1000.0) * length_m
                    mass = volume * density
                    row[7].value = round(mass, 2)
                    print(f"计算旁路挡板质量 mass = {row[7].value} kg")
                except Exception as e:
                    print(f"❌ 计算旁路挡板质量失败: {e}")
            else:
                row[7].value = 0.0
                print("条件不满足，旁路挡板质量置 0")


        elif name == "内折流板":

            try:

                datas = jisuan_data.get("DictOutDatas", {}).get("浮头管束", {}).get("Datas", [])

                n_fixed = get_param(datas, "固定管板侧内折流板数量") or 0

                n_float = get_param(datas, "浮动管板侧内折流板数量") or 0

                row[6].value = int(n_fixed) + int(n_float)

            except Exception as e:

                print(f"❌ 计算内折流板数量失败: {e}")

        elif name == "弓形折流板" or name == "弓形折流板Ⅰ" or name == "弓形折流板Ⅱ":

            try:

                datas = jisuan_data.get("DictOutDatas", {}).get("浮头管束", {}).get("Datas", [])

                n_fixed = get_param(datas, "弓形折流板数量") or 0

                row[6].value = int(n_fixed)

            except Exception as e:

                print(f"❌ 计算弓形折流板数量失败: {e}")

        elif name == "异形折流板":

            try:

                datas = jisuan_data.get("DictOutDatas", {}).get("浮头管束", {}).get("Datas", [])

                n_fixed = get_param(datas, "异形折流板数量") or 0

                row[6].value = int(n_fixed)

            except Exception as e:

                print(f"❌ 计算异形折流板数量失败: {e}")

        elif name == "内导流筒":

            try:

                datas = jisuan_data.get("DictOutDatas", {}).get("浮头管束", {}).get("Datas", [])

                n_fixed = get_param(datas, "导流筒数量") or 0

                row[6].value = int(n_fixed)

            except Exception as e:

                print(f"❌ 计算导流筒数量失败: {e}")

        elif name == "中间挡板":
            print("➡ 进入中间挡板计算分支")  # 🔹

            # === 1) 数量：直接读取元件数量（元件类型=2） ===
            qty = 0
            try:
                conn_tmp = pymysql.connect(
                    host="localhost",
                    port=3306,
                    user="root",
                    password="123456",
                    database="产品设计活动库",
                    charset="utf8mb4"
                )
                cur_tmp = conn_tmp.cursor()
                cur_tmp.execute(
                    """
                    SELECT 元件数量
                    FROM 产品设计活动表_布管元件表
                    WHERE 产品ID = %s AND 元件类型 = 4
                    """,
                    (product_id,)
                )
                rows = cur_tmp.fetchall() or []

                # 直接求和
                for row_item in rows:
                    val = row_item[0] if isinstance(row_item, (tuple, list)) else row_item.get("元件数量", 0)
                    if val is not None:
                        try:
                            qty += float(val)
                        except ValueError:
                            continue

                print(f"挡管 元件数量: {qty}")

            except Exception as e:
                print(f"❌ 从布管元件表获取挡管(类型2)数量失败: {e}")
            finally:
                try:
                    conn_tmp.close()
                except Exception:
                    pass

            # 写入数量（仍保留 /2 的逻辑）
            row[6].value = qty

            # === 2) 质量算法保持原逻辑（尺寸来自参数表，乘以 qty） ===
            thickness_mm = 0.0
            width_mm = 0.0
            try:
                conn = pymysql.connect(
                    host="localhost",
                    port=3306,
                    user="root",
                    password="123456",
                    database="产品设计活动库",
                    charset="utf8mb4"
                )
                cur = conn.cursor()

                # 厚度
                cur.execute(
                    "SELECT 参数值 FROM 产品设计活动表_布管参数表 "
                    "WHERE 产品ID=%s AND 参数名=%s LIMIT 1",
                    (product_id, "中间挡板厚度")
                )
                row_param = cur.fetchone()
                if row_param and row_param[0] is not None:
                    try:
                        thickness_mm = float(row_param[0])
                    except Exception:
                        try:
                            thickness_mm = float(ast.literal_eval(str(row_param[0])))
                        except Exception:
                            thickness_mm = 0.0
                print(f"中间挡板厚度 thickness_mm = {thickness_mm}")

                # 宽度
                cur.execute(
                    "SELECT 参数值 FROM 产品设计活动表_布管参数表 "
                    "WHERE 产品ID=%s AND 参数名=%s LIMIT 1",
                    (product_id, "中间挡板宽度")
                )
                row_param = cur.fetchone()
                if row_param and row_param[0] is not None:
                    try:
                        width_mm = float(row_param[0])
                    except Exception:
                        try:
                            width_mm = float(ast.literal_eval(str(row_param[0])))
                        except Exception:
                            width_mm = 0.0
                print(f"中间挡板宽度 width_mm = {width_mm}")

                # 长度（来自 jisuan_data，单位 mm；无“管束”则回退“浮头管束”）
                pipe_datas = (
                        jisuan_data.get("DictOutDatas", {}).get("管束", {}).get("Datas", [])
                        or jisuan_data.get("DictOutDatas", {}).get("浮头管束", {}).get("Datas", [])
                )
                mid_baffle_length = get_param(pipe_datas, "中间挡管/挡板长度")
                length_m = float(mid_baffle_length) / 1000.0 if mid_baffle_length else 0.0

                # 密度（按“中间挡板”查）
                density = get_material_density("中间挡板", product_id)  # kg/m³

                # 体积（m³/件）与总质量（kg）
                volume_per = (thickness_mm / 1000.0) * (width_mm / 1000.0) * length_m
                total_mass = volume_per * density
                row[7].value = round(total_mass, 2)
                print(f"中间挡板：t={thickness_mm} mm, w={width_mm} mm, L={length_m} m, ρ={density} kg/m³, "
                      f"qty={qty}, mass={row[7].value} kg")

            except Exception as e:
                print(f"❌ 计算中间挡板质量失败: {e}")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        elif name == "螺柱（外头盖法兰）" and luozhu_qty4:

            row[6].value = luozhu_qty4

            dh = get_value(jisuan_data, "外头盖法兰", "螺栓公称直径")

            R = get_actual_diameter(dh)

            H = get_luozhu_length(jisuan_data, product_id)

            density = get_material_density_from_merged("螺柱（外头盖法兰）", product_id)

            print("R", R)

            print("H", H)

            print("density", density)

            if R and H and density:
                mass_luozhu = round((math.pi * (R / 1000) ** 2 / 4) * (H / 1000) * density, 2)

                row[7].value = mass_luozhu
        elif name == "螺母（外头盖法兰）" and luozhu_qty4:

            row[6].value = luozhu_qty4 * 2

            # === 获取公称直径，查找质量 ===

            dia = get_value(jisuan_data, "外头盖法兰", "螺栓公称直径")

            if dia:

                try:

                    conn3 = pymysql.connect(

                        host="localhost", user="root", password="123456",

                        database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

                    )

                    with conn3.cursor() as cursor:

                        cursor.execute("""

                            SELECT `管法兰专用螺母` 

                            FROM `螺母近似质量表`

                            WHERE 规格 = %s

                            LIMIT 1

                        """, (str(dia),))

                        row_m = cursor.fetchone()

                        if row_m and row_m.get("管法兰专用螺母"):
                            mass_per_unit = float(row_m["管法兰专用螺母"])

                            row[7].value = mass_per_unit

                    conn3.close()

                except Exception as e:

                    print(f"❌ 查询螺母质量失败: {e}")

        elif name == "螺柱（管箱法兰）" and luozhu_qty:
            qty = 0
            dn_value = None
            trigger = False
            conn1 = pymysql.connect(

                host="localhost", user="root", password="123456",

                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

            )

            with conn1.cursor() as cursor:

                cursor.execute("""
                                SELECT 管程数值 FROM 产品设计活动表_设计数据表
                                  WHERE 产品ID = %s AND 参数名称 = '公称直径*' LIMIT 1
                                 """, (product_id,))

                roww = cursor.fetchone()

                if roww and roww.get("管程数值"):
                    dn_value = float(roww["管程数值"])

                cursor.execute("""
                    SELECT 产品型式 
                    FROM 产品设计活动表
                    WHERE 产品ID = %s
                """, (product_id,))
                product_info = cursor.fetchone()

                if product_info and product_info["产品型式"] not in ("NEN", "AEM", "BEM"):
                    trigger = True
                elif product_info and product_info["产品型式"] in ("BEM"):
                    luozhu_qty = luozhu_qty * 2
            if dn_value and trigger == True:

                try:

                    conn2 = pymysql.connect(

                        host="localhost", user="root", password="123456",

                        database="配置库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

                    )

                    with conn2.cursor() as cursor:

                        cursor.execute("SELECT value FROM user_config WHERE id = 2.16")

                        roww = cursor.fetchone()

                        if roww:

                            config = eval(roww["value"])

                            values = config[1][1:]

                            if dn_value < 800:

                                qty = values[0]

                            elif 800 <= dn_value <= 2000:

                                qty = values[1]

                            else:

                                qty = values[2]

                    conn2.close()

                except:

                    pass

            luozhu_qty_guanxiangfalan = int(luozhu_qty) - int(qty)
            row[6].value = int(luozhu_qty_guanxiangfalan)

            dh = get_value(jisuan_data, "管箱法兰", "螺栓公称直径")

            R = get_actual_diameter(dh)

            H = get_luozhu_length(jisuan_data, product_id)

            density = get_material_density_from_merged("螺柱（管箱法兰）", product_id)

            print("R", R)

            print("H", H)

            print("density", density)

            if R and H and density:
                mass_luozhu = round((math.pi * (R / 1000) ** 2 / 4) * (H / 1000) * density, 2)

                row[7].value = mass_luozhu
            print("mass_luozhu", mass_luozhu)
        elif name == "螺柱（前端管箱法兰）" and luozhu_qty:
            qty = 0
            dn_value = None
            trigger = False
            conn1 = pymysql.connect(

                host="localhost", user="root", password="123456",

                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

            )

            with conn1.cursor() as cursor:

                cursor.execute("""
                                                        SELECT 管程数值 FROM 产品设计活动表_设计数据表
                                                          WHERE 产品ID = %s AND 参数名称 = '公称直径*' LIMIT 1
                                                         """, (product_id,))

                roww = cursor.fetchone()

                if roww and roww.get("管程数值"):
                    dn_value = float(roww["管程数值"])

                cursor.execute("""
                                            SELECT 产品型式 
                                            FROM 产品设计活动表
                                            WHERE 产品ID = %s
                                        """, (product_id,))
                product_info = cursor.fetchone()

                if product_info and product_info["产品型式"] not in ("NEN", "AEM", "BEM"):
                    trigger = True
            if dn_value and trigger == True:

                try:

                    conn2 = pymysql.connect(

                        host="localhost", user="root", password="123456",

                        database="配置库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

                    )

                    with conn2.cursor() as cursor:

                        cursor.execute("SELECT value FROM user_config WHERE id = 2.16")

                        roww = cursor.fetchone()

                        if roww:

                            config = eval(roww["value"])

                            values = config[1][1:]

                            if dn_value < 800:

                                qty = values[0]

                            elif 800 <= dn_value <= 2000:

                                qty = values[1]

                            else:

                                qty = values[2]

                    conn2.close()

                except:

                    pass

            luozhu_qty_guanxiangfalan = int(luozhu_qty) - int(qty)
            row[6].value = int(luozhu_qty_guanxiangfalan)

            dh = get_value(jisuan_data, "管箱法兰", "螺栓公称直径")

            R = get_actual_diameter(dh)

            H = get_luozhu_length(jisuan_data, product_id)

            density = get_material_density_from_merged("螺柱（管箱法兰）", product_id)

            print("R", R)

            print("H", H)

            print("density", density)

            if R and H and density:
                mass_luozhu = round((math.pi * (R / 1000) ** 2 / 4) * (H / 1000) * density, 2)

                row[7].value = mass_luozhu
            print("mass_luozhu", mass_luozhu)
        elif name == "螺柱（后端管箱封头）" and luozhu_qty:
            qty = 0
            dn_value = None
            trigger = False
            conn1 = pymysql.connect(

                host="localhost", user="root", password="123456",

                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

            )

            with conn1.cursor() as cursor:

                cursor.execute("""
                                            SELECT 管程数值 FROM 产品设计活动表_设计数据表
                                              WHERE 产品ID = %s AND 参数名称 = '公称直径*' LIMIT 1
                                             """, (product_id,))

                roww = cursor.fetchone()

                if roww and roww.get("管程数值"):
                    dn_value = float(roww["管程数值"])

                cursor.execute("""
                                SELECT 产品型式 
                                FROM 产品设计活动表
                                WHERE 产品ID = %s
                            """, (product_id,))
                product_info = cursor.fetchone()

                if product_info and product_info["产品型式"] not in ("NEN", "AEM", "BEM"):
                    trigger = True
            if dn_value and trigger == True:

                try:

                    conn2 = pymysql.connect(

                        host="localhost", user="root", password="123456",

                        database="配置库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

                    )

                    with conn2.cursor() as cursor:

                        cursor.execute("SELECT value FROM user_config WHERE id = 2.16")

                        roww = cursor.fetchone()

                        if roww:

                            config = eval(roww["value"])

                            values = config[1][1:]

                            if dn_value < 800:

                                qty = values[0]

                            elif 800 <= dn_value <= 2000:

                                qty = values[1]

                            else:

                                qty = values[2]

                    conn2.close()

                except:

                    pass

            luozhu_qty_guanxiangfalan = int(luozhu_qty) - int(qty)
            row[6].value = int(luozhu_qty_guanxiangfalan)

            dh = get_value(jisuan_data, "管箱法兰", "螺栓公称直径")

            R = get_actual_diameter(dh)

            H = get_luozhu_length(jisuan_data, product_id)

            density = get_material_density_from_merged("螺柱（管箱法兰）", product_id)

            print("R", R)

            print("H", H)

            print("density", density)

            if R and H and density:
                mass_luozhu = round((math.pi * (R / 1000) ** 2 / 4) * (H / 1000) * density, 2)

                row[7].value = mass_luozhu
            print("mass_luozhu", mass_luozhu)
        elif name == "螺柱（后端管箱法兰）" and luozhu_qty:
            qty = 0
            dn_value = None
            trigger = False
            conn1 = pymysql.connect(

                host="localhost", user="root", password="123456",

                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

            )

            with conn1.cursor() as cursor:

                cursor.execute("""
                                            SELECT 管程数值 FROM 产品设计活动表_设计数据表
                                              WHERE 产品ID = %s AND 参数名称 = '公称直径*' LIMIT 1
                                             """, (product_id,))

                roww = cursor.fetchone()

                if roww and roww.get("管程数值"):
                    dn_value = float(roww["管程数值"])

                cursor.execute("""
                                SELECT 产品型式 
                                FROM 产品设计活动表
                                WHERE 产品ID = %s
                            """, (product_id,))
                product_info = cursor.fetchone()

                if product_info and product_info["产品型式"] not in ("NEN", "AEM", "BEM"):
                    trigger = True
            if dn_value and trigger == True:

                try:

                    conn2 = pymysql.connect(

                        host="localhost", user="root", password="123456",

                        database="配置库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

                    )

                    with conn2.cursor() as cursor:

                        cursor.execute("SELECT value FROM user_config WHERE id = 2.16")

                        roww = cursor.fetchone()

                        if roww:

                            config = eval(roww["value"])

                            values = config[1][1:]

                            if dn_value < 800:

                                qty = values[0]

                            elif 800 <= dn_value <= 2000:

                                qty = values[1]

                            else:

                                qty = values[2]

                    conn2.close()

                except:

                    pass

            luozhu_qty_guanxiangfalan = int(luozhu_qty) - int(qty)
            row[6].value = int(luozhu_qty_guanxiangfalan)

            dh = get_value(jisuan_data, "管箱法兰", "螺栓公称直径")

            R = get_actual_diameter(dh)

            H = get_luozhu_length(jisuan_data, product_id)

            density = get_material_density_from_merged("螺柱（管箱法兰）", product_id)

            print("R", R)

            print("H", H)

            print("density", density)

            if R and H and density:
                mass_luozhu = round((math.pi * (R / 1000) ** 2 / 4) * (H / 1000) * density, 2)

                row[7].value = mass_luozhu
            print("mass_luozhu", mass_luozhu)

        elif name == "螺柱（浮头法兰）":

            dh = get_value(jisuan_data, "浮头法兰", "螺栓公称直径")

            R = get_actual_diameter(dh)

            H = get_luozhu_length(jisuan_data, product_id)

            density = get_material_density_from_merged("螺柱（浮头法兰）", product_id)

            print("R", R)

            print("H", H)

            print("density", density)

            if R and H and density:
                mass_luozhu = round((math.pi * (R / 1000) ** 2 / 4) * (H / 1000) * density, 2)

                row[7].value = mass_luozhu

        elif name == "螺母（浮头法兰）" and luozhu_qty3:

            row[6].value = luozhu_qty3 * 2

            # === 获取公称直径，查找质量 ===

            dia = get_value(jisuan_data, "浮头法兰", "螺栓公称直径")

            if dia:

                try:

                    conn3 = pymysql.connect(

                        host="localhost", user="root", password="123456",

                        database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

                    )

                    with conn3.cursor() as cursor:

                        cursor.execute("""

                            SELECT `管法兰专用螺母` 

                            FROM `螺母近似质量表`

                            WHERE 规格 = %s

                            LIMIT 1

                        """, (str(dia),))

                        row_m = cursor.fetchone()

                        if row_m and row_m.get("管法兰专用螺母"):
                            mass_per_unit = float(row_m["管法兰专用螺母"])

                            row[7].value = mass_per_unit

                    conn3.close()

                except Exception as e:

                    print(f"❌ 查询螺母质量失败: {e}")

        elif name == "螺母（管箱法兰）" and luozhu_qty:

            row[6].value = luozhu_qty * 2

            # === 获取公称直径，查找质量 ===

            dia = get_value(jisuan_data, "管箱法兰", "螺栓公称直径")

            if dia:

                try:

                    conn3 = pymysql.connect(

                        host="localhost", user="root", password="123456",

                        database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

                    )

                    with conn3.cursor() as cursor:

                        cursor.execute("""

                            SELECT `管法兰专用螺母` 

                            FROM `螺母近似质量表`

                            WHERE 规格 = %s

                            LIMIT 1

                        """, (str(dia),))

                        row_m = cursor.fetchone()

                        if row_m and row_m.get("管法兰专用螺母"):
                            mass_per_unit = float(row_m["管法兰专用螺母"])

                            row[7].value = mass_per_unit

                    conn3.close()

                except Exception as e:

                    print(f"❌ 查询螺母质量失败: {e}")
        elif name == "螺母（前端管箱法兰）" and luozhu_qty:

            row[6].value = luozhu_qty * 2

            # === 获取公称直径，查找质量 ===

            dia = get_value(jisuan_data, "管箱法兰", "螺栓公称直径")

            if dia:

                try:

                    conn3 = pymysql.connect(

                        host="localhost", user="root", password="123456",

                        database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

                    )

                    with conn3.cursor() as cursor:

                        cursor.execute("""

                            SELECT `管法兰专用螺母` 

                            FROM `螺母近似质量表`

                            WHERE 规格 = %s

                            LIMIT 1

                        """, (str(dia),))

                        row_m = cursor.fetchone()

                        if row_m and row_m.get("管法兰专用螺母"):
                            mass_per_unit = float(row_m["管法兰专用螺母"])

                            row[7].value = mass_per_unit

                    conn3.close()

                except Exception as e:

                    print(f"❌ 查询螺母质量失败: {e}")
        elif name == "螺母（后端管箱封头）" and luozhu_qty:

            row[6].value = luozhu_qty * 2

            # === 获取公称直径，查找质量 ===

            dia = get_value(jisuan_data, "管箱法兰", "螺栓公称直径")

            if dia:

                try:

                    conn3 = pymysql.connect(

                        host="localhost", user="root", password="123456",

                        database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

                    )

                    with conn3.cursor() as cursor:

                        cursor.execute("""

                            SELECT `管法兰专用螺母` 

                            FROM `螺母近似质量表`

                            WHERE 规格 = %s

                            LIMIT 1

                        """, (str(dia),))

                        row_m = cursor.fetchone()

                        if row_m and row_m.get("管法兰专用螺母"):
                            mass_per_unit = float(row_m["管法兰专用螺母"])

                            row[7].value = mass_per_unit

                    conn3.close()

                except Exception as e:

                    print(f"❌ 查询螺母质量失败: {e}")
        elif name == "螺母（后端管箱法兰）" and luozhu_qty:

            row[6].value = luozhu_qty * 2

            # === 获取公称直径，查找质量 ===

            dia = get_value(jisuan_data, "管箱法兰", "螺栓公称直径")

            if dia:

                try:

                    conn3 = pymysql.connect(

                        host="localhost", user="root", password="123456",

                        database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

                    )

                    with conn3.cursor() as cursor:

                        cursor.execute("""

                            SELECT `管法兰专用螺母` 

                            FROM `螺母近似质量表`

                            WHERE 规格 = %s

                            LIMIT 1

                        """, (str(dia),))

                        row_m = cursor.fetchone()

                        if row_m and row_m.get("管法兰专用螺母"):
                            mass_per_unit = float(row_m["管法兰专用螺母"])

                            row[7].value = mass_per_unit

                    conn3.close()

                except Exception as e:

                    print(f"❌ 查询螺母质量失败: {e}")

        elif name == "螺柱（管箱平盖）" and luozhu_qty2:

            # ========================
            # 1. 设置默认数量
            # ========================
            row[6].value = luozhu_qty2

            # ========================
            # 2. 判断产品型式是否为 NEN
            # ========================
            try:
                conn = pymysql.connect(
                    host="localhost",
                    user="root",
                    password="123456",
                    database="产品设计活动库",
                    charset="utf8mb4",
                    cursorclass=pymysql.cursors.DictCursor
                )
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT 产品型式 
                        FROM 产品设计活动表
                        WHERE 产品ID = %s
                        LIMIT 1
                    """, (product_id,))
                    row_type = cursor.fetchone()

                if row_type and row_type["产品型式"] == "NEN":
                    print("⚙️ 产品型式为 NEN，螺柱数量加倍")
                    row[6].value = luozhu_qty2 * 2

            except Exception as e:
                print("⚠️ 获取产品型式失败：", e)

            dh = get_value(jisuan_data, "管箱平盖", "螺栓公称直径")

            R = get_actual_diameter(dh)

            H = get_luozhu_length(jisuan_data, product_id)

            density = get_material_density_from_merged("螺柱（管箱平盖）", product_id)

            print("R", R)

            print("H", H)

            print("density", density)

            if R and H and density:
                mass_luozhu = round((math.pi * (R / 1000) ** 2 / 4) * (H / 1000) * density, 2)

                row[7].value = mass_luozhu

        elif name == "螺母（管箱平盖）" and luozhu_qty2:

            # ========================
            # 1. 设置默认数量
            # ========================
            row[6].value = luozhu_qty2 * 2

            # ========================
            # 2. 判断产品型式是否为 NEN
            # ========================
            try:
                conn = pymysql.connect(
                    host="localhost",
                    user="root",
                    password="123456",
                    database="产品设计活动库",
                    charset="utf8mb4",
                    cursorclass=pymysql.cursors.DictCursor
                )
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT 产品型式 
                        FROM 产品设计活动表
                        WHERE 产品ID = %s
                        LIMIT 1
                    """, (product_id,))
                    row_type = cursor.fetchone()

                if row_type and row_type["产品型式"] == "NEN":
                    print("⚙️ 产品型式为 NEN，螺柱数量加倍")
                    row[6].value = luozhu_qty2 * 4

            except Exception as e:
                print("⚠️ 获取产品型式失败：", e)

            # === 获取公称直径，查找质量 ===

            dia = get_value(jisuan_data, "管箱平盖", "螺栓公称直径")

            if dia:

                try:

                    conn3 = pymysql.connect(

                        host="localhost", user="root", password="123456",

                        database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

                    )

                    with conn3.cursor() as cursor:

                        cursor.execute("""

                            SELECT `管法兰专用螺母` 

                            FROM `螺母近似质量表`

                            WHERE 规格 = %s

                            LIMIT 1

                        """, (str(dia),))

                        row_m = cursor.fetchone()

                        if row_m and row_m.get("管法兰专用螺母"):
                            mass_per_unit = float(row_m["管法兰专用螺母"])

                            row[7].value = mass_per_unit

                    conn3.close()

                except Exception as e:

                    print(f"❌ 查询螺母质量失败: {e}")
        elif name == "螺柱（前端管箱平盖）" and luozhu_qty2:

            # ========================
            # 1. 设置默认数量
            # ========================
            row[6].value = luozhu_qty2

            # ========================
            # 2. 判断产品型式是否为 NEN
            # ========================
            try:
                conn = pymysql.connect(
                    host="localhost",
                    user="root",
                    password="123456",
                    database="产品设计活动库",
                    charset="utf8mb4",
                    cursorclass=pymysql.cursors.DictCursor
                )
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT 产品型式 
                        FROM 产品设计活动表
                        WHERE 产品ID = %s
                        LIMIT 1
                    """, (product_id,))
                    row_type = cursor.fetchone()

                if row_type and row_type["产品型式"] == "NEN":
                    print("⚙️ 产品型式为 NEN，螺柱数量加倍")
                    row[6].value = luozhu_qty2 * 2

            except Exception as e:
                print("⚠️ 获取产品型式失败：", e)

            dh = get_value(jisuan_data, "管箱平盖", "螺栓公称直径")

            R = get_actual_diameter(dh)

            H = get_luozhu_length(jisuan_data, product_id)

            density = get_material_density_from_merged("螺柱（管箱平盖）", product_id)

            print("R", R)

            print("H", H)

            print("density", density)

            if R and H and density:
                mass_luozhu = round((math.pi * (R / 1000) ** 2 / 4) * (H / 1000) * density, 2)

                row[7].value = mass_luozhu
        elif name == "螺母（前端管箱平盖）" and luozhu_qty2:

            # ========================
            # 1. 设置默认数量
            # ========================
            row[6].value = luozhu_qty2 * 2

            # ========================
            # 2. 判断产品型式是否为 NEN
            # ========================
            try:
                conn = pymysql.connect(
                    host="localhost",
                    user="root",
                    password="123456",
                    database="产品设计活动库",
                    charset="utf8mb4",
                    cursorclass=pymysql.cursors.DictCursor
                )
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT 产品型式 
                        FROM 产品设计活动表
                        WHERE 产品ID = %s
                        LIMIT 1
                    """, (product_id,))
                    row_type = cursor.fetchone()

                if row_type and row_type["产品型式"] == "NEN":
                    print("⚙️ 产品型式为 NEN，螺柱数量加倍")
                    row[6].value = luozhu_qty2 * 4

            except Exception as e:
                print("⚠️ 获取产品型式失败：", e)

            # === 获取公称直径，查找质量 ===

            dia = get_value(jisuan_data, "管箱平盖", "螺栓公称直径")

            if dia:

                try:

                    conn3 = pymysql.connect(

                        host="localhost", user="root", password="123456",

                        database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

                    )

                    with conn3.cursor() as cursor:

                        cursor.execute("""

                            SELECT `管法兰专用螺母` 

                            FROM `螺母近似质量表`

                            WHERE 规格 = %s

                            LIMIT 1

                        """, (str(dia),))

                        row_m = cursor.fetchone()

                        if row_m and row_m.get("管法兰专用螺母"):
                            mass_per_unit = float(row_m["管法兰专用螺母"])

                            row[7].value = mass_per_unit

                    conn3.close()

                except Exception as e:

                    print(f"❌ 查询螺母质量失败: {e}")

        elif name == "吊环螺钉" or name == "环首螺钉":
            conn = pymysql.connect(
                host="localhost",
                port=3306,
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4"
            )
            cur = conn.cursor()
            cur.execute(
                "SELECT 参数值 FROM 产品设计活动表_布管参数表 "
                "WHERE 产品ID=%s AND 参数名=%s LIMIT 1",
                (product_id, "吊环螺钉数量")
            )
            row_diaohuan = cur.fetchone()
            num_diaohuan = row_diaohuan[0]
            row[6].value = num_diaohuan
            cur.execute(
                "SELECT 参数值 FROM 产品设计活动表_布管参数表 "
                "WHERE 产品ID=%s AND 参数名=%s LIMIT 1",
                (product_id, "吊环螺钉规格")
            )
            row_diaohuan = cur.fetchone()
            dh = row_diaohuan[0]
            conn_component = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="元件库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            try:
                cur_comp = conn_component.cursor()

                mass = 0.0
                if dh:
                    # ✅ 优先按“规格”精确匹配（字段名按你库里可能出现的几种写法做兼容）
                    cur_comp.execute("""
                        SELECT *
                        FROM 吊环螺钉质量表
                        WHERE 吊环螺钉规格=%s
                        LIMIT 1
                    """, dh)
                    row_mass = cur_comp.fetchone()

                    # ✅ 从结果中找“质量”字段（兼容不同字段名）
                    if row_mass:
                        for k in ["质量"]:
                            if k in row_mass and row_mass[k] not in (None, "", "None"):
                                mass = float(row_mass[k])
                                break

                    # ✅ 如果上面字段名都没命中，再兜底：找第一个可转 float 的数值字段
                    if row_mass and mass == 0.0:
                        for k, v in row_mass.items():
                            try:
                                if v not in (None, "", "None"):
                                    mass = float(str(v).strip())
                                    break
                            except Exception:
                                pass
                print(f"✅ 吊环螺钉规格={dh} → 质量={mass}")
                row[7].value = mass
            finally:
                conn_component.close()
        elif name == "支持板":

            zhichiban = jisuan_data.get("DictOutDatas", {}).get("浮头管束", {}).get("Datas", [])
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4"
            )
            cursor = conn.cursor()
            cursor.execute("""
                                                        SELECT 产品型式 
                                                        FROM 产品设计活动表 
                                                        WHERE 产品ID = %s
                                                    """, (product_id,))
            row_xingshi = cursor.fetchone()
            conn.close()

            if not row_xingshi:
                raise ValueError(f"未找到 product_id={product_id} 对应的产品型式")

            product_type = row_xingshi[0]
            if product_type in ("AKU", "BKU"):
                zhichiban = jisuan_data.get("DictOutDatas", {}).get("管束", {}).get("Datas", [])

            zhichiban_shuliang = get_param(zhichiban, "支持板数量")
            zhichiban_shuliang = int(zhichiban_shuliang) if zhichiban_shuliang not in (None, "", "None") else 1
            row[6].value = zhichiban_shuliang

            if support_R and support_t:
                density_zhichiban = get_material_density("支持板", product_id)
                print(density_zhichiban, "density_zhichiban")
                row[7].value = calc_weight(support_R, support_t, density_zhichiban)


        elif name == "换热管":

            uhx_data = jisuan_data.get("DictOutDatas", {}).get("固定管板", {}).get("Datas", [])

            uhx_mass = get_param(uhx_data, "单根换热管重量kg")

            uhx_mass = float(uhx_mass) if uhx_mass not in (None, "", "None") else None

            row[7].value = uhx_mass
        #
        # elif name == "浮动管板":
        #
        #     uhx_data = jisuan_data.get("DictOutDatas", {}).get("固定管板", {}).get("Datas", [])
        #
        #     uhx_mass = get_param(uhx_data, "单根换热管重量kg")
        #
        #     uhx_mass = float(uhx_mass) if uhx_mass not in (None, "", "None") else None
        #
        #     row[7].value = uhx_mass

        elif name == "铭牌板":

            uhx_mass = 0.8

            row[7].value = uhx_mass
        elif name == "铭牌":

            uhx_mass = 2

            row[7].value = uhx_mass
        elif name == "铭牌支架":

            uhx_mass = 1

            row[7].value = uhx_mass

        elif name == "管箱吊耳":

            uhx_mass = "/"

            row[7].value = uhx_mass

        elif name == "吊耳":

            uhx_mass = "/"

            row[7].value = uhx_mass
        elif name == "前端管箱吊耳":

            uhx_mass = "/"

            row[7].value = uhx_mass
        elif name == "后端管箱吊耳":

            uhx_mass = "/"

            row[7].value = uhx_mass
        elif name == "管箱垫片":

            uhx_mass = "/"

            row[7].value = uhx_mass

        elif name == "管箱侧垫片":

            uhx_mass = "/"

            row[7].value = uhx_mass

        elif name == "外头盖侧垫片":

            uhx_mass = "/"

            row[7].value = uhx_mass

        elif name == "外头盖垫片":

            uhx_mass = "/"

            row[7].value = uhx_mass

        elif name == "防松支耳":

            # === 获取防松支耳数量配置 ===

            qty = None

            dn_value = None

            conn1 = pymysql.connect(

                host="localhost", user="root", password="123456",

                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

            )

            with conn1.cursor() as cursor:

                cursor.execute("""

                                                   SELECT 管程数值 FROM 产品设计活动表_设计数据表

                                                   WHERE 产品ID = %s AND 参数名称 = '公称直径*' LIMIT 1

                                               """, (product_id,))

                roww = cursor.fetchone()

                if roww and roww.get("管程数值"):
                    dn_value = float(roww["管程数值"])

            if dn_value:

                try:

                    conn2 = pymysql.connect(

                        host="localhost", user="root", password="123456",

                        database="配置库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

                    )

                    with conn2.cursor() as cursor:

                        cursor.execute("SELECT value FROM user_config WHERE id = 2.16")

                        roww = cursor.fetchone()

                        print(dn_value, "dn_value")

                        if roww:

                            config = eval(roww["value"])

                            values = config[1][1:]

                            if dn_value < 800:

                                qty = values[0]

                            elif 800 <= dn_value <= 2000:

                                qty = values[1]

                            else:

                                qty = values[2]

                    conn2.close()

                except:

                    pass

            row[6].value = qty

            uhx_mass = 0.5

            row[7].value = uhx_mass

        elif name == "顶板":

            uhx_mass = 0.5

            row[7].value = uhx_mass

        elif name == "支座":
            # ---------- 1️⃣ 定位“鞍式支座”元件ID ----------
            saddle_component_id = get_value2_huodongku(
                """
                SELECT 元件ID
                FROM 产品设计活动表_元件附加参数合并表
                WHERE 产品ID = %s
                  AND 参数值 = '鞍式支座'
                LIMIT 1
                """,
                (product_id,)
            )

            materials = []

            if saddle_component_id:

                # ---------- 2️⃣ 取该元件下所有 Tab 分类 ----------
                tab_str = get_value2_huodongku(
                    """
                    SELECT GROUP_CONCAT(DISTINCT Tab分类 ORDER BY Tab分类)
                    FROM 产品设计活动表_元件附加参数合并表
                    WHERE 产品ID = %s
                      AND 元件ID = %s
                      AND 参数名称 = '元件名称'
                    """,
                    (product_id, saddle_component_id)
                ) or ""

                tabs = [t for t in tab_str.split(",") if t]

                # ✅ 分开收集，最后强制按顺序合并
                jinban_materials = []
                dianban_materials = []

                # ---------- 3️⃣ 遍历每个 Tab ----------
                for tab in tabs:

                    # 3.1 取该 Tab 下的「元件名称」（json list）
                    comp_value = get_value2_huodongku(
                        """
                        SELECT 参数值
                        FROM 产品设计活动表_元件附加参数合并表
                        WHERE 产品ID = %s
                          AND 元件ID = %s
                          AND Tab分类 = %s
                          AND 参数名称 = '元件名称'
                        LIMIT 1
                        """,
                        (product_id, saddle_component_id, tab)
                    )

                    try:
                        comp_list = json.loads(comp_value)
                        if not isinstance(comp_list, list):
                            continue
                    except Exception:
                        continue

                    # 3.2 如果该 Tab 含有 筋板 / 垫板 → 取材料牌号
                    if ("筋板" in comp_list) or ("垫板" in comp_list):
                        material = get_value2_huodongku(
                            """
                            SELECT 参数值
                            FROM 产品设计活动表_元件附加参数合并表
                            WHERE 产品ID = %s
                              AND 元件ID = %s
                              AND Tab分类 = %s
                              AND 参数名称 = '材料牌号'
                            LIMIT 1
                            """,
                            (product_id, saddle_component_id, tab)
                        )

                        if material:
                            if "筋板" in comp_list and material not in jinban_materials:
                                jinban_materials.append(material)
                                print("筋板:", material)

                            if "垫板" in comp_list and material not in dianban_materials:
                                dianban_materials.append(material)
                                print("垫板:", material)

                # ✅ 最终固定顺序：先筋板，再垫板
                materials = jinban_materials + [m for m in dianban_materials if m not in jinban_materials]

            print("materials", materials)

            # ---------- 4️⃣ 写回 ----------
            if materials:
                row[5].value = "/".join(materials)

            if not row[6].value:
                row[6].value = 2

            if saddle_mass:
                row[7].value = saddle_mass



        elif name == "带肩螺柱":

            dn_value = None

            conn1 = pymysql.connect(

                host="localhost", user="root", password="123456",

                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

            )

            with conn1.cursor() as cursor:

                cursor.execute("""

                            SELECT 管程数值 FROM 产品设计活动表_设计数据表

                            WHERE 产品ID = %s AND 参数名称 = '公称直径*' LIMIT 1

                        """, (product_id,))

                roww = cursor.fetchone()

                if roww and roww.get("管程数值"):
                    dn_value = float(roww["管程数值"])

            # === 获取防松支耳数量配置 ===

            qty = None

            if dn_value:

                try:

                    conn2 = pymysql.connect(

                        host="localhost", user="root", password="123456",

                        database="配置库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

                    )

                    with conn2.cursor() as cursor:

                        cursor.execute("SELECT value FROM user_config WHERE id = 2.16")

                        roww = cursor.fetchone()

                        if roww:

                            config = eval(roww["value"])

                            values = config[1][1:]

                            if dn_value < 800:

                                qty = values[0]

                            elif 800 <= dn_value <= 2000:

                                qty = values[1]

                            else:

                                qty = values[2]

                    conn2.close()

                except:

                    pass

            row[6].value = qty
            dh = get_value(jisuan_data, "管箱法兰", "螺栓公称直径")

            R = get_actual_diameter(dh)

            H = get_luozhu_length(jisuan_data, product_id)

            density = get_material_density_from_merged("螺柱（管箱法兰）", product_id)

            print("R", R)

            print("H", H)

            print("density", density)

            if R and H and density:
                mass_luozhu = round((math.pi * (R / 1000) ** 2 / 4) * (H / 1000) * density, 2)
            row[7].value = mass_luozhu
        elif name == "铆钉":
            row[6].value = 4
            row[7].value = 0.02

        # === 3. 固定映射兜底 ===
        elif name in mass_map:
            row[7].value = mass_map[name]
            if name in quantity_map:
                row[6].value = quantity_map[name]


def generate_material_list(product_id: str, output_path: str):
    print(f"✅ generate_material_list 已加载修复版: {MATERIAL_LIST_PATCH_VERSION} | {__file__}")
    print(f"✅ generate_material_list 补丁已加载: {MATERIAL_LIST_PATCH_VERSION}")
    template_path = os.path.abspath(
        os.path.join("templates", "material_list", "材料清单.xlsx")
    )
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"未找到模板文件: {template_path}")

    # 连接 产品设计活动库
    connection = pymysql.connect(
        host='localhost',
        port=3306,
        user='root',
        password='123456',
        database='产品设计活动库',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

    cursor = connection.cursor()

    # ① 查询产品需求库 → 产品需求表（获取产品信息）
    cursor.execute("""
        SELECT 产品名称, 设备位号, 产品型式, 图号前缀, 产品编号, 项目ID
        FROM 产品需求库.产品需求表
        WHERE 产品ID = %s
    """, (product_id,))
    product_info = cursor.fetchone()

    cursor.execute("""
        SELECT 管程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s AND 参数名称 = '公称直径*'
        LIMIT 1
    """, (product_id,))
    nominal_diameter_row = cursor.fetchone() or {}

    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_布管参数表
        WHERE 产品ID = %s AND 参数名 = '换热管公称长度 LN'
        LIMIT 1
    """, (product_id,))
    tube_length_row = cursor.fetchone() or {}

    # ② 查询元件材料表
    cursor.execute("""
        SELECT 元件名称, 材料类型, 材料牌号, 材料标准, 供货状态
        FROM 产品设计活动表_元件材料表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()

    if not rows:
        print(f"⚠️ 未找到产品ID {product_id} 的材料数据")
        cursor.close()
        connection.close()
        return

    # ③ 查询附加参数表（锻件级别）
    cursor.execute("""
        SELECT 元件名称, 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s 
          AND 参数名称 IN ('锻件级别','材料类型')
          AND 参数值 IS NOT NULL AND 参数值 <> ''
    """, (product_id,))
    param_rows = cursor.fetchall()

    param_map = {}
    for r in param_rows:
        comp = r["元件名称"]
        if comp not in param_map:
            param_map[comp] = {}
        param_map[comp][r["参数名称"]] = r["参数值"]

    forging_level_map = {
        comp: p["锻件级别"]
        for comp, p in param_map.items()
        if p.get("材料类型") == "钢锻件" and "锻件级别" in p
    }
    # ④ 查询元件附加参数合并表（设备法兰紧固件，多 Tab）
    cursor.execute("""
        SELECT 元件ID, 参数名称, 参数值, Tab分类
        FROM 产品设计活动表_元件附加参数合并表
        WHERE 产品ID = %s
    """, (product_id,))
    merged_rows = cursor.fetchall()

    # Tab -> 元件ID -> 参数字典
    merged_tab_map = {}
    for r in merged_rows:
        tab = r["Tab分类"]
        cid = r["元件ID"]
        merged_tab_map.setdefault(tab, {}).setdefault(cid, {})[r["参数名称"]] = r["参数值"]
    # 打开 Excel 模板
    wb = openpyxl.load_workbook(template_path)
    sheet = wb.active
    sheet.title = "Sheet1"

    # 清除模板中的示例/提示值，只清材料输出列，保留全部格式。
    for row in iter_material_rows(sheet):
        for column in MATERIAL_OUTPUT_COLUMNS:
            _clear_material_cell(row[column - 1])

    def display_value(value):
        if value in (None, "", "None"):
            return ""
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()

    if product_info:
        equipment_summary = (
            f"{display_value(product_info.get('设备位号'))}/"
            f"{display_value(product_info.get('产品名称'))}/"
            f"{display_value(product_info.get('产品型式'))}"
            f"{display_value(nominal_diameter_row.get('管程数值'))}*"
            f"{display_value(tube_length_row.get('参数值'))}"
        )
        # C2:H2 是合并单元格，只能写左上角 C2。
        sheet["C2"] = equipment_summary

    # 是否存在设备法兰紧固件元件（核心前提）
    has_device_fastener = any(
        r.get("元件名称") == "设备法兰紧固件"
        for r in rows
    )

    excel_row_idx = MATERIAL_START_ROW
    serial_no = 1
    written_normal_keys = set()
    written_fastener_keys = set()
    for row in rows:
        comp_name = row["元件名称"]

        # =================================================
        # 一、设备法兰紧固件：用合并表展开替代
        # =================================================
        if comp_name == "设备法兰紧固件" and has_device_fastener:

            for tab, comp_group in merged_tab_map.items():
                for cid, params in comp_group.items():

                    # 只认设备法兰紧固件
                    if params.get("元件名称") != "设备法兰紧固件":
                        continue

                    belongs_raw = params.get("元件所属")
                    if not belongs_raw:
                        continue

                    belongs_list = [
                        x.strip() for x in re.split(r"[，,、;；]", str(belongs_raw))
                        if x.strip()
                    ]

                    for belong in belongs_list:
                        for idx_flag, kind in [("1", "螺柱"), ("2", "螺母")]:

                            mat_grade = params.get(f"材料牌号{idx_flag}")
                            if mat_grade in (None, "", "None"):
                                continue

                            fastener_name = f"{kind}（{belong}）"

                            material = mat_grade

                            forge = params.get(f"锻件级别{idx_flag}")
                            mat_type = params.get(f"材料类型{idx_flag}")
                            supply_status = params.get(f"供货状态{idx_flag}")

                            if (
                                    forge not in (None, "", "None", "/", "-")
                                    and mat_type == "钢锻件"
                            ):
                                material = f"{material} {forge}"

                            mat_type_out = "/" if mat_type == "见参数定义" else params.get(f"材料类型{idx_flag}", "/")
                            supply_out = "/" if supply_status == "见参数定义" else params.get(f"供货状态{idx_flag}",
                                                                                              "/")

                            dedup_key = (
                                fastener_name,
                                material,
                                mat_type_out,
                                supply_out,
                            )

                            if dedup_key in written_fastener_keys:
                                continue

                            written_fastener_keys.add(dedup_key)

                            ensure_material_row_capacity(sheet, excel_row_idx)

                            sheet[f"A{excel_row_idx}"] = serial_no
                            sheet.cell(excel_row_idx, MATERIAL_NAME_COL, fastener_name)
                            sheet.cell(excel_row_idx, MATERIAL_GRADE_COL, material)
                            sheet.cell(excel_row_idx, MATERIAL_TYPE_COL, mat_type_out)
                            sheet.cell(excel_row_idx, MATERIAL_SUPPLY_COL, supply_out)

                            excel_row_idx += 1
                            serial_no += 1

            # ❗关键：原来的“设备法兰紧固件”这一行不再写
            continue

        # =================================================
        # 二、普通元件：完全走你原有逻辑
        # =================================================
        normal_key = (
            str(comp_name).strip(),
            str(row.get("材料牌号", "")).strip(),
            str(row.get("材料类型", "")).strip(),
            str(row.get("供货状态", "")).strip(),
        )

        if normal_key in written_normal_keys:
            continue

        written_normal_keys.add(normal_key)
        ensure_material_row_capacity(sheet, excel_row_idx)
        sheet[f"A{excel_row_idx}"] = serial_no
        sheet.cell(excel_row_idx, MATERIAL_NAME_COL, comp_name)

        material = "/" if row["材料牌号"] == "见参数定义" else row["材料牌号"]

        # 原有锻件级别逻辑
        if comp_name in forging_level_map:
            material = f"{material} {forging_level_map[comp_name]}"

        # ===== 原有覆层逻辑：一字不动 =====
        if any(key in comp_name for key in ["管板", "圆筒", "封头", "法兰", "平盖"]):
            if "固定管板" in comp_name:
                cursor.execute("""
                    SELECT 参数名称, 参数值 
                    FROM 产品设计活动表_元件附加参数表
                    WHERE 产品ID = %s AND 元件名称 = '固定管板'
                      AND 参数名称 IN (
                          '管程侧是否添加覆层', '管程侧覆层材料牌号',
                          '壳程侧是否添加覆层', '壳程侧覆层材料牌号'
                      )
                """, (product_id,))
                side_rows = cursor.fetchall()
                side_map = {r["参数名称"]: r["参数值"] for r in side_rows}

                has_side_flag = (
                        "管程侧是否添加覆层" in side_map or
                        "壳程侧是否添加覆层" in side_map
                )

                if has_side_flag:
                    if side_map.get("管程侧是否添加覆层") == "是" and side_map.get("壳程侧是否添加覆层") != "是":
                        gt_mat = side_map.get("管程侧覆层材料牌号")
                        if gt_mat not in (None, "", "无", "None"):
                            material = f"{material}+{gt_mat}"
                    elif side_map.get("壳程侧是否添加覆层") == "是" and side_map.get("管程侧是否添加覆层") != "是":
                        kc_mat = side_map.get("壳程侧覆层材料牌号")
                        if kc_mat not in (None, "", "无", "None"):
                            material = f"{material}+{kc_mat}"
                    elif side_map.get("管程侧是否添加覆层") == "是" and side_map.get("壳程侧是否添加覆层") == "是":
                        gt_mat = side_map.get("管程侧覆层材料牌号")
                        kc_mat = side_map.get("壳程侧覆层材料牌号")
                        if gt_mat and kc_mat:
                            material = f"{material}+{gt_mat}+{kc_mat}"
            else:
                cursor.execute("""
                    SELECT 参数名称, 参数值 
                    FROM 产品设计活动表_元件附加参数表
                    WHERE 产品ID = %s AND 元件名称 = %s
                      AND 参数名称 IN ('是否添加覆层','覆层材料牌号')
                """, (product_id, comp_name))
                fuceng_rows = cursor.fetchall()
                if fuceng_rows:
                    fuceng_map = {r["参数名称"]: r["参数值"] for r in fuceng_rows}
                    if fuceng_map.get("是否添加覆层") == "是" and fuceng_map.get("覆层材料牌号"):
                        material = f"{material}+{fuceng_map['覆层材料牌号']}"

        sheet.cell(excel_row_idx, MATERIAL_GRADE_COL, material)
        sheet.cell(
            excel_row_idx,
            MATERIAL_TYPE_COL,
            "/" if row["材料类型"] == "见参数定义" else row["材料类型"],
        )
        sheet.cell(
            excel_row_idx,
            MATERIAL_SUPPLY_COL,
            "/" if row["供货状态"] == "见参数定义" else row["供货状态"],
        )

        excel_row_idx += 1
        serial_no += 1

    cursor.close()
    connection.close()

    # 加载 JSON 并填充数量、重量等
    json_jisuan = load_json_file(os.path.join(os.getcwd(), "jisuan_output_new_tidai.json"))
    fill_quantity_weight(json_jisuan, sheet)
    remove_unused_nozzle_reinforcement_rings(sheet, json_jisuan)

    # 所有元件统一预过滤：附加参数存在但全部为空的元件，不进入特殊件计算。
    removed_empty = _remove_components_with_all_empty_params(sheet, product_id, json_jisuan)
    if removed_empty:
        print(f"✅ fill_special_items 前已删除空参数元件 {removed_empty} 行")

    try:
        fill_special_items(sheet, json_jisuan, product_id)
    except Exception as e:
        # 最后一层兜底：任何单个特殊件参数异常都不能中断整张材料清单生成。
        print(f"⚠️ 特殊件填充出现异常，已跳过后续特殊件处理，不中断材料清单生成: {e}")

    # 特殊件计算可能把吊耳重量回写为“/”，因此在保存前统一应用最终业务规则。
    apply_fixed_material_item_rules(sheet, product_id=product_id)

    # 保存
    wb.save(output_path)
    print(f"✅ 材料清单已生成：{output_path}")


def is_fastener_sub_item(name):
    if name in ("螺母（拉杆）", "拉杆"):
        return False
    return ("螺柱" in name) or ("螺母" in name)


def extract_flange_type(comp_name):
    for key in ["管箱平盖", "管箱法兰", "外头盖法兰", "浮头法兰", "壳体法兰", "外头盖侧法兰", "头盖法兰"]:
        if key in comp_name:
            return key
    return None


def split_belongs(belongs_str):
    if not belongs_str:
        return []
    return [x.strip() for x in re.split(r"[，,、;；]", str(belongs_str)) if x.strip()]


def build_fastener_rows_from_merge(merged_tab_map):
    """
    返回 List[dict]，每个 dict 表示 Excel 中的一行“真实紧固件元件”
    """
    rows_out = []

    for tab, comp_group in merged_tab_map.items():
        for cid, params in comp_group.items():
            if params.get("元件名称") != "设备法兰紧固件":
                continue

            belongs_list = split_belongs(params.get("元件所属"))

            for idx_flag, kind in [("1", "螺柱"), ("2", "螺母")]:
                mat_grade = params.get(f"材料牌号{idx_flag}")
                if mat_grade in (None, "", "None"):
                    continue

                for belong in belongs_list:
                    rows_out.append({
                        "元件名称": f"{kind}（{belong}）",
                        "材料牌号": mat_grade,
                        "材料类型": params.get(f"材料类型{idx_flag}", "/"),
                        "供货状态": params.get(f"供货状态{idx_flag}", "/"),
                        "锻件级别": params.get(f"锻件级别{idx_flag}", ""),
                        "Tab": tab,
                        "元件ID": cid,
                    })

    # 去重
    uniq = []
    seen = set()
    for r in rows_out:
        key = (r["元件名称"], r["Tab"], r["元件ID"])
        if key not in seen:
            seen.add(key)
            uniq.append(r)

    return uniq

# def fill_quantity_by_relation(sheet):
#     """
#     根据其他元件的数量或默认规则，补充填写G列数量。
#     """
#     # 收集所有结构件 → 数量映射（G列）
#     name_to_qty = {}
#     for row in sheet.iter_rows(min_row=8):
#         name_cell = row[3]  # D列
#         qty_cell = row[6]  # G列
#         if not name_cell.value:
#             continue
#         item_name = str(name_cell.value).strip()
#         name_to_qty[item_name] = qty_cell.value
#
#     # 定义依赖逻辑
#     for row in sheet.iter_rows(min_row=8):
#         name_cell = row[3]
#         qty_cell = row[6]
#         if not name_cell.value:
#             continue
#         item_name = str(name_cell.value).strip()
#
#         # 仅在数量为空时填
#         if qty_cell.value not in [None, ""] and qty_cell.value != 0:
#             continue
#
#         # 1. 与拉杆数量一致
#         # if item_name in {"螺母（拉杆）", "定距管"}:
#         #     qty_cell.value = name_to_qty.get("拉杆", "")
#
#         # 2. 螺柱 × 2
#         elif item_name == "螺柱（管箱法兰）":
#             val = name_to_qty.get("螺柱", "")
#             if isinstance(val, (int, float)):
#                 qty_cell.value = val * 2
#
#         # 3. 防松支耳 → 螺母（管箱法兰）
#         elif item_name == "螺母（管箱法兰）":
#             qty_cell.value = name_to_qty.get("防松支耳", "")
#
#         # 4. 一些元件固定数量为 1
#         elif item_name in {
#             "管箱垫片",  "管箱侧垫片", "固定鞍座", "滑动鞍座","铭牌支架","铭牌板","浮头法兰","浮头垫片","球冠形封头","吊耳","铭牌"
#         }:
#             qty_cell.value = 1
#         elif item_name in {
#             "铆钉"
#         }:
#             qty_cell.value = 8
#
#     print("✅ 已填写依赖关系数量（如与拉杆相同、固定为1等）")

