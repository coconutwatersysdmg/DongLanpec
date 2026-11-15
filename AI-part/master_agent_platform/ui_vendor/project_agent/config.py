# -*- coding: utf-8 -*-
"""
助手配置（独立 demo，与主项目零耦合）

【支持两家供应商，按 Key 格式自动识别，换 Key 就换供应商】
  DeepSeek    Key 形如 sk-xxxxxxx        付费，deepseek-flash 单次约 4 厘钱
  智谱 GLM    Key 形如 xxxxx.xxxxx        有长期免费模型
未配置 Key 时自动降级为内置规则解析，保证 demo 永远能跑。

【Key 怎么配】三选一，优先级从高到低：
  1. 环境变量 LLM_API_KEY（也认 DEEPSEEK_API_KEY / ZHIPU_API_KEY）
  2. 本目录下 api_key.txt（一行，只放 Key；.gitignore 已排除）
  3. 直接改本文件常量（不推荐，容易误提交）

【想强制指定供应商】设环境变量 LLM_PROVIDER=deepseek 或 zhipu

【DeepSeek 注意】deepseek-chat / deepseek-reasoner 已于 2026-07-24 弃用，
              当前模型名是 deepseek-flash 和 deepseek-v4-pro。
              两个模型默认都开 thinking，抽取任务要显式关掉才省钱。
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------- 供应商配置 ----------
PROVIDERS = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-flash",              # DeepSeek-V4.1-Flash，快且便宜
        # 固定只用 flash（用户决定）。不挂 deepseek-v4-pro 做兜底，
        # 原因是 pro 贵约 4 倍，静默切过去会悄悄多花钱；
        # 真出现模型不可用时宁可报错 + 降级规则解析，成本可控。
        "fallbacks": [],
        "force_thinking": (),                    # 两个都能关思考
        "keys_url": "https://platform.deepseek.com/api_keys",
        "topup_url": "https://platform.deepseek.com/top_up",
        "key_hint": "sk- 开头",
    },
    "zhipu": {
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model": "glm-4-flash-250414",
        "fallbacks": ["glm-4.5-flash", "glm-4.7-flash", "glm-4-flash"],
        # glm-4.7 / glm-5.3 强制开思考，传 thinking=disabled 会报错
        "force_thinking": ("glm-4.7", "glm-5.3"),
        "keys_url": "https://open.bigmodel.cn/usercenter/apikeys",
        "topup_url": "https://open.bigmodel.cn/usercenter/apikeys",
        "key_hint": "id.secret 格式（含点号）",
    },
}

# 认这些环境变量里的 Key，前面的优先
ENV_KEY_NAMES = ("LLM_API_KEY", "DEEPSEEK_API_KEY",
                 "ZHIPU_API_KEY", "ZHIPUAI_API_KEY", "GLM_API_KEY")

LLM_TIMEOUT = 60

# 真实 Key 都远超这个长度。低于它基本是占位符（比如随手写的 "111"），
# 直接当"未配置"处理，避免用户看到莫名其妙的"Key 无效"。
KEY_MIN_LEN = 16


def _load_api_key():
    """按优先级读 Key：环境变量 → api_key.txt。"""
    for env_name in ENV_KEY_NAMES:
        v = (os.environ.get(env_name) or "").strip()
        if v:
            return v

    key_file = os.path.join(BASE_DIR, "api_key.txt")
    if os.path.exists(key_file):
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    return line
        except Exception:
            pass

    return ""


def _detect_provider(key):
    """
    按 Key 格式判断是哪家。

    DeepSeek 的 Key 是 sk- 开头；智谱的是 id.secret（一定含点号）。
    两种情况都不像时按 DeepSeek 处理——猜错了报错信息也更直白。
    """
    forced = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
    if forced in PROVIDERS:
        return forced

    k = (key or "").strip()
    if k.startswith("sk-"):
        return "deepseek"
    if "." in k:
        return "zhipu"
    return "deepseek"


# ---------- 当前生效的配置 ----------
LLM_API_KEY = _load_api_key()
LLM_PROVIDER = _detect_provider(LLM_API_KEY)
_P = PROVIDERS[LLM_PROVIDER]

LLM_LABEL = _P["label"]
LLM_BASE_URL = _P["base_url"]
LLM_MODEL = _P["model"]
LLM_MODEL_FALLBACKS = list(_P["fallbacks"])
LLM_FORCE_THINKING = tuple(_P["force_thinking"])
LLM_KEYS_URL = _P["keys_url"]        # 鉴权失败 → 去这里重新生成 Key
LLM_TOPUP_URL = _P["topup_url"]      # 余额不足 → 去这里充值
LLM_CONSOLE_URL = LLM_TOPUP_URL      # 兼容旧名
LLM_KEY_HINT = _P["key_hint"]

# 这个供应商不会被关思考的模型清单（agent_core 用它决定要不要传 thinking 参数）
LLM_MODEL_CANDIDATES = [LLM_MODEL] + [m for m in LLM_MODEL_FALLBACKS if m != LLM_MODEL]


# ---------- 兼容旧名字（实际指向当前生效的供应商） ----------
# 早期代码里到处写 ZHIPU_*，现在统一用 LLM_*；这里保留别名防止漏改。
ZHIPU_API_KEY = LLM_API_KEY
ZHIPU_BASE_URL = LLM_BASE_URL
ZHIPU_MODEL = LLM_MODEL
ZHIPU_MODEL_FALLBACKS = LLM_MODEL_FALLBACKS


def api_key_source():
    """返回 Key 的来源，给界面展示用。"""
    for env_name in ENV_KEY_NAMES:
        if (os.environ.get(env_name) or "").strip():
            if len(LLM_API_KEY) < KEY_MIN_LEN:
                return "环境变量 %s（内容过短，像是占位符）" % env_name
            return "环境变量 %s" % env_name
    if os.path.exists(os.path.join(BASE_DIR, "api_key.txt")):
        if not LLM_API_KEY:
            return "api_key.txt（内容为空）"
        if len(LLM_API_KEY) < KEY_MIN_LEN:
            return "api_key.txt（内容只有 %d 字符，像是占位符）" % len(LLM_API_KEY)
        return "api_key.txt"
    return "未配置"


# ---------- 数据库（只读，仅用于取合法取值做校验） ----------
DB = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "123456",
    "charset": "utf8mb4",
    "connect_timeout": 5,
}

OUT_DIR = os.path.join(BASE_DIR, "output")


def ensure_dirs():
    os.makedirs(OUT_DIR, exist_ok=True)


def llm_enabled():
    """Key 存在且长度合理，才算真的配好了。"""
    return bool(LLM_API_KEY) and len(LLM_API_KEY) >= KEY_MIN_LEN
