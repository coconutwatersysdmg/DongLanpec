from PyQt5.QtWidgets import QWidget, QLabel, QLineEdit, QHBoxLayout, QTableWidget, QComboBox
from PyQt5.QtCore import Qt
import json

def duanjianfenji(table: QTableWidget, cursor, user_id, config_type):
    try:
        rules = [
            ("设计压力 < ", "10.0", "MPa 的法兰以及几何尺寸类似的锻件", "Ⅱ"),
            ("设计压力 ≥ ", "1.6", "MPa 的非低温容器用锻件", "Ⅱ"),
            ("设计压力 ≥ ", "10.0", "MPa 的中小型锻件", "Ⅲ"),
            ("", "", "大型锻件", "Ⅲ"),
            ("", "", "介质的毒性为极度危害性的锻件", "Ⅳ"),
            ("", "", "介质的毒性为高度危害性的锻件", "Ⅲ"),
            ("标准抗拉强度下限值 > ", "540", "MPa 且公称厚度 > 200mm 的低合金锻件", "Ⅲ"),
            ("公称厚度 > ", "300", "mm 的锻件", "Ⅳ"),
            ("", "", "采用分析设计标准设计的设备用锻件", "Ⅲ"),
            ("", "", "用作压力容器筒节和封头的筒形、环形和碗形锻件", "Ⅲ"),
            ("公称直径 ≥ ", "1200", "mm 的热交换器管板或平盖锻件", "Ⅳ"),
            ("", "", "非受压元件用中小型锻件", "Ⅰ")
        ]

        table.clear()
        table.setRowCount(len(rules))
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["技术等级规则"])
        table.horizontalHeader().setStretchLastSection(True)

        cursor.execute("SELECT value FROM user_config WHERE user_id=%s AND config_type=%s", (user_id, config_type))
        result = cursor.fetchone()
        if result:
            try:
                rules_json = json.loads(result[0])
                for i in range(min(len(rules), len(rules_json))):
                    if i == 6:
                        # 第七条固定540不可更改
                        rules[i] = (rules[i][0], "540", rules[i][2], rules_json[i].get("level", rules[i][3]))
                    else:
                        rules[i] = (
                            rules[i][0],
                            rules_json[i].get("value", rules[i][1]),
                            rules[i][2],
                            rules_json[i].get("level", rules[i][3])
                        )
            except Exception as e:
                print(f"[警告] 解析旧配置失败: {e}")

        table._config_inputs = []

        for i, (prefix, val, typ, level) in enumerate(rules):
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(5, 0, 0, 0)

            if prefix:
                layout.addWidget(QLabel(prefix))
                if i == 6:
                    value_input = QLabel(val)
                else:
                    value_input = QLineEdit(val)
                    value_input.setMaximumWidth(80)
                layout.addWidget(value_input)
                layout.addWidget(QLabel(" " + typ + " 应符合"))
            else:
                value_input = None
                layout.addWidget(QLabel(typ + " 应符合"))

            level_box = QComboBox()
            level_box.addItems(["Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ"])
            level_box.setCurrentText(level)
            level_box.setMaximumWidth(60)
            layout.addWidget(level_box)
            layout.addWidget(QLabel("级要求。"))
            layout.addStretch()

            table.setCellWidget(i, 0, widget)
            table._config_inputs.append({
                "prefix": prefix,
                "value_input": value_input,
                "type": typ,
                "level_combo": level_box
            })

        if not hasattr(table, "_save_connected_duanjian"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_duanjianjishudengji(table, cursor.connection, user_id, config_type))
                table._save_connected_duanjian = True

    except Exception as e:
        print(f"[错误] 加载锻件技术等级失败: {e}")

def save_duanjianjishudengji(table: QTableWidget, db_conn, user_id, config_type):
    try:
        rows = []
        for idx, item in enumerate(table._config_inputs):
            prefix = item["prefix"]
            if isinstance(item["value_input"], QLineEdit):
                val = item["value_input"].text()
            elif isinstance(item["value_input"], QLabel):
                val = item["value_input"].text()
            else:
                val = ""
            typ = item["type"]
            level = item["level_combo"].currentText()
            rows.append({"prefix": prefix, "value": val, "type": typ, "level": level})

        value_json = json.dumps(rows, ensure_ascii=False)

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM user_config WHERE user_id=%s AND config_type=%s", (user_id, config_type))
        cursor.execute("INSERT INTO user_config (user_id, config_type, value) VALUES (%s, %s, %s)",
                       (user_id, config_type, value_json))
        db_conn.commit()
        cursor.close()

        print("[保存成功] 技术等级要求")
    except Exception as e:
        print(f"[错误] 保存配置失败: {e}")