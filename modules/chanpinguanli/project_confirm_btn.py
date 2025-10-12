import os
import shutil
import modules.chanpinguanli.bianl as bianl
from PyQt5.QtWidgets import QMessageBox, QPushButton, QLineEdit
import modules.chanpinguanli.common_usage as common_usage
import modules.chanpinguanli.open_project as open_project




def save_project_to_db():
    """根据项目状态保存项目信息到数据库，并处理文件夹操作"""
    owner = bianl.owner_input.text().strip()
    project_number = bianl.project_number_input.text().strip()
    project_name = bianl.project_name_input.text().strip()
    department = bianl.department_input.text().strip()
    contractor = bianl.contractor_input.text().strip()
    project_path = bianl.project_path_input.text().strip()
    create_date = bianl.date_edit.date().toString("yyyy-MM-dd")

    if not owner or not project_name or not project_path:
        QMessageBox.warning(bianl.main_window, "提示", "业主名称、项目名称、项目路径为必填项！")
        return

    # 如果当前项目状态是 "view" 或 "edit"，但没有旧项目的原始信息，那么就自动将状态识别为 "new"
    # if bianl.project_mode in ("view", "edit") and (
    #         not bianl.old_owner or not bianl.old_project_name or not bianl.old_project_path):
    #     # 用户自己输入的，属于新建
    #     bianl.project_mode = "new"

    try:
        # 将最近存入
        # open_project.save_last_used_path(project_path)
        # 如果是新建项目，创建文件夹
        if bianl.project_mode == "new":
            # 生成项目id
            project_id = common_usage.get_next_project_id()
            # 存入了
            bianl.current_project_id = project_id
            # 创建文件夹
            project_folder = os.path.join(project_path, f"{owner}_{project_name}")
            if not os.path.exists(project_folder):
                os.makedirs(project_folder)
            # 保存项目ID到本地CSV
            with open(os.path.join(project_folder, "id.csv"), "w", encoding="utf-8") as f:
                f.write(project_id)

            # 插入到项目需求库
            # conn = common_usage.get_mysql_connection()
            # cursor = conn.cursor()
            conn = common_usage.get_mysql_connection_project()
            cursor = conn.cursor()

            sql = """
                INSERT INTO 项目需求表 (项目ID, 业主名称, 项目编号, 项目名称, 所属部门, 工程总包方, 建立日期, 项目保存路径)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            values = (
                project_id, owner, project_number, project_name, department, contractor, create_date, project_path)
            cursor.execute(sql, values)
            conn.commit()
            cursor.close()
            conn.close()
            # self.line_tip = setText(""成功", f"新建项目成功！"")
            bianl.main_window.line_tip.setText("新建项目成功！")
            bianl.main_window.line_tip.setToolTip("新建项目成功！")
            bianl.main_window.line_tip.setStyleSheet("color: black;")
            # 删除获取的信息
            bianl.old_owner = owner
            bianl.old_project_name = project_name
            bianl.old_project_path = project_path
            # 新加
            bianl.project_mode = "view"
            print("[状态] 新建项目成功，project_mode = view")
            # 新加的 产品表格不可编辑
            from modules.chanpinguanli.product_confirm_qianzhi import set_row_editable
            for row in range(bianl.product_table.rowCount()):
                status = bianl.product_table_row_status.get(row, {}).get("status", "")
                if status == "start":
                    set_row_editable(row, True)


            # 解锁产品信息表格输入 新加

        # 如果是修改项目，重命名文件夹并更新路径
        elif bianl.project_mode == "edit":
            # 处理文件夹重命名
            old_folder = os.path.join(bianl.old_project_path, f"{bianl.old_owner}_{bianl.old_project_name}")
            new_folder = os.path.join(project_path, f"{owner}_{project_name}")
            project_id = bianl.current_project_id
            if os.path.exists(old_folder):
                os.rename(old_folder, new_folder)  # 重命名文件夹
            # 更新数据库信息
            # conn = common_usage.get_mysql_connection()
            # cursor = conn.cursor()
            conn = common_usage.get_mysql_connection_project()
            cursor = conn.cursor()

            sql = """
                UPDATE 项目需求表
                SET 业主名称 = %s, 项目编号 = %s, 项目名称 = %s, 所属部门 = %s, 
                    工程总包方 = %s, 建立日期 = %s, 项目保存路径 = %s
                WHERE 项目ID = %s
            """
            values = (
                owner, project_number, project_name, department, contractor, create_date, project_path,
                project_id)
            cursor.execute(sql, values)
            conn.commit()
            cursor.close()
            conn.close()

            bianl.project_mode = "view"
            print("[状态] 修改项目完成，project_mode = view")
            # 新加的 产品表格不可编辑
            from modules.chanpinguanli.product_confirm_qianzhi import set_row_editable
            for row in range(bianl.product_table.rowCount()):
                status = bianl.product_table_row_status.get(row, {}).get("status", "")
                if status == "start":
                    set_row_editable(row, True)
            bianl.main_window.line_tip.setText("项目修改已保存！")
            bianl.main_window.line_tip.setToolTip("项目修改已保存！")
            bianl.main_window.line_tip.setStyleSheet("color: black;")
            # QMessageBox.information(bianl.main_window, "成功", "项目修改已保存")

        elif bianl.project_mode == "view":
            bianl.main_window.line_tip.setText("只读模式下不可保存修改！")
            bianl.main_window.line_tip.setToolTip("只读模式下不可保存修改！")
            bianl.main_window.line_tip.setStyleSheet("color: black;")
            # QMessageBox.warning(bianl.main_window, "提示", "只读模式下不可保存修改！")
            return
        else:
            bianl.main_window.line_tip.setText("未知的项目状态，无法保存！")
            bianl.main_window.line_tip.setToolTip("未知的项目状态，无法保存！")
            bianl.main_window.line_tip.setStyleSheet("color: black;")
            # QMessageBox.warning(bianl.main_window, "提示", "未知的项目状态，无法保存！")
            return

        common_usage.set_project_inputs_editable(False)
    except Exception as e:
        bianl.main_window.line_tip.setText(f"保存失败: {e}")
        bianl.main_window.line_tip.setToolTip(f"保存失败: {e}")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        # QMessageBox.critical(bianl.main_window, "错误", f"保存失败: {e}")

# 删除项目
def delete_project_and_related_data():
    """删除整个项目及其相关联的所有数据库和文件数据"""

    project_id = bianl.current_project_id
    if not project_id:
        bianl.main_window.line_tip.setText("未打开任何项目，无法删除。")
        bianl.main_window.line_tip.setToolTip("未打开任何项目，无法删除。")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        # QMessageBox.warning(bianl.main_window, "提示", "未打开任何项目，无法删除。")
        return

    # 自定义按钮文本
    msg_box = QMessageBox(bianl.main_window)
    msg_box.setWindowTitle("确认删除")
    msg_box.setText("是否确认永久删除当前项目的所有数据和文件？")
    msg_box.setIcon(QMessageBox.Question)

    # 自定义按钮
    yes_button = QPushButton("是")
    no_button = QPushButton("否")

    msg_box.addButton(yes_button, QMessageBox.YesRole)
    msg_box.addButton(no_button, QMessageBox.NoRole)

    # 显示对话框并获取结果
    result = msg_box.exec_()

    if msg_box.clickedButton() != yes_button:
        return

    try:
        # Step 1: 删除项目需求表
        conn_proj = common_usage.get_mysql_connection_project()
        cursor_proj = conn_proj.cursor()
        cursor_proj.execute("DELETE FROM 项目需求表 WHERE 项目ID = %s", (project_id,))
        conn_proj.commit()
        cursor_proj.close()
        conn_proj.close()

        # Step 2: 删除产品需求表
        conn_prod = common_usage.get_mysql_connection_product()
        cursor_prod = conn_prod.cursor()
        cursor_prod.execute("DELETE FROM 产品需求表 WHERE 项目ID = %s", (project_id,))
        conn_prod.commit()
        cursor_prod.close()
        conn_prod.close()

        # Step 3: 删除产品设计活动表
        conn_act = common_usage.get_mysql_connection_active()
        cursor_act = conn_act.cursor()
        cursor_act.execute("DELETE FROM 产品设计活动表 WHERE 项目ID = %s", (project_id,))
        conn_act.commit()
        cursor_act.close()
        conn_act.close()

        # Step 4: 删除项目文件夹
        folder_path = os.path.join(bianl.old_project_path, f"{bianl.old_owner}_{bianl.old_project_name}")
        if os.path.exists(folder_path):
            shutil.rmtree(folder_path)

        bianl.main_window.line_tip.setText("项目及所有相关数据删除成功！")
        bianl.main_window.line_tip.setToolTip("项目及所有相关数据删除成功！")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        # QMessageBox.information(bianl.main_window, "成功", "项目及所有相关数据删除成功！")

        # 清空界面
        from modules.chanpinguanli.new_project_button import clear_project_info
        clear_project_info()
        # 变成可编辑状态
        from modules.chanpinguanli.new_project_button import prepare_new_project
        prepare_new_project()

        bianl.current_project_id = None
        bianl.project_mode = "new"
        from modules.chanpinguanli.product_confirm_qianzhi import set_row_editable
        for row in range(bianl.product_table.rowCount()):
            set_row_editable(row, False)

    except Exception as e:
        import traceback
        with open("error_log.txt", "a", encoding="utf-8") as log:
            log.write("删除项目时发生错误：\n")
            log.write(traceback.format_exc())
        bianl.main_window.line_tip.setText(f"删除失败：{e}")
        bianl.main_window.line_tip.setToolTip(f"删除失败：{e}")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        # QMessageBox.critical(bianl.main_window, "错误", f"删除失败：{e}")