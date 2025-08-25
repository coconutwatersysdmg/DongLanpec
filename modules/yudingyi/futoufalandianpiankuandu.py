import re

from PyQt5.QtWidgets import QTableWidgetItem, QTableWidget, QMessageBox
from PyQt5.QtCore import Qt

def toufalan_dianpian_kuandu_config(table: QTableWidget, cursor, user_id):
    try:
        # 1. 获取预定义表的列名和数据（用于统一结构）
        cursor.execute("SELECT * FROM 浮头法兰垫片宽度预定义表")
        default_rows = cursor.fetchall()
        col_names = [desc[0] for desc in cursor.description]  # 不包含 user_id

        # 2. 初始化表结构
        table.clear()
        table.setColumnCount(len(col_names))
        table.setHorizontalHeaderLabels(col_names)
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        # 3. 检查用户表是否存在数据
        cursor.execute(
            f"SELECT {', '.join(col_names)} FROM 浮头法兰垫片宽度预定义用户表 WHERE user_id = %s",
            (user_id,)
        )
        user_rows = cursor.fetchall()

        if user_rows:
            print("[信息] 加载用户自定义配置")
            rows_to_use = user_rows
        else:
            print("[信息] 加载默认配置")
            rows_to_use = default_rows

        # 4. 设置行数并填充数据
        table.setRowCount(len(rows_to_use))
        for r, row_data in enumerate(rows_to_use):
            for c, val in enumerate(row_data):
                item = QTableWidgetItem(str(val))
                if r >= 2 and c in [2, 3]:  # 仅允许第3行起，第3/4列可编辑
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                else:
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                table.setItem(r, c, item)

        # 5. 存储列名供保存函数使用
        table._tfl_dpkd_colnames = col_names

        # 6. 绑定保存按钮
        if not hasattr(table, "_save_connected_tfl_dpkd"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_toufalan_dianpian_kuandu(table, cursor.connection, user_id)
                )
                table._save_connected_tfl_dpkd = True

    except Exception as e:
        print(f"[错误] 加载头法兰垫片宽度配置失败: {e}")
def extract_float(text):
    match = re.search(r'[-+]?\d+(?:\.\d+)?', text)
    return float(match.group()) if match else None

def save_toufalan_dianpian_kuandu(table: QTableWidget, db_conn, user_id):
    try:
        col_names = table._tfl_dpkd_colnames  # 所有列名
        cursor = db_conn.cursor()

        # 清除旧记录
        cursor.execute("DELETE FROM 浮头法兰垫片宽度预定义用户表 WHERE user_id = %s", (user_id,))

        # 遍历表格所有行
        for row_idx in range(table.rowCount()):
            values = []
            col2_val = col3_val = None

            for col_idx in range(table.columnCount()):
                item = table.item(row_idx, col_idx)
                val = item.text().strip() if item else ""
                values.append(val)

                # 第三行开始，且是第3和第4列时，提取待校验值
                if row_idx >= 2:
                    if col_idx == 2:
                        col2_val = val
                    elif col_idx == 3:
                        col3_val = val

            # 校验
            if row_idx >= 2:
                try:
                    val2 = extract_float(col2_val)
                    val3 = extract_float(col3_val)
                    if val2 is None or val3 is None:
                        QMessageBox.warning(table, "保存失败",
                            f"第 {row_idx+1} 行第3或4列值不是有效数字（如: '{col2_val}' 或 '{col3_val}'）")
                        return
                    if val3 < val2:
                        QMessageBox.warning(table, "保存失败",
                            f"第 {row_idx+1} 行：最大值需 ≥ 最小值\n当前值：{col2_val} < {col3_val}")
                        return
                except Exception as e:
                    QMessageBox.warning(table, "保存失败", f"第 {row_idx+1} 行校验出错：{str(e)}")
                    return

            # 插入数据
            col_fields = ", ".join(["user_id"] + col_names)
            placeholders = ", ".join(["%s"] * (len(col_names) + 1))
            sql = f"INSERT INTO 浮头法兰垫片宽度预定义用户表 ({col_fields}) VALUES ({placeholders})"
            cursor.execute(sql, (user_id, *values))

        db_conn.commit()
        cursor.close()
        print("[保存成功] 浮头法兰垫片宽度配置已更新")
        QMessageBox.information(table, "保存成功", "已成功保存浮头法兰垫片宽度配置。")

    except Exception as e:
        print(f"[错误] 保存失败: {e}")
        QMessageBox.critical(table, "错误", f"保存失败：{str(e)}")