    zhuiqiao = {
        "公称直径": "1500",
        "液柱静压力": "1",
        "用户自定义MAWP": "0",
        "耐压试验温度": "140",
        "耐压试验压力": "1",
        "锥壳半顶角": "0",
        "锥壳大端直边段内直径": "1500",
        "锥壳小端直边段内直径": "1000",
        "材料类型": "钢板",
        "材料牌号": "Q345R",
        "腐蚀裕量": "0",
        "焊接接头系数": "1",
        "压力试验类型": "液压",
        "锥壳名义厚度": "0",
        "大端圆筒名义厚度": "0",
        "小端圆筒名义厚度": "0",
        "大端锥壳加强段所需名义厚度": "0",
        "大端圆筒加强段所需名义厚度": "0",
        "小端锥壳加强段所需名义厚度": "0",
        "小端圆筒加强段所需名义厚度": "0",
        "锥壳及大小端圆筒是否覆层": "否",
        "锥壳及大小端圆筒覆层厚度": "0",
        "锥壳及大小端圆筒带覆层时的焊接凹槽深度": "0",
        "覆层材料类型": "钢板",
        "锥壳大端是否带折边": "否",
        "锥壳小端是否带折边": "否",
        "折边锥壳大端过渡段转角半径": "0",
        "折边锥壳小端过渡段转角半径": "0",
        "由外载荷在锥壳大端产生的单位圆周长度上轴向力": "0",
        "由外载荷在锥壳小端产生的单位圆周长度上轴向力": "0",
        "锥壳小端是否连接法兰或平盖等结构件": "否",
        "是否需要锥壳与大端连接处作为支撑线": "是",
        "是否需要锥壳与小端连接处作为支撑线": "是",
        "锥壳大端是否有加强圈": "加强圈在锥壳+圆筒",
        "锥壳小端是否有加强圈": "加强圈在锥壳+圆筒",
        "锥壳大端加强圈材料类型": "钢板",
        "锥壳大端加强圈材料牌号": "Q345R",
        "锥壳大端加强圈型钢类型": "T型钢",
        "锥壳大端加强圈两侧计算长度之和的一半": "0",
        "锥壳大端圆筒加强圈材料类型": "钢板",
        "锥壳大端圆筒加强圈材料牌号": "Q345R",
        "锥壳大端圆筒加强圈型钢类型": "T型钢",
        "锥壳大端圆筒加强圈两侧计算长度之和的一半": "0",
        "锥壳小端加强圈材料类型": "钢板",
        "锥壳小端加强圈材料牌号": "Q345R",
        "锥壳小端加强圈型钢类型": "T型钢",
        "锥壳小端加强圈两侧计算长度之和的一半": "0",
        "锥壳小端圆筒加强圈材料类型": "钢板",
        "锥壳小端圆筒加强圈材料牌号": "Q345R",
        "锥壳小端圆筒加强圈型钢类型": "T型钢",
        "锥壳小端圆筒加强圈两侧计算长度之和的一半": "0",
        "锥壳大端加强圈有效截面积": "0",
        "锥壳小端加强圈有效截面积": "0",
        "锥壳大端圆筒加强圈有效截面积": "0",
        "锥壳小端圆筒加强圈有效截面积": "0",
        "与锥壳大端连接的圆筒材料类型": "",
        "与锥壳大端连接的圆筒材料牌号": "",
        "与锥壳大端连接的圆筒焊接接头系数": "1",
        "与锥壳大端连接的圆筒腐蚀裕量": "0",
        "与锥壳小端连接的圆筒材料类型": "钢板",
        "与锥壳小端连接的圆筒材料牌号": "Q345R",
        "与锥壳小端连接的圆筒焊接接头系数": "1",
        "与锥壳小端连接的圆筒腐蚀裕量": "0",
        "LS1": "0",
        "LS2": "0",
        "HS": "0",
        "BTS": "0",
        "STOP": "0",
        "BSL1": "0",
        "BSL2": "0",
        "HC": "0",
        "BTC": "0",
        "CTOP": "0",
        "BCL1": "0",
        "BCL2": "0",
        "LL": "0",
        "LLM": "0",
        "TC2": "0",
        "AS": "0",
        "ATS": "0",
        "XTOP": "0",
        "ASL1": "0",
        "ASL2": "0",
        "AC": "0",
        "ATC": "0",
        "ATOP": "0",
        "ACL1": "0",
        "ACL2": "0",
        "LX": "0",
        "LXM": "0",
    }

    cursor.execute("""
        SELECT 参数名称, 壳程数值, 管程数值
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s
    """, (product_id,))
    rows = cursor.fetchall()

    # === 构建参数映射表 ===
    param_map = {row["参数名称"].strip(): row for row in rows}

    map3 = {
        "液柱静压力": "液柱静压力",
        "用户自定义MAWP": "最高允许工作压力",
        "腐蚀裕量": "腐蚀裕量*",
        "焊接接头系数": "焊接接头系数*",
        "公称直径": "公称直径*",
        "锥壳大端直边段内直径":"公称直径*",
        "与锥壳大端连接的圆筒焊接接头系数":"焊接接头系数*",
        "与锥壳大端连接的圆筒腐蚀裕量": "腐蚀裕量*",
    }

    for key, param_name in map3.items():
        value = param_map.get(param_name, {}).get("壳程数值", "")
        if value != "":
            zhuiqiao[key] = str(value)
    val1 = parse_float(param_map.get("自定义耐压试验压力（卧）", {}).get("壳程数值", ""))
    val2 = parse_float(param_map.get("自定义耐压试验压力（立）", {}).get("壳程数值", ""))

    # === 最大允许工作压力（管程数值） ===
    value = param_map.get("最大允许工作压力", {}).get("壳程数值")
    if value not in [None, ""]:
        zhuiqiao["最大允许工作压力"] = str(value)

    # === 耐压试验压力：取最大值 ===
    if val1 is not None and val2 is not None:
        zhuiqiao["耐压试验压力"] = str(max(val1, val2))
    elif val1 is not None:
        zhuiqiao["耐压试验压力"] = str(val1)
    elif val2 is not None:
        zhuiqiao["耐压试验压力"] = str(val2)
    else:
        zhuiqiao["耐压试验压力"] = "0"
    cursor.execute("""
            SELECT 参数名称, 壳程数值, 管程数值
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s
        """, (product_id,))
    rows = cursor.fetchall()
    param_map = {row["参数名称"].strip(): row for row in rows}

    # 公称直径（管程）
    if "公称直径*" in param_map:
        zhuiqiao["锥壳小端直边段内直径"] = str(param_map["公称直径*"].get("管程数值", ""))
        zhuiqiao["与锥壳小端连接的圆筒焊接接头系数"] = str(param_map["焊接接头系数*"].get("管程数值", ""))
        zhuiqiao["与锥壳小端连接的圆筒腐蚀裕量"] = str(param_map["腐蚀裕量*"].get("管程数值", ""))

    if "耐压试验类型*" in param_map:
        val = param_map["耐压试验类型*"].get("壳程数值", "")
        if val:
            clean_val = str(val).replace("试验", "").strip()
            zhuiqiao["压力试验类型"] = clean_val
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '锥壳'
        """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    zhuiqiao["材料类型"] = row_map.get("材料类型", "0")
    zhuiqiao["材料牌号"] = row_map.get("材料牌号", "0")
    cursor.execute("""
           SELECT 参数名称, 参数值 
           FROM 产品设计活动表_元件附加参数表
           WHERE 产品ID = %s AND 元件名称 = '锥壳'
       """, (product_id,))
    extra_rows = cursor.fetchall()
    extra_map = {row["参数名称"].strip(): row["参数值"] for row in extra_rows}

    # 是否添加覆层
    if extra_map.get("是否添加覆层") == "是":
        zhuiqiao["是否覆层"] = "1"
        zhuiqiao["覆层材料类型"] = extra_map.get("覆层材料类型", "")  # 若为空可改为 "未知"

        zhuiqiao["覆层复合方式"] = extra_map.get("覆层成型工艺", "轧制复合")  # 若为空可改为 "未知"
        zhuiqiao["圆筒覆层厚度"] = str(extra_map.get("覆层厚度", "0"))
    else:
        zhuiqiao["是否覆层"] = "0"
        zhuiqiao["覆层材料类型"] = "钢板"

        zhuiqiao["覆层复合方式"] = "无"
        zhuiqiao["圆筒覆层厚度"] = "0"
    # =========================
    # 锥壳小端是否连接法兰或平盖等结构件
    # 条件：
    # a = 产品设计活动表_设计数据表 中 “公称直径” 的管程数值
    # b = 产品设计活动表_设计数据表 中 “设计压力” 的管程数值
    # c = 产品设计活动表_设计数据表 中 “设计温度” 的管程数值
    # 当 a <= 2.18.5.1 且 b <= 2.18.5.2 且 c <= 2.18.5.3 时，为“是”，否则为“否”
    # =========================

    # 兼容参数名称带 * 和不带 * 的情况
    a = parse_float(
        param_map.get("公称直径", {}).get("管程数值", "") or
        param_map.get("公称直径*", {}).get("管程数值", "")
    )
    b = parse_float(
        param_map.get("设计压力", {}).get("管程数值", "") or
        param_map.get("设计压力*", {}).get("管程数值", "")
    )
    c = parse_float(
        param_map.get("设计温度", {}).get("管程数值", "") or
        param_map.get("设计温度*", {}).get("管程数值", "")
    )

    cursor.execute("""
    SELECT id, value
    FROM 配置库.user_config
    WHERE id IN ('2.18.5.1', '2.18.5.2', '2.18.5.3')
""")
    config_rows = cursor.fetchall()
    config_map = {str(row["id"]).strip(): parse_float(row["value"]) for row in config_rows}

    a_limit = config_map.get("2.18.5.1")
    b_limit = config_map.get("2.18.5.2")
    c_limit = config_map.get("2.18.5.3")

    if (
            a is not None and a_limit is not None and a <= a_limit and
            b is not None and b_limit is not None and b <= b_limit and
            c is not None and c_limit is not None and c <= c_limit
    ):
        zhuiqiao["锥壳小端是否连接法兰或平盖等结构件"] = "是"
    else:
        zhuiqiao["锥壳小端是否连接法兰或平盖等结构件"] = "否"
    cursor.execute("""
    SELECT 参数值 FROM 产品设计活动表_元件附加参数表
    WHERE 产品ID = %s AND 元件名称 = '锥壳' AND 参数名称 = '锥壳大端是否带折边'
""", (product_id,))
    row = cursor.fetchone()

    if row and row.get("参数值") is not None:
        zhuiqiao["锥壳大端是否带折边"] = str(row["参数值"])
    cursor.execute("""
    SELECT 参数值 FROM 产品设计活动表_元件附加参数表
    WHERE 产品ID = %s AND 元件名称 = '锥壳' AND 参数名称 = '锥壳小端是否带折边'
""", (product_id,))
    row = cursor.fetchone()

    if row and row.get("参数值") is not None:
        zhuiqiao["锥壳小端是否带折边"] = str(row["参数值"])
    cursor.execute("""
    SELECT 参数值 FROM 产品设计活动表_元件附加参数表
    WHERE 产品ID = %s AND 元件名称 = '锥壳' AND 参数名称 = '是否需要锥壳与大端连接处作为支撑线'
""", (product_id,))
    row = cursor.fetchone()

    if row and row.get("参数值") is not None:
        zhuiqiao["是否需要锥壳与大端连接处作为支撑线"] = str(row["参数值"])
    cursor.execute("""
    SELECT 参数值 FROM 产品设计活动表_元件附加参数表
    WHERE 产品ID = %s AND 元件名称 = '锥壳' AND 参数名称 = '是否需要锥壳与小端连接处作为支撑线'
""", (product_id,))
    row = cursor.fetchone()

    if row and row.get("参数值") is not None:
        zhuiqiao["是否需要锥壳与小端连接处作为支撑线"] = str(row["参数值"])
    cursor.execute("""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s AND 元件名称 = '壳体小端圆筒'
        """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    # guanxiang_pinggai["圆筒名义内径"] = row_map.get("内径", "0")
    # guanxiang_pinggai["圆筒名义外径"] = row_map.get("外径", "0")
    zhuiqiao["与锥壳小端连接的圆筒材料类型"] = row_map.get("材料类型", "0")
    zhuiqiao["与锥壳小端连接的圆筒材料牌号"] = row_map.get("材料牌号", "0")
    cursor.execute("""
        SELECT 参数名称, 参数值
        FROM 产品设计活动表_元件附加参数表
        WHERE 产品ID = %s AND 元件名称 = '壳体大端圆筒'
    """, (product_id,))
    rows = cursor.fetchall()
    row_map = {row["参数名称"].strip(): safe_str(row["参数值"]) for row in rows}

    # guanxiang_pinggai["圆筒名义内径"] = row_map.get("内径", "0")
    # guanxiang_pinggai["圆筒名义外径"] = row_map.get("外径", "0")
    zhuiqiao["与锥壳小端连接的圆筒材料类型"] = row_map.get("材料类型", "0")
    zhuiqiao["与锥壳小端连接的圆筒材料牌号"] = row_map.get("材料牌号", "0")