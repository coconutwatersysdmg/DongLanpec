# -*- coding: utf-8 -*-
import json
import math
import os
import re
import sys
import time

import pymysql
import pythoncom
import win32com.client

from modules.TwoD.TwoD_peizhi import (
    get_autocad_instance,
    get_current_doc,
    wait_cad_idle,
    get_project_save_dir
)
from modules.TwoD.cad_context import CAD_CTX


def make_point(x, y, z=0.0):
    return win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8,
        (float(x), float(y), float(z))
    )


def parse_first_number(val):
    if val is None:
        return None
    s = str(val).strip()
    s = s.replace("Φ", "").replace("φ", "")
    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def get_app_root():
    """
    获取项目根路径
    源码运行：返回工程根目录
    打包运行：返回 exe 所在目录
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


# AutoCAD 正忙时常见的两个 COM 错误码
_RPC_E_CALL_REJECTED = -2147418111       # 0x80010001，被呼叫方拒绝接收呼叫
_RPC_E_SERVERCALL_RETRYLATER = -2147417846  # 0x8001010A，服务器正忙，请稍后重试


def _get_com_hresult(exc):
    """尽量从异常中取得 COM HRESULT。"""
    hresult = getattr(exc, "hresult", None)
    if hresult is not None:
        return hresult

    args = getattr(exc, "args", ())
    if args and isinstance(args[0], int):
        return args[0]

    return None


def _is_retryable_autocad_com_error(exc):
    """判断是否属于 AutoCAD 暂时忙碌、稍后重试即可的错误。"""
    return _get_com_hresult(exc) in {
        _RPC_E_CALL_REJECTED,
        _RPC_E_SERVERCALL_RETRYLATER,
    }


def autocad_com_retry(action, action_name, retries=30, delay=0.35):
    """
    对容易被 AutoCAD 临时拒绝的 COM 调用进行重试。

    只重试“AutoCAD 正忙”类型错误；其它错误立即抛出，避免掩盖真实问题。
    """
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            try:
                pythoncom.PumpWaitingMessages()
            except Exception:
                pass

            return action()

        except Exception as exc:
            last_error = exc

            if not _is_retryable_autocad_com_error(exc):
                raise

            if attempt >= retries:
                break

            sleep_seconds = min(delay * (1.0 + (attempt - 1) * 0.15), 1.5)
            print(
                f"⚠️ AutoCAD 正忙，{action_name}被暂时拒绝，"
                f"第 {attempt}/{retries} 次重试，等待 {sleep_seconds:.2f} 秒..."
            )
            time.sleep(sleep_seconds)

    raise RuntimeError(
        f"AutoCAD 长时间忙碌，{action_name}连续重试 {retries} 次仍失败"
    ) from last_error


def wait_autocad_ready(acad, timeout=20, stable_checks=3):
    """
    等待 AutoCAD 真正进入空闲状态。

    仅调用一次 wait_cad_idle 有时会过早返回，尤其是在已有多个图纸打开、
    文档正在切换或刚执行 SaveAs 时。这里额外检查 IsQuiescent，只有连续
    stable_checks 次处于空闲状态才返回。
    """
    end_time = time.time() + timeout
    stable_count = 0
    last_error = None

    while time.time() < end_time:
        try:
            try:
                pythoncom.PumpWaitingMessages()
            except Exception:
                pass

            try:
                wait_cad_idle(acad, timeout=1)
            except Exception as exc:
                last_error = exc
                if not _is_retryable_autocad_com_error(exc):
                    # 不同项目中的 wait_cad_idle 实现可能不完全一致，
                    # 后面继续使用 AutoCAD 自身的 IsQuiescent 判断。
                    pass

            is_quiescent = autocad_com_retry(
                lambda: bool(acad.GetAcadState().IsQuiescent),
                "检查 AutoCAD 空闲状态",
                retries=5,
                delay=0.2
            )

            if is_quiescent:
                stable_count += 1
                if stable_count >= stable_checks:
                    return True
            else:
                stable_count = 0

        except Exception as exc:
            last_error = exc
            stable_count = 0
            if not _is_retryable_autocad_com_error(exc):
                # GetAcadState 在少数版本不可用时，退回固定短暂等待。
                time.sleep(0.5)
                return True

        time.sleep(0.25)

    print(f"⚠️ 等待 AutoCAD 空闲超时，将继续尝试后续操作: {last_error}")
    return False


def _safe_doc_identity(doc):
    """取得用于比较 AutoCAD 文档的稳定标识。"""
    if doc is None:
        return None

    for attr in ("FullName", "Name"):
        try:
            value = autocad_com_retry(
                lambda a=attr: getattr(doc, a),
                f"读取文档 {attr}",
                retries=10,
                delay=0.2
            )
            if value:
                return os.path.normcase(os.path.abspath(str(value)))
        except Exception:
            pass

    return None


def cancel_active_autocad_command(acad):
    """
    如果当前活动图纸仍停留在某个命令中，发送两次 ESC 退出命令。

    上一个布管图保持打开时，AutoCAD 可能仍处于 ZOOM、REGEN、选择集或
    其它命令状态。此时直接 Documents.Add/Activate 很容易触发
    RPC_E_CALL_REJECTED。
    """
    try:
        active_doc = autocad_com_retry(
            lambda: acad.ActiveDocument,
            "获取当前活动文档",
            retries=10,
            delay=0.25
        )
    except Exception:
        return

    try:
        cmd_names = autocad_com_retry(
            lambda: str(active_doc.GetVariable("CMDNAMES") or "").strip(),
            "读取 AutoCAD 当前命令",
            retries=8,
            delay=0.2
        )
    except Exception:
        cmd_names = ""

    if not cmd_names:
        return

    print(f"ℹ️ AutoCAD 当前仍有命令未结束：{cmd_names}，正在自动取消。")

    try:
        autocad_com_retry(
            lambda: active_doc.SendCommand("\x1b\x1b"),
            "取消 AutoCAD 当前命令",
            retries=10,
            delay=0.25
        )
    except Exception as exc:
        print(f"⚠️ 自动取消当前命令失败，将继续等待: {exc}")

    wait_autocad_ready(acad, timeout=10)


def activate_exact_document(acad, doc, retries=30):
    """
    激活指定文档，并确认 acad.ActiveDocument 确实就是该文档。

    不能在 Activate 失败后继续直接读取 acad.ActiveDocument；当上一个布管图
    仍打开时，那样可能会重新取得旧图纸，进而出现拒绝呼叫或画错文档。
    """
    if doc is None:
        raise RuntimeError("待激活的 AutoCAD 文档为空")

    expected_identity = _safe_doc_identity(doc)
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            cancel_active_autocad_command(acad)

            autocad_com_retry(
                lambda: doc.Activate(),
                "激活指定 AutoCAD 文档",
                retries=8,
                delay=0.25
            )

            wait_autocad_ready(acad, timeout=8, stable_checks=2)

            active_doc = autocad_com_retry(
                lambda: acad.ActiveDocument,
                "确认 AutoCAD 活动文档",
                retries=8,
                delay=0.25
            )

            active_identity = _safe_doc_identity(active_doc)

            # 优先按路径/名称核对；取不到标识时，再通过 Name 做一次兜底比较。
            same_doc = bool(
                expected_identity
                and active_identity
                and expected_identity == active_identity
            )

            if not same_doc:
                try:
                    expected_name = str(doc.Name).strip().lower()
                    active_name = str(active_doc.Name).strip().lower()
                    same_doc = expected_name == active_name
                except Exception:
                    same_doc = False

            if not same_doc:
                raise RuntimeError(
                    f"活动文档尚未切换到目标图纸："
                    f"目标={expected_identity}，当前={active_identity}"
                )

            return active_doc

        except Exception as exc:
            last_error = exc
            if attempt >= retries:
                break

            sleep_seconds = min(0.3 + attempt * 0.08, 1.5)
            print(
                f"⚠️ 目标图纸尚未完成激活，第 {attempt}/{retries} 次重试，"
                f"等待 {sleep_seconds:.2f} 秒..."
            )
            time.sleep(sleep_seconds)

    raise RuntimeError("无法稳定激活新建的 AutoCAD 图纸") from last_error


def get_doc_modelspace_with_retry(acad, doc=None, retries=30):
    """
    稳定取得“指定文档”的 ModelSpace。

    关键修复：
    - 不再忽略 doc.Activate() 失败；
    - 不再无条件改用 acad.ActiveDocument；
    - 必须确认当前活动图纸就是传入的 doc 后，才访问其 ModelSpace。
    """
    if doc is None:
        doc = autocad_com_retry(
            lambda: acad.ActiveDocument,
            "获取活动文档",
            retries=retries,
            delay=0.35
        )

    active_doc = activate_exact_document(acad, doc, retries=retries)

    model_space = autocad_com_retry(
        lambda: active_doc.ModelSpace,
        "获取目标文档 ModelSpace",
        retries=retries,
        delay=0.35
    )

    return active_doc, model_space


def create_new_doc_with_name(acad, save_path):
    """
    新建图纸并另存为 save_path。

    支持上一个布管图不关闭：先退出旧文档中的活动命令，再新建文档；
    SaveAs 后始终重新激活并核对新文档，避免误取旧文档的 ModelSpace。
    """
    folder = os.path.dirname(save_path)
    if folder and not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)

    try:
        if os.path.exists(save_path):
            os.remove(save_path)
    except Exception as e:
        print(f"⚠️ 删除旧文件失败: {e}")

    cancel_active_autocad_command(acad)
    wait_autocad_ready(acad, timeout=15)

    doc = autocad_com_retry(
        lambda: acad.Documents.Add(),
        "新建 AutoCAD 图纸",
        retries=40,
        delay=0.4
    )

    # Documents.Add 返回后，明确激活这个新文档，不能假设它已经是活动文档。
    doc = activate_exact_document(acad, doc, retries=30)

    abs_save_path = os.path.abspath(save_path)
    autocad_com_retry(
        lambda: doc.SaveAs(abs_save_path),
        "另存 AutoCAD 图纸",
        retries=40,
        delay=0.45
    )

    wait_autocad_ready(acad, timeout=25)

    # SaveAs 可能更新 COM 文档代理，必须重新确认目标文档仍处于活动状态。
    doc = activate_exact_document(acad, doc, retries=30)

    # 提前访问一次 ModelSpace，确保调用方拿到的文档已经可用。
    autocad_com_retry(
        lambda: doc.ModelSpace,
        "验证新图纸 ModelSpace",
        retries=30,
        delay=0.35
    )

    print(f"✅ 新建图纸并保存为: {save_path}")
    return doc

def fetch_tube_outer_diameter(product_id):
    """
    从 产品设计活动表_布管参数表 读取 换热管外径 do
    """
    conn = pymysql.connect(
        host="localhost",
        port=3306,
        user="root",
        password="123456",
        database="产品设计活动库",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT `参数名`, `参数值`
                FROM `产品设计活动表_布管参数表`
                WHERE `产品ID` = %s
            """, (product_id,))
            rows = cur.fetchall() or []

        do = None

        for row in rows:
            name = str(row.get("参数名") or "").strip()
            value = row.get("参数值")
            name_no_space = re.sub(r"\s+", "", name).upper()

            if ("换热管外径" in name and "DO" in name.upper()) or ("换热管外径DO" in name_no_space):
                do = parse_first_number(value)
                break

        if do is None:
            raise ValueError("未读取到参数：换热管外径 do")

        return do
    finally:
        conn.close()


def resolve_coord_json_path(product_id):
    """
    从 产品设计活动库 的 产品设计活动表 中，
    先查出当前产品ID对应的“产品文件夹绝对路径”，
    再拼接 coords/{product_id}.json
    """
    conn = pymysql.connect(
        host="localhost",
        user="root",
        password="123456",
        database="产品设计活动库",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT 产品文件夹绝对路径
                FROM 产品设计活动表
                WHERE 产品ID = %s
                LIMIT 1
                """,
                (product_id,)
            )
            row = cursor.fetchone()

        if not row or not row.get("产品文件夹绝对路径"):
            raise FileNotFoundError(f"未找到产品ID={product_id} 对应的产品文件夹绝对路径")

        product_folder = os.path.abspath(str(row["产品文件夹绝对路径"]).strip())

        json_path = os.path.join(
            product_folder,
            f"{product_id}.json"
        )
        json_path = os.path.abspath(json_path)

        if not os.path.exists(json_path):
            raise FileNotFoundError(f"未找到坐标文件: {json_path}")

        return json_path

    finally:
        conn.close()


def load_json_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_buguan_rows(product_id):
    """
    从 产品设计活动表_布管数量表_显示 读取每排数量
    """
    conn = pymysql.connect(
        host="localhost",
        port=3306,
        user="root",
        password="123456",
        database="产品设计活动库",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    `至水平中心线行号` AS row_no,
                    `管孔数量（上）` AS upper_cnt,
                    `管孔数量（下）` AS lower_cnt
                FROM `产品设计活动表_布管数量表_显示`
                WHERE `产品ID` = %s
                ORDER BY CAST(`至水平中心线行号` AS UNSIGNED)
            """, (product_id,))
            rows = cur.fetchall() or []

            result = []
            for r in rows:
                row_no = int(parse_first_number(r.get("row_no")) or 0)
                upper_cnt = int(parse_first_number(r.get("upper_cnt")) or 0)
                lower_cnt = int(parse_first_number(r.get("lower_cnt")) or 0)
                result.append({
                    "row_no": row_no,
                    "upper_cnt": upper_cnt,
                    "lower_cnt": lower_cnt
                })
            return result
    finally:
        conn.close()



def build_callout_pairs(groups, display_rows, count_key, side_name):
    """
    将某一侧实际识别到的管孔排，与数据库中该侧数量大于 0 的记录对应。

    规则：
    1. 保留数据库原始“至水平中心线行号”；
    2. 该侧数量为 0 的记录不消耗实际管孔排；
    3. 完全按照实际管孔排距中心线由近到远的顺序匹配；
    4. 不再根据管孔数量交换相邻排，避免第1、2排或其它相邻排发生交叉标注。

    返回：
        [(group, source_row_no, qty), ...]
    """
    valid_rows = []

    for row in sorted(display_rows, key=lambda r: int(r.get("row_no") or 0)):
        source_row_no = int(row.get("row_no") or 0)
        qty = int(row.get(count_key) or 0)

        if source_row_no > 0 and qty > 0:
            valid_rows.append({
                "source_row_no": source_row_no,
                "qty": qty
            })

    ordered_groups = list(groups)

    if len(ordered_groups) != len(valid_rows):
        print(
            f"⚠️ {side_name}实际识别到 {len(ordered_groups)} 排，"
            f"数据库中该侧数量大于0的记录有 {len(valid_rows)} 排；"
            f"将按距中心线由近到远依次匹配，不进行交叉交换。"
        )

    pairs = []

    for group, row_info in zip(ordered_groups, valid_rows):
        source_row_no = row_info["source_row_no"]
        expected_qty = row_info["qty"]
        actual_qty = len(group.get("points", []))

        if actual_qty != expected_qty:
            print(
                f"⚠️ {side_name}数据库第 {source_row_no} 排数量不一致："
                f"坐标识别={actual_qty}，数据库={expected_qty}；"
                f"仍按几何顺序标注，不交换相邻排。"
            )

        pairs.append((group, source_row_no, expected_qty))

    return pairs

def add_row_callout(
        ms,
        x,
        y,
        hole_radius,
        row_no,
        qty,
        side="right",
        highlight=True
):
    """
    画类似 '2-27' 的直线引出标注
    特点：
    1. 标识与管子保持同一排（同一 y）
    2. 只用水平直线，不用折线
    3. 字号更小
    """
    text_str = f"{row_no}-{qty}"

    # 字号调小
    text_h = max(hole_radius * 0.45, 0.9)

    # 圆点到引线、引线到文字的距离
    gap = max(hole_radius * 0.25, text_h * 0.25)
    horiz_len = max(hole_radius * 2.8, text_h * 4.0)

    if side == "right":
        # 从管子右侧直接水平引出
        p1 = (x + hole_radius + gap, y)
        p2 = (p1[0] + horiz_len, y)

        text_x = p2[0] + text_h * 0.25
        text_y = y - text_h * 0.35
    else:
        # 从管子左侧直接水平引出
        p1 = (x - hole_radius - gap, y)
        p2 = (p1[0] - horiz_len, y)

        est_w = len(text_str) * text_h * 0.65
        text_x = p2[0] - est_w - text_h * 0.25
        text_y = y - text_h * 0.35

    if highlight:
        try:
            # 红色小圈也缩小一点
            c = ms.AddCircle(make_point(x, y, 0), max(hole_radius * 0.55, text_h * 0.45))
            c.Color = 1
        except Exception:
            pass

    try:
        # 只画一条水平线
        ln = ms.AddLine(make_point(*p1, 0), make_point(*p2, 0))
        ln.Color = 3
    except Exception:
        pass

    try:
        txt = ms.AddText(text_str, make_point(text_x, text_y, 0), text_h)
        txt.Color = 3
    except Exception:
        pass


def estimate_row_tolerance(points):
    """
    根据实际坐标估计“同一排”的 y 容差
    """
    ys = sorted(set(round(p[1], 8) for p in points))
    if len(ys) < 2:
        return 1.0

    diffs = []
    for i in range(1, len(ys)):
        d = abs(ys[i] - ys[i - 1])
        if d > 1e-6:
            diffs.append(d)

    if not diffs:
        return 1.0

    min_diff = min(diffs)
    return max(min_diff * 0.35, 1e-4)


def group_points_by_rows(points, center_y, tol, row_map=None):
    """
    按 y 坐标把实际管孔分组为一排排
    返回:
        upper_groups: 从靠近中心线到远离中心线排序
        lower_groups: 从靠近中心线到远离中心线排序

    关键修复：
    1. 不再把中心线上的排直接丢掉
    2. 若只有一条中心线排，则根据数据库第1行上/下数量决定它归属哪一侧
    """
    if not points:
        return [], []

    pts = sorted(points, key=lambda p: p[1])
    groups = []

    for x, y in pts:
        placed = False
        for g in groups:
            if abs(y - g["y"]) <= tol:
                g["points"].append((x, y))
                g["y"] = sum(p[1] for p in g["points"]) / len(g["points"])
                placed = True
                break

        if not placed:
            groups.append({
                "y": y,
                "points": [(x, y)]
            })

    for g in groups:
        g["points"].sort(key=lambda p: p[0])
        g["leftmost"] = g["points"][0]
        g["rightmost"] = g["points"][-1]

    # 分成上、下、中心线
    upper_groups = [g for g in groups if g["y"] > center_y + tol]
    lower_groups = [g for g in groups if g["y"] < center_y - tol]
    center_groups = [g for g in groups if abs(g["y"] - center_y) <= tol]

    upper_groups.sort(key=lambda g: abs(g["y"] - center_y))
    lower_groups.sort(key=lambda g: abs(g["y"] - center_y))
    center_groups.sort(key=lambda g: g["y"], reverse=True)

    if center_groups:
        row1_upper = 0
        row1_lower = 0
        if row_map:
            row1 = row_map.get(1, {})
            row1_upper = int(row1.get("upper_cnt") or 0)
            row1_lower = int(row1.get("lower_cnt") or 0)

        # 只有一条中心线排：按数据库第1行决定归属
        if len(center_groups) == 1:
            cg = center_groups[0]

            if row1_upper > 0 and row1_lower <= 0:
                upper_groups.insert(0, cg)
            elif row1_lower > 0 and row1_upper <= 0:
                lower_groups.insert(0, cg)
            elif row1_upper > 0 and row1_lower > 0:
                # 理论上少见；若上下都要第1排，默认归上并告警
                upper_groups.insert(0, cg)
                print("⚠️ 检测到中心线仅1排，但数据库上下第1排都>0，默认归入上半区。")
            else:
                # 数据库第1行上下都为0，默认丢给更接近上侧
                upper_groups.insert(0, cg)

        else:
            # 若中心附近识别出多排，则按 y 相对位置分别归入
            for cg in center_groups:
                if cg["y"] >= center_y:
                    upper_groups.append(cg)
                else:
                    lower_groups.append(cg)

            upper_groups.sort(key=lambda g: abs(g["y"] - center_y))
            lower_groups.sort(key=lambda g: abs(g["y"] - center_y))

    return upper_groups, lower_groups

def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _find_xy_pair_in_dict(d):
    """
    尽量从一个 dict 中识别出一对 x/y 坐标
    支持键名里包含 x/y 的各种情况，比如:
    x,y / X,Y / absX,absY / coord_x,coord_y / x坐标,y坐标
    """
    numeric_items = {str(k): v for k, v in d.items() if _is_number(v)}
    if not numeric_items:
        return None

    x_key = None
    y_key = None

    for k in numeric_items.keys():
        lk = k.lower().replace("_", "").replace(" ", "")
        if x_key is None and "x" in lk:
            x_key = k
        if y_key is None and "y" in lk:
            y_key = k

    if x_key is not None and y_key is not None:
        return float(numeric_items[x_key]), float(numeric_items[y_key])

    return None


def extract_xy_points(obj):
    """
    递归提取 JSON 中所有可能的坐标点。
    支持：
    - [x, y]
    - {"x":..., "y":...}
    - {"X":..., "Y":...}
    - 其它 key 中只要含 x/y 且值为数值
    - 任意嵌套 dict/list
    """
    points = []

    def walk(node):
        if isinstance(node, dict):
            pair = _find_xy_pair_in_dict(node)
            if pair is not None:
                points.append(pair)

            for v in node.values():
                walk(v)

        elif isinstance(node, (list, tuple)):
            if len(node) >= 2 and _is_number(node[0]) and _is_number(node[1]):
                points.append((float(node[0]), float(node[1])))
            else:
                for item in node:
                    walk(item)

    walk(obj)

    uniq = []
    seen = set()
    for x, y in points:
        key = (round(float(x), 8), round(float(y), 8))
        if key not in seen:
            seen.add(key)
            uniq.append((float(x), float(y)))

    return uniq


def compute_enclosing_circle(points, hole_radius, margin=None):
    """
    根据所有管孔坐标计算一个能完整包住全部小圆的大圆
    """
    if not points:
        raise ValueError("没有可用的管孔坐标")

    if margin is None:
        margin = max(hole_radius * 1.5, 1.0)

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0

    radius = 0.0
    for x, y in points:
        d = math.hypot(x - cx, y - cy) + hole_radius
        if d > radius:
            radius = d

    radius += margin
    return cx, cy, radius


def median_value(values):
    """
    求中位数，避免极端间距影响判断。
    """
    values = [float(v) for v in values if v is not None and float(v) > 0]
    if not values:
        return None

    values.sort()
    n = len(values)

    if n % 2 == 1:
        return values[n // 2]

    return (values[n // 2 - 1] + values[n // 2]) / 2.0


def group_points_for_row_lines(points, y_tol):
    """
    将坐标点按 Y 坐标归并成一排排。

    返回：
    [
        {
            "y": 当前排平均Y,
            "points": [(x1, y1), (x2, y2), ...]
        },
        ...
    ]

    注意：
    - 排序按 Y 从大到小；
    - 每排内部按 X 从小到大。
    """
    if not points:
        return []

    if y_tol is None or y_tol <= 0:
        y_tol = 1.0

    sorted_points = sorted(points, key=lambda p: p[1], reverse=True)

    rows = []

    for x, y in sorted_points:
        matched = None

        for row in rows:
            if abs(y - row["y"]) <= y_tol:
                matched = row
                break

        if matched is None:
            rows.append({
                "y": float(y),
                "points": [(float(x), float(y))]
            })
        else:
            matched["points"].append((float(x), float(y)))
            matched["y"] = sum(p[1] for p in matched["points"]) / len(matched["points"])

    for row in rows:
        row["points"].sort(key=lambda p: p[0])

    rows.sort(key=lambda r: r["y"], reverse=True)

    return rows


def estimate_row_pitch(row_points):
    """
    估算同一排的正常管间距。
    通过相邻点 X 距离的中位数判断。
    """
    if not row_points or len(row_points) < 2:
        return None

    pts = sorted(row_points, key=lambda p: p[0])
    gaps = []

    for i in range(len(pts) - 1):
        dx = abs(pts[i + 1][0] - pts[i][0])
        if dx > 1e-6:
            gaps.append(dx)

    return median_value(gaps)


def _median(values):
    values = [float(v) for v in values if v is not None and float(v) > 1e-9]
    if not values:
        return None

    values.sort()
    n = len(values)

    if n % 2 == 1:
        return values[n // 2]

    return (values[n // 2 - 1] + values[n // 2]) / 2.0


def group_points_as_horizontal_rows(points, y_tol):
    """
    按 y 坐标把管孔分成一排排。
    每排内部按 x 从小到大排序。
    """
    if not points:
        return []

    if y_tol is None or y_tol <= 0:
        y_tol = 1.0

    sorted_points = sorted(points, key=lambda p: p[1], reverse=True)
    rows = []

    for x, y in sorted_points:
        x = float(x)
        y = float(y)

        matched_row = None

        for row in rows:
            if abs(y - row["y"]) <= y_tol:
                matched_row = row
                break

        if matched_row is None:
            rows.append({
                "y": y,
                "points": [(x, y)]
            })
        else:
            matched_row["points"].append((x, y))
            matched_row["y"] = sum(p[1] for p in matched_row["points"]) / len(matched_row["points"])

    for row in rows:
        row["points"].sort(key=lambda p: p[0])

    rows.sort(key=lambda r: r["y"], reverse=True)

    return rows


def estimate_normal_pitch_from_rows(rows):
    """
    估算一排内正常管间距。
    为避免缺管导致 2S、3S 影响，取较小部分间距的中位数。
    """
    gaps = []

    for row in rows:
        pts = row.get("points", [])
        if len(pts) < 2:
            continue

        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            gap = abs(x2 - x1)

            if gap > 1e-6:
                gaps.append(gap)

    if not gaps:
        return None

    gaps.sort()

    # 取较小的 40% 间距作为正常管距候选
    take_n = max(1, int(len(gaps) * 0.4))
    small_gaps = gaps[:take_n]

    return _median(small_gaps)


def draw_tube_rows_as_dot_lines(
        ms,
        moved_points,
        row_tol,
        node_radius,
        color=5,
        gap_factor=1.45
):
    """
    绘制 ●—●—● 形式的布管图。

    规则：
    1. 每个管孔位置画一个小圆点；
    2. 同一排内相邻管孔之间画线；
    3. 如果相邻两点距离明显大于正常管距，认为中间有空管位，不连线；
    4. 一排只有一个管孔时，只画点，不画线。
    """
    rows = group_points_as_horizontal_rows(moved_points, row_tol)
    normal_pitch = estimate_normal_pitch_from_rows(rows)

    if not normal_pitch or normal_pitch <= 0:
        print("⚠️ 未能估算正常管间距，将只画点，不画连线。")

    dot_count = 0
    line_count = 0

    # 先画线，再画圆点，这样圆点会压在线上，看起来更像 ●—●—●
    if normal_pitch and normal_pitch > 0:
        for row_idx, row in enumerate(rows, start=1):
            pts = row.get("points", [])

            if len(pts) < 2:
                continue

            for i in range(len(pts) - 1):
                x1, y1 = pts[i]
                x2, y2 = pts[i + 1]

                gap = abs(x2 - x1)

                # 间距明显变大，说明中间有空位，不跨空位连线
                if gap > normal_pitch * gap_factor:
                    continue

                try:
                    line = ms.AddLine(
                        make_point(x1, y1, 0),
                        make_point(x2, y2, 0)
                    )
                    line.Color = color
                    line_count += 1
                except Exception as e:
                    print(f"⚠️ 绘制第 {row_idx} 排连线失败: {e}")

    # 再画点
    for x, y in moved_points:
        try:
            dot = ms.AddCircle(make_point(x, y, 0), node_radius)
            dot.Color = color
            dot_count += 1
        except Exception as e:
            print(f"⚠️ 绘制管位圆点失败: ({x}, {y}), {e}")

    print(f"✅ 已绘制点线式布管图：圆点 {dot_count} 个，连线 {line_count} 条")

    return rows, dot_count, line_count


def draw_tube_rows_as_lines(
        ms,
        moved_points,
        row_tol,
        color=5,
        gap_factor=1.55
):
    """
    将布管坐标按排连线。

    规则：
    - 同一排内按 X 从小到大排序；
    - 相邻两管距离 <= 正常管距 * gap_factor 时连线；
    - 相邻两管距离 > 正常管距 * gap_factor 时认为中间有空位，不连线；
    - 一排只有一个点时不画线。
    """
    rows = group_points_for_row_lines(moved_points, row_tol)

    line_count = 0
    row_count = 0

    for row in rows:
        pts = row["points"]

        if len(pts) < 2:
            continue

        pitch = estimate_row_pitch(pts)

        if not pitch or pitch <= 0:
            continue

        row_count += 1

        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]

            dx = abs(x2 - x1)

            # 关键：距离明显大于正常管间距时，说明中间有空管位，不跨过去连线
            if dx > pitch * gap_factor:
                continue

            try:
                line = ms.AddLine(
                    make_point(x1, y1, 0),
                    make_point(x2, y2, 0)
                )
                try:
                    line.Color = color
                except Exception:
                    pass

                line_count += 1

            except Exception as e:
                print(f"⚠️ 画布管排线失败: ({x1}, {y1}) -> ({x2}, {y2}), {e}")

    print(f"✅ 已按排连线：识别 {row_count} 排，绘制 {line_count} 条线段")

    return rows, line_count


def draw_buguan_from_coord_json(
        acad,
        product_id,
        save_name="布管图.dwg",
        insert_center=(0.0, 0.0),
        target_rect=None,
        draw_in_current_doc=False,
        padding=5.0,
        show_callout=True
):
    """
    从 modules/buguan/buguan_ziyong/coord/{product_id}.json 读取实际管孔坐标绘图。

    参数说明：
    - acad:
        AutoCAD.Application 对象；为 None 时自动连接。
    - product_id:
        当前产品ID。
    - save_name:
        单独生成布管图时的文件名。
        当 draw_in_current_doc=True 时，建议传 None，避免单独保存布管图。
    - insert_center:
        未指定 target_rect 时，将布管图平移到该中心点。
    - target_rect:
        指定目标矩形区域，例如：
        ((6250.0, -58.0, 0.0), (6410.0, -185.0, 0.0))
        如果传入该参数，会自动缩放并居中放入该矩形。
    - draw_in_current_doc:
        False：新建并单独保存布管图；
        True：直接画到当前总图文档中。
    - padding:
        布管图放入目标矩形时的边距。
    - show_callout:
        是否显示每排数量标注。
        None 时：单独布管图显示标注；嵌入总图时默认不显示，避免太小太乱。
    """

    if acad is None:
        acad = get_autocad_instance()

    if acad is None:
        raise RuntimeError("AutoCAD 未连接")

    if show_callout is None:
        show_callout = not bool(target_rect)

    # =========================
    # 1) 读取 JSON 实际坐标
    # =========================
    coord_json_path = resolve_coord_json_path(product_id)
    print(f"✅ 坐标文件: {coord_json_path}")

    data = load_json_file(coord_json_path)
    points = extract_xy_points(data)

    if not points:
        raise ValueError(f"JSON 中未提取到任何坐标点: {coord_json_path}")

    print(f"✅ 共读取到 {len(points)} 个管孔坐标")

    # =========================
    # 2) 读取小圆直径
    # =========================
    do = fetch_tube_outer_diameter(product_id)
    hole_radius = do / 2.0
    print(f"✅ 读取换热管外径 do={do}，小圆半径={hole_radius}")

    # =========================
    # 3) 计算原始包络大圆
    # =========================
    src_cx, src_cy, big_radius = compute_enclosing_circle(points, hole_radius)

    # =========================
    # 4) 坐标变换
    #    A. 如果有 target_rect，则缩放进矩形区域
    #    B. 如果没有 target_rect，则只平移到 insert_center
    # =========================
    scale = 1.0

    if target_rect:
        p1, p2 = target_rect

        target_min_x = min(float(p1[0]), float(p2[0]))
        target_max_x = max(float(p1[0]), float(p2[0]))
        target_min_y = min(float(p1[1]), float(p2[1]))
        target_max_y = max(float(p1[1]), float(p2[1]))

        target_w = target_max_x - target_min_x
        target_h = target_max_y - target_min_y

        if target_w <= 0 or target_h <= 0:
            raise ValueError(f"目标矩形区域无效: {target_rect}")

        # 计算源图形包络，注意把小圆半径也算进去
        src_min_x = min(x for x, y in points) - hole_radius
        src_max_x = max(x for x, y in points) + hole_radius
        src_min_y = min(y for x, y in points) - hole_radius
        src_max_y = max(y for x, y in points) + hole_radius

        src_w = src_max_x - src_min_x
        src_h = src_max_y - src_min_y

        if src_w <= 0:
            src_w = 1.0
        if src_h <= 0:
            src_h = 1.0

        usable_w = max(1.0, target_w - 2.0 * padding)
        usable_h = max(1.0, target_h - 2.0 * padding)

        scale = min(usable_w / src_w, usable_h / src_h)

        dst_cx = (target_min_x + target_max_x) / 2.0
        dst_cy = (target_min_y + target_max_y) / 2.0

        def transform_xy(x, y):
            new_x = dst_cx + (x - src_cx) * scale
            new_y = dst_cy + (y - src_cy) * scale
            return new_x, new_y

        moved_points = [transform_xy(x, y) for x, y in points]

        hole_radius = hole_radius * scale
        big_radius = big_radius * scale

        print("✅ 布管图将缩放插入目标矩形区域")
        print(f"   目标区域: x={target_min_x}~{target_max_x}, y={target_min_y}~{target_max_y}")
        print(f"   插入中心: ({dst_cx}, {dst_cy})")
        print(f"   缩放比例: {scale}")

    else:
        dst_cx, dst_cy = insert_center
        dx = dst_cx - src_cx
        dy = dst_cy - src_cy
        moved_points = [(x + dx, y + dy) for x, y in points]

        print("✅ 布管图按插入中心平移")
        print(f"   插入中心: ({dst_cx}, {dst_cy})")

    # =========================
    # 5) 读取显示表
    # =========================
    display_rows = fetch_buguan_rows(product_id)
    row_map = {
        int(r["row_no"]): r
        for r in display_rows
        if int(r.get("row_no") or 0) > 0
    }

    # =========================
    # 6) 自动识别实际坐标中的“每一行”
    #    中心线上的管孔排必须根据数据库第1行归入正确一侧，
    #    否则该排会被丢弃，后续所有标注都会错一行。
    # =========================
    tol = estimate_row_tolerance(moved_points)
    upper_groups, lower_groups = group_points_by_rows(
        moved_points,
        center_y=dst_cy,
        tol=tol,
        row_map=row_map
    )

    print(f"✅ 识别到上半区 {len(upper_groups)} 排，下半区 {len(lower_groups)} 排")

    # =========================
    # 7) 获取绘图文档
    # =========================
    save_dir = CAD_CTX.get("save_dir")

    if not save_dir:
        save_dir = get_project_save_dir(product_id)

    if not save_dir:
        save_dir = os.getcwd()

    save_path = None
    if save_name:
        save_path = os.path.join(save_dir, save_name)

    wait_cad_idle(acad, timeout=10)

    if draw_in_current_doc:
        # 关键：不新建布管图，直接画到当前总图
        doc = get_current_doc(product_id)

        if doc is None:
            raise RuntimeError("当前没有可用的总图文档，无法把布管图插入总图。")

        try:
            doc.Activate()
        except Exception:
            pass

        print(f"✅ 当前模式：插入到已有总图文档：{doc.Name}")

    else:
        # 原逻辑：单独创建布管图
        if not save_path:
            raise RuntimeError("单独生成布管图时 save_name 不能为空。")

        doc = create_new_doc_with_name(acad, save_path)
        print(f"✅ 当前模式：单独生成布管图：{save_path}")

    # 新建、保存或激活文档后，使用重试方式稳定取得 ModelSpace
    doc, ms = get_doc_modelspace_with_retry(acad, doc=doc, retries=30)

    # =========================
    # 8) 画大圆
    # =========================
    outer = ms.AddCircle(make_point(dst_cx, dst_cy, 0), big_radius)
    try:
        outer.Color = 7
    except Exception:
        pass

    # =========================
    # 9) 绘制点线式布管图：●—●—●
    # =========================
    row_line_tol = tol

    # 嵌入总图后图形较小，给一个最小行分组容差，防止同一排被误分成多排
    if target_rect:
        row_line_tol = max(row_line_tol, hole_radius * 1.2, 0.8)

    # 点的半径不要用真实管孔半径，否则太大；
    # 这里是示意点半径，用来形成 ●—●—● 的视觉效果。
    if target_rect:
        node_radius = max(hole_radius * 0.45, 0.45)
    else:
        node_radius = max(hole_radius * 0.45, 1.2)

    line_rows, dot_count, line_count = draw_tube_rows_as_dot_lines(
        ms=ms,
        moved_points=moved_points,
        row_tol=row_line_tol,
        node_radius=node_radius,
        color=5,
        gap_factor=1.45
    )

    total = dot_count

    # =========================
    # 10) 给每一行加标注
    #     嵌入总图的小区域里默认不建议显示标注，
    #     否则文字可能挤在一起。
    # =========================
    if show_callout:
        # 标识整体缩小
        callout_radius = max(hole_radius * 0.6, 0.9)

        # 上半部分：保留数据库原始行号；中心线第1排会正确标注为 1-数量。
        upper_pairs = build_callout_pairs(
            groups=upper_groups,
            display_rows=display_rows,
            count_key="upper_cnt",
            side_name="上半区"
        )

        for g, row_no, qty in upper_pairs:
            rx, ry = g["rightmost"]
            add_row_callout(
                ms=ms,
                x=rx,
                y=ry,
                hole_radius=callout_radius,
                row_no=row_no,
                qty=qty,
                side="right",
                highlight=True
            )

        # 下半部分：数量为0的数据库行跳过，但后续仍保留原始行号。
        lower_pairs = build_callout_pairs(
            groups=lower_groups,
            display_rows=display_rows,
            count_key="lower_cnt",
            side_name="下半区"
        )

        for g, row_no, qty in lower_pairs:
            rx, ry = g["rightmost"]
            add_row_callout(
                ms=ms,
                x=rx,
                y=ry,
                hole_radius=callout_radius,
                row_no=row_no,
                qty=qty,
                side="right",
                highlight=True
            )
    else:
        print("ℹ️ 当前已关闭每排数量标注。")

    # =========================
    # 11) 刷新保存
    # =========================
    try:
        doc.Regen(1)
    except Exception:
        pass

    try:
        acad.ZoomExtents()
    except Exception:
        pass

    try:
        doc.Save()
    except Exception as e:
        print(f"⚠️ 保存失败: {e}")
        raise

    try:
        CAD_CTX["product_id"] = product_id
        CAD_CTX["save_dir"] = save_dir
        CAD_CTX["doc"] = doc

        if save_path:
            CAD_CTX["target_dwg"] = save_path
        else:
            try:
                CAD_CTX["target_dwg"] = doc.FullName
            except Exception:
                CAD_CTX["target_dwg"] = None

    except Exception:
        pass

    print(f"✅ 布管图绘制完成，共绘制 {total} 个小圆")

    if save_path:
        print(f"✅ 保存路径: {save_path}")
    else:
        print("✅ 已绘制到当前总图中，不再单独生成布管图文件")

    print(f"✅ 当前文件名: {doc.Name}")

    if save_path:
        return save_path

    try:
        return doc.FullName
    except Exception:
        return None


def add_row_callout_dandu(
        ms,
        x,
        y,
        hole_radius,
        row_no,
        qty,
        side="right",
        highlight=True
):
    """
    单独布管图的直线引出标注，例如“2-27”。

    修复规则：
    1. 标注与对应管孔排保持同一 Y 坐标；
    2. 只绘制一条水平直线，不再使用斜线和折线；
    3. 因此相邻排的引线不会发生交叉。
    """
    text_str = f"{row_no}-{qty}"

    text_h = max(hole_radius * 0.9, 2.5)
    gap = max(hole_radius * 0.6, text_h * 0.2)
    horiz_len = max(hole_radius * 6.3, text_h * 4.5)

    if side == "right":
        p1 = (x + hole_radius + gap, y)
        p2 = (p1[0] + horiz_len, y)

        text_x = p2[0] + max(hole_radius * 0.4, text_h * 0.2)
        text_y = y - text_h * 0.35
    else:
        p1 = (x - hole_radius - gap, y)
        p2 = (p1[0] - horiz_len, y)

        est_w = len(text_str) * text_h * 0.7
        text_x = p2[0] - est_w - max(hole_radius * 0.4, text_h * 0.2)
        text_y = y - text_h * 0.35

    if highlight:
        try:
            c = ms.AddCircle(make_point(x, y, 0), hole_radius * 1.15)
            c.Color = 1
        except Exception:
            pass

    try:
        line = ms.AddLine(make_point(*p1, 0), make_point(*p2, 0))
        line.Color = 3
    except Exception:
        pass

    try:
        txt = ms.AddText(text_str, make_point(text_x, text_y, 0), text_h)
        txt.Color = 3
    except Exception:
        pass

def estimate_row_tolerance_dandu(points):
    """
    根据实际坐标估计“同一排”的 y 容差
    """
    ys = sorted(set(round(p[1], 8) for p in points))
    if len(ys) < 2:
        return 1.0

    diffs = []
    for i in range(1, len(ys)):
        d = abs(ys[i] - ys[i - 1])
        if d > 1e-6:
            diffs.append(d)

    if not diffs:
        return 1.0

    min_diff = min(diffs)
    return max(min_diff * 0.35, 1e-4)


def group_points_by_rows_dandu(points, center_y, tol):
    """
    按 y 坐标把实际管孔分组为一排排
    返回:
        upper_groups: [ {y, points, rightmost, leftmost}, ... ]   # 从靠近中心线到远离中心线排序
        lower_groups: [ {y, points, rightmost, leftmost}, ... ]
    """
    if not points:
        return [], []

    # 先按 y 排序，再聚类
    pts = sorted(points, key=lambda p: p[1])
    groups = []

    for x, y in pts:
        placed = False
        for g in groups:
            if abs(y - g["y"]) <= tol:
                g["points"].append((x, y))
                # 更新该组平均 y
                g["y"] = sum(p[1] for p in g["points"]) / len(g["points"])
                placed = True
                break

        if not placed:
            groups.append({
                "y": y,
                "points": [(x, y)]
            })

    # 每组内部按 x 排序，得到最左最右
    for g in groups:
        g["points"].sort(key=lambda p: p[0])
        g["leftmost"] = g["points"][0]
        g["rightmost"] = g["points"][-1]

    upper_groups = [g for g in groups if g["y"] > center_y + tol]
    lower_groups = [g for g in groups if g["y"] < center_y - tol]

    # 按“离中心线的距离”排序，使 row_no=1 对应最靠近中心线的一排
    upper_groups.sort(key=lambda g: abs(g["y"] - center_y))
    lower_groups.sort(key=lambda g: abs(g["y"] - center_y))

    return upper_groups, lower_groups


def _is_number_dandu(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _find_xy_pair_in_dict_dandu(d):
    """
    尽量从一个 dict 中识别出一对 x/y 坐标
    支持键名里包含 x/y 的各种情况，比如:
    x,y / X,Y / absX,absY / coord_x,coord_y / x坐标,y坐标
    """
    numeric_items = {str(k): v for k, v in d.items() if _is_number_dandu(v)}
    if not numeric_items:
        return None

    x_key = None
    y_key = None

    for k in numeric_items.keys():
        lk = k.lower().replace("_", "").replace(" ", "")
        if x_key is None and "x" in lk:
            x_key = k
        if y_key is None and "y" in lk:
            y_key = k

    if x_key is not None and y_key is not None:
        return float(numeric_items[x_key]), float(numeric_items[y_key])

    return None


def extract_xy_points_dandu(obj):
    """
    递归提取 JSON 中所有可能的坐标点。
    支持：
    - [x, y]
    - {"x":..., "y":...}
    - {"X":..., "Y":...}
    - 其它 key 中只要含 x/y 且值为数值
    - 任意嵌套 dict/list
    """
    points = []

    def walk(node):
        if isinstance(node, dict):
            pair = _find_xy_pair_in_dict_dandu(node)
            if pair is not None:
                points.append(pair)

            for v in node.values():
                walk(v)

        elif isinstance(node, (list, tuple)):
            if len(node) >= 2 and _is_number_dandu(node[0]) and _is_number_dandu(node[1]):
                points.append((float(node[0]), float(node[1])))
            else:
                for item in node:
                    walk(item)

    walk(obj)

    uniq = []
    seen = set()
    for x, y in points:
        key = (round(float(x), 8), round(float(y), 8))
        if key not in seen:
            seen.add(key)
            uniq.append((float(x), float(y)))

    return uniq


def compute_enclosing_circle_dandu(points, hole_radius, margin=None):
    """
    根据所有管孔坐标计算一个能完整包住全部小圆的大圆
    """
    if not points:
        raise ValueError("没有可用的管孔坐标")

    if margin is None:
        margin = max(hole_radius * 1.5, 1.0)

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0

    radius = 0.0
    for x, y in points:
        d = math.hypot(x - cx, y - cy) + hole_radius
        if d > radius:
            radius = d

    radius += margin
    return cx, cy, radius


def draw_buguan_from_coord_json_dandu(
        acad,
        product_id,
        save_name="布管图.dwg",
        insert_center=(0.0, 0.0)
):
    """
    从 modules/buguan/buguan_ziyong/coord/{product_id}.json 读取实际管孔坐标绘图
    - 小圆直径：读取数据库中的 换热管外径 do
    - 大圆尺寸：按实际坐标自动包络，保证能包含全部小圆
    - 标注内容：继续读取 产品设计活动表_布管数量表_显示
    """
    if acad is None:
        acad = get_autocad_instance()
    if acad is None:
        raise RuntimeError("AutoCAD 未连接")

    # 1) 读取 JSON 实际坐标
    coord_json_path = resolve_coord_json_path(product_id)
    print(f"✅ 坐标文件: {coord_json_path}")

    data = load_json_file(coord_json_path)
    points = extract_xy_points_dandu(data)
    if not points:
        raise ValueError(f"JSON 中未提取到任何坐标点: {coord_json_path}")

    print(f"✅ 共读取到 {len(points)} 个管孔坐标")

    # 2) 读取小圆直径
    do = fetch_tube_outer_diameter(product_id)
    hole_radius = do / 2.0
    print(f"✅ 读取换热管外径 do={do}，小圆半径={hole_radius}")

    # 3) 计算包络大圆
    src_cx, src_cy, big_radius = compute_enclosing_circle_dandu(points, hole_radius)

    # 4) 平移到目标插入中心
    dst_cx, dst_cy = insert_center
    dx = dst_cx - src_cx
    dy = dst_cy - src_cy
    moved_points = [(x + dx, y + dy) for x, y in points]

    # 5) 读取显示表（用于每一行数量标注）
    display_rows = fetch_buguan_rows(product_id)
    row_map = {
        int(r["row_no"]): r
        for r in display_rows
        if int(r.get("row_no") or 0) > 0
    }

    # 6) 自动识别实际坐标中的“每一行”
    # 单独布管图也复用中心线感知的分组逻辑，避免中心线第一排被漏掉。
    tol = estimate_row_tolerance_dandu(moved_points)
    upper_groups, lower_groups = group_points_by_rows(
        moved_points,
        center_y=dst_cy,
        tol=tol,
        row_map=row_map
    )

    print(f"✅ 识别到上半区 {len(upper_groups)} 排，下半区 {len(lower_groups)} 排")

    # 7) 保存路径继续跟随前面的路径
    save_dir = CAD_CTX.get("save_dir")
    if not save_dir:
        save_dir = get_project_save_dir(product_id)
    if not save_dir:
        save_dir = os.getcwd()

    if not save_name or save_name == "布管图.dwg":
        save_name = make_buguan_timestamp_name("布管图")

    save_path = os.path.join(save_dir, save_name)

    wait_cad_idle(acad, timeout=10)
    doc = create_new_doc_with_name(acad, save_path)
    # SaveAs 后 AutoCAD 可能仍在切换文档状态，不能立即直接访问 doc.ModelSpace
    doc, ms = get_doc_modelspace_with_retry(acad, doc=doc, retries=30)

    # 8) 画大圆
    outer = ms.AddCircle(make_point(dst_cx, dst_cy, 0), big_radius)
    try:
        outer.Color = 7
    except Exception:
        pass

    # 9) 画全部实际管孔
    total = 0
    for x, y in moved_points:
        c = ms.AddCircle(make_point(x, y, 0), hole_radius)
        try:
            c.Color = 5
        except Exception:
            pass
        total += 1

    # 10) 给每一行加标注
    # 保留数据库原始行号；数量为0的行不画，但不能让后续行号前移。
    upper_pairs = build_callout_pairs(
        groups=upper_groups,
        display_rows=display_rows,
        count_key="upper_cnt",
        side_name="上半区"
    )

    for g, row_no, qty in upper_pairs:
        rx, ry = g["rightmost"]
        add_row_callout_dandu(
            ms=ms,
            x=rx,
            y=ry,
            hole_radius=hole_radius,
            row_no=row_no,
            qty=qty,
            side="right",
            highlight=True
        )

    lower_pairs = build_callout_pairs(
        groups=lower_groups,
        display_rows=display_rows,
        count_key="lower_cnt",
        side_name="下半区"
    )

    for g, row_no, qty in lower_pairs:
        rx, ry = g["rightmost"]
        add_row_callout_dandu(
            ms=ms,
            x=rx,
            y=ry,
            hole_radius=hole_radius,
            row_no=row_no,
            qty=qty,
            side="right",
            highlight=True
        )

    # 11) 刷新保存
    try:
        doc.Regen(1)
    except Exception:
        pass

    try:
        acad.ZoomExtents()
    except Exception:
        pass

    try:
        doc.Save()
    except Exception as e:
        print(f"⚠️ 保存失败: {e}")
        raise

    try:
        CAD_CTX["product_id"] = product_id
        CAD_CTX["save_dir"] = save_dir
        CAD_CTX["doc"] = doc
        CAD_CTX["target_dwg"] = save_path
    except Exception:
        pass

    print(f"✅ 布管图绘制完成，共绘制 {total} 个小圆")
    print(f"✅ 保存路径: {save_path}")
    print(f"✅ 当前文件名: {doc.Name}")

    return save_path
def make_buguan_timestamp_name(prefix="布管图"):
    """
    生成按日期精确到秒的布管图文件名。
    例如：布管图_20260601_153025.dwg
    """
    return f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.dwg"
