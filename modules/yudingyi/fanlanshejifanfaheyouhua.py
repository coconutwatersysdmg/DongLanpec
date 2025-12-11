from PyQt5.QtWidgets import QWidget, QLabel, QLineEdit, QHBoxLayout, QVBoxLayout, QRadioButton, QCheckBox, QTableWidget
from PyQt5.QtCore import Qt
import json

from PyQt5.QtWidgets import QWidget, QLabel, QLineEdit, QHBoxLayout, QVBoxLayout, QRadioButton, QCheckBox, QTableWidget
from PyQt5.QtCore import Qt

def create_falan_sheji_youhua_config(table: QTableWidget, cursor, user_id, config_type):
    try:
        table.clear()
        table.setRowCount(4)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["法兰设计与优化配置"])

        # ---- 加载旧值 ----
        cursor.execute("SELECT * FROM 法兰设计方法和优化原则预定义用户表 WHERE user_id=%s", (user_id,))
        result = cursor.fetchone()
        selected_methods = []
        selected_optimization = ""
        if result:
            selected_methods = result[1].split("，") if result[1] else []
            selected_optimization = result[2] or ""

        # ---- 第1行：设计方法多选（最多3项） ----
        row1 = QWidget()
        layout1 = QVBoxLayout(row1)
        layout1.setContentsMargins(5, 5, 5, 5)
        label1 = QLabel("1. 容器法兰的设计方法（可多选）")
        label1.setAlignment(Qt.AlignLeft)
        layout1.addWidget(label1)

        options1 = [
            "按NB/T 47020~47027《压力容器法兰、垫片、紧固件》标准选用",
            "按NB/T 47020~47027《压力容器法兰、垫片、紧固件》标准选用并按GB/T 150.3进行校核（校核通过则选用标准参数，不通过或无法选中标准法兰时则进行法兰设计计算）",
            "依据“附加余量”和“法兰优化原则”要求，按GB/T 150.3相关条款对法兰进行设计计算"
        ]
        checkboxes1 = []
        for opt in options1:
            cb = QCheckBox(opt)
            cb.setChecked(opt in selected_methods)
            cb.setStyleSheet("QCheckBox { text-align: left; }")
            layout1.addWidget(cb)
            checkboxes1.append(cb)
        table.setCellWidget(0, 0, row1)

        # ---- 第2行：优化原则 ----
        row2 = QWidget()
        layout2 = QVBoxLayout(row2)
        layout2.setContentsMargins(5, 5, 5, 5)
        label2 = QLabel("2. 对焊法兰优化原则（6选1）")
        label2.setAlignment(Qt.AlignLeft)
        layout2.addWidget(label2)

        radio_buttons = []
        radio_inputs = []

        # 单选项（前3项）
        for text in ["成型重量最小", "毛坯重量最小", "法兰总高度H最小"]:
            r = QRadioButton(text)
            r.setStyleSheet("QRadioButton { text-align: left; }")
            layout2.addWidget(r)
            radio_buttons.append(r)
            radio_inputs.append(None)
            if text in selected_optimization:
                r.setChecked(True)

        # 三个带输入框的单选项
        def make_radio_row(prefix, default_val, unit, suffix, keyword):
            container = QWidget()
            h = QHBoxLayout(container)
            h.setContentsMargins(0, 0, 0, 0)
            r = QRadioButton()
            val_input = QLineEdit(default_val)
            val_input.setFixedWidth(60)
            h.addWidget(r)
            h.addWidget(QLabel(prefix))
            h.addWidget(val_input)
            h.addWidget(QLabel(unit + suffix))
            h.addStretch()
            container.setLayout(h)
            layout2.addWidget(container)

            # 回显判断
            if keyword in selected_optimization:
                r.setChecked(True)
                if "(" in selected_optimization:
                    val = selected_optimization.split("(")[1].split(")")[0]
                    val_input.setText(val)

            return r, val_input

        cr1 = make_radio_row("在法兰总高度H最小范围(", "5", "mm", ")内，成型重量最小", "H最小范围")
        cr2 = make_radio_row("在法兰成型重量最小范围(", "50", "kg", ")内，毛坯重量最小", "成型重量最小范围")
        cr3 = make_radio_row("在法兰毛坯重量最小范围(", "50", "kg", ")内，成型重量最小", "毛坯重量最小范围")

        for r, i in [cr1, cr2, cr3]:
            radio_buttons.append(r)
            radio_inputs.append(i)

        table.setCellWidget(1, 0, row2)

        # ---- 第3行：结构约束 ----
        row3 = QWidget()
        layout3 = QHBoxLayout(row3)
        layout3.setContentsMargins(5, 0, 0, 0)
        cb_structure = QCheckBox("结构：法兰盘厚度 δ / 法兰总高度 H ≤")
        val_input_structure = QLineEdit("0.65")
        val_input_structure.setFixedWidth(60)
        if "δ / 法兰总高度 H ≤" in selected_optimization:
            cb_structure.setChecked(True)
            val_input_structure.setText(selected_optimization.split("≤")[1].split("。")[0])
        layout3.addWidget(cb_structure)
        layout3.addWidget(val_input_structure)
        layout3.addStretch()
        table.setCellWidget(2, 0, row3)

        # ---- 第4行：MAWP ----
        row4 = QWidget()
        layout4 = QHBoxLayout(row4)
        layout4.setContentsMargins(5, 0, 0, 0)
        cb_mawp = QCheckBox("容器的最高允许工作压力(MAWP)不由容器法兰控制")
        cb_mawp.setChecked("MAWP" in selected_optimization)
        layout4.addWidget(cb_mawp)
        layout4.addStretch()
        table.setCellWidget(3, 0, row4)

        # ---- 保存状态 ----
        table._falan_config_state = {
            "checkboxes1": checkboxes1,
            "radio_buttons": radio_buttons,
            "radio_inputs": radio_inputs,
            "structure_cb": cb_structure,
            "structure_val": val_input_structure,
            "mawp_cb": cb_mawp
        }

        # ---- 行高：第2行更高 ----
        for i in range(table.rowCount()):
            if i == 1:
                table.setRowHeight(i, 200)
            elif i ==0:
                table.setRowHeight(i, 130)
            else:
                table.setRowHeight(i, 30)

        # ---- 绑定保存按钮 ----
        if not hasattr(table, "_save_connected_falan"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(lambda: save_falan_sheji_youhua_config(
                    table, cursor.connection, user_id, config_type
                ))
                table._save_connected_falan = True

    except Exception as e:
        print("[错误] 加载法兰设计与优化配置失败：", e)
def save_falan_sheji_youhua_config(table: QTableWidget, db_conn, user_id, config_type):
    try:
        state = table._falan_config_state
        # --- 设计方法 ---
        selected_methods = [cb.text() for cb in state["checkboxes1"] if cb.isChecked()]
        methods_str = "，".join(selected_methods)

        # --- 优化原则 ---
        selected_optimization = ""
        for i, rb in enumerate(state["radio_buttons"]):
            if rb.isChecked():
                if state["radio_inputs"][i] is None:
                    selected_optimization = rb.text()
                else:
                    val = state["radio_inputs"][i].text()
                    label = rb.parentWidget().findChildren(QLabel)[0].text()  # eg: "在法兰毛坯..."
                    unit = rb.parentWidget().findChildren(QLabel)[2].text()   # eg: ")内，..."
                    selected_optimization = f"{label}({val}){unit}"
                break

        # --- 附加条件（结构、MAWP） ---
        if state["structure_cb"].isChecked():
            val = state["structure_val"].text()
            selected_optimization += f"，结构：法兰盘厚度 δ / 法兰总高度 H ≤{val}。"
        if state["mawp_cb"].isChecked():
            selected_optimization += "，容器的最高允许工作压力(MAWP)不由容器法兰控制。"

        # --- 保存到表 ---
        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 法兰设计方法和优化原则预定义用户表 WHERE user_id=%s", (user_id,))
        cursor.execute("""
            INSERT INTO 法兰设计方法和优化原则预定义用户表 
            (user_id, 设计方法, 优化原则)
            VALUES (%s, %s, %s)
        """, (user_id, methods_str, selected_optimization))
        db_conn.commit()
        cursor.close()

        print("[保存成功] 法兰设计与优化配置")

    except Exception as e:
        print("[错误] 保存法兰设计与优化配置失败：", e)
