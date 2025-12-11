from PyQt5.QtWidgets import QWidget, QLabel, QLineEdit, QHBoxLayout, QTableWidget
from PyQt5.QtCore import Qt
import re

def stepd_config(table: QTableWidget, cursor, user_id):
    try:
        default_step = "50"

        # 尝试读取用户已保存值
        cursor.execute("SELECT value FROM 外头盖内径递增值预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        if result:
            text = result[0]
            try:
                match = re.search(r"StepD为(\d+\.?\d*)", text)
                if match:
                    default_step = match.group(1)
            except Exception as e:
                print("[警告] 解析旧值失败：", e)

        # 设置表格结构
        table.clear()
        table.setRowCount(1)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["外头盖内径递增值配置"])
        table.verticalHeader().setDefaultSectionSize(50)
        table.horizontalHeader().setStretchLastSection(True)

        # 构建一行自然语句 + 编辑框
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 0, 10, 0)

        layout.addWidget(QLabel("外头盖内径递增值 StepD 为"))
        step_input = QLineEdit(default_step)
        step_input.setMaximumWidth(80)
        layout.addWidget(step_input)
        layout.addWidget(QLabel("mm。"))
        layout.addStretch()

        table.setCellWidget(0, 0, row)
        table._stepd_input = step_input

        # 绑定保存按钮
        if not hasattr(table, "_save_connected_stepd"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_stepd_config(table, cursor.connection, user_id)
                )
                table._save_connected_stepd = True

    except Exception as e:
        print(f"[错误] 加载 StepD 配置失败: {e}")
def save_stepd_config(table: QTableWidget, db_conn, user_id):
    try:
        step_input = table._stepd_input
        val = step_input.text().strip()

        value = f"外头盖内径递增值 StepD 为 {val} mm。"

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 外头盖内径递增值预定义用户表 WHERE user_id = %s", (user_id,))
        cursor.execute(
            "INSERT INTO 外头盖内径递增值预定义用户表 (user_id, value) VALUES (%s, %s)",
            (user_id, value)
        )
        db_conn.commit()
        cursor.close()

        print("[保存成功] 外头盖内径递增值配置更新")

    except Exception as e:
        print(f"[错误] 保存 StepD 配置失败: {e}")
