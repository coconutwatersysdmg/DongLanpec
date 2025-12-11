from PyQt5.QtWidgets import QTableWidget, QLabel, QWidget, QHBoxLayout, QLineEdit
from PyQt5.QtCore import Qt

def fengtouzhibiangaodudingyi(table: QTableWidget, cursor, user_id, config_type):
    try:
        table.clear()
        table.setRowCount(2)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(['配置内容'])

        val1 = "2000"
        val2 = "25"
        val3 = "40"
        val4 = "50"

        cursor.execute("SELECT value FROM user_config WHERE user_id=%s AND config_type=%s", (user_id, config_type))
        result = cursor.fetchone()
        if result:
            text = result[0]
            try:
                val1 = text.split("DN≤")[1].split("mm")[0].strip()
                val2 = text.split("DN≤")[1].split("时，h取")[1].split("mm")[0].strip()
                val3 = text.split("否则，h取")[1].split("mm")[0].strip()
                val4 = text.split("h为")[1].split("mm")[0].strip()
            except Exception as e:
                print("[警告] 解析失败，使用默认值", e)

        # 第1行：DN≤x时，h取x1，否则h取x2
        row1_widget = QWidget()
        row1_layout = QHBoxLayout(row1_widget)
        row1_layout.setContentsMargins(0, 0, 0, 0)
        row1_layout.setSpacing(5)
        row1_layout.addWidget(QLabel("对于带直边的封头，当公称直径 DN≤"))
        input1 = QLineEdit(val1)
        input1.setFixedWidth(50)
        row1_layout.addWidget(input1)
        row1_layout.addWidget(QLabel("mm 时，h 取"))
        input2 = QLineEdit(val2)
        input2.setFixedWidth(50)
        row1_layout.addWidget(input2)
        row1_layout.addWidget(QLabel("mm，否则，h 取"))
        input3 = QLineEdit(val3)
        input3.setFixedWidth(50)
        row1_layout.addWidget(input3)
        row1_layout.addWidget(QLabel("mm。"))
        row1_layout.addStretch()
        table.setCellWidget(0, 0, row1_widget)

        # 第2行：参照ASME时 h 为 x
        row2_widget = QWidget()
        row2_layout = QHBoxLayout(row2_widget)
        row2_layout.setContentsMargins(0, 0, 0, 0)
        row2_layout.setSpacing(5)
        row2_layout.addWidget(QLabel("当产品标准中包含参照 ASME VIII-1 时，h 为"))
        input4 = QLineEdit(val4)
        input4.setFixedWidth(50)
        row2_layout.addWidget(input4)
        row2_layout.addWidget(QLabel("mm。"))
        row2_layout.addStretch()
        table.setCellWidget(1, 0, row2_widget)

        # 保存句柄
        table._dn_input = input1
        table._h1_input = input2
        table._h2_input = input3
        table._h_asme_input = input4

        if not hasattr(table, '_save_connected_zhizhi'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_zhizhi_fengtou(table, cursor.connection, user_id, config_type)
                )
                table._save_connected_zhizhi = True

    except Exception as e:
        print(f"[错误] 加载直边封头 h 值配置失败: {e}")

def save_zhizhi_fengtou(table, db_conn, user_id, config_type):
    try:
        val1 = table._dn_input.text()
        val2 = table._h1_input.text()
        val3 = table._h2_input.text()
        val4 = table._h_asme_input.text()

        value_str = (
            f"对于带直边的封头，当公称直径DN≤{val1}mm时，h取{val2}mm，否则，h取{val3}mm。\n"
            f"当产品标准中包含参照ASME VIII-1时，h为{val4}mm。"
        )

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM user_config WHERE user_id=%s AND config_type=%s", (user_id, config_type))
        cursor.execute("INSERT INTO user_config (user_id, config_type, value) VALUES (%s, %s, %s)",
                       (user_id, config_type, value_str))
        db_conn.commit()
        cursor.close()

        print(f"[保存成功] {config_type}: {value_str}")
    except Exception as e:
        print(f"[错误] 保存直边封头 h 值配置失败: {e}")
