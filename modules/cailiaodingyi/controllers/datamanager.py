from functools import partial

from PyQt5 import QtWidgets, QtCore
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QTableWidgetItem, QTableWidget, QComboBox, QDoubleSpinBox, QMessageBox, QLineEdit, QLabel

from modules.cailiaodingyi.demo import NoWheelComboBoxFilter
from modules.cailiaodingyi.funcs.funcs_pdf_change import (
    load_element_additional_data,
    load_guankou_define_data,
    load_guankou_para_data,
    insert_or_update_element_data,
    insert_or_update_guankou_material_data,
    insert_or_update_guankou_para_data,
    insert_or_update_element_para_data,
    update_param_table_data,
    update_left_table_db_from_param_table,
    toggle_covering_fields,
    load_element_data_by_product_id,
    load_element_additional_data_by_product,
    update_guankou_define_data,
    update_guankou_define_status,
    load_updated_guankou_define_data,
    update_guankou_param,
    load_updated_guankou_param_data,
    load_guankou_para_data_leibie, is_all_guankou_parts_defined, get_filtered_material_options, save_image,
    query_image_from_database, get_dependency_mapping_from_db, toggle_dependent_fields,
    toggle_dependent_fields_multi_value, query_param_by_component_id, get_gasket_param_from_db,
    get_design_params_from_db, get_gasket_contact_dims_from_db, query_template_id, query_guankou_image_from_database,
    update_element_para_data, toggle_dependent_fields_complex, get_corrosion_allowance_from_db
)
from modules.cailiaodingyi.funcs.funcs_pdf_input import (
    load_elementoriginal_data,
    move_guankou_to_first,
    load_guankou_material_detail,
    query_template_guankou_para_data,
    query_template_element_para_data,
    load_material_dropdown_values, query_guankou_define_data_by_category, update_template_input_editable_state,
    load_guankou_material_detail_template, get_options_for_param, get_all_param_name, is_flatcover_trim_param_applicable
)
from modules.condition_input.funcs.funcs_cdt_input import sync_design_params_to_element_params
    # sync_corrosion_to_guankou_param


# def apply_combobox_to_table(table: QTableWidget, column_data_map: dict, viewer_instance, category_label: str):
#     """
#     给管口零件表格的定义设置下拉框
#     """
#     # 字段列索引和字段名映射
#     col_to_field = {1: '材料类型', 2: '材料牌号', 3: '材料标准', 4: '供货状态'}
#
#     # 初始化下拉框
#     for row in range(table.rowCount()):
#         for col, options in column_data_map.items():
#             current_text = table.item(row, col).text().strip() if table.item(row, col) else ""
#
#             # 创建下拉框
#             combo = QComboBox()
#             combo.addItem("")
#             combo.addItems(options)
#             combo.setEditable(True)
#             combo.lineEdit().setAlignment(Qt.AlignCenter)
#             combo.setStyleSheet("""
#                 QComboBox {
#                     border: none;
#                     background-color: transparent;
#                     font-size: 9pt;
#                     font-family: "Microsoft YaHei";
#                     padding-left: 2px;
#                 }
#             """)
#
#             combo.blockSignals(True)
#             index = combo.findText(current_text.strip(), Qt.MatchFixedString)
#             if index >= 0:
#                 combo.setCurrentIndex(index)
#             else:
#                 combo.setCurrentIndex(0)
#             combo.blockSignals(False)
#
#             table.setItem(row, col, None)
#             table.setCellWidget(row, col, combo)
#
#             # 绑定保存逻辑
#             combo.currentIndexChanged.connect(partial(on_combo_changed, viewer_instance, table, col, category_label))
#
#
#             # 绑定联动逻辑（只绑定，不执行）
#             if col in col_to_field:
#                 combo.currentTextChanged.connect(partial(on_material_field_changed_row, table, row))
#
#     # 👉 使用 QTimer 延后触发联动初始化，避免信号冲突
#     def delayed_linkage():
#         for row in range(table.rowCount()):
#             on_material_field_changed_row(table, row)
#
#     QTimer.singleShot(0, delayed_linkage)
def apply_combobox_to_table(table: QTableWidget, column_data_map: dict, viewer_instance, category_label: str):
    """
    设置“管口材料分类”表格的四字段联动下拉框（列式结构），绑定保存 + 联动逻辑
    """
    col_to_field = {1: '材料类型', 2: '材料牌号', 3: '材料标准', 4: '供货状态'}
    field_to_col = {v: k for k, v in col_to_field.items()}

    for row in range(table.rowCount()):
        for col, options in column_data_map.items():
            current_text = table.item(row, col).text().strip() if table.item(row, col) else ""

            combo = QComboBox()
            combo.setEditable(True)
            combo.addItem("")
            combo.addItems(options)
            combo.lineEdit().setAlignment(Qt.AlignCenter)
            combo.setStyleSheet("""
                QComboBox {
                    border: none;
                    background-color: transparent;
                    font-size: 9pt;
                    font-family: "Microsoft YaHei";
                    padding-left: 2px;
                }
            """)
            combo.full_options = options.copy()

            combo.blockSignals(True)
            combo.installEventFilter(NoWheelComboBoxFilter(combo))
            index = combo.findText(current_text.strip(), Qt.MatchFixedString)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

            table.setItem(row, col, None)
            table.setCellWidget(row, col, combo)

            # ✨设置 tooltip
            for i in range(combo.count()):
                combo.setItemData(i, combo.itemText(i), Qt.ToolTipRole)

            # ✅ 设置下拉框宽度适配最长项
            max_text_width = max([combo.fontMetrics().width(text) for text in combo.full_options] + [0])
            combo.view().setMinimumWidth(max_text_width + 40)  # 加40避免贴边

            # ✅ 保存逻辑
            combo.currentIndexChanged.connect(partial(
                on_combo_changed, viewer_instance, table, col, category_label
            ))

            # ✅ 联动逻辑（行联动，点击或选值均触发）
            if col in col_to_field:
                combo.currentTextChanged.connect(partial(
                    on_material_field_changed_row, table, row
                ))

    # ✅ 初始化完成后延迟触发一次联动（防止加载时闪跳）
    def delayed_init():
        for row in range(table.rowCount()):
            on_material_field_changed_row(table, row)

    QTimer.singleShot(0, delayed_init)


# def on_material_field_changed_row(table: QTableWidget, row: int):
#     material_fields = {
#         '材料类型': 1,
#         '材料牌号': 2,
#         '材料标准': 3,
#         '供货状态': 4
#     }
#     col_to_field = {v: k for k, v in material_fields.items()}
#     selected = {}
#
#     # 获取当前行已有值
#     for col, field in col_to_field.items():
#         combo = table.cellWidget(row, col)
#         if isinstance(combo, QComboBox):
#             val = combo.currentText().strip()
#             if val:
#                 selected[field] = val
#
#     filtered_options = get_filtered_material_options(selected)
#
#     # 更新字段
#     for col, field in col_to_field.items():
#         combo = table.cellWidget(row, col)
#         if not isinstance(combo, QComboBox):
#             continue
#         current_val = combo.currentText().strip()
#         new_options = filtered_options.get(field, [])
#
#         combo.blockSignals(True)
#         combo.clear()
#         combo.addItem("")
#         combo.addItems(new_options)
#         if current_val in new_options:
#             combo.setCurrentText(current_val)
#         else:
#             combo.setCurrentIndex(0)
#         combo.blockSignals(False)
def on_material_field_changed_row(table: QTableWidget, row: int):
    material_fields = {
        '材料类型': 1,
        '材料牌号': 2,
        '材料标准': 3,
        '供货状态': 4
    }
    col_to_field = {v: k for k, v in material_fields.items()}
    field_to_col = {v: k for k, v in col_to_field.items()}
    selected = {}
    combo_map = {}
    cleared_fields = set()  # ⬅️ 新增：记录哪些字段被清空

    sender = table.sender()
    sender_field = ""

    # 读取当前行所有字段值 & 控件
    for col, field in col_to_field.items():
        combo = table.cellWidget(row, col)
        if isinstance(combo, QComboBox):
            combo_map[field] = combo
            val = combo.currentText().strip()
            if val:
                selected[field] = val
            if combo is sender:
                sender_field = field

    # 强制清空材料类型变更时的后三项（无论值合不合法）
    if sender_field == "材料类型":
        for field in ["材料牌号", "材料标准", "供货状态"]:
            for r in range(table.rowCount()):
                param_item = table.item(r, 0)
                if param_item and param_item.text().strip() == field:
                    combo = table.cellWidget(r, 1)
                    if isinstance(combo, QComboBox):
                        combo.blockSignals(True)
                        combo.clear()
                        combo.addItem("")
                        combo.setCurrentIndex(0)
                        combo.lineEdit().clear()  # ✅ 关键：清除 lineEdit 显示内容
                        combo.blockSignals(False)
                    table.setItem(r, 1, QTableWidgetItem(""))  # 确保 TableItem 也清空
                    break

    # ✅ 材料牌号改动 → 若不兼容 → 清空标准、供货状态
    if sender_field == "材料牌号" and all(k in selected for k in material_fields.keys()):
        filter_basis = {
            "材料类型": selected["材料类型"],
            "材料牌号": selected["材料牌号"]
        }
        valid = get_filtered_material_options(filter_basis)
        for field in ['材料标准', '供货状态']:
            current_val = selected.get(field, "")
            if current_val not in valid.get(field, []):
                combo = combo_map[field]
                combo.blockSignals(True)
                combo.clear()
                combo.addItem("")
                table.setItem(row, field_to_col[field], QTableWidgetItem(""))  # 清除文本
                combo.blockSignals(False)
                cleared_fields.add(field)  # ⬅️ 标记为清空
                selected.pop(field, None)

    # ✅ 联动刷新
    for field, combo in combo_map.items():
        current_val = combo.currentText().strip()
        all_options = getattr(combo, "full_options", [])

        # 生成筛选条件
        if field == "材料类型":
            valid_options = all_options  # 不限制
        elif field == "材料牌号":
            filter_basis = {
                "材料类型": selected.get("材料类型", "")
            }
            valid_options = get_filtered_material_options(filter_basis).get(field, [])
        elif field == "材料标准":
            filter_basis = {
                "材料类型": selected.get("材料类型", ""),
                "材料牌号": selected.get("材料牌号", "")
            }
            valid_options = get_filtered_material_options(filter_basis).get(field, [])
        elif field == "供货状态":
            filter_basis = {
                "材料类型": selected.get("材料类型", ""),
                "材料牌号": selected.get("材料牌号", ""),
                "材料标准": selected.get("材料标准", "")
            }
            valid_options = get_filtered_material_options(filter_basis).get(field, [])
        else:
            valid_options = []

        combo.blockSignals(True)
        combo.clear()
        combo.addItem("")
        combo.addItems(valid_options)

        # ✅ 每次材料类型变更后，强制清空后三项；其余字段则根据选项数量决定是否自动填入
        if sender_field == "材料类型" and field in ["材料牌号", "材料标准", "供货状态"]:
            if len(valid_options) == 1:
                combo.blockSignals(True)
                combo.setCurrentText(valid_options[0])
                combo.blockSignals(False)
            else:
                combo.setCurrentIndex(0)
                combo.lineEdit().clear()
                table.setItem(row, field_to_col[field], QTableWidgetItem(""))
        elif field not in cleared_fields:
            # 非材料类型发起时：若旧值合法 → 保留；否则清空
            if current_val in valid_options:
                combo.setCurrentText(current_val)
            elif len(valid_options) == 1:
                combo.setCurrentText(valid_options[0])
            else:
                combo.setCurrentIndex(0)
                combo.lineEdit().clear()
                table.setItem(row, field_to_col[field], QTableWidgetItem(""))

        combo.blockSignals(False)


def on_combo_changed(viewer_instance, table, col, category_label):

    combo = table.sender()
    if not isinstance(combo, QComboBox):
        return

    for row in range(table.rowCount()):
        if table.cellWidget(row, col) == combo:
            break
    else:
        print("未找到 combo 所在行，跳过")
        return

    new_value = combo.currentText().strip()
    combo.setToolTip(new_value)
    combo.lineEdit().setToolTip(new_value)
    combo.currentTextChanged.connect(lambda text, c=combo: (
        c.setToolTip(text),
        c.lineEdit().setToolTip(text)
    ))

    # print(f"更新的数据: {new_value}")
    # print(f"找到行号: {row}")
    # print(f"{viewer_instance.guankou_define_info}")

    try:
        clicked_guankou_define_data = viewer_instance.guankou_define_info[row]
        # print(f"当前行数据: {clicked_guankou_define_data}")
    except Exception as e:
        print(f"[错误] 获取行数据失败: {e}")
        return

    try:
        guankou_id = clicked_guankou_define_data.get("管口零件ID", None)
        # print(f"获取到的管口零件ID: {guankou_id}")
    except Exception as e:
        print(f"[错误] 获取管口零件ID失败: {e}")
        return

    column_map = {1: '材料类型', 2: '材料牌号', 3: '材料标准', 4: '供货状态'}
    field_name = column_map.get(col, "未知字段")
    # print(f"更新的字段: {field_name}")

    # guankou_additional_info = load_guankou_para_data(guankou_id)
    update_guankou_define_data(viewer_instance.product_id, new_value, field_name, guankou_id, category_label)

    element_name = "管口"

    if (is_all_guankou_parts_defined(viewer_instance.product_id)):
        define_status = "已定义"
    else:
        define_status = "未定义"

    update_guankou_define_status(viewer_instance.product_id, element_name, define_status)
    update_element_info = load_element_data_by_product_id(viewer_instance.product_id)
    update_element_info = move_guankou_to_first(update_element_info)
    viewer_instance.render_data_to_table(update_element_info)
    # 存为模板
    # update_template_input_editable_state(viewer_instance)






# def on_guankou_param_changed(self, row, col, product_id):
#
#     item = self.tableWidget_guankou_param.item(row, col)
#     if not item:
#         return
#
#     new_value = item.text()
#     print(f"新的值{new_value}")
#
#     # 假设第0列是参数名，第1列是参数值
#     param_name = self.tableWidget_guankou_param.item(row, 0).text()
#     print(f"参数名{param_name}")
#     product_id = product_id
#
#     print(f"产品ID: {product_id}, 参数: {param_name}, 值: {new_value}")



def set_table_tooltips(table: QTableWidget):
    """
    为 QTableWidget 所有单元格设置 tooltip（悬浮提示），包含普通单元格和下拉框。
    """
    for row in range(table.rowCount()):
        for col in range(table.columnCount()):
            # 如果单元格是 QComboBox（widget）
            cell_widget = table.cellWidget(row, col)
            if isinstance(cell_widget, QComboBox):
                current_text = cell_widget.currentText()
                if current_text.strip():
                    cell_widget.setToolTip(current_text)
            else:
                item = table.item(row, col)
                if item and item.text().strip():
                    item.setToolTip(item.text())


def apply_paramname_dependent_combobox(table: QTableWidget,
                                       param_col: int,
                                       value_col: int,
                                       param_options: dict,
                                       component_info: dict = None,
                                       viewer_instance = None):
    """
    设置除管口外的零件对应参数信息的下拉框，包括“是否有覆层”固定选项
    """
    material_fields = ['材料类型', '材料牌号', '材料标准', '供货状态']

    for row in range(table.rowCount()):
        try:
            param_item = table.item(row, param_col)
            param_name = param_item.text().strip() if param_item else ""

            # ✅ 材料字段（支持联动）
            if param_name in param_options and param_name in material_fields:
                options = param_options[param_name]

                value_item = table.item(row, value_col)
                current_value = value_item.text().strip() if value_item else ""

                combo = QComboBox()
                combo.addItem("")
                combo.setEditable(True)
                combo.lineEdit().setAlignment(Qt.AlignCenter)
                combo.setStyleSheet("""
                                QComboBox {
                                    border: none;
                                    background-color: transparent;
                                    font-size: 9pt;
                                    font-family: "Microsoft YaHei";
                                    padding-left: 2px;
                                }
                            """)
                combo.addItems(options)
                combo.full_options = options.copy()

                matched = False
                for i in range(combo.count()):
                    if combo.itemText(i).strip() == current_value:
                        combo.setCurrentIndex(i)
                        matched = True
                        break
                if not matched:
                    combo.setCurrentIndex(0)

                table.setItem(row, value_col, None)
                table.setCellWidget(row, value_col, combo)
                combo.currentTextChanged.connect(partial(
                    on_material_combobox_changed, table, row, param_col, value_col, 2
                ))
                QTimer.singleShot(0, lambda r=row: on_material_combobox_changed(
                    table, r, param_col, value_col, 2
                ))

            if param_name == "材料类型":
                # 绑定联动逻辑：材料类型为“钢锻件”时，显示“锻件级别”
                combo.currentTextChanged.connect(
                    partial(toggle_dependent_fields, table, combo, "钢锻件", ["锻件级别"], logic="==")
                )
                toggle_dependent_fields(table, combo, "钢锻件", ["锻件级别"], logic="==")

                # ⚠ 如果当前不是“钢锻件”，则清空“锻件级别”字段并写入数据库
                def clear_forging_level_if_needed(val):
                    if val.strip() != "钢锻件":
                        for r in range(table.rowCount()):
                            pname_item = table.item(r, param_col)
                            if pname_item and pname_item.text().strip() == "锻件级别":
                                table.setRowHidden(r, True)

                                # 清空 UI 值
                                combo2 = table.cellWidget(r, value_col)
                                if isinstance(combo2, QComboBox):
                                    combo2.blockSignals(True)
                                    combo2.setCurrentIndex(0)
                                    combo2.lineEdit().clear()
                                    combo2.blockSignals(False)
                                table.setItem(r, value_col, QTableWidgetItem(""))

                                # 清空数据库
                                try:
                                    product_id = viewer_instance.product_id
                                    element_id = viewer_instance.clicked_element_data.get("元件ID", "")
                                    update_element_para_data(product_id, element_id, "锻件级别", "")
                                except Exception as e:
                                    print(f"[清空锻件级别失败] {e}")

                combo.currentTextChanged.connect(clear_forging_level_if_needed)
                # 初始化时触发一次
                clear_forging_level_if_needed(combo.currentText().strip())



            elif param_name == "是否添加覆层":
                value_item = table.item(row, value_col)
                current_value = value_item.text().strip() if value_item else ""
                combo = QComboBox()
                combo.addItems(["是", "否"])
                combo.setEditable(True)
                combo.setCurrentText("是" if current_value == "是" else "否")
                combo.lineEdit().setAlignment(Qt.AlignCenter)
                combo.setStyleSheet("""
                    QComboBox { border: none; background-color: transparent; font-size: 9pt; font-family: "Microsoft YaHei"; padding-left: 2px; }
                """)
                table.setItem(row, value_col, None)
                table.setCellWidget(row, value_col, combo)

                handler = make_on_covering_changed(component_info, viewer_instance, row)
                combo.currentTextChanged.connect(handler)

                handler(combo.currentText())
                combo.currentTextChanged.connect(
                    lambda _, c=combo, p=param_name: toggle_covering_fields(table, c, p)
                )
                toggle_covering_fields(table, combo, param_name)

            elif param_name in ["管程侧是否添加覆层", "壳程侧是否添加覆层"]:
                value_item = table.item(row, value_col)
                current_value = value_item.text().strip() if value_item else ""
                combo = QComboBox()
                combo.addItems(["是", "否"])
                combo.setEditable(True)
                combo.setCurrentText("是" if current_value == "是" else "否")
                combo.lineEdit().setAlignment(Qt.AlignCenter)
                combo.setStyleSheet("""
                    QComboBox { border: none; background-color: transparent; font-size: 9pt; font-family: "Microsoft YaHei"; padding-left: 2px; }
                """)

                table.setItem(row, value_col, None)
                table.setCellWidget(row, value_col, combo)
                combo.currentTextChanged.connect(
                    lambda _, c=combo, p=param_name: toggle_covering_fields(table, c, p)
                )
                toggle_covering_fields(table, combo, param_name)

        except Exception as e:
            print(f"[错误] 第{row}行处理失败：{e}")

    # ⚠ 统一在循环后绑定固定管板双字段逻辑
    if component_info and viewer_instance:
        fields = [table.item(r, param_col).text().strip() for r in range(table.rowCount())]
        if "管程侧是否添加覆层" in fields and "壳程侧是否添加覆层" in fields:
            handler = make_on_fixed_tube_covering_changed(component_info, viewer_instance, table, param_col, value_col)
            handler()

# ✅ 封装处理函数：绑定每行独立信息，避免闭包错误
def make_on_covering_changed(component_info_copy, viewer_instance_copy, row_index):
    def handler(value):
        try:
            print(f"[触发图片刷新] 当前 combo 值: '{value}'")
            value = value.strip()  # 清除空格
            has_covering = value == "是"
            print(f"→ 标准化后: 有无覆层 = {has_covering}")
            if not component_info_copy or not viewer_instance_copy:
                print(f"[跳过] 第{row_index}行：初始加载未绑定图示组件")
                return

            component_id = component_info_copy.get("元件ID")
            has_covering = value == "是"
            print(f"com{component_info_copy}")

            # ✅ 从 component_info 中取路径
            image_path = (
                component_info_copy.get("零件示意图覆层") if has_covering
                else component_info_copy.get("零件示意图")
            )

            # 针对非首次打开的处理逻辑
            if not image_path:
                template_name = component_info_copy.get("模板名称")
                element_id = component_info_copy.get("元件ID")
                has_covering = (value == "是")
                print(f"模板名称{template_name},元件ID{element_id}")
                print(f"有无覆层{has_covering}")

                # 查询数据库获取对应图片路径
                image_path = query_image_from_database(template_name, element_id, has_covering)
                print(f"材料库中图片{image_path}")

            if image_path:
                viewer_instance_copy.display_image(image_path)
                # viewer_instance.current_image_path = image_path

            else:
                print(f"[提示] 第{row_index}行元件无图片路径")

        except Exception as e:
            print(f"[错误] 第{row_index}行处理图片失败: {e}")

    return handler
#新增
def make_on_fixed_tube_covering_changed(component_info_copy, viewer_instance_copy, table, param_col, value_col):
    def refresh_image():
        try:
            # 获取两个ComboBox的最新状态
            guancheng_combo, kecheng_combo = None, None
            for r in range(table.rowCount()):
                pname = table.item(r, param_col).text().strip()
                if pname == "管程侧是否添加覆层":
                    guancheng_combo = table.cellWidget(r, value_col)
                elif pname == "壳程侧是否添加覆层":
                    kecheng_combo = table.cellWidget(r, value_col)

            if not guancheng_combo or not kecheng_combo:
                print("[警告] 未找到两个覆层控制ComboBox")
                return

            g_val = guancheng_combo.currentText().strip() == "是"
            k_val = kecheng_combo.currentText().strip() == "是"

            # 默认无覆层图（零件示意图）
            default_img = "16-固定管板无覆层.jpg" #!!!!!
            print(f"固定管板无覆层图{default_img}")
            if not default_img:
                template_name = component_info_copy.get("模板名称")
                element_id = component_info_copy.get("元件ID")
                default_img = query_image_from_database(template_name, element_id, has_covering=False)

            if not g_val and not k_val:
                img_to_show = default_img
            else:
                # 只有有覆层时，才取出覆层图片字段
                image_covering_str = component_info_copy.get("零件示意图覆层", "")
                if not image_covering_str:
                    template_name = component_info_copy.get("模板名称")
                    element_id = component_info_copy.get("元件ID")
                    image_covering_str = query_image_from_database(template_name, element_id, has_covering=True)

                image_list = image_covering_str.split('/')
                guancheng_img = image_list[0].strip() if len(image_list) > 0 else None
                kecheng_img = image_list[1].strip() if len(image_list) > 1 else None
                both_img = image_list[2].strip() if len(image_list) > 2 else None

                # 四种逻辑分支
                if g_val and not k_val:
                    img_to_show = guancheng_img or default_img
                elif not g_val and k_val:
                    img_to_show = kecheng_img or default_img
                elif g_val and k_val:
                    img_to_show = both_img or default_img
                else:
                    img_to_show = default_img

            if img_to_show:
                viewer_instance_copy.display_image(img_to_show)
                viewer_instance_copy.current_image_path = img_to_show
            else:
                viewer_instance_copy.label_part_image.clear()

        except Exception as e:
            print(f"[错误] 刷新图片失败: {e}")

    # 信号绑定仍保持稳定不重复绑定
    for r in range(table.rowCount()):
        pname = table.item(r, param_col).text().strip()
        if pname in ["管程侧是否添加覆层", "壳程侧是否添加覆层"]:
            combo = table.cellWidget(r, value_col)
            if combo and not hasattr(combo, "_already_bound_fixed_covering"):
                combo.currentTextChanged.connect(lambda _: refresh_image())
                setattr(combo, "_already_bound_fixed_covering", True)

    return refresh_image


def make_on_covering_changed_guankou(component_info_copy, viewer_instance_copy, row_index):
    def handler(value):
        try:
            print(f"[右上表触发图片刷新] 当前 combo 值: '{value}'")
            has_covering = value.strip() == "是"
            print(f"guankou{component_info_copy}")

            if not component_info_copy or not viewer_instance_copy:
                print(f"[跳过] 第{row_index}行：未绑定component_info")
                return

            # 右上表逻辑你现在已经有模板名和ID了
            template_name = component_info_copy.get("模板名称")
            template_id = query_template_id(template_name)
            element_id = component_info_copy.get("管口零件ID")  # 注意这里字段名你已经提供了

            # 查询数据库拿图片路径
            image_path = query_guankou_image_from_database(template_id, element_id, has_covering)
            print(f"材料库中图片路径: {image_path}")

            if image_path:
                viewer_instance_copy.display_image(image_path)
            else:
                print(f"[提示] 第{row_index}行无图片路径")

        except Exception as e:
            print(f"[右上表错误] 第{row_index}行图片处理失败: {e}")

    return handler




def on_material_combobox_changed(table: QTableWidget, changed_row: int, param_col: int, value_col: int, part_col: int):
    material_fields = ['材料类型', '材料牌号', '材料标准', '供货状态']

    part_item = table.item(changed_row, part_col)
    if not part_item:
        return
    part_name = part_item.text().strip()

    selected = {}
    combo_map = {}
    target_rows = []

    for row in range(table.rowCount()):
        if not table.item(row, part_col) or table.item(row, part_col).text().strip() != part_name:
            continue
        param_item = table.item(row, param_col)
        if not param_item:
            continue
        param_name = param_item.text().strip()

        if param_name in material_fields:
            combo = table.cellWidget(row, value_col)
            if not isinstance(combo, QComboBox):
                continue
            val = combo.currentText().strip()
            selected[param_name] = val
            combo_map[param_name] = combo
            target_rows.append((row, param_name, combo))

    changed_field = table.item(changed_row, param_col).text().strip()

    # --- 材料类型为空：直接清空其余三项
    if changed_field == "材料类型" and not selected.get("材料类型"):
        for f in ['材料牌号', '材料标准', '供货状态']:
            combo = combo_map.get(f)
            if combo:
                combo.blockSignals(True)
                combo.setCurrentIndex(0)
                table.setItem(changed_row, value_col, QTableWidgetItem(""))  # 清空表格文字
                combo.blockSignals(False)
        selected.clear()

    # --- 材料类型改动：不受限制，其它三项若不兼容就清空
    if changed_field == "材料类型":
        if all(f in selected for f in ['材料牌号', '材料标准', '供货状态']):
            for f in ['材料牌号', '材料标准', '供货状态']:
                test_basis = {
                    '材料类型': selected['材料类型'],
                    f: selected[f]
                }
                valid = get_filtered_material_options(test_basis).get(f, [])
                if selected[f] not in valid:
                    combo = combo_map[f]
                    combo.blockSignals(True)
                    combo.setCurrentIndex(0)
                    table.setItem(changed_row, value_col, QTableWidgetItem(""))  # 清空表格文字
                    combo.blockSignals(False)
                    selected.pop(f)

    # --- 材料牌号改动：只受材料类型限制，其它两项若不兼容就清空
    if changed_field == "材料牌号":
        if all(f in selected for f in ['材料类型', '材料牌号', '材料标准', '供货状态']):
            for f in ['材料标准', '供货状态']:
                test_basis = {
                    '材料类型': selected['材料类型'],
                    '材料牌号': selected['材料牌号'],
                    f: selected[f]
                }
                valid = get_filtered_material_options(test_basis).get(f, [])
                if selected[f] not in valid:
                    combo = combo_map[f]
                    combo.blockSignals(True)
                    combo.setCurrentIndex(0)
                    table.setItem(changed_row, value_col, QTableWidgetItem(""))  # 清空表格文字
                    combo.blockSignals(False)
                    selected.pop(f)

    # --- 联动字段刷新，自动带入唯一值
    for row, param_name, combo in target_rows:
        current_val = combo.currentText().strip()
        all_options = getattr(combo, "full_options", [])

        if param_name == "材料类型":
            valid_options = all_options  # 不受限制
        elif param_name == "材料牌号":
            filter_basis = {'材料类型': selected.get('材料类型', '')}
            valid_options = get_filtered_material_options(filter_basis).get(param_name, [])
        else:
            filter_basis = {
                '材料类型': selected.get('材料类型', ''),
                '材料牌号': selected.get('材料牌号', '')
            }
            valid_options = get_filtered_material_options(filter_basis).get(param_name, [])

        combo.blockSignals(True)
        combo.clear()
        combo.addItem("")
        combo.addItems(valid_options)

        # ✅ 自动填入逻辑（唯一时自动赋值并写入）
        if current_val in valid_options:
            combo.setCurrentText(current_val)
        elif len(valid_options) == 1:
            unique_val = valid_options[0]
            combo.setCurrentText(unique_val)
        else:
            combo.setCurrentIndex(0)
        combo.blockSignals(False)




def update_combo_options(combo: QComboBox, all_options, valid_options, current_val: str):
    combo.blockSignals(True)
    combo.clear()
    combo.addItem("")

    if valid_options:
        combo.addItems(valid_options)
    else:
        combo.addItem("（无匹配项）")
        combo.model().item(combo.count() - 1).setEnabled(False)

    valid_set = valid_options if valid_options else all_options
    if current_val and current_val in valid_set:
        combo.setCurrentText(current_val)
    else:
        combo.setCurrentIndex(0)

    combo.blockSignals(False)

    # ✅ 不再 emit 信号！只刷新显示
    combo.repaint()
    combo.update()

def bind_define_table_click(self, table_define, table_param, define_data, category_label):
    """
    绑定左侧定义表格点击事件，每次绑定前先断开旧连接，防止多次触发。
    """
    try:
        table_define.cellClicked.disconnect()
        print("[解绑成功] 原有 cellClicked 信号已断开")
    except Exception as e:
        print("[解绑跳过] 无旧信号或断开失败", e)

    def handler(row, col):
        self.on_define_table_clicked(row, define_data, table_param, category_label)

    table_define.cellClicked.connect(handler)
    print("[绑定完成] 已绑定新的 cellClicked 事件")



def load_data_by_template(viewer_instance, template_name):

    while viewer_instance.guankou_tabWidget.count() > 1:
        viewer_instance.guankou_tabWidget.removeTab(1)

    # 删除动态添加的 tab
    for tab in viewer_instance.dynamic_guankou_tabs:
        index = viewer_instance.guankou_tabWidget.indexOf(tab)
        if index != -1:
            viewer_instance.guankou_tabWidget.removeTab(index)
    viewer_instance.dynamic_guankou_tabs.clear()

    if not template_name:
        template_name = "None"

    # print(f"模板名称{template_name}")

    product_type = viewer_instance.product_type
    product_form = viewer_instance.product_form
    product_id = viewer_instance.product_id
    # print(f"产品ID{product_id}")

    if product_type and product_form:
        element_original_info = load_elementoriginal_data(template_name, product_type, product_form)

        viewer_instance.element_data = element_original_info  # 存储到实例变量
        # print(viewer_instance.element_data)

        if element_original_info:
            element_original_info = move_guankou_to_first(element_original_info)
            # print(f"选择模板后的元件列表{element_original_info}")
            viewer_instance.element_original_info_template = element_original_info
            # print(f"传入模板的元件列表{viewer_instance.element_original_info_template}")
            insert_or_update_element_data(element_original_info, product_id, template_name)

            viewer_instance.image_paths = [item.get('零件示意图', '') for item in element_original_info]
            viewer_instance.render_data_to_table(element_original_info)
            if len(element_original_info) > 0:
                first_part_image_path = element_original_info[0].get('零件示意图', '')
                viewer_instance.display_image(first_part_image_path)
                viewer_instance.first_element_id = element_original_info[0].get('元件ID', None)
            else:
                print(f"警告：模板 {template_name} 没有元素")

            # 获取更新模板后的对应的模板ID
            first_template_id = element_original_info[0].get('模板ID', None)
            # print(f"更新模板对应的模板ID{first_template_id}")

            # 获取当前模板ID对应的元件附加参数信息
            element_para_info = query_template_element_para_data(first_template_id)
            # print(f"更新后的零件列表信息{element_para_info}")
            # 更新产品活动库中的元件附加参数表
            insert_or_update_element_para_data(product_id, element_para_info)
            sync_design_params_to_element_params(product_id)

            # 获取当前模板ID对应的管口参数信息
            guankou_para_info = query_template_guankou_para_data(first_template_id)
            # print(f"更新后的管口零件参数信息{guankou_para_info}")
            # 将当前模板ID对应的管口参数信息写入到产品设计活动库中
            insert_or_update_guankou_para_data(product_id, guankou_para_info, template_name)
            # sync_corrosion_to_guankou_param(product_id)
            guankou_define_info = load_guankou_define_data(product_type, product_form, first_template_id)
            viewer_instance.guankou_define_info = guankou_define_info
            # 批量加上模板名称
            for item in viewer_instance.guankou_define_info:
                item['模板ID'] = first_template_id

            print("更新模板后管口定义信息：", viewer_instance.guankou_define_info)

            if guankou_define_info:
                render_guankou_param_table(viewer_instance, guankou_define_info)

                # 管口零件表格中的下拉框
                dropdown_data = load_material_dropdown_values()
                column_index_map = {'材料类型': 1, '材料牌号': 2, '材料标准': 3, '供货状态': 4}
                column_data_map = {column_index_map[k]: v for k, v in dropdown_data.items()}
                apply_combobox_to_table(viewer_instance.tableWidget_guankou_define, column_data_map, viewer_instance, category_label="管口材料分类1")
                set_table_tooltips(viewer_instance.tableWidget_guankou_define)

                #更新产品活动库中的管口零件材料表
                insert_or_update_guankou_material_data(guankou_define_info, product_id, template_name)
                # print(f"管口零件更新信息{guankou_define_info}")

                first_guankou_element = guankou_define_info[0]
                viewer_instance.guankou_define_info = guankou_define_info
                # print(f"第一条管口零件信息{first_guankou_element}")
                first_guankou_element_id = first_guankou_element.get("管口零件ID", None)
                # print(f"第一条管口零件对应的管口零件ID{first_guankou_element_id}")
                if first_guankou_element_id:
                    guankou_material_details = load_guankou_material_detail_template(first_guankou_element_id, first_template_id)
                    # print(f"第一个管口零件对应的参数信息{guankou_material_details}")
                    if guankou_material_details:
                        render_guankou_info_table(viewer_instance, guankou_material_details)
                        param_options = load_material_dropdown_values()
                        apply_paramname_dependent_combobox(
                            viewer_instance.tableWidget_para_define,
                            param_col=0,
                            value_col=1,
                            param_options=param_options
                        )
                        apply_paramname_dependent_combobox(
                            viewer_instance.tableWidget_guankou_param,
                            param_col=0,
                            value_col=1,
                            param_options=param_options
                        )
                        apply_gk_paramname_combobox(
                            viewer_instance.tableWidget_guankou_param,
                            param_col=0,
                            value_col=1
                        )


                        set_table_tooltips(viewer_instance.tableWidget_para_define)
                    else:
                        print("没有查到第一个管口零件材料的详细数据")
                else:
                    print("第一个管口零件没有ID")
            else:
                print("没有查到管口定义数据")

        else:
            viewer_instance.show_error_message("数据加载错误", f"模板 {template_name} 未找到元件数据")
    else:
        viewer_instance.show_error_message("输入错误", "产品类型或形式未找到")

    # 存为模板
    # update_template_input_editable_state(viewer_instance)
    bind_define_table_click(
        viewer_instance,
        viewer_instance.tableWidget_guankou_define,
        viewer_instance.tableWidget_guankou_param,
        guankou_define_info,  # 模板切换后的新数据
        category_label="管口材料分类1"
    )


    def force_select_guankou_and_trigger():
        print("✅ 自动选中管口并触发刷新")

        # 1. 先从左侧表格中查找“管口”行号
        table = viewer_instance.tableWidget_parts
        for r in range(table.rowCount()):
            item = table.item(r, 1)  # 第1列为“零件名称”
            if item and item.text().strip() == "管口":
                table.setCurrentCell(r, 0)
                viewer_instance.handle_table_click_guankou(r, 0)  # ✅ 切换到“管口”
                handle_table_click(viewer_instance, r, 0)  # ✅ 加载管口定义数据
                break

        # 2. 再模拟点击右侧“管口定义”表第一行
        QTimer.singleShot(10, lambda: viewer_instance.on_define_table_clicked(
            0,
            viewer_instance.guankou_define_info,
            viewer_instance.tableWidget_guankou_param,
            "管口材料分类1"
        ))

    QTimer.singleShot(10, force_select_guankou_and_trigger)


def render_common_material_editor(viewer_instance):
    """渲染多选统一编辑面板（4项下拉框）"""
    parts_table = viewer_instance.tableWidget_parts
    param_table = viewer_instance.tableWidget_para_define

    selected_indexes = parts_table.selectedIndexes()
    selected_rows = list(sorted(set(index.row() for index in selected_indexes)))

    if not selected_rows:
        return

    # 记录选中元件数据（便于确认时保存）
    viewer_instance.selected_elements_data = [
        viewer_instance.element_data[r] for r in selected_rows
    ]

    # 准备表格结构
    param_table.clear()
    param_table.setColumnCount(3)
    param_table.setRowCount(4)
    param_table.setHorizontalHeaderLabels(["参数名称", "参数值", "参数单位"])

    fields = ["材料类型", "材料牌号", "材料标准", "供货状态"]
    param_col = 0  # 参数名列
    value_col = 1
    part_col = 2

    # 读取下拉选项
    dropdown_data = load_material_dropdown_values()

    for i, field in enumerate(fields):
        # 参数名列
        name_item = QTableWidgetItem(field)
        name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        name_item.setTextAlignment(Qt.AlignCenter)
        param_table.setItem(i, 0, name_item)

        # 下拉框控件
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItem("")
        options = dropdown_data.get(field, [])
        combo.addItems(options)
        combo.full_options = options.copy()

        combo.lineEdit().setAlignment(Qt.AlignCenter)
        combo.setStyleSheet("""
            QComboBox {
                border: none;
                background-color: transparent;
                font-size: 9pt;
                font-family: "Microsoft YaHei";
                padding-left: 2px;
            }
        """)

        combo.currentTextChanged.connect(partial(
            on_material_combobox_changed, param_table, i, param_col, value_col, part_col
        ))

        # 添加下拉框到表格中
        param_table.setCellWidget(i, 1, combo)

        # 单位列空置
        unit_item = QTableWidgetItem("")
        unit_item.setFlags(Qt.ItemIsEnabled)
        unit_item.setTextAlignment(Qt.AlignCenter)
        param_table.setItem(i, 2, unit_item)

    param_table.setEditTriggers(QTableWidget.NoEditTriggers)


def handle_table_click(viewer_instance, row, col):
    """处理点击零件列表的逻辑"""
    # ✅ 统计当前选中的所有“行”索引
    selected_indexes = viewer_instance.tableWidget_parts.selectedIndexes()
    selected_rows = list(set(index.row() for index in selected_indexes))  # 去重得到选中行号列表

    # ✅ 收集所有选中元件的零件名称
    selected_names = [viewer_instance.element_data[r].get("零件名称", "") for r in selected_rows]

    # ✅ 判断是否包含“管口”或“垫片”
    if any("管口" in name or "垫片" in name for name in selected_names):
        print("[跳过多选] 包含‘管口’或‘垫片’，强制回退为单选")
        selected_rows = [row]  # 强制只保留当前点击行
        viewer_instance.tableWidget_parts.clearSelection()
        viewer_instance.tableWidget_parts.selectRow(row)

    # ✅ 重新读取点击行数据
    viewer_instance.selected_element_ids = []
    for index in selected_rows:
        element_id = viewer_instance.element_data[index].get("元件ID")
        if element_id:
            viewer_instance.selected_element_ids.append(element_id)

    if len(selected_rows) > 1:
        print("[多选模式] 渲染四字段材料信息")
        viewer_instance.label_part_image.clear()
        viewer_instance.stackedWidget.setCurrentIndex(1)
        render_common_material_editor(viewer_instance)
        return

    # 获取当前点击行的数据
    clicked_element_data = viewer_instance.element_data[row]  # 获取已经存储的行数据
    print(f"零件表格点击的行数据: {clicked_element_data}")
    viewer_instance.clicked_element_data = clicked_element_data

    # ✅ 设置当前激活元件ID（用于图片逻辑判断）
    viewer_instance.current_component_id = clicked_element_data.get("元件ID")
    viewer_instance.current_image_path = None  # ✅ 清除上一个图路径

    product_type = viewer_instance.product_type
    product_form = viewer_instance.product_form

    # print(product_type)

    # 获取元件ID和模板ID
    element_id = clicked_element_data.get("元件ID", None)
    template_id = clicked_element_data.get("模板ID", None)
    element_name = clicked_element_data.get("零件名称", "")
    # print(f"元件ID{element_id}")

    # 判断是否为管口
    if element_name == "管口":
        guankou_define_info = load_guankou_define_data(product_type, product_form, template_id, "管口材料分类1")
        updated_guankou_define_info = load_updated_guankou_define_data(viewer_instance.product_id, "管口材料分类1")
        render_guankou_param_table(viewer_instance, updated_guankou_define_info)
        viewer_instance.guankou_define_info = updated_guankou_define_info

        if not guankou_define_info:
            guankou_define_info = query_guankou_define_data_by_category(viewer_instance.product_id, "管口材料分类1")
            render_guankou_param_table(viewer_instance, guankou_define_info)
        else:
            guankou_ID = guankou_define_info[0].get("管口零件ID", None)
            # guankou_additional_info = load_guankou_para_data(guankou_ID, "管口材料分类1")
            guankou_additional_info = load_guankou_para_data(guankou_ID, viewer_instance.product_id, "管口材料分类1")

            if guankou_additional_info:
                render_guankou_info_table(viewer_instance, guankou_additional_info)

                # ✅ 关键改动：不论初始化还是切换，都插入控件
                param_options = load_material_dropdown_values()

                apply_paramname_dependent_combobox(
                    viewer_instance.tableWidget_guankou_param,
                    param_col=0,
                    value_col=1,
                    param_options=param_options,
                    component_info=viewer_instance.clicked_element_data,
                    viewer_instance=viewer_instance
                )
                apply_gk_paramname_combobox(
                    viewer_instance.tableWidget_guankou_param,
                    param_col=0,
                    value_col=1
                )
                set_table_tooltips(viewer_instance.tableWidget_guankou_param)
            else:
                guankou_para_table = viewer_instance.tableWidget_guankou_param
                guankou_para_table.setRowCount(0)
                guankou_para_table.clearContents()

        # ✅ 不管有没有零件信息，define表也一样正常渲染
        dropdown_data = load_material_dropdown_values()
        column_index_map = {'材料类型': 1, '材料牌号': 2, '材料标准': 3, '供货状态': 4}
        column_data_map = {column_index_map[k]: v for k, v in dropdown_data.items()}
        apply_combobox_to_table(viewer_instance.tableWidget_guankou_define, column_data_map, viewer_instance,
                                category_label="管口材料分类1")
        set_table_tooltips(viewer_instance.tableWidget_guankou_define)

        return

    if not element_id:
        print("没有找到有效的元件ID，跳过查询！")
        return

    additional_info = load_element_additional_data_by_product(viewer_instance.product_id, element_id)


    render_additional_info_table(viewer_instance, additional_info)
    param_options = load_material_dropdown_values()
    apply_paramname_dependent_combobox(
        viewer_instance.tableWidget_para_define,
        param_col=0,
        value_col=1,
        param_options=param_options,
        component_info=viewer_instance.clicked_element_data,
        viewer_instance=viewer_instance
    )
    apply_paramname_combobox(
        viewer_instance.tableWidget_para_define,
        param_col=0,
        value_col=1,
        viewer_instance=viewer_instance
    )
    mapping = get_dependency_mapping_from_db()
    apply_linked_param_combobox(viewer_instance.tableWidget_para_define, param_col=0, value_col=1, mapping=mapping)
    set_table_tooltips(viewer_instance.tableWidget_para_define)





def display_param_dict_on_right_panel(viewer_instance, param_dict):
    table = viewer_instance.tableWidget_para_define
    table.setRowCount(0)
    for i, (k, v) in enumerate(param_dict.items()):
        table.insertRow(i)
        table.setItem(i, 0, QTableWidgetItem(k))
        table.setItem(i, 1, QTableWidgetItem(str(v)))
        table.setItem(i, 2, QTableWidgetItem(""))  # 单位可补充


def clear_right_panel(viewer_instance):
    table = viewer_instance.tableWidget_para_define
    table.setRowCount(0)
    table.clearContents()

def on_confirm_param_update(viewer_instance):
    """除管口外零件确定按钮的绑定"""
    image_path = getattr(viewer_instance, "current_image_path", None)

    # 如果是多选，循环处理每个元件ID
    selected_ids = getattr(viewer_instance, "selected_element_ids", [])
    if len(selected_ids) > 1:
        print(f"[多选] 批量处理元件ID: {selected_ids}")
        for eid in selected_ids:
            update_param_table_data(
                viewer_instance.tableWidget_detail,
                viewer_instance.product_id,
                eid
            )
            # 通过 element_data 查找对应的零件名称
            part_info = next((item for item in viewer_instance.element_data if item["元件ID"] == eid), {})
            part_name = part_info.get("零件名称", "")
            update_left_table_db_from_param_table(
                viewer_instance.tableWidget_detail,
                viewer_instance.product_id,
                eid,
                part_name
            )
    else:
        # 原有的单选逻辑
        clicked_data = viewer_instance.clicked_element_data
        print(f"当前元件信息{clicked_data}")
        element_id = clicked_data.get("元件ID")
        part_name = clicked_data.get("零件名称")
        save_image(element_id, image_path, viewer_instance.product_id)
        update_param_table_data(
            viewer_instance.tableWidget_detail,
            viewer_instance.product_id,
            element_id
        )
        update_left_table_db_from_param_table(
            viewer_instance.tableWidget_detail,
            viewer_instance.product_id,
            element_id,
            part_name
        )

    # 刷新左表
    updated_element_info = load_element_data_by_product_id(viewer_instance.product_id)
    updated_element_info = move_guankou_to_first(updated_element_info)
    viewer_instance.element_data = updated_element_info
    viewer_instance.render_data_to_table(updated_element_info)
    # 存为模板
    # update_template_input_editable_state(viewer_instance)

    # 恢复点击绑定
    try:
        viewer_instance.tableWidget_parts.itemClicked.disconnect()
    except Exception as e:
        print(f"[调试] 点击事件解绑失败: {e}")
    try:
        viewer_instance.tableWidget_parts.itemClicked.connect(
            lambda item: handle_table_click(viewer_instance, item.row(), item.column())
        )
    except Exception as e:
        print(f"[调试] 点击事件绑定失败: {e}")


def show_success_message_auto(parent, message="保存成功！", timeout=2000):
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle("成功")
    box.setText(message)
    box.setStandardButtons(QMessageBox.NoButton)

    # ✅ 设置提示文字字体大小 & 控制整体宽度
    box.setStyleSheet("""
        QMessageBox {
            min-width: 200px;
            max-width: 300px;
        }
        QMessageBox QLabel {
            font-size: 18px;
            padding: 8px;
        }
    """)

    box.setWindowModality(False)  # 非阻塞
    box.show()
    QTimer.singleShot(timeout, box.accept)


def on_confirm_guankouparam(viewer_instance):#已修改
    print("点击了确定按钮")

    tab_name = viewer_instance.tabWidget.tabText(viewer_instance.tabWidget.currentIndex())

    if tab_name == "管口材料分类1":
        table_param = viewer_instance.tableWidget_guankou_param
    else:
        table_param = viewer_instance.dynamic_guankou_param_tabs.get(tab_name)

    if table_param is None:
        table_param = viewer_instance.tableWidget_guankou_param
        # print(f"当前tab页对应的表格参数{table_param}")

    clicked_data = getattr(viewer_instance, 'clicked_guankou_define_data', None)
    print(f"当前点击的数据{clicked_data}")

    if not clicked_data:
        guankou_id = viewer_instance.guankou_define_info[0].get("管口零件ID")
        print(f"未点击确定时管口零件ID{guankou_id}")
        category_label = viewer_instance.tabWidget.tabText(viewer_instance.tabWidget.currentIndex())
    else:
        guankou_id = clicked_data.get("管口零件ID")
        category_label = clicked_data.get("类别")

    print(f"当前管口零件ID：{guankou_id}，类别{category_label}")

    update_guankou_param(
        table_param,
        viewer_instance.product_id,
        guankou_id,
        category_label
    )

    # ✅ 无论是否定义都重新判断并更新定义状态
    define_status = "已定义" if is_all_guankou_parts_defined(viewer_instance.product_id) else "未定义"
    update_guankou_define_status(viewer_instance.product_id, "管口", define_status)

    update_element_info = load_element_data_by_product_id(viewer_instance.product_id)
    update_element_info = move_guankou_to_first(update_element_info)
    viewer_instance.render_data_to_table(update_element_info)
    # 存为模板
    # update_template_input_editable_state(viewer_instance)

    # 读取产品活动库中的管口零件参数信息
    updated_guankou_param = load_updated_guankou_param_data(viewer_instance.product_id, guankou_id, category_label)
    viewer_instance.render_guankou_material_detail_table(table_param, updated_guankou_param)
    param_options = load_material_dropdown_values()
    # apply_paramname_dependent_combobox(
    #     table_param,
    #     param_col=0,
    #     value_col=1,
    #     param_options=param_options
    # )
    apply_gk_paramname_combobox(
        table_param,
        param_col=0,
        value_col=1,
        viewer_instance=viewer_instance
    )
    # ✅ 获取当前 tab 和 tab 名
    tab_name = viewer_instance.tabWidget.tabText(viewer_instance.tabWidget.currentIndex())
    print(f"tabname{tab_name}")


    # ✅ 判断当前是否是第一个 tab（固定控件），还是动态 tab
    if tab_name == "管口材料分类1":
        table_define = viewer_instance.tableWidget_guankou_define  # 固定的第一个 tab 的表格
    else:
        table_define = viewer_instance.dynamic_guankou_define_tabs.get(tab_name)


    col_map = {1: "材料类型", 2: "材料牌号", 3: "材料标准", 4: "供货状态"}

    for row in range(table_define.rowCount()):
        part_item = table_define.item(row, 0)
        if not part_item:
            continue
        part_name = part_item.text().strip()
        guankou_id = None

        # ✅ 根据元件名称匹配 guankou_define_info 中的零件ID
        for item in viewer_instance.guankou_define_info:
            if item.get("零件名称", "").strip() == part_name:
                guankou_id = item.get("管口零件ID")
                break

        if not guankou_id:
            print(f"[跳过] 第{row}行未找到对应的管口ID，零件名称: {part_name}")
            continue

        # ✅ 遍历四字段列
        for col, field_name in col_map.items():
            combo = table_define.cellWidget(row, col)
            if isinstance(combo, QComboBox):
                value = combo.currentText().strip()
                update_guankou_define_data(viewer_instance.product_id, value, field_name, guankou_id, category_label)

    # ✅ 所有行保存完之后再弹提示框（只弹一次）
    show_success_message_auto(viewer_instance, "保存成功！", timeout=3000)







def render_additional_info_table(viewer_instance, additional_info):
    """渲染元件附加参数"""
    # print(f"[调试] 正在渲染右侧表格，附加参数: {additional_info}")
    details_table = viewer_instance.tableWidget_detail  # 还是用右下这个表格

    # 彻底清空表格数据
    details_table.setRowCount(0)  # 清空所有行
    details_table.clearContents()  # 清空现有数据

    headers = ["参数名称", "参数值", "参数单位"]
    details_table.setColumnCount(len(headers))

    details_table.setHorizontalHeaderLabels(headers)

    header = details_table.horizontalHeader()
    for i in range(details_table.columnCount()):
        header.setSectionResizeMode(i, QtWidgets.QHeaderView.Stretch)

    details_table.setRowCount(len(additional_info))

    for row_idx, row_data in enumerate(additional_info):
        for col_idx, header_name in enumerate(headers):
            item = QTableWidgetItem(str(row_data.get(header_name, "")))
            item.setTextAlignment(QtCore.Qt.AlignCenter)

            # ✅ 设置只读（不可编辑）列：参数名称 和 参数单位
            if col_idx in [0, 2]:  # 参数名称列 和 参数单位列
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)

            details_table.setItem(row_idx, col_idx, item)


def render_guankou_param_table(viewer_instance, guankou_param_info):
    """渲染管口参数定义数据到表格"""

    guankou_define = viewer_instance.tableWidget_guankou_define  # 获取右侧的表格控件

    # 清空现有数据
    guankou_define.clear()  # 清除所有行列和表头
    guankou_define.setRowCount(0)
    guankou_define.setColumnCount(0)

    # 设置列标题
    headers = ["零件名称", "材料类型", "材料牌号", "材料标准", "供货状态"]
    guankou_define.setColumnCount(len(headers))
    guankou_define.setRowCount(len(guankou_param_info))  # 设置行数
    guankou_define.setHorizontalHeaderLabels(headers)

    # 自动调整列宽
    header = guankou_define.horizontalHeader()
    for i in range(guankou_define.columnCount()):
        header.setSectionResizeMode(i, QtWidgets.QHeaderView.Stretch)

    # 填充表格
    for row_idx, row_data in enumerate(guankou_param_info):
        for col_idx, header_name in enumerate(headers):
            item = QTableWidgetItem(str(row_data.get(header_name, "")))
            item.setTextAlignment(QtCore.Qt.AlignCenter)
            guankou_define.setItem(row_idx, col_idx, item)


def handle_guankou_table_click(viewer_instance, row, col):

    print(f"传入数据{viewer_instance.guankou_define_info}")
    """处理点击零件列表的逻辑"""

    # 获取当前点击行的数据
    clicked_guankou_define_data = viewer_instance.guankou_define_info[row]  # 获取已经存储的行数据
    print(f"点击的行数据: {clicked_guankou_define_data}")

    viewer_instance.clicked_guankou_define_data = clicked_guankou_define_data

    # 获取管口零件ID
    guankou_id = clicked_guankou_define_data.get("管口零件ID", None)
    print(f"管口：{guankou_id}")
    # print(f"此时点击{clicked_guankou_define_data}")
    category_label = viewer_instance.label
    print(f"类别1: {category_label}")
    # category_label = clicked_guankou_define_data.get("类别", None)
    # print(f"类别: {category_label}")

    # 查询管口附加参数数据
    guankou_additional_info = load_guankou_para_data_leibie(guankou_id, category_label)
    print(f"管口零件参数信息: {guankou_additional_info}")

    # 渲染附加参数表格
    render_guankou_info_table(viewer_instance, guankou_additional_info)


def render_guankou_info_table(viewer_instance, additional_info):
    """渲染管口零件附加参数信息"""
    print(f"渲染了")
    details_table = viewer_instance.tableWidget_guankou_param
    print(f"当前数据{additional_info}")

    # ✅ 先获取旧行列数
    old_row_count = details_table.rowCount()
    old_col_count = details_table.columnCount()

    # ✅ 清除所有 cellWidgets
    for row in range(old_row_count):
        for col in range(old_col_count):
            widget = details_table.cellWidget(row, col)
            if widget:
                widget.deleteLater()
                details_table.removeCellWidget(row, col)

    # ✅ 再清空所有数据
    details_table.setRowCount(0)
    details_table.clearContents()

    headers = ["参数名称", "参数值", "参数单位"]

    # 隐藏列序号
    details_table.verticalHeader().setVisible(False)

    details_table.setColumnCount(len(headers))
    details_table.setRowCount(len(additional_info))
    details_table.setHorizontalHeaderLabels(headers)
    details_table.verticalHeader().setVisible(False)

    header = details_table.horizontalHeader()
    for i in range(details_table.columnCount()):
        header.setSectionResizeMode(i, QtWidgets.QHeaderView.Stretch)

    for row_idx, row_data in enumerate(additional_info):
        for col_idx, header_name in enumerate(headers):
            item = QTableWidgetItem(str(row_data.get(header_name, "")))
            item.setTextAlignment(QtCore.Qt.AlignCenter)
            # ✅ 设置只读（不可编辑）列：参数名称 和 参数单位
            if col_idx in [0, 2]:  # 参数名称列 和 参数单位列
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            details_table.setItem(row_idx, col_idx, item)
        print(f"[插入检查] 行 {row_idx} param: {row_data.get('参数名称')} → 值: {row_data.get('参数值')}")
    details_table.viewport().update()
    details_table.repaint()

    # details_table.setStyleSheet("QHeaderView::section { background-color: lightgreen; }")



def setup_overlay_controls_logic(table, param_col, value_col, param_name, combo, field_widgets):
    material_type_fields = {
        "覆层材料类型": {
            "control_field": "是否添加覆层",
            "level_field": "覆层材料级别",
            "status_field": "覆层使用状态",
            "process_field": "覆层成型工艺"
        },
        "管程侧覆层材料类型": {
            "control_field": "管程侧是否添加覆层",
            "level_field": "管程侧覆层材料级别",
            "status_field": "管程侧覆层使用状态",
            "process_field": "管程侧覆层成型工艺"
        },
        "壳程侧覆层材料类型": {
            "control_field": "壳程侧是否添加覆层",
            "level_field": "壳程侧覆层材料级别",
            "status_field": "壳程侧覆层使用状态",
            "process_field": "壳程侧覆层成型工艺"
        }
    }

    # 1. 对“是否添加覆层”字段的基本控制
    if param_name in ["是否添加覆层", "管程侧是否添加覆层", "壳程侧是否添加覆层"]:
        def on_cover_toggle(index, c=combo):
            value = c.currentText().strip()
            show = value == "是"

            # 根据当前控制字段，隐藏/显示对应字段
            for name, info in material_type_fields.items():
                if info["control_field"] == param_name:
                    targets = [name, info["level_field"], info["status_field"], info["process_field"]]
                    for r in range(table.rowCount()):
                        pitem = table.item(r, param_col)
                        if pitem and pitem.text().strip() in targets:
                            table.setRowHidden(r, not show)

                    if "on_material_type_changed_" + name in field_widgets:
                        field_widgets["on_material_type_changed_" + name](-1)

        combo.currentIndexChanged.connect(on_cover_toggle)
        QTimer.singleShot(0, lambda: on_cover_toggle(combo.currentIndex()))
        return

    # 2. 针对“覆层材料类型”联动成型工艺设置
    if param_name in material_type_fields:
        field_info = material_type_fields[param_name]

        def on_material_type_changed(index, c=combo):
            value = c.currentText().strip()
            print(f"[联动] 当前选择的 {param_name}: {value}")

            # 获取控制字段的值
            control_value = ""
            for rr in range(table.rowCount()):
                item = table.item(rr, param_col)
                if item and item.text().strip() == field_info["control_field"]:
                    widget = table.cellWidget(rr, value_col)
                    if isinstance(widget, QComboBox):
                        control_value = widget.currentText().strip()
                    break

            # 隐藏级别和状态字段（仅当板材+是才显示）
            for r in range(table.rowCount()):
                pitem = table.item(r, param_col)
                if not pitem:
                    continue
                pname = pitem.text().strip()
                if pname == field_info["level_field"]:
                    table.setRowHidden(r, not (control_value == "是" and value == "板材"))
                if pname == field_info["status_field"]:
                    table.setRowHidden(r, not (control_value == "是" and value == "板材"))

            # 延迟设置成型工艺
            def delayed_fill():
                widget = field_widgets.get(field_info["process_field"])
                if not widget:
                    print(f"[警告] {field_info['process_field']} 控件未找到")
                    return

                if not isinstance(widget, QComboBox):
                    print(f"[跳过] {field_info['process_field']} 不是 QComboBox")
                    return

                if control_value != "是":
                    print(f"[跳过] {field_info['control_field']} 未选中“是”，跳过设置 {field_info['process_field']}")
                    return

                widget.blockSignals(True)
                widget.clear()
                widget.addItem("")  # 空项，避免锁死

                if value == "板材":
                    widget.addItems(["轧制复合", "爆炸焊接"])
                    widget.setCurrentText("爆炸焊接")
                elif value == "焊材":
                    widget.addItem("堆焊")
                    widget.setCurrentText("堆焊")
                else:
                    widget.setCurrentText("")
                widget.blockSignals(False)

            QTimer.singleShot(50, delayed_fill)

        # 绑定唯一键，支持多个材料类型字段独立注册
        field_widgets["on_material_type_changed_" + param_name] = on_material_type_changed
        combo.currentIndexChanged.connect(on_material_type_changed)


def apply_paramname_combobox(table, param_col, value_col, viewer_instance):
    """
    根据表格中的参数名称列动态生成下拉框，并从数据库中加载相应的选项
    """
    param_names = get_all_param_name()

    field_widgets = {}

    # ✅ 必须 > 0 的数值字段
    strict_positive_params = {
        "隔板管板侧削边角度", "隔板管板侧削边长度", "隔板管板侧端部与管箱法兰密封面差值", "铭牌板厚度", "铭牌板倒圆半径",
        "排净孔轴向定位x倍隔板轴向长度", "削边角度", "削边长度", "旁路挡板厚度", "中间挡板厚度", "管板凸台高度",
        "滑道高度", "滑道厚度", "滑道与竖直中心线夹角", "切边长度 L1", "切边高度 h", "封头总深度H/总高度Ho",
        "球面部分内半径R", "过渡圆转角半径r", "铭牌板倒圆半径", "垫片与密封面接触内径D1", "铭牌板长度", "铭牌板宽度",
        "垫片与密封面接触外径D2", "铭牌支架长度", "铭牌支架宽度", "铭牌支架厚度", "铭牌支架高度", "铭牌支架铆钉孔直径",
        "铭牌支架长度方向铆钉孔间距", "铭牌支架宽度方向铆钉孔间距", "铭牌支架折弯圆角半径", "铭牌支架与铭牌板边距", "垫片名义内径D1n",
        "垫片名义外径D2n", "垫片厚度", "三角缺口高度", "三角缺口角度", "圆孔直径", "隔板平盖侧削边长度", "隔板平盖侧削边角度", "隔板平盖侧端部与头盖法兰密封面差值"
    }

    # ✅ 可以为 0 的字段（≥ 0）
    non_negative_params = {
        "凸面高度", "隔板槽深度", "覆层厚度", "凹槽深度",
        "附加弯矩", "轴向拉伸载荷", "预设厚度1", "预设厚度2", "预设厚度3",
        "附加弯矩", "轴向拉伸载荷", "凸面高度", "管程侧分程隔板槽深度", "壳程侧分程隔板槽深度", "分程隔板槽宽", "管程侧腐蚀裕量",
        "壳程侧腐蚀裕量", "管程侧覆层厚度", "壳程侧覆层厚度", "防冲板厚度", "排气通液槽高度h",
        "鞍座高度h", "垫片比压力y", "垫片系数m",
    }


    for row in range(table.rowCount()):
        try:
            # 获取当前行的参数名称
            param_item = table.item(row, param_col)
            param_name = param_item.text().strip() if param_item else ""

            if param_name in ["覆层成型工艺", "管程侧覆层成型工艺", "壳程侧覆层成型工艺"]:
                value_item = table.item(row, value_col)
                current_value = value_item.text().strip() if value_item else ""

                combo = QComboBox()
                combo.setEditable(True)
                combo.setInsertPolicy(QComboBox.NoInsert)
                combo.setCurrentText(current_value)
                combo.addItem("")  # 添加空项，避免空下拉无法点击
                combo.lineEdit().setAlignment(Qt.AlignCenter)

                combo.setStyleSheet("""
                    QComboBox {
                        border: none;
                        background-color: transparent;
                        font-size: 9pt;
                        font-family: "Microsoft YaHei";
                        padding-left: 2px;
                    }
                """)
                table.setItem(row, value_col, None)
                table.setCellWidget(row, value_col, combo)
                field_widgets[param_name] = combo

            # 如果该参数名称需要显示为下拉框
            if param_name in param_names:  # 确保只有需要下拉框的参数才处理
                # 从数据库获取该参数的所有选项
                options = get_options_for_param(param_name)

                if options:
                    value_item = table.item(row, value_col)
                    current_value = value_item.text().strip() if value_item else ""

                    # 创建下拉框并填充选项
                    combo = QComboBox()
                    combo.addItem("")  # 默认项
                    combo.addItems(options)
                    combo.setEditable(True)
                    combo.lineEdit().setAlignment(Qt.AlignCenter)
                    combo.setStyleSheet("""
                                        QComboBox {
                                            border: none;
                                            background-color: transparent;
                                            font-size: 9pt;
                                            font-family: "Microsoft YaHei";
                                            padding-left: 2px;
                                        }
                                    """)

                    # 匹配已有值
                    matched = False
                    for i in range(combo.count()):
                        if combo.itemText(i).strip() == current_value:
                            combo.setCurrentIndex(i)
                            matched = True
                            break
                    if not matched:
                        combo.setCurrentIndex(0)  # 如果没有匹配的值，选择第一个选项

                    # 清除原有单元格内容并设置下拉框
                    table.setItem(row, value_col, None)
                    table.setCellWidget(row, value_col, combo)

                    # ↓ 插入在 combo 创建完后（即 table.setCellWidget 后）
                    setup_overlay_controls_logic(table, param_col, value_col, param_name, combo, field_widgets)



                    if param_name == "垫片材料":
                        def on_gasket_material_changed(index, t=table, r=row, combo=combo):
                            selected_text = combo.currentText().strip()
                            gasket_data = get_gasket_param_from_db(selected_text)  # ✅ 从数据库查
                            updated_params = {}

                            if gasket_data:
                                for target_param, value in gasket_data.items():
                                    for rr in range(t.rowCount()):
                                        item = t.item(rr, param_col)
                                        if item and item.text().strip() == target_param:
                                            widget = t.cellWidget(rr, value_col)
                                            if isinstance(widget, QLineEdit):
                                                widget.setText(str(value))
                                            elif isinstance(widget, QComboBox):
                                                idx = widget.findText(str(value))
                                                widget.setCurrentIndex(idx if idx >= 0 else 0)
                                            updated_params[target_param] = str(value)
                                            break

                            product_id = viewer_instance.product_id
                            pn, dn = get_design_params_from_db(product_id)
                            if pn and dn:
                                dims = get_gasket_contact_dims_from_db(pn, dn)
                                for target_param, value in dims.items():
                                    for rr in range(t.rowCount()):
                                        item = t.item(rr, param_col)
                                        if item and item.text().strip() == target_param:
                                            widget = t.cellWidget(rr, value_col)
                                            if isinstance(widget, QLineEdit):
                                                widget.setText(str(value))
                                            updated_params[target_param] = str(value)
                                            break

                                if "垫片与密封面接触内径D1" in dims:
                                    d1_val = dims["垫片与密封面接触内径D1"]
                                    updated_params["垫片名义内径D1n"] = str(d1_val)
                                    for rr in range(t.rowCount()):
                                        item = t.item(rr, param_col)
                                        if item and item.text().strip() == "垫片名义内径D1n":
                                            widget = t.cellWidget(rr, value_col)
                                            if isinstance(widget, QLineEdit):
                                                widget.setText(str(d1_val))
                                            break

                                if "垫片与密封面接触外径D2" in dims:
                                    try:
                                        d2_val = float(dims["垫片与密封面接触外径D2"])
                                        d2n_val = d2_val + 2
                                        # ✅ 判断是否是整数（无小数部分），只保留整数字符串
                                        if d2n_val.is_integer():
                                            d2n_str = str(int(d2n_val))
                                        else:
                                            d2n_str = str(round(d2n_val, 3))  # 可调整保留几位小数

                                        updated_params["垫片名义外径D2n"] = d2n_str
                                        for rr in range(t.rowCount()):
                                            item = t.item(rr, param_col)
                                            if item and item.text().strip() == "垫片名义外径D2n":
                                                widget = t.cellWidget(rr, value_col)
                                                if isinstance(widget, QLineEdit):
                                                    widget.setText(d2n_str)
                                                break
                                    except Exception as e:
                                        print(f"[错误] 计算 D2n 失败: {e}")

                            element_id = viewer_instance.clicked_element_data.get("元件ID", "")
                            for pname, pvalue in updated_params.items():
                                update_element_para_data(product_id, element_id, pname, pvalue)
                        # combo.currentIndexChanged.connect(on_gasket_material_changed)
                        # on_gasket_material_changed(combo.currentIndex())  # 初始化触发一次
                        combo.currentIndexChanged.connect(on_gasket_material_changed)

                        # ✅ 显式传入 currentText 而非 currentIndex
                        def trigger_initial_gasket_update():
                            selected_text = combo.currentText().strip()
                            if selected_text:
                                on_gasket_material_changed(combo.currentIndex())

                        # ✅ 延迟一点执行（等 combo 渲染完成后）
                        QtCore.QTimer.singleShot(0, trigger_initial_gasket_update)

                    is_flatcover_applicable = is_flatcover_trim_param_applicable(viewer_instance.product_id)

                    # ✅ 在 param_name == "隔板平盖侧端部是否削边" 内部添加
                    if param_name == "隔板平盖侧端部是否削边":
                        combo.currentIndexChanged.connect(
                            partial(toggle_dependent_fields, table, combo, "是", [
                                "隔板平盖侧削边长度", "隔板平盖侧削边角度", "隔板平盖侧端部与头盖法兰密封面差值"
                            ], logic="==")
                        )
                        toggle_dependent_fields(table, combo, "是", [
                            "隔板平盖侧削边长度", "隔板平盖侧削边角度", "隔板平盖侧端部与头盖法兰密封面差值"
                        ], logic="==")

                        # ✅ 如果产品型式不是 AES/AEU 则强制隐藏以上四项
                        if not is_flatcover_applicable:
                            for r in range(table.rowCount()):
                                param_item = table.item(r, param_col)
                                if param_item and param_item.text().strip() in [
                                    "隔板平盖侧端部是否削边", "隔板平盖侧削边长度", "隔板平盖侧削边角度",
                                    "隔板平盖侧端部与头盖法兰密封面差值"
                                ]:
                                    table.setRowHidden(r, True)


                    if param_name == "隔板是否开排净孔":
                        combo.currentIndexChanged.connect(
                            partial(toggle_dependent_fields, table, combo, "是", [
                                "排净孔型式", "排净孔轴向定位x倍隔板轴向长度", "三角缺口高度", "三角缺口角度", "圆孔直径"
                            ], logic="==")
                        )
                        toggle_dependent_fields(table, combo, "是", [
                            "排净孔型式", "排净孔轴向定位x倍隔板轴向长度", "三角缺口高度", "三角缺口角度", "圆孔直径"
                        ], logic="==")

                    if param_name == "排净孔型式":
                        combo.currentIndexChanged.connect(lambda: toggle_dependent_fields_complex(
                            table,
                            conditions={"隔板是否开排净孔": "是", "排净孔型式": "边缘三角缺口"},
                            target_fields=["三角缺口角度", "三角缺口高度"]
                        ))

                        # ✅ 初始化判断一次
                        toggle_dependent_fields_complex(
                            table,
                            conditions={"隔板是否开排净孔": "是", "排净孔型式": "边缘三角缺口"},
                            target_fields=["三角缺口角度", "三角缺口高度"]
                        )

                    if param_name == "排净孔型式":
                        combo.currentIndexChanged.connect(lambda: toggle_dependent_fields_complex(
                            table,
                            conditions={"隔板是否开排净孔": "是", "排净孔型式": "圆孔"},
                            target_fields=["圆孔直径"]
                        ))
                        toggle_dependent_fields_complex(
                            table,
                            conditions={"隔板是否开排净孔": "是", "排净孔型式": "圆孔"},
                            target_fields=["圆孔直径"]
                        )

                    if param_name == "隔板管板侧端部是否削边":
                        combo.currentIndexChanged.connect(
                            partial(toggle_dependent_fields, table, combo, "是", [
                                "隔板管板侧削边长度", "隔板管板侧削边角度"
                            ], logic="==")
                        )
                        toggle_dependent_fields(table, combo, "是", [
                            "隔板管板侧削边长度", "隔板管板侧削边角度"
                        ], logic="==")


                    if param_name == "是否开设排气通液槽":
                        combo.currentIndexChanged.connect(
                            partial(toggle_dependent_fields, table, combo, "是", ["排气通液槽高度h"], logic="==")
                        )
                        toggle_dependent_fields(table, combo, "是", ["排气通液槽高度h"], logic="==")


                    if param_name == "防冲板形式":
                        combo.currentIndexChanged.connect(
                            partial(toggle_dependent_fields, table, combo, "平板形", ["防冲板折边角度"], logic="!=")
                        )
                        toggle_dependent_fields(table, combo, "平板形", ["防冲板折边角度"], logic="!=")

                    if param_name == "封头类型代号":
                        combo.currentIndexChanged.connect(
                            partial(toggle_dependent_fields_multi_value, table, combo,
                                    ["EHA（标准椭圆形）", "EHB（标准椭圆形）"], ["封头内曲面深度hi"])
                        )
                        toggle_dependent_fields_multi_value(table, combo,
                                                            ["EHA（标准椭圆形）", "EHB（标准椭圆形）"],
                                                            ["封头内曲面深度hi"])

                        # 2. THA 和 THB 时显示 R 和 r
                        combo.currentIndexChanged.connect(
                            partial(toggle_dependent_fields_multi_value, table, combo, ["THA（蝶形）", "THB（蝶形）"],
                                    ["球面部分内半径R", "过渡圆转角半径r"])
                        )
                        toggle_dependent_fields_multi_value(table, combo, ["THA（蝶形）", "THB（蝶形）"],
                                                            ["球面部分内半径R", "过渡圆转角半径r"])

                        # 3. HHA（准半球形）时显示连接方式
                        combo.currentIndexChanged.connect(
                            partial(toggle_dependent_fields_multi_value, table, combo, ["HHA（准半球形）"],
                                    ["圆筒与封头的连接方式"])
                        )
                        toggle_dependent_fields_multi_value(table, combo, ["HHA（准半球形）"], ["圆筒与封头的连接方式"])



            elif param_name in strict_positive_params or param_name in non_negative_params:
                value_item = table.item(row, value_col)
                current_text = value_item.text().strip() if value_item else ""
                line_edit = QLineEdit()
                line_edit.setText(current_text)
                line_edit.setAlignment(Qt.AlignCenter)
                line_edit.setStyleSheet("""
                    QLineEdit {
                        border: none;
                        background-color: transparent;
                        font-size: 9pt;
                        font-family: "Microsoft YaHei";
                        padding-left: 2px;
                    }
                """)

                if param_name in ["管程侧腐蚀裕量", "壳程侧腐蚀裕量"]:
                    corrosion_tube, corrosion_shell = get_corrosion_allowance_from_db(viewer_instance.product_id)
                    element_id = viewer_instance.clicked_element_data.get("元件ID", "")
                    print(f"[调试] 腐蚀余量: 管程={corrosion_tube} 壳程={corrosion_shell}")

                    if param_name == "管程侧腐蚀裕量" and corrosion_tube is not None:
                        line_edit.setText(str(corrosion_tube))
                        update_element_para_data(viewer_instance.product_id, element_id, param_name,
                                                 str(corrosion_tube))

                    if param_name == "壳程侧腐蚀裕量" and corrosion_shell is not None:
                        line_edit.setText(str(corrosion_shell))
                        update_element_para_data(viewer_instance.product_id, element_id, param_name,
                                                 str(corrosion_shell))

                allow_text_fields = {"旁路挡板厚度", "封头总深度H/总高度Ho"}

                def validate_input(le=line_edit, pname=param_name, r=row, tip=viewer_instance.line_tip):
                    text = le.text().strip()

                    # ✅ 特殊处理：允许填写“符合配置要求”的字段
                    if pname in allow_text_fields and text == "符合配置要求":
                        tip.setText("")
                        return

                    try:
                        val = float(text)

                        # ✅ 更严格范围限制
                        if pname == "三角缺口角度" and not (30 < val < 120):
                            raise ValueError("三角缺口角度应在 30 到 120 之间")

                        if pname in strict_positive_params and val <= 0:
                            raise ValueError
                        if pname in non_negative_params and val < 0:
                            raise ValueError

                        tip.setText("")  # 清空之前的错误提示

                    except Exception as e:
                        if pname == "三角缺口角度":
                            tip.setText(f"第 {r + 1} 行参数“{pname}”的值应为 30 到 120 之间的数字！")
                        elif pname in allow_text_fields:
                            tip.setText(f"第 {r + 1} 行参数“{pname}”的值应为大于 0 的数字，或填写“符合配置要求”！")
                        else:
                            limit = "大于 0" if pname in strict_positive_params else "大于等于 0"
                            tip.setText(f"第 {r + 1} 行参数“{pname}”的值应为{limit}的数字！")

                        tip.setStyleSheet("color: red;")
                        le.setText("")

                line_edit.editingFinished.connect(validate_input)
                table.setItem(row, value_col, None)
                table.setCellWidget(row, value_col, line_edit)



        except Exception as e:
            print(f"[错误] 第 {row} 行处理失败，参数名: '{param_name}'，错误: {e}")



def apply_linked_param_combobox(table, param_col, value_col, mapping):
    """根据联动表映射创建主字段和被控字段的下拉框，并设置联动关系"""
    row_count = table.rowCount()

    dropdown_style = """
    QComboBox {
        border: none;
        background-color: transparent;
        font-size: 9pt;
        font-family: "Microsoft YaHei";
        padding-left: 2px;
    }
    """

    master_fields = mapping.keys()

    for r in range(row_count):
        pname = table.item(r, param_col).text().strip() if table.item(r, param_col) else ""
        pval = table.item(r, value_col).text().strip() if table.item(r, value_col) else ""


    for row in range(row_count):
        param_item = table.item(row, param_col)
        param_name = param_item.text().strip() if param_item else ""

        if param_name in master_fields:
            saved_value = table.item(row, value_col).text().replace('\n', '').strip() if table.item(row, value_col) else ""

            master_combo = QComboBox()
            master_combo.addItem("")
            master_combo.addItems(list(mapping[param_name].keys()))
            master_combo.setEditable(True)
            master_combo.lineEdit().setAlignment(Qt.AlignCenter)
            master_combo.setStyleSheet(dropdown_style)

            table.setItem(row, value_col, None)
            table.setCellWidget(row, value_col, master_combo)

            all_options = [master_combo.itemText(i) for i in range(master_combo.count())]
            idx = master_combo.findText(saved_value)
            master_combo.setCurrentIndex(idx if idx >= 0 else 0)

            for sub_row in range(row_count):
                sub_param_item = table.item(sub_row, param_col)
                sub_param_name = sub_param_item.text().strip() if sub_param_item else ""

                if any(sub_param_name in dependents for dependents in mapping[param_name].values()):
                    saved_sub_value = table.item(sub_row, value_col).text().replace('\n', '').strip() if table.item(sub_row, value_col) else ""

                    dependent_combo = QComboBox()
                    dependent_combo.setEditable(True)
                    dependent_combo.setStyleSheet(dropdown_style)
                    dependent_combo.lineEdit().setAlignment(Qt.AlignCenter)
                    dependent_combo.addItem("")

                    table.setItem(sub_row, value_col, None)
                    table.setCellWidget(sub_row, value_col, dependent_combo)


                    def update_dependent(r, sub_r, master_field, sub_field, saved_val):
                        master_val = table.cellWidget(r, value_col).currentText().strip()

                        # ✅ 主字段未选择，跳过联动，防止清空已有值
                        if not master_val:
                            print(f"[跳过联动] 主字段 '{master_field}' 为空，跳过从字段 '{sub_field}' 的选项更新")
                            return

                        options = mapping.get(master_field, {}).get(master_val, {}).get(sub_field, [])
                        dep_cb = table.cellWidget(sub_r, value_col)
                        if dep_cb:
                            dep_cb.blockSignals(True)
                            dep_cb.clear()
                            dep_cb.addItem("")
                            dep_cb.addItems(options)

                            idx = dep_cb.findText(saved_val)
                            dep_cb.setCurrentIndex(idx if idx >= 0 else 0)

                            dep_cb.blockSignals(False)

                    def bind_update(combo, r, sub_r, master_field, sub_field, saved_val):
                        def handler(_):
                            update_dependent(r, sub_r, master_field, sub_field, saved_val)
                        combo.currentIndexChanged.connect(handler)

                    bind_update(master_combo, row, sub_row, param_name, sub_param_name, saved_sub_value)

                    # 初始化执行一次联动逻辑
                    update_dependent(row, sub_row, param_name, sub_param_name, saved_sub_value)





def apply_gk_paramname_combobox(table, param_col, value_col, component_info=None, viewer_instance=None):
    field_widgets = {}
    positive_float_params = {"焊缝金属截面积", "管程接管腐蚀裕量", "壳程接管腐蚀裕量", "覆层厚度"}
    toggle_cover_dependent_fields = [
        "覆层材料类型", "覆层材料牌号", "覆层材料级别",
        "覆层材料标准", "覆层成型工艺", "覆层使用状态", "覆层厚度"
    ]

    for row in range(table.rowCount()):
        try:
            param_item = table.item(row, param_col)
            param_name = param_item.text().strip() if param_item else ""

            value_item = table.item(row, value_col)
            current_value = value_item.text().strip() if value_item else ""

            # 处理是否添加覆层
            if param_name == "是否添加覆层":
                combo = QComboBox()
                combo.addItems(["是", "否"])
                combo.setEditable(True)
                combo.setCurrentText("是" if current_value == "是" else "否")
                combo.lineEdit().setAlignment(Qt.AlignCenter)
                combo.setStyleSheet("""
                    QComboBox { border: none; background-color: transparent; font-size: 9pt; font-family: "Microsoft YaHei"; padding-left: 2px; }
                """)
                table.setItem(row, value_col, None)
                table.setCellWidget(row, value_col, combo)

                # ✅ 直接把当前 component_info 存入 combo 属性
                combo.component_info = component_info
                combo.viewer_instance = viewer_instance

                # ✅ 定义信号槽时，取 combo 内部绑定的 component_info
                def on_cover_changed(value, combo_ref=combo):
                    ci = getattr(combo_ref, "component_info", None)
                    viewer = getattr(combo_ref, "viewer_instance", None)
                    has_covering = (value.strip() == "是")

                    for r in range(table.rowCount()):
                        pitem = table.item(r, param_col)
                        if not pitem:
                            continue
                        pname = pitem.text().strip()
                        if pname in toggle_cover_dependent_fields:
                            table.setRowHidden(r, not has_covering)

                            # ✅ 仅在隐藏行时清空控件内的值，保留控件
                            if not has_covering:
                                widget = table.cellWidget(r, value_col)
                                if isinstance(widget, QLineEdit):
                                    widget.clear()
                                elif isinstance(widget, QComboBox):
                                    widget.setCurrentIndex(0)  # 置为空白项（第一项）
                                    widget.setCurrentText("")  # 保险起见再清空显示文本

                    # 刷新图片逻辑
                    if ci and viewer:
                        template_name = ci.get("模板名称")
                        template_id = query_template_id(template_name) if template_name else ci.get("模板ID")
                        element_id = ci.get("管口零件ID")
                        if template_id and element_id:
                            image_path = query_guankou_image_from_database(template_id, element_id, has_covering)
                            if image_path:
                                viewer.display_image(image_path)

                # 初始化 & 绑定信号
                on_cover_changed(combo.currentText())
                combo.currentTextChanged.connect(on_cover_changed)

                continue

            # 处理覆层材料类型及其联动
            if param_name == "覆层材料类型":
                options = get_options_for_param(param_name) or []
                combo = QComboBox()
                combo.addItem("")
                combo.addItems(options)
                combo.setEditable(True)
                combo.setCurrentText(current_value)
                combo.lineEdit().setAlignment(Qt.AlignCenter)
                combo.setStyleSheet("""
                    QComboBox { border: none; background-color: transparent; font-size: 9pt; font-family: "Microsoft YaHei"; padding-left: 2px; }
                """)
                table.setItem(row, value_col, None)
                table.setCellWidget(row, value_col, combo)
                field_widgets["覆层材料类型"] = combo

                def on_material_type_changed(index, c=combo):
                    value = c.currentText().strip()
                    cover_value = ""
                    for rr in range(table.rowCount()):
                        item = table.item(rr, param_col)
                        if item and item.text().strip() == "是否添加覆层":
                            widget = table.cellWidget(rr, value_col)
                            if isinstance(widget, QComboBox):
                                cover_value = widget.currentText().strip()
                            break

                    # 控制“覆层材料级别”和“覆层使用状态”的显示
                    for r in range(table.rowCount()):
                        pitem = table.item(r, param_col)
                        if not pitem:
                            continue
                        pname = pitem.text().strip()
                        if pname == "覆层材料级别":
                            table.setRowHidden(r, not (cover_value == "是" and value == "板材"))
                        if pname == "覆层使用状态":
                            table.setRowHidden(r, not (cover_value == "是" and value == "板材"))

                    # ✅ 更新覆层成型工艺的下拉内容
                    if "覆层成型工艺" in field_widgets and cover_value == "是":
                        combo_widget = field_widgets["覆层成型工艺"]
                        combo_widget.blockSignals(True)
                        combo_widget.clear()
                        combo_widget.addItem("")
                        if value == "板材":
                            combo_widget.addItems(["轧制复合", "爆炸焊接"])
                            combo_widget.setCurrentText("爆炸焊接")
                        elif value == "焊材":
                            combo_widget.addItem("堆焊")
                            combo_widget.setCurrentText("堆焊")
                        else:
                            combo_widget.setCurrentText("")
                        combo_widget.blockSignals(False)

                combo.currentIndexChanged.connect(on_material_type_changed)
                QTimer.singleShot(0, lambda: on_material_type_changed(combo.currentIndex()))
                continue

            # 处理覆层成型工艺
            if param_name == "覆层成型工艺":
                combo = QComboBox()
                combo.setEditable(True)
                combo.setInsertPolicy(QComboBox.NoInsert)
                combo.addItem("")  # 添加空项，避免空下拉无法点击

                # ✅ 根据 current_value 判断初始化选项
                if current_value == "爆炸焊接":
                    combo.addItems(["轧制复合", "爆炸焊接"])
                elif current_value == "堆焊":
                    combo.addItem("堆焊")

                # ✅ 设置当前值（确保显示）
                combo.setCurrentText(current_value)

                combo.lineEdit().setAlignment(Qt.AlignCenter)
                combo.setStyleSheet("""
                    QComboBox {
                        border: none;
                        background-color: transparent;
                        font-size: 9pt;
                        font-family: "Microsoft YaHei";
                        padding-left: 2px;
                    }
                """)
                table.setItem(row, value_col, None)
                table.setCellWidget(row, value_col, combo)
                field_widgets["覆层成型工艺"] = combo
                continue

            # 处理一般正浮点数
            if param_name in positive_float_params:
                line_edit = QLineEdit()
                line_edit.setText(current_value)
                line_edit.setAlignment(Qt.AlignCenter)
                line_edit.setStyleSheet("""
                    QLineEdit { border: none; font-size: 9pt; font-family: "Microsoft YaHei"; }
                """)

                def validate(le=line_edit, pname=param_name, r=row, tip=viewer_instance.line_tip):
                    try:
                        val = float(le.text().strip())
                        if val < 0 or (pname == "焊缝金属截面积" and val == 0):
                            raise ValueError
                        tip.setText("")  # 输入合法时清空提示
                    except:
                        tip.setText(f"第 {r + 1} 行参数“{pname}”输入值不合法")
                        tip.setStyleSheet("color: red;")
                        le.setText("")

                line_edit.editingFinished.connect(validate)
                table.setItem(row, value_col, None)
                table.setCellWidget(row, value_col, line_edit)
                continue

            # 其他通用下拉
            options = get_options_for_param(param_name)
            if options:
                combo = QComboBox()
                combo.addItem("")
                combo.addItems(options)
                combo.setEditable(True)
                combo.setCurrentText(current_value)
                combo.lineEdit().setAlignment(Qt.AlignCenter)
                combo.setStyleSheet("""
                    QComboBox { border: none; background-color: transparent; font-size: 9pt; font-family: "Microsoft YaHei"; padding-left: 2px; }
                """)
                table.setItem(row, value_col, None)
                table.setCellWidget(row, value_col, combo)

        except Exception as e:
            print(f"[接管参数处理失败] 第{row}行 参数名: {param_name}，错误: {e}")






