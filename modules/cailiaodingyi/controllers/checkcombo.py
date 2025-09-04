from PyQt5.QtWidgets import QStyledItemDelegate, QComboBox, QTableWidgetItem
from PyQt5.QtGui import QStandardItemModel, QStandardItem, QColor
from PyQt5.QtCore import Qt, QTimer, QItemSelectionModel, QEvent, QModelIndex


class CheckComboDelegate(QStyledItemDelegate):
    def __init__(self, options=None, table=None, sep="、"):
        """
        options: list[str]  复选项（作为兜底）；实际会优先读取 table.property('gk_code_candidates')
        table:   QTableWidget 用于行高亮（可为 None）
        sep:     显示/存储分隔符
        """
        super().__init__(table)
        self.options = options or []
        self.table = table
        self.sep = sep

    # ---------- QStyledItemDelegate ----------
    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.setEditable(False)
        combo.setInsertPolicy(QComboBox.NoInsert)

        # ★★改动点1：拿“最新候选”——优先从表属性读取，失败用构造时的options兜底
        cands = self._get_candidates(option, index)

        # 模型：第0行显示文本；1..n为可勾选项
        model = QStandardItemModel(combo)
        display_item = QStandardItem("")         # 显示聚合文本
        display_item.setFlags(Qt.NoItemFlags)    # 不可选
        model.appendRow(display_item)

        for opt in cands:
            it = QStandardItem(str(opt))
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            it.setData(Qt.Unchecked, Qt.CheckStateRole)
            model.appendRow(it)

        combo.setModel(model)
        combo.setCurrentIndex(0)

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
        for row in range(1, editor.model().rowCount()):
            it = editor.model().item(row)
            it.setCheckState(Qt.Checked if it.text() in selected else Qt.Unchecked)
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
        it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)
        self._update_display_text(combo)
        combo.setCurrentIndex(0)
        # 关键：保持下拉不关闭，立刻再弹出
        QTimer.singleShot(0, combo.showPopup)

    def _selected_text(self, combo: QComboBox) -> str:
        vals = []
        for row in range(1, combo.model().rowCount()):
            it = combo.model().item(row)
            if it.checkState() == Qt.Checked:
                vals.append(it.text())
        return self.sep.join(vals)

    def _update_display_text(self, combo: QComboBox):
        combo.model().item(0).setText(self._selected_text(combo))
        combo.setCurrentIndex(0)

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
                return list(cands)
        # 兜底：构造时传入的 options
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
