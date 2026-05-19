import os

from PyQt5.QtGui import QBrush, QColor

import modules.chanpinguanli.bianl as bianl
from PyQt5.QtWidgets import QTableWidgetItem, QMessageBox, QComboBox
from PyQt5.QtCore import Qt, QEvent, QObject, QTimer, QModelIndex
import modules.chanpinguanli.common_usage as common_usage

import modules.chanpinguanli.auto_edit_row as auto_edit_row
import traceback
import shutil


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

def build_pd_folder_name(serial, name, position, number):
    # 0506新修改--产品信息非法字符约束
    import re
    
    # Windows文件名非法字符
    illegal_chars = r'[\\/:*?"<>|]'
    
    # 统一清洗 & 顺序：序号_产品名称_产品编号_设备位号（空值自动跳过）
    parts = [
        (serial or "").strip(),
        (name or "").strip(),
        (position or "").strip(),
        (number or "").strip(),
    ]
    # 0506新修改--产品信息非法字符约束
    # 安全验证：清理所有非法字符（作为兜底）
    sanitized_parts = []
    for part in parts:
        if part:
            # 检查并清理非法字符
            if re.search(illegal_chars, part):
                print(f"[build_pd_folder_name] 警告：发现非法字符并自动清理: {part}")
                part = re.sub(illegal_chars, '', part)  # 直接删除非法字符
            sanitized_parts.append(part)
    
    parts = [p for p in sanitized_parts if p]  # 跳过空
    return "_".join(parts)


def log_debug(message):
    with open("debug_log.txt", "a", encoding="utf-8") as f:
        f.write(message + "\n")


def log_error(message, exception=None):
    with open("error_log.txt", "a", encoding="utf-8") as f:
        f.write(message + "\n")
        if exception:
            f.write(traceback.format_exc() + "\n")


def get_status(row):
    val = bianl.product_table_row_status.get(row, {})
    return val.get("status", "start") if isinstance(val, dict) else val


# 1107新修改-修改产品
def check_batch_product_conflicts(modify_list, project_id):
    """
    批量检查产品修改后的冲突情况
    modify_list: 列表，每个元素是字典，包含：
        {
            'row': 行号,
            'product_id': 产品ID,
            'new_number': 新产品编号,
            'new_name': 新产品名称,
            'new_position': 新设备位号
        }
    返回: (has_conflict, conflict_rows)
        has_conflict: bool, 是否有冲突
        conflict_rows: list, 冲突的行号列表
    """
    init_tip_timer()
    conflict_rows = []
    
    if not modify_list:
        return False, []
    
    print(f"[check_batch_product_conflicts] 开始批量检查 {len(modify_list)} 个产品的冲突情况")
    
    try:
        # 1. 检查新值之间是否有重复
        new_value_triples = {}  # {(number, name, position): [row1, row2, ...]}
        for item in modify_list:
            triple = (item['new_number'], item['new_name'], item['new_position'])
            if triple in new_value_triples:
                new_value_triples[triple].append(item['row'])
            else:
                new_value_triples[triple] = [item['row']]
        
        # 检查新值之间的重复
        for triple, rows in new_value_triples.items():
            if len(rows) > 1:
                # 新值之间有重复（多个产品改成相同的值）
                # 只保留最小序号（最小row）的产品，其他的标记为冲突
                min_row = min(rows)  # 找出最小的row（序号最小）
                other_rows = [r for r in rows if r != min_row]  # 除了最小row之外的其他行
                conflict_rows.extend(other_rows)  # 只把其他的标记为冲突
                print(f"[check_batch_product_conflicts] 新值之间重复: {triple} 出现在行 {rows}，保留最小序号行 {min_row + 1}，冲突行: {[r + 1 for r in other_rows]}")

        # 去重冲突行号
        conflict_rows = list(set(conflict_rows))
        
        # 2. 检查新值是否与数据库中未修改的产品重复
        # 获取所有正在修改的产品ID列表（用于排除）
        modifying_product_ids = [item['product_id'] for item in modify_list if item.get('product_id')]
        
        if modifying_product_ids:
            conn = common_usage.get_mysql_connection_product()
            cursor = conn.cursor()
            
            # 检查每个新值是否与数据库中未修改的产品重复
            for item in modify_list:
                if item['row'] in conflict_rows:
                    continue  # 已经检测到冲突，跳过
                
                # 构建SQL，排除所有正在修改的产品ID
                placeholders = ','.join(['%s'] * len(modifying_product_ids))
                sql = f"""
                    SELECT 产品ID FROM 产品需求表 
                    WHERE 产品编号 = %s AND 产品名称 = %s AND 设备位号 = %s 
                    AND 项目ID = %s AND 产品ID NOT IN ({placeholders})
                """
                values = [item['new_number'], item['new_name'], item['new_position'], project_id] + modifying_product_ids
                cursor.execute(sql, values)
                result = cursor.fetchone()
                
                if result:
                    # 与数据库中未修改的产品重复
                    conflict_rows.append(item['row'])
                    print(f"[check_batch_product_conflicts] 行 {item['row']} 的新值与其他产品重复")
            
            cursor.close()
            conn.close()
        
        has_conflict = len(conflict_rows) > 0
        print(f"[check_batch_product_conflicts] 批量检查完成，冲突: {has_conflict}, 冲突行: {conflict_rows}")
        return has_conflict, conflict_rows
        
    except Exception as e:
        log_error("[check_batch_product_conflicts] 批量检查失败", e)
        bianl.main_window.line_tip.setText(f"批量检查产品冲突失败: {e}")
        bianl.main_window.line_tip.setToolTip(f"批量检查产品冲突失败: {e}")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        bianl.tip_timer.stop()
        bianl.tip_timer.start(5000)
        return True, []  # 出错时返回有冲突，阻止保存


# 1107新修改-修改产品
def check_existing_product(product_number, product_name, device_position, project_id, exclude_product_id=None):
    # 初始化定时器
    init_tip_timer()
    print(f"[check_existing_product] 检查产品是否存在: 编号={product_number}, 名称={product_name}, 设备位号={device_position} , 当前项目id={project_id}, 排除产品ID={exclude_product_id}")
    try:
        conn = common_usage.get_mysql_connection_product()
        cursor = conn.cursor()
        # 不对要区分大小写
        # 如果提供了exclude_product_id，则排除该产品ID（用于修改产品时排除自身）
        if exclude_product_id:
            sql = """
                SELECT * FROM 产品需求表 
                WHERE 产品编号 = %s AND 产品名称 = %s AND 设备位号 = %s AND 项目ID = %s AND 产品ID != %s
            """
            values = (product_number, product_name, device_position, project_id, exclude_product_id)
        else:
            sql = """
                SELECT * FROM 产品需求表 WHERE 产品编号 = %s AND 产品名称 = %s AND 设备位号 = %s AND 项目ID = %s
            """
            values = (product_number, product_name, device_position, project_id)
        cursor.execute(sql, values)
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        exists = bool(result)
        log_debug(f"[check_existing_product] 存在: {exists}")
        return exists
    except Exception as e:
        log_error("[check_existing_product] 查询数据库失败", e)
        bianl.main_window.line_tip.setText(f"查询产品需求表失败: {e}")
        bianl.main_window.line_tip.setToolTip(f"查询产品需求表失败: {e}")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        bianl.tip_timer.stop()
        bianl.tip_timer.start(5000)
        # QMessageBox.critical(bianl.main_window, "数据库错误", f"查询产品需求表失败: {e}")
        return False
#todo 把值传进来
def save_new_product(row,curr_row_serial,curr_row_product_name,curr_row_product_number,curr_row_device_position, curr_row_design_stage,curr_row_design_edition):
    # global curr_row_product_number, curr_row_product_name, curr_row_device_position

    # number_item = bianl.product_table.item(row, 3)
    # curr_row_product_number = number_item.text().strip() if number_item else ""
    #
    # name_item = bianl.product_table.item(row, 1)
    # curr_row_product_name = name_item.text().strip() if name_item else ""
    #
    # position_item = bianl.product_table.item(row, 2)
    # curr_row_device_position = position_item.text().strip() if position_item else ""
    #
    # print(f"[save_new_product] 获取到：编号='{curr_row_product_number}', 名称='{curr_row_product_name}', 位号='{curr_row_device_position}', 设计阶段='{curr_row_design_stage}'")
    # 初始化定时器
    init_tip_timer()
    # 生成此时的产品id 是生成的产品id 产品ID
    curr_product_id = common_usage.get_next_product_id()

    print(f"[save_new_product] 生成产品ID: {curr_product_id}")

    # 将产品id存入字典
    if row not in bianl.product_table_row_status or not isinstance(bianl.product_table_row_status[row], dict):
        bianl.product_table_row_status[row] = {}
    bianl.product_table_row_status[row]["product_id"] = curr_product_id
    print(f"[save_new_product] 存入状态表，第 {row} 行 product_id = {bianl.product_table_row_status[row]['product_id']}")
    # 存入状态表 为了删除重命名序号的获取
    bianl.product_table_row_status[row]["old_serial"] = curr_row_serial
    bianl.product_table_row_status[row]["old_name"] = curr_row_product_name
    bianl.product_table_row_status[row]["old_number"] = curr_row_product_number
    bianl.product_table_row_status[row]["old_position"] = curr_row_device_position

    # === 新建产品文件夹名称：加序号前缀 ===                            # 改3
    pd_folder_name = build_pd_folder_name(curr_row_serial, curr_row_product_name, curr_row_device_position , curr_row_product_number)

    # parts = [curr_row_serial, curr_row_product_name, curr_row_product_number, curr_row_device_position]
    # pd_folder_name = "_".join([p for p in parts if p])  # 自动跳过空字段

    # pd_folder_name = f"{curr_row_serial}_{curr_row_product_name}_{curr_row_product_number}_{curr_row_device_position}"  # 改3

    # pd_folder_name = f"{curr_row_product_name}_{curr_row_product_number}_{curr_row_device_position}"
    conn = common_usage.get_mysql_connection_project()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT `项目保存路径` FROM `项目需求表` WHERE `项目ID` = %s", (bianl.current_project_id,))
        result = cursor.fetchone()
        project_path_pd = result["项目保存路径"] if result and "项目保存路径" in result else None
        print(f"[save_new_product] 查询到项目路径: {project_path_pd}")

        if not project_path_pd:
            print("[save_new_product] ❌ 未找到项目路径")
            bianl.main_window.line_tip.setText("未找到项目保存路径。")
            bianl.main_window.line_tip.setToolTip("未找到项目保存路径。")
            bianl.main_window.line_tip.setStyleSheet("color: black;")
            bianl.tip_timer.stop()
            bianl.tip_timer.start(5000)
            # QMessageBox.warning(bianl.main_window, "警告", "未找到项目保存路径。")
            return
    except Exception as e:
        print(f"[save_new_product] ❌ 查询项目路径失败: {e}")
        bianl.main_window.line_tip.setText(f"查询项目保存路径失败: {e}")
        bianl.main_window.line_tip.setToolTip(f"查询项目保存路径失败: {e}")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        # QMessageBox.critical(bianl.main_window, "数据库错误", f"查询项目保存路径失败: {e}")
        cursor.close()
        conn.close()
        return
    cursor.close()
    conn.close()

    cur_project_owner = bianl.owner_input.text().strip()
    cur_project_name = bianl.project_name_input.text().strip()
    folder_path = os.path.join(project_path_pd, f"{cur_project_owner}_{cur_project_name}", pd_folder_name)

    print(f"[save_new_product] 准备创建产品文件夹: {folder_path}")
    if os.path.exists(folder_path):
        print("[save_new_product] ⚠️ 文件夹已存在")
        bianl.main_window.line_tip.setText(f"产品文件夹已存在：{folder_path}")
        bianl.main_window.line_tip.setToolTip(f"产品文件夹已存在：{folder_path}")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        # QMessageBox.warning(bianl.main_window, "提示", f"产品文件夹已存在：{folder_path}")
        return

    try:
        os.makedirs(folder_path)
        with open(os.path.join(folder_path, "pro_id.csv"), "w", encoding="utf-8") as f:
            f.write(str(curr_product_id))
        # 复制模板到新的路径
        template_path = os.path.join(os.path.dirname(__file__), "条件输入数据表.xlsx")
        target_path = os.path.join(folder_path, "条件输入数据表.xlsx")
        shutil.copy(template_path, target_path)
        template_path2 = os.path.join(os.path.dirname(__file__), "管口导入模板.xlsx")
        target_path2 = os.path.join(folder_path, "管口导入模板.xlsx")
        shutil.copy(template_path2, target_path2)
        print(f"[save_new_product] ✅ 模板文件复制完成: {target_path}")

        conn_pd = common_usage.get_mysql_connection_product()
        cursor_pd = conn_pd.cursor()
        sql_pd = """
            INSERT INTO 产品需求表 (产品ID, 项目ID, 产品编号, 产品名称, 设备位号,设计阶段,设计版次, 产品型号)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        values_pd = (curr_product_id, bianl.current_project_id,
                     curr_row_product_number, curr_row_product_name,
                     curr_row_device_position, curr_row_design_stage, curr_row_design_edition, '')
        cursor_pd.execute(sql_pd, values_pd)
        conn_pd.commit()
        cursor_pd.close()
        conn_pd.close()

        # 活动库：写入产品设计活动表（产品ID、项目ID、产品文件夹绝对路径）
        folder_abs = os.path.abspath(folder_path)
        try:
            conn_act = common_usage.get_mysql_connection_active()
            cursor_act = conn_act.cursor()
            sql_act = """
                INSERT INTO 产品设计活动表 (产品ID, 项目ID, 产品文件夹绝对路径)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  项目ID = VALUES(项目ID),
                  产品文件夹绝对路径 = VALUES(产品文件夹绝对路径)
            """
            cursor_act.execute(sql_act, (curr_product_id, bianl.current_project_id, folder_abs))
            conn_act.commit()
            cursor_act.close()
            conn_act.close()
            print(f"[save_new_product] ✅ 产品设计活动表已写入产品文件夹绝对路径: {folder_abs}")
        except Exception as e_act:
            print(f"[save_new_product] ⚠️ 写入产品设计活动表(产品文件夹绝对路径)失败: {e_act}")

        print("[save_new_product] ✅ 数据库插入成功")

        # 强制写回 item，可选
        # stage_text = widget.currentText().strip()
        # item_stage = QTableWidgetItem(stage_text)
        # item_stage.setTextAlignment(Qt.AlignCenter)
        # bianl.product_table.setItem(row, 4, item_stage)

        auto_edit_row.update_status(row, "view")
        print(f"[save_new_product] ✅ 状态更新完成 → view")
    except Exception as e:
        print(f"[save_new_product] ❌ 新建产品时出错: {e}")
        bianl.main_window.line_tip.setText(f"新建产品时发生错误：{e}")
        bianl.main_window.line_tip.setToolTip(f"新建产品时发生错误：{e}")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        # QMessageBox.critical(bianl.main_window, "错误", f"新建产品时发生错误：{e}")




def update_existing_product(row, new_serial, new_name, new_number, new_position, new_design_stage,new_design_edition):
    """更新产品信息，并重命名产品文件夹"""
    # global curr_row_product_number, curr_row_product_name, curr_row_device_position, curr_row_design_stage, curr_row_design_edition
    # 初始化定时器
    init_tip_timer()
    try:
        # 获取旧值
        row_status = bianl.product_table_row_status.get(row, {})
        if not isinstance(row_status, dict):
            print(f"[警告] 第 {row + 1} 行状态结构异常，强制恢复为空字典")
            row_status = {}

        # 获取当前行的产品id
        curr_product_id = row_status.get("product_id", "")
        # 获取之前的必填项
        old_number = row_status.get("old_number", "")
        old_name = row_status.get("old_name", "")
        old_position = row_status.get("old_position", "")
        old_serial = row_status.get("old_serial", "")

        curr_row_product_name = new_name
        curr_row_product_number = new_number
        curr_row_device_position = new_position
        curr_row_design_edition = new_design_edition
        curr_row_design_stage = new_design_stage
        curr_row_serial = new_serial

        print(
            f"[update_existing_product] 即将更新的产品信息 - 编号: {curr_row_product_number}, 名称: {curr_row_product_name}, 设备位号: {curr_row_device_position}, 设计阶段: {curr_row_design_stage}, 设计版次: {curr_row_design_edition}")

        # 获取项目文件夹路径
        conn = common_usage.get_mysql_connection_project()
        cursor = conn.cursor()
        cursor.execute("SELECT 项目保存路径 FROM 项目需求表 WHERE 项目ID = %s", (bianl.current_project_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        project_path = result["项目保存路径"] if result and "项目保存路径" in result else None
        if not project_path:
            bianl.main_window.line_tip.setText("无法获取项目路径，跳过重命名文件夹。")
            bianl.main_window.line_tip.setToolTip("无法获取项目路径，跳过重命名文件夹。")
            bianl.main_window.line_tip.setStyleSheet("color: black;")
            bianl.tip_timer.stop()
            bianl.tip_timer.start(5000)
            # QMessageBox.warning(bianl.main_window, "警告", "无法获取项目路径，跳过重命名文件夹。")
        else:
            # 项目路径
            project_root = os.path.join(project_path, f"{bianl.owner_input.text().strip()}_{bianl.project_name_input.text().strip()}")
            # todo 文件夹名称重命名更改
            # 旧的产品文件夹的路径
            # old_parts = [old_serial, old_name, old_number, old_position]
            # old_folder_name = "_".join([p for p in old_parts if p])  # 自动跳过空字段
            old_folder_name = build_pd_folder_name(old_serial, old_name, old_position, old_number)
            new_folder_name = build_pd_folder_name(curr_row_serial, curr_row_product_name, curr_row_device_position, curr_row_product_number)

            # 新的产品文件夹名称的路径
            # new_parts = [curr_row_serial, curr_row_product_name, curr_row_product_number, curr_row_device_position]
            # new_folder_name= "_".join([p for p in new_parts if p])

            # 2) 拼出“完整路径”
            old_folder = os.path.join(project_root, old_folder_name)
            new_folder = os.path.join(project_root, new_folder_name)

            # if old_folder != new_folder and os.path.exists(old_folder):
            #     os.rename(old_folder, new_folder)

            print(f"[rename] project_root = {project_root}")
            print(f"[rename] old_folder = {old_folder}")
            print(f"[rename] new_folder = {new_folder}")

            try:
                if old_folder == new_folder:
                    print("[rename] 文件夹名未变化，跳过。")
                elif not os.path.isdir(old_folder):
                    print(f"[rename] 找不到旧文件夹：{old_folder}（可能旧值记录有误或路径不一致）")
                elif os.path.exists(new_folder):
                    print(f"[rename] 目标已存在：{new_folder}，为了安全不覆盖。")
                    bianl.main_window.line_tip.setText(f"已存在同名文件夹：\n{new_folder}\n请手动处理后再试。")
                    bianl.main_window.line_tip.setToolTip(f"已存在同名文件夹：\n{new_folder}\n请手动处理后再试。")
                    bianl.main_window.line_tip.setStyleSheet("color: black;")
                    # QMessageBox.warning(bianl.main_window, "提示",
                    #                     f"已存在同名文件夹：\n{new_folder}\n请手动处理后再试。")
                else:
                    os.rename(old_folder, new_folder)
                    print("[rename] ✅ 重命名完成")
                    # 同步更新产品设计活动表中的产品文件夹绝对路径
                    new_folder_abs = os.path.abspath(new_folder)
                    try:
                        conn_act = common_usage.get_mysql_connection_active()
                        cur_act = conn_act.cursor()
                        cur_act.execute(
                            "UPDATE 产品设计活动表 SET 产品文件夹绝对路径 = %s WHERE 产品ID = %s",
                            (new_folder_abs, curr_product_id)
                        )
                        conn_act.commit()
                        cur_act.close()
                        conn_act.close()
                        print(f"[update_existing_product] ✅ 产品设计活动表已同步路径: {new_folder_abs}")
                    except Exception as e_act:
                        print(f"[update_existing_product] ⚠️ 更新产品设计活动表路径失败: {e_act}")
                    # ★修改：更新 row_status 的 old_xxx 删除
                    # row_status["old_serial"] = curr_row_serial
                    # row_status["old_name"] = curr_row_product_name
                    # row_status["old_number"] = curr_row_product_number
                    # row_status["old_position"] = curr_row_device_position
            except Exception as e:
                print(f"[rename] ❌ 重命名失败：{e}")
                bianl.main_window.line_tip.setText(f"重命名失败：{e}")
                bianl.main_window.line_tip.setToolTip(f"重命名失败：{e}")
                bianl.main_window.line_tip.setStyleSheet("color: black;")
                # QMessageBox.critical(bianl.main_window, "错误", f"重命名失败：{e}")

        # 更新数据库信息（加入 WHERE 语句防止全表修改）
        conn = common_usage.get_mysql_connection_product()
        cursor = conn.cursor()
        # 根据三个相同的更新 根据产品id进行更新
        # todo 查产品id更新对了么
        sql = """
            UPDATE 产品需求表
            SET 产品编号 = %s, 产品名称 = %s, 设备位号 = %s, 设计阶段 = %s, 设计版次 = %s
            WHERE 产品ID = %s
        """
        values = (
            curr_row_product_number, curr_row_product_name, curr_row_device_position, curr_row_design_stage,
            curr_row_design_edition, curr_product_id
        )
        cursor.execute(sql, values)
        conn.commit()
        cursor.close()
        conn.close()

        auto_edit_row.update_status(row, "view")
        print("产品已经更新完成！")
        # 不单独显示提示框，由调用函数统一处理
        bianl.main_window.line_tip.setText("产品信息已成功更新。")
        bianl.main_window.line_tip.setToolTip("产品信息已成功更新。")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        bianl.tip_timer.stop()
        bianl.tip_timer.start(5000)
        #QMessageBox.information(bianl.main_window, "产品信息更新", "产品信息已成功更新。")改77
        return True
    except Exception as e:
        import traceback
        with open("error_log.txt", "a", encoding="utf-8") as log:
            log.write("[update_existing_product] 更新失败：\\n")
            log.write(traceback.format_exc() + "\\n")
        bianl.main_window.line_tip.setText(f"更新产品失败：{e}")
        bianl.main_window.line_tip.setToolTip(f"更新产品失败：{e}")
        bianl.main_window.line_tip.setStyleSheet("color: black;")
        # QMessageBox.critical(bianl.main_window, "产品信息更改", f"更新产品失败：{e}")
        return False



def is_product_row_empty(row):
    """判断指定行是否为完全空行（产品编号、名称、设备位号、型号全为空）"""

    def get_clean_text(col):
        item = bianl.product_table.item(row, col)
        return item.text().strip() if item and item.text() else ""

    return all(get_clean_text(col) == "" for col in [1, 2, 3, 4])

# # 高亮 这里好像要改
# from PyQt5.QtWidgets import QTableWidgetItem
# from PyQt5.QtGui import QBrush, QColor
# from PyQt5.QtCore import Qt

# from PyQt5.QtCore import QObject, QEvent
# from PyQt5.QtGui import QBrush, QColor
# from PyQt5.QtWidgets import QComboBox
# import modules.chanpinguanli.bianl as bianl
# import modules.chanpinguanli.common_usage as common_usage

# yxx改
# 🔹 事件过滤器：禁止下拉展开，但允许点击 yxx改
class ReadOnlyComboBoxFilter(QObject):
    def __init__(self, row, col):
        super().__init__()
        self.row = row
        self.col = col

    def eventFilter(self, obj, event):
        from modules.chanpinguanli.chanpinguanli_main import highlight_row_except_current
        etype = event.type()

        if etype == QEvent.MouseButtonPress:

            highlight_row_except_current(self.row, self.col)
            print("阻止展开")

            return True   # 阻止展开

        if etype == QEvent.MouseButtonRelease:
            print("阻止展开2")
            return True

        if etype in (QEvent.MouseButtonDblClick, QEvent.KeyPress, QEvent.KeyRelease, QEvent.Wheel):
            print("阻止展开3")
            return True

        return False



# 改后设置下拉框
# def setup_design_stage_combo(row: int, editable: bool):
#     """专门处理设计阶段下拉框的函数"""
#     print(f"[调试] setup_design_stage_combo 调用 → row={row}, editable={editable}")
#     # 如果处于“表头高亮模式”，则直接跳过设置
#     if getattr(bianl, "is_header_highlighting", False):
#         print(f"[调试] 行 {row} 在表头高亮模式下 → 跳过样式设置")
#         return
#
#         # ✅ 屏蔽信号，防止无限递归
#     # bianl.product_table.blockSignals(True)
#
#     # ✅ 获取当前显示值（优先 QComboBox，再取 QTableWidgetItem）
#     # 去看看现在这格（第 row 行第 4 列）是不是已经有下拉框了，
#     # 如果有，那就记下它原来的值，比如“方案设计”或“详细设计” 没有就重新创建一下下拉框
#     # current_text先准备一个空变量
#     current_text = ""
#     # 获取控件，赋值给变量 widget
#     widget = bianl.product_table.cellWidget(row, 4)
#     # 先判断这个单元格有没有嵌入控件（widget 不为 None），并且这个控件是 QComboBox 类型（即下拉框）。
#     if widget and isinstance(widget, QComboBox):
#         # 从下拉框中获取当前显示的文本（即选中的选项）
#         current_text = widget.currentText().strip()
#         combo = widget
#         print(f"[调试] 行 {row} 已存在 QComboBox, currentText={combo.currentText()}")
#     #     控件不存在、或者说控件不是下拉框
#     elif bianl.product_table.item(row, 4):
#         # 不存在下拉框 或者是普通的文本
#         current_text = bianl.product_table.item(row, 4).text().strip()
#         print(f"[调试] 行 {row} 当前 QTableWidgetItem（控件/普通框） 文本: {current_text}")
#         # 下拉框控件不存在 创建下拉框
#         combo = QComboBox()
#         bianl.product_table.setCellWidget(row, 4, combo)
#         print(f"[调试] 行 {row} 新建 QComboBox")
#     else:
#         # 完全为空，既没有控件也没有 QTableWidgetItem
#         print(f"[调试] 行 {row} 无控件、无内容，直接创建 QComboBox")
#         combo = QComboBox()
#         bianl.product_table.setCellWidget(row, 4, combo)
#
#     # ✅ 外观样式设置 可编辑的
#     if editable:
#         print(f"[调试] 行 {row} → 设置为可编辑样式（白底黑字 + hover 蓝底白字）")
#         combo.setEnabled(True)
#         combo.setEditable(False)
#
#         # ✅ 卸载只读过滤器（如果之前加过） 要不editable的时候不能弹出
#         if hasattr(combo, "readonly_filter"):
#             combo.removeEventFilter(combo.readonly_filter)
#             del combo.readonly_filter
#             print(f"[调试] 行 {row} 已卸载 ReadOnlyComboBoxFilter")
#
#         combo.setStyleSheet("""
#             QComboBox {
#                 background-color: #ffffff;
#                 color: black;
#                 border: 0px;
#                 padding: 6px 8px;
#                 font-size: 11pt;
#                 font-family: '宋体';
#             }
#             QComboBox::drop-down { width: 0px; border: none; background: transparent; }
#             QComboBox::down-arrow { image: none; width: 0px; height: 0px; }
#             QComboBox QAbstractItemView {
#                 background-color: #ffffff;
#                 color: black;
#                 selection-background-color: #d0e7ff;
#                 selection-color: black;
#             }
#         """)
#     # view的样式
#     else:
#         print(f"[调试] 行 {row} → 设置为不可编辑样式（灰字白底）")
#         combo.setEnabled(True)
#         combo.setEditable(False)
#         combo.setStyleSheet("""
#             QComboBox {
#                 background-color: #ffffff;
#                 color: #888888;
#                 border: 0px;
#                 padding: 6px 8px;
#                 font-size: 11pt;
#                 font-family: '宋体';
#             }
#             QComboBox::drop-down { width: 0px; border: none; background: transparent; }
#             QComboBox::down-arrow { image: none; width: 0px; height: 0px; }
#         """)
#
#         # 安装只读事件过滤器 只读的情况下：看得见 但是点不了的处理
#         if not hasattr(combo, "readonly_filter"):
#             combo.readonly_filter = ReadOnlyComboBoxFilter(row, 4)
#             combo.installEventFilter(combo.readonly_filter)
#             print(f"[调试] 行 {row} 安装了 ReadOnlyComboBoxFilter")
#         else:
#             print(f"[调试] 行 {row} 已存在事件过滤器 {combo.readonly_filter}")
#     # ✅ 加载选项（仅当为空时加载一次）  下拉框为空的时候，从数据库里查两个选项填入
#     # 判断当前这个 QComboBox 里面有没有下拉项
#     # combo = QComboBox()是刚加入的下拉框
#     if combo.count() == 0:
#         design_stages = common_usage.get_product_design_time_db()
#         combo.addItems(design_stages)
#         print(f"[调试] 行 {row} 加载设计阶段选项: {design_stages}")
#
#     # ✅ 设置显示值（必须在加载完选项后）
#     if current_text:
#         # 根据文字找到索引
#         idx = combo.findText(current_text)
#         if idx >= 0:
#             # 通过设置索引 将下拉框的设置成相应的选项
#             combo.setCurrentIndex(idx)
#             print(f"[调试] 行 {row} 设置当前索引 idx={idx}")
#         else:
#             # 找不到文本对应的索引  显示出来保持原样
#             combo.setCurrentText(current_text)
#             print(f"[调试] 行 {row} 设置当前文本 {current_text}")
#     # 空白行 设置成-1 空白
#     else:
#         combo.setCurrentIndex(-1)
#         print(f"[调试] 行 {row} 没有文本，设置为 -1")
#     bianl.product_table.blockSignals(False)
#
#     # ✅ 若是 editable 状态，绑定联动行为
#     if editable:
#         from modules.chanpinguanli import auto_edit_row
#         auto_edit_row.bind_design_combo(combo, row, 4)
#         print(f"[调试] 行 {row} 绑定了 auto_edit_row.bind_design_combo")


# def set_row_editable(row: int, editable: bool):
#     print(f"[set_row_editable] 设置第 {row} 行为 {'可编辑' if editable else '不可编辑'}")
#     # 获取列数
#     col_count = bianl.product_table.columnCount()
#     # 从第一列开始
#     for col in range(1, col_count):
#         # 特殊处理设计阶段列（第4列，索引从0开始是3）
#         if col == 4:
#             # 调用专门处理设计阶段下拉框的函数改77
#             setup_design_stage_combo(row, editable)
#             print(f"进入{row}行，添加下拉框")
#         else:
#             # 普通列的处理逻辑不变
#             # 获取当前单元格的 QTableWidgetItem 项（单元格内容 + 属性）
#             item = bianl.product_table.item(row, col)
#             # 如果该单元格是空的（没有任何 item），就新建一个空单元格并放入表格
#             if item is None:
#                 item = QTableWidgetItem("")
#                 bianl.product_table.setItem(row, col, item)
#             else:
#                 #     存在的话
#                 # ✅ 保留已有文本与背景色
#                 text = item.text()
#                 background = item.background()
#
#                 item = QTableWidgetItem(text)
#                 item.setBackground(background)  # ✅ 恢复背景色
#                 # 保留对当前的文本与背景颜色
#                 bianl.product_table.setItem(row, col, item)
#
#             if editable:
#                 item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)
#                 item.setForeground(QBrush(QColor("#000000")))  # 黑色字体
#
#             else:
#                 item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
#                 item.setForeground(QBrush(QColor("#888888")))  # 灰色字体
#                 print("common不可编辑")


# 之前的 只设置颜色
def set_row_editable(row: int, editable: bool):
    log_debug(f"[set_row_editable] 设置第 {row} 行为 {'可编辑' if editable else '不可编辑'}")
    # 获取列数
    col_count = bianl.product_table.columnCount()
    # 从第一列开始
    for col in range(1, col_count):
        # 获取当前单元格的 QTableWidgetItem 项（单元格内容 + 属性）
        item = bianl.product_table.item(row, col)
        # 如果该单元格是空的（没有任何 item），就新建一个空单元格并放入表格
        if item is None:
            item = QTableWidgetItem("")
            bianl.product_table.setItem(row, col, item)
        else:
            #     存在的话
            # ✅ 保留已有文本与背景色
            text = item.text()
            background = item.background()

            item = QTableWidgetItem(text)
            item.setBackground(background)  # ✅ 恢复背景色
            # 保留对当前的文本与背景颜色
            bianl.product_table.setItem(row, col, item)

        if editable:
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)
            item.setForeground(QBrush(QColor("#000000")))  # 黑色字体

        else:
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            item.setForeground(QBrush(QColor("#888888")))  # 黑色字体
            print("common不可编辑")
