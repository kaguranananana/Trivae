# Technical Design

## 1. Smallest behavior gap and change boundary

### Smallest behavior gap

Trivae 的生产 Query 链路已经能产生可信 AnswerArtifact、Citation、Trace 和持久化
Conversation，但 CLI 只把“最终答案 + trace/log identity”投影给用户。用户无法在同一
生命周期内低成本完成 source review、scope/readiness 管理、反馈和历史恢复；已有 stream
事件也更像 debug transcript，而不是 normal product status。

### Behavior ownership

| Gap | 真正拥有行为的边界 | 本轮处理方式 |
| --- | --- | --- |
| Source review | `AnswerArtifact` trusted source snapshot + Canonical read adapter | Application 增加 bounded read facade；CLI 只编号/格式化 |
| Scope switch | CLI state + `ExecutionScope` → Application Query boundary | 选择新 scope 时清空 conversation/source/feedback state，后续 Query 以新 scope 创建 Conversation |
| Readiness | Composition/Application-owned Store、semantic status、Settings | 增加只读 readiness projection，不启动 runtime、扫描全文或 rebuild |
| Feedback | 独立 Product Feedback persistence boundary | 新增小型 SQLite store；不污染 Canonical/Evaluation/Trace |
| History/resume | Conversation Store schema/aggregate | 以 scope snapshot 做最小 migration；legacy null scope 只能列出、不能恢复 |
| Streaming UX/failure | 已有 `QueryStreamAdapter` + `CliEventRenderer` | 只改 projection/format/error mapping，不改变 event source 或 Query loop |

### Expected change files

以下是实现前的最小预期边界；如果实际 contract 证明某文件不需要修改，不会为了凑清单
修改它。

- `src/trivae/bootstrap/application.py`：提供 readiness、source inspection、conversation
  history/resume、feedback facade，并在同一 lifecycle 管理新 store；Query 新建/恢复时
  验证 scope compatibility。
- `src/trivae/bootstrap/status.py`（新）：定义无 secret 的 readiness read model，避免 CLI
  读取多个底层 store 并自行拼装状态语义。
- `src/trivae/query/evidence.py` 或相邻 source-review 模块：复用现有 MessageSource /
  StructuredSource，提供确定性的 source flatten/identity projection；不改变 Finalizer。
- `src/trivae/conversation/contracts.py`、`sqlite.py`：为新 Conversation 保存可比较的
  `ExecutionScope` snapshot，增加 summary/list contract 和 legacy migration。
- `src/trivae/feedback/`（新）：`FeedbackRecord`、store protocol、SQLite persistence；
  schema 只保存 feedback identity 和 bounded metadata。
- `src/trivae/interfaces/cli.py`：启动 readiness、命令 parser/dispatcher、scope/history/
  feedback/source state 和 friendly exception projection；不直接访问 SQLite、Capability
  或 Runtime。
- `src/trivae/interfaces/cli_renderer.py`：normal/verbose 的可读阶段投影、bounded source
  metadata、失败/部分答案/0-result 行边界；继续只消费 `QueryStreamEvent`。
- `tests/`：新增 product boundary、source, scope/status, feedback, history/resume, renderer
  and failure regression tests；保留现有测试不改契约期望来掩盖问题。
- `.trellis/spec/project/architecture.md`、相关 Stage 1.7/1.8/1.9/1.11、backend database
  guideline、`interview-defense.md`：完成后补写已验证事实与 Failure Case。

### Explicit non-goals

- 不改 Retrieval、Agent selection、Router/Planner、六个 canonical Tool、Finalizer 校验、
  Evaluation quality label 或 Trace event taxonomy。
- 不把 source review 实现成一次新的 Agent Tool call；不从 Trace Store polling 还原 live
  stream；不从 UI 再发 Provider/Retrieval 请求。
- 不把用户 feedback 写成 Trace Event、Evaluation Ground Truth 或人工 relevance label。
- 不给旧 Conversation 猜 scope；不在缺失 scope metadata 时通过当前 scope、session 名称、
  最近 Query 等 workaround 恢复。

## 2. Contracts and data flow

### 2.1 Source drill-down

```text
validated QueryResult.answer_artifact
  → deterministic source flatten (message/structured reference)
  → CLI bounded Sources projection
  → `/source n`
  → TrivaeApplication.inspect_message_source(reference, current_scope)
  → existing CanonicalReadRepository.read_message_context_scoped()
  → CLI target-highlighted bounded context
```

- Message source 的展示字段只读取 finalized `MessageDisplaySnapshot`；context 的每一行只
  读取 trusted `MessageProjection`。
- Source number 是当前 answer 的 display index，不改变 `MessageSource` identity；flatten
  规则按 `AnswerArtifact.evidence_items` / `EvidenceSource` 顺序去重 stable locator。
- Application 在 read facade 内校验 source type、session/message identity、scope/time 和
  target 必须出现在 returned context；source review 不触碰 Agent runtime。
- `StructuredSource` 由 CLI 展示 bounded locator/value/scope/limitations summary，并明确
  “structured result，无 message context”。
- context bound 继承现有 `get_message_context` 的 bounded contract，默认窗口小且固定；
  CLI 不允许用户通过 `/source` 传入无界 before/after。

### 2.2 Scope and conversation lifecycle

```text
CLI picker or `/chats`
  → ExecutionScope(allowed_session_ids=trusted session IDs | None)
  → QueryRequest.scope
  → Application creates Conversation(scope snapshot)
  → subsequent Query requires exact scope compatibility
```

- `/new` 只丢弃当前 conversation identity，保留同一个 `ExecutionScope`。
- 不同 scope 选择会清空当前 conversation、last completed source map 和 last feedback
  binding；下一个 Query 由 Application 创建新的 scoped Conversation。
- Conversation domain 增加可选 scope snapshot 只为兼容历史 rows；新 Query 创建的记录必须
  带 scope。legacy `NULL` scope 仍可读取/列出，但 `resume` 和带 conversation_id 的 Query
  显式失败。
- `/resume` 读取目标 Conversation 的已持久化 scope；如果与当前 scope 不同，命令明确
  输出 restored scope 后才把它设为当前 scope。后续 Application 再次做 exact comparison，
  不允许静默以当前较窄 scope 注入旧 history。

### 2.3 Readiness

```text
TrivaeApplication.readiness()
  ├─ Canonical read facade: open + sessions + message count
  ├─ existing semantic_index_status(): missing/building/completed/partial/failed/stale
  └─ settings.load_settings(): configured provider/model, no secret
        ↓
  CLI startup + `/status` bounded projection
```

- readiness 只读取 state/watermark/metadata；不执行 semantic integrity scan、rebuild、model
  load、network health call 或 Query。
- `completed` 在产品显示中可写为 `ready`，原始 semantic status 仍保留在 read model/verbose
  projection；其它状态原样保留并给出当前 CLI 已知的 rebuild 命令提示。
- Provider readiness 只说明 Settings contract 可构造 Query；网络/上游 TLS 失败仍属于
  Query execution failure，并由已有 Trace/known failure UX 处理。

### 2.4 Feedback persistence

```text
last successful QueryResult
  → CLI `/good` | `/bad [note]`
  → Application.save_feedback(...)
  → SQLiteFeedbackStore (separate adjacent database)
```

Record fields:

```text
feedback_id
created_at / updated_at
conversation_id
trace_id
run_id
scope_snapshot_json
rating: good | bad
note: bounded optional text
feedback_kind: user_experiential
```

- `(conversation_id, trace_id)` 是唯一 current feedback key；再次反馈执行 update/upsert，
  不制造多个互相矛盾的“ground truth”记录。
- store 不保存 answer/tool payload；`scope_snapshot_json` 只保存 trusted `scope_snapshot`
  的普通值。
- Application facade 负责验证 rating、current scope 和 completed run identity；CLI 不构造
  数据库 SQL。
- Evaluation Store 继续拥有 Case/Variant/Run/Review 语义，不承接用户体验反馈；Trace
  继续只保存 Query execution facts，不添加 feedback event。

### 2.5 History/resume

```text
ConversationStore.list_summaries(limit)
  → deterministic updated_at DESC / conversation_id ASC
  → title = existing title metadata OR bounded first user query
  → CLI `/history`
  → `/resume n` → read full aggregate + scope compatibility
```

Migration is additive and explicit:

- `conversations.scope_snapshot_json` is added when absent; existing rows remain `NULL` and are
  marked non-resumable instead of being assigned a guessed scope.
- New Application Query creates scoped Conversation rows. Existing direct Store callers that
  create an unscoped conversation remain compatible for tests/legacy code, but such rows cannot
  be used as a scoped Query resume.
- Migration runs during Conversation Store schema initialization inside the existing connection;
  no message rows or canonical tables are rewritten.

## 3. Normal/verbose renderer design

`QueryStreamAdapter` remains the only live projection source. `CliEventRenderer` remains a display
state machine, not an Agent state machine.

Normal mode:

- actual non-empty reasoning → `Thinking` segment;
- route/plan → one compact readable line/step list;
- tool start → friendly canonical tool label + bounded meaningful args;
- retrieval complete → real candidate/total/expanded/returned counts and explicit zero/partial
  wording; successful tool terminal lines are compact or omitted when redundant;
- answer delta → continuous answer segment; finalizer answer remains authoritative;
- failure/abort → close open line and print stable friendly message plus trace identity.

Verbose mode keeps the existing debug projection: source operation/sequence, bounded metadata,
timing, usage and normalized details. It still never prints provider raw fields, secret, raw
artifact, unbounded tool result or hidden CoT.

The renderer must not infer “thinking text” from a tool name or phase. Empty/no reasoning produces
no Thinking line. A partial answer followed by failure closes the line and reports failure; it
never emits `completed` or a fake final answer.

## 4. Failure ownership and diagnostics

Known failure codes retain their owner:

- semantic unavailable/stale → semantic status/tool failure; `/status` gives details, no fallback;
- no result → successful retrieval with zero count, not exception;
- tool failure + later agent continuation → show real tool failure then continue real events;
- finalizer/commit failure → no completed answer/commit, trace id retained;
- provider/settings failure → safe error code/message and trace identity;
- unknown exception → normal CLI shows bounded diagnostic reference and trace if available; verbose
  adds exception type and run identity, while application/logging continues to expose the root
  exception instead of swallowing it.

No application retry/fallback is added. If a test or real smoke reveals a lower-layer contract
failure, the checkpoint records reproduction, owner, root cause, minimal fix and regression before
the next checkpoint.

## 5. Compatibility and rollback

- Existing `QueryRequest`, `QueryStreamEvent`, six Tool registration, `search_messages` compatibility,
  Finalizer and Trace contracts remain additive/behavior-compatible.
- New Application methods and optional store injection preserve current non-CLI callers.
- The only persistence migration is an additive nullable Conversation scope column; feedback uses
  a separate database file and can be removed without changing Canonical/Conversation/Trace data.
- Each checkpoint is committed independently. Rollback removes only that checkpoint's CLI/store/
  docs changes; existing query data and old AnswerArtifacts remain readable.

## 6. Verification of local refactors

- Source review tests compare source display fields against trusted hydrated snapshots and verify no
  second Query/Tool call occurs.
- Conversation tests assert atomic commit remains User+Assistant only, scope is round-tripped,
  mismatch/legacy resume is rejected, and old historical evidence is still context-only.
- Renderer tests feed the same ordered `QueryStreamEvent` sequence to normal and verbose renderers;
  only projection detail differs, with no new execution invocation.
- Application regression tests use fake runtime/Trace/Store ports to prove production Query path,
  Trace operation sequence, six canonical capability names and Evaluation runner are unchanged.
- Real smoke is metadata-only and uses a temporary database copy where appropriate; no real chat
  body enters task artifacts or Git.
