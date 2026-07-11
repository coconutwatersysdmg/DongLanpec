"""布管计算相关的SQL构建逻辑，便于与界面代码解耦。"""

from collections import defaultdict
import math
from ast import literal_eval
import pymysql


def build_sql_for_u_tube_calc(editor, create_product_connection):
    from collections import defaultdict as _dd

    """
    构建U型管布管计算结果的SQL语句列表。
    这里保留原有逻辑，只是从My_Piping.py中抽离，传入editor实例和数据库连接创建函数。
    """
    if not hasattr(editor, "current_centers") or not isinstance(
            editor.current_centers, (list, set, tuple)
    ):
        return None
    if not hasattr(editor, "current_centers_lagan") or not isinstance(
            editor.current_centers_lagan, (list, set, tuple)
    ):
        return None
    try:
        coords = []
        for center in editor.current_centers:
            if len(center) >= 2:  # 确保包含x、y坐标
                x = float(center[0])
                y = float(center[1])
                coords.append((x, y))
        if not coords:
            return None
    except (ValueError, TypeError):
        return None
    try:
        current_centers_lagans = []
        for global_coord in editor.current_centers_lagan:
            if len(global_coord) >= 2:
                x = float(global_coord[0])
                y = float(global_coord[1])
                current_centers_lagans.append((x, y))
        print(current_centers_lagans,"global")
        if not current_centers_lagans:
            return None
    except (ValueError, TypeError):
        return None
    calc_results = {
        "沿水平隔板槽一侧的排管根数": "0",
        "沿竖直隔板槽一侧的排管根数": "0",
        "水平隔板槽两侧相邻管中心距": "0.0",
        "垂直隔板槽两侧相邻管中心距": "0.0",
        "换热管中心距 S": "0.0",
        "是否交叉布管": "0",
        "交叉管排1最两端管孔中心距": "0.0",
        "交叉管排1实际管孔数量": "0",
        "交叉管排2最两端管孔中心距": "0.0",
        "交叉管排2实际管孔数量": "0",
        "交叉管排3最两端管孔中心距": "0.0",
        "交叉管排3实际管孔数量": "0",
        "U型管弯曲直径": "0.0",
        "管总数 tubes_count": "0",
    }

    product_id = editor.productID
    tube_form = None
    s_val = 25.0
    sn_val = 0.0
    snh_val = 100.0
    tubes_count = 0

    try:
        conn = create_product_connection()
        if not conn:
            return None

        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            params_map = {
                "换热管中心距 S": "s_val",
                "分程隔板两侧相邻管中心距（竖直）": "sn_val",
                "分程隔板两侧相邻管中心距（水平）": "snh_val",
            }
            for param_name, param_key in params_map.items():
                cursor.execute(
                    """
                        SELECT 参数值 
                        FROM 产品设计活动表_布管参数表
                        WHERE 产品ID = %s AND 参数名 = %s
                        LIMIT 1
                    """,
                    (product_id, param_name),
                )
                row = cursor.fetchone()
                if row and row.get("参数值"):
                    raw_val = row["参数值"].strip()
                    try:
                        if param_key == "s_val":
                            s_val = float(raw_val)
                        elif param_key == "sn_val":
                            sn_val = float(raw_val)
                        elif param_key == "snh_val":
                            snh_val = float(raw_val)
                    except (ValueError, TypeError):
                        print("参数值无效")

                cursor.execute(
                    """
                            SELECT value 
                            FROM 产品设计活动表_布管结果表
                            WHERE 产品ID = %s AND `key` = 'W'
                            LIMIT 1
                        """,
                    (product_id,),
                )
                row = cursor.fetchone()
                if row and row.get("value"):
                    getiao_chicun = float(row["value"].strip())
                else:
                    getiao_chicun = 0.0

            cursor.execute(
                """
                    SELECT 参数值 
                    FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = '管程程数'
                    LIMIT 1
                """,
                (product_id,),
            )
            row = cursor.fetchone()
            tube_form = row["参数值"].strip() if (row and row.get("参数值")) else None
            deleted_coords = set()

            vertical_total = 0
            cursor.execute(
                """
                    SELECT `管孔数量（上）`, `管孔数量（下）`, CAST(`至水平中心线行号` AS SIGNED) AS line_no
                    FROM 产品设计活动表_布管数量表_水平
                    WHERE 产品ID = %s
                """,
                (product_id,),
            )
            qty_rows = cursor.fetchall() or []
            cursor.execute(
                """
                                    SELECT 坐标 
                                    FROM 产品设计活动表_布管元件表
                                    WHERE 产品ID = %s AND 元件类型 = 7
                                """,
                (product_id,),
            )
            deleted_rows = cursor.fetchall() or []

            for r in deleted_rows:
                raw_val = r.get("坐标") if isinstance(r, dict) else (r[0] if r else "")
                if not raw_val:
                    continue
                try:
                    coords_list = (
                        literal_eval(raw_val) if isinstance(raw_val, str) else raw_val
                    )
                    for xy in coords_list:
                        dx = float(xy[0])
                        dy = float(xy[1])
                        deleted_coords.add((dx, dy))
                except Exception:
                    continue

            cursor.execute(
                """
                    SELECT `管孔数量（上）`, `管孔数量（下）`, 
                           CAST(`至水平中心线行号` AS SIGNED) AS line_no
                    FROM 产品设计活动表_布管数量表_水平
                    WHERE 产品ID = %s
                """,
                (product_id,),
            )
            qty_rows = cursor.fetchall() or []

            if not qty_rows:
                cursor.execute(
                    """
                        SELECT `管孔数量（左）` AS `管孔数量（上）`,
                               `管孔数量（右）` AS `管孔数量（下）`,
                               CAST(`至竖直中心线行号` AS SIGNED) AS line_no
                        FROM 产品设计活动表_布管数量表_竖直
                        WHERE 产品ID = %s
                    """,
                    (product_id,),
                )
                qty_rows = cursor.fetchall() or []
                is_vertical = True
            else:
                is_vertical = False

            if qty_rows:
                total = 0
                for r in qty_rows:
                    up_val = r.get("管孔数量（上）")
                    up_val = (
                        int(up_val)
                        if (up_val and up_val not in ("None", "", "0"))
                        else 0
                    )
                    down_val = r.get("管孔数量（下）")
                    down_val = (
                        int(down_val)
                        if (down_val and down_val not in ("None", "", "0"))
                        else 0
                    )
                    total += up_val + down_val
                tubes_count = total

                horizontal_total = 0
                if is_vertical:
                    max_line = max(r.get("line_no", 0) or 0 for r in qty_rows)
                    for r in qty_rows:
                        if r.get("line_no") == 1:
                            up_val = r.get("管孔数量（上）")
                            up_val = (
                                int(up_val)
                                if (up_val and up_val not in ("None", "", "0"))
                                else 0
                            )
                            down_val = r.get("管孔数量（下）")
                            down_val = (
                                int(down_val)
                                if (down_val and down_val not in ("None", "", "0"))
                                else 0
                            )
                            horizontal_total = max(up_val, down_val)
                            break
                else:
                    for r in qty_rows:
                        if r.get("line_no") == 1:
                            up_val = r.get("管孔数量（上）")
                            up_val = (
                                int(up_val)
                                if (up_val and up_val not in ("None", "", "0"))
                                else 0
                            )
                            down_val = r.get("管孔数量（下）")
                            down_val = (
                                int(down_val)
                                if (down_val and down_val not in ("None", "", "0"))
                                else 0
                            )
                            horizontal_total = max(up_val, down_val)
                            break
            else:
                tubes_count = 0
                horizontal_total = 0
            cursor.execute(
                """
                    SELECT 参数值 
                    FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = '换热管外径 do'
                    LIMIT 1
                """,
                (product_id,),
            )
            row = cursor.fetchone()
            if row and row.get("参数值"):
                do_value = float(row["参数值"].strip())
            else:
                do_value = 25.0
            cursor.execute(
                """
                    SELECT 参数值 
                    FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = '折流板切口方向'
                    LIMIT 1
                """,
                (product_id,),
            )
            row = cursor.fetchone()
            mapped_val = row["参数值"].strip() if (row and row.get("参数值")) else ""
            if mapped_val in {"水平上下"}:
                cut_dir = "水平"
            elif mapped_val in {"左右", "垂直左右"}:
                cut_dir = "垂直"
            elif mapped_val in {"上下"}:
                cut_dir = "竖直"
            else:
                cut_dir = mapped_val
    except pymysql.Error:
        return None
    finally:
        if conn and conn.open:
            conn.close()

    def is_deleted(x, y, tol=1e-6):
        for dx, dy in deleted_coords:
            if abs(x - dx) < tol and abs(y - dy) < tol:
                return True
        return False

    filtered_coords = [(x, y) for x, y in coords if not is_deleted(x, y)]

    x_groups = defaultdict(list)
    y_groups = defaultdict(list)

    for x, y in coords:
        x_groups[x].append(y)
        y_groups[y].append(x)

    max_y_gap = 0.0
    min_y_gap = float("inf")
    if tube_form == "2":
        # 以 x 轴为参考 → 用 y
        axis_values = [abs(float(y)) for x, y in coords]
    elif tube_form in ("4", "6"):
        # 以 y 轴为参考 → 用 x
        axis_values = [abs(float(x)) for x, y in coords]
    else:
        raise ValueError(f"Unsupported tube_form: {tube_form}")

    for _, y_list in x_groups.items():
        numeric_y = [float(y) for y in y_list if str(y).replace(".", "").isdigit()]
        if len(numeric_y) >= 2:
            gap = max(numeric_y) - min(numeric_y)
            if gap > 0:
                max_y_gap = max(max_y_gap, gap)
                min_y_gap = min(min_y_gap, gap)

    max_x_gap = 0.0
    min_x_gap = float("inf")

    for _, x_list in y_groups.items():
        numeric_x = [float(x) for x in x_list if str(x).replace(".", "").isdigit()]
        if len(numeric_x) >= 2:
            gap = max(numeric_x) - min(numeric_x)
            if gap > 0:
                max_x_gap = max(max_x_gap, gap)
                min_x_gap = min(min_x_gap, gap)

    u_min_radius = round(min(axis_values), 3)
    u_max_diameter = round(2 * max(axis_values), 3)

    print("coords", coords)
    print(u_min_radius, "u_min_radius")
    print(u_max_diameter, "u_max_diameter")

    vertical_total = 0
    if tube_form == "2":
        horizontal_total = 0
        conn = create_product_connection()
        if conn:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                            SELECT CAST(`至水平中心线行号` AS SIGNED) AS line_no,
                                   `管孔数量（上）`, `管孔数量（下）`
                            FROM 产品设计活动表_布管数量表_显示
                            WHERE 产品ID = %s
                            ORDER BY line_no ASC
                        """,
                    (product_id,),
                )
                qty_rows = cursor.fetchall() or []

                if qty_rows:
                    for r in qty_rows:
                        try:
                            line_no = int(r.get("line_no", 0))
                        except Exception:
                            line_no = 0

                        raw_down = r.get("管孔数量（下）")
                        try:
                            down_val = (
                                int(raw_down)
                                if (
                                        raw_down is not None
                                        and str(raw_down).strip() not in ("", "None")
                                )
                                else 0
                            )
                        except Exception:
                            down_val = 0

                        if down_val > 0:
                            vertical_total = down_val
                            break
        calc_results["沿水平隔板槽一侧的排管根数"] = str(int(vertical_total))

    elif tube_form == "4":
        try:
            conn = create_product_connection()
            if conn:
                with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                    cursor.execute(
                        """
                                SELECT CAST(`至水平中心线行号` AS SIGNED) AS line_no,
                                       `管孔数量（上）`, `管孔数量（下）`
                                FROM 产品设计活动表_布管数量表_显示
                                WHERE 产品ID = %s
                                ORDER BY line_no ASC
                            """,
                        (product_id,),
                    )
                    qty_rows = cursor.fetchall() or []

                    vertical_total = 0
                    if qty_rows:
                        for r in qty_rows:
                            try:
                                line_no = int(r.get("line_no", 0))
                            except Exception:
                                line_no = 0

                            raw_down = r.get("管孔数量（下）")
                            try:
                                down_val = (
                                    int(raw_down)
                                    if (
                                            raw_down is not None
                                            and str(raw_down).strip() not in ("", "None")
                                    )
                                    else 0
                                )
                            except Exception:
                                down_val = 0

                            if down_val > 0:
                                vertical_total = down_val
                                break
        except Exception as e:
            print("读取布管数量表出错：", e)
            vertical_total = 0
        finally:
            if conn and conn.open:
                conn.close()
        calc_results["沿水平隔板槽一侧的排管根数"] = str(int(vertical_total))

    elif tube_form == "6":
        coords_local = []
        for center in editor.current_centers:
            if len(center) >= 2:
                x = float(center[0])
                y = float(center[1])
                coords_local.append((x, y))
        if not coords_local:
            return None
        filtered_coords = [(x, y) for x, y in coords_local if not is_deleted(x, y)]

        y_above = [y for x, y in filtered_coords if y < getiao_chicun]
        positive_ys = [y for x, y in filtered_coords if y > 0]
        if positive_ys:
            target_y = min(positive_ys)
        else:
            all_ys = [y for x, y in filtered_coords]
            target_y = min(all_ys) if all_ys else 0.0
        selected_coords_cross = []

        y_below = [y for x, y in filtered_coords if y > -getiao_chicun]
        if y_below:
            max_below_y = min(y_below)
            selected_coords_cross.extend(
                [(x, y) for x, y in filtered_coords if abs(y - max_below_y) < 1e-6]
            )
        calc_results["沿水平隔板槽一侧的排管根数"] = str(len(selected_coords_cross))

    calc_results["沿竖直隔板槽一侧的排管根数"] = str(horizontal_total)
    calc_results["水平隔板槽两侧相邻管中心距"] = str(round(snh_val, 3))
    calc_results["垂直隔板槽两侧相邻管中心距"] = str(round(sn_val, 3))
    calc_results["换热管中心距 S"] = str(round(s_val, 3))
    calc_results["U型管弯曲直径"] = str(u_max_diameter)
    calc_results["弯管段的最小弯曲半径"] = str(u_min_radius)

    calc_results["管总数 tubes_count"] = str(tubes_count)

    def calc_distance(x1, y1, x2, y2):
        return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5

    def get_max_distance(coord_list):
        max_dist = 0.0
        if len(coord_list) >= 2:
            for i in range(len(coord_list)):
                x1, y1 = coord_list[i]
                for j in range(i + 1, len(coord_list)):
                    x2, y2 = coord_list[j]
                    dist = calc_distance(x1, y1, x2, y2)
                    if dist > max_dist:
                        max_dist = dist
        return round(max_dist, 3)

    if current_centers_lagans:
        max_radius = max(math.hypot(x, y) for x, y in current_centers_lagans)
        calc_results["实际布管区域最大直径"] = str(round(max_radius * 2 + do_value, 3))

        max_height = 0.0
        max_width = 0.0

        if cut_dir == "竖直左右":
            # 同一排：y 相同，统计这一排的 x 跨度 -> 宽度
            y_groups = _dd(list)
            # 同一列：x 相同，统计这一列的 y 跨度 -> 高度
            x_groups = _dd(list)

            for x, y in current_centers_lagans:
                y_groups[round(y, 6)].append(x)
                x_groups[round(x, 6)].append(y)

            if y_groups:
                row_spans = [max(x_list) - min(x_list) for x_list in y_groups.values()]
                max_width = (max(row_spans) if row_spans else 0.0) + do_value

            if x_groups:
                col_spans = [max(y_list) - min(y_list) for y_list in x_groups.values()]
                max_height = (max(col_spans) if col_spans else 0.0) + do_value

        elif cut_dir == "水平上下":
            # 这里按你原来的思路，方向旋转后，排/列统计交换
            x_groups = _dd(list)
            y_groups = _dd(list)

            for x, y in coords:
                x_groups[round(x, 6)].append(y)
                y_groups[round(y, 6)].append(x)

            # 水平上下时，按你原业务习惯：
            # 宽度改为看“同一列中的 x 方向展开”
            if y_groups:
                row_spans = [max(x_list) - min(x_list) for x_list in y_groups.values()]
                max_width = (max(row_spans) if row_spans else 0.0) + do_value

            # 高度改为看“同一列中的 y 方向展开”
            if x_groups:
                col_spans = [max(y_list) - min(y_list) for y_list in x_groups.values()]
                max_height = (max(col_spans) if col_spans else 0.0) + do_value

        else:
            x_values = [x for x, _ in current_centers_lagans]
            y_values = [y for _, y in current_centers_lagans]
            max_width = (max(x_values) - min(x_values)) + do_value
            max_height = (max(y_values) - min(y_values)) + do_value

        calc_results["实际布管区域最大宽度"] = str(round(max_width, 3))
        calc_results["实际布管区域最大高度"] = str(round(max_height, 3))

    else:
        calc_results["实际布管区域最大直径"] = "0.0"
        calc_results["实际布管区域最大宽度"] = "0.0"
        calc_results["实际布管区域最大高度"] = "0.0"
    table_name = "`产品设计活动表_布管计算结果表`"
    sql_statements = []

    def escape_sql(value):
        if isinstance(value, str):
            return value.replace("'", "''")
        return str(value)

    delete_sql = (
        f"DELETE FROM {table_name} "
        f"WHERE `产品ID` = '{escape_sql(product_id)}' "
        f"AND `产品类型` = '2'"
    )
    sql_statements.append(delete_sql)

    for calc_name, calc_val in calc_results.items():
        esc_product_id = escape_sql(product_id)
        esc_calc_name = escape_sql(calc_name)
        esc_calc_val = escape_sql(calc_val)
        esc_product_type = "2"

        insert_sql = (
            f"INSERT INTO {table_name} "
            f"(`产品ID`, `计算值名称`, `计算值`, `产品类型`) "
            f"VALUES ("
            f"'{esc_product_id}', "
            f"'{esc_calc_name}', "
            f"'{esc_calc_val}', "
            f"'{esc_product_type}'"
            f")"
        )
        sql_statements.append(insert_sql)

    return sql_statements


def build_sql_for_floating_head_calc(editor, create_product_connection):
    """
    构建浮头式/固定管板布管计算结果的SQL语句列表。
    """
    from collections import defaultdict as _dd

    if not hasattr(editor, "current_centers") or not isinstance(
            editor.current_centers, (list, set, tuple)
    ):
        return None

    try:
        coords = []
        for center in editor.current_centers:
            if len(center) >= 2:
                x = float(center[0])
                y = float(center[1])
                coords.append((x, y))
        if not coords:
            return None
    except (ValueError, TypeError):
        return None

    if not hasattr(editor, "current_centers_lagan") or not isinstance(
            editor.current_centers_lagan, (list, set, tuple)
    ):
        return None

    try:
        current_centers_lagans = []
        for global_coord in editor.current_centers_lagan:
            if len(global_coord) >= 2:
                x = float(global_coord[0])
                y = float(global_coord[1])
                current_centers_lagans.append((x, y))
        print(current_centers_lagans,"global")
        if not current_centers_lagans:
            return None
    except (ValueError, TypeError):
        return None
    calc_results = {
        "'十字'交叉沿水平隔板槽单侧的排管根数": "0",
        "沿竖直隔板槽单侧的排管根数": "0",
        "'丁字'交叉沿水平隔板槽连续侧的排管根数": "0",
        "'丁字'交叉沿水平隔板槽不连续侧的排管根数": "0",
        "'十字'交叉沿水平隔板槽单侧管排1最两端管孔中心距": "0.0",
        "'十字'交叉沿水平隔板槽单侧管排2最两端管孔中心距": "0.0",
        "'十字'交叉沿水平隔板槽单侧管排3最两端管孔中心距": "0.0",
        "'丁字'交叉沿水平隔板槽不连续侧管排1最两端管孔中心距": "0.0",
        "'丁字'交叉沿水平隔板槽不连续侧管排2最两端管孔中心距": "0.0",
        "'丁字'交叉沿水平隔板槽不连续侧管排3最两端管孔中心距": "0.0",
        "沿竖直隔板槽单侧的管排最两端管孔中心距": "0.0",
        "相邻隔板槽中心距": "0.0",
        "实际布管区域最大直径": "0.0",
        "实际布管区域最大高度": "0.0",
    }

    product_id = editor.productID
    tube_form = None
    cut_dir = None
    tube_arr = None
    getiao_chicun = 0.0
    deleted_coords = set()
    do_value = 0.0

    try:
        conn = create_product_connection()
        if not conn:
            return None

        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(
                """
                    SELECT 参数值 
                    FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = '管程分程形式'
                    LIMIT 1
                """,
                (product_id,),
            )
            row = cursor.fetchone()
            tube_form = row["参数值"].strip() if (row and row.get("参数值")) else None
            cursor.execute(
                """
                    SELECT 参数值 
                    FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = '折流板类型'
                    LIMIT 1
                """,
                (product_id,),
            )
            row = cursor.fetchone()
            type_zheliuban = row["参数值"].strip() if (row and row.get("参数值")) else None
            cursor.execute(
                """
                    SELECT 参数值 
                    FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = '折流板切口方向'
                    LIMIT 1
                """,
                (product_id,),
            )
            row = cursor.fetchone()
            mapped_val = row["参数值"].strip() if (row and row.get("参数值")) else ""
            if mapped_val in {"水平上下"}:
                cut_dir = "水平"
            elif mapped_val in {"左右", "垂直左右"}:
                cut_dir = "垂直"
            elif mapped_val in {"上下"}:
                cut_dir = "竖直"
            else:
                cut_dir = mapped_val

            cursor.execute(
                """
                    SELECT 参数值 
                    FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = '换热管排列方式'
                    LIMIT 1
                """,
                (product_id,),
            )
            row = cursor.fetchone()
            tube_arr = row["参数值"].strip() if (row and row.get("参数值")) else None

            cursor.execute(
                """
                    SELECT value 
                    FROM 产品设计活动表_布管结果表
                    WHERE 产品ID = %s AND `key` = 'W'
                    LIMIT 1
                """,
                (product_id,),
            )
            row = cursor.fetchone()
            if row and row.get("value"):
                getiao_chicun = float(row["value"].strip())
            else:
                getiao_chicun = 0.0

            cursor.execute(
                """
                    SELECT 参数值 
                    FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = '换热管外径 do'
                    LIMIT 1
                """,
                (product_id,),
            )
            row = cursor.fetchone()
            if row and row.get("参数值"):
                do_value = float(row["参数值"].strip())
            else:
                do_value = 25.0

            cursor.execute(
                """
                    SELECT 坐标 
                    FROM 产品设计活动表_布管元件表
                    WHERE 产品ID = %s AND 元件类型 = 7
                """,
                (product_id,),
            )
            deleted_rows = cursor.fetchall() or []

            for r in deleted_rows:
                raw_val = r.get("坐标") if isinstance(r, dict) else (r[0] if r else "")
                if not raw_val:
                    continue
                try:
                    coords_list = (
                        literal_eval(raw_val) if isinstance(raw_val, str) else raw_val
                    )
                    for xy in coords_list:
                        dx = float(xy[0])
                        dy = float(xy[1])
                        deleted_coords.add((dx, dy))
                except Exception:
                    continue
    except pymysql.Error:
        return None
    finally:
        if conn and conn.open:
            conn.close()

    def is_deleted(x, y, tol=1e-6):
        for dx, dy in deleted_coords:
            if abs(x - dx) < tol and abs(y - dy) < tol:
                return True
        return False

    filtered_coords = [(x, y) for x, y in coords if not is_deleted(x, y)]
    # ================== NX / NY / NXA / NYA 计算 ==================
    try:
        conn = create_product_connection()
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(
                """
                    SELECT 参数值 
                    FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = 'A型板切口与中心线间距a'
                    LIMIT 1
                """,
                (product_id,),
            )
            row = cursor.fetchone()
            a_val = float(row["参数值"]) if row and row.get("参数值") else None

            cursor.execute(
                """
                    SELECT 参数值 
                    FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = 'B型板切口与中心线间距b'
                    LIMIT 1
                """,
                (product_id,),
            )
            row = cursor.fetchone()
            b_val = float(row["参数值"]) if row and row.get("参数值") else None

        def calc_double_bow_NX_NY(coords, a_val, b_val):
            from collections import defaultdict

            def calc_N_and_NA(coords, r, tol=1.0):
                if r is None:
                    return 0, 0

                # ===== 按 x 分组，并允许 x 坐标误差在 1 以内 =====
                centers = []
                x_groups = {}

                for x, y in coords:
                    try:
                        x_val = float(x)
                        y_val = float(y)
                    except Exception:
                        continue

                    best_idx = None
                    best_dist = None

                    for i, c in enumerate(centers):
                        dist = abs(x_val - c)
                        if best_dist is None or dist < best_dist:
                            best_dist = dist
                            best_idx = i

                    if best_dist is not None and best_dist <= tol:
                        old_c = centers[best_idx]
                        ys = x_groups.pop(old_c)
                        ys.append(y_val)

                        new_c = (old_c * (len(ys) - 1) + x_val) / len(ys)
                        centers[best_idx] = new_c
                        x_groups[new_c] = ys
                    else:
                        centers.append(x_val)
                        x_groups[x_val] = [y_val]

                # ===== 分别统计正侧 / 负侧 =====
                pos_groups = {x: ys for x, ys in x_groups.items() if x > r}
                neg_groups = {x: ys for x, ys in x_groups.items() if x < -r}

                pos_N = sum(len(ys) for ys in pos_groups.values())
                neg_N = sum(len(ys) for ys in neg_groups.values())

                # ===== 只取一侧：哪一侧更多就取哪一侧 =====
                if pos_N >= neg_N:
                    N = pos_N
                    if pos_groups:
                        closest_pos_x = min(pos_groups.keys(), key=lambda x: abs(x - r))
                        NA = len(pos_groups[closest_pos_x])
                    else:
                        NA = 0
                else:
                    N = neg_N
                    if neg_groups:
                        closest_neg_x = min(neg_groups.keys(), key=lambda x: abs(x + r))
                        NA = len(neg_groups[closest_neg_x])
                    else:
                        NA = 0

                return N, NA

            Na, NAa = calc_N_and_NA(coords, a_val)
            Nb, NAb = calc_N_and_NA(coords, b_val)

            # 这里保持你原来的双弓形逻辑不变
            if Na >= Nb:
                NX = Na
                NXA = NAa
                NY = Nb
                NYA = NAb
            else:
                NX = Nb
                NXA = NAb
                NY = Na
                NYA = NAa

            return NX, NXA, NY, NYA

        def calc_single_bow_NX_NY(coords, a_val, cut_dir):
            from collections import defaultdict

            def calc_N_and_NA(coords, r, use_x=True, tol=1.0):
                if r is None:
                    return 0, 0

                centers = []
                groups = {}

                for x, y in coords:
                    try:
                        key_val = float(x) if use_x else float(y)
                        other_val = float(y) if use_x else float(x)
                    except Exception:
                        continue

                    best_idx = None
                    best_dist = None

                    for i, c in enumerate(centers):
                        dist = abs(key_val - c)
                        if best_dist is None or dist < best_dist:
                            best_dist = dist
                            best_idx = i

                    if best_dist is not None and best_dist <= tol:
                        old_c = centers[best_idx]
                        vals = groups.pop(old_c)
                        vals.append(other_val)

                        new_c = (old_c * (len(vals) - 1) + key_val) / len(vals)
                        centers[best_idx] = new_c
                        groups[new_c] = vals
                    else:
                        centers.append(key_val)
                        groups[key_val] = [other_val]

                pos_groups = {k: vs for k, vs in groups.items() if k > r}
                neg_groups = {k: vs for k, vs in groups.items() if k < -r}

                pos_N = sum(len(vs) for vs in pos_groups.values())
                neg_N = sum(len(vs) for vs in neg_groups.values())

                if pos_N >= neg_N:
                    N = pos_N
                    if pos_groups:
                        closest_pos = min(pos_groups.keys(), key=lambda k: abs(k - r))
                        NA = len(pos_groups[closest_pos])
                    else:
                        NA = 0
                else:
                    N = neg_N
                    if neg_groups:
                        closest_neg = min(neg_groups.keys(), key=lambda k: abs(k + r))
                        NA = len(neg_groups[closest_neg])
                    else:
                        NA = 0

                return N, NA

            # 单弓形：
            # 垂直左右 -> 按 x
            # 水平上下 -> 按 y
            use_x = cut_dir not in ("水平上下", "水平")

            NX, NXA = calc_N_and_NA(coords, a_val, use_x=use_x)
            NY, NYA = 0, 0

            return NX, NXA, NY, NYA

        # ===== 分类型计算 =====
        if type_zheliuban in ("双弓形折流板", "双弓型折流板", "双弓形"):
            NX, NXA, NY, NYA = calc_double_bow_NX_NY(filtered_coords, a_val, b_val)

        elif type_zheliuban in ("单弓形折流板", "单弓型折流板", "单弓形"):
            NX, NXA, NY, NYA = calc_single_bow_NX_NY(filtered_coords, a_val, cut_dir)

        else:
            NX, NXA, NY, NYA = 0, 0, 0, 0

        print("NX =", NX, "NXA =", NXA)
        print("NY =", NY, "NYA =", NYA)

        calc_results["换热管数量NX"] = str(NX)
        calc_results["换热管数量NXA"] = str(NXA)
        calc_results["换热管数量NY"] = str(NY)
        calc_results["换热管数量NYA"] = str(NYA)

    except Exception as e:
        calc_results["换热管数量NX"] = "0"
        calc_results["换热管数量NXA"] = "0"
        calc_results["换热管数量NY"] = "0"
        calc_results["换热管数量NYA"] = "0"

    def calc_distance(x1, y1, x2, y2):
        return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5

    def get_max_distance(coord_list):
        max_dist = 0.0
        if len(coord_list) >= 2:
            for i in range(len(coord_list)):
                x1, y1 = coord_list[i]
                for j in range(i + 1, len(coord_list)):
                    x2, y2 = coord_list[j]
                    dist = calc_distance(x1, y1, x2, y2)
                    if dist > max_dist:
                        max_dist = dist
        return round(max_dist, 3)

    if current_centers_lagans:
        max_radius = max(math.hypot(x, y) for x, y in current_centers_lagans)
        calc_results["实际布管区域最大直径"] = str(round(max_radius * 2 + do_value, 3))

        max_height = 0.0
        max_width = 0.0

        if cut_dir == "竖直左右":
            # 同一排：y 相同，统计这一排的 x 跨度 -> 宽度
            y_groups = _dd(list)
            # 同一列：x 相同，统计这一列的 y 跨度 -> 高度
            x_groups = _dd(list)

            for x, y in current_centers_lagans:
                y_groups[round(y, 6)].append(x)
                x_groups[round(x, 6)].append(y)

            if y_groups:
                row_spans = [max(x_list) - min(x_list) for x_list in y_groups.values()]
                max_width = (max(row_spans) if row_spans else 0.0) + do_value

            if x_groups:
                col_spans = [max(y_list) - min(y_list) for y_list in x_groups.values()]
                max_height = (max(col_spans) if col_spans else 0.0) + do_value

        elif cut_dir == "水平上下":
            # 这里按你原来的思路，方向旋转后，排/列统计交换
            x_groups = _dd(list)
            y_groups = _dd(list)

            for x, y in coords:
                x_groups[round(x, 6)].append(y)
                y_groups[round(y, 6)].append(x)

            # 水平上下时，按你原业务习惯：
            # 宽度改为看“同一列中的 x 方向展开”
            if y_groups:
                row_spans = [max(x_list) - min(x_list) for x_list in y_groups.values()]
                max_width = (max(row_spans) if row_spans else 0.0) + do_value

            # 高度改为看“同一列中的 y 方向展开”
            if x_groups:
                col_spans = [max(y_list) - min(y_list) for y_list in x_groups.values()]
                max_height = (max(col_spans) if col_spans else 0.0) + do_value

        else:
            x_values = [x for x, _ in current_centers_lagans]
            y_values = [y for _, y in current_centers_lagans]
            max_width = (max(x_values) - min(x_values)) + do_value
            max_height = (max(y_values) - min(y_values)) + do_value

        calc_results["实际布管区域最大宽度"] = str(round(max_width, 3))
        calc_results["实际布管区域最大高度"] = str(round(max_height, 3))

    else:
        calc_results["实际布管区域最大直径"] = "0.0"
        calc_results["实际布管区域最大宽度"] = "0.0"
        calc_results["实际布管区域最大高度"] = "0.0"

    fenchengxingshi = tube_form if tube_form else ""
    if tube_form == "2":
        fenchengxingshi = "2.1"

    need_two_rows = (cut_dir == "垂直" and tube_arr == "正三角形") or (
            cut_dir == "水平" and tube_arr == "转角正三角形"
    )

    selected_coords_cross = []
    if fenchengxingshi == "2.1":
        positive_ys = [y for x, y in filtered_coords if y > 0]
        if positive_ys:
            target_y = min(positive_ys)
        else:
            all_ys = [y for x, y in filtered_coords]
            target_y = min(all_ys) if all_ys else 0.0
        selected_coords_cross = [
            (x, y) for x, y in filtered_coords if abs(y - target_y) < 1e-6
        ]
        calc_results["'十字'交叉沿水平隔板槽单侧的排管根数"] = str(len(selected_coords_cross))
        max_dist_cross = get_max_distance(selected_coords_cross)
        calc_results["'十字'交叉沿水平隔板槽单侧管排1最两端管孔中心距"] = str(max_dist_cross)
        calc_results["沿竖直隔板槽单侧的排管根数"] = "0"
        calc_results["沿竖直隔板槽单侧的管排最两端管孔中心距"] = "0"
    elif fenchengxingshi in ("4.2", "6.1"):
        selected_coords_vertical = []

        if filtered_coords:
            candidates = [p for p in filtered_coords if p[0] < 0]

            first_row_y = (
                max(y for x, y in candidates if y <= 0)
                if any(y <= 0 for x, y in candidates)
                else min(y for x, y in candidates)
            )
            first_row_points = [
                (x, y) for x, y in filtered_coords if abs(y - first_row_y) < 1e-6
            ]
            selected_coords_vertical.extend(first_row_points)

            if need_two_rows:
                lower_y_candidates = [y for x, y in filtered_coords if y < first_row_y]
                if lower_y_candidates:
                    second_row_y = max(lower_y_candidates)
                    second_row_points = [
                        (x, y)
                        for x, y in filtered_coords
                        if abs(y - second_row_y) < 1e-6
                    ]
                    selected_coords_vertical.extend(second_row_points)

        calc_results["'十字'交叉沿水平隔板槽单侧的排管根数"] = str(
            len(selected_coords_vertical)
        )
        max_dist_cross = get_max_distance(selected_coords_vertical)
        calc_results["'十字'交叉沿水平隔板槽单侧管排1最两端管孔中心距"] = str(max_dist_cross)

    elif fenchengxingshi == "6.2":
        y_above = [y for x, y in filtered_coords if y > getiao_chicun]
        if y_above:
            min_above_y = min(y_above)
            selected_coords_cross.extend(
                [(x, y) for x, y in filtered_coords if abs(y - min_above_y) < 1e-6]
            )
        y_below = [y for x, y in filtered_coords if y < -getiao_chicun]
        if y_below:
            max_below_y = max(y_below)
            selected_coords_cross.extend(
                [(x, y) for x, y in filtered_coords if abs(y - max_below_y) < 1e-6]
            )
        calc_results["'十字'交叉沿水平隔板槽单侧的排管根数"] = str(len(selected_coords_cross))
        # max_dist_cross = get_max_distance(selected_coords_cross)
        # calc_results["'十字'交叉沿水平隔板槽单侧管排1最两端管孔中心距"] = str(max_dist_cross)

    if fenchengxingshi in ("4.3", "6.2", "6.1", "4.2"):
        selected_coords_vertical = []

        if filtered_coords:
            candidates = [p for p in filtered_coords if p[1] <= 0 and p[0] < 0]
            if candidates:
                first_point = min(candidates, key=lambda p: abs(p[1]))
                first_x = first_point[0]
                first_y = first_point[1]

                first_column_coords = [
                    (x, y) for x, y in filtered_coords if abs(x - first_x) < 1e-6
                ]
                selected_coords_vertical.extend(first_column_coords)

                if (cut_dir == "水平" and tube_arr == "正三角形") or (
                        cut_dir == "垂直" and tube_arr == "转角正三角形"
                ):
                    second_candidates = [
                        p for p in candidates if abs(p[1]) > abs(first_y)
                    ]
                    if second_candidates:
                        second_y = min(second_candidates, key=lambda p: abs(p[1]))[1]

                        row_points = [
                            (x, y)
                            for x, y in filtered_coords
                            if abs(y - second_y) < 1e-6 and x < 0
                        ]

                        if row_points:
                            second_x = min(row_points, key=lambda p: abs(p[0]))[0]

                            second_column_coords = [
                                (x, y)
                                for x, y in filtered_coords
                                if abs(x - second_x) < 1e-6
                            ]
                            selected_coords_vertical.extend(second_column_coords)

        calc_results["沿竖直隔板槽单侧的排管根数"] = str(len(selected_coords_vertical))
        max_dist_vertical = get_max_distance(selected_coords_vertical)
        calc_results["沿竖直隔板槽单侧的管排最两端管孔中心距"] = str(max_dist_vertical)

    if fenchengxingshi in ("4.1", "4.3", "6.1", "6.2"):
        try:
            strange_tube_result = editor.calculate_strange_tube()
            print(strange_tube_result,"strange_tube_result")
            if isinstance(strange_tube_result, (list, tuple)) and len(
                    strange_tube_result
            ) >= 4:
                calc_results["'丁字'交叉沿水平隔板槽连续侧的排管根数"] = str(
                    strange_tube_result[1]
                )
                calc_results["'丁字'交叉沿水平隔板槽不连续侧的排管根数"] = str(
                    strange_tube_result[0]
                )
                calc_results[
                    "'丁字'交叉沿水平隔板槽不连续侧管排1最两端管孔中心距"
                ] = str(strange_tube_result[2])
                calc_results["相邻隔板槽中心距"] = str(strange_tube_result[3])
            if need_two_rows:
                y_above = sorted(
                    set([y for x, y in editor.current_centers if 0 < y < getiao_chicun]),
                    reverse=True,
                )
                if len(y_above) >= 1:
                    selected_coords_cross.extend(
                        [(x, y) for x, y in editor.current_centers if abs(y - y_above[0]) < 1e-6]
                    )
                if len(y_above) >= 2:
                    selected_coords_cross.extend(
                        [(x, y) for x, y in editor.current_centers if abs(y - y_above[1]) < 1e-6]
                    )

                y_below = sorted(
                    set([y for x, y in editor.current_centers if -getiao_chicun < y < 0])
                )
                if len(y_below) >= 1:
                    selected_coords_cross.extend(
                        [(x, y) for x, y in editor.current_centers if abs(y - y_below[0]) < 1e-6]
                    )
                if len(y_below) >= 2:
                    selected_coords_cross.extend(
                        [(x, y) for x, y in editor.current_centers if abs(y - y_below[1]) < 1e-6]
                    )

                calc_results["'丁字'交叉沿水平隔板槽不连续侧的排管根数"] = len(
                    selected_coords_cross
                )

                def unique_sorted(values, tol=1e-6):
                    vals = sorted(values)
                    uniq = []
                    for v in vals:
                        if not uniq or abs(v - uniq[-1]) > tol:
                            uniq.append(v)
                    return uniq

                selected_coords_cross = []
                added = set()

                y_above_vals = [y for x, y in editor.current_centers if y > getiao_chicun]
                y_above = unique_sorted(y_above_vals)
                if len(y_above) >= 1:
                    target = y_above[0]
                    for x, y in editor.current_centers:
                        if abs(y - target) < 1e-6 and (x, y) not in added:
                            selected_coords_cross.append((x, y))
                            added.add((x, y))
                if len(y_above) >= 2:
                    target = y_above[1]
                    for x, y in editor.current_centers:
                        if abs(y - target) < 1e-6 and (x, y) not in added:
                            selected_coords_cross.append((x, y))
                            added.add((x, y))

                y_below_vals = [y for x, y in editor.current_centers if y < -getiao_chicun]
                y_below = unique_sorted(y_below_vals)
                if len(y_below) >= 1:
                    target = y_below[-1]
                    for x, y in editor.current_centers:
                        if abs(y - target) < 1e-6 and (x, y) not in added:
                            selected_coords_cross.append((x, y))
                            added.add((x, y))
                if len(y_below) >= 2:
                    target = y_below[-2]
                    for x, y in editor.current_centers:
                        if abs(y - target) < 1e-6 and (x, y) not in added:
                            selected_coords_cross.append((x, y))
                            added.add((x, y))

                calc_results["'丁字'交叉沿水平隔板槽连续侧的排管根数"] = len(
                    selected_coords_cross
                )
            if fenchengxingshi == "6.2":
                calc_results["'丁字'交叉沿水平隔板槽连续侧的排管根数"] = "0"
                calc_results["'丁字'交叉沿水平隔板槽不连续侧的排管根数"] = "0"
                calc_results[
                    "'十字'交叉沿水平隔板槽单侧管排1最两端管孔中心距"
                ] = calc_results[
                    "'丁字'交叉沿水平隔板槽不连续侧管排1最两端管孔中心距"
                ]
                calc_results[
                    "'丁字'交叉沿水平隔板槽不连续侧管排1最两端管孔中心距"
                ] = "0"
        except Exception:
            calc_results["'丁字'交叉沿水平隔板槽连续侧的排管根数"] = "0"
            calc_results["'丁字'交叉沿水平隔板槽不连续侧的排管根数"] = "0"
            calc_results[
                "'丁字'交叉沿水平隔板槽不连续侧管排1最两端管孔中心距"
            ] = "0"
            calc_results["相邻隔板槽中心距"] = "0.0"
    else:
        calc_results["相邻隔板槽中心距"] = str(round(getiao_chicun, 3))

    table_name = "`产品设计活动表_布管计算结果表`"
    sql_statements = []

    def escape_sql(value):
        if isinstance(value, str):
            return value.replace("'", "''")
        return str(value)

    delete_sql = (
        f"DELETE FROM {table_name} WHERE `产品ID` = '{escape_sql(product_id)}' AND `产品类型` = '1'"
    )
    sql_statements.append(delete_sql)

    for calc_name, calc_val in calc_results.items():
        esc_product_id = escape_sql(product_id)
        esc_calc_name = escape_sql(calc_name)
        esc_calc_val = escape_sql(calc_val)
        esc_product_type = "1"

        insert_sql = (
            f"INSERT INTO {table_name} (`产品ID`, `计算值名称`, `计算值`, `产品类型`) "
            f"VALUES ('{esc_product_id}', '{esc_calc_name}', '{esc_calc_val}', '{esc_product_type}')"
        )
        sql_statements.append(insert_sql)

    return sql_statements
