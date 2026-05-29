from PyQt5.QtWidgets import (
    QMessageBox, QComboBox, QTableWidgetItem,
    QStyledItemDelegate, QStyleOptionComboBox, QStyle,
    QApplication, QLineEdit, QToolTip, QDialog
)
from PyQt5.QtCore import Qt, QEvent, QRect, QObject, QPoint
from PyQt5.QtGui import QCursor, QBrush, QColor
from PyQt5 import uic
import os
import math
from modules.guankoudingyi.db_cnt import get_connection, db_config_1, db_config_2
import pymysql.cursors
import traceback

from modules.guankoudingyi.obtain_product_type_version import get_product_type_and_version
from modules.guankoudingyi.funcs.pipe_get_units_types import get_unit_types_from_db, get_current_unit_types_from_ui
from modules.guankoudingyi.funcs.funcs_pipe_Load import init_pipe_openingload_dialog
from PyQt5.QtCore import QTimer


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

    def helpEvent(self, event, view, option, index):
        """处理帮助事件，只在单元格内容显示不全时显示悬浮提示"""
        if event.type() == QEvent.ToolTip:
            # 获取单元格的文本内容
            text = index.data(Qt.DisplayRole)
            if text:
                text_str = str(text)

                # 计算文本实际宽度
                font_metrics = view.fontMetrics()
                text_width = font_metrics.horizontalAdvance(text_str)

                # 获取单元格的显示区域宽度
                cell_width = option.rect.width()

                # 只有当文本宽度超过单元格宽度时才显示悬浮提示
                if text_width > cell_width - 10:  # 留10像素余量
                    QToolTip.showText(event.globalPos(), text_str, view)
                else:
                    QToolTip.hideText()
            else:
                QToolTip.hideText()
            return True
        return super().helpEvent(event, view, option, index)

    def eventFilter(self, editor, event):
        """事件过滤器，用于实现第一次按键覆盖整体内容、处理滚轮事件"""

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
        16: ["程序推荐"],  # 外伸高度(✅ 可编辑下拉)
    }
    for col, options in static_columns.items():
        # ✅ 关键修改：启用第一次按键覆盖功能
        delegate = ComboBoxDelegate(table, editable=True, overwrite_on_first_key=True)
        delegate.setItems(options)
        delegate.setParent(table)
        table.setItemDelegateForColumn(col, delegate)
        stats_widget.pipe_column_delegates[col] = delegate

    # 动态列：初始化空代理，后续在点击时更新选项
    dynamic_columns = [4, 5, 6, 7, 8, 9, 10, 11, 17]
    for col in dynamic_columns:
        # 🚩 关键修改：列9初始化为不可编辑
        editable = False
        delegate = ComboBoxDelegate(table, editable=editable)
        delegate.setItems([])
        delegate.setParent(table)
        table.setItemDelegateForColumn(col, delegate)
        stats_widget.pipe_column_delegates[col] = delegate

"""获取法兰标准的默认值和压力等级的默认值"""
def get_standard_flange_pressure_level_default_value(product_id, stats_widget=None):
    """
    获取法兰标准、压力等级和公称尺寸的默认值：
    - 优先从界面组件获取公称压力类型，如果获取不到则从数据库获取
    - 根据公称压力类型返回：
      - 默认法兰标准和默认压力等级（不用于最后一行）
      - 公称尺寸设定为空
    :param product_id: 产品ID
    :param stats_widget: Stats类实例，用于从界面获取单位类型
    :return: (pressure_type: str, default_standard: str, default_level: str, default_nominal_size: str)
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
        return pressure_type, "", "", ""

    # 设置默认值
    if pressure_type == "Class":
        default_standard = "HG/T 20615-2009"
        default_level = "150"
    else:  # PN
        default_standard = "HG/T 20592(A)-2009"
        default_level = "10"

    # 公称尺寸设定为空
    default_nominal_size = ""

    return pressure_type, default_standard, default_level, default_nominal_size

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

"""根据压力类型获取法兰标准的下拉框内容"""
def get_flange_standard_options_by_pressure_type(pressure_type):
    """
    根据压力类型从公称压力类型标准对应表中获取法兰标准选项
    :param pressure_type: 压力类型，如 "Class" 或 "PN"
    :return: 法兰标准选项列表
    """
    try:
        conn = get_connection(**db_config_1)
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        sql = "SELECT DISTINCT `法兰标准` FROM `公称压力类型标准对应表` WHERE `公称压力类型` = %s"
        cursor.execute(sql, (pressure_type,))
        results = cursor.fetchall()

        options = []
        for row in results:
            standard = row.get('法兰标准')
            if standard and str(standard).strip():
                options.append(str(standard).strip())

        return options

    except Exception as e:
        print(f"[ERROR] 获取法兰标准选项失败: {str(e)}")
        # 如果数据库查询失败，返回默认选项
        if pressure_type == "Class":
            return ["HG/T 20615-2009", "HG/T 20623-2009(A)", "HG/T 20623-2009(B)","SH/T 3406-2022","SH/T 3406-2022(A)","SH/T 3406-2022(B)"]
        elif pressure_type == "PN":
            return ["HG/T 20592-2009"]
        else:
            return []
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

"""处理Class压力等级下法兰标准切换时设置公称尺寸、压力等级、法兰型式和密封面型式"""
def handle_class_flange_standard_change(stats_widget, row, new_standard, old_standard=None):
    """
    当压力等级为Class且法兰标准在三个固定值之间切换时，
    自动设置法兰型式为WN，密封面型式为RF
    :param stats_widget: Stats类实例
    :param row: 当前行号
    :param new_standard: 新的法兰标准值
    :param old_standard: 旧的法兰标准值
    """
    try:
        table = stats_widget.tableWidget_pipe

        # 从界面组件获取当前的压力类型
        current_unit_types = get_current_unit_types_from_ui(stats_widget)
        pressure_type = current_unit_types.get("公称压力类型", "Class")

        # 检查新标准是否在当前压力类型的标准中
        valid_standards = get_flange_standard_options_by_pressure_type(pressure_type)
        if new_standard not in valid_standards:
            return

        # 如果没有传入旧标准值，则从表格中获取
        if old_standard is None:
            current_standard_item = table.item(row, 5)
            current_standard = current_standard_item.text().strip() if current_standard_item else ""
        else:
            current_standard = old_standard


        # 只有当新标准与旧标准(不为空)不同时才执行自动设置
        if new_standard == current_standard or current_standard =="":
            return

        # 检查压力类型是否为Class（只有Class类型才自动设置）
        if pressure_type != "Class":
            return


        # 抑制单元格变化信号，避免触发递归
        try:
            stats_widget.suppress_cell_change = True

            # 获取当前压力等级（第6列）
            pressure_level_item = table.item(row, 6)
            current_pressure_level = pressure_level_item.text().strip() if pressure_level_item else ""

            # 查询新标准下的所有压力等级（Class类型）
            new_standard_pressure_levels = get_pressure_levels_by_standard(new_standard, "Class")

            # 判断当前压力等级是否在新标准下存在
            if current_pressure_level and new_standard_pressure_levels:
                # Class类型下，压力等级单元格就是纯数字字符串，如 "150", "300"
                try:
                    current_level_value = int(current_pressure_level)
                    # 检查当前压力等级是否在新标准下存在
                    if current_level_value in new_standard_pressure_levels:
                        # 保留当前压力等级
                        if not pressure_level_item:
                            pressure_level_item = QTableWidgetItem()
                            table.setItem(row, 6, pressure_level_item)
                        pressure_level_item.setText(current_pressure_level)
                        pressure_level_item.setTextAlignment(Qt.AlignCenter)
                    else:
                        # 当前压力等级在新标准下不存在，使用推荐逻辑
                        # 获取管口相关信息
                        product_id = stats_widget.product_id
                        pipe_belong_item = table.item(row, 10)  # 第10列：管口所属元件
                        pipe_belong = pipe_belong_item.text().strip() if pipe_belong_item else ""
                        pipe_code_item = table.item(row, 1)  # 第1列：管口代号
                        pipe_code = pipe_code_item.text().strip() if pipe_code_item else ""

                        # 调用推荐逻辑获取最小压力等级
                        recommended_level = None
                        if product_id and pipe_belong:
                            flange_info, _ = get_minimum_pressure_level_for_flanges(
                                product_id,
                                pipe_belong,
                                "Class",
                                pipe_id=None,
                                pipe_code=pipe_code,
                                flange_std=new_standard
                            )

                            if flange_info and len(flange_info) > 0:
                                # 从多个推荐值中提取最高的压力等级
                                pressure_level_values = []
                                for info in flange_info:
                                    min_level_str = info.get('min_pressure_level', '')
                                    # 格式为 "Class 150"，提取数字部分
                                    if min_level_str.startswith("Class "):
                                        try:
                                            level_value = int(min_level_str.replace("Class ", "").strip())
                                            pressure_level_values.append(level_value)
                                        except (ValueError, AttributeError):
                                            continue

                                if pressure_level_values:
                                    # 取最高的压力等级
                                    recommended_level = max(pressure_level_values)

                        # 如果未查询到推荐值，则设为300
                        if recommended_level is None:
                            recommended_level = 300

                        # 设置推荐的压力等级
                        if not pressure_level_item:
                            pressure_level_item = QTableWidgetItem()
                            table.setItem(row, 6, pressure_level_item)
                        pressure_level_item.setText(str(recommended_level))
                        pressure_level_item.setTextAlignment(Qt.AlignCenter)
                except (ValueError, TypeError):
                    # 如果当前压力等级不是有效数字，置空
                    if not pressure_level_item:
                        pressure_level_item = QTableWidgetItem()
                        table.setItem(row, 6, pressure_level_item)
                    pressure_level_item.setText("")
                    pressure_level_item.setTextAlignment(Qt.AlignCenter)
            else:
                # 如果没有当前压力等级或新标准下没有压力等级，置空
                if not pressure_level_item:
                    pressure_level_item = QTableWidgetItem()
                    table.setItem(row, 6, pressure_level_item)
                pressure_level_item.setText("")
                pressure_level_item.setTextAlignment(Qt.AlignCenter)

            # 验证法兰型式（第7列）
            flange_type_item = table.item(row, 7)
            current_flange_type = flange_type_item.text().strip() if flange_type_item else ""
            current_pressure_level = pressure_level_item.text().strip() if pressure_level_item else ""

            if not current_pressure_level:
                # 若压力等级为空，则法兰型式置空
                if not flange_type_item:
                    flange_type_item = QTableWidgetItem()
                    table.setItem(row, 7, flange_type_item)
                flange_type_item.setText("")
                flange_type_item.setTextAlignment(Qt.AlignCenter)
            elif current_flange_type:
                # 如果压力等级不为空且法兰型式不为空，验证法兰型式在新标准下是否存在
                from modules.guankoudingyi.funcs.funcs_pipe_data_in_out import validate_flange_form_by_database
                validated_flange_type, _ = validate_flange_form_by_database(
                    current_flange_type,
                    new_standard,
                    current_pressure_level,
                    "Class",
                    row
                )
                if not flange_type_item:
                    flange_type_item = QTableWidgetItem()
                    table.setItem(row, 7, flange_type_item)
                flange_type_item.setText(validated_flange_type)
                flange_type_item.setTextAlignment(Qt.AlignCenter)
            else:
                # 如果压力等级不为空但法兰型式为空，保持为空
                if not flange_type_item:
                    flange_type_item = QTableWidgetItem()
                    table.setItem(row, 7, flange_type_item)
                flange_type_item.setText("")
                flange_type_item.setTextAlignment(Qt.AlignCenter)

            # 验证密封面型式（第8列）
            seal_type_item = table.item(row, 8)
            current_seal_type = seal_type_item.text().strip() if seal_type_item else ""
            # 获取验证后的压力等级和法兰型式
            validated_pressure_level = pressure_level_item.text().strip() if pressure_level_item else ""
            validated_flange_type = flange_type_item.text().strip() if flange_type_item else ""

            if not validated_pressure_level or not validated_flange_type:
                # 若压力等级为空或法兰型式为空，则密封面型式置空
                if not seal_type_item:
                    seal_type_item = QTableWidgetItem()
                    table.setItem(row, 8, seal_type_item)
                seal_type_item.setText("")
                seal_type_item.setTextAlignment(Qt.AlignCenter)
            elif current_seal_type:
                # 如果压力等级和法兰型式都不为空且密封面型式不为空，验证密封面型式在新标准下是否存在
                from modules.guankoudingyi.funcs.funcs_pipe_data_in_out import validate_sealing_face_form_by_database
                validated_seal_type, _ = validate_sealing_face_form_by_database(
                    current_seal_type,
                    new_standard,
                    validated_pressure_level,
                    "Class",
                    validated_flange_type,
                    row
                )
                if not seal_type_item:
                    seal_type_item = QTableWidgetItem()
                    table.setItem(row, 8, seal_type_item)
                seal_type_item.setText(validated_seal_type)
                seal_type_item.setTextAlignment(Qt.AlignCenter)
            else:
                # 如果压力等级和法兰型式都不为空但密封面型式为空，保持为空
                if not seal_type_item:
                    seal_type_item = QTableWidgetItem()
                    table.setItem(row, 8, seal_type_item)
                seal_type_item.setText("")
                seal_type_item.setTextAlignment(Qt.AlignCenter)

            # 处理公称尺寸列（第4列）
            # 小管口标准
            small_pipe_standards = ["HG/T 20615-2009", "SH/T 3406-2022"]
            # 大管口标准
            large_pipe_standards = ["HG/T 20623-2009(A)", "HG/T 20623-2009(B)", "SH/T 3406-2022(A)", "SH/T 3406-2022(B)"]

            # 判断旧标准和新标准分别属于小管口还是大管口
            old_is_small = current_standard in small_pipe_standards
            old_is_large = current_standard in large_pipe_standards
            new_is_small = new_standard in small_pipe_standards
            new_is_large = new_standard in large_pipe_standards

            # 如果从小管口切换到大管口，或从大管口切换到小管口，则公称尺寸置空
            # 其他情况（小管口之间切换、大管口之间切换）保留
            nominal_size_item = table.item(row, 4)
            if (old_is_small and new_is_large) or (old_is_large and new_is_small):
                # 小管口与大管口之间的切换，置空
                if not nominal_size_item:
                    nominal_size_item = QTableWidgetItem()
                    table.setItem(row, 4, nominal_size_item)
                nominal_size_item.setText("")
                nominal_size_item.setTextAlignment(Qt.AlignCenter)




        finally:
            stats_widget.suppress_cell_change = False

    except Exception as e:
        print(f"[ERROR] 处理Class法兰标准切换失败: {str(e)}")

"""查询指定标准下的所有压力等级"""
def get_pressure_levels_by_standard(standard, pressure_type):
    """
    查询元件库"管口压力等级表"，获取指定标准和公称压力类型下的所有压力等级
    :param standard: 法兰标准，如 'HG/T 20592-2009'
    :param pressure_type: 压力类型，'Class' 或 'PN'
    :return: 压力等级数值列表，如 [150, 300, 600] 或 [2.5, 6, 10]
    """
    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config_1)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT DISTINCT 压力等级
            FROM 管口压力等级表
            WHERE 标准=%s AND 公称压力类型=%s
        """, (standard, pressure_type))
        rows = cursor.fetchall()
        if not rows:
            return []

        levels = []
        for r in rows:
            try:
                if pressure_type == "PN":
                    lv = float(r["压力等级"])
                else:
                    lv = int(r["压力等级"])
                levels.append(lv)
            except (ValueError, TypeError):
                continue

        levels.sort()
        return levels

    except Exception as e:
        print(f"[ERROR] 查询压力等级失败: {str(e)}")
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

"""获取管口附件列的下拉框内容"""
def get_pipe_attachment_options():
    """
    从元件库的管口附件表中获取"附件类型"列所有非空值
    :return: 附件类型选项列表
    """
    try:
        conn = get_connection(**db_config_1)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("SELECT DISTINCT 附件类型 FROM 管口附件表 WHERE 附件类型 IS NOT NULL AND 附件类型 != ''")
        results = cursor.fetchall()
        options = [str(row["附件类型"]).strip() for row in results if row.get("附件类型")]
        return options
    except Exception as e:
        QMessageBox.warning(None, "错误", f"获取管口附件类型失败: {str(e)}")
        return []
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

"""获取公称尺寸列的下拉框内容"""
def get_nominal_size_options(product_id, stats_widget=None, flange_standard=None):
    """
    根据界面选择或产品ID获取公称尺寸类型（DN或NPS），然后从元件库的公称尺寸表中获取对应列的内容
    根据法兰标准进行筛选：
    - HG/T 20615-2009、HG/T 20592-2009: 只显示DN≤600（NPS≤24）
    - HG/T 20623-2009(A)、HG/T 20623-2009(B): 只显示DN>600（NPS>24）
    :param product_id: 产品ID
    :param stats_widget: Stats类实例，用于从界面获取单位类型
    :param flange_standard: 法兰标准，用于筛选公称尺寸范围
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

        # 构建基础查询
        base_sql = f"""
            SELECT DISTINCT `{column_name}` 
            FROM 公称尺寸表 
            WHERE `{column_name}` IS NOT NULL 
        """

        # 根据法兰标准添加筛选条件
        if flange_standard:
            if flange_standard in ["HG/T 20615-2009","SH/T 3406-2022"]:
                # DN≤600 或 NPS≤24
                if size_type == "DN":
                    base_sql += " AND CAST(`DN` AS UNSIGNED) <= 600"
                elif size_type == "NPS":
                    base_sql += " AND CAST(`NPS` AS UNSIGNED) <= 24"
            elif flange_standard in ["HG/T 20623-2009(A)", "HG/T 20623-2009(B)","SH/T 3406-2022(A)","SH/T 3406-2022(B)"]:
                # DN>600 或 NPS>24
                if size_type == "DN":
                    base_sql += " AND CAST(`DN` AS UNSIGNED) > 600"
                elif size_type == "NPS":
                    base_sql += " AND CAST(`NPS` AS UNSIGNED) > 24"

        base_sql += f" ORDER BY CAST(`{column_name}` AS UNSIGNED) ASC, `{column_name}` ASC"

        cursor.execute(base_sql)
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


"""获取当前行管口代号"""
def get_pipe_code_by_row(stats_widget, row):
    """
    根据行号获取管口代号
    :param stats_widget: Stats类实例
    :param row: 表格行号
    :return: 管口代号字符串，如果不存在则返回None
    """
    try:
        table = stats_widget.tableWidget_pipe
        if not table:
            return None

        # 管口代号在第1列（索引为1）
        pipe_code_item = table.item(row, 1)
        if pipe_code_item:
            pipe_code = pipe_code_item.text().strip()
            return pipe_code if pipe_code else None
        return None
    except Exception as e:
        print(f"[ERROR] 获取管口代号失败: {e}")
        return None


"""显示管口载荷设置对话框"""
def _show_pipe_openingload_dialog(stats_widget, row):
    """
    显示管口载荷设置对话框（pipe_openingload.ui）
    :param stats_widget: Stats类实例
    :param row: 当前行号
    """
    try:
        # === 0) 先校验是否已保存到产品设计活动表_管口表 ===
        product_id = getattr(stats_widget, "product_id", None)
        # 运行期隐藏管口ID（界面添加新行时分配）优先使用
        pipe_id = None
        if hasattr(stats_widget, "row_hidden_pipe_id"):
            pipe_id = stats_widget.row_hidden_pipe_id.get(row)

        # 若没有隐藏ID，尝试用管口代号查询
        pipe_code = None
        table = getattr(stats_widget, "tableWidget_pipe", None)
        if table:
            code_item = table.item(row, 1)
            pipe_code = code_item.text().strip() if code_item else None

        if not product_id:
            QMessageBox.warning(stats_widget, "提示", "请先选择产品并保存当前管口。")
            return

        # 连接产品设计活动库，检查记录是否存在
        conn = None
        cursor = None
        try:
            conn = get_connection(**db_config_2)
            cursor = conn.cursor(pymysql.cursors.DictCursor)

            if pipe_id:
                cursor.execute(
                    "SELECT 1 FROM 产品设计活动表_管口表 WHERE 产品ID=%s AND 管口ID=%s LIMIT 1",
                    (product_id, pipe_id),
                )
            elif pipe_code:
                cursor.execute(
                    "SELECT 1 FROM 产品设计活动表_管口表 WHERE 产品ID=%s AND 管口代号=%s LIMIT 1",
                    (product_id, pipe_code),
                )
            else:
                QMessageBox.warning(stats_widget, "提示", "请先填写并保存管口代号。")
                return

            exists = cursor.fetchone()
            if not exists:
                QMessageBox.warning(stats_widget, "提示", "未找到该管口信息，请先保存当前管口。")
                return
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

        # 创建对话框
        dialog = QDialog(stats_widget)

        # 获取UI文件路径（从funcs目录回到guankoudingyi目录）
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ui_path = os.path.join(current_dir, "ui", "pipe_openingload.ui")

        # 加载UI文件
        uic.loadUi(ui_path, dialog)

        # 复用上方获取到的 product_id / pipe_id / pipe_code 即可

        # 初始化对话框（调整列宽等，并传递product_id和pipe_id用于加载和保存数据）
        init_pipe_openingload_dialog(dialog, pipe_code, product_id, pipe_id)

        # 设置窗口标题
        dialog.setWindowTitle("局部应力数据输入")

        # 设置窗口标志：使用Dialog标志，移除帮助按钮，添加最小化/最大化按钮
        # 使用Dialog标志确保对话框独立，不会影响父窗口的最小化
        dialog.setWindowFlags(
            Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint
        )


        # 显示对话框（模态）
        dialog.exec_()

    except Exception as e:
        QMessageBox.warning(stats_widget, "错误", f"打开管口载荷设置对话框失败：{str(e)}")
        import traceback
        traceback.print_exc()

"""根据管口所属元件同步列12（及管板时13–15）的锁定状态与显示。"""
def apply_pipe_row_column_locks_by_belong(stats_widget, row):

    table = stats_widget.tableWidget_pipe
    belong_item = table.item(row, 10)
    pipe_belong = belong_item.text().strip() if belong_item else ""

    try:
        stats_widget.suppress_cell_change = True

        if "管板" in pipe_belong:
            item_col12 = table.item(row, 12)
            if not item_col12:
                item_col12 = QTableWidgetItem()
                table.setItem(row, 12, item_col12)
            if item_col12.text().strip() not in ("居中",):
                item_col12.setText("居中")
            item_col12.setTextAlignment(Qt.AlignCenter)
            item_col12.setFlags(Qt.ItemIsEnabled | Qt.ItemIsEditable | Qt.ItemIsSelectable)

            for lock_col in (13, 14, 15):
                lock_item = table.item(row, lock_col)
                if not lock_item:
                    lock_item = QTableWidgetItem()
                    table.setItem(row, lock_col, lock_item)
                lock_item.setText("—")
                lock_item.setTextAlignment(Qt.AlignCenter)
                lock_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

        elif ("封头" in pipe_belong) or ("平盖" in pipe_belong):
            lock_item = table.item(row, 12)
            if not lock_item:
                lock_item = QTableWidgetItem()
                table.setItem(row, 12, lock_item)
            lock_item.setText("—")
            lock_item.setTextAlignment(Qt.AlignCenter)
            lock_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)

            for unlock_col in (13, 14, 15):
                unlock_item = table.item(row, unlock_col)
                if unlock_item:
                    unlock_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsEditable | Qt.ItemIsSelectable)

        else:
            item_col12 = table.item(row, 12)
            if item_col12:
                item_col12.setFlags(Qt.ItemIsEnabled | Qt.ItemIsEditable | Qt.ItemIsSelectable)
                text_now = item_col12.text().strip()
                if text_now in ("", "—"):
                    pipe_function_item = table.item(row, 2)
                    pipe_function = pipe_function_item.text().strip() if pipe_function_item else ""
                    if pipe_function in ["管程入口", "管程出口"]:
                        default_value = "居中"
                    else:
                        default_value = "程序推荐"
                    item_col12.setText(default_value)
                    item_col12.setTextAlignment(Qt.AlignCenter)

            for unlock_col in (13, 14, 15):
                unlock_item = table.item(row, unlock_col)
                if unlock_item:
                    unlock_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsEditable | Qt.ItemIsSelectable)
    finally:
        stats_widget.suppress_cell_change = False


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

    belong_item = table.item(row, 10)
    pipe_belong = belong_item.text().strip() if belong_item else ""

    # 封头/平盖：禁用轴向定位距离（第12列），显示“—”，不进入下拉编辑
    if column == 12 and (("封头" in pipe_belong) or ("平盖" in pipe_belong)):
        try:
            stats_widget.suppress_cell_change = True
            lock_item = table.item(row, column)
            if not lock_item:
                lock_item = QTableWidgetItem()
                table.setItem(row, column, lock_item)
            lock_item.setText("—")
            lock_item.setTextAlignment(Qt.AlignCenter)
            lock_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        finally:
            stats_widget.suppress_cell_change = False
        return

    # ✅ 新增逻辑：单击即进入可编辑下拉
    if column == 12:
        # 根据管口所属元件（第10列）动态调整选项
        belong_item = table.item(row, 10)
        pipe_belong = belong_item.text().strip() if belong_item else ""
        options = ["居中"] if ("管板" in pipe_belong) else ["程序推荐", "居中"]

        delegate = stats_widget.pipe_column_delegates[column]
        delegate.setItems(options)
        table.editItem(table.item(row, column))
        return

    if column == 16:
        delegate = stats_widget.pipe_column_delegates[column]
        table.editItem(table.item(row, column))
        return

    # 管板：禁用 13/14/15；封头/平盖：禁用 12（轴向定位距离）
    if column in (12, 13, 14, 15):
        belong_item = table.item(row, 10)
        pipe_belong = belong_item.text().strip() if belong_item else ""
        lock_cols = False
        if "管板" in pipe_belong:
            lock_cols = True
        elif ("封头" in pipe_belong) or ("平盖" in pipe_belong):
            lock_cols = column == 12

        if lock_cols:
            try:
                stats_widget.suppress_cell_change = True
                lock_item = table.item(row, column)
                if not lock_item:
                    lock_item = QTableWidgetItem()
                    table.setItem(row, column, lock_item)
                lock_item.setText("—")
                lock_item.setTextAlignment(Qt.AlignCenter)
                lock_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            finally:
                stats_widget.suppress_cell_change = False
            return
    # # 管板时禁用 13/14/15 列编辑，设为空并置灰（保留可选中以保证整行高亮不丢失）
    # if column in (13, 14, 15):
    #     belong_item = table.item(row, 10)
    #     pipe_belong = belong_item.text().strip() if belong_item else ""
    #     if "管板" in pipe_belong:
    #         try:
    #             stats_widget.suppress_cell_change = True
    #             lock_item = table.item(row, column)
    #             if not lock_item:
    #                 lock_item = QTableWidgetItem()
    #                 table.setItem(row, column, lock_item)
    #             lock_item.setText("—")  # 置空
    #             lock_item.setTextAlignment(Qt.AlignCenter)
    #             # 只禁止编辑，不禁止选中，避免从“管板”切到其他元件后该列高亮丢失
    #             lock_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
    #
    #
    #
    #         finally:
    #             stats_widget.suppress_cell_change = False
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
        # ✅ 在编辑前保存当前值作为旧值（用于第一次切换时的判断）
        if not hasattr(stats_widget, 'pipe_belong_old_values'):
            stats_widget.pipe_belong_old_values = {}

        # 获取当前单元格的值作为旧值（如果字典中没有保存）
        if row not in stats_widget.pipe_belong_old_values:
            current_item = table.item(row, 10)
            if current_item:
                stats_widget.pipe_belong_old_values[row] = current_item.text().strip()
            else:
                stats_widget.pipe_belong_old_values[row] = ""

        # 获取产品类型和型式
        product_type = getattr(stats_widget, "current_product_type", "")
        product_version = getattr(stats_widget, "current_product_version", "")

        # 获取当前行的管口功能
        pipe_function_item = table.item(row, 2)  # 第2列为管口功能
        pipe_function = pipe_function_item.text().strip() if pipe_function_item else ""
        # 定义版本与对应"管程入口/出口"的管口所属元件选项映射
        version_belong_map = {
            ("NEN",): ["前端管箱平盖", "前端管箱圆筒", "后端管箱圆筒", "后端管箱平盖"],
            ("BEM",): ["前端管箱封头", "前端管箱圆筒", "后端管箱圆筒", "后端管箱封头"],
            ("AEM",): ["前端管箱平盖", "前端管箱圆筒", "后端管箱圆筒", "后端管箱封头"],
            ("NEN(Head)",): ["前端管箱封头", "前端管箱圆筒", "后端管箱圆筒", "后端管箱封头"],
            ("AES", "AEU","AKU"): ["管箱圆筒", "管箱平盖"],
            ("BES", "BEU","BKU"): ["管箱圆筒", "管箱封头"],

        }

        if product_type == "管壳式热交换器":
            # 遍历映射，寻找匹配的版本
            for versions, options in version_belong_map.items():
                if product_version in versions:
                    # 找到匹配版本，判断管口功能
                    if product_version in ["AKU", "BKU"] and pipe_function == "壳程入口":
                        belong_options = ["壳程大端圆筒", "锥壳"]
                    elif product_version in ["AKU", "BKU"] and pipe_function in [
                        "壳程液位计1", "壳程液位计2", "壳程温度计"
                    ]:
                        belong_options = ["壳程大端圆筒", "壳程封头"]
                    elif pipe_function in ["管程入口", "管程出口"]:
                        belong_options = options
                    else:
                        belong_options = get_belong_options(stats_widget.product_id)
                    break  # 匹配后退出循环
            else:
                # 无匹配版本（理论上不会走到这里，除非新增了未定义的版本）
                belong_options = get_belong_options(stats_widget.product_id)
        else:
            # 非管壳式热交换器，使用默认逻辑
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

    # 管口附件逻辑（第17列）
    if column == 17:
        attachment_options = get_pipe_attachment_options()
        delegate = MultiSelectComboDelegate(
            attachment_options if attachment_options else ["None"],
            table
        )
        table.setItemDelegateForColumn(column, delegate)
        table.editItem(table.item(row, column))
        return

    # 管口载荷逻辑（第18列）
    if column == 18:
        # 点击第18列时，弹出管口载荷设置对话框
        _show_pipe_openingload_dialog(stats_widget, row)
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
                # 批量模式下，对每个修改的行都处理公称尺寸修改的逻辑
                for modified_row in stats_widget.bulk_assign_rows:
                    _handle_nominal_size_changed(stats_widget, modified_row, stats_widget.product_id)

            delegate = stats_widget.pipe_column_delegates[column]
            delegate.bulk_select_callback = bulk_assign_callback
            delegate.disable_wheel_scroll = True  # 批量模式下禁用滚轮
            delegate.setItems(size_options if size_options else ["None"])
            table.editItem(table.item(row, column))

        else:
            # 单选模式：获取公称尺寸选项，根据当前行的法兰标准进行筛选
            # 获取当前行的法兰标准（第5列）
            flange_standard_item = table.item(row, 5)
            flange_standard = flange_standard_item.text().strip() if flange_standard_item else None

            size_options = get_nominal_size_options(stats_widget.product_id, stats_widget, flange_standard)

            # 设置公称尺寸修改后的处理回调
            def nominal_size_callback(value):
                # 先设置值
                apply_bulk_assign_value_immediate(stats_widget, column, [row], value)
                # 然后处理公称尺寸修改的逻辑
                _handle_nominal_size_changed(stats_widget, row, stats_widget.product_id)

            delegate = stats_widget.pipe_column_delegates[column]
            delegate.bulk_select_callback = nominal_size_callback
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
        # ✅ 新增：如果是法兰标准列（第5列），在批量编辑前保存所有行的当前值作为旧值
        if column == 5:
            if not hasattr(stats_widget, 'flange_standard_old_values'):
                stats_widget.flange_standard_old_values = {}

            # 为每个批量选择的行保存旧值
            for bulk_row in stats_widget.bulk_assign_rows:
                current_item = table.item(bulk_row, 5)
                if current_item:
                    stats_widget.flange_standard_old_values[bulk_row] = current_item.text().strip()
                else:
                    stats_widget.flange_standard_old_values[bulk_row] = ""

        # 批量模式：使用交集选项
        options = compute_intersection_options(stats_widget, column, stats_widget.bulk_assign_rows)


        # 设置批量赋值回调
        def bulk_assign_callback(value):
            # ✅ 新增：如果是法兰标准列，先处理切换逻辑，再执行批量赋值
            if column == 5:
                # 对每个批量选择的行处理法兰标准切换逻辑
                for bulk_row in stats_widget.bulk_assign_rows:
                    old_standard = stats_widget.flange_standard_old_values.get(bulk_row, "")
                    handle_class_flange_standard_change(stats_widget, bulk_row, value, old_standard)

            # 执行批量赋值
            apply_bulk_assign_value_immediate(stats_widget, column, stats_widget.bulk_assign_rows, value)

            # ✅ 新增：如果是法兰标准列，更新所有行的旧值
            if column == 5:
                for bulk_row in stats_widget.bulk_assign_rows:
                    stats_widget.flange_standard_old_values[bulk_row] = value

        delegate = stats_widget.pipe_column_delegates[column]
        delegate.bulk_select_callback = bulk_assign_callback
        delegate.disable_wheel_scroll = True  # 批量模式下禁用滚轮
        delegate.setItems(options if options else ["None"])
        table.editItem(table.item(row, column))

    else:
        # ✅ 新增：如果是法兰标准列（第5列），在编辑前保存当前值作为旧值
        if column == 5:
            if not hasattr(stats_widget, 'flange_standard_old_values'):
                stats_widget.flange_standard_old_values = {}

            # 获取当前单元格的值作为旧值
            current_item = table.item(row, 5)
            if current_item:
                stats_widget.flange_standard_old_values[row] = current_item.text().strip()
            else:
                stats_widget.flange_standard_old_values[row] = ""

        # 单选模式：使用当前行的筛选选项
        filters = {}
        for col_other, field in target_fields.items():
            if col_other != column:
                item = table.item(row, col_other)
                if item and item.text().strip():
                    filters[field] = item.text().strip()

        unit_types = get_unit_types_from_db(stats_widget.product_id)
        pressure_type, _, _, _ = get_standard_flange_pressure_level_default_value(stats_widget.product_id, stats_widget)

        # ✅ 新增：如果是法兰标准列（第5列）且压力类型为Class或PN，使用数据库中的对应选项
        if column == 5 and pressure_type in ["Class", "PN"]:
            options = get_flange_standard_options_by_pressure_type(pressure_type)
        else:
            options = get_filtered_pipe_options(current_field, filters, unit_types, pressure_type)

        # ✅ 新增：如果是压力等级列（第6列），显示接管法兰最小压力等级提示
        if column == 6:
            # 获取管口所属元件
            belong_item = table.item(row, 10)
            pipe_belong = belong_item.text().strip() if belong_item else ""
            # 读取当前行法兰标准（第5列）
            flange_item = table.item(row, 5)
            flange_std = flange_item.text().strip() if flange_item else ""


            # 获取管口ID（从隐藏的管口ID映射中获取）
            pipe_id = None
            if hasattr(stats_widget, 'row_hidden_pipe_id') and row in stats_widget.row_hidden_pipe_id:
                pipe_id = stats_widget.row_hidden_pipe_id[row]

            # 读取管口代号（第1列）
            pipe_code_item = table.item(row, 1)
            pipe_code = pipe_code_item.text().strip() if pipe_code_item else ""

            if pipe_belong and hasattr(stats_widget, 'line_tip'):
                try:
                    tip_message = generate_pressure_level_tips(stats_widget.product_id, pipe_belong,  pressure_type, pipe_id, pipe_code, flange_std)
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

    # ✅ 新增：记录点击单元格的初始值，仅对互斥相关列生效
    item = table.item(row, column)
    original_text = item.text().strip() if item else ""

    if not hasattr(stats_widget, "original_cell_value_map"):
        stats_widget.original_cell_value_map = {}

    if column in {13, 15}:
        stats_widget.original_cell_value_map[(row, column)] = original_text
        stats_widget.original_cell_value = original_text


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


"""根据列和多行，计算各行可选项的交集（列4返回统一选项）"""
def compute_intersection_options(stats_widget, column, rows):
    table = stats_widget.tableWidget_pipe
    if column == 4:
        # 公称尺寸：根据各行的法兰标准计算交集选项
        intersection_set = None
        for r in rows:
            # 获取该行的法兰标准（第5列）
            flange_standard_item = table.item(r, 5)
            flange_standard = flange_standard_item.text().strip() if flange_standard_item else None


            # 获取该行对应的公称尺寸选项
            row_options = get_nominal_size_options(stats_widget.product_id, stats_widget, flange_standard) or []
            row_set = set(row_options)

            if intersection_set is None :
                intersection_set = row_set
            else:
                intersection_set &= row_set


            if not intersection_set:
                # 交集已空，提前结束
                return []

        return sorted(intersection_set, key=lambda x: int(x) if x.isdigit() else float('inf')) if intersection_set else []

    # 5/6/7/8 列：根据每行已填的其他字段做筛选，最后取交集
    col_to_field = {5: "法兰标准", 6: "压力等级", 7: "法兰型式", 8: "密封面型式"}
    current_field = col_to_field.get(column)
    if not current_field:
        return []

    unit_map = get_unit_types_from_db(stats_widget.product_id) or {}
    pressure_type, _, _, _ = get_standard_flange_pressure_level_default_value(stats_widget.product_id, stats_widget)

    # ✅ 新增：如果是法兰标准列（第5列）且压力类型为Class或PN，直接返回对应选项，跳过交集运算
    if column == 5 and pressure_type in ["Class", "PN"]:
        return get_flange_standard_options_by_pressure_type(pressure_type)

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
        if ("管箱" in pipe_belong) or ("管板" in pipe_belong)or("锥壳" in pipe_belong):
            param_field = '管程数值'
        elif ("壳体" in pipe_belong) or ("壳程" in pipe_belong) or ("外头盖" in pipe_belong) :
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
       # print(result)

        if result is None or result.get(param_field) in (None, ""):#补充为""的清空
        #if result is None or result.get(param_field) is None or result=="":
            return False, "未获取到公称直径，须先至条件输入输入公称直径并保存"
        return True, float(result[param_field])
    except Exception as e:
        return False, f"数据库错误: {str(e)}"
    finally:
        cursor and cursor.close()
        conn and conn.close()

"""获取锥壳长度，供轴向定位等逻辑复用"""
def get_cone_length(product_id):
    """
    锥壳长度计算公式：
    cone_length = (壳程公称直径 - 管程公称直径) * tan(30°)
    :param product_id: 产品ID
    :return: 锥壳长度（float，最小为0）
    """
    try:
        # 分别获取管程与壳程公称直径（失败时按0处理）
        tube_ok, tube_nominal_diameter = get_nominal_diameter(product_id, "管箱")
        shell_ok, shell_nominal_diameter = get_nominal_diameter(product_id, "壳体")

        if (not tube_ok) or (tube_nominal_diameter is None):
            tube_nominal_diameter = 300
        if (not shell_ok) or (shell_nominal_diameter is None):
            shell_nominal_diameter = 400

        cone_length = (shell_nominal_diameter - tube_nominal_diameter) / math.tan(math.radians(30))
        return max(0, float(cone_length))
    except Exception:
        return 0

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
        elif ("壳体" in pipe_belong) or ("外头盖" in pipe_belong)or("壳程" in pipe_belong):
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

        # 默认推荐前4个；产品类型为 AKU/BKU 时推荐前5个（直接从数据库读取）
        db_type = get_product_type(product_id)
        product_type = str(db_type or "").strip().upper()
        recommend_count = 5 if product_type in {"AKU", "BKU"} else 4

        # 处理前N行（排除最后一行空白行）
        for row in range(min(recommend_count, table.rowCount() - 1)):
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


def auto_assign_eccentricity_for_aku_bku(stats_widget, product_id):
    """
    AKU/BKU 默认偏心距赋值：
    - 先取当前产品的管程公称直径 D
    - 将管口代号 L1/L2/T1 的偏心距（第15列）分别设置为 -1/4D、+1/4D、+1/4D
    """
    try:
        if not product_id:
            return
        product_type = str(get_product_type(product_id) or "").strip().upper()
        if product_type not in {"AKU", "BKU"}:
            return

        table = getattr(stats_widget, "tableWidget_pipe", None)
        if table is None:
            return

        ok, result = get_nominal_diameter(product_id, "壳程圆筒")
        if not ok:
            print(f"[DEBUG] AKU/BKU 自动赋偏心距失败（取管程公称直径）：{result}")
            return

        tube_nominal_diameter = float(result)
        quarter_d = tube_nominal_diameter / 4.0
        target_map = {
            "L1": -quarter_d,
            "L2": quarter_d,
            "T1": quarter_d,
        }

        old_suppress = getattr(stats_widget, "suppress_cell_change", None)
        if hasattr(stats_widget, "suppress_cell_change"):
            stats_widget.suppress_cell_change = True
        try:
            for row in range(max(0, table.rowCount() - 1)):  # 排除最后空白行
                code_item = table.item(row, 1)  # 管口代号
                code = code_item.text().strip() if code_item else ""
                if code not in target_map:
                    continue

                ecc_item = table.item(row, 15)  # 偏心距
                if ecc_item is None:
                    ecc_item = QTableWidgetItem("")
                    ecc_item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(row, 15, ecc_item)

                ecc_item.setText(str(target_map[code]))
                ecc_item.setTextAlignment(Qt.AlignCenter)
        finally:
            if hasattr(stats_widget, "suppress_cell_change"):
                stats_widget.suppress_cell_change = old_suppress if old_suppress is not None else False

    except Exception as e:
        print(f"[ERROR] AKU/BKU 自动赋偏心距失败: {str(e)}")

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

"""补丁：以下两个方法用于判断"零/非零"和"是否刚从零变为非零"""
def _is_zero_like(text: str) -> bool:
    """把 '', '0', '0.0', '0.00' 等都视为 0；非法数字也按非零处理"""
    t = (text or "").strip()
    if t in {"", "0", "0.0", "0.00"}:
        return True
    try:
        return abs(float(t)) < 1e-9
    except Exception:
        return False  # 非法数字当作非零，交给各自验证去拦

def _just_turned_from_zero_to_nonzero(stats_widget, row: int, column: int, new_text: str) -> bool:
    """
    仅当"本次编辑"的原值为零样式、且新值为非零样式时返回 True。
    - 依赖 handle_pipe_cell_click() 里记录的 stats_widget.original_cell_value
    """
    default_old = getattr(stats_widget, "original_cell_value", "")
    value_map = getattr(stats_widget, "original_cell_value_map", {})
    old_text = value_map.get((row, column), default_old)
    return _is_zero_like(old_text) and (not _is_zero_like(new_text))

"""检查并处理轴向夹角和偏心距的互斥逻辑"""
def _check_angle_eccentricity_mutex(stats_widget, row):
    """
    检查指定行的轴向夹角和偏心距是否同时非零，如果是则清空其中一个并弹窗提示
    :param stats_widget: Stats类实例
    :param row: 行号
    """
    table = stats_widget.tableWidget_pipe
    angle_item = table.item(row, 13)  # 轴向夹角列
    ecc_item = table.item(row, 15)    # 偏心距列

    angle_text = angle_item.text().strip() if angle_item else ""
    ecc_text = ecc_item.text().strip() if ecc_item else ""

    # 检查是否两个都不为0
    if not _is_zero_like(angle_text) and not _is_zero_like(ecc_text):
        # 两个都不为0，清空偏心距并弹窗
        try:
            stats_widget.suppress_cell_change = True
            if ecc_item:
                ecc_item.setText("0.0")
            else:
                ecc_item = QTableWidgetItem("0.0")
                ecc_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, 15, ecc_item)
            if hasattr(stats_widget, "original_cell_value_map"):
                stats_widget.original_cell_value_map[(row, 15)] = "0.0"
        finally:
            stats_widget.suppress_cell_change = False

        QMessageBox.warning(
            stats_widget,
            "校验冲突",
            "因轴向夹角和偏心距被同时赋值，基于GB/T 150规则无法对此管口进行强度校核"
        )

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
    if product_version not in ["AEU", "BEU", "AES", "BES", "NEN", "BEM","NEN(Head)"]:
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
        # 管板场景：列已锁定，保持当前显示，跳过验证
        pipe_belong = table.item(row, 10).text().strip() if table.item(row, 10) else ""
        if "管板" in pipe_belong:
            _set_tip(stats_widget, "")
            return

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
            if hasattr(stats_widget, "original_cell_value_map"):
                stats_widget.original_cell_value_map[(row, 13)] = str(default_value)
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
                and _just_turned_from_zero_to_nonzero(stats_widget, row, 13, str(result))
            ):
                stats_widget.suppress_cell_change = True

                ecc_item.setText("0.0")
                stats_widget.suppress_cell_change = False
                if hasattr(stats_widget, "original_cell_value_map"):
                    stats_widget.original_cell_value_map[(row, 15)] = "0.0"
                QMessageBox.warning(
                    stats_widget,
                    "校验冲突",
                    "因轴向夹角和偏心距被同时赋值，基于GB/T 150规则无法对此管口进行强度校核"
                )

            if hasattr(stats_widget, "original_cell_value_map"):
                stats_widget.original_cell_value_map[(row, 13)] = str(result)

        # ✅ 轴向夹角改变后刷新绘图
        if hasattr(stats_widget, 'view') and stats_widget.view:
            stats_widget.view.set_pipe_data(stats_widget.get_all_pipe_data())

    # 验证周向方位
    elif column == 14:  # 周向方位列
        # 管板场景：列已锁定，保持当前显示，跳过验证
        pipe_belong = table.item(row, 10).text().strip() if table.item(row, 10) else ""
        if "管板" in pipe_belong:
            _set_tip(stats_widget, "")
            return

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
        # 管板场景：列已锁定，保持当前显示，跳过验证
        pipe_belong = table.item(row, 10).text().strip() if table.item(row, 10) else ""
        if "管板" in pipe_belong:
            _set_tip(stats_widget, "")
            return

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
            if hasattr(stats_widget, "original_cell_value_map"):
                stats_widget.original_cell_value_map[(row, 15)] = str(default_value)
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
                and _just_turned_from_zero_to_nonzero(stats_widget, row, 15, str(result))
            ):
                stats_widget.suppress_cell_change = True

                angle_item.setText("0.0")
                stats_widget.suppress_cell_change = False
                if hasattr(stats_widget, "original_cell_value_map"):
                    stats_widget.original_cell_value_map[(row, 13)] = "0.0"
                QMessageBox.warning(
                    stats_widget,
                    "校验冲突",
                    "因轴向夹角和偏心距被同时赋值，基于GB/T 150规则无法对此管口进行强度校核"
                )

            if hasattr(stats_widget, "original_cell_value_map"):
                stats_widget.original_cell_value_map[(row, 15)] = str(result)

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
        # # 获取管口功能
        # function_item = table.item(row, 2)  # 2是管口功能列的索引
        # pipe_function = function_item.text().strip() if function_item else ""

        # 获取当前输入值
        input_value = item.text().strip()

        # 缓存单元格文本（避免重复调用item()和text()）
        pipe_function = table.item(row, 2).text().strip() if table.item(row, 2) else ""
        nominal_size_text = table.item(row, 4).text().strip() if table.item(row, 4) else ""
        pipe_belong = table.item(row, 10).text().strip() if table.item(row, 10) else ""
        pipe_code = table.item(row, 1).text().strip() if table.item(row, 1) else None

        # 封头/平盖：轴向定位距离禁用，保持“—”，避免高亮/代理提交触发校验改值
        if pipe_belong and (("封头" in pipe_belong) or ("平盖" in pipe_belong)):
            _set_tip(stats_widget, "")
            return

        # # 使用新的验证函数
        valid, result = validate_axial_position_distance(input_value, nominal_size_text, stats_widget, emit_error=False,
                                                         pipe_belong=pipe_belong, product_id=product_id,
                                                         pipe_code=pipe_code)

        if not valid:
            # 显示错误提示
            _set_tip(stats_widget, result, "red")
            # 根据管口功能设置默认值
            if pipe_function in ["管程入口", "管程出口"] or pipe_belong in["固定管板","前端管板","后端管板"]:
                default_value = "居中"
            else:
                default_value = "程序推荐"


            # 设置默认值
            try:
                stats_widget.suppress_cell_change = True
                item.setText(default_value)
            finally:
                stats_widget.suppress_cell_change = False
            return  # 验证失败时直接返回，保留红色提示
        else:
            # 验证通过时清空警告
            _set_tip(stats_widget, "")

            # 设置验证后的值
            table.blockSignals(True)
            item.setText(str(result))
            table.blockSignals(False)

        # ✅ 轴向定位距离改变后刷新绘图
        if hasattr(stats_widget, 'view') and stats_widget.view:
            stats_widget.view.set_pipe_data(stats_widget.get_all_pipe_data())

    # "管口所属元件"列
    elif column == 10:
        new_value = item.text().strip() if item else ""

        # 获取旧值：优先从字典中获取（在handle_pipe_cell_click中已保存）
        if not hasattr(stats_widget, 'pipe_belong_old_values'):
            stats_widget.pipe_belong_old_values = {}

        old_value = stats_widget.pipe_belong_old_values.get(row, "")

        # 如果 old_value 仍然为空（异常情况），尝试从当前单元格获取
        # 注意：此时 item 已经是新值了，所以不能直接从 item 获取
        # 这种情况应该在 handle_pipe_cell_click 中已经保存，如果还是空，说明可能是程序设置的值
        if not old_value:
            # 如果字典中没有旧值，可能是第一次编辑或程序初始化，此时 old_value 保持为空
            old_value = ""

        # 当切换为管板时，设定轴向定位距离（第12列）为“居中”，并锁定13/14/15列
        if "管板" in new_value:
            try:
                stats_widget.suppress_cell_change = True

                # 第12列：轴向定位距离 -> “居中”
                item_col12 = table.item(row, 12)
                if not item_col12:
                    item_col12 = QTableWidgetItem()
                    table.setItem(row, 12, item_col12)
                item_col12.setText("居中")
                item_col12.setTextAlignment(Qt.AlignCenter)

                # 第13/14/15列：轴向夹角、周向方位、偏心距 -> 置空且不可编辑（但保留可选中，保证整行高亮）
                for lock_col in (13, 14, 15):
                    lock_item = table.item(row, lock_col)
                    if not lock_item:
                        lock_item = QTableWidgetItem()
                        table.setItem(row, lock_col, lock_item)
                    lock_item.setText("—")
                    lock_item.setTextAlignment(Qt.AlignCenter)
                    # 只禁止编辑，不禁止选中，避免行选中高亮被截断
                    lock_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)




            finally:
                stats_widget.suppress_cell_change = False
        else:
            # 切换为非管板：解除锁定，并为占位符/空值填入默认值
            # 识别“来源于管板”的方式：
            # 1) old_value 中含“管板”（正常界面切换场景）
            # 2) 当前轴向定位基准为“管程侧端面”或“壳程侧端面”（导入场景下的管板行）
            base_item = table.item(row, 11)
            base_text = base_item.text().strip() if base_item else ""
            from_tubesheet = ("管板" in old_value) or (base_text in ("管程侧端面", "壳程侧端面"))

            if from_tubesheet:
                # 获取当前行的管口功能和新元件（用于默认值判断）
                pipe_function_item = table.item(row, 2)
                pipe_function = pipe_function_item.text().strip() if pipe_function_item else ""
                pipe_belong_new = new_value

                for unlock_col in (13, 14, 15):
                    unlock_item = table.item(row, unlock_col)
                    if not unlock_item:
                        unlock_item = QTableWidgetItem()
                        table.setItem(row, unlock_col, unlock_item)
                    unlock_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsEditable | Qt.ItemIsSelectable)
                    try:
                        stats_widget.suppress_cell_change = True
                        text_now = unlock_item.text().strip()

                        # 如果是从模板导入的“—”或空值，则根据规则写入默认值：
                        # 13列：轴向夹角 -> 默认 0.0
                        # 14列：周向方位 -> 根据管口功能，入口 0°，其他 180°
                        # 15列：偏心距   -> 默认 0.0
                        if text_now in ("", "—"):
                            if unlock_col == 13:
                                _, default_angle = validate_axial_angle("")
                                unlock_item.setText(str(default_angle))
                            elif unlock_col == 14:
                                _, default_pos = validate_circumferential_position("", pipe_function)
                                unlock_item.setText(str(default_pos))
                            elif unlock_col == 15:
                                _, default_ecc = validate_eccentricity("", product_id, pipe_belong_new, emit_error=False)
                                unlock_item.setText(str(default_ecc))

                        unlock_item.setTextAlignment(Qt.AlignCenter)
                        # 不强制设置白底，避免覆盖选中高亮颜色
                        # unlock_item.setBackground(Qt.white)
                    finally:
                        stats_widget.suppress_cell_change = False
                _set_tip(stats_widget, "")  # 清理底部提示

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

        elif new_value.endswith("平盖") and old_value.endswith("封头"):
            target_item = table.item(row, 11)
            if not target_item:
                target_item = QTableWidgetItem()
                table.setItem(row, 11, target_item)
            target_item.setText("平盖中心线")
            target_item.setTextAlignment(Qt.AlignCenter)

        elif new_value.endswith("封头") and old_value.endswith("平盖"):
            target_item = table.item(row, 11)
            if not target_item:
                target_item = QTableWidgetItem()
                table.setItem(row, 11, target_item)
            target_item.setText("封头中心线")
            target_item.setTextAlignment(Qt.AlignCenter)

        elif new_value.endswith("平盖") and old_value.endswith("圆筒"):
            target_item = table.item(row, 11)
            if not target_item:
                target_item = QTableWidgetItem()
                table.setItem(row, 11, target_item)
            target_item.setText("平盖中心线")
            target_item.setTextAlignment(Qt.AlignCenter)

        elif new_value.endswith("圆筒") and old_value.endswith("平盖"):
            target_item = table.item(row, 11)
            if not target_item:
                target_item = QTableWidgetItem()
                table.setItem(row, 11, target_item)
            target_item.setText("左基准线")
            target_item.setTextAlignment(Qt.AlignCenter)
        elif new_value.endswith("平盖") and old_value.endswith("锥壳"):
            target_item = table.item(row, 11)
            if not target_item:
                target_item = QTableWidgetItem()
                table.setItem(row, 11, target_item)
            target_item.setText("平盖中心线")
            target_item.setTextAlignment(Qt.AlignCenter)
        elif new_value.endswith("封头") and old_value.endswith("锥壳"):
            target_item = table.item(row, 11)
            if not target_item:
                target_item = QTableWidgetItem()
                table.setItem(row, 11, target_item)
            target_item.setText("封头中心线")
            target_item.setTextAlignment(Qt.AlignCenter)
        elif new_value.endswith("锥壳") and old_value.endswith("封头"):
            target_item = table.item(row, 11)
            if not target_item:
                target_item = QTableWidgetItem()
                table.setItem(row, 11, target_item)
            target_item.setText("左基准线")
            target_item.setTextAlignment(Qt.AlignCenter)
        elif new_value.endswith("锥壳") and old_value.endswith("平盖"):
            target_item = table.item(row, 11)
            if not target_item:
                target_item = QTableWidgetItem()
                table.setItem(row, 11, target_item)
            target_item.setText("左基准线")
            target_item.setTextAlignment(Qt.AlignCenter)

        # === 管板相关切换：从管板 → 圆筒/封头/平盖，以及 → 管板 的情况 ===
        else:
            base_item = table.item(row, 11)
            base_text = base_item.text().strip() if base_item else ""
            # 判断是否可视为来源于管板：old_value 含“管板”或当前基准为管板专用的两种端面
            from_tubesheet = ("管板" in old_value) or (base_text in ("管程侧端面", "壳程侧端面"))

            if new_value.endswith("圆筒") and from_tubesheet:
                target_item = base_item or QTableWidgetItem()
                if not base_item:
                    table.setItem(row, 11, target_item)
                target_item.setText("左基准线")
                target_item.setTextAlignment(Qt.AlignCenter)

            elif new_value.endswith("封头") and from_tubesheet:
                target_item = base_item or QTableWidgetItem()
                if not base_item:
                    table.setItem(row, 11, target_item)
                target_item.setText("封头中心线")
                target_item.setTextAlignment(Qt.AlignCenter)

            elif new_value.endswith("平盖") and from_tubesheet:
                target_item = base_item or QTableWidgetItem()
                if not base_item:
                    table.setItem(row, 11, target_item)
                target_item.setText("平盖中心线")
                target_item.setTextAlignment(Qt.AlignCenter)

            elif new_value.endswith("管板") and old_value.endswith("平盖"):
                target_item = base_item or QTableWidgetItem()
                if not base_item:
                    table.setItem(row, 11, target_item)
                target_item.setText("壳程侧端面")
                target_item.setTextAlignment(Qt.AlignCenter)

            elif new_value.endswith("管板") and old_value.endswith("封头"):
                target_item = base_item or QTableWidgetItem()
                if not base_item:
                    table.setItem(row, 11, target_item)
                target_item.setText("壳程侧端面")
                target_item.setTextAlignment(Qt.AlignCenter)

            elif new_value.endswith("管板") and old_value.endswith("圆筒"):
                target_item = base_item or QTableWidgetItem()
                if not base_item:
                    table.setItem(row, 11, target_item)
                target_item.setText("壳程侧端面")
                target_item.setTextAlignment(Qt.AlignCenter)

        # 注意：后续修改管口所属元件时不再自动推荐公称尺寸
        # 只在初始化时推荐一次

        # 切换为锥壳时：若当前公称尺寸超出锥壳长度，则重置为默认值10
        if "锥壳" in new_value:
            nominal_item = table.item(row, 4)
            nominal_text = nominal_item.text().strip() if nominal_item else ""
            if nominal_item and nominal_text:
                current_product_id = getattr(stats_widget, "product_id", None)
                cone_length = get_cone_length(current_product_id)
                nominal_numeric = get_nominal_size_numeric_value(nominal_text, stats_widget=stats_widget)
                if nominal_numeric is None:
                    nominal_numeric = get_component_nominal_size_od(nominal_text, stats_widget=stats_widget)

                if nominal_numeric is not None and nominal_numeric > cone_length:
                    try:
                        stats_widget.suppress_cell_change = True
                        nominal_item.setText("10")
                        model = table.model()
                        if model is not None:
                            model.setData(model.index(row, 4), "10")
                    finally:
                        stats_widget.suppress_cell_change = False

                    pipe_code_item = table.item(row, 1)
                    pipe_code_text = pipe_code_item.text().strip() if pipe_code_item else "当前"
                    try:
                        msg = f"{pipe_code_text}切换为锥壳后，公称尺寸超出锥壳长度，已设为默认值10"

                        _set_tip(stats_widget, msg, "orange")
                        QTimer.singleShot(5000, lambda: stats_widget.line_tip.setText(""))
                    except Exception:
                        pass

        # 同步列12/13–15 锁定状态（封头/平盖立即显示“—”，切回普通类型恢复可编辑）
        apply_pipe_row_column_locks_by_belong(stats_widget, row)

        # 更新旧值
        if not hasattr(stats_widget, 'pipe_belong_old_values'):
            stats_widget.pipe_belong_old_values = {}
        stats_widget.pipe_belong_old_values[row] = new_value

    # ✅ 新增：法兰标准列改变时的特殊处理（Class压力等级）
    elif column == 5:  # 法兰标准列
        new_standard = item.text().strip() if item else ""
        if new_standard:
            # 获取旧值
            old_standard = None
            if hasattr(stats_widget, 'flange_standard_old_values'):
                old_standard = stats_widget.flange_standard_old_values.get(row, "")

            # 调用Class压力等级下的法兰标准切换处理函数
            handle_class_flange_standard_change(stats_widget, row, new_standard, old_standard)

            # ✅ 新增：法兰标准变化时，更新公称尺寸列（第4列）的下拉框选项
            if hasattr(stats_widget, 'pipe_column_delegates') and 4 in stats_widget.pipe_column_delegates:
                size_options = get_nominal_size_options(stats_widget.product_id, stats_widget, new_standard)
                delegate = stats_widget.pipe_column_delegates[4]
                delegate.setItems(size_options if size_options else ["None"])

            # 更新旧值
            if not hasattr(stats_widget, 'flange_standard_old_values'):
                stats_widget.flange_standard_old_values = {}
            stats_widget.flange_standard_old_values[row] = new_standard

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


"""公称尺寸修改，修正轴向定位距离"""
def _check_and_fix_axial_distance_for_rows(stats_widget, table, target_belong_keywords, exclude_rows=None,
                                           product_id=None):
    """
    检查并修正指定类型管口的轴向定位距离
    :param stats_widget: Stats类实例
    :param table: 表格控件
    :param target_belong_keywords: 目标所属元件关键词列表，如["管箱圆筒"]或["壳体圆筒"]
    :param exclude_rows: 需要排除的行号列表
    :param product_id: 产品ID
    :return: 不合法管口代号列表
    """
    offending_codes = []
    exclude_rows = exclude_rows or []

    for check_row in range(table.rowCount()):
        # 排除指定行
        if check_row in exclude_rows:
            continue

        # 检查是否有管口代号
        pipe_code_item = table.item(check_row, 1)
        if not pipe_code_item or not pipe_code_item.text().strip():
            continue

        # 获取管口所属元件
        belong_item = table.item(check_row, 10)
        if not belong_item:
            continue

        pipe_belong = belong_item.text().strip()
        # 检查是否匹配目标类型
        if not pipe_belong or not any(keyword in pipe_belong for keyword in target_belong_keywords):
            continue

        # 获取该行的公称尺寸
        nominal_size_item = table.item(check_row, 4)
        if not nominal_size_item:
            continue

        nominal_size_text = nominal_size_item.text().strip()
        if not nominal_size_text:
            continue

        # 获取该行的轴向定位距离
        axial_distance_item = table.item(check_row, 12)
        if not axial_distance_item:
            continue

        axial_distance_text = axial_distance_item.text().strip()
        if not axial_distance_text:
            continue

        # 获取管口代号
        code_text_row = pipe_code_item.text().strip()

        # 验证轴向定位距离
        valid, result = validate_axial_position_distance(
            axial_distance_text,
            nominal_size_text,
            stats_widget,
            emit_error=False,
            pipe_belong=pipe_belong,
            product_id=product_id,
            pipe_code=code_text_row
        )

        # 如果验证不通过，设置为默认值，并记录以合并提示
        if not valid:
            # ✅ 根据管口所属元件类型设置默认值
            # 管箱圆筒、外头盖圆筒：设为"居中"
            # 壳体圆筒：设为"程序推荐"
            if "管箱圆筒" in pipe_belong or "外头盖圆筒" in pipe_belong or "管板" in pipe_belong:
                default_value = "居中"
            elif "壳体圆筒" in pipe_belong or "壳程大端圆筒" in pipe_belong or"锥壳"in pipe_belong:
                default_value = "程序推荐"
            else:
                # 其他类型，根据管口功能确定默认值
                func_item = table.item(check_row, 2)
                pipe_function = func_item.text().strip() if func_item else ""
                default_value = "居中" if pipe_function in ["管程入口", "管程出口"] else "程序推荐"

            try:
                stats_widget.suppress_cell_change = True
                axial_distance_item.setText(default_value)
            finally:
                stats_widget.suppress_cell_change = False

            if code_text_row:
                offending_codes.append(code_text_row)

    return offending_codes

def _handle_nominal_size_changed(stats_widget, row, product_id):
    """
    处理公称尺寸列修改时的逻辑
    公称尺寸修改时，对管箱外头盖和壳体管口的轴向定位距离进行验证，不合法则设为默/认值并合并提示
    """
    try:
        table = stats_widget.tableWidget_pipe

        # 先检查当前行：锥壳管口公称尺寸不得大于锥壳长度
        belong_item = table.item(row, 10)
        nominal_item = table.item(row, 4)
        if belong_item and nominal_item:
            pipe_belong = belong_item.text().strip()
            nominal_text = nominal_item.text().strip()
            if pipe_belong and "锥壳" in pipe_belong and nominal_text:
                current_product_id = product_id or getattr(stats_widget, "product_id", None)
                cone_length = get_cone_length(current_product_id)
                nominal_numeric = get_nominal_size_numeric_value(nominal_text, stats_widget=stats_widget)
                # 兜底：若公称尺寸数值解析失败，尝试按接管实际外径/纯数字再解析一次
                if nominal_numeric is None:
                    nominal_numeric = get_component_nominal_size_od(nominal_text, stats_widget=stats_widget)
                if nominal_numeric is None:
                    cleaned = "".join(ch for ch in nominal_text if (ch.isdigit() or ch == "."))
                    try:
                        nominal_numeric = float(cleaned) if cleaned else None
                    except Exception:
                        nominal_numeric = None

                if nominal_numeric is not None and nominal_numeric > cone_length:
                    try:
                        stats_widget.suppress_cell_change = True
                        nominal_item.setText("10")
                        model = table.model()
                        if model is not None:
                            model.setData(model.index(row, 4), "10")
                    finally:
                        stats_widget.suppress_cell_change = False

                    pipe_code_item = table.item(row, 1)
                    pipe_code_text = pipe_code_item.text().strip() if pipe_code_item else "当前"
                    try:
                        _set_tip(
                            stats_widget,
                            f"{pipe_code_text}管口公称尺寸已大于锥壳长度，已设为默认值，请重新选择",
                            "orange"
                        )
                        QTimer.singleShot(5000, lambda: stats_widget.line_tip.setText(""))
                    except Exception:
                        pass

        # ✅ 检查所有管口的轴向定位距离（不限制类型）
        # 收集所有不合法管口代号：管箱圆筒、外头盖圆筒、壳体圆筒
        all_offending_codes = []

        # 检查管箱圆筒和外头盖圆筒
        box_offending_codes = _check_and_fix_axial_distance_for_rows(
            stats_widget, table, ["管箱圆筒", "外头盖圆筒"], exclude_rows=None, product_id=product_id
        )
        all_offending_codes.extend(box_offending_codes)

        # 检查管板
        tubesheet_offending_codes = _check_and_fix_axial_distance_for_rows(
            stats_widget, table, ["管板"], exclude_rows=None, product_id=product_id
        )
        all_offending_codes.extend(tubesheet_offending_codes)

        # 检查壳体圆筒
        shell_offending_codes = _check_and_fix_axial_distance_for_rows(
            stats_widget, table, ["壳体圆筒","大端圆筒"], exclude_rows=None, product_id=product_id
        )
        all_offending_codes.extend(shell_offending_codes)

        conicalshell_offending_codes = _check_and_fix_axial_distance_for_rows(
            stats_widget, table, ["锥壳"], exclude_rows=None, product_id=product_id
        )
        all_offending_codes.extend(conicalshell_offending_codes)




        # 统一提示：将所有超限的管口代号合并显示
        if all_offending_codes:
            joined_codes = "、".join(all_offending_codes)
            try:
                _set_tip(
                    stats_widget,
                    f"{joined_codes} 管口轴向定位距离已超出限定值，已为您修改成程序默认值",
                    "orange"
                )
            except Exception:
                pass

        # 更新保存的最大值（用于跟踪最大值变化）
        new_max_pipe_nominal_size = get_max_pipe_nominal_size_from_ui(stats_widget)
        if new_max_pipe_nominal_size is not None:
            stats_widget._old_max_nominal_size = new_max_pipe_nominal_size

    except Exception as e:
        print(f"[ERROR] 处理公称尺寸修改时发生错误: {str(e)}")


"""对压力等级列进行验证的步骤，所调用的方法"""
# step1.分别确定三个接管法兰的类别号
def get_material_category_number_by_product(product_id, pressure_type, pipe_id=None, flange_std=None, pipe_code = None):
    """
    先从产品设计活动表_管口类别表读取管口属于哪个类别，
    然后从产品设计活动表_管口附加参数表中获取对应类别的接管法兰零件材料类型和材料牌号，
    再去元件库中的材料温压值类别表中，结合"当前管口的法兰标准"查找对应的类别号。
    :param product_id: 产品ID
    :param pressure_type: 压力类型（Class或PN）
    :param pipe_id: 管口ID（可选，如果提供则只查询该管口的分类）
    :param flange_std: 当前管口的法兰标准
    :return: 返回三个接管法兰的材料信息字典列表
    """
    conn_design = None
    conn_component = None
    try:

        product_type = get_product_type(product_id)
        if flange_std != None:
            flange_standard = flange_std;
        else:
            flange_standard = get_flange_standard(product_id, pipe_code, product_type)

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
                        WHERE 材料类型 = %s AND 材料牌号 = %s AND 法兰标准 = %s
                        LIMIT 1
                    """, (material_type_mapped, material_grade, flange_standard))
                    category_result = cursor_component.fetchone()

                    # 检查是否找到类别号
                    if not category_result:
                        # 仍然添加法兰信息，但标记为无类别号
                        print(f"[DEBUG_03] ❌ 未找到类别号 → 材料类型={material_type_mapped}, "
                              f"材料牌号={material_grade}, 法兰标准={flange_standard}")

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
    根据产品ID和管口所属元件字段，直接从“产品设计活动表_设计数据表”获取“设计温度（最高）*”。
    :param product_id: 产品ID
    :param pipe_belong: 管口所属元件（如"管箱圆筒"或"壳体封头"）
    """
    conn = None
    cursor = None
    try:
        if "管箱" in pipe_belong or "管板" in pipe_belong:
            value_field = "管程数值"
        elif "壳体" in pipe_belong or "外头盖" in pipe_belong or "壳程" in pipe_belong or "锥壳" in pipe_belong:
            value_field = "壳程数值"
        else:
            return None, "无效的管口所属元件字段"

        conn = get_connection(**db_config_2)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute(f"""
            SELECT `{value_field}` AS val
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s AND 参数名称 LIKE '设计温度%%'
            LIMIT 1
        """, (product_id,))
        result = cursor.fetchone()

        if not result or result.get("val") is None:
            return None, f"未在设计数据中找到{value_field}的设计温度（最高）*"

        try:
            return float(result["val"]), None
        except (ValueError, TypeError):
            return None, f"{value_field} 的设计温度（最高）*未填写"

    except Exception as e:
        return None, f"获取设计温度（最高）失败: {str(e)}"
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
        if "管箱" in pipe_belong or"管板" in pipe_belong:
            value_field = "管程数值"
        elif "壳体" in pipe_belong or "外头盖" in pipe_belong or "壳程" in pipe_belong or "锥壳" in pipe_belong:
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


"""对最后获取到的压力等级提示进行判断，看提示值能否在该标准下取到"""
def get_valid_pressure_level(standard, min_level, pressure_type):

    """
    给定标准和 min_level，例如：
    standard = 'HG/T20592'
    min_level = 'PN 2.5'
    pressure_type = 'PN' 或 'Class'

    在元件库"管口压力等级表"中查找对应标准的所有压力等级，
    若 min_level 不存在，则取比它大的最小值。
    """
    conn = get_connection(**db_config_1)
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute("""
            SELECT DISTINCT 压力等级
            FROM 管口压力等级表
            WHERE 标准=%s
        """, (standard,))
        rows = cursor.fetchall()
        if not rows:
            return min_level  # 找不到则原值返回

        levels = []
        for r in rows:
            lv = float(r["压力等级"]) if pressure_type == "PN" else int(r["压力等级"])
            levels.append(lv)

        levels.sort()

        # 提取 min_level 数值
        min_val = float(min_level.split()[1]) if pressure_type == "PN" else int(min_level.split()[1])

        # 找比 min_val 大的最小值
        upper = [lv for lv in levels if lv >= min_val]
        selected = upper[0] if upper else levels[-1]

        return f"{pressure_type} {selected}"

    finally:
        cursor.close()
        conn.close()

def get_product_type(product_id):
    """获取产品型式"""
    conn = get_connection(**db_config_2)
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    try:
        cursor.execute("""
            SELECT 产品型式
            FROM 产品设计活动表
            WHERE 产品ID=%s
        """, (product_id,))
        row = cursor.fetchone()
        return row["产品型式"] if row else None
    finally:
        cursor.close()
        conn.close()


def get_flange_standard(product_id, pipe_code, product_type):
    """法兰标准优先级：
    1) 产品设计活动库_管口表
    2) 元件库_管口默认表（按产品型式匹配）
    """

    # --- Step 1：先查产品设计活动表_管口表 ---
    conn = get_connection(**db_config_2)
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute("""
            SELECT 法兰标准
            FROM 产品设计活动表_管口表
            WHERE 产品ID=%s AND 管口代号=%s
        """, (product_id, pipe_code))
        row = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    # 如果查到了 → 直接返回
    if row and row.get("法兰标准"):
        return row["法兰标准"]

    # --- Step 2：再查元件库_管口默认表 ---
    conn = get_connection(**db_config_1)
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute("""
            SELECT DISTINCT 法兰标准
            FROM 管口默认表
            WHERE 所属型式=%s
        """, (product_type,))
        row = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    # 无结果返回 None
    return row["法兰标准"] if row else None

# step5.确定每个接管法兰压力等级的推荐值（允许部分成功）
def get_minimum_pressure_level_for_flanges(product_id, pipe_belong, pressure_type, pipe_id=None, pipe_code=None, flange_std=None):
    """
    允许“部分成功”；识别出>=1组材料即进行计算推荐
    未填写/未匹配到类别号，则作为警告返回，不吞掉成功的结果，即对三组均有反馈
    :param product_id: 产品ID
    :param pipe_belong: 管口所属元件
    :param pressure_type: 公称压力类型（Class/PN），用于确定压力等级格式
    :param pipe_id: 管口ID（可选）
    :param pipe_code: 管口代号（用于提示）
    :param flange_std: 当前管口的法兰标准
    """
    try:
        # Step 1: 获取所有接管法兰材料信息
        flange_materials, error = get_material_category_number_by_product(product_id, pressure_type, pipe_id, flange_std, pipe_code)
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

        # Step 2: 获取设计温度
        design_temp, temp_error = get_max_working_temperature_by_belong(product_id, pipe_belong)

        if temp_error:
            return None, f"获取设计温度（最高）*失败: {temp_error}"

        # 将设计温度转换为查询温度（若小于等于38，则统一按38处理）
        if design_temp <= 38:
            query_temp = 38
        else:
            query_temp = design_temp

        # === 调试打印温度 ===
        print(f"[DEBUG_TEMP] 管口所属元件={pipe_belong}, 设计温度={design_temp}°C, 查询温度={query_temp}°C")

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
            print(warn_msg,"warn_msg")
            return None, warn_msg or "此条件下无适用的压力等级推荐"

        return flange_pressure_info, warn_msg

    except Exception as e:
        traceback.format_exc()
        return None, f"计算最小压力等级失败: {str(e)}"

# step6.打印提示
def generate_pressure_level_tips(product_id, pipe_belong, pressure_type, pipe_id=None,pipe_code=None, flange_std=None):
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
        flange_info, error = get_minimum_pressure_level_for_flanges(product_id, pipe_belong, pressure_type, pipe_id, pipe_code, flange_std)
        print(flange_info,"flange_info")
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
        # 生成提示信息（增加法兰标准和压力等级修正）
        tips = []
        product_type = get_product_type(product_id)

        for flange in unique_tips.values():
            std = get_flange_standard(product_id, pipe_code, product_type)
            if flange_std != None:
                corrected_level = get_valid_pressure_level(flange_std, flange["min_pressure_level"], pressure_type)
                tip = (
                    f"管口代号为 {pipe_code} 接管法兰材料类型为 {flange['material_type']}，"
                    f"牌号为 {flange['material_grade']} 时，"
                    f"依据标准 {flange_std}，适用最小压力等级为 {corrected_level}。"
                )
            else:
                corrected_level = get_valid_pressure_level(std, flange["min_pressure_level"], pressure_type)
                tip = (
                    f"管口代号为 {pipe_code} 接管法兰材料类型为 {flange['material_type']}，"
                    f"牌号为 {flange['material_grade']} 时，"
                    f"依据标准 {std}，适用最小压力等级为 {corrected_level}。"
                )
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

"""验证轴向定位距离"""
def validate_axial_position_distance(distance_text, nominal_size_text, stats_widget=None, emit_error=True,
                                     pipe_belong=None, product_id=None, pipe_code=None):
    """
    验证轴向定位距离输入值是否在有效范围内
    :param distance_text: 用户输入的轴向定位距离文本
    :param nominal_size_text: 公称尺寸文本
    :param stats_widget: Stats类实例，用于获取单位类型
    :param emit_error: 是否显示错误弹窗
    :param pipe_belong: 管口所属元件，用于判断是否需要特殊限制
    :param product_id: 产品ID
    :param pipe_code: 管口代号，用于错误提示
    :return: (是否有效: bool, 数值或错误消息: float|str)
    """
    try:
        # 如果是预设选项，直接通过验证
        if distance_text in ["程序推荐", "居中"]:
            return True, distance_text

        # 封头/平盖：轴向定位距离列禁用，占位符“—”合法
        if pipe_belong and (("封头" in pipe_belong) or ("平盖" in pipe_belong)):
            if distance_text.strip() in ("—", ""):
                return True, "—"

        # 如果输入为空，返回默认值
        if not distance_text or distance_text.strip() == "":
            return True, "居中"

        # 尝试转换为浮点数
        try:
            distance_value = float(distance_text)
        except ValueError:
            return False, "请输入有效的数字"

        # 检查是否有公称尺寸
        if not nominal_size_text or nominal_size_text.strip() == "":
            return False, "请先选择公称尺寸"

        # 管板：固定管板/前端管板/后端管板
        if pipe_belong and "管板" in pipe_belong:
            # 当前管口接管外径
            current_pipe_od = get_component_nominal_size_od(nominal_size_text, stats_widget=stats_widget)
            if current_pipe_od is None:
                return False, "无法获取当前管口公称尺寸的接管实际外径数值"

            # 管板上最大公称尺寸（界面获取）
            max_tubesheet_nominal = get_max_tubesheet_nominal_size_from_ui(stats_widget)
            if max_tubesheet_nominal is None:
                return False, "无法获取管板管口的最大公称尺寸信息"
            max_tubesheet_od = get_component_nominal_size_od(max_tubesheet_nominal, stats_widget=stats_widget)
            if max_tubesheet_od is None:
                return False, "无法获取管板最大管口的接管实际外径数值"

            # 固定管板：最小=0.5*当前OD；前/后端管板：最小=0；其他含“管板”默认最小=0
            if "固定管板" in pipe_belong:
                min_distance = 0.5 * current_pipe_od
            elif ("前端管板" in pipe_belong) or ("后端管板" in pipe_belong):
                min_distance = 0.0
            else:
                min_distance = 0.0

            max_distance = 50 * max_tubesheet_od  # 最大=最大管板管口外径的50倍

        # 判断管口所属元件是否为管箱或外头盖圆筒
        elif pipe_belong and ("管箱圆筒" in pipe_belong or "外头盖圆筒" in pipe_belong):
            # 第一步：获取界面中管口公称尺寸的最大值，查数据库转成od
            max_pipe_nominal_size = get_max_pipe_nominal_size_from_ui(stats_widget)

            if max_pipe_nominal_size is None:
                return False, ("无法获取界面中管口的公称尺寸信息"
                               "")

            max_pipe_od = get_component_nominal_size_od(max_pipe_nominal_size, stats_widget=stats_widget)

            if max_pipe_od is None:
                return False, "无法获取管箱上最大管口对应的接管实际外径数值"

            # 第二步：当前管口查数据库转成接管实际外径od
            current_pipe_od = get_component_nominal_size_od(nominal_size_text, stats_widget=stats_widget)
            if current_pipe_od is None:
                return False, "无法获取当前管口公称尺寸的接管实际外径数值"

            # 计算限定值：0.5*当前管口接管实际外径——管箱上最大公称尺寸对应的接管实际外径*2.5-0.5*当前管口接管实际外径
            min_distance = 0.5 * current_pipe_od

            max_distance = max_pipe_od * 2.5 - 0.5 * current_pipe_od
        # 判断管口所属元件是否为壳体
        elif pipe_belong and "锥壳" in pipe_belong:
            # 当前管口查元件库公称尺寸表转成接管实际外径od
            current_pipe_od = get_component_nominal_size_od(nominal_size_text, stats_widget=stats_widget)
            if current_pipe_od is None:
                return False, "无法获取当前管口公称尺寸对应的接管实际外径数值"

            # 分别获取管程、壳程公称直径（失败时按0处理）
            tube_ok, tube_nominal_diameter = get_nominal_diameter(product_id, "管箱")
            shell_ok, shell_nominal_diameter = get_nominal_diameter(product_id, "壳体")
            if (not tube_ok) or (tube_nominal_diameter is None):
                tube_nominal_diameter = 300
            if (not shell_ok) or (shell_nominal_diameter is None):
                shell_nominal_diameter = 400

            # 锥壳长度 = (壳程公称直径 - 管程公称直径) * tan30°
            cone_length = (shell_nominal_diameter - tube_nominal_diameter) / math.tan(math.radians(30))
            if cone_length < 0:
                cone_length = 0

            # 锥壳上轴向定位限制
            min_distance = round(0.5 * current_pipe_od, 2)

            max_distance = round(cone_length - 0.5 * current_pipe_od, 2)
            #print("tube_nominal_diameter",tube_nominal_diameter,"shell_nominal_diameter",shell_nominal_diameter,"cone_length",cone_length,"max_distance",max_distance)

        # 判断管口所属元件是否为壳体
        elif pipe_belong and ("壳体" in pipe_belong or "壳程大端圆筒" in pipe_belong):
            # 获取换热管长度
            tube_length = get_heat_exchanger_tube_length(product_id)
            product_version = getattr(stats_widget, "current_product_version", "")


            # 当前管口查元件库公称尺寸表转成接管实际外径od
            current_pipe_od = get_component_nominal_size_od(nominal_size_text, stats_widget=stats_widget)
            if current_pipe_od is None:
                return False, "无法获取当前管口公称尺寸对应的接管实际外径数值"

            # 计算限定值：0.5*当前管口接管实际外径——换热管长度+1/2壳程公称直径-0.5*当前管口接管实际外径
            min_distance = round(0.5 * current_pipe_od, 2)
            if product_version in [ "AEU", "BEU","AES", "BES", "AEM", "BEM", "NEN","NEN(Head)"]:
                # 获取壳程公称直径数值（失败时按0处理）
                nominal_ok, shell_lengh = get_nominal_diameter(product_id, "壳体")
                if (not nominal_ok) or (shell_lengh is None):
                    shell_lengh = 0
                max_distance = round(tube_length + 1/2 * shell_lengh - 0.5 * current_pipe_od, 2)
            elif product_version in ["AKU", "BKU"]:
                # 大端圆筒的长度为总长-锥壳长度
                tube_ok, tube_nominal_diameter = get_nominal_diameter(product_id, "管箱")
                shell_ok, shell_nominal_diameter = get_nominal_diameter(product_id, "壳体")
                if (not tube_ok) or (tube_nominal_diameter is None):
                    tube_nominal_diameter = 300
                if (not shell_ok) or (shell_nominal_diameter is None):
                    shell_nominal_diameter = 400

                # 锥壳长度 = (壳程公称直径 - 管程公称直径) * tan30°
                cone_length = (shell_nominal_diameter - tube_nominal_diameter) / math.tan(math.radians(30))
                if cone_length < 0:
                    cone_length = 0
                #总长
                max_distance = round(tube_length+ 1/2 * shell_nominal_diameter-cone_length - 0.5 * current_pipe_od, 2)
                print("tube_nominal_diameter1", tube_nominal_diameter, "shell_nominal_diameter", shell_nominal_diameter,
                      "cone_length", cone_length, "max_distance", max_distance)
            else:
                max_distance = round(tube_length - 0.5 * current_pipe_od, 2)
        else:
            # 其他类型暂时不做限制，直接通过验证
            return True, distance_value

        # 验证距离是否在有效范围内
        if min_distance <= distance_value <= max_distance:
            return True, distance_value
        else:
            # 根据不同的管口所属元件类型显示不同的错误消息
            pipe_code_text = pipe_code if pipe_code else "当前"
            if pipe_belong and "管板" in pipe_belong:
                min_tip = f"{pipe_code_text}接管实际外径的0.5倍" if "固定管板" in pipe_belong else "0"
                error_msg = f"{pipe_code_text}管口的轴向定位值需在{min_distance:.2f} mm至{max_distance:.2f} mm之间（最小值为{min_tip}，最大值为管板上最大管口对应接管实际外径的50倍）"
            elif pipe_belong and ("管箱" in pipe_belong or "外头盖圆筒" in pipe_belong):
                error_msg = f"{pipe_code_text}管口的轴向定位值需在{min_distance:.2f} mm至{max_distance:.2f} mm之间（最小值为{pipe_code_text}管口接管实际外径的0.5倍，最大值为所有管口中公称尺寸最大管口对应接管实际外径的2.5倍减去{pipe_code_text}管口接管实际外径的0.5倍）"
            elif pipe_belong and ("壳体" in pipe_belong or "壳程大端圆筒" in pipe_belong):
                # 获取换热管长度用于提示
                #tube_length = get_heat_exchanger_tube_length(product_id) if product_id else None
                if product_version in ["AKU", "BKU"]:
                    error_msg = f"{pipe_code_text}管口的轴向定位值需在{min_distance:.2f} mm至{max_distance:.2f} mm之间（最小值为{pipe_code_text}管口接管实际外径的0.5倍，最大值为大端圆筒长度减去{pipe_code_text}管口接管实际外径的0.5倍）"
                else:
                    error_msg = f"{pipe_code_text}管口的轴向定位值需在{min_distance:.2f} mm至{max_distance:.2f} mm之间（最小值为{pipe_code_text}管口接管实际外径的0.5倍，最大值为壳体圆筒长度（U型管直管段长度（换热管公称长度）加上1/2壳程公称直径长度）减去{pipe_code_text}管口接管实际外径的0.5倍）"
            elif pipe_belong and "锥壳" in pipe_belong:
                error_msg = f"{pipe_code_text}管口的轴向定位值需在{min_distance:.2f} mm至{max_distance:.2f} mm之间（最小值为{pipe_code_text}管口接管实际外径的0.5倍，最大值为锥壳长度减去{pipe_code_text}管口接管实际外径的0.5倍）"
            else:
                error_msg = f"{pipe_code_text}管口的轴向定位值需在{min_distance:.2f} mm至{max_distance:.2f} mm之间"
            return False, error_msg

    except Exception as e:
        return False, f"验证失败: {str(e)}"


"""获取界面中管口所属元件为"管箱圆筒"或"外头盖圆筒"的公称尺寸的最大值"""
def get_max_pipe_nominal_size_from_ui(stats_widget):
    """
    获取界面中管口所属元件为"管箱圆筒"或"外头盖圆筒"的公称尺寸的最大值
    :param stats_widget: Stats类实例
    :return: 最大公称尺寸的数值，如果无法获取则返回None
    """
    try:
        if not stats_widget or not hasattr(stats_widget, 'tableWidget_pipe'):
            return None

        table = stats_widget.tableWidget_pipe
        if not table:
            return None

        max_nominal_size = None
        max_numeric_value = 0
        last_row = table.rowCount() - 1  # 排除最后空行

        # 定义需要匹配的管口所属元件关键词
        target_belong_keywords = ["管箱圆筒", "外头盖圆筒"]

        for row in range(last_row):
            # 获取管口所属元件列（第11列，索引为10）
            pipe_belong_item = table.item(row, 10)
            if not pipe_belong_item:
                continue

            pipe_belong_text = pipe_belong_item.text().strip()
            if not pipe_belong_text:
                continue

            # 检查管口所属元件是否包含"管箱圆筒"或"外头盖圆筒"
            is_target_belong = any(keyword in pipe_belong_text for keyword in target_belong_keywords)
            if not is_target_belong:
                continue  # 跳过不符合条件的管口

            # 获取公称尺寸列（第5列，索引为4）
            nominal_size_item = table.item(row, 4)
            if not nominal_size_item:
                continue

            nominal_size_text = nominal_size_item.text().strip()
            if not nominal_size_text:
                continue

            # 获取公称尺寸的数值用于比较大小
            nominal_size_value = get_nominal_size_numeric_value(nominal_size_text, stats_widget)
            if nominal_size_value is not None and nominal_size_value > max_numeric_value:
                max_numeric_value = nominal_size_value
                max_nominal_size = nominal_size_text  # 保存原始的公称尺寸文本

        return max_nominal_size

    except Exception as e:
        print(f"获取界面最大管口公称尺寸失败: {e}")
        return None


"""获取界面中管口所属元件为“管板”的公称尺寸的最大值"""
def get_max_tubesheet_nominal_size_from_ui(stats_widget):
    """
    获取界面中管口所属元件包含“管板”的公称尺寸的最大值
    :param stats_widget: Stats类实例
    :return: 最大公称尺寸的文本，如果无法获取则返回None
    """
    try:
        if not stats_widget or not hasattr(stats_widget, 'tableWidget_pipe'):
            return None

        table = stats_widget.tableWidget_pipe
        if not table:
            return None

        max_nominal_size = None
        max_numeric_value = 0
        last_row = table.rowCount() - 1  # 排除最后空行

        for row in range(last_row):
            belong_item = table.item(row, 10)  # 第11列
            if not belong_item:
                continue
            belong_text = belong_item.text().strip()
            if not belong_text or "管板" not in belong_text:
                continue

            nominal_item = table.item(row, 4)  # 第5列
            if not nominal_item:
                continue
            nominal_text = nominal_item.text().strip()
            if not nominal_text:
                continue

            nominal_value = get_nominal_size_numeric_value(nominal_text, stats_widget)
            if nominal_value is not None and nominal_value > max_numeric_value:
                max_numeric_value = nominal_value
                max_nominal_size = nominal_text

        return max_nominal_size
    except Exception:
        return None


"""获取公称尺寸DN的数值"""
def get_nominal_size_numeric_value(nominal_size_text, stats_widget=None):
    """
    获取公称尺寸的数值，如果当前单位是NPS则转换为DN数值
    :param nominal_size_text: 公称尺寸文本
    :param stats_widget: Stats类实例，用于获取单位类型
    :return: 数值或None（如果转换失败）
    """
    try:
        # 如果当前单位是NPS，需要转换为DN进行验证
        if stats_widget:
            current_unit_types = get_current_unit_types_from_ui(stats_widget)
            size_type = current_unit_types.get("公称尺寸类型", "DN")

            if size_type == "NPS":
                # 直接调用funcs_pipe_comboBox_units.py中的函数进行NPS到DN转换
                from modules.guankoudingyi.funcs.funcs_pipe_comboBox_units import load_nps_to_dn_map
                nps_to_dn_map = load_nps_to_dn_map()
                # 使用原始的nominal_size_text（包含NPS）进行查找
                if nominal_size_text in nps_to_dn_map:
                    return float(nps_to_dn_map[nominal_size_text])
                else:
                    # 如果映射表中找不到，返回None表示转换失败
                    return None
            else:
                # DN单位，清理文本后转换为数值
                nominal_size_clean = nominal_size_text.replace("DN", "").strip()
                try:
                    return float(nominal_size_clean)
                except ValueError:
                    return None
        else:
            # 没有stats_widget时，假设是DN单位
            nominal_size_clean = nominal_size_text.replace("DN", "").strip()
            try:
                return float(nominal_size_clean)
            except ValueError:
                return None

    except Exception as e:
        return None


"""查询公称尺寸表得到公称尺寸对应的接管实际外径数值"""
def get_component_nominal_size_od(nominal_size_value, product_id=None, stats_widget=None, size_type_override=None):
    """
    查询公称尺寸表得到公称尺寸对应的接管实际外径数值
    :param nominal_size_value: 公称尺寸值（DN或NPS）
    :param product_id: 产品ID，用于获取公称尺寸类型
    :param stats_widget: Stats类实例，用于从界面获取单位类型
    :return: 对应的接管实际外径数值，如果无法获取则返回None
    """
    try:
        # 优先使用外部显式指定的单位覆盖
        if size_type_override in ("DN", "NPS"):
            size_type = size_type_override
        else:
            # 优先从界面组件获取公称尺寸类型，如果获取不到则从数据库获取
            if stats_widget:
                current_unit_types = get_current_unit_types_from_ui(stats_widget)
                size_type = current_unit_types.get("公称尺寸类型", "DN")
            elif product_id:
                # 兼容性处理：如果没有传入stats_widget，仍然从数据库读取
                unit_types = get_unit_types_from_db(product_id)
                size_type = unit_types.get("公称尺寸类型", "DN") if unit_types else "DN"
            else:
                # 如果都没有提供，无法确定类型，返回None
                return None

        conn = get_connection(**db_config_1)
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # 判断公称尺寸类型：如果是DN则用DN查询，否则用NPS查询
        if size_type == "DN":
            column_name = "DN"
        else:
            column_name = "NPS"

        # 如果是浮点数，转换为整数再转字符串，避免100.0格式
        if isinstance(nominal_size_value, float):
            query_value = str(int(nominal_size_value))
        else:
            query_value = str(nominal_size_value).strip()

        # 根据类型选择对应的列进行查询

        sql = f"""
            SELECT OD FROM 公称尺寸表
            WHERE `{column_name}` = %s
            LIMIT 1
        """
        cursor.execute(sql, (query_value,))
        row = cursor.fetchone()

        cursor.close()
        conn.close()

        if row:
            try:
                # 使用字典方式访问接管实际外径OD字段
                od_value = float(row['OD'])
                return od_value
            except (ValueError, TypeError, KeyError):
                return None
        else:
            return None

    except Exception as e:
        print(f"查询公称尺寸表接管实际外径数值失败: {e}")
        return None


"""获取换热管长度"""
def get_heat_exchanger_tube_length(product_id):
    """
    获取换热管长度
    根据当前产品ID查询数据库中产品设计活动库的产品设计活动表_布管参数表，
    判断当前产品ID是否存在对应参数名称是"换热管公称长度 LN"的参数，
    如果有，取对应的参数值，如果没有，设定其默认值为4500

    :param product_id: 产品ID
    :return: 换热管长度（单位：mm），如果查询失败返回默认值4500
    """
    try:
        # 获取数据库连接
        connection = get_connection(**db_config_2)
        if not connection:
            print("获取数据库连接失败，使用默认值4500")
            return 4500

        with connection.cursor() as cursor:
            # 查询产品设计活动表_布管参数表中是否存在"换热管公称长度 LN"参数
            sql = """
            SELECT 参数值 
            FROM 产品设计活动表_布管参数表 
            WHERE 产品ID = %s AND 参数名 = '换热管公称长度 LN'
            """

            cursor.execute(sql, (product_id,))
            result = cursor.fetchone()

            if result and result['参数值']:
                try:
                    # 尝试将参数值转换为浮点数
                    tube_length = float(result['参数值'])

                    return tube_length
                except (ValueError, TypeError):

                    return 4500
            else:
                print(f"产品ID {product_id} 未找到换热管公称长度参数，使用默认值4500")
                return 4500

    except Exception as e:

        return 4500
    finally:
        if 'connection' in locals():
            connection.close()


"""管口附件下拉框实现多选"""
from PyQt5.QtWidgets import QStyledItemDelegate

class MultiSelectComboDelegate(QStyledItemDelegate):
    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.items = items or ["None"]

    def createEditor(self, parent, option, index):
        editor = CheckableComboBox(parent)
        editor.addItems(self.items)
        return editor

    def setEditorData(self, editor, index):
        value = index.data()
        # 处理空值：如果值为 None 或空字符串，都视为未选择
        if value is None:
            value = " "
        value = str(value).strip()
        # 使用与保存/显示一致的分隔符 ";"，避免二次编辑时已选内容无法还原
        selected = value.split(";") if value else []
        # 先清除所有选中状态
        for i in range(editor.count()):
            item = editor.model().item(i)
            item.setCheckState(Qt.Unchecked)
        # 然后根据值设置选中状态
        for i in range(editor.count()):
            item = editor.model().item(i)
            if item.text() in selected:
                item.setCheckState(Qt.Checked)
        editor._update_text()

    def setModelData(self, editor, model, index):
        checked_items = editor.checkedItems()
        # 如果没有选中任何项，设置为空字符串，确保能保存空值到数据库
        value = ";".join(checked_items) if checked_items else " "
        model.setData(index, value)


class CheckableComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setPlaceholderText("")
        self.view().pressed.connect(self.handle_item_pressed)

    def addItems(self, items):
        super().clear()
        for text in items:
            self.addItem(text)
            item = self.model().item(self.count() - 1, 0)
            item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Unchecked)

    def handle_item_pressed(self, index):
        item = self.model().itemFromIndex(index)
        item.setCheckState(
            Qt.Checked if item.checkState() == Qt.Unchecked else Qt.Unchecked
        )
        self._update_text()

    def _update_text(self):
        checked = [
            self.itemText(i)
            for i in range(self.count())
            if self.model().item(i).checkState() == Qt.Checked
        ]
        self.lineEdit().setText(";".join(checked))

    def checkedItems(self):
        return [
            self.itemText(i)
            for i in range(self.count())
            if self.model().item(i).checkState() == Qt.Checked
        ]



