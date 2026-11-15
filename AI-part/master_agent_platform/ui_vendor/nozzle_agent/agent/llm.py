# -*- coding: utf-8 -*-
"""
可选的大模型解析（OpenAI 兼容协议，全部走免费模型）。

默认关闭：不配置 API Key 时，Agent 使用本地规则引擎，离线可跑、结果稳定。
配置后：大模型只负责"把一句话拆成字段"，拆出来的每个字段仍要过校验器。

免费模型参考（按推荐顺序）：
1. DeepSeek              https://platform.deepseek.com    base_url: https://api.deepseek.com/v1
2. 智谱 GLM-4-Flash       https://open.bigmodel.cn        base_url: https://open.bigmodel.cn/api/paas/v4
3. 硅基流动 SiliconFlow    https://cloud.siliconflow.cn    base_url: https://api.siliconflow.cn/v1
4. 本地 Ollama（零成本）   base_url: http://localhost:11434/v1   model: qwen2.5:3b
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from . import spec

PRESETS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "note": "DeepSeek，便宜且中文强，支持强制 JSON 输出",
        "json_mode": True,
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "note": "智谱 GLM-4-Flash，注册后免费额度",
    },
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "note": "硅基流动，部分模型免费",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5:3b",
        "note": "本地 Ollama，完全离线",
    },
}

from . import spec  # noqa: E402


def _build_system_prompt() -> str:
    """取值清单直接取自元件库，避免提示词与项目真实取值脱节。"""
    pn = "、".join("%g" % float(x) for x in spec.PN_SERIES)
    cl = "、".join("%g" % float(x) for x in spec.CLASS_SERIES)
    return f"""你是压力容器管口参数抽取器。把用户的一句话转成 JSON，只输出 JSON，不要解释。

字段与取值范围（**必须使用下面列出的取值，尤其是代号，不要翻译成中文**）：
- action: add / update / delete / query / check
- 管口代号: 形如 N1，可选
- 公称尺寸: 整数 DN 值，如 50；NPS 时写字符串如 "2"
- 尺寸单位: DN 或 NPS
- 压力等级类型: PN 或 Class
- 压力等级: PN 体系取 {pn}；Class 体系取 {cl}
- 法兰标准: {' / '.join(spec.FLANGE_STANDARDS)}
- 法兰型式（存代号）: {' / '.join(spec.FLANGE_TYPES)}
- 密封面型式（存代号）: {' / '.join(spec.SEALING_FACES)}
- 焊端规格: {' / '.join(spec.SCH_VALUES)}（不带 Sch 前缀，Sch40 写成 40）
- 焊端规格单位: Sch 或 mm
- 管口功能（这是"管程入口"这类值，不是管口用途）: {' / '.join(spec.FUNCTION_VALUES[:12])}
- 管口用途: 自由文本，多数情况留空不输出
- 管口所属元件: {' / '.join(spec.ELEMENT_VALUES)}
- 周向方位(°): 0~360
- 外伸高度 / 轴向夹角 / 偏心距 / 轴向定位距离: 数字，单位 mm 或 度

规则：
1. 用户没提到的字段一律不要输出，不要猜。
2. 用户写了非法值（如 DN55），原样输出，不要自行纠正——后续由校验器报错。
3. 用户说"带颈对焊/突面/凹凸面"等中文时，转成对应代号（WN / RF / MF）。
4. 只输出一个 JSON 对象。"""


SYSTEM_PROMPT = _build_system_prompt()

ALLOWED_KEYS = {
    "action", "管口代号", "公称尺寸", "尺寸单位", "压力等级类型", "压力等级",
    "法兰标准", "法兰型式", "密封面型式", "焊端规格", "焊端规格单位",
    "管口功能", "管口用途", "管口所属元件", "轴向定位基准", "轴向定位距离",
    "轴向夹角", "周向方位(°)", "偏心距", "外伸高度", "内伸高度", "target_code",
}


class LLMExtractor:
    def __init__(self, config_path: Optional[str] = None):
        self.cfg: Dict[str, Any] = {}
        self.error: str = ""          # 配置层错误（读文件失败等）
        self.last_error: str = ""     # 最近一次调用错误，成功调用后清空
        cfg_path = config_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json"
        )
        try:
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    self.cfg = json.load(f) or {}
        except Exception as exc:  # 配置文件坏了就退回规则引擎
            self.error = f"读取 config.json 失败：{exc}"
            self.cfg = {}

        preset = PRESETS.get(str(self.cfg.get("preset", "")).lower())
        if preset:
            self.cfg.setdefault("base_url", preset["base_url"])
            self.cfg.setdefault("model", preset["model"])
            self.cfg.setdefault("json_mode", preset.get("json_mode", False))

    # ------------------------------------------------------------------ 状态
    def available(self) -> bool:
        if not self.cfg.get("enabled"):
            return False
        base = str(self.cfg.get("base_url") or "")
        key = str(self.cfg.get("api_key") or "")
        if not base:
            return False
        # 本地 Ollama 不需要 Key
        if "localhost" in base or "127.0.0.1" in base:
            return bool(self.cfg.get("model"))
        return bool(key)

    def label(self) -> str:
        nice = {"deepseek": "DeepSeek", "zhipu": "智谱 GLM",
                "siliconflow": "硅基流动", "ollama": "Ollama"}
        if self.available():
            prefix = nice.get(str(self.cfg.get("preset", "")).lower(), "大模型")
            tail = "（上次调用失败，已回退）" if self.last_error else ""
            return f"{prefix} · {self.cfg.get('model')}{tail}"
        if self.cfg.get("enabled") and self.error:
            return f"规则引擎（{self.error}）"
        return "本地规则引擎"

    # ------------------------------------------------------------------ 调用
    def extract(self, text: str) -> Dict[str, Any]:
        if not self.available():
            return {}
        url = str(self.cfg["base_url"]).rstrip("/") + "/chat/completions"
        payload = {
            "model": self.cfg.get("model"),
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        }
        # DeepSeek / 新版 OpenAI 兼容服务支持强制 JSON 输出，能省掉"模型加了句客套话"的解析失败
        if self.cfg.get("json_mode"):
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.cfg.get("api_key"):
            headers["Authorization"] = f"Bearer {self.cfg['api_key']}"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=int(self.cfg.get("timeout", 20))) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "ignore")[:200]
            except Exception:
                pass
            self.last_error = f"HTTP {exc.code} {body}".strip()
            self.error = f"大模型调用失败，已回退规则引擎：{self.last_error}"
            return {}
        except (urllib.error.URLError, KeyError, json.JSONDecodeError, TimeoutError) as exc:
            self.last_error = str(exc)
            self.error = f"大模型调用失败，已回退规则引擎：{exc}"
            return {}

        self.last_error = ""
        return self._sanitize(content)

    def _sanitize(self, content: str) -> Dict[str, Any]:
        """剥掉代码围栏，只保留合法字段，数字字段强制转型。防止模型自由发挥。"""
        text = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.M).strip()
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            self.last_error = "返回内容里没有 JSON"
            return {}
        try:
            raw = json.loads(m.group(0))
        except json.JSONDecodeError:
            self.last_error = "返回的不是合法 JSON"
            self.error = "大模型返回的不是合法 JSON，已忽略"
            return {}
        out: Dict[str, Any] = {}
        for k, v in raw.items():
            if k not in ALLOWED_KEYS or v in (None, "", "null"):
                continue
            if k in ("公称尺寸", "压力等级", "轴向定位距离", "轴向夹角",
                     "周向方位(°)", "偏心距", "外伸高度", "内伸高度"):
                try:
                    fv = float(v)
                    v = int(fv) if fv == int(fv) else fv
                except (TypeError, ValueError):
                    v = str(v)
            elif k == "焊端规格":
                v = str(v)
            out[k] = v
        if "法兰型式" in out:
            out["法兰型式"] = spec.FLANGE_TYPE_ALIASES.get(str(out["法兰型式"]), out["法兰型式"])
        if "密封面型式" in out:
            out["密封面型式"] = spec.SEALING_FACE_ALIASES.get(str(out["密封面型式"]), out["密封面型式"])
        return out
