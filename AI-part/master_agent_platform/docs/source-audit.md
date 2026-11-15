# 源码接入核查

核查日期：2026-11-13。本表是初始静态源码核查；此后完成了只读基础库复制、私有库校验、真实文件抽取及布管引擎合成烟测，详见 implementation-status.md。没有调用外部模型或强度计算 DLL。

行号为本次工作区定位，可随后续修改变化。

| 范围 | 已确认入口 | 当前能力 | 接入独立平台需要补齐 |
| --- | --- | --- | --- |
| 项目产品 | `AI-part/ai_xiangmuguanli/product_splitter.py:59` `split(paths)` | PDF/Excel 项目与产品识别、证据、原文页段 | 实际分片与平台身份；规范化文件冲突处理；不把位号数量和实物台数混为一谈 |
| 条件输入 | `AI-part/ai_tiaojianshuru/api.py:63` `run_condition_agent` | 无界面输出五类条件，带状态/程侧/单位/证据 | 与私有模板及数据编织写入服务对接；不能将 `status=ok` 等同完整；模块使用通用 `config/core/infra` 导入名，同进程加载多个模块会有冲突风险，应改为包内导入或隔离工作进程 |
| 元件定义 | `AI-part/ai_yuanjiandingyi/graph.py:41` `run_pipeline`，`:66` `apply_pipeline` | 文档/对话材料抽取、映射、验证和写库流程 | 当前主要是材料四字段；增加模板实例、全部几何及附加/合并参数；`modules.element_define_agent.*` 导入路径与本目录不一致，不能假设直接可用；依赖旧业务数据库的部分改为私有 Repository |
| 管口定义 | `AI-part/ai_guankoudingyi/server/service.py:164` `parse_bytes`，`:192` `parse_path` | 无界面解析及 `dlp.nozzle-list/2` 输出，有独立 HTTP 服务 | 转为统一平台契约；管口实例身份、材料与附件归属、定位与方位待核对项进入领域校验；未知角度保留未知，不补0 |
| 布管设计 | `AI-part/ai_buguan/bundle/engine.py:186` `compute`；`session.py:127` `save` | 正式 HE3DTB 几何接口；四页保留后事务写入 | 四页数据准备、校验与保存脱离 PyQt；默认值按私有模板及型式选择；引擎中的 `FALLBACK_INPUT` 不能不经核对作为任意产品的工程事实 |
| 数据空间 | `data_center_standalone/data_center/backend.py`、`space_store.py`、`resource_store.py` | 原库字段引用/事务、产品范围、资源/版本及元数据 | 显式连接私有实例，独立 home 与上下文；增加 Agent 数据契约、任务快照和候选接受流程 |
| 知识上下文 | `data_center_standalone/data_center/knowledge_export.py:45` `build_package` | `donglanpec.knowledge-package/1`，版本、SHA256、稳定片段ID及位置 | 当前是有界摘录，无向量库、语义检索、OCR；补检索服务和覆盖标记，扫描资料无解析能力时不宣称已理解 |
| 数据空间迁移 | `data_center_standalone/data_center/resource_store.py:379` `backup` | 一致 SQLite 目录快照、托管文件及运行证据校验 | 不含业务数据库、原位资料或远程资源；要脱离源系统，需另外复制基础库与必要原位文件并重定位 |
| 计算输入 | `modules/qiangdujisuan/jiekou_python/combine_json_new_aem.py:6875` 等 | 组装 `WSList/TTDict/DesignParams/DictPart/DictDatas`；`:6893` 用产品名称填 `ProjectName` | `:6954` 同函数实际调用强度 DLL；应迁出纯数据组装器并验证全部规则；不能为了导出而调用旧函数 |
| JSON 顶层检查 | `modules/json_backfill/validator.py` | 支持九种换热器型式、顶层结构检查与部分提示 | 该校验器面向反填；不检查全部工程必填项，空工况/空部件仅告警，不能证明可计算 |
| 旧包格式 | `modules/chanpinguanli/project_archive.py:237` `export_project` | 原业务库所选产品和文件的 `.dlpec` 快照 | 依赖已有产品记录及数据库；不是从输入文件自动生成新产品的独立接口。本期新包不宣称兼容 `.dlpec` |

## 主要工程风险

1. **抽取成功不等于产品完整**：现有模块的能力范围和成功语义不统一。主控必须依据领域要求核对每个适用实例和字段。
2. **界面解耦不等于运行脱离原库**：部分查询、全局配置和导入路径仍指向旧环境；必须在断源验收中逐项暴露，不靠改启动文件解决。
3. **知识摘录不等于语义检索或完整资料迁移**：必须分别建设检索与源文件托管。
4. **JSON 顶层一致不等于计算兼容**：嵌套映射、型式、工况、单位、占位符和材料/几何派生规则需要真实消费者契约与基准案例核验。
5. **数据编织不是任意多源拼接**：项目/产品、程侧、工况、元件实例、管口类别和参数 Tab_ID 必须保留粒度，不能按名称或数字ID猜测关联。

## 本次交付状态

已完成范围澄清、源码静态核查、目标架构/契约/依赖图设计，并实现独立数据库复制、后台源码副本、任务回执、数据空间托管和单窗口抽取原型。当前已取消固定型式/首台限制，真实11产品逐台处理；缺项经审核循环，只有明确必需的未解项进入人工审核，人工提交后重新校验。条件、材料、管口抽取已在真实多产品文件上验证，几何引擎仅完成合成烟测。元件预设计、完整工程必需性规则、完整模块适配器和计算输入导出器仍未完成。不得据本轮审核完成宣称完整产品包已生成。
