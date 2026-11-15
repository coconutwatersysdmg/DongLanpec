# -*- coding: utf-8 -*-
"""
抽取结果落盘（旁路日志）

设计原则：**只追加，不参与业务**
- 每次解析完成后追加一行 JSON 到 output/records.jsonl
- 写日志失败绝不影响主流程（抛出的异常在这里全部吞掉并打警告）
- 界面仍读内存里的 _last_result，本模块不改变任何显示逻辑

为什么用 JSONL（每行一个 JSON）而不是一个大 JSON 数组：
  - 追加写不用读整个文件，几十万条也不卡
  - 某一行写坏了只损失那一行，不会让整个文件变成非法 JSON
  - 用 pandas / Excel / grep 都能直接读
"""
import io
import json
import os
import threading
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
LOG_PATH = os.path.join(OUTPUT_DIR, "records.jsonl")

# 单文件上限，超过就滚动一份备份，避免无限增长
MAX_BYTES = 20 * 1024 * 1024      # 20 MB

_lock = threading.Lock()          # 多线程/多次快速点击时防交叉写


def _ensure_dir():
    if not os.path.isdir(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)


def record(result, file_info=None, raw_input=None, extra=None):
    """
    追加一条抽取记录。

    result:    agent_core.parse() 返回的 dict（含 data/missing/source/note/errors/warnings）
    file_info: 上传文件时传 {"name","kind","chars","pages"}，对话输入传 None
    raw_input: 送给模型的原文（文件场景是裁剪后的片段），默认不存全文只存长度
    extra:     预留，可放任何自定义字段

    返回写入的记录 dict；失败返回 None（不抛异常）。
    """
    try:
        res = result or {}
        data = res.get("data") or {}
        errs = res.get("errors") or []
        warns = res.get("warnings") or []

        rec = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "input_type": "file" if file_info else "text",
            "file": (file_info or {}).get("name"),
            "file_kind": (file_info or {}).get("kind"),
            "file_chars": (file_info or {}).get("chars"),
            "input_chars": len(raw_input) if raw_input else 0,
            "source": res.get("source"),
            "note": res.get("note"),
            "n_fields": len([k for k, v in data.items() if str(v or "").strip()]),
            "data": data,
            "missing": res.get("missing") or [],
            "n_errors": len(errs),
            "errors": errs,
            "n_warnings": len(warns),
            "warnings": warns,
        }
        if extra:
            rec.update(extra)

        line = json.dumps(rec, ensure_ascii=False)
        _append_line(line, rec)
        return rec
    except Exception as e:
        # 落盘失败不能拖垮主流程，只提示
        print("[record] 写日志失败：%s: %s" % (type(e).__name__, e))
        return None


def _append_line(line, rec):
    with _lock:
        _ensure_dir()
        _rotate_if_needed()
        with io.open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")


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
    """
    读回全部记录（新的在前）。供调试/将来做"历史记录"界面用。
    limit: 只取最近 N 条。
    """
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
        "avg_fields": round(sum(r.get("n_fields", 0) for r in recs) / len(recs), 1),
        "files": len({r.get("file") for r in recs if r.get("file")}),
    }
