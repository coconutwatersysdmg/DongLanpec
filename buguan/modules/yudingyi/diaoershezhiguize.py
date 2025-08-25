from PyQt5.QtWidgets import QTableWidget, QCheckBox, QWidget, QHBoxLayout, QLabel, QLineEdit


def diaoerjiegou_config(table: QTableWidget, cursor, user_id):
    try:
        # 默认值
        default_coef = "2"

        # 查询旧值（取已保存句子集合）
        cursor.execute("SELECT value FROM 吊耳设置规则预定义用户表 WHERE user_id = %s", (user_id,))
        saved = set(row[0] for row in cursor.fetchall())

        table.clear()
        table.setRowCount(4)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["吊耳结构设置"])
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        table._diaoer_rows = []

        def make_row(checkbox, widgets):
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(10, 0, 10, 0)
            layout.addWidget(checkbox)
            for w in widgets:
                layout.addWidget(w if isinstance(w, QWidget) else QLabel(str(w)))
            layout.addStretch()
            return container

        # 第1条：可编辑系数
        cb1 = QCheckBox()
        coef_edit = QLineEdit(default_coef)
        template1 = "吊耳安全余量系数取 {}。"
        full1 = template1.format(coef_edit.text())
        if full1 in saved:
            cb1.setChecked(True)
            coef_edit.setText(full1.split("取 ")[1].split("。")[0])
        else:
            cb1.setChecked(True)  # 默认选中

        row1 = make_row(cb1, ["吊耳安全余量系数取", coef_edit, "。"])
        table.setCellWidget(0, 0, row1)
        table._diaoer_rows.append((cb1, template1, [coef_edit]))

        # 第2条：纯文本
        cb2 = QCheckBox()
        text2 = "吊耳结构尺寸按 HG/T 21574-2018 《化工设备吊耳设计选用规范》选用。"
        cb2.setChecked(text2 in saved)
        row2 = make_row(cb2, [text2])
        table.setCellWidget(1, 0, row2)
        table._diaoer_rows.append((cb2, text2, []))

        # 第3条：纯文本
        cb3 = QCheckBox()
        text3 = "按 HG/T 21574-2018 选用吊耳时，不考虑安全余量系数。"
        cb3.setChecked(text3 in saved)
        row3 = make_row(cb3, [text3])
        table.setCellWidget(2, 0, row3)
        table._diaoer_rows.append((cb3, text3, []))

        # 第4条：纯文本，默认选中
        cb4 = QCheckBox()
        text4 = "总是进行强度校核(含按 HG/T 21574-2018 选用)。"
        cb4.setChecked(text4 in saved)
        row4 = make_row(cb4, [text4])
        table.setCellWidget(3, 0, row4)
        table._diaoer_rows.append((cb4, text4, []))

        if not hasattr(table, '_save_connected_diaoerjiegou'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_diaoerjiegou_config(table, cursor.connection, user_id)
                )
                table._save_connected_diaoerjiegou = True

    except Exception as e:
        print(f"[错误] 加载吊耳结构设置失败: {e}")
def save_diaoerjiegou_config(table: QTableWidget, db_conn, user_id):
    try:
        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 吊耳设置规则预定义用户表 WHERE user_id = %s", (user_id,))

        for checkbox, template, edits in table._diaoer_rows:
            if checkbox.isChecked():
                if edits:
                    val = template.format(*[edit.text().strip() for edit in edits])
                else:
                    val = template
                cursor.execute(
                    "INSERT INTO 吊耳设置规则预定义用户表 (user_id, value) VALUES (%s, %s)",
                    (user_id, val)
                )

        db_conn.commit()
        cursor.close()
        print(f"[保存成功] 吊耳设置规则配置已更新")
    except Exception as e:
        print(f"[错误] 保存吊耳设置规则配置失败: {e}")
