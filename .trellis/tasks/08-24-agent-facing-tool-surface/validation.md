# Stage A Validation — Dual Retrieval Agent Surface

## 1. Problem / Motivation

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

### FC-A2 — Semantic-first run ended with provider transport error

- Type: `real failure`。
- Scenario: semantic-dominant paraphrase query；Agent 首先选择 `semantic_search`，随后又
  调用 `lexical_search`。
- Observed failure: 两个 Tool call 都返回；Trace 的 `runtime.run` 最终以
  `RUNTIME_ERROR` 终止，`diagnostic_type=SSLError`，没有 silent lexical fallback。
- Root cause: 当前 Provider 请求链路出现 SSL transport error；Trace 能定位 origin/observed
  stage 都是 Runtime，但没有进一步的 upstream certificate/endpoint 证据，因此不把它误判
  为 Retrieval 或 Tool Contract failure。
- Current handling: 保持 terminal error，向 Query caller 暴露 `RUNTIME_ERROR`；不增加 retry、
  fallback 或 provider-specific patch。
- Validation: `trace-b414d84a0ee0460b82c7cb8b2cdae8a2` 的 runtime event 与 failure projection；
  单元测试覆盖 semantic unavailable 的显式 `SEMANTIC_INDEX_UNAVAILABLE`。

### FC-A3 — Provider router degraded and retained static route

- Type: `real failure` / degradation。
- Scenario: 四个真实 smoke case 都记录 `ROUTER_COMPLETION_TIMEOUT`。
- Observed failure: Router Trace 标记 `degradation`，handling 为 `static_route_retained`；Query
  仍按可观测的 static route 继续，而不是静默切换数据源。
- Root cause: 当前 Provider router completion 超时；现有 Trace 没有给出更具体的 upstream
  网络根因，因此只记录到 Router degradation 层。
- Current handling: 沿用既有 Router degradation contract；本阶段不改 Router，不把这组
  运行结果当作质量提升证据。
- Validation: 四个 smoke trace 均可定位该 event；本地单元/集成测试保持通过。

### FC-A4 — Lexical-first answer failed final artifact validation

- Type: `real failure`。
- Scenario: lexical-dominant exact-term query；Agent 首先选 `lexical_search`，之后调用
  `semantic_search`。
- Observed failure: Retrieval Tool events 为 lexical `ok`、semantic `partial`；Runtime
  曾产出回答文本，但 citation/finalization 以 `INVALID_ANSWER_ARTIFACT` 结束，正式
  `answer_artifact` 和 Evidence/Citation 没有提交。
- Root cause: Provider final output 在 Tool execution 后不是可验证的 JSON object；这是
  Answer/Citation contract failure，不把它改写成 Retrieval success。
- Current handling: Finalizer 显式拒绝无效 artifact；不删除 citation、不猜测 evidence、不
  静默返回未验证文本。
- Validation: `trace-ae73fdec9fbd4db88068c8cc77efcc97` 的 citation validation、answer
  finalization 和 query failure events；已有 evidence regression tests 保持该边界。

### FC-A5 — Semantic index unavailable remains explicit

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

| Case | First / actual sequence | Calls / rounds | Final state | Trace |
| --- | --- | ---: | --- | --- |
| lexical-dominant | `lexical_search → semantic_search` | 2 / 1 | finalization failed: `INVALID_ANSWER_ARTIFACT` | `trace-ae73fdec9fbd4db88068c8cc77efcc97` |
| semantic-dominant | `semantic_search → lexical_search` | 2 / 1 | runtime failed: `RUNTIME_ERROR`, diagnostic `SSLError` | `trace-b414d84a0ee0460b82c7cb8b2cdae8a2` |
| multi-search | `lexical_search → semantic_search` | 2 / 2 | completed; 2 Evidence / 2 citations | `trace-d7b3b2e60289486286bcc138423b60bb` |
| no-result | `lexical_search → semantic_search` | 2 / 2 | completed; 0 Evidence / 0 citations | `trace-df766dd65a4d49399e67a794abfe7186` |

Measured latency was approximately 26–79 seconds per case on this Provider/index run. This is a
smoke observation, not a production SLA or a reason to change `dense_top_k`, model, dimension or
chunking parameters. Usage/token values remain in the local smoke report only; the repository does
not commit raw transcripts or credentials.

The Agent selected the expected first Tool for the lexical- and semantic-dominant diagnostics, but
the observed model behavior also issued a second retrieval call in each case. Whether that second
call is unnecessary or justified depends on result sufficiency; this catalog records it for review,
not as a rigid unique-sequence assertion. Existing paired lexical-only vs semantic-only retrieval
evaluation remains unchanged, and its labels remain `llm_assisted_provisional`, never
`human_verified`.

## 6. Observability / Debugging

The Stage A Trace path exposes the user-query boundary, visible capabilities, model Tool action and
arguments, Tool result status (`ok`/`partial`/error), retrieval result summary, subsequent Tool call,
Evidence/Citation finalization and final Query outcome. It does not persist hidden chain-of-thought.

The smoke traces distinguish:

- selection/runtime problem: `runtime.run` failure with `diagnostic_type=SSLError`;
- retrieval status: lexical `ok`, semantic `partial`, candidate/empty summaries;
- answer contract problem: `citation.validation.failed` and `INVALID_ANSWER_ARTIFACT`;
- Router degradation: `ROUTER_COMPLETION_TIMEOUT` with `static_route_retained`;
- no-result: completed query with zero Evidence/Citation, rather than fabricated evidence.

## 7. Scale / Performance

The smoke snapshot contains 473,236 canonical messages and a real semantic index of the same
canonical corpus. Semantic KNN was the dominant measured cost in the observed run; exact per-query
latency varied from roughly 26 to 79 seconds across the four Provider cases. No index/model/parameter
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

The next evidence gate is Stage B context/member behavior, followed by Stage C structured SQL. A
future hybrid, reranker, query rewrite or retrieval parameter change requires a reproducible Failure
Case plus paired/Agent Evaluation evidence. A repeated Provider SSL failure needs provider transport
diagnostics or configuration evidence before any compatibility change is considered.

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
  Stage 1.3/1.4 failure contract；真实实现保持 explicit error。
- Q: 这轮真实运行证明了什么？ 证据：四个 Provider smoke trace；它证明了 surface、sequence、
  error attribution 和 no-result transparency 可被观测，但不证明 Agent answer quality、
  production latency SLA 或 paired retrieval 的 human-verified correctness。
