from PyQt5.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QCheckBox, QLineEdit, QTableWidget
)

def zhichenghuan_rongqi_config(table: QTableWidget, cursor, user_id):
    try:
        # 默认值
        defaults = {
            "inner_expr": "所在元件外直径+2*支撑环与相焊元件间隙",
            "outer_expr_low": "为元件外直径+保温厚度*2",
            "outer_expr_high": "为元件外直径+保温厚度*2-20",
            "thk": "6"
        }

        # 查询旧值
        cursor.execute("SELECT value FROM 与容器直接焊接的支撑环预定义用户表 WHERE user_id = %s", (user_id,))
        saved = set(row[0] for row in cursor.fetchall())

        table.clear()
        table.setRowCount(3)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["支撑环参数配置"])
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

        def insert_sentence(row, template, default_values):
            cb = QCheckBox()
            edits = []
            if isinstance(default_values, (tuple, list)):
                edits = [QLineEdit(val) for val in default_values]
                sentence = template.format(*[e.text() for e in edits])
            else:
                edits = [QLineEdit(default_values)]
                sentence = template.format(edits[0].text())

            for old in saved:
                prefix = template.split("{}")[0]
                if old.startswith(prefix):
                    cb.setChecked(True)
                    if len(edits) == 1:
                        suffix = template.split("{}")[1]
                        edits[0].setText(old.replace(prefix, "").replace(suffix, ""))
                    else:
                        try:
                            values = old.replace(prefix, "").split("；保温（保冷）厚度>40：")
                            edits[0].setText(values[0].replace(" mm。", "").strip())
                            edits[1].setText(values[1].replace(" mm。", "").strip())
                        except:
                            pass

            widgets = []
            if len(edits) == 1:
                widgets = [template.split("{}")[0], edits[0], template.split("{}")[1]]
            else:
                parts = template.split("{}")
                widgets = [parts[0], edits[0], parts[1], edits[1], parts[2]]
            table.setCellWidget(row, 0, make_row(cb, widgets))
            table._zhichenghuan_items.append((cb, template, edits))

        insert_sentence(0, "支撑环内径为：{}mm。", defaults["inner_expr"])
        insert_sentence(1, "支撑环外径为：保温（保冷）厚度<=40：{} mm；保温（保冷）厚度>40：{} mm。", (defaults["outer_expr_low"], defaults["outer_expr_high"]))
        insert_sentence(2, "支撑环厚度默认为{} mm。", defaults["thk"])

        if not hasattr(table, '_save_connected_zhichenghuan_jiejie'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_zhichenghuan_jiejie_config(table, cursor.connection, user_id)
                )
                table._save_connected_zhichenghuan_jiejie = True

    except Exception as e:
        print(f"[错误] 加载支撑环参数配置失败: {e}")

def save_zhichenghuan_jiejie_config(table: QTableWidget, db_conn, user_id):
    try:
        print("[调试] 支撑环配置保存逻辑已调用")
        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 与容器直接焊接的支撑环预定义用户表 WHERE user_id = %s", (user_id,))

        for cb, template, edits in table._zhichenghuan_items:
            if cb.isChecked():
                values = [edit.text().strip() for edit in edits]
                final_sentence = template.format(*values)
                cursor.execute(
                    "INSERT INTO 与容器直接焊接的支撑环预定义用户表 (user_id, value) VALUES (%s, %s)",
                    (user_id, final_sentence)
                )

        db_conn.commit()
        cursor.close()
        print("[保存成功] 支撑环配置已更新")
    except Exception as e:
        print(f"[错误] 保存支撑环配置失败: {e}")
