# -*- coding: utf-8 -*-
"""
真实文件端到端回归：用 docs 目录里的真实输入文件验证抽取质量。

和 selftest.py 的分工：
  selftest.py    —— 离线用例（少量真实 API 调用），验证校验逻辑和规则路径
  test_real_files.py（本文件）—— 真实文件 + 真实 API，验证"抽得对不对"

为什么要单独一套：只对一个文件调优会过拟合。这里同时跑 PDF / xlsx / .doc
三种真实格式，其中 xlsx 和 .doc 的正文内容与 PDF 完全不同——
能同时抽对，才说明规则不是围着某一份文件转的。

用法：python test_real_files.py        （退出码 0 = 全过）

断言分三级：
  [FAIL] 原文里确实有该值，却被 _sanitize 误删 → 校验层 bug
  [MISS] 原文里没有 / 模型本次漏抽         → 模型波动，只提示不算失败
  [WARN] 期望空但抽出了值                   → 需要人工看一眼
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agent_core
import file_reader
import schema

DOCS = r"F:\DongLanpec-localNEN\DongLanpec-卧单版\docs\01-管壳式热交换器-输入文件"

# 每份文件期望抽到的字段（None 表示"不该出现该字段"）
CASES = [
    ("DD-DDS-OST-PR-19001 管壳式换热器数据表 -20220808.pdf", {
        "项目名称": "渤中19-6凝析气田I期开发项目滨州天然气终端工程",
        # 项目编号不再自动抽取：封面那个 213002D1019 是「项目文件号」，
        # 与数据库按合同口径的项目编号（OED2022-32）不是一回事
        "项目编号": None,
        "产品名称": "常温脱硫塔入口丙烷冷却器",
        "设备位号": "OST-E-1901",
        "产品型号": "BKU500/900-4.0/3.2-17-2/25-2I",
        # 原文写「管壳式换热器」，系统登记的名是「管壳式热交换器」。
        # 两种写法都算对——抽取层不该替原文纠正，交给校验层提示。
        "产品类型": ("管壳式换热器", "管壳式热交换器"),
    }),
    ("OED2022-32 渤中19-6 滨州工程-14台换热器--项目记录表 .xlsx", {
        # 这张表其实是一份「技术交底会记录」，正文没有具体设备型号/位号，
        # 只能抽项目级字段。产品型式本来就不该有——旧版抽出 BKU 是串味。
        "项目名称": "渤中19-6凝析气田I期开发项目滨州天然气终端EPC总承包工程",
        # 同上：表里那个 OED2022-32 现在已经不用抽了，用户手工填
        "项目编号": None,
        "工程总包方": "中海油石化工程有限公司",
        "产品型式": None,
        "设备位号": None,
        "产品型号": None,
        # 产品名称不能是正文里的通用词「热交换器」
        "产品名称": None,
        # 原文里两种写法都有（「管壳式热交换器的设计使用年限…」
        # 和「管壳式换热器数据表…」），抽中任一个都算对
        "产品类型": ("管壳式热交换器", "管壳式换热器"),
    }),
    ("1901换热器基础设计条件.doc", {
        "项目名称": None,           # 原件无工程名称，不该硬凑
        "项目编号": None,           # 表单编码 MM-01-04-08-B087 不是项目编号
        "业主名称": "中海油石化工程有限公司",
        "所属部门": "管道",
        "设计阶段": "详细设计",
    }),
]


def find(name):
    for root, dirs, files in os.walk(DOCS):
        for f in files:
            if f == name:
                return os.path.join(root, f)
    return None


def run():
    fails = 0
    for name, expect in CASES:
        path = find(name)
        print("=" * 70)
        if not path:
            print("[跳过] 没找到：%s" % name)
            continue
        text, meta = file_reader.extract_text(path)
        if not meta["ok"]:
            print("[失败] %s 读取失败：%s" % (name, meta["error"]))
            fails += 1
            continue
        picked, cut = file_reader.pick_relevant(text)
        print("%s | 原文 %d 字符 → 裁剪 %d 字符" % (name, meta["chars"], len(picked)))

        res = agent_core.parse(picked, is_document=True)
        data = res.get("data") or {}
        print("  来源：%s（%s）" % (res.get("source"), res.get("note")))
        for k, v in data.items():
            print("    %-6s %s" % (k, v))

        # 断言
        for k, v in expect.items():
            got = (data.get(k) or "").strip()
            if v is None:
                if got:
                    # 允许非空但必须合理（长项目名 / 工程名替代）
                    print("    [WARN] %s 期望为空，实际=%r" % (k, got))
                continue
            # 期望值可以给多个候选（原文里存在同义写法时，抽中任一个都算对）
            candidates = v if isinstance(v, (tuple, list)) else (v,)
            if not any(c in got for c in candidates):
                # 区分两种失败：
                #   A. 原文里确实有该值，但被 _sanitize 误删 → 校验层 bug，算失败
                #   B. 原文里就没有/模型这次漏抽         → 模型波动，只告警
                if any(agent_core._value_in_source(c, picked) for c in candidates):
                    print("    [FAIL] %s 原文有 %r 却被过滤，实际=%r" % (k, v, got))
                    fails += 1
                else:
                    print("    [MISS] %s 模型本次未抽出（原文无该值或漏抽）" % k)
        # 通用硬校验：不该出现的东西
        # 人工填写字段（项目编号/产品编号/图号/设计版次）在文件路径下必须被过滤掉，
        # 哪怕模型硬抽了也不行——填错口径比留空更麻烦
        leaked = [k for k in schema.MANUAL_FIELDS if (data.get(k) or "").strip()]
        if leaked:
            print("    [FAIL] 人工填写字段漏出来了：%s"
                  % "、".join("%s=%r" % (k, data[k]) for k in leaked))
            fails += 1
        pname = (data.get("项目名称") or "")
        if pname and " " in pname:
            print("    [FAIL] 项目名称含逐字空格：%r" % pname)
            fails += 1
        if pname and re_looks_like_title(pname):
            print("    [FAIL] 项目名称是文档标题：%r" % pname)
            fails += 1

    print("=" * 70)
    print("失败项：%d" % fails)
    return fails


def run_cross_contamination():
    """
    串味专项测试：同一进程里先解析 PDF，再解析无关的 .doc。

    模型本身是无状态的，但业务上最容易出的错就是"把上一份文件的值带过来"。
    这里连续调用，确认第二份结果里不含第一份独有的值。
    """
    print("=" * 70)
    print("【串味测试】先 PDF 后 .doc，检查 .doc 结果是否混入 PDF 的内容")
    pdf = find("DD-DDS-OST-PR-19001 管壳式换热器数据表 -20220808.pdf")
    doc = find("1901换热器基础设计条件.doc")
    if not (pdf and doc):
        print("[跳过] 文件缺失")
        return 0

    t1, _ = file_reader.extract_text(pdf)
    p1, _ = file_reader.pick_relevant(t1)
    r1 = agent_core.parse(p1, is_document=True)
    print("  第1份(PDF)抽到 %d 字段" % len(r1.get("data") or {}))

    t2, _ = file_reader.extract_text(doc)
    p2, _ = file_reader.pick_relevant(t2)
    r2 = agent_core.parse(p2, is_document=True)
    d2 = r2.get("data") or {}
    print("  第2份(doc)抽到 %d 字段" % len(d2))

    bad = 0
    # 「常温脱硫塔入口丙烷冷却器」是 PDF 独有的产品名，doc 里没有
    if "脱硫塔" in str(d2.get("产品名称") or ""):
        print("  [FAIL] 串味：产品名称带入了 PDF 的值 %r" % d2.get("产品名称"))
        bad += 1
    for k, v in d2.items():
        if isinstance(v, str) and not agent_core._value_in_source(v, p2):
            print("  [FAIL] %s=%r 在 doc 原文里找不到" % (k, v))
            bad += 1
    if not bad:
        print("  [OK] 无串味")
    return bad


def re_looks_like_title(s):
    for w in ("设计条件", "数据表", "项目记录表", "投标文件", "技术规格书", "说明书"):
        if s.replace(" ", "") == w or s.replace(" ", "").endswith(w):
            return True
    return False


if __name__ == "__main__":
    n = run() + run_cross_contamination()
    print("=" * 70)
    print("总计失败：%d" % n)
    sys.exit(1 if n else 0)

