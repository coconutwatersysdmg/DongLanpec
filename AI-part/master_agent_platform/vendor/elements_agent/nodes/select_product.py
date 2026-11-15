# -*- coding: utf-8 -*-
"""步骤2：产品/台设备识别、歧义标记、批量建产品骨架。"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from elements_agent.models import DocumentChunk, ProductCandidate

# 文件名/正文中常见：位号、产品名、数字对（可能 DN 或压力）
_TAG_RE = re.compile(
    r"(?:设备位号|位号)[:：\s]*([A-Za-z0-9\-_/]+)",
    re.I,
)
_NAME_RE = re.compile(
    r"(?:产品名称|设备名称)[:：\s]*([^\n\r,，;；]{2,40})"
)
_NUM_PAIR_RE = re.compile(
    r"\b([A-Za-z]{2,6})\s*[-_]?\s*(\d{2,4})\s*[\/×xX\-_\s]+\s*(\d{2,4})\b"
)


def resolve_product_candidates(
    chunks: Sequence[DocumentChunk],
    user_text: str = "",
    current_product_id: str = "",
) -> List[ProductCandidate]:
    """从切片与用户输入抽产品候选；数字对歧义不强行判定。"""
    texts: List[str] = []
    for ch in chunks:
        texts.append(os.path.basename(ch.file_path or ""))
        if ch.text:
            texts.append(ch.text[:2000])
    if user_text:
        texts.append(user_text)
    blob = "\n".join(texts)

    candidates: List[ProductCandidate] = []
    seen = set()

    for m in _TAG_RE.finditer(blob):
        tag = m.group(1).strip()
        if tag and tag not in seen:
            seen.add(tag)
            candidates.append(ProductCandidate(raw_name=tag, tag_no=tag, count=1))

    for m in _NAME_RE.finditer(blob):
        name = m.group(1).strip()
        if name and name not in seen:
            seen.add(name)
            candidates.append(ProductCandidate(raw_name=name, count=1))

    for m in _NUM_PAIR_RE.finditer(blob):
        prefix, a, b = m.group(1), m.group(2), m.group(3)
        raw = f"{prefix} {a} {b}"
        if raw in seen:
            continue
        seen.add(raw)
        guesses = [
            f"可能为公称直径 DN{a} / 另一尺寸 {b}",
            f"可能为设计压力相关数值 {a}/{b}（单位待确认）",
            f"可能为产品型号片段 {prefix}-{a}/{b}",
        ]
        candidates.append(
            ProductCandidate(
                raw_name=raw,
                tag_no=prefix,
                guesses=guesses,
                ambiguous=True,
                count=1,
            )
        )

    # 台数：如「14台」
    count_m = re.search(r"(\d+)\s*台", blob)
    batch_n = int(count_m.group(1)) if count_m else 0
    if batch_n >= 2 and candidates:
        # 标记批量意图到第一条非歧义或第一条
        target = next((c for c in candidates if not c.ambiguous), candidates[0])
        target.count = batch_n

    if current_product_id and not any(c.product_id == current_product_id for c in candidates):
        candidates.insert(
            0,
            ProductCandidate(
                raw_name=current_product_id,
                product_id=current_product_id,
                count=1,
            ),
        )

    return candidates


def format_candidate_report(cands: Sequence[ProductCandidate]) -> List[str]:
    lines = [f"产品/台设备候选 {len(cands)} 项："]
    for i, c in enumerate(cands, 1):
        flag = "【歧义】" if c.ambiguous else ""
        pid = f" ID={c.product_id}" if c.product_id else ""
        cnt = f" ×{c.count}台" if c.count and c.count > 1 else ""
        lines.append(f"  {i}. {flag}{c.raw_name}{pid}{cnt}")
        for g in c.guesses:
            lines.append(f"      · {g}")
    if any(c.ambiguous for c in cands):
        lines.append("提示：歧义项请在对话中确认（如：按公称直径 DN600 理解），或下拉选择已有产品。")
    return lines


def batch_create_product_shells(
    *,
    project_id: str,
    base_name: str,
    count: int,
    tag_prefix: str = "",
) -> Tuple[List[Dict[str, str]], List[str]]:
    """
    批量创建活动库产品壳（仅写 产品设计活动表 最小字段）。
    完整模板复制依赖项目管理流程；此处提供可调用骨架。
    返回 ([{产品ID,...}], logs)
    """
    logs: List[str] = []
    created: List[Dict[str, str]] = []
    if count <= 0:
        return [], ["台数无效"]
    if not project_id:
        return [], ["缺少项目ID，无法批量建产品（请先在项目管理中打开项目）"]

    try:
        from modules.cailiaodingyi.db_cnt import get_connection
        from modules.cailiaodingyi.funcs.funcs_pdf_change import db_config_1
    except Exception as e:
        return [], [f"导入数据库失败: {e}"]

    try:
        conn = get_connection(**db_config_1)
    except Exception as e:
        return [], [f"连接活动库失败: {e}"]

    try:
        with conn.cursor() as cur:
            for i in range(1, count + 1):
                pid = _new_product_id()
                tag = f"{tag_prefix}{i:02d}" if tag_prefix else f"{base_name}-{i:02d}"
                try:
                    cur.execute(
                        """
                        INSERT INTO 产品设计活动表 (产品ID, 项目ID)
                        VALUES (%s, %s)
                        ON DUPLICATE KEY UPDATE 项目ID = VALUES(项目ID)
                        """,
                        (pid, project_id),
                    )
                    created.append(
                        {
                            "产品ID": pid,
                            "项目ID": project_id,
                            "产品名称": base_name,
                            "设备位号": tag,
                        }
                    )
                    logs.append(f"已创建产品壳 {pid} 位号={tag}")
                except Exception as e:
                    logs.append(f"创建失败 {tag}: {e}")
        conn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return created, logs + [f"批量建产品回滚: {e}"]
    finally:
        conn.close()

    logs.append(
        f"合计创建 {len(created)} 台产品壳。元件材料模板需在「产品定义/元件定义」侧按类型继续初始化。"
    )
    return created, logs


def _new_product_id() -> str:
    return "PD" + datetime.now().strftime("%Y%m%d%H%M%S%f")[:18]
