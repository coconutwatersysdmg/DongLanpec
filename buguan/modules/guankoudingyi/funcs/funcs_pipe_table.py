import pymysql
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTableWidgetItem, QMessageBox, QWidget, QComboBox, QLabel
from functools import partial
from PyQt5.QtWidgets import QAbstractItemView
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QTableWidgetSelectionRange

from modules.guankoudingyi.db_cnt import get_connection

db_config_1 = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '元件库'
}

db_config_2 = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '产品设计活动库'
}

"""数据读取，界面显示，数据存入产品设计活动表_管口表"""
def read_pipe_temp(stats_widget, belong_type, belong_version, product_id):
    """
    读取元件库的管口默认表，显示到界面 tableWidget_pipe，同时保存到产品设计活动表_管口表。
    首先，根据当前 产品ID 去产品设计活动表_管口表判断当前产品ID是否有对应的数据，若没有，则根据当前产品所属类型和所属型式去元件库
    中的管口默认表读取对应的默认数据，若还没有，则给出弹窗提示；
    自动防止重复插入（利用唯一索引产品ID+管口代号）
    """
    table_pipe = stats_widget.tableWidget_pipe  # 获取界面表格控件

    # 先连接
    conn_component = get_connection(**db_config_1)
    conn_product = get_connection(**db_config_2)
    cursor_component = conn_component.cursor()
    cursor_product = conn_product.cursor()
    try:
        sql1 = """
            SELECT COUNT(*) as count FROM 产品设计活动表_管口表 WHERE 产品ID = %s
        """
        cursor_product.execute(sql1, (product_id,))
        if cursor_product.fetchone()['count'] > 0:
            source_is_default = False   #使用已有数据
        else:
            source_is_default = True    #使用默认表中的数据

        # 优先查产品设计活动表
        sql_product = """
            SELECT 管口代号, 管口功能, 管口用途, 公称尺寸, 法兰标准, 压力等级, 法兰型式,
                   密封面型式, 焊端规格, 管口所属元件, 轴向定位基准, 轴向定位距离,
                   `轴向夹角（°）`, `周向方位（°）`, `偏心距`, 外伸高度, 管口附件, 管口载荷
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s
        """
        cursor_product.execute(sql_product, (product_id,))
        results = cursor_product.fetchall()
        source_is_default = False

        # 如果没有产品表数据，查询默认表
        if not results:
            sql_default = """
                SELECT 管口代号, 管口功能, 管口用途, 公称尺寸, 法兰标准, 压力等级, 法兰型式,
                       密封面型式, 焊端规格, 管口所属元件, 轴向定位基准, 轴向定位距离,
                       `轴向夹角（°）`, `周向方位（°）`, `偏心距`, 外伸高度, 管口附件, 管口载荷
                FROM 管口默认表
                WHERE 所属类型 = %s AND 所属型式 = %s
            """
            cursor_component.execute(sql_default, (belong_type, belong_version))
            results = cursor_component.fetchall()
            source_is_default = True

        # 若仍无结果，提示并清空表格
        if not results:
            QMessageBox.information(stats_widget, "查询结果", "未找到符合条件的数据")
            table_pipe.clearContents()
            table_pipe.setRowCount(0)
            return

        # 设置行数（数据行）
        table_pipe.setRowCount(len(results))

        # 显示到界面
        for row_index, row_data in enumerate(results):
            for col_index, cell in enumerate(row_data.values()):
                value = "" if cell is None or str(cell) == "None" else str(cell)
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                table_pipe.setItem(row_index, col_index + 1, item)

        # 序号的刷新
        stats_widget.refresh_pipe_table_sequence()
        # 检查是否需要添加新行
        check_last_row_and_add_new(stats_widget)
        # 列宽调整
        stats_widget.adjust_pipe_column_width()
        #管口功能列只读状态
        set_pipe_function_column_readonly(stats_widget)

        # 插入产品设计活动表_管口表（防止重复）
        if source_is_default:
            change_status = '未更改'
            sql_insert = """
                INSERT INTO 产品设计活动表_管口表 (
                    产品ID, 管口代号, 管口功能, 管口用途, 公称尺寸, 法兰标准, 压力等级,
                    法兰型式, 密封面型式, 焊端规格, 管口所属元件, 轴向定位基准, 轴向定位距离,
                    轴向夹角（°）, 周向方位（°）, 偏心距, 外伸高度, 管口附件, 管口载荷, 管口更改状态
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
            """

            params_list = []
            for row_data in results:
                params = (
                    product_id,
                    row_data["管口代号"], row_data["管口功能"], row_data["管口用途"],
                    row_data["公称尺寸"], row_data["法兰标准"], row_data["压力等级"],
                    row_data["法兰型式"], row_data["密封面型式"], row_data["焊端规格"],
                    row_data["管口所属元件"], row_data["轴向定位基准"], row_data["轴向定位距离"],
                    row_data["轴向夹角（°）"], row_data["周向方位（°）"], row_data["偏心距"],
                    row_data["外伸高度"], row_data["管口附件"], row_data["管口载荷"],
                    change_status
                )
                params_list.append(params)

            cursor_product.executemany(sql_insert, params_list)
            conn_product.commit()

    except pymysql.MySQLError as e:
        conn_product.rollback()
        QMessageBox.critical(stats_widget, "数据库操作失败", f"错误信息: {e}")

    finally:
        cursor_component.close()
        conn_component.close()
        cursor_product.close()
        conn_product.close()

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
            readonly_values = {"管程入口", "管程出口", "壳程入口", "壳程出口", "排液口", "排气口"}

    # 遍历表格行，同时设置管口功能列和管口所属元件列的只读状态
    func_col = 2  # 管口功能列
    belong_col = 10  # 管口所属元件列
    
    for row in range(table.rowCount() - 1):  # 排除最后空白行
        func_item = table.item(row, func_col)
        belong_item = table.item(row, belong_col)
        
        if not func_item:
            continue
            
        func_value = func_item.text().strip()
        is_readonly = func_value in readonly_values
        
        # 设置管口功能列的只读状态
        if is_readonly:
            func_item.setFlags(func_item.flags() & ~Qt.ItemIsEditable)
        else:
            func_item.setFlags(func_item.flags() | Qt.ItemIsEditable)
        
        # 设置管口所属元件列的只读状态（与管口功能列保持一致）
        if belong_item:
            if is_readonly:
                belong_item.setFlags(belong_item.flags() & ~Qt.ItemIsEditable)
            else:
                belong_item.setFlags(belong_item.flags() | Qt.ItemIsEditable)

"""管口删除"""
def delete_selected_pipe_rows(stats_widget, product_id):
    """
    删除选中行：从界面 tableWidget_pipe 和数据库中同步删除
    :param stats_widget: 主窗口实例
    :param product_id: 当前产品ID
    """
    table = stats_widget.tableWidget_pipe
    selected_rows = list(set(index.row() for index in table.selectedIndexes()))

    # 排除最后一行
    last_row_index = table.rowCount() - 1
    selected_rows = [r for r in selected_rows if r != last_row_index]

    if not selected_rows:
        stats_widget.line_tip.setText("最后一行不能删除，请选择其他要删除的管口行")
        stats_widget.line_tip.setStyleSheet("color: red;")
        return

    # 确认删除
    reply = QMessageBox.question(
        stats_widget, "确认删除", f"确定要删除选中的 {len(selected_rows)} 行管口数据吗？",
        QMessageBox.Yes | QMessageBox.No, QMessageBox.No
    )
    if reply != QMessageBox.Yes:
        return

    # 删除数据库中的记录
    try:
        # 连接数据库
        conn = get_connection(**db_config_2)
        cursor = conn.cursor()

    except Exception as e:
        QMessageBox.critical(stats_widget, "数据库错误", f"连接数据库失败：{e}")
        return

    try:
        for row in sorted(selected_rows, reverse=True):
            port_code_item = table.item(row, 1)  # 第1列是"管口代号"
            if port_code_item:
                port_code = port_code_item.text()
                # 从数据库删除管口表中的记录
                cursor.execute(
                    "DELETE FROM 产品设计活动表_管口表 WHERE 产品ID = %s AND 管口代号 = %s",
                    (product_id, port_code)
                )
                # 从界面删除
                table.removeRow(row)

        conn.commit()
        print("已从界面和数据库删除选中的管口数据")
    except Exception as e:
        conn.rollback()
        QMessageBox.critical(stats_widget, "删除失败", f"数据库操作失败：{e}")
    finally:
        cursor.close()
        conn.close()
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
                table.setItem(new_row, col, item)
            
            # 添加新行后自动调整列宽
            stats_widget.adjust_pipe_column_width()
        finally:
            # === 恢复信号连接 ===
            table.blockSignals(False)
        # ✅ 新增：刷新序号
        stats_widget.refresh_pipe_table_sequence()

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

