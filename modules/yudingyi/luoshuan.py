import json
import pymysql

import pymysql
import json

def update_user_config_for_2_6_1(product_id, json_path="modules/yudingyi/dn_pressure_table.json"):
    """同时更新远程(10.32.22.189)与本地localhost数据库；若远程连接失败，则仅更新本地。"""
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

    # 尝试连接远程数据库
    remote_conn = None
    try:
        remote_conn = pymysql.connect(
            host='10.32.22.189',
            user='root',
            password='123456',
            database='产品设计活动库',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5
        )
        print("✅ 已连接远程数据库 10.32.22.189")
    except Exception as e:
        print(f"⚠️ 无法连接远程数据库 10.32.22.189：{e}，将跳过远程更新。")

    # 本地数据库连接（总是执行）
    local_conn = None
    try:
        local_conn = pymysql.connect(
            host='localhost',
            user='root',
            password='123456',
            database='产品设计活动库',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        print("✅ 已连接本地数据库 localhost")
    except Exception as e:
        print(f"❌ 无法连接本地数据库：{e}")
        return

    try:
        # 使用本地数据库获取设计参数
        with local_conn.cursor() as cursor:
            # 获取公称直径
            cursor.execute("""
                SELECT 管程数值, 壳程数值 FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s AND 参数名称 = '公称直径*'
            """, (product_id,))
            row_d = cursor.fetchone()
            values_d = [row_d.get("管程数值"), row_d.get("壳程数值")] if row_d else [0, 0]
            values_d = [float(v) if v not in (None, '') else 0 for v in values_d]
            nominal_diameter = max(values_d) if values_d else 0

            # 获取设计压力
            cursor.execute("""
                SELECT 管程数值, 壳程数值 FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s AND 参数名称 = '设计压力*'
            """, (product_id,))
            row_p = cursor.fetchone()
            values_p = [row_p.get("管程数值"), row_p.get("壳程数值")] if row_p else [0, 0]
            values_p = [float(v) if v not in (None, '') else 0 for v in values_p]
            design_pressure = max(values_p) if values_p else 0

        if nominal_diameter is None or design_pressure is None:
            print("❌ 公称直径或设计压力缺失，无法判断。")
            return

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
                if not pr_data:
                    print(f"⚠️ 未找到压力区间 {label} 的数据")
                    return

                mmin = str(pr_data["Mmin"])
                mmax = str(pr_data["Mmax"])
                update_sql = "UPDATE 配置库.user_config SET value = %s WHERE id = %s"

                # 更新本地数据库
                with local_conn.cursor() as c1:
                    c1.execute(update_sql, (mmin, "2.4.6.1"))
                    c1.execute(update_sql, (mmax, "2.4.6.2"))
                    local_conn.commit()
                    print(f"✅ 已更新本地 user_config：2.4.6.1={mmin}, 2.4.6.2={mmax}")

                # 更新远程数据库（如果连接成功）
                if remote_conn:
                    try:
                        with remote_conn.cursor() as c2:
                            c2.execute(update_sql, (mmin, "2.4.6.1"))
                            c2.execute(update_sql, (mmax, "2.4.6.2"))
                            remote_conn.commit()
                            print("✅ 已更新远程 user_config 同步完成。")
                    except Exception as e:
                        print(f"⚠️ 远程更新失败：{e}")

                return  # 成功后退出循环

        print(f"⚠️ 无法匹配设计压力 {design_pressure} 的区间")

    finally:
        if local_conn:
            local_conn.close()
        if remote_conn:
            remote_conn.close()
