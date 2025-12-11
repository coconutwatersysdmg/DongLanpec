from PyQt5.QtWidgets import QTableWidget, QLineEdit, QHBoxLayout, QLabel, QWidget


def diaoerzhixian_config(table: QTableWidget, cursor, user_id):
    try:
        defaults = {
            "guanxiang": "50",
            "pinggai": "100",
            "waitougai": "100",
            "futougai": "30"
        }

        # 查询旧值
        cursor.execute("SELECT value FROM 超出重量限制吊耳设置预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        if result:
            try:
                val = result[0]
                defaults["guanxiang"] = val.split("管箱")[1].split("kg")[0]
                defaults["pinggai"] = val.split("管箱平盖")[1].split("kg")[0]
                defaults["waitougai"] = val.split("外头盖")[1].split("kg")[0]
                defaults["futougai"] = val.split("浮头盖")[1].split("kg")[0]
            except Exception as e:
                print(f"[警告] 吊耳重量解析失败，使用默认值: {e}")

        table.clear()
        table.setRowCount(1)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["超出重量限制吊耳设置"])
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        edits = {
            "guanxiang": QLineEdit(defaults["guanxiang"]),
            "pinggai": QLineEdit(defaults["pinggai"]),
            "waitougai": QLineEdit(defaults["waitougai"]),
            "futougai": QLineEdit(defaults["futougai"])
        }

        layout = QHBoxLayout()
        layout.setContentsMargins(10, 0, 10, 0)
        layout.addWidget(QLabel("管箱"))
        layout.addWidget(edits["guanxiang"])
        layout.addWidget(QLabel("kg；管箱平盖"))
        layout.addWidget(edits["pinggai"])
        layout.addWidget(QLabel("kg；外头盖"))
        layout.addWidget(edits["waitougai"])
        layout.addWidget(QLabel("kg；浮头盖"))
        layout.addWidget(edits["futougai"])
        layout.addWidget(QLabel("kg；"))
        layout.addStretch()

        container = QWidget()
        container.setLayout(layout)
        table.setCellWidget(0, 0, container)

        table._diaoer_edits = edits

        if not hasattr(table, '_save_connected_diaoer'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_diaoerzhixian_config(table, cursor.connection, user_id)
                )
                table._save_connected_diaoer = True

    except Exception as e:
        print(f"[错误] 加载吊耳设置失败: {e}")
def save_diaoerzhixian_config(table: QTableWidget, db_conn, user_id):
    try:
        edits = table._diaoer_edits
        sentence = (
            f"管箱{edits['guanxiang'].text()}kg；"
            f"管箱平盖{edits['pinggai'].text()}kg；"
            f"外头盖{edits['waitougai'].text()}kg；"
            f"浮头盖{edits['futougai'].text()}kg；"
        )

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 超出重量限制吊耳设置预定义用户表 WHERE user_id = %s", (user_id,))
        cursor.execute(
            "INSERT INTO 超出重量限制吊耳设置预定义用户表 (user_id, value) VALUES (%s, %s)",
            (user_id, sentence)
        )
        db_conn.commit()
        cursor.close()
        print(f"[保存成功] 用户 {user_id} 的吊耳设置已更新")
    except Exception as e:
        print(f"[错误] 保存吊耳设置失败: {e}")
