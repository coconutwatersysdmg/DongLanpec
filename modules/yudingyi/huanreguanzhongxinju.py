from PyQt5.QtWidgets import QTableWidgetItem, QTableWidget
from PyQt5.QtCore import Qt

def huanreqi_zhongxinju_config(table: QTableWidget, cursor, user_id):
    try:
        # 查询原始数据
        cursor.execute("SELECT * FROM 换热管中心距预定义表")
        default_rows = cursor.fetchall()
        col_names = [desc[0] for desc in cursor.description]

        # 查询用户数据
        cursor.execute("SELECT * FROM 换热管中心距预定义用户表 WHERE user_id = %s", (user_id,))
        user_rows = cursor.fetchall()
        use_user_data = bool(user_rows)

        # 决定数据来源
        rows = user_rows if use_user_data else default_rows

        # 如果使用用户数据，剔除 user_id 列
        if use_user_data:
            col_names = [desc[0] for desc in cursor.description if desc[0] != "user_id"]
            start_col = 1  # 假设 user_id 是第一个字段
        else:
            start_col = 0

        table.clear()
        table.setColumnCount(len(col_names))
        table.setRowCount(len(rows))
        table.setHorizontalHeaderLabels(col_names)
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        for row_idx, row_data in enumerate(rows):
            for col_idx, col_name in enumerate(col_names):
                val = row_data[col_idx + start_col] if use_user_data else row_data[col_idx]
                item = QTableWidgetItem(str(val))
                if row_idx > 0 and col_idx >= 1:
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                else:
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                table.setItem(row_idx, col_idx, item)

        table._hrg_colnames = col_names

        if not hasattr(table, "_save_connected_hrg"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_huanreqi_zhongxinju(table, cursor.connection, user_id)
                )
                table._save_connected_hrg = True

    except Exception as e:
        print(f"[错误] 加载换热管中心距配置失败: {e}")
def save_huanreqi_zhongxinju(table: QTableWidget, db_conn, user_id):
    try:
        col_names = table._hrg_colnames
        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 换热管中心距预定义用户表 WHERE user_id = %s", (user_id,))

        for row_idx in range(table.rowCount()):
            values = []
            for col_idx in range(table.columnCount()):
                item = table.item(row_idx, col_idx)
                values.append(item.text().strip() if item else "")
            insert_sql = f"""
                INSERT INTO 换热管中心距预定义用户表 (user_id, {', '.join(col_names)})
                VALUES (%s, {', '.join(['%s'] * len(col_names))})
            """
            cursor.execute(insert_sql, (user_id, *values))

        db_conn.commit()
        cursor.close()
        print("[保存成功] 换热管中心距用户表已更新")
    except Exception as e:
        print(f"[错误] 保存换热管中心距配置失败: {e}")
