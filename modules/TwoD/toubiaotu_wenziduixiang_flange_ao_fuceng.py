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


FLANGE_COVER_GEN_RUNNING = False


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
    覆层法兰二维图生成：
    1. 模板只复制一次
    2. 只打开复制后的那一个副本
    3. 所有写入都落在这一个副本上
    """
    global FLANGE_COVER_GEN_RUNNING

    if FLANGE_COVER_GEN_RUNNING:
        print("⚠️ 覆层法兰图生成正在进行中，忽略重复调用")
        return None

    FLANGE_COVER_GEN_RUNNING = True

    conn_product = None
    conn_material = None
    connection = None
    conn_cover = None

    try:
        print(f"=== 开始生成覆层法兰图 === product_id={product_id}, flange={flange}, time={time.time()}")

        flange_origin = flange
        if flange == "前端管箱头盖法兰":
            flange = "头盖法兰"

        acad = get_autocad_instance()
        if acad is None:
            print("❌ 没有可用的 AutoCAD 实例")
            return None

        dwg_path = os.path.abspath("法兰凹-覆层.dwg")
        if not os.path.exists(dwg_path):
            print(f"❌ 模板文件不存在: {dwg_path}")
            return None

        # === 默认保存目录 ===
        save_dir = get_project_save_dir(product_id)
        if not save_dir:
            save_dir = os.path.join(os.getcwd(), "exports")
        save_dir = os.path.abspath(save_dir)
        os.makedirs(save_dir, exist_ok=True)

        # === 只复制一次模板 ===
        target_dwg = copy_template_to_target(dwg_path, save_dir, flange)
        print(f"✅ 已创建目标副本: {target_dwg}")

        # === 清理 AutoCAD 空白图 ===
        close_temp_drawings(acad)

        # === 避免同一路径重复打开 ===
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

        def _to_float(v, default=None):
            if v is None:
                return default
            s = str(v).strip()
            if s == "" or s.lower() == "none":
                return default
            m = re.search(r"[-+]?\d+(\.\d+)?", s)
            if not m:
                return default
            try:
                return float(m.group(0))
            except Exception:
                return default

        def _fetch_design_value_pair(cur, product_id_, name_like):
            cur.execute(
                """
                SELECT *
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s AND 参数名称 LIKE %s
                LIMIT 1
                """,
                (product_id_, name_like)
            )
            return cur.fetchone() or {}

        # =========================
        # 写入基本参数
        # =========================
        regulation_text = get_flang_jisuan_value(product_id, "法兰名义外径", flange)
        if regulation_text:
            safe_modify(doc, "325f", regulation_text)

        regulation_text = get_flang_jisuan_value(product_id, "法兰名义内径", flange)
        if regulation_text:
            safe_modify(doc, "3260", regulation_text)

        regulation_text = get_flang_jisuan_value(product_id, "法兰名义内径", flange)
        regulation_text2 = get_flang_jisuan_value(product_id, "法兰颈部小端名义厚度", flange)
        try:
            regulation_value = float(regulation_text) + 2 * float(regulation_text2)
            safe_modify(doc, "3262", regulation_value)
        except Exception:
            pass

        regulation_text = get_flang_jisuan_value(product_id, "D2", flange)
        if regulation_text:
            safe_modify(doc, "3282", regulation_text)

        regulation_text = get_flang_jisuan_value(product_id, "D3", flange)
        if regulation_text:
            safe_modify(doc, "3289", regulation_text)

        regulation_text = get_flang_jisuan_value(product_id, "法兰名义内径", flange)
        regulation_text2 = get_flang_jisuan_value(product_id, "法兰颈部大端名义厚度", flange)
        try:
            regulation_value = float(regulation_text) + 2 * float(regulation_text2)
            safe_modify(doc, "326a", regulation_value)
        except Exception:
            pass

        regulation_text = get_flang_jisuan_value(product_id, "法兰名义厚度", flange)
        if regulation_text:
            safe_modify(doc, "3263", regulation_text)

        regulation_text = get_flang_jisuan_value(product_id, "法兰颈部高度", flange)
        if regulation_text:
            safe_modify(doc, "3264", regulation_text)

        regulation_text = get_flang_jisuan_value(product_id, "法兰总高", flange)
        if regulation_text:
            safe_modify(doc, "3265", regulation_text)

        regulation_text = get_flang_jisuan_value(product_id, "螺栓数量", flange)
        if regulation_text:
            safe_modify(doc, "3267", regulation_text)

        regulation_text = get_flang_jisuan_value(product_id, "螺栓孔直径", flange)
        if regulation_text:
            safe_modify(doc, "3268", round(float(regulation_text)))

        regulation_text = get_flang_jisuan_value(product_id, "法兰直边段高度", flange)
        if regulation_text:
            safe_modify(doc, "326d", regulation_text)

        regulation_text = get_flang_jisuan_value(product_id, "法兰毛坯质量", flange)
        if regulation_text:
            safe_modify(doc, "332c", round(float(regulation_text), 2))

        regulation_text = get_flang_jisuan_value(product_id, "法兰成型质量", flange)
        if regulation_text:
            safe_modify(doc, "3385", round(float(regulation_text), 2))

        regulation_text = get_flang_jisuan_value(product_id, "螺栓中心圆直径", flange)
        if regulation_text:
            safe_modify(doc, "3261", regulation_text)

        # =========================
        # 查询并写入 R
        # =========================
        conn_product = pymysql.connect(
            host="localhost",
            user="root",
            password="123456",
            database="产品设计活动库",
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor
        )
        conn_material = pymysql.connect(
            host="localhost",
            user="root",
            password="123456",
            database="材料库",
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor
        )

        cur_p = conn_product.cursor()
        cur_m = conn_material.cursor()

        row_dn = _fetch_design_value_pair(cur_p, product_id, "公称直径%")
        row_pn = _fetch_design_value_pair(cur_p, product_id, "设计压力%")

        dn_tube = _to_float(row_dn.get("管程数值"))
        dn_shell = _to_float(row_dn.get("壳程数值"))
        pn_tube = _to_float(row_pn.get("管程数值"))
        pn_shell = _to_float(row_pn.get("壳程数值"))

        flange_s = str(flange or "")
        if "管箱" in flange_s:
            DN = dn_tube
            PN = pn_tube
        elif ("外头盖" in flange_s) or ("壳体" in flange_s):
            DN = dn_shell
            PN = pn_shell
        else:
            DN = dn_tube if dn_tube is not None else dn_shell
            PN = pn_tube if pn_tube is not None else pn_shell

        if DN is None or PN is None:
            print(f"⚠️ DN/PN 取值失败：DN={DN}, PN={PN}, flange={flange}")
        else:
            cur_m.execute("SELECT DISTINCT DN FROM 法兰结构形式及尺寸表 ORDER BY DN ASC")
            dn_list = [float(r["DN"]) for r in (cur_m.fetchall() or []) if r.get("DN") is not None]

            if dn_list:
                if DN not in dn_list:
                    bigger_dns = [x for x in dn_list if x > DN]
                    DN_use = min(bigger_dns) if bigger_dns else max(dn_list)
                else:
                    DN_use = DN
            else:
                DN_use = DN

            cur_m.execute(
                """
                SELECT DISTINCT PN
                FROM 法兰结构形式及尺寸表
                WHERE DN = %s
                ORDER BY PN ASC
                """,
                (DN_use,)
            )
            pn_list = [float(r["PN"]) for r in (cur_m.fetchall() or []) if r.get("PN") is not None]

            if pn_list:
                if PN not in pn_list:
                    bigger_pns = [x for x in pn_list if x > PN]
                    PN_use = min(bigger_pns) if bigger_pns else max(pn_list)
                else:
                    PN_use = PN
            else:
                PN_use = PN

            cur_m.execute(
                """
                SELECT R
                FROM 法兰结构形式及尺寸表
                WHERE DN = %s AND PN = %s
                LIMIT 1
                """,
                (DN_use, PN_use)
            )
            r_row = cur_m.fetchone()
            R = r_row.get("R") if r_row else None

            if R is not None and str(R).strip() != "":
                safe_modify(doc, "18db", str(R).strip())
                print(f"✅ 写入 18db: R={R} (DN={DN_use}, PN={PN_use}, flange={flange})")
            else:
                print(f"⚠️ 未在表中找到 R：DN={DN_use}, PN={PN_use}")

        # =========================
        # 写入法兰名称
        # =========================
        safe_modify(doc, "326e", flange)
        safe_modify(doc, "1a25", flange)

        # =========================
        # 查询材料与覆层
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

        fucengcailiao = ""

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

            cursor.execute("""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = %s
                  AND 参数名称 IN ('是否添加覆层', '覆层材料牌号')
            """, (product_id, flange_origin))
            fuceng_rows = cursor.fetchall()

            if fuceng_rows:
                fuceng_map = {r["参数名称"]: r["参数值"] for r in fuceng_rows}
                if fuceng_map.get("是否添加覆层") == "是" and fuceng_map.get("覆层材料牌号"):
                    fucengcailiao = fuceng_map["覆层材料牌号"]

            sql_param = """
                SELECT 元件名称, 参数名称, 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s
                  AND 参数名称 IN ('锻件级别', '材料类型')
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
                material = f"{material}{forging_level_map[row['元件名称']]}{fucengcailiao}"
            else:
                material = f"{material}{fucengcailiao}" if material else fucengcailiao

            if material:
                safe_modify(doc, "332b", material)

        # =========================
        # 查询并写入覆层厚度
        # =========================
        conn_cover = pymysql.connect(
            host="localhost",
            user="root",
            password="123456",
            database="产品设计活动库",
            charset="utf8mb4"
        )

        with conn_cover.cursor() as cursor_cover:
            sql = """
                SELECT 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = %s AND 参数名称 = '覆层厚度'
            """
            cursor_cover.execute(sql, (product_id, flange_origin))
            row = cursor_cover.fetchone()

        if row:
            cover_thickness = str(row[0])
            safe_modify(doc, "18ed", cover_thickness)
            print(f"✅ 已更新 Handle=18ed 覆层厚度: {cover_thickness}")
        else:
            print(f"⚠️ 未找到 {flange} 覆层厚度")

        # 最后只保存当前副本
        save_current_doc(doc)

        print(f"🔹 覆层法兰 {flange} 生成完成，准备返回 COM 对象")
        return doc

    except Exception as e:
        print(f"❌ twoDgeneration 执行失败: {e}")
        traceback.print_exc()
        return None

    finally:
        FLANGE_COVER_GEN_RUNNING = False

        try:
            if conn_product:
                conn_product.close()
        except Exception:
            pass

        try:
            if conn_material:
                conn_material.close()
        except Exception:
            pass

        try:
            if connection:
                connection.close()
        except Exception:
            pass

        try:
            if conn_cover:
                conn_cover.close()
        except Exception:
            pass