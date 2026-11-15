# -*- coding: utf-8 -*-
"""
Key 自检：验证当前供应商的 API Key 是否可用、模型是否可用。

用法（不需要开界面）：
    D:/Anaconda/envs/py39_clean/python.exe agent_assistant/check_key.py

它会告诉你：
  1. 当前识别到哪家供应商（DeepSeek / 智谱），Key 从哪里读到的
  2. Key 本身是否有效（鉴权 / 余额）
  3. 哪些模型能用、哪些不能用
  4. 用真实文件跑一遍，看抽取结果对不对
"""
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
import config


# 探测清单由 config 按供应商给出；再补几个已知的历史模型名做对照，
# 让用户能看出"哪些名字已经死了"，避免照抄旧教程。
_LEGACY = {
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "zhipu": ["glm-4.6v-flash"],
}
CANDIDATES = list(config.LLM_MODEL_CANDIDATES) + [
    m for m in _LEGACY.get(config.LLM_PROVIDER, []) if m not in config.LLM_MODEL_CANDIDATES
]

PROBE_TEXT = (
    "项目名称：渤中19-6滨州终端换热器，项目编号：OED2022-32，"
    "业主名称：中海油石化工程有限公司，所属部门：设备室，"
    "产品名称：提纯塔入口冷却器，设备位号：E-2107，"
    "产品类型：管壳式热交换器，产品型式：BEU，设计阶段：方案设计"
)

# 探测用提示词必须包含"全部字段清单"，否则模型只抽示例里提到的那一个，
# 会让人误以为模型能力差（早期版本就踩了这个坑）。
PROBE_SYSTEM = """你是压力容器设计软件的数据录入助手。从用户描述中提取字段。

可提取的字段（只能返回这些 key）：
项目级：项目名称、项目编号、业主名称、所属部门、工程总包方
产品级：产品名称、产品编号、设备位号、产品型号、产品类型、产品型式、设计阶段、设计版次

规则：
1. 只返回 JSON，格式：{"项目名称": "...", "产品类型": "...", ...}
2. 用户没提到的字段，不要出现在 JSON 里，不要编造。
3. 产品类型/产品型式/设计阶段 原样保留用户说的词，不要自动纠正。
"""

# 探测用的期望结果：用户文本里明确给出了这 6 个字段
PROBE_EXPECT = ["项目名称", "项目编号", "业主名称", "所属部门",
                "产品名称", "设备位号", "产品类型", "产品型式", "设计阶段"]


def mask(k):
    if not k:
        return "（空）"
    if len(k) <= 12:
        return k[:3] + "***"
    return k[:6] + "..." + k[-4:] + "（共 %d 字符）" % len(k)


def probe(model, key):
    """返回 (状态, 说明)"""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": PROBE_SYSTEM},
            {"role": "user", "content": PROBE_TEXT},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    if not any(model.lower().startswith(p) for p in config.LLM_FORCE_THINKING):
        payload["thinking"] = {"type": "disabled"}

    try:
        r = requests.post(
            config.LLM_BASE_URL,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=60)
    except Exception as e:
        return "网络错误", "%s: %s" % (type(e).__name__, e)

    if r.status_code == 401:
        return "Key无效", r.text[:160]
    if r.status_code == 402:
        return "余额不足", "请到 %s 充值" % config.LLM_TOPUP_URL
    if r.status_code == 429:
        return "限流", "并发受限，稍后重试"
    if r.status_code in (400, 404, 422):
        body = r.text[:200]
        low = body.lower()
        if any(k in low for k in ("模型", "model", "不存在", "not found",
                                  "无权限", "unsupported", "not exist")):
            return "模型不可用", body
        return "请求被拒", body
    if r.status_code in (500, 503):
        return "服务端异常", "HTTP %d，稍后重试" % r.status_code
    if r.status_code != 200:
        return "HTTP %d" % r.status_code, r.text[:160]

    try:
        msg = r.json()["choices"][0]["message"]
        content = (msg.get("content") or "").strip() or (msg.get("reasoning_content") or "").strip()
        obj = json.loads(content)
    except Exception as e:
        return "返回异常", "%s: %s" % (type(e).__name__, str(r.text)[:160])

    # 按"该抽出来的有没有抽出来"打分，而不是简单地数字段个数
    missing = [k for k in PROBE_EXPECT if not str(obj.get(k) or "").strip()]
    if missing:
        return "部分可用", "%d/%d 命中，漏了：%s" % (
            len(PROBE_EXPECT) - len(missing), len(PROBE_EXPECT), "、".join(missing))
    return "可用", "%d/%d 字段全部命中" % (len(PROBE_EXPECT), len(PROBE_EXPECT))


def main():
    print("=" * 68)
    print("%s API Key 自检" % config.LLM_LABEL)
    print("=" * 68)
    print("供应商  ：", config.LLM_PROVIDER, "（按 Key 格式自动识别）")
    print("Key 来源：", config.api_key_source())
    print("Key 值  ：", mask(config.LLM_API_KEY))
    print("接口地址：", config.LLM_BASE_URL)
    print("默认模型：", config.LLM_MODEL)
    print("备选模型：", " / ".join(config.LLM_MODEL_FALLBACKS) or "（无）")
    print()

    if not config.LLM_API_KEY:
        print("✗ 没有读到 Key。三种配置方式任选一种：")
        print("  1) 环境变量（当前窗口有效）：")
        print('       $env:LLM_API_KEY = "你的Key"')
        print("  2) 新建文件 agent_assistant/api_key.txt，只写一行 Key")
        print("  3) 改 config.py 里的常量（不推荐）")
        print()
        print("获取 Key： %s" % config.LLM_KEYS_URL)
        return 2

    if config.LLM_PROVIDER == "deepseek" and not config.LLM_API_KEY.startswith("sk-"):
        print("⚠ DeepSeek 的 Key 通常是 sk- 开头，确认是否复制完整。\n")
    if config.LLM_PROVIDER == "zhipu" and "." not in config.LLM_API_KEY:
        print("⚠ 智谱的 Key 通常是 id.secret 格式（含点号），确认是否复制完整。\n")

    print("-" * 68)
    print("逐个探测模型（每个最多等 60 秒）")
    print("-" * 68)
    usable = []
    balance_out = False
    for m in CANDIDATES:
        state, detail = probe(m, config.LLM_API_KEY)
        mark = "✓" if state == "可用" else ("△" if state == "部分可用" else "✗")
        print("%s %-24s %-10s %s" % (mark, m, state, detail))
        if state == "可用":
            usable.append(m)
        if state == "Key无效":
            print("\nKey 无效，后面的模型不用试了。请重新生成 Key。")
            break
        if state == "余额不足":
            balance_out = True
            print("\n账户余额不足，后面的模型不用试了。请先充值。")
            break

    print()
    print("=" * 68)
    if usable:
        print("结论：Key 可用。完全可用的模型：%s" % "、".join(usable))
        if config.LLM_MODEL not in usable:
            print("      注意：默认模型 %s 未完全通过，建议把 config.py 的" % config.LLM_MODEL)
            print("      PROVIDERS 里 %s 的 model 改成 %s" % (config.LLM_PROVIDER, usable[0]))
        else:
            print("      默认模型 %s 可用，直接启动 app.py 即可。" % config.LLM_MODEL)
        print("=" * 68)
        _real_file_test()
        return 0
    elif balance_out:
        print("结论：余额不足。充值后重新运行本脚本。")
        print("      充值页：%s" % config.LLM_TOPUP_URL)
        print("=" * 68)
        return 1
    else:
        print("结论：没有模型完全通过，请检查网络或换一个 Key。")
        print("=" * 68)
        _real_file_test()
        return 1


def _real_file_test():
    """用真实文件跑一遍完整链路，这才是实际使用效果。"""
    print()
    print("=" * 68)
    print("真实文件端到端测试（走 app 里完全相同的解析+校验链路）")
    print("=" * 68)

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    doc = os.path.join(root, "docs", "01-管壳式热交换器-输入文件")
    target = None
    if os.path.isdir(doc):
        for n in sorted(os.listdir(doc)):
            if "数据表" in n and n.lower().endswith(".pdf"):
                target = os.path.join(doc, n)
                break

    if not target:
        print("未找到示例数据表 PDF，跳过。")
        print("（可手动上传任意文件到 app.py 里试）")
        return

    import file_reader
    import schema

    print("文件：%s" % os.path.basename(target))
    text, meta = file_reader.extract_text(target)
    if not meta["ok"]:
        print("读取失败：%s" % meta["error"])
        return
    picked, truncated = file_reader.pick_relevant(text)
    print("抽出 %d 字符%s" % (meta["chars"],
                            "，裁剪为 %d 字符送模型" % len(picked) if truncated else ""))

    import agent_core
    res = agent_core.parse(picked, is_document=True)
    errs, warns = schema.validate(res["data"])

    print("来源：%s | %s" % (res["source"], res["note"]))
    print()
    for k, v in res["data"].items():
        print("  %-8s %s" % (k, v))
    if res["missing"]:
        print("  缺失必填：%s" % "、".join(res["missing"]))
    if errs:
        print()
        for e in errs:
            print("  ✗ %s：%s" % (e["field"], e["reason"]))
            if e.get("suggest"):
                print("    建议：%s" % e["suggest"])
    print()
    print("字段数 %d，错误 %d，缺失 %d" % (len(res["data"]), len(errs), len(res["missing"])))
    print("=" * 68)


if __name__ == "__main__":
    sys.exit(main())
