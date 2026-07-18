from PyQt5.QtWidgets import QMenu, QAction, QTableWidgetItem, QLabel
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCursor, QColor
import re
from fractions import Fraction

from modules.guankoudingyi.funcs.funcs_pipe_table import (
    set_pipe_function_column_readonly,
    set_pipe_load_column_readonly,
    get_pipe_sort_string_columns,
    get_pipe_sort_numeric_columns,
    get_pipe_position_hide_columns,
    sync_display_order_from_ui,
    ensure_hidden_maps,
    check_last_row_and_add_new,
    control_last_row_editable_state,
)


# from modules.guankoudingyi.funcs.funcs_pipe_table import set_pipe_function_column_readonly, \
#     lock_belong_if_function_filled


# 定义表头点击事件处理函数
def setup_header_click_sort(stats_widget):
    """
    设置表头点击排序功能
    :param stats_widget: 主窗口实例
    """
    # 为冻结表头添加点击事件
    stats_widget.tableWidget_pipe_title.cellClicked.connect(
        lambda row, col: show_head_menu(stats_widget, row, col)
    )

# 显示排序菜单
def show_head_menu(stats_widget, row, col):
    """
    显示排序菜单
    :param stats_widget: 主窗口实例
    :param row: 点击的行
    :param col: 点击的列
    """
    if row == 0:
        if row == 0 and col == 5:  # 第0行第5列是“法兰规格”合并列
            menu = QMenu(stats_widget)
            menu.setStyleSheet("""
                QMenu {
                    background-color: white;
                    border: 1px solid #CCCCCC;
                }
                QMenu::item {
                    padding: 6px 40px 6px 20px;
                    border: 1px solid transparent;
                }
                QMenu::item:selected {
                    background-color: #2563EB;
                    color: white;
                }
            """)

            # 添加隐藏“法兰规格”子列组的选项
            hide_group_action = QAction("隐藏该列", stats_widget)

            def hide_flange_group():
                for cc in [5, 6, 7, 8, 9]:  # 法兰标准、压力等级、法兰型式、密封面型式、焊端规格
                    hide_pipe_column(stats_widget, cc)

            hide_group_action.triggered.connect(hide_flange_group)
            menu.addAction(hide_group_action)

            # 显示“显示隐藏列”子菜单（复用已有逻辑）
            hidden_columns = getattr(stats_widget, 'hidden_pipe_columns', set())
            if hidden_columns:
                show_menu = menu.addMenu("显示隐藏列")

                show_all_action = QAction("显示所有隐藏列", stats_widget)

                def show_all_columns():
                    for cc in list(hidden_columns):
                        show_pipe_column(stats_widget, cc)

                show_all_action.triggered.connect(show_all_columns)
                show_menu.addAction(show_all_action)

                def get_fake_header_label(col):
                    title_table = stats_widget.tableWidget_pipe_title
                    for row in [1, 0]:
                        item = title_table.item(row, col)
                        if item and item.text().strip():
                            return item.text().strip()
                        widget = title_table.cellWidget(row, col)
                        if widget:
                            labels = widget.findChildren(QLabel)
                            for label in labels:
                                text = label.text().strip()
                                if text:
                                    return text
                    return f"第{col + 1}列"

                for c in sorted(hidden_columns):
                    col_name = get_fake_header_label(c)
                    action = QAction(f"显示“{col_name}”列", stats_widget)
                    action.triggered.connect(lambda _, cc=c: show_pipe_column(stats_widget, cc))
                    show_menu.addAction(action)

            menu.exec_(QCursor.pos())
            return  # ⚠️防止继续执行后续默认逻辑

        elif row == 0 and col == 10:  # ✅“管口位置”合并表头列
            menu = QMenu(stats_widget)
            menu.setStyleSheet("""
                QMenu {
                    background-color: white;
                    border: 1px solid #CCCCCC;
                }
                QMenu::item {
                    padding: 6px 40px 6px 20px;
                    border: 1px solid transparent;
                }
                QMenu::item:selected {
                    background-color: #2563EB;
                    color: white;
                }
            """)

            # 隐藏“管口位置”子列的功能
            hide_group_action = QAction("隐藏该列", stats_widget)
            def hide_pipepos_group():
                is_container = getattr(stats_widget, 'is_container_product', False)
                for cc in get_pipe_position_hide_columns(is_container):
                    hide_pipe_column(stats_widget, cc)
            hide_group_action.triggered.connect(hide_pipepos_group)
            menu.addAction(hide_group_action)

            # 显示隐藏列逻辑复用
            hidden_columns = getattr(stats_widget, 'hidden_pipe_columns', set())
            if hidden_columns:
                show_menu = menu.addMenu("显示隐藏列")
                show_all_action = QAction("显示所有隐藏列", stats_widget)
                show_all_action.triggered.connect(lambda: [show_pipe_column(stats_widget, c) for c in list(hidden_columns)])
                show_menu.addAction(show_all_action)

                def get_fake_header_label(col):
                    title_table = stats_widget.tableWidget_pipe_title
                    for row in [1, 0]:
                        item = title_table.item(row, col)
                        if item and item.text().strip():
                            return item.text().strip()
                        widget = title_table.cellWidget(row, col)
                        if widget:
                            labels = widget.findChildren(QLabel)
                            for label in labels:
                                text = label.text().strip()
                                if text:
                                    return text
                    return f"第{col+1}列"

                for c in sorted(hidden_columns):
                    col_name = get_fake_header_label(c)
                    action = QAction(f"显示“{col_name}”列", stats_widget)
                    action.triggered.connect(lambda _, cc=c: show_pipe_column(stats_widget, cc))
                    show_menu.addAction(action)

            menu.exec_(QCursor.pos())
            return  # 防止继续执行默认排序逻辑

    elif row != 1:
        # 响应第1行，其他行不处理
        return

    # ✅ 禁用“序号”列的排序菜单
    if col == 0:
        return

    # 创建右键菜单
    menu = QMenu(stats_widget)
    # 设置菜单样式
    menu.setStyleSheet("""
        QMenu {
            background-color: white;
            border: 1px solid #CCCCCC;
        }
        QMenu::item {
            padding: 6px 40px 6px 20px;
            border: 1px solid transparent;
        }
        QMenu::item:selected {
            background-color: #2563EB;
            color: white;
        }
    """)
    #=============排序功能=================
    # 添加排序选项
    ascending_action = QAction("升序", stats_widget)
    descending_action = QAction("降序", stats_widget)
    
    # 设置排序操作
    ascending_action.triggered.connect(lambda: sort_table_column(stats_widget, col, True))
    descending_action.triggered.connect(lambda: sort_table_column(stats_widget, col, False))
    
    # 添加到菜单
    menu.addAction(ascending_action)
    menu.addAction(descending_action)

    #=================隐藏列====================
    if col >= 4:
        hide_action = QAction("隐藏该列", stats_widget)
        hide_action.triggered.connect(lambda: hide_pipe_column(stats_widget, col))
        menu.addAction(hide_action)

    # 如果当前列已隐藏，则显示“取消隐藏”菜单（也可扩展成子菜单）
    hidden_columns = getattr(stats_widget, 'hidden_pipe_columns', set())
    if hidden_columns:
        show_menu = menu.addMenu("显示隐藏列")
        # ✅添加“一键显示所有列”选项
        show_all_action = QAction("显示所有隐藏列", stats_widget)
        def show_all_columns():
            for cc in list(hidden_columns):  # 必须转成list避免set大小变化错误
                show_pipe_column(stats_widget, cc)
        show_all_action.triggered.connect(show_all_columns)
        show_menu.addAction(show_all_action)

        # 获取表头文本的函数
        def get_fake_header_label(col):
            """
            获取自定义表头的列名，优先使用 QTableWidgetItem 的文本，
            如果是嵌套控件结构则尝试查找 QLabel 内容
            """
            title_table = stats_widget.tableWidget_pipe_title

            # 先优先查看 row=1（因为大部分二级表头都在这一行）
            for row in [1, 0]:  # 先看row=1，再看row=0
                item = title_table.item(row, col)
                if item and item.text().strip():
                    return item.text().strip()

                widget = title_table.cellWidget(row, col)
                if widget:
                    labels = widget.findChildren(QLabel)
                    for label in labels:
                        text = label.text().strip()
                        if text:
                            return text

            return f"第{col + 1}列"

        # 分别添加每一列的显示动作
        for c in sorted(hidden_columns):
            col_name = get_fake_header_label(c)
            action = QAction(f"显示“{col_name}”列", stats_widget)
            action.triggered.connect(lambda _, cc=c: show_pipe_column(stats_widget, cc))
            show_menu.addAction(action)

    # 显示菜单在鼠标位置
    menu.exec_(QCursor.pos())

# 解析NPS字符串
def parse_nps_value(val):
    """
    解析 NPS 字符串，将 '1-1/4' 解释为 1 - 1/4，而不是混合分数。
    支持 '3/4'、'1'、'1-1/4' 等。
    """
    val = val.strip()
    if not val:
        return 0.0

    try:
        # 如果是减法表达式，如 '1-1/4'
        if '-' in val and re.match(r'^\d+\s*-\s*\d+/\d+$', val):
            parts = re.split(r'\s*-\s*', val)
            base = float(parts[0])
            sub = float(Fraction(parts[1]))
            return base - sub
        # 是普通分数，如 '3/4'
        elif '/' in val and re.match(r'^\d+/\d+$', val):
            return float(Fraction(val))
        # 是普通整数或小数
        else:
            return float(val)
    except Exception:
        return 0.0


def _mixed_cell_sort_key(val):
    """
    混合单元格排序键：空白 / 数值 / 文本 使用统一元组，避免 str 与 float 比较触发 TypeError。
    升序时：数值 < 文本 < 空白。
    """
    s = (val or "").strip() if val is not None else ""
    if not s:
        return (2, 0.0, "")
    try:
        return (0, float(s), s)
    except ValueError:
        return (1, 0.0, s.lower())


# 对指定列进行特殊排序，因为有的列同时存在数字和字符串，需进行特殊处理
def sort_table_column(stats_widget, col, ascending=True):
    """
    对指定列进行排序（增强版，支持浮点数排序）
    """
    table = stats_widget.tableWidget_pipe
    row_count = table.rowCount()
    ensure_hidden_maps(stats_widget)

    data = []
    for row in range(row_count):
        if row == row_count - 1:
            item = table.item(row, 1)
            if item is None or not item.text().strip():
                continue

        row_data = {}
        row_data["_pipe_id"] = stats_widget.row_hidden_pipe_id.get(row)
        for c in range(table.columnCount()):
            item = table.item(row, c)
            row_data[c] = item.text().strip() if item else ""
        data.append(row_data)

    is_container = getattr(stats_widget, 'is_container_product', False)
    string_cols = get_pipe_sort_string_columns(is_container)
    numeric_cols = get_pipe_sort_numeric_columns(is_container)

    if col in string_cols:
        data.sort(key=lambda x: x.get(col, ""), reverse=not ascending)
    elif col in numeric_cols:
        data.sort(key=lambda x: parse_nps_value(x.get(col, "")), reverse=not ascending)
    else:
        data.sort(key=lambda x: _mixed_cell_sort_key(x.get(col, "")), reverse=not ascending)

    table.blockSignals(True)
    try:
        stats_widget.row_hidden_pipe_id.clear()
        table.setRowCount(len(data))
        for row, row_data in enumerate(data):
            hid = row_data.pop("_pipe_id", None)
            if hid is not None:
                stats_widget.row_hidden_pipe_id[row] = hid
            for c, value in row_data.items():
                if c != 0:
                    item = QTableWidgetItem(value)
                    item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(row, c, item)
        stats_widget.refresh_pipe_table_sequence()
        sync_display_order_from_ui(stats_widget)
        check_last_row_and_add_new(stats_widget)
        control_last_row_editable_state(stats_widget, enable_editing=False)
    finally:
        table.blockSignals(False)

    set_pipe_function_column_readonly(stats_widget)
    set_pipe_load_column_readonly(stats_widget)


# 隐藏列功能
def hide_pipe_column(stats_widget, col):
    """
    隐藏主表格和冻结表头中的指定列
    """
    stats_widget.tableWidget_pipe.setColumnHidden(col, True)
    stats_widget.tableWidget_pipe_title.setColumnHidden(col, True)

    # 记录隐藏列
    if not hasattr(stats_widget, 'hidden_pipe_columns'):
        stats_widget.hidden_pipe_columns = set()
    stats_widget.hidden_pipe_columns.add(col)

# 显示隐藏列
def show_pipe_column(stats_widget, col):
    """
    显示指定列
    """
    stats_widget.tableWidget_pipe.setColumnHidden(col, False)
    stats_widget.tableWidget_pipe_title.setColumnHidden(col, False)

    if hasattr(stats_widget, 'hidden_pipe_columns'):
        stats_widget.hidden_pipe_columns.discard(col)