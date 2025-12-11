import sys

from PyQt5 import uic
from PyQt5.QtGui import QPixmap, QPainter, QFont
from PyQt5.QtWidgets import QWidget, QMessageBox, QFileDialog, QApplication, QToolTip
from PyQt5.QtCore import QTimer, Qt
import os

from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QTableWidgetItem

from modules.chanpinguanli.bianl import current_project_id
from modules.condition_input.funcs.multi_conditions_dialog import MultiConditionsDialog
from PyQt5.QtWidgets import QMessageBox, QPushButton

# 导入功能函数
from modules.condition_input.funcs.funcs_product_info import check_pdt_define, check_has_any_product
from modules.condition_input.funcs.ctrl_helper import enable_full_undo
from modules.condition_input.funcs.funcs_cdt_input import load_design_data_if_exists, render_grouped_table, \
    render_coating_table, set_multilevel_headers, apply_table_style, highlight_missing_required_rows, \
    validate_required_fields, import_all_reference_data, save_local_condition_file, save_all_tables, \
    trigger_all_cross_table_relations, apply_design_data_dropdowns, apply_general_data_dropdowns, \
    apply_trail_data_dropdowns, TrailTableComboDelegate, highlight_entire_row, shrink_index_column, shrink_unit_column,\
    get_ref_data_excel_path, fetch_all_mode_orders, capture_default_order, apply_mode_param_order
from modules.chanpinguanli.chanpinguanli_main import product_manager
from modules.condition_input.funcs.design_data_delegate import DesignDataDelegate  # 根据实际路径调整
product_id = None


def on_product_id_changed(new_id):
    print(f"Received new PRODUCT_ID: {new_id}")
    global product_id
    product_id = new_id


# 测试用产品 ID（真实情况中由外部输入）
product_manager.product_id_changed.connect(on_product_id_changed)


#0903会议纪要 添加一个通用的检查函数，用于所有非项目管理界面
def check_project_and_product():
    """检查项目和产品状态的通用函数（修复变量引用问题）"""
    # 关键修改：直接通过bianl模块访问current_project_id
    from modules.chanpinguanli import bianl
    # 打印调试信息，确认获取的项目ID
    print(f"检查函数中获取的项目ID: {repr(bianl.current_project_id)}")
    # 检查项目ID是否有效
    if not bianl.current_project_id or str(bianl.current_project_id).strip() == "":
        return False, "请先创建项目！"
    # 检查当前项目下是否有产品
    if not check_has_any_product(bianl.current_project_id):
        return False, "请先创建至少一个产品！"
    return True, ""

class DesignConditionInputViewer(QWidget):
    def __init__(self, line_tip=None):
        super().__init__()

        # # 0903会议纪要 首先进行项目和产品检查
        # print("准备检查项目和产品状态...")
        # can_open, msg = check_project_and_product()
        # if not can_open:
        #     QMessageBox.information(self, "提示", msg)
        #     self.deleteLater()  # 不打开界面
        #     return  # 立即返回

        current_dir = os.path.dirname(os.path.abspath(__file__))
        ui_path = os.path.join(current_dir, "viewer.ui")
        uic.loadUi(ui_path, self)

        self.product_id = product_id

        self.line_tip = line_tip
        screen_geometry = QApplication.desktop().screenGeometry()
        screen_width = screen_geometry.width()
        screen_height = screen_geometry.height()
        target_width = int(screen_width * 0.7)
        target_height = int(screen_height * 0.7)
        self.resize(target_width, target_height)
        self.move((screen_width - target_width) // 2, (screen_height - target_height) // 2)

        QToolTip.setFont(QFont("Microsoft YaHei", 12))
        # self.product_id = product_id
        self._is_valid_product = True
        self._early_tip_msg = ""
        self._is_modified = False

        if not self.product_id:
            self._is_valid_product = False
            self._early_tip_msg = "请先至项目管理处选择产品！"

        elif not check_pdt_define(self.product_id):
            self._is_valid_product = False
            self._early_tip_msg = "请先至项目管理处对当前产品进行定义！"


        # 统一处理提示
        if not self._is_valid_product:
            if self.line_tip:
                self.line_tip.setText(self._early_tip_msg)
                self.line_tip.setToolTip(self._early_tip_msg)
            self.setDisabled(True)  # 禁用界面交互
            self._original_pixmap = None
            return  # 如果你仍想中断后续数据加载逻辑，可以留这个 return，但控件已完整初始化

        self._is_loading_data = True

        # === 模式下拉初始化 === 新增
        try:
            self._mode_orders = fetch_all_mode_orders()  # {模式名: [id...]}
        except Exception:
            self._mode_orders = {}

        self._default_mode_name = "设计模式"
        combo = getattr(self, "combo_mode", None)  # 直接取 UI 里的 combo_mode

        if combo is None:
            print("[ERR][init] 在 UI 里没有找到 combo_mode，请确认 .ui 文件里对象名是否为 'combo_mode'")
        else:
            combo.blockSignals(True)
            combo.clear()
            if self._default_mode_name not in self._mode_orders:
                combo.addItem(self._default_mode_name)
            else:
                other_modes = [m for m in self._mode_orders if m != self._default_mode_name]
                combo.addItems([self._default_mode_name] + other_modes)
                print(f"[DBG][init] 填充模式列表: {[combo.itemText(i) for i in range(combo.count())]}")
            combo.blockSignals(False)

            # 确保 on_mode_changed 已定义
            if hasattr(self, "on_mode_changed") and callable(self.on_mode_changed):
                combo.currentTextChanged.connect(self.on_mode_changed)
            else:
                print("[ERR][init] 没有定义 on_mode_changed 方法，无法连接信号")

        self.btn_inputrefdata.clicked.connect(self.on_input_ref_data_clicked)
        self.btn_confirm.clicked.connect(lambda: self.check_and_save_data(force=True))
        self.btn_output.clicked.connect(self.export_condition_file)
        self.import_condition_data(self.product_id)

        tables = [
            self.tableWidget_design_data,
            self.tableWidget_general_data,
            self.tableWidget_product_std,
            self.tableWidget_trail_data,
            self.tableWidget_coating_data
        ]
        for table in tables:
            font_metrics = table.fontMetrics()
            header_height = font_metrics.height() + 12
            table.horizontalHeader().setFixedHeight(header_height)

        for table in tables:
            apply_table_style(table)

        if self._is_valid_product:
            # 新增
            for table1 in [
                self.tableWidget_design_data,
                self.tableWidget_general_data,
                self.tableWidget_product_std
            ]:
                shrink_index_column(table1, width=100)

            # 新增
            for table2 in [
                self.tableWidget_design_data,
                self.tableWidget_general_data
            ]:
                shrink_unit_column(table2, width=200)
        for table in tables:
            table.itemSelectionChanged.connect(lambda t=table: highlight_entire_row(t))
        design_config = apply_design_data_dropdowns(product_id=self.product_id)
        general_config = apply_general_data_dropdowns()
        trail_config = apply_trail_data_dropdowns()
        enable_full_undo(self.tableWidget_product_std, self, mode="product")
        enable_full_undo(self.tableWidget_design_data, self, mode="design", dropdown_config=design_config)
        enable_full_undo(self.tableWidget_general_data, self, mode="general", dropdown_config=general_config)
        enable_full_undo(self.tableWidget_coating_data, self, mode="coating")
        trail_delegate = TrailTableComboDelegate(config=trail_config, parent=self.tableWidget_trail_data)
        for col in [2, 4, 5, 7]:
            self.tableWidget_trail_data.setItemDelegateForColumn(col, trail_delegate)

        from modules.condition_input.funcs.ctrl_helper import DropDownClickOnlyFilter
        filter = DropDownClickOnlyFilter(self.tableWidget_trail_data, trail_delegate)
        self.tableWidget_trail_data.viewport().installEventFilter(filter)

        enable_full_undo(self.tableWidget_trail_data, self, mode="trail")
        self.tableWidget_trail_data.viewer = self
        self.tableWidget_trail_data.undo_stack = self.undo_stack

        # 只对“设计数据”表开启单击打开多工况窗口
        self.tableWidget_design_data.viewport().installEventFilter(self)
        self._is_loading_data = False
        # 应用自定义代理显示多工况标识
        if hasattr(self, 'tableWidget_design_data') and self.tableWidget_design_data is not None:
            self.design_delegate = DesignDataDelegate()
            self.tableWidget_design_data.setItemDelegateForColumn(1, self.design_delegate)
            self.tableWidget_design_data.viewer = self
    def import_condition_data(self, product_id):
        if not product_id:
            return

        result = load_design_data_if_exists(product_id)

        if not result or not result.get("import_status"):
            QMessageBox.information(self, "提示", "未找到设计数据，表格将保持为空。")
            return

        result = load_design_data_if_exists(product_id)
        self.design_data_source = result["data_source_status"]
        print(f"数据来源：{self.design_data_source}")

        # ❗️没有导入数据，提示后返回（错误/空数据情况需要用户知道）
        if not result.get("import_status", False):
            QMessageBox.information(self, "提示", "未在产品设计活动库中找到该产品的设计数据。")
            return

        # ✅ 成功导入时不弹窗，用 print 或 QLabel 替代
        data = result["数据"]
        print("✅ 成功导入产品设计活动数据")  # 或界面提示也可

        self.fill_table_widget(
            self.tableWidget_product_std,
            data["产品标准"]["headers"],
            data["产品标准"]["rows"],
            index_header=data["产品标准"].get("prepend_index_header")
        )
        self.fill_table_widget(
            self.tableWidget_design_data,
            data["设计数据"]["headers"],
            data["设计数据"]["rows"],
            index_header=data["设计数据"].get("prepend_index_header")
        )
        self.fill_table_widget(
            self.tableWidget_general_data,
            data["通用数据"]["headers"],
            data["通用数据"]["rows"],
            index_header=data["通用数据"].get("prepend_index_header")
        )

        # === 记录默认顺序（用于保存/导出固定顺序写出）===
        #capture_default_order(self.tableWidget_product_std)
        capture_default_order(self.tableWidget_design_data)
        #capture_default_order(self.tableWidget_general_data)

        set_multilevel_headers(
            self.tableWidget_trail_data,
            top_headers=["接头种类", "检测方法", "壳程", "管程"],
            sub_headers=["", "", "技术等级", "检测比例%", "合格级别", "技术等级", "检测比例%", "合格级别"],
            span_map=[(0, 1), (1, 1), (2, 3), (5, 3)]
        )
        self.render_grouped_table(
            self.tableWidget_trail_data,
            data["检测数据"]["格式化"],
            [
                "接头种类", "检测方法",
                "壳程_技术等级", "壳程_检测比例", "壳程_合格级别",
                "管程_技术等级", "管程_检测比例", "管程_合格级别"
            ],
            group_key_column=0
        )
        # 导入涂漆数据，执行标准/规范从产品标准中取值
        # 在导入涂漆数据之前加入以下代码
        product_std_rows = data["产品标准"]["rows"]
        coating_std_value = ""
        for row in product_std_rows:
            if row.get("规范/标准名称", "").strip() == "涂漆标准":
                coating_std_value = row.get("规范/标准代号", "").strip()
                break
        render_coating_table(self.tableWidget_coating_data, data["涂漆数据"]["格式化"], coating_std_value)
        if hasattr(self, 'undo_stack'):
            self.undo_stack.clear()
        # 专门用于触发“绝热层类型”的联动
        trigger_all_cross_table_relations(self)

    def fill_table_widget(self, table_widget, headers, rows, index_header=None):
        """
        填充 QTableWidget 的通用方法
        """
        # === 新增：仅在设计数据表中过滤掉 [工况] 参数 ===
        if table_widget.objectName() == "tableWidget_design_data":
            before = len(rows)
            rows = [row for row in rows if "[工况" not in str(row.get("参数名称", ""))]
            after = len(rows)
            print(f"[过滤] 设计数据表: 原始 {before} 行, 过滤后 {after} 行")

        # === 下面保持你原来的逻辑不变 ===
        clean_headers = headers.copy()
        if index_header in clean_headers:
            clean_headers.remove(index_header)

        extra_col = 1 if index_header else 0
        table_widget.clear()
        table_widget.setColumnCount(len(clean_headers) + extra_col)
        table_widget.setRowCount(len(rows))

        header_labels = [index_header] + clean_headers if index_header else clean_headers

        for col_index, header_text in enumerate(header_labels):
            display_text = "序号" if index_header and col_index == 0 else header_text
            item = QTableWidgetItem(display_text)
            item.setData(Qt.UserRole, header_text)  # ✅ 存储真实字段名
            item.setTextAlignment(Qt.AlignCenter)
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            table_widget.setHorizontalHeaderItem(col_index, item)

        table_widget.verticalHeader().setVisible(False)

        for row_idx, row in enumerate(rows):
            if index_header:
                index_value = row.get(index_header, "")
                index_item = QTableWidgetItem(str(index_value))
                index_item.setTextAlignment(Qt.AlignCenter)
                index_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                table_widget.setItem(row_idx, 0, index_item)

            for col_idx, key in enumerate(clean_headers):
                value = str(row.get(key, ""))
                item = QTableWidgetItem(value)

                is_name_column = col_idx == 0
                is_code_column = key == "规范/标准代号"
                is_unit_column = key == "参数单位"  # 修改
                if is_name_column:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                elif is_unit_column:  # 修改
                    item.setTextAlignment(Qt.AlignCenter)  # ✅ 居中
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)  # ✅ 不可编辑
                else:
                    if is_code_column:
                        item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    else:
                        item.setTextAlignment(Qt.AlignCenter)
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)

                table_widget.setItem(row_idx, col_idx + extra_col, item)

        # ✅ 仅对涂漆表设置 logical_headers，避免误操作其他表
        if table_widget.objectName() == "tableWidget_coating_data":
            table_widget.logical_headers = [
                "执行标准/规范", "用途", "油漆类别", "颜色", "干膜厚度（μm）", "涂漆面积", "备注"
            ]

        table_widget.resizeColumnsToContents()

    def on_input_ref_data_clicked(self):
        if not getattr(self, "_is_valid_product", True):
            self.line_tip.setText("当前未选择产品，无法导入参考数据")
            self.line_tip.setStyleSheet("color: black;")
            return
        try:
            # 弹出文件选择框
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "选择条件输入数据表",
                "",
                "Excel 文件 (*.xlsx);;所有文件 (*)"
            )
            if not file_path:
                return  # 用户取消选择，直接返回

            # 执行导入操作
            import_all_reference_data(file_path, self)
            QMessageBox.information(self, "成功", "成功导入参考数据！")

        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))

    def render_grouped_table(self, table_widget, grouped_data, headers, group_key_column=0):
        render_grouped_table(table_widget, grouped_data, headers, group_key_column)

    # 保存及检查必填项
    def check_and_save_data(self, force=False):
        """
        保存及检查必填项
        :param force: 是否强制保存（确认按钮时 True，切换/关闭时 False）
        """
        if not getattr(self, "_is_valid_product", True):
            return True  # 空界面不用保存

        # 如果不是强制保存，并且没有修改过数据，就直接跳过
        if not force and not getattr(self, "_is_modified", False):
            return True

        try:
            has_missing_dsg, missing_dsg = validate_required_fields(
                self.tableWidget_design_data, mode="设计数据"
            )
            has_missing_common, missing_common = validate_required_fields(
                self.tableWidget_general_data, mode="通用数据"
            )
            if has_missing_dsg or has_missing_common:
                missing_fields = [name for _, name in (missing_dsg + missing_common)]
                msg = (
                    "以下必填项：\n"
                    + "、".join(missing_fields)
                    + "\n对应参数值不能为空。\n是否继续保存？"
                )

                # 自定义“是 / 否”按钮
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Question)
                box.setWindowTitle("提示")
                box.setText(msg)
                yes_btn = box.addButton("是", QMessageBox.YesRole)
                no_btn = box.addButton("否", QMessageBox.NoRole)
                box.setDefaultButton(no_btn)
                box.exec_()

                # 始终高亮未填项
                highlight_missing_required_rows(self.tableWidget_design_data, missing_dsg)
                highlight_missing_required_rows(self.tableWidget_general_data, missing_common)

                if box.clickedButton() == no_btn:
                    return False
                # 如果点“是”，继续保存
            if not save_local_condition_file(self.product_id, self):
                return False
            save_all_tables(self, self.product_id)
            self.line_tip.setText("保存成功！")
            self.line_tip.setToolTip("保存成功！")
            self.line_tip.setStyleSheet("color: black;")
            # 保存完成后清除修改标志
            self._is_modified = False
            return True

        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存数据出错：\n{str(e)}")
            return False

    def export_condition_file(self):
        """
        导出条件输入数据表：先保存至本地文件，然后复制至用户选择的位置。
        """
        from PyQt5.QtWidgets import QFileDialog
        import shutil

        if not getattr(self, "_is_valid_product", True):
            if self.line_tip:
                self.line_tip.setText("❌ 当前未选择有效产品，无法导出。")
            return

        try:
            # 第一步：保存到本地文件
            success = save_local_condition_file(self.product_id, self)
            if not success:
                return

            # 获取本地文件路径
            local_path = get_ref_data_excel_path(self.product_id)

            # 第二步：让用户选择导出路径
            dest_path, _ = QFileDialog.getSaveFileName(
                self,
                "保存条件输入数据表",
                "条件输入数据表.xlsx",
                "Excel 文件 (*.xlsx);;所有文件 (*)"
            )
            if not dest_path:
                if self.line_tip:
                    self.line_tip.setText("导出已取消")
                return

            # 第三步：复制文件到目标位置
            shutil.copyfile(local_path, dest_path)

            message = f"已成功导出文件至: {dest_path}"
            if self.line_tip:
                self.line_tip.setText(message)
                self.line_tip.setToolTip(message)

        except Exception as e:
            err_msg = f"导出文件时出错: {str(e)}"
            if self.line_tip:
                self.line_tip.setText(err_msg[:80])
                self.line_tip.setToolTip(err_msg)
            else:
                QMessageBox.critical(self, "导出失败", err_msg)

    #新增 模式切换处理函数
    def on_mode_changed(self, mode_name: str):
        """
        仅改变界面显示顺序；数据库与本地Excel保存仍使用默认顺序。
        """
        if not mode_name:
            return
        # 默认模式 = 恢复默认顺序（即初始载入时顺序）
        if mode_name == self._default_mode_name or mode_name.strip() == "":
            # 用“默认ID顺序”再排一次（就是 capture_default_order 记录那次的出现次序）
            #ids_std = getattr(self.tableWidget_product_std, "_default_param_ids", None)
            ids_design = getattr(self.tableWidget_design_data, "_default_param_ids", None)
            #ids_general = getattr(self.tableWidget_general_data, "_default_param_ids", None)
            #if ids_std:
                #apply_mode_param_order(self.tableWidget_product_std, [i for i in ids_std if i is not None])
            if ids_design:
                apply_mode_param_order(self.tableWidget_design_data, [i for i in ids_design if i is not None])
            #if ids_general:
                #apply_mode_param_order(self.tableWidget_general_data, [i for i in ids_general if i is not None])
            return

        # 其他模式：查表里的“参数顺序”并应用
        target_ids = self._mode_orders.get(mode_name)
        if not target_ids:
            return

        # 仅重排三张含“参数ID”的表
        #apply_mode_param_order(self.tableWidget_product_std, target_ids)
        apply_mode_param_order(self.tableWidget_design_data, target_ids)
        #apply_mode_param_order(self.tableWidget_general_data, target_ids)

    def eventFilter(self, obj, event):
        """
        拦截“设计数据”表的单击：
        - 命中“参数名称”列 且 参数名为“设计压力*”或“设计压力”时，弹出多工况窗口
        - 单击即可触发（若想双击触发，把 MouseButtonRelease 改成 MouseButtonDblClick）
        """
        try:
            if obj is self.tableWidget_design_data.viewport() and event.type() == QEvent.MouseButtonRelease:
                pos = event.pos()
                index = self.tableWidget_design_data.indexAt(pos)
                if not index.isValid():
                    return super().eventFilter(obj, event)

                row, col = index.row(), index.column()

                # 参数名称列索引是 1（0=序号, 1=参数名称）
                if col != 1:
                    return super().eventFilter(obj, event)

                # 获取参数名称
                name_item = self.tableWidget_design_data.item(row, col)
                param_name = name_item.text().strip() if name_item else ""

            return super().eventFilter(obj, event)
        except Exception as e:
            print(f"[多工况] eventFilter 异常：{e}")
            return super().eventFilter(obj, event)

    def _open_multi_conditions_dialog(self, row: int, col: int, side: str):
        """
        打开“多工况”窗口（6行参数+壳程/管程两列），切换工况可编辑不同工况数据，
        确认时直接保存到数据库。
        """
        dlg = MultiConditionsDialog(self, product_id=self.product_id)
        dlg.exec_()

    def _set_modified(self, modified=True):
        """标记数据是否已修改"""
        self._is_modified = modified
