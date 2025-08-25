from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem
from PyQt5.QtCore import Qt


def create_jingujian_guige_config(table: QTableWidget, cursor, user_id, config_type):
    try:
        # 获取预定义 value 列所有值
        cursor.execute("SELECT value FROM 容器法兰配套紧固件常用规格预定义表")
        values = [row[0] for row in cursor.fetchall() if row[0]]

        if not values:
            print("[警告] 表中无数据")
            return

        # 获取用户已有选择（value 字符串用分号分隔）
        cursor.execute("SELECT value FROM 容器法兰配套紧固件常用规格预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        selected_values = result[0].split(";") if result and result[0] else []

        # 设置表格结构
        table.clear()
        table.setColumnCount(2)
        table.setRowCount(len(values))
        table.setHorizontalHeaderLabels(["规格", "是否选中"])
        table.horizontalHeader().setStretchLastSection(True)

        for row_idx, val in enumerate(values):
            item_val = QTableWidgetItem(val)
            item_val.setFlags(Qt.ItemIsEnabled)  # 只读

            item_check = QTableWidgetItem("☑" if val in selected_values else "☐")
            item_check.setTextAlignment(Qt.AlignCenter)
            item_check.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)  # 可选可变

            table.setItem(row_idx, 0, item_val)
            table.setItem(row_idx, 1, item_check)

            # 最后一项加高显示
            if row_idx == len(values) - 1:
                table.setRowHeight(row_idx, 50)
            else:
                table.setRowHeight(row_idx, 35)

        table._jingujian_values = values

        # 保存按钮绑定
        if not hasattr(table, "_save_connected_jingujian"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_jingujian_guige_config(table, cursor.connection, user_id, config_type)
                )
                table._save_connected_jingujian = True

        # 添加点击切换状态（☑ <-> ☐）
        def toggle_check(row, col):
            if col == 1:
                item = table.item(row, col)
                if item.text() == "☑":
                    item.setText("☐")
                else:
                    item.setText("☑")

        table.cellClicked.connect(toggle_check)

    except Exception as e:
        print("[错误] 加载紧固件常用规格失败：", e)
def save_jingujian_guige_config(table: QTableWidget, db_conn, user_id, config_type):
    try:
        values = table._jingujian_values
        selected = []

        for row in range(table.rowCount()):
            check = table.item(row, 1)
            if check and check.text() == "☑":
                selected.append(values[row])

        value_str = ";".join(selected)

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 容器法兰配套紧固件常用规格预定义用户表 WHERE user_id = %s", (user_id,))
        cursor.execute("""
            INSERT INTO 容器法兰配套紧固件常用规格预定义用户表 (user_id, value)
            VALUES (%s, %s)
        """, (user_id, value_str))
        db_conn.commit()
        cursor.close()

        print(f"[保存成功] 规格已存：{value_str}")

    except Exception as e:
        print("[错误] 保存紧固件常用规格失败：", e)
