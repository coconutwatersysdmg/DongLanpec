from PyQt5.QtWidgets import QWidget, QLabel, QLineEdit, QTableWidget, QHBoxLayout

def lagan_jiegou_config(table: QTableWidget, cursor, user_id):
    try:
        default_d = "19"  # 默认值

        # 查询旧记录
        cursor.execute("SELECT value FROM 拉杆结构预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        if result:
            import re
            m = re.search(r"外径≥(\d+\.?\d*)mm", result[0])
            if m:
                default_d = m.group(1)

        # 初始化表格
        table.clear()
        table.setRowCount(1)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["拉杆结构配置"])
        table.verticalHeader().setDefaultSectionSize(50)
        table.horizontalHeader().setStretchLastSection(True)

        # 编辑框行
        edit = QLineEdit(default_d)
        edit.setMaximumWidth(60)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.addWidget(QLabel("换热管外径≥"))
        layout.addWidget(edit)
        layout.addWidget(QLabel("mm 的管束，拉杆与管板连接使用螺纹结构，否则，使用焊接结构。"))
        layout.addStretch()
        table.setCellWidget(0, 0, row)

        # 保存输入引用
        table._lagan_inputs = {"edit": edit}

        # 绑定保存按钮
        if not hasattr(table, "_save_connected_lagan"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_lagan_jiegou_config(table, cursor.connection, user_id)
                )
                table._save_connected_lagan = True

    except Exception as e:
        print(f"[错误] 加载拉杆结构配置失败: {e}")
def save_lagan_jiegou_config(table: QTableWidget, db_conn, user_id):
    try:
        val = table._lagan_inputs["edit"].text().strip()
        sentence = f"换热管外径≥{val}mm 的管束，拉杆与管板连接使用螺纹结构，否则，使用焊接结构。"

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 拉杆结构预定义用户表 WHERE user_id = %s", (user_id,))
        cursor.execute(
            "INSERT INTO 拉杆结构预定义用户表 (user_id, value) VALUES (%s, %s)", (user_id, sentence)
        )
        db_conn.commit()
        cursor.close()
        print("[保存成功] 拉杆结构配置已更新")

    except Exception as e:
        print(f"[错误] 保存拉杆结构配置失败: {e}")
