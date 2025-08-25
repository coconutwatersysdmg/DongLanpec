from PyQt5.QtWidgets import QMessageBox, QLabel, QComboBox
import pymysql
from modules.guankoudingyi.db_cnt import get_connection

db_config_2 = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '产品设计活动库'
}

def save_all_pipe_data(stats_widget):
    """
    保存表格中所有管口数据到数据库
    :param stats_widget: 主窗口实例
    """
    try:
        # 获取表格和产品ID
        table = stats_widget.tableWidget_pipe
        product_id = stats_widget.product_id

        # 连接数据库
        conn = get_connection(**db_config_2)
        cursor = conn.cursor()

        # ✅ 判断是否存在该产品ID对应的数据
        cursor.execute("SELECT COUNT(*) as count FROM 产品设计活动表_管口表 WHERE 产品ID = %s", (product_id,))
        existing_count = cursor.fetchone()['count']

        if existing_count > 0:
            # ✅ 如果有旧记录，先删除
            cursor.execute("DELETE FROM 产品设计活动表_管口表 WHERE 产品ID = %s", (product_id,))
            conn.commit()  # 删除后立即提交，避免后续操作影响

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

        # 遍历表格行（除了最后一行，因为最后一行是用于添加新数据的空行）
        for row in range(table.rowCount() - 1):
            # 获取管口代号（必需字段）
            port_code_item = table.item(row, 1)
            if not port_code_item or not port_code_item.text().strip():
                continue  # 跳过没有管口代号的行

            port_code = port_code_item.text().strip()
            insert_data = {}
            for col, field in column_map.items():
                item = table.item(row, col)
                if item and item.text().strip():
                    insert_data[field] = item.text().strip()

            if not insert_data:
                continue  # 如果没有数据要插入，跳过

            # 构造插入语句
            insert_data.pop("管口代号", None)  # ✅ 删除潜在重复字段
            fields = ['产品ID', '管口代号', '管口更改状态'] + list(insert_data.keys())
            values = [product_id, port_code, '已更改'] + list(insert_data.values())
            placeholders = ", ".join(["%s"] * len(fields))
            sql = f"""
                       INSERT INTO 产品设计活动表_管口表
                       (`{'`, `'.join(fields)}`)
                       VALUES ({placeholders})
                   """
            cursor.execute(sql, values)
        # 提交事务
        conn.commit()
        QMessageBox.information(stats_widget, "保存成功", "所有管口数据已成功保存到数据库")

    except Exception as e:
        if conn:
            conn.rollback()
        QMessageBox.critical(stats_widget, "保存失败", f"保存数据时出错：{str(e)}")

    finally:
        if cursor:
            cursor.close()
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
