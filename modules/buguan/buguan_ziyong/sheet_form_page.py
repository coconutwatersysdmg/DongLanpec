#'''
#10/23/2 修改，图片展示正常，一切功能正常。
#选择NEN时可以自动展示b类图片，且图片显示正常；b、e、f类图片文字添加正常，均在左上角，且适应界面变化
import os
import traceback
# 导入 QTimer
from PyQt5.QtCore import Qt, QSize, QTimer, QRect
from PyQt5.QtGui import QPixmap, QFont, QIcon, QPainter, QColor
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
                             QGridLayout, QFrame, QListWidget, QListWidgetItem, QLineEdit, QComboBox, QSizePolicy,
                             QTableWidget, QTableWidgetItem, QHeaderView, QDialog, QApplication)
import pymysql

class ImagePreviewDialog(QDialog):
    """显示可缩放大图的弹窗，支持 Ctrl+滚轮缩放"""

    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("图片预览")
        self.resize(800, 600)

        self._scale_factor = 1.0
        self._original_pixmap = QPixmap(image_path)

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignCenter)

        if not self._original_pixmap.isNull():
            self._label.setPixmap(self._original_pixmap)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self._label)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll_area)

    def wheelEvent(self, event):
        # 按住 Ctrl 时，使用滚轮缩放图片；否则交给默认滚动处理
        if QApplication.keyboardModifiers() & Qt.ControlModifier and not self._original_pixmap.isNull():
            delta = event.angleDelta().y()
            if delta > 0:
                self._scale_factor *= 1.1
            elif delta < 0:
                self._scale_factor /= 1.1

            # 限制缩放范围
            self._scale_factor = max(0.1, min(self._scale_factor, 10.0))

            scaled = self._original_pixmap.scaled(
                self._original_pixmap.size() * self._scale_factor,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self._label.setPixmap(scaled)
        else:
            super().wheelEvent(event)



class NoWheelTableWidget(QTableWidget):
    """自定义表格，禁用滚轮事件"""
    def __init__(self, parent=None):
        super().__init__(parent)

    def wheelEvent(self, event):
        pos = event.pos()
        row = self.rowAt(pos.y())
        column = self.columnAt(pos.x())

        if 0 <= row < self.rowCount() and 0 <= column < self.columnCount():
            cell_widget = self.cellWidget(row, column)
            if cell_widget:
                return

        super().wheelEvent(event)


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
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.critical(None, "数据库错误", f"连接产品设计活动库失败: {e}")
        return None


def get_plate_form_params(image_name, product_id=None):
    """从管板形式表中获取参数，仿照tube_sheet_connection.py的多级查询逻辑"""
    # 根据图片名称构建管板类型
    plate_type = os.path.splitext(image_name)[0]
    plate_type = f"{plate_type}"  # 直接构建管板类型，不进行额外拆分
    
    print(f"🔍 [调试] 查询管板形式参数，管板类型: '{plate_type}', 产品ID: '{product_id}'")
    
    # 步骤1：优先从产品设计活动库读取（如果有product_id）
    if product_id:
        prod_conn = create_product_connection()
        if prod_conn:
            try:
                with prod_conn.cursor() as cursor:
                    query = """
                        SELECT 参数符号, 默认值
                        FROM 产品设计活动表_管板形式表
                        WHERE 产品ID = %s AND 管板类型 = %s
                    """
                    cursor.execute(query, (product_id, plate_type))
                    params = cursor.fetchall()
                    
                    if params:
                        print(f"✅ [调试] 从产品设计活动库找到 {len(params)} 个参数")
                        # 处理查询结果 - 去重处理
                        param_dict = {}
                        seen_params = set()  # 用于去重
                        
                        for param in params:
                            param_symbol = param['参数符号']
                            param_value = param['默认值']
                            
                            # 只检查参数符号不为空，默认值可以为空字符串
                            if param_symbol and param_symbol not in seen_params:
                                seen_params.add(param_symbol)
                                param_dict[param_symbol] = str(param_value) if param_value is not None else ""
                                # print(f"✅ [调试] 添加参数: '{param_symbol}' = '{param_dict[param_symbol]}'")
                            elif param_symbol in seen_params:
                                print(f"🔄 [调试] 跳过重复参数: '{param_symbol}' = '{param_value}'")
                            else:
                                print(f"❌ [调试] 跳过空参数符号")
                        
                        # print(f"🔍 [调试] 最终参数字典包含 {len(param_dict)} 个参数")
                        return param_dict
                    else:
                        print(f"🔍 [调试] 产品设计活动库中没有找到参数，将查询元件库")
            except pymysql.Error as e:
                print(f"❌ [调试] 产品设计活动库查询错误: {e}")
            finally:
                prod_conn.close()
    
    # 步骤2：如果产品库没有，从元件库读取
    comp_conn = create_component_connection()
    if not comp_conn:
        print(f"❌ [调试] 无法连接元件库")
        return {}
    
    try:
        with comp_conn.cursor() as cursor:
            query = """
                SELECT 参数符号, 默认值
                FROM 管板形式表
                WHERE 管板类型 = %s
            """
            cursor.execute(query, (plate_type,))
            params = cursor.fetchall()
            
            print(f"🔍 [调试] 从元件库找到 {len(params)} 个参数")
            
            # 处理查询结果
            param_dict = {}
            for param in params:
                param_symbol = param['参数符号']
                param_value = param['默认值']
                print(f"🔍 [调试] 处理参数: '{param_symbol}' = '{param_value}' (类型: {type(param_value)})")
                
                # 只检查参数符号不为空，默认值可以为空字符串
                if param_symbol:
                    param_dict[param_symbol] = str(param_value) if param_value is not None else ""
                    print(f"✅ [调试] 添加参数: '{param_symbol}' = '{param_dict[param_symbol]}'")
                else:
                    print(f"❌ [调试] 跳过空参数符号")
            
            print(f"🔍 [调试] 最终参数字典包含 {len(param_dict)} 个参数")
            return param_dict
    except pymysql.Error as e:
        print(f"❌ [调试] 元件库查询错误: {e}")
        return {}
    finally:
        comp_conn.close()


# -----------------------------------------------------------------
# ✅ 解决方案：自定义 ImageLabel 类
# -----------------------------------------------------------------
class ImageLabel(QLabel):
    """
    一个自定义 QLabel, 它总是将图像居中显示，并将指定文本绘制在左上角。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._overlay_text = ""
        # 默认字体和颜色
        self._text_font = QFont("Arial", 12, QFont.Bold)
        self._text_color = QColor(0, 60, 200)

    def setPixmap(self, pixmap):
        """存储原始 pixmap 并触发重绘"""
        self._pixmap = pixmap
        self.update()  # 请求重绘

    def setText(self, text):
        """存储文本并触发重绘"""
        self._overlay_text = text
        self.update() # 请求重绘

    def clear(self):
        """清除 pixmap 和文本"""
        super().clear()
        self._pixmap = QPixmap()
        self._overlay_text = ""
        self.update()

    # def paintEvent(self, event):
    #     """
    #     重写绘制事件，在调整大小时自动重新计算布局。
    #     """
    #     # 1. 首先调用父类的 paintEvent 来绘制边框、背景等 (来自Stylesheet)
    #     super().paintEvent(event)
        
    #     # 如果没有 pixmap，则不执行任何操作
    #     if self._pixmap.isNull():
    #         return

    #     painter = QPainter(self)
    #     painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)

    #     # 2. 绘制居中的图像
    #     # 获取 QLabel 的当前矩形区域
    #     label_rect = self.rect()
        
    #     # 缩放图像以适应 QLabel (减去边距)，保持宽高比
    #     scaled_pixmap = self._pixmap.scaled(
    #         label_rect.size() - QSize(10, 10), # 留出 5px 边距
    #         Qt.KeepAspectRatio,
    #         Qt.SmoothTransformation
    #     )

    #     # 计算居中绘制的坐标 (x, y)
    #     img_x = (label_rect.width() - scaled_pixmap.width()) // 2
    #     img_y = (label_rect.height() - scaled_pixmap.height()) // 2

    #     # 绘制图像
    #     painter.drawPixmap(img_x, img_y, scaled_pixmap)

    #     # 3. 绘制左上角的文本
    #     if self._overlay_text:
    #         painter.setFont(self._text_font)
    #         painter.setPen(self._text_color)
            
    #         fm = painter.fontMetrics()
            
    #         # 真正锚定在 (2, 2)
    #         margin_x = 2
    #         text_y = 2 + fm.ascent() # Y 坐标是基于字体的基线
            
    #         painter.drawText(margin_x, text_y, self._overlay_text)

    #     painter.end()
    def paintEvent(self, event):
        """
        重写绘制事件：图片居中、多行文字绘制，支持缩进(\t)。
        """
        super().paintEvent(event)

        if self._pixmap.isNull():
            return

        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)

        # ========== 1. 绘制居中图像 ==========
        label_rect = self.rect()
        scaled_pixmap = self._pixmap.scaled(
            label_rect.size() - QSize(10, 10),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        img_x = (label_rect.width() - scaled_pixmap.width()) // 2
        img_y = (label_rect.height() - scaled_pixmap.height()) // 2
        painter.drawPixmap(img_x, img_y, scaled_pixmap)

        # ========== 2. 绘制左上角文本（支持 \n + \t 缩进） ==========
        if self._overlay_text:
            painter.setFont(self._text_font)
            painter.setPen(self._text_color)

            margin_x = 8   # 左边距
            margin_y = 6    # 上边距
            line_spacing = painter.fontMetrics().lineSpacing()
            tab_width = 32  # 每个 \t 缩进宽度（像素）

            # 手动逐行绘制（因为 Qt 不处理 \t 缩进）
            lines = self._overlay_text.split("\n")
            y = margin_y

            for line in lines:
                # 计算制表符数量并移除它们
                tabs = line.count("\t")
                text = line.replace("\t", "")

                # 根据制表符数量偏移起点
                x_offset = margin_x + tabs * tab_width
                painter.drawText(x_offset, y + painter.fontMetrics().ascent(), text)

                # 下一行
                y += line_spacing

        painter.end()

# -----------------------------------------------------------------


class SheetFormPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent  # 保存父窗口引用
        # 标记图片下拉框是否已在初始时自动弹出
        self._sheet_form_combo_popup_done = False
        self.sheet_form_param_layout = None
        self.sheet_form_image_labels = []
        self.sheet_form_current_images = []  # 初始化图片列表
        self.DN = None  # 初始化全局变量：公称直径 DN
        self.Di = None  # 初始化全局变量：壳体内直径 Dis
        self.use_outer_diameter_base = None  # "是否以外径为基准"的当前值
        self.DL = None  # 布管限定圆 DL
        self.setup_ui()
        # 确保布局已初始化
        if self.sheet_form_param_layout is None:
            self._init_fallback_param_layout()

    def showEvent(self, event):
        """仅在页面第一次真正显示时，让图片下拉框处于弹出状态。"""
        super().showEvent(event)
        try:
            if (not self._sheet_form_combo_popup_done
                    and hasattr(self, 'sheet_form_connection_type_combo')
                    and self.sheet_form_connection_type_combo is not None):
                self.sheet_form_connection_type_combo.showPopup()
                self._sheet_form_combo_popup_done = True
        except Exception:
            pass

    def _get_saved_plate_type(self):
        """从产品设计活动表_管板形式表中，根据产品ID查询已保存的管板类型"""
        product_id = self.get_product_id()
        if not product_id:
            return None

        conn = create_product_connection()
        if not conn:
            return None

        try:
            with conn.cursor() as cursor:
                sql = """
                    SELECT 管板类型
                    FROM 产品设计活动表_管板形式表
                    WHERE 产品ID = %s
                    LIMIT 1
                """
                print(f"[sheet_form_page] 自动选择已保存管板形式 - SQL: {sql}")
                cursor.execute(sql, (product_id,))
                row = cursor.fetchone()
                if not row:
                    print("[sheet_form_page] 自动选择已保存管板形式 - 未找到该产品ID的记录")
                    return None

                raw_type = row.get("管板类型") if isinstance(row, dict) else row[0]
                plate_type = str(raw_type).strip() if raw_type is not None else ""

                # 规范化管板类型：去掉“型管板”等后缀，只保留前缀字母
                if plate_type:
                    plate_type = plate_type.replace("型管板", "").strip()
                    if plate_type:
                        plate_type = plate_type[0].lower()

                print(f"[sheet_form_page] 自动选择已保存管板形式 - 原始类型: {raw_type}, 规范化后: {plate_type}")
                return plate_type or None
        except Exception as e:
            print(f"[sheet_form_page] 自动选择已保存管板形式时发生错误: {e}")
            traceback.print_exc()
            return None
        finally:
            conn.close()

    def _get_saved_plate_node(self):
        """从产品设计活动表_管板形式表中，根据产品ID查询已保存的具体节点名。

        这里直接使用 "管板类型" 原始值作为节点名（去掉"型管板"等后缀），
        以便与图片文件名（如 b_h.png → b_h）一一对应。
        """
        product_id = self.get_product_id()
        if not product_id:
            return None

        conn = create_product_connection()
        if not conn:
            return None

        try:
            with conn.cursor() as cursor:
                sql = """
                    SELECT 管板类型
                    FROM 产品设计活动表_管板形式表
                    WHERE 产品ID = %s
                    LIMIT 1
                """
                print(f"[sheet_form_page] 自动选择已保存管板节点 - SQL: {sql}")
                cursor.execute(sql, (product_id,))
                row = cursor.fetchone()
                if not row:
                    print("[sheet_form_page] 自动选择已保存管板节点 - 未找到该产品ID的记录")
                    return None

                raw_type = row.get("管板类型") if isinstance(row, dict) else row[0]
                node_name = str(raw_type).strip() if raw_type is not None else ""

                # 去掉可能的中文后缀（如 "型管板"），保留完整节点名（如 b_h）
                if node_name:
                    node_name = node_name.replace("型管板", "").strip()

                print(f"[sheet_form_page] 自动选择已保存管板节点 - 原始类型: {raw_type}, 节点名: {node_name}")
                return node_name or None
        except Exception as e:
            print(f"[sheet_form_page] 自动选择已保存管板节点时发生错误: {e}")
            traceback.print_exc()
            return None
        finally:
            conn.close()

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

            # 关键修改：简化样式，专注于尺寸控制
            self.sheet_form_connection_type_combo.setStyleSheet("""
                QComboBox {
                    font-size: 14px;
                    padding: 8px;
                    min-width: 540px;
                    border: 1px solid #ddd;
                    border-radius: 4px;
                    background-color: white;
                }
                QComboBox::drop-down {
                    width: 30px;
                    border: none;
                }
                QComboBox QAbstractItemView {
                    border: 1px solid #ddd;
                    background: white;
                    outline: none;
                    padding: 0px;
                    margin: 0px;
                }
            """)

            # 连接信号
            self.sheet_form_connection_type_combo.currentIndexChanged.connect(
                lambda index: self._safe_call(lambda: self.sheet_form_updates_image_path(index))
            )

            # 创建列表视图 - 简化版本
            view = QListWidget()
            view.setViewMode(QListWidget.IconMode)
            view.setIconSize(QSize(140, 140))
            view.setResizeMode(QListWidget.Adjust)
            view.setSpacing(2)
            view.setGridSize(QSize(150, 150))
            view.setSelectionMode(QListWidget.SingleSelection)

            # 禁用滚动条
            view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

            # 设置固定尺寸策略
            view.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

            # 关键修改：简化样式，只关注必要的属性
            view.setStyleSheet("""
                QListWidget {
                    border: 1px solid #e0e0e0;
                    background: white;
                    padding: 0px;
                    margin: 0px;
                    outline: none;
                }
                QListWidget::item {
                    border: 1px solid #e0e0e0;
                    border-radius: 4px;
                    padding: 0px;
                    margin: 0px;
                    background: white;
                }
                QListWidget::item:selected {
                    border: 2px solid #2196F3;
                    background-color: #e8f4fd;
                }
                QListWidget::item:hover {
                    border: 2px solid #4CAF50;
                }
            """)

            # 加载图片
            connection_type_images = ['a', 'b', 'c', 'd', 'e', 'f']
            script_dir = os.path.dirname(os.path.abspath(__file__))
            image_base_path = os.path.join(script_dir, "static", "管板与壳体、管箱的连接")

            for name in sorted(connection_type_images):
                image_path = os.path.join(image_base_path, f"{name}.png")
                try:
                    if not os.path.exists(image_path):
                        print(f"警告: 图片文件不存在: {image_path}")
                        continue

                    pixmap = QPixmap(image_path)
                    if not pixmap.isNull():
                        # 简单缩放图片
                        scaled_pixmap = pixmap.scaled(
                            140, 140,
                            Qt.KeepAspectRatio,
                            Qt.SmoothTransformation
                        )

                        icon = QIcon(scaled_pixmap)
                        item = QListWidgetItem(icon, "")
                        item.setData(Qt.UserRole, name)
                        # 设置项目尺寸
                        item.setSizeHint(QSize(150, 150))
                        view.addItem(item)
                except Exception as e:
                    print(f"处理图片 {name}.png 时出错: {str(e)}")

            # 关键修改：精确计算尺寸（3列×2行）
            # 网格尺寸：150px × 150px
            # 间距：2px
            # 计算：3列 × 150px + 2个间距 × 2px = 450 + 4 = 454px
            # 2行 × 150px + 1个间距 × 2px = 300 + 2 = 302px
            exact_width = 454
            exact_height = 302

            # 设置固定尺寸
            view.setFixedSize(exact_width, exact_height)

            # 设置下拉框的模型和视图
            self.sheet_form_connection_type_combo.setModel(view.model())
            self.sheet_form_connection_type_combo.setView(view)

            # 设置最大可见项目数
            self.sheet_form_connection_type_combo.setMaxVisibleItems(6)
            popup = self.sheet_form_connection_type_combo.view().window()
            popup.setFixedSize(view.size())
            popup.setStyleSheet("background:white; border:1px solid #ccc; border-radius:6px;")

            header_layout.addWidget(self.sheet_form_connection_type_combo)
            header_layout.addStretch()
            main_layout.addLayout(header_layout)

            # 主体内容布局
            body_layout = QHBoxLayout()
            body_layout.setSpacing(30)

            # 左侧图片展示区
            image_frame = QFrame()
            image_frame.setStyleSheet("background-color: #f5f5f5; border-radius: 8px;")
            self.image_layout = QGridLayout(image_frame)
            self.image_layout.setSpacing(20)
            self.image_layout.setContentsMargins(15, 15, 15, 15)

            # 初始化图片标签
            self.sheet_form_image_labels = []

            # 创建图片标签 - 恢复原来的6个
            for i in range(6):
                # ✅ 解决方案：使用我们自定义的 ImageLabel
                label = ImageLabel() 
                
                # 关键：设置最小尺寸，这是我们缩放的依据，增加高度以匹配右侧参数区
                label.setMinimumSize(280, 250)
                label.setStyleSheet("""
                    ImageLabel {
                        border: 2px solid #ddd;
                        border-radius: 6px;
                        background-color: white;
                    }
                    ImageLabel:hover {
                        border: 2px solid #4CAF50;
                    }
                    ImageLabel[selected=true] {
                        border: 3px solid #2196F3;
                    }
                    ImageLabel[selected=true][special_b_b=true] {
                        border: 3px solid #888888;
                    }
                """)
                label.setProperty("selected", False)
                label.setProperty("special_b_b", False)
                label.setProperty("index", i)

                # 使用lambda绑定正确的索引
                label.mousePressEvent = lambda event, idx=i: self._handle_image_click(event, idx)
                label.mouseDoubleClickEvent = lambda event, idx=i: self._handle_image_double_click(event, idx)

                self.sheet_form_image_labels.append(label)
                self.image_layout.addWidget(label, i // 3, i % 3)

            # 将图片容器添加到滚动区域
            self.image_scroll_area = QScrollArea()
            self.image_scroll_area.setWidgetResizable(True)
            self.image_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.image_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.image_scroll_area.setStyleSheet("background-color: #f5f5f5; border-radius: 8px;")
            self.image_scroll_area.setWidget(image_frame)
            body_layout.addWidget(self.image_scroll_area, 2)

            # 右侧参数展示区 - 完全照搬tube_sheet_connection.py的样式
            self.sheet_form_param_frame = QFrame()
            self.sheet_form_param_frame.setStyleSheet("""
                QFrame {
                    background-color: #f9f9f9;
                    border-radius: 8px;
                }
            """)
            self.sheet_form_param_layout = QVBoxLayout(self.sheet_form_param_frame)
            self.sheet_form_param_layout.setContentsMargins(15, 15, 15, 15)
            self.sheet_form_param_layout.setSpacing(15)

            # 创建参数表格 - 完全照搬tube_sheet_connection.py的样式
            self.sheet_form_param_table = NoWheelTableWidget()
            self.sheet_form_param_table.setColumnCount(2)
            # 注释掉表头
            self.sheet_form_param_table.verticalHeader().setVisible(False)
            self.sheet_form_param_table.horizontalHeader().setVisible(False)  # 隐藏水平表头
            
            # 设置列宽自适应策略 - 照搬tube_sheet_connection.py
            self.sheet_form_param_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
            self.sheet_form_param_table.horizontalHeader().setDefaultSectionSize(100)
            self.sheet_form_param_table.horizontalHeader().setMinimumSectionSize(10)
            
            # 为各列设置不同的调整策略 - 照搬tube_sheet_connection.py
            # 参数名列：可拉伸，占据较多空间
            self.sheet_form_param_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            # 参数值列：交互式调整
            self.sheet_form_param_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
            
            # 设置初始列宽比例 - 照搬tube_sheet_connection.py
            def set_initial_column_widths():
                total_width = self.sheet_form_param_table.viewport().width()
                if total_width > 0:
                    # 设置合理的初始比例：参数名60%，参数值40%
                    self.sheet_form_param_table.setColumnWidth(0, int(total_width * 0.6))  # 参数名
                    self.sheet_form_param_table.setColumnWidth(1, int(total_width * 0.4))  # 参数值
            
            # 在表格显示后设置初始列宽
            self.sheet_form_param_table.showEvent = lambda event: set_initial_column_widths()
            
            self.sheet_form_param_layout.addWidget(self.sheet_form_param_table)
            body_layout.addWidget(self.sheet_form_param_frame, 1)
            main_layout.addLayout(body_layout)

            #
            # 延迟检查父窗口的 heat_exchanger 值
            # 延迟检查父窗口的 heat_exchanger 值，并优先使用已保存的管板类型
            def _delayed_check_heat_exchanger():
                try:
                    # 进入管板形式页面时，先从布管界面刷新一次关键参数
                    try:
                        self.get_DN_and_Di_from_parent()
                    except Exception:
                        pass

                    # 1. 优先从产品设计活动表_管板形式表中获取已保存的管板类型
                    saved_plate_type = self._get_saved_plate_type()
                    print(f"[DEBUG 延迟检查] 已保存的管板类型: {saved_plate_type}")

                    # 下拉框对应的类型编码
                    connection_type_images = ['a', 'b', 'c', 'd', 'e', 'f']
                    target_index = None

                    if saved_plate_type and saved_plate_type in connection_type_images:
                        # 有已保存的管板类型，按已保存的来
                        target_index = connection_type_images.index(saved_plate_type)
                        print(f"[DEBUG 延迟检查] 使用已保存管板类型，索引 = {target_index}")
                    else:
                        # 2. 没有保存记录，回退到原来的 heat_exchanger 逻辑
                        parent_value = getattr(self.parent, "heat_exchanger", None)
                        print(f"[DEBUG 延迟检查] 从父窗口获取 heat_exchanger = {parent_value}")

                        if parent_value in ["BEM","AEM"]:
                            target_index = 4  # 'e'
                        elif parent_value in ["NEN"]:
                            target_index = 1  # 'b'
                        else:
                            target_index = 0  # 'a'

                    if target_index is None:
                        return

                    # 3. 设置下拉框索引并加载该类型图片
                    self.sheet_form_connection_type_combo.blockSignals(True)
                    self.sheet_form_connection_type_combo.setCurrentIndex(target_index)
                    self.sheet_form_connection_type_combo.blockSignals(False)
                    self.sheet_form_updates_image_path(target_index)

                    # 4. 如果当前有图片，优先根据已保存节点模拟点击，自动加载参数
                    if self.sheet_form_current_images and len(self.sheet_form_image_labels) > 0:
                        target_node = self._get_saved_plate_node()
                        print(f"[DEBUG 延迟检查] 已保存的管板节点: {target_node}")

                        click_index = 0
                        if target_node:
                            for idx, img_path in enumerate(self.sheet_form_current_images):
                                base = os.path.splitext(os.path.basename(str(img_path)))[0]
                                if base == target_node:
                                    click_index = idx
                                    break

                        # 等价于用户单击对应图，加载参数表
                        self._handle_image_click(None, click_index)

                except Exception as e:
                    print(f"[DEBUG 延迟检查] 发生异常: {e}")
                    traceback.print_exc()
            # 延迟 100 毫秒执行
            QTimer.singleShot(100, _delayed_check_heat_exchanger)
            #

        except Exception as e:
            print(f"创建管板形式页面时发生致命错误: {str(e)}")
            traceback.print_exc()
            # 异常时确保布局有默认值
            self._init_fallback_param_layout()

    def get_product_id(self):
        # 方法内容保持不变
        try:
            if hasattr(self.parent, 'productID'):
                product_id = self.parent.productID
                heat_exchanger = self.parent.heat_exchanger
                print(f"[sheet_form_page] 从My_Piping获取到的productID: {product_id}")
                print(f"[sheet_form_page] 从My_Piping获取到的热交换器类型: {heat_exchanger}")
                if product_id:
                    return product_id
                else:
                    print(f"[sheet_form_page] productID为空")
                    return None
            else:
                print(f"[sheet_form_page] parent没有productID属性")
                return None
        except Exception as e:
            print(f"[sheet_form_page] 获取productID时出错: {e}")
            return None

    def _handle_image_click(self, event, index):
        # 方法内容保持不变
        try:
            # 每次点击图片前，尝试从父窗口刷新一次关键参数（DN、Di、是否以外径为基准、DL）
            try:
                self.get_DN_and_Di_from_parent()
            except Exception:
                pass

            if index >= len(self.sheet_form_image_labels):
                return

            label = self.sheet_form_image_labels[index]

            # 重置所有图片的选中状态
            for lbl in self.sheet_form_image_labels:
                lbl.setProperty("selected", False)
                lbl.setProperty("special_b_b", False)
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
            
            # 输出选中的图片名称（不带扩展名）
            image_name_without_ext = os.path.splitext(clicked_image)[0]
            print(f"选中节点: {image_name_without_ext}")
            
            # 输出产品ID
            product_id = self.get_product_id()
            print(f"当前产品ID: {product_id}")

            # 获取当前下拉框选中的文件夹名称
            connection_type_images = ['a', 'b', 'c', 'd', 'e', 'f']
            selected_folder = connection_type_images[current_index] if current_index < len(connection_type_images) else ""

            # 判断是否为 b 类中的 b_b 节点，用于控制选中时的边框颜色
            is_b_b_node = (selected_folder == 'b' and image_name_without_ext == 'b_b')
            label.setProperty("special_b_b", is_b_b_node)
            label.style().unpolish(label)
            label.style().polish(label)

            # 若为 b_b 节点，仿照 My_Piping.show_distance 提示“该节点暂不可用”
            if is_b_b_node and self.parent is not None and hasattr(self.parent, "line_tip"):
                try:
                    message = "该节点暂不可用"
                    line_tip = self.parent.line_tip
                    line_tip.setText(message)
                    line_tip.setStyleSheet("color: black;")
                    line_tip.setVisible(True)
                    from PyQt5.QtCore import QTimer
                    QTimer.singleShot(5000, lambda: line_tip.setText(""))
                except Exception:
                    pass

            # 清空右侧参数区域
            self._clear_param_layout()

            # 根据选择的图片显示对应的参数 - 使用表格形式
            # 获取产品ID
            product_id = self.get_product_id()
            params = get_plate_form_params(clicked_image, product_id)
            if params:
                # 每次填充前清除单元格合并状态
                self.sheet_form_param_table.clearSpans()

                # 默认使用两列表格
                self.sheet_form_param_table.setColumnCount(2)

                # 设置表格行数
                self.sheet_form_param_table.setRowCount(len(params))

                # 填充表格数据 - 完全照搬tube_sheet_connection.py的方式
                for row, (param_name, default_value) in enumerate(params.items()):
                    # 参数名列 - 只读
                    name_item = QTableWidgetItem(param_name)
                    name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)  # 参数名不可编辑
                    self.sheet_form_param_table.setItem(row, 0, name_item)

                    # 对于 e_f、f_f 节点，如果参数名为 a，则根据公式重新计算默认值
                    adjusted_value = default_value
                    if param_name == "a" and selected_folder in ["e", "f"] and image_name_without_ext in ["e_f", "f_f"]:
                        try:
                            dl = self.DL
                            dn = self.DN
                            di = self.Di
                            flag = (self.use_outer_diameter_base or "").strip()

                            # 仅在 DL 和相应直径存在时才计算
                            if flag == "否" and dl is not None and dn is not None:
                                adjusted_value = (dn - dl) / 4.0
                            elif flag == "是" and dl is not None and di is not None:
                                adjusted_value = (di - dl) / 4.0

                            # 将数值格式化为字符串（保留3位小数）
                            if isinstance(adjusted_value, (int, float)):
                                adjusted_value = f"{adjusted_value:.3f}"
                        except Exception as calc_err:
                            print(f"计算 a 默认值时出错: {calc_err}")

                    # 参数值列 - 根据是否为 b 类的 b_b 节点控制是否可编辑
                    value_item = QTableWidgetItem(str(adjusted_value))
                    if selected_folder == 'b' and image_name_without_ext == 'b_b':
                        # b_b 情况下参数值不可编辑
                        value_item.setFlags(value_item.flags() & ~Qt.ItemIsEditable & ~Qt.ItemIsEnabled)
                    else:
                        # 其他情况保持可编辑
                        value_item.setFlags(Qt.ItemIsEditable | Qt.ItemIsEnabled)
                    self.sheet_form_param_table.setItem(row, 1, value_item)

                # 对于 e_b、e_c、f_b、f_c 节点，特殊处理最后一行为三列显示，并在表格下方添加说明文字
                special_three_col_nodes = {
                    'e': ['e_b', 'e_c'],
                    'f': ['f_b', 'f_c']
                }

                if (
                    selected_folder in special_three_col_nodes
                    and image_name_without_ext in special_three_col_nodes[selected_folder]
                    and self.sheet_form_param_table.rowCount() > 0
                ):
                    total_rows = self.sheet_form_param_table.rowCount()

                    # 将表格扩展为3列
                    self.sheet_form_param_table.setColumnCount(3)

                    # 为除最后一行外的所有行合并第1、2两列，使其看起来仍是两列
                    for row in range(total_rows - 1):
                        self.sheet_form_param_table.setSpan(row, 1, 1, 2)

                    # 最后一行单独设置第三列内容为"*δ"，且只读不可编辑
                    last_row = total_rows - 1
                    third_item = QTableWidgetItem("*δ")
                    third_item.setFlags(third_item.flags() & ~Qt.ItemIsEditable)
                    self.sheet_form_param_table.setItem(last_row, 2, third_item)

                    # 在参数表格下方添加说明文字
                    note_label = QLabel(
                        "注：x的默认取值为：\n1.当δ≤12mm时，x=1.0；\n2.当δ>12mm时，x=0.75；"
                    )
                    note_label.setWordWrap(True)
                    # 再调大字号以便更加清晰
                    note_label.setStyleSheet("color: #555555; font-size: 20px;")
                    self.sheet_form_param_layout.addWidget(note_label)

                # 点击图片后同步更新父窗口的sheet_form_param_layout
                if self.parent:
                    self.parent.sheet_form_param_layout = self.get_current_tube_form_data()
            else:
                # 如果没有参数，显示空表格
                self.sheet_form_param_table.setRowCount(0)
        except Exception as e:
            print(f"处理图片点击时出错: {str(e)}")
            traceback.print_exc()

    def _handle_image_double_click(self, event, index):
        """双击图片时，打开大图预览弹窗"""
        try:
            if index < 0 or index >= len(self.sheet_form_image_labels):
                return

            # 先保持原有选择逻辑
            self._handle_image_click(event, index)

            # 根据当前索引获取图片路径
            if index >= len(self.sheet_form_current_images):
                return

            image_path = self.sheet_form_current_images[index]
            if not image_path or not os.path.exists(image_path):
                return

            dlg = ImagePreviewDialog(image_path, self)
            dlg.exec_()

        except Exception as e:
            print(f"处理图片双击时出错: {str(e)}")
            traceback.print_exc()

    def _clear_param_layout(self):
        # 清空布局中的所有控件，但保留表格
        if hasattr(self, 'sheet_form_param_layout') and self.sheet_form_param_layout:
            # 临时存储表格引用
            table_widget = self.sheet_form_param_table
            
            # 清空布局中的所有控件
            while self.sheet_form_param_layout.count():
                item = self.sheet_form_param_layout.takeAt(0)
                if item.widget() and item.widget() != table_widget:
                    item.widget().deleteLater()
                elif item.layout():
                    self._clear_sub_layout(item.layout())
            
            # 重新添加表格
            self.sheet_form_param_layout.addWidget(table_widget)
            
            # 清空表格内容
            if hasattr(self, 'sheet_form_param_table') and self.sheet_form_param_table is not None:
                self.sheet_form_param_table.setRowCount(0)

    def _clear_sub_layout(self, layout):
        # 方法内容保持不变
        while layout.count():
            sub_item = layout.takeAt(0)
            if sub_item.widget():
                sub_item.widget().deleteLater()
            elif sub_item.layout():
                self._clear_sub_layout(sub_item.layout())

    # -----------------------------------------------------------------
    # ✅ 解决方案：修改 update 方法以使用 ImageLabel
    # -----------------------------------------------------------------
    def sheet_form_updates_image_path(self, index):
        print(f"[DEBUG] 调用 sheet_form_updates_image_path, index={index}")
        try:
            if index < 0:
                return

            connection_type_images = ['a', 'b', 'c', 'd', 'e', 'f']
            if index >= len(connection_type_images):
                return

            selected_folder = connection_type_images[index]

            script_dir = os.path.dirname(os.path.abspath(__file__))
            image_base_path = os.path.join(script_dir, "static", "管板与壳体、管箱的连接")
            folder_path = os.path.join(image_base_path, selected_folder)

            if not os.path.exists(folder_path):
                for label in self.sheet_form_image_labels:
                    label.clear()
                    label.setText("无可用图片")  # 使用 ImageLabel.setText
                return

            # 清空旧图片
            for label in self.sheet_form_image_labels:
                label.clear()  # 调用 ImageLabel.clear()
                label.setProperty("selected", False)
                label.setStyleSheet(label.styleSheet())  # 重新应用样式

            self.sheet_form_current_images = []

            image_extensions = ['.png', '.jpg', '.jpeg', '.bmp']
            try:
                image_files = sorted([
                    f for f in os.listdir(folder_path)
                    if os.path.isfile(os.path.join(folder_path, f))
                    and os.path.splitext(f)[1].lower() in image_extensions
                ])
            except Exception as e:
                print(f"读取图片文件时出错: {str(e)}")
                image_files = []

            # 左上角标注文本
            b_overlay_texts = [
                "a)𝑝 ≤ 4MPa",
                "b)",
                "c)𝑝 < 6.4MPa",
                "d)𝑝 ≥ 6.4MPa",
                "e)𝑝 ≥ 6.4MPa",
                "h)𝑝 ≤ 4MPa"
            ]

            ef_overlay_texts = [
                "a)δ ≤ 12mm, Ps ≤ 1MPa",
                "b)1MPa < Ps ≤ 4MPa, δ ≤ 12, k = δ\n\t\t\t\t\tδ > 12, k = 0.7δ",
                "c)1MPa < Ps ≤ 4MPa, δ ≤ 12, k = δ\n\t\t\t\t\tδ > 12, k = 0.7δ",
                "d)Ps > 4MPa",
                "e)Ps > 4MPa",
                "f)Ps ≥ 4MPa",
                "g)Ps ≥ 4MPa"
            ]

            # 如果图片数量超过现有标签数量，动态创建更多标签
            while len(self.sheet_form_image_labels) < len(image_files):
                i = len(self.sheet_form_image_labels)
                # 创建新的图片标签
                lbl = ImageLabel()
                lbl.setMinimumSize(280, 250)
                lbl.setStyleSheet("""
                    ImageLabel {
                        border: 2px solid #ddd;
                        border-radius: 6px;
                        background-color: white;
                    }
                    ImageLabel:hover {
                        border: 2px solid #4CAF50;
                    }
                    ImageLabel[selected=true] {
                        border: 3px solid #2196F3;
                    }
                    ImageLabel[selected=true][special_b_b=true] {
                        border: 3px solid #888888;
                    }
                """)
                lbl.setProperty("selected", False)
                lbl.setProperty("special_b_b", False)
                lbl.setProperty("index", i)
                lbl.mousePressEvent = lambda event, idx=i: self._handle_image_click(event, idx)
                
                self.sheet_form_image_labels.append(lbl)
                # 添加到网格布局
                self.image_layout.addWidget(lbl, i // 3, i % 3)

            for i, image_file in enumerate(image_files):
                lbl = self.sheet_form_image_labels[i]
                image_path = os.path.join(folder_path, image_file)
                self.sheet_form_current_images.append(image_path)

                pixmap = QPixmap(image_path)
                if pixmap.isNull():
                    lbl.setText("图片加载失败")
                    continue

                # ✅ 根据分类选择对应文字
                text_to_draw = ""
                if selected_folder == 'b' and i < len(b_overlay_texts):
                    text_to_draw = b_overlay_texts[i]
                elif selected_folder in ['e', 'f'] and i < len(ef_overlay_texts):
                    text_to_draw = ef_overlay_texts[i]

                # ✅ 将原始 pixmap 和文字交给 ImageLabel
                lbl.setPixmap(pixmap)
                lbl.setText(text_to_draw)

            # 隐藏多余的标签（如果图片数量少于标签数量）
            for i in range(len(image_files), len(self.sheet_form_image_labels)):
                self.sheet_form_image_labels[i].hide()

            # 显示需要的标签
            for i in range(len(image_files)):
                self.sheet_form_image_labels[i].show()

            # 清空右侧参数区域
            self._clear_param_layout()

        except Exception as e:
            print(f"更新图片路径时出错: {str(e)}")
            import traceback
            traceback.print_exc()

        print(f"[DEBUG] 加载完成, 共加载 {len(self.sheet_form_current_images)} 张图片")




    def _safe_call(self, func):
        # 方法内容保持不变
        try:
            func()
        except Exception as e:
            print(f"调用函数时出错: {str(e)}")
            traceback.print_exc()

    def get_current_tube_form_data(self):
        """获取当前管板形式参数，返回元组列表格式"""
        # 检查是否有选中的图片
        selected_index = next(
            (i for i, lbl in enumerate(self.sheet_form_image_labels) if lbl.property("selected")),
            None
        )

        if selected_index is None:
            print("未选择任何管板图片")
            return []  # 返回空列表

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
            
            # 对 image_files 排序以确保 selected_index 匹配
            image_files.sort() 

            if selected_index >= len(image_files):
                raise IndexError(f"选中的图片索引 {selected_index} 超出范围 {len(image_files)}")

            # 提取管板类型
            clicked_image = image_files[selected_index]
            plate_type = os.path.splitext(clicked_image)[0]
            plate_type = f"{plate_type}"

        except Exception as e:
            print(f"获取管板类型时出错: {str(e)}")
            plate_type = "未知类型"

        # 从表格中提取参数数据，返回元组列表格式
        if not hasattr(self, 'sheet_form_param_table') or self.sheet_form_param_table is None:
            print("参数表格未初始化")
            return []

        # 构建完整参数列表：管板类型 + 具体参数
        full_params = []

        # 添加管板类型参数
        if plate_type:
            full_params.append(("管板类型", plate_type))

        # 从表格中提取具体参数
        for row in range(self.sheet_form_param_table.rowCount()):
            # 获取参数名（第0列）
            name_item = self.sheet_form_param_table.item(row, 0)
            # 获取参数值（第1列）
            value_item = self.sheet_form_param_table.item(row, 1)
            
            if name_item and value_item:
                param_name = name_item.text().strip()
                param_value = value_item.text().strip()
                
                if param_name:
                    full_params.append((param_name, param_value))

        print(f"🔍 [调试] 管板形式参数数量: {len(full_params)}")
        return full_params

    def get_DN_and_Di_from_parent(self):
        # 从父界面的布管参数表中获取：公称直径 DN、壳体内直径 Dis、是否以外径为基准、布管限定圆 DL
        try:
            # 检查父窗口是否存在
            if not self.parent:
                print("错误：父窗口不存在")
                return False
            
            # 检查父窗口是否有param_table属性
            if not hasattr(self.parent, 'param_table'):
                print("错误：父窗口没有param_table属性")
                return False
            
            param_table = self.parent.param_table
            
            # 初始化变量
            dn_value = None
            di_value = None
            outer_base_value = None  # "是否以外径为基准"
            dl_value = None         # 布管限定圆 DL
            
            # 遍历参数表的所有行
            for row in range(param_table.rowCount()):
                # 跳过隐藏行
                if param_table.isRowHidden(row):
                    continue
                
                # 获取参数名（第1列）
                param_name_item = param_table.item(row, 1)
                if not param_name_item:
                    continue
                
                param_name = param_name_item.text().strip()
                
                # 获取参数值（第2列）
                # 需要检查是否是QComboBox
                cell_widget = param_table.cellWidget(row, 2)
                if isinstance(cell_widget, QComboBox):
                    param_value = cell_widget.currentText()
                else:
                    value_item = param_table.item(row, 2)
                    param_value = value_item.text() if value_item else ""
                
                # 匹配参数名并获取值
                if param_name == "公称直径 DN":
                    try:
                        dn_value = float(param_value) if param_value else None
                        print(f"获取到公称直径 DN: {dn_value}")
                    except ValueError:
                        print(f"警告：公称直径 DN 的值 '{param_value}' 无法转换为数字")
                        dn_value = None
                
                elif param_name == "壳体内直径 Dis":
                    try:
                        di_value = float(param_value) if param_value else None
                        print(f"获取到壳体内直径 Dis: {di_value}")
                    except ValueError:
                        print(f"警告：壳体内直径 Dis 的值 '{param_value}' 无法转换为数字")
                        di_value = None

                elif param_name == "是否以外径为基准":
                    # 直接保存文本：“是”或“否”等
                    outer_base_value = param_value.strip()
                    print(f"获取到 是否以外径为基准: {outer_base_value}")

                elif param_name == "布管限定圆 DL":
                    try:
                        dl_value = float(param_value) if param_value else None
                        print(f"获取到 布管限定圆 DL: {dl_value}")
                    except ValueError:
                        print(f"警告：布管限定圆 DL 的值 '{param_value}' 无法转换为数字")
                        dl_value = None
            
            # 将获取到的值赋给全局变量
            self.DN = dn_value
            self.Di = di_value
            self.use_outer_diameter_base = outer_base_value
            self.DL = dl_value
            
            # 检查是否成功获取到关键参数（DN、Di、DL 至少要有一个）
            if self.DN is None and self.Di is None:
                print("警告：未能从参数表中找到'公称直径 DN'和'壳体内直径 Dis'")
                return False
            if self.DL is None:
                print("警告：未能从参数表中找到 '布管限定圆 DL'")
            print(f"成功获取参数 - 公称直径 DN: {self.DN}, 壳体内直径 Dis: {self.Di}, 是否以外径为基准: {self.use_outer_diameter_base}, 布管限定圆 DL: {self.DL}")
            return True
                
        except Exception as e:
            print(f"获取参数时发生错误: {str(e)}")
            traceback.print_exc()
            return False

#'''

