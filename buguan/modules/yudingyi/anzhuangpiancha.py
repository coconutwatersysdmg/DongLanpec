from PyQt5.QtWidgets import QWidget, QLabel, QLineEdit, QHBoxLayout, QTableWidget
import re

def anzhuang_piancha_config(table: QTableWidget, cursor, user_id):
    try:
        min_val = "3"
        max_val = "3"

        cursor.execute("SELECT value FROM 安装偏差预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        if result:
            try:
                text = result[0]
                min_match = re.search(r"安装偏差为 -(\d+\.?\d*)", text)
                max_match = re.search(r"/\+(\d+\.?\d*)", text)
                if min_match: min_val = min_match.group(1)
                if max_match: max_val = max_match.group(1)
            except Exception as e:
                print(f"[警告] 解析旧值失败: {e}")

        table.clear()
        table.setRowCount(1)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["安装偏差"])
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.addWidget(QLabel("球冠封头与浮头法兰的安装偏差为 -"))

        edit_min = QLineEdit(min_val)
        edit_min.setMaximumWidth(60)
        layout.addWidget(edit_min)

        layout.addWidget(QLabel(" / +"))

        edit_max = QLineEdit(max_val)
        edit_max.setMaximumWidth(60)
        layout.addWidget(edit_max)

        layout.addWidget(QLabel(" mm。"))
        layout.addStretch()

        table.setCellWidget(0, 0, row)

        # 保存引用
        table._anzhuang_inputs = {
            "edit_min": edit_min,
            "edit_max": edit_max
        }

        if not hasattr(table, "_save_connected_anzhuang"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_anzhuang_piancha_config(table, cursor.connection, user_id)
                )
                table._save_connected_anzhuang = True

    except Exception as e:
        print(f"[错误] 加载安装偏差配置失败: {e}")
def save_anzhuang_piancha_config(table: QTableWidget, db_conn, user_id):
    try:
        data = table._anzhuang_inputs
        min_val = data["edit_min"].text().strip()
        max_val = data["edit_max"].text().strip()

        value = f"球冠封头与浮头法兰的安装偏差为 -{min_val} / +{max_val} mm。"

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 安装偏差预定义用户表 WHERE user_id = %s", (user_id,))
        cursor.execute(
            "INSERT INTO 安装偏差预定义用户表 (user_id, value) VALUES (%s, %s)",
            (user_id, value)
        )
        db_conn.commit()
        cursor.close()
        print("[保存成功] 安装偏差配置已更新")

    except Exception as e:
        print(f"[错误] 保存安装偏差配置失败: {e}")
