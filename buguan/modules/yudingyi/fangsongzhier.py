from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem


def fangsong_zhier_config(table: QTableWidget, cursor, user_id):
    try:
        # 获取原始预定义表数据
        cursor.execute("SELECT * FROM 防松支耳预定义表")
        rows = cursor.fetchall()
        col_names = [desc[0] for desc in cursor.description]

        # 获取用户自定义数据
        cursor.execute("SELECT * FROM 防松支耳预定义用户表 WHERE user_id = %s", (user_id,))
        user_rows = cursor.fetchall()
        use_user_data = bool(user_rows)

        table.clear()
        table.setColumnCount(len(col_names))
        table.setRowCount(len(rows))
        table.setHorizontalHeaderLabels(col_names)
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        data = user_rows if use_user_data else rows

        for row_idx, row_data in enumerate(data):
            for col_idx, val in enumerate(row_data):
                item = QTableWidgetItem(str(val))
                if row_idx >= 1 and col_idx >= 2:
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                else:
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                table.setItem(row_idx, col_idx, item)

        table._fangsong_colnames = col_names

        if not hasattr(table, "_save_connected_fangsong"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(lambda: save_fangsong_zhier_config(table, cursor.connection, user_id))
                table._save_connected_fangsong = True

    except Exception as e:
        print(f"[错误] 加载防松支耳配置失败: {e}")

def save_fangsong_zhier_config(table: QTableWidget, db_conn, user_id):
    try:
        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 防松支耳预定义用户表 WHERE user_id = %s", (user_id,))

        for row in range(table.rowCount()):
            values = [table.item(row, col).text().strip() if table.item(row, col) else "" for col in range(table.columnCount())]
            placeholders = ", ".join(["%s"] * (len(values) + 1))
            columns = ", ".join(["user_id"] + table._fangsong_colnames)
            cursor.execute(f"INSERT INTO 防松支耳预定义用户表 ({columns}) VALUES ({placeholders})", (user_id, *values))

        db_conn.commit()
        cursor.close()
        print("[保存成功] 防松支耳配置已更新")

    except Exception as e:
        print(f"[错误] 保存防松支耳配置失败: {e}")
