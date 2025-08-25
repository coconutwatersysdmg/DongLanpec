from PyQt5.QtWidgets import QTableWidget, QCheckBox, QWidget, QHBoxLayout, QLabel


def zhichengban_config(table: QTableWidget, cursor, user_id):
    try:
        table.clear()
        table.setRowCount(1)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["支撑板配置"])
        table.verticalHeader().setDefaultSectionSize(60)
        table.horizontalHeader().setStretchLastSection(True)

        # 读取历史记录
        cursor.execute("SELECT value FROM 支撑板预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        saved_text = result[0] if result else ""

        cb1 = QCheckBox("max(旁路挡板，折流板厚度)")
        cb2 = QCheckBox("旁路挡板")
        cb3 = QCheckBox("折流板厚度")

        # 自动勾选之前保存的内容
        if "max(旁路挡板，折流板厚度)" in saved_text:
            cb1.setChecked(True)
        if "旁路挡板" in saved_text:
            cb2.setChecked(True)
        if "折流板厚度" in saved_text:
            cb3.setChecked(True)

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.addWidget(QLabel("支撑板厚度的确定："))
        layout.addWidget(cb1)
        layout.addWidget(cb2)
        layout.addWidget(cb3)
        layout.addStretch()
        table.setCellWidget(0, 0, row)

        table._zhichengban_inputs = {
            "cb1": cb1,
            "cb2": cb2,
            "cb3": cb3
        }

        if not hasattr(table, "_save_connected_zhichengban"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(lambda: save_zhichengban_config(table, cursor.connection, user_id))
                table._save_connected_zhichengban = True

    except Exception as e:
        print(f"[错误] 加载支撑板配置失败: {e}")

def save_zhichengban_config(table: QTableWidget, db_conn, user_id):
    try:
        data = table._zhichengban_inputs
        selected = []
        if data["cb1"].isChecked():
            selected.append("max(旁路挡板，折流板厚度)")
        if data["cb2"].isChecked():
            selected.append("旁路挡板")
        if data["cb3"].isChecked():
            selected.append("折流板厚度")

        sentence = "支撑板厚度的确定：" + "，".join(selected)

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 支撑板预定义用户表 WHERE user_id = %s", (user_id,))
        cursor.execute("INSERT INTO 支撑板预定义用户表 (user_id, value) VALUES (%s, %s)", (user_id, sentence))
        db_conn.commit()
        cursor.close()
        print("[保存成功] 支撑板配置已更新")

    except Exception as e:
        print(f"[错误] 保存支撑板配置失败: {e}")
