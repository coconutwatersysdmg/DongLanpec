# -*- coding: utf-8 -*-
"""
容器产品：顶部「管束设计」按钮可见性 / 前置校验 / 打开拦截。
逻辑集中在此文件；main.py 仅保留少量调用或 install() 一行安装。
"""
from __future__ import annotations

import sys

from PyQt5.QtWidgets import QAbstractButton

import modules.chanpinguanli.bianl as bianl
from modules.chanpinguanli.common_usage import (
    get_mysql_connection_product,
    get_mysql_connection_active,
)

TUBE_BUNDLE_BTN_OBJECT_NAME = "btn_pipeDesign"
# True=隐藏按钮；False=仅禁用（不禁用时可改为 setEnabled）
HIDE_TUBE_BUNDLE_BTN = True


def _product_type_from_db_row(row) -> str:
    if not row:
        return ""
    if isinstance(row, dict):
        return str(row.get("产品类型") or "").strip()
    return str(row[0] or "").strip()


def is_product_defined(product_id) -> bool:
    """产品定义已保存（definition_status == view）。"""
    if not product_id:
        return False
    for _row, status_dict in bianl.product_table_row_status.items():
        if not isinstance(status_dict, dict):
            continue
        if status_dict.get("product_id") == product_id:
            return status_dict.get("definition_status") == "view"
    return False


def is_container_product_id(product_id) -> bool:
    """产品类型是否属于容器（含立式/卧式）。"""
    if not product_id:
        return False
    queries = (
        ("SELECT 产品类型 FROM 产品需求表 WHERE 产品ID = %s", get_mysql_connection_product),
        ("SELECT 产品类型 FROM 产品设计活动表 WHERE 产品ID = %s", get_mysql_connection_active),
    )
    for sql, connect in queries:
        conn = None
        try:
            conn = connect()
            with conn.cursor() as cursor:
                cursor.execute(sql, (product_id,))
                row = cursor.fetchone()
            product_type = _product_type_from_db_row(row)
            if product_type and "容器" in product_type:
                return True
        except Exception as e:
            print(f"[tube_bundle_toolbar] 查询产品类型失败: {e}")
        finally:
            if conn:
                conn.close()
    return False


def is_defined_container_product(product_id, product_type_hint=None) -> bool:
    if not product_id or not is_product_defined(product_id):
        return False
    hint = str(product_type_hint or "").strip()
    if hint and "容器" in hint:
        return True
    return is_container_product_id(product_id)


def resolve_app_top_window():
    """顶层主窗口（含 btn_pipeDesign）；不是项目管理子页 bianl.main_window。"""
    target = getattr(bianl, "app_top_window", None)
    if target is not None:
        return target
    for mod_name in ("__main__", "main"):
        mod = sys.modules.get(mod_name)
        if mod is not None:
            target = getattr(mod, "APP_MAIN_WINDOW", None)
            if target is not None:
                return target
    return None


def _apply_tube_bundle_btn_state(btn, hide: bool):
    if HIDE_TUBE_BUNDLE_BTN:
        btn.setVisible(not hide)
    else:
        btn.setVisible(True)
        btn.setEnabled(not hide)


def refresh_for_product(product_id=None, product_type_hint=None):
    """
    已定义容器：隐藏/禁用「管束设计」并关闭已打开 Tab。
    换热器或未定义：恢复显示/启用。
    """
    target = resolve_app_top_window()
    if target is None:
        print("[tube_bundle_toolbar] 未找到顶层主窗口")
        return

    btn = target.findChild(QAbstractButton, TUBE_BUNDLE_BTN_OBJECT_NAME)
    if btn is None:
        print("[tube_bundle_toolbar] 未找到 btn_pipeDesign")
        return

    hide = is_defined_container_product(product_id, product_type_hint)
    _apply_tube_bundle_btn_state(btn, hide)
    print(
        f"[tube_bundle_toolbar] product_id={product_id!r} hide={hide} "
        f"visible={btn.isVisible()} enabled={btn.isEnabled()}"
    )

    if not hide:
        return

    tw = getattr(target, "tab_widget", None)
    if tw is None:
        return
    for i in reversed(range(tw.count())):
        if tw.tabText(i) != "管束设计":
            continue
        if hasattr(target, "close_tab"):
            target.close_tab(i, force_close=True)
        else:
            widget_to_close = tw.widget(i)
            tw.removeTab(i)
            if widget_to_close:
                widget_to_close.deleteLater()
        break


def should_skip_tube_bundle_prerequisite(product_id) -> bool:
    """容器产品：设计运算等前置校验跳过管束设计数据检查。"""
    return is_defined_container_product(product_id)


def should_block_tube_bundle_tab(product_id) -> bool:
    """容器产品：禁止打开管束设计模块。"""
    return is_defined_container_product(product_id)


def prerequisites_hint_message(product_id) -> str:
    if should_skip_tube_bundle_prerequisite(product_id):
        return (
            "请先完成【条件输入】、【元件定义】、【管口及附件定义】"
            "模块的数据定义与保存！\n\n"
        )
    return (
        "请先完成【条件输入】、【元件定义】、【管口及附件定义】"
        "和【管束设计】模块的数据定义与保存！\n\n"
    )


def install(main_window):
    """
    可选：在 MainWindow.__init__ 末尾调用一次，自动监听产品切换信号。
    项目管理内的刷新仍由 chanpinguanli_main 调用 refresh_for_product。
    """
    try:
        from modules.chanpinguanli.chanpinguanli_main import product_manager

        def _on_pid_changed(new_id):
            refresh_for_product(new_id)

        product_manager.product_id_changed.connect(_on_pid_changed)
    except Exception as e:
        print(f"[tube_bundle_toolbar.install] 连接 product_id_changed 失败: {e}")

    setattr(main_window, "_tube_bundle_toolbar_installed", True)
