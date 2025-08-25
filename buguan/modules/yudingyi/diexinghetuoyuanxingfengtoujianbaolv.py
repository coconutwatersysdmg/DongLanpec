from PyQt5.QtWidgets import QTableWidget, QLabel, QMessageBox
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt

def diexinghetuoyuanxingfengtoujianbaolv(table: QTableWidget, cursor, user_id, config_type):
    try:
        cursor.execute("SELECT * FROM 碟形和椭圆形封头成形方法和厚度减薄率表")
        rows = cursor.fetchall()
        headers = [desc[0] for desc in cursor.description]
        if not rows:
            print("[错误] 无数据")
            return

        row_count = len(rows)
        col_count = len(headers)

        table.clear()
        table.setRowCount(row_count)
        table.setColumnCount(col_count)
        table.setHorizontalHeaderLabels(headers)

        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                label = QLabel(str(val))
                label.setAlignment(Qt.AlignCenter)
                table.setCellWidget(r, c, label)

        # 找“厚度减薄率%”列
        target_col = None
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                if str(val).strip() == "厚度减薄率%":
                    target_col = c
                    break
            if target_col is not None:
                break

        if target_col is None:
            print("[错误] 未找到“厚度减薄率%”")
            return

        table._target_col = target_col
        table._selected_row = None
        table._headers = headers
        table._rows = rows  # 存下原始数据

        # 合并前两列中相邻值
        for col in range(2):
            last_val = None
            start_row = 0
            for row in range(row_count):
                text = table.cellWidget(row, col).text()
                if text != last_val:
                    if row > start_row + 1:
                        table.setSpan(start_row, col, row - start_row, 1)
                    last_val = text
                    start_row = row
            if row_count > start_row + 1:
                table.setSpan(start_row, col, row_count - start_row, 1)

        def cell_clicked(row, col):
            if col == table._target_col and rows[row][col] != "厚度减薄率%":
                table._selected_row = row
            else:
                table._selected_row = None

        table.cellClicked.connect(cell_clicked)

        if not hasattr(table, '_save_connected_houdu'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_houdujianbaolv_value(table, cursor.connection, user_id))
                table._save_connected_houdu = True

    except Exception as e:
        print(f"[错误] 加载厚度减薄率表失败: {e}")

def save_houdujianbaolv_value(table: QTableWidget, db_conn, user_id):
    try:
        headers = getattr(table, '_headers', [])
        rows = getattr(table, '_rows', [])
        if not headers or not rows:
            QMessageBox.warning(table, "保存失败", "表格数据为空")
            return

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 碟形和椭圆形封头成形方法和厚度减薄率预定义用户表 WHERE user_id=%s", (user_id,))

        # ✅ 用反引号包裹字段名防止非法字符报错
        quoted_headers = [f"`{col}`" for col in headers]
        insert_sql = f"""
            INSERT INTO 碟形和椭圆形封头成形方法和厚度减薄率预定义用户表
            ({', '.join(quoted_headers)}, user_id)
            VALUES ({', '.join(['%s'] * len(headers))}, %s)
        """

        for row in rows:
            cursor.execute(insert_sql, list(row) + [user_id])

        db_conn.commit()
        cursor.close()

        print(f"[保存成功] 共保存 {len(rows)} 行至预定义表（user_id={user_id}）")
    except Exception as e:
        print(f"[错误] 批量保存失败: {e}")
