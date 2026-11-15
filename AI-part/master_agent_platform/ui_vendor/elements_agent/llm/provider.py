# -*- coding: utf-8 -*-
"""LLM 适配：默认 DeepSeek（OpenAI 兼容）；可选 Ollama 作 fallback。"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional

try:
    from elements_agent.local_config import apply_secrets_to_environ

    apply_secrets_to_environ()
except Exception:
    pass


def _ollama_base() -> str:
    return (os.environ.get("ELEMENT_AGENT_OLLAMA_BASE") or "http://127.0.0.1:11434").rstrip("/")


def _ollama_model() -> str:
    return os.environ.get("ELEMENT_AGENT_OLLAMA_MODEL") or "qwen2.5:3b"


def _openai_compat_base() -> str:
    """DeepSeek / 其它 OpenAI 兼容 API。默认 DeepSeek 官方地址。"""
    return (
        os.environ.get("ELEMENT_AGENT_LLM_BASE")
        or os.environ.get("DEEPSEEK_API_BASE")
        or "https://api.deepseek.com"
    ).rstrip("/")


def _openai_compat_key() -> str:
    return (
        os.environ.get("ELEMENT_AGENT_LLM_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
        or ""
    )


def _openai_compat_model() -> str:
    """默认 deepseek-flash（DeepSeek-V4.1-Flash）。

    也可设 ELEMENT_AGENT_LLM_MODEL / DEEPSEEK_MODEL 为 deepseek-v4-pro 等。
    旧名 deepseek-chat 已退役，勿再作默认。
    """
    return (
        os.environ.get("ELEMENT_AGENT_LLM_MODEL")
        or os.environ.get("DEEPSEEK_MODEL")
        or "deepseek-flash"
    )


def llm_available() -> bool:
    if _openai_compat_key():
        return True
    try:
        req = urllib.request.Request(
            f"{_ollama_base()}/api/tags",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def active_backend() -> str:
    if _openai_compat_key():
        return f"deepseek:{_openai_compat_model()}"
    return f"ollama:{_ollama_model()}"


def chat_completion(system: str, user: str, timeout: float = 90.0) -> Optional[str]:
    """返回助手文本；失败返回 None（调用方应 fallback 规则解析）。"""
    # 主路径：DeepSeek（有 Key 即优先）
    if _openai_compat_key():
        text = _chat_openai_compat(system, user, timeout=timeout)
        if text is not None:
            return text
    # Fallback：本地 Ollama
    return _chat_ollama(system, user, timeout=timeout)


def _chat_ollama(system: str, user: str, timeout: float = 60.0) -> Optional[str]:
    url = f"{_ollama_base()}/api/chat"
    payload = {
        "model": _ollama_model(),
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {"temperature": 0.1},
    }
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        msg = (body.get("message") or {}).get("content")
        return (msg or "").strip() or None
    except Exception as e:
        print(f"[LLM] Ollama 调用失败: {e}")
        return None


def _chat_openai_compat(system: str, user: str, timeout: float = 90.0) -> Optional[str]:
    url = f"{_openai_compat_base()}/chat/completions"
    payload = {
        "model": _openai_compat_model(),
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {_openai_compat_key()}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        choices = body.get("choices") or []
        if not choices:
            return None
        msg = ((choices[0].get("message") or {}).get("content") or "").strip()
        return msg or None
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="ignore")[:300]
        except Exception:
            pass
        print(f"[LLM] DeepSeek/OpenAI 兼容 API HTTP 错误: {e} {err_body}")
        return None
    except Exception as e:
        print(f"[LLM] DeepSeek/OpenAI 兼容 API 调用失败: {e}")
        return None
