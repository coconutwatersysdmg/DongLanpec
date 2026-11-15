# -*- coding: utf-8 -*-
"""
离线自测脚本（不需要人工点界面）

跑一段示例输入，打印解析/校验/预览结果，用于快速验证逻辑。
也可以加 --shot 生成窗口截图。
"""
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agent_core
import schema


CASES = [
    ("全部合法",
     "给我添加一个新项目，项目名称：渤中19-6滨州终端换热器，"
     "项目编号：OED2022-32，业主名称：中海油石化工程有限公司，"
     "产品名称：提纯塔入口冷却器，产品编号：MT-ED2232-MA-600001，"
     "设备位号：E-2101，产品类型：管壳式热交换器，产品型式：BEU，设计阶段：方案设计"),

    ("产品类型非法",
     "新建项目，项目名称：天津石化二期，产品名称：再沸器，"
     "产品类型：管壳式换热器，产品型式：AEU，设计阶段：详细设计"),

    ("型式与类型不匹配",
     "加个项目，项目名称：测试工程，产品名称：冷凝器，"
     "产品类型：立式容器，产品型式：AEU"),

    ("缺必填",
     "帮我建个项目，项目名称：某工程"),
]


def run():
    print("=" * 70)
    print("Agent 助手 · 离线自测")
    print("=" * 70)
    import config
    if config.llm_enabled():
        print("模型状态：%s 已配置（%s）" % (config.LLM_LABEL, config.LLM_MODEL))
    else:
        print("模型状态：未配置 Key（使用规则解析）")
    print()

    ok_count = 0
    for title, text in CASES:
        r = agent_core.parse(text)
        errs, warns = schema.validate(r["data"])
        print("-" * 70)
        print("【%s】" % title)
        print("输入：", text)
        print("解析：", r["data"])
        print("来源：", r["source"], "|", r["note"])
        if errs:
            print("不合法：")
            for e in errs:
                print("   ✗ %s：%s" % (e["field"], e["reason"]))
                if e.get("suggest"):
                    print("     建议：%s" % e["suggest"])
        if r["missing"]:
            print("缺失必填：", "、".join(r["missing"]))
        if warns:
            print("提醒：")
            for w in warns:
                print("   · %s：%s" % (w["field"], w["reason"]))
        if not errs and not r["missing"]:
            print("✓ 通过")
            ok_count += 1
        print()

    print("=" * 70)
    print("自测完成：%d/%d 个用例完全通过" % (ok_count, len(CASES)))
    print("（其余用例是故意构造的异常，应该报错）")
    print()

    run_text_cases()


# 文件读取/文本抽取相关：用"模拟 PDF 抽出的文本"验证规则，不依赖磁盘文件
TEXT_CASES = [
    ("PDF 标签与值分行 + 中英对照标签",
     """项目文件号
213002D1019
PROJECT NO.
业主文件号
DD-DDS-OST-PR-19001
OWNER NO.
设计阶段
详细工程设计
STAGE
工厂(公司)名称
中海石油（中国）有限公司天津分公司
COMPANY NAME
项目名称
渤中19-6凝析气田I期开发项目滨州天然气终端工程
PROJECT NAME""",
     {"项目名称": "渤中19-6凝析气田I期开发项目滨州天然气终端工程",
      "项目编号": "213002D1019",
      "业主名称": "中海石油（中国）有限公司天津分公司",
      "设计阶段": "详细工程设计"}),

    ("Excel 一行里多段「标签：值」",
     "工程名称：渤中19-6凝析气田I期开发项目滨州天然气终端EPC总承包工程换热器等设备  "
     "总包方：中海油石化工程有限公司  项目编号：OED2022-32",
     {"项目名称": "渤中19-6凝析气田I期开发项目滨州天然气终端EPC总承包工程换热器等设备",
      "工程总包方": "中海油石化工程有限公司",
      "项目编号": "OED2022-32"}),

    ("逐字加空格的抬头不能当值",
     """工程名称
换 热 器 基 础 设 计 条 件
设计阶段
详细设计
资料编号
项目号""",
     {"设计阶段": "详细设计"}),
]


def run_text_cases():
    print("=" * 70)
    print("文本抽取自测（模拟文件抽出来的文本）")
    print("=" * 70)
    passed = 0
    for title, text, expect in TEXT_CASES:
        got = agent_core._parse_rule(text)
        bad = {}
        for k, v in expect.items():
            if got.get(k) != v:
                bad[k] = (v, got.get(k))
        # 额外检查：不该出现噪声值
        noise = {k: v for k, v in got.items() if not v or v.strip() in ("说 明", "换 热 器 基 础 设 计 条 件")}
        if not bad and not noise:
            print("  ✓ %s" % title)
            passed += 1
        else:
            print("  ✗ %s" % title)
            for k, (want, real) in bad.items():
                print("      %s 期望 %r，实际 %r" % (k, want, real))
            if noise:
                print("      噪声字段: %r" % noise)
    print()
    print("文本抽取：%d/%d 通过" % (passed, len(TEXT_CASES)))
    print()


if __name__ == "__main__":
    run()
