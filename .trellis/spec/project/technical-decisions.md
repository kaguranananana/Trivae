# Technical Decisions

> 重大技术决策（ADR）的沉淀位置与格式。
> 当前状态：Stage 1.1 的一级架构方向记录于 architecture.md；Stage 1.2–1.11 的关键决策分别记录于本页索引的对应 ADR。

---

## 记录位置

正式决策文档：`.trellis/spec/project/technical-decisions/<slug>.md`，本文件作为索引。

## 当前 ADR 列表

| Stage | 状态 | 主要决策 | ADR 路径 |
| --- | --- | --- | --- |
| Stage 1.2 | Confirmed | Data Model + Ingestion | [stage-1-2-data-model-ingestion.md](./technical-decisions/stage-1-2-data-model-ingestion.md) |
| Stage 1.3 | Confirmed | Retrieval Architecture | [stage-1-3-retrieval-architecture.md](./technical-decisions/stage-1-3-retrieval-architecture.md) |
| Stage 1.4 | Confirmed / Completed | Tool / Capability Layer | [stage-1-4-tool-capability-layer.md](./technical-decisions/stage-1-4-tool-capability-layer.md) |
| Stage 1.5 | Confirmed / Completed | Router 与 Planner gating | [stage-1-5-router.md](./technical-decisions/stage-1-5-router.md) |
| Stage 1.6 | Confirmed / Completed | Thin pre-execution investigation planner | [stage-1-6-planner.md](./technical-decisions/stage-1-6-planner.md) |
| Stage 1.7 | Confirmed / Completed | Agent Loop · SDK · Runtime lifecycle | [stage-1-7-agent-runtime.md](./technical-decisions/stage-1-7-agent-runtime.md) |
| Stage 1.8 | Confirmed / Completed；M5a/M5b implemented | Evidence · Citation · Source review | [stage-1-8-evidence-citation.md](./technical-decisions/stage-1-8-evidence-citation.md) |
| Stage 1.9 | Confirmed / Completed（修订版） | Normalized Trace · Failure Attribution · Coverage · Normal/Debug Profiles · Privacy / Retention · Error Ownership | [stage-1-9-trace-observability.md](./technical-decisions/stage-1-9-trace-observability.md) |
| Stage 1.10 | Confirmed / Completed（架构契约） | Evaluation Case Bundle · Reference completeness / provenance · pinned Baseline · forced-path Planner Utility · blind paired review · Regression | [stage-1-10-evaluation.md](./technical-decisions/stage-1-10-evaluation.md) |
| Stage 1.11 | Confirmed / Completed（架构边界） | Application Boundary · Composition Root · Python package ownership · unified Query execution core · CLI / API / Evaluation adapters | [stage-1-11-application-architecture.md](./technical-decisions/stage-1-11-application-architecture.md) |
| Web UI | Confirmed / Implemented | Local Web 成为 primary interaction surface · QueryStreamEvent UI-neutral · Conversation shared capability · provider reasoning visibility · Trace Finder · Session≠Conversation | [web-primary-interface.md](./technical-decisions/web-primary-interface.md) |
| Provider Migration | Confirmed | OpenCode Go → Official DeepSeek · exact capability registry · JSON/tools boundary · evaluation identity | [provider-migration-deepseek-official.md](./technical-decisions/provider-migration-deepseek-official.md) |
| Router Jev experiment | Experimental / Not promoted | OpenRouter Decisions provider for ambiguous Router choices · default shadow · paired diagnostic Evaluation | [router-jev-provider-experiment.md](./technical-decisions/router-jev-provider-experiment.md) |

Stage 1.1 一级架构骨架仍记录于 [architecture.md](./architecture.md)。Stage 1.11 架构边界已确认；M4 Query、M5a Evidence/Citation、M5b Conversation、M6 Trace backend 与 Evaluation runner 已实现。Planner Utility 已在 37 条 Development Case 上执行，当前 Planner-specific Suite 与 Router Utility 分析链路已实现并完成两条真实 smoke；人工 treatment 裁决、fresh generalization、最终阈值与生产 Jev 切换仍 Pending。

## 决策问题链

以下链路按决策类型取舍；`Problem / Constraint`、`Root Cause` 或 `Regression` 不适用时应明确标注，而不是强行制造 Failure Case。

```
Initial Design / Context
↓
Problem / Constraint (if applicable)
↓
Evidence / Rationale
↓
Root Cause (if applicable)
↓
Candidate Solutions
↓
Decision
↓
Reason
↓
Result
↓
Trade-off
↓
Regression
```

禁止只记录结论（如 "Use Hybrid Retrieval."）而不记录演化原因。

## 来源分级

- **项目级 Architecture Principle：ChatLab 作为 Reference Implementation**：ChatLab 是 Trivae 的主要参考实现，适用设计默认继承；全项目的适用性判断、偏离记录要求和证据门槛统一见 [Architecture Governance](./architecture.md#architecture-principle-chatlab-as-reference-implementation)。
- 对其他框架、开源项目或未经验证的默认值，仍视为 **Initial hypothesis / reference design**；应通过项目约束、Prototype、Test、Benchmark、Evaluation 或真实 Failure Case 确认。

## 决策状态与重新打开规则

- **Confirmed**：已经完成决策，默认冻结；后续讨论主要用于解释和理解，不直接重新设计。
- **Pending**：尚未决定，可以继续比较方案。
- **Experimental**：明确偏离已有方案，必须通过实验或 Evaluation 验证。

重新打开 Confirmed 决策必须记录 **Reopen Reason**，且由新 Failure Case、新技术约束、新 Evaluation 结果或新业务需求触发。

## 重点关注清单

优先记录影响 Quality / Reliability / Latency / Token / Cost / Complexity / Maintainability 的决策，例如：

- Rule Router / LLM Router / Hybrid Router
- Keyword / Semantic / Hybrid Retrieval
- 是否需要 Reranker
- Agent Loop 终止条件
- Tool 参数错误处理
- Context 规模控制
- Retry / Fallback 策略
- Token / Latency 控制

## 当前记录

### Stage 1.1：整体架构骨架

- 状态：Draft / In Progress，不是最终 Architecture Specification。
- 内容：Data Plane + Query Plane、Query 主链路、Router / Planner / Agent Runtime / Tool Layer / Retrieval / Evidence 的一级职责边界。
- 记录位置：[architecture.md](./architecture.md)。
- 后续：Stage 1.2-1.11 已分别确认；Stage 1.10 的实现 / 校准与 Stage 1.11 的业务实现、产品交互和实现级契约仍按各自阶段推进。

### Stage 1.2：Data Model + Ingestion

- 状态：Confirmed（逻辑数据模型与概念边界；Stage 1.2 当时未决定存储技术，第一版 SQLite 后由 Stage 1.4 确认；Physical Schema 细节仍 Pending）。
- 内容：Canonical Model 隔离、Stable Platform Identity 优先、Platform Identity 与 Membership 分离、Shared Importer、Stable Message ID 优先 + Fingerprint fallback、Canonical Store 为 Source of Truth、ImportBatch 观测、Canonicalization 保真、Canonical Timestamp 语义。
- 记录位置：[technical-decisions/stage-1-2-data-model-ingestion.md](./technical-decisions/stage-1-2-data-model-ingestion.md)（详细 rationale），[architecture.md](./architecture.md)（整体视图）。
- 后续：Stage 1.3 Retrieval Architecture。

### Stage 1.3：Retrieval Architecture

- 状态：Confirmed（Retrieval 内部能力与组合策略；Tool 暴露方式已在 Stage 1.4 确认；Trace / query-scope coverage 语义已在 Stage 1.9 确认；Reranker、Fusion 权重、Chunk 参数、Message-level 辅助索引、具体 Trace Schema、Vector Store / Embedding 仍 Pending）。
- 内容：Multi-strategy Retrieval（Composition + 三个 Primitives + Post-Retrieval Operator）、Hybrid 为组合策略、集合确定后的确定性查询优先、Conversation Chunk 为第一版 Semantic primary indexing unit（Time-aware Parent + Small Child，Message-level 辅助索引 Pending Evaluation）、Context Expansion 为 Post-Retrieval Operator、Query-specific strategy、Retrieval Result provenance（Message Candidates + Structured Results 分列）、Partial / Coverage 显式暴露（Stage 1.9 已细化为 query-scope coverage）、Failure Attribution 分类、Evidence 判断不硬编码、Retrieval Trace 观察需求。
- 记录位置：[technical-decisions/stage-1-3-retrieval-architecture.md](./technical-decisions/stage-1-3-retrieval-architecture.md)（详细 rationale），[architecture.md](./architecture.md)（整体视图）。
- 后续：Stage 1.4 Tool / Capability Layer 已完成；Stage 1.5 Router 已完成。

### Stage 1.4：Tool / Capability Layer

- 状态：**Confirmed / Completed（Stage 1.4）**。具体 bounded 参数仍 Pending Evaluation，但不影响本阶段架构完成状态。
- 内容：遵循项目级 ChatLab Reference Implementation Architecture Principle；Tool 与 Capability 分离且可组合；当前第一版 7 个 Tool（含 `get_recent_messages`、`lexical_search`、`semantic_search`、`get_message_context`、`find_members`、`get_schema`、`execute_sql`）；Message Search 默认 bounded context；稳定 `message_id` 深度扩展；Data Access Scope 约束所有 Tool（包括 `execute_sql`），Query Context / Query-specific Filters 不自动等同于权限边界；Member Lookup 返回候选；第一版 structured / canonical persistent store 采用 SQLite，直接暴露 Physical Query Schema + bounded read-only SQL，且 bounded 不要求 Agent SQL 自带 `LIMIT`；`get_recent_messages` 使用独立 `1000/5000` temporal capacity、keyset continuation 和 query-scope coverage，不改变通用 structured `100`；统一 Search Result / Tool Envelope 语义契约但不冻结实现 Schema；禁止 silent fallback；第一版不引入 Analysis View、Candidate State、Hybrid / Universal / Evidence Tool 或大量 Specialized Analysis Tools。
- 记录位置：[technical-decisions/stage-1-4-tool-capability-layer.md](./technical-decisions/stage-1-4-tool-capability-layer.md)（详细 rationale），[architecture.md](./architecture.md)（整体视图）。
- 后续：Stage 1.5 Router 已完成；Stage 1.4 的经验参数由后续 Evaluation 校准，重新打开 Confirmed 决策必须记录 Reopen Reason。

### Stage 1.5：Router

- 状态：**Confirmed / Completed（Stage 1.5）**。本阶段完成 Router 架构决策沉淀；M4 已落地两路 rule-first Router 与可选 strict-JSON completion fallback。
- 内容：Router 作为 execution-complexity classifier / Planner gate；两路 Route（`standard_execution` / `planned_execution`）；两种 Route 进入同一个 Agent Runtime；Planner 为 planned path 提供 soft guidance；Runtime 注入 Router Context / Data Snapshot / Capability Summary；严格区分 Evidence dependency / Dependent semantic investigation 与普通 Retrieval / Synthesis；明确 Data Scope Size、Retrieval Volume、Tool Call Count 等 non-signals；Rule-first + LLM fallback；conservative default；Router failure graceful degradation；Router 与 Tool / Retrieval / Planner 的职责边界；Route Decision 的 Trace / Evaluation 语义；真实 Trivae seed workload；Planner Utility 优先于单独的 Route Classification Accuracy。
- 记录位置：[technical-decisions/stage-1-5-router.md](./technical-decisions/stage-1-5-router.md)（详细 rationale），[architecture.md](./architecture.md)（稳定结构与模块边界）。
- 后续：Router Rule/LLM/Jev shadow、Trace 与 16 条 route diagnostic 已实现；forced-path Planner Utility 已有 Development 结果，Router Utility 的人工标签、正式运行与长期参数校准仍 Pending。

### Stage 1.6：Planner

- 状态：**Confirmed / Completed（Stage 1.6）**。本阶段完成 Planner 架构决策沉淀；M4 已落地 bounded validation/sanitization、soft guidance 和 graceful skip。
- 内容：Planner 定义为 Thin pre-execution investigation planner；只在 `planned_execution` 进入 Agent Runtime 前运行一次；`standard_execution` 与 `planned_execution` 使用同一个 Agent Runtime；Plan 是 soft investigation guidance，不是 Workflow；Planner Input 由 Runtime 注入 `user_query`、`query_context`、compact `data_snapshot` 与 `capability_summary`；第一版采用轻量 Plan Schema（version / title / intent / steps.goal / suggested_tools / evidence_needed / success_criteria）；suggested_tools 是 advisory hint，不生成 Tool Arguments；evidence_needed 不是 Stage 1.8 Evidence Object；Plan 经过 deterministic validation / sanitization；hallucinated Tool 被过滤；Plan bounded；Planner failure graceful degradation 且不重写 Router Decision；第一版不 automatic replan、不 Planner-owned state、不 Planner-specific retry / regeneration、不增加 LLM Plan Validator。
- 记录位置：[technical-decisions/stage-1-6-planner.md](./technical-decisions/stage-1-6-planner.md)（详细 rationale、Trade-off、Failure Case 与 Reopen Conditions），[architecture.md](./architecture.md)（稳定结构与模块边界）。
- 后续：SoftPlanner 的 Python class、Prompt、bounded Plan、Trace 与生产注入已实现；forced-path Development 已测。zero-result 的聚合行误拒已修，SQL-first 路径的稳定消失尚未证实；人工 utility 裁决、fresh 泛化和长期参数校准仍 Pending。

### Stage 1.7：Agent Runtime

- 状态：**Confirmed / Completed（Stage 1.7）**。本阶段完成 Agent Runtime 架构决策沉淀；M4 已落地 SDK 0.22.0 streamed adapter、RuntimeEvent、tool budget、abort 和 lifecycle；Conversation persistence 已由 M5b 落地第一版 Store/replay，Trace/Evaluation 仍 Pending。
- 内容：继承 ChatLab 的 Thin Agent Core 架构，由 OpenAI Agents SDK 承载通用 Agent Loop；Trivae 拥有外层执行编排、Context、Conversation History、Tool Adapter、生命周期语义与事件契约；Thin Agent Runtime + 单 Agent + 两种 Route 用同一个 Runtime；OpenAI Agents SDK 通过概念性的 Runtime / Function Tool Adapter 接入，不冻结文件布局；RuntimeContext（local）与 Agent Model Context（LLM-visible）分离且 Data Access Scope 硬执行；Trivae Conversation Store 为 source of truth，SDK / Provider conversation state 只作可重建 adapter state，streaming、完成、中止与失败记录有明确提交边界；pre-run Context 压缩（不做 mid-run compaction）；Tool Round 按一个包含 Tool Result 的模型轮次计数，Trivae Budget 先触发 graceful final synthesis，SDK `max_turns` 预留最终模型调用并只作兜底；仅已知 Tool Contract Error 可由 Agent 恢复，未知 Tool / Adapter 异常显式 `FAILED`；Abort 采用协作式 cancellation，晚到结果不得重启执行；Streaming 为 canonical path；Runtime lifecycle 状态机；Planner soft guidance 注入；Trivae 显式关闭 SDK built-in external tracing；ChatLab 经验参数可直接继承但标注来源并保留 Evaluation 校准。
- 记录位置：[technical-decisions/stage-1-7-agent-runtime.md](./technical-decisions/stage-1-7-agent-runtime.md)（详细 rationale、Trade-off、Failure Case 与 Reopen Conditions），[architecture.md](./architecture.md)（稳定结构与模块边界）。
- 后续：Stage 1.8 已确认 Evidence / Citation；Stage 1.9 已确认 Runtime / Evidence / Citation Event family、Trace conceptual envelope、Error Code ownership 与 Observability；具体 Trace Schema / 实现 Pending；Stage 1.10 已确认 correctness / diagnosability 以及成本分轴，Runtime 参数和真实结果仍 Pending。

### Stage 1.8：Evidence / Citation

- 状态：**Confirmed / Completed（Stage 1.8）**。本阶段完成 Evidence / Citation 架构决策沉淀；M5a/M5b 已落地第一版 finalization、Artifact codec、Conversation persistence 与 replay 实现，Trace/Evaluation 与长期质量校准仍 Pending。
- 内容：主链路固定为 `Retrieval / Structured Result → Evidence Selection / Organization → Final Evidence → Citation-bound Answer`；Answer Content、claim Citation bindings、Evidence Items 与 limitations 组成单一 conceptual Answer Artifact；Evidence Item 按 claim / finding 组织，可包含 `supports / contradicts / context` 多 Source；Message Source 使用 current-run Tool provenance、显式 Session / Message locator 与可信人工复核 snapshot，Structured Result Source 使用独立结果 locator；Semantic Chunk 只作 acquisition provenance；question-specific criterion 与 `sufficient / partial / insufficient` 已确认，并与 Tool `partial / coverage / truncated / unavailable` 分轴表达；Citation Validator 只做确定性结构、provenance、locator 与 Data Access Scope 校验，不声称证明语义正确；invalid / unresolved Citation 显式阻止提交；validated Artifact 随 Assistant Message 持久化，旧 Evidence 不作后续 Run 的 fresh evidence；应用内只展示 bounded 原始上下文，全量聊天留在原社交平台；Evidence-aware stopping 第一版仅作 Agent guidance。
- 明确不引入：`retrieve_evidence` Tool、Evidence Agent、固定关键词 Judge、固定时间聚类、Runtime-owned Evidence State Machine、silent citation drop、自动来源替换或无依据 repair / retry。
- 记录位置：[technical-decisions/stage-1-8-evidence-citation.md](./technical-decisions/stage-1-8-evidence-citation.md)（详细 rationale、ChatLab 代码证据、Trade-off、Failure Case 与 Reopen Conditions），[architecture.md](./architecture.md)（稳定结构与模块边界）。
- 后续：Stage 1.9 已确认 Evidence Selection / Citation Validation / Answer Finalization 的 Trace family、Error Code ownership、storage 与 operational metric 原则；具体 Schema / 实现 Pending；Stage 1.10 已确认 Evidence / Citation 的 completeness、groundedness、coverage 与 blind Review 语义，具体 rubric / runner / 校准仍 Pending。

### Stage 1.9：Trace / Observability

- 状态：**Confirmed / Implemented（Stage 1.9，修订版）**。跨 Query Plane Trace Collector、normal/debug 投影与 SQLite Store 已实现；retention 和长期 operational calibration 仍 Pending。
- 内容：一个 Trivae-owned normalized event boundary 横跨 Context、Router、Planner、Runtime、Tool、Retrieval、Evidence、Citation 与 Answer commit；Stream / Trace 使用不同 projection；conceptual envelope 保留 version、identity、correlation、sequence 与 operation causality；append-only event 为 Trace source of truth；Failure Attribution 区分 origin / observation / handling / terminal outcome；query-scope coverage 以授权 effective scope 为基准并支持 `complete / partial / none / unknown / not_applicable`；Error Code 由 contract owner namespace 拥有；Trace 采用 `normal / debug` Profile，Normal 允许 bounded / redacted actual content，Debug 在授权范围内允许完整或近完整的 model-visible / system-visible facts，但两者都排除 secrets、越权数据和 hidden Chain-of-Thought；retention 分层且不强制 Debug 比 Normal 更短；Trace Store 独立、versioned、append-only；Collector failure 显式产生 incomplete 但不回滚成功业务结果；Stage 1.9 只确认 operational metric dimensions，不设置质量阈值。
- 记录位置：[technical-decisions/stage-1-9-trace-observability.md](./technical-decisions/stage-1-9-trace-observability.md)（详细 rationale、Failure Case、Validation Contract 与 Reopen Conditions），[architecture.md](./architecture.md)（稳定结构与跨切面边界）。
- 后续：具体 Python / JSON Schema、Error Code 枚举、Collector / Store backend、retention 时长与 privacy enforcement 属于 Implementation；Evaluation Case / Dataset、quality metrics、threshold / gate 与参数校准已由 Stage 1.10 ADR 确认语义，具体实现与真实校准仍 Pending。

### Stage 1.10：Evaluation / Regression

- 状态：**Confirmed / Development-evaluated（架构与第一版实现）**。Case/Reference/Suite、Snapshot、Runner、Store、paired comparison 与 Planner forced-path Development 实验已实现；Router Utility 有 2 条未裁决真实 smoke，人工 treatment 裁决、fresh baseline 与最终数值 gate 仍 Pending。
- 内容：端到端 Evaluation Case Bundle 是 canonical truth；Reference 按具体 Finding 组织，每个 Finding 表达 `exhaustive / partial / unknown` completeness 与 provenance，Case 级完整度只能派生；Design Seed、Core、Failure Regression、Calibration Slice 分层，Core 通过 versioned Suite 刷新并保留历史；Baseline 是 pinned Controlled Variant，Candidate 声明显式 diff；Planner Utility 先通过除 Planner 是否介入及其 guidance 外其他条件完全相同的 forced standard / forced planned 测量，再评价 Router Utility；没有明显 Planner 收益的 Case 不强制填写 `expectedRoute`；quality 与 module diagnostics 分轴，paired quality review 使用 blind、随机 A/B、同 rubric、同 Evidence visibility；Snapshot 可重建但不绕过删除与权限变化；Stage 1.9 Trace 只能被引用、不能被 Diagnosis 改写。
- 记录位置：[technical-decisions/stage-1-10-evaluation.md](./technical-decisions/stage-1-10-evaluation.md)（详细 rationale、Decision Set、Trivae-specific Seeds、ChatLab 继承 / 偏离、Deferred 与 Reopen Conditions），[architecture.md](./architecture.md)（整体视图）。
- 后续：Planner-specific Development Suite、人工 treatment review contract 与 Router Utility 离线分析已准备；大样本真实运行、人工一致性、数值 threshold 和长期校准仍 Pending。
