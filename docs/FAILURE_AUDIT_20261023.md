# 当前 Failure Case 复核与下一轮验证建议

2026-10-23。审查起点为当前 `main` 的 `287a199`。本轮是审计和零模型复现，没有修改产品实现、Prompt、默认预算、在线数据或历史运行结果。

最值得继续做的工作是：修复**补齐转发正文仍被判为相同重复**、**SQL 阻塞事件循环**两条已复现链路；重新验证**笔试经历检索遗漏**和**结论与所绑来源不匹配**。另外，部分覆盖下的空结果交付、混合单字检索和流式解析诊断仍有明确缺口。不能把此前某份修复清单收口解释为全部历史质量问题已经解决。

## 复核范围与当前基线

- 重读当前状态、开发日志、修复清单、10-20 质量实验、10-21 轮次实验、10-22 回复/预算/空结果验收、10-23 长消息/全范围建议/前端验收；重要判断再检查保存的结果、逐题评审或当前代码。
- 复用现有只读审计器读取 1,574 条唯一 Evaluation 运行，200 个批次/Provider/模型/Variant/版本分组，全部可关联 Trace；2 个封存库排除，读取错误 0。这里包含历史实验和离线重放，不能合成线上成功率。
- 10-23 的若干直接 Application 查询不在上述 Evaluation 分母中，另外检查其独立结果和报告；不能由库存中没有新 Evaluation 推断当天没有真实运行。
- 当前在线 readiness：Canonical 829,397 条、12 会话；语义索引完成且 revision 63,617 对齐，100,175 chunks、14,763 条转发投影；Plan / gpt-6.1-sol ready。readiness 只证明装配与索引状态。
- 本轮后端 `1269 passed / 1 skipped`（33.53 秒），前端 `80 passed`；Ruff `src tests scripts`、mypy 129 个源文件通过。没有新增真实生成请求或 Judge，没有复制大库或重算向量。

## 按价值排序

| 优先级 | 问题 | 当前证据 | 下一步性质 |
| --- | --- | --- | --- |
| 高 | 后导入的完整转发正文被当作 equal duplicate 丢弃 | 本轮正式 Importer→Canonical→重建 FTS 最小复现失败；反向顺序控制通过 | 修导入归并及正文保留，补回归 |
| 高 | SQL 有 5 秒期限，仍占住异步事件循环 | 本轮真实 SDK 入口两次观察约 5 秒阻塞；快查询控制正常 | 修执行调度，验收并发和 Stop |
| 高 | 笔试经历题找到相近材料后提前结束 | 最新保存的 Plan 运行漏目标；当前词法确认目标可达 | 先跑当前配置的原题验证，再决定策略改动 |
| 高 | 来源真实，但数字/人物/整体概括未绑到支持它的原文 | 历史逐题审查有具体失败；当前模型未系统复验 | 小规模结论—来源核验及真实质量实验 |
| 中 | 不完整覆盖且零命中缺少正常交付形态 | 当前真实工具历史下 no_result 失败，空来源 claims 仅 degraded | 明确并实现此类调查结果的输出契约 |
| 中 | 多词 AND 夹单个汉字仍漏召回 | `github.com 荐` 为 0，主表有 19 条字面同时命中 | 按真实搜索需求决定是否扩大契约 |
| 中 | 真实流式解析失败没有可重放的坏正文 | 10-21 原失败仍在；只存异常类型及前两次正常输出 | 补失败诊断，再定位，不盲修 parser |
| 后续实验 | 语义改写、全范围综合、6 轮及 Planner 的一般收益 | 多数只是历史样本或单次正结果，缺少当前配对/重复 | 固定条件做少量针对性实验 |

## 1. 新增确定性缺陷：补齐的转发正文没有进入 Canonical

输入形态来自现存的未展开转发：第一次导出只含预览、`messages: []`，后一次导出补齐同一根消息的内部正文。隔离小库保留相同消息 ID、时间、预览及其他稳定字段，只改变内部正文。

| 导入顺序 | 第二次导入 | 重建 FTS 后正文命中 | 剩余缺口 | 非 Canonical 版本保存 |
| --- | --- | --- | --- | --- |
| 空转发→完整转发 | duplicate 1 / conflict 0 | **0** | 1 | duplicate_equal，raw 为空 |
| 完整转发→空转发 | duplicate 1 / conflict 0 | 1 | 0 | duplicate_equal，raw 为空 |

根因在 [model.py](../src/trivae/data/model.py) 的 `canonical_projection()` 与 [sqlite.py](../src/trivae/data/storage/sqlite.py) 的 `write_message()`：重复比较排除了 `content_json`，两版根消息的 `content_text` 相同，于是内部正文变化也被当作完全相同；equal duplicate 又不保存 incoming raw。重建索引无法恢复根本没有存入 Canonical 的正文。反向控制证明转发解析和 FTS 可以检索这段输入。

这与“全部采用最后一次导出”是不同的修改范围。应先让实质转发正文变化被识别和保留，再明确空节点补齐的归并规则；不能把所有 exporter 元数据都加入 invariant，也不能直接覆盖完整的旧正文。验收至少包括空→完整、重复补齐的幂等、嵌套补齐，以及 Canonical revision / FTS / 语义增量发布的真实同步。

当前实际库有 244 个空转发节点，涉及 143 条根消息，242 个为嵌套节点、2 个为根层节点。检查了这些消息的 11 次其他来源出现，涉及 7 个仍在本地的源文件；尚未证明它们提供可直接恢复的完整替代正文。因此**244 不是本缺陷已确认造成的丢失数量**。本轮证明的是当前导入链不能吸收这种补齐，实际历史影响量仍待专门核验。

## 2. 新增确定性缺陷：SQL 超时没有解决事件循环阻塞

历史 SQL 无期限计算已修，当前 5 秒中断也确实生效；遗留的是响应性。

在临时 1,000 条消息小库，通过真实 `ExecuteSQLSDKToolAdapter` 执行四表交叉计数，同时安排 20ms 后执行一个普通事件循环回调：

- 快查询控制：SQL 约 1.1ms；回调约 21.1ms 执行。
- 慢查询：SQL 约 5.0004 秒返回 `SQL_EXECUTION_TIMEOUT`；回调约 5.0005 秒才执行，额外迟到约 4.9805 秒。
- 先前独立测量同样迟到约 4.9809 秒。未访问线上库，没有模型请求。

[openai_tools.py](../src/trivae/query/runtime/openai_tools.py) 的异步工具函数直接调用同步 `registry.invoke()`；SQLite 计算期间没有让出事件循环。Web 的 Query、Stop 和其他异步路由共用这一调度机制，因此存在同进程请求及取消处理被拖住的风险。这里直接测量的是 SDK 调度阻塞，尚未冒充已完成真实浏览器并发压测。

建议将 SQL 计算移出 Web 事件循环，保留现有超时和错误分类；同时处理 SQLite 连接及 Trace 的线程归属，不能把整个共享 Registry 随意包进线程。修复验收应覆盖同一次慢查询期间的普通 API 响应、Stop 送达、显式超时，以及之后正常 SQL 仍可用。探针的 200ms 阈值只是捕获这次五秒阻塞的检查线，不是产品 SLA。

## 3. 历史仍未闭合：笔试经历检索遗漏

原题：**“有人遇到过笔试需要自己构造测试数据的情况吗？”**

最新保存的 Plan / gpt-6.1-sol / medium 运行在 10-22，3 HTTP、2 工具轮、Finalizer valid。它先 semantic（limit 6、dense_top_k 40），再 lexical `构造`（limit 20），共取得 110 条不同消息，没有投影省略，但已知直接经历没有进入完整 ToolResult。答案谨慎地说“暂未确认”，并区分面试手撕和笔试样例不足；措辞没有编造，核心证据仍漏了。

本轮在当前只读库确认目标原文存在，直接描述笔试未给输入示例、需要自行构造模拟简历测试集。词法诊断为：

| 查询 | 当前总命中 | 已知目标排名 |
| --- | --- | --- |
| 构造 | 91 | 41 |
| 笔试 测试 | 40 | 8 |

这说明现有路径能够找到目标，宽词取前 20 存在明显遗漏通道。当前库与旧实验快照不同，**不能把现在的第 41 名当作旧运行的精确排名**，也不能把人工诊断词直接硬编码到产品。旧运行没有用完工具轮数；仅把默认值提高到 6 不证明模型会继续查找。

下一步用当前完整配置重跑原题，检查目标或等价的直接经历是否进入 Host、模型可见输入和最终答案。若仍失败，才隔离查询构造、候选深度或证据充分性中的一个变量。先不要重做此前已经被否决的“具名资源充分性 Prompt”。

## 4. 历史仍未闭合：结论与其实际所绑来源不匹配

重新读取 10-20 保存的逐题 Assistant 审查，具体失败包括：

- **Nanobot**：正文数字确实出现在本轮另一个工具来源，却没有附到包含该数字的段落；属于引用绑定遗漏，不是数字凭空编造。
- **Archify**：概述段包含实际使用及整体判断，其绑定来源只支持发布、链接和定位；使用证据附在其他段落，不能代替本段来源。
- **Matt**：把另一产品讨论中的短评当成目标工具好评；旧候选另出现不同 UTC 日期合并、另一位同名人物材料被用于讨论跨度。
- 建议题历史上还出现把有限表达建议扩成优先级比较、遗漏相反意见等情况；owner 与 advice 后续已有局部修复和有效来源复核，不能重复列为全部未修。

当前 Finalizer 校验身份、范围、位置、可信元数据和结构；不会证明自然语言概括得到引用原文支持。来源按钮和段落引用现已接通，也不会自动修复生成阶段的选据错误。

这些历史失败没有形成当前 Plan/Sol 上的系统复验，不能宣称今天仍必然发生，也不能宣称已经普遍解决。建议先选数字、人物、概述各一题，逐段检查“这句话由实际绑定的哪段原文支持”。复用已有 ReviewPacket 即可；先取得小规模可判定结果，不需要给每句话增加模型裁判或机械打总分。

## 5. 当前可复现的交付缺口：部分覆盖下的零命中

10-20 CJK 实验的不存在词曾因转发缺口导致空结果被拒。本轮用当前正式词法工具查询同一不存在词“量子香蕉数据库”：

- `total_hits=0`，工具 status 为 ok，但 coverage 为 partial，原因是范围内 244 个未展开转发节点。
- 对同一工具历史输出诚实的 `kind=no_result`，即使说明缺失转发、不声称全库没有，仍得到 `INVALID_FINAL_OUTPUT`。
- 改为无来源的普通 claims，严格校验为 `MISSING_EVIDENCE`，现有 graceful 路径能够保留正文，最终为 **degraded / 0 个有效引用**。

因此不能说系统完全不能答；准确缺口是：**“可恢复材料中未命中、无法确定全范围”没有正常的正式结果形态，模型只要选择 no_result 就仍会整次失败。** [prompt.py](../src/trivae/query/runtime/prompt.py) 又明确要求工具回答的 sources 非空，模型在这个状态缺少清楚的合法出口。

完整空范围的 no_result 正证明应该保留。可按真实失败建立不完整空检索的调查结果契约，让 Host 已知的范围、0 命中及缺口成为可表达的观察事实；不要通过声称 coverage complete 或伪造消息来源消除错误。应同时验完整空窗、缺转发空检索和实际有命中的控制，不必扩大成一般 fallback 系统。

## 6. 当前检索契约边界：多词夹单字与 ASCII 词内片段

完整 keyword 为单个汉字的召回已经修好。本轮新的组合对照：`github.com 荐` 的 FTS 命中为 **0**；仅主表就有 **19** 条同时包含字面 `github.com` 和 `荐` 的消息。

根因在 [sqlite_read.py](../src/trivae/data/storage/sqlite_read.py)：只有整个查询恰好是一个 Han 单字时才使用单字索引；混合 AND 的单字仍落在 bigram 索引。这是已记录但仍有效的能力边界，不能把“单字已修”理解为所有组合也已支持。

ASCII 词内前后缀（如 GitHubeducation 中搜 GitHub）也仍是 exact-token 边界。这里不建议直接引入 LIKE、改 BM25 或全面改为子串搜索。先确认这种用户查询是否值得支持；若推进，保留非单字排序与真实范围/转发语义，用少量实际查询验证即可。

## 7. 真实失败仍无法归因：AnswerDeltaParseError

10-21 Written B 的真实失败仍保存在原 Trace。当前复核可见两次正常 `model.output`、随后第三次调用发生 `AnswerDeltaParseError`，没有失败正文或解析位置可供重放。

后续 Collector 的轮次高估、Usage 漏计已经修复。修好了统计不等于修好了这次坏 JSON 的根因。现在无法区分 Provider 输出非法字符、跨 turn 状态问题或增量 parser 缺陷；也不能从后来 Plan 正常结束推断旧失败已被定位。

最有价值的工程工作是保留失败位置、当前响应/turn 身份、有限的正文上下文及终态传输事实，使下一次失败可以重放。只采集公开正文，不采集隐藏推理或凭证。原错误继续显式失败，不加 JSON 修复、兼容解析或无依据重试。现有合法/非法 JSON 单测通过，只证明已覆盖形态。

## 应做的少量真实实验

1. **当前模型的检索质量复验。** 优先原笔试题，再看 Webnovel、实习难点；求职焦虑题的最近专门证据更旧，作为后续候选。先判断有没有等价材料满足核心问题，不把旧 target 少一条自动判错。用已修 owner/反问题作控制，避免修了发现题又损害观点覆盖。
2. **结论与来源绑定检查。** 取 Nanobot 数字、Matt 人物、Archify 概述各一题，按正式段落绑定读原文。先核查当前答案是否还有同类错误，再决定最小改动；保留 Assistant 审查与人工审核的区别。
3. **广泛主题的召回和答案覆盖。** 167/167 反问词法命中送达不代表全部语义角度进入答案；该次没有语义补查，也只对相关长文做了选择性续读。换一个已有材料但表达分散的主题，检查不同概念、长文尾部、真人/bot 与独立建议是否保留。字数变长不作为通过标准。
4. **6 轮的价值单独验证。** 当前默认 6 轮的 SDK 流程通过；既有全范围同题两组都只用 2 轮。若要研究轮数收益，应在固定 Prompt、数据、总证据池和模型下只改变轮数，并记录是否实际进入额外轮及新增必要证据。不要再次把前三轮策略变化算成第四至六轮收益。
5. **Planner/Router 放在后面。** 最近质量验收主要强制 Standard；历史 SQL-first 风险、Planner 截断及一般 utility 并没有被这些结果覆盖。确有继续使用 Planned 的目标时再做同题配对；不要先扩大为一轮全库 Planner 调参。

先做前三类的少量当前样本，每个关键问题重复两次可以揭示明显波动，但不足以给稳定成功率。全部共享一份冻结数据与索引，独立保存每次答案/Trace/请求账本；不重复复制大库，不覆盖首次失败，不打开已封存 Holdout，也不额外调用 Judge。真正要发布候选时，再补独立新问题和人工审核。

## 不应重复列为当前未修 Bug

- 三题关键回复送达与最终引用：已有确定性回归及真实模型成功。
- 长消息 1000 字之后不可读、尾页引用错位、来源不能展开：已有分页和浏览器验收。
- 中文完整单字检索：已有独立索引及真实 parity；本轮保留的是组合查询边界。
- SQL 永久计算：5 秒 VM 中断已修；本轮新发现的是调度阻塞。
- 时间窗 Schema、密集两天和两周分段份额：已有当前自主验收；partial 不等于 Bug，也不代表覆盖全部热点。
- 前端丢草稿、来源错误无法重读、阅读位置与交错导航：已有失败回归和浏览器修复验收；实体手机键盘、读屏仍待验证。
- 旧 Miner 未命中指定仓库：Plan 已有用途匹配的替代答案，不能仅凭旧 target 直接否定。
- OAuth iat 偏差、旧 Collector 轮次/Usage 计数：已有修复；历史 TLS/ReadTimeout/断流保留为传输失败，不自动推导成应加产品重试。

## 复现与证据入口

新增 [audit_failure_boundaries.py](../scripts/audit_failure_boundaries.py)，全部操作为只读当前库或写临时小库，模型请求为 0。无门禁选项时输出观察结果；以下两个独立门禁在当前产品上**预期 exit 1**，分别锁定真实阻塞与转发正文丢失，不属于完整 pytest 新增失败。

```bash
uv run python -m scripts.audit_failure_boundaries \
  --output data/evaluation/failure-audit-20261023/sql-check.json \
  --require-responsive-sql

uv run python -m scripts.audit_failure_boundaries \
  --output data/evaluation/failure-audit-20261023/forward-check.json \
  --require-forward-enrichment
```

本轮实际保存的观察：`current-probes.json`（SQL 门禁红）、`with-forward-probes.json`（转发门禁红及反向控制）、`forward-enrichment-first-observation.json`、`forward-gap-causes.json`、`forward-gap-variants.json`、`forward-alternate-raw-checks.json`，均位于本地 `data/evaluation/failure-audit-20261023/`。原始正文和完整库存不进入公开报告。

库存重放：`uv run python -m scripts.audit_tool_round_budget --output data/evaluation/failure-audit-20261023/inventory`。另有原笔试 `result.json` 与 Trace、10-20 两份逐题 Assistant review，支持本文历史部分。历史评审仍为 Assistant provisional，不升级为人工通过率。

相关已有报告：[REPAIR_PLAN.md](REPAIR_PLAN.md)、[Evaluation历史失败审计-20261020.md](../interview-docs/Evaluation历史失败审计-20261020.md)、[Evaluation端到端质量实验-20261020.md](../interview-docs/Evaluation端到端质量实验-20261020.md)、[tool-round-budget-20261021/report.md](../evaluation/experiments/tool-round-budget-20261021/report.md)、[broad-advice-20261023/report.md](../evaluation/experiments/broad-advice-20261023/report.md)、[FRONTEND_REVIEW_20261023.md](FRONTEND_REVIEW_20261023.md)。
