import ast
import json
import math
import os

import configparser

import chardet
import pandas as pd
import pymysql
import openpyxl
from openpyxl.reader.excel import load_workbook

from modules.chanpinguanli.chanpinguanli_main import product_manager
from modules.wenbenshengcheng.cunguige import get_ttgd_from_db

product_id = None


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

import ast  # 比 eval 安全，用来解析字符串形式的 list/tuple

import ast


def get_tie_rods_length(product_id, conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 坐标
        FROM 产品设计活动表_布管元件表
        WHERE 产品ID = %s AND 元件类型 = %s
    """, (product_id, 0))

    rows = cursor.fetchall() or []
    coords = []

    for row in rows:
        # 兼容 tuple 和 dict
        val = row[0] if isinstance(row, (tuple, list)) else row["坐标"]

        if val is None:
            continue
        if isinstance(val, list):
            coords.extend(val)
        elif isinstance(val, str):
            try:
                arr = ast.literal_eval(val)  # 解析 "[(-10,-1),(-11,-1)]"
                if isinstance(arr, list):
                    coords.extend(arr)
            except Exception:
                pass

    return len(coords)


# === 精准映射：元件名称 → List[(section, 字段名, 类型)]
mapping_dict = {
    "管箱封头": [("管箱封头", "椭圆形封头质量 kg", "质量")],
    "管箱圆筒": [("管箱圆筒", "圆筒重量kg", "质量")],
    "外头盖圆筒": [("外头盖圆筒", "圆筒重量kg", "质量")],
    "外头盖封头": [("外头盖封头", "椭圆形封头质量 kg", "质量")],
    "浮头法兰": [("浮头法兰", "腐蚀前管程浮头法兰重量", "质量")],
    "浮动管板": [("固定管板", "管板重量-毛坯", "质量")],

    "管箱法兰": [("管箱法兰", "法兰毛坯质量", "质量")],
    "固定管板": [("固定管板", "管板重量-毛坯", "质量")],
    "U形换热管": [("固定管板", "换热管根数", "数量")],
    "壳体法兰": [("壳体法兰", "法兰毛坯质量", "质量")],
    "管箱平盖":[("管箱平盖", "法兰毛坯质量", "质量")],
    "头盖法兰":[("头盖法兰", "法兰毛坯质量", "质量")],
    "外头盖法兰": [("外头盖法兰", "法兰毛坯质量", "质量")],
    "外头盖侧法兰": [("外头盖侧法兰", "法兰毛坯质量", "质量")],
    "壳体圆筒": [("壳体圆筒", "圆筒重量kg", "质量")],
    "壳体封头": [("壳体封头", "椭圆形封头质量 kg", "质量")],
    "固定鞍座": [("固定鞍座", "鞍式支座质量", "质量")],
    "螺柱（管箱法兰）": [("管箱法兰", "螺栓数量", "数量")],
    "尾部支撑": [("管束", "尾部支撑数量", "数量")],
    "折流板": [("管束", "折流板数量", "数量")],
    "分程隔板": [("管箱分程隔板", "管箱分程隔板重量", "质量")],
    "螺柱（壳体法兰）": [("壳体法兰", "螺栓数量", "数量")],
    "螺柱（浮头法兰）": [("浮头法兰", "螺栓数量", "数量")],
    "换热管": [("固定管板", "换热管根数", "数量")],
    "异形折流板": [("浮头管束", "异形折流板重量", "质量")],
    "弓形折流板": [("浮头管束", "弓形折流板重量", "质量")],
    "支撑板": [("浮头管束", "固定侧支撑板重量", "质量")],
    "支持板": [("浮头管束", "支持板重量", "质量")],
    "内导流筒": [("浮头管束", "固定侧导流筒重量", "质量")],
    "滑道": [("浮头管束", "滑道重量", "质量")],
    "中间挡管": [("浮头管束", "中间挡管重量", "质量")],
    "防冲挡板重量": [("浮头管束", "防冲挡板重量", "质量")],
    "堵板": [("浮头管束", "堵板重量", "质量")],
    "拉杆": [("浮头管束", "拉杆重量", "质量")],
    "定距管": [("浮头管束", "定距管重量", "质量")],
    "隔板": [("管箱分程隔板", "水平隔板数量", "数量"),("管箱分程隔板", "管箱分程隔板重量", "质量")],
    "钩圈": [("浮头法兰", "钩圈重量", "质量")],
    "内折流板": [("浮头管束", "内折流板重量", "质量")],
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
    for row in sheet.iter_rows(min_row=8):
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
def fill_special_items(sheet, jisuan_data, product_id):
    import re
    pipe_data={}
    pipe_input_data={}
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

    def get_luozhu_length(data, product_id):
        dh = get_value(data, "管箱法兰", "螺栓公称直径")
        if dh is None:
            return None
        try:
            dh_val = int(re.search(r'\d+', str(dh)).group())
        except:
            dh_val = 0
        flange_thk_1 = get_value(data, "管箱法兰", "法兰名义厚度") or 0
        gasket_thk_1 = get_value(data, "管箱法兰", "垫片厚度") or 0
        flange_thk_2 = get_value(data, "壳体法兰", "法兰名义厚度") or 0
        gasket_thk_2 = get_value(data, "管箱法兰", "垫片厚度") or 0
        ttgd = get_ttgd_from_db(product_id) or 0
        return 20 + 2 * dh_val + flange_thk_1 + gasket_thk_1 + flange_thk_2 + gasket_thk_2 - 2 * ttgd

    def get_value(data, section, name):
        for section_name, section_data in data.get("DictOutDatas", {}).items():
            if section_name == section:
                for item in section_data.get("Datas", []):
                    if item.get("Name") == name:
                        try:
                            return float(item["Value"])
                        except:
                            return item["Value"]
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
    print("denisty_huadao",denisty_huadao)
    slipway_mass = calc_slipway_mass(product_id, jisuan_data, denisty_huadao)
    print("slipway_mass",slipway_mass)
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
    datas = jisuan_data.get("DictOutDatas", {}).get("管箱法兰", {}).get("Datas", [])
    luozhu_qty = next((int(float(item.get("Value", "0"))) for item in datas if item.get("Name") == "螺栓数量"), None)
    datas2 = jisuan_data.get("DictOutDatas", {}).get("管箱平盖", {}).get("Datas", [])
    luozhu_qty2 = next((int(float(item.get("Value", "0"))) for item in datas2 if item.get("Name") == "螺栓数量"), None)
    datas3 = jisuan_data.get("DictOutDatas", {}).get("浮头法兰", {}).get("Datas", [])
    luozhu_qty3 = next((int(float(item.get("Value", "0"))) for item in datas3 if item.get("Name") == "螺栓数量"), None)
    datas4 = jisuan_data.get("DictOutDatas", {}).get("外头盖法兰", {}).get("Datas", [])
    luozhu_qty4 = next((int(float(item.get("Value", "0"))) for item in datas3 if item.get("Name") == "螺栓数量"), None)

    guanshu_datas = jisuan_data.get("DictOutDatas", {}).get("管束", {}).get("Datas", [])
    baffle_R = get_param(guanshu_datas, "折流板/支持板外直径")
    baffle_t = get_param(guanshu_datas, "折流板厚度")
    support_R = get_param(guanshu_datas, "折流板/支持板外直径")
    support_t = get_param(guanshu_datas, "支持板厚度")

    saddle_data = jisuan_data.get("DictOutDatas", {}).get("鞍座", {}).get("Datas", [])
    saddle_mass = get_param(saddle_data, "鞍式支座质量")
    print("saddle_mass",saddle_mass)
    saddle_mass = float(saddle_mass) if saddle_mass not in (None, "", "None") else None

    uhx_data = jisuan_data.get("DictOutDatas", {}).get("固定管板", {}).get("Datas", [])
    uhx_mass = get_param(uhx_data, "单根换热管重量kg")
    uhx_mass = float(uhx_mass) if uhx_mass not in (None, "", "None") else None


    # 使用时
    tie_list = get_tie_rods_length(product_id, conn)
    print("tie_list",tie_list)
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
        # "旁路挡板": count_valid_items(pipe_data, "BPBs"),
        "拉杆": tie_list,
        # "中间挡板": count_valid_items(pipe_data, "VerticalBaffle"),
        "滑道": get_slipway_count(product_id),
        "防冲板": 1 if isinstance(pipe_data.get("ImpingementPlate"), dict) else 0,
        "定距管": tie_list,
        "螺母（拉杆）": tie_list,
        "管箱侧垫片": 1,
        "外头盖垫片": 1,
        "平盖垫片": 1,

        "管箱垫片": 1,
        "浮头法兰":1,
        "浮头垫片":1,
        "球冠形封头":1,
        "浮动管板":1,
        "支持板":1,
        '铭牌板': 1,
        "铭牌支架": 1,
        "顶板": 1,

    }
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
    }
    mass_luozhu = None
    # === 遍历写入 Excel sheet ===
    for row in sheet.iter_rows(min_row=2):
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
            row[6].value = tie_list
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

            dh_str=None
            for r in rows:
                name, value = r if isinstance(r, (tuple, list)) else (r["参数名"], r["参数值"])
                if name == "拉杆直径":
                    dh_str = value
            print("直径：",dh_str)
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
            H1 = get_param(datas, "拉杆长度1")
            H2 = get_param(datas, "拉杆长度2")
            H = max(H1, H2)

            # 密度
            density = get_material_density("拉杆", product_id)
            print("R:",R)
            print("H:",H)
            print("density:",density)


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
                name, value = r if isinstance(r, (tuple, list)) else (r["参数名"], r["参数值"])
                if name == "拉杆直径":
                    dh_str = value
            dia = str("M"+str(int(dh_str)))
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
            print("管程程数：",fencheng)
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

        elif name == "铭牌支架":
            row[7].value = 1

        elif name in {"管箱吊耳", "吊耳", "管箱垫片", "管箱侧垫片", "外头盖侧垫片", "外头盖垫片","平盖垫片"}:
            row[7].value = "/"

        elif name == "U形换热管":
            # uhx_data = jisuan_data.get("DictOutDatas", {}).get("固定管板", {}).get("Datas", [])
            # uhx_mass = get_param(uhx_data, "单根换热管重量kg")
            # row[7].value = float(uhx_mass) if uhx_mass not in (None, "", "None") else None
            row[7].value = "见U型管明细工作表"
        elif name == "旁路挡板":
            print("➡ 进入旁路挡板计算分支")  # 🔹 打印进入分支
            # --- 从 产品设计活动表_布管元件表 中读取 元件类型=3 的 坐标 字段 ---
            bpb_coords = []
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
                    "SELECT 坐标 FROM 产品设计活动表_布管元件表 WHERE 产品ID = %s AND 元件类型 = 3",
                    (product_id,)
                )
                rows_coords = cur_tmp.fetchall()
                for r in rows_coords:
                    coord_raw = r[0]
                    if coord_raw is None:
                        continue
                    parsed = None
                    # 尝试 json -> ast.literal_eval -> 直接使用
                    if isinstance(coord_raw, str):
                        s = coord_raw.strip()
                        try:
                            parsed = json.loads(s)
                        except Exception:
                            try:
                                parsed = ast.literal_eval(s)
                            except Exception:
                                parsed = None
                    else:
                        parsed = coord_raw

                    if parsed is None:
                        continue
                    # 期望 parsed 为 list/tuple（数组），否则将其包装为单元素数组
                    if isinstance(parsed, (list, tuple)):
                        bpb_coords.append(parsed)
                    else:
                        bpb_coords.append([parsed])
            except Exception as e:
                print(f"❌ 从布管元件表获取旁路挡板坐标失败: {e}")
            finally:
                try:
                    conn_tmp.close()
                except Exception:
                    pass

            # 每个数组元素数 n 对应挡板数量 2*n（1->2, 2->4）
            bpb_count = sum(2 * len(arr) for arr in bpb_coords)
            row[6].value = bpb_count

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
                cur.execute(
                    "SELECT 参数值 FROM 产品设计活动表_布管参数表 "
                    "WHERE 产品ID=%s AND 参数名=%s LIMIT 1",
                    (product_id, "旁路挡板宽度")
                )
                row_param = cur.fetchone()
                print(f"数据库查询旁路挡板宽度: {row_param}")
                if row_param and row_param[0] is not None:
                    try:
                        raw_float = float(row_param[0])
                        print(f"原始宽度参数值: {raw_float}")
                        width_mm_val = abs(raw_float)
                        print(f"取绝对值后: {width_mm_val}")
                    except Exception as e:
                        print(f"转换旁路挡板宽度失败: {e}")
                        width_mm_val = 0.0
                else:
                    width_mm_val = 0.0
                    print("旁路挡板宽度为空或None")
                print(f"宽度 width_mm_val = {width_mm_val}")

            except Exception as e:
                print(f"❌ 读取旁路挡板参数失败: {e}")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

            # --- 获取拉杆长度 ---
            pipe_datas = jisuan_data.get("DictOutDatas", {}).get("管束", {}).get("Datas", [])
            if not pipe_datas:
                pipe_datas = jisuan_data.get("DictOutDatas", {}).get("浮头管束", {}).get("Datas", [])
            print(f"管束数据: {pipe_datas}")

            H1 = get_param(pipe_datas, "拉杆长度1")
            H2 = get_param(pipe_datas, "拉杆长度2")
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

            # --- 计算第一个挡板质量 ---
            if bpb_count > 0 and thickness_mm > 0 and width_mm_val > 0 and length_m > 0:
                try:
                    volume = (thickness_mm/1000) * (width_mm_val/1000) * length_m
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

        elif name == "弓形折流板":

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

            vbaffles = pipe_data.get("VerticalBaffle", [])

            qty = len(vbaffles)

            row[6].value = qty

            try:

                # === 获取厚度和宽度（取第一个挡板）

                if vbaffles:

                    thickness_mm = float(vbaffles[0].get("Width", 0))  # mm

                    width_mm = float(vbaffles[0].get("Height", 0))  # mm

                else:

                    thickness_mm = width_mm = 0

                # === 获取长度（来自 jisuan_data）

                mid_baffle_length = get_param(

                    jisuan_data.get("DictOutDatas", {}).get("管束", {}).get("Datas", []),

                    "中间挡管/挡板长度"

                )

                length_m = float(mid_baffle_length) / 1000 if mid_baffle_length else 0

                # === 获取密度

                density = get_material_density("中间挡板", product_id)  # kg/m³

                # === 计算质量

                volume = (thickness_mm / 1000) * (width_mm / 1000) * length_m  # m³

                total_mass = volume * density * qty

                row[7].value = round(total_mass, 2)

            except Exception as e:

                print(f"❌ 计算中间挡板质量失败: {e}")
        elif name == "螺柱（外头盖法兰）" and luozhu_qty4:

            row[6].value = luozhu_qty

            dh = get_value(jisuan_data, "外头盖法兰", "螺栓公称直径")

            R = get_actual_diameter(dh)

            H = get_luozhu_length(jisuan_data, product_id)

            density = get_material_density("螺柱（外头盖法兰）", product_id) * 1000

            print("R", R)

            print("H", H)

            print("density", density)

            if R and H and density:
                mass_luozhu = round((math.pi * (R / 1000) ** 2 / 4) * (H / 1000) * density, 2)

                row[7].value = mass_luozhu
        elif name == "螺母（外头盖法兰）" and luozhu_qty4:

            row[6].value = luozhu_qty * 2

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

            row[6].value = int(luozhu_qty) - int(qty)

            dh = get_value(jisuan_data, "管箱法兰", "螺栓公称直径")

            R = get_actual_diameter(dh)

            H = get_luozhu_length(jisuan_data, product_id)

            density = get_material_density("螺柱（管箱法兰）", product_id) * 1000

            print("R", R)

            print("H", H)

            print("density", density)

            if R and H and density:
                mass_luozhu = round((math.pi * (R / 1000) ** 2 / 4) * (H / 1000) * density, 2)

                row[7].value = mass_luozhu


        elif name == "螺柱（浮头法兰）":

            dh = get_value(jisuan_data, "浮头法兰", "螺栓公称直径")

            R = get_actual_diameter(dh)

            H = get_luozhu_length(jisuan_data, product_id)

            density = get_material_density("螺柱（浮头法兰）", product_id)

            print("R", R)

            print("H", H)

            print("density", density)

            if R and H and density:
                mass_luozhu = round((math.pi * (R / 1000) ** 2 / 4) * (H / 1000) * density, 2) * 1000

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


        elif name == "螺柱（管箱平盖）" and luozhu_qty2:

            row[6].value = luozhu_qty2

            dh = get_value(jisuan_data, "管箱平盖", "螺栓公称直径")

            R = get_actual_diameter(dh)

            H = get_luozhu_length(jisuan_data, product_id)

            density = get_material_density("螺柱（管箱平盖）", product_id)

            print("R", R)

            print("H", H)

            print("density", density)

            if R and H and density:
                mass_luozhu = round((math.pi * (R / 1000) ** 2 / 4) * (H / 1000) * density, 2) * 1000

                row[7].value = mass_luozhu




        elif name == "螺母（管箱平盖）" and luozhu_qty2:

            row[6].value = luozhu_qty2 * 2

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

        elif name == "折流板" and baffle_R and baffle_t:

            density_zheliuban = get_material_density("折流板", product_id)

            row[7].value = calc_weight(baffle_R, baffle_t, density_zheliuban)

        # elif name == "防冲板":

        elif name == "支持板":

            if not row[6].value:
                row[6].value = 1

            if support_R and support_t:
                density_zhichiban = get_material_density("支持板", product_id)

                row[7].value = calc_weight(support_R, support_t, density_zhichiban)

        elif name == "挡管":

            # 获取挡管数量

            dummy_tubes = pipe_data.get("dummy_tubes", [])

            if isinstance(dummy_tubes, str):
                dummy_tubes = ast.literal_eval(dummy_tubes)

            dummy_count = len(dummy_tubes)

            print(dummy_tubes)

            print(dummy_count)

            row[6].value = dummy_count

            uhx_data = jisuan_data.get("DictOutDatas", {}).get("固定管板", {}).get("Datas", [])

            uhx_mass = get_param(uhx_data, "单根换热管重量kg")

            uhx_mass = float(uhx_mass) if uhx_mass not in (None, "", "None") else None

            row[7].value = uhx_mass

        elif name == "换热管":

            uhx_data = jisuan_data.get("DictOutDatas", {}).get("固定管板", {}).get("Datas", [])

            uhx_mass = get_param(uhx_data, "单根换热管重量kg")

            uhx_mass = float(uhx_mass) if uhx_mass not in (None, "", "None") else None

            row[7].value = uhx_mass

        elif name == "浮动管板":

            uhx_data = jisuan_data.get("DictOutDatas", {}).get("固定管板", {}).get("Datas", [])

            uhx_mass = get_param(uhx_data, "单根换热管重量kg")

            uhx_mass = float(uhx_mass) if uhx_mass not in (None, "", "None") else None

            row[7].value = uhx_mass

        elif name == "铭牌板":

            uhx_mass = 0.8

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

        elif name in {"固定鞍座", "滑动鞍座"}:

            if not row[6].value:
                row[6].value = 1

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
    template_path = os.path.join(os.getcwd(), "modules/wenbenshengcheng/设备材料清单.xlsx")
    if not os.path.exists(template_path):
        raise FileNotFoundError("未找到模板文件: 设备材料清单.xlsx")

    connection = pymysql.connect(
        host='localhost',
        port=3306,
        user='root',
        password='123456',
        database='产品设计活动库',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

    try:
        with connection.cursor() as cursor:
            # 先取元件材料表
            sql = """
                SELECT 元件名称, 材料类型, 材料牌号, 材料标准, 供货状态
                FROM 产品设计活动表_元件材料表
                WHERE 产品ID = %s
                """
            cursor.execute(sql, (product_id,))
            rows = cursor.fetchall()

            if not rows:
                print(f"⚠️ 未找到产品ID {product_id} 的材料数据")
                return

            # 再取锻件级别信息
            sql_param = """
                SELECT 元件名称, 参数名称, 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s 
                  AND 参数名称 IN ('锻件级别','材料类型')
                  AND 参数值 IS NOT NULL AND 参数值 <> ''
                """
            cursor.execute(sql_param, (product_id,))
            param_rows = cursor.fetchall()

            # 整理出 {元件名称: {"材料类型": "xxx", "锻件级别": "yyy"}}
            param_map = {}
            for r in param_rows:
                comp = r["元件名称"]
                if comp not in param_map:
                    param_map[comp] = {}
                param_map[comp][r["参数名称"]] = r["参数值"]

            # 过滤出 材料类型=钢锻件 的才保留锻件级别
            forging_level_map = {}
            for comp, p in param_map.items():
                if p.get("材料类型") == "钢锻件" and "锻件级别" in p:
                    forging_level_map[comp] = p["锻件级别"]

    finally:
        connection.close()

    wb = openpyxl.load_workbook(template_path)
    sheet = wb.active

    for idx, row in enumerate(rows):
        row_idx = 8 + idx
        sheet[f"A{row_idx}"] = idx + 1
        sheet[f"D{row_idx}"] = row["元件名称"]

        # 判断是否需要拼接锻件级别
        material = "/" if row["材料牌号"] == "见参数定义" else row["材料牌号"]
        if row["元件名称"] in forging_level_map:
            material = f"{material} {forging_level_map[row['元件名称']]}"

        sheet[f"F{row_idx}"] = material
        sheet[f"K{row_idx}"] = "/" if row["材料类型"] == "见参数定义" else row["材料类型"]
        sheet[f"J{row_idx}"] = "/" if row["供货状态"] == "见参数定义" else row["供货状态"]

    # 加载 JSON
    json_jisuan = load_json_file(os.path.join(os.getcwd(), "jisuan_output_new.json"))
    # 填写信息
    fill_quantity_weight(json_jisuan, sheet)
    fill_special_items(sheet, json_jisuan,product_id)

    # 保存
    wb.save(output_path)
    print(f"✅ 材料清单已生成：{output_path}")

def fill_quantity_by_relation(sheet):
    """
    根据其他元件的数量或默认规则，补充填写G列数量。
    """
    # 收集所有结构件 → 数量映射（G列）
    name_to_qty = {}
    for row in sheet.iter_rows(min_row=8):
        name_cell = row[3]  # D列
        qty_cell = row[6]  # G列
        if not name_cell.value:
            continue
        item_name = str(name_cell.value).strip()
        name_to_qty[item_name] = qty_cell.value

    # 定义依赖逻辑
    for row in sheet.iter_rows(min_row=8):
        name_cell = row[3]
        qty_cell = row[6]
        if not name_cell.value:
            continue
        item_name = str(name_cell.value).strip()

        # 仅在数量为空时填
        if qty_cell.value not in [None, ""] and qty_cell.value != 0:
            continue

        # 1. 与拉杆数量一致
        if item_name in {"螺母（拉杆）", "定距管"}:
            qty_cell.value = name_to_qty.get("拉杆", "")

        # 2. 螺柱 × 2
        elif item_name == "螺柱（管箱法兰）":
            val = name_to_qty.get("螺柱", "")
            if isinstance(val, (int, float)):
                qty_cell.value = val * 2

        # 3. 防松支耳 → 螺母（管箱法兰）
        elif item_name == "螺母（管箱法兰）":
            qty_cell.value = name_to_qty.get("防松支耳", "")

        # 4. 一些元件固定数量为 1
        elif item_name in {
            "管箱垫片", "支持板", "管箱侧垫片", "固定鞍座", "滑动鞍座","铭牌支架","铭牌板","浮头法兰","浮头垫片","球冠形封头","吊耳"
        }:
            qty_cell.value = 1
        elif item_name in {
            "铆钉"
        }:
            qty_cell.value = 8

    print("✅ 已填写依赖关系数量（如与拉杆相同、固定为1等）")


# def fill_additional_quantities(sheet, path_to_json):
#     try:
#         with open(path_to_json, "r", encoding="utf-8") as f:
#             pipe_data = json.load(f)
#     except Exception as e:
#         print(f"❌ 无法读取布管输出参数文件: {e}")
#         return
#
#     # 计数函数：获取含特征字段的数组元素数量
#     def count_valid_items(array_key, required_field):
#         items = pipe_data.get(array_key, [])
#         if not isinstance(items, list):
#             return 0
#         return sum(1 for item in items if isinstance(item, dict) and required_field in item)
#
#     quantity_map = {
#         "旁路挡板": count_valid_items("BPBs", "BPBHeight"),
#         "拉杆": count_valid_items("TieRodsParam", "Postion"),
#         "滑道": count_valid_items("SlipWays", "P1"),
#         "中间挡板": count_valid_items("DummyTubesParam", "CenterPt"),
#         "防冲板": 1 if isinstance(pipe_data.get("ImpingementPlate"), dict) else 0,
#         "浮动管板": 1,
#         "浮头法兰":1,
#         "浮头垫片": 1,
#         "球冠形封头": 1,
#         '铭牌板':1,
#         "铭牌支架":1,
#         "顶板":1,
#     }
#
#     for row in sheet.iter_rows(min_row=8):
#         name_cell = row[3]  # D列：元件名称
#         qty_cell = row[6]   # G列：数量
#
#         if not name_cell.value:
#             continue
#
#         item_name = str(name_cell.value).strip()
#         if item_name in quantity_map:
#             if qty_cell.value in [None, ""]:
#                 qty_cell.value = quantity_map[item_name]
#
#     print("✅ 已从布管输出参数中填写附加数量（修正字段匹配）")


