from PyQt5.QtWidgets import QWidget, QLabel, QLineEdit, QHBoxLayout, QComboBox, QTableWidget
from PyQt5.QtCore import Qt

def jieguanjiegouchicunjibenyaoqiu(table: QTableWidget, cursor, user_id, config_type=None):
    try:

        table.clearContents()
        table.setRowCount(0)
        table.setColumnCount(0)

        table.setRowCount(7)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["限制条件"])
        table.verticalHeader().setDefaultSectionSize(50)

        # 默认值
        angle, duanbuchangdu, daojiao, changdu, banjing, neibubanjing, jiegou = \
            "45", "1.5", "斜角", "0.5", "1.5", "0.25", "焊接过渡"

        # ✅ 从新表读取用户旧配置（只使用 user_id）
        cursor.execute("""
            SELECT value FROM `厚壁锻管/嵌入式接管结构尺寸基本要求预定义用户表`
            WHERE user_id = %s
        """, (user_id,))
        result = cursor.fetchone()
        if result:
            try:
                val = result[0]
                angle = val.split("半锥角为")[1].split("；")[0]
                duanbuchangdu = val.split("长度≥")[1].split("倍")[0]
                daojiao = val.split("倒角为：")[1].split("；")[0]
                changdu = val.split("长度≥")[1].split("倍")[1].split("；")[0]
                banjing = val.split("倒圆角半径≥")[1].split("倍")[0]
                neibubanjing = val.split("内部倒圆角半径≥")[1].split("倍")[0]
                jiegou = val.split("连接结构：")[1]
            except Exception as e:
                print(f"[警告] 解析旧值失败，使用默认值: {e}")

        def set_row(row_idx, prefix: str, control, suffix: str = ""):
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(QLabel(prefix))
            control.setMaximumWidth(80)
            layout.addWidget(control)
            if suffix:
                layout.addWidget(QLabel(suffix))
            layout.addStretch()
            table.setCellWidget(row_idx, 0, widget)

        # 控件设置
        angle_input = QLineEdit(angle)
        set_row(0, "变径锥段的半锥角为", angle_input, "°")

        duanbuchangdu_input = QLineEdit(duanbuchangdu)
        set_row(1, "小径端部长度≥", duanbuchangdu_input, "倍小径端部名义厚度")

        daojiao_input = QComboBox()
        daojiao_input.addItems(["斜角", "圆角"])
        daojiao_input.setCurrentText(daojiao)
        set_row(2, "接管与嵌入结构处倒角为：", daojiao_input)

        changdu_input = QLineEdit(changdu)
        set_row(3, "倒角半径或直边长度≥", changdu_input, "倍大径端部名义厚度")

        banjing_input = QLineEdit(banjing)
        set_row(4, "倒圆角半径≥", banjing_input, "倍大径端部名义厚度")

        neibubanjing_input = QLineEdit(neibubanjing)
        set_row(5, "内部倒圆角半径≥", neibubanjing_input, "倍大径端部名义厚度")

        jiegou_input = QComboBox()
        jiegou_input.addItems(["削边", "焊接过渡"])
        jiegou_input.setCurrentText(jiegou)
        set_row(6, "嵌入式接管与壳体连接结构：", jiegou_input)

        table._jieguan_inputs = {
            "angle": angle_input,
            "duanbuchangdu": duanbuchangdu_input,
            "daojiao": daojiao_input,
            "changdu": changdu_input,
            "banjing": banjing_input,
            "neibubanjing": neibubanjing_input,
            "jiegou": jiegou_input
        }

        if not hasattr(table, '_save_connected_jieguan'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_jieguan_config(table, cursor.connection, user_id)
                )
                table._save_connected_jieguan = True
            else:
                print("[错误] 找不到 save_button")

    except Exception as e:
        print(f"[错误] 加载结构尺寸配置失败: {e}")


def save_jieguan_config(table: QTableWidget, db_conn, user_id):
    try:
        inputs = table._jieguan_inputs
        value_str = (
            f"变径锥段的半锥角为{inputs['angle'].text()}；"
            f"小径端部长度≥{inputs['duanbuchangdu'].text()}倍小径端部名义厚度；"
            f"接管与嵌入结构处倒角为：{inputs['daojiao'].currentText()}；"
            f"倒角半径或直边长度≥{inputs['changdu'].text()}倍大径端部名义厚度；"
            f"倒圆角半径≥{inputs['banjing'].text()}倍大径端部名义厚度；"
            f"内部倒圆角半径≥{inputs['neibubanjing'].text()}倍大径端部名义厚度；"
            f"嵌入式接管与壳体连接结构：{inputs['jiegou'].currentText()}"
        )

        cursor = db_conn.cursor()
        cursor.execute("""
            DELETE FROM `厚壁锻管/嵌入式接管结构尺寸基本要求预定义用户表`
            WHERE user_id = %s
        """, (user_id,))
        cursor.execute("""
            INSERT INTO `厚壁锻管/嵌入式接管结构尺寸基本要求预定义用户表`
            (value, user_id) VALUES (%s, %s)
        """, (value_str, user_id))

        db_conn.commit()
        cursor.close()

        print(f"[保存成功] 接管结构尺寸配置: {value_str}")
    except Exception as e:
        print(f"[错误] 保存结构尺寸配置失败: {e}")
