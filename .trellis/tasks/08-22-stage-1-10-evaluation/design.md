# Design: Stage 1.10 Evaluation

## 1. Problem Restatement

Trivae 真正需要解决的问题不是“怎样得到更多指标”，而是：

> 当系统修改 Router、Planner、Retrieval、Prompt、Model、Budget 或 Evidence 逻辑后，怎样用相同问题和相同数据证明最终证据型回答真的变好，并能解释改善或退化发生在哪一层。

Evaluation 必须同时满足四个基本事实：

1. 最终价值是用户得到正确、充分、可追溯且不过度断言的回答。
2. 端到端失败可能由多个模块造成，只看最终答案无法定位，只看局部指标又无法证明用户价值。
3. LLM 输出有随机性，单次运行不能可靠代表一个方案。
4. Trivae 当前没有业务实现和真实 baseline，因此本阶段只能冻结评测契约，不能冻结数字结论。

## 2. Responsibility Boundary

### Evaluation 负责

- 保存可复现的 Case 与受控运行条件；
- 连接最终 Answer 质量、Evidence 质量与 Stage 1.9 Trace 事实；
- 执行 deterministic checks、组织人工 review，并允许受治理的 model-assisted review；
- 对相同 Case 的 baseline / candidate 运行做 paired comparison；
- 形成 post-run Diagnosis，并把真实 Failure Case 沉淀为 Regression Case；
- 为参数校准、Experimental 方案和 ADR Reopen 提供证据。

### Evaluation 不负责

- 驱动在线 Query Execution 或成为新的 Workflow Engine；
- 修改、补造或覆盖 Stage 1.9 canonical Trace；
- 在运行时自动修复 Citation、重试 Tool 或决定继续调查；
- 用一个 Judge 分数代替 Ground Truth、人工复核和 Failure Attribution；
- 永久保留全部原始 Trace 或全部聊天正文；
- 在没有 baseline 的情况下发明阈值或最优参数。

### 与其他验证手段的边界

| 手段 | 回答的问题 | 例子 |
| --- | --- | --- |
| Unit / Contract Test | 实现是否遵守确定性契约 | invalid Citation 必须阻止 Finalization |
| Operational Metric | 系统实际发生了什么 | latency、token、Tool Round、partial、error code |
| Offline Evaluation | 相同 Case 下方案质量如何 | Candidate 是否比 Baseline 找到更多关键证据 |
| Online Observation | 真实 workload 分布与新 Failure Case | shadow Route 分布、用户复核发现的遗漏 |
| Regression Gate | 已修复问题是否重新出现 | 某个历史 Chunk Boundary Error 是否复发 |

Operational Metric 可以成为 Evaluation 输入，但本身不自动证明质量。

## 3. Architecture Overview

```text
Evaluation Suite
    └── Evaluation Case Bundle (canonical truth)
            ├── Dataset Snapshot + Data Access Scope
            ├── User Query + Scenario Slices
            ├── Reference Findings / Evidence / Constraints
            └── Review Policy
                         │
                         ▼
                 Controlled Variant
                         │
                         ▼
                    Evaluation Run
            ├── Answer Artifact
            ├── sanitized Trace reference
            ├── operational measurements
            └── deterministic check results
                         │
                         ▼
                 Evaluation Review
            ├── human labels
            ├── optional model-assisted labels
            └── disagreement / confidence
                         │
                         ▼
             Result + Paired Comparison
                         │
                         ▼
              Post-run Failure Diagnosis
                         │
                         ▼
              Failure Regression Set
```

## 4. Canonical Concepts

本阶段确认概念边界，不冻结 Python / JSON / Database Schema 或字段名。

### Evaluation Case Bundle

一条端到端评测事实的最小单位。它至少表达：

- 稳定 Case identity 与版本；
- 固定 Dataset Snapshot identity；
- Data Access Scope 与 Query-specific context；
- User Query、locale、time context 与场景标签；
- Reference Findings：回答应覆盖的关键事实或调查维度；
- Reference Evidence：已知 relevant Message / Structured Result，以及 relation；
- Negative / uncertainty constraints：禁止断言的内容、证据不足时应保留的不确定性；
- 可选 Route / Planner / Retrieval diagnostic reference；
- Review policy 与 critical requirements。

Case Bundle 是 canonical truth。Router、Planner、Retrieval、Evidence、Citation 与 Answer 的 module evaluation 都从同一 Case 派生，不建立互不关联的质量事实源。

纯模块边界输入仍可作为 Unit Test、Contract Test 或 Diagnostic Fixture；它们不冒充端到端质量 Case。

### Evaluation Suite

一组固定 Case version 的清单。第一版区分：

- **Design / Seed Cases**：用于解释场景与架构，不产生 gate，不伪装成已标注 Benchmark；
- **Core Evaluation Set**：覆盖代表性真实 workload，用于稳定的方案比较；
- **Failure Regression Set**：来自已复现真实 Failure Case，默认只增不删；
- **Calibration Slice**：从前两类按某个参数问题选出的视图，不复制 Case Truth。

当数据规模足以支持时，Core Set 可以再分 development / holdout，防止围绕公开 Case 过拟合；本阶段不规定样本数与比例。

### Controlled Variant

一次实验所使用的完整系统配置 identity，包括与结果相关的 model、prompt、Router / Planner、Tool、Retrieval、index、chunk、budget、Evidence / Citation 和 Runtime 版本或参数。它必须显式记录变化点，不能用“current defaults”这种会漂移的描述作为长期比较依据。

### Evaluation Run

某个 Case + Controlled Variant 的一次真实执行。Run 保存 Answer Artifact、sanitized Trace reference、terminal outcome、operational measurements 与 deterministic check results。

由于模型具有随机性，同一 Case / Variant 可以有多个 Run。具体重复次数由实现成本和观测方差决定，本阶段不写死。

### Evaluation Review

针对一个 Run 的质量复核。Review 与原始 Trace 分离，记录 reviewer 类型、使用的 rubric / judge version、各质量轴结论、简短依据、置信度与 disagreement 状态。

### Evaluation Result / Comparison

Result 是单个 Run 的事实、检查与 Review 聚合。Comparison 是相同 Case / Snapshot 下 baseline 与 candidate 的配对比较，不创建脱离 Case 的总分事实源。

### Failure Diagnosis

Evaluation 后追加或关联的 Root Cause 判断。它可以引用 Trace operation / event 与 Evidence，但不能改写 canonical Trace。允许记录 primary cause 与 contributing factors，前提是有实际证据；无法确定时保持 unresolved。

### Regression Case

由真实 Failure Case 提升而来，保留来源、复现条件、失败表现、Diagnosis、最小修复与修复后证据。Regression Case 继续使用 Case Bundle，不发明第二套格式。

## 5. Ground Truth / Reference Design

### 不使用唯一标准答案文本

群聊分析允许多种正确表达。把一段 reference answer 当唯一 Ground Truth 会把文风差异误判为质量差异，也会鼓励对参考文本过拟合。

Case Bundle 的 Reference 由以下部分组成：

- **Reference Findings**：必须覆盖、可选覆盖或明确不得断言的 finding；
- **Reference Evidence**：已知支持、反驳或提供上下文的 Source；
- **Evidence relevance**：Source 与哪个 finding 相关，而不是只列一堆 Message ID；
- **Uncertainty expectation**：数据或 coverage 不足时，什么内容只能表达为 partial / insufficient；
- **Critical requirement**：违反即使平均分较高也不能接受的行为，例如越权来源或虚构 Citation。

Reference Evidence 不宣称永远穷尽全部正确来源。若标注集不完整，不能机械地把发现新但真实的来源当成 false positive；需要人工确认后更新 Case version。

## 6. Evaluation Layers

### Layer A: Deterministic Contract Checks

适合自动检查且可以作为 hard failure 的内容：

- Answer Artifact 能否按已确认契约解析；
- Citation 是否指向 current-run、Scope 内、可解析的真实 Source；
- unresolved / invalid Citation 是否错误地通过 Finalization；
- Route / Plan / Tool / terminal event 是否满足已确认的生命周期契约；
- Tool status、truncation、partial、coverage limitation 是否被显式保留；
- 运行配置、数据快照与必要 identity 是否足以复现。

Trace incomplete 不自动证明 Answer 错误；但它会使对应 Run 的 Failure Attribution 不完整。评测结果必须显示 `quality result` 与 `diagnosability` 是两个不同轴。

### Layer B: End-to-End User Quality

第一版核心质量轴保持精简：

- **Task / Finding Correctness**：主要结论是否正确，是否回答用户真正的问题；
- **Evidence Completeness**：关键 findings 与调查维度是否有足够 Evidence，是否发生重要遗漏；
- **Groundedness / Entailment**：Claim 是否被所绑 Source 支持，是否忽略反例或上下文；
- **Uncertainty Calibration**：证据不足、coverage partial 或零命中时是否避免过度断言；
- **Answer Relevance**：是否围绕问题组织结果，而不是堆积无关召回内容。

这些轴不机械合成一个“总质量分”。具体评分档位与 rubric 文案在实现时结合真实 Case 校准。

### Layer C: Module Diagnostics

模块指标用于解释端到端结果，不单独宣称用户质量。

#### Router / Planner

- Route confusion、planned precision / recall 与 workload route distribution；
- Planner invocation / invalid / skipped 等事实；
- Missed Dimensions 与 Plan anchoring 等诊断；
- **Planner Utility**：同一 Case 的 planned / standard 或 with / without planner 质量变化，相对于 latency、token 与 Tool Call 成本。

Planner 文本“看起来合理”不是成功条件。如果 Plan 很漂亮但最终 Answer 没改善，Planner 没有证明价值。

#### Retrieval / Context Expansion

- 对已知 relevant sources 的 Recall@K 或 evidence recall；
- 在标注足够完整时观察 Precision@K / ranking quality；
- Lexical Miss、Semantic Miss、Chunk Boundary Error、Ranking Error；
- Context Expansion 是否恢复必要上下文，以及新增噪声 / token 成本；
- query-scope coverage、partial / truncated / unavailable 作为解释条件，不与 relevance 混为一个分数。

如果 Reference Evidence 并不穷尽，Precision 指标只能作为辅助，不能把新发现的真实证据机械判错。

#### Tool / Agent Runtime

- Tool selection / argument correctness、contract error 与执行结果；
- read-only / Scope / bounded contract 是否满足；
- Tool status 和 truncation 是否透明；
- Tool Round、budget finalization、loop failure、unknown exception；
- latency、tokens、Tool Calls、context size 和 compression outcome。

这些多数是 reliability / cost / diagnosis 轴。它们需要与最终质量配对后，才能判断某个预算或机制是否合理。

#### Evidence / Citation

- Finding 与 Evidence relation 是否正确；
- Evidence selection precision / completeness；
- supports / contradicts / context 是否被正确处理；
- Citation precision：Citation 是否真的支持对应 Claim；
- Citation coverage：所有需要外部证据的数据性 Claim 是否都有有效 Citation；
- sufficiency 与 Tool completeness limitation 是否分轴表达；
- criterion quality 是否与用户问题一致。

不定义“每段至少几个 Citation”之类机械密度规则。Citation 数量不等于质量。

## 7. Review / Judge Governance

采用三层机制：

1. **Deterministic first**：能由 identity、Scope、Schema 和 Source relation 确认的内容先自动检查。
2. **Human reference / review**：Ground Truth 建立、争议 Case、关键 gate 与 Judge 校准由人工负责。
3. **Model-assisted review**：可辅助 semantic entailment、finding coverage、相关性与批量初筛，但不能成为不可复核的唯一真相来源。

Model-assisted review 必须记录 Judge model / prompt / rubric version、实际看到的 Query / Claim / Source 范围与结构化结论。Judge 不应看到 baseline / candidate 身份等会造成偏差的无关信息。

以下情况转人工复核：

- Judge 与 deterministic result 冲突；
- 多 Judge / 多次 Judge 结论明显不一致；
- Case 属于 critical gate 或 ADR Reopen 证据；
- 新 Source 不在 Reference Evidence 中但可能真实相关；
- sufficiency、因果关系、讽刺、转述或多人上下文难以可靠判断。

不引入在线 Judge、Evidence Agent 或自动 correction loop。

## 8. Paired Comparison and Stochastic Runs

所有方案比较遵循：

- 相同 Case version；
- 相同 Dataset Snapshot 与 Data Access Scope；
- 相同外部可用能力边界；
- baseline 与 candidate 的差异显式可枚举；
- 同一 Case 上进行配对，而不是比较两批不同问题的平均数；
- 对 stochastic path 重复运行并保留分布 / 稳定性，不用一次 lucky run 下结论；
- timeout、provider failure 或 Trace incomplete 不静默丢弃，单独报告可用性与可评测性。

比较结果优先回答：

1. critical failure 是否消失或新增；
2. 哪些 Case 明确改善、持平或退化；
3. 改善来自哪一层；
4. 质量变化换来了多少 latency / token / Tool Call 成本；
5. 结论是否跨重复运行稳定。

本阶段不冻结重复次数、统计检验、置信区间算法或 promotion 数字。

## 9. Threshold and Gate Policy

### 当前可确认的非数值 Hard Contract

- Scope violation 不可接受；
- 虚构、越权、invalid / unresolved Citation 不可提交；
- 已确认的生命周期与错误透明契约不能为了质量分被绕过；
- Regression Case 中已修复的 critical failure 不应复发；
- Trace / Review 证据不足时不能声称已定位 Root Cause。

### 数值 threshold 的建立条件

只有同时具备以下证据后，才设置某个 numerical gate：

- 固定 Suite 上的真实 baseline；
- stochastic variation 与 evaluator disagreement 的观测；
- 对该 Failure 的业务成本和容忍度；
- threshold 两侧的真实 Failure Case；
- gate 失败后的明确处理，而不是为了通过而 silent fallback。

阈值按质量轴和场景 slice 设置，不用一个全局平均掩盖 planned cases、insufficient-evidence cases 或 critical failures。

Latency、Token、Tool Calls 与成本是约束 / trade-off 轴，不直接等价为质量。优先使用 Pareto 比较：质量更好且成本可接受，或质量持平但成本明显更低。

## 10. Parameter Calibration Contract

Stage 1.10 不替 Stage 1.3–1.9 猜参数，而是确认校准方法。

### Retrieval / Context

- Parent gap、Child chars / messages / token、overlap；
- lexical / semantic candidate pool、top-k、merge / dedup / fusion；
- Message-level 辅助索引与 Reranker 是否值得引入；
- Search 自动 context before / after、Parent expansion 与 Tool Result token budget。

先建立最小 baseline，再由真实 Retrieval Miss、Chunk Boundary Error 或 Ranking Error 触发候选方案。Reranker 和 Message-level index 只有在对应错误成为主导且端到端质量改善时才进入。

### Router / Planner

- Rule / LLM fallback threshold、model、prompt、timeout；
- Plan steps / criteria bounds、intent taxonomy；
- Planner latency / token budget 与 invocation policy；
- Replan 是否有价值。

判断依据是 Planner Utility 与 Failure Case，不是 Route accuracy 或 Plan aesthetics。

### Runtime / History

- Tool Round / SDK turn bounds；
- history window、compression threshold、summary / retention budget；
- Tool concurrency；
- graceful final synthesis 时机。

ChatLab 经验值可以作为标注来源的 baseline。参数增加只有在质量收益超过额外成本和 Failure Attribution 复杂度时成立。

### Evidence / Citation

- bounded source review、Evidence Item / Source 数量与 Citation 展示密度；
- Evidence-aware stopping；
- minimum-citation / coverage gate；
- bounded repair / retry 的进入条件。

第一版继续保持 Evidence-aware stopping 为 Agent guidance。没有真实 Evaluation 证明前，不增加 machine-enforced stopping、minimum citation 数量或 automatic repair。

Machine-enforced stopping 只有在以下条件同时成立时才可重开：

- completion predicate 可由已确认 Artifact / coverage 事实稳定判断；
- false stop 与 unnecessary continue 都有代表性 Case；
- paired evaluation 证明成本下降且关键质量不退化；
- partial / insufficient 与 budget exhaustion 的失败出口保持显式；
- gate 行为可 Trace、可复现、可关闭。

## 11. Failure Attribution and Regression Lifecycle

```text
真实失败
→ 选择并治理必要的数据快照
→ 稳定复现
→ 关联 sanitized Trace 与 Answer Artifact
→ 人工 / Evaluation Diagnosis
→ 确认 primary cause / contributing factors
→ 最小修复
→ baseline / candidate paired comparison
→ 修复成立
→ 提升为 Regression Case
```

Diagnosis label 可以沿用 Stage 1.9 的模块边界，例如 Under-routing、Planner Missed Dimension、Lexical / Semantic Miss、Chunk Boundary Error、Ranking Error、Tool Selection / Arguments Error、Evidence Selection Error、Citation Entailment Error、Answer Generation Error。

Label 不是通过关键词自动猜测。若证据只能说明“Retrieval 没拿到参考来源”，但无法区分 query formulation、index coverage 或 ranking，则 Root Cause 保持 unresolved / multi-candidate。

Regression Case 默认保留稳定 identity 和历史结果。若数据或 Reference 修正，创建新 Case version，并保留旧结果可解释性。

## 12. Privacy, Retention, and Reproducibility

- Evaluation Artifact 是经过独立选择和治理的数据，不通过永久保留全部 Trace 自动获得；
- Dataset Snapshot 必须绑定合法 Data Access Scope；
- Reference Evidence 只保留复现所需的 bounded source 或稳定 locator；
- sanitized Trace、Answer Artifact 与 review artifact 按 Stage 1.9 data minimization 原则处理；
- 删除、权限变化或数据治理要求必须能使对应 Case 失效或产生新 version，不能继续把不可访问 Source 当有效 Ground Truth；
- Evaluation Result 必须能识别 Case、Snapshot、Variant、model / prompt / index / parameter identity 与 evaluator version；
- 不要求把完整聊天正文上传给第三方 Judge；Judge 只获得被允许且完成 privacy projection 的最小输入。

## 13. ChatLab Inheritance / Deviation

### Inherit

- 固定 Case ID、locale / chat type / scenario slice；
- planned case 显式列 expected evidence coverage；
- baseline 在真实环境运行前保持 Pending；
- Route / Plan / Tool / usage / budget 可观察；
- 参数可覆盖，先观察真实 workload 再校准；
- ChatLab Runtime、Chunk、Search context、Compression 与 Evidence budget 数字可作为标注来源的 v1 baseline variant。

### Adapt

- ChatLab 三路 Route 映射为 Trivae 两路 `standard_execution / planned_execution`；
- 静态 Router Case 扩展为绑定 Snapshot、Scope、Findings、Evidence 和 Answer review 的端到端 Case Bundle；
- expected evidence coverage 从 planned-only 描述扩展为所有数据性问题都可使用的 Reference Findings / Evidence；
- shadow-style observation 扩展为受控 paired evaluation 与 Regression lifecycle。

### Do Not Inherit

- 固定关键词 included / excluded Evidence Judge；
- 固定时间 Evidence grouping；
- ChatLab-specific Tool surface 和 Prompt heuristic；
- 24 个 Case 的数量、类别比例或 expected route 作为 Trivae 固定 Benchmark 分布；
- Router accuracy 作为最终成功指标；
- ChatLab 经验参数作为 Trivae 最优值；
- 只有结构测试、没有真实运行的 Evaluation Set 被描述为完成的质量 baseline。

## 14. Failure Cases

| Failure Case | 架构处理 |
| --- | --- |
| 最终答案错，但 Retrieval Recall 很高 | 保留端到端 Answer / Evidence review，继续定位 Evidence Selection 或 Answer Generation |
| 各模块平均分都高，关键 planned case 失败 | 按 Case / slice 报告，critical regression 不被 aggregate average 掩盖 |
| Candidate 单次运行表现很好 | 重复 stochastic run，不用 lucky run 做 promotion |
| Judge 认为 Citation 支持 Claim，但人工不同意 | 记录 disagreement，关键结论转人工，不让 Judge 成为唯一事实源 |
| 找到 Reference 外的新真实证据 | 人工复核并升级 Case version，不机械算 false positive |
| Trace incomplete 但 Answer 看起来正确 | Answer quality 与 diagnosability 分轴；不伪造 Root Cause |
| 为通过 gate 增加 retry / fallback | 禁止；先定位主链路 Failure，恢复机制需真实证据和独立评测 |
| Evaluation Set 被 Prompt 反复针对性优化 | 引入真实 Failure Regression、必要时使用 holdout，不围绕单个 Case 写规则 |
| 数据权限变化后旧 Case 仍引用 Source | Case 失效或产生新 version，不继续使用越权 Ground Truth |
| 平均质量略升但 Token / latency 大幅上升 | 以 paired Pareto trade-off 审查，不用单一总分掩盖成本 |

## 15. Confirmed Decision Set for ADR

1. Evaluation 验证真实改善，不是指标展示层。
2. Evaluation 与在线 Query Execution 分离，不成为业务编排层。
3. 端到端 Evaluation Case Bundle 是 canonical truth。
4. 模块评测从同一 Case 派生；纯模块输入属于 Test / Diagnostic Fixture。
5. Case 绑定 Dataset Snapshot、Data Access Scope、Query、Findings、Evidence 与 uncertainty constraints。
6. Ground Truth 使用 Reference Findings / Evidence，不使用唯一标准答案文本。
7. Design Seed、Core Evaluation、Failure Regression 与 Calibration Slice 语义分开。
8. Run 绑定完整 Controlled Variant；禁止依赖漂移的 current defaults。
9. stochastic path 使用重复 Run，具体次数后续校准。
10. Deterministic checks、Human review、Model-assisted review 分层。
11. Model-assisted Judge 不是唯一真相源，关键争议转人工。
12. End-to-end quality 与 module diagnostics 同时保留，但不机械合成单一总分。
13. Router 的最终目标是 Planner Utility，不是 Aggregate Accuracy。
14. Retrieval relevance、query-scope coverage 与 Evidence sufficiency 分轴。
15. Citation precision、Citation coverage、semantic entailment 与 criterion quality 分开。
16. Paired comparison 固定 Case / Snapshot / Scope，只改变显式 Variant。
17. Failure Diagnosis 关联但不改写 Stage 1.9 canonical Trace。
18. 真实 Failure 修复后进入 versioned Regression Set。
19. Hard contract 可先确认；numerical threshold 必须等待真实 baseline、方差与 Failure Cost。
20. 质量与 latency / token / Tool Call / cost 做 Pareto trade-off，不压成一个总分。
21. ChatLab 参数只作标注来源的 baseline seed，不视为 Trivae 最优值。
22. Evidence-aware stopping 第一版继续作 guidance；machine gate / repair / retry 需要独立进入条件。
23. Evaluation Artifact 独立选择与治理，不延长全部 Trace retention。
24. Stage 1.10 不实现 runner、Schema、Dashboard，不伪造 baseline、threshold 或最佳参数。

## 16. Deferred

### Implementation Pending

- Python / JSON / Database Schema 与 package layout；
- Dataset Snapshot 构建、Case authoring、runner、replay 与结果存储；
- Judge adapter、human review workflow 与 UI；
- Trace / Answer Artifact 的具体读取接口；
- baseline / candidate execution scheduling；
- report、dashboard、CLI / API exposure；
- 数据脱敏、权限与 retention 的具体实现。

### Real-run Calibration Pending

- Core / Regression Set 的样本数、slice 比例与 development / holdout 划分；
- 重复 Run 次数、统计方法与 evaluator agreement 阈值；
- 所有质量、latency、token、cost、coverage 与 budget 数值 gate；
- model / prompt / chunk / top-k / fusion / rerank / Tool Budget / stopping 的最终参数；
- 是否引入 Reranker、Message-level index、Specialized Tool、Replan、automatic repair 或 machine stopping。

### Stage 1.11 Pending

- CLI / API / UI 中的 Evaluation 触发、状态、结果、对比与 Source review 体验。

## 17. Reopen Conditions

只有以下证据可以重开本 ADR：

- 真实 workload 证明端到端 Case Bundle 无法承载某类重要模块评测；
- 数据治理要求禁止使用固定 Snapshot，且存在可复现的替代机制；
- 大规模人工复核证明 Reference Findings / Evidence 模型成本不可接受；
- 经过人工校准的自动 Judge 在明确场景达到稳定、低误报且显著降低成本；
- 新业务需求要求在线 audit-grade quality gate，而非离线 Evaluation；
- Evaluation 实现表明 paired comparison 或多次 Run 无法在可接受成本下提供决策价值。

“常见框架都有一个总分”“ChatLab 使用某个默认值”“先定阈值看起来更完整”不构成 Reopen Reason。
