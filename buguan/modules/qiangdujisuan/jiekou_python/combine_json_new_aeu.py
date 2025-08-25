import os
import re
import string
import sys
from collections import defaultdict

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


material_type_map = {
    "板材":"钢板",
    "锻件": "钢锻件",
    "Q235系列钢板": "钢板",

}

def calculate_heat_exchanger_strength_AEU(product_id):
    # 连接数据库
    conn = pymysql.connect(
        host='localhost',
        user='root',
        password='123456',
        database='产品设计活动库',
        charset='utf8mb4'
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
    cursor.execute("""
        SELECT 公称尺寸类型, 公称压力类型
        FROM 产品设计活动表_管口类型选择表
        WHERE 产品ID = %s
    """, (product_id,))
    row = cursor.fetchone()

    # 获取全局默认类型（没有管口代号）
    pipe_type_default = {
        "公称尺寸类型": row["公称尺寸类型"] if row else "",
        "公称压力类型": row["公称压力类型"] if row else ""
    }

    cursor.execute("""
        SELECT *
        FROM 产品设计活动表_管口表
        WHERE 产品ID = %s
    """, (product_id,))
    port_rows = cursor.fetchall()
    ttdict = {}

    for i, row in enumerate(port_rows):
        if i >= 4:  # 最多只生成 N1 到 N4
            break
        # key = string.ascii_lowercase[i]  # a, b, c, ...
        key = f"N{i + 1}"  # 生成 N1, N2, N3, ...

        axial_angle = row.get("轴向夹角（°）", "")
        zhouxiangfangwei = row.get("周向方位（°）", "")

        ttdict[key] = {
            "ttNo": 0,
            "ttCode": clean_value(row.get("管口代号")),
            "ttUse": clean_value(row.get("管口功能")),

            "ttDN": clean_value(row.get("公称尺寸")),

            "ttPClass": clean_value(row.get("压力等级")),
            "ttDType": pipe_type_default["公称尺寸类型"],  # ✅ 全部统一用默认
            "ttPType": pipe_type_default["公称压力类型"],
            # "ttType": clean_value(row.get("法兰型式")),
            "ttType": "WN",
            "ttRF": clean_value(row.get("密封面型式")),
            "ttSpec": clean_value(row.get("焊端规格")),
            "ttAttach": clean_value(row.get("管口所属元件")),
            "ttPlace": {"左基准线": "左轮廓线", "右基准线": "右轮廓线"}.get(row.get("轴向定位基准", ""),
                                                                                clean_value(row.get("轴向定位基准"))),
            "ttLoc": clean_value(row.get("轴向定位距离")),
            "ttFW": clean_value(axial_angle),
            "ttThita": clean_value(row.get("偏心距")),
            # "ttThita": clean_value(row.get("密封面型式")),
            "ttAngel": clean_value(zhouxiangfangwei),
            "ttH": "0" if str(row.get("外伸高度")).strip() == "默认" else clean_value(row.get("外伸高度")),
            "ttMemo": "默认"
        }

    # ===== 预设默认值 =====
    design_params = {
        "公称直径": "1000",
        "是否以外径为基准": "1",
        "介质类型": "介质易爆/极度危害/高度危害",
        "管箱圆筒长度工况": "工况1",
        "绝热厚度": "4",
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
        "管箱平盖": "平盖",
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




    # 初始化字典
    guangxiang_pinggai = {
            "换热器型号": "BEU",
            "壳程液柱密度": "1",
            "管程液柱密度": "1",
            "壳程液柱静压力": "0",
            "管程液柱静压力": "0",
            "压紧面形状序号": "1a",
            "法兰盘是否考虑腐蚀裕量": "是",
            "法兰压紧面压紧宽度ω": "0",
            "轴向外力": "0",
            "外力矩": "0",
            "法兰类型": "松式法兰4",
            "法兰材料类型": "钢锻件",
            "法兰材料牌号": "16Mn",
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
            "圆筒材料类型": "钢板",
            "圆筒材料牌号": "Q345R",
            "焊缝高度": "0",
            "焊缝长度": "10",
            "焊缝深度": "0",
            "法兰种类": "长颈",
            "介质情况": "毒性",
            "公称直径管前左": "1000",
            "公称直径壳后右": "1200",
            "对接元件管前左内直径": "1000",
            "对接元件壳后右内直径": "1000",
            "对接元件管前左基层名义厚度": "20",
            "对接元件壳后右基层名义厚度": "30",
            "对接元件管前左材料类型": "钢板",
            "对接元件壳后右材料类型": "钢板",
            "对接元件管前左材料牌号": "Q345R",
            "对接元件壳后右材料牌号": "Q345R",
            "是否带分程隔板管前左": "是",
            "是否带分程隔板壳后右": "是",
            "法兰类型管前左": "整体法兰2",
            "法兰材料类型管前左": "钢锻件",
            "法兰材料牌号管前左": "16Mn",
            "法兰材料腐蚀裕量管前左": "3",
            "法兰类型壳后右": "整体法兰2",
            "法兰材料类型壳后右": "钢锻件",
            "法兰材料牌号壳后右": "16Mn",
            "法兰材料腐蚀裕量壳后右": "3",
            "覆层厚度管前左": "0.2",
            "覆层厚度壳后右": "0.3",
            "堆焊层厚度管前左": "1.5",
            "堆焊层厚度壳后右": "1.6",
            "法兰位置管前左": "管箱法兰",
            "法兰位置壳后右": "壳体法兰",
            "垫片名义外径": "1060",
            "垫片名义内径": "1020",
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
            "m": "3",
            "y": "69",
            "垫片厚度": "3",
            "垫片有效外径": "1063",
            "垫片有效内径": "1023",
            "分程隔板处垫片有效密封面积": "0",
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
    pinggai_params = {
        r["参数名称"].strip(): {
            "壳程数值": r["壳程数值"],
            "管程数值": r["管程数值"]
        }
        for r in rows
    }
    if "液柱静压力" in pinggai_params:
        shell_pressure = pinggai_params["液柱静压力"].get("壳程数值", "")
        tube_pressure = pinggai_params["液柱静压力"].get("管程数值", "")
        if shell_pressure:
            guangxiang_pinggai["壳程液柱静压力"] = str(shell_pressure)
        if tube_pressure:
            guangxiang_pinggai["管程液柱静压力"] = str(tube_pressure)
    if "介质密度" in pinggai_params:
        shell_density = pinggai_params["介质密度"].get("壳程数值", "")
        tube_density = pinggai_params["介质密度"].get("管程数值", "")
        if shell_density:
            guangxiang_pinggai["壳程液柱密度"] = str(shell_density)
        if tube_density:
            guangxiang_pinggai["管程液柱密度"] = str(tube_density)
    cursor.execute("""
        SELECT 参数值 FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '平盖垫片' AND 参数名称 = '压紧面形状'
    """, (product_id,))
    row = cursor.fetchone()
    if row and "参数值" in row:
        guangxiang_pinggai["压紧面形状序号"] = str(row["参数值"])
        # 参数名映射关系：数据库参数名 → 字典字段名
    param_map = {
        "轴向拉伸载荷": "轴向外力",
        "附加弯矩": "外力矩",
        "法兰类型": "法兰类型",
        "材料类型": "法兰材料类型",
        "材料牌号": "法兰材料牌号"
    }

    # 查询数据库
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '头盖法兰'
    """, (product_id,))

    rows = cursor.fetchall()

    for row in rows:
        name = row["参数名称"].strip()
        raw_value = row["参数值"]
        value = str(raw_value).strip() if raw_value is not None and str(raw_value).strip() != "" else "0"
        if name in param_map:
            guangxiang_pinggai[param_map[name]] = value
        # 来自设计数据表（param_map）
    sheji_param = {
        "法兰材料腐蚀裕量": ("腐蚀裕量*", "管程数值"),
        "法兰材料腐蚀裕量管前左": ("腐蚀裕量*", "管程数值"),
        "公称直径管前左": ("公称直径*", "管程数值"),
        "公称直径壳后右": ("公称直径*", "壳程数值"),
        "纵向焊接接头系数": ("焊接接头系数*", "管程数值"),
        "对接元件管前左内直径":("公称直径*","壳程数值"),
        "对接元件壳后右内直径":  ("公称直径*", "管程数值"),
    }
    for field, (param, side) in sheji_param.items():
        val = param_map.get(param, {}).get(side, "")
        if val:
            guangxiang_pinggai[field] = str(val)

        # 查询元件附加参数表中元件名称为“管箱封头”的数据
    cursor.execute("""
              SELECT 参数名称, 参数值
              FROM 产品设计活动表_元件附加参数表
              WHERE 产品ID = %s AND 元件名称 = '管箱平盖'
          """, (product_id,))
    extra_rows = cursor.fetchall()
    extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}


    # 补充映射关系：用于“管箱圆筒”元件
    yuantong_param_map = {
        "材料类型": "圆筒材料类型",
        "材料牌号": "圆筒材料牌号"
    }

    # 查询数据库
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱圆筒'
    """, (product_id,))

    rows = cursor.fetchall()

    # 更新目标字典
    for row in rows:
        name = row["参数名称"].strip()
        value = str(row["参数值"]).strip()
        if name in yuantong_param_map:
            guangxiang_pinggai[yuantong_param_map[name]] = value
    yuanjian_param = {
        ("头盖法兰", "法兰类型"): "法兰类型",
        ("头盖法兰", "材料类型"): "法兰材料类型",
        ("头盖法兰", "材料牌号"): "法兰材料牌号",
        ("壳体法兰", "法兰类型"): "法兰类型壳后右",
        ("壳体法兰", "材料类型"): "法兰材料类型壳后右",
        ("壳体法兰", "材料牌号"): "法兰材料牌号壳后右",
        # ("管箱法兰", "覆层厚度"): "覆层厚度管前左",
        # ("壳体法兰", "覆层厚度"): "覆层厚度壳后右",
        ("管箱圆筒", "材料类型"): "圆筒材料类型",
        ("管箱圆筒", "材料牌号"): "圆筒材料牌号",
        ("管箱法兰", "法兰类型"): "法兰类型管前左",
        ("管箱法兰", "材料类型"): "法兰材料类型管前左",
        ("管箱法兰", "材料牌号"): "法兰材料牌号管前左",
        ("管箱平盖", "平盖类型"): "平盖序号",
        ("螺柱（头盖法兰）", "材料牌号"): "螺栓材料牌号",
        ("平盖垫片", "材料牌号"): "垫片材料牌号",
        # ("平盖垫片", "垫片系数m"): "m",
        ("平盖垫片", "垫片比压力y"): "y",
        ("平盖垫片", "垫片与密封面接触外径D2"): "垫片有效外径",
        ("平盖垫片", "垫片与垫片与密封面接触内径D1"): "垫片有效内径"
    }
    # 构造：每个元件对应哪些参数
    component_param_names = defaultdict(set)
    for (component, pname) in yuanjian_param:
        component_param_names[component].add(pname)

    # 遍历每个元件查询并赋值，空值则为 "0"
    for component, param_names in component_param_names.items():
        cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = %s
        """, (product_id, component))
        rows = cursor.fetchall()

        for row in rows:
            pname = row["参数名称"].strip()
            if pname in param_names:
                key = (component, pname)
                raw_value = row["参数值"]
                value = str(raw_value).strip() if raw_value is not None else ""
                guangxiang_pinggai[yuanjian_param[key]] = value if value else "0"






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
        "压力试验温度": "20",
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
            keti_fengtou["压力试验类型"] = pressure_type_map.get(clean_val, "0")

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
    if extra_map.get("是否添加覆层") == "有覆层":
        keti_fengtou["是否覆层"] = "1"
        keti_fengtou["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        keti_fengtou["椭圆形封头覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
    else:
        keti_fengtou["是否覆层"] = "0"
        keti_fengtou["覆层复合方式"] = "轧制复合"
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

    }
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

    }

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
           SELECT 管程数值 FROM 产品设计活动表_设计数据表
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
        cursor.execute("""
               SELECT 参数名称, 参数值 
               FROM 产品设计活动表_元件附加参数表
               WHERE 产品ID = %s AND 元件名称 = '壳体封头'
           """, (product_id,))
        extra_rows = cursor.fetchall()
        extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}







    guanxiang_falan = {
        "换热器型号": "BEU",
        "壳程液柱密度": "1",
        "管程液柱密度": "1",
        "壳程液柱静压力": "0",
        "管程液柱静压力": "0",
        "压紧面形状序号": "1a",
        "法兰盘是否考虑腐蚀裕量": "是",
        "法兰压紧面压紧宽度ω": "0",
        "轴向外力": "0",
        "外力矩": "0",
        "法兰类型": "松式法兰4",
        "法兰材料类型": "锻件",
        "法兰材料牌号": "16Mn",
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
        "法兰材料类型管前左": "锻件",
        "法兰材料牌号管前左": "16Mn",
        "法兰材料腐蚀裕量管前左": "3",
        "法兰类型壳后右": "整体法兰2",
        "法兰材料类型壳后右": "锻件",
        "法兰材料牌号壳后右": "16Mn",
        "法兰材料腐蚀裕量壳后右": "3",
        "覆层厚度管前左": "0.2",
        "覆层厚度壳后右": "0.3",
        "堆焊层厚度管前左": "1.5",
        "堆焊层厚度壳后右": "1.6",
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
        "m": "3",
        "y": "69",
        "垫片厚度": "3",
        "垫片有效外径": "1063",
        "垫片有效内径": "1023",
        "分程隔板处垫片有效密封面积": "0",
        "垫片分程隔板肋条有效密封宽度": "0",
        "垫片代号": "2.1",
        "隔条位置尺寸": "0",
        "介质情况": "毒性"
    }

    # 从产品需求表中获取“产品型式”作为“换热器型号”
    # 切换数据库连接到产品需求库



    cursor.execute("USE 产品设计活动库")

    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱法兰'
    """, (product_id,))
    rows = cursor.fetchall()
    falan_params = {r["参数名称"]: r["参数值"] for r in rows}

    if "法兰类型" in falan_params:
        guanxiang_falan["法兰类型"] = falan_params["法兰类型"]
    if "材料类型" in falan_params:
        guanxiang_falan["法兰材料类型"] = falan_params["材料类型"]
    if "材料牌号" in falan_params:
        guanxiang_falan["法兰材料牌号"] = falan_params["材料牌号"]
    # 介质密度 → 壳程液柱密度 和 管程液柱密度
    if "介质密度" in falan_params:
        shell_density = falan_params["介质密度"].get("壳程数值", "")
        tube_density = falan_params["介质密度"].get("管程数值", "")
        if shell_density:
            guanxiang_falan["壳程液柱密度"] = str(shell_density)
        if tube_density:
            guanxiang_falan["管程液柱密度"] = str(tube_density)
    if "液柱静压力" in falan_params:
        shell_pressure = falan_params["液柱静压力"].get("壳程数值", "")
        tube_pressure = falan_params["液柱静压力"].get("管程数值", "")
        if shell_pressure:
            guanxiang_falan["壳程液柱静压力"] = str(shell_pressure)
        if tube_pressure:
            guanxiang_falan["管程液柱静压力"] = str(tube_pressure)
    cursor.execute("""
        SELECT 参数值 FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '管箱垫片' AND 参数名称 = '压紧面形状'
    """, (product_id,))
    row = cursor.fetchone()
    if row and "参数值" in row:
        guanxiang_falan["压紧面形状序号"] = str(row["参数值"])

    # param_map：参数名称 → {壳程数值, 管程数值}
    cursor.execute("""
        SELECT 参数名称, 壳程数值, 管程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()
    param_map = {r["参数名称"].strip(): r for r in rows}

    # component_map: 元件名称 -> 参数名称 -> 参数值
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
    # 来自设计数据表（param_map）
    sheji_param = {
        "法兰材料腐蚀裕量": ("腐蚀裕量*", "管程数值"),
        "法兰材料腐蚀裕量管前左": ("腐蚀裕量*", "管程数值"),
        "公称直径管前左": ("公称直径*", "管程数值"),
        "公称直径壳后右": ("公称直径*", "壳程数值"),
        "纵向焊接接头系数": ("焊接接头系数*", "壳程数值"),
        "对接元件管前左内直径": ("公称直径*", "壳程数值"),
        "对接元件壳后右内直径": ("公称直径*", "管程数值"),
    }
    for field, (param, side) in sheji_param.items():
        val = param_map.get(param, {}).get(side, "")
        if val:
            guanxiang_falan[field] = str(val)

    # 来自元件附加参数表（component_map）
    yuanjian_param = {
        ("管箱法兰", "轴向拉伸载荷"): "轴向外力",
        ("管箱法兰", "附加弯矩"): "外力矩",
        ("管箱法兰", "法兰类型"): "法兰类型",
        ("管箱法兰", "材料类型"): "法兰材料类型",
        ("管箱法兰", "材料牌号"): "法兰材料牌号",
        ("管箱法兰", "覆层厚度"): "覆层厚度",
        ("壳体法兰", "法兰类型"): "法兰类型壳后右",
        ("壳体法兰", "材料类型"): "法兰材料类型壳后右",
        ("壳体法兰", "材料牌号"): "法兰材料牌号壳后右",
        ("管箱法兰", "覆层厚度"): "覆层厚度管前左",
        ("壳体法兰", "覆层厚度"): "覆层厚度壳后右",
        ("管箱圆筒", "材料类型"): "圆筒材料类型",
        ("管箱圆筒", "材料牌号"): "圆筒材料牌号",
        ("管箱法兰", "法兰类型"): "法兰类型管前左",
        ("管箱法兰", "材料类型"): "法兰材料类型管前左",
        ("管箱法兰", "材料牌号"): "法兰材料牌号管前左",
        ("管箱平盖", "平盖类型"): "平盖序号",
        ("螺柱（管箱法兰）", "材料牌号"): "螺栓材料牌号",
        ("管箱垫片", "材料牌号"): "垫片材料牌号",
        ("管箱垫片", "垫片系数m"): "m",
        ("管箱垫片", "垫片比压力y"): "y",
        ("管箱垫片", "垫片与密封面接触外径D2"): "垫片有效外径",
        ("管箱垫片", "垫片与垫片与密封面接触内径D1"): "垫片有效内径"
    }
    for (comp, param), field in yuanjian_param.items():
        val = component_map.get(comp, {}).get(param, "")

        # # 如果是“螺栓材料牌号”且为空，默认赋为“35CrMo”
        # if field == "螺栓材料牌号" and (val is None or str(val).strip() == "" or str(val).strip() == '0'):
        #     guanxiang_falan[field] = "35CrMo"
        # else:
        #     guanxiang_falan[field] = str(val if val not in ["", None,'0'] else "0")
        # if field == "垫片材料牌号" and (val is None or str(val).strip() == ""):
        #     guanxiang_falan[field] = "复合柔性石墨波齿金属板(不锈钢)"
        # else:
        #     guanxiang_falan[field] = str(val if val not in ["", None,'0'] else "0")
        # # 如果是“螺栓材料牌号”且为空，默认赋为“35CrMo”
        # if field == "垫片有效外径" and (val is None or str(val).strip() == "" or str(val).strip() == '0'):
        #     guanxiang_falan[field] = "1063"
        # else:
        #     guanxiang_falan[field] = str(val if val not in ["", None,'0'] else "0")
        # if field == "垫片有效内径" and (val is None or str(val).strip() == ""):
        #     guanxiang_falan[field] = "1023"
        # else:
        #     guanxiang_falan[field] = str(val if val not in ["", None,'0'] else "0")
    keti_falan = {
        "换热器型号": "BEU",
        "壳程液柱密度": "1",
        "管程液柱密度": "1",
        "壳程液柱静压力": "0",
        "管程液柱静压力": "0",
        "压紧面形状序号": "1a",
        "法兰盘是否考虑腐蚀裕量": "是",
        "法兰压紧面压紧宽度ω": "0",
        "轴向外力": "0",
        "外力矩": "0",
        "法兰类型": "松式法兰4",
        "法兰材料类型": "锻件",
        "法兰材料牌号": "16Mn",
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
        "是否带分程隔板壳后右": "否",
        "法兰类型管前左": "整体法兰2",
        "法兰材料类型管前左": "锻件",
        "法兰材料牌号管前左": "16Mn",
        "法兰材料腐蚀裕量管前左": "3",
        "法兰类型壳后右": "整体法兰2",
        "法兰材料类型壳后右": "锻件",
        "法兰材料牌号壳后右": "16Mn",
        "法兰材料腐蚀裕量壳后右": "3",
        "覆层厚度管前左": "0.2",
        "覆层厚度壳后右": "0.3",
        "堆焊层厚度管前左": "1.5",
        "堆焊层厚度壳后右": "1.6",
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
        "m": "3",
        "y": "69",
        "垫片厚度": "3",
        "垫片有效外径": "1063",
        "垫片有效内径": "1023",
        "分程隔板处垫片有效密封面积": "0",
        "垫片分程隔板肋条有效密封宽度": "0",
        "垫片代号": "2.1",
        "隔条位置尺寸": "0",
        "介质情况": "毒性"
    }

    # # 切换数据库连接到产品需求库
    # cursor.execute("USE 产品需求库")
    #
    # # 查询产品型式
    # cursor.execute("""
    #         SELECT 产品型式 FROM 产品需求表
    #         WHERE 产品ID = %s
    #     """, (product_id,))
    # row = cursor.fetchone()
    # if row and "产品型式" in row:
    #     keti_falan["换热器型号"] = str(row["产品型式"])

    cursor.execute("USE 产品设计活动库")

    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '壳体法兰'
        """, (product_id,))
    rows = cursor.fetchall()
    falan_params = {r["参数名称"]: r["参数值"] for r in rows}

    if "法兰类型" in falan_params:
        keti_falan["法兰类型"] = falan_params["法兰类型"]
    if "材料类型" in falan_params:
        keti_falan["法兰材料类型"] = falan_params["材料类型"]
    if "材料牌号" in falan_params:
        keti_falan["法兰材料牌号"] = falan_params["材料牌号"]
    # 介质密度 → 壳程液柱密度 和 管程液柱密度
    if "介质密度" in falan_params:
        shell_density = falan_params["介质密度"].get("壳程数值", "")
        tube_density = falan_params["介质密度"].get("管程数值", "")
        if shell_density:
            keti_falan["壳程液柱密度"] = str(shell_density)
        if tube_density:
            keti_falan["管程液柱密度"] = str(tube_density)
    if "液柱静压力" in falan_params:
        shell_pressure = falan_params["液柱静压力"].get("壳程数值", "")
        tube_pressure = falan_params["液柱静压力"].get("管程数值", "")
        if shell_pressure:
            keti_falan["壳程液柱静压力"] = str(shell_pressure)
        if tube_pressure:
            keti_falan["管程液柱静压力"] = str(tube_pressure)
    cursor.execute("""
            SELECT 参数值 FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '壳体垫片' AND 参数名称 = '压紧面形状'
        """, (product_id,))
    row = cursor.fetchone()
    if row and "参数值" in row:
        keti_falan["压紧面形状序号"] = str(row["参数值"])

    # param_map：参数名称 → {壳程数值, 管程数值}
    cursor.execute("""
            SELECT 参数名称, 壳程数值, 管程数值
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s
        """, (product_id,))
    rows = cursor.fetchall()
    param_map = {r["参数名称"].strip(): r for r in rows}

    # component_map: 元件名称 -> 参数名称 -> 参数值
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
    # 来自设计数据表（param_map）
    sheji_param = {
        "法兰材料腐蚀裕量": ("腐蚀裕量*", "管程数值"),
        "法兰材料腐蚀裕量管前左": ("腐蚀裕量*", "管程数值"),
        "公称直径管前左": ("公称直径*", "管程数值"),
        "公称直径壳后右": ("公称直径*", "壳程数值"),
        "纵向焊接接头系数": ("焊接接头系数*", "壳程数值"),
        "对接元件管前左内直径": ("公称直径*", "壳程数值"),
        "对接元件壳后右内直径": ("公称直径*", "管程数值"),
    }
    for field, (param, side) in sheji_param.items():
        val = param_map.get(param, {}).get(side, "")
        if val:
            keti_falan[field] = str(val)

    # 来自元件附加参数表（component_map）
    yuanjian_param = {
        ("壳体法兰", "轴向拉伸载荷"): "轴向外力",
        ("壳体法兰", "附加弯矩"): "外力矩",
        ("壳体法兰", "法兰类型"): "法兰类型",
        ("壳体法兰", "材料类型"): "法兰材料类型",
        ("壳体法兰", "材料牌号"): "法兰材料牌号",
        ("壳体法兰", "覆层厚度"): "覆层厚度",
        ("壳体法兰", "法兰类型"): "法兰类型壳后右",
        ("壳体法兰", "材料类型"): "法兰材料类型壳后右",
        ("壳体法兰", "材料牌号"): "法兰材料牌号壳后右",
        ("壳体法兰", "覆层厚度"): "覆层厚度管前左",
        ("壳体法兰", "覆层厚度"): "覆层厚度壳后右",
        ("壳体圆筒", "材料类型"): "圆筒材料类型",
        ("壳体圆筒", "材料牌号"): "圆筒材料牌号",
        ("壳体法兰", "法兰类型"): "法兰类型管前左",
        ("壳体法兰", "材料类型"): "法兰材料类型管前左",
        ("壳体法兰", "材料牌号"): "法兰材料牌号管前左",
        ("壳体平盖", "平盖类型"): "平盖序号",
        ("螺柱（壳体法兰）", "材料牌号"): "螺栓材料牌号",
        ("壳体垫片", "材料牌号"): "垫片材料牌号",
        ("壳体垫片", "垫片系数m"): "m",
        ("壳体垫片", "垫片比压力y"): "y",
        ("壳体垫片", "垫片与密封面接触外径D2"): "垫片有效外径",
        ("壳体垫片", "垫片与垫片与密封面接触内径D1"): "垫片有效内径"
    }
    for (comp, param), field in yuanjian_param.items():
        val = component_map.get(comp, {}).get(param, "")

        # # 如果是“螺栓材料牌号”且为空，默认赋为“35CrMo”
        # if field == "螺栓材料牌号" and (val is None or str(val).strip() == "0" or str(val).strip() == '0'):
        #     keti_falan[field] = "35CrMo"
        # else:
        #     keti_falan[field] = str(val if val not in ["", None] else "0")
        # if field == "垫片材料牌号" and (val is None or str(val).strip() == "0"):
        #     keti_falan[field] = "复合柔性石墨波齿金属板(不锈钢)"
        # else:
        #     keti_falan[field] = str(val if val not in ["", None,'0'] else "0")
        # if field == "垫片有效外径" and (val is None or str(val).strip() == ""):
        #     keti_falan[field] = "1063"
        # else:
        #     keti_falan[field] = str(val if val not in ["", None,'0'] else "0")
        # if field == "垫片有效内径" and (val is None or str(val).strip() == ""):
        #     keti_falan[field] = "1023"
        # else:
        #     keti_falan[field] = str(val if val not in ["", None,'0'] else "0")
    fencheng_geban = {
        "材料类型": "钢板",
        "材料牌号": "Q345R",
        "公称直径": "1000",
        "管箱分程隔板名义厚度": "0",
        "管箱分程隔板两侧压力差值": "0.05",
        "管箱分程隔板结构尺寸长边a": "596",
        "管箱分程隔板结构尺寸长边b": "785",
        "管箱分程隔板结构型式": "三边固定一边简支",
        "耐压试验温度": "20",
        "腐蚀裕量(双面)": "4",
        "管箱分程隔板设计余量": "0"
    }

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
        "换热管中心距": "25",
        "换热管直管段长度": "3000",
        "耐压试验温度": "15",
        "内孔焊焊接接头系数": "0.85",
        "换热管与管板胀接长度或焊脚高度": "3.5",
        "换热管是否钢材": "1",
        "胀接管孔是否开槽": "1",
        "换热管根数": "220",
        "垫片材料名称": "复合柔性石墨波齿金属板(不锈钢)",
        "管板外径": "863",
        "垫片与密封面接触外径": "863",
        "垫片与密封面接触内径": "825",
        "垫片厚度": "3",
        "压紧面形式": "1a或1b",
        "换热管排列方式": "正三角形",
        "折流板切口方向": "水平",
        "管/壳程布置型式": "2.1",
        "沿水平隔板槽一侧的排管根数": "2",
        "沿竖直隔板槽一侧的排管根数": "1",
        "水平隔板槽两侧相邻管中心距": "80",
        "垂直隔板槽两侧相邻管中心距": "80",
        "管板分程处面积Ad": "0",
        "是否交叉布管": "0",
        "交叉管排1最两端管孔中心距": "0",
        "交叉管排1实际管孔数量": "0",
        "交叉管排2最两端管孔中心距": "0",
        "交叉管排2实际管孔数量": "0",
        "交叉管排3最两端管孔中心距": "0",
        "交叉管排3实际管孔数量": "0"
    }

    cursor.execute("""
        SELECT `至水平中心线行号`, `管孔数量（上）`
        FROM 产品设计活动表_布管数量表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()

    horizontal_count = "0"
    vertical_count = 0

    for row in rows:
        row_num = row.get("至水平中心线行号")
        count_up = row.get("管孔数量（上）")

        try:
            row_num_int = int(str(row_num).strip())
            count_up_int = int(str(count_up).strip())

            if row_num_int == 1:
                horizontal_count = str(count_up_int)

            if row_num_int > vertical_count:
                vertical_count = row_num_int

        except (TypeError, ValueError):
            continue  # 忽略无效数据

    # 写入到字典
    guanban_a["沿水平隔板槽一侧的排管根数"] = horizontal_count
    guanban_a["沿竖直隔板槽一侧的排管根数"] = str(vertical_count)
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
        guanban_a["换热管使用场合"] = "/".join(media_parts)
    cursor.execute("""
        SELECT 材料类型, 材料牌号
        FROM 产品设计活动表_管口零件材料表
        WHERE 产品ID = %s AND 零件名称 = '接管'
    """, (product_id,))
    row = cursor.fetchone()

    # 如果查询到，则覆盖 guanban_a 中对应字段
    if row:
        if row.get("材料类型"):
            guanban_a["换热管材料类型"] = str(row["材料类型"])
        if row.get("材料牌号"):
            guanban_a["换热管材料牌号"] = str(row["材料牌号"])

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


    # 更新 guanban_a 字典中的材料类型和材料牌号
    if "材料类型" in param_map:
        guanban_a["材料类型"] = str(param_map["材料类型"])
    if "材料牌号" in param_map:
        guanban_a["材料牌号"] = str(param_map["材料牌号"])
    # 查询换热管相关参数（外径、壁厚、中心距、直管段长度）
    cursor.execute("""
        SELECT 参数名, 参数值
        FROM 产品设计活动表_布管参数表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()

    # 整理为字典
    tube_params = {row["参数名"].strip(): row["参数值"] for row in rows}

    # 对应关系：参数名 → guanban_a字段名
    mapping = {
        "换热管外径 do": "换热管外径",
        "换热管壁厚 δ": "换热管壁厚",
        "换热管中心距 S": "换热管中心距",
        "换热管公称长度LN": "换热管直管段长度"
    }

    # 写入 guanban_a，处理空值与小数点
    for param_name, key in mapping.items():
        val = tube_params.get(param_name)

        # 特殊处理换热管中心距为空的情况
        if param_name == "换热管中心距 S":
            if val is None or str(val).strip() in ["", "0", "0.0", "None"]:
                guanban_a[key] = "25"
            else:
                guanban_a[key] = str(val).split(".")[0]
        else:
            if val is not None and str(val).strip() != "":
                guanban_a[key] = str(val).split(".")[0]

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
    cursor.execute("""
        SELECT `管孔数量（上）`, `管孔数量（下）`
        FROM 产品设计活动表_布管数量表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()

    # 累加总根数
    total_count = 0
    for row in rows:
        upper = row.get("管孔数量（上）", 0) or 0
        try:
            total_count += float(upper)
        except:
            pass  # 跳过非数字

    # 设置根数，若为 0 则使用默认值 220
    guanban_a["换热管根数"] = str(int(total_count) if total_count else 220)

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
    # 查询布管参数表中该产品的所有参数
    # 定义排列形式映射字典

    # 默认值配置
    default = {
        "换热管排列形式": "正三角形",
        "折流板切口方向": "垂直"
    }

    # 映射字典
    arrangement_map = {
        "0": "正三角形",
        "1": "转角正三角形",
        "2": "正方形",
        "3": "转角正方形"
    }
    arrangement_map2 = {
        "0": "水平",
        "1": "垂直"
    }

    # 查询数据库
    cursor.execute("""
        SELECT 参数名, 参数值
        FROM 产品设计活动表_布管参数表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()

    # 构建 参数名 → 参数值 的映射，过滤 None 和空字符串
    tube_params = {
        row["参数名"].strip(): str(row["参数值"]).strip()
        for row in rows
        if row["参数值"] is not None and str(row["参数值"]).strip() != ""
    }

    # 写入 guanban_a（先取数据库值，再映射，最后默认值）
    val1 = tube_params.get("换热管排列形式", "")
    guanban_a["换热管排列方式"] = arrangement_map.get(val1, val1 if val1 else default["换热管排列形式"])

    val2 = tube_params.get("折流板切口方向", "")
    guanban_a["折流板切口方向"] = arrangement_map2.get(val2, val2 if val2 else default["折流板切口方向"])

    if "管程分程形式" in tube_params:
        val = tube_params["管程分程形式"].strip()

        if re.match(r"^\d+_\d+$", val):  # 匹配形如 "2_1" 的形式
            guanban_a["管/壳程布置型式"] = val.replace("_", ".")
        elif val == "2":
            guanban_a["管/壳程布置型式"] = "2.1"
        elif val == "4":
            guanban_a["管/壳程布置型式"] = "4.2"
        else:
            guanban_a["管/壳程布置型式"] = val  # 其他情况保持不变
    if "隔板槽两侧相邻管中心距Sn(水平)" in tube_params:
        guanban_a["水平隔板槽两侧相邻管中心距"] = tube_params["隔板槽两侧相邻管中心距Sn(水平)"]
    if "隔板槽两侧相邻管中心距Sn(竖直)" in tube_params:
        guanban_a["垂直隔板槽两侧相邻管中心距"] = tube_params["隔板槽两侧相邻管中心距Sn(竖直)"]

    tube_bundle = {
        "倾斜U形换热管两管孔的中心距离1排": "62.8013",
        "倾斜U形换热管两管孔的中心距离2排": "85.0582",
        "倾斜U形换热管两管孔的中心距离3排": "127.0858",
        "换热管孔间距": "25",
        "允许交叉布管的排数": "3",
        "管垂直间距3排": "124.6",
        "管垂直间距2排": "81.3",
        "管垂直间距1排": "38",
        "仅倾斜or交叉1排": "交叉",
        "仅倾斜or交叉2排": "交叉",
        "仅倾斜or交叉3排": "交叉",
        "管程数": "2",
        "管孔排列形式": "正三角形30水平切",
        "折流板缺口": "水平上下",
        "水平分程隔板槽两侧相邻管中心距水平上下": "38",
        "竖直分程隔板槽两侧相邻管中心距垂直左右": "0",
        "水平分程隔板槽数量": "1",
        "竖直分程隔板槽数量": "0",
        "布管限定圆直径": "784",
        "换热管理论直管长度": "6000",
        "换热管伸出管板值": "4.5",
        "管板名义厚度": "80",
        "折流板切口与中心线间距": "200",
        "圆筒内径": "800",
        "公称直径": "1000",
        "滑道与固定管板是否焊接连接": "是",
        "滑道伸出折流板/支持板最小值": "50",
        "是否交叉布管": "否",
        "接管外径1": "273",
        "接管外径2": "219",
        "接管1名义厚度": "16",
        "接管2名义厚度": "12",
        "圆筒名义厚度": "12",
        "管板类型": "a",
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
        "折流板厚度初始值": "10",
        "U形换热管最大弯曲直径": "760",
        "换热管材料序号": "1",
        "拉杆直径": "10",
        "接管OD2中心至壳程圆筒边缘(封头侧)最小距离": "219",
        "换热管材料类型": "钢管",
        "换热管材料牌号": "10(GB8163)"
    }

    # 预定义映射关系：目标字段名 → (参数名，对应的 tube_bundle 键)
    bgtube_map = {
        "换热管中心距 S": "换热管孔间距",
        "管程数": "管程数",
        "换热管排列形式": "管孔排列形式",
        "折流板切口方向": "折流板缺口",
        "隔板槽两侧相邻管中心距Sn(水平)": "水平分程隔板槽两侧相邻管中心距水平上下",
        "隔板槽两侧相邻管中心距Sn(竖直)": "竖直分程隔板槽两侧相邻管中心距垂直左右"
    }

    # 默认值配置
    default_values = {
        "换热管中心距 S": "25",
        "管程数": "2",
        "换热管排列形式": "正三角形30水平切",
        "折流板切口方向": "水平上下",
        "隔板槽两侧相邻管中心距Sn(水平)": "80",
        "隔板槽两侧相邻管中心距Sn(竖直)": "80",
    }

    # 特殊值映射
    arrangement_map = {
        "0": "正三角形30水平切"
    }
    baffle_dir_map = {
        "0": "水平上下",
        "1": "垂直左右"
    }

    # 查询数据库
    cursor.execute("""
        SELECT 参数名, 参数值
        FROM 产品设计活动表_布管参数表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()

    # 写入 tube_bundle 字典
    for row in rows:
        param_name = row["参数名"].strip()
        value = row["参数值"]
        if param_name in bgtube_map:
            key = bgtube_map[param_name]
            str_value = str(value).strip() if value is not None else ""

            # 针对特定字段映射处理
            if param_name == "换热管排列形式":
                tube_bundle[key] = arrangement_map.get(str_value, str_value or default_values[param_name])
            elif param_name == "折流板切口方向":
                tube_bundle[key] = baffle_dir_map.get(str_value, str_value or default_values[param_name])
            else:
                tube_bundle[key] = str_value or default_values[param_name]

            if str_value == "":
                print(f"⚠️ 参数 '{param_name}' 为空，使用默认值 '{tube_bundle[key]}'")

    more_tube_params = {
        "布管限定圆 DL": "布管限定圆直径",
        "换热管公称长度LN": "换热管理论直管长度",
        "折流板切口与中心线间距": "折流板切口与中心线间距",
        "换热管外径 do": "换热管外径"
    }

    # 合并映射（之前已有 bgtube_map）
    bgtube_map.update(more_tube_params)
    if row:
        if row.get("材料类型"):
            tube_bundle["换热管材料类型"] = str(row["材料类型"])
        if row.get("材料牌号"):
            tube_bundle["换热管材料牌号"] = str(row["材料牌号"])
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

    cursor.execute("""
        SELECT 管板类型 FROM 产品设计活动表_管板形式表
        WHERE 产品ID = %s
    """, (product_id,))
    row = cursor.fetchone()

    if row and row.get("管板类型") is not None:
        tube_bundle["管板类型"] = str(row["管板类型"]).split("_")[0]

    cursor.execute("""
        SELECT 参数值 FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '拉杆' AND 参数名称 = '拉杆型式'
    """, (product_id,))
    row = cursor.fetchone()

    if row and row.get("参数值") is not None:
        tube_bundle["拉杆类型"] = str(row["参数值"])
    conn2 = pymysql.connect(
        host='localhost',
        user='donghua704',
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
        "接管腐蚀余量": "3",
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
        "开孔补强自定义补强面积裕量百分比": "20",
        "补强区内的焊缝面积(含嵌入式接管焊缝面积)": "49",
        "补强圈材料类型": "板材",
        "补强圈材料牌号": "Q345R",
        "开孔元件名称": "管箱圆筒",
        "管口表序号": "N1"
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
        jieguan_guanchengrukou["设备公称直径"] = str(param_map["公称直径*"].get("管程数值", ""))
    # 参数映射：数据库参数名 → jieguan_guanchengrukou 字典键名
    jieguan_param_map = {
        "接管腐蚀裕量": "接管腐蚀余量",
        "覆层成型工艺": "覆层复合方式",
        "覆层厚度": "接管覆层厚度"
    }

    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_管口零件材料参数表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()

    for row in rows:
        param = row.get("参数名称", "").strip()
        val = row.get("参数值", "")
        if param in jieguan_param_map:
            if param == "覆层复合方式":
                jieguan_guanchengrukou[jieguan_param_map[param]] = str(val if val not in [None, ""] else "轧制复合")

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
            jieguan_guanchengrukou[material_field_map[(part_name, "材料类型")]] = material_type or "0"
        if (part_name, "材料牌号") in material_field_map:
            jieguan_guanchengrukou[material_field_map[(part_name, "材料牌号")]] = material_grade or "0"
    # 查询管口代号为 N1 的记录
    cursor.execute("""
        SELECT `轴向夹角（°）`, `偏心距`
        FROM 产品设计活动表_管口表
        WHERE 产品ID = %s AND 管口代号 = 'N1'
    """, (product_id,))
    row = cursor.fetchone()

    if row:
        try:
            angle = float(row.get("轴向夹角（°）") or 0)
            offset = float(row.get("偏心距") or 0)
        except ValueError:
            angle, offset = 0, 0  # 遇到非数字就默认0

        # 判断条件：两个都为 0 是类型 1，有一个不为 0 是类型 2
        if angle == 0 and offset == 0:
            jieguan_guanchengrukou["接管类型"] = "1"
        else:
            jieguan_guanchengrukou["接管类型"] = "2"
    else:
        jieguan_guanchengrukou["接管类型"] = "1"  # 没查到记录时默认类型 1
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
        "接管腐蚀余量": "3",
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
        "开孔补强自定义补强面积裕量百分比": "20",
        "补强区内的焊缝面积(含嵌入式接管焊缝面积)": "49",
        "补强圈材料类型": "板材",
        "补强圈材料牌号": "Q345R",
        "开孔元件名称": "管箱圆筒",
        "管口表序号": "N2"
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
        jieguan_guanchengchukou["设备公称直径"] = str(param_map["公称直径*"].get("管程数值", ""))
    # 参数映射：数据库参数名 → jieguan_guanchengrukou 字典键名
    jieguan_param_map = {
        "接管腐蚀裕量": "接管腐蚀余量",
        "覆层成型工艺": "覆层复合方式",
        "覆层厚度": "接管覆层厚度"
    }

    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_管口零件材料参数表
            WHERE 产品ID = %s
        """, (product_id,))
    rows = cursor.fetchall()

    for row in rows:
        param = row.get("参数名称", "").strip()
        val = row.get("参数值", "")
        if param in jieguan_param_map:
            if param == "覆层复合方式":
                jieguan_guanchengrukou[jieguan_param_map[param]] = str(val if val not in [None, ""] else "轧制复合")
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
    cursor.execute("""
            SELECT `轴向夹角（°）`, `偏心距`
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口代号 = 'N2'
        """, (product_id,))
    row = cursor.fetchone()

    if row:
        try:
            angle = float(row.get("轴向夹角（°）") or 0)
            offset = float(row.get("偏心距") or 0)
        except ValueError:
            angle, offset = 0, 0  # 遇到非数字就默认0

        # 判断条件：两个都为 0 是类型 1，有一个不为 0 是类型 2
        if angle == 0 and offset == 0:
            jieguan_guanchengchukou["接管类型"] = "1"
        else:
            jieguan_guanchengchukou["接管类型"] = "2"
    else:
        jieguan_guanchengchukou["接管类型"] = "1"  # 没查到记录时默认类型 1
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
        if raw_value is None or str(raw_value).strip() == "":
            jieguan_guanchengchukou["接管实际外伸长度"] = "0"
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
        "接管腐蚀余量": "3",
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
        "开孔补强自定义补强面积裕量百分比": "20",
        "补强区内的焊缝面积(含嵌入式接管焊缝面积)": "49",
        "补强圈材料类型": "板材",
        "补强圈材料牌号": "Q345R",
        "开孔元件名称": "管箱圆筒",
        "管口表序号": "N3"
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
        jieguan_kechengrukou["设备公称直径"] = str(param_map["公称直径*"].get("壳程数值", ""))
    # 参数映射：数据库参数名 → jieguan_guanchengrukou 字典键名
    jieguan_param_map = {
        "接管腐蚀裕量": "接管腐蚀余量",
        "覆层成型工艺": "覆层复合方式",
        "覆层厚度": "接管覆层厚度"
    }

    cursor.execute("""
                    SELECT 参数名称, 参数值
                    FROM 产品设计活动表_管口零件材料参数表
                    WHERE 产品ID = %s
                """, (product_id,))
    rows = cursor.fetchall()

    for row in rows:
        param = row.get("参数名称", "").strip()
        val = row.get("参数值", "")
        if param in jieguan_param_map:
            if param == "覆层复合方式":
                jieguan_kechengrukou[jieguan_param_map[param]] = str(val if val not in [None, ""] else "轧制复合")

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

    if row:
        try:
            angle = float(row.get("轴向夹角（°）") or 0)
            offset = float(row.get("偏心距") or 0)
        except ValueError:
            angle, offset = 0, 0  # 遇到非数字就默认0

        # 判断条件：两个都为 0 是类型 1，有一个不为 0 是类型 2
        if angle == 0 and offset == 0:
            jieguan_kechengrukou["接管类型"] = "1"
        else:
            jieguan_kechengrukou["接管类型"] = "2"
    else:
        jieguan_kechengrukou["接管类型"] = "1"  # 没查到记录时默认类型 1
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
                    WHERE 产品ID = %s AND 管口代号 = 'N4'
                """, (product_id,))
    row = cursor.fetchone()

    if row:
        jieguan_kechengrukou["开孔元件名称"] = str(row.get("管口所属元件") or "未知")
    jieguan_kechengchukou = {
        "设备公称直径": "1000",

        "接管是否以外径为基准": "True",
        "接管腐蚀余量": "3",
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
        "开孔补强自定义补强面积裕量百分比": "20",
        "补强区内的焊缝面积(含嵌入式接管焊缝面积)": "49",
        "补强圈材料类型": "板材",
        "补强圈材料牌号": "Q345R",
        "开孔元件名称": "管箱圆筒",
        "管口表序号": "N4"
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
        jieguan_kechengchukou["设备公称直径"] = str(param_map["公称直径*"].get("壳程数值", ""))
    # 参数映射：数据库参数名 → jieguan_guanchengrukou 字典键名
    jieguan_param_map = {
        "接管腐蚀裕量": "接管腐蚀余量",
        "覆层成型工艺": "覆层复合方式",
        "覆层厚度": "接管覆层厚度"
    }

    cursor.execute("""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_管口零件材料参数表
                WHERE 产品ID = %s
            """, (product_id,))
    rows = cursor.fetchall()

    for row in rows:
        param = row.get("参数名称", "").strip()
        val = row.get("参数值", "")
        if param in jieguan_param_map:
            if param == "覆层复合方式":
                jieguan_kechengchukou[jieguan_param_map[param]] = str(val if val not in [None, ""] else "轧制复合")

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
    cursor.execute("""
                SELECT `轴向夹角（°）`, `偏心距`
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口代号 = 'N4'
            """, (product_id,))
    row = cursor.fetchone()

    if row:
        try:
            angle = float(row.get("轴向夹角（°）") or 0)
            offset = float(row.get("偏心距") or 0)
        except ValueError:
            angle, offset = 0, 0  # 遇到非数字就默认0

        # 判断条件：两个都为 0 是类型 1，有一个不为 0 是类型 2
        if angle == 0 and offset == 0:
            jieguan_kechengchukou["接管类型"] = "1"
        else:
            jieguan_kechengchukou["接管类型"] = "2"
    else:
        jieguan_kechengchukou["接管类型"] = "1"  # 没查到记录时默认类型 1
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
            "管箱平盖": guangxiang_pinggai,
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

    def update_all_flange_types(obj):
        if isinstance(obj, dict):
            for key in obj:
                if isinstance(obj[key], dict):
                    update_all_flange_types(obj[key])
                elif isinstance(obj[key], list):
                    for item in obj[key]:
                        update_all_flange_types(item)
                elif isinstance(key, str) and (
                        key.startswith("法兰类型管前左") or key.startswith("法兰类型壳后右")
                ):
                    obj[key] = "整体法兰2"

    update_all_flange_types(result)
    # 保存结果到JSON文件
    with open("result_qiangdujisuan_new1.json", "w", encoding="utf-8") as f:
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
    with open("result_qiangdujisuan_new1.json", "r", encoding="utf-8") as f:
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
    product_id = 'PD20250706001'  # 替换为你自己的产品ID
    result = calculate_heat_exchanger_strength_AEU(product_id)
    print(result)