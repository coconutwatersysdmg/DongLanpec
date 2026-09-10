"""容器产品隐藏/跳过「管束设计」相关逻辑（供 main.py 调用）。"""

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QAbstractButton, QMessageBox

from modules.chanpinguanli.common_usage import get_mysql_connection_product

CONTAINER_PRODUCT_TYPES = {"立式容器", "卧式容器"}
CONTAINER_PRODUCT_FORMS = {"单腔型", "双腔型"}


def _fetch_product_type_form(product_id):
    """返回 (产品类型, 产品型式)，查不到则 ("", "")。"""
    if not product_id:
        return "", ""
    conn = None
    try:
        conn = get_mysql_connection_product()
        if not conn:
            return "", ""
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT `产品类型`, `产品型式` FROM `产品需求表` WHERE `产品ID` = %s LIMIT 1",
                (product_id,),
            )
            row = cursor.fetchone() or {}
            ptype = str(row.get("产品类型") or "").strip()
            pform = str(row.get("产品型式") or "").strip()
            return ptype, pform
    except Exception as e:
        print(f"[tube_bundle_toolbar] 查询产品类型失败: {e}")
        return "", ""
    finally:
        try:
            if conn and getattr(conn, "open", False):
                conn.close()
        except Exception:
            pass


def is_container_product(product_id) -> bool:
    """立式/卧式容器，或型式为单腔型/双腔型，视为容器产品。"""
    ptype, pform = _fetch_product_type_form(product_id)
    if ptype in CONTAINER_PRODUCT_TYPES:
        return True
    if pform in CONTAINER_PRODUCT_FORMS:
        return True
    return False


def should_block_tube_bundle_tab(product_id) -> bool:
    """容器产品不允许打开「管束设计」页签。"""
    if not is_container_product(product_id):
        return False
    try:
        QMessageBox.information(
            None,
            "提示",
            "当前为容器产品，不支持管束设计模块。",
        )
    except Exception:
        pass
    return True


def should_skip_tube_bundle_prerequisite(product_id) -> bool:
    """容器产品检查前置条件时跳过管束设计相关库表。"""
    return is_container_product(product_id)


def prerequisites_hint_message(product_id) -> str:
    """前置条件未满足时的提示文案。"""
    if is_container_product(product_id):
        return (
            "请先完成以下模块并保存数据后再进入：\n"
            "条件输入、元件定义、管口及附件定义。"
        )
    return (
        "请先完成以下模块并保存数据后再进入：\n"
        "条件输入、元件定义、管口及附件定义、管束设计。"
    )


def refresh_tube_bundle_button(main_window):
    """按当前产品显隐「管束设计」按钮。"""
    if main_window is None:
        return
    btn = None
    try:
        btn = main_window.findChild(QAbstractButton, "btn_pipeDesign")
    except Exception:
        btn = None
    if btn is None:
        return

    product_id = getattr(main_window, "current_product_id", None)
    if not product_id:
        try:
            import modules.chanpinguanli.bianl as bianl

            product_id = getattr(bianl, "current_product_id", None)
        except Exception:
            product_id = None

    hide = bool(product_id) and is_container_product(product_id)
    btn.setVisible(not hide)


def install(main_window):
    """
    挂到主窗口：UI 加载后再刷新一次按钮，并在产品切换时更新显隐。
    注意：main.py 在 loadUi 之前调用本函数，因此用 singleShot 延后执行。
    """
    if main_window is None:
        return

    def _refresh():
        refresh_tube_bundle_button(main_window)

    QTimer.singleShot(0, _refresh)
    # 再补一次，避免 loadUi / 登录后按钮状态不同步
    QTimer.singleShot(500, _refresh)

    try:
        from modules.chanpinguanli.chanpinguanli_main import product_manager

        product_manager.product_id_changed.connect(lambda *_: _refresh())
    except Exception as e:
        print(f"[tube_bundle_toolbar] 连接 product_id_changed 失败: {e}")
