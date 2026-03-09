from PyQt5.QtWidgets import QStyledItemDelegate, QComboBox, QTableWidgetItem
from PyQt5.QtGui import QStandardItemModel, QStandardItem, QColor
from PyQt5.QtCore import Qt, QTimer, QItemSelectionModel, QEvent, QModelIndex


class CheckComboDelegate(QStyledItemDelegate):
    def __init__(self, options=None, table=None, sep="、", enable_select_all=False):
        """
        options: list[str]  复选项（作为兜底）；实际会优先读取 table.property('gk_code_candidates')
        table:   QTableWidget 用于行高亮（可为 None）
        sep:     显示/存储分隔符
        enable_select_all: bool  是否启用"全选"功能（默认False）
        
        说明：enable_select_all 参数用于控制是否在下拉框中显示"全选"选项。
        - 管口元件（管口号）：传入 enable_select_all=True，显示"全选"功能，方便一键选择所有管口号
        - 其他元件（支座、铭牌、保温装置等的元件名称）：使用默认值 False，不显示"全选"功能
        """
        super().__init__(table)
        self.options = options or []
        self.table = table
        self.sep = sep
        # 控制是否启用"全选"功能：True=管口元件有全选，False=其他元件无全选
        self.enable_select_all = enable_select_all
        self.select_all_label = "全选"

    # ---------- QStyledItemDelegate ----------
    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.setEditable(False)
        combo.setInsertPolicy(QComboBox.NoInsert)

        # ★★改动点1：拿"最新候选"——优先从表属性读取，失败用构造时的options兜底
        cands = self._get_candidates(option, index)
        print(f"[CheckComboDelegate] createEditor: 最终使用的候选选项: {cands}")

        # 模型：第0行显示文本；1..n为可勾选项
        model = QStandardItemModel(combo)
        display_item = QStandardItem("")         # 显示聚合文本
        display_item.setFlags(Qt.NoItemFlags)    # 不可选
        model.appendRow(display_item)

        # 追加"全选"行（仅在启用时）
        # 说明：只有管口元件（enable_select_all=True）才会添加"全选"选项
        #       其他元件（支座、铭牌、保温装置等）不会显示"全选"
        if self.enable_select_all and cands:
            select_all_item = QStandardItem(self.select_all_label)
            select_all_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            select_all_item.setData(Qt.Unchecked, Qt.CheckStateRole)
            select_all_item.setData(True, Qt.UserRole)  # 标记为全选行
            model.appendRow(select_all_item)

        for opt in cands:
            it = QStandardItem(str(opt))
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            it.setData(Qt.Unchecked, Qt.CheckStateRole)
            model.appendRow(it)

        combo.setModel(model)
        combo.setCurrentIndex(0)
        #11.19 设备法兰复选框新增
        try:
            setattr(combo, "_delegate_index", index)
            setattr(combo, "_delegate_model", index.model())
        except Exception:
            pass

        # 点击仅切换勾选，不改变 currentIndex，不关闭 popup；随后再自动弹出
        combo.view().pressed.connect(lambda mi: self._on_pressed(mi, combo))

        # 进入编辑即弹出
        QTimer.singleShot(0, combo.showPopup)

        # 可选：行高亮
        if self.table:
            sel = self.table.selectionModel()
            if sel:
                sel.clearSelection()
                sel.select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)
                self.table.setCurrentIndex(index)
            self._highlight_row(index.row())

        return combo

    def setEditorData(self, editor: QComboBox, index):
        # 把单元格里的 "N1、N6" 回写为勾选状态
        text = (index.model().data(index, Qt.EditRole) or "").strip()
        selected = [t for t in text.split(self.sep) if t]
        for it in self._iter_option_items(editor):
            it.setCheckState(Qt.Checked if it.text() in selected else Qt.Unchecked)
        # 只有管口元件才需要同步"全选"状态，其他元件无需此操作
        if self.enable_select_all:
            self._sync_select_all_state(editor)
        self._update_display_text(editor)

    def setModelData(self, editor: QComboBox, model, index):
        model.setData(index, self._selected_text(editor), Qt.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)

    def editorEvent(self, event, model, option, index):
        # 点击单元格立即进入编辑（弹出）
        if event.type() == QEvent.MouseButtonPress:
            parent = option.widget
            if parent:
                parent.edit(index)
        return super().editorEvent(event, model, option, index)

    # ---------- helpers ----------
    def _on_pressed(self, mi: QModelIndex, combo: QComboBox):
        row = mi.row()
        if row == 0:                 # 点显示行，无操作
            combo.setCurrentIndex(0)
            return
        it = combo.model().item(row)
        # "全选"行：全开/全关（仅在启用时）
        # 说明：只有管口元件（enable_select_all=True）才会处理"全选"点击事件
        #       其他元件（支座、铭牌、保温装置等）不会进入此分支
        if self.enable_select_all and self._is_select_all_item(it):
            target = Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked
            it.setCheckState(target)
            for opt in self._iter_option_items(combo):
                opt.setCheckState(target)
        else:
            it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)
            # 只有管口元件才需要同步"全选"状态，其他元件无需此操作
            if self.enable_select_all:
                self._sync_select_all_state(combo)
        self._update_display_text(combo)
        #11.19 设备法兰复选框新增
        # 立即提交数据，避免必须回车/切焦
        try:
            self.commitData.emit(combo)
        except Exception:
            pass
        # 同步写回模型与表格单元格文本
        try:
            txt = self._selected_text(combo)
            idx = getattr(combo, "_delegate_index", None)
            mdl = getattr(combo, "_delegate_model", None)
            if idx is not None and mdl is not None:
                mdl.setData(idx, txt, Qt.EditRole)
            if self.table is not None and idx is not None:
                r, c = idx.row(), idx.column()
                it2 = self.table.item(r, c)
                if it2 is None:
                    it2 = QTableWidgetItem()
                    it2.setTextAlignment(Qt.AlignCenter)
                    it2.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
                    self.table.setItem(r, c, it2)
                it2.setText(txt)
        except Exception:
            pass

        combo.setCurrentIndex(0)
        # 关键：保持下拉不关闭，立刻再弹出
        QTimer.singleShot(0, combo.showPopup)

    def _selected_text(self, combo: QComboBox) -> str:
        vals = []
        for it in self._iter_option_items(combo):
            if it.checkState() == Qt.Checked:
                vals.append(it.text())
        return self.sep.join(vals)

    def _update_display_text(self, combo: QComboBox):
        combo.model().item(0).setText(self._selected_text(combo))
        combo.setCurrentIndex(0)

    def _iter_option_items(self, combo: QComboBox):
        """跳过显示行和“全选”行，返回真正的选项 items。"""
        model = combo.model()
        for row in range(1, model.rowCount()):
            it = model.item(row)
            if it and not self._is_select_all_item(it):
                yield it

    def _is_select_all_item(self, item: QStandardItem) -> bool:
        try:
            return bool(item.data(Qt.UserRole))
        except Exception:
            return False

    def _sync_select_all_state(self, combo: QComboBox):
        """根据实际选中情况更新“全选”行的勾选状态。"""
        model = combo.model()
        # “全选”行位于第1行（如果存在）
        all_item = model.item(1) if model.rowCount() > 1 else None
        if all_item and self._is_select_all_item(all_item):
            opts = list(self._iter_option_items(combo))
            if not opts:
                all_item.setCheckState(Qt.Unchecked)
            else:
                all_checked = all(opt.checkState() == Qt.Checked for opt in opts)
                all_item.setCheckState(Qt.Checked if all_checked else Qt.Unchecked)

    def _highlight_row(self, row: int):
        if not self.table:
            return
        for r in range(self.table.rowCount()):
            for c in range(self.table.columnCount()):
                it = self.table.item(r, c)
                if it:
                    it.setBackground(QColor("#ffffff"))
        for c in range(self.table.columnCount()):
            it = self.table.item(row, c)
            if it:
                it.setBackground(QColor("#d0e7ff"))

    # ★★改动点2：读取最新候选
    def _get_candidates(self, option, index):
        """
        优先从 table.property('gk_code_candidates') 取；否则回退 self.options。
        不依赖外部函数，安全。
        """
        # 尝试拿到当前表对象
        table = self.table
        if table is None:
            # QTableWidget 通常就是 option.widget
            table = getattr(option, "widget", None)
        if table is not None:
            cands = table.property("gk_code_candidates")
            if cands:
                # 转为 list，确保可迭代
                print(f"[CheckComboDelegate] 从table.property读取候选选项: {list(cands)}")
                return list(cands)
        # 兜底：构造时传入的 options
        print(f"[CheckComboDelegate] 使用构造时传入的选项: {list(self.options)}")
        return list(self.options)


    def _find_row(table, label_text: str):
        for r in range(table.rowCount()):
            it = table.item(r, 0)
            if it and it.text().strip() == label_text:
                return r
        return None


    def _set_text_center(table, r, c, txt):
        it = table.item(r, c)
        if it is None:
            it = QTableWidgetItem()
            it.setTextAlignment(Qt.AlignCenter)
            it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
            table.setItem(r, c, it)
        it.setText(txt or "")
