import os
import shutil

from PyQt5.QtCore import QTimer

import modules.chanpinguanli.bianl as bianl
from PyQt5.QtWidgets import QMessageBox, QPushButton, QLineEdit
import modules.chanpinguanli.common_usage as common_usage
import modules.chanpinguanli.open_project as open_project

# 初始化提示定时器（确保只初始化一次）
def init_tip_timer():
    if not hasattr(bianl, 'tip_timer'):
        bianl.tip_timer = QTimer()
        bianl.tip_timer.setSingleShot(True)
        bianl.tip_timer.timeout.connect(clear_line_tip)

# 清空提示信息的函数
def clear_line_tip():
    """5秒后自动清空line_tip的文本和样式"""
    if hasattr(bianl.main_window, "line_tip") and bianl.main_window.line_tip:
        bianl.main_window.line_tip.setText("")
        bianl.main_window.line_tip.setStyleSheet("")
        bianl.main_window.line_tip.setToolTip("")


def show_confirm_dialog(parent, title, text):
    """显示带有中文按钮（确认/取消）的确认对话框，返回True表示确认。"""
    msg_box = QMessageBox(parent)
    msg_box.setWindowTitle(title)
    msg_box.setText(text)
    msg_box.setIcon(QMessageBox.Question)

    yes_button = QPushButton("确认")
    no_button = QPushButton("取消")

    msg_box.addButton(yes_button, QMessageBox.YesRole)
    msg_box.addButton(no_button, QMessageBox.NoRole)

    msg_box.exec_()
    return msg_box.clickedButton() == yes_button

# 0515新修改-项目路径变更处理--项目路径保存时，变更为绝对路径
def normalize_project_save_path(raw: str) -> str:
    """项目保存路径（项目根父目录）入库前统一为本地绝对路径，避免相对路径依赖 cwd。"""
    s = (raw or "").strip()
    if not s:
        return s
    return os.path.normpath(os.path.abspath(s))


def save_project_to_db():
    """根据项目状态保存项目信息到数据库，并处理文件夹操作"""
    # 初始化定时器
    init_tip_timer()
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

# 0515新修改-项目路径变更处理
    project_path = normalize_project_save_path(project_path)
    if bianl.project_path_input is not None:
        bianl.project_path_input.setText(project_path)

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
            # ==========1014 新增：启动5秒定时器 ==========
            bianl.tip_timer.stop()  # 先停止可能存在的旧定时器
            bianl.tip_timer.start(5000)  # 5秒后清空
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
            # 0515新修改-项目路径变更处理
            # 处理文件夹重命名（旧路径可能是历史相对路径，先规范为绝对路径再 rename / 替换前缀）
            old_parent = normalize_project_save_path(bianl.old_project_path or "")
            old_folder = os.path.normpath(
                os.path.join(old_parent, f"{bianl.old_owner}_{bianl.old_project_name}")
            )
            new_folder = os.path.normpath(os.path.join(project_path, f"{owner}_{project_name}"))
            project_id = bianl.current_project_id

            #0519新修改- 在移动/重命名之前，确保新的目标父目录存在
            if not os.path.exists(project_path):
                print(f"[修改项目] 新的项目路径 '{project_path}' 不存在，正在创建...")
                os.makedirs(project_path, exist_ok=True)
            # 增加一个健壮性检查：如果新旧文件夹路径相同，则无需移动
            if old_folder != new_folder:
                # 再次检查：确保源文件夹存在才进行移动
                if os.path.exists(old_folder):
                    # 增加检查：防止目标位置已存在同名文件夹导致报错
                    if os.path.exists(new_folder):
                        QMessageBox.critical(bianl.main_window, "操作失败",
                                                 f"目标位置已存在同名项目文件夹：\n{new_folder}\n\n请检查项目名称或项目路径。")
                        return
                    print(f"[修改项目] 正在移动文件夹: '{old_folder}' -> '{new_folder}'")
                    os.rename(old_folder, new_folder)  # 重命名/移动文件夹
                else:
                    # 如果旧文件夹不存在，可能已经被移动或删除，只更新数据库记录
                    print(f"[修改项目] 警告：未找到旧的项目文件夹 '{old_folder}'，将仅更新数据库记录。")
            # if os.path.exists(old_folder):
            #     os.rename(old_folder, new_folder)  # 重命名文件夹
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
            # 0506新修改
            # 同步更新产品设计活动表中的产品文件夹绝对路径
            try:
                print(f"[修改项目] 开始同步产品路径，项目ID: {project_id}")
                print(f"[修改项目] 旧项目文件夹: {old_folder}")
                print(f"[修改项目] 新项目文件夹: {new_folder}")
                
                conn_act = common_usage.get_mysql_connection_active()
                cursor_act = conn_act.cursor()
                
                # 获取该项目下所有产品
                cursor_act.execute(
                    "SELECT 产品ID, 产品文件夹绝对路径 FROM 产品设计活动表 WHERE 项目ID = %s",
                    (project_id,)
                )
                products = cursor_act.fetchall()
                print(f"[修改项目] 找到 {len(products)} 个产品记录")
                
                updated_count = 0
                for i, product in enumerate(products):
                    # 支持字典和元组两种返回格式
                    if isinstance(product, dict):
                        product_id = product.get('产品ID')
                        old_path = product.get('产品文件夹绝对路径')
                    else:
                        product_id = product[0]
                        old_path = product[1]
                    
                    print(f"[修改项目] 产品 {i+1}: ID={product_id}, 旧路径={old_path}")
                    
                    if old_path:
                        # 直接替换路径前缀，处理路径不匹配的情况
                        try:
                            # 方法1：如果旧路径包含旧项目文件夹，直接替换
                            if old_folder in old_path:
                                new_product_path = old_path.replace(old_folder, new_folder)
                            else:
                                # 方法2：如果路径不匹配，尝试从旧路径中提取产品文件夹名，然后拼接到新项目路径
                                product_folder_name = os.path.basename(old_path)
                                new_product_path = os.path.join(new_folder, product_folder_name)
                            
                            # 标准化路径
                            new_product_path = os.path.normpath(new_product_path)
                            
                            print(f"[修改项目]   新路径: {new_product_path}")
                            
                            # 更新产品文件夹绝对路径
                            cursor_act.execute(
                                "UPDATE 产品设计活动表 SET 产品文件夹绝对路径 = %s WHERE 产品ID = %s",
                                (new_product_path, product_id)
                            )
                            updated_count += 1
                            print(f"[修改项目]   ✅ 已更新产品路径: {product_id}")
                            
                        except Exception as e_path:
                            print(f"[修改项目]   ❌ 路径更新失败: {e_path}")
                    else:
                        print(f"[修改项目]   ⚠️ 跳过空路径: {old_path}")
                
                conn_act.commit()
                cursor_act.close()
                conn_act.close()
                print(f"[修改项目] ✅ 已同步更新 {updated_count} 个产品的文件夹路径")
                
            except Exception as e_act:
                print(f"[修改项目] ⚠️ 更新产品设计活动表路径失败: {e_act}")
                import traceback
                traceback.print_exc()

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
            bianl.tip_timer.stop()
            bianl.tip_timer.start(5000)
            # QMessageBox.information(bianl.main_window, "成功", "项目修改已保存")
            bianl.old_owner = owner
            bianl.old_project_name = project_name
            bianl.old_project_path = project_path

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

# 1112新修改 - 关闭所有产品相关界面（删除项目时使用）
def close_all_product_related_tabs():
    """
    关闭所有产品相关界面（除了项目管理界面）
    用于删除项目时关闭所有已打开的产品界面
    """
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if not app:
            print("[关闭界面] 无法获取应用实例")
            return
        
        # 查找主窗口
        main_window = None
        for widget in app.topLevelWidgets():
            if hasattr(widget, 'tab_widget') and hasattr(widget, 'close_tab'):
                main_window = widget
                break
        
        if not main_window:
            print("[关闭界面] 无法找到主窗口")
            return
        
        # 定义所有产品相关标签页名称
        all_product_tabs = {"条件输入", "元件定义", "管口及附件定义", "管束设计", "设计运算", "图纸绘制", "文本说明生成", "模型创建"}
        
        # 倒序遍历标签页，关闭所有产品相关界面
        for i in reversed(range(main_window.tab_widget.count())):
            tab_text = main_window.tab_widget.tabText(i)
            if tab_text in all_product_tabs:
                widget_to_close = main_window.tab_widget.widget(i)
                main_window.tab_widget.removeTab(i)
                if widget_to_close:
                    widget_to_close.deleteLater()
                print(f"[删除项目] 关闭界面: {tab_text}")
        
        print("[删除项目] 已关闭所有产品相关界面")
        
    except Exception as e:
        print(f"[删除项目] 关闭相关界面时出错: {e}")
        import traceback
        traceback.print_exc()

# 删除项目
def delete_project_and_related_data():
    """删除整个项目及其相关联的所有数据库和文件数据"""
    # 确保定时器已初始化
    init_tip_timer()

    project_id = bianl.current_project_id
    if not project_id:
        bianl.main_window.line_tip.setText("未打开任何项目，无法删除。")
        bianl.main_window.line_tip.setToolTip("未打开任何项目，无法删除。")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        # QMessageBox.warning(bianl.main_window, "提示", "未打开任何项目，无法删除。")
        return

    # 确认弹窗（中文按钮）
    if not show_confirm_dialog(bianl.main_window, "确认删除", "是否确认永久删除当前项目的所有数据和文件？"):
        return

    # 1112新修改 - 删除项目前先关闭所有产品相关界面
    close_all_product_related_tabs()

    try:
        # Step 0: 在删除前，获取该项目下所有产品ID（后续用于删除活动库中仅存有“产品ID”的表数据）
        conn_prod_query = common_usage.get_mysql_connection_product()
        cursor_prod_query = conn_prod_query.cursor()
        cursor_prod_query.execute("SELECT 产品ID FROM 产品需求表 WHERE 项目ID = %s", (project_id,))
        product_rows = cursor_prod_query.fetchall()
        product_ids = [row.get("产品ID") for row in product_rows if row.get("产品ID")]
        cursor_prod_query.close()
        conn_prod_query.close()

        # Step 1: 删除项目需求表
        conn_proj = common_usage.get_mysql_connection_project()
        cursor_proj = conn_proj.cursor()
        cursor_proj.execute("DELETE FROM 项目需求表 WHERE 项目ID = %s", (project_id,))
        conn_proj.commit()
        cursor_proj.close()
        conn_proj.close()

        # Step 2: 删除产品需求表（按项目ID）
        conn_prod = common_usage.get_mysql_connection_product()
        cursor_prod = conn_prod.cursor()
        cursor_prod.execute("DELETE FROM 产品需求表 WHERE 项目ID = %s", (project_id,))
        conn_prod.commit()
        cursor_prod.close()
        conn_prod.close()

        # Step 3: 删除产品设计活动库中与这些产品ID有关的所有表数据
        if product_ids:
            conn_act = common_usage.get_mysql_connection_active()
            cursor_act = conn_act.cursor()

            table_list = [
                "产品设计活动表",
                "产品设计活动表_布管参数表",
                "产品设计活动表_布管换热管表",
                "产品设计活动表_布管计算结果表",
                "产品设计活动表_布管交叉布管表",
                "产品设计活动表_布管结果表",
                "产品设计活动表_布管拉杆表",
                "产品设计活动表_布管输入表",
                "产品设计活动表_布管数量表_水平",
                "产品设计活动表_布管数量表_竖直",
                "产品设计活动表_布管数量表_显示",
                "产品设计活动表_布管元件表",
                "产品设计活动表_布管坐标表",
                "产品设计活动表_产品标准数据表",
                "产品设计活动表_附件表",
                "产品设计活动表_管板连接表",
                "产品设计活动表_管板形式表",
                "产品设计活动表_管口表",
                "产品设计活动表_管口附加参数表",
                "产品设计活动表_管口计算提交表",
                "产品设计活动表_管口类别表",
                "产品设计活动表_管口类型选择表",
                "产品设计活动表_管口零件材料表",
                "产品设计活动表_管口零件材料参数表",
                "产品设计活动表_计算结果日志表",
                "产品设计活动表_计算提交表",
                "产品设计活动表_设计数据表",
                "产品设计活动表_设计数据计算提交表",
                "产品设计活动表_通用数据表",
                "产品设计活动表_涂漆数据表",
                "产品设计活动表_无损检测数据表",
                "产品设计活动表_元件材料表",
                "产品设计活动表_元件附加参数表",
                "产品设计活动表_元件计算结果表"
            ]

            # 逐表按产品ID删除；使用参数化避免SQL注入
            for table in table_list:
                sql = f"DELETE FROM `{table}` WHERE 产品ID = %s"
                for pid in product_ids:
                    cursor_act.execute(sql, (pid,))

            # 兜底：对于主表再按项目ID删一次（如果该表也包含项目ID）
            cursor_act.execute("DELETE FROM 产品设计活动表 WHERE 项目ID = %s", (project_id,))

            conn_act.commit()
            cursor_act.close()
            conn_act.close()
        else:
            # 没有产品ID时，也尝试按项目ID清理主表记录
            conn_act = common_usage.get_mysql_connection_active()
            cursor_act = conn_act.cursor()
            cursor_act.execute("DELETE FROM 产品设计活动表 WHERE 项目ID = %s", (project_id,))
            conn_act.commit()
            cursor_act.close()
            conn_act.close()

        # 0515新修改-项目路径变更处理
        # Step 4: 删除项目文件夹（与保存路径一致：相对路径按 cwd 规范为绝对路径再删）
        _del_parent = normalize_project_save_path(bianl.old_project_path or "")
        folder_path = os.path.normpath(
            os.path.join(_del_parent, f"{bianl.old_owner}_{bianl.old_project_name}")
        )
        if os.path.exists(folder_path):
            shutil.rmtree(folder_path)

        bianl.main_window.line_tip.setText("项目及所有相关数据删除成功！")
        bianl.main_window.line_tip.setToolTip("项目及所有相关数据删除成功！")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        bianl.tip_timer.stop()
        bianl.tip_timer.start(5000)
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
        bianl.tip_timer.stop()
        bianl.tip_timer.start(5000)
        # QMessageBox.critical(bianl.main_window, "错误", f"删除失败：{e}")