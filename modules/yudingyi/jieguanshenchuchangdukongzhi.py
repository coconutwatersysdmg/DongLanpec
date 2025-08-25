from PyQt5.QtWidgets import QTableWidget, QLabel, QVBoxLayout, QWidget, QHBoxLayout, QLineEdit, QMessageBox
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt
import os
def resource_path(relative_path):
    """获取打包后的资源路径"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)  # _MEIPASS 是 PyInstaller 解压临时目录
    return os.path.join(os.path.abspath("."), relative_path)
def jieguanshenchuchangdu(table: QTableWidget, cursor, user_id, config_type=None):
    try:
        # 查询所有数据
        cursor.execute("SELECT * FROM 接管伸出长度控制表")
        rows = cursor.fetchall()
        headers = [desc[0] for desc in cursor.description]

        row_count = len(rows)
        col_count = len(headers)

        table.clear()
        table.setRowCount(row_count)
        table.setColumnCount(col_count + 1)  # 增加一列用于图像展示

        # 设置表头
        table.setHorizontalHeaderLabels([''] + headers)

        # 加载图像
        image_label = QLabel()
        pixmap = QPixmap(resource_path(os.path.join("static", "接管伸出长度控制1.png")))
        scaled_pixmap = pixmap.scaled(pixmap.width() * 0.6, pixmap.height() * 0.6, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        image_label.setPixmap(scaled_pixmap)
        image_label.setAlignment(Qt.AlignCenter)
        table.setCellWidget(0, 0, image_label)
        table.setSpan(0, 0, row_count, 1)
        table.setColumnWidth(0, 120)

        # 填充数据
        for row_idx, row_data in enumerate(rows):
            for col_idx, value in enumerate(row_data):
                if headers[col_idx] == "最小伸出长度l":
                    # 可编辑
                    editor = QLineEdit(str(value))
                    editor.setAlignment(Qt.AlignCenter)
                    table.setCellWidget(row_idx, col_idx + 1, editor)
                else:
                    label = QLabel(str(value))
                    label.setAlignment(Qt.AlignCenter)
                    table.setCellWidget(row_idx, col_idx + 1, label)

        # 合并保温层厚度列（图片列后第一列）
        last_value = None
        start_row = 0
        for row in range(row_count):
            current_widget = table.cellWidget(row, 1)
            current_value = current_widget.text() if isinstance(current_widget, QLabel) else ""
            if current_value != last_value:
                if row > start_row + 1:
                    table.setSpan(start_row, 1, row - start_row, 1)
                start_row = row
                last_value = current_value
        if row_count > start_row + 1:
            table.setSpan(start_row, 1, row_count - start_row, 1)

        # 绑定保存逻辑
        if not hasattr(table, '_save_connected_shenchu'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_shenchu_table(table, cursor.connection, user_id)
                )
                table._save_connected_shenchu = True
            else:
                print("[错误] 找不到 save_button")

    except Exception as e:
        print(f"[错误] 加载接管伸出长度控制表失败: {e}")


def save_shenchu_table(table: QTableWidget, db_conn, user_id):
    try:
        headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
        保温层_idx = headers.index("保温层厚度")
        DN_idx = headers.index("接管公称直径DN")
        l_idx = headers.index("最小伸出长度l")

        data = []

        for row in range(table.rowCount()):
            保温层 = table.cellWidget(row, 保温层_idx)
            DN = table.cellWidget(row, DN_idx)
            l = table.cellWidget(row, l_idx)

            def get_text(widget):
                if isinstance(widget, QLabel):
                    return widget.text().strip()
                elif isinstance(widget, QLineEdit):
                    return widget.text().strip()
                return ""

            b = get_text(保温层)
            dn = get_text(DN)
            l_val = get_text(l)

            if b and dn and l_val:
                data.append((b, dn, l_val))

        # 写入数据库
        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 接管伸出长度控制1预定义用户表 WHERE user_id = %s", (user_id,))
        for b, dn, l_val in data:
            cursor.execute("""
                INSERT INTO 接管伸出长度控制预定义用户表 
                (保温层厚度, 接管公称直径DN, 最小伸出长度l, user_id)
                VALUES (%s, %s, %s, %s)
            """, (b, dn, l_val, user_id))
        db_conn.commit()
        cursor.close()

        QMessageBox.information(table, "保存成功", "接管伸出长度控制表已保存到预定义用户表。")
        print("[保存成功] 接管伸出长度控制预定义用户表写入完成")

    except Exception as e:
        QMessageBox.critical(table, "保存失败", f"保存失败：{e}")
        print(f"[错误] 保存接管伸出长度失败: {e}")
