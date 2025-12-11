for row in sheet.iter_rows(min_row=2):
    name = str(row[3].value).strip()
    print("name:", name)

    # === 1. 数量 ===
    if name in quantity_map:
        row[6].value = quantity_map[name]

    # === 2. 特殊件质量计算 ===
    if name == "滑道":
        if slipway_mass:
            row[7].value = slipway_mass

    elif name == "拉杆":
        # 数量
        row[6].value = tie_list

        # 直径
        dh_str = get_value(jisuan_data, "管箱法兰", "螺栓公称直径")
        match = re.search(r"M(\d+)", str(dh_str)) if dh_str else None
        dh_val = int(match.group(1)) if match else None
        R = dh_val / 2 if dh_val else None

        # 长度
        dict_out = jisuan_data.get("DictOutDatas", {})
        datas = dict_out.get("管束", {}).get("Datas", []) \
             or dict_out.get("浮头管束", {}).get("Datas", [])
        H1 = get_param(datas, "拉杆长度1")
        H2 = get_param(datas, "拉杆长度2")
        H = max(H1, H2)

        # 密度
        density = get_material_density("拉杆", product_id)

        # 质量
        if R and H and density:
            R_m = R / 1000
            H_m = float(H) / 1000
            mass = round((math.pi * R_m**2 / 4) * H_m * density * 1000, 2)
            row[7].value = mass

    elif name == "螺母（拉杆）":
        row[6].value = quantity_map.get("螺母（拉杆）", 0)
        dia = get_value(jisuan_data, "管箱法兰", "螺栓公称直径")
        if dia:
            try:
                conn3 = pymysql.connect(
                    host="localhost", user="root", password="123456",
                    database="材料库", charset="utf8mb4",
                    cursorclass=pymysql.cursors.DictCursor
                )
                with conn3.cursor() as cursor:
                    cursor.execute("""
                        SELECT `管法兰专用螺母`
                        FROM `螺母近似质量表`
                        WHERE 规格 = %s
                        LIMIT 1
                    """, (str(dia),))
                    row_m = cursor.fetchone()
                    if row_m and row_m.get("管法兰专用螺母"):
                        row[7].value = float(row_m["管法兰专用螺母"])
                conn3.close()
            except Exception as e:
                print("❌ 查询螺母质量失败:", e)

    elif name == "定距管":
        uhx_data = jisuan_data.get("DictOutDatas", {}).get("固定管板", {}).get("Datas", [])
        uhx_mass = get_param(uhx_data, "单根换热管重量kg")
        row[7].value = float(uhx_mass) if uhx_mass not in (None, "", "None") else None

    elif name == "铭牌板":
        row[7].value = 0.8

    elif name == "铭牌支架":
        row[7].value = 1

    elif name in {"管箱吊耳", "吊耳", "管箱垫片", "管箱侧垫片", "外头盖侧垫片", "外头盖垫片"}:
        row[7].value = "/"

    elif name == "U形换热管":
        uhx_data = jisuan_data.get("DictOutDatas", {}).get("固定管板", {}).get("Datas", [])
        uhx_mass = get_param(uhx_data, "单根换热管重量kg")
        row[7].value = float(uhx_mass) if uhx_mass not in (None, "", "None") else None

    elif name == "旁路挡板":
        # 你已有的 bpb_list + BPBThick 逻辑
        bpb_list = pipe_data.get("BPBs", [])
        heights = pipe_data.get("BPBThick", [])

        # 确保 bpb_list 是 list
        if isinstance(bpb_list, str):
            try:
                # 先尝试 JSON
                bpb_list = json.loads(bpb_list)
            except json.JSONDecodeError:
                # 如果不是 JSON，就尝试 eval 成 Python list
                bpb_list = ast.literal_eval(bpb_list)

        if not isinstance(bpb_list, list):
            bpb_list = []

        row[6].value = len(bpb_list)

        try:
            # 获取长度
            H1 = get_param(jisuan_data.get("DictOutDatas", {}).get("管束", {}).get("Datas", []), "拉杆长度1")
            H2 = get_param(jisuan_data.get("DictOutDatas", {}).get("管束", {}).get("Datas", []), "拉杆长度2")
            length_m = max(float(H1 or 0), float(H2 or 0)) / 1000  # 转换成 float 后再除1000

            # 获取密度
            density = get_material_density("旁路挡板", product_id)  # kg/m³

            # 显示第一个挡板质量
            if bpb_list and heights:
                thickness_mm = float(heights[0])
                width_mm = float(width_mm)
                volume = (thickness_mm / 1000) * (width_mm / 1000) * length_m
                mass = volume * density
                row[7].value = round(mass, 2)
        except Exception as e:
            print(f"❌ 计算旁路挡板质量失败: {e}")


    elif name == "内折流板":

        try:

            datas = jisuan_data.get("DictOutDatas", {}).get("浮头管束", {}).get("Datas", [])

            n_fixed = get_param(datas, "固定管板侧内折流板数量") or 0

            n_float = get_param(datas, "浮动管板侧内折流板数量") or 0

            row[6].value = int(n_fixed) + int(n_float)

        except Exception as e:

            print(f"❌ 计算内折流板数量失败: {e}")

    elif name == "弓形折流板":

        try:

            datas = jisuan_data.get("DictOutDatas", {}).get("浮头管束", {}).get("Datas", [])

            n_fixed = get_param(datas, "弓形折流板数量") or 0

            row[6].value = int(n_fixed)

        except Exception as e:

            print(f"❌ 计算弓形折流板数量失败: {e}")

    elif name == "异形折流板":

        try:

            datas = jisuan_data.get("DictOutDatas", {}).get("浮头管束", {}).get("Datas", [])

            n_fixed = get_param(datas, "异形折流板数量") or 0

            row[6].value = int(n_fixed)

        except Exception as e:

            print(f"❌ 计算异形折流板数量失败: {e}")

    elif name == "内导流筒":

        try:

            datas = jisuan_data.get("DictOutDatas", {}).get("浮头管束", {}).get("Datas", [])

            n_fixed = get_param(datas, "导流筒数量") or 0

            row[6].value = int(n_fixed)

        except Exception as e:

            print(f"❌ 计算导流筒数量失败: {e}")

    elif name == "中间挡板":

        vbaffles = pipe_data.get("VerticalBaffle", [])

        qty = len(vbaffles)

        row[6].value = qty

        try:

            # === 获取厚度和宽度（取第一个挡板）

            if vbaffles:

                thickness_mm = float(vbaffles[0].get("Width", 0))  # mm

                width_mm = float(vbaffles[0].get("Height", 0))  # mm

            else:

                thickness_mm = width_mm = 0

            # === 获取长度（来自 jisuan_data）

            mid_baffle_length = get_param(

                jisuan_data.get("DictOutDatas", {}).get("管束", {}).get("Datas", []),

                "中间挡管/挡板长度"

            )

            length_m = float(mid_baffle_length) / 1000 if mid_baffle_length else 0

            # === 获取密度

            density = get_material_density("中间挡板", product_id)  # kg/m³

            # === 计算质量

            volume = (thickness_mm / 1000) * (width_mm / 1000) * length_m  # m³

            total_mass = volume * density * qty * 1000

            row[7].value = round(total_mass, 2)

        except Exception as e:

            print(f"❌ 计算中间挡板质量失败: {e}")





    elif name == "螺柱（管箱法兰）" and luozhu_qty:

        row[6].value = luozhu_qty

        dh = get_value(jisuan_data, "管箱法兰", "螺栓公称直径")

        R = get_actual_diameter(dh)

        H = get_luozhu_length(jisuan_data, product_id)

        density = get_material_density("螺柱（管箱法兰）", product_id)

        print("R", R)

        print("H", H)

        print("density", density)

        if R and H and density:
            mass_luozhu = round((math.pi * (R / 1000) ** 2 / 4) * (H / 1000) * density * 1000, 2)

            row[7].value = mass_luozhu


    elif name == "螺柱（浮头法兰）":

        dh = get_value(jisuan_data, "管箱法兰", "螺栓公称直径")

        R = get_actual_diameter(dh)

        H = get_luozhu_length(jisuan_data, product_id)

        density = get_material_density("螺柱（浮头法兰）", product_id)

        print("R", R)

        print("H", H)

        print("density", density)

        if R and H and density:
            mass_luozhu = round((math.pi * (R / 1000) ** 2 / 4) * (H / 1000) * density * 1000, 2)

            row[7].value = mass_luozhu

    elif name == "螺母（浮头法兰）" and luozhu_qty3:

        row[6].value = luozhu_qty3 * 2

        # === 获取公称直径，查找质量 ===

        dia = get_value(jisuan_data, "浮头法兰", "螺栓公称直径")

        if dia:

            try:

                conn3 = pymysql.connect(

                    host="localhost", user="root", password="123456",

                    database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

                )

                with conn3.cursor() as cursor:

                    cursor.execute("""

                        SELECT `管法兰专用螺母` 

                        FROM `螺母近似质量表`

                        WHERE 规格 = %s

                        LIMIT 1

                    """, (str(dia),))

                    row_m = cursor.fetchone()

                    if row_m and row_m.get("管法兰专用螺母"):
                        mass_per_unit = float(row_m["管法兰专用螺母"])

                        row[7].value = mass_per_unit

                conn3.close()

            except Exception as e:

                print(f"❌ 查询螺母质量失败: {e}")

    elif name == "螺母（管箱法兰）" and luozhu_qty:

        row[6].value = luozhu_qty * 2

        # === 获取公称直径，查找质量 ===

        dia = get_value(jisuan_data, "管箱法兰", "螺栓公称直径")

        if dia:

            try:

                conn3 = pymysql.connect(

                    host="localhost", user="root", password="123456",

                    database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

                )

                with conn3.cursor() as cursor:

                    cursor.execute("""

                        SELECT `管法兰专用螺母` 

                        FROM `螺母近似质量表`

                        WHERE 规格 = %s

                        LIMIT 1

                    """, (str(dia),))

                    row_m = cursor.fetchone()

                    if row_m and row_m.get("管法兰专用螺母"):
                        mass_per_unit = float(row_m["管法兰专用螺母"])

                        row[7].value = mass_per_unit

                conn3.close()

            except Exception as e:

                print(f"❌ 查询螺母质量失败: {e}")

    elif name == "螺母（管箱法兰）" and luozhu_qty:

        row[6].value = luozhu_qty * 2

        # === 获取公称直径，查找质量 ===

        dia = get_value(jisuan_data, "管箱法兰", "螺栓公称直径")

        if dia:

            try:

                conn3 = pymysql.connect(

                    host="localhost", user="root", password="123456",

                    database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

                )

                with conn3.cursor() as cursor:

                    cursor.execute("""

                        SELECT `管法兰专用螺母` 

                        FROM `螺母近似质量表`

                        WHERE 规格 = %s

                        LIMIT 1

                    """, (str(dia),))

                    row_m = cursor.fetchone()

                    if row_m and row_m.get("管法兰专用螺母"):
                        mass_per_unit = float(row_m["管法兰专用螺母"])

                        row[7].value = mass_per_unit

                conn3.close()

            except Exception as e:

                print(f"❌ 查询螺母质量失败: {e}")

    elif name == "螺柱（管箱平盖）" and luozhu_qty2:

        row[6].value = luozhu_qty2

        dh = get_value(jisuan_data, "管箱法兰", "螺栓公称直径")

        R = get_actual_diameter(dh)

        H = get_luozhu_length(jisuan_data, product_id)

        density = get_material_density("螺柱（管箱平盖）", product_id)

        print("R", R)

        print("H", H)

        print("density", density)

        if R and H and density:
            mass_luozhu = round((math.pi * (R / 1000) ** 2 / 4) * (H / 1000) * density * 1000, 2)

            row[7].value = mass_luozhu




    elif name == "螺母（管箱平盖）" and luozhu_qty2:

        row[6].value = luozhu_qty2 * 2

        # === 获取公称直径，查找质量 ===

        dia = get_value(jisuan_data, "管箱法兰", "螺栓公称直径")

        if dia:

            try:

                conn3 = pymysql.connect(

                    host="localhost", user="root", password="123456",

                    database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

                )

                with conn3.cursor() as cursor:

                    cursor.execute("""

                        SELECT `管法兰专用螺母` 

                        FROM `螺母近似质量表`

                        WHERE 规格 = %s

                        LIMIT 1

                    """, (str(dia),))

                    row_m = cursor.fetchone()

                    if row_m and row_m.get("管法兰专用螺母"):
                        mass_per_unit = float(row_m["管法兰专用螺母"])

                        row[7].value = mass_per_unit

                conn3.close()

            except Exception as e:

                print(f"❌ 查询螺母质量失败: {e}")

    elif name == "折流板" and baffle_R and baffle_t:

        density_zheliuban = get_material_density("折流板", product_id)

        row[7].value = calc_weight(baffle_R, baffle_t, density_zheliuban)

    # elif name == "防冲板":

    elif name == "支持板":

        if not row[6].value:
            row[6].value = 1

        if support_R and support_t:
            density_zhichiban = get_material_density("支持板", product_id)

            row[7].value = calc_weight(support_R, support_t, density_zhichiban)

    elif name == "挡管":

        # 获取挡管数量

        dummy_tubes = pipe_data.get("dummy_tubes", [])

        if isinstance(dummy_tubes, str):
            dummy_tubes = ast.literal_eval(dummy_tubes)

        dummy_count = len(dummy_tubes)

        print(dummy_tubes)

        print(dummy_count)

        row[6].value = dummy_count

        uhx_data = jisuan_data.get("DictOutDatas", {}).get("固定管板", {}).get("Datas", [])

        uhx_mass = get_param(uhx_data, "单根换热管重量kg")

        uhx_mass = float(uhx_mass) if uhx_mass not in (None, "", "None") else None

        row[7].value = uhx_mass

    elif name == "换热管":

        uhx_data = jisuan_data.get("DictOutDatas", {}).get("固定管板", {}).get("Datas", [])

        uhx_mass = get_param(uhx_data, "单根换热管重量kg")

        uhx_mass = float(uhx_mass) if uhx_mass not in (None, "", "None") else None

        row[7].value = uhx_mass

    elif name == "浮动管板":

        uhx_data = jisuan_data.get("DictOutDatas", {}).get("固定管板", {}).get("Datas", [])

        uhx_mass = get_param(uhx_data, "单根换热管重量kg")

        uhx_mass = float(uhx_mass) if uhx_mass not in (None, "", "None") else None

        row[7].value = uhx_mass

    elif name == "铭牌板":

        uhx_mass = 0.8

        row[7].value = uhx_mass

    elif name == "铭牌支架":

        uhx_mass = 1

        row[7].value = uhx_mass

    elif name == "管箱吊耳":

        uhx_mass = "/"

        row[7].value = uhx_mass

    elif name == "吊耳":

        uhx_mass = "/"

        row[7].value = uhx_mass

    elif name == "管箱垫片":

        uhx_mass = "/"

        row[7].value = uhx_mass

    elif name == "管箱侧垫片":

        uhx_mass = "/"

        row[7].value = uhx_mass

    elif name == "外头盖侧垫片":

        uhx_mass = "/"

        row[7].value = uhx_mass

    elif name == "外头盖垫片":

        uhx_mass = "/"

        row[7].value = uhx_mass

    elif name == "防松支耳":

        print(11111111111111111111111111111111111111111)

        # === 获取防松支耳数量配置 ===

        qty = None

        dn_value = None

        conn1 = pymysql.connect(

            host="localhost", user="root", password="123456",

            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

        )

        with conn1.cursor() as cursor:

            cursor.execute("""

                                               SELECT 管程数值 FROM 产品设计活动表_设计数据表

                                               WHERE 产品ID = %s AND 参数名称 = '公称直径*' LIMIT 1

                                           """, (product_id,))

            roww = cursor.fetchone()

            if roww and roww.get("管程数值"):
                dn_value = float(roww["管程数值"])

        if dn_value:

            try:

                conn2 = pymysql.connect(

                    host="localhost", user="root", password="123456",

                    database="配置库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

                )

                with conn2.cursor() as cursor:

                    cursor.execute("SELECT value FROM user_config WHERE id = 2.16")

                    roww = cursor.fetchone()

                    print(dn_value, "dn_value")

                    if roww:

                        config = eval(roww["value"])

                        values = config[1][1:]

                        if dn_value < 800:

                            qty = values[0]

                        elif 800 <= dn_value <= 2000:

                            qty = values[1]

                        else:

                            qty = values[2]

                conn2.close()

            except:

                pass

        row[6].value = qty

        uhx_mass = "/"

        row[7].value = uhx_mass

    elif name == "顶板":

        uhx_mass = 0.5

        row[7].value = uhx_mass

    elif name in {"固定鞍座", "滑动鞍座"}:

        if not row[6].value:
            row[6].value = 1

        if saddle_mass:
            row[7].value = saddle_mass



    elif name == "带肩螺柱":

        dn_value = None

        conn1 = pymysql.connect(

            host="localhost", user="root", password="123456",

            database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

        )

        with conn1.cursor() as cursor:

            cursor.execute("""

                        SELECT 管程数值 FROM 产品设计活动表_设计数据表

                        WHERE 产品ID = %s AND 参数名称 = '公称直径*' LIMIT 1

                    """, (product_id,))

            roww = cursor.fetchone()

            if roww and roww.get("管程数值"):
                dn_value = float(roww["管程数值"])

        # === 获取防松支耳数量配置 ===

        qty = None

        if dn_value:

            try:

                conn2 = pymysql.connect(

                    host="localhost", user="root", password="123456",

                    database="配置库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor

                )

                with conn2.cursor() as cursor:

                    cursor.execute("SELECT value FROM user_config WHERE id = 2.16")

                    roww = cursor.fetchone()

                    if roww:

                        config = eval(roww["value"])

                        values = config[1][1:]

                        if dn_value < 800:

                            qty = values[0]

                        elif 800 <= dn_value <= 2000:

                            qty = values[1]

                        else:

                            qty = values[2]

                conn2.close()

            except:

                pass

        row[6].value = qty

        row[7].value = mass_luozhu
    # === 3. 固定映射兜底 ===
    elif name in mass_map:
        row[7].value = mass_map[name]
        if name in quantity_map:
            row[6].value = quantity_map[name]
