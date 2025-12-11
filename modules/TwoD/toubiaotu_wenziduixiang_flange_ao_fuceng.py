import datetime
import json
import re
import shutil
import tempfile
import time
import traceback

import chardet
import configparser

import openpyxl
from pyautocad import Autocad
import pymysql

from modules.TwoD.toubiaotu_biaozhu import extract_dimensions
from modules.chanpinguanli.chanpinguanli_main import product_manager

import win32com.client
import os

from modules.wenbenshengcheng import cunguige
from modules.wenbenshengcheng.cunguige import get_value, load_json_data
from modules.wenbenshengcheng.generate_material_list import generate_material_list


def open_drawing_with_wait(file_path, timeout=30, cold_start_delay=5):
    """
    打开图纸文件并等待 AutoCAD 加载完成，返回 Autocad 实例和 doc。
    """
    if not os.path.exists(file_path):
        print(f"❌ 图纸文件不存在: {file_path}")
        return None, None

    file_name = os.path.basename(file_path).lower()
    print(f"📂 正在启动 AutoCAD 打开图纸: {file_path}")
    os.startfile(file_path)

    # 给 AutoCAD 一个冷启动时间，避免立刻调用 COM
    time.sleep(cold_start_delay)

    elapsed = 0
    acad = None
    doc = None

    while elapsed < timeout:
        try:
            acad = Autocad(create_if_not_exists=True, visible=True)
            for d in acad.app.Documents:
                if d.Name.lower() == file_name:
                    doc = d
                    print(f"✅ 成功连接到图纸: {doc.Name}")
                    return acad, doc
        except Exception as e:
            # AutoCAD 尚未就绪（常见 RPC 错误）
            print(f"⌛ AutoCAD 尚未就绪（{elapsed}s）：{e}")

        time.sleep(1)
        elapsed += 1

    print("❌ 超时未能连接到目标图纸")
    return None, None
def twoDgeneration(product_id, flange):
    dwg_path = os.path.abspath("法兰凹-覆层.dwg")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_dwg = os.path.abspath(f"{flange}_{timestamp}.dwg")
    shutil.copyfile(dwg_path, temp_dwg)  # 复制模板生成新文件
    acad, doc = open_drawing_with_wait(temp_dwg, timeout=40, cold_start_delay=8)
    if not doc:
        print("❌ 图纸未打开成功，流程中止。")
        return
    # 这里就可以安全提取文字、图元
    # for ent in acad.iter_objects("Text"):
    #     print("文字内容:", ent.TextString)
    def get_flange_value(product_id, param_name, flange_name):
        connection = pymysql.connect(
            host='localhost',
            user='root',
            password='123456',
            database='产品设计活动库',
            charset='utf8mb4'
        )
        with connection.cursor() as cursor:
            sql = """
                SELECT `参数值`
                FROM `产品设计活动表_元件附加参数表`
                WHERE `产品ID` = %s AND `参数名称`=%s AND `元件名称` = %s
            """
            cursor.execute(sql, (product_id, param_name ,flange_name))
            row = cursor.fetchone()
            if row:
                return str(row[0] or "-")
            else:
                print(f"未找到 产品ID={product_id} 法兰={flange_name}")
                return "-", "-"
    def get_flang_jisuan_value(product_id, param_name, flange_name):
        connection = pymysql.connect(
            host='localhost',
            user='root',
            password='123456',
            database='产品设计活动库',
            charset='utf8mb4'
        )
        with connection.cursor() as cursor:
            sql = """
                        SELECT `Value`
                        FROM `产品设计活动表_元件计算结果表`
                        WHERE `产品ID` = %s AND `元件名称`=%s AND `Name` = %s
                        LIMIT 1
                    """
            cursor.execute(sql, (product_id, flange_name, param_name ))
            row = cursor.fetchone()
            if row:
                return str(row[0] or "-")
            else:
                print(f"未找到 产品ID={product_id} 法兰={flange_name}")
                return "-"


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
    def get_obj_safe(doc, handle, retries=3, delay=1):
        """通过 Handle 安全获取对象"""
        for attempt in range(retries):
            try:
                obj = doc.HandleToObject(handle)
                if obj:
                    return obj
            except Exception as e:
                print(f"⚠️ 第 {attempt + 1} 次尝试获取 Handle {handle} 失败: {e}")
            time.sleep(delay)
        print(f"❌ Handle {handle} 最终无法获取")
        return None

    # 通用函数：修改文字对象（支持 Text, MText, Dimension, Attribute, 有 Value 属性的对象）
    def get_current_doc():
        acad = Autocad(create_if_not_exists=True)  # ⚡ 每次都创建新的 COM 对象
        try:
            return acad.doc
        except Exception as e:
            print(f"⚠️ 获取当前文档失败: {e}")
            return None

    def modify_by_handle(doc, handle, new_text, retries=5, delay=0.5):
        doc = get_current_doc()
        if not doc:
            print("⚠️ 未获取当前文档")
            return False

        safe_text = str(new_text).replace("\r", "").replace("\n", "").replace("\t", "")

        # ⚡ 强制刷新文档状态
        try:
            doc.Regen()
        except:
            pass

        time.sleep(0.5)  # 等待 COM 稳定

        for attempt in range(retries):
            try:
                obj = doc.HandleToObject(handle)
                if obj is None:
                    print(f"⚠️ Handle {handle} 不存在，第 {attempt + 1} 次重试...")
                    time.sleep(delay)
                    continue

                if obj.ObjectName in ("AcDbText", "AcDbMText"):
                    old = obj.TextString
                    obj.TextString = safe_text
                    print(f"✅ 修改成功: '{old}' → '{safe_text}' (Handle {handle})")
                    return True

                elif "Dimension" in obj.ObjectName:
                    old = obj.TextOverride
                    obj.TextOverride = safe_text
                    print(f"✅ 修改成功: '{old}' → '{safe_text}' (Handle {handle})")
                    return True

                else:
                    print(f"⚠️ Handle {handle} 类型不支持修改: {obj.ObjectName}")
                    return False

            except Exception as e:
                print(f"⚠️ 第 {attempt + 1} 次修改失败: {e}")
                time.sleep(delay)

        print(f"❌ 修改失败: {handle}")
        return False

    def modify_text_by_handle(doc, handle, new_text):
        """兼容修改，和 modify_by_handle 保持一致"""
        obj = get_obj_safe(doc, handle)
        if not obj:
            return False
        safe_text = str(new_text).replace("\r", "").replace("\n", "").replace("\t", "")
        try:
            if hasattr(obj, "TextString"):
                old_text = obj.TextString
                obj.TextString = safe_text
                print(f"✅ 修改成功: '{old_text}' → '{safe_text}' (Handle: {handle})")
                return True
            elif hasattr(obj, "Value"):
                old_val = obj.Value
                obj.Value = safe_text
                print(f"✅ 修改成功(Value): '{old_val}' → '{safe_text}' (Handle: {handle})")
                return True
            elif "Dimension" in obj.ObjectName:
                old_text = getattr(obj, "TextOverride", "")
                obj.TextOverride = safe_text
                print(f"✅ 修改标注: '{old_text}' → '{safe_text}' (Handle: {handle})")
                return True
            else:
                print(f"⚠️ Handle {handle} 类型未支持修改: {obj.ObjectName}")
                return False
        except Exception as e:
            print(f"❌ 修改失败 (Handle: {handle}): {e}")
            return False
    # 初始化 AutoCAD
    # extract_text(doc)

    # 处理产品法规 → 替换到 handle 77872
    regulation_text = get_flang_jisuan_value(product_id, "法兰名义外径", flange)
    if regulation_text:
        modify_text_by_handle(doc,"325f", regulation_text)
        # modify_by_handle(doc,"12DE", regulation_text)

    regulation_text = get_flang_jisuan_value(product_id, "法兰名义内径", flange)
    if regulation_text:
        modify_text_by_handle(doc,"3260", regulation_text)
        regulation_text = f"∅{regulation_text}"
        # modify_by_handle(doc,"1302", regulation_text)

    regulation_text = get_flang_jisuan_value(product_id, "法兰名义内径", flange)
    regulation_text2 = get_flang_jisuan_value(product_id, "法兰颈部小端名义厚度", flange)
    regulation_text = float(regulation_text)+2*float(regulation_text2)
    if regulation_text:
        modify_text_by_handle(doc,"3262", regulation_text)
        regulation_text = f"∅{regulation_text}"
        # modify_by_handle(doc,"1309", regulation_text)
    regulation_text = get_flang_jisuan_value(product_id, "D2", flange)
    modify_text_by_handle(doc, "3282", regulation_text)
    regulation_text = get_flang_jisuan_value(product_id, "D3", flange)
    modify_text_by_handle(doc, "3289", regulation_text)

    regulation_text = get_flang_jisuan_value(product_id, "法兰名义内径", flange)
    regulation_text2 = get_flang_jisuan_value(product_id, "法兰颈部大端名义厚度", flange)
    regulation_text = float(regulation_text)+2*float(regulation_text2)
    if regulation_text:
        modify_text_by_handle(doc,"326a", regulation_text)
        regulation_text = f"∅{regulation_text}"
        # modify_by_handle(doc,"12E8", regulation_text)

    regulation_text = get_flang_jisuan_value(product_id, "法兰名义厚度", flange)
    if regulation_text:
        modify_text_by_handle(doc,"3263", regulation_text)
        # modify_by_handle(doc,"1312", regulation_text)

    regulation_text = get_flang_jisuan_value(product_id, "法兰颈部高度", flange)
    if regulation_text:
        modify_text_by_handle(doc,"3264", regulation_text)
        # modify_by_handle(doc,"12FD", regulation_text)

    regulation_text = get_flang_jisuan_value(product_id, "法兰总高", flange)
    if regulation_text:
        modify_text_by_handle(doc,"3265", regulation_text)
        # modify_by_handle(doc,"12DB", regulation_text)
    regulation_text = get_flang_jisuan_value(product_id, "螺栓数量", flange)
    regulation_text2 = get_flang_jisuan_value(product_id, "螺栓根径", flange)
    regulation_text = f"{regulation_text}-∅{round(float(regulation_text2))}"
    # modify_by_handle(doc, "1335", regulation_text)

    regulation_text = get_flang_jisuan_value(product_id, "螺栓数量", flange)
    if regulation_text:
        modify_text_by_handle(doc,"3267", regulation_text)

    regulation_text = get_flang_jisuan_value(product_id, "螺栓孔直径", flange)
    if regulation_text:
        modify_text_by_handle(doc,"3268", round(float(regulation_text)))
    regulation_text = get_flang_jisuan_value(product_id, "法兰直边段高度", flange)
    if regulation_text:
        modify_text_by_handle(doc,"326d", regulation_text)
        # modify_by_handle(doc,"1378", regulation_text)

    regulation_text = get_flang_jisuan_value(product_id, "螺栓中心圆直径", flange)
    if regulation_text:
        modify_text_by_handle(doc,"3261", regulation_text)
        regulation_text = f"∅{regulation_text}"
        # modify_by_handle(doc,"12DF", regulation_text)

    modify_text_by_handle(doc, "326e", flange)
    modify_text_by_handle(doc, "1a25", flange)
    regulation_text = get_flang_jisuan_value(product_id, "法兰总高", flange)
    # if regulation_text:
        # modify_by_handle(doc,"12DB", regulation_text)
    # extract_dimensions(doc)

    # === 连接数据库 ===
    # conn = pymysql.connect(
    #     host="localhost",
    #     user="root",
    #     password="123456",
    #     database="产品设计活动库",
    #     charset="utf8mb4"
    # )
    # cursor = conn.cursor()

    # # === 查询凹槽深度 ===
    # sql = """
    #     SELECT 参数值
    #     FROM 产品设计活动表_元件附加参数表
    #     WHERE 产品ID=%s AND 元件名称=%s AND 参数名称='凹槽深度'
    # """
    # cursor.execute(sql, (product_id, flange))
    # row = cursor.fetchone()
    # conn.close()
    #
    # if row:
    #     groove_depth = str(row[0])  # 取出凹槽深度
    #     # === 修改 CAD 文字 ===
    #     modify_by_handle(doc, "1315", groove_depth)
    #     print(f"✅ 已更新 Handle=1315 为凹槽深度: {groove_depth}")
    # else:
    #     print(f"⚠️ 未找到 {flange} 的凹槽深度")

