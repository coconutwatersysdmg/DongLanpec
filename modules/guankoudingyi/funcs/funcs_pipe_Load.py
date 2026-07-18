from PyQt5.QtWidgets import (QDialog, QTableWidget, QTableWidgetItem, QHeaderView, 
                             QSizePolicy, QAbstractScrollArea, QStyledItemDelegate, 
                             QComboBox, QLineEdit, QLabel, QWidget, QVBoxLayout, QTabWidget, QPushButton, QMessageBox, QRadioButton)
from PyQt5.QtCore import Qt, QTimer, QEvent
from PyQt5.QtGui import QFont, QPixmap, QDoubleValidator, QColor, QBrush
import os
import re
from modules.guankoudingyi.db_cnt import get_connection, db_config_1, db_config_2
from modules.guankoudingyi.funcs.funcs_pipe_table import show_styled_message


class NoWheelComboBox(QComboBox):
    """与管口定义页一致：禁止滚轮误改值"""
    def wheelEvent(self, e):
        e.ignore()


class LocalStressCalcTypeComboDelegate(QStyledItemDelegate):
    """局部应力计算类型下拉框代理（仅对第二行第二列生效）"""
    
    def __init__(self, parent=None, options=None, target_row=1, target_col=1):
        """
        :param parent: 父对象
        :param options: 下拉框选项列表
        :param target_row: 目标行索引（默认1，即第二行）
        :param target_col: 目标列索引（默认1，即第二列）
        """
        super().__init__(parent)
        self.items = options or []
        self.target_row = target_row
        self.target_col = target_col
    
    def setItems(self, items):
        """设置下拉框的选项"""
        self.items = items or []
    
    def createEditor(self, parent, option, index):
        """创建编辑器（下拉框），仅对目标单元格生效"""
        # 只对第二行第二列创建下拉框
        if index.row() == self.target_row and index.column() == self.target_col:
            editor = NoWheelComboBox(parent)
            editor.addItems(self.items)
            editor.setEditable(False)  # 不可编辑，只能选择
            # 设置下拉框选项之间的间距
            editor.view().setSpacing(5)
            return editor
        else:
            # 其他单元格使用普通文本编辑器
            editor = QLineEdit(parent)
            return editor
    
    def setEditorData(self, editor, index):
        """设置编辑器的数据"""
        # 只处理目标单元格
        if index.row() == self.target_row and index.column() == self.target_col and isinstance(editor, QComboBox):
            value = index.model().data(index, Qt.EditRole) or ""
            if value:
                # 查找匹配的选项索引
                item_index = editor.findText(value)
                if item_index >= 0:
                    editor.setCurrentIndex(item_index)
                else:
                    editor.setCurrentIndex(0)
            else:
                editor.setCurrentIndex(0)
        else:
            super().setEditorData(editor, index)
    
    def setModelData(self, editor, model, index):
        """将编辑器的数据设置到模型中"""
        if isinstance(editor, QComboBox):
            value = editor.currentText()
            model.setData(index, value, Qt.EditRole)
        else:
            super().setModelData(editor, model, index)
    
    def updateEditorGeometry(self, editor, option, index):
        """更新编辑器的几何位置"""
        editor.setGeometry(option.rect)


class NumericValueDelegate(QStyledItemDelegate):
    """zaihecanshu 第二列数值输入代理：仅允许数值（含负号与小数）。"""

    def createEditor(self, parent, option, index):
        # 仅对第二列生效，其他列沿用默认编辑器
        if index.column() != 1:
            return super().createEditor(parent, option, index)

        editor = QLineEdit(parent)
        validator = QDoubleValidator(editor)
        validator.setNotation(QDoubleValidator.StandardNotation)
        validator.setDecimals(8)
        validator.setBottom(-1e20)
        validator.setTop(1e20)
        editor.setValidator(validator)
        return editor

"""读取局部应力计算类型的下拉框内容"""
def get_local_stress_calc_types_from_db():
    """
    从元件库的管口载荷图配置表中读取局部应力计算类型列的所有不重复值
    :return: 局部应力计算类型列表
    """
    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config_1)
        cursor = conn.cursor()
        
        sql = """
            SELECT DISTINCT 局部应力计算类型 
            FROM 管口载荷图配置表
            WHERE 局部应力计算类型 IS NOT NULL AND 局部应力计算类型 != ''
            
        """
        cursor.execute(sql)
        results = cursor.fetchall()
        
        # 提取所有不重复的局部应力计算类型
        types = [row["局部应力计算类型"].strip() for row in results if row.get("局部应力计算类型")]
        return types
        
    except Exception as e:
        print(f"[ERROR] 读取局部应力计算类型失败: {e}")
        return []
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

"""读取局部应力计算类型对应的示意图"""
def get_load_image_path_by_calc_type(calc_type):
    """
    根据局部应力计算类型从数据库获取对应的载荷示意图路径
    :param calc_type: 局部应力计算类型
    :return: 载荷示意图的文件名（不包含文件夹路径），如果不存在则返回None
    """
    if not calc_type or not calc_type.strip():
        return None
    
    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config_1)
        cursor = conn.cursor()
        
        sql = """
            SELECT 载荷示意图 
            FROM 管口载荷图配置表
            WHERE 局部应力计算类型 = %s
            LIMIT 1
        """
        cursor.execute(sql, (calc_type.strip(),))
        result = cursor.fetchone()
        
        if result and result.get("载荷示意图"):
            image_path = result["载荷示意图"].replace("\\", os.sep).strip()
            # 从路径中提取文件名（处理 openload_img\WRC537_2.png 格式）
            # 数据库中可能存储 openload_img\WRC537_2.png，实际文件夹是 openload_img
            filename = os.path.basename(image_path)
            return filename
        return None
        
    except Exception as e:
        print(f"[ERROR] 读取载荷示意图路径失败: {e}")
        return None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

"""读取局部应力计算类型对应的载荷计算图路径（第二个tab页用）"""
def get_load_calc_image_path_by_calc_type(calc_type):
    """
    根据局部应力计算类型从数据库获取对应的载荷计算图路径（第二个tab页用）
    :param calc_type: 局部应力计算类型
    :return: 载荷计算图的文件名（不包含文件夹路径），如果不存在则返回None
    """
    if not calc_type or not calc_type.strip():
        return None
    
    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config_1)
        cursor = conn.cursor()
        
        sql = """
            SELECT 载荷计算图 
            FROM 管口载荷图配置表
            WHERE 局部应力计算类型 = %s
            LIMIT 1
        """
        cursor.execute(sql, (calc_type.strip(),))
        result = cursor.fetchone()
        
        if result and result.get("载荷计算图"):
            image_path = result["载荷计算图"].replace("\\", os.sep).strip()
            # 从路径中提取文件名（处理 openload_img\WRC537_2.png 格式）
            # 数据库中可能存储 openload_img\WRC537_2.png，实际文件夹是 openload_img
            filename = os.path.basename(image_path)
            return filename
        return None
        
    except Exception as e:
        print(f"[ERROR] 读取载荷计算图路径失败: {e}")
        return None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

"""显示管口载荷示意图"""
def display_load_image(dialog, calc_type):
    """
    根据局部应力计算类型显示对应的载荷示意图
    :param dialog: 对话框实例
    :param calc_type: 局部应力计算类型
    """
    if not dialog or not calc_type:
        return
    
    def apply_image():
        try:
            # 获取图片显示控件（img_load）
            image_widget = dialog.findChild(QWidget, "img_load")
            if not image_widget:
                print("[图片显示] 未找到图片显示控件 img_load")
                return
            
            # 获取载荷示意图文件名
            filename = get_load_image_path_by_calc_type(calc_type)
            if not filename:
                print(f"[图片显示] 未找到局部应力计算类型 '{calc_type}' 对应的载荷示意图")
                # 清空图片显示
                image_widget.setStyleSheet("background-color: rgb(255, 255, 255);")
                return
            
            # 构建完整图片路径
            # 图片文件夹在 modules/guankoudingyi/openload_img/ 目录下
            # 获取当前文件所在目录（funcs），然后回到 guankoudingyi 目录
            current_file_dir = os.path.dirname(os.path.abspath(__file__))  # funcs目录
            guankoudingyi_dir = os.path.dirname(current_file_dir)  # guankoudingyi目录
            openingload_img_dir = os.path.join(guankoudingyi_dir, "openload_img")
            image_path = os.path.join(openingload_img_dir, filename)
            
            # 统一路径分隔符
            image_path = os.path.normpath(image_path)
            
            #print(f"[图片显示] 尝试加载图片: {image_path}")
            
            if os.path.exists(image_path):
                # 加载图片
                pixmap = QPixmap(image_path)
                if pixmap.isNull():
                    print(f"[图片显示] QPixmap 加载失败，文件格式可能不支持: {image_path}")
                    image_widget.setStyleSheet("background-color: rgb(255, 255, 255);")
                    return
                
                # 在widget上显示图片
                # 检查widget是否有QLabel子控件，如果没有则创建
                label = image_widget.findChild(QLabel)
                if not label:
                    # 创建一个QLabel来显示图片
                    label = QLabel(image_widget)
                    label.setAlignment(Qt.AlignCenter)
                    # 设置label填满整个widget
                    layout = image_widget.layout()
                    if layout is None:
                        layout = QVBoxLayout(image_widget)
                        layout.setContentsMargins(0, 0, 0, 0)
                    layout.addWidget(label)
                
                # 获取用于缩放的基准尺寸
                # 需求：弹窗放大/还原后，切换类型时不要根据当前放大的尺寸继续放大图片，
                # 而是始终使用弹窗初次打开时的尺寸进行缩放，这样图片大小更稳定。
                base_size = getattr(dialog, "_img_load_base_size", None)
                if base_size is None or base_size.width() <= 0 or base_size.height() <= 0:
                    # 第一次调用时记录当前控件尺寸，后续切换类型都使用这个基准尺寸
                    base_size = image_widget.size()
                    dialog._img_load_base_size = base_size
                
                widget_width = max(1, base_size.width())
                widget_height = max(1, base_size.height())
                
                # 缩放图片以填满整个控件，保持宽高比（超出部分会被裁剪）
                scaled_pixmap = pixmap.scaled(
                    widget_width,
                    widget_height,
                    Qt.KeepAspectRatioByExpanding,  # 保持宽高比，但填满整个区域
                    Qt.SmoothTransformation
                )
                
                # 设置缩放后的图片
                label.setPixmap(scaled_pixmap)
                # 不使用setScaledContents，因为我们已经手动缩放了
                label.setScaledContents(False)
                label.show()
                #print(f"[图片显示] 图片加载并显示成功")
            else:
                print(f"[图片显示] 图片文件不存在: {image_path}")
                image_widget.setStyleSheet("background-color: rgb(255, 255, 255);")
                
        except Exception as e:
            print(f"[图片显示] 加载图片异常: {e}")
            import traceback
            traceback.print_exc()
    
    # 延迟执行以确保layout完成
    QTimer.singleShot(0, apply_image)

"""显示第二个tab页的载荷计算图"""
def display_load_calc_image(dialog, calc_type, retry_count=0):
    """
    根据局部应力计算类型显示对应的载荷计算图（第二个tab页）
    :param dialog: 对话框实例
    :param calc_type: 局部应力计算类型
    :param retry_count: 重试次数（用于避免无限递归，已废弃，保留参数以兼容）
    """
    if not dialog or not calc_type:
        return
    
    def apply_image():
        try:
            # 获取图片显示控件（img_loadParameter）
            image_widget = dialog.findChild(QWidget, "img_loadParameter")
            if not image_widget:
                print("[图片显示-第二个tab页] 未找到图片显示控件 img_loadParameter")
                return
            
            # 获取载荷计算图文件名
            filename = get_load_calc_image_path_by_calc_type(calc_type)
            if not filename:
                print(f"[图片显示-第二个tab页] 未找到局部应力计算类型 '{calc_type}' 对应的载荷计算图")
                # 清空图片显示
                image_widget.setStyleSheet("background-color: rgb(255, 255, 255);")
                return
            
            # 构建完整图片路径
            # 图片文件夹在 modules/guankoudingyi/openload_img/ 目录下
            # 获取当前文件所在目录（funcs），然后回到 guankoudingyi 目录
            current_file_dir = os.path.dirname(os.path.abspath(__file__))  # funcs目录
            guankoudingyi_dir = os.path.dirname(current_file_dir)  # guankoudingyi目录
            openingload_img_dir = os.path.join(guankoudingyi_dir, "openload_img")
            image_path = os.path.join(openingload_img_dir, filename)
            
            # 统一路径分隔符
            image_path = os.path.normpath(image_path)
            
            #print(f"[图片显示-第二个tab页] 尝试加载图片: {image_path}")
            
            if os.path.exists(image_path):
                # 加载图片
                pixmap = QPixmap(image_path)
                if pixmap.isNull():
                    print(f"[图片显示-第二个tab页] QPixmap 加载失败，文件格式可能不支持: {image_path}")
                    image_widget.setStyleSheet("background-color: rgb(255, 255, 255);")
                    return
                
                # 在widget上显示图片
                # 检查widget是否有QLabel子控件，如果没有则创建
                label = image_widget.findChild(QLabel)
                if not label:
                    # 创建一个QLabel来显示图片
                    label = QLabel(image_widget)
                    label.setAlignment(Qt.AlignCenter)
                    # 设置label填满整个widget
                    layout = image_widget.layout()
                    if layout is None:
                        layout = QVBoxLayout(image_widget)
                        layout.setContentsMargins(0, 0, 0, 0)
                    layout.addWidget(label)
                
                # 获取用于缩放的基准尺寸
                # 需求：弹窗放大/还原后，切换类型时不要根据当前放大的尺寸继续放大图片，
                # 而是始终使用弹窗初次打开时的尺寸进行缩放，这样图片大小更稳定。
                base_size = getattr(dialog, "_img_load_param_base_size", None)
                if base_size is None or base_size.width() <= 0 or base_size.height() <= 0:
                    # 第一次调用时记录当前控件尺寸，后续切换类型都使用这个基准尺寸
                    base_size = image_widget.size()
                    dialog._img_load_param_base_size = base_size

                widget_width = max(1, base_size.width())
                widget_height = max(1, base_size.height())
                
                # # 重试机制已废弃（UI文件中已设置最小尺寸，不再需要）
                # # 如果控件尺寸还未确定（宽度或高度小于50），且重试次数小于3，使用延迟重试
                # if (widget_width < 50 or widget_height < 50) and retry_count < 3:
                #     # 使用更长的延迟，等待控件尺寸确定
                #     QTimer.singleShot(200, lambda: display_load_calc_image(dialog, calc_type, retry_count + 1))
                #     return
                # 
                # # 如果尺寸仍然很小，使用sizeHint作为备用
                # if widget_width < 50 or widget_height < 50:
                #     size_hint = image_widget.sizeHint()
                #     if size_hint.width() > 50:
                #         widget_width = size_hint.width()
                #     if size_hint.height() > 50:
                #         widget_height = size_hint.height()
                
                # 图片显示尺寸：控件尺寸减去4像素（上下左右各2像素边距）
                margin = 2
                image_width = max(1, widget_width - margin * 2)
                image_height = max(1, widget_height - margin * 2)
                
                # 缩放图片，保持宽高比，略小于控件大小（留出2像素边距）
                scaled_pixmap = pixmap.scaled(
                    image_width,
                    image_height,
                    Qt.KeepAspectRatio,  # 保持宽高比，不超出区域
                    Qt.SmoothTransformation
                )
                
                # 设置缩放后的图片
                label.setPixmap(scaled_pixmap)
                # 不使用setScaledContents，因为我们已经手动缩放了
                label.setScaledContents(False)
                # label已经设置了居中对齐，图片会在label中居中显示，周围自然会有边距
                label.show()
                #print(f"[图片显示-第二个tab页] 图片加载并显示成功")
            else:
                print(f"[图片显示-第二个tab页] 图片文件不存在: {image_path}")
                image_widget.setStyleSheet("background-color: rgb(255, 255, 255);")
                
        except Exception as e:
            print(f"[图片显示-第二个tab页] 加载图片异常: {e}")
            import traceback
            traceback.print_exc()
    
    # 延迟执行以确保layout完成
    # 由于UI文件中已设置图片控件的最小尺寸，可以使用较小的延迟
    QTimer.singleShot(0, apply_image)
    
    # # 重试机制已废弃（UI文件中已设置最小尺寸，不再需要）
    # # 第一次调用时使用稍长的延迟（100ms），确保控件尺寸已确定
    # # 如果是重试调用，使用200ms的延迟
    # delay = 100 if retry_count == 0 else 200
    # QTimer.singleShot(delay, apply_image)

"""根据局部应力计算类型读取参数并填充到第二个tab页表格的第一列"""
def fill_load_params_by_calc_type(dialog: QDialog, calc_type: str):
    """
    根据局部应力计算类型从元件库的管口载荷参数表中读取参数，填充到第二个tab页表格的第一列
    :param dialog: 对话框实例
    :param calc_type: 局部应力计算类型
    """
    if not dialog or not calc_type or not calc_type.strip():
        return
    
    # 获取第二个tab页的表格（zaihecanshu）
    table: QTableWidget = dialog.findChild(QTableWidget, "zaihecanshu")
    if not table:
        print("[填充载荷参数] 未找到zaihecanshu控件")
        return
    
    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config_1)
        cursor = conn.cursor()
        
        # 从元件库的管口载荷参数表中读取对应参数
        sql = """
            SELECT 对应参数 
            FROM 管口载荷参数表 
            WHERE 局部应力计算类型 = %s
            ORDER BY 对应ID
        """
        cursor.execute(sql, (calc_type.strip(),))
        results = cursor.fetchall()

        if not results:
            print(f"[填充载荷参数] 未找到局部应力计算类型 '{calc_type}' 对应的参数")
            return
        
        # 提取参数列表
        params = [row["对应参数"].strip() for row in results if row.get("对应参数")]

        # 现在zaihecanshu表从第一行开始就是参数行（参考引用已移到justlike表）
        # 需要显示的总行数 = 参数行数
        # 例如：3、4、6 个参数 -> 3、4、6 行；7 个参数 -> 7行
        target_row_count = len(params)

        # 先根据目标行数增减表格行数，避免出现多余的空白单元行
        current_row_count = table.rowCount()
        if current_row_count < target_row_count:
            # 不足时，从末尾开始插入新行
            for _ in range(target_row_count - current_row_count):
                row_index = table.rowCount()
                table.insertRow(row_index)
                table.setRowHeight(row_index, 40)
        elif current_row_count > target_row_count:
            # 多余时，从末尾开始删除行
            for _ in range(current_row_count - target_row_count):
                table.removeRow(table.rowCount() - 1)

        # 从第一行开始（行索引0）填充参数到第一列
        start_row = 0
        for idx, param in enumerate(params):
            row_index = start_row + idx

            # 获取或创建第一列的单元格
            item = table.item(row_index, 0)
            if item is None:
                item = QTableWidgetItem(param)
            else:
                item.setText(param)

            # 对第一列统一设置：居中、不可编辑、不可选中
            #item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable & ~Qt.ItemIsSelectable)
            table.setItem(row_index, 0, item)
            
            # 确保第二列已存在 item 并设置规则（参数值在切换类型时由 clear_zaihecanshu_parameter_values 清空）
            item_col1 = table.item(row_index, 1)
            if item_col1 is None:
                item_col1 = QTableWidgetItem()
                table.setItem(row_index, 1, item_col1)
            if _is_fixed_zero_angle_param(param):
                _set_fixed_zero_angle_cell_style(item_col1)
            else:
                item_col1.setTextAlignment(Qt.AlignCenter)
                item_col1.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                item_col1.setBackground(QBrush(QColor(255, 255, 255)))

        # 行数变化后，同步重设表格高度：有几行就只显示几行（避免内部空白）
        fixed_row_height = 40
        for r in range(table.rowCount()):
            table.setRowHeight(r, fixed_row_height)
        total_height = fixed_row_height * table.rowCount() + 2
        table.setFixedHeight(total_height)
        table.setMinimumHeight(total_height)
        table.setMaximumHeight(total_height)
        

        

        
    except Exception as e:
        print(f"[ERROR] 读取载荷参数失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

"""根据局部应力计算类型获取对应的tab页编号"""
def get_tab_number_by_calc_type(calc_type: str) -> str:
    """
    根据局部应力计算类型返回对应的tab页编号
    :param calc_type: 局部应力计算类型
    :return: tab页编号字符串，如果未匹配则返回"默认值"
    """
    if not calc_type or not calc_type.strip():
        return "柱壳上圆形附件或接管数据输入"
    
    calc_type = calc_type.strip()
    
    # 定义映射关系
    type_to_number = {
        "柱壳上圆形附件或接管计算(WRC 537)": "柱壳上圆形附件或接管数据输入",
        "凸形封头上接管计算(WRC 537)": "凸形封头上接管数据输入",
        "柱壳上接管计算(WRC 297)": "柱壳上接管数据输入",
        "凸形封头上接管计算(EN 13445)": "凸形封头上接管数据输入",
        "柱壳上接管计算(EN 13445)": "柱壳上接管数据输入",
        "圆柱壳上接管计算(CSCBPV-TD001-2013)": "圆柱壳上接管数据输入"
    }
    
    return type_to_number.get(calc_type, "柱壳上圆形附件或接管数据输入")

"""更新第二个tab页的名称"""
def update_second_tab_name(dialog: QDialog, calc_type: str):
    """
    根据局部应力计算类型更新第二个tab页的名称
    :param dialog: 对话框实例
    :param calc_type: 局部应力计算类型
    """
    if not dialog or not calc_type:
        return
    
    tab_widget = dialog.findChild(QTabWidget, "tabWidget")
    if not tab_widget:
        print("[更新Tab页名称] 未找到tabWidget控件")
        return
    
    # 获取对应的tab页编号
    tab_number = get_tab_number_by_calc_type(calc_type)
    
    # 第二个tab页的索引是1
    if tab_widget.count() > 1:
        tab_widget.setTabText(1, tab_number)

    else:
        print("[更新Tab页名称] tabWidget中不存在第二个tab页")

"""设置局部应力符号的默认值"""
def set_local_stress_symbol_by_pipe_code(dialog: QDialog, pipe_code: str):
    """
    根据管口代号设置局部应力符号的默认值
    :param dialog: 对话框实例
    :param pipe_code: 管口代号（例如：N1, N2, N3...）
    """
    if not dialog or not pipe_code:
        return
    
    # 获取表格控件
    table = dialog.findChild(QTableWidget, "yinglijisuan")
    if not table:
        return
    
    # 从管口代号中提取数字部分（例如：N1 -> 1, N2 -> 2）
    match = re.search(r'\d+', pipe_code)
    if match:
        number = match.group()
        symbol_value = f"F{number}"
    else:
        # 如果无法提取数字，使用默认值F1
        symbol_value = "F"
        print(f"[局部应力符号] 无法从管口代号 '{pipe_code}' 中提取数字，使用默认值: {symbol_value}")
    
    # 第一行第一列（索引0,0）是标签"局部应力符号"
    # 第一行第二列（索引0,1）是局部应力符号的输入框
    # 获取或创建第一行第二列的item
    item = table.item(0, 1)
    if item is None:
        item = QTableWidgetItem(symbol_value)
        item.setTextAlignment(Qt.AlignCenter)
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
        table.setItem(0, 1, item)
    else:
        # 如果item已存在但为空，设置默认值
        if not item.text().strip():
            item.setText(symbol_value)
    
    #print(f"[局部应力符号] 根据管口代号 '{pipe_code}' 设置默认值: {symbol_value}")

"""从数据库加载管口载荷数据"""
def load_pipe_load_data_from_db(product_id, pipe_id):
    """
    从产品设计活动库的产品设计活动表_管口载荷表中加载数据
    :param product_id: 产品ID
    :param pipe_id: 管口ID
    :return: 字典，键为参数名称，值为参数值；若不存在返回None
    """
    if not product_id or not pipe_id:
        return None
    
    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config_2)
        cursor = conn.cursor()
        
        sql = """
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_管口载荷表
            WHERE 产品ID = %s AND 管口ID = %s
              AND 参数名称 IN ('局部应力符号', '局部应力计算类型', '载荷作用位置')
        """
        cursor.execute(sql, (product_id, pipe_id))
        results = cursor.fetchall()

        if results:
            data = {}
            for row in results:
                param_name = (row.get("参数名称") or "").strip()
                if not param_name:
                    continue
                param_value = row.get("参数值")
                data[param_name] = str(param_value).strip() if param_value is not None else None
            return data if data else None
        return None
        
    except Exception as e:
        print(f"[ERROR] 加载管口载荷数据失败: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

"""从数据库加载第二个tab页的载荷参数值"""
def load_second_tab_params_from_db(dialog: QDialog, product_id: int, pipe_id: int):
    """
    从数据库加载第二个tab页表格的参数值到第二列
    根据第一列的参数名称（字段名），从数据库查询对应的值并填入第二列
    :param dialog: 对话框实例
    :param product_id: 产品ID
    :param pipe_id: 管口ID
    """
    if not dialog or not product_id or not pipe_id:
        return
    
    # 获取第二个tab页的表格
    table: QTableWidget = dialog.findChild(QTableWidget, "zaihecanshu")
    if not table:
        print("[加载第二个tab页参数值] 未找到zaihecanshu控件")
        return
    
    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config_2)
        cursor = conn.cursor()

        # 先收集表格第一列的参数名称
        param_names = []
        for row in range(table.rowCount()):
            param_item = table.item(row, 0)
            if not param_item:
                continue
            name = param_item.text().strip()
            if name:
                param_names.append(name)

        if not param_names:
            return

        placeholders = ", ".join(["%s"] * len(param_names))
        sql = f"""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_管口载荷表
            WHERE 产品ID = %s AND 管口ID = %s
              AND 参数名称 IN ({placeholders})
        """
        cursor.execute(sql, [product_id, pipe_id, *param_names])
        rows = cursor.fetchall() or []

        value_map = {}
        for r in rows:
            k = (r.get("参数名称") or "").strip()
            if not k:
                continue
            v = r.get("参数值")
            value_map[k] = "" if v is None else str(v).strip()

        # 回填第二列
        for row in range(table.rowCount()):
            param_item = table.item(row, 0)
            if not param_item:
                continue
            name = param_item.text().strip()
            if not name:
                continue

            value_str = value_map.get(name, "")
            value_item = table.item(row, 1)
            if value_item is None:
                value_item = QTableWidgetItem(value_str)
                value_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, 1, value_item)
            if _is_fixed_zero_angle_param(name):
                _set_fixed_zero_angle_cell_style(value_item)
            else:
                value_item.setText(value_str)
                value_item.setTextAlignment(Qt.AlignCenter)
                value_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                value_item.setBackground(QBrush(QColor(255, 255, 255)))

    except Exception as e:
        print(f"[ERROR] 加载第二个tab页参数值失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def get_reference_pipe_candidates(product_id: int, current_pipe_id: int, calc_type: str):
    """
    查询可作为“参考引用”的管口：
    - 同一产品
    - 局部应力计算类型与当前一致
    - 非当前管口
    - 在第二界面参数中至少有一项已填写（参数值非空）
    """
    if not product_id or not current_pipe_id or not calc_type:
        return []

    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config_2)
        cursor = conn.cursor()
        sql = """
            SELECT DISTINCT t.管口ID, code_map.管口代号
            FROM 产品设计活动表_管口载荷表 t
            LEFT JOIN (
                SELECT 产品ID, 管口ID, MAX(NULLIF(TRIM(管口代号), '')) AS 管口代号
                FROM 产品设计活动表_管口载荷表
                WHERE 参数名称 IN ('局部应力符号', '局部应力计算类型', '载荷作用位置')
                GROUP BY 产品ID, 管口ID
            ) code_map
                ON code_map.产品ID = t.产品ID
               AND code_map.管口ID = t.管口ID
            INNER JOIN 产品设计活动表_管口载荷表 ct
                ON ct.产品ID = t.产品ID
               AND ct.管口ID = t.管口ID
               AND ct.参数名称 = '局部应力计算类型'
               AND TRIM(COALESCE(ct.参数值, '')) = TRIM(%s)
            WHERE t.产品ID = %s
              AND t.管口ID <> %s
              AND t.参数名称 NOT IN ('局部应力符号', '局部应力计算类型', '载荷作用位置')
              AND COALESCE(TRIM(t.参数值), '') <> ''
            ORDER BY code_map.管口代号
        """
        cursor.execute(sql, (calc_type.strip(), product_id, current_pipe_id))
        rows = cursor.fetchall() or []
        result = []
        for row in rows:
            code = (row.get("管口代号") or "").strip()
            pid = row.get("管口ID")
            if not pid:
                continue
            # 仅显示真实管口代号；若未查到代号则不展示该候选
            if not code:
                continue
            result.append({"pipe_id": pid, "pipe_code": code})
        return result
    except Exception as e:
        print(f"[ERROR] 查询参考引用候选管口失败: {e}")
        return []
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def apply_reference_pipe_params(dialog: QDialog, product_id: int, ref_pipe_id: int):
    """按参数名称从参考管口读取第二页参数值并回填到当前 zaihecanshu 表格。"""
    if not dialog or not product_id or not ref_pipe_id:
        return
    table: QTableWidget = dialog.findChild(QTableWidget, "zaihecanshu")
    if not table:
        return

    param_names = []
    for row in range(table.rowCount()):
        name_item = table.item(row, 0)
        name = name_item.text().strip() if name_item and name_item.text() else ""
        if name:
            param_names.append(name)
    if not param_names:
        return

    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config_2)
        cursor = conn.cursor()
        placeholders = ", ".join(["%s"] * len(param_names))
        sql = f"""
            SELECT 参数名称, 参数值
            FROM 产品设计活动表_管口载荷表
            WHERE 产品ID = %s AND 管口ID = %s
              AND 参数名称 IN ({placeholders})
        """
        cursor.execute(sql, [product_id, ref_pipe_id, *param_names])
        rows = cursor.fetchall() or []
        value_map = {}
        for r in rows:
            name = (r.get("参数名称") or "").strip()
            if not name:
                continue
            v = r.get("参数值")
            value_map[name] = "" if v is None else str(v).strip()

        table.blockSignals(True)
        try:
            for row in range(table.rowCount()):
                name_item = table.item(row, 0)
                name = name_item.text().strip() if name_item and name_item.text() else ""
                if not name:
                    continue
                value_item = table.item(row, 1)
                if value_item is None:
                    value_item = QTableWidgetItem()
                    value_item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(row, 1, value_item)
                if _is_fixed_zero_angle_param(name):
                    _set_fixed_zero_angle_cell_style(value_item)
                else:
                    value_item.setText(value_map.get(name, ""))
                    value_item.setTextAlignment(Qt.AlignCenter)
                    value_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                    value_item.setBackground(QBrush(QColor(255, 255, 255)))
        finally:
            table.blockSignals(False)
    except Exception as e:
        print(f"[ERROR] 引用管口参数失败: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def refresh_reference_pipe_dropdown(dialog: QDialog, product_id: int, current_pipe_id: int):
    """刷新 justlike 第1行第2列（参考引用）下拉项：同局部应力计算类型的可引用管口代号。"""
    if not dialog:
        return
    justlike_table: QTableWidget = dialog.findChild(QTableWidget, "justlike")
    ylj_table: QTableWidget = dialog.findChild(QTableWidget, "yinglijisuan")
    if not justlike_table or justlike_table.rowCount() < 1 or not ylj_table:
        return

    calc_type_item = ylj_table.item(1, 1)
    calc_type = calc_type_item.text().strip() if calc_type_item and calc_type_item.text() else ""
    candidates = get_reference_pipe_candidates(product_id, current_pipe_id, calc_type)
    options = [x["pipe_code"] for x in candidates]
    dialog._reference_pipe_id_map = {x["pipe_code"]: x["pipe_id"] for x in candidates}

    # 仅作用于第1行（索引0）第2列，保留第2行载荷作用位置原有下拉逻辑
    ref_delegate = LocalStressCalcTypeComboDelegate(
        justlike_table, options=options, target_row=0, target_col=1
    )
    ref_delegate.setParent(justlike_table)
    justlike_table.setItemDelegateForRow(0, ref_delegate)

    item = justlike_table.item(0, 1)
    if item is None:
        item = QTableWidgetItem()
        item.setTextAlignment(Qt.AlignCenter)
        justlike_table.setItem(0, 1, item)
    current_text = item.text().strip() if item.text() else ""
    if current_text and current_text not in dialog._reference_pipe_id_map:
        item.setText("")

"""保存管口载荷数据到数据库（随输随存）"""
def save_pipe_load_data_to_db(product_id, pipe_id, pipe_code, local_stress_symbol, local_stress_calc_type):
    """
    保存管口载荷数据到产品设计活动库的产品设计活动表_管口载荷表
    :param product_id: 产品ID
    :param pipe_id: 管口ID
    :param pipe_code: 管口代号
    :param local_stress_symbol: 局部应力符号
    :param local_stress_calc_type: 局部应力计算类型
    """
    if not product_id or not pipe_id:
        print("[保存管口载荷] 产品ID或管口ID为空，跳过保存")
        return
    
    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config_2)
        cursor = conn.cursor()
        
        # 处理空值，如果为空则设为None
        pipe_code_val = pipe_code.strip() if pipe_code and pipe_code.strip() else None
        symbol_val = local_stress_symbol.strip() if local_stress_symbol and local_stress_symbol.strip() else None
        calc_type_val = local_stress_calc_type.strip() if local_stress_calc_type and local_stress_calc_type.strip() else None

        # 新表结构：参数名称/参数值键值存储
        # 先删除旧记录，再插入两条参数，避免唯一键不含“参数名称”时发生互相覆盖
        delete_sql = """
            DELETE FROM 产品设计活动表_管口载荷表
            WHERE 管口ID = %s AND 产品ID = %s
              AND 参数名称 IN ('局部应力符号', '局部应力计算类型')
        """
        cursor.execute(delete_sql, (pipe_id, product_id))

        insert_sql = """
            INSERT INTO 产品设计活动表_管口载荷表 
                (管口ID, 产品ID, 管口代号, 参数名称, 参数值)
            VALUES (%s, %s, %s, %s, %s)
        """

        payloads = [
            (pipe_id, product_id, pipe_code_val, "局部应力符号", symbol_val),
            (pipe_id, product_id, pipe_code_val, "局部应力计算类型", calc_type_val),
        ]
        cursor.executemany(insert_sql, payloads)
        conn.commit()
        
        #print(f"[保存管口载荷] 保存成功: 产品ID={product_id}, 管口ID={pipe_id}, 管口代号={pipe_code_val}, 局部应力符号={symbol_val}, 局部应力计算类型={calc_type_val}")
        
    except Exception as e:
        print(f"[ERROR] 保存管口载荷数据失败: {e}")
        import traceback
        traceback.print_exc()
        if conn:
            conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

"""保存管口载荷（随输随存）"""
# def save_pipe_load_data_by_table(product_id, pipe_id, pipe_code, table: QTableWidget, rows=None):
#     """
#     将指定行的“第一列参数名称 + 第二列参数值”写入数据库。
#     :param product_id: 产品ID
#     :param pipe_id: 管口ID
#     :param pipe_code: 管口代号
#     :param table: 局部应力数据输入表格
#     :param rows: 需要保存的行号列表；None 时默认保存前两行
#     """
#     if not product_id or not pipe_id or table is None:
#         print("[保存管口载荷] 参数不完整，跳过保存")
#         return
#
#     target_rows = rows if rows is not None else [0, 1]
#     pipe_code_val = pipe_code.strip() if pipe_code and pipe_code.strip() else None
#     payloads = []
#     param_names = []
#
#     for r in target_rows:
#         if r < 0 or r >= table.rowCount():
#             continue
#         name_item = table.item(r, 0)
#         value_item = table.item(r, 1)
#         param_name = name_item.text().strip() if name_item and name_item.text() else ""
#         if not param_name:
#             continue
#         param_value = value_item.text().strip() if value_item and value_item.text() else None
#         payloads.append((pipe_id, product_id, pipe_code_val, param_name, param_value))
#         param_names.append(param_name)
#
#     if not payloads:
#         return
#
#     conn = None
#     cursor = None
#     try:
#         conn = get_connection(**db_config_2)
#         cursor = conn.cursor()
#
#         placeholders = ",".join(["%s"] * len(param_names))
#         delete_sql = f"""
#             DELETE FROM 产品设计活动表_管口载荷表
#             WHERE 管口ID = %s AND 产品ID = %s
#               AND 参数名称 IN ({placeholders})
#         """
#         cursor.execute(delete_sql, [pipe_id, product_id, *param_names])
#
#         insert_sql = """
#             INSERT INTO 产品设计活动表_管口载荷表
#                 (管口ID, 产品ID, 管口代号, 参数名称, 参数值)
#             VALUES (%s, %s, %s, %s, %s)
#         """
#         cursor.executemany(insert_sql, payloads)
#         conn.commit()
#     except Exception as e:
#         print(f"[ERROR] 按表格保存管口载荷失败: {e}")
#         import traceback
#         traceback.print_exc()
#         if conn:
#             conn.rollback()
#     finally:
#         if cursor:
#             cursor.close()
#         if conn:
#             conn.close()
def save_pipe_load_data_by_table(product_id, pipe_id, pipe_code, table: QTableWidget, rows=None):
    """
    将指定行的“第一列参数名称 + 第二列参数值”写入数据库。
    :param product_id: 产品ID
    :param pipe_id: 管口ID
    :param pipe_code: 管口代号
    :param table: 局部应力数据输入表格
    :param rows: 需要保存的行号列表；None 时默认保存前两行
    """
    if not product_id or not pipe_id or table is None:
        print("[保存管口载荷] 参数不完整，跳过保存")
        return

    target_rows = rows if rows is not None else [0, 1]
    # 管口代号优先从产品设计活动表_管口表读取；若不存在再回退到界面传入值
    ui_pipe_code_val = pipe_code.strip() if (pipe_code and pipe_code.strip()) else None
    pipe_code_val = ui_pipe_code_val
    lookup_conn = None
    lookup_cursor = None
    try:
        lookup_conn = get_connection(**db_config_2)
        lookup_cursor = lookup_conn.cursor()
        lookup_cursor.execute("""
            SELECT 管口代号
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口ID = %s
            LIMIT 1
        """, (product_id, pipe_id))
        row = lookup_cursor.fetchone()
        db_pipe_code = (row.get("管口代号") or "").strip() if row else ""
        if db_pipe_code:
            pipe_code_val = db_pipe_code
    except Exception as e:
        print(f"[WARN] 读取管口表中的管口代号失败，回退界面值: {e}")
    finally:
        if lookup_cursor:
            try:
                lookup_cursor.close()
            except:
                pass
        if lookup_conn:
            try:
                lookup_conn.close()
            except:
                pass
    payloads = []
    param_names = []

    for r in target_rows:
        # 行号越界检查
        if r < 0 or r >= table.rowCount():
            continue

        # 获取单元格 item（QTableWidget 空单元格会返回 None）
        name_item = table.item(r, 0)
        value_item = table.item(r, 1)

        # 参数名称必须有效
        param_name = name_item.text().strip() if (name_item and name_item.text()) else ""
        if not param_name:
            continue

        # 参数值：空字符串转为 None，方便数据库存储 NULL
        param_value = value_item.text().strip() if (value_item and value_item.text()) else None
        param_value = param_value if param_value else None

        payloads.append((pipe_id, product_id, pipe_code_val, param_name, param_value))
        param_names.append(param_name)

    if not payloads:
        print("[保存管口载荷] 无有效数据需要保存")
        return

    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config_2)
        cursor = conn.cursor()

        # ============== 修复 BUG：动态生成 IN 占位符 ==============
        param_placeholders = ", ".join(["%s"] * len(param_names))
        delete_sql = f"""
            DELETE FROM 产品设计活动表_管口载荷表
            WHERE 管口ID = %s AND 产品ID = %s
              AND 参数名称 IN ({param_placeholders})
        """
        # 拼接参数：[管口ID, 产品ID, 参数1, 参数2, ...]
        delete_params = [pipe_id, product_id] + param_names
        cursor.execute(delete_sql, delete_params)

        # 批量插入
        insert_sql = """
            INSERT INTO 产品设计活动表_管口载荷表
                (管口ID, 产品ID, 管口代号, 参数名称, 参数值)
            VALUES (%s, %s, %s, %s, %s)
        """
        cursor.executemany(insert_sql, payloads)

        conn.commit()
        print(f"[保存管口载荷] 成功保存 {len(payloads)} 条数据")

    except Exception as e:
        print(f"[ERROR] 按表格保存管口载荷失败: {str(e)}")
        import traceback
        traceback.print_exc()
        if conn:
            conn.rollback()
    finally:
        # 安全关闭游标和连接
        if cursor:
            try:
                cursor.close()
            except:
                pass
        if conn:
            try:
                conn.close()
            except:
                pass

"""保存第二个tab页的载荷参数数据到数据库"""
def save_second_tab_load_params_to_db(dialog: QDialog, product_id: int, pipe_id: int):
    """
    保存第二个tab页表格的数据到产品设计活动库的产品设计活动库_管口载荷表
    根据第一列的参数名称（字段名）和第二列的数值，更新对应的字段
    :param dialog: 对话框实例
    :param product_id: 产品ID
    :param pipe_id: 管口ID
    """
    if not dialog or not product_id or not pipe_id:
        print("[保存第二个tab页载荷参数] 参数不完整，跳过保存")
        return
    
    # 获取第二个tab页的表格
    table: QTableWidget = dialog.findChild(QTableWidget, "zaihecanshu")
    if not table:
        print("[保存第二个tab页载荷参数] 未找到zaihecanshu控件")
        return
    
    # 获取管口代号，作为记录中的冗余字段一并保存
    # 优先从产品设计活动表_管口表按 产品ID+管口ID 获取；查不到再回退界面值
    pipe_code = None
    parent_stats = dialog.parent()
    if parent_stats and hasattr(parent_stats, "lineEdit_productpipeCode"):
        try:
            pipe_code = parent_stats.lineEdit_productpipeCode.text().strip()
        except Exception:
            pipe_code = None

    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config_2)
        cursor = conn.cursor()

        # 优先读取数据库中的最新管口代号
        cursor.execute("""
            SELECT 管口代号
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口ID = %s
            LIMIT 1
        """, (product_id, pipe_id))
        row = cursor.fetchone()
        db_pipe_code = (row.get("管口代号") or "").strip() if row else ""
        if db_pipe_code:
            pipe_code = db_pipe_code

        payloads = []
        param_names = []

        for row in range(table.rowCount()):
            param_item = table.item(row, 0)
            if not param_item:
                continue

            param_name = param_item.text().strip()
            if not param_name:
                continue

            value_item = table.item(row, 1)
            value_text = value_item.text().strip() if value_item else ""
            param_value = value_text if value_text else None

            payloads.append((pipe_id, product_id, pipe_code, param_name, param_value))
            param_names.append(param_name)

        if not payloads:
            print("[保存第二个tab页载荷参数] 没有需要更新的数据")
            return

        param_placeholders = ", ".join(["%s"] * len(param_names))
        delete_sql = f"""
            DELETE FROM 产品设计活动表_管口载荷表
            WHERE 管口ID = %s AND 产品ID = %s
              AND 参数名称 IN ({param_placeholders})
        """
        delete_params = [pipe_id, product_id] + param_names
        cursor.execute(delete_sql, delete_params)

        insert_sql = """
            INSERT INTO 产品设计活动表_管口载荷表
                (管口ID, 产品ID, 管口代号, 参数名称, 参数值)
            VALUES (%s, %s, %s, %s, %s)
        """
        cursor.executemany(insert_sql, payloads)
        conn.commit()

        print(f"[保存第二个tab页载荷参数] 成功保存 {len(payloads)} 条参数: 产品ID={product_id}, 管口ID={pipe_id}")
        show_styled_message(dialog, "提示", "保存成功！", icon=QMessageBox.Information)

    except Exception as e:
        print(f"[ERROR] 保存第二个tab页载荷参数失败: {e}")
        import traceback
        traceback.print_exc()
        if conn:
            conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

"""切换局部应力计算类型时，清空第二个界面参数记录"""
def clear_second_tab_params_in_db(product_id: int, pipe_id: int):
    """
    删除当前管口在载荷表中的第二界面（zaihecanshu）及 justlike 中的载荷作用位置等，
    仅保留第一页 yinglijisuan 的两项：
    - 局部应力符号
    - 局部应力计算类型
    （载荷作用位置在第二套 UI 中，切换计算类型后一并清除，需用户在第二界面点确认重新保存）
    """
    if not product_id or not pipe_id:
        return

    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config_2)
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM 产品设计活动表_管口载荷表
            WHERE 产品ID = %s AND 管口ID = %s
              AND 参数名称 NOT IN ('局部应力符号', '局部应力计算类型')
        """, (product_id, pipe_id))
        conn.commit()
    except Exception as e:
        print(f"[ERROR] 清空第二界面参数失败: {e}")
        if conn:
            conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# 与 setup_justlike_table 中第2行第2列默认文案一致
_DEFAULT_LOAD_POSITION_TEXT = "载荷作用于接管顶部"
# 第二个页面固定规则：该参数默认值恒为 0，且不可编辑
_FIXED_ZERO_ANGLE_PARAM_KEYWORD = "两坐标系之夹角(°)"


def _is_fixed_zero_angle_param(param_name: str) -> bool:
    """判断是否为第二个页面中固定为 0 的角度参数。"""
    text = (param_name or "").strip()
    if not text:
        return False
    # 容错：参数名可能带空格、单位（如“(°)”）或全角括号，统一归一化后做包含匹配
    normalized = (
        text.replace(" ", "")
        .replace("\u3000", "")
        .replace("（", "(")
        .replace("）", ")")
    )
    keyword = (
        _FIXED_ZERO_ANGLE_PARAM_KEYWORD.replace(" ", "")
        .replace("\u3000", "")
        .replace("（", "(")
        .replace("）", ")")
    )
    return keyword in normalized


def _set_fixed_zero_angle_cell_style(item: QTableWidgetItem):
    """将目标单元格设置为默认值 0、灰底、不可编辑。"""
    if item is None:
        return
    item.setText("0")
    item.setTextAlignment(Qt.AlignCenter)
    item.setFlags(item.flags() & ~Qt.ItemIsEditable & ~Qt.ItemIsSelectable)
    item.setBackground(QBrush(QColor(240, 240, 240)))


def reset_justlike_load_position_to_default(dialog: QDialog):
    """切换局部应力计算类型时，将 justlike 表中「载荷作用位置」恢复为默认值。"""
    if not dialog:
        return
    table = dialog.findChild(QTableWidget, "justlike")
    if not table or table.rowCount() < 2:
        return
    item = table.item(1, 1)
    if item is None:
        item = QTableWidgetItem(_DEFAULT_LOAD_POSITION_TEXT)
        item.setTextAlignment(Qt.AlignCenter)
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
        table.setItem(1, 1, item)
    else:
        item.setText(_DEFAULT_LOAD_POSITION_TEXT)


def clear_zaihecanshu_parameter_values(dialog: QDialog):
    """清空第二个界面 zaihecanshu 表格第二列（参数值），行结构由 fill_load_params_by_calc_type 决定。"""
    if not dialog:
        return
    table = dialog.findChild(QTableWidget, "zaihecanshu")
    if not table:
        return
    for row in range(table.rowCount()):
        name_item = table.item(row, 0)
        param_name = name_item.text().strip() if name_item and name_item.text() else ""
        item = table.item(row, 1)
        if item is None:
            item = QTableWidgetItem()
            item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 1, item)
        if _is_fixed_zero_angle_param(param_name):
            _set_fixed_zero_angle_cell_style(item)
        else:
            item.setText("")
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
            item.setBackground(QBrush(QColor(255, 255, 255)))


"""设置第二个tab页的justlike表格（参考引用）"""
def setup_justlike_table(dialog: QDialog):
    """
    对第二个tab页的justlike表格进行设置：
    - 只显示两行，不显示多余空白
    - 第一列显示"参考引用"，不可编辑
    - 第二列与radioButton联动，控制可编辑状态
    """
    if dialog is None:
        return

    # 获取justlike表格
    table: QTableWidget = dialog.findChild(QTableWidget, "justlike")
    if not table:
        print("[设置justlike表格] 未找到justlike控件")
        return

    # 设置表格只显示2行
    table.setRowCount(2)
    
    # 设置行高为40
    row_height = 40
    table.setRowHeight(0, row_height)
    table.setRowHeight(1, row_height)
    
    # 设置垂直标题头为固定模式
    if table.verticalHeader():
        table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
    
    # 禁用垂直滚动条
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    
    # 设置第一列（索引0）：第1行显示"参考引用"，不可编辑、不可选中
    item_col0 = table.item(0, 0)
    if item_col0 is None:
        item_col0 = QTableWidgetItem("参考引用")
        table.setItem(0, 0, item_col0)
    else:
        item_col0.setText("参考引用")
    item_col0.setFlags(item_col0.flags() & ~Qt.ItemIsEditable & ~Qt.ItemIsSelectable)
    #item_col0.setBackground(QBrush(QColor(240, 240, 240)))

    # 设置第一列（索引0）：第2行显示"载荷作用位置"，不可编辑、不可选中
    item_row1_col0 = table.item(1, 0)
    if item_row1_col0 is None:
        item_row1_col0 = QTableWidgetItem("载荷作用位置")
        table.setItem(1, 0, item_row1_col0)
    else:
        item_row1_col0.setText("载荷作用位置")
    item_row1_col0.setFlags(item_row1_col0.flags() & ~Qt.ItemIsEditable & ~Qt.ItemIsSelectable)
    
    # 设置第二列（索引1）：第1行初始不可编辑、不可选中，与radioButton联动
    item_col1 = table.item(0, 1)
    if item_col1 is None:
        item_col1 = QTableWidgetItem()
        table.setItem(0, 1, item_col1)
    item_col1.setFlags(item_col1.flags() & ~Qt.ItemIsEditable & ~Qt.ItemIsSelectable)
    #item_col1.setBackground(QBrush(QColor(240, 240, 240)))

    # 设置第二列（索引1）：第2行采用与管口定义一致风格的下拉框委托
    load_position_options = ["载荷作用于接管根部", "载荷作用于接管顶部"]
    load_position_delegate = LocalStressCalcTypeComboDelegate(
        table, options=load_position_options, target_row=1, target_col=1
    )
    load_position_delegate.setParent(table)
    table.setItemDelegateForRow(1, load_position_delegate)

    # 第2行第2列默认值：载荷作用于接管顶部
    item_row1_col1 = table.item(1, 1)
    if item_row1_col1 is None:
        item_row1_col1 = QTableWidgetItem("载荷作用于接管顶部")
        table.setItem(1, 1, item_row1_col1)
    else:
        item_row1_col1.setText("载荷作用于接管顶部")
    item_row1_col1.setTextAlignment(Qt.AlignCenter)
    item_row1_col1.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)

    # 单击第2行第2列时直接展开下拉
    def  on_justlike_cell_clicked(clicked_row, clicked_col):
        if clicked_row == 1 and clicked_col == 1:
            target_item = table.item(1, 1)
            if target_item is None:
                target_item = QTableWidgetItem("载荷作用于接管顶部")
                target_item.setTextAlignment(Qt.AlignCenter)
                target_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                table.setItem(1, 1, target_item)
            table.editItem(target_item)
        elif clicked_row == 0 and clicked_col == 1:
            # 仅在“参考引用”被启用时允许下拉选择参考管口代号
            if getattr(dialog, "_first_row_editable", False):
                target_item = table.item(0, 1)
                if target_item is None:
                    target_item = QTableWidgetItem()
                    target_item.setTextAlignment(Qt.AlignCenter)
                    target_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                    table.setItem(0, 1, target_item)
                table.editItem(target_item)

    try:
        table.cellClicked.disconnect(table._justlike_click_handler)
    except Exception:
        pass
    table._justlike_click_handler = on_justlike_cell_clicked
    table.cellClicked.connect(table._justlike_click_handler)
    
    # 设置列宽：第一列固定宽度360，第二列可以拉伸自适应
    table.setColumnWidth(0, 430)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
    
    if table.columnCount() > 1:
        table.setColumnWidth(1, 120)  # 设置初始宽度
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
    
    # 禁止水平滚动条
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    
    # 设置表格固定高度，只显示两行
    total_height = row_height * 2 + 2  # 两行行高 + 边框
    table.setFixedHeight(total_height)
    
    # 设置表格大小策略：高度固定，宽度可扩展
    table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    
    # 设置表格最小宽度
    min_width = 360 + 135
    table.setMinimumWidth(min_width)

"""设置第二个tab页的zaihecanshu表格"""
def setup_second_tab_table(dialog: QDialog):
    """
    对第二个tab页的表格（zaihecanshu）进行设置：
    - 第一列列宽设为430
    - 第二列列宽设为120
    - 行高设为40（和第一个tab页一样）
    """
    if dialog is None:
        return

    # 第二个 Tab 的表格名为 zaihecanshu
    table: QTableWidget = dialog.findChild(QTableWidget, "zaihecanshu")
    if not table:
        print("[设置第二个tab页表格] 未找到zaihecanshu控件")
        return

    # 布局修正：去掉 justlike 与 zaihecanshu 之间的弹簧，避免表格被压到下方
    parent_layout = dialog.findChild(QVBoxLayout, "verticalLayout_4")
    if parent_layout:
        i = 0
        while i < parent_layout.count():
            item = parent_layout.itemAt(i)
            if item and item.spacerItem() is not None:
                parent_layout.takeAt(i)
                continue
            i += 1
        parent_layout.setSpacing(8)
        parent_layout.setAlignment(Qt.AlignTop)

    # 第二列（参数值）统一限制为数值输入
    table.setItemDelegateForColumn(1, NumericValueDelegate(table))

    # 获取行数并固定每行高度（不拉伸）
    row_count = table.rowCount()
    fixed_row_height = 40
    for r in range(row_count):
        table.setRowHeight(r, fixed_row_height)
    if table.verticalHeader():
        table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)

    # 高度随行数动态变化：有几行就显示几行
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    total_height = fixed_row_height * row_count + 2  # 行高总和 + 边框
    table.setFixedHeight(total_height)
    
    # 现在zaihecanshu表从第一行开始就是参数行（参考引用已移到justlike表）
    for row in range(table.rowCount()):
        # 第一列：不可编辑、不可选中
        item = table.item(row, 0)
        if item is None:
            # 如果单元格不存在，创建一个
            item = QTableWidgetItem()
            table.setItem(row, 0, item)
        # 移除可编辑和可选中标志，只保留可启用（参考第一个tab页的实现）
        item.setFlags(item.flags() & ~Qt.ItemIsEditable & ~Qt.ItemIsSelectable)
        
        # 第二列：设置输入居中（如果item已存在，设置对齐方式）
        item_col1 = table.item(row, 1)
        if item_col1 is not None:
            item_col1.setTextAlignment(Qt.AlignCenter)

    # 设置列宽：第一列固定宽度430，第二列可以拉伸自适应（参考第一个tab页的实现）
    # 第一列设置为固定宽度模式
    table.setColumnWidth(0, 430)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
    
    # 第二列设置为拉伸模式，可以自适应对话框宽度变化
    if table.columnCount() > 1:
        table.setColumnWidth(1, 120)  # 设置初始宽度
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

    # 禁止水平滚动条
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    
    # 设置表格大小策略：宽度可扩展，高度固定为按行数计算后的高度
    table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    
    # 设置表格最小尺寸（宽度最小为两列最小宽度之和，高度为所有行高度之和）
    min_width = 360 + 135  # 第一列360 + 第二列最小135
    min_height = total_height
    table.setMinimumSize(min_width, min_height)
    # 不设置最大宽度，允许水平扩展；高度固定为当前行数对应高度
    table.setMaximumSize(16777215, total_height)  # 16777215是Qt的最大整数值



"""初始化管口载荷弹窗"""
def init_pipe_openingload_dialog(dialog: QDialog, pipe_code: str = None, product_id: int = None, pipe_id: int = None) -> None:
    """
    对管口载荷弹窗（pipe_openingload.ui）做统一初始化：
    - 第一个 Tab 左侧表格（yinglijisuan）：设置列宽，第一列最小设为180，第二列设为400。
    - 第一列设置为不可编辑、不可选中（参考 dynamically_adjust_ui.py 的设置表格形式函数的逻辑）
    - UI文件设定的表格为两行，界面里也只显示两行
    """
    if dialog is None:
        return

    # 移除layoutWidget的固定geometry，让它使用布局管理以实现自适应
    layout_widget = dialog.findChild(QWidget, "layoutWidget")
    if layout_widget:
        # 移除固定geometry，让布局管理器控制大小
        layout_widget.setGeometry(0, 0, 0, 0)
        # 设置大小策略，允许扩展
        layout_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    
    # 设置图片widget的大小策略，允许扩展
    image_widget = dialog.findChild(QWidget, "img_load")
    if image_widget:
        image_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    # 第一个 Tab 左侧表格名为 yinglijisuan
    table: QTableWidget = dialog.findChild(QTableWidget, "yinglijisuan")
    if not table:
        return


    # 显式设定每一行行高为 40
    row_height = 40

    for r in range(table.rowCount()):
        table.setRowHeight(r, row_height)

    # 禁用垂直滚动条，确保只显示2行
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    # 设置表格固定高度，使其刚好显示2行
    # 计算表格总高度：2行高度
    total_height = row_height * 2+2
    table.setFixedHeight(total_height)

    # 参考 dynamically_adjust_ui.py 中 setup_tableWidget_pipe_header 的逻辑
    # 设置第一列的所有单元格为不可编辑、不可选中
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        if item is None:
            # 如果单元格不存在，创建一个
            item = QTableWidgetItem()
            table.setItem(row, 0, item)
        # 移除可编辑和可选中标志，只保留可启用（参考 dynamically_adjust_ui.py 第504行）
        item.setFlags(item.flags() & ~Qt.ItemIsEditable & ~Qt.ItemIsSelectable)
    
    # 设置列宽：第一列固定宽度200，第二列可以拉伸自适应
    # 第一列设置为固定宽度模式
    table.setColumnWidth(0, 200)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
    
    # 第二列设置为拉伸模式，可以自适应对话框宽度变化
    if table.columnCount() > 1:
        table.setColumnWidth(1, 500)  # 设置初始宽度
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

    # 禁止水平滚动条，视觉更干净
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    # 设置表格大小策略：高度固定，宽度可扩展
    table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    
    # 设置表格最小尺寸（宽度最小为两列最小宽度之和，高度固定）
    min_width = 180 + 400  # 第一列180 + 第二列最小400
    table.setMinimumSize(min_width, total_height)
    # 不设置最大宽度，允许水平扩展
    table.setMaximumSize(16777215, total_height)  # 16777215是Qt的最大整数值
    
    # 设置第二个tab页的justlike表格（参考引用表）
    setup_justlike_table(dialog)
    #设置参数表格
    setup_second_tab_table(dialog)
    # 初始化兜底：若 UI 设计时已预置了参数行，先应用一次“夹角=0、灰色、不可编辑”规则
    clear_zaihecanshu_parameter_values(dialog)

    # # 注意：zaihecanshu表格的基础设置会在fill_load_params_by_calc_type之后进行
    # # 因为需要先填充数据才能知道表格需要多少行
    # # 但先进行基础的表格初始化，确保表格存在
    # zaihecanshu_table = dialog.findChild(QTableWidget, "zaihecanshu")
    # if zaihecanshu_table:
    #     # 只设置基础属性，不设置行高和列宽（这些会在fill_load_params_by_calc_type之后设置）
    #     zaihecanshu_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    #     zaihecanshu_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    #     if zaihecanshu_table.verticalHeader():
    #         zaihecanshu_table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)

    # 为第二行第二列（索引1,1）设置局部应力计算类型下拉框
    # 读取局部应力计算类型选项
    calc_types = get_local_stress_calc_types_from_db()

    # 创建下拉框代理
    combo_delegate = LocalStressCalcTypeComboDelegate(table, options=calc_types)
    combo_delegate.setParent(table)

    # 为第二行第二列设置下拉框代理（第二行索引为1，第二列索引为1）
    table.setItemDelegateForColumn(1, combo_delegate)

    # 设置默认值变量
    default_value = "柱壳上圆形附件或接管计算(WRC 537)"
    dialog._last_calc_type_value = default_value

    # 连接单元格点击信号，实现单击即可显示下拉框
    def on_cell_clicked(row, column):
        """处理单元格点击事件，第二行第二列单击时立即进入编辑模式"""
        if row == 1 and column == 1:
            # 确保item存在
            target_item = table.item(1, 1)
            if target_item is None:
                target_item = QTableWidgetItem(default_value)
                target_item.setTextAlignment(Qt.AlignCenter)
                target_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                table.setItem(1, 1, target_item)
            elif not target_item.text().strip():
                # 如果item存在但为空，设置默认值
                target_item.setText(default_value)
            # 立即进入编辑模式，显示下拉框
            table.editItem(target_item)

    table.cellClicked.connect(on_cell_clicked)
    
    # 连接单元格变化信号，实现局部应力计算类型与图片的联动，以及随输随存
    def on_cell_changed(row, column):
        """处理单元格内容变化事件"""
        # 处理局部应力计算类型与图片的联动（第二行第二列，索引1,1）
        if row == 1 and column == 1:
            item = table.item(1, 1)
            if item:
                calc_type = item.text().strip()
                if calc_type:
                    prev_calc_type = getattr(dialog, "_last_calc_type_value", "")
                    calc_type_switched = prev_calc_type != calc_type
                    # 当局部应力计算类型发生切换时：清库（仅保留第一页两项）、载荷作用位置恢复默认
                    if calc_type_switched:
                        if product_id and pipe_id:
                            clear_second_tab_params_in_db(product_id, pipe_id)
                        reset_justlike_load_position_to_default(dialog)
                    dialog._last_calc_type_value = calc_type

                    # 显示对应的载荷示意图（第一个tab页）
                    display_load_image(dialog, calc_type)
                    # 显示对应的载荷计算图（第二个tab页）
                    display_load_calc_image(dialog, calc_type)
                    # 更新第二个tab页的名称
                    update_second_tab_name(dialog, calc_type)
                    # 填充对应的参数到第二个tab页表格第一列
                    fill_load_params_by_calc_type(dialog, calc_type)
                    if calc_type_switched:
                        clear_zaihecanshu_parameter_values(dialog)
                    # 计算类型变化后，刷新“参考引用”可选管口代号
                    if product_id and pipe_id:
                        refresh_reference_pipe_dropdown(dialog, product_id, pipe_id)
                    # 切换类型时，将radioButton设为未选中（False），使第一行第二列默认禁用
                    # 直接设置，让信号正常触发，这样toggle函数会被调用，确保状态正确
                    radio_btn = dialog.findChild(QRadioButton, "justlike_btn")
                    if radio_btn:
                        radio_btn.setChecked(False)
                else:
                    # 如果为空，清空图片显示（第一个tab页）
                    image_widget = dialog.findChild(QWidget, "img_load")
                    if image_widget:
                        image_widget.setStyleSheet("background-color: rgb(255, 255, 255);")
                        label = image_widget.findChild(QLabel)
                        if label:
                            label.clear()
                    # 如果为空，清空图片显示（第二个tab页）
                    image_widget_param = dialog.findChild(QWidget, "img_loadParameter")
                    if image_widget_param:
                        image_widget_param.setStyleSheet("background-color: rgb(255, 255, 255);")
                        label_param = image_widget_param.findChild(QLabel)
                        if label_param:
                            label_param.clear()
                    # 如果为空，将tab页名称设置为默认值"1"
                    update_second_tab_name(dialog, default_value)
                    # 填充默认值对应的参数到第二个tab页表格第一列
                    fill_load_params_by_calc_type(dialog, default_value)
                    # 显示默认值对应的载荷计算图（第二个tab页）
                    display_load_calc_image(dialog, default_value)
        
        # 第一页 yinglijisuan 随输随存：只写「局部应力符号」「局部应力计算类型」两行（与 1461-1465 一致）
        if (row == 0 and column == 1) or (row == 1 and column == 1):
            if product_id and pipe_id:
                save_pipe_load_data_by_table(product_id, pipe_id, pipe_code, table, rows=[0, 1])

    table.cellChanged.connect(on_cell_changed)
    
    # 从数据库加载已有数据（在连接cellChanged信号之后，先阻止信号触发，避免加载时触发保存）
    table.blockSignals(True)
    try:
        if product_id and pipe_id:
            loaded_data = load_pipe_load_data_from_db(product_id, pipe_id)
            if loaded_data:
                # 回填“载荷作用位置”（justlike表第2行第2列）
                justlike_table = dialog.findChild(QTableWidget, "justlike")
                if justlike_table and justlike_table.rowCount() > 1:
                    load_pos_item = justlike_table.item(1, 1)
                    load_pos_text = loaded_data.get("载荷作用位置") or "载荷作用于接管顶部"
                    if load_pos_item is None:
                        load_pos_item = QTableWidgetItem(load_pos_text)
                        load_pos_item.setTextAlignment(Qt.AlignCenter)
                        load_pos_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                        justlike_table.setItem(1, 1, load_pos_item)
                    else:
                        load_pos_item.setText(load_pos_text)

                # 如果数据库中有数据，优先使用数据库中的数据
                # 设置局部应力符号（第0行第1列）
                if loaded_data.get("局部应力符号"):
                    symbol_item = table.item(0, 1)
                    if symbol_item is None:
                        symbol_item = QTableWidgetItem(loaded_data["局部应力符号"])
                        symbol_item.setTextAlignment(Qt.AlignCenter)
                        symbol_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                        table.setItem(0, 1, symbol_item)
                    else:
                        symbol_item.setText(loaded_data["局部应力符号"])
                else:
                    # 如果数据库中没有局部应力符号，根据管口代号设置默认值
                    if pipe_code:
                        set_local_stress_symbol_by_pipe_code(dialog, pipe_code)
                
                # 获取当前的局部应力符号（用于后续保存）
                symbol_item = table.item(0, 1)
                current_symbol = symbol_item.text().strip() if symbol_item else ""
                
                # 设置局部应力计算类型（第1行第1列）
                if loaded_data.get("局部应力计算类型"):
                    calc_type_item = table.item(1, 1)
                    if calc_type_item is None:
                        calc_type_item = QTableWidgetItem(loaded_data["局部应力计算类型"])
                        calc_type_item.setTextAlignment(Qt.AlignCenter)
                        calc_type_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                        table.setItem(1, 1, calc_type_item)
                    else:
                        calc_type_item.setText(loaded_data["局部应力计算类型"])
                    # 显示对应的图片（第一个tab页）
                    display_load_image(dialog, loaded_data["局部应力计算类型"])
                    # 显示对应的载荷计算图（第二个tab页）
                    display_load_calc_image(dialog, loaded_data["局部应力计算类型"])
                    # 更新第二个tab页的名称
                    update_second_tab_name(dialog, loaded_data["局部应力计算类型"])
                    # 填充对应的参数到第二个tab页表格第一列
                    fill_load_params_by_calc_type(dialog, loaded_data["局部应力计算类型"])
                    # 加载第二个tab页的参数值（如果数据库中有值）
                    load_second_tab_params_from_db(dialog, product_id, pipe_id)
                    # 如果局部应力符号是刚设置的默认值，需要保存到数据库
                    if not loaded_data.get("局部应力符号") and current_symbol:
                        save_pipe_load_data_by_table(product_id, pipe_id, pipe_code, table, rows=[0, 1])
                else:
                    # 如果数据库中没有局部应力计算类型，使用默认值并保存到数据库
                    calc_type_item = table.item(1, 1)
                    if calc_type_item is None:
                        calc_type_item = QTableWidgetItem(default_value)
                        calc_type_item.setTextAlignment(Qt.AlignCenter)
                        calc_type_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                        table.setItem(1, 1, calc_type_item)
                    else:
                        calc_type_item.setText(default_value)
                    # 显示默认值对应的图片（第一个tab页）
                    display_load_image(dialog, default_value)
                    # 显示默认值对应的载荷计算图（第二个tab页）
                    display_load_calc_image(dialog, default_value)
                    # 更新第二个tab页的名称为默认值对应的编号
                    update_second_tab_name(dialog, default_value)
                    # 填充默认值对应的参数到第二个tab页表格第一列
                    fill_load_params_by_calc_type(dialog, default_value)
                    # 加载第二个tab页的参数值（如果数据库中有值）
                    load_second_tab_params_from_db(dialog, product_id, pipe_id)
                    # 保存默认值到数据库（如果之前没有记录，或者局部应力符号是默认值）
                    if current_symbol:
                        save_pipe_load_data_by_table(product_id, pipe_id, pipe_code, table, rows=[0, 1])
            else:
                # 如果数据库中没有数据，使用默认值并保存到数据库
                # 根据管口代号设置局部应力符号的默认值
                local_stress_symbol = ""
                if pipe_code:
                    set_local_stress_symbol_by_pipe_code(dialog, pipe_code)
                    # 获取设置后的局部应力符号
                    symbol_item = table.item(0, 1)
                    local_stress_symbol = symbol_item.text().strip() if symbol_item else ""

                # 设置局部应力计算类型默认值
                calc_type_item = table.item(1, 1)
                if calc_type_item is None:
                    calc_type_item = QTableWidgetItem(default_value)
                    calc_type_item.setTextAlignment(Qt.AlignCenter)
                    calc_type_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                    table.setItem(1, 1, calc_type_item)
                else:
                    calc_type_item.setText(default_value)
                # 显示默认值对应的图片（第一个tab页）
                display_load_image(dialog, default_value)
                # 显示默认值对应的载荷计算图（第二个tab页）
                display_load_calc_image(dialog, default_value)
                # 更新第二个tab页的名称为默认值对应的编号
                update_second_tab_name(dialog, default_value)
                # 填充默认值对应的参数到第二个tab页表格第一列
                fill_load_params_by_calc_type(dialog, default_value)
                # 加载第二个tab页的参数值（如果数据库中有值）
                load_second_tab_params_from_db(dialog, product_id, pipe_id)

                # 将默认值保存到数据库
                save_pipe_load_data_by_table(product_id, pipe_id, pipe_code, table, rows=[0, 1])

                justlike_table = dialog.findChild(QTableWidget, "justlike")
                if justlike_table and justlike_table.rowCount() > 1:
                    load_pos_item = justlike_table.item(1, 1)
                    load_pos_text = "载荷作用于接管顶部"
                    if load_pos_item is None:
                        load_pos_item = QTableWidgetItem(load_pos_text)
                        load_pos_item.setTextAlignment(Qt.AlignCenter)
                        load_pos_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                        justlike_table.setItem(1, 1, load_pos_item)
                    else:
                        load_pos_item.setText(load_pos_text)
        else:
            # 如果product_id或pipe_id为空，使用默认值
            if pipe_code:
                set_local_stress_symbol_by_pipe_code(dialog, pipe_code)
            # 设置局部应力计算类型默认值
            calc_type_item = table.item(1, 1)
            if calc_type_item is None:
                calc_type_item = QTableWidgetItem(default_value)
                calc_type_item.setTextAlignment(Qt.AlignCenter)
                calc_type_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                table.setItem(1, 1, calc_type_item)
            else:
                calc_type_item.setText(default_value)
            # 显示默认值对应的图片（第一个tab页）
            display_load_image(dialog, default_value)
            # 显示默认值对应的载荷计算图（第二个tab页）
            display_load_calc_image(dialog, default_value)
            # 更新第二个tab页的名称为默认值对应的编号
            update_second_tab_name(dialog, default_value)
            # 填充默认值对应的参数到第二个tab页表格第一列
            fill_load_params_by_calc_type(dialog, default_value)
        # 与界面实际「局部应力计算类型」同步，避免切换时误判未变化而不清空第二界面
        ct_item = table.item(1, 1)
        dialog._last_calc_type_value = ct_item.text().strip() if ct_item and ct_item.text() else default_value
    finally:
        # 恢复信号连接
        table.blockSignals(False)

    # 初始化（或刷新）“参考引用”下拉数据源
    if product_id and pipe_id:
        refresh_reference_pipe_dropdown(dialog, product_id, pipe_id)
    
    # 设置第一个tab页的引用功能：与radioButton联动，控制justlike表格第一行的可编辑状态
    # 获取radioButton和justlike表格
    radio_btn = dialog.findChild(QRadioButton, "justlike_btn")
    justlike_table = dialog.findChild(QTableWidget, "justlike")
    if radio_btn and justlike_table:
        # 创建一个bool变量来跟踪状态，初始为False（不可编辑）
        dialog._first_row_editable = False
        
        def toggle_first_row_editable(checked):
            """切换justlike表格第一行的可编辑状态和背景色（第一列始终保持不可编辑，但背景色联动）"""
            dialog._first_row_editable = checked
            # 重新获取justlike表格，确保能访问到最新的表格状态
            table = dialog.findChild(QTableWidget, "justlike")
            if not table or table.rowCount() == 0:
                return
            
            # 处理第一行的所有列
            for col in range(table.columnCount()):
                item = table.item(0, col)
                if item is None:
                    item = QTableWidgetItem()
                    table.setItem(0, col, item)
                
                if checked:
                    # 背景色改为白色（整个第一行联动）
                    #item.setBackground(QBrush(QColor(255, 255, 255)))
                    # 第二列设为可编辑、可选中
                    if col == 1:
                        if product_id and pipe_id:
                            refresh_reference_pipe_dropdown(dialog, product_id, pipe_id)
                        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                    # 第一列始终保持不可编辑、不可选中
                    elif col == 0:
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable & ~Qt.ItemIsSelectable)
                else:
                    # 背景色改为浅灰色（整个第一行联动）
                    #item.setBackground(QBrush(QColor(240, 240, 240)))
                    # 第二列设为不可编辑、不可选中
                    if col == 1:
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable & ~Qt.ItemIsSelectable)
                        item.setText("")
                    # 第一列始终保持不可编辑、不可选中
                    elif col == 0:
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable & ~Qt.ItemIsSelectable)
        
        # 连接radioButton的toggled信号
        radio_btn.toggled.connect(toggle_first_row_editable)
        # 初始状态设为未选中（False），这会触发toggle函数，设置第一行为禁用状态
        radio_btn.setChecked(False)

    # 参考引用代号改变时，自动按同计算类型的参考管口回填当前参数
    if justlike_table:
        def on_justlike_cell_changed(row, col):
            if row != 0 or col != 1:
                return
            if not (product_id and pipe_id):
                return
            if not getattr(dialog, "_first_row_editable", False):
                return
            selected_item = justlike_table.item(0, 1)
            selected_code = selected_item.text().strip() if selected_item and selected_item.text() else ""
            if not selected_code:
                return
            ref_map = getattr(dialog, "_reference_pipe_id_map", {}) or {}
            ref_pipe_id = ref_map.get(selected_code)
            if not ref_pipe_id:
                return
            apply_reference_pipe_params(dialog, product_id, ref_pipe_id)

        try:
            justlike_table.cellChanged.disconnect(dialog._justlike_cell_changed_handler)
        except Exception:
            pass
        dialog._justlike_cell_changed_handler = on_justlike_cell_changed
        justlike_table.cellChanged.connect(dialog._justlike_cell_changed_handler)
    
    # 连接确认按钮的点击事件：统一保存第一tab、justlike和第二tab
    save_btn = dialog.findChild(QPushButton, "save_btn")
    if save_btn:
        def on_save_btn_clicked():
            """确认按钮点击事件处理函数"""
            if product_id and pipe_id:
                # 1) 保存第一个tab页（局部应力符号、局部应力计算类型）
                save_pipe_load_data_by_table(product_id, pipe_id, pipe_code, table, rows=[0, 1])

                # 2) 保存第一tab里的justlike表（载荷作用位置）
                justlike_table = dialog.findChild(QTableWidget, "justlike")
                if justlike_table:
                    save_pipe_load_data_by_table(product_id, pipe_id, pipe_code, justlike_table, rows=[1])

                # 3) 保存第二个tab页参数
                save_second_tab_load_params_to_db(dialog, product_id, pipe_id)
            else:
                print("[保存第二个tab页载荷参数] 产品ID或管口ID为空，无法保存")

        save_btn.clicked.connect(on_save_btn_clicked)
    else:
        print("[初始化管口载荷弹窗] 未找到确认按钮 save_btn")
