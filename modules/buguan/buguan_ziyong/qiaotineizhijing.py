import os
import re
import string
import sys
from collections import defaultdict
import math
import os
import re
import string
import sys
from collections import defaultdict
import pymysql

import configparser

import chardet
import pymysql
import json
import clr
import configparser

import chardet
import json
import clr

from modules.chanpinguanli.chanpinguanli_main import product_manager


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
product_id = None


def on_product_id_changed(new_id):
    print(f"Received new PRODUCT_ID: {new_id}")
    global product_id
    product_id = new_id


# 测试用产品 ID（真实情况中由外部输入）
product_manager.product_id_changed.connect(on_product_id_changed)


def cal_qiaotineizhijing_U(product_id, isDi_change, isDN_change, user_Di, user_DN):
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
            SELECT 参数名称, 壳程数值, 管程数值
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s
        """, (product_id,))
    rows = cursor.fetchall()

    # 参数名映射
    ws_mapping = {
        "设计压力*": ("ShellWorkingPressure", "TubeWorkingPressure"),
        "设计温度（最高）*": ("ShellWorkingTemperature", "TubeWorkingTemperature"),
        "设计压力2（设计工况2）": ("ShellWorkingPressure", "TubeWorkingPressure"),
        "设计温度2（设计工况2）": ("ShellWorkingTemperature", "TubeWorkingTemperature"),
    }

    # 填写数据
    for row in rows:
        param = row["参数名称"].strip()
        shell_val, tube_val = row["壳程数值"], row["管程数值"]
        if param in ws_mapping:
            shell_key, tube_key = ws_mapping[param]
            if "2" in param:
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

        ttdict[key] = {
            "ttNo": 0,
            "ttCode": clean_value(row.get("管口代号")),
            "ttUse": clean_value(row.get("管口功能")),
            "ttDN": clean_value(row.get("公称尺寸")),
            "ttPClass": clean_value(row.get("压力等级")),
            "ttDType": pipe_type_default["公称尺寸类型"],
            "ttPType": pipe_type_default["公称压力类型"],
            "ttType": "WN",
            "ttRF": clean_value(row.get("密封面型式")),
            "ttSpec": "默认" if clean_value(row.get("焊端规格")) == "程序推荐" else clean_value(row.get("焊端规格")),
            "ttAttach": clean_value(row.get("管口所属元件")),
            "ttPlace": {
                "左基准线": "左轮廓线",
                "右基准线": "右轮廓线"
            }.get(row.get("轴向定位基准", ""), clean_value(row.get("轴向定位基准"))),
            "ttLoc": "默认" if clean_value(row.get("轴向定位距离")) == "程序推荐" else clean_value(
                row.get("轴向定位距离")),
            "ttFW": clean_value(zhouxiangfangwei),
            "ttThita": clean_value(row.get("偏心距")),
            "ttAngel": clean_value(axial_angle),
            "ttH": ttH_val,
            "ttMemo": "默认"
        }

    # ===== 预设默认值 =====
    design_params = {
        "公称直径": "1000",
        "是否以外径为基准": "1",
        "介质类型": "介质易爆/极度危害/高度危害",
        "管箱圆筒长度工况": "工况1",
        "绝热厚度": "4",
        "管/壳程布置型式": "2.1"
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
        if tube_form == "2":
            design_params["管/壳程布置型式"] = "2.1"
        # === 查询设计数据表 ===
        cursor.execute("""
                SELECT 参数名称, 壳程数值, 管程数值
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s
            """, (product_id,))
        rows = cursor.fetchall()
        param_map = {row["参数名称"].strip(): row for row in rows}
    except Exception as e:
        print(f"❌ 查询失败: {e}")
    # 公称直径分类讨论
    if isDN_change:
        design_params["公称直径"] = user_DN
    else:
        # 公称直径（管程）
        if "公称直径*" in param_map:
            design_params["公称直径"] = str(param_map["公称直径*"].get("管程数值", ""))

    # 绝热厚度（管程）
    if "绝热层厚度" in param_map:
        design_params["绝热厚度"] = str(param_map["绝热层厚度"].get("管程数值", ""))

    # 介质类型 = 爆炸危险性 + 壳程毒性 + 管程毒性
    media_parts = []
    if "介质特性（爆炸危险程度）" in param_map:
        expl = param_map["介质特性（爆炸危险程度）"].get("壳程数值", "")
        if expl == "可燃":
            media_parts.append("介质易爆")
    if "介质特性（毒性危害程度）" in param_map:
        shell_toxic = param_map["介质特性（毒性危害程度）"].get("壳程数值", "")
        tube_toxic = param_map["介质特性（毒性危害程度）"].get("管程数值", "")
        if shell_toxic:
            media_parts.append(f"{shell_toxic}危害")
        if tube_toxic:
            media_parts.append(f"{tube_toxic}危害")

    if media_parts:
        design_params["介质类型"] = "/".join(media_parts)

    # ===== 获取"是否以外径为基准" =====
    cursor.execute("""
            SELECT 数值 FROM 产品设计活动表_通用数据表
            WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
        """, (product_id,))
    row = cursor.fetchone()
    if row and "数值" in row:
        val = str(row["数值"]).strip()
        design_params["是否以外径为基准"] = "1" if val == "是" else "0"

    dict_part = {
        "管箱封头": "椭圆形封头",
        "管箱圆筒": "筒体",
        "管箱法兰": "法兰",
        "管箱分程隔板": "分程隔板",
        "壳体圆筒": "筒体",
        "壳体法兰": "法兰",
        "固定管板": "a型管板（U型管）",
        "管束": "管束",
        "壳体封头": "椭圆形封头",
        "鞍座": "鞍座",

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

    tougai_falan = {
        "换热器型号": "0",
        "壳程液柱密度": "0",
        "管程液柱密度": "0",
        "壳程液柱静压力": "0",
        "管程液柱静压力": "0",
        "压紧面形状序号": "0",
        "法兰是否考虑腐蚀裕量": "0",
        "法兰压紧面压紧宽度ω": "0",
        "轴向外力": "0",
        "外力矩": "0",
        "法兰类型": "0",
        "法兰材料类型": "0",
        "法兰材料牌号": "0",
        "法兰材料腐蚀裕量": "0",
        "法兰颈部大端有效厚度": "0",
        "法兰颈部小端有效厚度": "0",
        "法兰名义内径": "0",
        "法兰名义外径": "0",
        "法兰名义厚度": "0",
        "法兰颈部高度": "0",
        "覆层厚度": "0",
        "管程还是壳程": "0",
        "法兰为夹持法兰": "0",
        "法兰位置": "0",
        "圆筒名义厚度": "0",
        "圆筒有效厚度": "0",
        "圆筒名义内径": "0",
        "圆筒名义外径": "0",
        "圆筒材料类型": "0",
        "圆筒材料牌号": "0",
        "焊缝高度": "0",
        "焊缝长度": "0",
        "焊缝深度": "0",
        "法兰种类": "0",
        "公称直径管前左": "0",
        "公称直径壳后右": "0",
        "对接元件管前左材料类型": "0",
        "对接元件壳后右材料类型": "0",
        "对接元件管前左材料牌号": "0",
        "对接元件壳后右材料牌号": "0",
        "是否带分程隔板管前左": "0",
        "是否带分程隔板壳后右": "0",
        "法兰类型管前左": "0",
        "法兰材料类型管前左": "0",
        "法兰材料牌号管前左": "0",
        "法兰材料腐蚀裕量管前左": "0",
        "法兰类型壳后右": "0",
        "法兰材料类型壳后右": "0",
        "法兰材料牌号壳后右": "0",
        "法兰材料腐蚀裕量壳后右": "0",
        "覆层厚度管前左": "0",
        "覆层厚度壳后右": "0",
        "对接元件覆层厚度管前左": "0",
        "对接元件覆层厚度壳后右": "0",
        "平盖序号": "0",
        "平盖直径": "0",
        "纵向焊接接头系数": "0",
        "是否为圆形平盖": "0",
        "平盖材料类型": "0",
        "平盖材料牌号": "0",
        "平盖分程隔板槽深度": "0",
        "平盖材料腐蚀裕量": "0",
        "平盖名义厚度": "0",
        "垫片名义外径": "0",
        "垫片名义内径": "0",
        "螺栓中心圆直径": "0",
        "螺栓材料牌号": "0",
        "螺栓公称直径": "0",
        "螺栓数量": "0",
        "螺栓根径": "0",
        "垫片材料牌号": "0",
        "m": "0",
        "y": "0",
        "垫片厚度": "0",
        "垫片有效外径": "0",
        "垫片有效内径": "0",
        "分程隔板与垫片接触面面积": "0",
        "垫片代号": "0",
        "隔条位置尺寸": "0",
        "介质情况": "0",
        "垫片标准号": "0",
        "垫片实际密封宽度": "0",
        "分程隔板槽宽度": "0",
    }

    guangxiang_pinggai = {
        "分程隔板槽宽度": "0",
        "换热器型号": "0",
        "壳程液柱密度": "0",
        "管程液柱密度": "0",
        "壳程液柱静压力": "0",
        "管程液柱静压力": "0",
        "压紧面形状序号": "0",
        "法兰是否考虑腐蚀裕量": "0",
        "法兰压紧面压紧宽度ω": "0",
        "轴向外力": "0",
        "外力矩": "0",
        "法兰类型": "0",
        "法兰材料类型": "0",
        "法兰材料牌号": "0",
        "法兰材料腐蚀裕量": "0",
        "法兰颈部大端有效厚度": "0",
        "法兰颈部小端有效厚度": "0",
        "法兰名义内径": "0",
        "法兰名义外径": "0",
        "法兰名义厚度": "0",
        "法兰颈部高度": "0",
        "覆层厚度": "0",
        "管程还是壳程": "0",
        "法兰为夹持法兰": "0",
        "法兰位置": "0",
        "圆筒名义厚度": "0",
        "圆筒有效厚度": "0",
        "圆筒名义内径": "0",
        "圆筒名义外径": "0",
        "圆筒材料类型": "0",
        "圆筒材料牌号": "0",
        "焊缝高度": "0",
        "焊缝长度": "0",
        "焊缝深度": "0",
        "法兰种类": "0",
        "介质情况": "0",
        "公称直径管前左": "0",
        "公称直径壳后右": "0",
        "对接元件管前左材料类型": "0",
        "对接元件壳后右材料类型": "0",
        "对接元件管前左材料牌号": "0",
        "对接元件壳后右材料牌号": "0",
        "是否带分程隔板管前左": "0",
        "是否带分程隔板壳后右": "0",
        "法兰类型管前左": "0",
        "法兰材料类型管前左": "0",
        "法兰材料牌号管前左": "0",
        "法兰材料腐蚀裕量管前左": "0",
        "法兰类型壳后右": "0",
        "法兰材料类型壳后右": "0",
        "法兰材料牌号壳后右": "0",
        "法兰材料腐蚀裕量壳后右": "0",
        "覆层厚度管前左": "0",
        "覆层厚度壳后右": "0",
        "对接元件覆层厚度管前左": "0",
        "对接元件覆层厚度壳后右": "0",
        "垫片名义外径": "0",
        "垫片名义内径": "0",
        "平盖序号": "0",
        "纵向焊接接头系数": "0",
        "平盖直径": "0",
        "是否为圆形平盖": "0",
        "平盖材料类型": "0",
        "平盖材料牌号": "0",
        "平盖分程隔板槽深度": "0",
        "平盖材料腐蚀裕量": "0",
        "平盖名义厚度": "0",
        "螺栓中心圆直径": "0",
        "螺栓材料牌号": "0",
        "螺栓公称直径": "0",
        "螺栓数量": "0",
        "螺栓根径": "0",
        "垫片材料牌号": "0",
        "m": "0",
        "y": "0",
        "垫片厚度": "0",
        "垫片有效外径": "0",
        "垫片有效内径": "0",
        "分程隔板与垫片接触面面积": "0",
        "垫片代号": "0",
        "隔条位置尺寸": "0",
        "垫片标准号": "0",
        "垫片实际密封宽度": "0",
    }

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
    if isDN_change:
        guangxiang_fengtou["公称直径"] = user_DN
    # ===== 获取预设厚度1~3（来自元件附加参数表）=====
    cursor.execute("""
            SELECT 参数名称, 参数值 FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '管箱封头'
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
            SELECT 参数名称, 壳程数值, 管程数值
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s
        """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row for row in rows}

    cursor.execute("""
            SELECT 数值 FROM 产品设计活动表_通用数据表
            WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
        """, (product_id,))
    row = cursor.fetchone()
    if row and "数值" in row:
        val = str(row["数值"]).strip()
        design_params["是否以外径为基准"] = "1" if val == "是" else "0"

    # 查询设计数据表
    cursor.execute("""
            SELECT 参数名称, 壳程数值, 管程数值
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
    if isDN_change:
        map2["公称直径"] = user_DN

    for key, param_name in map2.items():
        value = param_map.get(param_name, {}).get("管程数值", "")
        if value != "":
            guangxiang_fengtou[key] = str(value)

    # ===== 压力试验类型（去掉末尾“试验”并映射为数字）=====
    pressure_type_map = {
        "液压": "1",
        "气压": "2",
        "气液": "3"
    }

    if "耐压试验类型*" in param_map:
        val = param_map["耐压试验类型*"].get("管程数值", "")
        if val:
            clean_val = str(val).replace("试验", "").strip()
            guangxiang_fengtou["压力试验类型"] = pressure_type_map.get(clean_val, "0")

    # ===== 用户自定义耐压试验压力：取卧与立中较大者 =====
    val1 = param_map.get("自定义耐压试验压力（卧）", {}).get("管程数值", "")
    val2 = param_map.get("自定义耐压试验压力（立）", {}).get("管程数值", "")
    # ===== 最大允许工作压力 =====
    if "最大允许工作压力" in param_map:
        value = param_map["最大允许工作压力"].get("管程数值", "")
        if value != "":
            guangxiang_fengtou["最大允许工作压力"] = str(value)

    try:
        val_max = max(float(val1), float(val2))
        guangxiang_fengtou["用户自定义耐压试验压力"] = str(int(val_max))
    except:
        guangxiang_fengtou["用户自定义耐压试验压力"] = str(val1 or val2 or "0")  # 至少有一个值就保留

    # 查询元件附加参数表中元件名称为“管箱封头”的数据
    cursor.execute("""
            SELECT 参数名称, 参数值 
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '管箱封头'
        """, (product_id,))
    extra_rows = cursor.fetchall()
    extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}

    # 是否添加覆层
    if extra_map.get("是否添加覆层") == "是":
        guangxiang_fengtou["是否覆层"] = "1"
        guangxiang_fengtou["覆层材料类型"] = extra_map.get("覆层材料类型", "轧制复合")  # 若为空可改为 "未知"

        guangxiang_fengtou["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        guangxiang_fengtou["椭圆形封头覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
    else:
        guangxiang_fengtou["是否覆层"] = "0"
        guangxiang_fengtou["覆层材料类型"] = "钢板"  # 若为空可改为 "未知"
        guangxiang_fengtou["覆层复合方式"] = "无"
        guangxiang_fengtou["椭圆形封头覆层厚度"] = "0"
        guangxiang_fengtou["椭圆形封头曲面深度"] = extra_map.get("封头面曲面深度hi", "0")  # 默认“未知”可改为""

    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '管箱封头'
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
    if isDN_change:
        keti_fengtou["公称直径"] = user_DN
    # ===== 获取预设厚度1~3（来自元件附加参数表）=====
    cursor.execute("""
            SELECT 参数名称, 参数值 FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '管箱封头'
        """, (product_id,))
    rows = cursor.fetchall()
    extra_param_map = {r["参数名称"].strip(): r["参数值"] for r in rows}

    # 写入 guangxiang_fengtou 中的预设厚度
    for i in range(1, 4):
        key = f"预设厚度{i}"
        if key in extra_param_map:
            keti_fengtou[key] = str(extra_param_map[key])

    cursor.execute("""
            SELECT 数值 FROM 产品设计活动表_通用数据表
            WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
        """, (product_id,))
    row = cursor.fetchone()
    if row and "数值" in row:
        val = str(row["数值"]).strip()
        keti_fengtou["是否以外径为基准"] = "1" if val == "是" else "0"

    # 查询设计数据表
    cursor.execute("""
               SELECT 参数名称, 壳程数值, 管程数值
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
    if isDN_change:
        map2["公称直径"] = user_DN

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
        val = param_map["耐压试验类型*"].get("管程数值", "")
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

    # 查询元件附加参数表中元件名称为“管箱封头”的数据
    cursor.execute("""
               SELECT 参数名称, 参数值 
               FROM 产品设计活动表_元件附加参数表
               WHERE 产品ID = %s AND 元件名称 = '壳体封头'
           """, (product_id,))
    extra_rows = cursor.fetchall()
    extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}

    # 是否添加覆层
    if extra_map.get("是否添加覆层") == "是":
        keti_fengtou["是否覆层"] = "1"
        keti_fengtou["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        keti_fengtou["椭圆形封头覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
        keti_fengtou["覆层材料类型"] = extra_map.get("覆层材料类型", "")  # 若为空可改为 "未知"

    else:
        keti_fengtou["是否覆层"] = "0"
        keti_fengtou["覆层复合方式"] = "无"
        keti_fengtou["椭圆形封头覆层厚度"] = "0"
        keti_fengtou["覆层材料类型"] = "钢板"  # 若为空可改为 "未知"

    keti_fengtou["椭圆形封头曲面深度"] = extra_map.get("封头面曲面深度hi", "0")  # 默认“未知”可改为""

    cursor.execute("""
               SELECT 参数名称, 参数值
               FROM 产品设计活动表_元件附加参数表
               WHERE 产品ID = %s AND 元件名称 = '壳体封头'
           """, (product_id,))
    rows = cursor.fetchall()
    extra_map = {r["参数名称"]: r["参数值"] for r in rows}

    if "材料类型" in extra_map:
        raw_type = extra_map["材料类型"]
        keti_fengtou["材料类型"] = material_type_map.get(raw_type, raw_type)
    if "材料牌号" in extra_map:
        keti_fengtou["材料牌号"] = extra_map["材料牌号"]

    # 初始化默认值
    guanxiang_yuantong = {
        "预设厚度1": "8",
        "预设厚度2": "10",
        "预设厚度3": "12",
        "圆筒使用位置": "管箱圆筒",
        "圆筒名义厚度": "0",
        "圆筒内/外径": "0",
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
        "公称直径": ""
    }
    if isDi_change:
        guanxiang_yuantong["圆筒内/外径"] = user_Di
    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()
        if isDN_change:
            design_params["公称直径"] = user_DN
        else:
            # 查询设计数据表，获取公称直径*
            cursor.execute("""
                                  SELECT 管程数值
                                  FROM 产品设计活动表_设计数据表
                                  WHERE 产品ID = %s AND 参数名称 = '公称直径*'
                              """, (product_id,))
            row = cursor.fetchone()
            raw_val = row["管程数值"].strip() if row and row.get("管程数值") else None
            guanxiang_yuantong["公称直径"] = raw_val

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
        print(f"❌ 查询失败: {e}")

    # === 处理参数值（空或无效则默认 6000） ===
    tube_length = raw_val if raw_val not in (None, "", " ", "None") else "6000"

    # 写入 qiaoti_yuantong
    guanxiang_yuantong["换热管长度"] = tube_length
    cursor.execute("""
               SELECT 参数名称, 参数值 
               FROM 产品设计活动表_元件附加参数表
               WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
           """, (product_id,))
    extra_rows = cursor.fetchall()
    extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}

    # 是否添加覆层
    if extra_map.get("是否添加覆层") == "是":
        guanxiang_yuantong["是否覆层"] = "1"
        guanxiang_yuantong["覆层材料类型"] = extra_map.get("覆层材料类型", "")
        guanxiang_yuantong["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        guanxiang_yuantong["圆筒覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
    else:
        guanxiang_yuantong["覆层材料类型"] = "钢板"
        guanxiang_yuantong["是否覆层"] = "0"
        guanxiang_yuantong["覆层复合方式"] = "无"
        guanxiang_yuantong["圆筒覆层厚度"] = "0"
    # === 查询数据库 ===
    cursor.execute("""
            SELECT 参数名称, 壳程数值, 管程数值
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

    val1 = parse_float(param_map.get("自定义耐压试验压力（卧）", {}).get("管程数值", ""))
    val2 = parse_float(param_map.get("自定义耐压试验压力（立）", {}).get("管程数值", ""))

    # === 最大允许工作压力（管程数值） ===
    value = param_map.get("最大允许工作压力", {}).get("管程数值")
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
            WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
        """, (product_id,))
    rows = cursor.fetchall()
    extra_param_map = {r["参数名称"].strip(): r["参数值"] for r in rows}

    # 写入 guangxiang_fengtou 中的预设厚度
    for i in range(1, 4):
        key = f"预设厚度{i}"
        if key in extra_param_map:
            guanxiang_yuantong[key] = str(extra_param_map[key])

    # # 从数据库获取“是否以外径为基准*”的管程数值
    # cursor.execute("""
    #         SELECT 数值 FROM 产品设计活动表_通用数据表
    #         WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
    #     """, (product_id,))
    # row = cursor.fetchone()
    # if row and "数值" in row:
    #     guanxiang_yuantong["是否按外径计算"] = "1" if row["数值"] == "是" else "0"
    # 查询设计数据表，获取公称直径*
    if isDN_change:
        guanxiang_yuantong["圆筒内/外径"] = user_DN
    else:
        cursor.execute("""
                    SELECT 管程数值 FROM 产品设计活动表_设计数据表
                    WHERE 产品ID = %s AND 参数名称 = '公称直径*'
                """, (product_id,))
        row = cursor.fetchone()
        if row and "管程数值" in row:
            guanxiang_yuantong["圆筒内/外径"] = str(row["管程数值"])

    map3 = {
        "液柱静压力": "液柱静压力",
        "用户自定义MAWP": "最高允许工作压力",
        "腐蚀裕量": "腐蚀裕量*",
        "焊接接头系数": "焊接接头系数*",

    }

    for key, param_name in map3.items():
        value = param_map.get(param_name, {}).get("管程数值", "")
        if value != "":
            guanxiang_yuantong[key] = str(value)

    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
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
        val = param_map["耐压试验类型*"].get("管程数值", "")
        if val:
            guanxiang_yuantong["压力试验类型"] = str(val).replace("试验", "").strip()

        # 初始化默认值
    qiaoti_yuantong = {
        "预设厚度1": "8",
        "预设厚度2": "10",
        "预设厚度3": "12",
        "圆筒使用位置": "壳体圆筒",
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
        "公称直径": ""
    }
    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()
        # 查询设计数据表，获取公称直径*
        if isDN_change:
            qiaoti_yuantong["公称直径"] = user_DN
        else:
            cursor.execute("""
                                    SELECT 壳程数值
                                    FROM 产品设计活动表_设计数据表
                                    WHERE 产品ID = %s AND 参数名称 = '公称直径*'
                                    LIMIT 1
                                """, (product_id,))
            row = cursor.fetchone()
            raw_val = row["壳程数值"].strip() if row and row.get("壳程数值") else None
            qiaoti_yuantong["公称直径"] = raw_val

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
        print(f"❌ 查询失败: {e}")

    # === 处理参数值（空或无效则默认 6000） ===
    tube_length = raw_val if raw_val not in (None, "", " ", "None") else "6000"

    # 写入 qiaoti_yuantong
    qiaoti_yuantong["换热管长度"] = tube_length
    cursor.execute("""
               SELECT 参数名称, 参数值 
               FROM 产品设计活动表_元件附加参数表
               WHERE 产品ID = %s AND 元件名称 = '壳体圆筒'
           """, (product_id,))
    extra_rows = cursor.fetchall()
    extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}

    # 是否添加覆层
    if extra_map.get("是否添加覆层") == "是":
        qiaoti_yuantong["是否覆层"] = "1"
        qiaoti_yuantong["覆层材料类型"] = extra_map.get("覆层材料类型", "")  # 若为空可改为 "未知"

        qiaoti_yuantong["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        qiaoti_yuantong["圆筒覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
    else:
        qiaoti_yuantong["是否覆层"] = "0"
        qiaoti_yuantong["覆层材料类型"] = "钢板"

        qiaoti_yuantong["覆层复合方式"] = "无"
        qiaoti_yuantong["圆筒覆层厚度"] = "0"
    # 查询设计数据表
    # === 查询数据库 ===
    cursor.execute("""
            SELECT 参数名称, 壳程数值, 管程数值
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

    val1 = parse_float(param_map.get("自定义耐压试验压力（卧）", {}).get("管程数值", ""))
    val2 = parse_float(param_map.get("自定义耐压试验压力（立）", {}).get("管程数值", ""))

    # === 最大允许工作压力（管程数值） ===
    value = param_map.get("最大允许工作压力", {}).get("管程数值")
    if value not in [None, ""]:
        guanxiang_yuantong["最大允许工作压力"] = str(value)

    # === 耐压试验压力：取最大值 ===
    if val1 is not None and val2 is not None:
        qiaoti_yuantong["耐压试验压力"] = str(max(val1, val2))
    elif val1 is not None:
        qiaoti_yuantong["耐压试验压力"] = str(val1)
    elif val2 is not None:
        qiaoti_yuantong["耐压试验压力"] = str(val2)
    else:
        qiaoti_yuantong["耐压试验压力"] = "0"

    # ===== 获取预设厚度1~3（来自元件附加参数表）=====
    cursor.execute("""
            SELECT 参数名称, 参数值 FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '壳体圆筒'
        """, (product_id,))
    rows = cursor.fetchall()
    extra_param_map = {r["参数名称"].strip(): r["参数值"] for r in rows}

    # 写入 guangxiang_fengtou 中的预设厚度
    for i in range(1, 4):
        key = f"预设厚度{i}"
        if key in extra_param_map:
            qiaoti_yuantong[key] = str(extra_param_map[key])
    # 从数据库获取“是否以外径为基准*”的管程数值
    cursor.execute("""
               SELECT 数值 FROM 产品设计活动表_通用数据表
               WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
           """, (product_id,))
    row = cursor.fetchone()
    if row and "数值" in row:
        qiaoti_yuantong["是否按外径计算"] = "1" if row["数值"] == "是" else "0"
    if isDN_change:
        qiaoti_yuantong["圆筒内/外径"] = user_DN
    else:
        # 查询设计数据表，获取公称直径*
        cursor.execute("""
                      SELECT 壳程数值 FROM 产品设计活动表_设计数据表
                      WHERE 产品ID = %s AND 参数名称 = '公称直径*'
                  """, (product_id,))
        row = cursor.fetchone()
        if row and "壳程数值" in row:
            qiaoti_yuantong["圆筒内/外径"] = str(row["壳程数值"])

    map3 = {
        "液柱静压力": "液柱静压力",
        "用户自定义MAWP": "最高允许工作压力",
        "腐蚀裕量": "腐蚀裕量*",
        "焊接接头系数": "焊接接头系数*",

    }

    for key, param_name in map3.items():
        value = param_map.get(param_name, {}).get("壳程数值", "")
        if value != "":
            qiaoti_yuantong[key] = str(value)

    cursor.execute("""
               SELECT 参数名称, 参数值
               FROM 产品设计活动表_元件附加参数表
               WHERE 产品ID = %s AND 元件名称 = '壳体圆筒'
           """, (product_id,))
    rows = cursor.fetchall()
    extra_map = {r["参数名称"]: r["参数值"] for r in rows}

    if "材料类型" in extra_map:
        raw_type = extra_map["材料类型"]
        qiaoti_yuantong["材料类型"] = material_type_map.get(raw_type, raw_type)
    if "材料牌号" in extra_map:
        qiaoti_yuantong["材料牌号"] = extra_map["材料牌号"]
    # ===== 压力试验类型（去掉末尾“试验”并映射为数字）=====
    if "耐压试验类型*" in param_map:
        val = param_map["耐压试验类型*"].get("壳程数值", "")
        if val:
            clean_val = str(val).replace("试验", "").strip()
            qiaoti_yuantong["压力试验类型"] = clean_val
        # 查询元件附加参数表中元件名称为“管箱封头”的数据
        # cursor.execute("""
        #        SELECT 参数名称, 参数值
        #        FROM 产品设计活动表_元件附加参数表
        #        WHERE 产品ID = %s AND 元件名称 = '壳体封头'
        #    """, (product_id,))
        # extra_rows = cursor.fetchall()
        # extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}

    guanxiang_falan = {'换热器型号': 0, '壳程液柱密度': 0, '管程液柱密度': 0, '壳程液柱静压力': 0, '管程液柱静压力': 0,
                       '压紧面形状序号': 0, '法兰是否考虑腐蚀裕量': 0, '法兰压紧面压紧宽度ω': 0, '轴向外力': 0,
                       '外力矩': 0, '法兰类型': 0, '法兰材料类型': 0, '法兰材料牌号': 0, '法兰材料腐蚀裕量': 0,
                       '法兰颈部大端有效厚度': 0, '法兰颈部小端有效厚度': 0, '法兰名义内径': 0, '法兰名义外径': 0,
                       '法兰名义厚度': 0, '法兰颈部高度': 0, '覆层厚度': 0, '管程还是壳程': 0, '法兰为夹持法兰': 0,
                       '法兰位置': 0, '圆筒名义厚度': 0, '圆筒有效厚度': 0, '圆筒名义内径': 0, '圆筒名义外径': 0,
                       '圆筒材料类型': 0, '圆筒材料牌号': 0, '焊缝高度': 0, '焊缝长度': 0, '焊缝深度': 0, '法兰种类': 0,
                       '公称直径管前左': 0, '公称直径壳后右': 0, '对接元件管前左材料类型': 0,
                       '对接元件壳后右材料类型': 0, '对接元件管前左材料牌号': 0, '对接元件壳后右材料牌号': 0,
                       '是否带分程隔板管前左': 0, '是否带分程隔板壳后右': 0, '法兰类型管前左': 0,
                       '法兰材料类型管前左': 0, '法兰材料牌号管前左': 0, '法兰材料腐蚀裕量管前左': 0,
                       '法兰类型壳后右': 0, '法兰材料类型壳后右': 0, '法兰材料牌号壳后右': 0,
                       '法兰材料腐蚀裕量壳后右': 0, '覆层厚度管前左': 0, '覆层厚度壳后右': 0,
                       '对接元件覆层厚度管前左': 0, '对接元件覆层厚度壳后右': 0, '平盖序号': 0, '纵向焊接接头系数': 0,
                       '平盖直径': 0, '是否为圆形平盖': 0, '平盖材料类型': 0, '平盖材料牌号': 0,
                       '平盖分程隔板槽深度': 0, '平盖材料腐蚀裕量': 0, '平盖名义厚度': 0, '垫片名义外径': 0,
                       '垫片名义内径': 0, '螺栓中心圆直径': 0, '螺栓材料牌号': 0, '螺栓公称直径': 0, '螺栓数量': 0,
                       '螺栓根径': 0, '垫片材料牌号': 0, 'm': 0, 'y': 0, '垫片厚度': 0, '垫片有效外径': 0,
                       '垫片有效内径': 0, '分程隔板与垫片接触面面积': 0, '垫片代号': 0, '隔条位置尺寸': 0,
                       '介质情况': 0, '垫片标准号': 0, '垫片实际密封宽度': 0, '分程隔板槽宽度': 0}

    keti_falan = {'换热器型号': 0, '壳程液柱密度': 0, '管程液柱密度': 0, '壳程液柱静压力': 0, '管程液柱静压力': 0,
                  '压紧面形状序号': 0, '法兰是否考虑腐蚀裕量': 0, '法兰压紧面压紧宽度ω': 0, '轴向外力': 0, '外力矩': 0,
                  '法兰类型': 0, '法兰材料类型': 0, '法兰材料牌号': 0, '法兰材料腐蚀裕量': 0, '法兰颈部大端有效厚度': 0,
                  '法兰颈部小端有效厚度': 0, '法兰名义内径': 0, '法兰名义外径': 0, '法兰名义厚度': 0, '法兰颈部高度': 0,
                  '覆层厚度': 0, '管程还是壳程': 0, '法兰为夹持法兰': 0, '法兰位置': 0, '圆筒名义厚度': 0,
                  '圆筒有效厚度': 0, '圆筒名义内径': 0, '圆筒名义外径': 0, '圆筒材料类型': 0, '圆筒材料牌号': 0,
                  '焊缝高度': 0, '焊缝长度': 0, '焊缝深度': 0, '法兰种类': 0, '公称直径管前左': 0, '公称直径壳后右': 0,
                  '对接元件管前左材料类型': 0, '对接元件壳后右材料类型': 0, '对接元件管前左材料牌号': 0,
                  '对接元件壳后右材料牌号': 0, '是否带分程隔板管前左': 0, '是否带分程隔板壳后右': 0,
                  '法兰类型管前左': 0, '法兰材料类型管前左': 0, '法兰材料牌号管前左': 0, '法兰材料腐蚀裕量管前左': 0,
                  '法兰类型壳后右': 0, '法兰材料类型壳后右': 0, '法兰材料牌号壳后右': 0, '法兰材料腐蚀裕量壳后右': 0,
                  '覆层厚度管前左': 0, '覆层厚度壳后右': 0, '对接元件覆层厚度管前左': 0, '对接元件覆层厚度壳后右': 0,
                  '平盖序号': 0, '平盖直径': 0, '纵向焊接接头系数': 0, '是否为圆形平盖': 0, '平盖材料类型': 0,
                  '平盖材料牌号': 0, '平盖分程隔板槽深度': 0, '平盖材料腐蚀裕量': 0, '平盖名义厚度': 0,
                  '垫片名义外径': 0, '垫片名义内径': 0, '螺栓中心圆直径': 0, '螺栓材料牌号': 0, '螺栓公称直径': 0,
                  '螺栓数量': 0, '螺栓根径': 0, '垫片材料牌号': 0, 'm': 0, 'y': 0, '垫片厚度': 0, '垫片有效外径': 0,
                  '垫片有效内径': 0, '分程隔板与垫片接触面面积': 0, '垫片代号': 0, '隔条位置尺寸': 0, '介质情况': 0,
                  '垫片标准号': 0, '垫片实际密封宽度': 0, '分程隔板槽宽度': 0}

    fencheng_geban = {'材料类型': 0, '材料牌号': 0, '公称直径': 0, '管箱分程隔板名义厚度': 0,
                      '管箱分程隔板两侧压力差值': 0, '管箱分程隔板结构尺寸长边a': 0, '管箱分程隔板结构尺寸长边b': 0,
                      '管箱分程隔板结构型式': 0, '耐压试验温度': 0, '腐蚀裕量(双面)': 0, '管箱分程隔板设计余量': 0,
                      '隔条位置尺寸': 0, '分程隔板槽宽度': 0}

    guanban_a = {'公称直径': 0, '管程液柱静压力': 0, '壳程液柱静压力': 0, '管程腐蚀裕量': 0, '壳程腐蚀裕量': 0,
                 '是否可以保证在任何情况下管壳程压力都能同时作用': 0, '换热管使用场合': 0, '换热管与管板连接方式': 0,
                 '材料类型': 0, '材料牌号': 0, '管板名义厚度': 0, '管板强度削弱系数': 0, '壳程侧结构槽深': 0,
                 '管程侧隔板槽深': 0, '换热管材料类型': 0, '换热管材料牌号': 0, '换热管外径': 0, '换热管壁厚': 0,
                 '换热管中心距': 0, '换热管直管段长度': 0, '耐压试验温度': 0, '内孔焊焊接接头系数': 0,
                 '换热管与管板胀接长度或焊脚高度': 0, '换热管是否钢材': 0, '胀接管孔是否开槽': 0, '换热管根数': 0,
                 '垫片材料名称': 0, '管板外径': 0, '垫片与密封面接触外径': 0, '垫片与密封面接触内径': 0, '垫片厚度': 0,
                 '压紧面形式': 0, '换热管排列方式': 0, '折流板切口方向': 0, '管/壳程布置型式': 0,
                 '沿水平隔板槽一侧的排管根数': 0, '沿竖直隔板槽一侧的排管根数': 0, '水平隔板槽两侧相邻管中心距': 0,
                 '垂直隔板槽两侧相邻管中心距': 0, '管板分程处面积Ad': 0, '是否交叉布管': 0,
                 '交叉管排1最两端管孔中心距': 0, '交叉管排1实际管孔数量': 0, '交叉管排2最两端管孔中心距': 0,
                 '交叉管排2实际管孔数量': 0, '交叉管排3最两端管孔中心距': 0, '交叉管排3实际管孔数量': 0}

    tube_bundle = {'倾斜U形换热管两管孔的中心距离1排': 0, '倾斜U形换热管两管孔的中心距离2排': 0,
                   '倾斜U形换热管两管孔的中心距离3排': 0, '换热管孔间距': 0, '允许交叉布管的排数': 0,
                   '管垂直间距3排': 0, '管垂直间距2排': 0, '管垂直间距1排': 0, '仅倾斜or交叉1排': 0,
                   '仅倾斜or交叉2排': 0, '仅倾斜or交叉3排': 0, '管程数': 0, '水平分程隔板槽两侧相邻管中心距水平上下': 0,
                   '竖直分程隔板槽两侧相邻管中心距垂直左右': 0, '水平分程隔板槽数量': 0, '竖直分程隔板槽数量': 0,
                   '布管限定圆直径': 0, '换热管理论直管长度': 0, '换热管伸出管板值': 0, '管板名义厚度': 0,
                   '折流板切口与中心线间距': 0, '圆筒内径': 0, '公称直径': 0, '滑道与固定管板是否焊接连接': 0,
                   '滑道伸出折流板/支持板最小值': 0, '是否交叉布管': 0, '接管外径1': 0, '接管外径2': 0,
                   '接管1名义厚度': 0, '接管2名义厚度': 0, '圆筒名义厚度': 0, '管板类型': 0,
                   '接管中心线至圆筒边缘距离': 0, '管板凸台高度': 0, '垫片厚度': 0, '管板与壳程圆筒连接台肩长度': 0,
                   '折流板需求间距': 0, '入口OD1/OD2': 0, '拉杆类型': 0, '拉杆用螺母厚度': 0, '换热管外径': 0,
                   '折流板厚度初始值': 0, 'U形换热管最大弯曲直径': 0, '换热管材料序号': 0, '拉杆直径': 0,
                   '接管OD2中心至壳程圆筒边缘(封头侧)最小距离': 0, '换热管材料类型': 0, '换热管材料牌号': 0,
                   '换热管排列方式': 0, '折流板切口方向': 0}

    anzuo = {'公称直径': 0, '鞍座设计温度': 0, '筋板材料类型': 0, '筋板材料牌号': 0, '筋板名义厚度': 0,
             '腹板材料类型': 0, '腹板材料牌号': 0, '腹板名义厚度': 0, '底板材料类型': 0, '底板材料牌号': 0,
             '底板名义厚度': 0, '壳程入口接管法兰外径': 0, '壳程出口接管法兰外径': 0}

    def build_jieguan(cursor, product_id, guankou_daihao):
        jieguan = {
            "设备公称直径": "1000",
            "接管是否以外径为基准": "True",
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
            "覆层复合方式": "轧制复合",
            "接管覆层厚度": "1",
            "接管带覆层时的焊接凹槽深度": "0",
            "接管最小有效外伸高度系数": "0.8",
            "焊缝面积A3焊脚高度系数": "0.7",
            "开孔补强自定义补强面积裕量百分比": "0",
            "补强区内的焊缝面积(含嵌入式接管焊缝面积)": "49",
            "补强圈材料类型": "板材",
            "补强圈材料牌号": "Q345R",
            "开孔元件名称": "管箱圆筒",
            "接管材料类型1": "",
            "接管材料牌号1": "",
            "接管材料类型2": "",
            "接管材料牌号2": "",
            "接管材料类型3": "",
            "接管材料牌号3": "",
            "管口表序号": guankou_daihao,
            "是否覆层": "",
            "覆层材料类型": ""
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
            jieguan["开孔元件名称"] = row.get("管口所属元件", "").strip()
            jieguan["接管中心线至筒体轴线距离(偏心距)"] = str(row.get("偏心距", "0"))
            jieguan["接管中心线与法线夹角(包括封头)"] = str(row.get("轴向夹角（°）", "0"))
            jieguan["接管实际外伸长度"] = str(row.get("外伸高度", "0"))

        # 程序推荐兜底
        if jieguan.get("接管实际外伸长度") == "程序推荐":
            jieguan["接管实际外伸长度"] = "0"

        cursor.execute("""
                SELECT 参数名称, 管程数值
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s AND 参数名称 IN ('工作温度（入口）', '工作温度（出口）')
            """, (product_id,))
        rows = cursor.fetchall()

        # 初始化入口/出口温度
        temp_in = None
        temp_out = None

        for row in rows:
            name = row.get("参数名称", "").strip()
            value = row.get("管程数值")
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

        # === 获取管口材料分类 ===
        cursor.execute("""
                SELECT 材料分类
                FROM 产品设计活动表_管口类别表
                WHERE 产品ID = %s AND 管口代号 = %s
                LIMIT 1
            """, (product_id, guankou_daihao))
        row = cursor.fetchone()

        if row and row.get("材料分类"):
            category = row["材料分类"].strip()
        else:
            category = ""  # 默认分类

        print(f"✅ 管口代号 {guankou_daihao} 使用材料分类: {category}")

        # === 根据材料分类，从附加参数表里取材料参数 ===
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
            r["参数名称"].strip(): str(r["参数值"]).strip()
            for r in material_rows if r.get("参数名称") and r.get("参数值") not in (None, "", "None")
        }

        # 更新到 jieguan
        for i in range(1, 3 + 1):
            jieguan[f"接管材料类型{i}"] = material_map.get(f"接管材料类型{i}", "")
            jieguan[f"接管材料牌号{i}"] = material_map.get(f"接管材料牌号{i}", "")
            jieguan[f"接管腐蚀余量{i}"] = material_map.get(f"接管腐蚀裕量{i}", "")
        # ===== 获取公称直径、绝热厚度、毒性/爆炸危险等 =====
        cursor.execute("""
                    SELECT 参数名称, 壳程数值, 管程数值
                    FROM 产品设计活动表_设计数据表
                    WHERE 产品ID = %s
                """, (product_id,))
        rows = cursor.fetchall()
        param_map = {row["参数名称"].strip(): row for row in rows}
        if isDN_change:
            param_map["公称直径*"]["管程数值"] = user_DN

        # 公称直径（管程）
        if "公称直径*" in param_map:
            jieguan["设备公称直径"] = str(param_map["公称直径*"].get("管程数值", ""))
        # 参数映射：数据库参数名 → jieguan 字典键名

        # === 获取该管口的材料分类 ===
        cursor.execute("""
                SELECT 材料分类
                FROM 产品设计活动表_管口类别表
                WHERE 产品ID = %s AND 管口代号 = %s
            """, (product_id, guankou_daihao))
        material_class_rows = cursor.fetchall()
        material_classes = [r["材料分类"].strip() for r in material_class_rows if r.get("材料分类")]

        use_category_filter = bool(material_classes)
        category = material_classes[0] if use_category_filter else None
        print(f"✅ 材料分类（{guankou_daihao}）: {material_classes or '统一材料'}")

        # === 获取管口功能 ===
        cursor.execute("""
                SELECT 管口功能
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口代号 = %s
                LIMIT 1
            """, (product_id, guankou_daihao))
        row = cursor.fetchone()
        guankou_gongneng = row["管口功能"].strip() if row and row["管口功能"] else ""
        print(f"✅ 管口功能: {guankou_gongneng}")
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

        print(f"✅ 管口功能: {guankou_gongneng}")
        print(f"✅ 所属元件: {suoshuyuanjian}")

        if gongcheng_size is not None:
            jieguan["接管内/外径"] = str(gongcheng_size)

        # === 获取材料分类 ===
        cursor.execute("""
                    SELECT 材料分类 
                    FROM 产品设计活动表_管口类别表 
                    WHERE 产品ID = %s AND 管口代号 = %s
                """, (product_id, guankou_daihao))
        class_rows = cursor.fetchall()
        category = class_rows[0]["材料分类"].strip() if class_rows and class_rows[0].get("材料分类") else None
        use_category_filter = bool(category)
        print("category", category)
        # === 遍历接管/2/3 获取材料参数 ===
        material_map = {}  # 放循环外：存全部接管材料类型/牌号
        param_map_total = {}  # 放循环外：存所有参数（用途后续统一处理）
        # === 查询接管覆层参数（新的逻辑：来自 管口附加参数表）===
        cursor.execute("""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_管口附加参数表
                WHERE 产品ID = %s 
                  AND 参数名称 IN ('接管是否添加覆层','覆层材料类型','覆层成型工艺','覆层厚度')
            """, (product_id,))
        cover_rows = cursor.fetchall()

        cover_map = {
            r["参数名称"].strip(): str(r["参数值"]).strip()
            for r in cover_rows if r.get("参数名称") and r.get("参数值") not in (None, "", "None")
        }

        if cover_map.get("接管是否添加覆层") == "是":
            jieguan["是否覆层"] = "1"
            jieguan["覆层材料类型"] = cover_map.get("覆层材料类型", "未知")
            jieguan["覆层复合方式"] = cover_map.get("覆层成型工艺", "轧制复合")
            jieguan["接管覆层厚度"] = cover_map.get("覆层厚度", "0")
            has_cover = True
        else:
            jieguan["是否覆层"] = "0"
            jieguan["覆层材料类型"] = "钢板"
            jieguan["覆层复合方式"] = "无"
            jieguan["接管覆层厚度"] = "0"
            has_cover = False

        # === 查询补强圈材料信息（按顺序优先：1 → 2 → 3）===
        cursor.execute("""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_管口附加参数表
                WHERE 产品ID = %s 
                  AND 参数名称 IN (
                      '补强圈材料类型1','补强圈材料牌号1',
                      '补强圈材料类型2','补强圈材料牌号2',
                      '补强圈材料类型3','补强圈材料牌号3'
                  )
            """, (product_id,))
        rows = cursor.fetchall()

        extra_map = {
            r["参数名称"].strip(): str(r["参数值"]).strip()
            for r in rows if r.get("参数名称") and r.get("参数值") not in (None, "", "None")
        }

        # 默认值
        jieguan["补强圈材料类型"] = "钢板"
        jieguan["补强圈材料牌号"] = "0"

        # 按顺序查找
        for i in range(1, 4):
            mat_type = extra_map.get(f"补强圈材料类型{i}", "").strip()
            mat_grade = extra_map.get(f"补强圈材料牌号{i}", "").strip()
            if mat_type or mat_grade:  # 有一个非空就用
                jieguan["补强圈材料类型"] = mat_type if mat_type else "0"
                jieguan["补强圈材料牌号"] = mat_grade if mat_grade else "0"
                break  # 找到就停

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
        "管箱封头": guangxiang_fengtou,
        "管箱圆筒": guanxiang_yuantong,
        "管箱法兰": guanxiang_falan,
        "管箱分程隔板": fencheng_geban,
        "壳体圆筒": qiaoti_yuantong,
        "壳体法兰": keti_falan,
        "固定管板": guanban_a,
        "管束": tube_bundle,
        "壳体封头": keti_fengtou,
        "鞍座": anzuo,
    }
    # 合并
    dict_datas.update(jieguan_dict)

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
        result["ExchangerType"] = row.get("产品型式", "Unknown")
    else:
        result["ProjectName"] = "UnnamedProject"
        result["ExchangerType"] = "Unknown"
    # ✅ 类型判断并替换结构
    if result.get("ExchangerType") == "AEU":
        result["DictDatas"].pop("管箱封头", None)
        result["DictDatas"]["管箱平盖"] = guangxiang_pinggai
        result["DictDatas"]["头盖法兰"] = tougai_falan
        if "DictPart" in result and "管箱封头" in result["DictPart"]:
            result["DictPart"].pop("管箱封头", None)
            result["DictPart"]["管箱平盖"] = "平盖"
        result["DictPart"]["头盖法兰"] = "法兰"
        # === 替换 DictDatas 中所有模块的 "换热器类型" 为 AEU ===
        for module_data in result.get("DictDatas", {}).values():
            print(module_data)
            if isinstance(module_data, dict):
                for key in module_data:
                    if key == "换热器型号":
                        module_data[key] = "AEU"

    def deep_map(obj):
        if isinstance(obj, dict):
            return {k: deep_map(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [deep_map(item) for item in obj]
        elif obj is None:
            return "0"
        elif isinstance(obj, str) and obj in material_type_map:
            return material_type_map[obj]
        else:
            return obj

    result = deep_map(result)
    # ✅ 删除 WSList 中所有字段都是 "0" 的项
    if "WSList" in result and isinstance(result["WSList"], list):
        result["WSList"] = [
            ws for ws in result["WSList"]
            if not all(str(ws.get(key, "0")) == "0" for key in [
                "ShellWorkingPressure", "TubeWorkingPressure",
                "ShellWorkingTemperature", "TubeWorkingTemperature"
            ])
        ]

    # # 读取JSON文件并转换为紧凑格式
    with open("qiaotineizhijing.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)
    with open("qiaotineizhijing.json", "r", encoding="utf-8") as f:
        data = json.load(f)  # 此时可以正常读取

    clr.AddReference("CalCulationInterF")  # 不加 .dll 后缀
    from CalCulationInterF import CalPartInterface
    # # 读取JSON文件并转换为紧凑格式
    with open("qiaotineizhijing.json", "r", encoding="utf-8") as f:
        json_input = f.read()
    parsed = json.loads(json_input)
    compact_json = json.dumps(parsed, separators=(',', ':'))
    cpi = CalPartInterface()
    outputjsonstr = cpi.IntergratedDi(compact_json)
    return outputjsonstr


def cal_qiaotineizhijing_S(product_id, isDi_change, isDN_change, user_Di, user_DN):
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
        SELECT 参数名称, 壳程数值, 管程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()

    # 参数名映射
    ws_mapping = {
        "设计压力*": ("ShellWorkingPressure", "TubeWorkingPressure"),
        "设计温度（最高）*": ("ShellWorkingTemperature", "TubeWorkingTemperature"),
        "设计压力2（设计工况2）": ("ShellWorkingPressure", "TubeWorkingPressure"),
        "设计温度2（设计工况2）": ("ShellWorkingTemperature", "TubeWorkingTemperature"),
    }

    # 填写数据
    for row in rows:
        param = row["参数名称"].strip()
        shell_val, tube_val = row["壳程数值"], row["管程数值"]
        if param in ws_mapping:
            shell_key, tube_key = ws_mapping[param]
            if "2" in param:
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

        ttdict[key] = {
            "ttNo": 0,
            "ttCode": clean_value(row.get("管口代号")),
            "ttUse": clean_value(row.get("管口功能")),
            "ttDN": clean_value(row.get("公称尺寸")),
            "ttPClass": clean_value(row.get("压力等级")),
            "ttDType": pipe_type_default["公称尺寸类型"],
            "ttPType": pipe_type_default["公称压力类型"],
            "ttType": "WN",
            "ttRF": clean_value(row.get("密封面型式")),
            "ttSpec": "默认" if clean_value(row.get("焊端规格")) == "程序推荐" else clean_value(
                row.get("焊端规格")),
            "ttAttach": clean_value(row.get("管口所属元件")),
            "ttPlace": {
                "左基准线": "左轮廓线",
                "右基准线": "右轮廓线"
            }.get(row.get("轴向定位基准", ""), clean_value(row.get("轴向定位基准"))),
            "ttLoc": "默认" if clean_value(row.get("轴向定位距离")) == "程序推荐" else clean_value(
                row.get("轴向定位距离")),
            "ttFW": clean_value(zhouxiangfangwei),
            "ttThita": clean_value(row.get("偏心距")),
            "ttAngel": clean_value(axial_angle),
            "ttH": ttH_val,
            "ttMemo": "默认"
        }

    # ===== 预设默认值 =====
    design_params = {
        "公称直径": "1000",
        "是否以外径为基准": "1",
        "介质类型": "介质易爆/极度危害/高度危害",
        "管箱圆筒长度工况": "工况1",
        "绝热厚度": "4",
        "管/壳程布置型式": "2.1"
    }
    if isDN_change:
        design_params["公称直径"] = user_DN
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
        if tube_form == "2":
            design_params["管/壳程布置型式"] = "2.1"
        # === 查询设计数据表 ===
        cursor.execute("""
            SELECT 参数名称, 壳程数值, 管程数值
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s
        """, (product_id,))
        rows = cursor.fetchall()
        param_map = {row["参数名称"].strip(): row for row in rows}
    except Exception as e:
        print(f"❌ 查询失败: {e}")
    if isDN_change:
        design_params["公称直径"] = user_DN
    else:
        # 公称直径（管程）
        if "公称直径*" in param_map:
            design_params["公称直径"] = str(param_map["公称直径*"].get("管程数值", ""))
    # 绝热厚度（管程）
    if "绝热层厚度" in param_map:
        design_params["绝热厚度"] = str(param_map["绝热层厚度"].get("管程数值", ""))

    # 介质类型 = 爆炸危险性 + 壳程毒性 + 管程毒性
    media_parts = []
    if "介质特性（爆炸危险程度）" in param_map:
        expl = param_map["介质特性（爆炸危险程度）"].get("壳程数值", "")
        if expl == "可燃":
            media_parts.append("介质易爆")
    if "介质特性（毒性危害程度）" in param_map:
        shell_toxic = param_map["介质特性（毒性危害程度）"].get("壳程数值", "")
        tube_toxic = param_map["介质特性（毒性危害程度）"].get("管程数值", "")
        if shell_toxic:
            media_parts.append(f"{shell_toxic}危害")
        if tube_toxic:
            media_parts.append(f"{tube_toxic}危害")

    if media_parts:
        design_params["介质类型"] = "/".join(media_parts)

    # ===== 获取"是否以外径为基准" =====
    cursor.execute("""
        SELECT 数值 FROM 产品设计活动表_通用数据表
        WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
    """, (product_id,))
    row = cursor.fetchone()
    if row and "数值" in row:
        val = str(row["数值"]).strip()
        design_params["是否以外径为基准"] = "1" if val == "是" else "0"

    dict_part = {
        "管箱封头": "椭圆形封头",
        "管箱圆筒": "筒体",
        "管箱法兰": "法兰",
        "管箱分程隔板": "分程隔板",
        "壳体圆筒": "筒体",
        "壳体法兰": "法兰",
        "固定管板": "a型管板（浮头式）",
        "浮头管束": "浮头管束",
        "外头盖封头": "椭圆形封头",
        "鞍座": "鞍座",
        "外头盖侧法兰": "法兰",
        "浮头法兰": "浮头法兰",
        "外头盖法兰": "法兰",
        "外头盖圆筒": "筒体",
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
    futou_falan = {'浮头法兰内径含覆层': 0, '浮头法兰外径含覆层': 0, '法兰名义厚度': 0, '球冠形封头名义厚度': 0,
                   'B型钩圈名义厚度': 0, 'B型钩圈颈部厚度': 0, '壳体圆筒名义内径': 0, '球冠形封头预设厚度1': 0,
                   '球冠形封头预设厚度2': 0, '球冠形封头预设厚度3': 0, '浮动管板名义厚度': 0, '浮动管板名义外径': 0,
                   '公称直径': 0, '壳程液柱密度': 0, '管程液柱密度': 0, '壳程液柱静压力': 0, '管程液柱静压力': 0,
                   '法兰材料类型': 0, '法兰材料牌号': 0, '管程法兰材料腐蚀裕量': 0, '壳程法兰材料腐蚀裕量': 0,
                   '浮头法兰管程覆层厚度': 0, '浮头法兰壳程覆层厚度': 0, '球冠形封头材料类型': 0,
                   '球冠形封头材料牌号': 0, '球冠形封头装入深度': 0, '球冠形封头焊接接头系数': 0,
                   '法兰密封面凸台高度': 0, '球冠形封头管程覆层厚度': 0, '球冠形封头壳程覆层厚度': 0,
                   '管程球冠形封头腐蚀裕量': 0, '壳程球冠形封头腐蚀裕量': 0, '压紧面形状序号': 0,
                   '法兰压紧面压紧宽度ω': 0, '垫片名义外径': 0, '垫片名义内径': 0, '球冠形封头覆层复合方式': 0,
                   '球冠形封头带覆层时的焊接凹槽深度': 0, 'B型钩圈试验温度': 0, 'B型钩圈材料类型': 0,
                   'B型钩圈材料牌号': 0, 'B型钩圈覆层厚度': 0, '覆层位置': 0, '螺栓中心圆直径': 0, '螺栓材料牌号': 0,
                   '螺栓公称直径': 0, '螺栓数量': 0, '螺栓根径': 0, '垫片材料牌号': 0, 'm': 0, 'y': 0, '垫片厚度': 0,
                   '分程隔板与垫片接触面面积': 0, '垫片实际密封宽度': 0, '垫片代号': 0, '隔条位置尺寸': 0,
                   '垫片标准号': 0, '分程隔板槽宽度': 0, '球冠形封头试验温度': 0, '球冠形封头管程压力试验类型': 0,
                   '球冠形封头壳程压力试验类型': 0}

    waitougai_yuantong = {
        "预设厚度1": "8",  # 外头盖圆筒
        "预设厚度2": "10",  # 外头盖圆筒
        "预设厚度3": "12",  # 外头盖圆筒
        "圆筒使用位置": "外头盖圆筒",  # 外头盖圆筒
        "圆筒名义厚度": "0",  # 无
        "圆筒内/外径": "1000",  # 管程
        "是否按外径计算": "1",  # 是否以外径为基准
        "液柱静压力": "0",  # 管程
        "用户自定义MAWP": "0",  # 最高允许工作压力，管程
        "耐压试验温度": "15",  # 无
        "耐压试验压力": "0",  # 管程，壳程取max
        "圆筒长度": "1200",  # 无
        "外压圆筒计算长度": "1200",  # 无
        "材料类型": "板材",  # 外头盖圆筒
        "材料牌号": "Q345R",  # 外头盖圆筒
        "腐蚀裕量": "1",  # 管程
        "焊接接头系数": "1",  # 管程
        "压力试验类型": "液压",  # 耐压试验类型，管程
        "覆层复合方式": "轧制复合",  # 外头盖圆筒
        "圆筒覆层厚度": "0",  # 外头盖圆筒
        "圆筒带覆层时的焊接凹槽深度": "0",  # 无
        "泊松比": "0.3",  # 无
        "换热管长度": "",  # 换热管公称长度 LN
        "是否覆层": "0",  # 外头盖圆筒
        "覆层材料类型": "钢板",  # 外头盖圆筒
        "公称直径": "0",
    }
    try:

        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()

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
        print(f"❌ 查询失败: {e}")

    # === 处理参数值（空或无效则默认 6000） ===
    tube_length = raw_val if raw_val not in (None, "", " ", "None") else "6000"

    # 写入 qiaoti_yuantong
    waitougai_yuantong["换热管长度"] = tube_length
    cursor.execute("""
           SELECT 参数名称, 参数值 
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s AND 元件名称 = '外头盖圆筒'
       """, (product_id,))
    extra_rows = cursor.fetchall()
    extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}

    # 是否添加覆层
    if extra_map.get("是否添加覆层") == "是":
        waitougai_yuantong["是否覆层"] = "1"
        waitougai_yuantong["覆层材料类型"] = extra_map.get("覆层材料类型", "")
        waitougai_yuantong["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        waitougai_yuantong["圆筒覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
    else:
        waitougai_yuantong["覆层材料类型"] = "钢板"
        waitougai_yuantong["是否覆层"] = "0"
        waitougai_yuantong["覆层复合方式"] = "无"
        waitougai_yuantong["圆筒覆层厚度"] = "0"
    # === 查询数据库 ===
    cursor.execute("""
        SELECT 参数名称, 壳程数值, 管程数值
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

    val1 = parse_float(param_map.get("自定义耐压试验压力（卧）", {}).get("管程数值", ""))
    val2 = parse_float(param_map.get("自定义耐压试验压力（立）", {}).get("管程数值", ""))

    # === 最大允许工作压力（管程数值） ===
    value = param_map.get("最大允许工作压力", {}).get("管程数值")
    if value not in [None, ""]:
        waitougai_yuantong["最大允许工作压力"] = str(value)

    # === 耐压试验压力：取最大值 ===
    if val1 is not None and val2 is not None:
        waitougai_yuantong["耐压试验压力"] = str(max(val1, val2))
    elif val1 is not None:
        waitougai_yuantong["耐压试验压力"] = str(val1)
    elif val2 is not None:
        waitougai_yuantong["耐压试验压力"] = str(val2)
    else:
        waitougai_yuantong["耐压试验压力"] = "0"

    # ===== 获取预设厚度1~3（来自元件附加参数表）=====
    cursor.execute("""
        SELECT 参数名称, 参数值 FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '外头盖圆筒'
    """, (product_id,))
    rows = cursor.fetchall()
    extra_param_map = {r["参数名称"].strip(): r["参数值"] for r in rows}

    # 写入 guangxiang_fengtou 中的预设厚度
    for i in range(1, 4):
        key = f"预设厚度{i}"
        if key in extra_param_map:
            waitougai_yuantong[key] = str(extra_param_map[key])

    # 从数据库获取“是否以外径为基准*”的管程数值
    cursor.execute("""
        SELECT 数值 FROM 产品设计活动表_通用数据表
        WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
    """, (product_id,))
    row = cursor.fetchone()
    if row and "数值" in row:
        waitougai_yuantong["是否按外径计算"] = "1" if row["数值"] == "是" else "0"
    if isDi_change:
        waitougai_yuantong["圆筒内/外径"] = user_Di
    else:
        if isDN_change:
            waitougai_yuantong["圆筒内/外径"] = user_DN
        else:
            cursor.execute("""
                    SELECT 管程数值 FROM 产品设计活动表_设计数据表
                    WHERE 产品ID = %s AND 参数名称 = '公称直径*'
                """, (product_id,))
            row = cursor.fetchone()
            if row and "管程数值" in row:
                waitougai_yuantong["圆筒内/外径"] = str(row["管程数值"])

    map3 = {
        "液柱静压力": "液柱静压力",
        "用户自定义MAWP": "最高允许工作压力",
        "腐蚀裕量": "腐蚀裕量*",
        "焊接接头系数": "焊接接头系数*",

    }

    for key, param_name in map3.items():
        value = param_map.get(param_name, {}).get("管程数值", "")
        if value != "":
            waitougai_yuantong[key] = str(value)

    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '外头盖圆筒'
    """, (product_id,))
    rows = cursor.fetchall()
    extra_map = {r["参数名称"]: r["参数值"] for r in rows}

    if "材料类型" in extra_map:
        raw_type = extra_map["材料类型"]
        waitougai_yuantong["材料类型"] = material_type_map.get(raw_type, raw_type)
    if "材料牌号" in extra_map:
        waitougai_yuantong["材料牌号"] = extra_map["材料牌号"]
    # ===== 压力试验类型（仅去掉末尾“试验”）=====
    if "耐压试验类型*" in param_map:
        val = param_map["耐压试验类型*"].get("管程数值", "")
        if val:
            waitougai_yuantong["压力试验类型"] = str(val).replace("试验", "").strip()
    waitougai_falan = {'换热器型号': 0, '壳程液柱密度': 0, '管程液柱密度': 0, '壳程液柱静压力': 0, '管程液柱静压力': 0,
                       '压紧面形状序号': 0, '法兰是否考虑腐蚀裕量': 0, '法兰压紧面压紧宽度ω': 0, '轴向外力': 0,
                       '外力矩': 0, '法兰类型': 0, '法兰材料类型': 0, '法兰材料牌号': 0, '法兰材料腐蚀裕量': 0,
                       '法兰颈部大端有效厚度': 0, '法兰颈部小端有效厚度': 0, '法兰名义内径': 0, '法兰名义外径': 0,
                       '法兰名义厚度': 0, '法兰颈部高度': 0, '覆层厚度': 0, '管程还是壳程': 0, '法兰为夹持法兰': 0,
                       '法兰位置': 0, '圆筒名义厚度': 0, '圆筒有效厚度': 0, '圆筒名义内径': 0, '圆筒名义外径': 0,
                       '圆筒材料类型': 0, '圆筒材料牌号': 0, '焊缝高度': 0, '焊缝长度': 0, '焊缝深度': 0, '法兰种类': 0,
                       '公称直径管前左': 0, '公称直径壳后右': 0, '对接元件管前左材料类型': 0,
                       '对接元件壳后右材料类型': 0, '对接元件管前左材料牌号': 0, '对接元件壳后右材料牌号': 0,
                       '是否带分程隔板管前左': 0, '是否带分程隔板壳后右': 0, '法兰类型管前左': 0,
                       '法兰材料类型管前左': 0, '法兰材料牌号管前左': 0, '法兰材料腐蚀裕量管前左': 0,
                       '法兰类型壳后右': 0, '法兰材料类型壳后右': 0, '法兰材料牌号壳后右': 0,
                       '法兰材料腐蚀裕量壳后右': 0, '覆层厚度管前左': 0, '覆层厚度壳后右': 0,
                       '对接元件覆层厚度管前左': 0, '对接元件覆层厚度壳后右': 0, '平盖序号': 0, '平盖直径': 0,
                       '纵向焊接接头系数': 0, '是否为圆形平盖': 0, '平盖材料类型': 0, '平盖材料牌号': 0,
                       '平盖分程隔板槽深度': 0, '平盖材料腐蚀裕量': 0, '平盖名义厚度': 0, '垫片名义外径': 0,
                       '垫片名义内径': 0, '螺栓中心圆直径': 0, '螺栓材料牌号': 0, '螺栓公称直径': 0, '螺栓数量': 0,
                       '螺栓根径': 0, '垫片材料牌号': 0, 'm': 0, 'y': 0, '垫片厚度': 0, '垫片有效外径': 0,
                       '垫片有效内径': 0, '分程隔板与垫片接触面面积': 0, '垫片代号': 0, '隔条位置尺寸': 0,
                       '介质情况': 0, '垫片标准号': 0, '垫片实际密封宽度': 0, '分程隔板槽宽度': 0}

    waitougaice_falan = {'换热器型号': 0, '壳程液柱密度': 0, '管程液柱密度': 0, '壳程液柱静压力': 0,
                         '管程液柱静压力': 0, '压紧面形状序号': 0, '法兰是否考虑腐蚀裕量': 0, '法兰压紧面压紧宽度ω': 0,
                         '轴向外力': 0, '外力矩': 0, '法兰类型': 0, '法兰材料类型': 0, '法兰材料牌号': 0,
                         '法兰材料腐蚀裕量': 0, '法兰颈部大端有效厚度': 0, '法兰颈部小端有效厚度': 0, '法兰名义内径': 0,
                         '法兰名义外径': 0, '法兰名义厚度': 0, '法兰颈部高度': 0, '覆层厚度': 0, '管程还是壳程': 0,
                         '法兰为夹持法兰': 0, '法兰位置': 0, '圆筒名义厚度': 0, '圆筒有效厚度': 0, '圆筒名义内径': 0,
                         '圆筒名义外径': 0, '圆筒材料类型': 0, '圆筒材料牌号': 0, '焊缝高度': 0, '焊缝长度': 0,
                         '焊缝深度': 0, '法兰种类': 0, '公称直径管前左': 0, '公称直径壳后右': 0,
                         '对接元件管前左材料类型': 0, '对接元件壳后右材料类型': 0, '对接元件管前左材料牌号': 0,
                         '对接元件壳后右材料牌号': 0, '是否带分程隔板管前左': 0, '是否带分程隔板壳后右': 0,
                         '法兰类型管前左': 0, '法兰材料类型管前左': 0, '法兰材料牌号管前左': 0,
                         '法兰材料腐蚀裕量管前左': 0, '法兰类型壳后右': 0, '法兰材料类型壳后右': 0,
                         '法兰材料牌号壳后右': 0, '法兰材料腐蚀裕量壳后右': 0, '覆层厚度管前左': 0, '覆层厚度壳后右': 0,
                         '对接元件覆层厚度管前左': 0, '对接元件覆层厚度壳后右': 0, '平盖序号': 0, '平盖直径': 0,
                         '纵向焊接接头系数': 0, '是否为圆形平盖': 0, '平盖材料类型': 0, '平盖材料牌号': 0,
                         '平盖分程隔板槽深度': 0, '平盖材料腐蚀裕量': 0, '平盖名义厚度': 0, '垫片名义外径': 0,
                         '垫片名义内径': 0, '螺栓中心圆直径': 0, '螺栓材料牌号': 0, '螺栓公称直径': 0, '螺栓数量': 0,
                         '螺栓根径': 0, '垫片材料牌号': 0, 'm': 0, 'y': 0, '垫片厚度': 0, '垫片有效外径': 0,
                         '垫片有效内径': 0, '分程隔板与垫片接触面面积': 0, '垫片代号': 0, '隔条位置尺寸': 0,
                         '介质情况': 0, '垫片标准号': 0, '垫片实际密封宽度': 0, '分程隔板槽宽度': 0}

    tougai_falan = {'换热器型号': 0, '壳程液柱密度': 0, '管程液柱密度': 0, '壳程液柱静压力': 0, '管程液柱静压力': 0,
                    '压紧面形状序号': 0, '法兰是否考虑腐蚀裕量': 0, '法兰压紧面压紧宽度ω': 0, '轴向外力': 0,
                    '外力矩': 0, '法兰类型': 0, '法兰材料类型': 0, '法兰材料牌号': 0, '法兰材料腐蚀裕量': 0,
                    '法兰颈部大端有效厚度': 0, '法兰颈部小端有效厚度': 0, '法兰名义内径': 0, '法兰名义外径': 0,
                    '法兰名义厚度': 0, '法兰颈部高度': 0, '覆层厚度': 0, '管程还是壳程': 0, '法兰为夹持法兰': 0,
                    '法兰位置': 0, '圆筒名义厚度': 0, '圆筒有效厚度': 0, '圆筒名义内径': 0, '圆筒名义外径': 0,
                    '圆筒材料类型': 0, '圆筒材料牌号': 0, '焊缝高度': 0, '焊缝长度': 0, '焊缝深度': 0, '法兰种类': 0,
                    '公称直径管前左': 0, '公称直径壳后右': 0, '对接元件管前左材料类型': 0, '对接元件壳后右材料类型': 0,
                    '对接元件管前左材料牌号': 0, '对接元件壳后右材料牌号': 0, '是否带分程隔板管前左': 0,
                    '是否带分程隔板壳后右': 0, '法兰类型管前左': 0, '法兰材料类型管前左': 0, '法兰材料牌号管前左': 0,
                    '法兰材料腐蚀裕量管前左': 0, '法兰类型壳后右': 0, '法兰材料类型壳后右': 0, '法兰材料牌号壳后右': 0,
                    '法兰材料腐蚀裕量壳后右': 0, '覆层厚度管前左': 0, '覆层厚度壳后右': 0, '对接元件覆层厚度管前左': 0,
                    '对接元件覆层厚度壳后右': 0, '平盖序号': 0, '平盖直径': 0, '纵向焊接接头系数': 0,
                    '是否为圆形平盖': 0, '平盖材料类型': 0, '平盖材料牌号': 0, '平盖分程隔板槽深度': 0,
                    '平盖材料腐蚀裕量': 0, '平盖名义厚度': 0, '垫片名义外径': 0, '垫片名义内径': 0, '螺栓中心圆直径': 0,
                    '螺栓材料牌号': 0, '螺栓公称直径': 0, '螺栓数量': 0, '螺栓根径': 0, '垫片材料牌号': 0, 'm': 0,
                    'y': 0, '垫片厚度': 0, '垫片有效外径': 0, '垫片有效内径': 0, '分程隔板与垫片接触面面积': 0,
                    '垫片代号': 0, '隔条位置尺寸': 0, '介质情况': 0, '垫片标准号': 0, '垫片实际密封宽度': 0,
                    '分程隔板槽宽度': 0}

    guangxiang_pinggai = {'分程隔板槽宽度': 0, '换热器型号': 0, '壳程液柱密度': 0, '管程液柱密度': 0,
                          '壳程液柱静压力': 0, '管程液柱静压力': 0, '压紧面形状序号': 0, '法兰是否考虑腐蚀裕量': 0,
                          '法兰压紧面压紧宽度ω': 0, '轴向外力': 0, '外力矩': 0, '法兰类型': 0, '法兰材料类型': 0,
                          '法兰材料牌号': 0, '法兰材料腐蚀裕量': 0, '法兰颈部大端有效厚度': 0,
                          '法兰颈部小端有效厚度': 0, '法兰名义内径': 0, '法兰名义外径': 0, '法兰名义厚度': 0,
                          '法兰颈部高度': 0, '覆层厚度': 0, '管程还是壳程': 0, '法兰为夹持法兰': 0, '法兰位置': 0,
                          '圆筒名义厚度': 0, '圆筒有效厚度': 0, '圆筒名义内径': 0, '圆筒名义外径': 0, '圆筒材料类型': 0,
                          '圆筒材料牌号': 0, '焊缝高度': 0, '焊缝长度': 0, '焊缝深度': 0, '法兰种类': 0, '介质情况': 0,
                          '公称直径管前左': 0, '公称直径壳后右': 0, '对接元件管前左材料类型': 0,
                          '对接元件壳后右材料类型': 0, '对接元件管前左材料牌号': 0, '对接元件壳后右材料牌号': 0,
                          '是否带分程隔板管前左': 0, '是否带分程隔板壳后右': 0, '法兰类型管前左': 0,
                          '法兰材料类型管前左': 0, '法兰材料牌号管前左': 0, '法兰材料腐蚀裕量管前左': 0,
                          '法兰类型壳后右': 0, '法兰材料类型壳后右': 0, '法兰材料牌号壳后右': 0,
                          '法兰材料腐蚀裕量壳后右': 0, '覆层厚度管前左': 0, '覆层厚度壳后右': 0,
                          '对接元件覆层厚度管前左': 0, '对接元件覆层厚度壳后右': 0, '垫片名义外径': 0,
                          '垫片名义内径': 0, '平盖序号': 0, '纵向焊接接头系数': 0, '平盖直径': 0, '是否为圆形平盖': 0,
                          '平盖材料类型': 0, '平盖材料牌号': 0, '平盖分程隔板槽深度': 0, '平盖材料腐蚀裕量': 0,
                          '平盖名义厚度': 0, '螺栓中心圆直径': 0, '螺栓材料牌号': 0, '螺栓公称直径': 0, '螺栓数量': 0,
                          '螺栓根径': 0, '垫片材料牌号': 0, 'm': 0, 'y': 0, '垫片厚度': 0, '垫片有效外径': 0,
                          '垫片有效内径': 0, '分程隔板与垫片接触面面积': 0, '垫片代号': 0, '隔条位置尺寸': 0,
                          '垫片标准号': 0, '垫片实际密封宽度': 0}

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
    if isDN_change:
        guangxiang_fengtou["公称直径"]=user_DN
    # ===== 获取预设厚度1~3（来自元件附加参数表）=====
    cursor.execute("""
        SELECT 参数名称, 参数值 FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱封头'
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
        SELECT 参数名称, 壳程数值, 管程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row for row in rows}

    cursor.execute("""
        SELECT 数值 FROM 产品设计活动表_通用数据表
        WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
    """, (product_id,))
    row = cursor.fetchone()
    if row and "数值" in row:
        val = str(row["数值"]).strip()
        design_params["是否以外径为基准"] = "1" if val == "是" else "0"

    # 查询设计数据表
    cursor.execute("""
        SELECT 参数名称, 壳程数值, 管程数值
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
        value = param_map.get(param_name, {}).get("管程数值", "")
        if value != "":
            guangxiang_fengtou[key] = str(value)

    # ===== 压力试验类型（去掉末尾“试验”并映射为数字）=====
    pressure_type_map = {
        "液压": "1",
        "气压": "2",
        "气液": "3"
    }

    if "耐压试验类型*" in param_map:
        val = param_map["耐压试验类型*"].get("管程数值", "")
        if val:
            clean_val = str(val).replace("试验", "").strip()
            guangxiang_fengtou["压力试验类型"] = pressure_type_map.get(clean_val, "0")

    # ===== 用户自定义耐压试验压力：取卧与立中较大者 =====
    val1 = param_map.get("自定义耐压试验压力（卧）", {}).get("管程数值", "")
    val2 = param_map.get("自定义耐压试验压力（立）", {}).get("管程数值", "")
    # ===== 最大允许工作压力 =====
    if "最大允许工作压力" in param_map:
        value = param_map["最大允许工作压力"].get("管程数值", "")
        if value != "":
            guangxiang_fengtou["最大允许工作压力"] = str(value)

    try:
        val_max = max(float(val1), float(val2))
        guangxiang_fengtou["用户自定义耐压试验压力"] = str(int(val_max))
    except:
        guangxiang_fengtou["用户自定义耐压试验压力"] = str(val1 or val2 or "0")  # 至少有一个值就保留

    # 查询元件附加参数表中元件名称为“管箱封头”的数据
    cursor.execute("""
        SELECT 参数名称, 参数值 
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱封头'
    """, (product_id,))
    extra_rows = cursor.fetchall()
    extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}

    # 是否添加覆层
    if extra_map.get("是否添加覆层") == "是":
        guangxiang_fengtou["是否覆层"] = "1"
        guangxiang_fengtou["覆层材料类型"] = extra_map.get("覆层材料类型", "轧制复合")  # 若为空可改为 "未知"

        guangxiang_fengtou["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        guangxiang_fengtou["椭圆形封头覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
    else:
        guangxiang_fengtou["是否覆层"] = "0"
        guangxiang_fengtou["覆层材料类型"] = "钢板"  # 若为空可改为 "未知"
        guangxiang_fengtou["覆层复合方式"] = "无"
        guangxiang_fengtou["椭圆形封头覆层厚度"] = "0"
        guangxiang_fengtou["椭圆形封头曲面深度"] = extra_map.get("封头面曲面深度hi", "0")  # 默认“未知”可改为""

    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱封头'
    """, (product_id,))
    rows = cursor.fetchall()
    extra_map = {r["参数名称"]: r["参数值"] for r in rows}

    if "材料类型" in extra_map:
        raw_type = extra_map["材料类型"]
        guangxiang_fengtou["材料类型"] = material_type_map.get(raw_type, raw_type)
    if "材料牌号" in extra_map:
        guangxiang_fengtou["材料牌号"] = extra_map["材料牌号"]

        # 初始化字典
    waitougai_fengtou = {
        "预设厚度1": "8",  # 外头盖封头
        "预设厚度2": "10",  # 外头盖封头
        "预设厚度3": "12",  # 外头盖封头
        "是否以外径为基准": "1",  # 是否以外径为基准
        "公称直径": "1000",  # 壳程
        "液柱静压力": "0",  # 壳程
        "腐蚀余量": "3",  # 壳程
        "焊接接头系数": "1",  # 壳程
        "压力试验类型": "1",  # 壳程
        "用户自定义耐压试验压力": "0",  # 用户自定义耐压试验压力，壳程管程取max
        "压力试验温度": "15",
        "最大允许工作压力": "0",  # 最高允许工作压力，壳程
        "封头与圆筒的连接型式": "A",
        "是否覆层": "1",  # 外头盖封头
        "覆层复合方式": "轧制复合",  # 外头盖封头
        "带覆层时的焊接凹槽深度": "2",
        "是否采用拼(板)接成形": "0",
        "封头成型厚度减薄率": "11",
        "材料类型": "板材",  # 外头盖封头
        "材料牌号": "Q345R",  # 外头盖封头
        "椭圆形封头内/外径": "1000",  # 壳程，公称直径
        "椭圆形封头名义厚度": "0",
        "椭圆形封头覆层厚度": "3",  # 外头盖封头
        "椭圆形封头曲面深度": "250",
        "椭圆形封头直边段高度": "25",
        "覆层材料类型": ""  # 外头盖封头
    }
    # ===== 获取预设厚度1~3（来自元件附加参数表）=====
    cursor.execute("""
        SELECT 参数名称, 参数值 FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '外头盖封头'
    """, (product_id,))
    rows = cursor.fetchall()
    extra_param_map = {r["参数名称"].strip(): r["参数值"] for r in rows}

    # 写入 guangxiang_fengtou 中的预设厚度
    for i in range(1, 4):
        key = f"预设厚度{i}"
        if key in extra_param_map:
            waitougai_fengtou[key] = str(extra_param_map[key])

    cursor.execute("""
        SELECT 数值 FROM 产品设计活动表_通用数据表
        WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
    """, (product_id,))
    row = cursor.fetchone()
    if row and "数值" in row:
        val = str(row["数值"]).strip()
        waitougai_fengtou["是否以外径为基准"] = "1" if val == "是" else "0"

    # 查询设计数据表
    cursor.execute("""
           SELECT 参数名称, 壳程数值, 管程数值
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
            waitougai_fengtou[key] = str(value)

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

    try:
        val_max = max(float(val1), float(val2))
        waitougai_fengtou["用户自定义耐压试验压力"] = str(val_max)
    except:
        waitougai_fengtou["用户自定义耐压试验压力"] = str(val1 or val2 or "0")  # 至少有一个值就保留

    # 查询元件附加参数表中元件名称为“管箱封头”的数据
    cursor.execute("""
           SELECT 参数名称, 参数值 
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s AND 元件名称 = '外头盖封头'
       """, (product_id,))
    extra_rows = cursor.fetchall()
    extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}

    # 是否添加覆层
    if extra_map.get("是否添加覆层") == "是":
        waitougai_fengtou["是否覆层"] = "1"
        waitougai_fengtou["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        waitougai_fengtou["椭圆形封头覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
        waitougai_fengtou["覆层材料类型"] = extra_map.get("覆层材料类型", "")  # 若为空可改为 "未知"

    else:
        waitougai_fengtou["是否覆层"] = "0"
        waitougai_fengtou["覆层复合方式"] = "无"
        waitougai_fengtou["椭圆形封头覆层厚度"] = "0"
        waitougai_fengtou["覆层材料类型"] = "钢板"

    waitougai_fengtou["椭圆形封头曲面深度"] = extra_map.get("封头面曲面深度hi", "0")  # 默认“未知”可改为""

    cursor.execute("""
           SELECT 参数名称, 参数值
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s AND 元件名称 = '外头盖封头'
       """, (product_id,))
    rows = cursor.fetchall()
    extra_map = {r["参数名称"]: r["参数值"] for r in rows}

    if "材料类型" in extra_map:
        raw_type = extra_map["材料类型"]
        waitougai_fengtou["材料类型"] = material_type_map.get(raw_type, raw_type)
    if "材料牌号" in extra_map:
        waitougai_fengtou["材料牌号"] = extra_map["材料牌号"]

    # 初始化默认值
    guanxiang_yuantong = {
        "预设厚度1": "8",
        "预设厚度2": "10",
        "预设厚度3": "12",
        "圆筒使用位置": "管箱圆筒",
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
        "公称直径": ''
    }
    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()
        # === 查询换热管公称长度 LN ===
        cursor.execute("""
                   SELECT 管程数值
                   FROM 产品设计活动表_设计数据表
                   WHERE 产品ID = %s AND 参数名称 = '公称直径*'
                   LIMIT 1
               """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["管程数值"].strip() if row and row.get("管程数值") else None
        guanxiang_yuantong["公称直径"] = raw_val
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
        print(f"❌ 查询失败: {e}")

    # === 处理参数值（空或无效则默认 6000） ===
    tube_length = raw_val if raw_val not in (None, "", " ", "None") else "6000"

    # 写入 qiaoti_yuantong
    guanxiang_yuantong["换热管长度"] = tube_length
    cursor.execute("""
           SELECT 参数名称, 参数值 
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
       """, (product_id,))
    extra_rows = cursor.fetchall()
    extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}

    # 是否添加覆层
    if extra_map.get("是否添加覆层") == "是":
        guanxiang_yuantong["是否覆层"] = "1"
        guanxiang_yuantong["覆层材料类型"] = extra_map.get("覆层材料类型", "")
        guanxiang_yuantong["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        guanxiang_yuantong["圆筒覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
    else:
        guanxiang_yuantong["覆层材料类型"] = "钢板"
        guanxiang_yuantong["是否覆层"] = "0"
        guanxiang_yuantong["覆层复合方式"] = "无"
        guanxiang_yuantong["圆筒覆层厚度"] = "0"
    # === 查询数据库 ===
    cursor.execute("""
        SELECT 参数名称, 壳程数值, 管程数值
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

    val1 = parse_float(param_map.get("自定义耐压试验压力（卧）", {}).get("管程数值", ""))
    val2 = parse_float(param_map.get("自定义耐压试验压力（立）", {}).get("管程数值", ""))

    # === 最大允许工作压力（管程数值） ===
    value = param_map.get("最大允许工作压力", {}).get("管程数值")
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
        WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
    """, (product_id,))
    rows = cursor.fetchall()
    extra_param_map = {r["参数名称"].strip(): r["参数值"] for r in rows}

    # 写入 guangxiang_fengtou 中的预设厚度
    for i in range(1, 4):
        key = f"预设厚度{i}"
        if key in extra_param_map:
            guanxiang_yuantong[key] = str(extra_param_map[key])

    # 从数据库获取“是否以外径为基准*”的管程数值
    cursor.execute("""
        SELECT 数值 FROM 产品设计活动表_通用数据表
        WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
    """, (product_id,))
    row = cursor.fetchone()
    if row and "数值" in row:
        guanxiang_yuantong["是否按外径计算"] = "1" if row["数值"] == "是" else "0"
    if isDi_change:
        guanxiang_yuantong["圆筒内/外径"] = user_Di
    else:
        if isDN_change:
            guanxiang_yuantong["圆筒内/外径"] = user_DN
        else:
            # 查询设计数据表，获取公称直径*
            cursor.execute("""
                    SELECT 管程数值 FROM 产品设计活动表_设计数据表
                    WHERE 产品ID = %s AND 参数名称 = '公称直径*'
                """, (product_id,))
            row = cursor.fetchone()
            if row and "管程数值" in row:
                guanxiang_yuantong["圆筒内/外径"] = str(row["管程数值"])

    map3 = {
        "液柱静压力": "液柱静压力",
        "用户自定义MAWP": "最高允许工作压力",
        "腐蚀裕量": "腐蚀裕量*",
        "焊接接头系数": "焊接接头系数*",

    }

    for key, param_name in map3.items():
        value = param_map.get(param_name, {}).get("管程数值", "")
        if value != "":
            guanxiang_yuantong[key] = str(value)

    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
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
        val = param_map["耐压试验类型*"].get("管程数值", "")
        if val:
            guanxiang_yuantong["压力试验类型"] = str(val).replace("试验", "").strip()

        # 初始化默认值
    qiaoti_yuantong = {
        "预设厚度1": "8",
        "预设厚度2": "10",
        "预设厚度3": "12",
        "圆筒使用位置": "壳体圆筒",
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
    }

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()
        # === 查询换热管公称长度 LN ===
        cursor.execute("""
                    SELECT 壳程数值
                    FROM 产品设计活动表_设计数据表
                    WHERE 产品ID = %s AND 参数名称 = '公称直径*'
                    LIMIT 1
                """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["壳程数值"].strip() if row and row.get("壳程数值") else None
        qiaoti_yuantong["公称直径"] = raw_val
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
        print(f"❌ 查询失败: {e}")

    # === 处理参数值（空或无效则默认 6000） ===
    tube_length = raw_val if raw_val not in (None, "", " ", "None") else "6000"

    # 写入 qiaoti_yuantong
    qiaoti_yuantong["换热管长度"] = tube_length
    cursor.execute("""
           SELECT 参数名称, 参数值 
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s AND 元件名称 = '壳体圆筒'
       """, (product_id,))
    extra_rows = cursor.fetchall()
    extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}

    # 是否添加覆层
    if extra_map.get("是否添加覆层") == "是":
        qiaoti_yuantong["是否覆层"] = "1"
        qiaoti_yuantong["覆层材料类型"] = extra_map.get("覆层材料类型", "")  # 若为空可改为 "未知"

        qiaoti_yuantong["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        qiaoti_yuantong["圆筒覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
    else:
        qiaoti_yuantong["是否覆层"] = "0"
        qiaoti_yuantong["覆层材料类型"] = "钢板"

        qiaoti_yuantong["覆层复合方式"] = "无"
        qiaoti_yuantong["圆筒覆层厚度"] = "0"
    # 查询设计数据表
    # === 查询数据库 ===
    cursor.execute("""
        SELECT 参数名称, 壳程数值, 管程数值
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

    val1 = parse_float(param_map.get("自定义耐压试验压力（卧）", {}).get("管程数值", ""))
    val2 = parse_float(param_map.get("自定义耐压试验压力（立）", {}).get("管程数值", ""))

    # === 最大允许工作压力（管程数值） ===
    value = param_map.get("最大允许工作压力", {}).get("管程数值")
    if value not in [None, ""]:
        guanxiang_yuantong["最大允许工作压力"] = str(value)

    # === 耐压试验压力：取最大值 ===
    if val1 is not None and val2 is not None:
        qiaoti_yuantong["耐压试验压力"] = str(max(val1, val2))
    elif val1 is not None:
        qiaoti_yuantong["耐压试验压力"] = str(val1)
    elif val2 is not None:
        qiaoti_yuantong["耐压试验压力"] = str(val2)
    else:
        qiaoti_yuantong["耐压试验压力"] = "0"

    # ===== 获取预设厚度1~3（来自元件附加参数表）=====
    cursor.execute("""
        SELECT 参数名称, 参数值 FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '壳体圆筒'
    """, (product_id,))
    rows = cursor.fetchall()
    extra_param_map = {r["参数名称"].strip(): r["参数值"] for r in rows}

    # 写入 guangxiang_fengtou 中的预设厚度
    for i in range(1, 4):
        key = f"预设厚度{i}"
        if key in extra_param_map:
            qiaoti_yuantong[key] = str(extra_param_map[key])
    # 从数据库获取“是否以外径为基准*”的管程数值
    cursor.execute("""
           SELECT 数值 FROM 产品设计活动表_通用数据表
           WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
       """, (product_id,))
    row = cursor.fetchone()
    if row and "数值" in row:
        qiaoti_yuantong["是否按外径计算"] = "1" if row["数值"] == "是" else "0"
    if isDi_change:
        qiaoti_yuantong["圆筒内/外径"] = user_Di
    else:
        if isDN_change:
            qiaoti_yuantong["圆筒内/外径"] = user_DN
        else:
            # 查询设计数据表，获取公称直径*
            cursor.execute("""
                       SELECT 壳程数值 FROM 产品设计活动表_设计数据表
                       WHERE 产品ID = %s AND 参数名称 = '公称直径*'
                   """, (product_id,))
            row = cursor.fetchone()
            if row and "壳程数值" in row:
                qiaoti_yuantong["圆筒内/外径"] = str(row["壳程数值"])

    map3 = {
        "液柱静压力": "液柱静压力",
        "用户自定义MAWP": "最高允许工作压力",
        "腐蚀裕量": "腐蚀裕量*",
        "焊接接头系数": "焊接接头系数*",

    }

    for key, param_name in map3.items():
        value = param_map.get(param_name, {}).get("壳程数值", "")
        if value != "":
            qiaoti_yuantong[key] = str(value)

    cursor.execute("""
           SELECT 参数名称, 参数值
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s AND 元件名称 = '壳体圆筒'
       """, (product_id,))
    rows = cursor.fetchall()
    extra_map = {r["参数名称"]: r["参数值"] for r in rows}

    if "材料类型" in extra_map:
        raw_type = extra_map["材料类型"]
        qiaoti_yuantong["材料类型"] = material_type_map.get(raw_type, raw_type)
    if "材料牌号" in extra_map:
        qiaoti_yuantong["材料牌号"] = extra_map["材料牌号"]
    # ===== 压力试验类型（去掉末尾“试验”并映射为数字）=====
    if "耐压试验类型*" in param_map:
        val = param_map["耐压试验类型*"].get("壳程数值", "")
        if val:
            clean_val = str(val).replace("试验", "").strip()
            qiaoti_yuantong["压力试验类型"] = clean_val
        # 查询元件附加参数表中元件名称为“管箱封头”的数据
        # cursor.execute("""
        #        SELECT 参数名称, 参数值
        #        FROM 产品设计活动表_元件附加参数表
        #        WHERE 产品ID = %s AND 元件名称 = '外头盖封头'
        #    """, (product_id,))
        # extra_rows = cursor.fetchall()
        # extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}

    guanxiang_falan = {'换热器型号': 0, '壳程液柱密度': 0, '管程液柱密度': 0, '壳程液柱静压力': 0, '管程液柱静压力': 0,
                       '压紧面形状序号': 0, '法兰是否考虑腐蚀裕量': 0, '法兰压紧面压紧宽度ω': 0, '轴向外力': 0,
                       '外力矩': 0, '法兰类型': 0, '法兰材料类型': 0, '法兰材料牌号': 0, '法兰材料腐蚀裕量': 0,
                       '法兰颈部大端有效厚度': 0, '法兰颈部小端有效厚度': 0, '法兰名义内径': 0, '法兰名义外径': 0,
                       '法兰名义厚度': 0, '法兰颈部高度': 0, '覆层厚度': 0, '管程还是壳程': 0, '法兰为夹持法兰': 0,
                       '法兰位置': 0, '圆筒名义厚度': 0, '圆筒有效厚度': 0, '圆筒名义内径': 0, '圆筒名义外径': 0,
                       '圆筒材料类型': 0, '圆筒材料牌号': 0, '焊缝高度': 0, '焊缝长度': 0, '焊缝深度': 0, '法兰种类': 0,
                       '公称直径管前左': 0, '公称直径壳后右': 0, '对接元件管前左材料类型': 0,
                       '对接元件壳后右材料类型': 0, '对接元件管前左材料牌号': 0, '对接元件壳后右材料牌号': 0,
                       '是否带分程隔板管前左': 0, '是否带分程隔板壳后右': 0, '法兰类型管前左': 0,
                       '法兰材料类型管前左': 0, '法兰材料牌号管前左': 0, '法兰材料腐蚀裕量管前左': 0,
                       '法兰类型壳后右': 0, '法兰材料类型壳后右': 0, '法兰材料牌号壳后右': 0,
                       '法兰材料腐蚀裕量壳后右': 0, '覆层厚度管前左': 0, '覆层厚度壳后右': 0,
                       '对接元件覆层厚度管前左': 0, '对接元件覆层厚度壳后右': 0, '平盖序号': 0, '纵向焊接接头系数': 0,
                       '平盖直径': 0, '是否为圆形平盖': 0, '平盖材料类型': 0, '平盖材料牌号': 0,
                       '平盖分程隔板槽深度': 0, '平盖材料腐蚀裕量': 0, '平盖名义厚度': 0, '垫片名义外径': 0,
                       '垫片名义内径': 0, '螺栓中心圆直径': 0, '螺栓材料牌号': 0, '螺栓公称直径': 0, '螺栓数量': 0,
                       '螺栓根径': 0, '垫片材料牌号': 0, 'm': 0, 'y': 0, '垫片厚度': 0, '垫片有效外径': 0,
                       '垫片有效内径': 0, '分程隔板与垫片接触面面积': 0, '垫片代号': 0, '隔条位置尺寸': 0,
                       '介质情况': 0, '垫片标准号': 0, '垫片实际密封宽度': 0, '分程隔板槽宽度': 0}

    keti_falan = {'换热器型号': 0, '壳程液柱密度': 0, '管程液柱密度': 0, '壳程液柱静压力': 0, '管程液柱静压力': 0,
                  '压紧面形状序号': 0, '法兰是否考虑腐蚀裕量': 0, '法兰压紧面压紧宽度ω': 0, '轴向外力': 0, '外力矩': 0,
                  '法兰类型': 0, '法兰材料类型': 0, '法兰材料牌号': 0, '法兰材料腐蚀裕量': 0, '法兰颈部大端有效厚度': 0,
                  '法兰颈部小端有效厚度': 0, '法兰名义内径': 0, '法兰名义外径': 0, '法兰名义厚度': 0, '法兰颈部高度': 0,
                  '覆层厚度': 0, '管程还是壳程': 0, '法兰为夹持法兰': 0, '法兰位置': 0, '圆筒名义厚度': 0,
                  '圆筒有效厚度': 0, '圆筒名义内径': 0, '圆筒名义外径': 0, '圆筒材料类型': 0, '圆筒材料牌号': 0,
                  '焊缝高度': 0, '焊缝长度': 0, '焊缝深度': 0, '法兰种类': 0, '公称直径管前左': 0, '公称直径壳后右': 0,
                  '对接元件管前左材料类型': 0, '对接元件壳后右材料类型': 0, '对接元件管前左材料牌号': 0,
                  '对接元件壳后右材料牌号': 0, '是否带分程隔板管前左': 0, '是否带分程隔板壳后右': 0,
                  '法兰类型管前左': 0, '法兰材料类型管前左': 0, '法兰材料牌号管前左': 0, '法兰材料腐蚀裕量管前左': 0,
                  '法兰类型壳后右': 0, '法兰材料类型壳后右': 0, '法兰材料牌号壳后右': 0, '法兰材料腐蚀裕量壳后右': 0,
                  '覆层厚度管前左': 0, '覆层厚度壳后右': 0, '对接元件覆层厚度管前左': 0, '对接元件覆层厚度壳后右': 0,
                  '平盖序号': 0, '平盖直径': 0, '纵向焊接接头系数': 0, '是否为圆形平盖': 0, '平盖材料类型': 0,
                  '平盖材料牌号': 0, '平盖分程隔板槽深度': 0, '平盖材料腐蚀裕量': 0, '平盖名义厚度': 0,
                  '垫片名义外径': 0, '垫片名义内径': 0, '螺栓中心圆直径': 0, '螺栓材料牌号': 0, '螺栓公称直径': 0,
                  '螺栓数量': 0, '螺栓根径': 0, '垫片材料牌号': 0, 'm': 0, 'y': 0, '垫片厚度': 0, '垫片有效外径': 0,
                  '垫片有效内径': 0, '分程隔板与垫片接触面面积': 0, '垫片代号': 0, '隔条位置尺寸': 0, '介质情况': 0,
                  '垫片标准号': 0, '垫片实际密封宽度': 0, '分程隔板槽宽度': 0}

    fencheng_geban = {'材料类型': 0, '材料牌号': 0, '公称直径': 0, '管箱分程隔板名义厚度': 0,
                      '管箱分程隔板两侧压力差值': 0, '管箱分程隔板结构尺寸长边a': 0, '管箱分程隔板结构尺寸长边b': 0,
                      '管箱分程隔板结构型式': 0, '耐压试验温度': 0, '腐蚀裕量(双面)': 0, '管箱分程隔板设计余量': 0,
                      '隔条位置尺寸': 0, '分程隔板槽宽度': 0}

    guanban_a = {'公称直径': 0, '管程液柱静压力': 0, '壳程液柱静压力': 0, '管程腐蚀裕量': 0, '壳程腐蚀裕量': 0,
                 '是否可以保证在任何情况下管壳程压力都能同时作用': 0, '换热管使用场合': 0, '换热管与管板连接方式': 0,
                 '材料类型': 0, '材料牌号': 0, '管板名义厚度': 0, '管板外径': 0, '壳程侧结构槽深': 0,
                 '管程侧隔板槽深': 0, '管板强度削弱系数': 0, '管板刚度削弱系数': 0, '换热管材料类型': 0,
                 '换热管材料牌号': 0, '换热管外径': 0, '换热管壁厚': 0, '换热管直管段长度': 0, '换热管伸出管板长度': 0,
                 '换热管根数': 0, '换热管中心距': 0, '耐压试验温度': 0, '换热管受压失稳当量长度': 0,
                 '内孔焊焊接接头系数': 0, '换热管与管板胀接长度或焊脚高度': 0, '换热管是否钢材': 0,
                 '胀接管孔是否开槽': 0, '垫片材料名称': 0, '垫片与密封面接触外径': 0, '垫片与密封面接触内径': 0,
                 '垫片厚度': 0, '压紧面形式': 0, '换热管排列方式': 0, '折流板切口方向': 0, '管/壳程布置型式': 0,
                 '水平隔板槽两侧相邻管中心距': 0, '竖直隔板槽两侧相邻管中心距': 0, '相邻隔板槽中心距': 0,
                 '管板分程处面积Ad': 0, "'十字'交叉沿水平隔板槽单侧的排管根数": 0, '沿竖直隔板槽单侧的排管根数': 0,
                 "'丁字'交叉沿水平隔板槽连续侧的排管根数": 0, "'丁字'交叉沿水平隔板槽不连续侧的排管根数": 0,
                 "'十字'交叉沿水平隔板槽单侧管排1最两端管孔中心距": 0,
                 "'十字'交叉沿水平隔板槽单侧管排2最两端管孔中心距": 0,
                 "'十字'交叉沿水平隔板槽单侧管排3最两端管孔中心距": 0,
                 "'丁字'交叉沿水平隔板槽不连续侧管排1最两端管孔中心距": 0,
                 "'丁字'交叉沿水平隔板槽不连续侧管排2最两端管孔中心距": 0,
                 "'丁字'交叉沿水平隔板槽不连续侧管排3最两端管孔中心距": 0, '沿竖直隔板槽单侧的管排最两端管孔中心距': 0}

    tube_bundle = {'实际布管区域最大直径': 0, '实际布管区域最大高度': 0, '导流筒边缘过水平中心线距离': 0,
                   '导流筒厚度': 0, '旁路挡板厚度': 0, '导流筒内部折边倒角': 0, '换热管壁厚': 0, '换热管孔间距': 0,
                   '接管布置型式': 0, '管程数': 0, '换热管排列方式': 0, '折流板切口方向': 0,
                   '水平分程隔板槽两侧相邻管中心距水平上下': 0, '竖直分程隔板槽两侧相邻管中心距垂直左右': 0,
                   '水平分程隔板槽数量': 0, '竖直分程隔板槽数量': 0, '布管限定圆直径': 0, '换热管理论直管长度': 0,
                   '换热管伸出管板值': 0, '折流板切口与中心线间距': 0, '圆筒内径': 0, '公称直径': 0, '圆筒名义厚度': 0,
                   '管板类型': 0, '管板凸台高度': 0, '垫片厚度': 0, '管板与壳程圆筒连接台肩长度': 0,
                   '折流板需求间距': 0, '入口OD1/OD2': 0, '拉杆类型': 0, '拉杆用螺母厚度': 0, '换热管外径': 0,
                   '折流板厚度初始值': 0, '换热管材料序号': 0, '拉杆直径': 0, '换热管材料类型': 0, '换热管材料牌号': 0,
                   '内折流板材料牌号': 0, '内折流板材料类型': 0, '异形折流板材料牌号': 0, '异形折流板材料类型': 0,
                   '弓形折流板材料牌号': 0, '弓形折流板材料类型': 0, '支撑板材料牌号': 0, '支撑板材料类型': 0,
                   '导流筒材料牌号': 0, '导流筒材料类型': 0, '中间挡板材料牌号': 0, '中间挡板材料类型': 0,
                   '支持板材料牌号': 0, '支持板材料类型': 0, '滑道材料牌号': 0, '滑道材料类型': 0,
                   '中间挡管材料牌号': 0, '中间挡管材料类型': 0, '堵板材料牌号': 0, '堵板材料类型': 0,
                   '防冲挡板材料牌号': 0, '防冲挡板材料类型': 0, '拉杆材料牌号': 0, '拉杆材料类型': 0,
                   '定距管材料牌号': 0, '定距管材料类型': 0, '滑道高度': 0, '滑道厚度': 0, '防冲挡板宽度': 0,
                   '防冲挡板厚度': 0, '中间挡板宽度': 0, '中间挡板厚度': 0}

    anzuo = {'公称直径': 0, '鞍座设计温度': 0, '筋板材料类型': 0, '筋板材料牌号': 0, '筋板名义厚度': 0,
             '腹板材料类型': 0, '腹板材料牌号': 0, '腹板名义厚度': 0, '底板材料类型': 0, '底板材料牌号': 0,
             '底板名义厚度': 0}

    def build_jieguan(cursor, product_id, guankou_daihao):
        jieguan = {
            "设备公称直径": "1000",
            "接管是否以外径为基准": "True",
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
            "覆层复合方式": "轧制复合",
            "接管覆层厚度": "1",
            "接管带覆层时的焊接凹槽深度": "0",
            "接管最小有效外伸高度系数": "0.8",
            "焊缝面积A3焊脚高度系数": "0.7",
            "开孔补强自定义补强面积裕量百分比": "0",
            "补强区内的焊缝面积(含嵌入式接管焊缝面积)": "49",
            "补强圈材料类型": "板材",
            "补强圈材料牌号": "Q345R",
            "开孔元件名称": "管箱圆筒",
            "接管材料类型1": "钢管",
            "接管材料牌号1": "10(GB9948)",
            "接管材料类型2": "钢板",
            "接管材料牌号2": "Q345R",
            "接管材料类型3": "钢锻件",
            "接管材料牌号3": "16Mn",
            "管口表序号": guankou_daihao,
            "是否覆层": "",
            "覆层材料类型": ""
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
            jieguan["开孔元件名称"] = row.get("管口所属元件", "").strip()
            jieguan["接管中心线至筒体轴线距离(偏心距)"] = str(row.get("偏心距", "0"))
            jieguan["接管中心线与法线夹角(包括封头)"] = str(row.get("轴向夹角（°）", "0"))
            jieguan["接管实际外伸长度"] = str(row.get("外伸高度", "0"))

        # 程序推荐兜底
        if jieguan.get("接管实际外伸长度") == "程序推荐":
            jieguan["接管实际外伸长度"] = "0"

        cursor.execute("""
            SELECT 参数名称, 管程数值
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s AND 参数名称 IN ('工作温度（入口）', '工作温度（出口）')
        """, (product_id,))
        rows = cursor.fetchall()

        # 初始化入口/出口温度
        temp_in = None
        temp_out = None

        for row in rows:
            name = row.get("参数名称", "").strip()
            value = row.get("管程数值")
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

        # === 获取管口材料分类 ===
        cursor.execute("""
            SELECT 材料分类
            FROM 产品设计活动表_管口类别表
            WHERE 产品ID = %s AND 管口代号 = %s
            LIMIT 1
        """, (product_id, guankou_daihao))
        row = cursor.fetchone()

        if row and row.get("材料分类"):
            category = row["材料分类"].strip()
        else:
            category = ""  # 默认分类

        print(f"✅ 管口代号 {guankou_daihao} 使用材料分类: {category}")

        # === 根据材料分类，从附加参数表里取材料参数 ===
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
            r["参数名称"].strip(): str(r["参数值"]).strip()
            for r in material_rows if r.get("参数名称") and r.get("参数值") not in (None, "", "None")
        }

        # 更新到 jieguan
        for i in range(1, 3 + 1):
            jieguan[f"接管材料类型{i}"] = material_map.get(f"接管材料类型{i}", "")
            jieguan[f"接管材料牌号{i}"] = material_map.get(f"接管材料牌号{i}", "")
            jieguan[f"接管腐蚀余量{i}"] = material_map.get(f"接管腐蚀裕量{i}", "")
        # ===== 获取公称直径、绝热厚度、毒性/爆炸危险等 =====
        cursor.execute("""
                SELECT 参数名称, 壳程数值, 管程数值
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s
            """, (product_id,))
        rows = cursor.fetchall()
        param_map = {row["参数名称"].strip(): row for row in rows}

        # 公称直径（管程）
        if "公称直径*" in param_map:
            jieguan["设备公称直径"] = str(param_map["公称直径*"].get("管程数值", ""))
        # 参数映射：数据库参数名 → jieguan 字典键名

        # === 获取该管口的材料分类 ===
        cursor.execute("""
            SELECT 材料分类
            FROM 产品设计活动表_管口类别表
            WHERE 产品ID = %s AND 管口代号 = %s
        """, (product_id, guankou_daihao))
        material_class_rows = cursor.fetchall()
        material_classes = [r["材料分类"].strip() for r in material_class_rows if r.get("材料分类")]

        use_category_filter = bool(material_classes)
        category = material_classes[0] if use_category_filter else None
        print(f"✅ 材料分类（{guankou_daihao}）: {material_classes or '统一材料'}")

        # === 获取管口功能 ===
        cursor.execute("""
            SELECT 管口功能
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口代号 = %s
            LIMIT 1
        """, (product_id, guankou_daihao))
        row = cursor.fetchone()
        guankou_gongneng = row["管口功能"].strip() if row and row["管口功能"] else ""
        print(f"✅ 管口功能: {guankou_gongneng}")
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

        print(f"✅ 管口功能: {guankou_gongneng}")
        print(f"✅ 所属元件: {suoshuyuanjian}")

        if gongcheng_size is not None:
            jieguan["接管内/外径"] = str(gongcheng_size)

        # # === 根据所属元件，从设计数据表获取腐蚀裕量 ===
        # corrosion_value = None
        # if "管箱" in suoshuyuanjian:
        #     cursor.execute("""
        #         SELECT 管程数值
        #         FROM 产品设计活动表_设计数据表
        #         WHERE 产品ID = %s
        #         LIMIT 1
        #     """, (product_id,))
        #     row = cursor.fetchone()
        #     corrosion_value = row["管程数值"] if row and row["管程数值"] is not None else None
        #
        # elif "外头盖" in suoshuyuanjian or "壳体" in suoshuyuanjian:
        #     cursor.execute("""
        #         SELECT 壳程数值
        #         FROM 产品设计活动表_设计数据表
        #         WHERE 产品ID = %s
        #         LIMIT 1
        #     """, (product_id,))
        #     row = cursor.fetchone()
        #     corrosion_value = row["壳程数值"] if row and row["壳程数值"] is not None else None
        #
        # if corrosion_value is not None:
        #     jieguan["接管腐蚀裕量"] = str(corrosion_value)
        #
        # print(f"✅ 接管腐蚀裕量: {jieguan.get('接管腐蚀裕量')}")

        # === 获取材料分类 ===
        cursor.execute("""
                SELECT 材料分类 
                FROM 产品设计活动表_管口类别表 
                WHERE 产品ID = %s AND 管口代号 = %s
            """, (product_id, guankou_daihao))
        class_rows = cursor.fetchall()
        category = class_rows[0]["材料分类"].strip() if class_rows and class_rows[0].get("材料分类") else None
        use_category_filter = bool(category)
        print("category", category)
        # === 遍历接管/2/3 获取材料参数 ===
        material_map = {}  # 放循环外：存全部接管材料类型/牌号
        param_map_total = {}  # 放循环外：存所有参数（用于后续统一处理）
        # === 查询接管覆层参数（新的逻辑：来自 管口附加参数表）===
        cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_管口附加参数表
            WHERE 产品ID = %s 
              AND 参数名称 IN ('接管是否添加覆层','覆层材料类型','覆层成型工艺','覆层厚度')
        """, (product_id,))
        cover_rows = cursor.fetchall()

        cover_map = {
            r["参数名称"].strip(): str(r["参数值"]).strip()
            for r in cover_rows if r.get("参数名称") and r.get("参数值") not in (None, "", "None")
        }

        if cover_map.get("接管是否添加覆层") == "是":
            jieguan["是否覆层"] = "1"
            jieguan["覆层材料类型"] = cover_map.get("覆层材料类型", "未知")
            jieguan["覆层复合方式"] = cover_map.get("覆层成型工艺", "轧制复合")
            jieguan["接管覆层厚度"] = cover_map.get("覆层厚度", "0")
            has_cover = True
        else:
            jieguan["是否覆层"] = "0"
            jieguan["覆层材料类型"] = "钢板"
            jieguan["覆层复合方式"] = "无"
            jieguan["接管覆层厚度"] = "0"
            has_cover = False

        # === 查询补强圈材料信息（按顺序优先：1 → 2 → 3）===
        cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_管口附加参数表
            WHERE 产品ID = %s 
              AND 参数名称 IN (
                  '补强圈材料类型1','补强圈材料牌号1',
                  '补强圈材料类型2','补强圈材料牌号2',
                  '补强圈材料类型3','补强圈材料牌号3'
              )
        """, (product_id,))
        rows = cursor.fetchall()

        extra_map = {
            r["参数名称"].strip(): str(r["参数值"]).strip()
            for r in rows if r.get("参数名称") and r.get("参数值") not in (None, "", "None")
        }

        # 默认值
        jieguan["补强圈材料类型"] = "钢板"
        jieguan["补强圈材料牌号"] = "0"

        # 按顺序查找
        for i in range(1, 4):
            mat_type = extra_map.get(f"补强圈材料类型{i}", "").strip()
            mat_grade = extra_map.get(f"补强圈材料牌号{i}", "").strip()
            if mat_type or mat_grade:  # 有一个非空就用
                jieguan["补强圈材料类型"] = mat_type if mat_type else "0"
                jieguan["补强圈材料牌号"] = mat_grade if mat_grade else "0"
                break  # 找到就停

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
        "管箱封头": guangxiang_fengtou,
        "管箱圆筒": guanxiang_yuantong,
        "管箱法兰": guanxiang_falan,
        "管箱分程隔板": fencheng_geban,
        "壳体圆筒": qiaoti_yuantong,
        "壳体法兰": keti_falan,
        "固定管板": guanban_a,
        "浮头管束": tube_bundle,
        "外头盖封头": waitougai_fengtou,
        "鞍座": anzuo,
        "浮头法兰": futou_falan,
        "外头盖法兰": waitougai_falan,
        "外头盖圆筒": waitougai_yuantong,
        "外头盖侧法兰": waitougaice_falan,
    }
    # 合并
    dict_datas.update(jieguan_dict)

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
        result["ExchangerType"] = row.get("产品型式", "Unknown")
    else:
        result["ProjectName"] = "UnnamedProject"
        result["ExchangerType"] = "Unknown"
    # ✅ 类型判断并替换结构
    if result.get("ExchangerType") == "AES":
        result["DictDatas"].pop("管箱封头", None)
        result["DictDatas"]["管箱平盖"] = guangxiang_pinggai
        result["DictDatas"]["头盖法兰"] = tougai_falan
        if "DictPart" in result and "管箱封头" in result["DictPart"]:
            result["DictPart"].pop("管箱封头", None)
            result["DictPart"]["管箱平盖"] = "法兰"
        result["DictPart"]["头盖法兰"] = "法兰"
        # === 替换 DictDatas 中所有模块的 "换热器类型" 为 AEU ===
        for module_data in result.get("DictDatas", {}).values():
            print(module_data)
            if isinstance(module_data, dict):
                for key in module_data:
                    if key == "换热器型号":
                        module_data[key] = "AEU"

    def deep_map(obj):
        if isinstance(obj, dict):
            return {k: deep_map(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [deep_map(item) for item in obj]
        elif obj is None:
            return "0"
        elif isinstance(obj, str) and obj in material_type_map:
            return material_type_map[obj]
        else:
            return obj

    result = deep_map(result)
    # ✅ 删除 WSList 中所有字段都是 "0" 的项
    if "WSList" in result and isinstance(result["WSList"], list):
        result["WSList"] = [
            ws for ws in result["WSList"]
            if not all(str(ws.get(key, "0")) == "0" for key in [
                "ShellWorkingPressure", "TubeWorkingPressure",
                "ShellWorkingTemperature", "TubeWorkingTemperature"
            ])
        ]

    # def update_all_flange_types(obj):
    #     if isinstance(obj, dict):
    #         for key in obj:
    #             if isinstance(obj[key], dict):
    #                 update_all_flange_types(obj[key])
    #             elif isinstance(obj[key], list):
    #                 for item in obj[key]:
    #                     update_all_flange_types(item)
    #             elif isinstance(key, str) and (
    #                     key.startswith("法兰类型管前左") or key.startswith("法兰类型壳后右")
    #             ):
    #                 obj[key] = "整体法兰2"

    # update_all_flange_types(result)
    # 保存结果到JSON文件

    with open("shuru_jisuan.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)
        clr.AddReference("CalCulationInterF")  # 不加 .dll 后缀
    from CalCulationInterF import CalPartInterface
    # # 读取JSON文件并转换为紧凑格式
    with open("shuru_jisuan.json", "r", encoding="utf-8") as f:
        json_input = f.read()
    parsed = json.loads(json_input)
    compact_json = json.dumps(parsed, separators=(',', ':'))
    cpi = CalPartInterface()
    outputjsonstr = cpi.IntergratedDi(compact_json)
    return outputjsonstr
