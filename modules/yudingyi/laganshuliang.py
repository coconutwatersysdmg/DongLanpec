from PyQt5.QtWidgets import QTableWidgetItem, QTableWidget, QMessageBox
from PyQt5.QtCore import Qt

def lagan_shuliang_config(table: QTableWidget, cursor, user_id):
    try:
        # 获取原始表数据
        cursor.execute("SELECT * FROM 拉杆数量预定义表")
        original_rows = cursor.fetchall()
        col_names = [desc[0] for desc in cursor.description]

        # 检查是否有用户保存数据
        cursor.execute("SELECT * FROM 拉杆数量预定义用户表 WHERE user_id = %s", (user_id,))
        user_rows = cursor.fetchall()
        rows = [row[1:] for row in user_rows] if user_rows else original_rows

        # 保存原始数据用于校验
        table._lagan_original = original_rows

        # 构建表格
        table.clear()
        table.setColumnCount(len(col_names))
        table.setRowCount(len(rows))
        table.setHorizontalHeaderLabels(col_names)
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        for row_idx, row_data in enumerate(rows):
            for col_idx, val in enumerate(row_data):
                item = QTableWidgetItem(str(val))

                if (col_idx in [2, 3, 4] and row_idx >= 1) or col_idx == 5:
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                else:
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

                table.setItem(row_idx, col_idx, item)

        table._lagan_colnames = col_names

        if not hasattr(table, "_save_connected_lagan"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_lagan_shuliang_config(table, cursor.connection, user_id)
                )
                table._save_connected_lagan = True

    except Exception as e:
        print(f"[错误] 加载拉杆数量配置失败: {e}")


def save_lagan_shuliang_config(table: QTableWidget, db_conn, user_id):
    try:
        cursor = db_conn.cursor()
        col_names = table._lagan_colnames
        original = table._lagan_original

        # 校验数值不得小于原始值
        for row_idx in range(table.rowCount()):
            for col_idx in [2, 3, 4]:
                if row_idx >= 1:
                    item = table.item(row_idx, col_idx)
                    if not item:
                        continue
                    try:
                        new_val = float(item.text())
                        old_val = float(original[row_idx][col_idx])
                        if new_val < old_val:
                            QMessageBox.warning(
                                table,
                                "数值错误",
                                f"第{row_idx+1}行第{col_idx+1}列的值不能小于原始值：{old_val}"
                            )
                            return
                    except Exception:
                        QMessageBox.warning(
                            table,
                            "格式错误",
                            f"第{row_idx+1}行第{col_idx+1}列的值必须为数字"
                        )
                        return

        # 删除旧记录
        cursor.execute("DELETE FROM 拉杆数量预定义用户表 WHERE user_id = %s", (user_id,))

        for row_idx in range(table.rowCount()):
            values = []
            for col_idx in range(table.columnCount()):
                item = table.item(row_idx, col_idx)
                values.append(item.text().strip() if item else "")

            col_fields = ", ".join(["user_id"] + col_names)
            placeholders = ", ".join(["%s"] * (len(col_names) + 1))
            sql = f"INSERT INTO 拉杆数量预定义用户表 ({col_fields}) VALUES ({placeholders})"
            cursor.execute(sql, (user_id, *values))

        db_conn.commit()
        cursor.close()
        print("[保存成功] 拉杆数量预定义用户表已更新")

    except Exception as e:
        print(f"[错误] 保存拉杆数量配置失败: {e}")
