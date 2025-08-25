from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem


def create_rongqifalanxingshi_config(table: QTableWidget, cursor, user_id, config_type):
    try:
        # 读取预定义表所有数据
        cursor.execute("SELECT * FROM 容器法兰形式选择预定义表")
        rows = cursor.fetchall()
        col_names = [desc[0] for desc in cursor.description]

        table.clear()
        table.setColumnCount(len(col_names))
        table.setRowCount(len(rows))
        table.setHorizontalHeaderLabels(col_names)
        table.horizontalHeader().setStretchLastSection(True)

        table._falan_rows = []  # 保存所有单元格值（用于保存）

        for row_idx, row_data in enumerate(rows):
            row_cells = []
            for col_idx, cell_value in enumerate(row_data):
                item = QTableWidgetItem(str(cell_value))
                if row_idx == 0:
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                table.setItem(row_idx, col_idx, item)
                row_cells.append(item)
            table._falan_rows.append(row_cells)

        # 保存按钮绑定
        if not hasattr(table, "_save_connected_falanxingshi"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_rongqifalanxingshi_config(table, cursor.connection, user_id, config_type)
                )
                table._save_connected_falanxingshi = True

    except Exception as e:
        print("[错误] 加载容器法兰形式配置失败：", e)
def save_rongqifalanxingshi_config(table: QTableWidget, db_conn, user_id, config_type):
    try:
        cursor = db_conn.cursor()

        # 删除旧数据
        cursor.execute("DELETE FROM 容器法兰形式选择预定义用户表 WHERE user_id = %s", (user_id,))

        # 构造字段名：不包括 id，只包括 col_0 ~ col_15 和 user_id
        data_columns = [f"col_{i}" for i in range(16)]
        all_columns = data_columns + ['user_id']  # 注意 user_id 放最后（符合字段顺序）

        col_part = ", ".join(f"`{col}`" for col in all_columns)
        placeholders = ", ".join(["%s"] * len(all_columns))

        for row in range(table.rowCount()):
            values = []
            for col in range(len(data_columns)):
                item = table.item(row, col)
                values.append(item.text() if item else "")
            values.append(user_id)  # user_id 是最后一列

            if len(values) != len(all_columns):
                print(f"[错误] 第 {row} 行列数不匹配，应为 {len(all_columns)}，实际为 {len(values)}")
                continue

            cursor.execute(
                f"INSERT INTO 容器法兰形式选择预定义用户表 ({col_part}) VALUES ({placeholders})",
                values
            )

        db_conn.commit()
        cursor.close()
        print(f"[保存成功] 容器法兰形式配置（共 {table.rowCount()} 行）")

    except Exception as e:
        print("[错误] 保存容器法兰形式配置失败：", e)
