"""
全局变量管理模块

这个模块提供了将 TubeLayoutEditor 实例的属性同步到全局变量的机制，
"""

# ========== 全局变量声明 ==========
# 中间挡管相关数据结构
center_dangguan = (
    []
)  # 存储挡管坐标对列表，格式：[[coord1, coord2], [coord3, coord4], ...]
center_dangguan_num = 0  # 记录中间挡管数量计数器
selected_center_dangguan = []  # 选中的中间挡管对象列表

# 是否为 b 型管板的 c/d/e 节点（例如 b_c、b_d、b_e）
is_b_cde_node = False

# 当前管板参数快照（包含节点信息），例如：
# {
#   "plate_type": "b_c",
#   "main_category": "b",
#   "node_name": "c",
#   "params": [(name, value), ...]
# }
tube_sheet_params_snapshot = {}

# 图形对象
graphics_scene = None  # QGraphicsScene 对象，用于添加和删除图形项
graphics_view = None  # QGraphicsView 对象，用于刷新视图

# 计算参数和坐标数据
r = 0  # 半径（用于绘制挡管圆形）
full_sorted_current_centers_up = []  # 上部中心点坐标列表（排序后）
full_sorted_current_centers_down = []  # 下部中心点坐标列表（排序后）

# 状态标志
isSymmetry = True  # 对称模式标志，True=对称模式，False=非对称模式

# 操作记录（可选）
operations = []  # 操作历史记录列表

axial_basic_params = {}

# ========== 当前活跃实例引用 ==========
_current_editor = None  # 存储当前活跃的 TubeLayoutEditor 实例引用


# ========== 同步函数 ==========
def sync_from_editor(editor):
    """
    从编辑器实例同步属性到全局变量

    参数:
        editor: TubeLayoutEditor 实例对象
    """
    global center_dangguan, center_dangguan_num, selected_center_dangguan
    global graphics_scene, graphics_view, r
    global full_sorted_current_centers_up, full_sorted_current_centers_down
    global isSymmetry, operations, _current_editor

    if editor is None:
        return

    # 保存实例引用（用于调用方法）
    _current_editor = editor

    # 同步数据结构属性（使用 getattr 安全获取，避免属性不存在时报错）
    center_dangguan = getattr(editor, "center_dangguan", [])
    center_dangguan_num = getattr(editor, "center_dangguan_num", 0)
    selected_center_dangguan = getattr(editor, "selected_center_dangguan", [])

    # 同步图形对象
    graphics_scene = getattr(editor, "graphics_scene", None)
    graphics_view = getattr(editor, "graphics_view", None)

    # 同步计算参数
    r = getattr(editor, "r", 0)
    full_sorted_current_centers_up = getattr(
        editor, "full_sorted_current_centers_up", []
    )
    full_sorted_current_centers_down = getattr(
        editor, "full_sorted_current_centers_down", []
    )

    # 同步状态标志
    isSymmetry = getattr(editor, "isSymmetry", True)

    # 同步操作记录（可选）
    operations = getattr(editor, "operations", [])


def sync_to_editor(editor):
    """
    将全局变量同步回编辑器实例（反向同步）

    注意：这个方法主要用于确保编辑器实例的属性与全局变量保持一致。
    通常在修改全局变量后，如果需要将更改反映到实例中，可以调用此方法。

    参数:
        editor: TubeLayoutEditor 实例对象
    """
    global center_dangguan, center_dangguan_num, selected_center_dangguan
    global graphics_scene, graphics_view, r
    global full_sorted_current_centers_up, full_sorted_current_centers_down
    global isSymmetry, operations

    if editor is None:
        return

    # 将全局变量同步回实例属性
    editor.center_dangguan = center_dangguan
    editor.center_dangguan_num = center_dangguan_num
    if hasattr(editor, "selected_center_dangguan") or selected_center_dangguan:
        editor.selected_center_dangguan = selected_center_dangguan

    # 图形对象通常不应该反向同步（它们是实例特定的）
    # 但为了完整性，这里保持注释
    # editor.graphics_scene = graphics_scene
    # editor.graphics_view = graphics_view

    # 同步计算参数（只读属性通常不需要反向同步，但为了安全起见可以同步）
    editor.r = r
    editor.full_sorted_current_centers_up = full_sorted_current_centers_up
    editor.full_sorted_current_centers_down = full_sorted_current_centers_down

    # 同步状态标志
    editor.isSymmetry = isSymmetry

    # 同步操作记录（可选）
    if hasattr(editor, "operations"):
        editor.operations = operations


def clear_variables():
    """
    清理全局变量（Tab关闭时调用）

    注意：这里只清理实例引用，不清理数据结构，因为：
    1. 数据可能还需要在其他地方使用
    2. 下次打开Tab时会重新同步
    """
    global _current_editor
    _current_editor = None
    # 如果需要完全清理，可以取消下面的注释
    # global center_dangguan, center_dangguan_num, selected_center_dangguan
    # center_dangguan = []
    # center_dangguan_num = 0
    # selected_center_dangguan = []


def get_current_editor():
    """
    获取当前活跃的编辑器实例引用

    返回:
        TubeLayoutEditor 实例对象，如果未初始化则返回 None

    用途:
        用于在 center_dangguan.py 中调用需要实例方法的地方，如：
        - editor.selected_to_current_coords()
        - editor.get_tube_pass_count()
        - editor.judge_linkage_y()
        - editor._draw_single_dangguan_pair()
    """
    return _current_editor


# ========== 辅助函数 ==========
def is_editor_initialized():
    """
    检查编辑器实例是否已初始化

    返回:
        bool: True 表示已初始化，False 表示未初始化
    """
    return _current_editor is not None


def update_center_dangguan(new_value):
    """
    更新 center_dangguan 全局变量，并同步回实例（如果存在）

    参数:
        new_value: 新的 center_dangguan 值
    """
    global center_dangguan
    center_dangguan = new_value

    # 同时更新实例（如果存在）
    editor = get_current_editor()
    if editor:
        editor.center_dangguan = new_value


def update_center_dangguan_num(new_value):
    """
    更新 center_dangguan_num 全局变量，并同步回实例（如果存在）

    参数:
        new_value: 新的 center_dangguan_num 值
    """
    global center_dangguan_num
    center_dangguan_num = new_value

    # 同时更新实例（如果存在）
    editor = get_current_editor()
    if editor:
        editor.center_dangguan_num = new_value


def update_selected_center_dangguan(new_value):
    """
    更新 selected_center_dangguan 全局变量，并同步回实例（如果存在）

    参数:
        new_value: 新的 selected_center_dangguan 值
    """
    global selected_center_dangguan
    selected_center_dangguan = new_value

    # 同时更新实例（如果存在）
    editor = get_current_editor()
    if editor:
        editor.selected_center_dangguan = new_value


def update_is_b_cde_node(new_value):
    """更新 is_b_cde_node 全局变量，并同步回实例（如果存在）"""
    global is_b_cde_node
    is_b_cde_node = bool(new_value)

    # 同时更新实例（如果存在）
    editor = get_current_editor()
    if editor:
        # 为兼容性，仅在实例上简单挂一个同名属性
        try:
            editor.is_b_cde_node = bool(new_value)
        except Exception:
            pass


def update_tube_sheet_params_snapshot(new_snapshot):
    """更新 tube_sheet_params_snapshot 全局快照，并同步回实例（如果存在）"""
    global tube_sheet_params_snapshot
    # 直接存储传入的结构，调用方负责构造
    tube_sheet_params_snapshot = new_snapshot if new_snapshot is not None else {}

    editor = get_current_editor()
    if editor:
        try:
            editor.tube_sheet_params_snapshot = tube_sheet_params_snapshot
        except Exception:
            pass

    from pprint import pformat

    try:
        print(pformat(tube_sheet_params_snapshot))
    except Exception:
        print(tube_sheet_params_snapshot)

    try:
        plate_type = tube_sheet_params_snapshot.get("plate_type")
        main_category = tube_sheet_params_snapshot.get("main_category")
        node_name = tube_sheet_params_snapshot.get("node_name")
        params = tube_sheet_params_snapshot.get("params", []) or []

        print(
            f"{prefix} plate_type: {plate_type}, main_category: {main_category}, node_name: {node_name}"
        )
        for name, value in params:
            print(f"{prefix} 参数 - {name}: {value}")
    except Exception as e:
        print(f"{prefix} 打印快照时发生异常: {e}")


def update_axial_basic_params(new_params):
    """增量更新轴向基本参数字典。

    不再清空原有内容，避免其他地方已写入的 DN、do 等参数被覆盖掉，
    只对 new_params 中出现的键进行更新。
    """
    global axial_basic_params
    if not isinstance(axial_basic_params, dict):
        axial_basic_params = {}
    if not new_params:
        return
    try:
        axial_basic_params.update(new_params)
    except Exception:
        pass
