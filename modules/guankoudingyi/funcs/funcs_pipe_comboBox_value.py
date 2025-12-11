from PyQt5.QtWidgets import (
    QMessageBox, QComboBox, QTableWidgetItem, 
    QStyledItemDelegate, QStyleOptionComboBox, QStyle,
    QApplication, QLineEdit
)
from PyQt5.QtCore import Qt, QEvent, QRect, QObject
from modules.guankoudingyi.db_cnt import get_connection, db_config_1, db_config_2
import pymysql.cursors
import traceback

from modules.guankoudingyi.obtain_product_type_version import get_product_type_and_version
from modules.guankoudingyi.funcs.pipe_get_units_types import get_unit_types_from_db, get_current_unit_types_from_ui


# 补丁：禁止滚轮改值的下拉框
class NoWheelComboBox(QComboBox):
    def wheelEvent(self, e):
        # 忽略所有滚轮事件（不展开时不改值；展开后滚动由下拉视图接管，仍可滚动列表）
        e.ignore()

class ComboBoxDelegate(QStyledItemDelegate):
    """自定义的下拉框代理类（支持第一次按键覆盖整体内容）"""

    def __init__(self, parent=None, editable=False, overwrite_on_first_key=False):
        """
        :param parent: 父对象
        :param editable: 是否可编辑
        :param overwrite_on_first_key: 是否在第一次按键时覆盖整个内容
        """
        super().__init__(parent)
        self.items = []
        self.editable = editable # 新增：保存editable参数
        self.overwrite_on_first_key = overwrite_on_first_key
        self.first_key_pressed = False  # 标记是否是第一次按键
        self.old_text = ""  # 保存旧值
        self.bulk_select_callback = None  # 批量选择回调函数
        self.disable_wheel_scroll = False  # 是否禁用滚轮滚动


    def setItems(self, items):
        """设置下拉框的选项"""
        self.items = items

    def createEditor(self, parent, option, index):
        """创建编辑器（下拉框）"""
        # editor = QComboBox(parent)
        editor = NoWheelComboBox(parent)
        editor.addItems(self.items)
        editor.setCurrentText("")
        editor.setEditable(self.editable)  # 根据参数决定是否可编辑
        # 增加下拉框选项之间的间距
        editor.view().setSpacing(5)  # 设置选项之间的间距为5像素

        # 如果是可编辑的，为lineEdit安装事件过滤器
        if self.editable and self.overwrite_on_first_key:
            line_edit = editor.lineEdit()
            if line_edit:
                line_edit.installEventFilter(self)
                self.first_key_pressed = False  # 重置标志
                self.old_text = line_edit.text()  # 保存旧值

        # 连接批量选择回调（如果有的话）
        if self.bulk_select_callback:
            editor.activated[str].connect(self.bulk_select_callback)

        # 为编辑器安装事件过滤器以处理滚轮事件
        editor.installEventFilter(self)

        return editor

    def setEditorData(self, editor, index):
        """设置编辑器的数据"""
        value = index.model().data(index, Qt.EditRole) or ""

        # 修复多选时值改变的bug：区分可编辑和不可编辑下拉框的处理方式
        current_items = [editor.itemText(i) for i in range(editor.count())]

        if not self.bulk_select_callback:  # 非批量模式
            if value and value not in current_items:
                if self.editable:
                    # 可编辑模式：直接设置文本，不改变下拉选项
                    editor.setCurrentText(value)
                else:
                    # 不可编辑模式：临时添加原值但隐藏它，保持下拉选项不变
                    # print(f"[DEBUG] 非批量模式下不可编辑下拉框，原始值'{value}'不在选项中，临时显示原值")
                    editor.addItem(value)
                    # 隐藏最后一个项目（原始值），使其不在下拉选项中显示
                    view = editor.view()
                    if view:
                        last_row = editor.count() - 1
                        view.setRowHidden(last_row, True)
                    editor.setCurrentText(value)
            else:
                editor.setCurrentText(value)
        else:  # 批量模式
            if value and value not in current_items:
                if self.editable:
                    # 可编辑下拉框：直接设置文本显示原值，不改变下拉选项
                    # print(f"[DEBUG] 批量模式下可编辑下拉框，直接显示原值'{value}'，不改变选项")
                    editor.setCurrentText(value)
                else:
                    # 不可编辑下拉框：临时显示原值，但下拉选项保持交集
                    # print(f"[DEBUG] 批量模式下不可编辑下拉框，原始值'{value}'不在交集中，临时显示原值")
                    # 临时添加原始值到列表末尾
                    editor.addItem(value)
                    # 隐藏最后一个项目（原始值），使其不在下拉选项中显示
                    view = editor.view()
                    if view:
                        last_row = editor.count() - 1
                        view.setRowHidden(last_row, True)
                    editor.setCurrentText(value)
            else:
                editor.setCurrentText(value)

        # 如果是可编辑的且需要覆盖，全选文本
        if self.editable and self.overwrite_on_first_key:
            line_edit = editor.lineEdit()
            if line_edit:
                line_edit.selectAll()

    def setModelData(self, editor, model, index):
        """将编辑器的数据设置到模型中"""
        value = editor.currentText()
        model.setData(index, value, Qt.EditRole)

        # 重置状态
        self.first_key_pressed = False

    def eventFilter(self, editor, event):
        """事件过滤器，用于实现第一次按键覆盖整体内容和处理滚轮事件"""

        # 处理滚轮事件：在批量模式下禁用滚轮滚动
        if event.type() == QEvent.Wheel and self.disable_wheel_scroll:
            print(f"[DEBUG] 批量模式下阻止滚轮事件")
            return True  # 阻止滚轮事件

        # 只处理QLineEdit的键盘事件
        if isinstance(editor, QLineEdit) and event.type() == QEvent.KeyPress:
            # 处理可打印字符
            if not event.text().isEmpty() and event.text().isprintable():
                # 如果是第一次按键
                if not self.first_key_pressed:
                    # 保存当前文本作为旧值（可选）
                    self.old_text = editor.text()

                    # 清除内容并设置新字符
                    editor.setText(event.text())

                    # 移动光标到末尾
                    editor.setCursorPosition(len(event.text()))

                    # 标记已处理第一次按键
                    self.first_key_pressed = True
                    return True  # 事件已处理

                # 后续按键正常处理
                return False

            # 处理回车键（可选）
            elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
                # 重置标志，以便下次编辑时重新检测第一次按键
                self.first_key_pressed = False
                return False

        # 处理焦点离开事件
        elif event.type() == QEvent.FocusOut:
            self.first_key_pressed = False

        return super().eventFilter(editor, event)

"""初始化所有管口表的下拉框代理"""
def initialize_pipe_combobox_delegates(stats_widget):
    """
    初始化所有管口表格下拉框代理，只需在初始化表格时调用一次。
    :param stats_widget: 主窗口实例
    """
    table = stats_widget.tableWidget_pipe

    # 初始化缓存字典
    stats_widget.pipe_column_delegates = {}

    # 静态列：固定选项
    static_columns = {
        12: ["程序推荐", "居中"],  # 轴向定位距离(✅ 可编辑下拉)
        16: ["程序推荐"],         # 外伸高度(✅ 可编辑下拉)
    }
    for col, options in static_columns.items():
        # ✅ 关键修改：启用第一次按键覆盖功能
        delegate = ComboBoxDelegate(table, editable=True, overwrite_on_first_key=True)
        delegate.setItems(options)
        table.setItemDelegateForColumn(col, delegate)
        stats_widget.pipe_column_delegates[col] = delegate

    # 动态列：初始化空代理，后续在点击时更新选项
    dynamic_columns = [4, 5, 6, 7, 8, 9, 10, 11]
    for col in dynamic_columns:
        # 🚩 关键修改：列9初始化为不可编辑
        editable = False
        delegate = ComboBoxDelegate(table, editable=editable)
        delegate.setItems([])
        table.setItemDelegateForColumn(col, delegate)
        stats_widget.pipe_column_delegates[col] = delegate

"""获取法兰标准的默认值和压力等级的默认值"""
def get_standard_flange_pressure_level_default_value(product_id, stats_widget=None):
    """
    获取法兰标准的默认值和压力等级的默认值：
    - 优先从界面组件获取公称压力类型，如果获取不到则从数据库获取
    - 根据公称压力类型返回：
      - 默认法兰标准和默认压力等级（不用于最后一行）
    :param product_id: 产品ID
    :param stats_widget: Stats类实例，用于从界面获取单位类型
    :return: (pressure_type: str, default_standard: str, default_level: str, standards_list: list)
    """
    pressure_type = 'Class'  # 默认值
    try:
        # 优先从界面组件获取公称压力类型
        if stats_widget:
            current_unit_types = get_current_unit_types_from_ui(stats_widget)
            pressure_type = current_unit_types.get("公称压力类型", "Class")
        else:
            # 兼容性处理：如果没有传入stats_widget，仍然从数据库读取
            unit_types = get_unit_types_from_db(product_id)
            if unit_types and unit_types.get("公称压力类型"):
                pressure_type = unit_types["公称压力类型"]
    except Exception as e:
        QMessageBox.warning(None, "获取单位类型失败", f"无法获取公称压力类型: {str(e)}")
        return pressure_type, "", "", []

    # 设置默认值
    if pressure_type == "Class":
        default_standard = "HG/T 20615-2009"
        default_level = "150"
    else:  # PN
        default_standard = "HG/T 20592-2009"
        default_level = "10"

    return pressure_type, default_standard, default_level

"""六列之间互相限制，互相筛选"""
def get_filtered_pipe_options(field, filters, unit_map, pressure_type = None):
    """
    查询管口关系对应表，根据其他字段值过滤出指定字段候选值
    注意：不支持"公称尺寸"字段的筛选，公称尺寸独立于其他字段
    :param field: 当前目标字段（如"压力等级"、"法兰型式"等，不包括"公称尺寸"）
    :param filters: 其他字段的已填写值，如 {"密封面型式": "RF", "法兰型式": "SO"}
    :param unit_map: 单位映射，如 {"压力等级": "Class"}
    :return: 候选值列表
    """
    try:
        conn = get_connection(**db_config_1)
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 新的字段映射（移除公称尺寸的筛选）
        column_map = {
            "压力等级": "公称压力",  # 统一使用"公称压力"字段名
            "法兰型式": "法兰型式",
            "密封面型式": "密封面型式",
            "法兰标准": "法兰标准",
            "公称压力类型": "公称压力类型"
        }

        # 构建 WHERE 子句
        where_clauses = []
        params = []

        # 在筛选条件中加入“公称压力类型”
        where_clauses.append("公称压力类型 = %s")
        params.append(pressure_type)

        for key, value in filters.items():
            if value and value != "None":
                col = column_map.get(key)
                if col:
                    where_clauses.append(f"`{col}` = %s")
                    params.append(value)

        # 查询字段名
        target_column = column_map.get(field)
        if not target_column:
            # print(f"[WARNING] 未找到字段 {field} 的映射")  #调试信息
            return []

        sql = f"SELECT DISTINCT `{target_column}` FROM 管口关系对应表"
        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)

        cursor.execute(sql, params)
        results = cursor.fetchall()
        
        # 提取结果
        options = []
        for row in results:
            value = row[target_column]  # 使用列名作为键来获取值
            if value and str(value).strip():  # 只添加非空值
                options.append(str(value))

        return options

    except Exception as e:
        QMessageBox.warning(None, "错误", f"获取管口选项失败: {str(e)}")
        return []
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

"""根据产品ID从产品设计活动库中获取焊端规格类型"""
def get_welding_type_from_design_db(product_id):
    """
    根据产品ID从产品设计活动库中获取焊端规格类型
    :param product_id: 产品ID
    :return: 返回焊端规格类型字符串（如 'Sch'、'mm'），默认返回 'Sch'
    """
    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config_2)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT 焊端规格类型 
            FROM 产品设计活动表_管口类型选择表
            WHERE 产品ID = %s
        """, (product_id,))
        result = cursor.fetchone()
        return result['焊端规格类型'] if result and result.get('焊端规格类型') else 'Sch'
    except Exception as e:
        QMessageBox.warning(None, "数据库错误", f"获取焊端规格类型失败: {str(e)}")
        return 'Sch'
    finally:
        cursor and cursor.close()
        conn and conn.close()

"""获取焊端规格类型是Sch时，该列下拉框所应该显示的内容"""
def get_weld_end_spec_sch_options():
    """
    从元件库的焊端规格类型表中获取"焊端规格类型Sch"列所有非空值
    """
    try:
        conn = get_connection(**db_config_1)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("SELECT DISTINCT 焊端规格类型Sch FROM 焊端规格类型表")
        results = cursor.fetchall()
        options = [str(row["焊端规格类型Sch"]) for row in results if row["焊端规格类型Sch"]]
        return options
    except Exception as e:
        QMessageBox.warning(None, "错误", f"获取焊端规格类型Sch失败: {str(e)}")
        return []
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

"""获取公称尺寸列的下拉框内容"""
def get_nominal_size_options(product_id, stats_widget=None):
    """
    根据界面选择或产品ID获取公称尺寸类型（DN或NPS），然后从元件库的公称尺寸表中获取对应列的内容
    :param product_id: 产品ID
    :param stats_widget: Stats类实例，用于从界面获取单位类型
    :return: 公称尺寸选项列表
    """
    conn = None
    cursor = None
    try:
        # 优先从界面组件获取公称尺寸类型，如果获取不到则从数据库获取
        if stats_widget:
            current_unit_types = get_current_unit_types_from_ui(stats_widget)
            size_type = current_unit_types.get("公称尺寸类型", "DN")
        else:
            # 兼容性处理：如果没有传入stats_widget，仍然从数据库读取
            unit_types = get_unit_types_from_db(product_id)
            size_type = unit_types.get("公称尺寸类型", "DN") if unit_types else "DN"
        
        conn = get_connection(**db_config_1)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # 根据类型选择对应的列
        column_name = size_type  # "DN" 或 "NPS"
        
        cursor.execute(f"""
            SELECT DISTINCT `{column_name}` 
            FROM 公称尺寸表 
            WHERE `{column_name}` IS NOT NULL 
            ORDER BY CAST(`{column_name}` AS UNSIGNED) ASC, `{column_name}` ASC
        """)
        
        results = cursor.fetchall()
        options = []
        
        for row in results:
            value = row[column_name]
            if value and str(value).strip():  # 只添加非空值
                options.append(str(value))
        
        return options
        
    except Exception as e:
        QMessageBox.warning(None, "错误", f"获取公称尺寸选项失败: {str(e)}")
        return []
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

"""更新表格中所有行的公称尺寸下拉框选项"""
def update_nominal_size_delegate_options(stats_widget):
    """
    当表头的公称尺寸类型发生变化时，更新表格中第4列（公称尺寸列）的下拉框选项
    :param stats_widget: 主窗口实例
    """
    try:
        # 获取新的公称尺寸选项
        size_options = get_nominal_size_options(stats_widget.product_id, stats_widget)
        
        # 更新第4列的代理选项
        if hasattr(stats_widget, 'pipe_column_delegates') and 4 in stats_widget.pipe_column_delegates:
            delegate = stats_widget.pipe_column_delegates[4]
            delegate.setItems(size_options if size_options else ["None"])
            
            # 重新设置列代理以确保更新生效
            table = stats_widget.tableWidget_pipe
            table.setItemDelegateForColumn(4, delegate)
            
    except Exception as e:
        QMessageBox.warning(stats_widget, "错误", f"更新公称尺寸下拉框选项失败: {str(e)}")

"""获取管口所属元件的下拉框内容"""
def get_belong_options(product_id):
    """根据产品类型和产品型式从元件库中的管口所属元件轴向定位基准表中获取管口所属元件"""
     # 获取产品类型和型式
    product_type, product_version = get_product_type_and_version(product_id)
    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config_1)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT DISTINCT 管口所属元件
            FROM 管口所属轴向定位基准表
            WHERE 产品类型 = %s AND 产品型式 = %s
        """, (product_type, product_version))
        return [row["管口所属元件"] for row in cursor.fetchall() if row["管口所属元件"]]
    except Exception as e:
        raise RuntimeError(f"获取管口所属元件失败：{str(e)}")
    finally:
        cursor and cursor.close()
        conn and conn.close()

"""获取轴向定位基准的下拉框内容"""
def get_axial_position_base_options(product_id, pipe_belong=None):
    """
    根据产品类型、产品型式、管口所属元件获取“轴向定位基准”下拉框选项
    :param product_id: 产品ID
    :param pipe_belong: 管口所属元件，可为空
    :return: 轴向定位基准选项列表
    """
    try:
        # 获取产品类型和型式
        product_type, product_version = get_product_type_and_version(product_id)

        conn = get_connection(**db_config_1)
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        sql = """
            SELECT DISTINCT 轴向定位基准 
            FROM 管口所属轴向定位基准表 
            WHERE 产品类型 = %s AND 产品型式 = %s
        """
        params = [product_type, product_version]

        #只有在用户已填写“管口所属元件”时，才把它作为额外的查询条件加到 SQL 语句中
        if pipe_belong:
            sql += " AND 管口所属元件 = %s"
            params.append(pipe_belong)

        cursor.execute(sql, params)
        return [row["轴向定位基准"] for row in cursor.fetchall() if row["轴向定位基准"]]

    except Exception as e:
        QMessageBox.warning(None, "数据库错误", f"获取轴向定位基准失败: {str(e)}")
        return []
    finally:
        cursor and cursor.close()
        conn and conn.close()

"""处理单击出现下拉框的列"""
def handle_pipe_cell_click(stats_widget, row, column):
    # 用于记录当前用户点击的单元格
    stats_widget.current_editing_cell = (row, column)

    table = stats_widget.tableWidget_pipe

    is_last_row = (row == table.rowCount() - 1)
    pipe_code_item = table.item(row, 1)
    has_pipe_code = pipe_code_item.text().strip() != "" if pipe_code_item else False
    if is_last_row and not has_pipe_code:
        return

    # ✅ 新增逻辑：单击即进入可编辑下拉
    if column in [12, 16]:
        delegate = stats_widget.pipe_column_delegates[column]
        table.editItem(table.item(row, column))
        return

    # 焊端规格特殊逻辑
    if column == 9:
        # 从界面组件获取焊端规格类型，而不是从数据库
        current_unit_types = get_current_unit_types_from_ui(stats_widget)
        welding_type = current_unit_types.get("焊端规格类型", "Sch")  # 默认为Sch
        # delegate = stats_widget.pipe_column_delegates[column]
        if welding_type == "Sch":
            # Sch类型：使用不可编辑下拉框
            options = get_weld_end_spec_sch_options()
            delegate = ComboBoxDelegate(table, editable=False)
            delegate.setItems(options)
            table.setItemDelegateForColumn(column, delegate)
            stats_widget.pipe_column_delegates[column] = delegate
            table.editItem(table.item(row, column))
        else:  # 非Sch类型
            # 使用可编辑下拉框，并启用第一次按键覆盖功能
            delegate = ComboBoxDelegate(table, editable=True, overwrite_on_first_key=True)
            delegate.setItems(["程序推荐"])
            table.setItemDelegateForColumn(column, delegate)
            stats_widget.pipe_column_delegates[column] = delegate

            # 初始化空单元格为"程序推荐"
            for r in range(table.rowCount() - 1):
                item = table.item(r, column)
                # ✅ 只有当当前单元格为空时才设置默认
                if not item or not item.text().strip():
                    new_item = QTableWidgetItem("程序推荐")
                    new_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)
                    new_item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(r, column, new_item)
            table.editItem(table.item(row, column))
        return

    # 管口所属元件逻辑
    if column == 10:
        belong_options = get_belong_options(stats_widget.product_id)
        delegate = stats_widget.pipe_column_delegates[column]
        delegate.setItems(belong_options)
        table.editItem(table.item(row, column))
        return

    # 轴向定位基准逻辑
    if column == 11:
        belong_item = table.item(row, 10)
        pipe_belong = belong_item.text().strip() if belong_item else None
        base_options = get_axial_position_base_options(stats_widget.product_id, pipe_belong)
        delegate = stats_widget.pipe_column_delegates[column]
        delegate.setItems(base_options)
        table.editItem(table.item(row, column))
        return

    # 公称尺寸列逻辑（第4列）
    if column == 4:
        # 检查是否处于批量赋值模式
        is_bulk_mode = (hasattr(stats_widget, 'bulk_assign_target_column') and
                        stats_widget.bulk_assign_target_column == column and
                        hasattr(stats_widget, 'bulk_assign_rows') and
                        len(stats_widget.bulk_assign_rows) > 1)

        if is_bulk_mode:
            # 批量模式：使用交集选项（对于公称尺寸，返回统一选项）
            size_options = compute_intersection_options(stats_widget, column, stats_widget.bulk_assign_rows)
            print(f"[DEBUG] 批量模式下获取公称尺寸选项，列{column}：{size_options}")

            # 设置批量赋值回调
            def bulk_assign_callback(value):
                apply_bulk_assign_value_immediate(stats_widget, column, stats_widget.bulk_assign_rows, value)

            delegate = stats_widget.pipe_column_delegates[column]
            delegate.bulk_select_callback = bulk_assign_callback
            delegate.disable_wheel_scroll = True  # 批量模式下禁用滚轮
            delegate.setItems(size_options if size_options else ["None"])
            table.editItem(table.item(row, column))

        else:
            # 单选模式：获取公称尺寸选项
            size_options = get_nominal_size_options(stats_widget.product_id, stats_widget)
            print(f"[DEBUG] 单选模式下获取公称尺寸选项，列{column}：{size_options}")

            delegate = stats_widget.pipe_column_delegates[column]
            delegate.bulk_select_callback = None  # 清除批量回调
            delegate.disable_wheel_scroll = False  # 单选模式下允许滚轮
            delegate.setItems(size_options if size_options else ["None"])
            table.editItem(table.item(row, column))

        return

    # 其它 5/6/7/8 列逻辑（移除公称尺寸的筛选）
    target_fields = {5: "法兰标准", 6: "压力等级", 7: "法兰型式", 8: "密封面型式"}
    current_field = target_fields.get(column)
    
    if not current_field:
        return

    # 检查是否处于批量赋值模式（多选且有批量赋值状态）
    is_bulk_mode = (hasattr(stats_widget, 'bulk_assign_target_column') and
                    stats_widget.bulk_assign_target_column == column and
                    hasattr(stats_widget, 'bulk_assign_rows') and
                    len(stats_widget.bulk_assign_rows) > 1)

    if is_bulk_mode:
        # 批量模式：使用交集选项
        options = compute_intersection_options(stats_widget, column, stats_widget.bulk_assign_rows)
        print(f"[DEBUG] 批量模式下获取交集选项，列{column}：{options}")

        # 设置批量赋值回调
        def bulk_assign_callback(value):
            apply_bulk_assign_value_immediate(stats_widget, column, stats_widget.bulk_assign_rows, value)

        delegate = stats_widget.pipe_column_delegates[column]
        delegate.bulk_select_callback = bulk_assign_callback
        delegate.disable_wheel_scroll = True  # 批量模式下禁用滚轮
        delegate.setItems(options if options else ["None"])
        table.editItem(table.item(row, column))

    else:
        # 单选模式：使用当前行的筛选选项
        filters = {}
        for col_other, field in target_fields.items():
            if col_other != column:
                item = table.item(row, col_other)
                if item and item.text().strip():
                    filters[field] = item.text().strip()

        unit_types = get_unit_types_from_db(stats_widget.product_id)
        pressure_type, _, _ = get_standard_flange_pressure_level_default_value(stats_widget.product_id, stats_widget)
        options = get_filtered_pipe_options(current_field, filters, unit_types, pressure_type)

        # ✅ 新增：如果是压力等级列（第6列），显示接管法兰最小压力等级提示
        if column == 6:
            # 获取管口所属元件
            belong_item = table.item(row, 10)
            pipe_belong = belong_item.text().strip() if belong_item else ""

            # 获取管口ID（从隐藏的管口ID映射中获取）
            pipe_id = None
            if hasattr(stats_widget, 'row_hidden_pipe_id') and row in stats_widget.row_hidden_pipe_id:
                pipe_id = stats_widget.row_hidden_pipe_id[row]

            # 读取管口代号（第1列）
            pipe_code_item = table.item(row, 1)
            pipe_code = pipe_code_item.text().strip() if pipe_code_item else ""

            if pipe_belong and hasattr(stats_widget, 'line_tip'):
                try:
                    tip_message = generate_pressure_level_tips(stats_widget.product_id, pipe_belong, pressure_type, pipe_id, pipe_code)
                    # # ✅ 显示提示：主显示 + tooltip 显示完整内容
                    # display_text = tip_message[:80].replace("\n", " | ")
                    # if len(tip_message) > 80:
                    #     display_text += " ... (鼠标悬停查看完整内容)"
                    # stats_widget.line_tip.setText(display_text)
                    # stats_widget.line_tip.setToolTip(tip_message)
                    # # 确保 tooltip 可见
                    # stats_widget.line_tip.setStatusTip(tip_message)  # 状态栏提示作为备选
                    # stats_widget.line_tip.setStyleSheet("color: orange;")

                    # 使用 QFontMetrics 动态计算文字长度
                    metrics = stats_widget.line_tip.fontMetrics()
                    available_width = stats_widget.line_tip.width() - 30  # 给左右留点空隙
                    elided_text = metrics.elidedText(tip_message.replace("\n", " | "), Qt.ElideRight, available_width)

                    # 如果被省略了，加上提示
                    if elided_text != tip_message:
                        elided_text += "(鼠标悬停查看完整内容)"

                    # 设置显示与悬浮完整提示
                    stats_widget.line_tip.setText(elided_text)
                    stats_widget.line_tip.setToolTip(tip_message)  # 鼠标悬停显示完整内容
                    stats_widget.line_tip.setStatusTip(tip_message)  # 状态栏也显示完整内容
                    stats_widget.line_tip.setStyleSheet("color: orange;")

                except Exception as e:
                    # error_message = f"提示信息获取失败: {str(e)}"
                    # display_text = error_message[:60]
                    # if len(error_message) > 60:
                    #     display_text += "(鼠标悬停查看完整内容)"
                    # stats_widget.line_tip.setText(display_text)
                    # stats_widget.line_tip.setToolTip(error_message)
                    # stats_widget.line_tip.setStatusTip(error_message)
                    # stats_widget.line_tip.setStyleSheet("color: red;")

                    error_message = f"提示信息获取失败: {str(e)}"

                    # 使用 QFontMetrics 动态计算截断
                    metrics = stats_widget.line_tip.fontMetrics()
                    available_width = stats_widget.line_tip.width() - 30  # 给两边留点间距
                    elided_text = metrics.elidedText(error_message.replace("\n", " | "), Qt.ElideRight, available_width)

                    # 如果被省略了，加上提示
                    if elided_text != error_message:
                        elided_text += " ... (鼠标悬停查看完整内容)"

                    # 设置显示和悬浮提示
                    stats_widget.line_tip.setText(elided_text)
                    stats_widget.line_tip.setToolTip(error_message)  # 鼠标悬停完整信息
                    stats_widget.line_tip.setStatusTip(error_message)  # 状态栏完整信息
                    stats_widget.line_tip.setStyleSheet("color: red;")

            elif hasattr(stats_widget, 'line_tip'):
                stats_widget.line_tip.setText("请先选择管口所属元件")
                stats_widget.line_tip.setToolTip("请先选择管口所属元件")
                stats_widget.line_tip.setStatusTip("请先选择管口所属元件")
                stats_widget.line_tip.setStyleSheet("color: orange;")

        delegate = stats_widget.pipe_column_delegates[column]
        delegate.bulk_select_callback = None  # 清除批量回调
        delegate.disable_wheel_scroll = False  # 单选模式下允许滚轮
        delegate.setItems(options if options else ["None"])
        table.editItem(table.item(row, column))

    # ✅ 新增：记录点击单元格的初始值
    item = table.item(row, column)
    stats_widget.original_cell_value = item.text().strip() if item else ""

# ================= 批量赋值（多选行，列4-8）=================
"""当选择变化时，判断是否处于多选批量赋值状态"""
def update_bulk_assign_state(stats_widget):
    table = stats_widget.tableWidget_pipe
    if table is None:
        return

    # 仅在多行选择且当前列为目标列时进入批量模式
    current_col = table.currentColumn()
    target_columns = {4, 5, 6, 7, 8}
    if current_col not in target_columns:
        stats_widget.bulk_assign_target_column = None
        stats_widget.bulk_assign_rows = []
        return

    selected_indexes = table.selectedIndexes()
    if not selected_indexes:
        stats_widget.bulk_assign_target_column = None
        stats_widget.bulk_assign_rows = []
        return

    selected_rows = sorted({idx.row() for idx in selected_indexes})
    last_row = table.rowCount() - 1

    # 如果选择范围包含最后一行，则不进入批量模式
    if last_row in selected_rows:
        stats_widget.bulk_assign_target_column = None
        stats_widget.bulk_assign_rows = []
        return

    # 过滤：去掉没有管口代号的行
    valid_rows = []
    for r in selected_rows:
        code_item = table.item(r, 1)
        if code_item and code_item.text().strip():
            valid_rows.append(r)

    if len(valid_rows) < 2:
        # 少于两行不进入批量模式
        stats_widget.bulk_assign_target_column = None
        stats_widget.bulk_assign_rows = []
        return

    # 检查选中的单元格是否都在同一列（当前列）
    selected_columns = {idx.column() for idx in selected_indexes}
    if len(selected_columns) > 1 or current_col not in selected_columns:
        # 多列选择或当前列不在选中范围内，不进入批量模式
        stats_widget.bulk_assign_target_column = None
        stats_widget.bulk_assign_rows = []
        print(f"[DEBUG] 跨列选择，不进入批量模式：选中列={selected_columns}, 当前列={current_col}")
        return

    # 确保所有选中的单元格都在当前列
    selected_rows_in_current_col = [idx.row() for idx in selected_indexes if idx.column() == current_col]
    if len(selected_rows_in_current_col) != len(valid_rows):
        # 选中的行数与当前列的有效行数不匹配，不进入批量模式
        stats_widget.bulk_assign_target_column = None
        stats_widget.bulk_assign_rows = []
        print(f"[DEBUG] 选中行数不匹配，不进入批量模式：当前列选中行={selected_rows_in_current_col}, 有效行={valid_rows}")
        return

    # 计算交集选项，确保有有效选项
    options = compute_intersection_options(stats_widget, current_col, valid_rows)
    if not options:
        stats_widget.bulk_assign_target_column = None
        stats_widget.bulk_assign_rows = []
        return

    # 进入批量模式
    stats_widget.bulk_assign_target_column = current_col
    stats_widget.bulk_assign_rows = valid_rows
    print(f"[DEBUG] 进入批量赋值模式：列={current_col}, 行={valid_rows}, 交集选项={options}")

"""根据列和多行，计算各行可选项的交集（列4返回统一选项）"""
def compute_intersection_options(stats_widget, column, rows):

    table = stats_widget.tableWidget_pipe
    if column == 4:
        # 公称尺寸：取当前单位类型下的全量选项
        return get_nominal_size_options(stats_widget.product_id, stats_widget) or []

    # 5/6/7/8 列：根据每行已填的其他字段做筛选，最后取交集
    col_to_field = {5: "法兰标准", 6: "压力等级", 7: "法兰型式", 8: "密封面型式"}
    current_field = col_to_field.get(column)
    if not current_field:
        return []

    unit_map = get_unit_types_from_db(stats_widget.product_id) or {}
    pressure_type, _, _ = get_standard_flange_pressure_level_default_value(stats_widget.product_id, stats_widget)

    intersection_set = None
    for r in rows:
        # 构造过滤条件：其余列已填值
        filters = {}
        for col_other, field in col_to_field.items():
            if col_other == column:
                continue
            other_item = table.item(r, col_other)
            val = other_item.text().strip() if other_item else ""
            if val:
                filters[field] = val

        row_options = get_filtered_pipe_options(current_field, filters, unit_map, pressure_type) or []
        row_set = set(row_options)

        if intersection_set is None:
            intersection_set = row_set
        else:
            intersection_set &= row_set

        if not intersection_set:
            # 交集已空，提前结束
            return []

    return sorted(intersection_set) if intersection_set else []

"""立即将值批量赋给指定行的指定列"""
def apply_bulk_assign_value_immediate(stats_widget, column, rows, value):
    table = stats_widget.tableWidget_pipe

    try:
        # 暂时禁用单元格变化信号
        if hasattr(stats_widget, 'suppress_cell_change'):
            stats_widget.suppress_cell_change = True

        for row_idx in rows:
            item = table.item(row_idx, column)
            if not item:
                item = QTableWidgetItem()
                table.setItem(row_idx, column, item)
            item.setText(value)
            item.setTextAlignment(Qt.AlignCenter)

        print(f"[DEBUG] 批量赋值完成：列{column}，行{rows}，值='{value}'")

        # # 清除批量状态
        # stats_widget.bulk_assign_target_column = None
        # stats_widget.bulk_assign_rows = []

    finally:
        # 恢复单元格变化信号
        if hasattr(stats_widget, 'suppress_cell_change'):
            stats_widget.suppress_cell_change = False

################轴向夹角、周向方位、偏心距、外伸高度、轴向定位距离、管口所属元件、压力等级#############################
"""验证轴向夹角"""
def validate_axial_angle(angle_text):
    """
    验证轴向夹角输入值是否在有效范围内
    :param angle_text: 用户输入的角度文本
    :return: (有效性布尔值, 有效角度值或错误消息)
    """
    try:
        if not angle_text or angle_text.strip() == "":
            return True, 0.0  # 空值使用默认值0
        
        angle = float(angle_text)
        if -90 <= angle <= 90:
            return True, angle
        else:
            return False, "轴向夹角必须在-90到90度之间"
    except ValueError:
        return False, "请输入有效的数字"

"""验证周向方位"""
def validate_circumferential_position(position_text, pipe_function=""):
    """
    验证周向方位输入值是否在有效范围内并返回适当的默认值
    :param position_text: 用户输入的周向方位文本
    :param pipe_function: 管口功能，用于确定默认值
    :return: (有效性布尔值, 有效周向方位值或错误消息)
    """
    try:
        # 如果为空，根据管口功能设置默认值
        if not position_text or position_text.strip() == "":
            if pipe_function in ["管程入口", "壳程入口"]:
                return True, 0.0  # 入口默认为0°
            else:
                return True, 180.0  # 出口和其他新增管口默认为180°
        
        position = float(position_text)
        if 0 <= position < 360:
            return True, position
        else:
            return False, "周向方位必须在0到360度之间"
    except ValueError:
        return False, "请输入有效的数字"

"""获取公称直径的方法，在偏心距和外伸高度的验证中会用到"""
def get_nominal_diameter(product_id, pipe_belong):
    conn = None
    cursor = None
    # 判定取值字段：
    # - 管箱 → 管程数值
    # - 壳体 / 外头盖 → 壳程数值
    try:
        if "管箱" in pipe_belong:
            param_field = '管程数值'
        elif ("壳体" in pipe_belong) or ("外头盖" in pipe_belong):
            param_field = '壳程数值'
        else:
            return False, "无效的管口所属元件字段"

        conn = get_connection(**db_config_2)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT 管程数值, 壳程数值 
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
        """, (product_id,))
        result = cursor.fetchone()
        # 判断读取到的内容
        print(result)

        if result is None or result.get(param_field) is None:
            return False, "未获取到公称直径，须先至条件输入输入公称直径并保存"
        return True, float(result[param_field])
    except Exception as e:
        return False, f"数据库错误: {str(e)}"
    finally:
        cursor and cursor.close()
        conn and conn.close()

"""根据公称直径获取推荐的公称尺寸"""
def get_recommended_nominal_size(nominal_diameter, pipe_belong):
    """
    根据公称直径和管口所属元件，查询推荐的公称尺寸
    :param nominal_diameter: 公称直径值
    :param pipe_belong: 管口所属元件（管箱或壳体）
    :return: (是否成功: bool, 推荐值或错误消息: str)
    """
    try:
        conn = get_connection(**db_config_1)
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 查询公称直径在指定范围内的推荐值
        cursor.execute("""
            SELECT 管程出入口公称尺寸, 壳程出入口公称尺寸
            FROM 热交换器管壳程进出口默认规格表
            WHERE %s >= dn_min AND (%s < dn_max OR dn_max IS NULL)
            LIMIT 1
        """, (nominal_diameter, nominal_diameter))

        result = cursor.fetchone()
        if not result:
            return False, f"未找到公称直径 {nominal_diameter} 对应的推荐规格"

        # 根据管口所属元件返回对应的推荐值
        if "管箱" in pipe_belong:
            recommended_size = result['管程出入口公称尺寸']
        elif ("壳体" in pipe_belong) or ("外头盖" in pipe_belong):
            recommended_size = result['壳程出入口公称尺寸']
        else:
            return False, "无效的管口所属元件字段"

        return True, recommended_size

    except Exception as e:
        return False, f"查询推荐规格失败: {str(e)}"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

"""自动为前四个管口推荐公称尺寸"""
def auto_recommend_nominal_sizes_for_first_four_pipes(stats_widget, product_id):
    """
    自动为前四个管口推荐公称尺寸
    :param stats_widget: 主窗口实例
    :param product_id: 产品ID
    """
    try:
        table = stats_widget.tableWidget_pipe

        # 只处理前4行（索引0-3）
        for row in range(min(4, table.rowCount() - 1)):  # 排除最后一行空白行
            # 检查是否有管口代号
            code_item = table.item(row, 1)
            if not code_item or not code_item.text().strip():
                continue

            # 🚩 修改：在初始化时，如果没有管口所属元件，尝试根据管口功能推断
            belong_item = table.item(row, 10)
            pipe_belong = ""

            if belong_item and belong_item.text().strip():
                pipe_belong = belong_item.text().strip()
            else:
                # 如果没有管口所属元件，尝试根据管口功能推断
                function_item = table.item(row, 2)  # 管口功能列
                if function_item and function_item.text().strip():
                    function_text = function_item.text().strip()
                    # 根据管口功能推断所属元件
                    if "管程" in function_text:
                        pipe_belong = "管箱圆筒"  # 默认管程管口属于管箱
                    elif "壳程" in function_text:
                        pipe_belong = "壳体圆筒"  # 默认壳程管口属于壳体
                    else:
                        # 如果无法推断，跳过这一行
                        print(f"[DEBUG] 行{row}无法推断管口所属元件，跳过")
                        continue

            if not pipe_belong:
                print(f"[DEBUG] 行{row}没有管口所属元件，跳过")
                continue

            # 获取公称直径
            success, result = get_nominal_diameter(product_id, pipe_belong)
            if not success:
                print(f"[DEBUG] 行{row}获取公称直径失败: {result}")
                continue

            nominal_diameter = result

            # 获取推荐的公称尺寸
            success, recommended_size = get_recommended_nominal_size(nominal_diameter, pipe_belong)
            if not success:
                print(f"[DEBUG] 行{row}获取推荐规格失败: {recommended_size}")
                continue

            # 设置推荐值到公称尺寸列（第4列）
            size_item = table.item(row, 4)
            if not size_item:
                size_item = QTableWidgetItem()
                table.setItem(row, 4, size_item)

            size_item.setText(str(recommended_size))
            size_item.setTextAlignment(Qt.AlignCenter)

            print(f"[DEBUG] 行{row}自动推荐公称尺寸: {nominal_diameter} -> {recommended_size}")

    except Exception as e:
        print(f"[ERROR] 自动推荐公称尺寸失败: {str(e)}")
        # 在初始化时，不显示错误弹窗，只记录日志
        print(f"[ERROR] 自动推荐公称尺寸失败: {str(e)}")

"""验证偏心距"""
def validate_eccentricity(eccentricity_text, product_id, pipe_belong, emit_error=True):
    """
    验证偏心距输入值是否在有效范围内，并动态查询公称直径
    :param eccentricity_text: 用户输入的偏心距文本
    :param product_id: 产品ID
    :param pipe_belong: 管口所属元件（管箱或壳体）
    :return: (是否有效: bool, 数值或错误消息: float|str)
    如果 emit_error=False，不弹窗，只返回错误信息。
    """
    try:
        # 允许空值
        if not eccentricity_text or eccentricity_text.strip() == "":
            return True, 0.0

        eccentricity = float(eccentricity_text)

        # 管口所属元件未填写，显示最大值为 0.0
        if not pipe_belong:
            if eccentricity == 0.0:
                return True, 0.0
            else:
                return False, "偏心距必须在-0.0到0.0之间"

        success, result_or_error = get_nominal_diameter(product_id, pipe_belong)
        if not success:
            if emit_error:
                QMessageBox.warning(None, "验证错误", result_or_error)
            return False, result_or_error

        nominal_diameter = result_or_error
        max_ecc = nominal_diameter / 2

        if -max_ecc < eccentricity < max_ecc:
            return True, eccentricity
        else:
            return False, f"偏心距必须在-{max_ecc}到{max_ecc}之间"

    except ValueError:
        return False, "请输入有效的数字"

"""验证外伸高度"""
def validate_extension_height(height_text, product_id, pipe_belong, emit_error=True):
    """
    验证外伸高度是否有效。可为"程序推荐"，否则不能小于公称直径的一半。
    如果 emit_error=False，不弹窗，只返回错误信息
    """
    try:
        if not height_text or height_text.strip() == "":
            return True, "程序推荐"
        if height_text.strip() == "程序推荐":
            return True, "程序推荐"

        height_val = float(height_text)

        success, result_or_error = get_nominal_diameter(product_id, pipe_belong)
        if not success:
            if emit_error:
                QMessageBox.warning(None, "验证错误", result_or_error)
            return False, result_or_error

        nominal_diameter = result_or_error
        min_height = nominal_diameter / 2

        if height_val < min_height:
            return False, f"外伸高度不能小于公称直径的一半（{min_height}mm），请核对后重新输入"
        return True, height_val

    except ValueError:
        return False, "请输入有效数字或\"程序推荐\""

"""补丁：用于清空下方的提示条"""
def _set_tip(stats_widget, text="", color=None):
    """统一设置/清空底部提示条"""
    if not hasattr(stats_widget, "line_tip"):
        return
    stats_widget.line_tip.setText(text or "")
    stats_widget.line_tip.setToolTip(text or "")
    stats_widget.line_tip.setStatusTip(text or "")
    stats_widget.line_tip.setStyleSheet(f"color: {color};" if color else "")

"""补丁：以下两个方法用于判断“零/非零”和“是否刚从零变为非零”"""
def _is_zero_like(text: str) -> bool:
    """把 '', '0', '0.0', '0.00' 等都视为 0；非法数字也按非零处理"""
    t = (text or "").strip()
    if t in {"", "0", "0.0", "0.00"}:
        return True
    try:
        return abs(float(t)) < 1e-9
    except Exception:
        return False  # 非法数字当作非零，交给各自验证去拦

def _just_turned_from_zero_to_nonzero(stats_widget, new_text: str) -> bool:
    """
    仅当“本次编辑”的原值为零样式、且新值为非零样式时返回 True。
    - 依赖 handle_pipe_cell_click() 里记录的 stats_widget.original_cell_value
    """
    old_text = getattr(stats_widget, "original_cell_value", "")
    return _is_zero_like(old_text) and (not _is_zero_like(new_text))

"""轴向定位基准互斥选择"""
def enforce_shell_inout_axial_base_mutex(stats_widget, changed_row: int):
    """
    在六种型式下，使“壳程入口”和“壳程出口”的【轴向定位基准】互斥：
      - 任一方选为“右基准线”，另一方自动置为“左基准线”
      - 任一方改为“左基准线”，另一方自动置为“右基准线”
    只对 壳程入口/壳程出口 生效，且仅在产品型式 ∈ MUTEX_PRODUCT_VERSIONS 时启用
    """
    table = stats_widget.tableWidget_pipe
    product_version = getattr(stats_widget, "current_product_version", "") or ""
    if product_version not in ["AEU", "BEU", "AES", "BES", "NEN", "BEM"]:
        return

    func_col = 2      # 管口功能
    base_col = 11     # 轴向定位基准

    func_item = table.item(changed_row, func_col)
    base_item = table.item(changed_row, base_col)
    if not func_item or not base_item:
        return

    func_text = (func_item.text() or "").strip()
    base_text = (base_item.text() or "").strip()

    # 仅当修改的是壳程入口/壳程出口，且值为“左/右基准线”之一时才处理
    if func_text not in {"壳程入口", "壳程出口"} or base_text not in ["左基准线", "右基准线"]:
        return

    # 找到“另一方”行
    target_func = "壳程出口" if func_text == "壳程入口" else "壳程入口"
    other_row = None
    last = table.rowCount() - 1
    for r in range(0, last):  # 排除最后一行新增行
        it = table.item(r, func_col)
        if it and (it.text() or "").strip() == target_func:
            other_row = r
            break

    if other_row is None:
        return

    # 期望另一方取反
    desired_other = "左基准线" if base_text == "右基准线" else "右基准线"

    other_item = table.item(other_row, base_col)
    if other_item is None:
        from PyQt5.QtWidgets import QTableWidgetItem
        other_item = QTableWidgetItem("")
        other_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(other_row, base_col, other_item)

    # 若当前另一方已经是反向，就不必写回；否则写回并抑制回调重入
    if (other_item.text() or "").strip() != desired_other:
        try:
            # 利用项目中已有的抑制标志，避免递归触发 handle_pipe_cell_changed
            if hasattr(stats_widget, "suppress_cell_change"):
                stats_widget.suppress_cell_change = True
            other_item.setText(desired_other)
            other_item.setTextAlignment(Qt.AlignCenter)
        finally:
            if hasattr(stats_widget, "suppress_cell_change"):
                stats_widget.suppress_cell_change = False

"""处理单元格内容改变时触发的验证"""
def handle_pipe_cell_changed(stats_widget, row, column, product_id):
    """
    处理管口表格单元格值改变事件，对特定列进行值验证
    :param stats_widget: Stats类实例
    :param row: 修改的行号
    :param column: 修改的列号
    :param product_id: 产品ID
    """
    # ✅ 跳过由 setText 触发的程序性修改
    if getattr(stats_widget, "suppress_cell_change", False):
        return

    table = stats_widget.tableWidget_pipe
    item = table.item(row, column)
    
    if not item:
        return

    # ---------------- 新增：在最后一行“新增触发”之前做重复校验 ----------------
    # 仅在编辑的是管口代号列时检查
    if column == 1:
        from modules.guankoudingyi.funcs.funcs_pipe_table import is_duplicate_port_code, \
            control_last_row_editable_state
        code_text = item.text().strip()
        if code_text:  # 非空才检查
            if is_duplicate_port_code(table, code_text, row):
                # 重复：清空并保持最后一行冻结，禁止新增
                QMessageBox.warning(stats_widget, "管口代号重复", f"管口代号 '{code_text}' 已存在，禁止重复。")
                try:
                    stats_widget.suppress_cell_change = True
                    item.setText("")
                finally:
                    stats_widget.suppress_cell_change = False
                # 确保最后一行仍是冻结态
                control_last_row_editable_state(stats_widget, enable_editing=False)
                return
    # ----------------------------------------------------------------------
    ##########################
    # 检查是否是最后一行
    is_last_row = (row == table.rowCount() - 1)
    
    # 检查该行是否有管口代号（第1列，索引为1）
    pipe_code_item = table.item(row, 1)
    has_pipe_code = pipe_code_item.text().strip() != ""
    
    # ✅ 优先处理：如果是最后一行的管口代号列且刚填写完成，解冻其他列
    if is_last_row and column == 1 and has_pipe_code:
        # 导入解冻函数
        from modules.guankoudingyi.funcs.funcs_pipe_table import control_last_row_editable_state
        control_last_row_editable_state(stats_widget, enable_editing=True)
        # ✅ 新增：为该行分配“隐藏管口ID”（运行期，不入库）
        from modules.guankoudingyi.funcs.funcs_pipe_table import (
            ensure_hidden_maps, get_next_pipe_id_runtime
        )
        ensure_hidden_maps(stats_widget)
        try:
            new_hid = get_next_pipe_id_runtime(stats_widget, product_id)
            if not hasattr(stats_widget, "row_hidden_pipe_id"):
                stats_widget.row_hidden_pipe_id = {}
            stats_widget.row_hidden_pipe_id[row] = new_hid
        except Exception as e:
            QMessageBox.warning(stats_widget, "分配管口ID失败", f"无法分配新的管口ID：{e}")
        # 检查是否需要添加新行
        from modules.guankoudingyi.funcs.funcs_pipe_table import check_last_row_and_add_new
        check_last_row_and_add_new(stats_widget)
        return
    
    # ✅ 对于其他列，检查是否需要验证的列
    # 需要验证的列：轴向夹角(13)、周向方位(14)、偏心距(15)、外伸高度(16)、轴向定位距离(12)
    validation_columns = {12, 13, 14, 15, 16}
    if column != 1 and column not in validation_columns:
        # 对于非验证列，仍然只处理当前点击编辑的单元格
        if getattr(stats_widget, 'current_editing_cell', None) != (row, column):
            return
    
    # ✅ 对于验证列，无论是点击还是键盘输入都进行验证
    # 清除编辑状态标记（无论是否通过点击进入）
    if column in validation_columns:
        stats_widget.current_editing_cell = None
    
    # 如果是最后一行且没有管口代号，不设置默认值
    if is_last_row and not has_pipe_code:
        return
    ##########################
    # 验证轴向夹角
    if column == 13:  # 轴向夹角列
        valid, result = validate_axial_angle(item.text())
        if not valid:
            # stats_widget.line_tip.setText(result)
            # stats_widget.line_tip.setStyleSheet("color: red;")
            _set_tip(stats_widget, result, "red")
            # 获取默认值
            _, default_value = validate_axial_angle("")
            # item.setText(str(default_value))
            # 🔧 关键：防止二次触发把红色提示清掉
            try:
                stats_widget.suppress_cell_change = True
                item.setText(str(default_value))
            finally:
                stats_widget.suppress_cell_change = False
            return  # ❗非法时直接返回，保留红色提示
        else:
            # 验证通过时清空警告
            _set_tip(stats_widget, "")
            # 写回规范化值也用 blockSignals，避免多余触发
            table.blockSignals(True)
            item.setText(str(result))
            table.blockSignals(False)

            # 🚩 新增逻辑：若偏心距 ≠ 0，则清空偏心距并弹窗
            ecc_item = table.item(row, 15)
            # if ecc_item and ecc_item.text().strip() not in ["", "0", "0.0"]:
            if (
                ecc_item
                and not _is_zero_like(ecc_item.text())
                and _just_turned_from_zero_to_nonzero(stats_widget, str(result))
            ):
                stats_widget.suppress_cell_change = True
                ecc_item.setText("0.0")
                stats_widget.suppress_cell_change = False
                QMessageBox.warning(
                    stats_widget,
                    "校验冲突",
                    "因轴向夹角和偏心距被同时赋值，基于GB/T 150规则无法对此管口进行强度校核"
                )
                
        # ✅ 轴向夹角改变后刷新绘图
        if hasattr(stats_widget, 'view') and stats_widget.view:
            stats_widget.view.set_pipe_data(stats_widget.get_all_pipe_data())
    
    # 验证周向方位
    elif column == 14:  # 周向方位列
        # 获取管口功能
        function_column = 2  # "管口功能"列的索引为2
        function_item = table.item(row, function_column)
        pipe_function = ""
        if function_item:
            pipe_function = function_item.text().strip()
        
        valid, result = validate_circumferential_position(item.text(), pipe_function)
        if not valid:
            # stats_widget.line_tip.setText(result)
            # stats_widget.line_tip.setStyleSheet("color: red;")
            _set_tip(stats_widget, result, "red")
            # 获取默认值
            _, default_value = validate_circumferential_position("", pipe_function)
            # 🔧 关键：防止二次触发把红色提示清掉
            try:
                stats_widget.suppress_cell_change = True
                item.setText(str(default_value))
            finally:
                stats_widget.suppress_cell_change = False

            return  # ❗非法时直接返回，保留红色提示
        else:
            # 验证通过时清空警告
            _set_tip(stats_widget, "")
            table.blockSignals(True)
            item.setText(str(result))
            table.blockSignals(False)
        # ✅ 周向方位改变后刷新绘图
        if hasattr(stats_widget, 'view') and stats_widget.view:
            stats_widget.view.set_pipe_data(stats_widget.get_all_pipe_data())

    # 验证偏心距
    # 偏心距验证（第15列）
    elif column == 15:
        belong_item = table.item(row, 10)
        pipe_belong = belong_item.text().strip() if belong_item else ""
        valid, result = validate_eccentricity(item.text(), product_id, pipe_belong, emit_error=False)

        if not valid:
            # stats_widget.line_tip.setStyleSheet("color: red;")
            # stats_widget.line_tip.setText(f"{result}")
            _set_tip(stats_widget, result, "red")
            _, default_value = validate_eccentricity("", product_id, pipe_belong, emit_error=False)
            stats_widget.suppress_cell_change = True
            item.setText(str(default_value))
            stats_widget.suppress_cell_change = False
        else:
            # 验证通过时清空警告
            _set_tip(stats_widget, "")
            table.blockSignals(True)
            item.setText(str(result))
            table.blockSignals(False)
            # 🚩 新增逻辑：若轴向夹角 ≠ 0，则清空轴向夹角并弹窗
            angle_item = table.item(row, 13)
            # if angle_item and angle_item.text().strip() not in ["", "0", "0.0"]:
            if (
                angle_item
                and not _is_zero_like(angle_item.text())
                and _just_turned_from_zero_to_nonzero(stats_widget, str(result))
            ):
                stats_widget.suppress_cell_change = True
                angle_item.setText("0.0")
                stats_widget.suppress_cell_change = False
                QMessageBox.warning(
                    stats_widget,
                    "校验冲突",
                    "因轴向夹角和偏心距被同时赋值，基于GB/T 150规则无法对此管口进行强度校核"
                )
                
        # ✅ 偏心距改变后刷新绘图
        if hasattr(stats_widget, 'view') and stats_widget.view:
            stats_widget.view.set_pipe_data(stats_widget.get_all_pipe_data())


    # 外伸高度验证（第16列）
    elif column == 16:
        belong_item = table.item(row, 10)
        pipe_belong = belong_item.text().strip() if belong_item else ""

        # if not pipe_belong and not (is_last_row and not has_pipe_code):
        #     return

        valid, result = validate_extension_height(item.text(), product_id, pipe_belong, emit_error=False)
        if not valid:
            # stats_widget.line_tip.setStyleSheet("color: red;")
            # stats_widget.line_tip.setText(f"{result}")
            _set_tip(stats_widget, result, "red")
            _, default_value = validate_extension_height("", product_id, pipe_belong, emit_error=False)
            table.blockSignals(True)
            item.setText(str(default_value))
            table.blockSignals(False)
        else:
            # 验证通过时清空警告
            _set_tip(stats_widget, "")
            table.blockSignals(True)
            item.setText(str(result))
            table.blockSignals(False)
            
        # ✅ 外伸高度改变后刷新绘图
        if hasattr(stats_widget, 'view') and stats_widget.view:
            stats_widget.view.set_pipe_data(stats_widget.get_all_pipe_data())


    # 验证轴向定位距离
    elif column == 12:  # 轴向定位距离列
        # 获取管口功能
        function_item = table.item(row, 2)  # 2是管口功能列的索引
        pipe_function = function_item.text().strip() if function_item else ""

        # 获取当前输入值
        input_value = item.text().strip()

        # 验证输入值
        if input_value in ["程序推荐", "居中"]:
            # 如果是预设选项，直接使用
            item.setText(input_value)
        else:
            try:
                # 尝试转换为浮点数
                float_value = float(input_value)
                # 如果是数字，直接使用
                item.setText(str(float_value))
            except ValueError:
                # 如果既不是预设选项也不是有效数字，根据管口功能设置默认值
                if pipe_function in ["管程入口", "管程出口"]:
                    item.setText("居中")
                else:
                    item.setText("程序推荐")
                    
        # ✅ 轴向定位距离改变后刷新绘图
        if hasattr(stats_widget, 'view') and stats_widget.view:
            stats_widget.view.set_pipe_data(stats_widget.get_all_pipe_data())

    # "管口所属元件"列
    elif column == 10:
        new_value = item.text().strip() if item else ""
        old_value = stats_widget.pipe_belong_old_values.get(row, "") if hasattr(stats_widget, 'pipe_belong_old_values') else ""

        if new_value.endswith("封头") and old_value.endswith("圆筒"):
            target_item = table.item(row, 11)
            if not target_item:
                target_item = QTableWidgetItem()
                table.setItem(row, 11, target_item)
            target_item.setText("封头中心线")
            target_item.setTextAlignment(Qt.AlignCenter)

        elif new_value.endswith("圆筒") and old_value.endswith("封头"):
            target_item = table.item(row, 11)
            if not target_item:
                target_item = QTableWidgetItem()
                table.setItem(row, 11, target_item)
            target_item.setText("左基准线")
            target_item.setTextAlignment(Qt.AlignCenter)

        # 注意：后续修改管口所属元件时不再自动推荐公称尺寸
        # 只在初始化时推荐一次

        # 更新旧值
        if not hasattr(stats_widget, 'pipe_belong_old_values'):
            stats_widget.pipe_belong_old_values = {}
        stats_widget.pipe_belong_old_values[row] = new_value

    # ✅ 新增：轴向定位基准列改变时触发绘图更新
    elif column == 11:  # 轴向定位基准列
        # === 壳程入口/出口互斥处理 ===
        enforce_shell_inout_axial_base_mutex(stats_widget, row)

        # 检查当前行是否已有足够的基本信息来触发绘图
        pipe_code_item = table.item(row, 1)
        nominal_size_item = table.item(row, 4)
        pipe_belong_item = table.item(row, 10)
        axial_base_item = table.item(row, 11)
        
        if (pipe_code_item and pipe_code_item.text().strip() and
            nominal_size_item and nominal_size_item.text().strip() and
            pipe_belong_item and pipe_belong_item.text().strip() and
            axial_base_item and axial_base_item.text().strip()):
            
            # 满足基本条件，刷新绘图
            if hasattr(stats_widget, 'view') and stats_widget.view:
                stats_widget.view.set_pipe_data(stats_widget.get_all_pipe_data())


"""对压力等级列进行验证的步骤，所调用的方法"""
# step1.分别确定三个接管法兰的类别号
def get_material_category_number_by_product(product_id, pressure_type, pipe_id=None):
    """
    先从产品设计活动表_管口类别表读取管口属于哪个类别，
    然后从产品设计活动表_管口附加参数表中获取对应类别的接管法兰零件材料类型和材料牌号，
    再去元件库中的材料温压值类别表中查找对应的类别号。
    :param product_id: 产品ID
    :param pressure_type: 压力类型（Class或PN）
    :param pipe_id: 管口ID（可选，如果提供则只查询该管口的分类）
    :return: 返回三个接管法兰的材料信息字典列表
    """
    conn_design = None
    conn_component = None
    try:
        # === 第一步：查产品设计活动库中的管口类别 ===
        conn_design = get_connection(**db_config_2)
        cursor_design = conn_design.cursor(pymysql.cursors.DictCursor)

        # 先从管口类别表查询该产品的管口类别
        if pipe_id:
            # 查询特定管口的材料分类
            cursor_design.execute("""
                SELECT DISTINCT 材料分类
                FROM 产品设计活动表_管口类别表
                WHERE 产品ID = %s AND 管口ID = %s AND 材料分类 IS NOT NULL
            """, (product_id, pipe_id))
        else:
            # 查询该产品所有管口的材料分类
            cursor_design.execute("""
                SELECT DISTINCT 材料分类
                FROM 产品设计活动表_管口类别表
                WHERE 产品ID = %s AND 材料分类 IS NOT NULL
                ORDER BY 材料分类
            """, (product_id,))

        categories = cursor_design.fetchall()

        if not categories:
            return None, "未找到任何管口材料分类信息"

        print(f"[DEBUG_01] 获取到的材料分类: {[c['材料分类'] for c in categories]}")

        # 查询每个分类下的接管法兰材料信息
        flange_materials = []
        for category_row in categories:
            category = category_row['材料分类']

            # 查询该分类下所有接管法兰材料类型参数
            cursor_design.execute("""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_管口附加参数表
                WHERE 产品ID = %s AND 类别 = %s AND 参数名称 LIKE %s
            """, (product_id, category, '接管法兰材料类型%'))
            type_results = cursor_design.fetchall()

            # 查询该分类下所有接管法兰材料牌号参数
            cursor_design.execute("""
                SELECT 参数名称, 参数值
                FROM 产品设计活动表_管口附加参数表
                WHERE 产品ID = %s AND 类别 = %s AND 参数名称 LIKE %s
            """, (product_id, category, '接管法兰材料牌号%'))
            grade_results = cursor_design.fetchall()

            # 将结果转换为字典以便匹配
            type_dict = {row['参数名称']: row['参数值'] for row in type_results if row['参数值']}
            grade_dict = {row['参数名称']: row['参数值'] for row in grade_results if row['参数值']}

            # 匹配材料类型和材料牌号
            for type_param, material_type in type_dict.items():
                # 从参数名称中提取编号（如"接管法兰材料类型1" -> "1"）
                type_number = type_param.replace('接管法兰材料类型', '')
                grade_param = f'接管法兰材料牌号{type_number}'

                if grade_param in grade_dict:
                    material_grade = grade_dict[grade_param]

                    # ✅ 映射特殊材料类型
                    type_mapping = {
                        "Q235 系列钢板": "钢板"
                    }
                    material_type_mapped = type_mapping.get(material_type, material_type)

                    print(f"[DEBUG_02] 管口材料分类={category}, 接管法兰号={type_number}, 材料类型={material_type}, "
                          f"材料牌号={material_grade}, 映射后类型={material_type_mapped}")

                    # === 第二步：查元件库中的材料温压值类别表 ===
                    conn_component = get_connection(**db_config_1)
                    cursor_component = conn_component.cursor(pymysql.cursors.DictCursor)
                    cursor_component.execute("""
                        SELECT 类别号
                        FROM 材料温压值类别表
                        WHERE 材料类型 = %s AND 材料牌号 = %s AND 公称压力类型 = %s
                        LIMIT 1
                    """, (material_type_mapped, material_grade, pressure_type))
                    category_result = cursor_component.fetchone()

                    # 检查是否找到类别号
                    if not category_result:
                        # 仍然添加法兰信息，但标记为无类别号
                        print(f"[DEBUG_03] ❌ 未找到类别号 → 材料类型={material_type_mapped}, "
                              f"材料牌号={material_grade}, 压力类型={pressure_type}")

                        flange_info = {
                            'flange_number': type_number,
                            'category': category,
                            'material_type': material_type,
                            'material_grade': material_grade,
                            'material_type_mapped': material_type_mapped,
                            'category_number': None,
                            'no_category_found': True  # 标记为未找到类别
                        }
                    else:
                        print(f"[DEBUG_04] ✅ 找到类别号: {category_result['类别号']}")

                        flange_info = {
                            'flange_number': type_number,
                            'category': category,
                            'material_type': material_type,
                            'material_grade': material_grade,
                            'material_type_mapped': material_type_mapped,
                            'category_number': category_result["类别号"]
                        }

                    flange_materials.append(flange_info)

                    if conn_component:
                        conn_component.close()
                        conn_component = None

        if not flange_materials:
            return None, "未找到任何接管法兰的材料信息"

        return flange_materials, None

    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        return None, f"查询失败: {str(e)}"
    finally:
        if conn_design:
            conn_design.close()
        if conn_component:
            conn_component.close()

# step2. 获取管口所属元件
# step3. 根据上一步的管口所属元件确定取管程还是壳程数值，获得最大工作温度
def get_max_working_temperature_by_belong(product_id, pipe_belong):
    """
    根据产品ID和管口所属元件字段，获取"工作温度（入口）"与"工作温度（出口）"中的最大温度值。
    :param product_id: 产品ID
    :param pipe_belong: 管口所属元件（如"管箱圆筒"或"壳体封头"）
    """
    conn = None
    cursor = None
    try:
        if "管箱" in pipe_belong:
            value_field = "管程数值"
        elif "壳体" in pipe_belong or "外头盖" in pipe_belong:
            value_field = "壳程数值"
        else:
            return None, "无效的管口所属元件字段"

        conn = get_connection(**db_config_2)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute(f"""
            SELECT `{value_field}`
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s AND 参数名称 IN ('工作温度（入口）', '工作温度（出口）')
        """, (product_id,))
        results = cursor.fetchall()

        temperatures = []
        for row in results:
            val = row.get(value_field)
            if val is not None:
                try:
                    temperatures.append(float(val))
                except ValueError:
                    continue

        if not temperatures:
            return None, f"未找到有效的{value_field}温度值"
        return max(temperatures), None

    except Exception as e:
        return None, f"获取工作温度失败: {str(e)}"
    finally:
        cursor and cursor.close()
        conn and conn.close()

# step4. 根据step2的管口所属元件确定取管程还是壳程数值，获得工作压力
def get_working_pressure_by_belong(product_id, pipe_belong):
    """
    根据产品ID和管口所属元件字段（管箱/壳体）优先获取"最高允许工作压力"，如果获取不到则获取"设计压力*"
    """
    conn = None
    cursor = None
    try:
        if "管箱" in pipe_belong:
            value_field = "管程数值"
        elif "壳体" in pipe_belong or "外头盖" in pipe_belong:
            value_field = "壳程数值"
        else:
            return None, "无效的管口所属元件字段"

        conn = get_connection(**db_config_2)
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 优先尝试获取"最高允许工作压力"
        cursor.execute(f"""
            SELECT `{value_field}` AS val
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s AND 参数名称 = '最高允许工作压力'
            LIMIT 1
        """, (product_id,))
        result = cursor.fetchone()

        if result:
            val = result.get("val")
            try:
                return float(val), None
            except(ValueError, TypeError):
                pass  # 如果val不为空装换成float，否则直接跳过

        # 如果获取不到，再获取"设计压力*"
        cursor.execute(f"""
            SELECT `{value_field}` AS val
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s AND 参数名称 LIKE '设计压力%%'
            LIMIT 1
        """, (product_id,))
        result = cursor.fetchone()

        if result:
            val = result.get("val")
            try:
                return float(val), None
            except (ValueError, TypeError):
                return None, f"{value_field} 的设计压力*不是有效数字"

        return None, f"{value_field} 中未找到有效的设计压力*"

    except Exception as e:
        return None, f"获取参考压力失败: {str(e)}"
    finally:
        cursor and cursor.close()
        conn and conn.close()

# step5.确定每个接管法兰压力等级的推荐值（允许部分成功）
def get_minimum_pressure_level_for_flanges(product_id, pipe_belong, pressure_type, pipe_id=None, pipe_code=None):
    """
    允许“部分成功”；识别出>=1组材料即进行计算推荐
    未填写/未匹配到类别号，则作为警告返回，不吞掉成功的结果，即对三组均有反馈
    """
    try:
        # Step 1: 获取所有接管法兰材料信息
        flange_materials, error = get_material_category_number_by_product(product_id, pressure_type, pipe_id)
        # 没有填写接管法兰的材料信息
        if error or not flange_materials:
            return None, error or "请完善接管法兰材料信息"

        # 把经过Step 1后的情况分为三种：未填写、无类别号、可计算
        missing_nums = []        # 有该组但材料类型/牌号缺失
        no_category_list = []    # 材料类型和牌号齐全但是没有找到对应的类别号（去温压值表失败）
        computable = []          # 可以计算的组，即能够识别出类别号

        for f in flange_materials:
            num = f.get('flange_number')
            if not f.get('material_type') or not f.get('material_grade'):
                if num is not None:
                    missing_nums.append(str(num))
                continue

            if not f.get('category_number'):
                if f.get('no_category_found'):
                    no_category_list.append({
                        'flange_number': num,
                        'material_type': f.get('material_type'),
                        'material_grade': f.get('material_grade')
                    })
                continue
            computable.append(f)

        # Step 2: 获取工作温度
        max_temp, temp_error = get_max_working_temperature_by_belong(product_id, pipe_belong)

        if temp_error:
            return None, f"获取工作温度失败: {temp_error}"

        # 将最大工作温度转换为查询温度（若小于等于38，则统一按38处理）
        if max_temp <= 38:
            query_temp = 38
        else:
            query_temp = max_temp


        # Step 3: 获取工作压力
        work_pressure, pressure_error = get_working_pressure_by_belong(product_id, pipe_belong)

        if pressure_error:
            return None, f"获取工作压力失败: {pressure_error}"

        # Step 4: 为每个接管法兰计算最小压力等级
        flange_pressure_info = []
        for flange in computable:
            # 查询该材料在指定温度下的所有压力等级及对应的最大允许工作压力
            conn = get_connection(**db_config_1)
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            try:
                cursor.execute("""
                    SELECT DISTINCT 压力等级, 工作温度, 最大允许工作压力
                    FROM 温压值表
                    WHERE 类别号 = %s
                    ORDER BY 压力等级 ASC, 工作温度 ASC
                """, (flange['category_number'],)
                )
                temp_pressure_data = cursor.fetchall()
                if not temp_pressure_data:
                    print(f"DEBUG_05: 没有找到类别号 {flange['category_number']} 的温压数据")
                    continue

                # 按压力等级分组
                pressure_levels = {}
                for row in temp_pressure_data:
                    level = row['压力等级']
                    if level not in pressure_levels:
                        pressure_levels[level] = []
                    pressure_levels[level].append({
                        'temp': float(row['工作温度']),
                        'pressure': float(row['最大允许工作压力'])
                    })


                # 找到满足条件的最小压力等级
                suitable_levels = []
                for level, data_points in pressure_levels.items():
                    # 计算在查询温度下的最大允许工作压力
                    data_points.sort(key=lambda x: x['temp'])
                    temperatures = [point['temp'] for point in data_points]
                    pressures = [point['pressure'] for point in data_points]

                    if query_temp in temperatures:
                        max_allow_pressure = pressures[temperatures.index(query_temp)]
                    elif query_temp > max(temperatures):
                        continue  # 超出温度范围，跳过此压力等级
                    else:
                        # 线性插值
                        smaller_temps = [t for t in temperatures if t < query_temp]
                        larger_temps = [t for t in temperatures if t > query_temp]

                        if not smaller_temps or not larger_temps:
                            print(f"DEBUG_06: 无法对温度 {query_temp} 进行插值，跳过")
                            continue

                        smaller = max(smaller_temps)
                        larger = min(larger_temps)
                        p1 = pressures[temperatures.index(smaller)]
                        p2 = pressures[temperatures.index(larger)]
                        slope = (p2 - p1) / (larger - smaller)
                        max_allow_pressure = p1 + slope * (query_temp - smaller)

                    # 🚩单位换算：bar → MPa
                    max_allow_pressure_mpa = max_allow_pressure * 0.1

                    # 检查是否满足工作压力要求
                    if work_pressure <= max_allow_pressure_mpa:
                        suitable_levels.append(level)
                    else:
                        print(
                            f"DEBUG_07: 不满足条件 → "
                            f"接管法兰{flange['flange_number']} "
                            f"(材料类型={flange['material_type']}, 材料牌号={flange['material_grade']}, 类别号={flange['category_number']}) "
                            f"在压力等级 {level} 时, "
                            f"查询温度={query_temp}°C, "
                            f"工作压力={work_pressure} MPa > 最大允许工作压力={max_allow_pressure_mpa:.3f} MPa"
                        )

                # 选择最小的满足条件的压力等级
                if suitable_levels:
                    # 对压力等级进行排序（根据数值大小）
                    if pressure_type == "Class":
                        # Class类型按数字排序
                        suitable_levels.sort(key=lambda x: int(x))
                    else:
                        # PN类型按数字排序
                        suitable_levels.sort(key=lambda x: float(x))

                    min_pressure_level = suitable_levels[0]

                    flange_info = {
                        'flange_number': flange['flange_number'],
                        'material_type': flange['material_type'],
                        'material_grade': flange['material_grade'],
                        'min_pressure_level': f"{pressure_type} {min_pressure_level}"
                    }
                    flange_pressure_info.append(flange_info)

            finally:
                cursor.close()
                conn.close()

        # 整合非致命警告并返回（不吞掉已成功结果）
        warn_parts = []
        if no_category_list:
            for f in no_category_list:
                prefix = f"管口代号为 {pipe_code} 的" if pipe_code else ""
                warn_parts.append(
                    f"{prefix}接管法兰材料类型为 {f['material_type']}，牌号为 {f['material_grade']} 时，未查询到其适用的最小压力等级!"
                )
        if missing_nums:
            warn_parts.append("请完善接管法兰材料信息：" +
                              "、".join([f"接管法兰{n}" for n in sorted(missing_nums, key=int)]) +
                              "的材料类型或材料牌号未输入")
        warn_msg = " ".join(warn_parts) if warn_parts else None

        # 若一组都算不出来，再把警告作为错误抛上去
        if not flange_pressure_info:
            return None, warn_msg or "请完善接管法兰材料信息"

        return flange_pressure_info, warn_msg

    except Exception as e:
        traceback.format_exc()
        return None, f"计算最小压力等级失败: {str(e)}"

# step6.打印提示
def generate_pressure_level_tips(product_id, pipe_belong, pressure_type, pipe_id=None,pipe_code=None):
    """
    按要求生成压力等级提示：
    - 如果有1~2组通过，显示通过组和未通过组的不同提示
    - 如果三组全部通过，显示三条通过提示
    - 如果三组全部未通过，显示三条未通过提示
     统一句式：
      通过组：  管口代号为**的接管法兰材料类型为**，牌号为**时，适用最小压力等级为**
      未通过组：管口代号为**的接管法兰材料类型为**，牌号为**时，未查询到其适用的最小压力等级！
    """
    try:
        flange_info, error = get_minimum_pressure_level_for_flanges(product_id, pipe_belong, pressure_type, pipe_id, pipe_code)

        # 只有“材料信息不完整”这类错误才直接返回；其他错误（如：部分接管法兰无类别）如果同时有部分成功结果，不要吞掉成功的部分
        if not flange_info:
            if error:
                # 检查是否是材料信息不完整的错误
                if "请完善接管法兰材料信息" in error:
                    return error  # 直接返回原始错误信息
                else:
                    return error  # 无任何成功结果时，再作为失败提示
            # 没有结果也没有错误提示
            return "未找到接管法兰材料信息"

        # 去重：相同材料类型、牌号和最小压力等级的只显示一次
        unique_tips = {}
        for flange in flange_info:
            key = f"{flange['material_type']}_{flange['material_grade']}_{flange['min_pressure_level']}"
            if key not in unique_tips:
                unique_tips[key] = flange

        # 生成提示信息
        tips = []
        prefix = f"管口代号为 {pipe_code} 的" if pipe_code else ""
        for flange in unique_tips.values():
            tip = f"{prefix}接管法兰材料类型为 {flange['material_type']}，牌号为 {flange['material_grade']} 时，适用最小压力等级为 {flange['min_pressure_level']}。"
            tips.append(tip)

        # 如果有未通过的警告（warn_msg 已经是逐条拼好的失败提示），拼接在后面
        result = " ".join(tips)

        if error:
            result = f"{result} {error}"

        return result

    except Exception as e:
        # 添加更详细的错误信息
        error_detail = traceback.format_exc()
        # print(f"DEBUG: 异常发生: {str(e)}\n{error_detail}")
        return f"{str(e)}\n详细错误:\n{error_detail}"