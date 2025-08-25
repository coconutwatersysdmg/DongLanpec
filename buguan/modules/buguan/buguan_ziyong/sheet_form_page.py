import os
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QPixmap, QFont, QIcon
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
                             QGridLayout, QFrame, QListWidget, QListWidgetItem, QLineEdit, QComboBox)
import pymysql


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
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.critical(None, "数据库错误", f"连接元件库失败: {e}")
        return None


def get_plate_form_params(image_name):
    """从管板形式表中获取参数"""
    conn = create_component_connection()
    if not conn:
        return {}

    try:
        with conn.cursor() as cursor:
            # 根据图片名称构建管板类型
            plate_type = os.path.splitext(image_name)[0]
            plate_type = f"{plate_type}型管板"  # 直接构建管板类型，不进行额外拆分

            # 查询数据库
            query = """
                SELECT 参数符号, 默认值
                FROM 管板形式表
                WHERE 管板类型 = %s
            """
            cursor.execute(query, (plate_type,))
            params = cursor.fetchall()

            # 处理查询结果
            param_dict = {}
            for param in params:
                if param['参数符号'] and param['默认值']:
                    param_dict[param['参数符号']] = param['默认值']

            return param_dict
    except pymysql.Error as e:
        print(f"数据库错误: {e}")
        return {}
    finally:
        conn.close()


class SheetFormPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent  # 保存父窗口引用
        self.sheet_form_param_layout = None
        self.sheet_form_image_labels = []
        self.sheet_form_current_images = []  # 初始化图片列表
        self.setup_ui()
        # 确保布局已初始化
        if self.sheet_form_param_layout is None:
            self._init_fallback_param_layout()

    def _init_fallback_param_layout(self):
        """创建备用布局，防止初始化失败"""
        self.sheet_form_param_frame = QFrame()
        self.sheet_form_param_layout = QVBoxLayout(self.sheet_form_param_frame)
        self.sheet_form_param_layout.addWidget(QLabel("参数区域初始化失败"))

    def setup_ui(self):
        """创建管板形式页面UI"""
        try:
            main_layout = QVBoxLayout(self)
            main_layout.setContentsMargins(20, 20, 20, 20)
            main_layout.setSpacing(20)

            # 1. 下拉框区域
            header_layout = QHBoxLayout()
            header_layout.setSpacing(15)

            # 添加下拉框标签
            combo_label = QLabel("管板与壳体、管箱的连接:")
            combo_label.setStyleSheet("font-size: 14px; font-weight: bold;")
            header_layout.addWidget(combo_label)

            # 设置下拉框样式和大小
            self.sheet_form_connection_type_combo = QComboBox()
            self.sheet_form_connection_type_combo.setFixedHeight(50)
            self.sheet_form_connection_type_combo.setStyleSheet("""
                QComboBox {
                    font-size: 14px;
                    padding: 8px;
                    min-width: 540px;
                }
                QComboBox::drop-down {
                    width: 30px;
                }
                QComboBox QAbstractItemView {
                    border: none;
                    background: white;
                    outline: none;
                }
            """)

            # 连接信号
            self.sheet_form_connection_type_combo.currentIndexChanged.connect(
                lambda index: self._safe_call(lambda: self.sheet_form_updates_image_path(index))
            )

            # 创建一个网格布局的视图
            view = QListWidget()
            view.setViewMode(QListWidget.IconMode)
            view.setIconSize(QSize(150, 150))
            view.setResizeMode(QListWidget.Adjust)
            view.setSpacing(10)
            view.setGridSize(QSize(170, 170))
            view.setSelectionMode(QListWidget.SingleSelection)

            # 设置视图的宽度策略
            view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

            # 添加图片到下拉框
            connection_type_images = ['a', 'b', 'c', 'd', 'e', 'f']
            script_dir = os.path.dirname(os.path.abspath(__file__))
            image_base_path = os.path.join(script_dir, "static", "管板与壳体、管箱的连接")

            # 为下拉框项目添加样式
            view.setStyleSheet("""
                QListWidget {
                    border: 1px solid #ccc;
                    border-radius: 4px;
                    padding: 5px;
                    background-color: white;
                }
                QListWidget::item {
                    border: 2px solid #eee;
                    border-radius: 6px;
                    padding: 5px;
                    background-color: white;
                }
                QListWidget::item:selected {
                    border: 2px solid #2196F3;
                    background-color: #e8f4fd;
                }
                QListWidget::item:hover {
                    border: 2px solid #4CAF50;
                }
            """)

            # 确保图片加载顺序正确
            for name in sorted(connection_type_images):
                image_path = os.path.join(image_base_path, f"{name}.png")
                try:
                    if not os.path.exists(image_path):
                        print(f"警告: 图片文件不存在: {image_path}")
                        continue

                    pixmap = QPixmap(image_path)
                    if not pixmap.isNull():
                        scaled_pixmap = pixmap.scaled(
                            140, 140,
                            Qt.KeepAspectRatioByExpanding,
                            Qt.SmoothTransformation
                        )
                        icon = QIcon(scaled_pixmap)
                        item = QListWidgetItem(icon, "")
                        item.setData(Qt.UserRole, name)  # 保存标识符
                        view.addItem(item)
                except Exception as e:
                    print(f"处理图片 {name}.png 时出错: {str(e)}")

            # 根据图片数量动态计算下拉框弹出窗口的大小
            num_images = len(connection_type_images)
            num_cols = 3
            num_rows = (num_images + num_cols - 1) // num_cols
            popup_width = num_cols * 170 + 20
            popup_height = num_rows * 170 + 20
            view.setFixedSize(popup_width, popup_height)

            # 设置下拉框的模型和视图
            self.sheet_form_connection_type_combo.setModel(view.model())
            self.sheet_form_connection_type_combo.setView(view)

            header_layout.addWidget(self.sheet_form_connection_type_combo)
            header_layout.addStretch()
            main_layout.addLayout(header_layout)

            # 主体内容布局，左右分栏
            body_layout = QHBoxLayout()
            body_layout.setSpacing(30)

            # 左侧图片展示区
            image_frame = QFrame()
            image_frame.setStyleSheet("background-color: #f5f5f5; border-radius: 8px;")
            image_layout = QGridLayout(image_frame)
            image_layout.setSpacing(20)
            image_layout.setContentsMargins(15, 15, 15, 15)

            # 初始化图片标签
            self.sheet_form_image_labels = []  # 确保先初始化

            # 创建图片标签
            for i in range(6):
                label = QLabel()
                label.setAlignment(Qt.AlignCenter)
                label.setMinimumSize(280, 200)
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
                label.setProperty("index", i)  # 保存索引

                # 使用lambda绑定正确的索引
                label.mousePressEvent = lambda event, idx=i: self._handle_image_click(event, idx)

                self.sheet_form_image_labels.append(label)
                image_layout.addWidget(label, i // 3, i % 3)

            body_layout.addWidget(image_frame, 2)

            # 右侧参数展示区
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_area.setStyleSheet("""
                QScrollArea {
                    border: none;
                    background-color: #f9f9f9;
                    border-radius: 8px;
                }
                QScrollBar:vertical {
                    width: 10px;
                    background: #f1f1f1;
                    margin: 0px;
                    border-radius: 5px;
                }
                QScrollBar::handle:vertical {
                    background: #c1c1c1;
                    min-height: 20px;
                    border-radius: 5px;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    height: 0px;
                }
            """)

            self.sheet_form_param_frame = QFrame()
            self.sheet_form_param_frame.setStyleSheet("""
                QFrame {
                    background-color: #f9f9f9;
                    border-radius: 8px;
                }
                QLabel {  /* 修改标签字体 */
                    font-size: 20px;  
                    margin-bottom: 8px;
                    font-weight: 500;
                }
                QLineEdit {  /* 修改输入框样式 */
                    font-size: 25px;  
                    padding: 10px;  
                    border: 1px solid #ddd;
                    border-radius: 5px;
                    margin-bottom: 12px;
                    min-height: 40px;  
                }
            """)

            # 正确初始化布局为QVBoxLayout
            self.sheet_form_param_layout = QVBoxLayout(self.sheet_form_param_frame)
            self.sheet_form_param_layout.setContentsMargins(18, 18, 18, 18)  # 增加内边距
            self.sheet_form_param_layout.setSpacing(18)  # 增加间距
            self.sheet_form_param_layout.addWidget(QLabel("请选择左侧图片查看参数"))  # 初始提示文本

            scroll_area.setWidget(self.sheet_form_param_frame)
            body_layout.addWidget(scroll_area, 1)
            main_layout.addLayout(body_layout)

            # 最后再调用更新方法
            self.sheet_form_updates_image_path(0)  # 现在可以安全调用

        except Exception as e:
            print(f"创建管板形式页面时发生致命错误: {str(e)}")
            import traceback
            traceback.print_exc()
            # 异常时确保布局有默认值
            self._init_fallback_param_layout()

    def _handle_image_click(self, event, index):
        """处理图片点击事件"""
        try:
            if index >= len(self.sheet_form_image_labels):
                return

            label = self.sheet_form_image_labels[index]

            # 重置所有图片的选中状态
            for lbl in self.sheet_form_image_labels:
                lbl.setProperty("selected", False)
                lbl.style().unpolish(lbl)
                lbl.style().polish(lbl)

            # 设置当前图片为选中状态
            label.setProperty("selected", True)
            label.style().unpolish(label)
            label.style().polish(label)

            # 获取当前选中的下拉框索引
            current_index = self.sheet_form_connection_type_combo.currentIndex()
            if current_index < 0 or index >= len(self.sheet_form_current_images):
                return

            # 获取点击的图片路径
            clicked_image_path = self.sheet_form_current_images[index]
            clicked_image = os.path.basename(clicked_image_path)

            # 清空右侧参数区域
            self._clear_param_layout()

            # 根据选择的图片显示对应的参数输入框
            params = get_plate_form_params(clicked_image)
            if params:
                # 创建参数输入框
                for param_name, default_value in params.items():
                    param_layout = QHBoxLayout()

                    # 参数名称标签
                    label = QLabel(param_name + ":")
                    label.setFixedWidth(120)  # 增加宽度防止文字被截断
                    param_layout.addWidget(label)

                    # 参数输入框
                    line_edit = QLineEdit(str(default_value))  # 确保是字符串类型
                    line_edit.setObjectName(f"param_{param_name}")
                    param_layout.addWidget(line_edit)

                    self.sheet_form_param_layout.addLayout(param_layout)

                # 点击图片后同步更新父窗口的sheet_form_param_layout
                if self.parent:
                    self.parent.sheet_form_param_layout = self.get_current_tube_form_data()
            else:
                self.sheet_form_param_layout.addWidget(QLabel("暂无参数"))
        except Exception as e:
            print(f"处理图片点击时出错: {str(e)}")
            import traceback
            traceback.print_exc()

    def _clear_param_layout(self):
        """清空参数布局，增加安全检查"""
        # 先检查布局是否存在
        if not hasattr(self, 'sheet_form_param_layout') or self.sheet_form_param_layout is None:
            return

        while self.sheet_form_param_layout.count():
            item = self.sheet_form_param_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_sub_layout(item.layout())

    def _clear_sub_layout(self, layout):
        """清空子布局"""
        while layout.count():
            sub_item = layout.takeAt(0)
            if sub_item.widget():
                sub_item.widget().deleteLater()
            elif sub_item.layout():
                self._clear_sub_layout(sub_item.layout())

    def sheet_form_updates_image_path(self, index):
        """更新左侧图片展示区的图片"""
        try:
            if index < 0:
                return

            # 获取对应的文件夹名称
            connection_type_images = ['a', 'b', 'c', 'd', 'e', 'f']
            if index >= len(connection_type_images):
                return

            selected_folder = connection_type_images[index]

            script_dir = os.path.dirname(os.path.abspath(__file__))
            image_base_path = os.path.join(script_dir, "static", "管板与壳体、管箱的连接")
            folder_path = os.path.join(image_base_path, selected_folder)

            # 检查文件夹是否存在
            if not os.path.exists(folder_path):
                for label in self.sheet_form_image_labels:
                    label.clear()
                    label.setText("无可用图片")
                return

            # 清空之前的图片和记录
            for label in self.sheet_form_image_labels:
                label.clear()
                label.setProperty("selected", False)
                label.setStyleSheet(label.styleSheet())

            self.sheet_form_current_images = []  # 清空当前图片记录

            # 获取文件夹中的所有图片文件并按名称排序
            image_extensions = ['.png', '.jpg', '.jpeg', '.bmp']
            try:
                image_files = sorted([f for f in os.listdir(folder_path)
                                      if os.path.isfile(os.path.join(folder_path, f))
                                      and os.path.splitext(f)[1].lower() in image_extensions])
            except Exception as e:
                print(f"读取图片文件时出错: {str(e)}")
                image_files = []

            # 显示文件夹中的图片
            for i, image_file in enumerate(image_files[:6]):
                if i >= len(self.sheet_form_image_labels):
                    break

                image_path = os.path.join(folder_path, image_file)
                self.sheet_form_current_images.append(image_path)  # 记录当前图片路径

                pixmap = QPixmap(image_path)
                if not pixmap.isNull():
                    # 计算合适的缩放大小
                    label_size = self.sheet_form_image_labels[i].size()
                    scaled_pixmap = pixmap.scaled(
                        label_size.width() - 10, label_size.height() - 10,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                    self.sheet_form_image_labels[i].setPixmap(scaled_pixmap)
                else:
                    self.sheet_form_image_labels[i].setText("图片加载失败")

            # 清空右侧参数区域
            self._clear_param_layout()

        except Exception as e:
            print(f"更新图片路径时出错: {str(e)}")
            import traceback
            traceback.print_exc()

    def _safe_call(self, func):
        """安全调用函数，捕获并记录异常"""
        try:
            func()
        except Exception as e:
            print(f"调用函数时出错: {str(e)}")
            import traceback
            traceback.print_exc()

    def get_current_tube_form_data(self):
        """获取当前管板形式页面的右侧参数列表，确保返回有效数据"""
        tube_form_data = []  # 初始化数据列表

        # 检查是否有选中的图片
        selected_index = next(
            (i for i, lbl in enumerate(self.sheet_form_image_labels) if lbl.property("selected")),
            None
        )

        if selected_index is None:
            print("未选择任何管板图片")
            return tube_form_data  # 返回空列表但至少保证列表存在

        # 获取当前选中的图片信息
        try:
            # 获取下拉框选中的文件夹
            combo_index = self.sheet_form_connection_type_combo.currentIndex()
            connection_type_images = ['a', 'b', 'c', 'd', 'e', 'f']
            if combo_index < 0 or combo_index >= len(connection_type_images):
                raise ValueError("无效的下拉框索引")

            selected_folder = connection_type_images[combo_index]

            # 构建图片路径
            script_dir = os.path.dirname(os.path.abspath(__file__))
            image_base_path = os.path.join(script_dir, "static", "管板与壳体、管箱的连接")
            folder_path = os.path.join(image_base_path, selected_folder)

            # 获取图片文件列表
            image_extensions = ['.png', '.jpg', '.jpeg', '.bmp']
            image_files = [f for f in os.listdir(folder_path)
                           if os.path.isfile(os.path.join(folder_path, f))
                           and os.path.splitext(f)[1].lower() in image_extensions]

            if selected_index >= len(image_files):
                raise IndexError("选中的图片索引超出范围")

            # 提取管板类型
            clicked_image = image_files[selected_index]
            plate_type = os.path.splitext(clicked_image)[0]
            plate_type = f"{plate_type}型管板"

        except Exception as e:
            print(f"获取管板类型时出错: {str(e)}")
            plate_type = "未知类型"

        # 提取参数布局中的所有参数
        if not hasattr(self, 'sheet_form_param_layout') or self.sheet_form_param_layout is None:
            print("参数布局未初始化")
            return tube_form_data

        # 遍历布局中的所有参数项
        param_count = 0  # 用于统计有效参数数量
        for i in range(self.sheet_form_param_layout.count()):
            item = self.sheet_form_param_layout.itemAt(i)

            # 检查是否是水平布局（参数名+输入框）
            if item and isinstance(item.layout(), QHBoxLayout):
                h_layout = item.layout()
                if h_layout.count() >= 2:  # 确保有足够的控件
                    # 获取参数名标签
                    label_item = h_layout.itemAt(0)
                    # 获取参数值输入框
                    input_item = h_layout.itemAt(1)

                    if label_item and input_item:
                        label_widget = label_item.widget()
                        input_widget = input_item.widget()

                        if isinstance(label_widget, QLabel) and isinstance(input_widget, QLineEdit):
                            # 提取参数名（去除末尾的冒号）
                            param_name = label_widget.text().rstrip(':').strip()
                            # 提取参数值
                            param_value = input_widget.text().strip()

                            if param_name:  # 只添加有名称的参数
                                data = {
                                    "序号": str(param_count + 1),  # 添加序号
                                    "管板类型": plate_type,
                                    "参数符号": param_name,
                                    "默认值": param_value,

                                }
                                tube_form_data.append(data)
                                param_count += 1

        return tube_form_data
