# -*- coding: utf-8 -*-
"""
把「用户拖进来的文件」变成结构化结果。

现在只认 PDF 的换热器数据表，做三件事：
1. 找到「管口说明」那张表并读出来（量已按数量展开成一行一个管口）；
2. 顺手统计几个**已知对不上项目取值体系**的点，作为提示返回；
3. 把结果存一份 JSON（`agent/export.py`），供下游程序直接消费。

仍然不做换算、不做映射、不落表——那是下一步的事。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import export as exporter
from .doc_reader import expand_rows, read_nozzle_table

SUPPORTED_SUFFIX = (".pdf",)


@dataclass
class DocResult:
    """一次文件读取的结果。失败也返回对象，由 ok 区分，方便界面统一处理。"""

    path: str = ""
    ok: bool = False
    page: Optional[int] = None          # PDF 物理页码（这份文件里第几页）
    sheet: Optional[int] = None         # 图纸页号（页脚「第8页 共46页」里的 8）
    sheet_total: Optional[int] = None   # 整份数据表共几页
    raw_count: int = 0
    rows: List[Dict[str, str]] = field(default_factory=list)
    error: str = ""
    # 机器可读的失败原因（NOT_FOUND_FILE / UNSUPPORTED_TYPE / NO_TABLE /
    # ENGINE_UNAVAILABLE / PARSE_FAILED）。HTTP 层据此映射状态码；
    # 界面不用它，直接显示 error 那句话。
    error_code: str = ""
    notes: List[str] = field(default_factory=list)

    # ---- 结构化输出（JSON）----
    json_path: str = ""          # 落盘位置；没落成功时为空
    json_text: str = ""          # 内容本身；界面直接拿去展示/复制
    json_error: str = ""         # 落盘失败的原因（内容仍然可用）

    # ---- 方位图（表格页下方那张端视图）----
    azimuth: Any = None          # agent.azimuth.AzimuthResult；没图 / 没装 opencv 时为 None
    azimuth_error: str = ""      # 没识别出的原因
    azimuth_json: Optional[Dict[str, Any]] = None   # 写进 JSON 的那一段（见 AzimuthResult.layout）

    # ---- 展示用 ----
    @property
    def name(self) -> str:
        return os.path.basename(self.path) if self.path else ""

    @property
    def ext(self) -> str:
        return os.path.splitext(self.path)[1].lower().lstrip(".") if self.path else ""

    def page_text(self) -> str:
        """给人看的页码：优先图纸页号，和物理页不同时两个都写。

        数据表常是「一份 46 页里只给了第 7~10 页」，所以物理第 2 页
        其实是原文件第 8 页。写清楚两个，人才不会翻错。
        """
        if self.sheet and self.page and self.sheet != self.page:
            return f"第 {self.sheet} 页（本文件第 {self.page} 页）"
        if self.sheet:
            return f"第 {self.sheet} 页"
        if self.page:
            return f"第 {self.page} 页"
        return ""

    def headline(self) -> str:
        if not self.ok:
            return f"没能读取 {self.name}"
        where = f"{self.page_text()}：" if self.page_text() else ""
        if self.raw_count and self.raw_count != len(self.rows):
            return (f"已读取《{self.name}》{where}"
                    f"原始 {self.raw_count} 行 → 展开 {len(self.rows)} 个管口")
        return f"已读取《{self.name}》{where}{len(self.rows)} 个管口"

    @property
    def json_size(self) -> int:
        """JSON 的字节数（界面显示"多大"用）。"""
        return len(self.json_text.encode("utf-8")) if self.json_text else 0


def collect_notes(rows: List[Dict[str, str]]) -> List[str]:
    """列出"值能读出来、但和项目取值体系对不上"的几处，只提示不改写。"""
    notes: List[str] = []
    if not rows:
        return notes

    levels = sorted({r.get("接管等级", "").strip() for r in rows} - {""})
    if levels:
        notes.append(f"「接管等级」{'、'.join(levels)} 在项目元件库里没有对应字段，先按原文挂着")

    stds = sorted({r.get("法兰标准", "").strip() for r in rows} - {""})
    # 年份在标准号里是「-2022」这种形式；不能用 \d{4} 找——
    # 「SH/T 3406」里的 3406 会被当成出版年，结果该报的漏了。
    loose = [s for s in stds if not re.search(r"[-—–]\s*\d{4}", s)]
    if loose:
        notes.append(f"法兰标准 {'、'.join(loose)} 未标年份，项目取值是带年份的（如 SH/T 3406-2022）")

    pressures = [r.get("公称压力", "") for r in rows]
    if any(re.search(r"\.\d", p) for p in pressures):
        sample = next(p for p in pressures if re.search(r"\.\d", p))
        notes.append(f"公称压力按原文保留（本例 {sample} MPa），未换算成 Class / PN")

    return notes


def read_doc(path: str, save_json: bool = True,
             out_dir: Optional[str] = None,
             with_azimuth: bool = True,
             page: Optional[int] = None) -> DocResult:
    """读一个文件，并把结果打包成 JSON。

    save_json=False 时不落盘（只把内容放进 res.json_text），自测/演示用。
    with_azimuth=True 时顺手识别表格页上的方位图；失败不影响主结果。
    page: 1 起的页码。一份 PDF 里装了好几台设备（各有各的管口表）时用来指定，
          不传就自动找。HTTP 接口把它透出来，界面上没用到。
    """
    res = DocResult(path=path)
    if not path or not os.path.isfile(path):
        res.error = "文件不存在，或路径不可访问"
        res.error_code = "NOT_FOUND_FILE"
        return res

    suffix = os.path.splitext(path)[1].lower()
    if suffix not in SUPPORTED_SUFFIX:
        res.error = f"暂不支持 {suffix or '该类型'} 文件，目前只能读 PDF 数据表"
        res.error_code = "UNSUPPORTED_TYPE"
        return res

    try:
        report: Dict[str, Any] = {}
        raw = read_nozzle_table(path, page=page, expand=False, report=report)
        if not raw:
            res.error = f"第 {report.get('page', '?')} 页找到了管口表，但没读出数据行"
            res.error_code = "PARSE_FAILED"
            return res

        res.page = report.get("page")
        res.sheet = report.get("sheet")
        res.sheet_total = report.get("sheet_total")
        res.raw_count = len(raw)
        # 原始行带「数量」；展开后按项目列顺序输出，数量列去掉
        res.rows = expand_rows(raw)
        res.ok = True
        res.notes = collect_notes(res.rows)
    except RuntimeError as exc:          # 没装 pdfplumber：把安装命令一起给出来
        res.error = str(exc).strip()
        res.error_code = "ENGINE_UNAVAILABLE"
        return res
    except ValueError as exc:            # 没找到表 / 认不出表头：原话给出来，别包一层"读取失败"
        res.error = str(exc)
        # 「找不到表」和「表坏了」对调用方是两件事：前者换页码/换文件能解决，
        # 后者只能人工介入。所以这里按原因再分一层，别都塞进一个码里。
        res.error_code = ("NO_TABLE"
                          if ("没找到管口表" in res.error or "没有文字层" in res.error)
                          else "PARSE_FAILED")
        return res
    except Exception as exc:             # 损坏、加密、格式异常
        res.error = f"读取失败：{exc}"
        res.error_code = "PARSE_FAILED"
        return res

    # 方位图要先算：它的结果要跟着 JSON 一起出去（每个管口一个 azimuth_deg）
    if with_azimuth:
        _attach_azimuth(res)
        res.azimuth_json = _azimuth_payload(res)

    # 结构化输出：内容先算出来（一定成功），落盘单独算（可能被占用）
    payload = exporter.build_from_result(res)
    res.json_text = exporter.dumps(payload)
    if save_json:
        try:
            res.json_path = exporter.save(payload, out_dir=out_dir)
        except PermissionError:
            res.json_error = "JSON 没能写入（文件正被其他程序占用），内容仍可复制"
        except OSError as exc:
            res.json_error = f"JSON 没能写入：{exc.strerror or exc}"

    if with_azimuth and res.azimuth_json is None:
        res.azimuth_json = _azimuth_payload(res)
    return res


def _azimuth_payload(res: DocResult) -> Dict[str, Any]:
    """没有方位图时也要在 JSON 里留一段，说明为什么没有，别让下游猜。"""
    az = res.azimuth
    if az is not None and getattr(az, "ok", False):
        return az.layout()
    return {
        "ok": False,
        "error": res.azimuth_error or "这份文件里没有管口方位图",
        "nozzles": [],
        "by_code": {},
        "needs_review": [],
        "notes": [],
    }


def _attach_azimuth(res: DocResult) -> None:
    """顺手识别方位图。任何异常都吞掉——它是附加信息，不能拖垮读表结果。"""
    try:
        from . import azimuth as az
    except ImportError:                  # 没装 opencv：明确说清，而不是默默没有
        res.azimuth_error = "没装 opencv，方位图识别不可用（pip install opencv-python-headless）"
        return
    try:
        # 把管口表所在页告诉它：一份 PDF 里常有好几张端视图，挑最近的这张才是同一台设备
        got = az.analyze(res.path, near=(res.page - 1) if res.page else None)
    except Exception as exc:
        res.azimuth_error = f"方位图识别失败：{exc}"
        return
    if got.ok:
        res.azimuth = got
    else:
        res.azimuth_error = got.error


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python -m agent.doc_import <文件路径>")
        raise SystemExit(2)
    r = read_doc(sys.argv[1])
    print(r.headline())
    for n in r.notes:
        print(" -", n)
    if r.ok:
        if r.json_path:
            print("JSON:", r.json_path)
        elif r.json_error:
            print("JSON:", r.json_error)
        print(r.json_text, end="")
    else:
        print("错误:", r.error)
