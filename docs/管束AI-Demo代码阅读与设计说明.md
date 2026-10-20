# 管束参数抽取Demo：代码阅读与设计说明

## 任务与范围

本次依据师兄“先看看能抽出来结构化参数”的要求，围绕已有助手增加参数抽取入口。先交付可独立运行的演示，避免把第一次演示绑定在数据库、产品创建、工程DLL及全部图形元件操作上。

这里把“Agent”拆成可验证的步骤：用户描述 → 模型解释为数据 → 本地验证 → 调用确定性工具 → 展示结果。当前工具固定为参数验证和只读布管试算，不开放任意代码、SQL、数据库操作或模型生成坐标。没有引入Agent框架、模型训练、知识库或自动优化。

## 读到的实际代码链路

| 代码 | 职责与本次判断 |
| --- | --- |
| `modules/buguan/buguan_ziyong/My_Piping.py: TubeLayoutEditor` | 当前管束主界面。参数表 `param_table` 是实际编辑数据入口；已经安装 `TubeAssistantController`，适合复用现有助手入口 |
| `load_initial_data / setup_parameters` | 数据来自产品库和元件库，并受产品型式、内/外径基准、控件类型和是否已有布管影响。不能让模型直接批量填这个表 |
| `update_DN_Di / update_tube_layout_circle_dl / on_combobox_changed` | 参数之间存在联动，DL等数值不是独立的随意输入；这也是本Demo不自动回填、不给模型推算DL的原因 |
| `_calculate_piping_layout_local` | 主程序的本地布管绘图链路会更新坐标、图形和多种状态，部分下游涉及持久化，不适合作为第一次只读演示入口 |
| `tube_pass/adapter.py: run_local_tube_layout / build_compute_kwargs` | 将规范参数名映射到已有 `compute_centers` 算法，并返回管孔坐标；本Demo的试算直接复用此层 |
| `tube_pass/adapter.py` 的分程映射 | 4及以上管程有多个具体分程型式，不能只看到“4管程”就擅自选 `4.1`；因此第一版试算限于1/2管程 |
| `ai_assistant/controller.py / core.py / history.py` | 先前已有“对中/跨中候选比较、拉杆位置候选、应用和撤销”。保留该流程，并在原面板加入新参数抽取页 |
| `ai_assistant/api_client.py` | 先前只能将语言解析成“布管目标/拉杆需求”，且同步网络会阻塞调用界面；本次新抽取入口使用后台线程 |
| `tests/test_tube_ai_*.py` | 已有助手的候选计算和应用测试，作为本次兼容性回归范围 |

旧 `TubeDistributionCore.py` 不作为当前页面完整规范校核引擎使用。当前Demo的字段与取值约定以实际 `My_Piping.py` 和 `tube_pass/adapter.py` 为准。

## 本次实现

```text
独立入口 run_tube_ai_demo.py
或 管束设计 → AI助手 → 参数抽取Demo
             ↓
extraction_panel.py：输入、设置、后台请求、表格、JSON、只读预览
             ↓
api_client.py：百炼兼容HTTP接口，JSON模式，非思考，单次请求
             ↓
extraction.py：白名单、类型、单位、证据、缺失与冲突
             ↓
tube_pass/adapter.py → core_calculation.compute_centers
             ↓
参数表、JSON、待澄清项、管孔预览
```

### 数据合约

模型只返回：

```json
{
  "parameters": [
    {"name": "换热管公称长度 LN", "value": 4500, "unit": "mm", "evidence": "管长4.5米"}
  ],
  "unresolved": []
}
```

本地验证后派生规范参数映射、依据列表、缺失项和检查问题，再附上真实/样例来源、模型名与token使用量。不会信任模型声称的 `pass`、`missing` 或计算结果；这些字段不在模型返回合约内。

本地验证原文依据确实存在、字段属于白名单、数值有限、枚举与单位有效、部分几何关系成立。它不能数学证明模型理解了每句话；引用存在也不等于引用与值语义一致。因此保留原文对照与人工复核，不宣称已测出抽取准确率。

### 百炼接入

- 使用Python标准库 `urllib`，无需SDK；地址限于百炼已知HTTPS域名及业务空间域名。
- 默认 `qwen-plus`，`response_format={"type":"json_object"}`，`enable_thinking=false`。
- 参数抽取提示词明确要求仅提取原文，不补工程默认值；长度统一mm，歧义与不支持信息单列。
- 请求只发送用户输入的描述与字段约定，不自动发送产品数据库、当前页面完整参数、客户信息或程序源码。
- 后台线程只执行HTTP与纯数据处理，控件更新在Qt主线程进行。
- 描述或当前产品快照变化后，丢弃旧响应；不自动重试，不隐式追加请求。
- 新设置界面仅在进程内保留密钥，持久化文件只含地址/模型；导出JSON不含密钥。

### 只读试算边界

要求用户明确提供计算必需参数；2管程还要求竖直分程隔板间距。遇到缺失、歧义、已识别冲突时拒绝试算。复用原算法返回坐标，仅绘制预览，不调用主界面绘图/保存方法。

输出计数是管孔数量，不能未经换算就称作U形管根数。布管预览也不代表强度、制造、干涉、规范等完整检查通过。

## 后续怎么推进

1. 先用真实百炼请求跑成功、缺失、冲突三组描述，保存JSON与人工核对结果。
2. 收集20～50条实际描述，逐字段记录正确、漏提、误提、单位换算和歧义；没有数据前不承诺准确率。
3. 根据出现最多的需求补字段与同义词，不急于开放所有元件。
4. 确实需要回填时，先开放2～3个可安全修改的字段，显示旧值→新值并确认；需复用既有校验联动、保存边界和完整撤销机制。
5. 再考虑工具选择、多轮澄清、拉杆/折流板等功能。无需为“看起来像Agent”先引入重型框架。

本次测试与运行命令：

```powershell
python -m unittest discover -s tests -v
python run_tube_ai_demo.py --sample
python run_tube_ai_demo.py --screenshot docs/images/管束AI-Demo预览.png
```

真实模型质量和账号可用性仍需输入本地密钥后验收；模拟HTTP测试不能替代真实API联调。
