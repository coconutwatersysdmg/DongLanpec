from PyQt5.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QCheckBox, QLineEdit, QRadioButton, QButtonGroup, QTableWidget
)

def weibuzhicheng_config(table: QTableWidget, cursor, user_id):
    try:
        defaults = {
            "offset": "-1",
            "baobian_width": "40",
            "baobian_thk": "8",
            "support_type": "防振杆"
        }

        cursor.execute("SELECT value FROM 尾部支撑预定义用户表 WHERE user_id = %s", (user_id,))
        saved = set(row[0] for row in cursor.fetchall())

        table.clear()
        table.setRowCount(4)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["尾部支撑配置"])
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

        insert_sentence(0, "包边条宽度为{}mm。", defaults["baobian_width"])
        insert_sentence(1, "包边条厚度为{}mm。", defaults["baobian_thk"])

        # 单选项不再有勾选框
        radio1 = QRadioButton("尾部支撑件使用防振杆。")
        radio2 = QRadioButton("尾部支撑件使用防振板条。")
        group = QButtonGroup(table)
        group.addButton(radio1)
        group.addButton(radio2)
        if any(val.startswith("尾部支撑件使用防振杆") for val in saved):
            radio1.setChecked(True)
        elif any(val.startswith("尾部支撑件使用防振板条") for val in saved):
            radio2.setChecked(True)
        row_w = QWidget()
        layout = QHBoxLayout(row_w)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.addWidget(radio1)
        layout.addWidget(radio2)
        layout.addStretch()
        table.setCellWidget(2, 0, row_w)
        table._dingjuguan_items.append((None, group, []))

        if not hasattr(table, '_save_connected_dingjuguan'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_dingjuguan_config(table, cursor.connection, user_id)
                )
                table._save_connected_dingjuguan = True

    except Exception as e:
        print(f"[错误] 加载尾部支撑配置失败: {e}")

    def save_dingjuguan_config(table: QTableWidget, db_conn, user_id):
        try:
            print("[调试] 尾部支撑配置保存逻辑已调用")
            cursor = db_conn.cursor()
            cursor.execute("DELETE FROM 尾部支撑预定义用户表 WHERE user_id = %s", (user_id,))

            for cb, template_or_group, edits in table._dingjuguan_items:
                if isinstance(template_or_group, QButtonGroup):
                    selected = template_or_group.checkedButton()
                    if selected:
                        final_sentence = selected.text()
                        cursor.execute(
                            "INSERT INTO 尾部支撑预定义用户表 (user_id, value) VALUES (%s, %s)",
                            (user_id, final_sentence)
                        )
                elif cb and cb.isChecked():
                    if edits:
                        values = [edit.text().strip() for edit in edits]
                        final_sentence = template_or_group.format(*values)
                        cursor.execute(
                            "INSERT INTO 尾部支撑预定义用户表 (user_id, value) VALUES (%s, %s)",
                            (user_id, final_sentence)
                        )
                    else:
                        final_sentence = template_or_group
                        cursor.execute(
                            "INSERT INTO 尾部支撑预定义用户表 (user_id, value) VALUES (%s, %s)",
                            (user_id, final_sentence)
                        )

            db_conn.commit()
            cursor.close()
            print("[保存成功] 尾部支撑配置已更新")
        except Exception as e:
            print(f"[错误] 保存尾部支撑配置失败: {e}")
