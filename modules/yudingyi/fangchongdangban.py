from PyQt5.QtWidgets import QWidget, QCheckBox, QLineEdit, QHBoxLayout, QLabel, QTableWidget, QMessageBox
from PyQt5.QtCore import Qt

def fangchong_dangban_config(table: QTableWidget, cursor, user_id):
    try:
        default_ratio = "外径/内径"
        default_val = "1/4"
        checked = False

        # 查询旧值
        cursor.execute("SELECT value FROM 防冲挡板预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        if result:
            checked = True
            text = result[0]
            import re
            m1 = re.search(r"距离不小于(.+?)的", text)
            m2 = re.search(r"的(.+?)。", text)
            if m1: default_ratio = m1.group(1)
            if m2: default_val = m2.group(1)

        table.clear()
        table.setRowCount(1)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["防冲挡板规则"])
        table.verticalHeader().setDefaultSectionSize(50)
        table.horizontalHeader().setStretchLastSection(True)

        cb = QCheckBox("防冲板表面与壳程圆筒内壁距离不小于")
        cb.setChecked(checked)
        edit_ratio = QLineEdit(default_ratio)
        edit_ratio.setMaximumWidth(80)
        edit_val = QLineEdit(default_val)
        edit_val.setMaximumWidth(60)
        label = QLabel("的")
        label2 = QLabel("。")

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.addWidget(cb)
        layout.addWidget(edit_ratio)
        layout.addWidget(label)
        layout.addWidget(edit_val)
        layout.addWidget(label2)
        layout.addStretch()

        table.setCellWidget(0, 0, row)

        table._fangchong_inputs = {
            "cb": cb,
            "edit_ratio": edit_ratio,
            "edit_val": edit_val,
        }

        # 绑定保存按钮
        if not hasattr(table, "_save_connected_fangchong"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_fangchong_dangban_config(table, cursor.connection, user_id)
                )
                table._save_connected_fangchong = True

    except Exception as e:
        print(f"[错误] 加载防冲挡板配置失败: {e}")
def save_fangchong_dangban_config(table: QTableWidget, db_conn, user_id):
    try:
        data = table._fangchong_inputs
        cb = data["cb"]
        ratio = data["edit_ratio"].text().strip()
        val = data["edit_val"].text().strip()

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 防冲挡板预定义用户表 WHERE user_id = %s", (user_id,))

        if cb.isChecked():
            sentence = f"防冲板表面与壳程圆筒内壁距离不小于{ratio}的{val}。"
            cursor.execute(
                "INSERT INTO 防冲挡板预定义用户表 (user_id, value) VALUES (%s, %s)",
                (user_id, sentence)
            )

        db_conn.commit()
        cursor.close()
        QMessageBox.information(table, "提示", "防冲挡板配置已保存成功！")

    except Exception as e:
        print(f"[错误] 保存防冲挡板配置失败: {e}")
        QMessageBox.warning(table, "错误", f"保存防冲挡板配置失败: {e}")
