from PyQt5.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QCheckBox, QLineEdit, QTableWidget
)

def hanjiezhichengban_chicun_config(table: QTableWidget, cursor, user_id):
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
        cursor.execute("SELECT value FROM 与容器直接焊接的支撑板预定义用户表 WHERE user_id = %s", (user_id,))
        saved = set(row[0] for row in cursor.fetchall())

        table.clear()
        table.setRowCount(3)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["容器直接焊接的支撑板尺寸配置"])
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

        def insert_sentence(row, template, default_value, editable=False):
            cb = QCheckBox()
            edit = QLineEdit(default_value) if editable else None
            sentence = template.format(default_value) if editable else template
            for old in saved:
                if editable and old.startswith(template.split("{}")[0]):
                    cb.setChecked(True)
                    edit.setText(old.replace(template.split("{}")[0], "").replace(template.split("{}")[-1], ""))
                elif not editable and old == sentence:
                    cb.setChecked(True)
            if editable:
                table.setCellWidget(row, 0, make_row(cb, [template.split("{}")[0], edit, template.split("{}")[-1]]))
                table._zhichengban_items.append((cb, template, [edit]))
            else:
                table.setCellWidget(row, 0, make_row(cb, [sentence]))
                table._zhichengban_items.append((cb, sentence, []))

        insert_sentence(0, "支撑板长度符合19条1）第三条要求。", "", editable=False)
        insert_sentence(1, "支撑板宽度W（沿保温厚度方向）符合19条2）b-i第三条要求。", "", editable=False)
        insert_sentence(2, "支撑板厚度默认为{} mm。", defaults["thk"], editable=True)

        if not hasattr(table, '_save_connected_zhichengban_direct'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_zhichengban_direct_config(table, cursor.connection, user_id)
                )
                table._save_connected_zhichengban_direct = True

    except Exception as e:
        print(f"[错误] 加载容器直接焊接支撑板配置失败: {e}")

def save_zhichengban_direct_config(table: QTableWidget, db_conn, user_id):
    try:
        print("[调试] 容器直接焊接支撑板保存逻辑已调用")
        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 与容器直接焊接的支撑板预定义用户表 WHERE user_id = %s", (user_id,))

        for cb, template, edits in table._zhichengban_items:
            if cb.isChecked():
                if edits:
                    values = [edit.text().strip() for edit in edits]
                    final_sentence = template.format(*values)
                else:
                    final_sentence = template
                cursor.execute(
                    "INSERT INTO 与容器直接焊接的支撑板预定义用户表 (user_id, value) VALUES (%s, %s)",
                    (user_id, final_sentence)
                )

        db_conn.commit()
        cursor.close()
        print("[保存成功] 容器直接焊接支撑板配置已更新")
    except Exception as e:
        print(f"[错误] 保存容器直接焊接支撑板配置失败: {e}")
