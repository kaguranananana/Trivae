# 端到端质量优化实验（2026-10-20）

**开发集没有证明质量提升，候选被拒绝，生产保留原策略。** 本轮完成的是一次真实失败驱动、可回溯的优化尝试及负结果验证，不能写成“已提升 Agent 答案准确率”。历史复盘见 [历史失败审计](Evaluation历史失败审计-20261020.md)，调参外结果见 [独立验证](Evaluation独立验证-20261020.md)。

## 身份、冻结和公平性

| 项目 | 固定条件 |
|---|---|
| 当前 Baseline A | `8def8d7`；先完成全部 8 条，再修改质量逻辑 |
| Candidate B | 质量 treatment `53a5155`，冻结执行 `3d9cc0e`；后续不调参 |
| 数据 | SQLite backup：811,892 canonical + 14,119 可恢复 forward occurrence；88 份来源；FTS 826,011 行；Qwen index completed、98,012 chunks |
| 时间 | 毫秒范围 1753011800000–1792461585000；两侧同一副本；不是历史 473,236 条的冻结环境 |
| Case | 8 个独立 `quality-` Case，保留旧 Development Case/版本；19 个已核验存在的 target；新快照适用性人工待审 |
| Provider | 官方 `deepseek / deepseek-flash / https://api.deepseek.com`；本地环境读取凭证，不保存密钥 |
| 执行链 | `EvaluationRunner → TrivaeApplication.query → shared Runtime → tools → Finalizer → Conversation/Trace/Evaluation` |
| 工具与预算 | 七个生产工具；forced Standard 隔离 Router/Planner；3 tool rounds、8 SDK turns；output16,384 / completion2,048；dynamic tool result budget原样保留 |
| Prompt | A 为原生产文本；B 仅澄清具名工具发现的充分性；其余文本/动态后缀、工具Schema、模型设置、Scope、索引与Case相等 |
| 请求预算 | 所有批次共享发送前持久化账本，最多120次真实Flash HTTP；失败/重试/预检同计，不清零；生产SDK max_retries=0 |
| 审核 | 当前答案为非盲 Assistant 源证据复核；不是人工审核或独立LLM Judge。已准备原生 ReviewPacket 与隐藏arm的后续人工展示 |

每题只运行一遍。Development 是先 A 整批、后 B 整批；独立验证是逐题 A→B 邻接，未做 counterbalance。Provider 后台权重、缓存和生成随机性不能冻结，数据是描述性配对观察，没有显著性或稳定提升声明。延迟取生产 Trace 的 Query duration；包含Evaluation重读及导出成本的实验wall time另外保存，不混作Query耗时。

## 根因与最小 treatment

历史 `dev-lexical-resume-miner` 是具名工具发现问题。当前 A 运行完成，但只取得相关建议和无名 Skill，再围绕该讨论读上下文，最终没有给出满足用途的具名资源。4 个已知 target 在完整 Tool record 中均不存在，模型投影没有省略，故不是 Final Evidence 选择或 Host 预算裁剪。

零 Provider 的正式词法诊断说明：单搜“项目经历”或“简历”的前100没有目标；结合用途与已有资源线索，“简历 skill”43命中中的20/21/23/24和“简历 github.com”26命中中的7/9/11/12均能取得四目标。它证明现有路径可达，不证明模型会自动构造这些词，也不把这些具体词写入产品。

候选只在现有 `prompt.py` 的检索选择段补充：用户求具体工具/资源时，方法建议或无名实现不足以建立所需名称或链接；语义结果只有这类内容时，以用途和已观察线索进行聚焦词法核验，保持原预算，不要求穷尽搜索。未修改检索算法、工具集合/Schema、权限、引用标准或 Finalizer；未引入自动重试、fallback 或按Case规则。

这个假设有真实 Failure Case 支撑，但它没有通过验证。B 确实增加词法检索，却只搜宽词，找到另一个简历制作资源，仍未证明其具备题目要求的项目经历整理用途。不能将“新增一个链接”记为目标问题解决。

## 事先定义的评分

有证据答案通过要求：执行交付成功、必要事实正确、关键证据充分支持、引用合法并支持对应结论、满足问题核心要求；任一明确失败即 fail，仍需裁决则 pending。固定 target 覆盖与语义通过分开：不要求所有重复分享都引用，但不能用别用途资源替代必要事实。

机器核验包括原生 Tier1、完整 Host/tool/model-visible/final Evidence 分层、实际来源恢复、执行状态、请求数、Trace、usage 和延迟。语义复核检查实际附带来源；身份/时间/引用可恢复并不自动证明推荐、用途、讨论立场或概括得到支持。

公开分母始终保留8题。人工审核尚未完成，人工答案通过率与人工事实引用支持率 unavailable；Assistant 结论只作 provisional。pending不默认为通过，也不从分母中删除。

## Development 配对结果

| 质量指标 | Baseline A | Candidate B | 变化与解释 |
|---|---:|---:|---|
| 人工有证据答案通过率 | unavailable | unavailable | 尚无新答案人工审核 |
| Assistant已确认 grounded pass | 1/8；fail5、pending2 | 0/8；fail5、pending3 | 不是人工准确率；pending保留，不能据此声称统计显著下降 |
| 固定目标Evidence覆盖 | 11/19，57.89% | 8/19，42.11% | −3/19，−15.79个百分点 |
| Tool returned目标覆盖 | 12/19 | 11/19 | 首次偏离主要在获取/工具选择 |
| 最终 required_context | 1/3 | 1/3 | 无上下文指标改善 |
| 人工事实引用支持率 | unavailable | unavailable | 所有未裁决维度保持待审 |
| Assistant必要事实检查 | pass17/21、fail3、pending1 | pass16/21、fail5 | 同21个事实/约束身份；不是全答案atomic-claim准确率 |
| 附带消息来源可恢复 | 161/161 | 208/208 | 全部时间/正文前缀与canonical一致；不代表语义支持 |
| 执行成功率 | 8/8 | 8/8 | 原分母，无Provider或Finalizer失败 |
| 实际Flash HTTP | 21 | 21 | 工具调用数不等于HTTP请求数 |
| 总Token | 523,488 | 584,931 | +61,443，+11.74% |
| 平均E2E延迟 | 34.66s | 44.48s | +9.82s，+28.33%；单次观察 |
| 中位E2E延迟 | 24.99s | 38.68s | 无方差估计或线上SLA声明 |
| 货币成本 | unavailable | unavailable | Provider未返回金额，不估算 |

## 每题结果与退化

下表省略共同的 `quality-dev-` 前缀。core是满足必要业务要求，grounded额外包含对应引用支持。

| Case | Evidence A→B | core A→B | grounded A→B | Trace/来源解释 |
|---|---|---|---|---|
| context-archify | 0/2→0/2 | pass→pass | fail→fail | B新增2次context，有更具体好评；新数据其他来源已能答题，但首block总体使用判断与所绑来源仍不充分 |
| context-mattpocock-1 | 1/2→1/2 | pass→pass | fail→fail | B不再沿用A的另一话题体验句；却把不同UTC日合并，并混入另一位同名人物的材料，属于生成/选据错误 |
| context-mattpocock-2 | 2/2→1/2 | pass→pass | pending→pending | 两目标均取回/可见，B最终只保留所需好评回复，遗漏原链接target；核心未失败，重复来源覆盖下降 |
| para-intern-owner | 1/1→0/1 | pass→fail | pending→fail | A取得并呈现认可与谨慎两种立场；B改查宽词/谨慎讨论，认可立场未召回，退化成单向概括 |
| lexical-resume-miner | 0/4→0/4 | fail→fail | fail→fail | B新增词法检查，但宽词未取得目标；另一个具名工具的用途也未验证，不能记作修复成功 |
| para-resume-advice | 0/1→0/1 | pending→pass | fail→fail | B新来源更贴近无量化指标场景；但仍把表达建议扩成与数字的优先级比较，引用不支持该比较 |
| cite-nanobot | 4/4→4/4 | pass→pass | fail→pending | B已把背景数字附到正确来源；附加群体概括与作者选择解释待人工裁决，未默认通过 |
| cite-meimei | 3/3→2/3 | pass→pass | pass→pending | 返回三目标但B只引用两条；核心清单仍正确，新增方法解释的局部绑定不足以直接裁决 |

所有退化保留，没有扩大预算、删题或修改评分规则。没有一个原 grounded fail 的Case经同尺度确认变成grounded pass。两处局部改善不能抵销目标未闭合与立场覆盖退化。

## 关键题补充复测与非确定性

正式40次运行结束后，按新登记顺序额外执行目标工具题A→B、立场题B→A，各一对；共4次、13次HTTP，与正式开发/验证分母分开。没有改Prompt、重试覆盖失败或挑选好答案进入主表。

- 工具题两次A/B都未取得四个已知target；额外B取到一个用途相关的替代Skill，并明确其推荐来自机器人、未实测。该替代是否足够满足题意应人工裁决，不能按链接存在直接判通过，也不能只因未命中旧仓库名便否定所有替代。
- 立场题B在补充观察中重新取得认可立场、恢复双向观点；A两次均呈现双方。这说明首次B内容退化有非确定性，不能把一次观察说成该Prompt必然导致的稳定退化；也不能用后一次成功覆盖首次失败。
- 补充两题的固定target覆盖A/B都是1/5，执行均2/2成功；不是新的独立验证集或总体通过率。

全部任务实际为118/120次Flash HTTP，118次均收到200；44份raw、44条Evaluation run/result、44条对应Trace、43份正式Artifact和44份ReviewPacket对齐。777次附带消息引用均能恢复且时间/正文前缀与canonical一致，其中包含重复来源引用；不代表777个独立事实或语义全部正确。Trace事件完整性44/44，内容仍遵守既有bounded capture与limitation契约，不声称保存hidden reasoning。

## 决策与可信边界

拒绝 `3d9cc0e`，生产 `SYSTEM_PROMPT` 恢复 `8def8d7` 原文。冻结候选仍用于调参外诊断，结果不被删除。回归记录 `named-resource-sufficiency-v1.json` 保留失败及拒绝原因，而非将未通过方案作为已上线修复。

本轮能证明历史失败审计、当前复现、分层归因、同条件实验、候选否决与成本核算能力；没有取得可信的端到端质量提升，也没有完成新答案人工审核或 fresh Holdout。不能把当前8/8执行成功、来源可恢复100%、更多工具调用或更多链接写成事实准确率。

后续如继续优化，应先核验目标工具发现中的查询改写/候选可达性与必要事实绑定；不因本实验再次添加提示句、自动扩大上下文、提高Top-K或并入未隔离的reply/cap修改。

## 复现与证据

- 运行：`evaluation_quality_experiment.py --help`；Candidate显式使用`--prompt-treatment`和对应Baseline目录。
- 分析：`evaluation_quality_report.py --root data/evaluation/quality-optimization-20261020`，复用既有GT解析、Tier1和ReviewPacket。
- 本地目录保留`freeze-initial.json`、`candidate-freeze.json`、`selection.json`、`protocol.json`、A/B逐CaseArtifact、Trace、Conversation、Evaluation SQLite、HTTP账本和评审材料；均被Git忽略。
- 公开机器统计与逐题运行标识见 [metrics.json](../evaluation/experiments/answer-quality-20261020/metrics.json)。只有脱敏统计，不含聊天正文或完整原始Trace。
- 最终全套测试为1201 passed / 1 skipped，Ruff通过，mypy检查128个源文件通过；提交身份见Git历史，详细验证记录见归档任务的validation。
