from PyQt5.QtWidgets import QMessageBox, QLabel, QComboBox
import pymysql
from modules.guankoudingyi.db_cnt import get_connection, db_config_2
from modules.guankoudingyi.funcs.funcs_pipe_table import ensure_hidden_maps, get_next_pipe_id_runtime

def save_all_pipe_data(stats_widget):
    """
    保存策略：
    - 对每一行（除最后空行）：
        * 必须有 管口代号
        * 取隐藏 管口ID；若无（极端情况），运行期分配一个
        * 对 产品设计活动表_管口表 做 INSERT ... ON DUPLICATE KEY UPDATE
        * 同步对 产品设计活动表_管口类别表 做 INSERT ... ON DUPLICATE KEY UPDATE（四项：产品ID、管口ID、管口代号、管口所属元件）
    - 对 stats_widget.deleted_pipe_ids ：逐个 DELETE WHERE 产品ID AND 管口ID（同时删除两张表里的对应记录）
    """
    ensure_hidden_maps(stats_widget)
    # 获取表格和产品ID
    table = stats_widget.tableWidget_pipe
    product_id = stats_widget.product_id
    if not product_id:
        QMessageBox.warning(stats_widget, "错误", "产品ID不能为空")
        return

    # 定义列映射
    column_map = {
        1: "管口代号",
        2: "管口功能",
        3: "管口用途",
        4: "公称尺寸",
        5: "法兰标准",
        6: "压力等级",
        7: "法兰型式",
        8: "密封面型式",
        9: "焊端规格",
        10: "管口所属元件",
        11: "轴向定位基准",
        12: "轴向定位距离",
        13: "轴向夹角（°）",
        14: "周向方位（°）",
        15: "偏心距",
        16: "外伸高度",
        17: "管口附件",
        18: "管口载荷"
    }

    conn = None
    cur = None
    try:
        conn = get_connection(**db_config_2)
        cur = conn.cursor(pymysql.cursors.DictCursor)

        # —— 1) 先处理延迟删除 ——
        for hid in list(stats_widget.deleted_pipe_ids):
            # 管口表
            cur.execute("""
                DELETE FROM 产品设计活动表_管口表
                WHERE 产品ID=%s AND 管口ID=%s
            """, (product_id, hid))
            # 管口类别表（新增）
            cur.execute("""
                DELETE FROM 产品设计活动表_管口类别表
                WHERE 产品ID=%s AND 管口ID=%s
            """, (product_id, hid))
        stats_widget.deleted_pipe_ids.clear()

        # —— 2) 逐行 Upsert（新增/修改）——
        last_row = table.rowCount() - 1
        for row in range(last_row):  # 排除最后空行
            code_item = table.item(row, 1)
            port_code = code_item.text().strip() if code_item else ""
            if not port_code:
                continue

            # 收集行数据
            row_data = {}
            for col, field in column_map.items():
                it = table.item(row, col)
                txt = it.text().strip() if it else ""
                if txt != "":
                    row_data[field] = txt

            # 获取/兜底分配 管口ID（运行期分配，确认时才落库）
            hid = stats_widget.row_hidden_pipe_id.get(row)
            if not hid:
                hid = get_next_pipe_id_runtime(stats_widget, product_id)
                stats_widget.row_hidden_pipe_id[row] = hid  # 写回运行期映射

            # —— 2.1 写 "产品设计活动表_管口表"
            row_data.pop("管口代号", None)  # ✅ 删除潜在重复字段
            fields = ["产品ID", "管口ID", "管口代号", "管口更改状态"] + list(row_data.keys())
            values = [product_id, hid, port_code, "已更改"] + list(row_data.values())
            placeholders = ", ".join(["%s"] * len(fields))
            set_clause = ", ".join([f"`{k}`=VALUES(`{k}`)" for k in row_data.keys()] + [
                "`管口代号`=VALUES(`管口代号`)", "`管口更改状态`='已更改'"
            ])

            sql = f"""
                    INSERT INTO 产品设计活动表_管口表 (`{'`, `'.join(fields)}`)
                    VALUES ({placeholders})
                    ON DUPLICATE KEY UPDATE {set_clause}
                """
            cur.execute(sql, values)

            # —— 2.2 同步写 "产品设计活动表_管口类别表"（四列）
            # 获取管口所属元件
            component = row_data.get("管口所属元件", "")
            cur.execute("""
                INSERT INTO 产品设计活动表_管口类别表 (`产品ID`, `管口ID`, `管口代号`, `管口所属元件`)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE `管口代号`=VALUES(`管口代号`), `管口所属元件`=VALUES(`管口所属元件`)
            """, (product_id, hid, port_code, component))

        conn.commit()
        QMessageBox.information(stats_widget, "保存成功", "保存成功。")
    except Exception as e:
        if conn:
            conn.rollback()
        QMessageBox.critical(stats_widget, "保存失败", f"保存数据时出错：{e}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_type_selections_from_table_header(stats_widget):
    """
    从表头获取类型选择数据
    :param stats_widget: Stats类实例（更改参数类型以便访问comboBox组件）
    :return: 类型选择字典
    """
    type_selections = {}
    
    # ✅ 使用新的组件命名，不再使用findChild方式
    combo_mapping = [
        (stats_widget.combo_nominal_size_type, "公称尺寸类型"),
        (stats_widget.combo_pressure_level_type, "公称压力类型"),
        (stats_widget.combo_weld_end_spec_type, "焊端规格类型")
    ]
    
    for combo, db_field_name in combo_mapping:
        if combo is not None:
            selected_value = combo.currentText()
            type_selections[db_field_name] = selected_value
    
    return type_selections

def save_pipe_type_selection(stats_widget):
    """
    保存选中的公称尺寸类型、公称压力类型、焊端规格类型到数据库
    :param stats_widget: 主窗口实例
    """
    conn = None
    cursor = None
    
    try:
        # 验证产品ID
        product_id = stats_widget.product_id
        if not product_id:
            QMessageBox.warning(stats_widget, "错误", "产品ID不能为空")
            return False

        # 获取类型选择数据
        type_selections = get_type_selections_from_table_header(stats_widget)
        
        # 验证必需字段
        required_fields = ["公称尺寸类型", "公称压力类型", "焊端规格类型"]
        missing_fields = [field for field in required_fields if field not in type_selections]
        if missing_fields:
            QMessageBox.warning(stats_widget, "错误", f"未能获取到以下字段的选择值：{', '.join(missing_fields)}")
            return False

        # 数据库操作
        conn = get_connection(**db_config_2)
        cursor = conn.cursor()

        # 这里使用删除再插入的方式确保数据一致性
        cursor.execute("DELETE FROM 产品设计活动表_管口类型选择表 WHERE 产品ID = %s", (product_id,))
        
        sql = """
            INSERT INTO 产品设计活动表_管口类型选择表 
            (产品ID, 公称尺寸类型, 公称压力类型, 焊端规格类型) 
            VALUES (%s, %s, %s, %s)
        """
        values = (
            product_id,
            type_selections["公称尺寸类型"],
            type_selections["公称压力类型"], 
            type_selections["焊端规格类型"]
        )
        cursor.execute(sql, values)
        conn.commit()
        
        return True

    except Exception as e:
        if conn:
            conn.rollback()
        QMessageBox.critical(stats_widget, "保存失败", f"保存管口类型选择时出错：{str(e)}")
        return False

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def save_all_data_combined(stats_widget):
    """
    保存所有数据的组合方法：先保存管口类型选择，再保存管口数据
    :param stats_widget: 主窗口实例
    """
    # 先保存管口类型选择
    if save_pipe_type_selection(stats_widget):
        # 再保存管口数据
        save_all_pipe_data(stats_widget)

def connect_save_button(stats_widget):
    """
    连接确认按钮的点击事件
    :param stats_widget: 主窗口实例
    """
    stats_widget.pushButton_affirm.clicked.connect(lambda: save_all_data_combined(stats_widget))
