from PyQt5.QtWidgets import QWidget, QVBoxLayout, QCheckBox, QTableWidget
from PyQt5.QtCore import Qt

def handle_board_spec(table, cursor, user_id, config_type):
    try:
        table.clear()
        table.setRowCount(25)
        table.setColumnCount(8)
        table.setHorizontalHeaderLabels([f"列 {i + 1}" for i in range(8)])

        # 从数据库获取前200个板材配置
        cursor.execute("""
            SELECT 板材配置ID, 参数值, 是否启用 
            FROM 板材配置表 
        """)
        config_data = cursor.fetchall()  # List[Tuple[int, str, int]]

        # 查询用户之前的选择记录（参数值列表）
        cursor.execute("""
            SELECT value 
            FROM user_config 
            WHERE user_id=%s AND config_type=%s
        """, (user_id, config_type))
        selected_items = set([row[0] for row in cursor.fetchall()])

        for idx, (config_id, param_value, enabled) in enumerate(config_data):
            row = idx % 25
            col = idx // 25

            checkbox = QCheckBox(str(param_value))
            checkbox.setEnabled(enabled == '1')

            if param_value in selected_items:
                checkbox.setChecked(True)

            widget = QWidget()
            layout = QVBoxLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(checkbox, alignment=Qt.AlignCenter)
            table.setCellWidget(row, col, widget)

            table.setEditTriggers(QTableWidget.NoEditTriggers)  # 不可编辑
            table.setShowGrid(True)

        if not hasattr(table, '_save_connected'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_user_config(table, cursor.connection, user_id, config_type))
                table._save_connected = True
            else:
                print("[错误] 找不到 save_button")

    except Exception as e:
        print(f"[错误] 加载板材规格失败: {e}")


def save_user_config(table: QTableWidget, db_conn, user_id, config_type=None):
    try:
        selected_values = []

        for row in range(table.rowCount()):
            for col in range(table.columnCount()):
                widget = table.cellWidget(row, col)
                if widget:
                    checkbox = widget.findChild(QCheckBox)
                    if checkbox and checkbox.isChecked():
                        selected_values.append(checkbox.text())

        value_str = ','.join(selected_values)

        cursor = db_conn.cursor()
        cursor.execute("""
            DELETE FROM 常用板材规格配置预定义用户表 WHERE user_id = %s
        """, (user_id,))
        cursor.execute("""
            INSERT INTO 常用板材规格配置预定义用户表 (value, user_id)
            VALUES (%s, %s)
        """, (value_str, user_id))
        db_conn.commit()
        cursor.close()

        print(f"[保存成功] 常用板材规格: {value_str}")
    except Exception as e:
        print(f"[错误] 保存配置失败: {e}")
