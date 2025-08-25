from PyQt5.QtWidgets import QDialog, QTableWidgetItem, QMessageBox, QInputDialog, QTableWidget, QHeaderView, QWidget, \
    QFormLayout, QPushButton, QHBoxLayout
from PyQt5.QtWidgets import QLineEdit, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5 import uic
import pymysql

from modules.guankoudingyi.db_cnt import get_connection

# 数据库配置
db_config = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '产品设计活动库'
}

# 自定义输入对话框
class CustomInputDialog(QDialog):
    inputAccepted = pyqtSignal(str)
    
    def __init__(self, parent=None, title="", prompt="", existing_names=None):
        super(CustomInputDialog, self).__init__(parent)
        self.setWindowTitle(title)
        self.setFixedWidth(350)  # 设置更宽的宽度
        self.existing_names = existing_names or []  #保存已有分类名称

        # 整体竖直布局
        main_layout = QVBoxLayout()

        # 添加提示标签
        label = QLabel(prompt)
        main_layout.addWidget(label)

        # 添加输入框
        self.line_edit = QLineEdit()
        main_layout.addWidget(self.line_edit)

        # 创建按钮横向布局，并右对齐
        button_layout = QHBoxLayout()
        button_layout.addStretch()  # 添加弹性空间把按钮推到右侧

        # ✅ 添加确认按钮
        confirm_button = QPushButton("确认")
        confirm_button.setFixedWidth(self.width() // 3)  # 宽度约为输入框的三分之一
        confirm_button.setStyleSheet("background-color: rgb(249, 249, 249);")
        button_layout.addWidget(confirm_button)

        # 添加按钮布局到底部
        main_layout.addLayout(button_layout)

        # 设置布局
        self.setLayout(main_layout)

        # ✅ 让按钮响应回车键（Enter）
        confirm_button.setAutoDefault(True)
        confirm_button.setDefault(True)

        # 连接回车键事件——回车添加新的分类名
        # self.line_edit.returnPressed.connect(self.accept_input)
        confirm_button.clicked.connect(self.accept_input)  # ✅ 点击确认也触发输入提交

    def accept_input(self):
        """当用户按下回车键时触发"""
        text = self.line_edit.text().strip()
        if not text:
            QMessageBox.warning(self, "提示", "分类名称不能为空！")
            return
        if text in self.existing_names:
            QMessageBox.warning(self, "提示", f"分类名称“{text}”已存在，请重新输入")
            # self.line_edit.clear()
            return
        self.inputAccepted.emit(text)
        self.accept()

    def get_text(self):
        """获取输入的文本"""
        return self.line_edit.text()


class PipeMaterialDistribution(QDialog):
    def __init__(self, parent=None, product_id=None):
        super(PipeMaterialDistribution, self).__init__(parent)
        # 加载UI
        uic.loadUi("modules/guankoudingyi/ui/pipe_material_distri.ui", self)
        
        # 保存产品ID
        self.product_id = product_id
        
        # 设置窗口标题
        self.setWindowTitle("管口材料分类")
        
        # 初始化左侧管口列表
        self.init_pipe_code_list()
        
        # 绑定按钮事件
        self.pushButton_right.clicked.connect(self.move_to_right)
        self.pushButton_left.clicked.connect(self.move_to_left)
        self.pushButton.clicked.connect(self.add_classification)
        self.pushButton_2.clicked.connect(self.delete_classification)
        self.pushButton_3.clicked.connect(self.save_and_close)

    def init_pipe_code_list(self):
        """初始化左侧管口代号列表及右侧分类表"""
        try:
            # 连接数据库
            conn = get_connection(**db_config)
            cursor = conn.cursor()
            
            # 查询已经分类的管口代号
            classified_query = """
                SELECT 管口代号, 类别
                FROM 产品设计活动表_管口类别表
                WHERE 产品ID = %s
                ORDER BY 类别
            """
            cursor.execute(classified_query, (self.product_id,))
            classified_results = cursor.fetchall()
            
            # 记录已分类的管口代号
            classified_pipe_codes = set()
            category_pipes = {}
            
            # 处理已分类的管口数据
            for data in classified_results:
                pipe_code = data['管口代号']
                category = data['类别']
                classified_pipe_codes.add(pipe_code)
                
                # 将管口按类别分组
                if category not in category_pipes:
                    category_pipes[category] = []
                category_pipes[category].append(pipe_code)
            
            # 查询当前产品的所有管口代号
            query = """
                SELECT 管口代号
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s
            """
            cursor.execute(query, (self.product_id,))
            all_pipes_results = cursor.fetchall()
            
            # 过滤出未分类的管口代号
            unclassified_pipes = []
            for data in all_pipes_results:
                pipe_code = data['管口代号']
                if pipe_code not in classified_pipe_codes:
                    unclassified_pipes.append(pipe_code)
            
            # 清空左侧表格
            self.tableWidge_pipe_code.setRowCount(0)
            
            # 填充左侧表格（未分类的管口）
            if unclassified_pipes:
                self.tableWidge_pipe_code.setRowCount(len(unclassified_pipes))
                for row, pipe_code in enumerate(unclassified_pipes):
                    item = QTableWidgetItem(pipe_code)
                    item.setTextAlignment(Qt.AlignCenter)
                    self.tableWidge_pipe_code.setItem(row, 0, item)
            
            # 设置行高
            for row in range(self.tableWidge_pipe_code.rowCount()):
                self.tableWidge_pipe_code.setRowHeight(row, 30)
            
            # 新增：为每个 item 设置 tooltip
            self.set_pipe_code_tooltips()

            # 初始化右侧分类表
            # 首先清除现有的标签页
            self.tabWidget_pipe_classification.clear()
            
            # 为每个类别创建标签页
            for category, pipe_codes in category_pipes.items():
                # 创建标签页容器
                tab_widget = QWidget()
                
                # 创建布局
                layout = QFormLayout()
                layout.setContentsMargins(2, 2, 2, 2)
                layout.setHorizontalSpacing(2)
                layout.setVerticalSpacing(2)
                
                # 创建表格控件
                table = QTableWidget()
                table.setColumnCount(1)
                table.horizontalHeader().setVisible(False)
                table.verticalHeader().setVisible(False)
                table.setShowGrid(False)
                table.setFrameShape(QTableWidget.NoFrame)
                table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                table.horizontalHeader().setDefaultSectionSize(344)
                table.horizontalHeader().setMinimumSectionSize(340)
                table.horizontalHeader().setStretchLastSection(True)
                table.setStyleSheet("background-color: rgb(255, 255, 255);")
                
                # 填充表格
                table.setRowCount(len(pipe_codes))
                for row, pipe_code in enumerate(pipe_codes):
                    item = QTableWidgetItem(pipe_code)
                    item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(row, 0, item)
                    table.setRowHeight(row, 30)
                
                # 将表格添加到布局中
                layout.addRow(table)
                
                # 设置容器的布局
                tab_widget.setLayout(layout)
                
                # 添加新标签页
                self.tabWidget_pipe_classification.addTab(tab_widget, category)

        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载管口数据失败: {str(e)}")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    
    def move_to_right(self):
        """将选中的管口代号移动到右侧分类表"""
        # 获取当前选中的行
        selected_items = self.tableWidge_pipe_code.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "提示", "请先选择要分配的管口")
            return
            
        # 获取当前活动的分类标签
        current_tab_index = self.tabWidget_pipe_classification.currentIndex()
        if current_tab_index < 0:
            QMessageBox.information(self, "提示", "请先选择一个分类标签页")
            return
        current_tab_name = self.tabWidget_pipe_classification.tabText(current_tab_index)
        
        # 获取当前的表格控件
        current_tablewidget = self.tabWidget_pipe_classification.widget(current_tab_index)
        
        # 根据tab_widget的类型获取表格控件
        if isinstance(current_tablewidget, QTableWidget):
            # 如果tab_widget本身就是表格
            current_table = current_tablewidget
        else:
            # 如果tab_widget是一个容器，查找其中的表格控件
            current_table = current_tablewidget.findChild(QTableWidget)
            if not current_table:
                QMessageBox.critical(self, "错误", "无法获取当前标签页的表格控件")
                return
            
        # 获取管口代号
        selected_rows = set()  # 用于存储需要删除的行
        pipe_codes = []
        for item in selected_items:
            row = item.row()
            selected_rows.add(row)
            pipe_code = self.tableWidge_pipe_code.item(row, 0).text()
            pipe_codes.append(pipe_code)
            
        # 添加到右侧表格
        for code in pipe_codes:
            # 检查是否已存在
            exists = False
            for row in range(current_table.rowCount()):
                if current_table.item(row, 0) and current_table.item(row, 0).text() == code:
                    exists = True
                    break
                    
            if not exists:
                # 添加新行
                row_count = current_table.rowCount()
                current_table.setRowCount(row_count + 1)
                
                # 添加管口代号
                item = QTableWidgetItem(code)
                item.setTextAlignment(Qt.AlignCenter)
                current_table.setItem(row_count, 0, item)

                # 设置统一的行高
                current_table.setRowHeight(row_count, 30)
                
                # 保存到数据库
                try:
                    conn = get_connection(**db_config)
                    cursor = conn.cursor()
                    
                    # 准备插入数据
                    insert_query = """
                        INSERT INTO 产品设计活动表_管口类别表 (产品ID, 管口代号, 类别)
                        VALUES (%s, %s, %s)
                    """
                    cursor.execute(insert_query, (self.product_id, code, current_tab_name))
                    conn.commit()
                    
                except Exception as e:
                    QMessageBox.critical(self, "数据库错误", f"保存管口分类失败: {str(e)}")
                finally:
                    if cursor:
                        cursor.close()
                    if conn:
                        conn.close()
        
        # 从左侧表格中删除已移动的行
        # 注意：从后向前删除，避免索引变化
        for row in sorted(selected_rows, reverse=True):
            self.tableWidge_pipe_code.removeRow(row)
                
    def move_to_left(self):
        """将选中的管口代号从右侧分类表移回左侧"""
        # 获取当前活动的分类标签
        current_tab_index = self.tabWidget_pipe_classification.currentIndex()
        current_tab_name = self.tabWidget_pipe_classification.tabText(current_tab_index)
        
        # 获取当前的表格控件
        current_tablewidget = self.tabWidget_pipe_classification.widget(current_tab_index)
        
        # 根据tab_widget的类型获取表格控件
        if isinstance(current_tablewidget, QTableWidget):
            # 如果tab_widget本身就是表格
            current_table = current_tablewidget
        else:
            # 如果tab_widget是一个容器，查找其中的表格控件
            current_table = current_tablewidget.findChild(QTableWidget)
            if not current_table:
                QMessageBox.critical(self, "错误", "无法获取当前标签页的表格控件")
                return
            
        # 获取选中的行
        selected_items = current_table.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "提示", "请先选择要移除的管口")
            return
            
        # 从右侧表格移除并添加回左侧
        selected_rows = set()
        pipe_codes = []
        
        # 获取要移回左侧的管口代号
        for item in selected_items:
            row = item.row()
            selected_rows.add(row)
            if current_table.item(row, 0):
                pipe_codes.append(current_table.item(row, 0).text())
                
        # 添加回左侧表格
        for code in pipe_codes:
            row_count = self.tableWidge_pipe_code.rowCount()
            self.tableWidge_pipe_code.setRowCount(row_count + 1)
            item = QTableWidgetItem(code)
            item.setTextAlignment(Qt.AlignCenter)
            self.tableWidge_pipe_code.setItem(row_count, 0, item)
            
            # 从数据库中删除该管口的分类
            try:
                conn = get_connection(**db_config)
                cursor = conn.cursor()
                
                # 删除分类记录
                delete_query = """
                    DELETE FROM 产品设计活动表_管口类别表
                    WHERE 产品ID = %s AND 管口代号 = %s AND 类别 = %s
                """
                cursor.execute(delete_query, (self.product_id, code, current_tab_name))
                conn.commit()
                
            except Exception as e:
                QMessageBox.critical(self, "数据库错误", f"删除管口分类失败: {str(e)}")
            finally:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()
                
        # 从右侧表格中删除行
        for row in sorted(selected_rows, reverse=True):
            current_table.removeRow(row)
                
    def add_classification(self):
        """添加一个新的分类标签页"""
        # 获取所有已有标签名
        existing_names = [self.tabWidget_pipe_classification.tabText(i)
                          for i in range(self.tabWidget_pipe_classification.count())]

        # # 获取当前标签页数
        # tabs_count = self.tabWidget_pipe_classification.count()
        
        # 创建自定义输入对话框
        dialog = CustomInputDialog(
            self,
            "请输入分类名称",
            "分类名称:",
            existing_names = existing_names
        )
        
        # 连接信号
        def on_input_accepted(text):
            if text:
                # 创建标签页容器
                tab_widget = QWidget()
                
                # 创建布局
                layout = QFormLayout()
                layout.setContentsMargins(2, 2, 2, 2)
                layout.setHorizontalSpacing(2)
                layout.setVerticalSpacing(2)
                
                # 创建表格控件
                table = QTableWidget()
                table.setColumnCount(1)
                table.horizontalHeader().setVisible(False)
                table.verticalHeader().setVisible(False)
                table.setShowGrid(False)
                table.setFrameShape(QTableWidget.NoFrame)
                table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                table.horizontalHeader().setDefaultSectionSize(344)
                table.horizontalHeader().setMinimumSectionSize(340)
                table.horizontalHeader().setStretchLastSection(True)
                table.setStyleSheet("background-color: rgb(255, 255, 255);")
                
                # 将表格添加到布局中
                layout.addRow(table)
                # 设置容器的布局
                tab_widget.setLayout(layout)
                
                # 添加新标签页
                self.tabWidget_pipe_classification.addTab(tab_widget, text)
                
                # 激活新添加的标签页
                new_index = self.tabWidget_pipe_classification.count() - 1
                self.tabWidget_pipe_classification.setCurrentIndex(new_index)
        
        dialog.inputAccepted.connect(on_input_accepted)

        # 显示对话框
        dialog.exec_()

    def delete_classification(self):
        """删除当前分类标签页"""
        tabs_count = self.tabWidget_pipe_classification.count()
        current_index = self.tabWidget_pipe_classification.currentIndex()

        # if tabs_count <= 1:
        #     QMessageBox.information(self, "提示", "至少保留一个分类标签页")
        #     return

        current_tab_name = self.tabWidget_pipe_classification.tabText(current_index)
        current_widget = self.tabWidget_pipe_classification.widget(current_index)
        table = current_widget.findChild(QTableWidget)
        if not table:
            QMessageBox.critical(self, "错误", "未找到当前分类")
            return

        reply = QMessageBox.question(
            self, "确认删除", f"是否取消该分类：{current_tab_name}？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            # 获取所有管口代号
            pipe_codes = []
            for row in range(table.rowCount()):
                if table.item(row, 0):
                    pipe_codes.append(table.item(row, 0).text())

            # 添加回左侧未分类表格
            for code in pipe_codes:
                row_count = self.tableWidge_pipe_code.rowCount()
                self.tableWidge_pipe_code.setRowCount(row_count + 1)
                item = QTableWidgetItem(code)
                item.setTextAlignment(Qt.AlignCenter)
                self.tableWidge_pipe_code.setItem(row_count, 0, item)
                self.tableWidge_pipe_code.setRowHeight(row_count, 30)

            # 删除数据库中记录
            try:
                conn = get_connection(**db_config)
                cursor = conn.cursor()
                delete_query = """
                    DELETE FROM 产品设计活动表_管口类别表
                    WHERE 产品ID = %s AND 类别 = %s
                """
                cursor.execute(delete_query, (self.product_id, current_tab_name))
                conn.commit()
            except Exception as e:
                QMessageBox.critical(self, "数据库错误", f"删除分类失败: {str(e)}")
            finally:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()

            # 删除该标签页
            self.tabWidget_pipe_classification.removeTab(current_index)
            #删除后自动选中下一个标签页
            self.tabWidget_pipe_classification.setCurrentIndex(
                min(current_index, self.tabWidget_pipe_classification.count() - 1))


            
    def save_and_close(self):
        """保存分类结果并关闭窗口"""
        # 显示保存成功消息
        # QMessageBox.information(self, "保存成功", "管口材料分类已保存")
        # 关闭窗口
        self.accept()
        
    def rearrange_table_rows(self, table):
        """重新排列表格行，移除空行"""
        row_count = table.rowCount()
        content_rows = []
        
        # 收集所有非空行的内容
        for row in range(row_count):
            if table.item(row, 0) and table.item(row, 0).text():
                content_rows.append(table.item(row, 0).text())
                
        # 清空表格
        table.clearContents()
        
        # 重新填充内容
        for row, text in enumerate(content_rows):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 0, item)

    def set_pipe_code_tooltips(self):
        """为左侧管口代号表格的每一行设置鼠标悬停提示（tooltip）"""
        row_count = self.tableWidge_pipe_code.rowCount()
        for row in range(row_count):
            item = self.tableWidge_pipe_code.item(row, 0)
            if item:
                item.setToolTip(item.text())

# 打开管口材料分配窗口的函数
def open_pipe_material_distribution(parent, product_id):
    """打开管口材料分配窗口"""
    dialog = PipeMaterialDistribution(parent, product_id)
    dialog.exec_() 