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
        "设计压力*[工况2]": ("ShellWorkingPressure", "TubeWorkingPressure"),
        "设计温度（最高）*[工况2]": ("ShellWorkingTemperature", "TubeWorkingTemperature"),
    }

    # 填写数据
    for row in rows:
        param = row["参数名称"].strip()
        shell_val, tube_val = row["壳程数值"], row["管程数值"]
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
        raw_attach = clean_value(row.get("管口所属元件"))

        if raw_attach in ("前端管箱圆筒",):
            ttAttach = "管箱圆筒"
        elif raw_attach in ("前端管箱平盖"):
            ttAttach = "管箱平盖"
        elif raw_attach in ("前端管箱封头"):
            ttAttach = "管箱封头"
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
            "ttType": clean_value(row.get("法兰型式")),
            "ttRF": clean_value(row.get("密封面型式")),
            "ttSpec": "默认" if clean_value(row.get("焊端规格")) == "程序推荐" else clean_value(row.get("焊端规格")),
            "ttAttach": ttAttach,
            "ttPlace": {
                "左基准线": "左轮廓线",
                "右基准线": "右轮廓线"
            }.get(row.get("轴向定位基准", ""), clean_value(row.get("轴向定位基准"))),
            "ttLoc": "默认" if clean_value(row.get("轴向定位距离")) in("程序推荐","-","")  else clean_value(
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
        "管/壳程布置型式":"2.1",
        "大端公称直径": "1000",
        "锥壳大端与圆筒连接处是否作为支撑线":"否",
        "锥壳小端与圆筒连接处是否作为支撑线": "否",
        "设备类型": "卧式设备",
        "打压方式": "卧式打压"
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
            design_params["管/壳程布置型式"] ="2.1"
        # === 查询设计数据表 ===
        cursor.execute("""
            SELECT 参数名称, 壳程数值, 管程数值
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s
        """, (product_id,))
        rows = cursor.fetchall()
        param_map = {row["参数名称"].strip(): row for row in rows}


        # 公称直径（管程）
        if "公称直径*" in param_map:
            design_params["公称直径"] = str(param_map["公称直径*"].get("管程数值", ""))
            design_params["大端公称直径"] = str(param_map["公称直径*"].get("管程数值", ""))

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
            tube_expl = param_map["介质特性（爆炸危险程度）"].get("管程数值", "-")
            if tube_expl != "":
                media_parts.append(tube_expl)
        if "介质特性（毒性危害程度）" in param_map:
            shell_toxic = param_map["介质特性（毒性危害程度）"].get("壳程数值", "")
            if shell_toxic != "":
                media_parts.append(shell_toxic)
            tube_toxic = param_map["介质特性（毒性危害程度）"].get("管程数值", "-")
            if tube_toxic == "":
                media_parts.append(tube_toxic)
        if "介质特性（是否液化气体）" in param_map:
            shell_ox = param_map["介质特性（是否液化气体）"].get("壳程数值", "-")
            if shell_ox == "":
                media_parts.append(shell_ox)
            tube_ox = param_map["介质特性（是否液化气体）"].get("管程数值", "-")
            if tube_ox == "":
                media_parts.append(tube_ox)
        if media_parts:
            design_params["介质类型"] = "/".join(media_parts)
        else:
            design_params["介质类型"] = "0"
    except Exception as e:
        print(f" 查询失败: {e}")


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
        "管箱平盖": "法兰",
        "头盖法兰": "法兰",
        "管箱圆筒": "筒体",
        "管箱法兰": "法兰",
        "管箱分程隔板": "分程隔板",
        "壳体端部圆筒1": "筒体",
        "壳体圆筒": "筒体",
        "壳体端部圆筒2": "筒体",
        "固定管板": "e型管板",
        "管束": "BEM管束",
        "后端管箱圆筒": "筒体",
        "后端管箱封头": "椭圆形封头",
        "吊耳": "吊耳",
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
        "法兰名义内径": "0",
        "法兰名义外径": "0",
        "法兰名义厚度": "65",
        "法兰颈部高度": "35",
        "覆层厚度": "0",
        "管程还是壳程": "管程",
        "法兰为夹持法兰": "是",
        "法兰位置": "头盖法兰",
        "圆筒名义厚度": "10",
        "圆筒有效厚度": "8",
        "圆筒名义内径": "0",
        "圆筒名义外径": "0",
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
        "是否带分程隔板":"false",
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
        "介质情况": "毒性",
        "垫片标准号": "GB/T 29463-2023",
        "垫片实际密封宽度": "0",
        "管程侧分程隔板槽宽度": "",
        "壳程侧分程隔板槽宽度": "2",
        "介质类型":"",
        "管程程数":"",
        "管板形式":"",
        "螺栓根径类型": "",
        "x轴向弯矩": "",
        "y轴向弯矩": "",
        "径向载荷": "",
        "螺栓的有效长度": "",
        "螺栓螺母和螺母法兰面之间的总摩擦系数": "",
        "垫片材料弹性模量": "",
        "管前左法兰密封面高度": "0",
        "壳后右法兰密封面高度": "0",
        "覆层材料牌号管前左": "0",
        "覆层材料牌号壳后右": "0"

    }
    cursor.execute("""
            SELECT 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s
              AND 元件名称 = '前端管箱平盖'
              AND 参数名称 = '密封面高度'
        """, (product_id,))

    row = cursor.fetchone()
    if row:
        tougai_falan["管前左法兰密封面高度"] = safe_str(row.get("参数值"))
    cursor.execute("""
            SELECT 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s
              AND 元件名称 = '前端管箱头盖法兰'
              AND 参数名称 = '密封面高度'
        """, (product_id,))

    row = cursor.fetchone()
    if row:
        tougai_falan["壳后右法兰密封面高度"] = safe_str(row.get("参数值"))
    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s
          AND 元件名称 = '平盖垫片'
          AND 参数名称 = '压紧面形状'
    """, (product_id,))

    row = cursor.fetchone()
    if row:
        tougai_falan["压紧面形状序号"] = safe_str(row.get("参数值"))
    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '平盖垫片' AND 参数名称 = '垫片厚度'
    """, (product_id,))
    row = cursor.fetchone()
    val = row["参数值"] if row and row["参数值"] not in (None, "", "None") else "4.5"
    tougai_falan["垫片厚度"] = str(val)
    current_component = "前端管箱平盖"  # 也可以是 "外头盖法兰"、"浮头法兰"
    cursor.execute("""
            SELECT 参数值
            FROM 产品设计活动表_元件附加参数合并表
            WHERE 产品ID = %s
              AND 参数名称 = '螺柱根径系列1'
              AND Tab分类 = (
                    SELECT Tab分类
                    FROM 产品设计活动表_元件附加参数合并表
                    WHERE 产品ID = %s
                      AND 参数名称 = '元件所属'
                      AND FIND_IN_SET(%s, REPLACE(参数值, '、', ',')) > 0
                    LIMIT 1
              )
            LIMIT 1
        """, (product_id, product_id, current_component))

    row = cursor.fetchone()
    if row:
        tougai_falan["螺栓根径类型"] = safe_str(row.get("参数值") if isinstance(row, dict) else row[0])
    sheji_param = {
        "法兰材料腐蚀裕量": ("腐蚀裕量*", "管程数值"),
        "法兰材料腐蚀裕量管前左": ("腐蚀裕量*", "管程数值"),
        "法兰材料腐蚀裕量壳后右": ("腐蚀裕量*", "管程数值"),
        "公称直径管前左": ("公称直径*", "管程数值"),
        "公称直径壳后右": ("公称直径*", "壳程数值"),
        "纵向焊接接头系数": ("焊接接头系数*", "管程数值"),
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
        tougai_falan[field] = safe_str(val)

    # ========== 液柱静压力 和 介质密度 ==========
    if "液柱静压力" in param_map:
        tougai_falan["壳程液柱静压力"] = safe_str(param_map["液柱静压力"].get("壳程数值"))
        tougai_falan["管程液柱静压力"] = safe_str(param_map["液柱静压力"].get("管程数值"))
    if "介质密度" in param_map:
        tougai_falan["壳程液柱密度"] = safe_str(param_map["介质密度"].get("壳程数值"))
        tougai_falan["管程液柱密度"] = safe_str(param_map["介质密度"].get("管程数值"))
    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s
          AND 元件名称 = '前端管箱头盖法兰'
          AND 参数名称 = '法兰类型'
    """, (product_id,))

    row = cursor.fetchone()
    if row:
        tougai_falan["法兰种类"] = safe_str(row.get("参数值"))

    sql = """
        SELECT 管板类型
        FROM 产品设计活动表_管板形式表
        WHERE 产品ID = %s
        LIMIT 1
    """
    cursor.execute(sql, (product_id,))
    row = cursor.fetchone()
    if row:
        tougai_falan["管板形式"] = str(row["管板类型"])[0]  # 取第一个字母

    cursor.execute("""
               SELECT 参数值 
               FROM 产品设计活动表_布管参数表
               WHERE 产品ID = %s AND 参数名 = '管程程数'
               LIMIT 1
           """, (product_id,))
    row = cursor.fetchone()
    tube_passes1 = row["参数值"].strip() if row and row.get("参数值") else ""
    tougai_falan["管程程数"] = tube_passes1
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
        shell_expl = param_map["介质特性（爆炸危险程度）"].get("壳程数值", "-")
        if shell_expl == "":
            shell_expl = "-"
        media_parts.append(shell_expl)
        tube_expl = param_map["介质特性（爆炸危险程度）"].get("管程数值", "-")
        if tube_expl == "":
            tube_expl = "-"
        media_parts.append(tube_expl)
    if "介质特性（毒性危害程度）" in param_map:
        shell_toxic = param_map["介质特性（毒性危害程度）"].get("壳程数值", "")
        if shell_toxic == "":
            shell_toxic = "-"
        media_parts.append(shell_toxic)
        tube_toxic = param_map["介质特性（毒性危害程度）"].get("管程数值", "-")
        if tube_toxic == "":
            tube_toxic = "-"
        media_parts.append(tube_toxic)
    if "介质特性（是否液化气体）" in param_map:
        shell_ox = param_map["介质特性（是否液化气体）"].get("壳程数值", "-")
        if shell_ox == "":
            shell_ox = "-"
        media_parts.append(shell_ox)
        tube_ox = param_map["介质特性（是否液化气体）"].get("管程数值", "-")
        if tube_ox == "":
            tube_ox = "-"
        media_parts.append(tube_ox)

    if media_parts:
        tougai_falan["介质类型"] = "/".join(media_parts)
    else:
        tougai_falan["介质类型"] = "0"
    # === 查询管程分程形式 ===
    cursor.execute("""
                       SELECT 参数值 
                       FROM 产品设计活动表_布管参数表
                       WHERE 产品ID = %s AND 参数名 = '管程分程形式'
                       LIMIT 1
                   """, (product_id,))
    row = cursor.fetchone()
    tube_form = row["参数值"].strip() if row and row.get("参数值") else None
    if tube_form == '2':
        tube_form = '2.1'
    tougai_falan["垫片代号"] = tube_form
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '固定管板'
        """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    tougai_falan["管程侧分程隔板槽宽度"] = row_map.get("管程侧分程隔板槽宽度", "0")
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '固定管板'
        """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    tougai_falan["壳程侧分程隔板槽宽度"] = row_map.get("壳程侧分程隔板槽宽度", "0")
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
        tube_toxic = param_map["介质特性（毒性危害程度）"].get("管程数值", "-")
        if shell_toxic:
            media_parts.append(f"{shell_toxic}危害")
        if tube_toxic:
            media_parts.append(f"{tube_toxic}危害")

    if media_parts:
        tougai_falan["介质情况"] = "/".join(media_parts)
    cursor.execute("""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = '前端管箱平盖'
            """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    tougai_falan["法兰材料类型管前左"] = row_map.get("材料类型", "0")
    tougai_falan["法兰材料牌号管前左"] = row_map.get("材料牌号", "0")
    cursor.execute("""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = '前端管箱头盖法兰'
            """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    tougai_falan["法兰材料类型壳后右"] = row_map.get("材料类型", "0")
    tougai_falan["法兰材料牌号壳后右"] = row_map.get("材料牌号", "0")
    # === 获取“管箱圆筒”对接元件材料信息 ===
    cursor.execute("""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
            """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    tougai_falan["对接元件管前左材料类型"] = row_map.get("材料类型", "0")
    tougai_falan["对接元件管前左材料牌号"] = row_map.get("材料牌号", "0")

    # === 获取“壳体圆筒”对接元件材料信息 ===
    cursor.execute("""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
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

    # guanxiang_pinggai["圆筒名义内径"] = row_map.get("内径", "0")
    # guanxiang_pinggai["圆筒名义外径"] = row_map.get("外径", "0")
    tougai_falan["圆筒材料类型"] = row_map.get("材料类型", "0")
    tougai_falan["圆筒材料牌号"] = row_map.get("材料牌号", "0")
    # === 管箱圆筒 ===
    cursor.execute("""
               SELECT 参数名称, 参数值
               FROM 产品设计活动表_元件附加参数表
               WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
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
               WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
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
                   WHERE 产品ID = %s AND 元件名称 = '前端管箱头盖法兰'
               """, (product_id,))
    rows = cursor.fetchall()
    qt_data = {row["参数名称"]: str(row["参数值"]).strip() for row in rows if row["参数值"] not in (None, "", "None")}

    if qt_data.get("是否添加覆层") == "是":
        tougai_falan["覆层厚度壳后右"] = qt_data.get("覆层厚度", "0")
        tougai_falan["覆层材料牌号壳后右"] = qt_data.get("覆层材料牌号", "0")
        tougai_falan["覆层厚度"] = qt_data.get("覆层厚度", "0")

        # guanxiang_falan["对接元件覆层复合方式壳后右"] = qt_data.get("覆层成型工艺", "")
    else:
        tougai_falan["覆层厚度壳后右"] = "0"
        tougai_falan["覆层厚度"] = "0"

    cursor.execute("""
                   SELECT 参数名称, 参数值
                   FROM 产品设计活动表_元件附加参数表
                   WHERE 产品ID = %s AND 元件名称 = '前端管箱平盖'
               """, (product_id,))
    rows = cursor.fetchall()
    qt_data = {row["参数名称"]: str(row["参数值"]).strip() for row in rows if row["参数值"] not in (None, "", "None")}

    if qt_data.get("是否添加覆层") == "是":
        tougai_falan["覆层厚度管前左"] = qt_data.get("覆层厚度", "0")
        tougai_falan["覆层材料牌号管前左"] = qt_data.get("覆层材料牌号", "0")
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
            val11 = str(float(raw_val)) if raw_val not in (None, "", " ", "None","程序推荐") else "0"
        except ValueError:
            val11 = "0"
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
        print(f" 查询失败: {e}")



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
        WHERE 产品ID = %s
          AND 元件名称 = '前端管箱平盖垫片'
          AND 参数名称 IN ('垫片名义外径D2n','垫片名义内径D1n')
    """, (product_id,))

    rows = cursor.fetchall()
    if rows:
        params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}
        tougai_falan["垫片名义外径"] = params.get("垫片名义外径D2n", "")
        if tougai_falan["垫片名义外径"] in ("程序推荐", ""):
            tougai_falan["垫片名义外径"] = "0"

        tougai_falan["垫片名义内径"] = params.get("垫片名义内径D1n", "")
        if tougai_falan["垫片名义内径"] in ("程序推荐", ""):
            tougai_falan["垫片名义内径"] = "0"

    # 法兰材料类型
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '前端管箱头盖法兰'
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
        ("前端管箱头盖法兰", "轴向拉伸载荷"): "轴向外力",
        ("前端管箱头盖法兰", "附加弯矩"): "外力矩",
        # ("壳体法兰", "法兰类型"): "法兰类型壳后右",
        ("前端管箱头盖法兰", "材料类型"): "法兰材料类型壳后右",
        ("前端管箱头盖法兰", "材料牌号"): "法兰材料牌号壳后右",
        # ("壳体法兰", "覆层厚度"): "覆层厚度壳后右",
        # ("前端管箱法兰", "覆层厚度"): "覆层厚度管前左",
        ("管箱圆筒", "材料类型"): "圆筒材料类型",
        ("管箱圆筒", "材料牌号"): "圆筒材料牌号",
        # ("前端管箱法兰", "法兰类型"): "法兰类型管前左",
        ("前端管箱平盖", "材料类型"): "法兰材料类型管前左",
        ("前端管箱平盖", "材料牌号"): "法兰材料牌号管前左",
        ("前端管箱平盖", "平盖类型"): "平盖序号",
        ("螺柱（前端管箱平盖）", "材料牌号"): "螺栓材料牌号",
        ("前端管箱平盖垫片", "垫片材料"): "垫片材料牌号",
        ("前端管箱平盖垫片", "垫片标准"): "垫片标准号",

        ("前端管箱平盖垫片", "垫片系数m"): "m",
        ("前端管箱平盖垫片", "垫片比压力y"): "y",

    }
    special_force_fields = {"轴向拉伸载荷", "附加弯矩"}

    for (comp, param), field in yuanjian_param.items():

        # =========================================================
        # ✅ 特殊逻辑：螺柱（前端管箱平盖）的材料牌号 → 去合并表找
        # =========================================================
        if comp == "螺柱（前端管箱平盖）" and param == "材料牌号" and field == "螺栓材料牌号":
            val, hit_tab, hit_cid = get_fastener_bolt_material_by_belong(
                cursor, product_id, belong_keyword="前端管箱平盖", is_stud=True
            )
            val = val or ""  # 没找到就空，后面 apply_special_defaults 会兜底（若你有默认）
            # 可选：调试用
            # print(f"[DEBUG] 前端管箱平盖螺柱材料牌号命中: {val}, tab={hit_tab}, 元件ID={hit_cid}")

        else:
            # ===== 原有逻辑：从 component_map 取值 =====
            val = component_map.get(comp, {}).get(param, "")

        # ===== 原有清洗逻辑保持不变 =====
        val = str(val).strip() if val is not None else ""
        if val.lower() == "none":
            val = ""
        if param in special_force_fields and val == "":
            val = "0"
        if field == "m":
            try:
                val = str(float(val))
            except:
                val = "3"

        tougai_falan[field] = apply_special_defaults(field, val)
    guanxiang_pinggai = {
        "管程侧分程隔板槽宽度": "",
        "壳程侧分程隔板槽宽度": "2",

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
        "法兰位置": "管箱平盖",
        "圆筒名义厚度": "10",
        "圆筒有效厚度": "8",
        "圆筒名义内径": "0",
        "圆筒名义外径": "0",
        "圆筒材料类型": "",
        "圆筒材料牌号": "",
        "焊缝高度": "0",
        "焊缝长度": "0",
        "焊缝深度": "0",
        "法兰种类": "整体法兰2",
        "介质情况": "毒性",
        "公称直径管前左": "",
        "公称直径壳后右": "",
        "对接元件管前左材料类型": "无",
        "对接元件壳后右材料类型": "",
        "对接元件管前左材料牌号": "无",
        "对接元件壳后右材料牌号": "",
        "是否带分程隔板管前左": "是",
        "是否带分程隔板壳后右": "是",
        "法兰类型管前左": "整体法兰2",
        "是否带分程隔板":"false",
        "法兰材料类型管前左": "",
        "法兰材料牌号管前左": "16Mn",
        "法兰材料腐蚀裕量管前左": 0,
        "法兰类型壳后右": "整体法兰2",
        "法兰材料类型壳后右": "整体法兰2",
        "法兰材料牌号壳后右": "16Mn",
        "法兰材料腐蚀裕量壳后右": "3",
        "覆层厚度管前左": "0",
        "覆层厚度壳后右": "0",
        "对接元件覆层厚度管前左": "0",
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
        "介质类型":"",
        "管程程数":"",
        "管板形式":"",
        "螺栓根径类型": "",
        "管前左法兰密封面高度": "0",
        "壳后右法兰密封面高度": "0",
        "覆层材料牌号管前左": "0",
        "覆层材料牌号壳后右": "0"

    }
    cursor.execute("""
            SELECT 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s
              AND 元件名称 = '前端管箱平盖'
              AND 参数名称 = '密封面高度'
        """, (product_id,))

    row = cursor.fetchone()
    if row:
        guanxiang_pinggai["管前左法兰密封面高度"] = safe_str(row.get("参数值"))
    cursor.execute("""
            SELECT 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s
              AND 元件名称 = '前端管箱头盖法兰'
              AND 参数名称 = '密封面高度'
        """, (product_id,))

    row = cursor.fetchone()
    if row:
        guanxiang_pinggai["壳后右法兰密封面高度"] = safe_str(row.get("参数值"))
    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s
          AND 元件名称 = '平盖垫片'
          AND 参数名称 = '压紧面形状'
    """, (product_id,))

    row = cursor.fetchone()
    if row:
        guanxiang_pinggai["压紧面形状序号"] = safe_str(row.get("参数值"))
    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '平盖垫片' AND 参数名称 = '垫片厚度'
    """, (product_id,))
    row = cursor.fetchone()
    val = row["参数值"] if row and row["参数值"] not in (None, "", "None") else "4.5"
    guanxiang_pinggai["垫片厚度"] = str(val)
    current_component = "前端管箱平盖"  # 也可以是 "外头盖法兰"、"浮头法兰"
    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数合并表
        WHERE 产品ID = %s
          AND 参数名称 = '螺柱根径系列1'
          AND Tab分类 = (
                SELECT Tab分类
                FROM 产品设计活动表_元件附加参数合并表
                WHERE 产品ID = %s
                  AND 参数名称 = '元件所属'
                  AND FIND_IN_SET(%s, REPLACE(参数值, '、', ',')) > 0
                LIMIT 1
          )
        LIMIT 1
    """, (product_id, product_id, current_component))

    row = cursor.fetchone()
    if row:
        guanxiang_pinggai["螺栓根径类型"] = safe_str(row.get("参数值") if isinstance(row, dict) else row[0])

    row = cursor.fetchone()
    if row:
        guanxiang_pinggai["螺栓根径类型"] = safe_str(row.get("参数值"))
    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s
          AND 元件名称 = '前端管箱头盖法兰'
          AND 参数名称 = '法兰类型'
    """, (product_id,))

    row = cursor.fetchone()
    if row:
        guanxiang_pinggai["法兰种类"] = safe_str(row.get("参数值"))

    sql = """
        SELECT 管板类型
        FROM 产品设计活动表_管板形式表
        WHERE 产品ID = %s
        LIMIT 1
    """
    cursor.execute(sql, (product_id,))
    row = cursor.fetchone()
    if row:
        guanxiang_pinggai["管板形式"] = str(row["管板类型"])[0]  # 取第一个字母

    cursor.execute("""
               SELECT 参数值 
               FROM 产品设计活动表_布管参数表
               WHERE 产品ID = %s AND 参数名 = '管程程数'
               LIMIT 1
           """, (product_id,))
    row = cursor.fetchone()
    tube_passes1 = row["参数值"].strip() if row and row.get("参数值") else ""
    guanxiang_pinggai["管程程数"] = tube_passes1
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
        shell_expl = param_map["介质特性（爆炸危险程度）"].get("壳程数值", "-")
        if shell_expl == "":
            shell_expl = "-"
        media_parts.append(shell_expl)
        tube_expl = param_map["介质特性（爆炸危险程度）"].get("管程数值", "-")
        if tube_expl == "":
            tube_expl = "-"
        media_parts.append(tube_expl)
    if "介质特性（毒性危害程度）" in param_map:
        shell_toxic = param_map["介质特性（毒性危害程度）"].get("壳程数值", "")
        if shell_toxic == "":
            shell_toxic = "-"
        media_parts.append(shell_toxic)
        tube_toxic = param_map["介质特性（毒性危害程度）"].get("管程数值", "-")
        if tube_toxic == "":
            tube_toxic = "-"
        media_parts.append(tube_toxic)
    if "介质特性（是否液化气体）" in param_map:
        shell_ox = param_map["介质特性（是否液化气体）"].get("壳程数值", "-")
        if shell_ox == "":
            shell_ox = "-"
        media_parts.append(shell_ox)
        tube_ox = param_map["介质特性（是否液化气体）"].get("管程数值", "-")
        if tube_ox == "":
            tube_ox = "-"
        media_parts.append(tube_ox)

    if media_parts:
        guanxiang_pinggai["介质类型"] = "/".join(media_parts)
    else:
        guanxiang_pinggai["介质类型"] = "0"

    # === 查询管程分程形式 ==
    # =
    cursor.execute("""
                       SELECT 参数值 
                       FROM 产品设计活动表_布管参数表
                       WHERE 产品ID = %s AND 参数名 = '管程分程形式'
                       LIMIT 1
                   """, (product_id,))
    row = cursor.fetchone()
    tube_form = row["参数值"].strip() if row and row.get("参数值") else None
    if tube_form == '2':
        tube_form = '2.1'
    guanxiang_pinggai["垫片代号"] = tube_form
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '固定管板'
        """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    guanxiang_pinggai["管程侧分程隔板槽宽度"] = row_map.get("管程侧分程隔板槽宽度", "0")
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '固定管板'
        """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    guanxiang_pinggai["壳程侧分程隔板槽宽度"] = row_map.get("壳程侧分程隔板槽宽度", "0")
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
        tube_toxic = param_map["介质特性（毒性危害程度）"].get("管程数值", "-")
        if shell_toxic:
            media_parts.append(f"{shell_toxic}危害")
        if tube_toxic:
            media_parts.append(f"{tube_toxic}危害")

    if media_parts:
        guanxiang_pinggai["介质情况"] = "/".join(media_parts)
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s
          AND 元件名称 = '前端管箱平盖垫片'
          AND 参数名称 IN ('垫片名义外径D2n','垫片名义内径D1n')
    """, (product_id,))

    rows = cursor.fetchall()
    if rows:
        params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}
        guanxiang_pinggai["垫片名义外径"] = params.get("垫片名义外径D2n", "")
        if guanxiang_pinggai["垫片名义外径"] in ("程序推荐", ""):
            guanxiang_pinggai["垫片名义外径"] = "0"

        guanxiang_pinggai["垫片名义内径"] = params.get("垫片名义内径D1n", "")
        if guanxiang_pinggai["垫片名义内径"] in ("程序推荐", ""):
            guanxiang_pinggai["垫片名义内径"] = "0"

    # === 获取“管箱圆筒”对接元件材料信息 ===
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
    """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    guanxiang_pinggai["对接元件管前左材料类型"] = row_map.get("材料类型", "0")
    guanxiang_pinggai["对接元件管前左材料牌号"] = row_map.get("材料牌号", "0")

    # === 获取“壳体圆筒”对接元件材料信息 ===
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
    """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    guanxiang_pinggai["对接元件壳后右材料类型"] = row_map.get("材料类型", "0")
    guanxiang_pinggai["对接元件壳后右材料牌号"] = row_map.get("材料牌号", "0")

    # === 获取“管箱圆筒”的圆筒相关参数 ===
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
    """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    # guanxiang_pinggai["圆筒名义内径"] = row_map.get("内径", "0")
    # guanxiang_pinggai["圆筒名义外径"] = row_map.get("外径", "0")
    guanxiang_pinggai["圆筒材料类型"] = row_map.get("材料类型", "0")
    guanxiang_pinggai["圆筒材料牌号"] = row_map.get("材料牌号", "0")
       # === 壳体圆筒 ===
    cursor.execute("""
           SELECT 参数名称, 参数值
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s AND 元件名称 = '前端管箱头盖法兰'
       """, (product_id,))
    rows = cursor.fetchall()
    qt_data = {row["参数名称"]: str(row["参数值"]).strip() for row in rows if row["参数值"] not in (None, "", "None")}

    if qt_data.get("是否添加覆层") == "是":
        guanxiang_pinggai["覆层厚度壳后右"] = qt_data.get("覆层厚度", "0")
        guanxiang_pinggai["覆层材料牌号壳后右"] = qt_data.get("覆层材料牌号度", "0")        # guanxiang_falan["对接元件覆层复合方式壳后右"] = qt_data.get("覆层成型工艺", "")
    else:
        guanxiang_pinggai["覆层厚度壳后右"] = "0"
        # guanxiang_falan["对接元件覆层复合方式壳后右"] = ""
    cursor.execute("""
               SELECT 参数名称, 参数值
               FROM 产品设计活动表_元件附加参数表
               WHERE 产品ID = %s AND 元件名称 = '前端管箱平盖'
           """, (product_id,))
    rows = cursor.fetchall()
    qt_data = {row["参数名称"]: str(row["参数值"]).strip() for row in rows if row["参数值"] not in (None, "", "None")}

    if qt_data.get("是否添加覆层") == "是":
        guanxiang_pinggai["覆层厚度管前左"] = qt_data.get("覆层厚度", "0")
        guanxiang_pinggai["覆层材料牌号管前左"] = qt_data.get("覆层材料牌号", "0")
        guanxiang_pinggai["覆层厚度"] = qt_data.get("覆层厚度", "0")

        # guanxiang_falan["对接元件覆层复合方式壳后右"] = qt_data.get("覆层成型工艺", "")
    else:
        guanxiang_pinggai["覆层厚度管前左"] = "0"
        guanxiang_pinggai["覆层厚度"] = "0"

        # guanxiang_falan["对接元件覆层复合方式壳后右"] = ""
    # # ========== 查询管箱圆筒的覆层厚度 ==========
    cursor.execute("""
               SELECT 参数名称, 参数值
               FROM 产品设计活动表_元件附加参数表
               WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
           """, (product_id,))
    rows = cursor.fetchall()
    gx_data = {row["参数名称"]: str(row["参数值"]).strip() for row in rows if row["参数值"] not in (None, "", "None")}

    if gx_data.get("是否添加覆层") == "是":
        guanxiang_pinggai["对接元件覆层厚度管前左"] = gx_data.get("覆层厚度", "0")
        # guanxiang_falan["对接元件覆层复合方式管前左"] = gx_data.get("覆层成型工艺", "")
    else:
        guanxiang_pinggai["对接元件覆层厚度管前左"] = "0"
        # guanxiang_falan["对接元件覆层复合方式管前左"] = ""

    # ========== 查询壳体圆筒的覆层厚度 ==========
    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱圆筒' AND 参数名称 = '覆层厚度'
    """, (product_id,))
    row = cursor.fetchone()
    guanxiang_pinggai["对接元件覆层厚度壳后右"] = safe_str(row["参数值"]) if row else "0"
    cursor.execute("""
            SELECT 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '管箱圆筒' AND 参数名称 = '是否添加覆层'
        """, (product_id,))
    row = cursor.fetchone()
    if row["参数值"] == "否":
        guanxiang_pinggai["对接元件覆层厚度壳后右"] = "0"

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()

        # === 查询隔条位置尺寸 ===
        cursor.execute("""
            SELECT 参数值
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 = '隔条位置尺寸 W'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["参数值"].strip() if row and row.get("参数值") else None

        #  这里后面可以继续使用 cursor 执行多个查询
        # cursor.execute("SELECT ...")

    except Exception as e:
        print(f" 查询失败: {e}")

    # === 处理参数值（空或无效默认 10） ===
    try:
        val11 = str(float(raw_val)) if raw_val not in (None, "", " ", "None","程序推荐") else "0"
    except ValueError:
        val11 = "0"

    guanxiang_pinggai["隔条位置尺寸"] = val11

    # ========== 平盖直径 ==========
    cursor.execute("""
        SELECT 管程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s AND 参数名称 = '公称直径*'
        LIMIT 1
    """, (product_id,))
    row = cursor.fetchone()
    guanxiang_pinggai["平盖直径"] = safe_str(row["管程数值"]) if row else "0"



    # ========== 法兰名义内/外径 ==========
    cursor.execute("""
        SELECT 参数名称, 壳程数值, 管程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s AND 参数名称 = '公称直径*'
    """, (product_id,))
    row = cursor.fetchone()
    if row:
        guanxiang_pinggai["法兰名义内径"] = safe_str(row.get("壳程数值"))
        guanxiang_pinggai["法兰名义外径"] = safe_str(row.get("管程数值"))

    # ========== sheji_param 字段 ==========
    sheji_param = {
        "法兰材料腐蚀裕量": ("腐蚀裕量*", "管程数值"),
        "法兰材料腐蚀裕量管前左": ("腐蚀裕量*", "管程数值"),
        "法兰材料腐蚀裕量壳后右": ("腐蚀裕量*", "管程数值"),
        "公称直径管前左": ("公称直径*", "管程数值"),
        "公称直径壳后右": ("公称直径*", "壳程数值"),
        "纵向焊接接头系数": ("焊接接头系数*", "管程数值"),
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
        guanxiang_pinggai[field] = safe_str(val)

    # ========== 液柱静压力 和 介质密度 ==========
    if "液柱静压力" in param_map:
        guanxiang_pinggai["壳程液柱静压力"] = safe_str(param_map["液柱静压力"].get("壳程数值"))
        guanxiang_pinggai["管程液柱静压力"] = safe_str(param_map["液柱静压力"].get("管程数值"))
    if "介质密度" in param_map:
        guanxiang_pinggai["壳程液柱密度"] = safe_str(param_map["介质密度"].get("壳程数值"))
        guanxiang_pinggai["管程液柱密度"] = safe_str(param_map["介质密度"].get("管程数值"))

    # ========== 前端管箱头盖法兰参数 ==========
    param_map2 = {
        "轴向拉伸载荷": "轴向外力",
        "附加弯矩": "外力矩",
        # "法兰类型": "法兰类型",
        "材料类型": "法兰材料类型",
        "材料牌号": "法兰材料牌号"
    }
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '前端管箱头盖法兰'
    """, (product_id,))
    rows = cursor.fetchall()
    for row in rows:
        name = row["参数名称"].strip()
        if name in param_map2:
            val = safe_str(row["参数值"])
            if name in ("轴向拉伸载荷", "附加弯矩") and val == "0":
                val = "0"
            guanxiang_pinggai[param_map2[name]] = val

    # ========== yuanjian_param 结构 ==========
    yuanjian_param = {
        # ("前端管箱头盖法兰", "法兰类型"): "法兰类型",
        ("前端管箱平盖", "材料类型"): "法兰材料类型",
        ("前端管箱平盖", "材料牌号"): "法兰材料牌号",
        # ("壳体法兰", "法兰类型"): "法兰类型壳后右",
        ("前端管箱头盖法兰", "材料类型"): "法兰材料类型壳后右",
        ("前端管箱头盖法兰", "材料牌号"): "法兰材料牌号壳后右",
        # ("前端管箱法兰", "覆层厚度"): "覆层厚度管前左",
        # ("壳体法兰", "覆层厚度"): "覆层厚度壳后右",
        ("管箱圆筒", "材料类型"): "圆筒材料类型",
        ("管箱圆筒", "材料牌号"): "圆筒材料牌号",
        # ("前端管箱法兰", "法兰类型"): "法兰类型管前左",
        ("前端管箱平盖", "材料类型"): "法兰材料类型管前左",
        ("前端管箱平盖", "材料牌号"): "法兰材料牌号管前左",
        ("前端管箱平盖", "平盖类型"): "平盖序号",
        ("螺柱（前端管箱平盖）", "材料牌号"): "螺栓材料牌号",
        ("前端管箱平盖垫片", "垫片材料"): "垫片材料牌号",
        ("前端管箱平盖垫片", "垫片标准"): "垫片标准号",

        ("前端管箱平盖垫片", "垫片比压力y"): "y",

        ("前端管箱平盖垫片", "垫片系数m"): "m",
    }
    component_param_names = defaultdict(set)
    for (component, pname) in yuanjian_param:
        component_param_names[component].add(pname)

    for (comp, param), field in yuanjian_param.items():

        # =========================================================
        # ✅ 特殊逻辑：螺柱（前端管箱平盖）的材料牌号 → 去合并表找
        # =========================================================
        if comp == "螺柱（前端管箱平盖）" and param == "材料牌号" and field == "螺栓材料牌号":
            val, hit_tab, hit_cid = get_fastener_bolt_material_by_belong(
                cursor, product_id, belong_keyword="前端管箱平盖", is_stud=True
            )
            val = val or ""  # 没找到就空，后面 apply_special_defaults 会兜底（若你有默认）
            # 可选：调试用
            # print(f"[DEBUG] 前端管箱平盖螺柱材料牌号命中: {val}, tab={hit_tab}, 元件ID={hit_cid}")

        else:
            # ===== 原有逻辑：从 component_map 取值 =====
            val = component_map.get(comp, {}).get(param, "")

        # ===== 原有清洗逻辑保持不变 =====
        val = str(val).strip() if val is not None else ""
        if val.lower() == "none":
            val = ""
        if param in special_force_fields and val == "":
            val = "0"
        if field == "m":
            try:
                val = str(float(val))
            except:
                val = "3"

        guanxiang_pinggai[field] = apply_special_defaults(field, val)

    # 初始化字典

    guanxiang_houduanfengtou = {
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
        WHERE 产品ID = %s AND 元件名称 = '后端管箱封头'
    """, (product_id,))
    rows = cursor.fetchall()
    extra_param_map = {r["参数名称"].strip(): r["参数值"] for r in rows}

    # 写入 guanxiang_houduanfengtou 中的预设厚度
    for i in range(1, 4):
        key = f"预设厚度{i}"
        if key in extra_param_map:
            guanxiang_houduanfengtou[key] = str(extra_param_map[key])
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
            guanxiang_houduanfengtou[key] = str(value)

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
            guanxiang_houduanfengtou["压力试验类型"] = pressure_type_map.get(clean_val, "0")

    # ===== 用户自定义耐压试验压力：取卧与立中较大者 =====
    val1 = param_map.get("自定义耐压试验压力（卧）", {}).get("管程数值", "")
    val2 = param_map.get("自定义耐压试验压力（立）", {}).get("管程数值", "")
    # ===== 最大允许工作压力 =====
    if "最大允许工作压力" in param_map:
        value = param_map["最大允许工作压力"].get("管程数值", "")
        if value != "":
            guanxiang_houduanfengtou["最大允许工作压力"] = str(value)

    try:
        val_max = max(float(val1), float(val2))
        guanxiang_houduanfengtou["用户自定义耐压试验压力"] = str(int(val_max))
    except:
        guanxiang_houduanfengtou["用户自定义耐压试验压力"] = str(val1 or val2 or "0")  # 至少有一个值就保留

    # 查询元件附加参数表中元件名称为“管箱封头”的数据
    cursor.execute("""
        SELECT 参数名称, 参数值 
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '后端管箱封头'
    """, (product_id,))
    extra_rows = cursor.fetchall()
    extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}

    # 是否添加覆层
    if extra_map.get("是否添加覆层") == "是":
        guanxiang_houduanfengtou["是否覆层"] = "1"
        guanxiang_houduanfengtou["覆层材料类型"] = extra_map.get("覆层材料类型", "轧制复合")  # 若为空可改为 "未知"
        if guanxiang_houduanfengtou["覆层材料类型"] == "钢板":
            guanxiang_houduanfengtou["带覆层时的焊接凹槽深度"] = extra_map.get("存在覆层时的焊接凹槽深度",
                                                                          "0")  # 若为空可改为 "未知"
        else:
            guanxiang_houduanfengtou["带覆层时的焊接凹槽深度"] = "0"  # 若为空可改为 "未知"
        guanxiang_houduanfengtou["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        guanxiang_houduanfengtou["椭圆形封头覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
    else:
        guanxiang_houduanfengtou["是否覆层"] = "0"
        guanxiang_houduanfengtou["覆层材料类型"] = "钢板"  # 若为空可改为 "未知"
        guanxiang_houduanfengtou["覆层复合方式"] = "无"
        guanxiang_houduanfengtou["椭圆形封头覆层厚度"] = "0"
        guanxiang_houduanfengtou["椭圆形封头曲面深度"] = extra_map.get("封头面曲面深度hi", "0")  # 默认“未知”可改为""
        guanxiang_houduanfengtou["带覆层时的焊接凹槽深度"] = "0"
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '后端管箱封头'
    """, (product_id,))
    rows = cursor.fetchall()
    extra_map = {r["参数名称"]: r["参数值"] for r in rows}

    if "材料类型" in extra_map:
        raw_type = extra_map["材料类型"]
        guanxiang_houduanfengtou["材料类型"] = material_type_map.get(raw_type, raw_type)
    if "材料牌号" in extra_map:
        guanxiang_houduanfengtou["材料牌号"] = extra_map["材料牌号"]
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
    "公称直径":""
    }
    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()
        cursor.execute("""
                   SELECT 管程数值, 壳程数值
                   FROM 产品设计活动表_设计数据表
                   WHERE 产品ID = %s AND 参数名称 = '耐压试验温度'
               """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["管程数值"].strip() if row and row.get("管程数值") else None
        guanxiang_yuantong["耐压试验温度"] = raw_val

        # 查询设计数据表，获取公称直径*
        cursor.execute("""
                   SELECT 管程数值, 壳程数值
                   FROM 产品设计活动表_设计数据表
                   WHERE 产品ID = %s AND 参数名称 = '公称直径*'
               """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["管程数值"].strip() if row and row.get("管程数值") else None
        guanxiang_yuantong["公称直径"] = raw_val
        guanxiang_yuantong["圆筒内/外径"] = raw_val


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

    # 写入 guanxiang_fengtou 中的预设厚度
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
        "公称直径":""
    }
    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()
        cursor.execute("""
                   SELECT 管程数值, 壳程数值
                   FROM 产品设计活动表_设计数据表
                   WHERE 产品ID = %s AND 参数名称 = '耐压试验温度'
               """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["壳程数值"].strip() if row and row.get("壳程数值") else None
        qiaoti_yuantong["耐压试验温度"] = raw_val

        # 查询设计数据表，获取公称直径*
        cursor.execute("""
                   SELECT 管程数值, 壳程数值
                   FROM 产品设计活动表_设计数据表
                   WHERE 产品ID = %s AND 参数名称 = '公称直径*'
               """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["管程数值"].strip() if row and row.get("管程数值") else None
        qiaoti_yuantong["公称直径"] = raw_val
        qiaoti_yuantong["圆筒内/外径"] = raw_val

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
            qiaoti_yuantong["指定内径"] = "0"
            cursor.execute("""
                   SELECT 参数值 FROM 产品设计活动表_布管参数表
                   WHERE 产品ID = %s AND 参数名 = '壳体内直径 Dis'
               """, (product_id,))
            row = cursor.fetchone()
            if row and "参数值" in row:
                qiaoti_yuantong["指定内径"] = str(row["参数值"])
            else:
                qiaoti_yuantong["指定内径"] = "0"
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

    except Exception as e:
        print(f" 查询失败: {e}")

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
        if qiaoti_yuantong["覆层材料类型"] == "钢板":
            qiaoti_yuantong["圆筒带覆层时的焊接凹槽深度"] = extra_map.get("存在覆层时的焊接凹槽深度",
                                                                             "0")  # 若为空可改为 "未知"
        else:
            qiaoti_yuantong["圆筒带覆层时的焊接凹槽深度"] = "0"  # 若为空可改为 "未知"
        qiaoti_yuantong["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        qiaoti_yuantong["圆筒覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
    else:
        qiaoti_yuantong["是否覆层"] = "0"
        qiaoti_yuantong["覆层材料类型"] = "钢板"
        qiaoti_yuantong["圆筒带覆层时的焊接凹槽深度"] = "0"
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

    # 写入 guanxiang_fengtou 中的预设厚度
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
        "是否带分程隔板":"false",
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
        "介质情况": "毒性",
        "垫片标准号": "GB/T 29463-2023",
        "垫片实际密封宽度": "0",
        "分程隔板槽宽度" :"2",
        "介质类型":"",
        "管程程数":"",
        "管板形式":"",
        "螺栓根径类型": "",
        "x轴向弯矩": "",
        "y轴向弯矩": "",
        "径向载荷": "",
        "螺栓的有效长度": "",
        "螺栓螺母和螺母法兰面之间的总摩擦系数": "",
        "垫片材料弹性模量": "",

        "管前左法兰密封面高度": "0",
        "壳后右法兰密封面高度": "0",
        "覆层材料牌号管前左": "0",
        "覆层材料牌号壳后右": "0"

    }
    cursor.execute("""
            SELECT 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s
              AND 元件名称 = '管箱法兰'
              AND 参数名称 = '密封面高度'
        """, (product_id,))

    row = cursor.fetchone()
    if row:
        guanxiang_falan["管前左法兰密封面高度"] = safe_str(row.get("参数值"))
        guanxiang_falan["壳后右法兰密封面高度"] = safe_str(row.get("参数值"))


    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s
          AND 元件名称 = '管箱垫片'
          AND 参数名称 = '压紧面形状'
    """, (product_id,))

    row = cursor.fetchone()
    if row:
        guanxiang_falan["压紧面形状序号"] = safe_str(row.get("参数值"))

    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s
          AND 元件名称 = '管箱垫片'
          AND 参数名称 = '压紧面形状'
    """, (product_id,))

    row = cursor.fetchone()
    if row:
        guanxiang_falan["压紧面形状序号"] = safe_str(row.get("参数值"))
    current_component = "管箱法兰"  # 也可以是 "外头盖法兰"、"浮头法兰"
    cursor.execute("""
            SELECT 参数值
            FROM 产品设计活动表_元件附加参数合并表
            WHERE 产品ID = %s
              AND 参数名称 = '螺柱根径系列1'
              AND Tab分类 = (
                    SELECT Tab分类
                    FROM 产品设计活动表_元件附加参数合并表
                    WHERE 产品ID = %s
                      AND 参数名称 = '元件所属'
                      AND FIND_IN_SET(%s, REPLACE(参数值, '、', ',')) > 0
                    LIMIT 1
              )
            LIMIT 1
        """, (product_id, product_id, current_component))

    row = cursor.fetchone()
    if row:
        guanxiang_falan["螺栓根径类型"] = safe_str(row.get("参数值") if isinstance(row, dict) else row[0])
    # === 获取管箱垫片的垫片厚度 ===
    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱垫片' AND 参数名称 = '垫片厚度'
    """, (product_id,))
    row = cursor.fetchone()
    val = row["参数值"] if row and row["参数值"] not in (None, "", "None") else "4.5"
    guanxiang_falan["垫片厚度"] = str(val)
    sheji_param = {
        "法兰材料腐蚀裕量": ("腐蚀裕量*", "管程数值"),
        "法兰材料腐蚀裕量管前左": ("腐蚀裕量*", "管程数值"),
        "法兰材料腐蚀裕量壳后右": ("腐蚀裕量*", "管程数值"),
        "公称直径管前左": ("公称直径*", "管程数值"),
        "公称直径壳后右": ("公称直径*", "壳程数值"),
        "纵向焊接接头系数": ("焊接接头系数*", "管程数值"),
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
        guanxiang_falan[field] = safe_str(val)

    # ========== 液柱静压力 和 介质密度 ==========
    if "液柱静压力" in param_map:
        guanxiang_falan["壳程液柱静压力"] = safe_str(param_map["液柱静压力"].get("壳程数值"))
        guanxiang_falan["管程液柱静压力"] = safe_str(param_map["液柱静压力"].get("管程数值"))
    if "介质密度" in param_map:
        guanxiang_falan["壳程液柱密度"] = safe_str(param_map["介质密度"].get("壳程数值"))
        guanxiang_falan["管程液柱密度"] = safe_str(param_map["介质密度"].get("管程数值"))
    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s
          AND 元件名称 = '管箱法兰'
          AND 参数名称 = '法兰类型'
    """, (product_id,))

    row = cursor.fetchone()
    if row:
        guanxiang_falan["法兰种类"] = safe_str(row.get("参数值"))

    sql = """
        SELECT 管板类型
        FROM 产品设计活动表_管板形式表
        WHERE 产品ID = %s
        LIMIT 1
    """
    cursor.execute(sql, (product_id,))
    row = cursor.fetchone()
    if row:
        guanxiang_falan["管板形式"] = str(row["管板类型"])[0]  # 取第一个字母

    cursor.execute("""
               SELECT 参数值 
               FROM 产品设计活动表_布管参数表
               WHERE 产品ID = %s AND 参数名 = '管程程数'
               LIMIT 1
           """, (product_id,))
    row = cursor.fetchone()
    tube_passes1 = row["参数值"].strip() if row and row.get("参数值") else ""
    guanxiang_falan["管程程数"] = tube_passes1
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
        shell_expl = param_map["介质特性（爆炸危险程度）"].get("壳程数值", "-")
        if shell_expl == "":
            shell_expl = "-"
        media_parts.append(shell_expl)
        tube_expl = param_map["介质特性（爆炸危险程度）"].get("管程数值", "-")
        if tube_expl == "":
            tube_expl = "-"
        media_parts.append(tube_expl)
    if "介质特性（毒性危害程度）" in param_map:
        shell_toxic = param_map["介质特性（毒性危害程度）"].get("壳程数值", "")
        if shell_toxic == "":
            shell_toxic = "-"
        media_parts.append(shell_toxic)
        tube_toxic = param_map["介质特性（毒性危害程度）"].get("管程数值", "-")
        if tube_toxic == "":
            tube_toxic = "-"
        media_parts.append(tube_toxic)
    if "介质特性（是否液化气体）" in param_map:
        shell_ox = param_map["介质特性（是否液化气体）"].get("壳程数值", "-")
        if shell_ox == "":
            shell_ox = "-"
        media_parts.append(shell_ox)
        tube_ox = param_map["介质特性（是否液化气体）"].get("管程数值", "-")
        if tube_ox == "":
            tube_ox = "-"
        media_parts.append(tube_ox)

    if media_parts:
        guanxiang_falan["介质类型"] = "/".join(media_parts)
    else:
        guanxiang_falan["介质类型"] = "0"

    # === 查询管程分程形式 ===
    cursor.execute("""
                       SELECT 参数值 
                       FROM 产品设计活动表_布管参数表
                       WHERE 产品ID = %s AND 参数名 = '管程分程形式'
                       LIMIT 1
                   """, (product_id,))
    row = cursor.fetchone()
    tube_form = row["参数值"].strip() if row and row.get("参数值") else None
    if tube_form == '2':
        tube_form = '2.1'
    guanxiang_falan["垫片代号"] = tube_form
    # 平盖直径
    cursor.execute("""
        SELECT 管程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s AND 参数名称 = '公称直径*'
        LIMIT 1
    """, (product_id,))
    row = cursor.fetchone()
    guanxiang_falan["平盖直径"] = safe_str(row["管程数值"]) if row else "0"
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
        tube_toxic = param_map["介质特性（毒性危害程度）"].get("管程数值", "-")
        if shell_toxic:
            media_parts.append(f"{shell_toxic}危害")
        if tube_toxic:
            media_parts.append(f"{tube_toxic}危害")

    if media_parts:
        guanxiang_falan["介质情况"] = "/".join(media_parts)
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s
          AND 元件名称 = '管箱垫片'
          AND 参数名称 IN ('垫片名义外径D2n','垫片名义内径D1n')
    """, (product_id,))
    rows = cursor.fetchall()
    print("rows",rows)
    if rows:
        params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}
        guanxiang_falan["垫片名义外径"] = params.get("垫片名义外径D2n", "")
        if guanxiang_falan["垫片名义外径"] in ("程序推荐", ""):
            guanxiang_falan["垫片名义外径"] = "0"

        guanxiang_falan["垫片名义内径"] = params.get("垫片名义内径D1n", "")
        if guanxiang_falan["垫片名义内径"] in ("程序推荐", ""):
            guanxiang_falan["垫片名义内径"] = "0"

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
            WHERE 产品ID = %s AND 元件名称 = '管箱法兰'
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

    # guanxiang_pinggai["圆筒名义内径"] = row_map.get("内径", "0")
    # guanxiang_pinggai["圆筒名义外径"] = row_map.get("外径", "0")
    guanxiang_falan["圆筒材料类型"] = row_map.get("材料类型", "0")
    guanxiang_falan["圆筒材料牌号"] = row_map.get("材料牌号", "0")
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '固定管板'
        """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    guanxiang_falan["管程侧分程隔板槽宽度"] = row_map.get("管程侧分程隔板槽宽度", "0")
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '固定管板'
        """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    guanxiang_falan["壳程侧分程隔板槽宽度"] = row_map.get("壳程侧分程隔板槽宽度", "0")
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
        print(f" 查询失败: {e}")

    # === 处理参数值（空或无效默认 10） ===
    try:
        val11 = str(float(raw_val)) if raw_val not in (None, "", " ", "None","程序推荐") else "0"
    except ValueError:
        val11 = "0"

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
        if guanxiang_falan["法兰名义内径"] == "程序推荐":
            guanxiang_falan["法兰名义内径"] = "0"
        guanxiang_falan["法兰名义外径"] = safe_str(row["管程数值"])
        if guanxiang_falan["法兰名义外径"] == "程序推荐":
            guanxiang_falan["法兰名义外径"] = "0"
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
           WHERE 产品ID = %s AND 元件名称 = '管箱法兰'
       """, (product_id,))
    rows = cursor.fetchall()
    qt_data = {row["参数名称"]: str(row["参数值"]).strip() for row in rows if row["参数值"] not in (None, "", "None")}

    if qt_data.get("是否添加覆层") == "是":
        guanxiang_falan["覆层厚度壳后右"] = qt_data.get("覆层厚度", "0")
        guanxiang_falan["覆层材料牌号壳后右"] = qt_data.get("覆层材料牌号", "0")
        guanxiang_falan["覆层厚度"] = qt_data.get("覆层厚度", "0")

        # guanxiang_falan["对接元件覆层复合方式壳后右"] = qt_data.get("覆层成型工艺", "")
    else:
        guanxiang_falan["覆层厚度壳后右"] = "0"
        guanxiang_falan["覆层厚度"] = "0"

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
        guanxiang_falan["覆层材料牌号管前左"] = qt_data.get("覆层材料牌号", "0")
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
    }
    for field, (param_name, side) in sheji_param.items():
        guanxiang_falan[field] = safe_str(sheji_map.get(param_name, {}).get(side, "0"))

    # === 获取元件附加参数整体 ===
    # === 获取元件附加参数整体 ===
    cursor.execute(""" 
        SELECT 元件名称, 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()

    component_map = {}

    for r in rows:
        comp = r.get("元件名称")
        pname = r.get("参数名称")
        pvalue = r.get("参数值")

        # --- 健壮性判断 ---
        if not comp or not pname or pvalue is None:
            continue  # 若有字段为空或 None，跳过此行

        comp = str(comp).strip()
        pname = str(pname).strip()
        pvalue = str(pvalue).strip()

        if not comp or not pname or not pvalue:
            continue  # 去除空字符串的情况

        # --- 正常写入映射 ---
        if comp not in component_map:
            component_map[comp] = {}

        component_map[comp][pname] = pvalue

    # === 元件参数映射关系 ===
    yuanjian_param = {
        ("管箱法兰", "轴向拉伸载荷"): "轴向外力",
        ("管箱法兰", "附加弯矩"): "外力矩",
        # ("壳体法兰", "覆层厚度"): "覆层厚度壳后右",
        # ("管箱法兰", "覆层厚度"): "覆层厚度管前左",
        # ("管箱法兰", "法兰类型"): "法兰类型",
        ("管箱法兰", "材料类型"): "法兰材料类型",
        ("管箱法兰", "材料牌号"): "法兰材料牌号",
        # ("管箱法兰", "覆层厚度"): "覆层厚度",
        ("管箱圆筒", "材料类型"): "圆筒材料类型",
        ("管箱圆筒", "材料牌号"): "圆筒材料牌号",
        # ("前端管箱平盖", "平盖类型"): "平盖序号",
        ("螺柱（管箱法兰）", "材料牌号"): "螺栓材料牌号",
        ("管箱垫片", "垫片材料"): "垫片材料牌号",
        ("管箱垫片", "垫片标准"): "垫片标准号",

        ("管箱垫片", "垫片系数m"): "m",
        ("管箱垫片", "垫片比压力y"): "y",

        ("管箱法兰", "材料类型"): "法兰材料类型管前左",
        ("管箱法兰", "材料牌号"): "法兰材料牌号管前左",
        ("管箱法兰", "材料类型"): "法兰材料类型壳后右",
        ("管箱法兰", "材料牌号"): "法兰材料牌号壳后右",
        ("管箱法兰", "材料类型"): "法兰材料类型",
        ("管箱法兰", "材料牌号"): "法兰材料牌号",
    }

    # === 写入字段 ===
    for (comp, param), field in yuanjian_param.items():

        # =========================================================
        # ✅ 特殊逻辑：螺柱（前端管箱平盖）的材料牌号 → 去合并表找
        # =========================================================
        if comp == "螺柱（管箱法兰）" and param == "材料牌号" and field == "螺栓材料牌号":
            val, hit_tab, hit_cid = get_fastener_bolt_material_by_belong(
                cursor, product_id, belong_keyword="管箱法兰", is_stud=True
            )
            val = val or ""  # 没找到就空，后面 apply_special_defaults 会兜底（若你有默认）
            # 可选：调试用
            # print(f"[DEBUG] 前端管箱平盖螺柱材料牌号命中: {val}, tab={hit_tab}, 元件ID={hit_cid}")

        else:
            # ===== 原有逻辑：从 component_map 取值 =====
            val = component_map.get(comp, {}).get(param, "")

        # ===== 原有清洗逻辑保持不变 =====
        val = str(val).strip() if val is not None else ""
        if val.lower() == "none":
            val = ""
        if param in special_force_fields and val == "":
            val = "0"
        if field == "m":
            try:
                val = str(float(val))
            except:
                val = "3"

        guanxiang_falan[field] = apply_special_defaults(field, val)


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
    cursor.execute("""
               SELECT 管程数值, 壳程数值
               FROM 产品设计活动表_设计数据表
               WHERE 产品ID = %s AND 参数名称 = '耐压试验温度'
           """, (product_id,))
    row = cursor.fetchone()
    raw_val = row["管程数值"].strip() if row and row.get("管程数值") else None
    fencheng_geban["耐压试验温度"] = raw_val

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
        WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管程侧分程隔板槽宽度'
    """, (product_id,))
    row = cursor.fetchone()
    val = row["参数值"] if row and row["参数值"] not in (None, "", "None") else "0"
    fencheng_geban["分程隔板槽宽度"] = str(val)

    # === 获取管箱分程隔板两侧压力差值 ===
    pressure_diff_names = [
        "进、出口压力差*",
        "隔板两侧压力差值*（可取隔板两侧计算压降2倍）",
    ]

    fencheng_geban["管箱分程隔板两侧压力差值"] = "0"

    for parameter_name in pressure_diff_names:
        cursor.execute("""
            SELECT 管程数值
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s
              AND 参数名称 = %s
            LIMIT 1
        """, (product_id, parameter_name))

        row = cursor.fetchone()

        if not row:
            continue

        raw_value = row.get("管程数值")

        if raw_value in (None, ""):
            continue

        try:
            value = float(raw_value)
            fencheng_geban["管箱分程隔板两侧压力差值"] = str(value)
            break
        except (ValueError, TypeError):
            # 当前参数值无效，继续尝试下一个参数
            continue
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

    print(" 腐蚀裕量(双面) =", fencheng_geban["腐蚀裕量(双面)"])

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  #  不使用 with，游标不会自动关闭

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
        print(f" 查询失败: {e}")

    # === 处理参数值（空或无效默认 10） ===
    try:
        val11 = str(float(raw_val)) if raw_val not in (None, "", " ", "None","程序推荐") else "0"
    except ValueError:
        val11 = "0"

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
        cursor.execute("""
                   SELECT 管程数值, 壳程数值
                   FROM 产品设计活动表_设计数据表
                   WHERE 产品ID = %s AND 参数名称 = '耐压试验温度'
               """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["壳程数值"].strip() if row and row.get("壳程数值") else None
        qiaoti_duanbuyuantong1["耐压试验温度"] = raw_val

        # === 查询换热管公称长度 LN ===
        cursor.execute("""
                   SELECT 管程数值, 壳程数值
                   FROM 产品设计活动表_设计数据表
                   WHERE 产品ID = %s AND 参数名称 = '公称直径*'
               """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["壳程数值"].strip() if row and row.get("壳程数值") else None
        qiaoti_duanbuyuantong1["公称直径"] = raw_val
        qiaoti_duanbuyuantong1["圆筒内/外径"] = raw_val

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
            qiaoti_duanbuyuantong1["指定内径"] = "0"
            cursor.execute("""
                   SELECT 参数值 FROM 产品设计活动表_布管参数表
                   WHERE 产品ID = %s AND 参数名 = '壳体内直径 Dis'
               """, (product_id,))
            row = cursor.fetchone()
            if row and "参数值" in row:
                qiaoti_duanbuyuantong1["指定内径"] = str(row["参数值"])
            else:
                qiaoti_duanbuyuantong1["指定内径"] = "0"
            cursor.execute("""
                        SELECT 数值 FROM 产品设计活动表_通用数据表
                        WHERE 产品ID = %s AND 参数名称 = '外径'
                    """, (product_id,))
            row_waijing = cursor.fetchone()
            if row_waijing and "数值" in row_waijing:
                qiaoti_duanbuyuantong1["圆筒内/外径"] = row_waijing["数值"]
        else:
            qiaoti_duanbuyuantong1["指定内径"] = raw_val2

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
        if qiaoti_duanbuyuantong1["覆层材料类型"] == "钢板":
            qiaoti_duanbuyuantong1["圆筒带覆层时的焊接凹槽深度"] = extra_map.get("存在覆层时的焊接凹槽深度",
                                                                          "0")  # 若为空可改为 "未知"
        else:
            qiaoti_duanbuyuantong1["圆筒带覆层时的焊接凹槽深度"] = "0"  # 若为空可改为 "未知"
    else:
        qiaoti_duanbuyuantong1["覆层材料类型"] = "钢板"
        qiaoti_duanbuyuantong1["是否覆层"] = "0"
        qiaoti_duanbuyuantong1["覆层复合方式"] = "无"
        qiaoti_duanbuyuantong1["圆筒覆层厚度"] = "0"
        qiaoti_duanbuyuantong1["圆筒带覆层时的焊接凹槽深度"] = "0"
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

    # 写入 guanxiang_fengtou 中的预设厚度
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
        cursor.execute("""
                   SELECT 管程数值, 壳程数值
                   FROM 产品设计活动表_设计数据表
                   WHERE 产品ID = %s AND 参数名称 = '耐压试验温度'
               """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["壳程数值"].strip() if row and row.get("壳程数值") else None
        qiaoti_duanbuyuantong2["耐压试验温度"] = raw_val
        # === 查询换热管公称长度 LN ===
        cursor.execute("""
                   SELECT 管程数值, 壳程数值
                   FROM 产品设计活动表_设计数据表
                   WHERE 产品ID = %s AND 参数名称 = '公称直径*'
               """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["管程数值"].strip() if row and row.get("管程数值") else None
        qiaoti_duanbuyuantong2["公称直径"] = raw_val
        qiaoti_duanbuyuantong2["圆筒内/外径"] = raw_val

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
            qiaoti_duanbuyuantong2["指定内径"] = "0"
            cursor.execute("""
                   SELECT 参数值 FROM 产品设计活动表_布管参数表
                   WHERE 产品ID = %s AND 参数名 = '壳体内直径 Dis'
               """, (product_id,))
            row = cursor.fetchone()
            if row and "参数值" in row:
                qiaoti_duanbuyuantong2["指定内径"] = str(row["参数值"])
            else:
                qiaoti_duanbuyuantong2["指定内径"] = "0"
            cursor.execute("""
                        SELECT 数值 FROM 产品设计活动表_通用数据表
                        WHERE 产品ID = %s AND 参数名称 = '外径'
                    """, (product_id,))
            row_waijing = cursor.fetchone()
            if row_waijing and "数值" in row_waijing:
                qiaoti_duanbuyuantong2["圆筒内/外径"] = row_waijing["数值"]
        else:
            qiaoti_duanbuyuantong2["指定内径"] = raw_val2

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
        if qiaoti_duanbuyuantong2["覆层材料类型"] == "钢板":
            qiaoti_duanbuyuantong2["圆筒带覆层时的焊接凹槽深度"] = extra_map.get("存在覆层时的焊接凹槽深度",
                                                                                 "0")  # 若为空可改为 "未知"
        else:
            qiaoti_duanbuyuantong2["圆筒带覆层时的焊接凹槽深度"] = "0"  # 若为空可改为 "未知"
    else:
        qiaoti_duanbuyuantong2["覆层材料类型"] = "钢板"
        qiaoti_duanbuyuantong2["是否覆层"] = "0"
        qiaoti_duanbuyuantong2["覆层复合方式"] = "无"
        qiaoti_duanbuyuantong2["圆筒覆层厚度"] = "0"
        qiaoti_duanbuyuantong2["圆筒带覆层时的焊接凹槽深度"] = "0"
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

    # 写入 guanxiang_fengtou 中的预设厚度
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
        cursor.execute("""
                   SELECT 管程数值, 壳程数值
                   FROM 产品设计活动表_设计数据表
                   WHERE 产品ID = %s AND 参数名称 = '耐压试验温度'
               """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["管程数值"].strip() if row and row.get("管程数值") else None
        guanxiang_houduanyuantong["耐压试验温度"] = raw_val
        # === 查询换热管公称长度 LN ===
        cursor.execute("""
                   SELECT 管程数值, 壳程数值
                   FROM 产品设计活动表_设计数据表
                   WHERE 产品ID = %s AND 参数名称 = '公称直径*'
               """, (product_id,))
        row = cursor.fetchone()
        raw_val = row["管程数值"].strip() if row and row.get("管程数值") else None
        guanxiang_houduanyuantong["公称直径"] = raw_val
        guanxiang_houduanyuantong["圆筒内/外径"] = raw_val

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
            guanxiang_houduanyuantong["指定内径"] = "0"
            cursor.execute("""
                   SELECT 参数值 FROM 产品设计活动表_布管参数表
                   WHERE 产品ID = %s AND 参数名 = '管箱内直径 Dit'
               """, (product_id,))
            row = cursor.fetchone()
            if row and "参数值" in row:
                guanxiang_houduanyuantong["指定内径"] = str(row["参数值"])
            else:
                guanxiang_houduanyuantong["指定内径"] = "0"
            cursor.execute("""
                        SELECT 数值 FROM 产品设计活动表_通用数据表
                        WHERE 产品ID = %s AND 参数名称 = '外径'
                    """, (product_id,))
            row_waijing = cursor.fetchone()
            if row_waijing and "数值" in row_waijing:
                guanxiang_houduanyuantong["圆筒内/外径"] = row_waijing["数值"]
        else:
            guanxiang_houduanyuantong["指定内径"] = raw_val2


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
        if guanxiang_houduanyuantong["覆层材料类型"] == "钢板":
            guanxiang_houduanyuantong["圆筒带覆层时的焊接凹槽深度"] = extra_map.get("存在覆层时的焊接凹槽深度",
                                                                                 "0")  # 若为空可改为 "未知"
        else:
            guanxiang_houduanyuantong["圆筒带覆层时的焊接凹槽深度"] = "0"  # 若为空可改为 "未知"

    else:
        guanxiang_houduanyuantong["覆层材料类型"] = "钢板"
        guanxiang_houduanyuantong["是否覆层"] = "0"
        guanxiang_houduanyuantong["覆层复合方式"] = "无"
        guanxiang_houduanyuantong["圆筒覆层厚度"] = "0"
        guanxiang_houduanyuantong["圆筒带覆层时的焊接凹槽深度"] = "0"
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

    # 写入 guanxiang_fengtou 中的预设厚度
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
               SELECT 管程数值, 壳程数值
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
        cursor = conn.cursor()  #   不使用 with，游标不会自动关闭

        # 1. 读取3个参数值
        params_map = {
            "换热管中心距 S": ("s_val", 25),
            "分程隔板两侧相邻管中心距（竖直）": ("sn_val", 0), #分程隔板两侧相邻管中心距（竖直）
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
        cursor = conn.cursor()  #   手动创建游标，不会自动关闭

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
            print("tubes_count",tubes_count)
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
        "分程隔板与垫片接触面面积": "0",
        # "公称直径": "1000", #管程
        "管程液柱静压力": "0", #1
        "壳程液柱静压力": "0", #1
        "管程腐蚀裕量": "2", #1
        "壳程腐蚀裕量": "2",  #1
        "是否可以保证在任何情况下管壳程压力都能同时作用": "0", #1
        # "换热管使用场合": "介质易爆/极度危害/高度危害", #壳程，介质特性（爆炸危险程度）+管程和壳程，介质特性（毒性危害程度）
        # "换热管与管板连接方式": "焊接", #无
        "内孔焊焊接接头系数": "0.85",
        "管板材料类型": "钢锻件", #1
        "管板材料名称": "16Mn", #1
        "管板名义厚度": "0", #1
        # "管板外径": "1063", #无
        "壳程侧隔板槽深度": "0", #1
        "管程侧隔板槽深度": "6", #1
        "管程侧应力释放槽深度": "0",  #1
        "壳程侧应力释放槽深度": "0",  #1
        "管板强度削弱系数": "0.4",#1
        "管板刚度削弱系数": "0.4",#1
        "换热管材料类型": "钢管", #1
        "换热管材料牌号": "10(GB9948)",#1
        "换热管外径": "25",#1
        "换热管壁厚": "2", #1
        "换热管直管段长度": "6000", #1
        "换热管伸出管板长度": "4.5", #1
        "换热管根数": tubes_count,  #1
        "换热管中心距": s_val, #1
        "耐压试验温度": "20", #1
        "换热管受压失稳当量长度": "800",#1
        "管板凸台高度": "5",  # 1
        "管箱垫片型式": "波齿垫",#1
        "管箱垫片标准": "SH/T 3430-2018",#1
        "管箱垫片材料": "316L+F.G.",#1
        "管箱垫片外径": "0", #1
        "管箱垫片内径": "0",#1
        "垫片系数": "3", #1
        "垫片比压力": "50", #1
        "管箱法兰类型": "长颈对焊法兰", #1
        "管箱法兰是乙型平焊法兰时法兰短节厚度": "16",
        "管箱法兰材料类型": "钢锻件", #1
        "管箱法兰材料牌号": "16Mn", #1
        "管箱法兰外径": "0",
        "法兰螺栓孔中心圆直径": "940",
        "管箱法兰颈部小端厚度": "22",
        "管箱法兰颈部大端厚度": "32",
        "螺柱材料牌号": "35CrMo", #1
        "螺柱数量": "40",
        "螺柱规格": "M24",
        "螺柱根径": "23.752",
        "壳体法兰密封面外径": "885", #1
        "管板延长部分兼作法兰密封面高度": "6",
        "管箱法兰有效厚度":"",
        "换热管排列方式": "正三角形", #1
        "折流板切口方向": "垂直", #1
        "管/壳程布置型式": "2.1", #1
        "水平隔板槽两侧相邻管中心距": sn_val, #1
        "竖直隔板槽两侧相邻管中心距": snh_val, #1
        "相邻隔板槽中心距": "204", #1
        "管板分程处面积Ad": "0", #1
        "'十字'交叉沿水平隔板槽单侧的排管根数": "0", #1
        "沿竖直隔板槽单侧的排管根数": "0", #1
        "'丁字'交叉沿水平隔板槽连续侧的排管根数": "0", #1
        "'丁字'交叉沿水平隔板槽不连续侧的排管根数": "0",#1
        "'十字'交叉沿水平隔板槽单侧管排1最两端管孔中心距": "0", #1
        "'十字'交叉沿水平隔板槽单侧管排2最两端管孔中心距": "0", #1
        "'十字'交叉沿水平隔板槽单侧管排3最两端管孔中心距": "0", #1
        "'丁字'交叉沿水平隔板槽不连续侧管排1最两端管孔中心距": "0", #1
        "'丁字'交叉沿水平隔板槽不连续侧管排2最两端管孔中心距": "0", #1
        "'丁字'交叉沿水平隔板槽不连续侧管排3最两端管孔中心距": "0", #1
        "沿竖直隔板槽单侧的管排最两端管孔中心距": "0", #1
        "沿长度平均的壳程圆筒金属温度": "180", #1
        "沿长度平均的换热管金属温度": "155", #1
        "制造环境温度": "20",#1
        "管箱圆筒实际内径": "2500",#1
        "壳程圆筒实际内径": "2500",#1
        "管板材料负偏差": "0",#1
        "管程圆筒材料负偏差": "0.3",#1
        "壳程圆筒材料负偏差": "0.3",#1
        "管板管程侧覆层厚度": "0", #1
        "管板壳程侧覆层厚度": "0", #1
        "管箱圆筒材料类型": "钢板", #1
        "管箱圆筒材料名称": "Q345R",#1
        "壳程圆筒材料类型": "钢板",#1
        "壳程圆筒材料名称": "Q345R",#1
        "壳程圆筒是否分段": "0",#1
        "壳程圆筒端部材料类型": "钢板",#1
        "壳程圆筒端部材料名称": "Q345R",#1
        "管程圆筒环向焊接接头系数": "1", #1
        "壳程圆筒环向焊接接头系数": "0.6", #1
        "管板与壳体/管箱的连接序号": "b",#1
        # "应力释放槽深度": "3",
        "管-板连接形式": "强度焊接",#1
        "焊脚高度": "4",#1
        "折流板间距": "437.5", #1
        "壳程圆筒名义厚度": "20",#1
        "壳体端部圆筒1长度": "0",#1
        "壳体端部圆筒2长度": "0",#1
        "壳程端部圆筒名义厚度": "20",#1
        "管箱圆筒名义厚度": "20",#1
        "管箱法兰名义厚度": "0",#1
        # "壳体法兰厚度": "0",
        "a": "0",
        "b": "0",
        "c1": "0",
        "c2": "0",
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
        "q":"0",
        "f2":"0",
        "q2":"0",
        "管板管程覆层材料的密度": "0",
        "管板壳程覆层材料的密度": "0",
    }
    # 防止这些字段之前已经被默认值或其他逻辑写入
    tube_sheet_connection_fields = {
        "焊脚外伸高度",
        "管程侧坡口深度",
        "壳程侧不胀接长度",
        "贴胀长度",
        "焊脚高度",
        "管程侧不胀接长度",
        "壳程侧不胀接长度B",
    }

    for field in tube_sheet_connection_fields:
        guanban_a.pop(field, None)

    # 一次性读取当前产品对应的管板连接方式及全部连接参数
    cursor.execute("""
        SELECT 管板连接方式, 参数名, 参数值
        FROM 产品设计活动表_管板连接表
        WHERE 产品ID = %s
    """, (product_id,))

    connection_rows = cursor.fetchall()

    # ------------------------------------------------------------
    # 1. 获取管板连接方式
    # ------------------------------------------------------------
    connection_type = ""

    for row in connection_rows:
        raw_connection_type = row.get("管板连接方式")

        if raw_connection_type is not None:
            raw_connection_type = str(raw_connection_type).strip()

            if raw_connection_type and raw_connection_type.lower() != "none":
                connection_type = raw_connection_type
                break

    # 没查到时使用 "0"
    guanban_a["管-板连接形式"] = connection_type if connection_type else "0"

    # ------------------------------------------------------------
    # 2. 将参数名和参数值转换成字典
    # ------------------------------------------------------------
    connection_param_map = {}

    for row in connection_rows:
        param_name = row.get("参数名")
        param_value = row.get("参数值")

        if param_name is None:
            continue

        param_name = str(param_name).strip()

        if not param_name:
            continue

        if param_value is None:
            param_value = "0"
        else:
            param_value = str(param_value).strip()

            if not param_value or param_value.lower() == "none":
                param_value = "0"

        connection_param_map[param_name] = param_value

    # 优先使用当前产品在管板连接表中配置的内孔焊接头系数；无此参数时保留默认值。
    guanban_a["内孔焊焊接接头系数"] = connection_param_map.get(
        "内孔焊焊接接头系数φ",
        "0.85"
    )

    # ------------------------------------------------------------
    # 3. 不同连接形式对应需要写入 guanban_a 的字段
    #    key：管板连接方式
    #    value：{guanban_a字段名: 数据库参数名}
    # ------------------------------------------------------------
    connection_field_rules = {
        # 强度焊接加贴胀管孔结构：
        # 只输出焊脚外伸高度、管程侧坡口深度
        "强度焊接加贴胀管孔结构": {
            "焊脚外伸高度": "焊脚外伸高度 E",
            "管程侧坡口深度": "管程侧坡口深度 G",
        },

        # 机械胀接管孔结构：
        # 只输出壳程侧不胀接长度、贴胀长度
        "机械胀接管孔结构": {
            "壳程侧不胀接长度": "壳程侧不胀接长度 B",
            "贴胀长度": "贴胀长度 Y",
        },

        # 强度焊接的焊缝形式：
        # 只输出焊脚高度
        "强度焊接的焊缝形式": {
            "焊脚高度": "焊脚高度 l",
        },

        # 兼容数据库中可能没有“的”字的写法
        "强度焊接焊缝形式": {
            "焊脚高度": "焊脚高度 l",
        },

        # 机械强度胀接加密封焊管孔结构：
        # 只输出管程侧不胀接长度、壳程侧不胀接长度B
        "机械强度胀接加密封焊管孔结构": {
            "管程侧不胀接长度": "管程侧不胀接长度 A",
            "壳程侧不胀接长度B": "壳程侧不胀接长度 B",
        },

        # 内孔焊接头形式：
        # 不输出上述任何结构参数
        "内孔焊接头形式": {},
    }

    # ------------------------------------------------------------
    # 4. 根据管板连接形式，只写入当前形式需要的字段
    # ------------------------------------------------------------
    active_field_mapping = connection_field_rules.get(connection_type, {})

    for target_field, database_param_name in active_field_mapping.items():
        guanban_a[target_field] = connection_param_map.get(
            database_param_name,
            "0"
        )

    # 可选：未识别到连接形式时输出提示，方便检查数据库实际文字
    if connection_type and connection_type not in connection_field_rules:
        print(
            f"⚠ 未配置的管板连接方式：{connection_type}，"
            "本次不写入管板连接结构参数"
        )

    print("管-板连接形式：", guanban_a["管-板连接形式"])
    print("当前管板连接参数：", {
        key: guanban_a[key]
        for key in tube_sheet_connection_fields
        if key in guanban_a
    })
    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管板凸台高度'
    """, (product_id,))
    row = cursor.fetchone()
    val = row["参数值"] if row and row["参数值"] not in (None, "", "None") else "5"
    guanban_a["管板凸台高度"] = str(val)
    sheji_param = {
        "法兰材料腐蚀裕量": ("腐蚀裕量*", "管程数值"),
        "法兰材料腐蚀裕量管前左": ("腐蚀裕量*", "管程数值"),
        "法兰材料腐蚀裕量壳后右": ("腐蚀裕量*", "管程数值"),
        "公称直径管前左": ("公称直径*", "管程数值"),
        "公称直径壳后右": ("公称直径*", "壳程数值"),
        "纵向焊接接头系数": ("焊接接头系数*", "管程数值"),
    }
    cursor.execute("""
               SELECT 管程数值, 壳程数值
               FROM 产品设计活动表_设计数据表
               WHERE 产品ID = %s AND 参数名称 = '耐压试验温度'
           """, (product_id,))
    row = cursor.fetchone()
    raw_val = row["壳程数值"].strip() if row and row.get("壳程数值") else None
    guanban_a["耐压试验温度"] = raw_val
    cursor.execute("""
                   SELECT 参数名称, 参数值
                   FROM 产品设计活动表_元件附加参数表
                   WHERE 产品ID = %s AND 元件名称 = '固定管板'
               """, (product_id,))
    rows = cursor.fetchall()
    qt_data = {row["参数名称"]: str(row["参数值"]).strip() for row in rows if
               row["参数值"] not in (None, "", "None")}

    if qt_data.get("管程侧是否添加覆层") == "是":
        guanban_a["管板管程侧覆层厚度"] = qt_data.get("管程侧覆层厚度", "0")
    else:
        guanban_a["管板管程侧覆层厚度"] = "0"
    if qt_data.get("壳程侧是否添加覆层") == "是":
        guanban_a["管板壳程侧覆层厚度"] = qt_data.get("壳程侧覆层厚度", "0")
    else:
        guanban_a["管板壳程侧覆层厚度"] = "0"
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
        guanban_a[field] = safe_str(val)

    # ========== 液柱静压力 和 介质密度 ==========
    if "液柱静压力" in param_map:
        guanban_a["壳程液柱静压力"] = safe_str(param_map["液柱静压力"].get("壳程数值"))
        guanban_a["管程液柱静压力"] = safe_str(param_map["液柱静压力"].get("管程数值"))

    # === 元件参数映射关系 ===
    yuanjian_param = {
        ("管箱垫片", "垫片系数m"): "垫片系数",
        ("管箱垫片", "垫片比压力y"): "垫片比压力",
        ("管箱法兰", "法兰类型"): "管箱法兰类型",
        ("管箱法兰", "材料类型"): "管箱法兰材料类型",
        ("管箱法兰", "材料牌号"): "管箱法兰材料牌号",
        ("螺柱（管箱法兰）", "材料牌号"): "螺柱材料牌号",

    }

    # === 写入字段 ===
    for (comp, param), field in yuanjian_param.items():

        # =========================================================
        # ✅ 特殊逻辑：螺柱（前端管箱平盖）的材料牌号 → 去合并表找
        # =========================================================
        if comp == "螺柱（管箱法兰）" and param == "材料牌号" and field == "螺柱材料牌号":
            val, hit_tab, hit_cid = get_fastener_bolt_material_by_belong(
                cursor, product_id, belong_keyword="管箱法兰", is_stud=True
            )
            val = val or ""  # 没找到就空，后面 apply_special_defaults 会兜底（若你有默认）
            # 可选：调试用
            # print(f"[DEBUG] 前端管箱平盖螺柱材料牌号命中: {val}, tab={hit_tab}, 元件ID={hit_cid}")

        else:
            # ===== 原有逻辑：从 component_map 取值 =====
            val = component_map.get(comp, {}).get(param, "")

        # ===== 原有清洗逻辑保持不变 =====
        val = str(val).strip() if val is not None else ""
        if val.lower() == "none":
            val = ""
        if param in special_force_fields and val == "":
            val = "0"
        if field == "m":
            try:
                val = str(float(val))
            except:
                val = "3"

        guanban_a[field] = apply_special_defaults(field, val)

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
        guanban_a["管箱垫片材料"] = gasket_params["垫片材料"]
    if "垫片标准" in gasket_params:
        guanban_a["管箱垫片标准"] = gasket_params["垫片标准"]
    if "垫片类型" in gasket_params:
        guanban_a["管箱垫片型式"] = gasket_params["垫片类型"]

    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s
              AND 元件名称 = '管箱垫片'
              AND 参数名称 IN ('垫片名义外径D2n','垫片名义内径D1n')
        """, (product_id,))

    rows = cursor.fetchall()
    print("rows", rows)
    if rows:
        params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}
        guanban_a["管箱垫片外径"] = params.get("垫片名义外径D2n", "")
        if guanban_a["管箱垫片外径"] in ("程序推荐", ""):
            guanban_a["管箱垫片外径"] = "0"

        guanban_a["管箱垫片外径"] = params.get("垫片名义内径D1n", "")
        if guanban_a["管箱垫片外径"] in ("程序推荐", ""):
            guanban_a["管箱垫片外径"] = "0"

    # ======================================================
    # 根据 产品设计活动表_管板形式表.管板类型 映射管板符号
    # ======================================================

    def convert_fraction(val: str):
        """
        将 '1/4' 形式转换成小数 '0.25'，否则返回原值
        """
        try:
            if isinstance(val, str) and "/" in val:
                num, den = val.split("/")
                return str(float(num.strip()) / float(den.strip()))
        except Exception:
            pass
        return val

    def normalize_source_symbol(symbol):
        """
        数据库中的参数符号统一清洗：
        - 去空格
        - K/k 统一按小写 k 匹配
        """
        if symbol is None:
            return ""

        symbol = str(symbol).strip()
        symbol = symbol.replace(" ", "")
        symbol = symbol.replace("　", "")

        return symbol.lower()

    # 数据库原始符号 -> 当前管板类型下的真实符号
    guanban_symbol_map_by_type = {
        "e_a": {
            "d1": "a",
            "d2": "b",
            "d3": "c",
            "p": "d",
            "α1": "e",
            "α2": "f",
        },

        "e_b": {
            "R1": "a",
            "d1": "b",
            "d2": "c",
            "b": "d",
            "p": "e",
            "R2": "f",
            "d3": "g",
            "α": "h",
            "e": "j",
            "K": "k",
        },

        "e_c": {
            "p1": "a",
            "d1": "b",
            "R1": "c",
            "d2": "d",
            "b": "e",
            "R2": "f",
            "d3": "g",
            "α": "h",
            "e": "j",
            "p2": "l",
            "K": "k",
        },

        "e_d": {
            "R1": "a",
            "R2": "b",
            "d1": "c",
            "b": "d",
            "α1": "e",
            "α2": "f",
            "p": "g",
            "h": "h",
            "e": "j",
        },

        "e_e": {
            "R1": "a",
            "R2": "b",
            "α1": "c",
            "d1": "d",
            "b": "e",
            "α2": "f",
            "p": "g",
            "h": "h",
            "e": "j",
            "d2": "k",
        },

        "e_f": {
            "R1": "a",
            "h": "b",
            "α": "c",
            "p": "d",
            "e": "e",
        },

        "e_g": {
            "R1": "a",
            "R2": "b",
            "h": "c",
            "α": "d",
            "p": "e",
            "e": "f",
        },
    }

    conn = pymysql.connect(
        host="localhost",
        user="root",
        password="123456",
        database="产品设计活动库",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )

    cur = conn.cursor()

    # 1. 查询当前产品的管板类型
    cur.execute(
        """
        SELECT 管板类型
        FROM 产品设计活动表_管板形式表
        WHERE 产品ID = %s
          AND 管板类型 IS NOT NULL
          AND 管板类型 <> ''
        LIMIT 1
        """,
        (product_id,)
    )

    type_row = cur.fetchone()

    if not type_row:
        print(f"[管板形式] 产品ID={product_id} 未查询到管板类型，跳过管板符号覆盖。")
    else:
        guanban_type = str(type_row.get("管板类型")).strip()

        symbol_map = guanban_symbol_map_by_type.get(guanban_type)

        if not symbol_map:
            print(f"[管板形式] 未支持的管板类型：{guanban_type}，跳过管板符号覆盖。")
        else:
            # 2. 这里不要再加 参数符号 IN (...)
            # 否则数据库中符号有空格、大写、特殊写法时会被 SQL 直接过滤掉
            cur.execute(
                """
                SELECT 参数符号, 默认值
                FROM 产品设计活动表_管板形式表
                WHERE 产品ID = %s
                """,
                (product_id,)
            )

            rows = cur.fetchall()

            print(f"[管板形式] 产品ID={product_id}，管板类型={guanban_type}，共查询到 {len(rows)} 条参数记录")

            for row in rows:
                raw_symbol = row.get("参数符号")
                value = row.get("默认值")

                source_symbol = normalize_source_symbol(raw_symbol)

                print("原始符号:", raw_symbol, "清洗后符号:", source_symbol, "默认值:", value)

                if value in (None, "", "None", "none", "NULL", "null"):
                    continue

                # 当前管板类型下没有这个符号，则跳过
                if source_symbol not in symbol_map:
                    print(f"[管板形式] 符号 {raw_symbol} 不属于 {guanban_type} 的映射范围，跳过。")
                    continue

                target_symbol = symbol_map[source_symbol]
                final_value = convert_fraction(str(value))

                guanban_a[target_symbol] = final_value

                print(f"[管板形式] {raw_symbol} -> {target_symbol} = {final_value}")

            print(f"[管板形式] 产品ID={product_id}，管板类型={guanban_type}，符号映射完成。")



    # === 获取管箱垫片的垫片厚度 ===
    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱垫片' AND 参数名称 = '垫片厚度'
    """, (product_id,))
    row = cursor.fetchone()
    val = row["参数值"] if row and row["参数值"] not in (None, "", "None") else "4.5"
    guanban_a["垫片厚度"] = str(val)
    sql = """
                   SELECT 参数值
                   FROM 产品设计活动表_布管参数表
                   WHERE 产品ID = %s
                     AND 参数名 = '折流/支持板间距'
                   LIMIT 1
               """
    cursor.execute(sql, (product_id,))
    row = cursor.fetchone()
    if row:
        guanban_a["折流板间距"] = str(row["参数值"])  # 取参数值
    cursor.execute("""
           SELECT 参数名称, 参数值 
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
       """, (product_id,))
    extra_rows = cursor.fetchall()
    extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}


    if "材料类型" in extra_map:
        raw_type = extra_map["材料类型"]
        guanban_a["管箱圆筒材料类型"] = material_type_map.get(raw_type, raw_type)
    if "材料牌号" in extra_map:
        guanban_a["管箱圆筒材料名称"] = extra_map["材料牌号"]
    cursor.execute("""
           SELECT 参数名称, 参数值 
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s AND 元件名称 = '端部圆筒'
       """, (product_id,))
    extra_rows = cursor.fetchall()
    extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}
    if "材料类型" in extra_map:
        raw_type = extra_map["材料类型"]
        guanban_a["壳程圆筒端部材料类型"] = material_type_map.get(raw_type, raw_type)
    if "材料牌号" in extra_map:
        guanban_a["壳程圆筒端部材料名称"] = extra_map["材料牌号"]
    cursor.execute("""
           SELECT 参数名称, 参数值 
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s AND 元件名称 = '壳体圆筒'
       """, (product_id,))
    extra_rows = cursor.fetchall()
    extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}

    # 是否添加覆层

    if "材料类型" in extra_map:
        raw_type = extra_map["材料类型"]
        guanban_a["壳程圆筒材料类型"] = material_type_map.get(raw_type, raw_type)
    if "材料牌号" in extra_map:
        guanban_a["壳程圆筒材料名称"] = extra_map["材料牌号"]
    # ===== 获取公称直径、绝热厚度、毒性/爆炸危险等 =====
    cursor.execute("""
               SELECT 计算值名称, 计算值
               FROM 产品设计活动表_布管计算结果表
               WHERE 产品ID = %s
           """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["计算值名称"].strip(): row for row in rows}
    if "沿竖直隔板槽单侧的排管根数" in param_map:
        guanban_a["沿竖直隔板槽单侧的排管根数"] = str(param_map["沿竖直隔板槽单侧的排管根数"].get("计算值", "0"))
    if "'十字'交叉沿水平隔板槽单侧的排管根数" in param_map:
        guanban_a["'十字'交叉沿水平隔板槽单侧的排管根数"] = str(param_map["'十字'交叉沿水平隔板槽单侧的排管根数"].get("计算值", "0"))
    if "'丁字'交叉沿水平隔板槽连续侧的排管根数" in param_map:
        guanban_a["'丁字'交叉沿水平隔板槽连续侧的排管根数"] = str(param_map["'丁字'交叉沿水平隔板槽连续侧的排管根数"].get("计算值", "0"))
    if "'丁字'交叉沿水平隔板槽不连续侧的排管根数" in param_map:
        guanban_a["'丁字'交叉沿水平隔板槽不连续侧的排管根数"] = str(param_map["'丁字'交叉沿水平隔板槽不连续侧的排管根数"].get("计算值", "0"))
    if "'十字'交叉沿水平隔板槽单侧管排1最两端管孔中心距" in param_map:
        guanban_a["'十字'交叉沿水平隔板槽单侧管排1最两端管孔中心距"] = str(param_map["'十字'交叉沿水平隔板槽单侧管排1最两端管孔中心距"].get("计算值", "0"))
    if "'十字'交叉沿水平隔板槽单侧管排2最两端管孔中心距" in param_map:
        guanban_a["'十字'交叉沿水平隔板槽单侧管排2最两端管孔中心距"] = str(param_map["'十字'交叉沿水平隔板槽单侧管排2最两端管孔中心距"].get("计算值", "0"))
    if "'十字'交叉沿水平隔板槽单侧管排3最两端管孔中心距" in param_map:
        guanban_a["'十字'交叉沿水平隔板槽单侧管排3最两端管孔中心距"] = str(param_map["'十字'交叉沿水平隔板槽单侧管排3最两端管孔中心距"].get("计算值", "0"))
    if "'丁字'交叉沿水平隔板槽不连续侧管排1最两端管孔中心距" in param_map:
        guanban_a["'丁字'交叉沿水平隔板槽不连续侧管排1最两端管孔中心距"] = str(param_map["'丁字'交叉沿水平隔板槽不连续侧管排1最两端管孔中心距"].get("计算值", "0"))
    if "'丁字'交叉沿水平隔板槽不连续侧管排2最两端管孔中心距" in param_map:
        guanban_a["'丁字'交叉沿水平隔板槽不连续侧管排2最两端管孔中心距"] = str(param_map["'丁字'交叉沿水平隔板槽不连续侧管排2最两端管孔中心距"].get("计算值", "0"))
    if "'丁字'交叉沿水平隔板槽不连续侧管排3最两端管孔中心距" in param_map:
        guanban_a["'丁字'交叉沿水平隔板槽不连续侧管排3最两端管孔中心距"] = str(param_map["'丁字'交叉沿水平隔板槽不连续侧管排3最两端管孔中心距"].get("计算值", "0"))
    if "沿竖直隔板槽单侧的管排最两端管孔中心距" in param_map:
        guanban_a["沿竖直隔板槽单侧的管排最两端管孔中心距"] = str(param_map["沿竖直隔板槽单侧的管排最两端管孔中心距"].get("计算值", "0"))
    if "相邻隔板槽中心距" in param_map:
        guanban_a["相邻隔板槽中心距"] = str(param_map["相邻隔板槽中心距"].get("计算值", "0"))
    if "沿水平隔板槽一侧的排管根数" in param_map:
        guanban_a["沿水平隔板槽一侧的排管根数"] = str(param_map["沿水平隔板槽一侧的排管根数"].get("计算值", "0"))

    cursor.execute("""
        SELECT 管板类型 FROM 产品设计活动表_管板形式表
        WHERE 产品ID = %s
    """, (product_id,))
    row = cursor.fetchone()

    if row and row.get("管板类型"):
        gb_type_raw = str(row["管板类型"]).strip()

        # 安全 split
        parts = gb_type_raw.split("_")
        gb_type = parts[1] if len(parts) > 1 else parts[0]

        # 写入大字段
        guanban_a["管板与壳体/管箱的连接序号"] = gb_type

        # 准备第二次查询
        cursor2 = conn.cursor()

        if gb_type == "c":
            cursor2.execute("""
                SELECT 默认值 FROM 产品设计活动表_管板形式表
                WHERE 产品ID=%s AND 参数符号='f'
            """, (product_id,))
            row_f = cursor2.fetchone()

            if row_f and row_f.get("默认值") is not None:
                val = str(row_f["默认值"])
                guanban_a["管程侧应力释放槽深度"] = val
                guanban_a["壳程侧应力释放槽深度"] = val
            else:
                guanban_a["管程侧应力释放槽深度"] = "0"
                guanban_a["壳程侧应力释放槽深度"] = "0"

        elif gb_type == "e":
            cursor2.execute("""
                SELECT 默认值 FROM 产品设计活动表_管板形式表
                WHERE 产品ID=%s AND 参数符号='q'
            """, (product_id,))
            row_q = cursor2.fetchone()

            if row_q and row_q.get("默认值") is not None:
                guanban_a["管程侧应力释放槽深度"] = "0"
                guanban_a["壳程侧应力释放槽深度"] = str(row_q["默认值"])
            else:
                guanban_a["管程侧应力释放槽深度"] = "0"
                guanban_a["壳程侧应力释放槽深度"] = "0"

        else:
            guanban_a["管程侧应力释放槽深度"] = "0"
            guanban_a["壳程侧应力释放槽深度"] = "0"

    # === 获取管箱垫片的垫片厚度 ===
    # cursor.execute("""
    #     SELECT 参数值
    #     FROM 产品设计活动表_元件附加参数表
    #     WHERE 产品ID = %s AND 元件名称 = '管箱垫片' AND 参数名称 = '垫片厚度'
    # """, (product_id,))
    # row = cursor.fetchone()
    # val = row["参数值"] if row and row["参数值"] not in (None, "", "None") else "4.5"
    # guanban_a["垫片厚度"] = str(val)
    # 查询固定管板削弱系数
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s
          AND 元件名称 = '换热管'
          AND 参数名称 IN ('换热管外径')
    """, (product_id,))

    rows = cursor.fetchall()
    if rows:
        params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}
        guanban_a["换热管外径"] = params.get("换热管外径", "")

    # 查询固定管板削弱系数
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s
          AND 元件名称 = '固定管板'
          AND 参数名称 IN ('管板强度削弱系数','管板刚度削弱系数','管程侧分程隔板槽深度','壳程侧分程隔板槽深度')
    """, (product_id,))

    rows = cursor.fetchall()
    if rows:
        params = {row.get("参数名称"): safe_str(row.get("参数值")) for row in rows}
        guanban_a["管板强度削弱系数"] = params.get("管板强度削弱系数", "")
        guanban_a["管板刚度削弱系数"] = params.get("管板刚度削弱系数", "")
        guanban_a["管程侧隔板槽深度"] = params.get("管程侧分程隔板槽深度", "")
        guanban_a["壳程侧隔板槽深度"] = params.get("壳程侧分程隔板槽深度", "")
    import pymysql
    # 查询固定管板参数：是否可以保证在任何情况下管壳程压力都能同时作用
    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s
          AND 元件名称 = '固定管板'
          AND 参数名称 = '是否可以保证在任何情况下管壳程压力都能同时作用'
    """, (product_id,))

    row = cursor.fetchone()
    if safe_str(row.get("参数值")) == "是":
        guanban_a["是否可以保证在任何情况下管壳程压力都能同时作用"] = "1"
    else:
        guanban_a["是否可以保证在任何情况下管壳程压力都能同时作用"] = "0"

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  #   手动创建游标，不会自动关闭

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
        print(f"  查询失败: {e}")

        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  #   不使用 with，游标保持可用

        # === 查询管程分程形式 ===
        cursor.execute("""
                SELECT 参数值 
                FROM 产品设计活动表_布管参数表
                WHERE 产品ID = %s AND 参数名 = '管程分程形式'
                LIMIT 1
            """, (product_id,))
        row = cursor.fetchone()
        tube_form = row["参数值"].strip() if row and row.get("参数值") else None



    fenchengxingshi = f"{tube_form}" if tube_form else ""
    # === 处理查询结果并赋值给 design_params ===
    if fenchengxingshi:
        guanban_a["管/壳程布置型式"] = fenchengxingshi
        if fenchengxingshi == "2" or fenchengxingshi == None or fenchengxingshi == "":
            guanban_a["管/壳程布置型式"] ="2.1"
    else:
        print(f" ️ 未找到 产品ID={product_id} 的管程程数或壳程程数")
        guanban_a["管/壳程布置型式"] = ""
    print("fenchengxingshi",fenchengxingshi)

    e_val = 0.0
    g_val = 0.0
    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  #   手动创建游标，不会自动关闭

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
        print(f"  查询失败: {e}")
    print(e_val)
    print(g_val)
    # === 求和并写入 guanban_a ===
    sum_val = round(e_val + g_val, 1)  # 保留1位小数

    if "焊脚高度" in guanban_a:
        if sum_val == 0:
            guanban_a["焊脚高度"] = "3.5"
        else:
            guanban_a["焊脚高度"] = str(sum_val)


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
        guanban_a["管箱圆筒实际内径"] = str(param_map["公称直径*"].get("管程数值", "0"))
        guanban_a["壳程圆筒实际内径"] = str(param_map["公称直径*"].get("壳程数值", "0"))
    if "沿长度平均的换热管金属温度*" in param_map:
        guanban_a["沿长度平均的换热管金属温度"] = str(param_map["沿长度平均的换热管金属温度*"].get("管程数值", "0"))
    if "沿长度平均的壳程圆筒金属温度*" in param_map:
        guanban_a["沿长度平均的壳程圆筒金属温度"] = str(param_map["沿长度平均的壳程圆筒金属温度*"].get("壳程数值", "0"))
    if "焊接接头系数*" in param_map:
        guanban_a["管程圆筒环向焊接接头系数"] = str(param_map["焊接接头系数*"].get("管程数值", "0"))
    if "腐蚀裕量*" in param_map:
        guanban_a["管程腐蚀裕量"] = str(param_map["腐蚀裕量*"].get("管程数值", "0"))
        guanban_a["壳程腐蚀裕量"] = str(param_map["腐蚀裕量*"].get("壳程数值", "0"))
    media_parts = []
    if "介质特性（爆炸危险程度）" in param_map:
        expl = param_map["介质特性（爆炸危险程度）"].get("壳程数值", "")
        if expl == "可燃":
            media_parts.append("介质可燃")
        elif expl == "易爆":
            media_parts.append("介质易爆")
    if "介质特性（毒性危害程度）" in param_map:
        shell_toxic = param_map["介质特性（毒性危害程度）"].get("壳程数值", "")
        tube_toxic = param_map["介质特性（毒性危害程度）"].get("管程数值", "-")
        if shell_toxic:
            media_parts.append(f"{shell_toxic}危害")
        if tube_toxic:
            media_parts.append(f"{tube_toxic}危害")

    if media_parts:
        guanban_a["换热管使用场合"] = "/".join(media_parts)
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '换热管'
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
    # if "壳程侧分程隔板槽深度" in param_map:
    #     guanban_a["壳程侧结构开槽深度"] = str(param_map["壳程侧分程隔板槽深度"])
    # if "管程侧分程隔板槽深度" in param_map:
    #     guanban_a["管程侧结构开槽深度"] = str(param_map["管程侧分程隔板槽深度"])
    if "壳程圆筒环向焊接接头系数" in param_map:
        guanban_a["壳程圆筒环向焊接接头系数"] = str(param_map["壳程圆筒环向焊接接头系数"])

    # 更新 guanban_a 字典中的材料类型和材料牌号
    if "材料类型" in param_map:
        guanban_a["管板材料类型"] = str(param_map["材料类型"])
    if "材料牌号" in param_map:
        guanban_a["管板材料名称"] = str(param_map["材料牌号"])
    # === 参数名和 guanban_a 键的映射 ===
    mapping = {
        "换热管壁厚 δ": "换热管壁厚",
        "换热管公称长度 LN": "换热管直管段长度"
    }

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  #   手动管理游标

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
        print(f"  查询失败: {e}")

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
    # cursor.execute("""
    #     SELECT 参数值
    #     FROM 产品设计活动表_元件附加参数表
    #     WHERE 产品ID = %s AND 元件名称 = '换热管' AND 参数名称 = '材料类型'
    # """, (product_id,))
    # row = cursor.fetchone()
    #
    # # 判断是否为钢材或钢管
    # if row:
    #     material_type = str(row["参数值"]).strip()
    #     if "钢" in material_type:
    #         guanban_a["换热管是否钢材"] = "1"
    #     else:
    #         guanban_a["换热管是否钢材"] = "0"
    # else:
    #     guanban_a["换热管是否钢材"] = "0"  # 默认非钢材
    # 查询布管数量表中所有管孔数量（上）与（下）


    # 设置根数，若为 0 则使用默认值 220
    # guanban_a["换热管根数"] = str(int(total_count) if total_count else 220)

    # # 查询元件名称为“管箱垫片”的所有参数
    # cursor.execute("""
    #     SELECT 参数名称, 参数值
    #     FROM 产品设计活动表_元件附加参数表
    #     WHERE 产品ID = %s AND 元件名称 = '管箱垫片'
    # """, (product_id,))
    # rows = cursor.fetchall()
    #
    # # 构建一个参数名称 → 参数值 的字典
    # gasket_params = {row["参数名称"].strip(): str(row["参数值"]).strip() for row in rows if row["参数值"] is not None}
    #
    # # 写入 guanban_a 字典中
    # if "垫片材料" in gasket_params:
    #     guanban_a["垫片材料名称"] = gasket_params["垫片材料"]
    #
    # if "压紧面形状" in gasket_params:
    #     guanban_a["压紧面形式"] = gasket_params["压紧面形状"]
    # if "垫片与密封面接触内径D1" in gasket_params:
    #     guanban_a["垫片与密封面接触内径"] = gasket_params["垫片与密封面接触内径D1"]
    # if "垫片与密封面接触外径D2" in gasket_params:
    #     guanban_a["垫片与密封面接触外径"] = gasket_params["垫片与密封面接触外径D2"]
    # if "垫片与密封面接触内径D1" in gasket_params:
    #     guanban_a["垫片与密封面接触内径"] = gasket_params["垫片与密封面接触内径D1"]
    # if "垫片名义外径D2n" in gasket_params:
    #     guanban_a["垫片名义外径"] = gasket_params["垫片名义外径D2n"]
    #     if guanban_a["垫片名义外径"] == "程序推荐":
    #         guanban_a["垫片名义外径"] ='0'
    #
    # if "垫片名义内径D1n" in gasket_params:
    #     guanban_a["垫片名义内径"] = gasket_params["垫片名义内径D1n"]
    #     if guanban_a["垫片名义内径"] == "程序推荐":
    #         guanban_a["垫片名义内径"] ='0'
    # 查询布管参数表中该产品的所有参数
    # 定义排列形式映射字典

    # 默认值配置

    # if "隔板槽两侧相邻管中心距Sn(水平)" in tube_params:
    #     guanban_a["水平隔板槽两侧相邻管中心距"] = tube_params["隔板槽两侧相邻管中心距Sn(水平)"]
    # if "隔板槽两侧相邻管中心距Sn(竖直)" in tube_params:
    #     guanban_a["垂直隔板槽两侧相邻管中心距"] = tube_params["隔板槽两侧相邻管中心距Sn(竖直)"]

    tube_bundle = {
        "实际布管区域最大直径": "960", #1
        "实际布管区域最大高度": "200", #1
        # "导流筒边缘过水平中心线距离": "50", #无
        # "导流筒厚度": "3", #导流筒
        "旁路挡板厚度": "11", #1
        # "导流筒内部折边倒角": "2", #无
        "换热管壁厚": "2", #1
        "换热管孔间距": s_val,  #1
        "接管布置型式": "1",  #1
        "管程数": "2", #1
        "换热管排列方式": "正三角形",#1
        "折流板切口方向": "水平",#1
        "水平分程隔板槽两侧相邻管中心距水平上下": sn_val, #1
        "竖直分程隔板槽两侧相邻管中心距垂直左右": snh_val,#1
        "水平分程隔板槽数量": "1",#1
        "竖直分程隔板槽数量": "0",#1
        "布管限定圆直径": "784",#1
        "换热管理论直管长度": "6000", #1
        "换热管伸出管板值": "4.5", #1
        "折流板切口与中心线间距": "300",  #1
        # "圆筒内径": "800", #布管，壳体内直径
        "公称直径": "1000", #1
        "圆筒名义厚度": "12",#1
        "管板类型": "e", #1
        "管板凸台高度": "5", #1
        "垫片厚度": "4.5", #1
        # "管板与壳程圆筒连接台肩长度": "0", #无
        "折流板需求间距": "350", #1
        "入口OD1/OD2": "OD1", #1
        "拉杆类型": "螺纹拉杆", #1
        "拉杆用螺母厚度": "16", #1
        "换热管外径": "19", #1
        "折流板厚度初始值": "3", #1
        "换热管材料序号": "1", #1
        "拉杆直径": "", #1
        "换热管材料类型": "钢管", #1
        "换热管材料牌号": "10(GB8163)",#1
        # "内折流板材料牌号":'',
        # "内折流板材料类型": '',
        # "异形折流板材料牌号": '',
        # "异形折流板材料类型": '',
        "弓形折流板材料类型": '',  # 1
        "弓形折流板材料牌号": '', # 1
        "中间挡板材料类型": '',  # 1
        # "支撑板材料牌号": '',
        # "支撑板材料类型": '',
        # "导流筒材料牌号": '',
        # "导流筒材料类型": '',
        "中间挡板材料牌号": '',#1
        "支持板材料类型": '',  # 1
        "支持板材料牌号": '', #1
        "滑道材料类型": '',  # 1
        "滑道材料牌号": '',#1
        "中间挡管材料类型": '',  # 1
        "中间挡管材料牌号": '',#1
        "堵板材料类型": '',  # 1
        "堵板材料牌号": '',#1
        "防冲挡板材料类型": '',  # 1
        "防冲挡板材料牌号": '',#1
        "拉杆材料类型": '',  # 1
        "拉杆材料牌号": '',#1
        "定距管材料类型": '',  # 1
        "定距管材料牌号": '',#1

        "滑道高度": '',#1
        "滑道厚度": '',#1
        "防冲挡板宽度": '',#1
        "防冲挡板厚度": '',#1
        "中间挡板宽度": '',#1
        "中间挡板厚度": '',#1
        # "管板与壳程圆筒搭接长度": "3",
        "管板与壳体/管箱的连接序号": "b", # 1
        "换热管数量NX": "",  # 1
        "换热管数量NXA": "",  # 1
        "换热管数量NY": "",  # 1
        "换热管数量NYA": "",  # 1
        "管束级别": "",  # 1
        "折流板类型": "",  # 1

    }
    cursor.execute("""
                SELECT 参数值
                FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件名称 = '换热管' AND 参数名称 = '管束级别'
            """, (product_id,))
    row = cursor.fetchone()
    val = row["参数值"] if row and row["参数值"] not in (None, "", "None") else ""
    if val == "Ⅰ":
        val = "1"
    if val == "Ⅱ":
        val = "2"
    tube_bundle["管束级别"] = str(val)
    cursor.execute("""
                SELECT 参数值 
                FROM 产品设计活动表_布管参数表
                WHERE 产品ID = %s AND 参数名 = '折流板类型'
                LIMIT 1
            """, (product_id,))
    row = cursor.fetchone()
    tube_bundle["折流板类型"] = row["参数值"].strip() if row and row.get("参数值") else ""
    cursor.execute("""
               SELECT 计算值名称, 计算值
               FROM 产品设计活动表_布管计算结果表
               WHERE 产品ID = %s
           """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["计算值名称"].strip(): row for row in rows}

    if "换热管数量NX" in param_map:
        tube_bundle["换热管数量NX"] = str(param_map["换热管数量NX"].get("计算值", "0"))
    if "换热管数量NXA" in param_map:
        tube_bundle["换热管数量NXA"] = str(param_map["换热管数量NXA"].get("计算值", "0"))
    if "换热管数量NY" in param_map:
        tube_bundle["换热管数量NY"] = str(param_map["换热管数量NY"].get("计算值", "0"))
    if "换热管数量NYA" in param_map:
        tube_bundle["换热管数量NYA"] = str(param_map["换热管数量NYA"].get("计算值", "0"))
    cursor.execute("""
        SELECT 管板类型 FROM 产品设计活动表_管板形式表
        WHERE 产品ID = %s
    """, (product_id,))
    row = cursor.fetchone()

    if row and row.get("管板类型"):
        gb_type_raw = str(row["管板类型"]).strip()

        # 安全 split
        parts = gb_type_raw.split("_")
        gb_type = parts[1] if len(parts) > 1 else parts[0]

        # 写入大字段
        tube_bundle["管板与壳体/管箱的连接序号"] = gb_type
    # ===== 获取公称直径、绝热厚度、毒性/爆炸危险等 =====
    cursor.execute("""
                  SELECT 计算值名称, 计算值
                  FROM 产品设计活动表_布管计算结果表
                  WHERE 产品ID = %s
              """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["计算值名称"].strip(): row for row in rows}
    if "实际布管区域最大直径" in param_map:
        tube_bundle["实际布管区域最大直径"] = str(param_map["实际布管区域最大直径"].get("计算值", "0"))
    if "实际布管区域最大高度" in param_map:
        tube_bundle["实际布管区域最大高度"] = str(
            param_map["实际布管区域最大高度"].get("计算值", "0"))
    # === 查询布管元件表中该产品ID的元件类型和滑道布置情况 ===
    cursor.execute("""
        SELECT 元件类型, 是否布置滑道
        FROM 产品设计活动表_布管元件表
        WHERE 产品ID = %s
    """, (product_id,))
    element_rows = cursor.fetchall()

    # 元件类型集合
    element_types = {row["元件类型"] for row in element_rows}
    # 是否布置滑道
    has_slide = any(row["是否布置滑道"] == 1 for row in element_rows)

    # === 查询布管参数表中对应参数值 ===
    cursor.execute("""
        SELECT 参数名, 参数值
        FROM 产品设计活动表_布管参数表
        WHERE 产品ID = %s
          AND 参数名 IN (
              '滑道高度', '滑道厚度', 
              '防冲板宽度', '防冲板厚度',
              '中间挡板宽度', '中间挡板厚度'
          )
    """, (product_id,))
    params = {row["参数名"]: row["参数值"] for row in cursor.fetchall()}

    # === 填充 tube_bundle 字典 ===

    # 滑道参数
    tube_bundle["滑道高度"] = params.get("滑道高度", 0) if has_slide else 0
    tube_bundle["滑道厚度"] = params.get("滑道厚度", 0) if has_slide else 0
    # 中间挡板
    tube_bundle["中间挡板宽度"] = params.get("中间挡板宽度", 0) if 4 in element_types else 0
    if 4 in element_types:
        val = params.get("中间挡板厚度", 0)
        val_str = str(val).strip()  # 转为字符串并去掉首尾空格
        if val_str in("程序推荐"," ","",None,"None") :
            val_str = "0"
        tube_bundle["中间挡板厚度"] = val_str
    else:
        tube_bundle["中间挡板厚度"] = "0"

    # 防冲挡板
    tube_bundle["防冲挡板宽度"] = params.get("防冲板宽度", 0) if 5 in element_types or 6 in element_types else 0
    tube_bundle["防冲挡板厚度"] = params.get("防冲板厚度", 0) if 5 in element_types or 6 in element_types else 0


    # cursor.execute("""
    #             SELECT 参数值
    #             FROM 产品设计活动表_元件附加参数表
    #             WHERE 产品ID = %s AND 元件名称 = '内导流筒' AND 参数名称 = '导流筒直边高度'
    #         """, (product_id,))
    # row = cursor.fetchone()
    #
    # tube_bundle["导流筒边缘过水平中心线距离"] = str(row["参数值"]).strip()

    #
    # cursor.execute("""
    #             SELECT 参数值
    #             FROM 产品设计活动表_元件附加参数表
    #             WHERE 产品ID = %s AND 元件名称 = '内导流筒' AND 参数名称 = '倒圆半径'
    #         """, (product_id,))
    # row = cursor.fetchone()
    #
    # tube_bundle["导流筒内部折边倒角"] = str(row["参数值"]).strip()



    sql = """
            SELECT 参数值
            FROM 产品设计活动表_管板连接表
            WHERE 产品ID = %s
              AND 参数名 = '换热管伸出管板长度 L'
            LIMIT 1
        """
    cursor.execute(sql, (product_id,))
    row = cursor.fetchone()
    if row:
        tube_bundle["换热管伸出管板值"] = str(row["参数值"])  # 取参数值

    sql = """
                   SELECT 参数值
                   FROM 产品设计活动表_布管参数表
                   WHERE 产品ID = %s
                     AND 参数名 = '折流/支持板间距'
                   LIMIT 1
               """
    cursor.execute(sql, (product_id,))
    row = cursor.fetchone()
    if row:
        tube_bundle["折流板需求间距"] = str(row["参数值"])  # 取参数值
    sql = """
           SELECT 管口功能, `周向方位（°）`
           FROM 产品设计活动表_管口表
           WHERE 产品ID = %s
             AND 管口功能 IN ('壳程入口', '壳程出口')
       """
    cursor.execute(sql, (product_id,))
    rows = cursor.fetchall()

    # 2. 提取周向方位
    orientations = [row["周向方位（°）"] for row in rows if row.get("周向方位（°）") is not None]

    if len(orientations) < 2:
        print(" ️ 未找到两个管口（壳程入口/出口），无法判定")
        layout_type = None
    else:
        layout_type = "2" if orientations[0] == orientations[1] else "1"

    tube_bundle["接管布置型式"] = layout_type


    # 查询换热管材料级别
    cursor.execute("""
        SELECT 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s
          AND 元件名称 = '换热管'
          AND 参数名称 = '材料级别'
    """, (product_id,))

    row = cursor.fetchone()
    if row:
        raw_value = safe_str(row.get("参数值"))
        roman_to_arabic = {
            "Ⅰ": "1", "Ⅱ": "2", "Ⅲ": "3",
            "Ⅳ": "4", "Ⅴ": "5", "Ⅵ": "6"
        }
        tube_bundle["换热管材料序号"] = roman_to_arabic.get(raw_value, raw_value)

    # === 参数名和 guanban_a 键的映射 ===
    mapping = {
        "换热管壁厚 δ": "换热管壁厚",
        "换热管公称长度 LN": "换热管理论直管长度"
    }

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  #   手动管理游标

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
                    tube_bundle[target_key] = str(float(val)).rstrip("0").rstrip(".")
                except ValueError:
                    tube_bundle[target_key] = val

    except Exception as e:
        print(f"  查询失败: {e}")
    import pymysql
    # 查询固定管板参数：是否可以保证在任何情况下管壳程压力都能同时作用
    # cursor.execute("""
    #     SELECT 参数值
    #     FROM 产品设计活动表_元件附加参数表
    #     WHERE 产品ID = %s
    #       AND 元件名称 = '内导流筒'
    #       AND 参数名称 = '导流筒厚度'
    # """, (product_id,))
    #
    # row = cursor.fetchone()
    # if row:
    #     tube_bundle["导流筒厚度"] = safe_str(row.get("参数值"))
    cursor.execute("""
            SELECT 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s
              AND 元件名称 = '旁路挡板'
              AND 参数名称 = '旁路挡板厚度'
        """, (product_id,))

    row = cursor.fetchone()
    if row:
        tube_bundle["旁路挡板厚度"] = safe_str(row.get("参数值"))
    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  #   手动创建游标，不会自动关闭

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
        print(f"  查询失败: {e}")

    # 默认值
    buguan_dl_value = "784"

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  #   手动管理游标

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
            buguan_dl_value = "784"  #   可以保持默认值逻辑

    except Exception as e:
        print(f"  查询失败: {e}")

    #   写入目标字典
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
        cursor = conn.cursor()  #   不使用 with，游标不会自动关闭

        # # === 壳体内直径 Di ===
        # cursor.execute("""
        #     SELECT 参数值
        #     FROM 产品设计活动表_布管参数表
        #     WHERE 产品ID = %s AND 参数名 = '壳体内直径 Di'
        #     LIMIT 1
        # """, (product_id,))
        # row = cursor.fetchone()
        # if row and row.get("参数值") not in (None, "", " "):
        #     tube_bundle["圆筒内径"] = str(row["参数值"]).strip()

        # === 折流板切口与中心线间距 ===
        # === 折流板切口与中心线间距 ===
        cursor.execute("""
                SELECT 参数值 
                FROM 产品设计活动表_布管参数表
                WHERE 产品ID = %s AND 参数名 = '折流板类型'
                LIMIT 1
            """, (product_id,))
        row = cursor.fetchone()
        if row and row.get("参数值") == "双弓形":
            cursor.execute("""
                                       SELECT 参数值 
                                       FROM 产品设计活动表_布管参数表
                                       WHERE 产品ID = %s AND 参数名 = 'A型板切口与中心线间距a'
                                       LIMIT 1
                                   """, (product_id,))
            row2 = cursor.fetchone()
            tube_bundle["折流板切口与中心线间距"] = str(row2["参数值"]).strip()
        else:
            cursor.execute("""
                                SELECT 参数值 
                                FROM 产品设计活动表_布管参数表
                                WHERE 产品ID = %s AND 参数名 = '折流板切口与中心线间距a'
                                LIMIT 1
                            """, (product_id,))
            row1 = cursor.fetchone()

            tube_bundle["折流板切口与中心线间距"] = str(row1["参数值"]).strip()

    except Exception as e:
        print(f"  查询失败: {e}")

    cursor.execute("""
        SELECT 管口功能, 轴向定位基准, 轴向定位距离
        FROM 产品设计活动表_管口表
        WHERE 产品ID = %s AND 管口功能 IN ('壳程入口', '壳程出口')
    """, (product_id,))
    rows = cursor.fetchall()

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

        # 新规则：入口/出口分别判断
        if base_in == "左基准线":
            val = "OD1"
        elif base_out == "左基准线":
            val = "OD2"
        else:
            # 如果都不是左基准线，保持一个默认逻辑（可按需要调整）
            # 这里用入口在前：优先OD1
            val = "OD1"

        tube_bundle["入口OD1/OD2"] = val
    else:
        print("  缺少壳程入口或壳程出口的管口信息")

    try:
        conn = pymysql.connect(
            host="localhost", user="root", password="123456",
            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()  #   不使用 with，游标保持可用
        # === 读取管程数 ===
        cursor.execute("""
                   SELECT 参数值 
                   FROM 产品设计活动表_布管参数表
                   WHERE 产品ID = %s AND 参数名 = '管程程数'
                   LIMIT 1
               """, (product_id,))
        row = cursor.fetchone()
        tube_passes1 = row["参数值"].strip() if row and row.get("参数值") else ""
        tube_bundle["管程数"] = tube_passes1

        # === 读取管程数 ===
        cursor.execute("""
            SELECT 参数值 
            FROM 产品设计活动表_布管参数表
            WHERE 产品ID = %s AND 参数名 = '管程分程形式'
            LIMIT 1
        """, (product_id,))
        row = cursor.fetchone()
        tube_passes = row["参数值"].strip() if row and row.get("参数值") else ""
        print("tube_passes",tube_passes)
        # === 根据管程数设置分程隔板槽数量 ===
        if tube_passes == "2.1":
            tube_bundle["水平分程隔板槽数量"] = "1"
            tube_bundle["竖直分程隔板槽数量"] = "0"
        elif tube_passes == "4.2":
            tube_bundle["水平分程隔板槽数量"] = "1"
            tube_bundle["竖直分程隔板槽数量"] = "1"
        elif tube_passes == "4.1":
            tube_bundle["水平分程隔板槽数量"] = "3"
            tube_bundle["竖直分程隔板槽数量"] = "0"
        elif tube_passes == "4.3":
            tube_bundle["水平分程隔板槽数量"] = "2"
            tube_bundle["竖直分程隔板槽数量"] = "1"
        elif tube_passes == "6.1":
            tube_bundle["水平分程隔板槽数量"] = "3"
            tube_bundle["竖直分程隔板槽数量"] = "1"
        elif tube_passes == "6.2":
            tube_bundle["水平分程隔板槽数量"] = "2"
            tube_bundle["竖直分程隔板槽数量"] = "1"
        else:
            tube_bundle["水平分程隔板槽数量"] = "0"
            tube_bundle["竖直分程隔板槽数量"] = "0"

    except Exception as e:
        print(f"  查询失败: {e}")

    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '换热管'
    """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row["参数值"] for row in rows}

    # 遍历所有返回的参数，构建映射
    if param_map:
        if param_map.get("材料类型"):
            tube_bundle["换热管材料类型"] = param_map["材料类型"]
        if param_map.get("材料牌号"):
            tube_bundle["换热管材料牌号"] = param_map["材料牌号"]
    # cursor.execute("""
    #     SELECT 参数名称, 参数值
    #     FROM 产品设计活动表_元件附加参数表
    #     WHERE 产品ID = %s AND 元件名称 = '异形折流板'
    # """, (product_id,))
    # rows = cursor.fetchall()
    # param_map = {row["参数名称"].strip(): row["参数值"] for row in rows}
    #
    # # 遍历所有返回的参数，构建映射
    # if param_map:
    #     if param_map.get("材料类型"):
    #         tube_bundle["异形折流板材料牌号"] = param_map["材料牌号"]
    #         tube_bundle["异形折流板材料类型"] = param_map["材料类型"]
    #     if param_map.get("材料牌号"):
    # cursor.execute("""
    #     SELECT 参数名称, 参数值
    #     FROM 产品设计活动表_元件附加参数表
    #     WHERE 产品ID = %s AND 元件名称 = '内折流板'
    # """, (product_id,))
    # rows = cursor.fetchall()
    # param_map = {row["参数名称"].strip(): row["参数值"] for row in rows}
    # if param_map:
    #     if param_map.get("材料类型"):
    #         tube_bundle["内折流板材料类型"] = param_map["材料类型"]
    #     if param_map.get("材料牌号"):
    #         tube_bundle["内折流板材料牌号"] = param_map["材料牌号"]
    cursor.execute("""
         SELECT 参数名称, 参数值
         FROM 产品设计活动表_元件附加参数表
         WHERE 产品ID = %s AND 元件名称 = '折流板'
     """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row["参数值"] for row in rows}
    if param_map:
        if param_map.get("材料类型"):
            tube_bundle["弓形折流板材料类型"] = param_map["材料类型"]
        if param_map.get("材料牌号"):
            tube_bundle["弓形折流板材料牌号"] = param_map["材料牌号"]
    # cursor.execute("""
    #      SELECT 参数名称, 参数值
    #      FROM 产品设计活动表_元件附加参数表
    #      WHERE 产品ID = %s AND 元件名称 = '支撑板'
    #  """, (product_id,))
    # rows = cursor.fetchall()
    # param_map = {row["参数名称"].strip(): row["参数值"] for row in rows}
    # if param_map:
    #     if param_map.get("材料类型"):
    #         tube_bundle["支撑板材料类型"] = param_map["材料类型"]
    #     if param_map.get("材料牌号"):
    #         tube_bundle["支撑板材料牌号"] = param_map["材料牌号"]
    # cursor.execute("""
    #      SELECT 参数名称, 参数值
    #      FROM 产品设计活动表_元件附加参数表
    #      WHERE 产品ID = %s AND 元件名称 = '内导流筒'
    #  """, (product_id,))
    # rows = cursor.fetchall()
    # param_map = {row["参数名称"].strip(): row["参数值"] for row in rows}
    # if param_map:
    #     if param_map.get("材料类型"):
    #         tube_bundle["导流筒材料类型"] = param_map["材料类型"]
    #     if param_map.get("材料牌号"):
    #         tube_bundle["导流筒材料牌号"] = param_map["材料牌号"]

    cursor.execute("""
         SELECT 参数名称, 参数值
         FROM 产品设计活动表_元件附加参数表
         WHERE 产品ID = %s AND 元件名称 = '支持板'
     """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row["参数值"] for row in rows}
    if param_map:
        if param_map.get("材料类型"):
            tube_bundle["支持板材料类型"] = param_map["材料类型"]
        if param_map.get("材料牌号"):
            tube_bundle["支持板材料牌号"] = param_map["材料牌号"]

    cursor.execute("""
         SELECT 参数名称, 参数值
         FROM 产品设计活动表_元件附加参数表
         WHERE 产品ID = %s AND 元件名称 = '滑道'
     """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row["参数值"] for row in rows}
    if param_map:
        if param_map.get("材料类型"):
            tube_bundle["滑道材料类型"] = param_map["材料类型"]
        if param_map.get("材料牌号"):
            tube_bundle["滑道材料牌号"] = param_map["材料牌号"]
    cursor.execute("""
         SELECT 参数名称, 参数值
         FROM 产品设计活动表_元件附加参数表
         WHERE 产品ID = %s AND 元件名称 = '挡管'
     """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row["参数值"] for row in rows}
    if param_map:
        if param_map.get("材料类型"):
            tube_bundle["中间挡管材料类型"] = param_map["材料类型"]
        if param_map.get("材料牌号"):
            tube_bundle["中间挡管材料牌号"] = param_map["材料牌号"]
    cursor.execute("""
         SELECT 参数名称, 参数值
         FROM 产品设计活动表_元件附加参数表
         WHERE 产品ID = %s AND 元件名称 = '中间挡板'
     """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row["参数值"] for row in rows}
    if param_map:
        if param_map.get("材料类型"):
            tube_bundle["中间挡板材料类型"] = param_map["材料类型"]
        if param_map.get("材料牌号"):
            tube_bundle["中间挡板材料牌号"] = param_map["材料牌号"]
    cursor.execute("""
         SELECT 参数名称, 参数值
         FROM 产品设计活动表_元件附加参数表
         WHERE 产品ID = %s AND 元件名称 = '堵板'
     """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row["参数值"] for row in rows}
    if param_map:
        if param_map.get("材料类型"):
            tube_bundle["堵板材料类型"] = param_map["材料类型"]
        if param_map.get("材料牌号"):
            tube_bundle["堵板材料牌号"] = param_map["材料牌号"]
    cursor.execute("""
         SELECT 参数名称, 参数值
         FROM 产品设计活动表_元件附加参数表
         WHERE 产品ID = %s AND 元件名称 = '拉杆'
     """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row["参数值"] for row in rows}
    if param_map:
        if param_map.get("材料类型"):
            tube_bundle["拉杆材料类型"] = param_map["材料类型"]
        if param_map.get("材料牌号"):
            tube_bundle["拉杆材料牌号"] = param_map["材料牌号"]
    cursor.execute("""
             SELECT 参数名称, 参数值
             FROM 产品设计活动表_元件附加参数表
             WHERE 产品ID = %s AND 元件名称 = '防冲板'
         """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row["参数值"] for row in rows}
    if param_map:
        if param_map.get("材料类型"):
            tube_bundle["防冲挡板材料类型"] = param_map["材料类型"]
        if param_map.get("材料牌号"):
            tube_bundle["防冲挡板材料牌号"] = param_map["材料牌号"]
    cursor.execute("""
             SELECT 参数名称, 参数值
             FROM 产品设计活动表_元件附加参数表
             WHERE 产品ID = %s AND 元件名称 = '定距管'
         """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row["参数值"] for row in rows}
    if param_map:
        if param_map.get("材料类型"):
            tube_bundle["定距管材料类型"] = param_map["材料类型"]
        if param_map.get("材料牌号"):
            tube_bundle["定距管材料牌号"] = param_map["材料牌号"]

    # 遍历所有返回的参数，构建映射

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
        cursor = conn.cursor()  #   手动创建游标，不会自动关闭

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
        print(f"  查询失败: {e}")

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
        "筋板材料类型": "钢板",
        "筋板材料牌号": "Q345R",
        "筋板名义厚度": "10",
        "腹板材料类型": "钢板",
        "腹板材料牌号": "Q345R",
        "腹板名义厚度": "20",
        "底板材料类型": "钢板",
        "底板材料牌号": "Q345R",
        "底板名义厚度": "15",
        "壳程入口接管法兰外径":"",
        "壳程出口接管法兰外径":""
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
            "开孔元件名称": "管箱圆筒",
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
            SELECT 参数名称, 管程数值
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s AND 参数名称 IN ('工作温度（入口）', '工作温度（出口）')
        """, (product_id,))
        rows = cursor.fetchall()

        # 初始化入口/出口温度
        temp_in = None
        temp_out = None

        for row in rows:
            name = str(row.get("参数名称", "") or "").strip()
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
            SELECT 参数名称, 壳程数值, 管程数值
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s
        """, (product_id,))
        rows = cursor.fetchall()
        param_map = {str(row["参数名称"]).strip(): row for row in rows if row.get("参数名称")}

        # 公称直径（管程）
        if "公称直径*" in param_map:
            if "管程" in str(suoshuyuanjian) or "管箱" in str(suoshuyuanjian):
                jieguan["设备公称直径"] = str(param_map["公称直径*"].get("管程数值", "") or "")
            elif "壳程" in str(suoshuyuanjian) or "壳体" in str(suoshuyuanjian):
                jieguan["设备公称直径"] = str(param_map["公称直径*"].get("壳程数值", "") or "")

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
        # print(f" 接管腐蚀裕量: {jieguan.get('接管腐蚀裕量')}")

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
        "管箱平盖": guanxiang_pinggai,
        "管箱圆筒": guanxiang_yuantong,
        "头盖法兰": tougai_falan,
        "管箱法兰": guanxiang_falan,

        "管箱分程隔板": fencheng_geban,
        "壳体端部圆筒1": qiaoti_duanbuyuantong1,
        "壳体端部圆筒2": qiaoti_duanbuyuantong2,
        "壳体圆筒": qiaoti_yuantong,
        "固定管板": guanban_a,
        "管束": tube_bundle,
        "后端管箱圆筒": guanxiang_houduanyuantong,
        "后端管箱封头": guanxiang_houduanfengtou,

        "吊耳": diaoer,
        "鞍座": anzuo,
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
        result["ExchangerType"] = row.get("产品型式", "Unknown")
    else:
        result["ProjectName"] = "UnnamedProject"
        result["ExchangerType"] = "Unknown"

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
