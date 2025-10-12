import os
import string
import sys

import pymysql
import json
import clr

material_type_map = {
    "钢锻件": "锻件",
    "钢板": "板材",
    "钢棒": "棒材",
    "Q235系列钢板": "板材",
"06Cr13": "S11306",
    "06Cr13Al": "S11348",
    "019Cr19Mo2NbTi": "S11972",
    "06Cr19Ni10": "S30408",
    "022Cr19Ni10": "S30403",
    "07Cr19Ni10": "S30409",
    "08Cr19Ni10Si2CeN": "S30450",
    "06Cr19Ni10N": "S30458",
    "022Cr19Ni10N": "S30453",
    "06Cr19Ni9NbN": "S30478",
    "08Cr21Ni11Si2CeN": "S30859",
    "06Cr23Ni13": "S30908",
    "06Cr25Ni20": "S31008",
    "015Cr20Ni18Mo6CuN": "S31252",
    "06Cr17Ni12Mo2": "S31608",
    "022Cr17Ni12Mo2": "S31603",
    "07Cr17Ni12Mo2": "S31609",
    "06Cr17Ni12Mo2N": "S31658",
    "06Cr17Ni12Mo2Ti": "S31668",
    "022Cr17Ni12Mo2N": "S31653",
    "06Cr19Ni13Mo3": "S31708",
    "022Cr19Ni13Mo3": "S31703",
    "06Cr18Ni11Ti": "S32168",
    "07Cr19Ni11Ti": "S32169",
    "06Cr18Ni11Nb": "S34778",
    "07Cr18Ni11Nb": "S34779",
    "05Cr19Mn6Ni5Cu2N": "S35656",
    "015Cr21Ni26Mo5Cu2": "S39042",
    "022Cr19Ni5Mo3Si2N": "S21953",
    "022Cr21Ni3Mo2N": "S22153",
    "022Cr22Ni5Mo3N": "S22253",
    "022Cr23Ni5Mo3N": "S22053",
    "03Cr22Mn5Ni2MoCuN": "S22294",
    "022Cr23Ni4MoCuN": "S23043",
    "03Cr25Ni6Mo3Cu2N": "S25554",
    "022Cr25Ni7Mo4N": "S25073"
}
def calculate_heat_exchanger_strength(product_id):
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
        SELECT *
        FROM 产品设计活动表_管口表
        WHERE 产品ID = %s
    """, (product_id,))
    port_rows = cursor.fetchall()
    ttdict = {}
    for i, row in enumerate(port_rows):
        key = string.ascii_lowercase[i]  # a, b, c, ...

        axial_angle = row.get("轴向夹角（°）", "")
        zhouxiangfangwei = row.get("周向方位（°）", "")

        ttdict[key] = {
            "ttNo": 0,
            "ttCode": clean_value(row.get("管口代号")),
            "ttUse": clean_value(row.get("管口功能")),
            "ttDN": clean_value(row.get("公称尺寸")),
            "ttPClass": clean_value(row.get("压力等级")),
            "ttType": clean_value(row.get("法兰型式")),
            "ttRF": clean_value(row.get("密封面型式")),
            "ttSpec": clean_value(row.get("焊端规格")),
            "ttAttach": clean_value(row.get("管口所属元件")),
            "ttPlace": {"左基准线": "左轮廓线", "右基准线": "右轮廓线"}.get(row.get("轴向定位基准", ""),
                                                                            clean_value(row.get("轴向定位基准"))),
            "ttLoc": clean_value(row.get("轴向定位距离")),
            "ttFW": clean_value(axial_angle),
            "ttThita": clean_value(row.get("密封面型式")),  # 与 ttRF 一致
            "ttAngel": clean_value(zhouxiangfangwei),
            "ttH": clean_value(row.get("偏心距")),
            "ttMemo": "默认"
        }

    # ===== 预设默认值 =====
    design_params = {
        "公称直径": "1000",
        "是否以外径为基准": "1",
        "介质类型": "介质易爆/极度危害/高度危害",
        "管箱圆筒长度工况": "工况1",
        "绝热厚度": "4",
        "预设厚度1": "5",
        "预设厚度2": "8",
        "预设厚度3": "10",
        "管箱/壳体圆筒是否统一厚度" : '1',
       "封头/圆筒是否统一厚度" :'0'
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
            design_params[key] = str(extra_param_map[key])
    # ===== 获取是否以外径为基准（来自通用数据表）=====
    cursor.execute("""
        SELECT 数值 FROM 产品设计活动表_通用数据表
        WHERE 产品ID = %s AND 参数名称 = '是否以外径为基准*'
    """, (product_id,))
    row = cursor.fetchone()
    if row and "数值" in row:
        val = str(row["数值"]).strip()
        design_params["是否以外径为基准"] = "1" if val == "是" else "0"

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
        "管箱封头": "椭圆形封头",
        "管箱圆筒": "筒体",
        "管箱法兰": "法兰",
        "管箱分程隔板": "分程隔板",
        "壳体圆筒": "筒体",
        "壳体法兰": "法兰",
        "固定管板": "a型管板（U型管）",
        "管束": "管束",
        "壳体封头": "椭圆形封头"
    }




    # 初始化字典
    guangxiang_fengtou = {

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
        "最大允许工作压力": "最高允许工作压力"
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
        guangxiang_fengtou["用户自定义耐压试验压力"] = str(val_max)
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
    if extra_map.get("是否添加覆层") == "有覆层":
        guangxiang_fengtou["是否覆层"] = "1"
        guangxiang_fengtou["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        guangxiang_fengtou["椭圆形封头覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
    else:
        guangxiang_fengtou["是否覆层"] = "0"
        guangxiang_fengtou["覆层复合方式"] = "轧制复合"
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
        "最大允许工作压力": "最高允许工作压力"
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
    if extra_map.get("是否添加覆层") == "有覆层":
        guangxiang_fengtou["是否覆层"] = "1"
        guangxiang_fengtou["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        guangxiang_fengtou["椭圆形封头覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
    else:
        guangxiang_fengtou["是否覆层"] = "0"
        guangxiang_fengtou["覆层复合方式"] = "轧制复合"
        guangxiang_fengtou["椭圆形封头覆层厚度"] = "0"

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
        "是否考虑液柱静压力": "否",
        "壳程液柱静压力": "0",
        "管程液柱静压力": "0",
        "压紧面形状序号": "1a",
        "法兰盘是否考虑腐蚀裕量": "是",
        "法兰压紧面压紧宽度ω": "0",
        "轴向外力": "0",
        "外力矩": "0",
        "任意式法兰是否按活套法兰计算": "否",
        "法兰类型": "松式法兰4",
        "法兰材料类型": "锻件",
        "法兰材料牌号": "16Mn",
        "法兰材料腐蚀裕量": "3",
        "法兰材料负偏差": "0",
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
        "圆筒材料负偏差": "0.3",
        "圆筒材料类型": "板材",
        "圆筒材料牌号": "Q345R",
        "焊缝高度": "0",
        "焊缝长度": "0",
        "焊缝深度": "0",
        "法兰种类": "长颈",
        "设计序号": "3",
        "公称直径管前左": "1000",
        "公称直径壳后右": "1200",
        "对接元件管前左内直径": "1000",
        "对接元件壳后右内直径": "1000",
        "对接元件管前左基层名义厚度": "20",
        "对接元件壳后右基层名义厚度": "30",
        "对接元件管前左负偏差": "0.1",
        "对接元件壳后右负偏差": "0.2",
        "对接元件管前左材料类型": "板材",
        "对接元件壳后右材料类型": "板材",
        "对接元件管前左材料牌号": "Q345R",
        "对接元件壳后右材料牌号": "Q345R",
        "是否带分程隔板管前左": "是",
        "是否带分程隔板壳后右": "是",
        "Am裕量": "0.3",
        "应力裕量": "0.3",
        "刚度裕量": "0.3",
        "筛选条件": "1",
        "法兰类型管前左": "整体法兰2",
        "法兰材料类型管前左": "锻件",
        "法兰材料牌号管前左": "16Mn",
        "法兰材料腐蚀裕量管前左": "3",
        "法兰材料负偏差管前左": "0",
        "法兰类型壳后右": "整体法兰2",
        "法兰材料类型壳后右": "锻件",
        "法兰材料牌号壳后右": "16Mn",
        "法兰材料腐蚀裕量壳后右": "3",
        "法兰材料负偏差壳后右": "0",
        "覆层厚度管前左": "0.2",
        "覆层厚度壳后右": "0.3",
        "对接元件覆层厚度管前左": "1.5",
        "堆焊层厚度壳后右": "1.6",
        "螺栓公称直径上限": "42",
        "螺栓公称直径下限": "22",
        "平盖序号": "9",
        "纵向焊接接头系数": "1",
        "平盖设计余量百分比": "0.2",
        "平盖设计余量常数": "3",
        "法兰位置管前左": "管箱法兰",
        "法兰位置壳后右": "壳体法兰",
        "法兰材料密度管前左": "10000",
        "法兰材料密度壳后右": "10000",
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
        "垫片代号": "2A",
        "隔条位置尺寸": "0"
    }

    # 从产品需求表中获取“产品型式”作为“换热器型号”
    # 切换数据库连接到产品需求库
    cursor.execute("USE 产品需求库")

    # 查询产品型式
    cursor.execute("""
        SELECT 产品型式 FROM 产品需求表
        WHERE 产品ID = %s
    """, (product_id,))
    row = cursor.fetchone()
    if row and "产品型式" in row:
        guanxiang_falan["换热器型号"] = str(row["产品型式"])


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
        "纵向焊接接头系数": ("焊接接头系数*", "壳程数值")
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
        "是否考虑液柱静压力": "否",
        "壳程液柱静压力": "0",
        "管程液柱静压力": "0",
        "压紧面形状序号": "1a",
        "法兰盘是否考虑腐蚀裕量": "是",
        "法兰压紧面压紧宽度ω": "0",
        "轴向外力": "0",
        "外力矩": "0",
        "任意式法兰是否按活套法兰计算": "否",
        "法兰类型": "松式法兰4",
        "法兰材料类型": "锻件",
        "法兰材料牌号": "16Mn",
        "法兰材料腐蚀裕量": "3",
        "法兰材料负偏差": "0",
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
        "圆筒材料负偏差": "0.3",
        "圆筒材料类型": "板材",
        "圆筒材料牌号": "Q345R",
        "焊缝高度": "0",
        "焊缝长度": "0",
        "焊缝深度": "0",
        "法兰种类": "长颈",
        "设计序号": "3",
        "公称直径管前左": "1000",
        "公称直径壳后右": "1200",
        "对接元件管前左内直径": "1000",
        "对接元件壳后右内直径": "1000",
        "对接元件管前左基层名义厚度": "20",
        "对接元件壳后右基层名义厚度": "30",
        "对接元件管前左负偏差": "0.1",
        "对接元件壳后右负偏差": "0.2",
        "对接元件管前左材料类型": "板材",
        "对接元件壳后右材料类型": "板材",
        "对接元件管前左材料牌号": "Q345R",
        "对接元件壳后右材料牌号": "Q345R",
        "是否带分程隔板管前左": "是",
        "是否带分程隔板壳后右": "否",
        "Am裕量": "0.3",
        "应力裕量": "0.3",
        "刚度裕量": "0.3",
        "筛选条件": "1",
        "法兰类型管前左": "整体法兰2",
        "法兰材料类型管前左": "锻件",
        "法兰材料牌号管前左": "16Mn",
        "法兰材料腐蚀裕量管前左": "3",
        "法兰材料负偏差管前左": "0",
        "法兰类型壳后右": "整体法兰2",
        "法兰材料类型壳后右": "锻件",
        "法兰材料牌号壳后右": "16Mn",
        "法兰材料腐蚀裕量壳后右": "3",
        "法兰材料负偏差壳后右": "0",
        "覆层厚度管前左": "0.2",
        "覆层厚度壳后右": "0.3",
        "堆焊层厚度管前左": "1.5",
        "堆焊层厚度壳后右": "1.6",
        "螺栓公称直径上限": "42",
        "螺栓公称直径下限": "22",
        "平盖序号": "9",
        "纵向焊接接头系数": "1",
        "平盖设计余量百分比": "0.2",
        "平盖设计余量常数": "3",
        "法兰位置管前左": "管箱法兰",
        "法兰位置壳后右": "壳体法兰",
        "法兰材料密度管前左": "10000",
        "法兰材料密度壳后右": "10000",
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
        "垫片代号": "2A",
        "隔条位置尺寸": "0"
    }

    # 切换数据库连接到产品需求库
    cursor.execute("USE 产品需求库")

    # 查询产品型式
    cursor.execute("""
            SELECT 产品型式 FROM 产品需求表
            WHERE 产品ID = %s
        """, (product_id,))
    row = cursor.fetchone()
    if row and "产品型式" in row:
        keti_falan["换热器型号"] = str(row["产品型式"])

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
        "纵向焊接接头系数": ("焊接接头系数*", "壳程数值")
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
        "材料类型": "板材",
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
        "管程腐蚀裕量": "2",
        "壳程腐蚀裕量": "2",
        "是否可以保证在任何情况下管壳程压力都能同时作用": "0",
        "换热管使用场合": "介质易爆/极度危害/高度危害",
        "换热管与管板连接方式": "焊接",
        "材料类型": "锻件",
        "材料牌号": "16Mn",
        "管板名义厚度": "0",
        "管板外径": "863",
        "管板强度削弱系数": "0.4",
        "壳程侧结构槽深": "0",
        "管程侧隔板槽深": "6",
        "换热管材料类型": "钢管",
        "换热管材料牌号": "10(GB9948)",
        "换热管外径": "25",
        "换热管壁厚": "2",
        "换热管中心距": "32",
        "换热管直管段长度": "3000",
        "耐压试验温度": "15",
        "内孔焊焊接接头系数": "1.0",
        "换热管与管板胀接长度或焊脚高度": "3.5",
        "换热管是否钢材": "1",
        "胀接管孔是否开槽": "1",
        "换热管根数": "220",
        "垫片材料名称": "复合柔性石墨波齿金属板(不锈钢)",
        "垫片与密封面接触外径": "863",
        "垫片与密封面接触内径": "825",
        "垫片厚度": "3",
        "压紧面形式": "1a或1b",
        "换热管排列方式": "正三角形",
        "折流板切口方向": "水平",
        "管/壳程布置型式": "4.2",
        "沿水平隔板槽一侧的排管根数": "26",
        "沿竖直隔板槽一侧的排管根数": "13",
        "水平隔板槽两侧相邻管中心距": "44",
        "垂直隔板槽两侧相邻管中心距": "100",
        "管板分程处面积Ad": "0",
        "是否交叉布管": "0",
        "交叉管排1最两端管孔中心距": "0",
        "交叉管排1实际管孔数量": "0",
        "交叉管排2最两端管孔中心距": "0",
        "交叉管排2实际管孔数量": "0",
        "交叉管排3最两端管孔中心距": "0",
        "交叉管排3实际管孔数量": "0"
    }





    # ===== 获取公称直径、绝热厚度、毒性/爆炸危险等 =====
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
                guanban_a[key] = "32"
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
        lower = row.get("管孔数量（下）", 0) or 0
        try:
            total_count += float(upper) + float(lower)
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
    if "垫片与密封面接触外径D2" in gasket_params:
        guanban_a["垫片与密封面接触外径"] = gasket_params["垫片与密封面接触外径D2"]
    if "垫片与密封面接触内径D1" in gasket_params:
        guanban_a["垫片与密封面接触内径"] = gasket_params["垫片与密封面接触内径D1"]
    if "压紧面形状" in gasket_params:
        guanban_a["压紧面形式"] = gasket_params["压紧面形状"]
    # 查询布管参数表中该产品的所有参数
    cursor.execute("""
        SELECT 参数名, 参数值
        FROM 产品设计活动表_布管参数表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()

    # 构建参数名称 → 参数值的映射
    tube_params = {row["参数名"].strip(): str(row["参数值"]).strip() for row in rows if row["参数值"] is not None}

    # 写入 guanban_a 字典
    if "换热管排列形式" in tube_params:
        guanban_a["换热管排列方式"] = tube_params["换热管排列形式"]
    if "折流板切口方向" in tube_params:
        guanban_a["折流板切口方向"] = tube_params["折流板切口方向"]
    if "管程分程形式" in tube_params:
        guanban_a["管/壳程布置型式"] = tube_params["管程分程形式"]
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
        "仅倾斜or交叉1排": "",
        "仅倾斜or交叉2排": "",
        "仅倾斜or交叉3排": "",
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
        "最后一块折流/支持板至最短直管末端距离": "50",
        "折流板切口与中心线间距": "200",
        "圆筒内径": "800",
        "公称直径": "1000",
        "滑道与固定管板是否焊接连接": "是",
        "滑道伸出折流板/支持板最小值": "50",
        "是否交叉布管": "否",
        "接管外径1": "0",
        "接管外径2": "0",
        "接管名义厚度": "16",
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
        "尾部支撑类型": "防振杆",
        "折流板厚度初始值": "10",
        "U形换热管最大弯曲直径": "2000",
        "换热管材料序号": "1",
        "拉杆直径": "10"
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

    cursor.execute("""
        SELECT 参数名, 参数值
        FROM 产品设计活动表_布管参数表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()

    for row in rows:
        param_name = row["参数名"].strip()
        value = row["参数值"]
        if param_name in bgtube_map and value is not None:
            tube_bundle[bgtube_map[param_name]] = str(value)
    more_tube_params = {
        "布管限定圆 DL": "布管限定圆直径",
        "换热管公称长度LN": "换热管理论直管长度",
        "折流板切口与中心线间距": "折流板切口与中心线间距",
        "换热管外径 do": "换热管外径"
    }

    # 合并映射（之前已有 bgtube_map）
    bgtube_map.update(more_tube_params)

    # 读取并写入
    cursor.execute("""
        SELECT 参数名, 参数值
        FROM 产品设计活动表_布管参数表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()

    for row in rows:
        param_name = row["参数名"].strip()
        value = row["参数值"]
        if param_name in bgtube_map and value is not None:
            tube_bundle[bgtube_map[param_name]] = str(value)
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
        tube_bundle["管板类型"] = str(row["管板类型"])

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

    result = {
        "WSList": wslist,
        "TTDict": ttdict,
        "DesignParams": design_params,
        "DictPart": dict_part,
        "DictDatas": {
            "管箱封头": guangxiang_fengtou,
            "管箱圆筒": guanxiang_yuantong,
            "管箱法兰": guanxiang_falan,
            "管箱分程隔板": fencheng_geban,
            "壳体圆筒": qiaoti_yuantong,
            "壳体法兰": keti_falan,
            # "固定管板": gudingguanban,
            "固定管板":guanban_a,
            "管束": tube_bundle,
            "壳体封头": keti_fengtou,

        }
    }


    if row:
        result["ProjectName"] = row.get("产品名称", "UnnamedProject")
        result["ExchangerType"] = row.get("产品型式", "Unknown")



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


    # 保存结果到JSON文件
    with open("result_qiangdujisuan.json", "w", encoding="utf-8") as f:
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
    with open("result_qiangdujisuan.json", "r", encoding="utf-8") as f:
        json_input = f.read()
    parsed = json.loads(json_input)
    compact_json = json.dumps(parsed, separators=(',', ':'))

    cpi = CalPartInterface()
    calculation_result = cpi.IntergratedEquipment(compact_json)

    # 保存计算结果
    # with open("modules/qiangdujisuan/jiekou_python/jisuan_output.json", "w", encoding="utf-8") as f:
    with open("jisuan_output.json", "w", encoding="utf-8") as f:
        json.dump(json.loads(calculation_result), f, ensure_ascii=False, indent=4)
    return calculation_result


if __name__ == "__main__":
    product_id = 'PD20250625001'  # 替换为你自己的产品ID
    result = calculate_heat_exchanger_strength(product_id)
    print(result)