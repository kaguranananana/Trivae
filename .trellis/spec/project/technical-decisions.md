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

- **ChatLab First Principle**：ChatLab 是 Trivae 的主要参考基线。ChatLab 已存在且适用于 Trivae 的架构设计默认采用原方案，不因主观偏好重新设计。
- 任何偏离 ChatLab 的设计都必须记录：原方案不适用的原因、具体业务问题 / Failure Case / Evaluation / 技术约束、新方案收益、新增复杂度与风险，以及验证方法。
- “感觉可以更简单”“感觉可以少一个 Tool”“LLM 现在能力很强”“可以封装起来”“代码看起来更优雅”不足以改变 Confirmed 决策。
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
- 后续：Stage 1.2-1.11 分别确认剩余细节，完成后再统一升级文档状态。

### Stage 1.2：Data Model + Ingestion

- 状态：Confirmed（逻辑数据模型与概念边界；Stage 1.2 当时未决定存储技术，第一版 SQLite 后由 Stage 1.4 确认；Physical Schema 细节仍 Pending）。
- 内容：Canonical Model 隔离、Stable Platform Identity 优先、Platform Identity 与 Membership 分离、Shared Importer、Stable Message ID 优先 + Fingerprint fallback、Canonical Store 为 Source of Truth、ImportBatch 观测、Canonicalization 保真、Canonical Timestamp 语义。
- 记录位置：[technical-decisions/stage-1-2-data-model-ingestion.md](./technical-decisions/stage-1-2-data-model-ingestion.md)（详细 rationale），[architecture.md](./architecture.md)（整体视图）。
- 后续：Stage 1.3 Retrieval Architecture。

### Stage 1.3：Retrieval Architecture

- 状态：Confirmed（Retrieval 内部能力与组合策略；Tool 暴露方式已在 Stage 1.4 确认；Reranker、Fusion 权重、Chunk 参数、Message-level 辅助索引、Trace Schema、Vector Store / Embedding 仍 Pending）。
- 内容：Multi-strategy Retrieval（Composition + 三个 Primitives + Post-Retrieval Operator）、Hybrid 为组合策略、集合确定后的确定性查询优先、Conversation Chunk 为第一版 Semantic primary indexing unit（Time-aware Parent + Small Child，Message-level 辅助索引 Pending Evaluation）、Context Expansion 为 Post-Retrieval Operator、Query-specific strategy、Retrieval Result provenance（Message Candidates + Structured Results 分列）、Partial / Coverage 显式暴露（口径 Stage 1.9 细化）、Failure Attribution 分类、Evidence 判断不硬编码、Retrieval Trace 观察需求（Schema 不提前实现）。
- 记录位置：[technical-decisions/stage-1-3-retrieval-architecture.md](./technical-decisions/stage-1-3-retrieval-architecture.md)（详细 rationale），[architecture.md](./architecture.md)（整体视图）。
- 后续：Stage 1.4 Tool / Capability Layer 已完成；Stage 1.5 尚未开始。

### Stage 1.4：Tool / Capability Layer

- 状态：**Confirmed / Completed（Stage 1.4）**。具体 bounded 参数仍 Pending Evaluation，但不影响本阶段架构完成状态。
- 内容：ChatLab First Principle；Tool 与 Capability 分离且可组合；第一版 6 个 Tool（`lexical_search`、`semantic_search`、`get_message_context`、`find_members`、`get_schema`、`execute_sql`）；Message Search 默认 bounded context；稳定 `message_id` 深度扩展；Data Access Scope 约束所有 Tool（包括 `execute_sql`），Query Context / Query-specific Filters 不自动等同于权限边界；Member Lookup 返回候选；第一版 structured / canonical persistent store 采用 SQLite，直接暴露 Physical Query Schema + bounded read-only SQL，且 bounded 不要求 Agent SQL 自带 `LIMIT`；统一 Search Result / Tool Envelope 语义契约但不冻结实现 Schema；禁止 silent fallback；第一版不引入 Analysis View、Candidate State、Hybrid / Universal / Evidence Tool 或大量 Specialized Analysis Tools。
- 记录位置：[technical-decisions/stage-1-4-tool-capability-layer.md](./technical-decisions/stage-1-4-tool-capability-layer.md)（详细 rationale），[architecture.md](./architecture.md)（整体视图）。
- 后续：Stage 1.5 尚未开始；Stage 1.4 的经验参数由后续 Evaluation 校准，重新打开 Confirmed 决策必须记录 Reopen Reason。
