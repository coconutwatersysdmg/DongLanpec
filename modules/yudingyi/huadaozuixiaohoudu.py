from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem


def huadaohoudu_config(table: QTableWidget, cursor, user_id):
    try:
        # 优先读取用户表
        cursor.execute("SELECT * FROM 滑道最小厚度预定义用户表 WHERE user_id = %s", (user_id,))
        user_rows = cursor.fetchall()

        if user_rows:
            rows = user_rows
            col_names = [desc[0] for desc in cursor.description][1:]  # 去除 user_id 列
            start_col = 1  # 跳过 user_id
        else:
            cursor.execute("SELECT * FROM 滑道最小厚度预定义表")
            rows = cursor.fetchall()
            col_names = [desc[0] for desc in cursor.description]
            start_col = 0

        table.clear()
        table.setColumnCount(len(col_names))
        table.setRowCount(len(rows))
        table.setHorizontalHeaderLabels(col_names)
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        for row_idx, row_data in enumerate(rows):
            for col_idx in range(len(col_names)):
                val = row_data[col_idx + start_col] if start_col == 1 else row_data[col_idx]
                item = QTableWidgetItem(str(val))
                if row_idx >= 1 and (
                        (start_col == 1 and col_idx == 1) or
                        (start_col == 0 and col_idx == 2)
                ):
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                else:
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                table.setItem(row_idx, col_idx, item)

        if start_col == 1:
            table.setColumnHidden(table.columnCount() - 1, True)

        table._huadao_min_thickness_colnames = col_names
        table._huadao_min_thickness_rows = rows

        if not hasattr(table, "_save_connected_huadao_min_thickness"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_huadao_min_thickness_config(table, cursor.connection, user_id)
                )
                table._save_connected_huadao_min_thickness = True

    except Exception as e:
        print(f"[错误] 加载滑道最小厚度配置失败: {e}")

def save_huadao_min_thickness_config(table: QTableWidget, db_conn, user_id):
    try:
        col_names = table._huadao_min_thickness_colnames
        cursor = db_conn.cursor()

        cursor.execute("DELETE FROM 滑道最小厚度预定义用户表 WHERE user_id = %s", (user_id,))

        for row_idx in range(table.rowCount()):
            values = []
            for col_idx in range(table.columnCount()):
                item = table.item(row_idx, col_idx)
                values.append(item.text().strip() if item else "")

            col_fields = ", ".join(["user_id"] + col_names)
            placeholders = ", ".join(["%s"] * (len(col_names) + 1))
            insert_sql = f"INSERT INTO 滑道最小厚度预定义用户表 ({col_fields}) VALUES ({placeholders})"
            cursor.execute(insert_sql, (user_id, *values))

        db_conn.commit()
        cursor.close()
        print("[保存成功] 滑道最小厚度配置已更新")

    except Exception as e:
        print(f"[错误] 保存滑道最小厚度配置失败: {e}")
