from PyQt5.QtWidgets import QWidget, QCheckBox, QLabel, QLineEdit, QHBoxLayout, QTableWidget, QTableWidgetItem
from PyQt5.QtCore import Qt
import re

def build_reinforce_general_config(table: QTableWidget, cursor, user_id):
    try:
        # 定义所有句子和可编辑部分的位置
        items = [
            # label template, [(placeholder_text, default_value)]
            ("接管与筒体壁厚比值控制在下限值{}~上限值{}；", [("下限值", "0.5"), ("上限值", "2.5")]),
            ("是否使用补强圈和厚壁锻管联合补强结构；", []),
            ("是否使用增加壳体厚度的方法进行开孔补强(增厚量≤{}mm)（20250508修订）；", [("增厚量", "10")]),
            ("焊缝面积A3计入实际补强面积(焊脚高度按 {} 倍补强件较薄厚度)（本条款始终开启）（20250508修订）；",[("焊脚系数", "0.7")], True),
            ("接管最小实际外伸高度h≥{}√(d_op δ_nt)，δ_nt为接管名义厚度。（20250508修订）", [("系数", "0.8")]),
            ("在满足使用限制的条件下，优先使用补强圈结构(如需)对开孔进行补强；", []),
            ("{}不使用补强圈结构进行开孔补强。（20250418修订）", [("组件", "管箱圆筒")]),
            ("{}不使用补强圈结构进行开孔补强。（20250418修订）", [("组件", "壳程圆筒")]),
            ("{}不使用补强圈结构进行开孔补强。（20250418修订）", [("组件", "封头")])
        ]

        # 查询用户已选项
        cursor.execute("SELECT value FROM 等面积补强方法的一般要求预定义用户表 WHERE user_id = %s", (user_id,))
        saved = set(row[0] for row in cursor.fetchall())

        table.clear()
        table.setRowCount(len(items))
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["等面积补强方法一般要求"])
        table.verticalHeader().setDefaultSectionSize(60)
        table.horizontalHeader().setStretchLastSection(True)

        table._reinforce_items = []

        for idx, (template, vars, *force_checked) in enumerate(items):
            checkbox = QCheckBox()
            editable_values = []
            label_text = template
            for placeholder, default in vars:
                lineedit = QLineEdit(default)
                editable_values.append(lineedit)
            # 替换 {} 为输入框
            parts = template.split("{}")
            layout = QHBoxLayout()
            layout.setContentsMargins(10, 0, 10, 0)
            layout.addWidget(checkbox)

            for i, part in enumerate(parts):
                layout.addWidget(QLabel(part))
                if i < len(editable_values):
                    layout.addWidget(editable_values[i])

            layout.addStretch()
            container = QWidget()
            container.setLayout(layout)
            table.setCellWidget(idx, 0, container)

            sentence = template.format(*(edit.text() for edit in editable_values))
            if sentence in saved or (force_checked and force_checked[0]):
                checkbox.setChecked(True)
            if force_checked and force_checked[0]:
                checkbox.setEnabled(False)  # 第 4 条始终开启

            table._reinforce_items.append((checkbox, template, editable_values))

        # 保存按钮绑定
        if not hasattr(table, '_save_connected_reinforce'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_reinforce_general_config(table, cursor.connection, user_id)
                )
                table._save_connected_reinforce = True

    except Exception as e:
        print(f"[错误] 加载等面积补强方法配置失败: {e}")
def save_reinforce_general_config(table: QTableWidget, db_conn, user_id):
    try:
        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 等面积补强方法的一般要求预定义用户表 WHERE user_id = %s", (user_id,))

        for checkbox, template, edits in table._reinforce_items:
            if checkbox.isChecked():
                sentence = template.format(*(edit.text() for edit in edits))
                cursor.execute(
                    "INSERT INTO 等面积补强方法的一般要求预定义用户表 (user_id, value) VALUES (%s, %s)",
                    (user_id, sentence)
                )

        db_conn.commit()
        cursor.close()
        print(f"[保存成功] 用户 {user_id} 的等面积补强方法配置已更新")
    except Exception as e:
        print(f"[错误] 保存等面积补强方法配置失败: {e}")
