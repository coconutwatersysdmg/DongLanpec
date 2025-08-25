from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTableWidgetItem, QMessageBox

def yuantong_min_thickness_editor(table, cursor, user_id, config_type):
    try:
        cursor.execute("SELECT * FROM 自定义圆筒最小厚度默认预定义表")
        rows = cursor.fetchall()
        headers = [desc[0] for desc in cursor.description]

        row_count = len(rows)
        col_count = len(headers)

        table.clear()
        table.setRowCount(row_count)
        table.setColumnCount(col_count)
        table.setHorizontalHeaderLabels(headers)

        for row_idx, row in enumerate(rows):
            for col_idx, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                if not (2 <= row_idx <= 11 and 2 <= col_idx <= 4):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                table.setItem(row_idx, col_idx, item)

        table._min_thickness_editing_rows = list(range(2, 12))
        table._min_thickness_editing_cols = list(range(2, 5))
        table._min_thickness_user_id = user_id
        table._min_thickness_config_type = config_type

        if not hasattr(table, '_save_connected_minthick'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(lambda: save_yuantong_min_thickness(table, cursor.connection))
                table._save_connected_minthick = True

    except Exception as e:
        print(f"[错误] 加载圆筒最小厚度表失败: {e}")

def save_yuantong_min_thickness(table, db_conn):
    try:
        user_id = table._min_thickness_user_id
        all_rows = list(range(table.rowCount()))  # 包括前两行
        cursor = db_conn.cursor()

        # 清除用户原有记录
        cursor.execute("DELETE FROM 自定义圆筒最小厚度预定义用户表 WHERE user_id = %s", (user_id,))

        for row_idx in all_rows:
            row_values = []
            for col_idx in range(5):  # col_0 ~ col_4
                item = table.item(row_idx, col_idx)
                value = item.text() if item else ''
                row_values.append(value)

            # 插入完整记录（包含前两行）
            cursor.execute("""
                INSERT INTO 自定义圆筒最小厚度预定义用户表 
                (user_id, row_idx, col_0, col_1, col_2, col_3, col_4)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (user_id, row_idx, *row_values))

        db_conn.commit()
        cursor.close()
        print(f"[保存成功] 用户 {user_id} 的最小厚度表共保存 {len(all_rows)} 行")

    except Exception as e:
        print(f"[错误] 保存圆筒最小厚度失败: {e}")
        QMessageBox.critical(table, "保存失败", f"保存失败: {e}")

