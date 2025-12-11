from PyQt5.QtWidgets import QCheckBox, QLabel, QHBoxLayout, QWidget, QTableWidget

def bql_not_reinforce_config(table: QTableWidget, cursor, user_id):
    try:
        value_str = "当壳体开孔满足GB/T 150.3-6.1.3条款全部要求时，不另行补强。"

        # 查询是否已保存
        cursor.execute("SELECT value FROM 不另行补强预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        selected = result is not None and result[0] == value_str

        table.clear()
        table.setRowCount(1)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["不另行补强"])
        table.verticalHeader().setDefaultSectionSize(60)
        table.horizontalHeader().setStretchLastSection(True)

        checkbox = QCheckBox()
        checkbox.setChecked(selected)
        label = QLabel(value_str)

        layout = QHBoxLayout()
        layout.setContentsMargins(10, 0, 10, 0)
        layout.addWidget(checkbox)
        layout.addWidget(label)
        layout.addStretch()

        container = QWidget()
        container.setLayout(layout)
        table.setCellWidget(0, 0, container)

        # 保存引用
        table._bql_checkbox = checkbox
        table._bql_value = value_str

        if not hasattr(table, '_save_connected_bql'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_bql_not_reinforce(table, cursor.connection, user_id)
                )
                table._save_connected_bql = True

    except Exception as e:
        print(f"[错误] 加载不另行补强配置失败: {e}")


def save_bql_not_reinforce(table: QTableWidget, db_conn, user_id):
    try:
        checkbox = table._bql_checkbox
        value_str = table._bql_value

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 不另行补强预定义用户表 WHERE user_id = %s", (user_id,))

        if checkbox.isChecked():
            cursor.execute(
                "INSERT INTO 不另行补强预定义用户表 (user_id, value) VALUES (%s, %s)",
                (user_id, value_str)
            )

        db_conn.commit()
        cursor.close()
        print(f"[保存成功] 用户 {user_id} 的不另行补强配置已更新")
    except Exception as e:
        print(f"[错误] 保存不另行补强配置失败: {e}")
