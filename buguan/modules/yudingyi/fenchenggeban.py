from PyQt5.QtWidgets import (
    QWidget, QLabel, QHBoxLayout, QCheckBox, QLineEdit, QRadioButton, QButtonGroup, QTableWidget
)
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt
import sys
import os

def resource_path(relative_path):
    """获取打包后的资源路径"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)  # _MEIPASS 是 PyInstaller 解压临时目录
    return os.path.join(os.path.abspath("."), relative_path)


def fenchenggeban_config(table: QTableWidget, cursor, user_id):
    try:
        defaults = {
            "width": "3",
            "hole_diameter": "6",
            "notch_height": "10",
            "notch_type": "等腰直角三角形缺口",
        }

        cursor.execute("SELECT value FROM 分程隔板预定义用户表 WHERE user_id = %s", (user_id,))
        saved = set(row[0] for row in cursor.fetchall())

        table.clear()
        table.setRowCount(4)
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels(["分程隔板配置"])
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setStretchLastSection(True)

        table._fencheng_items = []

        def make_row(checkbox, widgets):
            w = QWidget()
            layout = QHBoxLayout(w)
            layout.setContentsMargins(10, 0, 10, 0)
            layout.addWidget(checkbox)
            for item in widgets:
                layout.addWidget(item if isinstance(item, QWidget) else QLabel(str(item)))
            layout.addStretch()
            return w

        def insert_sentence(row, template, default_values):
            cb = QCheckBox()
            edits = [QLineEdit(v) for v in default_values]
            text_segments = template.split("{}")
            widgets = []
            for i, seg in enumerate(text_segments):
                widgets.append(seg)
                if i < len(edits):
                    widgets.append(edits[i])

            # 恢复旧值
            for old in saved:
                try:
                    if template.count("{}") == 1:
                        if old.startswith(text_segments[0]) and old.endswith(text_segments[1]):
                            edits[0].setText(old[len(text_segments[0]):-len(text_segments[1])])
                            cb.setChecked(True)
                    elif template.count("{}") == 2:
                        mid_idx = old.find(text_segments[1], len(text_segments[0]))
                        if old.startswith(text_segments[0]) and text_segments[1] in old and old.endswith(text_segments[2]):
                            edits[0].setText(old[len(text_segments[0]):mid_idx])
                            edits[1].setText(old[mid_idx + len(text_segments[1]):-len(text_segments[2])])
                            cb.setChecked(True)
                except:
                    pass

            table.setCellWidget(row, 0, make_row(cb, widgets))
            table._fencheng_items.append((cb, template, edits))

        insert_sentence(0, "分程隔板宽度为圆筒内径-{}mm。", [defaults["width"]])
        insert_sentence(1, "水平布置的分程隔板通液孔为直径{}mm的圆孔。", [defaults["hole_diameter"]])
        insert_sentence(2, "竖直布置的分程隔板通液（气）口为对称布置的2个以隔板边缘（轴向）为底，高{}mm的{}。", [defaults["notch_height"], defaults["notch_type"]])

        radio_label = QLabel("分程隔板端部厚度削薄方式：")
        radio1 = QRadioButton("按GB/T 151-2014图6-14a）")
        radio2 = QRadioButton("按GB/T 151-2014图6-14b）")
        group = QButtonGroup(table)
        group.addButton(radio1)
        group.addButton(radio2)
        if any("图6-14a" in val for val in saved):
            radio1.setChecked(True)
        elif any("图6-14b" in val for val in saved):
            radio2.setChecked(True)

        image_label1 = QLabel()
        image_label1.setPixmap(QPixmap(resource_path("static/分程隔板1.png")).scaledToWidth(200, Qt.SmoothTransformation))
        image_label2 = QLabel()
        image_label2.setPixmap(QPixmap(resource_path("static/分程隔板1.png")).scaledToWidth(200, Qt.SmoothTransformation))

        row_w = QWidget()
        layout = QHBoxLayout(row_w)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.addWidget(radio_label)
        layout.addWidget(radio1)
        layout.addWidget(image_label1)
        layout.addWidget(radio2)
        layout.addWidget(image_label2)
        layout.addStretch()
        table.setCellWidget(3, 0, row_w)
        table.setRowHeight(3, 180)  # ✅ 高度可根据图片实际大小微调

        table._fencheng_items.append((group,))

        if not hasattr(table, '_save_connected_fencheng'):
            window = table.window()
            if hasattr(window, 'save_button'):
                window.save_button.clicked.connect(
                    lambda: save_fencheng_config(table, cursor.connection, user_id)
                )
                table._save_connected_fencheng = True

    except Exception as e:
        print(f"[错误] 加载分程隔板配置失败: {e}")


def save_fencheng_config(table: QTableWidget, db_conn, user_id):
    try:
        print("[调试] 分程隔板保存逻辑调用")
        cursor = db_conn.cursor()
        cursor.execute("DELETE FROM 分程隔板预定义用户表 WHERE user_id = %s", (user_id,))

        for item in table._fencheng_items:
            if isinstance(item[0], QButtonGroup):
                selected = item[0].checkedButton()
                if selected:
                    final_sentence = selected.text()
                    cursor.execute("INSERT INTO 分程隔板预定义用户表 (user_id, value) VALUES (%s, %s)", (user_id, final_sentence))
            else:
                cb, template, edits = item
                if cb.isChecked():
                    values = [edit.text().strip() for edit in edits]
                    final_sentence = template.format(*values)
                    cursor.execute("INSERT INTO 分程隔板预定义用户表 (user_id, value) VALUES (%s, %s)", (user_id, final_sentence))

        db_conn.commit()
        cursor.close()
        print("[保存成功] 分程隔板配置已更新")
    except Exception as e:
        print(f"[错误] 保存分程隔板配置失败: {e}")
