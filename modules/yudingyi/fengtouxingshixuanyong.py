from PyQt5.QtCore import Qt
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import QTableWidget, QMessageBox, QTableWidgetItem


def fengtouxingshixuanyong(table: QTableWidget, cursor, user_id, config_type=None):
    try:
        table.clear()
        cursor.execute("SELECT * FROM 封头形式选用表")
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]

        table.setRowCount(len(rows))
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setEditTriggers(QTableWidget.NoEditTriggers)

        # 填入数据
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(i, j, item)

        # 高亮选择单元格（非首行首列）
        def on_cell_clicked(row, col):
            if row == 0 or col == 0:
                QMessageBox.warning(table, "无效选择", "请选择非第一行、非第一列的单元格")
                table._selected_cell = None
                return

            table._selected_cell = (row, col)

            # 清除旧背景色
            for r in range(table.rowCount()):
                for c in range(table.columnCount()):
                    item = table.item(r, c)
                    if item:
                        item.setBackground(QBrush(QColor("white")))

            # 设置新高亮色
            item = table.item(row, col)
            if item:
                item.setBackground(QBrush(QColor(204, 232, 255)))  # 淡蓝色

        table.cellClicked.connect(on_cell_clicked)
        table._selected_cell = None

        if not hasattr(table, '_save_connected_fengtou'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_fengtou_selection(table, cursor.connection, user_id)
                )
                table._save_connected_fengtou = True

    except Exception as e:
        print(f"[错误] 加载封头选用表失败: {e}")


def save_fengtou_selection(table: QTableWidget, db_conn, user_id):
    try:
        selected = getattr(table, '_selected_cell', None)
        if not selected:
            QMessageBox.warning(table, "未选择", "请选择非第一行、非第一列的单元格再点击保存配置")
            return

        row, col = selected
        value = table.item(row, col).text()

        cursor = db_conn.cursor()
        cursor.execute("""
            DELETE FROM 封头形式选用预定义用户表 WHERE user_id = %s
        """, (user_id,))
        cursor.execute("""
            INSERT INTO 封头形式选用预定义用户表 (value, user_id) VALUES (%s, %s)
        """, (value, user_id))
        db_conn.commit()
        cursor.close()

        print(f"[保存成功] 封头形式选用: {value}")
    except Exception as e:
        print(f"[错误] 保存封头选项失败: {e}")
