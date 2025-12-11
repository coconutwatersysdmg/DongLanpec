import datetime
import json
import logging
import math
import re
import shutil
import subprocess
import time
import traceback

import chardet
import configparser

import openpyxl
from pyautocad import Autocad
import pymysql

from modules.TwoD.toubiaotu_wenziduixiang import get_autocad_instance
from modules.chanpinguanli.chanpinguanli_main import product_manager

import win32com.client
import os

from modules.wenbenshengcheng import cunguige
from modules.wenbenshengcheng.cunguige import get_value, load_json_data
from modules.wenbenshengcheng.generate_material_list import generate_material_list


def open_drawing_with_wait(file_path, timeout=30):
    """
    打开图纸文件并等待 AutoCAD 加载完成，返回目标文档对应的 Autocad 实例和 doc。
    """
    import os
    import time
    from pyautocad import Autocad

    if not os.path.exists(file_path):
        print(f"❌ 图纸文件不存在: {file_path}")
        return None, None

    file_name = os.path.basename(file_path).lower()
    print(f"📂 正在启动 AutoCAD 打开图纸: {file_path}")
    os.startfile(file_path)

    elapsed = 0
    while elapsed < timeout:
        try:
            acad = Autocad()
            for doc in acad.app.Documents:
                if doc.Name.lower() == file_name:
                    print(f"✅ 成功连接到图纸: {doc.Name}")
                    return acad, doc
        except Exception as e:
            print(f"⌛ AutoCAD 尚未就绪（{elapsed}s）：{e}")

        time.sleep(1)
        elapsed += 1

    print("❌ 超时未能连接到目标图纸")
    return None, None
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
        print(f"产品需求数据库读取失败: {e}")
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
        print(f"产品标准数据数据库读取失败: {e}")
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
        print(f"产品设计活动数据库读取失败: {e}")
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
        print(f"设计数据数据库读取失败: {e}")
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
        print(f"通用数据数据库读取失败: {e}")
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
                return str(row[0] or ""), str(row[1] or "")
            else:
                print(f"未找到 产品ID={product_id} 参数={param_name}")
                return "", ""
    except Exception as e:
        print(f"通用数据数据库读取失败: {e}")
        return "", ""
    finally:
        if 'connection' in locals():
            connection.close()


def get_guanban_value(product_id):
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
                SELECT DISTINCT `管板连接方式`
                FROM `产品设计活动表_管板连接表`
                WHERE `产品ID` = %s
            """
            cursor.execute(sql, (product_id))
            row = cursor.fetchone()
            if row:
                return row[0]
            else:
                print(f"未找到 产品ID={product_id}")
                return None, None
    except Exception as e:
        print(f"管板连接数据库读取失败: {e}")
        return None, None
    finally:
        if 'connection' in locals():
            connection.close()

import tkinter as tk
from tkinter import filedialog
def choose_cad_exe():
    root = tk.Tk()
    root.withdraw()
    exe_path = filedialog.askopenfilename(
        title="选择 AutoCAD 程序 (acad.exe)",
        filetypes=[("AutoCAD 可执行文件", "acad.exe"), ("所有文件", "*.*")]
    )
    return exe_path if exe_path else None
def try_start_autocad_com():
    try:
        acad = win32com.client.Dispatch("AutoCAD.Application")
        acad.Visible = True
        print("✅ 通过 COM 成功连接 AutoCAD")
        return acad
    except Exception as e:
        print(f"⚠️ COM 启动失败: {e}")
        return None
def start_autocad_by_path(exe_path):
    if not os.path.exists(exe_path):
        print("❌ 无效的 AutoCAD 路径")
        return None
    subprocess.Popen([exe_path])
    print(f"🚀 已手动启动 AutoCAD: {exe_path}")
    # ⚠️ 注意：这里要等 CAD 启动完成再去连 COM
    time.sleep(5)
    return try_start_autocad_com()
def get_autocad_instance():
    acad = try_start_autocad_com()
    if acad:
        return acad

    # 如果 COM 启动失败 → 让用户选择路径
    exe_path = choose_cad_exe()
    if not exe_path:
        print("⚠️ 未选择 AutoCAD 程序，退出。")
        return None

    return start_autocad_by_path(exe_path)
def twoDgeneration(product_id):
    try:
        acad = get_autocad_instance()
        if not acad:
            print("❌ 没有可用的 AutoCAD 实例")
            return
        path1 = "BES投标图"
        template_path = os.path.abspath("BES投标图-4-2.dwg")
        if not os.path.exists(template_path):
            print(f"❌ 模板不存在: {template_path}")
            return None
        print(f"🔹 使用模板: {template_path}")

        # 临时文件名

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_dwg = os.path.abspath(f"{path1}_{timestamp}.dwg")
        shutil.copy(template_path, temp_dwg)  # ✅ 复制模板

        print(f"🔹 复制模板生成临时文件: {temp_dwg}")
        # 打开指定图纸
        acad, doc = open_drawing_with_wait(temp_dwg)

        if not doc:
            print("❌ 图纸未打开成功")
            return

        print(f"✅ 已连接 CAD，当前文档: {doc.Name}")

        # def extract_text(doc, retries=10, delay=1):
        #     print("【文字对象】提取中...")
        #     for attempt in range(retries):
        #         try:
        #             count = 0
        #             for obj in doc.ModelSpace:
        #                 if obj.ObjectName in ['AcDbText', 'AcDbMText']:
        #                     print(
        #                         f"{obj.ObjectName}: '{obj.TextString}' "
        #                         f"位置: {obj.InsertionPoint} "
        #                         f"图层: {obj.Layer} "
        #                         f"Handle: {obj.Handle}"
        #                     )
        #                     count += 1
        #             print(f"✅ 成功访问 ModelSpace，提取到 {count} 个文字对象")
        #             return  # 成功就返回
        #         except Exception as e:
        #             print(f"⚠️ 第 {attempt + 1} 次尝试失败: {e}")
        #             time.sleep(delay)
        #     print("❌ 超过最大尝试次数，无法访问 ModelSpace")
        #
        # extract_text(doc, retries=15, delay=2)

        # 通用函数：修改文字对象
        def get_current_doc():
            acad = Autocad(create_if_not_exists=True)  # ⚡ 每次都创建新的 COM 对象
            try:
                return acad.doc
            except Exception as e:
                print(f"⚠️ 获取当前文档失败: {e}")
                return None

        def safe_modify(doc, handle, value):
            """如果 value 没有值，则替换成 '/'，再修改句柄"""
            if value in (None, "", "None"):
                value = "/"
            modify_text_by_handle(doc, handle, str(value))
        def modify_text_by_handle(doc, handle, new_text, retries=5, delay=0.5):
            doc = get_current_doc()
            if not doc:
                print("⚠️ 未获取当前文档")
                return False

            safe_text = str(new_text).replace("\r", "").replace("\n", "").replace("\t", "")

            # 强制刷新文档状态
            try:
                doc.Regen()
            except:
                pass

            # 等待 COM 对象稳定
            time.sleep(0.5)

            for attempt in range(retries):
                try:
                    obj = doc.HandleToObject(handle)
                    if obj is None:
                        print(f"⚠️ Handle {handle} 不存在，第 {attempt + 1} 次重试...")
                        time.sleep(delay)
                        continue

                    if hasattr(obj, 'TextString'):
                        old = obj.TextString
                        obj.TextString = safe_text
                        print(f"✅ 修改成功: Handle {handle} → '{safe_text}'")
                        return True
                    elif hasattr(obj, 'Value'):
                        old = obj.Value
                        obj.Value = safe_text
                        print(f"✅ 修改成功: Handle {handle} → '{safe_text}'")
                        return True
                    else:
                        print(f"⚠️ Handle {handle} 对象不支持 TextString/Value")
                        return False

                except Exception as e:
                    print(f"⚠️ 第 {attempt + 1} 次修改失败: {e}")
                    time.sleep(delay)

            print(f"❌ 修改失败: {handle}")
            return False
        # 初始化 AutoCAD
        # extract_text(doc)

        # 处理产品法规 → 替换到 handle 77872
        regulation_text = get_standard_value(product_id, "技术法规")
        if regulation_text:
            safe_modify(doc,"77872", regulation_text)
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
              AND `元件名称` = '壳体圆筒' 
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
        # 处理产品标准 → 替换到 handle 778CC
        standard_text = get_standard_value(product_id, "产品标准")
        if standard_text:
            safe_modify(doc,"778CC", standard_text)
        # 处理产品型式
        standard_text = get_xingshi_value(product_id)
        if standard_text:
            safe_modify(doc,"77849", standard_text)

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
        qiao_value, guan_value = get_shejishuju_value(product_id, "设计压力* ")
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
        safe_modify(doc,"77855", str(qiao_value))
        safe_modify(doc,"7786B", str(guan_value))
        qiao_value, guan_value = get_shejishuju_value(product_id, "焊接接头系数*")
        safe_modify(doc,"7786C", str(qiao_value))
        safe_modify(doc,"77C8C", str(guan_value))
        value, unit = get_tongyongshuju_value_danwei(product_id, "设计使用年限*")
        tongyongData = value + unit
        safe_modify(doc,"77856", str(tongyongData))
        qiao_value, guan_value = get_shejishuju_value(product_id, "超压泄放装置")
        safe_modify(doc,"77878", str(qiao_value))
        safe_modify(doc,"77879", str(guan_value))
        # 77852 7786C 金属平均温度（正常）（管程）（壳程）

        qiao_value, guan_value = get_shejishuju_value(product_id, "耐压试验试验介质")
        safe_modify(doc,"77885", str(qiao_value))
        safe_modify(doc,"77881", str(guan_value))
        qiao_value, guan_value = get_shejishuju_value(product_id, "耐压试验试验介质")
        safe_modify(doc,"77885", str(qiao_value))
        safe_modify(doc,"77881", str(guan_value))

        qiao_value, guan_value = get_shejishuju_value(product_id, "绝热层类型")
        if qiao_value == "保温" and guan_value == "保温":
            pass
        qiao_value, guan_value = get_shejishuju_value(product_id, "绝热材料")
        safe_modify(doc,"77889", str(qiao_value))
        safe_modify(doc,"7788A", str(guan_value))
        qiao_value, guan_value = get_shejishuju_value(product_id, "绝热层厚度")
        safe_modify(doc,"77883", str(qiao_value))
        safe_modify(doc,"77887", str(guan_value))
        qiao_value, guan_value = get_shejishuju_value(product_id, "绝热层厚度")
        safe_modify(doc,"77883", str(qiao_value))
        safe_modify(doc,"77887", str(guan_value))
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
        safe_modify(doc,"77873", regulation_text)
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
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                    safe_modify(doc, "7786F", str(kecheng_value))
                    safe_modify(doc, "7787B", str(guancheng_value))
                elif item[1] == "U.T.":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                    safe_modify(doc, "77896", str(kecheng_value))
                    safe_modify(doc, "77897", str(guancheng_value))
                elif item[1] == "TOFD":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                    safe_modify(doc, "77895", str(kecheng_value))
                    safe_modify(doc, "77898", str(guancheng_value))
                elif item[1] == "M.T.":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                    safe_modify(doc, "778CD", str(kecheng_value))
                    safe_modify(doc, "778CE", str(guancheng_value))
                elif item[1] == "P.T.":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                    safe_modify(doc, "7788D", str(kecheng_value))
                    safe_modify(doc, "7788E", str(guancheng_value))

            elif item[0] == "D":
                if item[1] == "U.T.":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                    safe_modify(doc, "7788F", str(kecheng_value))
                    safe_modify(doc, "77890", str(guancheng_value))
                elif item[1] == "M.T.":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                    safe_modify(doc, "77891", str(kecheng_value))
                    safe_modify(doc, "77892", str(guancheng_value))
                elif item[1] == "P.T.":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                    safe_modify(doc, "7F358", str(kecheng_value))
                    safe_modify(doc, "77894", str(guancheng_value))

            elif item[0] == "C，E":
                if item[1] == "M.T.[FB]":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                    safe_modify(doc, "7F360", str(kecheng_value))
                    safe_modify(doc, "7F368", str(guancheng_value))
                elif item[1] == "P.T.":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                    safe_modify(doc, "7F370", str(kecheng_value))
                    safe_modify(doc, "7F378", str(guancheng_value))

            elif item[0] == "T（管头）":
                if item[1] == "R.T.":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                    if kecheng_value != guancheng_value:
                        print("sth went wrong")
                    safe_modify(doc, "7F380", str(kecheng_value))
                    if str(kecheng_value) == '/////':
                        modify_text_by_handle(doc, "7F380", '/')
                elif item[1] == "P.T.":
                    kecheng_value = '/' if all(
                        str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                    guancheng_value = '/' if all(
                        str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"

                    safe_modify(doc, "7F388", str(kecheng_value))
                    if str(kecheng_value) == '/////':
                        modify_text_by_handle(doc, "7F388", '/')

        # √
        value, unit = get_tongyongshuju_value_danwei(product_id, "焊后热处理")
        if value == '壳程':
            safe_modify(doc,"7EDAC", '√')
            modify_text_by_handle(doc,"7787E", '')
        elif value == '管程':
            safe_modify(doc,"7787E", '√')
            modify_text_by_handle(doc,"7EDAC", '')
        else:
            modify_text_by_handle(doc,"7EDAC", '')
            modify_text_by_handle(doc,"7F0EF", '')
        value, unit = get_tongyongshuju_value_danwei(product_id, "硬度试验标准")
        safe_modify(doc,"77841", value)
        value, unit = get_tongyongshuju_value_danwei(product_id, "硬度试验合格指标")
        safe_modify(doc,"80CDD", value)
        value, unit = get_tongyongshuju_value_danwei(product_id, "管束防腐要求")
        if value == '管内':
            safe_modify(doc,"7EBAD", '√')
            modify_text_by_handle(doc,"7EBB5", '')
            safe_modify(doc,"7EDA4", '√')
            modify_text_by_handle(doc,"7ED9C", '')
        elif value == '管外':
            safe_modify(doc,"7EBB5", '√')
            modify_text_by_handle(doc,"7EBAD", '')
            safe_modify(doc,"7ED9C", '√')
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
        # 77861 设备操作重量

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
        safe_modify(doc,"7E7C1", 'TS1210A41-2024') #设计证书号
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
        # 假设你已连接数据库，conn 为 pymysql.connect() 返回的对象
        cursor.execute("""
            SELECT 管口代号, 公称尺寸
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口代号 IN ('N1', 'N2', 'N3', 'N4', 'N5','N6')
        """, (product_id,))
        rows = cursor.fetchall()

        # 构造代号 → 公称尺寸映射字典
        koukou_size_map = {row["管口代号"]: str(row["公称尺寸"]) for row in rows if row["公称尺寸"] is not None}
        safe_modify(doc, "778A9", koukou_size_map.get("N1", ""))
        safe_modify(doc, "778AA", koukou_size_map.get("N2", ""))
        safe_modify(doc, "778AB", koukou_size_map.get("N3", ""))
        safe_modify(doc, "778AC", koukou_size_map.get("N4", ""))
        safe_modify(doc, "80D4B", koukou_size_map.get("N5", ""))
        safe_modify(doc, "80D53", koukou_size_map.get("N6", ""))

        # ✅ 获取 公称压力类型
        cursor.execute("""
                SELECT 公称压力类型
                FROM 产品设计活动表_管口类型选择表
                WHERE 产品ID = %s 
            """, (product_id,))
        pressure_type_rows = cursor.fetchall()
        # 伪造管口代号字段 N1~N4
        guankou_ids = ["N1", "N2", "N3", "N4","N5","N6"]
        for i, row in enumerate(pressure_type_rows):
            if i < len(guankou_ids):
                row["管口代号"] = guankou_ids[i]

        # ✅ 不改结构的写法继续工作
        pressure_type_map = {
            row["管口代号"]: str(row["公称压力类型"]).strip()
            for row in pressure_type_rows if row.get("公称压力类型")
        }
        # ✅ 获取 压力等级
        cursor.execute("""
                SELECT 管口代号, 压力等级
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口代号 IN ('N1', 'N2', 'N3', 'N4', 'N5', 'N6')
            """, (product_id,))
        pressure_level_rows = cursor.fetchall()
        pressure_level_map = {row["管口代号"]: str(row["压力等级"]) for row in pressure_level_rows if row["压力等级"]}

        # ✅ 压力等级 + 公称压力类型 填充
        for handle, code in zip(["778AD", "778C3", "778C4", "778C5","80D4D","80D55"], ["N1", "N2", "N3", "N4","N5","N6"]):
            pressure_level = pressure_level_map.get(code, "")
            # pressure_type = pressure_type_map.get(code, "")
            combined = f"{pressure_level}" if pressure_level else ""
            safe_modify(doc, handle, combined)

        # ✅ 获取 法兰型式 + 密封面型式
        cursor.execute("""
            SELECT 管口代号, 法兰型式, 密封面型式
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口代号 IN ('N1', 'N2', 'N3', 'N4','N5','N6')
        """, (product_id,))
        flange_rows = cursor.fetchall()
        flange_type_map = {
            row["管口代号"]: f"{row['法兰型式']}/{row['密封面型式']}"
            for row in flange_rows if row["法兰型式"] and row["密封面型式"]
        }

        # ✅ 写入 handle：778AE、778B4、778B9、778BE
        for handle, code in zip(["778AE", "778B4", "778B9", "778BE","80D4E","80D56"], ["N1", "N2", "N3", "N4","N5","N6"]):
            text = flange_type_map.get(code, "")
            safe_modify(doc, handle, text)

        def build_out_length_map(product_id):
            """
            构建管口外伸高度映射 {管口名称: 外伸高度}
            包含：管程入口、管程出口、壳程入口、壳程出口、排气口、排液口
            """
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

            # === 1. 获取开孔元件外径 ===
            cur.execute("""
                SELECT 元件名称, value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 IN ('管程入口接管','管程出口接管','壳程入口接管','壳程出口接管','排气口接管','排液口接管')
                  AND Name = '开孔元件外径'
            """, (product_id,))
            waijing_map = {row["元件名称"]: float(row["value"]) for row in cur.fetchall() if row.get("value")}

            # === 2. 获取接管实际外伸长度 ===
            cur.execute("""
                SELECT 元件名称, value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 IN ('管程入口接管','管程出口接管','壳程入口接管','壳程出口接管','排气口接管','排液口接管')
                  AND Name = '接管实际外伸长度'
            """, (product_id,))
            changdu_map = {row["元件名称"]: float(row["value"]) for row in cur.fetchall() if row.get("value")}

            # === 3. 法兰匹配获取 H 值 ===
            # 获取管口信息
            cur.execute("""
                SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口功能 IN ('管程入口','管程出口','壳程入口','壳程出口','排气口','排液口')
            """, (product_id,))
            ports = cur.fetchall()

            # 管口类型选择
            cur.execute("SELECT 公称尺寸类型, 公称压力类型 FROM 产品设计活动表_管口类型选择表 WHERE 产品ID = %s",
                        (product_id,))
            type_info = cur.fetchone()
            size_type = type_info["公称尺寸类型"] if type_info else "DN"
            press_type = type_info["公称压力类型"] if type_info else "PN"

            # 公称尺寸表 (NPS → DN)
            cur3.execute("SELECT NPS, DN FROM 公称尺寸表")
            nps_map = {str(r["NPS"]).strip(): str(r["DN"]).strip() for r in cur3.fetchall()}

            # 管法兰质量表
            cur2.execute("SELECT * FROM 管法兰质量表")
            flange_rows = cur2.fetchall()

            gaodu_map = {}

            for port in ports:
                func = port["管口功能"]  # 管程入口/出口、壳程入口/出口、排气口、排液口
                std = port["法兰标准"]
                size = str(port["公称尺寸"]).strip()
                pressure = str(port["压力等级"]).strip()
                flange_type = port["法兰型式"]
                face_type = port["密封面型式"]

                if size_type.upper() == "NPS":
                    size = nps_map.get(size, size)  # 转换成 DN

                for row in flange_rows:
                    if std and row["标准"] not in std:
                        continue
                    if str(row["DN"]).strip() != size:
                        continue
                    if press_type.upper() == "PN":
                        if str(row["PN"]).strip() != pressure:
                            continue
                    elif press_type.upper() == "CLASS":
                        if str(row["Class"]).strip() != pressure:
                            continue
                    if flange_type and str(row["法兰型式代号"]).strip() != str(flange_type).strip():
                        continue

                    face_col = f"H{face_type}" if face_type else None
                    if face_col and face_col in row:
                        gaodu_map[f"{func}接管"] = float(row[face_col])
                    break

            # === 4. 计算最终外伸高度 ===
            result = {}
            for port in ['管程入口接管', '管程出口接管', '壳程入口接管', '壳程出口接管', '排气口接管', '排液口接管']:
                try:
                    result[port] = str(
                        waijing_map.get(port, 0) / 2 +
                        changdu_map.get(port, 0) +
                        gaodu_map.get(port, 0)
                    )
                except Exception:
                    result[port] = ""

            return result

        # === 获取所有管口外伸高度 ===
        out_len_map = build_out_length_map(product_id)

        # === 映射到 handle ===
        port_handle_map = {
            "管程入口接管": "778B0",  # N1
            "管程出口接管": "778C9",  # N2
            "壳程入口接管": "778CA",  # N3
            "壳程出口接管": "778CB",  # N4
            "排气口接管": "80D5B",  # N5
            "排液口接管": "80D5C",  # N6
        }

        for port, handle in port_handle_map.items():
            safe_modify(doc, handle, out_len_map.get(port, ""))
        # handle → 接管组件名 映射
        handle_map = {
            "778AF": "管程入口接管",
            "7e6cd": "管程出口接管",
            "778BA": "壳程入口接管",
            "7e6ce": "壳程出口接管",
            "80D51": "排气口接管",
            "80D59": "排液口接管"
        }

        json_path = "jisuan_output_new.json"  # 替换为实际路径
        jisuan_data = load_json_data(json_path)
        for handle, component_name in handle_map.items():
            if component_name in {"管程入口接管", "管程出口接管", "壳程入口接管", "壳程出口接管","排气口接管","排液口接管"}:
                od = get_value(jisuan_data, component_name, "接管大端外径")
                thick = get_value(jisuan_data, component_name, "接管大端壁厚")
                l1 = get_value(jisuan_data, component_name, "接管实际外伸长度") or 0
                l2 = get_value(jisuan_data, component_name, "接管实际内伸长度") or 0

                try:
                    if None not in (od, thick):
                        od = float(od)
                        thick = float(thick)
                        l1 = float(l1)
                        l2 = float(l2)
                        value = f"∅{od}×{thick};L={l1 + l2}"
                        safe_modify(doc, handle, value)
                except Exception as e:
                    print(f"❌ 处理 {component_name} 时出错: {e}")
        # handle → 模块名映射（用于读取 JSON）
        handle_to_module = {
            "778B2": "管程入口接管",
            "778B7": "管程出口接管",
            "778BC": "壳程入口接管",
            "778C1": "壳程出口接管",
            "80D50": "排气口接管",
            "80D58": "排液口接管",
        }

        # handle → 管口代号
        handle_map = {
            "778B2": "N1",
            "778B7": "N2",
            "778BC": "N3",
            "778C1": "N4",
            "80D50": "N5",
            "80D58": "N6",
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
                    guankou_id = handle_map[handle]
                    handuan_spec_map[guankou_id] = value
                    break

        for handle, code in handle_map.items():
            # t = handuan_type_map.get(code, "")
            s = handuan_spec_map.get(code, "")
            text = f"{s}" if s else ""
            safe_modify(doc, handle, text)
        # 获取 N1~N4 的法兰标准
        cursor.execute("""
            SELECT 管口代号, 法兰标准
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口代号 IN ('N1', 'N2', 'N3', 'N4','N5','N6')
        """, (product_id,))
        rows = cursor.fetchall()

        # 管口代号 → handle 映射
        guankou_to_handle = {
            "N1": "7E6A1",
            "N2": "7E6A2",
            "N3": "7E6A3",
            "N4": "7E6A4",
            "N5": "80D5D",
            "N6": "80D5E",
        }

        # 写入图纸
        for row in rows:
            guankou_id = row.get("管口代号", "").strip()
            flange_standard = str(row.get("法兰标准", "")).strip()
            handle = guankou_to_handle.get(guankou_id)

            if handle and flange_standard:
                safe_modify(doc, handle, flange_standard)
                print(f"✅ 写入 {handle} → {flange_standard}")
            else:
                print(f"⚠️ 跳过 {guankou_id}，无有效法兰标准或 handle")

        handle_map = {
            "778B1": "管程入口接管",
            "778B6": "管程出口接管",
            "778BB": "壳程入口接管",
            "778C0": "壳程出口接管",
            "80D4F": "排液口接管",
            "80D57": "排气口接管",
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
        # 🔎 获取材料牌号/类型（元件计算结果表 + 附加参数表）


        # 从 元件计算结果表 里取
        cursor.execute("""
            SELECT Name, Value
            FROM 产品设计活动表_元件计算结果表
            WHERE 产品ID = %s AND 元件名称 = %s
        """, (product_id, "管程入口接管"))
        calc_rows = cursor.fetchall()


        # ================== 从元件计算结果表取接管信息 ==================
        pipe_mat_type = ""
        pipe_mat_grade = ""
        for r in calc_rows:
            name = (r.get("Name") or "").strip()
            val = (r.get("Value") or "").strip()
            if name == "接管材料类型":
                pipe_mat_type = val
            elif name == "接管材料牌号":
                pipe_mat_grade = val

        # ================== 从附加参数表取所有参数 ==================
        cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_管口附加参数表
            WHERE 产品ID = %s
        """, (product_id,))
        param_rows = cursor.fetchall()


        param_map = {(r["参数名称"] or "").strip(): (r["参数值"] or "").strip() for r in param_rows}

        # ================== 初始化两套输出 ==================
        flange_mat_grade = ""  # 接管法兰材料牌号

        # ================== 匹配编号 idx ==================
        for idx in range(1, 4):  # 可按需要改范围
            t_key = f"接管材料类型{idx}"
            g_key = f"接管材料牌号{idx}"
            s_key = f"接管供货状态{idx}"

            # 找到和元件计算结果表一致的接管
            if param_map.get(t_key, "").lower() == pipe_mat_type.lower() and \
                    param_map.get(g_key, "").lower() == pipe_mat_grade.lower():

                # 对应 idx 的接管法兰信息
                flange_mat_grade = param_map.get(f"接管法兰材料牌号{idx}", "").strip()
                break
        safe_modify(doc, "85b05", flange_mat_grade)
        # 从 元件计算结果表 里取
        cursor.execute("""
            SELECT Name, Value
            FROM 产品设计活动表_元件计算结果表
            WHERE 产品ID = %s AND 元件名称 = %s
        """, (product_id, "壳程入口接管"))
        calc_rows = cursor.fetchall()


        # ================== 从元件计算结果表取接管信息 ==================
        pipe_mat_type = ""
        pipe_mat_grade = ""
        for r in calc_rows:
            name = (r.get("Name") or "").strip()
            val = (r.get("Value") or "").strip()
            if name == "接管材料类型":
                pipe_mat_type = val
            elif name == "接管材料牌号":
                pipe_mat_grade = val

        # ================== 从附加参数表取所有参数 ==================
        cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_管口附加参数表
            WHERE 产品ID = %s
        """, (product_id,))
        param_rows = cursor.fetchall()


        param_map = {(r["参数名称"] or "").strip(): (r["参数值"] or "").strip() for r in param_rows}

        # ================== 初始化两套输出 ==================
        flange_mat_grade = ""  # 接管法兰材料牌号

        # ================== 匹配编号 idx ==================
        for idx in range(1, 4):  # 可按需要改范围
            t_key = f"接管材料类型{idx}"
            g_key = f"接管材料牌号{idx}"
            s_key = f"接管供货状态{idx}"

            # 找到和元件计算结果表一致的接管
            if param_map.get(t_key, "").lower() == pipe_mat_type.lower() and \
                    param_map.get(g_key, "").lower() == pipe_mat_grade.lower():

                # 对应 idx 的接管法兰信息
                flange_mat_grade = param_map.get(f"接管法兰材料牌号{idx}", "").strip()
                break
        safe_modify(doc, "85b0d", flange_mat_grade)



        safe_modify(doc, "77816", "管箱平盖")
        safe_modify(doc, "77824", "壳体圆筒")
        # 🔍 获取接管材料信息
        # 从 JSON(dict_out) 拿第一个接管的信息（假设 N1 即可）
        module = dict_out_data.get("管程入口接管", {})
        datas = module.get("Datas", [])

        mat_type, mat_grade, mat_std = "", "", ""
        for item in datas:
            name = item.get("Name", "").strip()
            if name == "接管材料类型":
                mat_type = item.get("Value", "").strip()
            elif name == "接管材料牌号":
                mat_grade = item.get("Value", "").strip()
            elif name == "接管材料标准":
                mat_std = item.get("Value", "").strip()

        # === 匹配供货状态 ===
        supply_status = ""
        for i in range(1, 4):
            t_key, g_key, s_key = f"接管材料类型{i}", f"接管材料牌号{i}", f"接管供货状态{i}"
            if extra_params.get(t_key) == mat_type and extra_params.get(g_key) == mat_grade:
                supply_status = extra_params.get(s_key, "")
                break

        # 拼接最终文本
        text = f"{mat_grade}/{supply_status}/{mat_std}"

        # === 写入 Word 指定 handle ===
        safe_modify(doc, "77844", text)
        print(f"✅ 写入 handle 77844: {text}")


        # 🔍 查询 U形换热管 材料信息
        cursor.execute("""
            SELECT 材料牌号, 供货状态, 材料标准
            FROM 产品设计活动表_元件材料表
            WHERE 产品ID = %s AND 元件名称 = '换热管'
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
            SELECT `key`, `value`
            FROM 产品设计活动表_布管输入表
            WHERE 产品ID = %s
        """
        cursor.execute(sql, (product_id,))
        rows = cursor.fetchall()

        # 初始化字段值
        shell_passes = ""
        tube_passes = ""
        range_type = None

        for row in rows:
            pid = str(row["key"]).strip()
            pval = str(row["value"]).strip()

            if pid == "Shell_NumberOfPasses":
                shell_passes = pval
            elif pid == "LB_TubePassCount":
                tube_passes = pval
            elif pid == "换热管排列形式":
                range_type = pval

        # handle 映射
        range_handle_map = {
            "0": "80B00",
            "1": "80B09",
            "2": "80B11",
            "3": "80B19"
        }

        # 设置所有 handle
        all_handles = ["80B00", "80B09", "80B11", "80B19"]
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
            "管箱封头": "77817",
            "壳体圆筒": "77818",
            "管箱法兰": "7781D",
            "固定管板": "77821",
            "换热管": "77823",
            "壳体法兰": "77828",
            "外头盖封头": "77834",
            "管箱圆筒": "7781B",
            "球冠形封头": "80D88",
            "浮头法兰": "80D7F",
        }

        for name, handle in yuanjian_map.items():
            cursor.execute("""
                SELECT 参数值 
                FROM 产品设计活动表_元件附加参数表 
                WHERE 产品ID = %s AND 元件名称 = %s AND 参数名称 = '材料牌号'
                LIMIT 1
            """, (product_id, name))
            row = cursor.fetchone()
            value = row["参数值"].strip() if row and row.get("参数值") else ""
            handle_to_value[handle] = value
            print(f"✅ {name} 材料牌号: {value} → Handle: {handle}")

        # === 特殊：接管法兰 → 管口零件材料表 ===
        cursor.execute("""
            SELECT 材料牌号 
            FROM 产品设计活动表_管口零件材料表 
            WHERE 产品ID = %s AND 零件名称 = '接管法兰'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        value = row["材料牌号"].strip() if row and row.get("材料牌号") else ""
        handle_to_value["77819"] = value
        handle_to_value["7781F"] = value
        print(f"✅ 管程接管法兰 材料牌号: {value} → Handle: 7781D")

        # === 修改图纸文字 ===
        for handle, new_text in handle_to_value.items():
            print("handle:",handle)
            safe_modify(doc, handle, new_text )
        try:
            # === 预处理：先清空 77861/77862 文本 ===
            safe_modify(doc, "77861", "/")
            safe_modify(doc, "77862", "/")

            output_path = os.path.join("材料清单_temp.xlsx")

            # === ① 生成材料清单（G/H列） ===
            generate_material_list(product_id, output_path)
            json_path = "jisuan_output_new.json"
            # === ② 填写规格（E列） ===
            cunguige.main(json_path, output_path, 'Sheet1', product_id)

            # === ③ 计算 7785F ===
            def calculate_7785F_from_excel(excel_path, sheet_name):
                try:
                    wb = openpyxl.load_workbook(excel_path, data_only=True)
                    ws = wb[sheet_name]

                    def extract_number(value):
                        if value is None:
                            return 0
                        m = re.search(r"[-+]?\d*\.?\d+", str(value))
                        return float(m.group()) if m else 0

                    total = 0
                    for row in ws.iter_rows(min_row=8):
                        row_sum = sum(extract_number(row[col_idx - 1].value) for col_idx in range(12, 18))
                        total += row_sum

                    wb.close()
                    print(f"✅ 计算得到 7785F = {total}")
                    return total
                except Exception:
                    err = traceback.format_exc()
                    print(f"❌ 计算 7785F 失败:\n{err}")
                    return 0

            total_7785F = calculate_7785F_from_excel(output_path, 'Sheet1')
            print(total_7785F)
            safe_modify(doc, "7785F", str(round(total_7785F,2)))

            # === ④ 处理 77862 元件质量 ===
            TARGET_COMPONENTS = [
                "换热管", "旁路挡板", "中间挡板", "固定管板", "防松支耳", "尾部支撑",
                "定距管", "破涡器", "折流板", "防冲板", "支持板", "挡管", "堵板",
                "滑道", "拉杆", "螺母(拉杆)"
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
                            try:
                                val = float(row[8].value) if row[8].value not in (None, "", "None") else 0
                            except ValueError:
                                val = 0
                            mass_dict[name] = val
                    wb.close()
                    print("✅ 提取到质量字典：", mass_dict)
                except Exception:
                    err = traceback.format_exc()
                    print(f"❌ 提取质量失败:\n{err}")
                return mass_dict

            def update_77862_handle(doc, output_path, sheet_name):
                try:
                    mass_dict = extract_components_mass(output_path, sheet_name)
                    # ✅ 计算质量总和（忽略 None 和非数字）
                    total_mass = sum(v for v in mass_dict.values() if isinstance(v, (int, float)))

                    # ✅ 保留两位小数
                    total_mass = round(total_mass, 2)

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
    except Exception as e:
        logging.error("run_generation 出错", exc_info=True)
        traceback.print_exc()
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.critical(None, "错误", f"生成二维图失败:\n{e}")