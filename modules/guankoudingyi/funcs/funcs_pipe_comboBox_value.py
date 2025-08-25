from PyQt5.QtWidgets import (
    QMessageBox, QComboBox, QTableWidgetItem, 
    QStyledItemDelegate, QStyleOptionComboBox, QStyle,
    QApplication, QLineEdit
)
from PyQt5.QtCore import Qt, QEvent, QRect, QObject
from modules.guankoudingyi.db_cnt import get_connection
import pymysql.cursors

from modules.guankoudingyi.obtain_product_type_version import get_product_type_and_version
from modules.guankoudingyi.funcs.pipe_get_units_types import get_unit_types_from_db, get_current_unit_types_from_ui

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

    def setItems(self, items):
        """设置下拉框的选项"""
        self.items = items

    def createEditor(self, parent, option, index):
        """创建编辑器（下拉框）"""
        editor = QComboBox(parent)
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

        return editor

    def setEditorData(self, editor, index):
        """设置编辑器的数据"""
        value = index.model().data(index, Qt.EditRole) or ""
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
        """事件过滤器，用于实现第一次按键覆盖整体内容"""
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
        12: ["默认", "居中"],  # 轴向定位距离(✅ 可编辑下拉)
        16: ["默认"],         # 外伸高度(✅ 可编辑下拉)
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
            delegate.setItems(["默认"])
            table.setItemDelegateForColumn(column, delegate)
            stats_widget.pipe_column_delegates[column] = delegate

            # 初始化空单元格为"默认"
            for r in range(table.rowCount() - 1):
                item = table.item(r, column)
                # ✅ 只有当当前单元格为空时才设置默认
                if not item or not item.text().strip():
                    new_item = QTableWidgetItem("默认")
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
        # 获取公称尺寸选项
        size_options = get_nominal_size_options(stats_widget.product_id, stats_widget)
        delegate = stats_widget.pipe_column_delegates[column]
        delegate.setItems(size_options if size_options else ["None"])
        table.editItem(table.item(row, column))
        return

    # 其它 5/6/7/8 列逻辑（移除公称尺寸的筛选）
    target_fields = {5: "法兰标准", 6: "压力等级", 7: "法兰型式", 8: "密封面型式"}
    current_field = target_fields.get(column)
    
    if not current_field:
        return

    filters = {}
    for col_other, field in target_fields.items():
        if col_other != column:
            item = table.item(row, col_other)
            if item and item.text().strip():
                filters[field] = item.text().strip()

    unit_types = get_unit_types_from_db(stats_widget.product_id)
    pressure_type, _, _ = get_standard_flange_pressure_level_default_value(stats_widget.product_id, stats_widget)
    options = get_filtered_pipe_options(current_field, filters, unit_types, pressure_type)
    delegate = stats_widget.pipe_column_delegates[column]
    delegate.setItems(options if options else ["None"])
    table.editItem(table.item(row, column))

    # ✅ 新增：记录点击单元格的初始值
    item = table.item(row, column)
    stats_widget.original_cell_value = item.text().strip() if item else ""

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
    try:
        if "管箱" in pipe_belong:
            param_field = '管程数值'
        elif "壳体" in pipe_belong:
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
            return False, "未获取到公称直径，须先至条件输入填写公称直径并保存"
        return True, float(result[param_field])
    except Exception as e:
        return False, f"数据库错误: {str(e)}"
    finally:
        cursor and cursor.close()
        conn and conn.close()

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
    验证外伸高度是否有效。可为"默认"，否则不能小于公称直径的一半。
    如果 emit_error=False，不弹窗，只返回错误信息
    """
    try:
        if not height_text or height_text.strip() == "":
            return True, "默认"
        if height_text.strip() == "默认":
            return True, "默认"

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
        return False, "请输入有效数字或“默认”"

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

    # ✅ 仅处理当前点击编辑的单元格
    if getattr(stats_widget, 'current_editing_cell', None) != (row, column):
        return


    table = stats_widget.tableWidget_pipe
    item = table.item(row, column)
    
    if not item:
        return
    ##########################
    # 检查是否是最后一行
    is_last_row = (row == table.rowCount() - 1)
    
    # 检查该行是否有管口代号（第1列，索引为1）
    pipe_code_item = table.item(row, 1)
    has_pipe_code = pipe_code_item.text().strip() != ""
    
    # 如果是最后一行且没有管口代号，不设置默认值
    if is_last_row and not has_pipe_code:
        return
    ##########################
    # 验证轴向夹角
    if column == 13:  # 轴向夹角列
        # 清除编辑状态标记
        stats_widget.current_editing_cell = None
        valid, result = validate_axial_angle(item.text())
        if not valid:
            stats_widget.line_tip.setText(result)
            stats_widget.line_tip.setStyleSheet("color: red;")
            # 获取默认值
            _, default_value = validate_axial_angle("")
            item.setText(str(default_value))
        else:
            item.setText(str(result))
            # 🚩 新增逻辑：若偏心距 ≠ 0，则清空偏心距并弹窗
            ecc_item = table.item(row, 15)
            if ecc_item and ecc_item.text().strip() not in ["", "0", "0.0"]:
                stats_widget.suppress_cell_change = True
                ecc_item.setText("0.0")
                # save_cell_change_to_db(stats_widget, row, 15, product_id)
                stats_widget.suppress_cell_change = False
                QMessageBox.warning(
                    stats_widget,
                    "校验冲突",
                    "因轴向夹角和偏心距被同时赋值，基于GB/T 150规则无法对此管口进行强度校核"
                )
    
    # 验证周向方位
    elif column == 14:  # 周向方位列
        # 清除编辑状态标记
        stats_widget.current_editing_cell = None
        # 获取管口功能
        function_column = 2  # "管口功能"列的索引为2
        function_item = table.item(row, function_column)
        pipe_function = ""
        if function_item:
            pipe_function = function_item.text().strip()
        
        valid, result = validate_circumferential_position(item.text(), pipe_function)
        if not valid:
            stats_widget.line_tip.setText(result)
            stats_widget.line_tip.setStyleSheet("color: red;")
            # 获取默认值
            _, default_value = validate_circumferential_position("", pipe_function)
            item.setText(str(default_value))
        else:
            item.setText(str(result))

    # 验证偏心距
    # 偏心距验证（第15列）
    elif column == 15:
        # 清除编辑状态标记
        stats_widget.current_editing_cell = None
        belong_item = table.item(row, 10)
        pipe_belong = belong_item.text().strip() if belong_item else ""
        valid, result = validate_eccentricity(item.text(), product_id, pipe_belong, emit_error=False)

        if not valid:
            stats_widget.line_tip.setStyleSheet("color: red;")
            stats_widget.line_tip.setText(f"{result}")
            _, default_value = validate_eccentricity("", product_id, pipe_belong, emit_error=False)
            # table.blockSignals(True)
            stats_widget.suppress_cell_change = True
            item.setText(str(default_value))
            stats_widget.suppress_cell_change = False
            # table.blockSignals(False)
        else:
            table.blockSignals(True)
            item.setText(str(result))
            table.blockSignals(False)
            # 🚩 新增逻辑：若轴向夹角 ≠ 0，则清空轴向夹角并弹窗
            angle_item = table.item(row, 13)
            if angle_item and angle_item.text().strip() not in ["", "0", "0.0"]:
                stats_widget.suppress_cell_change = True
                angle_item.setText("0.0")
                # save_cell_change_to_db(stats_widget, row, 13, product_id)
                stats_widget.suppress_cell_change = False
                QMessageBox.warning(
                    stats_widget,
                    "校验冲突",
                    "因轴向夹角和偏心距被同时赋值，基于GB/T 150规则无法对此管口进行强度校核"
                )


    # 外伸高度验证（第16列）
    elif column == 16:
        # 清除编辑状态标记
        stats_widget.current_editing_cell = None
        belong_item = table.item(row, 10)
        pipe_belong = belong_item.text().strip() if belong_item else ""

        # if not pipe_belong and not (is_last_row and not has_pipe_code):
        #     return

        valid, result = validate_extension_height(item.text(), product_id, pipe_belong, emit_error=False)
        if not valid:
            stats_widget.line_tip.setStyleSheet("color: red;")
            stats_widget.line_tip.setText(f"{result}")
            _, default_value = validate_extension_height("", product_id, pipe_belong, emit_error=False)
            table.blockSignals(True)
            item.setText(str(default_value))
            table.blockSignals(False)
        else:
            table.blockSignals(True)
            item.setText(str(result))
            table.blockSignals(False)


    # 验证轴向定位距离
    elif column == 12:  # 轴向定位距离列
        # 清除编辑状态标记
        stats_widget.current_editing_cell = None
        # 获取管口功能
        function_item = table.item(row, 2)  # 2是管口功能列的索引
        pipe_function = function_item.text().strip() if function_item else ""

        # 获取当前输入值
        input_value = item.text().strip()

        # 验证输入值
        if input_value in ["默认", "居中"]:
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
                    item.setText("默认")

    # "管口所属元件"列
    elif column == 10:
        # 清除编辑状态标记
        stats_widget.current_editing_cell = None
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

        # 更新旧值
        if not hasattr(stats_widget, 'pipe_belong_old_values'):
            stats_widget.pipe_belong_old_values = {}
        stats_widget.pipe_belong_old_values[row] = new_value

    # 验证压力等级（第6列）
    elif column == 6:
        # # 限定只有点击并编辑该单元格才验证
        # if getattr(stats_widget, 'current_editing_cell', None) != (row, column):
        #     return  # 不是主动点击引发的编辑，跳过验证
        # stats_widget.current_editing_cell = None  # 重置为 None，避免下次误触发

        # 限定只有点击并编辑该单元格才验证
        if getattr(stats_widget, 'current_editing_cell', None) != (row, column):
            return

        # 获取当前值和之前点击时的原始值
        new_value = item.text().strip()
        old_value = getattr(stats_widget, 'original_cell_value', "")

        # 如果值没变，则认为无需验证，直接返回并清除状态
        if new_value == old_value:
            stats_widget.current_editing_cell = None
            stats_widget.original_cell_value = None
            return

        # 清除记录，防止下次误触发
        stats_widget.current_editing_cell = None
        stats_widget.original_cell_value = None

        # 获取第六列的压力等级
        pressure_level_text = item.text().strip()
        if not pressure_level_text:
            return

        # 提前尝试获取类别号，如果失败就跳过后续所有验证
        # 获取 pressure_type：优先使用界面监听值，其次数据库，最后默认 Class
        pressure_type = getattr(stats_widget, "current_pressure_type", None)

        if not pressure_type:
            unit_types = get_unit_types_from_db(product_id)
            pressure_type = unit_types.get("公称压力类型", "Class")

        # 提前尝试获取类别号，如果失败就跳过后续所有验证
        category_no, cat_err = get_material_category_number_by_product(product_id, pressure_type)
        if category_no is None:
            if not hasattr(stats_widget, "pressure_material_warning_shown"):
                QMessageBox.warning(stats_widget, "验证提示", cat_err or "未找到接管法兰的材料信息，跳过压力等级验证")
                stats_widget.pressure_material_warning_shown = True
            return  # 跳过整个验证过程

        # 获取第十列的管口所属元件
        belong_item = table.item(row, 10)
        pipe_belong = belong_item.text().strip() if belong_item else None
        if not pipe_belong:
            # 弹窗提示
            QMessageBox.warning(stats_widget, "验证错误", "请先选择管口所属元件")
            # 清空当前单元格的值
            table.blockSignals(True)  # 防止触发二次cellChanged
            item.setText("")  # 清空值
            table.blockSignals(False)
            return

        # 获取最大工作温度
        max_temp, temp_err = get_max_working_temperature_by_belong(product_id, pipe_belong)
        if temp_err:
            QMessageBox.warning(stats_widget, "验证错误", temp_err)
            return

        # 将最大工作温度转换为查询温度（若小于等于38，则统一按38处理）
        if max_temp <= 38:
            query_temp = 38
        else:
            query_temp = max_temp

        success, message = check_pressure_limit(product_id, pipe_belong, pressure_level_text, query_temp, pressure_type)

        # 其它错误继续提示
        if not success:
            QMessageBox.warning(stats_widget, "压力等级验证失败", message)


"""对压力等级列进行验证的步骤，所调用的方法"""
# step1.确定类别号
def get_material_category_number_by_product(product_id, pressure_type):
    """
    从产品设计活动表_管口零件材料表中获取指定产品ID的“接管法兰”零件的材料类型和材料牌号，
    再去元件库中的材料温压值类别表中查找对应的类别号。
    """
    conn_design = None
    conn_component = None
    try:
        # === 第一步：查产品设计活动库中的“接管法兰”零件材料 ===
        conn_design = get_connection(**db_config_2)
        cursor_design = conn_design.cursor(pymysql.cursors.DictCursor)

        cursor_design.execute("""
            SELECT 材料类型, 材料牌号
            FROM 产品设计活动表_管口零件材料表
            WHERE 产品ID = %s AND 零件名称 = '接管法兰'
            LIMIT 1
        """, (product_id,))
        material_result = cursor_design.fetchone()

        if not material_result:
            return None, "未找到接管法兰的材料信息"

        material_type = material_result["材料类型"]
        material_grade = material_result["材料牌号"]

        # ✅ 映射特殊材料类型
        type_mapping = {
            "Q235 系列钢板": "钢板"
        }
        material_type_mapped = type_mapping.get(material_type, material_type)

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

        if not category_result:
            return None, f"未在元件库中找到材料类型={material_type_mapped} 材料牌号={material_grade} 公称压力类型={pressure_type}的类别号"

        return category_result["类别号"], None

    except Exception as e:
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
    根据产品ID和管口所属元件字段，获取“工作温度（入口）”与“工作温度（出口）”中的最大温度值。
    :param product_id: 产品ID
    :param pipe_belong: 管口所属元件（如“管箱圆筒”或“壳体封头”）
    """
    conn = None
    cursor = None
    try:
        if "管箱" in pipe_belong:
            value_field = "管程数值"
        elif "壳体" in pipe_belong:
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
    根据产品ID和管口所属元件字段（管箱/壳体）优先获取“最高允许工作压力”，如果获取不到则获取“设计压力*”
    """
    conn = None
    cursor = None
    try:
        if "管箱" in pipe_belong:
            value_field = "管程数值"
        elif "壳体" in pipe_belong:
            value_field = "壳程数值"
        else:
            return None, "无效的管口所属元件字段"

        conn = get_connection(**db_config_2)
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 优先尝试获取“最高允许工作压力”
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

        # 如果获取不到，再获取“设计压力*”
        cursor.execute(f"""
            SELECT `{value_field}` AS val
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s AND 参数名称 = '设计压力*'
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
# step5. 用于检查压力等级与温度对应关系
def check_pressure_limit(product_id, pipe_belong, pressure_level, query_temp, pressure_type):
    """
    校验压力等级在给定温度下是否满足要求，返回 (bool, message)
    """
    #确定类别号
    category_no, cat_err = get_material_category_number_by_product(product_id, pressure_type)
    print(category_no)
    if category_no is None:
        return False, "未找到接管法兰的材料类型和牌号，无法校验压力等级"
    if cat_err:
        return False, cat_err

    try:
        conn = get_connection(**db_config_1)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT 工作温度, 最大允许工作压力
            FROM 温压值表
            WHERE 类别号 = %s AND 压力等级 = %s
            ORDER BY 工作温度 ASC
        """, (category_no, pressure_level))
        temp_rows = cursor.fetchall()

        if not temp_rows:
            return False, "未找到该类别号与压力等级下的温压数据"

        temperatures = [float(row["工作温度"]) for row in temp_rows]
        pressures = [float(row["最大允许工作压力"]) for row in temp_rows]

        if query_temp in temperatures:
            max_allow_pressure = pressures[temperatures.index(query_temp)]
        elif query_temp > max(temperatures):
            return False, f"工作温度 {query_temp}° 超过温压表中最大允许范围"
        else:
            smaller = max([t for t in temperatures if t < query_temp])
            larger = min([t for t in temperatures if t > query_temp])
            p1 = pressures[temperatures.index(smaller)]
            p2 = pressures[temperatures.index(larger)]
            slope = (p2 - p1) / (larger - smaller)
            max_allow_pressure = p1 + slope * (query_temp - smaller)

        work_pressure, wp_err = get_working_pressure_by_belong(product_id, pipe_belong)
        if wp_err:
            return False, f"获取工作压力失败：{wp_err}"

        # 🚩单位换算：bar → MPa
        max_allow_pressure_mpa = max_allow_pressure * 0.1  # 将 bar 转为 MPa
        if work_pressure > max_allow_pressure_mpa:
            return False, f"当前设计压力 {work_pressure}MPa 超过管法兰用材料最大允许工作压力 {max_allow_pressure_mpa:.1f}MPa，请调整法兰压力等级"

        return True, "压力校验通过"

    except Exception as e:
        return False, f"查询温压数据失败: {str(e)}"
    finally:
        try:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
        except:
            pass





