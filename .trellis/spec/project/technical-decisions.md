# Technical Decisions

> 重大技术决策（ADR）的沉淀位置与格式。
> 当前状态：Stage 1.1 的一级架构方向记录于 architecture.md；Stage 1.2 的关键决策记录于 [technical-decisions/stage-1-2-data-model-ingestion.md](./technical-decisions/stage-1-2-data-model-ingestion.md)；Stage 1.3 的关键决策记录于 [technical-decisions/stage-1-3-retrieval-architecture.md](./technical-decisions/stage-1-3-retrieval-architecture.md)；Stage 1.4 的关键决策记录于 [technical-decisions/stage-1-4-tool-capability-layer.md](./technical-decisions/stage-1-4-tool-capability-layer.md)。

---

## 记录位置

正式决策文档：`.trellis/spec/project/technical-decisions/<slug>.md`，本文件作为索引。

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

- 来自「框架默认 / ChatLab 如此 / 某开源项目如此」的方案视为 **Initial hypothesis / reference design**，不能直接视为最终结论。
- 应根据决策类型，通过项目约束、复杂度分析、Prototype、Test、Benchmark、Evaluation 或真实 Failure Case 等证据确认方案，再升级为决策记录。

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
- 后续：Stage 1.2-1.11 分别确认剩余细节，完成后再统一升级文档状态。

### Stage 1.2：Data Model + Ingestion

- 状态：Confirmed（逻辑数据模型与概念边界；Database Schema 与技术选型仍 Pending）。
- 内容：Canonical Model 隔离、Stable Platform Identity 优先、Platform Identity 与 Membership 分离、Shared Importer、Stable Message ID 优先 + Fingerprint fallback、Canonical Store 为 Source of Truth、ImportBatch 观测、Canonicalization 保真、Canonical Timestamp 语义。
- 记录位置：[technical-decisions/stage-1-2-data-model-ingestion.md](./technical-decisions/stage-1-2-data-model-ingestion.md)（详细 rationale），[architecture.md](./architecture.md)（整体视图）。
- 后续：Stage 1.3 Retrieval Architecture。

### Stage 1.3：Retrieval Architecture

- 状态：Confirmed（Retrieval 内部能力与组合策略；Tool 暴露方式、Reranker、Fusion 权重、Chunk 参数、Message-level 辅助索引、Trace Schema、Vector Store / Embedding 仍 Pending）。
- 内容：Multi-strategy Retrieval（Composition + 三个 Primitives + Post-Retrieval Operator）、Hybrid 为组合策略、集合确定后的确定性查询优先、Conversation Chunk 为第一版 Semantic primary indexing unit（Time-aware Parent + Small Child，Message-level 辅助索引 Pending Evaluation）、Context Expansion 为 Post-Retrieval Operator、Query-specific strategy、Retrieval Result provenance（Message Candidates + Structured Results 分列）、Partial / Coverage 显式暴露（口径 Stage 1.9 细化）、Failure Attribution 分类、Evidence 判断不硬编码、Retrieval Trace 观察需求（Schema 不提前实现）。
- 记录位置：[technical-decisions/stage-1-3-retrieval-architecture.md](./technical-decisions/stage-1-3-retrieval-architecture.md)（详细 rationale），[architecture.md](./architecture.md)（整体视图）。
- 后续：Stage 1.4 Tool / Capability Layer。

### Stage 1.4：Tool / Capability Layer

- 状态：**本文所记录决策均已 Confirmed；Stage 1.4 整体 In Progress**（完整 Tool 列表、Structured Query 设计、Search Result Schema、Tool Contract 等仍 Pending）。
- 内容：Tool 与 Capability 分离（Capability 不依赖 Agent Runtime）、一个 Tool 可组合多个 Capability、Tool Surface 优先 Agent 易用性、Message Search（Lexical / Semantic）默认自动补充 bounded context（Local context 为 Search Result 默认组成部分）、自动 Expand 必须 bounded、内部 Capability 独立可观测、Semantic Search 同原则且保留 provenance、不把大上下文窗口作为主要设计依据、参数由 Evaluation 决定、禁止 silent fallback、第一版不引入复杂 Candidate State。
- 记录位置：[technical-decisions/stage-1-4-tool-capability-layer.md](./technical-decisions/stage-1-4-tool-capability-layer.md)（详细 rationale），[architecture.md](./architecture.md)（整体视图）。
- 后续：继续 Stage 1.4，完成 Tool Surface / Contract 等剩余设计；Stage 1.5 暂不开始。
