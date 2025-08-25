import re

from PyQt5.QtWidgets import QTableWidget, QHBoxLayout, QWidget, QLineEdit, QLabel, QVBoxLayout


def fenxifa_yiban_config(table: QTableWidget, cursor, user_id):
    try:
        # 默认数值
        values = {
            "ratio_max": "0.8",
            "coef_cylinder": "1",
            "coef_nozzle": "1",
            "r_min_coef": "0.125",
            "r_max_coef": "0.5"
        }

        # 查询旧值
        cursor.execute("SELECT value FROM 分析法一般要求预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        if result:
            try:
                val = result[0]
                values["ratio_max"] = re.search(r"R_eL/R_m ≤ ([\d.]+)", val).group(1)
                values["coef_cylinder"] = re.search(r"圆筒 l > ([\d.]+)×√", val).group(1)
                values["coef_nozzle"] = re.search(r"接管 l_t > ([\d.]+)×√", val).group(1)
                values["r_min_coef"] = re.search(r"在 ([\d.]+)×δ_n", val).group(1)
                values["r_max_coef"] = re.search(r"≤ ([\d.]+)×δ_n", val).group(1)
            except Exception as e:
                print(f"[警告] 解析旧值失败: {e}")

        table.clear()
        table.setRowCount(3)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["分析法一般要求"])
        table.verticalHeader().setDefaultSectionSize(60)
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

        # 第1句
        edits["ratio_max"] = QLineEdit(values["ratio_max"])
        table.setCellWidget(0, 0, make_row(
            "圆筒、接管或补强件的材料，其标准室温屈服强度与标准抗拉强度下限值之比 R_eL/R_m ≤",
            edits["ratio_max"], "；"
        ))

        # 第2句：长句多行显示
        sub = QWidget()
        vbox = QVBoxLayout(sub)
        vbox.setContentsMargins(10, 0, 10, 0)

        line1 = QHBoxLayout()
        edits["coef_cylinder"] = QLineEdit(values["coef_cylinder"])
        edits["coef_nozzle"] = QLineEdit(values["coef_nozzle"])
        line1.addWidget(QLabel("对圆筒或接管进行整体补强，应满足补强范围尺寸（对于圆筒 l >"))
        line1.addWidget(edits["coef_cylinder"])
        line1.addWidget(QLabel("×√(D_i δ_n)，对于接管 l_t >"))
        line1.addWidget(edits["coef_nozzle"])
        line1.addWidget(QLabel("×√(d_o δ_nt)），或整体加厚圆筒体；"))
        line1.addStretch()

        line2 = QHBoxLayout()
        line2.addWidget(QLabel("补强范围内的 A、B 类焊接接头不得有任何超标缺陷，必要时应对此提出无损检测要求；"))
        line2.addStretch()

        vbox.addLayout(line1)
        vbox.addLayout(line2)
        table.setCellWidget(1, 0, sub)

        edits["weld_coef"] = QLineEdit("1")  # 新增：可编辑的 1 倍焊脚系数
        edits["r_min_coef"] = QLineEdit(values["r_min_coef"])
        edits["r_max_coef"] = QLineEdit(values["r_max_coef"])

        table.setCellWidget(2, 0, make_row(
            "圆筒与接管之间角焊缝的焊脚尺寸应分别不小于 ",
            edits["weld_coef"], "×max(δ_n/2 , δ_nt/2)， 接管内壁与圆筒内壁交线处圆角半径 R 满足：在 ",
            edits["r_min_coef"], "×δ_n /8 ≤ R ≤ ", edits["r_max_coef"], "×δ_n；"
        ))

        table._fenxifa_inputs = edits

        if not hasattr(table, '_save_connected_fenxifa'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_fenxifa_yiban_config(table, cursor.connection, user_id)
                )
                table._save_connected_fenxifa = True

    except Exception as e:
        print(f"[错误] 加载分析法一般要求失败: {e}")
def save_fenxifa_yiban_config(table: QTableWidget, db_conn, user_id):
    try:
        edits = table._fenxifa_inputs
        val = (
            f"圆筒、接管或补强件的材料，其标准室温屈服强度与标准抗拉强度下限值之比 R_eL/R_m ≤ {edits['ratio_max'].text()}；"
            f"对圆筒或接管进行整体补强，应满足补强范围尺寸（对于圆筒 l > {edits['coef_cylinder'].text()}×√(D_i δ_n)，"
            f"对于接管 l_t > {edits['coef_nozzle'].text()}×√(d_o δ_nt)），或整体加厚圆筒体；"
            f"补强范围内的 A、B 类焊接接头不得有任何超标缺陷，必要时应对此提出无损检测要求；"
            f"圆筒与接管之间角焊缝的焊脚尺寸应分别不小于 1×max(δ_n/2 , δ_nt/2)， 接管内壁与圆筒内壁交线处圆角半径 R 满足："
            f"在 {edits['r_min_coef'].text()}×δ_n /8 ≤ R ≤ {edits['r_max_coef'].text()}×δ_n；"
        )

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 分析法一般要求预定义用户表 WHERE user_id = %s", (user_id,))
        cursor.execute(
            "INSERT INTO 分析法一般要求预定义用户表 (user_id, value) VALUES (%s, %s)",
            (user_id, val)
        )
        db_conn.commit()
        cursor.close()
        print(f"[保存成功] 分析法一般要求配置已保存")
    except Exception as e:
        print(f"[错误] 保存失败: {e}")
