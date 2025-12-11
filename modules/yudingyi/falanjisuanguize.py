from PyQt5.QtWidgets import QWidget, QCheckBox, QLabel, QLineEdit, QHBoxLayout, QVBoxLayout, QTableWidget
from PyQt5.QtCore import Qt

from PyQt5.QtWidgets import QWidget, QCheckBox, QLabel, QLineEdit, QHBoxLayout, QTableWidget
from PyQt5.QtCore import Qt

def falanjisuan_guize_config_static(table: QTableWidget, cursor, user_id, config_type):
    try:
        # 默认值
        defaults = {
            "δ0_min": "0", "δ0_max": "15",
            "ratio_min": "0", "ratio_max": "300",
            "pressure_min": "0", "pressure_max": "2",
            "temp_min": "0", "temp_max": "370"
        }

        # 查询是否已有配置（解析自然语言值）
        cursor.execute("SELECT value FROM 法兰计算规则预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        selected = False
        if result:
            selected = True
            try:
                val = result[0]
                defaults["δ0_min"] = val.split("≤ δ0 ≤")[0].split("：")[-1].strip()
                defaults["δ0_max"] = val.split("≤ δ0 ≤")[1].split("mm")[0].strip()
                defaults["ratio_min"] = val.split("≤ Di/δ0 ≤")[0].split("，")[-1].strip()
                defaults["ratio_max"] = val.split("≤ Di/δ0 ≤")[1].split("；")[0].strip()
                defaults["pressure_min"] = val.split("MPa < 设计压力 ≤")[0].split("；")[-1].strip()
                defaults["pressure_max"] = val.split("MPa < 设计压力 ≤")[1].split(" MPa")[0].strip()
                defaults["temp_min"] = val.split("°C < 设计温度 ≤")[0].split("；")[-1].strip()
                defaults["temp_max"] = val.split("°C < 设计温度 ≤")[1].split(" °C")[0].strip()
            except Exception as e:
                print(f"[警告] 解析旧值失败，使用默认值: {e}")

        # 创建表格
        table.clear()
        table.setRowCount(1)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["法兰计算规则"])
        table.verticalHeader().setDefaultSectionSize(80)
        table.horizontalHeader().setStretchLastSection(True)

        # 控件
        checkbox = QCheckBox("启用")
        checkbox.setChecked(selected)

        δ0_min = QLineEdit(defaults["δ0_min"])
        δ0_max = QLineEdit(defaults["δ0_max"])
        ratio_min = QLineEdit(defaults["ratio_min"])
        ratio_max = QLineEdit(defaults["ratio_max"])
        pressure_min = QLineEdit(defaults["pressure_min"])
        pressure_max = QLineEdit(defaults["pressure_max"])
        temp_min = QLineEdit(defaults["temp_min"])
        temp_max = QLineEdit(defaults["temp_max"])

        layout = QHBoxLayout()
        layout.setContentsMargins(10, 0, 10, 0)
        layout.addWidget(checkbox)
        layout.addWidget(QLabel("任意式法兰，GB/T 150.3中图8-1h)、i）、j）、k)的焊接法兰，当同时满足下列条件时也按活套法兰计算："))
        layout.addWidget(δ0_min)
        layout.addWidget(QLabel(" ≤ δ0 ≤ "))
        layout.addWidget(δ0_max)
        layout.addWidget(QLabel(" mm，"))
        layout.addWidget(ratio_min)
        layout.addWidget(QLabel(" ≤ Di/δ0 ≤ "))
        layout.addWidget(ratio_max)
        layout.addWidget(QLabel("；"))
        layout.addWidget(pressure_min)
        layout.addWidget(QLabel(" MPa < 设计压力 ≤ "))
        layout.addWidget(pressure_max)
        layout.addWidget(QLabel(" MPa；"))
        layout.addWidget(temp_min)
        layout.addWidget(QLabel(" °C < 设计温度 ≤ "))
        layout.addWidget(temp_max)
        layout.addWidget(QLabel(" °C。"))
        layout.addStretch()

        container = QWidget()
        container.setLayout(layout)
        table.setCellWidget(0, 0, container)

        table._falan_guize_widget = (
            checkbox, δ0_min, δ0_max, ratio_min, ratio_max,
            pressure_min, pressure_max, temp_min, temp_max
        )

        if not hasattr(table, '_save_connected_falan_static'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_falanjisuan_static_to_user_table(table, cursor.connection, user_id)
                )
                table._save_connected_falan_static = True

    except Exception as e:
        print(f"[错误] 加载法兰计算规则配置失败: {e}")
def save_falanjisuan_static_to_user_table(table: QTableWidget, db_conn, user_id):
    try:
        (
            checkbox, δ0_min, δ0_max, ratio_min, ratio_max,
            pressure_min, pressure_max, temp_min, temp_max
        ) = table._falan_guize_widget

        cursor = db_conn.cursor()
        # 先删除旧配置
        cursor.execute("DELETE FROM 法兰计算规则预定义用户表 WHERE user_id=%s", (user_id,))

        if checkbox.isChecked():
            sentence = (
                f"任意式法兰，GB/T 150.3中图8-1h)、i）、j）、k)的焊接法兰，当同时满足下列条件时也按活套法兰计算："
                f"{δ0_min.text()} ≤ δ0 ≤ {δ0_max.text()} mm，"
                f"{ratio_min.text()} ≤ Di/δ0 ≤ {ratio_max.text()}；"
                f"{pressure_min.text()} MPa < 设计压力 ≤ {pressure_max.text()} MPa；"
                f"{temp_min.text()} °C < 设计温度 ≤ {temp_max.text()} °C。"
            )
            cursor.execute(
                "INSERT INTO 法兰计算规则预定义用户表 (user_id, value) VALUES (%s, %s)",
                (user_id, sentence)
            )

        db_conn.commit()
        cursor.close()
        print(f"[保存成功] 用户 {user_id} 的法兰计算规则已更新")
    except Exception as e:
        print(f"[错误] 保存法兰计算规则失败: {e}")
