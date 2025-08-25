from PyQt5.QtWidgets import QWidget, QTableWidget, QHBoxLayout, QLabel, QRadioButton, QButtonGroup
from PyQt5.QtCore import Qt

def huanreguanzhizaofangfa(table: QTableWidget, cursor, user_id, config_type):
    try:
        table.clear()
        table.setRowCount(2)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["配置选项"])
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        options = [
            "冷拔",
            "热轧"
        ]

        # 获取旧值
        cursor.execute("""
            SELECT value FROM user_config
            WHERE user_id = %s AND config_type = %s
        """, (user_id, config_type))
        result = cursor.fetchone()
        selected_value = result[0] if result else ""

        button_group = QButtonGroup(table)
        radio_buttons = []

        for i, option_text in enumerate(options):
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(10, 0, 0, 0)

            radio = QRadioButton(option_text)
            radio.setChecked(option_text == selected_value)

            layout.addWidget(radio)
            layout.addStretch()

            button_group.addButton(radio, i)
            radio_buttons.append(radio)

            table.setCellWidget(i, 0, widget)

        # 保存控件引用
        table._joint_factor_radios = radio_buttons
        table._joint_factor_group = button_group

        # 绑定保存按钮
        if not hasattr(table, '_save_connected_joint_factor'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_joint_factor(table, cursor.connection, user_id, config_type))
                table._save_connected_joint_factor = True
            else:
                print("[错误] 找不到 save_button")

    except Exception as e:
        print(f"[错误] 加载接头系数配置失败: {e}")


def save_joint_factor(table: QTableWidget, db_conn, user_id, config_type):
    try:
        radios = table._joint_factor_radios
        selected = next((rb.text() for rb in radios if rb.isChecked()), "")

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM user_config WHERE user_id = %s AND config_type = %s", (user_id, config_type))
        cursor.execute(
            "INSERT INTO user_config (user_id, config_type, value) VALUES (%s, %s, %s)",
            (user_id, config_type, selected)
        )
        db_conn.commit()
        cursor.close()

        print(f"[保存成功] {config_type}: {selected}")
    except Exception as e:
        print(f"[错误] 保存接头系数配置失败: {e}")
