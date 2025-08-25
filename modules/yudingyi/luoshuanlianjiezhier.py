from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QCheckBox, QTableWidget, QTableWidgetItem,
    QHBoxLayout, QLabel, QLineEdit
)
import json

def create_bolted_support_lug_config(table: QTableWidget, cursor, user_id):
    try:
        table.clear()
        table.setColumnCount(1)
        table.setRowCount(0)
        table.setHorizontalHeaderLabels(['螺栓连接支耳配置'])
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)

        row = 0
        checkbox_list = []

        def insert_checkbox_row(text, editable_line_text=None, suffix=None):
            nonlocal row
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(10, 0, 10, 0)
            cb = QCheckBox()
            layout.addWidget(cb)
            layout.addWidget(QLabel(text))
            line = None
            if editable_line_text:
                line = QLineEdit(editable_line_text)
                line.setMaximumWidth(80)
                layout.addWidget(line)
            if suffix:
                layout.addWidget(QLabel(suffix))
            layout.addStretch()
            table.insertRow(row)
            table.setCellWidget(row, 0, widget)
            table.setRowHeight(row, 40)  # ✅ 设置统一行高
            row += 1
            return cb, line, text, suffix

        cb1 = QCheckBox("支耳为单孔时，支耳长度H与设计温度默认关系（选中将显示可编辑表格）")
        table.insertRow(row)
        table.setCellWidget(row, 0, cb1)
        table.setRowHeight(row, 50)  # ✅ 设置首行较高，避免叠加
        row += 1

        table_length = QTableWidget()
        table_length.setFixedHeight(150)  # ✅ 设置固定高度避免撑满
        table.insertRow(row)
        table.setCellWidget(row, 0, table_length)
        table.setRowHeight(row, 150)  # ✅ 设置行高
        row += 1

        def load_length_table():
            cursor.execute("SELECT * FROM 支耳长度与设计温度关系预定义表")
            rows = cursor.fetchall()
            headers = [desc[0] for desc in cursor.description]
            table_length.setColumnCount(len(headers))
            table_length.setRowCount(len(rows))
            table_length.setHorizontalHeaderLabels(headers)
            for i, row_data in enumerate(rows):
                for j, val in enumerate(row_data):
                    item = QTableWidgetItem(str(val))
                    if i == 1 and j >= 1:
                        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                    else:
                        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                    table_length.setItem(i, j, item)

        cb1.stateChanged.connect(lambda: load_length_table() if cb1.isChecked() else table_length.clear())

        cb2, line2, _, _ = insert_checkbox_row("支耳为双孔时，长度为单孔支耳的", "2", "倍")
        checkbox_list.append((cb2, "双孔支耳长度倍数=", line2, "倍"))

        cb3 = QCheckBox("支耳宽度W与保温厚度T默认关系（选中将显示可编辑表格）")
        table.insertRow(row)
        table.setCellWidget(row, 0, cb3)
        table.setRowHeight(row, 50)
        row += 1

        table_width = QTableWidget()
        table_width.setFixedHeight(150)  # ✅ 设置固定高度
        table.insertRow(row)
        table.setCellWidget(row, 0, table_width)
        table.setRowHeight(row, 150)
        row += 1

        def load_width_table():
            cursor.execute("SELECT * FROM 支耳宽度与厚度关系预定义表")
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

        cb3.stateChanged.connect(lambda: load_width_table() if cb3.isChecked() else table_width.clear())

        cb4, line4, _, _ = insert_checkbox_row("支耳厚度默认为", "6", "mm。")
        checkbox_list.append((cb4, "支耳厚度默认为", line4, "mm。"))

        cb5, line5, _, _ = insert_checkbox_row("支耳螺栓孔与支耳边缘的距离最小值为：", "螺栓直径", "mm。")
        checkbox_list.append((cb5, "支耳螺栓孔与支耳边缘的距离最小值为：", line5, "mm。"))

        cb6, line6, _, _ = insert_checkbox_row("双孔支耳螺栓孔间距为：", "3*螺栓孔直径+螺栓直径", "mm。")
        checkbox_list.append((cb6, "双孔支耳螺栓孔间距为：", line6, "mm。"))

        table._zhier_checkbox_list = checkbox_list
        table._zhier_cb1 = cb1
        table._zhier_cb3 = cb3
        table._zhier_table_length = table_length
        table._zhier_table_width = table_width

        if not hasattr(table, "_save_connected_zhichengban"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(lambda: save_bolted_support_lug_config(table, cursor.connection, user_id))
                table._save_connected_zhichengban = True
    except Exception as e:
        print(f"[错误] 初始化螺栓连接支耳配置失败: {e}")

def save_bolted_support_lug_config(table: QTableWidget, db_conn, user_id):
    try:
        print("[调试] 螺栓连接支耳保存逻辑已调用")
        cursor = db_conn.cursor()

        if table._zhier_cb1.isChecked():
            cursor.execute("SELECT * FROM 支耳长度与设计温度关系预定义用户表 LIMIT 1")
            headers = [desc[0] for desc in cursor.description]
            cols = [col for col in headers if col.lower() not in ("id", "user_id")]

            cursor.execute("DELETE FROM 支耳长度与设计温度关系预定义用户表 WHERE user_id = %s", (user_id,))
            for row in range(table._zhier_table_length.rowCount()):
                values = [table._zhier_table_length.item(row, i + 1).text().strip()
                          if table._zhier_table_length.item(row, i + 1) else ""
                          for i in range(len(cols))]
                placeholders = ", ".join(["%s"] * (len(values) + 1))
                cursor.execute(f"INSERT INTO 支耳长度与设计温度关系预定义用户表 (user_id, {', '.join(cols)}) VALUES ({placeholders})", (user_id, *values))

        if table._zhier_cb3.isChecked():
            cursor.execute("SELECT * FROM 支耳宽度与厚度关系预定义用户表 LIMIT 1")
            headers = [desc[0] for desc in cursor.description]
            cols = [col for col in headers if col.lower() not in ("id", "user_id")]

            cursor.execute("DELETE FROM 支耳宽度与厚度关系预定义用户表 WHERE user_id = %s", (user_id,))
            for row in range(table._zhier_table_width.rowCount()):
                values = [table._zhier_table_width.item(row, i + 1).text().strip()
                          if table._zhier_table_width.item(row, i + 1) else ""
                          for i in range(len(cols))]
                placeholders = ", ".join(["%s"] * (len(values) + 1))
                cursor.execute(f"INSERT INTO 支耳宽度与厚度关系预定义用户表 (user_id, {', '.join(cols)}) VALUES ({placeholders})", (user_id, *values))

        cursor.execute("DELETE FROM 螺栓连接支耳预定义用户表 WHERE user_id = %s", (user_id,))

        cb2, prefix, line2, suffix = table._zhier_checkbox_list[0]
        if cb2.isChecked() and line2:
            value = f"{prefix}{line2.text()}{suffix}"
            cursor.execute("INSERT INTO 螺栓连接支耳预定义用户表 (user_id, value) VALUES (%s, %s)", (user_id, value))

        for cb, prefix, line, suffix in table._zhier_checkbox_list[1:]:
            if cb.isChecked() and line:
                sentence = f"{prefix}{line.text()}{suffix}"
                cursor.execute("INSERT INTO 螺栓连接支耳预定义用户表 (user_id, value) VALUES (%s, %s)", (user_id, sentence))

        db_conn.commit()
        print("[保存成功] 螺栓连接支耳配置已更新")

    except Exception as e:
        print(f"[错误] 保存螺栓连接支耳配置失败: {e}")