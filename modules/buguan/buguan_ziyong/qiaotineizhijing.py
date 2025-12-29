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
    except Exception as e:
        print(f"❌ 查询失败: {e}")
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
            WHERE 产品ID = %s AND 元件名称 = '壳体封头'
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
        "公称直径": "",
        "指定内径":"0"
    }
    if isDi_change:
        print("传入用户输入的值")
        print(user_Di)
        guanxiang_yuantong["指定内径"] = user_Di
    print(guanxiang_yuantong["指定内径"])
    print("最终用户传入的值")
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
                       SELECT 管程数值, 壳程数值
                       FROM 产品设计活动表_设计数据表
                       WHERE 产品ID = %s AND 参数名称 = '公称直径*'
                   """, (product_id,))
            row = cursor.fetchone()
            raw_val = row["管程数值"].strip() if row and row.get("管程数值") else None
            raw_val2 = row["壳程数值"].strip() if row and row.get("壳程数值") else None
            cursor.execute("""
                SELECT 数值 FROM 产品设计活动表_通用数据表
                WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
            """, (product_id,))
            row = cursor.fetchone()
            waijing_bool = ""
            if row and "数值" in row:
                waijing_bool = "1" if row["数值"] == "是" else "0"
            if waijing_bool == "1":

                cursor.execute("""
                            SELECT 数值 FROM 产品设计活动表_通用数据表
                            WHERE 产品ID = %s AND 参数名称 = '外径'
                        """, (product_id,))
                row_waijing = cursor.fetchone()
                if row_waijing and "数值" in row:
                    guanxiang_yuantong["圆筒内/外径"] = row_waijing["数值"]
            else:
                guanxiang_yuantong["指定内径"] = raw_val2
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
    except Exception as e:
        print(f"❌ 查询失败: {e}")
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
    # if isDN_change:
    #     guanxiang_yuantong["圆筒内/外径"] = user_DN
    # else:
        # cursor.execute("""
        #             SELECT 管程数值 FROM 产品设计活动表_设计数据表
        #             WHERE 产品ID = %s AND 参数名称 = '公称直径*'
        #         """, (product_id,))
        # row = cursor.fetchone()
        # if row and "管程数值" in row:
        #     guanxiang_yuantong["圆筒内/外径"] = str(row["管程数值"])
        pass
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
        "公称直径": "",
        "指定内径":"0"
    }
    try:
        if isDi_change:
            print("传入用户输入的值")
            print(user_Di)
            qiaoti_yuantong["指定内径"] = user_Di
        print(qiaoti_yuantong["指定内径"])
        print("最终用户传入的值")
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()
        # 查询设计数据表，获取公称直径*
        if isDN_change:
            qiaoti_yuantong["公称直径"] = user_DN
            cursor.execute("""
                            SELECT 数值 FROM 产品设计活动表_通用数据表
                            WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
                        """, (product_id,))
            row = cursor.fetchone()
            waijing_bool = ""
            if row and "数值" in row:
                waijing_bool = "1" if row["数值"] == "是" else "0"
            print("waijing_bool", waijing_bool)
            if waijing_bool == "1":
                print("对对对")
                cursor.execute("""
                                        SELECT 数值 FROM 产品设计活动表_通用数据表
                                        WHERE 产品ID = %s AND 参数名称 = '外径'
                                    """, (product_id,))
                row_waijing = cursor.fetchone()
                if row_waijing and "数值" in row_waijing:
                    qiaoti_yuantong["圆筒内/外径"] = row_waijing["数值"]
                qiaoti_yuantong["指定内径"] = "0"
            else:
                qiaoti_yuantong["指定内径"] = user_DN
        else:
            cursor.execute("""
                       SELECT 管程数值, 壳程数值
                       FROM 产品设计活动表_设计数据表
                       WHERE 产品ID = %s AND 参数名称 = '公称直径*'
                   """, (product_id,))
            row = cursor.fetchone()
            raw_val = row["管程数值"].strip() if row and row.get("管程数值") else None
            qiaoti_yuantong["公称直径"] = raw_val

            raw_val2 = row["壳程数值"].strip() if row and row.get("壳程数值") else None
            cursor.execute("""
                SELECT 数值 FROM 产品设计活动表_通用数据表
                WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
            """, (product_id,))
            row = cursor.fetchone()
            waijing_bool = ""
            if row and "数值" in row:
                waijing_bool = "1" if row["数值"] == "是" else "0"
            print("waijing_bool",waijing_bool)
            if waijing_bool == "1":
                print("对对对")
                cursor.execute("""
                            SELECT 数值 FROM 产品设计活动表_通用数据表
                            WHERE 产品ID = %s AND 参数名称 = '外径'
                        """, (product_id,))
                row_waijing = cursor.fetchone()
                if row_waijing and "数值" in row_waijing:
                    qiaoti_yuantong["圆筒内/外径"] = row_waijing["数值"]
            else:
                qiaoti_yuantong["指定内径"] = raw_val2

        # === 查询换热管公称长度 LN ===
        cursor.execute("""
                SELECT 参数值
                FROM 产品设计活动表_布管参数表
                WHERE 产品ID = %s AND 参数名 = '换热管公称长度 LN'
                LIMIT 1
            """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["参数值"].strip() if row and row.get("参数值") else None



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
    except Exception as e:
        print(f"❌ 查询失败: {e}")
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
        print(data)  # 输出到控制台
        print("U型管输入json")

    clr.AddReference("CalCulationInterF")  # 不加 .dll 后缀
    from CalCulationInterF import CalPartInterface
    # # 读取JSON文件并转换为紧凑格式
    with open("qiaotineizhijing.json", "r", encoding="utf-8") as f:
        json_input = f.read()
    parsed = json.loads(json_input)
    compact_json = json.dumps(parsed, separators=(',', ':'))
    cpi = CalPartInterface()
    outputjsonstr = cpi.IntergratedDi(compact_json)
    print(outputjsonstr)
    print("U型管输出json")
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
    except Exception as e:
        print(f"❌ 查询失败: {e}")
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
    futou_falan = {'浮头法兰内径含覆层': '1500', '浮头法兰外径含覆层': '2080', '法兰名义厚度': '123', '球冠形封头名义厚度': '30',
                   'B型钩圈名义厚度': '50', 'B型钩圈颈部厚度': '50', '壳体圆筒名义内径': 0, '球冠形封头预设厚度1': 0,
                   '球冠形封头预设厚度2': 0, '球冠形封头预设厚度3': 0, '浮动管板名义厚度': '10', '浮动管板名义外径': '990',
                   '公称直径': 0, '壳程液柱密度': 0, '管程液柱密度': 0, '壳程液柱静压力': 0, '管程液柱静压力': 0,
                   '法兰材料类型': 0, '法兰材料牌号': 0, '管程法兰材料腐蚀裕量': 0, '壳程法兰材料腐蚀裕量': 0,
                   '浮头法兰管程覆层厚度': 0, '浮头法兰壳程覆层厚度': 0, '球冠形封头材料类型': 0,
                   '球冠形封头材料牌号': 0, '球冠形封头装入深度': 0, '球冠形封头焊接接头系数': 1,
                   '法兰密封面凸台高度': '6', '球冠形封头管程覆层厚度': 0, '球冠形封头壳程覆层厚度': 0,
                   '管程球冠形封头腐蚀裕量': 0, '壳程球冠形封头腐蚀裕量': 0, '压紧面形状序号': 0,
                   '法兰压紧面压紧宽度ω': 0, '垫片名义外径': 0, '垫片名义内径': 0, '球冠形封头覆层复合方式': '堆焊',
                   '球冠形封头带覆层时的焊接凹槽深度': 0, 'B型钩圈试验温度': '20', 'B型钩圈材料类型': 0,
                   'B型钩圈材料牌号': 0, 'B型钩圈覆层厚度': 0, '覆层位置': 0, '螺栓中心圆直径': '2013', '螺栓材料牌号': 0,
                   '螺栓公称直径': 'M20', '螺栓数量': '76', '螺栓根径': 0, '垫片材料牌号': 0, 'm': 0, 'y': '50', '垫片厚度': 0,
                   '分程隔板与垫片接触面面积': 0, '垫片实际密封宽度': 0, '垫片代号': '2.1', '隔条位置尺寸': 0,
                   '垫片标准号': 0, '分程隔板槽宽度': '2', '球冠形封头试验温度': '20', '球冠形封头管程压力试验类型': 0,
                   '球冠形封头壳程压力试验类型': 0}
    conn = pymysql.connect(
        host="localhost", user="root", password="123456",
        database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
    )
    cursor = conn.cursor()
    cursor.execute("""
                    SELECT 参数名称, 参数值
                    FROM 产品设计活动表_元件附加参数表
                    WHERE 产品ID = %s AND 元件名称 = '浮头垫片'
                """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    futou_falan["垫片材料牌号"] = row_map.get("垫片材料", "复合柔性石墨波齿金属板(不锈钢)")
    cursor.execute("""
                        SELECT 参数名称, 参数值
                        FROM 产品设计活动表_元件附加参数表
                        WHERE 产品ID = %s AND 元件名称 = '螺柱（浮头法兰）'
                    """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    futou_falan["螺栓材料牌号"] = row_map.get("材料牌号", "35CrMo")
    # === 查询设计数据表 ===
    cursor.execute("""
               SELECT 参数名称, 壳程数值, 管程数值
               FROM 产品设计活动表_设计数据表
               WHERE 产品ID = %s
           """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row for row in rows}
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
        futou_falan["介质类型"] = "/".join(media_parts)
    else:
        futou_falan["介质类型"] = "介质易爆/极度危害/高度危害"

    # # === 查询管程分程形式 ===
    # cursor.execute("""
    #                   SELECT 参数值
    #                   FROM 产品设计活动表_布管参数表
    #                   WHERE 产品ID = %s AND 参数名 = '管程分程形式'
    #                   LIMIT 1
    #               """, (product_id,))
    # row = cursor.fetchone()
    # tube_form = row["参数值"].strip() if row and row.get("参数值") else None
    # if tube_form == '2':
    #     tube_form = '2.1'
    # futou_falan["垫片代号"] = tube_form

    # === 查询数据库 ===
    cursor.execute("""
           SELECT 参数名称, 壳程数值, 管程数值
           FROM 产品设计活动表_设计数据表
           WHERE 产品ID = %s
       """, (product_id,))
    rows = cursor.fetchall()

    # === 构建参数映射表 ===
    param_map = {row["参数名称"].strip(): row for row in rows}
    if "耐压试验类型*" in param_map:
        val = param_map["耐压试验类型*"].get("管程数值", "")
        if val:
            futou_falan["球冠形封头管程压力试验类型"] = str(val).replace("试验", "").strip()
        val2 = param_map["耐压试验类型*"].get("壳程数值", "")
        if val2:
            futou_falan["球冠形封头壳程压力试验类型"] = str(val2).replace("试验", "").strip()

    cursor.execute("""
                   SELECT 参数名称, 参数值
                   FROM 产品设计活动表_元件附加参数表
                   WHERE 产品ID = %s AND 元件名称 = '浮动管板'
               """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    futou_falan["分程隔板槽宽度"] = row_map.get("分程隔板槽宽", "0")
    cursor.execute("""
                   SELECT 参数名称, 参数值
                   FROM 产品设计活动表_元件附加参数表
                   WHERE 产品ID = %s AND 元件名称 = '浮头垫片'
               """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    futou_falan["垫片标准号"] = row_map.get("垫片标准", "0")

    # === 查询隔条位置尺寸 ===
    cursor.execute("""
                       SELECT 参数值
                       FROM 产品设计活动表_布管参数表
                       WHERE 产品ID = %s AND 参数名 = '隔条位置尺寸 W'
                       LIMIT 1
                   """, (product_id,))
    row = cursor.fetchone()
    raw_val = row["参数值"].strip() if row and row.get("参数值") else None
    val11 = str(raw_val) if raw_val not in (None, "", " ", "None", "程序推荐") else "0"

    futou_falan["隔条位置尺寸"] = val11
    # 查询浮头垫片名义外径和内径
    cursor.execute("""
           SELECT 参数名称, 参数值
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s
             AND 元件名称 = '浮头垫片'
             AND 参数名称 IN ('垫片名义外径D2n','垫片名义内径D1n')
       """, (product_id,))

    rows = cursor.fetchall()
    if rows:
        params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}
        futou_falan["垫片名义外径"] = params.get("垫片名义外径D2n", "")
        if futou_falan["垫片名义外径"] in ("程序推荐", ""):
            futou_falan["垫片名义外径"] = "0"

        futou_falan["垫片名义内径"] = params.get("垫片名义内径D1n", "")
        if futou_falan["垫片名义内径"] in ("程序推荐", ""):
            futou_falan["垫片名义内径"] = "0"
    # 查询浮头垫片的压紧面形状
    cursor.execute("""
           SELECT 参数值
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s
             AND 元件名称 = '浮头垫片'
             AND 参数名称 = '压紧面形状'
       """, (product_id,))

    row = cursor.fetchone()
    if row:
        futou_falan["压紧面形状序号"] = safe_str(row.get("参数值"))

    # 查询球冠形封头相关参数
    cursor.execute("""
           SELECT 参数名称, 参数值
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s
             AND 元件名称 = '球冠形封头'
             AND 参数名称 IN (
                 '管程侧腐蚀裕量',
                 '壳程侧腐蚀裕量',
                 '管程侧覆层厚度',
                 '壳程侧覆层厚度',
                 '管程侧是否添加覆层',
                 '壳程侧是否添加覆层'
             )
       """, (product_id,))

    rows = cursor.fetchall()
    if rows:
        params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}

        # 腐蚀裕量
        futou_falan["管程球冠形封头腐蚀裕量"] = params.get("管程侧腐蚀裕量", "")
        futou_falan["壳程球冠形封头腐蚀裕量"] = params.get("壳程侧腐蚀裕量", "")

        # 覆层厚度判断
        if params.get("管程侧是否添加覆层") == "否":
            futou_falan["球冠形封头管程覆层厚度"] = "0"
        else:
            futou_falan["球冠形封头管程覆层厚度"] = params.get("管程侧覆层厚度", "")

        if params.get("壳程侧是否添加覆层") == "否":
            futou_falan["球冠形封头壳程覆层厚度"] = "0"
        else:
            futou_falan["球冠形封头壳程覆层厚度"] = params.get("壳程侧覆层厚度", "")
        # 查询球冠形封头相关参数
        cursor.execute("""
               SELECT 参数名称, 参数值
               FROM 产品设计活动表_元件附加参数表
               WHERE 产品ID = %s
                 AND 元件名称 = '钩圈'
                 AND 参数名称 IN (
                     '管程侧是否添加覆层',
                     '壳程侧是否添加覆层'
                 )
           """, (product_id,))

        rows = cursor.fetchall()
        if rows:
            params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}
        if params.get("管程侧是否添加覆层") == "否" and params.get("壳程侧是否添加覆层") == "否":
            futou_falan["覆层位置"] = "无"
        elif params.get("管程侧是否添加覆层") == "是" and params.get("壳程侧是否添加覆层") == "是":
            futou_falan["覆层位置"] = "双侧"
        else:
            futou_falan["覆层位置"] = "单侧"
    # 查询球冠形封头装入深度
    cursor.execute("""
           SELECT 参数值
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s
             AND 元件名称 = '球冠形封头'
             AND 参数名称 = '封头焊入法兰深度'
       """, (product_id,))

    row = cursor.fetchone()
    if row:
        shendu = safe_str(row.get("参数值"))
        if shendu == "程序推荐":
            shendu = "27"
        futou_falan["球冠形封头装入深度"] = shendu

    # 查询球冠形封头材料信息
    cursor.execute("""
           SELECT 参数名称, 参数值
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s
             AND 元件名称 = '球冠形封头'
             AND 参数名称 IN ('材料类型','材料牌号')
       """, (product_id,))

    rows = cursor.fetchall()
    if rows:
        params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}
        futou_falan["球冠形封头材料类型"] = params.get("材料类型", "")
        futou_falan["球冠形封头材料牌号"] = params.get("材料牌号", "")
        # 查询球冠形封头材料信息
    cursor.execute("""
              SELECT 参数名称, 参数值
              FROM 产品设计活动表_元件附加参数表
              WHERE 产品ID = %s
                AND 元件名称 = '钩圈'
                AND 参数名称 IN ('材料类型','材料牌号')
          """, (product_id,))

    rows = cursor.fetchall()
    if rows:
        params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}
        futou_falan["B型钩圈材料类型"] = params.get("材料类型", "")
        futou_falan["B型钩圈材料牌号"] = params.get("材料牌号", "")
    # 查询浮头法兰相关参数
    cursor.execute("""
           SELECT 参数名称, 参数值
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s
             AND 元件名称 = '浮头法兰'
             AND 参数名称 IN (
                 '管程侧腐蚀裕量',
                 '壳程侧腐蚀裕量',
                 '管程侧覆层厚度',
                 '壳程侧覆层厚度',
                 '管程侧是否添加覆层',
                 '壳程侧是否添加覆层'
             )
       """, (product_id,))

    rows = cursor.fetchall()
    if rows:
        params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}

        # 腐蚀裕量
        futou_falan["管程法兰材料腐蚀裕量"] = params.get("管程侧腐蚀裕量", "")
        futou_falan["壳程法兰材料腐蚀裕量"] = params.get("壳程侧腐蚀裕量", "")

        # 覆层厚度判断
        if params.get("管程侧是否添加覆层") == "否":
            futou_falan["浮头法兰管程覆层厚度"] = "0"
        else:
            futou_falan["浮头法兰管程覆层厚度"] = params.get("管程侧覆层厚度", "")

        if params.get("壳程侧是否添加覆层") == "否":
            futou_falan["浮头法兰壳程覆层厚度"] = "0"
        else:
            futou_falan["浮头法兰壳程覆层厚度"] = params.get("壳程侧覆层厚度", "")

    # 查询球冠形封头的预设厚度参数
    cursor.execute("""
           SELECT 参数名称, 参数值
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s 
             AND 元件名称 = '球冠形封头'
             AND 参数名称 IN ('预设厚度1','预设厚度2','预设厚度3')
       """, (product_id,))

    rows = cursor.fetchall()
    if rows:
        for row in rows:
            param_name = row.get("参数名称")
            param_value = safe_str(row.get("参数值"))
            if param_name == "预设厚度1":
                futou_falan["球冠形封头预设厚度1"] = param_value
            elif param_name == "预设厚度2":
                futou_falan["球冠形封头预设厚度2"] = param_value
            elif param_name == "预设厚度3":
                futou_falan["球冠形封头预设厚度3"] = param_value

    # 法兰名义内/外径
    cursor.execute("""
               SELECT 参数名称, 壳程数值, 管程数值
               FROM 产品设计活动表_设计数据表
               WHERE 产品ID = %s AND 参数名称 = '公称直径*'
           """, (product_id,))
    row = cursor.fetchone()
    if row:
        futou_falan["壳体圆筒名义内径"] = safe_str(row.get("壳程数值"))
    # === 获取管箱垫片的垫片厚度 ===
    cursor.execute("""
           SELECT 参数值
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s AND 元件名称 = '浮头垫片' AND 参数名称 = '垫片厚度'
       """, (product_id,))
    row = cursor.fetchone()
    val = row["参数值"] if row and row["参数值"] not in (None, "", "None") else "4.5"
    futou_falan["垫片厚度"] = str(val)

    yuanjian_param = {
        ("螺柱（浮头法兰）", "材料牌号"): "材料牌号",
        ("浮头垫片", "垫片材料"): "材料牌号",
        ("浮头垫片", "材料标准"): "材料标准",
        ("浮头垫片", "垫片比压力y"): "y",
        ("浮头垫片", "垫片系数m"): "m",
    }
    # 附加元件参数组件表
    cursor.execute("""
                   SELECT 元件名称, 参数名称, 参数值
                   FROM 产品设计活动表_元件附加参数表
                   WHERE 产品ID = %s
               """, (product_id,))
    rows = cursor.fetchall()
    component_map = {}
    for r in rows:
        # 安全地获取字段值，处理None的情况
        comp_raw = r.get("元件名称")
        param_raw = r.get("参数名称")
        
        # 如果元件名称或参数名称为None，跳过该行
        if comp_raw is None or param_raw is None:
            continue
            
        comp = comp_raw.strip()
        param = param_raw.strip()
        val = r["参数值"]
        
        if not comp or not param:
            continue  # 如果缺少关键字段，跳过此行
            
        component_map.setdefault(comp, {})[param] = val
    component_param_names = defaultdict(set)
    for (comp, param), field in yuanjian_param.items():
        val = component_map.get(comp, {}).get(param, "")
        val = str(val).strip() if val is not None else ""
        if val.lower() == "none":
            val = ""
        if field == "m":
            try:
                val = str(int(float(val)))
            except:
                val = "3"
        if field == "y":
            try:
                val = str(int(float(val)))
            except:
                val = "50"
    futou_falan[field] = apply_special_defaults(field, val)

    for component, param_names in component_param_names.items():
        cursor.execute("""
                   SELECT 参数名称, 参数值
                   FROM 产品设计活动表_元件附加参数表
                   WHERE 产品ID = %s AND 元件名称 = %s
               """, (product_id, component))
        rows = cursor.fetchall()
        name_val_map = {
            (row.get("参数名称") or "").strip(): safe_str(row.get("参数值"))
            for row in rows
            if row.get("参数名称") is not None
        }

        for pname in param_names:
            key = (component, pname)
            if key in yuanjian_param:
                futou_falan[yuanjian_param[key]] = name_val_map.get(pname, "0")
            else:
                print(f"⚠️ 警告：未找到映射 key = {key}")
    # 查询设计数据表，获取公称直径*
    cursor.execute("""
              SELECT 管程数值 FROM 产品设计活动表_设计数据表
              WHERE 产品ID = %s AND 参数名称 = '公称直径*'
          """, (product_id,))
    row = cursor.fetchone()
    if row and "管程数值" in row:
        futou_falan["公称直径"] = str(row["管程数值"])

        cursor.execute("""
               SELECT 参数名称, 壳程数值, 管程数值
               FROM 产品设计活动表_设计数据表
               WHERE 产品ID = %s
           """, (product_id,))
        rows = cursor.fetchall()
        param_map = {
            row["参数名称"]: {
                "壳程数值": row["壳程数值"],
                "管程数值": row["管程数值"]
            }
            for row in rows
        }

        # ========== 液柱静压力 和 介质密度 ==========
        if "液柱静压力" in param_map:
            futou_falan["壳程液柱静压力"] = safe_str(param_map["液柱静压力"].get("壳程数值"))
            futou_falan["管程液柱静压力"] = safe_str(param_map["液柱静压力"].get("管程数值"))
        if "介质密度" in param_map:
            futou_falan["壳程液柱密度"] = safe_str(param_map["介质密度"].get("壳程数值"))
            futou_falan["管程液柱密度"] = safe_str(param_map["介质密度"].get("管程数值"))
        # 法兰材料类型
        cursor.execute("""
                   SELECT 参数名称, 参数值
                   FROM 产品设计活动表_元件附加参数表
                   WHERE 产品ID = %s AND 元件名称 = '浮头法兰'
               """, (product_id,))
        rows = cursor.fetchall()
        falan_params = {r["参数名称"]: r["参数值"] for r in rows}
        for name in ["材料类型", "材料牌号"]:
            if name in falan_params:
                futou_falan[f"法兰{name}"] = safe_str(falan_params[name])
                # 法兰材料类型
        cursor.execute("""
                   SELECT 参数名称, 参数值
                   FROM 产品设计活动表_元件附加参数表
                   WHERE 产品ID = %s
                     AND 元件名称 = '钩圈'
                     AND 参数名称 IN (
                         '管程侧覆层厚度',
                         '壳程侧覆层厚度',
                         '管程侧是否添加覆层',
                         '壳程侧是否添加覆层'
                     )
               """, (product_id,))

        rows = cursor.fetchall()
        if rows:
            params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}

            # 覆层厚度判断
            if params.get("壳程侧是否添加覆层") == "否":
                futou_falan["B形钩圈覆层厚度"] = "0"
            else:
                futou_falan["B形钩圈覆层厚度"] = params.get("壳程侧覆层厚度", "")
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
        "指定内径":"0"
    }
    try:
        if isDi_change:
            print("传入用户输入的值")
            print(user_Di)
            waitougai_yuantong["指定内径"] = user_Di
        print(waitougai_yuantong["指定内径"])
        print("最终用户传入的值")
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()
        cursor.execute("""
                   SELECT 管程数值, 壳程数值
                   FROM 产品设计活动表_设计数据表
                   WHERE 产品ID = %s AND 参数名称 = '公称直径*'
               """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["管程数值"].strip() if row and row.get("管程数值") else None
        raw_val2 = row["壳程数值"].strip() if row and row.get("壳程数值") else None
        cursor.execute("""
            SELECT 数值 FROM 产品设计活动表_通用数据表
            WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
        """, (product_id,))
        row = cursor.fetchone()
        waijing_bool = ""
        if row and "数值" in row:
            waijing_bool = "1" if row["数值"] == "是" else "0"
        if waijing_bool == "1":
            cursor.execute("""
                        SELECT 数值 FROM 产品设计活动表_通用数据表
                        WHERE 产品ID = %s AND 参数名称 = '外径'
                    """, (product_id,))
            row_waijing = cursor.fetchone()
            if row_waijing and "数值" in row:
                waitougai_yuantong["圆筒内/外径"] = row_waijing["数值"]
        else:
            waitougai_yuantong["指定内径"] = raw_val2
        waitougai_yuantong["圆筒内/外径"] = raw_val2
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
        "公称直径": '',
        "指定内径":""
    }
    try:
        if isDi_change:
            print("传入用户输入的值")
            print(user_Di)
            guanxiang_yuantong["指定内径"] = user_Di
        print(guanxiang_yuantong["指定内径"])
        print("最终用户传入的值")
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()
        # === 查询换热管公称长度 LN ===
        cursor.execute("""
                   SELECT 管程数值, 壳程数值
                   FROM 产品设计活动表_设计数据表
                   WHERE 产品ID = %s AND 参数名称 = '公称直径*'
               """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["管程数值"].strip() if row and row.get("管程数值") else None
        guanxiang_yuantong["公称直径"] = raw_val

        raw_val2 = row["壳程数值"].strip() if row and row.get("壳程数值") else None
        cursor.execute("""
            SELECT 数值 FROM 产品设计活动表_通用数据表
            WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
        """, (product_id,))
        row = cursor.fetchone()
        waijing_bool = ""
        if row and "数值" in row:
            waijing_bool = "1" if row["数值"] == "是" else "0"
        if waijing_bool == "1":

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
        "公称直径": "",
        "指定内径":"0"
    }
    try:
        if isDi_change:
            print("传入用户输入的值")
            print(user_Di)
            qiaoti_yuantong["指定内径"] = user_Di
        print(qiaoti_yuantong["指定内径"])
        print("最终用户传入的值")
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()
        # 查询设计数据表，获取公称直径*
        if isDN_change:
            qiaoti_yuantong["公称直径"] = user_DN
            cursor.execute("""
                            SELECT 数值 FROM 产品设计活动表_通用数据表
                            WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
                        """, (product_id,))
            row = cursor.fetchone()
            waijing_bool = ""
            if row and "数值" in row:
                waijing_bool = "1" if row["数值"] == "是" else "0"
            print("waijing_bool", waijing_bool)
            if waijing_bool == "1":
                print("对对对")
                cursor.execute("""
                                        SELECT 数值 FROM 产品设计活动表_通用数据表
                                        WHERE 产品ID = %s AND 参数名称 = '外径'
                                    """, (product_id,))
                row_waijing = cursor.fetchone()
                if row_waijing and "数值" in row_waijing:
                    qiaoti_yuantong["圆筒内/外径"] = row_waijing["数值"]
                qiaoti_yuantong["指定内径"] = "0"
            else:
                qiaoti_yuantong["指定内径"] = user_DN
        else:
            cursor.execute("""
                       SELECT 管程数值, 壳程数值
                       FROM 产品设计活动表_设计数据表
                       WHERE 产品ID = %s AND 参数名称 = '公称直径*'
                   """, (product_id,))
            row = cursor.fetchone()
            raw_val = row["管程数值"].strip() if row and row.get("管程数值") else None
            qiaoti_yuantong["公称直径"] = raw_val

            raw_val2 = row["壳程数值"].strip() if row and row.get("壳程数值") else None
            cursor.execute("""
                SELECT 数值 FROM 产品设计活动表_通用数据表
                WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
            """, (product_id,))
            row = cursor.fetchone()
            waijing_bool = ""
            if row and "数值" in row:
                waijing_bool = "1" if row["数值"] == "是" else "0"
            print("waijing_bool",waijing_bool)
            if waijing_bool == "1":
                print("对对对")
                cursor.execute("""
                            SELECT 数值 FROM 产品设计活动表_通用数据表
                            WHERE 产品ID = %s AND 参数名称 = '外径'
                        """, (product_id,))
                row_waijing = cursor.fetchone()
                if row_waijing and "数值" in row_waijing:
                    qiaoti_yuantong["圆筒内/外径"] = row_waijing["数值"]
            else:
                qiaoti_yuantong["指定内径"] = raw_val2

        # === 查询换热管公称长度 LN ===
        cursor.execute("""
                SELECT 参数值
                FROM 产品设计活动表_布管参数表
                WHERE 产品ID = %s AND 参数名 = '换热管公称长度 LN'
                LIMIT 1
            """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["参数值"].strip() if row and row.get("参数值") else None



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
    except Exception as e:
        print(f"❌ 查询失败: {e}")
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
        qiaoti_yuantong["最大允许工作压力"] = str(value)

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

    with open("qiaotineizhijing.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)
    clr.AddReference("CalCulationInterF")  # 不加 .dll 后缀
    from CalCulationInterF import CalPartInterface
    # # 读取JSON文件并转换为紧凑格式
    with open("qiaotineizhijing.json", "r", encoding="utf-8") as f:
        json_input = f.read()
    with open("qiaotineizhijing.json", "r", encoding="utf-8") as f:
        data = json.load(f)  # 此时可以正常读取
        print(data)  # 输出到控制台
        print("浮头式输入json")
    parsed = json.loads(json_input)
    compact_json = json.dumps(parsed, separators=(',', ':'))
    cpi = CalPartInterface()
    outputjsonstr = cpi.IntergratedDi(compact_json)
    print(outputjsonstr)
    print("浮头式输出json")
    return outputjsonstr
def cal_qiaotineizhijing_NEN(product_id, isDi_change, isDN_change, user_Di, user_DN):
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
        raw_attach = clean_value(row.get("管口所属元件"))

        if raw_attach in ("前端管箱圆筒",):
            ttAttach = "管箱圆筒"
        elif raw_attach in ("前端管箱平盖", "后端管箱平盖"):
            ttAttach = "管箱平盖"
        else:
            ttAttach = raw_attach
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
            "ttAttach": ttAttach,
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
            "ttMemo": clean_value(row.get("法兰标准"))
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
        if tube_form == "2" or tube_form == None or tube_form == "":
            design_params["管/壳程布置型式"] = "2.1"
        # === 查询设计数据表 ===
        cursor.execute("""
                SELECT 参数名称, 壳程数值, 管程数值
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s
            """, (product_id,))
        rows = cursor.fetchall()
        param_map = {row["参数名称"].strip(): row for row in rows}

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
    except Exception as e:
        print(f"❌ 查询失败: {e}")
    dict_part = {
        "管箱平盖": "法兰",
        "头盖法兰": "法兰",
        "管箱圆筒": "筒体",
        "管箱分程隔板": "分程隔板",
        "壳体端部圆筒1": "筒体",
        "壳体圆筒": "筒体",
        "壳体端部圆筒2": "筒体",
        "固定管板": "b型管板",
        "管束": "固定管板管束",
        "后端管箱圆筒": "筒体",
        "吊耳": "吊耳",
        "鞍座": "鞍座",
        "后端管箱平盖": "法兰",
        "后端头盖法兰": "法兰"
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

    qiaoti_duanbuyuantong1 = {
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
                           SELECT 壳程数值
                           FROM 产品设计活动表_设计数据表
                           WHERE 产品ID = %s AND 参数名称 = '公称直径*'
                           LIMIT 1
                       """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["壳程数值"].strip() if row and row.get("壳程数值") else None
        qiaoti_duanbuyuantong1["公称直径"] = raw_val
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
        print(f"  查询失败: {e}")

    # === 处理参数值（空或无效则默认 6000） ===
    tube_length = raw_val if raw_val not in (None, "", " ", "None") else "6000"

    # 写入 qiaoti_yuantong
    qiaoti_duanbuyuantong1["换热管长度"] = tube_length
    cursor.execute("""
                   SELECT 参数名称, 参数值
                   FROM 产品设计活动表_元件附加参数表
                   WHERE 产品ID = %s AND 元件名称 = '端部圆筒'
               """, (product_id,))
    extra_rows = cursor.fetchall()
    extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}

    # 是否添加覆层
    if extra_map.get("是否添加覆层") == "是":
        qiaoti_duanbuyuantong1["是否覆层"] = "1"
        qiaoti_duanbuyuantong1["覆层材料类型"] = extra_map.get("覆层材料类型", "")
        qiaoti_duanbuyuantong1["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        qiaoti_duanbuyuantong1["圆筒覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
    else:
        qiaoti_duanbuyuantong1["覆层材料类型"] = "钢板"
        qiaoti_duanbuyuantong1["是否覆层"] = "0"
        qiaoti_duanbuyuantong1["覆层复合方式"] = "无"
        qiaoti_duanbuyuantong1["圆筒覆层厚度"] = "0"
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

    val1 = parse_float(param_map.get("自定义耐压试验压力（卧）", {}).get("壳程数值", ""))
    val2 = parse_float(param_map.get("自定义耐压试验压力（立）", {}).get("壳程数值", ""))

    # === 最大允许工作压力（壳程数值） ===
    value = param_map.get("最大允许工作压力", {}).get("壳程数值")
    if value not in [None, ""]:
        qiaoti_duanbuyuantong1["最大允许工作压力"] = str(value)

    # === 耐压试验压力：取最大值 ===
    if val1 is not None and val2 is not None:
        qiaoti_duanbuyuantong1["耐压试验压力"] = str(max(val1, val2))
    elif val1 is not None:
        qiaoti_duanbuyuantong1["耐压试验压力"] = str(val1)
    elif val2 is not None:
        qiaoti_duanbuyuantong1["耐压试验压力"] = str(val2)
    else:
        qiaoti_duanbuyuantong1["耐压试验压力"] = "0"

    # ===== 获取预设厚度1~3（来自元件附加参数表）=====
    cursor.execute("""
                SELECT 参数名称, 参数值 FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = '端部圆筒'
            """, (product_id,))
    rows = cursor.fetchall()
    extra_param_map = {r["参数名称"].strip(): r["参数值"] for r in rows}

    # 写入 guangxiang_fengtou 中的预设厚度
    for i in range(1, 4):
        key = f"预设厚度{i}"
        if key in extra_param_map:
            qiaoti_duanbuyuantong1[key] = str(extra_param_map[key])

    # 从数据库获取“是否以外径为基准*”的壳程数值
    cursor.execute("""
                SELECT 数值 FROM 产品设计活动表_通用数据表
                WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
            """, (product_id,))
    row = cursor.fetchone()
    if row and "数值" in row:
        qiaoti_duanbuyuantong1["是否按外径计算"] = "1" if row["数值"] == "是" else "0"


    map3 = {
        "液柱静压力": "液柱静压力",
        "用户自定义MAWP": "最高允许工作压力",
        "腐蚀裕量": "腐蚀裕量*",
        "焊接接头系数": "焊接接头系数*",

    }

    for key, param_name in map3.items():
        value = param_map.get(param_name, {}).get("壳程数值", "")
        if value != "":
            qiaoti_duanbuyuantong1[key] = str(value)

    cursor.execute("""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = '端部圆筒'
            """, (product_id,))
    rows = cursor.fetchall()
    extra_map = {r["参数名称"]: r["参数值"] for r in rows}

    if "材料类型" in extra_map:
        raw_type = extra_map["材料类型"]
        qiaoti_duanbuyuantong1["材料类型"] = material_type_map.get(raw_type, raw_type)
    if "材料牌号" in extra_map:
        qiaoti_duanbuyuantong1["材料牌号"] = extra_map["材料牌号"]
    # ===== 压力试验类型（仅去掉末尾“试验”）=====
    if "耐压试验类型*" in param_map:
        val = param_map["耐压试验类型*"].get("壳程数值", "")
        if val:
            qiaoti_duanbuyuantong1["压力试验类型"] = str(val).replace("试验", "").strip()

    qiaoti_duanbuyuantong2 = {
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
                           SELECT 壳程数值
                           FROM 产品设计活动表_设计数据表
                           WHERE 产品ID = %s AND 参数名称 = '公称直径*'
                           LIMIT 1
                       """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["壳程数值"].strip() if row and row.get("壳程数值") else None
        qiaoti_duanbuyuantong2["公称直径"] = raw_val
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
        print(f"  查询失败: {e}")

    # === 处理参数值（空或无效则默认 6000） ===
    tube_length = raw_val if raw_val not in (None, "", " ", "None") else "6000"

    # 写入 qiaoti_yuantong
    qiaoti_duanbuyuantong2["换热管长度"] = tube_length
    cursor.execute("""
                   SELECT 参数名称, 参数值
                   FROM 产品设计活动表_元件附加参数表
                   WHERE 产品ID = %s AND 元件名称 = '端部圆筒'
               """, (product_id,))
    extra_rows = cursor.fetchall()
    extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}

    # 是否添加覆层
    if extra_map.get("是否添加覆层") == "是":
        qiaoti_duanbuyuantong2["是否覆层"] = "1"
        qiaoti_duanbuyuantong2["覆层材料类型"] = extra_map.get("覆层材料类型", "")
        qiaoti_duanbuyuantong2["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        qiaoti_duanbuyuantong2["圆筒覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
    else:
        qiaoti_duanbuyuantong2["覆层材料类型"] = "钢板"
        qiaoti_duanbuyuantong2["是否覆层"] = "0"
        qiaoti_duanbuyuantong2["覆层复合方式"] = "无"
        qiaoti_duanbuyuantong2["圆筒覆层厚度"] = "0"
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

    val1 = parse_float(param_map.get("自定义耐压试验压力（卧）", {}).get("壳程数值", ""))
    val2 = parse_float(param_map.get("自定义耐压试验压力（立）", {}).get("壳程数值", ""))

    # === 最大允许工作压力（壳程数值） ===
    value = param_map.get("最大允许工作压力", {}).get("壳程数值")
    if value not in [None, ""]:
        qiaoti_duanbuyuantong2["最大允许工作压力"] = str(value)

    # === 耐压试验压力：取最大值 ===
    if val1 is not None and val2 is not None:
        qiaoti_duanbuyuantong2["耐压试验压力"] = str(max(val1, val2))
    elif val1 is not None:
        qiaoti_duanbuyuantong2["耐压试验压力"] = str(val1)
    elif val2 is not None:
        qiaoti_duanbuyuantong2["耐压试验压力"] = str(val2)
    else:
        qiaoti_duanbuyuantong2["耐压试验压力"] = "0"

    # ===== 获取预设厚度1~3（来自元件附加参数表）=====
    cursor.execute("""
                SELECT 参数名称, 参数值 FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = '端部圆筒'
            """, (product_id,))
    rows = cursor.fetchall()
    extra_param_map = {r["参数名称"].strip(): r["参数值"] for r in rows}

    # 写入 guangxiang_fengtou 中的预设厚度
    for i in range(1, 4):
        key = f"预设厚度{i}"
        if key in extra_param_map:
            qiaoti_duanbuyuantong2[key] = str(extra_param_map[key])

    # 从数据库获取“是否以外径为基准*”的壳程数值
    cursor.execute("""
                SELECT 数值 FROM 产品设计活动表_通用数据表
                WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
            """, (product_id,))
    row = cursor.fetchone()
    if row and "数值" in row:
        qiaoti_duanbuyuantong2["是否按外径计算"] = "1" if row["数值"] == "是" else "0"
    if isDi_change:
        qiaoti_duanbuyuantong2["圆筒内/外径"] = user_Di

        # 查询设计数据表，获取公称直径*
    cursor.execute("""
                   SELECT 参数值 FROM 产品设计活动表_布管参数表
                   WHERE 产品ID = %s AND 参数名 = '壳体内直径 Di'
               """, (product_id,))
    row = cursor.fetchone()
    if row and "参数值" in row:
        qiaoti_duanbuyuantong2["圆筒内/外径"] = str(row["参数值"])

    map3 = {
        "液柱静压力": "液柱静压力",
        "用户自定义MAWP": "最高允许工作压力",
        "腐蚀裕量": "腐蚀裕量*",
        "焊接接头系数": "焊接接头系数*",

    }

    for key, param_name in map3.items():
        value = param_map.get(param_name, {}).get("壳程数值", "")
        if value != "":
            qiaoti_duanbuyuantong2[key] = str(value)

    cursor.execute("""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = '端部圆筒'
            """, (product_id,))
    rows = cursor.fetchall()
    extra_map = {r["参数名称"]: r["参数值"] for r in rows}

    if "材料类型" in extra_map:
        raw_type = extra_map["材料类型"]
        qiaoti_duanbuyuantong2["材料类型"] = material_type_map.get(raw_type, raw_type)
    if "材料牌号" in extra_map:
        qiaoti_duanbuyuantong2["材料牌号"] = extra_map["材料牌号"]
    # ===== 压力试验类型（仅去掉末尾“试验”）=====
    if "耐压试验类型*" in param_map:
        val = param_map["耐压试验类型*"].get("壳程数值", "")
        if val:
            qiaoti_duanbuyuantong2["压力试验类型"] = str(val).replace("试验", "").strip()

    guanxiang_houduanyuantong = {
        "预设厚度1": "8",
        "预设厚度2": "10",
        "预设厚度3": "12",
        "圆筒使用位置": "后端管箱圆筒",
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
        guanxiang_houduanyuantong["公称直径"] = raw_val
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
        print(f"  查询失败: {e}")

    # === 处理参数值（空或无效则默认 6000） ===
    tube_length = raw_val if raw_val not in (None, "", " ", "None") else "6000"

    # 写入 qiaoti_yuantong
    guanxiang_houduanyuantong["换热管长度"] = tube_length
    cursor.execute("""
                   SELECT 参数名称, 参数值
                   FROM 产品设计活动表_元件附加参数表
                   WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
               """, (product_id,))
    extra_rows = cursor.fetchall()
    extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}

    # 是否添加覆层
    if extra_map.get("是否添加覆层") == "是":
        guanxiang_houduanyuantong["是否覆层"] = "1"
        guanxiang_houduanyuantong["覆层材料类型"] = extra_map.get("覆层材料类型", "")
        guanxiang_houduanyuantong["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        guanxiang_houduanyuantong["圆筒覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
    else:
        guanxiang_houduanyuantong["覆层材料类型"] = "钢板"
        guanxiang_houduanyuantong["是否覆层"] = "0"
        guanxiang_houduanyuantong["覆层复合方式"] = "无"
        guanxiang_houduanyuantong["圆筒覆层厚度"] = "0"
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
        guanxiang_houduanyuantong["最大允许工作压力"] = str(value)

    # === 耐压试验压力：取最大值 ===
    if val1 is not None and val2 is not None:
        guanxiang_houduanyuantong["耐压试验压力"] = str(max(val1, val2))
    elif val1 is not None:
        guanxiang_houduanyuantong["耐压试验压力"] = str(val1)
    elif val2 is not None:
        guanxiang_houduanyuantong["耐压试验压力"] = str(val2)
    else:
        guanxiang_houduanyuantong["耐压试验压力"] = "0"

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
            guanxiang_houduanyuantong[key] = str(extra_param_map[key])

    # 从数据库获取“是否以外径为基准*”的管程数值
    cursor.execute("""
                SELECT 数值 FROM 产品设计活动表_通用数据表
                WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
            """, (product_id,))
    row = cursor.fetchone()
    if row and "数值" in row:
        guanxiang_houduanyuantong["是否按外径计算"] = "1" if row["数值"] == "是" else "0"
    if isDi_change:
        guanxiang_houduanyuantong["圆筒内/外径"] = user_Di

        # 查询设计数据表，获取公称直径*
    cursor.execute("""
                   SELECT 参数值 FROM 产品设计活动表_布管参数表
                   WHERE 产品ID = %s AND 参数名 = '壳体内直径 Di'
               """, (product_id,))
    row = cursor.fetchone()
    if row and "参数值" in row:
        guanxiang_houduanyuantong["圆筒内/外径"] = str(row["参数值"])

    map3 = {
        "液柱静压力": "液柱静压力",
        "用户自定义MAWP": "最高允许工作压力",
        "腐蚀裕量": "腐蚀裕量*",
        "焊接接头系数": "焊接接头系数*",

    }

    for key, param_name in map3.items():
        value = param_map.get(param_name, {}).get("管程数值", "")
        if value != "":
            guanxiang_houduanyuantong[key] = str(value)

    cursor.execute("""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
            """, (product_id,))
    rows = cursor.fetchall()
    extra_map = {r["参数名称"]: r["参数值"] for r in rows}

    if "材料类型" in extra_map:
        raw_type = extra_map["材料类型"]
        guanxiang_houduanyuantong["材料类型"] = material_type_map.get(raw_type, raw_type)
    if "材料牌号" in extra_map:
        guanxiang_houduanyuantong["材料牌号"] = extra_map["材料牌号"]
    # ===== 压力试验类型（仅去掉末尾“试验”）=====
    if "耐压试验类型*" in param_map:
        val = param_map["耐压试验类型*"].get("管程数值", "")
        if val:
            guanxiang_houduanyuantong["压力试验类型"] = str(val).replace("试验", "").strip()
    diaoer = {
        "与吊耳连接元件": "管箱圆筒",
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

    tougai_falan = {
        "换热器型号": "AEU",
        "壳程液柱密度": "1",
        "管程液柱密度": "1",
        "壳程液柱静压力": "0",
        "管程液柱静压力": "0",
        "压紧面形状序号": "1a",
        "法兰是否考虑腐蚀裕量": "是",
        "法兰压紧面压紧宽度ω": "0",
        "轴向外力": "0",
        "外力矩": "0",
        "法兰类型": "整体法兰2",
        "法兰材料类型": "",
        "法兰材料牌号": "",
        "法兰材料腐蚀裕量": "3",
        "法兰颈部大端有效厚度": "26",
        "法兰颈部小端有效厚度": "16",
        "法兰名义内径": "0",
        "法兰名义外径": "0",
        "法兰名义厚度": "65",
        "法兰颈部高度": "35",
        "覆层厚度": "0",
        "管程还是壳程": "管程",
        "法兰为夹持法兰": "是",
        "法兰位置": "壳体法兰",
        "圆筒名义厚度": "10",
        "圆筒有效厚度": "8",
        "圆筒名义内径": "800",
        "圆筒名义外径": "1020",
        "圆筒材料类型": "板材",
        "圆筒材料牌号": "Q345R",
        "焊缝高度": "0",
        "焊缝长度": "0",
        "焊缝深度": "0",
        "法兰种类": "整体法兰2",
        "公称直径管前左": "1000",
        "公称直径壳后右": "1200",
        "对接元件管前左材料类型": "板材",
        "对接元件壳后右材料类型": "板材",
        "对接元件管前左材料牌号": "Q345R",
        "对接元件壳后右材料牌号": "Q345R",
        "是否带分程隔板管前左": "是",
        "是否带分程隔板壳后右": "是",
        "法兰类型管前左": "整体法兰2",
        "法兰材料类型管前左": "",
        "法兰材料牌号管前左": "",
        "法兰材料腐蚀裕量管前左": "3",
        "法兰类型壳后右": "整体法兰2",
        "法兰材料类型壳后右": "",
        "法兰材料牌号壳后右": "",
        "法兰材料腐蚀裕量壳后右": "3",
        "覆层厚度管前左": "0",
        "覆层厚度壳后右": "0",
        "对接元件覆层厚度管前左": "1.5",
        "对接元件覆层厚度壳后右": "1.6",
        "平盖序号": "9",
        "平盖直径": "1000",
        "纵向焊接接头系数": "1",
        "是否为圆形平盖": "是",
        "平盖材料类型": "钢锻件",
        "平盖材料牌号": "16Mn",
        "平盖分程隔板槽深度": "6",
        "平盖材料腐蚀裕量": "0.1",
        "平盖名义厚度": "96",
        "垫片名义外径": "0",
        "垫片名义内径": "0",
        "螺栓中心圆直径": "1200",
        "螺栓材料牌号": "35CrMo",
        "螺栓公称直径": "M16",
        "螺栓数量": "60",
        "螺栓根径": "0",
        # "垫片序号": "1",
        "垫片材料牌号": "复合柔性石墨波齿金属板(不锈钢)",
        "m": "3",
        "y": "50",
        "垫片厚度": "3",
        "垫片有效外径": "0",
        "垫片有效内径": "0",
        "分程隔板与垫片接触面面积": "0",
        "垫片代号": "2.1",
        "隔条位置尺寸": "0",
        # "介质情况": "毒性",
        "垫片标准号": "GB/T 29463-2023",
        "垫片实际密封宽度": "0",
        "分程隔板槽宽度": "2",
        "介质类型": "",
        "管程程数": "",
        "管板形式": ""
    }

    houduan_tougaifalan = {
        "换热器型号": "AEU",
        "壳程液柱密度": "1",
        "管程液柱密度": "1",
        "壳程液柱静压力": "0",
        "管程液柱静压力": "0",
        "压紧面形状序号": "1a",
        "法兰是否考虑腐蚀裕量": "是",
        "法兰压紧面压紧宽度ω": "0",
        "轴向外力": "0",
        "外力矩": "0",
        "法兰类型": "整体法兰2",
        "法兰材料类型": "",
        "法兰材料牌号": "",
        "法兰材料腐蚀裕量": "3",
        "法兰颈部大端有效厚度": "26",
        "法兰颈部小端有效厚度": "16",
        "法兰名义内径": "0",
        "法兰名义外径": "0",
        "法兰名义厚度": "65",
        "法兰颈部高度": "35",
        "覆层厚度": "0",
        "管程还是壳程": "管程",
        "法兰为夹持法兰": "是",
        "法兰位置": "壳体法兰",
        "圆筒名义厚度": "10",
        "圆筒有效厚度": "8",
        "圆筒名义内径": "800",
        "圆筒名义外径": "1020",
        "圆筒材料类型": "板材",
        "圆筒材料牌号": "Q345R",
        "焊缝高度": "0",
        "焊缝长度": "0",
        "焊缝深度": "0",
        "法兰种类": "整体法兰2",
        "公称直径管前左": "1000",
        "公称直径壳后右": "1200",
        "对接元件管前左材料类型": "板材",
        "对接元件壳后右材料类型": "板材",
        "对接元件管前左材料牌号": "Q345R",
        "对接元件壳后右材料牌号": "Q345R",
        "是否带分程隔板管前左": "是",
        "是否带分程隔板壳后右": "是",
        "法兰类型管前左": "整体法兰2",
        "法兰材料类型管前左": "",
        "法兰材料牌号管前左": "",
        "法兰材料腐蚀裕量管前左": "3",
        "法兰类型壳后右": "整体法兰2",
        "法兰材料类型壳后右": "",
        "法兰材料牌号壳后右": "",
        "法兰材料腐蚀裕量壳后右": "3",
        "覆层厚度管前左": "0",
        "覆层厚度壳后右": "0",
        "对接元件覆层厚度管前左": "1.5",
        "对接元件覆层厚度壳后右": "1.6",
        "平盖序号": "9",
        "平盖直径": "1000",
        "纵向焊接接头系数": "1",
        "是否为圆形平盖": "是",
        "平盖材料类型": "钢锻件",
        "平盖材料牌号": "16Mn",
        "平盖分程隔板槽深度": "6",
        "平盖材料腐蚀裕量": "0.1",
        "平盖名义厚度": "96",
        "垫片名义外径": "0",
        "垫片名义内径": "0",
        "螺栓中心圆直径": "1200",
        "螺栓材料牌号": "35CrMo",
        "螺栓公称直径": "M16",
        "螺栓数量": "60",
        "螺栓根径": "0",
        # "垫片序号": "1",
        "垫片材料牌号": "复合柔性石墨波齿金属板(不锈钢)",
        "m": "3",
        "y": "50",
        "垫片厚度": "3",
        "垫片有效外径": "0",
        "垫片有效内径": "0",
        "分程隔板与垫片接触面面积": "0",
        "垫片代号": "2.1",
        "隔条位置尺寸": "0",
        # "介质情况": "毒性",
        "垫片标准号": "GB/T 29463-2023",
        "垫片实际密封宽度": "0",
        "分程隔板槽宽度": "2",
        "介质类型": "",
        "管程程数": "",
        "管板形式": ""
    }

    houduan_guanxiangpinggai = {
        "分程隔板槽宽度": "2",

        "换热器型号": "BEU",
        "壳程液柱密度": "1",
        "管程液柱密度": "1",
        "壳程液柱静压力": "0",
        "管程液柱静压力": "0",
        "压紧面形状序号": "1a",
        "法兰是否考虑腐蚀裕量": "是",
        "法兰压紧面压紧宽度ω": "0",
        "轴向外力": "0",
        "外力矩": "0",
        "法兰类型": "松式法兰4",
        "法兰材料类型": "",
        "法兰材料牌号": "",
        "法兰材料腐蚀裕量": "3",
        "法兰颈部大端有效厚度": "26",
        "法兰颈部小端有效厚度": "16",
        "法兰名义内径": "0",
        "法兰名义外径": "0",
        "法兰名义厚度": "65",
        "法兰颈部高度": "35",
        "覆层厚度": "0",
        "管程还是壳程": "管程",
        "法兰为夹持法兰": "是",
        "法兰位置": "管箱法兰",
        "圆筒名义厚度": "10",
        "圆筒有效厚度": "8",
        "圆筒名义内径": "0",
        "圆筒名义外径": "0",
        "圆筒材料类型": "",
        "圆筒材料牌号": "",
        "焊缝高度": "0",
        "焊缝长度": "10",
        "焊缝深度": "0",
        "法兰种类": "整体法兰2",
        # "介质情况": "毒性",
        "公称直径管前左": "",
        "公称直径壳后右": "",
        "对接元件管前左材料类型": "无",
        "对接元件壳后右材料类型": "",
        "对接元件管前左材料牌号": "无",
        "对接元件壳后右材料牌号": "",
        "是否带分程隔板管前左": "是",
        "是否带分程隔板壳后右": "是",
        "法兰类型管前左": "整体法兰2",
        "法兰材料类型管前左": "",
        "法兰材料牌号管前左": "16Mn",
        "法兰材料腐蚀裕量管前左": 0,
        "法兰类型壳后右": "整体法兰2",
        "法兰材料类型壳后右": "整体法兰2",
        "法兰材料牌号壳后右": "16Mn",
        "法兰材料腐蚀裕量壳后右": "3",
        "覆层厚度管前左": "0",
        "覆层厚度壳后右": "0",
        "对接元件覆层厚度管前左": 0,
        "对接元件覆层厚度壳后右": "1.6",
        "垫片名义外径": "0",
        "垫片名义内径": "0",
        "平盖序号": "9",
        "纵向焊接接头系数": "1",
        "平盖直径": "1000",
        "是否为圆形平盖": "是",
        "平盖材料类型": "钢锻件",
        "平盖材料牌号": "16Mn",
        "平盖分程隔板槽深度": "6",
        "平盖材料腐蚀裕量": "0.1",
        "平盖名义厚度": "96",
        "螺栓中心圆直径": "1200",
        "螺栓材料牌号": "35CrMo",
        "螺栓公称直径": "M16",
        "螺栓数量": "60",
        "螺栓根径": "0",
        # "垫片序号": "1",
        "垫片材料牌号": "复合柔性石墨波齿金属板(不锈钢)",
        "m": "3",
        "y": "50",
        "垫片厚度": "3",
        "垫片有效外径": "0",
        "垫片有效内径": "0",
        "分程隔板与垫片接触面面积": "0",
        "垫片代号": "2.1",
        "隔条位置尺寸": "0",
        "垫片标准号": "GB/T 29463-2023",
        "垫片实际密封宽度": "0",
        "介质类型": "",
        "管程程数": "",
        "管板形式": ""
    }

    guangxiang_pinggai = {
        "分程隔板槽宽度": "2",

        "换热器型号": "BEU",
        "壳程液柱密度": "1",
        "管程液柱密度": "1",
        "壳程液柱静压力": "0",
        "管程液柱静压力": "0",
        "压紧面形状序号": "1a",
        "法兰是否考虑腐蚀裕量": "是",
        "法兰压紧面压紧宽度ω": "0",
        "轴向外力": "0",
        "外力矩": "0",
        "法兰类型": "松式法兰4",
        "法兰材料类型": "",
        "法兰材料牌号": "",
        "法兰材料腐蚀裕量": "3",
        "法兰颈部大端有效厚度": "26",
        "法兰颈部小端有效厚度": "16",
        "法兰名义内径": "0",
        "法兰名义外径": "0",
        "法兰名义厚度": "65",
        "法兰颈部高度": "35",
        "覆层厚度": "0",
        "管程还是壳程": "管程",
        "法兰为夹持法兰": "是",
        "法兰位置": "管箱法兰",
        "圆筒名义厚度": "10",
        "圆筒有效厚度": "8",
        "圆筒名义内径": "0",
        "圆筒名义外径": "0",
        "圆筒材料类型": "",
        "圆筒材料牌号": "",
        "焊缝高度": "0",
        "焊缝长度": "10",
        "焊缝深度": "0",
        "法兰种类": "整体法兰2",
        # "介质情况": "毒性",
        "公称直径管前左": "",
        "公称直径壳后右": "",
        "对接元件管前左材料类型": "无",
        "对接元件壳后右材料类型": "",
        "对接元件管前左材料牌号": "无",
        "对接元件壳后右材料牌号": "",
        "是否带分程隔板管前左": "是",
        "是否带分程隔板壳后右": "是",
        "法兰类型管前左": "整体法兰2",
        "法兰材料类型管前左": "",
        "法兰材料牌号管前左": "16Mn",
        "法兰材料腐蚀裕量管前左": 0,
        "法兰类型壳后右": "整体法兰2",
        "法兰材料类型壳后右": "整体法兰2",
        "法兰材料牌号壳后右": "16Mn",
        "法兰材料腐蚀裕量壳后右": "3",
        "覆层厚度管前左": "0",
        "覆层厚度壳后右": "0",
        "对接元件覆层厚度管前左": 0,
        "对接元件覆层厚度壳后右": "1.6",
        "垫片名义外径": "0",
        "垫片名义内径": "0",
        "平盖序号": "9",
        "纵向焊接接头系数": "1",
        "平盖直径": "1000",
        "是否为圆形平盖": "是",
        "平盖材料类型": "钢锻件",
        "平盖材料牌号": "16Mn",
        "平盖分程隔板槽深度": "6",
        "平盖材料腐蚀裕量": "0.1",
        "平盖名义厚度": "96",
        "螺栓中心圆直径": "1200",
        "螺栓材料牌号": "35CrMo",
        "螺栓公称直径": "M16",
        "螺栓数量": "60",
        "螺栓根径": "0",
        # "垫片序号": "1",
        "垫片材料牌号": "复合柔性石墨波齿金属板(不锈钢)",
        "m": "3",
        "y": "50",
        "垫片厚度": "3",
        "垫片有效外径": "0",
        "垫片有效内径": "0",
        "分程隔板与垫片接触面面积": "0",
        "垫片代号": "2.1",
        "隔条位置尺寸": "0",
        "垫片标准号": "GB/T 29463-2023",
        "垫片实际密封宽度": "0",
        "介质类型": "",
        "管程程数": "",
        "管板形式": ""
    }


    # 初始化字典

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
        "公称直径": '',
        "指定内径":"0"
    }
    if isDi_change:
        print("传入用户输入的值")
        print(user_Di)
        guanxiang_yuantong["指定内径"] = user_Di
    print(guanxiang_yuantong["指定内径"])
    print("最终用户传入的值")
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
                       SELECT 管程数值, 壳程数值
                       FROM 产品设计活动表_设计数据表
                       WHERE 产品ID = %s AND 参数名称 = '公称直径*'
                   """, (product_id,))
            row = cursor.fetchone()
            raw_val = row["管程数值"].strip() if row and row.get("管程数值") else None
            guanxiang_yuantong["公称直径"] = raw_val

            raw_val2 = row["壳程数值"].strip() if row and row.get("壳程数值") else None
            cursor.execute("""
                SELECT 数值 FROM 产品设计活动表_通用数据表
                WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
            """, (product_id,))
            row = cursor.fetchone()
            waijing_bool = ""
            if row and "数值" in row:
                waijing_bool = "1" if row["数值"] == "是" else "0"
            if waijing_bool == "1":

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
    except Exception as e:
        print(f"❌ 查询失败: {e}")
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
        "公称直径": "",
        "指定内径":"0"
    }
    try:
        if isDi_change:
            print("传入用户输入的值")
            print(user_Di)
            qiaoti_yuantong["指定内径"] = user_Di
        print(qiaoti_yuantong["指定内径"])
        print("最终用户传入的值")
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()
        # 查询设计数据表，获取公称直径*
        if isDN_change:
            qiaoti_yuantong["公称直径"] = user_DN
            cursor.execute("""
                            SELECT 数值 FROM 产品设计活动表_通用数据表
                            WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
                        """, (product_id,))
            row = cursor.fetchone()
            waijing_bool = ""
            if row and "数值" in row:
                waijing_bool = "1" if row["数值"] == "是" else "0"
            print("waijing_bool", waijing_bool)
            if waijing_bool == "1":
                print("对对对")
                cursor.execute("""
                                        SELECT 数值 FROM 产品设计活动表_通用数据表
                                        WHERE 产品ID = %s AND 参数名称 = '外径'
                                    """, (product_id,))
                row_waijing = cursor.fetchone()
                if row_waijing and "数值" in row_waijing:
                    qiaoti_yuantong["圆筒内/外径"] = row_waijing["数值"]
                qiaoti_yuantong["指定内径"] = "0"
            else:
                qiaoti_yuantong["指定内径"] = user_DN
        else:
            cursor.execute("""
                       SELECT 管程数值, 壳程数值
                       FROM 产品设计活动表_设计数据表
                       WHERE 产品ID = %s AND 参数名称 = '公称直径*'
                   """, (product_id,))
            row = cursor.fetchone()
            raw_val = row["管程数值"].strip() if row and row.get("管程数值") else None
            qiaoti_yuantong["公称直径"] = raw_val

            raw_val2 = row["壳程数值"].strip() if row and row.get("壳程数值") else None
            cursor.execute("""
                SELECT 数值 FROM 产品设计活动表_通用数据表
                WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
            """, (product_id,))
            row = cursor.fetchone()
            waijing_bool = ""
            if row and "数值" in row:
                waijing_bool = "1" if row["数值"] == "是" else "0"
            print("waijing_bool",waijing_bool)
            if waijing_bool == "1":
                print("对对对")
                cursor.execute("""
                            SELECT 数值 FROM 产品设计活动表_通用数据表
                            WHERE 产品ID = %s AND 参数名称 = '外径'
                        """, (product_id,))
                row_waijing = cursor.fetchone()
                if row_waijing and "数值" in row_waijing:
                    qiaoti_yuantong["圆筒内/外径"] = row_waijing["数值"]
            else:
                qiaoti_yuantong["指定内径"] = raw_val2

        # === 查询换热管公称长度 LN ===
        cursor.execute("""
                SELECT 参数值
                FROM 产品设计活动表_布管参数表
                WHERE 产品ID = %s AND 参数名 = '换热管公称长度 LN'
                LIMIT 1
            """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["参数值"].strip() if row and row.get("参数值") else None



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
    except Exception as e:
        print(f"❌ 查询失败: {e}")
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
        qiaoti_yuantong["最大允许工作压力"] = str(value)

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
    fencheng_geban = {
        "材料类型": "钢板",
        "材料牌号": "Q345R",
        "公称直径": "1000",
        "管箱分程隔板名义厚度": "0",
        "管箱分程隔板两侧压力差值": "0.05",
        "管箱分程隔板结构尺寸长边a": "596",
        "管箱分程隔板结构尺寸长边b": "785",
        "管箱分程隔板结构型式": "三边固定一边简支",
        "耐压试验温度": "15",
        "腐蚀裕量(双面)": "4",
        "管箱分程隔板设计余量": "0",
        "隔条位置尺寸": "10",
        "分程隔板槽宽度": "0",
    }
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
        fencheng_geban["公称直径"] = str(param_map["公称直径*"].get("管程数值", ""))
    # === 获取固定管板的分程隔板槽宽度 ===
    cursor.execute("""
            SELECT 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '分程隔板槽宽'
        """, (product_id,))
    row = cursor.fetchone()
    val = row["参数值"] if row and row["参数值"] not in (None, "", "None") else "0"
    fencheng_geban["分程隔板槽宽度"] = str(val)

    # === 获取进出口压力差 ===
    cursor.execute("""
                SELECT 管程数值
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s AND 参数名称 = '进、出口压力差*'
                LIMIT 1
            """, (product_id,))
    row = cursor.fetchone()
    if row and row["管程数值"] is not None:
        try:
            val = float(row["管程数值"])
            fencheng_geban["管箱分程隔板两侧压力差值"] = str(val)
        except ValueError:
            fencheng_geban["管箱分程隔板两侧压力差值"] = "0"
    else:
        fencheng_geban["管箱分程隔板两侧压力差值"] = "0"
    # === 获取腐蚀裕量(双面) ===
    cursor.execute("""
            SELECT 管程数值
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s AND 参数名称 = '腐蚀裕量*'
            LIMIT 1
        """, (product_id,))
    row = cursor.fetchone()

    if row and row["管程数值"] is not None:
        try:
            val = float(row["管程数值"])
            fencheng_geban["腐蚀裕量(双面)"] = str(val * 2)
        except ValueError:
            fencheng_geban["腐蚀裕量(双面)"] = "0"
    else:
        fencheng_geban["腐蚀裕量(双面)"] = "0"

    print("  腐蚀裕量(双面) =", fencheng_geban["腐蚀裕量(双面)"])

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  # 不使用 with，游标不会自动关闭

        # === 查询隔条位置尺寸 ===
        cursor.execute("""
                SELECT 参数值
                FROM 产品设计活动表_布管参数表
                WHERE 产品ID = %s AND 参数名 = '隔条位置尺寸 W'
                LIMIT 1
            """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["参数值"].strip() if row and row.get("参数值") else None

    except Exception as e:
        print(f"  查询失败: {e}")

    # === 处理参数值（空或无效默认 10） ===
    try:
        val11 = str(float(raw_val)) if raw_val not in (None, "", " ", "None", "程序推荐") else "0"
    except ValueError:
        val11 = "10"

    fencheng_geban["隔条位置尺寸"] = val11
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '分程隔板'
        """, (product_id,))
    rows = cursor.fetchall()
    geban_params = {r["参数名称"]: r["参数值"] for r in rows}

    if "材料类型" in geban_params:
        fencheng_geban["材料类型"] = geban_params["材料类型"]
    if "材料牌号" in geban_params:
        fencheng_geban["材料牌号"] = geban_params["材料牌号"]

    # === 格式化函数 ===
    def format_no_decimal(val, default):
        try:
            f = float(val)
            return str(int(f)) if f.is_integer() else str(f)
        except (TypeError, ValueError):
            return str(default)

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  # 不使用 with，游标不会自动关闭

        # 1. 读取3个参数值
        params_map = {
            "换热管中心距 S": ("s_val", 25),
            "分程隔板两侧相邻管中心距（竖直）": ("sn_val", 0),  # 分程隔板两侧相邻管中心距（竖直）
            "分程隔板两侧相邻管中心距（水平）": ("snh_val", 100)
        }
        results = {}
        for pname, (key, default) in params_map.items():
            cursor.execute("""
                    SELECT 参数值 FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = %s LIMIT 1
                """, (product_id, pname))
            row = cursor.fetchone()
            raw_val = row["参数值"].strip() if row and row.get("参数值") else None
            results[key] = format_no_decimal(raw_val, default)

        s_val = results["s_val"]
        sn_val = results["sn_val"]
        snh_val = results["snh_val"]

        print("  S =", s_val)
        print("  竖直中心距 SN =", sn_val)
        print("  水平中心距 SNH =", snh_val)
    except Exception as e:
        print(f"  查询失败: {e}")

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()

        # === 查询管程程数 ===
        cursor.execute("""
                SELECT 参数值
                FROM 产品设计活动表_布管参数表
                WHERE 产品ID = %s AND 参数名 = '管程程数'
                LIMIT 1
            """, (product_id,))
        row = cursor.fetchone()
        tube_form = row["参数值"].strip() if row and row.get("参数值") else None

    except Exception as e:
        print(f"  查询失败: {e}")
        tube_form = None
    if tube_form == "1":
        sn_val = 0
        snh_val = 0

    vertical_total = 0
    horizontal_total = 0

    #   先查询水平隔板数量（行号=1 的记录）
    try:
        cursor.execute("""
                SELECT `管孔数量（上）`, `管孔数量（下）`
                FROM 产品设计活动表_布管数量表_水平
                WHERE 产品ID = %s AND CAST(`至水平中心线行号` AS SIGNED) = 1
                LIMIT 1
            """, (product_id,))
        row = cursor.fetchone()
        if row:
            up_val = int(row["管孔数量（上）"]) if row.get("管孔数量（上）") not in (None, "", "None") else 0
            down_val = int(row["管孔数量（下）"]) if row.get("管孔数量（下）") not in (None, "", "None") else 0
            horizontal_total = max(up_val, down_val)
    except Exception as e:
        print(f"  查询水平管子数量失败: {e}")
        horizontal_total = 0

    if tube_form == "2":
        #   管程=2 → 竖直隔板数量直接为0
        vertical_total = 0

    else:
        #   管程≠2 → 根据布管数量表计算竖直隔板数量
        try:
            cursor.execute("""
                    SELECT CAST(`至水平中心线行号` AS SIGNED) AS line_no,
                           `管孔数量（上）`, `管孔数量（下）`
                    FROM 产品设计活动表_布管数量表_水平
                    WHERE 产品ID = %s
                    ORDER BY line_no ASC
                """, (product_id,))
            rows = cursor.fetchall()

            if rows:
                max_line = 0
                has_zero_case = False
                for r in rows:
                    line_no = int(r["line_no"]) if r.get("line_no") else 0
                    up_val = int(r["管孔数量（上）"]) if r.get("管孔数量（上）") not in (None, "", "None") else 0
                    down_val = int(r["管孔数量（下）"]) if r.get("管孔数量（下）") not in (None, "", "None") else 0

                    max_line = max(max_line, line_no)
                    if up_val == 0 or down_val == 0:
                        has_zero_case = True

                vertical_total = max_line * 2
                if has_zero_case:
                    vertical_total -= 1
            else:
                vertical_total = 0

        except Exception as e:
            print(f"  查询竖直隔板数量失败: {e}")
            vertical_total = 0

    print(f"  水平隔板最内侧管总数 horizontal_total = {horizontal_total}")
    print(f"  竖直隔板最内侧管总数 vertical_total = {vertical_total}")

    import pymysql

    # 默认值
    lianjie = "否"

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  # 手动创建游标，不会自动关闭

        # === 查询滑道定位 ===
        cursor.execute("""
                SELECT 参数值
                FROM 产品设计活动表_布管参数表
                WHERE 产品ID = %s AND 参数名 = '滑道定位'
                LIMIT 1
            """, (product_id,))
        row = cursor.fetchone()
        val = row["参数值"].strip() if row and row.get("参数值") else ""
        print(f"  数据库中滑道定位 参数值 = {repr(val)}")

        lianjie = "是" if val == "滑道与管板焊接" else "否"

    except Exception as e:
        print(f"  查询失败: {e}")

    try:
        cursor.execute("""
                SELECT `管孔数量（上）`, `管孔数量（下）`
                FROM 产品设计活动表_布管数量表_水平
                WHERE 产品ID = %s
            """, (product_id,))
        rows = cursor.fetchall()

        if rows:
            total = 0
            for r in rows:
                try:
                    raw_val1 = r.get("管孔数量（上）")
                    val1 = int(raw_val1) if raw_val1 and raw_val1 not in ("None",) else 0

                    raw_val2 = r.get("管孔数量（下）")
                    val2 = int(raw_val2) if raw_val2 and raw_val2 not in ("None",) else 0

                    total += val1
                    total += val2
                except (ValueError, TypeError):
                    continue
            tubes_count = str(total)
            print("tubes_count", tubes_count)
        else:
            tubes_count = "0"
        print(f"  当前产品ID {product_id} 的管总数 tubes_count = {tubes_count}")
        print("  沿水平隔板槽一侧的排管根数 =", horizontal_total)
        print("  沿竖直隔板槽一侧的排管根数 =", vertical_total)


    except Exception as e:
        print(f"  查询 tubes_count 失败: {e}")
        tubes_count = "0"

    # === 构建 guanban_a 字典 ===
    guanban_a = {
        # "公称直径": "1000", #管程
        "管程液柱静压力": "0",  # 管程 1
        "壳程液柱静压力": "0",  # 壳程 1
        "管程腐蚀裕量": "2",  # 管程 1
        "壳程腐蚀裕量": "2",  # 壳程 1
        "是否可以保证在任何情况下管壳程压力都能同时作用": "0",  # 固定管板 1
        # "换热管使用场合": "介质易爆/极度危害/高度危害", #壳程，介质特性（爆炸危险程度）+管程和壳程，介质特性（毒性危害程度）
        # "换热管与管板连接方式": "焊接", #无
        "管板材料类型": "钢锻件",  # 固定管板 1
        "管板材料名称": "16Mn",  # 固定管板 1
        "管板名义厚度": "0",  # 无 1
        # "管板外径": "1063", #无
        "壳程侧隔板槽深度": "0",  # 固定管板 1
        "管程侧隔板槽深度": "6",  # 固定管板 1
        "管程侧应力释放槽深度": "0",  # 固定管板 1
        "壳程侧应力释放槽深度": "0",  # 固定管板 1
        "管板强度削弱系数": "0.4",  # 固定管板 1
        "管板刚度削弱系数": "0.4",  # 固定管板 1
        "换热管材料类型": "钢管",  # 换热管 1
        "换热管材料牌号": "10(GB9948)",  # 换热管 1
        "换热管外径": "25",  # 换热管 1
        "换热管壁厚": "2",  # 布管 1
        "换热管直管段长度": "6000",  # 布管 1
        "换热管伸出管板长度": "4.5",  # 无 1
        "换热管根数": tubes_count,  # 布管 1
        "换热管中心距": 0,  # 布管 1
        "耐压试验温度": "20",  # 无 1
        "换热管受压失稳当量长度": "800",  # 无 1
        # "内孔焊焊接接头系数": "0.85", #无
        # "换热管与管板胀接长度或焊脚高度": "3.5", #布管
        # "换热管是否钢材": "1", #换热管
        # "胀接管孔是否开槽": "1", #无
        # "垫片材料名称": "复合柔性石墨波齿金属板(不锈钢)", #管箱垫片
        # "垫片与密封面接触外径": "1063", #管箱垫片
        # "垫片与密封面接触内径": "1025", #管箱垫片
        # "垫片厚度": "3", #管箱垫片
        # "压紧面形式": "1a或1b", #管箱垫片
        "换热管排列方式": "正三角形",  # 布管 1
        "折流板切口方向": "垂直",  # 布管 1
        "管/壳程布置型式": "2.1",  # 布管，管程程数 1
        "水平隔板槽两侧相邻管中心距": 0,  # 布管 1
        "竖直隔板槽两侧相邻管中心距": 0,  # 布管 1
        "相邻隔板槽中心距": "204",  # 无 1
        "管板分程处面积Ad": "0",  # 无 1
        "'十字'交叉沿水平隔板槽单侧的排管根数": "0",  # 无 1
        "沿竖直隔板槽单侧的排管根数": "0",  # 无 1
        "'丁字'交叉沿水平隔板槽连续侧的排管根数": "0",  # 无 1
        "'丁字'交叉沿水平隔板槽不连续侧的排管根数": "0",  # 无 1
        "'十字'交叉沿水平隔板槽单侧管排1最两端管孔中心距": "0",  # 无 1
        "'十字'交叉沿水平隔板槽单侧管排2最两端管孔中心距": "0",  # 无 1
        "'十字'交叉沿水平隔板槽单侧管排3最两端管孔中心距": "0",  # 无 1
        "'丁字'交叉沿水平隔板槽不连续侧管排1最两端管孔中心距": "0",  # 无 1
        "'丁字'交叉沿水平隔板槽不连续侧管排2最两端管孔中心距": "0",  # 无 1
        "'丁字'交叉沿水平隔板槽不连续侧管排3最两端管孔中心距": "0",  # 无 1
        "沿竖直隔板槽单侧的管排最两端管孔中心距": "0",  # 无 1
        "沿长度平均的壳程圆筒金属温度": "180",  #
        "沿长度平均的换热管金属温度": "155",  #
        "制造环境温度": "20",
        "管程公称直径": "2500",  # 条件输入
        "壳程公称直径": "2500",  # 条件输入
        "管板材料负偏差": "0",
        "管程圆筒材料负偏差": "0.3",
        "壳程圆筒材料负偏差": "0.3",
        "管程覆层厚度": "0",  #
        "壳程覆层厚度": "0",  #
        "管箱圆筒材料类型": "钢板",  #
        "管箱圆筒材料名称": "Q345R",  #
        "壳程圆筒材料类型": "钢板",  #
        "壳程圆筒材料名称": "Q345R",  #
        "壳程圆筒是否分段": "0",
        "壳程圆筒端部材料类型": "钢板",  #
        "壳程圆筒端部材料名称": "Q345R",  #
        "管程圆筒环向焊接接头系数": "1",  #
        "壳程圆筒环向焊接接头系数": "0.6",  #
        "管板与壳体/管箱的连接序号": "b",
        "应力释放槽深度": "3",
        "换热管与管板连接型式": "强度焊接",
        "换热管与管板焊脚高度": "4",
        "折流板间距": "437.5",  #
        "壳程圆筒名义厚度": "20",
        "壳体端部圆筒1长度": "0",
        "壳体端部圆筒2长度": "0",
        "壳程端部圆筒名义厚度": "20",
        "管箱圆筒名义厚度": "20",
        "管箱法兰厚度": "0",
        "壳体法兰厚度": "0",
        "a": "0",
        "b": "0",
        "c": "0",
        "d": "0",
        "f": "0",
        "g": "0",
        "h": "0",
        "i": "0",
        "k": "0",
        "l": "0",
        "r": "0",
        "j": "0",
        "q": "0",
        "f2": "0",
        "q2": "0"
    }

    tube_bundle = {
        "实际布管区域最大直径": "960",  # 无
        "实际布管区域最大高度": "200",  # 无
        # "导流筒边缘过水平中心线距离": "50", #无
        # "导流筒厚度": "3", #导流筒
        "旁路挡板厚度": "11",  # 旁路挡板
        # "导流筒内部折边倒角": "2", #无
        "换热管壁厚": "2",  # 布管
        "换热管孔间距": 0,  # 无 #换热管中心距
        "接管布置型式": "1",  # 无
        "管程数": "2",  # 布管
        "换热管排列方式": "正三角形",  # 布管
        "折流板切口方向": "水平",  # 布管
        "水平分程隔板槽两侧相邻管中心距水平上下": 0,  # 布管
        "竖直分程隔板槽两侧相邻管中心距垂直左右": 0,  # 布管
        "水平分程隔板槽数量": "1",  # 无
        "竖直分程隔板槽数量": "0",  # 无
        "布管限定圆直径": "784",  # 布管
        "换热管理论直管长度": "6000",  # 换热管公称长度 LN
        "换热管伸出管板值": "4.5",  # 无
        "折流板切口与中心线间距": "300",  # 无
        # "圆筒内径": "800", #布管，壳体内直径
        "公称直径": "1000",  # 管程
        "圆筒名义厚度": "12",  # 无
        "管板类型": "a",  # 无
        "管板凸台高度": "5",  # 固定管板
        "垫片厚度": "4.5",  # 管箱垫片
        "管板与壳程圆筒连接台肩长度": "0",  # 无
        "折流板需求间距": "350",  # 无
        "入口OD1/OD2": "OD1",  # 轴向定位距离和基准进行计算
        "拉杆类型": "螺纹拉杆",  # 拉杆，拉杆型式
        "拉杆用螺母厚度": "16",  # 拉杆直径计算
        "换热管外径": "19",  # 布管
        "折流板厚度初始值": "3",  # 无
        "换热管材料序号": "1",  # 换热管，材料级别
        "拉杆直径": "",  # 根据换热管计算
        "换热管材料类型": "钢管",
        "换热管材料牌号": "10(GB8163)",
        # "内折流板材料牌号":'',
        # "内折流板材料类型": '',
        # "异形折流板材料牌号": '',
        # "异形折流板材料类型": '',
        "弓形折流板材料牌号": '',
        "弓形折流板材料类型": '',
        # "支撑板材料牌号": '',
        # "支撑板材料类型": '',
        # "导流筒材料牌号": '',
        # "导流筒材料类型": '',
        "中间挡板材料牌号": '',
        "中间挡板材料类型": '',
        "支持板材料牌号": '',
        "支持板材料类型": '',
        "滑道材料牌号": '',
        "滑道材料类型": '',
        "中间挡管材料牌号": '',
        "中间挡管材料类型": '',
        "堵板材料牌号": '',
        "堵板材料类型": '',
        "防冲挡板材料牌号": '',
        "防冲挡板材料类型": '',
        "拉杆材料牌号": '',
        "拉杆材料类型": '',
        "定距管材料牌号": '',
        "定距管材料类型": '',
        "滑道高度": '',
        "滑道厚度": '',
        "防冲挡板宽度": '',
        "防冲挡板厚度": '',
        "中间挡板宽度": '',
        "中间挡板厚度": '',
        "管板与壳程圆筒搭接长度": "3",
        "管板与壳体/管箱的连接序号": "b",
    }

    anzuo = {
        "公称直径": "1000",
        "鞍座设计温度": "50",
        "筋板材料类型": "钢板",
        "筋板材料牌号": "Q345R",
        "筋板名义厚度": "10",
        "腹板材料类型": "钢板",
        "腹板材料牌号": "Q345R",
        "腹板名义厚度": "20",
        "底板材料类型": "钢板",
        "底板材料牌号": "Q345R",
        "底板名义厚度": "15",
        "壳程入口接管法兰外径": "",
        "壳程出口接管法兰外径": ""
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

            #   获取列D对应的值（法兰外径）
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
            "接管是否以外径为基准": "True",
            "接管腐蚀余量1": "0",
            "接管腐蚀余量2": "0",
            "接管腐蚀余量3": "0",
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
                SELECT 数值 FROM 产品设计活动表_通用数据表
                WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
            """, (product_id,))
        row = cursor.fetchone()
        if row and "数值" in row:
            val = str(row["数值"]).strip()
            jieguan["接管是否以外径为基准"] = "1" if val == "是" else "0"
        # ===== 获取管口基础信息 =====
        cursor.execute("""
                SELECT 管口功能, 管口所属元件, 公称尺寸,
                       偏心距, `轴向夹角（°）`, 外伸高度
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口代号 = %s
                LIMIT 1
            """, (product_id, guankou_daihao))
        row = cursor.fetchone()

        if row:
            print("DEBUG: original value =", repr(row.get("管口所属元件")))

            val = row.get("管口所属元件", "").strip()
            if val == "前端管箱圆筒":
                val = "管箱圆筒"

            jieguan["开孔元件名称"] = val  # 后面根据这个判断取管程 / 壳程

            jieguan["接管中心线至筒体轴线距离(偏心距)"] = str(row.get("偏心距", "0"))
            jieguan["接管中心线与法线夹角(包括封头)"] = str(row.get("轴向夹角（°）", "0"))
            jieguan["接管实际外伸长度"] = str(row.get("外伸高度", "0"))

        # 程序推荐兜底
        if jieguan.get("接管实际外伸长度") == "程序推荐":
            jieguan["接管实际外伸长度"] = "0"

        # ======================================================================================
        # 计算正常操作工况下操作温度变化范围（核心逻辑）
        # ======================================================================================

        def safe_float(v):
            try:
                return float(v) if v not in (None, "", "None") else None
            except:
                return None

        # -------------------------------------------
        # ① 取入口/出口温度
        # -------------------------------------------
        cursor.execute("""
                SELECT 参数名称, 管程数值, 壳程数值
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s
                  AND 参数名称 IN ('工作温度（入口）','工作温度（出口）')
            """, (product_id,))
        rows = cursor.fetchall()

        temp_in = None
        temp_out = None

        is_gxt = "管箱圆筒" in jieguan["开孔元件名称"]  # 是否取管程数值
        is_hxt = "壳体圆筒" in jieguan["开孔元件名称"]  # 是否取壳程数值

        for r in rows:
            name = r.get("参数名称", "").strip()

            # 根据元件类型决定取哪一个字段
            if is_gxt:
                val = safe_float(r.get("管程数值"))
            else:
                val = safe_float(r.get("壳程数值"))

            if name == "工作温度（入口）":
                temp_in = val
            elif name == "工作温度（出口）":
                temp_out = val

        # -------------------------------------------
        # ② 若入口/出口有值 → max(入口、出口）- 20
        # -------------------------------------------
        result_temp = None

        if temp_in is not None or temp_out is not None:
            max_temp = max(v for v in (temp_in, temp_out) if v is not None)
            result_temp = max_temp - 20

        # -------------------------------------------
        # ③ 若入口/出口都空 → 用 “设计温度（最高）*”
        # -------------------------------------------
        if result_temp is None:
            cursor.execute("""
                    SELECT 管程数值, 壳程数值
                    FROM 产品设计活动表_设计数据表
                    WHERE 产品ID = %s
                      AND 参数名称 = '设计温度（最高）*'
                    LIMIT 1
                """, (product_id,))
            r = cursor.fetchone()
            if r:
                if is_gxt:
                    base_val = safe_float(r.get("管程数值"))
                else:
                    base_val = safe_float(r.get("壳程数值"))

                if base_val is not None:
                    result_temp = base_val - 20

        # -------------------------------------------
        # ④ 最终兜底
        # -------------------------------------------
        if result_temp is None:
            result_temp = 10

        jieguan["正常操作工况下操作温度变化范围"] = str(int(result_temp))

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

        print(f"  管口代号 {guankou_daihao} 使用材料分类: {category}")

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
        print(f"  材料分类（{guankou_daihao}）: {material_classes or '统一材料'}")

        # === 获取管口功能 ===
        cursor.execute("""
                SELECT 管口功能
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口代号 = %s
                LIMIT 1
            """, (product_id, guankou_daihao))
        row = cursor.fetchone()
        guankou_gongneng = row["管口功能"].strip() if row and row["管口功能"] else ""
        print(f"  管口功能: {guankou_gongneng}")
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

        print(f"  管口功能: {guankou_gongneng}")
        print(f"  所属元件: {suoshuyuanjian}")

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
        # print(f"  接管腐蚀裕量: {jieguan.get('接管腐蚀裕量')}")

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
        "管箱平盖": guangxiang_pinggai,
        "头盖法兰": tougai_falan,
        "管箱圆筒": guanxiang_yuantong,
        "管箱分程隔板": fencheng_geban,
        "壳体圆筒": qiaoti_yuantong,
        "固定管板": guanban_a,
        "管束": tube_bundle,
        "鞍座": anzuo,
        "壳体端部圆筒1": qiaoti_duanbuyuantong1,
        "壳体端部圆筒2": qiaoti_duanbuyuantong2,
        "后端管箱圆筒": guanxiang_houduanyuantong,
        "吊耳": diaoer,
        "后端管箱平盖": houduan_guanxiangpinggai,
        "后端头盖法兰": houduan_tougaifalan

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

        # === 替换 DictDatas 中所有模块的 "换热器类型" 为 AEU ===
        for module_data in result.get("DictDatas", {}).values():
            print(module_data)
            if isinstance(module_data, dict):
                for key in module_data:
                    if key == "换热器型号":
                        module_data[key] = "NEN"

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
    #   删除 WSList 中所有字段都是 "0" 的项
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

    with open("qiaotineizhijing.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)
    clr.AddReference("CalCulationInterF")  # 不加 .dll 后缀
    from CalCulationInterF import CalPartInterface
    # # 读取JSON文件并转换为紧凑格式
    with open("qiaotineizhijing.json", "r", encoding="utf-8") as f:
        json_input = f.read()
    with open("qiaotineizhijing.json", "r", encoding="utf-8") as f:
        data = json.load(f)  # 此时可以正常读取
        print(data)  # 输出到控制台
        print("NEN输入json")
    parsed = json.loads(json_input)
    compact_json = json.dumps(parsed, separators=(',', ':'))
    cpi = CalPartInterface()
    outputjsonstr = cpi.IntergratedDi(compact_json)
    print("outputjsonsrt",outputjsonstr)
    print("NEN输入json")
    return outputjsonstr


def get_fastener_bolt_material_by_belong(cursor, product_id, belong_keyword, is_stud=True):
    """
        从 元件附加参数合并表 中取设备法兰紧固件材料牌号：
          - belong_keyword: '管箱平盖' / '管箱法兰' / '外头盖法兰' / '浮头法兰' ...
          - is_stud=True 取螺柱(材料牌号1)，False 取螺母(材料牌号2)
        返回: (material_grade, hit_tab, hit_comp_id) 或 (None, None, None)
        """
    cursor.execute("""
            SELECT 元件ID, 参数名称, 参数值, Tab分类
            FROM 产品设计活动表_元件附加参数合并表
            WHERE 产品ID = %s
        """, (product_id,))
    rows = cursor.fetchall()

    # Tab -> 元件ID -> params
    tab_map = {}
    for r in rows:
        tab = r.get("Tab分类")
        cid = r.get("元件ID")
        tab_map.setdefault(tab, {}).setdefault(cid, {})[r.get("参数名称")] = r.get("参数值")

    idx_flag = "1" if is_stud else "2"

    for tab, comp_group in tab_map.items():
        for cid, params in comp_group.items():
            if params.get("元件名称") != "设备法兰紧固件":
                continue
            belongs = str(params.get("元件所属") or "")
            if belong_keyword not in belongs:
                continue

            mat = params.get(f"材料牌号{idx_flag}")
            mat = str(mat).strip() if mat is not None else ""
            if mat and mat.lower() != "none":
                return mat, tab, cid

    return None, None, None