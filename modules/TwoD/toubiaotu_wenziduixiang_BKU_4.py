import datetime
import json
import logging
import math
import re
import shutil
import subprocess
import time
import traceback
from modules.TwoD.cad_context import CAD_CTX

import chardet
import configparser

import openpyxl
from pyautocad import Autocad
import pymysql

from modules.TwoD.TwoD_peizhi import get_project_save_dir, get_autocad_instance, _find_open_doc, wait_cad_idle, \
    refresh_doc, get_current_doc, open_drawing_with_wait, ensure_dwg_path, must_exist_file, safe_modify, \
    copy_template_to_target, modify_text_by_handle, get_mingpai_fushu,calc_nozzle_H, choose_save_dir
from modules.chanpinguanli.chanpinguanli_main import product_manager

import win32com.client
import os

from modules.wenbenshengcheng import cunguige
from modules.wenbenshengcheng.cunguige import get_value, load_json_data, add_template_sheet, fill_template_values, \
    copy_u_tube_value_live, copy_u_tube_value_openpyxl
from modules.wenbenshengcheng.generate_material_list import generate_material_list
from modules.TwoD.toubiaotu_mass_utils import calculate_7785f_from_excel_with_audit


def get_sheji_value(product_id):
    try:
        connection = pymysql.connect(
            host='localhost',
            user='root',
            password='123456',  # 请替换成你的数据库密码
            database='产品设计活动库',
            charset='utf8mb4'
        )
        with connection.cursor() as cursor:
            sql = """
                SELECT `设计`
                FROM `产品设计活动表`
                WHERE `产品ID` = %s
            """
            cursor.execute(sql, (product_id))
            row = cursor.fetchone()
            if row:
                return row[0]
            else:
                print(f"未找到 产品ID={product_id}")
                return None
    except Exception as e:
        print(f"产品设计活动数据库读取失败: {e}")
        return None
    finally:
        if 'connection' in locals():
            connection.close()
def get_jiaodui_value(product_id):
    try:
        connection = pymysql.connect(
            host='localhost',
            user='root',
            password='123456',  # 请替换成你的数据库密码
            database='产品设计活动库',
            charset='utf8mb4'
        )
        with connection.cursor() as cursor:
            sql = """
                SELECT `校对`
                FROM `产品设计活动表`
                WHERE `产品ID` = %s
            """
            cursor.execute(sql, (product_id))
            row = cursor.fetchone()
            if row:
                return row[0]
            else:
                print(f"未找到 产品ID={product_id}")
                return None
    except Exception as e:
        print(f"产品设计活动数据库读取失败: {e}")
        return None
    finally:
        if 'connection' in locals():
            connection.close()
def get_shenhe_value(product_id):
    try:
        connection = pymysql.connect(
            host='localhost',
            user='root',
            password='123456',  # 请替换成你的数据库密码
            database='产品设计活动库',
            charset='utf8mb4'
        )
        with connection.cursor() as cursor:
            sql = """
                SELECT `审核`
                FROM `产品设计活动表`
                WHERE `产品ID` = %s
            """
            cursor.execute(sql, (product_id))
            row = cursor.fetchone()
            if row:
                return row[0]
            else:
                print(f"未找到 产品ID={product_id}")
                return None
    except Exception as e:
        print(f"产品设计活动数据库读取失败: {e}")
        return None
    finally:
        if 'connection' in locals():
            connection.close()
def get_biaozhunhua_value(product_id):
    try:
        connection = pymysql.connect(
            host='localhost',
            user='root',
            password='123456',  # 请替换成你的数据库密码
            database='产品设计活动库',
            charset='utf8mb4'
        )
        with connection.cursor() as cursor:
            sql = """
                SELECT `标准化`
                FROM `产品设计活动表`
                WHERE `产品ID` = %s
            """
            cursor.execute(sql, (product_id))
            row = cursor.fetchone()
            if row:
                return row[0]
            else:
                print(f"未找到 产品ID={product_id}")
                return None
    except Exception as e:
        print(f"产品设计活动数据库读取失败: {e}")
        return None
    finally:
        if 'connection' in locals():
            connection.close()
def get_pizhun_value(product_id):
    try:
        connection = pymysql.connect(
            host='localhost',
            user='root',
            password='123456',  # 请替换成你的数据库密码
            database='产品设计活动库',
            charset='utf8mb4'
        )
        with connection.cursor() as cursor:
            sql = """
                SELECT `批准`
                FROM `产品设计活动表`
                WHERE `产品ID` = %s
            """
            cursor.execute(sql, (product_id))
            row = cursor.fetchone()
            if row:
                return row[0]
            else:
                print(f"未找到 产品ID={product_id}")
                return None
    except Exception as e:
        print(f"产品设计活动数据库读取失败: {e}")
        return None
    finally:
        if 'connection' in locals():
            connection.close()
def get_huiqian_value(product_id):
    try:
        connection = pymysql.connect(
            host='localhost',
            user='root',
            password='123456',  # 请替换成你的数据库密码
            database='产品设计活动库',
            charset='utf8mb4'
        )
        with connection.cursor() as cursor:
            sql = """
                SELECT `会签`
                FROM `产品设计活动表`
                WHERE `产品ID` = %s
            """
            cursor.execute(sql, (product_id))
            row = cursor.fetchone()
            if row:
                return row[0]
            else:
                print(f"未找到 产品ID={product_id}")
                return None
    except Exception as e:
        print(f"产品设计活动数据库读取失败: {e}")
        return None
    finally:
        if 'connection' in locals():
            connection.close()
def get_chanpin_value(product_id):
    try:
        connection = pymysql.connect(
            host='localhost',
            user='root',
            password='123456',  # 请替换成你的数据库密码
            database='产品需求库',
            charset='utf8mb4'
        )
        with connection.cursor() as cursor:
            sql = """
                SELECT `产品名称`,`产品型号`,`设备位号`,`图号前缀`,`产品编号`,`设计阶段`,`设计版次`
                FROM `产品需求表`
                WHERE `产品ID` = %s
            """
            cursor.execute(sql, (product_id))
            row = cursor.fetchone()
            if row:
                return row
            else:
                return None
    except Exception as e:
        print(f"数据库读取失败: {e}")
        return None
    finally:
        if 'connection' in locals():
            connection.close()


# 通用函数：从数据库读取规范/标准代号
def get_standard_value(product_id, standard_name):
    try:
        connection = pymysql.connect(
            host='localhost',
            user='root',
            password='123456',  # 请替换成你的数据库密码
            database='产品设计活动库',
            charset='utf8mb4'
        )
        with connection.cursor() as cursor:
            sql = """
                SELECT `规范/标准代号`
                FROM `产品设计活动表_产品标准数据表`
                WHERE `产品ID` = %s AND `规范/标准名称` = %s
            """
            cursor.execute(sql, (product_id, standard_name))
            row = cursor.fetchone()
            if row:
                return row[0]
            else:
                print(f"未找到 产品ID={product_id} 且 规范/标准名称={standard_name} 的记录。")
                return None
    except Exception as e:
        print(f"数据库读取失败: {e}")
        return None
    finally:
        if 'connection' in locals():
            connection.close()


def get_xingshi_value(product_id):
    try:
        connection = pymysql.connect(
            host='localhost',
            user='root',
            password='123456',  # 请替换成你的数据库密码
            database='产品设计活动库',
            charset='utf8mb4'
        )
        with connection.cursor() as cursor:
            sql = """
                SELECT `产品型式`
                FROM `产品设计活动表`
                WHERE `产品ID` = %s
            """
            cursor.execute(sql, (product_id))
            row = cursor.fetchone()
            if row:
                return row[0]
            else:
                print(f"未找到 产品ID={product_id}")
                return None
    except Exception as e:
        print(f"数据库读取失败: {e}")
        return None
    finally:
        if 'connection' in locals():
            connection.close()


def get_shejishuju_value(product_id, param_name):
    try:
        connection = pymysql.connect(
            host='localhost',
            user='root',
            password='123456',
            database='产品设计活动库',
            charset='utf8mb4'
        )
        with connection.cursor() as cursor:
            sql = """
                SELECT `壳程数值`,`管程数值`
                FROM `产品设计活动表_设计数据表`
                WHERE `产品ID` = %s AND `参数名称` = %s
            """
            cursor.execute(sql, (product_id, param_name))
            row = cursor.fetchone()
            if row:
                return str(row[0] or ""), str(row[1] or "")
            else:
                print(f"未找到 产品ID={product_id} 参数={param_name}")
                return "", ""
    except Exception as e:
        print(f"数据库读取失败: {e}")
        return "", ""
    finally:
        if 'connection' in locals():
            connection.close()


def get_wusunjiance_value(product_id):
    try:
        connection = pymysql.connect(
            host='localhost',
            user='root',
            password='123456',  # 请替换成你的数据库密码
            database='产品设计活动库',
            charset='utf8mb4'
        )
        with connection.cursor() as cursor:
            sql = """
                SELECT `接头种类`,`检测方法`,`壳程_技术等级`,`壳程_检测比例`,`壳程_合格级别`,`管程_技术等级`,`管程_检测比例`,`管程_合格级别`
                FROM `产品设计活动表_无损检测数据表`
                WHERE `产品ID` = %s
            """
            cursor.execute(sql, product_id)
            row = cursor.fetchall()
            if row:
                return row
            else:
                print(f"未找到 产品ID={product_id}")
                return None, None
    except Exception as e:
        print(f"数据库读取失败: {e}")
        return None, None
    finally:
        if 'connection' in locals():
            connection.close()


def get_tongyongshuju_value_danwei(product_id, param_name):
    try:
        connection = pymysql.connect(
            host='localhost',
            user='root',
            password='123456',  # 请替换成你的数据库密码
            database='产品设计活动库',
            charset='utf8mb4'
        )
        with connection.cursor() as cursor:
            sql = """
                SELECT `数值`,`参数单位`
                FROM `产品设计活动表_通用数据表`
                WHERE `产品ID` = %s AND `参数名称` = %s
            """
            cursor.execute(sql, (product_id, param_name))
            row = cursor.fetchone()
            if row:
                return str(row[0] or ""), str(row[1] or "")
            else:
                print(f"未找到 产品ID={product_id} 参数={param_name}")
                return "", ""
    except Exception as e:
        print(f"数据库读取失败: {e}")
        return "", ""
    finally:
        if 'connection' in locals():
            connection.close()


def get_tongyongshuju_value(product_id, param_name):
    try:
        connection = pymysql.connect(
            host='localhost',
            user='root',
            password='123456',  # 请替换成你的数据库密码
            database='产品设计活动库',
            charset='utf8mb4'
        )
        with connection.cursor() as cursor:
            sql = """
                SELECT `数值`
                FROM `产品设计活动表_通用数据表`
                WHERE `产品ID` = %s AND `参数名称` = %s
            """
            cursor.execute(sql, (product_id, param_name))
            row = cursor.fetchone()
            if row:
                return str(row[0] or "0"), str(row[1] or "0")
            else:
                print(f"未找到 产品ID={product_id} 参数={param_name}")
                return "0", "0"
    except Exception as e:
        print(f"数据库读取失败: {e}")
        return "", ""
    finally:
        if 'connection' in locals():
            connection.close()


def get_guanban_value(product_id):
    """
    返回：标准化后的管板连接方式（中文映射后的值）
    """
    # === 映射字典 ===
    mapping = {
        "机械胀接管孔结构": "机械胀接",
        "强度焊接的焊缝形式": "强度焊接",
        "机械强度胀接加密封焊管孔结构": "机械强度胀接+密封焊",
        "强度焊接加贴胀管孔结构": "强度焊接+贴胀",
        "内孔焊接头形式": "内孔焊",
    }

    try:
        connection = pymysql.connect(
            host='localhost',
            user='root',
            password='123456',
            database='产品设计活动库',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )

        with connection.cursor() as cursor:
            sql = """
                SELECT DISTINCT `管板连接方式`
                FROM `产品设计活动表_管板连接表`
                WHERE `产品ID` = %s
            """
            cursor.execute(sql, (product_id,))
            row = cursor.fetchone()

            if not row:
                print(f"未找到 产品ID={product_id} 的管板连接方式")
                return "None"

            raw_value = row["管板连接方式"]

            # === 映射处理 ===
            mapped_value = mapping.get(raw_value, raw_value)

            return mapped_value

    except Exception as e:
        print(f"数据库读取失败: {e}")
        return None

    finally:
        if 'connection' in locals():
            connection.close()


def twoDgeneration(product_id):
    try:
        db_config = {
            'host': 'localhost',
            'user': 'root',
            'password': '123456',
            'charset': 'utf8mb4',
            'cursorclass': pymysql.cursors.DictCursor
        }
        conn = pymysql.connect(database='产品设计活动库', **db_config)
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        acad = get_autocad_instance()
        if acad is None:
            print("❌ 没有可用的 AutoCAD 实例")
            raise RuntimeError("没有可用的 CAD 实例，本次总图生成已停止。")

        path1 = "BKU投标图"

        cursor.execute("""
           SELECT COUNT(*) AS cnt
           FROM 产品设计活动表_元件计算结果表
           WHERE 产品ID = %s AND 元件名称 = '大端壳体圆筒加强段'
        """, (product_id,))
        row = cursor.fetchone()
        count = int(row["cnt"]) if row and row.get("cnt") is not None else 0

        # === 根据是否存在端部壳体决定模板 ===
        if count > 0:
            template_path = os.path.abspath("BKU投标图-4-分段.dwg")
        else:
            template_path = os.path.abspath("BKU投标图-4.dwg")

        if not os.path.exists(template_path):
            print(f"❌ 模板文件不存在: {template_path}")
            raise FileNotFoundError(f"总图模板不存在：{template_path}")

        # === 这里继续你原来的逻辑 ===
        print(f"✅ 使用模板: {template_path}")

        # === 解析默认保存目录（项目需求表->项目保存路径） ===
        # === 解析默认保存目录（项目需求表->项目保存路径） ===
        save_dir_default = get_project_save_dir(product_id)

        # 默认目录不存在/为空 -> 回退 exports
        if not save_dir_default:
            save_dir_default = os.path.join(os.getcwd(), "exports")
        save_dir_default = os.path.abspath(save_dir_default)

        os.makedirs(save_dir_default, exist_ok=True)

        # ✅ 让用户可选保存目录（取消则用默认目录）
        save_dir = choose_save_dir(save_dir_default)
        os.makedirs(save_dir, exist_ok=True)

        print(f"📁 保存目录：{save_dir}（默认：{save_dir_default}）")

        # === 关键修复 1：模板 → 唯一目标副本 ===
        target_dwg = copy_template_to_target(template_path, save_dir, path1)

        # === 关键修复 2：关闭 AutoCAD 的“未命名临时图纸” ===
        try:
            docs_to_close = []
            for i in range(acad.Documents.Count):
                doc_i = acad.Documents.Item(i)
                name = (doc_i.Name or "").lower()
                full = (doc_i.FullName or "").strip()
                # Drawing1 / Drawing2 / 无 FullName 的
                if name.startswith("drawing") and (not full):
                    docs_to_close.append(doc_i)
            for d in docs_to_close:
                try:
                    d.Close(False)
                except Exception:
                    pass
        except Exception:
            pass

        # === 关键修复 3：等待 AutoCAD 空闲，再打开目标文件 ===
        if not wait_cad_idle(acad, timeout=20):
            raise RuntimeError("CAD 未进入空闲状态，本次总图生成已停止，请结束 CAD 命令或关闭弹窗。")
        acad, doc = open_drawing_with_wait(target_dwg)
        if doc is None:
            print("❌ 打开目标图失败:", target_dwg)
            raise RuntimeError(f"打开总图失败：{target_dwg}")
        CAD_CTX["product_id"] = product_id
        CAD_CTX["save_dir"] = save_dir

        # 你得到 target_dwg 后：
        CAD_CTX["target_dwg"] = target_dwg

        # 你 open_drawing 得到 doc 后：
        CAD_CTX["doc"] = doc


        # === 关键修复 4：打开后再等一次空闲 + 刷新视图 ===
        if not wait_cad_idle(acad, timeout=30):
            raise RuntimeError("CAD 未进入空闲状态，本次总图生成已停止，请结束 CAD 命令或关闭弹窗。")
        refresh_doc(doc)
        print(f"✅ 成功打开唯一副本: {target_dwg}")


        # def extract_text(doc, retries=10, delay=1):
        #     print("【文字对象】提取中...")
        #     for attempt in range(retries):
        #         try:
        #          #             for obj in doc.ModelSpace:
        #                 if obj.ObjectName in ['AcDbText', 'AcDbMText']:
        #                     print(
        #                         f"{obj.ObjectName}: '{obj.TextString}' "
        #                         f"位置: {obj.InsertionPoint} "
        #                         f"图层: {obj.Layer} "
        #                         f"Handle: {obj.Handle}"
        #                     )
        #                     count += 1
        #             print(f"✅ 成功提取文字对象，共 {count} 条")
        #             return
        #         except Exception as e:
        #             print(f"⚠️ 第 {attempt + 1} 次尝试失败: {e}（剩余 {retries - attempt - 1} 次）")
        #             time.sleep(delay)
        #
        #     print("❌ 超过最大尝试次数，无法访问 ModelSpace")
        # 通用函数：修改文字对象

        # 初始化 AutoCAD
        # extract_text(doc)
        regulation_text = None
        standard_text = None
        # 处理产品法规 → 替换到 handle 77872
        regulation_text = get_standard_value(product_id, "技术法规")
        safe_modify(doc,"77872", regulation_text)

        # 处理产品标准 → 替换到 handle 778CC
        standard_text = get_standard_value(product_id, "产品标准")
        if standard_text:
            safe_modify(doc,"778CC", standard_text)
        # 处理产品型式
        standard_text = get_xingshi_value(product_id)
        if standard_text:
            safe_modify(doc,"77849", standard_text)
        def ceil_two_decimals(value):
            return math.ceil(float(value) * 100) / 100
        # 77861 设备操作重量
        db_config = {
            'host': 'localhost',
            'user': 'root',
            'password': '123456',
            'charset': 'utf8mb4',
            'cursorclass': pymysql.cursors.DictCursor
        }
        conn2 = pymysql.connect(database='产品设计活动库', **db_config)
        # 壳体圆筒
        cursor2 = conn2.cursor(pymysql.cursors.DictCursor)
        cursor2.execute("""
            SELECT `Value` 
            FROM 产品设计活动表_元件计算结果表 
            WHERE `产品ID` = %s 
              AND `元件名称` = '大端壳体圆筒' 
              AND `Name` = '圆筒压力试验压力'
        """, (product_id,))
        row = cursor2.fetchone()
        qiao_shiyanyali = ceil_two_decimals(row["Value"])

        # 管箱圆筒
        cursor3 = conn2.cursor(pymysql.cursors.DictCursor)
        cursor3.execute("""
            SELECT `Value` 
            FROM 产品设计活动表_元件计算结果表 
            WHERE `产品ID` = %s 
              AND `元件名称` = '管箱圆筒' 
              AND `Name` = '圆筒压力试验压力'
        """, (product_id,))
        row = cursor3.fetchone()
        guan_shiyanyali = ceil_two_decimals(row["Value"])

        # 替换图纸文字
        safe_modify(doc, "7786D", f"{qiao_shiyanyali:.2f}/-")
        safe_modify(doc, "77857", f"{guan_shiyanyali:.2f}/-")



        cursor2.close()
        conn2.close()
        # 获取壳程数值、管程数值
        qiao_value, guan_value = get_shejishuju_value(product_id, "介质（组分）")
        safe_modify(doc,"77874", str(qiao_value))
        safe_modify(doc,"77875", str(guan_value))
        qiao_value, guan_value = get_shejishuju_value(product_id, "介质特性（毒性危害程度）")
        safe_modify(doc,"77876", str(qiao_value))
        safe_modify(doc,"77877", str(guan_value))
        qiao_value, guan_value = get_shejishuju_value(product_id, "工作压力")
        safe_modify(doc,"80B4D", str(qiao_value))
        safe_modify(doc,"80B55", str(guan_value))
        qiao_value, guan_value = get_shejishuju_value(product_id, "设计压力*")
        safe_modify(doc,"77864", str(qiao_value))
        safe_modify(doc,"7784E", str(guan_value))
        qiao_value, guan_value = get_shejishuju_value(product_id, "最高允许工作压力")
        safe_modify(doc,"77880", str(qiao_value))
        safe_modify(doc,"7787F", str(guan_value))
        # 77865 管板设计压差（壳程）
        # 7784F 管板设计压差（管程）
        qiao_value, guan_value = get_shejishuju_value(product_id, "管板设计压差")
        safe_modify(doc,"80B5E", str(qiao_value))
        safe_modify(doc,"80B66", str(guan_value))
        qiao_value, guan_value = get_shejishuju_value(product_id, "最低设计温度")
        safe_modify(doc, "77869", str(qiao_value))
        safe_modify(doc, "77853", str(guan_value))
        ru_qiao_value, ru_guan_value = get_shejishuju_value(product_id, "工作温度（入口）")
        chu_qiao_value, chu_guan_value = get_shejishuju_value(product_id, "工作温度（出口）")
        qiao_value = ru_qiao_value + "/" + chu_qiao_value
        guan_value = ru_guan_value + "/" + chu_guan_value
        safe_modify(doc,"77866", str(qiao_value))
        safe_modify(doc,"77850", str(guan_value))

        qiao_value, guan_value = get_shejishuju_value(product_id, "设计温度（最高）*")
        safe_modify(doc,"77867", str(qiao_value))
        safe_modify(doc,"77851", str(guan_value))

        qiao_value, guan_value = get_shejishuju_value(product_id, "腐蚀裕量*")
        safe_modify(doc,"7786B", str(qiao_value))
        safe_modify(doc,"77855", str(guan_value))
        qiao_value, guan_value = get_shejishuju_value(product_id, "焊接接头系数*")
        safe_modify(doc,"7786C", str(qiao_value))
        safe_modify(doc,"77C8C", str(guan_value))
        value, unit = get_tongyongshuju_value_danwei(product_id, "设计使用年限*")
        tongyongData = value + unit
        safe_modify(doc,"77856", str(tongyongData))
        qiao_value, guan_value = get_shejishuju_value(product_id, "超压泄放装置")
        safe_modify(doc,"77878", str(qiao_value))
        safe_modify(doc,"77879", str(guan_value))
        safe_modify(doc,"7784b", "/")
        safe_modify(doc,"7784c", "/")

        qiao_value, guan_value = get_shejishuju_value(product_id, "泄漏试验类型")
        safe_modify(doc,"77885", str(qiao_value))
        safe_modify(doc,"77881", str(guan_value))
        qiao_value, guan_value = get_shejishuju_value(product_id, "耐压试验介质")
        safe_modify(doc,"7786e", str(qiao_value))
        safe_modify(doc,"77858", str(guan_value))

        qiao_value, guan_value = get_shejishuju_value(product_id, "绝热类型")
        if qiao_value == "保温":
            modify_text_by_handle(doc, "83c20", "√")
            modify_text_by_handle(doc, "83c28", " ")
        elif qiao_value == "保冷":
            modify_text_by_handle(doc, "83c20", " ")
            modify_text_by_handle(doc, "83c28", "√")
        else:
            modify_text_by_handle(doc, "83c20", " ")
            modify_text_by_handle(doc, "83c28", " ")
        qiao_value, guan_value = get_shejishuju_value(product_id, "绝热材料")
        safe_modify(doc,"7788A", str(qiao_value))
        safe_modify(doc,"77889", str(guan_value))
        qiao_value, guan_value = get_shejishuju_value(product_id, "绝热材料厚度")
        safe_modify(doc,"77887", str(qiao_value))
        safe_modify(doc,"77883", str(guan_value))
        qiao_value, guan_value = get_shejishuju_value(product_id, "绝热材料厚度")
        safe_modify(doc,"77887", str(qiao_value))
        safe_modify(doc,"77883", str(guan_value))
        value, unit = get_tongyongshuju_value_danwei(product_id, "地震设防烈度")
        safe_modify(doc,"77899", str(value))
        value, unit = get_tongyongshuju_value_danwei(product_id, "地震加速度")
        safe_modify(doc,"7789A", str(value))
        value, unit = get_tongyongshuju_value_danwei(product_id, "地震分组")
        safe_modify(doc,"7789B", str(value))
        value, unit = get_tongyongshuju_value_danwei(product_id, "场地土地类别")
        tongyongData = value
        safe_modify(doc,"77859", str(tongyongData))
        value, unit = get_tongyongshuju_value_danwei(product_id, "雪压值")
        safe_modify(doc,"7785A", str(value))
        # 77853  77C8C 最低设计金属温度（管程）（壳程）
        # 77850 工作温度（管程）
        # 77868 金属平均温度（壳程）
        # 77869 最低设计金属温度（壳程）
        # 77885 实验类型（壳程）
        # 7788C（换热管预管板焊接接头）射线
        # 77841 77842 硬度实验：标准，合格指标
        # 77843 钢板超声检测率
        # 77873 用户设计规范
        regulation_text = get_standard_value(product_id, "用户设计规范")
        modify_text_by_handle(doc,"77873", regulation_text)

        def clean(v):
            if v is None:
                return ""
            v = str(v).strip()
            return "" if v.lower() == "none" else v

        def get_param_value(cur, product_id, comp_name, param_name):
            cur.execute(
                """
                SELECT 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = %s AND 参数名称 = %s
                LIMIT 1
                """,
                (product_id, comp_name, param_name)
            )
            row = cur.fetchone()
            if not row:
                return ""
            val = row["参数值"] if isinstance(row, dict) else row[0]
            return clean(val)

        def get_triplet(cur, product_id, comp_name):
            """返回 (材料牌号, 供货状态, 材料标准)"""
            paihao = get_param_value(cur, product_id, comp_name, "材料牌号")
            gonghuo = get_param_value(cur, product_id, comp_name, "供货状态")
            biaozhun = get_param_value(cur, product_id, comp_name, "材料标准")
            return (paihao, gonghuo, biaozhun)

        def resolve_material_triplet(cur, product_id, cyl_name, head_name):
            """
            根据 cyl_name 的 材料类型 决定取圆筒还是取封头三项：
            - 钢板：取圆筒
            - 锻件：取封头
            - 其它/为空：默认取圆筒（取不到就是空）
            """
            mat_type = get_param_value(cur, product_id, cyl_name, "材料类型")
            target = head_name if mat_type == "锻件" else cyl_name
            return get_triplet(cur, product_id, target)

        def build_regulation_text(product_id,
                                  host="localhost", user="root", password="123456",
                                  db="产品设计活动库"):
            conn = pymysql.connect(
                host=host, user=user, password=password,
                database=db, charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            try:
                cur = conn.cursor()

                # 管箱圆筒：优先前端管箱圆筒，缺失则回退管箱圆筒
                tube_cyl = "前端管箱圆筒"
                if not get_param_value(cur, product_id, tube_cyl, "材料类型"):
                    tube_cyl = "管箱圆筒"

                shell_cyl = "大端壳体圆筒"

                # 取两边最终三元组（按钢板/锻件规则）
                t1 = resolve_material_triplet(cur, product_id, tube_cyl, "管箱封头")
                t2 = resolve_material_triplet(cur, product_id, shell_cyl, "壳体封头")

                # 拼接规则：不加名称；相同则合并；不同则直接连在一起
                if t1 == t2:
                    # 材料牌号/供货状态/材料标准
                    return "/".join([x for x in t1 if x != ""])
                else:
                    # 材料牌号1/供货状态1/材料标准1/材料牌号2/供货状态2/材料标准2
                    return "/".join([x for x in (t1 + t2) if x != ""])

            finally:
                try:
                    conn.close()
                except:
                    pass

        # ===== 生成并写入文档 =====
        regulation_text = build_regulation_text(product_id)
        modify_text_by_handle(doc,"7787a", regulation_text)

        def _norm_str(v):
            if v is None:
                return ""
            v = str(v).strip()
            return "" if v.lower() == "none" else v

        def fetch_attach_param(cur, product_id, part_name, param_name):
            """
            从 产品设计活动表_元件附加参数表 取某元件某参数的 参数值
            """
            cur.execute(
                """
                SELECT 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = %s AND 参数名称 = %s
                LIMIT 1
                """,
                (product_id, part_name, param_name)
            )
            row = cur.fetchone()
            if not row:
                return ""
            val = row["参数值"] if isinstance(row, dict) else row[0]
            return _norm_str(val)

        def fetch_material_triplet(cur, product_id, part_name):
            """
            返回 (材料牌号, 供货状态, 材料标准)
            """
            grade = fetch_attach_param(cur, product_id, part_name, "材料牌号")
            supply = fetch_attach_param(cur, product_id, part_name, "供货状态")
            std = fetch_attach_param(cur, product_id, part_name, "材料标准")
            return (grade, supply, std)

        def format_material_triplet(tri):
            """
            输出：材料牌号/供货状态/材料标准（空值自动跳过）
            """
            return "/".join([x for x in tri if x])

        def build_fixed_tubesheet_material_string(product_id,
                                                  host="localhost", user="root", password="123456",
                                                  db="产品设计活动库"):
            """
            固定管板材料字符串生成规则：
            - 固定管板 材料类型=锻件：取 固定管板 的 材料牌号/供货状态/材料标准
            - 固定管板 材料类型=钢板：优先取 管箱法兰 的三项；若结果为空，取 壳体法兰 的三项
            """
            conn = pymysql.connect(
                host=host, user=user, password=password,
                database=db, charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            try:
                cur = conn.cursor()

                mat_type = fetch_attach_param(cur, product_id, "固定管板", "材料类型")

                if mat_type == "钢锻件":                    return format_material_triplet(fetch_material_triplet(cur, product_id, "固定管板"))

                if mat_type == "钢板":
                    tube_flange = format_material_triplet(fetch_material_triplet(cur, product_id, "管箱法兰"))
                    if tube_flange:
                        return tube_flange
                    return format_material_triplet(fetch_material_triplet(cur, product_id, "壳体法兰"))

                # 兜底：按钢板策略
                tube_flange = format_material_triplet(fetch_material_triplet(cur, product_id, "管箱法兰"))
                if tube_flange:
                    return tube_flange
                return format_material_triplet(fetch_material_triplet(cur, product_id, "壳体法兰"))

            finally:
                try:
                    conn.close()
                except:
                    pass

        # 用法：
        fixed_tubesheet_text = build_fixed_tubesheet_material_string(product_id)
        modify_text_by_handle(doc,"778c7", fixed_tubesheet_text)
        regulation_text1 = get_standard_value(product_id, "焊接工艺评定")
        regulation_text2 = get_standard_value(product_id, "焊接规程")
        regulation_text = regulation_text1 + '、' + regulation_text2
        safe_modify(doc,"77846", regulation_text)
        regulation_text = get_standard_value(product_id, "焊接接头型式标准")
        safe_modify(doc,"77847", regulation_text)
        regulation_text = get_standard_value(product_id, "焊接材料推荐标准")
        safe_modify(doc,"77848", regulation_text)
        regulation_text = get_guanban_value(product_id)
        safe_modify(doc,"7785B", regulation_text)
        # jietouzhonglei,jiancefangfa,kechengJishudengji,kechengJiancebili,kechengHegejibie,guanchengJishudengji,guanchengJiancebili,guanchengHegejibie = get_wusunjiance_value(product_id)
        items = get_wusunjiance_value(product_id)
        for item in items:
            if item[0] == 'A，B':
                if item[1] == "R.T.":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}%/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}%/{item[7]}"
                    safe_modify(doc, "7786F", str(kecheng_value))
                    safe_modify(doc, "7787B", str(guancheng_value))
                elif item[1] == "U.T.":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}%/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}%/{item[7]}"
                    safe_modify(doc, "77896", str(kecheng_value))
                    safe_modify(doc, "77897", str(guancheng_value))
                elif item[1] == "TOFD":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}%/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}%/{item[7]}"
                    safe_modify(doc, "77895", str(kecheng_value))
                    safe_modify(doc, "77898", str(guancheng_value))
                elif item[1] == "M.T.":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}%/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}%/{item[7]}"
                    safe_modify(doc, "778CD", str(kecheng_value))
                    safe_modify(doc, "778CE", str(guancheng_value))
                elif item[1] == "P.T.":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}%/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}%/{item[7]}"
                    safe_modify(doc, "7788D", str(kecheng_value))
                    safe_modify(doc, "7788E", str(guancheng_value))

            elif item[0] == "D":
                if item[1] == "U.T.":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}%/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}%/{item[7]}"
                    safe_modify(doc, "7788F", str(kecheng_value))
                    safe_modify(doc, "77890", str(guancheng_value))
                elif item[1] == "M.T.":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}%/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}%/{item[7]}"
                    safe_modify(doc, "77891", str(kecheng_value))
                    safe_modify(doc, "77892", str(guancheng_value))
                elif item[1] == "P.T.":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}%/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}%/{item[7]}"
                    safe_modify(doc, "7F358", str(kecheng_value))
                    safe_modify(doc, "77894", str(guancheng_value))

            elif item[0] == "C，E":
                if item[1] == "M.T.[FB]":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}%/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}%/{item[7]}"
                    safe_modify(doc, "7F360", str(kecheng_value))
                    safe_modify(doc, "7F368", str(guancheng_value))
                elif item[1] == "P.T.":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}%/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}%/{item[7]}"
                    safe_modify(doc, "7F370", str(kecheng_value))
                    safe_modify(doc, "7F378", str(guancheng_value))

            elif item[0] == "T（管头）":
                if item[1] == "R.T.":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}%/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}%/{item[7]}"

                    safe_modify(doc, "7F380", str(kecheng_value))
                    if str(kecheng_value) == '///%//':
                        safe_modify(doc, "7F380", '/')
                elif item[1] == "P.T.":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}%/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}%/{item[7]}"

                    safe_modify(doc, "7F388", str(kecheng_value))
                    if str(kecheng_value) == '///%//':
                        safe_modify(doc, "7F388", '/')
        # √
        value, unit = get_tongyongshuju_value_danwei(product_id, "焊后热处理")
        heat_treatment_value = str(value or "")
        modify_text_by_handle(doc, "7EDAC", '√' if '壳程' in heat_treatment_value else '')
        modify_text_by_handle(doc, "7787E", '√' if '管程' in heat_treatment_value else '')
        value, unit = get_tongyongshuju_value_danwei(product_id, "硬度试验标准")
        safe_modify(doc,"77841", value)
        value, unit = get_tongyongshuju_value_danwei(product_id, "硬度试验合格指标")
        safe_modify(doc,"80CDD", value)
        value, unit = get_tongyongshuju_value_danwei(product_id, "管束防腐要求")
        if value == '管内':
            modify_text_by_handle(doc,"7EBAD", '√')
            modify_text_by_handle(doc,"7EBB5", '')
            modify_text_by_handle(doc,"7EDA4", '√')
            modify_text_by_handle(doc,"7ED9C", '')
        elif value == '管外':
            modify_text_by_handle(doc,"7EBB5", '√')
            modify_text_by_handle(doc,"7EBAD", '')
            modify_text_by_handle(doc,"7ED9C", '√')
            modify_text_by_handle(doc,"7EDA4", '')
        else:
            modify_text_by_handle(doc,"7EBB5", '')
            modify_text_by_handle(doc,"7EBAD", '')
            modify_text_by_handle(doc,"7ED9C", '')
            modify_text_by_handle(doc,"7EDA4", '')
        value1, unit = get_tongyongshuju_value_danwei(product_id, "表面处理位置")
        value2, unit = get_tongyongshuju_value_danwei(product_id, "表面处理标准")
        value3, unit = get_tongyongshuju_value_danwei(product_id, "表面处理合格级别")
        value = value1 + '/' + value2 + '/' + value3
        safe_modify(doc,"7787C", value)
        regulation_text = get_standard_value(product_id, "运输包装标准")
        if regulation_text:
            safe_modify(doc,"77840", regulation_text)
        value, unit = get_tongyongshuju_value_danwei(product_id, "地面粗糙度")
        safe_modify(doc,"7785D", value)
        value, unit = get_tongyongshuju_value_danwei(product_id, "基本风压")
        safe_modify(doc,"7785E", value)
        regulation_text = get_standard_value(product_id, "涂漆标准")
        safe_modify(doc, "83eff", regulation_text)
        # 77861 设备操作重量
        # 签名
        standard_text = get_sheji_value(product_id)
        if standard_text:
            modify_text_by_handle(doc,"83ddb", standard_text)
        standard_text = get_jiaodui_value(product_id)
        if standard_text:
            modify_text_by_handle(doc,"83de3", standard_text)
        standard_text = get_shenhe_value(product_id)
        if standard_text:
            modify_text_by_handle(doc,"83deb", standard_text)
        standard_text = get_biaozhunhua_value(product_id)
        if standard_text:
            modify_text_by_handle(doc,"83df3", standard_text)
        standard_text = get_pizhun_value(product_id)
        if standard_text:
            modify_text_by_handle(doc,"83dfb", standard_text)
        standard_text = get_huiqian_value(product_id)
        if standard_text:
            modify_text_by_handle(doc,"83e03", standard_text)
        db_config = {
            'host': 'localhost',
            'user': 'root',
            'password': '123456',
            'charset': 'utf8mb4',
            'cursorclass': pymysql.cursors.DictCursor
        }
        conn1 = pymysql.connect(database='产品设计活动库', **db_config)
        cursor1 = conn1.cursor()
        cursor1.execute("SELECT `项目ID` FROM 产品设计活动表 WHERE `产品ID` = %s", (product_id,))
        row = cursor1.fetchone()
        cursor1.close()
        conn1.close()

        if not row:
            raise ValueError("未找到对应的项目ID")

        xiangmu_id = row['项目ID']  # 直接提取一个值

        # 连接项目需求库
        conn2 = pymysql.connect(database='项目需求库', **db_config)
        cursor2 = conn2.cursor()
        cursor2.execute("""
            SELECT 项目名称, 业主名称, 项目编号, 工程总包方
            FROM 项目需求表
            WHERE 项目ID = %s
        """, (xiangmu_id,))
        row = cursor2.fetchone()
        cursor2.close()
        conn2.close()

        if not row:
            raise ValueError("未找到对应的项目需求信息")

        # 直接使用 row 中的数据
        safe_modify(doc,"7E778", row['项目名称'])
        safe_modify(doc,"7E780", row['业主名称'])
        safe_modify(doc,"7E7C9", row['项目编号'])
        safe_modify(doc,"7E790", row['工程总包方'])
        safe_modify(doc,"7E788", '/') #业主项目号

        row = get_chanpin_value(product_id)
        safe_modify(doc,"7E799", row[0])
        safe_modify(doc,"7E7A1", row[1])
        safe_modify(doc,"7E7A9", row[2])
        safe_modify(doc,"7E7B1", row[3])
        safe_modify(doc,"7E7D1", row[4])
        safe_modify(doc,"7E7D9", row[5])
        safe_modify(doc,"7E7F1", row[6])
        safe_modify(doc,"7E7C1", 'TS1210A41-2028') #设计证书号
        safe_modify(doc,"7E7E1", '/') #产品识别码
        print(row)
        connection = pymysql.connect(
            host='localhost',
            user='root',
            password='123456',
            database='产品设计活动库',
            charset='utf8mb4'
        )

        # ❗ 不使用 with，这样 cursor 不会自动关闭
        cursor = connection.cursor(pymysql.cursors.DictCursor)
        # 按管口功能识别管口，管口代号可能变化，不能作为匹配条件或映射键。
        cursor.execute("""
            SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s
              AND 管口功能 IN (
                  '管程入口', '管程出口', '壳程入口', '壳程液相出口',
                  '壳程气相出口', '壳程液位计1', '壳程液位计2', '壳程温度计'
              )
        """, (product_id,))
        ports = cursor.fetchall()
        port_by_function = {
            str(row.get("管口功能", "")).strip(): row
            for row in ports
            if row.get("管口功能")
        }

        def get_port_value(function_name, field_name):
            value = port_by_function.get(function_name, {}).get(field_name)
            return "" if value is None else str(value).strip()

        # 功能顺序对应原来的 N1、N2、N3、N4、N5、L1、L2、T1 槽位。
        port_functions = (
            "管程入口", "管程出口", "壳程入口", "壳程液相出口",
            "壳程气相出口", "壳程液位计1", "壳程液位计2", "壳程温度计",
        )

        # 管口编号（实际管口代号）按管口功能写入，handle 对应图纸中的编号栏。
        for function_name, handle in (
                ("管程入口", "7789d"),
                ("管程出口", "7789f"),
                ("壳程入口", "778a1"),
                ("壳程气相出口", "83fd8"),
                ("壳程液相出口", "84028"),
                ("壳程液位计1", "8402a"),
                ("壳程液位计2", "8402c"),
                ("壳程温度计", "8402e"),
        ):
            safe_modify(doc, handle, get_port_value(function_name, "管口代号"))

        for function_name, handle in zip(
                port_functions,
                ["778A9", "778AA", "778AB", "83fdb", "84034", "84035", "84052", "84053"]):
            safe_modify(doc, handle, get_port_value(function_name, "公称尺寸"))

        for function_name, handle in zip(
                port_functions,
                ["778AD", "778C3", "778C4", "83fdf", "84036", "84046", "84047", "84048"]):
            safe_modify(doc, handle, get_port_value(function_name, "压力等级"))

        for function_name, handle in zip(
                port_functions,
                ["778AE", "778B4", "83fdc", "778BE", "84037", "778B4", "8403c", "84043"]):
            flange_type = get_port_value(function_name, "法兰型式")
            sealing_face_type = get_port_value(function_name, "密封面型式")
            text = f"{flange_type}/{sealing_face_type}" if flange_type and sealing_face_type else ""
            safe_modify(doc, handle, text)

        def build_out_length_map(product_id):
            """
            构建管口外伸高度映射 {管口名称: 外伸高度}
            包含：管程入口、管程出口、壳程入口、壳程气相出口、排气口、排液口
            """
            conn_product = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            cur = conn_product.cursor()

            # === 1. 获取开孔元件外径 ===
            cur.execute("""
                SELECT 元件名称, value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 IN ('管程入口接管','管程出口接管','壳程入口接管','壳程气相出口接管','壳程温度计接管','壳程液位计2接管','壳程液位计1接管','壳程液相出口接管')
                  AND Name = '接管总外伸高度'
            """, (product_id,))
            waijing_map = {row["元件名称"]: float(row["value"]) for row in cur.fetchall() if row.get("value")}

            # === 计算最终外伸高度 ===
            result = {}
            for port in ['管程入口接管','管程出口接管','壳程入口接管','壳程气相出口接管','壳程温度计接管','壳程液位计2接管','壳程液位计1接管','壳程液相出口接管']:
                try:
                    result[port] = str(
                        waijing_map.get(port, 0)
                    )
                except Exception:
                    result[port] = ""

            return result
        # === 获取所有管口外伸高度 ===
        out_len_map = build_out_length_map(product_id)

        # === 映射到 handle ===
        port_handle_map = {
            "管程入口接管": "778B0",
            "管程出口接管": "778C9",
            "壳程入口接管": "778CA",
            "壳程气相出口接管": "83fe0",

            "壳程液相出口接管": "84039",
            "壳程液位计1接管": "84049",
            "壳程液位计2接管": "8404a",
            "壳程温度计接管": "8404b",
        }

        for port, handle in port_handle_map.items():
            safe_modify(doc, handle, out_len_map.get(port, ""))
        # handle → 接管组件名 映射
        handle_map = {
            "7E6CD": "管程出口接管",
            "83fe2": "壳程气相出口接管",
            "778BA": "壳程入口接管",
            "778AF": "管程入口接管",

            "84038": "壳程液相出口接管",
            "84050": "壳程液位计1接管",
            "84040": "壳程液位计2接管",
            "84051": "壳程温度计接管",


        }
        json_path = "jisuan_output_new.json"  # 替换为实际路径
        jisuan_data = load_json_data(json_path)
        for handle, component_name in handle_map.items():
            if component_name in {"管程入口接管", "管程出口接管", "壳程入口接管", "壳程气相出口接管", "壳程液相出口接管", "壳程液位计1接管", "壳程液位计2接管", "壳程温度计接管"}:
                od = get_value(jisuan_data, component_name, "接管大端外径")
                thick = get_value(jisuan_data, component_name, "接管大端壁厚")
                l1 = get_value(jisuan_data, component_name, "接管实际外伸长度") or 0
                l2 = get_value(jisuan_data, component_name, "接管实际内伸长度") or 0

                try:
                    if None not in (od, thick):
                        od = float(od)
                        thick = float(thick)

                        # ✅ 新：L 用数据库公式算 H，并保留两位小数
                        H = float(calc_nozzle_H(product_id, component_name))

                        value = f"∅{od}×{thick};L={H:.2f}"
                        safe_modify(doc, handle, value)

                except Exception as e:
                    print(f"❌ 处理 {component_name} 时出错: {e}")
        # handle → 模块名映射（用于读取 JSON）
        handle_to_module = {
            "778B2": "管程入口接管",
            "778B7": "管程出口接管",
            "778BC": "壳程入口接管",
            "83fde": "壳程气相出口接管",

            "8403b": "壳程液相出口接管",
            "8403e": "壳程液位计1接管",
            "84042": "壳程液位计2接管",
            "84045": "壳程温度计接管",
        }

        # 🔍 读取焊端规格（焊端壁厚）
        dict_out_data = jisuan_data.get("DictOutDatas", {})
        handuan_spec_map = {}

        for handle, module_name in handle_to_module.items():
            module = dict_out_data.get(module_name, {})
            datas = module.get("Datas", [])

            for item in datas:
                if item.get("Name", "").strip() == "接管与管法兰或外部连接端壁厚（焊端规格）":
                    value = item.get("Value", "").strip()
                    handuan_spec_map[handle] = value
                    break

        for handle in handle_to_module:
            s = handuan_spec_map.get(handle, "")
            text = f"{s}" if s else ""
            safe_modify(doc, handle, text)

        # 法兰标准同样按管口功能写入。
        for function_name, handle in zip(
                port_functions,
                ["7E6A1", "7E6A2", "7E6A3", "83fe1", "8404c", "8404d", "8404e", "8404f"]):
            flange_standard = get_port_value(function_name, "法兰标准")
            if flange_standard:
                safe_modify(doc, handle, flange_standard)
                print(f"✅ 写入 {handle} → {flange_standard}")
            else:
                print(f"⚠️ 跳过 {function_name}，无法兰标准")

        handle_map = {
            "778B1": "管程入口接管",
            "778B6": "管程出口接管",
            "778BB": "壳程入口接管",
            "83fdd": "壳程气相出口接管",

            "8403a": "壳程液相出口接管",
            "8403d": "壳程液位计1接管",
            "84041": "壳程液位计2接管",
            "84044": "壳程温度计接管",
        }

        # === 预读取附加参数表（供货状态用） ===
        cursor.execute("""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_管口附加参数表
                WHERE 产品ID = %s
            """, (product_id,))
        extra_params = {row["参数名称"]: row["参数值"] for row in cursor.fetchall()}

        # === 遍历 handle_map ===
        for handle, guankou_daihao in handle_map.items():
            module = dict_out_data.get(guankou_daihao, {})
            datas = module.get("Datas", [])

            mat_type, mat_grade, mass = "", "", ""
            for item in datas:
                name = item.get("Name", "").strip()
                if name == "接管材料类型":
                    mat_type = item.get("Value", "").strip()
                elif name == "接管材料牌号":
                    mat_grade = item.get("Value", "").strip()
                elif name == "接管重量":
                    mass = item.get("Value", "").strip()

            # 匹配供货状态 & 接管法兰材料类型
            supply_status = ""
            flange_mat_type = mat_type  # 默认还是接管材料类型
            for i in range(1, 4):
                t_key, g_key = f"接管材料类型{i}", f"接管材料牌号{i}"
                s_key, f_key = f"接管供货状态{i}", f"接管法兰材料类型{i}"

                if extra_params.get(t_key) == mat_type and extra_params.get(g_key) == mat_grade:
                    supply_status = extra_params.get(s_key, "")
                    flange_mat_type = extra_params.get(f_key, mat_type)  # 优先取法兰材料类型
                    break

            # 拼接最终文本 —— 用法兰材料类型替代接管材料类型
            text = f"{flange_mat_type}"

            # ⚡ 写入 Word 指定 handle
            safe_modify(doc, handle, text)
            print(f"✅ 写入 handle {handle} ({guankou_daihao}): {text}")

        safe_modify(doc, "77816", "管箱平盖")
        # 🔍 获取接管材料信息
        # 从 JSON(dict_out) 获取接管信息
        def _clean(v):
            return (v or "").strip()

        def build_inlet_nozzle_material_text(dict_out_data, extra_params, module_name):
            """
            复刻你给的逻辑：
            1) 从 dict_out_data[module_name]["Datas"] 里取：
               - 接管材料类型 -> mat_type
               - 接管材料牌号 -> mat_grade
               - 材料标准     -> mat_std
            2) 用 extra_params 匹配供货状态（按 1~3 组）
            3) 返回 text = 牌号/供货状态/标准
            """
            module = dict_out_data.get(module_name, {}) or {}
            datas = module.get("Datas", []) or []

            mat_type, mat_grade, mat_std = "", "", ""
            for item in datas:
                name = _clean(item.get("Name", ""))
                val = _clean(item.get("Value", ""))
                if name == "接管材料类型":
                    mat_type = val
                elif name == "接管材料牌号":
                    mat_grade = val
                elif name == "材料标准":
                    mat_std = val

            # 匹配供货状态
            supply_status = ""
            for i in range(1, 4):
                t_key, g_key, s_key = f"接管材料类型{i}", f"接管材料牌号{i}", f"接管供货状态{i}"
                if _clean(extra_params.get(t_key)) == mat_type and _clean(extra_params.get(g_key)) == mat_grade:
                    supply_status = _clean(extra_params.get(s_key, ""))
                    break

            return f"{mat_grade}/{supply_status}/{mat_std}"

        def write_inlet_nozzle_material(doc, handle, dict_out_data, extra_params):
            """
            需要写入 handle 的文本：
            - 同时计算 管程入口接管 & 壳程入口接管
            - 相同则合并（写一条）
            - 不同则拼接：text1/text2
              即 牌号/供货状态/标准/牌号/供货状态/标准
            """
            text_tube = build_inlet_nozzle_material_text(dict_out_data, extra_params, "管程入口接管")
            text_shell = build_inlet_nozzle_material_text(dict_out_data, extra_params, "壳程入口接管")

            # 合并规则：完全一致则只保留一个
            if text_tube == text_shell:
                final_text = text_tube
            else:
                final_text = f"{text_tube}/{text_shell}"

            safe_modify(doc, handle, final_text)
            print(f"✅ 写入 handle {handle}: {final_text}")

        # ===== 使用方式（替换你原来的那段）=====
        write_inlet_nozzle_material(doc, "77844", dict_out_data, extra_params)

        def normalize_text(v):
            """把 None/'None'/首尾空格 统一清洗成稳定字符串"""
            if v is None:
                return ""
            v = str(v).strip()
            return "" if v.lower() == "none" else v

        def fetch_dict_field(row, field_name, default=""):
            """兼容 DictCursor：安全取字段"""
            if not row:
                return default
            if isinstance(row, dict):
                return row.get(field_name, default)
            return default

        def write_device_flange_fastener_material_to_handle(
                doc,
                product_id,
                handle="77845",
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
        ):
            """
            逻辑：
            1) 在 产品设计活动表_元件附加参数合并表 中，
               用 (产品ID + 参数名称='元件名称' + 参数值='设备法兰紧固件') 找到元件ID；
            2) 在同一 产品ID + 元件ID 下取：材料牌号1/供货状态1/材料标准1；
            3) 拼成 '牌号/供货状态/标准' 写入指定 handle。
            """
            conn = pymysql.connect(
                host=host, user=user, password=password,
                database=database, charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            try:
                cursor = conn.cursor()

                # 1) 找元件ID
                cursor.execute(
                    """
                    SELECT 元件ID
                    FROM 产品设计活动表_元件附加参数合并表
                    WHERE 产品ID = %s
                      AND 参数名称 = '元件名称'
                      AND 参数值 = '设备法兰紧固件'
                    LIMIT 1
                    """,
                    (product_id,)
                )
                row = cursor.fetchone()
                component_id = normalize_text(fetch_dict_field(row, "元件ID", ""))

                # 2) 取材料三项（1号）
                grade1 = status1 = std1 = ""
                if component_id:
                    cursor.execute(
                        """
                        SELECT 参数名称, 参数值
                        FROM 产品设计活动表_元件附加参数合并表
                        WHERE 产品ID = %s
                          AND 元件ID = %s
                          AND 参数名称 IN ('材料牌号1', '供货状态1', '材料标准1')
                        """,
                        (product_id, component_id)
                    )
                    rows = cursor.fetchall() or []
                    for r in rows:
                        pname = normalize_text(r.get("参数名称"))
                        pval = normalize_text(r.get("参数值"))
                        if pname == "材料牌号1":
                            grade1 = pval
                        elif pname == "供货状态1":
                            status1 = pval
                        elif pname == "材料标准1":
                            std1 = pval

                # 3) 拼接并写入
                text = f"{grade1}/{status1}/{std1}"
                safe_modify(doc, handle, text)
                print(f"✅ 写入 handle {handle}: {text}")
                return text

            finally:
                try:
                    conn.close()
                except:
                    pass

        # 用法：
        write_device_flange_fastener_material_to_handle(doc, product_id, handle="77845")



        # 🔎 获取材料牌号/类型（元件计算结果表 + 附加参数表）

        # ========= 0) 从元件计算结果表取“管程入口接管”的材料类型/牌号 =========
        cursor.execute("""
            SELECT Name, Value
            FROM 产品设计活动表_元件计算结果表
            WHERE 产品ID = %s AND 元件名称 = %s
        """, (product_id, "管程入口接管"))
        calc_rows = cursor.fetchall()

        pipe_mat_type = ""
        pipe_mat_grade = ""
        for r in calc_rows:
            name = (r.get("Name") or "").strip()
            val = (r.get("Value") or "").strip()
            if name == "接管材料类型":
                pipe_mat_type = val
            elif name == "接管材料牌号":
                pipe_mat_grade = val

        # ========= 1) 管口表：找管口功能=“管程入口”的管口代号 =========
        cursor.execute("""
            SELECT 管口代号
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口功能 = %s
            LIMIT 1
        """, (product_id, "管程入口"))
        row_port = cursor.fetchone()
        port_code = (row_port.get("管口代号") if row_port else "") or ""
        port_code = str(port_code).strip()

        # 没找到就兜底（避免后续 SQL 报错）
        if not port_code:
            port_code = ""

        # ========= 2) 管口类别表：用 产品ID + 管口代号 找“材料分类” =========
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

        # 若材料分类仍为空：你可以选择直接 return / 或者退回全表逻辑
        # 这里选择“空则继续，但筛选会变宽（只按产品ID）”
        # 你如果希望更严格，可以改成 QMessageBox 或 raise
        # if not mat_category: ...

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
        param_map = {(str(r.get("参数名称") or "")).strip(): (str(r.get("参数值") or "")).strip() for r in param_rows}

        # ========= 4) idx 1~3：在“已筛选后的 param_map”里做匹配 =========
        flange_mat_grade = ""  # 接管法兰材料牌号
        flange_mat_type = ""  # 接管法兰材料类型

        for idx in range(1, 4):
            t_key = f"接管材料类型{idx}"
            g_key = f"接管材料牌号{idx}"

            # 在筛选后的类别内，比对材料类型/牌号，找到对应 idx
            if (param_map.get(t_key, "").strip().lower() == (pipe_mat_type or "").strip().lower()
                    and param_map.get(g_key, "").strip().lower() == (pipe_mat_grade or "").strip().lower()):
                flange_mat_grade = param_map.get(f"接管法兰材料牌号{idx}", "").strip()
                flange_mat_type = param_map.get(f"接管法兰材料类型{idx}", "").strip()
                print(idx, "idx")
                print(flange_mat_grade, "flange_mat_grade")
                break
        if flange_mat_type == "钢锻件":
            safe_modify(doc, "778b1",  f"{flange_mat_grade}Ⅱ")
            safe_modify(doc, "833e7",  f"{flange_mat_grade}Ⅱ")
        else:
            safe_modify(doc, "778b1", flange_mat_grade)
            safe_modify(doc, "833e7", flange_mat_grade)
        # ========= 0) 从元件计算结果表取“管程入口接管”的材料类型/牌号 =========
        cursor.execute("""
            SELECT Name, Value
            FROM 产品设计活动表_元件计算结果表
            WHERE 产品ID = %s AND 元件名称 = %s
        """, (product_id, "管程出口接管"))
        calc_rows = cursor.fetchall()

        pipe_mat_type = ""
        pipe_mat_grade = ""
        for r in calc_rows:
            name = (r.get("Name") or "").strip()
            val = (r.get("Value") or "").strip()
            if name == "接管材料类型":
                pipe_mat_type = val
            elif name == "接管材料牌号":
                pipe_mat_grade = val

        # ========= 1) 管口表：找管口功能=“管程入口”的管口代号 =========
        cursor.execute("""
            SELECT 管口代号
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口功能 = %s
            LIMIT 1
        """, (product_id, "管程出口"))
        row_port = cursor.fetchone()
        port_code = (row_port.get("管口代号") if row_port else "") or ""
        port_code = str(port_code).strip()

        # 没找到就兜底（避免后续 SQL 报错）
        if not port_code:
            port_code = ""

        # ========= 2) 管口类别表：用 产品ID + 管口代号 找“材料分类” =========
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

        # 若材料分类仍为空：你可以选择直接 return / 或者退回全表逻辑
        # 这里选择“空则继续，但筛选会变宽（只按产品ID）”
        # 你如果希望更严格，可以改成 QMessageBox 或 raise
        # if not mat_category: ...

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
        param_map = {(str(r.get("参数名称") or "")).strip(): (str(r.get("参数值") or "")).strip() for r in param_rows}

        # ========= 4) idx 1~3：在“已筛选后的 param_map”里做匹配 =========
        flange_mat_grade = ""  # 接管法兰材料牌号
        flange_mat_type = ""  # 接管法兰材料类型

        for idx in range(1, 4):
            t_key = f"接管材料类型{idx}"
            g_key = f"接管材料牌号{idx}"

            # 在筛选后的类别内，比对材料类型/牌号，找到对应 idx
            if (param_map.get(t_key, "").strip().lower() == (pipe_mat_type or "").strip().lower()
                    and param_map.get(g_key, "").strip().lower() == (pipe_mat_grade or "").strip().lower()):
                flange_mat_grade = param_map.get(f"接管法兰材料牌号{idx}", "").strip()
                flange_mat_type = param_map.get(f"接管法兰材料类型{idx}", "").strip()
                print(idx, "idx")
                print(flange_mat_grade, "flange_mat_grade")
                break
        if flange_mat_type == "钢锻件":
            safe_modify(doc, "778b6", f"{flange_mat_grade}Ⅱ")
        else:
            safe_modify(doc, "778b6", flange_mat_grade)

        # ========= 0) 从元件计算结果表取“管程入口接管”的材料类型/牌号 =========
        cursor.execute("""
            SELECT Name, Value
            FROM 产品设计活动表_元件计算结果表
            WHERE 产品ID = %s AND 元件名称 = %s
        """, (product_id, "壳程入口接管"))
        calc_rows = cursor.fetchall()

        pipe_mat_type = ""
        pipe_mat_grade = ""
        for r in calc_rows:
            name = (r.get("Name") or "").strip()
            val = (r.get("Value") or "").strip()
            if name == "接管材料类型":
                pipe_mat_type = val
            elif name == "接管材料牌号":
                pipe_mat_grade = val

        # ========= 1) 管口表：找管口功能=“管程入口”的管口代号 =========
        cursor.execute("""
            SELECT 管口代号
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口功能 = %s
            LIMIT 1
        """, (product_id, "壳程入口"))
        row_port = cursor.fetchone()
        port_code = (row_port.get("管口代号") if row_port else "") or ""
        port_code = str(port_code).strip()

        # 没找到就兜底（避免后续 SQL 报错）
        if not port_code:
            port_code = ""

        # ========= 2) 管口类别表：用 产品ID + 管口代号 找“材料分类” =========
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

        # 若材料分类仍为空：你可以选择直接 return / 或者退回全表逻辑
        # 这里选择“空则继续，但筛选会变宽（只按产品ID）”
        # 你如果希望更严格，可以改成 QMessageBox 或 raise
        # if not mat_category: ...

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
        param_map = {(str(r.get("参数名称") or "")).strip(): (str(r.get("参数值") or "")).strip() for r in param_rows}

        # ========= 4) idx 1~3：在“已筛选后的 param_map”里做匹配 =========
        flange_mat_grade = ""  # 接管法兰材料牌号
        flange_mat_type = ""  # 接管法兰材料类型

        for idx in range(1, 4):
            t_key = f"接管材料类型{idx}"
            g_key = f"接管材料牌号{idx}"

            # 在筛选后的类别内，比对材料类型/牌号，找到对应 idx
            if (param_map.get(t_key, "").strip().lower() == (pipe_mat_type or "").strip().lower()
                    and param_map.get(g_key, "").strip().lower() == (pipe_mat_grade or "").strip().lower()):
                flange_mat_grade = param_map.get(f"接管法兰材料牌号{idx}", "").strip()
                flange_mat_type = param_map.get(f"接管法兰材料类型{idx}", "").strip()
                print(idx, "idx")
                print(flange_mat_grade, "flange_mat_grade")
                break
        if flange_mat_type == "钢锻件":
            safe_modify(doc, "778bb", f"{flange_mat_grade}Ⅱ")
            safe_modify(doc, "833ea", f"{flange_mat_grade}Ⅱ")
        else:
            safe_modify(doc, "778bb", flange_mat_grade)
            safe_modify(doc, "833ea", flange_mat_grade)

        # ========= 0) 从元件计算结果表取“管程入口接管”的材料类型/牌号 =========
        cursor.execute("""
            SELECT Name, Value
            FROM 产品设计活动表_元件计算结果表
            WHERE 产品ID = %s AND 元件名称 = %s
        """, (product_id, "壳程气相出口接管"))
        calc_rows = cursor.fetchall()

        pipe_mat_type = ""
        pipe_mat_grade = ""
        for r in calc_rows:
            name = (r.get("Name") or "").strip()
            val = (r.get("Value") or "").strip()
            if name == "接管材料类型":
                pipe_mat_type = val
            elif name == "接管材料牌号":
                pipe_mat_grade = val

        # ========= 1) 管口表：找管口功能=“管程入口”的管口代号 =========
        cursor.execute("""
            SELECT 管口代号
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口功能 = %s
            LIMIT 1
        """, (product_id, "壳程气相出口"))
        row_port = cursor.fetchone()
        port_code = (row_port.get("管口代号") if row_port else "") or ""
        port_code = str(port_code).strip()

        # 没找到就兜底（避免后续 SQL 报错）
        if not port_code:
            port_code = ""

        # ========= 2) 管口类别表：用 产品ID + 管口代号 找“材料分类” =========
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

        # 若材料分类仍为空：你可以选择直接 return / 或者退回全表逻辑
        # 这里选择“空则继续，但筛选会变宽（只按产品ID）”
        # 你如果希望更严格，可以改成 QMessageBox 或 raise
        # if not mat_category: ...

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
        param_map = {(str(r.get("参数名称") or "")).strip(): (str(r.get("参数值") or "")).strip() for r in param_rows}

        # ========= 4) idx 1~3：在“已筛选后的 param_map”里做匹配 =========
        flange_mat_grade = ""  # 接管法兰材料牌号
        flange_mat_type = ""  # 接管法兰材料类型

        for idx in range(1, 4):
            t_key = f"接管材料类型{idx}"
            g_key = f"接管材料牌号{idx}"

            # 在筛选后的类别内，比对材料类型/牌号，找到对应 idx
            if (param_map.get(t_key, "").strip().lower() == (pipe_mat_type or "").strip().lower()
                    and param_map.get(g_key, "").strip().lower() == (pipe_mat_grade or "").strip().lower()):
                flange_mat_grade = param_map.get(f"接管法兰材料牌号{idx}", "").strip()
                flange_mat_type = param_map.get(f"接管法兰材料类型{idx}", "").strip()
                print(idx, "idx")
                print(flange_mat_grade, "flange_mat_grade")
                break
        if flange_mat_type == "钢锻件":
            safe_modify(doc, "83fdd", f"{flange_mat_grade}Ⅱ")
        else:
            safe_modify(doc, "83fdd", flange_mat_grade)
        # ========= 0) 从元件计算结果表取“管程入口接管”的材料类型/牌号 =========
        cursor.execute("""
                    SELECT Name, Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s AND 元件名称 = %s
                """, (product_id, "壳程液相出口接管"))
        calc_rows = cursor.fetchall()

        pipe_mat_type = ""
        pipe_mat_grade = ""
        for r in calc_rows:
            name = (r.get("Name") or "").strip()
            val = (r.get("Value") or "").strip()
            if name == "接管材料类型":
                pipe_mat_type = val
            elif name == "接管材料牌号":
                pipe_mat_grade = val

        # ========= 1) 管口表：找管口功能=“管程入口”的管口代号 =========
        cursor.execute("""
                    SELECT 管口代号
                    FROM 产品设计活动表_管口表
                    WHERE 产品ID = %s AND 管口功能 = %s
                    LIMIT 1
                """, (product_id, "壳程液相出口"))
        row_port = cursor.fetchone()
        port_code = (row_port.get("管口代号") if row_port else "") or ""
        port_code = str(port_code).strip()

        # 没找到就兜底（避免后续 SQL 报错）
        if not port_code:
            port_code = ""

        # ========= 2) 管口类别表：用 产品ID + 管口代号 找“材料分类” =========
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

        # 若材料分类仍为空：你可以选择直接 return / 或者退回全表逻辑
        # 这里选择“空则继续，但筛选会变宽（只按产品ID）”
        # 你如果希望更严格，可以改成 QMessageBox 或 raise
        # if not mat_category: ...

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
        param_map = {(str(r.get("参数名称") or "")).strip(): (str(r.get("参数值") or "")).strip() for r in
                     param_rows}

        # ========= 4) idx 1~3：在“已筛选后的 param_map”里做匹配 =========
        flange_mat_grade = ""  # 接管法兰材料牌号
        flange_mat_type = ""  # 接管法兰材料类型

        for idx in range(1, 4):
            t_key = f"接管材料类型{idx}"
            g_key = f"接管材料牌号{idx}"

            # 在筛选后的类别内，比对材料类型/牌号，找到对应 idx
            if (param_map.get(t_key, "").strip().lower() == (pipe_mat_type or "").strip().lower()
                    and param_map.get(g_key, "").strip().lower() == (pipe_mat_grade or "").strip().lower()):
                flange_mat_grade = param_map.get(f"接管法兰材料牌号{idx}", "").strip()
                flange_mat_type = param_map.get(f"接管法兰材料类型{idx}", "").strip()
                print(idx, "idx")
                print(flange_mat_grade, "flange_mat_grade")
                break
        if flange_mat_type == "钢锻件":
            safe_modify(doc, "8403a", f"{flange_mat_grade}Ⅱ")
        else:
            safe_modify(doc, "8403a", flange_mat_grade)
        # ========= 0) 从元件计算结果表取“管程入口接管”的材料类型/牌号 =========
        cursor.execute("""
                    SELECT Name, Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s AND 元件名称 = %s
                """, (product_id, "壳程液位计1接管"))
        calc_rows = cursor.fetchall()

        pipe_mat_type = ""
        pipe_mat_grade = ""
        for r in calc_rows:
            name = (r.get("Name") or "").strip()
            val = (r.get("Value") or "").strip()
            if name == "接管材料类型":
                pipe_mat_type = val
            elif name == "接管材料牌号":
                pipe_mat_grade = val

        # ========= 1) 管口表：找管口功能=“管程入口”的管口代号 =========
        cursor.execute("""
                    SELECT 管口代号
                    FROM 产品设计活动表_管口表
                    WHERE 产品ID = %s AND 管口功能 = %s
                    LIMIT 1
                """, (product_id, "壳程液位计1"))
        row_port = cursor.fetchone()
        port_code = (row_port.get("管口代号") if row_port else "") or ""
        port_code = str(port_code).strip()

        # 没找到就兜底（避免后续 SQL 报错）
        if not port_code:
            port_code = ""

        # ========= 2) 管口类别表：用 产品ID + 管口代号 找“材料分类” =========
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

        # 若材料分类仍为空：你可以选择直接 return / 或者退回全表逻辑
        # 这里选择“空则继续，但筛选会变宽（只按产品ID）”
        # 你如果希望更严格，可以改成 QMessageBox 或 raise
        # if not mat_category: ...

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
        param_map = {(str(r.get("参数名称") or "")).strip(): (str(r.get("参数值") or "")).strip() for r in
                     param_rows}

        # ========= 4) idx 1~3：在“已筛选后的 param_map”里做匹配 =========
        flange_mat_grade = ""  # 接管法兰材料牌号
        flange_mat_type = ""  # 接管法兰材料类型

        for idx in range(1, 4):
            t_key = f"接管材料类型{idx}"
            g_key = f"接管材料牌号{idx}"

            # 在筛选后的类别内，比对材料类型/牌号，找到对应 idx
            if (param_map.get(t_key, "").strip().lower() == (pipe_mat_type or "").strip().lower()
                    and param_map.get(g_key, "").strip().lower() == (pipe_mat_grade or "").strip().lower()):
                flange_mat_grade = param_map.get(f"接管法兰材料牌号{idx}", "").strip()
                flange_mat_type = param_map.get(f"接管法兰材料类型{idx}", "").strip()
                print(idx, "idx")
                print(flange_mat_grade, "flange_mat_grade")
                break
        if flange_mat_type == "钢锻件":
            safe_modify(doc, "8403d", f"{flange_mat_grade}Ⅱ")
        else:
            safe_modify(doc, "8403d", flange_mat_grade)
        # ========= 0) 从元件计算结果表取“管程入口接管”的材料类型/牌号 =========
        cursor.execute("""
                        SELECT Name, Value
                        FROM 产品设计活动表_元件计算结果表
                        WHERE 产品ID = %s AND 元件名称 = %s
                    """, (product_id, "壳程液位计2接管"))
        calc_rows = cursor.fetchall()

        pipe_mat_type = ""
        pipe_mat_grade = ""
        for r in calc_rows:
            name = (r.get("Name") or "").strip()
            val = (r.get("Value") or "").strip()
            if name == "接管材料类型":
                pipe_mat_type = val
            elif name == "接管材料牌号":
                pipe_mat_grade = val

        # ========= 1) 管口表：找管口功能=“管程入口”的管口代号 =========
        cursor.execute("""
                        SELECT 管口代号
                        FROM 产品设计活动表_管口表
                        WHERE 产品ID = %s AND 管口功能 = %s
                        LIMIT 1
                    """, (product_id, "壳程液位计2"))
        row_port = cursor.fetchone()
        port_code = (row_port.get("管口代号") if row_port else "") or ""
        port_code = str(port_code).strip()

        # 没找到就兜底（避免后续 SQL 报错）
        if not port_code:
            port_code = ""

        # ========= 2) 管口类别表：用 产品ID + 管口代号 找“材料分类” =========
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

        # 若材料分类仍为空：你可以选择直接 return / 或者退回全表逻辑
        # 这里选择“空则继续，但筛选会变宽（只按产品ID）”
        # 你如果希望更严格，可以改成 QMessageBox 或 raise
        # if not mat_category: ...

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
        param_map = {(str(r.get("参数名称") or "")).strip(): (str(r.get("参数值") or "")).strip() for r in
                     param_rows}

        # ========= 4) idx 1~3：在“已筛选后的 param_map”里做匹配 =========
        flange_mat_grade = ""  # 接管法兰材料牌号
        flange_mat_type = ""  # 接管法兰材料类型

        for idx in range(1, 4):
            t_key = f"接管材料类型{idx}"
            g_key = f"接管材料牌号{idx}"

            # 在筛选后的类别内，比对材料类型/牌号，找到对应 idx
            if (param_map.get(t_key, "").strip().lower() == (pipe_mat_type or "").strip().lower()
                    and param_map.get(g_key, "").strip().lower() == (pipe_mat_grade or "").strip().lower()):
                flange_mat_grade = param_map.get(f"接管法兰材料牌号{idx}", "").strip()
                flange_mat_type = param_map.get(f"接管法兰材料类型{idx}", "").strip()
                print(idx, "idx")
                print(flange_mat_grade, "flange_mat_grade")
                break
        if flange_mat_type == "钢锻件":
            safe_modify(doc, "84041", f"{flange_mat_grade}Ⅱ")
        else:
            safe_modify(doc, "84041", flange_mat_grade)
        # ========= 0) 从元件计算结果表取“管程入口接管”的材料类型/牌号 =========
        cursor.execute("""
                            SELECT Name, Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s AND 元件名称 = %s
                        """, (product_id, "壳程温度计接管"))
        calc_rows = cursor.fetchall()

        pipe_mat_type = ""
        pipe_mat_grade = ""
        for r in calc_rows:
            name = (r.get("Name") or "").strip()
            val = (r.get("Value") or "").strip()
            if name == "接管材料类型":
                pipe_mat_type = val
            elif name == "接管材料牌号":
                pipe_mat_grade = val

        # ========= 1) 管口表：找管口功能=“管程入口”的管口代号 =========
        cursor.execute("""
                            SELECT 管口代号
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID = %s AND 管口功能 = %s
                            LIMIT 1
                        """, (product_id, "壳程温度计"))
        row_port = cursor.fetchone()
        port_code = (row_port.get("管口代号") if row_port else "") or ""
        port_code = str(port_code).strip()

        # 没找到就兜底（避免后续 SQL 报错）
        if not port_code:
            port_code = ""

        # ========= 2) 管口类别表：用 产品ID + 管口代号 找“材料分类” =========
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

        # 若材料分类仍为空：你可以选择直接 return / 或者退回全表逻辑
        # 这里选择“空则继续，但筛选会变宽（只按产品ID）”
        # 你如果希望更严格，可以改成 QMessageBox 或 raise
        # if not mat_category: ...

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
        param_map = {(str(r.get("参数名称") or "")).strip(): (str(r.get("参数值") or "")).strip() for r in
                     param_rows}

        # ========= 4) idx 1~3：在“已筛选后的 param_map”里做匹配 =========
        flange_mat_grade = ""  # 接管法兰材料牌号
        flange_mat_type = ""  # 接管法兰材料类型

        for idx in range(1, 4):
            t_key = f"接管材料类型{idx}"
            g_key = f"接管材料牌号{idx}"

            # 在筛选后的类别内，比对材料类型/牌号，找到对应 idx
            if (param_map.get(t_key, "").strip().lower() == (pipe_mat_type or "").strip().lower()
                    and param_map.get(g_key, "").strip().lower() == (pipe_mat_grade or "").strip().lower()):
                flange_mat_grade = param_map.get(f"接管法兰材料牌号{idx}", "").strip()
                flange_mat_type = param_map.get(f"接管法兰材料类型{idx}", "").strip()
                print(idx, "idx")
                print(flange_mat_grade, "flange_mat_grade")
                break
        if flange_mat_type == "钢锻件":
            safe_modify(doc, "84044", f"{flange_mat_grade}Ⅱ")
        else:
            safe_modify(doc, "84044", flange_mat_grade)

        # 🔍 查询 U形换热管 材料信息
        cursor.execute("""
            SELECT 材料牌号, 供货状态, 材料标准
            FROM 产品设计活动表_元件材料表
            WHERE 产品ID = %s AND 元件名称 = 'U形换热管'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()

        if row:
            caipai = str(row.get("材料牌号", "") or "").strip()
            gonghuo = str(row.get("供货状态", "") or "").strip()
            biaozhun = str(row.get("材料标准", "") or "").strip()

            text = f"{caipai}/{gonghuo}/{biaozhun}"
            safe_modify(doc, "778C8", text)
            print(f"✅ 写入 handle 778C8: {text}")
        else:
            print("⚠️ 未找到 U形换热管 材料信息，未写入 778C8")
            # === 获取 config.ini 中布管输入参数 JSON 路径 ===
        # === 从数据库读取布管输入参数 ===
        sql = """
            SELECT `参数名`, `参数值`
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s
        """
        cursor.execute(sql, (product_id,))
        rows = cursor.fetchall()

        # 初始化字段值
        shell_passes = ""
        tube_passes = ""
        range_type = None

        for row in rows:
            pid = str(row["参数名"]).strip()
            pval = str(row["参数值"]).strip()

            if pid == "壳程程数":
                shell_passes = pval
            elif pid == "管程程数":
                tube_passes = pval
            elif pid == "换热管排列方式":
                range_type = pval

        # handle 映射
        range_handle_map = {
            "正三角形": "835bf",
            "转角正三角形": "835c0",
            "正方形": "835c1",
            "转角正方形": "835c2"
        }

        # 设置所有 handle
        all_handles = ["835bf", "835c0", "835c1", "835c2"]
        for h in all_handles:
            text = "√" if h == range_handle_map.get(range_type) else " "
            safe_modify(doc, h, text)
            print(f"✅ 设置 {h} → {text}")

        # === 写入图纸 ===
        safe_modify(doc, "7786A", shell_passes)
        safe_modify(doc, "77854", tube_passes)

        print(f"✅ 写入 77854（壳程数）: {shell_passes}")
        print(f"✅ 写入 7786A（管程数）: {tube_passes}")

        handle_to_value = {}

        # === 通用：元件附加参数表 ===
        yuanjian_map = {
            "管箱封头": "85896",
            "壳体大端圆筒": "8588d",
            "壳体小端圆筒": "85865",
            "锥壳":"8588f",
            "管箱法兰": "85888",
            "固定管板": "8588a",
            "U形换热管": "8586b",
            "壳体法兰": "85889",
            "壳体封头": "8587c",
            "管箱圆筒": "85867",
        }

        for name, handle in yuanjian_map.items():

            # =====================================================
            # 1️⃣ 材料牌号
            # =====================================================
            cursor.execute("""
                SELECT 参数值 
                FROM 产品设计活动表_元件附加参数表 
                WHERE 产品ID = %s AND 元件名称 = %s AND 参数名称 = '材料牌号'
                LIMIT 1
            """, (product_id, name))
            row = cursor.fetchone()
            material = row["参数值"].strip() if row and row.get("参数值") else ""

            # =====================================================
            # 2️⃣ 材料类型
            # =====================================================
            cursor.execute("""
                SELECT 参数值 
                FROM 产品设计活动表_元件附加参数表 
                WHERE 产品ID = %s AND 元件名称 = %s AND 参数名称 = '材料类型'
                LIMIT 1
            """, (product_id, name))
            row = cursor.fetchone()
            material_type = row["参数值"].strip() if row and row.get("参数值") else ""

            # =====================================================
            # 3️⃣ 锻件级别（⚠️ 结构属性，必须优先拼）
            # =====================================================
            forging_level = ""
            if material_type == "钢锻件":
                cursor.execute("""
                    SELECT 参数值 
                    FROM 产品设计活动表_元件附加参数表 
                    WHERE 产品ID = %s AND 元件名称 = %s AND 参数名称 = '锻件级别'
                    LIMIT 1
                """, (product_id, name))
                row = cursor.fetchone()
                forging_level = row["参数值"].strip() if row and row.get("参数值") else ""

            # ⭐ 基础值：材料牌号 + 锻件级别（先定死）
            base_value = f"{material}{forging_level}" if forging_level else material
            final_value = base_value

            # =====================================================
            # 4️⃣ 覆层逻辑
            # =====================================================
            if name == "固定管板":
                # ---------- 固定管板：双侧覆层 ----------
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

                gt_flag = side_map.get("管程侧是否添加覆层") == "是"
                kc_flag = side_map.get("壳程侧是否添加覆层") == "是"

                gt_mat = side_map.get("管程侧覆层材料牌号")
                kc_mat = side_map.get("壳程侧覆层材料牌号")

                if gt_flag and not kc_flag and gt_mat not in (None, "", "无", "None"):
                    final_value = f"{base_value}+{gt_mat}"

                elif kc_flag and not gt_flag and kc_mat not in (None, "", "无", "None"):
                    final_value = f"{base_value}+{kc_mat}"

                elif gt_flag and kc_flag:
                    if gt_mat not in (None, "", "无", "None") and kc_mat not in (None, "", "无", "None"):
                        final_value = f"{base_value}+{gt_mat}+{kc_mat}"

                # ---------- 回退旧逻辑 ----------
                else:
                    cursor.execute("""
                        SELECT 参数名称, 参数值 
                        FROM 产品设计活动表_元件附加参数表
                        WHERE 产品ID = %s AND 元件名称 = %s
                          AND 参数名称 IN ('是否添加覆层','覆层材料牌号')
                    """, (product_id, name))
                    fuceng_rows = cursor.fetchall()
                    if fuceng_rows:
                        fuceng_map = {r["参数名称"]: r["参数值"] for r in fuceng_rows}
                        if fuceng_map.get("是否添加覆层") == "是" and fuceng_map.get("覆层材料牌号"):
                            final_value = f"{base_value}+{fuceng_map['覆层材料牌号']}"

            else:
                # ---------- 非固定管板 ----------
                cursor.execute("""
                    SELECT 参数名称, 参数值 
                    FROM 产品设计活动表_元件附加参数表
                    WHERE 产品ID = %s AND 元件名称 = %s
                      AND 参数名称 IN ('是否添加覆层','覆层材料牌号')
                """, (product_id, name))
                fuceng_rows = cursor.fetchall()
                if fuceng_rows:
                    fuceng_map = {r["参数名称"]: r["参数值"] for r in fuceng_rows}
                    if fuceng_map.get("是否添加覆层") == "是" and fuceng_map.get("覆层材料牌号"):
                        final_value = f"{base_value}+{fuceng_map['覆层材料牌号']}"

            # =====================================================
            # 5️⃣ 写入结果
            # =====================================================
            handle_to_value[handle] = final_value
            print(f"👉 {name} = {final_value} → Handle: {handle}")

        # === 修改图纸文字 ===
        for handle, new_text in handle_to_value.items():
            print("handle:",handle)
            safe_modify(doc, handle, new_text )
        try:
            # === 预处理：先清空 77861/77862 文本 ===
            safe_modify(doc, "77861", "/")
            safe_modify(doc, "77862", "/")

            output_path = os.path.abspath("材料清单_temp.xlsx")

            # === ① 生成材料清单（G/H列） ===
            generate_material_list(product_id, output_path)
            json_path = "jisuan_output_new.json"
            template_file_path = os.path.join("modules\wenbenshengcheng", 'U形管计算.xlsx')

            # === ② 填写规格（E列） ===
            cunguige.main(json_path, output_path, 'Sheet1', product_id)
            add_template_sheet(output_path, template_file_path)
            fill_template_values(output_path, product_id)
            copy_u_tube_value_openpyxl(output_path)

            # === ③ 计算 7785F ===
            def calculate_huareminaji_from_excel(excel_path, sheet_name):
                try:
                    wb = openpyxl.load_workbook(excel_path, data_only=True)
                    ws = wb[sheet_name]

                    def extract_number(value):
                        if value is None:
                            return 0
                        m = re.search(r"[-+]?\d*\.?\d+", str(value))
                        return float(m.group()) if m else 0

                    tube_total = 0.0
                    if "U形管明细" in wb.sheetnames:
                        ws_u = wb["U形管明细"]
                        cell_value = ws_u["G5"].value
                        num = extract_number(cell_value)
                        tube_total = num if num is not None else 0.0
                        print(f"[U形管明细] G5={cell_value} -> tube_total={tube_total}")
                    else:
                        print("⚠️ 未找到工作表 'U形管明细'，tube_total=0")

                    # 2) total：来自 sheet_name 的 J 列最后一个有效数字
                    total = 0.0
                    if sheet_name in wb.sheetnames:
                        ws = wb[sheet_name]
                        last_num = None

                        for r in range(ws.max_row, 0, -1):
                            cell_value = ws.cell(row=r, column=10).value  # J列=10

                            # 过滤空
                            if cell_value is None:
                                continue
                            s = str(cell_value).strip()
                            if s == "" or s.lower() == "none":
                                continue

                            num = extract_number(cell_value)
                            if num is not None:
                                last_num = num
                                print(f"[{sheet_name}] last J: row={r}, value={cell_value} -> {last_num}")
                                break

                        total = last_num if last_num is not None else 0.0
                    else:
                        print(f"⚠️ 未找到工作表 '{sheet_name}'，total=0")

                    result = total + tube_total

                    wb.close()
                    print(f"✅ 计算得到 7785F = {result} (total={total} + tube_total={tube_total})")
                    return result


                except Exception as e:
                    print(f"❌ calculate_7785F_from_excel 出错: {e}")
                    return 0

            # === ③ 计算 7785F ===
            def calculate_7785F_from_excel(excel_path, sheet_name):
                return calculate_7785f_from_excel_with_audit(
                    excel_path,
                    sheet_name,
                    mode="sheet_total_plus_utube",
                    audit_label=os.path.basename(__file__) if "__file__" in globals() else None
                )


            total_7785F = calculate_7785F_from_excel(output_path, 'Sheet1')
            huanremianji = calculate_huareminaji_from_excel(output_path, 'U形管明细')
            print(total_7785F)
            safe_modify(doc, "7785F", str(round(total_7785F, 2)))
            safe_modify(doc, "7784a", str(round(huanremianji, 2)))

            # === ④ 处理 77862 元件质量 ===
            TARGET_COMPONENTS = [
                "U形换热管", "旁路挡板", "中间挡板", "固定管板", "防松支耳", "尾部支撑",
                "定距管", "破涡器", "折流板", "防冲板", "支持板", "挡管", "堵板",
                "滑道", "拉杆", "螺母（拉杆）"
            ]

            def extract_components_mass(excel_path, sheet_name):
                mass_dict = {}
                try:
                    wb = openpyxl.load_workbook(excel_path, data_only=True)
                    ws = wb[sheet_name]

                    for row in ws.iter_rows(min_row=8):
                        name = str(row[3].value).strip() if row[3].value else ""
                        print(name)

                        if name in TARGET_COMPONENTS:
                            # ✅ U形换热管读第9列(row[8])，其他读第10列(row[9])
                            cell = row[8] if name == "U形换热管" else row[9]

                            try:
                                raw = cell.value
                                val = float(raw) if raw not in (None, "", "None") else 0.0
                            except (ValueError, TypeError):
                                val = 0.0

                            # ✅ 保留两位小数
                            mass_dict[name] = round(val, 2)

                    wb.close()
                    print("✅ 提取到质量字典：", mass_dict)

                except Exception:
                    err = traceback.format_exc()
                    print(f"❌ 提取质量失败:\n{err}")

                return mass_dict

            def update_77862_handle(doc, output_path, sheet_name):
                try:
                    import win32com.client as win32

                    mass_dict = extract_components_mass(output_path, sheet_name)
                    # ✅ 计算质量总和（忽略 None 和非数字）
                    total_mass = sum(v for v in mass_dict.values() if isinstance(v, (int, float)))

                    # ✅ 保留两位小数
                    total_mass = round(float(total_mass), 2)
                    # 🧩 Excel彻底关闭后再重新初始化COM（避免线程污染）

                    print(total_mass,"total_mass")
                    safe_modify(doc, "77860", total_mass)
                    print(f"🎯 77860 修改完成 → {total_mass}")
                except Exception:
                    err = traceback.format_exc()
                    print(f"❌ 更新 77862 失败:\n{err}")

            update_77862_handle(doc, output_path, 'Sheet1')

            # === ⑤ 删除临时 Excel ===
            def delete_temp_excel(file_path):
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        print(f"🗑️ 已删除临时文件: {file_path}")
                    else:
                        print(f"⚠️ 未找到临时文件: {file_path}")
                except Exception:
                    err = traceback.format_exc()
                    print(f"❌ 删除 {file_path} 失败:\n{err}")

            delete_temp_excel(output_path)

        except Exception:
            error_msg = traceback.format_exc()
            print(f"❌ 总体执行异常:\n{error_msg}")
            with open("生成7785F_77862错误.log", "a", encoding="utf-8") as f:
                f.write("==== 错误发生 ====\n")
                f.write(error_msg + "\n")
        value = get_mingpai_fushu(product_id)
        safe_modify(doc, "836cc", value)
    except Exception as e:
        logging.error("run_generation 出错", exc_info=True)
        traceback.print_exc()
        CAD_CTX["doc"] = None
        CAD_CTX["target_dwg"] = None
        raise RuntimeError(f"生成总图失败：{e}") from e
