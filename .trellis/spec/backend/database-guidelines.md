# Database Guidelines

> 状态：**M1 SQLite Canonical Store、M2 read/FTS5 derived boundary 已实现；Semantic/Vector 等后续存储仍 Pending**
> Stage 1.4 已确认第一版 persistent store 使用 SQLite；本节同时记录 M1 canonical、M2 read/FTS5 derived 和 M3 读取边界的实际实现契约。

---

## 当前结论

- M1 ingestion 已采用 SQLite 并实现下方最小 physical schema；M2 Structured/FTS5 read boundary 已在实现任务中落地；Semantic/Embedding derived store、迁移演进和跨环境部署策略仍等待后续 Architecture Specification。
- 以下为 Stage 1.2 已确认的**数据库无关原则**，后续任何存储实现都必须满足：

### 已确认的数据库无关原则

- **Canonical Message Store 是聊天数据的 Source of Truth**；Keyword Index、Embedding、Vector Index、Chunk、Topic / Summary Index 等均为 Derived Data，必须可基于 Canonical Store 重建，搜索索引不得成为原始事实来源。
- **Message Identity 区分两个 ID**：Trivae Internal Message ID 与 Platform / Source Message ID 是两个概念，Message 需能通过 source message id 追溯到原始聊天记录（Evidence / Citation 依赖此能力）。
- **逻辑实体**：`Source`、`ChatSession`、`UserIdentity`、`Membership`、`Message`、`ImportBatch` 是已确认的逻辑数据模型；M1 的表映射只服务 ingestion，不冻结后续查询/派生索引物理设计。
- **稳定身份优先**：ChatSession 以 `platform + external_chat_id` 为稳定身份，UserIdentity 以 `platform + platform_user_id` 为稳定身份；群名、昵称等可变字段不能作为身份判断依据。
- **去重优先级**：stable platform/source message id 优先，M1 的缺失 ID fallback 使用结构化字段 key，不能只使用 content hash。M1 对相同 identity 的 payload 采用 canonical first-wins + variant/conflict provenance；后续 mutation semantics 只有被真实 Failure Case 证明需要时才重新决策。

## M1: SQLite Canonical Store Ingestion Contract

### 1. Scope / Trigger

- Trigger：第一条 data-plane ingestion vertical slice 新增 SQLite 持久化、跨层导入入口和可重跑的来源追踪。
- Scope：QQ JSON Adapter → Canonical Model → Shared Importer → SQLite Store → thin CLI。
- 原始 JSON 是只读输入；SQLite 是可重建的 Canonical Store，不承担 Retrieval 或 Embedding derived data。

### 2. Signatures

- `create_application(database_path: Path) -> TrivaeApplication`
- `TrivaeApplication.import_directory(raw_directory: Path) -> ImportRunSummary`
- `PYTHONPATH=src python3 -m trivae import --raw-dir <dir> --database <path>`
- SQLite 核心表：`sources`、`chat_sessions`、`users`、`memberships`、`messages`、`message_sources`、`message_variants`、`import_batches`、`import_errors`。

### 3. Contracts

- ChatSession identity：`platform + external_chat_id`；QQ 新版优先 `chatInfo.peerUid`，旧版只读取文件名中明确的群号，不按群名猜测。
- Message identity：同一 session 优先按 `source_message_id` 去重；缺失时使用包含 session、sender、seq、timestamp、type、content 和 reply locator 的结构化 identity key，不使用 content-only key 或哈希。
- `timestamp` 是必需的有效整数；`seq` 是可缺省的排序提示。缺失、`null` 或空字符串的 `seq` 规范化为 `None`，非空但非法的 `seq` 仍产生记录级错误。缺失 `seq` 时，查询排序使用 `timestamp` 与 `internal_message_id` 的确定性 tie-breaker。
- Error code 由异常类型声明并由 Importer 原样投影到存储；错误消息只用于诊断，不参与分类。当前 M1 类型映射为 `SOURCE_FORMAT_INVALID`、`SOURCE_ID_INVALID`、`RECORD_INVALID` 和通用 `INGESTION_INVALID`。
- `ImportRunSummary.to_dict()` 必须返回 `totals` 和逐文件 `batches`；每个 batch 至少包含 `received_count`、`inserted_count`、`duplicate_count`、`conflict_count`、`error_count`、`status`。
- 每条输入消息在 `message_sources` 中保留 source file + record index provenance；canonical payload 不被后续冲突输入静默覆盖，冲突写入 `message_variants`。
- 每个输入文件独立 transaction；单条记录错误可提交其他有效记录并将 batch 标为 `partial`，文件级解析/身份错误必须形成 `failed` batch。

### 4. Validation & Error Matrix

| 条件 | 处理 | 可观察结果 |
| --- | --- | --- |
| `metadata`/`chatInfo`/`messages` 类型错误或 JSON 非法 | 文件级失败 | `import_batches.status=failed`、`import_errors.error_count=1`、CLI 非零 |
| 无 `peerUid` 且文件名无明确群号 | 文件级失败 | `SourceIdentityError`，禁止按群名合并 |
| 单条消息缺少/非法 `timestamp` 或 content 结构 | 记录级错误 | `import_errors` 定位到 `messages[index]`，batch=`partial` |
| 单条消息的 `seq` 缺失、`null` 或空字符串 | 接受并规范化为 `None` | 不产生错误；排序由 `timestamp` 与 `internal_message_id` 保证确定性 |
| 单条消息的非空 `seq` 非法 | 记录级错误 | `error_code=RECORD_INVALID`，batch=`partial` |
| 已存在相同 session + source message ID | 不新增 `messages` | `duplicate_count` 增加，来源 occurrence 保留 |
| 已存在消息的 invariant projection 不同 | 不覆盖 canonical | `conflict_count` 增加，写入 `message_variants` |
| 同一文件同一记录再次导入 | 幂等重放 | 不新增 message/source/variant，只报告 duplicate |

### 5. Good/Base/Bad Cases

- Good：当前 14 个 JSON 文件导入为 7 个 session，`received=494628`、`inserted=473236`，每个文件都有 completed batch。
- Base：同一目录再次导入，`inserted=0`、`duplicate=494628`，`messages`、`message_sources`、`message_variants` 行数保持不变。
- Bad：使用群名作为 session key、直接覆盖冲突 raw payload、或捕获异常后继续报告成功；这些都会破坏来源可追溯性，禁止实现。

### 5.1 M1 真实数据校准

- 当前 14 个真实 QQ 导出文件的 `seq` 均存在且可解析为整数，因此本次将 `seq` 改为可缺省提示不会改变既有全量统计。
- 当前 2775 个 conflict 与 18617 个 `duplicate_equal` 的 projection 对比中，没有发现“结构化语义不同但 projection 相等”的真实样本。已观察到的 equal 差异集中在导出器表示层：文本占位符空白、`at` 元素拆分/顺序、图片占位符与尺寸元数据、空 URL 与缺失 URL。
- 因此 M1 不扩大 `canonical_projection()`；若未来出现 mention identity、reply target 或附件 identity 不同而 projection 仍相等，必须先增加可复现 Failure Case，再最小化扩展 projection 并重跑全量统计。

### 6. Tests Required

- Adapter unit tests：V5 文件名群号、0.1.0 `peerUid`、两种 message type、timestamp、reply、结构化 fallback。
- Store/import integration tests：同群多文件合并、跨群同 ID 分离、duplicate/conflict provenance、记录级错误可见、幂等重跑。
- Failure-path tests：缺省/非法 `seq`、非法 `timestamp`、文件级格式/身份错误、未知异常回滚、CLI 非零退出与 typed error code。
- Real-run assertions：`sources=14`、`chat_sessions=7`、`messages=473236`、`message_sources=494628`、`import_errors=0`，并逐 session 校验消息数。

### 7. Wrong vs Correct

#### Wrong

```python
session_id = chat_info["name"]
existing.content = incoming.content
```

#### Correct

```python
session_id = f"qq:{authoritative_external_chat_id}"
write_variant_when_projection_differs(incoming)
```

正确实现保留稳定身份和冲突 provenance，使同群增量合并可重建、可核对；未来若修改 mutation semantics，必须由真实 Failure Case 和回归测试驱动。

## 后续待决内容（后续架构到达后）

- Semantic/Vector/Chunk 的 derived store 与查询模式
- 跨环境 migration / backup / deployment 策略
- Vector Store、Embedding 与 Chunk 的物理 schema
- Query Plane 的数据访问 scope 与保留策略

## M2 Retrieval Read / Derived Index Contract

### Read adapter

- `SQLiteCanonicalReadRepository` 使用独立 `mode=ro` connection 和 `PRAGMA query_only=ON`；Retrieval 不持有 Store connection，不返回 `sqlite3.Row`。
- SQL、列选择、scope predicates、aggregate expressions、ordering 和 FTS query 全部集中在 `data/storage`；值使用 parameter binding。
- Retrieval projection 只包含 internal/source ID、session、sender identity snapshot、timestamp、optional seq、message type、normalized content、reply locator、recalled/system；raw payload、`content_json`、`canonical_projection_json` 不出边界。
- source/reply message ID 必须与显式 `session_ids` 同时出现；session predicate 不能省略。时间范围为 `[start_timestamp, end_timestamp)`。
- 消息排序显式为 timestamp、present seq、missing seq、internal ID；missing seq 的稳定顺序不代表恢复平台真实顺序。
- `total_hits`/`returned_count`、`coverage`/`partial`/`truncated` 分别表达匹配总数、返回数、数据覆盖、内部部分完成和 bounded 截断。
- Structured aggregate 支持总数以及按 session、sender、UTC month 分组；NULL sender 保留为真实 NULL bucket，不伪造身份。

### FTS5 derived index

- `messages_fts` 是 SQLite FTS5 virtual table，字段为 `internal_message_id UNINDEXED`、`session_id UNINDEXED`、`source_message_id UNINDEXED` 和 `content_text`；它只服务 lexical retrieval，不是 canonical/evidence source of truth。
- `SQLiteLexicalIndex.rebuild()` 在显式调用时从 `messages` 全量重建，失败回滚 derived transaction；删除 FTS table 不影响 canonical messages。
- Read adapter 在 lexical 查询前比较 FTS row count 与 canonical message count；缺失或 stale index 显式返回 `RETRIEVAL_LEXICAL_INDEX`，不静默 LIKE 降级。
- FTS5 当前使用 `unicode61` literal AND query；它与 LIKE 的 substring 语义不同，尤其中文命中数必须按 lexical contract 和真实校准解释，不能把两个数字当成同一集合。
- 当前不加入自动异步同步；canonical import 后通过 `rebuild_lexical_index()` 明确重建。若后续出现 stale-index 运维 Failure Case，再由证据驱动增量同步/版本标记设计。

### M3 read-facing boundary

- `search_messages` 是本轮最小 Tool registry 名称；Capability 继承 trusted session/time scope、验证 bound，再调用 Retrieval Core 的 lexical + automatic context expansion。
- Tool envelope 只投影 `ok`/`partial`/`error`、`meta.truncated`、typed error 和 Retrieval Result；Tool 不执行 SQL、构造 FTS expression 或实现 context merge/order/trim。

## M5b Conversation Store Contract

Conversation persistence 与 Canonical Chat Store 共用 SQLite database path，但由独立 `SQLiteConversationStore` connection 和 `conversation/` package 拥有；它不修改 `messages` canonical facts，Retrieval read repository 仍保持 `mode=ro` 与 query-only 写保护。

### 1. Scope / Trigger

- Trigger：M5a 已有 validated `AnswerArtifact`，需要在 Application boundary 内形成可重启 replay 的 completed Conversation / Assistant Message。
- Scope：Application history read/create → Runtime / Finalizer → `conversation/` Store → SQLite conversation tables；不扩展到 Trace、Evaluation、HTTP/UI 或 mutation UX。

### 2. Signatures

- `ConversationStore.create_conversation() -> Conversation`
- `ConversationStore.get_conversation(conversation_id: str) -> Conversation`
- `ConversationStore.commit_turn(conversation_id: str, user_content: str, answer_artifact: AnswerArtifact) -> Conversation`
- `TrivaeApplication.query(request: QueryRequest) -> QueryResult`：成功结果包含 `conversation_id`，失败不产生 completed Assistant row。

### 3. Contracts

#### Physical schema

- `conversations(conversation_id, created_at, updated_at)` 保存 Conversation 生命周期。
- `conversation_messages(message_id, conversation_id, ordinal, role, content, created_at, answer_artifact_json)` 保存 completed User / Assistant message；`ordinal` 通过 `UNIQUE(conversation_id, ordinal)` 提供稳定 replay 顺序。
- 外键保证 message 必须属于已存在的 conversation；CHECK 约束保证 User 没有 Artifact、Assistant 必须有 Artifact JSON。
- `answer_artifact_json` 是显式 JSON snapshot，不是 SQLite 可查询的第二套 Evidence truth；Canonical Message 仍是聊天事实 source of truth，历史 Artifact 是回答时的记录。

- Application 先完成 Runtime `completed`、Citation Finalizer、provenance validation 和 trusted hydration，再调用 Conversation Store 的 atomic `commit_turn()`。
- `commit_turn()` 用单 connection 的 `BEGIN IMMEDIATE` 在一个 transaction 中追加 User + Assistant 并更新 `updated_at`；任一 insert、codec 或约束失败都 rollback，不留下半个 turn。
- Assistant rows 读取时必须通过 `deserialize_answer_artifact()` 和现有 AnswerArtifact domain constructors 恢复；损坏 JSON、未知 source type、missing field 或 content mismatch 显式失败。
- MessageSource 保存 current-run locator 与 trusted display snapshot；StructuredSource 保存 locator/value、query scope snapshot 和 execution limitations。历史读取不重新 Retrieval、hydrate 或调用 LLM。
- Conversation history 可编译成 Runtime `ModelContextMessage` 以理解 follow-up，但不转换成当前 `ToolResultRecord`；后续 factual query 必须由新的 run/tool result 取得 fresh evidence。

### 4. Validation & Error Matrix

| 条件 | 处理 | 可观察结果 |
| --- | --- | --- |
| 没有 conversation id | Application 创建空 Conversation | 返回新的 `conversation_id`；后续成功 Query 原子追加一整个 turn |
| 有 conversation id | Store 读取并编译稳定排序历史 | 不重新搜索或 hydration；未知 id 显式 `ConversationNotFoundError` |
| Runtime 未完成、Finalizer 失败或 Artifact 缺失 | 不调用 `commit_turn()` | `QueryResult.is_successful=False` 或显式应用错误；无 completed Assistant row |
| User/Assistant 插入、约束或 codec 失败 | Store 回滚整个 transaction | 不留下半个 turn；SQLite/codec typed error 向上暴露 |
| 历史 Artifact JSON 损坏或 content 不一致 | 领域 codec/constructor 拒绝 replay | `ConversationCodecError`，不静默丢弃或重新生成 |
| 历史 Evidence 被新 Run 重用 | Finalizer 按 current-run provenance 拒绝 | `INVALID_PROVENANCE` |

### 5. Good / Base / Bad Cases

- Good：validated Artifact 经过 `commit_turn()`，close/reopen 后按 ordinal 恢复 User + Assistant，Artifact 与 trusted snapshot 语义一致。
- Base：Conversation 只有 User 或为空时可读取；后续 Query 仍由新 Runtime 产生新的 ToolResult provenance。
- Bad：Runtime/Finalizer 失败仍写 Assistant、把旧 source locator 变成当前 ToolResult，或用 LIKE/SDK Session 替代已定义边界；这些路径禁止实现。

### 6. Tests Required

- `tests/test_conversation.py` 使用真实 temporary SQLite 覆盖 codec round-trip、restart replay、stable ordering、transaction rollback、Application success/failure boundary 与 old Evidence provenance boundary。
- 真实数据 smoke 使用 `messages=473236` 的 SQLite 副本，并显式重建 `messages_fts`；原始 canonical database 不因 smoke 改写。

### 7. Wrong vs Correct

#### Wrong

```python
conversation_messages.append(assistant_text)
```

这会绕过 validated Artifact、current-run provenance 和 SQLite transaction，无法证明 Assistant Message 可回放。

#### Correct

```python
if result.is_successful and result.answer_artifact is not None:
    conversation_store.commit_turn(conversation_id, request.query, result.answer_artifact)
```

Application 只把已完成、已 finalise、已 hydration 的 Artifact 交给 Store，由 Store 在单个 transaction 中写入 User + Assistant。
