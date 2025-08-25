from PyQt5.QtWidgets import QTableWidget, QLabel, QMessageBox
from PyQt5.QtCore import Qt

def HHAfengtouchengxinghoudujianbaolv(table: QTableWidget, cursor, user_id, config_type):
    try:
        # 获取所有字段顺序
        cursor.execute("SELECT * FROM hha封头成形厚度减薄率表")
        rows = cursor.fetchall()
        headers = [desc[0] for desc in cursor.description]  # 保持原顺序

        if not rows or not headers:
            print("[错误] 表为空")
            return

        row_count = len(rows)
        col_count = len(headers)

        table.clear()
        table.setRowCount(row_count)
        table.setColumnCount(col_count)
        table.setHorizontalHeaderLabels(headers)

        # 渲染所有内容
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                item = QLabel(str(val))
                item.setAlignment(Qt.AlignCenter)
                table.setCellWidget(r, c, item)

        # 合并前两列中相邻相同的值
        merge_same_cells(table, row_count, [0, 1])

        # 记录“厚度减薄率”所在列
        if "厚度减薄率" not in headers:
            print("[错误] 未找到“厚度减薄率”列")
            return

        target_col = headers.index("厚度减薄率")
        table._target_col = target_col
        table._selected_row = None

        def cell_clicked(row, col):
            if col == target_col:
                table._selected_row = row

        table.cellClicked.connect(cell_clicked)

        # 绑定保存按钮
        if not hasattr(table, '_save_connected_hha'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_hha_houdu_value(table, cursor.connection, user_id, config_type))
                table._save_connected_hha = True

    except Exception as e:
        print(f"[错误] 加载厚度减薄率表失败: {e}")

def save_hha_houdu_value(table: QTableWidget, db_conn, user_id, config_type):
    try:
        # 获取表头（字段名）
        headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
        row_count = table.rowCount()

        if not headers or row_count == 0:
            QMessageBox.warning(table, "保存失败", "表格数据为空，无法保存")
            return

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM hha封头成形厚度减薄率预定义用户表 WHERE user_id=%s", (user_id,))

        # 构造 INSERT SQL
        quoted_headers = [f"`{h}`" for h in headers]
        insert_sql = f"""
            INSERT INTO hha封头成形厚度减薄率预定义用户表
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

        print(f"[保存成功] 共保存 {row_count} 行至 hha 预定义用户表（user_id={user_id}）")

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
        # 处理最后一组
        if row_count > start_row + 1:
            table.setSpan(start_row, col, row_count - start_row, 1)
