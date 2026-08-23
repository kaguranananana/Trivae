# M5 durable conversation persistence finalization — design

## Boundary

本轮最小行为缺口是：`QueryOrchestrator` 已产生 validated `AnswerArtifact`，但 `TrivaeApplication` 没有 Conversation Store，进程结束后 User / Assistant turn 与 Evidence 结构全部丢失。

改动落在 Application / Conversation Store 边界：

```text
TrivaeApplication.query()
    ↓ load persisted history
QueryOrchestrator
    ↓ QueryResult
validated success only
    ↓
SQLiteConversationStore.commit_turn()
```

Runtime、Tool、Retrieval、Finalizer 不拥有 Conversation Store，不执行 SQL；接口层只调用 Application facade。

## Planned modules

```text
src/trivae/conversation/
├── __init__.py
├── contracts.py       # Conversation / ConversationMessage / Store protocol
├── serialization.py   # explicit AnswerArtifact JSON codec
└── sqlite.py          # SQLite Conversation Store and transaction
```

必要的既有修改：

- `query/contracts.py`：为 Query 关联可选 `conversation_id`，为结果返回实际 conversation id，保持已有 positional 参数顺序兼容。
- `bootstrap/application.py`：Composition Root 创建、关闭 Conversation Store；`query()` 加载历史、调用统一 Orchestrator、成功后提交 turn；增加 create/read facade。
- `query/runtime` 或 Conversation compiler：把已完成历史转换为 `ModelContextMessage`；历史 Evidence 只作为标记为 historical 的上下文摘要，不被注入当前 `RuntimeResult.tool_results`。
- `tests/`：真实 SQLite lifecycle、codec、commit boundary 和 fresh-evidence integration coverage。
- `.trellis/spec/` 与任务 validation/journal：同步 M5 状态、技术决策、目录 ownership 和真实 Failure 证据。

## SQLite physical design

Conversation Store 使用与 Canonical Store 相同的 SQLite database path，但使用独立 connection 和独立 schema owner。初始化采用现有项目的显式 `CREATE TABLE IF NOT EXISTS` 风格，不引入迁移框架。

```sql
conversations(
    conversation_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)

conversation_messages(
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    answer_artifact_json TEXT,
    UNIQUE(conversation_id, ordinal),
    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id),
    CHECK (
        (role = 'user' AND answer_artifact_json IS NULL)
        OR (role = 'assistant' AND answer_artifact_json IS NOT NULL)
    )
)
```

`ordinal` 是每个 conversation 内的持久化顺序，避免依赖 timestamp 精度或 SQLite 隐含 row order。`answer_artifact_json` 是已验证 Artifact 的结构化快照；当前 scope 不需要把 Artifact 拆成多张可查询表，显式 codec 已足够表达 replay contract，也避免把 Evidence schema 扩展成新的事实来源。

`created_at / updated_at` 使用带 offset 的 UTC ISO-8601 毫秒文本，沿用 Canonical Store 的 `utc_now()` 语义。message id、conversation id 使用本地生成的 UUID hex，不把 provider id 当作 Conversation identity。

## Domain model and invariants

- 只允许 `user` 和 `assistant` 两种 completed message role。
- `user` message 没有 Artifact；`assistant` message 必须有 Artifact，且 `content == artifact.answer_text`。
- Artifact 使用现有领域构造函数重新建立，构造失败、未知 source type、缺失字段或 JSON 类型错误显式抛出 `ConversationStoreError`。
- `Conversation.messages` 按 `ordinal` 返回；`updated_at` 反映最后一次成功 commit。
- Store 不保存 SDK raw items、provider payload、ExecutionScope 对象或未验证候选 Artifact。

## Explicit codec shape

序列化不使用 `dataclasses.asdict()` 或隐式 pickle，采用稳定 JSON object：

```text
artifact
├── content_blocks[]
├── citation_bindings[]
├── evidence_items[]
│   └── sources[]
│       └── reference.type = message | structured
└── limitations[]
```

Message source 写入全部 locator 字段及 `snapshot`；snapshot 写入 session/author display、timestamp、timezone、excerpt、truncated 和 source message id。Structured source 写入 locator kind、locator、value snapshot、query scope snapshot、execution limitations。反序列化先检查 object/array/type discriminator，再调用 `MessageSource` / `StructuredSource` / `EvidenceItem` / `AnswerArtifact` 构造函数，因此持久化恢复与 M5a 领域 contract 共用同一验证入口。

## Query and history flow

1. Application 校验并解析 request 的 conversation id；没有 id 时创建空 conversation。
2. 有 id 时读取已提交 messages，并通过 Conversation compiler 生成 `ModelContextMessage`；不从 provider Session 读取历史。
3. 以本地历史替换 runtime request 的 prior context，执行既有 Router → Planner? → Runtime → Finalizer。
4. Runtime 非 completed 或 Finalizer 失败时直接返回 QueryResult，不调用 `commit_turn()`。
5. QueryResult 成功后，在一个 Conversation Store transaction 内追加 User message 和 Assistant message，并更新 conversation。
6. 返回带 conversation id 的 QueryResult；重启后 `read_conversation()` 直接恢复 Artifact。

历史 Assistant 上下文包含回答文本与 bounded finding/criterion/limitation 摘要，并明确标记为 historical context。它用于理解“他们”“后来”等指代，但不把旧 source locator 作为当前 ToolResult；新 Run 的 final synthesis 若提交旧 run/source，已有 `finalize_answer()` 会以 `INVALID_PROVENANCE` 拒绝。

如果调用方同时给出 conversation id 和手工 prior context，Application 不允许两套 history source 混用，应该显式拒绝，而不是静默覆盖。没有 conversation id 时，保留现有手工 `prior_context` 测试/调用语义。

## Atomic commit

`commit_turn()` 使用单个 Conversation Store connection 的 `BEGIN IMMEDIATE`：

```text
BEGIN IMMEDIATE
  verify conversation exists
  allocate next ordinal
  insert user message
  insert assistant message + serialized validated artifact
  update conversations.updated_at
COMMIT
```

任何 insert、序列化或约束异常都执行 rollback 并原样暴露；不会返回一个半成功 Conversation。序列化在 transaction 前完成并再次由 assistant domain invariant 校验，避免先写 User 后发现 Artifact 无法编码。测试用可控的 assistant insert failure 验证中途 rollback；不添加生产 fallback。

Canonical Store / FTS / read repository 不参与该 transaction，故不会把 Conversation persistence 权限扩散到 Retrieval，也不会把业务回答写入 Canonical Message Source of Truth。

## Fresh-evidence boundary

历史 Artifact 只从 Conversation Store read path 进入 replay/context；Application 不把它转换为 `ToolResultRecord`，也不把旧 result ids 合并到新 `RuntimeResult`。每个新 query 仍由 Runtime 产生自己的 run id 和 ToolResult tuple，Finalizer 只索引当前 `run_id`。

Deterministic integration test 构造 Turn 1 的 validated source，Turn 2 使用 Turn 1 source locator 但新 run id；期望 `INVALID_PROVENANCE`。另一个 follow-up test 使用 scripted runtime 产生新的 ToolResult and new source，确认 Turn 2 可成功提交且两个 Artifact 的 provenance 不同。

## Compatibility and rollback

- 现有没有 `conversation` package 或 conversation tables，首次打开旧 SQLite 文件时只新增两张表，不修改 Canonical 表和数据。
- 现有不带 conversation id 的 `QueryRequest` 保持可运行；为其创建新 conversation 并在成功时返回 id。
- 不实现旧 Artifact schema 兼容分支；当前仓库没有已发布 Conversation schema。codec 失败显式暴露，便于未来由真实 migration 需求驱动。
- 回滚只需移除 Application 接线和新 conversation tables；代码不会执行删除表或 destructive migration。

## Risks and deferred items

- 目前没有 Trace backend，因此 commit failure 只通过异常和测试可见；M6 再建立跨层 trace attribution。
- 真实 DeepSeek smoke 的回答语义仍不等于 Evaluation correctness；本轮只验证 persistence and provenance facts。
- 未来 history window / compression / branching / regenerate 需要独立设计和 Evaluation，不在本轮扩展。
