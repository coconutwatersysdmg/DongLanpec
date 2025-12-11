from PyQt5.QtWidgets import QWidget, QTableWidgetItem, QCheckBox, QHBoxLayout, QLineEdit, QTableWidget
from PyQt5.QtCore import Qt

def kaikongbq_fangfa_config(table: QTableWidget, cursor, user_id):
    try:
        # 读取所有预定义方法
        cursor.execute("SELECT 开孔补强的计算方法, 优先级 FROM 开孔补强的设计方法选用预定义表")
        rows = cursor.fetchall()

        # 查询用户已保存项：从 id-value-user_id 结构中读取
        cursor.execute("SELECT id, value FROM 开孔补强的设计方法选用预定义用户表 WHERE user_id = %s", (user_id,))
        user_rows = cursor.fetchall()
        user_selected = {row[0]: row[1] for row in user_rows}

        table.clear()
        table.setRowCount(len(rows))
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["选择", "开孔补强的计算方法", "优先级"])
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        table._kaikongbq_rows = []

        for row_idx, (method, default_priority) in enumerate(rows):
            checkbox = QCheckBox()
            lineedit = QLineEdit(user_selected.get(method, str(default_priority)))
            if method in user_selected:
                checkbox.setChecked(True)

            # 插入控件
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(checkbox)
            layout.setAlignment(Qt.AlignCenter)
            widget.setLayout(layout)

            table.setCellWidget(row_idx, 0, widget)
            table.setItem(row_idx, 1, QTableWidgetItem(method))
            table.setCellWidget(row_idx, 2, lineedit)

            table._kaikongbq_rows.append((checkbox, method, lineedit))

        # 保存按钮绑定
        if not hasattr(table, '_save_connected_kaikongbq'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_kaikongbq_fangfa(table, cursor.connection, user_id)
                )
                table._save_connected_kaikongbq = True

    except Exception as e:
        print(f"[错误] 加载开孔补强设计方法失败: {e}")
def save_kaikongbq_fangfa(table: QTableWidget, db_conn, user_id):
    try:
        cursor = db_conn.cursor()
        # 清除旧数据
        cursor.execute("DELETE FROM 开孔补强的设计方法选用预定义用户表 WHERE user_id = %s", (user_id,))

        for checkbox, method, lineedit in table._kaikongbq_rows:
            if checkbox.isChecked():
                priority = lineedit.text().strip()
                value = f"{method}:{priority}"
                cursor.execute(
                    "INSERT INTO 开孔补强的设计方法选用预定义用户表 (value, user_id) VALUES (%s, %s)",
                    (value, user_id)
                )

        db_conn.commit()
        cursor.close()
        print(f"[保存成功] 用户 {user_id} 的开孔补强设计方法已更新")
    except Exception as e:
        print(f"[错误] 保存开孔补强设计方法失败: {e}")
