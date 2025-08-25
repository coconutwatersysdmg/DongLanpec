import re

from PyQt5.QtWidgets import QWidget, QLabel, QLineEdit, QVBoxLayout, QHBoxLayout, QTableWidget
from PyQt5.QtCore import Qt

def buqiangquan_xianzhi_config(table: QTableWidget, cursor, user_id):
    try:
        # 默认值
        values = {
            "pressure": "6.4",
            "temp_min": "-20",
            "temp_max": "350",
            "rm_max": "540",
            "thickness_max": "38",
            "ratio_min": "0.25",
            "ratio_max": "1.5",
            "carbon_max": "32",
            "q345r_max": "30"
        }

        # 读取旧值
        cursor.execute("SELECT value FROM 补强圈的使用限制预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        if result:
            val = result[0]
            try:
                # 1. 压力
                match = re.search(r"设计压力 < ([\d.]+)MPa", val)
                if match: values["pressure"] = match.group(1)

                # 2. 温度
                match = re.search(r"([\d\-.]+)℃ ≤ 设计温度 ≤ ([\d.]+)℃", val)
                if match:
                    values["temp_min"] = match.group(1)
                    values["temp_max"] = match.group(2)

                # 3. R_m
                match = re.search(r"R_m < ([\d.]+)MPa", val)
                if match: values["rm_max"] = match.group(1)

                # 4. 壳体名义厚度
                match = re.search(r"δ_n ≤ ([\d.]+)mm", val)
                if match: values["thickness_max"] = match.group(1)

                # 5. 厚度比和最大厚度限制
                match = re.search(
                    r"([\d.]+)δ_n ≤ 补强圈厚度 ≤ ([\d.]+)δ_n.*碳钢：([\d.]+)mm；Q345R：([\d.]+)mm", val
                )
                if match:
                    values["ratio_min"] = match.group(1)
                    values["ratio_max"] = match.group(2)
                    values["carbon_max"] = match.group(3)
                    values["q345r_max"] = match.group(4)

            except Exception as e:
                print(f"[警告] 解析旧值失败: {e}")

        # 创建表格
        table.clear()
        table.setRowCount(5)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["补强圈使用限制"])
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        edits = {}

        def make_row(*widgets):
            w = QWidget()
            layout = QHBoxLayout(w)
            layout.setContentsMargins(10, 0, 10, 0)
            for item in widgets:
                layout.addWidget(item if isinstance(item, QWidget) else QLabel(str(item)))
            layout.addStretch()
            return w

        # 第1行：设计压力
        edits["pressure"] = QLineEdit(values["pressure"])
        table.setCellWidget(0, 0, make_row("设计压力 <", edits["pressure"], "MPa；"))

        # 第2行：温度范围
        edits["temp_min"] = QLineEdit(values["temp_min"])
        edits["temp_max"] = QLineEdit(values["temp_max"])
        table.setCellWidget(1, 0, make_row(edits["temp_min"], "℃ ≤ 设计温度 ≤", edits["temp_max"], "℃；"))

        # 第3行：Rm
        edits["rm_max"] = QLineEdit(values["rm_max"])
        table.setCellWidget(2, 0, make_row("钢材的标准抗拉强度下限值 R_m <", edits["rm_max"], "MPa；"))

        # 第4行：壳体名义厚度
        edits["thickness_max"] = QLineEdit(values["thickness_max"])
        table.setCellWidget(3, 0, make_row("壳体名义厚度 δ_n ≤", edits["thickness_max"], "mm；"))

        # 第5行：厚度比范围 + 限制
        edits["ratio_min"] = QLineEdit(values["ratio_min"])
        edits["ratio_max"] = QLineEdit(values["ratio_max"])
        edits["carbon_max"] = QLineEdit(values["carbon_max"])
        edits["q345r_max"] = QLineEdit(values["q345r_max"])
        table.setCellWidget(4, 0, make_row(
            edits["ratio_min"], "δ_n ≤ 补强圈厚度 ≤", edits["ratio_max"], "δ_n，及最大厚度限制值（碳钢：",
            edits["carbon_max"], "mm；Q345R：", edits["q345r_max"], "mm）。"
        ))

        table._buqiangquan_inputs = edits

        if not hasattr(table, '_save_connected_bqq_limit_row'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_buqiangquan_xianzhi_config(table, cursor.connection, user_id)
                )
                table._save_connected_bqq_limit_row = True

    except Exception as e:
        print(f"[错误] 加载补强圈使用限制配置失败: {e}")

def save_buqiangquan_xianzhi_config(table: QTableWidget, db_conn, user_id):
    try:
        edits = table._buqiangquan_inputs

        sentence = (
            f"同时满足下列条款时，使用补强圈结构进行开孔补强："
            f"设计压力 < {edits['pressure'].text()}MPa；"
            f"{edits['temp_min'].text()}℃ ≤ 设计温度 ≤ {edits['temp_max'].text()}℃；"
            f"钢材的标准抗拉强度下限值 R_m < {edits['rm_max'].text()}MPa；"
            f"壳体名义厚度 δ_n ≤ {edits['thickness_max'].text()}mm；"
            f"{edits['ratio_min'].text()}δ_n ≤ 补强圈厚度 ≤ {edits['ratio_max'].text()}δ_n"
            f"及最大厚度限制值（碳钢：{edits['carbon_max'].text()}mm；Q345R：{edits['q345r_max'].text()}mm）。"
        )

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 补强圈的使用限制预定义用户表 WHERE user_id = %s", (user_id,))
        cursor.execute(
            "INSERT INTO 补强圈的使用限制预定义用户表 (user_id, value) VALUES (%s, %s)",
            (user_id, sentence)
        )
        db_conn.commit()
        cursor.close()
        print(f"[保存成功] 用户 {user_id} 的补强圈使用限制配置已保存")

    except Exception as e:
        print(f"[错误] 保存补强圈使用限制配置失败: {e}")
