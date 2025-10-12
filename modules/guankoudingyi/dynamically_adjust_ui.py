from PyQt5.QtCore import Qt, QObject, QEvent, QItemSelectionModel

from PyQt5 import QtWidgets, uic
from PyQt5.QtWidgets import (
    QTableWidgetItem, QComboBox, QLabel,
    QVBoxLayout, QWidget, QMessageBox, QHeaderView
)
from PyQt5.QtGui import QColor
from pandas.core.interchange import column

from modules.chanpinguanli.chanpinguanli_main import product_manager
from modules.condition_input.view import check_project_and_product
from modules.guankoudingyi.funcs.funcs_pipe_data_output import export_nozzle_listing
#导入函数功能
from modules.guankoudingyi.obtain_product_type_version import get_product_type_and_version


from modules.guankoudingyi.funcs.funcs_pipe_table import (
    read_pipe_temp,
    move_selected_pipe_rows_up,
    move_selected_pipe_rows_down,
    delete_selected_pipe_rows, check_last_row_and_add_new
)
from modules.guankoudingyi.funcs.funcs_pipe_comboBox_units import setup_unit_selection_handlers, load_nps_to_dn_map
from modules.guankoudingyi.funcs.funcs_pipe_comboBox_value import handle_pipe_cell_click, handle_pipe_cell_changed, \
    initialize_pipe_combobox_delegates, NoWheelComboBox
# 导入表头排序功能
from modules.guankoudingyi.funcs.funcs_pipe_sort import setup_header_click_sort
# 导入确认按钮功能
from modules.guankoudingyi.funcs.funs_enter_key import connect_save_button
from modules.guankoudingyi.view_drawing.main_view import embed_heat_exchanger_view, HeatExchangerView

# 几个界面连接所添加的产品ID的传送
product_id = None

def on_product_id_changed(new_id):
    print(f"Received new PRODUCT_ID: {new_id}")
    global product_id
    product_id = new_id

# 测试用产品 ID（真实情况中由外部输入）
product_manager.product_id_changed.connect(on_product_id_changed)

# === 加入 ReturnKeyJumpFilter 定义 按enter键进入下一行===
class ReturnKeyJumpFilter(QObject):
    def __init__(self, table):
        super().__init__(table)
        self.table = table

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.table.state() == self.table.EditingState:
                return False

            current = self.table.currentIndex()
            if not current.isValid():
                return False

            row = current.row()
            col = current.column()

            next_row = row + 1
            if next_row >= self.table.rowCount():
                next_row = 0  # 循环跳转第一行（可按需修改）

            self.table.setCurrentCell(next_row, col)
            return True

        return super().eventFilter(obj, event)

# === 对公称尺寸、法兰标准、压力等级、法兰型式、密封面型式进行多行定义的时候最后一行编辑保护过滤器 ===
class LastRowEditProtector(QObject):
    def __init__(self, table, stats_widget):
        super().__init__(table)
        self.table = table
        self.stats_widget = stats_widget

    def eventFilter(self, obj, event):
        # 拦截可能触发编辑的事件
        if event.type() in (QEvent.MouseButtonDblClick, QEvent.KeyPress):
            current = self.table.currentIndex()
            if current.isValid():
                row = current.row()
                column = current.column()

                # 检查是否是最后一行且没有管口代号
                if row == self.table.rowCount() - 1:
                    pipe_code_item = self.table.item(row, 1)
                    has_pipe_code = pipe_code_item.text().strip() != "" if pipe_code_item else False

                    if not has_pipe_code and column in {4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18}:
                        print(f"[DEBUG] 过滤器阻止最后一行编辑：行={row}, 列={column}, 事件={event.type()}")
                        return True  # 阻止事件传递

        return super().eventFilter(obj, event)

# === 自定义选择模型，阻止选中最后一行空白行的特定列 ===
class CustomSelectionModel(QItemSelectionModel):
    def __init__(self, model, stats_widget):
        super().__init__(model)
        self.stats_widget = stats_widget
        self.table = stats_widget.tableWidget_pipe

    def select(self, selection, command):
        # 过滤选择范围，移除最后一行空白行的目标列单元格
        if hasattr(selection, 'indexes'):
            # 处理 QItemSelection
            filtered_selection = selection.__class__()
            for sel_range in selection:
                filtered_range = self.filter_selection_range(sel_range)
                if not filtered_range.isEmpty():
                    filtered_selection.append(filtered_range)
            super().select(filtered_selection, command)
        else:
            # 处理单个 QModelIndex
            if self.is_valid_selection(selection):
                super().select(selection, command)

    def filter_selection_range(self, sel_range):
        """过滤选择范围，移除最后一行空白行的目标列"""
        top = sel_range.top()
        bottom = sel_range.bottom()
        left = sel_range.left()
        right = sel_range.right()

        last_row = self.table.rowCount() - 1
        target_columns = {4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18}

        # 如果选择范围包含最后一行
        if bottom == last_row:
            # 检查最后一行是否有管口代号
            pipe_code_item = self.table.item(last_row, 1)
            has_pipe_code = pipe_code_item.text().strip() != "" if pipe_code_item else False

            if not has_pipe_code:
                # 检查选择范围是否包含目标列
                if any(col in target_columns for col in range(left, right + 1)):
                    # 如果只选择了最后一行，返回空选择
                    if top == bottom:
                        return sel_range.__class__()
                    # 否则，将选择范围缩小到倒数第二行
                    bottom = last_row - 1

        # 返回过滤后的选择范围
        if top <= bottom and left <= right:
            return sel_range.__class__(
                self.model().index(top, left),
                self.model().index(bottom, right)
            )
        else:
            return sel_range.__class__()

    def is_valid_selection(self, index):
        """检查单个索引是否可以被选择"""
        if not index.isValid():
            return True

        row = index.row()
        column = index.column()
        last_row = self.table.rowCount() - 1
        target_columns = {4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18}

        # 如果是最后一行的目标列
        if row == last_row and column in target_columns:
            pipe_code_item = self.table.item(row, 1)
            has_pipe_code = pipe_code_item.text().strip() != "" if pipe_code_item else False
            return has_pipe_code

        return True

# === 主程序 ===
class Stats(QtWidgets.QWidget):
    def __init__(self, line_tip=None):
        super().__init__()

        # # 0903会议纪要 首先进行项目和产品检查
        # print("准备检查项目和产品状态...")
        # can_open, msg = check_project_and_product()
        # if not can_open:
        #     QMessageBox.information(self, "提示", msg)
        #     self.deleteLater()  # 不打开界面
        #     return  # 立即返回

        self.line_tip = line_tip
        uic.loadUi("modules/guankoudingyi/ui/pipe_attachment_define.ui", self)

        # 保存product_id为实例变量，这样其他方法可以访问
        self.product_id = product_id
        print('product_id1111111111',self.product_id)

        # === ✅检查产品ID是否存在 ===
        # if not self.product_id:
        #     QMessageBox.warning(self, "提示", "请先至项目管理处选择产品！")
        #     return  # 中止初始化，避免后续出错

        # 保存旧的管口代号
        self.old_port_code = None
        # 修改管口代号但是管口代号重复，回退成之前的管口代号时用于阻隔信号
        self.is_restoring_pipe_code = False
        # 缓存每列的下拉框代理
        self.pipe_column_delegates = {}
        
        # ✅ 新增：冻结表头中的三个comboBox组件命名
        self.combo_nominal_size_type = None      # 公称尺寸类型选择框
        self.combo_pressure_level_type = None    # 压力等级类型选择框
        self.combo_weld_end_spec_type = None     # 焊端规格类型选择框

        # 设置冻结表头
        self.setup_tableWidget_pipe_title_freeze()
        # 设置主表格（隐藏表头）
        self.setup_tableWidget_pipe_header()
        # 在表格列创建完毕后，立即初始化缓存代理
        initialize_pipe_combobox_delegates(self)
        # ✅ 用于记录用户当前点击的单元格,默认无点击
        self.current_editing_cell = None
        # ✅ 新增：防止程序内部 setText 时误触发验证弹窗
        self.suppress_cell_change = False

        # 附件定义部分表头设计
        self.setup_tableWidget_attachment_header()

        # 绑定水平滚动条同步
        self.tableWidget_pipe.horizontalScrollBar().valueChanged.connect(
            self.tableWidget_pipe_title.horizontalScrollBar().setValue
        )
        self.tableWidget_pipe_title.horizontalScrollBar().valueChanged.connect(
            self.tableWidget_pipe.horizontalScrollBar().setValue
        )

        # 监听垂直滚动条显示状态变化
        self.tableWidget_pipe.verticalScrollBar().rangeChanged.connect(
            self.handle_vertical_scrollbar_visibility
        )

        # 隐藏冻结表头的滚动条
        self.tableWidget_pipe_title.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tableWidget_pipe_title.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 设置冻结表头的高度
        self.tableWidget_pipe_title.setMaximumHeight(105)  # 根据实际需要调整高度

        #调用其它类中的方法
        # 获取产品类型 & 型式
        belong_type, belong_version = get_product_type_and_version(self.product_id)
        if not belong_type or not belong_version:
            return  # 或者弹窗提示
        
        # ✅ 保存产品类型和型式到实例属性中，供set_pipe_function_column_readonly使用
        self.current_product_type = belong_type
        self.current_product_version = belong_version
        
        #读管口默认表到界面并存入产品设计活动表
        read_pipe_temp(self, belong_type, belong_version, self.product_id)
        
        # 创建视图并设置数据（放到数据加载后）
        embed_heat_exchanger_view(self.widget_control)
        self.view = self.widget_control.findChild(HeatExchangerView)  # ✅保存为实例变量
        if self.view:
            self.view.set_product_id(self.product_id) # ✅ 必须加上这一句，否则类型为 None
            self.view.nps_to_dn_map = load_nps_to_dn_map()  # ✅ 注入 NPS→DN 映射表
            self.view.set_pipe_data(self.get_all_pipe_data())

        #管口删除
        self.pushButton_pipe_delete.clicked.connect(lambda: delete_selected_pipe_rows(self, self.product_id))
        #管口上移
        self.pushButton_pipe_up.clicked.connect(lambda: move_selected_pipe_rows_up(self))
        #管口下移
        self.pushButton_pipe_down.clicked.connect(lambda: move_selected_pipe_rows_down(self))
        #管口信息导出
        self.pushButton_out.clicked.connect(self._on_click_export)

        # 单元格改变的监听
        self.tableWidget_pipe.cellChanged.connect(self.handle_cell_change)
        # 单元格监听——单击变下拉框
        self.tableWidget_pipe.cellClicked.connect(self.handle_pipe_cell_click)
        # 高亮行
        self.tableWidget_pipe.selectionModel().selectionChanged.connect(self.highlight_selected_rows)

        # 在表格初始化时连接信号
        self.tableWidget_pipe.cellChanged.connect(lambda row, column: handle_pipe_cell_changed(self, row, column, self.product_id))

        # 设置表头点击排序功能
        setup_header_click_sort(self)

        # 新增：监听焦点变化，自动保存旧管口代号
        # self.tableWidget_pipe.currentCellChanged.connect(self.on_pipe_cell_focus_changed)
        # 安装键盘事件监听器（用于实时保存旧管口代号）
        # self.tableWidget_pipe.installEventFilter(self)

        #回车事件到下一行
        self.tableWidget_pipe.installEventFilter(ReturnKeyJumpFilter(self.tableWidget_pipe))

        # 安装编辑保护过滤器
        self.tableWidget_pipe.installEventFilter(LastRowEditProtector(self.tableWidget_pipe, self))

        # 连接确认按钮
        connect_save_button(self)
        self.clear_bottom_tip()

        # ===== 批量赋值状态跟踪 =====
        # 仅用于第4-8列（公称尺寸、法兰标准、压力等级、法兰型式、密封面型式）
        self.bulk_assign_target_column = None
        self.bulk_assign_rows = []


    """设置冻结的表头"""
    def setup_tableWidget_pipe_title_freeze(self):
        # 把 tableWidget_pipe_title 这个表格控件赋值给局部变量 table_title
        # self. 表示这个表格控件是属于某个窗口类（Stats 类）的成员变量
        table_title = self.tableWidget_pipe_title
        table_title.setStyleSheet("""
            QTableView {
                border-top: 1px solid palette(mid);
                border-left: 1px solid palette(mid);
                border-right: 1px solid palette(mid);
                border-bottom: none;  /* ✅ 取消底部边框 */
                gridline-color: palette(midlight);
            }
        """)

        # 设置选择行为
        table_title.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        table_title.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        level1_headers = [
            "序号", "管口代号", "管口功能", "管口用途", "公称尺寸",
            "法兰规格", "管口位置", "管口附件", "管口载荷"
        ]

        level2_headers = {
            "法兰规格": ["法兰标准", "压力等级", "法兰型式", "密封面型式",  "焊端规格"],
            "管口位置": ["管口所属元件", "轴向定位基准", "轴向定位距离", "轴向夹角(°)", "周向方位(°)", "偏心距(mm)", "外伸高度"]
        }

        unit_options = {
            "公称尺寸": ["DN", "NPS"],
            "压力等级": ["Class", "PN"],
            "焊端规格": ["mm", "Sch"]
        }

        # 构建完整列映射
        header_map = []
        total_columns = 0
        for h1 in level1_headers:
            if h1 in level2_headers:
                for h2 in level2_headers[h1]:
                    header_map.append((h1, h2))
                    total_columns += 1
            else:
                header_map.append((h1, ""))
                total_columns += 1

        table_title.setColumnCount(total_columns)
        table_title.setRowCount(3)  # 一级 + 二级/单位组合行

        # 设置第0行：一级标题
        col = 0
        for h1 in level1_headers:
            if h1 == "公称尺寸":
                table_title.setSpan(0, col, 3, 1)  # ✅合并3行
                item = QTableWidgetItem("")  # ✅一级表头设为空防止重复
                item.setTextAlignment(Qt.AlignCenter)
                table_title.setItem(0, col, item)
                col += 1
            elif h1 in level2_headers:
                span = len(level2_headers[h1])
                table_title.setSpan(0, col, 1, span)
                item = QTableWidgetItem(h1)
                item.setTextAlignment(Qt.AlignCenter)
                table_title.setItem(0, col, item)
                col += span
            else:
                table_title.setSpan(0, col, 3, 1)  # 一级标题合并3行
                item = QTableWidgetItem(h1)
                item.setTextAlignment(Qt.AlignCenter)
                table_title.setItem(0, col, item)
                col += 1

        # 设置第1~2行：合并后的内容
        for i, (h1, h2) in enumerate(header_map):
            key = h2 if h2 else h1
            if key == "公称尺寸":
                # ✅公称尺寸 → 使用3行合并格子(0, i)，嵌入自定义控件
                widget = QWidget()
                layout = QVBoxLayout(widget)
                layout.setContentsMargins(2, 2, 2, 2)
                layout.setSpacing(2)

                label = QLabel(key)
                label.setAlignment(Qt.AlignCenter)
                label.setStyleSheet("font-size: 12pt;")
                # combo = QComboBox()
                combo = NoWheelComboBox()
                combo.addItems(unit_options[key])
                combo.setStyleSheet("QComboBox { font-size: 10pt; }")
                
                # ✅ 保存到实例变量
                self.combo_nominal_size_type = combo

                layout.addStretch()
                layout.addWidget(label)
                layout.addWidget(combo)
                layout.addStretch()
                table_title.setCellWidget(0, i, widget)
            elif key in unit_options:
                # 有单位选择的列
                table_title.setSpan(1, i, 2, 1)
                widget = QWidget()
                layout = QVBoxLayout(widget)
                layout.setContentsMargins(1, 1, 1, 1)
                layout.setSpacing(1)

                label = QLabel(key)
                label.setAlignment(Qt.AlignCenter)
                label.setStyleSheet("font-size: 12pt;")
                # combo = QComboBox()
                combo = NoWheelComboBox()
                combo.addItems(unit_options[key])
                combo.setStyleSheet("QComboBox { font-size: 10pt; }")
                
                # ✅ 根据字段类型保存到对应的实例变量
                if key == "压力等级":
                    self.combo_pressure_level_type = combo
                elif key == "焊端规格":
                    self.combo_weld_end_spec_type = combo

                layout.addWidget(label)
                layout.addWidget(combo)
                table_title.setCellWidget(1, i, widget)
            else:
                # 无单位字段，合并第2、3行，垂直居中
                table_title.setSpan(1, i, 2, 1)
                item = QTableWidgetItem(key)
                item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
                table_title.setItem(1, i, item)

        # 设置行高
        table_title.setRowHeight(0, 30)
        table_title.setRowHeight(1,65)
        table_title.setRowHeight(2, 0)  # 合并后高度置零

        # 设置列宽与主表格同步
        self.adjust_pipe_column_width()

        # 设置单位选择下拉框的事件处理器
        setup_unit_selection_handlers(self)

        row0 = table_title.rowHeight(0)
        row1 = table_title.rowHeight(1)
        header = table_title.horizontalHeader().height()
        dpi_scale = table_title.logicalDpiY() / 96.0
        padding = int(6 * dpi_scale)
        total_height = header + row0 + row1 + padding
        table_title.setFixedHeight(total_height)

    """设置主表格（盛放数据的表格）"""
    def setup_tableWidget_pipe_header(self):
        table_pipe = self.tableWidget_pipe
        self.tableWidget_pipe.setStyleSheet("""
            QTableView {
                border-top: none;
                border-left: 1px solid palette(mid);
                border-right: 1px solid palette(mid);
                border-bottom: 1px solid palette(mid);
                gridline-color: palette(midlight);
            }
        """)

        # 隐藏表头
        table_pipe.horizontalHeader().setVisible(False)

        # 设置与冻结表头相同的列数
        table_pipe.setColumnCount(self.tableWidget_pipe_title.columnCount())

        # 设置自定义选择模型，阻止选中最后一行空白行的特定列
        custom_selection_model = CustomSelectionModel(table_pipe.model(), self)
        table_pipe.setSelectionModel(custom_selection_model)

        # 连接选择变化信号，额外过滤最后一行空白行
        custom_selection_model.selectionChanged.connect(self.filter_last_row_selection)

        # 锁定第一列（序号列）不可编辑
        for row in range(table_pipe.rowCount()):
            item = table_pipe.item(row, 0)
            if item is None:
                item = QTableWidgetItem()
                table_pipe.setItem(row, 0, item)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)

    """处理两个表格的垂直滚动条显示状态变化"""
    def handle_vertical_scrollbar_visibility(self, min_val, max_val):
        """处理垂直滚动条显示状态变化"""
        scrollbar = self.tableWidget_pipe.verticalScrollBar()
        scrollbar_width = scrollbar.width() if max_val > min_val else 0
        
        # 获取最后一列的索引
        last_column = self.tableWidget_pipe.columnCount() - 1
        
        # 计算主表格最后一列的实际宽度
        main_table_last_col_width = self.tableWidget_pipe.columnWidth(last_column)
        
        # 如果有垂直滚动条，增加表头最后一列的宽度
        title_width = main_table_last_col_width + scrollbar_width
        self.tableWidget_pipe_title.setColumnWidth(last_column, title_width)

    """同步设置两个表格的列宽"""
    def adjust_pipe_column_width(self):
        # 最小列宽设置
        min_widths = {
            0: 70,  # 序号
            1: 110,  # 管口代号
            2: 110,  # 管口功能
            3: 110,  # 管口用途
            4: 110,  # 公称尺寸
            5: 220,  # 法兰标准
            6: 110,  # 压力等级
            7: 110,  # 法兰型式
            8: 130,  # 密封面型式
            9: 160,  # 焊端规格
            10: 160,  # 管口所属元件
            11: 160,  # 轴向定位基准
            12: 160,  # 轴向定位距离
            13: 140,  # 轴向夹角(°)
            14: 140,  # 周向方位(°)
            15: 140,  # 偏心距(mm)
            16: 160,  # 外伸高度
            17: 110,  # 管口附件
            18: 110  # 管口载荷
        }

        # 首先设置最小宽度
        for col in range(self.tableWidget_pipe.columnCount()):
            # 先手动设置最小列宽，避免初次 resizeColumnToContents 计算偏小
            min_width = min_widths.get(col, 90)
            # 设置最小列宽
            self.tableWidget_pipe.setColumnWidth(col, min_width)
            self.tableWidget_pipe_title.setColumnWidth(col, min_width)

        # 然后根据内容调整列宽
        for col in range(self.tableWidget_pipe.columnCount()):
            # 先让内容表和冻结表头分别根据内容自动调整
            self.tableWidget_pipe.resizeColumnToContents(col)
            self.tableWidget_pipe_title.resizeColumnToContents(col)

            # 取两者计算出的最大宽度
            content_width = max(
                self.tableWidget_pipe.columnWidth(col),
                self.tableWidget_pipe_title.columnWidth(col),
                min_widths.get(col, 90)
            )

            # 应用最终宽度到两个表格
            self.tableWidget_pipe.setColumnWidth(col, content_width)
            self.tableWidget_pipe_title.setColumnWidth(col, content_width)

        # 初始检查垂直滚动条状态
        self.handle_vertical_scrollbar_visibility(
            self.tableWidget_pipe.verticalScrollBar().minimum(),
            self.tableWidget_pipe.verticalScrollBar().maximum()
        )

    """该方法用于自动刷新序号，因为添加、删除、上/下移管口都存在序号的刷新，因此做了一个序号刷新的方法"""
    def refresh_pipe_table_sequence(self):
        """
        刷新管口定义表（tableWidget_pipe）第0列序号，从1开始递增
        """
        table = self.tableWidget_pipe
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is None:
                item = QTableWidgetItem()
                table.setItem(row, 0, item)
            item.setText(str(row + 1))  # 序号从1开始
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)  # 序号列始终不可编辑

    """处理单元格内容修改的监听"""
    def handle_cell_change(self, row, column):
        """
                处理单元格内容修改的事件
                :param row: 修改的行号
                :param column: 修改的列号
                """
        table = self.tableWidget_pipe
        # ✅ 管口代号列：检测是否重复
        if column == 1:
            item = table.item(row, column)
            if item:
                new_code = item.text().strip()
                if new_code:
                    for r in range(table.rowCount()):
                        if r != row:
                            other_item = table.item(r, 1)
                            if other_item and other_item.text().strip() == new_code:
                                QMessageBox.warning(self, "管口代号重复", f"管口代号 '{new_code}' 已存在，禁止重复。")
                                item.setText("")  # 清空
                                table.setCurrentCell(row, column)
                                return

        # 如果是管口代号列(column==1)且没有保存旧值，则假设是新添加的行，将old_port_code设为空
        if column == 1 and not hasattr(self, 'old_port_code'):
            self.old_port_code = ''

        # # ✅ 如果是最后一行的管口代号被填写，自动添加新行
        # if column == 1 and row == self.tableWidget_pipe.rowCount() - 1:
        #     item = self.tableWidget_pipe.item(row, column)
        #     if item and item.text().strip():
        #         check_last_row_and_add_new(self)

        # ✅ 更新视图
        view = self.widget_control.findChild(HeatExchangerView)
        if view:
            view.set_pipe_data(self.get_all_pipe_data())

    """处理单元格单击的监听，单击变成下拉框"""
    def handle_pipe_cell_click(self, row, column):
        """监听管口表单元格点击，若是五个目标字段，则转换为下拉框"""
        # 首先检查最后一行的限制：如果是最后一行且没有管口代号，不允许编辑
        table = self.tableWidget_pipe
        if row == table.rowCount() - 1:
            pipe_code_item = table.item(row, 1)
            has_pipe_code = pipe_code_item.text().strip() != "" if pipe_code_item else False
            if not has_pipe_code:
                print(f"[DEBUG] 阻止最后一行编辑：行={row}, 列={column}, 有管口代号={has_pipe_code}")
                return  # 阻止最后一行在没有管口代号时编辑

        handle_pipe_cell_click(self, row, column)

    """单行和多行高亮"""
    def highlight_selected_rows(self):
        """统一高亮逻辑：普通单元格和下拉框完全一致处理，不做特殊样式覆盖"""
        try:
            self.tableWidget_pipe.cellChanged.disconnect(self.handle_cell_change)
            table = self.tableWidget_pipe
            total_columns = table.columnCount()

            selected_indexes = table.selectedIndexes()
            if not selected_indexes:
                return

            selected_rows = set(index.row() for index in selected_indexes)
            selected_cells = set((index.row(), index.column()) for index in selected_indexes)

            # 当前正在编辑单元格（用于跳过正在编辑状态）
            current_editor = table.indexWidget(table.currentIndex())
            editing_row, editing_col = table.currentIndex().row(), table.currentIndex().column()
            is_editing = current_editor is not None

            for row in range(table.rowCount()):
                row_selected = row in selected_rows

                for col in range(total_columns):
                    # 正在编辑的单元格跳过不渲染，防止闪烁
                    if is_editing and (row == editing_row and col == editing_col):
                        continue

                    item = table.item(row, col)
                    if not item:
                        continue

                    if row_selected:
                        if (row, col) in selected_cells:
                            item.setBackground(QColor("#0078d7"))
                            item.setForeground(QColor("white"))
                        else:
                            item.setBackground(QColor("#d0e7ff"))
                            item.setForeground(QColor("black"))
                    else:
                        item.setBackground(Qt.transparent)
                        item.setForeground(Qt.black)

            # ✅ 同步高亮绘图模块管口代号
            if self.view:
                pipe_codes = []
                for row in selected_rows:
                    item = self.tableWidget_pipe.item(row, 1)
                    if item:
                        code = item.text().strip()
                        if code:
                            pipe_codes.append(code)
                self.view.set_highlight_pipe_codes(pipe_codes)

        except Exception as e:
            print(f"高亮行出错: {str(e)}")
        finally:
            try:
                self.tableWidget_pipe.cellChanged.connect(self.handle_cell_change)
            except Exception:
                pass

        # 在高亮刷新后，更新批量赋值状态
        try:
            from modules.guankoudingyi.funcs.funcs_pipe_comboBox_value import update_bulk_assign_state
            update_bulk_assign_state(self)
        except Exception as e:
            print(f"更新批量赋值状态出错: {str(e)}")

    """从表格中提取所有管口数据"""
    def get_all_pipe_data(self):
        table = self.tableWidget_pipe
        fields = {
            1: "管口代号", 4: "公称尺寸", 10: "管口所属元件",
            11: "轴向定位基准", 12: "轴向定位距离", 13: "轴向夹角（°）",
            14: "周向方位（°）", 15: "偏心距", 16: "外伸高度"
        }
        data = []
        for row in range(table.rowCount() - 1):  # 忽略最后一行
            item = {}
            for col, key in fields.items():
                cell = table.item(row, col)
                item[key] = cell.text().strip() if cell else ""
            
            # ✅ 修改条件：只要有管口代号、公称尺寸、管口所属元件、轴向定位基准这四个基本信息就开始绘制
            if (item["管口代号"] and item["公称尺寸"] and 
                item["管口所属元件"] and item["轴向定位基准"]):
                
                # 为空值参数设置默认值
                if not item["轴向定位距离"]:
                    item["轴向定位距离"] = "程序推荐"
                if not item["轴向夹角（°）"]:
                    item["轴向夹角（°）"] = "0"
                if not item["周向方位（°）"]:
                    item["周向方位（°）"] = "180"
                if not item["偏心距"]:
                    item["偏心距"] = "0"
                if not item["外伸高度"]:
                    item["外伸高度"] = "程序推荐"
                    
                data.append(item)
        return data

    # """只要焦点进入管口代号列，就保存旧值"""
    # def on_pipe_cell_focus_changed(self, currentRow, currentColumn, previousRow, previousColumn):
    #     if currentColumn == 1:  # 管口代号列
    #         item = self.tableWidget_pipe.item(currentRow, currentColumn)
    #         if item:
    #             self.old_port_code = item.text().strip()
    #             print(f"[焦点] 保存原始管口代号: {self.old_port_code}")
    #         else:
    #             self.old_port_code = ''
    #             print(f"[焦点] 单元格为空，设置空字符串作为原始管口代号")

    # """安装一个 eventFilter（事件过滤器），在用户对管口代号单元格输入任意键盘事件时，实时更新 old_port_code 的值。
    #     这样即使焦点未变化，连续修改也能识别上次的值。"""
    # def eventFilter(self, obj, event):
    #     # 实时保存管口代号的旧值（避免连续修改失败）
    #     if obj == self.tableWidget_pipe and event.type() == QEvent.KeyPress:
    #         current_row = self.tableWidget_pipe.currentRow()
    #         current_col = self.tableWidget_pipe.currentColumn()
    #         if current_col == 1:  # 仅处理管口代号列
    #             item = self.tableWidget_pipe.item(current_row, current_col)
    #             if item:
    #                 self.old_port_code = item.text().strip()
    #                 print(f"[键盘] 实时更新旧管口代号: {self.old_port_code}")
    #             else:
    #                 self.old_port_code = ''
    #         return False  # 允许事件继续传递
    #     return super().eventFilter(obj, event)

    """创建一个方法对附件定义表的表头进行设置"""
    def setup_tableWidget_attachment_header(self):
        table_attach = self.tableWidget_attachment
        # 一级标题
        headers = [
            "序号", "元件名称", "类型", "附属", "位置近", "轴向定位值",
            "数量", "间距", "周向方位(°)", "偏心距", "夹角(°)", "外伸高度", "备注"
        ]

        table_attach.setColumnCount(len(headers))
        table_attach.setRowCount(1)

        for i, title in enumerate(headers):
            item = QTableWidgetItem(title)
            item.setTextAlignment(Qt.AlignCenter)
            table_attach.setItem(0, i, item)

        # 表格外观设置
        table_attach.verticalHeader().setVisible(False)
        table_attach.horizontalHeader().setVisible(False)
        table_attach.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table_attach.setRowHeight(0, 30)


    """过滤选择，移除最后一行空白行的特定列选择"""
    def filter_last_row_selection(self, selected, deselected):

        table = self.tableWidget_pipe
        last_row = table.rowCount() - 1
        target_columns = {4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18}

        # 检查最后一行是否有管口代号
        pipe_code_item = table.item(last_row, 1)
        has_pipe_code = pipe_code_item.text().strip() != "" if pipe_code_item else False

        if not has_pipe_code:
            # 获取当前选择
            selection_model = table.selectionModel()
            current_selection = selection_model.selection()

            # 检查是否有最后一行的目标列被选中
            should_clear = False
            for sel_range in current_selection:
                if sel_range.bottom() == last_row:
                    # 检查是否包含目标列
                    if any(col in target_columns for col in range(sel_range.left(), sel_range.right() + 1)):
                        should_clear = True
                        break

            if should_clear:
                # 创建新的选择，排除最后一行的目标列
                from PyQt5.QtCore import QItemSelection
                new_selection = QItemSelection()

                for sel_range in current_selection:
                    top = sel_range.top()
                    bottom = sel_range.bottom()
                    left = sel_range.left()
                    right = sel_range.right()

                    # 如果选择范围包含最后一行
                    if bottom == last_row:
                        # 检查是否包含目标列
                        if any(col in target_columns for col in range(left, right + 1)):
                            # 如果只选择了最后一行，跳过这个范围
                            if top == bottom:
                                continue
                            # 否则，缩小选择范围到倒数第二行
                            bottom = last_row - 1

                    # 添加过滤后的范围
                    if top <= bottom:
                        new_selection.select(
                            table.model().index(top, left),
                            table.model().index(bottom, right)
                        )

                # 应用新的选择
                selection_model.blockSignals(True)
                selection_model.clearSelection()
                selection_model.select(new_selection, QItemSelectionModel.Select)
                selection_model.blockSignals(False)

    def _on_click_export(self):
        try:
            # 在导出前先给出提示
            if self.line_tip:
                self.line_tip.setText("离开该界面前请勿忘记点击“确认”按钮！")
                self.line_tip.setStyleSheet("color: #fcb15d; font-weight:bold;")

            out_path = export_nozzle_listing(self)  # self 就是 stats_widget
            if out_path:
                QMessageBox.information(self, "导出成功", f"已导出到：\n{out_path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))
    """用于点击确认后，清除下方给出的提示"""
    def clear_bottom_tip(self):
        if self.line_tip:
            self.line_tip.clear()



