# Stage A Validation — Dual Retrieval Agent Surface

## 1. Problem / Motivation

本记录当前只覆盖 Checkpoint A；按最新开发指令，Stage B/C 保持冻结，不在本轮继续扩展。

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

Stage B context/member behavior and Stage C structured SQL remain pending and frozen for the current
handoff. A future hybrid, reranker, query rewrite or retrieval parameter change requires a reproducible
Failure Case plus paired/Agent Evaluation evidence. A repeated Provider SSL failure needs provider
transport diagnostics or configuration evidence before any further compatibility change is considered.

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
