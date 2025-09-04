import re
from functools import partial
from typing import Optional

from PyQt5 import QtWidgets, QtCore
from PyQt5.QtCore import Qt, QTimer, QEvent
from PyQt5.QtGui import QDoubleValidator
from PyQt5.QtWidgets import QTableWidgetItem, QTableWidget, QComboBox, QDoubleSpinBox, QMessageBox, QLineEdit, QLabel, \
    QAbstractItemView, QStyledItemDelegate, QDialog, QVBoxLayout, QPushButton

from modules.cailiaodingyi.controllers.checkcombo import CheckComboDelegate
from modules.cailiaodingyi.controllers.combo import ComboDelegate, MaterialInstantDelegate
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
    update_element_para_data, toggle_dependent_fields_complex, get_corrosion_allowance_from_db,
    update_guankou_category_for_tab, save_guankou_codes_for_tab, query_template_codes,
    update_guankou_params_bulk, get_numeric_rules, load_update_guankou_para_data,
    clear_guankou_category, evaluate_visibility_rules_from_db, query_guankou_codes, fetch_product_element_materials,
    fetch_template_element_materials, diff_product_vs_template
)
from modules.cailiaodingyi.funcs.funcs_pdf_input import (
    load_elementoriginal_data,
    move_guankou_to_first,
    load_guankou_material_detail,
    query_template_guankou_para_data,
    query_template_element_para_data,
    load_material_dropdown_values, query_guankou_define_data_by_category, update_template_input_editable_state,
    load_guankou_material_detail_template, get_options_for_param, get_all_param_name,
    is_flatcover_trim_param_applicable, query_unassigned_codes, load_tab_assigned_codes, query_guankou_default,
    insert_guankou_info
)
from modules.cailiaodingyi.funcs.funcs_pdf_render import render_guankou_param_to_ui, FreezeUI
from modules.condition_input.funcs.funcs_cdt_input import sync_design_params_to_element_params, \
    sync_corrosion_to_guankou_param


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


def on_clear_param_update(viewer_instance):
    """
    清空参数数值列，写库并刷新界面（不清空“元件名称”）
    """
    param_table = viewer_instance.tableWidget_detail
    row_count = param_table.rowCount()
    param_value_col = 1
    param_name_col  = 0

    preserved_params = {"管程侧是否添加覆层", "壳程侧是否添加覆层", "是否添加覆层"}
    skip_params_ui_db = {"元件名称"}   # ✅ UI 与 DB 都保留

    # 信息样式确认弹窗
    box = QtWidgets.QMessageBox(
        QtWidgets.QMessageBox.Information,
        "清空确认",
        "清空后不可撤销，是否继续？",
        QtWidgets.QMessageBox.NoButton,
        param_table
    )
    btn_ok = box.addButton("确认", QtWidgets.QMessageBox.YesRole)
    btn_cancel = box.addButton("取消", QtWidgets.QMessageBox.NoRole)
    box.setDefaultButton(btn_cancel)
    box.exec_()
    if box.clickedButton() is not btn_ok:
        print("[清空] 用户取消操作")
        return

    # 清空参数数值列（处理文本和控件）
    for row in range(row_count):
        name_item = param_table.item(row, param_name_col)
        param_name = name_item.text().strip() if name_item else ""

        # ✅ 跳过“元件名称”
        if param_name in skip_params_ui_db:
            continue

        cell_widget = param_table.cellWidget(row, param_value_col)
        if cell_widget:
            if isinstance(cell_widget, QtWidgets.QComboBox):
                if param_name in preserved_params:
                    idx = cell_widget.findText("否")
                    cell_widget.setCurrentIndex(idx if idx >= 0 else 0)
                else:
                    cell_widget.setCurrentIndex(0)
            elif isinstance(cell_widget, QtWidgets.QLineEdit):
                if param_name in preserved_params:
                    cell_widget.setText("否")
                else:
                    cell_widget.clear()
            elif isinstance(cell_widget, QtWidgets.QSpinBox):
                # 统一清 0，若要最小值可改回 minimum()
                cell_widget.setValue(0 if param_name not in preserved_params else 0)
            else:
                pass
        else:
            item = param_table.item(row, param_value_col)
            if not item:
                item = QtWidgets.QTableWidgetItem("")
                param_table.setItem(row, param_value_col, item)
            item.setText("否" if param_name in preserved_params else "")

    # 写库
    selected_ids = getattr(viewer_instance, "selected_element_ids", [])
    if len(selected_ids) > 1:
        print(f"[多选] 批量清空元件ID: {selected_ids}")
        for eid in selected_ids:
            update_param_table_data(param_table, viewer_instance.product_id, eid)
            part_info = next((it for it in viewer_instance.element_data if it["元件ID"] == eid), {})
            update_left_table_db_from_param_table(param_table, viewer_instance.product_id, eid, part_info.get("零件名称", ""))
    else:
        clicked = viewer_instance.clicked_element_data
        element_id = clicked.get("元件ID")
        part_name  = clicked.get("零件名称")
        update_param_table_data(param_table, viewer_instance.product_id, element_id)
        update_left_table_db_from_param_table(param_table, viewer_instance.product_id, element_id, part_name)

    # 刷新左表
    updated = load_element_data_by_product_id(viewer_instance.product_id)
    updated = move_guankou_to_first(updated)
    viewer_instance.element_data = updated
    viewer_instance.render_data_to_table(updated)

    # 恢复点击绑定
    try:
        viewer_instance.tableWidget_parts.itemClicked.disconnect()
    except Exception:
        pass
    try:
        viewer_instance.tableWidget_parts.itemClicked.connect(
            lambda item: handle_table_click(viewer_instance, item.row(), item.column())
        )
    except Exception:
        pass




def on_clear_guankou_param_update(viewer_instance):
    """
    安全清空管口参数表格，并同步数据库（使用与保存相同的映射/展开规则）
    """
    # 1) 询问确认 —— 使用标准信息样式的确认框（与“完成”外观一致）
    table = getattr(viewer_instance, "tableWidget_guankou", None)
    if table is None:
        return

    box = QMessageBox(QMessageBox.Information, "清空确认",
                      "清空后不可撤销，是否继续？",
                      QMessageBox.NoButton, table)
    btn_ok = box.addButton("确认", QMessageBox.YesRole)
    btn_cancel = box.addButton("取消", QMessageBox.NoRole)
    box.setDefaultButton(btn_cancel)  # 默认光标在“取消”，更安全
    box.exec_()
    if box.clickedButton() is not btn_ok:
        print("[清空] 用户取消操作")
        return

    # 2) 当前 Tab / 表
    tw = getattr(viewer_instance, "guankou_tabWidget", None)
    if tw is None or tw.currentIndex() < 0:
        print("[清空] 无法定位当前管口Tab")
        return
    cur_idx = tw.currentIndex()
    tab_name = tw.tabText(cur_idx).strip()
    table_param = _get_tab_table(viewer_instance, cur_idx)
    if table_param is None:
        QMessageBox.warning(viewer_instance, "错误", f"未找到 {tab_name} 的参数表")
        return

    # 3) UI 清空（不销毁委托/控件，只清文本；两条覆层开关置“否”）
    preserved_params = {"接管是否添加覆层", "接管法兰是否添加覆层"}
    table_param.blockSignals(True)
    try:
        for r in range(table_param.rowCount()):
            it0 = table_param.item(r, 0)
            label_ui = it0.text().strip() if it0 else ""
            if not label_ui:
                continue

            if _is_multi_col_row(table_param, r):
                # 多列行：1/2/3 列全部置空
                for c in (1, 2, 3):
                    it = table_param.item(r, c)
                    if it:
                        it.setText("")
                    else:
                        table_param.setItem(r, c, QTableWidgetItem(""))
            else:
                # 单值行：覆层开关置“否”，其余置空
                v = "否" if label_ui in preserved_params else ""
                it = table_param.item(r, 1)
                if it:
                    it.setText(v)
                else:
                    table_param.setItem(r, 1, QTableWidgetItem(v))
    finally:
        table_param.blockSignals(False)

    # 4) DB 批量清空（与“确定”存库同路径：_ui2db_name + 多列展开）
    try:
        _clear_other_params_for_tab_mapped(
            viewer_instance, table_param,
            viewer_instance.product_id, tab_name,
            preserved_params=preserved_params
        )
    except Exception as e:
        print("[数据库错误] 清空管口参数失败：", e)

    # 5) 同时清空管口占用（管口号）
    try:
        clear_guankou_category(viewer_instance.product_id, tab_name)
    except Exception as e:
        print("[数据库错误] 当前材料清空管口分类失败：", e)




def _clear_other_params_for_tab_mapped(viewer_instance, table_param, product_id, tab_name,
                                       preserved_params: set):
    """
    与 save_other_params_for_tab 同样的映射/展开规则来清空：
      - 单值行 -> (product_id, tab_name, label_db, value='')
      - 多列行 -> (product_id, tab_name, f'{label_db}{i}', value_i='')  i=1..3
      - 覆层开关（preserved_params）写入 '否'
    实际落库时使用 update_guankou_params_bulk(..., treat_empty_as_null=True)，
    让空串写成 NULL（开关除外）。
    """
    rows_to_save = []

    for r in range(table_param.rowCount()):
        it0 = table_param.item(r, 0)
        label_ui = it0.text().strip() if it0 else ""
        if not label_ui or label_ui == "管口号":
            continue

        label_db_base = _ui2db_name(label_ui, viewer_instance)

        if _is_multi_col_row(table_param, r):
            # 多列行：展开 label1/label2/label3 -> 全置空
            value_cols = [1, 2, 3] if table_param.columnCount() >= 4 else [1, 2]
            for i, _c in enumerate(value_cols, start=1):
                rows_to_save.append((product_id, tab_name, f"{label_db_base}{i}", ""))
        else:
            # 单值行：覆层开关=“否”，其它=空
            v1 = "否" if label_ui in preserved_params else ""
            rows_to_save.append((product_id, tab_name, label_db_base, v1))

    # 批量更新为 NULL（空串）或“否”
    ret = update_guankou_params_bulk(rows_to_save, treat_empty_as_null=True)
    print(f"[清空-调试] Tab={tab_name} 更新 {ret['updated']} 行, 未命中 {len(ret['missing'])} 行")






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
            handler = make_on_fixed_tube_covering_changed_v2(component_info, viewer_instance, table, param_col, value_col)
            handler()

_IMAGE_PATH_CACHE = {}  # key = (template_name, element_id, has_covering, mode) → path

def _query_image_cached(template_name, element_id, has_covering, mode="global"):
    key = (template_name or "", str(element_id or ""), bool(has_covering), mode)
    if key in _IMAGE_PATH_CACHE:
        return _IMAGE_PATH_CACHE[key]
    p = query_image_from_database(template_name, element_id, has_covering)
    _IMAGE_PATH_CACHE[key] = p
    return p

def _set_pixmap_if_changed(viewer_instance, image_path: str):
    """仅当路径变化时才刷新，避免卡顿；空路径则清空。"""
    cur = getattr(viewer_instance, "current_image_path", None)
    if not image_path:
        viewer_instance.label_part_image.clear()
        viewer_instance.current_image_path = None
        return
    if cur == image_path:
        return
    viewer_instance.display_image(image_path)
    viewer_instance.current_image_path = image_path


# ✅ 封装处理函数：绑定每行独立信息，避免闭包错误
def make_on_covering_changed(component_info_copy, viewer_instance_copy, row_index, table=None):
    """全局‘是否添加覆层’ → 图片刷新（一次性去抖，无连接累积）"""
    def handler(value):
        def _do():
            try:
                has_covering = (value or "").strip() == "是"
                if not component_info_copy or not viewer_instance_copy:
                    return
                image_path = (component_info_copy.get("零件示意图覆层") if has_covering
                              else component_info_copy.get("零件示意图"))
                if not image_path:
                    template_name = component_info_copy.get("模板名称")
                    element_id = component_info_copy.get("元件ID")
                    image_path = _query_image_cached(template_name, element_id, has_covering, mode="global")
                _set_pixmap_if_changed(viewer_instance_copy, image_path)
            except Exception as e:
                print(f"[错误] 第{row_index}行处理图片失败: {e}")

        QTimer.singleShot(60, _do)   # 60ms 去抖
    return handler




def make_on_fixed_tube_covering_changed_v2(component_info_copy, viewer_instance_copy,
                                           table: QTableWidget, param_col: int, value_col: int):
    """固定管板‘管程侧/壳程侧是否添加覆层’ → 图片刷新（无连接累积、不卡顿）"""

    def _compute():
        g_row = k_row = None
        for r in range(table.rowCount()):
            it = table.item(r, param_col)
            if not it:
                continue
            name = it.text().strip()
            if name == "管程侧是否添加覆层":
                g_row = r
            elif name == "壳程侧是否添加覆层":
                k_row = r
        if g_row is None or k_row is None:
            return None

        def _is_yes(row):
            vitem = table.item(row, value_col)
            return (vitem.text().strip() if vitem else "") == "是"

        g_yes = _is_yes(g_row)
        k_yes = _is_yes(k_row)

        default_img = component_info_copy.get("零件示意图") or _query_image_cached(
            component_info_copy.get("模板名称"), component_info_copy.get("元件ID"),
            False, mode="fixed-default"
        )

        if not g_yes and not k_yes:
            return default_img

        image_covering_str = component_info_copy.get("零件示意图覆层", "")
        if not image_covering_str:
            image_covering_str = _query_image_cached(
                component_info_copy.get("模板名称"), component_info_copy.get("元件ID"),
                True, mode="fixed-covering"
            )

        parts = (image_covering_str or "").split('/')
        guancheng_img = parts[0].strip() if len(parts) > 0 and parts[0] else None
        kecheng_img   = parts[1].strip() if len(parts) > 1 and parts[1] else None
        both_img      = parts[2].strip() if len(parts) > 2 and parts[2] else None

        if g_yes and not k_yes:
            return guancheng_img or default_img
        if not g_yes and k_yes:
            return kecheng_img or default_img
        if g_yes and k_yes:
            return both_img or default_img
        return default_img

    def refresh_image():
        # 60ms 去抖；不会产生额外的信号连接
        QTimer.singleShot(60, lambda: _set_pixmap_if_changed(
            viewer_instance_copy, _compute()
        ))

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

MATERIAL_FIELDS = ("材料类型", "材料牌号", "材料标准", "供货状态")

def _find_row_by_param(table, param_col, name: str) -> int:
    for r in range(table.rowCount()):
        it = table.item(r, param_col)
        if it and it.text().strip() == name:
            return r
    return -1

def _ensure_editable_item(table, row, col):
    it = table.item(row, col)
    if it is None:
        it = QTableWidgetItem("")
        table.setItem(row, col, it)
    it.setTextAlignment(Qt.AlignCenter)
    it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
    return it


class InstantCommitComboDelegate:
    pass


def _set_row_delegate(table, row, options, keep_current=False, current_text="", on_change=None):
    # 去空去重省略...
    if keep_current and current_text and current_text not in options:
        options = [current_text] + options

    if on_change is not None:
        table.setItemDelegateForRow(row, InstantCommitComboDelegate(options, table, on_change=on_change))
    else:
        table.setItemDelegateForRow(row, ComboDelegate(options, table))







def install_material_delegate_linkage(table, param_col, value_col, viewer_instance=None):
    """
    渲染完成后调用：给‘材料类型/牌号/标准/供货状态’四行安装 MaterialInstantDelegate，
    由代理直接把新值回调进来，立即联动其它三项。
    """
    from PyQt5.QtWidgets import QAbstractItemView
    if getattr(table, "_material_delegates_installed", False):
        return
    table.setEditTriggers(QAbstractItemView.SelectedClicked)

    # ---- 查四行行号 ----
    r_type   = _find_row_by_param(table, param_col, "材料类型")
    r_brand  = _find_row_by_param(table, param_col, "材料牌号")
    r_std    = _find_row_by_param(table, param_col, "材料标准")
    r_status = _find_row_by_param(table, param_col, "供货状态")
    rows = [r for r in (r_type, r_brand, r_std, r_status) if r >= 0]
    if not rows:
        return

    # 确保 value 列是可编辑 item，清掉 cellWidget
    for r in rows:
        if table.cellWidget(r, value_col):
            table.setCellWidget(r, value_col, None)
        _ensure_editable_item(table, r, value_col)

    # 便捷读/写
    def _get(r):
        it = table.item(r, value_col)
        return (it.text().strip() if it else "")
    def _set(r, txt):
        it = table.item(r, value_col)
        if it is None:
            it = QTableWidgetItem()
            it.setTextAlignment(Qt.AlignCenter)
            table.setItem(r, value_col, it)
        it.setText(txt or "")

    # ---- 初次候选（按当前 DB 值筛）----
    cur_type, cur_brand, cur_std = _get(r_type), _get(r_brand), _get(r_std)

    opts_type = get_filtered_material_options({}).get("材料类型", []) or []
    opts_brand = get_filtered_material_options({"材料类型": cur_type} if cur_type else {}).get("材料牌号", []) or []
    basis_std = {k:v for k,v in {"材料类型": cur_type, "材料牌号": cur_brand}.items() if v}
    opts_std  = get_filtered_material_options(basis_std).get("材料标准", []) or []
    basis_stat = {k:v for k,v in {"材料类型": cur_type, "材料牌号": cur_brand, "材料标准": cur_std}.items() if v}
    opts_stat = get_filtered_material_options(basis_stat).get("供货状态", []) or []

    # ---- 回调：联动逻辑（不经 itemChanged）----
    def on_pick(field_name: str, new_text: str, row: int, col: int):
        # 读当前四值（此时模型里已经是新值）
        cur_t = _get(r_type)
        cur_b = _get(r_brand)
        cur_s = _get(r_std)
        cur_u = _get(r_status)

        if field_name == "材料类型":
            # 类型变更：强制清空后三项
            for rr in (r_brand, r_std, r_status):
                if rr >= 0:
                    _set(rr, "")
            # 重装 牌号 候选
            b = get_filtered_material_options({"材料类型": new_text}) or {}
            _install_row_delegate("材料牌号", r_brand, b.get("材料牌号", []))

            # 标准/状态的候选要等牌号确定后再给；这里先清空代理（给空列表）
            _install_row_delegate("材料标准", r_std, [])
            _install_row_delegate("供货状态", r_status, [])

        elif field_name == "材料牌号":
            # 依据 类型 + 牌号 → 刷新 标准/状态 候选，且唯一时自动带入
            basis = {"材料类型": cur_t, "材料牌号": new_text}
            f = get_filtered_material_options(basis) or {}

            std_opts = f.get("材料标准", []) or []
            _install_row_delegate("材料标准", r_std, std_opts)
            if (not _get(r_std)) and len([x for x in std_opts if x]) == 1:
                only = [x for x in std_opts if x][0]
                _set(r_std, only)

            stat_opts = f.get("供货状态", []) or []
            _install_row_delegate("供货状态", r_status, stat_opts)
            if (not _get(r_status)) and len([x for x in stat_opts if x]) == 1:
                only = [x for x in stat_opts if x][0]
                _set(r_status, only)

        elif field_name == "材料标准":
            # 标准变更：状态可能进一步收窄（可按需添加：依据 类型+牌号+标准 来刷新状态）
            basis = {"材料类型": cur_t, "材料牌号": cur_b, "材料标准": new_text}
            f = get_filtered_material_options(basis) or {}
            stat_opts = f.get("供货状态", []) or []
            _install_row_delegate("供货状态", r_status, stat_opts)
            if (not _get(r_status)) and len([x for x in stat_opts if x]) == 1:
                _set(r_status, [x for x in stat_opts if x][0])

        # ‘材料类型’==钢锻件 → 显隐“锻件级别”
        if field_name == "材料类型":
            _apply_forging_visibility(table, param_col, value_col, viewer_instance, new_text, write_db=True)

        table.viewport().update()

    # ---- 安装四行代理（专用代理 + 回调）----
    def _install_row_delegate(field_name, row_idx, options):
        if row_idx < 0:
            return
        # 去空/去重/保序；保持 UI 上“空项”置顶（按你原习惯需要可自行添加 ""）
        seen, opts = set(), []
        for o in options or []:
            s = (o or "").strip()
            if s and s not in seen:
                seen.add(s); opts.append(o)
        table.setItemDelegateForRow(row_idx, MaterialInstantDelegate(opts, table, field_name, on_pick))

    _install_row_delegate("材料类型", r_type,   opts_type)
    _install_row_delegate("材料牌号", r_brand,  opts_brand)
    _install_row_delegate("材料标准", r_std,    opts_std)
    _install_row_delegate("供货状态", r_status, opts_stat)

    # 初始状态下的“锻件级别”显隐（不写库）
    _apply_forging_visibility(table, param_col, value_col, viewer_instance, cur_type, write_db=False)



def install_covering_delegate_linkage(table: QTableWidget,
                                      param_col: int,
                                      value_col: int,
                                      component_info: dict,
                                      viewer_instance):
    """
    给 ‘是否添加覆层 / 管程侧是否添加覆层 / 壳程侧是否添加覆层’ 安装行委托，并用 itemChanged 驱动
    toggle_covering_fields() 与图片刷新（兼容代理，不依赖 QComboBox 控件）。
    """
    if getattr(table, "_covering_delegates_installed", False):
        return
    def _find_row(name: str) -> int:
        for r in range(table.rowCount()):
            it = table.item(r, param_col)
            if it and it.text().strip() == name:
                return r
        return -1

    r_global = _find_row("是否添加覆层")
    r_g = _find_row("管程侧是否添加覆层")
    r_k = _find_row("壳程侧是否添加覆层")

    # 1) 给三行装下拉代理（仍然使用你现有的 ComboDelegate；不新增代理类）
    for rr in [r_global, r_g, r_k]:
        if rr >= 0:
            # 确保 value 列有可编辑 item（代理才能工作）
            it = table.item(rr, value_col)
            if it is None:
                it = QTableWidgetItem("")
                it.setTextAlignment(Qt.AlignCenter)
                table.setItem(rr, value_col, it)
            # 行代理：是/否
            table.setItemDelegateForRow(rr, ComboDelegate(["是", "否"], table))

    # 2) 统一的 itemChanged 处理（避免重复绑定）
    def _on_item_changed(item: QTableWidgetItem):
        if item.column() != value_col:
            return
        r = item.row()
        name_it = table.item(r, param_col)
        if not name_it:
            return
        pname = name_it.text().strip()
        val   = item.text().strip()

        # 显隐逻辑（直接调用你原有的方法）
        if pname in ("是否添加覆层", "管程侧是否添加覆层", "壳程侧是否添加覆层"):
            # 用一个“假的 combo”接口传给 toggle_covering_fields（它只用到了 currentText）
            class _Fake:
                def __init__(self, t): self._t=t
                def currentText(self): return self._t
            toggle_covering_fields(table, _Fake(val), pname)

            # 固定管板：双侧任意变化 → 刷新图片
            if component_info and viewer_instance and (r_g >= 0 and r_k >= 0):
                handler = make_on_fixed_tube_covering_changed_v2(
                    component_info, viewer_instance, table, param_col, value_col
                )
                handler()

            # 全局单开关：刷新图片
            if component_info and viewer_instance and pname == "是否添加覆层":
                h = make_on_covering_changed(component_info, viewer_instance, r, table=table)
                h(val)

    # 断开旧连接，防重复触发
    try:
        table.itemChanged.disconnect(_on_item_changed)
    except Exception:
        pass
    table.itemChanged.connect(_on_item_changed)

    # 3) 初始化：根据当前值做一次显隐与图片刷新
    def _init_apply(row_idx: int, pname: str):
        if row_idx < 0:
            return
        vitem = table.item(row_idx, value_col)
        cur = vitem.text().strip() if vitem else ""
        class _Fake:
            def __init__(self, t): self._t=t
            def currentText(self): return self._t
        toggle_covering_fields(table, _Fake(cur), pname)

    _init_apply(r_global, "是否添加覆层")
    _init_apply(r_g,      "管程侧是否添加覆层")
    _init_apply(r_k,      "壳程侧是否添加覆层")

    # 固定管板：初始化图片
    if component_info and viewer_instance and (r_g >= 0 and r_k >= 0):
        handler = make_on_fixed_tube_covering_changed_v2(component_info, viewer_instance, table, param_col, value_col)
        handler()









def _apply_forging_visibility(table, param_col, value_col, viewer_instance, material_type_text, write_db=True):
    """材料类型≠钢锻件 → 隐藏‘锻件级别’并清空（可选写库）"""
    show = (material_type_text == "钢锻件")
    for rr in range(table.rowCount()):
        pit = table.item(rr, param_col)
        if pit and pit.text().strip() == "锻件级别":
            table.setRowHidden(rr, not show)
            if not show:
                try:
                    table.blockSignals(True)
                    iv = table.item(rr, value_col)
                    if iv: iv.setText("")
                finally:
                    table.blockSignals(False)
                if write_db:
                    try:
                        product_id = getattr(viewer_instance, "product_id", "")
                        element_id = getattr(viewer_instance, "clicked_element_data", {}).get("元件ID", "")
                        update_element_para_data(product_id, element_id, "锻件级别", "")
                    except Exception as e:
                        print(f"[清空锻件级别失败] {e}")
            break


def _norm(s: str) -> str:
    return (s or "").strip()

def _clean_options(options):
    # 去 None/空串，去重保序
    seen, out = set(), []
    for o in options or []:
        t = _norm(o)
        if not t:
            continue
        if t not in seen:
            seen.add(t); out.append(o)   # 保留原字符串，但用于比较走 _norm
    return out

def _in_options(val: str, options) -> bool:
    v = _norm(val)
    return any(_norm(x) == v for x in (options or []))




def on_material_delegate_changed(table, item, param_col, value_col, viewer_instance=None):
    if item.column() != value_col:
        return

    rows_map = table.property("material_rows") or {}
    if not rows_map:
        return

    r_type   = rows_map.get("材料类型",  -1)
    r_brand  = rows_map.get("材料牌号",  -1)
    r_std    = rows_map.get("材料标准",  -1)
    r_status = rows_map.get("供货状态", -1)
    if item.row() not in {r_type, r_brand, r_std, r_status}:
        return

    init_mode = bool(table.property("material_init_mode"))
    getv = lambda rr: (table.item(rr, value_col).text().strip() if rr >= 0 else "")
    cur_type, cur_brand, cur_std, cur_status = getv(r_type), getv(r_brand), getv(r_std), getv(r_status)

    def _reinstall_and_fix(row, options, current_text):
        if row < 0:
            return
        # 重新装代理（非编辑态也能立即生效）
        _set_row_delegate(table, row, options, keep_current=init_mode, current_text=current_text)

        cur = (current_text or "").strip()
        opts = [x for x in (options or []) if str(x).strip()]
        new_val, need_fix = cur, False

        if not init_mode:
            if cur and cur not in opts:
                new_val = (opts[0] if len(opts) == 1 else "")
                need_fix = True
            elif not cur and len(opts) == 1:
                new_val = opts[0]
                need_fix = True
        else:
            if not cur and len(opts) == 1:
                new_val = opts[0]
                need_fix = True

        if need_fix:
            table.blockSignals(True)
            try:
                table.item(row, value_col).setText(new_val)
            finally:
                table.blockSignals(False)

    # 1) 类型
    opts_type = get_filtered_material_options({}).get("材料类型", [])
    _reinstall_and_fix(r_type, opts_type, cur_type)

    # 2) 牌号（受类型）
    cur_type = getv(r_type)
    basis_brand = {"材料类型": cur_type} if cur_type else {}
    opts_brand  = get_filtered_material_options(basis_brand).get("材料牌号", [])
    _reinstall_and_fix(r_brand, opts_brand, cur_brand)

    # 3) 标准（受类型+牌号）
    cur_brand = getv(r_brand)
    basis_std = {"材料类型": cur_type, "材料牌号": cur_brand}
    basis_std = {k: v for k, v in basis_std.items() if v}
    opts_std  = get_filtered_material_options(basis_std).get("材料标准", [])
    _reinstall_and_fix(r_std, opts_std, cur_std)

    # 4) 供货状态（受类型+牌号+标准）
    cur_std   = getv(r_std)
    basis_stat = {"材料类型": cur_type, "材料牌号": cur_brand, "材料标准": cur_std}
    basis_stat = {k: v for k, v in basis_stat.items() if v}
    opts_stat  = get_filtered_material_options(basis_stat).get("供货状态", [])
    _reinstall_and_fix(r_status, opts_stat, cur_status)

    # 材料类型变更时的“锻件级别”显隐/清空
    if item.row() == r_type:
        _apply_forging_visibility(table, param_col, value_col, viewer_instance, getv(r_type), write_db=(not init_mode))





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


def generate_unique_guankou_label(self) -> str:
    """
    基于当前 tab 上的已有标题自动取下一个序号。
    无需全局计数器，切换模板后自然从 2 开始。
    """
    tw = self.guankou_tabWidget
    used = set()
    max_idx = 1

    for i in range(tw.count()):
        text = tw.tabText(i)
        used.add(text)
        m = re.match(r"^管口材料分类(\d+)$", text)
        if m:
            try:
                max_idx = max(max_idx, int(m.group(1)))
            except ValueError:
                pass

    # 末尾有 '+' 的话，不影响取号
    next_idx = max_idx + 1
    while True:
        label = f"管口材料分类{next_idx}"
        if label not in used:
            # 你如果维护了 used_labels，可顺手登记一下（可选）
            if hasattr(self, "guankou_used_labels"):
                self.guankou_used_labels.add(label)
            return label
        next_idx += 1


def refresh_guankou_tabs_from_db(viewer_instance):
    """
    读取数据库 → 统一刷新每个tab：
      显示：若该tab在库里有已保存集合 → 按库里为准（保序显示）；
           否则显示为空（或你愿意可显示=当前∩未分配）
      候选：未分配 ∪ 本tab已保存
    同时写 table.property('gk_code_candidates') 给委托读取，不更换委托。
    """
    from PyQt5.QtWidgets import QTableWidgetItem
    from PyQt5.QtCore import Qt

    product_id = getattr(viewer_instance, "product_id", None)
    if not product_id:
        return

    # ① 未分配集合
    try:
        unassigned = set(query_unassigned_codes(product_id) or [])
    except Exception as e:
        print(f"[警告] 查询未分配失败：{e}")
        unassigned = set()

    # ② tab → 已保存集合（你上一条我已给了实现）
    try:
        tab_to_saved = load_tab_assigned_codes(product_id) or {}
        tab_to_saved = {str(k).strip(): set(v or []) for k, v in tab_to_saved.items()}
    except Exception as e:
        print(f"[警告] 读取tab分配映射失败：{e}")
        tab_to_saved = {}

    def _find_row(table, label: str) -> int:
        for r in range(table.rowCount()):
            it = table.item(r, 0)
            if it and it.text().strip() == label:
                return r
        return -1

    def _set_candidates(table, cands):
        table.setProperty("gk_code_candidates", tuple(sorted(set(cands))))
        table.setProperty("gk_code_candidates_ready", True)

    tw = viewer_instance.guankou_tabWidget
    for i in range(tw.count()):
        tab_name = tw.tabText(i).strip()
        if tab_name in {"+", "＋"}:
            continue

        # 取本tab的表
        table = _get_tab_table(viewer_instance, i)
        if table is None:
            print(f"[提示] 第{i}页({tab_name}) 未绑定 param_table")
            continue

        row_idx = _find_row(table, "管口号")
        if row_idx < 0:
            continue

        # 本tab在库里的已保存集合
        saved = tab_to_saved.get(tab_name, set())

        # 显示：以库里为准（换模板后通常为空）
        display_text = "、".join([x for x in saved])

        # 候选：未分配 ∪ 本tab已保存
        candidates = unassigned | saved

        # 写入显示与候选（不触发信号）
        table.blockSignals(True)
        try:
            item_val = table.item(row_idx, 1)
            if item_val:
                item_val.setText(display_text)
            else:
                it = QTableWidgetItem(display_text)
                it.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_idx, 1, it)
        finally:
            table.blockSignals(False)

        _set_candidates(table, candidates)
        table.viewport().update()


def _show_full_diff_dialog(parent, diffs, template_name):
    dlg = QDialog(parent)
    dlg.setWindowTitle(f"与模板 {template_name} 的差异明细")
    layout = QVBoxLayout(dlg)
    table = QTableWidget(dlg)
    table.setColumnCount(4)
    table.setHorizontalHeaderLabels(["元件名称","字段","当前值","模板值"])
    table.setRowCount(len(diffs))
    for i, d in enumerate(diffs):
        table.setItem(i, 0, QTableWidgetItem(d["name"]))
        table.setItem(i, 1, QTableWidgetItem(d["field"]))
        table.setItem(i, 2, QTableWidgetItem(str(d["old"])))
        table.setItem(i, 3, QTableWidgetItem(str(d["new"])))
    table.resizeColumnsToContents()
    layout.addWidget(table)

    btn = QPushButton("关闭", dlg)
    btn.clicked.connect(dlg.accept)
    layout.addWidget(btn)
    dlg.resize(860, 520)
    dlg.exec_()


def ask_before_switch_template_against_current(parent, product_id: str,
                                               base_template_name: str,
                                               target_template_name: str) -> bool:
    """
    切换之前提示：比较 “产品当前数据” vs “当前模板(base_template_name) 的模板基准”
    显示差异后问是否继续切换到 target_template_name
    """
    # 读库
    prod_map = fetch_product_element_materials(product_id)
    tpl_map  = fetch_template_element_materials(base_template_name)

    diffs = diff_product_vs_template(prod_map, tpl_map)

    if not diffs:
        # 没差异，直接允许切换
        return True

    preview = diffs[:8]
    lines = [f"• {d['name']}：{d['field']}：当前“{d['old']}” → 模板“{d['new']}”" for d in preview]
    more  = "" if len(diffs) <= 8 else f"<br>…… 还有 {len(diffs)-8} 处差异"

    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Information)
    msg.setWindowTitle("模板切换差异提示")
    msg.setTextFormat(Qt.RichText)
    msg.setText(
        f"将切换到模板 <b>{target_template_name}</b>。<br>"
        f"在切换前，基于“当前模板 <b>{base_template_name or '（空）'}</b>”的模板基准，"
        f"检测到与当前产品数据存在如下差异：<br><br>"
        + "<br>".join(lines) + more +
        "<br><br><i>此提示仅用于告知差异，不会修改你的现有数据。</i>"
    )
    btn_continue = msg.addButton("继续切换", QMessageBox.AcceptRole)
    btn_detail   = msg.addButton("查看全部", QMessageBox.ActionRole)
    msg.addButton("取消", QMessageBox.RejectRole)
    msg.exec_()

    if msg.clickedButton() == btn_detail:
        _show_full_diff_dialog(parent, diffs, base_template_name)  # 这里展示“和当前模板”的全部差异
        # 再问一次
        msg2 = QMessageBox(parent)
        msg2.setIcon(QMessageBox.Question)
        msg2.setWindowTitle("确认切换")
        msg2.setText(f"是否继续切换到模板 “{target_template_name}”？")
        ok2 = msg2.addButton("继续切换", QMessageBox.AcceptRole)
        msg2.addButton("取消", QMessageBox.RejectRole)
        msg2.exec_()
        return msg2.clickedButton() == ok2

    return msg.clickedButton() == btn_continue





def load_data_by_template(viewer_instance, template_name):

    while viewer_instance.guankou_tabWidget.count() > 1:
        viewer_instance.guankou_tabWidget.removeTab(1)

    # 删除动态添加的 tab
    for tab in viewer_instance.dynamic_guankou_tabs:
        index = viewer_instance.guankou_tabWidget.indexOf(tab)
        if index != -1:
            viewer_instance.guankou_tabWidget.removeTab(index)
    viewer_instance.dynamic_guankou_tabs.clear()

    viewer_instance.dynamic_guankou_param_tabs.clear()
    # 默认tab重新登记
    viewer_instance.dynamic_guankou_param_tabs["管口材料分类1"] = viewer_instance.tableWidget_guankou

    if hasattr(viewer_instance, "plus_mgr") and viewer_instance.plus_mgr:
        viewer_instance.plus_mgr.refresh_after_model_change()

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

        # 管口类别表的读取插入
        guankou_info = query_template_codes(product_id)

        if not guankou_info:
            guankou_info = query_guankou_default(viewer_instance.product_type, viewer_instance.product_form)

        insert_guankou_info(product_id, guankou_info)

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

            # 将当前模板ID对应的管口参数信息写入到产品设计活动库中
            insert_or_update_guankou_para_data(product_id, guankou_para_info, template_name)
            # sync_corrosion_to_guankou_param(product_id)
            if viewer_instance.guankou_tabWidget.count() > 0:
                current_index = viewer_instance.guankou_tabWidget.currentIndex()  # 当前选中 tab
                category_label = viewer_instance.guankou_tabWidget.tabText(current_index)
            else:
                category_label = "管口材料分类1"  # fallback

                # 打印当前分类标签（category_label）
            print(f"[调试] 当前的分类标签是: {category_label}")

            guankou_codes = query_guankou_codes(product_id, category_label)
            # 打印查询到的管口号
            print(f"[调试] 查询到的管口号: {guankou_codes}")
            sync_corrosion_to_guankou_param(product_id, guankou_codes, category_label)

            refresh_guankou_tabs_from_db(viewer_instance)
            guankou_define_info = load_guankou_define_data(product_id)

            viewer_instance.guankou_define_info = guankou_define_info
            # 批量加上模板名称
            for item in viewer_instance.guankou_define_info:
                item['模板ID'] = first_template_id

            print("更新模板后管口定义信息：", viewer_instance.guankou_define_info)

            if guankou_define_info:

                render_guankou_param_to_ui(viewer_instance, guankou_define_info)

                # # 管口零件表格中的下拉框
                # dropdown_data = load_material_dropdown_values()
                # column_index_map = {'材料类型': 1, '材料牌号': 2, '材料标准': 3, '供货状态': 4}
                # column_data_map = {column_index_map[k]: v for k, v in dropdown_data.items()}
                # apply_combobox_to_table(viewer_instance.tableWidget_guankou_define, column_data_map, viewer_instance, category_label="管口材料分类1")
                # set_table_tooltips(viewer_instance.tableWidget_guankou_define)

                # #更新产品活动库中的管口零件材料表
                # insert_or_update_guankou_material_data(guankou_define_info, product_id, template_name)
                # # print(f"管口零件更新信息{guankou_define_info}")
                #
                # first_guankou_element = guankou_define_info[0]
                # viewer_instance.guankou_define_info = guankou_define_info
                # # print(f"第一条管口零件信息{first_guankou_element}")
                # first_guankou_element_id = first_guankou_element.get("管口零件ID", None)
                # # print(f"第一条管口零件对应的管口零件ID{first_guankou_element_id}")
                # if first_guankou_element_id:
                #     guankou_material_details = load_guankou_material_detail_template(first_guankou_element_id, first_template_id)
                #     # print(f"第一个管口零件对应的参数信息{guankou_material_details}")
                #     if guankou_material_details:
                #         render_guankou_info_table(viewer_instance, guankou_material_details)
                #         param_options = load_material_dropdown_values()
                #         apply_paramname_dependent_combobox(
                #             viewer_instance.tableWidget_para_define,
                #             param_col=0,
                #             value_col=1,
                #             param_options=param_options
                #         )
                #         apply_paramname_dependent_combobox(
                #             viewer_instance.tableWidget_guankou_param,
                #             param_col=0,
                #             value_col=1,
                #             param_options=param_options
                #         )
                #         apply_gk_paramname_combobox(
                #             viewer_instance.tableWidget_guankou_param,
                #             param_col=0,
                #             value_col=1
                #         )
                #
                #
                #         set_table_tooltips(viewer_instance.tableWidget_para_define)
                #     else:
                #         print("没有查到第一个管口零件材料的详细数据")
                # else:
                #     print("第一个管口零件没有ID")
            else:
                print("没有查到管口定义数据")

        else:
            viewer_instance.show_error_message("数据加载错误", f"模板 {template_name} 未找到元件数据")
    else:
        viewer_instance.show_error_message("输入错误", "产品类型或形式未找到")

    # # 存为模板
    # # update_template_input_editable_state(viewer_instance)
    # bind_define_table_click(
    #     viewer_instance,
    #     viewer_instance.tableWidget_guankou_define,
    #     viewer_instance.tableWidget_guankou_param,
    #     guankou_define_info,  # 模板切换后的新数据
    #     category_label="管口材料分类1"
    # )


    # def force_select_guankou_and_trigger():
    #     print("✅ 自动选中管口并触发刷新")
    #
    #     # 1. 先从左侧表格中查找“管口”行号
    #     table = viewer_instance.tableWidget_parts
    #     for r in range(table.rowCount()):
    #         item = table.item(r, 1)  # 第1列为“零件名称”
    #         if item and item.text().strip() == "管口":
    #             table.setCurrentCell(r, 0)
    #             viewer_instance.handle_table_click_guankou(r, 0)  # ✅ 切换到“管口”
    #             handle_table_click(viewer_instance, r, 0)  # ✅ 加载管口定义数据
    #             break
    #
    #     # 2. 再模拟点击右侧“管口定义”表第一行
    #     QTimer.singleShot(10, lambda: viewer_instance.on_define_table_clicked(
    #         0,
    #         viewer_instance.guankou_define_info,
    #         viewer_instance.tableWidget_guankou_param,
    #         "管口材料分类1"
    #     ))
    #
    # QTimer.singleShot(10, force_select_guankou_and_trigger)


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


    # 获取元件ID和模板ID
    element_id = clicked_element_data.get("元件ID", None)
    template_id = clicked_element_data.get("模板ID", None)
    element_name = clicked_element_data.get("零件名称", "")
    # print(f"元件ID{element_id}")

    # 判断是否为管口
    if element_name == "管口":
        # guankou_define_info = load_guankou_define_data(template_id, "1")
        # print(f"管口{guankou_define_info}")
        updated_guankou_define_info = load_updated_guankou_define_data(viewer_instance.product_id, "管口材料分类1")
        print(f"更新{updated_guankou_define_info}")
        render_guankou_param_to_ui(viewer_instance, updated_guankou_define_info)
        viewer_instance.guankou_define_info = updated_guankou_define_info

        # ✅ 关键：首次点击时也刷新“管口号”的显示值与候选
        tw = getattr(viewer_instance, "guankou_tabWidget", None)
        cur_tab = (tw.tabText(tw.currentIndex()).strip()
                   if tw and tw.currentIndex() >= 0 else "管口材料分类1")

        try:
            viewer_instance.patch_codes_for_current_tab(viewer_instance.tableWidget_guankou, cur_tab)
        except Exception as e:
            print(f"[GUANKOU] 首次补刷失败：{e}")

        # 再用 0ms 兜底刷一次，确保在所有委托安装完成后也生效
        QTimer.singleShot(0, lambda:
        viewer_instance.patch_codes_for_current_tab(viewer_instance.tableWidget_guankou, cur_tab)
                          )

        # if not guankou_define_info:
        #     guankou_define_info = query_guankou_define_data_by_category(viewer_instance.product_id, "管口材料分类1")
        #     render_guankou_param_table(viewer_instance, guankou_define_info)
        # else:
        #     guankou_ID = guankou_define_info[0].get("管口零件ID", None)
        #     # guankou_additional_info = load_guankou_para_data(guankou_ID, "管口材料分类1")
        #     guankou_additional_info = load_guankou_para_data(guankou_ID, viewer_instance.product_id, "管口材料分类1")

        #     if guankou_additional_info:
        #         render_guankou_info_table(viewer_instance, guankou_additional_info)
        #
        #         # ✅ 关键改动：不论初始化还是切换，都插入控件
        #         param_options = load_material_dropdown_values()
        #
        #         apply_paramname_dependent_combobox(
        #             viewer_instance.tableWidget_guankou_param,
        #             param_col=0,
        #             value_col=1,
        #             param_options=param_options,
        #             component_info=viewer_instance.clicked_element_data,
        #             viewer_instance=viewer_instance
        #         )
        #         apply_gk_paramname_combobox(
        #             viewer_instance.tableWidget_guankou_param,
        #             param_col=0,
        #             value_col=1
        #         )
        #         set_table_tooltips(viewer_instance.tableWidget_guankou_param)
        #     else:
        #         guankou_para_table = viewer_instance.tableWidget_guankou_param
        #         guankou_para_table.setRowCount(0)
        #         guankou_para_table.clearContents()
        #
        # # ✅ 不管有没有零件信息，define表也一样正常渲染
        # dropdown_data = load_material_dropdown_values()
        # column_index_map = {'材料类型': 1, '材料牌号': 2, '材料标准': 3, '供货状态': 4}
        # column_data_map = {column_index_map[k]: v for k, v in dropdown_data.items()}
        # apply_combobox_to_table(viewer_instance.tableWidget_guankou_define, column_data_map, viewer_instance,
        #                         category_label="管口材料分类1")
        # set_table_tooltips(viewer_instance.tableWidget_guankou_define)

        return

    if not element_id:
        print("没有找到有效的元件ID，跳过查询！")
        return

    additional_info = load_element_additional_data_by_product(viewer_instance.product_id, element_id)


    render_additional_info_table(viewer_instance, additional_info)
    param_options = load_material_dropdown_values()
    # apply_paramname_dependent_combobox(
    #     viewer_instance.tableWidget_para_define,
    #     param_col=0,
    #     value_col=1,
    #     param_options=param_options,
    #     component_info=viewer_instance.clicked_element_data,
    #     viewer_instance=viewer_instance
    # )
    install_material_delegate_linkage(
        table=viewer_instance.tableWidget_para_define,
        param_col=0,
        value_col=1,
        viewer_instance=viewer_instance,  # 用于“锻件级别”清库时的 product_id / element_id
    )
    # install_covering_delegate_linkage(
    #     table=viewer_instance.tableWidget_para_define,
    #     param_col=0,
    #     value_col=1,
    #     component_info=viewer_instance.clicked_element_data,
    #     viewer_instance=viewer_instance
    # )
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


def _get_tab_table(viewer_instance, i: int):
    tw = getattr(viewer_instance, "guankou_tabWidget", None)
    if tw is None or i < 0 or i >= tw.count():
        return None
    page = tw.widget(i)
    t = page.property('param_table') if page else None
    if t is None and i == 0:
        t = getattr(viewer_instance, "tableWidget_guankou", None)  # 首 tab 兜底
    return t


def refresh_all_tabs_after_save(viewer_instance, current_tab_index: int, current_selected_codes: set):
    """
    规则：
      - 显示：优先以“库里已保存集合”为准；若该tab尚未保存，则显示=当前显示∩未分配（并剔除他tab新占用）
      - 候选：所有tab统一为 未分配 ∪ 本tab已保存
    不更换委托，只更新单元格文本与表属性 gk_code_candidates。
    """
    from PyQt5.QtWidgets import QTableWidgetItem
    from PyQt5.QtCore import Qt
    import re

    product_id = getattr(viewer_instance, "product_id", None)
    if not product_id:
        return

    # ① 库里未分配集合
    try:
        unassigned = set(query_unassigned_codes(product_id) or [])
    except Exception as e:
        print(f"[警告] 查询未分配失败：{e}")
        unassigned = set()

    # ② 库里“tab → 已分配集合”映射（需要你实现：返回 dict[str, set[str]]）
    #    要求：键使用【tab页当前标题】保存和读取保持一致。
    try:
        tab_to_saved = load_tab_assigned_codes(product_id) or {}   # e.g. {"管口材料分类1": {"N1","N2"}, ...}
        # 规范成 set
        tab_to_saved = {str(k).strip(): set(v or []) for k, v in tab_to_saved.items()}
    except Exception as e:
        print(f"[警告] 读取tab分配映射失败：{e}")
        tab_to_saved = {}

    def parse_codes(s: str):
        return [x for x in re.split(r"[、，,\s]+", (s or "").strip()) if x]

    def merge_in_display_order(cur_list, keep_set):
        head = [x for x in cur_list if x in keep_set]
        tail = [x for x in keep_set if x not in cur_list]
        return head + tail

    def _set_candidates_property(table, cands):
        table.setProperty("gk_code_candidates", tuple(sorted(set(cands))))
        table.setProperty("gk_code_candidates_ready", True)

    tw = viewer_instance.guankou_tabWidget
    for i in range(tw.count()):
        name = tw.tabText(i).strip()
        if name in {"+", "＋"}:
            continue

        table = _get_tab_table(viewer_instance, i)
        if table is None:
            print(f"[提示] 第{i}页({name}) 未绑定 param_table")
            continue

        # 找“管口号”行
        row_idx = -1
        for r in range(table.rowCount()):
            it0 = table.item(r, 0)
            if it0 and it0.text().strip() == "管口号":
                row_idx = r
                break
        if row_idx < 0:
            continue

        item_val = table.item(row_idx, 1)
        cur_text = item_val.text().strip() if (item_val and item_val.text()) else ""
        cur_list = parse_codes(cur_text)

        # 本tab在库里的已保存集合
        saved_set = set(tab_to_saved.get(name, set()))

        if saved_set:
            # ✅ 已经保存过：显示=库里为准（按原顺序保序）
            keep_list = merge_in_display_order(cur_list, saved_set)
        else:
            # ⬜ 尚未保存：显示=当前显示 ∩ 未分配（并剔除本次新占用）
            #   （当次保存发生在 current_tab_index，已被写入库的其它tab会走上面的分支）
            tmp = [x for x in cur_list if x not in (current_selected_codes or set())]
            keep_list = [x for x in tmp if x in unassigned]

        new_text = "、".join(keep_list)

        # 候选 = 未分配 ∪ 本tab已保存（无论是否当前tab，都一样）
        cand = unassigned | saved_set

        table.blockSignals(True)
        try:
            if item_val:
                item_val.setText(new_text)
            else:
                it = QTableWidgetItem(new_text)
                it.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_idx, 1, it)
        finally:
            table.blockSignals(False)

        _set_candidates_property(table, cand)
        table.viewport().update()



SEP = "、"

def _cell_text(table, r: int, c: int) -> str:
    w = table.cellWidget(r, c)
    if isinstance(w, QComboBox):
        return (w.currentText() or "").strip()
    it = table.item(r, c)
    return (it.text() or "").strip() if isinstance(it, QTableWidgetItem) else ""

def _is_multi_col_row(table, r: int) -> bool:
    """
    更稳妥的多列判定：如果第1个值单元格 (col=1) 没有被横向合并（span==1），
    且总列数>=4，则认为是 3 列值的“多列行”。
    —— 你的两列行是把 (r,1) 跨 3 列合并的；多列行则不会合并。
    """
    try:
        return table.columnCount() >= 4 and table.columnSpan(r, 1) == 1
    except Exception:
        # 某些版本没有 columnSpan 或异常时退回到旧判定
        return table.columnCount() > 2 and any(_cell_text(table, r, c) != "" for c in range(2, table.columnCount()))

def _dedup_keep_order(items):
    seen = set(); out = []
    for x in items or []:
        x = (x or "").strip()
        if x and x not in seen:
            seen.add(x); out.append(x)
    return out

_BRACKETS = [('（','）'), ('(',')'), ('[',']')]

def _strip_units_from_label(label: str) -> str:
    """
    去掉 UI 字段名尾部的单位标注：
    - 壁厚（mm） -> 壁厚
    - 温度(℃) -> 温度
    - 流量 kg/s -> 流量
    - 压力 MPa -> 压力
    """
    s = (label or "").strip()

    # 1) 末尾括号单位： 名称（mm） / 名称(mm) / 名称[mm]
    for L, R in _BRACKETS:
        m = re.match(rf"^(.*?){re.escape(L)}\s*[^ {re.escape(L+R)}]*\s*{re.escape(R)}\s*$", s)
        if m:
            return m.group(1).rstrip(" ：:")

    # 2) 尾部空格+单位（无括号）： 名称 kg/s、名称 MPa、名称 ℃
    m = re.match(r"^(.*?)(?:\s|[：:])+[a-zA-Zμµ%°℃℉/·\-\*\^0-9]+$", s)
    if m and m.group(1).strip():
        return m.group(1).strip()

    return s

def _ui2db_name(label: str, viewer_instance=None) -> str:
    """
    UI → DB 基础名：
    1) 先剥单位
    2) 再查可选的自定义映射 name_map_ui2db（如需特殊保留/改名）
    """
    base = _strip_units_from_label(label)
    name_map = getattr(viewer_instance, "name_map_ui2db", None) or {}
    return name_map.get(base, base)

def save_other_params_for_tab(viewer_instance, table_param, product_id, tab_name):
    """
    把“除管口号外”的参数行写库：
    - 单列行： (product_id, tab_name, label, value)
    - 多列行： (product_id, tab_name, f"{label}{i}", value_i)  i=1..3
    """
    rows_to_save = []

    for r in range(table_param.rowCount()):
        it0 = table_param.item(r, 0)
        if not it0:
            continue
        label_ui = it0.text().strip()
        if not label_ui:
            continue
        if label_ui == "管口号":
            # “管口号”另有 save_guankou_codes_for_tab 处理，这里跳过
            continue

        label_db_base = _ui2db_name(label_ui, viewer_instance)

        if _is_multi_col_row(table_param, r):
            # —— 多列行：展开 label1/label2/label3 —— #
            # 列序：值列通常是 1、2、3；保证最多取 3 个
            value_cols = [1, 2, 3] if table_param.columnCount() >= 4 else [1, 2]
            for i, c in enumerate(value_cols, start=1):
                v = _cell_text(table_param, r, c)
                # 这里如果你想“空值不写库”，可改成：if v != "": 再 append
                rows_to_save.append((product_id, tab_name, f"{label_db_base}{i}", v))
        else:
            # —— 两列行（(r,1) 跨 3 列）或普通单值行 —— #
            v1 = _cell_text(table_param, r, 1)
            rows_to_save.append((product_id, tab_name, label_db_base, v1))

    # 批量更新
    ret = update_guankou_params_bulk(rows_to_save, treat_empty_as_null=True)
    print(f"[调试] Tab={tab_name} 更新参数 {ret['updated']} 行, 未命中 {len(ret['missing'])} 行")




def on_confirm_guankouparam(viewer_instance):#已修改
    print("点击了管口确定按钮")

    # tab_name = viewer_instance.tabWidget.tabText(viewer_instance.tabWidget.currentIndex())
    #
    # if tab_name == "管口材料分类1":
    #     table_param = viewer_instance.tableWidget_guankou
    # else:
    #     table_param = viewer_instance.dynamic_guankou_param_tabs.get(tab_name)
    #
    # if table_param is None:
    #     table_param = viewer_instance.tableWidget_guankou

    tw = getattr(viewer_instance, "guankou_tabWidget", None)
    if tw is None:
        return

    cur_idx = tw.currentIndex()
    tab_name = tw.tabText(cur_idx).strip()

    table_param = _get_tab_table(viewer_instance, cur_idx)  # 统一用按索引取表
    if table_param is None:
        QMessageBox.warning(viewer_instance, "错误", f"未找到 {tab_name} 的参数表")
        return

    # 读“管口号”
    selected_text = ""
    for r in range(table_param.rowCount()):
        it0 = table_param.item(r, 0)
        if it0 and it0.text().strip() == "管口号":
            it1 = table_param.item(r, 1)
            selected_text = (it1.text().strip() if (it1 and it1.text()) else "")
            break

    import re
    def parse_codes(s: str):
        return [x for x in re.split(r"[、，,\s]+", s.strip()) if x]

    selected_codes = parse_codes(selected_text)

    # 1) 保存占用（确保 commit）
    try:
        save_guankou_codes_for_tab(getattr(viewer_instance, "product_id", None), tab_name, selected_codes)
        if hasattr(viewer_instance, "force_commit"):
            viewer_instance.force_commit()  # 如有这个方法就调用；没有就忽略
        save_other_params_for_tab(viewer_instance, table_param, viewer_instance.product_id, tab_name)
    except Exception as e:
        print(f"[错误] 保存占用失败：{e}")

    # 2) 刷新（把“本次真正分配集合”传进去）
    refresh_all_tabs_after_save(viewer_instance, cur_idx, set(selected_codes))

    QMessageBox.information(viewer_instance, "提示", f"{tab_name} 已保存管口号：{selected_text or '无'}")








def render_additional_info_table(viewer_instance, additional_info):
    details_table = viewer_instance.tableWidget_detail
    with FreezeUI(details_table):   # 🚩 批量操作前冻结
        details_table.setRowCount(0)
        details_table.clearContents()
        headers = ["参数名称", "参数值", "参数单位"]
        details_table.setColumnCount(len(headers))
        details_table.setHorizontalHeaderLabels(headers)
        details_table.setRowCount(len(additional_info))
        for row_idx, row_data in enumerate(additional_info):
            for col_idx, header_name in enumerate(headers):
                item = QTableWidgetItem(str(row_data.get(header_name, "")))
                item.setTextAlignment(Qt.AlignCenter)
                if col_idx in [0, 2]:
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
                    table.setRowHidden(r, not (control_value == "是" and value == "钢板"))
                if pname == field_info["status_field"]:
                    table.setRowHidden(r, not (control_value == "是" and value == "钢板"))

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

                if value == "钢板":
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


def find_row_by_param_name(table: QTableWidget, name: str, param_col: int,
                           *, fuzzy: bool = False) -> Optional[int]:
    """
    在参数表中按“参数名称列(param_col)”查找行号。
    - 精确匹配：默认；去掉前后空格后完全相等
    - 模糊匹配：fuzzy=True 时，支持以 name 为前缀（如 '覆层材料级别' 可匹配 '管程侧覆层材料级别'）
    找不到返回 None
    """
    if not table or name is None:
        return None

    target = (str(name)).strip()
    if not target:
        return None

    for r in range(table.rowCount()):
        it = table.item(r, param_col)
        if not it:
            continue
        txt = (it.text() or "").strip()
        if txt == target:
            return r
        if fuzzy and txt.startswith(target):
            return r
    return None

def _apply_cladding_type_logic(table, param_col, value_col, type_field_name: str, type_value: str):
    """
    覆层材料类型联动：
      - = '焊材'  → 隐藏「覆层材料级别」「覆层使用状态」，并把「覆层成型工艺」限定为 ['堆焊'] 且值=堆焊
      - = '板材'  → 显示 上述两项，且「覆层成型工艺」候选 ['轧制复合','爆炸焊接']，默认爆炸焊接
      - 其它/空   → 仅恢复可见，不强制设工艺
    同时支持「管程侧/壳程侧」前缀的同名字段。
    """
    from PyQt5.QtCore import QSignalBlocker
    from PyQt5.QtWidgets import QTableWidgetItem
    # 你项目里已经在本函数中使用过 ComboDelegate，这里直接复用
    # from modules.cailiaodingyi.controllers.combo import ComboDelegate  # 若需要显式导入就解开

    prefix = "管程侧" if type_field_name.startswith("管程侧") else ("壳程侧" if type_field_name.startswith("壳程侧") else "")
    def N(x): return f"{prefix}{x}" if prefix else x

    def _row(label):
        return find_row_by_param_name(table, label, param_col)

    def _set(row, text):
        if row is None: return
        with QSignalBlocker(table):
            it = table.item(row, value_col)
            if it is None:
                it = QTableWidgetItem("")
                table.setItem(row, value_col, it)
            it.setText(text or "")

    level_row = _row(N("覆层材料级别"))
    state_row = _row(N("覆层使用状态"))
    craft_row = _row(N("覆层成型工艺"))

    v = (type_value or "").strip()
    if v == "焊材":
        if level_row is not None: table.setRowHidden(level_row, True)
        if state_row is not None: table.setRowHidden(state_row, True)
        if craft_row is not None:
            # 只允许“堆焊”
            try:
                table.setItemDelegateForRow(craft_row, ComboDelegate(["堆焊"], table))
            except Exception:
                pass
            _set(craft_row, "堆焊")
    elif v in ("板材", "钢板"):
        # 显示“覆层材料级别/覆层使用状态”
        if level_row is not None: table.setRowHidden(level_row, False)
        if state_row is not None: table.setRowHidden(state_row, False)
        # “覆层成型工艺”可选：爆炸焊接、轧制复合；默认爆炸焊接
        if craft_row is not None:
            try:
                # 注意把“爆炸焊接”放前面，便于默认
                table.setItemDelegateForRow(craft_row, ComboDelegate(["爆炸焊接", "轧制复合"], table))
            except Exception:
                pass
            cur = table.item(craft_row, value_col)
            cur_txt = cur.text().strip() if cur else ""
            # 若当前为空或不在可选范围内，则设为默认“爆炸焊接”
            if cur_txt not in ("爆炸焊接", "轧制复合"):
                _set(craft_row, "爆炸焊接")
    else:
        # 恢复可见，不强制设值
        if level_row is not None: table.setRowHidden(level_row, False)
        if state_row is not None: table.setRowHidden(state_row, False)



def apply_paramname_combobox(table: QTableWidget, param_col: int, value_col: int, viewer_instance):
    """
    最终版：
      - 普通下拉：使用现有 ComboDelegate(options)
      - 材料四字段：install_material_delegate_linkage() 统一安装代理 + 建立联动
      - 数值字段：QLineEdit + 校验（含腐蚀裕量自动带入）
      - 覆层开关：使用 ComboDelegate(['是','否']) + itemChanged 联动/写库/刷新
      - 其它元件的“显隐联动”：evaluate_visibility_rules_from_db()（查库+计算封装）
    """
    # ===== 常量集合 =====
    MATERIAL_FIELDS = {"材料类型", "材料牌号", "材料标准", "供货状态"}
    COVERING_SWITCH_GLOBAL = {"是否添加覆层"}
    COVERING_SWITCH_SIDED  = {"管程侧是否添加覆层", "壳程侧是否添加覆层"}
    CLADDING_TYPE_FIELDS = {"覆层材料类型", "管程侧覆层材料类型", "壳程侧覆层材料类型"}
    READONLY_PARAMS = {"元件名称", "零件名称"}   # 这里把“零件名称”也列为只读

    # ---------- 工具：安全获取当前元件名称 ----------
    def _current_element_name() -> str:
        name = ""
        try:
            ced = getattr(viewer_instance, "clicked_element_data", None) or {}
            # ① 先从 clicked_element_data 里拿
            for key in ("元件名称", "零件名称"):
                if key in ced and str(ced.get(key) or "").strip():
                    name = str(ced.get(key)).strip()
                    break
            # ② 拿不到就从表里读“元件名称/零件名称”的值列
            if not name:
                for key in ("元件名称", "零件名称"):
                    r = find_row_by_param_name(table, key, param_col)
                    if r is not None:
                        itv = table.item(r, value_col)
                        txt = (itv.text() if itv else "") if itv else ""
                        if txt and str(txt).strip():
                            name = str(txt).strip()
                            break
        except Exception as e:
            print(f"[显隐规则] 元件名获取异常: {e}")
        if not name:
            print("[显隐规则] 未获取到元件名称（规则将不生效）")
        return name

    # ---------- 数值代理 ----------
    class NumericDelegate(QStyledItemDelegate):
        def __init__(self, rule: str, pname_for_tip: str, minmax=None):
            super().__init__(table)
            self.rule = rule
            self.pname = pname_for_tip
            self.minmax = minmax or (None, None, True, True)
        def createEditor(self, parent, option, index):
            le = QLineEdit(parent)
            le.setAlignment(Qt.AlignCenter)
            le.setAutoFillBackground(True)
            le.setStyleSheet("""
                QLineEdit{
                    border:none;
                    background:palette(base);
                    font-size:9pt;
                    font-family:"Microsoft YaHei";
                    padding-left:2px;
                }
            """)
            le.editingFinished.connect(lambda: self.commitData.emit(le))
            le.returnPressed.connect(lambda: (self.commitData.emit(le),
                                              self.closeEditor.emit(le, QStyledItemDelegate.NoHint)))
            le.installEventFilter(self)
            return le
        def eventFilter(self, editor, ev):
            if isinstance(editor, QLineEdit) and ev.type() == QEvent.FocusOut:
                try: self.commitData.emit(editor)
                except Exception: pass
            return super().eventFilter(editor, ev)
        def setEditorData(self, editor, index):
            editor.setText(index.data() or ""); editor.selectAll()
        def updateEditorGeometry(self, editor, option, index):
            editor.setGeometry(option.rect)
        def setModelData(self, editor, model, index):
            tip = getattr(viewer_instance, "line_tip", None)
            txt = (editor.text() or "").strip()
            def show_tip(msg: str):
                if not tip: return
                tip.setStyleSheet("color:red;"); tip.setText(msg)
                QTimer.singleShot(0,  lambda: (tip.setStyleSheet("color:red;"), tip.setText(msg)))
                QTimer.singleShot(50, lambda: (tip.setStyleSheet("color:red;"), tip.setText(msg)))
            def clear_tip():
                if tip: tip.setText("")
            if txt == "":
                model.setData(index, ""); clear_tip(); return
            try:
                val = float(txt); ok = True; limit_msg = "有效数值"
                if self.rule == "gt0": ok = (val > 0);  limit_msg = "大于 0"
                elif self.rule == "ge0": ok = (val >= 0); limit_msg = "大于等于 0"
                elif self.rule == "range":
                    lo, hi, lo_inc, hi_inc = self.minmax; parts = []
                    if lo is not None: ok = ok and (val >= lo if lo_inc else val > lo); parts.append(("≥" if lo_inc else ">") + str(lo))
                    if hi is not None: ok = ok and (val <= hi if hi_inc else val < hi); parts.append(("≤" if hi_inc else "<") + str(hi))
                    limit_msg = " 且 ".join(parts) if parts else "有效范围"
                if not ok: show_tip(f"第 {index.row() + 1} 行参数“{self.pname}”的值应为{limit_msg}的数字！"); model.setData(index, ""); return
                clear_tip(); model.setData(index, txt)
            except Exception:
                show_tip(f"第 {index.row() + 1} 行参数“{self.pname}”的值应为数字！"); model.setData(index, "")

    def _prefix_from(name: str) -> str:
        return "管程侧" if name.startswith("管程侧") else ("壳程侧" if name.startswith("壳程侧") else "")

    def _is_covering_enabled_for(field_name: str) -> bool:
        prefix = _prefix_from(field_name)
        switch = f"{prefix}是否添加覆层" if prefix else "是否添加覆层"
        r_sw = find_row_by_param_name(table, switch, param_col)
        if r_sw is None: return False
        it_sw = table.item(r_sw, value_col)
        return bool(it_sw and it_sw.text().strip() == "是")

    # 可能会用到的外部数据
    try:
        param_names = set(get_all_param_name() or [])
    except Exception:
        param_names = set()
    gt0_params, ge0_params, range_params = get_numeric_rules()

    # 1) 单击进入编辑
    table.setEditTriggers(QAbstractItemView.SelectedClicked)

    # 2) 清理 value 列 cellWidget
    for r in range(table.rowCount()):
        if table.cellWidget(r, value_col):
            table.setCellWidget(r, value_col, None)

    # 简化的小工具
    def ensure_editable_item(r, c, txt=""):
        it = table.item(r, c)
        if it is None:
            it = QTableWidgetItem(txt); table.setItem(r, c, it)
        it.setTextAlignment(Qt.AlignCenter)
        it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
        return it
    def ensure_readonly_item(r, c, txt=""):
        it = table.item(r, c)
        if it is None:
            it = QTableWidgetItem(txt); table.setItem(r, c, it)
        it.setTextAlignment(Qt.AlignCenter)
        it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        return it

    # 3) 渲染每一行（保持你的原有分支）
    for row in range(table.rowCount()):
        pitem = table.item(row, param_col)
        pname = pitem.text().strip() if pitem else ""

        if pname in READONLY_PARAMS:
            table.setItemDelegateForRow(row, None)
            if table.cellWidget(row, value_col): table.setCellWidget(row, value_col, None)
            cur = table.item(row, value_col).text().strip() if table.item(row, value_col) else ""
            ensure_readonly_item(row, value_col, cur); continue

        if pname in MATERIAL_FIELDS:
            cur_text = table.item(row, value_col).text().strip() if table.item(row, value_col) else ""
            ensure_editable_item(row, value_col, cur_text); continue

        if (pname in gt0_params) or (pname in ge0_params) or (pname in range_params):
            vitem = table.item(row, value_col); cur_text = vitem.text().strip() if vitem else ""
            if pname in ["管程侧腐蚀裕量", "壳程侧腐蚀裕量"]:
                try:
                    ct, cs = get_corrosion_allowance_from_db(viewer_instance.product_id)
                    element_id = viewer_instance.clicked_element_data.get("元件ID", "")
                    if pname == "管程侧腐蚀裕量" and ct is not None:
                        cur_text = str(ct); update_element_para_data(viewer_instance.product_id, element_id, pname, cur_text)
                    if pname == "壳程侧腐蚀裕量" and cs is not None:
                        cur_text = str(cs); update_element_para_data(viewer_instance.product_id, element_id, pname, cur_text)
                except Exception as e:
                    print(f"[腐蚀裕量带入失败] {e}")
            ensure_editable_item(row, value_col, cur_text)
            if pname in gt0_params: rule, minmax = "gt0", None
            elif pname in ge0_params: rule, minmax = "ge0", None
            else: rule, minmax = "range", range_params.get(pname)
            table.setItemDelegateForRow(row, NumericDelegate(rule, pname, minmax)); continue

        if pname in COVERING_SWITCH_GLOBAL or pname in COVERING_SWITCH_SIDED:
            vitem = table.item(row, value_col); cur_text = "是" if (vitem and vitem.text().strip() == "是") else "否"
            ensure_editable_item(row, value_col, cur_text)
            table.setItemDelegateForRow(row, ComboDelegate(["是", "否"], table)); continue

        # 普通下拉
        options = []
        try:
            if pname in param_names: options = get_options_for_param(pname) or []
        except Exception: options = []
        cur_text = table.item(row, value_col).text().strip() if table.item(row, value_col) else ""
        ensure_editable_item(row, value_col, cur_text)
        options = [o for o in dict.fromkeys([str(x).strip() for x in options]) if o != ""]
        if options: table.setItemDelegateForRow(row, ComboDelegate(options, table))
        else:       table.setItemDelegateForRow(row, None)

    # ==== 显隐规则：初次渲染后评估 ====
    try:
        ele_name = _current_element_name()
        if ele_name:
            effects = evaluate_visibility_rules_from_db(
                ele_name, table=table, param_col=param_col, value_col=value_col, viewer_instance=viewer_instance
            )
            with FreezeUI(table):
                for tgt_param, act in effects.items():
                    rr = find_row_by_param_name(table, tgt_param, param_col)
                    if rr is not None:
                        table.setRowHidden(rr, act == "HIDE")
    except Exception as e:
        print(f"[显隐规则-初次评估失败] {e}")

    # 4) itemChanged：覆层联动 + 写库 + 图片刷新 + 再评估显隐
    def _on_item_changed(item: QTableWidgetItem):
        if item.column() != value_col: return
        r = item.row()
        pitem = table.item(r, param_col)
        if not pitem: return
        pname = pitem.text().strip()
        val = (item.text() or "").strip()

        if pname in CLADDING_TYPE_FIELDS:
            if not _is_covering_enabled_for(pname): return
            with FreezeUI(table):
                _apply_cladding_type_logic(table, param_col, value_col, pname, val)
            # 注意：不要 return，这样改变覆层类型后也会走一次显隐评估
        if pname in COVERING_SWITCH_GLOBAL or pname in COVERING_SWITCH_SIDED:
            try:
                product_id = viewer_instance.product_id
                element_id = viewer_instance.clicked_element_data.get("元件ID", "")
                update_element_para_data(product_id, element_id, pname, val)
            except Exception as e:
                print(f"[写库失败] {pname}={val}: {e}")

        if pname in COVERING_SWITCH_GLOBAL:
            handler = make_on_covering_changed(
                viewer_instance.clicked_element_data, viewer_instance, r, table=table
            ); handler(val)
            class _Fake:
                def __init__(self, t): self._t = t
                def currentText(self): return self._t
            with FreezeUI(table):
                toggle_covering_fields(table, _Fake(val), pname)
                if val == "是":
                    type_field = "覆层材料类型"
                    r_type = find_row_by_param_name(table, type_field, param_col)
                    if r_type is not None:
                        it_type = table.item(r_type, value_col)
                        cur_type = it_type.text().strip() if it_type else ""
                        _apply_cladding_type_logic(table, param_col, value_col, type_field, cur_type)

        if pname in COVERING_SWITCH_SIDED:
            refresh = make_on_fixed_tube_covering_changed_v2(
                viewer_instance.clicked_element_data, viewer_instance, table, param_col, value_col
            ); refresh()
            class _Fake:
                def __init__(self, t): self._t = t
                def currentText(self): return self._t
            with FreezeUI(table):
                toggle_covering_fields(table, _Fake(val), pname)
                if val == "是":
                    prefix = "管程侧" if pname.startswith("管程侧") else "壳程侧"
                    type_field = f"{prefix}覆层材料类型"
                    r_type = find_row_by_param_name(table, type_field, param_col)
                    if r_type is not None:
                        it_type = table.item(r_type, value_col)
                        cur_type = it_type.text().strip() if it_type else ""
                        _apply_cladding_type_logic(table, param_col, value_col, type_field, cur_type)

        # ==== 显隐规则：每次值变化后再评估 ====
        try:
            ele_name = _current_element_name()
            if ele_name:
                effects = evaluate_visibility_rules_from_db(
                    ele_name, table=table, param_col=param_col, value_col=value_col, viewer_instance=viewer_instance
                )
                with FreezeUI(table):
                    for tgt_param, act in effects.items():
                        rr = find_row_by_param_name(table, tgt_param, param_col)
                        if rr is not None:
                            table.setRowHidden(rr, act == "HIDE")
        except Exception as e:
            print(f"[显隐规则-变更后评估失败] {e}")

    # 防重复绑定
    old_handler = getattr(table, "_covering_item_changed_handler", None)
    if old_handler is not None:
        try: table.itemChanged.disconnect(old_handler)
        except Exception: pass
    table.itemChanged.connect(_on_item_changed)
    table._covering_item_changed_handler = _on_item_changed

    # 5) 单击进入编辑
    def _edit_on_click(r, c):
        idx = table.model().index(r, c)
        it = table.item(r, c)
        if idx.isValid() and it and (it.flags() & Qt.ItemIsEditable):
            table.setCurrentIndex(idx); table.edit(idx)
    try: table.cellClicked.disconnect()
    except Exception: pass
    table.cellClicked.connect(_edit_on_click)








def apply_linked_param_combobox(table, param_col, value_col, mapping):
    """
    根据联动表映射创建主字段和被控字段的“代理下拉”，并设置联动关系（即时生效）。
    mapping 结构示例：
    {
        "主字段A": {
            "主值1": {"从字段X": [..], "从字段Y": [..]},
            "主值2": {"从字段X": [..], "从字段Y": [..]},
        },
        "主字段B": { ... }
    }
    """
    from PyQt5.QtWidgets import QTableWidgetItem, QAbstractItemView

    # ---- 便捷读写 ----
    def _get(r):
        it = table.item(r, value_col)
        return (it.text().strip() if it else "")

    def _set(r, txt):
        it = table.item(r, value_col)
        if it is None:
            it = QTableWidgetItem()
            it.setTextAlignment(Qt.AlignCenter)
            table.setItem(r, value_col, it)
        it.setText(txt or "")

    # 所有参与联动的字段名
    master_fields = list(mapping.keys())
    dependent_fields_all = {}  # master -> set(all dependent fields)
    for mf in master_fields:
        s = set()
        for mv, submap in (mapping.get(mf, {}) or {}).items():
            s.update((submap or {}).keys())
        dependent_fields_all[mf] = s

    # 建立 “字段名 -> 行号” 索引
    name_to_row = {}
    for r in range(table.rowCount()):
        it = table.item(r, param_col)
        if it:
            name_to_row[it.text().strip()] = r

    # 去掉 cellWidget，保证可编辑
    for fname in set(master_fields) | set().union(*dependent_fields_all.values()):
        r = name_to_row.get(fname, -1)
        if r >= 0:
            if table.cellWidget(r, value_col):
                table.setCellWidget(r, value_col, None)
            _ensure_editable_item(table, r, value_col)

    table.setEditTriggers(QAbstractItemView.SelectedClicked)

    # ---- 安装“被控字段”的代理（无回调，仅提供候选）----
    def _install_dependent_delegate(sub_field, options):
        r = name_to_row.get(sub_field, -1)
        if r < 0:
            return
        # 去空/去重/保序
        seen, opts = set(), []
        for o in (options or []):
            s = (o or "").strip()
            if s and s not in seen:
                seen.add(s); opts.append(o)

        # 被控字段不需要回调
        table.setItemDelegateForRow(r, MaterialInstantDelegate(opts, table, field_name=sub_field, on_pick=None))

        # 校验当前值；不合法则修正：唯一候选自动带入，否则清空
        cur = _get(r)
        if opts:
            if cur and (cur not in opts):
                _set(r, opts[0] if len(opts) == 1 else "")
        else:
            # 没有候选时保持现值（或按需清空）
            pass

    # ---- 安装“主字段”的代理（带回调，驱动联动）----
    def _install_master_delegate(master_field):
        r_master = name_to_row.get(master_field, -1)
        if r_master < 0:
            return

        saved = _get(r_master)
        # 主字段候选：mapping[master_field] 的所有 key
        base_opts = list((mapping.get(master_field) or {}).keys())

        # 如果数据库已有值且不在候选，补进去以便初始命中
        if saved and (saved not in base_opts):
            base_opts = base_opts + [saved]

        # 回调：当主字段选中变化时，刷新被控字段
        def on_master_pick(_field_name, new_text, _row, _col):
            # 主字段未选时，跳过（不清空已有从字段）
            if not (new_text or "").strip():
                return

            # 根据当前主值拿到 “从字段 -> 候选列表”
            submap = (mapping.get(master_field, {}) or {}).get(new_text, {}) or {}

            # 对该主字段下的“所有可能从字段”都处理：
            for sub_field in dependent_fields_all.get(master_field, []):
                opts = submap.get(sub_field, [])
                _install_dependent_delegate(sub_field, opts)

            table.viewport().update()

        table.setItemDelegateForRow(
            r_master,
            MaterialInstantDelegate(base_opts, table, field_name=master_field, on_pick=on_master_pick)
        )

        # 用“当前主值”做一次初始化刷新
        if saved:
            on_master_pick(master_field, saved, r_master, value_col)

    # 逐个主字段安装代理并初始化一次
    for mf in master_fields:
        _install_master_delegate(mf)





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
                            table.setRowHidden(r, not (cover_value == "是" and value == "钢板"))
                        if pname == "覆层使用状态":
                            table.setRowHidden(r, not (cover_value == "是" and value == "钢板"))

                    # ✅ 更新覆层成型工艺的下拉内容
                    if "覆层成型工艺" in field_widgets and cover_value == "是":
                        combo_widget = field_widgets["覆层成型工艺"]
                        combo_widget.blockSignals(True)
                        combo_widget.clear()
                        combo_widget.addItem("")
                        if value == "钢板":
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






