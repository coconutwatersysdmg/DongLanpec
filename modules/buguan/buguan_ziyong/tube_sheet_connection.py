from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QScrollArea, QFrame, QLineEdit, QComboBox, QGridLayout, QMessageBox)
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt
import pymysql
import os
from pathlib import Path  # 引入pathlib处理路径


def create_component_connection():
    """创建元件库数据库连接"""
    try:
        return pymysql.connect(
            host='localhost',
            port=3306,
            database='元件库',
            user='root',
            password='123456',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
    except pymysql.MySQLError as e:
        QMessageBox.critical(None, "数据库错误", f"连接元件库失败: {e}")
        return None


def create_product_connection():
    """创建产品设计活动库数据库连接"""
    try:
        return pymysql.connect(
            host='localhost',
            database='产品设计活动库',
            user='root',
            password='123456',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
    except pymysql.MySQLError as e:
        QMessageBox.critical(None, "数据库错误", f"连接产品设计活动库失败: {e}")
        return None


class TubeSheetConnectionPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.current_params = []  # 存储参数名和值的列表
        self.current_image_path = ""  # 当前选中的图片路径
        self.current_connection_type = ""  # 当前连接方式
        # 获取当前代码文件所在目录的绝对路径
        self.current_dir = Path(__file__).parent.resolve()
        self.setup_ui()

    def setup_ui(self):
        """创建管-板连接页面"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        # 1. 下拉框区域
        header_layout = QHBoxLayout()
        header_layout.setSpacing(15)

        combo_label = QLabel("换热管与管板连接方式:")
        combo_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        header_layout.addWidget(combo_label)

        self.connection_type_combo = QComboBox()
        self.connection_type_combo.addItems(
            ["强度焊接加贴胀管孔结构", "机械胀接管孔结构", "强度焊接的焊缝形式", "机械强度胀接加密封焊管孔结构",
             "内孔焊接头形式"])
        self.connection_type_combo.setFixedHeight(30)
        self.connection_type_combo.setStyleSheet("""
            QComboBox {
                font-size: 14px;
                padding: 5px;
                min-width: 250px;
            }
            QComboBox QAbstractItemView {
                font-size: 14px;
                min-width: 300px;
            }
        """)
        self.connection_type_combo.currentIndexChanged.connect(self.update_image_path)
        header_layout.addWidget(self.connection_type_combo)
        header_layout.addStretch()

        main_layout.addLayout(header_layout)

        # 2. 主体内容布局（左右分栏）
        body_layout = QHBoxLayout()
        body_layout.setSpacing(30)

        # 左侧图片展示区
        image_frame = QFrame()
        image_frame.setStyleSheet("background-color: #f5f5f5; border-radius: 8px;")
        image_layout = QGridLayout(image_frame)
        image_layout.setSpacing(20)
        image_layout.setContentsMargins(15, 15, 15, 15)

        self.image_labels = []
        for i in range(6):  # 2行x3列布局
            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumSize(200, 150)
            label.setStyleSheet("""
                QLabel {
                    border: 2px solid #ddd;
                    border-radius: 6px;
                    background-color: white;
                }
                QLabel:hover {
                    border: 2px solid #4CAF50;
                }
                QLabel[selected=true] {
                    border: 3px solid #2196F3;
                }
            """)
            label.setProperty("selected", False)
            label.mousePressEvent = lambda event, lbl=label: self.select_image(lbl)
            self.image_labels.append(label)
            image_layout.addWidget(label, i // 3, i % 3)

        body_layout.addWidget(image_frame, 2)

        # 右侧参数展示区
        self.param_frame = QFrame()
        self.param_frame.setStyleSheet("""
            QFrame {
                background-color: #f9f9f9;
                border-radius: 8px;
            }
            QLabel {
                font-size: 16px;
                font-weight: bold;
                margin-bottom: 5px;
            }
            QLineEdit {
                font-size: 16px;
                padding: 10px;
                border: 1px solid #ddd;
                border-radius: 4px;
                min-height: 36px;
            }
        """)
        self.param_layout = QVBoxLayout(self.param_frame)
        self.param_layout.setContentsMargins(15, 15, 15, 15)
        self.param_layout.setSpacing(15)

        param_title = QLabel("参数设置")
        param_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #333;")
        param_title.setAlignment(Qt.AlignCenter)
        self.param_layout.addWidget(param_title)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setStyleSheet("color: #ddd;")
        self.param_layout.addWidget(separator)

        # 滚动区域（用于参数较多时）
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        self.scroll_param_layout = QVBoxLayout(scroll_content)
        self.scroll_param_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_param_layout.setSpacing(15)
        scroll_area.setWidget(scroll_content)
        self.param_layout.addWidget(scroll_area)

        body_layout.addWidget(self.param_frame, 1)
        main_layout.addLayout(body_layout)

        self.update_image_path()

    def update_image_path(self):
        """根据连接方式更新图片路径（使用相对路径）"""
        self.current_connection_type = self.connection_type_combo.currentText()
        # 构建相对路径：当前代码目录 -> static -> 连接方式文件夹 -> 图片文件
        # 使用pathlib的joinpath方法自动处理跨平台路径分隔符
        path = self.current_dir.joinpath("static", self.current_connection_type)
        # 清除所有图片
        for label in self.image_labels:
            label.setPixmap(QPixmap())
            label.setVisible(False)
            label.image_path = ""

        # 加载复合管板和整体管板图片
        try:
            # 复合管板图片路径
            composite_img_path = path.joinpath("复合管板.png")
            # 检查文件是否存在
            if composite_img_path.exists():
                pixmap_1 = QPixmap(str(composite_img_path))
                self.image_labels[0].setPixmap(pixmap_1.scaled(300, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.image_labels[0].setVisible(True)
                self.image_labels[0].image_path = str(composite_img_path)
            else:
                print(f"复合管板图片不存在: {composite_img_path}")

            # 整体管板图片路径
            integral_img_path = path.joinpath("整体管板.png")
            if integral_img_path.exists():
                pixmap_2 = QPixmap(str(integral_img_path))
                self.image_labels[1].setPixmap(pixmap_2.scaled(300, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.image_labels[1].setVisible(True)
                self.image_labels[1].image_path = str(integral_img_path)
            else:
                print(f"整体管板图片不存在: {integral_img_path}")

        except Exception as e:
            print(f"加载图片时出错: {e}")

    def select_image(self, label):
        """选择图片后加载对应参数"""
        # 更新选中样式
        for lbl in self.image_labels:
            lbl.setProperty("selected", False)
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

        label.setProperty("selected", True)
        label.style().unpolish(label)
        label.style().polish(label)
        self.current_image_path = getattr(label, 'image_path', '')

        # 清空之前的参数
        for i in reversed(range(self.scroll_param_layout.count())):
            widget = self.scroll_param_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        self.current_params = []

        # 确定管板类型（复合/整体）
        connection_type = self.connection_type_combo.currentText()
        image_type = "复合管板" if label == self.image_labels[0] else "整体管板"

        # 加载参数
        param_data = self.get_parameters_by_type(connection_type, image_type)
        for param in param_data:
            param_group = QHBoxLayout()
            param_group.setSpacing(5)

            name_label = QLabel(f"{param['name']}:")
            name_label.setFixedWidth(200)

            input_edit = QLineEdit(param['value'])
            input_edit.setFixedWidth(80)
            input_edit.textChanged.connect(lambda text, name=param['name']: self.update_param_value(name, text))

            self.current_params.append((param['name'], param['value']))

            container = QWidget()
            container.setLayout(param_group)
            param_group.addWidget(name_label)
            param_group.addWidget(input_edit)
            self.scroll_param_layout.addWidget(container)

        self.scroll_param_layout.addStretch()

    def update_param_value(self, param_name, param_value):
        """更新参数值"""
        for i, (name, value) in enumerate(self.current_params):
            if name == param_name:
                self.current_params[i] = (name, param_value)
                break

    def get_connection_params(self, connection_type, image_type):
        """从数据库获取参数"""
        conn = create_component_connection()
        if not conn:
            return []

        try:
            with conn.cursor() as cursor:
                composite_cond = 1 if image_type == "复合管板" else 0
                query = """
                    SELECT 参数名, 参数值
                    FROM 管板连接表
                    WHERE 管板连接方式 = %s AND 复合管板 = %s
                """
                cursor.execute(query, (connection_type, composite_cond))
                params = cursor.fetchall()
                return [{"name": p["参数名"], "value": p["参数值"]} for p in params]
        except pymysql.Error as e:
            print(f"数据库错误: {e}")
            QMessageBox.critical(self, "数据库错误", f"查询失败: {e}")
            return []
        finally:
            conn.close()

    def get_parameters_by_type(self, connection_type, image_type):
        """获取指定类型的参数"""
        return self.get_connection_params(connection_type, image_type)

    def get_current_parameters(self):
        """新增：获取当前页面所有参数（供保存使用）"""
        # 收集基础信息（连接方式和管板类型）
        connection_type = self.connection_type_combo.currentText()
        selected_image_type = "未选择"
        for label in self.image_labels:
            if label.property("selected"):
                selected_image_type = "复合管板" if label == self.image_labels[0] else "整体管板"
                break

        # 构建参数列表（包含基础信息和详细参数）
        parameters = [
            {"参数名": "换热管与管板连接方式", "参数值": connection_type, "单位": ""},
            {"参数名": "管板类型", "参数值": selected_image_type, "单位": ""}
        ]

        # 添加详细参数
        for name, value in self.current_params:
            parameters.append({"参数名": name, "参数值": value, "单位": ""})

        return parameters