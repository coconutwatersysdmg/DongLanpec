from PyQt5.QtWidgets import QTableWidget, QWidget, QLabel, QLineEdit, QHBoxLayout, QCheckBox, QMessageBox
from PyQt5.QtCore import Qt

def fengtoupinjie(table: QTableWidget, cursor, user_id, config_type):
    try:
        table.clear()
        table.setRowCount(1)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(['配置内容'])

        default_diameter = "2200"
        checked = False

        # 查询旧值
        cursor.execute("SELECT value FROM user_config WHERE user_id=%s AND config_type=%s", (user_id, config_type))
        result = cursor.fetchone()
        if result and "DN>" in result[0]:
            try:
                default_diameter = result[0].split("DN>")[1].split("mm")[0].strip()
                checked = True
            except Exception as e:
                print("[警告] 解析旧值失败，使用默认值", e)

        # 构造行
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(5)

        checkbox = QCheckBox("当公称直径 DN >")
        checkbox.setChecked(checked)
        diameter_input = QLineEdit(default_diameter)
        diameter_input.setFixedWidth(60)
        label_suffix = QLabel("mm 时，采用拼（板）接封头。")

        row_layout.addWidget(checkbox)
        row_layout.addWidget(diameter_input)
        row_layout.addWidget(label_suffix)
        row_layout.addStretch()
        table.setCellWidget(0, 0, row_widget)

        # 保存引用
        table._checkbox = checkbox
        table._diameter_input = diameter_input

        # 保存按钮绑定
        if not hasattr(table, '_save_connected_pinban_opt'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_pinban_optional_config(table, cursor.connection, user_id, config_type))
                table._save_connected_pinban_opt = True

    except Exception as e:
        print(f"[错误] 加载拼板接封头配置失败: {e}")

def save_pinban_optional_config(table: QTableWidget, db_conn, user_id, config_type):
    try:
        checkbox = table._checkbox
        diameter_input = table._diameter_input

        if not checkbox.isChecked():
            # 不选中则删除配置
            cursor = db_conn.cursor()
            cursor.execute("DELETE FROM user_config WHERE user_id=%s AND config_type=%s", (user_id, config_type))
            db_conn.commit()
            cursor.close()
            print(f"[保存成功] 未勾选，已清除 {config_type}")
            return

        diameter = diameter_input.text().strip()
        if not diameter.isdigit():
            QMessageBox.warning(table, "输入错误", "请输入有效的数字值")
            return

        sentence = f"当公称直径DN>{diameter}mm时，采用拼（板）接封头。"

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM user_config WHERE user_id=%s AND config_type=%s", (user_id, config_type))
        cursor.execute("INSERT INTO user_config (user_id, config_type, value) VALUES (%s, %s, %s)",
                       (user_id, config_type, sentence))
        db_conn.commit()
        cursor.close()

        print(f"[保存成功] {config_type}: {sentence}")
    except Exception as e:
        print(f"[错误] 保存拼板接封头配置失败: {e}")
