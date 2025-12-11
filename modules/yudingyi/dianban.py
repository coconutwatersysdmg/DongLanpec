from PyQt5.QtWidgets import QWidget, QLabel, QLineEdit, QCheckBox, QTableWidget, QHBoxLayout
from PyQt5.QtCore import Qt
import re

def dianban_guiize_config(table: QTableWidget, cursor, user_id):
    from PyQt5.QtWidgets import QWidget, QLabel, QLineEdit, QCheckBox, QHBoxLayout
    from PyQt5.QtCore import Qt
    import re

    try:
        default_val = "20"
        default_check1 = True
        default_check2 = False

        cursor.execute("SELECT value FROM 垫板预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        if result:
            try:
                val = result[0]
                numbers = re.findall(r"(\d+\.?\d*)mm", val)
                if numbers:
                    default_val = numbers[0]
                default_check1 = "吊耳" in val
                default_check2 = "支座" in val
            except Exception as e:
                print(f"[警告] 解析旧值失败: {e}")

        table.clear()
        table.setRowCount(3)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["垫板厚度确定规则"])
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        # ✅ 创建3个独立 QLineEdit
        input1 = QLineEdit()
        input2 = QLineEdit()
        input3 = QLineEdit()
        for box in [input1, input2, input3]:
            box.setText(default_val)

        def sync_all(text):
            for box in [input1, input2, input3]:
                if box.text() != text:
                    box.setText(text)

        # ✅ 联动更新
        input1.textChanged.connect(sync_all)
        input2.textChanged.connect(sync_all)
        input3.textChanged.connect(sync_all)

        # 行1
        row1 = QWidget()
        hbox1 = QHBoxLayout(row1)
        hbox1.setContentsMargins(10, 0, 10, 0)
        hbox1.addWidget(QLabel("当容器封头或筒节的名义厚度 ≤"))
        hbox1.addWidget(input1)
        hbox1.addWidget(QLabel("mm 时，垫板厚度与容器封头或筒节名义厚度相同；"))
        hbox1.addStretch()
        table.setCellWidget(0, 0, row1)

        # 行2
        row2 = QWidget()
        hbox2 = QHBoxLayout(row2)
        hbox2.setContentsMargins(10, 0, 10, 0)
        hbox2.addWidget(QLabel("当容器封头或筒节的名义厚度 >"))
        hbox2.addWidget(input2)
        hbox2.addWidget(QLabel("mm 时，垫板厚度取"))
        hbox2.addWidget(input3)
        hbox2.addWidget(QLabel("mm。"))
        hbox2.addStretch()
        table.setCellWidget(1, 0, row2)

        # 行3
        row3 = QWidget()
        hbox3 = QHBoxLayout(row3)
        hbox3.setContentsMargins(10, 0, 10, 0)
        hbox3.addWidget(QLabel("适用元件（根据元件需求）包括："))
        cb1 = QCheckBox("吊耳")
        cb1.setChecked(default_check1)
        cb2 = QCheckBox("支座")
        cb2.setChecked(default_check2)
        hbox3.addWidget(cb1)
        hbox3.addWidget(cb2)
        hbox3.addStretch()
        table.setCellWidget(2, 0, row3)

        # ✅ 存引用
        table._dianban_inputs = {
            "inputs": (input1, input2, input3),
            "check1": cb1,
            "check2": cb2,
        }

        if not hasattr(table, "_save_connected_dianban"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_dianban_guiize_config(table, cursor.connection, user_id)
                )
                table._save_connected_dianban = True

    except Exception as e:
        print(f"[错误] 加载垫板厚度配置失败: {e}")






import re

def clean_number(text):
    match = re.search(r"(\d+\.?\d*)", text.strip())
    return match.group(1) if match else ""

def save_dianban_guiize_config(table, db_conn, user_id):
    try:
        data = table._dianban_inputs
        inputs = data["inputs"]
        val = clean_number(inputs[0].text())  # 任意一个即可，三个是同步的

        parts = [
            f"当容器封头或筒节的名义厚度 ≤ {val}mm 时，垫板厚度与容器封头或筒节名义厚度相同；",
            f"当容器封头或筒节的名义厚度 > {val}mm 时，垫板厚度取 {val}mm。"
        ]

        selected = []
        if data["check1"].isChecked():
            selected.append("吊耳")
        if data["check2"].isChecked():
            selected.append("支座")
        if selected:
            parts.append("适用元件（根据元件需求）包括：" + "、".join(selected) + "。")

        value = "\n".join(parts)

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 垫板预定义用户表 WHERE user_id = %s", (user_id,))
        cursor.execute(
            "INSERT INTO 垫板预定义用户表 (user_id, value) VALUES (%s, %s)",
            (user_id, value)
        )
        db_conn.commit()
        cursor.close()

        print("[保存成功] 垫板配置规则已更新")

    except Exception as e:
        print(f"[错误] 保存垫板配置失败: {e}")
