import re
from collections import defaultdict
from functools import partial

from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import QComboBox, QTableWidget, QTableWidgetItem
from PyQt5.QtCore import Qt, QTimer, QObject

from modules.cailiaodingyi.controllers.datamanager import (
    load_data_by_template, ask_before_switch_template_against_current
)
from modules.cailiaodingyi.demo import NoWheelComboBoxFilter
from modules.cailiaodingyi.funcs.funcs_pdf_change import (
    update_guankou_define_data,
    update_guankou_define_status,
    load_element_data_by_product_id, is_all_guankou_parts_defined, get_filtered_material_options,
    query_template_name_by_product
)
from modules.cailiaodingyi.funcs.funcs_pdf_input import (
    move_guankou_to_first, move_guankou_attachment_to_second, update_template_input_editable_state
)






def handle_template_change(viewer_instance, index):
    print("handle_template_change called with index:", index)
    selected_template = viewer_instance.comboBox_template.itemText(index).strip()
    # 特殊处理：如果模板名称为空字符串，则设置为"None"
    if not selected_template:
        selected_template = "None"
        print(f"[调试] 模板名称为空，设置为: '{selected_template}'")



    pid = getattr(viewer_instance, "product_id", None)
    if not pid:
        viewer_instance.show_error_message("提示", "未检测到产品ID，无法切换模板")
        return

    # ✅ 先尝试从数据库取
    old_template = query_template_name_by_product(pid)
    print(f"old{old_template}")
    # ✅ 如果取不到，就 fallback 用当前控件保存的 current_template_name
    if not old_template:
        old_template = getattr(viewer_instance, "current_template_name", "").strip()

    ok = ask_before_switch_template_against_current(
        viewer_instance,
        pid,
        base_template_name=old_template,
        target_template_name=selected_template
    )
    if not ok:
        print("[模板切换] 用户取消")
        try:
            viewer_instance._template_reverting = True
            viewer_instance.comboBox_template.blockSignals(True)
            viewer_instance.comboBox_template.setCurrentIndex(getattr(viewer_instance, "_template_prev_index", 0))
        finally:
            viewer_instance.comboBox_template.blockSignals(False)
            viewer_instance._template_reverting = False
        return

    # 真正切换
    load_data_by_template(viewer_instance, selected_template)

    viewer_instance.current_template_name = selected_template
    viewer_instance._template_prev_index = index




# 初始化（UI建立好且下拉框已有值后调用一次）
def init_template_combo_hooks(self):
    self.current_template_name = self.comboBox_template.currentText().strip()
    self._template_prev_index = self.comboBox_template.currentIndex()
    self._template_reverting = False
    self.comboBox_template.currentIndexChanged.connect(
        lambda idx: handle_template_change(self, idx)
    )




def inject_material_refresh(combo: QComboBox, table: QTableWidget, row: int, col: int):
    def refresh_options_before_dropdown():
        on_pipe_material_combobox_changed(table, row, col)

    # 注入 mousePressEvent（下拉点击前触发）
    original_mouse_press = combo.mousePressEvent

    def new_mouse_press(event):
        refresh_options_before_dropdown()
        original_mouse_press(event)

    combo.mousePressEvent = new_mouse_press

# def apply_combobox_to_table(table: QTableWidget, column_data_map: dict,
#                             guankou_define_info, product_id,
#                             viewer_instance, category_label: str):
#     """
#     给管口零件表格的定义设置下拉框
#     """
#     # ✅ 彻底清除旧控件
#     for row in range(table.rowCount()):
#         for col in range(table.columnCount()):
#             table.removeCellWidget(row, col)
#
#     # ✅ 确保每个单元格有 QTableWidgetItem（避免 .text() 报错）
#     for row in range(table.rowCount()):
#         for col in range(table.columnCount()):
#             if not table.item(row, col):
#                 table.setItem(row, col, QTableWidgetItem(""))
#
#     # ✅ 插入 ComboBox 并绑定信号
#     for row in range(table.rowCount()):
#         for col, items in column_data_map.items():
#             # 获取当前单元格显示文本（使用 viewport 渲染过的数据）
#             item = table.item(row, col)
#             current_text = item.text().strip() if item else ""
#
#             # 创建下拉框
#             combo = QComboBox()
#             combo.addItem("")
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
#             combo.addItems(items)
#
#             combo.blockSignals(True)
#             if current_text in items:
#                 combo.setCurrentText(current_text)
#             else:
#                 combo.setCurrentIndex(0)
#             combo.blockSignals(False)
#
#             # print(f"row {row}, col {col} 原始值：'{current_text}'，选中下拉值：'{combo.currentText()}'")
#
#             # 设置下拉框替代原单元格内容
#             table.setItem(row, col, None)
#             table.setCellWidget(row, col, combo)
#
#             combo.currentIndexChanged.connect(partial(
#                 on_combo_changed, guankou_define_info, table, row, col,
#                 product_id, viewer_instance, category_label
#             ))
#             combo.currentIndexChanged.connect(partial(
#                 on_pipe_material_combobox_changed, table, row, col
#             ))
#
#             QTimer.singleShot(0, lambda r=row, c=col: on_pipe_material_combobox_changed(table, r, c))
#
#         # # ✅ 每行控件设置完后，主动刷新一次联动逻辑
#         # on_material_field_changed_row(table, row)
def apply_combobox_to_table(table: QTableWidget, column_data_map: dict,
                            guankou_define_info, product_id,
                            viewer_instance, category_label: str):
    """
    设置“管口材料分类”表格的四字段联动下拉框（列式结构）
    """

    col_to_field = {
        1: '材料类型',
        2: '材料牌号',
        3: '材料标准',
        4: '供货状态'
    }
    field_to_col = {v: k for k, v in col_to_field.items()}

    # 清除旧控件 + 初始化空Item
    for row in range(table.rowCount()):
        for col in range(table.columnCount()):
            table.removeCellWidget(row, col)
            if not table.item(row, col):
                table.setItem(row, col, QTableWidgetItem(""))

    # 遍历每一行
    for row in range(table.rowCount()):
        combo_map = {}

        # 为每列插入 combo
        for col, field in col_to_field.items():
            current_text = table.item(row, col).text().strip()

            combo = QComboBox()
            combo.setEditable(True)
            combo.setStyleSheet("""
                QComboBox {
                    border: none;
                    background-color: transparent;
                    font-size: 9pt;
                    font-family: "Microsoft YaHei";
                    padding-left: 2px;
                }
            """)
            combo.lineEdit().setAlignment(Qt.AlignCenter)

            # 添加初始备选项
            all_options = column_data_map.get(col, [])
            combo.addItem("")
            combo.addItems(all_options)
            combo.full_options = all_options.copy()

            # ✨设置 tooltip
            for i in range(combo.count()):
                combo.setItemData(i, combo.itemText(i), Qt.ToolTipRole)

            # ✅ 设置下拉框宽度适配最长项
            max_text_width = max([combo.fontMetrics().width(text) for text in all_options] + [0])
            combo.view().setMinimumWidth(max_text_width + 40)  # 加40避免贴边

            # 设置当前值
            if current_text in all_options:
                combo.setCurrentText(current_text)
            else:
                combo.setCurrentIndex(0)

            combo.installEventFilter(NoWheelComboBoxFilter(combo))
            table.setItem(row, col, None)
            table.setCellWidget(row, col, combo)
            combo_map[field] = combo

        # 🔁 绑定每个 combo 的 textChanged 事件（对整行生效）
        for field, combo in combo_map.items():
            col = field_to_col[field]
            combo.currentTextChanged.connect(
                partial(on_material_combobox_changed_rowwise, table, row, col_to_field, column_data_map)
            )

            # combo.currentIndexChanged.connect(
            #     partial(on_combo_changed, viewer_instance, table, col, category_label)
            # )
            combo.currentIndexChanged.connect(partial(
                on_combo_changed, guankou_define_info, table, row, col,
                product_id, viewer_instance, category_label
            ))

        # ✅ 初始化时主动触发一次
        QTimer.singleShot(0, partial(on_material_combobox_changed_rowwise, table, row, col_to_field, column_data_map))






def on_combo_changed(guankou_define_info, table, row, col, product_id, viewer_instance, category_label):
    """
    下拉框内容改变时的事件处理函数
    """
    # 获取当前单元格中的下拉框并获取选中的文本
    combo = table.cellWidget(row, col)
    new_value = combo.currentText().strip()
    print(f"更新的数据{new_value}")

    # 获取当前行的数据
    clicked_guankou_define_data = guankou_define_info[row]
    print(f"点击的行数据: {clicked_guankou_define_data}")

    # 通过行数据获取管口零件ID
    guankou_id = clicked_guankou_define_data.get("管口零件ID", None)
    print(f"获取到的管口零件ID: {guankou_id}")

    # 映射列索引对应的数据库字段
    column_map = {1: '材料类型', 2: '材料牌号', 3: '材料标准', 4: '供货状态'}

    # 获取对应列的字段名
    field_name = column_map.get(col, "未知字段")
    combo.setToolTip(new_value)
    combo.lineEdit().setToolTip(new_value)
    combo.currentTextChanged.connect(lambda text, c=combo: (
        c.setToolTip(text),
        c.lineEdit().setToolTip(text)
    ))
    print(f"更新的字段: {field_name}")

    # 更新管口零件定义数据库
    update_guankou_define_data(product_id, new_value, field_name, guankou_id, category_label)

    element_name = "管口"

    # 执行元件表中管口的更新操作
    if (is_all_guankou_parts_defined(viewer_instance.product_id)):
        # update_guankou_define_status(product_id, element_name)
        update_element_info = load_element_data_by_product_id(product_id)
        updated_element_info = move_guankou_to_first(update_element_info)
        updated_element_info = move_guankou_attachment_to_second(updated_element_info)
        print(f"更新后的元件列表{updated_element_info}")
        viewer_instance.render_data_to_table(updated_element_info)
        # 存为模板
        # update_template_input_editable_state(viewer_instance)


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

    # 特例：改动材料类型时清空其他三项（无论是否有值，只要改成空就清空）
    if sender_field == "材料类型":
        # 如果材料类型为空，直接清空后三项
        if not selected.get("材料类型", ""):
            for field in ['材料牌号', '材料标准', '供货状态']:
                combo = combo_map[field]
                combo.blockSignals(True)
                combo.clear()
                combo.addItem("")
                table.setItem(row, field_to_col[field], QTableWidgetItem(""))
                combo.blockSignals(False)
            selected = {}  # 全清空
        # 否则如果材料类型不兼容其他三项 → 清空不兼容项
        elif all(k in selected for k in ['材料牌号', '材料标准', '供货状态']):
            filter_basis = {"材料类型": selected["材料类型"]}
            valid_options = get_filtered_material_options(filter_basis)
            if any(selected[k] not in valid_options.get(k, []) for k in ['材料牌号', '材料标准', '供货状态']):
                for field in ['材料牌号', '材料标准', '供货状态']:
                    combo = combo_map[field]
                    combo.blockSignals(True)
                    combo.clear()
                    combo.addItem("")
                    table.setItem(row, field_to_col[field], QTableWidgetItem(""))
                    combo.blockSignals(False)
                selected = {"材料类型": selected["材料类型"]}

    # 特例：改动材料牌号后不兼容后两项，清空
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
                table.setItem(row, field_to_col[field], QTableWidgetItem(""))
                combo.blockSignals(False)
                selected.pop(field, None)

    # 联动刷新（注意各字段使用不同条件）
    for field, combo in combo_map.items():
        current_val = combo.currentText().strip()
        if field == "材料类型":
            valid_options = combo.full_options if hasattr(combo, 'full_options') else get_filtered_material_options({}).get(field, [])
        elif field == "材料牌号":
            filter_basis = {"材料类型": selected.get("材料类型", "")}
            valid_options = get_filtered_material_options(filter_basis).get(field, [])
        else:
            filter_basis = {k: v for k, v in selected.items() if k != field and k in ["材料标准", "供货状态"]}
            valid_options = get_filtered_material_options(filter_basis).get(field, [])

        combo.blockSignals(True)
        combo.clear()
        combo.addItem("")
        combo.addItems(valid_options)
        if current_val in valid_options:
            combo.setCurrentText(current_val)
        else:
            combo.setCurrentIndex(0)
        combo.blockSignals(False)

def on_pipe_material_combobox_changed(table: QTableWidget, row: int, changed_col: int):
    col_to_field = {
        1: '材料类型',
        2: '材料牌号',
        3: '材料标准',
        4: '供货状态'
    }

    selected = {}
    combo_map = {}

    for col, field in col_to_field.items():
        combo = table.cellWidget(row, col)
        if isinstance(combo, QComboBox):
            combo_map[field] = combo
            val = combo.currentText().strip()
            if val:
                selected[field] = val

    for col, field in col_to_field.items():
        combo = combo_map[field]
        current_val = combo.currentText().strip()

        filter_basis = {k: v for k, v in selected.items() if k != field}
        filtered = get_filtered_material_options(filter_basis)
        valid_options = filtered.get(field, [])

        combo.blockSignals(True)
        combo.clear()
        combo.addItem("")
        combo.addItems(valid_options)

        if current_val in valid_options:
            combo.setCurrentText(current_val)
        else:
            combo.setCurrentIndex(0)
        combo.blockSignals(False)

def on_material_combobox_changed_rowwise(table: QTableWidget, row: int,
                                         col_to_field: dict, column_data_map: dict):
    selected = {}
    combo_map = {}
    field_to_col = {v: k for k, v in col_to_field.items()}

    for col, field in col_to_field.items():
        combo = table.cellWidget(row, col)
        if isinstance(combo, QComboBox):
            combo_map[field] = combo
            val = combo.currentText().strip()
            if val:
                selected[field] = val

    sender_combo = QObject.sender(table)
    sender_field = ""
    for field, combo in combo_map.items():
        if combo is sender_combo:
            sender_field = field
            break

    # ✅ 材料类型始终显示全部
    if "材料类型" in combo_map:
        combo = combo_map["材料类型"]
        current_val = combo.currentText().strip()
        full_options = column_data_map.get(field_to_col["材料类型"], [])
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("")
        combo.addItems(full_options)
        combo.setCurrentText(current_val if current_val in full_options else "")
        combo.blockSignals(False)

    # ✅ 材料类型为空 → 清空后三项
    if sender_field == "材料类型":
        if not selected.get("材料类型", ""):
            for field in ["材料牌号", "材料标准", "供货状态"]:
                combo = combo_map[field]
                combo.blockSignals(True)
                combo.clear()
                combo.addItem("")
                table.setItem(row, field_to_col[field], QTableWidgetItem(""))
                combo.blockSignals(False)
            selected = {}
        # 材料类型变了但其他字段值不兼容 → 清空
        elif all(k in selected for k in ["材料牌号", "材料标准", "供货状态"]):
            filter_basis = {"材料类型": selected["材料类型"]}
            valid_options = get_filtered_material_options(filter_basis)
            if any(selected[k] not in valid_options.get(k, []) for k in ["材料牌号", "材料标准", "供货状态"]):
                for field in ["材料牌号", "材料标准", "供货状态"]:
                    combo = combo_map[field]
                    combo.blockSignals(True)
                    combo.clear()
                    combo.addItem("")
                    table.setItem(row, field_to_col[field], QTableWidgetItem(""))
                    combo.blockSignals(False)
                selected = {"材料类型": selected["材料类型"]}

    # ✅ 材料牌号变更 → 清空材料标准 + 供货状态
    if sender_field == "材料牌号":
        for field in ["材料标准", "供货状态"]:
            combo = combo_map[field]
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("")
            table.setItem(row, field_to_col[field], QTableWidgetItem(""))
            combo.blockSignals(False)
        selected.pop("材料标准", None)
        selected.pop("供货状态", None)

    # ✅ 联动刷新其余字段，自动填入唯一选项
    for field in ["材料牌号", "材料标准", "供货状态"]:
        combo = combo_map[field]
        current_val = combo.currentText().strip()

        # 构建筛选条件
        if field == "材料牌号":
            filter_basis = {"材料类型": selected.get("材料类型", "")}
        elif field == "材料标准":
            filter_basis = {
                "材料类型": selected.get("材料类型", ""),
                "材料牌号": selected.get("材料牌号", "")
            }
        elif field == "供货状态":
            filter_basis = {
                "材料类型": selected.get("材料类型", ""),
                "材料牌号": selected.get("材料牌号", ""),
                "材料标准": selected.get("材料标准", "")
            }
        else:
            filter_basis = {}

        valid_options = get_filtered_material_options(filter_basis).get(field, [])

        combo.blockSignals(True)
        combo.clear()
        combo.addItem("")
        combo.addItems(valid_options)

        if current_val in valid_options:
            combo.setCurrentText(current_val)
        elif len(valid_options) == 1:
            combo.setCurrentText(valid_options[0])  # ✅ 自动填入唯一值
        else:
            combo.setCurrentIndex(0)
            table.setItem(row, field_to_col[field], QTableWidgetItem(""))
        combo.blockSignals(False)











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




