import json
import time

import pymysql
import pythoncom

from modules.TwoD.toubiaotu_biaozhu import apply_dimension_labels
from modules.TwoD.toubiaotu_wenziduixiang_NEN_1 import twoDgeneration


def get_db_connection():
    conn = pymysql.connect(
        host="localhost",
        port=3306,
        user="root",
        password="123456",
        database="产品设计活动库",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )
    return conn, conn.cursor()

def _apply_nozzle_code_labels(handle_label_dict, product_id, handle_to_function):
    """把图纸上固定的 N1/N2/L1 等管口标号替换成当前产品真实管口代号。"""
    if not handle_to_function:
        return

    conn = None
    try:
        conn, cursor = get_db_connection()
        functions = sorted(set(handle_to_function.values()))
        placeholders = ", ".join(["%s"] * len(functions))
        cursor.execute(f"""
            SELECT 管口代号, 管口功能
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口功能 IN ({placeholders})
        """, (product_id, *functions))
        port_code_by_function = {
            str(row.get("管口功能", "")).strip(): str(row.get("管口代号") or "").strip()
            for row in cursor.fetchall()
            if row.get("管口功能")
        }

        for handle, function_name in handle_to_function.items():
            port_code = port_code_by_function.get(function_name, "")
            if port_code:
                handle_label_dict[handle] = port_code
            else:
                print(f"⚠️ 未找到管口功能 {function_name} 的管口代号，跳过 handle {handle}")
    except Exception as exc:
        print(f"⚠️ 写入管口代号标注失败: {exc}")
    finally:
        if conn:
            conn.close()


def toubiaotu_NEN_1_1(product_id):
    twoDgeneration(product_id)
    handle_label_dict = {
        "81815": '',
        "817ec": "",
        "817f3": "",
        '817F8': '7036',
        '81811': '6500',
        '7786A': '滑动鞍座至固定鞍座距离',
        '77854': '滑动鞍座至固定鞍座距离',
        "818BB": "管程入口接管",
        "81905": "管程出口接管",
        "819E5": "壳程入口接管",
        "81A03": "壳程出口接管",
        '81886': '7036',
        '77994': '6500',
        '81592': '滑动鞍座至固定鞍座距离',
        '81883': '滑动鞍座至固定鞍座距离',
        '77992': '固定鞍座至壳程圆筒左端距离+8',
        '77990': '默认',
        '77C75': '默认',
        '81889': '1000',
        '8188B': '1000',
        '779A3': '封头覆层厚度',
        '81881': '1，2号管口距离',
        '81890': '1000',
        '8188E': '1000',
        "819E9": "支座高度",
        "8161B": "1",
        '779E6': '',
        '816E9': '',
        '816F0': '',
        '817F0': '',
        '81711': '1000',
        '81756': '1000',
        '77988': '封头覆层厚度',
        '77989': '1，2号管口距离',
        '77997': '1000',
        "816EC": '封头到管箱距离',
        "817F1": "支座高度",
        "816C3": '封头到管箱距离',
        "816ED": "管程连接厚度",
        "815E1": "支座高度",
        '815E0': '管口和底座差值',
        "815DA": "",
        "85db6": "",
        "87bcb": "",
        "87c26": "",
        "87973": "",
        "87bcd": "",
        "87bcc": "",
        "87970": "",
        "87a62": "",
        "87c27": "",
        "87b33": "",
        "87c23": "",
        "87c2a": "",
        "87bd1": "",
        "87bd0": "",
        "87bd3": "",
        "87bd2": "",
        "87c2d": "",
        "87ba6": "",

    }

    with open("jisuan_output_new_tidai.json", "r", encoding="utf-8") as f:
        json_data = json.load(f)

    dict_out = json_data.get("DictOutDatas", {})
    data_by_module = {
        module: datas["Datas"]
        for module, datas in dict_out.items()
        if datas.get("IsSuccess")
    }


    def get_val(module, name):
        for entry in data_by_module.get(module, []):
            if entry.get("Name") == name:
                try:
                    return float(entry.get("Value", 0))
                except:
                    return 0
        return 0


    def get_val_by_id_and_name(module, id_str, name_str):
        for entry in data_by_module.get(module, []):
            if entry.get("Name") == name_str and entry.get("Id") == id_str:
                try:
                    return float(entry.get("Value", 0))
                except:
                    return 0
        return 0


    import pymysql

    conn = pymysql.connect(
        host="localhost",
        user="root",
        password="123456",
        database="产品设计活动库",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )
    cursor = conn.cursor()

    # 读取圆筒内径
    cursor.execute("""
                                SELECT Value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s 
                                  AND 元件名称 = '管箱圆筒' 
                                  AND Name = '圆筒名义厚度'
                            """, (product_id,))
    row = cursor.fetchone()
    yuantongmingyihoudu = float(row["Value"])
    handle_label_dict["87bcb"] = yuantongmingyihoudu
    cursor.execute("""
                                SELECT Value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s 
                                  AND 元件名称 = '后端管箱圆筒' 
                                  AND Name = '圆筒名义厚度'
                            """, (product_id,))
    row = cursor.fetchone()
    yuantongmingyihoudu = float(row["Value"])
    handle_label_dict["87bd3"] = yuantongmingyihoudu
    # like_pattern = "%腐蚀前%"
    # cursor.execute("""
    #     SELECT Value
    #     FROM 产品设计活动表_元件计算结果表
    #     WHERE 产品ID = %s
    #       AND 元件名称 = '固定管板'
    #       AND Id LIKE %s
    #       AND Name = '壳程端部圆筒名义厚度δsdn'
    # """, (product_id, like_pattern))
    # row = cursor.fetchone()
    # duanbuyuantongmingyihoudu = float(row["Value"])
    # handle_label_dict["87bd1"] = duanbuyuantongmingyihoudu
    # handle_label_dict["87bcd"] = duanbuyuantongmingyihoudu

    cursor.execute("""
                        SELECT 管口所属元件, 轴向定位距离
                        FROM 产品设计活动表_管口表
                        WHERE 产品ID = %s AND `周向方位（°）` = 0
                        LIMIT 2
                    """, (product_id,))
    ports = cursor.fetchall()


    def parse_axis_position(raw, module):
        raw = str(raw).strip()
        if module == "管箱圆筒":
            if raw == "默认":
                return get_val("管箱圆筒", "圆筒长度")
            elif raw == "居中":
                return get_val("管箱圆筒", "圆筒长度") / 2
        elif module == "壳体圆筒":
            if raw == "默认":
                return 0
            elif raw == "居中":
                return get_val("壳体圆筒", "圆筒长度") / 2
        try:
            return float(raw)
        except:
            return 0


    tutai_height = "0"  # 默认值
    cursor.execute("""
                        SELECT 参数值
                        FROM 产品设计活动表_元件附加参数表
                        WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管板凸台高度'
                        LIMIT 1
                    """, (product_id,))
    row = cursor.fetchone()
    if row:
        try:
            val = str(row.get("参数值", "")).strip()
            if val not in ("", "None"):
                tutai_height = float(val)
        except (ValueError, TypeError):
            tutai_height = 10  # 或保留默认值

    print(f"✅ 管板凸台高度 = {tutai_height}")

    if len(ports) == 2:
        print("ports:", ports)
        d1 = parse_axis_position(ports[0]["轴向定位距离"], ports[0]["管口所属元件"])
        d2 = parse_axis_position(ports[1]["轴向定位距离"], ports[1]["管口所属元件"])
        base_distance = abs(d1 - d2)
        print("固定管板厚度 =", get_val("固定管板", "管板名义厚度"))
        print("管箱法兰垫片厚度 =", get_val("管箱法兰", "垫片厚度"))
        print("壳体法兰垫片厚度 =", get_val("壳体法兰", "垫片厚度"))
        print("tutai_height =", tutai_height)

        handle_label_dict["815EA"] = str(round(base_distance, 3)) + "±6"

        # 读取圆筒内径
        cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳程入口接管' 
                  AND Name = '接管中心线到圆筒边缘距离'
            """, (product_id,))
        row = cursor.fetchone()
        rukoujieguan_juli = float(row["Value"])
        cursor.execute("""
                        SELECT Value
                        FROM 产品设计活动表_元件计算结果表
                        WHERE 产品ID = %s 
                          AND 元件名称 = '壳程出口接管' 
                          AND Name = '接管中心线到圆筒边缘距离'
                    """, (product_id,))
        row = cursor.fetchone()
        chukoujieguan_juli = float(row["Value"])
        cursor.execute("""
                        SELECT Value
                        FROM 产品设计活动表_元件计算结果表
                        WHERE 产品ID = %s 
                          AND 元件名称 = '壳体圆筒' 
                          AND Name = '圆筒长度'
                    """, (product_id,))
        row = cursor.fetchone()
        yuantongchangdu = float(row["Value"])

        handle_label_dict["8161B"] = float(yuantongchangdu) - float(chukoujieguan_juli) - float(
            rukoujieguan_juli)


    else:
        handle_label_dict["8161B"] = "[未找到2个管口]"

    for handle, label in handle_label_dict.items():
        if handle == "87b33":
            total_length = (
                    (
                            get_val("管箱平盖", "法兰名义厚度") +
                            +6 + 1.5 +
                            get_val("头盖法兰", "法兰总高")) * 2 +
                    get_val("管箱圆筒", "圆筒长度") +
                    get_val("后端管箱圆筒", "圆筒长度") +
                    get_val("壳体圆筒", "圆筒长度") +
                    get_val("固定管板", "管板名义厚度") * 2

            )
            handle_label_dict[handle] = round(total_length, 3)
            # 刷新消息队列，防止 COM 超时
            pythoncom.PumpWaitingMessages()

            # 短暂延时，让 AutoCAD 处理内部消息
            time.sleep(0.1)  # 50ms，可根据情况调整
        elif handle != "8161B":
            found = False
            for module_name, entries in data_by_module.items():
                for entry in entries:
                    if entry.get("Name") == label:
                        handle_label_dict[handle] = entry.get("Value", "")
                        found = True
                        break
                if found:
                    break
    conn = pymysql.connect(
        host="localhost",
        user="root",
        password="123456",
        database="产品设计活动库",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )

    cursor = conn.cursor()

    # 读取圆筒内径
    cursor.execute("""
            SELECT Value
            FROM 产品设计活动表_元件计算结果表
            WHERE 产品ID = %s 
              AND 元件名称 = '壳体圆筒' 
              AND Name = '圆筒内径'
        """, (product_id,))
    row = cursor.fetchone()
    cylinder_inner_diameter = float(row["Value"]) / 2 if row else 0.0

    # 读取圆筒名义厚度
    cursor.execute("""
            SELECT Value
            FROM 产品设计活动表_元件计算结果表
            WHERE 产品ID = %s 
              AND 元件名称 = '壳体圆筒' 
              AND Name = '圆筒名义厚度'
        """, (product_id,))
    row = cursor.fetchone()
    cylinder_nominal_thickness = float(row["Value"]) if row else 0.0

    # 读取鞍式支座高度 h
    cursor.execute("""
            SELECT Value
            FROM 产品设计活动表_元件计算结果表
            WHERE 产品ID = %s 
              AND 元件名称 = '鞍座' 
              AND Name = '鞍式支座高度h'
        """, (product_id,))
    row = cursor.fetchone()
    saddle_height = float(row["Value"]) if row else 0.0

    # 三者求和
    total_value = cylinder_inner_diameter + cylinder_nominal_thickness + saddle_height

    # 填入 handle_label_dict
    handle_label_dict["87f93"] = f"{total_value}"
    # === 查询数据库：N2 和 N4 的 外伸高度
    cursor.execute("""
                            SELECT 元件名称, value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管大端外径'
                        """, (product_id,))
    rows = cursor.fetchall()
    # 构建管口代号 → 外伸高度 映射
    out_len_map = {
        row["元件名称"]: str(row.get("value", "")).strip()
        for row in rows if row.get("元件名称")
    }
    n2_len = out_len_map.get("管程出口接管", "")
    n1_len = out_len_map.get("管程入口接管", "")
    n3_len = out_len_map.get("壳程入口接管", "")
    n4_len = out_len_map.get("壳程出口接管", "")
    n5_len = out_len_map.get("排气口接管", "")
    n6_len = out_len_map.get("排液口接管", "")
    cursor.execute("""
                            SELECT 元件名称, value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管名义厚度'
                        """, (product_id,))
    rows = cursor.fetchall()
    # 构建管口代号 → 外伸高度 映射
    out_len_map = {
        row["元件名称"]: str(row.get("value", "")).strip()
        for row in rows if row.get("元件名称")
    }
    n2_houdu = out_len_map.get("管程出口接管", "")
    n1_houdu = out_len_map.get("管程入口接管", "")
    n3_houdu = out_len_map.get("壳程入口接管", "")
    n4_houdu = out_len_map.get("壳程出口接管", "")
    n5_houdu = out_len_map.get("排气口接管", "")
    n6_houdu = out_len_map.get("排液口接管", "")
    handle_label_dict["87c49"] = f"∅{n1_len}x{n1_houdu}"
    handle_label_dict["87c64"] = f"∅{n2_len}x{n2_houdu}"
    handle_label_dict["87bd5"] = f"∅{n3_len}x{n3_houdu}"
    handle_label_dict["87bd4"] = f"∅{n4_len}x{n4_houdu}"
    handle_label_dict["817EC"] = f"∅{n5_len}x{n5_houdu}"
    handle_label_dict["817ED"] = f"∅{n6_len}x{n6_houdu}"

    # === 查询数据库：N2 和 N4 的 外伸高度
    cursor.execute("""
                        SELECT 元件名称, value
                        FROM 产品设计活动表_元件计算结果表
                        WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管') AND Name = '接管实际外伸长度'
                    """, (product_id,))
    rows = cursor.fetchall()

    # 构建管口代号 → 外伸高度 映射
    out_len_map = {
        row["元件名称"]: str(row.get("value", "")).strip()
        for row in rows if row.get("元件名称")
    }

    # === N2 → handle 779E6
    n2_len = out_len_map.get("排气口接管", "")
    handle_label_dict["779E6"] = n2_len
    print(f"✅ 管口 N2 → 外伸高度 → handle 779E6 = {n2_len}")
    kt_value = ""
    # === 查询管程和壳程公称直径 ===
    cursor.execute("""
                        SELECT 参数名称, 管程数值, 壳程数值
                        FROM 产品设计活动表_设计数据表
                        WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                    """, (product_id,))
    rows = cursor.fetchall()

    # === 提取参数值并写入 handle_label_dict ===
    for row in rows:
        kt_value = str(row.get("壳程数值", "")).strip()

    # === N4 → handle 779EA
    n4_len = out_len_map.get("排液口接管", "")
    # === 查询数据库：N2 和 N4 的 外伸高度
    cursor.execute("""
                            SELECT 元件名称, value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管') AND Name = '开孔元件外径'
                        """, (product_id,))
    rows = cursor.fetchall()

    # 构建管口代号 → 外伸高度 映射
    out_len_map = {
        row["元件名称"]: str(row.get("value", "")).strip()
        for row in rows if row.get("元件名称")
    }
    waijing1 = out_len_map.get("排液口接管", "")
    waijing2 = out_len_map.get("排气口接管", "")
    waijing3 = out_len_map.get("管程入口接管", "")
    waijing4 = out_len_map.get("管程出口接管", "")
    waijing5 = out_len_map.get("壳程入口接管", "")
    waijing6 = out_len_map.get("壳程出口接管", "")
    cursor.execute("""
                            SELECT 元件名称, value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管') AND Name = '接管实际外伸长度'
                        """, (product_id,))
    rows = cursor.fetchall()

    # 构建管口代号 → 外伸高度 映射
    out_len_map = {
        row["元件名称"]: str(row.get("value", "")).strip()
        for row in rows if row.get("元件名称")
    }
    changdu1 = out_len_map.get("排液口接管", "")
    changdu2 = out_len_map.get("排气口接管", "")
    changdu3 = out_len_map.get("管程入口接管", "")
    changdu4 = out_len_map.get("管程出口接管", "")
    changdu5 = out_len_map.get("壳程入口接管", "")
    changdu6 = out_len_map.get("壳程出口接管", "")
    import pymysql

    # === 数据库连接 ===
    conn_product = pymysql.connect(
        host="localhost", user="root", password="123456",
        database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
    )
    conn_material = pymysql.connect(
        host="localhost", user="root", password="123456",
        database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
    )
    conn_component = pymysql.connect(
        host="localhost", user="root", password="123456",
        database="元件库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
    )

    cur = conn_product.cursor()
    cur2 = conn_material.cursor()
    cur3 = conn_component.cursor()

    # === 1. 获取管口表数据（排气口、排液口）===
    cur.execute("""
            SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口功能 IN ('排气口', '排液口','管程入口', '管程出口','壳程入口', '壳程出口')
        """, (product_id,))
    ports = cur.fetchall()

    # === 2. 获取管口类型选择表 (尺寸/压力类型) ===
    cur.execute("""
            SELECT 公称尺寸类型, 公称压力类型
            FROM 产品设计活动表_管口类型选择表
            WHERE 产品ID = %s
        """, (product_id,))
    type_info = cur.fetchone()  # 一个产品只会有一行配置

    # 默认类型（防止为空）
    size_type = type_info["公称尺寸类型"] if type_info else "DN"
    press_type = type_info["公称压力类型"] if type_info else "PN"

    # === 3. 获取公称尺寸 NPS → DN 对照表 ===
    cur3.execute("SELECT NPS, DN FROM 公称尺寸表")
    nps_rows = cur3.fetchall()
    nps_map = {str(r["NPS"]).strip(): str(r["DN"]).strip() for r in nps_rows}

    # === 4. 获取管法兰质量表数据 ===
    # === 4. 获取管法兰质量表数据 ===
    cur2.execute("SELECT * FROM 管法兰质量表")
    flange_rows = cur2.fetchall()

    # === 5. 匹配逻辑 ===
    gaodu1 = gaodu2 = gaodu3 = gaodu4 = gaodu5 = gaodu6 = 0.0


    def clean_val(v):
        """清洗 0.0、'None'、空格等无效值"""
        if v is None:
            return ""
        v = str(v).strip()
        if v.lower() == "none":
            return ""
        return v


    for port in ports:
        code = clean_val(port.get("管口代号"))
        func = clean_val(port.get("管口功能"))
        std = clean_val(port.get("法兰标准"))
        size = clean_val(port.get("公称尺寸"))
        pressure = clean_val(port.get("压力等级"))
        flange_type = clean_val(port.get("法兰型式"))
        face_type = clean_val(port.get("密封面型式"))

        # --- 公称尺寸处理 ---
        if size_type.upper() == "NPS":
            size = nps_map.get(size, size)  # NPS → DN

        # --- 遍历法兰质量表匹配 ---
        for row in flange_rows:
            std_db = clean_val(row.get("标准"))
            dn_db = clean_val(row.get("DN"))
            pn_db = clean_val(row.get("PN"))
            cls_db = clean_val(row.get("Class"))
            type_db = clean_val(row.get("法兰型式代号"))

            # === 匹配逻辑 ===
            # 标准匹配（仅当表中标准不为空时才判断）
            if std_db and std_db != std:
                continue
            # 公称尺寸匹配（仅当表中DN不为空时才判断）
            if dn_db and dn_db != size:
                continue
            # 压力等级匹配
            if press_type.upper() == "PN":
                if pn_db and pn_db != pressure:
                    continue
            elif press_type.upper() == "CLASS":
                if cls_db and cls_db != pressure:
                    continue
            # 法兰型式匹配（仅当表中有定义时才判断）
            if type_db and flange_type and type_db != flange_type:
                continue

            # ✅ 只取 H+密封面型式 对应的列
            if face_type:  # 确保 face_type 有值
                face_col = f"H{face_type}" if face_type else ""
                if face_col:
                    val = clean_val(row.get(face_col)) if face_col in row else ""
                    if func == "排液口":
                        gaodu1 = val
                    elif func == "排气口":
                        gaodu2 = val
                    elif func == "管程入口":
                        gaodu3 = val
                    elif func == "管程出口":
                        gaodu4 = val
                    elif func == "壳程入口":
                        gaodu5 = val
                    elif func == "壳程出口":
                        gaodu6 = val
            break  # 找到一个匹配项就退出

    print("排液口对应值:", gaodu1)
    print("排气口对应值:", gaodu2)
    cursor.execute("""
           SELECT Value
           FROM 产品设计活动表_元件计算结果表
           WHERE 产品ID = %s 
             AND 元件名称 = '管程入口接管' 
             AND Name = '接管总外伸高度'
       """, (product_id,))
    row = cursor.fetchone()
    guanchengrukoujieguan_waishengaodu =float(row["Value"]) if row else 0.0
    cursor.execute("""
                           SELECT Value
                           FROM 产品设计活动表_元件计算结果表
                           WHERE 产品ID = %s 
                             AND 元件名称 = '管程入口接管' 
                             AND Name = '接管中心线到圆筒边缘距离'
                       """, (product_id,))
    row = cursor.fetchone()
    guanchengrukoujieguan_jieguandingwei = float(row["Value"]) if row else 0.0

    cursor.execute("""
           SELECT Value
           FROM 产品设计活动表_元件计算结果表
           WHERE 产品ID = %s 
             AND 元件名称 = '管程出口接管' 
             AND Name = '接管总外伸高度'
       """, (product_id,))
    row = cursor.fetchone()
    guanchengchukoujieguan_waishengaodu =float(row["Value"]) if row else 0.0
    cursor.execute("""
           SELECT Value
           FROM 产品设计活动表_元件计算结果表
           WHERE 产品ID = %s 
             AND 元件名称 = '壳程入口接管' 
             AND Name = '接管总外伸高度'
       """, (product_id,))
    row = cursor.fetchone()
    qiaochengrukoujieguan_waishengaodu =float(row["Value"]) if row else 0.0
    cursor.execute("""
                           SELECT Value
                           FROM 产品设计活动表_元件计算结果表
                           WHERE 产品ID = %s 
                             AND 元件名称 = '壳程入口接管' 
                             AND Name = '接管中心线到圆筒边缘距离'
                       """, (product_id,))
    row = cursor.fetchone()
    qiaochengrukoujieguan_jieguandingwei = float(row["Value"]) if row else 0.0
    cursor.execute("""
           SELECT Value
           FROM 产品设计活动表_元件计算结果表
           WHERE 产品ID = %s 
             AND 元件名称 = '壳程出口接管' 
             AND Name = '接管总外伸高度'
       """, (product_id,))
    row = cursor.fetchone()
    qiaochengchukoujieguan_waishengaodu =float(row["Value"]) if row else 0.0
    cursor.execute("""
           SELECT Value
           FROM 产品设计活动表_元件计算结果表
           WHERE 产品ID = %s 
             AND 元件名称 = '排气口接管' 
             AND Name = '接管总外伸高度'
       """, (product_id,))
    row = cursor.fetchone()
    paiqikoujieguan_waishengaodu =float(row["Value"]) if row else 0.0
    cursor.execute("""
           SELECT Value
           FROM 产品设计活动表_元件计算结果表
           WHERE 产品ID = %s 
             AND 元件名称 = '排液口接管' 
             AND Name = '接管中心线到圆筒边缘距离'
       """, (product_id,))
    row = cursor.fetchone()
    paiyekoukoujieguan_jieguandingwei = float(row["Value"]) if row else 0.0
    cursor.execute("""
           SELECT Value
           FROM 产品设计活动表_元件计算结果表
           WHERE 产品ID = %s 
             AND 元件名称 = '排液口接管' 
             AND Name = '接管总外伸高度'
       """, (product_id,))
    row = cursor.fetchone()
    paiyekoukoujieguan_waishengaodu =float(row["Value"]) if row else 0.0
    print(f"✅ 管口 N4 → 外伸高度 → handle 779EA = {n4_len}")
    handle_label_dict["88200"] = str(round(float(paiqikoujieguan_waishengaodu),2)) + "±3"
    handle_label_dict["87c26"] = str(round(float(guanchengrukoujieguan_waishengaodu),2)) + "±3"
    handle_label_dict["87c27"] = str(round(float(qiaochengrukoujieguan_waishengaodu),2)) + "±3"
    handle_label_dict["87c2a"] = str(round(float(qiaochengchukoujieguan_waishengaodu),2)) + "±3"
    handle_label_dict["87c2d"] = str(round(float(guanchengchukoujieguan_waishengaodu),2)) + "±3"
    handle_label_dict["88228"] = str(round(float(paiyekoukoujieguan_waishengaodu),2)) + "±3"

    handle_label_dict["87973"] = str(guanchengrukoujieguan_jieguandingwei) + "±3"
    handle_label_dict["87970"] = str(qiaochengrukoujieguan_jieguandingwei) + "±3"
    handle_label_dict["87ba6"] = str(paiyekoukoujieguan_jieguandingwei) + "±3"

    # === 从 JSON 中读取鞍式支座高度h ===
    support_height = 0
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "鞍式支座高度h":
            try:
                support_height = float(entry.get("Value", 0))
            except:
                support_height = 0
            break
    l1_val = 0.0
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "底板长度":
            l1_val = entry.get("Value", "")
            break

    # === 更新两个 handle 对应的值
    handle_label_dict["817F4"] = l1_val
    handle_label_dict["87fc3"] = l1_val
    l9_val = 0.0
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "G":
            l9_val = entry.get("Value", "")
            break

    # === 更新两个 handle 对应的值
    handle_label_dict["8161b"] = l9_val
    lhoudu_val = 0
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "底板厚度":
            lhoudu_val = entry.get("Value", "")
            break

    handle_label_dict["88123"] = lhoudu_val

    juli1 = 0
    juli1 = (get_val("管箱平盖", "法兰名义厚度") +
             get_val("头盖法兰", "法兰颈部高度") +
             get_val("头盖法兰", "法兰名义厚度") +
             get_val("管程入口接管", "接管中心线到圆筒边缘距离")
             )
    handle_label_dict["815ca"] = juli1

    # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
    l2_val = 0.0
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "螺栓孔间距1":
            l2_val = entry.get("Value", "")
            break
    # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
    l6_val = 0.0
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "H":
            l6_val = entry.get("Value", "")
            break
    # === 更新两个 handle 对应的值
    handle_label_dict["87a62"] = l6_val
    # === 更新两个 handle 对应的值
    handle_label_dict["87fc2"] = f"{l2_val}±2"
    b5_val = 0.0
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "D":
            b5_val = entry.get("Value", "")
            break
    handle_label_dict["87a6b"] = b5_val
    handle_label_dict["817f0"] = b5_val

    print(f"✅ 间距l2 → handle 817F0, 87a6b = {l2_val}")
    # === 更新两个 handle 对应的值
    b1_val = 0.0
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "底板宽度":
            b1_val = entry.get("Value", "")
            break
    handle_label_dict["81813"] = float(b1_val) / 2
    print("81813", float(b1_val) / 2)
    handle_label_dict["81814"] = float(b1_val) / 2
    # === 更新两个 handle 对应的值
    handle_label_dict["817EC"] = float(b1_val)
    print(float(b1_val))
    handle_label_dict["817ED"] = float(b1_val)
    # === 从 JSON 中提取 鞍座 → l3 的值 ===
    l3_val = 0.0
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "螺栓孔间距1":
            l3_val = entry.get("Value", "")
            break
    luoshuan_shuliang = 0.0
    luoshuan_zhijing = 0.0
    handle_label_dict["817F3"] = str(l3_val) + "±2"
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "螺栓数量":
            luoshuan_shuliang = entry.get("Value", "")
        if entry.get("Name") == "螺孔直径":
            luoshuan_zhijing = entry.get("Value", "")
    print("螺栓数量", luoshuan_shuliang)
    handle_label_dict["81815"] = f"{luoshuan_shuliang}-∅{luoshuan_zhijing}"
    s1 = 0.0
    # 底板厚度
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "底板厚度":
            s1 = entry.get("Value", "")
    print("s1", s1)
    print("Before:", handle_label_dict.get("817F8"))
    handle_label_dict["817F8"] = s1
    print("After:", handle_label_dict.get("817F8"))
    handle_label_dict["81811"] = s1

    print(f"✅ l3 → handle 77992 = {l3_val}")
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "螺孔长度":
            b1_val = entry.get("Value", "")
            break
    # === 更新两个 handle 对应的值
    handle_label_dict["817F2"] = b1_val
    print("b1_val", b1_val)

    print(f"✅ 间距l2 → handle 77993, 77C15 = {l2_val}")
    # === 从 JSON 中提取 鞍座 → l3 的值 ===
    l3_val = 0.0
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "筋板长度":
            l3_val = entry.get("Value", "")
            break

    handle_label_dict["77992"] = l3_val
    print(f"✅ l3 → handle 77992 = {l3_val}")
    # === 77C75: 管程出口接管 → 接管定位距
    gp_exit_val = 0.0
    gp_exit_val1 = 0
    for entry in data_by_module.get("管程出口接管", []):
        if entry.get("Name") == "接管定位距":
            gp_exit_val = entry.get("Value", "")
            break
    for entry in data_by_module.get("管箱法兰", []):
        if entry.get("Name") == "法兰总高":
            gp_exit_val1 = entry.get("Value", "")
            break
    handle_label_dict["77C75"] = float(gp_exit_val) + float(gp_exit_val1)
    print(f"✅ 管程出口接管 → 接管定位距 → handle 77C75 = {gp_exit_val}")

    # === 77990: 壳程出口接管 → 接管定位距
    shell_exit_val = 0.0
    shell_exit_val2 = 0.0
    for entry in data_by_module.get("壳程出口接管", []):
        if entry.get("Name") == "接管定位距":
            shell_exit_val = entry.get("Value", "")
            break
    for entry in data_by_module.get("壳体法兰", []):
        if entry.get("Name") == "法兰总高":
            shell_exit_val2 = entry.get("Value", "")
            break
    handle_label_dict["77990"] = float(shell_exit_val) + float(shell_exit_val2)
    print(f"✅ 壳程出口接管 → 接管定位距 → handle 77990 = {shell_exit_val}")
    # === 定义新的映射关系：handle → 模块名
    handle_to_module = {
        "77988": "管程入口接管",
        "779A4": "管程出口接管",
        "77989": "壳程入口接管",
        "77997": "壳程出口接管"
    }

    # === 构造值并写入 handle_label_dict
    for handle, module in handle_to_module.items():
        entries = data_by_module.get(module, [])


        def get_entry_val(param_name):
            for entry in entries:
                if entry.get("Name") == param_name:
                    return entry.get("Value")
            return None


        od = get_entry_val("接管大端外径")
        thick = get_entry_val("接管大端壁厚")
        l1 = get_entry_val("接管实际外伸长度") or 0
        l2 = get_entry_val("接管实际内伸长度") or 0

        try:
            if None not in (od, thick):
                od = float(od)
                thick = float(thick)
                l1 = float(l1)
                l2 = float(l2)
                value = f"∅{od}×{thick}"
            else:
                value = ""
        except Exception as e:
            print(f"❌ 处理 {module} 时出错: {e}")
            value = ""

        handle_label_dict[handle] = value
        print(f"✅ {module} → handle {handle} = {value}")

    # === 连接数据库，查找管程和壳程公称直径 ===
    conn = pymysql.connect(
        host="localhost",
        user="root",
        password="123456",
        database="产品设计活动库",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )
    cursor = conn.cursor()
    # 读取圆筒名义厚度
    cursor.execute("""
               SELECT Value
               FROM 产品设计活动表_元件计算结果表
               WHERE 产品ID = %s 
                 AND 元件名称 = '外头盖圆筒' 
                 AND Name = '圆筒内径'
           """, (product_id,))
    row = cursor.fetchone()
    yuantong_neijing = float(row["Value"]) if row else 0.0
    cursor.execute("""
               SELECT Value
               FROM 产品设计活动表_元件计算结果表
               WHERE 产品ID = %s 
                 AND 元件名称 = '管箱圆筒' 
                 AND Name = '圆筒内径'
           """, (product_id,))
    row = cursor.fetchone()
    yuantong_neijing2 = float(row["Value"]) if row else 0.0
    cursor.execute("""
               SELECT Value
               FROM 产品设计活动表_元件计算结果表
               WHERE 产品ID = %s 
                 AND 元件名称 = '后端管箱圆筒' 
                 AND Name = '圆筒内径'
           """, (product_id,))
    row = cursor.fetchone()
    yuantong_neijing4 = float(row["Value"]) if row else 0.0
    cursor.execute("""
               SELECT Value
               FROM 产品设计活动表_元件计算结果表
               WHERE 产品ID = %s 
                 AND 元件名称 = '壳体圆筒' 
                 AND Name = '圆筒内径'
           """, (product_id,))

    row = cursor.fetchone()
    yuantong_neijing3 = float(row["Value"]) if row else 0.0
    cursor.execute("""
               SELECT Value
               FROM 产品设计活动表_元件计算结果表
               WHERE 产品ID = %s 
                 AND 元件名称 = '壳程端部圆筒1' 
                 AND Name = '圆筒内径'
           """, (product_id,))

    row = cursor.fetchone()
    yuantong_neijing5 = float(row["Value"]) if row else " "
    cursor.execute("""
                               SELECT Value
                               FROM 产品设计活动表_元件计算结果表
                               WHERE 产品ID = %s 
                                 AND 元件名称 = '壳程端部圆筒2' 
                                 AND Name = '圆筒内径'
                           """, (product_id,))

    row = cursor.fetchone()
    yuantong_neijing6 = float(row["Value"]) if row else " "
    handle_label_dict["87bca"] = f"∅{yuantong_neijing2}"

    handle_label_dict["87bd2"] = f"∅{yuantong_neijing4}"

    handle_label_dict["87bce"] = f"∅{yuantong_neijing3}"
    handle_label_dict["816EC"] = f"∅{yuantong_neijing}"
    handle_label_dict["893e6"] = f"∅{yuantong_neijing5}"
    handle_label_dict["87bd0"] = f"∅{yuantong_neijing6}"
    if yuantong_neijing5 == " ":
        handle_label_dict["893e6"] = f"{yuantong_neijing5}"
    if yuantong_neijing6 == " ":
        handle_label_dict["87bd0"] = f"{yuantong_neijing6}"

    # === 查询管程和壳程公称直径 ===
    cursor.execute("""
                        SELECT 参数名称, 管程数值, 壳程数值
                        FROM 产品设计活动表_设计数据表
                        WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                    """, (product_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    # === 提取参数值并写入 handle_label_dict ===
    for row in rows:
        name = row.get("参数名称", "")
        gt_value = str(row.get("管程数值", "")).strip()
        kt_value = str(row.get("壳程数值", "")).strip()

    # === 从 JSON 中提取 鞍座 → 腹板 的值 ===
    fuban_val = 0.0
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "底板厚度":
            fuban_val = entry.get("Value", "")
            break

    handle_label_dict["779ED"] = fuban_val
    print(f"✅ 鞍座 → 腹板 → handle 779ED = {fuban_val}")
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "螺孔直径":
            fuban_val = entry.get("Value", "")
            break

    handle_label_dict["817F1"] = fuban_val
    # === 从 JSON 中提取 管箱圆筒 → 圆筒长度 的值
    guanxiang_length = 0.0
    for entry in data_by_module.get("管箱圆筒", []):
        if entry.get("Name") == "圆筒长度":
            guanxiang_length = entry.get("Value", "")
            break

    handle_label_dict["77995"] = guanxiang_length
    print(f"✅ 管箱圆筒 → 圆筒长度 → handle 77995 = {guanxiang_length}")
    # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
    nominal_thickness = 0.0
    for entry in data_by_module.get("固定管板", []):
        if entry.get("Name") == "管板名义厚度":
            nominal_thickness = entry.get("Value", "")
            break

    handle_label_dict["77C78"] = nominal_thickness
    print(f"✅ 固定管板 → 管板名义厚度 → handle 77C78 = {nominal_thickness}")
    # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
    nominal_thickness = 0.0
    for entry in data_by_module.get("浮头法兰", []):
        if entry.get("Name") == "球冠形封头名义厚度":
            nominal_thickness = entry.get("Value", "")
            break
    # min_thickness = 0.0
    # for entry in data_by_module.get("浮头法兰", []):
    #     if entry.get("Name") == "腐蚀前壳程球冠形封头有效厚度":
    #         min_thickness = entry.get("Value", "")
    #         break
    handle_label_dict["816C3"] = nominal_thickness
    print(f"✅ 球冠形封头 → handle 816C3 = {nominal_thickness}")
    # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
    nominal_thickness = 0.0
    for entry in data_by_module.get("外头盖封头", []):
        if entry.get("Name") == "椭圆形封头名义厚度":
            nominal_thickness = entry.get("Value", "")
            break
    thickness = 0.0
    for entry in data_by_module.get("外头盖封头", []):
        if entry.get("Name") == "椭圆形封头最小成型厚度":
            thickness = entry.get("Value", "")
            break
    waitougaiyuantonghoudu = 0.0
    for entry in data_by_module.get("外头盖圆筒", []):
        if entry.get("Name") == "圆筒名义厚度":
            waitougaiyuantonghoudu = entry.get("Value", "")
            break
    handle_label_dict["816ED"] = waitougaiyuantonghoudu
    handle_label_dict["815E1"] = f"{nominal_thickness}(min{thickness})"
    print(f"✅ 外头盖封头 → handle 815E1 = {nominal_thickness}")
    nominal_thickness = 0.0
    for entry in data_by_module.get("管箱封头", []):
        if entry.get("Name") == "椭圆形封头名义厚度":
            nominal_thickness = entry.get("Value", "")
            break
    yuantong_thickness = 0.0
    for entry in data_by_module.get("壳体圆筒", []):
        if entry.get("Name") == "圆筒名义厚度":
            yuantong_thickness = entry.get("Value", "")
            break
    yuantong_thickness1 = ' '
    for entry in data_by_module.get("壳程端部圆筒1", []):
        if entry.get("Name") == "圆筒名义厚度":
            yuantong_thickness1 = str(entry.get("Value", ""))
        else:
            yuantong_thickness1 = ""
            break
    yuantong_thickness2 = " "
    for entry in data_by_module.get("壳程端部圆筒2", []):
        if entry.get("Name") == "圆筒名义厚度":
            yuantong_thickness2 = str(entry.get("Value", ""))
        else:
            yuantong_thickness2 = ""

            break

    print(yuantong_thickness2, "yuantong_thickness2")
    thickness = 0.0
    for entry in data_by_module.get("管箱封头", []):
        if entry.get("Name") == "椭圆形封头最小成型厚度":
            thickness = entry.get("Value", "")
            break
    handle_label_dict["87bcf"] = yuantong_thickness
    handle_label_dict["893e7"] = yuantong_thickness1
    handle_label_dict["87bd1"] = yuantong_thickness2

    handle_label_dict["815E0"] = f"{nominal_thickness}(min{thickness})"
    print(f"✅ 外头盖封头 → handle 815E0 = {nominal_thickness}")
    conn, cursor = get_db_connection()
    tube_pass = 0.0
    shell_pass = 0.0
    cursor.execute("""
                        SELECT 参数值
                        FROM 产品设计活动表_布管参数表
                        WHERE 产品ID = %s AND 参数名 = '管程程数'
                        LIMIT 1
                    """, (product_id,))
    row = cursor.fetchone()
    if row:
        tube_pass = str(row["参数值"]).strip()
    cursor.execute("""
                                    SELECT 参数值
                                    FROM 产品设计活动表_布管参数表
                                    WHERE 产品ID = %s AND 参数名 = '壳程程数'
                                    LIMIT 1
                                """, (product_id,))
    row = cursor.fetchone()
    if row:
        shell_pass = str(row["参数值"]).strip()
    handle_label_dict["7786A"] = tube_pass
    handle_label_dict["77854"] = shell_pass
    # 按管口功能读取当前真实管口代号，替换图纸中的 N1/N2/L1 等固定标号。
    # 覆盖 DWG：NEN投标图-1.dwg、NEN投标图-1-无分段.dwg
    _nozzle_code_handle_to_function = {
        "87BB7": "壳程入口",
        "87BAE": "壳程出口",
        "87BA8": "排气口",
        "87BBD": "排液口",
        "87BB4": "管程入口",
        "87BB1": "管程出口",
    }
    _apply_nozzle_code_labels(handle_label_dict, product_id, _nozzle_code_handle_to_function)
    apply_dimension_labels(handle_label_dict)