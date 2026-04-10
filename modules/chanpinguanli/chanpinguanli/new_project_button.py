import sys
import os
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                             QComboBox, QFileDialog, QFrame, QGroupBox, QHeaderView, QDateEdit, QMessageBox)
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QPixmap
import mysql.connector
import modules.chanpinguanli.bianl as bianl
# prepare_new_project 函数 新建按钮对应操作xx
from modules.chanpinguanli import product_confirm_qianzhi
from modules.chanpinguanli import common_usage
from modules.chanpinguanli.bianl import main_window


def clear_project_info():
    """清空项目信息"""
    bianl.owner_input.clear()
    bianl.project_number_input.clear()
    bianl.project_name_input.clear()
    bianl.department_input.clear()
    bianl.contractor_input.clear()
    bianl.project_path_input.clear()
    bianl.date_edit.setDate(QDate.currentDate())
    # 产品信息（产品表格）
    # 清空产品表格内容
    bianl.product_table.clearContents()
    bianl.product_table.setRowCount(3)
    bianl.product_table_row_status.clear()  # 清空旧的状态记录

    # 重新初始化每一行状态、定义状态与序号
    for row in range(3):
        item = QTableWidgetItem(f"{row + 1:02d}")
        item.setTextAlignment(Qt.AlignCenter)

        # 高光
        item.setFlags(Qt.ItemIsSelectable)
        bianl.product_table.setItem(row, 0, item)

        bianl.product_table_row_status[row] = {
            "status": "start",
            "definition_status": "start"
        }
        # 新建时表的可编辑状态
        product_confirm_qianzhi.set_row_editable(row, True)

    # 产品定义区清空   改77
    bianl.product_type_combo.setCurrentIndex(-1)
    bianl.product_form_combo.setCurrentIndex(-1)
    bianl.product_model_input.clear()
    bianl.drawing_prefix_input.clear()

    bianl.design_input.clear()
    bianl.proofread_input.clear()
    bianl.review_input.clear()
    bianl.standardization_input.clear()
    bianl.approval_input.clear()
    bianl.co_signature_input.clear()

    # 示意图
    bianl.image_label.clear()
    # bianl.image_label.setText("示意图：请确定产品类型和产品形式")


def clear_current_product_info():
    """清除当前设计产品控件中的信息"""
    # 清除产品ID相关变量
    bianl.product_id = None
    bianl.current_product_id = None
    
    # 通知其他模块产品ID已清除
    from modules.chanpinguanli.chanpinguanli_main import product_manager
    product_manager.update_product_id(None)
    
    # 清除产品定义字段
    from modules.chanpinguanli.chanpinguanli_main import clear_product_definition_fields
    clear_product_definition_fields()
    
    # 清除产品表格的选中状态
    if bianl.product_table:
        bianl.product_table.clearSelection()
        # 清除高亮显示
        for row in range(bianl.product_table.rowCount()):
            for col in range(bianl.product_table.columnCount()):
                item = bianl.product_table.item(row, col)
                if item:
                    item.setBackground(Qt.white)  # 恢复默认背景色


def prepare_new_project():
    """准备新建项目"""
    # 先判断控件是否加载完成
    if not all([bianl.owner_input, bianl.project_name_input, bianl.project_path_input]):
        return
    # 1. 清空项目管理界面的信息
    clear_project_info()

    # 2. 清除当前设计产品控件中的信息
    clear_current_product_info()

    common_usage.set_project_inputs_editable(True)
    # bianl.owner_input.setReadOnly(False)
    # bianl.project_number_input.setReadOnly(False)
    # bianl.project_name_input.setReadOnly(False)
    # bianl.department_input.setReadOnly(False)
    # bianl.contractor_input.setReadOnly(False)
    # bianl.project_path_input.setReadOnly(False)

    # 设置项目模式为新建
    bianl.project_mode = "new"
    # 解锁产品信息表格输入 新加
    bianl.current_project_id = None
    # 新加产品不可编辑
    bianl.project_mode = "new"
    from modules.chanpinguanli.product_confirm_qianzhi import set_row_editable
    for row in range(bianl.product_table.rowCount()):
        set_row_editable(row, False)


