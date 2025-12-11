from PyQt5.QtWidgets import QWidget, QLabel, QLineEdit, QTableWidget, QHBoxLayout
import json

def jieguancailiaoyouxianji(table: QTableWidget, cursor, user_id, config_type):
    try:
        table.clear()
        table.setRowCount(3)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["推荐接管材质配置"])

        default_values = ["50", "400", "400"]

        cursor.execute("SELECT value FROM user_config WHERE user_id=%s AND config_type=%s", (user_id, config_type))
        result = cursor.fetchone()
        if result:
            try:
                loaded = json.loads(result[0])
                default_values = [str(loaded[0]["value"]), str(loaded[1]["value"]), str(loaded[2]["value"])]
            except Exception as e:
                print(f"[警告] 配置解析失败，使用默认值: {e}")

        table._material_inputs = []

        for i in range(3):
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(5, 0, 0, 0)

            if i == 0:
                val_input = QLineEdit(default_values[i])
                val_input.setMaximumWidth(80)
                layout.addWidget(QLabel("DN≤"))
                layout.addWidget(val_input)
                layout.addWidget(QLabel("mm规格的接管优先采用锻制管或厚壁管。"))
                table._material_inputs.append(val_input)
            elif i == 1:
                left_val_input = QLineEdit(default_values[0])
                left_val_input.setMaximumWidth(80)
                right_val_input = QLineEdit(default_values[1])
                right_val_input.setMaximumWidth(80)
                layout.addWidget(left_val_input)
                layout.addWidget(QLabel("mm<DN≤"))
                layout.addWidget(right_val_input)
                layout.addWidget(QLabel("mm规格的接管优先采用无缝钢管。"))
                table._material_inputs.extend([left_val_input, right_val_input])
            else:
                val_input = QLineEdit(default_values[2])
                val_input.setMaximumWidth(80)
                layout.addWidget(QLabel("DN>"))
                layout.addWidget(val_input)
                layout.addWidget(QLabel("mm规格的接管优先采用钢板卷制管。"))
                table._material_inputs.append(val_input)

            layout.addStretch()
            table.setCellWidget(i, 0, widget)

        if not hasattr(table, "_save_connected_pipe_material"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_pipe_material_config(table, cursor.connection, user_id, config_type))
                table._save_connected_pipe_material = True

    except Exception as e:
        print(f"[错误] 加载推荐接管材质配置失败: {e}")

def save_pipe_material_config(table: QTableWidget, db_conn, user_id, config_type):
    try:
        val1 = float(table._material_inputs[0].text())
        val2 = float(table._material_inputs[1].text())
        val3 = float(table._material_inputs[2].text())
        val4 = float(table._material_inputs[3].text())

        if not (val1 < val3 < val4):
            print("[错误] 数值区间有重叠或顺序错误")
            return

        result = [
            {"value": val1, "material": f"DN≤{val1}mm规格的接管优先采用锻制管或厚壁管。"},
            {"value": [val1, val3], "material": f"{val1}mm<DN≤{val3}mm规格的接管优先采用无缝钢管。"},
            {"value": val4, "material": f"DN>{val4}mm规格的接管优先采用钢板卷制管。"},
        ]

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM user_config WHERE user_id=%s AND config_type=%s", (user_id, config_type))
        cursor.execute("INSERT INTO user_config (user_id, config_type, value) VALUES (%s, %s, %s)",
                       (user_id, config_type, json.dumps(result, ensure_ascii=False)))
        db_conn.commit()
        cursor.close()
        print("[保存成功] 推荐接管材质配置")

    except Exception as e:
        print(f"[错误] 保存推荐材质失败: {e}")
