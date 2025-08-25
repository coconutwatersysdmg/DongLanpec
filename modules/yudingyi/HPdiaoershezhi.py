from PyQt5.QtWidgets import QWidget, QLabel, QLineEdit, QTableWidget, QHBoxLayout, QVBoxLayout
from PyQt5.QtCore import Qt

def hp_diaoer_guiize_config(table: QTableWidget, cursor, user_id):
    try:
        defaults = {
            "thk_limit": "40",
            "tie_thk_limit": "20",
            "tie_thk_value": "20"
        }

        cursor.execute("SELECT value FROM HP吊耳规则预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        if result:
            try:
                val = result[0]
                defaults["thk_limit"] = val.split("名义厚度 ≤")[1].split("mm")[0].strip()
                defaults["tie_thk_limit"] = val.split("吊耳名义厚度 ≤")[1].split("mm")[0].strip()
                defaults["tie_thk_value"] = val.split("吊耳名义厚度 >")[1].split("mm")[0].strip()
            except Exception as e:
                print(f"[警告] 吊耳规则解析失败: {e}")

        table.clear()
        table.setRowCount(2)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["HP吊耳规则设置"])
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        edits = {
            "thk_limit": QLineEdit(defaults["thk_limit"]),
            "tie_thk_limit": QLineEdit(defaults["tie_thk_limit"]),
            "tie_thk_value": QLineEdit(defaults["tie_thk_value"]),
        }

        # 句①
        row1 = QWidget()
        hbox1 = QHBoxLayout(row1)
        hbox1.setContentsMargins(10, 0, 10, 0)
        hbox1.addWidget(QLabel("当容器封头或筒节的名义厚度 ≤"))
        hbox1.addWidget(edits["thk_limit"])
        hbox1.addWidget(QLabel("mm 时，吊耳厚度与容器封头或筒节名义厚度相同（满足选用或计算要求时）。"))
        hbox1.addStretch()
        table.setCellWidget(0, 0, row1)

        # 句②
        row2 = QWidget()
        hbox2 = QHBoxLayout(row2)
        hbox2.setContentsMargins(10, 0, 10, 0)
        hbox2.addWidget(QLabel("如需设置系揽环板时，当吊耳名义厚度 ≤"))
        hbox2.addWidget(edits["tie_thk_limit"])
        hbox2.addWidget(QLabel("mm 时，系揽环板厚度与吊耳厚度相同，当吊耳名义厚度 >"))
        hbox2.addWidget(edits["tie_thk_value"])
        hbox2.addWidget(QLabel("mm 时，系揽环板厚度取该值。"))
        hbox2.addStretch()
        table.setCellWidget(1, 0, row2)

        table._hp_diaoer_inputs = edits

        if not hasattr(table, '_save_connected_hp_diaoer'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_hp_diaoer_guiize(table, cursor.connection, user_id)
                )
                table._save_connected_hp_diaoer = True

    except Exception as e:
        print(f"[错误] 加载 HP 吊耳规则失败: {e}")
import re

def clean_number(text):
    result = re.findall(r"\d+\.?\d*", text.strip())
    return result[0] if result else ""

def save_hp_diaoer_guiize(table: QTableWidget, db_conn, user_id):
    try:
        edits = table._hp_diaoer_inputs

        sentence = (
            f"当容器封头或筒节的名义厚度 ≤ {clean_number(edits['thk_limit'].text())}mm 时，"
            f"吊耳厚度与容器封头或筒节名义厚度相同（满足选用或计算要求时）。\n"
            f"如需设置系揽环板时，当吊耳名义厚度 ≤ {clean_number(edits['tie_thk_limit'].text())}mm 时，"
            f"系揽环板厚度与吊耳厚度相同，当吊耳名义厚度 > {clean_number(edits['tie_thk_limit'].text())}mm 时，"
            f"系揽环板厚度取 {clean_number(edits['tie_thk_value'].text())}mm。"
        )

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM HP吊耳规则预定义用户表 WHERE user_id = %s", (user_id,))
        cursor.execute(
            "INSERT INTO HP吊耳规则预定义用户表 (user_id, value) VALUES (%s, %s)",
            (user_id, sentence)
        )
        db_conn.commit()
        cursor.close()

        print(f"[保存成功] HP吊耳规则已更新")

    except Exception as e:
        print(f"[错误] 保存 HP 吊耳规则失败: {e}")
