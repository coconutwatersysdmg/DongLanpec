import json
import os
import re
from collections import defaultdict

import chardet
import configparser
from openpyxl import load_workbook

import json
from openpyxl import load_workbook
import pymysql
from openpyxl.cell import MergedCell

from modules.chanpinguanli.chanpinguanli_main import product_manager
from modules.wenbenshengcheng.CalculateReport import generate_calReport
from modules.wenbenshengcheng.calculation_report_empty_sheets import (
    delete_empty_component_report_sheets,
)
from modules.wenbenshengcheng.db_cnt import get_connection

product_id = None


def on_product_id_changed(new_id):
    print(f"Received new PRODUCT_ID: {new_id}")
    global product_id
    product_id = new_id


# 测试用产品 ID（真实情况中由外部输入）
product_manager.product_id_changed.connect(on_product_id_changed)

def get_weld_area(product_id):
    db_config = {
        "host": "localhost",
        "user": "root",
        "password": "123456",
        "database": "产品设计活动库",
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor
    }
    conn = pymysql.connect(**db_config)
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 参数值 
                FROM 产品设计活动表_管口零件材料参数表 
                WHERE 产品ID = %s AND 参数名称 = '焊缝金属截面积'
            """, (product_id,))
            row = cursor.fetchone()
            return row["参数值"] if row and row["参数值"].strip() else "0"
    finally:
        conn.close()
def get_jietouxishu_data(product_id):
    db_config = {
        "host": "localhost",
        "user": "root",
        "password": "123456",
        "database": "产品设计活动库",
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor
    }
    conn = pymysql.connect(**db_config)
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 管程数值 
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s AND 参数名称 = "焊接接头系数*"
            """, (product_id,))
            row = cursor.fetchone()
            return row["管程数值"] if row and row["管程数值"].strip() else "0"
    finally:
        conn.close()
def get_pinggai_data(product_id):
    db_config = {
        "host": "localhost",
        "user": "root",
        "password": "123456",
        "database": "产品设计活动库",
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor
    }
    conn = pymysql.connect(**db_config)
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 参数值 
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = "管箱平盖" AND 参数名称 = '覆层材料牌号'
            """, (product_id,))
            row = cursor.fetchone()
            if row and row.get("参数值") not in (None, "", "None"):
                return row["参数值"].strip()
            else:
                return "0"
    finally:
        conn.close()
def get_guanban_data(product_id):
    db_config = {
        "host": "localhost",
        "user": "root",
        "password": "123456",
        "database": "产品设计活动库",
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor
    }
    conn = pymysql.connect(**db_config)
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 参数值 
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = "固定管板" AND 参数名称 = '管板凸台高度'
            """, (product_id,))
            row = cursor.fetchone()
            if row and row.get("参数值") not in (None, "", "None"):
                return row["参数值"].strip()
            else:
                return "0"
    finally:
        conn.close()

def fill_calculation_report(json_path, excel_path, output_path):
    with open(json_path, "r", encoding="utf-8") as f:
        json_data = json.load(f)

    dict_out_data = json_data.get("DictOutDatas", {})
    wb = load_workbook(excel_path)

    # -----------------------------
    # 特殊处理：接管模板
    # -----------------------------
    pipe_modules = []
    if "接管" in wb.sheetnames:
        template_sheet = wb["接管"]
        # 找出 JSON 中所有名称包含 "接管" 的模块
        pipe_modules = [k for k in dict_out_data.keys() if "接管" in k]
        for module_name in pipe_modules:
            if module_name in wb.sheetnames:
                continue
            new_sheet = wb.copy_worksheet(template_sheet)
            new_sheet.title = module_name

        # 删除接管模板
        std = wb["接管"]
        wb.remove(std)

    # -----------------------------
    # 遍历工作表填充数据
    # -----------------------------
    for sheet_name in wb.sheetnames:
        if sheet_name not in dict_out_data:
            print(f"⚠️ JSON 中未找到模块：{sheet_name}，跳过该表")
            continue

        module_data = dict_out_data.get(sheet_name)
        if not module_data:
            print(f"⚠️ 模块 {sheet_name} 数据为空，跳过写入")
            return  # 或 continue

        datas = module_data.get("Datas") or []

        sheet = wb[sheet_name]
        print(f"✅ 正在写入模块：{sheet_name}")

        # 清空 A/B/C 列
        for row in sheet.iter_rows(min_row=2):
            for cell in row[:3]:
                cell.value = None

        # 写入 A/B/C 列
        for idx, item in enumerate(datas, start=2):
            sheet.cell(row=idx, column=1, value=item.get("Id", ""))
            sheet.cell(row=idx, column=2, value=item.get("Name", ""))
            sheet.cell(row=idx, column=3, value=item.get("Value", ""))

        # -----------------------------
        # 封头统一处理（半球/碟形 → 椭圆形）
        # -----------------------------
        # -----------------------------
        # 封头统一处理（半球/碟形 → 椭圆形 + 精确替换规则）
        # -----------------------------
        if "封头" in sheet_name:
            print(f"🔧 检测到封头工作表：{sheet_name}，正在执行名称统一与特定替换")

            for row in sheet.iter_rows(min_row=2, min_col=2, max_col=2):
                cell = row[0]
                if not cell.value:
                    continue

                text = str(cell.value)

                # -----------------------------------------
                # ① 先进行封头类型统一：半球形/碟形 → 椭圆形
                # -----------------------------------------
                text = text.replace("半球形封头", "椭圆形封头")
                text = text.replace("碟形封头", "椭圆形封头")

                # -----------------------------------------
                # ② 再进行封头字段精确替换（按你给的全部规则）
                # -----------------------------------------
                replacements = {
                    "椭圆形封头计算内圆直径": "椭圆形封头计算内径",
                    "椭圆形封头外圆直径": "椭圆形封头计算外径",
                    "球壳内半径": "椭圆形封头内曲面深度",
                    "球壳外半径": "椭圆形封头外曲面深度",
                    "径比K=Do/Di": "椭圆形封头形状系数K",
                    "材料标准室温屈服强度": "材料试验温度下屈服强度",
                    "椭圆形封头耐压试验类型": "耐压试验类型",
                    "椭圆形封头耐压试验值": "椭圆形封头耐压试验压力",
                    "椭圆形封头试验压力下的计算应力": "椭圆形封头压力试验下的计算应力",
                    "椭圆形封头计算厚度": "椭圆形封头内压强度计算厚度"
                }

                for old, new in replacements.items():
                    text = text.replace(old, new)

                # 回写修改后的文本
                cell.value = text

    wb.save(output_path)
    print(f"✅ 综合填充完成，保存为：{output_path}")
#         return "是"
#     elif str(val).lower() == "false":
#         return "否"
#     return val  # 其他值保持不变

MODULE_TO_SHEET_MAP = {
    "管箱法兰": "管箱法兰",
    "壳体法兰": "壳体法兰",
    "管箱平盖": "管箱平盖",
    "壳体平盖": "壳体平盖",
    "平盖": "管箱平盖",   # ✅
}



def write_flange_values(intermediate_excel_path, target_wb):
    from openpyxl import load_workbook
    from collections import defaultdict

    inter_wb = load_workbook(intermediate_excel_path, data_only=True)

    for sheet in inter_wb.worksheets:
        rows = list(sheet.iter_rows(min_row=2))
        id_name_value_list = [(str(r[0].value).strip(), str(r[1].value).strip(), r[2].value)
                              for r in rows if r[0].value and r[1].value]

        # 获取归属定义
        m_NameFl_raw = None
        m_NameFl2_raw = None
        for id_, name, value in id_name_value_list:
            if id_ == "m_NameFl":
                m_NameFl_raw = str(value).strip()
            elif id_ == "m_NameFl2":
                m_NameFl2_raw = str(value).strip()

        if not m_NameFl_raw or not m_NameFl2_raw:
            print(f"⚠️ `{sheet.title}` 缺少 m_NameFl 或 m_NameFl2，跳过")
            continue

        # 做映射
        m_NameFl_val = MODULE_TO_SHEET_MAP.get(m_NameFl_raw, m_NameFl_raw)
        m_NameFl2_val = MODULE_TO_SHEET_MAP.get(m_NameFl2_raw, m_NameFl2_raw)

        # 分组
        short_id_items = defaultdict(str)
        long_id_items = defaultdict(str)

        for id_, name, value in id_name_value_list:
            if id_ in ("m_NameFl", "m_NameFl2"):
                continue
            if id_.endswith("2"):
                long_id_items[name] = value
            else:
                short_id_items[name] = value

        # 写入短 ID（m_NameFl 对应模块）
        if m_NameFl_val in target_wb.sheetnames:
            sheet1 = target_wb[m_NameFl_val]
            for name, value in short_id_items.items():
                _write_to_sheet_by_name(sheet1, name, value)
        else:
            print(f"❌ 未找到目标 sheet：{m_NameFl_val}")

        # 写入长 ID（m_NameFl2 对应模块）
        if m_NameFl2_val in target_wb.sheetnames:
            sheet2 = target_wb[m_NameFl2_val]
            for name, value in long_id_items.items():
                _write_to_sheet_by_name(sheet2, name, value)
        else:
            print(f"❌ 未找到目标 sheet：{m_NameFl2_val}")

        print(f"✅ `{sheet.title}` 字段写入完成 → {m_NameFl_val} / {m_NameFl2_val}")


def _write_to_sheet_by_name(sheet, name, value):
    for row in sheet.iter_rows(min_row=2):
        if str(row[2].value).strip() == name:
            row[3].value = value
            return


# === 仅这些字段允许做 “是/否” 映射 ===
bool_field_names = {
    "是否以外径为基准",
    "Pt与Ps是否同时作用",
    "是否需要另加补强",
    "结论",
    "校核条件"
}

def fill_final_excel_from_intermediate(intermediate_excel_path, target_excel_path, output_excel_path, json_path):
    import json
    import shutil
    import os
    import re
    import pymysql
    import xlwings as xw
    from collections import defaultdict

    from openpyxl import load_workbook
    from openpyxl.cell.cell import Cell
    from openpyxl.cell.cell import MergedCell

    # === 用户提供 product_id 外部变量 ===
    global product_id
    print("office")
    # =========================
    # 工具函数（保持你原逻辑）
    # =========================
    def get_weld_area(product_id):
        conn = pymysql.connect(
            host="localhost",
            user="root",
            password="123456",
            database="产品设计活动库",
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT 参数值 
                    FROM 产品设计活动表_元件附加参数表
                    WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '焊缝金属截面积A3'
                """, (product_id,))
                row = cursor.fetchone()
                return str(row["参数值"]) if row and row["参数值"] not in (None, "", "None") else "0"
        finally:
            conn.close()

    def auto_map_bool(val):
        if str(val).strip() in ("True", "true", "1"):
            return "是"
        if str(val).strip() in ("False", "false", "0"):
            return "否"
        return val

    def copy_nominal_thickness(sheet_from, sheet_to, wb):
        try:
            if sheet_from not in wb.sheetnames:
                print(f"⚠️ 源工作表 '{sheet_from}' 不存在，跳过")
                return
            if sheet_to not in wb.sheetnames:
                print(f"⚠️ 目标工作表 '{sheet_to}' 不存在，跳过")
                return

            source_value = None
            for row in wb[sheet_from].iter_rows(min_row=1):
                if len(row) >= 4 and str(row[2].value).strip() == "名义厚度δn":
                    source_value = row[3].value
                    break

            if source_value is None:
                print(f"⚠️ 未在工作表 '{sheet_from}' 中找到“名义厚度δn”")
                return

            matched = False
            for row in wb[sheet_to].iter_rows(min_row=1):
                if len(row) >= 4 and str(row[2].value).strip() == "名义厚度δn":
                    row[3].value = source_value
                    matched = True
                    print(f"🔁 已将 '{sheet_from}' 中“名义厚度δn”={source_value} 写入 '{sheet_to}'")
                    break

            if not matched:
                print(f"⚠️ 未在工作表 '{sheet_to}' 中找到“名义厚度δn”，未能写入")
        except Exception as e:
            print(f"❌ 处理过程中出现错误：{e}")

    def write_flange_values(intermediate_excel_path, target_wb_inner):
        inter_wb_local = load_workbook(intermediate_excel_path, data_only=True)
        try:
            for sheet in inter_wb_local.worksheets:
                rows = list(sheet.iter_rows(min_row=2))
                id_name_value_list = [
                    (str(r[0].value).strip(), str(r[1].value).strip(), r[2].value)
                    for r in rows if r[0].value and r[1].value
                ]
                name_val_map = {name: val for _, name, val in id_name_value_list}
                if sheet.title in target_wb_inner.sheetnames:
                    target_sheet = target_wb_inner[sheet.title]
                    for row in target_sheet.iter_rows(min_row=2):
                        name_cell = row[0]
                        val_cell = row[3]
                        if name_cell.value and (val_cell.value is None or str(val_cell.value).strip() == ""):
                            name = str(name_cell.value).strip()
                            matched_key = None
                            matched_value = None
                            for candidate in (name, f"{name}（替）", f"{name}(替)"):
                                if candidate in name_val_map:
                                    matched_key = candidate
                                    matched_value = name_val_map[candidate]
                                    break

                            if matched_key is not None:
                                val_cell.value = matched_value
        finally:
            inter_wb_local.close()

    # ================
    # 读取 JSON 结论
    # ================
    with open(json_path, "r", encoding="utf-8") as f:
        json_data = json.load(f)
    dict_out_data = json_data.get("DictOutDatas", {})
    module_success_map = {
        name: data.get("IsSuccess", False)
        for name, data in dict_out_data.items()
        if isinstance(data, dict)
    }

    # ================
    # 读取中间 Excel
    # ================
    inter_wb = load_workbook(intermediate_excel_path, data_only=True)

    def extract_case_label(id_val):
        s = str(id_val or "").strip()
        m = re.match(r"^(工况\s*\d+)\s*[：:]\s*(.*)$", s)
        if m:
            return m.group(1).replace(" ", ""), m.group(2).strip()
        return "工况1", s

    # =======================================
    # ⭐关键改动：用 inter_data_map_all 保存三层
    # inter_data_map_all[case][sheet][name] = value
    # =======================================
    inter_data_map_all = defaultdict(lambda: defaultdict(dict))
    inter_row_map_all = defaultdict(lambda: defaultdict(list))  # ⭐新增：保留逐行 id/name/value
    case_order = []
    case_seen = set()

    for sheet in inter_wb.worksheets:
        for row in sheet.iter_rows(min_row=2):
            id_val = row[0].value
            name = row[1].value
            value = row[2].value
            if not name:
                continue

            case_label, pure_id_val = extract_case_label(id_val)

            if case_label not in case_seen:
                case_seen.add(case_label)
                case_order.append(case_label)

            # 同一工况内同名字段只取第一次
            if name not in inter_data_map_all[case_label][sheet.title]:
                inter_data_map_all[case_label][sheet.title][name] = value

            # ⭐保留逐行原始信息，供“接管校核 / 小端校核”分流使用
            inter_row_map_all[case_label][sheet.title].append({
                "id_val": str(pure_id_val or "").strip(),
                "name": str(name).strip(),
                "value": value
            })

    case_labels = case_order or ["工况1"]
    print("✅ 识别到工况：", case_labels)

    # ======================
    # 字段映射（原样保留）
    # ======================
    field_reverse_maps = {
        "换热管排列方式(0:30°;1:60°;2:90°;3:45°)": {"0": "正三角形", "1": "转角正三角形", "2": "正方形", "3": "转角正方形"},
        "开孔所属位置": {"1": "圆筒", "2": "椭圆形封头", "3": "锥形封头或锥壳", "4": "平封头(平板）", "5": "碟形封头", "6": "球壳"},
        "接管类型": {"1": "圆形", "2": "椭圆形或长圆孔"},
        "开孔方位": {"1": "径向", "2": "斜向", "3": "切向或偏心"},
        "补强类型": {
            "1": "增加筒体厚度", "2": "增加接管厚度", "3": "补强圈补强", "4": "嵌入式接管补强",
            "5": "筒体和接管联合补强", "6": "接管和补强圈联合补强", "7": "筒体和补强圈联合补强", "8": "筒体和接管和补强圈联合补强"
        },
        "接管与壳体连接结构型式": {"1": "插入式", "2": "安放式"},
        "嵌入式接管补强类型": {"1": "a型", "2": "b型", "3": "c型"}
    }
    field_reverse_maps2 = {"压力试验类型": {"1": "液压", "2": "气压", "3": "气液"}}

    # ==========================================================
    # ⭐关键改动：按工况循环，每个工况复制一份模板并生成独立输出
    # ==========================================================
    # monkeypatch：拦截 openpyxl 写入，同步 xlwings

    def is_yes(v):
        return str(v or "").strip() in ("是", "1", "true", "True", "YES", "Yes")

    def get_nozzle_row_mode(id_val: str):
        s = str(id_val or "").strip()
        if "接管强度校核" in s:
            return "normal"
        if "小端校核" in s:
            return "small"
        return None

    def get_nozzle_sheet_mode(sheet_name: str):
        s = str(sheet_name or "").strip()
        if "厚壁管小端校核" in s:
            return "small"
        if "接管校核" in s:
            return "normal"
        return ""
    for case_label in case_labels:
        # 生成工况输出文件名：xxx_工况1.xlsx
        orig_value_prop = Cell.value
        orig_fget = orig_value_prop.fget
        orig_fset = orig_value_prop.fset
        base, ext = os.path.splitext(output_excel_path)
        case_output_excel_path = f"{base}_{case_label}{ext}"

        shutil.copyfile(target_excel_path, case_output_excel_path)
        print(f"📌 已复制模板：{target_excel_path} → {case_output_excel_path}")

        # ⭐关键：保持你后面使用 inter_data_map 的名字不变
        inter_data_map = inter_data_map_all[case_label]

        # =======================================
        # 打开“副本”工作簿：openpyxl + xlwings
        # =======================================
        target_wb = load_workbook(case_output_excel_path, data_only=False)

        app = xw.App(visible=False, add_book=False)
        app.display_alerts = False
        app.screen_updating = False
        wb_x = app.books.open(case_output_excel_path)

        # 建立 sheet 名称到 xlwings sheet 的映射
        sheet_map = {}
        for ws in target_wb.worksheets:
            try:
                sheet_map[ws.title] = wb_x.sheets[ws.title]
            except Exception:
                pass


        def patched_fset(self, value):
            orig_fset(self, value)
            try:
                ws = self.parent
                sheet_name = ws.title
                row = self.row
                col = self.column
                if sheet_name in sheet_map:
                    sht_x = sheet_map[sheet_name]
                    sht_x.range(row, col).value = value
            except Exception as e:
                print(f"[patched_fset] 同步到 xlwings 失败: {e}")

        Cell.value = property(orig_fget, patched_fset)
        def safe_float(v):
            if v is None:
                return None
            s = str(v).strip()
            if s == "" or s.lower() == "none":
                return None
            try:
                return float(s)
            except:
                return None

        def decide_mode_single(v):
            """
            - v >= 0 => 内压
            - v < 0  => 外压
            - v is None => 外压
            """
            if v is None:
                return "OUT2"
            return "IN2" if v >= 0 else "OUT2"

        # ✅ 当前 case 对应的“设计压力参数名称”
        case_param_map = {
            "工况1": "设计压力*",
            "工况2": "设计压力*[工况2]",
            "工况3": "设计压力*[工况3]",
        }
        current_param_name = case_param_map.get(case_label, "设计压力*")

        # ======== 只读取“当前 case”的设计压力（管程/壳程）========
        current_pressure = {"tube": None, "shell": None}

        conn_dp = pymysql.connect(
            host="localhost", port=3306, user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4"
        )
        cur_dp = conn_dp.cursor(pymysql.cursors.DictCursor)

        cur_dp.execute("""
            SELECT 参数名称, 管程数值, 壳程数值
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID=%s AND 参数名称=%s
            LIMIT 1
        """, (product_id, current_param_name))

        r = cur_dp.fetchone()
        if r:
            current_pressure["tube"] = safe_float(r.get("管程数值"))
            current_pressure["shell"] = safe_float(r.get("壳程数值"))

        cur_dp.close()
        conn_dp.close()
        def normalize_sheet_name(sheet_name):
            """
            把“壳体圆筒（外压）”统一还原成“壳体圆筒”
            其他工作表名保持不变
            """
            s = str(sheet_name or "").strip()
            if s.endswith("（外压）"):
                return s[:-4].strip()
            return s

        def find_existing_sheet_name(target_wb, logical_name):
            """
            根据逻辑名查实际存在的工作表名：
            - 先找原名
            - 再找“（外压）”
            返回实际存在的 sheet 名，不存在则返回 None
            """
            if logical_name in target_wb.sheetnames:
                return logical_name

            outer_name = f"{logical_name}（外压）"
            if outer_name in target_wb.sheetnames:
                return outer_name

            return None
        # ==========================================================
        # ✅ 圆筒内/外压工作表处理（与接管逻辑并行，不放在接管分支里）
        # 规则：
        # - 当前工况设计压力 >= 0：保留“...圆筒”，删除“...圆筒（外压）”
        # - 当前工况设计压力 < 0 ：删除“...圆筒”，保留“...圆筒（外压）”
        # - 取不到压力：按外压处理
        # ==========================================================

        CYLINDER_SIDE_EXACT_MAP = {

                # 圆筒
                "管箱圆筒": "tube",
                "前端管箱圆筒": "tube",
                "后端管箱圆筒": "tube",
                "容器圆筒": "shell",
                "壳体圆筒": "shell",
                "外头盖圆筒": "shell",
                "壳程端部圆筒1": "shell",
                "壳程端部圆筒2": "shell",

                # 封头
                "管箱封头": "tube",
                "前端管箱封头": "tube",
                "后端管箱封头": "tube",
                "前端封头": "shell",
                "后端封头": "shell",
                "壳体封头": "shell",
                "外头盖封头": "shell",
                "壳程端部封头1": "shell",
                "壳程端部封头2": "shell",

        }


        def delete_sheet_both(sheet_name):
            """
            同时删除 openpyxl 和 xlwings 中的工作表。
            因为最终是 wb_x.save()，所以必须删 xlwings 里的 sheet。
            """
            deleted_openpyxl = False
            deleted_xlwings = False

            if sheet_name in target_wb.sheetnames:
                try:
                    del target_wb[sheet_name]
                    deleted_openpyxl = True
                except Exception as e:
                    print(f"⚠️ openpyxl 删除失败：{sheet_name}，原因：{e}")

            try:
                wb_x.app.display_alerts = False
                wb_x.sheets[sheet_name].delete()
                deleted_xlwings = True
            except Exception as e:
                print(f"⚠️ xlwings 删除失败或已不存在：{sheet_name}，原因：{e}")

            sheet_map.pop(sheet_name, None)

            print(
                f"🗑 删除工作表：{sheet_name}，"
                f"openpyxl={deleted_openpyxl}，xlwings={deleted_xlwings}"
            )
        # ==========================================================
        # ✅ 锥壳内/外压工作表处理：xlwings + openpyxl 同步版
        # 适配当前中间 Excel：
        #   锥壳
        #   锥壳(α1-工况一)
        #   锥壳(α1-工况二)
        #   锥壳(α1-工况三)
        # ==========================================================

        CONE_GENERAL_SOURCE_SHEET = "锥壳"
        CONE_INNER_REPORT_SHEET = "内压锥壳"
        CONE_ECC_REPORT_SHEET = "偏心锥壳"
        CONE_ECC_WAIYA_REPORT_SHEET = "偏心锥壳（外压）"
        CONE_ALPHA_SOURCE_SHEET_MAP = {
            "工况一": "锥壳(α1-工况一)",
            "工况二": "锥壳(α1-工况二)",
            "工况三": "锥壳(α1-工况三)",
        }

        CONE_OUTER_REPORT_SHEET_MAP = {
            "工况一": "外压锥壳（工况一）",
            "工况二": "外压锥壳（工况二）",
            "工况三": "外压锥壳（工况三）",
        }
        # ✅ 新增：内压锥壳三工况的中间 Excel 来源工作表
        # 注意：这里是“（正压）”，不是普通的 α1 工况表
        CONE_POSITIVE_ALPHA_SOURCE_SHEET_MAP = {
            "工况一": "锥壳(α1-工况一)（正压）",
            "工况二": "锥壳(α1-工况二)（正压）",
            "工况三": "锥壳(α1-工况三)（正压）",
        }

        # ✅ 新增：最终 Excel 中的内压锥壳三工况工作表
        # 如果你的模板实际名字不是这个，把右侧工作表名改成实际名称即可
        CONE_INNER_CASE_REPORT_SHEET_MAP = {
            "工况一": "内压锥壳（工况一）",
            "工况二": "内压锥壳（工况二）",
            "工况三": "内压锥壳（工况三）",
        }

        def rename_single_cone_case_sheets_if_needed():
            """
            外压锥壳/内压锥壳工况页最终只剩一组时：
              外压锥壳（工况一） -> 外压锥壳
              内压锥壳（工况一） -> 内压锥壳

            判断标准：
              同一个 condition_label 下，只要外压页或内压页存在，就算这一组存在。
              如果最终只剩一个 condition_label，则去掉工作表名中的“（工况X）”。
            """
            remaining_conditions = []

            for condition_label in ("工况一", "工况二", "工况三"):
                outer_sheet_name = CONE_OUTER_REPORT_SHEET_MAP.get(condition_label)
                inner_sheet_name = CONE_INNER_CASE_REPORT_SHEET_MAP.get(condition_label)

                has_outer_sheet = outer_sheet_name in target_wb.sheetnames if outer_sheet_name else False
                has_inner_sheet = inner_sheet_name in target_wb.sheetnames if inner_sheet_name else False

                if has_outer_sheet or has_inner_sheet:
                    remaining_conditions.append(condition_label)

            if len(remaining_conditions) != 1:
                print(
                    f"🔎 [{case_label}] 锥壳工况页剩余组数={len(remaining_conditions)}，"
                    f"不进行单工况重命名"
                )
                return

            only_condition = remaining_conditions[0]

            outer_old_name = CONE_OUTER_REPORT_SHEET_MAP.get(only_condition)
            inner_old_name = CONE_INNER_CASE_REPORT_SHEET_MAP.get(only_condition)

            if outer_old_name in target_wb.sheetnames:
                rename_sheet_if_exists(
                    outer_old_name,
                    "外压锥壳"
                )

            if inner_old_name in target_wb.sheetnames:
                rename_sheet_if_exists(
                    inner_old_name,
                    CONE_INNER_REPORT_SHEET
                )

            print(
                f"✅ [{case_label}] 锥壳最终只剩 {only_condition} 一组，"
                f"已去掉外压/内压锥壳工作表名中的工况后缀"
            )
        def delete_sheet_if_exists(sheet_name):
            """
            同时删除 openpyxl 和 xlwings 中的工作表，并维护 sheet_map。
            """
            deleted = False

            if sheet_name in target_wb.sheetnames:
                try:
                    del target_wb[sheet_name]
                    deleted = True
                except Exception as e:
                    print(f"⚠️ openpyxl 删除工作表失败：{sheet_name}，原因：{e}")

            try:
                wb_x.sheets[sheet_name].delete()
                deleted = True
            except Exception:
                pass

            sheet_map.pop(sheet_name, None)

            if deleted:
                print(f"🗑️ 已删除锥壳工作表：{sheet_name}")

        def rename_sheet_if_exists(old_name, new_name):
            """
            同时重命名 openpyxl 和 xlwings 中的工作表。
            若 new_name 已存在，先删除 new_name，避免 Excel/openpyxl 自动生成重名后缀。
            """
            if old_name not in target_wb.sheetnames:
                return False

            if new_name in target_wb.sheetnames and old_name != new_name:
                delete_sheet_if_exists(new_name)

            try:
                target_wb[old_name].title = new_name
            except Exception as e:
                print(f"⚠️ openpyxl 重命名工作表失败：{old_name} -> {new_name}，原因：{e}")

            try:
                wb_x.sheets[old_name].name = new_name
            except Exception as e:
                print(f"⚠️ xlwings 重命名工作表失败：{old_name} -> {new_name}，原因：{e}")

            old_x = sheet_map.pop(old_name, None)
            if old_x is not None:
                sheet_map[new_name] = old_x
            else:
                try:
                    sheet_map[new_name] = wb_x.sheets[new_name]
                except Exception:
                    pass

            print(f"🔁 已将工作表 [{old_name}] 重命名为 [{new_name}]")
            return True

        def hide_column_a_if_exists(sheet_name):
            """
            同时隐藏 openpyxl 和 xlwings 中的 A 列。
            """
            if sheet_name in target_wb.sheetnames:
                try:
                    target_wb[sheet_name].column_dimensions["A"].hidden = True
                except Exception as e:
                    print(f"⚠️ openpyxl 隐藏 A 列失败：{sheet_name}，原因：{e}")

            try:
                wb_x.sheets[sheet_name].range("A:A").api.EntireColumn.Hidden = True
            except Exception:
                pass

        def normalize_cone_condition(text):
            """
            工况1 / 工况一 -> 工况一
            工况2 / 工况二 -> 工况二
            工况3 / 工况三 -> 工况三
            """
            s = str(text or "").strip()
            s = (
                s.replace("１", "1")
                .replace("２", "2")
                .replace("３", "3")
            )

            m = re.search(r"工况\s*([123一二三])", s)
            if not m:
                return None

            return {
                "1": "工况一",
                "2": "工况二",
                "3": "工况三",
                "一": "工况一",
                "二": "工况二",
                "三": "工况三",
            }.get(m.group(1))

        def normalize_alpha_text(text):
            s = str(text or "").strip()
            s = (
                s.replace("α_", "α")
                .replace("α ", "α")
                .replace("１", "1")
                .replace("２", "2")
                .replace("３", "3")
            )
            return s

        def strip_condition_marker_from_keyword(keyword):
            """
            去掉 A 列中的【工况一/二/三】标识符。
            """
            s = str(keyword or "").strip()
            s = re.sub(r"【\s*工况\s*[123一二三]\s*】", "", s)
            return s.strip()

        def extract_condition_marker_from_keyword(keyword):
            """
            从 A 列中提取【工况一/二/三】。
            """
            s = str(keyword or "").strip()
            m = re.search(r"【([^】]+)】", s)
            if not m:
                return None
            return normalize_cone_condition(m.group(1))

        def is_cone_alpha_condition_id(id_val, condition_label):
            """
            兜底用：
            如果以后又变回“锥壳”工作表中通过 Id 区分 α1 工况，
            这里仍然可以识别：
              锥壳(α1-工况一)
              锥壳(α1-工况二)
              锥壳(α1-工况三)
            """
            s = normalize_alpha_text(id_val)

            if "锥壳" not in s:
                return False

            paren_contents = re.findall(r"[（(]([^（）()]*)[）)]", s)
            for content in paren_contents:
                content2 = normalize_alpha_text(content)

                if "α1" not in content2:
                    continue

                cond = normalize_cone_condition(content2)
                if cond == condition_label:
                    return True

            return False

        def build_map_from_inter_sheet(sheet_name):
            """
            从 inter_data_map 中按工作表名取 name -> value。
            当前例子中：
              inter_data_map["锥壳"]
              inter_data_map["锥壳(α1-工况一)"]
              inter_data_map["锥壳(α1-工况二)"]
              inter_data_map["锥壳(α1-工况三)"]
            """
            result = {}

            if sheet_name in inter_data_map:
                for k, v in inter_data_map.get(sheet_name, {}).items():
                    if k is None:
                        continue
                    name = str(k).strip()
                    if name and name not in result:
                        result[name] = v

            return result

        def build_cone_general_map():
            """
            普通锥壳数据：
            来源：中间 Excel 的 “锥壳” 工作表。
            用于：
              - 内压锥壳
              - 偏心锥壳中不带工况标识的普通行
            """
            result = build_map_from_inter_sheet(CONE_GENERAL_SOURCE_SHEET)

            # 兜底：如果 inter_data_map 中没有，尝试逐行读取
            if not result:
                for item in inter_row_map_all.get(case_label, {}).get(CONE_GENERAL_SOURCE_SHEET, []):
                    row_name = str(item.get("name", "")).strip()
                    row_value = item.get("value", None)
                    if row_name and row_name not in result:
                        result[row_name] = row_value

            return result

        def build_cone_alpha_map(condition_label):
            """
            α1 外压工况数据：
            优先来源：
              锥壳(α1-工况一)
              锥壳(α1-工况二)
              锥壳(α1-工况三)

            兜底来源：
              如果以后又放回“锥壳”工作表，则根据 Id 中的 α1-工况X 提取。
            """
            source_sheet = CONE_ALPHA_SOURCE_SHEET_MAP.get(condition_label)
            result = {}

            # 1）优先按独立工作表读取
            if source_sheet:
                result.update(build_map_from_inter_sheet(source_sheet))

            # 2）兜底：从同名工作表逐行读取
            if not result and source_sheet:
                for item in inter_row_map_all.get(case_label, {}).get(source_sheet, []):
                    row_name = str(item.get("name", "")).strip()
                    row_value = item.get("value", None)
                    if row_name and row_name not in result:
                        result[row_name] = row_value

            # 3）兜底：如果数据混在“锥壳”表中，根据 Id 判断 α1-工况
            if not result:
                for item in inter_row_map_all.get(case_label, {}).get(CONE_GENERAL_SOURCE_SHEET, []):
                    row_id_val = item.get("id_val", "")
                    row_name = str(item.get("name", "")).strip()
                    row_value = item.get("value", None)

                    if not row_name:
                        continue

                    if is_cone_alpha_condition_id(row_id_val, condition_label):
                        result[row_name] = row_value

            return result

        def build_cone_positive_alpha_map(condition_label):
            """
            构建内压锥壳三工况数据。

            来源工作表：
              工况一 -> 锥壳(α1-工况一)（正压）
              工况二 -> 锥壳(α1-工况二)（正压）
              工况三 -> 锥壳(α1-工况三)（正压）

            用途：
              外压情况下，仍然需要输出：
                内压锥壳（工况一）
                内压锥壳（工况二）
                内压锥壳（工况三）
            """
            source_sheet = CONE_POSITIVE_ALPHA_SOURCE_SHEET_MAP.get(condition_label)
            result = {}

            # 1）优先按独立工作表读取
            if source_sheet:
                result.update(build_map_from_inter_sheet(source_sheet))

            # 2）兜底：从同名工作表逐行读取
            if not result and source_sheet:
                for item in inter_row_map_all.get(case_label, {}).get(source_sheet, []):
                    row_name = str(item.get("name", "")).strip()
                    row_value = item.get("value", None)

                    if row_name and row_name not in result:
                        result[row_name] = row_value

            return result

        # A列/C列字段别名：最终报告字段名 -> 中间 Excel Name
        CONE_KEYWORD_ALIAS = {
            # 偏心锥壳工况行常见简称
            "DiL": "锥壳大端圆筒加强段(直边段)计算内直径",
            "DIL": "锥壳大端圆筒加强段(直边段)计算内直径",
            "D_iL": "锥壳大端圆筒加强段(直边段)计算内直径",
            "DᵢL": "锥壳大端圆筒加强段(直边段)计算内直径",

            "Dis": "锥壳小端圆筒加强段(直边段)计算内直径",
            "DIS": "锥壳小端圆筒加强段(直边段)计算内直径",
            "D_is": "锥壳小端圆筒加强段(直边段)计算内直径",
            "Dᵢs": "锥壳小端圆筒加强段(直边段)计算内直径",

            # 模板描述列可能出现的文字
            "输入轴对称锥壳的大端内径": "锥壳大端圆筒加强段(直边段)计算内直径",
            "输入轴对称锥壳的小端内径": "锥壳小端圆筒加强段(直边段)计算内直径",
            "输入轴对称锥壳的长度": "锥壳段轴向长度（轴对称）",

            # 常见长度/角度别名
            "锥壳的计算总长度H": "锥壳总体长度",
            "锥壳计算总长度H": "锥壳总体长度",
            "锥壳的计算半夹角α_1": "锥壳夹角最大值",
            "锥壳计算半夹角α_1": "锥壳夹角最大值",
        }

        def get_cone_lookup_candidates(raw_keyword, desc_keyword=None):
            """
            生成候选匹配字段。
            例如：
              A列 DiL -> 锥壳大端圆筒加强段(直边段)计算内直径
              A列 锥壳夹角最大值【工况一】 -> 锥壳夹角最大值
              C列 输入轴对称锥壳的小端内径 -> 锥壳小端圆筒加强段(直边段)计算内直径
            """
            candidates = []

            clean_keyword = strip_condition_marker_from_keyword(raw_keyword)
            desc_keyword = str(desc_keyword or "").strip()

            for k in (
                    clean_keyword,
                    CONE_KEYWORD_ALIAS.get(clean_keyword),
                    CONE_KEYWORD_ALIAS.get(desc_keyword),
            ):
                if k and k not in candidates:
                    candidates.append(k)

            return candidates

        def find_value_with_replace_suffix(name_value_map, keyword):
            """
            从中间 Excel 的 name->value 映射中取值。

            匹配顺序：
            1）先按原字段名精确匹配；
            2）如果匹配不到，再按“字段名（替）”匹配；
            3）兼容半角括号“(替)”；
            4）同时兼容字段名前后有空格的情况。

            例如：
              目标字段：椭圆形封头最大允许工作压力
              中间 Excel 没有该字段，但有：椭圆形封头最大允许工作压力（替）
              则返回“（替）”这一行的值。
            """
            if not name_value_map or keyword is None:
                return None, None

            keyword_raw = keyword
            keyword_str = str(keyword).strip()
            if not keyword_str:
                return None, None

            candidates = []

            def add_candidate(k):
                if k is None:
                    return
                if k not in candidates:
                    candidates.append(k)

            add_candidate(keyword_raw)
            add_candidate(keyword_str)

            if not keyword_str.endswith(("（替）", "(替)")):
                add_candidate(f"{keyword_str}（替）")
                add_candidate(f"{keyword_str}(替)")

            # 优先直接按字典 key 查，保持原逻辑效率
            for key in candidates:
                if key in name_value_map:
                    return key, name_value_map[key]

            # 兜底：兼容中间 Excel 字段名前后带空格
            candidate_str_set = {str(k).strip() for k in candidates if k is not None}
            for map_key, map_value in name_value_map.items():
                if str(map_key).strip() in candidate_str_set:
                    return map_key, map_value

            return None, None

        def find_value_by_candidates(name_value_map, candidates):
            for key in candidates:
                matched_key, matched_value = find_value_with_replace_suffix(name_value_map, key)
                if matched_key is not None:
                    return matched_key, matched_value
            return None, None

        def write_value_if_empty(cell, value):
            if cell.value is None or str(cell.value).strip() == "":
                cell.value = value
                return True
            return False

        def has_valid_cone_data(name_value_map):
            """
            判断某个锥壳工况是否真的有可写数据。
            """
            if not name_value_map:
                return False

            for v in name_value_map.values():
                if v not in (None, "", "None"):
                    return True

            return False

        def is_negative_cone_small_end_diameter(condition_label, *name_value_maps):
            """
            判断某个锥壳工况的小端直边段内直径是否为负数。
            如果为负数，则该工况的外压锥壳、内压锥壳工况页都删除。

            兼容字段：
              锥壳小端直边段内直径【工况一】
              锥壳小端直边段内直径
              锥壳小端圆筒加强段(直边段)计算内直径【工况一】
              锥壳小端圆筒加强段(直边段)计算内直径

            同时兼容字段末尾带：
              （替）
              (替)
            """
            raw_candidates = [
                f"锥壳小端直边段内直径【{condition_label}】",
                "锥壳小端直边段内直径",
                f"锥壳小端圆筒加强段(直边段)计算内直径【{condition_label}】",
                "锥壳小端圆筒加强段(直边段)计算内直径",
            ]

            candidates = []
            for key in raw_candidates:
                key = str(key).strip()
                for cand in (key, f"{key}（替）", f"{key}(替)"):
                    if cand not in candidates:
                        candidates.append(cand)

            for name_value_map in name_value_maps:
                if not name_value_map:
                    continue

                for cand in candidates:
                    if cand not in name_value_map:
                        continue

                    v = safe_float(name_value_map.get(cand))
                    if v is not None and v < 0:
                        print(
                            f"⚠️ [{case_label}] 锥壳{condition_label}小端直边段内直径为负数："
                            f"{cand}={name_value_map.get(cand)}，删除该工况内/外压锥壳页"
                        )
                        return True

            return False

        def fill_cone_sheet_by_map(sheet_name, name_value_map):
            """
            普通填充：
            用于 内压锥壳、外压锥壳（工况一/二/三）。
            A列字段名 -> D列值。

            额外逻辑：
            根据中间 Excel 中：
              1. 锥壳大端是否带折边
              2. 锥壳小端是否带折边

            判断最终工作表中对应 B 列合并区域的 D 列是否需要清空。
            """
            if sheet_name not in target_wb.sheetnames:
                print(f"⚠️ 锥壳目标工作表不存在：{sheet_name}")
                return

            ws = target_wb[sheet_name]
            hit_count = 0
            miss_count = 0

            for row in ws.iter_rows(min_row=2):
                keyword_cell = row[0]  # A列
                output_cell = row[3]  # D列

                raw_keyword = keyword_cell.value
                if raw_keyword is None:
                    continue

                # C列描述也作为辅助匹配
                desc_keyword = row[2].value if len(row) >= 3 else None

                candidates = get_cone_lookup_candidates(raw_keyword, desc_keyword)
                matched_key, val = find_value_by_candidates(name_value_map, candidates)

                if matched_key is not None:
                    if write_value_if_empty(output_cell, val):
                        hit_count += 1
                else:
                    if str(raw_keyword).strip():
                        miss_count += 1

            # ==================================================
            # ✅ 新增：根据大端/小端是否带折边，清空对应计算区域 D列
            # ==================================================
            def normalize_flag(v):
                """
                把 是/否/True/False/1/0 统一成 yes/no。
                """
                s = str(v or "").strip()

                if s in ("是", "True", "true", "1", "YES", "Yes", "yes"):
                    return "yes"

                if s in ("否", "False", "false", "0", "NO", "No", "no"):
                    return "no"

                return ""

            def get_value_from_map_with_replace_key(param_name):
                """
                从中间 Excel 映射中取值。
                先找原字段，找不到再找：
                  字段名（替）
                  字段名(替)
                """
                candidates = [
                    param_name,
                    f"{param_name}（替）",
                    f"{param_name}(替)",
                ]

                for key in candidates:
                    if key in name_value_map:
                        return name_value_map[key]

                return None

            def normalize_text(v):
                """
                用于比较 B列合并单元格标题。
                兼容半角/全角括号和空格差异。
                """
                return (
                    str(v or "")
                    .strip()
                    .replace("(", "（")
                    .replace(")", "）")
                    .replace(" ", "")
                    .replace("\n", "")
                    .replace("\r", "")
                )

            def get_merged_cell_value(ws, row_idx, col_idx):
                """
                获取某个单元格所在合并区域左上角的值。
                例如 B列是合并单元格时，非左上角单元格本身 value 为空，
                需要从 merged_cells 中找到真正的标题值。
                """
                cell = ws.cell(row=row_idx, column=col_idx)

                if cell.value not in (None, ""):
                    return cell.value

                for merged_range in ws.merged_cells.ranges:
                    if cell.coordinate in merged_range:
                        return ws.cell(
                            row=merged_range.min_row,
                            column=merged_range.min_col
                        ).value

                return cell.value

            def clear_d_column_by_b_merged_titles(title_list):
                """
                清空 B列合并单元格标题属于 title_list 的所有行的 D列。
                """
                normalized_titles = [normalize_text(t) for t in title_list]
                clear_count = 0

                for r in range(2, ws.max_row + 1):
                    b_text = normalize_text(get_merged_cell_value(ws, r, 2))  # B列
                    if not b_text:
                        continue

                    matched = False
                    for title in normalized_titles:
                        # 用包含判断，避免模板里标题前后有补充文字
                        if title and title in b_text:
                            matched = True
                            break

                    if not matched:
                        continue

                    d_cell = ws.cell(row=r, column=4)  # D列
                    if isinstance(d_cell, MergedCell):
                        continue

                    if d_cell.value not in (None, ""):
                        d_cell.value = None
                        clear_count += 1

                return clear_count

            big_end_flag = normalize_flag(
                get_value_from_map_with_replace_key("锥壳大端是否带折边")
            )
            small_end_flag = normalize_flag(
                get_value_from_map_with_replace_key("锥壳小端是否带折边")
            )

            # ---------- 大端 ----------
            if big_end_flag == "no":
                # 大端不带折边：
                # 清空“大端折边锥壳相关计算”
                cnt = clear_d_column_by_b_merged_titles([
                    "大端折边锥壳相关计算",
                ])
                print(f"🧹 [{case_label}] {sheet_name}：锥壳大端不带折边，已清空大端折边相关计算 D列 {cnt} 项")

            elif big_end_flag == "yes":
                # 大端带折边：
                # 清空无折边大端相关计算
                cnt = clear_d_column_by_b_merged_titles([
                    "无折边大端锥壳相关计算",
                    "无折边大端锥壳与筒体连接处的加强计算（内压+载荷）",
                ])
                print(f"🧹 [{case_label}] {sheet_name}：锥壳大端带折边，已清空无折边大端相关计算 D列 {cnt} 项")

            # ---------- 小端 ----------
            if small_end_flag == "no":
                # 小端不带折边：
                # 清空“小端折边锥壳相关计算”
                cnt = clear_d_column_by_b_merged_titles([
                    "小端折边锥壳相关计算",
                ])
                print(f"🧹 [{case_label}] {sheet_name}：锥壳小端不带折边，已清空小端折边相关计算 D列 {cnt} 项")

            elif small_end_flag == "yes":
                # 小端带折边：
                # 清空无折边小端相关计算
                cnt = clear_d_column_by_b_merged_titles([
                    "无折边小端锥壳相关计算",
                    "无折边小端锥壳与筒体连接处的加强计算（内压+载荷）",
                ])
                print(f"🧹 [{case_label}] {sheet_name}：锥壳小端带折边，已清空无折边小端相关计算 D列 {cnt} 项")

            hide_column_a_if_exists(sheet_name)
            print(f"✅ [{case_label}] 锥壳填充：{sheet_name}，命中 {hit_count} 项，未命中 {miss_count} 项")

        def fill_cone_eccentric_sheet(general_map, alpha_map_by_condition):
            """
            偏心锥壳专用填充。

            规则：
            1）A列带【工况一/二/三】：用对应 α1 工况表。
            2）B列出现“工况一/二/三”：说明从该行开始进入该工况分组。
               例如：
                   A列 DiL，B列 工况一
                   A列 Dis，B列空
               Dis 仍然属于上一行的“工况一”。
            3）A列、B列都没有工况：用普通锥壳 general_map。
            """
            sheet_name = CONE_ECC_WAIYA_REPORT_SHEET

            if sheet_name not in target_wb.sheetnames:
                print(f"⚠️ 锥壳目标工作表不存在：{sheet_name}")
                return

            ws = target_wb[sheet_name]
            hit_count = 0
            miss_count = 0

            current_condition = None

            for row in ws.iter_rows(min_row=2):
                keyword_cell = row[0]  # A列
                group_cell = row[1]  # B列
                desc_cell = row[2]  # C列
                output_cell = row[3]  # D列

                raw_keyword = keyword_cell.value
                if raw_keyword is None:
                    continue

                # B列如果写了 工况一/二/三，则更新当前分组
                b_condition = normalize_cone_condition(group_cell.value)
                if b_condition:
                    current_condition = b_condition

                # A列【工况一】优先，其次 B列工况，其次继承上一组工况
                condition_label = (
                        extract_condition_marker_from_keyword(raw_keyword)
                        or b_condition
                        or current_condition
                )

                candidates = get_cone_lookup_candidates(
                    raw_keyword=raw_keyword,
                    desc_keyword=desc_cell.value
                )

                if condition_label in alpha_map_by_condition:
                    source_map = alpha_map_by_condition.get(condition_label, {})
                else:
                    source_map = general_map

                matched_key, val = find_value_by_candidates(source_map, candidates)

                if matched_key is not None:
                    if write_value_if_empty(output_cell, val):
                        hit_count += 1
                else:
                    if str(raw_keyword).strip():
                        miss_count += 1

            hide_column_a_if_exists(sheet_name)
            print(f"✅ [{case_label}] 锥壳填充：{sheet_name}，命中 {hit_count} 项，未命中 {miss_count} 项")

        def process_cone_sheets_by_pressure():
            """
            锥壳总处理入口。

            内压：
              中间 Excel “锥壳” -> 最终 Excel “内压锥壳”
              删除：偏心锥壳、外压锥壳（工况一/二/三）

            外压：
              中间 Excel “锥壳” -> 内压锥壳、偏心锥壳普通字段
              中间 Excel “锥壳(α1-工况一)” -> 外压锥壳（工况一）
              中间 Excel “锥壳(α1-工况二)” -> 外压锥壳（工况二）
              中间 Excel “锥壳(α1-工况三)” -> 外压锥壳（工况三）
            """
            has_any_cone_data = (
                    CONE_GENERAL_SOURCE_SHEET in inter_data_map
                    or any(s in inter_data_map for s in CONE_ALPHA_SOURCE_SHEET_MAP.values())
                    or any(s in inter_data_map for s in CONE_POSITIVE_ALPHA_SOURCE_SHEET_MAP.values())
            )

            if not has_any_cone_data:
                print(f"⚠️ [{case_label}] 中间 Excel 没有锥壳相关工作表，跳过锥壳处理")
                return

            # 锥壳默认按壳程压力判断内外压
            cone_pressure = current_pressure.get("shell")
            cone_mode = decide_mode_single(cone_pressure)

            general_map = build_cone_general_map()

            alpha_map_by_condition = {
                "工况一": build_cone_alpha_map("工况一"),
                "工况二": build_cone_alpha_map("工况二"),
                "工况三": build_cone_alpha_map("工况三"),
            }
            positive_alpha_map_by_condition = {
                "工况一": build_cone_positive_alpha_map("工况一"),
                "工况二": build_cone_positive_alpha_map("工况二"),
                "工况三": build_cone_positive_alpha_map("工况三"),
            }
            print(
                f"🔎 [{case_label}] 锥壳数据统计："
                f"普通={len(general_map)}，"
                f"外压α1-工况一={len(alpha_map_by_condition['工况一'])}，"
                f"外压α1-工况二={len(alpha_map_by_condition['工况二'])}，"
                f"外压α1-工况三={len(alpha_map_by_condition['工况三'])}，"
                f"正压α1-工况一={len(positive_alpha_map_by_condition['工况一'])}，"
                f"正压α1-工况二={len(positive_alpha_map_by_condition['工况二'])}，"
                f"正压α1-工况三={len(positive_alpha_map_by_condition['工况三'])}"
            )

            if cone_mode == "IN2":
                # 内压/正压：只保留普通“内压锥壳”
                # 删除偏心锥壳、外压锥壳三工况、内压锥壳三工况
                for del_name in (
                        "偏心锥壳（外压）",

                        "外压锥壳（工况一）",
                        "外压锥壳（工况二）",
                        "外压锥壳（工况三）",

                        "内压锥壳（工况一）",
                        "内压锥壳（工况二）",
                        "内压锥壳（工况三）",
                ):
                    delete_sheet_if_exists(del_name)

                fill_cone_sheet_by_map(
                    sheet_name=CONE_INNER_REPORT_SHEET,
                    name_value_map=general_map
                )
                fill_cone_sheet_by_map(
                    sheet_name=CONE_ECC_REPORT_SHEET,
                    name_value_map=general_map
                )
                print(f"✅ [{case_label}] 锥壳判定为内压，保留[{CONE_INNER_REPORT_SHEET}]")

            else:
                # 外压：保留内压锥壳、偏心锥壳、外压锥壳三工况
                # fill_cone_sheet_by_map(
                #     sheet_name=CONE_INNER_REPORT_SHEET,
                #     name_value_map=general_map
                # )

                fill_cone_eccentric_sheet(
                    general_map=general_map,
                    alpha_map_by_condition=alpha_map_by_condition
                )

                # ==================================================
                # ✅ 外压情况下：逐个工况判断是否存在
                # - 如果某个工况外压数据和正压数据都没有：
                #   删除对应的 外压锥壳（工况X） 和 内压锥壳（工况X）
                # - 如果只有外压数据：保留并填充外压锥壳，删除对应内压锥壳
                # - 如果只有正压数据：保留并填充内压锥壳，删除对应外压锥壳
                # - 如果两者都有：两个都保留并填充
                # ==================================================
                delete_sheet_if_exists(CONE_INNER_REPORT_SHEET)
                delete_sheet_if_exists(CONE_ECC_REPORT_SHEET)
                # ✅ 新增：外压偏心锥壳最终仍命名为“偏心锥壳”
                rename_sheet_if_exists(
                    CONE_ECC_WAIYA_REPORT_SHEET,
                    CONE_ECC_REPORT_SHEET
                )
                for condition_label in ("工况一", "工况二", "工况三"):
                    outer_sheet_name = CONE_OUTER_REPORT_SHEET_MAP.get(condition_label)
                    inner_case_sheet_name = CONE_INNER_CASE_REPORT_SHEET_MAP.get(condition_label)

                    outer_map = alpha_map_by_condition.get(condition_label, {})
                    positive_map = positive_alpha_map_by_condition.get(condition_label, {})

                    has_outer = has_valid_cone_data(outer_map)
                    has_positive = has_valid_cone_data(positive_map)

                    # ✅ 新增：如果该工况“锥壳小端直边段内直径”为负数，
                    # 则删除对应的 外压锥壳（工况X） 和 内压锥壳（工况X）
                    if is_negative_cone_small_end_diameter(
                            condition_label,
                            outer_map,
                            positive_map
                    ):
                        if outer_sheet_name:
                            delete_sheet_if_exists(outer_sheet_name)
                        if inner_case_sheet_name:
                            delete_sheet_if_exists(inner_case_sheet_name)

                        print(
                            f"🗑️ [{case_label}] 锥壳{condition_label}小端直边段内直径为负数，"
                            f"已删除[{outer_sheet_name}]和[{inner_case_sheet_name}]"
                        )
                        continue

                    # 1）这个工况完全没有数据：删除对应两个工作表
                    if not has_outer and not has_positive:
                        if outer_sheet_name:
                            delete_sheet_if_exists(outer_sheet_name)
                        if inner_case_sheet_name:
                            delete_sheet_if_exists(inner_case_sheet_name)

                        print(
                            f"🗑️ [{case_label}] 锥壳{condition_label}无数据，"
                            f"已删除[{outer_sheet_name}]和[{inner_case_sheet_name}]"
                        )
                        continue

                    # 2）外压数据存在：填充外压锥壳（工况X）
                    if has_outer:
                        fill_cone_sheet_by_map(
                            sheet_name=outer_sheet_name,
                            name_value_map=outer_map
                        )
                    else:
                        # 外压数据不存在，但正压数据存在：删除外压工况页
                        if outer_sheet_name:
                            delete_sheet_if_exists(outer_sheet_name)

                    # 3）正压数据存在：填充内压锥壳（工况X）
                    if has_positive:
                        fill_cone_sheet_by_map(
                            sheet_name=inner_case_sheet_name,
                            name_value_map=positive_map
                        )
                    else:
                        # 正压数据不存在，但外压数据存在：删除内压工况页
                        if inner_case_sheet_name:
                            delete_sheet_if_exists(inner_case_sheet_name)
                # ✅ 新增：如果最终只剩一组锥壳工况页，则去掉“（工况X）”后缀
                rename_single_cone_case_sheets_if_needed()
        # ✅ 执行锥壳处理
        process_cone_sheets_by_pressure()
        processed_cylinder_bases = set()

        def get_side_by_pressure_sheet_name(sheet_name):
            """
            根据工作表名称判断属于管程还是壳程
            """
            name = strip_pressure_suffix(sheet_name)

            SIDE_EXACT_MAP = {
                # 圆筒
                "管箱圆筒": "tube",
                "前端管箱圆筒": "tube",
                "后端管箱圆筒": "tube",

                "壳体圆筒": "shell",
                "外头盖圆筒": "shell",
                "壳程端部圆筒1": "shell",
                "壳程端部圆筒2": "shell",

                # 封头
                "管箱封头": "tube",
                "前端管箱封头": "tube",
                "后端管箱封头": "tube",

                "壳体封头": "shell",
                "外头盖封头": "shell",
                "壳程端部封头1": "shell",
                "壳程端部封头2": "shell",
            }

            if name in SIDE_EXACT_MAP:
                return SIDE_EXACT_MAP[name]

            if ("管箱" in name) or ("管程" in name):
                return "tube"

            if ("壳体" in name) or ("壳程" in name) or ("外头盖" in name):
                return "shell"

            return None
        def strip_pressure_suffix(sheet_name):
            """
            去掉工作表名中的外压后缀，得到基础表名
            """
            name = normalize_sheet_name(sheet_name)
            name = name.replace("（外压）", "").replace("(外压)", "")
            return name.strip()
        def process_inner_outer_pressure_sheets(
                target_wb,
                keyword,
                item_label,
                current_pressure,
                case_label
        ):
            """
            统一处理圆筒 / 封头的内压、外压工作表。

            keyword:
                用于筛选工作表，如 "圆筒"、"封头"

            item_label:
                打印日志用，如 "圆筒"、"封头"
            """
            processed_bases = set()

            for sname in list(target_wb.sheetnames):
                if keyword not in sname:
                    continue

                base_name = strip_pressure_suffix(sname)

                if base_name in processed_bases:
                    continue
                processed_bases.add(base_name)

                inner_name = base_name
                outer_name = f"{base_name}（外压）"

                has_inner = inner_name in target_wb.sheetnames
                has_outer = outer_name in target_wb.sheetnames

                if not (has_inner and has_outer):
                    continue

                side = get_side_by_pressure_sheet_name(base_name)

                if side == "tube":
                    v_case = current_pressure["tube"]
                elif side == "shell":
                    v_case = current_pressure["shell"]
                else:
                    v_case = None

                mode = decide_mode_single(v_case)

                if mode == "IN2":
                    delete_sheet_both(outer_name)
                    print(f"✅ [{case_label}] {item_label}[{base_name}]判定为内压，删除[{outer_name}]")
                else:
                    delete_sheet_both(inner_name)
                    print(f"✅ [{case_label}] {item_label}[{base_name}]判定为外压，删除[{inner_name}]")

        # ==========================================================
        # ✅ 圆筒 / 封头内外压工作表处理
        # ==========================================================
        process_inner_outer_pressure_sheets(
            target_wb=target_wb,
            keyword="圆筒",
            item_label="圆筒",
            current_pressure=current_pressure,
            case_label=case_label
        )

        process_inner_outer_pressure_sheets(
            target_wb=target_wb,
            keyword="封头",
            item_label="封头",
            current_pressure=current_pressure,
            case_label=case_label
        )
        # ==========================================================
        # ✅ 你的“展开接管模板 + 复制四模板”逻辑：原样保留
        # ==========================================================
        if "接管" in target_wb.sheetnames:
            template_sheet = target_wb["接管"]
            pipe_modules = [k for k in dict_out_data.keys() if "接管" in k]

            template_x = wb_x.sheets["接管"]
            excel_app = wb_x.app.api

            for module_name in pipe_modules:
                guankou_daihao = ""
                if module_name not in target_wb.sheetnames:
                    conn2 = pymysql.connect(
                        host="localhost",
                        port=3306,
                        user="root",
                        password="123456",
                        database="产品设计活动库",
                        charset="utf8mb4"
                    )

                    if module_name.endswith("接管"):
                        base_name_short = module_name[:-2]
                    else:
                        base_name_short = module_name

                    cur2 = conn2.cursor(pymysql.cursors.DictCursor)

                    cur2.execute("""
                        SELECT 管口代号, 管口功能, 管口用途
                        FROM 产品设计活动表_管口表
                        WHERE 产品ID=%s AND 管口功能=%s
                        LIMIT 1
                    """, (product_id, base_name_short))
                    row = cur2.fetchone()

                    if not row:
                        cur2.execute("""
                            SELECT 管口代号, 管口功能, 管口用途
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID=%s AND 管口功能=%s
                            LIMIT 1
                        """, (product_id, base_name_short))
                        row = cur2.fetchone()

                    guankou_daihao = row["管口代号"] if row else ""
                    cur2.close()
                    conn2.close()

                    new_sheet = target_wb.copy_worksheet(template_sheet)
                    new_sheet.title = module_name
                    new_sheet["B2"].value = f"{module_name}计算报告"

                template_x.api.Copy(After=template_x.api)
                new_x = excel_app.ActiveSheet
                new_x.Name = module_name

                new_x_sheet = wb_x.sheets[module_name]
                new_x_sheet.range("B2").value = f"({guankou_daihao}){module_name}计算报告"
                sheet_map[module_name] = new_x_sheet
                template_x = new_x_sheet

            # 删除模板“接管”
            if "接管" in target_wb.sheetnames:
                del target_wb["接管"]
            try:
                wb_x.sheets["接管"].delete()
                sheet_map.pop("接管", None)
            except:
                pass

            # ===========================
            # ✅ 接管校核模板：按“当前 case”设计压力(管程/壳程)正负自动决定展开哪些页
            # ===========================

            nozzle_template_sheets_all = [
                "接管校核（内压）",
                "接管校核（外压）",
                "厚壁管小端校核（内压）",
                "厚壁管小端校核（外压）",
            ]
            nozzle_suffixes_all = [
                "校核（内压）",
                "校核（外压）",
                "厚壁管小端校核（内压）",
                "厚壁管小端校核（外压）",
            ]
            NOZZLE_MODE_TO_INDEX = {
                "IN2": [0, 2],  # 只内压
                "OUT2": [1, 3],  # 只外压
            }

            def safe_float(v):
                if v is None:
                    return None
                s = str(v).strip()
                if s == "" or s.lower() == "none":
                    return None
                try:
                    return float(s)
                except:
                    return None

            def decide_mode_single(v):
                """
                ✅ 只基于“当前工况”的一个数值判断：
                - v >= 0 => 内压
                - v < 0  => 外压
                - v is None(缺字段) => 外压（按你最保守的需求）
                """
                if v is None:
                    return "OUT2"
                return "IN2" if v >= 0 else "OUT2"

            def get_side_by_guankou(product_id, guankou_daihao):
                if not guankou_daihao:
                    return None

                conn_s = pymysql.connect(
                    host="localhost", port=3306, user="root", password="123456",
                    database="产品设计活动库", charset="utf8mb4"
                )
                cur_s = conn_s.cursor(pymysql.cursors.DictCursor)

                cur_s.execute("""
                    SELECT 管口所属元件
                    FROM 产品设计活动表_管口表
                    WHERE 产品ID=%s AND 管口代号=%s
                    LIMIT 1
                """, (product_id, guankou_daihao))
                rr = cur_s.fetchone()

                cur_s.close()
                conn_s.close()

                owner = (rr.get("管口所属元件") if rr else "") or ""
                owner = str(owner).strip()

                if "管箱" in owner:
                    return "tube"
                if ("壳体" in owner) or ("外头盖" in owner) or ("锥壳" in owner) or ("壳程" in owner):
                    return "shell"
                return None

            # ✅ 当前 case 对应的“设计压力参数名称”——每个 case 只取一个字段！
            case_param_map = {
                "工况1": "设计压力*",
                "工况2": "设计压力*[工况2]",
                "工况3": "设计压力*[工况3]",
            }
            # 如果你的 case_label 不是“工况1/2/3”这种，就按实际字符串改 key
            current_param_name = case_param_map.get(case_label, "设计压力*")

            # ======== 只读取“当前 case”的设计压力（管程/壳程）========
            current_pressure = {"tube": None, "shell": None}

            conn_dp = pymysql.connect(
                host="localhost", port=3306, user="root", password="123456",
                database="产品设计活动库", charset="utf8mb4"
            )
            cur_dp = conn_dp.cursor(pymysql.cursors.DictCursor)

            cur_dp.execute("""
                SELECT 参数名称, 管程数值, 壳程数值
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID=%s AND 参数名称=%s
                LIMIT 1
            """, (product_id, current_param_name))

            r = cur_dp.fetchone()
            if r:
                current_pressure["tube"] = safe_float(r.get("管程数值"))
                current_pressure["shell"] = safe_float(r.get("壳程数值"))

            cur_dp.close()
            conn_dp.close()

            # ======== 主逻辑：仅当四个模板页都存在时才展开 ========
            if all(t in target_wb.sheetnames for t in nozzle_template_sheets_all):
                template_sheets_ox = {t: target_wb[t] for t in nozzle_template_sheets_all}
                template_sheets_xw = {t: wb_x.sheets[t] for t in nozzle_template_sheets_all}
                excel_app = wb_x.app.api

                pipe_modules = [k for k in dict_out_data.keys() if "接管" in k]

                for module_name in pipe_modules:
                    # --- 先查管口代号（你原逻辑）---
                    guankou_daihao = ""
                    conn2 = pymysql.connect(
                        host="localhost", port=3306, user="root", password="123456",
                        database="产品设计活动库", charset="utf8mb4"
                    )
                    base_name_short = module_name[:-2] if module_name.endswith("接管") else module_name
                    cur2 = conn2.cursor(pymysql.cursors.DictCursor)

                    cur2.execute("""
                        SELECT 管口代号, 管口功能, 管口用途
                        FROM 产品设计活动表_管口表
                        WHERE 产品ID=%s AND 管口功能=%s
                        LIMIT 1
                    """, (product_id, base_name_short))
                    row = cur2.fetchone()

                    if not row:
                        cur2.execute("""
                            SELECT 管口代号, 管口功能, 管口用途
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID=%s AND 管口功能=%s
                            LIMIT 1
                        """, (product_id, base_name_short))
                        row = cur2.fetchone()

                    guankou_daihao = row["管口代号"] if row else ""
                    cur2.close()
                    conn2.close()
                    # ✅ 判断当前接管是否变径（基于当前工况的中间数据）
                    module_data_map = inter_data_map_all.get(case_label, {}).get(module_name, {})
                    is_reducer_nozzle = is_yes(module_data_map.get("接管是否变径"))
                    # ✅ 关键：只取“当前 case”的一个数值来判断内/外压
                    side = get_side_by_guankou(product_id, guankou_daihao)  # tube/shell/None

                    if side == "tube":
                        v_case = current_pressure["tube"]
                    elif side == "shell":
                        v_case = current_pressure["shell"]
                    else:
                        v_case = None  # 取不到所属元件 => 按缺字段处理（外压）

                    mode = decide_mode_single(v_case)  # IN2 / OUT2

                    # ✅ 根据“接管是否变径”决定是否保留“小端校核”
                    if mode == "IN2":
                        idx_list = [0, 2] if is_reducer_nozzle else [0]
                    else:
                        idx_list = [1, 3] if is_reducer_nozzle else [1]

                    # === 仅展开需要的模板页 ===
                    for i in idx_list:
                        tpl_sheet_name = nozzle_template_sheets_all[i]
                        suffix = nozzle_suffixes_all[i]
                        new_sheet_name = f"{module_name}{suffix}"

                        if new_sheet_name not in target_wb.sheetnames:
                            new_sheet = target_wb.copy_worksheet(template_sheets_ox[tpl_sheet_name])
                            new_sheet.title = new_sheet_name
                            new_sheet["B2"].value = f"{module_name}{suffix}计算报告"

                        template_x = template_sheets_xw[tpl_sheet_name]
                        template_x.api.Copy(After=template_x.api)
                        new_x = excel_app.ActiveSheet
                        new_x.Name = new_sheet_name

                        new_x_sheet = wb_x.sheets[new_sheet_name]
                        new_x_sheet.range("B2").value = f"({guankou_daihao}){module_name}{suffix}计算报告"
                        sheet_map[new_sheet_name] = new_x_sheet

                # 删除四个模板页
                for tpl in nozzle_template_sheets_all:
                    if tpl in target_wb.sheetnames:
                        del target_wb[tpl]
                    try:
                        wb_x.sheets[tpl].delete()
                        sheet_map.pop(tpl, None)
                    except:
                        pass
            else:
                print("⚠️ 未找到接管四个模板页（接管校核/厚壁管小端校核），跳过展开")
        # ==========================================================
        # ✅ 下面开始：你原来“特殊匹配 + 接管增强 + 主循环写值”
        # 关键修复：凡是从 inter_wb 逐行扫描的地方，都按 case_label 过滤！
        # ==========================================================

        special_match_map = {
            "浮头法兰": ["浮头法兰（TNC）", "浮头法兰（SNC）", "浮头法兰（TC）", "浮头法兰（SC）",
                         "B型钩圈（SC）", "B型钩圈（SNC）", "B型钩圈（TC）", "B型钩圈（TNC）",
                         "球冠形封头（管程）","球冠形封头（壳程）", "外头盖圆筒"],
            "固定管板": ["球冠形封头（管程）","球冠形封头（壳程）", "固定管板",
                       "B型钩圈（SC）", "B型钩圈（SNC）", "B型钩圈（TC）", "B型钩圈（TNC）"],
            "球冠形封头": ["球冠形封头（管程）","球冠形封头（壳程）"]
        }

        # ✅ 注意：现在 inter_data_map 是两层（sheet->name->value），所以 inter_name 要查 inter_data_map 的 key
        for inter_name, target_sheets in special_match_map.items():
            if inter_name not in inter_data_map:
                continue

            # 固定管板合并逻辑：这里按你写法保留（会在当前工况下合并）
            if inter_name == "固定管板":
                name_value_map = {}
                name_value_map.update(inter_data_map.get("固定管板", {}))
                name_value_map.update(inter_data_map.get("浮头管束", {}))
                name_value_map.update(inter_data_map.get("管箱法兰", {}))
            else:
                name_value_map = inter_data_map[inter_name]

            for logical_target_name in target_sheets:
                actual_sheet_name = find_existing_sheet_name(target_wb, logical_target_name)
                if not actual_sheet_name:
                    continue

                sheet = target_wb[actual_sheet_name]
                for row in sheet.iter_rows(min_row=2):
                    keyword_cell = row[0]
                    output_cell = row[3]
                    keyword = keyword_cell.value
                    matched_key, matched_value = find_value_with_replace_suffix(name_value_map, keyword)
                    if matched_key is not None and (output_cell.value is None or str(output_cell.value).strip() == ""):
                        output_cell.value = matched_value

        def nozzle_base_sheet_name(sheet_name: str) -> str:
            if "校核（" not in sheet_name:
                return ""
            prefix = sheet_name.split("校核（", 1)[0]
            idx = prefix.rfind("接管")
            return prefix[:idx + 2] if idx != -1 else ""

        def extract_guankou_daihao_from_b2(b2_text: str) -> str:
            if not b2_text:
                return ""
            m = re.search(r"\(([^)]+)\)", str(b2_text))
            return m.group(1).strip() if m else ""

        def fetch_port_owner_component(product_id, guankou_daihao) -> str:
            if not guankou_daihao:
                return ""
            conn = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="产品设计活动库", charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT 管口所属元件
                    FROM 产品设计活动表_管口表
                    WHERE 产品ID=%s AND 管口代号=%s
                    LIMIT 1
                """, (product_id, guankou_daihao))
                row = cur.fetchone()
                return str(row.get("管口所属元件", "")).strip() if row else ""
            finally:
                conn.close()

        def decide_side(sheet_name: str, owner_component: str) -> str:
            sname = str(sheet_name or "")
            owner = str(owner_component or "")
            if "管箱" in owner:
                return "tube"
            if "壳体" in owner:
                return "shell"
            if ("管箱" in sname) or ("管程" in sname):
                return "tube"
            if ("壳体" in sname) or ("壳程" in sname):
                return "shell"
            if sname.startswith("管程"):
                return "tube"
            if sname.startswith("壳程"):
                return "shell"
            return "tube"

        # 接管四表增强填值（基于当前工况 inter_data_map）
        for sheet_name in target_wb.sheetnames:
            base_nozzle = nozzle_base_sheet_name(sheet_name)
            if not base_nozzle:
                continue
            if base_nozzle not in inter_data_map:
                continue

            sheet = target_wb[sheet_name]

            # 当前接管页类型：normal / small
            current_sheet_mode = get_nozzle_sheet_mode(sheet_name)
            if not current_sheet_mode:
                continue

            # 当前接管是否变径
            nozzle_base_map = inter_data_map.get(base_nozzle, {})
            is_reducer_nozzle = is_yes(nozzle_base_map.get("接管是否变径"))

            # 如果当前页是“小端校核”，但接管不变径，则直接跳过
            if current_sheet_mode == "small" and not is_reducer_nozzle:
                continue

            merged_map = {}

            # 只把 id_val 命中的数据写到对应页，不命中的一律不写
            for item in inter_row_map_all.get(case_label, {}).get(base_nozzle, []):
                row_id_val = item.get("id_val", "")
                row_name = item.get("name", "")
                row_value = item.get("value", None)

                row_mode = get_nozzle_row_mode(row_id_val)

                if row_mode == current_sheet_mode:
                    merged_map[row_name] = row_value

            guankou_daihao = extract_guankou_daihao_from_b2(sheet["B2"].value)
            owner_component = fetch_port_owner_component(product_id, guankou_daihao)
            side = decide_side(sheet_name, owner_component)

            for row in sheet.iter_rows(min_row=2):
                keyword_cell = row[0]
                output_cell = row[3]
                keyword = keyword_cell.value
                matched_key, matched_value = find_value_with_replace_suffix(merged_map, keyword)
                if matched_key is not None and (output_cell.value is None or str(output_cell.value).strip() == ""):
                    output_cell.value = matched_value

        # ==========================================================
        # ✅ 主循环：遍历所有 sheet（你的原逻辑）
        # 关键修复：凡扫描 inter_wb 的地方都要按工况过滤
        # ==========================================================
        for sheet in target_wb.worksheets:
            sheet_name = sheet.title
            logical_sheet_name = normalize_sheet_name(sheet_name)  # 业务匹配名
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )

            try:
                # 固定管板(b) 腐蚀前/后 —— 按工况过滤 inter_wb 行
                if sheet_name in ("固定管板(b)腐蚀前", "固定管板(b)腐蚀后"):
                    sheet.column_dimensions['A'].hidden = True
                    sheet.column_dimensions['B'].hidden = True
                    sheet.column_dimensions['C'].hidden = True
                    sheet.column_dimensions['D'].hidden = True

                    inter_data = []
                    if "固定管板" in inter_wb.sheetnames:
                        inter_sheet = inter_wb["固定管板"]
                        inter_data.extend(inter_sheet.iter_rows(min_row=2))
                    if "管束" in inter_wb.sheetnames:
                        inter_sheet_bundle = inter_wb["管束"]
                        inter_data.extend(inter_sheet_bundle.iter_rows(min_row=2))

                    for inter_row in inter_data:
                        raw_id = inter_row[0].value
                        row_case, clean_id = extract_case_label(raw_id)
                        if row_case != case_label:
                            continue

                        id_val = str(clean_id).strip() if clean_id else ""
                        name_val = str(inter_row[1].value).strip() if inter_row[1].value else None
                        value_val = inter_row[2].value
                        if not name_val or value_val is None:
                            continue

                        target_sheets = []
                        if "腐蚀前" in id_val:
                            target_sheets.append("固定管板(b)腐蚀前")
                        elif "腐蚀后" in id_val:
                            target_sheets.append("固定管板(b)腐蚀后")
                        else:
                            target_sheets.extend(["固定管板(b)腐蚀前", "固定管板(b)腐蚀后"])

                        for ts_name in target_sheets:
                            if ts_name not in target_wb.sheetnames:
                                continue
                            ts = target_wb[ts_name]
                            for row in ts.iter_rows(min_row=5):
                                for src_idx in range(4):
                                    src_cell = row[src_idx]
                                    tgt_cell = row[src_idx + 6]
                                    if isinstance(tgt_cell, MergedCell):
                                        continue
                                    if str(src_cell.value).strip() == name_val and (
                                            tgt_cell.value is None or str(tgt_cell.value).strip() == ""):
                                        tgt_cell.value = value_val

                # 固定管板(e) 腐蚀前/后 —— 按工况过滤 inter_wb 行（其余数据库逻辑不变）
                if sheet_name in ("固定管板(e)腐蚀前", "固定管板(e)腐蚀后"):
                    sheet.column_dimensions['A'].hidden = True
                    sheet.column_dimensions['B'].hidden = True
                    sheet.column_dimensions['C'].hidden = True
                    sheet.column_dimensions['D'].hidden = True

                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT 参数名称, 参数值
                        FROM 产品设计活动表_元件附加参数表
                        WHERE 产品ID = %s
                          AND 元件名称 = '管箱垫片'
                          AND 参数名称 IN ('垫片类型', '垫片标准')
                    """, (product_id,))
                    rows = cursor.fetchall()

                    gasket_type = None
                    gasket_std = None
                    for r in rows:
                        if r["参数名称"] == "垫片类型":
                            gasket_type = r["参数值"]
                        elif r["参数名称"] == "垫片标准":
                            gasket_std = r["参数值"]

                    if gasket_type or gasket_std:
                        for ts_name in ("固定管板(e)腐蚀前", "固定管板(e)腐蚀后"):
                            if ts_name not in target_wb.sheetnames:
                                continue
                            ts = target_wb[ts_name]
                            for row in ts.iter_rows(min_row=5):
                                f_text = str(row[5].value).strip() if row[5].value else ""
                                if gasket_type and "管箱垫片型式" in f_text:
                                    if row[6].value in (None, "", "None"):
                                        row[6].value = gasket_type
                                if gasket_std and "管箱垫片标准" in f_text:
                                    if row[6].value in (None, "", "None"):
                                        row[6].value = gasket_std

                    inter_data = []
                    if "固定管板" in inter_wb.sheetnames:
                        inter_data.extend(inter_wb["固定管板"].iter_rows(min_row=2))
                    if "管束" in inter_wb.sheetnames:
                        inter_data.extend(inter_wb["管束"].iter_rows(min_row=2))
                    if "管箱法兰" in inter_wb.sheetnames:
                        inter_data.extend(inter_wb["管箱法兰"].iter_rows(min_row=2))

                    for inter_row in inter_data:
                        raw_id = inter_row[0].value
                        row_case, clean_id = extract_case_label(raw_id)
                        if row_case != case_label:
                            continue

                        id_val = str(clean_id).strip() if clean_id else ""
                        name_val = str(inter_row[1].value).strip() if inter_row[1].value else None
                        value_val = inter_row[2].value
                        if not name_val or value_val is None:
                            continue

                        target_sheets = []
                        if "腐蚀前" in id_val:
                            target_sheets.append("固定管板(e)腐蚀前")
                        elif "腐蚀后" in id_val:
                            target_sheets.append("固定管板(e)腐蚀后")
                        else:
                            target_sheets.extend(["固定管板(e)腐蚀前", "固定管板(e)腐蚀后"])

                        for ts_name in target_sheets:
                            if ts_name not in target_wb.sheetnames:
                                continue
                            ts = target_wb[ts_name]
                            for row in ts.iter_rows(min_row=5):
                                for src_idx in range(4):
                                    src_cell = row[src_idx]
                                    tgt_cell = row[src_idx + 6]
                                    if isinstance(tgt_cell, MergedCell):
                                        continue
                                    if str(src_cell.value).strip() == name_val and (
                                            tgt_cell.value is None or str(tgt_cell.value).strip() == ""):
                                        tgt_cell.value = value_val

                # 壳程端部圆筒1/2 删除逻辑（原样）
                if logical_sheet_name in ("壳程端部圆筒1", "大端壳体圆筒加强段","大端壳体圆筒加强段（外压）","壳程端部圆筒2","壳程端部圆筒1（外压）", "壳程端部圆筒2（外压）"):
                    if logical_sheet_name in inter_wb.sheetnames:
                        inter_sheet = inter_wb[logical_sheet_name]
                        has_data = False
                        for row in inter_sheet.iter_rows(min_row=2):
                            raw_id = row[0].value
                            row_case, _ = extract_case_label(raw_id)
                            if row_case != case_label:
                                continue
                            if any(cell.value not in (None, "") for cell in row):
                                has_data = True
                                break

                        if not has_data:
                            if sheet_name in target_wb.sheetnames:
                                target_wb.remove(target_wb[sheet_name])
                            try:
                                wb_x.sheets[sheet_name].delete()
                                sheet_map.pop(sheet_name, None)
                                print(f"🗑️ 删除工作表 '{sheet_name}'（{case_label} 无数据）")
                            except Exception:
                                pass

                # ===========================
                # ✅ 你的后续“数据库专项写入逻辑”
                # （管箱平盖 / B型钩圈 / 球冠形封头 / 浮头法兰 / 固定管板等）
                # 这些不依赖 inter_data_map 的结构变化，所以保持原样即可
                # ===========================

                # ---- 你原来的专项写入逻辑，从这里开始照搬 ----
                # （为了不改变你的工程逻辑，我这里不删任何调用，不改任何字段名）
                # ----------------------------------------------------------------

                # === 管箱平盖 ===
                if sheet_name == "管箱平盖":
                    pinggai_paihao = get_pinggai_data(product_id)
                    jietouxishu = get_jietouxishu_data(product_id)

                    for idx in range(2, sheet.max_row + 1):
                        c_cell = sheet.cell(row=idx, column=3)
                        d_cell = sheet.cell(row=idx, column=4)
                        c_val = str(c_cell.value).strip() if c_cell.value else ""

                        if c_val == "平盖覆层材料牌号" and not d_cell.value:
                            val = pinggai_paihao
                            if val == "0":
                                val = "-"
                            d_cell.value = val

                        if c_val == "焊接接头系数ф" and not d_cell.value:
                            d_cell.value = jietouxishu

                # if sheet_name == "固定管板(e)腐蚀前" or sheet_name == "固定管板(e)腐蚀后":
                #     ttgd = get_guanban_data(product_id)
                #     for idx in range(2, sheet.max_row + 1):
                #         c_cell = sheet.cell(row=idx, column=6)
                #         d_cell = sheet.cell(row=idx, column=7)
                #         c_val = str(c_cell.value).strip() if c_cell.value else ""
                #         if c_val == "管板凸台高度" and not d_cell.value:
                #             val = ttgd
                #             if val == "0":
                #                 val = "-"
                #             d_cell.value = val

                # === B型钩圈（SC）/（SNC） ===
                if sheet_name == "B型钩圈（SC）" or sheet_name == "B型钩圈（SNC）":
                    conn2 = pymysql.connect(
                        host="localhost",
                        port=3306,
                        user="root",
                        password="123456",
                        database="产品设计活动库",
                        charset="utf8mb4"
                    )
                    cursor = conn2.cursor()
                    sql = """
                        SELECT 参数名称, 参数值
                        FROM 产品设计活动表_元件附加参数表
                        WHERE 产品ID = %s AND 元件名称 = '钩圈'
                    """
                    cursor.execute(sql, (product_id,))
                    params = {r[0]: r[1] for r in cursor.fetchall()}
                    cursor.close()
                    conn2.close()

                    mapping = {
                        "材料牌号": "B型钩圈材料牌号",
                        "材料类型": "B型钩圈材料类型",
                    }

                    for idx in range(2, sheet.max_row + 1):
                        c_cell = sheet.cell(row=idx, column=3)
                        d_cell = sheet.cell(row=idx, column=4)
                        c_val = str(c_cell.value).strip() if c_cell.value else ""

                        if c_val == "B型钩圈覆层厚度" and not d_cell.value:
                            d_cell.value = 0
                            continue

                        for param_name, excel_c_name in mapping.items():
                            if c_val == excel_c_name and not d_cell.value and param_name in params:
                                d_cell.value = params[param_name]

                # === B型钩圈（TC）/（TNC） ===
                if sheet_name == "B型钩圈（TC）" or sheet_name == "B型钩圈（TNC）":
                    conn2 = pymysql.connect(
                        host="localhost",
                        port=3306,
                        user="root",
                        password="123456",
                        database="产品设计活动库",
                        charset="utf8mb4"
                    )
                    cursor = conn2.cursor()
                    sql = """
                        SELECT 参数名称, 参数值
                        FROM 产品设计活动表_元件附加参数表
                        WHERE 产品ID = %s AND 元件名称 = '钩圈'
                    """
                    cursor.execute(sql, (product_id,))
                    params = {r[0]: r[1] for r in cursor.fetchall()}
                    cursor.close()
                    conn2.close()

                    mapping = {
                        "材料牌号": "B型钩圈材料牌号",
                        "材料类型": "B型钩圈材料类型",
                    }

                    for idx in range(2, sheet.max_row + 1):
                        c_cell = sheet.cell(row=idx, column=3)
                        d_cell = sheet.cell(row=idx, column=4)
                        c_val = str(c_cell.value).strip() if c_cell.value else ""

                        if c_val == "B型钩圈覆层厚度" and not d_cell.value:
                            d_cell.value = 0
                            continue

                        for param_name, excel_c_name in mapping.items():
                            if c_val == excel_c_name and not d_cell.value and param_name in params:
                                d_cell.value = params[param_name]

                # === 球冠形封头 ===（原样保留）
                if sheet_name == "球冠形封头（管程）" or sheet_name == "球冠形封头（壳程）":
                    conn2 = pymysql.connect(
                        host="localhost",
                        port=3306,
                        user="root",
                        password="123456",
                        database="产品设计活动库",
                        charset="utf8mb4"
                    )
                    cursor = conn2.cursor()

                    sql1 = """
                        SELECT 参数名称, 参数值
                        FROM 产品设计活动表_元件附加参数表
                        WHERE 产品ID = %s AND 元件名称 = '球冠形封头'
                    """
                    cursor.execute(sql1, (product_id,))
                    params1 = {r[0]: r[1] for r in cursor.fetchall()}

                    sql2 = """
                        SELECT 参数名称, 壳程数值, 管程数值
                        FROM 产品设计活动表_设计数据表
                        WHERE 产品ID = %s
                    """
                    cursor.execute(sql2, (product_id,))
                    params2 = {r[0]: (r[1], r[2]) for r in cursor.fetchall()}

                    cursor.close()
                    conn2.close()

                    mapping1 = {
                        "管程侧腐蚀裕量": "管程侧腐蚀裕量C2t",
                        "壳程侧腐蚀裕量": "壳程侧腐蚀裕量C2s",
                        "壳程侧覆层厚度": "球冠形封头覆层厚度t",
                        "材料类型": "球冠形封头材料类型",
                        "材料牌号": "球冠形封头材料牌号",
                    }
                    mapping2 = {
                        "设计压力*": {"壳程设计压力": "壳程", "管程设计压力": "管程"},
                        "设计温度（最高）*": {"壳程设计温度": "壳程", "管程设计温度": "管程"},
                        "焊接接头系数*": {"纵向焊接接头系数ф": "壳程"},
                    }

                    for idx in range(2, sheet.max_row + 1):
                        c_val = str(sheet.cell(row=idx, column=3).value).strip() if sheet.cell(row=idx, column=3).value else ""
                        d_cell = sheet.cell(row=idx, column=4)

                        for param_name, excel_c_name in mapping1.items():
                            if c_val == excel_c_name and not d_cell.value and param_name in params1:
                                param_val = params1[param_name]
                                if "覆层厚度" in param_name or "裕量" in param_name:
                                    if param_val is None or str(param_val).strip() == "":
                                        param_val = 0
                                d_cell.value = param_val

                    for idx in range(2, sheet.max_row + 1):
                        c_val = str(sheet.cell(row=idx, column=3).value).strip() if sheet.cell(row=idx, column=3).value else ""
                        d_cell = sheet.cell(row=idx, column=4)

                        for param_name, excel_map in mapping2.items():
                            if param_name in params2:
                                shell_val, tube_val = params2[param_name]
                                for excel_c_name, which in excel_map.items():
                                    if c_val == excel_c_name and not d_cell.value:
                                        if which == "壳程":
                                            val = shell_val if shell_val not in (None, "") else 0
                                        else:
                                            val = tube_val if tube_val not in (None, "") else 0
                                        d_cell.value = val

                if "浮头法兰" in sheet_name:
                    conn2 = pymysql.connect(
                        host="localhost",
                        port=3306,
                        user="root",
                        password="123456",
                        database="产品设计活动库",
                        charset="utf8mb4"
                    )
                    cursor = conn2.cursor()

                    try:
                        # 1）先取普通元件参数（这里不再取“螺柱（浮头法兰）”的材料信息）
                        sql = """
                            SELECT 元件名称, 参数名称, 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s
                              AND 元件名称 IN ('浮头法兰', '球冠形封头')
                        """
                        cursor.execute(sql, (product_id,))
                        rows = cursor.fetchall()

                        params = {(r[0], r[1]): r[2] for r in rows}

                        # 2）去“元件附加参数合并表”中找：
                        #    参数名称='元件所属'，且参数值里包含“浮头法兰”的那个 Tab分类
                        tab_sql = """
                            SELECT Tab分类
                            FROM 产品设计活动表_元件附加参数合并表
                            WHERE 产品ID = %s
                              AND 参数名称 = '元件所属'
                              AND FIND_IN_SET(%s, REPLACE(REPLACE(参数值, '、', ','), '，', ',')) > 0
                            LIMIT 1
                        """
                        cursor.execute(tab_sql, (product_id, "浮头法兰"))
                        tab_row = cursor.fetchone()

                        if tab_row:
                            tab_category = tab_row[0]

                            # 3）在同一个 Tab分类 下取 材料类型1、材料牌号1
                            mat_sql = """
                                SELECT 参数名称, 参数值
                                FROM 产品设计活动表_元件附加参数合并表
                                WHERE 产品ID = %s
                                  AND Tab分类 = %s
                                  AND 参数名称 IN ('材料类型1', '材料牌号1')
                            """
                            cursor.execute(mat_sql, (product_id, tab_category))
                            mat_rows = cursor.fetchall()

                            mat_map = {r[0]: r[1] for r in mat_rows}

                            # 写回 params，供后面统一填表使用
                            if "材料类型1" in mat_map:
                                params[("螺柱（浮头法兰）", "材料类型")] = mat_map["材料类型1"]
                            if "材料牌号1" in mat_map:
                                params[("螺柱（浮头法兰）", "材料牌号")] = mat_map["材料牌号1"]

                        mapping = {
                            ("浮头法兰", "材料牌号"): "浮头法兰材料牌号",
                            ("浮头法兰", "材料类型"): "浮头法兰材料类型",
                            ("浮头法兰", "密封面高度"): "浮头法兰密封槽深度",
                            ("球冠形封头", "材料牌号"): "球冠形封头材料牌号",
                            ("球冠形封头", "材料类型"): "球冠形封头材料类型",
                            ("球冠形封头", "壳程侧腐蚀裕量"): "球冠形封头腐蚀裕量（壳程侧）",
                            ("球冠形封头", "管程侧腐蚀裕量"): "球冠形封头腐蚀裕量（管程侧）",
                            ("螺柱（浮头法兰）", "材料牌号"): "螺栓材料牌号",
                            ("螺柱（浮头法兰）", "材料类型"): "螺栓材料类型",
                        }

                        for idx in range(2, sheet.max_row + 1):
                            c_val = str(sheet.cell(row=idx, column=3).value).strip() if sheet.cell(row=idx,
                                                                                                   column=3).value else ""
                            d_cell = sheet.cell(row=idx, column=4)

                            for (comp, param), excel_c_name in mapping.items():
                                if c_val == excel_c_name and not d_cell.value and (comp, param) in params:
                                    param_val = params[(comp, param)]
                                    if "腐蚀裕量" in param:
                                        if param_val is None or str(param_val).strip() == "":
                                            param_val = 0
                                    d_cell.value = param_val

                    finally:
                        cursor.close()
                        conn2.close()

                # === 固定管板（换热管长度Lt、管程数）===（原样）
                if sheet_name == "固定管板":
                    conn2 = pymysql.connect(
                        host="localhost",
                        port=3306,
                        user="root",
                        password="123456",
                        database="产品设计活动库",
                        charset="utf8mb4"
                    )
                    cursor = conn2.cursor()

                    tube_length = ""
                    tube_pass_count = ""

                    sql = """
                        SELECT 参数名, 参数值
                        FROM 产品设计活动表_布管参数表
                        WHERE 产品ID = %s
                    """
                    cursor.execute(sql, (product_id,))
                    for param_name, param_value in cursor.fetchall():
                        if param_name == "换热管公称长度 LN":
                            tube_length = str(param_value)
                        elif param_name == "管程程数":
                            tube_pass_count = str(param_value)

                    cursor.close()
                    conn2.close()

                    for idx in range(2, sheet.max_row + 1):
                        c_val = str(sheet.cell(row=idx, column=3).value).strip() if sheet.cell(row=idx, column=3).value else ""
                        d_cell = sheet.cell(row=idx, column=4)
                        if c_val == "换热管长度Lt" and not d_cell.value:
                            d_cell.value = tube_length
                        elif c_val == "管程数" and not d_cell.value:
                            d_cell.value = tube_pass_count

                # ==========================
                # ✅ 核心：选择 name_value_map
                # 修复点：这里 inter_data_map 是两层，且你要的逻辑恢复正常
                # 特殊三张报告：仍然从 inter_wb["固定管板"] 过滤，但要按工况过滤
                # ==========================
                special_sheet_map = {
                    "换热管内压": "内压",
                    "换热管外压计算报告1": "外压",
                    "换热管外压计算报告2": "水压"
                }

                if sheet_name in special_sheet_map:
                    keyword = special_sheet_map[sheet_name]
                    fixed_data = {**inter_data_map.get("固定管板", {}), **inter_data_map.get("管束", {})}

                    inter_sheet = inter_wb["固定管板"]
                    filtered_map = {}
                    for row in inter_sheet.iter_rows(min_row=2):
                        raw_id = row[0].value
                        row_case, clean_id = extract_case_label(raw_id)
                        if row_case != case_label:
                            continue

                        id_val = str(clean_id).strip() if clean_id else ""
                        name = str(row[1].value).strip() if row[1].value else ""
                        value = row[2].value
                        if keyword in id_val and name:
                            filtered_map[name] = value

                    name_value_map = filtered_map.copy()
                    for k, v in fixed_data.items():
                        if k not in name_value_map:
                            name_value_map[k] = v


                elif logical_sheet_name in inter_data_map:

                    name_value_map = inter_data_map[logical_sheet_name]
                else:
                    conn.close()
                    continue

                # ======= 通用写入（原样） =======
                for row in sheet.iter_rows(min_row=2):
                    keyword_cell = row[0]
                    output_cell = row[3]
                    keyword2 = keyword_cell.value

                    if keyword2 == "焊缝金属截面积A3":
                        output_cell.value = get_weld_area(product_id)
                        continue

                    matched_key, val = find_value_with_replace_suffix(name_value_map, keyword2)
                    if matched_key is not None and (
                            output_cell.value is None or str(output_cell.value).strip() == ""):
                        keyword2_str = str(keyword2).strip() if keyword2 is not None else ""

                        if keyword2_str in field_reverse_maps and val in field_reverse_maps[keyword2_str]:
                            val = field_reverse_maps[keyword2_str][val]
                        if keyword2_str in field_reverse_maps2 and val in field_reverse_maps2[keyword2_str]:
                            val = field_reverse_maps2[keyword2_str][val]

                        if keyword2_str in bool_field_names:
                            output_cell.value = auto_map_bool(val)
                        else:
                            output_cell.value = val

                success_key = sheet_name if sheet_name in module_success_map else logical_sheet_name
                if success_key in module_success_map:
                    result = "合格" if module_success_map[success_key] else "不合格"
                    for row in sheet.iter_rows(min_row=2):
                        if "结论" in str(row[2].value):
                            row[3].value = result

                sheet.column_dimensions['A'].hidden = True
            finally:
                pass
        for name in ("固定管板(b)腐蚀前", "固定管板(b)腐蚀后", "固定管板(e)腐蚀前", "固定管板(e)腐蚀后"):
            if name not in target_wb.sheetnames:
                continue

            ws = target_wb[name]
            need_clear = False
            l1_row = None

            for row in ws.iter_rows(min_row=5):
                f_text = str(row[5].value).strip() if row[5].value else ""
                if "壳程两端部圆筒总长度L1'+L1''" in f_text:
                    g_val = row[6].value
                    if g_val in (None, 0, "0", "0.0", "", " "):
                        need_clear = True
                        l1_row = row
                    break

            if not need_clear:
                continue

            if l1_row:
                l1_row[6].value = None

            for row in ws.iter_rows(min_row=5):
                f_text = str(row[5].value).strip() if row[5].value else ""
                if ("壳程端部圆筒" in f_text) or ("分段圆筒" in f_text):
                    row[6].value = None
                    print(f"➡ [{name}] 清空第 {row[0].row} 行")
                if ("壳程(端部圆筒)轴向应力" in f_text):
                    if row[6].value == "0":
                        row[6].value = None
                    if row[8].value == "0":
                        row[8].value = None

        source1 = find_existing_sheet_name(target_wb, "壳体圆筒")
        if source1 and "壳体法兰" in target_wb.sheetnames:
            copy_nominal_thickness(source1, "壳体法兰", target_wb)

        source2 = find_existing_sheet_name(target_wb, "管箱圆筒")
        if source2 and "管箱法兰" in target_wb.sheetnames:
            copy_nominal_thickness(source2, "管箱法兰", target_wb)
        write_flange_values(intermediate_excel_path, target_wb)
        process_test_type(target_wb)
        # === 在保存之前：如果管程程数 = 1，则删除“管箱分程隔板” ===
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
                    SELECT 参数值
                    FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = '管程程数'
                """, (product_id,))
                row = cursor.fetchone()

                if row:
                    value = str(row.get("参数值", "")).strip()
                    if value == "1":
                        sheet_to_delete = "管箱分程隔板"

                        # ① 删除 openpyxl 里的 sheet
                        if sheet_to_delete in target_wb.sheetnames:
                            ws = target_wb[sheet_to_delete]
                            target_wb.remove(ws)
                            print(f"🗑 已从 openpyxl 删除工作表：{sheet_to_delete}")

                        # ② 删除 xlwings 里的 sheet（真正影响最终 Excel 文件）
                        try:
                            wb_x.sheets[sheet_to_delete].delete()
                            print(f"🗑 已从 xlwings 删除工作表：{sheet_to_delete}")
                        except:
                            print(f"⚠️ xlwings 中找不到表：{sheet_to_delete}（可能已经被删）")

        finally:
            conn.close()

            # 只清理最终计算报告：中间“计算参数总览表”原样保留。
            # 使用同步删除函数，确保 openpyxl 与实际由 Excel 保存的工作簿一致。
            delete_empty_component_report_sheets(
                target_sheet_names=list(target_wb.sheetnames),
                intermediate_workbook=inter_wb,
                case_label=case_label,
                component_names=dict_out_data.keys(),
                delete_sheet=delete_sheet_both,
            )

            # 恢复 Cell.value
            Cell.value = property(orig_fget, orig_fset)

            # ✅ 只通过 xlwings 保存，保证格式不丢
            try:
                wb_x.save()
                print(f"✅ 工况 {case_label} 最终Excel已生成：{case_output_excel_path}")
            finally:
                wb_x.close()
                app.quit()


def process_test_type(target_wb):

    """
    遍历Excel所有工作表，将C列中值为'耐压试验类型'的行，
    根据D列数值映射为对应文本。
    """
    mapping = {'1': "液压", '2': "气压", '3': "气液"}
    for sheet in target_wb.worksheets:  # 遍历所有工作表
        if sheet.title == "球冠形封头":
            db_config = {
                'host': 'localhost',
                'port': 3306,
                'user': 'root',
                'password': '123456',
                'database': '产品设计活动库'
            }
            connection = get_connection(
                db_config['host'],
                db_config['port'],
                db_config['user'],
                db_config['password'],
                db_config['database']
            )
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT 壳程数值, 管程数值
                    FROM 产品设计活动表_设计数据表
                    WHERE 产品ID = %s AND 参数名称 = %s
                """, (product_id, "耐压试验类型*"))
                design_rows = cursor.fetchall()

                for i, row in enumerate(design_rows):
                    if not row:
                        continue
                    try:
                        shell_val = row["壳程数值"]
                        tube_val = row["管程数值"]
                    except Exception as e:
                        continue

                    for row in sheet.iter_rows(min_row=1, max_col=4):
                        c_cell = row[2]  # C列
                        d_cell = row[3]  # D列
                        if c_cell.value == "耐压试验类型（内压）":
                            d_cell.value = tube_val
                        if c_cell.value == "耐压试验类型（外压）":
                            d_cell.value = shell_val

        print("sheet",sheet.title)
        for row in sheet.iter_rows(min_row=1, max_col=4):
            c_cell = row[2]  # C列
            d_cell = row[3]  # D列
            if c_cell.value == "耐压试验类型" and d_cell.value in mapping:
                d_cell.value = mapping[d_cell.value]
