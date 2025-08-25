import os
import re
import string
import sys
from collections import defaultdict

import configparser

import chardet
import pymysql
import json
import clr

from modules.chanpinguanli.chanpinguanli_main import product_manager

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
        return "1063"
    if field == "垫片有效内径" and v == "0":
        return "1023"
    return v
material_type_map = {
    "板材":"钢板",
    "锻件": "钢锻件",
    "Q235系列钢板": "钢板",

}
falan_map = {
    '长颈对焊法兰' : '整体法兰2'
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

    for i, row in enumerate(port_rows):
        if i >= 4:
            break
        key = f"N{i + 1}"

        axial_angle = row.get("轴向夹角（°）", "")
        zhouxiangfangwei = row.get("周向方位（°）", "")

        # 外伸高度处理逻辑
        ttH_raw = row.get("外伸高度", "默认")
        ttH_val = "0" if ttH_raw in (None, "", "默认") else str(ttH_raw)

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
            "ttSpec": clean_value(row.get("焊端规格")),
            "ttAttach": clean_value(row.get("管口所属元件")),
            "ttPlace": {
                "左基准线": "左轮廓线",
                "右基准线": "右轮廓线"
            }.get(row.get("轴向定位基准", ""), clean_value(row.get("轴向定位基准"))),
            "ttLoc": clean_value(row.get("轴向定位距离")),
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
        "管/壳程布置型式":"2.1"
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
            WHERE 产品ID = %s AND 参数名 = '管程程数'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        tube_form = row["参数值"].strip() if row and row.get("参数值") else None
        # === 处理查询结果并赋值给 design_params ===
        if tube_form:
            if re.match(r"^\d+_\d+$", tube_form):
                design_params["管/壳程布置型式"] = tube_form.replace("_", ".")
            elif tube_form == "2":
                design_params["管/壳程布置型式"] = "2.1"
            elif tube_form == "4":
                design_params["管/壳程布置型式"] = "4.2"
            elif tube_form == "6":
                design_params["管/壳程布置型式"] = "6.2"
            else:
                design_params["管/壳程布置型式"] = tube_form
        else:
            print(f"⚠️ 未找到 产品ID={product_id} 的管程分程形式")
            design_params["管/壳程布置型式"] = ""
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
        "管程入口接管": "接管",
        "管程出口接管": "接管",
        "壳程入口接管": "接管",
        "壳程出口接管": "接管"

    }
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
        "法兰类型": "松式法兰4",
        "法兰材料类型": "",
        "法兰材料牌号": "",
        "法兰材料腐蚀裕量": "3",
        "法兰颈部大端有效厚度": "26",
        "法兰颈部小端有效厚度": "16",
        "法兰名义内径": "1020",
        "法兰名义外径": "1300",
        "法兰名义厚度": "65",
        "法兰颈部高度": "35",
        "覆层厚度": "0",
        "管程还是壳程": "管程",
        "法兰为夹持法兰": "是",
        "法兰位置": "壳体法兰",
        "圆筒名义厚度": "10",
        "圆筒有效厚度": "8",
        "圆筒名义内径": "1000",
        "圆筒名义外径": "1020",
        "圆筒材料类型": "板材",
        "圆筒材料牌号": "Q345R",
        "焊缝高度": "0",
        "焊缝长度": "0",
        "焊缝深度": "0",
        "法兰种类": "长颈",
        "公称直径管前左": "1000",
        "公称直径壳后右": "1200",
        "对接元件管前左内直径": "1000",
        "对接元件壳后右内直径": "1000",
        "对接元件管前左基层名义厚度": "20",
        "对接元件壳后右基层名义厚度": "30",
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
        "法兰位置管前左": "管箱平盖",
        "法兰位置壳后右": "头盖法兰",
        "垫片名义外径": "1060",
        "垫片名义内径": "1020",
        "螺栓中心圆直径": "1200",
        "螺栓材料牌号": "35CrMo",
        "螺栓公称直径": "M16",
        "螺栓数量": "60",
        "螺栓根径": "0",
        "螺栓面积余量百分比": "30",
        "垫片序号": "1",
        "垫片材料牌号": "复合柔性石墨波齿金属板(不锈钢)",
        "m": "0",
        "y": "0",
        "垫片厚度": "3",
        "垫片有效外径": "0",
        "垫片有效内径": "0",
        "分程隔板与垫片接触面面积": "0",
        "垫片分程隔板肋条有效密封宽度": "0",
        "垫片代号": "2.1",
        "隔条位置尺寸": "0",
        "介质情况": "毒性"
    }


    cursor.execute("""
        SELECT 参数名称, 壳程数值, 管程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row for row in rows}
    # 管箱侧垫片参数 → 名称映射
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
        tougai_falan["介质情况"] = "/".join(media_parts)
    cursor.execute("""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = '管箱平盖'
            """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    tougai_falan["法兰材料类型管前左"] = row_map.get("材料类型", "0")
    tougai_falan["法兰材料牌号管前左"] = row_map.get("材料牌号", "0")
    cursor.execute("""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = '头盖法兰'
            """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    tougai_falan["法兰材料类型壳后右"] = row_map.get("材料类型", "0")
    tougai_falan["法兰材料牌号壳后右"] = row_map.get("材料牌号", "0")
    # === 获取“管箱圆筒”对接元件材料信息 ===
    cursor.execute("""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = '管箱平盖'
            """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    tougai_falan["对接元件管前左材料类型"] = row_map.get("材料类型", "0")
    tougai_falan["对接元件管前左材料牌号"] = row_map.get("材料牌号", "0")

    # === 获取“壳体圆筒”对接元件材料信息 ===
    cursor.execute("""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = '头盖法兰'
            """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    tougai_falan["对接元件壳后右材料类型"] = row_map.get("材料类型", "0")
    tougai_falan["对接元件壳后右材料牌号"] = row_map.get("材料牌号", "0")

    # === 获取“管箱圆筒”的圆筒相关参数 ===
    cursor.execute("""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
            """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    # guangxiang_pinggai["圆筒名义内径"] = row_map.get("内径", "0")
    # guangxiang_pinggai["圆筒名义外径"] = row_map.get("外径", "0")
    tougai_falan["圆筒材料类型"] = row_map.get("材料类型", "0")
    tougai_falan["圆筒材料牌号"] = row_map.get("材料牌号", "0")
    # === 管箱圆筒 ===
    cursor.execute("""
               SELECT 参数名称, 参数值
               FROM 产品设计活动表_元件附加参数表
               WHERE 产品ID = %s AND 元件名称 = '管箱平盖'
           """, (product_id,))
    rows = cursor.fetchall()
    gx_data = {row["参数名称"]: str(row["参数值"]).strip() for row in rows if row["参数值"] not in (None, "", "None")}

    if gx_data.get("是否添加覆层") == "是":
        tougai_falan["对接元件覆层厚度管前左"] = gx_data.get("覆层厚度", "0")
        # guanxiang_falan["对接元件覆层复合方式管前左"] = gx_data.get("覆层成型工艺", "")
    else:
        tougai_falan["对接元件覆层厚度管前左"] = "0"
        # guanxiang_falan["对接元件覆层复合方式管前左"] = ""

    # === 壳体圆筒 ===
    cursor.execute("""
               SELECT 参数名称, 参数值
               FROM 产品设计活动表_元件附加参数表
               WHERE 产品ID = %s AND 元件名称 = '头盖法兰'
           """, (product_id,))
    rows = cursor.fetchall()
    qt_data = {row["参数名称"]: str(row["参数值"]).strip() for row in rows if row["参数值"] not in (None, "", "None")}

    if qt_data.get("是否添加覆层") == "是":
        tougai_falan["对接元件覆层厚度壳后右"] = qt_data.get("覆层厚度", "0")
        # guanxiang_falan["对接元件覆层复合方式壳后右"] = qt_data.get("覆层成型工艺", "")
    else:
        tougai_falan["对接元件覆层厚度壳后右"] = "0"
        # guanxiang_falan["对接元件覆层复合方式壳后右"] = ""
    cursor.execute("""
                   SELECT 参数名称, 参数值
                   FROM 产品设计活动表_元件附加参数表
                   WHERE 产品ID = %s AND 元件名称 = '头盖法兰'
               """, (product_id,))
    rows = cursor.fetchall()
    qt_data = {row["参数名称"]: str(row["参数值"]).strip() for row in rows if row["参数值"] not in (None, "", "None")}

    if qt_data.get("是否添加覆层") == "是":
        tougai_falan["覆层厚度壳后右"] = qt_data.get("覆层厚度", "0")
        # guanxiang_falan["对接元件覆层复合方式壳后右"] = qt_data.get("覆层成型工艺", "")
    else:
        tougai_falan["覆层厚度壳后右"] = "0"
    cursor.execute("""
                   SELECT 参数名称, 参数值
                   FROM 产品设计活动表_元件附加参数表
                   WHERE 产品ID = %s AND 元件名称 = '管箱平盖'
               """, (product_id,))
    rows = cursor.fetchall()
    qt_data = {row["参数名称"]: str(row["参数值"]).strip() for row in rows if row["参数值"] not in (None, "", "None")}

    if qt_data.get("是否添加覆层") == "是":
        tougai_falan["覆层厚度管前左"] = qt_data.get("覆层厚度", "0")
        # guanxiang_falan["对接元件覆层复合方式壳后右"] = qt_data.get("覆层成型工艺", "")
    else:
        tougai_falan["覆层厚度管前左"] = "0"

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()

        # === 查询隔条位置尺寸 W ===
        cursor.execute("""
            SELECT 参数值
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 = '隔条位置尺寸 W'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["参数值"].strip() if row and row.get("参数值") else None

        try:
            val11 = str(float(raw_val)) if raw_val not in (None, "", " ", "None") else "10"
        except ValueError:
            val11 = "10"
        tougai_falan["隔条位置尺寸"] = val11

        # === 查询平盖直径 ===
        cursor.execute("""
            SELECT 管程数值
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s AND 参数名称 = '公称直径*'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        tougai_falan["平盖直径"] = safe_str(row["管程数值"]) if row else "0"

    except Exception as e:
        print(f"❌ 查询失败: {e}")

    # 分程隔板槽宽
    cursor.execute("""
            SELECT 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '分程隔板槽宽'
            LIMIT 1
        """, (product_id,))
    row = cursor.fetchone()
    try:
        val = int(float(row["参数值"])) - 2 if row and row["参数值"] else 0
    except (ValueError, TypeError):
        val = 0
    tougai_falan["垫片分程隔板肋条有效密封宽度"] = str(val)

    # 法兰名义内/外径
    cursor.execute("""
            SELECT 参数名称, 壳程数值, 管程数值
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s AND 参数名称 = '公称直径*'
        """, (product_id,))
    row = cursor.fetchone()
    if row:
        tougai_falan["法兰名义内径"] = safe_str(row.get("壳程数值"))
        tougai_falan["法兰名义外径"] = safe_str(row.get("管程数值"))

    # 管箱侧垫片参数 → 名称映射
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '平盖垫片'
        """, (product_id,))
    rows = cursor.fetchall()

    # 统一清洗参数值
    def clean_val(val):
        return str(val).strip() if val not in (None, "", "None") else "0"

    param_map = {r["参数名称"].strip(): clean_val(r["参数值"]) for r in rows}

    gasket_map = {
        "垫片名义外径D2n": "垫片名义外径",
        "垫片名义内径D1n": "垫片名义内径",
        "垫片与密封面接触外径D2": "垫片有效外径",
        "垫片与密封面接触内径D1": "垫片有效内径"
    }

    for k, v in gasket_map.items():
        tougai_falan[v] = param_map.get(k, "0")

    # 法兰材料类型
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '头盖法兰'
        """, (product_id,))
    rows = cursor.fetchall()
    falan_params = {r["参数名称"]: r["参数值"] for r in rows}
    for name in ["材料类型", "材料牌号"]:
        if name in falan_params:
            tougai_falan[f"法兰{name}"] = safe_str(falan_params[name])

    # 液柱静压力 & 介质密度
    cursor.execute("""
            SELECT 参数名称, 壳程数值, 管程数值
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s
        """, (product_id,))
    rows = cursor.fetchall()
    param_map = {r["参数名称"].strip(): r for r in rows}
    for field_name, key in [("液柱静压力", "液柱静压力")]:
        if key in param_map:
            tougai_falan[f"壳程{field_name}"] = safe_str(param_map[key].get("壳程数值"))
            tougai_falan[f"管程{field_name}"] = safe_str(param_map[key].get("管程数值"))

    # 设计参数（sheji_param）
    sheji_param = {
        "法兰材料腐蚀裕量": ("腐蚀裕量*", "管程数值"),
        "法兰材料腐蚀裕量管前左": ("腐蚀裕量*", "管程数值"),
        "法兰材料腐蚀裕量壳后右": ("腐蚀裕量*", "管程数值"),
        "公称直径管前左": ("公称直径*", "管程数值"),
        "公称直径壳后右": ("公称直径*", "壳程数值"),
        "纵向焊接接头系数": ("焊接接头系数*", "壳程数值"),
        "对接元件管前左内直径": ("公称直径*", "壳程数值"),
        "对接元件壳后右内直径": ("公称直径*", "管程数值"),
    }
    for field, (param, side) in sheji_param.items():
        val = param_map.get(param, {}).get(side, "")
        tougai_falan[field] = safe_str(val)

    # 附加元件参数组件表
    cursor.execute("""
            SELECT 元件名称, 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s
        """, (product_id,))
    rows = cursor.fetchall()
    component_map = {}
    for r in rows:
        comp = (r.get("元件名称") or "").strip()
        param = (r.get("参数名称") or "").strip()
        val = r.get("参数值") or ""

        if not comp or not param:
            continue  # 如果缺少关键字段，跳过此行

        component_map.setdefault(comp, {})[param] = val

    # 元件参数映射
    yuanjian_param = {
        ("头盖法兰", "轴向拉伸载荷"): "轴向外力",
        ("头盖法兰", "附加弯矩"): "外力矩",
        # ("壳体法兰", "法兰类型"): "法兰类型壳后右",
        ("头盖法兰", "材料类型"): "法兰材料类型壳后右",
        ("头盖法兰", "材料牌号"): "法兰材料牌号壳后右",
        # ("壳体法兰", "覆层厚度"): "覆层厚度壳后右",
        # ("管箱法兰", "覆层厚度"): "覆层厚度管前左",
        ("管箱圆筒", "材料类型"): "圆筒材料类型",
        ("管箱圆筒", "材料牌号"): "圆筒材料牌号",
        # ("管箱法兰", "法兰类型"): "法兰类型管前左",
        ("管箱平盖", "材料类型"): "法兰材料类型管前左",
        ("管箱平盖", "材料牌号"): "法兰材料牌号管前左",
        ("管箱平盖", "平盖类型"): "平盖序号",
        ("螺柱（平盖法兰）", "材料牌号"): "螺栓材料牌号",
        ("平盖垫片", "材料牌号"): "垫片材料牌号",
        ("平盖垫片", "垫片系数m"): "m",
        ("平盖垫片", "垫片比压力y"): "y",

    }
    special_force_fields = {"轴向拉伸载荷", "附加弯矩"}

    for (comp, param), field in yuanjian_param.items():
        val = component_map.get(comp, {}).get(param, "")
        val = str(val).strip() if val is not None else ""
        if val.lower() == "none":
            val = ""
        if param in special_force_fields and val == "":
            val = "0"
        if field == "m":
            try:
                val = str(int(float(val)))
            except:
                val = "0"
        tougai_falan[field] = apply_special_defaults(field, val)
    guangxiang_pinggai = {

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
        "法兰名义内径": "",
        "法兰名义外径": "",
        "法兰名义厚度": "65",
        "法兰颈部高度": "35",
        "覆层厚度": "0",
        "管程还是壳程": "管程",
        "法兰为夹持法兰": "是",
        "法兰位置": "管箱平盖",
        "圆筒名义厚度": "10",
        "圆筒有效厚度": "8",
        "圆筒名义内径": "0",
        "圆筒名义外径": "0",
        "圆筒材料类型": "",
        "圆筒材料牌号": "",
        "焊缝高度": "0",
        "焊缝长度": "10",
        "焊缝深度": "0",
        "法兰种类": "长颈",
        "介质情况": "毒性",
        "公称直径管前左": "",
        "公称直径壳后右": "",
        "对接元件管前左内直径": 0,
        "对接元件壳后右内直径": "",
        "对接元件管前左基层名义厚度": 0,
        "对接元件壳后右基层名义厚度": "30",
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
        "法兰位置管前左": "管箱平盖",
        "法兰位置壳后右": "头盖法兰",
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
        "螺栓面积余量百分比": "30",
        "垫片序号": "1",
        "垫片材料牌号": "复合柔性石墨波齿金属板(不锈钢)",
        "m": "0",
        "y": "0",
        "垫片厚度": "3",
        "垫片有效外径": "0",
        "垫片有效内径": "0",
        "分程隔板与垫片接触面面积": "0",
        "垫片分程隔板肋条有效密封宽度": "0",
        "垫片代号": "2.1",
        "隔条位置尺寸": "0"

    }

    cursor.execute("""
        SELECT 参数名称, 壳程数值, 管程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row for row in rows}
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
        guangxiang_pinggai["介质情况"] = "/".join(media_parts)
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '平盖垫片'
        """, (product_id,))
    rows = cursor.fetchall()

    # 统一清洗参数值
    def clean_val(val):
        return str(val).strip() if val not in (None, "", "None") else "0"

    param_map = {r["参数名称"].strip(): clean_val(r["参数值"]) for r in rows}

    gasket_map = {
        "垫片名义外径D2n": "垫片名义外径",
        "垫片名义内径D1n": "垫片名义内径",
        "垫片与密封面接触外径D2": "垫片有效外径",
        "垫片与密封面接触内径D1": "垫片有效内径"
    }

    for k, v in gasket_map.items():
        guangxiang_pinggai[v] = param_map.get(k, "0")
    # === 获取“管箱圆筒”对接元件材料信息 ===
    # cursor.execute("""
    #     SELECT 参数名称, 参数值
    #     FROM 产品设计活动表_元件附加参数表
    #     WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
    # """, (product_id,))
    # rows = cursor.fetchall()
    # row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    # guangxiang_pinggai["对接元件管前左材料类型"] = row_map.get("材料类型", "0")
    # guangxiang_pinggai["对接元件管前左材料牌号"] = row_map.get("材料牌号", "0")

    # === 获取“壳体圆筒”对接元件材料信息 ===
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
    """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    guangxiang_pinggai["对接元件壳后右材料类型"] = row_map.get("材料类型", "0")
    guangxiang_pinggai["对接元件壳后右材料牌号"] = row_map.get("材料牌号", "0")

    # === 获取“管箱圆筒”的圆筒相关参数 ===
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
    """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    # guangxiang_pinggai["圆筒名义内径"] = row_map.get("内径", "0")
    # guangxiang_pinggai["圆筒名义外径"] = row_map.get("外径", "0")
    guangxiang_pinggai["圆筒材料类型"] = row_map.get("材料类型", "0")
    guangxiang_pinggai["圆筒材料牌号"] = row_map.get("材料牌号", "0")
       # === 壳体圆筒 ===
    cursor.execute("""
           SELECT 参数名称, 参数值
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s AND 元件名称 = '头盖法兰'
       """, (product_id,))
    rows = cursor.fetchall()
    qt_data = {row["参数名称"]: str(row["参数值"]).strip() for row in rows if row["参数值"] not in (None, "", "None")}

    if qt_data.get("是否添加覆层") == "是":
        guangxiang_pinggai["覆层厚度壳后右"] = qt_data.get("覆层厚度", "0")
        # guanxiang_falan["对接元件覆层复合方式壳后右"] = qt_data.get("覆层成型工艺", "")
    else:
        guangxiang_pinggai["覆层厚度壳后右"] = "0"
        # guanxiang_falan["对接元件覆层复合方式壳后右"] = ""
    cursor.execute("""
               SELECT 参数名称, 参数值
               FROM 产品设计活动表_元件附加参数表
               WHERE 产品ID = %s AND 元件名称 = '管箱平盖'
           """, (product_id,))
    rows = cursor.fetchall()
    qt_data = {row["参数名称"]: str(row["参数值"]).strip() for row in rows if row["参数值"] not in (None, "", "None")}

    if qt_data.get("是否添加覆层") == "是":
        guangxiang_pinggai["覆层厚度管前左"] = qt_data.get("覆层厚度", "0")
        # guanxiang_falan["对接元件覆层复合方式壳后右"] = qt_data.get("覆层成型工艺", "")
    else:
        guangxiang_pinggai["覆层厚度管前左"] = "0"
        # guanxiang_falan["对接元件覆层复合方式壳后右"] = ""
    # # ========== 查询管箱圆筒的覆层厚度 ==========
    # cursor.execute("""
    #     SELECT 参数值
    #     FROM 产品设计活动表_元件附加参数表
    #     WHERE 产品ID = %s AND 元件名称 = '管箱圆筒' AND 参数名称 = '覆层厚度'
    # """, (product_id,))
    # row = cursor.fetchone()
    # guangxiang_pinggai["对接元件覆层厚度管前左"] = safe_str(row["参数值"]) if row else "0"

    # ========== 查询壳体圆筒的覆层厚度 ==========
    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '壳体圆筒' AND 参数名称 = '覆层厚度'
    """, (product_id,))
    row = cursor.fetchone()
    guangxiang_pinggai["对接元件覆层厚度壳后右"] = safe_str(row["参数值"]) if row else "0"

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()

        # === 查询隔条位置尺寸 W ===
        cursor.execute("""
            SELECT 参数值
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 = '隔条位置尺寸 W'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["参数值"].strip() if row and row.get("参数值") else None

        # ✅ 这里后面可以继续使用 cursor 执行多个查询
        # cursor.execute("SELECT ...")

    except Exception as e:
        print(f"❌ 查询失败: {e}")

    # === 处理参数值（空或无效默认 10） ===
    try:
        val11 = str(float(raw_val)) if raw_val not in (None, "", " ", "None") else "10"
    except ValueError:
        val11 = "10"

    guangxiang_pinggai["隔条位置尺寸"] = val11

    # ========== 平盖直径 ==========
    cursor.execute("""
        SELECT 管程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s AND 参数名称 = '公称直径*'
        LIMIT 1
    """, (product_id,))
    row = cursor.fetchone()
    guangxiang_pinggai["平盖直径"] = safe_str(row["管程数值"]) if row else "0"

    # ========== 垫片分程隔板肋条有效密封宽度 ==========
    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '分程隔板槽宽'
        LIMIT 1
    """, (product_id,))
    row = cursor.fetchone()
    try:
        val = int(float(row["参数值"])) - 2 if row and row["参数值"] else ""
    except (ValueError, TypeError):
        val = ""
    guangxiang_pinggai["垫片分程隔板肋条有效密封宽度"] = str(val) if val != "" else "0"

    # ========== 法兰名义内/外径 ==========
    cursor.execute("""
        SELECT 参数名称, 壳程数值, 管程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s AND 参数名称 = '公称直径*'
    """, (product_id,))
    row = cursor.fetchone()
    if row:
        guangxiang_pinggai["法兰名义内径"] = safe_str(row.get("壳程数值"))
        guangxiang_pinggai["法兰名义外径"] = safe_str(row.get("管程数值"))

    # ========== sheji_param 字段 ==========
    sheji_param = {
        "法兰材料腐蚀裕量": ("腐蚀裕量*", "管程数值"),
        "法兰材料腐蚀裕量管前左": ("腐蚀裕量*", "管程数值"),
        "法兰材料腐蚀裕量壳后右": ("腐蚀裕量*", "管程数值"),
        "公称直径管前左": ("公称直径*", "管程数值"),
        "公称直径壳后右": ("公称直径*", "壳程数值"),
        "纵向焊接接头系数": ("焊接接头系数*", "管程数值"),
        # "对接元件管前左内直径": ("公称直径*", "壳程数值"),
        "对接元件壳后右内直径": ("公称直径*", "管程数值"),
    }

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

    for field, (param, side) in sheji_param.items():
        val = param_map.get(param, {}).get(side, "")
        guangxiang_pinggai[field] = safe_str(val)

    # ========== 液柱静压力 和 介质密度 ==========
    if "液柱静压力" in param_map:
        guangxiang_pinggai["壳程液柱静压力"] = safe_str(param_map["液柱静压力"].get("壳程数值"))
        guangxiang_pinggai["管程液柱静压力"] = safe_str(param_map["液柱静压力"].get("管程数值"))
    if "介质密度" in param_map:
        guangxiang_pinggai["壳程液柱密度"] = safe_str(param_map["介质密度"].get("壳程数值"))
        guangxiang_pinggai["管程液柱密度"] = safe_str(param_map["介质密度"].get("管程数值"))

    # ========== 头盖法兰参数 ==========
    param_map2 = {
        "轴向拉伸载荷": "轴向外力",
        "附加弯矩": "外力矩",
        "法兰类型": "法兰类型",
        "材料类型": "法兰材料类型",
        "材料牌号": "法兰材料牌号"
    }
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '头盖法兰'
    """, (product_id,))
    rows = cursor.fetchall()
    for row in rows:
        name = row["参数名称"].strip()
        if name in param_map2:
            val = safe_str(row["参数值"])
            if name in ("轴向拉伸载荷", "附加弯矩") and val == "0":
                val = "0"
            guangxiang_pinggai[param_map2[name]] = val

    # ========== yuanjian_param 结构 ==========
    yuanjian_param = {
        ("头盖法兰", "法兰类型"): "法兰类型",
        ("头盖法兰", "材料类型"): "法兰材料类型",
        ("头盖法兰", "材料牌号"): "法兰材料牌号",
        # ("壳体法兰", "法兰类型"): "法兰类型壳后右",
        ("壳体法兰", "材料类型"): "法兰材料类型壳后右",
        ("壳体法兰", "材料牌号"): "法兰材料牌号壳后右",
        # ("管箱法兰", "覆层厚度"): "覆层厚度管前左",
        # ("壳体法兰", "覆层厚度"): "覆层厚度壳后右",
        ("管箱圆筒", "材料类型"): "圆筒材料类型",
        ("管箱圆筒", "材料牌号"): "圆筒材料牌号",
        # ("管箱法兰", "法兰类型"): "法兰类型管前左",
        ("管箱法兰", "材料类型"): "法兰材料类型管前左",
        ("管箱法兰", "材料牌号"): "法兰材料牌号管前左",
        ("管箱平盖", "平盖类型"): "平盖序号",
        ("螺柱（管箱平盖）", "材料牌号"): "螺栓材料牌号",
        ("平盖垫片", "垫片材料"): "垫片材料牌号",
        ("平盖垫片", "垫片比压力y"): "y",

        ("平盖垫片", "垫片系数m"): "m",
    }
    component_param_names = defaultdict(set)
    for (component, pname) in yuanjian_param:
        component_param_names[component].add(pname)

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
                guangxiang_pinggai[yuanjian_param[key]] = name_val_map.get(pname, "0")
            else:
                print(f"⚠️ 警告：未找到映射 key = {key}")

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

    }
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
        guangxiang_fengtou["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        guangxiang_fengtou["椭圆形封头覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
    else:
        guangxiang_fengtou["是否覆层"] = "0"
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

    }
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
    else:
        keti_fengtou["是否覆层"] = "0"
        keti_fengtou["覆层复合方式"] = "无"
        keti_fengtou["椭圆形封头覆层厚度"] = "0"

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
    "换热管长度": ""
    }
    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()

        # === 查询换热管公称长度LN ===
        cursor.execute("""
            SELECT 参数值
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 = '换热管公称长度LN'
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
        guanxiang_yuantong["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        guanxiang_yuantong["圆筒覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
    else:
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
        "换热管长度": ""
    }
    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()

        # === 查询换热管公称长度LN ===
        cursor.execute("""
            SELECT 参数值
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 = '换热管公称长度LN'
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
        qiaoti_yuantong["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        qiaoti_yuantong["圆筒覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
    else:
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



    guanxiang_falan = {
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
        "法兰名义内径": "1020",
        "法兰名义外径": "1300",
        "法兰名义厚度": "65",
        "法兰颈部高度": "35",
        "覆层厚度": "0",
        "管程还是壳程": "管程",
        "法兰为夹持法兰": "是",
        "法兰位置": "管箱法兰",
        "圆筒名义厚度": "10",
        "圆筒有效厚度": "8",
        "圆筒名义内径": "1000",
        "圆筒名义外径": "1020",
        "圆筒材料类型": "板材",
        "圆筒材料牌号": "Q345R",
        "焊缝高度": "0",
        "焊缝长度": "0",
        "焊缝深度": "0",
        "法兰种类": "长颈",
        "公称直径管前左": "1000",
        "公称直径壳后右": "1200",
        "对接元件管前左内直径": "1000",
        "对接元件壳后右内直径": "1000",
        "对接元件管前左基层名义厚度": "20",
        "对接元件壳后右基层名义厚度": "30",
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
        "纵向焊接接头系数": "1",
        "平盖直径": "1000",
        "是否为圆形平盖": "是",
        "平盖材料类型": "钢锻件",
        "平盖材料牌号": "16Mn",
        "平盖分程隔板槽深度": "6",
        "平盖材料腐蚀裕量": "0.1",
        "平盖名义厚度": "96",
        "法兰位置管前左": "管箱法兰",
        "法兰位置壳后右": "壳体法兰",
        "垫片名义外径": "0",
        "垫片名义内径": "0",
        "螺栓中心圆直径": "1200",
        "螺栓材料牌号": "35CrMo",
        "螺栓公称直径": "M16",
        "螺栓数量": "60",
        "螺栓根径": "0",
        "螺栓面积余量百分比": "30",
        "垫片序号": "1",
        "垫片材料牌号": "复合柔性石墨波齿金属板(不锈钢)",
        "m": "0",
        "y": "0",
        "垫片厚度": "3",
        "垫片有效外径": "0",
        "垫片有效内径": "0",
        "分程隔板与垫片接触面面积": "0",
        "垫片分程隔板肋条有效密封宽度": "0",
        "垫片代号": "2.1",
        "隔条位置尺寸": "0",
        "介质情况": "毒性"
    }
    cursor.execute("""
        SELECT 参数名称, 壳程数值, 管程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row for row in rows}
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
        guanxiang_falan["介质情况"] = "/".join(media_parts)
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱垫片'
    """, (product_id,))
    rows = cursor.fetchall()

    # 统一清洗参数值
    def clean_val(val):
        return str(val).strip() if val not in (None, "", "None") else "0"

    param_map = {r["参数名称"].strip(): clean_val(r["参数值"]) for r in rows}

    gasket_map = {
        "垫片名义外径D2n": "垫片名义外径",
        "垫片名义内径D1n": "垫片名义内径",
        "垫片与密封面接触外径D2": "垫片有效外径",
        "垫片与密封面接触内径D1": "垫片有效内径"
    }

    for k, v in gasket_map.items():
        guanxiang_falan[v] = param_map.get(k, "0")
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '管箱法兰'
        """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    guanxiang_falan["法兰材料类型管前左"] = row_map.get("材料类型", "0")
    guanxiang_falan["法兰材料牌号管前左"] = row_map.get("材料牌号", "0")
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '壳体法兰'
        """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    guanxiang_falan["法兰材料类型壳后右"] = row_map.get("材料类型", "0")
    guanxiang_falan["法兰材料牌号壳后右"] = row_map.get("材料牌号", "0")
    # === 获取“管箱圆筒”对接元件材料信息 ===
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
        """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    guanxiang_falan["对接元件管前左材料类型"] = row_map.get("材料类型", "0")
    guanxiang_falan["对接元件管前左材料牌号"] = row_map.get("材料牌号", "0")

    # === 获取“壳体圆筒”对接元件材料信息 ===
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '壳体圆筒'
        """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    guanxiang_falan["对接元件壳后右材料类型"] = row_map.get("材料类型", "0")
    guanxiang_falan["对接元件壳后右材料牌号"] = row_map.get("材料牌号", "0")

    # === 获取“管箱圆筒”的圆筒相关参数 ===
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
        """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    # guangxiang_pinggai["圆筒名义内径"] = row_map.get("内径", "0")
    # guangxiang_pinggai["圆筒名义外径"] = row_map.get("外径", "0")
    guanxiang_falan["圆筒材料类型"] = row_map.get("材料类型", "0")
    guanxiang_falan["圆筒材料牌号"] = row_map.get("材料牌号", "0")
    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()

        # === 查询隔条位置尺寸 W ===
        cursor.execute("""
            SELECT 参数值
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 = '隔条位置尺寸 W'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["参数值"].strip() if row and row.get("参数值") else None

    except Exception as e:
        print(f"❌ 查询失败: {e}")

    # === 处理参数值（空或无效默认 10） ===
    try:
        val11 = str(float(raw_val)) if raw_val not in (None, "", " ", "None") else "10"
    except ValueError:
        val11 = "10"

    guanxiang_falan["隔条位置尺寸"] = val11

    # === 获取法兰名义内径 / 外径 ===
    cursor.execute("""
        SELECT 参数名称, 壳程数值, 管程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s AND 参数名称 = '公称直径*'
    """, (product_id,))
    row = cursor.fetchone()
    if row:
        guanxiang_falan["法兰名义内径"] = safe_str(row["壳程数值"])
        guanxiang_falan["法兰名义外径"] = safe_str(row["管程数值"])
    else:
        guanxiang_falan["法兰名义内径"] = "0"
        guanxiang_falan["法兰名义外径"] = "0"

    # === 获取液柱密度、液柱静压力 ===
    cursor.execute("""
        SELECT 参数名称, 壳程数值, 管程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()
    sheji_map = {r["参数名称"].strip(): r for r in rows}
    for param, field in [
        ("介质密度", "液柱密度"),
        ("液柱静压力", "液柱静压力")
    ]:
        guanxiang_falan[f"壳程{field}"] = safe_str(sheji_map.get(param, {}).get("壳程数值", "0"))
        guanxiang_falan[f"管程{field}"] = safe_str(sheji_map.get(param, {}).get("管程数值", "0"))

    # === 法兰附加参数：槽宽 - 2 ===
    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '分程隔板槽宽'
    """, (product_id,))
    row = cursor.fetchone()
    try:
        val = float(row["参数值"])
        guanxiang_falan["垫片分程隔板肋条有效密封宽度"] = str(int(val) - 2)
    except:
        guanxiang_falan["垫片分程隔板肋条有效密封宽度"] = "0"

    # === 管箱圆筒 ===
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
    """, (product_id,))
    rows = cursor.fetchall()
    gx_data = {row["参数名称"]: str(row["参数值"]).strip() for row in rows if row["参数值"] not in (None, "", "None")}

    if gx_data.get("是否添加覆层") == "是":
        guanxiang_falan["对接元件覆层厚度管前左"] = gx_data.get("覆层厚度", "0")
        # guanxiang_falan["对接元件覆层复合方式管前左"] = gx_data.get("覆层成型工艺", "")
    else:
        guanxiang_falan["对接元件覆层厚度管前左"] = "0"
        # guanxiang_falan["对接元件覆层复合方式管前左"] = ""

    # === 壳体圆筒 ===
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '壳体圆筒'
    """, (product_id,))
    rows = cursor.fetchall()
    qt_data = {row["参数名称"]: str(row["参数值"]).strip() for row in rows if row["参数值"] not in (None, "", "None")}

    if qt_data.get("是否添加覆层") == "是":
        guanxiang_falan["对接元件覆层厚度壳后右"] = qt_data.get("覆层厚度", "0")
        # guanxiang_falan["对接元件覆层复合方式壳后右"] = qt_data.get("覆层成型工艺", "")
    else:
        guanxiang_falan["对接元件覆层厚度壳后右"] = "0"
        # guanxiang_falan["对接元件覆层复合方式壳后右"] = ""
        # === 壳体圆筒 ===
    cursor.execute("""
           SELECT 参数名称, 参数值
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s AND 元件名称 = '壳体法兰'
       """, (product_id,))
    rows = cursor.fetchall()
    qt_data = {row["参数名称"]: str(row["参数值"]).strip() for row in rows if row["参数值"] not in (None, "", "None")}

    if qt_data.get("是否添加覆层") == "是":
        guanxiang_falan["覆层厚度壳后右"] = qt_data.get("覆层厚度", "0")
        # guanxiang_falan["对接元件覆层复合方式壳后右"] = qt_data.get("覆层成型工艺", "")
    else:
        guanxiang_falan["覆层厚度壳后右"] = "0"
        # guanxiang_falan["对接元件覆层复合方式壳后右"] = ""
    cursor.execute("""
               SELECT 参数名称, 参数值
               FROM 产品设计活动表_元件附加参数表
               WHERE 产品ID = %s AND 元件名称 = '管箱法兰'
           """, (product_id,))
    rows = cursor.fetchall()
    qt_data = {row["参数名称"]: str(row["参数值"]).strip() for row in rows if row["参数值"] not in (None, "", "None")}

    if qt_data.get("是否添加覆层") == "是":
        guanxiang_falan["覆层厚度管前左"] = qt_data.get("覆层厚度", "0")
        # guanxiang_falan["对接元件覆层复合方式壳后右"] = qt_data.get("覆层成型工艺", "")
    else:
        guanxiang_falan["覆层厚度管前左"] = "0"
        # guanxiang_falan["对接元件覆层复合方式壳后右"] = ""
    # === 获取设计参数表中的其余字段 ===
    sheji_param = {
        "法兰材料腐蚀裕量": ("腐蚀裕量*", "管程数值"),
        "法兰材料腐蚀裕量管前左": ("腐蚀裕量*", "管程数值"),
        "法兰材料腐蚀裕量壳后右": ("腐蚀裕量*", "壳程数值"),
        "公称直径管前左": ("公称直径*", "管程数值"),
        "公称直径壳后右": ("公称直径*", "壳程数值"),
        "纵向焊接接头系数": ("焊接接头系数*", "壳程数值"),
        "对接元件管前左内直径": ("公称直径*", "壳程数值"),
        "对接元件壳后右内直径": ("公称直径*", "管程数值"),
    }
    for field, (param_name, side) in sheji_param.items():
        guanxiang_falan[field] = safe_str(sheji_map.get(param_name, {}).get(side, "0"))

    # === 获取元件附加参数整体 ===
    cursor.execute("""
        SELECT 元件名称, 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()
    component_map = {}
    for r in rows:
        comp = r["元件名称"].strip()
        pname = r["参数名称"].strip()
        component_map.setdefault(comp, {})[pname] = r["参数值"]
        if not comp or not param:
            continue  # 如果缺少关键字段，跳过此行

    component_map.setdefault(comp, {})[param] = val
    # === 元件参数映射关系 ===
    yuanjian_param = {
        ("管箱法兰", "轴向拉伸载荷"): "轴向外力",
        ("管箱法兰", "附加弯矩"): "外力矩",
        # ("壳体法兰", "覆层厚度"): "覆层厚度壳后右",
        # ("管箱法兰", "覆层厚度"): "覆层厚度管前左",
        # ("管箱法兰", "法兰类型"): "法兰类型",
        ("管箱法兰", "材料类型"): "法兰材料类型",
        ("管箱法兰", "材料牌号"): "法兰材料牌号",
        ("管箱法兰", "覆层厚度"): "覆层厚度",
        ("管箱圆筒", "材料类型"): "圆筒材料类型",
        ("管箱圆筒", "材料牌号"): "圆筒材料牌号",
        ("管箱平盖", "平盖类型"): "平盖序号",
        ("螺柱（管箱法兰）", "材料牌号"): "螺栓材料牌号",
        ("管箱垫片", "材料牌号"): "垫片材料牌号",
        ("管箱垫片", "垫片系数m"): "m",
        ("管箱垫片", "垫片比压力y"): "y",

        ("管箱法兰", "材料类型"): "法兰材料类型管前左",
        ("管箱法兰", "材料牌号"): "法兰材料牌号管前左",
        ("壳体法兰", "材料类型"): "法兰材料类型壳后右",
        ("壳体法兰", "材料牌号"): "法兰材料牌号壳后右",
        ("管箱法兰", "材料类型"): "法兰材料类型",
        ("管箱法兰", "材料牌号"): "法兰材料牌号",
    }

    # === 写入字段 ===
    for (comp, pname), field in yuanjian_param.items():
        val = component_map.get(comp, {}).get(pname, "")
        val = safe_str(val)
        if pname in {"轴向拉伸载荷", "附加弯矩"} and val == "0":
            val = "0"
        if field == "m":
            try:
                val = str(int(float(val)))
            except:
                val = "0"
        guanxiang_falan[field] = apply_special_defaults(field, val)
    keti_falan = {
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
        "法兰名义内径": "1020",
        "法兰名义外径": "1300",
        "法兰名义厚度": "65",
        "法兰颈部高度": "35",
        "覆层厚度": "0",
        "管程还是壳程": "管程",
        "法兰为夹持法兰": "是",
        "法兰位置": "壳体法兰",
        "圆筒名义厚度": "10",
        "圆筒有效厚度": "8",
        "圆筒名义内径": "1000",
        "圆筒名义外径": "1020",
        "圆筒材料类型": "板材",
        "圆筒材料牌号": "Q345R",
        "焊缝高度": "0",
        "焊缝长度": "0",
        "焊缝深度": "0",
        "法兰种类": "长颈",
        "公称直径管前左": "1000",
        "公称直径壳后右": "1200",
        "对接元件管前左内直径": "1000",
        "对接元件壳后右内直径": "1000",
        "对接元件管前左基层名义厚度": "20",
        "对接元件壳后右基层名义厚度": "30",
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
        "法兰位置管前左": "管箱法兰",
        "法兰位置壳后右": "壳体法兰",
        "垫片名义外径": "1060",
        "垫片名义内径": "1020",
        "螺栓中心圆直径": "1200",
        "螺栓材料牌号": "35CrMo",
        "螺栓公称直径": "M16",
        "螺栓数量": "60",
        "螺栓根径": "0",
        "螺栓面积余量百分比": "30",
        "垫片序号": "1",
        "垫片材料牌号": "复合柔性石墨波齿金属板(不锈钢)",
        "m": "0",
        "y": "0",
        "垫片厚度": "3",
        "垫片有效外径": "0",
        "垫片有效内径": "0",
        "分程隔板与垫片接触面面积": "0",
        "垫片分程隔板肋条有效密封宽度": "0",
        "垫片代号": "2.1",
        "隔条位置尺寸": "0",
        "介质情况": "毒性"
    }
    cursor.execute("""
        SELECT 参数名称, 壳程数值, 管程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row for row in rows}
    # 管箱侧垫片参数 → 名称映射
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
        keti_falan["介质情况"] = "/".join(media_parts)

    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '管箱法兰'
        """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    keti_falan["法兰材料类型管前左"] = row_map.get("材料类型", "0")
    keti_falan["法兰材料牌号管前左"] = row_map.get("材料牌号", "0")
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '壳体法兰'
        """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    keti_falan["法兰材料类型壳后右"] = row_map.get("材料类型", "0")
    keti_falan["法兰材料牌号壳后右"] = row_map.get("材料牌号", "0")
    # === 获取“管箱圆筒”对接元件材料信息 ===
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
        """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    keti_falan["对接元件管前左材料类型"] = row_map.get("材料类型", "0")
    keti_falan["对接元件管前左材料牌号"] = row_map.get("材料牌号", "0")

    # === 获取“壳体圆筒”对接元件材料信息 ===
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '壳体圆筒'
        """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    keti_falan["对接元件壳后右材料类型"] = row_map.get("材料类型", "0")
    keti_falan["对接元件壳后右材料牌号"] = row_map.get("材料牌号", "0")

    # === 获取“管箱圆筒”的圆筒相关参数 ===
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
        """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    # guangxiang_pinggai["圆筒名义内径"] = row_map.get("内径", "0")
    # guangxiang_pinggai["圆筒名义外径"] = row_map.get("外径", "0")
    keti_falan["圆筒材料类型"] = row_map.get("材料类型", "0")
    keti_falan["圆筒材料牌号"] = row_map.get("材料牌号", "0")
    # === 管箱圆筒 ===
    cursor.execute("""
           SELECT 参数名称, 参数值
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
       """, (product_id,))
    rows = cursor.fetchall()
    gx_data = {row["参数名称"]: str(row["参数值"]).strip() for row in rows if row["参数值"] not in (None, "", "None")}

    if gx_data.get("是否添加覆层") == "是":
        keti_falan["对接元件覆层厚度管前左"] = gx_data.get("覆层厚度", "0")
        # guanxiang_falan["对接元件覆层复合方式管前左"] = gx_data.get("覆层成型工艺", "")
    else:
        keti_falan["对接元件覆层厚度管前左"] = "0"
        # guanxiang_falan["对接元件覆层复合方式管前左"] = ""

    # === 壳体圆筒 ===
    cursor.execute("""
           SELECT 参数名称, 参数值
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s AND 元件名称 = '壳体圆筒'
       """, (product_id,))
    rows = cursor.fetchall()
    qt_data = {row["参数名称"]: str(row["参数值"]).strip() for row in rows if row["参数值"] not in (None, "", "None")}

    if qt_data.get("是否添加覆层") == "是":
        keti_falan["对接元件覆层厚度壳后右"] = qt_data.get("覆层厚度", "0")
        # guanxiang_falan["对接元件覆层复合方式壳后右"] = qt_data.get("覆层成型工艺", "")
    else:
        keti_falan["对接元件覆层厚度壳后右"] = "0"
        # guanxiang_falan["对接元件覆层复合方式壳后右"] = ""
    cursor.execute("""
               SELECT 参数名称, 参数值
               FROM 产品设计活动表_元件附加参数表
               WHERE 产品ID = %s AND 元件名称 = '壳体法兰'
           """, (product_id,))
    rows = cursor.fetchall()
    qt_data = {row["参数名称"]: str(row["参数值"]).strip() for row in rows if row["参数值"] not in (None, "", "None")}

    if qt_data.get("是否添加覆层") == "是":
        keti_falan["覆层厚度壳后右"] = qt_data.get("覆层厚度", "0")
        # guanxiang_falan["对接元件覆层复合方式壳后右"] = qt_data.get("覆层成型工艺", "")
    else:
        keti_falan["覆层厚度壳后右"] = "0"
    cursor.execute("""
               SELECT 参数名称, 参数值
               FROM 产品设计活动表_元件附加参数表
               WHERE 产品ID = %s AND 元件名称 = '管箱法兰'
           """, (product_id,))
    rows = cursor.fetchall()
    qt_data = {row["参数名称"]: str(row["参数值"]).strip() for row in rows if row["参数值"] not in (None, "", "None")}

    if qt_data.get("是否添加覆层") == "是":
        keti_falan["覆层厚度管前左"] = qt_data.get("覆层厚度", "0")
        # guanxiang_falan["对接元件覆层复合方式壳后右"] = qt_data.get("覆层成型工艺", "")
    else:
        keti_falan["覆层厚度管前左"] = "0"
    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  # ✅ 手动创建游标，不使用 with

        # === 查询隔条位置尺寸 W ===
        cursor.execute("""
            SELECT 参数值
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 = '隔条位置尺寸 W'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["参数值"].strip() if row and row.get("参数值") else None

    except Exception as e:
        print(f"❌ 查询失败: {e}")

    # === 处理参数值（空或无效默认 10） ===
    try:
        val11 = str(float(raw_val)) if raw_val not in (None, "", " ", "None") else "10"
    except ValueError:
        val11 = "10"

    keti_falan["隔条位置尺寸"] = val11

    # 平盖直径
    cursor.execute("""
        SELECT 管程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s AND 参数名称 = '公称直径*'
        LIMIT 1
    """, (product_id,))
    row = cursor.fetchone()
    keti_falan["平盖直径"] = safe_str(row["管程数值"]) if row else "0"

    # 分程隔板槽宽
    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '分程隔板槽宽'
        LIMIT 1
    """, (product_id,))
    row = cursor.fetchone()
    try:
        val = int(float(row["参数值"])) - 2 if row and row["参数值"] else 0
    except (ValueError, TypeError):
        val = 0
    keti_falan["垫片分程隔板肋条有效密封宽度"] = str(val)

    # 法兰名义内/外径
    cursor.execute("""
        SELECT 参数名称, 壳程数值, 管程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s AND 参数名称 = '公称直径*'
    """, (product_id,))
    row = cursor.fetchone()
    if row:
        keti_falan["法兰名义内径"] = safe_str(row.get("壳程数值"))
        keti_falan["法兰名义外径"] = safe_str(row.get("管程数值"))

    # 管箱侧垫片参数 → 名称映射
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱侧垫片'
    """, (product_id,))
    rows = cursor.fetchall()

    # 统一清洗参数值
    def clean_val(val):
        return str(val).strip() if val not in (None, "", "None") else "0"

    param_map = {r["参数名称"].strip(): clean_val(r["参数值"]) for r in rows}

    gasket_map = {
        "垫片名义外径D2n": "垫片名义外径",
        "垫片名义内径D1n": "垫片名义内径",
        "垫片与密封面接触外径D2": "垫片有效外径",
        "垫片与密封面接触内径D1": "垫片有效内径"
    }

    for k, v in gasket_map.items():
        keti_falan[v] = param_map.get(k, "0")

    # 法兰材料类型
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '壳体法兰'
    """, (product_id,))
    rows = cursor.fetchall()
    falan_params = {r["参数名称"]: r["参数值"] for r in rows}
    for name in ["材料类型", "材料牌号"]:
        if name in falan_params:
            keti_falan[f"法兰{name}"] = safe_str(falan_params[name])

    # 液柱静压力 & 介质密度
    cursor.execute("""
        SELECT 参数名称, 壳程数值, 管程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()
    param_map = {r["参数名称"].strip(): r for r in rows}
    for field_name, key in [("液柱静压力", "液柱静压力")]:
        if key in param_map:
            keti_falan[f"壳程{field_name}"] = safe_str(param_map[key].get("壳程数值"))
            keti_falan[f"管程{field_name}"] = safe_str(param_map[key].get("管程数值"))

    # 设计参数（sheji_param）
    sheji_param = {
        "法兰材料腐蚀裕量": ("腐蚀裕量*", "管程数值"),
        "法兰材料腐蚀裕量管前左": ("腐蚀裕量*", "管程数值"),
        "法兰材料腐蚀裕量壳后右": ("腐蚀裕量*", "壳程数值"),
        "公称直径管前左": ("公称直径*", "管程数值"),
        "公称直径壳后右": ("公称直径*", "壳程数值"),
        "纵向焊接接头系数": ("焊接接头系数*", "壳程数值"),
        "对接元件管前左内直径": ("公称直径*", "壳程数值"),
        "对接元件壳后右内直径": ("公称直径*", "管程数值"),
    }
    for field, (param, side) in sheji_param.items():
        val = param_map.get(param, {}).get(side, "")
        keti_falan[field] = safe_str(val)

    # 附加元件参数组件表
    cursor.execute("""
        SELECT 元件名称, 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()
    component_map = {}
    for r in rows:
        comp = r["元件名称"].strip()
        param = r["参数名称"].strip()
        val = r["参数值"]
        component_map.setdefault(comp, {})[param] = val
        if not comp or not param:
            continue  # 如果缺少关键字段，跳过此行

    component_map.setdefault(comp, {})[param] = val
    # 元件参数映射
    yuanjian_param = {
        ("壳体法兰", "轴向拉伸载荷"): "轴向外力",
        ("壳体法兰", "附加弯矩"): "外力矩",
        # ("壳体法兰", "法兰类型"): "法兰类型壳后右",
        ("壳体法兰", "材料类型"): "法兰材料类型壳后右",
        ("壳体法兰", "材料牌号"): "法兰材料牌号壳后右",
        # ("壳体法兰", "覆层厚度"): "覆层厚度壳后右",
        # ("管箱法兰", "覆层厚度"): "覆层厚度管前左",
        ("壳体圆筒", "材料类型"): "圆筒材料类型",
        ("壳体圆筒", "材料牌号"): "圆筒材料牌号",
        # ("管箱法兰", "法兰类型"): "法兰类型管前左",
        ("管箱法兰", "材料类型"): "法兰材料类型管前左",
        ("管箱法兰", "材料牌号"): "法兰材料牌号管前左",
        ("壳体平盖", "平盖类型"): "平盖序号",
        ("螺柱（壳体法兰）", "材料牌号"): "螺栓材料牌号",
        ("管箱侧垫片", "材料牌号"): "垫片材料牌号",
        ("管箱侧垫片", "垫片系数m"): "m",
        ("管箱侧垫片", "垫片比压力y"): "y",

    }
    special_force_fields = {"轴向拉伸载荷", "附加弯矩"}

    for (comp, param), field in yuanjian_param.items():
        val = component_map.get(comp, {}).get(param, "")
        val = str(val).strip() if val is not None else ""
        if val.lower() == "none":
            val = ""
        if param in special_force_fields and val == "":
            val = "0"
        if field == "m":
            try:
                val = str(int(float(val)))
            except:
                val = "0"
        keti_falan[field] = apply_special_defaults(field, val)


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
        "隔条位置尺寸":"10",
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

    print("✅ 腐蚀裕量(双面) =", fencheng_geban["腐蚀裕量(双面)"])

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  # ✅ 不使用 with，游标不会自动关闭

        # === 查询隔条位置尺寸 W ===
        cursor.execute("""
            SELECT 参数值
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 = '隔条位置尺寸 W'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["参数值"].strip() if row and row.get("参数值") else None

    except Exception as e:
        print(f"❌ 查询失败: {e}")

    # === 处理参数值（空或无效默认 10） ===
    try:
        val11 = str(float(raw_val)) if raw_val not in (None, "", " ", "None") else "10"
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
        cursor = conn.cursor()  # ✅ 不使用 with，游标不会自动关闭

        # 1. 读取3个参数值
        params_map = {
            "换热管中心距 S": ("s_val", 25),
            "隔板槽两侧相邻管中心距Sn（竖直）": ("sn_val", 38),
            "隔板槽两侧相邻管中心距Sn（水平）": ("snh_val", 0)
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

        # 2. 读取布管坐标表
        cursor.execute("""
            SELECT `x坐标`, `y坐标`, `R值`
            FROM 产品设计活动表_布管坐标表
            WHERE 产品ID = %s
        """, (product_id,))
        coord_rows = cursor.fetchall()

    except Exception as e:
        print(f"❌ 查询失败: {e}")

    # === 收集所有坐标点 ===
    points = [(row["x坐标"], row["y坐标"]) for row in coord_rows if
              row.get("x坐标") is not None and row.get("y坐标") is not None]

    # === 按相同X、Y分组计算间距 ===
    x_groups = defaultdict(list)
    y_groups = defaultdict(list)

    for x, y in points:
        x_groups[x].append(y)
        y_groups[y].append(x)

    # === 计算最大Y方向间距 ===
    max_y_gap = 0
    max_y_coords = (None, None)

    for x, y_list in x_groups.items():
        # ✅ 将 y_list 中的值转换为 float（过滤 None 和空字符串）
        numeric_y = [float(y) for y in y_list if y not in (None, "", " ")]

        if len(numeric_y) >= 2:
            gap = max(numeric_y) - min(numeric_y)
            if gap > max_y_gap:
                max_y_gap = gap
                max_y_coords = ((x, min(numeric_y)), (x, max(numeric_y)))

    # === 计算最大X方向间距 ===
    max_x_gap = 0
    max_x_coords = (None, None)

    for y, x_list in y_groups.items():
        # ✅ 将 x_list 转换为 float（过滤 None 和空字符串）
        numeric_x = [float(xx) for xx in x_list if xx not in (None, "", " ")]

        if len(numeric_x) >= 2:
            gap = max(numeric_x) - min(numeric_x)
            if gap > max_x_gap:
                max_x_gap = gap
                max_x_coords = ((min(numeric_x), y), (max(numeric_x), y))

    # === 最终结果 ===
    if max_y_gap > max_x_gap:
        u_max_diameter = str(round(max_y_gap, 3))
        point1, point2 = max_y_coords
    else:
        u_max_diameter = str(round(max_x_gap, 3))
        point1, point2 = max_x_coords

    # === 输出结果 ===
    print(f"✅ S = {s_val}, Sn(竖直) = {sn_val}, Sn(水平) = {snh_val}")
    print(f"✅ 弯曲直径 u_max_diameter = {u_max_diameter}")
    print(f"✅ 最大间距坐标点：{point1} <-> {point2}")

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
        print(f"❌ 查询失败: {e}")
        tube_form = None

    vertical_total = 0
    horizontal_total = 0

    # ✅ 先查询水平隔板数量（行号=1 的记录）
    try:
        cursor.execute("""
            SELECT `管孔数量（上）`, `管孔数量（下）`
            FROM 产品设计活动表_布管数量表
            WHERE 产品ID = %s AND CAST(`至水平中心线行号` AS SIGNED) = 1
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        if row:
            up_val = int(row["管孔数量（上）"]) if row.get("管孔数量（上）") not in (None, "", "None") else 0
            down_val = int(row["管孔数量（下）"]) if row.get("管孔数量（下）") not in (None, "", "None") else 0
            horizontal_total = max(up_val, down_val)
    except Exception as e:
        print(f"❌ 查询水平隔板数量失败: {e}")
        horizontal_total = 0

    if tube_form == "2":
        # ✅ 管程=2 → 竖直隔板数量直接为0
        vertical_total = 0

    else:
        # ✅ 管程≠2 → 根据布管数量表计算竖直隔板数量
        try:
            cursor.execute("""
                SELECT CAST(`至水平中心线行号` AS SIGNED) AS line_no,
                       `管孔数量（上）`, `管孔数量（下）`
                FROM 产品设计活动表_布管数量表
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
            print(f"❌ 查询竖直隔板数量失败: {e}")
            vertical_total = 0

    print(f"✅ 水平隔板最内侧管总数 horizontal_total = {horizontal_total}")
    print(f"✅ 竖直隔板最内侧管总数 vertical_total = {vertical_total}")

    import pymysql

    # 默认值
    lianjie = "否"

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  # ✅ 手动创建游标，不会自动关闭

        # === 查询滑道定位 ===
        cursor.execute("""
            SELECT 参数值 
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 = '滑道定位'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        val = row["参数值"].strip() if row and row.get("参数值") else ""
        print(f"✅ 数据库中滑道定位 参数值 = {repr(val)}")

        lianjie = "是" if val == "滑道与管板焊接" else "否"

    except Exception as e:
        print(f"❌ 查询失败: {e}")

    # # 每侧排管根数（假设左右/上下对称）
    # horizontal_one_side = str(horizontal_total // 2)
    # vertical_one_side = str(vertical_total // 2)
    # === 从 管板连接形式.json 中获取第一个条目的 Id，作为管板类型 ===
    #----------------------------------------- 待改动------------------------------------------------------------------------
    # guanban_id = "a"
    # form_json_path = os.path.join(product_dir, "中间数据", "管板连接形式.json")
    #
    # if os.path.exists(form_json_path):
    #     with open(form_json_path, "r", encoding="utf-8") as f:
    #         form_data = json.load(f)
    #
    #         # 情况1：form_data 是 list 且不为空
    #         if isinstance(form_data, list) and form_data:
    #             guanban_id = form_data[0].get("FormId", "")
    #
    #         # 情况2：form_data 是 dict，直接取 FormId
    #         elif isinstance(form_data, dict):
    #             guanban_id = form_data.get("FormId", "")
    #
    #         else:
    #             guanban_id = ""
    #
    # else:
    #     print(f"⚠️ 未找到文件: {form_json_path}")
    #
    # # 示例存入 tube_bundle 或其他 dict 中
    # print("✅ 管板类型 =", guanban_id)
    # === tubes_count 从数据库读取管孔数量（上）总和 ===
    tubes_count = "0"
    try:
        cursor.execute("""
            SELECT `管孔数量（上）`
            FROM 产品设计活动表_布管数量表
            WHERE 产品ID = %s
        """, (product_id,))
        rows = cursor.fetchall()

        if rows:
            total = 0
            for r in rows:
                try:
                    val = int(r["管孔数量（上）"]) if r.get("管孔数量（上）") not in (None, "", "None") else 0
                    total += val
                except (ValueError, TypeError):
                    continue
            tubes_count = str(total)
        else:
            tubes_count = "0"

    except Exception as e:
        print(f"❌ 查询 tubes_count 失败: {e}")
        tubes_count = "0"

    print(f"✅ 当前产品ID {product_id} 的管总数 tubes_count = {tubes_count}")
    print("✅ 沿水平隔板槽一侧的排管根数 =", horizontal_total)
    print("✅ 沿竖直隔板槽一侧的排管根数 =", vertical_total)
    print("✅ S =", s_val)
    print("✅ 竖直中心距 SN =", sn_val)
    print("✅ 水平中心距 SNH =", snh_val)
    # print("✅ gap_width =", gap_width)
    # print("✅ gap_height =", gap_height)
    # print("✅ gap_area =", gap_area)

    # === 构建 guanban_a 字典 ===
    guanban_a = {
        "公称直径": "1000",
        "管程液柱静压力": "0",
        "壳程液柱静压力": "0",
        "管程腐蚀裕量": "0",
        "壳程腐蚀裕量": "0",
        "是否可以保证在任何情况下管壳程压力都能同时作用": "0",
        "换热管使用场合": "介质易爆/极度危害/高度危害",
        "换热管与管板连接方式": "焊接",
        "材料类型": "锻件",
        "材料牌号": "16Mn",
        "管板名义厚度": "0",
        "管板强度削弱系数": "0.4",
        "壳程侧结构槽深": "0",
        "管程侧隔板槽深": "6",
        "换热管材料类型": "钢管",
        "换热管材料牌号": "10(GB9948)",
        "换热管外径": "25",
        "换热管壁厚": "2",
        "换热管中心距": s_val,
        "换热管直管段长度": "3000",
        "耐压试验温度": "15",
        "内孔焊焊接接头系数": "0.85",
        "换热管与管板胀接长度或焊脚高度": "3.5",
        "换热管是否钢材": "1",
        "胀接管孔是否开槽": "1",
        "换热管根数": tubes_count,
        "垫片材料名称": "复合柔性石墨波齿金属板(不锈钢)",
        "管板外径": "863",
        "垫片与密封面接触外径": "863",
        "垫片与密封面接触内径": "825",
        "垫片厚度": "3",
        "压紧面形式": "1a或1b",
        "换热管排列方式": "正三角形",
        "折流板切口方向": "水平",
        "管/壳程布置型式": "2.1",
        "沿水平隔板槽一侧的排管根数": horizontal_total,
        "沿竖直隔板槽一侧的排管根数": vertical_total,
        "水平隔板槽两侧相邻管中心距": snh_val,
        "垂直隔板槽两侧相邻管中心距": sn_val,
        # "U形换热管最大弯曲直径": u_max_diameter,
        "管板分程处面积Ad": 0,
        "是否交叉布管": "0",
        "交叉管排1最两端管孔中心距": "0",
        "交叉管排1实际管孔数量": "0",
        "交叉管排2最两端管孔中心距": "0",
        "交叉管排2实际管孔数量": "0",
        "交叉管排3最两端管孔中心距": "0",
        "交叉管排3实际管孔数量": "0",
        # "垫片名义外径": '1023',
        # "垫片名义内径": '1000'
    }
    import pymysql

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  # ✅ 手动创建游标，不会自动关闭

        # === 读取换热管排列方式 ===
        cursor.execute("""
            SELECT 参数值 
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 = '换热管排列方式'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        guanban_a["换热管排列方式"] = row["参数值"].strip() if row and row.get("参数值") else ""

        # === 读取折流板切口方向 ===
        cursor.execute("""
            SELECT 参数值 
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 = '折流板切口方向'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        mapped_val = row["参数值"].strip() if row and row.get("参数值") else ""

        # === 二次分类映射（保持原逻辑） ===
        if mapped_val in {"水平上下"}:
            guanban_a["折流板切口方向"] = "水平"
        elif mapped_val in {"左右", "垂直左右"}:
            guanban_a["折流板切口方向"] = "垂直"
        elif mapped_val in {"上下"}:
            guanban_a["折流板切口方向"] = "竖直"
        else:
            guanban_a["折流板切口方向"] = mapped_val

    except Exception as e:
        print(f"❌ 查询失败: {e}")

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  # ✅ 不使用 with，游标保持可用

        # === 查询管程分程形式 ===
        cursor.execute("""
            SELECT 参数值 
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 = '管程程数'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        tube_form = row["参数值"].strip() if row and row.get("参数值") else None

    except Exception as e:
        print(f"❌ 查询失败: {e}")

    # === 处理查询结果并赋值给 design_params ===
    if tube_form:
        if re.match(r"^\d+_\d+$", tube_form):
            guanban_a["管/壳程布置型式"] = tube_form.replace("_", ".")
        elif tube_form == "2":
            guanban_a["管/壳程布置型式"] = "2.1"
        elif tube_form == "4":
            guanban_a["管/壳程布置型式"] = "4.2"
        elif tube_form == "6":
            guanban_a["管/壳程布置型式"] = "6.2"
        else:
            guanban_a["管/壳程布置型式"] = tube_form
    else:
        print(f"⚠️ 未找到 产品ID={product_id} 的管程分程形式")
        guanban_a["管/壳程布置型式"] = ""

    # 默认值
    e_val = 0.0
    g_val = 0.0
    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  # ✅ 手动创建游标，不会自动关闭

        # === 读取焊脚外伸高度E ===
        cursor.execute("""
            SELECT 参数值 FROM 产品设计活动表_管板连接表
            WHERE 产品ID = %s AND 参数名 = '焊脚外伸高度 E' LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        try:
            e_val = float(row["参数值"]) if row and row.get("参数值") else 0.0
        except (TypeError, ValueError):
            e_val = 0.0

        # === 读取管程侧坡口深度G ===
        cursor.execute("""
            SELECT 参数值 FROM 产品设计活动表_管板连接表
            WHERE 产品ID = %s AND 参数名 = '管程侧坡口深度 G' LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        try:
            g_val = float(row["参数值"]) if row and row.get("参数值") else 0.0
        except (TypeError, ValueError):
            g_val = 0.0

    except Exception as e:
        print(f"❌ 查询失败: {e}")
    print(e_val)
    print(g_val)
    # === 求和并写入 guanban_a ===
    sum_val = round(e_val + g_val, 1)  # 保留1位小数

    if "换热管与管板胀接长度或焊脚高度" in guanban_a:
        guanban_a["换热管与管板胀接长度或焊脚高度"] = str(sum_val)


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
        guanban_a["公称直径"] = str(param_map["公称直径*"].get("管程数值", ""))
    if "腐蚀裕量*" in param_map:
        guanban_a["管程腐蚀裕量"] = str(param_map["腐蚀裕量*"].get("管程数值", ""))
    if "腐蚀裕量*" in param_map:
        guanban_a["壳程腐蚀裕量"] = str(param_map["腐蚀裕量*"].get("壳程数值", ""))
    media_parts = []
    if "介质特性（爆炸危险程度）" in param_map:
        expl = param_map["介质特性（爆炸危险程度）"].get("壳程数值", "")
        if expl == "可燃":
            media_parts.append("介质可燃")
        elif expl == "易爆":
            media_parts.append("介质易爆")
    if "介质特性（毒性危害程度）" in param_map:
        shell_toxic = param_map["介质特性（毒性危害程度）"].get("壳程数值", "")
        tube_toxic = param_map["介质特性（毒性危害程度）"].get("管程数值", "")
        if shell_toxic:
            media_parts.append(f"{shell_toxic}危害")
        if tube_toxic:
            media_parts.append(f"{tube_toxic}危害")

    if media_parts:
        guanban_a["换热管使用场合"] = "/".join(media_parts)
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = 'U形换热管'
    """, (product_id,))
    rows = cursor.fetchall()

    # 遍历所有返回的参数，构建映射
    param_map = {row["参数名称"].strip(): str(row["参数值"]).strip() for row in rows if row["参数值"] is not None}

    # 设置 guanban_a 中的字段
    if "材料类型" in param_map:
        guanban_a["换热管材料类型"] = param_map["材料类型"]
    if "材料牌号" in param_map:
        guanban_a["换热管材料牌号"] = param_map["材料牌号"]

    # 查询壳程侧结构槽深和管程侧结构槽深
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '固定管板'
    """, (product_id,))
    rows = cursor.fetchall()

    # 转换为字典方便查找
    param_map = {row["参数名称"].strip(): row["参数值"] for row in rows}

    # 更新 guanban_a 中的两个字段
    if "壳程侧分程隔板槽深度" in param_map:
        guanban_a["壳程侧结构槽深"] = str(param_map["壳程侧分程隔板槽深度"])
    if "管程侧分程隔板槽深度" in param_map:
        guanban_a["管程侧隔板槽深"] = str(param_map["管程侧分程隔板槽深度"])
    if "壳程侧分程隔板槽深度" in param_map:
        guanban_a["壳程腐蚀裕量"] = str(param_map["壳程侧腐蚀裕量"])
    if "管程侧分程隔板槽深度" in param_map:
        guanban_a["管程腐蚀裕量"] = str(param_map["管程侧腐蚀裕量"])

    # 更新 guanban_a 字典中的材料类型和材料牌号
    if "材料类型" in param_map:
        guanban_a["材料类型"] = str(param_map["材料类型"])
    if "材料牌号" in param_map:
        guanban_a["材料牌号"] = str(param_map["材料牌号"])
    # === 参数名和 guanban_a 键的映射 ===
    mapping = {
        "换热管外径 do": "换热管外径",
        "换热管壁厚 δ": "换热管壁厚",
        "热交换器公称（换热管）长度 L": "换热管直管段长度"
    }

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  # ✅ 手动管理游标

        for param_name, target_key in mapping.items():
            cursor.execute("""
                SELECT 参数值 
                FROM 产品设计活动表_布管参数表
                WHERE 产品ID = %s AND 参数名 = %s
                LIMIT 1
            """, (product_id, param_name))
            row = cursor.fetchone()
            val = row["参数值"].strip() if row and row.get("参数值") else ""

            if val:  # 非空才写入
                try:
                    guanban_a[target_key] = str(float(val)).rstrip("0").rstrip(".")
                except ValueError:
                    guanban_a[target_key] = val

    except Exception as e:
        print(f"❌ 查询失败: {e}")

        # # 特殊处理换热管中心距为空的情况
        # if param_name == "换热管中心距 S":
        #     if val is None or str(val).strip() in ["", "0", "0.0", "None"]:
        #         guanban_a[key] = "25"
        #     else:
        #         guanban_a[key] = str(val).split(".")[0]
        # else:
        #     if val is not None and str(val).strip() != "":
        #         guanban_a[key] = str(val).split(".")[0]

    # 查询“U形换热管”的材料类型
    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = 'U形换热管' AND 参数名称 = '材料类型'
    """, (product_id,))
    row = cursor.fetchone()

    # 判断是否为钢材或钢管
    if row:
        material_type = str(row["参数值"]).strip()
        if "钢" in material_type:
            guanban_a["换热管是否钢材"] = "1"
        else:
            guanban_a["换热管是否钢材"] = "0"
    else:
        guanban_a["换热管是否钢材"] = "0"  # 默认非钢材
    # 查询布管数量表中所有管孔数量（上）与（下）


    # 设置根数，若为 0 则使用默认值 220
    # guanban_a["换热管根数"] = str(int(total_count) if total_count else 220)

    # 查询元件名称为“管箱垫片”的所有参数
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱垫片'
    """, (product_id,))
    rows = cursor.fetchall()

    # 构建一个参数名称 → 参数值 的字典
    gasket_params = {row["参数名称"].strip(): str(row["参数值"]).strip() for row in rows if row["参数值"] is not None}

    # 写入 guanban_a 字典中
    if "垫片材料" in gasket_params:
        guanban_a["垫片材料名称"] = gasket_params["垫片材料"]

    if "压紧面形状" in gasket_params:
        guanban_a["压紧面形式"] = gasket_params["压紧面形状"]
    if "垫片与密封面接触内径D1" in gasket_params:
        guanban_a["垫片与密封面接触内径"] = gasket_params["垫片与密封面接触内径D1"]
    if "垫片与密封面接触外径D2" in gasket_params:
        guanban_a["垫片与密封面接触外径"] = gasket_params["垫片与密封面接触外径D2"]
    if "垫片与密封面接触内径D1" in gasket_params:
        guanban_a["垫片与密封面接触内径"] = gasket_params["垫片与密封面接触内径D1"]
    # if "垫片名义外径D2n" in gasket_params:
    #     guanban_a["垫片名义外径"] = gasket_params["垫片名义外径D2n"]
    # if "垫片名义内径D1n" in gasket_params:
    #     guanban_a["垫片名义内径"] = gasket_params["垫片名义内径D1n"]
    # 查询布管参数表中该产品的所有参数
    # 定义排列形式映射字典

    # 默认值配置

    # if "隔板槽两侧相邻管中心距Sn(水平)" in tube_params:
    #     guanban_a["水平隔板槽两侧相邻管中心距"] = tube_params["隔板槽两侧相邻管中心距Sn(水平)"]
    # if "隔板槽两侧相邻管中心距Sn(竖直)" in tube_params:
    #     guanban_a["垂直隔板槽两侧相邻管中心距"] = tube_params["隔板槽两侧相邻管中心距Sn(竖直)"]

    tube_bundle = {
        "倾斜U形换热管两管孔的中心距离1排": "0",
        "倾斜U形换热管两管孔的中心距离2排": "0",
        "倾斜U形换热管两管孔的中心距离3排": "0",
        "换热管孔间距": "25",
        "允许交叉布管的排数": "0",
        "管垂直间距3排": "0",
        "管垂直间距2排": "0",
        "管垂直间距1排": "0",
        "仅倾斜or交叉1排": "0",
        "仅倾斜or交叉2排": "0",
        "仅倾斜or交叉3排": "0",
        "管程数": "2",
        # "管孔排列形式": "正三角形30水平切",
        "折流板缺口": "水平上下",
        "水平分程隔板槽两侧相邻管中心距水平上下": snh_val,
        "竖直分程隔板槽两侧相邻管中心距垂直左右": sn_val,
        "水平分程隔板槽数量": "1",
        "竖直分程隔板槽数量": "0",
        "布管限定圆直径": "784",
        "换热管理论直管长度": "6000",
        "换热管伸出管板值": "4.5",
        "管板名义厚度": "80",
        "折流板切口与中心线间距": "200",
        "圆筒内径": "800",
        "公称直径": "1000",
        "滑道与固定管板是否焊接连接": lianjie,
        "滑道伸出折流板/支持板最小值": "50",
        "是否交叉布管": "否",
        "接管外径1": "273",
        "接管外径2": "219",
        "接管1名义厚度": "16",
        "接管2名义厚度": "12",
        "圆筒名义厚度": "12",
        "管板类型": 'a',
        "接管中心线至圆筒边缘距离": "200",
        "法兰高度": "130",
        "管板凸台高度": "5",
        "垫片厚度": "4.5",
        "管板与壳程圆筒连接台肩长度": "0",
        "折流板需求间距": "350",
        "入口OD1/OD2": "OD1",
        "拉杆类型": "螺纹拉杆",
        "拉杆用螺母厚度": "16",
        "换热管外径": "19",
        "折流板厚度初始值": "3",
        "U形换热管最大弯曲直径": u_max_diameter,
        "换热管材料序号": "1",
        "拉杆直径": "",
        "接管OD2中心至壳程圆筒边缘(封头侧)最小距离": "219",
        "换热管材料类型": "钢管",
        "换热管材料牌号": "10(GB8163)",
        "换热管排列方式": "",
        "折流板切口方向":""
    }

    import pymysql

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  # ✅ 手动创建游标，不会自动关闭

        # === 读取换热管排列方式 ===
        cursor.execute("""
            SELECT 参数值 
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 = '换热管排列方式'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        tube_bundle["换热管排列方式"] = row["参数值"].strip() if row and row.get("参数值") else ""

        # === 读取折流板切口方向 ===
        cursor.execute("""
            SELECT 参数值 
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 = '折流板切口方向'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        mapped_val = row["参数值"].strip() if row and row.get("参数值") else ""

        # === 二次分类映射（保持原逻辑） ===
        if mapped_val in {"水平上下"}:
            tube_bundle["折流板切口方向"] = "水平"
        elif mapped_val in {"左右", "垂直左右"}:
            tube_bundle["折流板切口方向"] = "垂直"
        elif mapped_val in {"上下"}:
            tube_bundle["折流板切口方向"] = "竖直"
        else:
            tube_bundle["折流板切口方向"] = mapped_val

    except Exception as e:
        print(f"❌ 查询失败: {e}")

    # 默认值
    buguan_dl_value = "784"

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  # ✅ 手动管理游标

        cursor.execute("""
            SELECT 参数值 
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 = '布管限定圆 DL'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        if row and row.get("参数值") not in (None, "", "None"):
            buguan_dl_value = str(row["参数值"]).strip()
        else:
            buguan_dl_value = "784"  # ✅ 可以保持默认值逻辑

    except Exception as e:
        print(f"❌ 查询失败: {e}")

    # ✅ 写入目标字典
    tube_bundle["布管限定圆直径"] = buguan_dl_value

    # === 获取管箱垫片的垫片厚度 ===
    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱垫片' AND 参数名称 = '垫片厚度'
    """, (product_id,))
    row = cursor.fetchone()
    val = row["参数值"] if row and row["参数值"] not in (None, "", "None") else "4.5"
    tube_bundle["垫片厚度"] = str(val)

    # === 获取固定管板的管板凸台高度 ===
    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管板凸台高度'
    """, (product_id,))
    row = cursor.fetchone()
    val = row["参数值"] if row and row["参数值"] not in (None, "", "None") else "5"
    tube_bundle["管板凸台高度"] = str(val)

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  # ✅ 不使用 with，游标不会自动关闭

        # === 壳体内直径 Di ===
        cursor.execute("""
            SELECT 参数值 
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 = '壳体内直径 Di'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        if row and row.get("参数值") not in (None, "", " "):
            tube_bundle["圆筒内径"] = str(row["参数值"]).strip()

        # === 折流板切口与中心线间距 ===
        cursor.execute("""
            SELECT 参数值 
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 = '折流板切口与中心线间距'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        if row and row.get("参数值") not in (None, "", " "):
            tube_bundle["折流板切口与中心线间距"] = str(row["参数值"]).strip()

    except Exception as e:
        print(f"❌ 查询失败: {e}")

    cursor.execute("""
        SELECT 管口功能, 轴向定位基准, 轴向定位距离
        FROM 产品设计活动表_管口表
        WHERE 产品ID = %s AND 管口功能 IN ('壳程入口', '壳程出口')
    """, (product_id,))
    rows = cursor.fetchall()

    # 构建入口、出口信息
    koukou_map = {row["管口功能"]: row for row in rows}
    entry = koukou_map.get("壳程入口")
    exit_ = koukou_map.get("壳程出口")

    def parse_distance(val):
        if val is None:
            return 0
        val_str = str(val).strip()
        if val_str == "居中":
            return 500
        try:
            return float(val_str)
        except ValueError:
            return 0

    if entry and exit_:
        base_in = str(entry.get("轴向定位基准", "")).strip()
        base_out = str(exit_.get("轴向定位基准", "")).strip()
        dist_in = parse_distance(entry.get("轴向定位距离"))
        dist_out = parse_distance(exit_.get("轴向定位距离"))

        if base_in == "左轮廓线" and base_out == "左轮廓线":
            val = "OD2" if dist_out < dist_in else "OD1"
        elif base_in == "右轮廓线" and base_out == "右轮廓线":
            val = "OD1" if dist_out < dist_in else "OD2"
        elif base_out == "左轮廓线":
            val = "OD2"
        else:
            val = "OD1"

        tube_bundle["入口OD1/OD2"] = val
    else:
        print("❌ 缺少壳程入口或壳程出口的管口信息")

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  # ✅ 不使用 with，游标保持可用

        # === 读取管程数 ===
        cursor.execute("""
            SELECT 参数值 
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 = '管程数'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        tube_passes = row["参数值"].strip() if row and row.get("参数值") else ""

        if tube_passes:
            tube_bundle["管程数"] = tube_passes
            # === 根据管程数设置分程隔板槽数量 ===
            if tube_passes == "2":
                tube_bundle["水平分程隔板槽数量"] = "1"
                tube_bundle["竖直分程隔板槽数量"] = "0"
            elif tube_passes == "4":
                tube_bundle["水平分程隔板槽数量"] = "1"
                tube_bundle["竖直分程隔板槽数量"] = "1"
            else:
                tube_bundle["水平分程隔板槽数量"] = "0"
                tube_bundle["竖直分程隔板槽数量"] = "0"

    except Exception as e:
        print(f"❌ 查询失败: {e}")

    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = 'U形换热管'
    """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row["参数值"] for row in rows}

    # 遍历所有返回的参数，构建映射
    if param_map:
        if param_map.get("材料类型"):
            tube_bundle["换热管材料类型"] = param_map["材料类型"]
        if param_map.get("材料牌号"):
            tube_bundle["换热管材料牌号"] = param_map["材料牌号"]

    # ===== 补充处理拉杆直径 =====
    # 从已有 rows 构建参数名 → 参数值的映射（避免重复查询）

    import pymysql

    huanregaowaijing = ""
    # lagan_value = ""

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  # ✅ 手动创建游标，不会自动关闭

        # === 获取换热管外径 do ===
        cursor.execute("""
            SELECT 参数值 
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 = '换热管外径 do'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        if row and row.get("参数值"):
            huanregaowaijing = row["参数值"].strip()
        else:
            huanregaowaijing = ""
        tube_bundle['换热管外径'] = huanregaowaijing
        # ===（如果以后需要）获取拉杆直径 ===
        # cursor.execute("""
        #     SELECT 参数值
        #     FROM 产品设计活动表_布管参数表
        #     WHERE 产品ID = %s AND 参数名 = '拉杆直径'
        #     LIMIT 1
        # """, (product_id,))
        # row = cursor.fetchone()
        # lagan_value = row["参数值"].strip() if row and row.get("参数值") else None

    except Exception as e:
        print(f"❌ 查询失败: {e}")

    try:
        od_val = float(huanregaowaijing)
        if 10 <= od_val <= 14:
            tube_bundle["拉杆直径"] = "10"
        elif 14 < od_val < 25:
            tube_bundle["拉杆直径"] = "12"
        elif 25 <= od_val <= 57:
            tube_bundle["拉杆直径"] = "16"
        else:
            tube_bundle["拉杆直径"] = "未知"
    except (TypeError, ValueError):
        tube_bundle["拉杆直径"] = "未知"

    # === 螺母厚度 = 拉杆直径 ===
    tube_bundle["拉杆用螺母厚度"] = tube_bundle.get("拉杆直径", "")

    # # 读取并写入
    # cursor.execute("""
    #     SELECT 参数名, 参数值
    #     FROM 产品设计活动表_布管参数表
    #     WHERE 产品ID = %s
    # """, (product_id,))
    # rows = cursor.fetchall()
    #
    # for row in rows:
    #     param_name = row["参数名"].strip()
    #     value = row["参数值"]
    #     if param_name in bgtube_map and value is not None:
    #         tube_bundle[bgtube_map[param_name]] = str(value)
    # 查询设计数据表
    cursor.execute("""
        SELECT 参数名称, 管程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()

    # 查找公称直径* 对应的管程数值
    for row in rows:
        pname = row["参数名称"].strip()
        if pname == "公称直径*":
            value = row["管程数值"]
            if value is not None:
                tube_bundle["公称直径"] = str(value)
            break  # 找到后即可跳出

    # cursor.execute("""
    #     SELECT 管板类型 FROM 产品设计活动表_管板形式表
    #     WHERE 产品ID = %s
    # """, (product_id,))
    # row = cursor.fetchone()
    #
    # if row and row.get("管板类型") is not None:
    #     tube_bundle["管板类型"] = str(row["管板类型"]).split("_")[0]

    cursor.execute("""
        SELECT 参数值 FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '拉杆' AND 参数名称 = '拉杆型式'
    """, (product_id,))
    row = cursor.fetchone()

    if row and row.get("参数值") is not None:
        tube_bundle["拉杆类型"] = str(row["参数值"])
    conn2 = pymysql.connect(
        host='localhost',
        user='root',
        password='123456',
        database='产品需求库',
        charset='utf8mb4'
    )
    cursor2 = conn2.cursor(pymysql.cursors.DictCursor)
    cursor2.execute("""
        SELECT 产品名称, 产品型式
        FROM 产品需求表
        WHERE 产品ID = %s
    """, (product_id,))
    row = cursor2.fetchone()


    anzuo = {
        "公称直径": "1000",
        "鞍座设计温度": "50",
        "鞍座材料类型": "钢板",
        "鞍座材料牌号": "Q345R",
        "鞍座名义厚度": "100"
    }
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
    # 查询元件材料表中底板（固定鞍座）对应的材料
    cursor.execute("""
        SELECT 材料类型, 材料牌号
        FROM 产品设计活动表_元件材料表
        WHERE 产品ID = %s AND 元件名称 = '腹板（固定鞍座）'
    """, (product_id,))
    row = cursor.fetchone()

    if row:
        anzuo["鞍座材料类型"] = str(row.get("材料类型") or "")
        anzuo["鞍座材料牌号"] = str(row.get("材料牌号") or "")
    else:
        anzuo["鞍座材料类型"] = ""
        anzuo["鞍座材料牌号"] = ""
    jieguan_guanchengrukou = {
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
        "管口表序号": "N1"
    }
    # # === 第一步：查找 N1 管口的材料分类 ===
    # cursor.execute("""
    #     SELECT 材料分类
    #     FROM 产品设计活动表_管口类别表
    #     WHERE 产品ID = %s AND 管口代号 = 'N1'
    #     LIMIT 1
    # """, (product_id,))
    # row = cursor.fetchone()
    # cailiao_fenlei = row["材料分类"].strip() if row and row["材料分类"] else ""
    #
    # if cailiao_fenlei:
    #     # === 第二步：查找该材料分类的管口零件ID ===
    #     cursor.execute("""
    #         SELECT 管口零件ID
    #         FROM 产品设计活动表_管口零件材料表
    #         WHERE 产品ID = %s AND 类别 = %s
    #         LIMIT 1
    #     """, (product_id, cailiao_fenlei))
    #     row = cursor.fetchone()
    #     guankou_lingjian_id = row["管口零件ID"].strip() if row and row["管口零件ID"] else ""
    #
    #     if guankou_lingjian_id:
    #         # === 第三步：查找覆层成型工艺 ===
    #         cursor.execute("""
    #             SELECT 参数值
    #             FROM 产品设计活动表_管口零件材料参数表
    #             WHERE 产品ID = %s AND 类别 = %s AND 管口零件ID = %s AND 参数名称 = '覆层成型工艺'
    #             LIMIT 1
    #         """, (product_id, cailiao_fenlei, guankou_lingjian_id))
    #         row = cursor.fetchone()
    #         if row and row["参数值"] and row["参数值"].strip() not in ("", "None"):
    #             jieguan_guanchengrukou["覆层复合方式"] = row["参数值"].strip()
    #         cursor.execute("""
    #                         SELECT 参数值
    #                         FROM 产品设计活动表_管口零件材料参数表
    #                         WHERE 产品ID = %s AND 类别 = %s AND 管口零件ID = %s AND 参数名称 = '覆层厚度'
    #                         LIMIT 1
    #                     """, (product_id, cailiao_fenlei, guankou_lingjian_id))
    #         row = cursor.fetchone()
    #         if row and row["参数值"] and row["参数值"].strip() not in ("", "None"):
    #             jieguan_guanchengrukou["接管覆层厚度"] = row["参数值"].strip()
    # === 查询工作温度（入口）和（出口）的管程数值 ===
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
        jieguan_guanchengrukou["正常操作工况下操作温度变化范围"] = str(int(delta_temp))
    else:
        jieguan_guanchengrukou["正常操作工况下操作温度变化范围"] = "10"  # 默认值

    # 查询材料信息
    cursor.execute("""
        SELECT 零件名称, 材料类型, 材料牌号
        FROM 产品设计活动表_管口零件材料表
        WHERE 产品ID = %s AND 零件名称 IN ('接管', '接管2', '接管3')
    """, (product_id,))
    material_rows = cursor.fetchall()

    # 建立 映射：零件名称 -> (材料类型, 材料牌号)
    material_map = {
        row["零件名称"]: (row["材料类型"], row["材料牌号"])
        for row in material_rows
    }

    # 更新 jieguan_guanchengrukou 中的材料字段
    for i, part_name in enumerate(["接管", "接管2", "接管3"], start=1):
        mat_type, mat_grade = material_map.get(part_name, ("", ""))
        jieguan_guanchengrukou[f"接管材料类型{i}"] = mat_type
        jieguan_guanchengrukou[f"接管材料牌号{i}"] = mat_grade

    # cursor.execute("""
    #     SELECT 材料类型, 材料牌号
    #     FROM 产品设计活动表_管口零件材料表
    #     WHERE 产品ID = %s AND 零件名称 = '接管'
    # """, (product_id,))
    # row = cursor.fetchone()

    # if row:
    #     if row["材料类型"] is not None:
    #         jieguan_guanchengrukou["接管材料类型"] = row["材料类型"]
    #     if row["材料牌号"] is not None:
    #         jieguan_guanchengrukou["接管材料牌号"] = row["材料牌号"]

    cursor.execute("""
        SELECT 公称尺寸
        FROM 产品设计活动表_管口表
        WHERE 产品ID = %s AND 管口功能 = '管程入口'
        LIMIT 1
    """, (product_id,))
    row = cursor.fetchone()

    if row and row["公称尺寸"] is not None:
        jieguan_guanchengrukou["接管内/外径"] = str(row["公称尺寸"])

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
        jieguan_guanchengrukou["设备公称直径"] = str(param_map["公称直径*"].get("管程数值", ""))
    # 参数映射：数据库参数名 → jieguan_guanchengrukou 字典键名

    jieguan_param_map = {
        "覆层成型工艺": "覆层复合方式",
        "覆层厚度": "接管覆层厚度"
    }

    guankou_daihao = "N1"

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

    # === 获取接管零件ID ===
    cursor.execute("""
        SELECT 管口零件ID
        FROM 产品设计活动表_管口零件材料表
        WHERE 产品ID = %s AND 零件名称 = '接管'
        LIMIT 1
    """, (product_id,))
    row = cursor.fetchone()
    jieguan_part_id = row["管口零件ID"] if row and row["管口零件ID"] not in (None, "", "None") else None
    print(f"✅ 接管零件ID: {jieguan_part_id}")

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

    if "管程" in guankou_gongneng:
        corrosion_param_name = "管程接管腐蚀裕量"
    elif "壳程" in guankou_gongneng:
        corrosion_param_name = "壳程接管腐蚀裕量"
    else:
        corrosion_param_name = None
    print(f"✅ 腐蚀裕量参数名: {corrosion_param_name}")

    material_map = {}



    # === 获取材料分类 ===
    cursor.execute("""
            SELECT 材料分类 
            FROM 产品设计活动表_管口类别表 
            WHERE 产品ID = %s AND 管口代号 = %s
        """, (product_id, guankou_daihao))
    class_rows = cursor.fetchall()
    category = class_rows[0]["材料分类"].strip() if class_rows and class_rows[0].get("材料分类") else None
    use_category_filter = bool(category)
    print("category",category)
    # === 遍历接管/2/3 获取材料参数 ===
    material_map = {}  # 放循环外：存全部接管材料类型/牌号
    param_map_total = {}  # 放循环外：存所有参数（用于后续统一处理）

    for part_name in ["接管", "接管2", "接管3"]:
        # 获取该接管对应的零件 ID
        cursor.execute("""
            SELECT 管口零件ID, 材料类型, 材料牌号
            FROM 产品设计活动表_管口零件材料表 
            WHERE 产品ID = %s AND 零件名称 = %s
        """, (product_id, part_name))
        row = cursor.fetchone()

        part_id = row["管口零件ID"] if row and row.get("管口零件ID") not in (None, "", "None") else None
        material_type = row.get("材料类型", "").strip() if row else ""
        material_grade = row.get("材料牌号", "").strip() if row else ""
        material_map[part_name] = (material_type, material_grade)
        print(f"📌 {part_name} 材料类型: {material_type}, 材料牌号: {material_grade}")

        if not part_id:
            continue

        # 查询其余材料参数
        if use_category_filter:
            cursor.execute("""
                SELECT 参数名称, 参数值 
                FROM 产品设计活动表_管口零件材料参数表 
                WHERE 产品ID = %s AND 管口零件ID = %s AND 类别 = %s
            """, (product_id, part_id, category))
        else:
            cursor.execute("""
                SELECT 参数名称, 参数值 
                FROM 产品设计活动表_管口零件材料参数表 
                WHERE 产品ID = %s AND 管口零件ID = %s
            """, (product_id, part_id))

        rows = cursor.fetchall()
        sub_param_map = {
            r["参数名称"].strip(): str(r["参数值"]).strip()
            for r in rows if r.get("参数名称") and r.get("参数值") not in (None, "", "None")
        }
        param_map_total.update(sub_param_map)
        print(f"📌 {part_name} 参数: {sub_param_map}")

    # ✅ 循环外统一写入材料类型/牌号
    for i, part_name in enumerate(["接管", "接管2", "接管3"], start=1):
        mat_type, mat_grade = material_map.get(part_name, ("", ""))
        jieguan_guanchengrukou[f"接管材料类型{i}"] = mat_type
        jieguan_guanchengrukou[f"接管材料牌号{i}"] = mat_grade
        print(f"✅ 写入接管{i}: 类型={mat_type}, 牌号={mat_grade}")

        # 处理其余参数（统一用 param_map_total）
        has_cover = param_map_total.get("是否添加覆层") == "是"
        print(f"✅ 是否添加覆层: {'是' if has_cover else '否'}")

        if corrosion_param_name:
            corrosion_val = param_map_total.get(corrosion_param_name, "0")
            print(f"✅ 腐蚀裕量值: {corrosion_val}")
            jieguan_guanchengrukou["接管腐蚀余量"] = corrosion_val

        for raw_param, mapped_key in jieguan_param_map.items():
            val = param_map_total.get(raw_param)
            print(f"✅ 参数 {raw_param} → {val}")
            if not has_cover:
                jieguan_guanchengrukou[mapped_key] = "0" if "厚度" in mapped_key else "无"
            else:
                jieguan_guanchengrukou[mapped_key] = val if val else ("0" if "厚度" in mapped_key else "无覆层")

        print(f"\n🟢 最终输出: {jieguan_guanchengrukou}")

    # 映射关系：元件名称 + 字段 → jieguan_guanchengrukou 中的字段
    material_field_map = {
        ("接管补强圈", "材料类型"): "补强圈材料类型",
        ("接管补强圈", "材料牌号"): "补强圈材料牌号"
    }

    cursor.execute("""
        SELECT 零件名称, 材料类型, 材料牌号
        FROM 产品设计活动表_管口零件材料表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()

    for row in rows:
        part_name = (row.get("零件名称") or "").strip()
        material_type = (row.get("材料类型") or "").strip()
        material_grade = (row.get("材料牌号") or "").strip()

        # 接管
        if (part_name, "材料类型") in material_field_map:
            jieguan_guanchengrukou[material_field_map[(part_name, "材料类型")]] = material_type or "0"
        if (part_name, "材料牌号") in material_field_map:
            jieguan_guanchengrukou[material_field_map[(part_name, "材料牌号")]] = material_grade or "0"
    # 查询管口代号为 N1 的记录
    # cursor.execute("""
    #     SELECT `轴向夹角（°）`, `偏心距`
    #     FROM 产品设计活动表_管口表
    #     WHERE 产品ID = %s AND 管口代号 = 'N1'
    # """, (product_id,))
    # row = cursor.fetchone()
    #
    # if row:
    #     try:
    #         angle = float(row.get("轴向夹角（°）") or 0)
    #         offset = float(row.get("偏心距") or 0)
    #     except ValueError:
    #         angle, offset = 0, 0  # 遇到非数字就默认0
    #
    #     # 判断条件：两个都为 0 是类型 1，有一个不为 0 是类型 2
    #     if angle == 0 and offset == 0:
    #         jieguan_guanchengrukou["接管类型"] = "1"
    #     else:
    #         jieguan_guanchengrukou["接管类型"] = "2"
    # else:
    #     jieguan_guanchengrukou["接管类型"] = "1"  # 没查到记录时默认类型 1
    # 查询 N1 管口的偏心距 和 轴向夹角
    cursor.execute("""
        SELECT `偏心距`, `轴向夹角（°）`
        FROM 产品设计活动表_管口表
        WHERE 产品ID = %s AND 管口代号 = 'N1'
    """, (product_id,))
    row = cursor.fetchone()

    if row:
        # 赋值，若为空则默认为 "0"
        jieguan_guanchengrukou["接管中心线至筒体轴线距离(偏心距)"] = str(row.get("偏心距") or "0")
        jieguan_guanchengrukou["接管中心线与法线夹角(包括封头)"] = str(row.get("轴向夹角（°）") or "0")

    # 查询 N1 管口的外伸高度
    cursor.execute("""
        SELECT `外伸高度`
        FROM 产品设计活动表_管口表
        WHERE 产品ID = %s AND 管口代号 = 'N1'
    """, (product_id,))
    row = cursor.fetchone()

    if row:
        jieguan_guanchengrukou["接管实际外伸长度"] = str(row.get("外伸高度") or "0")
    # 如果“接管实际内伸长度”或“接管实际外伸长度”为"默认"，则替换为 "0"
    if jieguan_guanchengrukou.get("接管实际内伸长度") == "默认":
        jieguan_guanchengrukou["接管实际内伸长度"] = "0"

    if jieguan_guanchengrukou.get("接管实际外伸长度") == "默认":
        jieguan_guanchengrukou["接管实际外伸长度"] = "0"

    # 查询 N1 管口的“管口所属元件”
    cursor.execute("""
        SELECT `管口所属元件`
        FROM 产品设计活动表_管口表
        WHERE 产品ID = %s AND 管口代号 = 'N1'
    """, (product_id,))
    row = cursor.fetchone()

    if row:
        jieguan_guanchengrukou["开孔元件名称"] = str(row.get("管口所属元件") or "未知")
    jieguan_guanchengchukou = {
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
        "接管覆层厚度": "0",
        "接管带覆层时的焊接凹槽深度": "0",
        "接管最小有效外伸高度系数": "0.8",
        "焊缝面积A3焊脚高度系数": "0.7",
        "开孔补强自定义补强面积裕量百分比": "0",
        "补强区内的焊缝面积(含嵌入式接管焊缝面积)": "49",
        "补强圈材料类型": "板材",
        "补强圈材料牌号": "Q345R",
        "开孔元件名称": "管箱圆筒",
        "管口表序号": "N2"
    }
    # === 查询工作温度（入口）和（出口）的管程数值 ===
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
        elif name == "工作温度（出口）":
            temp_out = float_val

    # 计算绝对差值并赋值
    if temp_in is not None and temp_out is not None:
        delta_temp = abs(temp_out - temp_in)
        jieguan_guanchengchukou["正常操作工况下操作温度变化范围"] = str(int(delta_temp))
    else:
        jieguan_guanchengchukou["正常操作工况下操作温度变化范围"] = "10"  # 默认值
    # cursor.execute("""
    #     SELECT 材料类型, 材料牌号
    #     FROM 产品设计活动表_管口零件材料表
    #     WHERE 产品ID = %s AND 零件名称 = '接管'
    # """, (product_id,))
    # row = cursor.fetchone()
    #
    # if row:
    #     if row["材料类型"] is not None:
    #         jieguan_guanchengchukou["接管材料类型"] = row["材料类型"]
    #     if row["材料牌号"] is not None:
    #         jieguan_guanchengchukou["接管材料牌号"] = row["材料牌号"]
    cursor.execute("""
           SELECT 零件名称, 材料类型, 材料牌号
           FROM 产品设计活动表_管口零件材料表
           WHERE 产品ID = %s AND 零件名称 IN ('接管', '接管2', '接管3')
       """, (product_id,))
    material_rows = cursor.fetchall()

    # 建立 映射：零件名称 -> (材料类型, 材料牌号)
    material_map = {
        row["零件名称"]: (row["材料类型"], row["材料牌号"])
        for row in material_rows
    }

    # 更新 jieguan_guanchengrukou 中的材料字段
    for i, part_name in enumerate(["接管", "接管2", "接管3"], start=1):
        mat_type, mat_grade = material_map.get(part_name, ("", ""))
        jieguan_guanchengchukou[f"接管材料类型{i}"] = mat_type
        jieguan_guanchengchukou[f"接管材料牌号{i}"] = mat_grade
    cursor.execute("""
        SELECT 公称尺寸
        FROM 产品设计活动表_管口表
        WHERE 产品ID = %s AND 管口功能 = '管程出口'
        LIMIT 1
    """, (product_id,))
    row = cursor.fetchone()

    if row and row["公称尺寸"] is not None:
        jieguan_guanchengchukou["接管内/外径"] = str(row["公称尺寸"])

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
        jieguan_guanchengchukou["设备公称直径"] = str(param_map["公称直径*"].get("管程数值", ""))
    # 参数映射：数据库参数名 → jieguan_guanchengrukou 字典键名
        # === 设置映射 ===
    jieguan_param_map = {
        "覆层成型工艺": "覆层复合方式",
        "覆层厚度": "接管覆层厚度"
    }

    guankou_daihao = "N2"

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

    # === 获取接管零件ID ===
    cursor.execute("""
        SELECT 管口零件ID
        FROM 产品设计活动表_管口零件材料表
        WHERE 产品ID = %s AND 零件名称 = '接管'
        LIMIT 1
    """, (product_id,))
    row = cursor.fetchone()
    jieguan_part_id = row["管口零件ID"] if row and row["管口零件ID"] not in (None, "", "None") else None
    print(f"✅ 接管零件ID: {jieguan_part_id}")

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

    if "管程" in guankou_gongneng:
        corrosion_param_name = "管程接管腐蚀裕量"
    elif "壳程" in guankou_gongneng:
        corrosion_param_name = "壳程接管腐蚀裕量"
    else:
        corrosion_param_name = None
    print(f"✅ 腐蚀裕量参数名: {corrosion_param_name}")

    # === 获取材料分类 ===
    cursor.execute("""
            SELECT 材料分类 
            FROM 产品设计活动表_管口类别表 
            WHERE 产品ID = %s AND 管口代号 = %s
        """, (product_id, guankou_daihao))
    class_rows = cursor.fetchall()
    category = class_rows[0]["材料分类"].strip() if class_rows and class_rows[0].get("材料分类") else None
    use_category_filter = bool(category)
    print("category",category)
    # === 遍历接管/2/3 获取材料参数 ===
    material_map = {}  # 放循环外：存全部接管材料类型/牌号
    param_map_total = {}  # 放循环外：存所有参数（用于后续统一处理）

    for part_name in ["接管", "接管2", "接管3"]:
        # 获取该接管对应的零件 ID
        cursor.execute("""
            SELECT 管口零件ID, 材料类型, 材料牌号
            FROM 产品设计活动表_管口零件材料表 
            WHERE 产品ID = %s AND 零件名称 = %s
        """, (product_id, part_name))
        row = cursor.fetchone()

        part_id = row["管口零件ID"] if row and row.get("管口零件ID") not in (None, "", "None") else None
        material_type = row.get("材料类型", "").strip() if row else ""
        material_grade = row.get("材料牌号", "").strip() if row else ""
        material_map[part_name] = (material_type, material_grade)
        print(f"📌 {part_name} 材料类型: {material_type}, 材料牌号: {material_grade}")

        if not part_id:
            continue

        # 查询其余材料参数
        if use_category_filter:
            cursor.execute("""
                SELECT 参数名称, 参数值 
                FROM 产品设计活动表_管口零件材料参数表 
                WHERE 产品ID = %s AND 管口零件ID = %s AND 类别 = %s
            """, (product_id, part_id, category))
        else:
            cursor.execute("""
                SELECT 参数名称, 参数值 
                FROM 产品设计活动表_管口零件材料参数表 
                WHERE 产品ID = %s AND 管口零件ID = %s
            """, (product_id, part_id))

        rows = cursor.fetchall()
        sub_param_map = {
            r["参数名称"].strip(): str(r["参数值"]).strip()
            for r in rows if r.get("参数名称") and r.get("参数值") not in (None, "", "None")
        }
        param_map_total.update(sub_param_map)
        print(f"📌 {part_name} 参数: {sub_param_map}")

    # ✅ 循环外统一写入材料类型/牌号
    for i, part_name in enumerate(["接管", "接管2", "接管3"], start=1):
        mat_type, mat_grade = material_map.get(part_name, ("", ""))
        jieguan_guanchengchukou[f"接管材料类型{i}"] = mat_type
        jieguan_guanchengchukou[f"接管材料牌号{i}"] = mat_grade
        print(f"✅ 写入接管{i}: 类型={mat_type}, 牌号={mat_grade}")

        # 处理其余参数（统一用 param_map_total）
        has_cover = param_map_total.get("是否添加覆层") == "是"
        print(f"✅ 是否添加覆层: {'是' if has_cover else '否'}")

        if corrosion_param_name:
            corrosion_val = param_map_total.get(corrosion_param_name, "0")
            print(f"✅ 腐蚀裕量值: {corrosion_val}")
            jieguan_guanchengchukou["接管腐蚀余量"] = corrosion_val

        for raw_param, mapped_key in jieguan_param_map.items():
            val = param_map_total.get(raw_param)
            print(f"✅ 参数 {raw_param} → {val}")
            if not has_cover:
                jieguan_guanchengchukou[mapped_key] = "0" if "厚度" in mapped_key else "无"
            else:
                jieguan_guanchengchukou[mapped_key] = val if val else ("0" if "厚度" in mapped_key else "无覆层")

        print(f"\n🟢 最终输出: {jieguan_guanchengchukou}")

    # === 是否添加覆层 ===
    has_cover = param_map.get("是否添加覆层") == "是"
    print(f"✅ 是否添加覆层: {'是' if has_cover else '否'}")

    # === 腐蚀裕量 ===
    if corrosion_param_name:
        corrosion_val = param_map.get(corrosion_param_name, "0")
        print(f"✅ 腐蚀裕量值: {corrosion_val}")
        jieguan_guanchengchukou["接管腐蚀余量"] = corrosion_val

    # === 覆层参数处理 ===
    for raw_param, mapped_key in jieguan_param_map.items():
        val = param_map.get(raw_param)
        print(f"✅ 参数 {raw_param} → {val}")
        if not has_cover:
            jieguan_guanchengchukou[mapped_key] = "0" if "厚度" in mapped_key else "无"
        else:
            jieguan_guanchengchukou[mapped_key] = val if val else ("0" if "厚度" in mapped_key else "无覆层")

    print(f"\n🟢 最终输出: {jieguan_guanchengchukou}")

    # 映射关系：元件名称 + 字段 → jieguan_guanchengrukou 中的字段
    material_field_map = {
        ("接管补强圈", "材料类型"): "补强圈材料类型",
        ("接管补强圈", "材料牌号"): "补强圈材料牌号"
    }

    cursor.execute("""
            SELECT 零件名称, 材料类型, 材料牌号
            FROM 产品设计活动表_管口零件材料表
            WHERE 产品ID = %s
        """, (product_id,))
    rows = cursor.fetchall()

    for row in rows:
        part_name = row.get("零件名称", "").strip()
        material_type = row.get("材料类型", "").strip()
        material_grade = row.get("材料牌号", "").strip()

        # 接管
        if (part_name, "材料类型") in material_field_map:
            jieguan_guanchengchukou[material_field_map[(part_name, "材料类型")]] = material_type or "0"
        if (part_name, "材料牌号") in material_field_map:
            jieguan_guanchengchukou[material_field_map[(part_name, "材料牌号")]] = material_grade or "0"
    # 查询管口代号为 N1 的记录
    # cursor.execute("""
    #         SELECT `轴向夹角（°）`, `偏心距`
    #         FROM 产品设计活动表_管口表
    #         WHERE 产品ID = %s AND 管口代号 = 'N2'
    #     """, (product_id,))
    # row = cursor.fetchone()
    #
    # if row:
    #     try:
    #         angle = float(row.get("轴向夹角（°）") or 0)
    #         offset = float(row.get("偏心距") or 0)
    #     except ValueError:
    #         angle, offset = 0, 0  # 遇到非数字就默认0
    #
    #     # 判断条件：两个都为 0 是类型 1，有一个不为 0 是类型 2
    #     if angle == 0 and offset == 0:
    #         jieguan_guanchengchukou["接管类型"] = "1"
    #     else:
    #         jieguan_guanchengchukou["接管类型"] = "2"
    # else:
    #     jieguan_guanchengchukou["接管类型"] = "1"  # 没查到记录时默认类型 1
    # 查询 N1 管口的偏心距 和 轴向夹角
    cursor.execute("""
            SELECT `偏心距`, `轴向夹角（°）`
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口代号 = 'N2'
        """, (product_id,))
    row = cursor.fetchone()

    if row:
        # 赋值，若为空则默认为 "0"
        jieguan_guanchengchukou["接管中心线至筒体轴线距离(偏心距)"] = str(row.get("偏心距") or "0")
        jieguan_guanchengchukou["接管中心线与法线夹角(包括封头)"] = str(row.get("轴向夹角（°）") or "0")

    # 查询 N1 管口的外伸高度
    cursor.execute("""
            SELECT `外伸高度`
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口代号 = 'N2'
        """, (product_id,))
    row = cursor.fetchone()

    if row:
        raw_value = row.get("外伸高度")
        if raw_value is None or str(raw_value).strip() == "" :
            jieguan_guanchengchukou["接管实际外伸长度"] = "0"
        elif str(raw_value).strip() == "默认":
            pass
        else:
            # 去除小数点后的部分
            int_value = int(float(raw_value))
            jieguan_guanchengchukou["接管实际外伸长度"] = str(int_value)
    # 如果“接管实际内伸长度”或“接管实际外伸长度”为"默认"，则替换为 "0"
    if jieguan_guanchengchukou.get("接管实际内伸长度") == "默认":
        jieguan_guanchengchukou["接管实际内伸长度"] = "0"

    if jieguan_guanchengchukou.get("接管实际外伸长度") == "默认":
        jieguan_guanchengchukou["接管实际外伸长度"] = "0"

    # 查询 N1 管口的“管口所属元件”
    cursor.execute("""
            SELECT `管口所属元件`
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口代号 = 'N2'
        """, (product_id,))
    row = cursor.fetchone()

    if row:
        jieguan_guanchengchukou["开孔元件名称"] = str(row.get("管口所属元件") or "未知")
    jieguan_kechengrukou = {
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
        "接管覆层厚度": "0",
        "接管带覆层时的焊接凹槽深度": "0",
        "接管最小有效外伸高度系数": "0.8",
        "焊缝面积A3焊脚高度系数": "0.7",
        "开孔补强自定义补强面积裕量百分比": "0",
        "补强区内的焊缝面积(含嵌入式接管焊缝面积)": "49",
        "补强圈材料类型": "板材",
        "补强圈材料牌号": "Q345R",
        "开孔元件名称": "管箱圆筒",
        "管口表序号": "N3"
    }
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
        name = row.get("参数名称", "").strip()
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
        jieguan_kechengrukou["正常操作工况下操作温度变化范围"] = str(int(delta_temp))
    else:
        jieguan_kechengrukou["正常操作工况下操作温度变化范围"] = "10"  # 默认值
    # cursor.execute("""
    #     SELECT 材料类型, 材料牌号
    #     FROM 产品设计活动表_管口零件材料表
    #     WHERE 产品ID = %s AND 零件名称 = '接管'
    # """, (product_id,))
    # row = cursor.fetchone()
    #
    # if row:
    #     if row["材料类型"] is not None:
    #         jieguan_kechengrukou["接管材料类型"] = row["材料类型"]
    #     if row["材料牌号"] is not None:
    #         jieguan_kechengrukou["接管材料牌号"] = row["材料牌号"]
    cursor.execute("""
           SELECT 零件名称, 材料类型, 材料牌号
           FROM 产品设计活动表_管口零件材料表
           WHERE 产品ID = %s AND 零件名称 IN ('接管', '接管2', '接管3')
       """, (product_id,))
    material_rows = cursor.fetchall()

    # 建立 映射：零件名称 -> (材料类型, 材料牌号)
    material_map = {
        row["零件名称"]: (row["材料类型"], row["材料牌号"])
        for row in material_rows
    }

    # 更新 jieguan_guanchengrukou 中的材料字段
    for i, part_name in enumerate(["接管", "接管2", "接管3"], start=1):
        mat_type, mat_grade = material_map.get(part_name, ("", ""))
        jieguan_kechengrukou[f"接管材料类型{i}"] = mat_type
        jieguan_kechengrukou[f"接管材料牌号{i}"] = mat_grade
    cursor.execute("""
        SELECT 公称尺寸
        FROM 产品设计活动表_管口表
        WHERE 产品ID = %s AND 管口功能 = '壳程入口'
        LIMIT 1
    """, (product_id,))
    row = cursor.fetchone()

    if row and row["公称尺寸"] is not None:
        jieguan_kechengrukou["接管内/外径"] = str(row["公称尺寸"])

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
        jieguan_kechengrukou["设备公称直径"] = str(param_map["公称直径*"].get("壳程数值", ""))
    # 参数映射：数据库参数名 → jieguan_guanchengrukou 字典键名
    jieguan_param_map = {
        "覆层成型工艺": "覆层复合方式",
        "覆层厚度": "接管覆层厚度"
    }

    guankou_daihao = "N3"

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

    # === 获取接管零件ID ===
    cursor.execute("""
        SELECT 管口零件ID
        FROM 产品设计活动表_管口零件材料表
        WHERE 产品ID = %s AND 零件名称 = '接管'
        LIMIT 1
    """, (product_id,))
    row = cursor.fetchone()
    jieguan_part_id = row["管口零件ID"] if row and row["管口零件ID"] not in (None, "", "None") else None
    print(f"✅ 接管零件ID: {jieguan_part_id}")

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

    if "管程" in guankou_gongneng:
        corrosion_param_name = "管程接管腐蚀裕量"
    elif "壳程" in guankou_gongneng:
        corrosion_param_name = "壳程接管腐蚀裕量"
    else:
        corrosion_param_name = None
    print(f"✅ 腐蚀裕量参数名: {corrosion_param_name}")

    material_map = {}

    # 假设当前管口代号为 N1 或 N2（如传入外层变量 guankou_daihao）
    guankou_daihao = "N3"  # 或 "N2"，根据你的流程控制设置

    # === 获取材料分类 ===
    cursor.execute("""
            SELECT 材料分类 
            FROM 产品设计活动表_管口类别表 
            WHERE 产品ID = %s AND 管口代号 = %s
        """, (product_id, guankou_daihao))
    class_rows = cursor.fetchall()
    category = class_rows[0]["材料分类"].strip() if class_rows and class_rows[0].get("材料分类") else None
    use_category_filter = bool(category)
    print("category",category)
    # === 遍历接管/2/3 获取材料参数 ===
    material_map = {}  # 放循环外：存全部接管材料类型/牌号
    param_map_total = {}  # 放循环外：存所有参数（用于后续统一处理）

    for part_name in ["接管", "接管2", "接管3"]:
        # 获取该接管对应的零件 ID
        cursor.execute("""
            SELECT 管口零件ID, 材料类型, 材料牌号
            FROM 产品设计活动表_管口零件材料表 
            WHERE 产品ID = %s AND 零件名称 = %s
        """, (product_id, part_name))
        row = cursor.fetchone()

        part_id = row["管口零件ID"] if row and row.get("管口零件ID") not in (None, "", "None") else None
        material_type = row.get("材料类型", "").strip() if row else ""
        material_grade = row.get("材料牌号", "").strip() if row else ""
        material_map[part_name] = (material_type, material_grade)
        print(f"📌 {part_name} 材料类型: {material_type}, 材料牌号: {material_grade}")

        if not part_id:
            continue

        # 查询其余材料参数
        if use_category_filter:
            cursor.execute("""
                SELECT 参数名称, 参数值 
                FROM 产品设计活动表_管口零件材料参数表 
                WHERE 产品ID = %s AND 管口零件ID = %s AND 类别 = %s
            """, (product_id, part_id, category))
        else:
            cursor.execute("""
                SELECT 参数名称, 参数值 
                FROM 产品设计活动表_管口零件材料参数表 
                WHERE 产品ID = %s AND 管口零件ID = %s
            """, (product_id, part_id))

        rows = cursor.fetchall()
        sub_param_map = {
            r["参数名称"].strip(): str(r["参数值"]).strip()
            for r in rows if r.get("参数名称") and r.get("参数值") not in (None, "", "None")
        }
        param_map_total.update(sub_param_map)
        print(f"📌 {part_name} 参数: {sub_param_map}")

    # ✅ 循环外统一写入材料类型/牌号
    for i, part_name in enumerate(["接管", "接管2", "接管3"], start=1):
        mat_type, mat_grade = material_map.get(part_name, ("", ""))
        jieguan_kechengrukou[f"接管材料类型{i}"] = mat_type
        jieguan_kechengrukou[f"接管材料牌号{i}"] = mat_grade
        print(f"✅ 写入接管{i}: 类型={mat_type}, 牌号={mat_grade}")

        # 处理其余参数（统一用 param_map_total）
        has_cover = param_map_total.get("是否添加覆层") == "是"
        print(f"✅ 是否添加覆层: {'是' if has_cover else '否'}")

        if corrosion_param_name:
            corrosion_val = param_map_total.get(corrosion_param_name, "0")
            print(f"✅ 腐蚀裕量值: {corrosion_val}")
            jieguan_kechengrukou["接管腐蚀余量"] = corrosion_val

        for raw_param, mapped_key in jieguan_param_map.items():
            val = param_map_total.get(raw_param)
            print(f"✅ 参数 {raw_param} → {val}")
            if not has_cover:
                jieguan_kechengrukou[mapped_key] = "0" if "厚度" in mapped_key else "无"
            else:
                jieguan_kechengrukou[mapped_key] = val if val else ("0" if "厚度" in mapped_key else "无覆层")

        print(f"\n🟢 最终输出: {jieguan_kechengrukou}")

    # === 是否添加覆层 ===
    has_cover = param_map.get("是否添加覆层") == "是"
    print(f"✅ 是否添加覆层: {'是' if has_cover else '否'}")

    # === 腐蚀裕量 ===
    if corrosion_param_name:
        corrosion_val = param_map.get(corrosion_param_name, "0")
        print(f"✅ 腐蚀裕量值: {corrosion_val}")
        jieguan_kechengrukou["接管腐蚀余量"] = corrosion_val

    # === 覆层参数处理 ===
    for raw_param, mapped_key in jieguan_param_map.items():
        val = param_map.get(raw_param)
        print(f"✅ 参数 {raw_param} → {val}")
        if not has_cover:
            jieguan_kechengrukou[mapped_key] = "0" if "厚度" in mapped_key else "无"
        else:
            jieguan_kechengrukou[mapped_key] = val if val else ("0" if "厚度" in mapped_key else "无覆层")

    print(f"\n🟢 最终输出: {jieguan_kechengrukou}")

    # 映射关系：元件名称 + 字段 → jieguan_guanchengrukou 中的字段
    material_field_map = {

        ("接管补强圈", "材料类型"): "补强圈材料类型",
        ("接管补强圈", "材料牌号"): "补强圈材料牌号"
    }

    cursor.execute("""
                    SELECT 零件名称, 材料类型, 材料牌号
                    FROM 产品设计活动表_管口零件材料表
                    WHERE 产品ID = %s
                """, (product_id,))
    rows = cursor.fetchall()

    for row in rows:
        part_name = row.get("零件名称", "").strip()
        material_type = row.get("材料类型", "").strip()
        material_grade = row.get("材料牌号", "").strip()

        # 接管
        if (part_name, "材料类型") in material_field_map:
            jieguan_kechengrukou[material_field_map[(part_name, "材料类型")]] = material_type or "0"
        if (part_name, "材料牌号") in material_field_map:
            jieguan_kechengrukou[material_field_map[(part_name, "材料牌号")]] = material_grade or "0"
    # 查询管口代号为 N1 的记录
    cursor.execute("""
                    SELECT `轴向夹角（°）`, `偏心距`
                    FROM 产品设计活动表_管口表
                    WHERE 产品ID = %s AND 管口代号 = 'N3'
                """, (product_id,))
    row = cursor.fetchone()

    # if row:
    #     try:
    #         angle = float(row.get("轴向夹角（°）") or 0)
    #         offset = float(row.get("偏心距") or 0)
    #     except ValueError:
    #         angle, offset = 0, 0  # 遇到非数字就默认0
    #
    #     # 判断条件：两个都为 0 是类型 1，有一个不为 0 是类型 2
    #     if angle == 0 and offset == 0:
    #         jieguan_kechengrukou["接管类型"] = "1"
    #     else:
    #         jieguan_kechengrukou["接管类型"] = "2"
    # else:
    #     jieguan_kechengrukou["接管类型"] = "1"  # 没查到记录时默认类型 1
    # 查询 N1 管口的偏心距 和 轴向夹角
    cursor.execute("""
                    SELECT `偏心距`, `轴向夹角（°）`
                    FROM 产品设计活动表_管口表
                    WHERE 产品ID = %s AND 管口代号 = 'N3'
                """, (product_id,))
    row = cursor.fetchone()

    if row:
        # 赋值，若为空则默认为 "0"
        jieguan_kechengrukou["接管中心线至筒体轴线距离(偏心距)"] = str(row.get("偏心距") or "0")
        jieguan_kechengrukou["接管中心线与法线夹角(包括封头)"] = str(row.get("轴向夹角（°）") or "0")

    # 查询 N1 管口的外伸高度
    cursor.execute("""
                    SELECT `外伸高度`
                    FROM 产品设计活动表_管口表
                    WHERE 产品ID = %s AND 管口代号 = 'N3'
                """, (product_id,))
    row = cursor.fetchone()

    if row:
        raw_value = row.get("外伸高度")
        if raw_value is None or str(raw_value).strip() == "":
            jieguan_kechengrukou["接管实际外伸长度"] = "0"
        elif str(raw_value).strip() == "默认":
            pass
        else:
            # 去除小数点后的部分
            int_value = int(float(raw_value))
            jieguan_kechengrukou["接管实际外伸长度"] = str(int_value)
    # 如果“接管实际内伸长度”或“接管实际外伸长度”为"默认"，则替换为 "0"
    if jieguan_kechengrukou.get("接管实际内伸长度") == "默认":
        jieguan_kechengrukou["接管实际内伸长度"] = "0"

    if jieguan_kechengrukou.get("接管实际外伸长度") == "默认":
        jieguan_kechengrukou["接管实际外伸长度"] = "0"

    # 查询 N1 管口的“管口所属元件”
    cursor.execute("""
                    SELECT `管口所属元件`
                    FROM 产品设计活动表_管口表
                    WHERE 产品ID = %s AND 管口代号 = 'N3'
                """, (product_id,))
    row = cursor.fetchone()

    if row:
        jieguan_kechengrukou["开孔元件名称"] = str(row.get("管口所属元件") or "未知")
    jieguan_kechengchukou = {
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
        "接管覆层厚度": "0",
        "接管带覆层时的焊接凹槽深度": "0",
        "接管最小有效外伸高度系数": "0.8",
        "焊缝面积A3焊脚高度系数": "0.7",
        "开孔补强自定义补强面积裕量百分比": "0",
        "补强区内的焊缝面积(含嵌入式接管焊缝面积)": "49",
        "补强圈材料类型": "板材",
        "补强圈材料牌号": "Q345R",
        "开孔元件名称": "管箱圆筒",
        "管口表序号": "N4"
    }
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
        name = row.get("参数名称", "").strip()
        value = row.get("管程数值")
        try:
            float_val = float(value) if value not in (None, "", "None") else None
        except:
            float_val = None

        if name == "工作温度（入口）":
            temp_in = float_val
        elif name == "工作温度（出口）":
            temp_out = float_val

    # 计算绝对差值并赋值
    if temp_in is not None and temp_out is not None:
        delta_temp = abs(temp_out - temp_in)
        jieguan_kechengchukou["正常操作工况下操作温度变化范围"] = str(int(delta_temp))
    else:
        jieguan_kechengchukou["正常操作工况下操作温度变化范围"] = "10"  # 默认值
    cursor.execute("""
        SELECT 零件名称, 材料类型, 材料牌号
        FROM 产品设计活动表_管口零件材料表
        WHERE 产品ID = %s AND 零件名称 IN ('接管', '接管2', '接管3')
    """, (product_id,))
    material_rows = cursor.fetchall()

    # 建立 映射：零件名称 -> (材料类型, 材料牌号)
    material_map = {
        row["零件名称"]: (row["材料类型"], row["材料牌号"])
        for row in material_rows
    }

    # 更新 jieguan_guanchengrukou 中的材料字段
    for i, part_name in enumerate(["接管", "接管2", "接管3"], start=1):
        mat_type, mat_grade = material_map.get(part_name, ("", ""))
        jieguan_kechengchukou[f"接管材料类型{i}"] = mat_type
        jieguan_kechengchukou[f"接管材料牌号{i}"] = mat_grade
    # cursor.execute("""
    #     SELECT 材料类型, 材料牌号
    #     FROM 产品设计活动表_管口零件材料表
    #     WHERE 产品ID = %s AND 零件名称 = '接管'
    # """, (product_id,))
    # row = cursor.fetchone()
    #
    # if row:
    #     if row["材料类型"] is not None:
    #         jieguan_kechengchukou["接管材料类型"] = row["材料类型"]
    #     if row["材料牌号"] is not None:
    #         jieguan_kechengchukou["接管材料牌号"] = row["材料牌号"]

    cursor.execute("""
        SELECT 公称尺寸
        FROM 产品设计活动表_管口表
        WHERE 产品ID = %s AND 管口功能 = '壳程出口'
        LIMIT 1
    """, (product_id,))
    row = cursor.fetchone()

    if row and row["公称尺寸"] is not None:
        jieguan_kechengchukou["接管内/外径"] = str(row["公称尺寸"])

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
        jieguan_kechengchukou["设备公称直径"] = str(param_map["公称直径*"].get("壳程数值", ""))
    jieguan_param_map = {
        "覆层成型工艺": "覆层复合方式",
        "覆层厚度": "接管覆层厚度"
    }

    guankou_daihao = "N4"

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

    # === 获取接管零件ID ===
    cursor.execute("""
         SELECT 管口零件ID
         FROM 产品设计活动表_管口零件材料表
         WHERE 产品ID = %s AND 零件名称 = '接管'
         LIMIT 1
     """, (product_id,))
    row = cursor.fetchone()
    jieguan_part_id = row["管口零件ID"] if row and row["管口零件ID"] not in (None, "", "None") else None
    print(f"✅ 接管零件ID: {jieguan_part_id}")

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

    if "管程" in guankou_gongneng:
        corrosion_param_name = "管程接管腐蚀裕量"
    elif "壳程" in guankou_gongneng:
        corrosion_param_name = "壳程接管腐蚀裕量"
    else:
        corrosion_param_name = None
    print(f"✅ 腐蚀裕量参数名: {corrosion_param_name}")

    # 假设当前管口代号为 N1 或 N2（如传入外层变量 guankou_daihao）
    guankou_daihao = "N4"  # 或 "N2"，根据你的流程控制设置

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

    for part_name in ["接管", "接管2", "接管3"]:
        # 获取该接管对应的零件 ID
        cursor.execute("""
            SELECT 管口零件ID, 材料类型, 材料牌号
            FROM 产品设计活动表_管口零件材料表 
            WHERE 产品ID = %s AND 零件名称 = %s
        """, (product_id, part_name))
        row = cursor.fetchone()

        part_id = row["管口零件ID"] if row and row.get("管口零件ID") not in (None, "", "None") else None
        material_type = row.get("材料类型", "").strip() if row else ""
        material_grade = row.get("材料牌号", "").strip() if row else ""
        material_map[part_name] = (material_type, material_grade)
        print(f"📌 {part_name} 材料类型: {material_type}, 材料牌号: {material_grade}")

        if not part_id:
            continue

        # 查询其余材料参数
        if use_category_filter:
            cursor.execute("""
                SELECT 参数名称, 参数值 
                FROM 产品设计活动表_管口零件材料参数表 
                WHERE 产品ID = %s AND 管口零件ID = %s AND 类别 = %s
            """, (product_id, part_id, category))
        else:
            cursor.execute("""
                SELECT 参数名称, 参数值 
                FROM 产品设计活动表_管口零件材料参数表 
                WHERE 产品ID = %s AND 管口零件ID = %s
            """, (product_id, part_id))

        rows = cursor.fetchall()
        sub_param_map = {
            r["参数名称"].strip(): str(r["参数值"]).strip()
            for r in rows if r.get("参数名称") and r.get("参数值") not in (None, "", "None")
        }
        param_map_total.update(sub_param_map)
        print(f"📌 {part_name} 参数: {sub_param_map}")

    # ✅ 循环外统一写入材料类型/牌号
    for i, part_name in enumerate(["接管", "接管2", "接管3"], start=1):
        mat_type, mat_grade = material_map.get(part_name, ("", ""))
        jieguan_kechengchukou[f"接管材料类型{i}"] = mat_type
        jieguan_kechengchukou[f"接管材料牌号{i}"] = mat_grade
        print(f"✅ 写入接管{i}: 类型={mat_type}, 牌号={mat_grade}")

        # 处理其余参数（统一用 param_map_total）
        has_cover = param_map_total.get("是否添加覆层") == "是"
        print(f"✅ 是否添加覆层: {'是' if has_cover else '否'}")

        if corrosion_param_name:
            corrosion_val = param_map_total.get(corrosion_param_name, "0")
            print(f"✅ 腐蚀裕量值: {corrosion_val}")
            jieguan_kechengchukou["接管腐蚀余量"] = corrosion_val

        for raw_param, mapped_key in jieguan_param_map.items():
            val = param_map_total.get(raw_param)
            print(f"✅ 参数 {raw_param} → {val}")
            if not has_cover:
                jieguan_kechengchukou[mapped_key] = "0" if "厚度" in mapped_key else "无"
            else:
                jieguan_kechengchukou[mapped_key] = val if val else ("0" if "厚度" in mapped_key else "无覆层")

        print(f"\n🟢 最终输出: {jieguan_kechengchukou}")

    # === 是否添加覆层 ===
    has_cover = param_map.get("是否添加覆层") == "是"
    print(f"✅ 是否添加覆层: {'是' if has_cover else '否'}")

    # === 腐蚀裕量 ===
    if corrosion_param_name:
        corrosion_val = param_map.get(corrosion_param_name, "0")
        print(f"✅ 腐蚀裕量值: {corrosion_val}")
        jieguan_kechengchukou["接管腐蚀余量"] = corrosion_val

    # === 覆层参数处理 ===
    for raw_param, mapped_key in jieguan_param_map.items():
        val = param_map.get(raw_param)
        print(f"✅ 参数 {raw_param} → {val}")
        if not has_cover:
            jieguan_kechengchukou[mapped_key] = "0" if "厚度" in mapped_key else "无"
        else:
            jieguan_kechengchukou[mapped_key] = val if val else ("0" if "厚度" in mapped_key else "无覆层")

    print(f"\n🟢 最终输出: {jieguan_kechengchukou}")

    # 映射关系：元件名称 + 字段 → jieguan_guanchengrukou 中的字段
    material_field_map = {

        ("接管补强圈", "材料类型"): "补强圈材料类型",
        ("接管补强圈", "材料牌号"): "补强圈材料牌号"
    }

    cursor.execute("""
                SELECT 零件名称, 材料类型, 材料牌号
                FROM 产品设计活动表_管口零件材料表
                WHERE 产品ID = %s
            """, (product_id,))
    rows = cursor.fetchall()

    for row in rows:
        part_name = row.get("零件名称", "").strip()
        material_type = row.get("材料类型", "").strip()
        material_grade = row.get("材料牌号", "").strip()

        # 接管
        if (part_name, "材料类型") in material_field_map:
            jieguan_kechengchukou[material_field_map[(part_name, "材料类型")]] = material_type or "0"
        if (part_name, "材料牌号") in material_field_map:
            jieguan_kechengchukou[material_field_map[(part_name, "材料牌号")]] = material_grade or "0"
    # 查询管口代号为 N1 的记录
    # cursor.execute("""
    #             SELECT `轴向夹角（°）`, `偏心距`
    #             FROM 产品设计活动表_管口表
    #             WHERE 产品ID = %s AND 管口代号 = 'N4'
    #         """, (product_id,))
    # row = cursor.fetchone()

    # if row:
    #     try:
    #         angle = float(row.get("轴向夹角（°）") or 0)
    #         offset = float(row.get("偏心距") or 0)
    #     except ValueError:
    #         angle, offset = 0, 0  # 遇到非数字就默认0
    #
    #     # 判断条件：两个都为 0 是类型 1，有一个不为 0 是类型 2
    #     if angle == 0 and offset == 0:
    #         jieguan_kechengchukou["接管类型"] = "1"
    #     else:
    #         jieguan_kechengchukou["接管类型"] = "2"
    # else:
    #     jieguan_kechengchukou["接管类型"] = "1"  # 没查到记录时默认类型 1
    # 查询 N1 管口的偏心距 和 轴向夹角
    cursor.execute("""
                SELECT `偏心距`, `轴向夹角（°）`
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口代号 = 'N4'
            """, (product_id,))
    row = cursor.fetchone()

    if row:
        # 赋值，若为空则默认为 "0"
        jieguan_kechengchukou["接管中心线至筒体轴线距离(偏心距)"] = str(row.get("偏心距") or "0")
        jieguan_kechengchukou["接管中心线与法线夹角(包括封头)"] = str(row.get("轴向夹角（°）") or "0")

    # 查询 N1 管口的外伸高度
    cursor.execute("""
                SELECT `外伸高度`
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口代号 = 'N4'
            """, (product_id,))
    row = cursor.fetchone()

    if row:
        jieguan_kechengchukou["接管实际外伸长度"] = str(row.get("外伸高度") or "0")
        jieguan_kechengchukou["接管实际内伸长度"] = str(row.get("内伸高度") or "0")

    # 如果“接管实际内伸长度”或“接管实际外伸长度”为"默认"，则替换为 "0"
    if jieguan_kechengchukou.get("接管实际内伸长度") == "默认":
        jieguan_kechengchukou["接管实际内伸长度"] = "0"

    if jieguan_kechengchukou.get("接管实际外伸长度") == "默认":
        jieguan_kechengchukou["接管实际外伸长度"] = "0"

    # 查询 N1 管口的“管口所属元件”
    cursor.execute("""
                SELECT `管口所属元件`
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口代号 = 'N4'
            """, (product_id,))
    row = cursor.fetchone()

    if row:
        jieguan_kechengchukou["开孔元件名称"] = str(row.get("管口所属元件") or "未知")





    result = {
        "WSList": wslist,
        "TTDict": ttdict,
        "DesignParams": design_params,
        "DictPart": dict_part,
        "DictDatas": {
            "管箱封头": guangxiang_fengtou,
            "管箱圆筒": guanxiang_yuantong,
            "管程入口接管": jieguan_guanchengrukou,
            "管程出口接管": jieguan_guanchengchukou,
            "管箱法兰": guanxiang_falan,
            "管箱分程隔板": fencheng_geban,
            "壳体圆筒": qiaoti_yuantong,
            "壳程入口接管": jieguan_kechengrukou,
            "壳程出口接管": jieguan_kechengchukou,
            "壳体法兰": keti_falan,
            "固定管板":guanban_a,
            "管束": tube_bundle,
            "壳体封头": keti_fengtou,
            "鞍座": anzuo,
        }
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

    with open("result_qiangdujisuan_new.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)

    # 获取当前脚本所在的绝对路径
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # 构造 DLL 文件的相对路径
    dll_path = os.path.join(base_dir, 'CalCulationPartLib.dll')

    # print("当前脚本路径：", base_dir)
    # print("构造的 DLL 路径：", dll_path)
    # print("DLL 文件是否存在：", os.path.exists(dll_path))

    clr.AddReference("CalCulationPartLib")  # 不加 .dll 后缀
    from CalCulationPartLib import CalPartInterface
    # # 读取JSON文件并转换为紧凑格式
    with open("result_qiangdujisuan_new.json", "r", encoding="utf-8") as f:
        json_input = f.read()
    parsed = json.loads(json_input)
    compact_json = json.dumps(parsed, separators=(',', ':'))

    cpi = CalPartInterface()
    calculation_result = cpi.IntergratedEquipment(compact_json)

    # 保存计算结果
    # with open("modules/qiangdujisuan/jiekou_python/jisuan_output.json", "w", encoding="utf-8") as f:
    with open("jisuan_output_new.json", "w", encoding="utf-8") as f:
        json.dump(json.loads(calculation_result), f, ensure_ascii=False, indent=4)
    return calculation_result

if __name__ == "__main__":
    product_id = 'PD20250704007'
    # product_id = 'PD20250706001'  # 替换为你自己的产品ID
    result = calculate_heat_exchanger_strength(product_id)
    print(result)