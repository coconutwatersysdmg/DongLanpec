from typing import Callable
import weakref

import sip

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QComboBox, QTableWidget


def ensure_table_tooltip_updater(
    table: QTableWidget,
    *,
    combo_formatter=None,
    item_formatter=None,
) -> Callable[[], None]:
    """
    确保为指定的 QTableWidget 安装 tooltip 自动更新机制。
    combo_formatter / item_formatter 应返回字符串（允许返回空字符串，表示清空 tooltip），
    也可以返回 None（同样视为清空 tooltip）。
    函数返回一个可调用对象，执行后会立即刷新整张表格的 tooltip。
    """

    if combo_formatter is None:
        combo_formatter = lambda combo, row, col: combo.currentText().strip()

    if item_formatter is None:
        item_formatter = lambda item, row, col: (item.text() or "").strip()

    support = getattr(table, "_tooltip_support", None)

    if support is None:
        support = {
            "pending": False,
            "destroyed": False,
            "table_ref": weakref.ref(table),
        }
        table._tooltip_support = support  # type: ignore[attr-defined]

        def mark_destroyed():
            support["destroyed"] = True

        table.destroyed.connect(mark_destroyed)

        def schedule_update():
            if support["pending"] or support["destroyed"]:
                return

            support["pending"] = True

            def _run():
                support["pending"] = False
                if not support["destroyed"]:
                    update_all()

            QTimer.singleShot(0, _run)

        support["schedule_update"] = schedule_update

        def bind_combo(combo: QComboBox):
            if getattr(combo, "_tooltip_support_connected", False):
                return

            if sip.isdeleted(combo):
                return

            combo.currentTextChanged.connect(schedule_update)
            combo.editTextChanged.connect(schedule_update)
            combo._tooltip_support_connected = True  # type: ignore[attr-defined]

        support["bind_combo"] = bind_combo

        def update_all():
            table_ref = support["table_ref"]()
            if table_ref is None or sip.isdeleted(table_ref):
                support["destroyed"] = True
                return

            combo_fmt = support["combo_formatter"]
            item_fmt = support["item_formatter"]

            for row in range(table_ref.rowCount()):
                for col in range(table_ref.columnCount()):
                    cell_widget = table_ref.cellWidget(row, col)
                    if isinstance(cell_widget, QComboBox):
                        if sip.isdeleted(cell_widget):
                            continue

                        tooltip = combo_fmt(cell_widget, row, col)
                        cell_widget.setToolTip("" if tooltip is None else str(tooltip))
                        bind_combo(cell_widget)
                    else:
                        item = table_ref.item(row, col)
                        if not item:
                            continue
                        if sip.isdeleted(item):
                            continue
                        tooltip = item_fmt(item, row, col)
                        item.setToolTip("" if tooltip is None else str(tooltip))

        support["update_all"] = update_all

        # 只在首次安装时连接信号
        model = table.model()
        schedule = support["schedule_update"]
        if model:
            model.dataChanged.connect(lambda *args: schedule())
            model.rowsInserted.connect(lambda *args: schedule())
            model.rowsRemoved.connect(lambda *args: schedule())
            model.modelReset.connect(schedule)
            model.layoutChanged.connect(lambda *args: schedule())

        table.itemChanged.connect(lambda *args: schedule())
        table.cellChanged.connect(lambda *args: schedule())

    # 更新格式化函数并立即刷新一次
    support["combo_formatter"] = combo_formatter
    support["item_formatter"] = item_formatter

    update_now = support["update_all"]
    update_now()

    return update_now


