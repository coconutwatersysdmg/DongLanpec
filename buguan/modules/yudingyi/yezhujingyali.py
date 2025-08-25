from PyQt5.QtWidgets import QTableWidget, QWidget, QCheckBox, QHBoxLayout, QMessageBox

def yezhujingyali(table: QTableWidget, cursor, user_id, config_type):
    try:
        table.clear()
        table.setRowCount(1)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(['配置内容'])

        checked = False
        default_sentence = "当液柱静压力小于设计压力的5%时，仍然计入。"

        # 查询旧值是否存在
        cursor.execute("SELECT value FROM user_config WHERE user_id=%s AND config_type=%s", (user_id, config_type))
        result = cursor.fetchone()
        if result and default_sentence in result[0]:
            checked = True

        # 创建可选项
        row_widget = QWidget()
        layout = QHBoxLayout(row_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        checkbox = QCheckBox(default_sentence)
        checkbox.setChecked(checked)
        layout.addWidget(checkbox)
        layout.addStretch()

        table.setCellWidget(0, 0, row_widget)

        # 保存引用
        table._checkbox_yzjy = checkbox

        # 保存按钮绑定
        if not hasattr(table, '_save_connected_yzjy'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_yzjy_optional(table, cursor.connection, user_id, config_type))
                table._save_connected_yzjy = True

    except Exception as e:
        print(f"[错误] 加载液柱静压力配置失败: {e}")

def save_yzjy_optional(table: QTableWidget, db_conn, user_id, config_type):
    try:
        checkbox = table._checkbox_yzjy
        sentence = "当液柱静压力小于设计压力的5%时，仍然计入。"

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM user_config WHERE user_id=%s AND config_type=%s", (user_id, config_type))

        if checkbox.isChecked():
            cursor.execute("INSERT INTO user_config (user_id, config_type, value) VALUES (%s, %s, %s)",
                           (user_id, config_type, sentence))
            print(f"[保存成功] {config_type}: {sentence}")
        else:
            print(f"[保存成功] 未勾选，清除 {config_type} 配置")

        db_conn.commit()
        cursor.close()

    except Exception as e:
        print(f"[错误] 保存液柱静压力配置失败: {e}")
