# 这是一个示例 Python 脚本。
import warnings

# 按 Shift+F10 执行或将其替换为您的代码。
# 按 双击 Shift 在所有地方搜索类、文件、工具窗口、操作和设置。
from PyQt5 import QtWidgets, uic
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence, QBrush, QColor
import sys

from PyQt5.uic.properties import QtCore

from modules.chanpinguanli import common_usage

# 屏蔽所有弃用警告
if not sys.warnoptions:
    warnings.simplefilter("ignore", category=DeprecationWarning)

# 相关文件导入
import os
import traceback
import modules.chanpinguanli.bianl as bianl
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                             QComboBox, QFileDialog, QFrame, QGroupBox, QHeaderView, QDateEdit, QMessageBox, QAction)
from PyQt5.QtCore import QDate

import modules.chanpinguanli.new_project_button as new_project_button
import modules.chanpinguanli.project_confirm_btn as project_confirm_btn
import modules.chanpinguanli.modify_project as modify_project
import modules.chanpinguanli.open_project as open_project
import modules.chanpinguanli.product_confirm_qbtn as product_confirm_qbtn
import modules.chanpinguanli.product_modify as product_modify
import modules.chanpinguanli.chanpinguanli_main as main
import modules.chanpinguanli.auto_edit_row as auto_edit_row


class cpgl_Stats(QtWidgets.QWidget):
    def __init__(self,line_tip=None):
        super().__init__()
        uic.loadUi("modules/chanpinguanli/guanli.ui", self)
        # 强制给整个界面设置字体
        font = QtWidgets.QApplication.font()
        self.setFont(font)
        self.line_tip=line_tip




        # 绑定 Qt Designer 中的控件到 bianl 全局变量  改66
        bianl.main_window = self
        bianl.project_info_group = self.findChild(QtWidgets.QGroupBox, "project_info_group")
        bianl.product_info_group = self.findChild(QtWidgets.QGroupBox, "product_info_group")
        bianl.product_definition_group = self.findChild(QtWidgets.QGroupBox, "product_definition_group")
        bianl.work_information_group = self.findChild(QtWidgets.QGroupBox, "work_information_group")

        # 项目信息区
        bianl.owner_input = self.findChild(QtWidgets.QLineEdit, "owner_input")
        bianl.project_number_input = self.findChild(QtWidgets.QLineEdit, "project_number_input")
        bianl.project_name_input = self.findChild(QtWidgets.QLineEdit, "project_name_input")
        bianl.department_input = self.findChild(QtWidgets.QLineEdit, "department_input")
        bianl.contractor_input = self.findChild(QtWidgets.QLineEdit, "contractor_input")
        bianl.project_path_input = self.findChild(QtWidgets.QLineEdit, "project_path_input")
        bianl.date_edit = self.findChild(QtWidgets.QDateEdit, "date_edit")
        # 日历弹出日期
        bianl.date_edit.setCalendarPopup(True)
        # 设置格式
        # bianl.date_edit.setDisplayFormat("yyyy/MM/dd")

        from PyQt5.QtCore import QDate
        bianl.date_edit.setDate(QDate.currentDate())

        # 产品信息区
        bianl.product_table = self.findChild(QtWidgets.QTableWidget, "product_table")

        # 产品定义区 改77
        bianl.product_type_combo = self.findChild(QtWidgets.QComboBox, "product_type_combo")
        bianl.product_form_combo = self.findChild(QtWidgets.QComboBox, "product_form_combo")
        print("🧪 启动时 product_form_combo.currentText() =", bianl.product_form_combo.currentText())

        bianl.product_model_input = self.findChild(QtWidgets.QLineEdit, "product_model_input")
        bianl.drawing_prefix_input = self.findChild(QtWidgets.QLineEdit, "drawing_prefix_input")
        bianl.image_label = self.findChild(QtWidgets.QLabel, "image_label")
        bianl.image_area = self.findChild(QtWidgets.QFrame, "image_area")

        #工作信息区 改77
        bianl.design_input = self.findChild(QtWidgets.QLineEdit, "design_input")
        bianl.proofread_input = self.findChild(QtWidgets.QLineEdit, "proofread_input")
        bianl.review_input = self.findChild(QtWidgets.QLineEdit, "review_input")
        bianl.standardization_input = self.findChild(QtWidgets.QLineEdit, "standardization_input")
        bianl.approval_input = self.findChild(QtWidgets.QLineEdit, "approval_input")
        bianl.co_signature_input = self.findChild(QtWidgets.QLineEdit, "co_signature_input")

        # 渲染图片 立式容器 双腔型 对应的图片切换 不会出现问题
        # 1. 不让 QLabel 撑大自己
        # 居中
        bianl.image_label.setAlignment(Qt.AlignCenter)
        bianl.image_label.setScaledContents(False)  # 不直接拉伸图片

        # 2. 设置 QLabel 尺寸策略为不扩展，防止撑开 layout
        from PyQt5.QtWidgets import QSizePolicy
        policy = QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        bianl.image_label.setSizePolicy(policy)

        # 设置初始数据(新增）
        bianl.product_table.setRowCount(3)  # 设置初始行数
        for row in range(3):
            main.set_row_number(row)  # 调用新增函数，为初始行编号xx
            bianl.product_table_row_status[row] = {
                "status": "start",
                "definition_status": "start"
            }
            # main.on_rows_inserted(row, row)  # ✅ 初始行也生成下拉框
        from typing import List
        # 下拉框的列
        def get_design_stage_options() -> List[str]:
            # 这里可以替换为数据库读取/配置读取
            return ["方案设计", "详细设计"]

        # 若你已有：def get_status(row) -> "view"/"edit" ...
        self.design_stage_col4 = main.ColumnComboInstaller(
            table=self.product_table,
            column=4,
            options_provider=get_design_stage_options,
            editable=True,  # 允许在下拉里手动输入；若不允许，改为 False
            # read_only_checker=get_status  # 可选：根据行状态设只读；没有就去掉此参数
        )
        self.design_stage_col4.install()

        # 初始化 产品定义 全部锁住 改77
        # 单独锁一个 产品信息部分的下拉框

        main.lock_combo(bianl.product_type_combo)
        main.lock_combo(bianl.product_form_combo)
        main.lock_line_edit(bianl.product_model_input)
        main.lock_line_edit(bianl.drawing_prefix_input)

        main.lock_line_edit(bianl.design_input)
        main.lock_line_edit(bianl.proofread_input)
        main.lock_line_edit(bianl.review_input)
        main.lock_line_edit(bianl.standardization_input)
        main.lock_line_edit(bianl.approval_input)
        main.lock_line_edit(bianl.co_signature_input)



        # ✅ 你也可以绑定按钮，如：
        # === 按钮绑定 ===


        # 折叠按钮、
        # self.findChild(QtWidgets.QPushButton, "toggle_project_info_btn").clicked.connect(main.toggle_project_info)
        #
        # 绑定按钮并保存引用
        btn = self.findChild(QtWidgets.QPushButton, "toggle_project_info_btn")
        btn.clicked.connect(main.toggle_project_info)
        btn.setText("∧")  # 初始状态：展开
        bianl.toggle_project_info_btn = btn



        # 项目信息
        # 上面四个 加一个确认
        self.findChild(QtWidgets.QPushButton, "new_project_btn").clicked.connect(new_project_button.prepare_new_project)
        # self.findChild(QtWidgets.QPushButton, "confirm_project_btn").clicked.connect(project_confirm_btn.save_project_to_db)
        # lxy修改
        self.findChild(QtWidgets.QPushButton, "confirm_project_btn").clicked.connect(self._on_save_clicked)

        self.findChild(QtWidgets.QPushButton, "edit_project_btn").clicked.connect(modify_project.modify_project)
        self.findChild(QtWidgets.QPushButton, "open_project_btn").clicked.connect(open_project.open_project)
        self.findChild(QtWidgets.QPushButton, "delete_project_btn").clicked.connect(project_confirm_btn.delete_project_and_related_data)
        # self.findChild(QtWidgets.QPushButton, "project_path_button").clicked.connect(main.select_project_path)

        # 设置选择项目文件夹的按钮
        bianl.project_path_button = self.findChild(QtWidgets.QPushButton, "project_path_button")
        bianl.project_path_button.clicked.connect(main.select_project_path)
        # bianl.project_path_button.setMinimumWidth(80)  # ✅ 在控件初始化后再设置大小
        bianl.project_path_button.setText("...")

        # ✅ 样式 + 对齐输入框高度（一般 QLineEdit 是 28px 左右）
        bianl.project_path_button.setFixedHeight(bianl.project_path_input.sizeHint().height())  # 高度一致
        bianl.project_path_button.setFixedWidth(50)  # 你可以调为 40, 50，看你喜欢的宽度

        # ✅ 可选样式，浅灰色直角立体风  文件选择路径的按钮样式
        bianl.project_path_button.setStyleSheet("""
            QPushButton {
                background-color: #f0f0f0;
                border: 1px solid #ccc;
                border-radius: 0px;  /* 直角 */
                color: #333;
                font-size: 12pt;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
            QPushButton:pressed {
                background-color: #d0d0d0;
                border-style: inset;
            }
        """)

        # 产品信息 监控
        # cellChanged单元格被改变的时候 开始调用这个函数 进行删增
        #  确认
        # bianl.product_table.cellChanged.connect(auto_edit_row.handle_auto_add_row)
        # 避免有产品id的时候自删
        try:
            bianl.product_table.cellChanged.disconnect()
        except Exception:
            pass
        bianl.product_table.cellChanged.connect(main.on_product_cell_changed_router)

        self.findChild(QtWidgets.QPushButton, "confirm_product_btn").clicked.connect(product_confirm_qbtn.handle_confirm_product)
        # 改成修改产品的编辑状态
        self.findChild(QtWidgets.QPushButton, "modify_product_btn").clicked.connect(product_modify.edit_row_state)
        # 删除产品
        self.findChild(QtWidgets.QPushButton, "delete_product_btn").clicked.connect(main.delete_selected_product)






        # 产品定义 改66
        # 下拉框
        bianl.product_type_combo.showPopup = main.wrap_show_popup(bianl.product_type_combo.showPopup, main.load_product_types)
        bianl.product_form_combo.showPopup = main.wrap_show_popup(bianl.product_form_combo.showPopup, main.load_product_forms)
        bianl.product_type_combo.currentTextChanged.connect(main.load_product_forms)

        # 设计阶段 下拉框  改88
        # bianl.design_stage_combo.showPopup = main.wrap_show_popup(bianl.design_stage_combo.showPopup,
        #                                                      main.load_product_types_design_t)

        # 产品表格处发生点击时间
        # ✅ 新增：键盘移动\点击

        bianl.product_table.currentCellChanged.connect(main.on_product_row_clicked)

        # 产品定义 确定
        # self.findChild(QtWidgets.QPushButton, "confirm_definition_btn").clicked.connect(main.confirm_product_definition)
        # lxy修改
        self.findChild(QtWidgets.QPushButton, "confirm_definition_btn").clicked.connect(
            self._on_confirm_definition_clicked)

        # 图片渲染
        bianl.product_type_combo.currentTextChanged.connect(main.try_show_image)
        bianl.product_form_combo.currentTextChanged.connect(main.try_show_image)

        # 不让他查询
        main.disable_keyboard_search(bianl.product_table)
        # 点击回车保存跟下滑
        bianl.product_table.installEventFilter(main.ReturnKeyJumpFilter(bianl.product_table))



        # 复制粘贴的快捷键插入
        # Ctrl+C 复制选中单元格或整行
        copy_action = QAction(bianl.main_window)
        copy_action.setShortcut(QKeySequence("Ctrl+C"))
        copy_action.triggered.connect(main.copy_selected_cells)
        bianl.main_window.addAction(copy_action)

        # Ctrl+V 粘贴到当前单元格位置
        paste_action = QAction(bianl.main_window)
        paste_action.setShortcut(QKeySequence("Ctrl+V"))
        paste_action.triggered.connect(main.paste_cells_to_table)
        bianl.main_window.addAction(paste_action)

        # 你也可以在这里执行初始化逻辑：
        # 初始化 产品信息部分的表格
        # 设置表格属性
        # 设置水平表头 自动拉伸
        # bianl.product_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        # # 设置表格的垂直表头 行高
        # bianl.product_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        # # 水平滚动条 为始终显示
        # bianl.product_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        from PyQt5.QtWidgets import QHeaderView

        # 获取列数
        column_count = bianl.product_table.columnCount()
        # 设置序号列宽度（假设序号列为第0列）

        bianl.product_table.setColumnWidth(0, 150)  # 将序号列宽度设置为 50

        # 禁止拖拽 实现调整序号列的宽度
        bianl.product_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)  # 禁用序号列的拖拽调整

        # 设置其他列的宽度为等分
        header = bianl.product_table.horizontalHeader()

        # 设置第 1 列到最后一列为自适应宽度
        for i in range(1, column_count):
            header.setSectionResizeMode(i, QHeaderView.Stretch)

        # 设置表格的垂直表头 行高（根据内容自适应）
        bianl.product_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        # 水平滚动条 始终显示
        bianl.product_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        # 开启表格的网格线
        # bianl.product_table.setShowGrid(True)  # 显示表格线
        #  新加的表格线
        from PyQt5.QtWidgets import QApplication

        # 设置全局样式
        from PyQt5.QtWidgets import QApplication

        # 设置表头底部分割线
        bianl.product_table.setStyleSheet("""
        QHeaderView::section {
            border-top: none;
            border-left: 1px solid #c0c0c0;
            border-right: 1px solid #c0c0c0;
            border-bottom: 1px solid #c0c0c0;
            background-color: palette(window);
        }
        """)

        # 显示表格线
        bianl.product_table.setShowGrid(True)
        #改77
        main.load_product_types()
        main.load_product_forms()
        # main.load_product_types_design_t()
        # 产品信息表格 不可编辑
        bianl.project_mode = "new"
        from modules.chanpinguanli.product_confirm_qianzhi import set_row_editable
        for row in range(bianl.product_table.rowCount()):
            set_row_editable(row, False)
        # 产品信息表格部分的每行的字体颜色灰色的初始话
        # open_project.apply_table_font_style()
        # 绑定信号 点击表头 列变成深蓝色
        # bianl.product_table.horizontalHeader().sectionClicked.connect(main._on_header_clicked)


        # 项目管理 回车 键盘上下左右键控制 其他输入框的绑定方向
        from PyQt5.QtWidgets import QLineEdit, QDateEdit

        def apply_project_info_keyboard_control():
            from PyQt5.QtCore import Qt

            nav_map = {
                bianl.owner_input: {
                    Qt.Key_Right: bianl.project_number_input,
                    Qt.Key_Down: bianl.project_name_input,
                },
                bianl.project_number_input: {
                    Qt.Key_Left: bianl.owner_input,
                    Qt.Key_Down: bianl.department_input,
                },
                bianl.project_name_input: {
                    Qt.Key_Right: bianl.department_input,
                    Qt.Key_Up: bianl.owner_input,
                    Qt.Key_Down: bianl.contractor_input
                },
                bianl.department_input: {
                    Qt.Key_Left: bianl.project_name_input,
                    Qt.Key_Up: bianl.project_number_input,
                    Qt.Key_Down: bianl.date_edit
                },
                bianl.contractor_input: {
                    # 工程总包方
                    Qt.Key_Up: bianl.project_name_input,
                    Qt.Key_Down: bianl.project_path_input,
                    Qt.Key_Right:bianl.date_edit
                },
                bianl.project_path_input: {
                    Qt.Key_Up: bianl.contractor_input,
                    Qt.Key_Right: bianl.date_edit
                }
                # ,
                # bianl.date_edit: {
                #     # Qt.Key_Left: bianl.project_path_input,
                #     Qt.Key_Up: bianl.department_input,
                #     Qt.Key_Down: bianl.project_path_input
                # }
            }

            def make_handler(widget):
                def key_handler(e):
                    key = e.key()
                    if widget in nav_map and key in nav_map[widget]:
                        target = nav_map[widget][key]
                        if callable(target):
                            target()
                        else:
                            target.setFocus()
                    elif key in (Qt.Key_Return, Qt.Key_Enter):
                        widget.focusNextChild()
                    else:
                        type(widget).keyPressEvent(widget, e)

                return key_handler

            for widget in nav_map:
                widget.keyPressEvent = make_handler(widget)

                # ✅ 专门处理 QDateEdit 的方向键行为

            # 单独处理创建日期输入框的上下键设置
            def fix_date_edit_arrow_navigation():
                def key_handler(e):
                    key = e.key()
                    line_edit = bianl.date_edit.lineEdit()
                    cursor_pos = line_edit.cursorPosition()
                    text_len = len(line_edit.text())

                    if key == Qt.Key_Left:
                        if cursor_pos == 0:
                            bianl.contractor_input.setFocus()
                        else:
                            QDateEdit.keyPressEvent(bianl.date_edit, e)

                    # elif key == Qt.Key_Right:
                    #     if cursor_pos == text_len:
                    #         bianl.project_path_input.setFocus()
                    #     else:
                    #         QDateEdit.keyPressEvent(bianl.date_edit, e)

                    elif key == Qt.Key_Up:
                        bianl.department_input.setFocus()
                    elif key == Qt.Key_Down:
                        bianl.project_path_input.setFocus()
                    elif key in (Qt.Key_Return, Qt.Key_Enter):
                        bianl.date_edit.focusNextChild()
                    else:
                        QDateEdit.keyPressEvent(bianl.date_edit, e)

                bianl.date_edit.keyPressEvent = key_handler

            fix_date_edit_arrow_navigation()

            # 👇 添加这一段代码
            for label in bianl.product_definition_group.findChildren(QtWidgets.QLabel):
                label.setStyleSheet("background-color: transparent;")
            for label in bianl.work_information_group.findChildren(QtWidgets.QLabel):
                label.setStyleSheet("background-color: transparent;")
        # 👇 添加这一行调用函数（必须放在控件都初始化之后）
        apply_project_info_keyboard_control()


        #产品定义 工作信息 的键盘绑定
        def apply_product_work_info_keyboard_control():
            from PyQt5.QtCore import Qt

            nav_map = {
                # 产品定义区
                bianl.product_type_combo: {
                    Qt.Key_Down: bianl.product_form_combo,
                    Qt.Key_Right: bianl.design_input,  # 右键跨到工作信息第一行
                },
                bianl.product_form_combo: {
                    Qt.Key_Up: bianl.product_type_combo,
                    Qt.Key_Down: bianl.product_model_input,
                    Qt.Key_Right: bianl.design_input,
                },
                bianl.product_model_input: {
                    Qt.Key_Up: bianl.product_form_combo,
                    Qt.Key_Down: bianl.drawing_prefix_input,
                    Qt.Key_Right: bianl.design_input,
                },
                bianl.drawing_prefix_input: {
                    Qt.Key_Up: bianl.product_model_input,
                    Qt.Key_Down: bianl.design_input,  # ↓ 直接进入工作信息
                    Qt.Key_Right: bianl.design_input,
                },

                # 工作信息区
                bianl.design_input: {
                    Qt.Key_Left: bianl.product_model_input,  # ← 回到型号
                    Qt.Key_Up: bianl.drawing_prefix_input,
                    Qt.Key_Down: bianl.proofread_input,
                },
                bianl.proofread_input: {
                    Qt.Key_Up: bianl.design_input,
                    Qt.Key_Down: bianl.review_input,
                    Qt.Key_Left: bianl.product_model_input,
                },
                bianl.review_input: {
                    Qt.Key_Up: bianl.proofread_input,
                    Qt.Key_Down: bianl.standardization_input,
                    Qt.Key_Left: bianl.product_model_input,
                },
                bianl.standardization_input: {
                    Qt.Key_Up: bianl.review_input,
                    Qt.Key_Down: bianl.approval_input,
                    Qt.Key_Left: bianl.product_model_input,
                },
                bianl.approval_input: {
                    Qt.Key_Up: bianl.standardization_input,
                    Qt.Key_Down: bianl.co_signature_input,
                    Qt.Key_Left: bianl.product_model_input,
                },
                bianl.co_signature_input: {
                    Qt.Key_Up: bianl.approval_input,
                    Qt.Key_Left: bianl.product_model_input,
                },
            }

            def make_handler(widget):
                def key_handler(e):
                    key = e.key()
                    if widget in nav_map and key in nav_map[widget]:
                        target = nav_map[widget][key]
                        target.setFocus()
                    elif key in (Qt.Key_Return, Qt.Key_Enter):
                        # 回车等价于 ↓
                        if widget in nav_map and Qt.Key_Down in nav_map[widget]:
                            nav_map[widget][Qt.Key_Down].setFocus()
                        else:
                            widget.focusNextChild()
                    else:
                        type(widget).keyPressEvent(widget, e)

                return key_handler

            for widget in nav_map:
                widget.keyPressEvent = make_handler(widget)

        # lxy修改
        self._dirty = False  # 是否存在未保存修改
        self._wire_dirty_signals()  # 只对“用户编辑”置脏的信号绑定

        # 👇 添加这一行调用函数（必须放在控件都初始化之后）
        apply_product_work_info_keyboard_control()
        # lxy修改
        self._wire_definition_work_edit_signals()

        # 延迟加载最后使用的项目，确保UI完全初始化  改3
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(20, main.load_last_project)


        # 新建类 窗口关闭 检查内容是否已经保存

    # lxy新增
    def _on_confirm_definition_clicked(self):
        """包装产品定义保存：成功后复位 definition_status=view；失败保持 edit 并尽量恢复控件可编辑"""
        ok = False
        try:
            # 要求 main.confirm_product_definition() 在成功时返回 True，失败时返回 False
            res = main.confirm_product_definition()
            ok = bool(res)  # ✅ 只有 True 才算成功；False/None 都当失败
        except Exception as e:
            print(f"[confirm_definition 异常] {e}")
            ok = False

        row = bianl.product_table.currentRow()
        st = bianl.product_table_row_status.get(row, {}) if row is not None else {}

        if ok:
            if isinstance(st, dict):
                st["definition_status"] = "view"
                print(f"【调试】第{row + 1}行 definition_status 复位为 view（定义/工作信息已保存）")
            if hasattr(self, "mark_clean"):
                self.mark_clean()
        else:
            # 失败：保持 edit，不要复位
            if isinstance(st, dict):
                st["definition_status"] = "edit"
                print(f"【调试】第{row + 1}行保存失败，保持 definition_status=edit")
            # 有些实现里保存前会把控件 setEnabled(False)，失败时要把它们恢复，以便用户继续改
            try:
                for w in (bianl.product_type_combo,
                          bianl.product_form_combo,
                          bianl.product_model_input,
                          bianl.drawing_prefix_input,
                          bianl.design_input, bianl.proofread_input, bianl.review_input,
                          bianl.standardization_input, bianl.approval_input, bianl.co_signature_input):
                    if w:
                        w.setEnabled(True)
            except Exception as e:
                print(f"[confirm_definition 恢复可编辑失败] {e}")

    # ======【项目管理页：脏标记与保存包装】======
    def _set_definition_edit_flag(self, *args):
        """当前产品行进入编辑：把 definition_status=edit"""
        try:
            row = bianl.product_table.currentRow()
            if row is None or row < 0:
                return
            row_status = bianl.product_table_row_status.get(row)
            if not isinstance(row_status, dict):
                return
            # 只有有 product_id 的行才算“已有定义，可编辑”
            if not row_status.get("product_id"):
                return
            if row_status.get("definition_status") != "edit":
                row_status["definition_status"] = "edit"
                print(f"【调试】第{row + 1}行 definition_status 置为 edit（用户开始修改定义/工作信息）")
        except Exception as e:
            print(f"[_set_definition_edit_flag] 异常: {e}")

    def _wire_definition_work_edit_signals(self):
        """把定义/工作信息控件的用户编辑信号 → 置为 edit"""
        # 定义区（用只在用户操作触发的信号）
        if bianl.product_type_combo:
            bianl.product_type_combo.activated.connect(self._set_definition_edit_flag)
        if bianl.product_form_combo:
            bianl.product_form_combo.activated.connect(self._set_definition_edit_flag)
        if bianl.product_model_input:
            bianl.product_model_input.textEdited.connect(self._set_definition_edit_flag)
        if bianl.drawing_prefix_input:
            bianl.drawing_prefix_input.textEdited.connect(self._set_definition_edit_flag)

        # 工作信息区
        for le in [
            bianl.design_input,
            bianl.proofread_input,
            bianl.review_input,
            bianl.standardization_input,
            bianl.approval_input,
            bianl.co_signature_input,
        ]:
            if le:
                le.textEdited.connect(self._set_definition_edit_flag)

    def _wire_dirty_signals(self):
        """仅对用户操作置脏：程序写值不置脏"""
        from PyQt5.QtCore import pyqtSignal

        # 1) 纯文本输入：用 textEdited（只在用户键入时触发）
        for le in [
            bianl.owner_input,
            bianl.project_number_input,
            bianl.project_name_input,
            bianl.department_input,
            bianl.contractor_input,
            bianl.project_path_input,
            bianl.product_model_input,
            bianl.drawing_prefix_input,
            bianl.design_input,
            bianl.proofread_input,
            bianl.review_input,
            bianl.standardization_input,
            bianl.approval_input,
            bianl.co_signature_input,
        ]:
            if le is not None:
                le.textEdited.connect(self._mark_dirty)

        # 2) 下拉框：用 activated（只在用户选择时触发；程序 setCurrentIndex 不触发）
        if bianl.product_type_combo is not None:
            bianl.product_type_combo.activated.connect(self._mark_dirty)
        if bianl.product_form_combo is not None:
            bianl.product_form_combo.activated.connect(self._mark_dirty)

        # 3) 日期：用户完成编辑时再置脏（程序 setDate 不触发）
        if bianl.date_edit is not None:
            bianl.date_edit.editingFinished.connect(self._mark_dirty)

        # 4) （可选）产品表：若你希望把“用户编辑表格”也计入脏，可以解开下面三行；
        #    注意：程序性写值同样会触发 itemChanged，若要区分需在写值处做 QSignalBlocker。
        # if bianl.product_table is not None:
        #     try:
        #         bianl.product_table.itemChanged.disconnect(self._mark_dirty_table)
        #     except Exception:
        #         pass
        #     bianl.product_table.itemChanged.connect(self._mark_dirty_table)

    def _mark_dirty(self, *args):
        self._dirty = True

    def _mark_dirty_table(self, *args):
        self._dirty = True

    def has_unsaved_changes(self) -> bool:
        """供主窗口关闭逻辑调用：是否有未保存修改（以精确检查为准）"""
        try:
            return not bool(self.check_if_all_saved())
        except Exception:
            # 兜底：万一检查异常，保守地看作“有未保存”
            return True

    def mark_clean(self):
        """保存成功后由本类标记为干净"""
        self._dirty = False

    def _on_save_clicked(self):
        """
        保存按钮包装：
        - 调用你原有的保存函数 project_confirm_btn.save_project_to_db()
        - 若返回 True 表示保存成功 → 清脏
          （若该函数无返回值，你可以在保存成功后主动调用 self.mark_clean()）
        """
        ok = False
        try:
            res = project_confirm_btn.save_project_to_db()
            # 约定：保存函数若返回布尔值，则以 True 视为成功
            ok = (res is True) or (res is None)  # 若无明确返回，默认按成功处理；如需严格，请改成 res is True
        except Exception as e:
            print(f"[项目管理][保存异常] {e}")
            ok = False

        if ok:
            self.mark_clean()
            # 建议：成功后，必要时可刷新一次界面并在刷新完成后保持 _dirty=False
            # 例如：self.reload_from_db(...)
# lxy新增结束
    def closeEvent(self, event):
        # 检查有没有保存
        if not self.check_if_all_saved():
            # 自定义按钮文本
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("未保存的更改")
            msg_box.setText("存在未保存的信息，是否仍要退出？")
            msg_box.setIcon(QMessageBox.Warning)

            # 自定义按钮
            yes_button = QPushButton("是")
            no_button = QPushButton("否")

            msg_box.addButton(yes_button, QMessageBox.YesRole)
            msg_box.addButton(no_button, QMessageBox.NoRole)

            # 显示对话框并获取结果
            result = msg_box.exec_()

            if msg_box.clickedButton() == no_button:
                event.ignore()  # 如果点击的是“否”，忽略退出操作
                return
        event.accept()
    # 检查是否进行保存
    def check_if_all_saved(self):
        print("【调试】开始检查是否有未保存数据...")

        # ---------------- 项目信息 ----------------
        print(f"【调试】当前 project_mode = {bianl.project_mode}")
        if bianl.project_mode in ("new", "edit"):
            project_fields = {
                "业主": bianl.owner_input.text().strip(),
                "项目名称": bianl.project_name_input.text().strip(),
                "项目路径": bianl.project_path_input.text().strip(),
                "项目编号": bianl.project_number_input.text().strip(),
                "所属部门": bianl.department_input.text().strip(),
                "工程总包方": bianl.contractor_input.text().strip(),
            }
            for label, value in project_fields.items():
                print(f"【调试】{label} = '{value}'")
            if any(project_fields.values()):
                print("【调试】项目信息已输入但未保存")
                return False
            else:
                print("【调试】项目信息为空")

        # ---------------- 产品信息 ----------------
        for row, status_dict in bianl.product_table_row_status.items():
            if not isinstance(status_dict, dict):
                continue
            status = status_dict.get("status", "view")
            print(f"【调试】[产品信息] 第{row + 1}行 status = {status}")
            if status == "view":
                continue

            for col in range(1, bianl.product_table.columnCount()):
                item = bianl.product_table.item(row, col)
                if item and item.text().strip():
                    print(f"【调试】第{row + 1}行产品信息有输入，未保存")
                    return False

        print("【调试】产品信息部分全部为空或为 view 状态")

        # ----------------lxy 产品定义 + 工作信息 ----------------
        for row, status_dict in bianl.product_table_row_status.items():
            if not isinstance(status_dict, dict):
                continue

            # ✅ 修正取键名
            def_status = status_dict.get("definition_status", "view")
            print(f"【调试】[产品定义] 第{row + 1}行 definition_status = {def_status}")

            if def_status == "edit":
                # 定义区
                definition_fields = {
                    "产品类型": bianl.product_type_combo.currentText().strip(),
                    "产品形式": bianl.product_form_combo.currentText().strip(),
                    "产品型号": bianl.product_model_input.text().strip(),
                    "图号前缀": bianl.drawing_prefix_input.text().strip(),
                }
                for label, value in definition_fields.items():
                    print(f"【调试】{label} = '{value}'")
                if any(definition_fields.values()):
                    print(f"【调试】第{row + 1}行产品定义字段有输入，未保存")
                    return False

                # 工作信息区
                work_fields = {
                    "设计": bianl.design_input.text().strip(),
                    "校对": bianl.proofread_input.text().strip(),
                    "审核": bianl.review_input.text().strip(),
                    "标准化": bianl.standardization_input.text().strip(),
                    "批准": bianl.approval_input.text().strip(),
                    "会签": bianl.co_signature_input.text().strip(),
                }
                for label, value in work_fields.items():
                    print(f"【调试】(工作信息) {label} = '{value}'")
                if any(work_fields.values()):
                    print(f"【调试】第{row + 1}行工作信息有输入，未保存")
                    return False

        # # ---------------- 产品定义 ----------------改66definition_status
        # for row, status_dict in bianl.product_table_row_status.items():
        #     if not isinstance(status_dict, dict):
        #         continue
        #     # def_status = status_dict.get("", "view")
        #     # === lxyFIX 1: 取对键名 ===
        #     def_status = status_dict.get("definition_status", "view")
        #     print(f"【调试】[产品定义] 第{row + 1}行 definition_status = {def_status}")
        #
        #     if def_status == "edit":
        #         definition_fields = {  # 改77
        #             "产品类型": bianl.product_type_combo.currentText().strip(),
        #             "产品形式": bianl.product_form_combo.currentText().strip(),
        #             "产品型号": bianl.product_model_input.text().strip(),
        #             "图号前缀": bianl.drawing_prefix_input.text().strip(),
        #         }
        #         for label, value in definition_fields.items():
        #             print(f"【调试】{label} = '{value}'")
        #         if any(definition_fields.values()):
        #             print(f"【调试】第{row + 1}行产品定义字段有输入，未保存")
        #             return False
        #         # === lxy工作信息：同一轮编辑一起判断（只要进入 edit，就认为这部分也可能在编辑）===
        #         work_fields = {
        #             "设计": bianl.design_input.text().strip(),
        #             "校对": bianl.proofread_input.text().strip(),
        #             "审核": bianl.review_input.text().strip(),
        #             "标准化": bianl.standardization_input.text().strip(),
        #             "批准": bianl.approval_input.text().strip(),
        #             "会签": bianl.co_signature_input.text().strip(),
        #         }
        #         for label, value in work_fields.items():
        #             print(f"【调试】(工作信息) {label} = '{value}'")
        #         if any(work_fields.values()):
        #             print(f"【调试】第{row + 1}行工作信息有输入，未保存")
        #             return False


        print("【调试】所有检查通过，无需提示未保存")
        return True

# if __name__ == "__main__":
#     App = QApplication(sys.argv)
#
#     stats = Stats()
#     stats.show()
#     # ✅ 添加初始化下拉框选项
#     main.load_product_types()
#     main.load_product_forms()
#     main.load_product_types_design_t()
#     sys.exit(App.exec_())

