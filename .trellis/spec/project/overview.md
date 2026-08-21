# Project Overview

> 简短说明，不展开架构细节（架构见 architecture.md，当前 Draft / In Progress）。

---

## 项目

**Trivae** — 使用 Python 实现的高噪声群聊技术情报分析系统。

## 目标

从大量 QQ 技术群等高噪声聊天记录中：

1. 根据自然语言问题寻找相关信息；
2. 分析其中的技术讨论；
3. 形成**能够追溯到原始聊天消息**的证据型回答。

## 核心特征

- 输入：海量、高噪声、非结构化的群聊文本；
- 输出：证据型回答（每个结论可追溯到原始消息）；
- 主要架构参考：[ChatLab](https://github.com/ChatLab/ChatLab)（借鉴范围与映射方式由正式 Architecture Specification 确定）。

## 已确认信息

| 项 | 值 |
|----|----|
| 语言 | Python |
| 领域 | 高噪声群聊情报 / 技术讨论分析 |
| 架构参考 | ChatLab（待正式规格） |
| 开发管理 | Trellis |
| 工程风格 | Simple / Explicit / Testable / Observable / Failure-case driven / Evidence-based |

## 当前阶段

**Stage 1.1 已完成**：Stage 0 的 Git、Trellis 与工程规范已完成；Data Plane + Query Plane 的架构骨架已沉淀，业务代码仍为零。

**Stage 1.2（Data Model + Ingestion）已完成**：Canonical Data Model（Source / ChatSession / UserIdentity / Membership / Message / ImportBatch）、统一 Ingestion Pipeline、Shared Importer、Identity 与去重原则、Canonical Store 为 Source of Truth 已沉淀（见 [architecture.md](./architecture.md)）。

**Stage 1.3（Retrieval Architecture）已完成**：Retrieval 由 Retrieval Composition、三个 Primitives（Structured / Lexical / Semantic）与 Post-Retrieval Operator（Context Expansion）组成；Hybrid 为组合策略；集合确定后的确定性查询优先；Semantic 第一版 primary indexing unit 为 Conversation Chunk（Time-aware Parent + Small Child，Message-level 辅助索引 Pending Evaluation）；Retrieval Strategy 由任务决定；Retrieval Result provenance 与 Partial / Coverage 显式暴露已沉淀（见 [architecture.md](./architecture.md)）。Reranker、Fusion 权重、Chunk 参数等保持 Pending Evaluation。

**Stage 1.4（Tool / Capability Layer）已完成**：Tool 与 Capability 分离且可组合；第一版固定 6 个 Agent-facing Tool；Message Search 默认自动补充 bounded context；深度调查通过稳定 `message_id` 调用 `get_message_context`；Data Access Scope 构成所有 Tool（包括 `execute_sql`）的硬授权边界，Query-specific Filters 不自动等同于权限边界；人物查询使用 `find_members`；第一版 structured / canonical persistent store 采用 SQLite，Structured Retrieval 直接使用 Physical Schema + bounded read-only SQL，且 bounded 不要求 Agent SQL 自带 `LIMIT`；Search Result 与 Tool Result Envelope 的语义契约已确认、实现 Schema 尚未冻结；禁止 silent fallback；第一版不引入 Analysis View、Candidate State、Hybrid / Universal / Evidence Tool 或大量 Specialized Analysis Tools（见 [architecture.md](./architecture.md)）。

**Stage 1.5（Router）已完成**：Router 被定义为轻量 execution-complexity classifier / Planner gate；第一版只保留 `standard_execution` 与 `planned_execution`；两种 Route 最终进入同一个 Agent Runtime，只有 planned path 额外经过 Planner 并接收 soft execution guidance；Router 不选择 Tool 或 Retrieval Strategy；采用 Rule-first + LLM fallback、conservative default，并在 Router 失败时显式、可观测地降级到可用 Rule Decision 或 `standard_execution`（见 [architecture.md](./architecture.md) 与 [stage-1-5-router.md](./technical-decisions/stage-1-5-router.md)）。

**Stage 1.6（Planner）已完成**：Planner 被定义为 Thin pre-execution investigation planner，只在 `planned_execution` 进入同一个 Agent Runtime 前运行一次；Plan 是经过 deterministic validation / sanitization 的 soft guidance，不是 Workflow 或 Step Executor；第一版不引入 automatic replan、Planner-owned state、Planner Tool Calling 或 Planner-specific retry（见 [architecture.md](./architecture.md) 与 [stage-1-6-planner.md](./technical-decisions/stage-1-6-planner.md)）。

**Stage 1.7（Agent Runtime）已完成**：第一版采用 Thin Agent Runtime + OpenAI Agents SDK，单 Agent 承载 bounded Agent Loop；Trivae 保有 Context、Conversation History、Tool Adapter、生命周期和事件契约。Conversation Store 是 source of truth；Tool Round、graceful final synthesis 与 SDK `max_turns` 的关系已明确；仅已知 Tool Contract Error 可恢复，未知异常显式失败；Abort、Streaming、提交边界与 external tracing 配置均已确认（见 [architecture.md](./architecture.md) 与 [stage-1-7-agent-runtime.md](./technical-decisions/stage-1-7-agent-runtime.md)）。

当前架构文档仍为 `Draft / In Progress`。第一版 SQLite Physical Schema、Vector Store、Chunking 参数、Embedding、Evidence / Citation、Trace 等细节仍为 Pending，不能视为最终 Architecture Specification。

**当前任务**：Stage 1.7 已完成，等待进入 Stage 1.8 Evidence / Citation。在对应架构细节确认前不实现业务功能。

## 演进目标

持续把 Demo 演化为「可验证、可定位、可维护、可迭代」的工程系统，核心闭环：

```
实现 → 暴露问题 → 保存 Failure Case → 复现 → Trace/Log 定位 → 分析 Root Cause
→ 比较候选方案 → 最小合理修改 → 测试/Evaluation → 验证改善 → Regression → 文档沉淀
```

详见 [engineering-principles.md](./engineering-principles.md)。
