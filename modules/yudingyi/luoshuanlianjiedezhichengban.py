from PyQt5.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QCheckBox, QLineEdit, QTableWidget
)

def zhichengban_chicun_config(table: QTableWidget, cursor, user_id):
    try:
        # 默认值
        defaults = {
            "expr1": "支耳间距+单孔支耳（或焊接支耳）宽度",
            "expr2": "支耳间距+0.5*单孔支耳宽度+0.5*双孔支耳宽度-0.5*螺栓孔直径",
            "expr3": "支耳间距+双孔支耳宽度-螺栓孔直径",
            "max_len": "3200",
            "thk": "6",
            "bolt_d": "螺栓直径",
            "width_expr": "支耳宽度-5"
        }

        # 查询旧值
        cursor.execute("SELECT value FROM 与支耳焊接螺栓连接的支撑板预定义用户表 WHERE user_id = %s", (user_id,))
        saved = set(row[0] for row in cursor.fetchall())

        table.clear()
        table.setRowCount(7)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["支撑板尺寸配置"])
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        table._zhichengban_items = []

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
                    edit.setText(old.replace(template.split("{}")[0], "").replace(template.split("{}")[-1], ""))
            table.setCellWidget(row, 0, make_row(cb, [template.split("{}")[0], edit, template.split("{}")[-1]]))
            table._zhichengban_items.append((cb, template, [edit]))

        insert_sentence(0, "当支撑板两端支耳都为单孔支耳（或焊接支耳）时，支撑板长度为：{}，即支撑板正好盖住支耳。", defaults["expr1"])
        insert_sentence(1, "当支撑板一端支耳为单孔支耳，另一端支耳为双孔支耳时，支撑板长度为：{}。", defaults["expr2"])
        insert_sentence(2, "当支撑板两端支耳都为双孔支耳时，支撑板长度为：{}。", defaults["expr3"])
        insert_sentence(3, "螺栓连接支撑板长度不大于{}mm。", defaults["max_len"])
        insert_sentence(4, "支撑板宽度为：{}mm。", defaults["width_expr"])
        insert_sentence(5, "支撑板厚度默认为{} mm。", defaults["thk"])
        insert_sentence(6, "支撑板螺栓孔与支耳边缘的距离最小值为：{} mm。", defaults["bolt_d"])

        if not hasattr(table, '_save_connected_zhichengban'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_zhichengban_chicun_config(table, cursor.connection, user_id)
                )
                table._save_connected_zhichengban = True

    except Exception as e:
        print(f"[错误] 加载支撑板尺寸配置失败: {e}")

def save_zhichengban_chicun_config(table: QTableWidget, db_conn, user_id):
    try:
        print("[调试] 支撑板尺寸保存逻辑已调用")
        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 与支耳焊接螺栓连接的支撑板预定义用户表 WHERE user_id = %s", (user_id,))

        for cb, template, edits in table._zhichengban_items:
            if cb.isChecked():
                values = [edit.text().strip() for edit in edits]
                final_sentence = template.format(*values)
                cursor.execute(
                    "INSERT INTO 与支耳焊接螺栓连接的支撑板预定义用户表 (user_id, value) VALUES (%s, %s)",
                    (user_id, final_sentence)
                )

        db_conn.commit()
        cursor.close()
        print("[保存成功] 支撑板尺寸配置已更新")
    except Exception as e:
        print(f"[错误] 保存支撑板尺寸配置失败: {e}")