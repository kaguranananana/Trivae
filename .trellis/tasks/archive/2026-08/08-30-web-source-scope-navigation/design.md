# Design: Source Scope → Conversation → Turns

## 1. Change Boundary

### Smallest behavior gap

当前 Web 把全局最近 Conversation 作为 Sidebar 输入，再在客户端按 scope 分组；初始自动打开全局最新项。
目标是让 Source Scope 成为一级导航，并让 Conversation list query 在 Store/SQLite 层精确过滤后再 limit。

### Behavior owners

- Web navigation state：`scope.ts`
- scope identity / DTO compilation：`utils/scope.ts` + `contracts.ts`
- list request lifecycle：`conversations.ts` + `client.ts`
- displayed/stream buffer ownership：`chat.ts`
- three-column orchestration：`App.vue` + Sidebar components
- Web selector validation：`interfaces/web/contracts.py` / `routes.py` / `conversation.py`
- filter-before-limit：Conversation domain contract → Application facade → `sqlite.py`

### Expected product files

- Frontend：`App.vue`、`SourceScopeSidebar.vue`、`ConversationSidebar.vue`、`scope.ts` store、
  `conversations.ts` store、`chat.ts` store、`utils/scope.ts`、`types/contracts.ts`、`api/client.ts`。
- Backend：`conversation/contracts.py`、`conversation/sqlite.py`、`bootstrap/application.py`、
  `interfaces/web/contracts.py`、`interfaces/web/routes.py`、`interfaces/web/conversation.py`。
- Tests：`tests/test_conversation.py`、`tests/test_web_server.py`、对应 `web/tests/*.test.ts`。
- Docs：`web-primary-interface.md` 与本任务 Validation / Failure Cases。

### Explicit non-goals

不重做 Retrieval/ExecutionScope，不增加 multi-session primary selector，不迁移历史数据，不改变 CLI/TUI。
前端拆分只增加一个有独立职责的 Source Scope Sidebar，不制造大量薄组件。

## 2. Information Architecture

```text
GET /api/source-sessions
        │
        ▼
SourceScopeSidebar ── selectedSourceScope (navigation only)
        │
        ├── null ──────────────> no list / no draft / composer disabled
        ├── all ───────────────> ScopeRequest { mode: "all" }
        └── session:<id> ──────> ScopeRequest { mode: "sessions", session_ids: [id] }
                                      │
                                      ▼
                            GET /api/conversations
                            filter → order → limit
                                      │
                                      ▼
                            ConversationSidebar
                                      │
                                      ▼
                            immutable ConversationBuffer
                                      │
                                      ▼
                         User / Process / Answer / Sources
```

## 3. Frontend State

### 3.1 Navigation model

```ts
type SelectedSourceScope =
  | null
  | { kind: 'all' }
  | { kind: 'session'; sessionId: string }
```

`null` 不可序列化为 ScopeRequest。唯一编译函数返回 `ScopeRequest | null`；所有 New Chat / Send
调用点必须先得到非 null 结果。`scopeKey()` 继续作为共享 exact identity owner：`all`、
`session:<id>`、`sessions:<sorted ids>`、`unmarked`。

### 3.2 Scope restore

- `mode=all` → `{kind:'all'}`。
- `mode=sessions` 且规范化后恰好一个 ID，并存在于 catalog → `{kind:'session', sessionId}`。
- multi-session、unknown session、legacy null → `null`，保留 detail buffer 只读回放，不猜测合法 scope。

### 3.3 Conversation list request lifecycle

`refresh(selection)` 的顺序：

1. increment generation；
2. 立即清空 `conversations`、重置 loaded、设置 loading；
3. selection=null 时结束，不请求；
4. 编译 bounded query selector并请求；
5. 只有 generation 仍是最新且 selected scope key 未改变时提交 response。

generation 是 A→B race 的必要保护：如果 A 请求晚于 B 返回，不允许把 A 列表写回 B。

### 3.4 Displayed buffer 与 draft isolation

持久化 Conversation 仍以 conversation ID 为 key。Draft 不再共享单一可覆写对象，而按 exact scope key
生成 draft key（`__draft__:` + canonical `scopeKey()`，例如 `__draft__:all`、单 session 为
`__draft__:sessions:["<id>"]`）。这样 A 的 create request await 期间切到 B，
B 会绑定另一 draft；A 创建完成后仍把 A draft rename 为 A conversation ID。

stream 仍只通过 `request_id → streamOwners → bufferKey` 更新 owner；Scope switch 只把 `currentKey`
设为 null/对应 draft，不删除 A buffer 或 A stream context。

### 3.5 URL restore

不引入 Vue Router。使用一个窄的 URL helper 管理 `conversation_id` query：

- open Conversation 后 `history.replaceState` 写入 ID；
- Scope switch / New Chat / delete current 清除 ID；
- mount 时先 load session catalog；如有 ID，读取 detail，恢复合法 navigation scope，再请求该 scope list；
- 无 ID 时保持 unselected，不自动打开最近 Conversation。

## 4. Backend Contract

### 4.1 Web selector

GET 仅接受 `scope_mode`、`session_id`、`limit`。Web 层把它编译为 Conversation domain 的 exact identity
selector；不会构造带 time/max 的 ExecutionScope，也不会允许其他字段穿透。

Validation matrix：

| Input | Result |
| --- | --- |
| `scope_mode=all`, no session | all selector |
| `scope_mode=sessions`, one non-empty session | exact single-session selector |
| missing/unknown mode | 422 `CONVERSATION_SCOPE_SELECTOR_INVALID` |
| all + session / sessions without session | 422 same stable error |
| session not in canonical catalog | 404 `SOURCE_SESSION_NOT_FOUND` |

### 4.2 Domain selector

Conversation Store 使用最小不可变 selector，只表达 `allowed_session_ids=None`（all）或规范化的非空 tuple。
它不是新的 ExecutionScope，也不包含 Retrieval 参数；它只描述 persisted scope snapshot 的 identity。

### 4.3 SQLite filter-before-limit

`list_summaries(selector, limit)` 先构造 predicate：

- all：`scope_snapshot_json IS NOT NULL` 且 `allowed_session_ids` 为 JSON null；
- single session：snapshot 非 null、`allowed_session_ids` JSON array 长度恰为 1，且 `[0]` 等于 session ID。

然后执行：

```sql
SELECT ...
FROM conversations
WHERE <exact scope identity predicate>
ORDER BY updated_at DESC, conversation_id ASC
LIMIT ?
```

legacy SQL NULL 被两类 predicate 排除；multi-session 因 array length 不为 1 被单 session 排除。当前 378 行
规模不需要新增 JSON expression index；先由真实查询和测试证明正确性，未来性能问题再用测量驱动索引。

## 5. ChatLab Inheritance and Trivae Differences

直接继承：一级 Source Session navigation、session-scoped list request、New Chat 继承当前 session、当前项
高亮、列表空状态、URL conversation restore、display buffer 与 background owner 分离。

保留 Trivae 差异：

- Trivae 有明确 `all` Retrieval Scope；ChatLab global chat API 与 session chat API 分开。
- Trivae Conversation 保存 immutable full ExecutionScope snapshot；列表只按 selectable identity 比较。
- Trivae primary UI 不把 multi-session 暴露为可编辑选择。
- Trivae legacy null 不能 resume/send，也不能当作 all。

## 6. Failure Cases and Controls

| Failure | Root control |
| --- | --- |
| C 排在全局第 101，前端最近 100 无 C | SQLite WHERE before LIMIT regression |
| `sessions:[A,B]` 出现在 A | JSON array length + exact identity test |
| A response 晚到覆盖 B | frontend request generation guard |
| scope switch 保留旧 main Conversation | explicit `clearDisplayed()` before refresh |
| unselected send 默认为 all | nullable compile + store-level explicit rejection；删除 all fallback |
| A draft create await 时被 B 改 scope | scope-keyed draft buffers |
| A stream 写入 B | request owner map remains sole write path |
| reload 打开历史但 Scope 未对齐 | detail-first URL restore → selection → scoped list |
| unknown/legacy history 获得合法权限 | read-only compatibility; composer disabled |

## 7. Rollback Shape

改动不迁移表、不改历史数据。回滚产品 commit 即恢复旧 API/UI；SQLite snapshot 仍兼容。新增 query selector 是 Web
interface change，回滚时 Application/Store signature 与前端 client 必须作为同一 commit 集合回退。
