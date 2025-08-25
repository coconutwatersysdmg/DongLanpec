from PyQt5.QtWidgets import QWidget, QLabel, QLineEdit, QCheckBox, QTableWidget, QHBoxLayout
import re

def ignore_futougaigai_config(table: QTableWidget, cursor, user_id):
    try:
        default1 = "2"
        default2 = "附加余量值"
        default3 = "0.5"
        check3 = True

        cursor.execute("SELECT value FROM 忽略浮头盖设计余量预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        if result:
            text = result[0]
            try:
                m1 = re.search(r"设计厚度-厚度负偏差）>(\d+\.?\d*)mm", text)
                if m1: default1 = m1.group(1)

                m2 = re.search(r"≥(.+?)时", text)
                if m2: default2 = m2.group(1)

                m3 = re.findall(r"设计厚度-厚度负偏差）>(\d+\.?\d*)mm", text)
                if len(m3) >= 2: default3 = m3[-1]

                check3 = "如球冠封头厚度按附加余量值增加将导致" in text
            except Exception as e:
                print("[警告] 解析旧值失败：", e)

        table.clear()
        table.setRowCount(3)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["忽略浮头盖设计余量规则"])
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        edit1 = QLineEdit(default1)
        edit1.setMaximumWidth(60)
        row1 = QWidget()
        h1 = QHBoxLayout(row1)
        h1.setContentsMargins(10, 0, 10, 0)
        h1.addWidget(QLabel("如浮头法兰按附加余量值增加将导致法兰材料许用应力值改变，且考虑厚度附加余量前，（法兰名义厚度-设计厚度-厚度负偏差）>"))
        h1.addWidget(edit1)
        h1.addWidget(QLabel("mm 时。"))
        h1.addStretch()
        table.setCellWidget(0, 0, row1)

        edit2 = QLineEdit(default2)
        edit2.setMaximumWidth(100)
        row2 = QWidget()
        h2 = QHBoxLayout(row2)
        h2.setContentsMargins(10, 0, 10, 0)
        h2.addWidget(QLabel("如球冠封头考虑厚度附加余量前，（球冠封头名义厚度-设计厚度-厚度负偏差）≥"))
        h2.addWidget(edit2)
        h2.addWidget(QLabel("时；"))
        h2.addStretch()
        table.setCellWidget(1, 0, row2)

        edit3 = QLineEdit(default3)
        edit3.setMaximumWidth(60)
        cb3 = QCheckBox("如球冠封头厚度按附加余量值增加将导致球冠封头材料许用应力值改变，且考虑厚度附加余量前，（球冠封头名义厚度-设计厚度-厚度负偏差）>")
        cb3.setChecked(check3)
        row3 = QWidget()
        h3 = QHBoxLayout(row3)
        h3.setContentsMargins(10, 0, 10, 0)
        h3.addWidget(cb3)
        h3.addWidget(edit3)
        h3.addWidget(QLabel("mm 时。"))
        h3.addStretch()
        table.setCellWidget(2, 0, row3)

        # 保存引用
        table._futou_ignore_inputs = {
            "edit1": edit1,
            "edit2": edit2,
            "edit3": edit3,
            "cb3": cb3
        }

        if not hasattr(table, "_save_connected_futou_ignore"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_ignore_futougaigai_config(table, cursor.connection, user_id)
                )
                table._save_connected_futou_ignore = True

    except Exception as e:
        print(f"[错误] 加载忽略浮头盖配置失败: {e}")
def save_ignore_futougaigai_config(table: QTableWidget, db_conn, user_id):
    try:
        data = table._futou_ignore_inputs
        v1 = data["edit1"].text().strip()
        v2 = data["edit2"].text().strip()
        v3 = data["edit3"].text().strip()
        cb3 = data["cb3"].isChecked()

        lines = [
            f"如浮头法兰按附加余量值增加将导致法兰材料许用应力值改变，且考虑厚度附加余量前，（法兰名义厚度-设计厚度-厚度负偏差）>{v1}mm 时。",
            f"如球冠封头考虑厚度附加余量前，（球冠封头名义厚度-设计厚度-厚度负偏差）≥{v2}时；"
        ]
        if cb3:
            lines.append(
                f"如球冠封头厚度按附加余量值增加将导致球冠封头材料许用应力值改变，且考虑厚度附加余量前，（球冠封头名义厚度-设计厚度-厚度负偏差）>{v3}mm 时。"
            )

        value = "\n".join(lines)

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 忽略浮头盖设计余量预定义用户表 WHERE user_id = %s", (user_id,))
        cursor.execute(
            "INSERT INTO 忽略浮头盖设计余量预定义用户表 (user_id, value) VALUES (%s, %s)",
            (user_id, value)
        )
        db_conn.commit()
        cursor.close()
        print("[保存成功] 忽略浮头盖设计余量规则更新")

    except Exception as e:
        print(f"[错误] 保存忽略浮头盖配置失败: {e}")
