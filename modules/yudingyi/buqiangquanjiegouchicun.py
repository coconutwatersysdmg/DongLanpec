from PyQt5.QtWidgets import QWidget, QLabel, QHBoxLayout, QCheckBox, QLineEdit, QTableWidget


def buqiangquan_jiegou_chicun_config(table: QTableWidget, cursor, user_id):
    try:
        # 默认值
        defaults = {
            "ratio_thk": "1.0",
            "min_width": "40",
            "max_ratio": "2"
        }

        # 查询旧值
        cursor.execute("SELECT value FROM 补强圈结构尺寸的确定预定义用户表 WHERE user_id = %s", (user_id,))
        saved = set(row[0] for row in cursor.fetchall())

        table.clear()
        table.setRowCount(4)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["补强圈结构尺寸要求"])
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        table._bqq_chicun_items = []

        def make_row(checkbox, widgets):
            w = QWidget()
            layout = QHBoxLayout(w)
            layout.setContentsMargins(10, 0, 10, 0)
            layout.addWidget(checkbox)
            for item in widgets:
                layout.addWidget(item if isinstance(item, QWidget) else QLabel(str(item)))
            layout.addStretch()
            return w

        # 第1条：纯文本
        cb1 = QCheckBox()
        sentence1 = "满足 JB/T 4736《补强圈》标准中表列的结构尺寸；"
        cb1.setChecked(sentence1 in saved)
        table.setCellWidget(0, 0, make_row(cb1, [sentence1]))
        table._bqq_chicun_items.append((cb1, sentence1, []))

        # 第2条：1.0 倍厚度
        cb2 = QCheckBox()
        edits2 = [QLineEdit(defaults["ratio_thk"])]
        sentence2_template = "补强圈厚度值优先选 {} 倍其附属壳体厚度；"
        full_sentence2 = sentence2_template.format(edits2[0].text())
        if full_sentence2 in saved:
            cb2.setChecked(True)
        table.setCellWidget(1, 0, make_row(cb2, ["补强圈厚度值优先选", edits2[0], "倍其附属壳体厚度；"]))
        table._bqq_chicun_items.append((cb2, sentence2_template, edits2))

        # 第3条：最小宽度
        cb3 = QCheckBox()
        edits3 = [QLineEdit(defaults["min_width"])]
        sentence3_template = "补强圈外径值应尽可能小，但补强圈最小宽度应 ≥ {}mm；"
        full_sentence3 = sentence3_template.format(edits3[0].text())
        if full_sentence3 in saved:
            cb3.setChecked(True)
        table.setCellWidget(2, 0, make_row(cb3, ["补强圈外径值应尽可能小，但补强圈最小宽度应 ≥", edits3[0], "mm；"]))
        table._bqq_chicun_items.append((cb3, sentence3_template, edits3))

        # 第4条：最大外径比
        cb4 = QCheckBox()
        edits4 = [QLineEdit(defaults["max_ratio"])]
        sentence4_template = "补强圈外径值应尽可能大，但不大于 {}d_op。"
        full_sentence4 = sentence4_template.format(edits4[0].text())
        if full_sentence4 in saved:
            cb4.setChecked(True)
        table.setCellWidget(3, 0, make_row(cb4, ["补强圈外径值应尽可能大，但不大于", edits4[0], "d_op。"]))
        table._bqq_chicun_items.append((cb4, sentence4_template, edits4))

        if not hasattr(table, '_save_connected_bqq_chicun'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_bqq_chicun_config(table, cursor.connection, user_id)
                )
                table._save_connected_bqq_chicun = True

    except Exception as e:
        print(f"[错误] 加载补强圈结构尺寸配置失败: {e}")
def save_bqq_chicun_config(table: QTableWidget, db_conn, user_id):
    try:
        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 补强圈结构尺寸的确定预定义用户表 WHERE user_id = %s", (user_id,))

        for cb, template, edits in table._bqq_chicun_items:
            if cb.isChecked():
                if edits:
                    values = [edit.text().strip() for edit in edits]
                    final_sentence = template.format(*values)
                else:
                    final_sentence = template
                cursor.execute(
                    "INSERT INTO 补强圈结构尺寸的确定预定义用户表 (user_id, value) VALUES (%s, %s)",
                    (user_id, final_sentence)
                )

        db_conn.commit()
        cursor.close()
        print(f"[保存成功] 用户 {user_id} 的补强圈结构尺寸配置已更新")
    except Exception as e:
        print(f"[错误] 保存补强圈结构尺寸配置失败: {e}")
