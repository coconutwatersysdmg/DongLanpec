from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem, QCheckBox, QWidget, QHBoxLayout, QRadioButton


def zhichibanzengliang_config(table: QTableWidget, cursor, user_id):
    try:
        # 判断是否之前存储过 col_0（语句）或表格值
        cursor.execute("SELECT col_0 FROM 支持板增量用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        use_statement = bool(result)  # ✅ 默认根据数据库恢复选择

        table.clear()
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["支持板设置规则"])
        table.verticalHeader().setDefaultSectionSize(50)
        table.horizontalHeader().setStretchLastSection(True)

        # ✅ 创建切换选择按钮
        selector = QWidget()
        layout = QHBoxLayout(selector)
        layout.setContentsMargins(10, 0, 10, 0)
        rb1 = QRadioButton("使用语句：支持板和折流板始终厚度相等")
        rb2 = QRadioButton("使用支持板增量表")
        rb1.setChecked(use_statement)
        rb2.setChecked(not use_statement)
        layout.addWidget(rb1)
        layout.addWidget(rb2)
        layout.addStretch()

        table.setRowCount(1)
        table.setCellWidget(0, 0, selector)

        def reload_config():
            # 先清空所有非第0行的数据行和内容
            for row in range(1, table.rowCount()):
                table.removeRow(1)  # 每次都删第二行，因为删了后行数会变

            if rb1.isChecked():
                # ➤ 模式一：语句模式
                cb = QCheckBox("最后一块设置支持板时，支持板和折流板始终厚度相等。")
                cb.setChecked(True)
                row = QWidget()
                h = QHBoxLayout(row)
                h.setContentsMargins(10, 0, 10, 0)
                h.addWidget(cb)
                h.addStretch()
                table.insertRow(1)
                table.setCellWidget(1, 0, row)
                table._zhichengban_cb = cb
                table._zhichengban_choice = True
            else:
                # ➤ 模式二：表格模式
                cursor.execute("SELECT * FROM 支持板增量表")
                rows = cursor.fetchall()
                col_names = [desc[0] for desc in cursor.description]

                table.setColumnCount(len(col_names) - 1)
                table.setHorizontalHeaderLabels(col_names[1:])
                table.setRowCount(len(rows) + 1)  # +1 是因为第0行为radio

                for row_idx, row_data in enumerate(rows):
                    for col_idx in range(1, len(col_names)):  # 跳过 ID
                        item = QTableWidgetItem(str(row_data[col_idx]))
                        if row_idx == 1 and 1 <= col_idx <= 5:
                            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                        else:
                            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                        table.setItem(row_idx + 1, col_idx - 1, item)

                table._zhichengban_table_cols = col_names[1:]
                table._zhichengban_choice = False

        rb1.toggled.connect(reload_config)
        reload_config()

        if not hasattr(table, "_save_connected_zhichengban"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(lambda: save_zhichengban_config(table, cursor.connection, user_id))
                table._save_connected_zhichengban = True

    except Exception as e:
        print(f"[错误] 加载支持板配置失败: {e}")

def save_zhichengban_config(table: QTableWidget, db_conn, user_id):
    try:
        cursor = db_conn.cursor()
        if getattr(table, "_zhichengban_choice", True):
            # 保存第一种方式
            cb = table._zhichengban_cb
            if cb and cb.isChecked():
                value = cb.text()
                cursor.execute("DELETE FROM 支持板增量用户表 WHERE user_id = %s", (user_id,))
                cursor.execute("INSERT INTO 支持板增量用户表 (user_id, col_0) VALUES (%s, %s)", (user_id, value))
        else:
            # 保存第二种方式（表格数据）
            cursor.execute("DELETE FROM 支持板增量用户表 WHERE user_id = %s", (user_id,))
            for row in range(table.rowCount()):
                # ✅ 判断整行是否为空
                is_empty = True
                for col in range(table.columnCount()):
                    item = table.item(row, col)
                    if item and item.text().strip():
                        is_empty = False
                        break
                if is_empty:
                    continue

                values = []
                for col in range(table.columnCount()):
                    item = table.item(row, col)
                    values.append(item.text().strip() if item else "")

                columns = ", ".join(["user_id"] + table._zhichengban_table_cols)
                placeholders = ", ".join(["%s"] * (len(values) + 1))
                cursor.execute(f"INSERT INTO 支持板增量用户表 ({columns}) VALUES ({placeholders})", (user_id, *values))

        db_conn.commit()
        cursor.close()
        print("[保存成功] 支持板配置已更新")
    except Exception as e:
        print(f"[错误] 保存支持板配置失败: {e}")
