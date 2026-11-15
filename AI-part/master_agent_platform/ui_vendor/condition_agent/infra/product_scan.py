# -*- coding: utf-8 -*-
"""
产品目录扫描：从"已拆分好的产品文件夹/小 PDF"里恢复产品清单。

背景
----
项目管理的流程里，用户上传整份项目文件后，会把里面每个产品的 PDF 页面拆出来，
存到各自的产品文件夹里。条件输入 Agent 进入时，不再重新读整份大 PDF，
而是直接扫这些"每个产品一本小 PDF"的产物，一个产品一个产品地处理。

文件名约定（来自 split_demo 实测）：
    01_OST-E-1901_P3-6.pdf       → 序号 01，位号 OST-E-1901，原页 P3-6
    02_OST-E-1903A-B_P7-10.pdf   → 位号 OST-E-1903A-B（A/B 双台共一本）

所以这里要能从文件名里同时抠出三样东西：
    1. 序号（01/02/...，排序用）
    2. 位号（OST-E-1901 / OST-E-1903A-B，挂到产品上）
    3. 页码（P3-6，溯源时提示"这是原大 PDF 的第几页"）
"""
import os
import re

# 位号：OST 开头（或 OED 等其他前缀），后面跟 - 和字母数字，可能带 A/B 后缀
# 实测样本：OST-E-1901 / OST-E-1903A-B / OST-WC-1902
_TAG_IN_NAME = re.compile(r"(?:OST|OED|O)\s*[-_]\s*[A-Z]{1,3}\s*[-_]\s*\d{3,4}[A-Z/\-]*",
                          re.I)
_PAGE_IN_NAME = re.compile(r"[Pp]\s*(\d+)\s*(?:[-_~到]\s*(\d+))?", )


def scan_products(root_dir):
    """
    扫描 root_dir 下所有产品小 PDF，返回产品清单。

    返回：
        [{
            "index": 1,               # 序号（从文件名前缀或排序得出）
            "tag": "OST-E-1901",      # 设备位号
            "name": "",               # 设备名称（本函数不读 PDF，先留空，打开时再补）
            "pdf_path": ".../01_OST-E-1901_P3-6.pdf",
            "page_range": "P3-6",     # 原大 PDF 的页码范围（提示用）
            "file": "01_OST-E-1901_P3-6.pdf",
        }, ...]
    按序号升序。扫不到任何 PDF 返回空列表。
    """
    if not root_dir or not os.path.isdir(root_dir):
        return []

    pdfs = []
    for dirpath, _dirs, files in os.walk(root_dir):
        for fn in files:
            if fn.lower().endswith(".pdf"):
                pdfs.append(os.path.join(dirpath, fn))

    products = []
    for path in pdfs:
        fn = os.path.basename(path)
        tag = _extract_tag(fn)
        page_range = _extract_page_range(fn)
        products.append({
            "index": _extract_index(fn),
            "tag": tag,
            "name": "",
            "pdf_path": path,
            "page_range": page_range,
            "file": fn,
        })

    # 按序号排，序号拿不到的按文件名排，保证顺序稳定
    products.sort(key=lambda p: (p["index"], p["file"]))
    # 重新编号，让 index 连续从 1 开始（避免文件名序号不连续时列表有空洞）
    for i, p in enumerate(products, 1):
        p["index"] = i
    return products


def _extract_index(fn):
    """从 '01_OST-E-1901_P3-6.pdf' 里取 1。取不到返回一个很大的数，排最后。"""
    m = re.match(r"^(\d{1,3})[_\-.]", fn)
    return int(m.group(1)) if m else 9999


def _extract_tag(fn):
    """从文件名抠位号。"""
    m = _TAG_IN_NAME.search(fn)
    if not m:
        return ""
    tag = m.group(0)
    # 去掉可能粘着的尾部分隔符
    tag = re.sub(r"[_\-.\s]+$", "", tag)
    return tag


def _extract_page_range(fn):
    """从 '01_OST-E-1901_P3-6.pdf' 取 'P3-6'。取不到返回空串。"""
    m = re.search(r"[Pp]\s*(\d+)\s*(?:[-_~到]\s*(\d+))?", fn)
    if not m:
        return ""
    a, b = m.group(1), m.group(2)
    return "P%s" % (a if not b else "%s-%s" % (a, b))


def scan_default():
    """用默认的产品目录（项目管理 Agent 的输出）扫描。"""
    import config
    root = getattr(config, "PRODUCT_DIR", None) or config.DEFAULT_PRODUCT_DIR
    return scan_products(root)


def match_tag(products, tag):
    """按位号挑一个产品。tag 为空返回 None。"""
    if not tag:
        return None
    for p in products:
        if p["tag"].lower() == tag.lower():
            return p
    return None
