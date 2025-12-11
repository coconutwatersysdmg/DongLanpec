import json
import pymysql

def update_user_config_for_2_6_1(product_id, json_path="modules/yudingyi/dn_pressure_table.json"):
    # 读取 JSON 压力区间数据
    with open(json_path, "r", encoding="utf-8") as f:
        dn_table = json.load(f)["data"]

    # 压力区间定义
    pressure_ranges = [
        ("≥-0.1", float("-inf"), 0.6),
        ("≥0.6", 0.6, 1),
        ("≥1", 1, 1.6),
        ("≥1.6", 1.6, 2.5),
        ("≥2.5", 2.5, 4),
        ("≥4", 4, float("inf"))
    ]

    # 数据库连接
    conn = pymysql.connect(
        host='localhost',
        user='root',
        password='123456',
        database='产品设计活动库',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

    try:
        with conn.cursor() as cursor:
            # 获取公称直径
            cursor.execute("""
                SELECT 管程数值, 壳程数值 FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s AND 参数名称 = '公称直径*'
            """, (product_id,))
            row_d = cursor.fetchone()
            values_d = [row_d.get("管程数值"), row_d.get("壳程数值")] if row_d else [0,0]
            values_d = [float(v if v else 100) for v in values_d if v is not None]
            nominal_diameter = max(values_d) if values_d else None

            # 获取设计压力
            cursor.execute("""
                SELECT 管程数值, 壳程数值 FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s AND 参数名称 = '设计压力*'
            """, (product_id,))
            row_p = cursor.fetchone()
            values_p = [row_p.get("管程数值"), row_p.get("壳程数值")] if row_p else [0,0]
            values_p = [float(v if v else 0) for v in values_p if v is not None]
            design_pressure = max(values_p) if values_p else 0

            if nominal_diameter is not None and design_pressure is not None:
                # 找到 DN 对应数据
                dn_int = round(nominal_diameter)
                matched_dn = next((item for item in dn_table if item["DN"] == dn_int), None)
                if not matched_dn:
                    print(f"❌ 找不到公称直径 DN={dn_int} 的数据")
                    return

                # 匹配压力范围
                for label, low, high in pressure_ranges:
                    if low <= design_pressure < high:
                        pr_data = matched_dn["P_ranges"].get(label)
                        if pr_data:
                            mmin = str(pr_data["Mmin"])
                            mmax = str(pr_data["Mmax"])

                            # 执行更新
                            update_sql = """
                                UPDATE 配置库.user_config SET value = %s WHERE id = %s
                            """
                            cursor.execute(update_sql, (mmin, "2.4.6.1"))
                            cursor.execute(update_sql, (mmax, "2.4.6.2"))
                            conn.commit()
                            print(f"✅ 已更新 user_config：2.4.6.1 = {mmin}, 2.4.6.2 = {mmax}")
                            return
                        else:
                            print(f"⚠️ 未找到压力区间 {label} 的数据")
                print(f"⚠️ 无法匹配设计压力 {design_pressure} 的区间")
            else:
                print("❌ 公称直径或设计压力缺失，无法判断")

    finally:
        conn.close()
