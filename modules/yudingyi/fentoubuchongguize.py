from PyQt5.QtWidgets import QTableWidget, QLabel, QWidget, QHBoxLayout, QCheckBox, QLineEdit
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt


def fengtoubuchongguize(table: QTableWidget, cursor, user_id, config_type):
    try:
        table.clear()
        table.setRowCount(6)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(['配置内容'])

        val = "6"
        typ = "HH"
        val2 = "60"
        opt_main = opt1 = opt2 = opt3 = False

        # ✅ 从表“封头选用补充规则预定义用户表”读取旧值
        cursor.execute("SELECT value FROM 封头选用补充规则预定义用户表 WHERE user_id=%s", (user_id,))
        result = cursor.fetchone()
        if result:
            text = result[0]
            try:
                opt_main = "改选用" in text
                val = text.split("厚度大于与其连接的圆筒名义厚度")[1].split("mm")[0].strip()
                typ = text.split("改选用")[1].split("型封头")[0].strip()
                val2 = text.split("厚度的")[1].split("%")[0].strip()
                opt1 = "L值包含在" in text
                opt2 = "根据L值增大" in text
                opt3 = "厚度不小于" in text
            except Exception as e:
                print("[警告] 解析失败，使用默认值", e)

        bold_font = QFont()
        bold_font.setBold(True)

        row0 = QLabel("1. 椭圆形或蝶形封头对连接圆筒长度的影响：")
        row0.setFont(bold_font)
        table.setCellWidget(0, 0, row0)

        row1_widget = QWidget()
        row1_layout = QHBoxLayout(row1_widget)
        row1_layout.setContentsMargins(0, 0, 0, 0)
        row1_layout.setSpacing(5)
        checkbox_main = QCheckBox("当选用椭圆形或蝶形封头，封头名义厚度大于与其连接的圆筒名义厚度")
        val_input = QLineEdit(val)
        val_input.setFixedWidth(50)
        type_input = QLineEdit(typ)
        type_input.setFixedWidth(50)
        row1_layout.addWidget(checkbox_main)
        row1_layout.addWidget(val_input)
        row1_layout.addWidget(QLabel("mm时，改选用"))
        row1_layout.addWidget(type_input)
        row1_layout.addWidget(QLabel("型封头。"))
        row1_layout.addStretch()
        table.setCellWidget(1, 0, row1_widget)
        checkbox_main.setChecked(opt_main)
        val_input.setEnabled(opt_main)
        type_input.setEnabled(opt_main)
        checkbox_main.stateChanged.connect(lambda state: (val_input.setEnabled(state == Qt.Checked),
                                                          type_input.setEnabled(state == Qt.Checked)))

        row2 = QLabel("2. 球(缺)形封头对连接圆筒长度的影响：")
        row2.setFont(bold_font)
        table.setCellWidget(2, 0, row2)

        row3_widget = QWidget()
        row3_layout = QHBoxLayout(row3_widget)
        row3_layout.setContentsMargins(0, 0, 0, 0)
        cb1 = QCheckBox("当使用I、III型球(缺)形封头时，L值包含在(不增大)圆筒长度内；")
        cb1.setChecked(opt1)
        row3_layout.addWidget(cb1)
        row3_layout.addStretch()
        table.setCellWidget(3, 0, row3_widget)

        row4_widget = QWidget()
        row4_layout = QHBoxLayout(row4_widget)
        row4_layout.setContentsMargins(0, 0, 0, 0)
        cb2 = QCheckBox("当使用I、III型球(缺)形封头时，根据L值增大圆筒长度。")
        cb2.setChecked(opt2)
        row4_layout.addWidget(cb2)
        row4_layout.addStretch()
        table.setCellWidget(4, 0, row4_widget)

        row5_widget = QWidget()
        row5_layout = QHBoxLayout(row5_widget)
        row5_layout.setContentsMargins(0, 0, 0, 0)
        cb3 = QCheckBox("球(缺)形封头厚度不小于与其连接圆筒厚度的")
        cb3.setChecked(opt3)
        val2_input = QLineEdit(val2)
        val2_input.setFixedWidth(50)
        row5_layout.addWidget(cb3)
        row5_layout.addWidget(val2_input)
        row5_layout.addWidget(QLabel("%。"))
        row5_layout.addStretch()
        table.setCellWidget(5, 0, row5_widget)

        table._checkbox_main = checkbox_main
        table._val_input = val_input
        table._type_input = type_input
        table._cb1 = cb1
        table._cb2 = cb2
        table._cb3 = cb3
        table._val2_input = val2_input

        if not hasattr(table, '_save_connected_touxing'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(lambda: save_touxing(table, cursor.connection, user_id))
                table._save_connected_touxing = True

    except Exception as e:
        print(f"[错误] 加载配置失败: {e}")


def save_touxing(table, db_conn, user_id):
    try:
        if table._checkbox_main.isChecked():
            val = table._val_input.text()
            typ = table._type_input.text()
            part_main = f"当选用椭圆形或蝶形封头，封头名义厚度大于与其连接的圆筒名义厚度{val}mm时，改选用{typ}型封头。"
        else:
            part_main = ""

        cb1 = table._cb1.isChecked()
        cb2 = table._cb2.isChecked()
        cb3 = table._cb3.isChecked()
        val2 = table._val2_input.text()

        parts = []
        if part_main:
            parts.append(part_main)
        if cb1:
            parts.append("当使用I、III型球(缺)形封头时，L值包含在(不增大)圆筒长度内；")
        if cb2:
            parts.append("当使用I、III型球(缺)形封头时，根据L值增大圆筒长度。")
        if cb3:
            parts.append(f"球(缺)形封头厚度不小于与其连接圆筒厚度的{val2}%。")

        value_str = "\n".join(parts)

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 封头选用补充规则预定义用户表 WHERE user_id=%s", (user_id,))
        cursor.execute("INSERT INTO 封头选用补充规则预定义用户表 (value, user_id) VALUES (%s, %s)",
                       (value_str, user_id))
        db_conn.commit()
        cursor.close()

        print(f"[保存成功] 封头选用补充规则预定义用户表: {value_str}")
    except Exception as e:
        print(f"[错误] 保存配置失败: {e}")
