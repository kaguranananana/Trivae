# Database Guidelines

> 状态：**M1 已实现 SQLite Canonical Store；Retrieval/Derived Index 等后续存储仍 Pending**
> Stage 1.4 已确认第一版 persistent store 使用 SQLite；本节的 M1 物理 schema 是当前 ingestion vertical slice 的实现契约，不提前决定后续 Retrieval/Embedding 存储。

---

## 当前结论

- M1 ingestion 已采用 SQLite 并实现下方最小 physical schema；Retrieval/Embedding derived store、迁移演进和跨环境部署策略仍等待后续 Architecture Specification。
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
- `ImportRunSummary.to_dict()` 必须返回 `totals` 和逐文件 `batches`；每个 batch 至少包含 `received_count`、`inserted_count`、`duplicate_count`、`conflict_count`、`error_count`、`status`。
- 每条输入消息在 `message_sources` 中保留 source file + record index provenance；canonical payload 不被后续冲突输入静默覆盖，冲突写入 `message_variants`。
- 每个输入文件独立 transaction；单条记录错误可提交其他有效记录并将 batch 标为 `partial`，文件级解析/身份错误必须形成 `failed` batch。

### 4. Validation & Error Matrix

| 条件 | 处理 | 可观察结果 |
| --- | --- | --- |
| `metadata`/`chatInfo`/`messages` 类型错误或 JSON 非法 | 文件级失败 | `import_batches.status=failed`、`import_errors.error_count=1`、CLI 非零 |
| 无 `peerUid` 且文件名无明确群号 | 文件级失败 | `SourceIdentityError`，禁止按群名合并 |
| 单条消息缺少/非法 `timestamp`、`seq` 或 content 结构 | 记录级错误 | `import_errors` 定位到 `messages[index]`，batch=`partial` |
| 已存在相同 session + source message ID | 不新增 `messages` | `duplicate_count` 增加，来源 occurrence 保留 |
| 已存在消息的 invariant projection 不同 | 不覆盖 canonical | `conflict_count` 增加，写入 `message_variants` |
| 同一文件同一记录再次导入 | 幂等重放 | 不新增 message/source/variant，只报告 duplicate |

### 5. Good/Base/Bad Cases

- Good：当前 14 个 JSON 文件导入为 7 个 session，`received=494628`、`inserted=473236`，每个文件都有 completed batch。
- Base：同一目录再次导入，`inserted=0`、`duplicate=494628`，`messages`、`message_sources`、`message_variants` 行数保持不变。
- Bad：使用群名作为 session key、直接覆盖冲突 raw payload、或捕获异常后继续报告成功；这些都会破坏来源可追溯性，禁止实现。

### 6. Tests Required

- Adapter unit tests：V5 文件名群号、0.1.0 `peerUid`、两种 message type、timestamp、reply、结构化 fallback。
- Store/import integration tests：同群多文件合并、跨群同 ID 分离、duplicate/conflict provenance、记录级错误可见、幂等重跑。
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

- Retrieval structured/lexical/semantic 的 derived store 与查询模式
- 跨环境 migration / backup / deployment 策略
- Vector Store、Embedding 与 Chunk 的物理 schema
- Query Plane 的数据访问 scope 与保留策略
