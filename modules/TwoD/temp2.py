if product_type == "BEU" and (passes == "4" or passes == "6"):
    twoDgeneration_BEU_4(product_id)
    # extract_dimensions()
    handle_label_dict = {
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
        '8188F': '底座高度+500',
        '779ED': '管口和底座差值',
        "77995": '封头到管箱距离',
        "77C78": "管程连接厚度",
        "819E9": "支座高度"
    }
    # === 读取 JSON 文件 ===
    with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    saddle_height = None

    # === 遍历 DictOutData 中的支座条目 ===
    for item in data.get("DictOutData", {}).get("支座", []):
        if item.get("Id") == "m_Saddle_h":
            saddle_height = item.get("Value", "0")
            break
    handle_label_dict["819E9"] = saddle_height

    print(f"✅ 鞍式支座高度h: {saddle_height}")
    with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
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
        d1 = parse_axis_position(ports[0]["轴向定位距离"], ports[0]["管口所属元件"])
        d2 = parse_axis_position(ports[1]["轴向定位距离"], ports[1]["管口所属元件"])
        base_distance = abs(d1 - d2)
        extra = (get_val_by_id_and_name("固定管板", "工况1：TSH14", "管板名义厚度") -
                 2 * get_val_by_id_and_name("管箱法兰", "m_ThicknessGasket", "垫片厚度") -
                 2 * get_val_by_id_and_name("壳体法兰", "m_ThicknessGasket", "垫片厚度") -
                 2 * tutai_height +
                 get_val_by_id_and_name("管箱法兰", "工况1：FL155", "法兰总高") +
                 get_val_by_id_and_name("壳体法兰", "工况1：FL155", "法兰总高")
                 )
        handle_label_dict["81881"] = round(base_distance + extra, 3)
    else:
        handle_label_dict["81881"] = "[未找到2个管口]"

    for handle, label in handle_label_dict.items():
        if handle == "81886":
            total_length = (
                    get_val("壳体圆筒", "圆筒长度") +
                    get_val("管箱圆筒", "圆筒长度") +
                    get_val("管箱封头", "椭圆形封头有效厚度") +
                    get_val("管箱封头", "椭圆形封头外曲面深度") +
                    get_val("管箱圆筒", "与圆筒连接的椭圆形封头直边段长度") +
                    get_val("管箱法兰", "法兰有效厚度") +
                    get_val("管箱法兰", "垫片厚度") +
                    get_val("固定管板", "设计厚度") +
                    get_val("管箱法兰", "垫片厚度") +
                    get_val("管箱法兰", "法兰有效厚度") +
                    get_val("壳体封头", "椭圆形封头有效厚度") +
                    get_val("壳体封头", "椭圆形封头外曲面深度") +
                    get_val("壳体封头", "椭圆形封头直边高度")
            )
            handle_label_dict[handle] = round(total_length, 3)
            # 刷新消息队列，防止 COM 超时
            pythoncom.PumpWaitingMessages()

            # 短暂延时，让 AutoCAD 处理内部消息
            time.sleep(0.1)  # 50ms，可根据情况调整
        elif handle != "77991":
            found = False
            for module_name, entries in data_by_module.items():
                for entry in entries:
                    if entry.get("Name") == label:
                        handle_label_dict[handle] = entry.get("Value", "")
                        found = True
                        break
                if found:
                    break

    cursor.execute("""
            SELECT Value
            FROM 产品设计活动表_元件计算结果表
            WHERE 产品ID = %s 
              AND 元件名称 = '管程入口接管' 
              AND Name = '开孔元件外径'
        """, (product_id,))
    row = cursor.fetchone()
    cylinder_inner_diameter1 = float(row["Value"]) / 2 if row else 0.0
    cursor.execute("""
            SELECT Value
            FROM 产品设计活动表_元件计算结果表
            WHERE 产品ID = %s 
              AND 元件名称 = '管程出口接管' 
              AND Name = '开孔元件外径'
        """, (product_id,))
    row = cursor.fetchone()
    cylinder_inner_diameter2 = float(row["Value"]) / 2 if row else 0.0
    # === 查询数据库：N2 和 N4 的 外伸高度
    cursor.execute("""
                        SELECT 元件名称, value
                        FROM 产品设计活动表_元件计算结果表
                        WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管') AND Name = '接管实际外伸长度'
                    """, (product_id,))
    rows = cursor.fetchall()
    # 构建管口代号 → 外伸高度 映射
    out_len_map = {
        row["元件名称"]: str(row.get("value", "")).strip()
        for row in rows if row.get("元件名称")
    }

    # === N2 → handle 779E6
    n2_len = out_len_map.get("管程入口接管", "")

    import pymysql

    middle_value = None
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
                    WHERE 产品ID = %s AND 管口功能 IN ('管程入口', '管程出口')
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
    cur2.execute("SELECT * FROM 管法兰质量表")
    flange_rows = cur2.fetchall()

    # === 5. 匹配逻辑 ===

    gaodu3 = None  # 排液口
    gaodu4 = None  # 排气口
    for port in ports:
        code = port["管口代号"]
        func = port["管口功能"]  # 排气口 or
        # 排液口
        std = port["法兰标准"]
        size = str(port["公称尺寸"]).strip()
        pressure = str(port["压力等级"]).strip()

        # --- 公称尺寸处理 ---
        if size_type.upper() == "NPS":
            size = nps_map.get(size, size)  # NPS → DN

        # --- 遍历管法兰质量表匹配 ---
        for row in flange_rows:
            # 标准匹配（包含关系）
            if std and row["标准"] not in std:
                continue
            # 公称尺寸匹配（DN）
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
            flange_type = port["法兰型式"]
            if flange_type and str(row["法兰型式代号"]).strip() != str(flange_type).strip():
                continue

            # ✅ 只取 H+密封面型式 对应的值
            face_type = port["密封面型式"]
            face_col = f"H{face_type}" if face_type else None
            if face_col and face_col in row:
                val = row[face_col]

                if func == "管程入口":
                    gaodu3 = val
                elif func == "管程出口":
                    gaodu4 = val
            break  # 找到一个匹配项就退出

    middle_value = str(float(n2_len) + float(cylinder_inner_diameter1) + float(gaodu3))

    handle_label_dict["8188E"] = f"{middle_value}±3"
    print(f"✅ 管口 N2 → 外伸高度 → handle 8188E = {n2_len}")

    # === N4 → handle 779EA
    n4_len = out_len_map.get("管程出口接管", "")
    if n4_len == "默认":
        n4_len = "600"
    middle_value2 = float(n4_len) + float(cylinder_inner_diameter2) + float(gaodu4)
    handle_label_dict["81890"] = f"{middle_value2}±3"
    print(f"✅ 管口 N4 → 外伸高度 → handle 81890 = {n4_len}")

    # === 从 JSON 中读取鞍式支座高度h ===
    support_height = 0
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "鞍式支座高度h":
            try:
                support_height = float(entry.get("Value", 0))
            except:
                support_height = 0
            break

    # === 从数据库中查公称直径（注意：名称可能为“公称直径DN”或类似） ===
    conn = pymysql.connect(
        host="localhost",
        user="root",
        password="123456",
        database="产品设计活动库",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )
    cursor = conn.cursor()
    cursor.execute("""
                    SELECT 管程数值 
                    FROM 产品设计活动表_设计数据表
                    WHERE 产品ID = %s AND 参数名称 = '公称直径*'
                    LIMIT 1
                """, (product_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    nominal_diameter = 0
    if row and row.get("管程数值"):
        try:
            nominal_diameter = float(row["管程数值"])
        except:
            nominal_diameter = 0

    # === 计算最终高度：鞍式支座高度h + 公称直径/2
    handle_label_dict["8188F"] = round(support_height + nominal_diameter / 2, 3)
    print(f"✅ 8188F → {support_height} + {nominal_diameter / 2} = {handle_label_dict['8188F']}")
    # === 从 JSON 中读取鞍式支座高度h ===
    support_height = 0
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "鞍式支座高度h":
            try:
                support_height = float(entry.get("Value", 0))
            except:
                support_height = 0
            break
    handle_label_dict["819E9"] = support_height
    l1_val = None
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "底板长度":
            l1_val = entry.get("Value", "")
            break

    # === 更新两个 handle 对应的值
    handle_label_dict["81888"] = float(l1_val) - 10
    handle_label_dict["81592"] = float(l1_val) - 10
    handle_label_dict["81596"] = l1_val

    fuban_val = None
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "螺孔直径":
            fuban_val = entry.get("Value", "")
            break

    handle_label_dict["81593"] = fuban_val
    handle_label_dict["815C3"] = f"2-{fuban_val}"
    l9_val = None
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "G":
            l9_val = entry.get("Value", "")
            break

    # === 更新两个 handle 对应的值
    handle_label_dict["81881"] = l9_val
    # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
    l2_val = None
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "螺栓孔间距1":
            l2_val = entry.get("Value", "")
            break
    # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
    l6_val = None
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "H":
            l6_val = entry.get("Value", "")
            break
    # === 更新两个 handle 对应的值
    handle_label_dict["81882"] = l6_val
    # === 更新两个 handle 对应的值
    handle_label_dict["81595"] = f"{l2_val}±2"
    handle_label_dict["81887"] = f"{l2_val}±2"
    handle_label_dict["816FD"] = l2_val
    b5_val = None
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "D":
            b5_val = entry.get("Value", "")
            break
    handle_label_dict["81883"] = b5_val
    handle_label_dict["81592"] = b5_val
    print(f"✅ 间距l2 → handle 817F0, 815CE = {l2_val}")
    # === 更新两个 handle 对应的值
    b1_val = None
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "底板宽度":
            b1_val = entry.get("Value", "")
            break
    handle_label_dict["815C1"] = int(b1_val) / 2
    handle_label_dict["815C2"] = int(b1_val) / 2
    # === 更新两个 handle 对应的值
    handle_label_dict["8158E"] = int(b1_val)
    print(int(b1_val))
    handle_label_dict["8158F"] = int(b1_val)
    # === 从 JSON 中提取 鞍座 → l3 的值 ===
    l3_val = None
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "筋板长度":
            l3_val = entry.get("Value", "")
            break

    handle_label_dict["817F3"] = str(l3_val) + "±2"

    print(f"✅ l3 → handle 77992 = {l3_val}")
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "螺孔长度":
            b1_val = entry.get("Value", "")
            break
    # === 更新两个 handle 对应的值
    handle_label_dict["81594"] = b1_val
    print("b1_val", b1_val)

    print(f"✅ 间距l2 → handle 77993, 77C15 = {l2_val}")
    # === 从 JSON 中提取 鞍座 → l3 的值 ===
    l3_val = None
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "筋板长度":
            l3_val = entry.get("Value", "")
            break

    handle_label_dict["77992"] = l3_val
    print(f"✅ l3 → handle 77992 = {l3_val}")
    gp_exit_val = None
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
    shell_exit_val = None
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
        "818BB": "管程入口接管",
        "81A03": "管程出口接管",
        "81905": "壳程入口接管",
        "819E5": "壳程出口接管"
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
                value = f"∅{od}×{thick};L={l1 + l2}"
            else:
                value = None
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

        if gt_value:
            handle_label_dict["81889"] = gt_value
            print(f"✅ 管程公称直径 → handle 81889 = {gt_value}")
        if kt_value:
            handle_label_dict["8188B"] = kt_value
            print(f"✅ 壳程公称直径 → handle 8188B = {kt_value}")

    # === 从 JSON 中提取 鞍座 → 腹板 的值 ===
    fuban_val = None
    for entry in data_by_module.get("鞍座", []):
        if entry.get("Name") == "底板厚度":
            fuban_val = entry.get("Value", "")
            break

    handle_label_dict["779ED"] = fuban_val
    print(f"✅ 鞍座 → 腹板 → handle 779ED = {fuban_val}")
    # === 从 JSON 中提取 管箱圆筒 → 圆筒长度 的值
    guanxiang_length = None
    for entry in data_by_module.get("管箱圆筒", []):
        if entry.get("Name") == "圆筒长度":
            guanxiang_length = entry.get("Value", "")
            break

    handle_label_dict["77995"] = guanxiang_length
    print(f"✅ 管箱圆筒 → 圆筒长度 → handle 77995 = {guanxiang_length}")
    # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
    nominal_thickness = None
    for entry in data_by_module.get("固定管板", []):
        if entry.get("Name") == "管板名义厚度":
            nominal_thickness = entry.get("Value", "")
            break

    handle_label_dict["77C78"] = nominal_thickness
    print(f"✅ 固定管板 → 管板名义厚度 → handle 77C78 = {nominal_thickness}")
    conn, cursor = get_db_connection()
    tube_pass = None
    shell_pass = None
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
    apply_dimension_labels(handle_label_dict)
    generate_and_save_flange(product_id, flange_info)
