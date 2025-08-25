from PyQt5.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QCheckBox, QLineEdit, QTableWidget
)

def dingjuguan_config(table: QTableWidget, cursor, user_id):
    try:
        defaults = {
            "offset": "-1",
        }

        cursor.execute("SELECT value FROM 定距管预定义用户表 WHERE user_id = %s", (user_id,))
        saved = set(row[0] for row in cursor.fetchall())

        table.clear()
        table.setRowCount(2)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["定距管配置"])
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        table._dingjuguan_items = []

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
                prefix = template.split("{}")[0]
                suffix = template.split("{}")[1]
                if old.startswith(prefix) and old.endswith(suffix):
                    cb.setChecked(True)
                    edit.setText(old[len(prefix):-len(suffix)])
            widgets = [template.split("{}")[0], edit, template.split("{}")[1]]
            table.setCellWidget(row, 0, make_row(cb, widgets))
            table._dingjuguan_items.append((cb, template, [edit]))

        insert_sentence(0, "所有定距管长度偏差为{}mm。", defaults["offset"])

        cb2 = QCheckBox()
        sentence2 = "定距管默认与换热管相同规格。"
        cb2.setChecked(sentence2 in saved)
        table.setCellWidget(1, 0, make_row(cb2, [sentence2]))
        table._dingjuguan_items.append((cb2, sentence2, []))

        if not hasattr(table, '_save_connected_dingjuguan'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_dingjuguan_config(table, cursor.connection, user_id)
                )
                table._save_connected_dingjuguan = True

    except Exception as e:
        print(f"[错误] 加载定距管配置失败: {e}")

def save_dingjuguan_config(table: QTableWidget, db_conn, user_id):
    try:
        print("[调试] 定距管配置保存逻辑已调用")
        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 定距管预定义用户表 WHERE user_id = %s", (user_id,))

        for cb, template, edits in table._dingjuguan_items:
            if cb.isChecked():
                if edits:
                    values = [edit.text().strip() for edit in edits]
                    final_sentence = template.format(*values)
                else:
                    final_sentence = template
                cursor.execute(
                    "INSERT INTO 定距管预定义用户表 (user_id, value) VALUES (%s, %s)",
                    (user_id, final_sentence)
                )

        db_conn.commit()
        cursor.close()
        print("[保存成功] 定距管配置已更新")
    except Exception as e:
        print(f"[错误] 保存定距管配置失败: {e}")
