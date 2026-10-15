import ast
import json
import math
import os
import re
from multiprocessing import Process

import chardet
import configparser
import openpyxl
import pandas as pd
import pymysql
from openpyxl.reader.excel import load_workbook
from openpyxl.cell.cell import MergedCell

from modules.buguan.buguan_ziyong.My_Piping import create_product_connection
from modules.condition_input.funcs.db_cnt import get_connection
from openpyxl.styles import Alignment, Border, Side, Font

from modules.qiangdujisuan.jiekou_python.combine_json_new_abes import safe_str
from modules.wenbenshengcheng.nozzle_flange_fasteners import load_nozzle_fastener_dimensions
from modules.wenbenshengcheng.nozzle_flange_materials import (
    PAIRED_FLANGE,
    build_nozzle_flange_materials,
)
CUNGUIGE_PATCH_VERSION = "2026-10-13-v18-nozzle-reinforcement-ring"
print(f"✅ cunguige 已加载修复版: {CUNGUIGE_PATCH_VERSION} | {__file__}")

from modules.wenbenshengcheng.generate_material_list import (
    MATERIAL_FORMED_TOTAL_WEIGHT_COL,
    MATERIAL_FORMED_UNIT_WEIGHT_COL,
    MATERIAL_GRADE_COL,
    MATERIAL_NAME_COL,
    MATERIAL_OUTPUT_FONT_NAME,
    MATERIAL_OUTPUT_COLUMNS,
    MATERIAL_QUANTITY_COL,
    MATERIAL_REMARK_COL,
    MATERIAL_SPEC_COL,
    MATERIAL_SPEC_STAGING_COL,
    MATERIAL_START_ROW,
    MATERIAL_SUPPLY_COL,
    MATERIAL_TOTAL_WEIGHT_COL,
    MATERIAL_TYPE_COL,
    MATERIAL_UNIT_WEIGHT_COL,
    MATERIAL_WEIGHT_COLUMNS,
    apply_fixed_material_item_rules,
    ensure_material_row_capacity,
    find_material_section_end,
    find_material_fixed_tail_start,
    insert_material_row,
    iter_material_rows,
    iter_material_fixed_tail_rows,
    load_json_file,
    remove_material_rows,
    remove_unused_nozzle_reinforcement_rings,
    trim_unused_material_rows,
    write_material_weight_totals,
)

product_id = None


def on_product_id_changed(new_id):
    print(f"Received new PRODUCT_ID: {new_id}")
    global product_id
    product_id = new_id


thin_border = Border(
    left=Side(style='thin'),
    right=Side(style='thin'),
    top=Side(style='thin'),
    bottom=Side(style='thin')
)

center_align = Alignment(horizontal='center', vertical='center')
font_10 = Font(name=MATERIAL_OUTPUT_FONT_NAME, size=10)

db_config1 = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '产品设计活动库'
}


# === 读取 JSON 数据 ===
def load_json_data(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


# === 从 JSON 中提取指定 section + 名称 的值 ===
def get_value(data, section, name):
    dict_out = (data or {}).get("DictOutDatas") or {}

    # DictOutDatas 可能不是 dict
    if not isinstance(dict_out, dict):
        return None

    section_data = dict_out.get(section)

    # 关键：section_data 可能是 None / 非 dict
    if not isinstance(section_data, dict):
        return None

    datas = section_data.get("Datas") or []
    # 关键：Datas 可能是 None / 非 list
    if not isinstance(datas, list):
        return None

    for item in datas:
        if not isinstance(item, dict):
            continue
        if item.get("Name") == name:
            v = item.get("Value", None)
            if v is None:
                return None

            # 尝试转 float：允许 "123" / "123.4" / "123mm" 这种
            if isinstance(v, (int, float)):
                return float(v)

            if isinstance(v, str):
                s = v.strip()
                # 提取字符串中的第一个数字（含小数/科学计数）
                import re
                m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", s)
                if m:
                    try:
                        return float(m.group(0))
                    except:
                        pass
                return s  # 转不了就原样返回

            return v  # 其他类型直接返回

    return None


# === 拆分元件共用取值：优先使用原始总元件的数据 ===
def _get_first_component_value(data, sections, name):
    """按 sections 顺序取第一个非空值；用于前/后拆分件继承原元件参数。"""
    for section in sections:
        value = get_value(data, section, name)
        if not _is_empty_component_param_value(value):
            return value
    return None


def _get_component_int_value(data, sections, name):
    """读取第一个有效数值并安全转为整数；缺值时返回 None。"""
    value = _get_first_component_value(data, sections, name)
    if _is_empty_component_param_value(value):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value))
        if not match:
            return None
        return int(float(match.group(0)))


# === 定义各结构件规格的生成逻辑 ===
def generate_spec(component_name, data, product_id=None):
    """
    根据元件名称返回其规格字符串，如：EHA500X10;h=8
    如果无法生成返回 None
    """
    print('component_name', component_name)
    if component_name == "管箱封头":
        dh = get_value(data, "管箱封头", "封头类型代号") or 0
        d = get_value(data, "管箱封头", "椭圆形封头计算内径") or 0
        t = get_value(data, "管箱封头", "椭圆形封头名义厚度") or 0

        t_plus = get_value(data, "管箱封头", "椭圆形封头最小成型厚度") or 0
        h = get_value(data, "管箱封头", "椭圆形封头直边高度") or 0
        fuceng = get_value(data, "管箱封头", "椭圆形封头覆层厚度") or 0

        if None not in (dh, d, t, h):
            if fuceng not in (0, 0.0, "0", "0.0", None, "None"):
                return f"{dh}{d}×({t}({t_plus})+{fuceng});h={h}"
            else:
                return f"{dh}{d}×{t}({t_plus});h={h}"
    if component_name in ("封头", "前端封头", "后端封头"):
        # 计算文件中前/后端封头是两个独立 section；优先取各自 section。
        # 仅保留“封头”作为兼容旧数据的后备来源。
        if component_name == "前端封头":
            sections = ("前端封头", "封头")
        elif component_name == "后端封头":
            sections = ("后端封头", "封头")
        else:
            sections = ("封头",)
        dh = _get_first_component_value(data, sections, "封头类型代号")
        d = _get_first_component_value(data, sections, "椭圆形封头计算内径")
        t = _get_first_component_value(data, sections, "椭圆形封头名义厚度")
        t_plus = _get_first_component_value(data, sections, "椭圆形封头最小成型厚度")
        h = _get_first_component_value(data, sections, "椭圆形封头直边高度")
        fuceng = _get_first_component_value(data, sections, "椭圆形封头覆层厚度")

        if None not in (dh, d, t, h):
            if fuceng not in (0, 0.0, "0", "0.0", None, "None"):
                return f"{dh}{d}×({t}({t_plus or 0})+{fuceng});h={h}"
            return f"{dh}{d}×{t}({t_plus or 0});h={h}"
        return None
    if component_name == "后端管箱封头":
        dh = get_value(data, "后端管箱封头", "封头类型代号") or 0
        d = get_value(data, "后端管箱封头", "椭圆形封头计算内径") or 0
        t = get_value(data, "后端管箱封头", "椭圆形封头名义厚度") or 0

        t_plus = get_value(data, "后端管箱封头", "椭圆形封头最小成型厚度") or 0
        h = get_value(data, "后端管箱封头", "椭圆形封头直边高度") or 0
        fuceng = get_value(data, "后端管箱封头", "椭圆形封头覆层厚度") or 0

        if None not in (dh, d, t, h):
            if fuceng not in (0, 0.0, "0", "0.0", None, "None"):
                return f"{dh}{d}×({t}({t_plus})+{fuceng});h={h}"
            else:
                return f"{dh}{d}×{t}({t_plus});h={h}"
    elif component_name == "外头盖封头":
        dh = get_value(data, "外头盖封头", "封头类型代号") or 0
        d = get_value(data, "外头盖封头", "椭圆形封头计算内径") or 0
        t = get_value(data, "外头盖封头", "椭圆形封头名义厚度") or 0
        t_plus = get_value(data, "外头盖封头", "椭圆形封头最小成型厚度") or 0
        h = get_value(data, "外头盖封头", "椭圆形封头直边高度") or 0
        fuceng = get_value(data, "外头盖封头", "椭圆形封头覆层厚度") or 0
        if None not in (dh, d, t, h):
            if fuceng not in (0, 0.0, "0", "0.0", None, "None"):
                return f"{dh}{d}×({t}({t_plus})+{fuceng});h={h}"
            else:
                return f"{dh}{d}×{t}({t_plus});h={h}"
    elif component_name == "管箱圆筒":
        id_ = get_value(data, "管箱圆筒", "圆筒内径") or 0
        t = get_value(data, "管箱圆筒", "圆筒名义厚度") or 0
        l = get_value(data, "管箱圆筒", "圆筒长度") or 0
        fuceng = get_value(data, "管箱圆筒", "圆筒覆层厚度") or 0
        if None not in (id_, t, l):
            if fuceng not in (0, 0.0, "0", "0.0", None, "None"):
                return f"ID{id_}×({t}+{fuceng});L={l}"
            else:
                return f"ID{id_}×{t};L={l}"
        else:
            return f"ID{id_}×{t};L={l}"
    elif component_name == "圆筒":
        # 圆筒不拆分；规格参数严格取自计算 JSON 的“容器圆筒”。
        id_ = get_value(data, "容器圆筒", "圆筒内径")
        t = get_value(data, "容器圆筒", "圆筒名义厚度")
        l = get_value(data, "容器圆筒", "圆筒长度")
        fuceng = get_value(data, "容器圆筒", "圆筒覆层厚度")
        if None not in (id_, t, l):
            if fuceng not in (0, 0.0, "0", "0.0", None, "None"):
                return f"ID{id_}×({t}+{fuceng});L={l}"
            return f"ID{id_}×{t};L={l}"
        return None
    elif component_name == "后端管箱圆筒":
        id_ = get_value(data, "后端管箱圆筒", "圆筒内径") or 0
        t = get_value(data, "后端管箱圆筒", "圆筒名义厚度") or 0
        l = get_value(data, "后端管箱圆筒", "圆筒长度") or 0
        fuceng = get_value(data, "后端管箱圆筒", "圆筒覆层厚度") or 0
        if None not in (id_, t, l):
            if fuceng not in (0, 0.0, "0", "0.0", None, "None"):
                return f"ID{id_}×({t}+{fuceng});L={l}"
            else:
                return f"ID{id_}×{t};L={l}"
        else:
            return f"ID{id_}×{t};L={l}"
    elif component_name == "前端管箱圆筒":
        id_ = get_value(data, "管箱圆筒", "圆筒内径") or 0
        t = get_value(data, "管箱圆筒", "圆筒名义厚度") or 0
        l = get_value(data, "管箱圆筒", "圆筒长度") or 0
        fuceng = get_value(data, "管箱圆筒", "圆筒覆层厚度") or 0
        if None not in (id_, t, l):
            if fuceng not in (0, 0.0, "0", "0.0", None, "None"):
                return f"ID{id_}×({t}+{fuceng});L={l}"
            else:
                return f"ID{id_}×{t};L={l}"
        else:
            return f"ID{id_}×{t};L={l}"
    elif component_name == "端部圆筒":
        id_ = get_value(data, "后端管箱圆筒", "圆筒内径") or 0
        t = get_value(data, "后端管箱圆筒", "圆筒名义厚度") or 0
        l = get_value(data, "后端管箱圆筒", "圆筒长度") or 0
        fuceng = get_value(data, "后端管箱圆筒", "圆筒覆层厚度") or 0
        if None not in (id_, t, l):
            if fuceng not in (0, 0.0, "0", "0.0", None, "None"):
                return f"ID{id_}×({t}+{fuceng});L={l}"
            else:
                return f"ID{id_}×{t};L={l}"
        else:
            return f"ID{id_}×{t};L={l}"
    elif component_name == "锥壳":
        id_1 = get_value(data, "大端壳体圆筒", "圆筒内径") or 0
        id_2 = get_value(data, "小端壳体圆筒", "圆筒内径") or 0
        t = get_value(data, "锥壳", "锥壳名义厚度") or 0
        fuceng = get_value(data, "锥壳", "锥壳覆层厚度") or 0
        l = get_value(data, "锥壳", "锥壳长度") or 0
        if None not in (id_1, id_2, t, l):
            if fuceng not in (0, 0.0, "0", "0.0", None, "None"):
                return f"Ø{id_1}/Ø{id_2}×({t}+{fuceng});L={l}"
            else:
                return f"Ø{id_1}/Ø{id_2}×{t};L={l}"
        else:
            return f"Ø{id_1}/Ø{id_2}×{t};L={l}"

    elif component_name == "外头盖圆筒":
        id_ = get_value(data, "外头盖圆筒", "圆筒内径") or 0
        t = get_value(data, "外头盖圆筒", "圆筒名义厚度") or 0
        l = get_value(data, "外头盖圆筒", "圆筒长度") or 0
        fuceng = get_value(data, "外头盖圆筒", "圆筒覆层厚度") or 0
        if None not in (id_, t, l):
            if fuceng not in (0, 0.0, "0", "0.0", None, "None"):
                return f"ID{id_}×({t}+{fuceng});L={l}"
            else:
                return f"ID{id_}×{t};L={l}"
        else:
            return f"ID{id_}×{t};L={l}"

    elif component_name == "管箱法兰":
        w = get_value(data, "管箱法兰", "法兰名义外径") or 0
        n = get_value(data, "管箱法兰", "法兰名义内径") or 0
        h = get_value(data, "管箱法兰", "法兰总高") or 0
        if None not in (w, n, h):
            return f"Ø{w}/Ø{n}；H={h}"
    elif component_name == "后端管箱法兰":
        w = get_value(data, "管箱法兰", "法兰名义外径") or 0
        n = get_value(data, "管箱法兰", "法兰名义内径") or 0
        h = get_value(data, "管箱法兰", "法兰总高") or 0
        if None not in (w, n, h):
            return f"Ø{w}/Ø{n}；H={h}"
    elif component_name == "前端管箱法兰":
        w = get_value(data, "管箱法兰", "法兰名义外径") or 0
        n = get_value(data, "管箱法兰", "法兰名义内径") or 0
        h = get_value(data, "管箱法兰", "法兰总高") or 0
        if None not in (w, n, h):
            return f"Ø{w}/Ø{n}；H={h}"
    elif component_name == "外头盖法兰":
        w = get_value(data, "外头盖法兰", "法兰名义外径") or 0
        n = get_value(data, "外头盖法兰", "法兰名义内径") or 0
        h = get_value(data, "外头盖法兰", "法兰总高") or 0
        if None not in (w, n, h):
            return f"Ø{w}/Ø{n}；H={h}"
    elif component_name == "外头盖侧法兰":
        w = get_value(data, "外头盖侧法兰", "法兰名义外径") or 0
        n = get_value(data, "外头盖侧法兰", "法兰名义内径") or 0
        h = get_value(data, "外头盖侧法兰", "法兰总高") or 0
        if None not in (w, n, h):
            return f"Ø{w}/Ø{n}；H={h}"
    elif component_name == "浮头法兰":
        w = get_value(data, "浮头法兰", "浮头法兰名义外径(含覆层厚度)") or 0
        n = get_value(data, "浮头法兰", "覆层后浮头法兰内径(含覆层厚度)") or 0
        h1 = get_value(data, "浮头法兰", "法兰颈部高度") or 0
        h2 = get_value(data, "浮头法兰", "浮头法兰名义厚度") or 0
        h = h1 + h2
        if None not in (w, n, h):
            return f"Ø{w}/Ø{n}；H={h}"

    # elif component_name == "分程隔板":
    #     t = get_value(data, "管箱分程隔板", "管箱分程隔板名义厚度") or 0
    #     t2 = get_value(data, "管箱分程隔板", "管箱分程隔板结构尺寸长边a") or 0
    #     t3 = get_value(data, "管箱分程隔板", "管箱分程隔板结构尺寸长边b") or 0
    #
    #     if t is not None:
    #         return f"{t2}×{t3}×{t}"
    elif component_name == "内导流筒":
        t = get_value(data, "浮头管束", "导流筒厚度") or 0
        if t is not None:
            return f"δ={t}"
    elif component_name == "接地装置":
        t = get_jiedizhuangzhi_from_db(product_id) or 0
        if t is not None:
            return f"{t}"
    elif component_name == "堰板":
        h = get_value(data, "管束", "堰板厚度") or 0
        if h == 0:
            h = get_value(data, "浮动管束", "堰板厚度") or 0
        if h is not None:
            return f"δ={h}"
    elif component_name == "浮动管板":
        w = get_value(data, "浮头法兰", "浮动管板名义厚度") or 0
        l1 = get_value(data, "固定管板", "浮动管板外径") or 0

        conn = get_connection(**db_config1)
        cursor = conn.cursor()

        def query_param(param_name):
            cursor.execute("""
                   SELECT 参数值 
                   FROM 产品设计活动表_元件附加参数表 
                   WHERE 产品ID = %s AND 元件名称 = '浮动管板' AND 参数名称 = %s
                   LIMIT 1
               """, (product_id, param_name))
            row = cursor.fetchone()
            return row["参数值"].strip() if row and row.get("参数值") not in (None, "", "None") else "0"

        pipe_flag = query_param("管程侧是否添加覆层")
        shell_flag = query_param("壳程侧是否添加覆层")
        pipe_thick = query_param("管程侧覆层厚度")
        shell_thick = query_param("壳程侧覆层厚度")

        cursor.close()
        conn.close()

        # 覆层厚度处理：数值相加
        fuceng_total = 0.0
        if pipe_flag == "是" and shell_flag == "是":
            try:
                fuceng_total = float(pipe_thick) + float(shell_thick)
            except ValueError:
                fuceng_total = 0.0
        elif pipe_flag == "是":
            try:
                fuceng_total = float(pipe_thick)
            except ValueError:
                fuceng_total = 0.0
        elif shell_flag == "是":
            try:
                fuceng_total = float(shell_thick)
            except ValueError:
                fuceng_total = 0.0
        else:
            fuceng_total = 0.0  # 都不为是，不加覆层

        fuceng_str = f"{fuceng_total}" if fuceng_total > 0 else ""

        # 构建最终字符串
        if w and l1 is not None:
            if fuceng_str != "":
                return f"Ø{l1};δ={w}+{fuceng_str}"
            else:
                return f"Ø{l1};δ={w}"
        elif l1 is None:
            if fuceng_str:
                return f"δ={w}+{fuceng_str}"
            else:
                return f"δ={w}"
        else:
            return ""

    elif component_name == "隔板":
        t = get_value(data, "管箱分程隔板", "管箱分程隔板名义厚度") or 0
        if t is not None:
            return f"δ={t}"
    elif component_name == "管箱垫片":
        w = get_value(data, "管箱法兰", "垫片名义外径") or 0
        n = get_value(data, "管箱法兰", "垫片名义内径") or 0
        dphd = get_dphd_from_db("管箱垫片", product_id) or 0
        if None not in (w, n):
            return f"Ø{w}/Ø{n}；δ={dphd}"
    elif component_name == "前端管箱垫片":
        w = get_value(data, "管箱法兰", "垫片名义外径") or 0
        n = get_value(data, "管箱法兰", "垫片名义内径") or 0
        dphd = get_dphd_from_db("前端管箱垫片", product_id) or 0
        if None not in (w, n):
            return f"Ø{w}/Ø{n}；δ={dphd}"
    elif component_name == "后端管箱垫片":
        w = get_value(data, "管箱法兰", "垫片名义外径") or 0
        n = get_value(data, "管箱法兰", "垫片名义内径") or 0
        dphd = get_dphd_from_db("后端管箱垫片", product_id) or 0
        if None not in (w, n):
            return f"Ø{w}/Ø{n}；δ={dphd}"
    elif component_name == "外头盖垫片":
        w = get_value(data, "外头盖法兰", "垫片名义外径") or 0
        n = get_value(data, "外头盖法兰", "垫片名义内径") or 0
        dphd = get_dphd_from_db("外头盖垫片", product_id) or 0
        if None not in (w, n):
            return f"Ø{w}/Ø{n}；δ={dphd}"
    elif component_name == "浮头垫片":
        w = get_value(data, "浮头法兰", "垫片名义外径") or 0
        n = get_value(data, "浮头法兰", "垫片名义内径") or 0
        dphd = get_dphd_from_db("浮头垫片", product_id) or 0
        if None not in (w, n):
            return f"Ø{w}/Ø{n}；δ={dphd}"

    elif component_name == "U形换热管":
        w = get_value(data, "固定管板", "换热管外径") or 0
        b = get_value(data, "固定管板", "换热管壁厚") or 0
        l = get_pipe_param_value(product_id, "换热管公称长度LN") or 0
        if None not in (w, b, l):
            return f"Ø{w}×{b};L={l}"
    elif component_name == "换热管":
        w = get_value(data, "固定管板", "换热管外径") or 0
        b = get_value(data, "固定管板", "换热管壁厚") or 0
        l = get_pipe_param_value(product_id, "换热管公称长度LN") or 0
        if None not in (w, b, l):
            return f"Ø{w}×{b};L={l}"
    elif component_name == "中间挡板":
        conn = pymysql.connect(
            host="localhost",
            port=3306,
            user="root",
            password="123456",
            database="产品设计活动库",
            charset="utf8mb4"
        )
        cur = conn.cursor()
        thickness_mm = 0.0
        kuandu_mm = 0.0
        # 厚度
        cur.execute(
            "SELECT 参数值 FROM 产品设计活动表_布管参数表 "
            "WHERE 产品ID=%s AND 参数名=%s LIMIT 1",
            (product_id, "中间挡板厚度")
        )
        row_param = cur.fetchone()
        print(f"数据库查询中间挡板厚度: {row_param}")
        if row_param and row_param[0] is not None:
            try:
                thickness_mm = float(row_param[0])
            except Exception:
                try:
                    thickness_mm = float(ast.literal_eval(str(row_param[0])))
                except Exception:
                    thickness_mm = 0.0
        cur.execute(
            "SELECT 参数值 FROM 产品设计活动表_布管参数表 "
            "WHERE 产品ID=%s AND 参数名=%s LIMIT 1",
            (product_id, "中间挡板宽度")
        )
        row_param = cur.fetchone()
        print(f"数据库查询中间挡板板宽度: {row_param}")
        if row_param and row_param[0] is not None:
            try:
                kuandu_mm = float(row_param[0])
            except Exception:
                try:
                    kuandu_mm = float(ast.literal_eval(str(row_param[0])))
                except Exception:
                    kuandu_mm = 0.0
        jisuan_data = load_json_file(os.path.join(os.getcwd(), "jisuan_output_new_tidai.json"))

        pipe_datas = jisuan_data.get("DictOutDatas", {}).get("管束", {}).get("Datas", []) \
                     or jisuan_data.get("DictOutDatas", {}).get("浮头管束", {}).get("Datas", [])
        print(f"管束数据: {pipe_datas}")

        H1 = get_param(pipe_datas, "中间挡管/挡板长度") or 0
        H2 = get_param(pipe_datas, "中间挡管/挡板长度") or 0
        print(f"H1={H1}, H2={H2}")
        try:
            length_m = max(float(H1 or 0), float(H2 or 0))
        except Exception:
            length_m = 0.0

        return f"{length_m}×{kuandu_mm}×{thickness_mm}"

    elif component_name == "旁路挡板":
        conn = pymysql.connect(
            host="localhost",
            port=3306,
            user="root",
            password="123456",
            database="产品设计活动库",
            charset="utf8mb4"
        )
        cur = conn.cursor()
        thickness_mm = 0.0
        kuandu_mm = 0.0
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
        # 查询旁路挡板宽度（可能多条）
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

        kuandu_values = []

        for row in rows:
            val = row[0]
            if val in (None, "", "None"):
                continue

            try:
                # 常规字符串 / 数字
                num = float(val)
                kuandu_values.append(num)
                continue
            except Exception:
                pass

            try:
                # 处理 "[600]" / "(600,)" / "['600']" 这类
                parsed = ast.literal_eval(str(val))
                if isinstance(parsed, (list, tuple)) and parsed:
                    kuandu_values.append(float(parsed[0]))
                elif isinstance(parsed, (int, float)):
                    kuandu_values.append(float(parsed))
            except Exception:
                pass

        # 取最大宽度
        kuandu_mm = max(kuandu_values) if kuandu_values else 0.0

        print(f"✅ 旁路挡板最大宽度 kuandu_mm = {kuandu_mm}")

        jisuan_data = load_json_file(os.path.join(os.getcwd(), "jisuan_output_new_tidai.json"))

        pipe_datas = jisuan_data.get("DictOutDatas", {}).get("管束", {}).get("Datas", []) \
                     or jisuan_data.get("DictOutDatas", {}).get("浮头管束", {}).get("Datas", [])
        print(f"管束数据: {pipe_datas}")

        H1 = get_param(pipe_datas, "拉杆长度1") or 0
        if H1 == 0:
            H1 = get_param(pipe_datas, "拉杆长度") or 0

        H2 = get_param(pipe_datas, "拉杆长度2") or 0
        print(f"H1={H1}, H2={H2}")
        try:
            length_m = max(float(H1 or 0), float(H2 or 0))
        except Exception:
            length_m = 0.0

        return f"{length_m}×{kuandu_mm}×{thickness_mm}"
    elif component_name == "固定管板":
        w = get_value(data, "固定管板", "管板名义厚度") or 0
        if not w:
            w = get_value(data, "固定管板", "管板名义厚度 δn'") or 0

        l1 = get_value(data, "固定管板", "管板外径") or 0
        if not l1:
            # —— 从数据库补充 l1（管板外径 δn'）——
            try:
                conn2 = get_connection(**db_config1)
                cursor2 = conn2.cursor()

                cursor2.execute("""
                            SELECT `Value`
                            FROM `产品设计活动表_元件计算结果表`
                            WHERE `产品ID` = %s
                              AND `元件名称` = '固定管板'
                              AND `Id` LIKE '%%腐蚀前%%'
                              AND `Name` = '管板外径 δn'''
                            LIMIT 1
                        """, (product_id,))

                row2 = cursor2.fetchone()
                if row2 and row2.get("Value") not in (None, "", "None"):
                    l1 = str(row2["Value"]).strip()
                else:
                    l1 = ""
            except Exception as e:
                print("❌ 查询固定管板管板外径 δn' 失败：", e)
                l1 = ""
            finally:
                try:
                    cursor2.close()
                    conn2.close()
                except:
                    pass

        conn = get_connection(**db_config1)
        cursor = conn.cursor()

        # 获取鞍座型式代号（dh）
        def query_param(param_name):
            cursor.execute("""
                   SELECT 参数值 
                   FROM 产品设计活动表_元件附加参数表 
                   WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = %s
                   LIMIT 1
               """, (product_id, param_name))
            row = cursor.fetchone()
            return row["参数值"].strip() if row and row.get("参数值") not in (None, "", "None") else "0"

        pipe_flag = query_param("管程侧是否添加覆层")
        shell_flag = query_param("壳程侧是否添加覆层")
        pipe_thick = query_param("管程侧覆层厚度")
        shell_thick = query_param("壳程侧覆层厚度")

        cursor.close()
        conn.close()

        # 覆层厚度处理：数值相加
        fuceng_total = 0.0
        if pipe_flag == "是" and shell_flag == "是":
            try:
                fuceng_total = float(pipe_thick) + float(shell_thick)
            except ValueError:
                fuceng_total = 0.0
        elif pipe_flag == "是":
            try:
                fuceng_total = float(pipe_thick)
            except ValueError:
                fuceng_total = 0.0
        elif shell_flag == "是":
            try:
                fuceng_total = float(shell_thick)
            except ValueError:
                fuceng_total = 0.0
        else:
            fuceng_total = 0.0  # 都不为是，不加覆层

        fuceng_str = f"{fuceng_total}" if fuceng_total > 0 else ""

        # 构建最终字符串
        if w and l1 is not None:
            if fuceng_str:
                return f"Ø{l1};δ={w}+{fuceng_str}"
            else:
                return f"Ø{l1};δ={w}"
        elif l1 is None:
            if fuceng_str:
                return f"δ={w}+{fuceng_str}"
            else:
                return f"δ={w}"
        else:
            return ""
    elif component_name == "定距管":

        def safe_int(value):
            """将数值安全转换为 int，遇到 None、NaN、空字符串时返回 0"""
            try:
                if value is None:
                    return 0
                if isinstance(value, str) and not value.strip():
                    return 0
                if isinstance(value, float) and math.isnan(value):
                    return 0
                return int(float(value))  # 允许 '12.0' 这类字符串
            except (ValueError, TypeError):
                return 0

        val1 = get_value(data, "管束", "定距管长度1")
        if val1 is None:
            val1 = get_value(data, "浮头管束", "定距管长度1") or 0
        if val1 in (None, 0, "None"):
            val1 = get_value(data, "管束", "定距管长度") or 0
        val2 = get_value(data, "管束", "定距管长度2")
        if val2 is None:
            val2 = get_value(data, "浮头管束", "定距管长度2") or 0

        l = max(safe_int(val1), safe_int(val2))

        # if None not in (w,n,l):
        #     return f"Ø{w}×{n};L={l}"
        w = get_value(data, "固定管板", "换热管外径") or 0
        b = get_value(data, "固定管板", "换热管壁厚") or 0

        # l = get_pipe_param_value(product_id,"换热管公称长度LN")
        if None not in (w, b, l):
            return f"Ø{w}×{b};L={l}"
    elif component_name == "折流板":

        w = get_value(data, "管束", "折流板厚度") or 0
        print(data, "datasssss")
        l1 = get_value(data, "管束", "折流板/支持板外直径") or 0
        if w is not None:
            return f"Ø{l1};δ={w}"
        if w is None:
            w = get_value(data, "浮头管束", "折流板厚度") or 0
            l1 = get_value(data, "浮头管束", "折流板/支持板外直径") or 0

        return f"Ø{l1};δ={w}"
    elif component_name == "钩圈":
        l1 = get_value(data, "浮头法兰", "钩圈外径") or 0
        l2 = get_value(data, "浮头法兰", "钩圈内径") or 0

        w = get_value(data, "浮头法兰", "B型钩圈名义厚度") or 0
        if w is not None:
            return f"Ø{l1}×Ø{l2},H={w}"
    elif component_name == "内折流板":
        w = get_value(data, "管束", "折流板厚度")
        print(data, "datasssss")

        l1 = get_value(data, "管束", "折流板/支持板外直径") or 0
        if w is not None:
            return f"Ø{l1};δ={w}"
        if w is None:
            w = get_value(data, "浮头管束", "折流板厚度") or 0
            l1 = get_value(data, "浮头管束", "折流板/支持板外直径") or 0

        return f"Ø{l1};δ={w}"
    elif component_name == "异形折流板":
        l1 = None
        w = get_value(data, "管束", "折流板厚度")
        l1 = get_value(data, "管束", "折流板/支持板外直径") or 0
        if w is not None:
            return f"Ø{l1};δ={w}"
        if w is None:
            w = get_value(data, "浮头管束", "折流板厚度") or 0
            l1 = get_value(data, "浮头管束", "折流板/支持板外直径") or 0

        return f"Ø{l1};δ={w}"
    elif component_name == "弓形折流板":
        l1 = None
        w = get_value(data, "管束", "折流板厚度")
        l1 = get_value(data, "管束", "折流板/支持板外直径") or 0
        if w is not None:
            return f"Ø{l1};δ={w}"
        if w is None:
            w = get_value(data, "浮头管束", "折流板厚度") or 0
            l1 = get_value(data, "浮头管束", "折流板/支持板外直径") or 0

        return f"Ø{l1};δ={w}"
    elif component_name == "防冲板":
        conn = pymysql.connect(
            host="localhost",
            port=3306,
            user="root",
            password="123456",
            database="产品设计活动库",
            charset="utf8mb4"
        )
        cur = conn.cursor()
        thickness_mm = 0.0
        kuandu_mm = 0.0
        # 厚度
        cur.execute(
            "SELECT 参数值 FROM 产品设计活动表_布管参数表 "
            "WHERE 产品ID=%s AND 参数名=%s LIMIT 1",
            (product_id, "防冲板厚度")
        )
        row_param = cur.fetchone()
        print(f"数据库查询防冲板厚度: {row_param}")
        if row_param and row_param[0] is not None:
            try:
                thickness_mm = float(row_param[0])
            except Exception:
                try:
                    thickness_mm = float(ast.literal_eval(str(row_param[0])))
                except Exception:
                    thickness_mm = 0.0
        cur.execute(
            "SELECT 参数值 FROM 产品设计活动表_布管参数表 "
            "WHERE 产品ID=%s AND 参数名=%s LIMIT 1",
            (product_id, "防冲板宽度")
        )
        row_param = cur.fetchone()
        print(f"数据库查询防冲板宽度: {row_param}")
        if row_param and row_param[0] is not None:
            try:
                kuandu_mm = float(row_param[0])
            except Exception:
                try:
                    kuandu_mm = float(ast.literal_eval(str(row_param[0])))
                except Exception:
                    kuandu_mm = 0.0
        length_m = (
                get_value(data, "浮头管束", "防冲挡板与入口接管横截面平行的矩形（轴向）边长")
                or get_value(data, "管束", "防冲挡板与入口接管横截面平行的矩形（轴向）边长")
                or 0
        )
        return f"{length_m}×{kuandu_mm}×{thickness_mm}"
    elif component_name == "滑道":
        conn = get_connection(**db_config1)
        cursor = conn.cursor()

        l = get_value(data, "管束", "滑道长度")
        if l is None:
            l = get_value(data, "浮头管束", "滑道长度") or 0
        cursor.execute("""
                            SELECT 参数值 
                            FROM 产品设计活动表_布管参数表
                            WHERE 产品ID = %s AND 参数名 = '滑道高度'
                            LIMIT 1
                        """, (product_id,))
        h = cursor.fetchone()
        h1 = h['参数值']
        cursor.execute("""
                            SELECT 参数值 
                            FROM 产品设计活动表_布管参数表
                            WHERE 产品ID = %s AND 参数名 = '滑道厚度'
                            LIMIT 1
                        """, (product_id,))
        h = cursor.fetchone()
        h2 = h['参数值']

        return f"{l}×{h1}×{h2}"
    elif component_name == "球冠形封头":
        w = get_value(data, "浮头法兰", "球冠形封头名义厚度")
        if w is not None:
            return f"δ={w}"
    elif component_name == "支持板":
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
        row = cursor.fetchone()
        conn.close()

        if not row:
            raise ValueError(f"未找到 product_id={product_id} 对应的产品型式")

        product_type = row[0]
        if product_type in ("AKU", "BKU"):
            w = get_value(data, "管束", "支持板厚度") or 0
            l1 = get_value(data, "管束", "支持板外直径") or 0
            return f"Ø{l1};δ={w}"
        l1 = None
        w = get_value(data, "管束", "支持板厚度")
        l1 = get_value(data, "管束", "折流板/支持板外直径") or 0
        if w is not None:
            return f"Ø{l1};δ={w}"
        if w is None:
            w = get_value(data, "浮头管束", "支持板厚度") or 0
            l1 = get_value(data, "浮头管束", "折流板/支持板外直径") or 0

        return f"Ø{l1};δ={w}"

    elif component_name == "挡管":
        w = get_value(data, "固定管板", "换热管外径")
        b = get_value(data, "固定管板", "换热管壁厚")
        l = get_value(data, "管束", "中间挡管/挡板长度")
        if l is None:
            l = get_value(data, "浮头管束", "中间挡管/挡板长度")
        if None not in (w, b, l):
            return f"Ø{w}×{b};L={l}"
    elif component_name == "支撑板":
        w1 = get_value(data, "浮头管束", "支撑板厚度")
        b1 = get_value(data, "浮头管束", "支撑板高度")
        l1 = get_value(data, "浮头管束", "浮动侧支撑板长度")

        w2 = get_value(data, "浮头管束", "支撑板厚度")
        b2 = get_value(data, "浮头管束", "支撑板高度")
        l2 = get_value(data, "浮头管束", "固定侧支撑板长度")

        lines = ""
        if None not in (w1, b1, l1) and None not in (w2, b2, l2):
            # 两组都有值时，比较 l1 和 l2
            if float(l1) >= float(l2):
                lines = f"{l1}×{b1}×{w1}"
            else:
                lines = f"{l2}×{b2}×{w2}"
        elif None not in (w1, b1, l1):
            # 只有第一组有值
            lines = f"{l1}×{b1}×{w1}"
        elif None not in (w2, b2, l2):
            # 只有第二组有值
            lines = f"{l2}×{b2}×{w2}"
        if lines:
            return str(lines)
    elif component_name == "拉杆":
        val1 = get_value(data, "管束", "拉杆长度1")
        if val1 is None:
            val1 = get_value(data, "浮头管束", "拉杆长度1")
        if val1 in (None, 0, "None"):
            val1 = get_value(data, "管束", "拉杆长度")
        val2 = get_value(data, "管束", "拉杆长度2")
        if val2 is None:
            val2 = get_value(data, "浮头管束", "拉杆长度2") or 0

        w = max(val1, val2) if None not in (val1, val2) else None
        conn = get_connection(**db_config1)
        cursor = conn.cursor()
        # 获取鞍座型式代号（dh）
        cursor.execute("""
                    SELECT 参数值 
                    FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = '拉杆直径'
                    LIMIT 1
                """, (product_id,))
        row_dh = cursor.fetchone()
        l = row_dh["参数值"] if row_dh and row_dh.get("参数值") not in (None, "", "None") else None

        if None not in (w, l):
            return f"Ø{l};L={w}"

        if l is not None:
            try:
                l = float(l)
                if 10 <= l <= 14:
                    rod_diameter = 10
                elif 14 < l < 25:
                    rod_diameter = 12
                elif 25 <= l <= 32:
                    rod_diameter = 16
                elif 32 < l <= 57:
                    rod_diameter = 27
                else:
                    rod_diameter = "[超出范围]"
                return f"Ø{rod_diameter},L={w}"
            except:
                return ""

    elif component_name == "螺母（拉杆）":
        conn = get_connection(**db_config1)
        cursor = conn.cursor()
        # 获取鞍座型式代号（dh）
        cursor.execute("""
                    SELECT 参数值 
                    FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = '拉杆直径'
                    LIMIT 1
                """, (product_id,))
        row_dh = cursor.fetchone()

        l = row_dh["参数值"] if row_dh and row_dh.get("参数值") not in (None, "", "None") else None
        if l:
            return f"M{l}"
        else:
            w = get_value(data, "固定管板", "换热管外径")
            if w is not None:
                try:
                    w = float(w)
                    if 10 <= w <= 14:
                        rod_diameter = 10
                    elif 14 < w < 25:
                        rod_diameter = 12
                    elif 25 <= w <= 32:
                        rod_diameter = 16
                    elif 32 < w <= 57:
                        rod_diameter = 27
                    else:
                        rod_diameter = "[超出范围]"
                    return f"M{rod_diameter}"
                except:
                    return ""

    elif component_name == "管箱侧垫片":
        w = get_value(data, "管箱法兰", "垫片名义外径")
        n = get_value(data, "管箱法兰", "垫片名义内径")
        dphd = get_dphd_from_db("管箱侧垫片", product_id) or 0
        if None not in (w, n):
            return f"Ø{w}/Ø{n}；δ={dphd}"
    elif component_name == "头盖法兰":
        w = get_value(data, "头盖法兰", "法兰名义外径")
        n = get_value(data, "头盖法兰", "法兰名义内径")
        h = get_value(data, "头盖法兰", "法兰总高")
        if None not in (w, n, h):
            return f"Ø{w}/Ø{n}；H={h}"
    elif component_name == "前端管箱头盖法兰":
        w = get_value(data, "头盖法兰", "法兰名义外径")
        n = get_value(data, "头盖法兰", "法兰名义内径")
        h = get_value(data, "头盖法兰", "法兰总高")
        if None not in (w, n, h):
            return f"Ø{w}/Ø{n}；H={h}"
    elif component_name == "管箱平盖":
        w = get_value(data, "管箱平盖", "法兰名义外径") or 0
        h = get_value(data, "管箱平盖", "法兰名义厚度") or 0
        if None not in (w, h):
            return f"Ø{w}；δ={h}"
    elif component_name == "前端管箱平盖":
        w = get_value(data, "管箱平盖", "法兰名义外径") or 0
        h = get_value(data, "管箱平盖", "法兰名义厚度") or 0
        if None not in (w, h):
            return f"Ø{w}；δ={h}"
    elif component_name == "平盖垫片":
        w = get_value(data, "头盖法兰", "垫片名义外径") or 0
        n = get_value(data, "头盖法兰", "垫片名义内径") or 0
        dphd = get_dphd_from_db("平盖垫片", product_id) or 0
        if None not in (w, n):
            return f"Ø{w}/Ø{n}；δ={dphd}"
    elif component_name == "前端管箱平盖垫片":
        w = get_value(data, "头盖法兰", "垫片名义外径") or 0
        n = get_value(data, "头盖法兰", "垫片名义内径") or 0
        dphd = get_dphd_from_db("前端管箱平盖垫片", product_id) or 0
        if None not in (w, n):
            return f"Ø{w}/Ø{n}；δ={dphd}"
    elif component_name == "壳体法兰":
        w = get_value(data, "壳体法兰", "法兰名义外径") or 0
        n = get_value(data, "壳体法兰", "法兰名义内径") or 0
        h = get_value(data, "壳体法兰", "法兰总高") or 0
        if None not in (w, n, h):
            return f"Ø{w}/Ø{n}；H={h}"
    elif component_name == "壳体大端圆筒":
        id_ = get_value(data, "大端壳体圆筒", "圆筒内径") or 0
        t = get_value(data, "大端壳体圆筒", "圆筒名义厚度") or 0
        l = get_value(data, "大端壳体圆筒", "圆筒长度") or 0
        fuceng = get_value(data, "大端壳体圆筒", "圆筒覆层厚度") or 0
        if None not in (id_, t, l):
            if fuceng not in (0, 0.0, "0", "0.0", None, "None"):
                return f"ID{id_}×({t}+{fuceng});L={l}"
            else:
                return f"ID{id_}×{t};L={l}"
        else:
            return f"ID{id_}×{t};L={l}"
    elif component_name == "大端壳体圆筒加强段":
        id_ = get_value(data, "大端壳体圆筒加强段", "圆筒内径") or 0
        t = get_value(data, "大端壳体圆筒加强段", "圆筒名义厚度") or 0
        l = get_value(data, "大端壳体圆筒加强段", "圆筒长度") or 0
        fuceng = get_value(data, "大端壳体圆筒加强段", "圆筒覆层厚度") or 0
        if None not in (id_, t, l):
            if fuceng not in (0, 0.0, "0", "0.0", None, "None"):
                return f"ID{id_}×({t}+{fuceng});L={l}"
            else:
                return f"ID{id_}×{t};L={l}"
        else:
            return f"ID{id_}×{t};L={l}"
    elif component_name == "壳体小端圆筒":
        id_ = get_value(data, "小端壳体圆筒", "圆筒内径") or 0
        t = get_value(data, "小端壳体圆筒", "圆筒名义厚度") or 0
        l = get_value(data, "小端壳体圆筒", "圆筒长度") or 0
        fuceng = get_value(data, "小端壳体圆筒", "圆筒覆层厚度") or 0
        if None not in (id_, t, l):
            if fuceng not in (0, 0.0, "0", "0.0", None, "None"):
                return f"ID{id_}×({t}+{fuceng});L={l}"
            else:
                return f"ID{id_}×{t};L={l}"
        else:
            return f"ID{id_}×{t};L={l}"
    elif component_name == "壳体圆筒":
        id_ = get_value(data, "壳体圆筒", "圆筒内径") or 0
        t = get_value(data, "壳体圆筒", "圆筒名义厚度") or 0
        l = get_value(data, "壳体圆筒", "圆筒长度") or 0
        fuceng = get_value(data, "壳体圆筒", "圆筒覆层厚度") or 0
        if None not in (id_, t, l):
            if fuceng not in (0, 0.0, "0", "0.0", None, "None"):
                return f"ID{id_}×({t}+{fuceng});L={l}"
            else:
                return f"ID{id_}×{t};L={l}"
        else:
            return f"ID{id_}×{t};L={l}"
    elif component_name == "壳体封头":
        dh = get_value(data, "壳体封头", "封头类型代号") or 0
        d = get_value(data, "壳体封头", "椭圆形封头计算内径") or 0
        t = get_value(data, "壳体封头", "椭圆形封头名义厚度") or 0
        t_plus = get_value(data, "壳体封头", "椭圆形封头最小成型厚度") or 0
        h = get_value(data, "壳体封头", "椭圆形封头直边高度") or 0
        fuceng = get_value(data, "壳体封头", "椭圆形封头覆层厚度") or 0

        if None not in (dh, d, t, h):
            if fuceng not in (0, 0.0, "0", "0.0", None, "None"):
                return f"{dh}{d}×({t}({t_plus})+{fuceng});h={h}"
            else:
                return f"{dh}{d}×{t}({t_plus});h={h}"


    elif component_name == "支座":
        conn = get_connection(**db_config1)
        cursor = conn.cursor()
        # 获取鞍座型式代号（dh）
        cursor.execute("""
            SELECT Value 
            FROM 产品设计活动表_元件计算结果表
            WHERE 产品ID = %s AND Name = '鞍座形式'
            LIMIT 1
        """, (product_id,))
        row_dh = cursor.fetchone()
        zhizuo_xingshi = row_dh["Value"] if row_dh and row_dh.get("Value") not in (None, "", "None") else None
        cursor.execute("""
                    SELECT 参数值 
                    FROM 产品设计活动表_元件附加参数合并表
                    WHERE 产品ID = %s AND 参数名称 = '支座型式'
                    LIMIT 1
                """, (product_id,))
        row_dh = cursor.fetchone()
        zhizuo_xinghao = row_dh["参数值"] if row_dh and row_dh.get("参数值") not in (None, "", "None") else None

        # 获取鞍座型式代号（dh）

        h = get_value(data, "鞍座", "鞍式支座高度h") or 0

        if zhizuo_xingshi is not None and h is not None:
            return f"{zhizuo_xinghao} {zhizuo_xingshi},h={h}"
        elif zhizuo_xingshi is not None:
            return f"{zhizuo_xinghao} {zhizuo_xingshi}"
        else:
            return ""

    elif component_name == "滑动鞍座":
        conn = get_connection(**db_config1)
        cursor = conn.cursor()
        # 获取鞍座型式代号（dh）
        cursor.execute("""
            SELECT 参数值 
            FROM 产品设计活动表_元件附加参数表 
            WHERE 产品ID = %s AND 元件名称 = '滑动鞍座' AND 参数名称 = '鞍座型式代号'
            LIMIT 1
        """, (product_id,))
        row_dh = cursor.fetchone()
        dh = row_dh["参数值"] if row_dh and row_dh.get("参数值") not in (None, "", "None") else None
        h = get_value(data, "鞍座", "鞍式支座高度h") or 0
        if dh is not None and h is not None:
            return f"{dh},h={h}"
        elif dh is not None:
            return f"{dh}"
        elif h is not None:
            return f"h={h}"
        else:
            return ""
    elif component_name in ("螺柱（管箱法兰）", "螺柱（前端管箱法兰）", "螺柱（后端管箱法兰）", "螺柱（壳体法兰）"):
        dh = get_value(data, "管箱法兰", "螺栓公称直径") or 0
        if dh is None:
            return None

        try:
            dh_val = int(re.search(r'\d+', str(dh)).group())
        except:
            dh_val = 0

        flange_thk_1 = get_value(data, "管箱法兰", "法兰名义厚度") or 0
        gasket_thk_1 = get_value(data, "管箱法兰", "垫片厚度") or 0
        flange_thk_2 = get_value(data, "壳体法兰", "法兰名义厚度") or 0
        gasket_thk_2 = get_value(data, "壳体法兰", "垫片厚度") or 0
        gbhd = get_value(data, "固定管板", "管板名义厚度")
        if not gbhd:
            gbhd = get_value(data, "固定管板", "管板名义厚度 δn'") or 0
        gbc = get_gbc_from_db(product_id) or 0

        ttgd = get_ttgd_from_db(product_id) or 0
        guanban_guancheng_fuceng = 0.0
        guanban_qiaocheng_fuceng = 0.0
        falan_fuceng = 0.0
        falan2_fuceng = 0.0

        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()

        cursor.execute("""
                    SELECT 参数名称, 参数值
                    FROM 产品设计活动表_元件附加参数表
                    WHERE 产品ID = %s
                      AND 元件名称 = '固定管板'
                      AND 参数名称 IN (
                          '管程侧覆层厚度',
                          '壳程侧覆层厚度',
                          '管程侧是否添加覆层',
                          '壳程侧是否添加覆层'
                      )
                """, (product_id,))

        rows = cursor.fetchall()
        if rows:
            params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}

            # 覆层厚度判断
            if params.get("管程侧是否添加覆层") == "否":
                guanban_guancheng_fuceng = 0.0
            else:
                guanban_guancheng_fuceng = float(params.get("管程侧覆层厚度", "0"))

            if params.get("壳程侧是否添加覆层") == "否":
                guanban_qiaocheng_fuceng = 0.0
            else:
                guanban_qiaocheng_fuceng = float(params.get("壳程侧覆层厚度", "0"))
        cursor.execute("""
                    SELECT 参数名称, 参数值
                    FROM 产品设计活动表_元件附加参数表
                    WHERE 产品ID = %s
                      AND 元件名称 = '管箱法兰'
                      AND 参数名称 IN (
                          '覆层厚度',
                          '是否添加覆层'
                      )
                """, (product_id,))

        rows = cursor.fetchall()
        if rows:
            params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}

            # 覆层厚度判断
            if params.get("是否添加覆层") == "否":
                falan_fuceng = 0.0
            else:
                falan_fuceng = float(params.get("覆层厚度", "0"))
        cursor.execute("""
                           SELECT 参数名称, 参数值
                           FROM 产品设计活动表_元件附加参数表
                           WHERE 产品ID = %s
                             AND 元件名称 = '壳体法兰'
                             AND 参数名称 IN (
                                 '覆层厚度',
                                 '是否添加覆层'
                             )
                       """, (product_id,))

        rows = cursor.fetchall()
        if rows:
            params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}

            # 覆层厚度判断
            if params.get("是否添加覆层") == "否":
                falan2_fuceng = 0.0
            else:
                falan2_fuceng = float(params.get("覆层厚度", "0"))
        l = 20 + 2 * dh_val + flange_thk_1 + gasket_thk_1 + flange_thk_2 + gasket_thk_2 - 2 * ttgd + gbhd + guanban_qiaocheng_fuceng + guanban_guancheng_fuceng + falan_fuceng + falan2_fuceng
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
        row = cursor.fetchone()
        conn.close()

        if not row:
            raise ValueError(f"未找到 product_id={product_id} 对应的产品型式")

        product_type = row[0]
        if product_type in ("AEM", "BEM"):
            l = flange_thk_1 + gbhd + 20 + dh_val * 2 - ttgd - gbc + gasket_thk_1 + guanban_qiaocheng_fuceng + guanban_guancheng_fuceng + falan_fuceng
        l = math.ceil(l / 5) * 5

        return f"M{dh}x{l}"

    elif component_name == "螺柱（后端管箱封头）":
        dh = get_value(data, "管箱法兰", "螺栓公称直径") or 0
        if dh is None:
            return None

        try:
            dh_val = int(re.search(r'\d+', str(dh)).group())
        except:
            dh_val = 0

        flange_thk_1 = get_value(data, "管箱法兰", "法兰名义厚度") or 0
        gasket_thk_1 = get_value(data, "管箱法兰", "垫片厚度") or 0
        flange_thk_2 = get_value(data, "壳体法兰", "法兰名义厚度") or 0
        gasket_thk_2 = get_value(data, "壳体法兰", "垫片厚度") or 0
        gbhd = get_value(data, "固定管板", "管板名义厚度")
        if not gbhd:
            gbhd = get_value(data, "固定管板", "管板名义厚度 δn'") or 0
        gbc = get_gbc_from_db(product_id) or 0

        ttgd = get_ttgd_from_db(product_id) or 0

        l = 20 + 2 * dh_val + flange_thk_1 + gasket_thk_1 + flange_thk_2 + gasket_thk_2 - 2 * ttgd + gbhd
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
        row = cursor.fetchone()
        conn.close()

        if not row:
            raise ValueError(f"未找到 product_id={product_id} 对应的产品型式")

        product_type = row[0]
        if product_type in ("AEM", "BEM"):
            l = flange_thk_1 + gbhd + 20 + dh_val * 2 - ttgd - gbc
        l = math.ceil(l / 5) * 5

        return f"M{dh}x{l}"

    elif component_name in ("螺柱（外头盖法兰）", "螺柱（外头盖侧法兰）"):
        dh = get_value(data, "外头盖法兰", "螺栓公称直径") or 0
        if dh is None:
            return None

        try:
            dh_val = int(re.search(r'\d+', str(dh)).group())
        except:
            dh_val = 0

        flange_thk_1 = get_value(data, "外头盖法兰", "法兰名义厚度") or 0
        gasket_thk_1 = get_value(data, "外头盖法兰", "垫片厚度") or 0
        flange_thk_2 = get_value(data, "外头盖侧法兰", "法兰名义厚度") or 0
        gasket_thk_2 = get_value(data, "外头盖侧法兰", "垫片厚度") or 0
        gbhd = get_value(data, "固定管板", "管板名义厚度")
        if not gbhd:
            gbhd = get_value(data, "固定管板", "管板名义厚度 δn'") or 0
        gbc = get_gbc_from_db(product_id) or 0

        ttgd = get_waitougaittgd_from_db(product_id) or 0
        guanban_guancheng_fuceng = 0.0
        guanban_qiaocheng_fuceng = 0.0
        falan_fuceng = 0.0
        falan2_fuceng = 0.0

        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()

        cursor.execute("""
                            SELECT 参数名称, 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s
                              AND 元件名称 = '浮动管板'
                              AND 参数名称 IN (
                                  '管程侧覆层厚度',
                                  '壳程侧覆层厚度',
                                  '管程侧是否添加覆层',
                                  '壳程侧是否添加覆层'
                              )
                        """, (product_id,))

        rows = cursor.fetchall()
        if rows:
            params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}

            # 覆层厚度判断
            if params.get("管程侧是否添加覆层") == "否":
                guanban_guancheng_fuceng = 0.0
            else:
                guanban_guancheng_fuceng = float(params.get("管程侧覆层厚度", "0"))

            if params.get("壳程侧是否添加覆层") == "否":
                guanban_qiaocheng_fuceng = 0.0
            else:
                guanban_qiaocheng_fuceng = float(params.get("壳程侧覆层厚度", "0"))
        cursor.execute("""
                            SELECT 参数名称, 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s
                              AND 元件名称 = '外头盖法兰'
                              AND 参数名称 IN (
                                  '覆层厚度',
                                  '是否添加覆层'
                              )
                        """, (product_id,))

        rows = cursor.fetchall()
        if rows:
            params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}

            # 覆层厚度判断
            if params.get("是否添加覆层") == "否":
                falan_fuceng = 0.0
            else:
                falan_fuceng = float(params.get("覆层厚度", "0"))
        cursor.execute("""
                                   SELECT 参数名称, 参数值
                                   FROM 产品设计活动表_元件附加参数表
                                   WHERE 产品ID = %s
                                     AND 元件名称 = '外头盖侧法兰'
                                     AND 参数名称 IN (
                                         '覆层厚度',
                                         '是否添加覆层'
                                     )
                               """, (product_id,))

        rows = cursor.fetchall()
        if rows:
            params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}

            # 覆层厚度判断
            if params.get("是否添加覆层") == "否":
                falan2_fuceng = 0.0
            else:
                falan2_fuceng = float(params.get("覆层厚度", "0"))
        l = 20 + 2 * dh_val + flange_thk_1 + gasket_thk_1 + flange_thk_2 + ttgd + guanban_guancheng_fuceng + guanban_qiaocheng_fuceng + falan2_fuceng + falan_fuceng

        l = math.ceil(l / 5) * 5
        return f"M{dh}x{l}"
    elif component_name == "铭牌":
        return "组合件"
    elif component_name == "螺柱（浮头法兰）":
        dh = get_value(data, "浮头法兰", "螺栓公称直径") or 0
        if dh is None:
            return None

        try:
            dh_val = int(re.search(r'\d+', str(dh)).group())
        except:
            dh_val = 0

        flange_thk_1 = get_value(data, "浮头法兰", "法兰名义厚度") or 0
        gasket_thk_1 = get_value(data, "浮头法兰", "垫片厚度") or 0
        flange_thk_2 = get_value(data, "浮头法兰", "B型钩圈颈部厚度") or 0
        gbhd = get_value(data, "浮动管板", "管板名义厚度")
        if not gbhd:
            gbhd = get_value(data, "浮动管板", "管板名义厚度 δn'") or 0
        gbc = get_gbc_from_db(product_id) or 0
        ttgd = get_ttgd_from_db(product_id) or 0
        ftzpttgd = get_ftzhuangpeittgd_from_db(product_id) or 0
        futou_falan_guancheng_fuceng = 0.0
        futou_falan_qiaocheng_fuceng = 0.0
        fudong_guanban_guancheng_fuceng = 0.0
        fudong_guanban_qiaocheng_fuceng = 0.0

        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s
              AND 元件名称 = '浮头法兰'
              AND 参数名称 IN (
                  '管程侧覆层厚度',
                  '壳程侧覆层厚度',
                  '管程侧是否添加覆层',
                  '壳程侧是否添加覆层'
              )
        """, (product_id,))

        rows = cursor.fetchall()
        if rows:
            params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}

            # 覆层厚度判断
            if params.get("管程侧是否添加覆层") == "否":
                futou_falan_guancheng_fuceng = 0.0
            else:
                futou_falan_guancheng_fuceng = float(params.get("管程侧覆层厚度", "0"))

            if params.get("壳程侧是否添加覆层") == "否":
                futou_falan_qiaocheng_fuceng = 0.0
            else:
                futou_falan_qiaocheng_fuceng = float(params.get("壳程侧覆层厚度", "0"))
        cursor.execute("""
                    SELECT 参数名称, 参数值
                    FROM 产品设计活动表_元件附加参数表
                    WHERE 产品ID = %s
                      AND 元件名称 = '浮动管板'
                      AND 参数名称 IN (
                          '管程侧覆层厚度',
                          '壳程侧覆层厚度',
                          '管程侧是否添加覆层',
                          '壳程侧是否添加覆层'
                      )
                """, (product_id,))

        rows = cursor.fetchall()
        if rows:
            params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}

            # 覆层厚度判断
            if params.get("管程侧是否添加覆层") == "否":
                fudong_guanban_guancheng_fuceng = 0.0
            else:
                fudong_guanban_guancheng_fuceng = float(params.get("管程侧覆层厚度", "0"))

            if params.get("壳程侧是否添加覆层") == "否":
                fudong_guanban_qiaocheng_fuceng = 0.0
            else:
                fudong_guanban_qiaocheng_fuceng = float(params.get("壳程侧覆层厚度", "0"))

        l = 20 + 2 * dh_val + flange_thk_1 + gasket_thk_1 + flange_thk_2 - ttgd + gbhd - 1.5 - ftzpttgd + futou_falan_guancheng_fuceng + futou_falan_qiaocheng_fuceng + fudong_guanban_guancheng_fuceng + fudong_guanban_qiaocheng_fuceng
        l = math.ceil(l / 5) * 5
        return f"M{dh}x{l}"
    elif component_name == "螺母（后端管箱封头）":
        dh = _get_component_int_value(data, ("管箱法兰",), "螺栓公称直径")

        if dh is not None:
            return f"M{dh}"

    elif component_name == "螺母（管箱法兰）":
        dh = _get_component_int_value(data, ("管箱法兰",), "螺栓公称直径")

        if dh is not None:
            return f"M{dh}"
    elif component_name == "螺母（前端管箱法兰）":
        dh = _get_component_int_value(
            data,
            ("前端管箱法兰", "管箱法兰"),
            "螺栓公称直径",
        )

        if dh is not None:
            return f"M{dh}"
    elif component_name == "螺母（后端管箱法兰）":
        dh = _get_component_int_value(
            data,
            ("后端管箱法兰", "管箱法兰"),
            "螺栓公称直径",
        )

        if dh is not None:
            return f"M{dh}"
    elif component_name == "螺母（外头盖法兰）":
        dh = _get_component_int_value(data, ("外头盖法兰",), "螺栓公称直径")

        if dh is not None:
            return f"M{dh}"

    elif component_name == "螺母（浮头法兰）":
        dh = _get_component_int_value(data, ("浮头法兰",), "螺栓公称直径")
        if dh is not None:
            return f"M{dh}"
    elif component_name in ("螺柱（管箱平盖）", "螺柱（前端管箱平盖）", "螺柱（前端管箱头盖法兰）", "螺柱（头盖法兰）"):
        is_front_flat_cover = "前端" in component_name
        flat_cover_sections = (
            ("前端管箱平盖", "管箱平盖")
            if is_front_flat_cover
            else ("管箱平盖",)
        )
        head_flange_sections = (
            ("前端管箱头盖法兰", "头盖法兰")
            if is_front_flat_cover
            else ("头盖法兰",)
        )
        dh = _get_component_int_value(data, flat_cover_sections, "螺栓公称直径")

        if dh is None:
            print(f"⚠️ {component_name} 缺少螺栓公称直径，规格留空")
            return None

        dh_val = dh

        flange_thk_1 = _get_first_component_value(data, flat_cover_sections, "法兰名义厚度") or 0
        gasket_thk_1 = _get_first_component_value(data, flat_cover_sections, "垫片厚度") or 0
        flange_thk_2 = _get_first_component_value(data, head_flange_sections, "法兰名义厚度") or 0
        gasket_thk_2 = _get_first_component_value(data, head_flange_sections, "垫片厚度") or 0
        gbhd = get_value(data, "固定管板", "管板名义厚度")
        if not gbhd:
            gbhd = get_value(data, "固定管板", "管板名义厚度 δn'") or 0
        guanban_guancheng_fuceng = 0.0
        guanban_qiaocheng_fuceng = 0.0
        falan_fuceng = 0.0
        falan2_fuceng = 0.0
        ttgd = (
            get_qdzhuangpeittgd_from_db(product_id)
            if is_front_flat_cover
            else get_zhuangpeittgd_from_db(product_id)
        ) or 0
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()

        cursor.execute("""
                    SELECT 参数名称, 参数值
                    FROM 产品设计活动表_元件附加参数表
                    WHERE 产品ID = %s
                      AND 元件名称 = '固定管板'
                      AND 参数名称 IN (
                          '管程侧覆层厚度',
                          '壳程侧覆层厚度',
                          '管程侧是否添加覆层',
                          '壳程侧是否添加覆层'
                      )
                """, (product_id,))

        rows = cursor.fetchall()
        if rows:
            params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}

            # 覆层厚度判断
            if params.get("管程侧是否添加覆层") == "否":
                guanban_guancheng_fuceng = 0.0
            else:
                guanban_guancheng_fuceng = float(params.get("管程侧覆层厚度", "0"))

            if params.get("壳程侧是否添加覆层") == "否":
                guanban_qiaocheng_fuceng = 0.0
            else:
                guanban_qiaocheng_fuceng = float(params.get("壳程侧覆层厚度", "0"))
        cursor.execute("""
                    SELECT 参数名称, 参数值
                    FROM 产品设计活动表_元件附加参数表
                    WHERE 产品ID = %s
                      AND 元件名称 = '管箱平盖'
                      AND 参数名称 IN (
                          '覆层厚度',
                          '是否添加覆层'
                      )
                """, (product_id,))

        rows = cursor.fetchall()
        if rows:
            params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}

            # 覆层厚度判断
            if params.get("是否添加覆层") == "否":
                falan_fuceng = 0.0
            else:
                falan_fuceng = float(params.get("覆层厚度", "0"))
        cursor.execute("""
                            SELECT 参数名称, 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s
                              AND 元件名称 = '头盖法兰'
                              AND 参数名称 IN (
                                  '覆层厚度',
                                  '是否添加覆层'
                              )
                        """, (product_id,))

        rows = cursor.fetchall()
        if rows:
            params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}

            # 覆层厚度判断
            if params.get("是否添加覆层") == "否":
                falan2_fuceng = 0.0
            else:
                falan2_fuceng = float(params.get("覆层厚度", "0"))
        l = 20 + 2 * dh_val + flange_thk_1 + gasket_thk_1 + flange_thk_2 - ttgd + guanban_guancheng_fuceng + guanban_qiaocheng_fuceng + falan_fuceng + falan2_fuceng
        l = math.ceil(l / 5) * 5
        return f"M{dh}x{l}"

    elif component_name == "螺母（管箱平盖）":
        dh = _get_component_int_value(data, ("管箱平盖",), "螺栓公称直径")
        if dh is not None:
            return f"M{dh}"
    elif component_name == "螺母（前端管箱平盖）":
        dh = _get_component_int_value(
            data,
            ("前端管箱平盖", "管箱平盖"),
            "螺栓公称直径",
        )
        if dh is not None:
            return f"M{dh}"
    elif component_name == "吊环螺钉" or component_name == "环首螺钉":
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
            (product_id, "吊环螺钉规格")
        )
        row_diaohuan = cur.fetchone()
        dh = row_diaohuan[0]
        if dh is not None:
            return f"{dh}"
        else:
            return ""
    # elif component_name == "接管(钢管)":
    #     dh = get_value(data, "管程入口接管", "接管外径") or 0
    #     bh = get_value(data, "管程入口接管", "接管外径") or 0
    #     l = get_value(data, "管程入口接管", "接管实际外伸长度") or 0+get_value(data, "管程入口接管", "接管实际内伸长度") or 0
    #     if None not in (dh, bh):
    #         return f"OD{dh}×{bh};L={l}"
    # elif component_name == "接管(钢管)":
    #     dh = get_value(data, "管程入口接管", "接管外径") or 0
    #     bh = get_value(data, "管程入口接管", "接管名义厚度") or 0
    #     l = get_value(data, "管程入口接管", "接管实际外伸长度") or 0+get_value(data, "管程入口接管", "接管实际内伸长度") or 0
    #     if None not in (dh, bh):
    #         return f"OD{dh}×{bh};L={l}"
    # elif component_name == "接管(钢板)":
    #     dh = get_value(data, "管程入口接管", "接管外径") or 0
    #     bh = get_value(data, "管程入口接管", "接管名义厚度") or 0
    #     l = get_value(data, "管程入口接管", "接管实际外伸长度") or 0+get_value(data, "管程入口接管", "接管实际内伸长度") or 0
    #     if None not in (dh, bh):
    #         return f"OD{dh}×{bh};L={l}"
    # elif component_name == "接管(钢锻件)":
    #     dh = get_value(data, "管程入口接管", "接管外径") or 0
    #     bh = get_value(data, "管程入口接管", "接管内径") or 0
    #     l = get_value(data, "管程入口接管", "接管实际外伸长度") or 0+get_value(data, "管程入口接管", "接管实际内伸长度") or 0
    #     if None not in (dh, bh):
    #         return f"Ø{dh}/Ø{bh}；L={l}"
    # 你可以在此添加更多规则：
    # elif component_name == "其他元件名称":
    #     return "你定义的规格格式"
    elif component_name == "铭牌支架":
        return "δ=5"
    elif component_name == "铭牌板":
        return "δ=2"
    elif component_name == "铆钉":
        return "Ø3×14"
    elif component_name.endswith("接管"):
        print(component_name)
        od = get_value(data, component_name, "接管大端外径") or 0
        thick = get_value(data, component_name, "接管大端壁厚") or 0
        l1 = get_value(data, component_name, "接管总外伸高度") or 0
        c = get_value(data, component_name, "开孔元件内径") / 2 or 0
        a = get_value(data, component_name, "接管大端外径") / 2 or 0
        h = 0
        if a == 0:
            a = get_value(data, component_name, "接管小端外径") / 2 or 0
        conn_product = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        conn_material = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        conn_component = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="元件库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )

        cur = conn_product.cursor()
        cur2 = conn_material.cursor()
        cur3 = conn_component.cursor()

        # === 1. 获取管口表数据（排气口、排液口）===
        cur.execute("""
                SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s
            """, (product_id,))
        ports = cur.fetchall()
        print(ports, "ports")
        print(product_id, "pro_id")
        # === 2. 获取管口类型选择表 (尺寸/压力类型) ===
        cur.execute("""
                SELECT 公称尺寸类型, 公称压力类型
                FROM 产品设计活动表_管口类型选择表
                WHERE 产品ID = %s
            """, (product_id,))
        type_info = cur.fetchone()  # 一个产品只会有一行配置

        # 默认类型（防止为空）
        size_type = type_info["公称尺寸类型"] if type_info else "DN"
        press_type = type_info["公称压力类型"] if type_info else "PN"

        # === 3. 获取公称尺寸 NPS → DN 对照表 ===
        cur3.execute("SELECT NPS, DN FROM 公称尺寸表")
        nps_rows = cur3.fetchall()
        nps_map = {str(r["NPS"]).strip(): str(r["DN"]).strip() for r in nps_rows}

        # === 4. 获取管法兰质量表数据 ===
        cur2.execute("SELECT * FROM 管法兰质量表")
        flange_rows = cur2.fetchall() or []

        def clean_val(v):
            """清洗 0.0、'None'、空格等无效值"""
            if v is None:
                return ""
            v = str(v).strip()
            if v.lower() == "none":
                return ""
            return v

        func_like = component_name[:-2] if component_name.endswith("接管") else component_name

        h = 0.0
        matched_type_db = ""
        matched_row = None  # ✅ 保存最终命中的row，用于取N1

        for port in ports:
            func = clean_val(port.get("管口功能"))

            # ✅ 只处理与当前 component_name 对应的那一个功能
            if func != func_like:
                continue

            std = clean_val(port.get("法兰标准"))
            size = clean_val(port.get("公称尺寸"))
            pressure = clean_val(port.get("压力等级"))
            flange_type = clean_val(port.get("法兰型式"))
            print(flange_type, "flange_type")
            face_type = clean_val(port.get("密封面型式"))
            print(face_type, "face_type")
            if size_type.upper() == "NPS":
                size = nps_map.get(size, size)

            for row in flange_rows:
                std_db = clean_val(row.get("标准"))
                dn_db = clean_val(row.get("DN"))
                pn_db = clean_val(row.get("PN"))
                cls_db = clean_val(row.get("Class"))
                type_db = clean_val(row.get("法兰型式代号"))

                if std_db and std_db != std:
                    continue
                if dn_db and dn_db != size:
                    continue

                if press_type.upper() == "PN":
                    if pn_db and pn_db != pressure:
                        continue
                elif press_type.upper() == "CLASS":
                    if cls_db and cls_db != pressure:
                        continue

                if type_db and flange_type and type_db != flange_type:
                    continue

                # ✅ 命中：取h，并记录命中行
                if face_type:
                    face_col = f"H{face_type}"
                    print(face_type, "face_type")
                    hv = clean_val(row.get(face_col)) if face_col in row else ""
                    print(hv, "hv")
                    try:
                        h = float(hv) if hv != "" else 0.0
                    except Exception:
                        h = 0.0

                    matched_type_db = type_db
                    matched_row = row

        # ✅ LWN：用 N1/2 与 a 取大者替换 a
        if matched_type_db == "LWN" and matched_row is not None:
            n1v = clean_val(matched_row.get("N1"))  # ⚠️ 若你表头不是N1，改这里
            try:
                n1 = float(n1v) if n1v != "" else 0.0
            except Exception:
                n1 = 0.0

            a = max(float(a or 0.0), n1 / 2.0)

        # === 公式（防sqrt负数）===
        inside = float(c or 0.0) ** 2 - float(a or 0.0) ** 2
        if inside < 0:
            inside = 0.0

        sqrt_part = math.sqrt(inside)
        small_thick = float(get_value(data, component_name, "接管小端壁厚") or 0.0)

        if matched_type_db in ("SO", "PL"):
            H = float(l1 or 0.0) - 1 - small_thick - sqrt_part
        else:
            # 其余情况保持你原来的算法，包括 LWN
            H = float(l1 or 0.0) - float(h or 0.0) - sqrt_part

        H = round(H, 2)
        print("料单")
        print(l1, "l1")
        print(h, "h")
        print(c, "c")
        print(a, "a")
        print(inside, "inside")
        print(H, "H")
        if None not in (od, thick):
            return f"OD{od}×{thick};L={H}"

        return None


# ============================================================
# 新增辅助判断：只用于“空参数元件是否显示”
# 原有 get_value / load_json_data / generate_spec 等方法保持不变。
# ============================================================
def _is_empty_component_param_value(value):
    """None、空串、None/null/nan 文本、NaN 视为空；0 仍视为有效值。"""
    if value is None:
        return True

    if isinstance(value, float):
        try:
            if math.isnan(value):
                return True
        except Exception:
            pass

    s = str(value).strip()
    if s == "":
        return True

    return s.lower() in ("none", "null", "nan")


def _component_source_candidates(component_name):
    """拆分件回到原元件判断参数，其余元件使用自身名称。"""
    name = str(component_name or "").strip()
    aliases = {
        "前端封头": ("封头",),
        "后端封头": ("封头",),
        # 圆筒不拆分；有效性判断同时识别数据库“圆筒”和计算数据“容器圆筒”。
        "圆筒": ("圆筒", "容器圆筒"),
        # 加强圈是否存在，以“容器圆筒加强圈”的计算结果为准。
        "加强圈": ("加强圈", "容器圆筒加强圈"),
    }
    return aliases.get(name, (name,))


def _component_all_params_empty(product_id, component_name):
    """
    对所有元件统一判断：如果其源元件在附加参数表中存在记录，
    且这些记录全部没有有效参数值，则视为无用元件。
    拆分件按原“封头/圆筒”判断。
    """
    conn = None
    cursor = None
    try:
        candidates = _component_source_candidates(component_name)
        placeholders = ",".join(["%s"] * len(candidates))
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT 元件名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 IN ({placeholders})
            """,
            (product_id, *candidates),
        )
        rows = cursor.fetchall() or []
        if not rows:
            return False
        return all(_is_empty_component_param_value(r.get("参数值")) for r in rows)
    except Exception as e:
        print(f"⚠️ 检查元件参数是否为空失败：{component_name}，{e}")
        return False
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


def _is_meaningful_component_source_value(value):
    """
    用于判断“这个元件是否真的有数据”。

    与普通参数取值不同：这里把纯 0 也视为“没有有效结构数据”，
    因为很多未参与设计的元件会被计算程序补成 0，不能因此保留在材料清单里。
    非数值文本（例如材料牌号、是/否、型号）仍视为有效。
    """
    if _is_empty_component_param_value(value):
        return False

    s = str(value).strip()
    if s.lower() in {"/", "-", "无", "n/a", "na"}:
        return False

    try:
        number = float(s.replace(",", ""))
        if math.isnan(number):
            return False
        return abs(number) > 1e-12
    except Exception:
        # 兼容“0mm / 0.0 kg / Q235B”之类字符串：
        # 只要包含数字，就按其中所有数字是否全为0判断。
        nums = re.findall(r"[-+]?\d+(?:\.\d+)?", s)
        if nums:
            try:
                return any(abs(float(x)) > 1e-12 for x in nums)
            except Exception:
                pass
        return True


def _resolve_source_component_mass(data, product_id, component_name, existing_value=None):
    """优先使用原行质量；为空/0 时，从原元件 JSON 或计算结果表补取毛坯单重。"""
    def mass_number(value):
        if not _is_meaningful_component_source_value(value):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value).replace(",", ""))
        if match:
            try:
                number = float(match.group(0))
                return number if abs(number) > 1e-12 else None
            except Exception:
                return None
        return None

    existing_number = mass_number(existing_value)
    if existing_number is not None:
        return existing_number

    field_priority = (
        "椭圆形封头质量 kg",
        "封头质量 kg",
        "封头重量kg",
        "封头重量 kg",
        "圆筒重量kg",
        "圆筒质量 kg",
        "质量 kg",
        "重量kg",
    )

    dict_out = (data or {}).get("DictOutDatas") or {}
    obj = dict_out.get(component_name) if isinstance(dict_out, dict) else None
    datas = obj.get("Datas") if isinstance(obj, dict) else None
    if isinstance(datas, list):
        by_name = {
            str(item.get("Name") or "").strip(): item.get("Value")
            for item in datas if isinstance(item, dict)
        }
        for field_name in field_priority:
            value = by_name.get(field_name)
            number = mass_number(value)
            if number is not None:
                return number

        # 字段名可能略有差异，最后按“质量/重量”兜底。
        for item in datas:
            if not isinstance(item, dict):
                continue
            field_name = str(item.get("Name") or "").strip()
            value = item.get("Value")
            if "质量" in field_name or "重量" in field_name:
                number = mass_number(value)
                if number is not None:
                    return number

    conn = None
    cursor = None
    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
        cursor = conn.cursor()
        cursor.execute("""
            SELECT Name, Value
            FROM 产品设计活动表_元件计算结果表
            WHERE 产品ID = %s AND 元件名称 = %s
        """, (product_id, component_name))
        rows = cursor.fetchall() or []

        row_map = {str(r.get("Name") or "").strip(): r.get("Value") for r in rows}
        for field_name in field_priority:
            value = row_map.get(field_name)
            number = mass_number(value)
            if number is not None:
                return number

        for r in rows:
            field_name = str(r.get("Name") or "").strip()
            value = r.get("Value")
            if "质量" in field_name or "重量" in field_name:
                number = mass_number(value)
                if number is not None:
                    return number
    except Exception as e:
        print(f"⚠️ 获取{component_name}质量失败：{e}")
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

    return None


def _remove_all_unused_components(sheet, product_id, data, preserved_names=()):
    """
    最终统一清理所有无用元件（v7）。

    核心规则：
    - 数量=1、材料、牌号、标准、供货状态、型式等不能单独证明元件有效；
    - 结构/尺寸/计算参数必须至少有一个非零有效值，或规格中至少有一个非零尺寸，
      或四个质量字段中至少有一个非零质量；
    - 所有垫片额外执行强规则：规格全0/空 且 质量全0/空/"/" => 删除；
    - 加强圈额外执行强规则：只有“容器圆筒加强圈”存在非零有效计算结果才保留；
    - 管口补强圈：对应接管计算输出“是否使用补强圈”不为“是”时，优先删除；
    - 兼容 B 列已经被拼成“名称+规格”的情况，不再只依赖名称完全相等。
    """
    removed_nozzle_rings = remove_unused_nozzle_reinforcement_rings(sheet, data)
    param_rows = {}
    calc_rows = {}
    conn = None
    cursor = None

    def is_metadata_field(field_name):
        name = str(field_name or "").strip()
        metadata_tokens = (
            "材料", "标准", "供货", "锻件",
            "型式", "形式", "类型", "类别",
            "名称", "牌号", "代号", "等级", "级别",
            "是否", "备注", "说明", "用途",
            "状态", "结果", "校核", "提示", "错误",
        )
        return any(token in name for token in metadata_tokens)

    def is_structural_value(field_name, value):
        if is_metadata_field(field_name):
            return False
        return _is_meaningful_component_source_value(value)

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 元件名称, 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s
        """, (product_id,))
        for r in cursor.fetchall() or []:
            n = str(r.get("元件名称") or "").strip()
            if n:
                param_rows.setdefault(n, []).append((r.get("参数名称"), r.get("参数值")))

        cursor.execute("""
            SELECT 元件名称, Name, Value
            FROM 产品设计活动表_元件计算结果表
            WHERE 产品ID = %s
        """, (product_id,))
        for r in cursor.fetchall() or []:
            n = str(r.get("元件名称") or "").strip()
            if n:
                calc_rows.setdefault(n, []).append((r.get("Name"), r.get("Value")))
    except Exception as e:
        print(f"⚠️ [CUNGUIGE-CLEAN-V7] 数据库读取失败：{e}")
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

    dict_out = (data or {}).get("DictOutDatas") or {}

    # 用于兼容“名称已经拼上规格”的场景。
    known_names = set(param_rows) | set(calc_rows)
    if isinstance(dict_out, dict):
        known_names |= {str(k).strip() for k in dict_out.keys() if str(k).strip()}
    known_names |= {
        "加强圈", "平盖垫片", "设备法兰垫片",
        "前端封头", "后端封头", "封头", "圆筒",
        "平盖", "设备法兰", "锥壳", "堰板",
    }

    def resolve_base_name_and_spec(raw_name, staging_spec):
        raw_name = str(raw_name or "").strip()
        spec = str(staging_spec or "").strip()

        # 正常流程：B=名称，W=规格。
        if raw_name in known_names:
            return raw_name, spec

        # 如果 B 已经是“名称+规格”，优先按最长元件名切分。
        matches = [n for n in known_names if n and raw_name.startswith(n)]
        if matches:
            base = max(matches, key=len)
            suffix = raw_name[len(base):].strip()
            if not spec:
                spec = suffix
            return base, spec

        return raw_name, spec

    def json_section_has_nonzero_calculation(section_name):
        obj = dict_out.get(section_name) if isinstance(dict_out, dict) else None
        datas = obj.get("Datas") if isinstance(obj, dict) else None
        if not isinstance(datas, list) or not datas:
            return False
        for item in datas:
            if not isinstance(item, dict):
                continue
            field_name = str(item.get("Name") or "").strip()
            if is_metadata_field(field_name):
                continue
            if _is_meaningful_component_source_value(item.get("Value")):
                return True
        return False

    def json_has_structural_value(candidates):
        names = list(candidates)
        if "圆筒" in names and "容器圆筒" not in names:
            names.append("容器圆筒")
        for candidate in names:
            obj = dict_out.get(candidate) if isinstance(dict_out, dict) else None
            datas = obj.get("Datas") if isinstance(obj, dict) else None
            if not isinstance(datas, list):
                continue
            for item in datas:
                if isinstance(item, dict) and is_structural_value(item.get("Name"), item.get("Value")):
                    return True
        return False

    def output_has_meaningful_value(value):
        if not _is_meaningful_component_source_value(value):
            return False
        s = str(value).strip()
        nums = re.findall(r"[-+]?\d+(?:\.\d+)?", s)
        if nums:
            try:
                return any(abs(float(x)) > 1e-12 for x in nums)
            except Exception:
                return False
        # 非数值输出只有在不是占位符时才有效。
        return s.lower() not in {"", "none", "null", "nan", "/", "-", "无", "n/a", "na"}

    rows_to_delete = []
    preserved_names = set(preserved_names)
    print("🔎 [CUNGUIGE-CLEAN-V7] 开始最终无用元件清理")

    for row in iter_material_rows(sheet):
        name_cell = row[MATERIAL_NAME_COL - 1]
        raw_name = str(name_cell.value or "").strip()
        if not raw_name:
            continue
        # 已通过附件表“管口号”关联的四项明细，缺少规格/质量时仍须保留名称。
        if raw_name in preserved_names:
            continue

        staging_spec = row[MATERIAL_SPEC_STAGING_COL - 1].value
        name, spec = resolve_base_name_and_spec(raw_name, staging_spec)

        candidates = _component_source_candidates(name)
        param_values = [item for candidate in candidates for item in param_rows.get(candidate, [])]
        calc_values = [item for candidate in candidates for item in calc_rows.get(candidate, [])]

        has_structural_source = (
            any(is_structural_value(field, value) for field, value in param_values)
            or any(is_structural_value(field, value) for field, value in calc_values)
            or json_has_structural_value(candidates)
        )

        rough_unit = row[MATERIAL_UNIT_WEIGHT_COL - 1].value
        rough_total = row[MATERIAL_TOTAL_WEIGHT_COL - 1].value
        formed_unit = row[MATERIAL_FORMED_UNIT_WEIGHT_COL - 1].value
        formed_total = row[MATERIAL_FORMED_TOTAL_WEIGHT_COL - 1].value
        mass_values = (rough_unit, rough_total, formed_unit, formed_total)

        has_real_spec = output_has_meaningful_value(spec)
        has_real_mass = any(output_has_meaningful_value(v) for v in mass_values)
        has_real_output = has_real_spec or has_real_mass

        # 加强圈：必须由“容器圆筒加强圈”计算结果证明存在。
        if name == "加强圈" or raw_name.startswith("加强圈"):
            ring_ok = json_section_has_nonzero_calculation("容器圆筒加强圈")
            print(f"🔎 [CUNGUIGE-CLEAN-V7] 加强圈: ring_ok={ring_ok}, raw={raw_name!r}")
            if not ring_ok:
                rows_to_delete.append(name_cell.row)
                print("🗑️ [CUNGUIGE-CLEAN-V7] 删除：加强圈（容器圆筒加强圈未通过/无有效非零结果）")
                continue

        # 所有垫片：规格全0/空 且质量全0/空/"/"，无条件删除。
        if "垫片" in name or "垫片" in raw_name:
            print(
                f"🔎 [CUNGUIGE-CLEAN-V7] 垫片 {raw_name!r}: "
                f"spec={spec!r}, spec_ok={has_real_spec}, mass={mass_values!r}, mass_ok={has_real_mass}"
            )
            if not has_real_spec and not has_real_mass:
                rows_to_delete.append(name_cell.row)
                print(f"🗑️ [CUNGUIGE-CLEAN-V7] 删除：{raw_name}（规格/质量均无有效值）")
                continue

        # 一般元件统一规则。
        if not has_structural_source and not has_real_output:
            rows_to_delete.append(name_cell.row)
            print(
                f"🗑️ [CUNGUIGE-CLEAN-V7] 删除：{raw_name} "
                f"(structural={has_structural_source}, spec={spec!r}, mass={mass_values!r})"
            )

    # 去重，避免同一行被多条规则重复加入。
    rows_to_delete = sorted(set(rows_to_delete))
    if rows_to_delete:
        print(f"🧹 [CUNGUIGE-CLEAN-V7] 实际删除行号: {rows_to_delete}")
        remove_material_rows(sheet, rows_to_delete)
    else:
        print("ℹ️ [CUNGUIGE-CLEAN-V7] 本次没有需要删除的行")

    return removed_nozzle_rings + len(rows_to_delete)


def _resolve_single_head_mass(data, product_id, component_name):
    """
    分别读取“前端封头”或“后端封头”的毛坯/成型质量。

    数据源优先级：
    1) 计算 JSON: DictOutDatas[component_name].Datas
    2) 产品设计活动表_元件计算结果表: 元件名称 = component_name

    返回: (rough_mass, formed_mass, source_desc)
    """
    def to_mass(value):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            try:
                num = float(value)
                return num if math.isfinite(num) and abs(num) > 1e-12 else None
            except Exception:
                return None
        s = str(value).strip().replace(',', '')
        if not s or s.lower() in {'none', 'null', 'nan', '/', '-', '无'}:
            return None
        try:
            num = float(s)
            return num if math.isfinite(num) and abs(num) > 1e-12 else None
        except Exception:
            m = re.search(r'[-+]?\d+(?:\.\d+)?', s)
            if not m:
                return None
            try:
                num = float(m.group(0))
                return num if math.isfinite(num) and abs(num) > 1e-12 else None
            except Exception:
                return None

    rough_names = (
        '椭圆形封头质量 kg', '椭圆形封头质量kg',
        '封头质量 kg', '封头质量kg', '封头质量',
        '封头重量 kg', '封头重量kg', '封头重量',
        '毛坯质量', '毛坯重量',
    )
    formed_names = (
        '椭圆形封头成型质量 kg', '椭圆形封头成型质量kg',
        '封头成型质量 kg', '封头成型质量kg', '封头成型质量',
        '封头成型重量 kg', '封头成型重量kg', '封头成型重量',
        '成型质量', '成型重量',
    )

    rough = None
    formed = None
    source_notes = []

    # 1) 计算 JSON：前端、后端分别读取自己的 section。
    dict_out = (data or {}).get('DictOutDatas') or {}
    if isinstance(dict_out, dict):
        obj = dict_out.get(component_name)
        datas = obj.get('Datas') if isinstance(obj, dict) else None
        if isinstance(datas, list):
            items = [x for x in datas if isinstance(x, dict)]
            by_name = {str(x.get('Name') or '').strip(): x.get('Value') for x in items}

            for field in rough_names:
                num = to_mass(by_name.get(field))
                if num is not None:
                    rough = num
                    source_notes.append(f'JSON:{component_name}/{field}={num}')
                    break

            for field in formed_names:
                num = to_mass(by_name.get(field))
                if num is not None:
                    formed = num
                    source_notes.append(f'JSON:{component_name}/{field}={num}')
                    break

            # 字段名称有差异时兜底：只认包含“质量”或“重量”的字段。
            for item in items:
                field = str(item.get('Name') or '').strip()
                num = to_mass(item.get('Value'))
                if num is None or not ('质量' in field or '重量' in field):
                    continue
                if '成型' in field or '成品' in field:
                    if formed is None:
                        formed = num
                        source_notes.append(f'JSON:{component_name}/{field}={num}')
                elif rough is None:
                    rough = num
                    source_notes.append(f'JSON:{component_name}/{field}={num}')

    # 2) 计算结果表：同样严格按照前端/后端元件名称查。
    conn = None
    cursor = None
    try:
        conn = pymysql.connect(
            host='localhost', user='root', password='123456',
            database='产品设计活动库', charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
        )
        cursor = conn.cursor()
        cursor.execute("""
            SELECT Name, Value
            FROM 产品设计活动表_元件计算结果表
            WHERE 产品ID = %s AND 元件名称 = %s
        """, (product_id, component_name))
        rows = cursor.fetchall() or []
        by_name = {str(r.get('Name') or '').strip(): r.get('Value') for r in rows}

        if rough is None:
            for field in rough_names:
                num = to_mass(by_name.get(field))
                if num is not None:
                    rough = num
                    source_notes.append(f'DB:{component_name}/{field}={num}')
                    break

        if formed is None:
            for field in formed_names:
                num = to_mass(by_name.get(field))
                if num is not None:
                    formed = num
                    source_notes.append(f'DB:{component_name}/{field}={num}')
                    break

        for r in rows:
            field = str(r.get('Name') or '').strip()
            num = to_mass(r.get('Value'))
            if num is None or not ('质量' in field or '重量' in field):
                continue
            if '成型' in field or '成品' in field:
                if formed is None:
                    formed = num
                    source_notes.append(f'DB:{component_name}/{field}={num}')
            elif rough is None:
                rough = num
                source_notes.append(f'DB:{component_name}/{field}={num}')
    except Exception as e:
        source_notes.append(f'DB查询失败:{e}')
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

    # 若计算文件只给一个质量，则成型单重沿用该质量。
    if formed is None:
        formed = rough
        if rough is not None:
            source_notes.append('成型质量未单列，继承该端封头毛坯质量')

    return rough, formed, '; '.join(source_notes) if source_notes else f'未找到{component_name}质量数据'


def _force_fill_split_head_weights(sheet, data, product_id):
    """
    最终保存前强制保证：
    - 前端封头数量 = 1，质量取计算文件“前端封头”
    - 后端封头数量 = 1，质量取计算文件“后端封头”
    - P=O，Q=暂存成型单重（因为数量均为1）
    """
    mass_map = {}
    for component_name in ('前端封头', '后端封头'):
        rough, formed, source_desc = _resolve_single_head_mass(
            data, product_id, component_name
        )
        mass_map[component_name] = (rough, formed)
        print(
            f'🔎 [HEAD-MASS-V9] {component_name}质量源: '
            f'rough={rough}, formed={formed}, source={source_desc}'
        )

    hit = set()
    for row in iter_material_rows(sheet):
        name = str(row[MATERIAL_NAME_COL - 1].value or '').strip()
        if name not in mass_map:
            continue

        hit.add(name)
        rough, formed = mass_map[name]

        # 两端数量都固定为 1。
        row[MATERIAL_QUANTITY_COL - 1].value = 1

        # 质量以各自计算文件结果为准；有值时直接覆盖拆分前继承的旧值。
        if rough is not None:
            row[MATERIAL_UNIT_WEIGHT_COL - 1].value = rough
            row[MATERIAL_TOTAL_WEIGHT_COL - 1].value = rough

        if formed is not None:
            row[MATERIAL_FORMED_UNIT_WEIGHT_COL - 1].value = formed
            row[MATERIAL_FORMED_TOTAL_WEIGHT_COL - 1].value = formed
        elif rough is not None:
            row[MATERIAL_FORMED_UNIT_WEIGHT_COL - 1].value = rough
            row[MATERIAL_FORMED_TOTAL_WEIGHT_COL - 1].value = rough

        print(
            f'✅ [HEAD-MASS-V9] {name}: 数量=1, '
            f'O={row[MATERIAL_UNIT_WEIGHT_COL - 1].value}, '
            f'P={row[MATERIAL_TOTAL_WEIGHT_COL - 1].value}, '
            f'Q={row[MATERIAL_FORMED_TOTAL_WEIGHT_COL - 1].value}'
        )

    for component_name in ('前端封头', '后端封头'):
        if component_name not in hit:
            print(f'⚠️ [HEAD-MASS-V9] 材料清单中未找到{component_name}')
        elif mass_map[component_name][0] is None:
            print(
                f'⚠️ [HEAD-MASS-V9] 未找到“{component_name}”的有效质量值；'
                '已保留该行已有质量，不写0占位'
            )


# === 写入规格到 Excel ===
def write_spec_to_excel(data, excel_path, sheet_name, product_id):
    wb = openpyxl.load_workbook(excel_path)
    sheet = wb[sheet_name]

    # ==================================================
    # 最开始只拆分“封头”：只改名称和数量，其余列完整继承原封头。
    # 封头 -> 前端封头 + 后端封头；两者数量均为1。
    # 圆筒不拆分，仍保留“圆筒”一行。
    # ==================================================
    split_rules = (
        ("封头", "前端封头", "后端封头"),
    )

    for source_name, front_name, rear_name in split_rules:
        source_rows = []
        for excel_row in iter_material_rows(sheet):
            name_cell = excel_row[MATERIAL_NAME_COL - 1]
            if str(name_cell.value or "").strip() == source_name:
                source_rows.append(name_cell.row)

        # 倒序处理，避免插入行改变后续行号
        for row_idx in reversed(source_rows):
            original_values = {
                col_idx: sheet.cell(row=row_idx, column=col_idx).value
                for col_idx in MATERIAL_OUTPUT_COLUMNS
                if not isinstance(sheet.cell(row=row_idx, column=col_idx), MergedCell)
            }

            # 封头拆分阶段先继承原材料行已有质量；最终保存前由 HEAD-MASS-V9
            # 分别使用计算文件“前端封头”/“后端封头”的质量进行覆盖。
            source_rough_mass = original_values.get(MATERIAL_UNIT_WEIGHT_COL)
            source_formed_mass = original_values.get(MATERIAL_FORMED_UNIT_WEIGHT_COL)
            if _is_meaningful_component_source_value(source_rough_mass):
                original_values[MATERIAL_TOTAL_WEIGHT_COL] = source_rough_mass
            if _is_meaningful_component_source_value(source_formed_mass):
                original_values[MATERIAL_FORMED_TOTAL_WEIGHT_COL] = source_formed_mass

            # 原行直接作为前端件；除名称/数量外，材料、质量、供货状态等全部继承原“封头”。
            for col_idx, value in original_values.items():
                target_cell = sheet.cell(row=row_idx, column=col_idx)
                if not isinstance(target_cell, MergedCell):
                    target_cell.value = value
            sheet.cell(row=row_idx, column=MATERIAL_NAME_COL).value = front_name
            sheet.cell(row=row_idx, column=MATERIAL_QUANTITY_COL).value = 1
            sheet.cell(row=row_idx, column=MATERIAL_SPEC_STAGING_COL).value = None

            # 插入后端件并复制原元件的材料、质量及供货信息。
            insert_material_row(sheet, row_idx + 1)
            for col_idx, value in original_values.items():
                target_cell = sheet.cell(row=row_idx + 1, column=col_idx)
                if isinstance(target_cell, MergedCell):
                    continue
                target_cell.value = value

            sheet.cell(row=row_idx + 1, column=MATERIAL_NAME_COL).value = rear_name
            sheet.cell(row=row_idx + 1, column=MATERIAL_QUANTITY_COL).value = 1
            sheet.cell(row=row_idx + 1, column=MATERIAL_SPEC_STAGING_COL).value = None

            print(
                f"✅ 已将第 {row_idx} 行‘{source_name}’拆分为‘{front_name}’和‘{rear_name}’，"
                "数量均为1，其余参数/质量继承原元件"
            )

    # 先查一次产品型式
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
    db_row = cursor.fetchone()
    conn.close()

    if not db_row:
        raise ValueError(f"未找到 product_id={product_id} 对应的产品型式")

    product_type = db_row[0]

    rows_to_delete = []

    for excel_row in iter_material_rows(sheet):
        name_cell = excel_row[MATERIAL_NAME_COL - 1]
        spec_cell = excel_row[MATERIAL_SPEC_STAGING_COL - 1]

        if not name_cell.value:
            continue

        name = str(name_cell.value).strip()

        # 圆筒不拆分，数量固定为1；规格/参数统一由“容器圆筒”生成。
        if name == "圆筒":
            excel_row[MATERIAL_QUANTITY_COL - 1].value = 1

        # 新增2：该元件存在参数记录，但所有参数值都为空时，不显示该元件
        if _component_all_params_empty(product_id, name):
            rows_to_delete.append(name_cell.row)
            print(f"⏭️ 跳过空参数元件：{name}")
            continue

        # AKU/BKU 下删除“折流板”这一整行
        if product_type in ("AKU", "BKU") and name == "折流板":
            rows_to_delete.append(name_cell.row)
            continue

        spec = generate_spec(name, data, product_id)
        spec_cell.value = spec

    remove_material_rows(sheet, rows_to_delete)

    wb.save(excel_path)
    print(f"✅ 已填写规格列至 Excel：{excel_path}")


def get_pipe_param_value(product_id, field_name):
    """
    从产品设计活动表_布管输入表中获取指定字段值
    特殊逻辑：当 field_name = "换热管公称长度" 时，从布管参数表获取 "换热管公称长度 LN"
    """
    conn = create_product_connection()
    if conn is None:
        return None

    try:
        cursor = conn.cursor()

        # 特殊逻辑
        if field_name == "换热管公称长度LN":
            sql = """
                SELECT `参数值`
                FROM 产品设计活动表_布管参数表
                WHERE 产品ID = %s AND 参数名 = '换热管公称长度 LN'
                LIMIT 1
            """
            cursor.execute(sql, (product_id,))
            row = cursor.fetchone()
            return row["参数值"] if row else None

        # 普通逻辑：从布管输入表读取
        sql = """
            SELECT `key`, `value`
            FROM 产品设计活动表_布管输入表
            WHERE 产品ID = %s
        """
        cursor.execute(sql, (product_id,))
        rows = cursor.fetchall()

        data = {row["key"]: row["value"] for row in rows}
        return data.get(field_name)

    except Exception as e:
        print(f"❌ 获取参数 `{field_name}` 失败: {e}")
        return None
    finally:
        cursor.close()
        conn.close()


def get_ftzhuangpeittgd_from_db(product_id):
    try:
        conn = get_connection(**db_config1)
        cursor = conn.cursor()
        sql = """
            SELECT 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '浮头法兰' AND 参数名称 = '密封面高度'
        """
        cursor.execute(sql, (product_id,))
        row = cursor.fetchone()
        conn.close()
        if row and "参数值" in row:
            return float(row["参数值"])
    except Exception as e:
        print(f"❌ 装配凸台高度: {e}")
    return 0  # 默认值为0，避免None参与计算出错

def get_jiedizhuangzhi_from_db(product_id):
    conn = None
    try:
        conn = get_connection(**db_config1)
        cursor = conn.cursor()
        sql = """
            SELECT 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '接地装置' AND 参数名称 = '装置类型'
        """
        cursor.execute(sql, (product_id,))
        row = cursor.fetchone()
        if row and "参数值" in row:
            value = row["参数值"]
            if value not in (None, "", "None"):
                return str(value).strip()
    except Exception as e:
        print(f"⚠️ 获取接地装置类型失败: {e}")
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
    return None
def get_waitougaittgd_from_db(product_id):
    try:
        conn = get_connection(**db_config1)
        cursor = conn.cursor()
        sql = """
            SELECT 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '外头盖侧法兰' AND 参数名称 = '密封面高度'
        """
        cursor.execute(sql, (product_id,))
        row = cursor.fetchone()
        conn.close()
        if row and "参数值" in row:
            return float(row["参数值"])
    except Exception as e:
        print(f"❌ 获取管板凸台高度失败: {e}")
    return 0  # 默认值为0，避免None参与计算出错


def get_ttgd_from_db(product_id):
    try:
        conn = get_connection(**db_config1)
        cursor = conn.cursor()
        sql = """
            SELECT 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管板延长部分兼作法兰密封面高度'
        """
        cursor.execute(sql, (product_id,))
        row = cursor.fetchone()
        conn.close()
        if row and "参数值" in row:
            return float(row["参数值"])
    except Exception as e:
        print(f"❌ 获取管板凸台高度失败: {e}")
    return 0  # 默认值为0，避免None参与计算出错


def get_zhuangpeittgd_from_db(product_id):
    try:
        conn = get_connection(**db_config1)
        cursor = conn.cursor()
        sql = """
            SELECT 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '管箱平盖' AND 参数名称 = '装配凸台高度'
        """
        cursor.execute(sql, (product_id,))
        row = cursor.fetchone()
        conn.close()
        if row and "参数值" in row:
            return float(row["参数值"])
    except Exception as e:
        print(f"❌ 装配凸台高度: {e}")
    return 0  # 默认值为0，避免None参与计算出错


def get_qdzhuangpeittgd_from_db(product_id):
    try:
        conn = get_connection(**db_config1)
        cursor = conn.cursor()
        sql = """
            SELECT 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '前端管箱平盖' AND 参数名称 = '装配凸台高度'
        """
        cursor.execute(sql, (product_id,))
        row = cursor.fetchone()
        conn.close()
        if row and "参数值" in row:
            return float(row["参数值"])
    except Exception as e:
        print(f"❌ 装配凸台高度: {e}")
    return 0  # 默认值为0，避免None参与计算出错


def get_dphd_from_db(dianpian, product_id):
    try:
        conn = get_connection(**db_config1)
        cursor = conn.cursor()
        sql = """
            SELECT 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = %s AND 参数名称 = '垫片厚度'
        """
        cursor.execute(sql, (product_id, dianpian))
        row = cursor.fetchone()
        conn.close()
        if row and "参数值" in row:
            return float(row["参数值"])
    except Exception as e:
        print(f"❌ 获取垫片失败: {e}")
    return 0  # 默认值为0，避免None参与计算出错


def get_gbc_from_db(product_id):
    try:
        conn = get_connection(**db_config1)
        cursor = conn.cursor()
        sql = """
            SELECT 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '壳程侧分程隔板槽深度'
        """
        cursor.execute(sql, (product_id,))
        row = cursor.fetchone()
        conn.close()
        if row and "参数值" in row:
            return float(row["参数值"])
    except Exception as e:
        print(f"❌ 获取管板凸台高度失败: {e}")
    return 0  # 默认值为0，避免None参与计算出错


def insert_jiaguan_falan_rows(sheet, product_id, json_data):
    """
    在“管口”行后插入接管法兰行。
    - B列：管口功能 + 接管法兰 + 规格
    - C列：材料牌号（来自接管法兰材料牌号，若有覆层则拼接）
    - D列：数量（默认 1）
    - P列：毛坯单重
    - T列：供货状态
    - U列：材料类型
    """

    nps_to_dn = {
        "1/2": "15", "3/4": "20", "1": "25", "1-1/4": "32", "1-1/2": "40", "2": "50",
        "2-1/2": "65", "3": "80", "4": "100", "5": "125", "6": "150", "8": "200",
        "10": "250", "12": "300", "14": "350", "16": "400", "18": "450",
        "20": "500", "24": "600"
    }

    try:
        conn = get_connection(**db_config1)
        cursor = conn.cursor()

        # 1️⃣ 查询接管法兰主参数
        sql_main = """
            SELECT 法兰标准, 管口功能, 公称尺寸, 压力等级, 法兰型式, 密封面型式
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s
        """
        cursor.execute(sql_main, (product_id,))
        rows = cursor.fetchall()
        if not rows:
            print("⚠️ 数据库中未找到接管法兰数据")
            conn.close()
            return
        conn.close()

        # 2️⃣ 定位“管口”行
        insert_index = None
        for row in iter_material_rows(sheet):
            d_val = str(row[MATERIAL_NAME_COL - 1].value or "").strip()
            if d_val == "管口":
                insert_index = row[MATERIAL_NAME_COL - 1].row + 1
                break
        if insert_index is None:
            print("❌ 未找到“管口”行，无法插入接管法兰")
            return

        # 3️⃣ 倒序插入接管法兰行
        for data in reversed(rows):
            insert_material_row(sheet, insert_index)

            standard = str(data.get("法兰标准", "")).strip()
            function = str(data.get("管口功能", "")).strip()
            dn = str(data.get("公称尺寸", "")).strip()
            pn = str(data.get("压力等级", "")).strip()
            flange_type = str(data.get("法兰型式", "")).strip()
            face_type = str(data.get("密封面型式", "")).strip()

            jiaguan_key = function + "接管"

            # 替换公称尺寸为 DN
            dn = nps_to_dn.get(dn, dn)

            sheet.cell(row=insert_index, column=MATERIAL_NAME_COL).value = f"{function}接管法兰"
            spec = f"{flange_type} {dn}-{pn} {face_type}".strip()
            sheet.cell(row=insert_index, column=MATERIAL_SPEC_STAGING_COL).value = spec
            sheet.cell(row=insert_index, column=MATERIAL_QUANTITY_COL).value = 1

            # 🔎 获取接管材料类型/牌号
            conn = get_connection(**db_config1)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT Name, Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s AND 元件名称 = %s
            """, (product_id, jiaguan_key))
            calc_rows = cursor.fetchall()
            cursor.close()
            conn.close()

            # ================== 先取“接管材料类型/牌号”（来自元件计算结果表） ==================
            pipe_mat_type = ""
            pipe_mat_grade = ""
            for r in calc_rows:
                name = (r.get("Name") or "").strip()
                val = (r.get("Value") or "").strip()
                if name == "接管材料类型":
                    pipe_mat_type = val
                elif name == "接管材料牌号":
                    pipe_mat_grade = val

            # ========= 0) 由 jiaguan_key 得到“管口功能”(用于管口表匹配) =========
            # 规则：port_func = jiaguan_key 去掉末尾“接管”两个字
            jk = (jiaguan_key or "").strip().replace("\u3000", " ").strip()
            if jk.endswith("接管"):
                port_func = jk[:-2].strip()
            else:
                port_func = jk
            port_func = port_func or ""

            # ========= 1) 管口表：找管口功能 -> 管口代号 =========
            port_code = ""
            conn = get_connection(**db_config1)
            cursor = conn.cursor()

            if port_func:
                cursor.execute("""
                    SELECT 管口代号
                    FROM 产品设计活动表_管口表
                    WHERE 产品ID = %s AND 管口功能 = %s
                    LIMIT 1
                """, (product_id, port_func))
                row_port = cursor.fetchone()
                port_code = (row_port.get("管口代号") if row_port else "") or ""
                port_code = str(port_code).strip()

            # ========= 2) 管口类别表：产品ID + 管口代号 -> 材料分类 =========
            mat_category = ""
            if port_code:
                cursor.execute("""
                    SELECT 材料分类
                    FROM 产品设计活动表_管口类别表
                    WHERE 产品ID = %s AND 管口代号 = %s
                    LIMIT 1
                """, (product_id, port_code))
                row_cat = cursor.fetchone()
                mat_category = (row_cat.get("材料分类") if row_cat else "") or ""
                mat_category = str(mat_category).strip()

            # ========= 3) 管口附加参数表：先按 产品ID 筛，再按 类别(材料分类) 筛 =========
            if mat_category:
                cursor.execute("""
                    SELECT 类别, 参数名称, 参数值
                    FROM 产品设计活动表_管口附加参数表
                    WHERE 产品ID = %s AND 类别 = %s
                """, (product_id, mat_category))
            else:
                # 分类拿不到时兜底：至少先按产品ID筛
                cursor.execute("""
                    SELECT 类别, 参数名称, 参数值
                    FROM 产品设计活动表_管口附加参数表
                    WHERE 产品ID = %s
                """, (product_id,))

            param_rows = cursor.fetchall()
            cursor.close()
            conn.close()

            param_map = {
                (str(r.get("参数名称") or "")).strip(): (str(r.get("参数值") or "")).strip()
                for r in param_rows
            }

            # ================== 4) idx 1~3：在“已筛选后的 param_map”里做匹配 ==================
            pipe_supply_status = ""
            flange_mat_type = ""
            flange_mat_grade = ""
            flange_forging_level = ""
            flange_supply_status = ""
            fuceng_grade = ""

            for idx in range(1, 4):
                t_key = f"接管材料类型{idx}"
                g_key = f"接管材料牌号{idx}"
                s_key = f"接管供货状态{idx}"

                if (param_map.get(t_key, "").strip().lower() == (pipe_mat_type or "").strip().lower()
                        and param_map.get(g_key, "").strip().lower() == (pipe_mat_grade or "").strip().lower()):

                    # 接管供货状态
                    pipe_supply_status = param_map.get(s_key, "").strip()

                    # 接管法兰材料
                    flange_mat_type = param_map.get(f"接管法兰材料类型{idx}", "").strip()
                    flange_mat_grade = param_map.get(f"接管法兰材料牌号{idx}", "").strip()
                    flange_forging_level = param_map.get(
                        f"接管法兰锻件级别{idx}", ""
                    ).strip()
                    flange_supply_status = param_map.get(f"接管法兰供货状态{idx}", "").strip()

                    # ✅ 判断是否添加覆层
                    fuceng_flag = (param_map.get("接管法兰是否添加覆层", "否") or "").strip()
                    if fuceng_flag == "是":
                        fuceng_key = f"接管法兰覆层材料牌号{idx}"
                        fuceng_val = (param_map.get(fuceng_key, "") or "").strip()
                        if fuceng_val:
                            fuceng_grade = fuceng_val
                    break

            # ================== 写入表格 ==================
            # J列：供货状态
            sheet.cell(row=insert_index, column=MATERIAL_SUPPLY_COL).value = (
                flange_supply_status or pipe_supply_status or None
            )

            # K列：材料类型
            sheet.cell(row=insert_index, column=MATERIAL_TYPE_COL).value = (flange_mat_type or None)

            # F列：材料牌号（拼接覆层材料牌号）
            final_grade = flange_mat_grade or ""
            # 锻件级别必须使用当前材料组的实际值；空值不再默认补“Ⅱ”。
            if ((flange_mat_type or "").strip() == "钢锻件"
                    and flange_forging_level not in ("", "None")):
                final_grade = (
                    f"{final_grade}{flange_forging_level}"
                    if final_grade else flange_forging_level
                )
            if fuceng_grade:
                final_grade = f"{final_grade}+{fuceng_grade}" if final_grade else fuceng_grade

            sheet.cell(row=insert_index, column=MATERIAL_GRADE_COL).value = (final_grade or None)
            print(f"✅ 已插入接管法兰 {len(rows)} 条，含接管/法兰材料信息")

        # === 质量写入逻辑（保持原有 Step1–Step4） ===
        try:
            conn1 = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn2 = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )

            try:
                cursor = conn1.cursor()
                cursor.execute("""
                    SELECT 公称尺寸类型, 公称压力类型 
                    FROM 产品设计活动表_管口类型选择表 
                    WHERE 产品ID = %s LIMIT 1
                """, (product_id,))
                config = cursor.fetchone()
                size_type = config.get("公称尺寸类型", "DN").strip()
                press_type = config.get("公称压力类型", "PN").strip()
                cursor.close()

                cursor = conn1.cursor()
                cursor.execute("""
                    SELECT 管口代号, 管口功能, 公称尺寸, 压力等级, 法兰型式, 法兰标准 
                    FROM 产品设计活动表_管口表 
                    WHERE 产品ID = %s
                """, (product_id,))
                kou_rows = cursor.fetchall()
                cursor.close()

                flange_mass_map = {}
                # 使用 DictCursor 确保 row 可以用字符串索引
                cursor2 = conn2.cursor(pymysql.cursors.DictCursor)

                def clean_val(v):
                    if v is None:
                        return ""
                    v = str(v).strip()
                    if v.lower() == "none":
                        return ""
                    return v

                for row in kou_rows:
                    kou_id = clean_val(row.get("管口代号"))
                    size = clean_val(row.get("公称尺寸"))
                    pressure = clean_val(row.get("压力等级"))
                    flange_type = clean_val(row.get("法兰型式"))

                    standard_full = clean_val(row.get("法兰标准"))
                    print(standard_full, "standard_full")
                    standard_1 = standard_full
                    print(standard_1, "standard_1")
                    size_col = "DN" if size_type.upper() == "DN" else "NPS"
                    press_col = "PN" if press_type.upper() == "PN" else "Class"

                    cursor2.execute(f"""
                        SELECT 质量 FROM 管法兰质量表
                        WHERE 标准 = %s AND 法兰型式代号 = %s
                          AND (`{size_col}` = %s OR `{size_col}` IS NULL OR `{size_col}` = '')
                          AND (`{press_col}` = %s OR `{press_col}` IS NULL OR `{press_col}` = '')
                        LIMIT 1
                    """, (standard_1, flange_type, size, pressure))
                    res = cursor2.fetchone()
                    flange_mass_map[kou_id] = float(res["质量"]) if res and res.get("质量") not in (
                        None, '', 'None') else 0.0

                cursor2.close()
            finally:
                conn1.close()
                conn2.close()

            print("✅ flange_mass_map =", flange_mass_map)

            for row in iter_material_rows(sheet):
                part_name = str(row[MATERIAL_NAME_COL - 1].value or "").strip()
                for kou in kou_rows:
                    kou_id = kou["管口代号"]
                    kou_func = kou.get("管口功能", "").strip()
                    expected_name = f"{kou_func}接管法兰"
                    if part_name == expected_name:
                        row[MATERIAL_UNIT_WEIGHT_COL - 1].value = flange_mass_map.get(kou_id, 0)
                        break

        except Exception as e:
            print(f"❌ 获取接管法兰质量或写入 Excel 失败: {e}")

    except Exception as e:
        print(f"❌ insert_jiaguan_falan_rows 失败: {e}")


def insert_nozzle_flange_attachment_rows(sheet, product_id, json_data):
    """在对应接管法兰后插入配对法兰、垫片、螺栓和螺母，返回需保留的名称。"""
    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config1)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT Tab分类, Tab_ID, 附件类型, 标题分组, 参数名称, 参数数值
            FROM 产品设计活动表_管口附件附加参数表
            WHERE 产品ID = %s AND 附件类型 = %s
            ORDER BY 参数ID
        """, (product_id, PAIRED_FLANGE))
        attachment_rows = cursor.fetchall()
        if not attachment_rows:
            return set()
        cursor.execute("""
            SELECT 管口代号, 管口功能, 公称尺寸, 压力等级, 法兰标准,
                   法兰型式, 密封面型式, 焊端规格
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s
        """, (product_id,))
        nozzle_rows = cursor.fetchall()
        cursor.execute("""
            SELECT 公称尺寸类型, 公称压力类型
            FROM 产品设计活动表_管口类型选择表
            WHERE 产品ID = %s LIMIT 1
        """, (product_id,))
        unit_config = cursor.fetchone() or {}
    except Exception as e:
        print(f"⚠️ 读取接管法兰配对附件失败: {e}")
        return set()
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()

    preserved_names = set()
    dimensions = load_nozzle_fastener_dimensions(nozzle_rows, unit_config)
    for bundle in build_nozzle_flange_materials(attachment_rows, nozzle_rows, json_data, dimensions):
        anchor = next((row for row in iter_material_rows(sheet)
                       if str(row[MATERIAL_NAME_COL - 1].value or "").strip()
                       == bundle["flange_name"]), None)
        insert_at = anchor[MATERIAL_NAME_COL - 1].row + 1 if anchor else _first_empty_material_row(sheet)
        flange_spec = anchor[MATERIAL_SPEC_STAGING_COL - 1].value if anchor else None
        flange_weight = anchor[MATERIAL_UNIT_WEIGHT_COL - 1].value if anchor else None
        for item in bundle["items"]:
            spec = item["spec"]
            weight = item["unit_weight"]
            if item["inherit_flange_spec"] and flange_spec:
                spec = re.sub(r"\s+s\s*=.*$", "", str(flange_spec)).strip()
            if item["group"] == PAIRED_FLANGE and weight is None:
                weight = flange_weight
            _insert_component_row(
                sheet, insert_at, item["name"], spec, item["material"],
                item["quantity"], weight, item["supply"], item["material_type"],
            )
            preserved_names.add(item["name"])
            insert_at += 1
        print(f"✅ 已插入管口 {bundle['code']} 的配对法兰附件 4 行")
    return preserved_names


def replace_and_insert_fencheng_gebans(sheet, product_id):
    """
    1) 删除 Excel 中 B列包含：前端分程隔板/后端分程隔板/分程隔板/隔板 的所有行
    2) 从数据库 产品设计活动表_元件计算结果表 读取 元件名称='管箱分程隔板' 的 Name/Value
       用预定义字段组做匹配，存在的组就插入一行：
         B=名称，C=规格型号（与组一一对应）
         D=材料牌号（钢锻件：牌号 + 锻件级别）
         E=数量（来自该组数量字段）
         O=毛坯单重（来自该组重量字段）
         R=供货状态
         S=材料类型
    3) D/R/S 的取值来源：产品设计活动表_元件附加参数表 中 元件名称='分程隔板' 或 '隔板'
       （哪个有就用哪个）
    """
    import pymysql

    # ========= 1) 先删 Excel 里旧的隔板行 =========
    keywords = ("前端分程隔板", "后端分程隔板", "分程隔板", "隔板")
    rows_to_delete = []
    for r in range(MATERIAL_START_ROW, find_material_fixed_tail_start(sheet)):
        v = sheet.cell(row=r, column=MATERIAL_NAME_COL).value
        if v and any(k in str(v) for k in keywords):
            rows_to_delete.append(r)

    remove_material_rows(sheet, rows_to_delete)

    # ========= 2) 连接数据库 =========
    conn = pymysql.connect(
        host="localhost",
        user="root",
        password="123456",
        database="产品设计活动库",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )
    cursor = conn.cursor()

    # ========= 3) 从“分程隔板/隔板”取材料信息（附加参数表） =========
    def fetch_material_from_component(component_name):
        cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = %s
        """, (product_id, component_name))
        rows = cursor.fetchall() or []

        mat_type = ""
        mat_grade = ""
        supply_status = ""
        forging_level = ""

        for r in rows:
            n = r.get("参数名称")
            v = r.get("参数值")
            if n == "材料类型":
                mat_type = v
            elif n == "材料牌号":
                mat_grade = v
            elif n == "供货状态":
                supply_status = v
            elif n == "锻件级别":
                forging_level = v

        # 钢锻件显示：牌号+锻件级别
        if mat_type == "钢锻件":
            if forging_level not in (None, "", "None"):
                mat_grade_display = f"{mat_grade}{forging_level}"
            else:
                mat_grade_display = mat_grade
        else:
            mat_grade_display = mat_grade

        return mat_type, mat_grade_display, supply_status

    mat_type, mat_grade_display, supply_status = fetch_material_from_component("分程隔板")
    if (mat_type in (None, "", "None")) and (mat_grade_display in (None, "", "None")) and (
            supply_status in (None, "", "None")):
        mat_type, mat_grade_display, supply_status = fetch_material_from_component("隔板")
    if (mat_type in (None, "", "None")) and (mat_grade_display in (None, "", "None")) and (
            supply_status in (None, "", "None")):
        mat_type, mat_grade_display, supply_status = fetch_material_from_component("前端分程隔板")
    # ========= 4) 读取计算结果表（管箱分程隔板） =========
    cursor.execute("""
        SELECT Name, Value
        FROM 产品设计活动表_元件计算结果表
        WHERE 产品ID = %s AND 元件名称 = '管箱分程隔板'
    """, (product_id,))
    calc_rows = cursor.fetchall() or []
    conn.close()

    name_to_value = {}
    for r in calc_rows:
        k = r.get("Name")
        v = r.get("Value")
        if k:
            name_to_value[str(k).strip()] = v

    # ✅ t：名义厚度（统一）
    t = name_to_value.get("管箱分程隔板名义厚度", "")  # 没有就留空

    # ========= 5) 6 组字段定义（含径向/轴长度）=========
    groups = [
        {
            "title": "水平分程隔板",
            "qty_key": "水平隔板数量",
            "mass_key": "水平分程隔板重量",
            "radial_key": "水平分程隔板径向长度",
            "axial_key": "水平分程隔板轴长度",
        },
        {
            "title": "竖直分程隔板",
            "qty_key": "竖直隔板数量",
            "mass_key": "竖直分程隔板重量",
            "radial_key": "竖直分程隔板径向长度",
            "axial_key": "竖直分程隔板轴长度",
        },
        {
            "title": "分程隔板2",
            "qty_key": "分程隔板2数量",
            "mass_key": "分程隔板2重量",
            "radial_key": "分程隔板2径向长度",
            "axial_key": "分程隔板2轴长度",
        },
        {
            "title": "浮头盖水平分程隔板",
            "qty_key": "浮头盖水平隔板数量",
            "mass_key": "浮头盖水平隔板重量",
            "radial_key": "浮头盖水平分程隔板径向长度",
            "axial_key": "浮头盖水平分程隔板轴长度",
        },
        {
            "title": "浮头盖竖直分程隔板",
            "qty_key": "浮头盖竖直隔板数量",
            "mass_key": "浮头盖竖直隔板重量",
            "radial_key": "浮头盖竖直分程隔板径向长度",
            "axial_key": "浮头盖竖直分程隔板轴长度",
        },
        {
            "title": "浮头盖分程隔板2",
            "qty_key": "浮头盖分程隔板2数量",
            "mass_key": "浮头盖分程隔板2重量",
            "radial_key": "浮头盖分程隔板2径向长度",
            "axial_key": "浮头盖分程隔板2轴长度",
        },
    ]

    # ========= 6) 找插入位置并逐组插入 =========
    def find_first_empty_name(start_row=MATERIAL_START_ROW):
        for rr in range(start_row, find_material_fixed_tail_start(sheet)):
            if not sheet.cell(row=rr, column=MATERIAL_NAME_COL).value:
                return rr
        return find_material_fixed_tail_start(sheet)

    insert_index = find_first_empty_name()

    for g in groups:
        qty_key = g["qty_key"]
        mass_key = g["mass_key"]
        radial_key = g["radial_key"]
        axial_key = g["axial_key"]

        # 组是否存在：按数量字段存在判断（你说组内字段同时出现）
        if qty_key not in name_to_value:
            continue

        qty = name_to_value.get(qty_key, "")
        mass = name_to_value.get(mass_key, "")
        t2 = round(float(name_to_value.get(radial_key, "")), 2)
        t3 = round(float(name_to_value.get(axial_key, "")), 2)

        # ✅ 规格：径向×轴×厚度（厚度t统一）
        # 若 t 为空，则退化为 “径向×轴”
        if t not in (None, "", "None", "0", 0):
            spec = f"{t2}×{t3}×{t}"
        else:
            spec = f"{t2}×{t3}"

        insert_material_row(sheet, insert_index)

        sheet.cell(row=insert_index, column=MATERIAL_NAME_COL).value = g["title"]
        sheet.cell(row=insert_index, column=MATERIAL_SPEC_STAGING_COL).value = spec
        sheet.cell(row=insert_index, column=MATERIAL_GRADE_COL).value = mat_grade_display

        # G列：数量
        try:
            sheet.cell(row=insert_index, column=MATERIAL_QUANTITY_COL).value = int(float(qty))
        except:
            sheet.cell(row=insert_index, column=MATERIAL_QUANTITY_COL).value = qty

        # H列：重量
        try:
            sheet.cell(row=insert_index, column=MATERIAL_UNIT_WEIGHT_COL).value = round(float(mass), 2)
        except:
            sheet.cell(row=insert_index, column=MATERIAL_UNIT_WEIGHT_COL).value = mass

        # S/T：供货状态、材料类型
        sheet.cell(row=insert_index, column=MATERIAL_SUPPLY_COL).value = supply_status
        sheet.cell(row=insert_index, column=MATERIAL_TYPE_COL).value = mat_type

        print(f"✅ 已插入 {g['title']}：spec={spec}，行={insert_index}")
        insert_index += 1


import json
import re


def extract_standard_number(standard):
    if not standard:
        return ""
    m = re.search(r"\b(\d{4,6})\b", standard)
    return m.group(1) if m else ""


def insert_jiaguan_rows(sheet, product_id, data, jisuan_json_path):
    print("!!!!!!!!!!")
    """
    在“管口”行后插入接管行。
    每行包括：
    - B列：管口功能接管 + 规格
    - C列：材料牌号
    - D列：数量（默认为 1）
    - P列：接管毛坯单重
    - T列：供货状态
    - U列：材料类型
    """
    import json

    # === 读取计算结果 JSON 文件 ===
    try:
        with open(jisuan_json_path, "r", encoding="utf-8") as f:
            jisuan_data = json.load(f)
            dict_out = jisuan_data.get("DictOutDatas", {})
    except Exception as e:
        print(f"❌ 无法读取计算结果 JSON: {e}")
        dict_out = {}

    conn = get_connection(**db_config1)
    cursor = conn.cursor()

    # === 找到“管口”行 ===
    insert_index = None
    for row in iter_material_rows(sheet):
        if str(row[MATERIAL_NAME_COL - 1].value or "").strip() == "管口":
            insert_index = row[MATERIAL_NAME_COL - 1].row + 1
            break
    if insert_index is None:
        print("❌ 未找到“管口”行，无法插入接管")
        return

    # === 获取所有接管名称 ===
    cursor.execute("""
        SELECT DISTINCT 元件名称
        FROM 产品设计活动表_元件计算结果表
        WHERE 产品ID = %s AND 元件名称 LIKE %s
    """, (product_id, '%接管'))
    rows = cursor.fetchall()
    jieguan_names = [row["元件名称"] for row in rows if row.get("元件名称")]
    print(jieguan_names, "jieguan_names")
    # ✅ 不再全表预读取附加参数表（会串组）
    # 这里做一个缓存：key=材料分类(类别) -> param_map(该类别下的 参数名称->参数值)
    param_map_cache = {}

    conn.close()

    # === 倒序插入接管 ===
    for name in reversed(jieguan_names):
        spec = generate_spec(name, data, product_id) or ""
        print("jieguan_spec", spec)
        # ⛳ 从 JSON 提取该接管的重量/材料信息
        mass = ""
        mat_type = ""
        mat_grade = ""
        length = ""
        module = dict_out.get(name, {})
        datas = module.get("Datas", [])
        for item in datas:
            n = (item.get("Name", "") or "").strip()
            if n == "接管重量":
                mass = item.get("Value", "")
            elif n == "接管材料类型":
                mat_type = item.get("Value", "")
            elif n == "接管材料牌号":
                mat_grade = item.get("Value", "")
            elif n == "接管实际外伸长度":
                length = item.get("Value", "")

        mat_type = (str(mat_type or "")).strip()
        mat_grade = (str(mat_grade or "")).strip()

        # ========= A) 计算 port_func：接管名去掉末尾“接管” =========
        jk = (name or "").strip().replace("\u3000", " ").strip()
        if jk.endswith("接管"):
            port_func = jk[:-2].strip()
        else:
            port_func = jk
        port_func = port_func or ""

        # ========= B) 查：管口代号 =========
        port_code = ""
        conn = get_connection(**db_config1)
        cursor = conn.cursor()

        if port_func:
            cursor.execute("""
                SELECT 管口代号
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口功能 = %s
                LIMIT 1
            """, (product_id, port_func))
            row_port = cursor.fetchone()
            port_code = (row_port.get("管口代号") if row_port else "") or ""
            port_code = str(port_code).strip()

        # ========= C) 查：材料分类(类别) =========
        mat_category = ""
        if port_code:
            cursor.execute("""
                SELECT 材料分类
                FROM 产品设计活动表_管口类别表
                WHERE 产品ID = %s AND 管口代号 = %s
                LIMIT 1
            """, (product_id, port_code))
            row_cat = cursor.fetchone()
            mat_category = (row_cat.get("材料分类") if row_cat else "") or ""
            mat_category = str(mat_category).strip()

        # ========= D) 取该类别下的 param_map（带缓存） =========
        if mat_category and mat_category in param_map_cache:
            param_map = param_map_cache[mat_category]
        else:
            if mat_category:
                cursor.execute("""
                    SELECT 参数名称, 参数值
                    FROM 产品设计活动表_管口附加参数表
                    WHERE 产品ID = %s AND 类别 = %s
                """, (product_id, mat_category))
            else:
                # 分类取不到时兜底：只按产品ID（可能会串组，但比直接全表 dict 好一些）
                cursor.execute("""
                    SELECT 参数名称, 参数值
                    FROM 产品设计活动表_管口附加参数表
                    WHERE 产品ID = %s
                """, (product_id,))

            param_rows = cursor.fetchall()
            param_map = {
                (str(r.get("参数名称") or "")).strip(): (str(r.get("参数值") or "")).strip()
                for r in param_rows
            }

            if mat_category:
                param_map_cache[mat_category] = param_map

        cursor.close()
        conn.close()

        # ========= E) 在“该类别(分组)的 param_map”里匹配供货状态 idx1~3 =========
        supply_status = ""
        forging_level = ""
        for i in range(1, 4):
            t_key = f"接管材料类型{i}"
            g_key = f"接管材料牌号{i}"
            s_key = f"接管供货状态{i}"

            if (param_map.get(t_key, "").strip().lower() == mat_type.lower()
                    and param_map.get(g_key, "").strip().lower() == mat_grade.lower()):
                supply_status = (param_map.get(s_key, "") or "").strip()
                forging_level = (
                    param_map.get(f"接管锻件级别{i}", "") or ""
                ).strip()
                break
        # === 插入行 ===
        insert_material_row(sheet, insert_index)
        sheet.cell(row=insert_index, column=MATERIAL_NAME_COL).value = name
        sheet.cell(row=insert_index, column=MATERIAL_SPEC_STAGING_COL).value = spec

        # 锻件级别随材料类型/牌号一起按同一个 i 反推；空值保持为空。
        if mat_type == "钢锻件" and forging_level not in ("", "None"):
            sheet.cell(row=insert_index, column=MATERIAL_GRADE_COL).value = (
                f"{mat_grade}{forging_level}" if mat_grade else forging_level
            )
        else:
            sheet.cell(row=insert_index, column=MATERIAL_GRADE_COL).value = f"{mat_grade}"

        sheet.cell(row=insert_index, column=MATERIAL_QUANTITY_COL).value = 1

        # H列：重量 = spec中L=后的值 / length * 当前mass
        l_match = re.search(r"L\s*=\s*([0-9.]+)", str(spec or ""))
        spec_l = float(l_match.group(1)) if l_match else 0.0
        print(spec_l, "spec_l")
        print(length, "length")
        print(mass, "mass")
        calc_mass = 0.0
        if float(length or 0) != 0:
            calc_mass = spec_l / float(length) * float(mass)

        sheet.cell(row=insert_index, column=MATERIAL_UNIT_WEIGHT_COL).value = round(calc_mass, 2)

        sheet.cell(row=insert_index, column=MATERIAL_SUPPLY_COL).value = supply_status
        sheet.cell(row=insert_index, column=MATERIAL_TYPE_COL).value = mat_type


from openpyxl.styles import Alignment, Border, Side, Font


def clean_and_renumber(sheet, product_id):
    """
    删除指定结构件行（黑名单），
    以及灰名单中与数据库无对应项的行（仅按 D 列比对），
    以及从第8行开始 G 列值为 0（但垫片除外）的行。
    """

    # ================= 黑名单（必删） =================
    names_to_remove = {
        "螺母（保温支撑）", "螺柱（保温支撑）",
        "底板（固定鞍座）", "腹板（固定鞍座）", "筋板（固定鞍座）", "垫板（固定鞍座）",
        "底板（滑动鞍座）", "腹板（滑动鞍座）", "筋板（滑动鞍座）", "垫板（滑动鞍座）",
        "支撑板（保温支撑）", "支撑环（保温支撑）", "支撑条（保温支撑）",
        "管口",
        "顶丝", "顶板", "堵板", "破涡器",
        "尾部支撑", "纵向隔板", "保温支撑", "保温装置", "平盖吊耳", "管口附件"
    }

    # ================= 灰名单 A：对比数据库 name =================
    gray_names = {
        "外头盖吊耳", "壳体吊耳", "管箱吊耳", "吊耳",
         "导流筒", "支撑板", "前端管箱吊耳", "后端管箱吊耳"
    }

    # ================= 灰名单 B：对比数据库 元件名称 =================
    gray_component_names = {
        "后端管箱圆筒"
    }

    conn = pymysql.connect(
        host="localhost",
        port=3306,
        user="root",
        password="123456",
        database="产品设计活动库",
        charset="utf8mb4"
    )

    # =========================================================
    # ① 查询数据库中真实存在的 name / 元件名称
    # =========================================================
    valid_names = set()
    valid_component_names = set()

    with conn.cursor(pymysql.cursors.DictCursor) as cursor:
        cursor.execute("""
            SELECT name, 元件名称
            FROM 产品设计活动表_元件计算结果表
            WHERE 产品ID = %s
        """, (product_id,))
        rows = cursor.fetchall()

        for r in rows:
            if r.get("name"):
                valid_names.add(str(r["name"]).strip())
            if r.get("元件名称"):
                valid_component_names.add(str(r["元件名称"]).strip())

    conn.close()

    # =========================================================
    # ② 端部圆筒判断（保持你原逻辑）
    # =========================================================
    has_end1 = "壳体端部圆筒1" in valid_names
    has_end2 = "壳体端部圆筒2" in valid_names
    end_both_missing = (not has_end1) and (not has_end2)

    # =========================================================
    # ③ 开始逐行筛选（只看 D 列）
    # =========================================================
    rows_to_delete = []

    for row in iter_material_rows(sheet):
        name_cell = row[MATERIAL_NAME_COL - 1]
        d_val = str(name_cell.value).strip() if name_cell.value else ""
        g_val = row[MATERIAL_QUANTITY_COL - 1].value
        idx = name_cell.row

        # ---------- 黑名单：必删 ----------
        if d_val in names_to_remove:
            rows_to_delete.append(idx)
            continue

        # ---------- 端部圆筒 ----------
        if "端部圆筒" in d_val and end_both_missing:
            rows_to_delete.append(idx)
            continue

        # ---------- 灰名单：仅灰名单项参与数据库比对 ----------
        hit_gray_a = d_val in gray_names
        hit_gray_b = d_val in gray_component_names

        if hit_gray_a or hit_gray_b:
            ok_a = hit_gray_a and d_val in valid_names
            ok_b = hit_gray_b and d_val in valid_component_names

            # 任一通过即可保留；都不通过才删
            if not (ok_a or ok_b):
                rows_to_delete.append(idx)
                continue

        # ---------- G 列为 0，但不是垫片 ----------
        if (g_val == 0 or g_val == "0") and "垫片" not in d_val:
            rows_to_delete.append(idx)

    # =========================================================
    # 只压缩材料区，不能让第16行后的固定模板内容上移。
    # =========================================================
    remove_material_rows(sheet, rows_to_delete)


def generate_spec_houdan_yuantong(data):
    """
    生成后端管箱圆筒的规格，格式和“管箱圆筒”保持完全一致：
    - ID×t;L=长度
    - 或 ID×(t+覆层);L=长度
    """

    id_ = get_value(data, "后端管箱圆筒", "圆筒内径") or 0
    t = get_value(data, "后端管箱圆筒", "圆筒名义厚度") or 0
    l = get_value(data, "后端管箱圆筒", "圆筒长度") or 0
    fuceng = get_value(data, "后端管箱圆筒", "圆筒覆层厚度") or 0

    if None not in (id_, t, l):
        if fuceng not in (0, 0.0, "0", "0.0", None, "None"):
            return f"ID{id_}×({t}+{fuceng});L={l}"
        else:
            return f"ID{id_}×{t};L={l}"
    else:
        return f"ID{id_}×{t};L={l}"


def generate_spec_daduan_yuantong(data):
    """
    生成后端管箱圆筒的规格，格式和“管箱圆筒”保持完全一致：
    - ID×t;L=长度
    - 或 ID×(t+覆层);L=长度
    """
    print(data, "dataaaaa")
    id_ = get_value(data, "大端壳体圆筒加强段", "圆筒内径") or 0
    t = get_value(data, "大端壳体圆筒加强段", "圆筒名义厚度") or 0
    l = get_value(data, "大端壳体圆筒加强段", "圆筒长度") or 0
    fuceng = get_value(data, "大端壳体圆筒加强段", "圆筒覆层厚度") or 0

    if None not in (id_, t, l):
        if fuceng not in (0, 0.0, "0", "0.0", None, "None"):
            return f"ID{id_}×({t}+{fuceng});L={l}"
        else:
            return f"ID{id_}×{t};L={l}"
    else:
        return f"ID{id_}×{t};L={l}"


def generate_spec_houdan_fengtou(data):
    """
    生成后端管箱圆筒的规格，格式和“管箱圆筒”保持完全一致：
    - ID×t;L=长度
    - 或 ID×(t+覆层);L=长度
    """

    dh = get_value(data, "后端管箱封头", "封头类型代号") or 0
    d = get_value(data, "后端管箱封头", "椭圆形封头计算内径") or 0
    t = get_value(data, "后端管箱封头", "椭圆形封头名义厚度") or 0

    t_plus = get_value(data, "后端管箱封头", "椭圆形封头最小成型厚度") or 0
    h = get_value(data, "后端管箱封头", "椭圆形封头直边高度") or 0
    fuceng = get_value(data, "后端管箱封头", "椭圆形封头覆层厚度") or 0

    if None not in (dh, d, t, h):
        if fuceng not in (0, 0.0, "0", "0.0", None, "None"):
            return f"{dh}{d}×({t}({t_plus})+{fuceng});h={h}"
        else:
            return f"{dh}{d}×{t}({t_plus});h={h}"


def _first_empty_material_row(sheet):
    for row_idx in range(MATERIAL_START_ROW, find_material_fixed_tail_start(sheet)):
        if sheet.cell(row_idx, MATERIAL_NAME_COL).value in (None, "", "None"):
            return row_idx
    return find_material_fixed_tail_start(sheet)


def _insert_component_row(sheet, row_idx, name, spec, material, quantity,
                          unit_weight, supply_status, material_type):
    insert_material_row(sheet, row_idx)
    sheet.cell(row_idx, MATERIAL_NAME_COL).value = name
    sheet.cell(row_idx, MATERIAL_SPEC_STAGING_COL).value = spec
    sheet.cell(row_idx, MATERIAL_GRADE_COL).value = material
    sheet.cell(row_idx, MATERIAL_QUANTITY_COL).value = quantity
    try:
        unit_weight = round(float(unit_weight), 2)
    except (TypeError, ValueError):
        pass
    sheet.cell(row_idx, MATERIAL_UNIT_WEIGHT_COL).value = unit_weight
    sheet.cell(row_idx, MATERIAL_SUPPLY_COL).value = supply_status
    sheet.cell(row_idx, MATERIAL_TYPE_COL).value = material_type


def _finalize_material_name_specs(sheet):
    for row in iter_material_rows(sheet):
        name_cell = row[MATERIAL_NAME_COL - 1]
        spec_cell = row[MATERIAL_SPEC_STAGING_COL - 1]
        name = str(name_cell.value or "").strip()
        spec = str(spec_cell.value or "").strip()
        if name:
            name_cell.value = name
            row[MATERIAL_SPEC_COL - 1].value = spec or None
        spec_cell.value = None


def insert_houdan_guanxiang_yuantong(sheet, product_id, data):
    """
    插入“后端管箱圆筒”
    B列名称，C列规格，D列材料，E列数量，O列毛坯单重，S/T列供货状态/材料类型。
    """

    import pymysql

    conn = pymysql.connect(
        host="localhost",
        user="root",
        password="123456",
        database="产品设计活动库",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )
    cursor = conn.cursor()

    # ======================================================
    # ✅ 0) 插入前判断：如果数据库里已经有“后端管箱圆筒”，则不再添加
    #    判断范围：产品设计活动表_元件附加参数表 的 元件名称
    # ======================================================
    cursor.execute("""
        SELECT 1
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '后端管箱圆筒'
        LIMIT 1
    """, (product_id,))
    exists = cursor.fetchone()
    if exists:
        conn.close()
        print("ℹ️ 数据库已存在“后端管箱圆筒”，跳过插入")
        return

    # ======================================================
    # ① 获取 材料类型 / 材料牌号 / 供货状态 / 锻件级别
    # ======================================================
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
    """, (product_id,))
    rows = cursor.fetchall()

    mat_type = ""
    mat_grade = ""
    supply_status = ""
    forging_level = ""  # 锻件级别（Ⅱ、Ⅲ、Ⅳ等）

    for r in rows:
        name = r.get("参数名称")
        val = r.get("参数值")
        if name == "材料类型":
            mat_type = val
        elif name == "材料牌号":
            mat_grade = val
        elif name == "供货状态":
            supply_status = val
        elif name == "锻件级别":
            forging_level = val

    # ======================================================
    # 正确的钢锻件显示逻辑
    # ======================================================
    if mat_type == "钢锻件":
        if forging_level not in (None, "", "None"):
            mat_grade_display = f"{mat_grade}{forging_level}"
        else:
            mat_grade_display = mat_grade
    else:
        mat_grade_display = mat_grade

    # ======================================================
    # ② 获取“后端管箱圆筒”的重量
    # ======================================================
    cursor.execute("""
        SELECT Name, Value
        FROM 产品设计活动表_元件计算结果表
        WHERE 产品ID = %s AND 元件名称 = '后端管箱圆筒'
    """, (product_id,))
    rows = cursor.fetchall()

    mass = ""
    for r in rows:
        if r.get("Name") == "圆筒重量kg":
            mass = r.get("Value")
            break

    conn.close()

    # ======================================================
    # ③ 找到插入位置（D列的第一个空行）
    # ======================================================
    insert_index = _first_empty_material_row(sheet)

    # 规格
    spec = generate_spec_houdan_yuantong(data)

    # ======================================================
    # ④ 插入行
    # ======================================================
    _insert_component_row(
        sheet, insert_index, "后端管箱圆筒", spec, mat_grade_display,
        1, mass, supply_status, mat_type,
    )

    print(f"✅ 已插入 后端管箱圆筒，第 {insert_index} 行")


def insert_daduan_guanxiang_yuantong(sheet, product_id, data):
    """
    插入“大端壳体圆筒加强段”。
    B列名称，C列规格，D列材料，E列数量，O列毛坯单重，S/T列供货状态/材料类型。
    """

    import pymysql

    conn = pymysql.connect(
        host="localhost",
        user="root",
        password="123456",
        database="产品设计活动库",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )
    cursor = conn.cursor()

    # ======================================================
    # ① 获取 材料类型 / 材料牌号 / 供货状态 / 锻件级别
    # ======================================================
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '壳体大端圆筒'
    """, (product_id,))
    rows = cursor.fetchall()

    mat_type = ""
    mat_grade = ""
    supply_status = ""
    forging_level = ""  # 锻件级别（Ⅱ、Ⅲ、Ⅳ等）

    for r in rows:
        name = r.get("参数名称")
        val = r.get("参数值")
        if name == "材料类型":
            mat_type = val
            print(mat_type, "mat_type")
        elif name == "材料牌号":
            mat_grade = val
        elif name == "供货状态":
            supply_status = val
        elif name == "锻件级别":
            forging_level = val

    # ======================================================
    # 正确的钢锻件显示逻辑
    # ======================================================
    if mat_type == "钢锻件":
        if forging_level not in (None, "", "None"):
            mat_grade_display = f"{mat_grade}{forging_level}"
        else:
            mat_grade_display = mat_grade
    else:
        mat_grade_display = mat_grade

    # ======================================================
    # ② 获取“后端管箱圆筒”的重量
    # ======================================================
    cursor.execute("""
        SELECT Name, Value
        FROM 产品设计活动表_元件计算结果表
        WHERE 产品ID = %s AND 元件名称 = '大端壳体圆筒加强段'
    """, (product_id,))
    rows = cursor.fetchall()

    mass = ""
    for r in rows:
        if r.get("Name") == "圆筒重量kg":
            mass = r.get("Value")
            break

    conn.close()

    # ======================================================
    # ③ 找到插入位置（D列的第一个空行）
    # ======================================================
    insert_index = _first_empty_material_row(sheet)

    # 规格
    spec = generate_spec_daduan_yuantong(data)

    # ======================================================
    # ④ 插入行
    # ======================================================
    _insert_component_row(
        sheet, insert_index, "大端壳体圆筒加强段", spec, mat_grade_display,
        1, mass, supply_status, mat_type,
    )

    print(f"✅ 已插入 大端壳体圆筒加强段，第 {insert_index} 行")


def insert_houdan_guanxiang_fengtou(sheet, product_id, data):
    """
    插入“后端管箱封头”。
    B列名称，C列规格，D列材料，E列数量，O列毛坯单重，S/T列供货状态/材料类型。
    """

    import pymysql

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
        SELECT 1
        FROM 产品设计活动表
        WHERE 产品ID = %s AND 产品型式 != 'BEM'
        LIMIT 1
    """, (product_id,))
    exists = cursor.fetchone()
    if exists:
        conn.close()
        print("跳过插入")
        return
    # ======================================================
    # ✅ 0) 插入前判断：如果数据库里已经有“后端管箱圆筒”，则不再添加
    #    判断范围：产品设计活动表_元件附加参数表 的 元件名称
    # ======================================================
    cursor.execute("""
        SELECT 1
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '后端管箱封头'
        LIMIT 1
    """, (product_id,))
    exists = cursor.fetchone()
    if exists:
        conn.close()
        print("ℹ️ 数据库已存在“后端管箱封头”，跳过插入")
        return

    # ======================================================
    # ① 获取 材料类型 / 材料牌号 / 供货状态 / 锻件级别
    # ======================================================
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱封头'
    """, (product_id,))
    rows = cursor.fetchall()

    mat_type = ""
    mat_grade = ""
    supply_status = ""
    forging_level = ""  # 锻件级别（Ⅱ、Ⅲ、Ⅳ等）

    for r in rows:
        name = r.get("参数名称")
        val = r.get("参数值")
        if name == "材料类型":
            mat_type = val
        elif name == "材料牌号":
            mat_grade = val
        elif name == "供货状态":
            supply_status = val
        elif name == "锻件级别":
            forging_level = val

    # ======================================================
    # 正确的钢锻件显示逻辑
    # ======================================================
    if mat_type == "钢锻件":
        if forging_level not in (None, "", "None"):
            mat_grade_display = f"{mat_grade}{forging_level}"
        else:
            mat_grade_display = mat_grade
    else:
        mat_grade_display = mat_grade

    # ======================================================
    # ② 获取“后端管箱圆筒”的重量
    # ======================================================
    cursor.execute("""
        SELECT Name, Value
        FROM 产品设计活动表_元件计算结果表
        WHERE 产品ID = %s AND 元件名称 = '后端管箱封头'
    """, (product_id,))
    rows = cursor.fetchall()

    mass = ""
    for r in rows:
        if "封头质量 kg" in (r.get("Name")):
            mass = r.get("Value")
            break

    conn.close()

    # ======================================================
    # ③ 找到插入位置（D列的第一个空行）
    # ======================================================
    insert_index = _first_empty_material_row(sheet)

    # 规格
    spec = generate_spec_houdan_fengtou(data)

    # ======================================================
    # ④ 插入行
    # ======================================================
    _insert_component_row(
        sheet, insert_index, "后端管箱封头", spec, mat_grade_display,
        1, mass, supply_status, mat_type,
    )

    print(f"✅ 已插入 后端管箱封头，第 {insert_index} 行")


# === 主函数入口 ===
def main(json_file_path, excel_file_path, sheet_name, product_id):
    import openpyxl
    from openpyxl.cell.cell import MergedCell
    from openpyxl.styles import Font, Border, Side, Alignment

    data = load_json_data(json_file_path)
    write_spec_to_excel(data, excel_file_path, sheet_name, product_id)

    wb = openpyxl.load_workbook(excel_file_path)
    sheet = wb[sheet_name]

    insert_houdan_guanxiang_yuantong(sheet, product_id, data)
    insert_houdan_guanxiang_fengtou(sheet, product_id, data)
    insert_jiaguan_falan_rows(sheet, product_id, data)
    nozzle_attachment_names = insert_nozzle_flange_attachment_rows(sheet, product_id, data)
    replace_and_insert_fencheng_gebans(sheet, product_id)

    insert_jiaguan_rows(sheet, product_id, data, "jisuan_output_new_tidai.json")
    clean_and_renumber(sheet, product_id)
    # 先判断是否存在“大端壳体圆筒加强段”
    dict_out_data = data.get("DictOutDatas", {})

    daduan_obj = dict_out_data.get("大端壳体圆筒加强段", {})
    daduan_datas = daduan_obj.get("Datas", []) if isinstance(daduan_obj, dict) else []

    if isinstance(daduan_datas, list) and len(daduan_datas) > 0:
        insert_daduan_guanxiang_yuantong(sheet, product_id, data)
    else:
        print("大端壳体圆筒加强段 Datas 为空，跳过 insert_daduan_guanxiang_yuantong")

    # 所有补充行插入完成后再统一编号，避免末尾追加的行没有序号。
    current_index = 1
    for row in iter_material_rows(sheet):
        if row[MATERIAL_NAME_COL - 1].value in (None, "", "None"):
            break
        row[0].value = current_index
        current_index += 1

    # 在总重计算前再次落实固定规则，防止规格/特殊件流程覆盖数量或单重。
    apply_fixed_material_item_rules(sheet, product_id=product_id)

    # ==================================================
    # 1️⃣ 填充 P 列：E * O（仅 B 列有值，且 P 为空）
    # ==================================================
    for row in iter_material_rows(sheet):
        if isinstance(row[MATERIAL_TOTAL_WEIGHT_COL - 1], MergedCell):
            continue

        d_val = row[MATERIAL_NAME_COL - 1].value
        g_val = row[MATERIAL_QUANTITY_COL - 1].value
        h_val = row[MATERIAL_UNIT_WEIGHT_COL - 1].value
        i_cell = row[MATERIAL_TOTAL_WEIGHT_COL - 1]

        if d_val and i_cell.value in (None, "", "None"):
            try:
                g = float(g_val) if g_val not in (None, "", "None") else 0
                h = float(h_val) if h_val not in (None, "", "None") else 0
                i_cell.value = round(g * h, 3)
            except:
                i_cell.value = 0

    # ==================================================
    # 2️⃣ 删除无效零件行
    # ==================================================
    remove_names = {"旁路挡板", "中间挡板", "防冲板", "挡管"}
    rows_to_delete = []

    for row in iter_material_rows(sheet):
        name_cell = row[MATERIAL_NAME_COL - 1]
        i = name_cell.row
        d_val = str(name_cell.value).strip() if name_cell.value else ""
        g_val = row[MATERIAL_QUANTITY_COL - 1].value
        if d_val in remove_names and g_val in (None, "", "None", 0, 0.0, "0"):
            rows_to_delete.append(i)

    remove_material_rows(sheet, rows_to_delete)

    # ==================================================
    # 3️⃣ 重排 A 列序号
    # ==================================================
    current_index = 1
    for row in iter_material_rows(sheet):
        d_val = row[MATERIAL_NAME_COL - 1].value
        if d_val in (None, "", "None"):
            break
        row[0].value = current_index
        current_index += 1

    # ==================================================
    # 4️⃣ DictOutDatas → 写入临时成型单重列（只执行一次）
    # ==================================================
    name_field_map = {
        "管箱法兰": ("管箱法兰", "法兰成型质量"),
        "固定管板": ("固定管板", "管板重量-成品（基层）"),
        "壳体法兰": ("壳体法兰", "法兰成型质量"),
        "头盖法兰": ("头盖法兰", "法兰成型质量"),
        "管箱平盖": ("管箱平盖", "法兰成型质量"),
        "外头盖法兰": ("外头盖法兰", "法兰成型质量"),
        "外头盖侧法兰": ("外头盖侧法兰", "法兰成型质量"),
        "浮动管板": ("固定管板", "浮动管板重量-成品"),
        "前端管箱平盖": ("管箱平盖", "法兰成型质量"),
        "前端管箱头盖法兰": ("头盖法兰", "法兰成型质量"),
        "前端管箱法兰": ("管箱法兰", "法兰成型质量"),
        "浮头法兰": ("浮头法兰", "腐蚀前管程浮头法兰成型重量"),

    }

    for row in iter_material_rows(sheet):
        part_name_cell = row[MATERIAL_NAME_COL - 1]
        part_name = str(part_name_cell.value).strip() if part_name_cell.value else ""
        if part_name in name_field_map:
            module, key = name_field_map[part_name]
            dict_out = (data or {}).get("DictOutDatas") or {}
            module_obj = dict_out.get(module) if isinstance(dict_out, dict) else None
            datas = (module_obj.get("Datas") if isinstance(module_obj, dict) else None) or []
            if not isinstance(datas, list):
                datas = []

            for item in datas:
                if item.get("Name") == key:
                    row[MATERIAL_FORMED_UNIT_WEIGHT_COL - 1].value = item.get("Value", "")
                    # 如果不是浮动管板和固定管板，再补充一句话
                    if part_name in ("头盖法兰", "管箱法兰", "壳体法兰", "外头盖侧法兰", "外头盖法兰", "前端管箱法兰",
                                     "前端管箱头盖法兰",):
                        row[MATERIAL_REMARK_COL - 1].value = "法兰高度不包含密封面凸台高度"
                    break
        # ===== 折流板相关（单独处理）=====
        if part_name in ("折流板", "弓形折流板", "异形折流板", "内折流板"):

            # 默认值
            final_value = None
            single_val = 0
            # ---------- 1. 折流板 / 弓形折流板 ----------
            if part_name in ("折流板", "弓形折流板"):
                # 同时从「管束」和「浮头管束」里找
                module_data = None
                if "管束" in data.get("DictOutDatas", {}):
                    module_data = data["DictOutDatas"]["管束"]
                elif "浮头管束" in data.get("DictOutDatas", {}):
                    module_data = data["DictOutDatas"]["浮头管束"]

                # 如果两个都不存在，直接跳过
                if not module_data:
                    pass
                else:
                    datas = module_data.get("Datas", [])

                    val_A = 0.0
                    val_B = 0.0
                    val_single = 0.0

                    for item in datas:
                        name = (item.get("Name") or "").strip()
                        try:
                            value = float(item.get("Value", 0) or 0)
                        except Exception:
                            value = 0.0

                        if name == "双弓形折流板A成型重量":
                            val_A = value
                        elif name == "双弓形折流板B成型重量":
                            val_B = value
                        elif name == "单弓形折流板成型重量":
                            val_single = value

                    # 2️⃣ 判断用 A+B 还是 单弓形
                    if val_A != 0 and val_B != 0:
                        row[MATERIAL_FORMED_UNIT_WEIGHT_COL - 1].value = val_A + val_B
                    else:
                        if val_single != 0:
                            row[MATERIAL_FORMED_UNIT_WEIGHT_COL - 1].value = val_single

            # ---------- 2. 异形折流板（仅浮头管束） ----------
            elif part_name == "异形折流板":
                datas = data.get("DictOutDatas", {}).get("浮头管束", {}).get("Datas", [])
                for item in datas:
                    if item.get("Name") == "异形折流板成型重量":
                        final_value = item.get("Value", "")
                        break

            # ---------- 3. 内折流板（仅浮头管束） ----------
            elif part_name == "内折流板":
                datas = data.get("DictOutDatas", {}).get("浮头管束", {}).get("Datas", [])
                for item in datas:
                    if item.get("Name") == "内折流板成型重量":
                        final_value = item.get("Value", "")
                        break

            # 写入结果
            if final_value not in (None, "", 0, "0"):
                row[MATERIAL_FORMED_UNIT_WEIGHT_COL - 1].value = final_value
            continue

    # ==================================================
    # 4.5️⃣ 最终统一删除所有无用元件（针对所有元件，不做单件特判）
    # ==================================================
    print("✅ [CUNGUIGE-CLEAN-V7] main 已执行到最终清理阶段")
    removed_unused_count = _remove_all_unused_components(
        sheet, product_id, data, preserved_names=nozzle_attachment_names,
    )
    if removed_unused_count:
        print(f"✅ 已统一删除无用元件 {removed_unused_count} 行")

    # 删除后必须重新编号，否则会出现 27、29 这种断号。
    current_index = 1
    for row in iter_material_rows(sheet):
        name_value = row[MATERIAL_NAME_COL - 1].value
        if name_value in (None, "", "None"):
            break
        row[0].value = current_index
        current_index += 1

    # ==================================================
    # 5️⃣ 计算成型质量：
    #    - 暂存成型单重为空时，以 O（毛坯单重）补齐
    #    - Q（成型总重）= 暂存成型单重 * E（数量）
    # ==================================================
    def to_float_safe(v):
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip()
        if s == "" or s.lower() == "none":
            return None
        s = s.replace(",", "")
        try:
            return float(s)
        except:
            return None

    weight_columns = MATERIAL_WEIGHT_COLUMNS

    for row in iter_material_rows(sheet):
        quantity_cell = row[MATERIAL_QUANTITY_COL - 1]
        rough_unit_cell = row[MATERIAL_UNIT_WEIGHT_COL - 1]
        rough_total_cell = row[MATERIAL_TOTAL_WEIGHT_COL - 1]
        formed_unit_cell = row[MATERIAL_FORMED_UNIT_WEIGHT_COL - 1]
        formed_total_cell = row[MATERIAL_FORMED_TOTAL_WEIGHT_COL - 1]

        if isinstance(formed_unit_cell, MergedCell) or isinstance(formed_total_cell, MergedCell):
            continue

        if formed_unit_cell.value in (None, "", "None"):
            formed_unit_cell.value = rough_unit_cell.value

        unit_num = to_float_safe(formed_unit_cell.value)
        quantity_num = to_float_safe(quantity_cell.value)
        if unit_num is not None and quantity_num is not None:
            formed_total_cell.value = round(unit_num * quantity_num, 2)
        elif formed_total_cell.value in (None, "", "None"):
            formed_total_cell.value = rough_total_cell.value

        for column in weight_columns:
            weight_cell = row[column - 1]
            weight_num = to_float_safe(weight_cell.value)
            if weight_num is not None:
                weight_cell.value = round(weight_num, 2)
            weight_cell.number_format = "0.00"

    # ==================================================
    # 5.5️⃣ 最终强制补齐前/后端封头质量
    #      两者数量均为1，O/P/Q继承各自的封头质量源。
    #      放在所有通用质量计算之后，防止中间流程再次覆盖。
    # ==================================================
    _force_fill_split_head_weights(sheet, data, product_id)

    # 以最终质量值统一两位小数，并仅在 P/Q 数值不同时加粗 Q。
    formed_total_difference_rows = set()
    for row in iter_material_rows(sheet):
        for column in weight_columns:
            weight_cell = row[column - 1]
            weight_num = to_float_safe(weight_cell.value)
            if weight_num is not None:
                weight_cell.value = round(weight_num, 2)
            weight_cell.number_format = "0.00"

        rough_total_num = to_float_safe(row[MATERIAL_TOTAL_WEIGHT_COL - 1].value)
        formed_total_num = to_float_safe(row[MATERIAL_FORMED_TOTAL_WEIGHT_COL - 1].value)
        if (
            rough_total_num is not None
            and formed_total_num is not None
            and round(rough_total_num, 2) != round(formed_total_num, 2)
        ):
            formed_total_difference_rows.add(row[MATERIAL_NAME_COL - 1].row)

    # ==================================================
    # 6️⃣ 删除多余空白行，并将 O:P:Q:R 的重量统计放在最后一条明细的下一行。
    # ==================================================
    last_data_row = trim_unused_material_rows(sheet)
    write_material_weight_totals(sheet, last_data_row)

    # 固定尾行也按最终生成行数顺延编号，且与生成内容之间没有空行。
    current_index = 1
    for row in iter_material_rows(sheet):
        if row[MATERIAL_NAME_COL - 1].value in (None, "", "None"):
            continue
        row[0].value = current_index
        current_index += 1
    for row in iter_material_fixed_tail_rows(sheet):
        row[0].value = current_index
        current_index += 1

    # ==================================================
    # 7️⃣ 统一样式
    # ==================================================
    thin = Side(border_style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    alignment = Alignment(horizontal="center", vertical="center")
    text_alignment = Alignment(horizontal="left", vertical="center")

    for row_idx in range(MATERIAL_START_ROW, last_data_row + 1):
        for column in MATERIAL_OUTPUT_COLUMNS[:-1]:
            cell = sheet.cell(row_idx, column)
            cell.border = border
            cell_bold = cell.font.bold
            if column == MATERIAL_FORMED_TOTAL_WEIGHT_COL:
                cell_bold = row_idx in formed_total_difference_rows
            cell.font = Font(
                name=MATERIAL_OUTPUT_FONT_NAME,
                size=10,
                bold=cell_bold,
                color="000000",
            )
            cell.alignment = (
                text_alignment
                if column in (MATERIAL_NAME_COL, MATERIAL_SPEC_COL)
                else alignment
            )

    _finalize_material_name_specs(sheet)
    if sheet.max_column >= MATERIAL_FORMED_UNIT_WEIGHT_COL:
        sheet.delete_cols(MATERIAL_FORMED_UNIT_WEIGHT_COL, 2)

    wb.save(excel_file_path)


from openpyxl import load_workbook
import xlwings as xw


def _update_u_tube_excel(output_path):
    """子进程执行的 Excel 操作"""
    app = xw.App(visible=False)
    try:
        wb = app.books.open(output_path)
        ws_source = wb.sheets["U形管明细"]
        ws_target = wb.sheets["Sheet1"]

        # 获取公式计算后的值
        value = ws_source.range("G6").value

        # 找到目标行并写入 P 列（毛坯总重）
        for row in range(1, ws_target.used_range.last_cell.row + 1):
            name = ws_target.range(f"B{row}").value
            if str(name or "").strip().startswith("U形换热管"):
                ws_target.range(f"P{row}").value = value
                break

        wb.save()
        wb.close()
    finally:
        app.quit()

def copy_u_tube_value_openpyxl(output_path):
    """
    不使用 xlwings / Excel COM。
    直接用 openpyxl 读取 U形管明细!G6，
    然后写入 Sheet1 中 B列为“U形换热管”的那一行 P列。
    """

    output_path = os.path.abspath(output_path)

    if not os.path.exists(output_path):
        raise FileNotFoundError(f"材料清单文件不存在: {output_path}")

    wb = openpyxl.load_workbook(output_path)

    try:
        if "U形管明细" not in wb.sheetnames:
            print("⚠️ 未找到工作表 'U形管明细'，跳过 U形换热管重量写入")
            return None

        if "Sheet1" not in wb.sheetnames:
            print("⚠️ 未找到工作表 'Sheet1'，跳过 U形换热管重量写入")
            return None

        ws_u = wb["U形管明细"]
        ws = wb["Sheet1"]

        def get_merged_cell_value(ws, cell_name):
            """
            兼容合并单元格。
            如果 G6 是合并单元格内部单元格，就取合并区域左上角的值。
            """
            value = ws[cell_name].value
            if value is not None:
                return value

            for merged_range in ws.merged_cells.ranges:
                if cell_name in merged_range:
                    return ws.cell(
                        row=merged_range.min_row,
                        column=merged_range.min_col
                    ).value

            return None

        def extract_number(value):
            if value is None:
                return None

            if isinstance(value, (int, float)):
                return float(value)

            s = str(value).strip()
            if s == "" or s.lower() in ("none", "null", "nan"):
                return None

            s = s.replace(",", "").replace("，", "")

            m = re.search(r"[-+]?\d*\.?\d+", s)
            return float(m.group()) if m else None

        raw_g6 = get_merged_cell_value(ws_u, "G6")
        tube_weight = extract_number(raw_g6)

        print(f"[openpyxl] U形管明细!G6 原始值={repr(raw_g6)} -> tube_weight={tube_weight}")

        if tube_weight is None:
            print("⚠️ U形管明细!G6 没有读取到有效数字，未写入 Sheet1")
            return None

        found = False

        # 新模板中元件名称在 B列，毛坯总重在 P列。
        for r in range(1, ws.max_row + 1):
            name = ws.cell(row=r, column=MATERIAL_NAME_COL).value

            if str(name or "").strip().startswith("U形换热管"):
                ws.cell(row=r, column=MATERIAL_TOTAL_WEIGHT_COL).value = tube_weight
                found = True
                print(f"✅ 已写入 Sheet1 第{r}行 P列：U形换热管重量={tube_weight}")
                break

        if not found:
            print("⚠️ Sheet1 中未找到 B列为 'U形换热管' 的行，未写入")

        wb.save(output_path)
        print(f"✅ openpyxl 已保存文件: {output_path}")

        return tube_weight

    finally:
        wb.close()
def copy_u_tube_value_live(output_path):
    """主函数调用，保证 Excel COM 独立于主线程"""
    output_path = os.path.abspath(output_path)

    p = Process(target=_update_u_tube_excel, args=(output_path,))
    p.start()
    p.join()

    if p.exitcode != 0:
        raise RuntimeError(f"copy_u_tube_value_live 子进程执行失败，exitcode={p.exitcode}，文件={output_path}")

    print(f"✅ copy_u_tube_value_live 执行完成：{output_path}")


def add_template_sheet(excel_file_path, template_file_path):
    wb = load_workbook(excel_file_path)

    # 已存在就删掉
    if "U形管明细" in wb.sheetnames:
        del wb["U形管明细"]

    template_wb = load_workbook(template_file_path)
    template_sheet = template_wb.active

    ws_new = wb.create_sheet(title="U形管明细")

    for row in template_sheet.iter_rows():
        for cell in row:
            new_cell = ws_new.cell(row=cell.row, column=cell.column, value=cell.value)
            if cell.has_style:
                new_cell.font = cell.font.copy()
                new_cell.border = cell.border.copy()
                new_cell.fill = cell.fill.copy()
                new_cell.number_format = cell.number_format
                new_cell.protection = cell.protection.copy()
                new_cell.alignment = cell.alignment.copy()

    thin = Side(border_style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    font = Font(name=MATERIAL_OUTPUT_FONT_NAME, size=10)

    for row in ws_new.iter_rows(min_row=8, min_col=1, max_col=18):
        for cell in row:
            cell.border = border
            cell.font = font

    wb.save(excel_file_path)


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


def fill_template_values(excel_file_path, product_id):
    import math
    import pymysql
    from openpyxl import load_workbook

    conn = pymysql.connect(
        host="localhost", user="root", password="123456",
        database="产品设计活动库", charset="utf8mb4",
        cursorclass=pymysql.cursors.Cursor
    )
    cursor = conn.cursor()

    conn2 = pymysql.connect(
        host="localhost", user="root", password="123456",
        database="材料库", charset="utf8mb4",
        cursorclass=pymysql.cursors.Cursor
    )
    cursor2 = conn2.cursor()

    wb = load_workbook(excel_file_path)
    ws = wb["U形管明细"]

    def get_value_teshu(sql, params=None):
        cursor.execute(sql, params or ())
        row = cursor.fetchone()
        return row[0] if row and row[0] is not None else None

    def get_value2(sql, params=None):
        cursor2.execute(sql, params or ())
        row = cursor2.fetchone()
        return row[0] if row and row[0] is not None else None

    def safe_float(v, default=0.0):
        try:
            if v is None:
                return default
            s = str(v).strip()
            if s == "" or s.lower() in ("none", "null"):
                return default
            return float(s)
        except Exception:
            return default

    def safe_int(v, default=0):
        try:
            if v is None:
                return default
            s = str(v).strip()
            if s == "" or s.lower() in ("none", "null"):
                return default
            return int(float(s))
        except Exception:
            return default

    def is_zero(v):
        if v is None:
            return True
        s = str(v).strip()
        if s == "" or s.lower() in ("none", "null"):
            return True
        try:
            return abs(float(s)) < 1e-9
        except Exception:
            return False

    def normalize_line_no(v):
        """
        把布管数量表中的行号/列号统一转为 1、2、3 这种整数。
        竖直表时，列号也按 line_no 处理。
        """
        try:
            return int(float(v))
        except Exception:
            return None

    def half_count(v):
        """
        交叉布管时，数量除以2。
        如果刚好是整数，写整数；否则保留小数，避免丢数量。
        """
        h = safe_float(v, 0.0) / 2.0
        if abs(h - round(h)) < 1e-9:
            return int(round(h))
        return h

    def fetch_tube_rows(table_name, line_col, count_col):
        """
        返回结构：
        [
            {
                "line_no": 行号/列号,
                "R": R值,
                "hole_count": 管孔数量
            },
            ...
        ]

        注意：
        这里按布管数量表中的行号/列号顺序读取，
        不再按 R 排序，避免 R=0 或管孔数量=0 的行跑到最前面。
        """
        sql = f"""
            SELECT 
                `{line_col}` AS line_no,
                R AS r_val,
                `{count_col}` AS hole_cnt
            FROM `{table_name}`
            WHERE 产品ID = %s
            ORDER BY CAST(`{line_col}` AS DECIMAL(20, 6)) ASC
        """
        cursor.execute(sql, (product_id,))
        raw_rows = cursor.fetchall()

        result = []
        for line_no, r_val, hole_cnt in raw_rows:
            result.append({
                "line_no": safe_float(line_no),
                "R": safe_float(r_val),
                "hole_count": safe_int(hole_cnt)
            })

        return result

    def fetch_incline_or_cross_rules():
        """
        读取交叉/倾斜布管判断结果。

        返回：
        {
            1: "仅倾斜" 或 "交叉",
            2: "仅倾斜" 或 "交叉",
            3: "仅倾斜" 或 "交叉"
        }

        规则：
        - 第一排/第二排/第三排不为0，说明该排需要特殊处理；
        - 交叉类型 = 2 时，为“仅倾斜”；
        - 其他值，比如 4，为“交叉”。
        """
        cursor.execute("""
            SELECT
                第一排,
                第二排,
                第三排,
                第一排交叉类型,
                第二排交叉类型,
                第三排交叉类型
            FROM 产品设计活动表_布管交叉布管表
            WHERE 产品ID = %s
            LIMIT 1
        """, (product_id,))

        row = cursor.fetchone()
        if not row:
            return {}

        first_row, second_row, third_row, first_type, second_type, third_type = row

        rules = {}

        for row_no, row_value, cross_type in [
            (1, first_row, first_type),
            (2, second_row, second_type),
            (3, third_row, third_type),
        ]:
            if not is_zero(row_value):
                if str(cross_type).strip() == "2":
                    rules[row_no] = "仅倾斜"
                else:
                    rules[row_no] = "交叉"

        return rules

    def fetch_incline_lengths():
        """
        从 产品设计活动表_元件计算结果表 中读取管束的六个倾斜管直管段长度。
        """
        length_names = [
            "倾斜管1直管段长度",
            "倾斜管2直管段长度",
            "倾斜管3直管段长度",
            "倾斜管4直管段长度",
            "倾斜管5直管段长度",
            "倾斜管6直管段长度",
        ]

        placeholders = ",".join(["%s"] * len(length_names))

        sql = f"""
            SELECT Name, Value
            FROM 产品设计活动表_元件计算结果表
            WHERE 产品ID = %s
              AND 元件名称 = '管束'
              AND Name IN ({placeholders})
        """

        cursor.execute(sql, [product_id] + length_names)
        rows = cursor.fetchall()

        result = {}
        for name, value in rows:
            result[name] = safe_float(value, None)

        return result

    def get_special_length(length_map, length_name, default_length, divide_by_2=False):
        """
        获取倾斜管直管段长度。

        规则：
        1. 仅倾斜：直接使用倾斜管直管段长度，不除以2。
        2. 交叉：每个交叉分支使用对应倾斜管直管段长度 / 2。
        """
        v = length_map.get(length_name)
        if v is None or is_zero(v):
            print(f"[WARN] 未找到 {length_name}，该行仍使用原始换热管公称长度 LN={default_length}")
            return default_length

        v = safe_float(v)
        return v / 2.0 if divide_by_2 else v

    def build_detail_rows(tube_rows, default_length):
        """
        根据交叉/仅倾斜规则，把原始 tube_rows 转成实际写入 Excel 的 detail_rows。

        普通行：
            D列 = 换热管公称长度 LN
            A列 = 原始层号/列号

        仅倾斜：
            第1排 -> 倾斜管2直管段长度
            第2排 -> 倾斜管4直管段长度
            第3排 -> 倾斜管6直管段长度
            注意：仅倾斜不除以2。

        交叉：
            第1排拆成两行：
                A列都为1
                倾斜管1直管段长度 / 2，数量 / 2
                倾斜管2直管段长度 / 2，数量 / 2

            第2排拆成两行：
                A列都为2
                倾斜管3直管段长度 / 2，数量 / 2
                倾斜管4直管段长度 / 2，数量 / 2

            第3排拆成两行：
                A列都为3
                倾斜管5直管段长度 / 2，数量 / 2
                倾斜管6直管段长度 / 2，数量 / 2

        关键：
            交叉拆出来的两行 A列层数相同；
            后续层数仍按原始层号继续，比如第1层交叉后，下面仍从2开始。
        """
        rules = fetch_incline_or_cross_rules()
        length_map = fetch_incline_lengths()

        row_length_names = {
            1: ("倾斜管1直管段长度", "倾斜管2直管段长度"),
            2: ("倾斜管3直管段长度", "倾斜管4直管段长度"),
            3: ("倾斜管5直管段长度", "倾斜管6直管段长度"),
        }

        detail_rows = []

        for row in tube_rows:
            line_no = normalize_line_no(row.get("line_no"))
            mode = rules.get(line_no)

            # A列显示层号。正常情况下就是原始 line_no。
            display_layer_no = line_no

            # 普通布管行
            if mode is None:
                new_row = dict(row)
                new_row["nominal_length"] = default_length
                new_row["special_mode"] = "普通"
                new_row["source_length_name"] = "换热管公称长度 LN"
                new_row["display_layer_no"] = display_layer_no
                detail_rows.append(new_row)
                continue

            # 防止异常行号
            if line_no not in row_length_names:
                new_row = dict(row)
                new_row["nominal_length"] = default_length
                new_row["special_mode"] = "普通"
                new_row["source_length_name"] = "换热管公称长度 LN"
                new_row["display_layer_no"] = display_layer_no
                detail_rows.append(new_row)
                continue

            length_name_1, length_name_2 = row_length_names[line_no]

            # 仅倾斜：
            # 第1排用倾斜管2直管段长度
            # 第2排用倾斜管4直管段长度
            # 第3排用倾斜管6直管段长度
            # 注意：这里不除以2
            if mode == "仅倾斜":
                new_row = dict(row)
                new_row["nominal_length"] = get_special_length(
                    length_map,
                    length_name_2,
                    default_length,
                    divide_by_2=False
                )
                new_row["special_mode"] = "仅倾斜"
                new_row["source_length_name"] = length_name_2
                new_row["display_layer_no"] = display_layer_no
                detail_rows.append(new_row)

            # 交叉：
            # 拆成两条记录；
            # 两条记录 A列层号相同；
            # 数量各除以2；
            # 长度各自除以2。
            else:
                for split_index, length_name in enumerate([length_name_1, length_name_2], start=1):
                    new_row = dict(row)
                    new_row["hole_count"] = half_count(row.get("hole_count"))
                    new_row["nominal_length"] = get_special_length(
                        length_map,
                        length_name,
                        default_length,
                        divide_by_2=False
                    )
                    new_row["special_mode"] = f"交叉{split_index}"
                    new_row["source_length_name"] = length_name
                    new_row["display_layer_no"] = display_layer_no
                    detail_rows.append(new_row)

        return detail_rows

    try:
        # --- 基础参数 C2,C3,C4,C5,E2,E4,E5 ---
        C2 = get_value_teshu(
            "SELECT 参数值 FROM 产品设计活动表_布管参数表 WHERE 产品ID=%s AND 参数名='换热管外径 do'",
            (product_id,)
        )

        C3 = get_value_teshu(
            "SELECT 参数值 FROM 产品设计活动表_布管参数表 WHERE 产品ID=%s AND 参数名='换热管壁厚 δ'",
            (product_id,)
        )

        C4 = get_value_teshu(
            "SELECT 参数值 FROM 产品设计活动表_布管参数表 WHERE 产品ID=%s AND 参数名='换热管公称长度 LN'",
            (product_id,)
        )

        default_nominal_length = safe_float(C4)

        material_name = get_value_teshu(
            "SELECT 参数值 FROM 产品设计活动表_元件附加参数表 "
            "WHERE 产品ID=%s AND 元件名称='U形换热管' AND 参数名称='材料牌号'",
            (product_id,)
        )

        C5 = None
        if material_name:
            den = get_value2(
                "SELECT 材料密度 FROM 材料密度表 WHERE 材料牌号=%s LIMIT 1",
                (material_name,)
            )
            if den is not None:
                C5 = safe_float(den) / 1000.0

        E2 = get_value_teshu(
            "SELECT 参数值 FROM 产品设计活动表_布管参数表 WHERE 产品ID=%s AND 参数名='换热管中心距 S'",
            (product_id,)
        )

        arrangement = get_value_teshu(
            "SELECT 参数值 FROM 产品设计活动表_布管参数表 WHERE 产品ID=%s AND 参数名='换热管排列方式'",
            (product_id,)
        )

        arrangement_map = {
            "正三角形": 30,
            "转角正三角形": 60,
            "正方形": 90,
            "转角正方形": 45
        }

        E4 = arrangement_map.get(arrangement, arrangement if arrangement is not None else 0)
        E4 = safe_float(E4)

        E5 = get_value_teshu(
            "SELECT Value FROM 产品设计活动表_元件计算结果表 "
            "WHERE 产品ID=%s AND 元件名称='固定管板' AND Name='管板名义厚度'",
            (product_id,)
        )
        E5_val = safe_float(E5)

        # --- 优先读取水平表；如果没有，再读取竖直表 ---
        tube_rows = fetch_tube_rows(
            table_name="产品设计活动表_布管数量表_水平",
            line_col="至水平中心线行号",
            count_col="管孔数量（上）"
        )

        if not tube_rows:
            tube_rows = fetch_tube_rows(
                table_name="产品设计活动表_布管数量表_竖直",
                line_col="至竖直中心线行号",
                count_col="管孔数量（左）"
            )

        # 这里不要再按 R 排序
        # tube_rows.sort(key=lambda x: (x["R"], x["line_no"]))

        # 根据交叉/仅倾斜规则生成实际写入行
        detail_rows = build_detail_rows(tube_rows, default_nominal_length)

        if not detail_rows:
            wb.save(excel_file_path)
            return

        print("========== U形管明细最终写入行 ==========")
        for i, row in enumerate(detail_rows, start=1):
            print(
                f"序号={i}, "
                f"原始行/列号={row.get('line_no')}, "
                f"R={row.get('R')}, "
                f"写入E列R/2={safe_float(row.get('R')) / 2.0}, "
                f"管孔数量={row.get('hole_count')}, "
                f"D列公称长度={row.get('nominal_length')}, "
                f"模式={row.get('special_mode')}, "
                f"长度来源={row.get('source_length_name')}"
            )

        # --- 写入 N/O 辅助区 ---
        e2_num = safe_float(E2)

        ws["N2"].value = 30
        ws["N3"].value = 60
        ws["N4"].value = 45
        ws["N5"].value = 90

        ws["O2"].value = e2_num / 2.0 * math.sqrt(3)
        ws["O3"].value = e2_num / 2.0
        ws["O4"].value = e2_num * math.sqrt(2) / 2.0
        ws["O5"].value = e2_num

        # --- 清理旧的明细数据，避免上次交叉拆行后留下多余旧行 ---
        start_row = 10
        for row in ws.iter_rows(min_row=start_row, max_row=ws.max_row, min_col=1, max_col=11):
            for cell in row:
                cell.value = None

        # --- 从第10行开始逐行计算并写入 A-K 列 ---
        results = []

        B_val = safe_float(C2)
        C_val = safe_float(C3)
        C5_val = safe_float(C5)

        for idx, row_data in enumerate(detail_rows):
            row_no = start_row + idx

            # A列不能用最终写入序号；
            # 交叉拆成两行时，两行层数应该相同；
            # 后续层数仍按原始层号继续。
            A = row_data.get("display_layer_no")
            if A is None:
                A = idx + 1
            B = B_val
            C = C_val

            # D列：现在不是固定 C4，而是每一行自己的 nominal_length
            D = safe_float(row_data.get("nominal_length"), default_nominal_length)

            # E列：R值 / 2
            E = safe_float(row_data.get("R")) / 2.0

            # F = 2*D + PI()*E
            F = 2.0 * D + math.pi * E

            # G列：管孔数量；交叉时已经在 detail_rows 中除以2
            G = safe_float(row_data.get("hole_count"))

            # 如果 G 是整数，写整数；否则保留小数
            if abs(G - round(G)) < 1e-9:
                G_write = int(round(G))
            else:
                G_write = G

            # H = C * (B - C) * PI() * F * C5 *0.001*0.001
            H = C * (B - C) * math.pi * F * C5_val * 0.001 * 0.001

            # I = G * H
            I = G * H

            # J = PI()/4*(B-2*C)^2 * F *0.001^3 * G
            J = math.pi / 4.0 * (B - 2.0 * C) ** 2 * F * 0.001 * 0.001 * 0.001 * G

            # K = PI()/4 * B^2 * (F - 2*E5) * 0.001^3 * G
            K = math.pi / 4.0 * B ** 2 * (F - 2.0 * E5_val) * 0.001 * 0.001 * 0.001 * G

            # G5 对应原公式：
            # PI()*B*(2*D - 2*E5)*0.001^2*G
            # 现在 D 可能每行不同，所以必须逐行算后求和，不能再用统一 C4 * G_sum
            G5_item = math.pi * B * (2.0 * D - 2.0 * E5_val) * 0.001 * 0.001 * G

            ws.cell(row=row_no, column=1, value=A)        # A
            ws.cell(row=row_no, column=2, value=B)        # B
            ws.cell(row=row_no, column=3, value=C)        # C
            ws.cell(row=row_no, column=4, value=D)        # D
            ws.cell(row=row_no, column=5, value=E)        # E
            ws.cell(row=row_no, column=6, value=F)        # F
            ws.cell(row=row_no, column=7, value=G_write)  # G
            ws.cell(row=row_no, column=8, value=H)        # H
            ws.cell(row=row_no, column=9, value=I)        # I
            ws.cell(row=row_no, column=10, value=J)       # J
            ws.cell(row=row_no, column=11, value=K)       # K

            results.append({
                "I": I,
                "J": J,
                "K": K,
                "G": G,
                "G5_item": G5_item
            })
        # --- 最终校验：数量列 G 为 0 的明细行删除，并重新编号 A 列 ---
        data_start_row = start_row
        data_end_row = start_row + len(detail_rows) - 1

        kept_rows = []
        kept_results = []

        for offset, excel_row in enumerate(range(data_start_row, data_end_row + 1)):
            g_value = ws.cell(row=excel_row, column=7).value  # G列：数量

            # G列数量为0，则该行最终不保留
            if is_zero(g_value):
                continue

            row_values = [
                ws.cell(row=excel_row, column=col).value
                for col in range(1, 12)
            ]
            kept_rows.append(row_values)

            if offset < len(results):
                kept_results.append(results[offset])

        # 清空原来的明细区域 A-K
        for excel_row in range(data_start_row, data_end_row + 1):
            for col in range(1, 12):
                ws.cell(row=excel_row, column=col).value = None

        # 将保留行重新写回，并只重排 A 列序号
        for new_idx, row_values in enumerate(kept_rows, start=1):
            target_row = data_start_row + new_idx - 1

            # 只在最后重排第一列序号
            row_values[0] = new_idx

            for col, value in enumerate(row_values, start=1):
                ws.cell(row=target_row, column=col, value=value)

        # 汇总结果也同步去掉数量为0的行
        results = kept_results
        # --- 写入汇总行 G2~G6 ---
        I_sum = sum(r["I"] for r in results)
        J_sum = sum(r["J"] for r in results)
        K_sum = sum(r["K"] for r in results)
        G_sum = sum(r["G"] for r in results)
        G5_sum = sum(r["G5_item"] for r in results)

        ws["G6"].value = I_sum
        ws["G2"].value = J_sum
        ws["G3"].value = K_sum

        if abs(G_sum - round(G_sum)) < 1e-9:
            ws["G4"].value = int(round(G_sum))
        else:
            ws["G4"].value = G_sum

        ws["G5"].value = G5_sum

        # 删除 K 之后的列，保持到 K 列
        while ws.max_column > 11:
            ws.delete_cols(12)

        wb.save(excel_file_path)

    finally:
        cursor.close()
        conn.close()
        cursor2.close()
        conn2.close()


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


# === 示例调用 ===
if __name__ == "__main__":
    main("jisuan_output_new_tidai.json", "材料清单_已填.xlsx", "Sheet1")

