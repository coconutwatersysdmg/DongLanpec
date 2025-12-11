from PyQt5.QtWidgets import QTableWidgetItem, QHeaderView, QMessageBox
from PyQt5.QtCore import Qt


def handle_pipe_spec(table, cursor, user_id, config_type=None):
    try:
        # 1. 获取列信息
        cursor.execute("SELECT * FROM 常用管材规格预定义表")
        data = cursor.fetchall()
        column_names = [desc[0] for desc in cursor.description]

        table.blockSignals(True)
        table.clear()
        table.setRowCount(len(data))
        table.setColumnCount(len(column_names))
        table.setHorizontalHeaderLabels(column_names)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        # 2. 渲染内容 + 设置可编辑范围
        for row_idx, row_data in enumerate(data):
            for col_idx, col_name in enumerate(column_names):
                val = row_data[col_idx]
                display = str(val) if val is not None else ""
                item = QTableWidgetItem(display)

                if row_idx >= 1 and col_idx >= 4:
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)
                else:
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

                table.setItem(row_idx, col_idx, item)

        table.blockSignals(False)

        print("[加载成功] 常用管材规格预定义表")

        # 3. 绑定保存按钮逻辑
        if not hasattr(table, '_save_connected'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_pipe_spec_to_user(table, cursor.connection, user_id)
                )
                table._save_connected = True
            else:
                print("[错误] 找不到 save_button")

    except Exception as e:
        print(f"[错误] 加载管材规格失败: {e}")


def save_pipe_spec_to_user(table, db_conn, user_id):
    try:
        column_names = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
        cursor = db_conn.cursor()

        # 删除旧记录
        cursor.execute("DELETE FROM 常用管材规格预定义用户表 WHERE user_id = %s", (user_id,))

        # 遍历所有行并插入
        for row in range(table.rowCount()):
            row_values = []
            for col in range(table.columnCount()):
                item = table.item(row, col)
                row_values.append(item.text() if item else "")

            # 构造 SQL，注意字段名从 col_0 开始（不包含 row_idx）
            sql = f"""
                INSERT INTO 常用管材规格预定义用户表
                (user_id, {', '.join(column_names)})
                VALUES (%s, {', '.join(['%s'] * len(column_names))})
            """
            cursor.execute(sql, (user_id, *row_values))

        db_conn.commit()
        cursor.close()

        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.information(table, "保存成功", "常用管材规格用户配置保存成功。")
        print("[保存成功] 管材规格预定义用户表已写入")

    except Exception as e:
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.critical(table, "保存失败", f"保存失败: {e}")
        print(f"[错误] 保存失败: {e}")
