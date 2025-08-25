import os
import sys
from collections import defaultdict
from urllib.parse import urljoin
from urllib.request import pathname2url

from PyQt5 import QtWidgets, uic, QtCore, QtGui
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import QApplication, QWidget, QTableWidgetItem, QMessageBox, QMenu, QAction, QComboBox, \
    QStyledItemDelegate, QPushButton, QTableWidget, QVBoxLayout, QTabWidget, QLabel, QAbstractItemView, QLineEdit, \
    QDialog

from modules import chanpinguanli
from modules.cailiaodingyi.controllers.rename import RenamableLineEdit
from modules.cailiaodingyi.controllers.table import CustomHeaderView
from modules.cailiaodingyi.controllers.template_handler import (
    handle_template_change,
    apply_combobox_to_table,
    set_table_tooltips
)
from modules.cailiaodingyi.controllers.datamanager import (
    handle_table_click,
    handle_guankou_table_click,
    on_confirm_param_update,
    on_confirm_guankouparam, apply_paramname_dependent_combobox, apply_paramname_combobox,
    apply_gk_paramname_combobox, bind_define_table_click,
)
from modules.cailiaodingyi.funcs.funcs_pdf_change import load_guankou_para_data_leibie, load_guankou_define_leibie, \
    load_updated_guankou_define_data, load_update_element_data, load_update_guankou_define_data, \
    load_update_guankou_para_data, get_design_params_by_product_id, update_guankou_param_by_param_name
from modules.cailiaodingyi.controllers.style import ReturnKeyJumpFilter
from modules.cailiaodingyi.funcs.funcs_pdf_input import (
    load_design_product_data,
    load_elementoriginal_data,
    load_element_details,
    move_guankou_to_first,
    load_guankou_define_data,
    load_guankou_material_detail,
    insert_element_data,
    insert_guankou_material_data,
    query_template_guankou_para_data,
    insert_guankou_para_data,
    query_template_element_para_data,
    insert_element_para_data,
    load_material_dropdown_values,
    select_template_id,
    insert_add_guankou_define,
    insert_all_guankou_param,
    has_product, query_all_guankou_categories, load_element_info, query_guankou_define_data_by_category,
    query_guankou_param_by_product, update_template_input_editable_state, is_all_defined_in_left_table,
    save_to_template_library, get_template_id_by_name, insert_updated_element_para_data, insert_guankou_define_data,
    insert_guankou_para_info, load_template, load_guankou_material_detail_template, get_grouped,
    update_material_category_in_db, query_guankou_param_by_template, load_guankou_param_leibie, load_guankou_param_byid,
    delete_guankou_data_from_db
)
from modules.chanpinguanli import chanpinguanli_main
from modules.chanpinguanli.chanpinguanli_main import product_manager
# from modules.condition_input.funcs.funcs_cdt_input import sync_corrosion_to_guankou_param
from modules.condition_input.view import DesignConditionInputViewer
from modules.guankoudingyi.dynamically_adjust_ui import Stats

product_id = None


def on_product_id_changed(new_id):
    print(f"Received new PRODUCT_ID: {new_id}")
    global product_id
    product_id = new_id


# 测试用产品 ID（真实情况中由外部输入）
product_manager.product_id_changed.connect(on_product_id_changed)

class DesignParameterDefineInputerViewer(QWidget):
    def __init__(self, line_tip=None, main_window=None):
        super().__init__()
        self.line_tip = line_tip
        self.main_window = main_window
        self.guankou_define_info = None
        self.ui = uic.loadUi("modules/cailiaodingyi/ui/paradefine_modified.ui", self)  # 加载UI文件
        self.init_widgets()  # 获取所有控件、绑定事件
        self.product_id = product_id
        print("self.product_id", self.product_id)
        self.product_type, self.product_form = load_design_product_data(self.product_id)
        # 初始化管口材料tab页列表
        self.dynamic_guankou_tabs = []
        self.dynamic_guankou_param_tabs = {}
        self.dynamic_guankou_define_tabs = {}
        self.load_original_data()
        # self.product_id = "PD20250526001"
        # self.product_type = "管壳式热交换器"
        # self.product_form = "BEU"
        self.dropdown_initialized = False

        # 回退筛选
        self.visible_rows_stack = []

        self.setWindowTitle("参数定义")

        # 监听下拉框选择变化
        self.comboBox_template.currentIndexChanged.connect(lambda idx: handle_template_change(self, idx))
        ## 绑定管口与右侧表格事件：选项变化时触发筛选函数
        self.tableWidget_parts.cellClicked.connect(self.handle_table_click_guankou)
    def init_widgets(self):
        # 获取界面中所有控件的对象
        self.comboBox_template = self.findChild(QtWidgets.QComboBox, "comboBox_template")
        self.tableWidget_parts = self.findChild(QtWidgets.QTableWidget, "tableWidget")
        self.tableWidget_parts.setHorizontalHeader(CustomHeaderView(QtCore.Qt.Horizontal, self.tableWidget_parts))
        self.tableWidget_parts.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tableWidget_parts.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.tableWidget_parts.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tableWidget_parts.installEventFilter(ReturnKeyJumpFilter(self.tableWidget_parts))
        self.stackedWidget = self.findChild(QtWidgets.QStackedWidget, "stackedWidget")
        self.textBrowser_part_image = self.findChild(QtWidgets.QTextBrowser, "textBrowser")
        # 获取右侧表格控件
        self.tableWidget_detail = self.findChild(QtWidgets.QTableWidget, "tableWidget_para")
        # 绘制非管口参数表头
        self.tableWidget_detail.setHorizontalHeader(CustomHeaderView(QtCore.Qt.Horizontal, self.tableWidget_detail))
        self.pushButton_detail = self.findChild(QPushButton, "pushButton_8")
        if self.pushButton_detail:
            self.pushButton_detail.clicked.connect(lambda: on_confirm_param_update(self))
        # 设置列宽自适应
        header = self.tableWidget_detail.horizontalHeader()
        for i in range(self.tableWidget_detail.columnCount()):
            header.setSectionResizeMode(i, QtWidgets.QHeaderView.Stretch)

        # 零件列表表格行高亮
        self.tableWidget_parts.itemSelectionChanged.connect(self.on_selection_changed)

        # 获取快速筛选输入框
        self.lineEdit_filter = self.findChild(QtWidgets.QLineEdit, "lineEdit")
        self.lineEdit_filter.setPlaceholderText("输入关键词筛选所有列...")
        self.lineEdit_filter.textChanged.connect(self.filter_table_globally)
        # 获取管口定义表格控件
        self.tableWidget_guankou_define = self.findChild(QtWidgets.QTableWidget, "tableWidget_define1")
        # 绘制管口定义表格

        self.tableWidget_guankou_define.setHorizontalHeader(CustomHeaderView(QtCore.Qt.Horizontal, self.tableWidget_guankou_define))
        self.tableWidget_guankou_define.cellClicked.connect(lambda row, col: handle_guankou_table_click(self, row, col))
        self.tableWidget_guankou_param = self.findChild(QtWidgets.QTableWidget, "tableWidget_gpara1")
        self.tableWidget_guankou_define.cellClicked.connect(lambda row, col: handle_guankou_table_click(self, row, col))
        # 绘制管口参数表格
        self.tableWidget_guankou_param.setHorizontalHeader(CustomHeaderView(QtCore.Qt.Horizontal, self.tableWidget_guankou_param))
        self.tableWidget_guankou_param.installEventFilter(ReturnKeyJumpFilter(self.tableWidget_guankou_param))

        self.label_part_image = self.findChild(QLabel, "label_4")
        print("self.label_part_image", self.label_part_image)
        # 管口参数定义的确定按钮
        self.pushButton_guankouparam = self.findChild(QPushButton, "pushButton_7")
        if self.pushButton_guankouparam:
            self.pushButton_guankouparam.clicked.connect(lambda: on_confirm_guankouparam(self))
        self.clicked_guankou_define_data = {}
        # 监听表格选中项变化，将选中的零件示意图显示到右侧
        self.tableWidget_parts.cellClicked.connect(lambda row, col: handle_table_click(self, row, col))

        self.tableWidget_parts.selectionModel().selectionChanged.connect(self.show_image_in_text_browser)
        # 针对模板选用
        self.comboBox_template.insertItem(0, "")
        self.comboBox_template.setCurrentIndex(0)  # 默认选中第0个，也就是空白
        # 对于非管口的零件获取参数定义表格
        self.tableWidget_para_define = self.findChild(QtWidgets.QTableWidget, "tableWidget_para")
        self.tableWidget_para_define.installEventFilter(ReturnKeyJumpFilter(self.tableWidget_para_define))

        # # 监控非管口的参数定义
        # self.tableWidget_para_define.itemChanged.connect(self.on_para_define_item_changed)

        # 对于非管口的零件参数表格设置高亮
        self.tableWidget_para_define.itemSelectionChanged.connect(self.on_param_table_selection_changed)

        # 监听添加管口材料分类按钮
        self.pushButton_add_guankou = self.findChild(QPushButton, "pushButton_6")
        self.pushButton_add_guankou.clicked.connect(lambda: self.add_guankou_category_tab(mode='add'))
        # 监听复制按钮
        self.pushButton_copy_guankou = self.findChild(QPushButton, "pushButton")
        self.pushButton_copy_guankou.clicked.connect(lambda: self.add_guankou_category_tab(mode='copy'))
        # 获取管口定义对应的tabs
        self.guankou_tabWidget = self.findChild(QTabWidget, "tabWidget")
        self.guankou_tabWidget.currentChanged.connect(self.on_tab_changed)
        # 第一个 tab 页
        self.default_guankou_tab_widget = self.guankou_tabWidget.widget(0)

        # 获取默认tab页的边框
        self.param_section_widget = self.findChild(QWidget, "param_section_widget")
        self.param_section_layout = self.param_section_widget.layout()
        # 消除 param_section_layout 的边距和间距
        self.param_section_layout.setContentsMargins(0, 0, 0, 0)
        self.param_section_layout.setSpacing(4)

        # 启用关闭按钮
        self.guankou_tabWidget.setTabsClosable(True)
        # 绑定关闭按钮事件
        self.guankou_tabWidget.tabCloseRequested.connect(self.remove_guankou_tab)

        # 监听双击 tab 重命名
        self.guankou_tabWidget.tabBarDoubleClicked.connect(self.on_tab_double_clicked)

        # 右键 tab 页
        self.guankou_tabWidget.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.guankou_tabWidget.tabBar().customContextMenuRequested.connect(self.on_tab_right_clicked)

        # 获取存为模板输入框
        self.lineEdit_template = self.findChild(QtWidgets.QLineEdit, "lineEdit_2")
        self.lineEdit_template.returnPressed.connect(self.on_template_name_entered)

        # 获取管口材料分类对应的下拉框
        self.guankou_material_category = self.findChild(QtWidgets.QComboBox, "comboBox_8")

        # self.tableWidget_parts.installEventFilter(ReturnKeyJumpFilter(self.tableWidget_parts))
        self.tableWidget_parts.installEventFilter(
            ReturnKeyJumpFilter(
                self.tableWidget_parts,
                after_jump_callback=lambda r, c: handle_table_click(self, r, c)
            )
        )
        self.tableWidget_guankou_param.installEventFilter(ReturnKeyJumpFilter(self.tableWidget_guankou_param))
        self.tableWidget_para_define.installEventFilter(ReturnKeyJumpFilter(self.tableWidget_para_define))

        # 用户修改，才标记未保存
        self.detail_table_modified = True

        # # 上一步下一步
        # self.last_button = self.findChild(QPushButton, "pushButton_4")
        # self.next_button = self.findChild(QPushButton, "pushButton_5")
        # self.last_button.clicked.connect(self.goto_previous_page)
        # self.next_button.clicked.connect(self.goto_next_page)



    def on_tab_changed(self, index):
        self.guankou_material_category.setCurrentIndex(0)

    def remove_guankou_tab(self, index):
        if self.guankou_tabWidget.count() <= 1:
            QMessageBox.information(self, "提示", "至少保留一个管口材料分类，不能删除最后一个 tab")
            return

        tab = self.guankou_tabWidget.widget(index)
        tab_name = self.guankou_tabWidget.tabText(index)

        print(f"[调试] 正在删除 tab: {tab_name}")
        if self.product_id:
            delete_guankou_data_from_db(self.product_id, tab_name)
        else:
            print("[警告] 当前 product_id 不存在，无法删除数据库记录")

        # ✅ 清理映射
        self.dynamic_guankou_param_tabs.pop(tab_name, None)
        self.dynamic_guankou_define_tabs.pop(tab_name, None)

        self.guankou_tabWidget.removeTab(index)


    def on_tab_double_clicked(self, index):
        """更改tab页标题"""
        if index == -1:
            return  # 用户双击了空白处

        tab_bar = self.guankou_tabWidget.tabBar()
        old_label = tab_bar.tabText(index)

        def confirm_edit(new_label):
            if not new_label or new_label == old_label:
                return

            existing_labels = [self.guankou_tabWidget.tabText(i) for i in range(self.guankou_tabWidget.count())]
            if new_label in existing_labels:
                QMessageBox.warning(self, "重名", "该名称已存在，请重新输入")
                return

            self.guankou_tabWidget.setTabText(index, new_label)
            self.dynamic_guankou_param_tabs[new_label] = self.dynamic_guankou_param_tabs.pop(old_label, None)
            self.dynamic_guankou_define_tabs[new_label] = self.dynamic_guankou_define_tabs.pop(old_label, None)
            update_material_category_in_db(self.product_id, old_label, new_label)
            print(f"[调试] tab 重命名：{old_label} → {new_label}")

        rect = tab_bar.tabRect(index)
        line_edit = RenamableLineEdit(old_label, confirm_edit, tab_bar)
        line_edit.setFrame(False)
        line_edit.setAlignment(Qt.AlignCenter)
        line_edit.setGeometry(rect)
        line_edit.setFocus()
        line_edit.selectAll()
        line_edit.show()

        def finish_edit():
            new_label = line_edit.text().strip()
            if not new_label or new_label == old_label:
                line_edit.deleteLater()
                return

            # ⚠️ 防止重名
            existing_labels = [self.guankou_tabWidget.tabText(i) for i in range(self.guankou_tabWidget.count())]
            if new_label in existing_labels:
                QMessageBox.warning(self, "重名", "该名称已存在，请重新输入")
                return

            self.guankou_tabWidget.setTabText(index, new_label)

            # ✅ 同步更新映射 dict
            self.dynamic_guankou_param_tabs[new_label] = self.dynamic_guankou_param_tabs.pop(old_label, None)
            self.dynamic_guankou_define_tabs[new_label] = self.dynamic_guankou_define_tabs.pop(old_label, None)

            # ✅ 可选：同步更新数据库中“类别”字段（建议）
            update_material_category_in_db(self.product_id, old_label, new_label)

            print(f"[调试] tab 重命名：{old_label} → {new_label}")
            line_edit.deleteLater()

        line_edit.editingFinished.connect(finish_edit)
        line_edit.show()

    def generate_unique_guankou_label(self, prefix="管口材料分类"):
        existing_labels = set(self.dynamic_guankou_param_tabs.keys())
        existing_labels.update([self.guankou_tabWidget.tabText(i) for i in range(self.guankou_tabWidget.count())])

        for i in range(1, 100):  # 最多允许99个
            label = f"{prefix}{i}"
            if label not in existing_labels:
                return label
        raise ValueError("管口材料分类数量超限，无法生成唯一标签")

    def on_tab_right_clicked(self, pos):
        tab_bar = self.guankou_tabWidget.tabBar()
        index = tab_bar.tabAt(pos)
        if index == -1:
            return

        menu = QMenu()
        enlarge_action = menu.addAction("放大查看参数表格")

        action = menu.exec_(tab_bar.mapToGlobal(pos))
        if action == enlarge_action:
            self.show_floating_table(index)

    def show_floating_table(self, tab_index):
        if self.guankou_tabWidget.widget(tab_index) is self.default_guankou_tab_widget:
            param_table = self.tableWidget_guankou_param
            tab_name = self.guankou_tabWidget.tabText(0)
        else:
            tab_name = self.guankou_tabWidget.tabText(tab_index)
            param_table = self.dynamic_guankou_param_tabs.get(tab_name)

        if not param_table:
            QMessageBox.warning(self, "未找到", f"未找到 {tab_name} 对应的参数表格")
            return

        float_win = QDialog(self)
        float_win.setWindowTitle(f"{tab_name} - 参数表格放大查看")
        float_win.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        float_win.resize(1200, 700)

        layout = QVBoxLayout(float_win)
        # ✅ 将原表格嵌入新窗口（注意不能重复 setParent，否则原位置会消失）
        shared_table = param_table  # ✅ 实际共享同一个表格

        layout.addWidget(shared_table)

        def restore_table():
            float_win.close()

            tab_widget = self.guankou_tabWidget.widget(tab_index)

            if tab_widget.objectName() == "tab":
                layout = self.param_section_layout
                param = self.tableWidget_guankou_param
                define = self.tableWidget_guankou_define

                other = define if shared_table == param else param

                # 安全移除原来的
                try:
                    old_parent = shared_table.parent()
                    if old_parent != tab_widget:
                        old_layout = old_parent.layout()
                        if old_layout:
                            old_layout.removeWidget(shared_table)
                except Exception as e:
                    print(f"[移除旧 parent 失败] {e}")

                def safe_remove(lay, w):
                    try:
                        if lay.indexOf(w) != -1:
                            lay.removeWidget(w)
                    except:
                        pass

                safe_remove(layout, shared_table)
                safe_remove(layout, other)

                # 插入，保持上下结构
                layout.addWidget(define)
                layout.addWidget(param)

            else:
                # 动态 tab 恢复
                layout = tab_widget.layout()
                try:
                    old_parent = shared_table.parent()
                    if old_parent and old_parent != tab_widget:
                        old_layout = old_parent.layout()
                        if old_layout:
                            old_layout.removeWidget(shared_table)
                except:
                    pass
                layout.addWidget(shared_table)

        float_win.finished.connect(restore_table)
        float_win.show()


    def goto_previous_page(self):
        if self.main_window:
            self.main_window.open_tab(
                "条件输入",
                DesignConditionInputViewer(
                    line_tip=self.line_tip, main_window=self.main_window)
            )

    def goto_next_page(self):
        if self.main_window:
            self.main_window.open_tab(
                "管口及附件定义",
                Stats(line_tip=self.line_tip, main_window=self.main_window)
            )

    def on_selection_changed(self):
        table = self.tableWidget_parts

        # 先恢复条纹背景
        for r in range(table.rowCount()):
            for c in range(table.columnCount()):
                item = table.item(r, c)
                if not item:
                    continue
                # 直接用硬编码色，模拟条纹 (你Designer里设定的可以替换这里)
                if r % 2 == 0:
                    item.setBackground(QColor("#ffffff"))  # 偶数行
                else:
                    item.setBackground(QColor("#f6f6f6"))  # 奇数行 (假设你的条纹色)

        selected_items = table.selectedItems()
        if not selected_items:
            return

        selected_cells = set((item.row(), item.column()) for item in selected_items)
        selected_rows = set(r for r, _ in selected_cells)

        for row in selected_rows:
            for c in range(table.columnCount()):
                if (row, c) in selected_cells:
                    continue  # 系统选中项不动
                item = table.item(row, c)
                if item:
                    item.setBackground(QColor("#d0e7ff"))  # 高亮色

    def show_error_message(self, title, message):
        # 创建QMessageBox来显示错误信息
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Critical)  # 设置为错误图标
        msg_box.setWindowTitle(title)  # 设置窗口标题
        msg_box.setText(message)  # 设置显示的错误信息
        msg_box.setStandardButtons(QMessageBox.Ok)  # 设置“确定”按钮
        msg_box.exec_()  # 显示弹窗

    def show_info_message(self, title, message):
        # 创建QMessageBox来显示正常提示信息
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Information)  # 设置为信息图标
        msg_box.setWindowTitle(title)  # 设置窗口标题
        msg_box.setText(message)  # 设置显示的提示信息
        msg_box.setStandardButtons(QMessageBox.Ok)  # 设置“确定”按钮
        msg_box.exec_()  # 显示弹窗


    def populate_guankou_combo(self, combo_box):

        results = get_grouped(product_id)

        category_dict = defaultdict(list)
        for row in results:
            category = row['类别']
            code = row['管口代号']
            category_dict[category].append(code)

        combo_items = [
            ';'.join(codes)
            for category, codes in category_dict.items()
        ]

        combo_box.clear()
        combo_box.addItem("选择管口分配")  # 默认提示项
        combo_box.addItems(combo_items)
        combo_box.setCurrentIndex(0)


    def update_template_input_editable_state(self):
        """
        根据当前 comboBox_template 的内容来启用或禁用 '存为模板' 输入框
        """
        current_template = self.comboBox_template.currentText()
        if not current_template or current_template == "None":
            # 没有模板
            self.lineEdit_template.setEnabled(False)
        else:
            # 有模板
            self.lineEdit_template.setEnabled(True)


    def load_original_data(self):

        # 如果模板名称为空，则设置为 "None"字符串
        template_name = "None"
        self.product_type, self.product_form = load_design_product_data(product_id)
        self.product_id = product_id

        template_names = load_template(self.product_type, self.product_form)
        template_list = [
            "" if row['模板名称'] == "None" else row['模板名称']
            for row in template_names
        ]

        self.comboBox_template.clear()
        self.comboBox_template.addItems(template_list)
        # 默认选中空白项
        index_blank = template_list.index("") if "" in template_list else 0
        self.comboBox_template.setCurrentIndex(index_blank)

        self.populate_guankou_combo(self.guankou_material_category)
        print("绑定下拉框对象：", self.guankou_material_category)
        # 替代原本的直接 connect 和赋值
        QTimer.singleShot(0, lambda: (
            self.guankou_material_category.currentIndexChanged[int].connect(self.on_guankou_selected),
            setattr(self, 'dropdown_initialized', True)
        ))
        # 检查产品设计活动库数据
        if has_product(product_id):
            # 获取零件列表信息
            element_original_info = load_element_info(product_id)
            template_name_from_db = element_original_info[0].get("模板名称", "None")
            index = self.comboBox_template.findText(template_name_from_db)
            if index != -1:
                self.comboBox_template.setCurrentIndex(index)
            else:
                print(f"模板下拉框中找不到：{template_name_from_db}")

            #zhange
            if not template_name_from_db or template_name_from_db == "None":
                # 模板名称为空或者默认无模板，存为模板输入框禁用
                self.lineEdit_template.setEnabled(False)
            else:
                # 有模板名称，存为模板输入框启用
                self.lineEdit_template.setEnabled(True)


            guankou_define_dict = {}
            category_labels = query_all_guankou_categories(product_id)
            print(11111111111111111,category_labels)
            for label in category_labels:
                define_data = query_guankou_define_data_by_category(product_id, label)
                guankou_define_dict[label] = define_data
                print("111111111111111", guankou_define_dict[label])
                self.label = label


        # 从模板库中读数据
        elif self.product_type and self.product_form:

            # zhange
            self.lineEdit_template.setEnabled(False)  # 首次无模板，禁用输入框


            element_original_info = load_elementoriginal_data(template_name, self.product_type, self.product_form)
            insert_element_data(element_original_info, product_id, template_name)
            if not element_original_info:
                self.show_error_message("数据加载错误", "没有找到零件数据")
                return

            first_template_id = element_original_info[0].get('模板ID', None)
            guankou_para_info = query_template_guankou_para_data(first_template_id)
            insert_guankou_para_data(product_id, guankou_para_info, template_name)

            element_para_info = query_template_element_para_data(first_template_id)
            insert_element_para_data(product_id, element_para_info)

            guankou_define_info = load_guankou_define_data(self.product_type, self.product_form, first_template_id)
            insert_guankou_material_data(guankou_define_info, product_id, template_name)
            guankou_define_dict = {"管口材料分类1": guankou_define_info}
            print(f"模板对应的数据{guankou_define_dict}")

        else:
            self.show_info_message("提示", "未选择产品，界面以空白状态打开。")

            #zhange
            self.lineEdit_template.setEnabled(False)  # 界面空白，禁用输入框


            return

        # 渲染零件列表数据(包括零件示意图)
        element_original_info = move_guankou_to_first(element_original_info)
        self.element_data = element_original_info
        self.render_data_to_table(element_original_info)


        # 渲染到表格
        self.render_data_to_table(element_original_info)

        # 存为模板
        # update_template_input_editable_state(self)
        # 存储零件的示意图路径，以便后续使用
        self.image_paths = [item.get('零件示意图', '') for item in element_original_info]  # 假设返回的字段名是 '零件示意图'
        if self.image_paths:
            QTimer.singleShot(1, lambda: self.display_image(self.image_paths[0]))
        # 清空旧 tab 页
        while self.guankou_tabWidget.count() > 1:
            self.guankou_tabWidget.removeTab(1)

        # 假设你的 UI 中默认 tab 是“管口材料分类1”
        category_label = "管口材料分类1"
        data = guankou_define_dict[category_label]
        print(f"data{data}")
        self.guankou_define_info = data

        # 使用 UI 里已有的表格控件
        table_define = self.tableWidget_guankou_define
        table_param = self.tableWidget_guankou_param

        self.render_guankou_param_table(table_define, data)
        # 绑定下拉框
        dropdown_data = load_material_dropdown_values()
        column_index_map = {'材料类型': 1, '材料牌号': 2, '材料标准': 3, '供货状态': 4}
        column_data_map = {column_index_map[k]: v for k, v in dropdown_data.items()}
        apply_combobox_to_table(table_define, column_data_map, data, self.product_id, self,
                                category_label=category_label)
        set_table_tooltips(table_define)

        # 渲染下半参数表
        if data:
            first_id = data[0].get("管口零件ID", None)
            if first_id:
                if has_product(product_id):
                    param_data = query_guankou_param_by_product(self.product_id, first_id, category_label)
                else:
                    param_data = query_guankou_param_by_template(first_id, category_label)
                if param_data:
                    self.render_guankou_material_detail_table(table_param, param_data)
                    param_options = load_material_dropdown_values()
                    # apply_paramname_dependent_combobox(
                    #     self.tableWidget_guankou_param,
                    #     param_col=0,
                    #     value_col=1,
                    #     param_options=param_options
                    # )
                    apply_gk_paramname_combobox(
                        self.tableWidget_guankou_param,
                        param_col=0,
                        value_col=1
                    )

        bind_define_table_click(self, table_define, table_param, data, category_label)

        # 行点击绑定
        table_define.cellClicked.connect(
            lambda row, col, d=data, p=table_param, label=category_label:
            self.on_define_table_clicked(row, d, p, label)
        )

        for category_label, data in guankou_define_dict.items():
            if category_label == "管口材料分类1":
                continue  # 已处理，跳过
            # 创建 tab 页容器和布局
            tab = QWidget()
            layout = QVBoxLayout(tab)

            # 创建上表格（管口定义）
            table_define = QTableWidget()
            table_define.setHorizontalHeader(CustomHeaderView(QtCore.Qt.Horizontal, table_define))
            table_define.setObjectName(f"table_define_{category_label}")
            layout.addWidget(table_define)

            # 创建下表格（参数信息）
            table_param = QTableWidget()
            table_param.setHorizontalHeader(CustomHeaderView(QtCore.Qt.Horizontal, table_param))
            table_param.setObjectName(f"table_param_{category_label}")
            layout.addWidget(table_param)

            # 添加 tab 到 QTabWidget
            self.guankou_tabWidget.addTab(tab, category_label)

            # 渲染上表格
            self.render_guankou_param_table(table_define, data)

            # 下拉框绑定
            dropdown_data = load_material_dropdown_values()
            column_index_map = {'材料类型': 1, '材料牌号': 2, '材料标准': 3, '供货状态': 4}
            column_data_map = {column_index_map[k]: v for k, v in dropdown_data.items()}
            apply_combobox_to_table(table_define, column_data_map, data,
                                    self.product_id, self, category_label=category_label)
            set_table_tooltips(table_define)

            # 渲染默认参数（定义表的第一条）
            if data:
                first_id = data[0].get("管口零件ID", None)
                if first_id:
                    if has_product(product_id):
                        # sync_corrosion_to_guankou_param(product_id)
                        param_data = query_guankou_param_by_product(self.product_id, first_id, category_label)
                    else:
                        param_data = query_template_guankou_para_data(first_id)
                    if param_data:
                        self.render_guankou_material_detail_table(table_param, param_data)
                        param_options = load_material_dropdown_values()
                        apply_paramname_dependent_combobox(
                            table_param,
                            param_col=0,
                            value_col=1,
                            param_options=param_options
                        )
                        apply_gk_paramname_combobox(
                            table_param,
                            param_col=0,
                            value_col=1
                        )

                # 添加 "+" 标签页


            def make_handler(table_def, table_par, label):
                return lambda row, col: self._on_define_row_clicked(table_def, table_par, row, label)

            table_define.cellClicked.connect(
                lambda row, col, d=data, p=table_param, label=category_label:
                self.on_define_table_clicked(row, d, p, label)

            )


            # ✅ 遍历已有的 tab 页，补充 dynamic_guankou_xxx_tabs 映射
            for i in range(self.guankou_tabWidget.count()):
                print(f"[调试] 当前 tab 数量: {self.guankou_tabWidget.count()}")

                tab_widget = self.guankou_tabWidget.widget(i)
                print(f"tab{tab_widget}")
                tab_name = self.guankou_tabWidget.tabText(i)
                print(f"tabname{tab_name}")

                # 跳过第一个默认 tab（通常已初始化）
                if tab_name == "管口材料分类1":
                    continue

                # 在 tab_widget 中查找两个表格
                try:
                    tables = tab_widget.findChildren(QTableWidget)
                    print(f"tables = {tables}")  # ✅ 输出完整的列表
                    if len(tables) >= 2:
                        define_table = tables[0]
                        param_table = tables[1]
                        print(f"define_table = {define_table}")
                        print(f"param_table = {param_table}")

                        self.dynamic_guankou_define_tabs[tab_name] = define_table
                        self.dynamic_guankou_param_tabs[tab_name] = param_table
                        print(f"[调试] viewer_instance ID: {id(self)}")

                        print(f"[恢复] 注册 {tab_name} → 定义表格 {define_table}，参数表格 {param_table}")
                    else:
                        print(f"[警告] 未找到 {tab_name} 中的两个表格，当前获取到表格数量: {len(tables)}")
                except Exception as e:
                    print(f"[异常] 恢复 tab 时出错: {e}")
        # 创建一个加号按钮
        plus_button = QPushButton("+")
        plus_button.setFixedSize(20, 20)
        plus_button.setStyleSheet("QPushButton { border: none; font-weight: bold; }")

        # 将加号按钮放在 QTabWidget 的右上角（右上角跟随 Tab 标签）
        self.tabWidget.setCornerWidget(plus_button, corner=Qt.TopRightCorner)

        # 加号点击连接逻辑
        # plus_button.clicked.connect(复制)
        plus_button.clicked.connect(lambda: self.add_guankou_category_tab(mode='copy'))

        # zhange
        self.comboBox_template.currentIndexChanged.connect(self.update_template_input_editable_state)
        # 初始执行一次，保证状态正确
        self.update_template_input_editable_state()






    def render_data_to_table(self, element_original_info):
        # 获取表格控件
        table = self.tableWidget_parts

        # 清理原有数据（防止重复）
        table.clear()

        # 设置表格的列标题
        headers = ["序号", "零件名称", "材料类型", "材料牌号", "材料标准", "供货状态", "有无覆层", "是否定义",
                   "所属部件"]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)

        # 设置表格的行数为数据条数
        table.setRowCount(len(element_original_info))

        # 启用表头点击事件
        header = table.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSectionsMovable(True)
        try:
            header.sectionClicked.disconnect(self.on_header_clicked)
        except TypeError:
            pass
        header.sectionClicked.connect(self.on_header_clicked)

        # 设置列宽
        for i in range(table.columnCount()):
            if i in (0, 7, 8):
                header.setSectionResizeMode(i, QtWidgets.QHeaderView.ResizeToContents)
            else:
                header.setSectionResizeMode(i, QtWidgets.QHeaderView.Stretch)

        # 强制不出现水平滚动条
        table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        # 让表头更高一点，留出分隔感
        table.horizontalHeader().setFixedHeight(35)

        # 用 QSS 尝试在表头底部挤出视觉间隔
        table.setStyleSheet("""
        QHeaderView::section {
            padding-bottom: 5px;
            background-color: #f9f9f9;
            border: none;
        }
        QTableWidget::item {
            margin-top: 2px;
        }
        """)

        # 限制最后一列最大宽度（可选）
        last_col = table.columnCount() - 1
        table.setColumnWidth(last_col, 100)

        # 遍历数据并填入表格
        for row_index, row_data in enumerate(element_original_info):
            for col_idx, key in enumerate(headers):
                if key == "序号":
                    item = QTableWidgetItem(f"{row_index + 1:02d}")
                else:
                    item = QTableWidgetItem(str(row_data.get(key, "")))
                item.setTextAlignment(Qt.AlignCenter)
                item.setToolTip(item.text())  # ✅ 添加悬浮提示
                table.setItem(row_index, col_idx, item)

        # ✅ 视觉分隔效果【核心】
        table.setShowGrid(True)
        table.setGridStyle(QtCore.Qt.SolidLine)
        table.setStyleSheet("QTableWidget { gridline-color: lightgray; }")

    def on_header_clicked(self, column):
        """表头点击事件：显示筛选菜单"""
        table = self.tableWidget_parts
        header = table.horizontalHeader()
        header_text = table.horizontalHeaderItem(column).text()

        # 创建菜单
        menu = QtWidgets.QMenu(self)

        # 添加排序和筛选选项
        sort_asc_action = menu.addAction(f"升序排序 ({header_text})")
        sort_desc_action = menu.addAction(f"降序排序 ({header_text})")
        menu.addSeparator()

        # 添加筛选选项
        filter_menu = menu.addMenu("筛选")
        filter_all_action = filter_menu.addAction("显示全部")
        reset_filter_action = filter_menu.addAction("重置筛选（清空所有记录）")
        filter_menu.addSeparator()

        # 只考虑当前未隐藏的行
        visible_values = set()
        for row in range(table.rowCount()):
            if not table.isRowHidden(row):
                item = table.item(row, column)
                if item:
                    visible_values.add(item.text())

        for value in sorted(visible_values):
            filter_action = filter_menu.addAction(value)

        # 显示菜单并等待用户选择
        selected_action = menu.exec_(QtGui.QCursor.pos())

        # 处理用户选择
        if selected_action == sort_asc_action:
            table.sortItems(column, Qt.AscendingOrder)
        elif selected_action == sort_desc_action:
            table.sortItems(column, Qt.DescendingOrder)
        elif selected_action == filter_all_action:
            if self.visible_rows_stack:
                previous_visible = self.visible_rows_stack.pop()
                for row in range(table.rowCount()):
                    table.setRowHidden(row, row not in previous_visible)
            else:
                for row in range(table.rowCount()):
                    table.setRowHidden(row, False)

        elif selected_action == reset_filter_action:
            self.visible_rows_stack.clear()
            for row in range(table.rowCount()):
                table.setRowHidden(row, False)
        elif selected_action in filter_menu.actions():
            filter_value = selected_action.text()
            current_visible_rows = [row for row in range(table.rowCount()) if not table.isRowHidden(row)]
            self.visible_rows_stack.append(current_visible_rows)
            for row in current_visible_rows:
                item = table.item(row, column)
                if not item or item.text() != filter_value:
                    table.setRowHidden(row, True)
        menu.close()
        # 关键修复：取消表头选中状态
        header.setHighlightSections(False)  # 禁用高亮
        header.clearSelection()  # 清除选中状态
        table.clearSelection()  # 清除表格单元格的选中状态（可选）

    def filter_table_globally(self, keyword):
        """全局筛选：匹配所有列的任意单元格"""
        table = self.tableWidget_parts
        keyword = keyword.strip().lower()  # 忽略大小写和前后空格
        # 遍历所有行（跳过表头筛选行）
        for row in range(0, table.rowCount()):  # 假设第0行是筛选行
            row_visible = False
            # 检查当前行的每一列是否匹配关键词
            for col in range(table.columnCount()):
                item = table.item(row, col)
                if item and keyword in item.text().lower():
                    row_visible = True
                    break  # 只要有一列匹配就显示该行

            # 设置行可见性
            table.setRowHidden(row, not row_visible)

    def show_image_in_text_browser(self, selected, deselected):
        # 获取选中的行
        selected_row = self.tableWidget_parts.selectedIndexes()

        if selected_row:
            row = selected_row[0].row()  # 获取选中行的索引
            # print(f"Selected row index: {row}")

            # 从内存中获取零件示意图的路径
            if row < len(self.image_paths):  # 确保索引有效
                image_path = self.image_paths[row]
                # print(f"Image path: {image_path}")

                # 显示图片到右侧的QTextBrowser控件
                self.display_image(image_path)
            else:
                self.show_error_message("无效的行索引", "所选行没有有效的图片路径。")
        else:
            print("No row selected")

    def display_image(self, image_path):
        if not image_path:
            self.label_part_image.clear()
            return

        image_path = os.path.normpath(image_path.strip())
        if not os.path.isabs(image_path):
            base_dir = os.path.dirname(os.path.abspath(__file__))
            # 这里添加 img 目录
            abs_path = os.path.join(base_dir, "img", image_path)
        else:
            abs_path = image_path

        if not os.path.exists(abs_path):
            print(f"[警告] 图片路径不存在: {abs_path}")
            self.label_part_image.clear()
            return

        pixmap = QPixmap(abs_path)
        if pixmap.isNull():
            print(f"[警告] 图片无法加载: {abs_path}")
            self.label_part_image.clear()
            return

        # ✅ 获取控件实际尺寸
        label_size = self.label_part_image.size()
        if label_size.width() <= 0 or label_size.height() <= 0:
            print("[提示] QLabel 尺寸未准备好，跳过")
            return

        # ✅ 使用 Qt.SmoothTransformation 进行平滑缩放
        scaled_pixmap = pixmap.scaled(
            label_size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

        # ✅ 设置图片
        self.label_part_image.setPixmap(scaled_pixmap)
        self.label_part_image.setAlignment(Qt.AlignCenter)

    def render_details_to_table(self, element_details):
        print("render_details_to_table called")

        if self.first_element_id:
            print(f"Calling load_element_details with element_id: {self.first_element_id}")
            element_details = load_element_details(self.first_element_id)
        else:
            print("没有找到元件ID")
            return

        details_table = self.tableWidget_detail
        headers = ["参数名称", "参数数值", "参数单位"]

        details_table.setColumnCount(len(headers))
        details_table.setRowCount(len(element_details))
        details_table.setHorizontalHeaderLabels(headers)

        header = details_table.horizontalHeader()
        for i in range(details_table.columnCount()):
            header.setSectionResizeMode(i, QtWidgets.QHeaderView.Stretch)

        for row_index, row_data in enumerate(element_details):
            for col_idx, header_name in enumerate(headers):
                item = QTableWidgetItem(str(row_data.get(header_name, "")))
                item.setTextAlignment(QtCore.Qt.AlignCenter)

                # ✅ 设置只读（不可编辑）列：参数名称 和 参数单位
                if col_idx in [0, 2]:  # 参数名称列 和 参数单位列
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)

                details_table.setItem(row_index, col_idx, item)

    def render_guankou_param_table(self, table: QTableWidget, guankou_param_info):

        """渲染上半部分管口参数表"""

        headers = ["零件名称", "材料类型", "材料牌号", "材料标准", "供货状态"]
        table.setColumnCount(len(headers))
        table.setRowCount(len(guankou_param_info))
        table.setHorizontalHeaderLabels(headers)

        header = table.horizontalHeader()

        # 隐藏列序号
        table.verticalHeader().setVisible(False)

        for i in range(table.columnCount()):
            header.setSectionResizeMode(i, QtWidgets.QHeaderView.Stretch)

        for row_index, row_data in enumerate(guankou_param_info):
            for col_idx, header_name in enumerate(headers):
                item = QTableWidgetItem(str(row_data.get(header_name, "")))
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_index, col_idx, item)

    def render_guankou_material_detail_table(self, table: QTableWidget, material_details):

        """渲染右下半部分管口零件材料详细表"""
        # 清空现有数据
        print(f"覆盖")
        table.clear()  # 清除所有行列和表头
        table.setRowCount(0)
        table.setColumnCount(0)

        headers = ["参数名称", "参数值", "参数单位"]
        table.setColumnCount(len(headers))
        table.setRowCount(len(material_details))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)

        header = table.horizontalHeader()

        # 隐藏列序号
        table.verticalHeader().setVisible(False)

        for i in range(table.columnCount()):
            header.setSectionResizeMode(i, QtWidgets.QHeaderView.Stretch)

        for row_index, row_data in enumerate(material_details):
            for col_idx, header_name in enumerate(headers):
                item = QTableWidgetItem(str(row_data.get(header_name, "")))
                item.setTextAlignment(QtCore.Qt.AlignCenter)

                # ✅ 设置只读（不可编辑）列：参数名称 和 参数单位
                if col_idx in [0, 2]:  # 参数名称列 和 参数单位列
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)

                table.setItem(row_index, col_idx, item)

    def add_guankou_category_tab(self, mode='add'):
        print(f"[调试] 开始执行 add_guankou_category_tab，模式: {mode}")
        new_tab = QWidget()
        table_guankou_define = QTableWidget()
        table_guankou_param = QTableWidget()
        table_guankou_define.setHorizontalHeader(CustomHeaderView(QtCore.Qt.Horizontal, table_guankou_define))
        table_guankou_param.setHorizontalHeader(CustomHeaderView(QtCore.Qt.Horizontal, table_guankou_param))
        table_guankou_define.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        table_guankou_param.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)

        upper_layout = QtWidgets.QVBoxLayout()
        upper_layout.addWidget(table_guankou_define)
        lower_layout = QtWidgets.QVBoxLayout()
        lower_layout.addWidget(table_guankou_param)
        main_layout = QtWidgets.QVBoxLayout()
        main_layout.addLayout(upper_layout, 1)
        main_layout.addLayout(lower_layout, 1)
        new_tab.setLayout(main_layout)

        # ✅ 使用唯一 tab 名
        tab_label = self.generate_unique_guankou_label()
        category_label = tab_label
        print(f"[调试] 新 tab_label = {tab_label}")

        index = self.guankou_tabWidget.addTab(new_tab, tab_label)

        # 注册映射
        self.dynamic_guankou_param_tabs[tab_label] = table_guankou_param
        self.dynamic_guankou_define_tabs[tab_label] = table_guankou_define

        select_template = self.comboBox_template.currentText() or 'None'
        print(f"[调试] 当前选择的模板: {select_template}")
        template_id = select_template_id(select_template, self.product_form, self.product_type)
        print(f"[调试] 模板ID: {template_id}, 分类标签: {category_label}")

        if mode == 'add':
            guankou_define_data = load_guankou_define_data(self.product_type, self.product_form, template_id)
            insert_add_guankou_define(guankou_define_data, category_label, self.product_id, select_template)
            self.render_guankou_param_table(table_guankou_define, guankou_define_data)
        elif mode == 'copy':
            current_index = self.guankou_tabWidget.currentIndex()
            current_tab = self.guankou_tabWidget.tabText(current_index)
            guankou_define_data = load_guankou_define_leibie(current_tab, self.product_id, select_template)
            insert_add_guankou_define(guankou_define_data, category_label, self.product_id, select_template)
            self.render_guankou_param_table(table_guankou_define, guankou_define_data)

        dropdown_data = load_material_dropdown_values()
        column_index_map = {'材料类型': 1, '材料牌号': 2, '材料标准': 3, '供货状态': 4}
        column_data_map = {column_index_map[k]: v for k, v in dropdown_data.items()}
        apply_combobox_to_table(table_guankou_define, column_data_map, guankou_define_data,
                                self.product_id, self, category_label)
        self.guankou_define_info = guankou_define_data
        set_table_tooltips(table_guankou_define)

        table_guankou_define.cellClicked.connect(
            lambda row, col, d=guankou_define_data, t=table_guankou_param, c=category_label:
            self.on_define_table_clicked(row, d, t, c)
        )

        if mode == 'add':
            guankou_param_id = guankou_define_data[0].get('管口零件ID')
            guankou_param_data = load_guankou_material_detail_template(guankou_param_id, template_id)
            ca_map = get_design_params_by_product_id(self.product_id)
            tube_ca = ca_map.get("腐蚀裕量*", {}).get("管程数值", "")
            shell_ca = ca_map.get("腐蚀裕量*", {}).get("壳程数值", "")
            for item in guankou_param_data:
                if item.get("参数名称") == "管程接管腐蚀裕量" and tube_ca != "":
                    item["参数值"] = str(tube_ca)
                elif item.get("参数名称") == "壳程接管腐蚀裕量" and shell_ca != "":
                    item["参数值"] = str(shell_ca)
                    break
            print(f"[调试] 新增的管口零件参数信息: {guankou_param_data}")
            all_guankou_param_data = query_template_guankou_para_data(template_id)
            insert_all_guankou_param(all_guankou_param_data, category_label, self.product_id, select_template)
            # sync_corrosion_to_guankou_param(self.product_id)
            self.render_guankou_material_detail_table(table_guankou_param, guankou_param_data)
        elif mode == 'copy':
            current_index = self.guankou_tabWidget.currentIndex()
            current_tab = self.guankou_tabWidget.tabText(current_index)
            guankou_param_data = load_guankou_param_leibie(current_tab, self.product_id, select_template)
            guankou_param_id = guankou_define_data[0].get('管口零件ID')
            guankou_param = load_guankou_param_byid(current_tab, self.product_id, select_template, guankou_param_id)
            self.render_guankou_material_detail_table(table_guankou_param, guankou_param)
            insert_all_guankou_param(guankou_param_data, category_label, self.product_id, select_template)

        apply_gk_paramname_combobox(table_guankou_param, param_col=0, value_col=1)
        self.dynamic_guankou_tabs.append(new_tab)

    def on_define_table_clicked(self, row, define_data, table_param, category_label):
        """
        监控添加管口零件分类的材料定义
        """

        guankou_row = define_data[row] if row < len(define_data) else {}
        print(f"管口定义{guankou_row}")
        guankou_id = guankou_row.get('管口零件ID')
        part_name = guankou_row.get('零件名称', '')


        if not guankou_id:
            print("[调试] 跳过：无有效管口ID")
            return  # 避免空数据覆盖

        # 保存当前点击项（供后续使用）
        self.clicked_guankou_define_data = guankou_row
        self.clicked_guankou_define_data["类别"] = category_label
        image_path = guankou_row.get('元件示意图')
        self.display_image(image_path)

        # 查询参数：先查产品库，再查模板库
        param_data = query_guankou_param_by_product(self.product_id, guankou_id, category_label)
        print(f"当前产品{self.product_id}，当前管口ID{guankou_id}，当前类别{category_label}")
        print(f"产品库数据{param_data}")

        if not param_data:
            param_data = query_guankou_param_by_template(guankou_id, category_label, )
            print(f"材料库数据{param_data}")

        if param_data:
            self.render_guankou_material_detail_table(table_param, param_data)
            param_row_data = param_data[0]  # ✅ 取出第一行参数数据当作 component_info


            # 绑定参数下拉逻辑
            param_options = load_material_dropdown_values()
            # apply_paramname_dependent_combobox(
            #     self.tableWidget_guankou_param,
            #     param_col=0,
            #     value_col=1,
            #     param_options=param_options,
            #     component_info=guankou_row,
            #     viewer_instance=self
            # )
            # apply_paramname_dependent_combobox(
            #     table_param,
            #     param_col=0,
            #     value_col=1,
            #     param_options=param_options
            # )
            apply_gk_paramname_combobox(
                table_param,
                param_col=0,
                value_col=1,
                component_info=param_row_data,
                viewer_instance=self
            )
        else:
            # 无数据时清空参数表格（防止显示旧内容）
            table_param.clear()
            table_param.setRowCount(0)
            table_param.setColumnCount(3)
            table_param.setHorizontalHeaderLabels(["参数名称", "参数值", "参数单位"])


    def handle_table_click_guankou(self, row, column):
        # 获取当前行的“零件名称”
        part_name_item = self.tableWidget_parts.item(row, 1)
        if part_name_item and part_name_item.text() == "管口":
            self.stackedWidget.setCurrentIndex(0)
        else:
            self.stackedWidget.setCurrentIndex(1)

    # 监控存为模板输入框
    def on_template_name_entered(self):

        template_name = self.lineEdit_template.text().strip()
        print(f"当前输入的模板名称{template_name}")
        if not template_name:
            self.show_error_message("提示", "请输入模板名称后再按回车。")
            return

        # 判断左侧表格是否全部为“已定义”
        # if not is_all_defined_in_left_table(self.tableWidget_parts, define_status_col=7):  # 假设定义状态列是第7列
        #     self.show_error_message("提示", "还有未定义的零件，不能保存为模板。")
        #     return

        # 查询产品设计活动库数据
        product_data = load_element_info(self.product_id)

        if not product_data:
            self.show_error_message("错误", "未找到产品材料数据。")
            return

        # 写入模板库
        save_to_template_library(template_name, product_data, self.product_type, self.product_form)
        self.show_info_message("模板保存成功", f"模板 '{template_name}' 已保存到材料库。")


        # 根据用户输入的模板名称去材料库中查找对应的模板ID
        template_id = get_template_id_by_name(template_name)
        if template_id is not None:
            print(f"查询到模板ID：{template_id}")
            updated_element_para = load_update_element_data(self.product_id)
            insert_updated_element_para_data(template_id, updated_element_para)
            updated_guankou_define = load_update_guankou_define_data(self.product_id)
            insert_guankou_define_data(template_id, updated_guankou_define, self.product_type, self.product_form)
            updated_guankou_para = load_update_guankou_para_data(self.product_id)
            print(f"当前管口参数信息{updated_guankou_para}")
            insert_guankou_para_info(template_id, updated_guankou_para)
        else:
            print("未找到对应模板ID")

    def on_guankou_selected(self, index):

        if not getattr(self, 'dropdown_initialized', False):
            return

        if index == 0:
            return

        selected_text = self.guankou_material_category.currentText()

        codes = selected_text.split(';')

        current_tab_index = self.guankou_tabWidget.currentIndex()
        material_category = self.guankou_tabWidget.tabText(current_tab_index)

        update_material_category_in_db(codes, material_category)

    def on_param_table_selection_changed(self):
        table = self.tableWidget_para_define

        selected_items = table.selectedItems()
        selected_cells = {(item.row(), item.column()) for item in selected_items}
        selected_rows = {row for row, _ in selected_cells}

        # 1. 清除所有背景
        for r in range(table.rowCount()):
            for c in range(table.columnCount()):
                item = table.item(r, c)
                if item:
                    if (r, c) in selected_cells:
                        continue  # 保留深蓝
                    item.setBackground(Qt.white)

        # 2. 高亮选中行其他未选中单元格
        for row in selected_rows:
            for col in range(table.columnCount()):
                if (row, col) in selected_cells:
                    continue
                item = table.item(row, col)
                if item:
                    item.setBackground(QColor("#d0e7ff"))


# def startCailiao():
#     app = QApplication(sys.argv)
#     window = DesignParameterDefineInputerViewer()
#     window.show()  # 显示窗口
#     sys.exit(app.exec_())  # 启动事件循环
