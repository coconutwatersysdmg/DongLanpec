from PyQt5.QtWidgets import QCheckBox, QWidget, QHBoxLayout, QTableWidget

def huanreqiang_area_config(table: QTableWidget, cursor, user_id):
    try:
        checked = False

        # 查询历史配置
        cursor.execute("SELECT value FROM 换热面积预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        if result and "U形管计算换热面积核算时" in result[0]:
            checked = True

        table.clear()
        table.setRowCount(1)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["换热面积规则"])
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        cb = QCheckBox("U形管计算换热面积核算时，不包含U弯部分换热管长度。")
        cb.setChecked(checked)

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.addWidget(cb)
        table.setCellWidget(0, 0, row)

        table._huanreqiang_area_data = {
            "cb": cb
        }

        # 绑定保存按钮
        if not hasattr(table, "_save_connected_huanreqiang_area"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_huanreqiang_area_config(table, cursor.connection, user_id)
                )
                table._save_connected_huanreqiang_area = True

    except Exception as e:
        print(f"[错误] 加载换热面积配置失败: {e}")
def save_huanreqiang_area_config(table: QTableWidget, db_conn, user_id):
    try:
        cb = table._huanreqiang_area_data["cb"]
        value = ""
        if cb.isChecked():
            value = "U形管计算换热面积核算时，不包含U弯部分换热管长度。"

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 换热面积预定义用户表 WHERE user_id = %s", (user_id,))
        if value:
            cursor.execute("INSERT INTO 换热面积预定义用户表 (user_id, value) VALUES (%s, %s)", (user_id, value))
        db_conn.commit()
        cursor.close()

        print("[保存成功] 换热面积规则已更新")

    except Exception as e:
        print(f"[错误] 保存换热面积配置失败: {e}")
