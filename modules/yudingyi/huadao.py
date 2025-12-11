import re

from PyQt5.QtWidgets import QTableWidget, QLineEdit, QCheckBox, QWidget, QHBoxLayout, QLabel


def huadao_config(table: QTableWidget, cursor, user_id):
    try:
        table.clear()
        table.setRowCount(7)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["滑道配置"])
        table.verticalHeader().setDefaultSectionSize(60)
        table.horizontalHeader().setStretchLastSection(True)

        # 默认值
        defaults = {
            "width_max": "60",
            "threshold": "20",
            "extend": "50",
            "ratio": "2",
            "cb1": False,
            "cb2": False,
            "cb3": True,
            "cb4": False,
            "cb5": False,
            "cb6": False
        }

        # 查询旧值
        cursor.execute("SELECT value FROM 滑道预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        if result:
            text = result[0]
            try:
                m1 = re.search(r"滑道最大宽度(\d+)mm", text)
                if m1: defaults["width_max"] = m1.group(1)
                m2 = re.search(r"滑道宽度>(\d+)mm", text)
                if m2: defaults["threshold"] = m2.group(1)
                m3 = re.search(r"伸出.*?(\d+)mm", text)
                if m3: defaults["extend"] = m3.group(1)
                m4 = re.search(r"滑道宽度/厚度≥(\d+)", text)
                if m4: defaults["ratio"] = m4.group(1)
                defaults["cb1"] = "滑道最大宽度" in text
                defaults["cb2"] = "使用板式滑道" in text
                defaults["cb3"] = "max（滑道最小厚度" in text
                defaults["cb4"] = "不设置滑道" in text
                defaults["cb5"] = "伸出折流板/支持板最小值" in text
                defaults["cb6"] = "滑道与固定管板焊接连接" in text
            except Exception as e:
                print("[警告] 解析旧值失败：", e)

        cb1 = QCheckBox("滑道最大宽度")
        edit1 = QLineEdit(defaults["width_max"])
        edit1.setMaximumWidth(60)
        cb1.setChecked(defaults["cb1"])
        row1 = QWidget()
        h1 = QHBoxLayout(row1)
        h1.setContentsMargins(10, 0, 10, 0)
        h1.addWidget(cb1)
        h1.addWidget(edit1)
        h1.addWidget(QLabel("mm"))
        h1.addStretch()
        table.setCellWidget(0, 0, row1)

        cb2 = QCheckBox("使用板式滑道")
        edit2 = QLineEdit(defaults["threshold"])
        edit2.setMaximumWidth(60)
        cb2.setChecked(defaults["cb2"])
        row2 = QWidget()
        h2 = QHBoxLayout(row2)
        h2.setContentsMargins(10, 0, 10, 0)
        h2.addWidget(QLabel("当滑道宽度 >"))
        h2.addWidget(edit2)
        h2.addWidget(QLabel("mm 时，"))
        h2.addWidget(cb2)
        h2.addWidget(QLabel("，否则使用圆钢。"))
        h2.addStretch()
        table.setCellWidget(1, 0, row2)

        cb3 = QCheckBox("max（滑道最小厚度，折流板厚度）")
        cb4 = QCheckBox("滑道最小厚度")
        cb5 = QCheckBox("折流板厚度")
        cb3.setChecked(defaults["cb3"])
        row3 = QWidget()
        h3 = QHBoxLayout(row3)
        h3.setContentsMargins(10, 0, 10, 0)
        h3.addWidget(QLabel("滑道使用厚度："))
        h3.addWidget(cb3)
        h3.addWidget(cb4)
        h3.addWidget(cb5)
        h3.addStretch()
        table.setCellWidget(2, 0, row3)

        cb6 = QCheckBox("对于浮头式热交换器，当旁路挡板设置在垂直方位且数量 > 2 个时，不设置滑道")
        cb6.setChecked(defaults["cb4"])
        table.setCellWidget(3, 0, cb6)

        row4 = QWidget()
        h4 = QHBoxLayout(row4)
        h4.setContentsMargins(10, 0, 10, 0)
        edit3 = QLineEdit(defaults["extend"])
        edit3.setMaximumWidth(60)
        cb7 = QCheckBox("滑道伸出折流板/支持板最小值")
        cb7.setChecked(defaults["cb5"])
        h4.addWidget(cb7)
        h4.addWidget(edit3)
        h4.addWidget(QLabel("mm"))
        h4.addStretch()
        table.setCellWidget(4, 0, row4)

        cb8 = QCheckBox("滑道与固定管板焊接连接")
        cb8.setChecked(defaults["cb6"])
        table.setCellWidget(5, 0, cb8)

        row5 = QWidget()
        h5 = QHBoxLayout(row5)
        h5.setContentsMargins(10, 0, 10, 0)
        edit4 = QLineEdit(defaults["ratio"])
        edit4.setMaximumWidth(60)
        h5.addWidget(QLabel("滑道宽度/厚度 ≥"))
        h5.addWidget(edit4)
        h5.addStretch()
        table.setCellWidget(6, 0, row5)

        table._huadao_inputs = {
            "cb1": cb1, "edit1": edit1,
            "edit2": edit2, "cb2": cb2,
            "cb3": cb3, "cb4": cb4, "cb5": cb5,
            "cb6": cb6, "cb7": cb7, "edit3": edit3,
            "cb8": cb8, "edit4": edit4
        }

        if not hasattr(table, "_save_connected_huadao"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_huadao_config(table, cursor.connection, user_id)
                )
                table._save_connected_huadao = True

    except Exception as e:
        print(f"[错误] 加载滑道配置失败: {e}")

def save_huadao_config(table: QTableWidget, db_conn, user_id):
    try:
        data = table._huadao_inputs
        lines = []

        if data["cb1"].isChecked():
            lines.append(f"滑道最大宽度{data['edit1'].text()}mm。")
        if data["cb2"].isChecked():
            lines.append(f"当滑道宽度>{data['edit2'].text()}mm时，使用板式滑道，否则使用圆钢。")

        sub_opts = []
        if data["cb3"].isChecked(): sub_opts.append("max（滑道最小厚度，折流板厚度）")
        if data["cb4"].isChecked(): sub_opts.append("滑道最小厚度")
        if data["cb5"].isChecked(): sub_opts.append("折流板厚度")
        if sub_opts:
            lines.append("滑道使用厚度：" + "，".join(sub_opts) + "。")

        if data["cb6"].isChecked():
            lines.append("对于浮头式热交换器，当旁路挡板设置在垂直方位且数量 > 2 个时，不设置滑道。")
        if data["cb7"].isChecked():
            lines.append(f"滑道伸出折流板/支持板最小值{data['edit3'].text()}mm。")
        if data["cb8"].isChecked():
            lines.append("滑道与固定管板焊接连接。")

        lines.append(f"滑道宽度/厚度≥{data['edit4'].text()}。")
        value = "\n".join(lines)

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 滑道预定义用户表 WHERE user_id = %s", (user_id,))
        cursor.execute("INSERT INTO 滑道预定义用户表 (user_id, value) VALUES (%s, %s)", (user_id, value))
        db_conn.commit()
        cursor.close()
        print("[保存成功] 滑道配置已更新")

    except Exception as e:
        print(f"[错误] 保存滑道配置失败: {e}")

