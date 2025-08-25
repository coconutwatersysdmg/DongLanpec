from PyQt5.QtWidgets import QWidget, QLabel, QLineEdit, QHBoxLayout, QTableWidget, QTableWidgetItem
from PyQt5.QtCore import Qt

def zhongxiaoxingduanjiandingyi(table: QTableWidget, cursor, user_id, config_type):
    try:
        table.clear()
        table.setRowCount(4)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["限制条件"])
        table.verticalHeader().setDefaultSectionSize(50)
        table.horizontalHeader().setStretchLastSection(True)

        # 默认值
        pn, dn = "2.5", "600"
        weight1 = "800"
        dia2, weight2 = "200", "1500"

        # 查询旧值
        cursor.execute("""
            SELECT value FROM user_config WHERE user_id=%s AND config_type=%s
        """, (user_id, config_type))
        result = cursor.fetchone()
        if result:
            try:
                val = result[0]
                pn = val.split("PN")[1].split("(")[0]
                dn = val.split("DN")[1].split("的")[0]
                weight1 = val.split("重量不大于")[1].split("kg")[0]
                dia2 = val.split("直径不大于")[1].split("mm")[0]
                weight2 = val.split("重量不大于")[2].split("kg")[0]
            except Exception as e:
                print(f"[警告] 旧值解析失败，使用默认值: {e}")

        def build_row(prefix, inputs, suffix=""):
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(10, 0, 0, 0)
            layout.addWidget(QLabel(prefix))
            for edit in inputs:
                edit.setMaximumWidth(80)
                layout.addWidget(edit)
            if suffix:
                layout.addWidget(QLabel(suffix))
            layout.addStretch()
            return widget

        # 备注行
        table.setItem(0, 0, QTableWidgetItem("备注：满足以下三条条件之一即可"))
        table.item(0, 0).setFlags(Qt.ItemIsEnabled)

        # 第1条
        pn_input = QLineEdit(pn)
        dn_input = QLineEdit(dn)
        row1 = build_row("规格不大于 PN", [pn_input], f"(MPa)、DN{dn_input.text()} 的法兰或相当于该尺寸的其他环形锻件；")
        table.setCellWidget(1, 0, row1)

        # 第2条
        weight1_input = QLineEdit(weight1)
        row2 = build_row("重量不大于", [weight1_input], "kg 的饼状、筒型和异型锻件（如三通、阀体等）；")
        table.setCellWidget(2, 0, row2)

        # 第3条
        dia_input = QLineEdit(dia2)
        weight2_input = QLineEdit(weight2)
        row3 = build_row("直径不大于", [dia_input], f"mm 且重量不大于 {weight2_input.text()}kg 的条形或轴类锻件。")
        table.setCellWidget(3, 0, row3)

        table._hx_inputs = {
            "pn": pn_input, "dn": dn_input,
            "weight1": weight1_input,
            "dia2": dia_input, "weight2": weight2_input
        }

        if not hasattr(table, '_save_connected_hx'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_huanxingduanjian(table, cursor.connection, user_id, config_type))
                table._save_connected_hx = True

    except Exception as e:
        print(f"[错误] 加载环形锻件限制失败: {e}")


def save_huanxingduanjian(table: QTableWidget, db_conn, user_id, config_type):
    try:
        i = table._hx_inputs
        value_str = (
            f"备注：满足以下三条条件之一即可。"
            f"规格不大于 PN{i['pn'].text()}(MPa)、DN{i['dn'].text()} 的法兰或相当于该尺寸的其他环形锻件；"
            f"重量不大于 {i['weight1'].text()}kg 的饼状、筒型和异型锻件（如三通、阀体等）；"
            f"直径不大于 {i['dia2'].text()}mm 且重量不大于 {i['weight2'].text()}kg 的条形或轴类锻件。"
        )

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM user_config WHERE user_id = %s AND config_type = %s", (user_id, config_type))
        cursor.execute(
            "INSERT INTO user_config (user_id, config_type, value) VALUES (%s, %s, %s)",
            (user_id, config_type, value_str)
        )
        db_conn.commit()
        cursor.close()
        print(f"[保存成功] {config_type}: {value_str}")
    except Exception as e:
        print(f"[错误] 保存环形锻件配置失败: {e}")
