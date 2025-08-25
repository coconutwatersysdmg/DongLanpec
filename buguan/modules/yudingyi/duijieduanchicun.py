from PyQt5.QtWidgets import QWidget, QVBoxLayout, QCheckBox, QTableWidget, QTableWidgetItem
from PyQt5.QtCore import Qt

def duijieduanchicun(table: QTableWidget, cursor, user_id, config_type=None):
    try:
        options = [
            "按设计规则“管材规格”项或管口表指定值；",
            "满足GB/T 17395《无缝钢管尺寸、外形、重量及允许偏差》列出的全部内容；",
            "板(卷)制接管厚度取圆筒或凸形封头壁厚较大值（作为开孔补强的初始值，根据需求增厚）；"
        ]

        # 清空旧内容
        table.clearContents()
        table.setRowCount(0)
        table.setColumnCount(0)

        table.setRowCount(len(options))
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["参考标准选项"])
        table.setEditTriggers(QTableWidget.NoEditTriggers)

        # ✅ 查询新表中的旧值
        cursor.execute("""
            SELECT value FROM 接管与管法兰或外部对接端尺寸预定义用户表
            WHERE user_id = %s
        """, (user_id,))
        result = cursor.fetchone()
        selected_values = result[0].split("|") if result else []

        # 插入复选框
        for i, option in enumerate(options):
            checkbox = QCheckBox(option)
            checkbox.setChecked(option in selected_values)
            widget = QWidget()
            layout = QVBoxLayout(widget)
            layout.setContentsMargins(5, 0, 0, 0)
            layout.addWidget(checkbox, alignment=Qt.AlignLeft)
            table.setCellWidget(i, 0, widget)
            table.setRowHeight(i, 40)

        # 保存按钮绑定
        if not hasattr(table, '_save_connected_cankaobiaozhun'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_cankaobiaozhun(table, cursor.connection, user_id)
                )
                table._save_connected_cankaobiaozhun = True
            else:
                print("[错误] 找不到 save_button")

    except Exception as e:
        print(f"[错误] 加载参考标准配置失败: {e}")


def save_cankaobiaozhun(table: QTableWidget, db_conn, user_id):
    try:
        selected_values = []
        for row in range(table.rowCount()):
            widget = table.cellWidget(row, 0)
            if widget:
                checkbox = widget.findChild(QCheckBox)
                if checkbox and checkbox.isChecked():
                    selected_values.append(checkbox.text())

        value_str = ";".join(selected_values)

        cursor = db_conn.cursor()
        cursor.execute("""
            DELETE FROM 接管与管法兰或外部对接端尺寸预定义用户表 
            WHERE user_id = %s
        """, (user_id,))
        cursor.execute("""
            INSERT INTO 接管与管法兰或外部对接端尺寸预定义用户表 (value, user_id) 
            VALUES (%s, %s)
        """, (value_str, user_id))
        db_conn.commit()
        cursor.close()

        print(f"[保存成功] 接管对接端尺寸: {value_str}")

    except Exception as e:
        print(f"[错误] 保存参考标准配置失败: {e}")
