import os
import shutil
import modules.chanpinguanli.bianl as bianl
from PyQt5.QtWidgets import QMessageBox
import modules.chanpinguanli.common_usage as common_usage


def modify_project():
    """点击修改按钮后，切换到编辑模式，保存旧数据"""
    # 先判断界面控件是否都初始化完成
    if not all([bianl.owner_input, bianl.project_name_input, bianl.project_path_input]):
        bianl.main_window.line_tip.setText("界面控件未加载完成，无法修改项目！")
        bianl.main_window.line_tip.setToolTip("界面控件未加载完成，无法修改项目！")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        # QMessageBox.critical(bianl.main_window, "错误", "界面控件未加载完成，无法修改项目！")
        return
    # 可编辑
    common_usage.set_project_inputs_editable(True)
    # 修改状态标志
    bianl.project_mode = "edit"
    # 保存旧的信息（用于后续重命名文件夹和更新数据库）
    bianl.old_owner = bianl.owner_input.text().strip()
    bianl.old_project_name = bianl.project_name_input.text().strip()
    bianl.old_project_path = bianl.project_path_input.text().strip()
    # 读取csv文件 找到文件
    old_project_folder = os.path.join(bianl.old_project_path, f"{bianl.old_owner}_{bianl.old_project_name}")
    project_id_file = os.path.join(old_project_folder, "id.csv")

    if not os.path.exists(project_id_file):
        bianl.main_window.line_tip.setText("未找到项目ID文件，无法修改！")
        bianl.main_window.line_tip.setToolTip("未找到项目ID文件，无法修改！")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        # QMessageBox.critical(bianl.main_window, "错误", "未找到项目ID文件，无法修改！")
        return

    with open(project_id_file, "r", encoding="utf-8") as f:
        bianl.current_project_id = f.read().strip()

