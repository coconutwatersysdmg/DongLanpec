# -*- coding: utf-8 -*-
"""
多设备文档切块。

为什么需要这一层
----------------
一份《管壳式换热器数据表》PDF 有 46 页，里面装了 **13 台设备**，
每台 4 页（工艺操作数据 / 结构参数 / 设备设计数据 / 制造检验）。

如果直接整份文件丢给抽取器，会发生这种事（实测踩到）：

    设计压力  2.56 / 3.2   ← 取自第 25 页，那是第 6 台设备的值
    设计温度  -45 / 65     ← 取自第 5 页，那是第 1 台设备的值

温度和压力来自**不同设备**，拼在一起是一份根本不存在的工况。
在别的行业可能只是"数据不准"，在压力容器设计里是会出安全事故的。

所以：先切块，再按块抽取，绝不跨设备。
"""
import re

# 设备块首页的标志行。实测这条最可靠：
#     设备位号 Item NO.：OST-E-1901
#     设备名称 Equipment name：常温脱硫塔入口丙烷冷却器
_TAG_PAT = re.compile(r"设备位号\s*Item\s*NO\.?\s*[:：]\s*([^\s、,，;；]+)", re.I)
_NAME_PAT = re.compile(r"设备名称\s*Equipment\s*name\s*[:：]\s*(.+?)(?:设备规格|Equipment\s*spec|$)", re.I)
_SPEC_PAT = re.compile(r"设备规格\s*Equipment\s*specification\s*[:：]\s*(\S+)", re.I)


def _find_tag(text):
    m = _TAG_PAT.search(text)
    return m.group(1).strip() if m else ""


def _find_name(text):
    m = _NAME_PAT.search(text)
    if m:
        name = m.group(1).strip()
        name = re.split(r"设备规格|Equipment\s*spec", name, flags=re.I)[0].strip()
        if name:
            return name[:60]
    # 退路：有的表把"设备名称："和名字拆成两行
    lines = [l.strip() for l in text.split("\n")]
    for i, ln in enumerate(lines):
        if re.search(r"设备名称|Equipment\s*name", ln, re.I):
            if "：" in ln or ":" in ln:
                tail = re.split(r"[:：]", ln, maxsplit=1)[-1].strip()
                tail = re.split(r"设备规格|Equipment\s*spec", tail, flags=re.I)[0].strip()
                if tail:
                    return tail[:60]
            elif i + 1 < len(lines) and "规格" not in lines[i + 1]:
                return lines[i + 1][:60]
    return ""


def _find_spec(text):
    m = _SPEC_PAT.search(text)
    return m.group(1).strip() if m else ""


def split_equipment(pages):
    """
    把 pages（[{"no","text"}]）按设备切块。

    返回：
        blocks = [{
            "tag": "OST-E-1901",          # 设备位号
            "name": "常温脱硫塔入口丙烷冷却器",
            "spec": "BES800-4-125-4.5/25-2I",   # 规格型号（可能为空）
            "pages": [{"no":3,"text":...}, ...],
            "page_range": "3-6",
        }, ...]

    只有一页带位号时就返回单块（等于不切）。
    一页都没有位号时返回空列表，调用方按"整份文件一台设备"处理。
    """
    if not pages:
        return []

    starts = []
    for idx, p in enumerate(pages):
        tag = _find_tag(p["text"])
        if tag:
            starts.append((idx, tag, _find_name(p["text"]), _find_spec(p["text"])))

    if not starts:
        return []

    blocks = []
    for k, (idx, tag, name, spec) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(pages)
        sub = pages[idx:end]
        nos = [p["no"] for p in sub]
        blocks.append({
            "tag": tag,
            "name": name,
            "spec": spec,
            "pages": sub,
            "page_range": ("%d-%d" % (min(nos), max(nos))) if nos else "",
        })
    return blocks


def summary(blocks):
    """给界面用的一句话摘要。"""
    if not blocks:
        return ""
    if len(blocks) == 1:
        b = blocks[0]
        return "识别到 1 台设备：%s %s（第 %s 页）" % (b["tag"], b["name"], b["page_range"])
    names = "、".join(b["tag"] for b in blocks[:4])
    more = "" if len(blocks) <= 4 else " 等"
    return "识别到 %d 台设备：%s%s" % (len(blocks), names, more)


def pick(blocks, key):
    """
    按位号或序号挑一台。key 可以是：
        "OST-E-1901"  位号精确匹配（大小写不敏感）
        "1" / "第1台"  序号
    都匹配不到返回 None。
    """
    if not blocks:
        return None
    k = (key or "").strip()
    if not k:
        return blocks[0]

    for b in blocks:
        if b["tag"].lower() == k.lower():
            return b

    m = re.search(r"\d+", k)
    if m:
        n = int(m.group(0))
        if 1 <= n <= len(blocks):
            return blocks[n - 1]
        # 也可能是位号里的数字，如 "1901" → 模糊匹配
        for b in blocks:
            if str(n) in b["tag"]:
                return b
    return None
