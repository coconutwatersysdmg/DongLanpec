from PyQt5.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QCheckBox, QLineEdit, QTableWidget
)

def zhichenghuan_config(table: QTableWidget, cursor, user_id):
    try:
        # 默认值
        defaults = {
            "inner": "所在元件外直径+12",
            "outer": "所在元件外直径+2*支耳与相焊元件间隙+2*支耳宽度",
            "thk": "6"
        }

        cursor.execute("SELECT value FROM 与支耳螺栓连接的支撑环预定义用户表 WHERE user_id = %s", (user_id,))
        saved = set(row[0] for row in cursor.fetchall())

        table.clear()
        table.setRowCount(3)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["支撑环配置"])
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        table._zhichenghuan_items = []

        def make_row(checkbox, widgets):
            w = QWidget()
            layout = QHBoxLayout(w)
            layout.setContentsMargins(10, 0, 10, 0)
            layout.addWidget(checkbox)
            for item in widgets:
                layout.addWidget(item if isinstance(item, QWidget) else QLabel(str(item)))
            layout.addStretch()
            return w

        def insert_sentence(row, template, default_value):
            cb = QCheckBox()
            edit = QLineEdit(default_value)
            sentence = template.format(edit.text())
            for old in saved:
                if old.startswith(template.split("{}")[0]):
                    cb.setChecked(True)
                    edit.setText(old.replace(template.split("{}")[0], "").replace(template.split("{}")[1], ""))
            table.setCellWidget(row, 0, make_row(cb, [template.split("{}")[0], edit, template.split("{}")[1]]))
            table._zhichenghuan_items.append((cb, template, [edit]))

        insert_sentence(0, "支撑环内径为：{}mm。", defaults["inner"])
        insert_sentence(1, "支撑环外径为：{}mm。", defaults["outer"])
        insert_sentence(2, "支撑环厚度默认为{} mm。", defaults["thk"])

        if not hasattr(table, '_save_connected_zhichenghuan'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_zhichenghuan_config(table, cursor.connection, user_id)
                )
                table._save_connected_zhichenghuan = True

    except Exception as e:
        print(f"[错误] 加载支撑环配置失败: {e}")

def save_zhichenghuan_config(table: QTableWidget, db_conn, user_id):
    try:
        print("[调试] 支撑环保存逻辑已调用")
        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 与支耳螺栓连接的支撑环预定义用户表 WHERE user_id = %s", (user_id,))

        for cb, template, edits in table._zhichenghuan_items:
            if cb.isChecked():
                values = [edit.text().strip() for edit in edits]
                final_sentence = template.format(*values)
                cursor.execute(
                    "INSERT INTO 与支耳螺栓连接的支撑环预定义用户表 (user_id, value) VALUES (%s, %s)",
                    (user_id, final_sentence)
                )

        db_conn.commit()
        cursor.close()
        print("[保存成功] 支撑环配置已更新")
    except Exception as e:
        print(f"[错误] 保存支撑环配置失败: {e}")
