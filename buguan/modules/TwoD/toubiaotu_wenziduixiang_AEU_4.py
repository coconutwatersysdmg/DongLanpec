import json
import re
import time
import traceback

import chardet
import configparser

import openpyxl
from pyautocad import Autocad
import pymysql

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
                return str(row[0] or "0"), str(row[1] or "0")
            else:
                print(f"未找到 产品ID={product_id} 参数={param_name}")
                return "0", "0"
    except Exception as e:
        print(f"数据库读取失败: {e}")
        return "0", "0"
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
                return str(row[0] or "0"), str(row[1] or "0")
            else:
                print(f"未找到 产品ID={product_id} 参数={param_name}")
                return "0", "0"
    except Exception as e:
        print(f"数据库读取失败: {e}")
        return "0", "0"
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
        return "0", "0"
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
                return row[0], row[1]
            else:
                print(f"未找到 产品ID={product_id}")
                return None, None
    except Exception as e:
        print(f"数据库读取失败: {e}")
        return None, None
    finally:
        if 'connection' in locals():
            connection.close()


# 主程序
# product_id =None
#
#
# def on_product_id_changed(new_id):
#     print(f"Received new PRODUCT_ID: {new_id}")
#     global product_id
#     product_id = new_id
#
#
# print('product_id', product_id)
#
# # # 测试用产品 ID（真实情况中由外部输入）
# product_manager.product_id_changed.connect(on_product_id_changed)


def twoDgeneration(product_id):
    acad, doc = open_drawing_with_wait(r'AEU投标图_4.dwg')
    if not doc:
        print("❌ 图纸未打开成功，流程中止。")
        return    # 提取文字类对象

    def extract_text(doc, retries=10, delay=1):
        print("【文字对象】提取中...")
        for attempt in range(retries):
            try:
                for obj in doc.ModelSpace:
                    if obj.ObjectName in ['AcDbText', 'AcDbMText']:
                        print(
                            f"{obj.ObjectName}: '{obj.TextString}' 位置: {obj.InsertionPoint} 图层: {obj.Layer} Handle: {obj.Handle}")
                return  # 成功就返回
            except Exception as e:
                print(f"⚠️ 第 {attempt + 1} 次尝试失败: {e}")
                time.sleep(delay)
        print("❌ 超过最大尝试次数，无法访问 ModelSpace")
    # 通用函数：修改文字对象
    def modify_text_by_handle(acad,handle, new_text):
        try:
            obj = doc.HandleToObject(handle)
            if obj is None:
                print(f"❌ Handle {handle} 不存在！")
                return False
            if obj.ObjectName in ['AcDbText', 'AcDbMText']:
                old_text = obj.TextString
                obj.TextString = new_text
                print(f"✅ 修改成功: '{old_text}' → '{new_text}' (Handle: {handle})")
                return True
            else:
                print(f"⚠️ Handle {handle} 类型不是文字对象：{obj.ObjectName}")
                return False
        except Exception as e:
            print(f"❌ 修改失败 (Handle: {handle}): {e}")
            return False
    # 初始化 AutoCAD
    extract_text(doc)

    # 处理产品法规 → 替换到 handle 77872
    regulation_text = get_standard_value(product_id, "技术法规")
    if regulation_text:
        modify_text_by_handle(doc,"77872", regulation_text)

    # 处理产品标准 → 替换到 handle 778CC
    standard_text = get_standard_value(product_id, "产品标准")
    if standard_text:
        modify_text_by_handle(doc,"778CC", standard_text)
    # 处理产品型式
    standard_text = get_xingshi_value(product_id)
    if standard_text:
        modify_text_by_handle(doc,"77849", standard_text)

    # 获取壳程数值、管程数值
    qiao_value, guan_value = get_shejishuju_value(product_id, "介质（组分）")
    modify_text_by_handle(doc,"77874", str(qiao_value))
    modify_text_by_handle(doc,"77875", str(guan_value))
    qiao_value, guan_value = get_shejishuju_value(product_id, "介质特性（毒性危害程度）")
    modify_text_by_handle(doc,"77876", str(qiao_value))
    modify_text_by_handle(doc,"77877", str(guan_value))
    qiao_value, guan_value = get_shejishuju_value(product_id, "工作压力")
    modify_text_by_handle(doc,"80B4D", str(qiao_value))
    modify_text_by_handle(doc,"80B55", str(guan_value))
    qiao_value, guan_value = get_shejishuju_value(product_id, "设计压力*")
    modify_text_by_handle(doc,"77864", str(qiao_value))
    modify_text_by_handle(doc,"7784E", str(guan_value))
    qiao_value, guan_value = get_shejishuju_value(product_id, "最高允许工作压力")
    modify_text_by_handle(doc,"77880", str(qiao_value))
    modify_text_by_handle(doc,"7787F", str(guan_value))
    # 77865 管板设计压差（壳程）
    # 7784F 管板设计压差（管程）
    qiao_value, guan_value = get_shejishuju_value(product_id, "管板设计压差")
    modify_text_by_handle(doc,"80B5E", str(qiao_value))
    modify_text_by_handle(doc,"80B66", str(guan_value))
    qiao_value, guan_value = get_shejishuju_value(product_id, "最低设计温度")
    modify_text_by_handle(doc, "77869", str(qiao_value))
    modify_text_by_handle(doc, "77853", str(guan_value))
    ru_qiao_value, ru_guan_value = get_shejishuju_value(product_id, "工作温度（入口）")
    chu_qiao_value, chu_guan_value = get_shejishuju_value(product_id, "工作温度（出口）")
    qiao_value = ru_qiao_value + "/" + chu_qiao_value
    guan_value = ru_guan_value + "/" + chu_guan_value
    modify_text_by_handle(doc,"77866", str(qiao_value))
    modify_text_by_handle(doc,"77850", str(guan_value))

    qiao_value, guan_value = get_shejishuju_value(product_id, "设计温度（最高）*")
    modify_text_by_handle(doc,"77867", str(qiao_value))
    modify_text_by_handle(doc,"77851", str(guan_value))

    qiao_value, guan_value = get_shejishuju_value(product_id, "腐蚀裕量*")
    modify_text_by_handle(doc,"77855", str(qiao_value))
    modify_text_by_handle(doc,"7786B", str(guan_value))
    qiao_value, guan_value = get_shejishuju_value(product_id, "焊接接头系数*")
    modify_text_by_handle(doc,"7786C", str(qiao_value))
    modify_text_by_handle(doc,"77C8C", str(guan_value))
    value, unit = get_tongyongshuju_value_danwei(product_id, "设计使用年限*")
    tongyongData = value + unit
    modify_text_by_handle(doc,"77856", str(tongyongData))
    qiao_value, guan_value = get_shejishuju_value(product_id, "超压泄放装置")
    modify_text_by_handle(doc,"77878", str(qiao_value))
    modify_text_by_handle(doc,"77879", str(guan_value))
    # 77852 7786C 金属平均温度（正常）（管程）（壳程）
    qiao_value1, guan_value1 = get_shejishuju_value(product_id, "自定义耐压试验压力（卧）")
    qiao_value2, guan_value2 = get_shejishuju_value(product_id, "自定义耐压试验压力（立）")
    modify_text_by_handle(doc,"7786D", str(qiao_value1+"/"+qiao_value1))
    modify_text_by_handle(doc,"77857", str(qiao_value2+"/"+qiao_value2))
    qiao_value, guan_value = get_shejishuju_value(product_id, "耐压试验试验介质")
    modify_text_by_handle(doc,"77885", str(qiao_value))
    modify_text_by_handle(doc,"77881", str(guan_value))
    qiao_value, guan_value = get_shejishuju_value(product_id, "耐压试验试验介质")
    modify_text_by_handle(doc,"77885", str(qiao_value))
    modify_text_by_handle(doc,"77881", str(guan_value))

    qiao_value, guan_value = get_shejishuju_value(product_id, "绝热层类型")
    if qiao_value == "保温" and guan_value == "保温":
        pass
    qiao_value, guan_value = get_shejishuju_value(product_id, "绝热材料")
    modify_text_by_handle(doc,"77889", str(qiao_value))
    modify_text_by_handle(doc,"7788A", str(guan_value))
    qiao_value, guan_value = get_shejishuju_value(product_id, "绝热层厚度")
    modify_text_by_handle(doc,"77883", str(qiao_value))
    modify_text_by_handle(doc,"77887", str(guan_value))
    qiao_value, guan_value = get_shejishuju_value(product_id, "绝热层厚度")
    modify_text_by_handle(doc,"77883", str(qiao_value))
    modify_text_by_handle(doc,"77887", str(guan_value))
    value, unit = get_tongyongshuju_value_danwei(product_id, "地震设防烈度")
    modify_text_by_handle(doc,"77899", str(value))
    value, unit = get_tongyongshuju_value_danwei(product_id, "地震加速度")
    modify_text_by_handle(doc,"7789A", str(value))
    value, unit = get_tongyongshuju_value_danwei(product_id, "地震分组")
    modify_text_by_handle(doc,"7789B", str(value))
    value, unit = get_tongyongshuju_value_danwei(product_id, "场地土地类别")
    tongyongData = value
    modify_text_by_handle(doc,"77859", str(tongyongData))
    value, unit = get_tongyongshuju_value_danwei(product_id, "雪压值")
    modify_text_by_handle(doc,"7785A", str(value))
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
    regulation_text1 = get_standard_value(product_id, "焊接工艺评定")
    regulation_text2 = get_standard_value(product_id, "焊接规程")
    regulation_text = regulation_text1 + '、' + regulation_text2
    modify_text_by_handle(doc,"77846", regulation_text)
    regulation_text = get_standard_value(product_id, "焊接接头型式标准")
    modify_text_by_handle(doc,"77847", regulation_text)
    regulation_text = get_standard_value(product_id, "焊接材料推荐标准")
    modify_text_by_handle(doc,"77848", regulation_text)
    regulation_text = get_guanban_value(product_id)
    modify_text_by_handle(doc,"7785B", regulation_text)
    # jietouzhonglei,jiancefangfa,kechengJishudengji,kechengJiancebili,kechengHegejibie,guanchengJishudengji,guanchengJiancebili,guanchengHegejibie = get_wusunjiance_value(product_id)
    items = get_wusunjiance_value(product_id)
    for item in items:
        if item[0] == 'A，B':
            if item[1] == "R.T.":
                kecheng_value = '/' if all(
                    str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                guancheng_value = '/' if all(
                    str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                modify_text_by_handle(doc, "7786F", str(kecheng_value))
                modify_text_by_handle(doc, "7787B", str(guancheng_value))
            elif item[1] == "U.T.":
                kecheng_value = '/' if all(
                    str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                guancheng_value = '/' if all(
                    str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                modify_text_by_handle(doc, "77896", str(kecheng_value))
                modify_text_by_handle(doc, "77897", str(guancheng_value))
            elif item[1] == "TOFD":
                kecheng_value = '/' if all(
                    str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                guancheng_value = '/' if all(
                    str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                modify_text_by_handle(doc, "77895", str(kecheng_value))
                modify_text_by_handle(doc, "77898", str(guancheng_value))
            elif item[1] == "M.T.":
                kecheng_value = '/' if all(
                    str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                guancheng_value = '/' if all(
                    str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                modify_text_by_handle(doc, "778CD", str(kecheng_value))
                modify_text_by_handle(doc, "778CE", str(guancheng_value))
            elif item[1] == "P.T.":
                kecheng_value = '/' if all(
                    str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                guancheng_value = '/' if all(
                    str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                modify_text_by_handle(doc, "7788D", str(kecheng_value))
                modify_text_by_handle(doc, "7788E", str(guancheng_value))

        elif item[0] == "D":
            if item[1] == "U.T.":
                kecheng_value = '/' if all(
                    str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                guancheng_value = '/' if all(
                    str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                modify_text_by_handle(doc, "7788F", str(kecheng_value))
                modify_text_by_handle(doc, "77890", str(guancheng_value))
            elif item[1] == "M.T.":
                kecheng_value = '/' if all(
                    str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                guancheng_value = '/' if all(
                    str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                modify_text_by_handle(doc, "77891", str(kecheng_value))
                modify_text_by_handle(doc, "77892", str(guancheng_value))
            elif item[1] == "P.T.":
                kecheng_value = '/' if all(
                    str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                guancheng_value = '/' if all(
                    str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                modify_text_by_handle(doc, "7F358", str(kecheng_value))
                modify_text_by_handle(doc, "77894", str(guancheng_value))

        elif item[0] == "C，E":
            if item[1] == "M.T.[FB]":
                kecheng_value = '/' if all(
                    str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                guancheng_value = '/' if all(
                    str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                modify_text_by_handle(doc, "7F360", str(kecheng_value))
                modify_text_by_handle(doc, "7F368", str(guancheng_value))
            elif item[1] == "P.T.":
                kecheng_value = '/' if all(
                    str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                guancheng_value = '/' if all(
                    str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                modify_text_by_handle(doc, "7F370", str(kecheng_value))
                modify_text_by_handle(doc, "7F378", str(guancheng_value))

        elif item[0] == "T（管头）":
            if item[1] == "R.T.":
                kecheng_value = '/' if all(
                    str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                guancheng_value = '/' if all(
                    str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                if kecheng_value != guancheng_value:
                    print("sth went wrong")
                modify_text_by_handle(doc, "7F380", str(kecheng_value))
            elif item[1] == "P.T.":
                kecheng_value = '/' if all(
                    str(x).strip() == '' for x in item[2:5]) else f"{item[2]}/{item[3]}/{item[4]}"
                guancheng_value = '/' if all(
                    str(x).strip() == '' for x in item[5:8]) else f"{item[5]}/{item[6]}/{item[7]}"
                if kecheng_value != guancheng_value:
                    print("sth went wrong")
                modify_text_by_handle(doc, "7F388", str(kecheng_value))

    # √
    value, unit = get_tongyongshuju_value_danwei(product_id, "焊后热处理")
    if value == '壳程':
        modify_text_by_handle(doc,"7EDAC", '√')
        modify_text_by_handle(doc,"7787E", '')
    elif value == '管程':
        modify_text_by_handle(doc,"7787E", '√')
        modify_text_by_handle(doc,"7EDAC", '')
    else:
        modify_text_by_handle(doc,"7EDAC", '')
        modify_text_by_handle(doc,"7F0EF", '')
    value, unit = get_tongyongshuju_value_danwei(product_id, "硬度试验标准")
    modify_text_by_handle(doc,"77841", value)
    value, unit = get_tongyongshuju_value_danwei(product_id, "硬度试验合格指标")
    modify_text_by_handle(doc,"80CDD", value)
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
    value1, unit = get_tongyongshuju_value_danwei(product_id, "表面处理位置")
    value2, unit = get_tongyongshuju_value_danwei(product_id, "表面处理标准")
    value3, unit = get_tongyongshuju_value_danwei(product_id, "表面处理合格级别")
    value = value1 + '/' + value2 + '/' + value3
    modify_text_by_handle(doc,"7787C", value)
    regulation_text = get_standard_value(product_id, "运输包装标准")
    if regulation_text:
        modify_text_by_handle(doc,"77840", regulation_text)
    value, unit = get_tongyongshuju_value_danwei(product_id, "地面粗糙度")
    modify_text_by_handle(doc,"7785D", value)
    value, unit = get_tongyongshuju_value_danwei(product_id, "基本风压")
    modify_text_by_handle(doc,"7785E", value)
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
    modify_text_by_handle(doc,"7E778", row['项目名称'])
    modify_text_by_handle(doc,"7E780", row['业主名称'])
    modify_text_by_handle(doc,"7E7C9", row['项目编号'])
    modify_text_by_handle(doc,"7E790", row['工程总包方'])
    modify_text_by_handle(doc,"7E788", '/') #业主项目号

    row = get_chanpin_value(product_id)
    modify_text_by_handle(doc,"7E799", row[0])
    modify_text_by_handle(doc,"7E7A1", row[1])
    modify_text_by_handle(doc,"7E7A9", row[2])
    modify_text_by_handle(doc,"7E7B1", row[3])
    modify_text_by_handle(doc,"7E7D1", row[4])
    modify_text_by_handle(doc,"7E7D9", row[5])
    modify_text_by_handle(doc,"7E7F1", row[6])
    modify_text_by_handle(doc,"7E7C1", 'TS1210A41-2024') #设计证书号
    modify_text_by_handle(doc,"7E7E1", '/') #产品识别码
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
        WHERE 产品ID = %s AND 管口代号 IN ('N1', 'N2', 'N3', 'N4')
    """, (product_id,))
    rows = cursor.fetchall()

    # 构造代号 → 公称尺寸映射字典
    koukou_size_map = {row["管口代号"]: str(row["公称尺寸"]) for row in rows if row["公称尺寸"] is not None}
    modify_text_by_handle(doc, "778A9", koukou_size_map.get("N1", ""))
    modify_text_by_handle(doc, "778AA", koukou_size_map.get("N2", ""))
    modify_text_by_handle(doc, "778AB", koukou_size_map.get("N3", ""))
    modify_text_by_handle(doc, "778AC", koukou_size_map.get("N4", ""))
    # ✅ 获取 公称压力类型
    cursor.execute("""
            SELECT 公称压力类型
            FROM 产品设计活动表_管口类型选择表
            WHERE 产品ID = %s 
        """, (product_id,))
    pressure_type_rows = cursor.fetchall()
    # 伪造管口代号字段 N1~N4
    guankou_ids = ["N1", "N2", "N3", "N4"]
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
            WHERE 产品ID = %s AND 管口代号 IN ('N1', 'N2', 'N3', 'N4')
        """, (product_id,))
    pressure_level_rows = cursor.fetchall()
    pressure_level_map = {row["管口代号"]: str(row["压力等级"]) for row in pressure_level_rows if row["压力等级"]}

    # ✅ 压力等级 + 公称压力类型 填充
    for handle, code in zip(["778AD", "778C3", "778C4", "778C5"], ["N1", "N2", "N3", "N4"]):
        pressure_level = pressure_level_map.get(code, "")
        # pressure_type = pressure_type_map.get(code, "")
        combined = f"{pressure_level}" if pressure_level else ""
        modify_text_by_handle(doc, handle, combined)

    # ✅ 获取 法兰型式 + 密封面型式
    cursor.execute("""
        SELECT 管口代号, 法兰型式, 密封面型式
        FROM 产品设计活动表_管口表
        WHERE 产品ID = %s AND 管口代号 IN ('N1', 'N2', 'N3', 'N4')
    """, (product_id,))
    flange_rows = cursor.fetchall()
    flange_type_map = {
        row["管口代号"]: f"{row['法兰型式']}/{row['密封面型式']}"
        for row in flange_rows if row["法兰型式"] and row["密封面型式"]
    }

    # ✅ 写入 handle：778AE、778B4、778B9、778BE
    for handle, code in zip(["778AE", "778B4", "778B9", "778BE"], ["N1", "N2", "N3", "N4"]):
        text = flange_type_map.get(code, "")
        modify_text_by_handle(doc, handle, text)

    # ✅ 获取 外伸高度
    cursor.execute("""
        SELECT 管口代号, 外伸高度
        FROM 产品设计活动表_管口表
        WHERE 产品ID = %s AND 管口代号 IN ('N1', 'N2', 'N3', 'N4')
    """, (product_id,))
    extension_rows = cursor.fetchall()
    extension_map = {
        row["管口代号"]: str(row["外伸高度"])
        for row in extension_rows if row["外伸高度"] is not None
    }

    # ✅ 写入 handle：778B0、778C9、778CA、778CB
    for handle, code in zip(["778B0", "778C9", "778CA", "778CB"], ["N1", "N2", "N3", "N4"]):
        text = extension_map.get(code, "")
        modify_text_by_handle(doc, handle, text)
    # handle → 接管组件名 映射
    handle_map = {
        "7E6CD": "管程入口接管",
        "7E6CE": "管程出口接管",
        "778BA": "壳程入口接管",
        "778AF": "壳程出口接管"
    }
    json_path = "jisuan_output_new.json"  # 替换为实际路径
    jisuan_data = load_json_data(json_path)
    for handle, component_name in handle_map.items():
        if component_name in {"管程入口接管", "管程出口接管", "壳程入口接管", "壳程出口接管"}:
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
                    modify_text_by_handle(doc, handle, value)
            except Exception as e:
                print(f"❌ 处理 {component_name} 时出错: {e}")
    # handle → 模块名映射（用于读取 JSON）
    handle_to_module = {
        "778B2": "管程入口接管",
        "778B7": "管程出口接管",
        "778BC": "壳程入口接管",
        "778C1": "壳程出口接管"
    }

    # handle → 管口代号
    handle_map = {
        "778B2": "N1",
        "778B7": "N2",
        "778BC": "N3",
        "778C1": "N4"
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
        modify_text_by_handle(doc, handle, text)
    # 获取 N1~N4 的法兰标准
    cursor.execute("""
        SELECT 管口代号, 法兰标准
        FROM 产品设计活动表_管口表
        WHERE 产品ID = %s AND 管口代号 IN ('N1', 'N2', 'N3', 'N4')
    """, (product_id,))
    rows = cursor.fetchall()

    # 管口代号 → handle 映射
    guankou_to_handle = {
        "N1": "7E6A1",
        "N2": "7E6A2",
        "N3": "7E6A3",
        "N4": "7E6A4"
    }

    # 写入图纸
    for row in rows:
        guankou_id = row.get("管口代号", "").strip()
        flange_standard = str(row.get("法兰标准", "")).strip()
        handle = guankou_to_handle.get(guankou_id)

        if handle and flange_standard:
            modify_text_by_handle(doc, handle, flange_standard)
            print(f"✅ 写入 {handle} → {flange_standard}")
        else:
            print(f"⚠️ 跳过 {guankou_id}，无有效法兰标准或 handle")

    handle_map = {
        "778B1": "N1",
        "778B6": "N2",
        "778BB": "N3",
        "778C0": "N4"
    }


    for handle, guankou_daihao in handle_map.items():
        # 1️⃣ 获取材料分类
        cursor.execute("""
            SELECT 材料分类
            FROM 产品设计活动表_管口类别表
            WHERE 产品ID = %s
        """, (product_id,))
        class_rows = cursor.fetchall()
        category = class_rows[0]["材料分类"].strip() if class_rows and class_rows[0].get("材料分类") else None

        # 2️⃣ 获取管口零件ID
        cursor.execute("""
            SELECT 管口零件ID
            FROM 产品设计活动表_管口零件材料表
            WHERE 产品ID = %s AND 零件名称 = '接管'
        """, (product_id,))
        row = cursor.fetchone()
        part_id = row["管口零件ID"] if row and row.get("管口零件ID") else None

        if part_id:
            # 3️⃣ 获取材料类型参数
            if category:
                cursor.execute("""
                    SELECT 参数值
                    FROM 产品设计活动表_管口零件材料参数表
                    WHERE 产品ID = %s AND 管口零件ID = %s AND 类别 = %s AND 参数名称 = '材料类型'
                """, (product_id, part_id, category))
            else:
                cursor.execute("""
                    SELECT 参数值
                    FROM 产品设计活动表_管口零件材料参数表
                    WHERE 产品ID = %s AND 管口零件ID = %s AND 参数名称 = '材料类型'
                """, (product_id, part_id))

            mat_row = cursor.fetchone()
            value = str(mat_row["参数值"]).strip() if mat_row and mat_row.get("参数值") else ""
            modify_text_by_handle(doc, handle, value)
        else:
            print(f"❌ 未找到管口零件ID（{guankou_daihao}）")
    # 🔍 获取接管材料信息
    cursor.execute("""
        SELECT 材料牌号, 供货状态, 材料标准
        FROM 产品设计活动表_管口零件材料表
        WHERE 产品ID = %s AND 零件名称 = '接管'
        LIMIT 1
    """, (product_id,))
    row = cursor.fetchone()

    if row:
        caipai = str(row.get("材料牌号", "") or "").strip()
        gonghuo = str(row.get("供货状态", "") or "").strip()
        biaozhun = str(row.get("材料标准", "") or "").strip()

        text = f"{caipai}/{gonghuo}/{biaozhun}"
        modify_text_by_handle(doc, "77844", text)
        print(f"✅ 写入 handle 77844: {text}")
    else:
        print("⚠️ 未找到接管材料信息，未写入 77844")
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
        modify_text_by_handle(doc, "778C8", text)
        print(f"✅ 写入 handle 778C8: {text}")
    else:
        print("⚠️ 未找到 U形换热管 材料信息，未写入 778C8")
        # === 获取 config.ini 中布管输入参数 JSON 路径 ===
    config_path = os.path.expandvars(r"%APPDATA%\UDS\蓝滨数字化合作\data\config.ini")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"❌ 未找到配置文件: {config_path}")

    with open(config_path, 'rb') as f:
        raw = f.read()
        encoding = chardet.detect(raw)['encoding'] or 'utf-8'

    config = configparser.ConfigParser()
    config.read_string(raw.decode(encoding))
    product_dir = os.path.normpath(config.get('ProjectInfo', 'product_directory', fallback=''))

    json_path = os.path.join(product_dir, "中间数据", "布管输入参数.json")
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"❌ 未找到布管输入参数.json 文件: {json_path}")

    # === 加载 JSON 内容 ===
    with open(json_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
    range_type = None
    for item in json_data:
        if isinstance(item, dict) and item.get("paramName") == "换热管排列形式":
            range_type = str(item.get("paramValue", "")).strip()
            break

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
        modify_text_by_handle(doc, h, text)
        print(f"✅ 设置 {h} → {text}")
    # === 读取布管输入参数.json ===
    with open(json_path, "r", encoding="utf-8") as f:
        pipe_input_data = json.load(f)

    # 初始化字段值
    shell_passes = ""
    tube_passes = ""

    for item in pipe_input_data:
        if not isinstance(item, dict):
            continue
        pid = item.get("paramId", "")
        pval = str(item.get("paramValue", "")).strip()

        if pid == "Shell_NumberOfPasses":
            shell_passes = pval
        elif pid == "LB_TubePassCount":
            tube_passes = pval

    # === 写入图纸 ===
    modify_text_by_handle(doc, "77854", shell_passes)
    modify_text_by_handle(doc, "7786A", tube_passes)

    print(f"✅ 写入 77854（壳程数）: {shell_passes}")
    print(f"✅ 写入 7786A（管程数）: {tube_passes}")

    handle_to_value = {}

    # === 通用：元件附加参数表 ===
    yuanjian_map = {
        "管箱平盖": "77817",
        "壳体圆筒": "77818",
        "管箱法兰": "7781D",
        "固定管板": "77821",
        "U形换热管": "77823",
        "壳体法兰": "77828",
        "壳体封头": "77834",
        "管箱圆筒": "7781B",
        "头盖法兰": "81E28",
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
        modify_text_by_handle(doc, handle, new_text )
    try:
        # === 预处理：先清空 77861/77862 文本 ===
        modify_text_by_handle(doc, "77861", "/")
        modify_text_by_handle(doc, "77862", "/")

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
        modify_text_by_handle(doc, "7785F", str(round(total_7785F,2)))

        # === ④ 处理 77862 元件质量 ===
        TARGET_COMPONENTS = [
            "U形换热管", "旁路挡板", "中间挡板", "固定管板", "防松支耳", "尾部支撑",
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

                modify_text_by_handle(doc, "77860", total_mass)
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