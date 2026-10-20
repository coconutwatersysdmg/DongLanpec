# 管束模块 AI 操作助手实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本文件仅为计划，不代表已经授权开始实现；执行方式后续确定。

**Goal:** 在管束页面加入 AI 助手，实现自然语言生成参数修改草案、确认后应用，以及解释当前设计的程序检查结果。

**Architecture:** 第一版使用云端模型 API。PyQt5 页面收集当前设计快照，AI 返回结构化建议，本地程序验证后展示变更预览，用户确认后通过既有参数编辑流程应用。现有程序负责计算和规则判定；模型调用封装在独立模块，后续可以适配本地推理服务。

**Tech Stack:** 现有 Python / PyQt5、HTTP JSON 模型接口、标准库 unittest；不在本阶段安装依赖、创建密钥或运行付费请求。

**Spec:** 本文件“设计范围与决策”节是本计划的自包含设计依据，来源为当前聊天中的方案讨论。

## Global Constraints

- 当前交付为可讨论的方案与实施计划，不修改产品代码，不安装模型。
- 第一版仅允许修改当前管束页面确实允许用户编辑的参数；产品定义来源字段、锁定字段、自动计算字段不得通过 AI 绕过限制。
- 模型输出只能表示预定义操作或文本解释，不得执行其返回的 Python、SQL 或任意工具命令。
- 数字计算、几何检查、约束判定由本地程序负责；AI 不得把自己的推测标记为通过规范校核。
- 修改必须先显示对比并经用户确认；不新增自动保存和自动重算。用户按现有按钮计算、保存。
- 发送到模型的内容限定为本次必要的设计参数和检查结果；不发送数据库凭据、客户资料或整库内容。API 密钥从运行环境读取，不写入源码或日志。
- 不覆盖工作区已有的用户修改，不更换现有数据库结构。

## Review Focus

1. 页面或产品切换后返回的旧 AI 响应：丢弃，不更新当前页。
2. 预览期间用户手动修改参数：旧草案失效，要求重新解析。
3. 模型生成只读字段或未知字段的修改：整份草案拒绝，不部分执行。
4. 部分赋值触发现有联动或失败：恢复变更前的完整编辑状态；未实现恢复之前不开放多字段应用。
5. 检查未覆盖的条件、数据不全：显示“未检查”或“信息不足”，不得显示“设计合格”。

## 设计范围与决策

### 第一版功能

1. **自然语言填参**：输入要求，生成“参数、原值、新值、单位”的草案。首批仅开放 2～3 个经代码确认允许编辑、能够恢复状态的字段。
2. **检查结果解释**：程序输出可复用的检查结果，AI 将其转成“问题、依据、处理建议”；只读，不自动改参数。
3. **统一入口**：管束页操作区新增“AI助手”，弹出非模态面板，包含指令输入、解析按钮、变更预览、确认应用、解释检查结果。

示例语句：“把某个当前可编辑参数设为指定值。”具体演示字段以阶段 1 的可编辑白名单为准，不能提前假设管程数、外径等字段在所有产品下都允许修改。

不纳入第一版：模型训练、微调、全自动布管优化、图像识图、跨模块修改、自动写数据库、规范知识库检索。

### API 与本地部署

| 路线 | 方式 | 适用判断 |
| --- | --- | --- |
| 云端 API（首选） | 桌面端通过 HTTPS 调用服务商提供的模型 | 原型接入较直接，无需在电脑运行模型；需要网络、服务凭据，费用取决于实际调用 |
| 本地模型（后续） | 使用本机推理服务，再通过本地 HTTP 接口调用 | 有离线要求或明确的数据不出机要求时再评估；速度和资源需求取决于模型、量化及机器配置 |

二者都可以通过 API 调用，区别是模型运行在哪里。统一接口仅使上层流程可复用；服务切换仍需适配鉴权、请求格式并重新验证输出质量。

现在可以先用明确标注“模拟响应”的数据展示交互，但模拟演示不算完成模型接入。模型服务商和具体型号在真正实现前选择，不在本计划中购买或绑定。

### 已核实的项目入口

- `modules/buguan/buguan_ziyong/My_Piping.py`：实际管束编辑页面，已有 `param_table`、操作栏与“操作记录”。
- 该文件的 `on_param_changed` 负责参数修改相关处理，需要沿用现有校验与联动。
- 布管前存在 `update_tube_center_distance`、`update_DN_Di` 等同步流程，部分参数会重新计算或被上游数据覆盖。
- 不直接将 `TubeDistributionCore.py` 中的旧校验当成当前页面完整检查引擎；必须确认当前调用链后复用。

### 建议文件职责

在 `modules/buguan/buguan_ziyong/ai_assistant/` 下新增：

- `contracts.py`：快照、字段定义、变更草案、检查结果和响应校验。
- `provider.py`：HTTP 模型调用、超时、响应解析；后续本地服务适配也放在此边界。
- `bridge.py`：页面状态读取、可编辑字段映射、调用既有编辑流程、状态恢复。
- `panel.py`：AI 面板、后台请求任务、结果预览与状态显示。
- `__init__.py`：包入口。

仅在 `My_Piping.py` 增加入口和桥接挂接，不把网络请求堆入该大文件。单元测试置于 `tests/test_tube_ai_*.py`。

## Task 1：确认参数边界与页面快照

**Files:** `ai_assistant/contracts.py`、`ai_assistant/bridge.py`、`tests/test_tube_ai_bridge.py`；以上模块路径均以建议目录为基准。

**Interfaces:** `collect_snapshot(editor) -> dict`，返回 `context_id`、`revision`、`parameters`、`results`、`checks`；参数字典每项包含 `id`、`label`、`value`、`unit`、`editable`、`allowed_values`。`context_id` 标识产品及页面实例；`revision` 在影响本次请求的状态变化时递增。

- [ ] 沿当前页面调用链确认 2～3 个可编辑字段，记录来源、类型、单位、可选值与联动；无法确认的字段保持只读。
- [ ] 先写快照测试：只读字段 `editable=False`，界面中的空值保持为空，下拉框返回当前真实值。
- [ ] 实现快照读取，不读取隐藏凭据，不产生数据库写入。
- [ ] 运行 `python -m unittest discover -s tests -p "test_tube_ai_bridge.py" -v`，预期全部通过。

**Deliverable:** 一份与当前页面一致、可作为模拟或真实模型输入的结构化快照。

## Task 2：定义修改草案与本地验证

**Files:** `ai_assistant/contracts.py`、`tests/test_tube_ai_contracts.py`。

**Interfaces:** `validate_proposal(raw: dict, snapshot: dict) -> dict`。输入操作固定为 `propose_parameter_changes`，`changes` 每项仅含 `parameter_id`、`value`、`unit`；返回已验证草案，补充由本地快照读取的原值。错误抛出 `ValueError`，不返回可部分执行的草案。

- [ ] 先写测试：未知操作、未知字段、只读字段、重复字段、非有限数字、不匹配单位、选项不在允许范围均拒绝；合法单字段修改接受。
- [ ] 实现字段白名单及类型检查；第一版只接受字段原生单位，其他单位提示用户重述，避免隐式换算。
- [ ] 对相同值返回无变更提示，不生成可执行修改。
- [ ] 运行 `python -m unittest discover -s tests -p "test_tube_ai_contracts.py" -v`，预期全部通过。

**Deliverable:** 不依赖服务商的输出约束，可用固定响应验证交互。

## Task 3：接入模型 API

**Files:** `ai_assistant/provider.py`、`tests/test_tube_ai_provider.py`。

**Interfaces:** `request_ai(mode: str, instruction: str, snapshot: dict) -> dict`；`mode` 只接受 `propose_changes`、`explain_checks`。连接参数由运行配置提供，密钥只从环境变量取得。

- [ ] 实现前选定服务商与模型，确认凭据的配置方式；此计划阶段不收集密钥、不创建账号、不发付费请求。
- [ ] 先写模拟 HTTP 测试：成功、30 秒超时、鉴权失败、响应为空、JSON 非法、字段不合约定。失败不得返回成功草案；不自动重试付费请求。
- [ ] 将指令、字段定义和快照发送给模型，要求结构化输出；对模型响应执行 Task 2 的验证，JSON 合法不等于业务合法。
- [ ] 不把密钥或完整请求写入错误日志；仅显示用户可理解的失败原因。
- [ ] 运行 `python -m unittest discover -s tests -p "test_tube_ai_provider.py" -v`，预期全部通过。真正端到端验收必须额外完成一次真实 API 调用。

**Deliverable:** 隔离的模型调用接口，后续可通过服务适配接入本地模型。

## Task 4：加入预览与确认应用

**Files:** `ai_assistant/panel.py`、`ai_assistant/bridge.py`、`My_Piping.py`、`tests/test_tube_ai_bridge.py`。

**Interfaces:** `apply_proposal(editor, proposal: dict, expected_context_id: str, expected_revision: int) -> dict`；返回实际生效值和联动变更。上下文不符或应用失败时拒绝并恢复，不自动保存或布管。

- [ ] 先写测试：产品切换后拒绝旧草案、预览后手动修改导致草案失效、取消不变更状态、赋值失败恢复原状态。
- [ ] 在现有操作栏增加“AI助手”，显示输入框和“原值 → 新值”预览。
- [ ] 后台任务执行网络请求，主线程读取快照与更新控件；响应回来再次核对上下文，避免串产品或串页面。
- [ ] 通过现有编辑、校验及联动流程应用参数；不屏蔽既有校验，不直接写数据库。确认后展示实际联动结果。
- [ ] 单字段事务验证可靠后再开放多字段；撤销/恢复需覆盖联动状态，不能只把输入框改回去。
- [ ] 运行桥接单元测试，并手动验证等待期间界面可交互、取消无副作用、原布管与保存流程仍可用。

**Deliverable:** 自然语言到实际参数操作的完整闭环。

## Task 5：解释检查结果

**Files:** `ai_assistant/bridge.py`、`ai_assistant/provider.py`、`ai_assistant/panel.py`、`tests/test_tube_ai_checks.py`。

**Interfaces:** `collect_checks(editor) -> list[dict]`；每项包含 `check_id`、`status`、`parameter_ids`、`message`、`basis`。`status` 仅用 `pass`、`fail`、`not_checked`；AI 解释响应包含 `check_id`、`explanation`、`suggestion`，不得改变原始检查状态。

- [ ] 确认并封装实际可复用的校验；第一版至少覆盖必要输入缺失和已有可复用的约束，未覆盖项目明确标记。
- [ ] 先写测试：没有检查记录不能报告合格；缺参数显示信息不足；模型引用不存在的检查编号时拒绝对应解释。
- [ ] 面板固定显示程序原始检查状态，AI 解释作为补充文字；建议值若无程序依据不得呈现为确定结果。
- [ ] 运行 `python -m unittest discover -s tests -p "test_tube_ai_checks.py" -v`，预期全部通过。

**Deliverable:** 能说明检查依据与下一步操作的只读诊断功能。

## Task 6：演示与验收

- [ ] 运行 `python -m unittest discover -s tests -p "test_tube_ai_*.py" -v`，预期全部通过。
- [ ] 准备有效设计：输入合法指令，出现准确变更对比，确认后值与联动一致，再由用户点击现有布管按钮。
- [ ] 准备缺参数设计：解释指出缺失字段，不编造计算结果和规范结论。
- [ ] 演示取消、未知字段、超时、产品切换、预览后手改；均不产生意外参数变更。
- [ ] 在具备配置时完成真实 API 的合法指令与异常响应验证；固定响应必须标明“模拟”，不作为真实 AI 接入完成的依据。
- [ ] 记录所测指令和结果，课堂汇报展示成功与失败各一例；不在尚未实测前承诺准确率。

**Deliverable:** 可复现演示及验证记录。

## 当前阶段向老师汇报的表述

“计划在管束模块增加 AI 操作助手，第一版通过模型 API 将自然语言转成结构化参数修改草案，由现有程序校验、用户确认后应用；同时结合当前设计数据解释检查结果。布管和约束判定沿用原算法。先验证交互与可编辑字段范围，后续如有离线要求，再评估本地部署。”

## 技术参考

- DeepSeek JSON Output（云端接口能力示例，不代表已选服务商）：https://api-docs.deepseek.com/zh-cn/guides/json_mode/
- Ollama 本地 HTTP API：https://docs.ollama.com/api/introduction
- Ollama 结构化输出：https://docs.ollama.com/capabilities/structured-outputs

计划编写日期：2026-10-17。未安装依赖、未配置服务凭据、未调用计费模型接口、未修改管束产品代码。
