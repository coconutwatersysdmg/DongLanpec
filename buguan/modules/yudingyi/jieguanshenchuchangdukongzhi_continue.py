import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QCheckBox, QHBoxLayout, QWidget, QLabel, QLineEdit, QTableWidget
def resource_path(relative_path):
    """获取打包后的资源路径"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)  # _MEIPASS 是 PyInstaller 解压临时目录
    return os.path.join(os.path.abspath("."), relative_path)

def jieguanshenchuchangdukongzhi_continue(table: QTableWidget, cursor, user_id, config_type=None):
    try:
        table.clearContents()
        table.setRowCount(0)
        table.setColumnCount(0)
        table.clear()
        table.setRowCount(6)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(['配置内容'])

        # 默认值
        val1 = "50"
        val2 = "25"
        opt1, opt2 = False, False

        # ✅ 查询旧值（从新表中）
        cursor.execute("SELECT value FROM 接管伸出长度控制2预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        if result:
            text = result[0]
            try:
                val1 = text.split("距离不小于")[1].split("mm")[0].strip()
                val2 = text.split("距离不应小于")[1].split("mm")[0].strip()
                opt1 = "法兰密封面宜在同一水平面上" in text
                opt2 = "法兰密封面在同一水平面上" in text and not opt1
            except Exception as e:
                print("[警告] 解析失败，使用默认值", e)

        # 第1行
        row1_widget = QWidget()
        row1_layout = QHBoxLayout(row1_widget)
        row1_layout.setContentsMargins(0, 0, 0, 0)
        row1_layout.addWidget(QLabel("接管与带颈对焊法兰连接时，l值确定还应满足接管上的焊缝与壳体上焊缝之间的距离不小于"))
        val1_input = QLineEdit(val1)
        val1_input.setFixedWidth(50)
        row1_layout.addWidget(val1_input)
        row1_layout.addWidget(QLabel("mm；"))
        table.setCellWidget(0, 0, row1_widget)

        # 第2行图
        pic1 = QLabel()
        pix1 = QPixmap(resource_path(os.path.join("static", "接管伸出长度控制2.png")))
        pix1 = pix1.scaled(pix1.width() * 0.6, pix1.height() * 0.6, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pic1.setPixmap(pix1)
        pic1.setAlignment(Qt.AlignCenter)
        table.setCellWidget(1, 0, pic1)
        table.setRowHeight(1, pix1.height() + 20)

        # 第3行
        row3_widget = QWidget()
        row3_layout = QHBoxLayout(row3_widget)
        row3_layout.setContentsMargins(0, 0, 0, 0)
        row3_layout.addWidget(QLabel("接管轴线不垂直于壳体经线时，接管及其连接法兰的外缘与保温层之间的直线距离不应小于"))
        val2_input = QLineEdit(val2)
        val2_input.setFixedWidth(50)
        row3_layout.addWidget(val2_input)
        row3_layout.addWidget(QLabel("mm。"))
        table.setCellWidget(2, 0, row3_widget)

        # 第4行图
        pic2 = QLabel()
        pix2 = QPixmap(resource_path(os.path.join("static", "接管伸出长度控制3.png")))
        pix2 = pix2.scaled(pix2.width() * 0.6, pix2.height() * 0.6, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pic2.setPixmap(pix2)
        pic2.setAlignment(Qt.AlignCenter)
        table.setCellWidget(3, 0, pic2)
        table.setRowHeight(3, pix2.height() + 20)

        # 第5行复选框
        row5_widget = QWidget()
        row5_layout = QHBoxLayout(row5_widget)
        row5_layout.setContentsMargins(0, 0, 0, 0)
        checkbox1 = QCheckBox("容器顶部接管的法兰密封面宜在同一水平面上。")
        checkbox1.setChecked(opt1)
        row5_layout.addWidget(checkbox1)
        table.setCellWidget(4, 0, row5_widget)

        # 第6行复选框
        row6_widget = QWidget()
        row6_layout = QHBoxLayout(row6_widget)
        row6_layout.setContentsMargins(0, 0, 0, 0)
        checkbox2 = QCheckBox("容器底(侧)部接管的法兰密封面在同一水平面上。")
        checkbox2.setChecked(opt2)
        row6_layout.addWidget(checkbox2)
        table.setCellWidget(5, 0, row6_widget)

        # 保存引用
        table._val1_input = val1_input
        table._val2_input = val2_input
        table._checkbox1 = checkbox1
        table._checkbox2 = checkbox2

        # 绑定保存
        if not hasattr(table, '_save_connected_buzhou'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_buzhouchicun(table, cursor.connection, user_id)
                )
                table._save_connected_buzhou = True

                # 为图像行设置合理行高
            table.setRowHeight(1, int(pix1.height() * 0.6) + 40)
            table.setRowHeight(3, int(pix2.height() * 0.6) + 40)

            # 为其余行设默认高度
            for i in range(table.rowCount()):
                if i not in [1, 3]:  # 非图像行
                    table.setRowHeight(i, 60)

    except Exception as e:
        print(f"[错误] 加载布置尺寸配置失败: {e}")
def save_buzhouchicun(table: QTableWidget, db_conn, user_id):
    try:
        val1 = table._val1_input.text()
        val2 = table._val2_input.text()
        checkbox1 = table._checkbox1.isChecked()
        checkbox2 = table._checkbox2.isChecked()

        text1 = f"接管与带颈对焊法兰连接时，l值确定还应满足接管上的焊缝与壳体上焊缝之间的距离不小于{val1}mm；"
        text2 = f"接管轴线不垂直于壳体经线时，接管及其连接法兰的外缘与保温层之间的直线距离不应小于{val2}mm。"

        extras = []
        if checkbox1:
            extras.append("容器顶部接管的法兰密封面宜在同一水平面上。")
        if checkbox2:
            extras.append("容器底(侧)部接管的法兰密封面在同一水平面上。")

        value_str = text1 + "\n" + text2 + ("\n" + "\n".join(extras) if extras else "")

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 接管伸出长度控制2预定义用户表 WHERE user_id = %s", (user_id,))
        cursor.execute(
            "INSERT INTO 接管伸出长度控制2预定义用户表 (value, user_id) VALUES (%s, %s)",
            (value_str, user_id)
        )
        db_conn.commit()
        cursor.close()

        print(f"[保存成功] 接管伸出长度控制2配置: {value_str}")
    except Exception as e:
        print(f"[错误] 保存布置尺寸配置失败: {e}")
