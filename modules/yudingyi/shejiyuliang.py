from PyQt5.QtWidgets import QTableWidget, QLabel, QTableWidgetItem, QMessageBox, QCheckBox
from PyQt5.QtCore import Qt

def shejiyuliang(table: QTableWidget, cursor, user_id, config_type):
    try:
        cursor.execute("SELECT * FROM 设计余量预定义表")
        rows = cursor.fetchall()
        headers = [desc[0] for desc in cursor.description]

        table.clear()
        table.setRowCount(len(rows))
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)

        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                if r >= 4 and c >= 2:
                    item = QTableWidgetItem(str(val))
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    table.setItem(r, c, item)  # ✅ 这行是必须的

                elif r >= 4 and c == 1 and row[0] == "容器法兰":
                    checkbox = QCheckBox(str(val))
                    checkbox.setChecked(False)
                    checkbox.setAlignment(Qt.AlignCenter)
                    table.setCellWidget(r, c, checkbox)
                else:
                    item = QTableWidgetItem(str(val))
                    item.setFlags(Qt.ItemIsEnabled)
                    table.setItem(r, c, item)

        table._headers = headers
        table._full_data = rows

        if not hasattr(table, '_save_connected_yuliang'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_shejiyuliang(table, cursor.connection, user_id, config_type))
                table._save_connected_yuliang = True
    except Exception as e:
        print(f"[错误] 加载设计余量失败: {e}")

def save_shejiyuliang(table: QTableWidget, db_conn, user_id, config_type):
    try:
        headers = getattr(table, '_headers', [])
        if not headers:
            QMessageBox.warning(table, "保存失败", "表头缺失")
            return

        row_count = table.rowCount()
        col_count = table.columnCount()

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 设计余量预定义用户表 WHERE user_id=%s", (user_id,))

        quoted_headers = [f"`{h}`" for h in headers]
        insert_sql = f"""
            INSERT INTO 设计余量预定义用户表 ({', '.join(quoted_headers)}, user_id)
            VALUES ({', '.join(['%s'] * col_count)}, %s)
        """

        for row in range(row_count):
            row_data = []
            row_skip = False
            for col in range(col_count):
                widget = table.cellWidget(row, col)
                item = table.item(row, col)

                if row >= 4 and table.item(row, 0) and table.item(row, 0).text() == "容器法兰" and col == 1:
                    # 容器法兰，col_1 为 QCheckBox
                    if isinstance(widget, QCheckBox):
                        if not widget.isChecked():
                            row_skip = True
                            break
                        row_data.append(widget.text())
                    else:
                        row_data.append("")
                elif isinstance(widget, QCheckBox):
                    row_data.append(widget.text())
                elif item:
                    row_data.append(item.text())
                else:
                    row_data.append("")

            if not row_skip:
                cursor.execute(insert_sql, row_data + [user_id])

        db_conn.commit()
        cursor.close()
        print(f"[保存成功] 已保存至设计余量预定义用户表（user_id={user_id}）")
    except Exception as e:
        print(f"[错误] 保存失败: {e}")
