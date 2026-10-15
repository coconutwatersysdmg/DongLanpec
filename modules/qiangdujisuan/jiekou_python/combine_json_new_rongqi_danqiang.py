import ast
import math
import os
import re
import string
import sys
from collections import defaultdict

import configparser

import chardet
import pymysql
import json
from modules.qiangdujisuan.jiekou_python.calculation_process import run_integrated_calculation

from modules.chanpinguanli.chanpinguanli_main import product_manager
from modules.qiangdujisuan.jiekou_python.combine_json_new_nen import get_fastener_bolt_material_by_belong
from modules.qiangdujisuan.jiekou_python.head_type_utils import apply_head_types

product_id = None


def on_product_id_changed(new_id):
    print(f"Received new PRODUCT_ID: {new_id}")
    global product_id
    product_id = new_id


# 测试用产品 ID（真实情况中由外部输入）
product_manager.product_id_changed.connect(on_product_id_changed)


# ========== 安全值转换函数 ==========
def safe_str(val, default="0"):
    if val is None:
        return default
    val = str(val).strip()
    return val if val.lower() not in ("", "none") else default


def apply_special_defaults(field, val):
    v = safe_str(val)
    if field == "螺栓材料牌号" and v == "0":
        return "35CrMo"
    if field == "垫片材料牌号" and v == "0":
        return "复合柔性石墨波齿金属板(不锈钢)"
    if field == "垫片有效外径" and v == "0":
        return "0"
    if field == "垫片有效内径" and v == "0":
        return "0"
    return v


material_type_map = {
    "板材": "钢板",
    "锻件": "钢锻件",
    "Q235系列钢板": "钢板",

}
falan_map = {
    '长颈对焊法兰': '整体法兰2'
}


def calculate_heat_exchanger_strength(product_id):
    import pymysql

    # 连接数据库
    conn = pymysql.connect(
        host='localhost',
        user='root',
        password='123456',
        database='产品设计活动库',
        charset='utf8mb4',

    )
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # ====== 处理 WSList ======
    # 初始化为完整字段，全部为 "0"
    gongkuang1 = {
        "ShellWorkingPressure": "0",
        "TubeWorkingPressure": "0",
        "ShellWorkingTemperature": "0",
        "TubeWorkingTemperature": "0"
    }
    gongkuang2 = {
        "ShellWorkingPressure": "0",
        "TubeWorkingPressure": "0",
        "ShellWorkingTemperature": "0",
        "TubeWorkingTemperature": "0"
    }

    # 读取数据库
    cursor.execute("""
        SELECT 参数名称, 壳程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()

    # 参数名映射
    ws_mapping = {
        "设计压力*": ("ShellWorkingPressure", "TubeWorkingPressure"),
        "设计温度（最高）*": ("ShellWorkingTemperature", "TubeWorkingTemperature"),
        "设计压力*[工况2]": ("ShellWorkingPressure", "TubeWorkingPressure"),
        "设计温度（最高）*[工况2]": ("ShellWorkingTemperature", "TubeWorkingTemperature"),
    }

    # 填写数据
    for row in rows:
        param = row["参数名称"].strip()
        shell_val, tube_val = row["壳程数值"], row["壳程数值"]
        if param in ws_mapping:
            shell_key, tube_key = ws_mapping[param]
            if "[工况2]" in param:
                gongkuang2[shell_key] = str(shell_val) if shell_val not in [None, ""] else "0"
                gongkuang2[tube_key] = str(tube_val) if tube_val not in [None, ""] else "0"
            else:
                gongkuang1[shell_key] = str(shell_val) if shell_val not in [None, ""] else "0"
                gongkuang1[tube_key] = str(tube_val) if tube_val not in [None, ""] else "0"

    # 构建列表
    wslist = [gongkuang1]
    wslist.append(gongkuang2)

    def clean_value(val):
        if val is None or val == "":
            return "0"
        val_str = str(val)
        if "." in val_str:
            val_str = val_str.split(".")[0]
        return val_str

    # ====== 处理 TTDict ======

    # 获取统一的 公称尺寸类型 和 公称压力类型（该表不含管口代号）
    cursor.execute("""
        SELECT 公称尺寸类型, 公称压力类型
        FROM 产品设计活动表_管口类型选择表
        WHERE 产品ID = %s
    """, (product_id,))
    row = cursor.fetchone()

    pipe_type_default = {
        "公称尺寸类型": row["公称尺寸类型"] if row else "DN",
        "公称压力类型": row["公称压力类型"] if row else "PN"
    }

    # 获取所有管口数据（含外伸高度）
    cursor.execute("""
        SELECT *
        FROM 产品设计活动表_管口表
        WHERE 产品ID = %s
    """, (product_id,))
    port_rows = cursor.fetchall()

    ttdict = {}

    for row in port_rows:
        key = clean_value(row.get("管口代号"))  # 直接用管口代号作为 key

        axial_angle = row.get("轴向夹角（°）", "")
        zhouxiangfangwei = row.get("周向方位（°）", "")

        # 外伸高度处理逻辑
        ttH_raw = row.get("外伸高度", "程序推荐")
        ttH_val = "0" if ttH_raw in (None, "", "程序推荐") else str(ttH_raw)
        ttAttach = clean_value(row.get("管口所属元件"))
        if ttAttach == "圆筒":
            ttAttach = "容器圆筒"
        if ttAttach == "左封头":
            ttAttach = "前端封头"
        if ttAttach == "右封头":
            ttAttach = "后端封头"
        ttdict[key] = {
            "ttNo": 0,
            "ttCode": clean_value(row.get("管口代号")),
            "ttUse": clean_value(row.get("管口功能")),
            "ttDN": clean_value(row.get("公称尺寸")),
            "ttPClass": clean_value(row.get("压力等级")),
            "ttDType": pipe_type_default["公称尺寸类型"],
            "ttPType": pipe_type_default["公称压力类型"],
            "ttType": clean_value(row.get("法兰型式")),
            "ttRF": clean_value(row.get("密封面型式")),
            "ttSpec": "默认" if clean_value(row.get("焊端规格")) == "程序推荐" else clean_value(row.get("焊端规格")),
            "ttAttach": ttAttach,
            "ttPlace": {
                "左基准线": "左轮廓线",
                "右基准线": "右轮廓线"
            }.get(row.get("轴向定位基准", ""), clean_value(row.get("轴向定位基准"))),
            "ttLoc": "默认" if clean_value(row.get("轴向定位距离")) in ("程序推荐", "-", "") else clean_value(
                row.get("轴向定位距离")),
            "ttFW": clean_value(zhouxiangfangwei),
            "ttThita": clean_value(row.get("偏心距")),
            "ttAngel": clean_value(axial_angle),
            "ttH": ttH_val,
            "ttMemo": clean_value(row.get("法兰标准"))
        }

    # ===== 预设默认值 =====
    design_params = {
        "公称直径": "1000",
        "是否以外径为基准": "1",
        "介质类型": "介质易爆/极度危害/高度危害",
        "管箱圆筒长度工况": "工况1",
        "绝热厚度": "4",
        "管/壳程布置型式": "2.1",
        "大端公称直径": "1000",
        "锥壳大端与圆筒连接处是否作为支撑线": "否",
        "锥壳小端与圆筒连接处是否作为支撑线": "否",
        "设备类型": "卧式设备",
        "打压方式": "卧式打压",
        "介质密度": "2",
        "内件重量占容器重量百分比": "25",
        "左侧封头切线到右侧封头切线的距离": "6000",
    }
    # === 直接从数据库读取参数值 ===
    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()

        # === 查询管程分程形式 ===
        cursor.execute("""
                SELECT 参数值 
                FROM 产品设计活动表_布管参数表
                WHERE 产品ID = %s AND 参数名 = '管程分程形式'
                LIMIT 1
            """, (product_id,))
        row = cursor.fetchone()
        tube_form = row["参数值"].strip() if row and row.get("参数值") else None
        design_params["管/壳程布置型式"] = tube_form
        if tube_form == "2" or tube_form == None or tube_form == "":
            design_params["管/壳程布置型式"] = "2.1"
        # === 查询设计数据表 ===
        cursor.execute("""
            SELECT 参数名称, 壳程数值
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s
        """, (product_id,))
        rows = cursor.fetchall()
        param_map = {row["参数名称"].strip(): row for row in rows}

        # 公称直径（管程）
        if "公称直径*" in param_map:
            design_params["公称直径"] = str(param_map["公称直径*"].get("壳程数值", ""))
            design_params["大端公称直径"] = str(param_map["公称直径*"].get("壳程数值", ""))
        if "介质密度*" in param_map:
            design_params["介质密度"] = str(param_map["介质密度*"].get("壳程数值", ""))
        # 绝热厚度（管程）
        value = param_map.get("绝热材料厚度", {}).get("壳程数值")

        design_params["绝热厚度"] = (
            str(value).strip()
            if value is not None and str(value).strip() != ""
            else "0"
        )

        # 介质类型 = 爆炸危险性 + 壳程毒性 + 管程毒性
        media_parts = []
        if "介质特性（爆炸危险程度）" in param_map:
            shell_expl = param_map["介质特性（爆炸危险程度）"].get("壳程数值", "-")
            if shell_expl != "":
                media_parts.append(shell_expl)

        if "介质特性（毒性危害程度）" in param_map:
            shell_toxic = param_map["介质特性（毒性危害程度）"].get("壳程数值", "")
            if shell_toxic != "":
                media_parts.append(shell_toxic)

        if "介质特性（是否液化气体）" in param_map:
            shell_ox = param_map["介质特性（是否液化气体）"].get("壳程数值", "-")
            if shell_ox == "":
                media_parts.append(shell_ox)

        if media_parts:
            design_params["介质类型"] = "/".join(media_parts)
        else:
            design_params["介质类型"] = "0"
    except Exception as e:
        print(f" 查询失败: {e}")

    # ===== 获取"是否以外径为基准" =====
    cursor.execute("""
        SELECT 壳程数值 FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
    """, (product_id,))
    row = cursor.fetchone()
    if row and "壳程数值" in row:
        val = str(row["壳程数值"]).strip()
        design_params["是否以外径为基准"] = "1" if val == "是" else "0"
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '支座'
        """, (product_id,))
    rows = cursor.fetchall()
    extra_map = {r["参数名称"]: r["参数值"] for r in rows}
    if "内件重量占容器重量百分比" in extra_map:
        raw_type = extra_map["内件重量占容器重量百分比"]
        design_params["内件重量占容器重量百分比"] = material_type_map.get(raw_type, raw_type)

    dict_part = {
        "前端封头": "椭圆形封头",
        "容器圆筒": "筒体",
        "后端封头": "椭圆形封头",
        "鞍座": "鞍座",
        "吊耳": "吊耳",
        "容器圆筒加强圈": "加强圈",
    }

    def generate_pipe_dict(product_id):
        """
        根据产品ID生成接管字典：
        key = 管口功能+接管 或 管口用途+接管
        value = "接管"
        """
        pipe_dict = {}

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
                    SELECT 管口功能, 管口用途
                    FROM 产品设计活动表_管口表
                    WHERE 产品ID = %s
                """, (product_id,))
                rows = cursor.fetchall()
                for row in rows:
                    func = row.get("管口功能")
                    usage = row.get("管口用途")
                    if func and func.strip():
                        key = f"{func.strip()}接管"
                    elif usage and usage.strip():
                        key = f"{usage.strip()}接管"
                    else:
                        continue  # 两个字段都空就跳过
                    pipe_dict[key] = "接管"
        finally:
            conn.close()

        return pipe_dict

    def merge_dicts(original_dict, pipe_dict):
        """
        合并原字典与生成的接管字典，保留原来的非接管项
        """
        full_dict = original_dict.copy()
        for k, v in pipe_dict.items():
            if k not in full_dict:
                full_dict[k] = v
        return full_dict

    pipe_dict = generate_pipe_dict(product_id)
    full_dict = merge_dicts(dict_part, pipe_dict)

    jiaqiangquan = {
        "公称直径": "8",
        "圆筒内外径": "0",
        "名义厚度": "0",
        "是否以外径为基准": "1",
        "腐蚀裕量": "1000",
        "耐压试验温度": "15",
        "容器壳体长度": "3",
        "从加强圈中心线到相邻两侧加强圈中心线距离之和的一半": "0",
        "两个加强圈之间的距离": "0",
        "加强圈材料类型": "15",
        "加强圈材料牌号": "15",
        "加强圈型钢类型": "0",
        "HS": "0",
        "BTS": "0",
        "STOP": "0",
        "BSL1": "0",
        "BSL2": "0",
        "容器壳体长度基准": "T-T",
    }
    # === 查询设计数据表 ===
    cursor.execute("""
                SELECT 参数名称, 壳程数值
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s
            """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row for row in rows}

    # 公称直径（管程）
    if "公称直径*" in param_map:
        jiaqiangquan["公称直径"] = str(param_map["公称直径*"].get("壳程数值", ""))
    if "是否以外径为基准*" in param_map:
        jiaqiangquan["是否以外径为基准"] = "1" if str(param_map["是否以外径为基准*"].get("壳程数值", "")) == "是" else "0"
    if "耐压试验温度" in param_map:
        jiaqiangquan["耐压试验温度"] = str(param_map["耐压试验温度"].get("壳程数值", ""))
    if "容器壳体长度*" in param_map:
        jiaqiangquan["容器壳体长度"] = str(param_map["容器壳体长度*"].get("壳程数值", ""))
    if "容器壳体长度基准*" in param_map:
        jiaqiangquan["容器壳体长度基准"] = str(param_map["容器壳体长度基准*"].get("壳程数值", ""))
    if "腐蚀裕量*" in param_map:
        jiaqiangquan["腐蚀裕量"] = str(param_map["腐蚀裕量*"].get("壳程数值", ""))
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '加强圈'
        """, (product_id,))
    rows = cursor.fetchall()
    extra_map = {r["参数名称"]: r["参数值"] for r in rows}
    if "材料类型" in extra_map:
        raw_type = extra_map["材料类型"]
        jiaqiangquan["加强圈材料类型"] = material_type_map.get(raw_type, raw_type)
    if "材料牌号" in extra_map:
        jiaqiangquan["加强圈材料牌号"] = extra_map["材料牌号"]
        # 初始化字典

    guangxiang_fengtou = {
        "预设厚度1": "8",
        "预设厚度2": "10",
        "预设厚度3": "12",
        "是否以外径为基准": "1",
        "公称直径": "1000",
        "液柱静压力": "0",
        "腐蚀余量": "3",
        "焊接接头系数": "1",
        "压力试验类型": "1",
        "用户自定义耐压试验压力": "0",
        "压力试验温度": "15",
        "最大允许工作压力": "0",
        "封头与圆筒的连接型式": "A",
        "是否覆层": "1",
        "覆层复合方式": "轧制复合",
        "带覆层时的焊接凹槽深度": "2",
        "是否采用拼(板)接成形": "0",
        "封头成型厚度减薄率": "11",
        "材料类型": "板材",
        "材料牌号": "Q345R",
        "椭圆形封头内/外径": "1000",
        "椭圆形封头名义厚度": "0",
        "椭圆形封头覆层厚度": "3",
        "椭圆形封头曲面深度": "250",
        "椭圆形封头直边段高度": "25",
        "覆层材料类型": "",
    }
    # ===== 获取预设厚度1~3（来自元件附加参数表）=====
    cursor.execute("""
        SELECT 参数名称, 参数值 FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '封头'
    """, (product_id,))
    rows = cursor.fetchall()
    extra_param_map = {r["参数名称"].strip(): r["参数值"] for r in rows}

    # 写入 guangxiang_fengtou 中的预设厚度
    for i in range(1, 4):
        key = f"预设厚度{i}"
        if key in extra_param_map:
            guangxiang_fengtou[key] = str(extra_param_map[key])
    # 查询设计数据表
    cursor.execute("""
        SELECT 参数名称, 壳程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row for row in rows}

    cursor.execute("""
        SELECT 壳程数值 FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
    """, (product_id,))
    row = cursor.fetchone()
    if row and "壳程数值" in row:
        val = str(row["壳程数值"]).strip()
        design_params["是否以外径为基准"] = "1" if val == "是" else "0"

    # 查询设计数据表
    cursor.execute("""
        SELECT 参数名称, 壳程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row for row in rows}

    # ===== 基本字段赋值 =====
    map2 = {
        "公称直径": "公称直径*",
        "液柱静压力": "液柱静压力",
        "腐蚀裕量": "腐蚀裕量*",
        "焊接接头系数": "焊接接头系数*",
        "最大允许工作压力": "最高允许工作压力",
        "椭圆形封头内/外径": "公称直径*"
    }

    for key, param_name in map2.items():
        value = param_map.get(param_name, {}).get("壳程数值", "")
        if value != "":
            guangxiang_fengtou[key] = str(value)

    # ===== 压力试验类型（去掉末尾“试验”并映射为数字）=====
    pressure_type_map = {
        "液压": "1",
        "气压": "2",
        "气液": "3"
    }

    if "耐压试验类型*" in param_map:
        val = param_map["耐压试验类型*"].get("壳程数值", "")
        if val:
            clean_val = str(val).replace("试验", "").strip()
            guangxiang_fengtou["压力试验类型"] = pressure_type_map.get(clean_val, "0")

    # ===== 用户自定义耐压试验压力：取卧与立中较大者 =====
    val1 = param_map.get("自定义耐压试验压力（卧）", {}).get("壳程数值", "")
    val2 = param_map.get("自定义耐压试验压力（立）", {}).get("壳程数值", "")
    # ===== 最大允许工作压力 =====
    if "最大允许工作压力" in param_map:
        value = param_map["最大允许工作压力"].get("壳程数值", "")
        if value != "":
            guangxiang_fengtou["最大允许工作压力"] = str(value)

    try:
        val_max = max(float(val1), float(val2))
        guangxiang_fengtou["用户自定义耐压试验压力"] = str(int(val_max))
    except:
        guangxiang_fengtou["用户自定义耐压试验压力"] = str(val1 or val2 or "0")  # 至少有一个值就保留

    # 查询元件附加参数表中元件名称为“封头”的数据
    cursor.execute("""
        SELECT 参数名称, 参数值 
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '封头'
    """, (product_id,))
    extra_rows = cursor.fetchall()
    extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}

    # 是否添加覆层
    if extra_map.get("是否添加覆层") == "是":
        guangxiang_fengtou["是否覆层"] = "1"
        guangxiang_fengtou["覆层材料类型"] = extra_map.get("覆层材料类型", "轧制复合")  # 若为空可改为 "未知"
        if guangxiang_fengtou["覆层材料类型"] == "钢板":
            guangxiang_fengtou["带覆层时的焊接凹槽深度"] = extra_map.get("存在覆层时的焊接凹槽深度",
                                                                         "0")  # 若为空可改为 "未知"
        else:
            guangxiang_fengtou["带覆层时的焊接凹槽深度"] = "0"  # 若为空可改为 "未知"

        guangxiang_fengtou["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        guangxiang_fengtou["椭圆形封头覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
    else:
        guangxiang_fengtou["是否覆层"] = "0"
        guangxiang_fengtou["覆层材料类型"] = "钢板"  # 若为空可改为 "未知"
        guangxiang_fengtou["覆层复合方式"] = "无"
        guangxiang_fengtou["椭圆形封头覆层厚度"] = "0"
        guangxiang_fengtou["椭圆形封头曲面深度"] = extra_map.get("封头面曲面深度hi", "0")  # 默认“未知”可改为""
        guangxiang_fengtou["带覆层时的焊接凹槽深度"] = "0"  # 若为空可改为 "未知"

    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '封头'
    """, (product_id,))
    rows = cursor.fetchall()
    extra_map = {r["参数名称"]: r["参数值"] for r in rows}

    if "材料类型" in extra_map:
        raw_type = extra_map["材料类型"]
        guangxiang_fengtou["材料类型"] = material_type_map.get(raw_type, raw_type)
    if "材料牌号" in extra_map:
        guangxiang_fengtou["材料牌号"] = extra_map["材料牌号"]

        # 初始化字典
    keti_fengtou = {
        "预设厚度1": "8",
        "预设厚度2": "10",
        "预设厚度3": "12",
        "是否以外径为基准": "1",
        "公称直径": "1000",
        "液柱静压力": "0",
        "腐蚀余量": "3",
        "焊接接头系数": "1",
        "压力试验类型": "1",
        "用户自定义耐压试验压力": "0",
        "压力试验温度": "15",
        "最大允许工作压力": "0",
        "封头与圆筒的连接型式": "A",
        "是否覆层": "1",
        "覆层复合方式": "轧制复合",
        "带覆层时的焊接凹槽深度": "2",
        "是否采用拼(板)接成形": "0",
        "封头成型厚度减薄率": "11",
        "材料类型": "板材",
        "材料牌号": "Q345R",
        "椭圆形封头内/外径": "1000",
        "椭圆形封头名义厚度": "0",
        "椭圆形封头覆层厚度": "3",
        "椭圆形封头曲面深度": "250",
        "椭圆形封头直边段高度": "25",
        "覆层材料类型": ""
    }
    # ===== 获取预设厚度1~3（来自元件附加参数表）=====
    cursor.execute("""
        SELECT 参数名称, 参数值 FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '封头'
    """, (product_id,))
    rows = cursor.fetchall()
    extra_param_map = {r["参数名称"].strip(): r["参数值"] for r in rows}

    # 写入 guangxiang_fengtou 中的预设厚度
    for i in range(1, 4):
        key = f"预设厚度{i}"
        if key in extra_param_map:
            keti_fengtou[key] = str(extra_param_map[key])

    cursor.execute("""
        SELECT 壳程数值 FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
    """, (product_id,))
    row = cursor.fetchone()
    if row and "壳程数值" in row:
        val = str(row["壳程数值"]).strip()
        keti_fengtou["是否以外径为基准"] = "1" if val == "是" else "0"

    # 查询设计数据表
    cursor.execute("""
           SELECT 参数名称, 壳程数值
           FROM 产品设计活动表_设计数据表
           WHERE 产品ID = %s
       """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row for row in rows}
    # ===== 基本字段赋值 =====
    map2 = {
        "公称直径": "公称直径*",
        "液柱静压力": "液柱静压力",
        "腐蚀余量": "腐蚀裕量*",
        "焊接接头系数": "焊接接头系数*",
        "最大允许工作压力": "最高允许工作压力",
        "椭圆形封头内/外径": "公称直径*"
    }

    for key, param_name in map2.items():
        value = param_map.get(param_name, {}).get("壳程数值", "")
        if value != "":
            keti_fengtou[key] = str(value)

        # ===== 压力试验类型（去掉末尾“试验”并映射为数字）=====
    pressure_type_map = {
        "液压": "1",
        "气压": "2",
        "气液": "3"
    }

    if "耐压试验类型*" in param_map:
        val = param_map["耐压试验类型*"].get("壳程数值", "")
        if val:
            clean_val = str(val).replace("试验", "").strip()
            guangxiang_fengtou["压力试验类型"] = pressure_type_map.get(clean_val, "0")

    # ===== 用户自定义耐压试验压力：取卧与立中较大者 =====
    val1 = param_map.get("自定义耐压试验压力（卧）", {}).get("壳程数值", "")
    val2 = param_map.get("自定义耐压试验压力（立）", {}).get("壳程数值", "")
    # ===== 最大允许工作压力 =====
    if "最大允许工作压力" in param_map:
        value = param_map["最大允许工作压力"].get("壳程数值", "")
        if value != "":
            keti_fengtou["最大允许工作压力"] = str(value)

    try:
        val_max = max(float(val1), float(val2))
        keti_fengtou["用户自定义耐压试验压力"] = str(val_max)
    except:
        keti_fengtou["用户自定义耐压试验压力"] = str(val1 or val2 or "0")  # 至少有一个值就保留

    # 查询元件附加参数表中元件名称为“封头”的数据
    cursor.execute("""
           SELECT 参数名称, 参数值 
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s AND 元件名称 = '封头'
       """, (product_id,))
    extra_rows = cursor.fetchall()
    extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}

    # 是否添加覆层
    if extra_map.get("是否添加覆层") == "是":
        keti_fengtou["是否覆层"] = "1"
        keti_fengtou["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        keti_fengtou["椭圆形封头覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
        keti_fengtou["覆层材料类型"] = extra_map.get("覆层材料类型", "")  # 若为空可改为 "未知"
        if keti_fengtou["覆层材料类型"] == "钢板":
            keti_fengtou["带覆层时的焊接凹槽深度"] = extra_map.get("存在覆层时的焊接凹槽深度",
                                                                   "0")  # 若为空可改为 "未知"
        else:
            keti_fengtou["带覆层时的焊接凹槽深度"] = "0"  # 若为空可改为 "未知"


    else:
        keti_fengtou["是否覆层"] = "0"
        keti_fengtou["覆层复合方式"] = "无"
        keti_fengtou["椭圆形封头覆层厚度"] = "0"
        keti_fengtou["覆层材料类型"] = "钢板"  # 若为空可改为 "未知"
        keti_fengtou["带覆层时的焊接凹槽深度"] = "0"  # 若为空可改为 "未知"

    keti_fengtou["椭圆形封头曲面深度"] = extra_map.get("封头面曲面深度hi", "0")  # 默认“未知”可改为""

    cursor.execute("""
           SELECT 参数名称, 参数值
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s AND 元件名称 = '封头'
       """, (product_id,))
    rows = cursor.fetchall()
    extra_map = {r["参数名称"]: r["参数值"] for r in rows}

    if "材料类型" in extra_map:
        raw_type = extra_map["材料类型"]
        keti_fengtou["材料类型"] = material_type_map.get(raw_type, raw_type)
    if "材料牌号" in extra_map:
        keti_fengtou["材料牌号"] = extra_map["材料牌号"]

    diaoer = {
        "与吊耳连接元件": "容器圆筒",
        "设备公称直径": "1000",
        "设计温度": "20",
        "耐压试验温度": "20",
        "材料类型": "钢板",
        "材料牌号": "Q345R",
        "吊耳名义厚度": "16",
        "设备吊装质量": "489",
        "设备总高度": "2200",
        "设备重心到设备底部距离": "1100",
        "设备圆筒名义厚度": "16",
        "设备圆筒材料厚度负偏差": "0.3",
        "设备圆筒保温厚度": "0",
        "安全余量系数": "1.65",
        "是否带垫板": "0",
        "是否带系揽环板": "0",
        "吊耳放置方位": "1",
        "吊耳数量": "1",
        "吊耳外圆半径": "40",
        "吊耳孔直径": "30",
        "吊耳板高度": "45",
        "销轴直径": "27",
        "垫板宽度": "0",
        "垫板长度": "0",
        "垫板厚度": "0",
        "系揽环板外径": "0",
        "系揽环板厚度": "0",
        "角焊缝系数": "0.7",
        "吊索与垂直方向夹角": "50",
        "吊耳底边宽度": "120"
    }

    cursor.execute("""
               SELECT 壳程数值
               FROM 产品设计活动表_设计数据表
               WHERE 产品ID = %s AND 参数名称 = '耐压试验温度'
           """, (product_id,))
    row = cursor.fetchone()
    raw_val = row["壳程数值"].strip() if row and row.get("壳程数值") else None
    diaoer["耐压试验温度"] = raw_val
    cursor.execute("""
        SELECT 参数名称, 壳程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row["壳程数值"] for row in rows}

    # 获取公称直径
    if "公称直径*" in param_map:
        diaoer["设备公称直径"] = str(param_map["公称直径*"]).split(".")[0]

    # 获取鞍座设计温度，取最大值
    val1 = param_map.get("设计温度（最高）*", 0)
    val2 = param_map.get("设计温度2（设计工况2）", 0)

    try:
        max_temp = max(float(val1 or 0), float(val2 or 0))
    except:
        max_temp = 0

    diaoer["设计温度"] = str(int(max_temp))
    cursor.execute("""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = '管箱吊耳'
            """, (product_id,))
    rows = cursor.fetchall()
    extra_map = {r["参数名称"]: r["参数值"] for r in rows}

    if "材料类型" in extra_map:
        raw_type = extra_map["材料类型"]
        diaoer["材料类型"] = material_type_map.get(raw_type, raw_type)
    if "材料牌号" in extra_map:
        diaoer["材料牌号"] = extra_map["材料牌号"]
    if "是否带垫板" in extra_map:
        is_dianban = extra_map["是否带垫板"]
        if is_dianban == "是":
            diaoer["是否带垫板"] = "1"
        else:
            diaoer["是否带垫板"] = "0"

    # 初始化默认值
    guanxiang_yuantong = {
        "预设厚度1": "8",
        "预设厚度2": "10",
        "预设厚度3": "12",
        "圆筒使用位置": "容器圆筒",
        "圆筒名义厚度": "0",
        "圆筒内/外径": "1000",
        "是否按外径计算": "1",
        "液柱静压力": "0",
        "用户自定义MAWP": "0",
        "耐压试验温度": "15",
        "耐压试验压力": "0",
        "圆筒长度": "1200",
        "外压圆筒计算长度": "1200",
        "材料类型": "板材",
        "材料牌号": "Q345R",
        "腐蚀裕量": "1",
        "焊接接头系数": "1",
        "压力试验类型": "液压",
        "覆层复合方式": "轧制复合",
        "圆筒覆层厚度": "0",
        "圆筒带覆层时的焊接凹槽深度": "0",
        "泊松比": "0.3",
        "换热管长度": "",
        "是否覆层": "0",
        "覆层材料类型": "钢板",
        "公称直径": "",
        "指定内径": ""
    }

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()
        cursor.execute("""
                   SELECT 壳程数值
                   FROM 产品设计活动表_设计数据表
                   WHERE 产品ID = %s AND 参数名称 = '耐压试验温度'
               """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["壳程数值"].strip() if row and row.get("壳程数值") else None
        guanxiang_yuantong["耐压试验温度"] = raw_val

        # 查询设计数据表，获取公称直径*
        cursor.execute("""
                   SELECT 壳程数值
                   FROM 产品设计活动表_设计数据表
                   WHERE 产品ID = %s AND 参数名称 = '公称直径*'
               """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["壳程数值"].strip() if row and row.get("壳程数值") else None
        guanxiang_yuantong["公称直径"] = raw_val
        guanxiang_yuantong["圆筒内/外径"] = raw_val
        raw_val2 = row["壳程数值"].strip() if row and row.get("壳程数值") else None
        cursor.execute("""
            SELECT 壳程数值 FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
        """, (product_id,))
        row = cursor.fetchone()
        waijing_bool = ""
        if row and "壳程数值" in row:
            waijing_bool = "1" if row["壳程数值"] == "是" else "0"
        if waijing_bool == "1":
            guanxiang_yuantong["指定内径"] = "0"
            cursor.execute("""
                   SELECT 参数值 FROM 产品设计活动表_布管参数表
                   WHERE 产品ID = %s AND 参数名 = '管箱内直径 Dit'
               """, (product_id,))
            row = cursor.fetchone()
            if row and "参数值" in row:
                guanxiang_yuantong["指定内径"] = str(row["参数值"])
            else:
                guanxiang_yuantong["指定内径"] = "0"
            cursor.execute("""
                        SELECT 数值 FROM 产品设计活动表_通用数据表
                        WHERE 产品ID = %s AND 参数名称 = '外径'
                    """, (product_id,))
            row_waijing = cursor.fetchone()
            if row_waijing and "数值" in row_waijing:
                guanxiang_yuantong["圆筒内/外径"] = row_waijing["数值"]
        else:
            guanxiang_yuantong["指定内径"] = raw_val2

        # === 查询换热管公称长度 LN ===
        cursor.execute("""
            SELECT 参数值
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 = '换热管公称长度 LN'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["参数值"].strip() if row and row.get("参数值") else None

    except Exception as e:
        print(f" 查询失败: {e}")

    # === 处理参数值（空或无效则默认 6000） ===
    tube_length = raw_val if raw_val not in (None, "", " ", "None") else "6000"

    # 写入 qiaoti_yuantong
    guanxiang_yuantong["换热管长度"] = tube_length
    cursor.execute("""
           SELECT 参数名称, 参数值 
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s AND 元件名称 = '圆筒'
       """, (product_id,))
    extra_rows = cursor.fetchall()
    extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}

    # 是否添加覆层
    if extra_map.get("是否添加覆层") == "是":
        guanxiang_yuantong["是否覆层"] = "1"
        guanxiang_yuantong["覆层材料类型"] = extra_map.get("覆层材料类型", "")
        guanxiang_yuantong["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        guanxiang_yuantong["圆筒覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
        if guanxiang_yuantong["覆层材料类型"] == "钢板":
            guanxiang_yuantong["圆筒带覆层时的焊接凹槽深度"] = extra_map.get("存在覆层时的焊接凹槽深度",
                                                                             "0")  # 若为空可改为 "未知"
        else:
            guanxiang_yuantong["圆筒带覆层时的焊接凹槽深度"] = "0"  # 若为空可改为 "未知"

    else:
        guanxiang_yuantong["覆层材料类型"] = "钢板"
        guanxiang_yuantong["是否覆层"] = "0"
        guanxiang_yuantong["覆层复合方式"] = "无"
        guanxiang_yuantong["圆筒覆层厚度"] = "0"
        guanxiang_yuantong["圆筒带覆层时的焊接凹槽深度"] = "0"
    # === 查询数据库 ===
    cursor.execute("""
        SELECT 参数名称, 壳程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()

    # === 构建参数映射表 ===
    param_map = {row["参数名称"].strip(): row for row in rows}

    # === 获取两个自定义耐压试验压力 ===
    def parse_float(value):
        try:
            return float(value)
        except:
            return None

    val1 = parse_float(param_map.get("自定义耐压试验压力（卧）", {}).get("壳程数值", ""))
    val2 = parse_float(param_map.get("自定义耐压试验压力（立）", {}).get("壳程数值", ""))

    # === 最大允许工作压力（壳程数值） ===
    value = param_map.get("最大允许工作压力", {}).get("壳程数值")
    if value not in [None, ""]:
        guanxiang_yuantong["最大允许工作压力"] = str(value)

    # === 耐压试验压力：取最大值 ===
    if val1 is not None and val2 is not None:
        guanxiang_yuantong["耐压试验压力"] = str(max(val1, val2))
    elif val1 is not None:
        guanxiang_yuantong["耐压试验压力"] = str(val1)
    elif val2 is not None:
        guanxiang_yuantong["耐压试验压力"] = str(val2)
    else:
        guanxiang_yuantong["耐压试验压力"] = "0"

    # ===== 获取预设厚度1~3（来自元件附加参数表）=====
    cursor.execute("""
        SELECT 参数名称, 参数值 FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '圆筒'
    """, (product_id,))
    rows = cursor.fetchall()
    extra_param_map = {r["参数名称"].strip(): r["参数值"] for r in rows}

    # 写入 guangxiang_fengtou 中的预设厚度
    for i in range(1, 4):
        key = f"预设厚度{i}"
        if key in extra_param_map:
            guanxiang_yuantong[key] = str(extra_param_map[key])

    # 从数据库获取“是否以外径为基准*”的壳程数值
    cursor.execute("""
        SELECT 壳程数值 FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
    """, (product_id,))
    row = cursor.fetchone()
    if row and "壳程数值" in row:
        guanxiang_yuantong["是否按外径计算"] = "1" if row["壳程数值"] == "是" else "0"
    # 查询设计数据表，获取公称直径*

    map3 = {
        "液柱静压力": "液柱静压力",
        "用户自定义MAWP": "最高允许工作压力",
        "腐蚀裕量": "腐蚀裕量*",
        "焊接接头系数": "焊接接头系数*",

    }

    for key, param_name in map3.items():
        value = param_map.get(param_name, {}).get("壳程数值", "")
        if value != "":
            guanxiang_yuantong[key] = str(value)

    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '圆筒'
    """, (product_id,))
    rows = cursor.fetchall()
    extra_map = {r["参数名称"]: r["参数值"] for r in rows}

    if "材料类型" in extra_map:
        raw_type = extra_map["材料类型"]
        guanxiang_yuantong["材料类型"] = material_type_map.get(raw_type, raw_type)
    if "材料牌号" in extra_map:
        guanxiang_yuantong["材料牌号"] = extra_map["材料牌号"]
    # ===== 压力试验类型（仅去掉末尾“试验”）=====
    if "耐压试验类型*" in param_map:
        val = param_map["耐压试验类型*"].get("壳程数值", "")
        if val:
            guanxiang_yuantong["压力试验类型"] = str(val).replace("试验", "").strip()

        # 初始化默认值
    anzuo = {
        "公称直径": "1000",
        "鞍座设计温度": "50",
        "筋板材料类型": "钢板",
        "筋板材料牌号": "Q345R",
        "筋板名义厚度": "10",
        "腹板材料类型": "钢板",
        "腹板材料牌号": "Q345R",
        "腹板名义厚度": "12",
        "底板材料类型": "钢板",
        "底板材料牌号": "Q345R",
        "底板名义厚度": "15",
        "壳程入口接管法兰外径": "30",
        "壳程出口接管法兰外径": "40",
        "锥壳上是否有接管": "是",
        "试验压力": "2.5",
        "圆筒内直径": "1000",
        "圆筒腐蚀裕量": "3",
        "圆筒名义厚度": "10",
        "圆筒长度": "4000",
        "焊接接头系数": "1",
        "圆筒材料类型": "钢板",
        "圆筒材料牌号": "Q345R",
        "耐压试验温度": "25",
        "封头腐蚀裕量": "3",
        "封头名义厚度": "10",
        "封头曲面深度": "250",
        "封头直边高度": "25",
        "封头材料类型": "钢板",
        "封头材料牌号": "Q345R",
        "封头类型": "1",
        "鞍座高度": "200",
        "鞍座包角": "120",
        "鞍座宽度": "200",
        "垫板宽度": "330",
        "垫板名义厚度": "8",
        "鞍座腹板长度": "740",
        "筋板块数": "4",
        "筋板长度": "140",
        "筋板厚度": "12",
        "容器与鞍座安装形式": "焊接",
        "地脚螺栓材料牌号": "35CrMo",
        "地脚螺栓公称直径": "M24",
        "筒体轴线两侧螺栓间距": "600",
        "一个鞍座上地脚螺栓个数": "2",
        "腹板位置": "1",
        "操作时物料密度": "1000",
        "液压试验介质密度": "1000",
        "物料充装系数": "0.8",
        "内件及附件重量": "200",
        "地震烈度": "0.3g",
        "基础类型": "1",
        "设备配置是否有附属设备": "是",
        "附属设备内径": "300",
        "附属设备筒体名义厚度": "16",
        "附属设备筒体高度": "425",
        "附属设备总高": "500",
        "附属设备地震力作用中心到筒体外表面距离": "350",
        "附属设备轴线至左鞍座距离": "1000",
        "附属设备内件及附件重量": "50",
        "封头质量曲面部分": "168.553",
        "封头容积曲面部分": "130900000",
        "耐热层质量": "0",
        "附属设备封头质量": "16.6",
        "附属设备封头容积曲面部分": "5000000",
        "附属设备隔热层质量": "0",
        "操作工况附属设备内充液质量": "0",
        "圆筒材料负偏差": "0.3",
        "封头材料负偏差": "0.3",
        "鞍座间距": "3000",
        "管束和筒体质量": "7982",
        "管束抽芯力": "88000",
        "摩擦系数": "0.47",
        "鞍座数量": "2",
        "承受水平分力的腹板和垫板有效截面积": "10880",
        "鞍座有效断面抗弯模量": "115681",
        "圆筒最低表面至基础表面的距离": "216",
        "鞍座允许载荷": "147"
    }

    # === 1. 获取管口表数据（壳程入口、壳程出口）===
    cursor.execute("""
        SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
        FROM 产品设计活动表_管口表
        WHERE 产品ID = %s AND 管口功能 IN ('壳程入口', '壳程出口')
    """, (product_id,))
    ports = cursor.fetchall()

    # === 2. 获取管口类型选择表 (尺寸/压力类型) ===
    cursor.execute("""
        SELECT 公称尺寸类型, 公称压力类型
        FROM 产品设计活动表_管口类型选择表
        WHERE 产品ID = %s
    """, (product_id,))
    type_info = cursor.fetchone()  # 一个产品只会有一行配置

    # 默认类型（防止为空）
    size_type = type_info["公称尺寸类型"] if type_info else "DN"
    press_type = type_info["公称压力类型"] if type_info else "PN"
    conn_material = pymysql.connect(
        host="localhost", user="root", password="123456",
        database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
    )
    conn_component = pymysql.connect(
        host="localhost", user="root", password="123456",
        database="元件库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
    )

    cur2 = conn_material.cursor()
    cur3 = conn_component.cursor()
    # === 3 . 获取公称尺寸 NPS → DN 对照表 ===
    cur3.execute("SELECT NPS, DN FROM 公称尺寸表")
    nps_rows = cur3.fetchall()
    nps_map = {str(r["NPS"]).strip(): str(r["DN"]).strip() for r in nps_rows}

    # === 4. 获取管法兰外径表数据 ===
    cur2.execute("SELECT * FROM 管法兰外径表")
    flange_rows = cur2.fetchall()

    # === 5. 匹配逻辑 ===
    for port in ports:
        func = port["管口功能"]  # 管程入口 or 管程出口
        size = str(port["公称尺寸"]).strip()
        pressure = str(port["压力等级"]).strip()
        flange_type = str(port["法兰型式"]).strip() if port["法兰型式"] else None

        # --- 公称尺寸处理 ---
        if size_type.upper() == "NPS":
            size = nps_map.get(size, size)  # NPS → DN

        # --- 遍历管法兰外径表匹配 ---
        for row in flange_rows:
            # 标准匹配（包含关系）

            # 公称尺寸匹配（DN列）
            if str(row["DN"]).strip() != size:
                continue
            # 压力等级匹配
            if press_type.upper() == "PN":
                if str(row["PN"]).strip() != pressure:
                    continue
            elif press_type.upper() == "CLASS":
                if str(row["Class"]).strip() != pressure:
                    continue
            # 法兰型式匹配
            if flange_type and str(row["法兰型式"]).strip() != flange_type:
                continue

            #  获取列D对应的值（法兰外径）
            val = row.get("D")
            if func == "壳程入口":
                anzuo["壳程入口接管法兰外径"] = val
            elif func == "壳程出口":
                anzuo["壳程出口接管法兰外径"] = val

            break  # 找到匹配项就退出

    # 输出结果
    print("壳程入口接管法兰外径:", anzuo["壳程入口接管法兰外径"])
    print("壳程出口接管法兰外径:", anzuo["壳程出口接管法兰外径"])

    # 查询设计数据表中对应产品ID的数据
    cursor.execute("""
        SELECT 参数名称, 壳程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row["壳程数值"] for row in rows}

    # 获取公称直径
    if "公称直径*" in param_map:
        anzuo["公称直径"] = str(param_map["公称直径*"]).split(".")[0]

    # 获取鞍座设计温度，取最大值
    val1 = param_map.get("设计温度（最高）*", 0)
    val2 = param_map.get("设计温度2（设计工况2）", 0)

    try:
        max_temp = max(float(val1 or 0), float(val2 or 0))
    except:
        max_temp = 0

    anzuo["鞍座设计温度"] = str(int(max_temp))
    # # 读取当前产品ID对应的所有数据
    cursor.execute("""
        SELECT Tab分类, 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数合并表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()

    # 构建一个以Tab分类为层级的字典结构
    tab_data = defaultdict(list)
    for r in rows:
        tab_data[r["Tab分类"]].append(r)

    anzuos = ["筋板", "腹板", "底板"]

    # 遍历每个目标元件
    for part in anzuos:
        found = False  # 标记是否找到对应材料信息

        # 优先在同一Tab分类中查找
        for tab, params in tab_data.items():
            # 查找当前Tab下的“元件名称”项
            component_names = [
                eval(p["参数值"]) if isinstance(p["参数值"], str) and p["参数值"].startswith("[") else p["参数值"]
                for p in params if p["参数名称"] == "元件名称"
            ]

            # 若元件名称匹配当前目标
            matched = any(part in cn for cn in component_names if isinstance(cn, list))

            if matched:
                # 查找该Tab下的材料信息
                type_row = next((p for p in params if p["参数名称"] == "材料类型"), None)
                grade_row = next((p for p in params if p["参数名称"] == "材料牌号"), None)

                if type_row or grade_row:
                    anzuo[f"{part}材料类型"] = str(type_row["参数值"]) if type_row else ""
                    anzuo[f"{part}材料牌号"] = str(grade_row["参数值"]) if grade_row else ""
                    found = True
                    break  # 找到后不查找其他Tab

        # 若在所有Tab中都没找到该元件的材料信息，则为空
        if not found:
            anzuo[f"{part}材料类型"] = ""
            anzuo[f"{part}材料牌号"] = ""

    def build_jieguan(cursor, product_id, guankou_daihao):
        jieguan = {
            "设备公称直径": "1000",
            "接管是否以外径为基准": "0",
            "接管腐蚀余量": "0",
            "接管焊接接头系数": "1",
            "正常操作工况下操作温度变化范围": "20",
            "接管名义厚度": "0",
            "接管内/外径": "50",
            "接管类型": "1",
            "接管中心线至筒体轴线距离(偏心距)": "0",
            "接管中心线与法线夹角(包括封头)": "0",
            "椭圆形/长圆孔与筒体轴向方向的直径": "0",
            "椭圆形/长圆孔与筒体切向方向的直径": "0",
            "接管实际外伸长度": "300",
            "接管实际内伸长度": "0",
            "接管有效宽度B": "0",
            "接管有效补强外伸长度": "0",
            "接管材料减薄率": "10",
            "接管设计余量": "0",
            "接管覆层厚度": "1",
            "接管最小有效外伸高度系数": "0.8",
            "焊缝面积A3焊脚高度系数": "0.7",
            "开孔补强自定义补强面积裕量百分比": "0",
            "补强区内的焊缝面积(含嵌入式接管焊缝面积)": "49",
            "补强圈材料类型": "板材",
            "补强圈材料牌号": "Q345R",
            "开孔元件名称": "圆筒",
            "接管材料类型1": "",
            "接管材料牌号1": "",
            "接管材料类型2": "",
            "接管材料牌号2": "",
            "接管材料类型3": "",
            "接管材料牌号3": "",
            "接管是否覆层1": "",
            "接管覆层材料类型1": "",
            "接管覆层复合方式1": "",
            "接管覆层厚度1": "",
            "接管带覆层时的焊接凹槽深度1": "",
            "接管是否覆层2": "",
            "接管覆层材料类型2": "",
            "接管覆层复合方式2": "",
            "接管覆层厚度2": "",
            "接管带覆层时的焊接凹槽深度2": "",
            "接管是否覆层3": "",
            "接管覆层材料类型3": "",
            "接管覆层复合方式3": "",
            "接管覆层厚度3": "",
            "接管带覆层时的焊接凹槽深度3": "",
            "管口表序号": guankou_daihao,
            "是否覆层": "",
            "覆层材料类型": "",
            "所属元件开孔处焊接接头系数": ""
        }
        cursor.execute("""
            SELECT 管口功能, 管口所属元件, 公称尺寸,
                   偏心距, `轴向夹角（°）`, 外伸高度
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口代号 = %s
            LIMIT 1
        """, (product_id, guankou_daihao))
        row = cursor.fetchone()

        if row:
            jieguan["开孔元件名称"] = str(row.get("管口所属元件", "") or "").strip()
            if jieguan["开孔元件名称"] == "壳程大端圆筒":
                jieguan["开孔元件名称"] = "大端壳体圆筒"

            jieguan["接管中心线至筒体轴线距离(偏心距)"] = str(row.get("偏心距", "0") or "0")
            jieguan["接管中心线与法线夹角(包括封头)"] = str(row.get("轴向夹角（°）", "0") or "0")
            jieguan["接管实际外伸长度"] = str(row.get("外伸高度", "0") or "0")

        # 程序推荐兜底
        if jieguan.get("接管实际外伸长度") == "程序推荐":
            jieguan["接管实际外伸长度"] = "0"

        cursor.execute("""
            SELECT 参数名称, 壳程数值
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s AND 参数名称 IN ('工作温度（入口）', '工作温度（出口）')
        """, (product_id,))
        rows = cursor.fetchall()

        # 初始化入口/出口温度
        temp_in = None
        temp_out = None

        for row in rows:
            name = str(row.get("参数名称", "") or "").strip()
            value = row.get("壳程数值")
            try:
                float_val = float(value) if value not in (None, "", "None") else None
            except:
                float_val = None

            if name == "工作温度（入口）":
                temp_in = float_val
                print(temp_in)
            elif name == "工作温度（出口）":
                temp_out = float_val
                print(temp_out)

        # 计算绝对差值并赋值
        if temp_in is not None and temp_out is not None:
            delta_temp = abs(temp_out - temp_in)
            print(delta_temp)
            jieguan["正常操作工况下操作温度变化范围"] = str(int(delta_temp))
        else:
            jieguan["正常操作工况下操作温度变化范围"] = "10"  # 默认值

        def clean_val(v):
            if v in (None, "", "None"):
                return ""
            return str(v).strip()

        # === 获取管口类别表信息（材料分类 + 专属腐蚀裕量 + 焊接接头系数）===
        cursor.execute("""
            SELECT 材料分类,
                   `接管腐蚀裕量1`,
                   `接管腐蚀裕量2`,
                   `接管腐蚀裕量3`,
                   `所属元件开孔处焊接接头系数`
            FROM 产品设计活动表_管口类别表
            WHERE 产品ID = %s AND 管口代号 = %s
            LIMIT 1
        """, (product_id, guankou_daihao))
        category_row = cursor.fetchone() or {}

        category = clean_val(category_row.get("材料分类"))
        print(f" 管口代号 {guankou_daihao} 使用材料分类: {category if category else '统一材料'}")

        # === 根据材料分类，从附加参数表里取材料参数（原逻辑兜底）===
        material_map = {}
        if category:
            cursor.execute("""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_管口附加参数表
                WHERE 产品ID = %s AND 类别 = %s
                  AND 参数名称 IN (
                      '接管材料类型1','接管材料类型2','接管材料类型3',
                      '接管材料牌号1','接管材料牌号2','接管材料牌号3',
                      '接管腐蚀裕量1','接管腐蚀裕量2','接管腐蚀裕量3'
                  )
            """, (product_id, category))
            material_rows = cursor.fetchall()

            material_map = {
                str(r.get("参数名称") or "").strip(): clean_val(r.get("参数值"))
                for r in material_rows
                if r.get("参数名称")
            }

        # 更新到 jieguan
        for i in range(1, 4):
            # 材料类型 / 材料牌号：仍按原逻辑从附加参数表取
            jieguan[f"接管材料类型{i}"] = material_map.get(f"接管材料类型{i}", "")
            jieguan[f"接管材料牌号{i}"] = material_map.get(f"接管材料牌号{i}", "")

            # 腐蚀余量：优先从管口类别表按管口代号取，取不到再走原逻辑兜底
            corrosion_from_category = clean_val(category_row.get(f"接管腐蚀裕量{i}"))
            corrosion_from_extra = material_map.get(f"接管腐蚀裕量{i}", "")
            jieguan[f"接管腐蚀余量{i}"] = corrosion_from_category or corrosion_from_extra

        # 所属元件开孔处焊接接头系数：优先从管口类别表按管口代号取
        jieguan["所属元件开孔处焊接接头系数"] = clean_val(
            category_row.get("所属元件开孔处焊接接头系数")
        )

        # 焊接接头系数兜底：如果类别表没有，就按你的原逻辑默认
        if not jieguan["所属元件开孔处焊接接头系数"]:
            jieguan["所属元件开孔处焊接接头系数"] = "1.0"

        # ===== 获取公称直径、绝热厚度、毒性/爆炸危险等 =====

        print(f" 材料分类（{guankou_daihao}）: {category if category else '统一材料'}")
        print(" 接管腐蚀余量1:", jieguan.get("接管腐蚀余量1", ""))
        print(" 接管腐蚀余量2:", jieguan.get("接管腐蚀余量2", ""))
        print(" 接管腐蚀余量3:", jieguan.get("接管腐蚀余量3", ""))
        print(" 所属元件开孔处焊接接头系数:", jieguan.get("所属元件开孔处焊接接头系数", ""))

        # === 获取管口功能 ===
        cursor.execute("""
            SELECT 管口功能
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口代号 = %s
            LIMIT 1
        """, (product_id, guankou_daihao))
        row = cursor.fetchone()
        guankou_gongneng = row["管口功能"].strip() if row and row["管口功能"] else ""
        print(f" 管口功能: {guankou_gongneng}")
        # === 获取管口功能和所属元件 ===
        cursor.execute("""
            SELECT 管口功能, 管口所属元件, 公称尺寸
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口代号 = %s
            LIMIT 1
        """, (product_id, guankou_daihao))
        row = cursor.fetchone()

        guankou_gongneng = row["管口功能"].strip() if row and row["管口功能"] else ""
        suoshuyuanjian = row["管口所属元件"].strip() if row and row["管口所属元件"] else ""
        gongcheng_size = row["公称尺寸"] if row else None

        print(f" 管口功能: {guankou_gongneng}")
        print(f" 所属元件: {suoshuyuanjian}")

        if gongcheng_size is not None:
            jieguan["接管内/外径"] = str(gongcheng_size)
        cursor.execute("""
            SELECT 参数名称, 壳程数值
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s
        """, (product_id,))
        rows = cursor.fetchall()
        param_map = {str(row["参数名称"]).strip(): row for row in rows if row.get("参数名称")}

        # 公称直径（管程）
        if "公称直径*" in param_map:
            jieguan["设备公称直径"] = str(param_map["公称直径*"].get("壳程数值", "") or "")

        # ==========================================================
        # 获取当前类别对应的接管覆层参数
        # ==========================================================
        def get_category_extra_params(
                cursor,
                product_id,
                category,
                parameter_names
        ):
            """
            从“产品设计活动表_管口附加参数表”中读取指定类别的参数。

            获取规则：
            1. 先读取类别为空的通用参数；
            2. 再读取当前管口材料分类对应的参数；
            3. 当前类别的参数覆盖通用参数；
            4. 绝不会读取其他材料分类的参数。

            这样既能够保证按照类别分别获取，
            又能够在当前类别某个参数没有配置时使用通用参数兜底。
            """
            parameter_names = tuple(parameter_names)

            if not parameter_names:
                return {}

            placeholders = ", ".join(["%s"] * len(parameter_names))

            def rows_to_map(rows):
                result = {}

                for item in rows or []:
                    param_name = clean_val(item.get("参数名称"))
                    param_value = clean_val(item.get("参数值"))

                    if param_name:
                        result[param_name] = param_value

                return result

            # ------------------------------------------------------
            # 1. 查询类别为空的通用参数
            # ------------------------------------------------------
            common_sql = f"""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_管口附加参数表
                WHERE 产品ID = %s
                  AND (
                        类别 IS NULL
                        OR TRIM(类别) = ''
                      )
                  AND 参数名称 IN ({placeholders})
            """

            common_params = (product_id, *parameter_names)
            cursor.execute(common_sql, common_params)
            common_rows = cursor.fetchall() or []

            result_map = rows_to_map(common_rows)

            # ------------------------------------------------------
            # 2. 查询当前材料分类对应的专属参数
            # ------------------------------------------------------
            current_category = clean_val(category)

            if current_category:
                category_sql = f"""
                    SELECT 参数名称, 参数值
                    FROM 产品设计活动表_管口附加参数表
                    WHERE 产品ID = %s
                      AND TRIM(类别) = %s
                      AND 参数名称 IN ({placeholders})
                """

                category_params = (
                    product_id,
                    current_category,
                    *parameter_names
                )

                cursor.execute(category_sql, category_params)
                category_rows = cursor.fetchall() or []

                category_map = rows_to_map(category_rows)

                # 当前类别参数覆盖通用参数
                result_map.update(category_map)

            return result_map

        # ==========================================================
        # 接管覆层参数按第 1、2、3 组分别读取和输出
        # ==========================================================
        #
        # 兼容两类参数名称：
        # 1. 当前附加参数表中使用的名称：
        #    接管是否添加覆层1、接管覆层成型工艺1、
        #    接管存在覆层时的焊接凹槽深度1 等；
        # 2. 输出字段使用的名称：
        #    接管是否覆层1、接管覆层复合方式1、
        #    接管带覆层时的焊接凹槽深度1 等。
        #
        # 同时保留旧版未带序号的第 1 组参数作为兼容兜底。
        cover_parameter_names = [
            # 旧版第1组未带序号的兼容参数
            "接管是否添加覆层",
            "接管是否覆层",
            "接管覆层材料类型",
            "接管覆层成型工艺",
            "接管覆层复合方式",
            "接管覆层厚度",
            "接管存在覆层时的焊接凹槽深度",
            "接管带覆层时的焊接凹槽深度",
        ]

        for i in range(1, 4):
            cover_parameter_names.extend([
                f"接管是否添加覆层{i}",
                f"接管是否覆层{i}",
                f"接管覆层材料类型{i}",
                f"接管覆层成型工艺{i}",
                f"接管覆层复合方式{i}",
                f"接管覆层厚度{i}",
                f"接管存在覆层时的焊接凹槽深度{i}",
                f"接管带覆层时的焊接凹槽深度{i}",
            ])

        cover_map = get_category_extra_params(
            cursor=cursor,
            product_id=product_id,
            category=category,
            parameter_names=cover_parameter_names
        )

        def get_first_cover_value(*parameter_names):
            """
            按给定顺序取第一个非空覆层参数，兼容新旧参数名称。
            """
            for parameter_name in parameter_names:
                value = clean_val(cover_map.get(parameter_name))
                if value:
                    return value
            return ""

        def parse_cover_flag(value):
            """
            将数据库中的是否值统一转换为 True/False。
            """
            normalized = clean_val(value).lower()

            if normalized in {"是", "有", "1", "true", "yes", "y"}:
                return True

            if normalized in {"否", "无", "0", "false", "no", "n"}:
                return False

            return None

        for i in range(1, 4):
            # -----------------------------------------------
            # 1. 分别读取第 i 组覆层参数
            # -----------------------------------------------
            cover_flag_raw = get_first_cover_value(
                f"接管是否添加覆层",
                f"接管是否覆层{i}",
                # 仅第1组兼容旧版未带序号的参数
                *(
                    ("接管是否添加覆层", "接管是否覆层")
                    if i == 1 else ()
                )
            )

            cover_material_type = get_first_cover_value(
                f"接管覆层材料类型{i}",
                *(("接管覆层材料类型",) if i == 1 else ())
            )

            cover_compound_method = get_first_cover_value(
                f"接管覆层复合方式{i}",
                f"接管覆层成型工艺{i}",
                *(
                    ("接管覆层复合方式", "接管覆层成型工艺")
                    if i == 1 else ()
                )
            )

            cover_thickness = get_first_cover_value(
                f"接管覆层厚度{i}",
                *(("接管覆层厚度",) if i == 1 else ())
            )

            cover_groove_depth = get_first_cover_value(
                f"接管带覆层时的焊接凹槽深度{i}",
                f"接管存在覆层时的焊接凹槽深度{i}",
                *(
                    (
                        "接管带覆层时的焊接凹槽深度",
                        "接管存在覆层时的焊接凹槽深度"
                    )
                    if i == 1 else ()
                )
            )

            # -----------------------------------------------
            # 2. 判断第 i 组是否覆层
            # -----------------------------------------------
            has_cover = parse_cover_flag(cover_flag_raw)

            # 如果是否覆层没有明确配置，但第 i 组已经配置了覆层参数，
            # 则自动判定该组存在覆层，避免有效参数被忽略。
            if has_cover is None:
                has_cover = any([
                    cover_material_type,
                    cover_compound_method,
                    cover_thickness not in ("", "0", "0.0"),
                    cover_groove_depth not in ("", "0", "0.0"),
                ])

            # -----------------------------------------------
            # 3. 按序号写入 jieguan
            # -----------------------------------------------
            if has_cover:
                jieguan[f"接管是否覆层{i}"] = "1"
                jieguan[f"接管覆层材料类型{i}"] = (
                        cover_material_type or "未知"
                )
                jieguan[f"接管覆层复合方式{i}"] = (
                        cover_compound_method or "轧制复合"
                )
                jieguan[f"接管覆层厚度{i}"] = (
                        cover_thickness or "0"
                )

                # 沿用原来的业务规则：
                # 覆层材料类型为钢板时读取凹槽深度，否则置为 0。
                if jieguan[f"接管覆层材料类型{i}"] == "钢板":
                    jieguan[f"接管带覆层时的焊接凹槽深度{i}"] = (
                            cover_groove_depth or "0"
                    )
                else:
                    jieguan[f"接管带覆层时的焊接凹槽深度{i}"] = "0"
            else:
                jieguan[f"接管是否覆层{i}"] = "0"
                jieguan[f"接管覆层材料类型{i}"] = "钢板"
                jieguan[f"接管覆层复合方式{i}"] = "无"
                jieguan[f"接管覆层厚度{i}"] = "0"
                jieguan[f"接管带覆层时的焊接凹槽深度{i}"] = "0"

        # ==========================================================
        # 兼容旧版未带序号的输出字段
        # 默认取第1组，避免其它旧代码读取不到值。
        # ==========================================================
        jieguan["是否覆层"] = jieguan["接管是否覆层1"]
        jieguan["覆层材料类型"] = jieguan["接管覆层材料类型1"]
        jieguan["覆层复合方式"] = jieguan["接管覆层复合方式1"]
        jieguan["接管覆层厚度"] = jieguan["接管覆层厚度1"]
        jieguan["接管带覆层时的焊接凹槽深度"] = (
            jieguan["接管带覆层时的焊接凹槽深度1"]
        )

        # ==========================================================
        # 获取当前类别对应的补强圈材料参数
        # ==========================================================

        reinforcement_parameter_names = (
            "补强圈材料类型1",
            "补强圈材料牌号1",
            "补强圈材料类型2",
            "补强圈材料牌号2",
            "补强圈材料类型3",
            "补强圈材料牌号3"
        )

        reinforcement_map = get_category_extra_params(
            cursor=cursor,
            product_id=product_id,
            category=category,
            parameter_names=reinforcement_parameter_names
        )

        # 默认值
        jieguan["补强圈材料类型"] = "钢板"
        jieguan["补强圈材料牌号"] = "0"

        # 按照 1、2、3 的顺序选取第一组有效材料
        for i in range(1, 4):
            reinforcement_type = clean_val(
                reinforcement_map.get(f"补强圈材料类型{i}")
            )

            reinforcement_grade = clean_val(
                reinforcement_map.get(f"补强圈材料牌号{i}")
            )

            if reinforcement_type or reinforcement_grade:
                if reinforcement_type:
                    jieguan["补强圈材料类型"] = reinforcement_type
                else:
                    jieguan["补强圈材料类型"] = "0"

                if reinforcement_grade:
                    jieguan["补强圈材料牌号"] = reinforcement_grade
                else:
                    jieguan["补强圈材料牌号"] = "0"

                break

        print(
            f" 管口代号：{guankou_daihao}，"
            f"当前材料分类：{category if category else '通用参数'}"
        )
        print(" 覆层参数：", cover_map)
        for i in range(1, 4):
            print(
                f" 第{i}组覆层："
                f"是否覆层={jieguan.get(f'接管是否覆层{i}', '')}，"
                f"材料类型={jieguan.get(f'接管覆层材料类型{i}', '')}，"
                f"复合方式={jieguan.get(f'接管覆层复合方式{i}', '')}，"
                f"厚度={jieguan.get(f'接管覆层厚度{i}', '')}，"
                f"焊接凹槽深度="
                f"{jieguan.get(f'接管带覆层时的焊接凹槽深度{i}', '')}"
            )
        print(" 补强圈材料参数：", reinforcement_map)
        print(" 补强圈材料类型：", jieguan["补强圈材料类型"])
        print(" 补强圈材料牌号：", jieguan["补强圈材料牌号"])
        cursor.execute("""
            SELECT `偏心距`, `轴向夹角（°）`
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口代号 = %s
        """, (product_id, guankou_daihao))
        row = cursor.fetchone()

        if row:
            # 赋值，若为空则默认为 "0"
            jieguan["接管中心线至筒体轴线距离(偏心距)"] = str(row.get("偏心距") or "0")
            jieguan["接管中心线与法线夹角(包括封头)"] = str(row.get("轴向夹角（°）") or "0")

        # 查询 N1 管口的外伸高度
        cursor.execute("""
            SELECT `外伸高度`
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口代号 = %s
        """, (product_id, guankou_daihao))
        row = cursor.fetchone()

        if row:
            jieguan["接管实际外伸长度"] = str(row.get("外伸高度") or "0")
        # 如果“接管实际内伸长度”或“接管实际外伸长度”为"程序推荐"，则替换为 "0"
        if jieguan.get("接管实际内伸长度") == "程序推荐":
            jieguan["接管实际内伸长度"] = "0"

        if jieguan.get("接管实际外伸长度") == "程序推荐":
            jieguan["接管实际外伸长度"] = "0"

        # 查询 N1 管口的“管口所属元件”
        cursor.execute("""
            SELECT `管口所属元件`
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口代号 = %s
        """, (product_id, guankou_daihao))
        row = cursor.fetchone()
        if row:
            jieguan["开孔元件名称"] = str(row.get("管口所属元件") or "未知")
            if jieguan["开孔元件名称"] == "壳程大端圆筒":
                print(1111111111)
                jieguan["开孔元件名称"] = "大端壳体圆筒"

        return jieguan

    def build_all_jieguan(cursor, product_id):
        cursor.execute("""
            SELECT 管口代号, 管口功能
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s
        """, (product_id,))
        rows = cursor.fetchall()

        jieguan_dict = {}
        for row in rows:
            guankou_daihao = row["管口代号"].strip()
            guankou_gongneng = row["管口功能"].strip()

            # 动态生成一个接管
            jieguan = build_jieguan(cursor, product_id, guankou_daihao)

            # 字典 key = 管口功能 + 接管
            jieguan_dict[f"{guankou_gongneng}接管"] = jieguan

        return jieguan_dict

    jieguan_dict = build_all_jieguan(cursor, product_id)

    dict_datas = {
        "前端封头": guangxiang_fengtou,
        "容器圆筒": guanxiang_yuantong,
        "容器圆筒加强圈": jiaqiangquan,
        "后端封头": keti_fengtou,
        "鞍座": anzuo,
        "吊耳": diaoer,
    }
    # 合并
    dict_datas.update(jieguan_dict)
    apply_head_types(cursor, product_id, dict_part, dict_datas, full_dict)

    # 最终结果
    result = {
        "WSList": wslist,
        "TTDict": ttdict,
        "DesignParams": design_params,
        "DictPart": full_dict,
        "DictDatas": dict_datas
    }

    # 假设你已经连接了“产品需求库”
    # 替换为对应的数据库连接或游标，如：cursor_demand

    cursor.execute("""
        SELECT 产品名称, 产品型式
        FROM 产品需求库.产品需求表
        WHERE 产品ID = %s
    """, (product_id,))
    row = cursor.fetchone()

    if row:
        result["ProjectName"] = row.get("产品名称", "UnnamedProject")
        result["ExchangerType"] = "卧式容器"
    else:
        result["ProjectName"] = "UnnamedProject"
        result["ExchangerType"] = "Unknown"
    #  类型判断并替换结构
    empty_value_excluded_fields = ("材料类型", "材料牌号", "供货状态")

    def deep_map(obj, field_name=""):
        if isinstance(obj, dict):
            named_field = str(obj.get("Name", "")).strip()
            return {
                k: deep_map(
                    v,
                    named_field if k == "Value" and named_field else str(k)
                )
                for k, v in obj.items()
            }
        elif isinstance(obj, list):
            return [deep_map(item, field_name) for item in obj]
        elif obj is None or (isinstance(obj, str) and obj == ""):
            if any(keyword in field_name for keyword in empty_value_excluded_fields):
                return obj
            return "0"
        elif isinstance(obj, str) and obj in material_type_map:
            return material_type_map[obj]
        else:
            return obj

    result = deep_map(result)
    #  删除 WSList 中所有字段都是 "0" 的项
    if "WSList" in result and isinstance(result["WSList"], list):
        result["WSList"] = [
            ws for ws in result["WSList"]
            if not all(str(ws.get(key, "0")) == "0" for key in [
                "ShellWorkingPressure", "TubeWorkingPressure",
                "ShellWorkingTemperature", "TubeWorkingTemperature"
            ])
        ]

    # # 读取JSON文件并转换为紧凑格式
    with open("shuru_jisuan.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)

    # 获取当前脚本所在的绝对路径
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # print("当前脚本路径：", base_dir)
    # print("构造的 DLL 路径：", dll_path)
    # print("DLL 文件是否存在：", os.path.exists(dll_path))

    # # 读取JSON文件并转换为紧凑格式
    with open("shuru_jisuan.json", "r", encoding="utf-8") as f:
        json_input = f.read()
    parsed = json.loads(json_input)
    compact_json = json.dumps(parsed, separators=(',', ':'))
    conn = pymysql.connect(
        host="localhost",  # 改成你的数据库地址
        user="root",  # 改成你的用户名
        password="123456",  # 改成你的密码
        database="产品设计活动库",  # 改成你的数据库名
        charset="utf8mb4"
    )
    cursor = conn.cursor()

    try:
        # 3. 先删除旧数据
        cursor.execute("DELETE FROM 产品设计活动表_计算提交表 WHERE 产品ID = %s", (product_id,))
        cursor.execute("DELETE FROM 产品设计活动表_管口计算提交表 WHERE 产品ID = %s", (product_id,))
        cursor.execute("DELETE FROM 产品设计活动表_设计数据计算提交表 WHERE 产品ID = %s", (product_id,))

        # 4. 插入新数据
        # 4.1 产品设计活动表_计算提交表
        for component_name, kvs in parsed.get("DictDatas", {}).items():
            for k, v in kvs.items():
                cursor.execute("""
                    INSERT INTO 产品设计活动表_计算提交表 (产品ID, 元件名称, `key`, `value`)
                    VALUES (%s, %s, %s, %s)
                """, (product_id, component_name, k, v))

        # 4.2 产品设计活动表_管口计算提交表
        for nozzle_no, kvs in parsed.get("TTDict", {}).items():
            for k, v in kvs.items():
                cursor.execute("""
                    INSERT INTO 产品设计活动表_管口计算提交表 (产品ID, 管口号, `key`, `value`)
                    VALUES (%s, %s, %s, %s)
                """, (product_id, nozzle_no, k, v))

        # 4.3 产品设计活动表_设计数据计算提交表
        # 处理 WSList
        for ws_dict in parsed.get("WSList", []):
            for k, v in ws_dict.items():
                cursor.execute("""
                    INSERT INTO 产品设计活动表_设计数据计算提交表 (产品ID, `key`, `value`)
                    VALUES (%s, %s, %s)
                """, (product_id, k, v))

        # 处理 DesignParams
        for k, v in parsed.get("DesignParams", {}).items():
            cursor.execute("""
                INSERT INTO 产品设计活动表_设计数据计算提交表 (产品ID, `key`, `value`)
                VALUES (%s, %s, %s)
            """, (product_id, k, v))

        # 5. 提交事务
        conn.commit()
        print(f"产品ID {product_id} 的数据已成功保存")

    except Exception as e:
        conn.rollback()
        print("写入数据库失败:", e)
    calculation_result = run_integrated_calculation(compact_json)

    # 保存计算结果
    # with open("modules/qiangdujisuan/jiekou_python/jisuan_output.json", "w", encoding="utf-8") as f:
    with open("jisuan_output_new.json", "w", encoding="utf-8") as f:
        json.dump(json.loads(calculation_result), f, ensure_ascii=False, indent=4)
    with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
        parsed = json.load(f)

    # 一个小工具：把任意对象转成文本（确保中文不转义）
    def _to_text(x):
        if x is None:
            return ""
        if isinstance(x, str):
            return x
        return json.dumps(x, ensure_ascii=False)

    try:
        # === 3) 产品设计活动表_计算结果日志表：只插一行 ===
        cursor.execute("DELETE FROM 产品设计活动表_计算结果日志表 WHERE 产品ID = %s", (product_id,))

        # 1. Logs 数组拼接为一行
        logs_joined = "；".join(_to_text(item) for item in parsed.get("Logs", []))

        # 2. 元件结果：元件名=IsSuccess
        dict_out = parsed.get("DictOutDatas", {}) or {}
        comp_results = []
        for comp_name, comp_dict in dict_out.items():
            if isinstance(comp_dict, dict):
                is_success = comp_dict.get("IsSuccess")
                comp_results.append(f"{comp_name}={_to_text(is_success)}")
        comp_results_joined = "；".join(comp_results)

        # 插入一条记录
        cursor.execute("""
                INSERT INTO 产品设计活动表_计算结果日志表 (产品ID, Logs, 元件结果)
                VALUES (%s, %s, %s)
            """, (product_id, logs_joined, comp_results_joined))

        # ========== 产品设计活动表_元件计算结果表 ==========
        cursor.execute("DELETE FROM 产品设计活动表_元件计算结果表 WHERE 产品ID = %s", (product_id,))

        dict_out = parsed.get("DictOutDatas", {}) or {}
        if not isinstance(dict_out, dict):
            dict_out = {}

        for comp_name, comp_dict in dict_out.items():
            if not isinstance(comp_dict, dict):
                continue  # 跳过异常格式

            datas_list = comp_dict.get("Datas", []) or []
            if not isinstance(datas_list, list):
                continue  # 跳过异常格式

            for data_item in datas_list:
                if not isinstance(data_item, dict):
                    continue  # 保证 data_item 可用 .get

                cursor.execute("""
                    INSERT INTO 产品设计活动表_元件计算结果表 (产品ID, 元件名称, Id, Name, Value)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    product_id,
                    comp_name,
                    data_item.get("Id"),
                    data_item.get("Name"),
                    data_item.get("Value")
                ))

        conn.commit()
        print(f"产品ID {product_id} 的计算结果已成功保存")

    except Exception as e:
        conn.rollback()
        print("写入数据库失败:", e)
    return calculation_result


if __name__ == "__main__":
    product_id = 'PD2025112014095201'
    # product_id = 'PD20250706001'  # 替换为你自己的产品ID
    result = calculate_heat_exchanger_strength(product_id)
    print(result)
