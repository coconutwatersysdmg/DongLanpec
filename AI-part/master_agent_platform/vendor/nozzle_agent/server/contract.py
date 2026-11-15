# -*- coding: utf-8 -*-
"""
接口契约：版本号、错误码、字段字典。

为什么单独一个文件：这套东西要交给别人对接，文档和代码必须**同一个事实来源**。
`/v1/schema` 和 OpenAPI 描述都从这里生成，改一处两边同步，不会出现
"文档写 422、代码返 400" 这种事。

改字段语义 -> 升 `agent.export.SCHEMA`；改请求/响应外壳 -> 升 `API_VERSION`。
"""
from __future__ import annotations

from typing import Any, Dict, List

from agent import export as exporter

SERVICE = "dlp-nozzle-agent"
API_VERSION = "1.0"
AGENT_VERSION = "0.6.0"

# 与 agent/export.py 的 SCHEMA 保持一致：接口外壳可以变，载荷结构由它管
SCHEMA = exporter.SCHEMA
# 取值口径：文档里反复要引用这句话，跟着 export 走，别各写一版
VALUE_NOTE = exporter.VALUE_NOTE

# ------------------------------------------------------------------ 错误码
# code -> (HTTP 状态, 一句话, 对方该怎么办)
# 约定：code 是稳定的机器可读值，message 是给人看的，hint 是可选的下一步。
ERRORS: Dict[str, tuple] = {
    "BAD_REQUEST":       (400, "请求格式不对",
                          "JSON 体需为合法 JSON，multipart 需带 file 字段"),
    "UNAUTHORIZED":      (401, "缺少或错误的访问令牌",
                          "请求头加 Authorization: Bearer <token>"),
    "NOT_FOUND":         (404, "接口不存在",
                          "GET /v1/schema 可以列出全部可用接口"),
    "METHOD_NOT_ALLOWED": (405, "该路径不支持这个方法", "看接口文档里的 Method"),
    "FILE_TOO_LARGE":    (413, "文件超过大小上限",
                          "压缩后重传，或让服务端调大 --max-file-mb"),
    "UNSUPPORTED_TYPE":  (415, "文件类型不支持",
                          "目前只接受 PDF（.pdf）；扫描件需先做 OCR"),
    "NO_TABLE":          (422, "没找到管口表",
                          "确认这份 PDF 里有「管口说明/接管表/Nozzle schedule」；"
                          "一份文件装着多台设备时用 page 指定页码"),
    "PARSE_FAILED":      (422, "文件能打开，但表读不出来",
                          "常见于扫描件、加密 PDF、表头被拆成两层文字"),
    "ENGINE_UNAVAILABLE": (503, "解析引擎不可用",
                           "服务端缺依赖，执行 pip install -r requirements.txt"),
    "BUSY":              (429, "服务繁忙", "稍后重试；或调大 --workers"),
    "TIMEOUT":           (504, "处理超时", "换页数少的文件，或只传管口表那几页"),
    "INTERNAL":          (500, "服务内部错误", "带上 request_id 找开发看日志"),
}


def err(code: str, message: str = "", hint: str = "") -> Dict[str, Any]:
    """组装错误对象；没给 message/hint 就用契约里的默认描述。"""
    status, default_msg, default_hint = ERRORS.get(code, ERRORS["INTERNAL"])
    return {
        "code": code,
        "message": message or default_msg,
        "hint": hint or default_hint,
        "status": status,
    }


# ------------------------------------------------------------------ 字段字典
# key -> (中文名, 类型, 说明, 示例)
FIELD_DOC: Dict[str, tuple] = {
    "index": ("序号", "int",
              "本次结果里的行号，从 1 起。与图纸编号 code 无关，别混用", 1),
    "code": ("序号", "string",
             "图纸上的管口编号原文，可能带前缀（1、L1、N2）", "L1"),
    "name": ("名称", "string", "名称单元格原文，中英混排时原样保留", "管程入口 Tube inlet"),
    "name_cn": ("中文名", "string", "从 name 拆出的中文部分，拆不出来时为原文", "管程入口"),
    "name_en": ("英文名", "string", "从 name 拆出的英文部分，没有则为空串", "Tube inlet"),
    "pressure": ("公称压力", "string",
                 "原文照抄，未换算 Class / PN。可能是 \"2.5\" 或 \"PN16\"", "2.5"),
    "dn": ("公称直径", "string", "原文照抄，可能带 DN 或缺省单位", "DN300"),
    "pipe_class": ("接管等级", "string",
                   "原文照抄。项目元件库里暂无对应字段，进表前要人工映射", "A"),
    "flange_standard": ("法兰标准", "string",
                        "原文照抄，可能缺年份", "SH/T 3406-2022"),
    "flange_face": ("法兰密封面型式", "string", "原文照抄，通常是 RF / MFM / RJ", "RF"),
    "outside_height": ("开口外伸高度", "string",
                       "原文照抄，单位按图纸标注（多为 mm），未归一", "150"),
    "azimuth_deg": ("周向方位", "float|null",
                    "端视图上读出的方位角：正上方为 0°，顺时针为正。"
                    "null = 图上没标或程序没认出来，**不要当成 0°**", 180.0),
}

# 请求参数说明（给 /v1/schema 和文档用）
PARAMS_DOC: List[Dict[str, Any]] = [
    {
        "name": "file",
        "in": "multipart",
        "type": "file",
        "required": True,
        "desc": "数据表 PDF。字段名固定为 file；支持一次传多个（走 batch 语义）",
    },
    {
        "name": "path",
        "in": "json",
        "type": "string",
        "required": False,
        "desc": "服务端本机路径。默认关闭，需启动时加 --allow-local-path，"
                "且只能读 --allow-root 目录下的文件",
    },
    {
        "name": "page",
        "in": "query",
        "type": "int",
        "required": False,
        "desc": "1 起的页码。一份 PDF 装着多台设备时用来指定是哪一张管口表；"
                "不传则自动找（先认标题再认表头结构）",
    },
    {
        "name": "with_azimuth",
        "in": "query",
        "type": "bool",
        "required": False,
        "default": True,
        "desc": "是否顺手识别端视图上的周向方位。关掉能快 30%~50%",
    },
    {
        "name": "persist",
        "in": "query",
        "type": "bool",
        "required": False,
        "default": False,
        "desc": "是否在服务端 output/ 下落一份 JSON。接口默认不落盘，内容直接返回",
    },
]


def field_dictionary() -> List[Dict[str, Any]]:
    """字段字典，按 JSON 里的键顺序输出（nozzles[i] 的结构）。"""
    order = ["index"] + [k for _, k in exporter.FIELD_KEYS] + ["azimuth_deg"]
    # name_cn / name_en 紧跟在 name 后面，和实际 JSON 顺序一致
    order.insert(order.index("name") + 1, "name_en")
    order.insert(order.index("name") + 1, "name_cn")

    out: List[Dict[str, Any]] = []
    for key in order:
        zh, typ, desc, example = FIELD_DOC[key]
        out.append({
            "key": key,
            "label": zh,
            "type": typ,
            "desc": desc,
            "example": example,
        })
    return out


def schema_doc() -> Dict[str, Any]:
    """GET /v1/schema 的返回体：字段、参数、错误码、端点一览。"""
    return {
        "service": SERVICE,
        "api_version": API_VERSION,
        "agent_version": AGENT_VERSION,
        "payload_schema": SCHEMA,
        "field_note": exporter.VALUE_NOTE,
        "endpoints": [
            {"method": "GET", "path": "/health", "desc": "健康检查与依赖状态"},
            {"method": "GET", "path": "/v1/schema", "desc": "本文件：字段字典与错误码"},
            {"method": "POST", "path": "/v1/nozzles/parse",
             "desc": "解析一份数据表，返回管口清单"},
            {"method": "POST", "path": "/v1/nozzles/parse-batch",
             "desc": "一次解析多份，单份失败不影响其余"},
            {"method": "POST", "path": "/v1/azimuth",
             "desc": "只做端视图方位识别，不读表"},
            {"method": "GET", "path": "/openapi.json", "desc": "OpenAPI 3.0 描述"},
            {"method": "GET", "path": "/docs", "desc": "可直接点着调用的页面"},
        ],
        "fields": field_dictionary(),
        "params": PARAMS_DOC,
        "error_codes": [
            {"code": code, "status": st, "message": msg, "hint": hint}
            for code, (st, msg, hint) in ERRORS.items()
        ],
    }
