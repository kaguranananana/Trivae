# Stage 1.10：Evaluation / Regression 架构决策

> 状态：**Confirmed / Completed（Stage 1.10，架构契约）**
>
> 本 ADR 冻结 Evaluation 的事实边界、Case / Reference / Suite 语义、Baseline 与 Controlled Variant 身份、paired comparison、Judge governance、Failure Diagnosis 与 Reproducibility contract。它不实现 runner、CLI、Dataset storage、Evaluation Schema、真实 baseline、数值 threshold 或参数校准结果。实现与真实运行属于后续 Implementation / Real-run Calibration；Evaluation 触发、结果展示与用户交互属于 Stage 1.11。

---

## 0. Architecture Governance 与承接边界

本阶段遵循项目级 [ChatLab as Reference Implementation](../architecture.md#architecture-principle-chatlab-as-reference-implementation) 原则，并承接 Stage 1.1–1.9 已确认的边界：

- Router 只负责 `standard_execution / planned_execution` 的执行复杂度判断；两条路径使用同一个 Agent Runtime。
- Planner 是进入 Runtime 前的一次性、bounded、soft guidance，不拥有 Workflow、Step Executor 或执行状态。
- Retrieval Candidate 不等于 Final Evidence；Evidence、Citation、Answer Finalization 是独立边界。
- Data Access Scope 是 Tool / Capability 的硬边界；query filter、retrieval coverage、Tool partial 与 Evidence sufficiency 不互相伪装。
- Stage 1.9 Trace 是 append-only 的运行事实；Evaluation 可以引用它，但不能改写、补造或覆盖 canonical Trace。

Stage 1.10 只回答“如何用相同问题、数据条件和受控配置证明真实质量变化，并定位退化原因”。它不把在线 Query Execution 变成评测编排层，也不把一个 Judge 分数当作唯一真相。

## 1. Context：为什么需要独立 Evaluation 架构

最终价值是用户获得正确、充分、可追溯且不过度断言的回答。单看最终回答无法区分 Retrieval、Planner、Runtime、Evidence 或 Citation 的根因；单看局部 operational metric 又不能证明用户价值。LLM 与外部服务具有随机性，单次 Run 不能代表 Variant；而 Trivae 当前还没有业务实现和真实 baseline，因此本阶段只能冻结可验证的架构契约，不能伪造数字结论。

Evaluation 与其他验证手段的边界如下：

| 手段 | 主要回答的问题 |
| --- | --- |
| Unit / Contract Test | 实现是否遵守确定性契约，例如 invalid Citation 必须阻止 Finalization |
| Operational Metric | 运行实际发生了什么，例如 latency、token、Tool Round、partial、error code |
| Offline Evaluation | 相同 Case、Snapshot、Scope 下哪个 Variant 的回答质量更好 |
| Online Observation | 真实 workload 分布和新的 Failure Case 是什么 |
| Regression Gate | 已修复的历史 Failure 是否再次出现 |

Operational Metric 可以作为 Evaluation 输入，但不自动证明质量。

## 2. Responsibility Boundary

### Evaluation 负责

- 保存可重建的 Case、Dataset Snapshot、Data Access Scope 与 Controlled Variant 条件；
- 把 Answer、Evidence 质量与 Stage 1.9 Trace 事实关联起来；
- 先执行 deterministic checks，再组织人工和受治理的 model-assisted review；
- 对相同 Case 做 baseline / candidate paired comparison，并支持 stochastic 重复运行；
- 形成不改写 Trace 的 post-run Diagnosis；
- 将真实 Failure Case 沉淀为 versioned Regression Case；
- 为参数校准、Experimental 方案和 ADR Reopen 提供证据。

### Evaluation 不负责

- 驱动在线 Query Execution、修复 Citation、重试 Tool 或成为 Workflow Engine；
- 在没有 pinned baseline 与真实方差前发明 numerical threshold；
- 用总分隐藏 critical failure、Reference 不完整性或 diagnosability 缺失；
- 永久保留全部 Trace 或绕过删除、撤回授权和权限变化；
- 把 ChatLab 的静态 Case 数量、Route label 或经验参数伪装成 Trivae Benchmark。

## 3. Decision 1：Evaluation Case Bundle 是 canonical truth

### Decision

端到端 Evaluation 的最小事实单位是 **Evaluation Case Bundle**。所有 Router、Planner、Retrieval、Evidence、Citation 与 Answer 的模块评测都从同一 Case 派生，不能各自建立互不关联的质量事实源。

Case Bundle 在语义上至少包括：

```text
Case Bundle
├── stable case identity + version
├── Dataset Snapshot identity
├── Data Access Scope + query-specific context
├── user query / locale / time context / scenario tags
├── Reference Findings[]
│   ├── finding-specific criterion / expected semantics
│   ├── Reference Evidence + relation
│   ├── annotation completeness: exhaustive | partial | unknown
│   └── finding-level provenance / limitations
├── uncertainty / negative constraints / critical requirements
├── optional route hypothesis / planner diagnostic references
└── review policy / rubric reference
```

`annotation completeness` 是 **Finding 级别** 的语义：同一个 Case 可以有一个 `exhaustive` Finding、另一个 `partial` Finding；Case 级别如需汇总，只能是由 Finding 状态派生的摘要，不能覆盖更细粒度的标注。`route hypothesis` 也是可选诊断信息，不是必须填写的 `expectedRoute`，更不是 Gate。

纯模块输入可以是 Unit Test、Contract Test 或 Diagnostic Fixture，但不能冒充端到端质量 Case。

### Reason 与 Trade-off

同一 Case 才能让“最终回答退化”与“对应证据是否缺失、Scope 是否受限、Router 是否选错路径”使用同一事实背景。Bundle 比单一标准答案复杂，但可以表达群聊调查的多种正确措辞、反证、限制和不确定性。

## 4. Decision 2：Reference 不使用唯一答案文本，并保留完整度与来源

### Decision

Ground Truth 由多个 Reference Finding 组成；每个 Finding 绑定自己的 criterion、Reference Evidence、Evidence relation、annotation completeness、provenance、Uncertainty expectation 与 Critical requirements，不以一段 reference answer 作为唯一标准文本。

`annotation completeness` 必须针对具体 Finding、Snapshot、Scope 与 criterion 记录，概念语义固定为：

- **exhaustive**：在明确 Snapshot、Scope 和 criterion 内，由完整查询、人工穷举或可说明的可靠流程建立；Precision / Recall 可以较强解释，但只限于该边界。
- **partial**：只标注代表性或已知 Evidence；命中已知集合有意义，但 Reference 外真实 Source 不机械算 false positive，Recall 只解释为对已知集合的覆盖。
- **unknown**：无法判断完整度；用于定性 review、Finding Correctness 与 Failure Discovery，不从 Reference Set 得出强 Precision / Recall 结论。

`exhaustive` 不表示对现实世界绝对穷尽，只表示在当前 Snapshot、Scope 与 criterion 内有明确的穷尽依据。

每个 Finding 的 Reference provenance 至少说明建立者或建立流程、建立时间、使用的数据与 Scope、是否经过独立人工 adjudication、适用边界、已知限制和 completeness 依据。Reference 自身可能出错；发现新 Evidence 或标注错误时创建新 Case version，保留旧 Result 的历史解释。

Precision / Recall 应按 Finding 或一组 completeness 兼容的 Finding slice 报告。不能把一个 Case 内 `exhaustive`、`partial`、`unknown` 混合成一个强总体 Precision / Recall；partial / unknown Finding 的 Reference 外新 Evidence 进入人工复核，而不是直接判错。

例如同一个 Case 可以同时包含：

```text
F1：明确列出最近分享的仓库链接 → exhaustive
F2：总结半年态度变化 → partial
F3：判断某个观点是否从未出现 → unknown
```

这三个 Finding 必须分别评审和报告，不能用 Case 的一个 `completeness = partial` 抹平 F1 的穷尽性，也不能用 F1 的 exhaustive 标注替 F2 / F3 提供强 Recall 解释。

## 5. Decision 3：Suite 分层，Core 通过版本刷新

第一版区分以下 Suite 语义：

| Suite | 用途 | 是否直接产生质量 Gate |
| --- | --- | --- |
| Design / Seed | 验证架构能表达 Trivae 场景、Reference、forced path 和 Failure Attribution | 否 |
| Core Evaluation | 覆盖代表性真实 workload，用于稳定方案比较 | 后续由真实 baseline 校准 |
| Failure Regression | 由已复现真实 Failure Case 提升而来，默认只增不删 | 可形成 critical regression contract |
| Calibration Slice | 按具体参数问题从前两类派生的视图 | 否，不复制 Case Truth |

Core Set 不是一次建立后永不变化。真实 workload distribution、用户问题形态和新 Failure 出现后，应创建新的 **versioned Suite**；历史 Suite composition 与历史结果继续保留，不能用新清单覆盖旧结果。本阶段不规定刷新周期、采样比例、重加权方法或 development / holdout 比例。

## 6. Decision 4：Baseline 是 pinned Controlled Variant

一次实验必须绑定完整的 Controlled Variant identity，包括与结果相关的 model、prompt、Router / Planner、Tool、Retrieval、index、chunk、budget、Evidence / Citation、Runtime 版本或参数。禁止用 `main`、`production` 或 `current defaults` 作为长期比较身份。

**Baseline 本身也是完整 pin 住的 Controlled Variant。** Comparison 必须记录 Baseline identity、用途和 Candidate 相对 Baseline 的显式 diff。可以存在不同用途的 Baseline：

- `last_stable`：promotion / regression 的稳定参考；
- `minimal_control`：判断某个机制自身是否带来 Utility 的最小或消融控制；
- `chatlab_derived_seed`：第一版参数启动参考，不自动等于 Trivae stable baseline。

第一版 stable baseline 的实际选择留给实现阶段；“Baseline 必须 pinned、Candidate 必须显式 diff”在本阶段确认。

## 7. Decision 5：Run、Result 与 Failure Diagnosis 分离

一个 Evaluation Run 绑定一个 Case version、一个 Snapshot / Scope 条件和一个 Controlled Variant，保存 Answer Artifact、sanitized Trace reference、terminal outcome、operational measurements 与 deterministic check results。同一 Case / Variant 可以有多个 Run；重复次数由真实方差和成本校准，不在本阶段写死。

Evaluation Review 与原始 Trace 分离，记录 reviewer 类型、rubric / Judge version、各质量轴结论、简短依据、置信度与 disagreement。Evaluation Result 聚合 Run、Checks 和 Review；Comparison 只对同一 Case / Snapshot / Scope 的 Baseline 与 Candidate 做配对。

Failure Diagnosis 是 Run 之后追加或关联的判断，可以记录 primary cause 与 contributing factors，但不能改写 Stage 1.9 canonical Trace。证据不足时保持 `unresolved` 或多候选原因，不以关键词猜测 Root Cause。

## 8. Decision 6：两层质量与模块诊断，不合成单一总分

### Layer A：Deterministic Contract Checks

自动检查并可作为 hard failure 的内容包括：

- Answer Artifact 是否遵守已确认结构语义；
- Citation 是否指向 current-run、Scope 内、可解析的真实 Source；
- invalid / unresolved Citation 是否阻止 Finalization；
- Route、Plan、Tool、terminal event 是否满足生命周期契约；
- partial、truncated、coverage limitation 是否显式保留；
- Case、Snapshot、Scope、Variant 和必要 identity 是否足以重建条件。

Trace incomplete 不自动证明 Answer 错误，但会使对应 Run 的 diagnosability 不完整；quality result 与 diagnosability 必须分轴报告。

### Layer B：End-to-End User Quality

核心质量轴为 Task / Finding Correctness、Evidence Completeness、Groundedness / Entailment、Uncertainty Calibration、Answer Relevance。第一版不机械合成一个总质量分；具体 rubric 档位待真实 Case 校准。

### Layer C：Module Diagnostics

Router / Planner、Retrieval / Context Expansion、Tool / Agent Runtime、Evidence / Citation 的诊断用于解释 Layer B，不单独宣称用户质量。必须分别保留 Retrieval relevance、query-scope coverage、Evidence sufficiency、Citation precision / coverage、contradiction handling、latency、token、Tool Call、budget 和 cost 等轴。

## 9. Decision 7：Planner Utility 先走 forced path，再评价 Router Utility

若直接比较 Router 的最终结果，Planner 是否有用与 Router 是否选对会混在一起。因此同一个 Case 必须先绕过 Router 做 counterfactual：

```text
阶段 A：测 Planner 本身
Forced Standard: Case → Agent Runtime
Forced Planned:  Case → Planner → Agent Runtime

阶段 B：测 Router 的选择能力
Case → Router → standard / planned
与阶段 A 中当前 Planner / Runtime 的 Utility 对照
```

阶段 A 的 Planner Utility 比较质量变化与 latency、token、Tool Call 成本；“Plan 文本看起来合理”不是成功条件。阶段 B 的 Router Utility 只问 Router 能否把当前 Planner 确实有收益的 Case 送入 planned path，同时避免无收益或负收益的过度路由；它不是 Aggregate Route Accuracy。

### Planner Utility 的控制变量

测量 Planner Utility 时，除 Planner 是否介入及其产生的 guidance 外，其他条件必须保持一致：

- 同一 Case version、Dataset Snapshot、Data Access Scope、User Query 与 Reference；
- 同一 Agent Runtime、Model、Prompt、Tool surface、Retrieval / Index / Chunk / Evidence / Citation 版本；
- 同一 budget、timeout、外部能力边界、privacy projection 与输出检查；
- 同一 stochastic run 分层和配对调度；Provider 支持时记录并固定可用的 seed / generation 参数，不支持时保留随机性并比较配对分布。

比较不同 Planner 版本时，Planner 版本是唯一受控变化；比较 Planner on / off 时，唯一的实验变量是是否生成并注入 Planner guidance。任何其他配置变化都必须另建 Comparison，不能把它归因于 Planner Utility。

Planner Utility 绑定被评测的 Planner / Runtime Controlled Variant，不是永久不变的 Case 属性。Planner 或 Runtime 变化后，Router Utility 必须重新对照相应 forced-path 结果。

没有明显 Planner 收益的 Case 不强行规定 `expectedRoute`。它可以只保留 `route_hypothesis = null`，或者记录“待 forced-path 验证”的诊断假设；最终 Route 是否合理由 forced-path Utility、成本和真实结果决定，而不是由预先标签决定。

## 10. Decision 8：Review / Judge 分层，配对质量比较使用 blind pairwise

Review 采用三层机制：

1. deterministic checks 先确认 identity、Scope、Schema 和 Source relation；
2. 人工负责 Ground Truth、争议 Case、关键 Gate 与 Judge 校准；
3. model-assisted review 只能辅助 entailment、finding coverage、relevance 或批量初筛，不能成为不可复核的唯一真相源。

Baseline / Candidate 的质量比较优先使用 **blind pairwise review**：隐藏 Variant identity 和“旧 / 新”标签，随机 A / B 顺序，使用相同 rubric 和相同 Evidence visibility；先完成质量判断，再合并 latency、token、Tool Call 和 cost。Judge 必须记录 model、prompt、rubric version、实际可见 Query / Claim / Source 范围和结构化结论。

Judge 与 deterministic result 冲突、多次 Judge 不一致、Case 属于 critical gate、出现 Reference 外的新真实 Source，或涉及反讽、转述、多人上下文和 sufficiency 争议时，转人工复核。第一版不引入在线 Judge、Evidence Agent 或自动 correction loop。

## 11. Decision 9：Paired comparison 面向真实变化，随机性显式保留

Baseline 与 Candidate 比较必须固定：Case version、Dataset Snapshot、Data Access Scope、外部能力边界和运行条件；唯一变化是 Controlled Variant 的显式 diff。同一 Case 配对比较，不比较两批不同问题的 aggregate average。

Stochastic path 需要多次 Run，保留分布、稳定性和不可用原因。timeout、provider failure、permission change 或 Trace incomplete 不静默丢弃，单独报告 availability 与 evaluability。比较优先回答：critical failure 是否变化、哪些 Case 改善 / 持平 / 退化、改善来自哪一层、质量换来多少成本、结论是否跨重复 Run 稳定。

## 12. Decision 10：Hard Contract 先确认，数值 Gate 延后

当前可以直接确认的非数值 hard contract：

- Scope violation 不可接受；
- 虚构、越权、invalid / unresolved Citation 不可提交；
- 已确认的生命周期与错误透明契约不能为了质量分被绕过；
- Regression Case 中已修复的 critical failure 不应复发；
- Review / Trace 证据不足时不能声称已定位 Root Cause。

数值 threshold 只有在同时拥有真实 pinned baseline、随机方差与 evaluator disagreement、Failure cost、阈值两侧的真实 Case，以及明确失败处理时才可建立。阈值按质量轴和场景 slice 设置，不使用一个全局平均掩盖 planned、insufficient-evidence 或 critical case。Latency、Token、Tool Calls 与 Cost 是约束 / trade-off 轴，不直接等价为质量；优先做 paired Pareto 比较。

## 13. Decision 11：参数校准由 Evaluation 驱动，不在 ADR 猜数字

Stage 1.3–1.9 的参数只进入校准问题清单：

- Retrieval / Context：Parent gap、Child size、overlap、candidate pool、top-k、fusion、dedup、context expansion 与 Tool Result budget；
- Router / Planner：rule / LLM fallback、confidence、timeout、Plan bounds、invocation policy、replan；
- Runtime / History：Tool Round、SDK turn、history window、compression、Tool concurrency、graceful finalization；
- Evidence / Citation：bounded source review、Evidence Item / Source 数量、coverage gate、stopping、repair / retry。

先建立最小 baseline，再由真实 Retrieval Miss、Chunk Boundary、Ranking、Planner Utility、Evidence 或 Citation Failure 触发候选方案。ChatLab 经验参数可以作为标注来源的 baseline seed，但不自动等于 Trivae 最优值。Evidence-aware stopping 继续是 Agent guidance；machine-enforced stopping、minimum citation、automatic repair / retry 只有在有代表性 Case、paired quality / cost 证据、显式失败出口且可 Trace 时才可重开。

## 14. Decision 12：Failure Regression 生命周期

```text
真实失败
→ 治理必要的数据快照与 Scope
→ 稳定复现
→ 关联 sanitized Trace 与 Answer Artifact
→ 人工 / Evaluation Diagnosis
→ primary cause / contributing factors
→ 最小修复
→ Baseline / Candidate paired comparison
→ 修复成立
→ 提升为 versioned Regression Case
```

可沿用 Stage 1.9 的模块边界标签，例如 Under-routing、Planner Missed Dimension、Lexical / Semantic Miss、Chunk Boundary、Ranking、Tool Selection / Arguments、Evidence Selection、Citation Entailment、Answer Generation。若无法区分 query formulation、index coverage 或 ranking，Root Cause 保持 `unresolved` / `multi_candidate`。数据、权限或 Reference 改变时创建新 Case version，保留旧结果可解释性。

## 15. Decision 13：Snapshot 可重建，但不绕过数据治理

Evaluation Artifact 是独立选择和治理的数据，不因评测需要永久保留全部 Trace 或聊天正文。Dataset Snapshot 必须绑定合法 Data Access Scope；“固定”表示 Case version 在授权有效时引用不漂移的输入条件，不表示绕过后续删除、撤回授权或权限变化。

删除、权限变化或治理要求发生时，Case 必须失效、受限或产生新 version；不能复制一份当前不可访问的 Source 继续充当有效 Ground Truth。历史 Result 只在治理允许的 metadata 范围内保留。Judge 只获得经过 privacy projection 的最小 Query / Claim / Source 输入。

可复现性的承诺是：输入、Dataset、Scope、Controlled Variant 和 Evaluation 条件可重建，并能进行统计上可比较的重复运行；不承诺远程模型或外部服务半年后 bit-for-bit 相同。应记录可获得的 provider / model / version、运行时间和参数，并报告分布与 limitation。

## 16. Trivae-specific Design Seed Cases

以下 Seed 用来验证 Case Bundle、Reference、forced path、Review 和 Failure Attribution 的表达能力，不是已标注 Benchmark，不产生 Gate，也不冻结 workload 分布。

| Seed | 场景 | 需要验证的重点 |
| --- | --- | --- |
| T-EVAL-001 | 明确事实：最近分享了哪些 GitHub 仓库及作者 | Structured / Message Source、作者与链接事实、Citation coverage；可建立 exhaustive Reference |
| T-EVAL-002 | 长时间趋势：半年内对本地 Agent 框架的评价如何变化 | 多时间窗口、趋势 Evidence、不能把短期噪声写成长趋势 |
| T-EVAL-003 | 多阶段调查：工具从推荐到弃用及替代方案 | 多阶段 Findings；Planner 明显可能有收益 |
| T-EVAL-004 | 身份歧义：“小王”关于 RAG 的观点 | `find_members` 候选、不得混合未消歧的多人消息 |
| T-EVAL-005 | Evidence 不足：五月后是否明显减少 AI 讨论 | coverage / criterion / insufficient，不能过度断言 |
| T-EVAL-006 | 没找到与不存在：是否有人明确否定 PostgreSQL 向量检索 | zero hit、reformulation、query-scope coverage；不能把未找到升级为从未存在 |
| T-EVAL-007 | 冲突 Evidence：先称 bug 已修复，后称仍存在 | `supports / contradicts`、时间顺序、必须综合反例；纳入长期 Regression Core |
| T-EVAL-008 | Chunk Boundary：“这个问题修好了”中的“这个问题”指什么 | Parent / reply context recovery、Context Expansion / Chunk Boundary diagnosis |
| T-EVAL-009 | Planner 无收益：简单链接或资源查找 | forced planned 不应稳定改善质量，却可能增加成本；验证 over-routing |
| T-EVAL-010 | Scope 限制：一个群不在当前授权范围 | Scope hard gate，不得访问越权 Source，限制必须显式 |
| T-EVAL-011 | Reference 外新 Evidence：partial Reference 未列出但确实相关的新消息 | 新 Source 人工复核，不能机械算 false positive |

## 17. ChatLab 的继承、适配与不继承

### 继承

- 固定 Case ID、locale、chat type、scenario slice；Case 可以针对具体 Finding 表达 expected evidence coverage；
- Route / Plan / Tool / usage / budget 可观察；参数可覆盖并先观察 workload；
- ChatLab Runtime、Chunk、Search Context、Compression 和 Evidence budget 数字可作为 `chatlab_derived_seed`，但不是 stable baseline。

### 适配

- ChatLab 三路 taxonomy 映射为 Trivae 两路 `standard_execution / planned_execution`；
- 静态 Route Case 扩展为绑定 Snapshot、Scope、Findings、Evidence 和 Answer Review 的 Case Bundle；
- shadow-style observation 扩展为 forced-path、paired comparison 和 Regression lifecycle。

### 明确不继承

- 固定关键词 Evidence Judge、固定两小时时间聚类、ChatLab-specific Tool surface / Prompt heuristic；
- ChatLab 24 个 Case 的数量、比例、expected route 标签或结构测试结果作为 Trivae Benchmark；
- Router Accuracy 作为最终成功指标；
- ChatLab 经验参数作为 Trivae 最优值；
- 没有真实运行的 Evaluation Set 被描述为已完成质量 baseline。

## 18. Confirmed Decision Summary

1. Evaluation 验证真实改善，不是指标展示层；与在线 Query Execution 分离。
2. Case Bundle 是端到端 canonical truth；模块评测从同一 Case 派生。
3. Case 绑定 Snapshot、Scope、Query、Findings、Evidence 和 uncertainty constraints。
4. Ground Truth 不使用唯一答案文本；每个 Reference Finding 都有自己的 completeness：`exhaustive / partial / unknown`。
5. 每个 Finding 保存 provenance；完整度决定该 Finding 的 Precision / Recall 解释强度，不能被 Case 级摘要覆盖。
6. Design Seed、Core、Failure Regression、Calibration Slice 语义分开；Core 通过 versioned Suite 刷新并保留历史。
7. Run 绑定完整 Controlled Variant；Baseline 必须 pinned，Candidate 必须有显式 diff。
8. stochastic path 使用重复 Run；可复现承诺是条件可重建和统计可比较，不是 bit-for-bit。
9. Deterministic、Human、Model-assisted Review 分层；paired quality review 使用 blind、随机 A/B、同 rubric、同 Evidence visibility。
10. Quality 与 module diagnostics 分轴，不合成单一总分；成本使用 Pareto trade-off。
11. Planner Utility 先 forced standard / planned，再以当前 Planner Utility 对照 Router Utility。
12. Failure Diagnosis 关联但不改写 canonical Trace；真实 Failure 提升为 versioned Regression Case。
13. hard contract 先确认；numerical threshold、参数、runner、Schema、真实 baseline 和 UI 留到后续实现 / 校准。
14. 删除与权限变化优先于复现便利；不能复制越权 Source。
15. ChatLab 只作为架构与 baseline seed 参考，不机械继承其 Judge、Case 分布或最优参数。

## 19. Validation / Regression Contract

在业务实现前，本 ADR 的可验证内容是文档契约一致性，而不是伪造 Evaluation 结果：

- Case Bundle 必须能够同时承载端到端质量、Finding-level Reference completeness / provenance、模块诊断和 Failure Regression 关联；
- 同一 Case 允许不同 Finding 使用不同 completeness；Precision / Recall 只在 Finding 或兼容 slice 上解释，不对混合状态做强聚合；
- 每个 Baseline / Candidate Comparison 必须能指向同一 Case version、Snapshot、Scope、pinned Variant 与显式 diff；
- Planner Utility 的报告必须来自除 Planner 变量外其他条件相同的 forced standard / forced planned 配对，Router Utility 必须引用当前 Planner 的 forced-path 结果；
- 没有明显 Planner 收益的 Case 不要求 `expectedRoute`；route hypothesis 只能是可选、可被结果推翻的诊断信息；
- partial / unknown Reference 不得被文档或未来报告解释为强 Precision / Recall Ground Truth；
- blind pairwise review 必须隐藏 Variant identity、随机 A/B 顺序、固定 rubric / Evidence visibility，并在质量判断后才合并成本；
- Failure Diagnosis 只能关联 Stage 1.9 Trace，不能通过评测结果修改 Trace；真实 Failure 修复后才可创建新的 Regression Case version；
- Design Seed、ChatLab-derived seed、operational metric 或静态结构测试不能被标为真实 quality baseline。

实现阶段应为这些契约补充 Schema / Contract Test、真实 Case、重复 Run、Review agreement、paired report 与 Regression Test；在此之前不生成 pass / fail 数字或最佳参数结论。

## 20. Deferred

### Implementation Pending

- Python / JSON / Database Schema、package layout、Case authoring、Snapshot 构建、runner、replay 与结果存储；
- completeness / provenance、Baseline diff、Snapshot status 的具体字段；
- Judge adapter、人工 Review workflow、Trace / Answer Artifact 读取接口；
- 执行调度、report、dashboard、CLI / API、权限、脱敏、retention 和删除传播。

### Real-run Calibration Pending

- Core / Regression 样本数、slice 比例、development / holdout、Core refresh 周期和 sampling / reweight；
- 第一版 stable baseline 的具体选择、重复 Run 次数、统计方法与 evaluator agreement；
- quality、latency、token、cost、coverage、budget 的数值 Gate；
- model、prompt、chunk、top-k、fusion、rerank、Tool budget、stopping、repair / retry 的最终参数和是否引入。

### Stage 1.11 Application Boundary 已确认；实现 Pending

- CLI / API / UI 中的 Evaluation 触发、状态、结果、对比和 Source review 体验的具体产品交互与实现；Application Boundary、统一 Query execution core 与入口适配原则见 [Stage 1.11 ADR](./stage-1-11-application-architecture.md)。

## 21. Reopen Conditions

只有以下证据可以重开本 ADR：真实 workload 证明 Case Bundle 无法承载重要评测；数据治理禁止固定 Snapshot 且没有可重建替代；大规模人工复核证明 Reference 模型不可接受；经过人工校准的自动 Judge 在明确场景稳定且显著降低成本；新需求要求在线 audit-grade quality gate；或实现证明 paired comparison / 多次 Run 无法在可接受成本下提供决策价值。

“常见框架有一个总分”“ChatLab 使用某个默认值”或“先定阈值看起来更完整”不构成 Reopen Reason。

## 22. Graceful delivery 与 budget calibration amendment（2026-08-26）

Evaluation 必须同时记录 execution delivery 和 answer quality：`completed_degraded`/`degraded`
表示用户拿到了 bounded Answer Artifact，但不表示 citation grounded、claim entailment 或
enumeration completeness 通过。`finalization_status`、`dropped_citation_count`、
`normalization_count` 和 `validated_citation_count` 属于 operational/delivery facts；quality axes
继续由 Case Finding、Reference provenance 和 blind review 判断。

1M context 的 synthetic/real budget comparison 固定比较 fixed 16k、dynamic run pool 128k 和
dynamic run pool 256k（可引用 historical 64k），并同步报告 visible evidence、omission、truncation、
latency、provider usage/成本可得性和 graceful/fatal completion。只有 Retriever 找到、Canonical 保留、
不同预算可见性和最终答案使用情况都被 Trace/Case evidence 支持时，才能把收益归因给 budget；否则归类为
retrieval、enumeration 或 evidence consumption 问题。

## 23. Real Provider paired calibration amendment（2026-08-26）

本轮真实校准把第三个 variant 固定为当前默认 dynamic run pool，而不是继续比较一个显式
`256k` override：`fixed-16k`、`dynamic-run-128k`、`dynamic-default-250k`。相同 4 个 prompt、
3 次 repetition 和 Provider 条件共计划 36 个 cell；每个 cell 120 秒，整个实验 4500 秒。Timeout、
Provider runtime failure 和 completed 必须分开记录，前两者不能进入回答质量分母，也不能被转写成
finalization degraded。

2026-08-26 的 `1m-paired-v2` 真实运行完成 27 个 sample，另有 7 个 cell timeout、2 个 Provider
`SSLError` runtime failure；得到 21 个 pairwise completed comparison 和 6 个完整 triad。fixed
样本发生 3/10 次 model projection truncation，dynamic-128 与 default-250 均为 0；但 dynamic
run pool 在 completed sample 中都没有绑定，且 Retrieval 多次保持 partial/truncated。因 4 个真实
Case 尚无 exhaustive Reference Findings，本轮只能结论为“证据可见性 operationally 改善，最终枚举/证据
覆盖质量尚未证明稳定提升”，不能把 projection、latency 或 token 均值直接称为用户回答质量。

Evaluation report 必须同时提供：Retriever hits/returned、Canonical/model-visible projection、
omission/truncation、Tool calls/rounds、latency/usage、citation/finalization、Trace ID、timeout/
runtime failure inventory，以及 paired ReviewPacket 的人工可复核材料。没有 exhaustive Reference
时，enumeration completeness 与 obvious final-answer omission 保持 `unknown`；evidence coverage
可以记录 `partial`，但不能伪造自动分数。`dynamic-default-250k` 在本轮保持为有上限的 headroom，
是否继续产生质量收益必须由实际绑定 run pool 的多-call压力 Case 重新校准。
