from PyQt5.QtWidgets import (
    QWidget, QLabel, QLineEdit, QHBoxLayout, QTableWidget
)
from PyQt5.QtCore import Qt


def bancaijuanzhijieguanxianzhitiaojian(table: QTableWidget, cursor, user_id, config_type=None):
    try:
        table.clear()
        table.setRowCount(3)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["限制条件"])

        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        # 默认值
        rm_val, thickness_val, dn_val = "540", "32", "350"

        # ✅ 读取用户旧配置（改为新表）
        cursor.execute("""
            SELECT value 
            FROM 板材卷制接管限制条件预定义用户表 
            WHERE user_id = %s
        """, (user_id,))
        result = cursor.fetchone()
        if result:
            try:
                val = result[0]
                rm_val = val.split("Rm≤")[1].split("MPa")[0]
                thickness_val = val.split("厚度 ≤")[1].split("mm")[0]
                dn_val = val.split("规格 ≥DN")[1].strip()
            except Exception as e:
                print(f"[警告] 解析旧值失败，使用默认值: {e}")

        def build_row(prefix, input_widget, suffix=""):
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(10, 0, 10, 0)
            layout.addWidget(QLabel(prefix))
            input_widget.setMaximumWidth(80)
            layout.addWidget(input_widget)
            if suffix:
                layout.addWidget(QLabel(suffix))
            layout.addStretch()
            return widget

        # 设置行控件
        rm_input = QLineEdit(rm_val)
        table.setCellWidget(0, 0, build_row("板材标准抗拉强度下限值 Rm≤", rm_input, "MPa；"))

        thickness_input = QLineEdit(thickness_val)
        table.setCellWidget(1, 0, build_row("板材厚度 ≤", thickness_input, "mm；"))

        dn_input = QLineEdit(dn_val)
        table.setCellWidget(2, 0, build_row("接管最小成型规格 ≥DN", dn_input))

        table._pipe_inputs = (rm_input, thickness_input, dn_input)

        if not hasattr(table, '_save_connected_pipe_spec'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_pipe_spec(table, cursor.connection, user_id)
                )
                table._save_connected_pipe_spec = True
            else:
                print("[错误] 找不到 save_button")

    except Exception as e:
        print(f"[错误] 加载限制条件失败: {e}")
def save_pipe_spec(table: QTableWidget, db_conn, user_id, config_type=None):
    try:
        rm_input, thickness_input, dn_input = table._pipe_inputs
        rm_val = rm_input.text()
        thickness_val = thickness_input.text()
        dn_val = dn_input.text()

        value_str = (
            f"板材标准抗拉强度下限值 Rm≤{rm_val}MPa；"
            f"板材厚度 ≤{thickness_val}mm；"
            f"接管最小成型规格 ≥DN{dn_val}"
        )

        cursor = db_conn.cursor()
        cursor.execute(
            "DELETE FROM 板材卷制接管限制条件预定义用户表 WHERE user_id = %s",
            (user_id,)
        )
        cursor.execute(
            "INSERT INTO 板材卷制接管限制条件预定义用户表 (value, user_id) VALUES (%s, %s)",
            (value_str, user_id)
        )
        db_conn.commit()
        cursor.close()

        print(f"[保存成功] 限制条件: {value_str}")
    except Exception as e:
        print(f"[错误] 保存限制条件失败: {e}")
