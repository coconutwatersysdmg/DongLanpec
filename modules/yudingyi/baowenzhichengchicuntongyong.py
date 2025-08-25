import re

from PyQt5.QtWidgets import QTableWidget, QHBoxLayout, QLabel, QWidget, QLineEdit, QCheckBox


def baowen_zhichi_chicun_config(table: QTableWidget, cursor, user_id):
    try:
        default1 = "螺栓直径规格"
        default2 = "2"
        default3 = "40"
        checked1 = True
        checked2 = True

        cursor.execute("SELECT value FROM 保温支撑尺寸_通用预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        if result:
            try:
                text = result[0]
                m1 = re.search(r"螺栓孔默认直径为：(.+?)\+(.+?) mm", text)
                if m1:
                    default1 = m1.group(1).strip()
                    default2 = m1.group(2).strip()
                m2 = re.search(r"厚度小于(\d+\.?\d*)mm", text)
                if m2:
                    default3 = m2.group(1).strip()
                checked1 = "螺栓孔默认直径为" in text
                checked2 = "默认不推荐用螺栓连接" in text
            except Exception as e:
                print("[警告] 解析旧值失败:", e)

        table.clear()
        table.setRowCount(2)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["保温支撑尺寸配置"])
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        # 第一句
        cb1 = QCheckBox("螺栓孔默认直径为：")
        cb1.setChecked(checked1)
        edit1 = QLineEdit(default1)
        edit1.setMaximumWidth(100)
        row1 = QWidget()
        h1 = QHBoxLayout(row1)
        h1.setContentsMargins(10, 0, 10, 0)
        h1.addWidget(cb1)
        h1.addWidget(edit1)
        h1.addWidget(QLabel(" mm。"))
        h1.addStretch()
        table.setCellWidget(0, 0, row1)

        # 第二句
        cb2 = QCheckBox("当保温（保冷）厚度小于")
        cb2.setChecked(checked2)
        edit3 = QLineEdit(default3)
        edit3.setMaximumWidth(50)
        row2 = QWidget()
        h2 = QHBoxLayout(row2)
        h2.setContentsMargins(10, 0, 10, 0)
        h2.addWidget(cb2)
        h2.addWidget(edit3)
        h2.addWidget(QLabel("mm 时，默认不推荐用螺栓连接"))
        h2.addStretch()
        table.setCellWidget(1, 0, row2)

        table._bw_zhichi_chicun_inputs = {
            "cb1": cb1, "edit1": edit1,
            "cb2": cb2, "edit3": edit3
        }

        if not hasattr(table, "_save_connected_bw_zhichi_chicun"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_baowen_zhichi_chicun(table, cursor.connection, user_id)
                )
                table._save_connected_bw_zhichi_chicun = True

    except Exception as e:
        print(f"[错误] 加载保温支撑尺寸配置失败: {e}")

def save_baowen_zhichi_chicun(table: QTableWidget, db_conn, user_id):
    try:
        data = table._bw_zhichi_chicun_inputs
        cb1, edit1= data["cb1"], data["edit1"]
        cb2, edit3 = data["cb2"], data["edit3"]

        lines = []
        if cb1.isChecked():
            lines.append(f"螺栓孔默认直径为：{edit1.text().strip()} mm。")
        if cb2.isChecked():
            lines.append(f"当保温（保冷）厚度小于{edit3.text().strip()}mm时，默认不推荐用螺栓连接")

        value = "\n".join(lines)

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 保温支撑尺寸_通用预定义用户表 WHERE user_id = %s", (user_id,))
        cursor.execute(
            "INSERT INTO 保温支撑尺寸_通用预定义用户表 (user_id, value) VALUES (%s, %s)",
            (user_id, value)
        )
        db_conn.commit()
        cursor.close()
        print("[保存成功] 保温支撑尺寸配置已更新")

    except Exception as e:
        print(f"[错误] 保存保温支撑尺寸配置失败: {e}")
