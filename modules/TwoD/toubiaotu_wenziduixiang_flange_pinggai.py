import datetime
import json
import re
import shutil
import subprocess
import tempfile
import time
import traceback
import os
import configparser

import chardet
import openpyxl
import pymysql
import win32com.client
from pyautocad import Autocad

from modules.TwoD.cad_context import CAD_CTX


from modules.TwoD.TwoD_peizhi import (
    get_project_save_dir,
    get_autocad_instance,
    _find_open_doc,
    wait_cad_idle,
    refresh_doc,
    open_drawing_with_wait,
    ensure_dwg_path,
    must_exist_file,
    safe_modify,
    copy_template_to_target
)
from modules.TwoD.toubiaotu_biaozhu import extract_dimensions
from modules.chanpinguanli.chanpinguanli_main import product_manager
from modules.wenbenshengcheng import cunguige
from modules.wenbenshengcheng.cunguige import get_value, load_json_data
from modules.wenbenshengcheng.generate_material_list import generate_material_list


FLAT_COVER_GEN_RUNNING = False


def close_temp_drawings(acad):
    """
    关闭 AutoCAD 自动生成的空白图纸，例如 Drawing1 / Drawing2
    """
    try:
        docs_to_close = []
        for i in range(acad.Documents.Count):
            doc_i = acad.Documents.Item(i)
            name = (getattr(doc_i, "Name", "") or "").lower()
            full = (getattr(doc_i, "FullName", "") or "").strip()
            if name.startswith("drawing") and not full:
                docs_to_close.append(doc_i)

        for d in docs_to_close:
            try:
                d.Close(False)
            except Exception:
                pass
    except Exception as e:
        print(f"⚠️ 关闭临时空白图纸失败: {e}")


def close_doc_if_open(acad, file_path):
    """
    如果目标文件已经打开，先关闭，避免重复打开同一路径
    """
    try:
        target = os.path.normcase(os.path.normpath(os.path.abspath(file_path)))
        docs_to_close = []

        for i in range(acad.Documents.Count):
            d = acad.Documents.Item(i)
            full = getattr(d, "FullName", "") or ""
            if full:
                full_norm = os.path.normcase(os.path.normpath(os.path.abspath(full)))
                if full_norm == target:
                    docs_to_close.append(d)

        for d in docs_to_close:
            try:
                d.Close(False)
            except Exception:
                pass
    except Exception as e:
        print(f"⚠️ 关闭已打开目标图失败: {e}")


def get_current_doc():
    """
    优先从共享上下文 CAD_CTX 获取当前文档
    """
    doc = CAD_CTX.get("doc")
    if doc is not None:
        try:
            _ = getattr(doc, "Name", None)
            return doc
        except Exception:
            pass

    target_dwg = CAD_CTX.get("target_dwg")
    if target_dwg:
        try:
            acad = get_autocad_instance()
            if acad is not None:
                target = os.path.normcase(os.path.normpath(os.path.abspath(target_dwg)))
                for i in range(acad.Documents.Count):
                    d = acad.Documents.Item(i)
                    full = getattr(d, "FullName", "") or ""
                    if full:
                        full = os.path.normcase(os.path.normpath(os.path.abspath(full)))
                        if full == target:
                            CAD_CTX["doc"] = d
                            return d
        except Exception:
            pass

    try:
        acad = get_autocad_instance()
        if acad is not None:
            return acad.ActiveDocument
    except Exception as e:
        print(f"⚠️ 获取当前文档失败: {e}")

    return None


def save_current_doc(doc=None):
    """
    只保存当前已打开的这一份副本，不另存为第二份
    """
    if doc is None:
        doc = get_current_doc()

    if doc is None:
        print("⚠️ 没有可保存的当前文档")
        return False

    try:
        try:
            doc.Regen()
            time.sleep(0.3)
        except Exception:
            pass

        doc.Save()
        print(f"✅ 当前图纸已保存: {getattr(doc, 'FullName', getattr(doc, 'Name', '未命名图纸'))}")
        return True
    except Exception as e:
        print(f"❌ 保存当前图纸失败: {e}")
        return False


def twoDgeneration(product_id, flange):
    """
    管箱平盖二维图生成：
    1. 模板只复制一次
    2. 只打开复制后的那一个副本
    3. 所有写入都落在这一份副本上
    """
    global FLAT_COVER_GEN_RUNNING

    if FLAT_COVER_GEN_RUNNING:
        print("⚠️ 管箱平盖图生成正在进行中，忽略重复调用")
        return None

    FLAT_COVER_GEN_RUNNING = True
    connection = None

    try:
        print(f"=== 开始生成管箱平盖图 === product_id={product_id}, flange={flange}, time={time.time()}")

        flange_origin = flange
        if flange == "前端管箱平盖":
            flange = "管箱平盖"

        acad = get_autocad_instance()
        if acad is None:
            print("❌ 没有可用的 AutoCAD 实例")
            return None

        template_path = os.path.abspath("管箱平盖.dwg")
        if not os.path.exists(template_path):
            print(f"❌ 模板文件不存在: {template_path}")
            return None

        # === 默认保存目录 ===
        save_dir = get_project_save_dir(product_id)
        if not save_dir:
            save_dir = os.path.join(os.getcwd(), "exports")
        save_dir = os.path.abspath(save_dir)
        os.makedirs(save_dir, exist_ok=True)

        # === 只复制一次模板 ===
        target_dwg = copy_template_to_target(template_path, save_dir, flange)
        print(f"✅ 已创建目标副本: {target_dwg}")

        # === 清理空白图纸 ===
        close_temp_drawings(acad)

        # === 若目标已开，先关闭 ===
        close_doc_if_open(acad, target_dwg)

        # === 打开目标副本 ===
        wait_cad_idle(acad, timeout=20)
        acad, doc = open_drawing_with_wait(target_dwg)
        if doc is None:
            print("❌ 打开目标图失败:", target_dwg)
            return None

        # === 写入共享上下文 ===
        CAD_CTX["product_id"] = product_id
        CAD_CTX["save_dir"] = save_dir
        CAD_CTX["target_dwg"] = target_dwg
        CAD_CTX["doc"] = doc

        wait_cad_idle(acad, timeout=30)
        refresh_doc(doc)
        print(f"✅ 成功打开唯一副本: {target_dwg}")

        def get_flange_value(product_id_, param_name, flange_name):
            conn = pymysql.connect(
                host='localhost',
                user='root',
                password='123456',
                database='产品设计活动库',
                charset='utf8mb4'
            )
            try:
                with conn.cursor() as cursor:
                    sql = """
                        SELECT `参数值`
                        FROM `产品设计活动表_元件附加参数表`
                        WHERE `产品ID` = %s AND `参数名称` = %s AND `元件名称` = %s
                    """
                    cursor.execute(sql, (product_id_, param_name, flange_name))
                    row = cursor.fetchone()
                    if row:
                        return str(row[0] or "")
                    else:
                        print(f"未找到 产品ID={product_id_} 法兰={flange_name}")
                        return ""
            finally:
                conn.close()

        def get_flang_jisuan_value(product_id_, param_name, flange_name):
            conn = pymysql.connect(
                host='localhost',
                user='root',
                password='123456',
                database='产品设计活动库',
                charset='utf8mb4'
            )
            try:
                with conn.cursor() as cursor:
                    sql = """
                        SELECT `Value`
                        FROM `产品设计活动表_元件计算结果表`
                        WHERE `产品ID` = %s AND `元件名称` = %s AND `Name` = %s
                        LIMIT 1
                    """
                    cursor.execute(sql, (product_id_, flange_name, param_name))
                    row = cursor.fetchone()
                    if row:
                        return str(row[0] or "")
                    else:
                        print(f"未找到 产品ID={product_id_} 法兰={flange_name}")
                        return ""
            finally:
                conn.close()

        def extract_text(doc_, retries=10, delay=1):
            print("【文字对象】提取中...")
            for attempt in range(retries):
                try:
                    for obj in doc_.ModelSpace:
                        if obj.ObjectName in ['AcDbText', 'AcDbMText']:
                            print(
                                f"{obj.ObjectName}: '{obj.TextString}' 位置: {obj.InsertionPoint} 图层: {obj.Layer} Handle: {obj.Handle}"
                            )
                    return
                except Exception as e:
                    print(f"⚠️ 第 {attempt + 1} 次尝试失败: {e}")
                    time.sleep(delay)
            print("❌ 超过最大尝试次数，无法访问 ModelSpace")

        def get_obj_safe(doc_, handle, retries=3, delay=1):
            for attempt in range(retries):
                try:
                    obj = doc_.HandleToObject(handle)
                    if obj:
                        return obj
                except Exception as e:
                    print(f"⚠️ 第 {attempt + 1} 次尝试获取 Handle {handle} 失败: {e}")
                time.sleep(delay)
            print(f"❌ Handle {handle} 最终无法获取")
            return None

        # =========================
        # 写入基本参数
        # =========================
        regulation_text = get_flang_jisuan_value(product_id, "法兰名义外径", flange)
        if regulation_text:
            safe_modify(doc, "15AE", regulation_text)

        regulation_text = get_flang_jisuan_value(product_id, "法兰名义内径", "头盖法兰")
        if regulation_text:
            safe_modify(doc, "15AD", regulation_text)

        regulation_text = get_flang_jisuan_value(product_id, "D4", flange)
        if regulation_text:
            safe_modify(doc, "15B2", regulation_text)

        regulation_text = get_flang_jisuan_value(product_id, "D2", flange)
        if regulation_text:
            safe_modify(doc, "130f3", regulation_text)

        regulation_text = get_flang_jisuan_value(product_id, "D3", flange)
        if regulation_text:
            safe_modify(doc, "130fa", regulation_text)

        regulation_text = get_flang_jisuan_value(product_id, "法兰名义内径", "头盖法兰")
        try:
            regulation_value = int(float(regulation_text)) - 3
            safe_modify(doc, "15B3", regulation_value)
        except Exception:
            pass

        regulation_text = get_flang_jisuan_value(product_id, "法兰名义厚度", flange)
        if regulation_text:
            safe_modify(doc, "15B4", regulation_text)

        regulation_text = get_flang_jisuan_value(product_id, "法兰毛坯质量", flange)
        if regulation_text:
            safe_modify(doc, "1319d", round(float(regulation_text), 2))

        regulation_text = get_flang_jisuan_value(product_id, "法兰成型质量", flange)
        if regulation_text:
            safe_modify(doc, "131fe", round(float(regulation_text), 2))

        regulation_text = get_flang_jisuan_value(product_id, "螺栓数量", flange)
        if regulation_text:
            safe_modify(doc, "15B8", regulation_text)

        regulation_text = get_flang_jisuan_value(product_id, "螺栓孔直径", flange)
        if regulation_text:
            safe_modify(doc, "15B9", round(float(regulation_text)))

        regulation_text = get_flang_jisuan_value(product_id, "螺栓中心圆直径", flange)
        if regulation_text:
            safe_modify(doc, "15AF", regulation_text)
            print("regulationtest", f"∅{regulation_text}")

        safe_modify(doc, "18CB", flange)
        safe_modify(doc, "1B11", flange)

        # =========================
        # 材料信息
        # =========================
        connection = pymysql.connect(
            host='localhost',
            port=3306,
            user='root',
            password='123456',
            database='产品设计活动库',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )

        with connection.cursor() as cursor:
            sql = """
                SELECT 元件名称, 材料类型, 材料牌号, 材料标准, 供货状态
                FROM 产品设计活动表_元件材料表
                WHERE 产品ID = %s AND 元件名称 = %s
            """
            cursor.execute(sql, (product_id, flange_origin))
            rows = cursor.fetchall()

            if not rows:
                print(f"⚠️ 未找到产品ID {product_id} 的材料数据")
                save_current_doc(doc)
                return doc

            sql_param = """
                SELECT 元件名称, 参数名称, 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s
                  AND 参数名称 IN ('锻件级别','材料类型')
                  AND 元件名称 = %s
                  AND 参数值 IS NOT NULL AND 参数值 <> ''
            """
            cursor.execute(sql_param, (product_id, flange_origin))
            param_rows = cursor.fetchall()

            material = None
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

            row = None
            for idx, row in enumerate(rows):
                material = "/" if row["材料牌号"] == "见参数定义" else row["材料牌号"]

            if row and row["元件名称"] in forging_level_map:
                material = f"{material}{forging_level_map[row['元件名称']]}"

            if material is not None:
                safe_modify(doc, "1319c", material)

        # 最后只保存当前副本
        save_current_doc(doc)

        print(f"🔹 法兰 {flange} 生成完成，准备返回 COM 对象")
        return doc

    except Exception as e:
        print(f"❌ twoDgeneration 执行失败: {e}")
        traceback.print_exc()
        return None

    finally:
        FLAT_COVER_GEN_RUNNING = False

        try:
            if connection:
                connection.close()
        except Exception:
            pass