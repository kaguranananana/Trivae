# Trivae 工具轮次预算审计与小规模对照（2026-10-21）

**建议维持生产默认 3 轮。已证实三轮会强制终止继续检索，但尚未证实它是当前答案质量的主要瓶颈；本次五轮配置没有执行第 4、5 轮。** 简历工具题的 B 组恢复了真实缺失证据，但改进发生在前三轮，不能归因为“多用两轮”。Archify 两组均能回答；笔试题 B 组发生独立的流式解析失败。没有修改生产默认、Runtime、原始 GT，实验阶段按要求没有提交或推送；后续用户已授权提交工作区变更。

## 1. 运行机制与可识别边界

源码依据：[openai_adapter.py](../../../src/trivae/query/runtime/openai_adapter.py)、[settings.py](../../../src/trivae/config/settings.py)、[collector.py](../../../src/trivae/observability/collector.py)、[checks.py](../../../src/trivae/evaluation/checks.py)、[metrics.py](../../../src/trivae/evaluation/benchmark/metrics.py)。

- `_RuntimeHooks.on_tool_end` 在同一模型响应的**首个工具结果完成时**将 `tool_rounds` 加一；同一响应的其他工具调用，包括并行调用，不另算轮。工具错误若作为结果返回，也消耗所在轮次。
- 第三轮首个结果完成时设 `finalizing=True`、清除 `agent.tools`；已产生的同轮调用继续完成，全部返回后才广播 `finalizing`。下一次模型调用使用无工具提示进行 Final Synthesis。这是预算强制切换，未评估证据是否充分。
- SDK `max_turns` 计模型调用；一般五次工具响应加一次最终综合共六次模型调用，`max_turns=8` 足够，不能把它误当作五轮配置的必然阻碍。异常、多余模型轮次仍可能触发 `MAX_TURNS_EXCEEDED`，其类别为 `absolute_backstop`。Host Finalizer 是后续确定性校验，不另消耗模型轮次。
- `runtime.finalizing` 带 limitation `tool_budget_exhausted`，是本次强制触顶的直接证据。两者是**同一事件**。终态 `tool_rounds` 与配置上限、实际 `RuntimeToolCall.round` 可交叉核对。`model.turn` / `model.output` 的 `tool_round=4` 常只是三轮之后的综合调用，不能算作第四轮工具。
- 动态 instructions 每轮告诉模型已用/剩余预算；本实验是**工具预算配置的端到端对照**，包含前三轮策略变化，不是额外两轮的严格中介实验。
- 预算触顶、Runtime completed、Host Finalizer 通过、答案事实正确，是四件不同的事。

## 2. 历史审计

只读优先扫描 ignored 的本地 `data/evaluation/`，补充主 Evaluation 库和 `data/traces/`。SQLite 按 run_id 去重，JSON 原始记录按相同身份交叉关联，未增加重复分母。读取 1,537 条唯一运行、1,537 份可关联 Trace；1,534 条可判断工具轮次。另三条在 Runtime 之前失败，轮次 unavailable。没有把 Router/Planner-only probe、模块检索测试或未入 Evaluation 的任意聊天当成 Query 分母。

来源构成为旧 OpenCode Go / `deepseek-v4-flash` 1,244 条、官方 DeepSeek / `deepseek-flash` 233 条、ChatGPT plan / `gpt-6.1-sol` 60 条。封存 Holdout 的两个 Evaluation 库未打开内容，未选用 Holdout。最初文件库存预检只读取过它们的 suite/variant 行数；后续内容审计与选题均排除。其他遗留 JSON-only、Planner-only 实验不冒充完整 Query 历史。

库存轮次构成：0轮 272（17.73%）、1轮 752（49.02%）、2轮 344（22.43%）、3轮 166（10.82%），比例分母 1,534。**这不是生产总体分布或成功率**：237 条零轮运行在 Runtime 失败后跳过 Finalizer；零轮不代表证据已经充分。以下批次、Provider、模型和 Variant 分开分析。

完整 167 个分组的数量、比例、触顶率、事件和失败分解见 [history-groups.md](history-groups.md)，机器可读见 [history-summary.json](history-summary.json)。下表列最相关的正式批次；每格分布顺序为 0 / 1 / 2 / 3 轮。

| 批次 / 执行版本 | Provider / 模型 | Variant | 可分析 | 轮次分布 | 3/3触顶 | 触顶后交付 / Finalizer失败 / 其他失败 |
|---|---|---|---:|---|---:|---|
| 历史基线 `7bac928` | opencode-go / deepseek-v4-flash | lexical-only | 37 | 12 / 18 / 6 / 1 | 1（2.70%） | 1 / 0 / 0 |
| 同批 | 同上 | lexical-semantic | 37 | 0 / 29 / 7 / 1 | 1（2.70%） | 1 / 0 / 0 |
| 同批 | 同上 | semantic-ctx | 37 | 1 / 25 / 8 / 3 | 3（8.11%） | 3 / 0 / 0 |
| 同批 | 同上 | semantic-ctx-tool | 37 | 0 / 27 / 7 / 3 | 3（8.11%） | 3 / 0 / 0 |
| 同批 | 同上 | full-system | 37 | 0 / 23 / 7 / 7 | 7（18.92%） | 7 / 0 / 0 |
| Gate3 `8805aa2` | opencode-go / deepseek-v4-flash | lexical-only | 37 | 20 / 9 / 6 / 2 | 2（5.41%） | 2 / 0 / 0 |
| 同批 | 同上 | lexical-semantic | 37 | 19 / 12 / 6 / 0 | 0 | 0 / 0 / 0 |
| 同批 | 同上 | semantic-ctx | 37 | 0 / 21 / 10 / 6 | 6（16.22%） | 6 / 0 / 0 |
| 同批 | 同上 | semantic-ctx-tool | 37 | 1 / 27 / 9 / 0 | 0 | 0 / 0 / 0 |
| 同批 | 同上 | full-system | 37 | 0 / 21 / 11 / 5 | 5（13.51%） | 4 / 1 / 0 |
| Planner Utility `f94fffb` 正式Development | deepseek / deepseek-flash | forced-standard | 37 | 0 / 16 / 6 / 15 | 15（40.54%） | 15 / 0 / 0 |
| 同批 | 同上 | forced-planned | 37 | 0 / 10 / 8 / 19 | 19（51.35%） | 18 / 1 / 0 |
| 10-20质量实验 Development `8def8d7` | deepseek / deepseek-flash | quality:baseline | 8 | 0 / 3 / 5 / 0 | 0 | 0 / 0 / 0 |
| 同批 `3d9cc0e` | 同上 | quality:candidate | 8 | 0 / 3 / 5 / 0 | 0 | 0 / 0 / 0 |

原始 Variant 的 `code_version` 在部分旧实验中滞后；本表使用对应 raw report 的 `environment.git_commit`，两者都保留在私有审计中，不把所有旧运行误标成 `70e1b473`。

全库存观察到 166 个 `runtime.finalizing`、166 个 `tool_budget_exhausted` 标记，均为三轮触顶。只作库存清点：其中147次交付（137 valid、10 degraded），14次 Host Finalizer失败，5次 Runtime失败；**不据此合成跨批次质量成功率**。

质量关联也按批次区分：

- 基线 full-system 7次触顶中4次有可用的固定证据 Recall，其中2次不足（resume-miner、resume-advice）；semantic-ctx-tool 为2/3不足；semantic-ctx 为1/3不足。另有 meimei、siclaw、lofisu、agentic-zh 等用满三轮且固定目标全部覆盖的样本。
- Gate3 full-system 为2/3不足（ai-interest、webnovel），另1次 temporal-14d 被 Finalizer拒绝；lexical-only 两个触顶样本均不足，其中 mattpocock-1 为 Evidence 1/2、Context 0/1；semantic-ctx 为1/5不足。比例只针对触顶、成功交付、有相应GT的子集。
- 9-25 forced-standard 为7/12不足，forced-planned 为6/11不足。不能拿 Planned 的高触顶率证明提高预算有效；Plan、Prompt和工具路径同时不同。
- 最近10-20正式20题：baseline 1次触顶（written-test，1/1目标已取得）；candidate 2次（webnovel 0/1、zero-empty-2 Finalizer失败）；四次复测另有candidate miner触顶且0/4。完整原始工具结果可确认 miner / webnovel 固定目标未返回，无模型可见投影裁剪；这两次有真正的检索侧目标缺失。历史多数 normal Trace 仅存前50个候选及裁剪文本，无法给出可靠的全历史 Retrieval Miss 数量。

## 3. 典型 Case 与瓶颈分类

| Case / 证据来源 | 客观观察 | 分类与证据强度 |
|---|---|---|
| dev-temporal-14d，基线full-system | 连续3轮按cursor取100条，覆盖300/28,028、has_more=true，随即强制综合；最终Artifact valid | **疑似工具预算瓶颈**。已证实预算阻止继续翻页，尚未证实答案事实因此变差；五轮按同策略也只约500条，不能解决完整窗口覆盖 |
| dev-lexical-resume-miner，9-25 standard及10-20复测 | semantic后查宽泛词，最后一轮仍用于无关候选/版式讨论，最终0/4；10-20完整结果没有目标、没有Host投影省略 | **疑似检索策略问题，可能受预算约束放大**。数据库中确有具名工具及功能说明；没有发现“最后一轮刚找到 miner、只差下一轮”的直接证据 |
| dev-context-archify，9-27 v3 standard focus-r2 | 第1轮 lexical取得anchor；第2轮把短handle放进message_id，两个MESSAGE_NOT_FOUND；第3轮改source_id成功扩展，却扩展了其他消息，最终Evidence 1/2、Context 0/1 | **疑似检索策略/调用参数问题**。修正调用占用一轮，但选错anchor仍是独立原因；不能直接称三轮导致。当前Snapshot中目标回复确实存在并指向原anchor |
| dev-context-mattpocock-1，Gate3 lexical-only | 三轮lexical但没有必需回复，Evidence 1/2；该Variant工具面只有lexical | **疑似检索策略/工具面限制**。增加轮数不会自动获得不存在于此工具面的context能力 |
| dev-para-written-test，10-20 baseline | semantic→lexical→context，1/1目标进入最终Evidence；投影无省略 | **其他：充分证据对照**。触顶没有表现为固定GT损失 |
| Gate3 temporal-14d、最近zero-empty-2 | Runtime completed但Finalizer失败 | **其他质量/输出契约问题**。不作为预算实验首选，不把无可交付答案当证据不足案例 |
| normal Trace候选摘要裁剪、仅知最终漏目标的其他运行 | 无完整工具返回/可见上下文可重放 | **无法判断**召回、选据与裁剪的单点因果，不能用“摘要没看到”证明未检索 |

历史Archify及当前六次运行都没有相关Host投影省略的证据。工具自身Top-K/自动邻居窗口、Tool Result的Token裁剪、Trace序列化裁剪必须分别判断；索引支持整库不等于本次已读取整库。

## 4. 实验选择、固定条件与费用边界

选自已暴露的 Development GT：

| 新Case身份 | 原GT及选择理由 |
|---|---|
| budget-dev-lexical-resume-miner | 原dev-lexical-resume-miner；4条相关消息、expected fact为具名仓库。历史触顶且遗漏，测试多阶段工具发现 |
| budget-dev-context-archify | 原dev-context-archify；1条分享anchor及1条明确“好用”的回复。历史standard触顶且缺上下文，测试跨消息恢复 |
| budget-dev-para-written-test | 原dev-para-written-test；1条明确自构造简历测试集的笔试经历。10-20三轮已充分，作为对照 |

GT均为partial，**不是全库穷尽答案**。新Case只改记录身份，reference_findings、query、scope等保持原10-20副本内容；原文件未改。独立Snapshot含811,892条canonical、14,119条forward occurrence、98,012个semantic chunk；7条固定GT目标均存在。索引为同一Qwen3-Embedding-0.6B本地索引，canonical/index revision均46,112，没有重建索引或新增Provider embedding费用。

当前工作版本 `de17d71`，产品源码无本任务改动；基础Prompt、七工具schema、单次输出16,384、dynamic单次Tool Result上限128,000、run evidence pool250,000、max_turns=8保持一致。强制Standard，Router/Planner不额外调用。实际conditions逐字段对比，仅允许max_tool_rounds 3→5及对应动态预算句变化。每次Query新建对话，共用固定副本。顺序为 miner A→B、archify B→A、written-test A→B。

免费 `/models` 预检200，含deepseek-flash；SDK retries=0。首次付费前落盘protocol、conditions、执行顺序；预定6次Query、全局HTTP上限36。官方当前模型目录将别名指向V4.1-Flash-1017，但Provider别名不是不可变服务版本，不能保证历史同名运行完全同权重。

官方[价格页](https://api-docs.deepseek.com/quick_start/pricing/)核对于2026-10-21：峰时每百万Token未缓存输入$0.30、缓存输入$0.006、输出$1.20，非峰时减半。预检最坏36次占满1M输入及16,384输出约$11.51，历史用量预计不足$1。实际20次模型HTTP，6次Query，无重试、无补跑、无付费Judge。HTTP200表示请求已接受，不能当作答案成功。

## 5. 逐Case结果

延迟为原生Query latency；Token列为输入 / 输出 / 缓存输入。最后一行只有已完成两次响应的用量下界。

| Case / 组 | 实际工具轮 / 调用次数 | 去重返回消息 | GT返回 / 最终Evidence | 状态 / 引用provenance | 延迟秒 | Provider Token | 按公价估费USD |
|---|---|---:|---|---|---:|---|---:|
| miner A：3轮 | 3 / 4 | 189 | 0/4 / 0/4 | completed_degraded；删1个无效来源 | 105.03 | 120,572 / 2,698 / 29,056 | 0.01543 |
| miner B：5轮 | 3 / 6 | 295 | 4/4 / 4/4 | completed；provenance通过 | 128.84 | 187,636 / 4,489 / 16,384 | 0.02843 |
| archify A | 2 / 3 | 142 | 1/2 / 0/2 | completed；provenance通过 | 18.79 | 65,639 / 2,404 / 24,960 | 0.00762 |
| archify B | 2 / 4 | 173 | 1/2 / 0/2 | completed；provenance通过 | 22.68 | 70,539 / 2,551 / 24,960 | 0.00844 |
| written-test A | 2 / 2 | 133 | 0/1 / 0/1 | completed；provenance通过 | 89.60 | 66,201 / 2,069 / 24,960 | 0.00750 |
| written-test B | **2 / 4**；原终态误记3轮 | 172 | 0/1 / 无最终答案 | failed：AnswerDeltaParseError | 90.55 | ≥46,210 / ≥989 / ≥16,640 | ≥0.00508 |

原始身份、逐轮新增量、原生确定性指标和ReviewPacket在本地独立目录 `data/evaluation/tool-round-budget-20261021/`；脱敏逐题数字见 [comparison-summary.json](comparison-summary.json)。失败无Artifact，表中的“无最终答案”不能读成可评答案的0%事实正确率。

**证据和事实判断（Assistant非盲核对，无新增LLM Judge，也非独立人工裁决）：**

- **miner：本次B明确优于A的核心覆盖。** A第三轮只对版式工具候选扩上下文，未找到具名目标，结论仍偏否定；而Snapshot里确有该工具。B先并行两次semantic，第二轮扩展两个上下文，第三轮并行查“简历 github.com”“简历 skill”，恢复4条GT并在claim-1正确使用仓库、STAR、可读仓库、实习/开源等事实。B比A多202条不同消息，但只有4条可按固定GT验证；不能把202全算质量增益。B的“提到最多”等总体比较未经计数，“造轮子/白嫖”也不是实际效果评测；不宣称所有句子完全正确。A的第8段还因无效来源被删去绑定，正文仍保留，provenance degraded没有修复核心检索遗漏。
- **archify：未出现可证实的预算质量提升。** 两组都未取得旧GT那条“好用”回复，最终固定目标都0/2、Context Recovery均0/1；但新快照中两组均取得并引用了其他真实试用、格式统一、解释不细、耗时/费用等反馈，核心问题可回答，不能把0/2直接当内容失败。B多61条不同消息，未增加固定GT覆盖；两组都只用2轮。A有少量话题概括超出绑定节选，B也没有穷尽所有反馈，暂不判定全答案胜负。
- **written-test：历史充分对照这次未稳定复现。** A在两轮后自行收束，只找到隐藏用例/空数据库等相近话题，漏掉确有的自构造测试集经历；因此“格式valid”不是核心回答正确。B也未取得目标，随后解析失败，不能评其最终事实或引用支持。它没有消耗完5轮，不能说预算不足导致失败，也不能证明5轮配置稳定引起该解析错误。
- **没有任何B执行第4、5轮工具。** 所有新增来源均来自前三轮策略差异，额外两轮的有效证据增量为“未被使用，无法评估”，不是已经验证为零收益。没有可证实的相同参数原样重复调用；B三题均返回更多消息，也增加了前两题Token与延迟，不能只看召回数量宣称有效。

## 6. 失败与计数/成本局限

written-test B在第三次模型调用的正文增量阶段抛出AnswerDeltaParseError。`streaming.py` 的增量parser会显式拒绝非法JSON；原始坏字符没有持久化，不能从现存Trace判定是Provider错误JSON、跨turn文本状态还是parser缺陷。未重新付费复现，未增加兼容或fallback。

**已证实的观测缺陷**在 `collector.py`：observer失败时返回 `tool_rounds=max(event.tool_round)`，把下一次模型调用的编号算进已耗工具轮；`usage=last_usage`只取最近单次usage。这次原终态为3轮、1次usage，实际4个工具均属于前2轮，Trace有2个完成响应的usage；第三次HTTP已发出但响应未完整消费，usage未知。已用零费用合成事件经过真实parser/Collector复现这两个字段问题；它只复现统计缺陷，不冒充重放真实坏字符。脚本及结果保存在独立私有目录。

六次合计19个可见完整响应：已观测费用按非峰时价约 **$0.07251**；剩余一次按1M输入+16,384输出保守计，全部费用公价估算区间约 **$0.07251～$0.23234**。**Provider货币账单未返回，实际精确扣费unknown**。不可将终态usage简单相加后声称已核清账单。事先最坏边界与事后观测区间不是同一种数值。

历史另有两条ChatGPT/UserError终态轮次与已导出工具事件不一致；保留原始值和冲突标记，没有套用此次parser错误结论去改写历史。

## 7. 根因判断与建议

| 结论强度 | 本次可支持的结论 |
|---|---|
| **已证实** | 三轮会强制无工具综合；历史有触顶且漏GT，也有触顶且充分；长时间窗三次分页被预算截住；本次miner B恢复并使用真实缺失GT；本次B无第4/5轮；新增解析失败及失败统计字段缺陷真实存在 |
| **初步支持** | 预算配置能影响前三轮检索选择，miner本次覆盖改善与B配置相关，但不能排除单次抽样随机性；检索词、候选选择、短handle参数、充分性判断是比统一加轮数更直接的改进方向 |
| **证据不足** | 三轮是普遍答案质量瓶颈；额外第4/5轮能带来有效证据并被正确使用；五轮能提高总体质量/泛化表现；B稳定更差或更好；解析失败的底层JSON根因 |

建议保持默认3轮，优先处理已暴露的调用参数/候选选择、漏据后的充分性判断，以及失败观测字段问题。长时间窗应采用匹配问题的聚合或分层检索，避免靠多两页宣称完整覆盖。5轮可以保留为显式实验配置；当前没有证据支持统一提升或新增自动预算策略。本次不实现这些建议，不自动扩到37题、不补样本或重试。

样本为3道已暴露Development题、每侧仅1次，不能估计随机误差或统计显著性；运行顺序交替仍不能消除缓存、冷启动和服务波动。历史模型/Prompt/索引多次变更、GT多为partial、normal Trace裁剪、Provider别名可变、失败响应usage不完整，均限制归因。**当前最稳妥的答案是：三轮可能限制部分继续调查，但未证实偏少；五轮尚不值得统一采用。**

## 复核入口

- 历史审计：`scripts/audit_tool_round_budget.py --output data/evaluation/tool-round-budget-20261021`（零模型费用）。
- 实验执行器：`scripts/run_tool_round_budget_experiment.py`，输出create-only；本次已经跑完，**不要为复核再次执行付费脚本**。
- 离线分析：`scripts/analyze_tool_round_budget_experiment.py`（零模型费用）。
- 独立私有目录保留：protocol、conditions、selection、provider-preflight、HTTP账本、6份QueryResult、Evaluation/Conversation/Trace、Case副本、Snapshot、逐轮统计、ReviewPacket、失败计数复现。
- 验证：Ruff三脚本通过；相关预算/并行计数/max-turns/解析错误测试通过，详细计数见开发日志。没有修改生产逻辑，不宣称完整产品回归已通过。
