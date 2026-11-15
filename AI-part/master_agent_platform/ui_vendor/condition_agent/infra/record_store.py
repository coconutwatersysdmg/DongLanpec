# -*- coding: utf-8 -*-
"""
抽取结果落盘（旁路日志）

设计原则（与项目管理版一致）：**只追加，不参与业务**
- 每次抽取完成后追加一行 JSON 到 output/records.jsonl
- 写日志失败绝不影响主流程（异常在这里全部吞掉并打警告）
- 界面仍读内存里的结果，本模块不改变任何显示逻辑

与项目管理版的差异
------------------
条件输入的结果是**一长串参数行**（含侧位、页码、档位），不是十几个固定字段。
所以记录结构从 `"data": {字段: 值}` 换成 `"rows": [{param,side,value,page,tier}]`。

另外多记三样项目管理版没有的东西：
    equipment       这次抽的是哪台设备（多设备文档里必须留痕）
    n_equipment     文件里一共几台设备
    skipped         被派生字段规则拦掉的参数（留痕，方便复盘规则是否过严）

为什么用 JSONL 而不是一个大 JSON 数组：
  - 追加写不用读整个文件，几十万条也不卡
  - 某一行写坏了只损失那一行
  - pandas / Excel / grep 都能直接读
"""
import io
import json
import os
import threading
from datetime import datetime

import config

LOG_PATH = config.RECORD_PATH

# 单文件上限，超过就滚动一份备份，避免无限增长
MAX_BYTES = 20 * 1024 * 1024      # 20 MB

_lock = threading.Lock()


def record(result, file_info=None, raw_input=None, extra=None):
    """
    追加一条抽取记录。

    result:    extractor.extract() + proposal.build() 之后的 dict
               （含 items / rows / source / note / skipped / equipment / blocks）
    file_info: {"name","kind","chars","pages","path"}
    raw_input: 预留；条件输入不存全文，只存长度
    extra:     预留自定义字段

    返回写入的记录 dict；失败返回 None（不抛异常）。
    """
    try:
        res = result or {}
        rows = res.get("rows") or []
        eq = res.get("equipment") or {}
        skipped = res.get("skipped") or []

        # 只存"有值"的行，避免日志里一堆空占位
        filled = [r for r in rows if (r.get("value") or "").strip()]

        rec = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "input_type": "file" if file_info else "text",
            "file": (file_info or {}).get("name"),
            "file_kind": (file_info or {}).get("kind"),
            "file_chars": (file_info or {}).get("chars"),
            "file_pages": (file_info or {}).get("pages"),
            "input_chars": len(raw_input) if raw_input else 0,
            "source": res.get("source"),
            "note": res.get("note"),
            "equipment": {"tag": eq.get("tag"), "name": eq.get("name"),
                          "page_range": eq.get("page_range")} if eq else None,
            "n_equipment": res.get("n_equipment", 0),
            "n_rows": len(rows),
            "n_filled": len(filled),
            "n_errors": sum(1 for r in rows if r.get("errors")),
            "n_confirm": sum(1 for r in rows
                             if r.get("tier") == "confirm"),
            "n_manual": sum(1 for r in rows
                            if r.get("tier") == "manual"),
            "rows": [{"param": r.get("param"), "side": r.get("side"),
                      "value": r.get("value"), "page": r.get("page"),
                      "tier": r.get("tier"), "status": r.get("status")}
                     for r in filled],
            "skipped": [{"param": s.get("param"), "reason": s.get("reason")}
                        for s in skipped],
        }
        if extra:
            rec.update(extra)

        line = json.dumps(rec, ensure_ascii=False)
        _append_line(line)
        return rec
    except Exception as e:
        # 落盘失败不能拖垮主流程，只提示
        print("[record] 写日志失败：%s: %s" % (type(e).__name__, e))
        return None


def _append_line(line):
    with _lock:
        _ensure_dir()
        _rotate_if_needed()
        with io.open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def _ensure_dir():
    d = os.path.dirname(LOG_PATH)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def _rotate_if_needed():
    """超过上限就把当前文件改名为 records.jsonl.1，重新开始。"""
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > MAX_BYTES:
            bak = LOG_PATH + ".1"
            if os.path.exists(bak):
                os.remove(bak)
            os.replace(LOG_PATH, bak)
    except Exception:
        pass


def read_all(limit=None):
    """读回全部记录（新的在前）。"""
    if not os.path.exists(LOG_PATH):
        return []
    out = []
    try:
        with io.open(LOG_PATH, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    out.append(json.loads(ln))
                except Exception:
                    continue
    except Exception:
        return []
    out.reverse()
    return out[:limit] if limit else out


def stats():
    """给界面/命令行看的小结。"""
    recs = read_all()
    if not recs:
        return {"count": 0, "path": LOG_PATH}
    return {
        "count": len(recs),
        "path": LOG_PATH,
        "first": recs[-1].get("ts"),
        "last": recs[0].get("ts"),
        "files": len({r.get("file") for r in recs if r.get("file")}),
        "equipment": len({(r.get("equipment") or {}).get("tag")
                          for r in recs if r.get("equipment")}),
    }
