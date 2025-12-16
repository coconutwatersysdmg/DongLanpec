import pymysql
import re
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTableWidgetItem, QMessageBox, QWidget, QComboBox, QLabel, QDialog, QVBoxLayout, \
    QListWidget, QHBoxLayout, QPushButton
from functools import partial
from PyQt5.QtWidgets import QAbstractItemView
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QTableWidgetSelectionRange

from modules.guankoudingyi.db_cnt import get_connection, db_config_1, db_config_2

# —— 运行期隐藏ID映射 + 待删ID 集合 ——
def ensure_hidden_maps(stats_widget):
    if not hasattr(stats_widget, "row_hidden_pipe_id"):
        stats_widget.row_hidden_pipe_id = {}   # {row_index: 管口ID}
    if not hasattr(stats_widget, "deleted_pipe_ids"):
        stats_widget.deleted_pipe_ids = set()  # {管口ID}

# —— 计算“下一管口ID”（只分配，不入库）——
def get_next_pipe_id_runtime(stats_widget, product_id):
    """
    返回一个“尚未使用”的新 管口ID：
    max(数据库中该产品已有管口ID, 运行期已分配但未落库的管口ID) + 1
    """
    from modules.guankoudingyi.db_cnt import get_connection
    import pymysql
    ensure_hidden_maps(stats_widget)

    max_db = 0
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as c:
            c.execute("SELECT MAX(管口ID) AS mx FROM 产品设计活动表_管口表 WHERE 产品ID=%s", (product_id,))
            row = c.fetchone()
            if row and row.get("mx") is not None:
                max_db = int(row["mx"])
    finally:
        conn.close()

    max_runtime = 0
    if stats_widget.row_hidden_pipe_id:
        try:
            max_runtime = max(int(v) for v in stats_widget.row_hidden_pipe_id.values() if v is not None)
        except ValueError:
            max_runtime = 0

    return max(max_db, max_runtime) + 1

# —— 行交换时，同步隐藏“管口ID”映射 ——
def swap_hidden_id(stats_widget, row_a, row_b):
    ensure_hidden_maps(stats_widget)
    ida = stats_widget.row_hidden_pipe_id.get(row_a)
    idb = stats_widget.row_hidden_pipe_id.get(row_b)
    if ida is None and idb is None:
        return
    if ida is None:
        stats_widget.row_hidden_pipe_id.pop(row_b, None)
    else:
        stats_widget.row_hidden_pipe_id[row_b] = ida
    if idb is None:
        stats_widget.row_hidden_pipe_id.pop(row_a, None)
    else:
        stats_widget.row_hidden_pipe_id[row_a] = idb


"""数据读取，界面显示，数据存入产品设计活动表_管口表"""
def read_pipe_temp(stats_widget, belong_type, belong_version, product_id):
    """
    读取顺序：
      1) 产品设计活动库.产品设计活动表_管口表（带管口ID）
      2) 若无 → 元件库.管口默认表（带管口ID），并将其插入到产品表
      3) 若仍无 → 弹窗并清空界面
    """
    table_pipe = stats_widget.tableWidget_pipe  # 获取界面表格控件
    ensure_hidden_maps(stats_widget)

    # 先连接
    conn_component = get_connection(**db_config_1)
    conn_product = get_connection(**db_config_2)
    cursor_component = conn_component.cursor(pymysql.cursors.DictCursor)
    cursor_product = conn_product.cursor(pymysql.cursors.DictCursor)
    try:
        # ==== 标记数据来源（默认认为不是来自“默认表”）====
        loaded_from_default = False
        # 先查产品表（带 管口ID）
        cursor_product.execute("""
            SELECT 管口ID, 管口代号, 管口功能, 管口用途, 公称尺寸, 法兰标准, 压力等级, 法兰型式,
                   密封面型式, 焊端规格, 管口所属元件, 轴向定位基准, 轴向定位距离,
                   `轴向夹角（°）`, `周向方位（°）`, `偏心距`, 外伸高度, 管口附件, 管口载荷
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s
            ORDER BY 管口ID ASC
        """, (product_id,))
        rows = cursor_product.fetchall()
        # 若产品表无数据 → 查默认表（带 管口ID）
        if not rows:
            cursor_component.execute("""
                SELECT 管口ID, 管口代号, 管口功能, 管口用途, 公称尺寸, 法兰标准, 压力等级, 法兰型式,
                       密封面型式, 焊端规格, 管口所属元件, 轴向定位基准, 轴向定位距离,
                       `轴向夹角（°）`, `周向方位（°）`, `偏心距`, 外伸高度, 管口附件, 管口载荷
                FROM 管口默认表
                WHERE 所属类型 = %s AND 所属型式 = %s
                ORDER BY 管口ID ASC
            """, (belong_type, belong_version))
            rows = cursor_component.fetchall()

            if not rows:
                QMessageBox.information(stats_widget, "查询结果", "未在管口默认表中找到默认数据")
                table_pipe.clearContents()
                table_pipe.setRowCount(0)
                return

            # 把默认数据（含 管口ID）落库到产品表（防重复：依赖唯一键 (产品ID, 管口ID)）
            cursor_product.executemany("""
                INSERT INTO 产品设计活动表_管口表 (
                    产品ID, 管口ID, 管口代号, 管口功能, 管口用途, 公称尺寸, 法兰标准, 压力等级,
                    法兰型式, 密封面型式, 焊端规格, 管口所属元件, 轴向定位基准, 轴向定位距离,
                    `轴向夹角（°）`, `周向方位（°）`, `偏心距`, 外伸高度, 管口附件, 管口载荷, 管口更改状态
                ) VALUES (
                    %(产品ID)s, %(管口ID)s, %(管口代号)s, %(管口功能)s, %(管口用途)s, %(公称尺寸)s, %(法兰标准)s, %(压力等级)s,
                    %(法兰型式)s, %(密封面型式)s, %(焊端规格)s, %(管口所属元件)s, %(轴向定位基准)s, %(轴向定位距离)s,
                    %(轴向夹角（°）)s, %(周向方位（°）)s, %(偏心距)s, %(外伸高度)s, %(管口附件)s, %(管口载荷)s, '未更改'
                )
                ON DUPLICATE KEY UPDATE 管口代号=VALUES(管口代号)
            """, [{**r, "产品ID": product_id} for r in rows])
            conn_product.commit()

            # ==== 只有“来自默认表并首落库”的情况，才标记 True ====
            loaded_from_default = True

        # —— 渲染到UI（并建立隐藏ID映射）——
        table_pipe.clearContents()
        table_pipe.setRowCount(len(rows))
        stats_widget.row_hidden_pipe_id.clear()

        # ✅ 初始化 pipe_belong_old_values，保存加载时的管口所属元件值
        if not hasattr(stats_widget, 'pipe_belong_old_values'):
            stats_widget.pipe_belong_old_values = {}
        else:
            stats_widget.pipe_belong_old_values.clear()

        fields = ["管口代号", "管口功能", "管口用途", "公称尺寸", "法兰标准", "压力等级", "法兰型式",
                  "密封面型式", "焊端规格", "管口所属元件", "轴向定位基准", "轴向定位距离",
                  "轴向夹角（°）", "周向方位（°）", "偏心距", "外伸高度", "管口附件", "管口载荷"]
        for rr, row in enumerate(rows):
            stats_widget.row_hidden_pipe_id[rr] = row.get("管口ID")  # 记录隐藏ID
            for cc, name in enumerate(fields, start=1):
                val = row.get(name)
                text = "" if val is None or str(val) == "None" else str(val)
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                table_pipe.setItem(rr, cc, item)

            # ✅ 保存管口所属元件的初始值到 pipe_belong_old_values
            pipe_belong_val = row.get("管口所属元件")
            pipe_belong_text = "" if pipe_belong_val is None or str(pipe_belong_val) == "None" else str(pipe_belong_val).strip()
            stats_widget.pipe_belong_old_values[rr] = pipe_belong_text

        stats_widget.refresh_pipe_table_sequence()
        check_last_row_and_add_new(stats_widget)
        stats_widget.adjust_pipe_column_width()
        set_pipe_function_column_readonly(stats_widget)
        # 设置默认管口不可删除
        set_default_pipe_cannot_be_deleted(stats_widget)

        # ====只有首次创建（loaded_from_default=True）才触发自动推荐 ====
        if loaded_from_default:
            try:
                from modules.guankoudingyi.funcs.funcs_pipe_comboBox_value import \
                    auto_recommend_nominal_sizes_for_first_four_pipes
                auto_recommend_nominal_sizes_for_first_four_pipes(stats_widget, product_id)
            except Exception as e:
                print(f"[ERROR] 自动推荐公称尺寸失败: {str(e)}")

    except Exception as e:
        conn_product.rollback()
        QMessageBox.critical(stats_widget, "数据库错误", f"读取管口数据失败：{e}")
    finally:
        cursor_component.close();
        conn_component.close()
        cursor_product.close();
        conn_product.close()

"""管口功能列和管口所属元件列部分只读"""
# def set_pipe_function_column_readonly(stats_widget):
#     """
#     根据产品所属类型和型式，将特定的"管口功能"项和对应的"管口所属元件"项设为不可编辑。
#     排序后调用本函数，确保只读状态被重置。
#     """
#     table = stats_widget.tableWidget_pipe
#     product_type = getattr(stats_widget, "current_product_type", "")
#     product_version = getattr(stats_widget, "current_product_version", "")
#
#     # 定义每种类型下不可编辑的功能值
#     readonly_values = set()
#
#     if product_type == "管壳式热交换器":
#         if product_version in ["AEU", "BEU"]:
#             readonly_values = {"管程入口", "管程出口", "壳程入口", "壳程出口"}
#         elif product_version in ["AES", "BES"]:
#             readonly_values = {"管程入口", "管程出口", "壳程入口", "壳程出口"}
#         elif product_version in ["NEN"]:
#             readonly_values = {"管程入口", "管程出口", "壳程入口", "壳程出口"}
#         elif product_version in ["BEM"]:
#             readonly_values = {"管程入口", "管程出口", "壳程入口", "壳程出口"}
#
#     # 对于 NEN 类型，定义哪些功能的管口所属元件列应该可编辑
#     # NEN类型的"管程入口"、"管程出口"的管口所属元件列可编辑
#     belong_editable_for_nen = set()
#
#     if product_type == "管壳式热交换器" and product_version in ["NEN"]:
#         belong_editable_for_nen = {"管程入口", "管程出口"}
#
#     # 遍历表格行，同时设置管口功能列和管口所属元件列的只读状态
#     func_col = 2  # 管口功能列
#     belong_col = 10  # 管口所属元件列
#
#     for row in range(table.rowCount() - 1):  # 排除最后空白行
#         func_item = table.item(row, func_col)
#         belong_item = table.item(row, belong_col)
#
#         if not func_item:
#             continue
#
#         func_value = func_item.text().strip()
#         is_func_readonly = func_value in readonly_values
#
#         # 设置管口功能列的只读状态
#         if is_func_readonly:
#             func_item.setFlags(func_item.flags() & ~Qt.ItemIsEditable)
#         else:
#             func_item.setFlags(func_item.flags() | Qt.ItemIsEditable)
#
#         # 设置管口所属元件列的只读状态
#         # 对于 NEN BEM 类型，如果管口功能在 belong_editable_for_nen 中，则管口所属元件列可编辑
#         if belong_item:
#             if product_type == "管壳式热交换器" and product_version in ["NEN"]:
#                 # NEN 类型：管程入口、管程出口的管口所属元件列可编辑
#                 if func_value in belong_editable_for_nen:
#                     belong_item.setFlags(belong_item.flags() | Qt.ItemIsEditable)
#                 elif is_func_readonly:
#                     # 其他只读功能的管口所属元件列仍然只读
#                     belong_item.setFlags(belong_item.flags() & ~Qt.ItemIsEditable)
#                 else:
#                     # 非只读功能的管口所属元件列可编辑
#                     belong_item.setFlags(belong_item.flags() | Qt.ItemIsEditable)
#             else:
#                 # 其他类型：管口所属元件列的只读状态与管口功能列保持一致
#                 if is_func_readonly:
#                     belong_item.setFlags(belong_item.flags() & ~Qt.ItemIsEditable)
#                 else:
#                     belong_item.setFlags(belong_item.flags() | Qt.ItemIsEditable)
"""管口功能列和管口所属元件列部分只读"""
def set_pipe_function_column_readonly(stats_widget):
    """
    根据产品所属类型和型式，将特定的"管口功能"项和对应的"管口所属元件"项设为不可编辑。
    排序后调用本函数，确保只读状态被重置。
    """
    table = stats_widget.tableWidget_pipe
    product_type = getattr(stats_widget, "current_product_type", "")
    product_version = getattr(stats_widget, "current_product_version", "")

    # 定义每种类型下不可编辑的功能值
    readonly_values = set()

    if product_type == "管壳式热交换器":
        if product_version in ["AEU", "BEU"]:
            readonly_values = {"管程入口", "管程出口", "壳程入口", "壳程出口"}
        elif product_version in ["AES", "BES"]:
            readonly_values = {"管程入口", "管程出口", "壳程入口", "壳程出口"}
        elif product_version in ["NEN"]:
            readonly_values = {"管程入口", "管程出口", "壳程入口", "壳程出口"}
        elif product_version in ["BEM"]:
            readonly_values = {"管程入口", "管程出口", "壳程入口", "壳程出口"}

    # 所有类型的"管程入口"、"管程出口"的管口所属元件列可编辑
    belong_editable_functions = set()  # 变量名从belong_editable_for_nen改为更通用的名称
    if product_type == "管壳式热交换器" and product_version in ["NEN", "BEM","AES","BES","AEU","BEU"]:
        belong_editable_functions = {"管程入口", "管程出口"}

    # 遍历表格行，同时设置管口功能列和管口所属元件列的只读状态
    func_col = 2  # 管口功能列
    belong_col = 10  # 管口所属元件列

    for row in range(table.rowCount() - 1):  # 排除最后空白行
        func_item = table.item(row, func_col)
        belong_item = table.item(row, belong_col)

        if not func_item:
            continue

        func_value = func_item.text().strip()
        is_func_readonly = func_value in readonly_values

        # 设置管口功能列的只读状态
        if is_func_readonly:
            func_item.setFlags(func_item.flags() & ~Qt.ItemIsEditable)
        else:
            func_item.setFlags(func_item.flags() | Qt.ItemIsEditable)

        # 设置管口所属元件列的只读状态
        if belong_item:
            if product_type == "管壳式热交换器" and product_version in ["NEN", "BEM","AES","BES","AEU","BEU"]:  # 加入BEM
                #管程入口、管程出口的管口所属元件列可编辑
                if func_value in belong_editable_functions:  # 同步使用新的变量名
                    belong_item.setFlags(belong_item.flags() | Qt.ItemIsEditable)
                elif is_func_readonly:
                    # 其他只读功能的管口所属元件列仍然只读
                    belong_item.setFlags(belong_item.flags() & ~Qt.ItemIsEditable)
                else:
                    # 非只读功能的管口所属元件列可编辑
                    belong_item.setFlags(belong_item.flags() | Qt.ItemIsEditable)
            else:
                # 其他类型：管口所属元件列的只读状态与管口功能列保持一致
                if is_func_readonly:
                    belong_item.setFlags(belong_item.flags() & ~Qt.ItemIsEditable)
                else:
                    belong_item.setFlags(belong_item.flags() | Qt.ItemIsEditable)

"""管口删除"""
def delete_selected_pipe_rows(stats_widget, product_id):
    """
    删除选中行：只删界面；同时记录这些行对应的"隐藏管口ID"到 stats_widget.deleted_pipe_ids。
    真正的数据库删除在"确认保存"时执行。
    如果 cannot_be_deleted 为 True，会检查是否包含不可删除的默认管口。
    """
    ensure_hidden_maps(stats_widget)
    table = stats_widget.tableWidget_pipe
    selected_rows = sorted(set(index.row() for index in table.selectedIndexes()), reverse=True)

    # 排除最后一行
    last_row_index = table.rowCount() - 1
    selected_rows = [r for r in selected_rows if r != last_row_index]

    if not selected_rows:
        stats_widget.line_tip.setText("最后一行不能删除，请选择其他要删除的管口行")
        stats_widget.line_tip.setStyleSheet("color: red;")
        return

    # 检查是否包含不可删除的默认管口（当 cannot_be_deleted 为 True 时）
    cannot_be_deleted = getattr(stats_widget, "cannot_be_deleted", True)
    readonly_pipe_functions = getattr(stats_widget, "readonly_pipe_functions", set())

    if cannot_be_deleted and readonly_pipe_functions:
        # 检查选中的行中是否包含不可删除的管口（根据管口功能列判断）
        protected_pipe_functions = []
        for row in selected_rows:
            pipe_function_item = table.item(row, 2)  # 第2列为管口功能
            if pipe_function_item:
                pipe_function = pipe_function_item.text().strip()
                if pipe_function in readonly_pipe_functions:
                    protected_pipe_functions.append(pipe_function)

        # 如果包含不可删除的管口，阻止删除
        if protected_pipe_functions:
            # 格式化提示信息，根据管口功能生成提示
            function_names = "、".join(set(protected_pipe_functions))  # 使用set去重
            QMessageBox.warning(
                stats_widget,
                "删除失败",
                f"该管口功能为{function_names}，不可删除，您可更改其管口代号和移动其管口顺序。"
            )
            #stats_widget.line_tip.setText(f"管口功能为 {function_names} 的管口不可删除")
            #stats_widget.line_tip.setStyleSheet("color: red;")
            return

    # 确认删除
    reply = QMessageBox.question(
        stats_widget, "确认删除", f"确定要删除选中的 {len(selected_rows)} 行管口数据吗？",
        QMessageBox.Yes | QMessageBox.No, QMessageBox.No
    )
    if reply != QMessageBox.Yes:
        return

    for row in selected_rows:
        hid = getattr(stats_widget, "row_hidden_pipe_id", {}).pop(row, None)
        if hid is not None:
            stats_widget.deleted_pipe_ids.add(hid)
        table.removeRow(row)
    # 序号的刷新
    stats_widget.refresh_pipe_table_sequence()


"""管口上移"""
def move_selected_pipe_rows_up(stats_widget):
    """
    将选中的行在界面上向上移动一行（仅界面显示，不修改数据库）
    :param stats_widget: 主窗口对象
    """
    table = stats_widget.tableWidget_pipe

    # 修改获取选中行的方式，使用与highlight_selected_rows相同的方法
    selected_rows = sorted(set(idx.row() for idx in table.selectedIndexes()))

    # 禁止最后一行参与上移（最后一行用于新增）
    last_row_index = table.rowCount() - 1
    selected_rows = [r for r in selected_rows if r != last_row_index]

    if not selected_rows:
        stats_widget.line_tip.setText("最后一行不能上移，请先选择要上移的行")#提示
        stats_widget.line_tip.setStyleSheet("color: red;")
        return

    if selected_rows[0] <= 0:
        stats_widget.line_tip.setText("已到顶部，无法继续上移")#提示 有问题
        stats_widget.line_tip.setStyleSheet("color: red;")
        return
    
    # 阻止信号触发
    table.blockSignals(True)
    
    # 从上到下处理每一行（顺序很重要）
    for row in selected_rows:
        above_row = row - 1
        for col in range(1, table.columnCount()):  # 跳过序号列
            # 获取当前行和上一行的单元格内容
            current_item = table.takeItem(row, col)
            above_item = table.takeItem(above_row, col)
            # 交换单元格内容
            
            table.setItem(row, col, above_item)
            table.setItem(above_row, col, current_item)

    # 更新序号列
    stats_widget.refresh_pipe_table_sequence()

    # 清除之前的选中
    table.clearSelection()
    # 使用 setRangeSelected 强制选中行范围
    for row in [r - 1 for r in selected_rows]:
        table.setRangeSelected(QTableWidgetSelectionRange(row, 0, row, table.columnCount() - 1), True)
    # 强制焦点回到表格
    table.setFocus()
    # 延迟调用高亮处理，确保 selectionModel 处于最新状态
    # QTimer.singleShot(0, stats_widget.highlight_selected_rows)
    # 恢复信号
    table.blockSignals(False)
    # 手动调用高亮方法，确保高亮样式跟随移动
    # stats_widget.highlight_selected_rows()
    #——同步隐藏ID——
    for row in selected_rows:
        swap_hidden_id(stats_widget, row, row-1)

"""管口下移"""
def move_selected_pipe_rows_down(stats_widget):
    """
    将选中的行在界面上向下移动一行（不交换序号列，序号列重新编号）
    """
    table = stats_widget.tableWidget_pipe
    row_count = table.rowCount()
    
    # 修改获取选中行的方式，使用与highlight_selected_rows相同的方法
    selected_rows = sorted(set(idx.row() for idx in table.selectedIndexes()), reverse=True)

    if not selected_rows:
        stats_widget.line_tip.setText("请先选中要下移的行")#提示
        stats_widget.line_tip.setStyleSheet("color: red;")
        return

    if selected_rows[0] >= row_count - 2:
        stats_widget.line_tip.setText("已到最底部，无法继续下移")#提示
        stats_widget.line_tip.setStyleSheet("color: red;")
        return

    # 阻止信号触发
    table.blockSignals(True)

    # 从下到上处理每一行（顺序很重要）
    for row in selected_rows:
        below_row = row + 1
        if below_row >= row_count:
            continue
            
        for col in range(1, table.columnCount()):  # 从第1列开始交换（跳过序号列）
            current_item = table.takeItem(row, col)
            below_item = table.takeItem(below_row, col)
            
            table.setItem(row, col, below_item)
            table.setItem(below_row, col, current_item)

    # 更新序号列
    stats_widget.refresh_pipe_table_sequence()
    # 清除旧选中行
    table.clearSelection()
    # 新选中的行（下移后 +1）
    new_selected_rows = [r + 1 for r in selected_rows if r + 1 < row_count]
    for row in new_selected_rows:
        table.setRangeSelected(QTableWidgetSelectionRange(row, 0, row, table.columnCount() - 1), True)
    # 强制焦点刷新
    table.setFocus()
    # 延迟调用高亮处理
    # QTimer.singleShot(0, stats_widget.highlight_selected_rows)
    # 恢复信号
    table.blockSignals(False)
    # 手动调用高亮方法，确保高亮样式跟随移动
    # stats_widget.highlight_selected_rows()
    # ——同步隐藏ID——
    for row in selected_rows:
        swap_hidden_id(stats_widget, row, row + 1)


"""检查最后一行的管口代号是否已填写，如果已填写则添加新行"""
def check_last_row_and_add_new(stats_widget):
    """
    检查最后一行的管口代号是否已填写，如果已填写则添加新行
    :param stats_widget: 主窗口实例
    """
    table = stats_widget.tableWidget_pipe
    last_row = table.rowCount() - 1

    if last_row < 0:
        return  # 表格为空，跳过

    # 获取最后一行的管口代号
    last_port_code_item = table.item(last_row, 1)
    last_code_text = last_port_code_item.text().strip() if last_port_code_item else ""

    # 如果最后一行的管口代号不为空，添加新行
    if last_code_text:
        # 添加新行
        # === 临时断开 cellChanged 信号，防止误触发验证 ===
        try:
            table.blockSignals(True)
            # 添加新行
            new_row = table.rowCount()
            table.setRowCount(new_row + 1)

            # 设置新行的每个单元格为空白并居中
            for col in range(table.columnCount()):
                item = QTableWidgetItem()
                item.setTextAlignment(Qt.AlignCenter)
                if col == 0:
                    item.setText(str(new_row + 1)) # 序号列
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable) # 序号列不可编辑
                elif col == 1:
                    # 管口代号列：保持可编辑
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)
                else:
                    # 其他列：设为不可编辑（冻结状态）
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                table.setItem(new_row, col, item)
            
            # 添加新行后自动调整列宽
            stats_widget.adjust_pipe_column_width()
        finally:
            # === 恢复信号连接 ===
            table.blockSignals(False)
        # 刷新序号
        stats_widget.refresh_pipe_table_sequence()

"""控制最后一行其他列的编辑状态"""
def control_last_row_editable_state(stats_widget, enable_editing=True):
    """
    控制最后一行除管口代号外其他列的可编辑状态
    :param stats_widget: 主窗口实例
    :param enable_editing: True为解冻（可编辑），False为冻结（不可编辑）
    """
    table = stats_widget.tableWidget_pipe
    last_row = table.rowCount() - 1
    
    if last_row < 0:
        return
    
    # 检查是否确实是最后一行且管口代号已填写
    last_port_code_item = table.item(last_row, 1)
    if not last_port_code_item:
        return
    
    print(f"[DEBUG] 最后一行管口代号: '{last_port_code_item.text()}'")
    
    changed_count = 0
    for col in range(2, table.columnCount()):  # 从第2列开始（跳过序号和管口代号）
        item = table.item(last_row, col)
        if item:
            if enable_editing:
                # 解冻：恢复可编辑状态
                old_flags = item.flags()
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)
                new_flags = item.flags()
                if old_flags != new_flags:
                    changed_count += 1
                    print(f"[DEBUG] 列{col} 解冻成功")
            else:
                # 冻结：设为不可编辑
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                changed_count += 1


"""判断新输入的管口代号是否在界面上已存在"""
def is_duplicate_port_code(table, new_code: str, current_row: int) -> bool:
    """
    判断新输入的管口代号是否与其他行重复（排除自身）
    """
    for row in range(table.rowCount() - 1):  # 不包含新增空行
        if row == current_row:
            continue
        item = table.item(row, 1)  # 第1列为管口代号
        if item and item.text().strip() == new_code:
            return True
    return False


"""管口复制功能"""

"""对需要复制的管口选择"""
def copy_pipe_data(stats_widget, product_id):
    """
    管口复制功能：弹出对话框选择要复制的管口，然后复制到最新的空白行
    """


    table_pipe = stats_widget.tableWidget_pipe

    # 收集当前界面所有已填写的管口号
    pipe_codes = []
    for row in range(table_pipe.rowCount() - 1):  # 排除最后空白行
        code_item = table_pipe.item(row, 1)  # 第1列为管口代号
        if code_item and code_item.text().strip():
            pipe_codes.append(code_item.text().strip())

    if not pipe_codes:
        QMessageBox.information(stats_widget, "提示", "当前没有可复制的管口数据")
        return

    # 创建选择对话框
    dialog = QDialog(stats_widget)
    dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)
    dialog.setWindowTitle("管口复制")
    dialog.setModal(True)
    dialog.resize(300, 400)

    layout = QVBoxLayout(dialog)

    # 添加说明标签
    label = QLabel("请选择要复制的管口代号：")
    label.setStyleSheet("background-color: transparent;")
    layout.addWidget(label)

    # 创建列表控件
    list_widget = QListWidget()
    list_widget.addItems(pipe_codes)
    layout.addWidget(list_widget)

    # 按钮布局
    button_layout = QHBoxLayout()

    # 确定按钮
    ok_button = QPushButton("确定")
    ok_button.clicked.connect(dialog.accept)

    # 取消按钮
    cancel_button = QPushButton("取消")
    cancel_button.clicked.connect(dialog.reject)

    button_layout.addWidget(ok_button)
    button_layout.addWidget(cancel_button)
    layout.addLayout(button_layout)

    # 显示对话框
    if dialog.exec_() == QDialog.Accepted:
        selected_items = list_widget.selectedItems()
        if not selected_items:
            QMessageBox.warning(stats_widget, "警告", "请选择一个管口进行复制")
            return

        selected_code = selected_items[0].text()

        # 找到选中的管口所在行
        source_row = -1
        for row in range(table_pipe.rowCount() - 1):
            code_item = table_pipe.item(row, 1)
            if code_item and code_item.text().strip() == selected_code:
                source_row = row
                break

        if source_row == -1:
            QMessageBox.warning(stats_widget, "错误", "未找到选中的管口数据")
            return

        # 复制数据到最新空白行
        copy_pipe_row_data(stats_widget, source_row, product_id)

"""复制选中数据到空白行选择"""
def copy_pipe_row_data(stats_widget, source_row: int, product_id):
    """
    将指定行的管口数据复制到最新的空白行（倒数第一行）
    """
    table_pipe = stats_widget.tableWidget_pipe
    ensure_hidden_maps(stats_widget)

    # 找到最新的空白行（倒数第一行，即最后一行）
    target_row = table_pipe.rowCount() - 1

    # 检查最后一行是否已有数据
    last_row_code_item = table_pipe.item(target_row, 1)  # 第1列为管口代号
    if last_row_code_item and last_row_code_item.text().strip():
        # 如果最后一行已有数据，需要先添加新的空白行
        # 调用现有的函数来添加新行
        check_last_row_and_add_new(stats_widget)
        # 重新获取目标行（现在应该是新添加的空白行）
        target_row = table_pipe.rowCount() - 1

    # 复制数据（跳过序号列）
    fields = ["管口代号", "管口功能", "管口用途", "公称尺寸", "法兰标准", "压力等级", "法兰型式",
              "密封面型式", "焊端规格", "管口所属元件", "轴向定位基准", "轴向定位距离",
              "轴向夹角（°）", "周向方位（°）", "偏心距", "外伸高度", "管口附件", "管口载荷"]

    # 生成新的管口代号（在原代号后加序号）
    source_code_item = table_pipe.item(source_row, 1)
    if source_code_item:
        source_code = source_code_item.text().strip()
        # 生成新的管口代号
        new_code = generate_unique_pipe_code(table_pipe, source_code)

        # 复制数据到目标行
        for col_idx, field_name in enumerate(fields, start=1):  # 从第1列开始（跳过序号列）
            source_item = table_pipe.item(source_row, col_idx)
            if source_item:
                text_to_set = source_item.text()
                # 特殊规则：当“管口功能”为以下任一值时，复制后置空
                if col_idx == 2 and text_to_set.strip() in {"管程出口", "管程入口", "壳程出口", "壳程入口","排气口","排液口"}:
                    text_to_set = ""

                new_item = QTableWidgetItem(text_to_set)
                new_item.setTextAlignment(Qt.AlignCenter)

                # 如果是管口代号列，使用新生成的代号
                if col_idx == 1:  # 管口代号列
                    new_item.setText(new_code)
                    new_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)
                else:
                    # 其他列保持原数据（或置空），但设为可编辑
                    new_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)

                table_pipe.setItem(target_row, col_idx, new_item)

    # 为新行分配新的管口ID
    new_pipe_id = get_next_pipe_id_runtime(stats_widget, product_id)
    stats_widget.row_hidden_pipe_id[target_row] = new_pipe_id

    # 刷新序号
    stats_widget.refresh_pipe_table_sequence()

    # 调整列宽
    stats_widget.adjust_pipe_column_width()

    # 设置管口功能列只读状态
    set_pipe_function_column_readonly(stats_widget)

    # 提示复制成功
    stats_widget.line_tip.setText(f"已复制管口数据到新行，新管口代号：{new_code}")
    stats_widget.line_tip.setStyleSheet("color: blue;")

"""对复制的管口生成唯一的管口代号"""
def generate_unique_pipe_code(table, base_code: str) -> str:
    """
    基于基础管口代号生成唯一的管口代号：
    - 若末尾为数字：递增数字（如 N4 -> N5, g1 -> g2）
    - 若末尾为字母：递增最后一个字母（区分大小写，如 C -> D, INLET -> INLEU）
    - 若无法解析：保留原有“直接添加数字后缀”的逻辑
    """


    # 收集当前已存在的所有代码（排除最后空白行）
    existing_codes = set()
    for row in range(table.rowCount() - 1):
        item = table.item(row, 1)
        if item:
            existing_codes.add(item.text().strip())

    # 尝试解析末尾为一串字母或一串数字
    m = re.match(r'^(.*?)([A-Za-z]+|\d+)$', base_code)
    if m:
        prefix = m.group(1)
        tail = m.group(2)

        def next_letters(s: str) -> str:
            # 仅对最后一个字母做进位：Z/z 溢出时在末尾追加 'A'/'a'
            if not s:
                return 'A'
            last = s[-1]
            if 'A' <= last <= 'Y':
                return s[:-1] + chr(ord(last) + 1)
            if last == 'Z':
                return s + 'A'
            if 'a' <= last <= 'y':
                return s[:-1] + chr(ord(last) + 1)
            if last == 'z':
                return s + 'a'
            # 其它字符不应出现，兜底追加 'A'
            return s + 'A'

        # 生成候选并确保唯一
        if tail.isdigit():
            num = int(tail)
            candidate = f"{prefix}{num + 1}"
            while candidate in existing_codes:
                num += 1
                candidate = f"{prefix}{num + 1}"
            return candidate
        else:
            # 字母尾：对最后一个字母递增
            new_tail = next_letters(tail)
            candidate = f"{prefix}{new_tail}"
            # 若冲突，继续递增直至唯一
            counter_guard = 0
            while candidate in existing_codes and counter_guard < 1000:
                new_tail = next_letters(new_tail)
                candidate = f"{prefix}{new_tail}"
                counter_guard += 1
            return candidate

    # 无法解析时：直接添加数字后缀并去重
    seq = 1
    candidate = f"{base_code}{seq}"
    while candidate in existing_codes:
        seq += 1
        candidate = f"{base_code}{seq}"
    return candidate

"""初始默认管口不可删除"""
def set_default_pipe_cannot_be_deleted(stats_widget):
    """
    根据产品类型和型式，设置默认管口不可删除的管口功能集合
    同时设置 cannot_be_deleted 标志为 True（表示保护生效）

    :param stats_widget: 主窗口实例
    """
    # 初始化 cannot_be_deleted 标志为 True（表示保护生效）
    stats_widget.cannot_be_deleted = True

    # 直接获取产品类型和型式
    product_type = getattr(stats_widget, "current_product_type", "")
    product_version = getattr(stats_widget, "current_product_version", "")

    # 初始化不可删除的管口功能集合（注意：这里是管口功能，不是管口代号）
    readonly_pipe_functions = set()

    # 根据产品类型和型式确定不可删除的管口功能
    if product_type == "管壳式热交换器":
        if product_version in ["AEU", "BEU"]:
            readonly_pipe_functions = {"管程入口", "管程出口", "壳程入口", "壳程出口"}
        elif product_version in ["AES", "BES"]:
            readonly_pipe_functions = {"管程入口", "管程出口", "壳程入口", "壳程出口", "排液口", "排气口"}
        elif product_version in ["NEN"]:
            readonly_pipe_functions = {"管程入口", "管程出口", "壳程入口", "壳程出口", "排液口", "排气口"}
        elif product_version in ["BEM"]:
            readonly_pipe_functions = {"管程入口", "管程出口", "壳程入口", "壳程出口", "排液口", "排气口"}

    # 保存到 stats_widget 实例属性中
    stats_widget.readonly_pipe_functions = readonly_pipe_functions

