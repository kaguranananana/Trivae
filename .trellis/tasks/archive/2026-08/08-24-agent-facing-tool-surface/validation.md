# Stage A Validation — Dual Retrieval Agent Surface

## 1. Problem / Motivation

本记录先保存 Checkpoint A 的独立证据；Stage B 完成后追加独立的 Context/Member 验证记录。

Stage A 将正常 Application `QueryRequest` 的 Agent-visible retrieval surface 从旧的
`search_messages` 默认入口切换为 `lexical_search` + `semantic_search`。旧入口仍保留，
但只作为明确的 compatibility boundary。目标是让模型在精确词面和语义表达不同的查询之间
自行选择已经存在的两条 Retrieval Capability，不在 Tool 层偷偷合并、改写或 fallback。

问题归属 Application Query 编译、Runtime prompt/tool description 和 Evaluation 观察层：
底层 lexical/semantic capability 已存在，Stage A 不改变其索引、模型或检索参数。

## 2. Design Rationale

| Problem | Considered option | Selected option | Trade-off |
| --- | --- | --- | --- |
| 正常 Agent 默认只看到旧入口 | 直接删除 `search_messages`；或者把低层 Runtime 所有默认也改成双 Tool | Application `QueryRequest` 默认编译双 Tool，保留低层 `AgentRunRequest` 的 legacy 默认 | 正常 CLI/生产路径获得 canonical surface；直接构造低层 Runtime 的旧 caller 不被无意破坏 |
| 模型无法区分两条 Retrieval Path | 固定 hybrid/RRF；或者只在代码中硬编码路由 | 在 prompt 和 Tool description 中提供简短 selection guidance，让 Runtime 模型选择 | 不保证每次选择最优，但保留 Agent 调查和多 Tool call 的真实行为 |
| Agent 需要补查 | 新建 hybrid pipeline 或 candidate state | 允许同一 Runtime 内继续调用另一个 visible retrieval Tool | Tool round 和成本可能增加，但 Trace/Evidence provenance 保持同一条正式链路 |

## 3. Why not

- 固定 hybrid、RRF、reranker、query rewrite 和 multi-query expansion：当前任务明确不采用，
  等待 Agent behavior Evaluation 与 Failure Case 证据。
- semantic unavailable 时自动 lexical fallback：当前明确不采用。Semantic Tool 的
  unavailable/stale 状态必须作为显式 Tool failure 保留。
- 删除 `search_messages`：当前不采用。已有 tests、Evaluation 和低层 callers 仍需要
  明确的兼容入口。

## 4. Failure Cases

### FC-A1 — Smoke harness closed an async application in a running event loop

- Type: `real failure`, harness-only。
- Scenario: 初次 Provider smoke 在 `asyncio.run()` 内调用同步 `application.close()`。
- Observed failure: `RuntimeError`，业务 Query 已完成但 smoke 进程退出时关闭路径报错。
- Root cause: harness lifecycle 用错同步/异步 close 边界，不是 Tool、Runtime 或 Retrieval failure。
- Fix: smoke harness 改为在同步入口创建 Application，并在 async runner 的 `finally` 中调用
  `await application.aclose()`。
- Validation: 修正后的四个真实 Provider smoke 均完成并正常释放临时 snapshot。

### FC-A2 — OpenCode Go tool turn produced an invalid final artifact

- Type: `real failure`。
- Scenario: 初次 lexical/multi Provider smoke 在 Tool execution 后返回 prose/Markdown，而不是
  Finalizer 要求的 JSON object。
- Observed failure: citation/finalization 以 `INVALID_ANSWER_ARTIFACT` 终止；不能把未验证文本
  当成成功回答。
- Root cause: 真实 `opencode-go` 在携带 tools 的 Chat Completions 请求中去掉了 JSON mode，导致
  Tool turn 后的最终文本不稳定。
- Fix: 同一 Provider、同一输入上只做一次显式的无工具 finalization，保留原始 JSON mode；首次
  非 JSON 文本不进入 Runner/Evidence，Trace 追加公开的
  `provider_compatibility/json_finalization_repaired` observation。没有解析 prose、静默提交
  preview 或无限重试。
- Validation: 历史失败 `trace-ae73fdec9fbd4db88068c8cc77efcc97`；单元测试覆盖 repair 边界；最终
  acceptance `trace-941878b7ff83430aa12901d33d252a79` 真实命中 repair observation 并完成
  `answer_artifact`、Evidence/Citation。

### FC-A3 — Semantic context expansion exceeded Tool Result transport bound

- Type: `real failure`。
- Scenario: 真实 semantic result 的 bounded context expansion 生成超过 `ToolResultRecord` 的
  100-item transport bound。
- Observed failure: Tool adapter 报 `tool result items exceeds 100`，属于 Tool Result contract
  failure，而不是 semantic index unavailable。
- Root cause: semantic retrieval 原先把 expansion limit 放大到 `limit * 32`，在 10-hit 请求中
  可能恢复 101 条 message。
- Fix: 把 context expansion transport bound 收敛到现有 `ToolResultRecord` 上限 100；dense
  candidate pool、Qwen 模型、dimension、chunking 和 semantic 参数不变，超出 coverage 仍明确
  返回 `partial/truncated`。
- Validation: `tests/test_semantic_retrieval.py` 锁定该 bound；最终 semantic smoke 的 Tool
  状态为 `partial` 但 Query、Evidence/Citation 均成功。

### FC-A4 — Provider transport SSL failure remains explicit

- Type: `real failure`。
- Scenario: 一次 semantic-first rerun 中，semantic 与 lexical Tool 都完成后，下一次
  `opencode-go` 请求约 120 秒后以 `SSLError` 终止。
- Observed failure: `trace-a45aaa44a95a4e02ba7abfbbdc8c8513` 的 `runtime.run` 为
  `RUNTIME_ERROR`；没有 silent lexical fallback，也没有伪造 Evidence。
- Root cause: 当前 Trace 只有 Provider transport 层证据，不能进一步证明 upstream certificate 或
  endpoint 根因；不把它误判成 Retrieval、scope 或 Tool contract failure。
- Current handling: 保留 terminal error，不增加自动 retry/fallback。相同 semantic case 的
  手工复跑 `trace-9c562bb4b91946b2ac066fb5eda256fa` 成功，最终 acceptance
  `trace-7f2a314618c04d3f9fb21c73561d3074` 也成功；因此本轮将它记录为 intermittent external
  provider observation，而不是隐藏掉的代码成功。

### FC-A5 — Agent selection briefly used same-intent query expansion

- Type: `real failure` / Agent behavior diagnostic。
- Scenario: 初版 guidance 较弱时，真实模型把同一个 semantic 意图改写成中文和英文两次调用，
  也曾把 `sqlite-vec` 改成 `sqlite_vec` 重复 lexical search。
- Root cause: description 只说明适用场景，没有明确首选顺序和“不要用同一路径做翻译/同义词/
  标点变体扩展”的边界。
- Fix: 补充首轮 selection guidance、结果足够即停止、弱结果才切换另一条 path，以及禁止
  multi-query expansion loop；不增加 query-specific router 或 Runtime call blocker。
- Validation: 最终 acceptance 中 semantic-dominant 首选 `semantic_search`，no-result 只调用一次
  `lexical_search`；multi-search 的额外调用来自用户明确的复合问题，作为 cost/selection
  observation 保留，不伪造唯一正确 sequence。

### FC-A6 — Semantic index unavailable remains explicit

- Type: `regression test case`。
- Scenario: 临时空 Canonical DB 只显式 rebuild lexical index，semantic index 未 ready。
- Expected/observed: `semantic_search` 返回 `SEMANTIC_INDEX_NOT_READY`；不会转换成
  lexical success。对应 Trace 同时保留 Tool selection 和 explicit failure。
- Validation: `tests/test_agent_tool_surface.py` 的 semantic unavailable test。

## 5. Evaluation / Evidence

### Deterministic contract evidence

- `QueryRequest()` 默认 capabilities 为 `("lexical_search", "semantic_search")`。
- 显式 `available_capabilities=("search_messages",)` 仍可工作。
- Runtime model-visible Tool surface 和 prompt 中包含两个 canonical retrieval Tool 及 selection
  guidance；旧名仅在 compatibility description 中出现。
- 同一 Runtime 的 lexical → semantic scripted call 共享 `run_id`、scope、Trace 和 ToolResult
  provenance；未新增 Runtime、Evidence 或 Query pipeline。
- Evaluation snapshot 记录 `first_selected_tool`、完整 `tool_sequence`、retrieval sequence、
  tool count、tool rounds 和 tool errors；这些字段是 behavior observation，不是 human quality
  label。

### Real Provider smoke evidence

Smoke 使用当前真实 Canonical Snapshot 和已构建 semantic index 的临时副本，Provider 为
`opencode-go` / `deepseek-v4-flash`。没有把真实聊天正文写入 Git；只保留下表的元数据和
Trace IDs。

| Case | First / actual sequence | Calls / rounds | Final state | Wall time | Trace |
| --- | --- | ---: | --- | --- | --- |
| lexical-dominant | `lexical_search → semantic_search` | 2 / 2 | completed; 1 Evidence / 1 citation | ~91s | `trace-941878b7ff83430aa12901d33d252a79` |
| semantic-dominant | `semantic_search → lexical_search → lexical_search` | 3 / 2 | completed; 3 Evidence / 3 citations | ~60s | `trace-7f2a314618c04d3f9fb21c73561d3074` |
| multi-search | `lexical_search → semantic_search → lexical_search → lexical_search → semantic_search` | 5 / 2 | completed; 2 Evidence / 2 citations | ~158s | `trace-b51157f7ae764b14ba9fc1e441dc0300` |
| no-result | `lexical_search` | 1 / 1 | completed; 0 Evidence / 0 citations | ~68s | `trace-72409e145a4046beb9861323f23b1cc5` |

The final acceptance run 的四个 `success` 均为 true，Trace 均为 `completed/complete`，没有
`RUNTIME_ERROR` 或 finalization error。Runtime usage（按 case）为 lexical `56,294`、semantic
`120,446`、multi `180,441`、no-result `4,820` total tokens；这些是当前 Provider/index 的
diagnostic observation，不是 production SLA，也不是调整 `dense_top_k`、model、dimension 或
chunking 参数的依据。真实聊天正文、raw transcript 和 credentials 不进入 Git。

最终行为观察：lexical-dominant 首选 lexical，semantic-dominant 首选 semantic；弱/partial result
后模型可能继续另一条 path，multi-search 的复合问题也可能产生更多 Tool call。Evaluation 记录
这些实际行为和成本，不把某一条 sequence 硬编码为唯一答案。既有 paired lexical-only vs
semantic-only retrieval evaluation 保持不变，label 仍为 `llm_assisted_provisional`，从不自动
改成 `human_verified`。

## 6. Observability / Debugging

The Stage A Trace path exposes the user-query boundary, visible capabilities, model Tool action and
arguments, Tool result status (`ok`/`partial`/error), retrieval result summary, subsequent Tool call,
Evidence/Citation finalization and final Query outcome. It does not persist hidden chain-of-thought.

The smoke traces distinguish:

- selection/runtime problem: first selected Tool、model-visible arguments 和 terminal
  `diagnostic_type=SSLError`；成功重跑与失败 trace 可并存，不互相覆盖；
- retrieval status: lexical `ok`, semantic `partial`, candidate/empty summaries;
- answer contract problem: `citation.validation.failed`、`INVALID_ANSWER_ARTIFACT`，以及成功的
  `provider_compatibility/json_finalization_repaired`；
- Router degradation: `ROUTER_COMPLETION_TIMEOUT` with `static_route_retained`，最终仍由 Trace
  明确标记；
- no-result: completed query with zero Evidence/Citation, rather than fabricated evidence.

## 7. Scale / Performance

The smoke snapshot contains 473,236 canonical messages and a real semantic index of the same
canonical corpus. Semantic KNN and large model-visible Tool Results were the dominant observed costs;
the final acceptance wall time varied from roughly 60 to 158 seconds per case. No index/model/parameter
change is justified by this small diagnostic sample. A larger benchmark or verified Agent behavior
dataset is required before changing retrieval bounds or adding another retrieval architecture.

## 8. Boundary / Ownership

```text
Application QueryRequest compilation
  → Agent Runtime visible Tool registration / model selection
  → Tool adapter and CapabilityRegistry
  → lexical/semantic Retrieval and Canonical bounded context
  → ToolResultRecord / Evidence / Citation
  → TraceCollector + EvaluationRunner
```

Stage A owns the canonical Agent-facing registration, descriptions, default surface and behavior
observation. It does not own embedding generation, semantic chunking, SQLite schema, Router policy,
Planner policy, answer semantic correctness or a second Evidence/Trace system.

## 9. Evolution

Stage B context/member behavior is recorded below as a separate checkpoint. Stage C structured SQL
validation is recorded in section 12 below. A future hybrid, reranker, query rewrite or retrieval parameter change
requires a reproducible Failure Case plus paired/Agent Evaluation evidence. A repeated Provider SSL
failure needs provider transport diagnostics or configuration evidence before any further compatibility
change is considered.

## 10. Interview Defense Notes

- Q: 为什么 Tool 与 Capability 分离？ 证据：Stage 1.4 ADR、现有 CapabilityRegistry、
  `tests/test_agent_tool_surface.py` 的 canonical Tool registration。
- Q: 为什么 lexical 与 semantic 作为两个 Tool？ 证据：QueryRequest default、prompt/tool
  descriptions、A1/A2 diagnostic expectations 和真实 smoke 的实际 sequence。
- Q: 为什么不固定 hybrid？ 证据：Stage A 只提供 selection guidance；同一 Runtime 的多 Tool
  call 由模型实际决定，Trace 记录它而不伪造唯一序列。
- Q: 如何区分选错工具、工具搜错和答案错？ 证据：visible Tool/selection events、retrieval
  status、`INVALID_ANSWER_ARTIFACT` citation/finalization events 和 FC-A2/FC-A4。
- Q: 为什么 semantic unavailable 不 fallback？ 证据：semantic unavailable regression 和
  Stage 1.3/1.4 failure contract；真实实现保持 explicit error（FC-A6）。
- Q: 这轮真实运行证明了什么？ 证据：四个 Provider smoke trace；它证明了 surface、sequence、
  error attribution 和 no-result transparency 可被观测，但不证明 Agent answer quality、
  production latency SLA 或 paired retrieval 的 human-verified correctness。

## 11. Stage B Validation — Context and Member Tools

### 11.1 Scope and implementation evidence

Stage B 增加了两个 Agent-facing Tool，并继续使用同一个正式链路：

```text
Agent Runtime
  → get_message_context / find_members Tool adapter
  → CapabilityRegistry
  → ContextExpander / Canonical SQLite read adapter / UserIdentity + Membership
  → ToolResultRecord
  → Evidence/Citation + TraceCollector + EvaluationRunner
```

- `get_message_context` 复用 `ContextExpander` 和 Canonical message projection；显式读取只在
  trusted `ExecutionScope` 内执行，保持同一 session、时间边界和 transport bound，并把
  `explicit_deepening=true`、`automatic_search_context=false` 写入结果/Trace。
- `find_members` 复用现有 `users`、`memberships` physical tables，按 stable UserIdentity
  去重，并返回 nickname、group card、display/identity、alias-like `remark` 的匹配依据及
  scope 内全部 Membership。当前 schema 没有独立 alias 列，因此 `alias` 是 `remark` 的明确
  Agent-facing 投影，不新增第二套 identity model。
- 多候选是正常结果；Tool 不引入 `resolve_member`、candidate state machine 或唯一人物推断。
- Member candidate row 作为 existing `StructuredSource` 进入 ToolResultRecord；Finalizer 继续
  校验 current-run locator、exact `value_snapshot` 和 scope，没有放宽 citation contract。

### 11.2 Deterministic validation

`tests/test_stage_b_tools.py` 覆盖 10 个 Stage B contract/integration cases：

- context success、same-conversation boundary、invalid message ID、session/time scope、
  bounded truncation、input window bound；
- unique member、same nickname ambiguity、alias-like remark、multiple sessions、unknown member、
  requested-session scope violation 和 result bound；
- SDK 默认 Tool surface、同一 Runtime 的 `find_members → lexical_search`、Trace 内部 operation、
  public tool count 去重、transcript summary、Message/Structured provenance 和 Finalizer row
  citation；
- Evaluation behavior projection 新增 `context_tool_sequence` 与 `member_tool_sequence`，仍只
  记录公开行为事实，不生成 `human_verified` 质量判断。

最终本轮本地质量结果：`pytest` 全量 `264 passed`；Stage B focused `10 passed`；`ruff check`
和 `mypy src` 均通过。

### 11.3 Real Provider smoke evidence

Smoke 使用当前真实 Canonical Store（473,236 条消息）和已构建 semantic index，Provider 为
现有配置 `opencode-go / deepseek-v4-flash`。只保存 query category、Tool sequence、round/count、
Trace、Evidence/Citation、usage、latency 和 failure category；真实聊天正文、身份查询值、raw
transcript 和 credentials 没有进入 Git。

| Case category | Actual sequence | Calls / rounds | Final state | Evidence / citations | Trace | Observation |
| --- | --- | ---: | --- | ---: | --- | --- |
| member → lexical | `find_members → lexical_search` | 2 / 1 | `completed/complete` | 2 / 2 | `trace-58e9399de36f47d6a692f9b77ee146ea` | 68.5s, 9,506 total tokens |
| required context deepening | `lexical_search → semantic_search → get_message_context` | 3 / 3 | `completed/complete` | 3 / 3 | `trace-bc259f1fc6194e77890f3fca265ed8b6` | 228.1s, 80,547 total tokens; semantic result `partial` remained visible |
| member ambiguity | `find_members` | 1 / 1 | `completed/complete` | 1 / 1 | `trace-e401f4d785064bc0b1a350382a50bd6f` | 36.4s, 6,964 total tokens |
| no-result | `lexical_search` | 1 / 1 | `completed/complete` | 0 / 0 | `trace-fcc1a703c1ab4fd7aa5cfbb00f66e5e9` | no evidence was fabricated |

这里的 latency/usage 是当前 Provider、真实 snapshot 和本次模型行为的诊断事实，不是 production
SLA，也不是调整 dense top-k、embedding、chunking 或引入 hybrid 的依据。`semantic_search` 的
`partial` 没有被静默转换为 lexical success；required-context case 的第二次检索由 Agent
选择，随后才调用 explicit context。

### 11.4 Stage B Failure Cases

#### FC-B1 — Omitted member limit used static default

- Type: `real failure`。
- Scenario: 真实 Provider 在 scope `max_results=5` 下省略 `find_members.limit`。
- Observed failure: Python function static default `20` 进入 Capability，返回 `INVALID_ARGUMENT`；
  Agent 随后重试才完成，因此不能视为干净 smoke。
- Root cause: provider-facing JSON Schema 的动态 default 没有改变 SDK adapter Python function 的
  runtime default。
- Fix: `FindMembersSDKToolAdapter` 根据 trusted bound 设置闭包内 dynamic default；显式越界参数
  仍由 Capability 返回 `INVALID_ARGUMENT`，没有扩大 scope 或改用其他数据源。
- Validation: scripted SDK case 现在省略 limit 仍直接成功；修复后真实 member → lexical 与
  member ambiguity smoke 均无 Tool error。

#### FC-B2 — Member structured citation used message-shaped source

- Type: `real failure`。
- Scenario: `find_members → lexical_search` 两个 Tool 都成功，但模型把 candidate structured
  provenance 按 message source 形状生成。
- Observed failure: production Finalizer 返回 `INVALID_SOURCE`，Trace terminal 为 failed；没有
  提交未经验证的 AnswerArtifact。
- Root cause: prompt 只说了 structured source 的字段名，没有明确指出 `find_members` candidate
  必须从 `provenance.structured_sources` 复制完整 `locator_kind/locator/value_snapshot`。
- Fix: 补充 structured candidate citation contract；Finalizer 校验保持不变，并增加 exact row
  value 的 deterministic regression。
- Validation: 修复后真实 member → lexical case 为 `completed/complete`、2 Evidence/2 citations；
  unit test 验证 member row 可以通过现有 StructuredSource finalization。

#### FC-B3 — Context call is not mechanical

- Type: `Agent behavior diagnostic`，不是 Tool failure。
- Scenario: 一次仅要求搜索并回答的 query 实际只调用 lexical；没有因为 visible surface 增加就
  自动调用 `get_message_context`。
- Observation: 当问题明确要求前后三条消息时，Agent 使用
  `lexical_search → semantic_search → get_message_context`，并完成 Citation；Trace 能区分
  retrieval completion 与 `context.expansion.completed`。
- Handling: 不在 Runtime 固定 context call；继续让 Agent 根据局部上下文是否足够作选择，并由
  Evaluation 记录 sequence/round/cost。

### 11.5 Observability and interview evidence

Trace/Transcript 现在可以显示：用户 query、visible capabilities、member/context Tool action、
arguments、candidate/message result summary、是否继续 retrieval、explicit context deepening、
Evidence/Citation 和 final outcome；`project_trace` 的 `tool_count` 只统计公开
`tool.call.completed/failed`，不会把 `member.lookup.*` 或 `context.expansion.*` 内部事件重复计算。
hidden chain-of-thought 仍不落盘。

Stage B 的答辩事实索引已补入 `interview-defense.md`：为什么 Search 自带 bounded context 仍保留
显式 deepening、为什么身份查询返回候选而不是唯一 resolve、为什么 member row 使用 structured
Evidence、以及如何用 FC-B1/FC-B2/FC-B3 区分 Tool contract、Agent selection 和 Finalizer 错误。

## 12. Stage C Validation — Structured Schema and SQL Tools

### 12.1 Scope and implementation evidence

Stage C 增加 `get_schema` 与 `execute_sql`，但继续沿用同一个正式链路：

```text
Agent Runtime
  → get_schema / execute_sql Tool adapter
  → CapabilityRegistry
  → SQLiteCanonicalReadRepository Structured SQL port
  → public physical schema / scoped read-only SQL
  → ToolResultRecord / StructuredSource
  → TraceCollector + EvaluationRunner
```

- `get_schema` 读取现有 Canonical SQLite 的 public physical projection，只暴露
  `chat_sessions`、`users`、`memberships`、`messages` 及允许的列/关系；raw payload、ingestion
  diagnostics 和 lexical/semantic derived tables 不进入 Agent schema。没有新增 Analysis View。
- `execute_sql` 接收一条原始 SQL，通过独立 `mode=ro` connection 执行；不追加 LIMIT、不重写
  SQL、不静默 fallback。结果上限取 trusted `ExecutionScope.max_results` 与现有
  `ToolResultRecord` 100-item transport bound 的较小值，超限显式 `truncated`。
- partial session/time scope 在 driver authorizer 安装前 materialize 同名 temporary public
  tables；模型仍使用 public table names，SQLite authorizer 拒绝 `main` 越界读、写/DDL、PRAGMA、
  ATTACH、内部表和非 public 列。模型是否写 `WHERE session_id = ...` 不决定权限。
- SQL rows 和 schema tables 以 existing `StructuredSource` row locator 进入 Evidence/Finalizer；
  zero rows 是 `ok` 的空 structured result，SQL error 作为 Tool Envelope error 返回。

### 12.2 Deterministic validation

`tests/test_stage_c_tools.py` 覆盖 7 个 Stage C contract/integration cases：

- public physical schema inspection 与内部表/列隐藏；
- COUNT、GROUP BY、sender/session aggregation、time range 和 public JOIN；
- zero rows、malformed SQL、write/DDL/ATTACH/PRAGMA/internal schema rejection；
- session/time trusted scope、显式 `main` escape、结果 bound/truncation；
- SQL row `StructuredSource` finalization；
- schema/SQL Trace operation、public tool count、summary/transcript；
- scripted `get_schema → execute_sql` 同一 Runtime，以及六个 canonical Tool 的默认装配。

本地 Stage C focused 结果：`7 passed`。当前全量结果：`272 passed`；`.venv/bin/ruff check
src tests` 和 `.venv/bin/mypy src` 均通过。`AgentRunRequest` 低层默认仍保留
`search_messages` legacy contract；Application `QueryRequest`/CLI 默认 surface 已是六个
canonical tools，旧入口仍可显式调用。

### 12.3 Failure Cases

#### FC-C1 — Unqualified SQLite READ callback has no database name

- Type: implementation failure，已修复。
- Scenario: unrestricted SQL `SELECT COUNT(*) FROM messages` 被 authorizer 当成 scope escape。
- Observed failure: SQLite authorizer 的 `SQLITE_READ` callback 对未限定表名返回
  `database=None`，初版只允许 `main`/`temp`，导致正常 COUNT 返回 `SQL_SCOPE_VIOLATION`。
- Root cause: 把 Python sqlite3 authorizer 的 database 参数误认为始终包含 `main`/`temp`。
- Fix: full scope 下允许 public table 的 `database=None`；partial scope 预先为全部 public table
  建立同名 temporary shadow，未限定 public read 只命中 scoped temp projection；显式
  `main.messages` 仍被拒绝。
- Validation: COUNT、JOIN、session/time scope 和 explicit main escape 回归测试均通过。

#### FC-C2 — Canonical identity uses normalized platform user ID

- Type: test fixture failure，已修复。
- Scenario: sender aggregation 预期使用 fixture 的 raw `u1`，Canonical Store 实际保存
  `qq:uid:u1`。
- Root cause: Stage C 测试绕过了 Canonical identity normalization 的既有 contract。
- Fix: 测试按 public canonical `sender_user_id` 断言，没有修改 identity model 或 SQL Tool。

#### FC-C3 — Structured SQL Tool success did not imply a valid final citation artifact

- Type: real Provider Agent/finalization failure，已定位并修复提示 contract。
- Scenario: `get_schema → execute_sql` 两个 Tool 都返回 `ok`，但最终 JSON 的
  `citation_bindings.evidence_ids` 没有与同一对象的 `evidence_items.evidence_id` 对齐。
- Observed failure: `trace-ea31a454943b4bd1a52d6ebb31df5ce8` 的 Query termination 为 runtime
  `completed`，但 finalizer 返回 `INVALID_ANSWER_ARTIFACT`，错误为
  `citation binding references an unknown evidence ID`；未提交未经验证的回答。
- Root cause: Provider 遵循了 Tool sequence，却把示例中的 `e1` 当成 placeholder，违反了已有
  Artifact identity contract；不是 SQL、scope 或 Evidence hydration 失败。
- Fix: 在既有 final synthesis prompt 中明确要求 binding/evidence/content block 三组 identity
  必须在同一 JSON 内 exact match；不放宽 validator、不静默补 citation、不重试另一数据源。
- Validation: 修复后的同类真实 case 重新执行并记录在下方；仍保留本次失败 Trace 作为诊断证据。

#### FC-C4 — Agent sometimes used a second SQL call for intermediate confirmation

- Type: real Provider Agent behavior observation，不是 Tool contract failure。
- Scenario: aggregation、time-range 和 scoped-count cases 都先执行了 schema→SQL，随后又执行
  一次 SQL；这些调用仍在同一 Runtime、同一 scope 和同一 Evidence 链路内完成。
- Observation: 当前 Trace 可见实际 sequence 和每次 returned rows/columns；没有静默合并、固定
  hybrid 或 Runtime blocker。第二次调用有时用于确认时间换算/聚合事实，但也增加了 round、token
  和 latency cost。
- Handling: 不把唯一 sequence 写成硬脚本；Evaluation 记录 `sql_tool_sequence`、call count、
  rounds、usage 和 latency，后续只有在重复、可复核的 unnecessary-call failure evidence 足够
  时才调整 prompt/Planner。

### 12.4 Trace / Evaluation / real smoke status

Trace 已记录 `schema.inspect.*`、`sql.execute.*`、tool arguments、table/row summary、columns、
truncation、coverage、scope enforcement 和 SQL rewrite=false；不保存 hidden chain-of-thought。
Evaluation 新增 `diagnostics/agent-tool-selection-stage-c-v1.json`，保留
`schema_tool_sequence`/`sql_tool_sequence` 等公开行为 observation；preferred sequence 只是
`diagnostic_contract_expectation`，不是 `human_verified` ground truth。既有 paired
lexical-only vs semantic-only retrieval evaluation 未删除。

真实 Provider smoke 使用当前 Canonical Store（473,236 条消息）和已完成 semantic index，Provider
为现有配置 `opencode-go / deepseek-v4-flash`。只保存公开行为元数据；没有输出或提交聊天正文、
完整 SQL rows、raw transcript 或 credentials：

| Case | Actual sequence | Calls / rounds | Final state | Evidence / citations | Duration / total tokens | Trace |
| --- | --- | ---: | --- | ---: | ---: | --- |
| schema → count（修复后） | `get_schema → execute_sql` | 2 / 2 | `completed/complete` | 1 / 1 | 26.1s / 17,183 | `trace-88d5cec414a2436594a3cc004e1d4d55` |
| aggregation | `get_schema → execute_sql → execute_sql` | 3 / 3 | `completed/complete` | 1 / 1 | 47.2s / 31,557 | `trace-154afe7c6f5d4345a674d6dff17ec66a` |
| time range | `get_schema → execute_sql → execute_sql` | 3 / 3 | `completed/complete` | 1 / 1 | 42.2s / 28,142 | `trace-23476435f2d54a81826374552c5059f8` |
| structured zero count | `get_schema → execute_sql` | 2 / 2 | `completed/complete` | 1 / 1 | 19.1s / 17,491 | `trace-e5db7689a0d2456b94855550078adf3c` |
| scoped count | `get_schema → execute_sql → execute_sql` | 3 / 3 | `completed/complete` | 1 / 1 | 12.3s / 26,460 | `trace-31d9777e31154a708acf2fceb1263bca` |
| SQL zero rows | `get_schema → execute_sql` | 2 / 2 | `completed/complete` | 0 / 0 | 12.1s / 19,430 | `trace-f2847654eb8448a594214dc0d9b15e94` |

真实 smoke 的结构化结果均保持 `sql_rewritten=false`、`partial=false`；SQL zero rows 的 Trace
明确记录 `returned_rows=0` 和 0 Evidence/0 citations，没有把空结果编造成消息证据。初次 schema→
count 的失败 Trace `trace-ea31a454943b4bd1a52d6ebb31df5ce8` 保留为 FC-C3；修复 prompt 后重跑
成功。以上 latency/usage 是当前 Provider 和运行时的诊断事实，不是生产 SLA，也不是调整 SQL
bound、semantic 参数或增加新架构的依据。

Checkpoint C commit 在本节完成、Trellis validation 和质量门禁重新确认后创建。

## 13. Six-tool comprehensive diagnostic — 2026-08-24

### 13.1 Diagnostic catalog and boundary

本轮新增 `evaluation/diagnostics/agent-tool-selection-comprehensive-v1.json`，包含 14 个
version-controlled diagnostic cases：

- lexical/semantic dominant、context deepening 与 context-sufficient 对照；
- unique/ambiguous/unknown member、member → retrieval；
- COUNT、GROUP BY、mixed retrieval + SQL、structured zero rows；
- lexical/semantic no-result、scope-sensitive mixed execution。

所有 case 的 `available_tools` 恰好是：
`lexical_search`、`semantic_search`、`get_message_context`、`find_members`、`get_schema`、
`execute_sql`。`search_messages` 只出现在 compatibility metadata，不进入默认 surface。
`preferred_first_tools`、`allowed_sequences` 和 `deterministic_contract` 明确标记为
`diagnostic_contract_expectation`，不被解释为唯一正确序列或 `human_verified` ground truth。

### 13.2 Evaluation projection and deterministic regression

综合行为继续复用现有 `agent_tool_behavior_projection` 和 `operational_measurements`。本轮只在
同一 projection 上增加 bounded `tool_result_facts`，并汇总：

- 每个公开 Tool 的 category、status、returned messages/rows/candidates/tables、partial、truncated、
  coverage、result bound、scope enforcement 和 SQL rewrite 状态；
- 当前 Run 的 `evidence_count`、`citation_count`、`citation_state`、`finalization_state`；
- 既有 `termination`、`latency_ms`、`usage`、`coverage_statuses` 和 Tool category sequences。

投影只读取已有 normalized Trace terminal facts 和当前 `QueryResult` validated Artifact，不重新
查询 Canonical Store，不保存聊天正文、SQL rows 或 hidden chain-of-thought。

新增 `tests/test_comprehensive_tool_diagnostics.py` 覆盖：catalog case/category、六个 Tool 无重复
注册、legacy 不进入默认 surface、六 Tool 在同一 Runtime/run_id/scope 中执行、ToolResult provenance、
公开 Tool 计数和 Evaluation category/finalization projection。结果：`3 passed`；与既有测试合计
全量 `275 passed`。

### 13.3 Real Provider comprehensive smoke

运行条件：

- Provider：`opencode-go / deepseek-v4-flash`；
- Canonical Store：当前真实 snapshot，473,236 条消息、7 个 session；
- semantic index：现有 Qwen semantic index；
- scope-sensitive case 的 session scope 由 `Application.list_sessions()` 读取，不绕过 Application
  直接读数据库；
- 输出只保留 case category、公开 Tool 行为、bounded result facts、Trace、Evidence/Citation、
  Finalizer、latency/usage；没有把身份值、聊天正文、完整 SQL 结果或 credentials 写入 Git。

下表中的 Evidence/Citation 是 `evidence_count/citation_count`；`—` 表示 Finalizer 未成功产生
validated Artifact。latency/usage 是本次 provider、snapshot 和模型行为的 measured diagnostic
facts，不是生产 SLA 或答案质量结论。

| Case | Actual Tool sequence | Calls / rounds | Evidence / Citation | Final state | Trace | Latency / total tokens | Observation |
| --- | --- | ---: | ---: | --- | --- | ---: | --- |
| F1 lexical | `lexical → semantic → context` | 3 / 3 | 1 / 1 | completed | `trace-71e93d514359414195d0c74ada740ecb` | 163.4s / 62,822 | lexical first；后续 semantic/context 均保留 partial/truncated |
| F2 semantic | `semantic → semantic` | 2 / 2 | 3 / 3 | completed | `trace-4af210d2b8f54d40a5ed27a8931f536d` | 72.4s / 91,123 | 同一意图重复 semantic call；两次 partial/truncated |
| F3 context deepening | `lexical → semantic → context` | 3 / 3 | 1 / 1 | completed | `trace-5966249be8084aa6b0ca60f685851fde` | 80.1s / 65,940 | 显式 context deepening 可观察，未静默替换 retrieval |
| F4 context sufficient | `lexical` | 1 / 1 | 0 / 0 | completed | `trace-6daf6f0b87ac4779aa6fa19ca5bea633` | 18.0s / 8,900 | 没有机械调用 context；无证据状态透明 |
| F5 member → retrieval | `lexical → member → semantic → member → member → context` | 6 / 3 | — / — | failed | `trace-6e5844c0133245a2a647dc62c665f171` | 154.9s / 38,125 | Agent 重复 member；terminal `RUNTIME_ERROR/SSLError` |
| F6 member ambiguity | `schema → sql ×4` | 5 / 3 | 2 / 2 | completed | `trace-d81f84f504cf468a98c389713ba147b6` | 206.8s / 54,036 | 未选择 find_members；SQL scope 正确但重复调用 |
| F7 member no-result | `member` | 1 / 1 | 0 / 0 | completed | `trace-c52310a5d6fd45e79a0ef86183a1ce95` | 38.4s / 8,570 | 0 candidates 是显式成功，无身份编造 |
| F8 structured count | `schema → sql` | 2 / 2 | 1 / 1 | completed | `trace-404a3e3001f44b66829e0e71fc08a57f` | 10.1s / 19,361 | public schema 后 bounded SQL，scope enforcement 完整 |
| F9 aggregation | `schema → sql` | 2 / 2 | 1 / 1 | completed | `trace-7f38dde2f2a941ea9ccd0701de545ca2` | 55.3s / 19,416 | GROUP BY 走 structured path，结果有 truncation 摘要 |
| F10 mixed (first) | `lexical → schema → semantic → sql` | 4 / 3 | — / — | failed | `trace-8456cd5115c74663968f5974f244b94a` | 103.3s / 83,790 | Tool 都成功，但 `INVALID_PROVENANCE` 阻止最终 Artifact |
| F11 lexical no-result | `lexical` | 1 / 1 | 0 / 0 | completed | `trace-d4b7bb6cd74f4693b93ebd398bd28dd1` | 37.8s / 8,543 | 空结果透明，无 silent fallback |
| F12 semantic weak | `lexical → semantic` | 2 / 2 | 1 / 1 | completed | `trace-b34131793573495682990ec6190f5ad9` | 87.7s / 39,879 | 先 lexical 后 semantic；semantic partial/truncated 可见 |
| F13 structured zero (wording v1) | `schema → sql → sql` | 3 / 2 | 2 / 2 | completed | `trace-b53fb1ebc87f4e199b93b6241ec30f6c` | 83.5s / 20,915 | 得到 `COUNT=0` 一行，证明原 query wording 不是 zero-row case |
| F14 scope (first) | no Tool call | 0 / 0 | — / — | failed | `trace-ee2fe9af3eb74fdfb1f7011a3128318c` | 60.2s / — | pre-tool `RUNTIME_ERROR/SSLError`，无 scope 结论 |

### 13.4 Targeted reruns and corrected case evidence

| Case | Actual Tool sequence | Calls / rounds | Evidence / Citation | Final state | Trace | Latency / total tokens | Observation |
| --- | --- | ---: | ---: | --- | --- | ---: | --- |
| F5 rerun | `lexical → member → semantic → member → context` | 5 / 3 | 2 / 2 | completed | `trace-7a1ab9bc457b4c29bd2859665e9f02a9` | 98.8s / 70,038 | provider SSL 未复现；Agent 仍 lexical first 且重复 member，完成但 cost 高 |
| F10 rerun | `lexical → semantic → schema` | 3 / 3 | 2 / 2 | completed | `trace-dafffc8a1c52410e8fa7364723f75075` | 137.5s / 64,700 | 没有继续 `execute_sql`，mixed 统计未完成；sequence 具有模型方差 |
| F13 corrected | `schema → sql` | 2 / 2 | — / — | failed | `trace-db848f1520204fd0bab18766aeb173e6` | 60.5s / 17,921 | SQL `returned_rows=0` 正确；Provider 提交不存在的 structured citation，被 `UNRESOLVED_STRUCTURED_SOURCE` 拒绝 |
| F14 rerun | `schema → sql → sql` | 3 / 3 | 2 / 1 | completed | `trace-419e032605a74a9cb3f8427fbe6a230a` | 27.9s / 28,280 | partial scope 的 temp table + authorizer enforcement 正确；第二次 SQL 是 cost observation |

### 13.5 Failure Cases and ownership

#### FC-F1 — Same-intent semantic repetition

- Scenario：F2 semantic-dominant case。
- Observed behavior：`semantic_search → semantic_search`，两次均 partial/truncated；Finalizer 成功。
- Owner layer：Agent Tool Selection / Runtime behavior observation，不是 Semantic Capability failure。
- Root cause：当前 Provider 在已有 partial result 后重复选择同一 retrieval category；没有证据证明是
  index stale 或 Tool contract 错误。
- Handling：保留实际 sequence、round、latency、usage 和 partial facts；不加 query-specific blocker、
  fixed hybrid 或 silent dedupe。
- Regression evidence：catalog F2、deterministic sequence projection test、Trace
  `trace-4af210d2b8f54d40a5ed27a8931f536d`。
- Real rerun evidence：同意图重复行为在 F5/F12 以不同组合出现，但没有把单次 sequence 当唯一
  ground truth；是否需要 prompt/planner 调整留待下一轮 Evaluation 决策。

#### FC-F2 — Member task selection variance with transient provider failure

- Scenario：F5 member → retrieval。
- Observed behavior：首次 lexical first，随后重复 `find_members`，最终 `RUNTIME_ERROR/SSLError`；
  member Tool 本身返回 ok，无 Tool error。
- Owner layer：行为部分属于 Agent Selection；terminal failure 属于 external Provider Runtime。
- Root cause：Trace 明确显示 provider transport `SSLError`，不是 scope、identity 或 retrieval
  fallback；同一 case rerun 没有复现 transport failure。
- Handling：不新增静默 retry/fallback；保留首次失败 Trace，并用 targeted rerun 区分 transient provider
  failure 与 Agent behavior。
- Regression evidence：现有 Runtime/provider error tests、catalog F5、Failure attribution Trace。
- Real rerun evidence：`trace-7a1ab9bc457b4c29bd2859665e9f02a9` completed，但仍记录 lexical first
  和重复 member cost；不能包装为 selection accuracy 结论。

#### FC-F3 — Mixed retrieval/SQL composition can stop before required SQL

- Scenario：F10 mixed retrieval + structured aggregation。
- Observed behavior：首次调用到 `execute_sql` 但 Finalizer 因 provenance 失败；rerun 在 `get_schema`
  后停止，没有执行 `execute_sql`，虽 completed 但任务维度未完成。
- Owner layer：Agent Selection / termination / answer contract，各层 Trace 已分开记录。
- Root cause：两次 sequence 不同；首次是 Provider artifact provenance contract failure，rerun 是
  Agent 未完成结构化阶段。没有证据支持 SQL adapter 本身错误。
- Handling：不硬编码 `retrieval → schema → sql`，Evaluation 记录 category switch、是否实际 SQL、
  Finalizer 状态和 cost，等待重复 Failure Case 后再决定是否调整 guidance。
- Regression evidence：catalog F10、same-runtime mixed sequence test、existing Finalizer provenance
  regression。
- Real rerun evidence：首次 `trace-8456cd5115c74663968f5974f244b94a`，rerun
  `trace-dafffc8a1c52410e8fa7364723f75075`。

#### FC-F4 — Finalizer rejects invalid current-run provenance

- Scenario：F10 first run，Retrieval/Schema/SQL Tool 都返回 success。
- Observed behavior：`runtime completed` 后 `citation.validation.failed(INVALID_PROVENANCE)`，Query
  失败且没有提交 AnswerArtifact。
- Owner layer：Evidence/Citation/Finalizer contract；不是 Tool success 判断。
- Root cause：Provider 输出的 citation provenance 没有通过 current-run identity validation；Trace
  的 failure attribution 为 `origin_stage=citation`。
- Handling：保持 Finalizer hard gate，不猜 evidence ID、不做 citation repair、不删除 citation、不
  fallback 到旧 Run 或其他数据源。
- Regression evidence：existing current-run provenance tests、FC-C3、Trace
  `trace-8456cd5115c74663968f5974f244b94a`。
- Real rerun evidence：F10 rerun `trace-dafffc8a1c52410e8fa7364723f75075` 没有复现同一 Finalizer
  failure，但暴露了另一种 Agent composition incompleteness；不能把 rerun 当作首次失败消失的质量证明。

#### FC-F5 — Zero-row SQL result cannot support a fabricated structured citation

- Scenario：修正后的 F13 structured zero-row case。
- Observed behavior：`get_schema → execute_sql`，SQL `returned_rows=0`、scope enforcement 正确；
  Provider 仍提交不存在的 structured source，Finalizer 返回 `UNRESOLVED_STRUCTURED_SOURCE`。
- Owner layer：Provider answer artifact / Finalizer boundary；SQL zero-row semantics 本身正确。
- Root cause：空 structured result 没有可引用的 row locator，但 Provider 仍生成了 citation；不是
  Tool error，也不是将 zero rows 误报为 SQL error。
- Handling：Finalizer 继续拒绝 unresolved source；Evaluation 分开记录 `returned_rows=0` 与
  `citation_state=failed`，不 silent repair。
- Regression evidence：Stage C zero-row and structured-source tests、catalog F13、Trace
  `trace-db848f1520204fd0bab18766aeb173e6`。
- Real rerun evidence：该 corrected rerun 已确认 SQL empty-result contract 与 Finalizer hard gate
  同时生效。

#### FC-F6 — Repeated SQL calls are observable cost, not scope escape

- Scenario：F6 member ambiguity 和 F14 scope rerun。
- Observed behavior：F6 错误选择 schema/SQL 并重复 SQL；F14 在正确 partial scope 下重复 SQL；两者
  SQL rows、scope enforcement 和 Trace provenance 均保持 bounded。
- Owner layer：Agent Selection / cost observation。
- Root cause：Provider 对可见结果进行重复确认；没有发现 SQL rewrite、scope expansion 或第二套 pipeline。
- Handling：记录 call count、rounds、latency、usage、returned rows 和 scope enforcement；当前不增加
  progress handler、execution timeout 或 Runtime blocker，因为没有 runaway SQL Failure Case。
- Regression evidence：Stage C structured tests、comprehensive projection test、F14 Trace
  `trace-419e032605a74a9cb3f8427fbe6a230a`。
- Real rerun evidence：F14 rerun 完成，scope enforcement 为
  `scope_filtered_temp_tables_and_sqlite_authorizer`；重复 SQL 仍是可见 cost observation。

### 13.6 Trace / Evaluation conclusion

综合 Trace 可按以下链路定位问题：

```text
query.received
  → visible capabilities / model tool action
  → tool.call.* + retrieval/context/member/schema/sql terminal summary
  → optional next Tool category
  → evidence.prepare / citation.validation
  → answer.finalization / query terminal
```

`TraceProjection.metrics.tool_count` 只统计公开 `tool.call.completed/failed`，不会把内部
`retrieval.search.*`、`member.lookup.*`、`context.expansion.*` 或 `sql.execute.*` 重复计算。综合
Evaluation 现在能直接观察 retrieval、context、member、schema、SQL、Evidence、Citation、
Finalizer、termination、latency、usage、partial/truncated 和 scope enforcement；hidden
chain-of-thought 没有进入 projection。

本轮没有发现需要改动 Router、Planner、Agent Runtime、Retrieval 参数、SQL access boundary 或
Finalizer contract 的确定性生产 bug。真实结果证明的是“行为可观察、失败可归属、scope/citation
hard boundary 生效”，不是 Agent selection accuracy、自然语言答案 correctness、production
latency SLA 或 `llm_assisted_provisional` retrieval quality 的结论。
