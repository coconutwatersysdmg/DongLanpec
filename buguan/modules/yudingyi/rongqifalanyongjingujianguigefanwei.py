from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem


def create_rongqifalanjingujian_config(table: QTableWidget, cursor, user_id, config_type):
    try:
        cursor.execute("SELECT * FROM 容器法兰用紧固件规格范围选用表")
        rows = cursor.fetchall()
        col_names = [desc[0] for desc in cursor.description]

        table.clear()
        table.setColumnCount(len(col_names))
        table.setRowCount(len(rows))
        table.setHorizontalHeaderLabels(col_names)
        table.horizontalHeader().setStretchLastSection(True)

        table._jingujian_rows = []

        for row_idx, row_data in enumerate(rows):
            row_cells = []
            for col_idx, cell_value in enumerate(row_data):
                item = QTableWidgetItem(str(cell_value))
                item.setFlags(item.flags() | Qt.ItemIsEditable)  # 所有值都可编辑
                table.setItem(row_idx, col_idx, item)
                row_cells.append(item)
            table._jingujian_rows.append(row_cells)

        if not hasattr(table, "_save_connected_jingujian"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_rongqifalanjingujian_config(table, cursor.connection, user_id, config_type)
                )
                table._save_connected_jingujian = True

    except Exception as e:
        print("[错误] 加载容器法兰紧固件配置失败：", e)
def save_rongqifalanjingujian_config(table: QTableWidget, db_conn, user_id, config_type):
    try:
        cursor = db_conn.cursor()

        cursor.execute("DELETE FROM 容器法兰用紧固件规格范围选用用户表 WHERE user_id = %s", (user_id,))

        col_names = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
        col_names.append('user_id')

        col_part = ", ".join(f"`{col}`" for col in col_names)
        placeholders = ", ".join(["%s"] * len(col_names))

        for row in range(table.rowCount()):
            values = []
            for col in range(table.columnCount()):
                item = table.item(row, col)
                values.append(item.text() if item else "")
            values.append(user_id)

            cursor.execute(f"INSERT INTO 容器法兰用紧固件规格范围选用用户表 ({col_part}) VALUES ({placeholders})", values)

        db_conn.commit()
        cursor.close()
        print(f"[保存成功] 容器法兰用紧固件规格配置（共 {table.rowCount()} 行）")

    except Exception as e:
        print("[错误] 保存容器法兰用紧固件规格配置失败：", e)
