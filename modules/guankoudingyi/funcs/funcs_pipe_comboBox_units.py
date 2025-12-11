import pymysql
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox, QLabel, QComboBox, QTableWidgetItem
from modules.guankoudingyi.db_cnt import get_connection, db_config_1, db_config_2
from modules.guankoudingyi.funcs.funcs_pipe_comboBox_value import get_standard_flange_pressure_level_default_value,get_weld_end_spec_sch_options, ComboBoxDelegate, update_nominal_size_delegate_options
from modules.guankoudingyi.funcs.pipe_get_units_types import get_unit_types_from_db, get_current_unit_types_from_ui


"""三个类型的选择会有对应的事件发生，这里是对下拉框产生的事件处理"""
def setup_unit_selection_handlers(stats_widget):
    """
    设置单位选择下拉框的事件处理器
    监听界面变化并触发相应的UI更新，不再直接保存到数据库
    :param stats_widget: Stats类实例
    """
    product_id = stats_widget.product_id

    # 从数据库获取现有的单位类型设置用于初始化界面
    existing_types = get_unit_types_from_db(product_id)

    def create_handler(field_name, combo_box):
        """
        为每个下拉框创建独立的处理函数
        只处理界面逻辑，不保存到数据库
        """
        def handler(index):
            unit_value = combo_box.currentText()
            
            # 公称压力类型切换时，刷新法兰标准和压力等级
            if field_name == "公称压力类型":
                stats_widget.current_pressure_type = unit_value  # ✨记录最新选择值

                # 获取新默认值和下拉选项
                _, default_standard, default_level = get_standard_flange_pressure_level_default_value(product_id, stats_widget)
                table = stats_widget.tableWidget_pipe

                for row in range(table.rowCount()):
                    # 只刷新有管口代号的行
                    code_item = table.item(row, 1)
                    if not code_item or not code_item.text().strip():
                        continue
                    # 法兰标准
                    standard_item = QTableWidgetItem(default_standard)
                    standard_item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(row, 5, standard_item)
                    # 压力等级
                    level_item = QTableWidgetItem(default_level)
                    level_item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(row, 6, level_item)

                    # 法兰型式列 (第7列)
                    flange_type_item = QTableWidgetItem('')  # 设置为空值
                    flange_type_item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(row, 7, flange_type_item)

                    # 密封面型式列 (第8列)
                    sealing_surface_item = QTableWidgetItem('')  # 设置为空值
                    sealing_surface_item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(row, 8, sealing_surface_item)

            # 如果是公称尺寸类型，调用转换数值函数，类型切换，数值转换
            elif field_name == "公称尺寸类型":
                convert_pipe_nominal_sizes(stats_widget)
                # 更新公称尺寸列的下拉框选项
                update_nominal_size_delegate_options(stats_widget)
            # 焊端规格单位切换逻辑
            elif field_name == "焊端规格类型":
                col_index = 9
                if unit_value == "mm":
                    table = stats_widget.tableWidget_pipe
                    # ✅ 直接用缓存好的 delegate
                    delegate = stats_widget.pipe_column_delegates[col_index]
                    delegate.setItems(["程序推荐"])
                    delegate.editable = True  # 允许可编辑
                    table.setItemDelegateForColumn(col_index, delegate)

                    for row in range(table.rowCount() - 1):
                        item = QTableWidgetItem("程序推荐")
                        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)
                        item.setTextAlignment(Qt.AlignCenter)
                        table.setItem(row, col_index, item)
                elif unit_value == "Sch":
                    # ✅ 【改动点1】用缓存的 pipe_column_delegates[col_index] 代理，不再重复创建 ComboBoxDelegate
                    options = get_weld_end_spec_sch_options()
                    delegate = stats_widget.pipe_column_delegates[col_index]
                    delegate.setItems(options)
                    table = stats_widget.tableWidget_pipe
                    for row in range(table.rowCount() - 1):
                        item = QTableWidgetItem("5S")
                        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)
                        item.setTextAlignment(Qt.AlignCenter)
                        table.setItem(row, col_index, item)

        return handler

    # ✅ 使用新的组件命名，不再使用findChild方式
    combo_components = [
        (stats_widget.combo_nominal_size_type, "公称尺寸类型"),
        (stats_widget.combo_pressure_level_type, "公称压力类型"), 
        (stats_widget.combo_weld_end_spec_type, "焊端规格类型")
    ]
    
    for combo, db_field_name in combo_components:
        if combo is not None:
            # 设置初始值（仅从数据库读取，不保存）
            if existing_types:
                # 如果数据库中有记录，使用数据库中的值
                db_value = existing_types[db_field_name]
                if db_value:
                    index = combo.findText(db_value)
                    if index >= 0:
                        combo.setCurrentIndex(index)
            
            # 为每个下拉框创建独立的处理函数实例
            handler = create_handler(db_field_name, combo)
            combo.currentIndexChanged.connect(handler)

"""公称尺寸两个单位类型之间的单位转换"""
def convert_pipe_nominal_sizes(stats_widget):
    """
    根据界面选择的公称尺寸单位类型，将管口表格中的公称尺寸列值进行转换（如 DN -> NPS）。
    """
    try:
        table = stats_widget.tableWidget_pipe

        # 1. 从界面组件获取当前选择的单位类型（如 DN 或 NPS）
        if not hasattr(stats_widget, 'combo_nominal_size_type') or stats_widget.combo_nominal_size_type is None:
            QMessageBox.warning(stats_widget, "错误", "无法获取公称尺寸单位选择组件")
            return
        size_unit = stats_widget.combo_nominal_size_type.currentText()  # 从界面组件获取当前选择

        # 2. 构建尺寸映射（从元件库读取）
        conn = get_connection(**db_config_1)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("SELECT DN, NPS FROM 公称尺寸表")
        size_map = cursor.fetchall()

        # 3. 构建转换字典：DN -> NPS 或 NPS -> DN
        dn_to_nps = {str(row["DN"]): row["NPS"] for row in size_map if row["DN"] is not None and row["NPS"]}
        nps_to_dn = {row["NPS"]: str(row["DN"]) for row in size_map if row["DN"] is not None and row["NPS"]}

        # 4. 扫描表格行，进行单位转换
        for row in range(table.rowCount()):
            item = table.item(row, 4)  # 第5列是"公称尺寸"（新位置）
            if not item:
                continue
            original = item.text().strip()
            if not original:
                continue

            # 执行转换
            converted = None
            if size_unit == "NPS":
                converted = dn_to_nps.get(original)
            elif size_unit == "DN":
                converted = nps_to_dn.get(original)

            if converted:
                item.setText(str(converted))  # 更新单元格显示

    except Exception as e:
        QMessageBox.warning(stats_widget, "错误", f"公称尺寸转换失败: {str(e)}")

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

"""绘图部分统一采用公称尺寸类型是DN时的数值进行绘制"""
def load_nps_to_dn_map():
    """
    从数据库读取 NPS → DN 映射表，用于绘图时将NPS值转换为DN值
    绘图部分统一使用DN数值进行绘制
    """
    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config_1)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("SELECT DN, NPS FROM 公称尺寸表 WHERE DN IS NOT NULL AND NPS IS NOT NULL")
        results = cursor.fetchall()
        return {row["NPS"]: row["DN"] for row in results if row["NPS"] and row["DN"]}
    except Exception as e:
        print(f"[ERROR] 加载NPS→DN映射表失败: {e}")
        return {}
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

