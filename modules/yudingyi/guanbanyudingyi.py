from PyQt5.QtWidgets import QWidget, QLabel, QLineEdit, QCheckBox, QTableWidget, QHBoxLayout, QVBoxLayout, QMessageBox
from PyQt5.QtCore import Qt
import re

def guanban_config(table: QTableWidget, cursor, user_id):
    try:
        default1 = ["换热管"]  # 多选默认
        default2 = "1/2"
        default3 = "0.1"
        default4 = "50"

        cursor.execute("SELECT value FROM 管板预定义用户表 WHERE user_id = %s", (user_id,))
        result = cursor.fetchone()
        if result:
            text = result[0]
            try:
                if "管孔外径值" in text: default1.append("管孔外径值")
                m2 = re.search(r"布管限定圆直径的(.+?)处", text)
                if m2: default2 = m2.group(1)
                m3 = re.search(r"减小(\d+\.?\d*) mm", text)
                if m3: default3 = m3.group(1)
                m4 = re.search(r"超过(\d+\.?\d*)kg", text)
                if m4: default4 = m4.group(1)
            except Exception as e:
                print("[警告] 解析旧值失败", e)

        table.clear()
        table.setRowCount(5)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["管板配置规则"])
        table.verticalHeader().setDefaultSectionSize(50)
        table.horizontalHeader().setStretchLastSection(True)

        # ✅ 第一条：多选项
        row1 = QWidget()
        h1 = QHBoxLayout(row1)
        h1.setContentsMargins(10, 0, 10, 0)
        cb1 = QCheckBox("换热管")
        cb2 = QCheckBox("管孔外径值")
        cb1.setChecked("换热管" in default1)
        cb2.setChecked("管孔外径值" in default1)
        h1.addWidget(QLabel("使用"))
        h1.addWidget(cb1)
        h1.addWidget(cb2)
        h1.addWidget(QLabel("作为基础进行布管。"))
        h1.addStretch()
        table.setCellWidget(0, 0, row1)

        # ✅ 第二条
        edit2 = QLineEdit(default2)
        edit2.setMaximumWidth(80)
        row2 = QWidget()
        h2 = QHBoxLayout(row2)
        h2.setContentsMargins(10, 0, 10, 0)
        h2.addWidget(QLabel("在换热管布置过程中，如需在垂直中心线上设置拉杆时，一般设置在（垂直中心线）布管限定圆直径的"))
        h2.addWidget(edit2)
        h2.addWidget(QLabel("处。"))
        h2.addStretch()
        table.setCellWidget(1, 0, row2)

        # ✅ 第三条
        edit3 = QLineEdit(default3)
        edit3.setMaximumWidth(80)
        row3 = QWidget()
        h3 = QHBoxLayout(row3)
        h3.setContentsMargins(10, 0, 10, 0)
        h3.addWidget(QLabel("当奥氏体不锈钢、双相不锈钢、钛、铜、镍、锆及其合金换热管与管板采用强度胀接时，管板的管孔公称直径减小"))
        h3.addWidget(edit3)
        h3.addWidget(QLabel(" mm。"))
        h3.addStretch()
        table.setCellWidget(2, 0, row3)

        # ✅ 第四条
        edit4 = QLineEdit(default4)
        edit4.setMaximumWidth(80)
        row4 = QWidget()
        h4 = QHBoxLayout(row4)
        h4.setContentsMargins(10, 0, 10, 0)
        h4.addWidget(QLabel("管束的重量若超过"))
        h4.addWidget(edit4)
        h4.addWidget(QLabel("kg，在固定管板外侧设置环首螺钉用螺孔。"))
        h4.addStretch()
        table.setCellWidget(3, 0, row4)

        # ✅ 注释行仅展示
        note = ("复合管板覆层最小厚度及相应要求如下：\n"
                "   与换热管焊接连接的复合管板，其覆层的厚度不应小于3mm；\n"
                "   与接热管强度胀接连接的复合管板，其覆层最小厚度不宜小于10mm；\n"
                "第4条的含义为，配孔即待环首螺钉、丝堵两种零件。")
        note_label = QLabel(note)
        note_label.setWordWrap(True)
        note_label.setStyleSheet("color: gray;")
        table.setCellWidget(4, 0, note_label)
        table.setRowHeight(4, 100)

        # 保存引用
        table._guanban_inputs = {
            "cb1": cb1, "cb2": cb2,
            "edit2": edit2, "edit3": edit3, "edit4": edit4
        }

        if not hasattr(table, "_save_connected_guanban"):
            window = table.window()
            if hasattr(window, "save_button"):
                window.save_button.clicked.connect(
                    lambda: save_guanban_config(table, cursor.connection, user_id)
                )
                table._save_connected_guanban = True

    except Exception as e:
        print(f"[错误] 加载管板配置失败: {e}")
def save_guanban_config(table: QTableWidget, db_conn, user_id):
    try:
        data = table._guanban_inputs
        selected_basis = []
        if data["cb1"].isChecked():
            selected_basis.append("换热管")
        if data["cb2"].isChecked():
            selected_basis.append("管孔外径值")
        if not selected_basis:
            QMessageBox.warning(table, "提示", "请至少选择一个布管基础。")
            return

        val2 = data["edit2"].text().strip()
        val3 = data["edit3"].text().strip()
        val4 = data["edit4"].text().strip()

        try:
            f = float(val3)
            if not (0 <= f <= 0.1):
                raise ValueError
        except:
            QMessageBox.warning(table, "数值错误", "第3条减小值必须在0~0.1之间。")
            return

        lines = [
            f"使用 {'/'.join(selected_basis)} 作为基础进行布管。",
            f"在换热管布置过程中，如需在垂直中心线上设置拉杆时，一般设置在（垂直中心线）布管限定圆直径的{val2}处。",
            f"当奥氏体不锈钢、双相不锈钢、钛、铜、镍、锆及其合金换热管与管板采用强度胀接时，管板的管孔公称直径减小{val3} mm。",
            f"管束的重量若超过{val4}kg，在固定管板外侧设置环首螺钉用螺孔。"
        ]
        value = "\n".join(lines)

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 管板预定义用户表 WHERE user_id = %s", (user_id,))
        cursor.execute("INSERT INTO 管板预定义用户表 (user_id, value) VALUES (%s, %s)", (user_id, value))
        db_conn.commit()
        cursor.close()
        print("[保存成功] 管板配置规则已更新")

    except Exception as e:
        print(f"[错误] 保存管板配置失败: {e}")
