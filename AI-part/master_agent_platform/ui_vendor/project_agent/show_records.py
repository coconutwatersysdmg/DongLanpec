# -*- coding: utf-8 -*-
"""
查看 Agent 助手的抽取记录

用法：
  python show_records.py              最近 10 条，摘要形式
  python show_records.py -n 50        最近 50 条
  python show_records.py -v           显示每个字段的完整值
  python show_records.py --stats      只看统计
  python show_records.py --csv        导出为 CSV（字段名作列）

记录文件：agent_assistant/output/records.jsonl（每行一个 JSON，已被 .gitignore 排除）
"""
import csv
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import record_store
import schema


def main():
    args = sys.argv[1:]
    n = 10
    verbose = "-v" in args or "--verbose" in args
    if "-n" in args:
        try:
            n = int(args[args.index("-n") + 1])
        except (IndexError, ValueError):
            pass

    if "--stats" in args:
        s = record_store.stats()
        if s["count"] == 0:
            print("还没有任何记录。跑一次 Agent 助手就会自动生成。")
            return
        print("记录条数：%d" % s["count"])
        print("涉及文件：%d 个" % s["files"])
        print("时间范围：%s ~ %s" % (s["first"], s["last"]))
        print("平均字段数：%s" % s["avg_fields"])
        print("文件位置：%s" % s["path"])
        return

    recs = record_store.read_all(limit=None if "--csv" in args else n)
    if not recs:
        print("还没有任何记录。跑一次 Agent 助手就会自动生成。")
        print("文件位置：%s" % record_store.LOG_PATH)
        return

    if "--csv" in args:
        _export_csv(recs)
        return

    print("共 %d 条记录（显示最近 %d 条），文件：%s\n"
          % (record_store.stats()["count"], len(recs), record_store.LOG_PATH))
    for i, r in enumerate(recs, 1):
        tag = "文件" if r.get("input_type") == "file" else "对话"
        name = r.get("file") or "（手动输入）"
        print("%2d. [%s] %s  %s" % (i, r.get("ts"), tag, name))
        print("    来源=%s  字段=%d  缺失=%d  错误=%d  警告=%d"
              % (r.get("source"), r.get("n_fields"),
                 len(r.get("missing") or []), r.get("n_errors", 0), r.get("n_warnings", 0)))
        data = r.get("data") or {}
        if verbose:
            for k in [f["key"] for f in schema.ALL_FIELDS]:
                v = (data.get(k) or "").strip()
                if v:
                    print("      %-6s %s" % (k, v))
        else:
            brief = "  ".join("%s=%s" % (k, v) for k, v in list(data.items())[:4])
            if len(data) > 4:
                brief += "  …"
            print("      %s" % (brief or "（无字段）"))
        if r.get("errors"):
            for e in r["errors"][:3]:
                print("      ✗ %s：%s" % (e.get("field"), e.get("reason")))
        print()


def _export_csv(recs):
    out = os.path.join(record_store.OUTPUT_DIR, "records.csv")
    keys = [f["key"] for f in schema.ALL_FIELDS]
    header = ["时间", "来源类型", "文件名", "解析来源", "字段数"] + keys + ["错误数", "缺失字段"]
    with io.open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in reversed(recs):          # CSV 按时间正序更自然
            data = r.get("data") or {}
            w.writerow(
                [r.get("ts"), r.get("input_type"), r.get("file") or "",
                 r.get("source"), r.get("n_fields", 0)]
                + [(data.get(k) or "") for k in keys]
                + [r.get("n_errors", 0), "、".join(r.get("missing") or [])]
            )
    print("已导出 %d 条到：%s" % (len(recs), out))


if __name__ == "__main__":
    main()
