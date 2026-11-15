# -*- coding: utf-8 -*-
"""
从业务库导出「条件输入」参数字典 → param_dict.json

为什么要有这一步（对应设计文档里的 M0「字典先行」）：
    条件输入的参数不是随便起的名字，每个都必须精确对上
    `产品条件库.设计数据模板表` 里的 `参数名称`。这是整个 Agent 的地基——
    参数名差一个字（"设计压力" vs "设计压力*"）就写不进库。

导出内容：
    设计数据模板表   → 参数名称 / 参数单位 / 所属类型 / 所属型式
    设计数据选项模板 → 单选多选枚举值（用来校验"超压泄放装置"这类字段）
    通用数据模板表 / 产品标准数据模板表 / 无损检测数据模板表 / 涂漆数据模板表
                     → 只导出参数名清单，本 demo 先不抽取

跑法：
    python build_dict.py            # 从数据库导（推荐，会覆盖 json）
    python build_dict.py --fallback # 数据库连不上时，用内置的离线快照重建

设计原则：
    - 全程只 SELECT，不写任何业务表
    - 导出失败不抛异常，保留旧 json，界面照常跑
"""
import io
import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(BASE_DIR, "param_dict.json")

DB = {
    "host": "localhost", "port": 3306, "user": "root", "password": "123456",
    "charset": "utf8mb4", "connect_timeout": 5,
}


def main():
    if "--fallback" in sys.argv:
        return _write(_offline_snapshot(), "内置离线快照")
    try:
        data = _from_db()
        _write(data, "产品条件库")
    except Exception as e:
        print("从数据库导出失败：%s: %s" % (type(e).__name__, e))
        print("改用内置离线快照重建（结果等价，只是不保证跟库里最新一致）")
        _write(_offline_snapshot(), "内置离线快照")


def _from_db():
    import pymysql
    conn = pymysql.connect(database="产品条件库", **DB)
    out = {"设计数据": [], "通用数据": [], "产品标准": [], "无损检测": [],
           "涂漆": [], "参数顺序": {}}
    try:
        cur = conn.cursor()

        # 1) 设计数据：主表
        #    2026-11-05 起把默认值（壳程数值/管程数值）也导出来：
        #    57 行里有 27 行带默认（如 焊接接头系数 1.0、耐压试验类型 液压试验），
        #    Agent 的填值规则是"抽到用抽到的，抽不到保留默认"。
        cur.execute("""SELECT 设计数据参数ID, 参数名称, 参数单位, 壳程数值, 管程数值, 所属类型, 所属型式
                       FROM 设计数据模板表 ORDER BY 设计数据参数ID""")
        seen = set()
        for pid, name, unit, dsh, dtu, typ, form in cur.fetchall():
            name = (name or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            out["设计数据"].append({
                # 参数ID 必须留着：界面显示顺序是按 ID 排的（见 设计数据参数顺序模板表），
                # 只留名字的话顺序模板就没法套用
                "参数ID": int(pid) if pid is not None else None,
                "参数名称": name,
                "参数单位": (unit or "").strip(),
                "所属类型": _split_types(typ),
                "所属型式": (form or "").strip() or "all",
                "默认壳程": (dsh or "").strip(),
                "默认管程": (dtu or "").strip(),
            })

        # 2) 设计数据：单选/多选枚举
        #    注意选项模板表的列名是英文的 type/editable/options，
        #    值是一个 JSON 数组的字符串，还带全角引号和 "—" 占位。
        cur.execute("SELECT 参数名称, type, options FROM 设计数据选项模板")
        for pname, sel_type, raw in cur.fetchall():
            pname = (pname or "").strip()
            opts = _parse_options(raw)
            if not pname or not opts:
                continue
            for item in out["设计数据"]:
                if item["参数名称"] == pname:
                    item["选项"] = opts
                    # single = 单选，multi = 多选拼接（如"气液组合试验"）
                    item["单选"] = str(sel_type or "").strip().lower() != "multi"
                    break

        # 3) 通用数据：默认值在「数值」列（如 基本风压 500、雪压值 300）
        cur.execute("""SELECT 参数名称, 参数单位, 数值, 所属类型, 所属型式
                       FROM 通用数据模板表 ORDER BY 通用数据参数ID""")
        out["通用数据"] = []
        for r in cur.fetchall():
            name = (r[0] or "").strip()
            if not name:
                continue
            out["通用数据"].append({
                "参数名称": name,
                "参数单位": (r[1] or "").strip(),
                "默认数值": (r[2] or "").strip(),
                "所属类型": (r[3] or "").strip() or "all",
                "所属型式": (r[4] or "").strip() or "all",
            })

        # 列名里带斜杠，必须加反引号，否则 MySQL 会把 / 当成语法分隔
        out["产品标准"] = _fetch_standard_names(cur)

        out["无损检测"] = _fetch_ndt(cur)
        out["涂漆"] = _fetch_paint(cur)

        # 4) 设计数据参数显示顺序
        #    库里 `设计数据参数顺序模板表`：模板名称 + 参数顺序（"[1,40,2,...]" 参数ID数组）。
        #    现有 4 行：完整输入 / 简洁输入 / 完整输入_容器 / 简洁输入_容器。
        #    这决定界面里设计数据表的**行序**（也就是主项目录入界面的顺序）。
        out["参数顺序"] = _fetch_param_orders(cur)
    finally:
        conn.close()
    return out


def _fetch_ndt(cur):
    """
    无损检测数据模板表 → 检测数据页签的行骨架。

    表结构（2026-11-05 查证，26 行）：
        无损检测数据参数ID / 接头种类 / 检测方法 /
        壳程_技术等级 / 壳程_检测比例 / 壳程_合格级别 /
        管程_技术等级 / 管程_检测比例 / 管程_合格级别 /
        所属类型 / 所属型式
    12 行是「管壳式热交换器」、14 行是「立式容器,卧式容器」，
    所以必须带 所属类型 出去给运行期过滤（跟产品标准/通用数据一个套路）。

    注意：**不能 SELECT DISTINCT 接头种类, 检测方法**。
      · 换热器和容器都有「A，B / U.T.」，DISTINCT 会把两行并成一行，
        所属类型随之丢失，过滤就失灵了（这一版之前的写法就是这个坑）。
      · 默认值（技术等级/比例/级别）也会一起丢。
    """
    cur.execute("""SELECT 无损检测数据参数ID, 接头种类, 检测方法,
                          壳程_技术等级, 壳程_检测比例, 壳程_合格级别,
                          管程_技术等级, 管程_检测比例, 管程_合格级别,
                          所属类型, 所属型式
                   FROM 无损检测数据模板表 ORDER BY 无损检测数据参数ID""")
    out = []
    for r in cur.fetchall():
        joints = (r[1] or "").strip()
        method = (r[2] or "").strip()
        if not joints and not method:
            continue
        out.append({
            "参数ID": int(r[0]) if r[0] is not None else None,
            "接头种类": joints,
            "检测方法": method,
            "默认壳程": [_s(r[3]), _s(r[4]), _s(r[5])],   # 技术等级/检测比例/合格级别
            "默认管程": [_s(r[6]), _s(r[7]), _s(r[8])],
            "所属类型": _s(r[9]) or "all",
            "所属型式": _s(r[10]) or "all",
        })
    return out


def _fetch_paint(cur):
    """
    涂漆数据模板表 → 涂漆数据页签的行骨架。

        涂漆数据参数ID / 用途 / 油漆类别 / 颜色 /
        干膜厚度（μm） / 涂漆面积 / 备注 / 所属类型 / 所属型式

    库里 18 行（换热器 12 + 容器 6），除「用途」外**全是空的**：
    涂漆是公司标准配置，模板只登记"要涂哪些部位"，
    具体油漆类别/颜色/厚度由项目涂漆规定填。所以这一页必然是
    "模板骨架 + 人工填写"，PDF 里通常也没有。
    """
    cur.execute("""SELECT 涂漆数据参数ID, 用途, 油漆类别, 颜色,
                          `干膜厚度（μm）`, 涂漆面积, 备注, 所属类型, 所属型式
                   FROM 涂漆数据模板表 ORDER BY 涂漆数据参数ID""")
    out = []
    for r in cur.fetchall():
        use = _s(r[1])
        if not use:
            continue
        out.append({
            "参数ID": int(r[0]) if r[0] is not None else None,
            "用途": use,
            "默认": {"油漆类别": _s(r[2]), "颜色": _s(r[3]),
                     "干膜厚度（μm）": _s(r[4]), "涂漆面积": _s(r[5]),
                     "备注": _s(r[6])},
            "所属类型": _s(r[7]) or "all",
            "所属型式": _s(r[8]) or "all",
        })
    return out


def _s(v):
    return ("" if v is None else str(v)).strip()


def _fetch_param_orders(cur):
    """
    读 `设计数据参数顺序模板表` → {模板名称: [参数ID, ...]}

    这是界面里设计数据表的**行序**来源（主项目录入界面也用它）：
        完整输入 / 简洁输入 / 完整输入_容器 / 简洁输入_容器
    注意库里现在只有这 4 行，**不是按 BKU/NEN 型式分**的；
    以后若新增 "完整输入_BKU" 这种带型式的模板，std_table 会优先匹配。

    参数顺序列是 varchar(255)，形如 "[1,40,2,3,...]" 或 "1,2,3"，
    两种都容错；解析失败不影响整份字典导出。
    """
    out = {}
    try:
        cur.execute("SELECT 模板名称, 参数顺序 FROM 设计数据参数顺序模板表")
        rows = cur.fetchall()
    except Exception:
        return out
    for name, raw in rows:
        name = (name or "").strip()
        seq = _parse_id_seq(raw)
        if name and seq:
            out[name] = seq
    return out


def _parse_id_seq(raw):
    """把 "[1,40,2]" / "1,40,2" 之类解析成 [1, 40, 2]。"""
    s = str(raw or "").strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            vals = json.loads(s)
            return [int(v) for v in vals if str(v).strip().lstrip("-").isdigit()]
        except Exception:
            pass
    return [int(v) for v in re.findall(r"\d+", s)]


def _split_types(typ):
    t = (typ or "").strip()
    if not t or t.lower() == "all":
        return ["all"]
    parts = []
    for sep in ("，", ",", "、", " "):
        t = t.replace(sep, "|")
    for p in t.split("|"):
        p = p.strip()
        if p:
            parts.append(p)
    return parts or ["all"]


def _parse_options(raw):
    """
    选项模板里存的是 JSON 数组字符串，实际数据有两个坑：
      1. 混了全角引号 “”   → json.loads 直接爆
      2. 数组里有 "—" 占位项 → 不是真选项，要去掉
    """
    if not raw:
        return []
    s = str(raw).strip()
    s = s.replace("“", '"').replace("”", '"').replace("，", ",")
    vals = []
    if s.startswith("["):
        try:
            vals = json.loads(s)
        except Exception:
            # 兜底：暴力抠引号里的东西
            import re as _re
            vals = _re.findall(r'"([^"]*)"', s)
    else:
        for sep in (",", "、", "|", "\n"):
            s = s.replace(sep, "\n")
        vals = s.split("\n")

    out = []
    for v in vals:
        v = str(v).strip()
        if v and v not in ("—", "-", "–", "无"):
            out.append(v)
    return out


def _fetch_standard_names(cur):
    """
    产品标准表的列名带斜杠（`规范/标准名称`），字段名必须加反引号，
    否则 MySQL 会把 / 当语法，报 1054 Unknown column。

    2026-11-05 起把默认代号也导出来：
        这张表的「规范/标准代号」就是条件输入里产品标准页的**默认值**
        （如 技术法规 → TSG 21-2016）。Agent 的规则是
        "解析到了用解析值，解析不到填默认值"，没有默认值这条规则就走不通。
    注意同名参数会按型式出多行（产品标准：管壳式/卧式容器各一行），
    导出时保留 所属类型，由 std_table 在运行期按产品型式过滤。
    """
    cur.execute("""SELECT `规范/标准名称`, `规范/标准代号`, `所属类型`
                   FROM 产品标准数据模板表 ORDER BY 产品标准数据参数ID""")
    out = []
    for name, code, typ in cur.fetchall():
        name = (name or "").strip()
        if not name:
            continue
        out.append({
            "参数名称": name,
            "默认代号": (code or "").strip(),
            "所属类型": (typ or "").strip() or "all",
        })
    return out


def _offline_snapshot():
    """数据库连不上时的兜底字典（与 db 导出结果等价的结构）。"""
    path = os.path.join(BASE_DIR, "param_dict_offline.json")
    if os.path.exists(path):
        with io.open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"设计数据": [], "通用数据": [], "产品标准": [], "无损检测": [], "涂漆": []}


def _write(data, source):
    payload = {
        "source": source,
        "n_设计数据": len(data.get("设计数据") or []),
        "data": data,
    }
    with io.open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print("已写出 %s（来源：%s，设计数据参数 %d 项）"
          % (OUT_PATH, source, payload["n_设计数据"]))


if __name__ == "__main__":
    main()
