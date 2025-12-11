from PyQt5.QtWidgets import QTableWidget, QLabel, QMessageBox
from PyQt5.QtCore import Qt

def cailiaofupiancha(table: QTableWidget, cursor, user_id):
    try:
        cursor.execute("SELECT * FROM 材料负偏差预定义表")
        rows = cursor.fetchall()
        headers = [desc[0] for desc in cursor.description]

        if not rows or not headers:
            print("[错误] 表为空")
            return

        row_count = len(rows)
        col_count = len(headers)

        table.clear()
        table.setRowCount(row_count)
        table.setColumnCount(col_count)
        table.setHorizontalHeaderLabels(headers)

        # 填充表格内容
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                item = QLabel(str(val))
                item.setAlignment(Qt.AlignCenter)
                table.setCellWidget(r, c, item)

        # 可选合并指定列（比如前两列相同内容）
        merge_same_cells(table, row_count, [0, 1] if col_count >= 2 else [])

        # 绑定保存按钮
        if not hasattr(table, '_save_connected_fupiancha'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_fupiancha_to_user_table(table, cursor.connection, user_id))
                table._save_connected_fupiancha = True

    except Exception as e:
        print(f"[错误] 加载材料负偏差表失败: {e}")


def save_fupiancha_to_user_table(table: QTableWidget, db_conn, user_id):
    try:
        headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
        row_count = table.rowCount()

        if not headers or row_count == 0:
            QMessageBox.warning(table, "保存失败", "表格数据为空，无法保存")
            return

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 材料负偏差预定义用户表 WHERE user_id = %s", (user_id,))

        quoted_headers = [f"`{h}`" for h in headers]
        insert_sql = f"""
            INSERT INTO 材料负偏差预定义用户表
            ({', '.join(quoted_headers)}, user_id)
            VALUES ({', '.join(['%s'] * len(headers))}, %s)
        """

        for row in range(row_count):
            row_data = []
            for col in range(table.columnCount()):
                widget = table.cellWidget(row, col)
                value = widget.text() if isinstance(widget, QLabel) else ""
                row_data.append(value)
            cursor.execute(insert_sql, row_data + [user_id])

        db_conn.commit()
        cursor.close()

        print(f"[保存成功] 共保存 {row_count} 行至 材料负偏差预定义用户表（user_id={user_id}）")

    except Exception as e:
        print(f"[错误] 批量保存失败: {e}")


def merge_same_cells(table: QTableWidget, row_count: int, columns: list):
    """合并指定列中相邻相同的值"""
    for col in columns:
        last_text = None
        start_row = 0
        for row in range(row_count):
            widget = table.cellWidget(row, col)
            text = widget.text() if isinstance(widget, QLabel) else ""
            if text != last_text:
                if row > start_row + 1:
                    table.setSpan(start_row, col, row - start_row, 1)
                start_row = row
                last_text = text
        if row_count > start_row + 1:
            table.setSpan(start_row, col, row_count - start_row, 1)
