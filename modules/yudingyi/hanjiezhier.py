from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QCheckBox, QTableWidget, QTableWidgetItem,
    QHBoxLayout, QLabel, QLineEdit
)

def create_welded_support_lug_config(table: QTableWidget, cursor, user_id):
    try:
        table.clear()
        table.setColumnCount(1)
        table.setRowCount(0)
        table.setHorizontalHeaderLabels(['焊接支耳配置'])
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)

        row = 0

        cb1 = QCheckBox("焊接支耳与单孔支耳的长度、厚度一致。")
        table.insertRow(row)
        table.setCellWidget(row, 0, cb1)
        table.setRowHeight(row, 50)
        row += 1

        cb2 = QCheckBox("焊接支耳宽度W与保温厚度T默认关系（选中将显示可编辑表格）")
        table.insertRow(row)
        table.setCellWidget(row, 0, cb2)
        table.setRowHeight(row, 50)
        row += 1

        table_width = QTableWidget()
        table_width.setFixedHeight(150)
        table.insertRow(row)
        table.setCellWidget(row, 0, table_width)
        table.setRowHeight(row, 160)
        row += 1

        def load_width_table():
            cursor.execute("SELECT * FROM 焊接支耳长度与设计温度关系预定义表")
            rows = cursor.fetchall()
            headers = [desc[0] for desc in cursor.description]
            table_width.setColumnCount(len(headers))
            table_width.setRowCount(len(rows))
            table_width.setHorizontalHeaderLabels(headers)
            for i, row_data in enumerate(rows):
                for j, val in enumerate(row_data):
                    item = QTableWidgetItem(str(val))
                    if i == 1 and j >= 1:
                        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                    else:
                        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                    table_width.setItem(i, j, item)

        cb2.stateChanged.connect(lambda: load_width_table() if cb2.isChecked() else table_width.clear())

        table._welded_cb1 = cb1
        table._welded_cb2 = cb2
        table._welded_table_width = table_width
        if not hasattr(table, "_save_connected_zhichengban"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(lambda: save_welded_support_lug_config(table, cursor.connection, user_id))
                table._save_connected_zhichengban = True
    except Exception as e:
        print(f"[错误] 初始化焊接支耳配置失败: {e}")

def save_welded_support_lug_config(table: QTableWidget, db_conn, user_id):
    try:
        print("[调试] 焊接支耳保存逻辑已调用")
        cursor = db_conn.cursor()

        if table._welded_cb2.isChecked():
            cursor.execute("SELECT * FROM 焊接支耳长度与设计温度关系预定义用户表 LIMIT 1")
            headers = [desc[0] for desc in cursor.description]
            cols = [col for col in headers if col.lower() not in ("id", "user_id")]

            cursor.execute("DELETE FROM 焊接支耳长度与设计温度关系预定义用户表 WHERE user_id = %s", (user_id,))
            for row in range(table._welded_table_width.rowCount()):
                values = [table._welded_table_width.item(row, i + 1).text().strip()
                          if table._welded_table_width.item(row, i + 1) else ""
                          for i in range(len(cols))]
                placeholders = ", ".join(["%s"] * (len(values) + 1))
                cursor.execute(f"INSERT INTO 焊接支耳长度与设计温度关系预定义用户表 (user_id, {', '.join(cols)}) VALUES ({placeholders})", (user_id, *values))

        cursor.execute("DELETE FROM 焊接支耳预定义用户表 WHERE user_id = %s", (user_id,))

        if table._welded_cb1.isChecked():
            value = "焊接支耳与单孔支耳的长度、厚度一致。"
            cursor.execute("INSERT INTO 焊接支耳预定义用户表 (user_id, value) VALUES (%s, %s)", (user_id, value))

        db_conn.commit()
        print("[保存成功] 焊接支耳配置已更新")

    except Exception as e:
        print(f"[错误] 保存焊接支耳配置失败: {e}")
