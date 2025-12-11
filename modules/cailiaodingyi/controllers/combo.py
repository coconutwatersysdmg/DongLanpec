from PyQt5 import QtCore, sip
from PyQt5.QtGui import QColor, QStandardItem
from PyQt5.QtWidgets import QTableWidgetItem, QComboBox, QStyledItemDelegate, QAbstractItemView
from PyQt5.QtCore import Qt, QObject, QTimer, QItemSelectionModel
from PyQt5.QtCore import QEvent

from modules.cailiaodingyi.funcs.funcs_pdf_change import get_filtered_material_options


from PyQt5.QtGui import QColor, QStandardItem
from PyQt5.QtWidgets import QTableWidgetItem, QComboBox, QStyledItemDelegate
from PyQt5.QtCore import Qt, QObject, QTimer, QItemSelectionModel
from PyQt5.QtCore import QEvent


class ComboDelegate(QStyledItemDelegate):
    def __init__(self, options, table=None):
        super().__init__(table)
        self.options = options or []
        self.table = table

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.setEditable(False)

        # 加载选项 & 行高亮（保持你原来的逻辑）
        opts = self.options or []
        if not opts or (opts and opts[0] != ""):
            opts = [""] + list(dict.fromkeys(opts))
        combo.addItems(opts)
        if self.table:
            self.highlight_row(index.row())

        # 对齐当前值
        cur = index.data() or ""
        i = combo.findText(cur)
        combo.setCurrentIndex(max(0, i))

        # 关键：进入编辑后自动展开一次（现在只会由“用户操作”触发进入编辑）
        QTimer.singleShot(0, combo.showPopup)

        combo.activated.connect(lambda _: self._commit_and_close(combo))
        return combo


    def setEditorData(self, editor, index):
        txt = index.model().data(index, Qt.EditRole) or ""
        i = editor.findText(txt)
        editor.setCurrentIndex(max(0, i))

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.EditRole)
        # 居中
        r, c = index.row(), index.column()
        it = self.table.item(r, c)
        if it is None:
            it = QTableWidgetItem()
            self.table.setItem(r, c, it)
        it.setText(editor.currentText() or "")
        it.setTextAlignment(Qt.AlignCenter)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)

    def _commit_and_close(self, editor):
        self.commitData.emit(editor)
        self.closeEditor.emit(editor, QStyledItemDelegate.NoHint)

    def setModelData(self, editor, model, index):
        r, c = index.row(), index.column()
        model.setData(index, editor.currentText(), Qt.EditRole)

        it = self.table.item(r, c)
        if it is None:
            it = QTableWidgetItem()
            self.table.setItem(r, c, it)
        it.setText(editor.currentText() or "")
        it.setTextAlignment(Qt.AlignCenter)

        # 立即恢复当前格 + 高亮（防止外部逻辑在稍后把 current 清掉）
        self.table.setCurrentCell(r, c)
        if hasattr(self, "highlight_row"):
            self.highlight_row(r)

    def highlight_row(self, row):
        """保留你原来的整行高亮效果"""
        for r in range(self.table.rowCount()):
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                if item:
                    item.setBackground(QColor("#ffffff"))
        for c in range(self.table.columnCount()):
            item = self.table.item(row, c)
            if item:
                item.setBackground(QColor("#d0e7ff"))

def _row_value_cols(table, row, *, exclude_col=None):
    """返回该行可写入的 1/2/3 列（可编辑的列）。"""
    cols = []
    for c in (1, 2, 3):
        if exclude_col is not None and c == exclude_col:
            continue
        it = table.item(row, c)
        if it and (it.flags() & Qt.ItemIsEditable):
            cols.append(c)
    return cols

def _set_text_center(table, r, c, text):
    it = table.item(r, c)
    if it is None:
        it = QTableWidgetItem()
        it.setTextAlignment(Qt.AlignCenter)
        table.setItem(r, c, it)
    it.setText(text or "")

class RowFillComboDelegate(ComboDelegate):
    """
    单元格选择一个下拉值后，把相同的值写入“本行其余可编辑的值列(1/2/3)”
    """
    def setModelData(self, editor, model, index):
        # 1) 先按原逻辑把当前格写回（含居中）
        super().setModelData(editor, model, index)

        row, col = index.row(), index.column()
        new_text = editor.currentText()

        # 2) 同步到本行其他可编辑的值列
        targets = _row_value_cols(self.table, row, exclude_col=col)
        if not targets:
            return

        self.table.blockSignals(True)
        try:
            for cc in targets:
                _set_text_center(self.table, row, cc, new_text)
        finally:
            self.table.blockSignals(False)
        self.table.setCurrentCell(row, col)


class ProcessPerColumnDelegate(QStyledItemDelegate):
    """
    成型工艺行专用代理：根据“覆层材料类型”本列的取值决定下拉候选。
    """
    def __init__(self, table, type_row, plate_values, weld_values,
                 plate_options, weld_options):
        super().__init__(table)
        self.table = table
        self.type_row = type_row
        self.plate_values = set(plate_values)
        self.weld_values  = set(weld_values)
        self.plate_options = list(plate_options)
        self.weld_options  = list(weld_options)

    def _type_text(self, col):
        w = self.table.cellWidget(self.type_row, col)
        if isinstance(w, QComboBox):
            return w.currentText().strip()
        it = self.table.item(self.type_row, col)
        return it.text().strip() if it else ""

    def createEditor(self, parent, option, index):
        cb = QComboBox(parent)
        t = self._type_text(index.column())
        if t in self.plate_values:
            opts = self.plate_options
        elif t in self.weld_values:
            opts = self.weld_options
        else:
            # 类型未知/为空时给个并集，防止下拉空白（按需可改）
            opts = list(dict.fromkeys(self.plate_options + self.weld_options))
        cb.addItems(opts if "" in opts else [""] + opts)
        return cb

    def setEditorData(self, editor, index):
        cur = index.data() or ""
        i = editor.findText(cur)
        editor.setCurrentIndex(0 if i < 0 else i)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText())

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class NonNegativeDoubleDelegate(QStyledItemDelegate):
    """
    给某一行装上后：该行所有可编辑单元格都用带下限的 QDoubleValidator。
    bottom: 允许的最小值（默认 0.0）
    decimals: 小数位数
    """
    def __init__(self, bottom=0.0, decimals=6, parent=None):
        super().__init__(parent)
        self.bottom = float(bottom)
        self.decimals = int(decimals)

    def createEditor(self, parent, option, index):
        from PyQt5.QtWidgets import QLineEdit
        from PyQt5.QtGui import QDoubleValidator
        le = QLineEdit(parent)
        v = QDoubleValidator(self.bottom, 1e12, self.decicals if hasattr(self, "decicals") else self.decimals, le)
        v.setNotation(QDoubleValidator.StandardNotation)
        le.setValidator(v)
        le.setAlignment(Qt.AlignCenter)
        return le

    def setEditorData(self, editor, index):
        editor.setText((index.data() or "").strip())

    def setModelData(self, editor, model, index):
        model.setData(index, editor.text().strip())


class MaterialInstantDelegate(ComboDelegate):
    """
    用于‘材料类型/材料牌号/材料标准/供货状态’四字段：
    - 选项改变时，立即写回模型、关闭编辑器；
    - 把“新值 + 行/列 + 字段名”回调给外部进行联动；
    """
    def __init__(self, options, table=None, field_name=None, on_pick=None):
        super().__init__(options, table)
        self.field_name = field_name
        self.on_pick = on_pick  # 回调签名: on_pick(field_name, new_text, row, col)

    def createEditor(self, parent, option, index):
        ed = super().createEditor(parent, option, index)

        def _commit_and_close():
            # 1) 写回
            self.commitData.emit(ed)
            # 2) 关闭编辑器（确保视觉与取值立刻更新）
            self.closeEditor.emit(ed, QStyledItemDelegate.NoHint)
            # 3) 下一拍回调联动（此时模型里已经是新值）
            if self.on_pick:
                r, c = index.row(), index.column()
                new_text = ed.currentText()
                QtCore.QTimer.singleShot(0, lambda: self.on_pick(self.field_name, new_text, r, c))

        # 任一变化都执行；不自动 showPopup
        ed.activated.connect(lambda _=None: _commit_and_close())
        ed.currentIndexChanged.connect(lambda _=None: _commit_and_close())
        ed.currentTextChanged.connect(lambda _=None: _commit_and_close())
        return ed

    def setModelData(self, editor, model, index):
        # 维持你原 ComboDelegate 的写回逻辑（包括居中对齐）
        super().setModelData(editor, model, index)










class ComboPopupEventFilter(QObject):
    def __init__(self, table):
        super().__init__(table)
        self.table = table

    def eventFilter(self, obj, event):
        if not hasattr(self, "table") or self.table is None:
            return False
        if sip.isdeleted(self.table):  # 需要 import sip
            return False
        # 只拦截 viewport 上的点击，避免影响别处
        if obj is self.table.viewport() and event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
            idx = self.table.indexAt(event.pos())
            if idx.isValid():
                sm = self.table.selectionModel()
                sel = sm.selectedIndexes() if sm else []
                # 判断：同一行是否有多列被选（只数 1/2/3 这三列的可编辑格）
                same_row_cols = sorted({
                    i.column() for i in sel
                    if i.row() == idx.row()
                    and self.table.item(i.row(), i.column())
                    and (self.table.item(i.row(), i.column()).flags() & Qt.ItemIsEditable)
                })
                if len(same_row_cols) >= 2:
                    # 关键：阻止 Qt 自己的选区处理（否则会清成 1 个）
                    event.accept()
                    QTimer.singleShot(0, lambda: self.table.edit(idx))
                    return True   # ⬅⬅⬅ 一定要返回 True
        return False





def _read_col_values(table, col: int, rows_map: dict):
    vals = {}
    for f, r in rows_map.items():
        it = table.item(r, col)
        vals[f] = (it.text().strip() if it else "")
    return vals

def _write_cell(table, row: int, col: int, text: str):
    it = table.item(row, col)
    if it is None:
        it = QTableWidgetItem()
        it.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, col, it)   # 仅在确实没有时创建
    else:
        # 复用已有 item，避免频繁 setItem 导致 currentIndex 丢失
        pass
    it.setText(text or "")


def on_material_field_changed_col(table, col: int, rows_map: dict, sender_field: str, prev_value: str = None):
    # 添加防重复执行标志
    if not hasattr(table, '_material_changing'):
        table._material_changing = False

    if table._material_changing:
        return  # 正在处理中，跳过

    table._material_changing = True

    try:
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

        # 获取行号
        r_type = rows_map.get('材料类型')
        r_brand = rows_map.get('材料牌号')
        r_std = rows_map.get('材料标准')
        r_status = rows_map.get('供货状态')

        # 读取当前值
        cur_type = _get(r_type)
        cur_brand = _get(r_brand)
        cur_std = _get(r_std)
        cur_status = _get(r_status)

        # 完全模仿普通元件的 on_pick 逻辑
        from modules.cailiaodingyi.funcs.funcs_pdf_change import get_filtered_material_options

        if sender_field == '材料类型':
            # 材料类型变化：清空后续字段，重新安装 delegate
            new_val = cur_type
            # prev_value 只有在 delegate 里会传；为 None 时视为"已变化"（用于批量写入）
            if prev_value is not None and (new_val or "") == (prev_value or ""):
                return

            # 清空后续字段
            table.blockSignals(True)
            try:
                for rr in (r_brand, r_std, r_status):
                    if rr is not None:
                        _set(rr, "")
            finally:
                table.blockSignals(False)

            # 重新安装 delegate（模仿普通元件的逻辑）
            _reinstall_material_delegates(table, col, rows_map, cur_type, cur_brand, cur_std)

        elif sender_field == '材料牌号':
            # 材料牌号变化：清空材料标准和供货状态，重新获取选项，自动选择唯一值
            table.blockSignals(True)
            try:
                # 先清空材料标准和供货状态
                if r_std is not None:
                    _set(r_std, "")
                if r_status is not None:
                    _set(r_status, "")
            finally:
                table.blockSignals(False)

            # 重新获取选项
            f = get_filtered_material_options({"材料类型": cur_type, "材料牌号": cur_brand}) or {}
            std_opts = f.get("材料标准", []) or []
            stat_opts = f.get("供货状态", []) or []

            # 自动选择唯一选项
            table.blockSignals(True)
            try:
                if len(std_opts) == 1:
                    _set(r_std, std_opts[0])
                if len(stat_opts) == 1:
                    _set(r_status, stat_opts[0])
            finally:
                table.blockSignals(False)

            # 重新安装 delegate
            _reinstall_material_delegates(table, col, rows_map, cur_type, cur_brand, cur_std)

        elif sender_field == '材料标准':
            # 材料标准变化：更新供货状态选项，自动选择唯一选项
            f = get_filtered_material_options({"材料类型": cur_type, "材料牌号": cur_brand, "材料标准": cur_std}) or {}
            stat_opts = f.get("供货状态", []) or []

            # 自动选择唯一选项
            if (not cur_status) and len(stat_opts) == 1:
                table.blockSignals(True)
                try:
                    _set(r_status, stat_opts[0])
                finally:
                    table.blockSignals(False)

            # 重新安装 delegate
            _reinstall_material_delegates(table, col, rows_map, cur_type, cur_brand, cur_std)

        # 供货状态变化：不做任何处理（最后一个字段）

    finally:
        table._material_changing = False


def _reinstall_material_delegates(table, col: int, rows_map: dict, cur_type: str, cur_brand: str, cur_std: str):
    """重新安装材料字段的 delegate，模仿普通元件的逻辑"""
    # 由于 DynamicOptionsDelegate 的 createEditor 方法每次都会重新计算选项，
    # 我们不需要强制重新安装 delegate，只需要确保数据已经正确更新
    # 让用户下次点击时自然触发 createEditor 重新计算选项

    # 简单触发视图更新，让用户知道数据已变化
    table.viewport().update()






class DynamicOptionsDelegate(ComboDelegate):
    def __init__(self, table, groups, row2field, row2group):
        super().__init__(options=[], table=table)
        self.groups = groups              # [ {字段->行号}, ... ]
        self.row2field = row2field        # {行号->字段}
        self.row2group = row2group        # {行号->组idx}

    def _field_of_row(self, row: int):
        return self.row2field.get(row, "")

    def _group_map_of_row(self, row: int):
        gi = self.row2group.get(row, None)
        return (self.groups[gi] if gi is not None and 0 <= gi < len(self.groups) else {})

    def _all_material_types(self):
        all_map = get_filtered_material_options({}) or {}
        # 去重保序
        return list(dict.fromkeys(all_map.get('材料类型', [])))

    def createEditor(self, parent, option, index):
        row, col = index.row(), index.column()
        field = self._field_of_row(row)
        if field not in ('材料类型', '材料牌号', '材料标准', '供货状态'):
            return None

        group_map = self._group_map_of_row(row)
        # 组内当前选择
        selected = {}
        for k in ('材料类型', '材料牌号', '材料标准', '供货状态'):
            rr = group_map.get(k)
            it = self.table.item(rr, col) if rr is not None else None
            selected[k] = (it.text().strip() if it else "")

        if field == '材料类型':
            opts = self._all_material_types()
        else:
            all_options = get_filtered_material_options(selected) or {}
            opts = all_options.get(field, [])

        if not opts or opts[0] != "":
            opts = [""] + list(dict.fromkeys(opts))
        self.options = opts

        ed = super().createEditor(parent, option, index)

        # 对齐当前值（支持直接点击即弹出）
        cur = index.data() or ""
        i = ed.findText(cur)
        ed.setCurrentIndex(max(0, i))
        return ed

    def setModelData(self, editor, model, index):
        # 先拿旧值
        old_val = index.data() or ""

        # 1) 正常写回（含居中）
        super().setModelData(editor, model, index)

        # 2) 联动：仅当真的变化才会在函数里清空
        row, col = index.row(), index.column()
        sender_field = self._field_of_row(row)
        if sender_field in ('材料类型', '材料牌号', '材料标准', '供货状态'):
            group_map = self._group_map_of_row(row)
            on_material_field_changed_col(self.table, col, group_map, sender_field, prev_value=old_val)

        self.table.setCurrentCell(row, col)



class BulkFillDynamicOptionsDelegate(DynamicOptionsDelegate):
    """
    支持“多选列 -> 一次选择 -> 批量写入”的材料四字段下拉代理。
    仅作用于同一行被多选的多列；逐列校验候选，不合法则跳过。
    """
    def _editable(self, r, c):
        it = self.table.item(r, c)
        return bool(it and (it.flags() & Qt.ItemIsEditable))

    def _selected_editable_cols_same_row(self, row, anchor_col):
        # 仅取与当前行相同、且可编辑的列
        cols = set()
        sm = self.table.selectionModel()
        if sm:
            for idx in sm.selectedIndexes():
                if idx.row() == row and self._editable(row, idx.column()):
                    cols.add(idx.column())
        # 如果只选了一个格，也允许“扩展到整行的可编辑列”
        if not cols:
            for c in range(self.table.columnCount()):
                if self._editable(row, c):
                    cols.add(c)
        # 保证当前列在集合里
        cols.add(anchor_col)
        return sorted(cols)

    def _current_group_values_at_col(self, group_map, col):
        cur = {}
        for k in ('材料类型','材料牌号','材料标准','供货状态'):
            rr = group_map.get(k)
            it = self.table.item(rr, col) if rr is not None else None
            cur[k] = (it.text().strip() if it else "")
        return cur

    def setModelData(self, editor, model, index):
        # 1) 先把当前格写回（含居中），与原类一致
        old_val = index.data() or ""
        super().setModelData(editor, model, index)

        row, col = index.row(), index.column()
        sender_field = self._field_of_row(row)
        if sender_field not in ('材料类型', '材料牌号', '材料标准', '供货状态'):
            self.table.setCurrentCell(row, col)
            return

        new_val = editor.currentText()
        group_map = self._group_map_of_row(row)

        # 2) 计算同一行被多选的其它列
        target_cols = self._selected_editable_cols_same_row(row, col)

        # 3) 逐列校验候选并写入
        from modules.cailiaodingyi.funcs.funcs_pdf_change import get_filtered_material_options

        def _set_cell_text(r, c, txt):
            it = self.table.item(r, c)
            if it is None:
                it = QTableWidgetItem()
                it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, it)
            it.setText(txt or "")

        # 先保存一下“类型变更会清空三项”的联动规则，我们稍后逐列手动触发
        self.table.blockSignals(True)
        try:
            for cc in target_cols:
                # 跳过当前列以外的列若不可编辑
                if not self._editable(row, cc):
                    continue

                # 基于【该列】当前选择组合拿候选
                cur_vals = self._current_group_values_at_col(group_map, cc)

                if sender_field == '材料类型':
                    # 材料类型的候选是全集（和你现逻辑一致）
                    all_map = get_filtered_material_options({}) or {}
                    opts = list(dict.fromkeys(all_map.get('材料类型', [])))
                else:
                    filtered = get_filtered_material_options(cur_vals) or {}
                    opts = filtered.get(sender_field, []) or []

                # 保留你之前的“首个空项”习惯
                if not opts or opts[0] != "":
                    opts = [""] + list(dict.fromkeys(opts))

                if new_val in opts:
                    rr = group_map.get(sender_field)
                    if rr is not None:
                        cur_txt = (self.table.item(rr, cc).text().strip()
                                   if self.table.item(rr, cc) else "")
                        if cur_txt != new_val:  # 🔒 未变化不写，避免无意义联动
                            _set_cell_text(rr, cc, new_val)
        finally:
            self.table.blockSignals(False)

        # 4) 批量联动：对写入过的每个列各触发一次
        for cc in target_cols:
            if cc == col:
                continue  # 当前列已在 super().setModelData 里正确联动过
            prev_cc = self._current_group_values_at_col(group_map, cc).get(sender_field, "")
            if prev_cc == new_val:
                continue  # 这列没发生变化，无需联动
            on_material_field_changed_col(self.table, cc, group_map, sender_field, prev_value=prev_cc)

        self.table.setCurrentCell(row, col)





class MultiSelectRowComboDelegate(ComboDelegate):
    """普通下拉：同一行横向多选(>=2)才批量写入；否则只改当前格"""

    def __init__(self, options, table=None):
        super().__init__(options, table)
        self._targets_cache = []  # ⬅️ 新增

    def _snapshot_targets(self, row: int):
        cols = []
        sm = self.table.selectionModel() if self.table else None
        if sm:
            for i in sm.selectedIndexes():
                if i.row() == row:
                    it = self.table.item(row, i.column())
                    if it and (it.flags() & Qt.ItemIsEditable):
                        cols.append(i.column())
        cols = sorted(set(cols))
        return cols

    def createEditor(self, parent, option, index):
        # ⬅️ 进入编辑前先把“多选列”快照下
        self._targets_cache = self._snapshot_targets(index.row())
        return super().createEditor(parent, option, index)

    def _selected_cols_same_row(self, row):
        sm = self.table.selectionModel()
        if not sm: return []
        cols = sorted({i.column()
                       for i in sm.selectedIndexes()
                       if i.row() == row and self.table.item(row, i.column())
                       and (self.table.item(row, i.column()).flags() & Qt.ItemIsEditable)})
        return cols if len(cols) >= 2 else []

    def setModelData(self, editor, model, index):
        # 1) 先正常写回当前格（含居中）
        super().setModelData(editor, model, index)

        row, col = index.row(), index.column()
        new_text = editor.currentText()

        # 2) 用快照批量写入（没有快照再兜底计算一次）
        targets = list(self._targets_cache) if self._targets_cache else self._snapshot_targets(row)
        self._targets_cache = []  # ⬅️ 用完清空

        if not targets:
            return

        self.table.blockSignals(True)
        try:
            for cc in targets:
                if cc == col:
                    continue
                it = self.table.item(row, cc) or QTableWidgetItem()
                it.setTextAlignment(Qt.AlignCenter)
                it.setText(new_text or "")
                self.table.setItem(row, cc, it)
        finally:
            self.table.blockSignals(False)
        self.table.setCurrentCell(row, col)


# —— 在 combo.py 中（建议放在 DynamicOptionsDelegate 定义之后）——

class MultiSelectDynamicOptionsDelegate(DynamicOptionsDelegate):
    """材料四字段：只有多选时才批量；逐列校验候选并逐列联动（带各自 prev）"""

    def __init__(self, table, groups, row2field, row2group):
        super().__init__(table, groups, row2field, row2group)
        self._targets_cache = []  # 进入编辑前的“同一行已选中的可编辑列”快照

    def _snapshot_targets(self, row: int):
        sm = self.table.selectionModel() if self.table else None
        if not sm:
            return []
        cols = sorted({
            i.column() for i in sm.selectedIndexes()
            if i.row() == row
               and self.table.item(row, i.column())
               and (self.table.item(row, i.column()).flags() & Qt.ItemIsEditable)
        })
        return cols if len(cols) >= 2 else []

    # ---------- 新增：材料牌号进入编辑时，仅按“材料类型”取全集 ----------
    def createEditor(self, parent, option, index):
        from PyQt5.QtWidgets import QComboBox
        from modules.cailiaodingyi.funcs.funcs_pdf_change import get_filtered_material_options

        # 进入编辑前先快照多选列
        self._targets_cache = self._snapshot_targets(index.row())

        field = self._field_of_row(index.row())
        if field == '材料牌号':
            grp = self._group_map_of_row(index.row()) or {}
            type_row = grp.get('材料类型')
            # 同列（index.column()）下，读取“材料类型”的当前值
            cur_type = ""
            if type_row is not None:
                it = self.table.item(type_row, index.column())
                cur_type = (it.text().strip() if it else "")

            # 仅按类型过滤，拿到“该类型下的所有牌号”
            brand_opts = []
            if cur_type:
                m = get_filtered_material_options({'材料类型': cur_type}) or {}
                brand_opts = list(dict.fromkeys(m.get('材料牌号', []) or []))

            # 构造一个简单的单选下拉（与 MaterialInstantDelegate 行为一致）
            cb = QComboBox(parent)
            cb.setEditable(False)
            cb.addItems(brand_opts)

            # 添加自动提交机制，模仿 MaterialInstantDelegate
            def _commit_and_close():
                # 1) 写回
                self.commitData.emit(cb)
                # 2) 关闭编辑器（确保视觉与取值立刻更新）
                self.closeEditor.emit(cb, QStyledItemDelegate.NoHint)

            # 连接选择变化事件，立即提交
            cb.activated.connect(lambda _=None: _commit_and_close())
            cb.currentIndexChanged.connect(lambda _=None: _commit_and_close())

            # 进入即弹出，体验一致
            QTimer.singleShot(0, cb.showPopup)
            return cb

        # 其他字段仍用父类默认编辑器
        return super().createEditor(parent, option, index)

    def _cur_vals(self, grp, col):
        d = {}
        for k in ('材料类型','材料牌号','材料标准','供货状态'):
            rr = grp.get(k)
            it = self.table.item(rr, col) if rr is not None else None
            d[k] = (it.text().strip() if it else "")
        return d

    # 补充分支：当 editor 是我们为“材料牌号”创建的 QComboBox 时，正确设置当前值
    def setEditorData(self, editor, index):
        from PyQt5.QtWidgets import QComboBox
        field = self._field_of_row(index.row())
        if isinstance(editor, QComboBox) and field == '材料牌号':
            cur = (index.data() or "").strip()
            if cur:
                pos = editor.findText(cur)
                if pos >= 0:
                    editor.setCurrentIndex(pos)
            return  # 其他字段交给父类
        return super().setEditorData(editor, index)

    # 写回：若是“材料牌号”的 QComboBox，用其 currentText 写回，然后继续走后续批量联动逻辑
    def setModelData(self, editor, model, index):
        from PyQt5.QtWidgets import QComboBox
        field = self._field_of_row(index.row())
        if isinstance(editor, QComboBox) and field == '材料牌号':
            txt = editor.currentText() or ""
            model.setData(index, txt)  # 先把当前格写回
            # 然后走父类（会继续触发你的单列联动）；父类可能会再次 setData，但值相同无影响
            super().setModelData(editor, model, index)
        else:
            super().setModelData(editor, model, index)

        # ===== 以下保持你原有的批量逻辑不变 =====
        row, col = index.row(), index.column()
        sender_field = self._field_of_row(row)
        if sender_field not in ('材料类型', '材料牌号', '材料标准', '供货状态'):
            return

        targets = list(getattr(self, "_targets_cache", []) or self._snapshot_targets(row))
        self._targets_cache = []
        if not targets:
            return

        grp = self._group_map_of_row(row)
        new_val = model.data(index) or ""

        from modules.cailiaodingyi.funcs.funcs_pdf_change import get_filtered_material_options

        # 1) 如果改了“材料类型”，清空其余三项（逐列）
        if sender_field == '材料类型':
            type_row = grp.get('材料类型')
            brand_row = grp.get('材料牌号')
            std_row = grp.get('材料标准')
            stat_row = grp.get('供货状态')

            self.table.blockSignals(True)
            try:
                cols_to_apply = sorted(set(targets + [col]))
                for cc in cols_to_apply:
                    old_type = ""
                    if type_row is not None:
                        it = self.table.item(type_row, cc)
                        old_type = (it.text().strip() if it else "")
                    if (new_val or "") != (old_type or ""):
                        for rr in (brand_row, std_row, stat_row):
                            if rr is None:
                                continue
                            it2 = self.table.item(rr, cc)
                            if it2 is None:
                                it2 = QTableWidgetItem("")
                                it2.setTextAlignment(Qt.AlignCenter)
                                self.table.setItem(rr, cc, it2)
                            if it2.text():
                                it2.setText("")
            finally:
                self.table.blockSignals(False)

        # 2) 批量把“同字段”的值写到其它被选列（并做候选校验）
        touched_cols = []
        self.table.blockSignals(True)
        try:
            for cc in targets:
                if cc == col:
                    continue
                # 该列的当前四字段
                cur_vals = {}
                for k in ('材料类型', '材料牌号', '材料标准', '供货状态'):
                    rr = grp.get(k)
                    it = self.table.item(rr, cc) if rr is not None else None
                    cur_vals[k] = (it.text().strip() if it else "")

                # 候选生成逻辑：材料牌号只看“类型”，其余照旧
                if sender_field == '材料类型':
                    all_map = get_filtered_material_options({}) or {}
                    opts = list(dict.fromkeys(all_map.get('材料类型', [])))
                else:
                    if sender_field == '材料牌号' and cur_vals.get('材料类型'):
                        filtered = get_filtered_material_options({'材料类型': cur_vals['材料类型']}) or {}
                        opts = filtered.get('材料牌号', []) or []
                    else:
                        filtered = get_filtered_material_options(cur_vals) or {}
                        opts = filtered.get(sender_field, []) or []

                if not opts or (opts and opts[0] != ""):
                    opts = [""] + list(dict.fromkeys(opts))

                if new_val in opts:
                    rr = grp.get(sender_field)
                    if rr is not None:
                        it = self.table.item(rr, cc) or QTableWidgetItem()
                        it.setTextAlignment(Qt.AlignCenter)
                        self.table.setItem(rr, cc, it)
                        if it.text().strip() != (new_val or ""):
                            it.setText(new_val or "")
                            touched_cols.append(cc)
        finally:
            self.table.blockSignals(False)

        # 3) 逐列触发联动回调
        for cc in touched_cols:
            if cc == col:
                continue
            prev_cc = ""
            on_material_field_changed_col(self.table, cc, grp, sender_field, prev_value=prev_cc)













