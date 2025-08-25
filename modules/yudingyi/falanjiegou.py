import sys

from PyQt5.QtWidgets import (
    QTableWidget, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QCheckBox, QRadioButton, QLineEdit
)
from PyQt5.QtGui import QPixmap, QFont
from PyQt5.QtCore import Qt
import os
def resource_path(relative_path):
    """获取打包后的资源路径"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)  # _MEIPASS 是 PyInstaller 解压临时目录
    return os.path.join(os.path.abspath("."), relative_path)
def flange_structure_config(table: QTableWidget, cursor, user_id, config_type):
    try:
        table.clear()
        table.setRowCount(4)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(['配置内容'])

        # 加载旧数据
        cursor.execute("""
            SELECT id, value FROM 法兰结构预定义用户表 WHERE user_id = %s
        """, (user_id,))
        rows = cursor.fetchall()
        config_data = {row[0]: row[1] for row in rows}

        bold_font = QFont()
        bold_font.setBold(True)

        # ========== 1. 对焊法兰锥段斜度大于1:3 型式选用 ==========
        row1 = QWidget()
        layout1 = QVBoxLayout(row1)
        layout1.setContentsMargins(0, 0, 0, 0)
        layout1.addWidget(QLabel("对焊法兰锥段斜度大于1:3时的型式选用："))

        cb1_1 = QCheckBox("Ⅰ型")
        cb1_2 = QCheckBox("Ⅱ型")
        selected1 = config_data.get("对焊法兰（斜度大于1:3）", "").split(";")
        cb1_1.setChecked("Ⅰ型" in selected1)
        cb1_2.setChecked("Ⅱ型" in selected1)

        img_layout1 = QHBoxLayout()
        img_layout1.addWidget(cb1_1)
        img1 = QLabel()
        img1.setPixmap(load_image(resource_path("static/对焊法兰锥1.png")))
        img_layout1.addWidget(img1)
        img_layout1.addWidget(cb1_2)
        img2 = QLabel()
        img2.setPixmap(load_image(resource_path("static/对焊法兰锥2.png")))
        img_layout1.addWidget(img2)
        layout1.addLayout(img_layout1)
        table.setCellWidget(0, 0, row1)

        # ========== 2. 衬里法兰结构形式 ==========
        row2 = QWidget()
        layout2 = QVBoxLayout(row2)
        layout2.setContentsMargins(0, 0, 0, 0)
        layout2.addWidget(QLabel("衬里法兰结构形式："))

        cb2_1 = QCheckBox("Ⅰ型")
        cb2_2 = QCheckBox("Ⅱ型")
        selected2 = config_data.get("衬里法兰结构形式", "").split(";")
        cb2_1.setChecked("Ⅰ型" in selected2)
        cb2_2.setChecked("Ⅱ型" in selected2)

        img_layout2 = QHBoxLayout()
        img_layout2.addWidget(cb2_1)
        img3 = QLabel()
        img3.setPixmap(load_image(resource_path("static/衬里法兰1.png")))
        img_layout2.addWidget(img3)
        img_layout2.addWidget(cb2_2)
        img4 = QLabel()
        img4.setPixmap(load_image(resource_path("static/衬里法兰2.png")))
        img_layout2.addWidget(img4)
        layout2.addLayout(img_layout2)
        table.setCellWidget(1, 0, row2)

        # ========== 3. 管箱头盖法兰结构尺寸 ==========
        row3 = QWidget()
        layout3 = QVBoxLayout(row3)
        layout3.setContentsMargins(0, 0, 0, 0)
        layout3.addWidget(QLabel("管箱头盖法兰结构尺寸的确定："))

        radio1 = QRadioButton("管箱头盖法兰结构尺寸与管箱法兰保持一致")
        radio2 = QRadioButton("当管/壳程设计压力值相等时，管箱头盖法兰结构尺寸与管箱法兰保持一致")
        selected_radio = config_data.get("管箱头盖法兰结构尺寸", "")
        radio1.setChecked(selected_radio == radio1.text())
        radio2.setChecked(selected_radio == radio2.text())

        layout3.addWidget(radio1)
        layout3.addWidget(radio2)
        table.setCellWidget(2, 0, row3)

        # ========== 4. 焊法兰圆角半径 ==========
        row4 = QWidget()
        layout4 = QVBoxLayout(row4)
        layout4.setContentsMargins(0, 0, 0, 0)
        layout4.addWidget(QLabel("焊法兰圆角半径："))

        sub_layout = QHBoxLayout()
        sub_layout.addWidget(QLabel("r ≥"))
        r_input1 = QLineEdit()
        r_input2 = QLineEdit()
        text_r = config_data.get("焊法兰圆角半径", "")
        import re
        match = re.findall(r"r ≥ ([\d.]+).*?([0-9]+)mm", text_r)
        if match:
            r_input1.setText(match[0][0])
            r_input2.setText(match[0][1])
        else:
            r_input1.setText("0.25")
            r_input2.setText("10")
        sub_layout.addWidget(r_input1)
        sub_layout.addWidget(QLabel("× δ₁，且不小于"))
        sub_layout.addWidget(r_input2)
        sub_layout.addWidget(QLabel("mm。"))
        layout4.addLayout(sub_layout)
        table.setCellWidget(3, 0, row4)

        # 设置统一行高
        for i in range(4):
            table.setRowHeight(i, 140)

        # 保存句柄
        table._flange_config_state = {
            "cb1": [cb1_1, cb1_2],
            "cb2": [cb2_1, cb2_2],
            "radio": [radio1, radio2],
            "r1": r_input1,
            "r2": r_input2,
        }

        if not hasattr(table, "_save_connected_flange"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(lambda: save_flange_config(
                    table, cursor.connection, user_id
                ))
                table._save_connected_flange = True
    except Exception as e:
        print("[错误] 加载法兰结构配置失败：", e)

def save_flange_config(table: QTableWidget, db_conn, user_id):
    try:
        state = table._flange_config_state
        data = [
            ("对焊法兰（斜度大于1:3）", ";".join(cb.text() for cb in state["cb1"] if cb.isChecked())),
            ("衬里法兰结构形式", ";".join(cb.text() for cb in state["cb2"] if cb.isChecked())),
            ("管箱头盖法兰结构尺寸", state["radio"][0].text() if state["radio"][0].isChecked() else state["radio"][1].text()),
            ("焊法兰圆角半径", f"r ≥ {state['r1'].text()}×δ₁，且不小于 {state['r2'].text()}mm。"),
        ]

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 法兰结构预定义用户表 WHERE user_id = %s", (user_id,))
        for entry_id, val in data:
            cursor.execute(
                "INSERT INTO 法兰结构预定义用户表 (id, value, user_id) VALUES (%s, %s, %s)",
                (entry_id, val, user_id)
            )
        db_conn.commit()
        cursor.close()
        print(f"[保存成功] user_id={user_id} 的法兰结构数据已保存")
    except Exception as e:
        print("[错误] 保存失败：", e)

def load_image(path):
    abs_path = os.path.abspath(path)
    if os.path.exists(abs_path):
        return QPixmap(abs_path).scaledToHeight(80)
    else:
        print(f"[警告] 图片未找到：{abs_path}")
        return QPixmap()
