# -*- coding: utf-8 -*-
"""
条件输入 Agent 对外接口（无界面版）

给其他模块 / 师兄的调度层调用的统一入口。与 app.py（PyQt5 界面）走
同一条抽取管道，但：
  - 不 import 任何 PyQt5，纯命令行 / 服务端可用
  - 不写业务库（只在本机 output/records.jsonl 留可选运行记录）
  - 返回值保证 JSON 可序列化，可直接 HTTP 返回或落盘

三个函数：
  list_products(product_dir)            扫"已拆分产品小 PDF"目录 → 产品清单
  run_condition_agent(pdf_path, ...)    单本产品 PDF → 五张表数据（核心接口）
  summarize_result(res)                 结果 dict → 一段人话摘要（调试/日志用）

典型用法：
    import api
    res = api.run_condition_agent(r"D:/split_demo/01_OST-E-1901_P3-6.pdf")
    if res["status"] == "ok":
        for r in res["design_rows"]:
            print(r["param"], r.get("side"), r.get("value"))
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import infra.equipment_split as equipment_split
import core.extractor as extractor
import infra.file_reader as file_reader
import core.ndt_paint as ndt_paint
import core.param_spec as ps
import infra.product_scan as product_scan
import core.proposal as proposal
import core.std_table as std_table


# ------------------------------------------------------------------
# 产品清单
# ------------------------------------------------------------------

def list_products(product_dir=None):
    """
    扫描「已拆分产品小 PDF」目录，返回产品清单。

    参数：
        product_dir  目录路径；缺省用 config.PRODUCT_DIR（可用环境变量
                     CONDITION_PRODUCT_DIR 覆盖）

    返回（JSON 可序列化）：
        [{"index": 1, "tag": "OST-E-1901", "name": "xxx换热器",
          "pdf_path": "...", "page_range": "P3-6", "file": "01_xxx.pdf"}, ...]
    """
    d = product_dir or config.PRODUCT_DIR
    return product_scan.scan_products(d)


# ------------------------------------------------------------------
# 核心接口：单本产品 PDF → 五张表数据
# ------------------------------------------------------------------

def run_condition_agent(pdf_path, equipment_tag=None, save_record=False):
    """
    处理一本产品小 PDF，返回条件输入五张表（设计/通用/产品标准/检测/涂漆）。

    参数：
        pdf_path       产品小 PDF 的路径（项目管理侧拆分产物）
        equipment_tag  位号。单本 PDF 通常只有一台设备，不用传；
                       一本 PDF 含多台时用它挑要抽的那台。
        save_record    True 时在本机 output/records.jsonl 追加一条运行记录
                       （默认 False，不产生任何文件写入）

    返回（JSON 可序列化 dict）：
        status        "ok" | "error"
        error         出错时的说明（status=error 时才有）
        file          {"name","kind","pages","chars","path"}
        product       {"tag","name","spec","page_range"}（能识别到才有）
        form          设备类型："换热器" | "容器" | None
        pform         型式代号："BKU"/"BEM"/"NEN"... | None
        engine        "llm"（配了 API Key）| "rules"（规则解析降级）
        design_rows   设计数据行列表，字段见 INTERFACE.md
        std_rows      产品标准行
        gen_rows      通用数据行
        ndt_rows      检测数据行
        paint_rows    涂漆数据行
        notes         各表的处理提示 {"defaults","std","gen","ndt","paint"}
        counts        统计 {"design","errors","need_confirm","manual"}
        skipped       拦掉的派生字段（程序算，不填）
    """
    fi = {"name": "", "kind": "", "chars": 0, "pages": 0, "path": pdf_path}
    try:
        pages, meta = file_reader.extract(pdf_path)
        if not meta.get("ok") or not pages:
            return _err_result("PDF 读取失败：%s" % meta.get("error", "未知原因"),
                               fi)
        fi = {"name": meta.get("name", ""), "kind": meta.get("kind", ""),
              "chars": meta.get("chars", 0), "pages": meta.get("pages", 0),
              "path": pdf_path}
        blocks = equipment_split.split_equipment(pages)
    except Exception as e:
        return _err_result("PDF 读取异常：%s: %s" % (type(e).__name__, e), fi)

    # 单本小 PDF 一般一台设备；多台时按位号挑
    equipment = equipment_tag
    if len(blocks) > 1 and not equipment:
        equipment = blocks[0].get("tag") or None

    try:
        res = extractor.extract(
            pages, file_name=fi["name"], equipment=equipment,
            all_blocks=blocks or None)
        rows = proposal.build(
            res.get("items") or [],
            source_file=fi["name"], source_path=fi["path"],
            source_type=fi["kind"], skipped=res.get("skipped"))

        eq_spec = (res.get("equipment") or {}).get("spec") or ""
        form = std_table.detect_form(pages)
        pform_code = std_table.product_form(eq_spec)

        # 设计数据白名单过滤（模板外参数归位通用数据）+ 模板默认值打底
        rows, gen_extra = std_table.split_design_rows(
            rows, form=form, pform=pform_code)
        rows, note_def = std_table.merge_design_defaults(
            rows, pform=pform_code, form=form, file_info=fi)

        gen_rows, gen_note = std_table.build_general_rows(pages, form)
        gen_rows, n_move = std_table.absorb_gen_extras(gen_rows, gen_extra)
        if n_move:
            gen_note = (gen_note + "；%d 项自设计数据抽取结果归位" % n_move
                        ).lstrip("；")
        std_rows, std_note = std_table.build_rows(pages, form)
        ndt_rows, ndt_note = ndt_paint.build_detection_rows(
            pages, form=form, pform=pform_code)
        paint_rows, paint_note = ndt_paint.build_paint_rows(
            pages, form=form, pform=pform_code)

        eq = res.get("equipment") or {}
        out = {
            "status": "ok",
            "error": "",
            "file": fi,
            "product": {
                "tag": eq.get("tag") or "",
                "name": eq.get("name") or "",
                "spec": eq_spec,
                "page_range": eq.get("page_range") or "",
            },
            "form": form,
            "pform": pform_code,
            "engine": "llm" if config.llm_enabled() else "rules",
            "design_rows": rows,
            "std_rows": std_rows,
            "gen_rows": gen_rows,
            "ndt_rows": ndt_rows,
            "paint_rows": paint_rows,
            "notes": {
                "defaults": note_def,
                "std": std_note,
                "gen": gen_note,
                "ndt": ndt_note,
                "paint": paint_note,
            },
            "counts": {
                "design": len(rows),
                "errors": sum(1 for r in rows if r.get("errors")),
                "need_confirm": sum(1 for r in rows
                                    if r.get("tier") == proposal.TIER_CONFIRM),
                "manual": sum(1 for r in rows
                              if r.get("tier") == proposal.TIER_MANUAL),
            },
            "skipped": res.get("skipped") or [],
        }
        out = _ensure_jsonable(out)
        if save_record:
            try:
                import infra.record_store as record_store
                record_store.record(res, file_info=fi)
            except Exception:
                pass
        return out
    except Exception as e:
        import traceback
        return _err_result("抽取异常：%s: %s" % (type(e).__name__, e), fi,
                           detail=traceback.format_exc())


def summarize_result(res):
    """
    结果 dict → 一段人话摘要（适合打日志 / 回给上层展示）。
    """
    if res.get("status") != "ok":
        return "条件输入抽取失败：%s" % res.get("error", "")
    p = res.get("product") or {}
    head = "设备 %s %s" % (p.get("tag") or "?", p.get("name") or "")
    c = res.get("counts") or {}
    lines = ["%s（%s）：设计数据 %d 项，其中 %d 需确认 / %d 待补充 / %d 校验错误"
             % (head, res.get("engine") or "?", c.get("design", 0),
                c.get("need_confirm", 0), c.get("manual", 0),
                c.get("errors", 0))]
    missing = proposal.missing_required(res.get("design_rows") or [])
    if missing:
        lines.append("必填项还缺：%s" % "、".join(missing))
    return "\n".join(lines)


# ------------------------------------------------------------------
# 内部工具
# ------------------------------------------------------------------

def _err_result(msg, fi, detail=""):
    r = {
        "status": "error",
        "error": msg,
        "file": fi,
        "product": {}, "form": None, "pform": None, "engine": "",
        "design_rows": [], "std_rows": [], "gen_rows": [],
        "ndt_rows": [], "paint_rows": [],
        "notes": {}, "counts": {}, "skipped": [],
    }
    if detail:
        r["traceback"] = detail
    return r


def _ensure_jsonable(obj):
    """递归兜底：任何 JSON 序列化不了的值转成 str，保证接口输出干净。"""
    import json
    try:
        json.dumps(obj, ensure_ascii=False)
        return obj
    except (TypeError, ValueError):
        pass
    if isinstance(obj, dict):
        return {str(k): _ensure_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_ensure_jsonable(v) for v in obj]
    return str(obj)
