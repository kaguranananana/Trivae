# M2A Read Contract + Structured Retrieval

## Goal

在一次连续 Trellis implementation cycle 内完成 M1 Hardening、M2 Retrieval Core（Read Contract、Structured、Lexical、Context Expansion、Result Contract、Real-data Validation）以及 M3 Capability/Tool Layer。目标是在不破坏 M1 Canonical Store 事实语义的前提下，形成一条可被后续 Agent Runtime 使用的本地 Retrieval + Tool 基础设施。

M2/M3 的每个 milestone 都必须由代码、回归测试或真实数据证据推进；已有 architecture/technical decision 支撑的普通实现细节不再逐项暂停等待确认。只有明确架构冲突、真实 Failure Case 推翻契约、稳定 canonical semantics 将受影响或缺少外部依赖时才停止并报告 blocker。

## Background and Confirmed Facts

- M1 已将 canonical messages 写入 SQLite；`session_id` 是消息边界和身份隔离边界。
- `source_message_id` 不是全局 ID，同一个值可能在不同 session 中出现；`reply_to_source_message_id` 也遵守同样的 session 作用域。
- `seq` 是可选的平台顺序提示，不是始终存在或始终可信的全局顺序。
- M1 已存在按 session/time 和按 session/source 的索引；Structured path 不改 M1 schema，Lexical path 允许新增可重建的 FTS5 derived virtual table，不改变 canonical write semantics。
- Stage 1.3 已确认 Lexical Search -> Search Hits -> 自动 Context Expansion -> Merge/Dedup -> Bounded Trim -> Hit Preservation 的 Retrieval flow；本任务直接实现该 flow 的第一版，不改成由 Agent 二次调用 context tool。
- Stage 1.4 已确认 Capability metadata、input/output contract、bounded result、typed error、execution scope 和 registry 的方向；M3 只包装已验证 Retrieval Core，不重写 SQL/FTS/context。
- 当前不进入 M4 Router/Planner/Agent Runtime、M5 Evidence/Citation、M6 Trace backend、M7 Evaluation runner、HTTP、Frontend、Semantic/Vector Retrieval。

## Requirements

### R1. Read Contract

提供冻结、可类型检查的消息查询契约，至少表达以下字段：

- `session_ids`
- `start_timestamp`、`end_timestamp`
- `sender_user_ids`
- `message_types`
- `source_message_id`
- `reply_to_source_message_id`
- `limit`

时间范围必须是半开区间 `[start_timestamp, end_timestamp)`。契约必须显式拒绝：开始时间晚于结束时间、`limit <= 0`、消息列表查询无界、没有 `session_ids` 却使用 source/reply ID、以及会导致作用域含义不清的空过滤集合。source/reply ID 只能在调用方给出的 session 集合内匹配，禁止全库全局匹配。

聚合查询使用独立的聚合契约，可选择 `session`、`sender` 或 UTC 月份分组，并复用同一组 session/time/sender/type/source/reply 过滤语义。聚合查询允许统计全量匹配行，但不提供消息列表的无界读取。

### R2. Retrieval-facing Projection

消息读取结果必须使用独立的 retrieval projection，至少包含：

- internal message ID 与 source message ID 的明确区分
- session ID
- sender identity（至少 `sender_user_id`，可带平台 ID、UIN 和展示名称快照）
- timestamp、显式 `seq`（缺失时保留 `None`）
- message type
- normalized content
- reply locator
- `recalled`、`system` 等对读取有意义的 canonical 标志

projection 不得暴露 SQLite row、`sqlite3.Row`、raw payload、`content_json`、canonical projection JSON 或数据库列布局。M2A 不解析结构化内容；只有在未来契约明确需要时才新增结构字段。

### R3. Deterministic Ordering

消息结果必须按 `timestamp ASC`，再按存在的 `seq ASC`，最后按 `internal_message_id ASC` 排序。SQL 必须显式处理 `seq IS NULL`，不能依赖 SQLite 默认 NULL 排序；相同 timestamp 且 seq 缺失时，只保证可重复的稳定顺序，不宣称恢复平台真实顺序。

### R4. Structured Retrieval

Structured Retrieval 必须支持参数化 SQL 的 session、半开时间、sender、message type、source ID、reply ID 和 limit 过滤。查询服务只协调契约、仓储调用、结果封装和观测，不直接执行 SQL。

必须提供彼此区分的消息结果与聚合结果类型：

- 消息结果包含 query/scope、`strategy="structured"`、messages、`total_hits`、`returned_count`、coverage、partial、truncated、metadata。
- 聚合结果包含 query/scope、`strategy="structured"`、总计数、聚合桶、coverage、partial、truncated、metadata。
- `total_hits` 表示过滤后的总匹配数，`returned_count` 表示实际返回消息数；limit 造成的截断必须通过 `truncated` 表达。
- 直接读取完整 canonical store 时 coverage 为 complete；coverage、partial、truncated 不能互相替代。
- Structured Retrieval 不执行语义分类；本轮 M2 只新增 lexical/FTS5 与 bounded context expansion，不引入 semantic、embedding、vector、chunk、hybrid、BM25、RRF、reranker 或 evidence/citation。

### R5. Repository Boundary and Lifecycle

新增 `SQLiteCanonicalReadRepository`（或等价命名）作为 data/storage 层的 SQLite 读取边界。所有 SQL、列选择、参数绑定、分组表达式和排序表达式集中在该边界内；retrieval 层不得直接持有或调用 SQLite connection。读取连接使用只读模式并由应用生命周期显式关闭；不得把 M1 write store 改造成 universal store，也不得新增公开 connection API。

### R6. Session Isolation

这是最高优先级验收项：A/B 两个 session 可以拥有相同的 source ID 或 reply ID，但带 session scope 的查询只能返回对应 session 的消息。无 session scope 的 source/reply 查询必须明确失败，不能返回跨 session 的“看似正确”结果。

### R7. Observability and Documentation

结果 metadata 至少能表达 ordering 和查询耗时；实现和测试应保留 query scope、strategy、filters、total、returned、truncated、coverage 等可诊断信息，但不实现 Stage1.9 完整 Trace。

若实现形成新的后端实现契约，同步更新 backend directory/database guideline 和本任务记录；没有架构冲突时不新增 ADR。

### R8. Interview-defense Evidence

本任务遵守项目级 [Interview Defense Evidence](../../spec/project/interview-defense.md) 原则。实现/验证记录必须能够支撑围绕“为什么、替代方案、失败、验证、debug、规模、演进”的连续追问，但不得为了面试制造复杂度或虚构项目事实。

任务记录新增 `validation.md`，只收录 architecture decision、implementation、test、真实 canonical 数据校准、benchmark、evaluation 或真实 Failure Case 能证明的内容，并明确区分 `measured fact` / `engineering expectation`、`real failure` / `regression test case` / `anticipated risk`、`permanently rejected` / `currently unnecessary / waiting for evaluation evidence`。不得为了面试制造复杂度或虚构性能/失败事实。

### R9. M1 Hardening

先检查并补齐 M1 的真实契约缺口：`seq` contract 与代码一致性、canonical conflict projection、typed error code mapping、ingestion Failure Case regression、CLI exit code、transaction rollback、rerun/provenance 幂等和必要 CI/lint/type check。不得重写已经通过真实数据验证的 ingestion 主链路；如果 clean import/rerun 的关键统计变化，必须记录根因并区分 semantic correction 与测试驱动改数。

### R10. Lexical Retrieval

在约 473k canonical messages 的真实规模上比较 `LIKE` 与 SQLite FTS5。若当前 Python/SQLite 支持 FTS5 且真实校准符合 Derived Index 原则，采用本地 SQLite FTS5；否则记录可复现证据和明确 blocker，不静默切换为未经验证的 fallback。

Canonical Store 始终是事实源，FTS 是可重建的 derived data。FTS 必须支持从 canonical messages rebuild，并在导入后通过明确的增量同步或显式 rebuild 保持一致；删除 FTS 不得损失 canonical facts。第一版 lexical 至少覆盖关键词查询、中文关键词、多关键词、空关键词/非法输入、session/time/sender scope、排序和 bounded hits。

### R11. Context Expansion

对 lexical hits 自动取得同 session 的前后窗口，合并重叠窗口、按消息 identity 去重、保持 chronological ordering，并在最终 bounded result 中保留真实 lexical hit。必须覆盖相邻 hits、session boundary、multiple hits 超过 limit、context trim 和空 hit。

### R12. Retrieval Result Contract

实现 Retrieval Core 自己的结果类型，不复用 ToolResult、Citation schema、Trace schema 或 Evaluation Case。结果至少表达 query/filters、lexical hits、expanded messages、total hits、returned messages、truncated/partial、coverage，并保留稳定的 internal/session/source/reply locator。

### R13. Capability / Tool Layer

在 M2 全部验证通过后，实现最小 Capability contract、metadata、input contract、output envelope、bounded semantics、typed errors、execution scope 和 registry。首批实现 `search_messages`，调用链必须是 `Tool -> Capability -> Retrieval Core`；Tool 不直接访问 SQLite、不构造 FTS SQL、不实现 context merge/order/trim。契约测试覆盖 valid/invalid/empty keyword、bound、session/time scope、retrieval error projection、partial/truncated 和 wrapper/core 语义一致性。

## Acceptance Criteria

- [x] 新增的 retrieval/capabilities 目录只包含本轮实际落地的 Read Contract、Structured、Lexical、Context、Result、Capability 和 Tool registry；不预留 semantic、hybrid、reranker、evidence、router、planner、runtime 空壳。
- [x] 消息契约覆盖 session、半开时间、sender、type、source、reply、limit，且非法时间、非法 limit、无界消息查询和无 scope 的 source/reply 查询均显式失败。
- [x] 消息 projection 不泄漏 raw/canonical JSON 或 SQLite 行对象，internal/source ID、session、sender、timestamp、seq、type、normalized content、reply locator 可直接读取。
- [x] 排序在相同 timestamp 下正确处理有 seq、不同 seq、缺失 seq，并重复执行返回相同顺序。
- [x] 参数化 SQL 覆盖所有结构化过滤、limit、count 和 session/sender/month 分组；消息结果与聚合结果为不同类型。
- [x] 结果正确区分 total 与 returned，并独立表达 coverage、partial、truncated。
- [x] 两个 session 的重复 source/reply ID 隔离测试通过。
- [x] 测试覆盖：session、半开时间、sender、type、source 隔离、reply 隔离、多条件、无结果、超过 limit、total≠returned、确定性排序、相同 timestamp 不同 seq、相同 timestamp 缺失 seq、跨 session 重复 source ID、count、按 session/sender/month 分组、非法时间/limit/query scope，共 20 个类别。
- [x] 现有 M1 unittest、相关项目代码 Ruff、mypy 和 `python -m trivae --help` 通过；未出现无 Failure Case 支撑的 M1 行为变更。
- [x] 使用现有真实 canonical 数据做只读校准：消息总数、7 个 session、真实 sender/time/source 查询、相同 timestamp 重复查询顺序和代表性耗时均有记录；不修改 raw 或 canonical 数据。
- [x] `validation.md` 完成事实化记录：Problem / Motivation、Design Rationale、Why not、Failure Cases、Evaluation / Evidence、Observability / Debugging、Scale / Performance、Boundary / Ownership、Evolution，以及 `Interview Defense Notes` 事实索引；没有证据的内容不写成事实。
- [x] M1 hardening 缺口以最小修改补齐并有 regression tests；clean real-data import + rerun 结果和任何统计变化均有根因记录。
- [x] LIKE 与 FTS5 在当前环境完成实际比较；若选 FTS5，index 可 rebuild、与 canonical source ownership 清晰、scope isolation 和中文/多关键词结果有测试。
- [x] Lexical hits 自动完成同 session context expansion、overlap merge、dedup、chronological order、bounded trim 和 hit preservation。
- [x] Retrieval Result 不混入 Tool/Citation/Trace/Evaluation schema，且能表达 hits、expanded messages、total/returned、coverage、partial、truncated。
- [x] M3 Capability registry 与 `search_messages` Tool 完成，并通过 Tool/Core 一致性和 scope/error/bound contract tests。
- [x] M4 Router/Planner/Agent Runtime、M5 Evidence/Citation、M6 Trace backend、M7 Evaluation runner、HTTP、Frontend、Semantic/Vector 保持未实现。

## Scope and Non-goals

### In scope

- M1 ingestion hardening 的真实缺口修复与回归测试
- `src/trivae/retrieval/` 下的 Read Contract、Structured、Lexical、Context Expansion、Result Contract
- `src/trivae/data/storage/` 下的 SQLite canonical read adapter 与 FTS derived index/rebuild boundary
- bootstrap/application 的最小 Retrieval 接线和生命周期管理
- `src/trivae/capabilities/` 下的最小 Capability contract、registry、`search_messages` adapter
- 测试数据库测试、真实 canonical 数据 lexical/context/calibration、必要 backend/technical decision/task 文档同步

### Explicitly out of scope

- semantic search、embedding、vector index、chunk、hybrid、BM25、RRF、reranker
- reply chain、evidence/citation、`get_schema`、`execute_sql`
- router、planner、runtime、HTTP、Frontend、新 Query CLI、OpenAI Agents SDK、LLM、Tool selection、answer generation
- M6 Trace backend 和 M7 Evaluation runner（只保留本任务的事实化 validation record）
- 改变 M1 projection、seq、identity、conflict 或 error mapping；除非在实现中复现并证明真实 Failure Case

## Notes

- 用户已通过 Fast-track implementation mode 明确授权：现有 PRD/Design/Implement 作为基础，增量扩展后直接启动并连续推进本 task；不再为已确定 milestone 逐项等待确认。
- 代码中的新增关键逻辑使用简体中文注释，解释边界、SQL 排序和 session 隔离原因。
