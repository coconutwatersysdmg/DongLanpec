from PyQt5.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QVBoxLayout, QCheckBox,
    QTableWidget, QMessageBox
)
from PyQt5.QtGui import QPixmap, QFont
from PyQt5.QtCore import Qt
import os
import json
def resource_path(relative_path):
    """获取打包后的资源路径"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)  # _MEIPASS 是 PyInstaller 解压临时目录
    return os.path.join(os.path.abspath("."), relative_path)
def shechengjiegou_l1_l2_l3(table: QTableWidget, cursor, user_id, config_type):
    table.clear()
    table.setColumnCount(1)
    table.setHorizontalHeaderLabels(['壳程接管定位'])
    table.setRowCount(0)

    # 显示图片
    image_path = resource_path(os.path.join("static", "壳程接管定位.png"))
    if os.path.exists(image_path):
        image_label = QLabel()
        pixmap = QPixmap(image_path).scaled(600, 400, Qt.KeepAspectRatio)
        image_label.setPixmap(pixmap)
        image_label.setAlignment(Qt.AlignLeft)
        table.insertRow(table.rowCount())
        table.setCellWidget(table.rowCount() - 1, 0, image_label)
    else:
        table.insertRow(table.rowCount())
        table.setCellWidget(table.rowCount() - 1, 0, QLabel("[未找到图片]"))

    bold_font = QFont()
    bold_font.setBold(True)

    sections = [
        ("L1按下述较大值：", ["3 x min(δn1,δn2)", "50"]),
        ("L2按下述较大值：", ["3 x δn1", "1 x √(DN×δ_n1 )", "50"]),
        ("L3按下述较大值：", ["1 x √(DN×δ_n1 )", "OD/2", "Dop/2", "Dip/2"]),
        ("其他：", [
            "对U形管换热器，当公称直径在DN>1500范围时，使U形端的壳体进(出)口安装在U形管末端/近U形管末端折流板以外，以消除U形管末端流体停滞的换热损失。"
        ])
    ]

    all_checkboxes = []

    for title, options in sections:
        # 标题
        title_label = QLabel(title)
        title_label.setFont(bold_font)
        table.insertRow(table.rowCount())
        table.setCellWidget(table.rowCount() - 1, 0, title_label)

        group_checkboxes = []
        for opt in options:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            cb = QCheckBox(opt)
            row_layout.addWidget(cb)
            table.insertRow(table.rowCount())
            table.setCellWidget(table.rowCount() - 1, 0, row_widget)
            group_checkboxes.append(cb)

        all_checkboxes.append(group_checkboxes)

    table._check_inputs_l123 = all_checkboxes
    table._l123_user_id = user_id
    table._l123_config_type = config_type

    if not hasattr(table, '_save_connected_l123'):
        window = table.window()
        if hasattr(window, 'save_button'):
            window.save_button.clicked.connect(lambda: save_shecheng_l123(table, cursor.connection))
            table._save_connected_l123 = True
    load_previous_shecheng_l123_selection(table, cursor)


def save_shecheng_l123(table, db_conn):
    try:
        user_id = table._l123_user_id
        all_groups = table._check_inputs_l123  # 应该是4个 group，分别对应 L1, L2, L3, else
        keys = ['L1', 'L2', 'L3', 'else']

        parts = []
        for key, group in zip(keys, all_groups):
            selected_texts = [cb.text() for cb in group if cb.isChecked()]
            part = f"{key}: {'|'.join(selected_texts)}"
            parts.append(part)

        value_str = "; ".join(parts)

        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 壳程接管定位预定义用户表 WHERE user_id=%s", (user_id,))
        cursor.execute("""
            INSERT INTO 壳程接管定位预定义用户表 (value, user_id)
            VALUES (%s, %s)
        """, (value_str, user_id))
        db_conn.commit()
        cursor.close()

        print(f"[保存成功] 壳程接管定位: {value_str}")
    except Exception as e:
        print(f"[错误] 保存失败: {e}")
        QMessageBox.critical(table, "保存失败", f"保存失败: {e}")
def load_previous_shecheng_l123_selection(table, cursor):
    try:
        user_id = table._l123_user_id
        cursor.execute("SELECT value FROM 壳程接管定位预定义用户表 WHERE user_id=%s", (user_id,))
        row = cursor.fetchone()
        if not row:
            return

        value_str = row[0]  # 示例：L1: 选项1|选项2; L2: xxx; ...
        key_map = {'L1': 0, 'L2': 1, 'L3': 2, 'else': 3}
        check_groups = table._check_inputs_l123

        for part in value_str.split(";"):
            if ':' not in part:
                continue
            key, val = part.strip().split(":", 1)
            idx = key_map.get(key.strip())
            if idx is None:
                continue
            selected = [v.strip() for v in val.strip().split("|") if v.strip()]
            for cb in check_groups[idx]:
                if cb.text() in selected:
                    cb.setChecked(True)

    except Exception as e:
        print(f"[错误] 加载历史选择失败: {e}")
