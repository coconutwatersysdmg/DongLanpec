from PyQt5.QtWidgets import QTableWidgetItem, QTableWidget
from PyQt5.QtCore import Qt

def luowen_lagan_zhijing_config(table: QTableWidget, cursor, user_id):
    try:
        # 优先读取用户保存数据
        cursor.execute("SELECT * FROM 螺纹拉杆直径选用预定义用户表 WHERE user_id = %s", (user_id,))
        user_rows = cursor.fetchall()

        if user_rows:
            rows = [row[1:] for row in user_rows]  # 去掉 user_id
            cursor.execute("SHOW COLUMNS FROM 螺纹拉杆直径选用预定义表")
            col_names = [col[0] for col in cursor.fetchall()]
        else:
            cursor.execute("SELECT * FROM 螺纹拉杆直径选用预定义表")
            rows = cursor.fetchall()
            col_names = [desc[0] for desc in cursor.description]

        # 初始化表格
        table.clear()
        table.setColumnCount(len(col_names))
        table.setRowCount(len(rows))
        table.setHorizontalHeaderLabels(col_names)
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        for row_idx, row_data in enumerate(rows):
            for col_idx, val in enumerate(row_data):
                item = QTableWidgetItem(str(val))
                if col_idx >= 2:  # ✅ 从第三列开始可编辑
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                else:
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                table.setItem(row_idx, col_idx, item)

        table._luowen_lagan_colnames = col_names

        # 绑定保存按钮
        if not hasattr(table, "_save_connected_lwlgzj"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_luowen_lagan_zhijing_config(table, cursor.connection, user_id)
                )
                table._save_connected_lwlgzj = True

    except Exception as e:
        print(f"[错误] 加载螺纹拉杆直径配置失败: {e}")

def save_luowen_lagan_zhijing_config(table: QTableWidget, db_conn, user_id):
    try:
        col_names = table._luowen_lagan_colnames
        cursor = db_conn.cursor()

        # 清除旧记录
        cursor.execute("DELETE FROM 螺纹拉杆直径选用预定义用户表 WHERE user_id = %s", (user_id,))

        # 保存新记录
        for row_idx in range(table.rowCount()):
            values = []
            for col_idx in range(table.columnCount()):
                item = table.item(row_idx, col_idx)
                values.append(item.text().strip() if item else "")

            col_fields = ", ".join(["user_id"] + col_names)
            placeholders = ", ".join(["%s"] * (len(values) + 1))
            insert_sql = f"INSERT INTO 螺纹拉杆直径选用预定义用户表 ({col_fields}) VALUES ({placeholders})"
            cursor.execute(insert_sql, (user_id, *values))

        db_conn.commit()
        cursor.close()
        print("[保存成功] 螺纹拉杆直径用户表已更新")

    except Exception as e:
        print(f"[错误] 保存螺纹拉杆直径失败: {e}")
