# M5 durable conversation persistence finalization

## Goal

在不改变 M5a Evidence / Citation 语义的前提下，把已经通过 Finalizer 和 trusted hydration 的 `Validated AnswerArtifact` 接入真实 SQLite Conversation Store，形成：

```text
Query → Runtime → current-run ToolResult → AnswerArtifact
→ Citation Finalizer → trusted hydration → validated artifact
→ atomic Conversation commit → restart replay
```

用户价值是：完成的 User / Assistant 对话可以在进程重启后恢复，回答中的 claim、Evidence、Citation 和可信消息快照仍然可复核；后续 follow-up 可以利用历史语境，但不会把历史 Evidence 冒充成新一轮事实依据。

## Confirmed repository facts

- `QueryOrchestrator.run()` 已在 `RuntimeResult` 完成后调用 `finalize_answer()`；失败返回 `finalization_error`，成功才填充 `QueryResult.answer_artifact`。
- `QueryResult.is_successful` 只在 Runtime `completed` 且存在 validated Artifact 时为 true。
- `ToolResultRecord` 保存本轮 `run_id / tool_call_id / tool_result_id / result_item_id` 及 bounded message/structured projection；Finalizer 已拒绝旧 run、fabricated locator 和 scope violation。
- `MessageSource.snapshot` 已由可信 Canonical projection hydrate，包含 session、author、timestamp、timezone、excerpt 和 source message id。
- Stage 1.7 把 Trivae Conversation Store 定义为 history source of truth；SDK Session / provider conversation state 不能成为 canonical history。
- Stage 1.8 已冻结 `Validated AnswerArtifact → Conversation Store commit` 和“旧 Evidence 不是后续 Run fresh evidence”的语义；本任务不重新设计这些 contract。
- Stage 1.11 要求 CLI、未来 HTTP、Evaluation 通过统一 Application / Query boundary 进入，不让 Runtime、Router、Planner、Tool 或 Finalizer 直接执行 SQL。
- 当前 Canonical Chat Store 和 Retrieval read repository 已分别拥有写入与只读边界；Conversation Store 将使用同一个 SQLite 文件中的独立 conversation tables 和独立 Store ownership。

## Requirements

### R1. Conversation domain and Application boundary

- 增加最小 `Conversation`、completed `ConversationMessage` 和 Conversation Store contract。
- 至少表达 conversation id、created/updated timestamps、message id、conversation id、role、content、created timestamp 和可选 validated `AnswerArtifact`。
- 提供 Application-level conversation create/read/query integration；Query execution 不能由接口层自行持久化。
- 有 conversation id 的 Query 必须从 Conversation Store 编译历史上下文；没有 id 时创建新的 conversation，并把返回的 id 暴露给调用方。

### R2. Durable SQLite persistence

- 使用真实 SQLite，不 mock 核心 repository。
- Conversation Store 与 Canonical Store 共用数据库文件但保持 ownership 清晰；Retrieval read repository 不获得写权限。
- User / completed Assistant message 的顺序必须在重启后稳定；Assistant 行必须同时保存文本投影和结构化 Artifact JSON。
- 读取时必须通过领域构造函数恢复并校验 Artifact；损坏、缺失或 content 与 Artifact 不一致时显式失败。

### R3. Reversible AnswerArtifact persistence

- 显式序列化 / 反序列化 `AnswerArtifact`，保留 content block id、citation binding、evidence id、finding、criterion、sufficiency、source relation、limitations。
- `MessageSource` 必须保留当前 run/tool/result/item provenance 和 trusted display snapshot。
- `StructuredSource` 必须保留 locator kind、locator、value snapshot、query scope snapshot 和 execution limitations。
- 不重新调用 LLM、Retrieval 或 hydration 来恢复历史 Artifact；重启后直接 replay 已持久化 snapshot。

### R4. Atomic commit boundary

- 只允许 `QueryResult.is_successful` 的 validated Artifact 进入 completed Assistant Message。
- 成功路径在一个 Conversation Store transaction 中提交 User message + completed Assistant message，并更新 conversation timestamp。
- Finalization failure、Runtime failure、abort、max-turns 或 provider failure 不得留下 completed Assistant Message / fake Artifact；中途事务失败不得留下半个 turn。
- 失败诊断不扩展为 M6 Trace / diagnostic backend；只保留现有 QueryResult / Runtime error 语义。

### R5. Historical replay and follow-up boundary

- `read_conversation()` 返回稳定顺序的结构化历史；历史 Assistant Artifact 可直接展示 / replay。
- 历史上下文可用于理解后续指代，但历史 source snapshot / evidence 不进入新 Runtime 的 `ToolResultRecord`。
- 后续 factual follow-up 必须经过新的 Runtime run、新 ToolResult provenance 和新的 finalization；现有 current-run Finalizer contract 不得放宽。
- 不新增完整产品级 regenerate API；用 deterministic integration coverage 验证新 run 不能复用旧 Evidence，若未来已有 entry point 再接入同一 Application boundary。

## Acceptance Criteria

- [x] Conversation 可创建、读取，User / Assistant 顺序稳定。
- [x] Validated `AnswerArtifact` 经过 serialize → SQLite → close/reopen → deserialize 后领域语义一致。
- [x] MessageSource snapshot、StructuredSource、CitationBinding、Evidence ID、relation、sufficiency、limitations 全部 round-trip。
- [x] 成功 query 只在 finalization 成功后 atomic commit User + completed Assistant。
- [x] Finalization failure、Runtime failure / abort / max-turns 不产生 completed Assistant。
- [x] transaction 中途失败回滚整个 turn，不留下半个 Artifact。
- [x] Application restart 后历史 AnswerArtifact 可直接 replay，不重新搜索、hydrate 或调用 LLM。
- [x] follow-up 使用新的 run/tool/result provenance；old Evidence 被作为新 Citation 提交时显式失败。
- [x] 真实 SQLite integration smoke 覆盖 create → query → commit → close → reopen → load。
- [x] deterministic tests、pytest、ruff、mypy、CLI help、Trellis validation、`git diff --check` 通过；真实 DeepSeek + SQLite persistence smoke 记录 secret-safe 结果。

## Explicitly out of scope

- M6 Trace / Observability backend、retention、diagnostic record store。
- M7 Evaluation runner、semantic citation judge、质量 threshold 或 citation repair agent。
- Semantic / hybrid retrieval、embedding、vector store、HTTP API、Web UI、Evidence Panel UI。
- 自动 retry、fallback、降级、旧 schema 兼容分支或静默吞错。
- 产品级 regenerate endpoint；仅保留新 run/fresh provenance 的 deterministic boundary test。

## Blocking open questions

无。SQLite 表结构、序列化格式、Application 接线和 transaction 实现按本任务设计落地；不改变已确认的 Stage 1.7 / 1.8 / 1.11 语义。
