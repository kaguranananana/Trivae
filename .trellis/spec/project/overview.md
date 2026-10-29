# Project Overview

> **历史项目概览，不是当前实现或进度入口。** 下方 Stage 完成状态和“当前任务状态”是该规格的历史快照；当前实现以源码及 [docs/architecture.md](../../../docs/architecture.md) 为准，当前进度见 [docs/PROJECT_STATUS.md](../../../docs/PROJECT_STATUS.md)。历史架构决定只有在仍与当前实现一致时才适用。

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
- 主要架构参考：[ChatLab](https://github.com/ChatLab/ChatLab)；适用设计默认继承，具体继承与偏离由各 Stage ADR 记录。

## 已确认信息

| 项 | 值 |
|----|----|
| 语言 | Python |
| 领域 | 高噪声群聊情报 / 技术讨论分析 |
| 架构参考 | ChatLab（作为 Reference Implementation；继承与偏离按各 Stage ADR 记录） |
| 开发管理 | Trellis |
| 工程风格 | Simple / Explicit / Testable / Observable / Failure-case driven / Evidence-based |

## 历史阶段快照（非当前进度）

**Stage 1.1 已完成**：Stage 0 的 Git、Trellis 与工程规范已完成；Data Plane + Query Plane 的架构骨架已沉淀。

**Stage 1.2（Data Model + Ingestion）已完成**：Canonical Data Model（Source / ChatSession / UserIdentity / Membership / Message / ImportBatch）、统一 Ingestion Pipeline、Shared Importer、Identity 与去重原则、Canonical Store 为 Source of Truth 已沉淀（见 [architecture.md](./architecture.md)）。

**Stage 1.3（Retrieval Architecture）已完成**：Retrieval 由 Retrieval Composition、三个 Primitives（Structured / Lexical / Semantic）与 Post-Retrieval Operator（Context Expansion）组成；Hybrid 为组合策略；集合确定后的确定性查询优先；Semantic 第一版 primary indexing unit 为 Conversation Chunk（Time-aware Parent + Small Child，Message-level 辅助索引 Pending Evaluation）；Retrieval Strategy 由任务决定；Retrieval Result provenance 与 Partial / Coverage 显式暴露已沉淀（见 [architecture.md](./architecture.md)）。Reranker、Fusion 权重、Chunk 参数等保持 Pending Evaluation。

**Stage 1.4（Tool / Capability Layer）已完成**：Tool 与 Capability 分离且可组合；第一版固定 6 个 Agent-facing Tool；Message Search 默认自动补充 bounded context；深度调查通过稳定 `message_id` 调用 `get_message_context`；Data Access Scope 构成所有 Tool（包括 `execute_sql`）的硬授权边界，Query-specific Filters 不自动等同于权限边界；人物查询使用 `find_members`；第一版 structured / canonical persistent store 采用 SQLite，Structured Retrieval 直接使用 Physical Schema + bounded read-only SQL，且 bounded 不要求 Agent SQL 自带 `LIMIT`；Search Result 与 Tool Result Envelope 的语义契约已确认、实现 Schema 尚未冻结；禁止 silent fallback；第一版不引入 Analysis View、Candidate State、Hybrid / Universal / Evidence Tool 或大量 Specialized Analysis Tools（见 [architecture.md](./architecture.md)）。

**Stage 1.5（Router）已完成**：Router 被定义为轻量 execution-complexity classifier / Planner gate；第一版只保留 `standard_execution` 与 `planned_execution`；两种 Route 最终进入同一个 Agent Runtime，只有 planned path 额外经过 Planner 并接收 soft execution guidance；Router 不选择 Tool 或 Retrieval Strategy；采用 Rule-first + LLM fallback、conservative default，并在 Router 失败时显式、可观测地降级到可用 Rule Decision 或 `standard_execution`（见 [architecture.md](./architecture.md) 与 [stage-1-5-router.md](./technical-decisions/stage-1-5-router.md)）。

**Stage 1.6（Planner）已完成**：Planner 被定义为 Thin pre-execution investigation planner，只在 `planned_execution` 进入同一个 Agent Runtime 前运行一次；Plan 是经过 deterministic validation / sanitization 的 soft guidance，不是 Workflow 或 Step Executor；第一版不引入 automatic replan、Planner-owned state、Planner Tool Calling 或 Planner-specific retry（见 [architecture.md](./architecture.md) 与 [stage-1-6-planner.md](./technical-decisions/stage-1-6-planner.md)）。

**Stage 1.7（Agent Runtime）已完成**：第一版采用 Thin Agent Runtime + OpenAI Agents SDK，单 Agent 承载 bounded Agent Loop；Trivae 保有 Context、Conversation History、Tool Adapter、生命周期和事件契约。Conversation Store 是 source of truth；Tool Round、graceful final synthesis 与 SDK `max_turns` 的关系已明确；仅已知 Tool Contract Error 可恢复，未知异常显式失败；Abort、Streaming、提交边界与 external tracing 配置均已确认（见 [architecture.md](./architecture.md) 与 [stage-1-7-agent-runtime.md](./technical-decisions/stage-1-7-agent-runtime.md)）。

**Stage 1.8（Evidence / Citation）已完成**：Answer 使用 claim-level Citation，并与 Evidence Panel 共用同一结构化 Answer Artifact；Final Evidence 按 claim / finding 组织，可包含 Message Source 与 Structured Result Source；Citation 必须来自当前 Run 实际取得且在 Data Access Scope 内的 Tool Result。用户可通过会话、作者、精确时间和 bounded 原始上下文复核来源，全量聊天留在原社交平台。invalid / unresolved Citation 会显式阻止 Answer 提交，第一版不新增 Evidence Tool、Evidence Agent、固定关键词 Judge、自动 citation repair 或 Runtime-owned Evidence State Machine（见 [architecture.md](./architecture.md) 与 [stage-1-8-evidence-citation.md](./technical-decisions/stage-1-8-evidence-citation.md)）。

**Stage 1.9（Trace / Observability）已完成（修订版）**：完整 Query Execution 使用 Trivae-owned normalized event boundary；Trace 以 versioned append-only event、单 Trace sequence 与 operation causality 支持跨 Router、Planner、Runtime、Tool、Retrieval、Evidence、Citation 和 Answer commit 的 Failure Attribution。当前代码已实现 Trace Collector、SQLite Trace Store、normal/debug capture policy、failure ownership 和 retrieval strategy/candidate/coverage payload；质量阈值与长期 retention 仍由真实运行校准。

**Stage 1.10（Evaluation / Regression）已完成（架构与实现契约）**：Evaluation Case Bundle 作为端到端 canonical truth；Reference 按具体 Finding 表达 `exhaustive / partial / unknown` annotation completeness 与 provenance，Case 级完整度只能派生；Design Seed、Core、Failure Regression、Calibration Slice 分层，Core 通过 versioned Suite 刷新且保留历史；Baseline 必须是 pinned Controlled Variant，Candidate 声声明式 diff；当前实现已具备 Evaluation Store、Runner、checks、paired comparison 与 lexical-only / semantic-enabled comparison fixtures；真实 Snapshot 的 Qwen baseline 与 LLM-assisted provisional annotation/metrics 已完成，human-verified labels、corpus-exhaustive reference 与长期数值 threshold 仍待校准。

**Stage 1.11（Application Boundary 与 Python 工程结构）已完成（架构边界）**：v1 采用单 Python distribution 与 `src/trivae` 概念 package layout；CLI 与 HTTP API 是薄 Interface Adapter，Evaluation 是拥有 Case / Variant / Runner / Review / Regression 语义的独立评测子系统，三者通过统一 Composition Root 进入同一个 Application / QueryOrchestrator；TrivaeApplication facade 现已覆盖 query、ingestion、conversations、evaluation、traces、lexical rebuild、semantic status/rebuild 与 lifecycle，产品路径不直接读取 Store；Semantic Retrieval 使用独立 sqlite-vec derived database、显式 identity/status 和 canonical range recovery；官方 Qwen provider 已完成 473,236 条 canonical message 的真实 baseline rebuild 与 LLM-assisted provisional paired Evaluation，HTTP Product Interaction、human verification 与长期运维阈值仍待后续任务。

当前架构文档仍为 `Draft / In Progress`。M1 SQLite ingestion、sqlite-vec semantic derived index、Qwen3 provider contract、Trace backend、Evaluation Schema/runner 已有 deterministic implementation；真实 Snapshot 已完成 1024-d Qwen baseline rebuild，并生成带 `llm_assisted_provisional` provenance 的 paired report。human-verified annotation、corpus-exhaustive reference、chunk/ANN 长期阈值与 HTTP Product Interaction 仍为 Pending，不得把 provisional metrics 写成质量结论。

**当前任务状态**：M1 ingestion、M2/M3 Retrieval/Capability、M4a Agent Runtime baseline、M4 Query Execution Core、M5a Evidence/Citation + Answer Finalization、M5b Conversation / Assistant Message persistence 与本 Semantic Retrieval vertical slice 已实现并完成 deterministic validation。当前 Query 主链路为 `QueryRequest → persisted history → Router → optional Planner → shared AgentRuntime → lexical_search/semantic_search → current-run ToolResult provenance → Evidence/Citation Finalizer → validated AnswerArtifact → atomic Conversation Store commit`；human-verified Qwen quality calibration、长期参数阈值、corpus-exhaustive reference 与 HTTP Product Interaction 仍待后续任务。

**Semantic Retrieval vertical slice（2026-08-23/24）**：默认本地 provider identity 为 `sentence-transformers / Qwen/Qwen3-Embedding-0.6B / 1024 / last_token / normalized / query instruction`；索引单位为 Time-aware Parent + Small Child，独立 sqlite-vec derived database 保存向量与 bounded range metadata。真实 Snapshot rebuild 已覆盖 473,236 messages、54,267 vectors，状态为 `completed`；同 Snapshot 生成的 12-query paired report 与 173 条标签全部标记 `llm_assisted_provisional`，`ground_truth_claim=false`，不能视为 human ground truth。`lexical_search` 与 `semantic_search` 是独立 Agent-facing tools；`search_messages` 仅作为无策略参数的现有兼容别名。缺失、building、failed、stale、partial、truncated 与 canonical context recovery failure 均保持显式，不执行 lexical fallback；最终 citation 只使用 canonical Message source。

## 演进目标

持续把 Demo 演化为「可验证、可定位、可维护、可迭代」的工程系统，核心闭环：

```
实现 → 暴露问题 → 保存 Failure Case → 复现 → Trace/Log 定位 → 分析 Root Cause
→ 比较候选方案 → 最小合理修改 → 测试/Evaluation → 验证改善 → Regression → 文档沉淀
```

详见 [engineering-principles.md](./engineering-principles.md)。
