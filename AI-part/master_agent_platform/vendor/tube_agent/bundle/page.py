"""布管页面：左侧参数表 + 中间布管图形 + 右侧管孔数量分布表 + 底部“保留”。

图形、表格、参数三者共用同一份状态：
    master_centers  正式程序布管接口算出的全部管孔
    removed         被删除/被拉杆等元件占用的管孔
    components      元件（拉杆、旁路挡板、滑道……）
任何一处变化都会刷新图形与右侧数量表，因此“整行选中 / 数量统计 / 元件显示”
始终一致，不存在只做样式的静态图。
"""
from __future__ import annotations

import math
from copy import deepcopy

from PyQt5.QtCore import QEvent, QLocale, QPointF, QRectF, QSize, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QDoubleValidator,
    QFont,
    QFontMetrics,
    QIntValidator,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import engine, geometry, impingement
from .hole_table import HoleDistributionTable
from .items import (
    BLOCK_TUBE_COLOR,
    BYPASS_COLOR,
    CENTER_BAFFLE_COLOR,
    IMPINGE_COLOR,
    IMPINGE_PEN_COLOR,
    ROD_COLOR,
    SIDE_ROD_COLOR,
    SLIDE_COLOR,
    TUBE_PEN_COLOR,
    BlockTubeItem,
    ComponentRectItem,
    FoldedPlateItem,
    GhostTubeItem,
    RadialHoleItem,
    RodItem,
    ScrewRingItem,
    TubeItem,
)
from .params import (
    DERIVED_FIELDS,
    PARAM_ORDER,
    TIE_ROD_DIAMETERS,
    canonical_tube_arrangement,
    layout_hidden_params,
    normalize_param_value,
    normalize_tube_arrangement,
    spec_for,
    tube_pattern_image,
)
from modules.buguan.buguan_ziyong.tube_pass.adapter import (
    is_local_tube_pass_cat,
    run_local_tube_layout,
)
from .view import LayoutGraphicsView
from .widgets import (
    FlowBar,
    ParamComboBox,
    ParamField,
    TubePassFormComboBox,
    apply_param_combo_style,
    ask_component_params,
    element_icon,
    param_combo_stylesheet,
)

STATIC_DIR = __import__("pathlib").Path(__file__).resolve().parent / "static"
_ASSETS_DIR = __import__("pathlib").Path(__file__).resolve().parents[1] / "assets"

# ---------------------------------------------------------------- 参数表（照搬正式程序）
# 行高 40、10pt、方角灰边；下拉框样式在 widgets.param_combo_stylesheet（同款）。
PARAM_ROW_HEIGHT = 40
# 管程分程形式行：正式程序也是统一 40 行高，示意图在格子里等比缩放
PATTERN_ROW_HEIGHT = PARAM_ROW_HEIGHT
PATTERN_COLUMN_WIDTH = 220

PARAM_TABLE_STYLE = f"""
QTableWidget {{
    gridline-color: #d4d4d4;
    background-color: #ffffff;
    border: 1px solid #bdbdbd;
    font-size: 10pt;
    selection-background-color: #e3f2fd;
    selection-color: #212121;
}}
QTableWidget::item {{
    padding: 4px 6px;
    border-bottom: 1px solid #eeeeee;
}}
QTableWidget::item:alternate {{
    background-color: #fafafa;
}}
QTableWidget::item:selected {{
    background-color: #e3f2fd;
    color: #212121;
}}
QHeaderView::section {{
    background-color: #f2f2f2;
    color: #222222;
    padding: 6px 4px;
    border: none;
    border-bottom: 1px solid #bdbdbd;
    border-right: 1px solid #e0e0e0;
    font-weight: 700;
    font-size: 10pt;
}}
QTableWidget QWidget {{
    background-color: transparent;
}}
QTableWidget QLineEdit {{
    border: 1px solid #dcdfe6;
    border-radius: 4px;
    padding: 2px 10px;
    background-color: #ffffff;
    color: #303133;
    font-size: 10pt;
    min-height: 24px;
}}
"""

# 元件工具条：浅底一条，按钮是白色胶囊；删除单独靠右、红色描边，避免误点
TOOLBAR_STYLE = """
QFrame#layoutToolbar{background:#f7f9fd;border:1px solid #e6ecf5;border-radius:8px;}
QPushButton#toolChip{background:#ffffff;border:1px solid #e2e8f2;border-radius:6px;
    padding:0 9px;font-size:9pt;color:#31405c;}
QPushButton#toolChip:hover{background:#eef4ff;border-color:#b8d0f5;color:#1d4ed8;}
QPushButton#toolChip:pressed{background:#dfeafe;border-color:#9dc0f2;}
QPushButton#toolChipDanger{background:#ffffff;border:1px solid #f0d2cd;border-radius:6px;
    padding:0 12px;font-size:9pt;color:#c0392b;}
QPushButton#toolChipDanger:hover{background:#fdf2f0;border-color:#e3aca4;}
QPushButton#toolChipDanger:pressed{background:#fbe4e0;}
"""

# 方案卡上的参数名简称（完整参数名太长，卡片要短）
_PARAM_SHORT = {
    "拉杆形式": "形式", "拉杆直径": "直径",
    "中间挡管安装方式": "安装",
    "旁路挡板厚度": "厚度", "旁路挡板宽度": "宽度",
    "中间挡板厚度": "厚度", "中间挡板宽度": "宽度", "中间挡板安装方式": "安装",
    "防冲板形式": "形式", "放置位置": "位置", "防冲板厚度": "厚度",
    "防冲板折边角度": "折边角", "防冲板宽度": "宽度", "防冲板方位角": "方位角",
    "至圆筒内壁距离": "距内壁",
    "吊环螺钉规格": "规格", "吊环螺钉数量": "数量",
    "吊环螺钉孔中心距": "孔中心距", "吊环螺钉起始方位角": "起始角",
    "滑道定位": "定位", "滑道形式": "形式", "滑道数量": "数量",
    "滑道方位角": "方位角", "圆钢规格": "圆钢", "滑道高度": "高度",
    "滑道厚度": "厚度", "滑道与竖直中心线夹角": "夹角",
    "滑道切边长度": "切边长", "滑道切边高度": "切边高",
    "折流/支持板外径": "外径", "折流/支持板间距": "间距",
    "折流板类型": "类型", "折流板切口方向": "切口方向",
}


def _param_unit(name: str) -> str:
    if "角" in name or "方位" in name:
        return "°"
    if any(key in name for key in ("直径", "厚度", "宽度", "高度", "长度", "内壁", "中心距", "外径", "间距")):
        return " mm"
    return ""


def _is_choice_param(name: str) -> bool:
    """下拉/选项类参数（形式、位置、安装方式…）；其余按数值处理。"""
    return any(key in name for key in ("形式", "位置", "安装方式", "方向", "类型", "规格", "定位"))


def baffle_chord_specs(parameters: dict, radius: float) -> list[dict]:
    """按正式程序 ``draw_baffle_plates`` 计算折流板切口弦线。"""
    if radius <= 0:
        return []

    def value(name: str, default=""):
        row = (parameters or {}).get(name, default)
        return row.get("value", default) if isinstance(row, dict) else row

    def number(name: str, default=None):
        try:
            return float(value(name, default))
        except (TypeError, ValueError):
            return default

    baffle_type = str(value("折流板类型", "") or "").strip()
    if baffle_type == "支持板":
        return []
    direction = str(value("折流板切口方向", "") or "").strip()
    orientation = "horizontal" if direction in {"水平上下", "水平"} else "vertical"
    specs: list[dict] = []

    def append(level: float, color: tuple[int, int, int], tag: str = ""):
        if level is None or abs(level) > radius:
            return
        specs.append({
            "orientation": orientation,
            "level": float(level),
            "half_length": math.sqrt(max(radius * radius - level * level, 0.0)),
            "color": color,
            "tag": tag,
            "width": 5 if tag else 3,
        })

    if baffle_type in {"双弓型", "双弓形"}:
        a = number("A型板切口与中心线间距a")
        b = number("B型板切口与中心线间距b")
        if a is None or b is None:
            return []
        append(a, (150, 200, 255), "A")
        append(-a, (150, 200, 255), "A")
        append(b, (255, 150, 150), "B")
        append(-b, (255, 150, 150), "B")
        return specs

    cut_rate = number("折流板要求切口率")
    if cut_rate is None or not 0 <= cut_rate <= 50:
        return []
    # 源程序：Dis × (0.5 - cut_rate/100)，其中 Dis/2 即绘图圆半径。
    distance = radius * (1.0 - 2.0 * cut_rate / 100.0)
    append(distance, (204, 204, 0))
    append(-distance, (204, 204, 0))
    return specs


COMPONENT_KIND_TO_TYPE = {
    "rod": 0,
    "free_rod": 1,
    "block_tube": 2,
    "bypass": 3,
    "center_baffle": 4,
    "impingement": 5,
    "impingement_folded": 6,
    "impingement_welded": 6,
    "slide": 8,
}
COMPONENT_LABEL = {
    "rod": "拉杆",
    "free_rod": "自由拉杆",
    "block_tube": "中间挡管",
    "bypass": "旁路挡板",
    "center_baffle": "中间挡板",
    "impingement": "平板形防冲板",
    "impingement_folded": "圆弧形防冲板",
    "impingement_welded": "焊接式防冲板",
    "slide": "滑道",
    "screw_ring": "吊环螺钉",
    "radial_hole": "径向开孔",
}


def _describe_rows(rows: list[int]) -> str:
    """把选中的行下标写成人话：第 3 行 / 第 3、5 行 / 第 3–7 行 / 第 3 行等 6 行。"""
    numbers = sorted({row + 1 for row in rows})
    if not numbers:
        return "第 0 行"
    if len(numbers) == 1:
        return f"第 {numbers[0]} 行"
    if numbers == list(range(numbers[0], numbers[-1] + 1)):
        return f"第 {numbers[0]}–{numbers[-1]} 行"
    if len(numbers) <= 4:
        return "第 " + "、".join(str(n) for n in numbers) + " 行"
    return f"第 {numbers[0]} 行等 {len(numbers)} 行"


class ParamTableWidget(QTableWidget):
    """左侧参数表：单击参数值格就进编辑（正式程序 My_Piping.py eventFilter 的 Excel 手感）。

    正式程序是在 eventFilter 里判断 viewport 的 MouseButtonRelease；这里放在表格自己的
    mouseReleaseEvent 里，事件类型天然是鼠标事件，不会对别的事件误取 pos()。
    下拉/示意图格有 cellWidget，点击自然落到控件上，这里只管纯文本格。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 表格自己的尺寸一变就重排列宽（页面 resizeEvent 那一刻视口宽度还是旧的）
        self.reflow = lambda: None

    def resizeEvent(self, event):  # noqa: N802 - Qt API
        super().resizeEvent(event)
        QTimer.singleShot(0, self.reflow)

    def _start_value_edit(self, index) -> None:
        """参数值列进入编辑：只认纯文本格（下拉格有自己的控件）。"""
        if not index.isValid() or index.column() != 2:
            return
        if self.cellWidget(index.row(), 2) is not None:
            return
        item = self.item(index.row(), 2)
        if item is None or not (item.flags() & Qt.ItemIsEditable):
            return
        if self.state() != QAbstractItemView.EditingState:
            QTimer.singleShot(0, lambda i=index: self._deferred_edit(i))

    def _deferred_edit(self, index) -> None:
        """延时进编辑；真到这一刻已经在编辑就不再动（双击会连发好几次，重复 edit 会关掉编辑框）。"""
        if self.state() == QAbstractItemView.EditingState:
            return
        self.edit(index)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt API
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            self._start_value_edit(self.indexAt(event.pos()))

    def mouseDoubleClickEvent(self, event):  # noqa: N802 - Qt API
        super().mouseDoubleClickEvent(event)
        if event.button() == Qt.LeftButton:
            self._start_value_edit(self.indexAt(event.pos()))


class TubeLayoutPage(QWidget):
    keep_requested = pyqtSignal()
    state_changed = pyqtSignal(dict)
    status_message = pyqtSignal(str)
    selected_count_changed = pyqtSignal(int)
    pane_fullscreen_requested = pyqtSignal(bool)
    basis_requested = pyqtSignal(str)  # 用户点「依据」：把布置依据文字交给上层弹窗展示

    def __init__(self, parameters: dict, product_type: str, defaults: dict | None = None,
                 center_distance_rows: list[list[str]] | None = None, sheet_form: dict | None = None,
                 parent=None):
        super().__init__(parent)
        self.product_type = (product_type or "AEU").strip().upper()
        self.defaults = defaults or {}
        self.center_distance_rows = center_distance_rows or []
        self.sheet_form = sheet_form or {}
        self.parameters: dict[str, dict] = {}
        for name in PARAM_ORDER:
            row = (parameters or {}).get(name) or {}
            self.parameters[name] = {
                "value": row.get("value", ""),
                "unit": row.get("unit", ""),
                "source": row.get("source", "程序默认值"),
                "editable": True,
            }
        self.result: engine.LayoutResult | None = None
        self.removed: set[tuple[float, float]] = set()
        # 最近一次“删换热管”方案删掉的管孔：用户随后说“恢复刚才删掉的管”时只还原这一批
        self._last_hole_delete: list[tuple[float, float]] = []
        # 模型给的行列号里查不到/状态不对的那些，如实攒在这里给卡片显示
        self._ref_problems: list[str] = []
        self.components: list[dict] = []
        self.selected: set[tuple[float, float]] = set()
        self.selected_components: set[int] = set()
        # 对称分布（正式程序 My_Piping.symmetric_checkbox，默认勾选）：
        # 勾选 = 4 象限镜像；不勾 = 只按管程程数做单轴镜像（2 管程左右、4/6 管程上下）
        self._symmetry = True
        self.issues: list[dict] = []
        self._undo: list[dict] = []
        self._tube_items: dict[tuple[float, float], TubeItem] = {}
        self._ghost_items: dict[tuple[float, float], GhostTubeItem] = {}
        self._component_items: dict[int, object] = {}
        self._rows_pos: list[list[tuple[float, float]]] = []
        self._rows_neg: list[list[tuple[float, float]]] = []
        self._cols_right: list[list[tuple[float, float]]] = []
        self._cols_left: list[list[tuple[float, float]]] = []
        self._editors: dict[str, QWidget] = {}
        self._suppress_commit = False
        self.graphics_expanded = False
        # 离屏自动验收时置 True：不弹模态框，改为在操作栏提示
        self.headless = False
        self._build_ui()
        self.rebuild_parameter_table()
        # 参数表是 1200 系列的存量数据，而公称直径 DN 常来自上游设计数据表（例如 400）。
        # 开算之前先按 DN 把 Dis/Dit/折流板外径/DL 校一遍，否则图上会出现比 DN 还大的
        # “内圆”，管子缩在中间一小块，DLL 也按错误的壳体内径布管。
        self._linkage_fixes: list[str] = []
        self._apply_linkage("公称直径 DN")
        self.recompute(first=True)
        # GB/T 151 自动布置方案：文件提取到「目标换热管数」时，切到布管页即已布好。
        # 只在首次创建页面时应用一次；用户手动点「布管」会清掉自动痕迹并复位，
        # 之后可从聊天指令「重新生成布置方案」再触发。
        self._auto_plan_applied = False
        self._auto_plan_basis = ""
        self._auto_plan_summary: dict = {}
        self.auto_apply_plan()

    # ------------------------------------------------------- 自动布置方案（GB/T 151）
    def _target_tubes(self) -> int:
        """目标换热管数：内部参数，来自文件提取的「管子数/台」。"""
        row = self.parameters.get("目标换热管数") or {}
        value = row.get("value") if isinstance(row, dict) else row
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return 0

    def _symmetric_trim_to_target(self, target: int) -> int:
        """把换热管数对称地调到 target，返回实际增删的根数。

        规则（GB/T 151 + 正式程序 judge_linkage_x/y + 用户约定俗成的设计规则）：
        · 2 管程：镜像轴 = 水平中心线，管孔按 (x, -y) 成对；
        · 4/6 管程：镜像轴 = 竖直中心线，管孔按 (-x, y) 成对；
        · 删管：**首先删 0°/180° 方向（竖直中心线、x≈0）的管孔**，这是设计惯例；
          同一方向内再按到圆心距离从大到小（先删外圈），成对删；
        · 补管：按距离从小到大成对补（先补最内圈）；
        · 轴线上（y≈0 或 x≈0）自己镜像自己的管孔，作为单点最后处理，
          保证奇偶差额也能精确到位。

        图上角度约定（见正式程序布管图）：0°=正上、90°=正右、180°=正下、270°=正左。
        所以"0°/180° 的管"是位于竖直中心线附近的管孔，即 |x| 小者。
        """
        if self.result is None:
            return 0
        passes = self._param_text("管程程数")
        axis = "y" if passes == "2" else "x" if passes in {"4", "6"} else None
        master = [tuple(c) for c in self.result.master_centers]
        alive = {(round(x, 6), round(y, 6)) for x, y in self.current_centers()}
        occupied = {
            (round(float(c["center"][0]), 6), round(float(c["center"][1]), 6))
            for c in self.components if c.get("center")
        }

        def mirror(c):
            x, y = c
            return (x, -y) if axis == "y" else (-x, y)

        # 按镜像把管孔配成若干"组"：{代表: [该组当前在/不在的点]}
        key_of = {}
        for c in master:
            k = (round(c[0], 6), round(c[1], 6))
            mk = (round(mirror(c)[0], 6), round(mirror(c)[1], 6))
            # 用有序对做组键，保证 c 与其镜像落到同一组
            key_of[k] = min(k, mk)
        groups: dict[tuple, list[tuple]] = {}
        for c in master:
            k = (round(c[0], 6), round(c[1], 6))
            groups.setdefault(key_of[k], []).append(c)

        def radius(c):
            return math.hypot(c[0], c[1])

        current = len(alive)
        delta = target - current
        if delta == 0:
            return 0

        # 用户约定俗成的设计规则：凑数删管**首先删 0°/180° 方向**（竖直中心线
        # x≈0）的换热管，同一方向内再由外向内。组内的镜像点共享 |x|，所以按
        # (|x| 小优先, 半径大优先) 排序即可；补管走反序。
        def group_axis_distance(g):
            return min(abs(c[0]) for c in g)

        ordered = sorted(
            groups.values(),
            key=lambda g: (group_axis_distance(g), -max(radius(c) for c in g)),
        )

        changed = 0
        if delta < 0:  # 删管：先 0°/180°，同列由外向内，成对删
            need = -delta
            for g in ordered:
                if need <= 0:
                    break
                for c in sorted(g, key=lambda p: (abs(p[0]), -radius(p))):
                    if need <= 0:
                        break
                    k = (round(c[0], 6), round(c[1], 6))
                    if k in alive and k not in occupied:
                        self.removed.add(c)
                        alive.discard(k)
                        need -= 1
                        changed += 1
        else:  # 补管：反序成对恢复（远离 0°/180° 的列优先、同列由内向外）
            need = delta
            for g in reversed(ordered):
                if need <= 0:
                    break
                for c in sorted(g, key=lambda p: (abs(p[0]), radius(p))):
                    if need <= 0:
                        break
                    k = (round(c[0], 6), round(c[1], 6))
                    if k not in alive and k in self.removed and k not in occupied:
                        for existing in [p for p in self.removed
                                         if (round(p[0], 6), round(p[1], 6)) == k]:
                            self.removed.discard(existing)
                        alive.add(k)
                        need -= 1
                        changed += 1

        if changed:
            self.rebuild_scene()
            self.refresh_hole_table()
        return changed

    def auto_apply_plan(self, force: bool = False) -> dict:
        """按 GB/T 151 规则自动布置元件 + 删管到目标数，静默落地（不弹确认框）。

        触发：页面创建完成（切到布管页图已布好）；或聊天指令强制重生成。
        幂等：默认已应用过就不再重复；force=True 时先清旧痕迹再重来。
        """
        if self.result is None:
            return {"ok": False, "message": "当前还没有布管结果，无法生成方案"}
        target = self._target_tubes()
        if not target:
            return {"ok": False, "message": "未提取到目标换热管数，跳过自动布置"}
        if self._auto_plan_applied and not force:
            return {"ok": True, "message": "已应用过自动方案，跳过"}
        if force:
            # 重新生成：先按当前参数恢复满布管孔、清掉上一次自动布置的元件，
            # 否则会在已删/已占的孔上二次删管，换热管数越算越少。
            self.recompute(reason="重新生成布置方案")
            target = self._target_tubes()

        from .placement import parse_placements, parse_hole_ops
        from .rule_plan import build_plan

        total = len(self.result.master_centers)
        plan = build_plan(self.parameters, self.product_type, total, target)
        items, bad = parse_placements(plan["placements"])
        # 注意：plan["hole_ops"] 是按"元件还没删管"预估的删管数，**不能直接落地**。
        # 用户 2026-11-22 明确要求：先布置元件（防冲板/滑道/拉杆的干涉删管自然发生），
        # 再看实际管孔数是否已经等于目标，没对齐才从外缘补删。旧版反过来（先删管再布
        # 元件），元件全落在已删的孔上，防冲板/滑道一根干涉管都删不到，这是错的。
        _, bad_ops = parse_hole_ops(plan["hole_ops"])

        # 第一步：先布置全部元件。防冲板/滑道按几何删掉干涉管，拉杆/挡管占孔。
        place_res = self.apply_placement_plan(items) if items else {"ok": True}

        self._auto_plan_basis = "\n".join(plan["basis"])
        self._auto_plan_summary = dict(plan["summary"])

        # 第二步：元件落地后再数实际管孔，差额用对称删管修正到目标。
        # 本版不布置防冲板/滑道，所以不会有"元件删管→为凑数又补回"的反复；
        # 只有拉杆/挡管占孔 + 目标差额，一次对称删管到位。
        actual = len(self.current_centers())
        if actual != target:
            # 对称删管：按用户约定俗成的设计规则，首先删 0°/180° 方向（竖直中心线
            # x≈0）的换热管，同列再由外向内，按管程镜像成对删；不用 region=outline
            # 的"每行最左最右"（那种会把中间行掏空、上下不对称）。
            changed = self._symmetric_trim_to_target(target)
            self._auto_plan_basis += (
                f"\n【数量校正】元件落地后 {actual} 根，目标 {target} 根，"
                f"{'补' if target > actual else '删'} {abs(target - actual)} 根"
                f"（实际调整 {changed} 根）：按管程镜像对称，"
                + (
                    "从远离 0°/180° 的列由内向外逐对补回"
                    if target > actual else
                    "首先删除 0°/180°（竖直中心线）附近的管孔、同列由外向内逐对删除"
                )
                + "，保持上下/左右对称。"
            )

        final = len(self.current_centers())
        self._auto_plan_applied = True
        self._auto_plan_summary["actual_tubes"] = final
        ok = final == target
        msg = (
            f"已按 GB/T 151 自动布置：元件 {len(items)} 类、"
            f"换热管 {final}/{target} 根" + ("" if ok else "（数量不符，请查看依据）")
        )
        self.status_message.emit(msg)
        return {"ok": ok, "message": msg, "items": len(items), "actual": final,
                "target": target, "rejected": bad + bad_ops}

    def _on_manual_recompute(self) -> None:
        """用户手动点「布管」：清掉自动方案痕迹，按当前参数重新布管。"""
        self._auto_plan_applied = False
        self._auto_plan_basis = ""
        self.recompute(reason="用户点击布管")

    def _emit_basis(self) -> None:
        text = self._auto_plan_basis
        if not text:
            text = (
                "当前尚未生成自动布置方案。\n"
                "若上游文件提供了「管子数/台」，切到布管页会自动按 GB/T 151-2026 "
                "布置元件并把换热管数凑到该值；也可在聊天里说「重新生成布置方案」。"
            )
        self.basis_requested.emit(text)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        body = QHBoxLayout()
        self.body_layout = body
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)

        # 元件工具条：整页顶部独占一行，避免挤占中间图形的宽度。
        # 图标改为矢量绘制（颜色对应图上的元件），按钮按内容宽度左对齐排列、
        # 装不下自动折行——旧版把按钮塞进等分列的网格里拉满整行，既空又难认。
        toolbar_frame = QFrame()
        self.toolbar_frame = toolbar_frame
        toolbar_frame.setObjectName("layoutToolbar")
        toolbar_frame.setStyleSheet(TOOLBAR_STYLE)
        toolbar_row = QHBoxLayout(toolbar_frame)
        toolbar_row.setContentsMargins(6, 4, 6, 4)
        toolbar_row.setSpacing(6)
        caption = QLabel("元件")
        caption.setStyleSheet("color:#8b95a7;font-size:8.5pt;padding-right:2px;")
        toolbar_row.addWidget(caption, 0, Qt.AlignVCenter)
        tools = FlowBar(toolbar_frame, 4, 4)
        tool_specs = [
            ("换热管", "tube", TUBE_PEN_COLOR, "恢复被删除的换热管，并重新布管", self.restore_tubes),
            ("拉杆", "rod", ROD_COLOR, "在选中的管孔位置布置拉杆", lambda: self.place_rod(free=False)),
            ("自由拉杆", "side_rod", SIDE_ROD_COLOR, "在选中的管孔位置布置自由拉杆", lambda: self.place_rod(free=True)),
            ("中间挡管", "block_tube", BLOCK_TUBE_COLOR, "布置中间挡管", self.place_block_tube),
            ("旁路挡板", "bypass", BYPASS_COLOR, "布置旁路挡板", lambda: self.place_plate("bypass")),
            ("滑道", "slide", SLIDE_COLOR, "布置滑道", self.place_slide),
            ("吊环螺钉", "screw_ring", QColor(0, 116, 160), "布置吊环螺钉", self.place_screw_ring),
            ("中间挡板", "center_baffle", CENTER_BAFFLE_COLOR, "布置中间挡板", lambda: self.place_plate("center_baffle")),
            ("防冲板", "impingement", IMPINGE_PEN_COLOR, "布置防冲板", self.place_impingement),
            ("折流板", "baffle", QColor(170, 132, 20), "布置折流板", self.place_baffle),
            ("径向开孔", "radial_hole", QColor(0, 110, 190), "在管板上径向开孔", self.place_radial_hole),
        ]
        for text, glyph, color, tip, slot in tool_specs:
            button = QPushButton(text)
            button.setObjectName("toolChip")
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(tip)
            button.setIcon(element_icon(glyph, QColor(color)))
            button.setIconSize(QSize(16, 16))
            button.setFixedHeight(26)
            button.setMinimumWidth(78)
            button.clicked.connect(slot)
            tools.add_widget(button)
        toolbar_row.addWidget(tools, 1)
        delete_button = QPushButton("删除")
        delete_button.setObjectName("toolChipDanger")
        delete_button.setCursor(Qt.PointingHandCursor)
        delete_button.setToolTip("删除选中的管孔或元件（也可按 Delete 键）")
        delete_button.setIcon(element_icon("delete", QColor("#c0392b")))
        delete_button.setIconSize(QSize(16, 16))
        delete_button.setFixedHeight(26)
        delete_button.setMinimumWidth(74)
        delete_button.clicked.connect(self.delete_selected)
        toolbar_row.addWidget(delete_button, 0, Qt.AlignVCenter)
        root.addWidget(toolbar_frame)

        # 左：参数表
        left = QFrame()
        self.left_frame = left
        left.setObjectName("layoutParamFrame")
        # 三栏按 3:5:2 分宽度：左侧只要放得下“参数名 + 数值 + 单位”，
        # 下限压到 330 才能在 1100 宽的编辑器里不出现整页横向滚动条。
        left.setMinimumWidth(330)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(4)
        self.param_table = ParamTableWidget(0, 4)
        # 照搬正式程序：10pt 字号、行高 40、方角灰边表格（样式见 PARAM_TABLE_STYLE）
        self.param_table.setFont(QFont("Microsoft YaHei UI", 10))
        self.param_table.setHorizontalHeaderLabels(["序号", "参数名称", "参数值", "单位"])
        self.param_table.verticalHeader().setVisible(False)
        self.param_table.verticalHeader().setDefaultSectionSize(PARAM_ROW_HEIGHT)
        self.param_table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        # 正式程序：Excel 式编辑——单击、双击、回车、直接敲字符都能进编辑
        self.param_table.setEditTriggers(
            QAbstractItemView.SelectedClicked
            | QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.AnyKeyPressed
        )
        self.param_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.param_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.param_table.setAlternatingRowColors(True)
        self.param_table.setStyleSheet(PARAM_TABLE_STYLE)
        header = self.param_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        # 参数名也用固定宽度：拉伸列取整会多出 1~3px，把单位列挤出可视区
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        self.param_table.setColumnWidth(0, 52)
        self.param_table.setColumnWidth(2, PATTERN_COLUMN_WIDTH)
        self.param_table.setColumnWidth(3, 52)
        header.setMinimumSectionSize(10)
        self.param_table.itemChanged.connect(self._on_param_item_changed)
        self.param_table.reflow = self.restore_param_table_column_widths
        left_layout.addWidget(self.param_table, 1)
        self.lagan_summary = QLabel("拉杆标准要求数量-/已有数量0")
        self.lagan_summary.setStyleSheet("color:#222; padding:4px 6px;")
        left_layout.addWidget(self.lagan_summary)
        self.divider_correction_tip = QLabel("")
        self.divider_correction_tip.setWordWrap(True)
        self.divider_correction_tip.setStyleSheet(
            "font-size:10px; color:#222; padding:0 6px 4px;"
        )
        self.divider_correction_tip.setVisible(False)
        left_layout.addWidget(self.divider_correction_tip)
        body.addWidget(left, 30)

        # 中：图形 + 操作栏
        center = QFrame()
        self.center_frame = center
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(4, 4, 4, 4)
        center_layout.setSpacing(4)

        self.scene = QGraphicsScene(self)
        self.view = LayoutGraphicsView(self.scene)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 图形区下限 240：图形本身按可用空间等比缩放，下限再高就会把整页顶出
        # 嵌在平台里的窗格，变成“要拖滚动条才能看全”。
        self.view.setMinimumHeight(240)
        self.view.rubber_band_finished.connect(self.on_rubber_band)
        # 正式程序：页面/图形空白处右键 = 取消筛选（清掉表格与图形的选中）
        self.view.clear_selection_requested.connect(self.clear_selection)
        # 正式程序 My_Piping.py 3808：白底圆角浮层贴在图形区右上角，默认勾选
        self.symmetry_check = QCheckBox("对称分布", self.view)
        self.symmetry_check.setChecked(True)
        self.symmetry_check.setCursor(Qt.PointingHandCursor)
        self.symmetry_check.setStyleSheet(
            "QCheckBox{background:rgba(255,255,255,220);border:1px solid #e6e5e2;"
            "border-radius:6px;padding:3px 9px;color:#333;font-size:10pt;}"
            "QCheckBox:hover{border-color:#c9d8ea;}"
            "QCheckBox::indicator{width:14px;height:14px;}"
        )
        self.symmetry_check.toggled.connect(self._on_symmetry_toggled)
        self.view.installEventFilter(self)
        center_layout.addWidget(self.view, 1)
        self._place_symmetry_check()

        action_bar = QHBoxLayout()
        action_bar.setSpacing(6)
        self.pipe_button = QPushButton("布管")
        self.pipe_button.setCursor(Qt.PointingHandCursor)
        self.pipe_button.setStyleSheet(
            "QPushButton{background:#2f6fe4;color:#fff;border:none;border-radius:7px;padding:6px 16px;font-weight:600;}"
            "QPushButton:hover{background:#2a63cc;}"
        )
        self.pipe_button.clicked.connect(self._on_manual_recompute)
        action_bar.addWidget(self.pipe_button)
        # 「依据」：弹出窗口说明当前自动布置是按哪些标准规则、什么参数算出来的。
        self.basis_button = QPushButton("依据")
        self.basis_button.setCursor(Qt.PointingHandCursor)
        self.basis_button.setToolTip("查看当前元件布置与删管的依据（GB/T 151-2026）")
        self.basis_button.setStyleSheet(
            "QPushButton{background:#fff;border:1px solid #c9d6ea;border-radius:7px;padding:5px 12px;color:#2f6fe4;}"
            "QPushButton:hover{background:#eef4ff;}"
        )
        self.basis_button.clicked.connect(self._emit_basis)
        action_bar.addWidget(self.basis_button)
        self.fullscreen_button = None
        for text, slot in (("撤销", self.undo), ("全屏", self.toggle_fullscreen)):
            button = QPushButton(text)
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(
                "QPushButton{background:#fff;border:1px solid #e2e3e6;border-radius:7px;padding:5px 12px;}"
                "QPushButton:hover{background:#f5f7fa;}"
            )
            button.clicked.connect(slot)
            action_bar.addWidget(button)
            if text == "全屏":
                self.fullscreen_button = button
        action_bar.addStretch()
        self.selection_label = QLabel("未选中管孔")
        self.selection_label.setStyleSheet("color:#8f949c;")
        action_bar.addWidget(self.selection_label)
        center_layout.addLayout(action_bar)
        body.addWidget(center, 50)

        # 右：管孔数量分布
        right = QFrame()
        self.right_frame = right
        right.setObjectName("layoutHoleFrame")
        right.setMinimumWidth(220)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 4, 4, 4)
        self.hole_table = HoleDistributionTable()
        self.hole_table.rows_selected.connect(self.on_table_rows_selected)
        self.hole_table.arrangement_changed.connect(lambda _by_row: self.refresh_hole_table())
        right_layout.addWidget(self.hole_table)
        body.addWidget(right, 20)

        root.addLayout(body, 1)

        # 校验问题 + 唯一的“保留”按钮
        self.issue_frame = QFrame()
        self.issue_frame.setObjectName("layoutIssueFrame")
        self.issue_frame.setStyleSheet(
            "QFrame#layoutIssueFrame{background:#fff8f7;border:1px solid #f0ceca;border-radius:8px;}"
        )
        issue_layout = QVBoxLayout(self.issue_frame)
        issue_layout.setContentsMargins(8, 3, 8, 3)
        issue_layout.setSpacing(1)
        self.issue_frame.setMaximumHeight(64)
        self.issue_title = QLabel("需要修改")
        self.issue_title.setStyleSheet("font-weight:600;color:#9b2c2c;font-size:8.5pt;")
        issue_layout.addWidget(self.issue_title)
        self.issue_list = QLabel("")
        self.issue_list.setWordWrap(True)
        self.issue_list.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.issue_list.setMaximumHeight(24)
        self.issue_list.setStyleSheet("font-size:8.5pt;")
        issue_layout.addWidget(self.issue_list)
        self.recommend_box = QHBoxLayout()
        self.recommend_box.setContentsMargins(0, 0, 0, 0)
        self.recommend_box.addStretch()
        issue_layout.addLayout(self.recommend_box)
        self.issue_frame.hide()
        root.addWidget(self.issue_frame)

        footer = QHBoxLayout()
        footer.addStretch()
        self.keep_button = QPushButton("保留")
        self.keep_button.setCursor(Qt.PointingHandCursor)
        self.keep_button.setMinimumWidth(88)
        self.keep_button.setStyleSheet(
            "QPushButton{background:#2f6fe4;color:#fff;border:none;border-radius:7px;padding:5px 16px;"
            "font-weight:600;font-size:9.5pt;}"
            "QPushButton:hover{background:#2a63cc;}"
            "QPushButton:disabled{background:#eef2fa;color:#a8b6cc;}"
        )
        self.keep_button.clicked.connect(self.keep_requested.emit)
        footer.addWidget(self.keep_button)
        root.addLayout(footer)

    # ------------------------------------------------------ 对称分布
    def eventFilter(self, obj, event):  # noqa: N802 - Qt API
        if obj is self.view and event.type() == QEvent.Resize:
            self._place_symmetry_check()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self.restore_param_table_column_widths()

    def restore_param_table_column_widths(self) -> None:
        """列宽照搬正式程序 restore_param_table_column_widths()：52 / 剩余 / 0.58 / 单位自适应。

        正式程序第 4 列是 `QHeaderView.ResizeToContents`，宽度跟着“单位”表头和 mm/°/个 走；
        这里同样按内容算，并且**只用真实视口宽度**（以前给过 420 的下限，窗口一窄
        四列加起来就超过视口，单位列被挤到右边界外只露出半截“…”）。
        """
        table = getattr(self, "param_table", None)
        if table is None:
            return
        # 留 2px 余量：拉伸列取整后偶尔会多出 1~2px，撑出横向滚动条
        total = table.viewport().width() - 2
        if total <= 0:
            return
        col0_width = 52
        header_font = QFont(table.font())
        header_font.setBold(True)                    # 表头是粗体，按粗体量宽
        header_metrics = QFontMetrics(header_font)
        unit_metrics = QFontMetrics(table.font())
        unit_width = header_metrics.horizontalAdvance("单位") + 28
        for row in range(table.rowCount()):
            unit_item = table.item(row, 3)
            if unit_item is None or not unit_item.text():
                continue
            unit_width = max(
                unit_width, unit_metrics.horizontalAdvance(unit_item.text()) + 28
            )
        unit_width = max(56, unit_width)
        remaining = max(0, total - col0_width - unit_width)
        # 参数名按当前可见行的最长名字给宽（“分程隔板两侧相邻管中心距（竖直）”这类不能出省略号），
        # 剩下的全给参数值列；窗口特别窄时优先保住参数值列，名字才允许省略（有 tooltip）。
        name_needed = 0
        for row in range(table.rowCount()):
            if table.isRowHidden(row):
                continue
            name_item = table.item(row, 1)
            if name_item is None:
                continue
            name_needed = max(name_needed, unit_metrics.horizontalAdvance(name_item.text()) + 22)
        name_width = min(name_needed or 120, max(remaining - 150, 110))
        name_width = max(name_width, min(remaining, 110))
        col1_width = max(name_width, 10)
        col2_width = max(remaining - col1_width, 72)
        table.setColumnWidth(0, col0_width)
        table.setColumnWidth(1, col1_width)
        table.setColumnWidth(2, col2_width)
        table.setColumnWidth(3, unit_width)

    def _place_symmetry_check(self) -> None:
        """勾选框贴在图形区右上角（正式程序 checkbox_container 同款位置）。"""
        box = getattr(self, "symmetry_check", None)
        if box is None:
            return
        box.adjustSize()
        x = max(self.view.width() - box.width() - 10, 6)
        box.move(x, 10)
        box.raise_()

    def _on_symmetry_toggled(self, checked: bool) -> None:
        self._symmetry = bool(checked)
        self.status_message.emit(
            "对称分布：开（选中 1 根自动补出 4 象限镜像）"
            if self._symmetry
            else "对称分布：关（只按管程程数做单轴镜像）"
        )

    def symmetry_on(self) -> bool:
        return bool(self._symmetry)

    def set_symmetry(self, on: bool) -> None:
        """给脚本/自检用：等价于点一下勾选框。"""
        box = getattr(self, "symmetry_check", None)
        if box is not None:
            box.setChecked(bool(on))
        self._symmetry = bool(on)

    # ------------------------------------------------------ 参数表
    def rebuild_parameter_table(self) -> None:
        table = self.param_table
        self._suppress_commit = True
        try:
            for row in range(table.rowCount()):
                widget = table.cellWidget(row, 2)
                if widget is not None:
                    table.removeCellWidget(row, 2)
                    widget.deleteLater()
            table.setRowCount(len(PARAM_ORDER))
            self._editors = {}
            for row, name in enumerate(PARAM_ORDER):
                spec = spec_for(name, self.product_type, self.parameters)
                data = self.parameters[name]
                seq = QTableWidgetItem(str(row + 1))
                seq.setTextAlignment(Qt.AlignCenter)
                seq.setFlags(Qt.ItemIsEnabled)
                table.setItem(row, 0, seq)
                label = QTableWidgetItem(name)
                label.setFlags(Qt.ItemIsEnabled)
                label.setToolTip(name)
                table.setItem(row, 1, label)
                unit = QTableWidgetItem(data.get("unit", "") or spec.unit)
                unit.setTextAlignment(Qt.AlignCenter)
                unit.setFlags(Qt.ItemIsEnabled)
                table.setItem(row, 3, unit)
                # 正式程序：普通参数就是单元格文本，单击/回车进编辑；只有下拉类
                # （combo / 可输入 combo / 分程形式示意图）才嵌控件。
                editor = self._make_editor(name, spec, data)
                if editor is None:
                    item = QTableWidgetItem(normalize_param_value(name, data.get("value"), self.parameters))
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
                    if not spec.readonly and name != "公称直径 DN":
                        flags |= Qt.ItemIsEditable
                    item.setFlags(flags)
                    table.setItem(row, 2, item)
                    self._editors[name] = None
                else:
                    placeholder = QTableWidgetItem("")
                    placeholder.setFlags(Qt.ItemIsEnabled)
                    table.setItem(row, 2, placeholder)
                    table.setCellWidget(row, 2, editor)
                    self._editors[name] = editor
                table.setRowHeight(row, PARAM_ROW_HEIGHT)
                self._paint_param_row(row, name)
            table.setRowHeight(PARAM_ORDER.index("管程分程形式"), PATTERN_ROW_HEIGHT)
            self.apply_param_visibility()
        finally:
            self._suppress_commit = False
        self._lock_outer_base_flag()
        self.restore_param_table_column_widths()

    def _make_editor(self, name: str, spec, data: dict) -> QWidget | None:
        # 正式程序填充参数表时的几条兜底（拉杆形式按 do、滑道数量默认 2、旧文案归一…）
        value = normalize_param_value(name, data.get("value"), self.parameters)
        readonly = spec.readonly
        if spec.kind == "pattern":
            # 正式程序 TubePassFormComboBox：显示示意图，不是数字/文字
            combo = TubePassFormComboBox()
            items = list(spec.options)
            if value and value not in items:
                # 库里留着历史值（如 4.3）：照样补一项并配它的示意图
                items.append(value)
            for option in items:
                image = tube_pattern_image(option)
                path = STATIC_DIR / "TubePattern" / image if image else None
                pixmap = QPixmap(str(path)) if path is not None and path.exists() else QPixmap()
                combo.addItem("", option)
                combo.setItemData(combo.count() - 1, option, Qt.UserRole)
                if not pixmap.isNull():
                    combo.setItemData(combo.count() - 1, pixmap, TubePassFormComboBox.PIXMAP_ROLE)
            index = combo.findData(value) if value else -1
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.setEnabled(not readonly)
            combo.activated.connect(lambda _i, n=name, c=combo: self._commit_param(n, c.currentData()))
            return combo
        if spec.kind == "combo" and spec.options:
            combo = ParamComboBox()
            for option in spec.options:
                combo.addItem(option, option)
            # 库里的“转角正方形”要显示成新文案“转角正方形排列（45°）”，提交时再转回去
            display = normalize_tube_arrangement(value) if name == "换热管排列方式" else value
            index = combo.findData(display) if display else -1
            if index < 0 and display:
                # 正式程序遇到表里没有的历史值时保留显示，但不允许再选新值
                combo.addItem(display, display)
                index = combo.count() - 1
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.setEnabled(not readonly)
            combo.activated.connect(lambda _i, n=name, c=combo: self._commit_param(n, c.currentData()))
            return combo
        if spec.kind == "combo_edit":
            # 正式程序：换热管外径 do / 公称长度 LN 都是“下拉可选 + 手工输入”
            combo = ParamComboBox(editable=True)
            if combo.lineEdit() is not None:
                combo.lineEdit().setReadOnly(False)
                if name == "换热管公称长度 LN":
                    validator = QIntValidator(1, 99999, combo)
                else:
                    validator = QDoubleValidator(0.0, 99999.0, 2, combo)
                    validator.setNotation(QDoubleValidator.StandardNotation)
                    validator.setLocale(QLocale.c())      # 小数点固定 "."，不跟系统区域
                combo.setValidator(validator)
            for option in spec.options:
                combo.addItem(option)
            if value:
                combo.setEditText(value)
            combo.setEnabled(not readonly)
            combo.activated.connect(lambda _i, n=name, c=combo: self._commit_param(n, c.currentText()))
            if combo.lineEdit() is not None:
                combo.lineEdit().editingFinished.connect(
                    lambda n=name, c=combo: self._commit_param(n, c.currentText())
                )
            return combo
        # 普通参数（数字/文本）：正式程序是单元格内直接编辑，不嵌控件
        return None

    def _paint_param_row(self, row: int, name: str) -> None:
        data = self.parameters[name]
        spec = spec_for(name, self.product_type, self.parameters)
        item = self.param_table.item(row, 2)
        if item is None:
            return
        issue = next((x for x in self.issues if x.get("field") == name), None)
        if issue:
            item.setBackground(QColor("#ffe4e2"))
            item.setToolTip(issue.get("message", ""))
        elif name in DERIVED_FIELDS:
            item.setBackground(QColor("#eef3f8"))
            item.setToolTip("由程序联动计算")
        else:
            item.setBackground(QColor("#ffffff"))
            item.setToolTip("")
        editor = self._editors.get(name)
        if editor is None:
            # 正式程序：公称直径 DN 灰字不可改；只读联动值也灰字
            grey = name == "公称直径 DN" or spec.readonly
            item.setForeground(QColor("#969696" if grey else "#1f1f1f"))
        if editor is not None:
            base = "QLineEdit{background:#ffffff;border:1px solid #e6e5e2;border-radius:4px;padding:2px 6px;}"
            error = "QLineEdit{background:#fff5f5;border:1px solid #d04b4b;border-radius:4px;padding:2px 6px;}"
            readonly = "QLineEdit{background:#f4f6f8;color:#6b7280;border:1px solid #eef0f3;border-radius:4px;padding:2px 6px;}"
            if isinstance(editor, QLineEdit):
                editor.setStyleSheet(error if issue else (readonly if spec.readonly else base))
            elif isinstance(editor, QComboBox):
                # 下拉框样式照搬正式程序（白底、1px #CCCCCC、灰色三角），不再用圆角。
                # 只读/锁定行（是否以外径为基准）灰底灰字。
                locked = (name == "是否以外径为基准") or spec.readonly or not editor.isEnabled()
                apply_param_combo_style(
                    editor,
                    disabled=locked,
                    border="#d04b4b" if issue else None,
                )
                editor.setToolTip(issue.get("message", "") if issue else "")
            if issue:
                editor.setToolTip(issue.get("message", ""))

    # ------------------------------------------------------ 参数提交与联动
    def set_parameter(self, name: str, value, source: str = "人工修改", run_linkage: bool = True) -> bool:
        if name not in self.parameters:
            return False
        spec = spec_for(name, self.product_type, self.parameters)
        text = "" if value is None else str(value).strip()
        if name == "换热管排列方式":
            text = canonical_tube_arrangement(text)      # 存库用规范名，与正式程序一致
        # 与正式程序一致：普通下拉只能是现有选项；只读参数不接受修改；数字必须能转成数
        if spec.readonly and source not in {"联动计算", "程序默认值", "联动修正"}:
            if str(self.parameters[name].get("value", "")) != text:
                self._warn("参数只读", f"{name} 由其他参数联动计算，不能直接修改。")
                self._refresh_editor(name)
                return False
        if spec.kind == "combo" and spec.options:
            allowed = set(spec.options)
            if name == "换热管排列方式":
                allowed |= {canonical_tube_arrangement(option) for option in spec.options}
            if text and text not in allowed:
                self._warn(
                    "无效选项",
                    f"{name} 是普通下拉框，只能从现有 {len(spec.options)} 个选项中选择，"
                    f"已拒绝“{text}”。",
                )
                self._refresh_editor(name)
                return False
        if spec.kind == "number" and text:
            try:
                float(text)
            except ValueError:
                self._warn("输入无效", f"{name} 必须填写数字，已拒绝“{text}”。")
                self._refresh_editor(name)
                return False
        if spec.kind == "combo_edit" and text and text != "程序推荐":
            try:
                float(text)
            except ValueError:
                self._warn("输入无效", f"{name} 只能填“程序推荐”或数字，已拒绝“{text}”。")
                self._refresh_editor(name)
                return False
        old = self.parameters[name]["value"]
        self.parameters[name]["value"] = value
        self.parameters[name]["source"] = source
        if run_linkage:
            self._apply_linkage(name)
        editor = self._editors.get(name)
        text = "" if value is None else str(value)
        if isinstance(editor, QLineEdit) and editor.text() != text:
            editor.setText(text)
        elif isinstance(editor, QComboBox):
            if str(editor.currentData()) != str(value):
                index = editor.findData(value)
                if index < 0:
                    index = editor.findText(text)
                if index >= 0 and editor.currentIndex() != index:
                    editor.setCurrentIndex(index)
        self.state_changed.emit({"parameter": name, "old": old, "value": value})
        return str(old) != str(value)

    def _commit_param(self, name: str, raw_value) -> None:
        if self._suppress_commit:
            return
        text = "" if raw_value is None else str(raw_value).strip()
        spec = spec_for(name, self.product_type, self.parameters)
        if spec.kind == "combo" and spec.options:
            if text and text not in spec.options:
                self._warn("不能输入", f"{name} 是普通下拉框，只能从现有选项中选择。")
                self._refresh_editor(name)
                return
        if spec.kind in {"number"} and text:
            try:
                float(text)
            except ValueError:
                self._warn("输入无效", f"{name} 必须填写数字。")
                self._refresh_editor(name)
                return
        if spec.kind == "combo_edit" and text and text != "程序推荐":
            try:
                float(text)
            except ValueError:
                self._warn("输入无效", f"{name} 只能填“程序推荐”或数字。")
                self._refresh_editor(name)
                return
        changed = self.set_parameter(name, text)
        if changed:
            self.recompute(reason=f"修改 {name}")
        else:
            self._refresh_editor(name)

    def _warn(self, title: str, text: str, kind: str = "warning") -> None:
        if self.headless:
            self.status_message.emit(f"{title}：{text}")
            return
        if kind == "info":
            QMessageBox.information(self, title, text)
        else:
            QMessageBox.warning(self, title, text)

    def _on_param_item_changed(self, item) -> None:
        """单元格内编辑提交（正式程序同款：直接改格子里的文字）。"""
        if self._suppress_commit or item is None or item.column() != 2:
            return
        row = item.row()
        if not 0 <= row < len(PARAM_ORDER):
            return
        self._commit_param(PARAM_ORDER[row], item.text())

    def _refresh_editor(self, name: str) -> None:
        editor = self._editors.get(name)
        value = self.parameters[name]["value"]
        if editor is None:
            # 普通参数没有控件，直接回写单元格文本
            item = self.param_table.item(PARAM_ORDER.index(name), 2)
            if item is None:
                return
            text = normalize_param_value(name, value, self.parameters)
            if item.text() == text:
                return
            self._suppress_commit = True
            try:
                item.setText(text)
            finally:
                self._suppress_commit = False
            return
        self._suppress_commit = True
        try:
            if isinstance(editor, QLineEdit):
                editor.setText("" if value is None else str(value))
            elif isinstance(editor, QComboBox):
                wanted = (
                    normalize_tube_arrangement(value)
                    if name == "换热管排列方式" else str(value)
                )
                spec = spec_for(name, self.product_type, self.parameters)
                if spec.kind == "combo_edit":
                    if editor.currentText() != wanted:
                        editor.setEditText(wanted)
                    return
                if str(editor.currentData()) == wanted:
                    return
                index = editor.findData(wanted)
                if index < 0:
                    index = editor.findText(wanted)
                if index >= 0:
                    editor.setCurrentIndex(index)
        finally:
            self._suppress_commit = False

    # ------------------------------------------------------ 参数显隐（正式程序同逻辑）
    def apply_param_visibility(self) -> None:
        """按正式程序的 hidden_params / update_SN / 直径基准规则隐藏参数行。"""
        hidden = layout_hidden_params(self.parameters)
        table = self.param_table
        for row, name in enumerate(PARAM_ORDER):
            table.setRowHidden(row, name in hidden)
        self._renumber_rows()

    def _renumber_rows(self) -> None:
        """隐藏行不占序号：可见行从 1 连续编号（正式程序 renumber_visible_rows）。"""
        visible = 0
        for row in range(self.param_table.rowCount()):
            if self.param_table.isRowHidden(row):
                continue
            visible += 1
            item = self.param_table.item(row, 0)
            if item is not None:
                item.setText(str(visible))

    def _lock_outer_base_flag(self) -> None:
        """正式程序：是否以外径为基准在布管页只读灰显，不在界面手工修改。"""
        editor = self._editors.get("是否以外径为基准")
        if isinstance(editor, QComboBox):
            editor.setEnabled(False)
            editor.setFocusPolicy(Qt.NoFocus)
            apply_param_combo_style(editor, disabled=True)   # 正式程序：灰底灰字、箭头照旧
            editor.setToolTip("由设计数据表/通用数据表决定，布管页不可修改")

    def _apply_linkage(self, changed: str) -> None:
        """正式程序的参数联动：DN→Dis/Dit，Dis→折流板外径/DL，do+排列→S/Sn，管程→分程形式。

        除了“程序默认值/联动计算”这种可覆盖的来源，这里还有一条硬约束：
        库里按 1200 系列存量的 Dis/Dit/折流板外径 一旦大于当前的公称直径 DN
        （典型情形：上游把 DN 改成 400，参数表里还留着 1144），
        画出来的“内圆”会比 DN 外圆还大、管子缩在中间一小块，DLL 也按错误直径布管。
        所以只要和 DN 矛盾，就按 DN 修正，并在来源里标成“联动修正”。
        """
        dn = self._float("公称直径 DN")
        dis = self._float("壳体内直径 Dis")
        r2 = self._float_from_sheet_form("R2", 8.0)
        default_like = {"程序默认值", "联动计算", "联动修正"}

        def fix(name: str, value: str) -> None:
            """写入联动值，并把“旧值 → 新值”记进修正回执（显示在操作栏）。"""
            old = self.parameters[name]["value"]
            if self.set_parameter(name, value, "联动修正", run_linkage=False):
                fixes = getattr(self, "_linkage_fixes", None)
                if fixes is not None:
                    fixes.append(f"{name} {old} → {value}")

        if changed == "公称直径 DN" and dn:
            if (self.parameters["壳体内直径 Dis"]["source"] in default_like
                    or dis is None or dis > dn):
                fix("壳体内直径 Dis", self._pretty(dn))
            dit = self._float("管箱内直径 Dit")
            if (self.parameters["管箱内直径 Dit"]["source"] in default_like
                    or dit is None or dit > dn):
                fix("管箱内直径 Dit", self._pretty(dn))
            dis = self._float("壳体内直径 Dis")
        if changed == "壳体内直径 Dis" and dn and dis and dis > dn:
            # 壳体内直径大于公称直径没有物理意义：按 DN 截断，再让下面联动 Dis 分支重算 DL
            fix("壳体内直径 Dis", self._pretty(dn))
            dis = self._float("壳体内直径 Dis")
        if changed in {"壳体内直径 Dis", "公称直径 DN"} and dis:
            baffle = self._float("折流/支持板外径")
            if (self.parameters["折流/支持板外径"]["source"] in default_like
                    or baffle is None or baffle > dis):
                # 正式程序：折流/支持板外径 = 壳体内直径 - 6（见默认表 1144→1138）
                fix("折流/支持板外径", self._pretty(max(dis - 6, 0)))
            dl = self._float("布管限定圆 DL")
            if (self.parameters["布管限定圆 DL"]["source"] in default_like
                    or dl is None or dl > dis):
                fix("布管限定圆 DL", self._pretty(max(dis - 2 * r2, 0)))
        if changed in {"换热管外径 do", "换热管排列方式"}:
            self._apply_center_distance()
        if changed == "管程程数":
            forms = spec_for("管程分程形式", self.product_type, self.parameters).options
            current = str(self.parameters["管程分程形式"]["value"])
            if forms and current not in forms:
                self.set_parameter("管程分程形式", forms[0], "联动计算", run_linkage=False)
            self._rebuild_editor_options("管程分程形式")
        if changed in {"是否以外径为基准", "管程程数", "管程分程形式"}:
            # 与正式程序一致：这几个参数变化后重算哪些行该隐藏
            self.apply_param_visibility()
        if getattr(self, "_linkage_fixes", None) and (self.isVisible() or changed != "公称直径 DN"):
            self._report_linkage_fixes()

    def _report_linkage_fixes(self) -> None:
        fixes = getattr(self, "_linkage_fixes", None)
        if not fixes:
            return
        self._linkage_fixes = []
        self.status_message.emit("已按公称直径 DN 校正参数：" + "；".join(fixes))

    def showEvent(self, event):  # noqa: N802 - Qt API
        super().showEvent(event)
        self._report_linkage_fixes()

    def _rebuild_editor_options(self, name: str) -> None:
        old = self._editors.get(name)
        if old is None:
            return
        row = PARAM_ORDER.index(name)
        spec = spec_for(name, self.product_type, self.parameters)
        new = self._make_editor(name, spec, self.parameters[name])
        self.param_table.removeCellWidget(row, 2)
        old.deleteLater()
        self.param_table.setCellWidget(row, 2, new)
        self._editors[name] = new

    def _apply_center_distance(self) -> None:
        if not self.center_distance_rows:
            return
        do = self._float("换热管外径 do")
        arrangement = str(self.parameters["换热管排列方式"]["value"] or "")
        if not do:
            return
        triangle = arrangement in {"正三角形", "转角正三角形"}
        header = self.center_distance_rows[0]
        try:
            index = header.index("换热管外径d")
        except ValueError:
            return
        row_s = self.center_distance_rows[1] if triangle else self.center_distance_rows[2]
        row_sn = self.center_distance_rows[3] if len(self.center_distance_rows) > 3 else None
        do_text = self._pretty(do)
        if do_text not in header:
            return
        position = header.index(do_text)
        if position >= len(row_s):
            return
        if self.parameters["换热管中心距 S"]["source"] in {"程序默认值", "联动计算"}:
            self.set_parameter("换热管中心距 S", row_s[position], "联动计算", run_linkage=False)
        if row_sn and position < len(row_sn) and self.parameters["分程隔板两侧相邻管中心距（竖直）"]["source"] in {"程序默认值", "联动计算"}:
            self.set_parameter("分程隔板两侧相邻管中心距（竖直）", row_sn[position], "联动计算", run_linkage=False)

    def _float(self, name: str) -> float | None:
        try:
            return float(str(self.parameters.get(name, {}).get("value", "")).strip())
        except (TypeError, ValueError):
            return None

    def _float_from_sheet_form(self, symbol: str, default: float) -> float:
        try:
            return float(str(self.sheet_form.get(symbol, default)).strip())
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _pretty(value: float) -> str:
        number = float(value)
        return str(int(number)) if number.is_integer() else f"{number:.1f}"

    # ------------------------------------------------------ 计算 + 绘制
    def _heal_tube_pass_form(self) -> None:
        """纠正上游提取带来的「管程分程形式」与程数不一致（如 4 管程配 2.1）。"""
        try:
            row = self.parameters.get("管程分程形式") or {}
            current = str(row.get("value") or "").strip()
            if not current:
                return
            from bundle.params import spec_for
            forms = list(spec_for("管程分程形式", self.product_type, self.parameters).options or ())
            if not forms:
                from bundle.params import TUBE_PATTERN_BY_PASS
                forms = list(TUBE_PATTERN_BY_PASS.get(
                    str(self.parameters.get("管程程数", {}).get("value", "")).strip(), ()))
            if forms and current not in forms:
                self.set_parameter("管程分程形式", forms[0], "联动计算", run_linkage=False)
        except Exception:
            pass

    def recompute(self, reason: str = "", first: bool = False, keep_components: bool = False) -> bool:
        # 正式程序点“布管”会清空全部元件（拉杆/挡板/防冲板/滑道…）再重算，
        # 这里保持一致：不保留上一次布置的元件，避免旧元件挂在新管孔上。
        # 撤销/回放时用 keep_components=True 把快照里的元件保住。
        had_components = len(self.components)
        self._push_undo()
        if not keep_components:
            self.components.clear()
            self._clear_selection_state()
            self.removed.clear()
        try:
            result = engine.compute(self.parameters, self.product_type, self.defaults)
        except Exception as exc:  # noqa: BLE001 - 需要把真实原因展示给用户
            self.divider_correction_tip.clear()
            self.divider_correction_tip.setVisible(False)
            self.issues = [{"field": "换热管中心距 S", "message": str(exc), "recommended": None}]
            self.show_issues()
            self.status_message.emit(f"布管失败：{exc}")
            return False
        self.result = result
        self._update_divider_correction_tip(result)
        if keep_components:
            # 重算后管孔集合可能变了：把挂在不存在的管孔/壳壁外的旧元件丢掉
            known = set(result.master_centers)
            self.removed &= known
            # 只有“钉在某个管孔上”的元件才要求这个管孔还在；滑道/吊环/防冲板/挡板
            # 的 center 只是几何中心，不能拿它去比管孔，否则一重算就被丢掉。
            hole_kinds = {"rod", "free_rod", "block_tube", "bypass", "radial_hole"}
            self.components = [
                comp for comp in self.components
                if comp.get("kind") not in hole_kinds
                or not comp.get("center")
                or tuple(comp["center"]) in known
            ]
        # 分程形式自愈：上游数据表里「管程分程形式」可能与「管程程数」不一致
        # （实测 1906：程数=4 但提取到 2.1），校验会据此标红。这里在校验前先按
        # 当前管程数的合法集合纠正一次，与用户手改程数时的联动逻辑保持一致。
        self._heal_tube_pass_form()
        self.issues = engine.check_geometry(self.parameters, result)
        self.rebuild_scene()
        self.refresh_hole_table()
        self.show_issues()
        if result.note:
            self.status_message.emit("布管数据已校正：" + result.note)
        if reason:
            total = len(self.current_centers())
            extra = f"，已清掉上次布置的 {had_components} 个元件" if had_components else ""
            self.status_message.emit(f"{reason}：已重新布管{extra}，当前 {total} 个管孔")
        return not self.issues

    @staticmethod
    def _plot(center) -> tuple[float, float]:
        """数学坐标（y 向上）→ 场景坐标（Qt y 向下），与正式程序 `_add(x, -y)` 一致。"""
        return (float(center[0]), -float(center[1]))

    def current_centers(self) -> list[tuple[float, float]]:
        if self.result is None:
            return []
        occupied = {c["center"] for c in self.components if c.get("center")}
        return [
            c for c in self.result.master_centers
            if c not in self.removed and c not in occupied
        ]

    def removed_centers(self) -> list[tuple[float, float]]:
        """已删除（且没有被拉杆/挡管占位）的管孔：图上画成虚线小叉，可点选恢复。"""
        if self.result is None:
            return []
        occupied = {c["center"] for c in self.components if c.get("center")}
        return [
            c for c in self.result.master_centers
            if c in self.removed and c not in occupied
        ]

    def selectable_centers(self) -> list[tuple[float, float]]:
        """可被单击选中的点：换热管孔 + 已布置的普通拉杆。

        正式程序 `ClickableCircleItem.mousePressEvent` 里，普通拉杆和换热管是同一性质：
        点一下把它自己的坐标并进 `selected_centers`（My_Piping.py 947~1005），
        所以防冲板/挡板可以直接“选两根拉杆”当参照管。
        """
        out = list(self.current_centers())
        seen = {(round(c[0], 6), round(c[1], 6)) for c in out}
        for comp in self.components:
            if comp.get("kind") != "rod" or not comp.get("center"):
                continue
            center = (float(comp["center"][0]), float(comp["center"][1]))
            key = (round(center[0], 6), round(center[1], 6))
            if key not in seen:
                seen.add(key)
                out.append(center)
        return out

    def _linkage_expand(self, centers, pool=None) -> list[tuple[float, float]]:
        """正式程序 `judge_linkage` / `judge_linkage_x` / `judge_linkage_y`。

        对称分布勾选（默认）→ 原选点 + 关于 y 轴、x 轴、圆心的三个镜像（4 象限）；
        不勾 → 只有 AEU/BEU/AKU/BKU 才补镜像：2 管程关于水平中心线 (x, −y)，
        4/6 管程关于竖直中心线 (−x, y)；其它型式只保留原选点。
        镜像点必须落在一个真实管孔（或已布置的拉杆）上，正式程序
        `actual_to_selected_coords` 返回空就是丢弃，这里同样丢弃。
        """
        known = {
            (round(c[0], 6), round(c[1], 6))
            for c in (self.selectable_centers() if pool is None else pool)
        }
        if self._symmetry:
            targets = [(x, y) for x in (1, -1) for y in (1, -1)]
        elif self.product_type in {"AEU", "BEU", "AKU", "BKU"}:
            passes = self._param_text("管程程数")
            if passes == "2":
                targets = [(1, 1), (1, -1)]
            elif passes in {"4", "6"}:
                targets = [(1, 1), (-1, 1)]
            else:
                targets = [(1, 1)]
        else:
            targets = [(1, 1)]

        out: list[tuple[float, float]] = []
        seen: set[tuple[float, float]] = set()
        for x, y in centers:
            for sx, sy in targets:
                key = (round(float(x) * sx, 6), round(float(y) * sy, 6))
                if key in seen or key not in known:
                    continue
                seen.add(key)
                out.append(key)
        return out

    def rebuild_scene(self) -> None:
        scene = self.scene
        scene.clear()
        self._tube_items.clear()
        self._component_items.clear()
        if self.result is None:
            return
        result = self.result
        radii = self._envelope_radii(result)
        outer = max(radii["外圆"], radii["内圆"], radii["限定圆"]) or float(result.big_r_wai)
        pad = max(outer, 10.0) * 0.18
        scene.setSceneRect(
            -outer - pad, -outer - pad,
            (outer + pad) * 2, (outer + pad) * 2,
        )
        self._draw_axes(outer)
        self._draw_envelope(result)
        self._draw_baffle_chords(result)
        self._draw_partition(result)
        self._draw_tubes(result)
        self._draw_components()
        self._draw_center_lines(result)
        self.view.fit_all()
        QTimer.singleShot(0, self.view.fit_all)
        self._update_lagan_summary()

    def _envelope_radii(self, result: engine.LayoutResult) -> dict[str, float]:
        """图上三个同心圆的半径，与参数表一一对应且互为约束。

        外圆 = 公称直径 DN；内圆 = 壳体内直径 Dis；限定圆 = 布管限定圆 DL。
        物理上必然 Dis ≤ DN、DL ≤ Dis；但库里的“布管参数表”是按 1200 系列存量的，
        当上游把 DN 改成 400 时，Dis/DL/折流板外径 可能仍留着 1144/1128/1138，
        照抄就会画出“比公称直径还大的外圆”，管子缩在中间一小块。这里按
        Dis ≤ DN、DL ≤ Dis、折流板外径 ≤ Dis 统一截断，保证图形与参数一致。
        """
        outer = max(float(result.big_r_wai), 0.0)
        inner = max(float(result.big_r_di), 0.0)
        limit = max(float(result.big_r_nei), 0.0)
        baffle = max(float(result.baffle_r), 0.0)
        if outer <= 0:
            outer = inner or limit or baffle
        if inner <= 0:
            inner = outer
        inner = min(inner, outer)
        if limit <= 0:
            limit = inner
        limit = min(limit, inner)
        baffle = min(baffle, inner)
        return {"外圆": outer, "内圆": inner, "限定圆": limit, "折流/支持板外圆": baffle}

    def _draw_baffle_chords(self, result: engine.LayoutResult) -> None:
        """绘制正式程序中的单弓黄线或双弓 A/B 蓝红弦线。"""
        baffle_type = self._param_text("折流板类型")
        radii = self._envelope_radii(result)
        # 正式程序：单弓形按壳体内径圆算黄线；双弓形优先按折流板外径圆算 A/B 线。
        radius = float(
            (radii["折流/支持板外圆"] or radii["内圆"])
            if baffle_type in {"双弓型", "双弓形"}
            else radii["内圆"]
        )
        for spec in baffle_chord_specs(self.parameters, radius):
            pen = QPen(QColor(*spec["color"]))
            pen.setWidth(int(spec["width"]))
            half = float(spec["half_length"])
            level = float(spec["level"])
            if spec["orientation"] == "horizontal":
                item = self.scene.addLine(-half, level, half, level, pen)
            else:
                item = self.scene.addLine(level, -half, level, half, pen)
            item.setZValue(10)

    def _draw_axes(self, radius: float) -> None:
        extension = radius * 0.1
        total = radius + extension
        arrow = 10
        x_color = QColor(Qt.red)
        x_color.setAlpha(128)
        y_color = QColor(Qt.green)
        y_color.setAlpha(128)
        pen_x = QPen(x_color)
        pen_x.setWidth(5)
        pen_y = QPen(y_color)
        pen_y.setWidth(5)
        for item in (
            self.scene.addLine(-total, 0, total, 0, pen_x),
            self.scene.addLine(total, 0, total - arrow, -arrow / 2, pen_x),
            self.scene.addLine(total, 0, total - arrow, arrow / 2, pen_x),
            self.scene.addLine(-total, 0, -total + arrow, -arrow / 2, pen_x),
            self.scene.addLine(-total, 0, -total + arrow, arrow / 2, pen_x),
            self.scene.addLine(0, -total, 0, total, pen_y),
            self.scene.addLine(0, -total, -arrow / 2, -total + arrow, pen_y),
            self.scene.addLine(0, -total, arrow / 2, -total + arrow, pen_y),
            self.scene.addLine(0, total, -arrow / 2, total - arrow, pen_y),
            self.scene.addLine(0, total, arrow / 2, total - arrow, pen_y),
        ):
            item.setZValue(15)
        font = QFont("Arial", 11, QFont.Bold)
        for label, x, y in (
            ("0°", -10, -total - 46),
            ("90°", total + 8, -20),
            ("180°", -22, total + 6),
            ("270°", -total - 46, -20),
        ):
            text = self.scene.addText(label, font)
            text.setDefaultTextColor(QColor(90, 90, 90))
            text.setPos(x, y)
            text.setZValue(16)

    def _draw_envelope(self, result: engine.LayoutResult) -> None:
        radii = self._envelope_radii(result)
        pens = {
            "外圆": QPen(Qt.black, 2),
            "内圆": QPen(Qt.gray, 2),
            "限定圆": QPen(QColor(0, 0, 0), 2),
        }
        for key, pen in pens.items():
            radius = radii[key]
            if radius <= 0:
                continue
            item = self.scene.addEllipse(-radius, -radius, radius * 2, radius * 2, pen, QBrush(Qt.NoBrush))
            item.setZValue(20)
        if radii["折流/支持板外圆"] > 0:
            pen = QPen(QColor(120, 120, 120), 1.6, Qt.DashLine)
            item = self.scene.addEllipse(
                -radii["折流/支持板外圆"], -radii["折流/支持板外圆"],
                radii["折流/支持板外圆"] * 2, radii["折流/支持板外圆"] * 2,
                pen, QBrush(Qt.NoBrush),
            )
            item.setZValue(18)

    def _draw_partition(self, result: engine.LayoutResult) -> None:
        """分程隔板：按 SN（竖直）/SNH（水平）在管孔带之间画隔板带。"""
        radii = self._envelope_radii(result)
        do = result.small_r * 2
        radius = radii["限定圆"] or radii["外圆"]
        sn = result.SN
        snh = float(result.raw.get("SNH") or 0)
        band_pen = QPen(QColor(80, 80, 80), 1.4)
        hatch = QBrush(QColor(200, 200, 200, 140), Qt.BDiagPattern)
        if sn and sn > do:
            half = (sn - do) / 2.0
            if half > 0.3 and half < radius:
                chord = math.sqrt(max(radius ** 2 - half ** 2, 0))
                rect = self.scene.addRect(-chord, -half, chord * 2, half * 2, band_pen, hatch)
                rect.setZValue(12)
        if snh and snh > do:
            half = (snh - do) / 2.0
            if half > 0.3 and half < radius:
                chord = math.sqrt(max(radius ** 2 - half ** 2, 0))
                rect = self.scene.addRect(-half, -chord, half * 2, chord * 2, band_pen, hatch)
                rect.setZValue(12)

    def _draw_tubes(self, result: engine.LayoutResult) -> None:
        r = result.small_r
        self._ghost_items.clear()
        # 已删除的管孔先画（在换热管下面）：虚线圆圈 + 小叉，仍可点选
        for center in self.removed_centers():
            ghost = GhostTubeItem(center, r, self)
            ghost.apply_selected(center in self.selected)
            self.scene.addItem(ghost)
            self._ghost_items[center] = ghost
        for center in self.current_centers():
            item = TubeItem(center, r, self)
            item.apply_selected(center in self.selected)
            self.scene.addItem(item)
            self._tube_items[center] = item

    def _draw_center_lines(self, result: engine.LayoutResult) -> None:
        """圆心连线：与正式程序 connect_center 一致——凡距离等于中心距 S 的相邻管孔连蓝色细线。

        正式程序用网格索引把 O(n²) 降到 O(n)，这里照搬；排列方式（转角三角形/正方形……）
        不同时相邻方向也不同，因此不能只判同行间距。
        """
        spacing = float(result.S or 0.0)
        if spacing <= 0:
            return
        # 源程序 connect_center 用的是 self.global_centers（所有理论管孔），不是删管后的
        # current_centers。删管后大量相邻关系断裂，连线会稀疏甚至消失。这里必须用满布孔。
        centers = list(result.master_centers)
        if len(centers) < 2:
            return
        # 源程序判据是 S-1 <= dist <= S+1，固定 ±1，不按百分比放大。
        tolerance = 1.0
        grid_size = max(spacing * 1.2, 1e-6)
        grid: dict[tuple[int, int], list[int]] = {}
        for index, (x, y) in enumerate(centers):
            grid.setdefault((round(x / grid_size), round(y / grid_size)), []).append(index)

        path = QPainterPath()
        linked: set[tuple[int, int]] = set()
        for index, (x0, y0) in enumerate(centers):
            cell = (round(x0 / grid_size), round(y0 / grid_size))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for other in grid.get((cell[0] + dx, cell[1] + dy), ()):
                        if other <= index:
                            continue
                        pair = (index, other)
                        if pair in linked:
                            continue
                        x1, y1 = centers[other]
                        if abs(math.hypot(x1 - x0, y1 - y0) - spacing) <= tolerance:
                            linked.add(pair)
                            path.moveTo(x0, -y0)
                            path.lineTo(x1, -y1)
        if path.isEmpty():
            return
        # 源程序 connect_center：pen = QPen(QColor(0,0,255)), width=1，不透明，
        # 且不设 z（默认在上层），连线穿过管孔圆心形成 × 网格，是可见的参考线。
        pen = QPen(QColor(0, 0, 255))
        pen.setWidthF(1.0)
        item = QGraphicsPathItem(path)
        item.setPen(pen)
        # 画在管孔之上、元件之下：连线可见但不遮挡防冲板/滑道/拉杆。
        item.setZValue(0.5)
        self.scene.addItem(item)

    # ------------------------------------------------------ 元件绘制
    def _draw_components(self) -> None:
        for index, component in enumerate(self.components):
            kind = component["kind"]
            center = component.get("center")
            if kind in {"rod", "free_rod", "block_tube"} and center:
                radius = self.result.small_r if self.result else 12.5
                if kind == "rod":
                    item = RodItem(center, radius, self, free=False)
                elif kind == "free_rod":
                    item = RodItem(center, radius, self, free=True)
                else:
                    item = BlockTubeItem(center, radius, self)
                # 普通拉杆和换热管同性质：选中状态记在 self.selected 的坐标里
                if kind == "rod":
                    item.apply_selected(tuple(center) in self.selected)
                else:
                    item.apply_selected(index in self.selected_components)
                item.component_index = index
                self.scene.addItem(item)
                self._component_items[index] = item
            elif kind == "screw_ring" and center:
                # 吊环螺钉：源程序 = 蓝色空心圆 + 井字弦，不是矩形块
                radius = (component.get("size", (24.0, 24.0))[0] or 24.0) / 2.0
                item = ScrewRingItem(center, radius, self)
                item.apply_selected(index in self.selected_components)
                item.component_index = index
                self.scene.addItem(item)
                self._component_items[index] = item
            elif component.get("points"):
                # 防冲板三种形式都是“有厚度的折线”：A-P-Q-B（圆弧形/焊接式）
                # 或两点直线（平板形），线宽 = 防冲板厚度，与正式程序画法一致。
                points = component["points"]
                path = QPainterPath()
                path.moveTo(float(points[0][0]), float(points[0][1]))
                for point in points[1:]:
                    path.lineTo(float(point[0]), float(point[1]))
                item = FoldedPlateItem(
                    path, self, kind=kind, label=COMPONENT_LABEL.get(kind, "防冲板"),
                    thickness=float(component.get("thickness") or 10.0),
                    color=IMPINGE_PEN_COLOR,
                )
                item.apply_selected(index in self.selected_components)
                item.component_index = index
                self.scene.addItem(item)
                self._component_items[index] = item
            elif kind in {"bypass", "center_baffle", "impingement", "impingement_folded", "slide"} and center:
                width, height = component.get("size", (40.0, 8.0))
                color = {
                    "bypass": BYPASS_COLOR,
                    "center_baffle": CENTER_BAFFLE_COLOR,
                    "impingement": IMPINGE_COLOR,
                    "impingement_folded": IMPINGE_COLOR,
                    "slide": SLIDE_COLOR,
                }[kind]
                plot = self._plot(center)
                rect = QRectF(plot[0] - width / 2, plot[1] - height / 2, width, height)
                item = ComponentRectItem(rect, self, kind=kind, label=COMPONENT_LABEL[kind], color=color)
                angle = float(component.get("angle") or 0.0)
                if abs(angle) > 1e-9:
                    # 板类元件按两参照管连线方向摆放（angle 为数学角度，屏幕顺时针为正）
                    item.setTransformOriginPoint(QPointF(plot[0], plot[1]))
                    item.setRotation(-angle)
                item.apply_selected(index in self.selected_components)
                item.component_index = index
                self.scene.addItem(item)
                self._component_items[index] = item
            elif kind == "radial_hole" and center:
                path = self._radial_hole_path(center)
                if path is not None:
                    item = RadialHoleItem(path, self)
                    item.component_index = index
                    item.apply_selected(index in self.selected_components)
                    self.scene.addItem(item)
                    self._component_items[index] = item

    def _radial_hole_path(self, center) -> QPainterPath | None:
        if self.result is None:
            return None
        cx, cy = self._plot(center)
        length = math.hypot(cx, cy)
        if length < 1e-6:
            return None
        dx, dy = cx / length, cy / length
        nx, ny = -dy, dx
        r = self.result.small_r
        # 沿半径方向开口：以管孔中心为顶点，向外张开的楔形（正式程序径向开孔的简化几何）
        path = QPainterPath()
        path.moveTo(cx + nx * r, cy + ny * r)
        path.lineTo(cx + dx * r * 2.2, cy + dy * r * 2.2)
        path.lineTo(cx - nx * r, cy - ny * r)
        path.closeSubpath()
        return path

    # ------------------------------------------------------ 数量表同步
    def _groupings(self) -> None:
        if self.result is None:
            return
        master = self.result.master_centers
        centers = self.current_centers()
        self._rows_pos, self._rows_neg = geometry.group_centers_by_y(centers, master)
        self._cols_right, self._cols_left = geometry.group_centers_by_x(centers, master)

    def refresh_hole_table(self) -> None:
        if self.result is None:
            return
        self._groupings()
        if self.hole_table.by_row:
            first, second = self._rows_pos, self._rows_neg
        else:
            first, second = self._cols_right, self._cols_left
        self.hole_table.set_data(first, second, total=len(self.current_centers()))
        self.hole_table.set_selected_count(len(self.selected))
        # 表格重建后把“图形里仍选中的管孔”对应的行重新高亮
        self._sync_table_highlight()
        self.selection_label.setText(self._selection_text())
        self.selected_count_changed.emit(len(self.selected))

    def on_table_rows_selected(self, rows: list[int]) -> None:
        if self.result is None:
            return
        if self.hole_table.by_row:
            first, second = self._rows_pos, self._rows_neg
        else:
            first, second = self._cols_right, self._cols_left
        centers: list[tuple[float, float]] = []
        for row in rows:
            if row < len(first):
                centers.extend(first[row])
            if row < len(second):
                centers.extend(second[row])
        self.select_centers(centers)
        if centers:
            self.status_message.emit(
                f"已选中{_describe_rows(rows)}，共 {len(self.selected)} 个换热管孔"
            )
        else:
            self.status_message.emit("已取消筛选，恢复显示全部管孔")

    def select_centers(self, centers: list[tuple[float, float]], additive: bool = False) -> None:
        if not additive:
            for center, item in self._tube_items.items():
                if item.is_selected:
                    item.apply_selected(False)
            for center, item in self._ghost_items.items():
                if item.is_selected:
                    item.apply_selected(False)
            for index in list(self.selected_components):
                other = self._component_items.get(index)
                if other is not None:
                    other.apply_selected(False)
            self.selected_components.clear()
            self._clear_selection_state()
        for center in centers:
            if center in self._tube_items:
                self.selected.add(center)
                self._tube_items[center].apply_selected(True)
            elif center in self._ghost_items:
                self.selected.add(center)
                self._ghost_items[center].apply_selected(True)
        self._after_selection_changed()

    def _selection_text(self) -> str:
        """底部选中提示：照正式程序，1 个给绝对坐标、2 个给中心距。"""
        if not self.selected:
            return "未选中管孔"
        deleted = sum(1 for center in self.selected if center in self._ghost_items)
        suffix = f"（含 {deleted} 个已删除管孔）" if deleted else ""
        if len(self.selected) == 1:
            (x, y), = self.selected
            return f"已选中 1 个管孔  X {float(x):.1f}  Y {float(y):.1f}{suffix}"
        if len(self.selected) == 2:
            (x1, y1), (x2, y2) = sorted(self.selected)
            span = math.hypot(float(x2) - float(x1), float(y2) - float(y1))
            return f"已选中 2 个管孔，中心距 {span:.1f} mm{suffix}"
        return f"已选中 {len(self.selected)} 个管孔{suffix}"

    def _clear_selection_state(self) -> None:
        self.selected.clear()
        self.selected_components.clear()

    def _after_selection_changed(self) -> None:
        self._sync_table_highlight()
        self.hole_table.set_selected_count(len(self.selected))
        self.selection_label.setText(self._selection_text())
        self.selected_count_changed.emit(len(self.selected))

    def _sync_table_highlight(self) -> None:
        if not self.selected:
            self.hole_table.highlight_for_selection([])
            return
        if self.hole_table.by_row:
            first, second = self._rows_pos, self._rows_neg
        else:
            first, second = self._cols_right, self._cols_left
        rows: list[int] = []
        for index in range(max(len(first), len(second))):
            group = []
            if index < len(first):
                group.extend(first[index])
            if index < len(second):
                group.extend(second[index])
            if any(center in self.selected for center in group):
                rows.append(index)
        self.hole_table.highlight_for_selection(rows)

    # ------------------------------------------------------ 图形交互
    def item_clicked(self, item, modifiers) -> None:
        """单击换热管 / 普通拉杆：**切换**该点的选中状态，且不动其它已选点。

        正式程序 `ClickableCircleItem.mousePressEvent` 里就是 `selected_centers` 的
        增/删切换（普通拉杆与换热管同等对待，见 My_Piping.py 947~1005），没有
        “点第二个把第一个顶掉”的逻辑；框选/表格筛选才是整批替换。
        其它元件（自由拉杆、挡管、挡板、防冲板…）同样累加多选，方便一次删掉几个。
        """
        kind = getattr(item, "item_kind", "")
        if kind in {"tube", "rod"}:
            center = item.center
            deleted = center in self._ghost_items
            if center in self.selected:
                self.selected.discard(center)
                item.apply_selected(False)
            else:
                self.selected.add(center)
                item.apply_selected(True)
            self._after_selection_changed()
            if deleted:
                self.status_message.emit(
                    f"已选中 {len(self.selected)} 个已删除管孔（可让我“恢复选中的换热管”）"
                )
            return
        index = getattr(item, "component_index", None)
        if index is not None:
            if index in self.selected_components:
                self.selected_components.discard(index)
                item.apply_selected(False)
            else:
                self.selected_components.add(index)
                item.apply_selected(True)
            label = COMPONENT_LABEL.get(self.components[index]["kind"], "元件")
            if self.selected_components:
                self.status_message.emit(
                    f"已选中 {label}（共 {len(self.selected_components)} 个元件），"
                    "可点击“删除”移除，右键清空"
                )
            else:
                self.status_message.emit("已取消元件选中")

    def item_double_clicked(self, item) -> None:
        """双击已布置元件时打开对应参数弹窗并更新图形。"""
        index = getattr(item, "component_index", None)
        if index is None or not 0 <= index < len(self.components):
            return
        self.edit_component(index)

    def edit_component(self, index: int) -> None:
        if not 0 <= index < len(self.components):
            return
        component = self.components[index]
        kind = component.get("kind", "")
        def is_flat(values: dict) -> bool:
            return values.get("防冲板形式", "平板形") == "平板形"

        def not_flat(values: dict) -> bool:
            return not is_flat(values)

        def is_welded(values: dict) -> bool:
            return values.get("防冲板形式") == "焊接式"

        def is_round_slide(values: dict) -> bool:
            return values.get("滑道形式") == "圆钢滑道"

        def show_slide_azimuth(values: dict) -> bool:
            return values.get("滑道形式") == "板式滑道" and values.get("滑道数量") == "1"

        is_kettle = self.product_type in {"AKU", "BKU"}
        impingement_fields = [
            ParamField("防冲板形式", "combo", ("平板形", "圆弧形", "焊接式")),
            ParamField("防冲板厚度", "number", unit="mm", minimum=0.1),
            ParamField(
                "放置位置", "combo", ("参照管顶部连线", "参照管中心连线"),
                visible=is_flat,
            ),
            ParamField(
                "防冲板折边角度", "number", unit="°", minimum=15, maximum=90,
                visible=not_flat,
            ),
            ParamField("防冲板宽度", "number", unit="mm", minimum=1.0,
                       visible=is_welded),
            ParamField("防冲板方位角", "number", unit="°", minimum=0,
                       maximum=359.9, visible=is_welded),
            ParamField("至圆筒内壁距离", "number", unit="mm", minimum=0.1,
                       visible=is_welded),
        ]
        fields_by_kind = {
            "rod": (
                "拉杆参数设置",
                [
                    ParamField("拉杆形式", "combo", ("焊接拉杆", "螺纹拉杆")),
                    ParamField("拉杆直径", "combo", TIE_ROD_DIAMETERS),
                ],
            ),
            "free_rod": (
                "自由拉杆参数设置",
                [ParamField("拉杆直径", "combo", TIE_ROD_DIAMETERS)],
            ),
            "block_tube": (
                "中间挡管参数设置",
                [ParamField("中间挡管安装方式", "combo", ("贯穿", "分割"))],
            ),
            "bypass": (
                "旁路挡板参数设置",
                [ParamField("旁路挡板厚度", "number", unit="mm", minimum=0.1)],
            ),
            "center_baffle": (
                "中间挡板参数设置",
                [
                    ParamField("中间挡板厚度", "number", unit="mm", minimum=0.1),
                    ParamField("中间挡板安装方式", "combo", ("贯穿", "分割")),
                ],
            ),
            "impingement": ("防冲板参数设置", impingement_fields),
            "impingement_folded": ("防冲板参数设置", impingement_fields),
            "impingement_welded": ("防冲板参数设置", impingement_fields),
            "slide": (
                "滑道参数设置",
                [
                    ParamField("滑道定位", "combo", ("固定管板", "第一块折流板或支持板")),
                    ParamField("滑道形式", "combo", ("板式滑道", "圆钢滑道")),
                    ParamField("滑道数量", "combo", ("1", "2")),
                    ParamField("滑道方位角", "number", unit="°",
                               visible=show_slide_azimuth),
                    ParamField("导轨类型", "combo", ("支撑导轨1", "支撑导轨2"),
                               visible=lambda _values: is_kettle),
                    ParamField("圆钢规格", "number", unit="mm", minimum=0.1,
                               visible=is_round_slide),
                    ParamField("滑道高度", "number", unit="mm", minimum=1.0,
                               visible=lambda values: not is_round_slide(values)),
                    ParamField("滑道厚度", "number", unit="mm", minimum=0.1,
                               visible=lambda values: not is_round_slide(values)),
                    ParamField("滑道与竖直中心线夹角", "number", unit="°",
                               visible=lambda values: is_round_slide(values)
                               or not show_slide_azimuth(values)),
                    ParamField("滑道切边长度", "number", unit="mm", minimum=0.0,
                               visible=lambda values: not is_round_slide(values)),
                    ParamField("滑道切边高度", "number", unit="mm", minimum=0.0,
                               visible=lambda values: not is_round_slide(values)),
                ],
            ),
            "screw_ring": (
                "吊环螺钉参数设置",
                [
                    ParamField("吊环螺钉规格", "combo", (
                        "M8", "M10", "M12", "M16", "M20", "M24", "M30", "M36",
                        "M42", "M48", "M56", "M64", "M72×6", "M80×6", "M100×6",
                    )),
                    ParamField("吊环螺钉数量", "number", unit="个", minimum=1, maximum=64),
                    ParamField("吊环螺钉孔中心距", "number", unit="mm", minimum=0.0),
                    ParamField("吊环螺钉起始方位角", "number", unit="°", minimum=0,
                               maximum=359.9),
                ],
            ),
        }
        config = fields_by_kind.get(kind)
        if config is None:
            return

        title, fields = config
        if kind in {"impingement", "impingement_folded", "impingement_welded"}:
            if not component.get("pair"):
                fields = [
                    ParamField("防冲板形式", "combo", ("焊接式",)),
                    *fields[1:],
                ]
        initial_values = dict(component.get("options") or {})
        if kind in {"impingement", "impingement_folded", "impingement_welded"}:
            initial_values.setdefault("防冲板形式", component.get("form") or {
                "impingement": "平板形",
                "impingement_folded": "圆弧形",
                "impingement_welded": "焊接式",
            }[kind])
        values = self._ask(title, fields, initial_values=initial_values)
        if values is None:
            return

        replacement = None
        if kind in {"impingement", "impingement_folded", "impingement_welded"}:
            form = str(values.get("防冲板形式") or "平板形").strip()
            pair = component.get("pair")
            if form != impingement.FORM_WELDED and not pair:
                self._warn("无法编辑防冲板", "缺少原始参照管信息，请删除后重新布置。")
                return
            try:
                replacement = self._impingement_geometry(form, pair, values)
            except impingement.ImpingementError as exc:
                self._warn("防冲板参数异常", str(exc))
                return
        center_baffle_side = None
        if kind == "center_baffle":
            pair = component.get("pair")
            if not pair:
                self._warn("无法编辑中间挡板", "缺少原始参照管信息，请删除后重新布置。")
                return
            center_baffle_side, reason = self._center_baffle_check(pair)
            if reason:
                self._warn("无法编辑中间挡板", reason)
                return
        elif kind == "bypass" and not component.get("anchor"):
            self._warn("无法编辑旁路挡板", "缺少原始参照管信息，请删除后重新布置。")
            return

        self._push_undo()
        self._write_back(values)
        if kind in {"impingement", "impingement_folded", "impingement_welded"}:
            self.removed.difference_update(component.get("deleted") or [])
            self._apply_impingement_deletions(
                replacement,
                replacement["form"],
                replacement.get("pair"),
                component.get("rod_deleted") or [],
            )
            self.components[index] = replacement
        elif kind == "center_baffle":
            pair = component["pair"]
            replacement = self._pair_geometry(kind, pair, center_baffle_side)
            replacement.update(kind=kind, options=dict(values))
            self.components[index] = replacement
        elif kind == "bypass":
            replacement = self._bypass_geometry(component["anchor"])
            replacement.update(
                kind=kind, anchor=component["anchor"], options=dict(values)
            )
            self.components[index] = replacement
        elif kind == "slide":
            self.components = [c for c in self.components if c.get("kind") != "slide"]
            self.components.extend(
                dict(item, kind="slide", options=dict(values))
                for item in self._slide_geometries()
            )
        elif kind == "screw_ring":
            self.components = [c for c in self.components if c.get("kind") != "screw_ring"]
            self.components.extend(
                dict(item, kind="screw_ring", options=dict(values))
                for item in self._screw_ring_geometries(
                    int(float(values.get("吊环螺钉数量") or 1))
                )
            )
        else:
            component["options"] = dict(values)

        self.rebuild_scene()
        self.refresh_hole_table()
        self.status_message.emit(f"已更新{COMPONENT_LABEL.get(kind, '元件')}参数")

    def on_rubber_band(self, rect: QRectF) -> None:
        picked = [
            center for center in list(self._tube_items) + list(self._ghost_items)
            if rect.contains(QPointF(center[0], -center[1]))
        ]
        if not picked:
            return
        additive = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
        self.select_centers(picked, additive=additive)
        self.status_message.emit(f"框选到 {len(picked)} 个换热管孔，共选中 {len(self.selected)} 个")

    def clear_selection(self) -> None:
        """右键取消筛选：清掉表格选中行、图形选中与元件选中（正式程序同款）。"""
        had_selection = bool(self.selected) or bool(self.selected_components)
        for item in self._tube_items.values():
            if item.is_selected:
                item.apply_selected(False)
        for item in self._ghost_items.values():
            if item.is_selected:
                item.apply_selected(False)
        self._clear_selection_state()
        for index, item in self._component_items.items():
            item.apply_selected(False)
        self.selected_components.clear()
        self.hole_table.clear_selection()
        self.hole_table.set_selected_count(0)
        self._after_selection_changed()
        self.status_message.emit(
            "已取消筛选，恢复显示全部管孔" if had_selection else "当前没有筛选/选中的管孔"
        )

    # ------------------------------------------------------ 元件操作
    def _require_selection(self) -> list[tuple[float, float]]:
        if not self.selected:
            self._warn("请先选择", "请先在图形中选中换热管孔（普通拉杆也能当参照管）。", kind="info")
            return []
        return sorted(self.selected)

    def _push_undo(self) -> None:
        self._undo.append({
            "removed": set(self.removed),
            "components": deepcopy(self.components),
            "params": deepcopy(self.parameters),
        })
        if len(self._undo) > 30:
            self._undo.pop(0)

    def undo(self) -> None:
        if not self._undo:
            self.status_message.emit("没有可撤销的操作")
            return
        state = self._undo.pop()
        self.removed = set(state["removed"])
        self.components = deepcopy(state["components"])
        self.parameters = deepcopy(state["params"])
        self._clear_selection_state()
        self.selected_components.clear()
        self.rebuild_parameter_table()
        self.recompute(reason="已撤销上一步", keep_components=True)
        self.status_message.emit("已撤销上一步操作")

    def _param_text(self, name: str) -> str:
        return str(self.parameters.get(name, {}).get("value", "") or "").strip()

    def _ask(
        self, title: str, fields: list[ParamField], hint: str = "",
        initial_values: dict | None = None,
    ) -> dict | None:
        """布置元件前弹窗确认参数（正式程序同款）；离屏自检时直接取当前值。"""
        values = {spec.name: self._param_text(spec.name) for spec in fields}
        values.update(initial_values or {})
        if self.headless:
            return values
        return ask_component_params(title, fields, values, hint=hint, parent=self)

    def _write_back(self, values: dict) -> None:
        for name, value in values.items():
            if name in self.parameters and str(self.parameters[name].get("value", "")) != str(value):
                self.set_parameter(name, value, "人工修改", run_linkage=False)

    def _pairs_from_centers(self, centers, what: str, required: int = 2) -> list[tuple]:
        """把选中的点两两成组（正式程序“选 2 个换热管/拉杆”的等价做法）。

        正式程序里防冲板/中间挡板/中间挡管都只认**恰好 2 个**选点
        （impingement_plate.on_dangban_click 校验 `len(selected_centers) not in (0, 2)`，
        否则 `QMessageBox.warning(self, "提示", "选择换热管的数量不正确！")`），
        而且普通拉杆和换热管一样可以当参照点，所以这里不做“必须成对”的额外限制。
        """
        if not centers:
            return []
        ordered = sorted(centers, key=lambda c: (-round(c[1], 3), c[0]))
        if len(ordered) != required:
            self._warn("提示", "选择换热管的数量不正确！")
            return []
        return [(tuple(ordered[0]), tuple(ordered[1]))]

    def _require_pairs(self, what: str) -> list[tuple]:
        """板类/挡管要求“选中 2 个换热管”（正式程序 on_dangban_click 等）。"""
        return self._pairs_from_centers(self._require_selection(), what)

    def _symmetry_pair_partners(self, pair) -> list[tuple]:
        """对称分布时，一对参照管还要在另一侧补一对（照抄 center_dangguan 的判轴规则）。

        正式程序 component/center_dangguan.py 的对称扩展：中点在 y 轴上（|x|≈0）就关于
        x 轴对称 (x, −y)，否则关于 y 轴对称 (−x, y)。镜像点必须也是真实管孔，
        否则不补（同 `actual_to_selected_coords` 返回空即丢弃）。
        """
        if not self._symmetry or not pair:
            return []
        (x1, y1), (x2, y2) = pair
        if abs((x1 + x2) / 2.0) < 1e-6:
            candidate = [(x1, -y1), (x2, -y2)]
        else:
            candidate = [(-x1, y1), (-x2, y2)]
        pool = {tuple(c) for c in self.current_centers()}
        if all(tuple(c) in pool for c in candidate):
            return [(tuple(candidate[0]), tuple(candidate[1]))]
        return []

    def _symmetry_pairs(self, pairs) -> list[tuple]:
        """一对参照管按“对称分布”补出另一侧的一对（挡管/挡板通用）。

        正式程序 `center_dangban.on_center_dangban_click` / `build_center_dangguan`
        在勾选对称分布时都先对选点做 `judge_linkage_x/y`：一对参照管在槽的另一侧
        再落一块（挡板）/一根（挡管）。落点仍由真实管孔算出，不编造坐标。
        """
        out: list[tuple] = []
        seen: set = set()
        for pair in pairs or []:
            for one in [tuple(pair), *self._symmetry_pair_partners(pair)]:
                key = tuple(sorted((round(p[0], 6), round(p[1], 6)) for p in one))
                if key in seen:
                    continue
                seen.add(key)
                out.append(tuple(one))
        return out

    def place_rod(self, free: bool = False) -> None:
        centers = self._require_selection()
        if not centers:
            return
        fields = [
            ParamField("拉杆形式", "combo", ("焊接拉杆", "螺纹拉杆")),
            ParamField("拉杆直径", "combo", TIE_ROD_DIAMETERS),
        ]
        # 提示文案照正式程序拉杆弹窗里的那句（按公称直径/拉杆直径查标准表）
        standard = self._param_text("拉杆数量")
        hint = (
            f"根据标准要求，拉杆数量不应小于 {standard} 根"
            if str(standard).strip()
            else "当前拉杆直径无拉杆数量标准要求"
        )
        values = self._ask("拉杆参数设置", fields, hint)
        if values is None:
            return
        self._write_back(values)
        do = self._float("换热管外径 do") or 25.0
        rod_d = self._float("拉杆直径") or 16.0
        if rod_d > do + 1e-6:
            # 拉杆是占一个换热管孔位画的，直径不可能大于管孔
            self._warn(
                "拉杆直径无效",
                f"拉杆直径 {rod_d:g} 大于换热管外径 do={do:g}，无法穿入管孔。",
            )
            return

        # 正式程序 on_lagan_click：种子管 → isSymmetry ? judge_linkage(4 象限)
        # : 按管程程数 judge_linkage_x/y（2 管程左右镜像、4/6 管程上下镜像）
        known = set(self.current_centers())
        placed = [c for c in self._linkage_expand(centers) if c in known]
        if not placed:
            placed = [c for c in centers if c in known]
        self._push_undo()
        for center in placed:
            self.removed.add(center)
            self.components.append({
                "kind": "free_rod" if free else "rod",
                "center": center,
                "options": dict(values),
            })
        self._clear_selection_state()
        self.rebuild_scene()
        self.refresh_hole_table()
        mode = "对称分布展开" if self._symmetry else "按管程镜像"
        self.status_message.emit(
            f"已按{mode}布置 {len(placed)} 根{'自由拉杆' if free else '拉杆'}，管孔数量已更新"
        )

    def place_block_tube(self) -> None:
        pairs = self._require_pairs("中间挡管")
        if not pairs:
            return
        # 正式程序 prompt_center_dangguan_params：弹窗里只有“安装方式”一项
        values = self._ask(
            "中间挡管参数设置",
            [ParamField("中间挡管安装方式", "combo", ("贯穿", "分割"))],
        )
        if values is None:
            return
        self._write_back(values)
        self._push_undo()
        added = 0
        # 正式程序 build_center_dangguan：每对参照管给出一个挡管位置（连线与隔板槽轴线的
        # 交点）；对称分布勾选时另一侧再补一根
        for pair in self._symmetry_pairs(pairs):
            point, error = self._block_tube_point(pair)
            if error:
                self._warn("提示", error)
                self._undo.pop()
                return
            if not self._is_midpoint(point, pair):
                if not self._ask_yes_no("提示", "所选参照管连线非水平线，是否继续？"):
                    continue
            if abs(point[0]) < 1e-6 and abs(point[1]) < 1e-6:
                continue
            if point in self.removed:
                continue
            self.removed.add(point)
            self.components.append({
                "kind": "block_tube", "center": point, "options": dict(values)
            })
            added += 1
        self._clear_selection_state()
        self.rebuild_scene()
        self.refresh_hole_table()
        self.status_message.emit(f"已布置 {added} 个中间挡管（落在分程隔板槽上）")

    def place_plate(self, kind: str) -> None:
        if kind == "bypass":
            centers = self._require_selection()
            if not centers:
                return
        else:
            pairs = self._require_pairs(COMPONENT_LABEL.get(kind, "挡板"))
            if not pairs:
                return
        if kind == "bypass":
            values = self._ask(
                "旁路挡板参数设置",
                [ParamField("旁路挡板厚度", "number", unit="mm", minimum=0.1)],
            )
        else:
            values = self._ask(
                "中间挡板参数设置",
                [
                    ParamField("中间挡板厚度", "number", unit="mm", minimum=0.1),
                    ParamField("中间挡板安装方式", "combo", ("贯穿", "分割")),
                ],
            )
        if values is None:
            return
        self._write_back(values)
        self._push_undo()
        placed = 0
        if kind == "bypass":
            # 正式程序 side_dangban.on_side_block_click：勾选对称分布时按 judge_linkage
            # 展开成 4 块，每个参照管沿折流板切口方向各生成一块，外边缘贴着折流板外径圆
            targets = self._linkage_expand(centers) if self._symmetry else centers
            widths = []
            for center in targets:
                geometry = self._bypass_geometry(center)
                widths.append(max(float(v) for v in geometry["size"]))
                self.components.append(
                    dict(geometry, kind="bypass", options=dict(values))
                )
            placed = len(targets)
            if widths:
                self.set_parameter(
                    "旁路挡板宽度", self._pretty(widths[0]), "人工布置", run_linkage=False
                )
        else:
            # 正式程序 center_dangban：先按“隔板槽两侧第一排”校验，两块参照管之间夹
            # 一块，长度取两管中心距 − do − 2×孔桥宽度；勾选对称分布时另一侧再补一块
            for pair in self._symmetry_pairs(pairs):
                side, reason = self._center_baffle_check(pair)
                if reason:
                    self._warn("只允许对分程挡板两侧的换热管建立中间挡板！", reason)
                    self._undo.pop()
                    return
                self.components.append(dict(
                    self._pair_geometry("center_baffle", pair, side),
                    kind="center_baffle",
                    options=dict(values),
                ))
                placed += 1
        self._clear_selection_state()
        self.rebuild_scene()
        self.status_message.emit(f"已布置 {placed} 个{COMPONENT_LABEL[kind]}")

    def place_slide(self) -> None:
        # 正式程序 slipway.on_green_slide_click：滑道不选换热管，完全按参数定位
        is_kettle = self.product_type in {"AKU", "BKU"}

        def is_round(values: dict) -> bool:
            return values.get("滑道形式") == "圆钢滑道"

        def show_azimuth(values: dict) -> bool:
            return values.get("滑道形式") == "板式滑道" and values.get("滑道数量") == "1"

        fields = [
            ParamField("滑道定位", "combo", ("固定管板", "第一块折流板或支持板")),
            ParamField("滑道形式", "combo", ("板式滑道", "圆钢滑道")),
            ParamField("滑道数量", "combo", ("1", "2")),
            ParamField("滑道方位角", "number", unit="°", visible=show_azimuth),
            ParamField("导轨类型", "combo", ("支撑导轨1", "支撑导轨2"), visible=lambda _v: is_kettle),
            ParamField("圆钢规格", "number", unit="mm", minimum=0.1, visible=is_round),
            ParamField("滑道高度", "number", unit="mm", minimum=1.0,
                       visible=lambda v: not is_round(v)),
            ParamField("滑道厚度", "number", unit="mm", minimum=0.1,
                       visible=lambda v: not is_round(v)),
            ParamField("滑道与竖直中心线夹角", "number", unit="°",
                       visible=lambda v: is_round(v) or not show_azimuth(v)),
            ParamField("滑道切边长度", "number", unit="mm", minimum=0.0,
                       visible=lambda v: not is_round(v)),
            ParamField("滑道切边高度", "number", unit="mm", minimum=0.0,
                       visible=lambda v: not is_round(v)),
        ]
        # 正式程序滑道弹窗只有 11 个参数行，没有任何说明文字
        values = self._ask("滑道参数设置", fields)
        if values is None:
            return
        self._write_back(values)
        self._push_undo()
        geometries = self._slide_geometries()
        for geometry in geometries:
            self.components.append(dict(geometry, kind="slide", options=dict(values)))
        self.rebuild_scene()
        self.status_message.emit(
            f"已布置 {len(geometries)} 条滑道（按方位角/夹角沿壳体内壁，不占管孔）"
        )

    def place_impingement(self) -> None:
        centers = sorted(self.selected)

        def is_flat(values: dict) -> bool:
            return values.get("防冲板形式", "平板形") == "平板形"

        def not_flat(values: dict) -> bool:
            return values.get("防冲板形式", "平板形") != "平板形"

        def is_welded(values: dict) -> bool:
            return values.get("防冲板形式") == "焊接式"

        fields = [
            ParamField("防冲板形式", "combo", ("平板形", "圆弧形", "焊接式")),
            ParamField("防冲板厚度", "number", unit="mm", minimum=0.1),
            ParamField("放置位置", "combo", ("参照管顶部连线", "参照管中心连线"),
                       visible=is_flat),
            ParamField("防冲板折边角度", "number", unit="°", minimum=15, maximum=90,
                       visible=not_flat),
            ParamField("防冲板宽度", "number", unit="mm", minimum=1.0, visible=is_welded),
            ParamField("防冲板方位角", "number", unit="°", minimum=0, maximum=359.9,
                       visible=is_welded),
            ParamField("至圆筒内壁距离", "number", unit="mm", minimum=0.1, visible=is_welded),
        ]
        # 正式程序弹窗只有参数，不放注意事项；选中数量在标题里点明即可
        values = self._ask("防冲板参数设置", fields)
        if values is None:
            return
        self._write_back(values)

        form = str(values.get("防冲板形式") or "平板形").strip()
        placed: list[tuple[dict, list | None]] = []
        details: list[str] = []
        if form == impingement.FORM_WELDED:
            # 焊接式不依附管孔（正式程序同一入口允许 0 个选点）
            try:
                geometry = self._impingement_geometry(form)
            except impingement.ImpingementError as exc:
                self._warn("防冲板参数异常", str(exc))
                return
            placed.append((geometry, None))
            details.append(
                f"方位角 {geometry.get('azimuth', 0):g}°、板宽 {geometry.get('width', 0):.1f}"
            )
        else:
            # 正式程序：len(selected_centers) 不是 2 就直接提示“选择换热管的数量不正确！”
            if len(centers) != 2:
                self._warn("提示", "选择换热管的数量不正确！")
                return
            pairs = self._pairs_from_centers(centers, "防冲板")
            if not pairs:
                return
            for pair in pairs:
                try:
                    geometry = self._impingement_geometry(form, pair)
                except impingement.ImpingementError as exc:
                    self._warn("防冲板参数异常", str(exc))
                    continue
                placed.append((geometry, pair))
                if form == impingement.FORM_FOLDED:
                    details.append(
                        f"折边高 {geometry['height']:g}、顶部 {geometry['top_length']:.1f}"
                    )
                else:
                    details.append(f"板长 {geometry['width']:.1f}")
        if not placed:
            return

        self._push_undo()
        deleted_total = 0
        deleted_rods_total = 0
        for geometry, pair in placed:
            # 正式程序 build_impingement_plate：落位后立刻删掉干涉换热管（含弦外弓形区）
            deleted_count, deleted_rod_count = self._apply_impingement_deletions(
                geometry, form, pair
            )
            deleted_total += deleted_count
            deleted_rods_total += deleted_rod_count
            self.components.append(geometry)
        self._clear_selection_state()
        self.rebuild_scene()
        self.refresh_hole_table()
        extra = f"，同时删掉 {deleted_total} 个干涉换热管" if deleted_total else ""
        if deleted_rods_total:
            extra += f"，同时删除 {deleted_rods_total} 根干涉拉杆"
        self.status_message.emit(
            f"已布置 {len(placed)} 块{form}防冲板（{'；'.join(details)}）{extra}"
        )

    def place_screw_ring(self) -> None:
        values = self._ask(
            "吊环螺钉参数设置",
            [
                ParamField("吊环螺钉规格", "combo", (
                    "M8", "M10", "M12", "M16", "M20", "M24", "M30", "M36",
                    "M42", "M48", "M56", "M64", "M72×6", "M80×6", "M100×6",
                )),
                ParamField("吊环螺钉数量", "number", unit="个", minimum=1, maximum=64),
                ParamField("吊环螺钉孔中心距", "number", unit="mm", minimum=0.0),
                ParamField("吊环螺钉起始方位角", "number", unit="°", minimum=0, maximum=359.9),
            ],
        )
        if values is None:
            return
        self._write_back(values)
        quantity = int(self._float("吊环螺钉数量") or 4)
        self._push_undo()
        for geometry in self._screw_ring_geometries(quantity):
            self.components.append(
                dict(geometry, kind="screw_ring", options=dict(values))
            )
        self.rebuild_scene()
        self.status_message.emit(f"已布置 {quantity} 个吊环螺钉（沿管板外圆均布）")

    def place_baffle(self) -> None:
        if self.result is None:
            return

        def double_bow(values: dict) -> bool:
            return values.get("折流板类型") == "双弓形"

        fields = [
            ParamField("折流/支持板外径", "number", unit="mm", minimum=1.0),
            ParamField("折流/支持板间距", "number", unit="mm", minimum=1.0),
            ParamField("折流板类型", "combo", ("单弓形", "双弓形", "支持板")),
            ParamField("折流板切口方向", "combo", ("水平上下", "垂直左右")),
            ParamField("折流板要求切口率", "number", unit="%", minimum=10, maximum=45),
            ParamField("折流板切口与中心线间距a", "number", unit="mm", minimum=0.0),
            ParamField("弓形弦高切口率", "number", unit="%", minimum=0.0, maximum=100.0,
                       visible=double_bow),
            ParamField("内侧中心切口率", "number", unit="%", minimum=0.0, maximum=100.0,
                       visible=double_bow),
            ParamField("A型板切口与中心线间距a", "number", unit="mm", minimum=0.0,
                       visible=double_bow),
            ParamField("B型板切口与中心线间距b", "number", unit="mm", minimum=0.0,
                       visible=double_bow),
        ]
        values = self._ask("折流板参数设置", fields)
        if values is None:
            return
        self._write_back(values)
        self.recompute(reason="折流板参数已确认", keep_components=True)
        spacing = self._float("折流/支持板间距") or 200.0
        self.status_message.emit(
            f"折流板已按 折流/支持板外径 {self.result.baffle_r * 2:g}、间距 {spacing:g} 绘制"
            "（外径虚线圆 + 切口弦线），"
            "布置数量由 轴向设计 页确认"
        )

    def place_radial_hole(self) -> None:
        centers = self._require_selection()
        if not centers:
            return
        self._push_undo()
        for center in centers:
            self.components.append({"kind": "radial_hole", "center": center})
        self._clear_selection_state()
        self.rebuild_scene()
        self.status_message.emit(f"已在 {len(centers)} 个管孔位置开径向孔")

    def restore_tubes(self) -> None:
        if not self.removed:
            self.status_message.emit("当前没有被删除的管孔")
            return
        self._push_undo()
        restored = len(self.removed)
        self.removed.clear()
        self.components = [
            c for c in self.components
            if c["kind"] not in {"rod", "free_rod", "block_tube"}
        ]
        self.rebuild_scene()
        self.refresh_hole_table()
        self.status_message.emit(f"已恢复 {restored} 个换热管孔")

    def delete_selected(self) -> None:
        """删除选中：先按“对称分布”把选点展开，再删拉杆/挡管图元与换热管。

        照抄正式程序 `on_del_click`：勾选了对称分布就按 4 象限展开（未勾选时按
        管程程数做单轴镜像），拉杆/挡管这些占孔元件在正式程序里也是先删图元、
        再把对应的换热管删掉（component/lagan.delete_selected_lagans 末尾
        `delete_huanreguan(coords_to_remove)`）。
        """
        if self.selected:
            self._push_undo()
            targets = self._linkage_expand(sorted(self.selected))
            target_set = set(targets)
            kept: list[dict] = []
            removed_components = 0
            for component in self.components:
                center = component.get("center")
                if (
                    component.get("kind") in {"rod", "free_rod", "block_tube"}
                    and center
                    and (float(center[0]), float(center[1])) in target_set
                ):
                    removed_components += 1
                    continue
                kept.append(component)
            self.components = kept
            # 元件删掉后它们原来的孔位又被放出来了：这些点按“删孔”处理
            self.removed |= target_set
            self._clear_selection_state()
            self.selected_components.clear()
            self.rebuild_scene()
            self.refresh_hole_table()
            extra = f"（含 {removed_components} 个拉杆/挡管图元）" if removed_components else ""
            self.status_message.emit(
                f"已删除 {len(target_set)} 个管孔{extra}，管孔数量已刷新"
            )
            return
        if self.selected_components:
            self._push_undo()
            kept = []
            labels = []
            for index, component in enumerate(self.components):
                if index in self.selected_components:
                    if (
                        component["kind"] in {"rod", "free_rod", "block_tube"}
                        and component.get("center")
                    ):
                        self.removed.discard(tuple(component["center"]))
                    labels.append(COMPONENT_LABEL.get(component["kind"], "元件"))
                    continue
                kept.append(component)
            self.components = kept
            self.selected_components.clear()
            self.rebuild_scene()
            self.refresh_hole_table()
            self.status_message.emit(f"已删除 {len(labels)} 个元件（{'、'.join(labels)}）")
            return
        self.status_message.emit("请先选择要删除的管孔或元件")

    def toggle_fullscreen(self) -> None:
        """请求主窗口放大整个布管预览窗格，而非进入系统全屏。"""
        self.set_pane_fullscreen(not self.graphics_expanded)

    def set_pane_fullscreen(self, enabled: bool, notify: bool = True) -> None:
        """放大预览窗格时只保留中间布管图；退出后恢复两侧表格。"""
        self.graphics_expanded = bool(enabled)
        self.left_frame.setVisible(not self.graphics_expanded)
        self.right_frame.setVisible(not self.graphics_expanded)
        self.body_layout.setStretch(0, 0 if self.graphics_expanded else 30)
        self.body_layout.setStretch(1, 1 if self.graphics_expanded else 50)
        self.body_layout.setStretch(2, 0 if self.graphics_expanded else 20)
        if self.fullscreen_button is not None:
            self.fullscreen_button.setText("退出全屏" if self.graphics_expanded else "全屏")
        self.body_layout.invalidate()
        self.body_layout.activate()
        if notify:
            self.pane_fullscreen_requested.emit(self.graphics_expanded)
        self.view.fit_all()
        # 等待主窗口完成上下窗格切换后再适配一次。
        QTimer.singleShot(0, self.view.fit_all)

    # ------------------------------------------------------ 校验与摘要
    def show_issues(self) -> None:
        for row, name in enumerate(PARAM_ORDER):
            self._paint_param_row(row, name)
        self._clear_recommendations()
        if not self.issues:
            self.issue_frame.hide()
            self.keep_button.setEnabled(True)
            return
        lines = []
        for issue in self.issues:
            text = f"• {issue['field']}：{issue['message']}"
            if issue.get("recommended") is not None:
                text += f"（推荐 {issue['recommended']}）"
            lines.append(text)
        self.issue_list.setText("\n".join(lines))
        self.issue_title.setText(f"需要修改 · {len(self.issues)} 项")
        for issue in self.issues:
            if issue.get("recommended") is None:
                continue
            button = QPushButton(f"{issue['field']} 采用 {issue['recommended']}")
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(
                "QPushButton{background:#fff;border:1px solid #e0b4b0;border-radius:6px;"
                "padding:4px 10px;color:#9b2c2c;font-size:9pt;}"
                "QPushButton:hover{background:#fff0ee;}"
            )
            button.clicked.connect(
                lambda _checked=False, field=issue["field"], value=issue["recommended"]: self.apply_recommendation(field, value)
            )
            self.recommend_box.addWidget(button)
        self.issue_frame.show()
        self.keep_button.setEnabled(False)

    def _clear_recommendations(self) -> None:
        """清掉上一次的“采用推荐值”按钮，避免重复累积。"""
        for index in reversed(range(self.recommend_box.count())):
            item = self.recommend_box.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget is not None:
                self.recommend_box.takeAt(index)
                widget.setParent(None)
                widget.deleteLater()

    def apply_recommendation(self, field: str, value) -> None:
        if field not in self.parameters:
            return
        self.set_parameter(field, str(value), "采用推荐值")
        self.recompute(reason=f"已采用 {field} 推荐值 {value}")

    def _update_lagan_summary(self) -> None:
        rods = sum(1 for c in self.components if c["kind"] in {"rod", "free_rod"})
        required = self._float("拉杆数量") or 0
        self.lagan_summary.setText(
            f"拉杆标准要求数量{int(required) if required else '-'}  已有数量{rods}"
        )

    def _update_divider_correction_tip(self, result: engine.LayoutResult) -> None:
        self.divider_correction_tip.clear()
        self.divider_correction_tip.setVisible(False)
        form = self._param_text("管程分程形式")
        if not is_local_tube_pass_cat(form):
            return

        param_map = {
            name: str(row.get("value") or self.defaults.get(name, "")).strip()
            for name, row in self.parameters.items()
        }
        param_map["换热管排列方式"] = canonical_tube_arrangement(
            param_map.get("换热管排列方式", "")
        )
        D = result.input_json.get("LB_DL") or result.raw.get("DL")
        d = result.input_json.get("LB_TubeD")
        DN = result.input_json.get("LB_DN")
        try:
            local = run_local_tube_layout(
                form, param_map, D=float(D), d=float(d), DN=float(DN)
            )
        except (TypeError, ValueError) as exc:
            self.divider_correction_tip.setText(f"隔条尺寸修正提示计算失败：{exc}")
            self.divider_correction_tip.setVisible(True)
            return

        tip = local["divider_corrections"].get("tip", "").strip()
        if tip:
            self.divider_correction_tip.setText(tip)
            self.divider_correction_tip.setVisible(True)

    # ------------------------------------------------------ 对外数据
    def validation_issues(self) -> list[dict]:
        return list(self.issues)

    def to_payload(self) -> dict:
        components: dict[int, list] = {kind: [] for kind in range(11)}
        for component in self.components:
            kind = component["kind"]
            if kind == "radial_hole":
                continue
            component_type = COMPONENT_KIND_TO_TYPE.get(kind)
            if component_type is None:
                continue
            center = component.get("center")
            if center:
                coord = (round(center[0], 6), round(center[1], 6))
                if coord not in components[component_type]:
                    components[component_type].append(coord)
        components[7] = [(round(x, 6), round(y, 6)) for x, y in sorted(self.removed)]
        quantity_rows = []
        if self.result is not None:
            self._groupings()
            first, second = self._rows_pos, self._rows_neg
            for index in range(max(len(first), len(second))):
                rows_a = len(first[index]) if index < len(first) else 0
                rows_b = len(second[index]) if index < len(second) else 0
                quantity_rows.append({"idx": index + 1, "a": rows_a, "b": rows_b, "r": ""})
        return {
            "parameters": deepcopy(self.parameters),
            "components": components,
            "input": dict(self.result.input_json) if self.result else {},
            "result": {k: str(v) for k, v in (self.result.summary if self.result else {}).items()},
            "quantity_rows": quantity_rows,
            "quantity_vertical": not (self.product_type in {"AEU", "BEU", "AKU", "BKU"}
                                      and str(self.parameters["管程程数"]["value"]) == "2"),
            "hole_count": len(self.current_centers()),
            "selected_count": len(self.selected),
        }

    def summary_lines(self) -> list[str]:
        if self.result is None:
            return ["尚未布管"]
        lines = [
            f"管孔总数 {len(self.current_centers())} 个（正式程序布管接口计算）",
            f"换热管中心距 S {self.result.S:g}，分程隔板相邻管中心距 SN {self.result.SN:g}",
            f"布管限定圆 DL {self.result.big_r_nei * 2:g}，折流/支持板外径 {self.result.baffle_r * 2:g}",
            f"已有拉杆 {sum(1 for c in self.components if c['kind'] in {'rod', 'free_rod'})} 根，"
            f"其他元件 {sum(1 for c in self.components if c['kind'] not in {'rod', 'free_rod'})} 个",
        ]
        if self.removed:
            lines.append(f"已删除/被元件占用的管孔 {len(self.removed)} 个")
        return lines

    # ------------------------------------------------------ Agent 可调用的受控操作
    def run_validation(self) -> list[dict]:
        """统一入口：几何 + 参数一致性校验，并刷新标红与推荐值。"""
        issues = engine.check_geometry(self.parameters, self.result)
        self.issues = issues
        self.show_issues()
        return list(issues)

    def max_tubes(self, target: int | None = None) -> dict:
        """尽量多布：按正式程序中心距依次尝试更小的 S，直到满足目标或达到极限。"""
        current_s = self._float("换热管中心距 S") or 32.0
        do = self._float("换热管外径 do") or 25.0
        original = self.parameters["换热管中心距 S"]["value"]
        best = None
        s = current_s
        while s > do + 1.5:
            self.set_parameter("换热管中心距 S", self._pretty(s), "AI 建议", run_linkage=False)
            try:
                result = engine.compute(self.parameters, self.product_type, self.defaults)
            except Exception:  # noqa: BLE001 - 试算失败换下一个中心距
                s -= 1.0
                continue
            issues = engine.check_geometry(self.parameters, result)
            if not issues:
                best = (s, len(result.master_centers))
                if target is None or best[1] >= target:
                    break
            s -= 1.0
        if best is None:
            self.set_parameter("换热管中心距 S", original, "AI 建议", run_linkage=False)
            return {"ok": False, "message": "当前参数下无法排布更多换热管"}
        self.set_parameter("换热管中心距 S", self._pretty(best[0]), "AI 建议", run_linkage=False)
        self.recompute(reason="尽量多布")
        return {"ok": True, "S": best[0], "count": best[1]}

    def place_edge_rods(self, count: int) -> int:
        """外围对称布置拉杆：1 个种子管 → judge_linkage 对称展开（正式程序 on_lagan_click）。"""
        from .placement import pick_centers, symmetric_group

        if self.result is None or count <= 0:
            return 0
        pool = self.current_centers()
        used = {c["center"] for c in self.components if c.get("center")}
        seeds = pick_centers(pool, min(len(pool), count * 2 + 2), "edge_symmetric")
        placed: list[tuple[float, float]] = []
        for seed in seeds:
            group = [c for c in symmetric_group([seed]) if c in pool and c not in used]
            if not group or any(c in placed for c in group):
                continue
            placed.extend(group)
            if len(placed) >= count:
                break
        placed = placed[:count]
        if not placed:
            return 0
        self._push_undo()
        for center in placed:
            self.removed.add(center)
            self.components.append({"kind": "rod", "center": center})
        self._clear_selection_state()
        self.rebuild_scene()
        self.refresh_hole_table()
        return len(placed)


    def place_bypasses(self, count: int) -> int:
        """旁路挡板：每个参照管沿折流板切口方向一块，从管伸到壳体内壁。"""
        from .placement import pick_centers

        if self.result is None or count <= 0:
            return 0
        picked = pick_centers(self.current_centers(), count, "near_shell")
        self._push_undo()
        for center in picked:
            self.components.append(dict(self._bypass_geometry(center), kind="bypass"))
        self.rebuild_scene()
        return len(picked)


    def placement_option_values(self, kind: str) -> dict:
        """卡片展示用：该元件相关参数的当前值（空缺的用布置时的兜底默认值补齐）。"""
        from .placement import OPTION_FIELDS

        fallback = {
            "拉杆形式": "焊接拉杆",
            "拉杆直径": "16",
            "旁路挡板厚度": "6",
            "旁路挡板宽度": "40",
            "中间挡板厚度": "6",
            "中间挡板宽度": "60",
            "防冲板形式": "平板形",
            "防冲板厚度": "10",
            "防冲板宽度": "200",
            "滑道形式": "板式滑道",
            "滑道高度": "150",
            "滑道厚度": "10",
            "吊环螺钉规格": "M20",
        }
        values = {name: self._param_text(name) for name in OPTION_FIELDS.get(kind, ())}
        for name, value in values.items():
            if not value:
                values[name] = fallback.get(name, "")
        return values

    # ------------------------------------------------------ 选管解析
    # 正式程序里每个元件都是「先选管（1 或 2 根换热管 / 拉杆），再改参数」。
    # AI 方案因此必须落成同一个东西：具体选中哪几根管。确认前先在图上高亮。
    def _impingement_form(self, item) -> str:
        """防冲板形式：方案卡上改过的优先，其次方案的，再其次元件类型，最后读参数表。"""
        form = str((getattr(item, "overrides", {}) or {}).get("防冲板形式") or "").strip()
        if not form:
            form = str(item.options.get("防冲板形式") or "").strip()
        if not form:
            form = {
                "impingement_folded": impingement.FORM_FOLDED,
                "impingement_welded": impingement.FORM_WELDED,
            }.get(item.kind, "")
        if not form:
            form = (self._param_text("防冲板形式") or impingement.FORM_FLAT).strip()
        return form

    def _resolve_item(self, item, pool=None) -> dict:
        """把“选孔意图”解析成具体换热管；选法与落地（apply_placement_plan）完全一致。"""
        from .placement import ANCHORS, pick_centers, pick_pairs

        pool = list(self.current_centers() if pool is None else pool)
        out = {"pairs": [], "tubes": [], "seeds": [], "note": ""}
        kind = item.kind
        if self.result is None or kind in {"slide", "screw_ring", "baffle"}:
            out["note"] = "不选管"
            return out

        # 0) 方案卡上已经指定了具体换热管/拉杆（用户可改）：直接用，不再重新选孔。
        #    焊接式防冲板不依附管孔，方案卡从平板/圆弧改成焊接式后要忽略旧的选点。
        welded = (
            kind in {"impingement", "impingement_folded", "impingement_welded"}
            and self._impingement_form(item) == impingement.FORM_WELDED
        )
        if welded:
            item.anchors = []
            out["note"] = "不选管"
            return out
        if item.anchors:
            wanted = [tuple(a) for a in item.anchors]
            # 普通拉杆和换热管一样可以当参照点（源程序 selected_centers 里两者混着用）
            available = {tuple(c) for c in self.selectable_centers()}
            missing = [c for c in wanted if c not in available]
            if missing:
                out["note"] = "指定的换热管不可用"
                return out
            if kind in {"rod", "free_rod"}:
                # 拉杆的输入是“种子管”，根数由 judge_linkage 决定：
                # 勾“对称分布”时 1 个种子就展开成 4 根，不是 1 根
                picked: list = []
                for seed in wanted:
                    group = [c for c in self._linkage_expand([seed], pool) if c in pool]
                    out["seeds"].append(seed)
                    picked.extend([c for c in group if c not in picked])
                out["tubes"] = picked or wanted[:1]
                return out
            if ANCHORS.get(kind, 1) == 2 and len(wanted) % 2 == 0:
                out["pairs"] = [tuple(wanted[i:i + 2]) for i in range(0, len(wanted), 2)]
            out["tubes"] = wanted
            return out

        # 拉杆 / 自由拉杆：1 个种子管 → judge_linkage（对称分布）/ 单轴镜像展开
        if kind in {"rod", "free_rod"}:
            # “外轮廓全部换成拉杆”是一个整体操作：外轮廓已经是程序按当前布管结果
            # 算出的精确集合，直接全部返回，不再压成一个种子管，也不设 Demo 人工上限。
            if item.region == "outline":
                out["tubes"] = list(self._outline_ring(pool, 1))
                out["note"] = "布管外轮廓全部管孔"
                return out
            # count 是“要布置的根数”；一个种子管经 judge_linkage 会铺满 4 个象限，
            # 所以种子数由展开结果凑到 count 为止（至少 1 个种子，源程序里
            # 选 1 根就自动补成 4 根）。最多只能占用当前真实可用管孔，不再另设 40 根上限。
            target = max(1, min(int(item.count or 1), len(pool)))
            # 镜像经常落到同一组（4 个点互相镜像），种子要多给一些才凑得够根数；
            # 遍历范围只受当前真实管孔池限制，确保一次方案可以完成全部目标。
            seeds = pick_centers(pool, min(len(pool), target * 2 + 4), item.region)
            picked: list = []
            for seed in seeds:
                group = [
                    c for c in self._linkage_expand([seed], pool)
                    if c in pool and c not in picked
                ]
                if not group or any(c in picked for c in group):
                    continue
                out["seeds"].append(seed)
                picked.extend(group)
                if len(picked) >= target:
                    break
            out["tubes"] = picked
            return out

        # 防冲板：圆弧形 / 平板形选 2 根参照管；焊接式不选管
        if kind in {"impingement", "impingement_folded", "impingement_welded"}:
            form = self._impingement_form(item)
            if form == impingement.FORM_WELDED:
                out["note"] = "不选管"
                return out
            min_span = 0.0
            if form == impingement.FORM_FOLDED:
                angle = self._float("防冲板折边角度") or 45.0
                override = str(item.overrides.get("防冲板折边角度") or "").strip()
                if override:
                    try:
                        angle = float(override)
                    except ValueError:
                        pass
                min_span = impingement.required_span_for_folded(
                    self._float("换热管外径 do") or 25.0,
                    self._float("换热管中心距 S") or 32.0,
                    angle,
                )
            region = item.region if item.region not in {"any", "uniform"} else "top"
            # 防冲板几何相对参照管往壳壁方向展开，参照管取最外行会让整块板落在
            # 管束之外、删不到任何管（用户反馈"上面一行没删"）。从外向内错开一行，
            # 与正式程序用户手选第二行参照管等价。
            region = {
                "top": "top_inner",
                "bottom": "bottom_inner",
            }.get(region, region)
            out["pairs"] = pick_pairs(pool, item.count, region, "row", min_span=min_span)
            out["tubes"] = [c for pair in out["pairs"] for c in pair]
            return out

        # 中间挡板 / 中间挡管：隔板槽两侧各选一根（源程序“同一隔板槽两侧各选一个参照管”）
        if kind in {"center_baffle", "block_tube"}:
            pairs = [p for p in self._groove_pairs() if p[0] in pool and p[1] in pool]
            if kind == "block_tube":
                # 正好跨在圆心上的那对，挡管会落到 (0,0)（没有可替换的管孔），跳过
                usable = []
                for one in pairs:
                    point, error = self._block_tube_point(one)
                    if error or (abs(point[0]) < 1e-6 and abs(point[1]) < 1e-6):
                        continue
                    usable.append(one)
                pairs = usable
            if item.region in {"top", "bottom", "left", "right"}:
                reverse = item.region in {"bottom", "right"}
                pairs = sorted(pairs, key=lambda p: (p[0][0] + p[0][1]), reverse=reverse)

            def mirror_is_distinct(pair) -> int:
                """对称分布时优先挑“镜像后确实是另一对”的参照管。

                压在竖直中心线上的那一对镜像就是自己（源程序 judge_linkage_y 的结果
                还是同一对），选它只会出一块板 / 一根挡管；挑偏心的那一对才会在两侧
                各出一块，这才是用户勾“对称分布”想看到的结果。
                """
                if not self._symmetry:
                    return 1
                mirror = self._symmetry_pair_partners(pair)
                if not mirror:
                    return 2
                return 0 if {tuple(p) for p in mirror[0]} != {tuple(p) for p in pair} else 2

            pairs = sorted(pairs, key=mirror_is_distinct)   # 稳定排序：同一档里保持上面排好的次序
            # 勾“对称分布”时，源程序在另一侧再补一块挡板 / 一根挡管
            out["pairs"] = self._symmetry_pairs(pairs[: max(1, item.count)])
            out["tubes"] = [c for pair in out["pairs"] for c in pair]
            return out

        # 旁路挡板：每个参照管各 1 块
        if kind == "bypass":
            region = "near_shell" if item.region in {"uniform", "any"} else item.region
            out["tubes"] = pick_centers(pool, item.count, region)
            return out

        out["tubes"] = pick_centers(pool, item.count, item.region)
        return out

    @staticmethod
    def _fmt_pt(center) -> str:
        return f"({float(center[0]):.1f}, {float(center[1]):.1f})"

    # ------------------------------------------------------ 管孔行列号
    # 方案卡让用户“改行号列号”来换参照管，所以这里给出一套与右侧数量表同源的
    # 编号：行号 = 至水平中心线第几排（正上负下），列号 = 至竖直中心线第几列
    # （正右负左，正好落在中心线上记 0）。
    def tube_row_col(self, center) -> tuple[int, int] | None:
        """坐标 → (行号, 列号)。

        行号/列号一律按**满布管孔**（result.master_centers）编号，不看当前还剩几根：
        删掉管子以后行号不会整体错位，已删管孔也能报出原来的行列号（以前这里
        找不到就直接给 (0, 0)，方案卡上全是“行0列0”）。
        """
        if self.result is None:
            return None
        x, y = float(center[0]), float(center[1])
        master = [(float(c[0]), float(c[1])) for c in self.result.master_centers]
        if not master:
            return None
        reps = geometry.build_axis_cluster_reps([abs(c[1]) for c in master])
        key = geometry.nearest_axis_cluster_key(abs(y), reps)
        if key is None:
            return None
        row_label = (key + 1) * (1 if y >= 0 else -1)
        same_row = [
            c for c in master
            if (c[1] >= 0) == (y >= 0)
            and abs(abs(c[1]) - reps[key]) <= geometry.AXIS_GROUP_TOL + 1e-9
        ]
        if abs(x) < 1e-6:
            return row_label, 0
        # 只数“同一侧、且更靠近竖直中心线”的管；正好在 x=0 的那根不算任何一侧
        nearer = [
            cx for cx, _cy in same_row
            if ((cx > 1e-6) if x > 0 else (cx < -1e-6)) and abs(cx) < abs(x) - 1e-6
        ]
        col_label = len(nearer) + 1
        return row_label, col_label if x > 0 else -col_label

    def center_for_row_col(self, row: int, col: int):
        """（行号, 列号）→ 换热管绝对坐标；没有这个管孔返回 None。"""
        if self.result is None or row == 0:
            return None
        master = [(float(c[0]), float(c[1])) for c in self.result.master_centers]
        reps = geometry.build_axis_cluster_reps([abs(c[1]) for c in master])
        index = abs(int(row)) - 1
        if index >= len(reps):
            return None
        group = [
            c for c in master
            if (c[1] >= 0) == (row > 0)
            and abs(abs(c[1]) - reps[index]) <= geometry.AXIS_GROUP_TOL + 1e-9
        ]
        group.sort(key=lambda c: abs(c[0]))
        if col == 0:
            for cx, cy in group:
                if abs(cx) < 1e-6:
                    return (float(cx), float(cy))
            return None
        side = [c for c in group if (c[0] > 1e-6 if col > 0 else c[0] < -1e-6)]
        side.sort(key=lambda c: abs(c[0]))
        position = abs(int(col)) - 1
        if position >= len(side):
            return None
        return (float(side[position][0]), float(side[position][1]))

    def row_limits(self) -> tuple[int, int]:
        """有效行号范围（上半最大行号, 下半最大行号），用于报错时给用户看。"""
        pos = max([i + 1 for i, group in enumerate(self._rows_pos) if group] or [0])
        neg = max([i + 1 for i, group in enumerate(self._rows_neg) if group] or [0])
        return pos, neg

    def _tube_ref(self, center) -> dict:
        row_col = self.tube_row_col(center) or (0, 0)
        return {
            "row": row_col[0],
            "col": row_col[1],
            "x": round(float(center[0]), 1),
            "y": round(float(center[1]), 1),
        }

    def validate_anchors(self, item) -> str | None:
        """方案卡里用户指定的参照管是否可用；返回错误文案（None 表示没问题）。

        判据全部照抄正式程序，不再自造“必须在同一排/同一列”这种限制：
        · 防冲板  `impingement_plate.build_impingement_plate`：只要求两根参照管；
          “参照管中心连线”方式要求中心距 > do；折边角度过大导致顶部长度为负、
          端点超出壳体大圆，都由几何计算直接报原文提示。
        · 中间挡管 `center_dangguan.build_center_dangguan`：连线与隔板槽轴线交点必须
          落在线段内，否则“所选参照管位置不合理，请在同一隔板槽两侧各选一个参照管!”
        · 中间挡板 `center_dangban.check_partition_side_for_two`：必须隔板槽两侧第一排。
        """
        from .placement import ANCHORS

        anchors = [tuple(a) for a in item.anchors]
        if not anchors:
            return None
        # 普通拉杆也能当参照管（源程序里两者同性质），所以池子要带上已布置的拉杆
        pool = {tuple(c) for c in self.selectable_centers()}
        for center in anchors:
            if center not in pool:
                return f"{self._fmt_pt(center)} 不是当前布管图上的换热管"
        needed = ANCHORS.get(item.kind, 1)
        if needed and len(anchors) % needed:
            # 源程序对 2 根参照管的元件统一提示这一句
            return "选择换热管的数量不正确！"
        if needed != 2:
            return None

        do = self._float("换热管外径 do") or 25.0
        for first, second in item.anchor_pairs:
            pair = (tuple(first), tuple(second))
            span = math.hypot(second[0] - first[0], second[1] - first[1])
            if item.kind in {"impingement", "impingement_folded", "impingement_welded"}:
                form = self._impingement_form(item)
                if form == impingement.FORM_WELDED:
                    continue
                if form == impingement.FORM_FLAT and span <= do + 1e-6:
                    placement = str(
                        item.overrides.get("放置位置") or self._param_text("放置位置")
                    )
                    if "中心连线" in placement:
                        return (
                            "两参照管中心距小于或等于换热管外径 do，"
                            "无法按“参照管中心连线”方式绘制防冲板！"
                        )
                try:
                    self._impingement_geometry(form, pair, item.overrides)
                except impingement.ImpingementError as exc:
                    return str(exc)
            elif item.kind == "block_tube":
                _point, error = self._block_tube_point(pair)
                if error:
                    return error
            elif item.kind == "center_baffle":
                _side, reason = self._center_baffle_check(pair)
                if reason:
                    return reason
        return None

    def plan_param_rows(self, item) -> list[dict]:
        """方案卡上可编辑的参数（名字/当前值/单位/控件类型/选项）。

        形式（防冲板形式/滑道形式/中间挡板安装方式…）同样可改：改完卡片会按新形式
        重新给出一组参数（平板形→放置位置、圆弧形→折边角、焊接式→宽度/方位角/距内壁），
        并把轮廓与“删几个干涉管”重算一遍。
        """
        from .placement import IMPINGEMENT_FIELDS_BY_FORM, OPTION_FIELDS

        names = OPTION_FIELDS.get(item.kind, ())
        if item.kind in {"impingement", "impingement_folded", "impingement_welded"}:
            names = IMPINGEMENT_FIELDS_BY_FORM.get(self._impingement_form(item), names)
        current = self.placement_option_values(item.kind)
        rows = []
        for name in names:
            spec = spec_for(name, self.product_type, self.parameters)
            value = str(item.overrides.get(name) or "").strip()
            if not value:
                if _is_choice_param(name):
                    value = str(item.options.get(name) or current.get(name) or "").strip()
                else:
                    value = str(current.get(name) or item.options.get(name) or "").strip()
            is_form = name.endswith("形式")
            # 旁路挡板宽度、中间挡板宽度都是程序按几何算出来的（正式程序写回参数表），
            # 卡片上只读显示算好的值，避免手填一个跟板长对不上的数字
            locked = name in {"旁路挡板宽度", "中间挡板宽度"}
            if locked:
                if item.kind == "bypass":
                    value = self.preview_bypass_width(item) or value
                elif item.kind == "center_baffle":
                    value = self.preview_baffle_width(item) or value
            if is_form:
                # 形式决定几何、也决定“要不要参照管”，选项以程序里的可选值为准
                if item.kind.startswith("impingement") or "防冲板" in name:
                    options = [impingement.FORM_FLAT, impingement.FORM_FOLDED,
                               impingement.FORM_WELDED]
                else:
                    options = [str(option) for option in spec.options if str(option).strip()]
                if value and value not in options:
                    options.append(value)
            else:
                options = list(spec.options)
            rows.append({
                "name": name,
                "short": _PARAM_SHORT.get(name, name),
                "value": value,
                "unit": spec.unit or _param_unit(name).strip(),
                "kind": "choice" if is_form or spec.kind in {"combo", "combo_edit", "pattern"} else "number",
                "options": options,
                "form": is_form,
                "locked": locked,
            })
        return rows

    def _anchor_text(self, item, resolution: dict) -> str:
        """卡片上「选中的换热管」一列：直接写具体管孔坐标，读起来就是用户点的管。"""
        if resolution.get("note") == "不选管":
            return "不选管"
        pairs = resolution.get("pairs") or []
        tubes = resolution.get("tubes") or []
        seeds = resolution.get("seeds") or []
        if pairs:
            return "；".join(f"{self._fmt_pt(a)} – {self._fmt_pt(b)}" for a, b in pairs)
        if seeds:
            return f"{self._fmt_pt(seeds[0])}，对称展开 {len(tubes)} 根"
        if not tubes:
            return "无可用管孔"
        if len(tubes) <= 4:
            return "、".join(self._fmt_pt(c) for c in tubes)
        return "、".join(self._fmt_pt(c) for c in tubes[:3]) + f" 等 {len(tubes)} 根"

    def _param_summary(self, item) -> str:
        """卡片上「参数」一列：直接用参数表当前值（用户不动就是默认值）。"""
        from .placement import IMPINGEMENT_FIELDS_BY_FORM, OPTION_FIELDS

        kind = item.kind
        names = OPTION_FIELDS.get(kind, ())
        if kind in {"impingement", "impingement_folded", "impingement_welded"}:
            names = IMPINGEMENT_FIELDS_BY_FORM.get(self._impingement_form(item), names)
        current = self.placement_option_values(kind)
        parts = []
        for name in names:
            # 用户在方案卡上改过的值优先（那就是他确认的布置参数）
            value = str(item.overrides.get(name) or "").strip()
            if not value:
                value = str(item.options.get(name) or "").strip()
            if name.endswith("形式") or name in {"放置位置"}:
                # 形式/位置是方案里的“选择”，优先按方案的
                value = value or str(current.get(name) or "").strip()
            else:
                # 数值参数一律用参数表当前值，模型给的只是参考
                value = str(item.overrides.get(name) or "").strip() or str(
                    current.get(name) or value
                ).strip()
            if not value:
                continue
            parts.append(f"{_PARAM_SHORT.get(name, name)} {value}{_param_unit(name)}")
        return "、".join(parts)

    @staticmethod
    def _plan_ref_mode(item, resolution: dict) -> str:
        """方案卡里“选中的换热管”怎么给用户编辑。

        - pair：正式程序里要选 2 根参照管的元件（防冲板/中间挡板/中间挡管），
                每块板给出两根管，行号列号都能改；
        - seed：拉杆/自由拉杆只选 1 个种子管，其余由 judge_linkage 对称展开；
        - none：滑道/吊环螺钉/焊接式防冲板不选管，只改参数；
        - text：旁路挡板等“每管一块”的元件只读显示选中的管，避免一次列几十行。
        """
        if resolution.get("pairs"):
            return "pair"
        if item.kind in {"rod", "free_rod"} and resolution.get("seeds"):
            return "seed"
        if resolution.get("note") == "不选管" or not resolution.get("tubes"):
            return "none"
        return "text"

    def preview_impingement_deletes(self, item, resolution=None) -> int:
        """方案预览：这块板落地后会删掉多少个干涉换热管（只算数，不动图）。"""
        if item.kind not in {
            "impingement", "impingement_folded", "impingement_welded"
        }:
            return 0
        form = self._impingement_form(item)
        resolution = resolution or self._resolve_item(item)
        if form == impingement.FORM_WELDED:
            try:
                geometry = self._impingement_geometry(form, None, item.overrides)
            except impingement.ImpingementError:
                return 0
            return len(self.impingement_delete_centers(form, geometry, None))
        total = 0
        for pair in resolution.get("pairs") or []:
            try:
                geometry = self._impingement_geometry(form, pair, item.overrides)
            except impingement.ImpingementError:
                continue
            total += len(self.impingement_delete_centers(form, geometry, pair))
        return total

    def preview_bypass_width(self, item) -> str:
        """方案预览：旁路挡板宽度先按正式程序公式算一遍（卡片上只读显示）。

        正式程序 `on_side_block_click` 也是先算宽度、把结果写进“旁路挡板宽度”参数，
        再按这个宽度画板，所以卡片上的宽度必须是算出来的值，不是手填的 40。
        """
        try:
            centers = self._resolve_item(item).get("tubes") or []
            if not centers:
                return ""
            geometry = self._bypass_geometry(centers[0])
            return self._pretty(max(float(v) for v in geometry["size"]))
        except Exception:  # noqa: BLE001 - 预览算不出来就不显示，别把卡片弄挂
            return ""

    def preview_baffle_width(self, item) -> str:
        """方案预览：中间挡板长度 = 两参照管中心距 − do − 2×名义孔桥（正式程序算法）。"""
        try:
            pairs = self._resolve_item(item).get("pairs") or []
            if not pairs:
                return ""
            return self._pretty(self._pair_geometry("center_baffle", pairs[0], None)["size"][0])
        except Exception:  # noqa: BLE001
            return ""

    def preview_placement(self, items) -> dict:
        """把方案解析成“选中的换热管”并在图上高亮；此时还没有任何元件落地。"""
        rows = []
        occupying = 0
        deletes = 0
        picked: list[tuple[float, float]] = []
        for item in items:
            resolution = self._resolve_item(item)
            tubes = resolution.get("tubes") or []
            mode = self._plan_ref_mode(item, resolution)
            refs: list[dict] = []
            if mode == "pair":
                refs = [self._tube_ref(c) for pair in resolution["pairs"] for c in pair]
            elif mode == "seed":
                seed = (resolution.get("seeds") or tubes or [None])[0]
                if seed is not None:
                    refs = [self._tube_ref(seed)]
            deleted = self.preview_impingement_deletes(item, resolution)
            label = item.label
            if item.kind in {"impingement", "impingement_folded", "impingement_welded"}:
                # 卡片上改了形式，标题也要跟着变（“圆弧形防冲板”→用户改成“平板形防冲板”）
                label = f"{self._impingement_form(item)}防冲板"
            # 挡管/挡板按“一对参照管 → 一块”，勾对称分布时一对会补成两对，块数按实际对数给
            shown_count = item.count
            if item.kind in {"rod", "free_rod"} and tubes:
                shown_count = len(tubes)
            if item.kind in {"center_baffle", "block_tube"} and resolution.get("pairs"):
                shown_count = len(resolution["pairs"])
            rows.append({
                "label": label,
                "kind": item.kind,
                "form": item.form,
                "count": shown_count,
                "anchors": self._anchor_text(item, resolution),
                "params": self._param_summary(item),
                "tubes": [self._tube_ref(c) for c in tubes],
                "refs": refs,
                "ref_mode": mode,
                "param_rows": self.plan_param_rows(item),
                "error": self.validate_anchors(item),
                "deleted": deleted,
            })
            if item.occupying:
                # 拉杆按“对称展开后的实际根数”占孔，挡管按参照管对数各占 1 个
                if item.kind == "block_tube":
                    occupying += len(resolution.get("pairs") or []) or item.count
                else:
                    occupying += len(tubes) or item.count
            deletes += deleted
            picked.extend(resolution.get("tubes") or [])
        holes = len(self.current_centers())
        if picked:
            self.select_centers(picked)
        pos_rows, neg_rows = self.row_limits()
        return {
            "rows": rows,
            "occupying": occupying,
            "deletes": deletes,
            "holes": holes,
            "remaining": max(holes - occupying - deletes, 0),
            "row_limits": (pos_rows, neg_rows),
        }

    # ------------------------------------------------------ 元件布置方案落地
    def _groove_axis(self) -> str:
        """分程隔板槽的走向：2 管程隔板水平（槽在 y=0），4/6 管程隔板竖直（槽在 x=0）。

        照抄正式程序 `center_dangguan.build_center_dangguan`：
        2 管程挡管落在 `(x_mid, 0)`，4/6 管程落在 `(0, y_mid)`。
        """
        return "x" if self._param_text("管程程数") in {"4", "6"} else "y"

    def _groove_pairs(self) -> list[tuple]:
        """隔板槽两侧第一排换热管的全部相邻管对。"""
        from .placement import groove_pairs

        return groove_pairs(self.selectable_centers(), self._groove_axis())

    def _anchor_orientation(self) -> str:
        """同 `_groove_axis()` 的“行/列”写法（挡板/挡管取参照管的方向）。"""
        return "col" if self._groove_axis() == "x" else "row"

    @staticmethod
    def _is_midpoint(point, pair) -> bool:
        (x1, y1), (x2, y2) = pair
        return abs(point[0] - (x1 + x2) / 2.0) < 1e-6 and abs(point[1] - (y1 + y2) / 2.0) < 1e-6

    def _block_tube_point(self, pair):
        """两根参照管连线与分程隔板槽轴线的交点（正式程序 `build_center_dangguan`）。

        正式程序先算连线与 x 轴（y=0）、y 轴（x=0）的交点，只保留落在线段内的；
        两个都在（跨槽又过中心）或都不在，都提示“所选参照管位置不合理，
        请在同一隔板槽两侧各选一个参照管!”；只有一个时，交点就是挡管位置
        （不是中点再问一句“所选参照管连线非水平线，是否继续？”）。
        """
        (x1, y1), (x2, y2) = pair
        axis = self._groove_axis()
        if axis == "y":                       # 水平隔板槽：要求一上一下
            if not ((y1 > 1e-6 > y2) or (y2 > 1e-6 > y1)):
                return None, "所选参照管位置不合理，请在同一隔板槽两侧各选一个参照管!"
            if abs(y2 - y1) < 1e-9:
                return None, "所选参照管位置不合理，请在同一隔板槽两侧各选一个参照管!"
            ratio = (0.0 - y1) / (y2 - y1)
            return (x1 + (x2 - x1) * ratio, 0.0), None
        if not ((x1 > 1e-6 > x2) or (x2 > 1e-6 > x1)):   # 竖直隔板槽：要求一左一右
            return None, "所选参照管位置不合理，请在同一隔板槽两侧各选一个参照管!"
        if abs(x2 - x1) < 1e-9:
            return None, "所选参照管位置不合理，请在同一隔板槽两侧各选一个参照管!"
        ratio = (0.0 - x1) / (x2 - x1)
        return (0.0, y1 + (y2 - y1) * ratio), None

    def _center_baffle_check(self, pair):
        """中间挡板参照管校验（照抄 `center_dangban.check_partition_side_for_two`）。

        返回 (side, reason)：side = "horizontal"（水平隔板槽两侧）/ "vertical"
        （竖直隔板槽两侧），reason 非空表示不允许布置。

        正式程序用两个专门参数判“是不是隔板槽两侧第一排”：
        `垂直隔板槽两侧相邻管中心距 LB_SN`（水平槽）与
        `水平隔板槽两侧相邻管中心距 LB_SNH`（竖直槽），并辅以“至中心线第 1 排”的
        行号判断。本程序没有这两个参数，等价做法是直接看几何：两管在槽的两侧、
        中间没有别的管子（就是第一排），且跨距等于该列/该行的槽宽。
        """
        (x1, y1), (x2, y2) = pair
        dx = abs(x1 - x2)
        dy = abs(y1 - y2)
        passes = self._param_text("管程程数")
        row1 = self.tube_row_col((x1, y1))
        row2 = self.tube_row_col((x2, y2))
        pool = [(float(x), float(y)) for x, y in self.current_centers()]

        def nothing_between(vertical_strict: bool) -> bool:
            for x, y in pool:
                if vertical_strict:                    # 同一列（x 相同）
                    if abs(x - x1) > 1e-6:
                        continue
                    if min(y1, y2) + 1e-6 < y < max(y1, y2) - 1e-6:
                        return False
                else:                                  # 同一行（y 相同）
                    if abs(y - y1) > 1e-6:
                        continue
                    if min(x1, x2) + 1e-6 < x < max(x1, x2) - 1e-6:
                        return False
            return True

        # 水平隔板槽两侧：同一列、一上一下，且紧贴槽（中间没有别的管）
        horizontal_ok = (
            dx < 1.0 and (y1 * y2) < 0 and dy > 0 and nothing_between(True)
        )
        # 竖直隔板槽两侧：同一行、一左一右，且是紧贴槽的第一排
        vertical_ok = (
            dy < 1.0 and (x1 * x2) < 0 and dx > 0 and nothing_between(False)
        )
        if horizontal_ok and vertical_ok:
            return None, "所选参照管位置不合理，请重新选择！"
        if passes in {"4", "6"}:
            side = "horizontal" if horizontal_ok else ("vertical" if vertical_ok else None)
        else:
            side = "horizontal" if horizontal_ok else None
        if side is None:
            return None, "只能选择隔板槽两侧第一排换热管孔作为中间挡板的参照管！"

        # 范围过大：水平侧看列号差（2 管程允许相邻一列，6 管程允许到 3 列），
        # 竖直侧看行号差
        try:
            if side == "horizontal" and row1 and row2:
                delta = abs(abs(row1[1]) - abs(row2[1]))
                limit = 3 if passes in {"4", "6"} else 1
                if delta > limit:
                    return None, "所选的2个换热管范围过大，请重新选择！"
            elif side == "vertical" and row1 and row2:
                if abs(abs(row1[0]) - abs(row2[0])) > 2:
                    return None, "所选的2个换热管范围过大，请重新选择！"
        except Exception:  # noqa: BLE001 - 行号算不出来就不拦
            pass
        return side, None

    def _ask_yes_no(self, title: str, text: str) -> bool:
        """正式程序里的“是否继续？”询问（按钮就是 是 / 否）。"""
        if self.headless:
            return True
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Question)
        box.setText(text)
        yes = box.addButton("是", QMessageBox.YesRole)
        no = box.addButton("否", QMessageBox.NoRole)
        box.setDefaultButton(no)
        box.exec_()
        return box.clickedButton() is yes

    def _impingement_geometry(self, form: str, pair=None, overrides: dict | None = None) -> dict:
        """防冲板三种形式的轮廓（照抄 `impingement_plate.build_impingement_plate`）。

        返回的 `points` 是**绘制坐标**（y 向下，与场景一致），`center` 换回数学坐标
        供选中/写库/撤销使用。参数全部取自左侧 65 项参数表（与正式程序同源）；
        方案卡上用户刚改过、还没落地的值（overrides）优先，这样卡片一改板厚/折边角，
        预览的轮廓和“删几个干涉管”就跟着变。
        """
        def number(name: str, default=None):
            text = str((overrides or {}).get(name) or "").strip() or self._param_text(name)
            try:
                return float(text)
            except (TypeError, ValueError):
                return default

        thickness = number("防冲板厚度", 10.0) or 10.0
        do = number("换热管外径 do", 25.0) or 25.0
        pitch = number("换热管中心距 S", 32.0) or 32.0
        fold_angle = number("防冲板折边角度", 45.0) or 45.0
        placement = (
            str((overrides or {}).get("放置位置") or "").strip()
            or self._param_text("放置位置")
            or "参照管顶部连线"
        ).strip()
        shell_radius = (self._float("壳体内直径 Dis") or 0.0) / 2.0
        if shell_radius <= 0 and self.result is not None:
            shell_radius = self.result.big_r_di
        scene_pair = None
        if pair:
            scene_pair = [self._plot(pair[0]), self._plot(pair[1])]
        geometry = impingement.geometry_for_form(
            form,
            scene_pair,
            tube_outer_diameter=do,
            tube_pitch=pitch,
            thickness=thickness,
            fold_angle=fold_angle,
            placement=placement,
            width=number("防冲板宽度", 0.0) or 0.0,
            azimuth=number("防冲板方位角", 0.0) or 0.0,
            distance_to_shell=number("至圆筒内壁距离", 0.0) or 0.0,
            shell_inner_radius=shell_radius,
        )
        centre_x, centre_y = impingement.centroid(geometry["points"])
        geometry["center"] = (centre_x, -centre_y)  # 绘制坐标 -> 数学坐标
        geometry["thickness"] = thickness
        geometry["form"] = form
        geometry["pair"] = [tuple(point) for point in pair] if pair else None
        geometry["options"] = {
            name: str((overrides or {}).get(name) or self._param_text(name))
            for name in (
                "防冲板形式", "放置位置", "防冲板厚度", "防冲板折边角度",
                "防冲板宽度", "防冲板方位角", "至圆筒内壁距离",
            )
        }
        return geometry

    def _shell_inner_radius(self) -> float:
        radius = (self._float("壳体内直径 Dis") or 0.0) / 2.0
        if radius <= 0 and self.result is not None:
            radius = self.result.big_r_di
        return radius

    def _linkage_mirror_centers(self, centers):
        """正式程序 `judge_linkage_x` / `judge_linkage_y`：按管程程数补镜像管。

        2 管程 → 关于水平中心线镜像（(x, −y)）；4/6 管程 → 关于竖直中心线镜像（(−x, y)）；
        产品型式不在 AEU/BEU/AKU/BKU 之列时不做镜像。坐标都用**绘制坐标**。
        """
        if self.product_type not in {"AEU", "BEU", "AKU", "BKU"}:
            return list(centers)
        passes = self._param_text("管程程数")
        if passes == "2":
            mirrors = [(x, -y) for x, y in centers]
        elif passes in {"4", "6"}:
            mirrors = [(-x, y) for x, y in centers]
        else:
            return list(centers)
        return list(centers) + mirrors

    def impingement_delete_centers(self, form: str, geometry: dict, pair=None):
        """防冲板落位要删掉的换热管（数学坐标），三步全照正式程序：

        1. 板体自身压到的管：
           平板形/圆弧形走 `calculate_and_update_interfering_tubes`（矩形带与圆求交，
           圆弧形对 A-P、P-Q、Q-B 三段各算一次再合并），焊接式走
           `calculate_welded_impingement_interfering_tubes`（APQB 扇形 + 线段距离）；
        2. `collect_extra_impingement_delete_centers`：弦靠壳壁一侧的整片弓形区也删，
           弦两端点外侧的管保留；
        3. `judge_linkage_x` / `judge_linkage_y`：按管程程数补镜像管。

        两块参照管是防冲板的支撑管，正式程序 `_merge_interfering_with_extra` 会把它们
        从删除表里剔除，这里同样剔除。
        """
        if self.result is None or not geometry.get("points"):
            return []
        thickness = float(
            geometry.get("thickness") or self._float("防冲板厚度") or 0.0
        )
        do = self._float("换热管外径 do") or 0.0
        pool = [self._plot(c) for c in self.current_centers()]
        scene_pair = [self._plot(c) for c in pair] if pair else []
        hits: list[tuple[float, float]] = []

        if form == impingement.FORM_WELDED:
            hits = impingement.welded_interference_centers(
                geometry["points"], thickness, do, pool, self._shell_inner_radius()
            )
        else:
            hits = impingement.interference_centers(
                geometry["points"], thickness, do, pool
            )
            limit_radius = (self._float("布管限定圆 DL") or 0.0) / 2.0
            if scene_pair and limit_radius > 0:
                hits += impingement.outer_cap_centers(scene_pair, pool, limit_radius)

        # 镜像先做、剔除参照管后做：正式程序 `_merge_interfering_with_extra` 的意图是
        # “两块参照管绝对不删”，所以镜像补出来的坐标也要过一遍这个剔除，否则
        # 上下对称为镜像的两根参照管会被互相删掉。
        hits = self._linkage_mirror_centers(hits)
        anchors = {(round(p[0], 6), round(p[1], 6)) for p in scene_pair}
        if anchors:
            hits = [c for c in hits if (round(c[0], 6), round(c[1], 6)) not in anchors]
        known = {(round(p[0], 6), round(p[1], 6)) for p in pool}
        seen: set[tuple[float, float]] = set()
        deleted: list[tuple[float, float]] = []
        for x, y in hits:
            key = (round(x, 6), round(y, 6))
            if key in seen or key not in known:
                continue
            seen.add(key)
            deleted.append((key[0], -key[1]))  # 绘制坐标 -> 数学坐标
        return sorted(deleted)

    def impingement_interfering_rod_centers(
        self, form: str, geometry: dict, pair=None
    ) -> list[tuple[float, float]]:
        """返回板体或弦外弓形区覆盖到的拉杆管孔（数学坐标）。"""
        if not geometry.get("points"):
            return []
        thickness = float(
            geometry.get("thickness") or self._float("防冲板厚度") or 0.0
        )
        scene_pair = [self._plot(center) for center in pair] if pair else []
        anchors = {(round(x, 6), round(y, 6)) for x, y in scene_pair}
        limit_radius = (self._float("布管限定圆 DL") or 0.0) / 2.0
        shell_radius = self._shell_inner_radius()
        hits: list[tuple[float, float]] = []

        for component in self.components:
            if component.get("kind") not in {"rod", "free_rod"}:
                continue
            center = component.get("center")
            if not center:
                continue
            scene_center = self._plot(center)
            if (round(scene_center[0], 6), round(scene_center[1], 6)) in anchors:
                continue
            options = component.get("options") or {}
            diameter = (
                options.get("拉杆直径")
                or options.get("自由拉杆直径")
                or self._float("拉杆直径")
                or 16.0
            )
            try:
                rod_diameter = float(diameter)
            except (TypeError, ValueError):
                rod_diameter = 16.0
            rod_pool = [scene_center]

            if form == impingement.FORM_WELDED:
                rod_hits = impingement.welded_interference_centers(
                    geometry["points"],
                    thickness,
                    rod_diameter,
                    rod_pool,
                    shell_radius,
                )
            else:
                rod_hits = impingement.interference_centers(
                    geometry["points"], thickness, rod_diameter, rod_pool
                )
                if scene_pair and limit_radius > 0:
                    rod_hits += impingement.outer_cap_centers(
                        scene_pair, rod_pool, limit_radius
                    )

            if rod_hits:
                hits.append((round(float(center[0]), 6), round(float(center[1]), 6)))
        return sorted(set(hits))

    def _apply_impingement_deletions(
        self,
        geometry: dict,
        form: str,
        pair=None,
        preserve_rod_deleted=(),
    ) -> tuple[int, int]:
        deleted = self.impingement_delete_centers(form, geometry, pair)
        newly_deleted_rods = self.impingement_interfering_rod_centers(
            form, geometry, pair
        )
        rod_deleted = {
            (round(float(x), 6), round(float(y), 6))
            for x, y in preserve_rod_deleted
        }
        rod_deleted.update(newly_deleted_rods)
        geometry["deleted"] = deleted
        geometry["rod_deleted"] = sorted(rod_deleted)
        self.removed.update(deleted)
        self.removed.update(rod_deleted)
        if newly_deleted_rods:
            deleted_keys = set(newly_deleted_rods)
            self.components = [
                component
                for component in self.components
                if component.get("kind") not in {"rod", "free_rod"}
                or not component.get("center")
                or (
                    round(float(component["center"][0]), 6),
                    round(float(component["center"][1]), 6),
                ) not in deleted_keys
            ]
        return len(deleted), len(newly_deleted_rods)

    def _pair_geometry(self, kind: str, pair, side: str | None = None) -> dict:
        """按两根参照管的真实坐标算板类元件几何（照抄正式程序）。

        `center_dangban.on_center_dangban_click` 要求“选中恰好 2 个换热管”，且必须
        分程隔板槽两侧第一排；板长 = 两管中心距 − do − 2×名义孔桥宽度，两个参照管
        就是板的两个端点，模型既不给坐标也不给方位角。
        防冲板另走 `_impingement_geometry()`（三种形式各不相同）。
        """
        from .placement import nominal_bridge_width

        (x1, y1), (x2, y2) = pair
        do = self._float("换热管外径 do") or 25.0
        span = math.hypot(x2 - x1, y2 - y1)
        angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
        name = "旁路挡板厚度" if kind == "bypass" else "中间挡板厚度"
        thickness = self._float(name) or 6.0
        length = max(span - do - 2.0 * nominal_bridge_width(do), do * 0.5)
        center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
        return {
            "center": center,
            "size": (length, thickness),
            "angle": angle,
            "pair": [tuple(pair[0]), tuple(pair[1])],
        }

    def _bypass_geometry(self, center, pool=None) -> dict:
        """旁路挡板：宽度按正式程序公式算，板的外边缘永远贴着折流/支持板外径圆。

        照抄 `side_dangban.calculate_level_side_dangban_length` /
        `calculate_vertical_side_dangban_length`：
        · 取同排（水平切口）最左侧 / 同列（竖直切口）最上侧的那根参照管，
        算它到折流板圆边的距离 `distance = |圆边 − 该管坐标|`；
        · 宽度 = |distance − 名义孔桥 − do/2|（板从圆边向里伸出的长度）；
        · `build_single_side_dangban(_vertical)` 里板的外边缘就压在圆边上
        （rect_x = min_x 或 max_x − 宽度 / rect_y = max_y − 长度 或 min_y），
        所以挡板一定落在大圆里面。以前按壳体半径加半宽画，才会跑到圆外。
        """
        from .placement import nominal_bridge_width

        do = self._float("换热管外径 do") or 25.0
        bridge = nominal_bridge_width(do)
        thickness = self._float("旁路挡板厚度") or 6.0
        radius = (
            self.result.baffle_r if self.result and self.result.baffle_r > 0
            else self._shell_inner_radius()
        )
        if radius <= 0:
            radius = 100.0
        x, y = float(center[0]), float(center[1])
        source = pool if pool is not None else self.selectable_centers()
        pool = [(float(c[0]), float(c[1])) for c in source] or [(x, y)]
        vertical = "竖直" in (self._param_text("折流板切口方向") or "")

        if vertical:
            column = [c for c in pool if abs(c[0] - x) < 1e-6]
            near = max(column, key=lambda c: c[1]) if column else (x, y)
            edge = math.sqrt(max(radius ** 2 - near[0] ** 2, 0.0))
            width = abs(abs(edge - abs(near[1])) - bridge - do / 2.0)
            # 外边缘压在圆上时，板的两个厚度转角比中线更靠外：按转角处收紧，
            # 保证整块板（含厚度）都落在折流板外径圆里
            outer_edge = math.sqrt(
                max(radius ** 2 - (abs(near[0]) + thickness / 2.0) ** 2, 0.0)
            )
            width = min(max(width, 1.0), max(2.0 * outer_edge, 1.0))
            top_side = abs(edge - y) <= abs(y + edge)
            outer = outer_edge if top_side else -outer_edge
            mid = (x, outer - width / 2.0 if top_side else outer + width / 2.0)
            return {
                "center": mid, "size": (thickness, width), "angle": 0.0,
                "anchor": (x, y),
            }

        row = [c for c in pool if abs(c[1] - y) < 1e-6]
        near = min(row, key=lambda c: c[0]) if row else (x, y)
        edge = math.sqrt(max(radius ** 2 - near[1] ** 2, 0.0))
        width = abs(abs(edge - abs(near[0])) - bridge - do / 2.0)
        outer_edge = math.sqrt(
            max(radius ** 2 - (abs(near[1]) + thickness / 2.0) ** 2, 0.0)
        )
        width = min(max(width, 1.0), max(2.0 * outer_edge, 1.0))
        left_side = abs(x + edge) < abs(edge - x)
        outer = -outer_edge if left_side else outer_edge
        mid = (outer + width / 2.0 if left_side else outer - width / 2.0, y)
        return {
            "center": mid, "size": (width, thickness), "angle": 0.0,
            "anchor": (x, y),
        }

    def _slide_geometries(self) -> list[dict]:
        """滑道不选管：按 定位/形式/数量/方位角/夹角 沿壳体内壁布置。"""
        form = self._param_text("滑道形式")
        is_round = form == "圆钢滑道"
        height = (self._float("圆钢规格") if is_round else self._float("滑道高度")) or 150.0
        thickness = height if is_round else (self._float("滑道厚度") or 10.0)
        # 正式程序 `build_huadao`：center_angle = 90°（Qt y 向下）= 数学 -90°，
        # 两条滑道按夹角对称分布在管束底部两侧；只有 1 条时就在底部正中。
        base = -90.0
        angles = [base]
        if (self._param_text("滑道数量") or "1") == "2":
            spread = self._float("滑道与竖直中心线夹角") or 20.0
            angles = [base + spread, base - spread]
        inner = self.result.big_r_di if self.result else height
        mid_radius = max(inner - height / 2.0, height / 2.0)
        items = []
        for angle in angles:
            rad = math.radians(angle)
            items.append({
                "center": (mid_radius * math.cos(rad), mid_radius * math.sin(rad)),
                "size": (height, thickness),
                "angle": angle,
            })
        return items

    def _slide_delete_centers(self, geometry: dict) -> list[tuple[float, float]]:
        """滑道覆盖的换热管孔（数学坐标）——照抄正式程序 slipway.py 干涉删管。

        正式程序 `check_tube_slide_interference`（My_Piping.py:2071 `_tube_intersects_slide_rect`）：
        管心到滑道矩形（底面贴基准圆、向内延伸 height、宽 thickness）任一边距离
        ≤ do/2 + clearance 即干涉，clearance = bridge_k × 名义孔桥宽度（k 默认 1.0）。
        再由 `slipway.py:1594-1608` 按干涉管所在的整行 y 扩展删除。
        """
        if self.result is None:
            return []
        from .placement import nominal_bridge_width
        from .impingement import _dist_to_segment

        do = self._float("换热管外径 do") or 0.0
        bridge = nominal_bridge_width(do)
        limit = do / 2.0 + bridge  # bridge_k 默认 1.0

        cx, cy = float(geometry["center"][0]), float(geometry["center"][1])
        height, thickness = float(geometry["size"][0]), float(geometry["size"][1])
        angle = math.radians(float(geometry.get("angle") or 0.0))
        # 滑道局部矩形：中心 (0,0)，长 height（径向，沿 angle 方向），宽 thickness（切向）
        ux, uy = math.cos(angle), math.sin(angle)      # 径向单位向量
        vx, vy = -uy, ux                               # 切向单位向量
        corners = []
        for a, b in ((height / 2, thickness / 2), (height / 2, -thickness / 2),
                     (-height / 2, -thickness / 2), (-height / 2, thickness / 2)):
            corners.append((cx + a * ux + b * vx, cy + a * uy + b * vy))
        edges = [(corners[i], corners[(i + 1) % 4]) for i in range(4)]

        def hits_rect(px, py):
            inside = True
            for (x1, y1), (x2, y2) in edges:
                cross = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
                # 矩形按顶点顺序，法向同号表示在内侧
                if cross < -1e-9:
                    inside = False
                    break
            if inside:
                return True
            return any(
                _dist_to_segment(px, py, x1, y1, x2, y2) <= limit
                for (x1, y1), (x2, y2) in edges
            )

        pool = list(self.result.master_centers)
        # 完全照正式程序 slipway.py:1454-1482 / 1594-1650：
        #   ① 先算与滑道矩形真正干涉的管（管心到矩形任一边 ≤ do/2+clearance）；
        #   ② 收集这些干涉管的 y 行键（round 6 位，避免浮点漏行）；
        #   ③ 把该 y 行上的**所有**管孔整行删掉，而不只是几何压到的那几根；
        #   ④ 再按管程程数做镜像联动。
        # 之前"只删矩形∩管心的管"是错的：滑道是一整条，它跨过的每一行都装不下管，
        # 正式程序整行删除。用户 2026-11-22 反馈"删的啥啊，应该整行删"。
        interfering = [(x, y) for (x, y) in pool if hits_rect(x, y)]
        if not interfering:
            return []
        y_keys = {round(float(y), 6) for (_, y) in interfering}
        whole_rows = [
            (x, y) for (x, y) in pool if round(float(y), 6) in y_keys
        ]
        # judge_linkage_x / judge_linkage_y：按管程补镜像，与防冲板删管一致
        return self._linkage_mirror_centers(whole_rows)

    def _screw_ring_geometries(self, count: int) -> list[dict]:
        """吊环螺钉不选管：按数量 + 起始方位角沿管板外圆均布。"""
        count = max(1, int(count))
        start = self._float("吊环螺钉起始方位角") or 0.0
        pitch = self._float("吊环螺钉孔中心距") or 50.0
        outer = self.result.big_r_wai if self.result else 500.0
        radius = max(outer - pitch / 2.0, pitch / 2.0)
        items = []
        for index in range(count):
            rad = math.radians(start + index * (360.0 / count))
            items.append({
                "center": (radius * math.cos(rad), radius * math.sin(rad)),
                "size": (14.0, 14.0),
            })
        return items

    def apply_placement_plan(self, items) -> dict:
        """把用户确认过的方案落到图形：选孔由程序按真实管孔算，模型不给坐标。

        各元件的选管规则照抄正式程序按钮入口（见 bundle/placement.ANCHORS）：
        防冲板/中间挡板/中间挡管必须落在两根相邻参照管上，拉杆由 1 个种子管
        对称展开，滑道与吊环螺钉完全由参数定位。
        """
        from .placement import KIND_LABEL, OPTION_FIELDS

        if self.result is None:
            return {"ok": False, "rows": [], "message": "当前还没有布管结果，无法布置元件"}

        holes_before = len(self.current_centers())
        rows: list[dict] = []
        used: set = set()
        need_recompute = False
        self._push_undo()

        for item in items:
            # 1) 只把“选择类”参数写回（形式/位置/安装方式…）；数值参数一律用参数表当前值，
            #    避免模型编一个板厚/直径把表里默认值悄悄改掉。用户在方案卡上亲手改过的
            #    参数（item.overrides）则照单写回——那是用户确认过的布置参数。
            allowed = OPTION_FIELDS.get(item.kind, ())
            values = {
                name: item.options[name]
                for name in item.options
                if name in allowed
                and name in self.parameters
                and _is_choice_param(name)
            }
            values.update({
                name: value
                for name, value in item.overrides.items()
                if name in allowed and name in self.parameters
            })
            if values:
                self._write_back(values)

            row = {
                "label": item.label,
                "kind": item.kind,
                "requested": item.count,
                "placed": 0,
                "skipped": 0,
                "detail": "",
            }
            kind = item.kind
            if kind not in KIND_LABEL:
                row["skipped"] = item.count
                row["detail"] = "不认识的元件类型，已跳过"
                rows.append(row)
                continue

            # 2) 参数型：折流板影响外径虚线圆、切口弦线与轴向设计
            if kind == "baffle":
                need_recompute = True
                row["placed"] = 1
                row["detail"] = "已按新参数重算折流板外径圆和切口弦线"
                rows.append(row)
                continue

            # 3) 不选管的元件：滑道 / 吊环螺钉
            if kind == "slide":
                for geometry in self._slide_geometries():
                    # 源程序 slipway.py：滑道压到的换热管孔要删掉（整行 y）。
                    deleted = self._slide_delete_centers(geometry)
                    geometry["deleted"] = deleted
                    self.removed.update(deleted)
                    self.components.append(dict(geometry, kind="slide"))
                    row["placed"] += 1
                rows.append(row)
                continue

            if kind == "screw_ring":
                geometries = self._screw_ring_geometries(item.count)
                for geometry in geometries:
                    self.components.append(dict(geometry, kind="screw_ring"))
                row["placed"] = len(geometries)
                self.set_parameter("吊环螺钉数量", str(row["placed"]), "AI 布置方案", run_linkage=False)
                rows.append(row)
                continue

            pool = [c for c in self.current_centers() if c not in used]

            # 4) 拉杆 / 自由拉杆：1 个种子管 → 对称展开（judge_linkage）
            if kind in {"rod", "free_rod"}:
                rod_d = self._float("拉杆直径") or 16.0
                do = self._float("换热管外径 do") or 25.0
                if rod_d > do + 1e-6:
                    row["skipped"] = item.count
                    row["detail"] = f"拉杆直径 {rod_d:g} 大于换热管外径 {do:g}，无法穿入管孔"
                    rows.append(row)
                    continue
                placed = self._resolve_item(item, pool)["tubes"]
                for center in placed:
                    used.add(center)
                    self.removed.add(center)
                    self.components.append({"kind": kind, "center": center})
                row["placed"] = len(placed)
                row["skipped"] = max(item.count - len(placed), 0)
                if row["skipped"]:
                    row["detail"] = f"可对称落位的管孔不足，只布置了 {row['placed']} 根"
                rows.append(row)
                continue

            # 5a) 防冲板：三种形式几何完全不同（正式程序 build_impingement_plate）
            if kind in {"impingement", "impingement_folded", "impingement_welded"}:
                form = self._impingement_form(item)
                row["label"] = f"{form}防冲板"
                if form == impingement.FORM_WELDED:
                    # 焊接式不依附管孔：宽度 + 方位角 + 至圆筒内壁距离
                    try:
                        geometry = self._impingement_geometry(
                            impingement.FORM_WELDED, None, item.overrides
                        )
                    except impingement.ImpingementError as exc:
                        row["skipped"] = item.count
                        row["detail"] = str(exc)
                        rows.append(row)
                        continue
                    deleted_count, deleted_rod_count = self._apply_impingement_deletions(
                        geometry, form, None
                    )
                    row["deleted"] = deleted_count
                    row["deleted_rods"] = deleted_rod_count
                    if deleted_rod_count:
                        row["detail"] = f"删除 {deleted_rod_count} 根干涉拉杆"
                    self.components.append(geometry)
                    row["placed"] = 1
                    rows.append(row)
                    continue
                picks = self._resolve_item(item, pool)["pairs"]
                if not picks:
                    row["skipped"] = item.count
                    row["detail"] = "找不到合适的参照管对"
                for pair in picks:
                    try:
                        geometry = self._impingement_geometry(form, pair, item.overrides)
                    except impingement.ImpingementError as exc:
                        row["skipped"] += 1
                        row["detail"] = str(exc)
                        continue
                    # 正式程序 build_impingement_plate：落位后立刻删掉干涉换热管
                    # （矩形带/折边三段 + 弦外弓形区 + 管程镜像）
                    deleted_count, deleted_rod_count = self._apply_impingement_deletions(
                        geometry, form, pair
                    )
                    row["deleted"] = row.get("deleted", 0) + deleted_count
                    row["deleted_rods"] = row.get("deleted_rods", 0) + deleted_rod_count
                    self.components.append(geometry)
                    used.update(pair)
                    row["placed"] += 1
                if row.get("deleted"):
                    note = f"删掉 {row['deleted']} 个干涉换热管"
                    row["detail"] = f"{row['detail']}；{note}" if row["detail"] else note
                if row.get("deleted_rods"):
                    note = f"删除 {row['deleted_rods']} 根干涉拉杆"
                    row["detail"] = f"{row['detail']}；{note}" if row["detail"] else note
                rows.append(row)
                continue

            # 5b) 中间挡板：必须落在隔板槽两侧第一排的两根参照管上
            if kind == "center_baffle":
                pairs = self._resolve_item(item, pool)["pairs"]
                for pair in pairs:
                    side, reason = self._center_baffle_check(pair)
                    if reason:
                        row["skipped"] += 1
                        row["detail"] = reason
                        continue
                    geometry = self._pair_geometry(kind, pair, side)
                    self.components.append(dict(geometry, kind=kind))
                    used.update(pair)
                    row["placed"] += 1
                row["skipped"] = max(item.count - row["placed"], 0)
                if row["skipped"]:
                    row["detail"] = "可用的相邻参照管不足，未布满"
                rows.append(row)
                continue

            # 6) 中间挡管：2 个参照管 → 挡管落在连线与隔板槽轴线的交点上
            if kind == "block_tube":
                pairs = self._resolve_item(item, pool)["pairs"]
                for pair in pairs:
                    center, error = self._block_tube_point(pair)
                    if error:
                        row["skipped"] += 1
                        row["detail"] = error
                        continue
                    if abs(center[0]) < 1e-6 and abs(center[1]) < 1e-6:
                        # 正式程序同样跳过落到圆心的挡管（没有可替换的管孔）
                        continue
                    self.removed.add(center)
                    self.components.append({"kind": "block_tube", "center": center})
                    used.update(pair)
                    row["placed"] += 1
                row["skipped"] = max(item.count - row["placed"], 0)
                if row["skipped"] and not row["detail"]:
                    row["detail"] = "可用的相邻参照管不足，未布满"
                rows.append(row)
                continue

            # 7) 旁路挡板：每个参照管各一块，板的外边缘贴折流板外径圆；
            #    勾“对称分布”时源程序走 judge_linkage，一个参照管铺 4 块
            if kind == "bypass":
                centers = self._resolve_item(item, pool)["tubes"]
                targets = self._linkage_expand(centers, pool) if self._symmetry else centers
                # 源程序里旁路挡板在折流板缺口侧、滑道在壳体底部，两者不重叠。
                # 自动选点按 near_shell 会挑到最外圈（含底部滑道位置），这里把落在
                # 滑道方位扇区内的参照管剔除，避免旁路挡板与滑道画在一起。
                slide_angles = [math.radians(float(g.get("angle") or 0.0))
                                for g in self._slide_geometries()]
                if slide_angles:
                    def _near_slide(pt):
                        px, py = float(pt[0]), float(pt[1])
                        if math.hypot(px, py) < 1e-6:
                            return False
                        a = math.atan2(py, px)
                        return any(abs(math.atan2(math.sin(a - sa), math.cos(a - sa))) < math.radians(18)
                                   for sa in slide_angles)
                    targets = [p for p in targets if not _near_slide(p)]
                widths: list[float] = []
                for center in targets:
                    geometry = self._bypass_geometry(center, pool)
                    widths.append(max(float(v) for v in geometry["size"]))
                    self.components.append(dict(geometry, kind="bypass"))
                    used.add(center)
                    row["placed"] += 1
                if widths and "旁路挡板宽度" in self.parameters:
                    # 正式程序把算出来的宽度写回参数表，参数区显示的就是这个值
                    self.set_parameter(
                        "旁路挡板宽度", self._pretty(widths[0]), "AI 布置方案", run_linkage=False
                    )
                row["skipped"] = max(item.count - row["placed"], 0)
                rows.append(row)
                continue

            # 8) 径向开孔：落在选中/指定管孔上
            for center in self._resolve_item(item, pool)["tubes"]:
                used.add(center)
                self.components.append({"kind": "radial_hole", "center": center})
                row["placed"] += 1
            row["skipped"] = max(item.count - row["placed"], 0)
            rows.append(row)

        self._clear_selection_state()
        if need_recompute:
            self.recompute(reason="折流板参数已按方案更新", keep_components=True)
        else:
            self.rebuild_scene()
            self.refresh_hole_table()

        holes_after = len(self.current_centers())
        total = sum(row["placed"] for row in rows)
        self.status_message.emit(
            f"已按布置方案布置 {total} 个元件（占用 {holes_before - holes_after} 个管孔），"
            f"当前剩 {holes_after} 个换热管孔"
        )
        return {
            "ok": total > 0,
            "rows": rows,
            "holes_before": holes_before,
            "holes_after": holes_after,
            "occupied": holes_before - holes_after,
        }


    # ------------------------------------------------ 换热管增删（对话里删/补管）
    def _hole_op_pool(self, op) -> list[tuple[float, float]]:
        """这条操作的作用池：删管看当前还在的换热管，补管看被删掉的那些。"""
        if op.op == "restore":
            occupied = {
                (round(float(c["center"][0]), 6), round(float(c["center"][1]), 6))
                for c in self.components if c.get("center")
            }
            # 没指定位置又没指定根数 = “把刚才删掉的管还回来”：只认最近一批，
            # 免得把防冲板干涉删除、拉杆占孔那些历史删除也一起恢复
            batch = self._last_hole_delete if (op.region == "any" and not op.count) else []
            source = batch or list(self.removed)
            return [
                (float(x), float(y)) for x, y in source
                if (round(float(x), 6), round(float(y), 6)) not in occupied
                and any((round(float(c[0]), 6), round(float(c[1]), 6))
                        == (round(float(x), 6), round(float(y), 6)) for c in self.removed)
            ]
        return self.current_centers()

    def _outline_ring(self, pool, layers: int = 1):
        """布管外轮廓：每行最左、最右各 layers 根，**再加最上、最下一整排**。

        以前按半径逐层剥离（±40° 扇形内没有更靠外的邻管才算最外层），
        正三角形布管下算出来是贯穿中间的锯齿——行19列-3、行18列-4、行11列-9…
        用户的原话是“不就是每行最左、最右的换热管吗”，于是改成按行取两端。

        但只取两端时，左右两条弧爬到 0°/180° 就断了，顶部那一排（示例 6 根）
        和底部那一排的中间几根空着——用户在图上一眼圈出来：最上和最下一整排
        也属于外轮廓。所以：中间各行取两端，最上 / 最下各 layers 排整排全取。
        """
        from .placement import group_lines

        out: list[tuple[float, float]] = []
        seen: set[tuple[float, float]] = set()
        lines = group_lines(pool, "row")          # 行按 y 由高到低排好，lines[0] 是最上一排
        take = max(1, int(layers))
        cap = min(take, len(lines))
        caps = set(range(cap)) | {len(lines) - 1 - i for i in range(cap)}
        for index, line in enumerate(lines):
            ordered = sorted(line, key=lambda c: c[0])
            if index in caps:                     # 最上 / 最下一整排，整排都要
                points = list(ordered)
            else:
                n = max(1, min(len(ordered), take))
                points = list(ordered[:n]) + list(ordered[-n:])
            for point in points:
                key = (round(point[0], 6), round(point[1], 6))
                if key in seen:
                    continue
                seen.add(key)
                out.append((float(point[0]), float(point[1])))
        out.sort(key=lambda c: (-round(c[1], 3), c[0]))
        return out

    def _boundary_ring(self, pool, layers: int = 1, outer: bool = True):
        """取“最外层/最内层”的若干圈管孔。

        以前 near_shell 只是按半径排个序，count 给 0 时整片 630 根全中——
        用户说“删最外一圈”结果全删了。这里按“这一圈有没有更靠外的邻管”逐层剥离：
        对每根管，若在 ±40° 扇形、1.8 倍中心距内有更靠外的管，它就还在里面一层。
        """
        remaining = list(pool)
        pitch = float(getattr(self.result, "S", 0) or 0) or 32.0
        picked: list[tuple[float, float]] = []
        span = math.radians(40.0)
        for _ in range(max(1, int(layers))):
            if not remaining:
                break
            layer = []
            for point in remaining:
                rp = math.hypot(point[0], point[1])
                ap = math.atan2(point[1], point[0])
                edge = True
                for other in remaining:
                    if other is point:
                        continue
                    ro = math.hypot(other[0], other[1])
                    if (ro <= rp + 1e-6) if outer else (ro >= rp - 1e-6):
                        continue
                    delta = abs((math.atan2(other[1], other[0]) - ap + math.pi)
                                % (2 * math.pi) - math.pi)
                    if delta <= span and math.hypot(
                        other[0] - point[0], other[1] - point[1]
                    ) <= 1.8 * pitch:
                        edge = False
                        break
                if edge:
                    layer.append(point)
            if not layer:
                break
            picked.extend(layer)
            drop = {id(p) for p in layer}
            remaining = [p for p in remaining if id(p) not in drop]
        picked.sort(key=lambda c: (-round(c[1], 3), c[0]))
        return picked

    def resolve_hole_op(self, op) -> list[tuple[float, float]]:
        """把“删哪几根”解析成真实管孔：模型只给区域/排数，坐标一律由程序算。

        区域照正式程序删管的几何含义：
        · groove：隔板槽两侧——按到槽线的距离分行/分列，两侧各取最近 rows 排；
        · near_shell / center：按到圆心的距离由外向内 / 由内向外；
        · top/bottom/left/right：按坐标排序取一整片；
        · selected：用图上当前选中的管孔。
        """
        from .placement import group_lines

        pool = self._hole_op_pool(op)
        if not pool:
            return []
        region = op.region
        chosen: list[tuple[float, float]] = []
        if getattr(op, "tubes", None):
            # 模型自己看着布管图挑的管孔：照单执行，程序不插嘴改口径
            centers, problems = self.centers_for_refs(
                list(op.tubes), "restore" if op.op == "restore" else "delete"
            )
            self._ref_problems = problems
            chosen = centers
        elif region == "selected":
            wanted = {(round(c[0], 6), round(c[1], 6)) for c in self.selected}
            chosen = [c for c in pool if (round(c[0], 6), round(c[1], 6)) in wanted]
            # 删管时若选中集合全是“已删除的管”，说明用户想反向恢复，交给 restore 分支
        elif region == "removed":
            wanted = {(round(c[0], 6), round(c[1], 6)) for c in self.removed_centers()}
            chosen = [c for c in pool if (round(c[0], 6), round(c[1], 6)) in wanted]
        elif region == "groove":
            axis = self._groove_axis()
            orient = "row" if axis == "y" else "col"
            index = 1 if orient == "row" else 0
            positive: list[tuple[float, list]] = []
            negative: list[tuple[float, list]] = []
            for line in group_lines(pool, orient):
                coord = float(line[0][index])
                if abs(coord) < 1e-6:
                    continue                      # 正压在槽线上的那排不参与
                (positive if coord > 0 else negative).append((abs(coord), line))
            positive.sort(key=lambda item: item[0])
            negative.sort(key=lambda item: item[0])
            take = max(1, int(op.rows))
            for _distance, line in positive[:take] + negative[:take]:
                chosen.extend(line)
            chosen.sort(key=lambda c: (-round(c[1], 3), c[0]))
        elif region in {"near_shell", "outline"}:
            # “最外层”= 布管轮廓，每行最左、最右各 rows 根 + 最上/最下各 rows 整排
            chosen = self._outline_ring(pool, max(1, int(op.rows)))
        elif region == "center":
            # “最内圈”仍然按半径由内向外剥离，rows 是圈数
            chosen = self._boundary_ring(pool, layers=max(1, int(op.rows)), outer=False)
        elif region in {"top", "bottom", "left", "right"}:
            key = {
                "top": lambda c: (-c[1], c[0]),
                "bottom": lambda c: (c[1], c[0]),
                "left": lambda c: (c[0], -c[1]),
                "right": lambda c: (-c[0], -c[1]),
            }[region]
            lines = group_lines(pool, "row" if region in {"top", "bottom"} else "col")
            lines = sorted(
                lines,
                key=lambda line: (
                    -max(abs(c[1]) for c in line) if region == "top"
                    else max(abs(c[1]) for c in line) if region == "bottom"
                    else -max(abs(c[0]) for c in line) if region == "right"
                    else max(abs(c[0]) for c in line)
                ),
            )
            chosen = []
            for line in lines[: max(1, int(op.rows))]:
                chosen.extend(sorted(line, key=key))
        else:
            chosen = sorted(pool, key=lambda c: (-round(c[1], 3), c[0]))
        if op.count:
            chosen = chosen[: int(op.count)]
        return [(float(c[0]), float(c[1])) for c in chosen]

    def preview_hole_ops(self, ops) -> dict:
        """换热管增删方案：先在图上圈出来给用户过目，确认后才改图。"""
        rows = []
        picked: list[tuple[float, float]] = []
        problems: list[str] = []
        holes = len(self.current_centers())
        delta = 0
        for op in ops:
            self._ref_problems = []
            centers = self.resolve_hole_op(op)
            problems.extend(self._ref_problems)     # 模型给的行列号查不到的，如实报出来
            rows.append({
                "op": op.op,
                "label": op.label,
                "where": op.describe(),
                "count": len(centers),
                "refs": [self._tube_ref(c) for c in centers[:8]],
                "more": max(len(centers) - 8, 0),
            })
            picked.extend(centers)
            delta += len(centers) if op.op == "restore" else -len(centers)
        if picked:
            self.select_centers(picked)
        return {
            "rows": rows,
            "holes": holes,
            "remaining": max(holes + delta, 0),
            "total": sum(row["count"] for row in rows),
            "problems": problems,
        }

    def apply_hole_ops(self, ops) -> dict:
        """落地方案：删管=从管孔池里去掉，补管=把之前删掉的管还回来。"""
        if self.result is None:
            return {"ok": False, "rows": [], "message": "当前还没有布管结果"}
        self._push_undo()
        holes_before = len(self.current_centers())
        rows = []
        deleted_batch: list[tuple[float, float]] = []
        for op in ops:
            centers = self.resolve_hole_op(op)
            targets = {(round(c[0], 6), round(c[1], 6)) for c in centers}
            changed = 0
            if op.op == "restore":
                for center in centers:
                    key = (round(center[0], 6), round(center[1], 6))
                    for existing in [c for c in self.removed if (round(c[0], 6), round(c[1], 6)) == key]:
                        self.removed.discard(existing)
                        changed += 1
            else:
                kept = []
                for component in self.components:
                    center = component.get("center")
                    if (
                        component.get("kind") in {"rod", "free_rod", "block_tube"}
                        and center
                        and (round(float(center[0]), 6), round(float(center[1]), 6)) in targets
                    ):
                        continue
                    kept.append(component)
                self.components = kept
                for center in centers:
                    key = (round(center[0], 6), round(center[1], 6))
                    if not any((round(c[0], 6), round(c[1], 6)) == key for c in self.removed):
                        self.removed.add((float(center[0]), float(center[1])))
                        deleted_batch.append((float(center[0]), float(center[1])))
                        changed += 1
            rows.append({
                "label": op.label,
                "where": op.describe(),
                "changed": changed,
                "requested": len(centers),
            })
        if deleted_batch:
            self._last_hole_delete = list(deleted_batch)
        self._clear_selection_state()
        self.rebuild_scene()
        self.refresh_hole_table()
        holes_after = len(self.current_centers())
        return {
            "ok": any(row["changed"] for row in rows),
            "rows": rows,
            "holes_before": holes_before,
            "holes_after": holes_after,
            "message": "" if any(row["changed"] for row in rows) else "这个范围内没有可调整的换热管",
        }

    def select_region(self, region: str, rows: int = 1, count: int = 0,
                      include_removed: bool = False) -> list[tuple[float, float]]:
        """按区域选管（“选中最外一圈”“选中隔板槽两侧”这类界面操作）。

        和智能删管共用一套区域规则，落点全由当前布管结果算出来，图上立即高亮。
        """
        from .placement import HoleOp

        op = HoleOp(op="delete", region=region, count=count, rows=rows)
        centers = self.resolve_hole_op(op)
        if include_removed:
            wanted = {(round(c[0], 6), round(c[1], 6)) for c in self.removed_centers()}
            extra = [c for c in self.result.master_centers
                     if (round(c[0], 6), round(c[1], 6)) in wanted
                     and (round(c[0], 6), round(c[1], 6))
                     not in {(round(x[0], 6), round(x[1], 6)) for x in centers}]
            centers.extend(extra)
        self.select_centers(centers)
        return centers

    def hole_coordinates(self) -> list[dict]:
        """满布管孔的全量坐标表（行列号 + X/Y + 当前状态），用于“列出所有坐标”。"""
        if self.result is None:
            return []
        alive = {(round(c[0], 6), round(c[1], 6)) for c in self.current_centers()}
        rows = []
        for center in self.result.master_centers:
            key = (round(center[0], 6), round(center[1], 6))
            ref = self._tube_ref(center)
            ref["state"] = "在" if key in alive else (
                "已删除" if center in self.removed else "占孔"
            )
            rows.append(ref)
        return rows

    # ------------------------------------------------------------ 给模型“看”的布管图
    # Agent 得先看得见，才谈得上自己判断。这里把当前布管画成一张字符图：
    # 模型看图决定“外轮廓/某一圈/上部”到底是哪几根，再用行列号回指；
    # 程序只负责把它指的那些管孔找出来、落到图上，不再替它解释“最外层”是什么。
    def plan_view_text(self) -> str:
        if self.result is None:
            return ""
        master = [(float(c[0]), float(c[1])) for c in self.result.master_centers]
        if not master:
            return ""
        alive = {(round(c[0], 6), round(c[1], 6)) for c in self.current_centers()}
        removed = {(round(c[0], 6), round(c[1], 6)) for c in self.removed}
        pitch = float(getattr(self.result, "S", 0) or 0) or 32.0
        step = max(pitch / 2.0, 1e-6)
        xmin = min(c[0] for c in master)
        xmax = max(c[0] for c in master)
        width = int(round((xmax - xmin) / step)) + 1

        lines_by_row: dict[int, list[tuple[int, float, float]]] = {}
        max_col = 0
        for center in master:
            row_col = self.tube_row_col(center)
            if row_col is None:
                continue
            row, col = row_col
            max_col = max(max_col, abs(col))
            lines_by_row.setdefault(row, []).append((col, center[0], center[1]))
        order = sorted(lines_by_row, key=lambda r: (-abs(r), -r))

        out = [
            "布管图（o=换热管在  x=已删除  #=被元件占孔；"
            "行号：上正下负、1 是贴中心线那排；列号：靠近竖直中心线为 1、左右各一套，0 是正中间那根）",
        ]
        for row in order:
            line = sorted(lines_by_row[row], key=lambda item: item[1])
            cells = [" "] * width
            cols = []
            for col, cx, cy in line:
                index = int(round((cx - xmin) / step))
                if 0 <= index < width:
                    key = (round(cx, 6), round(cy, 6))
                    cells[index] = "o" if key in alive else ("x" if key in removed else "#")
                cols.append(col)
            text = "".join(cells).rstrip()
            y = line[0][2] if line else 0.0
            out.append(
                f"行{row:+d} y={y:7.1f} |{text}| {len(line):2d}根 列[{','.join(str(c) for c in cols)}]"
            )
        out.append(
            f"共 {len(master)} 个管孔（可用 {len(alive)}、已删除 {len(master) - len(alive)}），"
            f"中心距 S={pitch:g}，每侧最多 {max_col} 列"
        )
        return "\n".join(out)

    def centers_for_refs(self, refs, op: str = "delete") -> tuple[list[tuple[float, float]], list[str]]:
        """模型给的行列号 → 真实管孔坐标。程序只做“查得到/状态对不对”，不改口径。

        op="delete" 只认当前还在的换热管；op="restore" 只认已删除的管孔；
        op="select" 两者都认（图上都能点）。找不到的逐个回一句人话。
        """
        from .placement import row_col_of

        centers: list[tuple[float, float]] = []
        problems: list[str] = []
        alive = {(round(c[0], 6), round(c[1], 6)) for c in self.current_centers()}
        removed = {(round(c[0], 6), round(c[1], 6)) for c in self.removed_centers()}
        seen: set[tuple[float, float]] = set()
        for ref in refs or []:
            row, col = row_col_of(ref)
            if row is None:
                problems.append(f"看不懂这个管孔位置：{ref}")
                continue
            center = self.center_for_row_col(row, col)
            if center is None:
                problems.append(f"行{row}列{col} 上没有管孔")
                continue
            key = (round(center[0], 6), round(center[1], 6))
            if key in seen:
                continue
            if op == "delete" and key not in alive:
                problems.append(f"行{row}列{col} 现在不是可删的换热管")
                continue
            if op == "restore" and key not in removed:
                problems.append(f"行{row}列{col} 不是已删除的管孔")
                continue
            seen.add(key)
            centers.append(center)
        return centers, problems

    # ------------------------------------------------------------ 元件数据字典
    # 每个元件在正式程序里都有一份自己的数据（拉杆有形式/直径，挡板有板长/板厚，
    # 防冲板有形式/折边角…）。用户要“拉杆坐标”时，必须给拉杆这份数据，
    # 不能一律摊换热管表。
    COMPONENT_SPEC = {
        "rod": ("拉杆形式", "拉杆直径"),
        "free_rod": ("自由拉杆形式", "自由拉杆直径"),
        "block_tube": ("中间挡管安装方式",),
        "bypass": ("旁路挡板宽度", "旁路挡板厚度"),
        "center_baffle": ("中间挡板厚度",),
        "impingement": ("防冲板形式", "防冲板厚度", "防冲板宽度"),
        "impingement_folded": ("防冲板形式", "防冲板厚度", "防冲板折边角度"),
        "impingement_welded": ("防冲板形式", "防冲板厚度", "防冲板宽度"),
        "slide": ("滑道形式", "滑道高度"),
        "screw_ring": ("吊环螺钉规格",),
        "radial_hole": (),
    }

    # 会占掉一个换热管孔的元件（放上去时 removed.add(孔)，删掉时要把孔还回去）
    OCCUPYING_KINDS = {"rod", "free_rod", "block_tube", "radial_hole"}

    @staticmethod
    def _kind_match(comp_kind: str, wanted: str) -> bool:
        """元件类型匹配：空=全部；impingement 覆盖三种防冲板形式。"""
        if not wanted:
            return True
        if comp_kind == wanted:
            return True
        return wanted == "impingement" and comp_kind.startswith("impingement")

    def component_coordinates(self, kind: str = "") -> dict:
        """按元件类型摊出各自的数据字典（“输出所有拉杆坐标”就只给拉杆）。

        字段照正式程序：拉杆=形式 + 直径 LB_TieRodD + 所在管孔行列号 + 绝对坐标；
        挡板类=板长/板厚/中心坐标；不占孔的元件（滑道、吊环螺钉）没有行列号。
        """
        wanted = str(kind or "").strip()
        label = COMPONENT_LABEL.get(wanted, "全部元件") if wanted else "全部元件"
        rows: list[dict] = []
        for index, comp in enumerate(self.components, start=1):
            comp_kind = str(comp.get("kind") or "")
            if not self._kind_match(comp_kind, wanted):
                continue
            center = comp.get("center") or (0.0, 0.0)
            cx, cy = float(center[0]), float(center[1])
            occupied = comp_kind in self.OCCUPYING_KINDS
            ref = self._tube_ref((cx, cy)) if occupied else {}
            spec: list[str] = []
            for name in self.COMPONENT_SPEC.get(comp_kind, ()):
                value = str(comp.get(name) or self._param_text(name) or "").strip()
                if not value:
                    continue
                if name.endswith("直径"):
                    spec.append(f"φ{value}")
                else:
                    spec.append(value)
            size = comp.get("size") or ()
            if size and len(size) >= 2:
                spec.append(f"{float(size[0]):g}×{float(size[1]):g}")
            if comp.get("length"):
                spec.append(f"板长{float(comp['length']):g}")
            angle = comp.get("angle")
            if angle not in (None, 0, 0.0):
                spec.append(f"{float(angle):g}°")
            rows.append({
                "no": len(rows) + 1,
                "name": COMPONENT_LABEL.get(comp_kind, comp_kind),
                "spec": " ".join(spec) or "-",
                "row": ref.get("row", ""),
                "col": ref.get("col", ""),
                "x": cx,
                "y": cy,
                "note": str(comp.get("note") or ("占孔" if occupied else "不占孔")),
            })
        return {"kind": wanted, "label": label, "rows": rows}

    def component_kinds(self) -> list[tuple[str, str, int]]:
        """当前图上所有元件类型及数量：[(kind, 中文名, 个数)]。"""
        counts: dict[str, int] = {}
        for comp in self.components:
            kind = str(comp.get("kind") or "")
            counts[kind] = counts.get(kind, 0) + 1
        order = list(COMPONENT_LABEL)
        return [
            (kind, COMPONENT_LABEL.get(kind, kind), counts[kind])
            for kind in order if counts.get(kind)
        ]

    def remove_components(self, kind: str = "") -> dict:
        """删掉某一类（或全部）元件，并把占用的管孔还给换热管。

        这就是“把拉杆恢复为换热管”的落地：拉杆当初是 removed.add(孔) + 记一条
        component 画出来的，删元件时同步 discard 那个孔，管子就回图上了。
        """
        if not self.components:
            return {"ok": False, "removed": 0, "restored": 0,
                    "message": "图上还没有布置任何元件"}
        wanted = str(kind or "").strip()
        self._push_undo()
        kept = []
        removed = 0
        restored = 0
        for comp in self.components:
            comp_kind = str(comp.get("kind") or "")
            hit = self._kind_match(comp_kind, wanted)
            if not hit:
                kept.append(comp)
                continue
            removed += 1
            center = comp.get("center")
            if center and comp_kind in self.OCCUPYING_KINDS:
                key = (round(float(center[0]), 6), round(float(center[1]), 6))
                for existing in [
                    c for c in self.removed
                    if (round(float(c[0]), 6), round(float(c[1]), 6)) == key
                ]:
                    self.removed.discard(existing)
                    restored += 1
        self.components = kept
        self._clear_selection_state()
        self.rebuild_scene()
        self.refresh_hole_table()
        name = COMPONENT_LABEL.get(wanted, wanted) if wanted else "全部元件"
        return {
            "ok": removed > 0,
            "removed": removed,
            "restored": restored,
            "holes": len(self.current_centers()),
            "message": (
                f"已删除全部 {removed} 个{name}" + (f"，{restored} 个管孔恢复为换热管" if restored else "")
                if removed else f"图上没有{name}",
            )[0],
        }

    def place_impingement_top(self, count: int = 1) -> int:
        """防冲板：每块跨两根参照管，优先取上方（正式程序 on_dangban_click）。"""
        from .placement import pick_pairs

        if self.result is None or count <= 0:
            return 0
        form = (self._param_text("防冲板形式") or impingement.FORM_FLAT).strip()
        if form == impingement.FORM_WELDED:
            try:
                geometry = self._impingement_geometry(form)
            except impingement.ImpingementError:
                return 0
            self._push_undo()
            self.components.append(geometry)
            self.rebuild_scene()
            return 1
        min_span = 0.0
        if form == impingement.FORM_FOLDED:
            min_span = impingement.required_span_for_folded(
                self._float("换热管外径 do") or 25.0,
                self._float("换热管中心距 S") or 32.0,
                self._float("防冲板折边角度") or 45.0,
            )
        pairs = pick_pairs(self.current_centers(), count, "top", "row", min_span=min_span)
        geometries = []
        for pair in pairs:
            try:
                geometries.append(self._impingement_geometry(form, pair))
            except impingement.ImpingementError:
                continue
        if not geometries:
            return 0
        self._push_undo()
        self.components.extend(geometries)
        self.rebuild_scene()
        return len(geometries)
