from PyQt5.QtWidgets import QWidget, QTableWidgetItem, QLineEdit, QLabel, QHBoxLayout, QVBoxLayout, QTableWidget
from PyQt5.QtCore import Qt

def futou_zuixiao_juli_config(table: QTableWidget, cursor, user_id):
    try:
        # 默认值
        dmin_val, hmin_val = "10", "5"

        # 查询用户表中是否已有记录
        cursor.execute("SELECT * FROM 浮头最小距离预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        if result:
            try:
                dmin_val = result[1].replace("mm", "").strip()
                hmin_val = result[2].replace("mm", "").strip()
            except Exception as e:
                print(f"[警告] 解析旧值失败，使用默认值: {e}")

        # 设置表格
        table.clear()
        table.setRowCount(2)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["浮头最小距离配置"])
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setDefaultSectionSize(60)  # ✅ 增加行高

        def build_row(label_text, lineedit, suffix):
            lineedit.setMaximumWidth(60)  # ✅ 设置编辑框较小
            layout = QHBoxLayout()
            layout.addWidget(QLabel(label_text))
            layout.addWidget(lineedit)
            layout.addWidget(QLabel(suffix))
            layout.addStretch()
            container = QWidget()
            container.setLayout(layout)
            return container

        dmin_input = QLineEdit(dmin_val)
        hmin_input = QLineEdit(hmin_val)

        table.setCellWidget(0, 0, build_row("外头盖内径距浮头法兰和钩圈外径最小距离 Dmin 为", dmin_input, "mm。"))
        table.setCellWidget(1, 0, build_row("浮头法兰螺栓孔边缘至密封槽最小距离 Hmin 为", hmin_input, "mm。"))

        table._futou_inputs = (dmin_input, hmin_input)

        if not hasattr(table, "_save_connected_futou_juli"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(lambda: save_futou_zuixiao_juli(table, cursor.connection, user_id))
                table._save_connected_futou_juli = True

    except Exception as e:
        print(f"[错误] 加载浮头最小距离配置失败: {e}")
def save_futou_zuixiao_juli(table: QTableWidget, db_conn, user_id):
    try:
        dmin_input, hmin_input = table._futou_inputs
        dmin = dmin_input.text().strip()
        hmin = hmin_input.text().strip()

        # 构造 value 字符串
        value_str = (
            f"外头盖内径距浮头法兰和钩圈外径最小距离 Dmin 为 {dmin} mm；"
            f"浮头法兰螺栓孔边缘至密封槽最小距离 Hmin 为 {hmin} mm。"
        )

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 浮头最小距离预定义用户表 WHERE user_id = %s", (user_id,))
        cursor.execute(
            "INSERT INTO 浮头最小距离预定义用户表 (user_id, value) VALUES (%s, %s)",
            (user_id, value_str)
        )
        db_conn.commit()
        cursor.close()
        print("[保存成功] 浮头最小距离配置已保存")

    except Exception as e:
        print(f"[错误] 保存浮头最小距离配置失败: {e}")
