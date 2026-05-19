import re
from collections import defaultdict

from PyQt5.QtCore import Qt, QEvent, QTimer
from PyQt5.QtGui import QKeySequence, QDoubleValidator, QPalette, QColor
from PyQt5.QtWidgets import QTableWidgetItem, QHeaderView, QAbstractItemView, QApplication, QTableWidget, QShortcut, \
    QStyledItemDelegate, QStyle

from PyQt5 import QtWidgets, QtGui, QtCore
from PyQt5.QtCore import Qt

from modules.cailiaodingyi.controllers.checkcombo import CheckComboDelegate
from modules.cailiaodingyi.controllers.combo import ComboDelegate, ComboPopupEventFilter, DynamicOptionsDelegate, \
    on_material_field_changed_col, ProcessPerColumnDelegate, NonNegativeDoubleDelegate, RowFillComboDelegate, \
    BulkFillDynamicOptionsDelegate, MultiSelectRowComboDelegate, MultiSelectDynamicOptionsDelegate
from modules.cailiaodingyi.funcs.funcs_pdf_change import get_filtered_material_options, get_fastener_bolt_type_options, \
    get_fastener_component_options_by_template_id, load_updated_fastener_define_data, \
    get_fastener_root_series_options, DEBUG_VERBOSE_DEFINE_UI
from modules.condition_input.funcs.funcs_cdt_input import get_opening_weld_joint_default
from modules.cailiaodingyi.funcs.funcs_pdf_input import load_guankou_param_structure_from_db, load_dropdown_options, \
    query_unassigned_codes, query_codes_for_tab_raw,get_fastener_param_structure_from_db
from modules.cailiaodingyi.controllers.tooltip_utils import ensure_table_tooltip_updater



class _CopyPasteEventFilter(QtCore.QObject):
    def __init__(self, table, groups, row2field, row2group):
        super().__init__(table)
        self.table = table
        self.groups, self.row2field, self.row2group = groups, row2field, row2group

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.KeyPress:
            if ev.matches(QKeySequence.Copy):
                _copy_cells(self.table)
                ev.accept()
                return True
            if ev.matches(QKeySequence.Paste):
                _paste_cells(self.table, self.groups, self.row2field, self.row2group)
                ev.accept()
                return True
        return False

def install_copy_paste_shortcuts(table: QTableWidget, groups, row2field, row2group):
    # 1) 快捷键：作用于 table 以及其子控件
    sc_copy  = QShortcut(QKeySequence.Copy,  table)
    sc_paste = QShortcut(QKeySequence.Paste, table)
    sc_copy.setContext(Qt.WidgetWithChildrenShortcut)
    sc_paste.setContext(Qt.WidgetWithChildrenShortcut)
    sc_copy.activated.connect(lambda: _copy_cells(table))
    sc_paste.activated.connect(lambda: _paste_cells(table, groups, row2field, row2group))

    # 2) 事件过滤器兜底：当焦点在 viewport/子控件时也截获
    filt = _CopyPasteEventFilter(table, groups, row2field, row2group)
    table._copy_paste_filter = filt  # 防止被GC
    table.installEventFilter(filt)
    table.viewport().installEventFilter(filt)

def group_guankou_params_by_prefix(guankou_para_info: list) -> dict:

    result = {}
    multi_col_fields = defaultdict(dict)
    single_col_fields = {}

    for item in guankou_para_info:
        raw_name = str(item.get("参数名称", "")).strip()
        # ✅ 兼容 “参数值” 和 “参数数值”
        value = item.get("参数值") or item.get("参数数值") or ""

        match = re.match(r"^(.*?)([1-3])$", raw_name)
        if match:
            base_name, index = match.groups()
            multi_col_fields[base_name][int(index)] = str(value).strip()
        else:
            single_col_fields[raw_name] = str(value).strip()

    result.update(single_col_fields)
    result.update(multi_col_fields)
    return result



# —— UI 冻结：批量写表时避免频繁重绘/触发信号 ——
class FreezeUI:
    def __init__(self, *widgets):
        self.widgets = widgets
        self._states = []
    def __enter__(self):
        for w in self.widgets:
            self._states.append((w, w.signalsBlocked(), w.updatesEnabled()))
            w.blockSignals(True)
            w.setUpdatesEnabled(False)
        return self
    def __exit__(self, *args):
        # 恢复刷新并强制一次重绘
        for w, sb, ue in self._states:
            w.blockSignals(sb)
            w.setUpdatesEnabled(ue)
            try:
                w.viewport().update()
            except Exception:
                pass

# —— 重入保护：点击/联动产生的递归触发一律挡住（很关键） ——
class ReentryGuard:
    def __init__(self, host, flag="_in_right_param_table_update"):
        self.host, self.flag, self.entered = host, flag, False
    def __enter__(self):
        if getattr(self.host, self.flag, False):
            return False
        setattr(self.host, self.flag, True)
        self.entered = True
        return True
    def __exit__(self, *args):
        if self.entered:
            setattr(self.host, self.flag, False)






def find_material_groups_fuzzy_strict(table):
    """
    严格版：只有同时命中【材料类型/材料牌号/材料标准/供货状态】四行，才认为是一组。
    组的边界：遇到“非材料行”或同组内出现重复字段时断组。
    返回:
      groups:    [ {字段->行号}, ... ]      # 仅包含“满四项”的组
      row2field: {行号->字段名}
      row2group: {行号->组下标}
    """
    import re
    KEYS = ('材料类型', '材料牌号', '材料标准', '供货状态')

    def norm(s: str) -> str:
        if not s: return ''
        s = s.strip()
        s = re.sub(r'\s+', '', s)                # 去空白
        s = re.sub(r'[0-9０-９]+', '', s)         # 去数字
        s = re.sub(r'（.*?）|\(.*?\)', '', s)     # 去括号内容
        return s

    def hit_key(txt: str):
        for k in KEYS:
            if k in txt:
                return k
        return None

    groups = []
    row2field, row2group = {}, {}

    def maybe_commit(cur_map):
        # 只有满四项才入组
        if len(cur_map) == 4:
            gi = len(groups)
            groups.append(cur_map.copy())
            for k, r in cur_map.items():
                row2field[r] = k
                row2group[r] = gi

    cur = {}  # 当前候选组 {字段->行}
    for r in range(table.rowCount()):
        it = table.item(r, 0)
        txt = norm(it.text() if it else '')
        k = hit_key(txt)

        if not k:
            # 遇到非材料行：尝试提交，再清空
            maybe_commit(cur)
            cur.clear()
            continue

        # 如同组内重复字段，则先尝试提交旧组，再以当前字段开新候选组
        if k in cur:
            maybe_commit(cur)
            cur = {}

        cur[k] = r

    # 收尾
    maybe_commit(cur)

    if not groups:
        print("[材料联动][错误] 未识别到任何【满四项】的材料字段组")
    else:
        if DEBUG_VERBOSE_DEFINE_UI:
            print("[材料联动] 严格识别到材料组：", groups)

    return groups, row2field, row2group

def ensure_editable_item(table: QTableWidget, r: int, c: int) -> bool:
    """保证目标格存在 item 且可编辑；原来没有就创建"""
    it = table.item(r, c)
    if it is None:
        it = QTableWidgetItem("")
        it.setTextAlignment(Qt.AlignCenter)
        # 生成一个“可选/可用/可编辑”的 item，避免因 None 被跳过
        it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
        table.setItem(r, c, it)
        return True
    # 已有 item，但可能不可编辑 → 赋予可编辑标志
    if not (it.flags() & Qt.ItemIsEditable):
        it.setFlags(it.flags() | Qt.ItemIsEditable)
    return True

def _apply_material_paste_batch(table, col: int, rows_map: dict, new_vals: dict):
    """
    批量粘贴用联动：
    - 直接写入 new_vals 里的四字段（有就写，没给的保持原值）
    - 然后执行：校验(不在候选则清空) + 唯一候选自动带入
    - 不执行：'材料类型' 变更后的强清三项
    """
    def _get(r):
        it = table.item(r, col)
        return (it.text().strip() if it else "")

    def _set(r, val):
        it = table.item(r, col)
        if it is None:
            it = QTableWidgetItem()
            it.setTextAlignment(Qt.AlignCenter)
            table.setItem(r, col, it)
        it.setText(val or "")

    # 0) 先把新值写进去（不触发清空）
    table.blockSignals(True)
    try:
        for k in ('材料类型', '材料牌号', '材料标准', '供货状态'):
            if k in new_vals and rows_map.get(k) is not None:
                _set(rows_map[k], new_vals[k])
    finally:
        table.blockSignals(False)

    # 1) 读取当前值
    cur = {
        '材料类型': _get(rows_map.get('材料类型')),
        '材料牌号': _get(rows_map.get('材料牌号')),
        '材料标准': _get(rows_map.get('材料标准')),
        '供货状态': _get(rows_map.get('供货状态')),
    }

    # 2) 基于当前选择拿候选
    filtered = get_filtered_material_options(cur) or {}
    def _opts_of(k):
        opts = filtered.get(k, []) or []
        if not opts or opts[0] != "":  # 保留你的“首个空项”习惯
            opts = [""] + list(dict.fromkeys(opts))
        return opts

    # 3) 校验：四字段不在候选则清空
    table.blockSignals(True)
    try:
        for k in ('材料类型', '材料牌号', '材料标准', '供货状态'):
            r = rows_map.get(k)
            if r is None:
                continue
            val = cur.get(k, "")
            if val and (val not in _opts_of(k)):
                _set(r, "")
                cur[k] = ""
    finally:
        table.blockSignals(False)

    # 4) 唯一候选自动带入（当 类型+牌号 已确定）
    if cur.get('材料类型') and cur.get('材料牌号'):
        filtered2 = get_filtered_material_options({
            '材料类型': cur['材料类型'],
            '材料牌号': cur['材料牌号'],
        }) or {}

        def _autofill_one(key):
            r = rows_map.get(key)
            if r is None or cur.get(key):
                return
            cand = [x for x in (filtered2.get(key, []) or []) if x]
            if len(cand) == 1:
                table.blockSignals(True)
                try:
                    _set(r, cand[0])
                    cur[key] = cand[0]
                finally:
                    table.blockSignals(False)
        _autofill_one('材料标准')
        _autofill_one('供货状态')



def _copy_cells(table: QTableWidget):
    """
    复制逻辑（更鲁棒）：
    1) 优先按 selectedRanges()[0] 作为矩形；
    2) 若矩形只有 1x1，但 actually 选了多个离散 index，则对所有选中 index 求外接矩形；
    3) 按矩形导出 TSV 到剪贴板。
    """
    rngs = table.selectedRanges()
    if rngs:
        r0 = rngs[0]
        top, left, bottom, right = r0.topRow(), r0.leftColumn(), r0.bottomRow(), r0.rightColumn()
    else:
        # 没有矩形，就看是否至少有一个当前格
        idx = table.currentIndex()
        if not idx.isValid():
            return
        top = bottom = idx.row()
        left = right = idx.column()

    # 若矩形只有 1x1，进一步看看是否其实选了很多离散格
    if top == bottom and left == right:
        idxs = table.selectedIndexes()
        if len(idxs) > 1:
            rows = [i.row() for i in idxs]
            cols = [i.column() for i in idxs]
            top, bottom = min(rows), max(rows)
            left, right = min(cols), max(cols)

    lines = []
    for r in range(top, bottom + 1):
        row_vals = []
        for c in range(left, right + 1):
            it = table.item(r, c)
            row_vals.append(it.text() if it else "")
        lines.append("\t".join(row_vals))
    tsv = "\n".join(lines)
    QApplication.clipboard().setText(tsv)

    # —— 调试输出 —— #
    print(f"[COPY] rect=({top},{left})~({bottom},{right}), "
          f"rows={bottom-top+1}, cols={right-left+1}, tsv_lines={len(lines)}")


def _paste_cells(table: QTableWidget, groups, row2field, row2group):
    md  = QApplication.clipboard().mimeData()
    txt = md.text() if (md and md.hasText()) else ""
    if not txt:
        return
    txt = txt.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    if not txt:
        return

    grid = [row.split("\t") for row in txt.split("\n")]
    rows_in, cols_in = len(grid), max((len(r) for r in grid), default=0)

    # 起点：若有矩形选区，用其左上角；否则用 currentIndex()
    rngs = table.selectedRanges()
    if rngs:
        anchor_r, anchor_c = rngs[0].topRow(), rngs[0].leftColumn()
    else:
        cur = table.currentIndex()
        if not cur.isValid():
            return
        anchor_r, anchor_c = cur.row(), cur.column()

    # 单值 + 有选区 → 填充选区；否则按照 grid 大小覆盖
    fill_mode = (rows_in == 1 and cols_in == 1 and bool(rngs))

    touched = set()
    table.closePersistentEditor(table.currentItem())
    table.blockSignals(True)
    try:
        if fill_mode:
            r0 = rngs[0]
            val = grid[0][0]
            for r in range(r0.topRow(), r0.bottomRow() + 1):
                for c in range(r0.leftColumn(), r0.rightColumn() + 1):
                    if ensure_editable_item(table, r, c):
                        _set_text_center(table, r, c, val)
                        touched.add((r, c))
        else:
            for rr, row_vals in enumerate(grid):
                for cc, val in enumerate(row_vals):
                    r, c = anchor_r + rr, anchor_c + cc
                    if r >= table.rowCount() or c >= table.columnCount():
                        continue
                    if ensure_editable_item(table, r, c):
                        _set_text_center(table, r, c, val)
                        touched.add((r, c))
    finally:
        table.blockSignals(False)

    # —— 调试输出 —— #
    if touched:
        min_r = min(r for r, _ in touched); max_r = max(r for r, _ in touched)
        min_c = min(c for _, c in touched); max_c = max(c for _, c in touched)
        print(f"[PASTE] from_clip_rows={rows_in}, cols={cols_in}, "
              f"anchor=({anchor_r},{anchor_c}), "
              f"applied_rect=({min_r},{min_c})~({max_r},{max_c}), "
              f"cells={len(touched)}")
    else:
        print("[PASTE] nothing applied")

    # —— 粘贴后：按【(组,列)】分桶，严格顺序触发联动 —— #
    order = ('材料类型', '材料牌号', '材料标准', '供货状态')

    buckets = {}  # key: (gi, c)  ->  value: {field: last_value}
    for (r, c) in touched:
        gi = row2group.get(r)
        if gi is None or gi < 0 or gi >= len(groups):
            continue
        fld = row2field.get(r)
        if fld not in ('材料类型', '材料牌号', '材料标准', '供货状态'):
            continue
        # 读取我们刚刚写入的文本（可能被后续覆盖，取“最后一次”的）
        it = table.item(r, c)
        val = (it.text().strip() if it else "")
        d = buckets.setdefault((gi, c), {})
        d[fld] = val

    # 对每个 (组,列) 批量应用，不走“类型强清”
    for (gi, c), vals in buckets.items():
        rows_map = groups[gi]
        _apply_material_paste_batch(table, c, rows_map, vals)


def _cell_is_editable(table: QTableWidget, r: int, c: int) -> bool:
    it = table.item(r, c)
    return bool(it and (it.flags() & Qt.ItemIsEditable))

def _set_text_center(table: QTableWidget, r: int, c: int, text: str):
    it = table.item(r, c)
    if it is None:
        it = QTableWidgetItem()
        table.setItem(r, c, it)
    it.setText(text or "")
    it.setTextAlignment(Qt.AlignCenter)


def install_reinforcement_group_toggle(
        table,
        *,
        param_col=0,
        value_cols=(1, 2, 3),
):
    """
    安装补强圈字段组的显示/隐藏切换功能

    当"是否使用补强圈"选择"是"时，显示所有补强圈相关字段
    当选择"否"时，隐藏所有补强圈相关字段
    """
    if not table or table.rowCount() == 0:
        return

    def _get_text(r, c):
        w = table.cellWidget(r, c)
        if isinstance(w, QComboBox):
            return w.currentText().strip()
        if isinstance(w, QLineEdit):
            return w.text().strip()
        it = table.item(r, c)
        return (it.text().strip() if it else "")

    # 参数名 -> 行号
    name2row = {}
    for r in range(table.rowCount()):
        it = table.item(r, param_col)
        if it:
            name2row[it.text().strip()] = r

    # 查找补强圈相关字段
    toggle_row = name2row.get("是否使用补强圈", -1)
    reinforcement_rows = []

    # 查找所有以"补强圈"开头的字段
    for r in range(table.rowCount()):
        it = table.item(r, param_col)
        if it and it.text().strip().startswith("补强圈"):
            reinforcement_rows.append(r)

    if toggle_row < 0 or not reinforcement_rows:
        print("[补强圈切换] 未找到补强圈相关字段，跳过安装")
        return

    def _refresh():
        """刷新补强圈字段的显示状态"""
        # 检查是否使用补强圈
        has_reinforcement = True
        if toggle_row >= 0:
            toggle_value = _get_text(toggle_row, min(value_cols))
            # 当选择"否"或"程序推荐"时隐藏，其他情况（"是"或空值）都显示
            has_reinforcement = toggle_value not in ["否", "程序推荐"]

        # 控制补强圈相关字段的显示/隐藏
        for rr in reinforcement_rows:
            table.setRowHidden(rr, not has_reinforcement)
            # 注意：不清空数据，只是隐藏/显示

        table.viewport().update()

    # 初始化
    _refresh()

    # 连接开关字段的变化事件
    if toggle_row >= 0:
        wdg = table.cellWidget(toggle_row, min(value_cols))
        if isinstance(wdg, QComboBox):
            def _on_toggle_changed():
                _refresh()

            try:
                wdg.currentTextChanged.disconnect()
            except Exception:
                pass
            try:
                wdg.currentIndexChanged.disconnect()
            except Exception:
                pass
            wdg.currentTextChanged.connect(lambda _t: _on_toggle_changed())
            wdg.currentIndexChanged.connect(lambda _i: _on_toggle_changed())

    # 监听模型数据变化
    model = table.model()
    old = getattr(table, "_reinforcement_toggle_conn", None)
    if old:
        try:
            model.dataChanged.disconnect(old)
        except Exception:
            pass

    def _on_data_changed(topLeft, bottomRight, roles=None):
        for r in range(topLeft.row(), bottomRight.row() + 1):
            if r == toggle_row:
                for c in range(topLeft.column(), bottomRight.column() + 1):
                    if c in value_cols:
                        _refresh()
                        return

    model.dataChanged.connect(_on_data_changed)
    table._reinforcement_toggle_conn = _on_data_changed

    print(f"[补强圈切换] 已安装，开关行={toggle_row}，受控行={reinforcement_rows}")


from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QComboBox, QLineEdit, QTableWidgetItem

def install_overlay_group_toggle(
    table,
    groups,
    *,
    param_col=0,
    value_cols=(1, 2, 3),
):
    if not table or table.rowCount() == 0:
        return

    def _get_text(r, c):
        w = table.cellWidget(r, c)
        if isinstance(w, QComboBox):
            return w.currentText().strip()
        if isinstance(w, QLineEdit):
            return w.text().strip()
        it = table.item(r, c)
        return (it.text().strip() if it else "")

    def _set_text(r, c, txt: str):
        it = table.item(r, c)
        if it is None:
            it = QTableWidgetItem(txt)
            it.setTextAlignment(Qt.AlignCenter)
            table.setItem(r, c, it)
        else:
            it.setText(txt)

    def _clear_cell(r, c):
        w = table.cellWidget(r, c)
        if isinstance(w, QComboBox):
            if w.findText("") >= 0:
                w.setCurrentText("")
            elif w.count():
                w.setCurrentIndex(0)
        elif isinstance(w, QLineEdit):
            w.clear()
        else:
            _set_text(r, c, "")

    def _set_cell_enabled(r, c, enabled: bool):
        """
        双保险禁用/启用单元格：
         - 若有持久化 widget（cellWidget），直接 setEnabled
         - 通过 item.flags 控制是否可编辑（如果没有 item，先创建一个占位 item）
        """
        w = table.cellWidget(r, c)
        if w is not None:
            try:
                w.setEnabled(enabled)
            except Exception:
                pass

        it = table.item(r, c)
        if it is None:
            # 创建占位 item，保证能设置 flags（并显示文本）
            it = QTableWidgetItem(_get_text(r, c))
            it.setTextAlignment(Qt.AlignCenter)
            table.setItem(r, c, it)

        flags = it.flags()
        if enabled:
            # 恢复可编辑/可用 — 如果之前你去掉了 ItemIsEnabled，这里要把它加回来
            flags |= Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable
            it.setBackground(Qt.white)  # 恢复白底
            it.setForeground(Qt.black)  # 黑字
        else:
            # 禁止编辑但仍可选中（外观不一定灰，若想灰则同时去掉 ItemIsEnabled）
            flags &= ~Qt.ItemIsEditable  # 软禁用：不可编辑，但可点选
            # it.setBackground(QColor(230, 230, 230))  # 浅灰色底
            # it.setForeground(Qt.darkGray)  # 灰字

            # 若想视觉灰掉，请使用下面这一行代替上一行(硬禁用)：
            # flags &= ~Qt.ItemIsEditable & ~Qt.ItemIsEnabled
        it.setFlags(flags)


    # 参数名 -> 行号
    name2row = {}
    for r in range(table.rowCount()):
        it = table.item(r, param_col)
        if it:
            name2row[it.text().strip()] = r

    watchers = []  # 每项是 dict，避免解包错误

    for g in groups:
        prefixes       = tuple(g.get("prefixes", ()))
        toggle_names   = tuple(g.get("toggle_names", ()))
        type_name      = g.get("type_name", "")
        grade_name     = g.get("grade_name", "")
        status_name    = g.get("status_name", "")
        process_name   = g.get("process_name", "")
        thickness_name = g.get("thickness_name", "")
        thickness_min  = float(g.get("thickness_min", 0.0))

        process_plate_options = list(g.get("process_plate_options", ["轧制复合", "爆炸焊接"]))
        process_plate_default = g.get("process_plate_default", "爆炸焊接")
        process_weld_options  = list(g.get("process_weld_options",  ["堆焊"]))
        process_weld_default  = g.get("process_weld_default",  "堆焊")

        plate_values  = set(g.get("plate_values", ["钢板", "板材"]))
        weld_values   = set(g.get("weld_values",  ["焊材"]))

        overlay_rows, toggle_row = [], -1
        for r in range(table.rowCount()):
            it = table.item(r, param_col)
            pname = it.text().strip() if it else ""
            if any(pname.startswith(px) for px in prefixes):
                overlay_rows.append(r)
            if toggle_row < 0 and pname in toggle_names:
                toggle_row = r

        type_row     = name2row.get(type_name,   -1) if type_name   else -1
        grade_row    = name2row.get(grade_name,  -1) if grade_name  else -1
        status_row   = name2row.get(status_name, -1) if status_name else -1
        process_row  = name2row.get(process_name,-1) if process_name else -1
        thickness_row = name2row.get(thickness_name, -1) if thickness_name else -1

        if not overlay_rows and toggle_row < 0 and (
            type_row < 0 and grade_row < 0 and status_row < 0 and process_row < 0 and thickness_row < 0
        ):
            continue

        # --- 生成刷新函数（注意参数顺序） ---
        def make_refresh(_toggle_row, _type_row, _grade_row, _status_row, _process_row,
                         _thickness_row, _thickness_min, _overlay_rows,
                         _plate_values, _weld_values,
                         _p_plate_opts, _p_plate_def, _p_weld_opts, _p_weld_def):
            def _refresh():
                # 1) 覆层开关：整块显隐
                has_overlay = True
                if _toggle_row >= 0:
                    has_overlay = (_get_text(_toggle_row, min(value_cols)) == "是")

                for rr in _overlay_rows:
                    table.setRowHidden(rr, not has_overlay)
                    # 注释掉覆层开关的清空逻辑，采用补强圈的逻辑（仅隐藏，不清空）
                    # if not has_overlay:
                    #     for cc in value_cols:
                    #         _clear_cell(rr, cc)

                if not has_overlay:
                    table.viewport().update()
                    return

                # 2) 类型驱动联动
                types = [_get_text(_type_row, c) for c in value_cols] if _type_row >= 0 else []
                non_empty = [t for t in types if t != ""]
                has_plate = any(t in _plate_values for t in types) if types else False
                all_weld  = (len(non_empty) > 0) and all(t in _weld_values for t in non_empty)


                # 2.1 级别（显隐 + 单列禁用）
                if _grade_row >= 0:
                    if all_weld:
                        table.setRowHidden(_grade_row, True)
                        # 三列都是焊材时，清空所有级别数据（焊材不需要级别）
                        for cc in value_cols:
                            _clear_cell(_grade_row, cc)
                    else:
                        table.setRowHidden(_grade_row, False)
                        for cc in value_cols:
                            t = _get_text(_type_row, cc) if _type_row >= 0 else ""
                            if t in _weld_values:
                                _set_cell_enabled(_grade_row, cc, False)
                                # 焊材列清空级别数据（焊材不需要级别）
                                _clear_cell(_grade_row, cc)
                            else:
                                _set_cell_enabled(_grade_row, cc, True)


                # 2.2 使用状态（显隐 + 单列禁用）
                if _status_row >= 0:
                    if all_weld:
                        table.setRowHidden(_status_row, True)
                        # 三列都是焊材时，清空所有状态数据（焊材不需要状态）
                        for cc in value_cols:
                            _clear_cell(_status_row, cc)
                    else:
                        table.setRowHidden(_status_row, False)
                        for cc in value_cols:
                            t = _get_text(_type_row, cc) if _type_row >= 0 else ""
                            if t in _weld_values:
                                _set_cell_enabled(_status_row, cc, False)
                                # 焊材列清空状态数据（焊材不需要状态）
                                _clear_cell(_status_row, cc)
                            else:
                                _set_cell_enabled(_status_row, cc, True)

                # 2.3 成型工艺（按列候选 + 值约束）
                if _process_row >= 0:
                    table.setRowHidden(_process_row, False)
                    try:
                        table.setItemDelegateForRow(
                            _process_row,
                            ProcessPerColumnDelegate(
                                table=table,
                                type_row=_type_row,
                                plate_values=_plate_values,
                                weld_values=_weld_values,
                                plate_options=_p_plate_opts,
                                weld_options=_p_weld_opts,
                            )
                        )
                    except Exception:
                        pass

                    for cc in value_cols:
                        t = _get_text(_type_row, cc)
                        if t in _weld_values:
                            _set_text(_process_row, cc, _p_weld_def)  # 焊材强制“堆焊”
                        elif t in _plate_values:
                            cur = _get_text(_process_row, cc)
                            if cur not in _p_plate_opts:
                                _set_text(_process_row, cc, _p_plate_def)  # 若不想改默认可注释
                        else:
                            pass

            return _refresh

        rf = make_refresh(
            toggle_row, type_row, grade_row, status_row, process_row,
            thickness_row, thickness_min, overlay_rows,
            plate_values, weld_values,
            process_plate_options, process_plate_default, process_weld_options, process_weld_default
        )

        watchers.append({
            "toggle_row": toggle_row,
            "type_row": type_row,
            "grade_row": grade_row,
            "status_row": status_row,
            "process_row": process_row,
            "thickness_min": thickness_min,
            "overlay_rows": overlay_rows,
            "refresh": rf,
        })

    if not watchers:
        return

    # 初始化
    for w in watchers:
        w["refresh"]()

    # 连接持久化 QComboBox（增强即时性）
    for w in watchers:
        toggle_row = w["toggle_row"]
        type_row   = w["type_row"]
        rf         = w["refresh"]

        if toggle_row >= 0:
            wdg = table.cellWidget(toggle_row, min(value_cols))
            if isinstance(wdg, QComboBox):
                def _cb1(): rf()
                try: wdg.currentTextChanged.disconnect()
                except Exception: pass
                try: wdg.currentIndexChanged.disconnect()
                except Exception: pass
                wdg.currentTextChanged.connect(lambda _t: _cb1())
                wdg.currentIndexChanged.connect(lambda _i: _cb1())

        if type_row >= 0:
            for c in value_cols:
                wdg = table.cellWidget(type_row, c)
                if isinstance(wdg, QComboBox):
                    def _cb2(): rf()
                    try: wdg.currentTextChanged.disconnect()
                    except Exception: pass
                    try: wdg.currentIndexChanged.disconnect()
                    except Exception: pass
                    wdg.currentTextChanged.connect(lambda _t: _cb2())
                    wdg.currentIndexChanged.connect(lambda _i: _cb2())

    # 统一监听模型写回（代理编辑器提交后必触发）
    model = table.model()
    old = getattr(table, "_overlay_toggle_conn", None)
    if old:
        try: model.dataChanged.disconnect(old)
        except Exception: pass

    watch_rows = set()
    for w in watchers:
        for key in ("toggle_row", "type_row", "process_row"):
            if w[key] >= 0:
                watch_rows.add(w[key])
    watch_cols = set(value_cols)

    def _on_data_changed(topLeft, bottomRight, roles=None):
        for r in range(topLeft.row(), bottomRight.row() + 1):
            if r in watch_rows:
                for c in range(topLeft.column(), bottomRight.column() + 1):
                    if c in watch_cols:
                        # # 厚度兜底校验（≥ min）
                        # for w in watchers:
                        #     if r == w["thickness_row"]:
                        #         txt = _get_text(r, c)
                        #         try:
                        #             if float(txt) < float(w["thickness_min"]):
                        #                 _clear_cell(r, c)
                        #         except Exception:
                        #             _clear_cell(r, c)
                        #         break
                        # 刷新相应组
                        for w in watchers:
                            if r in (w["toggle_row"], w["type_row"], w["process_row"]):
                                w["refresh"]()
                                break
                        return

    model.dataChanged.connect(_on_data_changed)
    table._overlay_toggle_conn = _on_data_changed


def install_selection_debug(table):
    def dump_selection(tag):
        idxs = table.selectedIndexes()
        if not idxs:
            return
        rows = sorted({i.row() for i in idxs})
        byrow = {}
        for i in idxs:
            byrow.setdefault(i.row(), []).append(i.column())
        msg_rows = ", ".join(f"r{r}:c{sorted(cols)}" for r, cols in byrow.items())
    sm = table.selectionModel()
    if sm:
        sm.selectionChanged.connect(lambda *_: dump_selection("changed"))
    # 首次也打一次
    dump_selection("init")

def render_guankou_param_to_ui(viewer_instance, guankou_para_info: list):
    table = viewer_instance.tableWidget_guankou

    # === 渲染前调试信息 ===
    try:
        tw = getattr(viewer_instance, "guankou_tabWidget", None)
        cur_tab = tw.tabText(tw.currentIndex()) if tw and tw.currentIndex() >= 0 else "<无>"
    except Exception:
        cur_tab = "<异常>"
    print(
        f"[DBG][render] 开始渲染 tab={repr(cur_tab)}  数据条数={0 if guankou_para_info is None else len(guankou_para_info)}")

    # 统计一下参数名分布，便于判断是否空数据
    if guankou_para_info:
        names_preview = [d.get("参数名称") for d in guankou_para_info[:10]]
        print(f"[DBG][render] 参数名预览(前10)：{names_preview}")

    table.clear()
    table.setRowCount(0)
    table.setColumnCount(4)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setVisible(False)
    table.setSelectionBehavior(QTableWidget.SelectItems)
    table.setSelectionMode(QTableWidget.ExtendedSelection)  # 支持框选/多选/Shift/Ctrl
    install_selection_debug(table)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)  # 关键：禁用默认触发
    table.setProperty("user_edited_corrosion", False)
    table.setProperty("user_edited_opening_weld_joint_coeff", False)

    # 安装我们的过滤器（持有引用避免被 GC）
    flt = ComboPopupEventFilter(table)
    table._popup_filter = flt
    table.viewport().installEventFilter(flt)

    class NumericDelegate(QStyledItemDelegate):
        def __init__(self, rule: str, pname: str, table=None, viewer=None, broadcast_row=True):
            """
            rule: 'ge0' (>=0) / 'gt0' (>0)
            """
            super().__init__(table)
            self.rule = rule
            self.pname = pname
            self.table = table
            self.viewer = viewer
            self.broadcast_row = broadcast_row
            self._targets_cache = []

        def _snapshot_targets(self, row: int):
            """进入编辑器前快照：同一行里被多选且可编辑的列"""
            cols = []
            if self.table and self.table.selectionModel():
                idxs = self.table.selectionModel().selectedIndexes()
                for i in idxs:
                    if i.row() == row:
                        it = self.table.item(row, i.column())
                        if it and (it.flags() & Qt.ItemIsEditable):
                            cols.append(i.column())
            cols = sorted(set(cols))
            return cols

        def highlight_row(self, row):
            if not self.table:
                return
            base = QColor("#ffffff")
            hl = QColor("#d0e7ff")
            for rr in range(self.table.rowCount()):
                for cc in range(self.table.columnCount()):
                    it = self.table.item(rr, cc)
                    if it:
                        it.setBackground(base)
            if 0 <= row < self.table.rowCount():
                for cc in range(self.table.columnCount()):
                    it = self.table.item(row, cc)
                    if it:
                        it.setBackground(hl)

        def createEditor(self, parent, option, index):
            self._targets_cache = self._snapshot_targets(index.row())

            if self.table:
                self.highlight_row(index.row())
                self._targets_cache = self._snapshot_targets(index.row())

            le = QLineEdit(parent)
            le.setFont(self.table.font() if self.table else parent.font())
            le.setAlignment(Qt.AlignCenter)
            le.setAutoFillBackground(True)

            pal = le.palette()
            if self.table:
                pal.setColor(QPalette.Base, self.table.palette().color(QPalette.Base))
                pal.setColor(QPalette.Text, self.table.palette().color(QPalette.Text))
            le.setPalette(pal)
            le.setStyleSheet(
                "QLineEdit{border:none;background:palette(base);color:palette(text);padding-left:2px;}"
            )

            # ❗不设置任何 QDoubleValidator，让用户可以输入任意字符，提交时统一校验
            le.editingFinished.connect(lambda: self.commitData.emit(le))
            le.returnPressed.connect(lambda: (self.commitData.emit(le),
                                              self.closeEditor.emit(le, QStyledItemDelegate.NoHint)))
            le.installEventFilter(self)  # 失焦兜底提交
            return le

        def eventFilter(self, editor, ev):
            if isinstance(editor, QLineEdit) and ev.type() == QEvent.FocusOut:
                try:
                    self.commitData.emit(editor)
                except Exception:
                    pass
            return super().eventFilter(editor, ev)

        def setEditorData(self, editor, index):
            editor.setText(index.data() or "")
            QTimer.singleShot(0, editor.selectAll)

        def updateEditorGeometry(self, editor, option, index):
            editor.setGeometry(option.rect)

        def _restore_item_text(self, model, index, text):
            if not self.table:
                return
            r, c = index.row(), index.column()
            it = self.table.item(r, c)
            if it is None:
                it = QTableWidgetItem()
                self.table.setItem(r, c, it)
            it.setText(text)
            it.setTextAlignment(Qt.AlignCenter)

        def setModelData(self, editor, model, index):
            txt = (editor.text() or "").strip()
            tip = getattr(self.viewer, "line_tip", None)
            r, c = index.row(), index.column()

            def show_tip(msg: str):
                if not tip: return
                tip.setStyleSheet("color:red;")
                tip.setText(msg)
                QTimer.singleShot(0, lambda: (tip.setStyleSheet("color:red;"), tip.setText(msg)))
                QTimer.singleShot(50, lambda: (tip.setStyleSheet("color:red;"), tip.setText(msg)))

            # 空值：清空当前格并返回
            if txt == "":
                if tip: tip.setText("")
                model.setData(index, "")
                self._restore_item_text(model, index, "")
                if self.table:
                    self.table.setCurrentCell(r, c)
                    self.highlight_row(r)
                return

            # 数值校验
            ok = False
            try:
                v = float(txt)
                ok = (v > 0) if (self.rule == "gt0") else (v >= 0)
            except Exception:
                ok = False

            if not ok:
                show_tip(f"参数“{self.pname}”的值应为{'大于 0' if self.rule == 'gt0' else '大于等于 0'}的数字！")
                model.setData(index, "")
                self._restore_item_text(model, index, "")
                if self.table:
                    self.table.setCurrentCell(r, c)
                    self.highlight_row(r)
                return

            # 针对“所属元件开孔处焊接接头系数”：强制用户输入值 >= 默认值 D（存放在 UserRole+1 中）
            if (self.pname or "") == "所属元件开孔处焊接接头系数" and self.table:
                d_val = None
                try:
                    it = self.table.item(r, c)
                    if it is not None:
                        d = it.data(Qt.UserRole + 1)
                        if d is not None and str(d).strip() != "":
                            d_val = float(d)
                except Exception:
                    d_val = None

                if d_val is not None and v < d_val:
                    show_tip(f"参数“{self.pname}”的值应不小于默认值 {d_val}！")
                    model.setData(index, "")
                    self._restore_item_text(model, index, "")
                    if self.table:
                        self.table.setCurrentCell(r, c)
                        self.highlight_row(r)
                    return


            # 先写回当前格
            model.setData(index, txt)
            self._restore_item_text(model, index, txt)
            if tip: tip.setText("")

            selected_cols = list(self._targets_cache) if self._targets_cache else []
            if not selected_cols and self.table:
                sm = self.table.selectionModel()
                if sm:
                    selected_cols = sorted({
                        i.column() for i in sm.selectedIndexes()
                        if i.row() == r
                           and self.table.item(r, i.column())
                           and (self.table.item(r, i.column()).flags() & Qt.ItemIsEditable)
                    })
            # 用完就清空快照
            self._targets_cache = []

            print(f"[NUM][commit] row={r} cur_col={c} selected_cols={selected_cols} "
                  f"mode={'MULTI' if len(selected_cols) >= 2 else 'SINGLE'}")

            if len(selected_cols) >= 2:
                self.table.blockSignals(True)
                try:
                    for cc in selected_cols:
                        if cc == c:
                            continue
                        it2 = self.table.item(r, cc) or QTableWidgetItem()
                        it2.setTextAlignment(Qt.AlignCenter)
                        it2.setText(txt)
                        self.table.setItem(r, cc, it2)
                finally:
                    self.table.blockSignals(False)

            if self.table:
                self.table.setCurrentCell(r, c)
                self.highlight_row(r)
            try:
                # 标记“接管腐蚀裕量”被用户编辑过
                if "腐蚀裕量" in (self.pname or "") and self.table:
                    self.table.setProperty("user_edited_corrosion", True)
                    v = getattr(self, "viewer", None)
                    if v:
                        tw = getattr(v, "guankou_tabWidget", None)
                        if tw and tw.currentIndex() >= 0:
                            name = tw.tabText(tw.currentIndex()).strip()
                            s = getattr(v, "_corrosion_user_override_tabs", None)
                            if s is None:
                                setattr(v, "_corrosion_user_override_tabs", set())
                                s = getattr(v, "_corrosion_user_override_tabs")
                            s.add(name)

                # 标记“所属元件开孔处焊接接头系数”被用户编辑过
                if (self.pname or "") == "所属元件开孔处焊接接头系数" and self.table:
                    self.table.setProperty("user_edited_opening_weld_joint_coeff", True)
            except Exception:
                pass

    # 这几个是你要改成数值输入的行名（可按需要继续加）
    NUM_GE0 = {
        "接管腐蚀裕量(mm)",
        "所属元件开孔处焊接接头系数",
        "接管焊缝金属截面积(mm²)",
        "接管覆层厚度(mm)",
        "接管法兰覆层厚度(mm)",
    }
    NUM_GT0 = set()  # 需要“严格 >0”的名字可以丢到这里

    param_structures = load_guankou_param_structure_from_db()
    dropdown_options = load_dropdown_options()
    display_map = group_guankou_params_by_prefix(guankou_para_info)

    # ✅ 只显示材料分类为空的管口代号
    try:
        product_id = getattr(viewer_instance, "product_id", None)
        if product_id:
            cur_tab = None
            tw = getattr(viewer_instance, "guankou_tabWidget", None)
            if tw and tw.currentIndex() >= 0 and tw.tabText(tw.currentIndex()) != "+":
                cur_tab = tw.tabText(tw.currentIndex())

            dropdown_options['管口号'] = query_codes_for_tab_raw(product_id, cur_tab)
    except Exception as e:
        print(f"[警告] 加载管口号候选失败: {e}")

    numeric_rows = []
    # ===== 渲染 =====
    for param_name, structure, control_type, prefix in param_structures:
        row = table.rowCount()
        table.insertRow(row)

        # 左侧名称列
        label_item = QTableWidgetItem(param_name)
        label_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        table.setItem(row, 0, label_item)

        option_key = prefix or param_name
        options = dropdown_options.get(option_key, [])

        if structure == "2列":
            table.setSpan(row, 1, 1, 3)
            value = display_map.get(prefix or param_name, "")

            if control_type == "combo":
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                table.setItem(row, 1, item)
                if options:
                    if param_name == "元件所属":
                        table.setItemDelegateForRow(row, CheckComboDelegate(options, table))
                    else:
                        table.setItemDelegateForRow(row, MultiSelectRowComboDelegate(options, table))

            elif control_type == "checkcombo":
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                table.setItem(row, 1, item)
                if options:
                    # 管口号启用"全选"功能，其他参数不启用
                    enable_select_all = (param_name == "管口号")
                    table.setItemDelegateForRow(row, CheckComboDelegate(options, table, enable_select_all=enable_select_all))

            elif control_type == "empty":
                # 2列+empty 类型：如果活动库里已有值（如“所属元件开孔处焊接接头系数”），这里要把值渲染出来
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

                # 为“所属元件开孔处焊接接头系数”写入默认值到 UserRole+1，供数值校验使用
                if param_name == "所属元件开孔处焊接接头系数":
                    try:
                        product_id = getattr(viewer_instance, "product_id", None)
                        cur_tab = None
                        tw = getattr(viewer_instance, "guankou_tabWidget", None)
                        if product_id and tw and tw.currentIndex() >= 0 and tw.tabText(tw.currentIndex()) != "+":
                            cur_tab = tw.tabText(tw.currentIndex())
                        if product_id and cur_tab:
                            default_val = get_opening_weld_joint_default(product_id, cur_tab)
                            if default_val is not None:
                                item.setData(Qt.UserRole + 1, float(default_val))
                    except Exception as e:
                        print(f"[警告] 设置所属元件开孔处焊接接头系数默认值失败: {e}")

                table.setItem(row, 1, item)

        elif structure == "4列":
            value_map = display_map.get(prefix or param_name, {})
            if not isinstance(value_map, dict):
                value_map = {}
            for col in range(1, 4):
                val = value_map.get(col, "")
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                table.setItem(row, col, item)

            opts = dropdown_options.get(param_name) \
                   or (dropdown_options.get(prefix) if prefix else None) \
                   or []

            if opts:
                if control_type == "combo":
                    table.setItemDelegateForRow(row, MultiSelectRowComboDelegate(opts, table))
                elif control_type == "checkcombo":
                    # 管口号启用"全选"功能，其他参数不启用
                    enable_select_all = (param_name == "管口号")
                    table.setItemDelegateForRow(row, CheckComboDelegate(opts, table, enable_select_all=enable_select_all))

        if param_name in NUM_GE0 or param_name in NUM_GT0:
            rule = "ge0" if param_name in NUM_GE0 else "gt0"
            numeric_rows.append((row, rule, param_name))

    # 表头自适应
    header = table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
    for col in range(1, 4):
        header.setSectionResizeMode(col, QHeaderView.Stretch)

    # === 严格分组识别（只保留满四项的组） ===
    groups, row2field, row2group = find_material_groups_fuzzy_strict(table)
    found_rows = sorted(row2field.keys())
    if not found_rows:
        print("[材料联动][警告] 没有满四项的材料组，跳过安装代理")
        return

    # 确保可编辑 & 去掉 cellWidget
    for r in found_rows:
        for c in (1, 2, 3):
            it = table.item(r, c)
            if it is None:
                it = QTableWidgetItem("")
                it.setTextAlignment(Qt.AlignCenter)
                table.setItem(r, c, it)
            it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
            if table.cellWidget(r, c):
                table.setCellWidget(r, c, None)

    # 安装动态代理（只对这些行）
    for r in found_rows:
        table.setItemDelegateForRow(r, None)
    dyn = MultiSelectDynamicOptionsDelegate(table, groups, row2field, row2group)
    for r in found_rows:
        table.setItemDelegateForRow(r, dyn)


    found_set = set(found_rows)
    for r, rule, pname in numeric_rows:
        if r in found_set:
            continue
        # 确保该行对应的数值单元格是可编辑的（包括 2列/4列 结构）
        for c in (1, 2, 3):
            it = table.item(r, c)
            if it:
                it.setFlags(it.flags() | Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        table.setItemDelegateForRow(r, NumericDelegate(rule, pname, table, viewer_instance))


    table.setEditTriggers(QAbstractItemView.SelectedClicked)

    install_copy_paste_shortcuts(table, groups, row2field, row2group)


    # 安装补强圈字段的显示/隐藏切换功能
    install_reinforcement_group_toggle(
        table=table,
        param_col=0,
        value_cols=(1, 2, 3),
    )

    install_overlay_group_toggle(
        table=viewer_instance.tableWidget_guankou,
        groups=[
            {
                "toggle_names": ("接管是否添加覆层", "是否添加覆层"),
                "prefixes": ("接管覆层",),
                "type_name": "接管覆层材料类型",
                "grade_name": "接管覆层材料级别",
                "status_name": "接管覆层使用状态",

                "process_name": "接管覆层成型工艺",
                "process_plate_options": ["轧制复合", "爆炸焊接"],
                "process_plate_default": "爆炸焊接",
                "process_weld_options": ["堆焊"],
                "process_weld_default": "堆焊",

                "thickness_name": "接管覆层厚度(mm)",
                "thickness_min": 0.0,

                "plate_values": ["钢板", "板材"],
                "weld_values": ["焊材"],
            },
            {
                "toggle_names": ("接管法兰是否添加覆层",),
                "prefixes": ("接管法兰覆层",),
                "type_name": "接管法兰覆层材料类型",
                "grade_name": "接管法兰覆层材料级别",
                "status_name": "接管法兰覆层使用状态",

                "process_name": "接管法兰覆层成型工艺",
                "process_plate_options": ["轧制复合", "爆炸焊接"],
                "process_plate_default": "爆炸焊接",
                "process_weld_options": ["堆焊"],
                "process_weld_default": "堆焊",

                "thickness_name": "接管法兰覆层厚度(mm)",
                "thickness_min": 0.0,

                "plate_values": ["钢板", "板材"],
                "weld_values": ["焊材"],
            },
        ],
        param_col=0,
        value_cols=(1, 2, 3),
    )

    def _find_row_by_name(tbl, name, col=0):
        for r in range(tbl.rowCount()):
            it = tbl.item(r, col)
            if it and it.text().strip() == name:
                return r
        return None

    for _name in ("接管覆层厚度(mm)", "接管法兰覆层厚度(mm)"):
        r = _find_row_by_name(table, _name, 0)
        if r is None:
            continue

        # 如果 overlay 逻辑给这行塞过 cellWidget，先移除
        if table.cellWidget(r, 1):
            table.setCellWidget(r, 1, None)

        # 这两行在结构表里一般是“2列”（第1列跨 3 个值列），
        # 但用 row 级委托即可；把三列都确保为可编辑 item
        for c in (1, 2, 3):
            it = table.item(r, c)
            if it is None:
                it = QTableWidgetItem("")
                it.setTextAlignment(Qt.AlignCenter)
                table.setItem(r, c, it)
            it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)

        # 安装我们的数值委托（>=0），并带上 viewer_instance 以便 tip 能正常显示
        table.setItemDelegateForRow(
            r, NumericDelegate("ge0", _name, table, viewer_instance)
        )

    def _select_row_first(r, c):
        table.selectRow(r)  # 先把整行高亮出来

    def _edit_on_click(r, c):
        idx = table.model().index(r, c)
        it = table.item(r, c)
        if idx.isValid() and it and (it.flags() & Qt.ItemIsEditable):
            table.setCurrentIndex(idx)
            table.edit(idx)

    try:
        table.cellPressed.disconnect()
    except Exception:
        pass
    table.cellPressed.connect(_select_row_first)

    try:
        table.cellClicked.disconnect()
    except Exception:
        pass
    table.cellClicked.connect(_edit_on_click)

    # 为整个表格设置悬停提示
    _set_table_tooltips(table)

    # 添加动态更新悬停提示的机制
    _install_tooltip_updater(table)

    print(f"[DBG][render] 完成渲染 tab={repr(cur_tab)}  最终行数={table.rowCount()}")



def _set_table_tooltips(table):
    """
    为管口参数表的所有单元格设置悬停提示
    包括普通单元格和下拉框单元格
    """
    for row in range(table.rowCount()):
        for col in range(table.columnCount()):
            # 检查是否是下拉框单元格
            cell_widget = table.cellWidget(row, col)
            if isinstance(cell_widget, QComboBox):
                # 为下拉框设置悬停提示
                current_text = cell_widget.currentText()
                if current_text and current_text.strip():
                    cell_widget.setToolTip(f"当前选择: {current_text}")
                else:
                    cell_widget.setToolTip("请选择选项")
            else:
                # 为普通单元格设置悬停提示
                item = table.item(row, col)
                if item and item.text().strip():
                    item.setToolTip(item.text())
                else:
                    # 为空单元格设置默认提示
                    if col == 0:  # 参数名列
                        item = table.item(row, col)
                        if item:
                            param_name = item.text().strip()
                            if param_name:
                                item.setToolTip(f"参数名: {param_name}")
                    else:  # 值列
                        item = table.item(row, col)
                        if item:
                            item.setToolTip("点击编辑")


def _install_tooltip_updater(table):
    """
    安装动态更新悬停提示的机制
    当表格内容变化时，自动更新悬停提示
    """
    def combo_formatter(combo: QComboBox, row: int, col: int):
        text = combo.currentText().strip()
        return f"当前选择: {text}" if text else "请选择选项"

    def item_formatter(item: QTableWidgetItem, row: int, col: int):
        text = (item.text() or "").strip()
        if text:
            return text
        if col == 0:
            param_name = (table.item(row, col).text() if table.item(row, col) else "").strip()
            return f"参数名: {param_name}" if param_name else ""
        return "点击编辑"

    ensure_table_tooltip_updater(
        table,
        combo_formatter=combo_formatter,
        item_formatter=item_formatter,
    )




# 11.16设备法兰
def render_fastener_param_to_ui(viewer_instance, fastener_para_info: list):
    """渲染设备法兰紧固件参数到UI - 支持PNO.x格式的tab页面"""
    # 获取参数结构
    param_structures = get_fastener_param_structure_from_db()
    if DEBUG_VERBOSE_DEFINE_UI:
        print(f"[DBG][fastener_render] 参数结构: {param_structures}")

    # 根据参数结构确定列数
    max_cols = 3  # 默认3列：参数名 + 参数值1 + 参数值2
    for _, structure, _, _ in param_structures:
        if structure == "4列":
            max_cols = 4
            break
        elif structure == "3列":
            max_cols = 3  # 3列结构：参数名 + 参数值1 + 参数值2
        elif structure == "2列":
            max_cols = 3  # 2列结构也使用3列表格，但会合并单元格

    template_id = fastener_para_info[0].get('模板ID') if fastener_para_info else None
    if DEBUG_VERBOSE_DEFINE_UI:
        print(f"[DBG][fastener_render] 模板ID: {template_id}")
    component_options = get_fastener_component_options_by_template_id(template_id)
    if DEBUG_VERBOSE_DEFINE_UI:
        print(f"[DBG][fastener_render] 元件所属候选项: {component_options}")
    bolt_type_options = get_fastener_bolt_type_options()
    if DEBUG_VERBOSE_DEFINE_UI:
        print(f"[DBG][fastener_render] 螺柱型式候选项: {bolt_type_options}")
    root_series_options = get_fastener_root_series_options()
    if DEBUG_VERBOSE_DEFINE_UI:
        print(f"[DBG][fastener_render] 螺柱根径系列候选项: {root_series_options}")
    try:
        setattr(viewer_instance, 'fastener_component_all_options', component_options or [])
    except Exception:
        pass

    used_by_tab = {}
    try:
        for item in fastener_para_info or []:
            name = str(item.get('参数名称', '')).strip()
            val = str(item.get('参数值', '') or '').strip()
            tabc = str(item.get('Tab分类', '') or '').strip()
            if not tabc:
                continue
            if not val or val.lower() == 'null':
                continue
            if name == '元件所属' or name.startswith('元件所属'):
                vals = []
                if val.startswith('['):
                    try:
                        import json
                        parsed = json.loads(val)
                        if isinstance(parsed, list):
                            vals = [str(x).strip() for x in parsed if str(x).strip()]
                    except Exception:
                        vals = []
                if not vals:
                    vals = [x.strip() for x in val.split('、') if x.strip()]
                s = used_by_tab.setdefault(tabc, set())
                for x in vals:
                    s.add(x)
    except Exception:
        used_by_tab = used_by_tab
    try:
        setattr(viewer_instance, 'fastener_belonging_used_by_tab_saved', used_by_tab)
    except Exception:
        pass

    # 处理数据分组 - 按Tab分类字段分组（strip 避免 'PNO.2' / 'PNO.2 ' 拆成两组）
    param_map = {}
    if fastener_para_info:
        for item in fastener_para_info:
            tab_class = str(item.get('Tab分类') or 'PNO.1').strip() or 'PNO.1'
            param_map.setdefault(tab_class, []).append(item)
    else:
        param_map = {"PNO.1": []}

    def _fastener_tab_sort_key(label: str):
        s = str(label or '').strip()
        up = s.upper()
        if up.startswith('PNO.'):
            try:
                return (0, int(s.split('.', 1)[1]))
            except (ValueError, IndexError):
                return (1, s)
        return (1, s)

    sorted_tab_items = sorted(param_map.items(), key=lambda kv: _fastener_tab_sort_key(kv[0]))

    if DEBUG_VERBOSE_DEFINE_UI:
        print(f"[DBG][fastener_render] 参数分组: {[k for k, _ in sorted_tab_items]}")

    # 获取或创建tabWidget - 设备法兰紧固件使用tabWidget_3
    tw = getattr(viewer_instance, "tabWidget_3", None)
    if not tw:
        if DEBUG_VERBOSE_DEFINE_UI:
            print("[DBG][fastener_render] 未找到tabWidget_3")
        return
    # 清空现有tab页（保留+号tab）
    has_plus = (tw.count() > 0 and tw.tabText(tw.count() - 1).strip() in {"+", "＋"})
    last_real = tw.count() - (1 if has_plus else 0)
    for i in range(last_real - 1, 0, -1):
        w = tw.widget(i)
        tw.removeTab(i)
        if w:
            w.deleteLater()

    # 初始化动态tab字典
    if not hasattr(viewer_instance, "dynamic_fastener_param_tabs"):
        viewer_instance.dynamic_fastener_param_tabs = {}
    viewer_instance.dynamic_fastener_param_tabs.clear()

    # 为每个PNO创建tab页（顺序固定为 PNO.1, PNO.2, …，不依赖数据库返回顺序）
    for idx, (pno_label, data) in enumerate(sorted_tab_items):
        already_used = set()
        for t, vs in used_by_tab.items():
            if t != pno_label:
                already_used |= set(vs or [])
        filtered_component_opts = [x for x in component_options if x not in already_used]
        curr_vals = list(used_by_tab.get(pno_label, set()))
        for v in curr_vals:
            if v and v not in filtered_component_opts:
                filtered_component_opts.append(v)
        dropdown_options = {
            "元件所属": filtered_component_opts,
            "螺柱型式": bolt_type_options,
            "螺柱根径系列": root_series_options,
        }
        try:
            from modules.cailiaodingyi.funcs.funcs_pdf_input import get_options_for_param
            forging_opts = get_options_for_param("锻件级别") or []
            dropdown_options["锻件级别"] = [str(x).strip() for x in forging_opts if str(x).strip()]
        except Exception:
            pass
        if idx == 0:
            # 第一个tab，复用现有的
            tw.setTabText(0, pno_label)
            page0 = tw.widget(0)
            tables = page0.findChildren(QTableWidget) if page0 else []
            table = tables[0] if tables else getattr(viewer_instance, "tableWidget_define1_3", None)
            if table is None:
                if DEBUG_VERBOSE_DEFINE_UI:
                    print("[DBG][fastener_render] 未找到tableWidget_define1_3")
                return
            page0.setProperty("param_table", table)
            try:
                table._viewer_instance = viewer_instance
                table._current_tab_name = pno_label
                table.setProperty('gk_code_candidates', filtered_component_opts)
            except Exception:
                pass
        else:
            # 创建新的tab页（设备法兰紧固件使用 tabWidget_3）
            from PyQt5 import QtWidgets, QtCore
            try:
                from modules.cailiaodingyi.controllers.table import CustomHeaderView
            except Exception:
                CustomHeaderView = None
            insert_pos = None
            last_is_plus = (tw.count() > 0 and tw.tabText(tw.count() - 1).strip() in {"+", "＋"})
            insert_pos = tw.count() - 1 if last_is_plus else tw.count()
            insert_pos = max(0, insert_pos)
            page = QtWidgets.QWidget()
            table = QTableWidget()
            if CustomHeaderView:
                table.setHorizontalHeader(CustomHeaderView(QtCore.Qt.Horizontal, table))
            table.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
            main_layout = QtWidgets.QVBoxLayout(page)
            w0 = tw.widget(0) if tw.count() > 0 else None
            if w0 and w0.layout():
                m = w0.layout().contentsMargins()
                main_layout.setContentsMargins(m.left(), m.top(), m.right(), m.bottom())
                main_layout.setSpacing(w0.layout().spacing())
                page.setStyleSheet(w0.styleSheet())
                mp = w0.contentsMargins()
                page.setContentsMargins(mp.left(), mp.top(), mp.right(), mp.bottom())
            else:
                main_layout.setContentsMargins(9, 6, 9, 6)
                main_layout.setSpacing(6)
            main_layout.addWidget(table)
            tw.insertTab(insert_pos, page, pno_label)
            tw.setCurrentIndex(insert_pos)
            page.setProperty("param_table", table)
            try:
                table._viewer_instance = viewer_instance
                table._current_tab_name = pno_label
                table.setProperty('gk_code_candidates', filtered_component_opts)
            except Exception:
                pass

        # 保存到字典
        viewer_instance.dynamic_fastener_param_tabs[pno_label] = table

        # 渲染数据到表格
        _render_fastener_table_data(table, data, param_structures, dropdown_options, max_cols, viewer_instance)

        if DEBUG_VERBOSE_DEFINE_UI:
            print(f"[DBG][fastener_render] 完成渲染 {pno_label}，共 {table.rowCount()} 行")

    try:
        from modules.cailiaodingyi.controllers.add_tab import PlusTabManager
        from modules.cailiaodingyi.controllers.datamanager import _add_single_fastener_tab_copy_only, _on_fastener_tab_right_menu
        if hasattr(viewer_instance, 'fastener_plus_mgr'):
            try:
                viewer_instance.fastener_plus_mgr.tw.tabBar().tabBarClicked.disconnect()
                viewer_instance.fastener_plus_mgr.tw.removeEventFilter(viewer_instance.fastener_plus_mgr)
                viewer_instance.fastener_plus_mgr.tw.tabBar().removeEventFilter(viewer_instance.fastener_plus_mgr)
            except Exception:
                pass
            del viewer_instance.fastener_plus_mgr

        def wrapper_add_fastener(src_idx, src_name):
            return _add_single_fastener_tab_copy_only(viewer_instance, src_idx, src_name)
        viewer_instance.fastener_plus_mgr = PlusTabManager(tw, wrapper_add_fastener)
        try:
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(100, lambda: (viewer_instance.fastener_plus_mgr.refresh_after_model_change(), viewer_instance.fastener_plus_mgr.update_mode()))
        except Exception:
            pass
        try:
            from PyQt5.QtCore import Qt
            if not getattr(tw.tabBar(), "_fastener_context_wired", False):
                tw.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
                tw.tabBar().customContextMenuRequested.connect(lambda pos: _on_fastener_tab_right_menu(viewer_instance, pos))
                setattr(tw.tabBar(), "_fastener_context_wired", True)
        except Exception as e:
            if DEBUG_VERBOSE_DEFINE_UI:
                print(f"[DBG][fastener_render] 右键菜单绑定失败: {e}")
    except Exception as e:
        if DEBUG_VERBOSE_DEFINE_UI:
            print(f"[DBG][fastener_render] 初始化PlusTabManager失败: {e}")

    try:
        refresh_fastener_belonging_candidates(viewer_instance)
    except Exception as e:
        if DEBUG_VERBOSE_DEFINE_UI:
            print(f"[DBG][fastener_render] 初次刷新候选失败: {e}")


def _render_fastener_table_data(table, data, param_structures, dropdown_options, max_cols, viewer_instance=None):
    """渲染设备法兰紧固件数据到表格"""
    from PyQt5.QtWidgets import QTableWidgetItem, QComboBox, QLineEdit
    from PyQt5.QtCore import Qt

    # 定义辅助函数
    def ensure_editable_item(r, c, txt=""):
        it = table.item(r, c)
        if it is None:
            it = QTableWidgetItem(txt)
            table.setItem(r, c, it)
        it.setTextAlignment(Qt.AlignCenter)
        it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
        it.setText(txt)
        return it

    def ensure_readonly_item(r, c, txt=""):
        it = table.item(r, c)
        if it is None:
            it = QTableWidgetItem(txt)
            table.setItem(r, c, it)
        it.setTextAlignment(Qt.AlignCenter)
        it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        it.setText(txt)
        return it

    def _normalize(v):
        s = "" if v is None else str(v).strip()
        return "" if s.lower() == "null" else s

    def _first_non_empty(d):
        for k in sorted(d.keys()):
            s = _normalize(d.get(k, ""))
            if s:
                return s
        return ""

    def _is_empty_belonging_text(s):
        s = (s or "").strip()
        if not s:
            return True
        if s in ("[]", "—", "请选择"):
            return True
        if s.lower() in ("null", "none"):
            return True
        if s.startswith("[") and s.endswith("]"):
            try:
                import json
                p = json.loads(s)
                if not p:
                    return True
            except Exception:
                pass
        parts = [x.strip() for x in s.split("、") if x.strip()]
        return len(parts) == 0

    def _clear_on_empty_belonging():
        try:
            table.blockSignals(True)
            bases = ["材料类型", "材料牌号", "材料标准", "供货状态"]
            for r in range(table.rowCount()):
                it0 = table.item(r, 0)
                if not it0:
                    continue
                nm = (it0.text() or "").strip()
                if nm in bases or any(nm.startswith(b) for b in bases):
                    for c in range(1, max_cols):
                        itv = table.item(r, c)
                        if itv:
                            itv.setText("")
                if nm == "螺柱型式":
                    itv1 = table.item(r, 1)
                    if itv1:
                        itv1.setText("")
        finally:
            table.blockSignals(False)

    table.clear()
    table.setRowCount(0)
    table.setColumnCount(max_cols)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setVisible(False)  # 隐藏表头
    table.setSelectionBehavior(QTableWidget.SelectItems)
    table.setSelectionMode(QTableWidget.ExtendedSelection)
    table.setEditTriggers(QAbstractItemView.SelectedClicked)

    flt = ComboPopupEventFilter(table)
    table._popup_filter = flt
    table.viewport().installEventFilter(flt)

    # 创建数据映射 - 支持多列数据格式
    display_map = {}
    if data:
        for item in data:
            param_name = item.get('参数名称', '')
            param_value = _normalize(item.get('参数值', ''))

            # 检查是否是带数字后缀的参数名（如"元件类型1"、"元件类型2"）
            import re
            match = re.match(r'^(.*?)(\d+)$', param_name)
            if match:
                base_name, col_index = match.groups()
                col_index = int(col_index)

                # 如果是多列参数，创建字典结构
                if base_name not in display_map:
                    display_map[base_name] = {}
                display_map[base_name][col_index] = param_value
            else:
                # 单列参数
                display_map[param_name] = param_value
        # 清空后，数据库仍有记录但值可能为空，这里补默认值
        # 1) 元件名称
        if not display_map.get("元件名称"):
            display_map["元件名称"] = "设备法兰紧固件"
        # 2) 元件类型（两列）
        typemap = display_map.get("元件类型")
        if not isinstance(typemap, dict):
            typemap = {}
        if not typemap.get(1):
            typemap[1] = "螺柱"
        if not typemap.get(2):
            typemap[2] = "螺母"
        display_map["元件类型"] = typemap
        # 3) 表面处理工艺
        if not display_map.get("表面处理工艺"):
            display_map["表面处理工艺"] = "/"

        if DEBUG_VERBOSE_DEFINE_UI:
            print(f"[DBG][fastener_render] 数据映射: {display_map}")
    else:
        if DEBUG_VERBOSE_DEFINE_UI:
            print(f"[DBG][fastener_render] 没有数据需要渲染")
        # 如果没有数据，为每个参数设置默认值
        for param_name, structure, control_type, prefix in param_structures:
            if param_name == "元件名称":
                display_map[param_name] = "设备法兰紧固件"
            elif param_name == "元件所属":
                display_map[param_name] = ""  # 空值，让用户选择
            elif param_name == "表面处理工艺":
                display_map[param_name] = "/"  # 默认值
            elif param_name == "元件类型":
                display_map[param_name] = {1: "螺柱", 2: "螺母"}
            else:
                display_map[param_name] = ""  # 其他字段为空

    # 渲染参数
    for param_name, structure, control_type, prefix in param_structures:
        row = table.rowCount()
        table.insertRow(row)

        # 左侧名称列
        label_item = QTableWidgetItem(param_name)
        label_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        table.setItem(row, 0, label_item)

        option_key = prefix or param_name
        options = dropdown_options.get(option_key, [])
        value = display_map.get(param_name, "")

        if structure == "2列":
            table.setSpan(row, 1, 1, 3)

            if control_type == "combo":
                display_val = _first_non_empty(value) if isinstance(value, dict) else _normalize(value)
                item = QTableWidgetItem(display_val)
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                table.setItem(row, 1, item)
                if param_name == "元件所属":
                    # 记录「上次已知的元件所属」：仅当用户从非空改为空时才清空材料行，避免加载/刷新时空值触发误清
                    item.setData(Qt.UserRole + 2, display_val)

                if param_name == "元件名称":
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

                if options:
                    if param_name == "元件所属":
                        table.setItemDelegateForRow(row, CheckComboDelegate(options, table))
                    else:
                        table.setItemDelegateForRow(row, MultiSelectRowComboDelegate(options, table))

            elif control_type == "text":
                display_val = _first_non_empty(value) if isinstance(value, dict) else _normalize(value)
                item = QTableWidgetItem(display_val)
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                table.setItem(row, 1, item)

                if param_name == "元件名称":
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

                if param_name == "表面处理工艺":
                    item.setText("/")
                    item.setVisible(False)

        elif structure == "3列":
            value_map = display_map.get(param_name, {})
            if not isinstance(value_map, dict):
                value_map = {}

            if param_name == "元件名称":
                table.setSpan(row, 1, 1, 2)
                val = value_map.get(1, "") if value_map else display_map.get(param_name, "")
                display_val = str(val) if val and str(val) != "null" else ""
                ensure_readonly_item(row, 1, display_val)
            else:
                if param_name == "螺柱型式":
                    # 螺柱型式：螺柱侧可编辑，下游一列只读占位
                    val1 = value_map.get(1, "")
                    display_val1 = str(val1) if val1 and str(val1) != "null" else ""
                    ensure_editable_item(row, 1, display_val1)
                    ensure_readonly_item(row, 2, "-")
                elif param_name == "螺柱根径系列":
                    # 螺柱根径系列：螺柱侧为下拉选择，螺母侧固定为斜杠"/"
                    val1 = value_map.get(1, "")
                    display_val1 = str(val1) if val1 and str(val1) != "null" else ""
                    ensure_editable_item(row, 1, display_val1)
                    ensure_readonly_item(row, 2, "/")
                else:
                    for col in range(1, 3):
                        val = value_map.get(col, "")
                        display_val = str(val) if val and str(val) != "null" else ""
                        if param_name == "元件类型":
                            ensure_readonly_item(row, col, display_val or ("螺柱" if col == 1 else "螺母"))
                        else:
                            ensure_editable_item(row, col, display_val)

            if options:
                material_fields = ["材料类型", "材料牌号", "材料标准", "供货状态"]
                if control_type == "combo":
                    if param_name not in material_fields and param_name != "元件类型":
                        table.setItemDelegateForRow(row, MultiSelectRowComboDelegate(options, table))
                elif control_type == "checkcombo":
                    table.setItemDelegateForRow(row, CheckComboDelegate(options, table))

        elif structure == "4列":
            value_map = display_map.get(param_name, {})
            if not isinstance(value_map, dict):
                value_map = {}
            for col in range(1, 4):
                val = value_map.get(col, "")
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                table.setItem(row, col, item)

            if options:
                material_fields = ["材料类型", "材料牌号", "材料标准", "供货状态"]
                if control_type == "combo":
                    if param_name not in material_fields:
                        table.setItemDelegateForRow(row, MultiSelectRowComboDelegate(options, table))
                elif control_type == "checkcombo":
                    table.setItemDelegateForRow(row, CheckComboDelegate(options, table))

    header = table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
    for col in range(1, max_cols):
        header.setSectionResizeMode(col, QHeaderView.Stretch)

    # 安装材料字段联动逻辑 - 使用四联组识别方式，确保列间独立性
    try:
        from modules.cailiaodingyi.funcs.funcs_pdf_render import find_material_groups_fuzzy_strict
        from modules.cailiaodingyi.controllers.combo import MultiSelectDynamicOptionsDelegate

        groups, row2field, row2group = find_material_groups_fuzzy_strict(table)
        found_rows = sorted(row2field.keys())

        if found_rows:
            # print(f"[DBG][fastener_render] 识别到材料四联组: {len(groups)} 组，涉及行: {found_rows}")

            for r in found_rows:
                for c in range(1, max_cols):
                    it = table.item(r, c)
                    if it is None:
                        it = QTableWidgetItem("")
                        it.setTextAlignment(Qt.AlignCenter)
                        table.setItem(r, c, it)
                    it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                    if table.cellWidget(r, c):
                        table.setCellWidget(r, c, None)

            for r in found_rows:
                table.setItemDelegateForRow(r, None)
            dyn = MultiSelectDynamicOptionsDelegate(table, groups, row2field, row2group)
            for r in found_rows:
                table.setItemDelegateForRow(r, dyn)
            install_copy_paste_shortcuts(table, groups, row2field, row2group)
        else:
            if DEBUG_VERBOSE_DEFINE_UI:
                print(f"[DBG][fastener_render] 未识别到材料四联组，跳过材料联动逻辑")

    except Exception as e:
        # print(f"[DBG][fastener_render] 材料字段联动逻辑安装失败: {e}")
        import traceback
        traceback.print_exc()

    # ===== 设备法兰紧固件：按材料类型控制显隐 =====
    def _find_row_by_name(tbl, name, col=0):
        for r in range(tbl.rowCount()):
            it = tbl.item(r, col)
            if it and it.text().strip() == name:
                return r
        return None

    def _apply_fastener_surface_treatment_visibility():
        try:
            type_row = _find_row_by_name(table, "材料类型", 0)
            target_row = _find_row_by_name(table, "表面处理工艺", 0)
            if type_row is None or target_row is None:
                return

            # 读取两列材料类型（3列结构对应两值列）并判断
            show = False
            type_vals = []
            for c in range(1, max_cols):
                it = table.item(type_row, c)
                type_vals.append((it.text().strip() if it else ""))

            show = any(tv == "钢棒" for tv in type_vals)

            table.setRowHidden(target_row, not show)

            # 显示时为空则设置默认值“/”以保持一致
            if show:
                for c in range(1, max_cols):
                    vitem = table.item(target_row, c)
                    if vitem and not (vitem.text() or "").strip():
                        vitem.setText("/")
            for c in range(1, max_cols):
                it = table.item(target_row, c)
                if it is None:
                    it = QTableWidgetItem("")
                    it.setTextAlignment(Qt.AlignCenter)
                    table.setItem(target_row, c, it)
                tv = type_vals[c-1] if c-1 < len(type_vals) else ""
                if tv == "钢棒":
                    it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                else:
                    it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                    if not (it.text() or "").strip():
                        it.setText("/")
        except Exception as _e:
            print(f"[设备法兰显隐] 表面处理工艺显隐更新失败: {_e}")

    def _apply_fastener_forging_grade_visibility():
        try:
            type_row = _find_row_by_name(table, "材料类型", 0)
            target_row = _find_row_by_name(table, "锻件级别", 0)
            if type_row is None or target_row is None:
                return

            type_vals = []
            for c in range(1, max_cols):
                it = table.item(type_row, c)
                type_vals.append((it.text().strip() if it else ""))

            show = any(tv == "钢锻件" for tv in type_vals)
            table.setRowHidden(target_row, not show)

            if show:
                for c in range(1, max_cols):
                    vitem = table.item(target_row, c)
                    if vitem is None:
                        vitem = QTableWidgetItem("")
                        vitem.setTextAlignment(Qt.AlignCenter)
                        table.setItem(target_row, c, vitem)
            for c in range(1, max_cols):
                it = table.item(target_row, c)
                if it is None:
                    it = QTableWidgetItem("")
                    it.setTextAlignment(Qt.AlignCenter)
                    table.setItem(target_row, c, it)
                tv = type_vals[c-1] if c-1 < len(type_vals) else ""
                if tv == "钢锻件":
                    it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                    cur_txt = (it.text() or "").strip()
                    if cur_txt in {"", "/", "-"}:
                        try:
                            cand = dropdown_options.get("锻件级别", []) or []
                            if "Ⅱ" in cand:
                                it.setText("Ⅱ")
                            elif cand:
                                # 取首个非空候选
                                it.setText(next((x for x in cand if (x or '').strip()), "/"))
                            else:
                                it.setText("/")
                        except Exception:
                            it.setText("Ⅱ")
                else:
                    it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                    it.setText("-" if show else "/")
        except Exception as _e:
            print(f"[设备法兰显隐] 锻件级别显隐更新失败: {_e}")

    # 初次渲染时应用一次显隐规则
    _apply_fastener_surface_treatment_visibility()
    _apply_fastener_forging_grade_visibility()

    def _on_item_changed(item: QTableWidgetItem):
        # 总闸
        if getattr(table, "_loading", False):
            return
        if getattr(table, "_fastener_suppress_belonging_clear", False):
            return
        if item.column() == 0:  # 参数名称列不处理
            return

        r = item.row()
        pitem = table.item(r, 0)
        if not pitem:
            return

        pname = pitem.text().strip()
        val = (item.text() or "").strip()
        # print(f"[设备法兰紧固件-参数修改] {pname}={val} (仅UI更新，未保存到数据库)")

        # 当材料类型修改时，更新相关显隐
        if pname == "材料类型":
            _apply_fastener_surface_treatment_visibility()
            _apply_fastener_forging_grade_visibility()
        if pname == "元件所属":
            it_own = table.item(r, 1)
            prev_raw = it_own.data(Qt.UserRole + 2) if it_own else None
            prev = "" if prev_raw is None else str(prev_raw)
            try:
                refresh_fastener_belonging_candidates(viewer_instance)
            except Exception as _e:
                print(f"[设备法兰紧固件] 刷新元件所属候选失败: {_e}")
            if _is_empty_belonging_text(val) and (not _is_empty_belonging_text(prev)):
                _clear_on_empty_belonging()
            if it_own:
                it_own.setData(Qt.UserRole + 2, val)

    def _select_row_first(r, c):
        table.selectRow(r)

    table.setEditTriggers(QAbstractItemView.SelectedClicked)

    def _edit_on_click(r, c):
        idx = table.model().index(r, c)
        it = table.item(r, c)
        if idx.isValid() and it and (it.flags() & Qt.ItemIsEditable):
            table.setCurrentIndex(idx)
            table.edit(idx)

    # 绑定事件
    try:
        table.itemChanged.disconnect()
    except Exception:
        pass
    table.itemChanged.connect(_on_item_changed)

    try:
        table.cellPressed.disconnect()
    except Exception:
        pass
    table.cellPressed.connect(_select_row_first)

    try:
        table.cellClicked.disconnect()
    except Exception:
        pass
    table.cellClicked.connect(_edit_on_click)

    _set_table_tooltips(table)
    _install_tooltip_updater(table)


def refresh_fastener_belonging_candidates(viewer_instance):
    try:
        all_options = getattr(viewer_instance, 'fastener_component_all_options', []) or []
        tabs = getattr(viewer_instance, 'dynamic_fastener_param_tabs', {}) or {}
        if not tabs:
            return
        used_by_tab_ui = {}
        from PyQt5.QtWidgets import QTableWidgetItem
        from PyQt5.QtCore import Qt
        def _find_row(tbl, name):
            for r in range(tbl.rowCount()):
                it = tbl.item(r, 0)
                if it and it.text().strip() == name:
                    return r
            return None
        import json
        tbl_list = list(tabs.values())
        for tbl in tbl_list:
            tbl.blockSignals(True)
            setattr(tbl, '_fastener_suppress_belonging_clear', True)
        try:
            for tab_name, tbl in tabs.items():
                r = _find_row(tbl, '元件所属')
                sel = set()
                if r is not None:
                    it = tbl.item(r, 1)
                    txt = (it.text() or '').strip() if it else ''
                    vals = []
                    if txt.startswith('['):
                        try:
                            parsed = json.loads(txt)
                            if isinstance(parsed, list):
                                vals = [str(x).strip() for x in parsed if str(x).strip()]
                        except Exception:
                            vals = []
                    if not vals:
                        vals = [x.strip() for x in txt.split('、') if x.strip()]
                    sel = set(vals)
                used_by_tab_ui[tab_name] = sel
            for tab_name, tbl in tabs.items():
                already = set()
                for t, vs in used_by_tab_ui.items():
                    if t != tab_name:
                        already |= (vs or set())
                filtered = [x for x in all_options if x not in already]
                curr = used_by_tab_ui.get(tab_name, set()) or set()
                for v in curr:
                    if v and v not in filtered:
                        filtered.append(v)
                try:
                    tbl.setProperty('gk_code_candidates', filtered)
                except Exception:
                    pass
                r = _find_row(tbl, '元件所属')
                if r is None:
                    continue
                it = tbl.item(r, 1)
                if it is None:
                    it = QTableWidgetItem('')
                    it.setTextAlignment(Qt.AlignCenter)
                    it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                    tbl.setItem(r, 1, it)
                from modules.cailiaodingyi.controllers.checkcombo import CheckComboDelegate
                if filtered:
                    tbl.setItemDelegateForRow(r, CheckComboDelegate(filtered, tbl))
                else:
                    tbl.setItemDelegateForRow(r, None)
        finally:
            for tbl in tbl_list:
                setattr(tbl, '_fastener_suppress_belonging_clear', False)
                tbl.blockSignals(False)
    except Exception as e:
        print(f"[设备法兰紧固件] 刷新候选失败: {e}")




