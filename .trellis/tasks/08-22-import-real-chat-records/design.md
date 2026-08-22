# Real chat ingestion vertical slice design

## Change boundary

本任务只实现第一条可运行的 Data Plane ingestion vertical slice：

```text
QQ JSON export
  → QQ Adapter / Normalizer
  → Canonical Model
  → Shared Importer
  → SQLite Canonical Store
  → thin CLI import command
```

最小缺口是仓库当前没有业务 package、导入入口或 Canonical Store，因此真实 `data/raw` 无法进入 Trivae。群合并逻辑实际属于 `data` 层的 session identity 和 message deduplication，不放在 CLI 文件名规则里；CLI 只发现输入文件并调用 Application ingestion facade。

## Roadmap

这份 roadmap 以可运行能力为单位，不把 Stage 1.1–1.11 机械横向实现：

| Milestone | 目标 | 前置 | Definition of Done | 本任务状态 |
| --- | --- | --- | --- | --- |
| M0 | Python distribution、Composition Root、薄 CLI 和测试骨架 | 无 | `PYTHONPATH=src python3 -m trivae --help` 可运行，测试可执行 | included |
| M1 | Canonical Model、QQ Adapter、SQLite Store、共享导入与真实数据合并 | M0 | 14 个 raw 文件可导入，7 个 session，重复/冲突/ImportBatch 可核对，重跑幂等 | included |
| M2 | Structured / Lexical Retrieval 与 bounded context expansion | M1 | 真实数据上可复现的关键词和结构化查询，coverage/partial 显式 | deferred |
| M3 | Capability contract、Tool Registry、首批 Agent-facing tools | M2 | Tool envelope、scope、错误和 bounded result 有 contract test | deferred |
| M4 | QueryOrchestrator、Router、Thin Planner、Agent Runtime 最小 E2E | M3 | CLI query 通过 Application → Orchestrator → Runtime → Tool 链路 | deferred |
| M5 | Evidence / Citation / Answer Artifact | M4 | claim-level citation 可校验并回溯 canonical message | deferred |
| M6 | Normalized Event、Trace Collector 和可诊断 Import/Query projection | M1/M4 | 跨阶段 trace correlation、sequence、failure attribution 可回放 | deferred |
| M7 | Evaluation Case Bundle、runner、真实 baseline 和 regression | M5/M6 | forced-path、paired comparison、Failure Case 可重复运行 | deferred |
| M8 | 基于真实 retrieval failure 的 Semantic / Hybrid Retrieval | M2/M7 | 只有真实 failure/evaluation 证明需要时才增加 | deferred |
| M9 | `/api/v1` HTTP、SSE-like streaming 和产品入口 | M4/M5/M6 | API 与 CLI 复用同一个 Application execution core | deferred |

M2 以后只在当前 vertical slice 的 Canonical Store 和 Application boundary 上继续，不在本任务提前创建 speculative package。

## Input identity and merge contract

### Chat session identity

- `platform` 固定为 `qq`。
- `external_chat_id` 首选 `chatInfo.peerUid`。
- V5 当前不携带 `peerUid`，Adapter 从文件名 `(...<group_id>).json` 或 `_<group_id>_<export_stamp>.json` 读取导出文件明确携带的群号。
- 两个字段都没有时抛出 `INVALID_SOURCE_ID`；不使用 `chatInfo.name` 作为 identity。
- `chatInfo.name` 只是可变 display name；Store 按消息最大 timestamp 更新当前显示名，并保留每个 Source 的原始 chat name。

### Message identity

- stable path：`qq:<external_chat_id>:<message.id>`。
- fallback path：将 session、sender identity、seq、timestamp、canonical type、content 和 reply locator 编码成结构化 JSON identity key；不使用 content-only identity，也不编写 hash/SHA256。
- 同一个 session 只允许一个 canonical message row。
- 同一 stable ID 的后续 payload 不覆盖既有 canonical row；若 canonical invariant projection 不同，写入 variant/conflict provenance，并在 batch summary 暴露。
- 不同 session 的同名或同 message ID 不是同一消息。

### Source normalization

QQ Adapter 统一处理：

- V5 `type_1`/`type_3` 与 0.1.0 `text`/`reply` 等类型；canonical type 从 system flag 和 element kinds 推导，source type 留在 raw payload。
- `timestamp` 统一保留 Unix 毫秒；不从两个版本的展示 `time` 字符串推断时区。
- sender 的 `uid` 优先、`uin` 次之；`未知`/空 sender 只作为 system/anonymous message，不伪造跨群身份。
- `content.text`、elements、resources、mentions、reply locator 和完整 raw payload 都保留，避免只留下拼接文本。

## SQLite implementation-level schema

SQLite 已由 Stage 1.4 确认为第一版 canonical persistent store；以下只是本任务为 M1 落地的最小物理 schema，不把实现字段上升为新的架构 ADR：

- `sources`: input file、adapter、format version、chat name、external chat ID。
- `chat_sessions`: `platform + external_chat_id` unique，current display name 和 observed time range。
- `users`: stable QQ user identity；system sender 不创建伪造 user。
- `memberships`: session-local display fields keyed by session/user。
- `messages`: canonical message，unique by session/source message ID where present，含 raw payload and source reference。
- `message_variants`: duplicate/conflict payload provenance，记录不被选为 canonical 的 source file 和 normalized/raw variant。
- `import_batches`: per-source-file received/inserted/duplicate/conflict/error/status/timestamps。
- `import_errors`: source record index、error code/message 和 raw locator，保留失败可定位性。

消息顺序查询使用 `session_id, timestamp, seq, internal_message_id` 的实现索引；不提前创建 Lexical/Embedding derived index。

## Transaction and error behavior

每个输入文件是一个 ImportBatch 和一个 SQLite transaction：

1. 先解析并验证文件级 metadata、群 ID 和 messages container。
2. 文件内每条可规范化消息进入 shared importer；重复记录不产生第二条 message。
3. 可见的 record error 写入 `import_errors` 并计入 batch；该文件的成功记录仍可提交，但最终 batch 为 `partial`/`error`，命令返回非零状态。
4. 文件级 JSON/metadata/session identity 错误不能静默跳过；该 batch 标记失败并保留错误。
5. 未知异常继续抛出，不转换成“成功导入”或 generic duplicate。

当前真实文件全部有 `message.id`、`seq`、`timestamp`，因此 stable path 是实际主链路；fallback 仅由测试验证，避免为理论场景改变真实导入结果。

## Compatibility and safety

- 原始 JSON 只读，不重写、不删除、不移动。
- SQLite 输出路径由 CLI 参数指定；默认输出到 `data/trivae.sqlite3`，并由 `.gitignore` 排除本地敏感数据。
- Import command 可以在已有数据库上重复执行；唯一约束和 stable identity 使重跑只产生 duplicate/variant observability，不扩大消息数量。
- 当前任务不下载 image/file URL 资源，不把 `/download` 相对 URL 当作本地文件，不丢弃原始资源描述。

## Explicit non-goals

不实现 Retrieval、Embedding、Chunk、Reranker、Tool、Router、Planner、Agent Runtime、Evidence/Citation、Trace Store、Evaluation runner、HTTP API、Streaming、附件下载或原始 JSON 合并覆盖。
