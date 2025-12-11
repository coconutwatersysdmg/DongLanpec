import re

from PyQt5.QtWidgets import QWidget, QLabel, QLineEdit, QCheckBox, QHBoxLayout, QTableWidget
from PyQt5.QtCore import Qt

def center_distance_supplement_config(table: QTableWidget, cursor, user_id):
    try:
        default_value = "50"
        checked = False

        # 查询旧值
        cursor.execute("SELECT value FROM 换热管中心距补充预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        if result:
            text = result[0]
            if "外径为25mm的换热管" in text:
                checked = True
            m = re.search(r"距U形换热管弯管切点(\d+\.?\d*)mm", text)
            if m:
                default_value = m.group(1)

        table.clear()
        table.setRowCount(2)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["换热管中心距补充规则"])
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        # 第一行：可选项，数值固定
        cb1 = QCheckBox("外径为25mm的换热管采用转角正方形排列时，其分程隔板槽两侧相邻管中心距Sn取45.25mm。")
        cb1.setChecked(checked)
        row1 = QWidget()
        layout1 = QHBoxLayout(row1)
        layout1.setContentsMargins(10, 0, 10, 0)
        layout1.addWidget(cb1)
        table.setCellWidget(0, 0, row1)

        # 第二行：数值可修改
        edit = QLineEdit(default_value)
        edit.setMaximumWidth(60)
        row2 = QWidget()
        layout2 = QHBoxLayout(row2)
        layout2.setContentsMargins(10, 0, 10, 0)
        layout2.addWidget(QLabel("距U形换热管弯管切点"))
        layout2.addWidget(edit)
        layout2.addWidget(QLabel("mm的直管段范围内不得设置折流板或支持板。"))
        layout2.addStretch()
        table.setCellWidget(1, 0, row2)

        table._center_supp_inputs = {
            "cb1": cb1,
            "edit": edit
        }

        # 绑定保存
        if not hasattr(table, "_save_connected_center_supp"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_center_distance_supplement_config(table, cursor.connection, user_id)
                )
                table._save_connected_center_supp = True

    except Exception as e:
        print(f"[错误] 加载换热管中心距补充配置失败: {e}")
def save_center_distance_supplement_config(table: QTableWidget, db_conn, user_id):
    try:
        data = table._center_supp_inputs
        cb1_checked = data["cb1"].isChecked()
        value2 = data["edit"].text().strip()

        lines = []
        if cb1_checked:
            lines.append("外径为25mm的换热管采用转角正方形排列时，其分程隔板槽两侧相邻管中心距Sn取45.25mm。")
        lines.append(f"距U形换热管弯管切点{value2}mm的直管段范围内不得设置折流板或支持板。")

        final_value = "\n".join(lines)

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 换热管中心距补充预定义用户表 WHERE user_id = %s", (user_id,))
        cursor.execute("INSERT INTO 换热管中心距补充预定义用户表 (user_id, value) VALUES (%s, %s)", (user_id, final_value))
        db_conn.commit()
        cursor.close()

        print("[保存成功] 换热管中心距补充配置已更新")

    except Exception as e:
        print(f"[错误] 保存换热管中心距补充配置失败: {e}")
