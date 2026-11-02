"""
附件定义表（tableWidget_attachment）的下拉代理、选项查询与单元格交互。
与管口表逻辑分离，对应 funcs_pipe_comboBox_value 中的管口部分。
"""
import pymysql.cursors
import re
from PyQt5 import sip
from PyQt5.QtCore import Qt, QObject, QEvent, QItemSelectionModel, QTimer
from PyQt5.QtWidgets import (
    QMessageBox,
    QTableWidgetItem,
    QApplication,
    QToolTip,
    QAbstractItemView,
)

from modules.guankoudingyi.db_cnt import get_connection, db_config_1, db_config_2
from modules.guankoudingyi.funcs.funcs_pipe_comboBox_value import (
    ComboBoxDelegate,
    pipe_combo_arrow_rect,
    _should_paint_pipe_combo_arrow,
    _arm_pipe_combo_editor,
    get_container_shell_length,
)
from modules.guankoudingyi.funcs.funcs_pipe_table import show_styled_warning
from modules.guankoudingyi.obtain_product_type_version import get_product_type_and_version


# ---------------------------------------------------------------------------
# 附件定义表列契约（容器界面 8 列；库中未展示字段保存时不覆盖）
# 0 序号 | 1 元件名称 | 2 元件类型 | 3 所属元件 | 4 轴向定位基准
# 5 轴向定位距离 | 6 周向方位 | 7 备注
# ---------------------------------------------------------------------------
ATTACHMENT_HEADERS = (
    "序号",
    "元件名称",
    "元件类型",
    "所属元件",
    "轴向定位基准",
    "轴向定位距离(mm)",
    "周向方位(°)",
    "备注",
)
ATTACHMENT_COLUMN_COUNT = len(ATTACHMENT_HEADERS)
ATTACHMENT_FIRST_EDITABLE_DATA_COL = 2  # 从「元件类型」起随元件名称解冻

# 界面列 → 产品设计活动表_附件表字段（序号不入库）
ATTACHMENT_UI_TO_DB_FIELD = {
    1: "元件名称",
    2: "元件类型",
    3: "所属元件",
    4: "轴向定位基准",
    5: "轴向定位距离mm",
    6: "周向方位（°）",
    7: "备注",
}

# 库回填到界面的字段顺序（与列 1~7 对齐；读库时兼容全角括号）
ATTACHMENT_LOAD_FIELDS = (
    "元件名称",
    "元件类型",
    "所属元件",
    "轴向定位基准",
    "轴向定位距离mm",
    "周向方位(°)",
    "备注",
)

ATTACHMENT_COMPONENT_NAME_COLUMN = 1
ATTACHMENT_COMPONENT_NAME_ITEM_FLAGS = Qt.ItemIsSelectable | Qt.ItemIsEnabled
ATTACHMENT_COL_COMPONENT_TYPE = 2
ATTACHMENT_COL_BELONG = 3
ATTACHMENT_COL_AXIAL_BASE = 4
ATTACHMENT_COL_AXIAL_DISTANCE = 5
ATTACHMENT_COL_CIRCUMFERENTIAL = 6
ATTACHMENT_COL_REMARK = 7
# 所属元件为封头类：锁定轴向定位基准 / 轴向定位距离 / 周向方位
ATTACHMENT_HEAD_LOCK_COLUMNS = (
    ATTACHMENT_COL_AXIAL_BASE,
    ATTACHMENT_COL_AXIAL_DISTANCE,
    ATTACHMENT_COL_CIRCUMFERENTIAL,
)
ATTACHMENT_HEAD_LOCK_TEXT = "/"
# 周向方位始终禁用并显示「/」的元件家族（不论所属元件）
ATTACHMENT_CIRC_ALWAYS_LOCK_BASES = frozenset({"保温支撑环", "加强圈"})
ATTACHMENT_VALIDATION_COLUMNS = frozenset({
    ATTACHMENT_COL_AXIAL_DISTANCE,
    ATTACHMENT_COL_CIRCUMFERENTIAL,
})
# 纯输入编辑列（轴向定位距离为可编辑下拉，不走此路径）
ATTACHMENT_PLAIN_EDIT_COLUMNS = frozenset({
    ATTACHMENT_COL_CIRCUMFERENTIAL,
    ATTACHMENT_COL_REMARK,
})
# 纯输入批量列（对齐管口 PIPE_PLAIN_BULK_COLUMNS）
ATTACHMENT_PLAIN_BULK_COLUMNS = frozenset({ATTACHMENT_COL_CIRCUMFERENTIAL})


def _attachment_bulk_assign_columns():
    """支持批量赋值的列：所属元件 + 轴向定位基准/距离 + 周向方位。"""
    return {
        ATTACHMENT_COL_BELONG,
        ATTACHMENT_COL_AXIAL_BASE,
        ATTACHMENT_COL_AXIAL_DISTANCE,
        ATTACHMENT_COL_CIRCUMFERENTIAL,
    }


def _clear_attachment_bulk_edit_guard(stats_widget):
    """结束附件批量编辑保护（高亮快照）。"""
    stats_widget._attachment_bulk_edit_active = False
    stats_widget._attachment_bulk_rows_snapshot = []


def compute_attachment_intersection_options(stats_widget, column, rows):
    """按多行计算附件下拉可选项交集（所属元件按各行元件名称分别过滤后再求交）。"""
    table = getattr(stats_widget, "tableWidget_attachment", None)
    if table is None:
        return []
    if column == ATTACHMENT_COL_BELONG:
        full = list(_cached_attachment_belong_options(stats_widget) or [])
        intersection = None
        ordered = []
        for r in rows:
            name_item = table.item(r, ATTACHMENT_COMPONENT_NAME_COLUMN)
            name = name_item.text().strip() if name_item else ""
            opts = _filter_attachment_belong_options(full, name)
            opts_set = set(opts)
            if intersection is None:
                intersection = opts_set
                ordered = list(opts)
            else:
                intersection &= opts_set
            if not intersection:
                return []
        return [x for x in ordered if x in intersection] or sorted(intersection)
    if column == ATTACHMENT_COL_AXIAL_DISTANCE:
        return ["程序推荐", "居中"]
    if column == ATTACHMENT_COL_AXIAL_BASE:
        product_id = getattr(stats_widget, "product_id", None)
        intersection = None
        ordered = []
        for r in rows:
            belong_item = table.item(r, ATTACHMENT_COL_BELONG)
            belong = belong_item.text().strip() if belong_item else None
            opts = get_attachment_axial_position_base_options(product_id, belong) or []
            opts_set = set(opts)
            if intersection is None:
                intersection = opts_set
                ordered = list(opts)
            else:
                intersection &= opts_set
            if not intersection:
                return []
        return [x for x in ordered if x in intersection] or sorted(intersection)
    return []


def attachment_editable_data_cols():
    """有元件名称时可编辑的数据列（不含序号、元件名称）。"""
    return range(ATTACHMENT_FIRST_EDITABLE_DATA_COL, ATTACHMENT_COLUMN_COUNT)


def _attachment_belong_is_head(belong: str) -> bool:
    return "封头" in (belong or "")


def _attachment_circumferential_always_locked(element_name: str) -> bool:
    """保温支撑环 / 加强圈：周向方位始终「/」且不可编。"""
    text = (element_name or "").strip()
    if not text:
        return False
    for base in ATTACHMENT_CIRC_ALWAYS_LOCK_BASES:
        if text == base or re.match(rf"^{re.escape(base)}\d+$", text):
            return True
    return False


def _attachment_column_should_lock(belong: str, element_name: str, column: int) -> bool:
    """封头锁定位列；保温支撑环/加强圈额外锁周向方位。"""
    if column not in ATTACHMENT_HEAD_LOCK_COLUMNS:
        return False
    if _attachment_belong_is_head(belong):
        return True
    if column == ATTACHMENT_COL_CIRCUMFERENTIAL and _attachment_circumferential_always_locked(
        element_name
    ):
        return True
    return False


def attachment_cell_is_head_locked(table, row, column) -> bool:
    """高亮/批量等：判断该格是否因封头或元件类型规则而禁用。"""
    if table is None or row <= 0 or column not in ATTACHMENT_HEAD_LOCK_COLUMNS:
        return False
    belong_item = table.item(row, ATTACHMENT_COL_BELONG)
    belong = belong_item.text().strip() if belong_item else ""
    name_item = table.item(row, ATTACHMENT_COMPONENT_NAME_COLUMN)
    name = name_item.text().strip() if name_item else ""
    return _attachment_column_should_lock(belong, name, column)


def apply_attachment_row_column_locks_by_belong(stats_widget, row):
    """
    所属元件含「封头」时：轴向定位基准、轴向定位距离、周向方位显示「/」且不可编辑。
    保温支撑环 / 加强圈：周向方位始终「/」且不可编辑（与所属无关）。
    背景色不在这里改，统一由 highlight_selected_attachment_rows 处理，避免与整行高亮互相覆盖。
    """
    table = getattr(stats_widget, "tableWidget_attachment", None)
    if table is None or row <= 0 or row >= table.rowCount():
        return

    belong_item = table.item(row, ATTACHMENT_COL_BELONG)
    belong = belong_item.text().strip() if belong_item else ""
    name_item = table.item(row, ATTACHMENT_COMPONENT_NAME_COLUMN)
    element_name = name_item.text().strip() if name_item else ""
    has_name = bool(element_name)
    locked_flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
    editable_flags = Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled

    prev_suppress = getattr(stats_widget, "suppress_cell_change", False)
    stats_widget.suppress_cell_change = True
    try:
        for col in ATTACHMENT_HEAD_LOCK_COLUMNS:
            item = table.item(row, col)
            if item is None:
                item = QTableWidgetItem("")
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, col, item)
            if _attachment_column_should_lock(belong, element_name, col):
                if item.text().strip() != ATTACHMENT_HEAD_LOCK_TEXT:
                    item.setText(ATTACHMENT_HEAD_LOCK_TEXT)
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(locked_flags)
            else:
                if item.text().strip() == ATTACHMENT_HEAD_LOCK_TEXT:
                    item.setText("")
                item.setFlags(editable_flags if has_name else locked_flags)
    finally:
        stats_widget.suppress_cell_change = prev_suppress

    # 只重刷背景（高亮/灰底），避免再进 update_bulk 造成多余状态变化
    try:
        if hasattr(stats_widget, "_apply_highlight_to_table_cells"):
            stats_widget._apply_highlight_to_table_cells(table)
            table.viewport().update()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 附件表数值列校验（与管口表当前规则一致；独立实现便于后续单独调整）
# ---------------------------------------------------------------------------
def _attachment_set_tip(stats_widget, text="", color=None):
    """统一设置/清空底部提示条（复用管口 _set_tip，含 sticky 防清空保护）。"""
    if getattr(stats_widget, "line_tip", None) is None:
        return
    from modules.guankoudingyi.funcs.funcs_pipe_comboBox_value import _set_tip
    _set_tip(stats_widget, text, color)


def _attachment_show_error_tip(stats_widget, message):
    """校验失败：显示红字 tip，并 sticky 防后续合法回写/高亮误清空。"""
    if not message:
        return
    from modules.guankoudingyi.funcs.funcs_pipe_comboBox_value import (
        _schedule_pipe_error_tip_restore,
    )
    _schedule_pipe_error_tip_restore(stats_widget, str(message))


def _attachment_clear_error_tip(stats_widget):
    """校验通过：解除 sticky 后再清空 tip。"""
    stats_widget._pipe_sticky_error_tip = None
    _attachment_set_tip(stats_widget, "")


def validate_attachment_circumferential_position(position_text, element_name=""):
    """
    验证附件表周向方位（0°～360°）。
    element_name：当前行元件名称（校验失败回填时保留入参兼容，空值不再按类型写默认角）。
    """
    try:
        text = (position_text or "").strip()
        # 空值、封头锁定占位「/」：不回填默认角度
        if not text or text in ("/", "-"):
            return True, text if text else ""
        position = float(text)
        if 0 <= position < 360:
            return True, position
        return False, "周向方位必须在0到360度之间"
    except ValueError:
        return False, "请输入有效的数字"


def validate_attachment_axial_position_distance(distance_text, product_id=None, element_name=""):
    """
    验证附件表轴向定位距离：预设项直接通过；数值须在 [0, 容器壳体长度) 内。
    与管口 validate_container_axial_position_distance 规则一致。
    """
    try:
        text = (distance_text or "").strip()
        if text in ("程序推荐", "居中"):
            return True, text
        # 封头锁定占位
        if text in ("/", "-"):
            return True, text
        if not text:
            return True, "程序推荐"
        try:
            distance_value = float(text)
        except ValueError:
            return False, "请输入有效的数字"

        shell_length = get_container_shell_length(product_id)
        if shell_length is None:
            return False, "未获取到容器壳体长度，须先至条件输入输入容器壳体长度并保存"

        if 0 <= distance_value < shell_length:
            return True, distance_value

        name = (element_name or "").strip() or "当前附件"
        return False, (
            f"{name}的轴向定位距离需在0 mm至{shell_length:.2f} mm之间"
            f"（小于容器壳体长度）"
        )
    except Exception as e:
        return False, f"验证失败: {str(e)}"


def get_attachment_belong_options(product_id):
    """根据产品类型和产品型式从元件库中的附件所属轴向定位基准表中获取所属元件。"""
    product_type, product_version = get_product_type_and_version(product_id)
    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config_1)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT DISTINCT 所属元件
            FROM 附件所属轴向定位基准表
            WHERE 产品类型 = %s AND 产品型式 = %s
        """, (product_type, product_version))
        return [row["所属元件"] for row in cursor.fetchall() if row.get("所属元件")]
    except Exception as e:
        QMessageBox.warning(None, "数据库错误", f"获取附件所属元件失败: {str(e)}")
        return []
    finally:
        cursor and cursor.close()
        conn and conn.close()


def _attachment_is_insulation_ring_name(element_name: str) -> bool:
    """保温支撑环 / 保温支撑环1… 才允许所属元件选封头类。"""
    text = (element_name or "").strip()
    if not text:
        return False
    return text == "保温支撑环" or bool(re.match(r"^保温支撑环\d+$", text))


def _filter_attachment_belong_options(options, element_name):
    """
    所属元件下拉：仅保温支撑环保留封头类；其余元件去掉封头，只留圆筒类。
    """
    opts = [str(o).strip() for o in (options or []) if str(o).strip()]
    if _attachment_is_insulation_ring_name(element_name):
        return opts
    return [o for o in opts if "封头" not in o]


def _cached_attachment_belong_options(stats_widget):
    """按产品缓存所属元件全量，避免多选时反复查库。"""
    pid = getattr(stats_widget, "product_id", None)
    cache = getattr(stats_widget, "_attachment_belong_options_cache", None)
    if isinstance(cache, tuple) and len(cache) == 2 and cache[0] == pid:
        return list(cache[1])
    opts = list(get_attachment_belong_options(pid) or [])
    stats_widget._attachment_belong_options_cache = (pid, opts)
    return list(opts)


def get_attachment_belong_options_for_row(stats_widget, row):
    """按当前行元件名称过滤后的所属元件选项。"""
    table = getattr(stats_widget, "tableWidget_attachment", None)
    name = ""
    if table is not None and row > 0:
        name_item = table.item(row, ATTACHMENT_COMPONENT_NAME_COLUMN)
        name = name_item.text().strip() if name_item else ""
    return _filter_attachment_belong_options(
        _cached_attachment_belong_options(stats_widget), name
    )


def get_attachment_axial_position_base_options(product_id, attachment_belong=None):
    """
    根据产品类型、产品型式、所属元件获取“轴向定位基准”下拉框选项（附件定义）。
    :param product_id: 产品ID
    :param attachment_belong: 所属元件，可为空
    :return: 轴向定位基准选项列表
    """
    conn = None
    cursor = None
    try:
        product_type, product_version = get_product_type_and_version(product_id)
        conn = get_connection(**db_config_1)
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        sql = """
            SELECT DISTINCT 轴向定位基准
            FROM 附件所属轴向定位基准表
            WHERE 产品类型 = %s AND 产品型式 = %s
        """
        params = [product_type, product_version]
        if attachment_belong:
            sql += " AND 所属元件 = %s"
            params.append(attachment_belong)

        cursor.execute(sql, params)
        return [row["轴向定位基准"] for row in cursor.fetchall() if row.get("轴向定位基准")]
    except Exception as e:
        QMessageBox.warning(None, "数据库错误", f"获取附件轴向定位基准失败: {str(e)}")
        return []
    finally:
        cursor and cursor.close()
        conn and conn.close()


# 与元件侧 datamanager 鞍式筛选常量对齐（管口侧不依赖其内部函数）
_ATTACHMENT_SADDLE_SUPPORT_STANDARD = "NB/T 47065.1"
_ATTACHMENT_SADDLE_MODEL_ALL = ["A", "BI", "BII", "BIII", "BIV", "BV"]


def _is_attachment_saddle_component_name(component_name: str) -> bool:
    """元件名称是否为鞍式支座家族（鞍式支座 / 鞍式支座1…）。"""
    text = (component_name or "").strip()
    if not text:
        return False
    return text == "鞍式支座" or bool(re.match(r"^鞍式支座\d+$", text))


def _filter_attachment_saddle_type_options_by_dn(base_options, product_id):
    """
    鞍式元件类型按壳程公称直径筛选（规则对齐元件侧）：
    - DN 空 / 查询失败 / 落在断开区间 → 回退全集（与管口类型表求交）
    - 否则 → 适用范围表结果与候选求交
    DN：funcs_pdf_change.get_shell_nominal_diameter_mm
    表筛：datamanager.get_saddle_model_options_by_dn
    """
    base = [m for m in (base_options or []) if str(m).strip()]
    if not base:
        base = list(_ATTACHMENT_SADDLE_MODEL_ALL)
    base_set = set(base)

    shell_dn = None
    if product_id:
        try:
            from modules.cailiaodingyi.funcs.funcs_pdf_change import (
                get_shell_nominal_diameter_mm,
            )
            shell_dn = get_shell_nominal_diameter_mm(product_id)
        except Exception as e:
            print(f"[附件] 读取壳程公称直径失败: {e}")
            shell_dn = None

    if shell_dn is None:
        return (
            [m for m in _ATTACHMENT_SADDLE_MODEL_ALL if m in base_set]
            or list(_ATTACHMENT_SADDLE_MODEL_ALL)
        )

    try:
        from modules.cailiaodingyi.controllers.datamanager import (
            get_saddle_model_options_by_dn,
        )
        allowed = get_saddle_model_options_by_dn(
            _ATTACHMENT_SADDLE_SUPPORT_STANDARD, shell_dn
        )
    except Exception as e:
        print(f"[附件] 鞍式型号DN筛选失败: {e}")
        allowed = None

    if not allowed:  # None(失败) 或 [](落空区间)
        return (
            [m for m in _ATTACHMENT_SADDLE_MODEL_ALL if m in base_set]
            or list(_ATTACHMENT_SADDLE_MODEL_ALL)
        )

    filtered = [m for m in allowed if m in base_set]
    if not filtered:
        return (
            [m for m in _ATTACHMENT_SADDLE_MODEL_ALL if m in base_set]
            or list(_ATTACHMENT_SADDLE_MODEL_ALL)
        )
    return filtered


def get_attachment_component_type_options(component_name, product_id=None):
    """
    根据元件名称从元件库“管口元件类型表”获取“元件类型”下拉选项。
    鞍式支座家族：再按壳程公称直径筛选（与元件定义支座型号规则一致）。
    :param component_name: 元件名称（对应表字段“对应元件”）
    :param product_id: 产品ID，鞍式筛选用；可空
    :return: 元件类型选项列表
    """
    if not component_name or not str(component_name).strip():
        return []

    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config_1)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT 元件类型
            FROM 管口元件类型表
            WHERE TRIM(%s) LIKE CONCAT('%%', TRIM(COALESCE(对应元件, '')), '%%')
            GROUP BY 元件类型
            ORDER BY MIN(类型ID) ASC
        """, (str(component_name).strip(),))
        options = [row["元件类型"] for row in cursor.fetchall() if row.get("元件类型")]
    except Exception as e:
        QMessageBox.warning(None, "数据库错误", f"获取附件元件类型失败: {str(e)}")
        return []
    finally:
        cursor and cursor.close()
        conn and conn.close()

    if _is_attachment_saddle_component_name(component_name):
        options = _filter_attachment_saddle_type_options_by_dn(options, product_id)
    return options


def initialize_attachment_combobox_delegates(stats_widget):
    """
    初始化附件定义表下拉框代理（对齐 ATTACHMENT_HEADERS 8 列契约）。
    2 元件类型、3 所属元件、4 轴向定位基准：纯下拉
    5 轴向定位距离：可编辑下拉
    """
    table = getattr(stats_widget, "tableWidget_attachment", None)
    if table is None:
        return

    stats_widget.attachment_column_delegates = {}

    static_columns = {
        ATTACHMENT_COL_AXIAL_DISTANCE: ["程序推荐", "居中"],
    }
    for col, options in static_columns.items():
        if col < 0 or col >= table.columnCount():
            continue
        delegate = ComboBoxDelegate(table, editable=True, overwrite_on_first_key=True)
        delegate.setItems(options)
        delegate.setParent(table)
        delegate.stats_widget = stats_widget
        delegate.show_dropdown_arrow = True
        table.setItemDelegateForColumn(col, delegate)
        stats_widget.attachment_column_delegates[col] = delegate

    dynamic_columns = [
        ATTACHMENT_COL_COMPONENT_TYPE,
        ATTACHMENT_COL_BELONG,
        ATTACHMENT_COL_AXIAL_BASE,
    ]
    for col in dynamic_columns:
        if col < 0 or col >= table.columnCount():
            continue
        delegate = ComboBoxDelegate(table, editable=False)
        delegate.setItems([])
        delegate.setParent(table)
        delegate.stats_widget = stats_widget
        delegate.show_dropdown_arrow = True
        table.setItemDelegateForColumn(col, delegate)
        stats_widget.attachment_column_delegates[col] = delegate

    stats_widget.attachment_dropdown_columns = set(static_columns.keys()) | set(dynamic_columns)


# 当前界面实际启用的下拉列
ATTACHMENT_ACTIVE_DROPDOWN_COLUMNS = frozenset({
    ATTACHMENT_COL_COMPONENT_TYPE,
    ATTACHMENT_COL_BELONG,
    ATTACHMENT_COL_AXIAL_BASE,
})
# 可编辑下拉（空白进编辑不展开；箭头才展开）
ATTACHMENT_EDITABLE_COMBO_COLUMNS = frozenset({ATTACHMENT_COL_AXIAL_DISTANCE})


def _attachment_dropdown_columns(stats_widget):
    return getattr(stats_widget, "attachment_dropdown_columns", None) or (
        ATTACHMENT_ACTIVE_DROPDOWN_COLUMNS | ATTACHMENT_EDITABLE_COMBO_COLUMNS
    )


def _is_attachment_editable_combo_column(column):
    return column in ATTACHMENT_EDITABLE_COMBO_COLUMNS


def _attachment_cell_is_editable(table, row, column):
    if table is None or row <= 0 or column < 0:
        return False
    item = table.item(row, column)
    if item is None:
        return False
    flags = item.flags()
    return bool(flags & Qt.ItemIsEnabled and flags & Qt.ItemIsEditable)


class AttachmentComboArrowMouseFilter(QObject):
    """
    附件表下拉列：仅点右侧箭头打开；点空白只选中（便于多选）。
    禁用列（不可编辑）不画箭头、不响应。
    与管口一致：松手再打开，避免触控按下弹出、松手立刻收起。
    """

    def __init__(self, table, stats_widget):
        super().__init__(table)
        self.table = table
        self.stats_widget = stats_widget
        self._pending_arrow_cell = None

    def _clear_pending_arrow(self):
        self._pending_arrow_cell = None

    def _open_arrow_combo(self, sw, row, col):
        sw._attachment_ignore_cell_click = True
        sw._attachment_arrow_click_cell = (row, col)
        handle_attachment_cell_click(sw, row, col, force_open=True)

        def _clear_ignore():
            try:
                if sw is None or sip.isdeleted(sw) or getattr(sw, "_pipe_closing", False):
                    return
                sw._attachment_ignore_cell_click = False
            except RuntimeError:
                pass

        QTimer.singleShot(0, _clear_ignore)

    def eventFilter(self, obj, event):
        try:
            if self.table is None or sip.isdeleted(self.table):
                return False
            if obj is not self.table.viewport():
                return False
        except RuntimeError:
            return False

        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            pending = self._pending_arrow_cell
            if pending is None:
                return False
            self._pending_arrow_cell = None
            sw = self.stats_widget
            try:
                if sw is None or sip.isdeleted(sw) or getattr(sw, "_pipe_closing", False):
                    return True
            except RuntimeError:
                return True
            row, col = pending
            index = self.table.indexAt(event.pos())
            if not index.isValid() or index.row() != row or index.column() != col:
                sw._attachment_ignore_cell_click = False
                return True
            self._open_arrow_combo(sw, row, col)
            return True

        if event.type() != QEvent.MouseButtonPress or event.button() != Qt.LeftButton:
            return False

        sw = self.stats_widget
        try:
            if sw is None or sip.isdeleted(sw) or getattr(sw, "_pipe_closing", False):
                return False
        except RuntimeError:
            return False

        pos = event.pos()
        index = self.table.indexAt(pos)
        if not index.isValid() or index.row() <= 0:
            self._clear_pending_arrow()
            return False

        if index.column() not in _attachment_dropdown_columns(sw):
            self._clear_pending_arrow()
            return False
        if not _attachment_cell_is_editable(self.table, index.row(), index.column()):
            self._clear_pending_arrow()
            return False

        delegate = self.table.itemDelegateForColumn(index.column())
        if not isinstance(delegate, ComboBoxDelegate):
            self._clear_pending_arrow()
            return False
        if not getattr(delegate, "show_dropdown_arrow", True):
            self._clear_pending_arrow()
            return False
        if not _should_paint_pipe_combo_arrow(index):
            self._clear_pending_arrow()
            return False

        cell_rect = self.table.visualRect(index)
        if not pipe_combo_arrow_rect(cell_rect).contains(pos):
            self._clear_pending_arrow()
            return False

        sw._attachment_ignore_cell_click = True
        self._pending_arrow_cell = (index.row(), index.column())

        sel_model = self.table.selectionModel()
        selected = self.table.selectedIndexes()
        already = any(
            i.row() == index.row() and i.column() == index.column() for i in selected
        )
        if already:
            sel_model.setCurrentIndex(index, QItemSelectionModel.NoUpdate)
        elif event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
            sel_model.select(
                index, QItemSelectionModel.Select | QItemSelectionModel.Current
            )
        else:
            self.table.setCurrentCell(index.row(), index.column())

        try:
            update_attachment_bulk_assign_state(sw)
        except Exception:
            pass

        bulk_rows = list(getattr(sw, "attachment_bulk_assign_rows", []) or [])
        bulk_col = getattr(sw, "attachment_bulk_assign_target_column", None)
        if bulk_col == index.column() and len(bulk_rows) > 1:
            sw._attachment_bulk_rows_snapshot = bulk_rows
            sw._attachment_bulk_edit_active = True
        else:
            sw._attachment_bulk_rows_snapshot = []
            sw._attachment_bulk_edit_active = False

        return True


# 全表至多各出现一次的元件名称；其余类型可多件，重名时自动加 1、2… 后缀区分
ATTACHMENT_SINGLETON_ELEMENT_NAMES = frozenset({"铭牌"})

# 需要“重复时自动编号”的可重复元件名称：
# - 首个保留原名（如 卧式设备板式吊耳）
# - 出现第二个同名时，首个自动改为 卧式设备板式吊耳1，新增为 卧式设备板式吊耳2
ATTACHMENT_AUTO_INDEXED_REPEATABLE_NAMES = frozenset({
    "鞍式支座",
    "卧式设备板式吊耳",
    "轴式吊耳",
    "保温支撑环",
    "保温支撑板",
    "加强圈",
})
# 元件类型全表同步的家族（同名/同名+数字）：改任一成员类型则全家同步
ATTACHMENT_SYNC_COMPONENT_TYPE_BASES = frozenset({
    "卧式设备板式吊耳",
    "轴式吊耳",
    "鞍式支座",
})
# 家族数量上限（超出则不允许再新建/复制）
ATTACHMENT_FAMILY_MAX_COUNT = {
    "鞍式支座": 2,
}


def _attachment_repeatable_base(name: str):
    """若属于自动编号家族，返回基名；否则 None。"""
    text = (name or "").strip()
    if not text:
        return None
    for base in ATTACHMENT_AUTO_INDEXED_REPEATABLE_NAMES:
        if text == base or re.match(rf"^{re.escape(base)}\d+$", text):
            return base
    return None


def _attachment_family_count(table, base: str, skip_row=None) -> int:
    """统计某自动编号家族已有行数（可跳过当前行）。"""
    if table is None or not base:
        return 0
    count = 0
    for r in range(1, table.rowCount()):
        if skip_row is not None and r == skip_row:
            continue
        it = table.item(r, ATTACHMENT_COMPONENT_NAME_COLUMN)
        txt = it.text().strip() if it else ""
        if _attachment_repeatable_base(txt) == base:
            count += 1
    return count


def attachment_family_add_blocked_message(table, proposed: str, skip_row=None):
    """
    若该家族已达上限，返回提示文案；否则 None。
    proposed 可以是基名或「基名+数字」。
    """
    base = _attachment_repeatable_base(proposed) or (
        proposed.strip() if proposed and proposed.strip() in ATTACHMENT_FAMILY_MAX_COUNT else None
    )
    if not base:
        return None
    limit = ATTACHMENT_FAMILY_MAX_COUNT.get(base)
    if not limit:
        return None
    if _attachment_family_count(table, base, skip_row=skip_row) >= limit:
        return f"{base}最多{limit}个。"
    return None


def _attachment_sync_component_type_base(name: str):
    """若属于需同步元件类型的家族，返回基名；否则 None。"""
    text = (name or "").strip()
    if not text:
        return None
    for base in ATTACHMENT_SYNC_COMPONENT_TYPE_BASES:
        if text == base or re.match(rf"^{re.escape(base)}\d+$", text):
            return base
    return None


def _attachment_family_rows_for_base(table, base: str):
    """返回元件名称属于该基名家族的数据行号列表。"""
    rows = []
    if table is None or not base:
        return rows
    for r in range(1, table.rowCount()):
        it = table.item(r, ATTACHMENT_COMPONENT_NAME_COLUMN)
        txt = it.text().strip() if it else ""
        if _attachment_sync_component_type_base(txt) == base:
            rows.append(r)
    return rows


def _attachment_family_existing_component_type(table, base: str, skip_row=None):
    """取家族中其它行已有非空元件类型（优先靠前行）。"""
    for r in _attachment_family_rows_for_base(table, base):
        if skip_row is not None and r == skip_row:
            continue
        it = table.item(r, ATTACHMENT_COL_COMPONENT_TYPE)
        text = it.text().strip() if it else ""
        if text:
            return text
    return ""


def apply_attachment_family_component_type(stats_widget, base: str, type_value: str):
    """将某家族所有行的元件类型写成同一值。"""
    table = getattr(stats_widget, "tableWidget_attachment", None)
    if table is None or not base:
        return
    type_value = (type_value or "").strip()
    rows = _attachment_family_rows_for_base(table, base)
    if not rows:
        return
    prev = getattr(stats_widget, "suppress_cell_change", False)
    stats_widget.suppress_cell_change = True
    try:
        for r in rows:
            item = table.item(r, ATTACHMENT_COL_COMPONENT_TYPE)
            if item is None:
                item = QTableWidgetItem("")
                item.setTextAlignment(Qt.AlignCenter)
                # 有元件名称时类型列应可编辑
                name_it = table.item(r, ATTACHMENT_COMPONENT_NAME_COLUMN)
                has_name = bool(name_it and name_it.text().strip())
                flags = (
                    Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled
                    if has_name
                    else Qt.ItemIsSelectable | Qt.ItemIsEnabled
                )
                item.setFlags(flags)
                table.setItem(r, ATTACHMENT_COL_COMPONENT_TYPE, item)
            if item.text().strip() != type_value:
                item.setText(type_value)
                item.setTextAlignment(Qt.AlignCenter)
    finally:
        stats_widget.suppress_cell_change = prev


def _maybe_inherit_family_component_type(stats_widget, row, element_name: str):
    """
    新增板式吊耳等家族成员时：若已有其它成员的元件类型，则带入并全家对齐。
    界面上尚无该家族时不做处理，留给用户自选类型。
    """
    base = _attachment_sync_component_type_base(element_name)
    if not base:
        return
    table = getattr(stats_widget, "tableWidget_attachment", None)
    if table is None:
        return
    existing = _attachment_family_existing_component_type(table, base, skip_row=row)
    if not existing:
        return
    apply_attachment_family_component_type(stats_widget, base, existing)


# 新建时备注列默认值（仅空备注时写入，不覆盖已有内容）
ATTACHMENT_DEFAULT_REMARK_BY_BASE = {
    "卧式设备板式吊耳": "布置形式：Ⅱ",
}
# 鞍式支座备注按序号：首个(鞍式支座/鞍式支座1)=固定鞍座，第2个(鞍式支座2)=滑动鞍座
ATTACHMENT_SADDLE_DEFAULT_REMARK_BY_INDEX = {
    1: "固定鞍座",
    2: "滑动鞍座",
}
# 新建时周向方位默认值（仅空值时写入；校验失败不再回填）
ATTACHMENT_DEFAULT_CIRCUMFERENTIAL_BY_BASE = {
    "鞍式支座": "180.0",
    "铭牌": "90.0",
}
# 新建时元件类型默认值（仅空类型时写入；同步家族优先走继承逻辑）
ATTACHMENT_DEFAULT_COMPONENT_TYPE_BY_BASE = {
    "保温支撑环": "与容器焊接",
    "保温支撑板": "与支耳焊接连接",
    "铭牌": "/",
    "加强圈": "外加强圈",
}
# 元件类型从「元件附加参数合并表」联动的家族（如鞍式支座 → 支座型号）
ATTACHMENT_LINKED_COMPONENT_TYPE_BASES = frozenset({"鞍式支座"})


def _match_attachment_name_base(element_name: str, mapping):
    """按「原名 / 原名+数字」匹配映射表或集合中的基名。"""
    text = (element_name or "").strip()
    if not text or mapping is None:
        return None
    keys = mapping.keys() if isinstance(mapping, dict) else mapping
    for name_base in keys:
        if text == name_base or re.match(rf"^{re.escape(name_base)}\d+$", text):
            return name_base
    return None


def _set_attachment_cell_text_if_empty(stats_widget, row, column, text: str):
    """单元格为空时写入 text（带 suppress，并补齐可编辑 flags）。"""
    table = getattr(stats_widget, "tableWidget_attachment", None)
    if table is None or row <= 0 or not text:
        return False
    item = table.item(row, column)
    if item is not None and item.text().strip():
        return False
    prev = getattr(stats_widget, "suppress_cell_change", False)
    stats_widget.suppress_cell_change = True
    try:
        if item is None:
            item = QTableWidgetItem("")
            item.setTextAlignment(Qt.AlignCenter)
            name_it = table.item(row, ATTACHMENT_COMPONENT_NAME_COLUMN)
            has_name = bool(name_it and name_it.text().strip())
            item.setFlags(
                Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled
                if has_name
                else Qt.ItemIsSelectable | Qt.ItemIsEnabled
            )
            table.setItem(row, column, item)
        item.setText(text)
        item.setTextAlignment(Qt.AlignCenter)
    finally:
        stats_widget.suppress_cell_change = prev
    return True


def query_saddle_support_model_from_merged_para(product_id):
    """
    从产品设计活动表_元件附加参数合并表取鞍式支座的「支座型号」。
    各 Tab 型号一致，取任意一条非空即可；无则返回 None。
    """
    if not product_id:
        return None
    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config_2)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        # 先定位存在「支座型式=鞍式支座」的 (元件ID, Tab分类)，再取同组「支座型号」
        cursor.execute(
            """
            SELECT m.`参数值` AS model_value
            FROM 产品设计活动表_元件附加参数合并表 AS t
            INNER JOIN 产品设计活动表_元件附加参数合并表 AS m
                ON m.`产品ID` = t.`产品ID`
               AND m.`元件ID` = t.`元件ID`
               AND IFNULL(m.`Tab分类`, '') = IFNULL(t.`Tab分类`, '')
            WHERE t.`产品ID` = %s
              AND t.`参数名称` = '支座型式'
              AND TRIM(t.`参数值`) = '鞍式支座'
              AND m.`参数名称` = '支座型号'
              AND TRIM(IFNULL(m.`参数值`, '')) <> ''
            LIMIT 1
            """,
            (product_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        model = str(row.get("model_value") or "").strip()
        return model or None
    except Exception as e:
        print(f"[附件] 查询鞍式支座型号失败: {e}")
        return None
    finally:
        try:
            cursor and cursor.close()
        except Exception:
            pass
        try:
            conn and conn.close()
        except Exception:
            pass


def collect_attachment_saddle_component_type(table):
    """从附件表取鞍式支座家族的非空元件类型（全表已同步，取第一条）。"""
    if table is None:
        return None
    last = table.rowCount() - 1
    for row in range(1, max(1, last)):
        name_item = table.item(row, ATTACHMENT_COMPONENT_NAME_COLUMN)
        name = name_item.text().strip() if name_item else ""
        if _match_attachment_name_base(name, ATTACHMENT_LINKED_COMPONENT_TYPE_BASES) != "鞍式支座":
            continue
        type_item = table.item(row, ATTACHMENT_COL_COMPONENT_TYPE)
        text = type_item.text().strip() if type_item else ""
        if text:
            return text
    return None


def sync_attachment_saddle_type_to_merged_para(product_id, component_type):
    """附件保存后：把鞍式支座元件类型写回合并表各 Tab 的「支座型号」。空值不覆盖。"""
    component_type = (component_type or "").strip()
    if not product_id or not component_type:
        return
    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config_2)
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE 产品设计活动表_元件附加参数合并表 AS m
            INNER JOIN 产品设计活动表_元件附加参数合并表 AS t
                ON m.`产品ID` = t.`产品ID`
               AND m.`元件ID` = t.`元件ID`
               AND IFNULL(m.`Tab分类`, '') = IFNULL(t.`Tab分类`, '')
            SET m.`参数值` = %s
            WHERE m.`产品ID` = %s
              AND m.`参数名称` = '支座型号'
              AND t.`参数名称` = '支座型式'
              AND TRIM(t.`参数值`) = '鞍式支座'
            """,
            (component_type, product_id),
        )
        conn.commit()
    except Exception as e:
        print(f"[附件保存] 回写鞍式支座型号失败: {e}")
        try:
            conn and conn.rollback()
        except Exception:
            pass
    finally:
        try:
            cursor and cursor.close()
        except Exception:
            pass
        try:
            conn and conn.close()
        except Exception:
            pass


def sync_merged_saddle_model_to_attachment(product_id):
    """元件定义保存后：把合并表「支座型号」写到附件表鞍式支座的元件类型。型号为空则不覆盖。"""
    model = query_saddle_support_model_from_merged_para(product_id)
    if not product_id or not model:
        return
    conn = None
    cursor = None
    try:
        conn = get_connection(**db_config_2)
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE 产品设计活动表_附件表
            SET `元件类型` = %s
            WHERE `产品ID` = %s
              AND `元件名称` REGEXP '^鞍式支座[0-9]*$'
            """,
            (model, product_id),
        )
        conn.commit()
    except Exception as e:
        print(f"[元件保存] 回写附件鞍式支座类型失败: {e}")
        try:
            conn and conn.rollback()
        except Exception:
            pass
    finally:
        try:
            cursor and cursor.close()
        except Exception:
            pass
        try:
            conn and conn.close()
        except Exception:
            pass


def refresh_attachment_saddle_type_from_merged_para(stats_widget):
    """
    切到「附件定义」时：用合并表已保存的「支座型号」刷新界面鞍式支座元件类型。
    仅改类型列；型号为空则不改，避免冲掉其它未保存编辑。
    """
    if stats_widget is None or not getattr(stats_widget, "is_container_product", False):
        return
    product_id = getattr(stats_widget, "product_id", None)
    model = query_saddle_support_model_from_merged_para(product_id)
    if not model:
        return
    apply_attachment_family_component_type(stats_widget, "鞍式支座", model)


def _attachment_saddle_name_index(element_name: str):
    """鞍式支座名称序号：原名或 *1 → 1，*2 → 2；非鞍式返回 None。"""
    text = (element_name or "").strip()
    if text == "鞍式支座":
        return 1
    m = re.match(r"^鞍式支座(\d+)$", text)
    if m:
        return int(m.group(1))
    return None


def _maybe_fill_default_remark(stats_widget, row, element_name: str):
    """按元件家族/鞍式序号填入备注默认值（备注为空时）。"""
    saddle_idx = _attachment_saddle_name_index(element_name)
    if saddle_idx is not None:
        default_remark = ATTACHMENT_SADDLE_DEFAULT_REMARK_BY_INDEX.get(saddle_idx) or ""
        if default_remark:
            _set_attachment_cell_text_if_empty(
                stats_widget, row, ATTACHMENT_COL_REMARK, default_remark
            )
        return

    base = _match_attachment_name_base(element_name, ATTACHMENT_DEFAULT_REMARK_BY_BASE)
    if not base:
        return
    default_remark = ATTACHMENT_DEFAULT_REMARK_BY_BASE.get(base) or ""
    _set_attachment_cell_text_if_empty(
        stats_widget, row, ATTACHMENT_COL_REMARK, default_remark
    )


def _maybe_fill_default_circumferential(stats_widget, row, element_name: str):
    """鞍式支座默认 180、铭牌默认 90（周向为空时写入）。"""
    base = _match_attachment_name_base(
        element_name, ATTACHMENT_DEFAULT_CIRCUMFERENTIAL_BY_BASE
    )
    if not base:
        return
    default_value = ATTACHMENT_DEFAULT_CIRCUMFERENTIAL_BY_BASE.get(base) or ""
    _set_attachment_cell_text_if_empty(
        stats_widget, row, ATTACHMENT_COL_CIRCUMFERENTIAL, default_value
    )


def _maybe_fill_default_belong_and_axial_base(stats_widget, row, element_name: str):
    """
    非保温支撑环：所属元件默认「圆筒」，轴向定位基准默认「左基准线」（空才写）。
    保温支撑环可选手动选封头，不自动带这两项。
    """
    if not (element_name or "").strip():
        return
    if _attachment_is_insulation_ring_name(element_name):
        return
    _set_attachment_cell_text_if_empty(
        stats_widget, row, ATTACHMENT_COL_BELONG, "圆筒"
    )
    _set_attachment_cell_text_if_empty(
        stats_widget, row, ATTACHMENT_COL_AXIAL_BASE, "左基准线"
    )


def _maybe_fill_default_component_type(stats_widget, row, element_name: str):
    """按元件家族基名填入元件类型默认值（类型为空时）。"""
    # 鞍式支座：从元件定义合并表联动「支座型号」
    linked_base = _match_attachment_name_base(
        element_name, ATTACHMENT_LINKED_COMPONENT_TYPE_BASES
    )
    if linked_base == "鞍式支座":
        product_id = getattr(stats_widget, "product_id", None)
        model = query_saddle_support_model_from_merged_para(product_id)
        if model:
            _set_attachment_cell_text_if_empty(
                stats_widget, row, ATTACHMENT_COL_COMPONENT_TYPE, model
            )
        return

    base = _match_attachment_name_base(
        element_name, ATTACHMENT_DEFAULT_COMPONENT_TYPE_BY_BASE
    )
    if not base:
        return
    default_type = ATTACHMENT_DEFAULT_COMPONENT_TYPE_BY_BASE.get(base) or ""
    _set_attachment_cell_text_if_empty(
        stats_widget, row, ATTACHMENT_COL_COMPONENT_TYPE, default_type
    )


# ================= 附件批量赋值（多选行：所属元件/轴向基准/距离/周向方位）=================
def update_attachment_bulk_assign_state(stats_widget):
    """
    附件表批量赋值状态跟踪：
    - 所属元件、轴向定位基准、轴向定位距离、周向方位
    - 下拉列：可选项取交集（无交集则不进入批量，仍可多选高亮单格改）
    - 周向方位：纯输入，有有效多选行即可批量
    - 封头锁定不可编辑格不参与批量
    """
    table = getattr(stats_widget, "tableWidget_attachment", None)
    if table is None:
        return

    # 批量编辑保护：仍在该批量列上编辑时用快照保住多选
    if getattr(stats_widget, "_attachment_bulk_edit_active", False):
        snap = list(getattr(stats_widget, "_attachment_bulk_rows_snapshot", []) or [])
        col = getattr(stats_widget, "attachment_bulk_assign_target_column", None)
        current_col = table.currentColumn()
        selected_indexes = table.selectedIndexes()
        selected_cols = {idx.column() for idx in selected_indexes}
        still_on_bulk_col = (
            col is not None
            and current_col == col
            and (not selected_cols or selected_cols == {col})
        )
        editing = still_on_bulk_col and table.state() == QAbstractItemView.EditingState
        if still_on_bulk_col and editing and len(snap) > 1:
            stats_widget.attachment_bulk_assign_rows = snap
            stats_widget.attachment_bulk_assign_target_column = col
            return
        _clear_attachment_bulk_edit_guard(stats_widget)

    current_col = table.currentColumn()
    target_columns = _attachment_bulk_assign_columns()
    if current_col not in target_columns:
        stats_widget.attachment_bulk_assign_target_column = None
        stats_widget.attachment_bulk_assign_rows = []
        return

    selected_indexes = table.selectedIndexes()
    if not selected_indexes:
        stats_widget.attachment_bulk_assign_target_column = None
        stats_widget.attachment_bulk_assign_rows = []
        return

    selected_rows = sorted({idx.row() for idx in selected_indexes})
    last_row = table.rowCount() - 1
    if last_row in selected_rows:
        stats_widget.attachment_bulk_assign_target_column = None
        stats_widget.attachment_bulk_assign_rows = []
        return

    # 过滤：元件名称已填 + 当前列可编辑（排除封头锁定格）
    valid_rows = []
    for r in selected_rows:
        if r <= 0:
            continue
        name_item = table.item(r, ATTACHMENT_COMPONENT_NAME_COLUMN)
        if not (name_item and name_item.text().strip()):
            continue
        cell_item = table.item(r, current_col)
        if cell_item is not None and not (cell_item.flags() & Qt.ItemIsEditable):
            continue
        valid_rows.append(r)

    if len(valid_rows) < 2:
        stats_widget.attachment_bulk_assign_target_column = None
        stats_widget.attachment_bulk_assign_rows = []
        return

    selected_columns = {idx.column() for idx in selected_indexes}
    if len(selected_columns) > 1 or current_col not in selected_columns:
        stats_widget.attachment_bulk_assign_target_column = None
        stats_widget.attachment_bulk_assign_rows = []
        return

    selected_rows_in_current_col = {
        idx.row() for idx in selected_indexes if idx.column() == current_col
    }
    if not set(valid_rows).issubset(selected_rows_in_current_col):
        stats_widget.attachment_bulk_assign_target_column = None
        stats_widget.attachment_bulk_assign_rows = []
        return

    if current_col in ATTACHMENT_PLAIN_BULK_COLUMNS:
        pass  # 周向方位：有有效多选行即可
    else:
        options = compute_attachment_intersection_options(
            stats_widget, current_col, valid_rows
        )
        if not options:
            stats_widget.attachment_bulk_assign_target_column = None
            stats_widget.attachment_bulk_assign_rows = []
            _clear_attachment_bulk_edit_guard(stats_widget)
            return

    stats_widget.attachment_bulk_assign_target_column = current_col
    stats_widget.attachment_bulk_assign_rows = valid_rows


def apply_attachment_bulk_assign_value_immediate(stats_widget, column, rows, value):
    table = getattr(stats_widget, "tableWidget_attachment", None)
    if table is None:
        return
    try:
        if hasattr(stats_widget, "suppress_cell_change"):
            stats_widget.suppress_cell_change = True
        for row_idx in rows:
            if column in ATTACHMENT_HEAD_LOCK_COLUMNS and attachment_cell_is_head_locked(
                table, row_idx, column
            ):
                continue
            item = table.item(row_idx, column)
            if not item:
                item = QTableWidgetItem("")
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_idx, column, item)
            item.setText(value)
            item.setTextAlignment(Qt.AlignCenter)
            if column == ATTACHMENT_COL_BELONG:
                if not hasattr(stats_widget, "attachment_belong_old_values"):
                    stats_widget.attachment_belong_old_values = {}
                stats_widget.attachment_belong_old_values[row_idx] = value
    finally:
        if hasattr(stats_widget, "suppress_cell_change"):
            stats_widget.suppress_cell_change = False
    # 所属元件变更后同步封头类列锁定（单选/批量共用此入口）
    if column == ATTACHMENT_COL_BELONG:
        for row_idx in rows:
            apply_attachment_row_column_locks_by_belong(stats_widget, row_idx)


def _run_bulk_handle_attachment_cell_changed(stats_widget, column, rows, product_id):
    """批量写入后逐行跑校验/联动（周向方位等）。"""
    for r in rows:
        try:
            handle_attachment_cell_changed(stats_widget, r, column, product_id)
        except Exception:
            pass


def _existing_attachment_element_names(table, skip_row: int):
    """除 skip_row 外，所有数据行第 1 列非空名称集合。"""
    out = set()
    for r in range(1, table.rowCount()):
        if r == skip_row:
            continue
        it = table.item(r, ATTACHMENT_COMPONENT_NAME_COLUMN)
        if it and it.text().strip():
            out.add(it.text().strip())
    return out


def validate_attachment_element_name(table, row, proposed: str):
    """
    校验并解析元件名称。
    :return: (是否允许, 错误说明或 None, 最终应写入的名称)
    """
    proposed = (proposed or "").strip()
    if not proposed:
        return True, None, proposed

    existing = _existing_attachment_element_names(table, row)

    if proposed in ATTACHMENT_SINGLETON_ELEMENT_NAMES:
        if proposed in existing:
            return (
                False,
                f"已有「{proposed}」此元件，铭牌唯一。",
                proposed,
            )
        return True, None, proposed

    # 可重复并“重复时自动编号”：
    # - 首个保留原名
    # - 第二个同名出现时，将已有原名自动改为 name1，当前为 name2
    if proposed in ATTACHMENT_AUTO_INDEXED_REPEATABLE_NAMES:
        blocked = attachment_family_add_blocked_message(table, proposed, skip_row=row)
        if blocked:
            return False, blocked, proposed
        # 1) 首个：没有同名/编号时，保留原名
        has_same_family = False
        plain_row = None
        for r in range(1, table.rowCount()):
            if r == row:
                continue
            it = table.item(r, ATTACHMENT_COMPONENT_NAME_COLUMN)
            txt = it.text().strip() if it else ""
            if not txt:
                continue
            if txt == proposed or re.match(rf"^{re.escape(proposed)}\d+$", txt):
                has_same_family = True
            if txt == proposed:
                plain_row = r
        if not has_same_family:
            return True, None, proposed

        # 2) 若存在一个“原名”行，先自动改成 name1（若 name1 已占用则顺延）
        if plain_row is not None:
            n_plain = 1
            candidate_plain = f"{proposed}{n_plain}"
            while candidate_plain in existing:
                n_plain += 1
                candidate_plain = f"{proposed}{n_plain}"
            plain_item = table.item(plain_row, ATTACHMENT_COMPONENT_NAME_COLUMN)
            if plain_item is None:
                plain_item = QTableWidgetItem("")
                plain_item.setTextAlignment(Qt.AlignCenter)
                table.setItem(plain_row, ATTACHMENT_COMPONENT_NAME_COLUMN, plain_item)
            table.blockSignals(True)
            try:
                plain_item.setFlags(ATTACHMENT_COMPONENT_NAME_ITEM_FLAGS)
                plain_item.setText(candidate_plain)
            finally:
                table.blockSignals(False)
            existing.discard(proposed)
            existing.add(candidate_plain)

        # 3) 当前新增行取下一个可用序号
        n_new = 1
        candidate_new = f"{proposed}{n_new}"
        while candidate_new in existing:
            n_new += 1
            candidate_new = f"{proposed}{n_new}"
        return True, None, candidate_new

    # 若用户/复制等路径传入了“名称+数字”，按数字递增去重（避免 1 -> 11）
    m = re.match(r"^(.*?)(\d+)$", proposed)
    if m:
        base, tail = m.group(1), m.group(2)
        if base in ATTACHMENT_AUTO_INDEXED_REPEATABLE_NAMES:
            num = int(tail)
            candidate = f"{base}{num}"
            while candidate in existing:
                num += 1
                candidate = f"{base}{num}"
            return True, None, candidate

    if proposed not in existing:
        return True, None, proposed

    n = 1
    while f"{proposed}{n}" in existing:
        n += 1
    return True, None, f"{proposed}{n}"


def _normalize_last_repeatable_element_name(table):
    """
    可重复家族归一：
    当某家族（卧式设备板式吊耳/保温支撑环/保温支撑板）仅剩一个成员且名称为“原名+数字”时，
    自动改回原名（例如 卧式设备板式吊耳1 -> 卧式设备板式吊耳）。
    """
    table.blockSignals(True)
    try:
        for base in ATTACHMENT_AUTO_INDEXED_REPEATABLE_NAMES:
            matched = []
            for r in range(1, table.rowCount()):
                it = table.item(r, ATTACHMENT_COMPONENT_NAME_COLUMN)
                txt = it.text().strip() if it else ""
                if not txt:
                    continue
                if txt == base or re.match(rf"^{re.escape(base)}\d+$", txt):
                    matched.append((r, txt))

            if len(matched) == 1:
                only_row, only_name = matched[0]
                if only_name != base:
                    only_item = table.item(only_row, ATTACHMENT_COMPONENT_NAME_COLUMN)
                    if only_item is None:
                        only_item = QTableWidgetItem("")
                        only_item.setTextAlignment(Qt.AlignCenter)
                        table.setItem(only_row, ATTACHMENT_COMPONENT_NAME_COLUMN, only_item)
                    only_item.setFlags(ATTACHMENT_COMPONENT_NAME_ITEM_FLAGS)
                    only_item.setText(base)
    finally:
        table.blockSignals(False)


def _finish_attachment_element_name_cell(stats_widget, row, proposed: str):
    """
    将第 row 行元件名称列设为校验后的结果，并同步占位行/可编辑状态。
    proposed 为意图名称（图示按钮或 cellChanged 传入）。
    """
    from modules.guankoudingyi.funcs.funcs_pipe_table import check_last_attachment_row_and_add_new

    table = stats_widget.tableWidget_attachment
    item = table.item(row, ATTACHMENT_COMPONENT_NAME_COLUMN)
    if item is None:
        item = QTableWidgetItem("")
        item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, ATTACHMENT_COMPONENT_NAME_COLUMN, item)

    proposed = (proposed or "").strip()
    current_text = item.text().strip()
    if not proposed:
        try:
            stats_widget.suppress_cell_change = True
            item.setFlags(ATTACHMENT_COMPONENT_NAME_ITEM_FLAGS)
            item.setText("")
        finally:
            stats_widget.suppress_cell_change = False
        if hasattr(stats_widget, "update_attachment_row_editable_state"):
            stats_widget.update_attachment_row_editable_state(row)
        check_last_attachment_row_and_add_new(stats_widget)
        return
    # 规则：已有元件名称时不允许覆盖修改，只能先清空后再填（不弹窗）
    if current_text and current_text != proposed:
        return

    ok, msg, resolved = validate_attachment_element_name(table, row, proposed)
    if not ok:
        show_styled_warning(stats_widget, "元件名称", msg or "名称无效")
        try:
            stats_widget.suppress_cell_change = True
            item.setFlags(ATTACHMENT_COMPONENT_NAME_ITEM_FLAGS)
            item.setText("")
        finally:
            stats_widget.suppress_cell_change = False
    else:
        try:
            stats_widget.suppress_cell_change = True
            item.setFlags(ATTACHMENT_COMPONENT_NAME_ITEM_FLAGS)
            item.setText(resolved)
        finally:
            stats_widget.suppress_cell_change = False

    # 名称修改后，做一次“可重复家族仅剩一个时去后缀”归一
    _normalize_last_repeatable_element_name(table)

    # 板式/轴式吊耳：第 2 个起继承类型；保温支撑环/板等填类型默认值；备注默认值（含鞍式按序号）
    if ok:
        final_name = item.text().strip() if item else ""
        if final_name:
            _maybe_inherit_family_component_type(stats_widget, row, final_name)
            _maybe_fill_default_component_type(stats_widget, row, final_name)
            _maybe_fill_default_remark(stats_widget, row, final_name)
            _maybe_fill_default_belong_and_axial_base(stats_widget, row, final_name)
            _maybe_fill_default_circumferential(stats_widget, row, final_name)
            # 鞍式首件被改名为 *1 时，同步给家族各行补空备注/周向默认值
            if _attachment_saddle_name_index(final_name) is not None:
                table_ref = getattr(stats_widget, "tableWidget_attachment", None)
                if table_ref is not None:
                    for r in range(1, table_ref.rowCount()):
                        if r == row:
                            continue
                        nit = table_ref.item(r, ATTACHMENT_COMPONENT_NAME_COLUMN)
                        ntxt = nit.text().strip() if nit else ""
                        if _attachment_saddle_name_index(ntxt) is not None:
                            _maybe_fill_default_remark(stats_widget, r, ntxt)
                            _maybe_fill_default_circumferential(stats_widget, r, ntxt)

    if hasattr(stats_widget, "update_attachment_row_editable_state"):
        stats_widget.update_attachment_row_editable_state(row)
    check_last_attachment_row_and_add_new(stats_widget)


def resolve_attachment_component_name_target_row(stats_widget):
    """解析图示按钮填入的目标行（默认写入元件名称列）。"""
    table = getattr(stats_widget, "tableWidget_attachment", None)
    if table is None:
        return None
    idx = table.currentIndex()
    # 有当前行时，默认使用该行（不要求当前列必须是元件名称列）
    if idx.isValid() and idx.row() > 0:
        return idx.row()

    # 无当前行时，优先取第一条“元件名称为空”的数据行
    for r in range(1, table.rowCount()):
        it = table.item(r, ATTACHMENT_COMPONENT_NAME_COLUMN)
        txt = it.text().strip() if it else ""
        if not txt:
            return r

    # 若没有空名称行，回退到最后一行（排除表头）
    if table.rowCount() > 1:
        return table.rowCount() - 1
    return None


def on_attachment_component_picture_clicked(stats_widget, component_name: str):
    """点击图示按钮默认写入元件名称列（若当前行已占用则自动落到空白行）。"""
    from modules.guankoudingyi.funcs.funcs_pipe_table import check_last_attachment_row_and_add_new

    row = resolve_attachment_component_name_target_row(stats_widget)
    table = stats_widget.tableWidget_attachment
    if row is None:
        row = 1 if table.rowCount() > 1 else None
        if row is None:
            return

    # 若当前行已有名称（含同名）：不覆盖，自动改填到第一条空白名称行
    current_item = table.item(row, ATTACHMENT_COMPONENT_NAME_COLUMN)
    current_text = current_item.text().strip() if current_item else ""
    if current_text:
        blank_row = None
        for r in range(1, table.rowCount()):
            it = table.item(r, ATTACHMENT_COMPONENT_NAME_COLUMN)
            txt = it.text().strip() if it else ""
            if not txt:
                blank_row = r
                break
        if blank_row is None:
            check_last_attachment_row_and_add_new(stats_widget)
            for r in range(1, table.rowCount()):
                it = table.item(r, ATTACHMENT_COMPONENT_NAME_COLUMN)
                txt = it.text().strip() if it else ""
                if not txt:
                    blank_row = r
                    break
        if blank_row is not None:
            row = blank_row

    item = table.item(row, ATTACHMENT_COMPONENT_NAME_COLUMN)
    if item is None:
        item = QTableWidgetItem("")
        item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, ATTACHMENT_COMPONENT_NAME_COLUMN, item)
    # 默认聚焦到元件名称列，确保图示按钮始终写入该列
    try:
        table.setCurrentCell(row, ATTACHMENT_COMPONENT_NAME_COLUMN)
    except Exception:
        pass
    table.blockSignals(True)
    try:
        item.setFlags(ATTACHMENT_COMPONENT_NAME_ITEM_FLAGS)
    finally:
        table.blockSignals(False)
    _finish_attachment_element_name_cell(stats_widget, row, component_name)


class _AttachmentPicTooltipFilter(QObject):
    """
    图示按钮悬停提示：拦截默认 tip，用 QToolTip.showText 弹出纯文字，
    """

    def __init__(self, tip_text, parent=None):
        super().__init__(parent)
        self._tip_text = tip_text or ""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.ToolTip:
            if self._tip_text:
                # 不传带 image 样式的按钮作 parent，避免 tip 继承黑底/图标
                QToolTip.showText(event.globalPos(), self._tip_text)
            else:
                QToolTip.hideText()
            return True
        if event.type() == QEvent.Leave:
            QToolTip.hideText()
        return False


def connect_attachment_component_picture_buttons(stats_widget):
    """pic_* 按钮 → 元件名称固定文案（默认写入元件名称列，无需预先选中该列）。"""
    # 界面从左到右顺序；耳座暂禁用，不接点击
    mapping = (
        ("pic_anshizhizuo", "鞍式支座"),
        ("pic_diaoer", "卧式设备板式吊耳"),
        ("pic_zhoushidiaoer", "轴式吊耳"),
        ("pic_mingpai", "铭牌"),
        ("pic_baowenzhichengquan", "保温支撑环"),
        ("pic_baowenzhichengtiao", "保温支撑板"),
        ("pic_jiaqiangquan", "加强圈"),
        ("pic_erzuo", "耳座"),
    )
    disabled_buttons = frozenset({"pic_erzuo"})
    for attr, label in mapping:
        btn = getattr(stats_widget, attr, None)
        if btn is None:
            continue
        is_disabled = attr in disabled_buttons
        tip = f"{label}（暂不可用）" if is_disabled else label
        if is_disabled:
            # 禁用但保持正常图标色（不额外压灰）
            btn.setEnabled(False)
            btn.setStyleSheet(
                "QPushButton, QPushButton:disabled {"
                " border: none; background: transparent;"
                " image: url(:/icons/耳座.png);"
                "}"
            )
        # 与其它图示按钮一致：拦截默认 tip，避免继承按钮 image 样式出现黑底/图标残影
        btn.setToolTip(tip)
        old_filter = getattr(btn, "_attachment_pic_tip_filter", None)
        if old_filter is not None:
            try:
                btn.removeEventFilter(old_filter)
            except Exception:
                pass
        tip_filter = _AttachmentPicTooltipFilter(tip, btn)
        btn._attachment_pic_tip_filter = tip_filter
        btn.installEventFilter(tip_filter)
        try:
            btn.setStatusTip(tip)
        except Exception:
            pass
        try:
            btn.clicked.disconnect()
        except TypeError:
            pass
        if is_disabled:
            continue
        btn.clicked.connect(
            lambda _checked=False, w=stats_widget, name=label: on_attachment_component_picture_clicked(w, name)
        )


def handle_attachment_cell_click(stats_widget, row, column, force_open=False):
    """
    附件定义表单击入口（对齐管口：空白只选中，箭头/force_open 才打开下拉）。
    :param force_open: True=箭头或键盘 Enter/Tab 进入，允许打开下拉并灌选项
    禁用列（flags 无 Editable）一律不进入编辑，保持灰底禁用。
    """
    table = getattr(stats_widget, "tableWidget_attachment", None)
    if table is None:
        return

    if row <= 0:
        return

    name_item = table.item(row, 1)
    has_component_name = name_item.text().strip() != "" if name_item else False

    arrow_cell = getattr(stats_widget, "_attachment_arrow_click_cell", None)
    opened_by_arrow = arrow_cell == (row, column)
    if opened_by_arrow:
        stats_widget._attachment_arrow_click_cell = None
    allow_open = bool(force_open or opened_by_arrow)

    if not has_component_name:
        return

    # 禁用列保持禁用
    if not _attachment_cell_is_editable(table, row, column):
        return

    dropdown_cols = _attachment_dropdown_columns(stats_widget)
    is_editable_combo = _is_attachment_editable_combo_column(column)

    if column in dropdown_cols and not allow_open:
        if is_editable_combo:
            pass  # 可编辑下拉：空白进编辑
        else:
            # 纯下拉：空白只选中
            return

    # 与管口共用 ComboBoxDelegate 的展开开关
    if is_editable_combo:
        stats_widget._pipe_combo_show_popup = bool(opened_by_arrow)
    else:
        stats_widget._pipe_combo_show_popup = True

    # 与管口一致：editItem 前武装，否则 createEditor 会因未武装直接返回 None
    if column in dropdown_cols:
        _arm_pipe_combo_editor(stats_widget)

    item = table.item(row, column)
    if item is None:
        item = QTableWidgetItem()
        item.setTextAlignment(Qt.AlignCenter)
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)
        table.setItem(row, column, item)
    delegates = getattr(stats_widget, "attachment_column_delegates", {})

    if column in ATTACHMENT_PLAIN_EDIT_COLUMNS:
        if not hasattr(stats_widget, "original_cell_value_map"):
            stats_widget.original_cell_value_map = {}
        # 周向方位：批量时快照行，避免 edit 收成单格丢失多选
        is_plain_bulk = (
            column in ATTACHMENT_PLAIN_BULK_COLUMNS
            and getattr(stats_widget, "attachment_bulk_assign_target_column", None) == column
            and len(getattr(stats_widget, "attachment_bulk_assign_rows", []) or []) > 1
        )
        if is_plain_bulk:
            bulk_rows = list(stats_widget.attachment_bulk_assign_rows)
            stats_widget._attachment_bulk_rows_snapshot = bulk_rows
            stats_widget._attachment_bulk_edit_active = True
            for r in bulk_rows:
                cell = table.item(r, column)
                stats_widget.original_cell_value_map[(r, column)] = (
                    cell.text().strip() if cell else ""
                )
        elif column in ATTACHMENT_PLAIN_BULK_COLUMNS:
            stats_widget.original_cell_value_map[(row, column)] = item.text().strip()
        table.editItem(item)
        return

    def _restore_attachment_bulk_from_snapshot(col):
        is_bulk = (
            getattr(stats_widget, "attachment_bulk_assign_target_column", None) == col
            and len(getattr(stats_widget, "attachment_bulk_assign_rows", []) or []) > 1
        )
        if getattr(stats_widget, "_attachment_bulk_edit_active", False):
            snap = list(getattr(stats_widget, "_attachment_bulk_rows_snapshot", []) or [])
            if len(snap) > 1:
                stats_widget.attachment_bulk_assign_rows = snap
                stats_widget.attachment_bulk_assign_target_column = col
                is_bulk = True
        return is_bulk

    if column == ATTACHMENT_COL_BELONG:
        is_bulk_mode = _restore_attachment_bulk_from_snapshot(column)
        bulk_options = []
        if is_bulk_mode:
            bulk_options = compute_attachment_intersection_options(
                stats_widget, column, stats_widget.attachment_bulk_assign_rows
            )
            if not bulk_options:
                is_bulk_mode = False
                stats_widget.attachment_bulk_assign_target_column = None
                stats_widget.attachment_bulk_assign_rows = []
                _clear_attachment_bulk_edit_guard(stats_widget)

        if is_bulk_mode:
            def bulk_assign_callback(value):
                apply_attachment_bulk_assign_value_immediate(
                    stats_widget, column, stats_widget.attachment_bulk_assign_rows, value
                )
                _clear_attachment_bulk_edit_guard(stats_widget)

            delegate = delegates.get(column)
            if delegate:
                delegate.bulk_select_callback = bulk_assign_callback
                delegate.disable_wheel_scroll = True
                delegate.setItems(bulk_options)
            table.editItem(item)
            return

        if not hasattr(stats_widget, "attachment_belong_old_values"):
            stats_widget.attachment_belong_old_values = {}
        if row not in stats_widget.attachment_belong_old_values:
            cur = table.item(row, ATTACHMENT_COL_BELONG)
            stats_widget.attachment_belong_old_values[row] = (
                cur.text().strip() if cur else ""
            )
        options = get_attachment_belong_options_for_row(stats_widget, row)

        def belong_single_callback(value, _row=row, _col=column):
            apply_attachment_bulk_assign_value_immediate(
                stats_widget, _col, [_row], value
            )

        delegate = delegates.get(column)
        if delegate:
            delegate.bulk_select_callback = belong_single_callback
            delegate.disable_wheel_scroll = False
            delegate.setItems(options if options else ["None"])
        table.editItem(item)
        return

    if column == ATTACHMENT_COL_AXIAL_BASE:
        is_bulk_mode = _restore_attachment_bulk_from_snapshot(column)
        if is_bulk_mode:
            options = compute_attachment_intersection_options(
                stats_widget, column, stats_widget.attachment_bulk_assign_rows
            )
            if not options:
                is_bulk_mode = False
                stats_widget.attachment_bulk_assign_target_column = None
                stats_widget.attachment_bulk_assign_rows = []
                _clear_attachment_bulk_edit_guard(stats_widget)

        if is_bulk_mode:
            def bulk_assign_callback(value):
                apply_attachment_bulk_assign_value_immediate(
                    stats_widget, column, stats_widget.attachment_bulk_assign_rows, value
                )
                _clear_attachment_bulk_edit_guard(stats_widget)

            delegate = delegates.get(column)
            if delegate:
                delegate.bulk_select_callback = bulk_assign_callback
                delegate.disable_wheel_scroll = True
                delegate.setItems(options if options else ["None"])
            table.editItem(item)
            return

        belong_item = table.item(row, ATTACHMENT_COL_BELONG)
        attachment_belong = belong_item.text().strip() if belong_item else None
        options = get_attachment_axial_position_base_options(
            getattr(stats_widget, "product_id", None), attachment_belong
        )
        delegate = delegates.get(column)
        if delegate:
            delegate.bulk_select_callback = None
            delegate.disable_wheel_scroll = False
            delegate.setItems(options if options else ["None"])
        table.editItem(item)
        return

    if column == ATTACHMENT_COL_AXIAL_DISTANCE:
        is_bulk_mode = _restore_attachment_bulk_from_snapshot(column)
        if is_bulk_mode:
            # 批量：不可编辑下拉，仅点选「程序推荐/居中」，禁止手输数值统一赋值
            options = compute_attachment_intersection_options(
                stats_widget, column, stats_widget.attachment_bulk_assign_rows
            )
            allowed = set(options or [])

            def bulk_assign_callback(value):
                text = str(value).strip() if value is not None else ""
                if text not in allowed:
                    return
                apply_attachment_bulk_assign_value_immediate(
                    stats_widget, column, stats_widget.attachment_bulk_assign_rows, text
                )
                _clear_attachment_bulk_edit_guard(stats_widget)

            delegate = ComboBoxDelegate(table, editable=False)
            delegate.stats_widget = stats_widget
            delegate.show_dropdown_arrow = True
            delegate.setItems(options if options else ["None"])
            delegate.bulk_select_callback = bulk_assign_callback
            delegate.disable_wheel_scroll = True
            table.setItemDelegateForColumn(column, delegate)
            stats_widget.attachment_column_delegates[column] = delegate
            table.editItem(item)
            return

        # 单选：可编辑下拉（可按行手输数值）
        options = ["程序推荐", "居中"]
        delegate = ComboBoxDelegate(table, editable=True, overwrite_on_first_key=True)
        delegate.stats_widget = stats_widget
        delegate.show_dropdown_arrow = True
        delegate.setItems(options)
        delegate.bulk_select_callback = None
        delegate.disable_wheel_scroll = False
        table.setItemDelegateForColumn(column, delegate)
        stats_widget.attachment_column_delegates[column] = delegate
        table.editItem(item)
        return

    if column == ATTACHMENT_COL_COMPONENT_TYPE:
        name_item = table.item(row, 1)
        component_name = name_item.text().strip() if name_item else ""
        options = get_attachment_component_type_options(
            component_name, product_id=getattr(stats_widget, "product_id", None)
        )
        delegate = delegates.get(column)
        if delegate:
            delegate.bulk_select_callback = None
            delegate.disable_wheel_scroll = False
            delegate.setItems(options if options else ["None"])
        table.editItem(item)
        return


def handle_attachment_cell_changed(stats_widget, row, column, product_id):
    """
    处理附件定义表 tableWidget_attachment 的单元格值改变事件。
    「所属元件」为第 3 列：封头类时锁定轴向定位基准/距离/周向方位为「/」。
    第 1 列元件名称：铭牌全表至多一个；其余类型重名时自动加 1、2… 后缀。
    """
    if getattr(stats_widget, "suppress_cell_change", False):
        return
    if row <= 0:
        return

    table = getattr(stats_widget, "tableWidget_attachment", None)
    if table is None:
        return

    if column == ATTACHMENT_COMPONENT_NAME_COLUMN:
        item = table.item(row, column)
        if not item:
            return
        _finish_attachment_element_name_cell(stats_widget, row, item.text())
        return

    item = table.item(row, column)
    if not item:
        return

    is_last_row = row == table.rowCount() - 1
    name_item = table.item(row, ATTACHMENT_COMPONENT_NAME_COLUMN)
    has_component_name = name_item.text().strip() != "" if name_item else False

    # ---------- 所属元件（第 3 列）：封头类锁定定位相关列 ----------
    if column == ATTACHMENT_COL_BELONG:
        new_value = item.text().strip() if item else ""
        if not hasattr(stats_widget, "attachment_belong_old_values"):
            stats_widget.attachment_belong_old_values = {}
        old_value = stats_widget.attachment_belong_old_values.get(row, "")
        if not old_value:
            old_value = ""

        apply_attachment_row_column_locks_by_belong(stats_widget, row)
        stats_widget.attachment_belong_old_values[row] = new_value

        # 所属元件切换 → 轴向定位基准（第 4 列），与管口第 11 列联动规则一致
        _ab_base = ATTACHMENT_COL_AXIAL_BASE
        # if new_value.endswith("封头") and old_value.endswith("圆筒"):
        #     target_item = table.item(row, _ab_base)
        #     if not target_item:
        #         target_item = QTableWidgetItem()
        #         table.setItem(row, _ab_base, target_item)
        #     target_item.setText("封头中心线")
        #     target_item.setTextAlignment(Qt.AlignCenter)
        #
        # elif new_value.endswith("圆筒") and old_value.endswith("封头"):
        #     target_item = table.item(row, _ab_base)
        #     if not target_item:
        #         target_item = QTableWidgetItem()
        #         table.setItem(row, _ab_base, target_item)
        #     target_item.setText("左基准线")
        #     target_item.setTextAlignment(Qt.AlignCenter)
        #
        # elif new_value.endswith("平盖") and old_value.endswith("封头"):
        #     target_item = table.item(row, _ab_base)
        #     if not target_item:
        #         target_item = QTableWidgetItem()
        #         table.setItem(row, _ab_base, target_item)
        #     target_item.setText("平盖中心线")
        #     target_item.setTextAlignment(Qt.AlignCenter)
        #
        # elif new_value.endswith("封头") and old_value.endswith("平盖"):
        #     target_item = table.item(row, _ab_base)
        #     if not target_item:
        #         target_item = QTableWidgetItem()
        #         table.setItem(row, _ab_base, target_item)
        #     target_item.setText("封头中心线")
        #     target_item.setTextAlignment(Qt.AlignCenter)
        #
        # elif new_value.endswith("平盖") and old_value.endswith("圆筒"):
        #     target_item = table.item(row, _ab_base)
        #     if not target_item:
        #         target_item = QTableWidgetItem()
        #         table.setItem(row, _ab_base, target_item)
        #     target_item.setText("平盖中心线")
        #     target_item.setTextAlignment(Qt.AlignCenter)
        #
        # elif new_value.endswith("圆筒") and old_value.endswith("平盖"):
        #     target_item = table.item(row, _ab_base)
        #     if not target_item:
        #         target_item = QTableWidgetItem()
        #         table.setItem(row, _ab_base, target_item)
        #     target_item.setText("左基准线")
        #     target_item.setTextAlignment(Qt.AlignCenter)
        # elif new_value.endswith("平盖") and old_value.endswith("锥壳"):
        #     target_item = table.item(row, _ab_base)
        #     if not target_item:
        #         target_item = QTableWidgetItem()
        #         table.setItem(row, _ab_base, target_item)
        #     target_item.setText("平盖中心线")
        #     target_item.setTextAlignment(Qt.AlignCenter)
        # elif new_value.endswith("封头") and old_value.endswith("锥壳"):
        #     target_item = table.item(row, _ab_base)
        #     if not target_item:
        #         target_item = QTableWidgetItem()
        #         table.setItem(row, _ab_base, target_item)
        #     target_item.setText("封头中心线")
        #     target_item.setTextAlignment(Qt.AlignCenter)
        # elif new_value.endswith("锥壳") and old_value.endswith("封头"):
        #     target_item = table.item(row, _ab_base)
        #     if not target_item:
        #         target_item = QTableWidgetItem()
        #         table.setItem(row, _ab_base, target_item)
        #     target_item.setText("左基准线")
        #     target_item.setTextAlignment(Qt.AlignCenter)
        # elif new_value.endswith("锥壳") and old_value.endswith("平盖"):
        #     target_item = table.item(row, _ab_base)
        #     if not target_item:
        #         target_item = QTableWidgetItem()
        #         table.setItem(row, _ab_base, target_item)
        #     target_item.setText("左基准线")
        #     target_item.setTextAlignment(Qt.AlignCenter)
        #
        # else:
        #     base_item = table.item(row, _ab_base)
        #     base_text = base_item.text().strip() if base_item else ""
        #     from_tubesheet = ("管板" in old_value) or (
        #         base_text in ("管程侧端面", "壳程侧端面")
        #     )
        #
        #     if new_value.endswith("圆筒") and from_tubesheet:
        #         target_item = base_item or QTableWidgetItem()
        #         if not base_item:
        #             table.setItem(row, _ab_base, target_item)
        #         target_item.setText("左基准线")
        #         target_item.setTextAlignment(Qt.AlignCenter)
        #
        #     elif new_value.endswith("封头") and from_tubesheet:
        #         target_item = base_item or QTableWidgetItem()
        #         if not base_item:
        #             table.setItem(row, _ab_base, target_item)
        #         target_item.setText("封头中心线")
        #         target_item.setTextAlignment(Qt.AlignCenter)
        #
        #     elif new_value.endswith("平盖") and from_tubesheet:
        #         target_item = base_item or QTableWidgetItem()
        #         if not base_item:
        #             table.setItem(row, _ab_base, target_item)
        #         target_item.setText("平盖中心线")
        #         target_item.setTextAlignment(Qt.AlignCenter)
        #
        #     elif new_value.endswith("管板") and old_value.endswith("平盖"):
        #         target_item = base_item or QTableWidgetItem()
        #         if not base_item:
        #             table.setItem(row, _ab_base, target_item)
        #         target_item.setText("壳程侧端面")
        #         target_item.setTextAlignment(Qt.AlignCenter)
        #
        #     elif new_value.endswith("管板") and old_value.endswith("封头"):
        #         target_item = base_item or QTableWidgetItem()
        #         if not base_item:
        #             table.setItem(row, _ab_base, target_item)
        #         target_item.setText("壳程侧端面")
        #         target_item.setTextAlignment(Qt.AlignCenter)
        #
        #     elif new_value.endswith("管板") and old_value.endswith("圆筒"):
        #         target_item = base_item or QTableWidgetItem()
        #         if not base_item:
        #             table.setItem(row, _ab_base, target_item)
        #         target_item.setText("壳程侧端面")
        #         target_item.setTextAlignment(Qt.AlignCenter)

        stats_widget.attachment_belong_old_values[row] = new_value
        return

    # ---------- 元件类型：板式吊耳家族全表同步 ----------
    if column == ATTACHMENT_COL_COMPONENT_TYPE:
        name_text = name_item.text().strip() if name_item else ""
        base = _attachment_sync_component_type_base(name_text)
        if base:
            apply_attachment_family_component_type(
                stats_widget, base, item.text().strip()
            )
        return

    # 周向方位：仅当相对编辑前旧值有改动时才批量写入，再逐行校验
    if (
        column in ATTACHMENT_PLAIN_BULK_COLUMNS
        and not getattr(stats_widget, "_attachment_bulk_plain_propagating", False)
    ):
        bulk_col = getattr(stats_widget, "attachment_bulk_assign_target_column", None)
        rows = list(
            getattr(stats_widget, "_attachment_bulk_rows_snapshot", None)
            or getattr(stats_widget, "attachment_bulk_assign_rows", None)
            or []
        )
        if bulk_col == column and len(rows) > 1 and row in rows:
            text = item.text().strip()
            original_map = getattr(stats_widget, "original_cell_value_map", {}) or {}
            old_text = original_map.get((row, column))
            if old_text is not None and text != str(old_text).strip():
                stats_widget._attachment_bulk_plain_propagating = True
                try:
                    apply_attachment_bulk_assign_value_immediate(
                        stats_widget, column, rows, text
                    )
                    _run_bulk_handle_attachment_cell_changed(
                        stats_widget, column, rows, product_id
                    )
                finally:
                    stats_widget._attachment_bulk_plain_propagating = False
                    _clear_attachment_bulk_edit_guard(stats_widget)
                return

    if column not in ATTACHMENT_VALIDATION_COLUMNS:
        return

    stats_widget.current_editing_cell = None

    if is_last_row and not has_component_name:
        return

    element_name = (
        table.item(row, ATTACHMENT_COMPONENT_NAME_COLUMN).text().strip()
        if table.item(row, ATTACHMENT_COMPONENT_NAME_COLUMN)
        else ""
    )
    belong_text = (
        table.item(row, ATTACHMENT_COL_BELONG).text().strip()
        if table.item(row, ATTACHMENT_COL_BELONG)
        else ""
    )

    # ---------- 轴向定位距离：数值须在 [0, 容器壳体长度) ----------
    if column == ATTACHMENT_COL_AXIAL_DISTANCE:
        # 封头类锁定为「/」，不校验、不改写
        if _attachment_belong_is_head(belong_text):
            _attachment_clear_error_tip(stats_widget)
            return

        input_value = item.text().strip()
        valid, result = validate_attachment_axial_position_distance(
            input_value, product_id=product_id, element_name=element_name
        )
        if not valid:
            _attachment_show_error_tip(stats_widget, result)
            # 与容器管口一致：失败时回填壳体长度的 1/2；无壳体长度则回「程序推荐」
            shell_length = get_container_shell_length(product_id)
            if shell_length is not None:
                default_value = f"{round(float(shell_length) / 2.0, 1):.1f}"
            else:
                default_value = "程序推荐"
            try:
                stats_widget.suppress_cell_change = True
                item.setText(str(default_value))
            finally:
                stats_widget.suppress_cell_change = False
            return
        _attachment_clear_error_tip(stats_widget)
        table.blockSignals(True)
        item.setText(str(result))
        table.blockSignals(False)
        return

    # ---------- 周向方位 ----------
    if column == ATTACHMENT_COL_CIRCUMFERENTIAL:
        valid, result = validate_attachment_circumferential_position(
            item.text(), element_name
        )
        if not valid:
            _attachment_show_error_tip(stats_widget, result)
            _, default_value = validate_attachment_circumferential_position(
                "", element_name
            )
            try:
                stats_widget.suppress_cell_change = True
                item.setText(str(default_value))
            finally:
                stats_widget.suppress_cell_change = False
            if hasattr(stats_widget, "original_cell_value_map"):
                stats_widget.original_cell_value_map[(row, column)] = str(default_value)
            return
        _attachment_clear_error_tip(stats_widget)
        table.blockSignals(True)
        item.setText(str(result))
        table.blockSignals(False)
        if hasattr(stats_widget, "original_cell_value_map"):
            stats_widget.original_cell_value_map[(row, column)] = str(result)

        if hasattr(stats_widget, "view") and stats_widget.view:
            stats_widget.view.set_pipe_data(stats_widget.get_all_pipe_data())
