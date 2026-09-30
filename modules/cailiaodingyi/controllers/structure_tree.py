# -*- coding: utf-8 -*-
"""元件定义 - 结构树：配置读取、对话框、写库；隐藏清空材料并删除附加参数行，再显示时从模板回填。"""

from typing import Dict, List, Optional, Set, Tuple

import pymysql
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from modules.cailiaodingyi.controllers.style import apply_dialog_style
from modules.cailiaodingyi.db_cnt import get_connection
from modules.cailiaodingyi.funcs.funcs_pdf_change import DEBUG_VERBOSE_DEFINE_UI
from modules.cailiaodingyi.funcs.funcs_pdf_input import db_config_1, db_config_2

# 膨胀节：由预定义 user_config(2.9.5.2) 动态控制结构树必选/锁定
# 适用产品形式以材料库「结构树配置表」是否登记「膨胀节」为准，不在此硬编码。
EXPANSION_JOINT_NAME = "膨胀节"
EXPANSION_JOINT_CONFIG_ID = "2.9.5.2"
EXPANSION_JOINT_LOCK_TIP = "未勾选预定义「设置膨胀节，不增厚壳程圆筒」，不可选择"



def _dbg_print(msg: str) -> None:
    """统一受 DEBUG_VERBOSE_DEFINE_UI 控制的结构树调试输出。"""
    if DEBUG_VERBOSE_DEFINE_UI:
        print(msg)


def _element_display_name(row: dict) -> str:
    return (row.get("零件名称") or row.get("元件名称") or "").strip()


def _is_yes(val) -> bool:
    if val is None:
        return False
    s = str(val).strip()
    return s in ("是", "1", "true", "True", "Y", "y")


def is_expansion_joint_enabled_by_user_config() -> bool:
    """预定义 user_config(id=2.9.5.2) 是否勾选「设置膨胀节，不增厚壳程圆筒」。"""
    try:
        from modules.cailiaodingyi.funcs.funcs_pdf_change import (
            _get_user_config_value,
            _is_truthy_config_value,
        )
        return _is_truthy_config_value(_get_user_config_value(EXPANSION_JOINT_CONFIG_ID))
    except Exception as e:
        _dbg_print(f"[结构树][膨胀节] 读取 user_config({EXPANSION_JOINT_CONFIG_ID}) 失败: {e}")
        return False


def is_expansion_joint_in_structure_tree_config(product_type: str, product_form: str) -> bool:
    """结构树配置表是否为该类型+形式登记了膨胀节。"""
    if not product_type or not product_form:
        return False
    by_name, _, _ = config_maps_by_name(product_type, product_form)
    return EXPANSION_JOINT_NAME in by_name


def find_expansion_joint_element_id(all_elements: Optional[List[dict]]) -> Optional:
    for item in all_elements or []:
        if _element_display_name(item) == EXPANSION_JOINT_NAME:
            eid = item.get("元件ID")
            if eid is not None:
                return eid
    return None


def augment_structure_tree_for_expansion_joint(
    product_type: str,
    product_form: str,
    all_elements: List[dict],
    visible_ids: List,
    mandatory_ids: Optional[Set] = None,
    locked_hidden_ids: Optional[Set] = None,
) -> Tuple[List, Set, Set]:
    """
    按预定义 2.9.5.2 调整膨胀节在结构树中的状态：
    - 勾选：右侧显示且必选；
    - 未勾选：左侧锁定（变灰不可选）。
    仅当结构树配置表已登记「膨胀节」时生效；配置表静态「是否显示/必选」会被本函数覆盖。
    """
    visible_ids = list(visible_ids or [])
    mandatory_ids = set(mandatory_ids or set())
    locked_hidden_ids = set(locked_hidden_ids or set())

    if not is_expansion_joint_in_structure_tree_config(product_type, product_form):
        return visible_ids, mandatory_ids, locked_hidden_ids

    eid = find_expansion_joint_element_id(all_elements)
    if eid is None:
        return visible_ids, mandatory_ids, locked_hidden_ids

    if is_expansion_joint_enabled_by_user_config():
        if eid not in visible_ids:
            visible_ids.append(eid)
        mandatory_ids.add(eid)
        locked_hidden_ids.discard(eid)
    else:
        visible_ids = [x for x in visible_ids if x != eid]
        mandatory_ids.discard(eid)
        locked_hidden_ids.add(eid)

    return visible_ids, mandatory_ids, locked_hidden_ids


def sync_expansion_joint_visibility_for_product(
    product_id: str,
    product_type: Optional[str] = None,
    product_form: Optional[str] = None,
) -> bool:
    """
    按最新 2.9.5.2 同步单个产品活动库中膨胀节的显示：
    - 勾选且当前未显示（或材料为空）→ 显示并带入模板材料/参数值；
    - 未勾选且当前显示 → 隐藏并清空。
    返回是否发生了可见性或回填变化。
    """
    if not product_id:
        return False
    if product_form is None or product_type is None:
        try:
            from modules.cailiaodingyi.funcs.funcs_pdf_input import load_design_product_data
            product_type, product_form = load_design_product_data(product_id)
        except Exception as e:
            _dbg_print(f"[结构树][膨胀节] 读取产品型式失败 product={product_id}: {e}")
            return False
    if not is_expansion_joint_in_structure_tree_config(product_type, product_form):
        return False

    try:
        from modules.cailiaodingyi.funcs.funcs_pdf_input import load_element_info
        all_elements = load_element_info(product_id, only_visible=False) or []
    except Exception as e:
        _dbg_print(f"[结构树][膨胀节] 读取元件列表失败 product={product_id}: {e}")
        return False
    if not all_elements:
        return False

    eid = find_expansion_joint_element_id(all_elements)
    if eid is None:
        return False

    enabled = is_expansion_joint_enabled_by_user_config()
    visible_ids = visible_ids_from_rows(all_elements)
    currently_visible = eid in set(visible_ids)

    if enabled:
        need_template_fill = (
            (not currently_visible)
            or _expansion_joint_left_materials_blank(product_id, eid)
            or (_element_para_row_count(product_id, eid) <= 0)
        )
        if need_template_fill:
            # 直接按模板回填材料/附加参数值/合并表，并置是否显示=是
            restore_expansion_joint_from_template(
                product_id,
                eid,
                all_elements,
                product_type=product_type,
                product_form=product_form,
            )
            _dbg_print(
                f"[结构树][膨胀节] 预定义已勾选，已显示并带入模板值 "
                f"product={product_id} element={eid} was_visible={currently_visible}"
            )
            return True
        return False

    if currently_visible:
        visible_ids = [x for x in visible_ids if x != eid]
        apply_structure_tree_selection(product_id, all_elements, visible_ids)
        _dbg_print(f"[结构树][膨胀节] 预定义已取消，已隐藏 product={product_id} element={eid}")
        return True
    return False


def sync_expansion_joint_visibility_from_user_config() -> int:
    """对活动库中已有「膨胀节」元件的产品批量同步显示（是否适用由结构树配置表决定）。"""
    conn = get_connection(**db_config_1)
    changed = 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT p.产品ID, p.产品类型, p.产品型式
                FROM 产品设计活动表 p
                INNER JOIN 产品设计活动表_元件材料表 m
                    ON p.产品ID = m.产品ID
                WHERE m.元件名称 = %s
                """,
                (EXPANSION_JOINT_NAME,),
            )
            rows = cur.fetchall() or []
    except pymysql.MySQLError as e:
        _dbg_print(f"[结构树][膨胀节] 查询待同步产品失败: {e}")
        return 0
    finally:
        conn.close()

    seen = set()
    for row in rows:
        pid = str((row.get("产品ID") if isinstance(row, dict) else row[0]) or "").strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        ptype = (row.get("产品类型") if isinstance(row, dict) else row[1]) or ""
        pform = (row.get("产品型式") if isinstance(row, dict) else row[2]) or ""
        try:
            if sync_expansion_joint_visibility_for_product(pid, ptype, pform):
                changed += 1
        except Exception as e:
            _dbg_print(f"[结构树][膨胀节] 同步失败 product={pid}: {e}")
    return changed


def query_structure_tree_config(product_type: str, product_form: str) -> List[dict]:
    """从材料库读取结构树配置。"""
    if not product_type or not product_form:
        return []
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 元件名称, 是否显示, 是否必选
                FROM 结构树配置表
                WHERE 所属类型 = %s AND 所属形式 = %s
                """,
                (product_type, product_form),
            )
            return cur.fetchall() or []
    except pymysql.MySQLError as e:
        _dbg_print(f"[结构树] 读取配置失败: {e}")
        return []
    finally:
        conn.close()


def config_maps_by_name(
    product_type: str, product_form: str
) -> Tuple[Dict[str, dict], Set[str], Set[str]]:
    """
    返回 (name->config, 配置中默认显示的元件名, 必选元件名)。
    """
    rows = query_structure_tree_config(product_type, product_form)
    by_name: Dict[str, dict] = {}
    default_visible_names: Set[str] = set()
    mandatory_names: Set[str] = set()
    for row in rows:
        name = (row.get("元件名称") or "").strip()
        if not name:
            continue
        by_name[name] = row
        if _is_yes(row.get("是否显示")):
            default_visible_names.add(name)
        if _is_yes(row.get("是否必选")):
            mandatory_names.add(name)
    return by_name, default_visible_names, mandatory_names


def build_initial_visible_and_mandatory(
    template_elements: List[dict], product_type: str, product_form: str
) -> Tuple[List, Set]:
    """
    首次进入：按配置表 + 模板元件列表得到初始 visible 元件ID 与 mandatory 元件ID。
    配置中无记录的模板元件默认不显示。
    """
    _, default_visible_names, mandatory_names = config_maps_by_name(product_type, product_form)
    visible_ids: List = []
    mandatory_ids: Set = set()

    for item in template_elements or []:
        eid = item.get("元件ID")
        if eid is None:
            continue
        name = _element_display_name(item)
        if name in default_visible_names:
            visible_ids.append(eid)
        if name in mandatory_names:
            mandatory_ids.add(eid)

    return visible_ids, mandatory_ids


def mandatory_ids_for_elements(
    all_elements: List[dict], product_type: str, product_form: str
) -> Set:
    _, _, mandatory_names = config_maps_by_name(product_type, product_form)
    ids: Set = set()
    for item in all_elements or []:
        name = _element_display_name(item)
        if name in mandatory_names:
            eid = item.get("元件ID")
            if eid is not None:
                ids.add(eid)
    return ids


def visible_ids_from_rows(all_elements: List[dict]) -> List:
    ids = []
    for item in all_elements or []:
        disp = item.get("是否显示")
        if disp is None or disp == "" or _is_yes(disp):
            eid = item.get("元件ID")
            if eid is not None:
                ids.append(eid)
    return ids


def filter_visible_elements(element_rows: List[dict]) -> List[dict]:
    return [r for r in (element_rows or []) if r.get("元件ID") in set(visible_ids_from_rows(element_rows))]


class StructureTreeDialog(QDialog):
    """双列表：左=不显示，右=显示；必选不可移除；锁定隐藏项左侧灰且不可添加。"""

    def __init__(
        self,
        parent,
        all_elements: List[dict],
        visible_element_ids: List,
        mandatory_element_ids: Optional[Set] = None,
        locked_hidden_element_ids: Optional[Set] = None,
        title: str = "结构树",
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 480)
        apply_dialog_style(self)
        self._mandatory: Set = set(mandatory_element_ids or [])
        self._locked_hidden: Set = set(locked_hidden_element_ids or [])
        # 必选与锁定互斥：锁定优先留在左侧
        self._mandatory -= self._locked_hidden
        self._result_visible_ids: Optional[List] = None

        id_to_row = {item["元件ID"]: item for item in all_elements if item.get("元件ID") is not None}
        visible_set = set(visible_element_ids or []) - self._locked_hidden
        all_ids = [item["元件ID"] for item in all_elements if item.get("元件ID") is not None]

        self.setLayout(QVBoxLayout())
        hint = QLabel(
            "左侧：不显示的元件；右侧：显示的元件。"
            "右侧灰色带*为固定显示不可移除；左侧灰色为当前不可选。"
        )
        hint.setWordWrap(True)
        self.layout().addWidget(hint)

        lists_row = QHBoxLayout()
        left_col = QVBoxLayout()
        left_col.addWidget(QLabel("不显示"))
        self.list_hidden = QListWidget()
        self.list_hidden.setSelectionMode(QListWidget.ExtendedSelection)
        left_col.addWidget(self.list_hidden)

        btn_col = QVBoxLayout()
        btn_col.addStretch()
        self.btn_add = QPushButton("添加 >>")
        self.btn_remove = QPushButton("<< 移除")
        btn_col.addWidget(self.btn_add)
        btn_col.addWidget(self.btn_remove)
        btn_col.addStretch()

        right_col = QVBoxLayout()
        right_col.addWidget(QLabel("显示"))
        self.list_visible = QListWidget()
        self.list_visible.setSelectionMode(QListWidget.ExtendedSelection)
        right_col.addWidget(self.list_visible)

        lists_row.addLayout(left_col, 1)
        lists_row.addLayout(btn_col)
        lists_row.addLayout(right_col, 1)
        self.layout().addLayout(lists_row)

        bbox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_btn = bbox.button(QDialogButtonBox.Ok)
        cancel_btn = bbox.button(QDialogButtonBox.Cancel)
        if ok_btn:
            ok_btn.setText("确定")
        if cancel_btn:
            cancel_btn.setText("取消")
        bbox.accepted.connect(self._on_accept)
        bbox.rejected.connect(self.reject)
        self.layout().addWidget(bbox)

        for eid in all_ids:
            row = id_to_row.get(eid, {})
            name = _element_display_name(row) or str(eid)
            locked = eid in self._locked_hidden
            mandatory = eid in self._mandatory
            if locked:
                target = self.list_hidden
            elif eid in visible_set or mandatory:
                target = self.list_visible
            else:
                target = self.list_hidden
            self._append_item(target, eid, name, mandatory=mandatory, locked_hidden=locked)

        self.btn_add.clicked.connect(self._move_to_visible)
        self.btn_remove.clicked.connect(self._move_to_hidden)

    def _append_item(
        self,
        list_widget: QListWidget,
        element_id,
        name: str,
        mandatory: bool = False,
        locked_hidden: bool = False,
    ):
        text = f"{name} *" if mandatory and list_widget is self.list_visible else name
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, element_id)
        if locked_hidden and list_widget is self.list_hidden:
            item.setForeground(QColor("#888888"))
            item.setToolTip(EXPANSION_JOINT_LOCK_TIP if name == EXPANSION_JOINT_NAME else "当前不可选择")
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
        elif mandatory and list_widget is self.list_visible:
            item.setForeground(QColor("#888888"))
            item.setToolTip("固定显示，不可移除")
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
        list_widget.addItem(item)

    def _move_to_visible(self):
        for item in self.list_hidden.selectedItems():
            eid = item.data(Qt.UserRole)
            if eid in self._locked_hidden:
                continue
            name = item.text().rstrip(" *").strip()
            row = self.list_hidden.row(item)
            self.list_hidden.takeItem(row)
            mandatory = eid in self._mandatory
            self._append_item(self.list_visible, eid, name, mandatory=mandatory)

    def _move_to_hidden(self):
        for item in self.list_visible.selectedItems():
            eid = item.data(Qt.UserRole)
            if eid in self._mandatory:
                continue
            name = item.text().rstrip(" *").strip()
            row = self.list_visible.row(item)
            self.list_visible.takeItem(row)
            locked = eid in self._locked_hidden
            self._append_item(self.list_hidden, eid, name, locked_hidden=locked)

    def _on_accept(self):
        ids = []
        seen = set()
        for i in range(self.list_visible.count()):
            eid = self.list_visible.item(i).data(Qt.UserRole)
            if eid is None or eid in self._locked_hidden or eid in seen:
                continue
            seen.add(eid)
            ids.append(eid)
        for eid in self._mandatory:
            if eid not in seen and eid not in self._locked_hidden:
                seen.add(eid)
                ids.append(eid)
        self._result_visible_ids = ids
        self.accept()

    def get_visible_element_ids(self) -> Optional[List]:
        return self._result_visible_ids


def show_structure_tree_dialog(
    parent,
    all_elements: List[dict],
    visible_element_ids: List,
    mandatory_element_ids: Optional[Set] = None,
    locked_hidden_element_ids: Optional[Set] = None,
    title: str = "结构树",
) -> Optional[List]:
    """
    弹出结构树；确认返回 visible 元件ID 列表，取消返回 None。
    locked_hidden_element_ids：强制留在左侧且不可添加到右侧。
    """
    dlg = StructureTreeDialog(
        parent,
        all_elements,
        visible_element_ids,
        mandatory_element_ids,
        locked_hidden_element_ids=locked_hidden_element_ids,
        title=title,
    )
    if dlg.exec_() != QDialog.Accepted:
        return None
    return dlg.get_visible_element_ids()


def clear_element_product_data(product_id: str, element_id) -> None:
    """
    隐藏元件：清空材料表业务字段并标记是否显示=否；
    删除该元件在「元件附加参数表」中的全部行（再选中时从模板回填）；
    合并表仍清空参数值（保留行结构，保留「元件名称」）。
    """
    conn = get_connection(**db_config_1)
    elem_name = ""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 元件名称 FROM 产品设计活动表_元件材料表
                WHERE 产品ID = %s AND 元件ID = %s
                LIMIT 1
                """,
                (product_id, element_id),
            )
            row = cur.fetchone()
            if row:
                elem_name = str((row.get("元件名称") if isinstance(row, dict) else row[0]) or "").strip()

            cur.execute(
                """
                UPDATE 产品设计活动表_元件材料表
                SET 材料类型 = '', 材料牌号 = '', 材料标准 = '',
                    供货状态 = '', 有无覆层 = '', 定义状态 = '未定义',
                    是否显示 = '否'
                WHERE 产品ID = %s AND 元件ID = %s
                """,
                (product_id, element_id),
            )
            # 未选元件：直接删除附加参数行（不再仅清空参数值）
            cur.execute(
                """
                DELETE FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件ID = %s
                """,
                (product_id, element_id),
            )
            # 合并表：其它参数清空，明确保留「元件名称」
            cur.execute(
                """
                UPDATE 产品设计活动表_元件附加参数合并表
                SET 参数值 = ''
                WHERE 产品ID = %s AND 元件ID = %s
                  AND 参数名称 <> '元件名称'
                """,
                (product_id, element_id),
            )
        conn.commit()
    except pymysql.MySQLError as e:
        _dbg_print(f"[结构树] 清空元件数据失败 product={product_id} element={element_id}: {e}")
    finally:
        conn.close()

    # 保温装置：清空后若元件名称为空，按管口附件表回填（不回填材料等模板参数）
    if elem_name == "保温装置":
        try:
            from modules.cailiaodingyi.controllers.datamanager import (
                sync_insulation_merged_component_names_from_attachment,
            )
            sync_insulation_merged_component_names_from_attachment(product_id, element_id)
        except Exception as e:
            _dbg_print(f"[结构树][保温装置] 清空后回填元件名称失败: {e}")


def _get_element_visibility_flag(product_id: str, element_id) -> Optional[str]:
    """返回 '是' / '否' / None（无行或空值）。"""
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 是否显示 FROM 产品设计活动表_元件材料表
                WHERE 产品ID = %s AND 元件ID = %s
                LIMIT 1
                """,
                (product_id, element_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            flag = str((row.get("是否显示") if isinstance(row, dict) else row[0]) or "").strip()
            if _is_yes(flag):
                return "是"
            if flag in ("否", "0", "false", "False", "N", "n"):
                return "否"
            return None
    except pymysql.MySQLError:
        return None
    finally:
        conn.close()


def _element_para_row_count(product_id: str, element_id) -> int:
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt FROM 产品设计活动表_元件附加参数表
                WHERE 产品ID = %s AND 元件ID = %s
                """,
                (product_id, element_id),
            )
            row = cur.fetchone()
            if not row:
                return 0
            return int(row.get("cnt") if isinstance(row, dict) else row[0] or 0)
    except pymysql.MySQLError:
        return 0
    finally:
        conn.close()


def _needs_element_para_restore(product_id: str, element_id) -> bool:
    """
    需要从模板回填附加参数：此前隐藏（是否显示=否），或附加参数表已无行。
    已显示且仍有参数行时不回填，避免覆盖用户已改数据。
    """
    if _get_element_visibility_flag(product_id, element_id) == "否":
        return True
    return _element_para_row_count(product_id, element_id) <= 0


def _resolve_product_template_name(product_id: str, all_elements: Optional[List[dict]] = None) -> str:
    for item in all_elements or []:
        name = (item.get("模板名称") or "").strip()
        if name:
            return name
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 模板名称 FROM 产品设计活动表_元件材料表
                WHERE 产品ID = %s
                LIMIT 1
                """,
                (product_id,),
            )
            row = cur.fetchone()
            if row:
                return str((row.get("模板名称") if isinstance(row, dict) else row[0]) or "").strip() or "None"
    except pymysql.MySQLError as e:
        _dbg_print(f"[结构树] 读取模板名称失败: {e}")
    finally:
        conn.close()
    return "None"


def _resolve_template_id_for_product(
    template_name: Optional[str],
    product_type: Optional[str] = None,
    product_form: Optional[str] = None,
    all_elements: Optional[List[dict]] = None,
):
    """
    解析材料库模板ID。
    空模板名「None」在多产品形式下会有多条，必须带类型+形式，避免 LIMIT 1 取错。
    """
    for item in all_elements or []:
        tid = item.get("模板ID")
        if tid is not None and str(tid).strip() != "":
            return tid

    tpl_name = (template_name or "").strip() or "None"
    ptype = (product_type or "").strip()
    pform = (product_form or "").strip()
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cur:
            if ptype and pform:
                cur.execute(
                    """
                    SELECT 模板ID FROM 元件材料模板表
                    WHERE 模板名称 = %s AND 所属类型 = %s AND 所属形式 = %s
                    LIMIT 1
                    """,
                    (tpl_name, ptype, pform),
                )
                row = cur.fetchone()
                if row:
                    return row.get("模板ID") if isinstance(row, dict) else row[0]
            from modules.cailiaodingyi.funcs.funcs_pdf_input import get_template_id_by_name
            return get_template_id_by_name(tpl_name)
    except Exception as e:
        _dbg_print(f"[结构树] 解析模板ID失败 template={tpl_name} type={ptype} form={pform}: {e}")
        return None
    finally:
        conn.close()


def restore_element_para_from_template(
    product_id: str,
    element_id,
    template_id=None,
    template_name: Optional[str] = None,
    fill_template_values: bool = False,
    element_name: Optional[str] = None,
    product_type: Optional[str] = None,
    product_form: Optional[str] = None,
) -> None:
    """
    再次选中（此前隐藏）时：从材料库模板读出该元件有哪些附加参数行并 INSERT。
    fill_template_values=False（默认，结构树手动再选）：参数值一律为空（仅「元件名称」写标准名）。
    fill_template_values=True（预定义勾选膨胀节等）：写入模板「参数数值」。
    先按元件ID匹配；匹配不到再按元件名称（空模板下 ID 不一致时仍能回填参数项）。
    写入活动库时始终使用当前产品的 element_id。
    """
    if not product_id or element_id is None:
        return

    from modules.cailiaodingyi.funcs.funcs_pdf_input import (
        query_template_element_para_data,
    )

    tpl_name = (template_name or "").strip() or "None"
    if template_id is None:
        template_id = _resolve_template_id_for_product(
            tpl_name, product_type=product_type, product_form=product_form
        )
    if template_id is None:
        _dbg_print(f"[结构树] 无法解析模板ID，跳过附加参数回填 product={product_id} element={element_id} template={tpl_name}")
        return

    template_rows = query_template_element_para_data(template_id) or []
    eid_str = str(element_id).strip()
    element_rows = [
        r for r in template_rows
        if str(r.get("元件ID") or "").strip() == eid_str
    ]
    # 空模板等场景：活动库元件ID 与材料库附加参数表元件ID 可能不一致，按名称回退
    if not element_rows:
        name = (element_name or "").strip()
        if not name and fill_template_values:
            name = EXPANSION_JOINT_NAME
        if name:
            element_rows = [
                r for r in template_rows
                if str(r.get("元件名称") or "").strip() == name
            ]
            if element_rows:
                _dbg_print(
                    f"[结构树] 附加参数按元件名称回退匹配 name={name} "
                    f"product={product_id} element={element_id} template_id={template_id} rows={len(element_rows)}"
                )
    if not element_rows:
        _dbg_print(
            f"[结构树] 模板无附加参数可回填 product={product_id} element={element_id} "
            f"template_id={template_id} name={element_name or ''}"
        )
        return

    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            # 预定义带模板值 / 名称回退重灌：清掉空骨架/残留，避免与 INSERT 冲突
            if fill_template_values:
                cur.execute(
                    """
                    DELETE FROM 产品设计活动表_元件附加参数表
                    WHERE 产品ID = %s AND 元件ID = %s
                    """,
                    (product_id, element_id),
                )
            for item in element_rows:
                param_name = str(item.get("参数名称", "") or "").strip()
                row_element_name = str(item.get("元件名称", "") or "").strip()
                if fill_template_values:
                    param_value = item.get("参数数值", "")
                    if param_value is None:
                        param_value = ""
                    if param_name == "元件名称" and not str(param_value).strip():
                        param_value = row_element_name
                else:
                    # 只恢复参数行结构；业务参数值清空。元件名称与旧清空逻辑一致予以保留。
                    if param_name == "元件名称":
                        param_value = row_element_name
                    else:
                        param_value = ""
                para_id = item.get("元件附加参数ID")
                if para_id is None:
                    continue
                cur.execute(
                    """
                    INSERT INTO 产品设计活动表_元件附加参数表
                    (元件附加参数ID, 产品ID, 元件ID, 元件名称, 参数名称, 参数值, 参数单位)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        para_id,
                        product_id,
                        element_id,
                        row_element_name or (element_name or ""),
                        item.get("参数名称"),
                        param_value,
                        item.get("参数单位"),
                    ),
                )
        conn.commit()
        mode = "模板值" if fill_template_values else "参数值清空"
        _dbg_print(
            f"[结构树] 已从模板回填附加参数({mode}) "
            f"product={product_id} element={element_id} rows={len(element_rows)}"
        )
    except pymysql.MySQLError as e:
        _dbg_print(f"[结构树] 从模板回填附加参数失败 product={product_id} element={element_id}: {e}")
    finally:
        conn.close()


def restore_element_material_from_template(
    product_id: str,
    element_id,
    template_name: Optional[str] = None,
    element_name: Optional[str] = None,
) -> bool:
    """从材料库「元件材料模板表」恢复左侧材料行（含定义状态），并置是否显示=是。"""
    if not product_id or element_id is None:
        return False
    tpl_name = (template_name or "").strip() or _resolve_product_template_name(product_id)
    name = (element_name or "").strip()
    if not name:
        name = EXPANSION_JOINT_NAME

    tpl = None
    conn = get_connection(**db_config_2)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 材料类型, 材料牌号, 材料标准, 供货状态, 有无覆层,
                       定义状态, 元件示意图, 所处部件
                FROM 元件材料模板表
                WHERE 模板名称 = %s AND 元件ID = %s
                LIMIT 1
                """,
                (tpl_name, element_id),
            )
            tpl = cur.fetchone()
            if not tpl:
                cur.execute(
                    """
                    SELECT 材料类型, 材料牌号, 材料标准, 供货状态, 有无覆层,
                           定义状态, 元件示意图, 所处部件
                    FROM 元件材料模板表
                    WHERE 模板名称 = %s AND 元件名称 = %s
                    LIMIT 1
                    """,
                    (tpl_name, name),
                )
                tpl = cur.fetchone()
    except pymysql.MySQLError as e:
        _dbg_print(f"[结构树] 查询元件材料模板失败: {e}")
        return False
    finally:
        conn.close()

    if not tpl:
        _dbg_print(f"[结构树] 模板无材料行 template={tpl_name} element={element_id} name={name}")
        return False

    def _g(key, idx):
        if isinstance(tpl, dict):
            return tpl.get(key) or ""
        return tpl[idx] if len(tpl) > idx else ""

    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE 产品设计活动表_元件材料表
                SET 材料类型 = %s, 材料牌号 = %s, 材料标准 = %s, 供货状态 = %s,
                    有无覆层 = %s, 定义状态 = %s,
                    元件示意图 = COALESCE(NULLIF(%s, ''), 元件示意图),
                    所处部件 = COALESCE(NULLIF(%s, ''), 所处部件),
                    是否显示 = '是'
                WHERE 产品ID = %s AND 元件ID = %s
                """,
                (
                    str(_g("材料类型", 0) or "").strip(),
                    str(_g("材料牌号", 1) or "").strip(),
                    str(_g("材料标准", 2) or "").strip(),
                    str(_g("供货状态", 3) or "").strip(),
                    str(_g("有无覆层", 4) or "").strip(),
                    str(_g("定义状态", 5) or "").strip() or "未定义",
                    str(_g("元件示意图", 6) or "").strip(),
                    str(_g("所处部件", 7) or "").strip(),
                    product_id,
                    element_id,
                ),
            )
            n = cur.rowcount or 0
        conn.commit()
        if n:
            _dbg_print(
                f"[结构树] 已从模板恢复材料字段 product={product_id} element={element_id} template={tpl_name}"
            )
        return n > 0
    except pymysql.MySQLError as e:
        _dbg_print(f"[结构树] 恢复材料字段失败 product={product_id} element={element_id}: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def restore_element_merged_para_from_template(
    product_id: str,
    element_id,
    template_id=None,
    template_name: Optional[str] = None,
    product_type: Optional[str] = None,
    product_form: Optional[str] = None,
    all_elements: Optional[List[dict]] = None,
) -> bool:
    """从材料库合并表模板重灌该元件合并表（带模板参数值）。"""
    if not product_id or element_id is None:
        return False
    from modules.cailiaodingyi.funcs.funcs_pdf_input import (
        query_template_element_merged_para_data,
    )

    tpl_name = (template_name or "").strip() or _resolve_product_template_name(product_id, all_elements)
    if template_id is None:
        template_id = _resolve_template_id_for_product(
            tpl_name,
            product_type=product_type,
            product_form=product_form,
            all_elements=all_elements,
        )
    if template_id is None:
        return False

    merged_rows = query_template_element_merged_para_data(template_id, element_id) or []
    if not merged_rows:
        # 按名称从附加参数表找到模板侧元件ID，再查合并表
        conn = get_connection(**db_config_2)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT 元件ID FROM 元件附加参数表
                    WHERE 模板ID = %s AND 元件名称 = %s
                    LIMIT 1
                    """,
                    (template_id, EXPANSION_JOINT_NAME),
                )
                row = cur.fetchone()
                tpl_eid = None
                if row:
                    tpl_eid = row.get("元件ID") if isinstance(row, dict) else row[0]
                if tpl_eid is not None and str(tpl_eid).strip() != str(element_id).strip():
                    merged_rows = query_template_element_merged_para_data(template_id, tpl_eid) or []
                    for item in merged_rows:
                        if isinstance(item, dict):
                            item["元件ID"] = element_id
        except Exception as e:
            _dbg_print(f"[结构树] 合并表按名称回退失败: {e}")
            merged_rows = []
        finally:
            conn.close()

    if not merged_rows:
        return False
    try:
        from modules.cailiaodingyi.controllers.datamanager import (
            insert_or_update_element_merged_para_data,
        )
        insert_or_update_element_merged_para_data(
            product_id, element_id, merged_rows, tpl_name
        )
        _dbg_print(
            f"[结构树] 已从模板重灌合并表 product={product_id} element={element_id} rows={len(merged_rows)}"
        )
        return True
    except Exception as e:
        _dbg_print(f"[结构树] 重灌合并表失败 product={product_id} element={element_id}: {e}")
        return False


def restore_expansion_joint_from_template(
    product_id: str,
    element_id,
    all_elements: Optional[List[dict]] = None,
    product_type: Optional[str] = None,
    product_form: Optional[str] = None,
) -> None:
    """
    预定义勾选膨胀节后：按当前产品模板完整回填材料、附加参数值、合并表。
    """
    if product_type is None or product_form is None:
        try:
            from modules.cailiaodingyi.funcs.funcs_pdf_input import load_design_product_data
            product_type, product_form = load_design_product_data(product_id)
        except Exception as e:
            _dbg_print(f"[结构树][膨胀节] 读取产品类型/形式失败: {e}")

    template_name = _resolve_product_template_name(product_id, all_elements)
    template_id = _resolve_template_id_for_product(
        template_name,
        product_type=product_type,
        product_form=product_form,
        all_elements=all_elements,
    )
    _dbg_print(
        f"[结构树][膨胀节] 回填模板 template={template_name!r} template_id={template_id} "
        f"type={product_type} form={product_form} element={element_id}"
    )

    restore_element_material_from_template(
        product_id, element_id, template_name=template_name, element_name=EXPANSION_JOINT_NAME
    )
    restore_element_para_from_template(
        product_id,
        element_id,
        template_id=template_id,
        template_name=template_name,
        fill_template_values=True,
        element_name=EXPANSION_JOINT_NAME,
        product_type=product_type,
        product_form=product_form,
    )
    restore_element_merged_para_from_template(
        product_id,
        element_id,
        template_id=template_id,
        template_name=template_name,
        product_type=product_type,
        product_form=product_form,
        all_elements=all_elements,
    )
    ensure_element_name_param(product_id, element_id, EXPANSION_JOINT_NAME)


def _expansion_joint_left_materials_blank(product_id: str, element_id) -> bool:
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 材料类型, 材料牌号, 材料标准, 供货状态
                FROM 产品设计活动表_元件材料表
                WHERE 产品ID = %s AND 元件ID = %s
                LIMIT 1
                """,
                (product_id, element_id),
            )
            row = cur.fetchone()
            if not row:
                return True
            if isinstance(row, dict):
                vals = [row.get("材料类型"), row.get("材料牌号"), row.get("材料标准"), row.get("供货状态")]
            else:
                vals = list(row[:4])
            return not any(str(v or "").strip() for v in vals)
    except pymysql.MySQLError:
        return True
    finally:
        conn.close()


def ensure_element_name_param(product_id: str, element_id, element_name: str) -> None:
    """显示元件时，若附加参数中「元件名称」为空则写回标准名。"""
    name = (element_name or "").strip()
    if not name:
        return
    # 保温装置合并表「元件名称」是子零件多选 JSON，不能写成父级名
    skip_merged = name == "保温装置"
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            tables = ["产品设计活动表_元件附加参数表"]
            if not skip_merged:
                tables.append("产品设计活动表_元件附加参数合并表")
            for table in tables:
                cur.execute(
                    f"""
                    UPDATE {table}
                    SET 参数值 = %s
                    WHERE 产品ID = %s AND 元件ID = %s
                      AND 参数名称 = '元件名称'
                      AND (参数值 IS NULL OR TRIM(参数值) = '')
                    """,
                    (name, product_id, element_id),
                )
        conn.commit()
    except pymysql.MySQLError as e:
        _dbg_print(f"[结构树] 恢复元件名称参数失败 product={product_id} element={element_id}: {e}")
    finally:
        conn.close()


def set_element_visible(product_id: str, element_id, visible: bool) -> None:
    flag = "是" if visible else "否"
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE 产品设计活动表_元件材料表
                SET 是否显示 = %s
                WHERE 产品ID = %s AND 元件ID = %s
                """,
                (flag, product_id, element_id),
            )
        conn.commit()
    except pymysql.MySQLError as e:
        _dbg_print(f"[结构树] 更新是否显示失败: {e}")
    finally:
        conn.close()


def fetch_hidden_element_names(product_id: str) -> Set[str]:
    """读取切换模板前用户设为不显示的元件名称（按元件名称匹配，跨模板保留）。"""
    if not product_id:
        return set()
    conn = get_connection(**db_config_1)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 元件名称
                FROM 产品设计活动表_元件材料表
                WHERE 产品ID = %s AND 是否显示 = '否'
                """,
                (product_id,),
            )
            rows = cur.fetchall() or []
            return {
                (r.get("元件名称") or "").strip()
                for r in rows
                if (r.get("元件名称") or "").strip()
            }
    except pymysql.MySQLError as e:
        _dbg_print(f"[结构树] 读取隐藏元件失败: {e}")
        return set()
    finally:
        conn.close()


def restore_structure_tree_visibility_after_template_switch(
    product_id: str,
    template_elements: List[dict],
    hidden_element_names: Set[str],
) -> None:
    """
    切换模板后：此前不显示的元件保持隐藏，并清空其模板数据（不做模板替换）。
    新模板中同名的元件仍按 hidden_element_names 处理。
    """
    if not product_id or not template_elements:
        return
    hidden = hidden_element_names or set()
    visible_ids: List = []
    all_for_apply: List[dict] = []
    for item in template_elements:
        eid = item.get("元件ID")
        if eid is None:
            continue
        name = _element_display_name(item)
        row = dict(item)
        if name:
            row.setdefault("零件名称", name)
        all_for_apply.append(row)
        if name not in hidden:
            visible_ids.append(eid)
    if hidden:
        apply_structure_tree_selection(product_id, all_for_apply, visible_ids)
        _dbg_print(f"[结构树] 切换模板后保留隐藏元件: {sorted(hidden)}")


def apply_structure_tree_selection(
    product_id: str,
    all_elements: List[dict],
    visible_element_ids: List,
) -> None:
    """
    按用户选择写是否显示：
    - 隐藏：清空材料表字段 + 删除元件附加参数表行 + 清空合并表参数值；
    - 显示：标记是否显示=是；若此前隐藏或附加参数已无行，则从模板恢复参数行结构（参数值清空，仅保留元件名称）。
    """
    visible_set = set(visible_element_ids or [])
    template_name = _resolve_product_template_name(product_id, all_elements)
    template_id = None
    try:
        from modules.cailiaodingyi.funcs.funcs_pdf_input import get_template_id_by_name
        template_id = get_template_id_by_name(template_name)
    except Exception as e:
        _dbg_print(f"[结构树] 解析模板ID失败 template={template_name}: {e}")

    for item in all_elements or []:
        eid = item.get("元件ID")
        if eid is None:
            continue
        if eid in visible_set:
            # 必须在改「是否显示」之前判断，才能识别「再次选中」
            need_restore = _needs_element_para_restore(product_id, eid)
            item_tpl_id = item.get("模板ID")
            set_element_visible(product_id, eid, True)
            if need_restore:
                restore_element_para_from_template(
                    product_id,
                    eid,
                    template_id=item_tpl_id if item_tpl_id is not None else template_id,
                    template_name=(item.get("模板名称") or template_name),
                )
            ensure_element_name_param(product_id, eid, _element_display_name(item))
        else:
            clear_element_product_data(product_id, eid)
    # 保温装置：无附件触发时不应残留合并表结构（与管口附件一致）
    try:
        from modules.cailiaodingyi.controllers.datamanager import (
            reconcile_insulation_merged_para_with_attachment,
        )
        reconcile_insulation_merged_para_with_attachment(product_id)
    except Exception as e:
        _dbg_print(f"[结构树][保温装置] 合并表对齐失败: {e}")
