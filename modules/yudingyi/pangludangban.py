from PyQt5.QtWidgets import QWidget, QLabel, QCheckBox, QLineEdit, QTableWidget, QHBoxLayout, QVBoxLayout
from PyQt5.QtCore import Qt

def bypass_dangban_config(table: QTableWidget, cursor, user_id):
    try:
        # 默认值
        default_thickness = "6"
        checkbox1_state = False
        checkbox2_state = False
        option_selected = []

        # 查询旧值
        cursor.execute("SELECT value FROM 旁路挡板预定义用户表 WHERE user_id=%s", (user_id,))
        result = cursor.fetchone()
        if result:
            value = result[0]
            checkbox1_state = "正方形(90°)" in value
            checkbox2_state = "最大许用厚度值" in value
            thickness_match = re.search(r"最大许用厚度值取(\d+\.?\d*)mm", value)
            if thickness_match:
                default_thickness = thickness_match.group(1)
            for opt in ["max(最大给定厚度值，折流板厚度)", "最大给定厚度值", "折流板厚度"]:
                if opt in value:
                    option_selected.append(opt)

        table.clear()
        table.setRowCount(3)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["旁路挡板配置"])
        table.verticalHeader().setDefaultSectionSize(50)
        table.horizontalHeader().setStretchLastSection(True)

        # 第一条自然语句
        cb1 = QCheckBox("对正方形(90°)和转角正方形(45°)管排列旁路挡板的设置应保持连续清扫通道。")
        cb1.setChecked(checkbox1_state)
        table.setCellWidget(0, 0, cb1)

        # 第二条自然语句
        cb2 = QCheckBox("旁路挡板最大许用厚度值取")
        edit_thickness = QLineEdit(default_thickness)
        edit_thickness.setMaximumWidth(60)
        label_mm = QLabel("mm。")
        row2 = QWidget()
        h2 = QHBoxLayout(row2)
        h2.setContentsMargins(10, 0, 10, 0)
        h2.addWidget(cb2)
        h2.addWidget(edit_thickness)
        h2.addWidget(label_mm)
        h2.addStretch()
        cb2.setChecked(checkbox2_state)
        table.setCellWidget(1, 0, row2)

        # 第三条自然语句（多选）
        label3 = QLabel("旁路挡板厚度的确定：")
        opts = ["max(最大给定厚度值，折流板厚度)", "最大给定厚度值", "折流板厚度"]
        checkboxes = [QCheckBox(opt) for opt in opts]
        for cb in checkboxes:
            if cb.text() in option_selected:
                cb.setChecked(True)
        row3 = QWidget()
        h3 = QHBoxLayout(row3)
        h3.setContentsMargins(10, 0, 10, 0)
        h3.addWidget(label3)
        for cb in checkboxes:
            h3.addWidget(cb)
        h3.addStretch()
        table.setCellWidget(2, 0, row3)

        table._bypass_config_refs = {
            "cb1": cb1,
            "cb2": cb2,
            "edit_thickness": edit_thickness,
            "check_options": checkboxes
        }

        if not hasattr(table, "_save_connected_bypass"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(lambda: save_bypass_dangban_config(table, cursor.connection, user_id))
                table._save_connected_bypass = True

    except Exception as e:
        print("[错误] 加载旁路挡板配置失败:", e)

def save_bypass_dangban_config(table: QTableWidget, db_conn, user_id):
    try:
        data = table._bypass_config_refs
        v1 = data["cb1"].isChecked()
        v2 = data["cb2"].isChecked()
        v3 = data["edit_thickness"].text().strip()
        selected_opts = [cb.text() for cb in data["check_options"] if cb.isChecked()]

        lines = []
        if v1:
            lines.append("对正方形(90°)和转角正方形(45°)管排列旁路挡板的设置应保持连续清扫通道。")
        if v2:
            lines.append(f"旁路挡板最大许用厚度值取{v3}mm。")
        if selected_opts:
            opt_line = "旁路挡板厚度的确定：" + "；".join(selected_opts) + "。"
            lines.append(opt_line)

        value = "\n".join(lines)
        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 旁路挡板预定义用户表 WHERE user_id = %s", (user_id,))
        cursor.execute("INSERT INTO 旁路挡板预定义用户表 (user_id, value) VALUES (%s, %s)", (user_id, value))
        db_conn.commit()
        cursor.close()
        print("[保存成功] 旁路挡板规则已更新")
    except Exception as e:
        print("[错误] 保存旁路挡板配置失败:", e)
