from PyQt5.QtWidgets import QWidget, QHBoxLayout, QCheckBox, QLabel, QLineEdit, QTableWidget


def baowen_zhicheng_config(table: QTableWidget, cursor, user_id):
    try:
        defaults = [
            ("保温支撑间距范围为", "500", "3000"),
            ("保冷支撑间距范围为", "750", "4500"),
            ("保温（保冷）支撑与容器焊缝间距最小值为", "50"),
            ("保温（保冷）钉间距最小值为", "50")
        ]

        # 读取用户保存值
        cursor.execute("SELECT value FROM 保温支撑间距预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        checked = [True, True, True, True]  # 默认全部勾选
        if result:
            value = result[0]
            checked = [text in value for text in ["保温支撑间距范围为", "保冷支撑间距范围为", "支撑与容器焊缝间距最小值为", "钉间距最小值为"]]
            import re
            m = re.findall(r"(\d+\.?\d*)", value)
            if len(m) >= 6:
                defaults[0] = (defaults[0][0], m[0], m[1])
                defaults[1] = (defaults[1][0], m[2], m[3])
                defaults[2] = (defaults[2][0], m[4])
                defaults[3] = (defaults[3][0], m[5])

        table.clear()
        table.setRowCount(4)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["保温支撑相关规则"])
        table.verticalHeader().setDefaultSectionSize(50)
        table.horizontalHeader().setStretchLastSection(True)

        inputs = {}

        for i, (prefix, *vals) in enumerate(defaults):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(10, 0, 10, 0)
            cb = QCheckBox("\u2003")
            cb.setChecked(checked[i])
            h.addWidget(cb)
            h.addWidget(QLabel(prefix))
            edits = []
            for val in vals:
                edit = QLineEdit(val)
                edit.setMaximumWidth(60)
                edits.append(edit)
                h.addWidget(edit)
                if len(edits) == 1 and len(vals) == 2:
                    h.addWidget(QLabel("~"))
            if i < 2:
                h.addWidget(QLabel("mm"))
            else:
                h.addWidget(QLabel("mm；"))
            h.addStretch()
            table.setCellWidget(i, 0, row)
            inputs[f"cb{i+1}"] = cb
            inputs[f"edits{i+1}"] = edits

        table._baowen_inputs = inputs

        if not hasattr(table, "_save_connected_baowen"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(lambda: save_baowen_zhicheng_config(table, cursor.connection, user_id))
                table._save_connected_baowen = True

    except Exception as e:
        print(f"[错误] 加载保温支撑配置失败: {e}")

def save_baowen_zhicheng_config(table: QTableWidget, db_conn, user_id):
    try:
        data = table._baowen_inputs
        lines = []
        if data["cb1"].isChecked():
            v1, v2 = data["edits1"]
            lines.append(f"保温支撑间距范围为{v1.text()}~{v2.text()}mm；")
        if data["cb2"].isChecked():
            v3, v4 = data["edits2"]
            lines.append(f"保冷支撑间距范围为{v3.text()}~{v4.text()}mm；")
        if data["cb3"].isChecked():
            v5 = data["edits3"][0]
            lines.append(f"保温（保冷）支撑与容器焊缝间距最小值为{v5.text()}mm；")
        if data["cb4"].isChecked():
            v6 = data["edits4"][0]
            lines.append(f"保温（保冷）钉间距最小值为{v6.text()}mm；")

        value = "\n".join(lines)

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 保温支撑间距预定义用户表 WHERE user_id = %s", (user_id,))
        cursor.execute("INSERT INTO 保温支撑间距预定义用户表 (user_id, value) VALUES (%s, %s)", (user_id, value))
        db_conn.commit()
        cursor.close()
        print("[保存成功] 保温支撑间距规则已更新")
    except Exception as e:
        print(f"[错误] 保存保温支撑配置失败: {e}")
