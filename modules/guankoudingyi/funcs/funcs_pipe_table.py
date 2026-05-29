import pymysql
import re
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QTableWidgetItem,
    QMessageBox,
    QWidget,
    QComboBox,
    QLabel,
    QDialog,
    QVBoxLayout,
    QListWidget,
    QHBoxLayout,
    QPushButton,
)
from PyQt5.QtGui import QBrush, QColor
from functools import partial
from PyQt5.QtWidgets import QAbstractItemView
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QTableWidgetSelectionRange

from modules.guankoudingyi.db_cnt import get_connection, db_config_1, db_config_2

# —— 运行期隐藏ID映射 + 待删ID 集合 ——
def ensure_hidden_maps(stats_widget):
    if not hasattr(stats_widget, "row_hidden_pipe_id"):
        stats_widget.row_hidden_pipe_id = {}   # {row_index: 管口ID}
    if not hasattr(stats_widget, "deleted_pipe_ids"):
        stats_widget.deleted_pipe_ids = set()  # {管口ID}


# —— 附件定义：运行期隐藏ID映射 + 待删ID 集合 ——
def ensure_hidden_attachment_maps(stats_widget):
    if not hasattr(stats_widget, "row_hidden_attachment_id"):
        stats_widget.row_hidden_attachment_id = {}   # {row_index: 元件ID}
    if not hasattr(stats_widget, "deleted_attachment_ids"):
        stats_widget.deleted_attachment_ids = set()  # {元件ID}


# —— 计算“下一管口ID”（只分配，不入库）——
def get_next_pipe_id_runtime(stats_widget, product_id):
    """
    返回一个“尚未使用”的新 管口ID：
    max(数据库中该产品已有管口ID, 运行期已分配但未落库的管口ID) + 1
    """
    from modules.guankoudingyi.db_cnt import get_connection
    import pymysql
    ensure_hidden_maps(stats_widget)

    max_db = 0
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as c:
            c.execute("SELECT MAX(管口ID) AS mx FROM 产品设计活动表_管口表 WHERE 产品ID=%s", (product_id,))
            row = c.fetchone()
            if row and row.get("mx") is not None:
                max_db = int(row["mx"])
    finally:
        conn.close()

    max_runtime = 0
    if stats_widget.row_hidden_pipe_id:
        try:
            max_runtime = max(int(v) for v in stats_widget.row_hidden_pipe_id.values() if v is not None)
        except ValueError:
            max_runtime = 0

    return max(max_db, max_runtime) + 1


# —— 计算“下一元件ID”（只分配，不入库）——
def get_next_attachment_id_runtime(stats_widget, product_id):
    """
    返回一个“尚未使用”的新 元件ID：
    max(数据库中该产品已有元件ID, 运行期已分配但未落库的元件ID) + 1

    注意：附件定义的元件表在不同项目中表名可能不同；若查询失败则退化为仅使用运行期分配。
    """
    ensure_hidden_attachment_maps(stats_widget)

    max_db = 0
    conn = None
    try:
        conn = get_connection(**db_config_2)
        with conn.cursor(pymysql.cursors.DictCursor) as c:
            # 约定：附件定义表存在元件ID列，并按产品ID分组
            c.execute("SELECT MAX(元件ID) AS mx FROM 产品设计活动表_附件表 WHERE 产品ID=%s", (product_id,))
            row = c.fetchone()
            if row and row.get("mx") is not None:
                max_db = int(row["mx"])
    except Exception:
        # 表不存在/字段不存在时不阻断界面使用，退化为运行期分配
        max_db = 0
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    max_runtime = 0
    if getattr(stats_widget, "row_hidden_attachment_id", None):
        try:
            max_runtime = max(int(v) for v in stats_widget.row_hidden_attachment_id.values() if v is not None)
        except ValueError:
            max_runtime = 0

    return max(max_db, max_runtime) + 1

# —— 行交换时，同步隐藏“管口ID”映射 ——
def swap_hidden_id(stats_widget, row_a, row_b):
    ensure_hidden_maps(stats_widget)
    ida = stats_widget.row_hidden_pipe_id.get(row_a)
    idb = stats_widget.row_hidden_pipe_id.get(row_b)
    if ida is None and idb is None:
        return
    if ida is None:
        stats_widget.row_hidden_pipe_id.pop(row_b, None)
    else:
        stats_widget.row_hidden_pipe_id[row_b] = ida
    if idb is None:
        stats_widget.row_hidden_pipe_id.pop(row_a, None)
    else:
        stats_widget.row_hidden_pipe_id[row_a] = idb


# —— 附件行交换时，同步隐藏「元件ID」映射（与管口 swap_hidden_id 同思路）——
def swap_hidden_attachment_id(stats_widget, row_a, row_b):
    ensure_hidden_attachment_maps(stats_widget)
    ida = stats_widget.row_hidden_attachment_id.get(row_a)
    idb = stats_widget.row_hidden_attachment_id.get(row_b)
    if ida is None and idb is None:
        return
    if ida is None:
        stats_widget.row_hidden_attachment_id.pop(row_b, None)
    else:
        stats_widget.row_hidden_attachment_id[row_b] = ida
    if idb is None:
        stats_widget.row_hidden_attachment_id.pop(row_a, None)
    else:
        stats_widget.row_hidden_attachment_id[row_a] = idb


"""数据读取，界面显示，数据存入产品设计活动表_管口表"""
def read_pipe_temp(stats_widget, belong_type, belong_version, product_id):
    """
    读取顺序：
      1) 产品设计活动库.产品设计活动表_管口表（带管口ID）
      2) 若无 → 元件库.管口默认表（带管口ID），并将其插入到产品表
      3) 若仍无 → 弹窗并清空界面
    """
    table_pipe = stats_widget.tableWidget_pipe  # 获取界面表格控件
    ensure_hidden_maps(stats_widget)
    ensure_hidden_attachment_maps(stats_widget)

    # 先连接
    conn_component = get_connection(**db_config_1)
    conn_product = get_connection(**db_config_2)
    cursor_component = conn_component.cursor(pymysql.cursors.DictCursor)
    cursor_product = conn_product.cursor(pymysql.cursors.DictCursor)
    try:
        # ==== 标记数据来源（默认认为不是来自“默认表”）====
        loaded_from_default = False
        # 先查产品表（带 管口ID）
        cursor_product.execute("""
            SELECT 管口ID, 管口代号, 管口功能, 管口用途, 公称尺寸, 法兰标准, 压力等级, 法兰型式,
                   密封面型式, 焊端规格, 管口所属元件, 轴向定位基准, 轴向定位距离,
                   `轴向夹角（°）`, `周向方位（°）`, `偏心距`, 外伸高度, 管口附件, 管口载荷
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s
            ORDER BY 管口ID ASC
        """, (product_id,))
        rows = cursor_product.fetchall()
        # 若产品表无数据 → 查默认表（带 管口ID）
        if not rows:
            cursor_component.execute("""
                SELECT 管口ID, 管口代号, 管口功能, 管口用途, 公称尺寸, 法兰标准, 压力等级, 法兰型式,
                       密封面型式, 焊端规格, 管口所属元件, 轴向定位基准, 轴向定位距离,
                       `轴向夹角（°）`, `周向方位（°）`, `偏心距`, 外伸高度, 管口附件, 管口载荷
                FROM 管口默认表
                WHERE 所属类型 = %s AND 所属型式 = %s
                ORDER BY 管口ID ASC
            """, (belong_type, belong_version))
            rows = cursor_component.fetchall()

            if not rows:
                QMessageBox.information(stats_widget, "查询结果", "未在管口默认表中找到默认数据")
                table_pipe.clearContents()
                table_pipe.setRowCount(0)
                return

            # # 把默认数据（含 管口ID）落库到产品表（防重复：依赖唯一键 (产品ID, 管口ID)）
            # cursor_product.executemany("""
            #     INSERT INTO 产品设计活动表_管口表 (
            #         产品ID, 管口ID, 管口代号, 管口功能, 管口用途, 公称尺寸, 法兰标准, 压力等级,
            #         法兰型式, 密封面型式, 焊端规格, 管口所属元件, 轴向定位基准, 轴向定位距离,
            #         `轴向夹角（°）`, `周向方位（°）`, `偏心距`, 外伸高度, 管口附件, 管口载荷, 管口更改状态
            #     ) VALUES (
            #         %(产品ID)s, %(管口ID)s, %(管口代号)s, %(管口功能)s, %(管口用途)s, %(公称尺寸)s, %(法兰标准)s, %(压力等级)s,
            #         %(法兰型式)s, %(密封面型式)s, %(焊端规格)s, %(管口所属元件)s, %(轴向定位基准)s, %(轴向定位距离)s,
            #         %(轴向夹角（°）)s, %(周向方位（°）)s, %(偏心距)s, %(外伸高度)s, %(管口附件)s, %(管口载荷)s, '未更改'
            #     )
            #     ON DUPLICATE KEY UPDATE 管口代号=VALUES(管口代号)
            # """, [{**r, "产品ID": product_id} for r in rows])
            # conn_product.commit()

            # ==== 只有“来自默认表并首落库”的情况，才标记 True ====
            loaded_from_default = True

        # —— 渲染到UI（并建立隐藏ID映射）——
        table_pipe.clearContents()
        table_pipe.setRowCount(len(rows))
        stats_widget.row_hidden_pipe_id.clear()

        # ✅ 初始化 pipe_belong_old_values，保存加载时的管口所属元件值
        if not hasattr(stats_widget, 'pipe_belong_old_values'):
            stats_widget.pipe_belong_old_values = {}
        else:
            stats_widget.pipe_belong_old_values.clear()

        fields = ["管口代号", "管口功能", "管口用途", "公称尺寸", "法兰标准", "压力等级", "法兰型式",
                  "密封面型式", "焊端规格", "管口所属元件", "轴向定位基准", "轴向定位距离",
                  "轴向夹角（°）", "周向方位（°）", "偏心距", "外伸高度", "管口附件", "管口载荷"]
        for rr, row in enumerate(rows):
            stats_widget.row_hidden_pipe_id[rr] = row.get("管口ID")  # 记录隐藏ID
            for cc, name in enumerate(fields, start=1):
                val = row.get(name)
                text = "" if val is None or str(val) == "None" else str(val)
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                table_pipe.setItem(rr, cc, item)

            # ✅ 保存管口所属元件的初始值到 pipe_belong_old_values
            pipe_belong_val = row.get("管口所属元件")
            pipe_belong_text = "" if pipe_belong_val is None or str(pipe_belong_val) == "None" else str(pipe_belong_val).strip()
            stats_widget.pipe_belong_old_values[rr] = pipe_belong_text

        stats_widget.refresh_pipe_table_sequence()
        check_last_row_and_add_new(stats_widget)
        stats_widget.adjust_pipe_column_width()
        set_pipe_function_column_readonly(stats_widget)
        try:
            from modules.guankoudingyi.funcs.funcs_pipe_comboBox_value import \
                apply_pipe_row_column_locks_by_belong
            for rr in range(table_pipe.rowCount() - 1):
                apply_pipe_row_column_locks_by_belong(stats_widget, rr)
        except Exception as e:
            print(f"[ERROR] 同步管口列锁定状态失败: {e}")
        # 设置默认管口不可删除
        set_default_pipe_cannot_be_deleted(stats_widget)

        # —— 读取附件定义表（有就读；没有则保持界面当前状态）——
        table_attach = getattr(stats_widget, "tableWidget_attachment", None)
        if table_attach is not None:
            # 与管口表一致：按 元件ID 升序加载；保存时已将 ID 与界面自上而下顺序对齐，无需单独排序列
            cursor_product.execute("""
                SELECT 元件ID, 元件名称, 元件类型, 所属元件, 轴向定位基准, 轴向定位距离mm,
                       数量, 间距, `轴向夹角（°）`, `周向方位（°）`, 偏心距, 外伸高度, 备注
                FROM 产品设计活动表_附件表
                WHERE 产品ID = %s
                ORDER BY 元件ID ASC
            """, (product_id,))
            attachment_rows = cursor_product.fetchall() or []

            if attachment_rows:
                # 第0行为表头；数据行 = 已有记录 + 1个尾部空白行（便于继续录入）
                table_attach.blockSignals(True)
                try:
                    table_attach.setRowCount(1 + len(attachment_rows) + 1)
                    try:
                        table_attach.setRowHidden(0, True)
                    except Exception:
                        pass
                    stats_widget.row_hidden_attachment_id.clear()

                    # 列映射（与附件定义表格列一致）
                    attach_fields = [
                        "元件名称", "元件类型", "所属元件", "轴向定位基准", "轴向定位距离mm",
                        "数量", "间距", "轴向夹角(°)", "周向方位(°)", "偏心距", "外伸高度", "备注"
                    ]

                    # 从第1行开始回填
                    for rr, row in enumerate(attachment_rows, start=1):
                        stats_widget.row_hidden_attachment_id[rr] = row.get("元件ID")
                        table_attach.setRowHeight(rr, 40)

                        for cc, name in enumerate(attach_fields, start=1):
                            # 兼容数据库全角括号字段名
                            if name == "轴向夹角(°)":
                                val = row.get("轴向夹角(°)", row.get("轴向夹角（°）"))
                            elif name == "周向方位(°)":
                                val = row.get("周向方位(°)", row.get("周向方位（°）"))
                            else:
                                val = row.get(name)

                            text = "" if val is None or str(val) == "None" else str(val)
                            item = QTableWidgetItem(text)
                            item.setTextAlignment(Qt.AlignCenter)
                            if cc == 1:
                                # 元件名称仅程序/按钮填入，不可手编
                                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                            elif cc in (2, 3):
                                # 当前附件策略：仅第2、3列启用编辑
                                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)
                            else:
                                # 其余后续列暂不启用，保持冻结且不可选中
                                item.setFlags(Qt.ItemIsEnabled)
                            if 4 <= cc <= 12:
                                item.setBackground(QBrush(QColor(235, 235, 235)))
                            table_attach.setItem(rr, cc, item)

                    # 尾部空白行初始化（序号由 refresh_attachment_table_sequence 统一维护）
                    blank_row = 1 + len(attachment_rows)
                    table_attach.setRowHeight(blank_row, 40)
                    for cc in range(1, table_attach.columnCount()):
                        item = table_attach.item(blank_row, cc)
                        if item is None:
                            item = QTableWidgetItem("")
                            item.setTextAlignment(Qt.AlignCenter)
                            if cc == 1:
                                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                            else:
                                # 除元件名称外默认冻结；第4~12列不可编辑且不可选中
                                if 4 <= cc <= 12:
                                    item.setFlags(Qt.ItemIsEnabled)
                                else:
                                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                            if 4 <= cc <= 12:
                                item.setBackground(QBrush(QColor(235, 235, 235)))
                            table_attach.setItem(blank_row, cc, item)
                    # 已加载数据行：按元件名称同步第 2 列及以后可编辑性
                    for rr in range(1, blank_row):
                        sync_attachment_row_tail_editable_by_name(stats_widget, rr)
                    # 对齐管口：只根据「最后一行占位行」是否已有元件名称，同步冻结/解冻后续列
                    name_last = ""
                    it_last = table_attach.item(blank_row, 1)
                    if it_last:
                        name_last = it_last.text().strip()
                    control_last_attachment_row_editable_state(
                        stats_widget, enable_editing=bool(name_last)
                    )

                    if hasattr(stats_widget, "refresh_attachment_table_sequence"):
                        stats_widget.refresh_attachment_table_sequence()
                finally:
                    table_attach.blockSignals(False)

        # ====只有首次创建（loaded_from_default=True）才触发自动推荐 ====
        if loaded_from_default:
            try:
                from modules.guankoudingyi.funcs.funcs_pipe_comboBox_value import \
                    auto_recommend_nominal_sizes_for_first_four_pipes, auto_assign_eccentricity_for_aku_bku
                auto_recommend_nominal_sizes_for_first_four_pipes(stats_widget, product_id)
                auto_assign_eccentricity_for_aku_bku(stats_widget, product_id)
            except Exception as e:
                print(f"[ERROR] 自动推荐公称尺寸失败: {str(e)}")

    except Exception as e:
        conn_product.rollback()
        QMessageBox.critical(stats_widget, "数据库错误", f"读取管口数据失败：{e}")
    finally:
        cursor_component.close();
        conn_component.close()
        cursor_product.close();
        conn_product.close()

"""管口功能列和管口所属元件列部分只读"""
# def set_pipe_function_column_readonly(stats_widget):
#     """
#     根据产品所属类型和型式，将特定的"管口功能"项和对应的"管口所属元件"项设为不可编辑。
#     排序后调用本函数，确保只读状态被重置。
#     """
#     table = stats_widget.tableWidget_pipe
#     product_type = getattr(stats_widget, "current_product_type", "")
#     product_version = getattr(stats_widget, "current_product_version", "")
#
#     # 定义每种类型下不可编辑的功能值
#     readonly_values = set()
#
#     if product_type == "管壳式热交换器":
#         if product_version in ["AEU", "BEU"]:
#             readonly_values = {"管程入口", "管程出口", "壳程入口", "壳程出口"}
#         elif product_version in ["AES", "BES"]:
#             readonly_values = {"管程入口", "管程出口", "壳程入口", "壳程出口"}
#         elif product_version in ["NEN"]:
#             readonly_values = {"管程入口", "管程出口", "壳程入口", "壳程出口"}
#         elif product_version in ["BEM"]:
#             readonly_values = {"管程入口", "管程出口", "壳程入口", "壳程出口"}
#
#     # 对于 NEN 类型，定义哪些功能的管口所属元件列应该可编辑
#     # NEN类型的"管程入口"、"管程出口"的管口所属元件列可编辑
#     belong_editable_for_nen = set()
#
#     if product_type == "管壳式热交换器" and product_version in ["NEN"]:
#         belong_editable_for_nen = {"管程入口", "管程出口"}
#
#     # 遍历表格行，同时设置管口功能列和管口所属元件列的只读状态
#     func_col = 2  # 管口功能列
#     belong_col = 10  # 管口所属元件列
#
#     for row in range(table.rowCount() - 1):  # 排除最后空白行
#         func_item = table.item(row, func_col)
#         belong_item = table.item(row, belong_col)
#
#         if not func_item:
#             continue
#
#         func_value = func_item.text().strip()
#         is_func_readonly = func_value in readonly_values
#
#         # 设置管口功能列的只读状态
#         if is_func_readonly:
#             func_item.setFlags(func_item.flags() & ~Qt.ItemIsEditable)
#         else:
#             func_item.setFlags(func_item.flags() | Qt.ItemIsEditable)
#
#         # 设置管口所属元件列的只读状态
#         # 对于 NEN BEM 类型，如果管口功能在 belong_editable_for_nen 中，则管口所属元件列可编辑
#         if belong_item:
#             if product_type == "管壳式热交换器" and product_version in ["NEN"]:
#                 # NEN 类型：管程入口、管程出口的管口所属元件列可编辑
#                 if func_value in belong_editable_for_nen:
#                     belong_item.setFlags(belong_item.flags() | Qt.ItemIsEditable)
#                 elif is_func_readonly:
#                     # 其他只读功能的管口所属元件列仍然只读
#                     belong_item.setFlags(belong_item.flags() & ~Qt.ItemIsEditable)
#                 else:
#                     # 非只读功能的管口所属元件列可编辑
#                     belong_item.setFlags(belong_item.flags() | Qt.ItemIsEditable)
#             else:
#                 # 其他类型：管口所属元件列的只读状态与管口功能列保持一致
#                 if is_func_readonly:
#                     belong_item.setFlags(belong_item.flags() & ~Qt.ItemIsEditable)
#                 else:
#                     belong_item.setFlags(belong_item.flags() | Qt.ItemIsEditable)
"""管口功能列和管口所属元件列部分只读"""
def set_pipe_function_column_readonly(stats_widget):
    """
    根据产品所属类型和型式，将特定的"管口功能"项和对应的"管口所属元件"项设为不可编辑。
    排序后调用本函数，确保只读状态被重置。
    """
    table = stats_widget.tableWidget_pipe
    product_type = getattr(stats_widget, "current_product_type", "")
    product_version = getattr(stats_widget, "current_product_version", "")

    # 定义每种类型下不可编辑的功能值
    readonly_values = set()

    if product_type == "管壳式热交换器":
        if product_version in ["AEU", "BEU"]:
            readonly_values = {"管程入口", "管程出口", "壳程入口", "壳程出口"}
        elif product_version in ["AES", "BES"]:
            readonly_values = {"管程入口", "管程出口", "壳程入口", "壳程出口"}
        elif product_version in ["NEN","NEN(Head)"]:
            readonly_values = {"管程入口", "管程出口", "壳程入口", "壳程出口"}
        elif product_version in ["BEM","AEM"]:
            readonly_values = {"管程入口", "管程出口", "壳程入口", "壳程出口"}
        elif product_version in ["AKU","BKU"]:
            readonly_values = {"管程入口", "管程出口", "壳程入口", "壳程气相出口","壳程液相出口","壳程液位计1","壳程液位计2","壳程温度计"}

    # 所有类型的"管程入口"、"管程出口"的管口所属元件列可编辑
    belong_editable_functions = set()  # 变量名从belong_editable_for_nen改为更通用的名称
    if product_type == "管壳式热交换器" and product_version in ["NEN", "BEM","AES","BES","AEU","BEU","AEM","NEN(Head)"]:
        belong_editable_functions = {"管程入口", "管程出口"}
    elif product_type == "管壳式热交换器" and product_version in ["AKU","BKU"]:
        belong_editable_functions ={"管程入口", "管程出口", "壳程入口","壳程液位计1","壳程液位计2","壳程温度计"}

    # 遍历表格行，同时设置管口功能列和管口所属元件列的只读状态
    func_col = 2  # 管口功能列
    belong_col = 10  # 管口所属元件列

    for row in range(table.rowCount() - 1):  # 排除最后空白行
        func_item = table.item(row, func_col)
        belong_item = table.item(row, belong_col)

        if not func_item:
            continue

        func_value = func_item.text().strip()
        is_func_readonly = func_value in readonly_values

        # 设置管口功能列的只读状态
        if is_func_readonly:
            func_item.setFlags(func_item.flags() & ~Qt.ItemIsEditable)
        else:
            func_item.setFlags(func_item.flags() | Qt.ItemIsEditable)

        # 设置管口所属元件列的只读状态
        if belong_item:
            if product_type == "管壳式热交换器" and product_version in ["NEN", "BEM","AES","BES","AEU","BEU","AEM","AKU","BKU","NEN(Head)"]:  # 加入BEM
                #管程入口、管程出口的管口所属元件列可编辑
                if func_value in belong_editable_functions:  # 同步使用新的变量名
                    belong_item.setFlags(belong_item.flags() | Qt.ItemIsEditable)
                elif is_func_readonly:
                    # 其他只读功能的管口所属元件列仍然只读
                    belong_item.setFlags(belong_item.flags() & ~Qt.ItemIsEditable)
                else:
                    # 非只读功能的管口所属元件列可编辑
                    belong_item.setFlags(belong_item.flags() | Qt.ItemIsEditable)
            else:
                # 其他类型：管口所属元件列的只读状态与管口功能列保持一致
                if is_func_readonly:
                    belong_item.setFlags(belong_item.flags() & ~Qt.ItemIsEditable)
                else:
                    belong_item.setFlags(belong_item.flags() | Qt.ItemIsEditable)

"""管口删除"""
def delete_selected_pipe_rows(stats_widget, product_id):
    """
    删除选中行：只删界面；同时记录这些行对应的"隐藏管口ID"到 stats_widget.deleted_pipe_ids。
    真正的数据库删除在"确认保存"时执行。
    如果 cannot_be_deleted 为 True，会检查是否包含不可删除的默认管口。
    """
    ensure_hidden_maps(stats_widget)
    table = stats_widget.tableWidget_pipe
    selected_rows = sorted(set(index.row() for index in table.selectedIndexes()), reverse=True)

    # 排除最后一行
    last_row_index = table.rowCount() - 1
    selected_rows = [r for r in selected_rows if r != last_row_index]

    if not selected_rows:
        stats_widget.line_tip.setText("最后一行不能删除，请选择其他要删除的管口行")
        stats_widget.line_tip.setStyleSheet("color: red;")
        return

    # 检查是否包含不可删除的默认管口（当 cannot_be_deleted 为 True 时）
    cannot_be_deleted = getattr(stats_widget, "cannot_be_deleted", True)
    readonly_pipe_functions = getattr(stats_widget, "readonly_pipe_functions", set())

    if cannot_be_deleted and readonly_pipe_functions:
        # 检查选中的行中是否包含不可删除的管口（根据管口功能列判断）
        protected_pipe_functions = []
        for row in selected_rows:
            pipe_function_item = table.item(row, 2)  # 第2列为管口功能
            if pipe_function_item:
                pipe_function = pipe_function_item.text().strip()
                if pipe_function in readonly_pipe_functions:
                    protected_pipe_functions.append(pipe_function)

        # 如果包含不可删除的管口，阻止删除
        if protected_pipe_functions:
            # 格式化提示信息，根据管口功能生成提示
            function_names = "、".join(set(protected_pipe_functions))  # 使用set去重
            QMessageBox.warning(
                stats_widget,
                "删除失败",
                f"该管口功能为{function_names}，不可删除，您可更改其管口代号和移动其管口顺序。"
            )
            #stats_widget.line_tip.setText(f"管口功能为 {function_names} 的管口不可删除")
            #stats_widget.line_tip.setStyleSheet("color: red;")
            return

    # 确认删除
    reply = QMessageBox.question(
        stats_widget, "确认删除", f"确定要删除选中的 {len(selected_rows)} 行管口数据吗？",
        QMessageBox.Yes | QMessageBox.No, QMessageBox.No
    )
    if reply != QMessageBox.Yes:
        return

    for row in selected_rows:
        hid = getattr(stats_widget, "row_hidden_pipe_id", {}).pop(row, None)
        if hid is not None:
            stats_widget.deleted_pipe_ids.add(hid)
        table.removeRow(row)
        # ✅ 关键：removeRow 会导致其下方所有行号整体 -1，必须同步修正隐藏ID映射的 key
        # 否则保存时会出现“行内容已上移，但仍沿用旧行号的管口ID”，从而导致重复/错删
        try:
            old_map = getattr(stats_widget, "row_hidden_pipe_id", {}) or {}
            if old_map:
                new_map = {}
                for k, v in old_map.items():
                    if k > row:
                        new_map[k - 1] = v
                    else:
                        new_map[k] = v
                stats_widget.row_hidden_pipe_id = new_map
        except Exception:
            # 映射修正失败不应阻断界面删除；保存时仍有 deleted_pipe_ids 兜底
            pass
    # 删除后：确保最后空白占位行不携带隐藏管口ID（防止后续被误判为“已有ID”的数据行）
    try:
        last_row_index = table.rowCount() - 1
        if hasattr(stats_widget, "row_hidden_pipe_id"):
            stats_widget.row_hidden_pipe_id.pop(last_row_index, None)
    except Exception:
        pass
    # 序号的刷新
    stats_widget.refresh_pipe_table_sequence()

"""元件删除"""
def delete_selected_attachment_rows(stats_widget, product_id):
    """
    删除附件定义表选中行：只删界面；同时记录这些行对应的"隐藏元件ID"到 stats_widget.deleted_attachment_ids。
    真正数据库删除在"确认保存"时执行。
    约定：
    - 第0行为表头，不能删除
    - 最后一行为自动新增的空白行，不允许删除
    """
    ensure_hidden_attachment_maps(stats_widget)
    table = getattr(stats_widget, "tableWidget_attachment", None)
    if table is None:
        return

    selected_rows = sorted(set(index.row() for index in table.selectedIndexes()), reverse=True)
    if not selected_rows:
        return

    last_row_index = table.rowCount() - 1
    # 排除表头行和最后空白行
    selected_rows = [r for r in selected_rows if r not in (0, last_row_index)]

    if not selected_rows:
        if hasattr(stats_widget, "line_tip") and stats_widget.line_tip:
            stats_widget.line_tip.setText("最后一行不能删除，请选择其他要删除的附件行")
            stats_widget.line_tip.setStyleSheet("color: red;")
        return

    reply = QMessageBox.question(
        stats_widget, "确认删除", f"确定要删除选中的 {len(selected_rows)} 行附件数据吗？",
        QMessageBox.Yes | QMessageBox.No, QMessageBox.No
    )
    if reply != QMessageBox.Yes:
        return

    for row in selected_rows:
        # 先取出并记录该行对应的隐藏元件ID（用于保存时落库删除）
        elem_id = getattr(stats_widget, "row_hidden_attachment_id", {}).pop(row, None)
        if elem_id is not None:
            stats_widget.deleted_attachment_ids.add(elem_id)
        table.removeRow(row)
        # ✅ 关键：removeRow 会导致其下方所有行号整体 -1，必须同步修正隐藏ID映射的 key
        # 否则保存时会出现“行内容已上移，但仍沿用旧行号的元件ID”，从而导致重复/错删
        try:
            old_map = getattr(stats_widget, "row_hidden_attachment_id", {}) or {}
            if old_map:
                new_map = {}
                for k, v in old_map.items():
                    if k > row:
                        new_map[k - 1] = v
                    else:
                        new_map[k] = v
                stats_widget.row_hidden_attachment_id = new_map
        except Exception:
            # 映射修正失败不应阻断界面删除；保存时仍有 deleted_attachment_ids 兜底
            pass

    # 删除后：确保末尾空白占位行不携带隐藏元件ID（防止后续被误判为“已有ID”的数据行）
    try:
        last_row_index = table.rowCount() - 1
        if hasattr(stats_widget, "row_hidden_attachment_id"):
            stats_widget.row_hidden_attachment_id.pop(last_row_index, None)
            stats_widget.row_hidden_attachment_id.pop(0, None)
    except Exception:
        pass

    # 删除后：可重复元件家族名称重排
    # - 多个成员：按界面行顺序压紧为 base1..baseN（例如 吊耳1,吊耳3,吊耳4 -> 吊耳1,吊耳2,吊耳3）
    # - 单个成员：回退为 base（例如 吊耳1 -> 吊耳）
    try:
        from modules.guankoudingyi.funcs.funcs_attachment_comboBox_value import (
            ATTACHMENT_AUTO_INDEXED_REPEATABLE_NAMES,
            ATTACHMENT_COMPONENT_NAME_COLUMN,
            ATTACHMENT_COMPONENT_NAME_ITEM_FLAGS,
        )

        table.blockSignals(True)
        for base_name in ATTACHMENT_AUTO_INDEXED_REPEATABLE_NAMES:
            matched_rows = []
            for r in range(1, table.rowCount()):
                item = table.item(r, ATTACHMENT_COMPONENT_NAME_COLUMN)
                if not item:
                    continue
                txt = item.text().strip()
                if not txt:
                    continue
                if txt == base_name or re.match(rf"^{re.escape(base_name)}\d+$", txt):
                    matched_rows.append(r)

            if not matched_rows:
                continue

            # 单个成员：回退原名
            if len(matched_rows) == 1:
                only_row = matched_rows[0]
                name_item = table.item(only_row, ATTACHMENT_COMPONENT_NAME_COLUMN)
                if name_item is None:
                    name_item = QTableWidgetItem("")
                    name_item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(only_row, ATTACHMENT_COMPONENT_NAME_COLUMN, name_item)
                name_item.setFlags(ATTACHMENT_COMPONENT_NAME_ITEM_FLAGS)
                if name_item.text().strip() != base_name:
                    name_item.setText(base_name)
                continue

            # 多个成员：按当前界面行顺序压紧为 base1..baseN
            for idx, r in enumerate(sorted(matched_rows), start=1):
                target_name = f"{base_name}{idx}"
                name_item = table.item(r, ATTACHMENT_COMPONENT_NAME_COLUMN)
                if name_item is None:
                    name_item = QTableWidgetItem("")
                    name_item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(r, ATTACHMENT_COMPONENT_NAME_COLUMN, name_item)
                name_item.setFlags(ATTACHMENT_COMPONENT_NAME_ITEM_FLAGS)
                if name_item.text().strip() != target_name:
                    name_item.setText(target_name)
    finally:
        try:
            table.blockSignals(False)
        except Exception:
            pass

    # 删除后刷新序号（附件从第1行开始计数）
    if hasattr(stats_widget, "refresh_attachment_table_sequence"):
        stats_widget.refresh_attachment_table_sequence()


"""管口上移"""
def move_selected_pipe_rows_up(stats_widget):
    """
    将选中的行在界面上向上移动一行（仅界面显示，不修改数据库）
    :param stats_widget: 主窗口对象
    """
    table = stats_widget.tableWidget_pipe

    # 修改获取选中行的方式，使用与highlight_selected_rows相同的方法
    selected_rows = sorted(set(idx.row() for idx in table.selectedIndexes()))

    # 禁止最后一行参与上移（最后一行用于新增）
    last_row_index = table.rowCount() - 1
    selected_rows = [r for r in selected_rows if r != last_row_index]

    if not selected_rows:
        stats_widget.line_tip.setText("最后一行不能上移，请先选择要上移的行")#提示
        stats_widget.line_tip.setStyleSheet("color: red;")
        return

    if selected_rows[0] <= 0:
        stats_widget.line_tip.setText("已到顶部，无法继续上移")#提示 有问题
        stats_widget.line_tip.setStyleSheet("color: red;")
        return
    
    # 阻止信号触发
    table.blockSignals(True)
    
    # 从上到下处理每一行（顺序很重要）
    for row in selected_rows:
        above_row = row - 1
        for col in range(1, table.columnCount()):  # 跳过序号列
            # 获取当前行和上一行的单元格内容
            current_item = table.takeItem(row, col)
            above_item = table.takeItem(above_row, col)
            # 交换单元格内容
            
            table.setItem(row, col, above_item)
            table.setItem(above_row, col, current_item)

    # 更新序号列
    stats_widget.refresh_pipe_table_sequence()

    # 清除之前的选中
    table.clearSelection()
    # 使用 setRangeSelected 强制选中行范围
    for row in [r - 1 for r in selected_rows]:
        table.setRangeSelected(QTableWidgetSelectionRange(row, 0, row, table.columnCount() - 1), True)
    # 强制焦点回到表格
    table.setFocus()
    # 延迟调用高亮处理，确保 selectionModel 处于最新状态
    # QTimer.singleShot(0, stats_widget.highlight_selected_rows)
    # 恢复信号
    table.blockSignals(False)
    # 手动调用高亮方法，确保高亮样式跟随移动
    # stats_widget.highlight_selected_rows()
    #——同步隐藏ID——
    for row in selected_rows:
        swap_hidden_id(stats_widget, row, row-1)

"""管口下移"""
def move_selected_pipe_rows_down(stats_widget):
    """
    将选中的行在界面上向下移动一行（不交换序号列，序号列重新编号）
    """
    table = stats_widget.tableWidget_pipe
    row_count = table.rowCount()
    
    # 修改获取选中行的方式，使用与highlight_selected_rows相同的方法
    selected_rows = sorted(set(idx.row() for idx in table.selectedIndexes()), reverse=True)

    if not selected_rows:
        stats_widget.line_tip.setText("请先选中要下移的行")#提示
        stats_widget.line_tip.setStyleSheet("color: red;")
        return

    if selected_rows[0] >= row_count - 2:
        stats_widget.line_tip.setText("已到最底部，无法继续下移")#提示
        stats_widget.line_tip.setStyleSheet("color: red;")
        return

    # 阻止信号触发
    table.blockSignals(True)

    # 从下到上处理每一行（顺序很重要）
    for row in selected_rows:
        below_row = row + 1
        if below_row >= row_count:
            continue
            
        for col in range(1, table.columnCount()):  # 从第1列开始交换（跳过序号列）
            current_item = table.takeItem(row, col)
            below_item = table.takeItem(below_row, col)
            
            table.setItem(row, col, below_item)
            table.setItem(below_row, col, current_item)

    # 更新序号列
    stats_widget.refresh_pipe_table_sequence()
    # 清除旧选中行
    table.clearSelection()
    # 新选中的行（下移后 +1）
    new_selected_rows = [r + 1 for r in selected_rows if r + 1 < row_count]
    for row in new_selected_rows:
        table.setRangeSelected(QTableWidgetSelectionRange(row, 0, row, table.columnCount() - 1), True)
    # 强制焦点刷新
    table.setFocus()
    # 延迟调用高亮处理
    # QTimer.singleShot(0, stats_widget.highlight_selected_rows)
    # 恢复信号
    table.blockSignals(False)
    # 手动调用高亮方法，确保高亮样式跟随移动
    # stats_widget.highlight_selected_rows()
    # ——同步隐藏ID——
    for row in selected_rows:
        swap_hidden_id(stats_widget, row, row + 1)


"""检查最后一行的管口代号是否已填写，如果已填写则添加新行"""
def check_last_row_and_add_new(stats_widget):
    """
    检查最后一行的管口代号是否已填写，如果已填写则添加新行
    :param stats_widget: 主窗口实例
    """
    table = stats_widget.tableWidget_pipe
    last_row = table.rowCount() - 1

    if last_row < 0:
        return  # 表格为空，跳过

    # 获取最后一行的管口代号
    last_port_code_item = table.item(last_row, 1)
    last_code_text = last_port_code_item.text().strip() if last_port_code_item else ""

    # 如果最后一行的管口代号不为空，添加新行
    if last_code_text:
        # 添加新行
        # === 临时断开 cellChanged 信号，防止误触发验证 ===
        try:
            table.blockSignals(True)
            # 添加新行
            new_row = table.rowCount()
            table.setRowCount(new_row + 1)

            # 设置新行的每个单元格为空白并居中
            for col in range(table.columnCount()):
                item = QTableWidgetItem()
                item.setTextAlignment(Qt.AlignCenter)
                if col == 0:
                    item.setText(str(new_row + 1)) # 序号列
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable) # 序号列不可编辑
                elif col == 1:
                    # 管口代号列：保持可编辑
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)
                else:
                    # 其他列：设为不可编辑（冻结状态）
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                table.setItem(new_row, col, item)
            
            # 添加新行后自动调整列宽
            stats_widget.adjust_pipe_column_width()
        finally:
            # === 恢复信号连接 ===
            table.blockSignals(False)
        # 刷新序号
        stats_widget.refresh_pipe_table_sequence()


"""检查附件定义最后一行的元件名称是否已填写，如果已填写则添加新行"""
def check_last_attachment_row_and_add_new(stats_widget):
    """
    检查附件定义表（tableWidget_attachment）最后一行的“元件名称”是否已填写，
    如果已填写则在末尾添加一行空白行。
    约定：
    - 第0行为表头
    - 第0列为序号列（不可编辑）
    - 第1列为元件名称列（触发新增行）
    """
    table = getattr(stats_widget, "tableWidget_attachment", None)
    if table is None:
        return

    last_row = table.rowCount() - 1
    if last_row < 1:
        return  # 只有表头或表格为空

    # 最后一行元件名称（列1）
    last_name_item = table.item(last_row, 1)
    last_name_text = last_name_item.text().strip() if last_name_item else ""
    if not last_name_text:
        return

    # 新增空白占位行时不分配元件ID：
    # 仅当该行真正填写了元件名称并参与保存时，再在 save_all_attachment_define_data 中按需分配
    try:
        table.blockSignals(True)
        new_row = table.rowCount()
        table.setRowCount(new_row + 1)
        table.setRowHeight(new_row, 40)

        # 新行初始化：全部居中；序号列不可编辑；元件名称列仅按钮程序填入；无名称时后续列锁定
        for col in range(table.columnCount()):
            item = QTableWidgetItem("")
            item.setTextAlignment(Qt.AlignCenter)
            if col == 0:
                # 序号从1开始（跳过表头）
                item.setText(str(new_row))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            elif col == 1:
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            else:
                if 4 <= col <= 12:
                    item.setFlags(Qt.ItemIsEnabled)
                else:
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            if 4 <= col <= 12:
                item.setBackground(QBrush(QColor(235, 235, 235)))
            table.setItem(new_row, col, item)
        # 新空白行作为最后一行：后续列保持冻结（与管口新增空行一致）
        control_last_attachment_row_editable_state(stats_widget, enable_editing=False)

    finally:
        table.blockSignals(False)

    # 刷新序号列（与 UI 里的实现保持一致）
    if hasattr(stats_widget, "refresh_attachment_table_sequence"):
        stats_widget.refresh_attachment_table_sequence()

"""控制最后一行其他列的编辑状态"""
def control_last_row_editable_state(stats_widget, enable_editing=True):
    """
    控制最后一行除管口代号外其他列的可编辑状态
    :param stats_widget: 主窗口实例
    :param enable_editing: True为解冻（可编辑），False为冻结（不可编辑）
    """
    table = stats_widget.tableWidget_pipe
    last_row = table.rowCount() - 1
    
    if last_row < 0:
        return
    
    # 检查是否确实是最后一行且管口代号已填写
    last_port_code_item = table.item(last_row, 1)
    if not last_port_code_item:
        return
    
    print(f"[DEBUG] 最后一行管口代号: '{last_port_code_item.text()}'")
    
    changed_count = 0
    for col in range(2, table.columnCount()):  # 从第2列开始（跳过序号和管口代号）
        item = table.item(last_row, col)
        if item:
            if enable_editing:
                # 解冻：恢复可编辑状态
                old_flags = item.flags()
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)
                new_flags = item.flags()
                if old_flags != new_flags:
                    changed_count += 1
                    print(f"[DEBUG] 列{col} 解冻成功")
            else:
                # 冻结：设为不可编辑
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                changed_count += 1


def control_last_attachment_row_editable_state(stats_widget, enable_editing=True):
    """
    控制附件表最后一行仅第 2、3 列的可编辑状态（其余后续列暂不启用，保持冻结）。
    仅处理 tableWidget_attachment 的最后一行数据行（第 0 行为表头）。
    :param enable_editing: True 解冻第 2、3 列；False 冻结
    """
    table = getattr(stats_widget, "tableWidget_attachment", None)
    if table is None:
        return
    last_row = table.rowCount() - 1
    if last_row < 1:
        return
    target_cols = [2, 3]
    for col in target_cols:
        if col >= table.columnCount():
            continue
        item = table.item(last_row, col)
        if item:
            if enable_editing:
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)
            else:
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)


def sync_attachment_row_tail_editable_by_name(stats_widget, row):
    """
    仅一行：根据该行第 1 列是否已有元件名称，设置第 2、3 列是否可编辑。
    用于非「最后一行占位行」的数据行；整段在 blockSignals 下执行，减轻 cellChanged 重入。
    """
    table = getattr(stats_widget, "tableWidget_attachment", None)
    if table is None or row <= 0 or row >= table.rowCount():
        return
    name_item = table.item(row, 1)
    if name_item is None:
        name_item = QTableWidgetItem("")
        name_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 1, name_item)
    has_name = name_item.text().strip() != ""
    table.blockSignals(True)
    try:
        # 元件名称列仅可选中，由界面 pic_* 按钮程序填入，不可手编
        name_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        target_cols = [2, 3]
        for col in target_cols:
            if col >= table.columnCount():
                continue
            item = table.item(row, col)
            if item is None:
                item = QTableWidgetItem("")
                item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, col, item)
            if has_name:
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)
            else:
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
    finally:
        table.blockSignals(False)


"""判断新输入的管口代号是否在界面上已存在"""
def is_duplicate_port_code(table, new_code: str, current_row: int) -> bool:
    """
    判断新输入的管口代号是否与其他行重复（排除自身）
    """
    for row in range(table.rowCount() - 1):  # 不包含新增空行
        if row == current_row:
            continue
        item = table.item(row, 1)  # 第1列为管口代号
        if item and item.text().strip() == new_code:
            return True
    return False


"""管口复制功能"""

"""对需要复制的管口选择"""
def copy_pipe_data(stats_widget, product_id):
    """
    管口复制功能：弹出对话框选择要复制的管口，然后复制到最新的空白行
    """


    table_pipe = stats_widget.tableWidget_pipe

    # 收集当前界面所有已填写的管口号
    pipe_codes = []
    for row in range(table_pipe.rowCount() - 1):  # 排除最后空白行
        code_item = table_pipe.item(row, 1)  # 第1列为管口代号
        if code_item and code_item.text().strip():
            pipe_codes.append(code_item.text().strip())

    if not pipe_codes:
        QMessageBox.information(stats_widget, "提示", "当前没有可复制的管口数据")
        return

    # 创建选择对话框
    dialog = QDialog(stats_widget)
    dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)
    dialog.setWindowTitle("管口复制")
    dialog.setModal(True)
    dialog.resize(300, 400)

    layout = QVBoxLayout(dialog)

    # 添加说明标签
    label = QLabel("请选择要复制的管口代号：")
    label.setStyleSheet("background-color: transparent;")
    layout.addWidget(label)

    # 创建列表控件
    list_widget = QListWidget()
    list_widget.addItems(pipe_codes)
    layout.addWidget(list_widget)

    # 按钮布局
    button_layout = QHBoxLayout()

    # 确定按钮
    ok_button = QPushButton("确定")
    ok_button.clicked.connect(dialog.accept)

    # 取消按钮
    cancel_button = QPushButton("取消")
    cancel_button.clicked.connect(dialog.reject)

    button_layout.addWidget(ok_button)
    button_layout.addWidget(cancel_button)
    layout.addLayout(button_layout)

    # 显示对话框
    if dialog.exec_() == QDialog.Accepted:
        selected_items = list_widget.selectedItems()
        if not selected_items:
            QMessageBox.warning(stats_widget, "警告", "请选择一个管口进行复制")
            return

        selected_code = selected_items[0].text()

        # 找到选中的管口所在行
        source_row = -1
        for row in range(table_pipe.rowCount() - 1):
            code_item = table_pipe.item(row, 1)
            if code_item and code_item.text().strip() == selected_code:
                source_row = row
                break

        if source_row == -1:
            QMessageBox.warning(stats_widget, "错误", "未找到选中的管口数据")
            return

        # 复制数据到最新空白行
        copy_pipe_row_data(stats_widget, source_row, product_id)

"""复制选中数据到空白行选择"""
def copy_pipe_row_data(stats_widget, source_row: int, product_id):
    """
    将指定行的管口数据复制到最新的空白行（倒数第一行）
    """
    table_pipe = stats_widget.tableWidget_pipe
    ensure_hidden_maps(stats_widget)

    # 找到最新的空白行（倒数第一行，即最后一行）
    target_row = table_pipe.rowCount() - 1

    # 检查最后一行是否已有数据
    last_row_code_item = table_pipe.item(target_row, 1)  # 第1列为管口代号
    if last_row_code_item and last_row_code_item.text().strip():
        # 如果最后一行已有数据，需要先添加新的空白行
        # 调用现有的函数来添加新行
        check_last_row_and_add_new(stats_widget)
        # 重新获取目标行（现在应该是新添加的空白行）
        target_row = table_pipe.rowCount() - 1

    # 复制数据（跳过序号列）
    fields = ["管口代号", "管口功能", "管口用途", "公称尺寸", "法兰标准", "压力等级", "法兰型式",
              "密封面型式", "焊端规格", "管口所属元件", "轴向定位基准", "轴向定位距离",
              "轴向夹角（°）", "周向方位（°）", "偏心距", "外伸高度", "管口附件", "管口载荷"]

    # 生成新的管口代号（在原代号后加序号）
    source_code_item = table_pipe.item(source_row, 1)
    if source_code_item:
        source_code = source_code_item.text().strip()
        # 生成新的管口代号
        new_code = generate_unique_pipe_code(table_pipe, source_code)

        # 复制数据到目标行
        for col_idx, field_name in enumerate(fields, start=1):  # 从第1列开始（跳过序号列）
            source_item = table_pipe.item(source_row, col_idx)
            if source_item:
                text_to_set = source_item.text()
                # 特殊规则：当“管口功能”为以下任一值时，复制后置空
                if col_idx == 2 and text_to_set.strip() in {"管程出口", "管程入口", "壳程出口", "壳程入口","排气口","排液口","壳程气相出口","壳程液相出口","壳程液位计1","壳程液位计2","壳程温度计"}:
                    text_to_set = ""

                new_item = QTableWidgetItem(text_to_set)
                new_item.setTextAlignment(Qt.AlignCenter)

                # 如果是管口代号列，使用新生成的代号
                if col_idx == 1:  # 管口代号列
                    new_item.setText(new_code)
                    new_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)
                else:
                    # 其他列保持原数据（或置空），但设为可编辑
                    new_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled)

                table_pipe.setItem(target_row, col_idx, new_item)

    # 为新行分配新的管口ID
    new_pipe_id = get_next_pipe_id_runtime(stats_widget, product_id)
    stats_widget.row_hidden_pipe_id[target_row] = new_pipe_id

    # 刷新序号
    stats_widget.refresh_pipe_table_sequence()

    # 调整列宽
    stats_widget.adjust_pipe_column_width()

    # 设置管口功能列只读状态
    set_pipe_function_column_readonly(stats_widget)

    # 提示复制成功
    stats_widget.line_tip.setText(f"已复制管口数据到新行，新管口代号：{new_code}")
    stats_widget.line_tip.setStyleSheet("color: blue;")
    QTimer.singleShot(5000, lambda: stats_widget.line_tip.setText(""))

"""对复制的管口生成唯一的管口代号"""
def generate_unique_pipe_code(table, base_code: str) -> str:
    """
    基于基础管口代号生成唯一的管口代号：
    - 若末尾为数字：递增数字（如 N4 -> N5, g1 -> g2）
    - 若末尾为字母：递增最后一个字母（区分大小写，如 C -> D, INLET -> INLEU）
    - 若无法解析：保留原有“直接添加数字后缀”的逻辑
    """


    # 收集当前已存在的所有代码（排除最后空白行）
    existing_codes = set()
    for row in range(table.rowCount() - 1):
        item = table.item(row, 1)
        if item:
            existing_codes.add(item.text().strip())

    # 尝试解析末尾为一串字母或一串数字
    m = re.match(r'^(.*?)([A-Za-z]+|\d+)$', base_code)
    if m:
        prefix = m.group(1)
        tail = m.group(2)

        def next_letters(s: str) -> str:
            # 仅对最后一个字母做进位：Z/z 溢出时在末尾追加 'A'/'a'
            if not s:
                return 'A'
            last = s[-1]
            if 'A' <= last <= 'Y':
                return s[:-1] + chr(ord(last) + 1)
            if last == 'Z':
                return s + 'A'
            if 'a' <= last <= 'y':
                return s[:-1] + chr(ord(last) + 1)
            if last == 'z':
                return s + 'a'
            # 其它字符不应出现，兜底追加 'A'
            return s + 'A'

        # 生成候选并确保唯一
        if tail.isdigit():
            num = int(tail)
            candidate = f"{prefix}{num + 1}"
            while candidate in existing_codes:
                num += 1
                candidate = f"{prefix}{num + 1}"
            return candidate
        else:
            # 字母尾：对最后一个字母递增
            new_tail = next_letters(tail)
            candidate = f"{prefix}{new_tail}"
            # 若冲突，继续递增直至唯一
            counter_guard = 0
            while candidate in existing_codes and counter_guard < 1000:
                new_tail = next_letters(new_tail)
                candidate = f"{prefix}{new_tail}"
                counter_guard += 1
            return candidate

    # 无法解析时：直接添加数字后缀并去重
    seq = 1
    candidate = f"{base_code}{seq}"
    while candidate in existing_codes:
        seq += 1
        candidate = f"{base_code}{seq}"
    return candidate


# 附件元件复制：以下名称全表各至多一个，不提供复制入口
ATTACHMENT_NON_COPYABLE_ELEMENT_NAMES = frozenset({"耳座", "鞍式支座", "铭牌"})
# 粘贴到空白行时，与 validate_attachment_element_name 一致的全表单件名（用于重名时加后缀）
_ATT_SINGLETON_ELEMENT_NAMES = frozenset({"鞍式支座", "耳座", "铭牌"})
# 可重复且采用“第二个开始编号”规则的元件
_ATT_AUTO_INDEXED_REPEATABLE_NAMES = frozenset({"吊耳", "保温支撑圈", "保温支撑条"})


def _existing_attachment_element_names_except_row(table, except_row: int):
    out = set()
    for r in range(1, table.rowCount()):
        if r == except_row:
            continue
        it = table.item(r, 1)
        if it and it.text().strip():
            out.add(it.text().strip())
    return out


def _resolve_attachment_element_name_for_paste(table, target_row: int, proposed: str) -> str:
    """将源行元件名称粘贴到 target_row 时，与其它行去重（单件名与其它行冲突时加 1、2…）。"""
    proposed = (proposed or "").strip()
    if not proposed:
        return proposed
    existing = _existing_attachment_element_names_except_row(table, target_row)
    if proposed in _ATT_SINGLETON_ELEMENT_NAMES:
        if proposed not in existing:
            return proposed
        n = 1
        while f"{proposed}{n}" in existing:
            n += 1
        return f"{proposed}{n}"

    # 可重复元件（吊耳/保温支撑圈/保温支撑条）：
    # - 家族首个保持原名；
    # - 当复制导致出现第二个时，把首个改为 name1，新复制为 name2。
    if proposed in _ATT_AUTO_INDEXED_REPEATABLE_NAMES:
        # 若存在“原名”行，先把它改为 name1（或当前可用的最小编号）
        if proposed in existing:
            plain_row = None
            for r in range(1, table.rowCount()):
                if r == target_row:
                    continue
                it = table.item(r, 1)
                if it and it.text().strip() == proposed:
                    plain_row = r
                    break
            if plain_row is not None:
                n_plain = 1
                candidate_plain = f"{proposed}{n_plain}"
                while candidate_plain in existing:
                    n_plain += 1
                    candidate_plain = f"{proposed}{n_plain}"
                plain_item = table.item(plain_row, 1)
                if plain_item is None:
                    plain_item = QTableWidgetItem("")
                    plain_item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(plain_row, 1, plain_item)
                table.blockSignals(True)
                try:
                    plain_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                    plain_item.setText(candidate_plain)
                finally:
                    table.blockSignals(False)
                existing.discard(proposed)
                existing.add(candidate_plain)

        # 家族存在时，新复制项取下一个可用序号；家族不存在则保留原名
        has_family = any(
            (name == proposed) or re.match(rf"^{re.escape(proposed)}\d+$", name)
            for name in existing
        )
        if not has_family:
            return proposed
        n_new = 1
        candidate_new = f"{proposed}{n_new}"
        while candidate_new in existing:
            n_new += 1
            candidate_new = f"{proposed}{n_new}"
        return candidate_new

    if proposed not in existing:
        return proposed
    # 参考管口代号生成：若末尾带数字，则递增数字；否则从 1 开始补后缀
    m = re.match(r"^(.*?)(\d+)$", proposed)
    if m:
        base = m.group(1)
        num = int(m.group(2))
        candidate = f"{base}{num + 1}"
        while candidate in existing:
            num += 1
            candidate = f"{base}{num + 1}"
        return candidate

    n = 1
    candidate = f"{proposed}{n}"
    while candidate in existing:
        n += 1
        candidate = f"{proposed}{n}"
    return candidate


"""对需要复制的附件元件选择（逻辑同管口复制）"""
def copy_attachment_data(stats_widget, product_id):
    """
    元件复制：弹出对话框选择要复制的附件行，复制到最后一行空白行。
    第 0 行为表头，不参与收集与复制。
    耳座、鞍式支座、铭牌不提供复制（全表各至多一个）。
    """
    table = getattr(stats_widget, "tableWidget_attachment", None)
    if table is None:
        return

    copyable = []  # (展示文案, 源行号)；第 0 行为表头，不参与
    for row in range(1, table.rowCount() - 1):
        name_item = table.item(row, 1)
        if not name_item:
            continue
        name = name_item.text().strip()
        if not name:
            continue
        if name in ATTACHMENT_NON_COPYABLE_ELEMENT_NAMES:
            continue
        copyable.append((name, row))

    if not copyable:
        QMessageBox.information(
            stats_widget, "提示", "当前没有可复制的附件元件（耳座、鞍式支座、铭牌不可复制）"
        )
        return

    dialog = QDialog(stats_widget)
    dialog.setWindowFlags(dialog.windowFlags() & ~Qt.WindowContextHelpButtonHint)
    dialog.setWindowTitle("元件复制")
    dialog.setModal(True)
    dialog.resize(360, 420)

    layout = QVBoxLayout(dialog)
    label = QLabel("请选择要复制的元件：")
    label.setStyleSheet("background-color: transparent;")
    layout.addWidget(label)

    list_widget = QListWidget()
    for display_text, _row in copyable:
        list_widget.addItem(display_text)
    # 避免未选择时 currentRow 默认落在首行导致误复制
    list_widget.clearSelection()
    list_widget.setCurrentRow(-1)
    layout.addWidget(list_widget)

    row_by_index = [r for _, r in copyable]

    button_layout = QHBoxLayout()
    ok_button = QPushButton("确定")
    ok_button.clicked.connect(dialog.accept)
    cancel_button = QPushButton("取消")
    cancel_button.clicked.connect(dialog.reject)
    button_layout.addWidget(ok_button)
    button_layout.addWidget(cancel_button)
    layout.addLayout(button_layout)

    if dialog.exec_() != QDialog.Accepted:
        return

    selected_items = list_widget.selectedItems()
    if not selected_items:
        QMessageBox.warning(stats_widget, "警告", "请选择一个元件进行复制")
        return
    selected = list_widget.row(selected_items[0])
    if selected < 0 or selected >= len(row_by_index):
        QMessageBox.warning(stats_widget, "警告", "请选择一个元件进行复制")
        return
    source_row = row_by_index[selected]
    copy_attachment_row_data(stats_widget, source_row, product_id)


def copy_attachment_row_data(stats_widget, source_row: int, product_id):
    """将指定附件行复制到最后一行空白行，并分配新元件 ID。"""
    table = getattr(stats_widget, "tableWidget_attachment", None)
    if table is None or source_row <= 0 or source_row >= table.rowCount():
        return

    ensure_hidden_attachment_maps(stats_widget)
    # 目标行优先使用“从上到下第一个空白数据行”（第0行为表头）
    target_row = None
    for r in range(1, table.rowCount()):
        it = table.item(r, 1)
        if it is None or not it.text().strip():
            target_row = r
            break

    # 若不存在空白行，则在末尾新增一行再作为目标
    if target_row is None:
        check_last_attachment_row_and_add_new(stats_widget)
        target_row = table.rowCount() - 1

    source_name_item = table.item(source_row, 1)
    source_name = source_name_item.text().strip() if source_name_item else ""
    if not source_name:
        QMessageBox.warning(stats_widget, "警告", "源行没有元件名称，无法复制")
        return
    if source_name in ATTACHMENT_NON_COPYABLE_ELEMENT_NAMES:
        QMessageBox.warning(stats_widget, "警告", "该元件不允许复制")
        return

    new_element_name = _resolve_attachment_element_name_for_paste(
        table, target_row, source_name
    )

    try:
        table.blockSignals(True)
        for col in range(1, table.columnCount()):
            # 复制策略：当前仅复制前3列；第4列及以后清空
            src = table.item(source_row, col)
            if col == 1:
                text = new_element_name
            elif col in (2, 3):
                text = src.text() if src else ""

            new_item = QTableWidgetItem(text)
            new_item.setTextAlignment(Qt.AlignCenter)
            if col == 1:
                new_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            elif col in (2, 3):
                # 当前附件策略：仅第2、3列可编辑
                new_item.setFlags(
                    Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsEnabled
                )
            else:
                # 第4列及以后暂不启用，保持冻结且不可选中
                new_item.setFlags(Qt.ItemIsEnabled)
            if 4 <= col <= 12:
                new_item.setBackground(QBrush(QColor(235, 235, 235)))
            table.setItem(target_row, col, new_item)
    finally:
        table.blockSignals(False)

    if product_id:
        new_id = get_next_attachment_id_runtime(stats_widget, product_id)
        stats_widget.row_hidden_attachment_id[target_row] = new_id

    if hasattr(stats_widget, "refresh_attachment_table_sequence"):
        stats_widget.refresh_attachment_table_sequence()
    if hasattr(stats_widget, "update_attachment_row_editable_state"):
        stats_widget.update_attachment_row_editable_state(target_row)
    check_last_attachment_row_and_add_new(stats_widget)

    if hasattr(stats_widget, "line_tip") and stats_widget.line_tip:
        stats_widget.line_tip.setText(
            f"已复制附件到新行，元件名称：{new_element_name}"
        )
        stats_widget.line_tip.setStyleSheet("color: blue;")
        QTimer.singleShot(5000, lambda: stats_widget.line_tip.setText(""))


"""初始默认管口不可删除"""
def set_default_pipe_cannot_be_deleted(stats_widget):
    """
    根据产品类型和型式，设置默认管口不可删除的管口功能集合
    同时设置 cannot_be_deleted 标志为 True（表示保护生效）

    :param stats_widget: 主窗口实例
    """
    # 初始化 cannot_be_deleted 标志为 True（表示保护生效）
    stats_widget.cannot_be_deleted = True

    # 直接获取产品类型和型式
    product_type = getattr(stats_widget, "current_product_type", "")
    product_version = getattr(stats_widget, "current_product_version", "")

    # 初始化不可删除的管口功能集合（注意：这里是管口功能，不是管口代号）
    readonly_pipe_functions = set()

    # 根据产品类型和型式确定不可删除的管口功能
    if product_type == "管壳式热交换器":
        if product_version in ["AEU", "BEU"]:
            readonly_pipe_functions = {"管程入口", "管程出口", "壳程入口", "壳程出口"}
        elif product_version in ["AES", "BES","NEN","AME","BEM","NEN(Head)"]:
            readonly_pipe_functions = {"管程入口", "管程出口", "壳程入口", "壳程出口", "排液口", "排气口"}
        elif product_version in ["AKU","BKU"]:
            readonly_pipe_functions = {"管程入口", "管程出口", "壳程入口", "壳程气相出口","壳程液相出口","壳程液位计1","壳程液位计2","壳程温度计"}

    # 保存到 stats_widget 实例属性中
    stats_widget.readonly_pipe_functions = readonly_pipe_functions

