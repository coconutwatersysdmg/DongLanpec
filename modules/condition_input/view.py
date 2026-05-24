import sys

from PyQt5 import uic
from PyQt5.QtGui import QPixmap, QPainter, QFont
from PyQt5.QtWidgets import QWidget, QMessageBox, QFileDialog, QApplication, QToolTip
from PyQt5.QtCore import QTimer, Qt
import os

from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QTableWidgetItem
from modules.condition_input.funcs.multi_conditions_dialog import MultiConditionsDialog
from PyQt5.QtWidgets import QMessageBox, QPushButton

# 导入功能函数
from modules.condition_input.funcs.funcs_product_info import check_pdt_define, check_has_any_product
from modules.condition_input.funcs.ctrl_helper import enable_full_undo
from modules.condition_input.funcs.funcs_cdt_input import load_design_data_if_exists, render_grouped_table, \
    render_coating_table, set_multilevel_headers, apply_table_style, highlight_missing_required_rows, \
    validate_required_fields, import_all_reference_data, save_local_condition_file, save_all_tables, \
    trigger_all_cross_table_relations, apply_design_data_dropdowns, apply_general_data_dropdowns, \
    apply_trail_data_dropdowns, TrailTableComboDelegate, highlight_entire_row, shrink_index_column, shrink_unit_column, \
    get_ref_data_excel_path, fetch_all_mode_orders, capture_default_order, apply_mode_param_order, \
    restore_default_order, autofill_outer_diameter
from modules.chanpinguanli.chanpinguanli_main import product_manager
from modules.condition_input.funcs.design_data_delegate import DesignDataDelegate  # 根据实际路径调整
# from modules.yudingyi.luoshuan import update_user_config_for_2_6_1
from modules.chanpinguanli.project_confirm_btn import show_confirm_dialog

product_id = None


def on_product_id_changed(new_id):
    print(f"Received new PRODUCT_ID: {new_id}")
    global product_id
    product_id = new_id


# 测试用产品 ID（真实情况中由外部输入）
product_manager.product_id_changed.connect(on_product_id_changed)


# 0903会议纪要 添加一个通用的检查函数，用于所有非项目管理界面
def check_project_and_product():
    """检查项目和产品状态的通用函数（修复变量引用问题）"""
    # 关键修改：直接通过bianl模块访问current_project_id
    from modules.chanpinguanli import bianl
    # 打印调试信息，确认获取的项目ID
    print(f"检查函数中获取的项目ID: {repr(bianl.current_project_id)}")
    # 检查项目ID是否有效
    if not bianl.current_project_id or str(bianl.current_project_id).strip() == "":
        return False, "请先创建项目和产品！"
    # 检查当前项目下是否有产品
    if not check_has_any_product(bianl.current_project_id):
        return False, "请先创建至少一个产品！"
    return True, ""


class DesignConditionInputViewer(QWidget):
    def __init__(self, line_tip=None):
        super().__init__()

        # ▼▼▼【核心修改 1】在最开始初始化状态变量 ▼▼▼
        self._is_modified = False  # 关键！追踪界面数据是否被修改
        self._local_condition_xlsx_missing = False  # 本地条件输入 xlsx 缺失（保存失败）时置 True
        self._is_loading_data = True  # 关键！开始初始化，标记为"正在加载"
        self.original_window_title = ""  # UI加载后赋值
        self._is_saved_to_design_db = False  # 记录产品是否已保存到产品设计活动库#1106新修改
        self._has_confirmed_saved = False  # 记录是否点击过确认按钮保存#1106新修改
        self._initial_table_snapshots = {}  # 1112新修改-条件输入表格实质性变化：存储初始状态快照，用于实质性变化检测
        self._pending_outer_series_sync = False  # 外径系列被user_config覆盖时置True，关闭时需保存到DB

        # 0903会议纪要 首先进行项目和产品检查
        print("准备检查项目和产品状态...")
        can_open, msg = check_project_and_product()
        if not can_open:
            QMessageBox.information(self, "提示", msg)
            self.deleteLater()  # 不打开界面
            return  # 立即返回

        current_dir = os.path.dirname(os.path.abspath(__file__))
        ui_path = os.path.join(current_dir, "viewer_new.ui")
        uic.loadUi(ui_path, self)
        # ▼▼▼【修改点 1.2】UI加载后获取标题 ▼▼▼
        self.original_window_title = self.windowTitle()

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

        # 1014lxy
        # ========== 新增：初始化提示定时器 ==========
        self.tip_timer = QTimer(self)  # 创建定时器实例
        self.tip_timer.setSingleShot(True)  # 仅触发一次（避免重复清空）
        self.tip_timer.timeout.connect(self.clear_line_tip)  # 超时后调用清空方法
        # self.product_id = product_id
        self._is_valid_product = True
        self._early_tip_msg = ""

        # self._is_modified = False
        self._validation_triggered = False  # <---lxy101 新增：验证触发标志，默认为 False

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
            # 禁用鼠标滚轮切换模式，避免误操作
            try:
                combo.installEventFilter(self)
            except Exception as _:
                pass

            # 确保 on_mode_changed 已定义
            if hasattr(self, "on_mode_changed") and callable(self.on_mode_changed):
                combo.currentTextChanged.connect(self.on_mode_changed)
                combo.currentTextChanged.connect(lambda: setattr(self, "_is_modified", True))
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

        # ===lxy101 核心修改点 1: 连接信号与槽函数 ===

        # 1112新修改-条件输入表格实质性变化：移除撤销/重做和模式切换的实时修改标记（改为按需检测）
        # 保留撤销/重做功能本身，但不再实时标记为修改状态

        # 只对“设计数据”表开启单击打开多工况窗口
        self.tableWidget_design_data.viewport().installEventFilter(self)
        self._is_loading_data = False
        # 应用自定义代理显示多工况标识
        if hasattr(self, 'tableWidget_design_data') and self.tableWidget_design_data is not None:
            self.design_delegate = DesignDataDelegate()
            self.tableWidget_design_data.setItemDelegateForColumn(1, self.design_delegate)
            self.tableWidget_design_data.viewer = self
        # 所有数据加载和UI设置完成后，更新状态标志
        self._is_loading_data = False
        tables = [
            self.tableWidget_design_data,
            self.tableWidget_general_data,
            self.tableWidget_product_std,
            self.tableWidget_trail_data,
            self.tableWidget_coating_data
        ]

        # 1112新修改-条件输入表格实质性变化：保留实时校验功能，但移除实时修改标记
        for table in tables:
            # 1015 为需要实时校验的表格，连接到 handle_cell_input（保留高亮功能）
            if table in [self.tableWidget_design_data, self.tableWidget_general_data]:
                table.itemChanged.connect(self.handle_cell_input)

        # 1206新修改-外径、外径系列、是否已外径为基准、公称直径联动
        # === 新增：通用数据表 外径联动 ===
        if hasattr(self, 'tableWidget_general_data') and self.tableWidget_general_data is not None:
            try:
                self.tableWidget_general_data.itemChanged.connect(self.on_general_table_item_changed)
            except Exception:
                pass
            # 初始化一次联动状态（仅作为UI展示基准，之后会在import_condition_data末尾统一保存快照）
            try:
                self.update_general_diameter_linkage()
            except Exception:
                pass
        # 标记外径自动填充就绪（避免在界面载入前触发弹窗）
        try:
            setattr(self, "_outer_autofill_ready", True)
        except Exception:
            pass
        # 初始化缓存，避免“仅点击单元格”引发重复联动
        try:
            self._outer_base_last_val = None  # 是否以外径为基准* 的上次值
        except Exception:
            pass
        # 将缓存初始化为当前"是否以外径为基准*"的值，防止首次仅点击即触发
        try:
            table = getattr(self, 'tableWidget_general_data', None)
            if table is not None:
                row = self._find_row_by_param_name(table, "是否以外径为基准*")
                if row >= 0:
                    it = table.item(row, 3)
                    cur = it.text().strip() if it and it.text() else ""
                    self._outer_base_last_val = cur
        except Exception:
            pass

        # 0209新修改-多工况输入标识显示
        # ✅ 新增：多工况数据缓存初始化
        self._has_multi_conditions = False  # 缓存：是否有工况2/3的非空数据
        if self._is_valid_product and self.product_id:
            try:
                self._check_multi_conditions()
            except Exception as e:
                print(f"[多工况] 初始化检查失败: {e}")

    # 1014lxy
    def mark_as_modified(self, item=None):  # item参数设为可选
        """当任何数据被用户改变时，将界面标记为已修改"""
        # 正在加载数据时，任何信号都忽略
        if self._is_loading_data:
            return

        # 如果已经标记过了，就不用重复操作了
        if self._is_modified:
            return

        self._is_modified = True
        # 在窗口标题上加一个星号，给用户直观提示
        self.setWindowTitle(f"{self.original_window_title}*")
        print("条件输入界面已被修改，标记完成。")

    # 1106新修改
    # 修改后 (弹窗提示)
    def can_be_closed(self):
        """
        供主窗口调用的关闭检查接口。
        根据两种情况决定是否需要检查必填项：
        情况A：新产品（未保存到设计活动库） -> 如果已确认保存且无新修改，不需要检查；否则需要检查
        情况B：老产品（已保存到设计活动库） -> 只有在有实质性修改时才需要检查
        返回: bool -> 是否可以安全关闭
        """
        # 判断是否需要检查必填项
        need_check = self._should_check_required_fields()

        if not need_check:
            # 不需要检查，直接允许关闭
            return True

        # 需要检查必填项
        is_valid, missing_fields = self.only_check_validate_data()

        if is_valid:
            # 必填项完整，允许关闭
            return True

        # 必填项不完整，弹窗提示
        msg = ("以下必填项：\n" + "、".join(missing_fields) + "\n对应参数值不能为空。\n是否确认继续关闭？")
        reply = show_confirm_dialog(self, "提示", msg)

        if reply:
            # 用户选择继续关闭
            return True
        else:
            # 用户选择取消关闭
            return False

    # 1112新修改-条件输入3情况优化-2情况
    def _should_check_required_fields(self):
        """
            #     判断是否需要检查必填项
            #     返回: bool -> True表示需要检查，False表示不需要检查
            #     两种情况：
            #     情况1：新产品，第一次打开，没有保存到产品设计活动库 -> 即使没有修改也需要检查
            #     情况2：产品，已保存到产品设计活动库 -> 如果没有修改或已确认保存且无新修改，不需要检查；否则需要检查
        """
        # 1112新修改-条件输入表格实质性变化：检查是否有实质性变化
        has_changes = self._has_substantial_changes()

        if not self._is_saved_to_design_db:
            # 情况A：新产品（未保存到设计活动库）
            # 如果已确认保存且没有新修改，不需要检查；否则需要检查
            return not (self._has_confirmed_saved and not has_changes)
        else:
            # 情况B：老产品（已保存到设计活动库）
            # 只有在有实质性修改时才需要检查
            return has_changes

    # 1106新修改
    # def _should_check_required_fields(self):
    #     """
    #     判断是否需要检查必填项
    #     返回: bool -> True表示需要检查，False表示不需要检查
    #
    #     三种情况：
    #     情况1：新产品，第一次打开，没有保存到产品设计活动库 -> 即使没有修改也需要检查
    #     情况2：新产品，第一次打开，进行了修改 -> 如果已确认保存且无新修改，不需要检查；否则需要检查
    #     情况3：老产品，已保存到产品设计活动库 -> 如果没有修改或已确认保存且无新修改，不需要检查；否则需要检查
    #     """
    #     # 1112新修改-条件输入表格实质性变化：检查是否有实质性变化
    #     has_changes = self._has_substantial_changes()
    #
    #     # 情况1和情况2：新产品，第一次打开，没有保存到产品设计活动库
    #     if not self._is_saved_to_design_db:
    #         # 如果已确认保存且没有新修改，不需要检查（情况2的特殊情况）
    #         if self._has_confirmed_saved and not has_changes:
    #             return False
    #         # 否则需要检查（情况1：没有修改也需要检查；情况2：有修改或未保存需要检查）
    #         return True
    #
    #     # 情况3：老产品，已保存到产品设计活动库
    #     # 如果没有任何实质性修改，不需要检查
    #     if not has_changes:
    #         return False
    #
    #     # 如果有实质性修改，需要检查
    #     return True
    # def can_be_closed(self): 无弹窗提示直接关闭版
    #     """
    #     供主窗口调用的关闭检查接口。
    #     - 如果没有修改，直接返回 True。
    #     - 如果有修改，自动执行静默保存 (不弹窗询问必填项)。
    #     - 保存成功，返回 True。
    #     - 保存失败，弹窗提示并返回 False。
    #     返回: bool -> 是否可以安全关闭
    #     """
    #     # 如果没有被修改过，直接告诉主窗口“可以关闭”
    #     if not self._is_modified:
    #         print("条件输入界面无修改，可直接关闭。")
    #         return True
    #
    #     print("检测到未保存的修改，正在自动静默保存...")
    #
    #     try:
    #         # 执行核心保存操作，不进行UI交互（如弹窗询问）
    #         if not save_local_condition_file(self.product_id, self):
    #             raise IOError("保存本地条件文件失败。")
    #         save_all_tables(self, self.product_id)
    #
    #         # 保存成功后，重置状态
    #         self._is_modified = False
    #         self.setWindowTitle(self.original_window_title)
    #
    #         print("自动保存成功！可以关闭。")
    #         if hasattr(self, 'line_tip') and self.line_tip:
    #             self.line_tip.setText("关闭前自动保存成功！")
    #             if hasattr(self, 'tip_timer'):
    #                 self.tip_timer.start(5000)
    #
    #         return True  # 返回成功，主窗口可以继续关闭操作
    #
    #     except Exception as e:
    #         print(f"自动保存失败，无法关闭: {e}")
    #         QMessageBox.critical(self, "保存失败", f"自动保存数据时发生错误，关闭操作已取消。\n\n错误信息: {e}")
    #         return False  # 返回失败，主窗口将中断关闭操作
    # lxy1014
    def clear_line_tip(self):
        """5秒后自动清空line_tip的文本和样式（避免残留）"""
        # 先判断line_tip是否存在，防止空指针错误
        if hasattr(self, "line_tip") and self.line_tip:
            self.line_tip.setText("")  # 清空提示文本
            self.line_tip.setStyleSheet("")  # 恢复默认样式（若之前设置过颜色）
            self.line_tip.setToolTip("")  # 清空 tooltip（可选）

    def import_condition_data(self, product_id):
        if not product_id:
            return

        # 调用函数获取产品形式，如果找不到或出错，则默认为 'all'
        from main import get_product_form_from_db
        product_form = get_product_form_from_db(product_id) or "all"
        print(f"当前产品ID: {product_id}, 获取到的产品型式: {product_form}")

        result = load_design_data_if_exists(product_id, product_form)

        if not result or not result.get("import_status"):
            QMessageBox.information(self, "提示", "未找到设计数据，表格将保持为空。")
            # 如果没有导入数据，默认为新产品（未保存到设计活动库）#1106新修改
            self._is_saved_to_design_db = False
            self.design_data_source = "条件模板"
            return

        self.design_data_source = result["data_source_status"]
        print(f"数据来源：{self.design_data_source}")
        # 记录产品是否已保存到产品设计活动库 #1106新修改
        self._is_saved_to_design_db = (self.design_data_source == "设计活动库")
        print(f"产品是否已保存到设计活动库：{self._is_saved_to_design_db}")

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
        # capture_default_order(self.tableWidget_product_std)
        capture_default_order(self.tableWidget_design_data)
        # capture_default_order(self.tableWidget_general_data)

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
        # 新增：数据导入后清除高亮lxy101
        self.clear_all_highlights()
        # 0209新修改-多工况输入标识显示
        # ✅ 数据加载完成后，检查多工况数据状态并刷新显示
        try:
            self.update_multi_conditions_status()
        except Exception as e:
            print(f"[多工况] 数据加载后检查失败: {e}")
        # === 数据加载完成后：触发外径自动填充，确保公式计算的外径值正确显示 ===
        try:
            # 标记外径自动填充就绪，确保可以触发计算
            setattr(self, "_outer_autofill_ready", True)

            # 触发一次外径自动填充，确保公式计算的外径值正确显示
            from modules.condition_input.funcs.funcs_cdt_input import autofill_outer_diameter
            autofill_outer_diameter(self)
            print(f"[外径加载] 数据加载完成后触发外径自动填充")
        except Exception as e:
            print(f"[数据加载后处理外径显示] 失败: {e}")
        # 1112新修改-条件输入表格实质性变化：
        # 将“导入 + 初始联动修正（包括外径显示为'—'）”之后的界面状态
        # 作为快照基准，避免仅打开界面就被视为实质性修改。
        self._save_initial_snapshots()

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

            # ✅ 新增：重新分配连续的序号
            if index_header and rows:
                for idx, row in enumerate(rows):
                    row[index_header] = idx + 1  # 重新分配从1开始的连续序号
                print(f"[序号重分配] 设计数据表: 已重新分配 {len(rows)} 个连续序号")

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
                # 0522新修改-ui修改
                if key == "参数名称":
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                elif is_name_column:
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

        # 1111新修改-2金属温度单元格不可编辑-仅对设计数据表应用特殊只读逻辑
        if table_widget.objectName() == "tableWidget_design_data":
            self._apply_special_readonly_for_nen_bem()

    # 1111新修改-2金属温度单元格不可编辑
    def _apply_special_readonly_for_nen_bem(self):
        """
        针对NEN和AEM、BEM产品，将设计数据表中的特定单元格设为只读：
        - "沿长度平均的换热管金属温度*" 的壳程数值列（第3列）
        - "沿长度平均的壳程圆筒金属温度*" 的管程数值列（第4列）

        此函数在表格填充后和模式切换后都需要调用。
        """
        if not hasattr(self, 'tableWidget_design_data') or self.tableWidget_design_data is None:
            return

        # 获取产品类型（只查询一次）
        from main import get_product_form_from_db
        product_form = get_product_form_from_db(self.product_id)

        # 只对NEN\AEM和BEM产品应用
        if product_form not in ['NEN', 'AEM', 'BEM', 'NEN(Head)']:
            return

        print(f"[DEBUG] 正在为NEN/NEN(Head)/AEM/BEM产品设置特殊只读单元格")

        # 遍历设计数据表的所有行
        for row in range(self.tableWidget_design_data.rowCount()):
            # 获取参数名称（第1列，第0列是序号）
            param_item = self.tableWidget_design_data.item(row, 1)
            if not param_item:
                continue
            param_name = param_item.text().strip()

            # "沿长度平均的换热管金属温度*" 的壳程数值列（第3列）设为只读
            if param_name == "沿长度平均的换热管金属温度*":
                shell_item = self.tableWidget_design_data.item(row, 3)
                if shell_item:
                    shell_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                    print(f"[DEBUG] 已设置'{param_name}'的壳程数值为只读")

            # "沿长度平均的壳程圆筒金属温度*" 的管程数值列（第4列）设为只读
            elif param_name == "沿长度平均的壳程圆筒金属温度*":
                tube_item = self.tableWidget_design_data.item(row, 4)
                if tube_item:
                    tube_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                    print(f"[DEBUG] 已设置'{param_name}'的管程数值为只读")

    # 1206新修改-外径、外径系列、是否已外径为基准、公称直径联动
    # === 新增：通用数据表 外径显示/编辑联动 ===
    def _find_row_by_param_name(self, table, target_name: str):
        """在给定表格中查找参数名称列（索引1）等于 target_name 的行索引；找不到返回 -1。"""
        if table is None:
            return -1
        try:
            rows = table.rowCount()
            for r in range(rows):
                item = table.item(r, 1)
                if item and item.text().strip() == target_name:
                    return r
        except Exception:
            pass
        return -1

    # 1206新修改-外径、外径系列、是否已外径为基准、公称直径联动
    def _set_row_editable(self, table, row: int, editable: bool):
        """切换整行可编辑性；缓存原始 flags 于 UserRole+10，恢复时按缓存。"""
        if table is None or row < 0:
            return
        try:
            cols = table.columnCount()
            for c in range(cols):
                it = table.item(row, c)
                if not it:
                    continue
                # 缓存原 flags
                key_role = Qt.UserRole + 10
                if it.data(key_role) is None:
                    try:
                        it.setData(key_role, int(it.flags()))
                    except Exception:
                        pass
                orig_flags = it.data(key_role)
                if orig_flags is None:
                    orig_flags = int(it.flags())
                if editable:
                    # 恢复为原始flags
                    it.setFlags(Qt.ItemFlags(int(orig_flags)))
                else:
                    # 去掉可编辑标志，但保留可选择/可用
                    it.setFlags((Qt.ItemFlags(int(orig_flags)) & ~Qt.ItemIsEditable))
        except Exception:
            pass

    # 1206新修改-外径、外径系列、是否已外径为基准、公称直径联动
    def update_general_diameter_linkage(self):
        """
        当“是否以外径为基准*”为“否”时，禁用并写入“/”；为“是”时，允许编辑并按需要触发外径自动计算。
        仅影响UI展示与编辑性，不直接改动数据库。
        """
        table = getattr(self, 'tableWidget_general_data', None)
        if table is None:
            return
        # 定位三行
        base_row = self._find_row_by_param_name(table, "是否以外径为基准*")
        row_series = self._find_row_by_param_name(table, "外径系列")
        row_diameter = self._find_row_by_param_name(table, "外径")
        if base_row < 0:
            return
        # 读取数值列（索引3）
        val_item = table.item(base_row, 3)
        val = val_item.text().strip() if val_item and val_item.text() else ""
        need_hide = (val == "否")

        # 更新封头类型代号联动（仅在非初始化加载时执行）
        try:
            is_loading = getattr(self, "_is_loading_data", False)
            if not is_loading:
                self._update_head_type_code_by_outer_base(val)
                # 0515元件定义新增
                # 「否」时 HG 法兰类型不在可选范围内：同步库内法兰类型/密封面/密封面高度，并刷新已打开的元件定义界面
                if val == "否":
                    pid = getattr(self, "product_id", None)
                    if pid:
                        try:
                            from modules.cailiaodingyi.funcs.funcs_pdf_change import (
                                sync_flange_params_when_outer_base_inner,
                            )
                            sync_flange_params_when_outer_base_inner(pid)
                        except Exception as _e_fl:
                            print(f"[基准切否-法兰同步库] 失败: {_e_fl}")
                        try:
                            from modules.cailiaodingyi.controllers.datamanager import (
                                refresh_open_paradefine_after_outer_base_inner,
                            )
                            refresh_open_paradefine_after_outer_base_inner(pid)
                        except Exception as _e_ui:
                            print(f"[基准切否-刷新元件定义界面] 失败: {_e_ui}")
        except Exception as e:
            print(f"[封头类型代号联动更新] 失败: {e}")

        # 处理"外径系列"
        if row_series >= 0:
            try:
                v_item = table.item(row_series, 3)
                if v_item is None:
                    v_item = QTableWidgetItem()
                    table.setItem(row_series, 3, v_item)
            except Exception:
                v_item = None

            if need_hide:
                # “否”：外径系列显示为“/”，整行只读
                # 对已经保存过的产品，先备份当前外径系列值，供之后切回“是”时恢复
                try:
                    is_saved_product = getattr(self, "_is_saved_to_design_db", False)
                    if is_saved_product:
                        try:
                            prev_text = v_item.text().strip() if (v_item and v_item.text()) else ""
                        except Exception:
                            prev_text = ""
                        if prev_text not in ("", "/"):
                            # 仅在有有效值时才备份
                            self._outer_series_backup = prev_text
                except Exception:
                    pass
                try:
                    bs = table.blockSignals(True)
                    try:
                        if v_item is None:
                            v_item = QTableWidgetItem()
                            table.setItem(row_series, 3, v_item)
                        v_item.setText("/")
                    finally:
                        table.blockSignals(bs)
                except Exception:
                    pass
                self._set_row_editable(table, row_series, False)
            else:
                # “是”：外径系列允许编辑；
                #   - 若有备份值，则优先恢复备份；
                #   - 否则在当前值为空或“/”时，根据配置库给出默认系列。
                self._set_row_editable(table, row_series, True)
                current_text = ""
                try:
                    current_text = v_item.text().strip() if (v_item and v_item.text()) else ""
                except Exception:
                    current_text = ""

                # 将 "" 和 "/" 都视为“空值”（尚未真正选择过外径系列）
                is_effectively_empty = (current_text == "" or current_text == "/")

                if is_effectively_empty:
                    # ① 已有备份时，优先恢复备份（适用于：曾经为“是”且保存过，再改为“否”后又改回“是”的老产品）
                    try:
                        backup_series = getattr(self, "_outer_series_backup", None)
                    except Exception:
                        backup_series = None

                    target_series = None
                    if backup_series:
                        target_series = backup_series
                    else:
                        # ② 没有备份：包含两种情况
                        #    - 新产品第一次切换为“是”
                        #    - 老产品之前一直是“否”，没有有效外径系列
                        #    都按当前配置库中的外径系列给一个默认值
                        try:
                            from modules.condition_input.funcs.funcs_cdt_input import _determine_diameter_series
                            target_series = _determine_diameter_series()
                        except Exception as e:
                            print(f"[设置外径系列默认值失败] {e}")
                            target_series = None

                    if target_series:
                        try:
                            bs = table.blockSignals(True)
                            try:
                                if v_item is None:
                                    v_item = QTableWidgetItem()
                                    table.setItem(row_series, 3, v_item)
                                v_item.setText(target_series)
                            finally:
                                table.blockSignals(bs)
                        except Exception:
                            pass
        # 处理“外径”：不再隐藏，按状态切换可编辑性，‘否’时写入“/”
        if row_diameter >= 0:
            self._set_row_editable(table, row_diameter, not need_hide)
            if need_hide:
                try:
                    v_item = table.item(row_diameter, 3)
                    if v_item is None:
                        v_item = QTableWidgetItem()
                        table.setItem(row_diameter, 3, v_item)
                    bs = table.blockSignals(True)
                    try:
                        v_item.setText("/")
                    finally:
                        table.blockSignals(bs)
                except Exception:
                    pass
        # 当切回"是"时，如非初始化阶段，可触发一次自动计算外径（使用当前界面的外径系列）
        if not need_hide and row_series >= 0:
            try:
                is_loading = getattr(self, "_is_loading_data", False)
            except Exception:
                is_loading = False
            if not is_loading:
                # 重置缓存，确保不会因为 (dn, series) 相同而跳过本次计算
                try:
                    setattr(self, "_outer_last_pair", None)
                except Exception:
                    pass
                try:
                    from modules.condition_input.funcs.funcs_cdt_input import autofill_outer_diameter
                    autofill_outer_diameter(self)
                except Exception as e:
                    print(f"[update_general_diameter_linkage] 自动填充外径失败: {e}")

    # 1206新修改-外径、外径系列、是否已外径为基准、公称直径联动
    def on_general_table_item_changed(self, item):
        """监听通用数据表变更，仅当“是否以外径为基准*”的数值列变化时触发联动。"""
        try:
            if self._is_loading_data:
                return
        except Exception:
            pass
        table = getattr(self, 'tableWidget_general_data', None)
        if table is None or item is None:
            return
        try:
            # 仅关注基准开关行的“数值列”(索引3)
            if item.column() != 3:
                return
            param_item = table.item(item.row(), 1)
            if param_item and param_item.text().strip() == "是否以外径为基准*":
                # 读取当前值，与上次缓存比较，避免“仅点击/重复提交相同值”造成的误触发
                cur_val = item.text().strip() if item and item.text() else ""
                last_val = getattr(self, "_outer_base_last_val", None)
                if last_val == cur_val:
                    return
                try:
                    self._outer_base_last_val = cur_val
                except Exception:
                    pass
                self.update_general_diameter_linkage()
        except Exception:
            pass

    def _update_head_type_code_by_outer_base(self, new_outer_base_value):
        """
        当"是否以外径为基准*"的值改变时，更新所有元件的"封头类型代号"
        映射规则：
        - EHA -> EHB (当从"否"变成"是")
        - EHB -> EHA (当从"是"变成"否")
        - THA -> THB (当从"否"变成"是")
        - THB -> THA (当从"是"变成"否")
        - 球（缺）形封头Ⅰ/Ⅱ/Ⅲ 不变
        """
        try:
            product_id = getattr(self, 'product_id', None)
            if not product_id:
                return

            from modules.cailiaodingyi.db_cnt import get_connection
            from modules.cailiaodingyi.funcs.funcs_pdf_change import db_config_1, update_element_para_data

            # 定义映射关系
            mapping = {
                "是": {
                    "EHA（椭圆形封头）": "EHB（椭圆形封头）",
                    "THA碟形封头": "THB碟形封头",
                },
                "否": {
                    "EHB（椭圆形封头）": "EHA（椭圆形封头）",
                    "THB碟形封头": "THA碟形封头",
                }
            }

            # 不需要变化的封头类型（在两个选项中都存在）
            unchanged_types = ["球（缺）形封头Ⅰ", "球（缺）形封头Ⅱ", "球（缺）形封头Ⅲ"]

            # 查询所有有"封头类型代号"参数的元件
            conn = get_connection(**db_config_1)
            try:
                with conn.cursor() as cur:
                    sql = """
                        SELECT 元件ID, 参数值 
                        FROM 产品设计活动表_元件附加参数表 
                        WHERE 产品ID = %s AND 参数名称 = %s
                    """
                    cur.execute(sql, (product_id, "封头类型代号"))
                    results = cur.fetchall()

                    # 获取当前映射表
                    current_mapping = mapping.get(new_outer_base_value, {})

                    # 更新每个元件的封头类型代号
                    for row in results:
                        element_id = row.get("元件ID")
                        current_value = (row.get("参数值") or "").strip()

                        if not current_value:
                            continue

                        # 如果是不需要变化的类型，跳过
                        if current_value in unchanged_types:
                            continue

                        # 如果当前值在映射表中，则更新为新值
                        if current_value in current_mapping:
                            new_value = current_mapping[current_value]
                            try:
                                update_element_para_data(product_id, element_id, "封头类型代号", new_value)
                                print(f"[封头类型代号联动] 元件ID={element_id}: {current_value} -> {new_value}")
                            except Exception as e:
                                print(f"[封头类型代号联动] 更新元件ID={element_id}失败: {e}")
            finally:
                conn.close()
        except Exception as e:
            print(f"[封头类型代号联动更新] 处理失败: {e}")

    # 1106新修改
    def on_input_ref_data_clicked(self):
        if not getattr(self, "_is_valid_product", True):
            self.line_tip.setText("当前未选择产品，无法导入参考数据")
            self.line_tip.setStyleSheet("color: black;")
            self.line_tip.setToolTip("当前未选择产品，无法导入参考数据")
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

            # 导入前阻塞信号，防止触发自动高亮 #1106新修改
            self.tableWidget_design_data.blockSignals(True)
            self.tableWidget_general_data.blockSignals(True)

            try:
                # 执行导入操作
                import_all_reference_data(file_path, self)
                QMessageBox.information(self, "成功", "成功导入参考数据！")

                # 1112新修改-条件输入表格实质性变化：导入后不更新快照，让系统检测到这是相对于初始状态的变化
                # 这样关闭界面时会提示保存

                # 0209新修改-多工况输入标识显示
                # ✅ 导入参考数据后，检查多工况数据状态并刷新显示（因为可能导入了工况2/3数据）
                try:
                    self.update_multi_conditions_status()
                except Exception as e:
                    print(f"[多工况] 导入参考数据后检查失败: {e}")

                # 导入后清除所有高亮，确保不会显示缺失项高亮 #1106新修改
                self.clear_all_highlights()
            finally:
                # 恢复信号
                self.tableWidget_design_data.blockSignals(False)
                self.tableWidget_general_data.blockSignals(False)

        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))
            # 确保异常时也恢复信号 #1106新修改
            self.tableWidget_design_data.blockSignals(False)
            self.tableWidget_general_data.blockSignals(False)

    def render_grouped_table(self, table_widget, grouped_data, headers, group_key_column=0):
        render_grouped_table(table_widget, grouped_data, headers, group_key_column)

    def only_check_validate_data(self, force=False):
        """
        仅用于检查必填项，并返回检查结果与未填写的必填项，不执行保存操作。
        返回：一个元组，(检查结果, 未填写的必填项列表)
        """
        if not getattr(self, "_is_valid_product", True):
            return True  # 如果产品有效则直接返回 True

        try:
            # 检查必填项
            has_missing_dsg, missing_dsg = validate_required_fields(
                self.tableWidget_design_data, mode="设计数据"
            )
            has_missing_common, missing_common = validate_required_fields(
                self.tableWidget_general_data, mode="通用数据"
            )

            missing_fields = [name for _, name in (missing_dsg + missing_common)]

            # 如果有缺失的必填项，进行高亮
            if has_missing_dsg or has_missing_common:
                self._validation_triggered = True  # 保留实时高亮逻辑
                highlight_missing_required_rows(self.tableWidget_design_data, missing_dsg)
                highlight_missing_required_rows(self.tableWidget_general_data, missing_common)

                # 返回 False，表示有未填写的必填项
                return False, missing_fields

            # 如果没有缺失项，则返回 True
            return True, []

        except Exception as e:
            print(f"检查数据出错：{str(e)}")
            return False, []

    # 这个方法现在只由他将输入界面的“确认”按钮调用 (force=True)
    # 1106新修改
    def check_and_save_data(self, force=False, skip_confirm=False):
        """
        【保留功能】仅用于用户点击“确认”按钮时，检查必填项、以及保存。
        """
        if not getattr(self, "_is_valid_product", True):
            return (True, [])

        try:
            # 检查必填项
            has_missing_dsg, missing_dsg = validate_required_fields(
                self.tableWidget_design_data, mode="设计数据"
            )
            has_missing_common, missing_common = validate_required_fields(
                self.tableWidget_general_data, mode="通用数据"
            )

            missing_fields = [name for _, name in (missing_dsg + missing_common)]

            if has_missing_dsg or has_missing_common:
                self._validation_triggered = True  # 保留您的实时高亮逻辑
                highlight_missing_required_rows(self.tableWidget_design_data, missing_dsg)
                highlight_missing_required_rows(self.tableWidget_general_data, missing_common)

                # 保留您的弹窗询问逻辑
                if skip_confirm == False:
                    msg = ("以下必填项：\n" + "、".join(missing_fields) + "\n对应参数值不能为空。\n是否确认继续保存？")
                    if not show_confirm_dialog(self, "提示", msg):
                        return (False, missing_fields)

            # 执行保存操作
            if not save_local_condition_file(self.product_id, self):
                return (False, missing_fields)
            save_all_tables(self, self.product_id)
            # update_user_config_for_2_6_1(product_id, json_path="modules/yudingyi/dn_pressure_table.json")

            # ✅ 保存成功后，同步固定鞍座的鞍座高度
            try:
                from modules.cailiaodingyi.controllers.datamanager import sync_saddle_height_on_tab_refresh, \
                    get_fixed_saddle_element_id_from_db
                element_id = get_fixed_saddle_element_id_from_db(self.product_id)
                if element_id:
                    sync_saddle_height_on_tab_refresh(self.product_id, element_id)
                    print(f"[条件输入保存] 已同步固定鞍座高度: 产品{self.product_id}")
            except Exception as e:
                print(f"[条件输入保存] 鞍座高度同步失败: {e}")

            # 保存成功后清理状态
            self._validation_triggered = False
            self.clear_all_highlights()
            self.line_tip.setText("保存成功！")
            self.line_tip.setToolTip("保存成功！")
            self.line_tip.setStyleSheet("color: black;")

            self.tip_timer.stop()
            self.tip_timer.start(5000)

            # 关键：保存成功后，重置修改状态
            self._is_modified = False
            self.setWindowTitle(self.original_window_title)  # 恢复窗口标题
            # 标记已点击确认按钮保存
            self._has_confirmed_saved = True
            # 保存后，产品已保存到设计活动库
            self._is_saved_to_design_db = True
            # 1112新修改-条件输入表格实质性变化：保存成功后更新快照，将当前状态作为新的基准状态
            self._save_initial_snapshots()
            self._pending_outer_series_sync = False

            return (True, [])

        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存数据出错：\n{str(e)}")
            return (False, [])

    def _offer_discard_when_local_xlsx_missing(self, *, for_close_tab: bool) -> bool:
        """
        本地条件输入表不可写时，询问是否放弃未保存修改并关闭标签或切换界面。
        """
        if for_close_tab:
            msg = "本次保存失败，关闭后，未保存的内容将清空，是否仍要关闭？"
        else:
            msg = "本次保存失败，离开后，未保存的内容将清空，是否仍要离开？"
        return show_confirm_dialog(self, "保存失败", msg)

    def _offer_close_after_save_failed_for_datagb(self, exc: Exception) -> bool:
        """
        仅用于关闭标签页流程（check_and_save_datagb）：
        保存失败后提示错误，再询问是否仍要关闭界面（未保存修改将丢失）。
        """
        if getattr(self, "_local_condition_xlsx_missing", False):
            return self._offer_discard_when_local_xlsx_missing(for_close_tab=True)

        QMessageBox.warning(
            self,
            "保存失败",
            f"保存数据时发生错误，无法自动保存。\n\n错误信息：{exc}",
        )
        return show_confirm_dialog(
            self,
            "确认关闭",
            "是否仍要关闭条件输入界面？未保存的修改将丢失。",
        )

    # 1106新修改
    def check_and_save_datagb(self, force=False, skip_confirm=False):
        """
        用于用户点击关闭界面时，检查必填项并保存。
        根据两种情况决定是否需要检查必填项。
        返回: (bool, list) -> (是否可以关闭, 缺失字段列表)
        """
        if not getattr(self, "_is_valid_product", True):
            return (True, [])

        # 判断是否需要检查必填项
        need_check = self._should_check_required_fields()

        if not need_check:
            # 不需要检查，直接允许关闭
            return (True, [])

        # 标记：当前处于“主窗体关闭标签页”触发的检查流程里
        self._in_close_tab_flow = True
        try:
            # 需要检查必填项
            is_valid, missing_fields = self.only_check_validate_data()
            if is_valid:
                # 1112新修改-条件输入表格实质性变化：必填项完整，但有实质性修改，直接保存（不弹窗）
                if self._has_substantial_changes():
                    try:
                        # 执行保存操作
                        if not save_local_condition_file(self.product_id, self):
                            raise IOError("保存本地条件文件失败。")
                        save_all_tables(self, self.product_id)
                        # update_user_config_for_2_6_1(product_id, json_path="modules/yudingyi/dn_pressure_table.json")
                        # ✅ 保存成功后，同步固定鞍座的鞍座高度
                        try:
                            from modules.cailiaodingyi.controllers.datamanager import sync_saddle_height_on_tab_refresh, \
                                get_fixed_saddle_element_id_from_db
                            element_id = get_fixed_saddle_element_id_from_db(self.product_id)
                            if element_id:
                                sync_saddle_height_on_tab_refresh(self.product_id, element_id)
                                print(f"[条件输入保存] 已同步固定鞍座高度: 产品{self.product_id}")
                        except Exception as e:
                            print(f"[条件输入保存] 鞍座高度同步失败: {e}")

                        # 保存成功后，重置状态并允许关闭
                        self._is_modified = False
                        self.setWindowTitle(self.original_window_title)
                        self._has_confirmed_saved = True
                        self._is_saved_to_design_db = True
                        # 1112新修改-条件输入表格实质性变化：保存成功后更新快照，将当前状态作为新的基准状态
                        self._save_initial_snapshots()
                        self._pending_outer_series_sync = False
                        # 保存成功后清理高亮状态
                        self._validation_triggered = False
                        self.clear_all_highlights()
                        print("保存成功！现在可以关闭。")
                        if hasattr(self, 'line_tip') and self.line_tip:
                            self.line_tip.setText("保存成功！")
                            self.line_tip.setStyleSheet("color: black;")
                            self.line_tip.setToolTip("保存成功！")
                            if hasattr(self, 'tip_timer'):
                                self.tip_timer.start(5000)
                        return (True, [])

                    except Exception as e:
                        # 如果保存失败，弹窗提示并阻止关闭
                        print(f"保存失败，无法关闭: {e}")
                        if self._offer_close_after_save_failed_for_datagb(e):
                            return (True, [])
                        return (False, [])
                # 必填项完整，没有修改，直接允许关闭
                return (True, [])
            # 必填项不完整，弹窗提示
            if not skip_confirm:
                msg = ("以下必填项：\n" + "、".join(missing_fields) + "\n对应参数值不能为空。\n是否确认继续关闭？")
                reply = show_confirm_dialog(self, "提示", msg)
                if not reply:
                    # 用户选择取消关闭
                    return (False, missing_fields)
            # 用户选择继续关闭，需要保存数据
            try:
                # 执行保存操作
                if not save_local_condition_file(self.product_id, self):
                    raise IOError("保存本地条件文件失败。")
                save_all_tables(self, self.product_id)
                # update_user_config_for_2_6_1(product_id, json_path="modules/yudingyi/dn_pressure_table.json")

                # ✅ 保存成功后，同步固定鞍座的鞍座高度
                try:
                    from modules.cailiaodingyi.controllers.datamanager import sync_saddle_height_on_tab_refresh, \
                        get_fixed_saddle_element_id_from_db
                    element_id = get_fixed_saddle_element_id_from_db(self.product_id)
                    if element_id:
                        sync_saddle_height_on_tab_refresh(self.product_id, element_id)
                        print(f"[条件输入保存] 已同步固定鞍座高度: 产品{self.product_id}")
                except Exception as e:
                    print(f"[条件输入保存] 鞍座高度同步失败: {e}")

                # 保存成功后，重置状态并允许关闭
                self._is_modified = False
                self.setWindowTitle(self.original_window_title)
                self._has_confirmed_saved = True
                self._is_saved_to_design_db = True
                # 1112新修改-条件输入表格实质性变化：保存成功后更新快照，将当前状态作为新的基准状态
                self._save_initial_snapshots()
                self._pending_outer_series_sync = False
                # 保存成功后清理高亮状态
                self._validation_triggered = False
                self.clear_all_highlights()
                print("保存成功！现在可以关闭。")
                if hasattr(self, 'line_tip') and self.line_tip:
                    self.line_tip.setText("保存成功！")
                    self.line_tip.setStyleSheet("color: black;")
                    self.line_tip.setToolTip("保存成功！")
                    if hasattr(self, 'tip_timer'):
                        self.tip_timer.start(5000)
                return (True, missing_fields)

            except Exception as e:
                # 如果保存失败，弹窗提示并阻止关闭
                print(f"保存失败，无法关闭: {e}")
                if self._offer_close_after_save_failed_for_datagb(e):
                    return (True, missing_fields)
                return (False, missing_fields)

        except Exception as e:
            print(f"检查数据出错：{str(e)}")
            QMessageBox.critical(self, "检查失败", f"检查数据时发生错误：\n{str(e)}")
            return (False, [])

        finally:
            self._in_close_tab_flow = False

    # 1106新修改
    def check_and_save_dataqh(self, force=False, skip_confirm=False):
        """
        用于用户从条件输入界面切换至其他界面时，检查必填项并保存。
        根据两种情况决定是否需要检查必填项。
        返回: (bool, list) -> (是否可以切换, 缺失字段列表)
        """
        if not getattr(self, "_is_valid_product", True):
            return (True, [])

        # 判断是否需要检查必填项
        need_check = self._should_check_required_fields()
        if not need_check:
            # 不需要检查，直接允许切换
            return (True, [])
        try:
            # 需要检查必填项
            is_valid, missing_fields = self.only_check_validate_data()
            if is_valid:
                # 1112新修改-条件输入表格实质性变化：必填项完整，但有实质性修改，直接保存（不弹窗）
                if self._has_substantial_changes():
                    try:
                        # 执行保存操作
                        if not save_local_condition_file(self.product_id, self):
                            raise IOError("保存本地条件文件失败。")
                        save_all_tables(self, self.product_id)
                        # update_user_config_for_2_6_1(product_id, json_path="modules/yudingyi/dn_pressure_table.json")
                        # ✅ 保存成功后，同步固定鞍座的鞍座高度
                        try:
                            from modules.cailiaodingyi.controllers.datamanager import sync_saddle_height_on_tab_refresh, \
                                get_fixed_saddle_element_id_from_db
                            element_id = get_fixed_saddle_element_id_from_db(self.product_id)
                            if element_id:
                                sync_saddle_height_on_tab_refresh(self.product_id, element_id)
                                print(f"[条件输入保存] 已同步固定鞍座高度: 产品{self.product_id}")
                        except Exception as e:
                            print(f"[条件输入保存] 鞍座高度同步失败: {e}")

                        # 保存成功后，重置状态并允许切换
                        self._is_modified = False
                        self.setWindowTitle(self.original_window_title)
                        self._has_confirmed_saved = True
                        self._is_saved_to_design_db = True
                        # 1112新修改-条件输入表格实质性变化：保存成功后更新快照，将当前状态作为新的基准状态
                        self._save_initial_snapshots()
                        self._pending_outer_series_sync = False
                        # 保存成功后清理高亮状态
                        self._validation_triggered = False
                        self.clear_all_highlights()
                        print("保存成功！现在可以切换。")
                        if hasattr(self, 'line_tip') and self.line_tip:
                            self.line_tip.setText("保存成功！")
                            self.line_tip.setStyleSheet("color: black;")
                            self.line_tip.setToolTip("保存成功！")
                            if hasattr(self, 'tip_timer'):
                                self.tip_timer.start(5000)
                        return (True, [])

                    except Exception as e:
                        # 如果保存失败，弹窗提示并阻止切换
                        print(f"保存失败，无法切换: {e}")
                        if getattr(self, "_local_condition_xlsx_missing", False):
                            if self._offer_discard_when_local_xlsx_missing(for_close_tab=False):
                                return (True, [])
                            return (False, [])
                        QMessageBox.critical(self, "保存失败", f"保存数据时发生错误，切换操作已取消。\n\n错误信息: {e}")
                        return (False, [])
                # 必填项完整，没有修改，直接允许切换
                return (True, [])
            # 必填项不完整，弹窗提示
            if not skip_confirm:
                msg = ("以下必填项：\n" + "、".join(missing_fields) + "\n对应参数值不能为空。\n是否确认继续切换界面？")
                reply = show_confirm_dialog(self, "提示", msg)
                if not reply:
                    # 用户选择取消切换
                    return (False, missing_fields)

            # 用户选择继续切换，需要保存数据
            try:
                # 执行核心保存操作
                if not save_local_condition_file(self.product_id, self):
                    raise IOError("保存本地条件文件失败。")
                save_all_tables(self, self.product_id)
                # update_user_config_for_2_6_1(product_id, json_path="modules/yudingyi/dn_pressure_table.json")
                # ✅ 保存成功后，同步固定鞍座的鞍座高度
                try:
                    from modules.cailiaodingyi.controllers.datamanager import sync_saddle_height_on_tab_refresh, \
                        get_fixed_saddle_element_id_from_db
                    element_id = get_fixed_saddle_element_id_from_db(self.product_id)
                    if element_id:
                        sync_saddle_height_on_tab_refresh(self.product_id, element_id)
                        print(f"[条件输入保存] 已同步固定鞍座高度: 产品{self.product_id}")
                except Exception as e:
                    print(f"[条件输入保存] 鞍座高度同步失败: {e}")

                # 保存成功后，重置状态并允许切换
                self._is_modified = False
                self.setWindowTitle(self.original_window_title)
                self._has_confirmed_saved = True
                self._is_saved_to_design_db = True
                # 1112新修改-条件输入表格实质性变化：保存成功后更新快照，将当前状态作为新的基准状态
                self._save_initial_snapshots()
                self._pending_outer_series_sync = False
                # 保存成功后清理高亮状态
                self._validation_triggered = False
                self.clear_all_highlights()
                print("保存成功！现在可以切换。")
                if hasattr(self, 'line_tip') and self.line_tip:
                    self.line_tip.setText("保存成功！")
                    self.line_tip.setStyleSheet("color: black;")
                    self.line_tip.setToolTip("保存成功！")
                    if hasattr(self, 'tip_timer'):
                        self.tip_timer.start(5000)
                return (True, missing_fields)

            except Exception as e:
                # 如果保存失败，弹窗提示并阻止切换
                print(f"保存失败，无法切换: {e}")
                if getattr(self, "_local_condition_xlsx_missing", False):
                    if self._offer_discard_when_local_xlsx_missing(for_close_tab=False):
                        return (True, missing_fields)
                    return (False, missing_fields)
                QMessageBox.critical(self, "保存失败", f"保存数据时发生错误，切换操作已取消。\n\n错误信息: {e}")
                return (False, missing_fields)

        except Exception as e:
            print(f"检查数据出错：{str(e)}")
            QMessageBox.critical(self, "检查失败", f"检查数据时发生错误：\n{str(e)}")
            return (False, [])

    # lxy101 新增清除高亮
    def clear_all_highlights(self):
        """清除所有表格的高亮显示"""
        # 清除设计数据表高亮
        highlight_missing_required_rows(self.tableWidget_design_data, [])
        # 清除通用数据表高亮
        highlight_missing_required_rows(self.tableWidget_general_data, [])
        # 若其他表格有高亮逻辑，在此补充
        # 示例：highlight_missing_required_rows(self.tableWidget_coating_data, [])

    def handle_cell_input(self, item):  # 信号会自动传入被修改的 QTableWidgetItem
        """处理单元格输入，实时校验并更新高亮状态"""

        # ▼▼▼【核心修改 2.1】检查“开关”状态 ▼▼▼
        # 如果从未触发过验证（即没点过“保存”并失败），则不进行任何实时高亮操作。
        if not self._validation_triggered:
            return

        # 正在加载数据时也忽略
        if self._is_loading_data:
            return

        table_widget = item.tableWidget()  # 从 item 对象获取它所属的表格

        # ▼▼▼【核心修改 2.2】在处理前，临时阻塞信号，防止无限循环 ▼▼▼
        table_widget.blockSignals(True)

        try:
            # 确定当前操作的是哪个表格，获取对应的模式名称
            mode = None
            if table_widget is self.tableWidget_design_data:
                mode = "设计数据"
            elif table_widget is self.tableWidget_general_data:
                mode = "通用数据"

            if mode:
                # 重新对当前表格的所有必填项进行校验
                has_missing, missing_fields = validate_required_fields(table_widget, mode=mode)

                # 根据最新的校验结果，直接更新高亮
                # 如果 missing_fields 为空，则会清除所有高亮
                highlight_missing_required_rows(table_widget, missing_fields)

        finally:
            # ▼▼▼【核心修改 2.3】处理完成后，一定要恢复信号 ▼▼▼
            table_widget.blockSignals(False)

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

    # 1111新修改-2金属温度单元格不可编辑
    # 新增 模式切换处理函数
    def on_mode_changed(self, mode_name: str):
        """
        仅改变界面显示顺序；数据库与本地Excel保存仍使用默认顺序。
        """
        print(f"[DEBUG] on_mode_changed 被调用，当前模式切换为: {mode_name}")  # ✅ 添加这行
        if not mode_name:
            return

        # 默认模式 = 恢复默认顺序（即初始载入时顺序） 设计模式
        if mode_name == self._default_mode_name or mode_name.strip() == "":
            # 用"默认ID顺序"再排一次（就是 capture_default_order 记录那次的出现次序）
            # 使用 restore_default_order 严格按照原始顺序恢复，不使用必填项优先逻辑
            # ids_std = getattr(self.tableWidget_product_std, "_default_param_ids", None)
            # if ids_std:
            # restore_default_order(self.tableWidget_product_std)
            restore_default_order(self.tableWidget_design_data)
            # ids_general = getattr(self.tableWidget_general_data, "_default_param_ids", None)
            # if ids_general:
            # restore_default_order(self.tableWidget_general_data)

            ## 1111新修改-2金属温度单元格不可编辑
            # 切换到设计模式后，重新应用NEN/BEM产品的特殊只读单元格
            self._apply_special_readonly_for_nen_bem()
            return

        # 其他模式：查表里的“参数顺序”并应用
        target_ids = self._mode_orders.get(mode_name)
        if not target_ids:
            return

        # 仅重排三张含“参数ID”的表
        # apply_mode_param_order(self.tableWidget_product_std, target_ids)
        apply_mode_param_order(self.tableWidget_design_data, target_ids)
        # apply_mode_param_order(self.tableWidget_general_data, target_ids)

        # ===== 新增：模式切换后，将设计数据表格的序号列设为不可编辑 =====
        print(f"[DEBUG] 正在设置设计数据表格（tableWidget_design_data）的序号列（第0列）为不可编辑")  # ✅ 调试打印

        # ✅ 无论切换到什么模式，都执行这一段 ✅ 所有模式切换逻辑执行完毕后，统一设置序号列不可编辑
        if hasattr(self, 'tableWidget_design_data') and self.tableWidget_design_data is not None:
            # 序号列是第 0 列
            column = 0
            for row in range(self.tableWidget_design_data.rowCount()):
                item = self.tableWidget_design_data.item(row, column)
                if item is not None:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)  # 移除可编辑标志
            print(f"[DEBUG] 设计数据表格序号列已设为不可编辑")  # ✅ 调试打印

        # # 1111新修改-2金属温度单元格不可编辑
        # 切换到工作模式后，重新应用NEN/BEM产品的特殊只读单元格
        self._apply_special_readonly_for_nen_bem()

    def eventFilter(self, obj, event):
        """
        拦截“设计数据”表的单击：
        - 命中“参数名称”列 且 参数名为“设计压力*”或“设计压力”时，弹出多工况窗口
        - 单击即可触发（若想双击触发，把 MouseButtonRelease 改成 MouseButtonDblClick）
        """
        try:
            # 屏蔽“设计模式/工作模式”等页面顶部下拉框的鼠标滚轮
            if hasattr(self, "combo_mode") and obj is getattr(self, "combo_mode") and event.type() == QEvent.Wheel:
                return True

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
        打开"多工况"窗口（6行参数+壳程/管程两列），切换工况可编辑不同工况数据，
        确认时直接保存到数据库。
        """
        dlg = MultiConditionsDialog(self, product_id=self.product_id)
        dlg.exec_()
        # ✅ 对话框关闭后，重新检查多工况数据状态并更新显示
        # 注意：如果用户在对话框中保存了数据，保存方法中已经会调用 update_multi_conditions_status
        # 但为了确保状态同步（即使没有保存），这里也检查一次
        self.update_multi_conditions_status()

    # 0209新修改-多工况输入标识显示
    def _check_multi_conditions(self):
        """
        检查是否有工况2或工况3的非空数据，更新缓存。
        检查逻辑：查询参数名称包含[工况2]或[工况3]的记录，且壳程数值或管程数值至少有一个非空。
        """
        if not self.product_id:
            self._has_multi_conditions = False
            return

        try:
            from modules.condition_input.funcs.funcs_cdt_input import get_connection
            db_config_2 = {
                'host': 'localhost',
                'port': 3306,
                'user': 'root',
                'password': '123456',
                'database': '产品设计活动库'
            }
            conn = get_connection(**db_config_2)
            with conn.cursor() as cur:
                # 查询是否有工况2或工况3的非空数据
                cur.execute("""
                    SELECT COUNT(*) AS cnt
                    FROM 产品设计活动表_设计数据表
                    WHERE 产品ID = %s
                      AND (参数名称 LIKE %s OR 参数名称 LIKE %s)
                      AND (TRIM(COALESCE(壳程数值, '')) != '' OR TRIM(COALESCE(管程数值, '')) != '')
                """, (self.product_id, '%[工况2]%', '%[工况3]%'))
                row = cur.fetchone()
                count = row.get("cnt", 0) if row else 0
                self._has_multi_conditions = count > 0
            conn.close()
        except Exception as e:
            print(f"[多工况] 检查多工况数据失败: {e}")
            self._has_multi_conditions = False

    def update_multi_conditions_status(self):
        """
        公共方法：更新多工况状态并刷新显示。
        供外部（如多工况对话框）调用。
        """
        self._check_multi_conditions()
        if hasattr(self, 'tableWidget_design_data'):
            # 重绘整个表格的viewport，确保"多工况..."标识更新
            self.tableWidget_design_data.viewport().update()

    def _set_modified(self, modified=True):
        """标记数据是否已修改"""
        self._is_modified = modified

    # 1112新修改-条件输入表格实质性变化
    def _extract_table_data(self, table_widget):
        """提取表格的所有数据内容，用于快照比较（忽略行顺序）"""
        if not table_widget:
            return {}

        data = {}
        row_count = table_widget.rowCount()
        col_count = table_widget.columnCount()

        # 提取表头信息
        headers = []
        for col in range(col_count):
            header_item = table_widget.horizontalHeaderItem(col)
            headers.append(header_item.text() if header_item else f"Col_{col}")
        data['headers'] = headers

        # 提取所有单元格数据，并按内容排序以忽略行顺序
        rows_data = []
        for row in range(row_count):
            row_data = []
            for col in range(col_count):
                item = table_widget.item(row, col)
                cell_value = item.text() if item else ""
                row_data.append(cell_value)
            rows_data.append(tuple(row_data))  # 转为tuple便于排序和比较

        # 对行数据进行排序，这样即使行的顺序改变，只要内容相同就认为没有变化
        rows_data.sort()
        data['rows'] = rows_data

        return data

    # 1112新修改-条件输入表格实质性变化
    def _save_initial_snapshots(self):
        """保存所有表格的初始状态快照"""
        tables = [
            ('design_data', self.tableWidget_design_data),
            ('general_data', self.tableWidget_general_data),
            ('product_std', self.tableWidget_product_std),
            ('trail_data', self.tableWidget_trail_data),
            ('coating_data', self.tableWidget_coating_data)
        ]

        for table_name, table_widget in tables:
            if table_widget:
                self._initial_table_snapshots[table_name] = self._extract_table_data(table_widget)

        print(f"[快照] 已保存 {len(self._initial_table_snapshots)} 个表格的初始状态快照")

    # 1112新修改-条件输入表格实质性变化
    def _has_substantial_changes(self):
        """检测是否有实质性变化（相对于初始状态）"""
        # 外径系列被user_config覆盖（与DB不一致）时，需在关闭时保存
        if getattr(self, "_pending_outer_series_sync", False):
            print("[快照] 检测到外径系列被预定义覆盖，需保存到数据库")
            return True
        if not self._initial_table_snapshots:
            # 如果没有初始快照，认为没有变化
            return False

        tables = [
            ('design_data', self.tableWidget_design_data),
            ('general_data', self.tableWidget_general_data),
            ('product_std', self.tableWidget_product_std),
            ('trail_data', self.tableWidget_trail_data),
            ('coating_data', self.tableWidget_coating_data)
        ]

        for table_name, table_widget in tables:
            if not table_widget:
                continue

            initial_data = self._initial_table_snapshots.get(table_name, {})
            current_data = self._extract_table_data(table_widget)

            # 比较当前数据与初始数据
            if initial_data != current_data:
                print(f"[快照] 检测到表格 {table_name} 发生实质性变化")
                return True

        print("[快照] 未检测到实质性变化")
        return False
