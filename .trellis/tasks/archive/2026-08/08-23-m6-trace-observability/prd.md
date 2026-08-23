# M6 Trace / Observability Vertical Slice

## Goal

让已经完成的 Import / Query 主链路具备一条 Trivae-owned、Local-first、可回放的诊断事实链：一次 Query Execution 可以通过 `request_id + trace_id` 关联，并按单 Trace 的确定性 sequence 回看 Context、Router、Planner、Runtime、Tool、Retrieval、Evidence/Citation、Answer Finalization 与 Conversation commit；失败可以区分根因层、观察层和处理方式。

用户价值是：最终回答不正确、执行被降级、工具返回错误或业务提交失败时，可以先从本地 Trace 判断“发生了什么、在哪一层失败、是否被恢复”，而不是只看到最终文本或 generic error。

## Background and confirmed repository facts

- M1–M5b 已落地：Canonical SQLite / FTS5、Capability/Tool Registry、Router、Soft Planner、单一 Agent Runtime、`RuntimeEvent`、`RuntimeResult`、Tool provenance、AnswerArtifact/Citation finalization，以及独立 SQLite Conversation Store 的 atomic `commit_turn()`。
- `TrivaeApplication.query()` 是正式 Application boundary；当前会在 query 前读取/创建 Conversation，调用 `QueryOrchestrator`，成功 finalization 后调用 `commit_turn()`。
- 当前 `QueryOrchestrator` 只消费 `AgentRuntime.run()`，`RuntimeEvent` 尚未持久化；当前 Application 也没有 `trace_id` 或 Trace read facade。
- Stage 1.9 ADR 已 Confirm：Normalized Event、append-only event、single-trace sequence、operation causality、Failure Attribution、`normal/debug` profile、query-scope coverage、独立 Trace Store、Trace failure 不控制业务、Trace 与 Evaluation 分离。
- Stage 1.11 ADR 已 Confirm：Composition Root 统一拥有 Trace resource，Application facade 提供 traces/import 路径，接口层不得直接读 SQLite 表。
- ChatLab reference 的可继承方向是 core/SDK event → project-owned event → stream/log projection，以及显式 Debug Mode 记录实际 LLM context；ChatLab 的日志文件格式、2000 字符规则、数据库字段和默认 retention 不属于 Trivae contract。

## Requirements

### R1. Normalized Event contract

实现不依赖 OpenAI Agents SDK 的 Trivae-owned normalized event，至少表达：

`schema_version`、`event_id`、`trace_id`、`request_id`、`sequence`、`occurred_at`、`observed_at`、`stage`、`operation`、`phase`、`operation_id`、可选 `parent_operation_id`、可选 `outcome`、可选 `duration_ms`、bounded/redacted `payload`、`limitations` 与结构化 `failure`。

每个 persisted event 有独立 identity；一次 Query Execution 每次都生成新 Trace；同一 Trace 的 sequence 从 1 开始单调递增；timestamp 不用于 replay 排序。`RuntimeEvent` 继续存在，并通过 mapper 成为 normalized Runtime family。

### R2. Collector and SQLite Trace Store

新增清晰的 `observability` ownership，包含 contract、collector、SQLite store、projection 所需的最小模块。Trace Store 使用独立 SQLite connection，不修改 Canonical Chat facts，不把 Trace 写入 Retrieval read connection，也不与 Conversation transaction 组成分布式事务。

Persisted events append-only；数据库约束保证 `UNIQUE(trace_id, sequence)`，读取按 sequence 排序。Trace Store failure 必须显式产生 Trace degraded/incomplete diagnostic，但不能阻止原本可继续的 Query/Agent 业务执行。

### R3. Query vertical-slice instrumentation

Application boundary 生成缺省 `request_id`、创建新的 `trace_id`，并贯穿 Orchestrator、Runtime、Tool、Retrieval、Evidence/Citation 和 commit boundary。`QueryResult` 包含本次 `trace_id`；Application 提供稳定的 `read_trace(trace_id)` 入口。

至少记录以下稳定语义 family（事件具体命名可按 ADR 实现）：

- query/context：received、context prepared、terminal completed/failed/aborted；
- router：decision 与 degraded/failed invocation，包含 route/confidence/reason/source、degradation code 和 latency；
- planner：started、completed/failed/skipped，包含 plan bounded projection、failure category、`executed_without_plan`；
- runtime/model：run、turn、usage、tool round、finalizing、budget/termination、terminal；不逐 token 永久保存；
- tool：name、Trivae tool call/result identity、round、status、latency、error code；
- retrieval：strategy、bounded query/filter、candidate count/identity/rank、coverage、partial/truncated/unavailable、context expansion、latency；
- evidence/citation/answer：finalization、selected source identities、citation validation outcome/unresolved count、limitations、final answer boundary；
- conversation：`answer.commit.started/completed/failed`，且只有真实 commit 成功后才记录 `query.completed`。

### R4. Failure Attribution

失败至少表达 `error_code`、`origin_stage`、`observed_stage`、可选 cause event/operation、`category`、`handling`，以及真实发生时的 retry count/diagnostic reference。

必须保留 Router degradation、Planner failure fallback、Tool Contract Error returned-to-agent、Retrieval failure observed by Tool wrapper、Abort 与 Budget limitation 的区别；recovery 不能删除原始 failure，wrapper 不能夺取底层 failure ownership。

### R5. Normal / Debug capture policy and privacy

提供简单的 `normal` / `debug` profile，不构建复杂 policy framework：

- Normal 保存 IDs、counts、route/status/error/latency/usage、bounded/redacted query/context/tool/retrieval/evidence facts；截断必须可见。
- Debug 在本次 trusted Data Access Scope 内保存更完整的 model-visible/system-visible context、Tool argument/result、Retrieval facts 和 final answer，帮助回答“模型当时实际看到了什么”。
- 两种 profile 都通过 Trace capture boundary 做结构化 key redaction 和 bounded serialization，禁止写入 `DEEPSEEK_API_KEY`、`OPENAI_API_KEY`、Authorization/Bearer/provider credential、`.env` secret、越权数据或 hidden Chain-of-Thought；Debug 不是权限扩张。

### R6. Replay and operational projection

给定 `trace_id`，可在 close/reopen 后 deterministic 恢复 Trace summary、request/trace/profile、terminal status、completeness、timeline、failure attribution 和 operational metrics（latency、model、usage、tool/retrieval count 等）。Projection 从 canonical events 派生，不成为第二套事实；缺少 terminal event 必须为 `incomplete`，不能猜成 completed/failed。

### R7. Import diagnostics projection

复用现有 `import_batches` / `import_errors` / `ImportRunSummary` 事实，提供统一诊断 projection，能按 source file 或 batch 查看 source、batch、received/inserted/duplicates/conflicts/errors/status，以及 error code、record index/locator 和 detail。不把 ImportBatch 强行伪装成 Query Runtime Event。

### R8. Application and thin CLI boundary

Application facade 提供 Trace read 和 Import diagnostics read；CLI 若增加开发诊断命令，只投影 Application 返回的 canonical projection，不直接 `sqlite3.connect` 或解释 raw event。M6 不实现 HTTP/FastAPI/SSE/WebSocket/UI。

### R9. Verification and evidence

新增 contract、persistence、integration、failure-attribution、privacy/profile、projection、Application boundary 和 Import diagnostics tests；完整回归 M1–M5b。使用 temporary SQLite 验证 close/reopen；在不修改用户唯一 canonical DB 的前提下完成真实数据 Query trace smoke；若环境有有效 DeepSeek key，再执行真实 Provider E2E，不让测试依赖网络、不打印 key。

实现记录必须区分 measured fact、regression test case 与 anticipated risk，并沉淀 Router degradation、Planner failure、Tool Contract Error、Retrieval partial、Citation failure、Conversation commit failure、Trace store failure、Abort、missing terminal 等 Failure Case 的发现/归因/Trace 表现/回归保护。

## Acceptance Criteria

- [ ] 每次 Query Execution 都有稳定 `request_id + trace_id`；每次 rerun/regenerate 使用新的 Trace。
- [ ] Normalized Event、Trace projection 和 Application facade 不依赖 OpenAI Agents SDK 类型；`RuntimeEvent` 被映射进同一 normalized event boundary。
- [ ] 单 Trace sequence 确定性递增且重启 replay 稳定；event identity、schema version、`UNIQUE(trace_id, sequence)` 和 append-only 均可测试。
- [ ] Tool → Retrieval 的 `operation_id / parent_operation_id` 因果关系可恢复。
- [ ] Router degradation、Planner failure/`executed_without_plan`、Tool error、Retrieval partial、Citation failure、Conversation commit failure、Abort 和 budget limitation 在 Trace 中保持各自 ownership/handling。
- [ ] `query.completed` 只在 Conversation `commit_turn()` 成功后出现；commit/finalization/runtime failure 不产生 completed Assistant commit。
- [ ] Normal/Debug capture 可工作；payload 有界、secret redaction 可验证，Debug 不记录 CoT 或扩大 scope。
- [ ] 缺少 terminal event 显示 `incomplete`；Trace Store/Collector failure 不控制业务执行且有显式 diagnostic warning。
- [ ] Trace metrics 只表达 operational facts，不引入 M7 quality judgment。
- [ ] Import diagnostics 可通过 Application 稳定读取现有 ImportBatch/ImportError 事实。
- [ ] 新增测试与原有 M1–M5b regression tests 全部通过；完成真实数据 smoke；有 key 时完成 DeepSeek smoke。
- [ ] backend/project 文档补充 implementation record、physical schema、failure cases 和 validation evidence；当前分支 commit 并 push，不 merge main。

## Explicit non-goals

- Embedding/vector/hybrid/reranker、新的 Tool/Planner/Workflow、M7 Evaluation Case/Runner/Judge/quality gate。
- HTTP/API、SSE server、WebSocket、UI、MCP、plugin system、distributed tracing、外部 observability SaaS/OpenTelemetry backend。
- SDK built-in external tracing、逐 token 永久 Trace、hidden Chain-of-Thought、自动 citation repair、无依据 retry/fallback、改变既有 FTS5 ranking 或 AnswerArtifact/Citation 语义。

## Open questions

无阻塞的产品或架构问题。具体 Python class、JSON 序列化细节、SQLite 表名和 CLI 子命令按下述 design/implement 在 Stage 1.9 Confirmed contract 内落地。
