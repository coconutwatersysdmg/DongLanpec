from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import QTableWidgetItem
from PyQt5.QtWidgets import QComboBox
from PyQt5.QtCore import Qt, QTimer
import modules.chanpinguanli.bianl as bianl
import modules.chanpinguanli.product_confirm_qianzhi as product_confirm_qianzhi
import modules.chanpinguanli.common_usage as common_usage
import os





def lock_combo(combo: QComboBox):
    combo.setEnabled(False)
    combo.setMinimumWidth(combo.sizeHint().width())  # 防止变窄
    combo.setStyleSheet("""
        QComboBox {
            background-color: #EEE;
            color: #555;
            border: 1px solid #CCC;   /* 浅灰边框 */
            padding: 2px 6px;
        }
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 0px;      /* 把下拉区域宽度压缩为 0 */
            border: none;    /* 去掉下拉区域边框 */
        }
        QComboBox::down-arrow {
            image: none;     /* 不显示箭头 */
            width: 0px;
            height: 0px;
        }
    """)

# def unlock_combo(combo: QComboBox):
#     combo.setEnabled(True)
#     combo.setMinimumWidth(0)
#     combo.setStyleSheet("")
def update_status(row, status):
    # 检查状态字典
    if row not in bianl.product_table_row_status or not isinstance(bianl.product_table_row_status[row], dict):
        bianl.product_table_row_status[row] = {}
    # 传入对应的状态
    bianl.product_table_row_status[row]["status"] = status

    # 如果是 start 状态，同时初始化 definition_status
    if status == "start" and "definition_status" not in bianl.product_table_row_status[row]:
        bianl.product_table_row_status[row]["definition_status"] = "start"
        print(f"[update_status] 行 {row} 初始化 definition_status = start")

    if status != "edit":
        bianl.product_table_row_status[row].pop("old_number", None)
        bianl.product_table_row_status[row].pop("old_name", None)
        bianl.product_table_row_status[row].pop("old_position", None)

def remove_row_and_status(row):
    bianl.product_table.removeRow(row)
    if row in bianl.product_table_row_status:
        del bianl.product_table_row_status[row]

#1106新修改
def add_table_row():
    # 防御：表格对象不存在或已销毁时直接返回，避免崩溃（不影响正常新增）
    try:
        table = getattr(bianl, "product_table", None)
        if table is None:
            return
        # 兼容性检测：若表格对象已被删除，直接返回
        try:
            import sip
            if sip.isdeleted(table):
                return
        except Exception:
            pass
        current_row_count = table.rowCount()
    except Exception:
        return
    bianl.product_table.insertRow(current_row_count)

    item = QTableWidgetItem(f"{current_row_count + 1:02d}")
    item.setTextAlignment(Qt.AlignCenter)
    # 可读
    # item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
    bianl.product_table.setItem(current_row_count, 0, item)





    # 设置状态为 start（此时 definition_status 也会一起被设）
    update_status(current_row_count, "start")


    # 锁定产品定义控件 改77
    lock_combo(bianl.product_type_combo)
    lock_combo(bianl.product_form_combo)
    lock_combo(bianl.product_model_input)
    lock_combo(bianl.drawing_prefix_input)

    #锁定工作信息控件 改77
    lock_combo(bianl.design_input)
    lock_combo(bianl.proofread_input)
    lock_combo(bianl.review_input)
    lock_combo(bianl.standardization_input)
    lock_combo(bianl.approval_input)
    lock_combo(bianl.co_signature_input)


    print(f"[add_table_row] 新增行 {current_row_count}：status=start, definition_status=start，产品定义区已锁定")

    bianl.product_table.scrollToBottom()
    # product_confirm_qianzhi.set_row_editable(current_row_count, True)




def record_cell_content(row, col):
    bianl.colum = col
    bianl.row = row
    item = bianl.product_table.item(row, col)
    bianl.last_cell_content = item.text().strip() if item else ""

def handle_auto_add_row(row, column):
    if column == 0:
        return
    item = bianl.product_table.item(row, column)
    new_text = item.text().strip() if item else ""
    QTimer.singleShot(0, lambda: finalize_row_edit(row, new_text))


# 更新序号 改yxx
def update_row_numbers():
    table = bianl.product_table
    table.blockSignals(True)

    for r in range(table.rowCount()):
        item = QTableWidgetItem(f"{r + 1:02d}")
        item.setTextAlignment(Qt.AlignCenter)
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

        # 判断是否为当前高亮行
        if hasattr(bianl, 'row') and r == bianl.row:
            item.setBackground(QBrush(QColor("#d0e7ff")))
        else:
            item.setBackground(QBrush(QColor("#ffffff")))

        row_status = bianl.product_table_row_status.get(r, {}).get("status", "")
        if row_status == "view":
            item.setForeground(QBrush(QColor("#888888")))
        else:
            item.setForeground(QBrush(Qt.black))
        # 将 item 设置到 product_table 的第 row 行第 0 列
        table.setItem(r, 0, item)
        # item.setForeground(QBrush(Qt.black))
        # table.setItem(r, 0, item)
    table.blockSignals(False)


# ✅ 【新增】完整新增 逻辑判断函数 ———————— 核心修改一：
# def is_row_filled(row):
#     total_columns = bianl.product_table.columnCount()
#     return any(
#         bianl.product_table.item(row, c) and bianl.product_table.item(row, c).text().strip()
#         for c in range(1, total_columns)
#     )
#
#
# def is_row_empty(row):
#     total_columns = bianl.product_table.columnCount()
#     return all(
#         not (bianl.product_table.item(row, c) and bianl.product_table.item(row, c).text().strip())
#         for c in range(1, total_columns)
#     )

def is_row_filled(row):
    total_columns = bianl.product_table.columnCount()
    for c in range(1, total_columns):
        widget = bianl.product_table.cellWidget(row, c)
        if isinstance(widget, QComboBox):
            if widget.currentText().strip():  # ✅ 下拉框有值
                return True
        item = bianl.product_table.item(row, c)
        if item and item.text().strip():
            return True
    return False


def is_row_empty(row):
    total_columns = bianl.product_table.columnCount()
    for c in range(1, total_columns):
        widget = bianl.product_table.cellWidget(row, c)
        if isinstance(widget, QComboBox):
            if widget.currentText().strip():  # ✅ 下拉框有值
                return False
        item = bianl.product_table.item(row, c)
        if item and item.text().strip():
            return False
    return True

# def record_cell_content(row, col):
#     bianl.colum = col
#     bianl.row = row
#     item = bianl.product_table.item(row, col)
#     bianl.last_cell_content = item.text().strip() if item else ""


#1106新修改
def finalize_row_edit(row, new_text):
    # 防御：表格对象不存在或已销毁时直接返回，避免崩溃（不影响正常保存）
    try:
        table = getattr(bianl, "product_table", None)
        if table is None:
            return
        try:
            import sip
            if sip.isdeleted(table):
                return
        except Exception:
            pass
    except Exception:
        return
    total_rows = table.rowCount()
    total_columns = table.columnCount()
    last_row = total_rows - 1
    if row not in bianl.product_table_row_status or not isinstance(bianl.product_table_row_status[row], dict):
        # 在这里定义了一个嵌套字典
        bianl.product_table_row_status[row] = {}

    # def is_row_filled(r):
    #     return any(table.item(r, c) and table.item(r, c).text().strip() for c in range(1, total_columns))
    #
    # def is_row_empty(r):
    #     return all(not (table.item(r, c) and table.item(r, c).text().strip()) for c in range(1, total_columns))
        # ✅ 初始行数只有3行时，全部填写完毕，自动新增行
    if total_rows == 3 and all(is_row_filled(r) for r in range(3)):

        add_table_row()
        print("增加")
        update_row_numbers()
        print("更新")
        return

    if total_rows >= 4:
        if row == last_row and is_row_filled(row):

            add_table_row()
            print("增加1")
            update_row_numbers()
            print("更新2")
            return
        if is_row_empty(row) and row != last_row and is_row_empty(last_row):
            remove_row_and_status(row)
            update_row_numbers()
            return

    update_row_numbers()
    from modules.chanpinguanli.chanpinguanli_main import highlight_row_except_current
    table = bianl.product_table
    row = table.currentRow()
    col = table.currentColumn()
    highlight_row_except_current(row, col)

#1106新修改
def handle_combo_changed(row: int, col: int):
    """统一处理：有值且在最后一行 → 自增；清空且非最后一行、整行空 → 自减"""

    # 防御：表格对象不存在或已销毁时直接返回（不影响正常回调）
    try:
        table = getattr(bianl, "product_table", None)
        if table is None:
            return
        try:
            import sip
            if sip.isdeleted(table):
                return
        except Exception:
            pass
    except Exception:
        return
    last_row = table.rowCount() - 1
    w = table.cellWidget(row, col)
    if not w:
        return
    else:
        text = w.currentText().strip()

    if text:
        # 在最后一行选了内容 → 新增一行
        if row == last_row:
            add_table_row()
            update_row_numbers()
    else:
        # 被清空：若不是最后一行且整行为空 → 删除该行
        if row != last_row and is_row_empty(row):
            remove_row_and_status(row)
            update_row_numbers()



from PyQt5.QtCore import QObject, QEvent, Qt, QTimer
from PyQt5.QtWidgets import QComboBox

# —— 绑定函数：供 setup_design_stage_combo 调用（只做绑定，不做业务）——
def bind_design_combo(combo: QComboBox, row: int, col: int):
    """把设计阶段下拉框与增/减行逻辑绑定到一起（选择、删除都走这里）"""
    # 1) 选择变化：有值 → 可能自增
    combo.currentIndexChanged.connect(lambda _=None: handle_combo_changed(row, col))
    # 2) 按 Delete/Backspace 清空：我们自己处理
    filt = _ComboDeleteFilter(combo, row, col)
    combo.installEventFilter(filt)
    # 防止被回收
    setattr(combo, "_delete_filter", filt)

# 下拉框 QComboBox 安装一个事件过滤器，让 Delete / Backspace 键可以把下拉框内容清空
class _ComboDeleteFilter(QObject):
    """拦截 Delete/Backspace 清空下拉框并触发统一逻辑"""
    def __init__(self, combo: QComboBox, row: int, col: int):
        super().__init__(combo)
        self.combo = combo
        self.row = row
        self.col = col

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            # 清空显示（设为未选中）
            self.combo.blockSignals(True)
            self.combo.setCurrentIndex(-1)
            self.combo.blockSignals(False)
            # 走统一的“变化后处理”
            QTimer.singleShot(0, lambda: handle_combo_changed(self.row, self.col))
            return True
        return False




