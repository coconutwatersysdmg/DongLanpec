"""
附件定义表（tableWidget_attachment）的下拉代理、选项查询与单元格交互。
与管口表逻辑分离，对应 funcs_pipe_comboBox_value 中的管口部分。
"""
import pymysql.cursors
import re
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox, QTableWidgetItem

from modules.guankoudingyi.db_cnt import get_connection, db_config_1, db_config_2
from modules.guankoudingyi.funcs.funcs_pipe_comboBox_value import ComboBoxDelegate
from modules.guankoudingyi.funcs.funcs_pipe_table import show_styled_warning
from modules.guankoudingyi.obtain_product_type_version import get_product_type_and_version


# ---------------------------------------------------------------------------
# 附件表数值列校验（与管口表当前规则一致；独立实现便于后续单独调整）
# ---------------------------------------------------------------------------
def _attachment_set_tip(stats_widget, text="", color=None):
    """统一设置/清空底部提示条（附件校验专用）。"""
    if not hasattr(stats_widget, "line_tip"):
        return
    stats_widget.line_tip.setText(text or "")
    stats_widget.line_tip.setToolTip(text or "")
    stats_widget.line_tip.setStatusTip(text or "")
    stats_widget.line_tip.setStyleSheet(f"color: {color};" if color else "")


def _attachment_is_zero_like(text: str) -> bool:
    """'', '0', '0.0' 等视为零；非法数字按非零处理。"""
    t = (text or "").strip()
    if t in {"", "0", "0.0", "0.00"}:
        return True
    try:
        return abs(float(t)) < 1e-9
    except Exception:
        return False


def _attachment_just_turned_from_zero_to_nonzero(
    stats_widget, row: int, column: int, new_text: str
) -> bool:
    """
    原值为零样式且新值为非零样式时返回 True。
    依赖 handle_attachment_cell_click 对轴向夹角/偏心距列写入的 original_cell_value_map。
    """
    default_old = getattr(stats_widget, "original_cell_value", "")
    value_map = getattr(stats_widget, "original_cell_value_map", {})
    old_text = value_map.get((row, column), default_old)
    return _attachment_is_zero_like(old_text) and (not _attachment_is_zero_like(new_text))


def _attachment_get_nominal_diameter(product_id, belong_text):
    """偏心距、外伸高度校验用：按所属元件取管程/壳程公称直径（与管口侧逻辑一致，独立副本）。"""
    conn = None
    cursor = None
    try:
        if ("管箱" in belong_text) or ("管板" in belong_text):
            param_field = "管程数值"
        elif (
            ("壳体" in belong_text)
            or ("壳程" in belong_text)
            or ("外头盖" in belong_text)
            or ("锥壳" in belong_text)
        ):
            param_field = "壳程数值"
        else:
            return False, "无效的管口所属元件字段"

        conn = get_connection(**db_config_2)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute(
            """
            SELECT 管程数值, 壳程数值
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
        """,
            (product_id,),
        )
        result = cursor.fetchone()
        if result is None or result.get(param_field) in (None, ""):
            return False, "未获取到公称直径，须先至条件输入输入公称直径并保存"
        return True, float(result[param_field])
    except Exception as e:
        return False, f"数据库错误: {str(e)}"
    finally:
        cursor and cursor.close()
        conn and conn.close()


def validate_attachment_axial_angle(angle_text):
    """验证附件表轴向夹角输入（-90°～90°）。"""
    try:
        if not angle_text or angle_text.strip() == "":
            return True, 0.0
        angle = float(angle_text)
        if -90 <= angle <= 90:
            return True, angle
        return False, "轴向夹角必须在-90到90度之间"
    except ValueError:
        return False, "请输入有效的数字"


def validate_attachment_circumferential_position(position_text, element_name=""):
    """
    验证附件表周向方位（0°～360°）。
    element_name：当前行第 1 列「元件名称」格子的文本（如鞍式支座、铭牌），不是库里的列名，只是入参。
    空值时按 element_name 给默认角（写法类似管口侧空值分支）。
    """
    try:
        if not position_text or position_text.strip() == "":
            name = (element_name or "").strip()
            if name == "鞍式支座":
                return True, 0.0
            if name == "铭牌":
                return True, 90.0
            return True, 0.0
        position = float(position_text)
        if 0 <= position < 360:
            return True, position
        return False, "周向方位必须在0到360度之间"
    except ValueError:
        return False, "请输入有效的数字"


def validate_attachment_eccentricity(eccentricity_text, product_id, belong_text, emit_error=True):
    """验证附件表偏心距（相对公称直径一半）。"""
    try:
        if not eccentricity_text or eccentricity_text.strip() == "":
            return True, 0.0
        eccentricity = float(eccentricity_text)
        if not belong_text:
            if eccentricity == 0.0:
                return True, 0.0
            return False, "偏心距必须在-0.0到0.0之间"

        success, result_or_error = _attachment_get_nominal_diameter(product_id, belong_text)
        if not success:
            if emit_error:
                QMessageBox.warning(None, "验证错误", result_or_error)
            return False, result_or_error

        nominal_diameter = result_or_error
        max_ecc = nominal_diameter / 2
        if -max_ecc < eccentricity < max_ecc:
            return True, eccentricity
        return False, f"偏心距必须在-{max_ecc}到{max_ecc}之间"
    except ValueError:
        return False, "请输入有效的数字"


def validate_attachment_extension_height(height_text, product_id, belong_text, emit_error=True):
    """验证附件表外伸高度：可为「程序推荐」，否则不小于公称直径一半。"""
    try:
        if not height_text or height_text.strip() == "":
            return True, "程序推荐"
        if height_text.strip() == "程序推荐":
            return True, "程序推荐"
        height_val = float(height_text)
        success, result_or_error = _attachment_get_nominal_diameter(product_id, belong_text)
        if not success:
            if emit_error:
                QMessageBox.warning(None, "验证错误", result_or_error)
            return False, result_or_error
        nominal_diameter = result_or_error
        min_height = nominal_diameter / 2
        if height_val < min_height:
            return (
                False,
                f"外伸高度不能小于公称直径的一半（{min_height}mm），请核对后重新输入",
            )
        return True, height_val
    except ValueError:
        return False, "请输入有效数字或\"程序推荐\""


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


def get_attachment_component_type_options(component_name):
    """
    根据元件名称从元件库“管口元件类型表”获取“元件类型”下拉选项。
    :param component_name: 元件名称（对应表字段“对应元件”）
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
        return [row["元件类型"] for row in cursor.fetchall() if row.get("元件类型")]
    except Exception as e:
        QMessageBox.warning(None, "数据库错误", f"获取附件元件类型失败: {str(e)}")
        return []
    finally:
        cursor and cursor.close()
        conn and conn.close()


def initialize_attachment_combobox_delegates(stats_widget):
    """
    初始化附件定义表下拉框代理。
    列定义（附件表）：
    2 元件类型（下拉）
    3 所属元件（下拉）
    4 轴向定位基准（下拉）
    5 轴向定位距离mm（可编辑下拉：程序推荐/居中）
    7 间距（可编辑下拉：程序推荐）
    11 外伸高度（可编辑下拉：程序推荐）
    12 备注（可编辑下拉：固定鞍座+滑动鞍座 / 滑动鞍座+固定鞍座）
    """
    table = getattr(stats_widget, "tableWidget_attachment", None)
    if table is None:
        return

    stats_widget.attachment_column_delegates = {}

    static_columns = {
        5: ["程序推荐", "居中"],
        7: ["程序推荐"],
        11: ["程序推荐"],
        12: ["固定鞍座+滑动鞍座", "滑动鞍座+固定鞍座"],
    }
    for col, options in static_columns.items():
        delegate = ComboBoxDelegate(table, editable=True, overwrite_on_first_key=True)
        delegate.setItems(options)
        delegate.setParent(table)
        table.setItemDelegateForColumn(col, delegate)
        stats_widget.attachment_column_delegates[col] = delegate

    dynamic_columns = [2, 3, 4]
    for col in dynamic_columns:
        delegate = ComboBoxDelegate(table, editable=False)
        delegate.setItems([])
        delegate.setParent(table)
        table.setItemDelegateForColumn(col, delegate)
        stats_widget.attachment_column_delegates[col] = delegate

    stats_widget.attachment_dropdown_columns = set(static_columns.keys()) | set(dynamic_columns)


# 附件表「元件名称」列（第 1 列）：仅可选中，由图示按钮程序填入
ATTACHMENT_COMPONENT_NAME_COLUMN = 1
ATTACHMENT_COMPONENT_NAME_ITEM_FLAGS = Qt.ItemIsSelectable | Qt.ItemIsEnabled

# 全表至多各出现一次的元件名称；其余类型可多件，重名时自动加 1、2… 后缀区分
ATTACHMENT_SINGLETON_ELEMENT_NAMES = frozenset({"鞍式支座", "耳座", "铭牌"})

# 需要“重复时自动编号”的可重复元件名称：
# - 首个保留原名（如 吊耳）
# - 出现第二个同名时，首个自动改为 吊耳1，新增为 吊耳2
ATTACHMENT_AUTO_INDEXED_REPEATABLE_NAMES = frozenset({"吊耳", "保温支撑圈", "保温支撑条"})

# 附件表与管口表同规则的数值列（管口 13–16 对应附件 8–11）
ATTACHMENT_COL_BELONG = 3  # 所属元件，对应管口「管口所属元件」用于管板判断及偏心距/外伸高度校验
ATTACHMENT_COL_AXIAL_BASE = 4  # 轴向定位基准（用于识别「管板」导入场景的基准文本）
ATTACHMENT_COL_AXIAL_ANGLE = 8
ATTACHMENT_COL_CIRCUMFERENTIAL = 9
ATTACHMENT_COL_ECCENTRICITY = 10
ATTACHMENT_COL_EXTENSION_HEIGHT = 11
ATTACHMENT_VALIDATION_COLUMNS = {
    ATTACHMENT_COL_AXIAL_ANGLE,
    ATTACHMENT_COL_CIRCUMFERENTIAL,
    ATTACHMENT_COL_ECCENTRICITY,
    ATTACHMENT_COL_EXTENSION_HEIGHT,
}


# ================= 附件批量赋值（多选行，第3列）=================
def update_attachment_bulk_assign_state(stats_widget):
    """
    附件表批量赋值状态跟踪：
    - 仅支持第3列「所属元件」
    - 不做交集计算：各行可选项相同
    """
    table = getattr(stats_widget, "tableWidget_attachment", None)
    if table is None:
        return
    current_col = table.currentColumn()
    target_columns = {ATTACHMENT_COL_BELONG}
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

    # 过滤：只允许元件名称已填写的行参与批量
    valid_rows = []
    for r in selected_rows:
        if r <= 0:
            continue
        name_item = table.item(r, ATTACHMENT_COMPONENT_NAME_COLUMN)
        if name_item and name_item.text().strip():
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

    selected_rows_in_current_col = [idx.row() for idx in selected_indexes if idx.column() == current_col]
    if len(selected_rows_in_current_col) != len(valid_rows):
        stats_widget.attachment_bulk_assign_target_column = None
        stats_widget.attachment_bulk_assign_rows = []
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
            item = table.item(row_idx, column)
            if not item:
                item = QTableWidgetItem("")
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_idx, column, item)
            item.setText(value)
            item.setTextAlignment(Qt.AlignCenter)
    finally:
        if hasattr(stats_widget, "suppress_cell_change"):
            stats_widget.suppress_cell_change = False


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
                f"已有「{proposed}」此元件，耳座、鞍式支座、铭牌唯一。",
                proposed,
            )
        return True, None, proposed

    # 可重复并“重复时自动编号”：
    # - 首个保留原名
    # - 第二个同名出现时，将已有原名自动改为 name1，当前为 name2
    if proposed in ATTACHMENT_AUTO_INDEXED_REPEATABLE_NAMES:
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
    当某家族（吊耳/保温支撑圈/保温支撑条）仅剩一个成员且名称为“原名+数字”时，
    自动改回原名（例如 吊耳1 -> 吊耳）。
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
        QMessageBox.warning(stats_widget, "元件名称", msg or "名称无效")
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


def connect_attachment_component_picture_buttons(stats_widget):
    """pic_* 按钮 → 元件名称固定文案（默认写入元件名称列，无需预先选中该列）。"""
    mapping = (
        ("pic_anshizhizuo", "鞍式支座"),
        ("pic_baowenzhichengquan", "保温支撑圈"),
        ("pic_baowenzhichengtiao", "保温支撑条"),
        ("pic_diaoer", "吊耳"),
        ("pic_erzuo", "耳座"),
        ("pic_mingpai", "铭牌"),
    )
    for attr, label in mapping:
        btn = getattr(stats_widget, attr, None)
        if btn is None:
            continue
        try:
            btn.clicked.disconnect()
        except TypeError:
            pass
        btn.clicked.connect(
            lambda _checked=False, w=stats_widget, name=label: on_attachment_component_picture_clicked(w, name)
        )


def handle_attachment_cell_click(stats_widget, row, column):
    """
    附件定义表的“单击即下拉”入口。
    - 从 stats_widget.attachment_dropdown_columns 读取目标列集合
    - 与 control_last_attachment_row_editable_state / sync_attachment_row_tail_editable_by_name、
      AttachmentEmptyComponentNameEditProtector 配合
    """
    table = getattr(stats_widget, "tableWidget_attachment", None)
    if table is None:
        return

    if row <= 0:
        return

    name_item = table.item(row, 1)
    has_component_name = name_item.text().strip() != "" if name_item else False

    # 轴向夹角、偏心距：非下拉列，仅记录编辑前旧值供 cellChanged 中互斥判断（与管口 13/15 列一致）
    if column in (ATTACHMENT_COL_AXIAL_ANGLE, ATTACHMENT_COL_ECCENTRICITY):
        if has_component_name:
            cell = table.item(row, column)
            original_text = cell.text().strip() if cell else ""
            if not hasattr(stats_widget, "original_cell_value_map"):
                stats_widget.original_cell_value_map = {}
            stats_widget.original_cell_value_map[(row, column)] = original_text
            stats_widget.original_cell_value = original_text
        return

    if not has_component_name:
        return

    dropdown_cols = getattr(stats_widget, "attachment_dropdown_columns", set())
    if column not in dropdown_cols:
        return

    item = table.item(row, column)
    if item is None:
        item = QTableWidgetItem()
        item.setTextAlignment(Qt.AlignCenter)
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)
        table.setItem(row, column, item)
    delegates = getattr(stats_widget, "attachment_column_delegates", {})

    if column in (5, 7, 11, 12):
        table.editItem(item)
        return

    if column == 3:
        # 批量赋值模式：多行同列选择时，直接把所选值写入所有行（不计算交集）
        is_bulk_mode = (
            hasattr(stats_widget, "attachment_bulk_assign_target_column")
            and stats_widget.attachment_bulk_assign_target_column == column
            and hasattr(stats_widget, "attachment_bulk_assign_rows")
            and len(stats_widget.attachment_bulk_assign_rows) > 1
        )

        if is_bulk_mode:
            options = get_attachment_belong_options(getattr(stats_widget, "product_id", None))

            def bulk_assign_callback(value):
                apply_attachment_bulk_assign_value_immediate(
                    stats_widget, column, stats_widget.attachment_bulk_assign_rows, value
                )
                # 批量写入后，逐行触发所属元件联动（锁定/基准联动等）
                for rr in stats_widget.attachment_bulk_assign_rows:
                    handle_attachment_cell_changed(
                        stats_widget, rr, column, getattr(stats_widget, "product_id", None)
                    )

            delegate = delegates.get(column)
            if delegate:
                delegate.bulk_select_callback = bulk_assign_callback
                delegate.disable_wheel_scroll = True
                delegate.setItems(options if options else ["None"])
            table.editItem(item)
            return

        if not hasattr(stats_widget, "attachment_belong_old_values"):
            stats_widget.attachment_belong_old_values = {}
        if row not in stats_widget.attachment_belong_old_values:
            cur = table.item(row, ATTACHMENT_COL_BELONG)
            stats_widget.attachment_belong_old_values[row] = (
                cur.text().strip() if cur else ""
            )
        options = get_attachment_belong_options(getattr(stats_widget, "product_id", None))
        delegate = delegates.get(column)
        if delegate:
            delegate.bulk_select_callback = None
            delegate.disable_wheel_scroll = False
            delegate.setItems(options if options else ["None"])
        table.editItem(item)
        return

    if column == 4:
        belong_item = table.item(row, 3)
        attachment_belong = belong_item.text().strip() if belong_item else None
        options = get_attachment_axial_position_base_options(
            getattr(stats_widget, "product_id", None), attachment_belong
        )
        delegate = delegates.get(column)
        if delegate:
            delegate.setItems(options if options else ["None"])
        table.editItem(item)
        return

    if column == 2:
        name_item = table.item(row, 1)
        component_name = name_item.text().strip() if name_item else ""
        options = get_attachment_component_type_options(component_name)
        delegate = delegates.get(column)
        if delegate:
            delegate.setItems(options if options else ["None"])
        table.editItem(item)
        return


def handle_attachment_cell_changed(stats_widget, row, column, product_id):
    """
    处理附件定义表 tableWidget_attachment 的单元格值改变事件。
    轴向夹角(8)、周向方位(9)、偏心距(10)、外伸高度(11)的校验在本模块内独立实现（validate_attachment_*），
    便于与管口表后续分叉维护。「所属元件」为第 3 列。
    所属元件为管板时锁定第 8、10 列（轴向夹角、偏心距），不锁周向方位；离开管板时解锁并回填默认（与管口管板分支类似）。
    第 1 列元件名称：鞍式支座/耳座/铭牌全表各至多一个；其余类型重名时自动加 1、2… 后缀。
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

    # ---------- 所属元件（第 3 列）：管板时仅锁定轴向夹角、偏心距（不锁周向方位）----------
    if column == ATTACHMENT_COL_BELONG:
        new_value = item.text().strip() if item else ""
        if not hasattr(stats_widget, "attachment_belong_old_values"):
            stats_widget.attachment_belong_old_values = {}
        old_value = stats_widget.attachment_belong_old_values.get(row, "")
        if not old_value:
            old_value = ""

        if "管板" in new_value:
            try:
                stats_widget.suppress_cell_change = True
                for lock_col in (ATTACHMENT_COL_AXIAL_ANGLE, ATTACHMENT_COL_ECCENTRICITY):
                    lock_item = table.item(row, lock_col)
                    if not lock_item:
                        lock_item = QTableWidgetItem()
                        table.setItem(row, lock_col, lock_item)
                    lock_item.setText("-")
                    lock_item.setTextAlignment(Qt.AlignCenter)
                    lock_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            finally:
                stats_widget.suppress_cell_change = False
        else:
            base_item = table.item(row, ATTACHMENT_COL_AXIAL_BASE)
            base_text = base_item.text().strip() if base_item else ""
            from_tubesheet = ("管板" in old_value) or (
                base_text in ("管程侧端面", "壳程侧端面")
            )
            belong_new = new_value
            if from_tubesheet:
                for unlock_col in (ATTACHMENT_COL_AXIAL_ANGLE, ATTACHMENT_COL_ECCENTRICITY):
                    unlock_item = table.item(row, unlock_col)
                    if not unlock_item:
                        unlock_item = QTableWidgetItem()
                        table.setItem(row, unlock_col, unlock_item)
                    unlock_item.setFlags(
                        Qt.ItemIsEnabled | Qt.ItemIsEditable | Qt.ItemIsSelectable
                    )
                    # try:
                    #     stats_widget.suppress_cell_change = True
                    #     text_now = unlock_item.text().strip()
                    #     if text_now in ("", "—"):
                    #         if unlock_col == ATTACHMENT_COL_AXIAL_ANGLE:
                    #             _, default_angle = validate_attachment_axial_angle("")
                    #             unlock_item.setText(str(default_angle))
                    #         elif unlock_col == ATTACHMENT_COL_ECCENTRICITY:
                    #             _, default_ecc = validate_attachment_eccentricity(
                    #                 "", product_id, belong_new, emit_error=False
                    #             )
                    #             unlock_item.setText(str(default_ecc))
                    #     unlock_item.setTextAlignment(Qt.AlignCenter)
                    # finally:
                    #     stats_widget.suppress_cell_change = False
                _attachment_set_tip(stats_widget, "")

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

    if column not in ATTACHMENT_VALIDATION_COLUMNS:
        return

    stats_widget.current_editing_cell = None

    if is_last_row and not has_component_name:
        return

    attachment_belong = (
        table.item(row, ATTACHMENT_COL_BELONG).text().strip()
        if table.item(row, ATTACHMENT_COL_BELONG)
        else ""
    )

    # ---------- 轴向夹角（对齐管口列 13）----------
    if column == ATTACHMENT_COL_AXIAL_ANGLE:
        if "管板" in attachment_belong:
            _attachment_set_tip(stats_widget, "")
            return

        valid, result = validate_attachment_axial_angle(item.text())
        if not valid:
            _attachment_set_tip(stats_widget, result, "red")
            _, default_value = validate_attachment_axial_angle("")
            try:
                stats_widget.suppress_cell_change = True
                item.setText(str(default_value))
            finally:
                stats_widget.suppress_cell_change = False
            if hasattr(stats_widget, "original_cell_value_map"):
                stats_widget.original_cell_value_map[(row, ATTACHMENT_COL_AXIAL_ANGLE)] = str(default_value)
            return
        _attachment_set_tip(stats_widget, "")
        table.blockSignals(True)
        item.setText(str(result))
        table.blockSignals(False)

        ecc_item = table.item(row, ATTACHMENT_COL_ECCENTRICITY)
        if (
            ecc_item
            and not _attachment_is_zero_like(ecc_item.text())
            and _attachment_just_turned_from_zero_to_nonzero(
                stats_widget, row, ATTACHMENT_COL_AXIAL_ANGLE, str(result)
            )
        ):
            stats_widget.suppress_cell_change = True
            ecc_item.setText("0.0")
            stats_widget.suppress_cell_change = False
            if hasattr(stats_widget, "original_cell_value_map"):
                stats_widget.original_cell_value_map[(row, ATTACHMENT_COL_ECCENTRICITY)] = "0.0"
            show_styled_warning(
                stats_widget,
                "校验冲突",
                "因轴向夹角和偏心距被同时赋值，基于GB/T 150规则无法对此管口进行强度校核",
            )

        if hasattr(stats_widget, "original_cell_value_map"):
            stats_widget.original_cell_value_map[(row, ATTACHMENT_COL_AXIAL_ANGLE)] = str(result)

        if hasattr(stats_widget, "view") and stats_widget.view:
            stats_widget.view.set_pipe_data(stats_widget.get_all_pipe_data())

    # ---------- 周向方位（默认值随第 1 列元件名称变化；管板时不锁定本列，仍允许编辑与校验）----------
    elif column == ATTACHMENT_COL_CIRCUMFERENTIAL:
        element_name = (
            table.item(row, ATTACHMENT_COMPONENT_NAME_COLUMN).text().strip()
            if table.item(row, ATTACHMENT_COMPONENT_NAME_COLUMN)
            else ""
        )
        valid, result = validate_attachment_circumferential_position(
            item.text(), element_name
        )
        if not valid:
            _attachment_set_tip(stats_widget, result, "red")
            _, default_value = validate_attachment_circumferential_position(
                "", element_name
            )
            try:
                stats_widget.suppress_cell_change = True
                item.setText(str(default_value))
            finally:
                stats_widget.suppress_cell_change = False
            return
        _attachment_set_tip(stats_widget, "")
        table.blockSignals(True)
        item.setText(str(result))
        table.blockSignals(False)

        if hasattr(stats_widget, "view") and stats_widget.view:
            stats_widget.view.set_pipe_data(stats_widget.get_all_pipe_data())

    # ---------- 偏心距（对齐管口列 15）----------
    elif column == ATTACHMENT_COL_ECCENTRICITY:
        if "管板" in attachment_belong:
            _attachment_set_tip(stats_widget, "")
            return

        valid, result = validate_attachment_eccentricity(
            item.text(), product_id, attachment_belong, emit_error=False
        )
        if not valid:
            _attachment_set_tip(stats_widget, result, "red")
            _, default_value = validate_attachment_eccentricity(
                "", product_id, attachment_belong, emit_error=False
            )
            stats_widget.suppress_cell_change = True
            item.setText(str(default_value))
            stats_widget.suppress_cell_change = False
            if hasattr(stats_widget, "original_cell_value_map"):
                stats_widget.original_cell_value_map[(row, ATTACHMENT_COL_ECCENTRICITY)] = str(
                    default_value
                )
        else:
            _attachment_set_tip(stats_widget, "")
            table.blockSignals(True)
            item.setText(str(result))
            table.blockSignals(False)
            angle_item = table.item(row, ATTACHMENT_COL_AXIAL_ANGLE)
            if (
                angle_item
                and not _attachment_is_zero_like(angle_item.text())
                and _attachment_just_turned_from_zero_to_nonzero(
                    stats_widget, row, ATTACHMENT_COL_ECCENTRICITY, str(result)
                )
            ):
                stats_widget.suppress_cell_change = True
                angle_item.setText("0.0")
                stats_widget.suppress_cell_change = False
                if hasattr(stats_widget, "original_cell_value_map"):
                    stats_widget.original_cell_value_map[(row, ATTACHMENT_COL_AXIAL_ANGLE)] = "0.0"
                show_styled_warning(
                    stats_widget,
                    "校验冲突",
                    "因轴向夹角和偏心距被同时赋值，基于GB/T 150规则无法对此管口进行强度校核",
                )

            if hasattr(stats_widget, "original_cell_value_map"):
                stats_widget.original_cell_value_map[(row, ATTACHMENT_COL_ECCENTRICITY)] = str(result)

        if hasattr(stats_widget, "view") and stats_widget.view:
            stats_widget.view.set_pipe_data(stats_widget.get_all_pipe_data())

    # ---------- 外伸高度（对齐管口列 16）----------
    elif column == ATTACHMENT_COL_EXTENSION_HEIGHT:
        valid, result = validate_attachment_extension_height(
            item.text(), product_id, attachment_belong, emit_error=False
        )
        if not valid:
            _attachment_set_tip(stats_widget, result, "red")
            _, default_value = validate_attachment_extension_height(
                "", product_id, attachment_belong, emit_error=False
            )
            table.blockSignals(True)
            item.setText(str(default_value))
            table.blockSignals(False)
        else:
            _attachment_set_tip(stats_widget, "")
            table.blockSignals(True)
            item.setText(str(result))
            table.blockSignals(False)

        if hasattr(stats_widget, "view") and stats_widget.view:
            stats_widget.view.set_pipe_data(stats_widget.get_all_pipe_data())
