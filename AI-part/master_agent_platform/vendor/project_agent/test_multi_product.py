# -*- coding: utf-8 -*-
"""
多产品拆分回归测试

用法：
    D:/Anaconda/envs/py39_clean/python.exe test_multi_product.py

断言分三级：
  FAIL  必须修：产品数不对、位号/名称/型式缺失、台数合计不对
  WARN  需留意：项目级字段缺失、型式不在库里（可能是库漏登记，不是抽取错误）
  OK    通过

为什么型式要分合法/不合法两类断言：
这份真实项目的 11 台设备里，BFU 和 BKM 不在「产品类型型式表」中，
抽取是对的、库里没有。如果哪天库补上了这两行，本脚本会从 WARN 变成 OK，
正好起到提醒作用，所以不能简单要求"全部合法"。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import product_splitter as ps
import schema

BASE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(os.path.dirname(BASE), "docs", "01-管壳式热交换器-输入文件")

PDF = os.path.join(DOCS, "DD-DDS-OST-PR-19001 管壳式换热器数据表 -20220808.pdf")
XLSX_TASK = os.path.join(DOCS, "项目执行任务书-渤中19-6 滨州工程-换热器.xlsx")
XLSX_REC = os.path.join(DOCS, "OED2022-32 渤中19-6 滨州工程-14台换热器--项目记录表 .xlsx")

EXPECT_PRODUCTS = 11        # 11 个位号（A/B 双台合并为一个位号）
EXPECT_UNITS = 14           # 数量列合计：1+2+2+1+1+1+2+1+1+1+1
EXPECT_FORMS = {"BKU", "BFU", "BES", "BKM"}

fails, warns, oks = [], [], []
_lines = []


def emit(s=""):
    """同时写终端和 UTF-8 报告文件。
    Windows 终端编码不统一时，看 output/multi_product_report.txt 更靠谱。"""
    _lines.append(str(s))
    try:
        print(s)
    except UnicodeEncodeError:
        print(str(s).encode("utf-8", "replace").decode("ascii", "replace"))


def fail(msg):
    fails.append(msg)


def warn(msg):
    warns.append(msg)


def ok(msg):
    oks.append(msg)


def main():
    missing = [p for p in (PDF, XLSX_TASK, XLSX_REC) if not os.path.exists(p)]
    if missing:
        emit("跳过：找不到测试文件")
        for p in missing:
            emit("   " + p)
        return 2

    r = ps.split([PDF, XLSX_TASK, XLSX_REC])
    prods = r["products"]

    # --- 产品数量 ---
    if len(prods) == EXPECT_PRODUCTS:
        ok("产品数 %d" % len(prods))
    else:
        fail("产品数应为 %d，实际 %d" % (EXPECT_PRODUCTS, len(prods)))

    total = sum(int(p.get("_qty") or 1) for p in prods)
    if total == EXPECT_UNITS:
        ok("台数合计 %d" % total)
    else:
        fail("台数合计应为 %d，实际 %d（_qty 是否丢失？）" % (EXPECT_UNITS, total))

    # --- 每台设备的关键字段 ---
    for i, p in enumerate(prods, 1):
        tag = p.get("设备位号") or ""
        if not tag.startswith("OST-"):
            fail("第 %d 台位号异常：%r" % (i, tag))
        if not (p.get("产品名称") or "").strip():
            fail("第 %d 台（%s）缺产品名称" % (i, tag))
        if not (p.get("产品型式") or "").strip():
            fail("第 %d 台（%s）缺产品型式" % (i, tag))
        if not (p.get("产品类型") or "").strip():
            fail("第 %d 台（%s）缺产品类型" % (i, tag))
        # 名称里不应粘上别的字段（PDF 排版挤行时会粘连）
        nm = p.get("产品名称") or ""
        for bad in ("设备规格", "Equipment", "需要台数", "Item NO"):
            if bad in nm:
                fail("第 %d 台名称里粘了其它字段：%r" % (i, nm))

    # --- 型式覆盖率 ---
    forms = {(p.get("产品型式") or "").strip() for p in prods}
    forms.discard("")
    if EXPECT_FORMS <= forms:
        ok("型式全部识别：%s" % "/".join(sorted(forms)))
    else:
        fail("型式缺失：期望 %s，实际 %s"
             % ("/".join(sorted(EXPECT_FORMS)), "/".join(sorted(forms)) or "无"))

    # --- 项目级字段：自动抽取的 ---
    for k in ("项目名称", "业主名称", "所属部门", "工程总包方", "设计阶段"):
        v = (r["project"].get(k) or "").strip()
        if v:
            ok("项目字段 %s = %s" % (k, v[:30]))
        else:
            warn("项目字段缺失：%s" % k)

    # --- 人工填写字段：必须留空（文件里的编号口径不对，不能自动填）---
    leaked = []
    for k in schema.MANUAL_FIELDS:
        if (r["project"].get(k) or "").strip():
            leaked.append("项目.%s=%s" % (k, r["project"][k]))
    for p in prods:
        for k in schema.MANUAL_FIELDS:
            if (p.get(k) or "").strip():
                leaked.append("%s.%s=%s" % (p.get("设备位号"), k, p[k]))
    if leaked:
        fail("人工填写字段被自动填了值（口径不对，会误导用户）：%s"
             % "；".join(leaked[:6]))
    else:
        ok("人工填写字段（%s）均未自动抽取" % "、".join(schema.MANUAL_FIELDS))

    # --- 设计阶段必须是库里的合法写法 ---
    stage = (r["project"].get("设计阶段") or "").strip()
    allowed = schema.load_allowed_values().get("stages") or []
    if stage and allowed and stage not in allowed:
        fail("设计阶段「%s」不在库里的合法值 %s 中" % (stage, allowed))

    # --- 型式合法性（不在库里只告警，因为抽取是对的、库缺登记） ---
    types = schema.load_allowed_values().get("types") or {}
    legal = set()
    for fs in types.values():
        legal |= set(fs)
    bad = []
    for p in prods:
        f = (p.get("产品型式") or "").strip()
        if f and legal and f not in legal:
            bad.append("%s(%s)" % (f, p.get("设备位号")))
    if bad:
        warn("以下型式不在数据库合法表中，落库前需要补登记或人工改：%s"
             % "、".join(bad))
    elif legal:
        ok("全部型式都在库内合法表")

    # --- 图号改为人工填写后，设备子码不该再被当成图号 ---
    # 源表那列叫「设备子码」，值是 10/20/…/110，与数据库「图号前缀」不是一回事。
    # 这条断言防止哪天又把它接回去。
    got_dwg = [p for p in prods if (p.get("图号前缀") or "").strip()]
    if got_dwg:
        fail("图号仍被自动填了 %d 台（应为空，改人工填写）：%s"
             % (len(got_dwg),
                "、".join("%s=%s" % (p.get("设备位号"), p.get("图号前缀"))
                          for p in got_dwg[:3])))
    else:
        ok("图号未自动抽取（改为人工填写）")

    # --- 默认值：图号前缀 A01、设计版次 1 ---
    # 这两个字段不抽，但界面要给个起点。默认值在界面层（schema.apply_defaults）加，
    # 抽取层仍然保持空，所以上面两条断言不会互相打架。
    if schema.DEFAULTS.get("图号前缀") == "A01" and schema.DEFAULTS.get("设计版次") == "1":
        ok("默认值已登记：图号前缀 A01 / 设计版次 1")
    else:
        fail("默认值不对：%s" % schema.DEFAULTS)

    probe = {"图号前缀": "B02", "设计版次": ""}
    schema.apply_defaults(probe)
    if probe["图号前缀"] != "B02" or probe["设计版次"] != "1":
        fail("apply_defaults 覆盖了已有值或没补空值：%s" % probe)
    else:
        ok("apply_defaults 只补空值，不覆盖手填内容")

    # --- 预览隐藏规则：总包方/所属部门/项目编号/产品编号 空着就不占一行 ---
    still_shown = [k for k in schema.HIDE_IF_EMPTY if schema.should_show(k, "")]
    if still_shown:
        fail("这些字段值为空却仍会显示：%s" % "、".join(still_shown))
    else:
        ok("空的总包方/部门/编号在预览界面隐藏（%d 个字段）"
           % len(schema.HIDE_IF_EMPTY))
    # 但有值时必须照常显示，别把抽到的信息也藏了
    kept = [k for k in schema.HIDE_IF_EMPTY if not schema.should_show(k, "有值")]
    if kept:
        fail("这些字段有值却被隐藏：%s" % "、".join(kept))
    else:
        ok("有值时照常显示，不会误藏")

    # --- 设计阶段：必须能用原文写法定位（防回归）---
    # 产品的「设计阶段」值被归一成「详细设计」，但原文写的是「详细工程设计」。
    # evidence 里必须带 original，否则依据列会显示"原文无此字符串"。
    ev_ps = (r.get("evidence") or {}).get("products") or []
    no_orig = []
    for i, p in enumerate(prods):
        evd = ev_ps[i] if i < len(ev_ps) else {}
        e = evd.get("设计阶段") or {}
        stage = (p.get("设计阶段") or "").strip()
        if stage and stage not in ("详细设计", "方案设计"):
            continue
        # 只要归一过（值 != 原文写法），就必须有 original
        if e and (e.get("page") or e.get("file")) and not e.get("original"):
            no_orig.append(p.get("设备位号"))
    if no_orig:
        fail("这些设备的设计阶段依据缺 original（依据列会显示无此写法）：%s"
             % "、".join(no_orig))
    elif ev_ps:
        ok("设计阶段依据带原文写法，可定位")

    # --- 页码范围：后续模块靠它只读自己那段，切错了整条链都错 ---
    no_span = [p.get("设备位号") for p in prods
               if not (p.get("_page_start") and p.get("_page_end"))]
    if no_span:
        fail("这些设备没算出页码范围：%s" % "、".join(no_span))
    else:
        # 按页范围排序，检查连续不重叠
        spans = sorted((p["_page_start"], p["_page_end"], p.get("设备位号"))
                       for p in prods)
        gaps, overlaps = [], []
        for a, b in zip(spans, spans[1:]):
            if b[0] != a[1] + 1:
                if b[0] <= a[1]:
                    overlaps.append("%s 与 %s" % (a[2], b[2]))
                else:
                    gaps.append("%s→%s" % (a[2], b[2]))
        if overlaps:
            fail("页码范围有重叠：%s" % "、".join(overlaps))
        elif gaps:
            warn("页码范围不连续（中间有别的页）：%s" % "、".join(gaps))
        else:
            span_desc = "、".join("P%d-%d" % (a, b) for a, b, _ in spans[:3])
            ok("页码范围连续：%s … 共 %d 段" % (span_desc, len(spans)))

    # --- 依据：每台设备都应有页码 ---
    no_page = [p.get("设备位号") for p in prods if not p.get("_page")]
    if no_page:
        warn("这些设备没记录来源页码，依据列会退化为全文定位：%s"
             % "、".join(no_page))
    else:
        ok("每台设备都记录了来源页码")

    # --- 输出 ---
    emit()
    emit("=" * 66)
    emit("多产品拆分回归   FAIL=%d  WARN=%d  OK=%d" % (len(fails), len(warns), len(oks)))
    emit("=" * 66)
    for m in oks:
        emit("  [OK]   %s" % m)
    for m in warns:
        emit("  [WARN] %s" % m)
    for m in fails:
        emit("  [FAIL] %s" % m)

    emit()
    emit("产品清单：")
    for i, p in enumerate(prods, 1):
        emit("  %2d. %-16s %-22s %-5s P%s-%s"
             % (i, p.get("设备位号"), p.get("产品名称") or "",
                p.get("产品型式") or "",
                p.get("_page_start"), p.get("_page_end")))

    if r.get("notes"):
        emit()
        emit("抽取提示：")
        for n in r["notes"]:
            emit("  - %s" % n)

    try:
        out_dir = os.path.join(BASE, "output")
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "multi_product_report.txt"),
                  "w", encoding="utf-8") as f:
            f.write("\n".join(_lines))
    except Exception:
        pass

    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
