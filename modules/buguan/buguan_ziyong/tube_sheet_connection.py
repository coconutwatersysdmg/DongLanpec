from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QScrollArea, QFrame, QLineEdit, QComboBox, QGridLayout, QMessageBox)
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt
import pymysql
import os
from pathlib import Path


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
        self.current_params = []
        self.current_image_path = ""
        self.current_connection_type = ""
        self.current_dir = Path(__file__).parent.resolve()
        self.setup_ui()

    def get_product_id(self):
        try:
            if hasattr(self.parent, 'productID'):
                product_id = self.parent.productID
                if product_id:
                    return product_id
                else:
                    return None
            else:
                # QMessageBox.warning(self, "警告", "父窗口中未定义 productID 属性")
                return None
        except Exception as e:
            # QMessageBox.critical(self, "错误", f"获取 productID 时发生错误: {str(e)}")
            return None

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

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.scroll_content = QWidget()
        self.scroll_param_layout = QVBoxLayout(self.scroll_content)
        self.scroll_param_layout.setContentsMargins(10, 10, 10, 10)
        self.scroll_param_layout.setSpacing(20)

        self.scroll_area.setWidget(self.scroll_content)
        self.param_layout.addWidget(self.scroll_area)

        body_layout.addWidget(self.param_frame, 1)
        main_layout.addLayout(body_layout)

        self.update_image_path()

    def update_image_path(self):
        self.current_connection_type = self.connection_type_combo.currentText()

        target_folder = self.current_dir.joinpath("static", self.current_connection_type)

        # 2. 初始化：清除所有图片标签的内容和可见性
        for label in self.image_labels:
            label.setPixmap(QPixmap())
            label.setVisible(False)
            label.image_path = ""
            label.tube_sheet_type = ""  # 清空管板类型

        if not target_folder.exists() or not target_folder.is_dir():
            print(f"目标图片文件夹不存在：{target_folder}")
            return

        # 3. 获取文件夹中的所有PNG图片文件
        png_images = []
        for file in target_folder.iterdir():
            if file.is_file() and file.suffix.lower() == ".png":
                png_images.append(file)

        # 4. 为每个图片文件推断管板类型
        for idx, img_file in enumerate(png_images[:6]):  # 最多显示6张图片
            try:
                # 从文件名推断管板类型
                tube_sheet_type = self.infer_tube_sheet_type(img_file.stem)

                # 读取图片并按比例缩放
                pixmap = QPixmap(str(img_file))
                scaled_pixmap = pixmap.scaled(
                    300, 200,  # 图片显示尺寸
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                # 给对应的标签设置图片、路径和管板类型
                target_label = self.image_labels[idx]
                target_label.setPixmap(scaled_pixmap)
                target_label.setVisible(True)
                target_label.image_path = str(img_file)
                target_label.tube_sheet_type = tube_sheet_type

                # 设置标签的提示文本
                type_mapping = {
                    '0': '复合管板',
                    '1': '整体管板',
                    'a': 'a类型',
                    'b': 'b类型',
                    'c': 'c类型',
                    'd': 'd类型'
                }
                display_name = type_mapping.get(tube_sheet_type, tube_sheet_type)
                target_label.setToolTip(f"管板类型: {display_name}")

                print(f"成功加载图片：{img_file.name} (推断管板类型: {tube_sheet_type})")

            except Exception as e:
                print(f"加载图片 {img_file.name} 失败：{e}")

    def infer_tube_sheet_type(self, filename):
        """从文件名推断管板类型"""
        filename_lower = filename.lower()

        # 根据文件名中的关键词推断管板类型
        if '复合' in filename_lower or '0' in filename_lower:
            return '0'
        elif '整体' in filename_lower or '1' in filename_lower:
            return '1'
        elif 'a' in filename_lower:
            return 'a'
        elif 'b' in filename_lower:
            return 'b'
        elif 'c' in filename_lower:
            return 'c'
        elif 'd' in filename_lower:
            return 'd'
        else:
            # 如果无法推断，返回文件名作为类型
            return filename

    def select_image(self, label):
        """选择图片后加载对应参数"""
        if not label.isVisible() or not hasattr(label, 'tube_sheet_type'):
            return

        # 更新选中样式
        for lbl in self.image_labels:
            lbl.setProperty("selected", False)
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

        label.setProperty("selected", True)
        label.style().unpolish(label)
        label.style().polish(label)
        self.current_image_path = getattr(label, 'image_path', '')
        selected_tube_sheet_type = getattr(label, 'tube_sheet_type', '')

        # 清空之前的参数
        self.clear_parameters()

        # 加载参数
        param_data = self.get_parameters_by_type(self.current_connection_type, selected_tube_sheet_type)
        for param in param_data:
            param_group = QHBoxLayout()
            param_group.setSpacing(15)
            param_group.setContentsMargins(0, 0, 0, 0)

            name_label = QLabel(f"{param['name']}:")
            name_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #333;")
            name_label.setFixedWidth(220)  # 增加宽度适应更大的字体
            name_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

            input_edit = QLineEdit(param['value'])
            input_edit.setStyleSheet("""
                QLineEdit {
                    font-size: 16px;
                    padding: 8px 12px;
                    border: 2px solid #ccc;
                    border-radius: 6px;
                    background-color: white;
                    min-height: 40px;
                }
                QLineEdit:focus {
                    border: 2px solid #2196F3;
                }
            """)
            input_edit.setFixedWidth(120)
            input_edit.setFixedHeight(40)
            input_edit.textChanged.connect(lambda text, name=param['name']: self.update_param_value(name, text))

            self.current_params.append((param['name'], param['value']))

            container = QWidget()
            container.setFixedHeight(50)  # 固定高度确保对齐
            container.setLayout(param_group)
            param_group.addWidget(name_label)
            param_group.addWidget(input_edit)
            param_group.addStretch()  # 在右侧添加弹性空间

            self.scroll_param_layout.addWidget(container)

        # 确保滚动区域回到顶部
        self.scroll_area.verticalScrollBar().setValue(0)

    def clear_parameters(self):
        """清空参数区域"""
        # 移除所有参数控件
        for i in reversed(range(self.scroll_param_layout.count())):
            widget = self.scroll_param_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        self.current_params = []

    def update_param_value(self, param_name, param_value):
        """更新参数值"""
        for i, (name, value) in enumerate(self.current_params):
            if name == param_name:
                self.current_params[i] = (name, param_value)
                break

    def get_connection_params(self, connection_type, tube_sheet_type):
        product_id = self.get_product_id()

        if product_id:
            product_conn = create_product_connection()
            if product_conn:
                try:
                    with product_conn.cursor() as cursor:
                        query = """
                            SELECT 参数名, 参数值
                            FROM 产品设计活动表_管板连接表
                            WHERE 产品ID = %s AND 管板连接方式 = %s AND 管板类型 = %s
                        """
                        cursor.execute(query, (product_id, connection_type, tube_sheet_type))
                        params = cursor.fetchall()
                        if params:
                            return [{"name": p["参数名"], "value": p["参数值"]} for p in params]
                except pymysql.Error as e:
                    print(f"产品设计活动库查询错误: {e}")
                    QMessageBox.warning(self, "数据库警告", f"产品设计活动库查询失败: {e}\n将尝试从元件库查询")
                finally:
                    product_conn.close()

        component_conn = create_component_connection()
        if not component_conn:
            return []

        try:
            with component_conn.cursor() as cursor:
                query = """
                    SELECT 参数名, 参数值
                    FROM 管板连接表
                    WHERE 管板连接方式 = %s AND 管板类型 = %s
                """
                cursor.execute(query, (connection_type, tube_sheet_type))
                params = cursor.fetchall()
                return [{"name": p["参数名"], "value": p["参数值"]} for p in params]
        except pymysql.Error as e:
            print(f"元件库数据库错误: {e}")
            QMessageBox.critical(self, "数据库错误", f"查询失败: {e}")
            return []
        finally:
            component_conn.close()

    def get_parameters_by_type(self, connection_type, tube_sheet_type):
        """获取指定类型的参数"""
        return self.get_connection_params(connection_type, tube_sheet_type)

    def get_current_parameters(self):
        """获取当前页面所有参数（供保存使用）"""
        # 收集基础信息（连接方式和管板类型）
        connection_type = self.connection_type_combo.currentText()
        selected_tube_sheet_type = ""
        selected_tube_sheet_name = "未选择"

        for label in self.image_labels:
            if label.property("selected") and hasattr(label, 'tube_sheet_type'):
                selected_tube_sheet_type = label.tube_sheet_type
                type_mapping = {
                    '0': '复合管板',
                    '1': '整体管板',
                    'a': 'a类型',
                    'b': 'b类型',
                    'c': 'c类型',
                    'd': 'd类型'
                }
                selected_tube_sheet_name = type_mapping.get(selected_tube_sheet_type, selected_tube_sheet_type)
                break

        # 构建参数列表（包含基础信息和详细参数）
        parameters = [
            {"参数名": "换热管与管板连接方式", "参数值": connection_type, "单位": ""},
            {"参数名": "管板类型", "参数值": selected_tube_sheet_name, "单位": ""}
        ]

        # 添加详细参数
        for name, value in self.current_params:
            parameters.append({"参数名": name, "参数值": value, "单位": ""})

        return parameters