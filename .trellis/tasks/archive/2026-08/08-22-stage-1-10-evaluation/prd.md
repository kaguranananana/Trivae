# PRD: Stage 1.10 Evaluation 架构决策

## Goal

为 Trivae 建立可重复、可归因、可用于回归的 Evaluation 架构，使后续实现能够证明一次修改是否真正改善了证据型回答质量，并解释改善或退化发生在 Router、Planner、Retrieval、Tool、Agent Runtime、Evidence、Citation 还是 Answer 层。

本任务完成 Stage 1.10 的稳定架构契约与项目文档同步，不伪造尚未运行的 baseline、阈值、参数结论或业务实现。

## Background

- Trivae 面向高噪声群聊技术情报分析，最终产物是可追溯到原始 Message Source 或 Structured Result Source 的证据型回答。
- Stage 1.1–1.9 已完成架构决策，但仓库仍无业务实现；Stage 1.10 之后才进入 CLI / API 与具体实现边界。
- Stage 1.9 Trace 只记录运行事实和 operational dimensions，不在线猜测质量 Root Cause；Evaluation 可以消费 sanitized Trace，并在运行后关联 Review / Diagnosis，但不能改写 Trace。
- Stage 1.5 已确认 Router 的目标不是孤立的分类准确率，而是 Planner Invocation 是否带来下游收益；需要比较同一 Query 的 standard 与 planned 路径。
- Stage 1.8 已确认 Citation Validator 只确定性证明来源真实、可解析且在 Scope 内；semantic entailment、criterion quality、sufficiency 与 Answer Correctness 属于 Evaluation。
- Stage 1.3–1.9 留下的 Evaluation Pending 包括 Dataset、labels / review、quality metrics、threshold / gate、Regression、paired comparison，以及 model / prompt / chunk / top-k / rerank / Tool Budget / stopping 等参数校准。
- ChatLab 当前只有 24 条静态 Router seed cases 和结构完整性测试；baseline 均明确标记为待真实环境运行，没有通用端到端 runner、质量评分、paired result 或 regression gate。它提供场景设计、稳定 ID、expected evidence coverage、显式参数和先观察后校准的参考，但不能直接充当 Trivae Evaluation 架构。

## Requirements

1. 定义 Evaluation 的职责边界，以及 Test、Operational Metric、Offline Evaluation、Online Observation 与 Regression Gate 的区别。
2. 以端到端 Evaluation Case Bundle 作为 canonical truth，绑定固定 Dataset Snapshot、Data Access Scope、User Query、Reference Findings / Evidence、annotation completeness / provenance、uncertainty constraints 与 review policy。
3. Router、Planner、Retrieval、Tool、Runtime、Evidence、Citation 与 Answer 的 module evaluation 必须从同一 Case 派生；纯模块输入只作为 Test / Diagnostic Fixture。
4. Ground Truth 不使用唯一标准答案文本，必须允许多个正确表达、新的真实 Evidence 与合理不确定性。
5. 区分 Design Seed、Core Evaluation Set、Failure Regression Set 与 Calibration Slice，不把设计样例描述成已经完成的 Benchmark；Core Set 通过 versioned Suite 随真实 workload 演变并保留历史结果。
6. 定义 Controlled Variant、pinned Baseline identity / Candidate diff、Evaluation Run、Review、Result / Comparison、Failure Diagnosis 与 Regression Case 的稳定概念边界。
7. 定义 deterministic check、人工 review 与 model-assisted review 的职责；Judge 不得成为在线依赖或不可复核的唯一真相来源。
8. 定义最小而有决策价值的质量轴和 module diagnostics；质量、延迟、Token、Tool Call 与成本不得被机械压成一个掩盖 trade-off 的总分。
9. 定义相同 Case、Snapshot、Scope 下 baseline / candidate 的 paired comparison、blind randomized review 与 stochastic run 的重复观测原则。
10. 定义 Failure Diagnosis 与 Stage 1.9 immutable Trace 的关联边界，并定义真实 Failure Case 进入 Regression Set 的生命周期。
11. 定义 threshold / gate 的证据门槛：没有真实 baseline、方差、review agreement、Failure Cost 与业务容忍度时，不冻结 numerical threshold。
12. 明确 Stage 1.3–1.9 Pending 参数的校准方法与 ADR Reopen 条件；不自动引入 Reranker、Message-level index、Specialized Tool、Replan、automatic repair 或 machine stopping。
13. 通过 forced standard / forced planned counterfactual experiment 先测 Planner Utility，再评价 Router 是否识别当前 Planner 真正有收益的 Case。
14. 明确 reproducibility 是 Evaluation 条件可重建与统计可比较，不承诺远程模型字节级重放；删除与权限变化优先于复现便利。
15. 新增一组 Trivae-specific Design Seed Cases，覆盖事实查找、趋势、多阶段调查、身份歧义、证据不足、absence、冲突 Evidence、Chunk Boundary、Planner 正负收益、Scope 限制与 Reference 外新 Evidence。
16. 记录 ChatLab 的 inherit / adapt / do-not-inherit 边界；具体经验参数只可作为标注来源的 baseline seed。
17. 同步项目 ADR、架构总览、阶段状态、工程原则和旧 ADR 的当前 Pending 路由。
18. 正式文档完成后，向用户详细解释 Evaluation 的目标、数据模型、运行链路、指标边界、Failure Attribution、参数校准和 ChatLab 对比。

## Key Decisions

- Stage 1.10 只确认 Evaluation 架构、概念契约、指标语义与必要 seed cases；不交付 runner、实现 Schema 或真实 Dataset。
- Evaluation Case Bundle 是 canonical truth；模块评测从端到端 Case 派生，不维护彼此割裂的质量事实源。
- Reference Findings / Evidence 取代唯一标准答案文本。
- Reference 使用 `exhaustive / partial / unknown` 完整度语义，并保存建立流程、时间、Scope、adjudication 与限制等 provenance。
- End-to-end quality 与 module diagnostics 同时保留，但不产生单一总分。
- Planner Utility 先通过绕过 Router 的 forced standard / forced planned 比较得到；Router 再评价是否识别 Planner 真正有收益的 Case。
- Evaluation 使用 deterministic first、human review、model-assisted review 三层机制，关键争议回到人工。
- Baseline 是 pin 住的 Controlled Variant，Candidate 声明显式 diff；last stable、minimal control 与 ChatLab-derived seed 用途分开。
- 方案比较必须是固定 Case / Snapshot / Scope 的 blind paired comparison，并考虑 stochastic variation。
- Core Set 根据真实 workload 通过 Suite versioning 刷新，历史 composition 与结果保留。
- Reproducibility 保证条件可重建与统计可比较，不保证外部模型输出字节级重放。
- Failure Diagnosis 只能关联、不能改写 canonical Trace；真实修复提升为 versioned Regression Case。
- Hard contract 可以先确认；numerical gate 必须等待真实 baseline 与 Failure Cost。
- 质量与 latency / token / Tool Call / cost 采用分轴或 Pareto trade-off。
- Evidence-aware stopping 第一版继续是 Agent guidance；machine gate、minimum citation 数量和 automatic repair 没有 Evaluation 证据前不引入。
- Evaluation Artifact 需要独立选择与治理，不能通过永久保留全部 Trace 或聊天正文获得。
- 11 个 Trivae Design Seed 只验证架构表达能力，不产生 gate 或固定 workload 分布。

## Acceptance Criteria

- [ ] 新增 `stage-1-10-evaluation.md`，结构与既有 ADR 一致，覆盖职责边界、Case / Suite / Run / Review / Result / Diagnosis / Regression、质量与诊断分层、paired comparison、Judge governance、threshold policy、参数校准、ChatLab 边界、Failure Cases、Deferred 与 Reopen Conditions。
- [ ] `technical-decisions.md` 的状态、ADR 列表与当前记录包含 Stage 1.10，并将 Stage 1.11 标为后续阶段。
- [ ] `architecture.md` 新增 Stage 1.10 稳定架构章节，并同步 Evaluation / Regression、Confirmed Decisions、Pending Decisions、ChatLab 边界与阶段顺序。
- [ ] Stage 1.3–1.9 ADR 的当前 Pending 路由同步到 Stage 1.10 已确认契约；历史 Context 保留，具体实现与真实校准不被误写为完成。
- [ ] `overview.md`、`project/workflow.md`、`engineering-principles.md`、`backend/index.md`、`backend/directory-structure.md` 与 `backend/logging-guidelines.md` 的阶段状态和术语一致。
- [ ] Evaluation Dataset 能同时承载端到端评测和分层归因，不要求为每个模块维护独立 Ground Truth。
- [ ] Reference completeness / provenance 的概念边界明确，并说明 `exhaustive / partial / unknown` 对 Precision / Recall 解释力的影响。
- [ ] Router / Planner Utility、Retrieval / Context、Tool / Runtime、Evidence / Citation、Answer 与系统成本的评测目标均有明确边界。
- [ ] Planner forced-path experiment 与 Router Utility 分离，避免把 Router 选择收益和 Planner 机制收益混为一体。
- [ ] Baseline 被定义为 pinned Controlled Variant，Candidate 通过显式 diff 比较，不使用漂移的 `main / current defaults`。
- [ ] 明确 quality result 与 diagnosability、relevance 与 query-scope coverage、Evidence sufficiency 与 Tool completeness、Citation precision 与 Citation coverage 的区别。
- [ ] 明确 deterministic check、人工 review 与 model-assisted review 的适用范围、争议处理与 blind randomized pairwise review。
- [ ] 明确 paired experiment、重复运行、baseline / candidate 比较与 Failure Regression 生命周期。
- [ ] 至少 8–12 个 Trivae-specific Design Seed 覆盖评审要求的真实场景形态，并明确不是 Benchmark / gate。
- [ ] Core Set workload refresh、Suite versioning、Snapshot 数据治理和非字节级 reproducibility 语义明确。
- [ ] 不伪造业务代码、Evaluation 结果、baseline 数字、pass / fail threshold、“最优参数”或 ChatLab 适配结论。
- [ ] 文档链接、阶段编号、术语和 Pending 路由通过全局复核，`git diff --check` 无错误。
- [ ] 完成后提供一份从问题、心智模型、具体例子、执行链路到关键取舍的详细中文解释。

## Out of Scope

- Evaluation runner、CLI、数据库表、Python / JSON Schema、具体 package layout 与 Dashboard。
- 创建或导入真实聊天 Evaluation Dataset，以及执行真实模型 baseline。
- 在没有实现和真实运行的情况下产出质量结论、数值 gate 或最优参数。
- Stage 1.11 CLI / API / UI 设计。
- 用 Stage 1.10 自动重写 Stage 1.1–1.9 已确认架构；只有满足对应 Reopen Condition 的证据才可另行重开。

## Deferred

- Case 数量、slice 比例、development / holdout 划分与 Regression 增长策略的数字；
- Core Set 刷新周期、workload sampling / reweight 算法与第一版 stable baseline 的具体选择；
- 重复 Run 次数、统计方法、Judge agreement 与全部 numerical threshold；
- completeness / provenance、Baseline diff 与 Snapshot status 的具体 Schema / 字段名；
- model / prompt / chunk / top-k / fusion / rerank / budget / stopping 的真实校准结果；
- Dataset storage、runner、replay、review workflow、report 与权限实现；
- CLI / API / UI exposure。
