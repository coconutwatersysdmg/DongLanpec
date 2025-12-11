import re

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem, QLineEdit, QHBoxLayout, QWidget, QCheckBox, QLabel


def zheliuban_config(table: QTableWidget, cursor, user_id):
    try:
        default1 = "3"
        default2 = "50"
        default3 = "4"
        default4 = "3"

        cursor.execute("SELECT value FROM 折流板预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        if result:
            text = result[0]
            try:
                m1 = re.search(r"腐蚀裕量≤(\d+\.?\d*)mm", text)
                if m1: default1 = m1.group(1)

                m2 = re.search(r"间距最小值为(\d+\.?\d*)mm", text)
                if m2: default2 = m2.group(1)

                m3 = re.search(r"腐蚀裕量C2≥(\d+\.?\d*)mm", text)
                if m3: default3 = m3.group(1)

                m4 = re.search(r"C2-(\d+\.?\d*)", text)
                if m4: default4 = m4.group(1)
            except Exception as e:
                print("[警告] 折流板规则解析失败：", e)

        table.clear()
        table.setRowCount(4)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["折流板设置规则"])
        table.verticalHeader().setDefaultSectionSize(50)
        table.horizontalHeader().setStretchLastSection(True)

        edits = []

        row_texts = [
            ("当壳程腐蚀裕量≤", default1, "mm时，在浮头式热交换器管束靠近浮动端设置整圆的支持板。"),
            ("允许管束组成元件中，第一/最后一块折流板或导流筒至管板间距最小值为", default2, "mm；"),
            ("当折流板/支持板材质为碳钢或低合金钢且壳程腐蚀裕量C2≥", default3, "mm时，折流板厚度取GB/T 151标准中规定的最小厚度值+2×(C2-", default4, ")"),
            ("当折流板缺口为竖直方向时，靠近管板的第一块折流板缺口在右侧（90°方向）。",)
        ]

        for i, rt in enumerate(row_texts):
            if len(rt) == 3:
                label1, val, label2 = rt
                edit = QLineEdit(val)
                edit.setMaximumWidth(60)
                row = QWidget()
                h = QHBoxLayout(row)
                h.setContentsMargins(10, 0, 10, 0)
                h.addWidget(QCheckBox())
                h.addWidget(QLabel(label1))
                h.addWidget(edit)
                h.addWidget(QLabel(label2))
                h.addStretch()
                edits.append((edit, True))
                table.setCellWidget(i, 0, row)
            elif len(rt) == 5:
                label1, val1, label2, val2, label3 = rt
                e1 = QLineEdit(val1)
                e1.setMaximumWidth(60)
                e2 = QLineEdit(val2)
                e2.setMaximumWidth(60)
                row = QWidget()
                h = QHBoxLayout(row)
                h.setContentsMargins(10, 0, 10, 0)
                h.addWidget(QCheckBox())
                h.addWidget(QLabel(label1))
                h.addWidget(e1)
                h.addWidget(QLabel(label2))
                h.addWidget(e2)
                h.addWidget(QLabel(label3))
                h.addStretch()
                edits.append(((e1, e2), True))
                table.setCellWidget(i, 0, row)
            else:
                row = QWidget()
                h = QHBoxLayout(row)
                h.setContentsMargins(10, 0, 10, 0)
                cb = QCheckBox(rt[0])
                cb.setChecked(True)
                h.addWidget(cb)
                h.addStretch()
                edits.append((cb, False))  # ✅ 改为 tuple 且仅存 QCheckBox
                table.setCellWidget(i, 0, row)

        table._zheliuban_inputs = edits

        if not hasattr(table, "_save_connected_zheliuban"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_zheliuban_config(table, cursor.connection, user_id)
                )
                table._save_connected_zheliuban = True

    except Exception as e:
        print(f"[错误] 加载折流板配置失败: {e}")

def save_zheliuban_config(table: QTableWidget, db_conn, user_id):
    try:
        inputs = table._zheliuban_inputs
        lines = []

        cb1 = table.cellWidget(0, 0).findChild(QCheckBox)
        if cb1 and cb1.isChecked():
            val = inputs[0][0].text().strip()
            lines.append(f"当壳程腐蚀裕量≤{val}mm时，在浮头式热交换器管束靠近浮动端设置整圆的支持板。")

        cb2 = table.cellWidget(1, 0).findChild(QCheckBox)
        if cb2 and cb2.isChecked():
            val = inputs[1][0].text().strip()
            lines.append(f"允许管束组成元件中，第一/最后一块折流板或导流筒至管板间距最小值为{val}mm；")

        cb3 = table.cellWidget(2, 0).findChild(QCheckBox)
        if cb3 and cb3.isChecked():
            val1 = inputs[2][0][0].text().strip()
            val2 = inputs[2][0][1].text().strip()
            lines.append(f"当折流板/支持板材质为碳钢或低合金钢且壳程腐蚀裕量C2≥{val1}mm时，折流板厚度取GB/T 151标准中规定的最小厚度值+2×(C2-{val2})")

        cb4 = inputs[3][0]
        if isinstance(cb4, QCheckBox) and cb4.isChecked():
            lines.append("当折流板缺口为竖直方向时，靠近管板的第一块折流板缺口在右侧（90°方向）。")

        value = "\n".join(lines)

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 折流板预定义用户表 WHERE user_id = %s", (user_id,))
        cursor.execute("INSERT INTO 折流板预定义用户表 (user_id, value) VALUES (%s, %s)", (user_id, value))
        db_conn.commit()
        cursor.close()
        print("[保存成功] 折流板规则更新")

    except Exception as e:
        print(f"[错误] 保存折流板配置失败: {e}")
