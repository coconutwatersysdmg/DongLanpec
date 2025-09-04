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
from modules.cailiaodingyi.funcs.funcs_pdf_change import get_filtered_material_options
from modules.cailiaodingyi.funcs.funcs_pdf_input import load_guankou_param_structure_from_db, load_dropdown_options, \
    query_unassigned_codes, query_codes_for_tab_raw


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
                    if not has_overlay:
                        for cc in value_cols:
                            _clear_cell(rr, cc)

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
                        for cc in value_cols:
                            _clear_cell(_grade_row, cc)
                    else:
                        table.setRowHidden(_grade_row, False)
                        for cc in value_cols:
                            t = _get_text(_type_row, cc) if _type_row >= 0 else ""
                            if t in _weld_values:
                                _set_cell_enabled(_grade_row, cc, False)
                                _clear_cell(_grade_row, cc)
                            else:
                                _set_cell_enabled(_grade_row, cc, True)


                # 2.2 使用状态（显隐 + 单列禁用）
                if _status_row >= 0:
                    if all_weld:
                        table.setRowHidden(_status_row, True)
                        for cc in value_cols:
                            _clear_cell(_status_row, cc)
                    else:
                        table.setRowHidden(_status_row, False)
                        for cc in value_cols:
                            t = _get_text(_type_row, cc) if _type_row >= 0 else ""
                            if t in _weld_values:
                                _set_cell_enabled(_status_row, cc, False)
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

    # 这几个是你要改成数值输入的行名（可按需要继续加）
    NUM_GE0 = {
        "接管腐蚀裕量(mm)",
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
                    table.setItemDelegateForRow(row, MultiSelectRowComboDelegate(options, table))

            elif control_type == "checkcombo":
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                table.setItem(row, 1, item)
                if options:
                    table.setItemDelegateForRow(row, CheckComboDelegate(options, table))

            elif control_type == "empty":
                item = QTableWidgetItem("")
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
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
                    table.setItemDelegateForRow(row, CheckComboDelegate(opts, table))

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
        table.setItemDelegateForRow(r, NumericDelegate(rule, pname, table, viewer_instance))


    table.setEditTriggers(QAbstractItemView.SelectedClicked)

    install_copy_paste_shortcuts(table, groups, row2field, row2group)

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

    print(f"[DBG][render] 完成渲染 tab={repr(cur_tab)}  最终行数={table.rowCount()}")










