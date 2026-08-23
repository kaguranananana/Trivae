# Technical design

## Planning status

本设计用于冻结最小实现边界；实现已按本设计完成，以下证据与最终代码保持同步。

## Evidence collected

### Trivae current implementation

- `src/trivae/query/runtime/openai_adapter.py` 的 `_RuntimeHooks.on_llm_start` 已处于正确的捕获时机：SDK 已完成 input filtering/deduplication，随后才调用 Provider。
- 当前 `_project_model_visible_context()` 只接受 `dict` 且只保留 `role` 与字符串 `content`。这会丢弃 `type=function_call`、`type=function_call_output`、content block list 形式的 assistant message，以及未被提前转换的 typed item。
- `src/trivae/observability/collector.py` 已是所有 Runtime Event 进入 `NormalizedQueryEvent` 的唯一入口；`CapturePolicy` 已负责 bounded/redacted capture 和 hidden reasoning key 过滤。
- 现有 planner/router/retrieval/evidence/citation/terminal 事件已经有足够的结构化诊断字段；主要缺口是 model turn input/output 的可读投影，而不是重新建立业务事实。
- 现有 `TraceTextLogWriter` 只把每个 normalized event 展开成 `[event n]`，适合机器诊断但不能顺序阅读一次 agent execution。

### OpenAI Agents SDK 0.22.0

本地 `.venv` 的已安装版本为 `openai-agents==0.22.0`。该版本的 `RunHooksBase.on_llm_start` 接收 `input_items: list[TResponseInputItem]`，Run Loop 在 `maybe_filter_model_input()` 和 deduplication 后、Provider `model.get_response()` 前调用 hook。实际可观察 item 的关键形态是：

```text
{"role": "system"|"user"|"assistant", "content": ...}
{"type": "function_call", "name": ..., "arguments": ..., "call_id": ...}
{"type": "function_call_output", "output": ..., "call_id": ...}
```

`ItemHelpers.tool_call_output_item()` 生成的 Tool Result 是 `type=function_call_output`，带 `call_id` 和 `output`；非字符串 tool output 会在 SDK 边界转换为模型可消费的字符串/结构化输出。因此 `on_llm_start` 的 `input_items` 是“实际进入本次模型调用”的首选事实边界，不能在 Transcript 侧从 DB 或 `ToolResultRecord` 猜测。

参考的官方源码：

- [lifecycle.py v0.22.0](https://github.com/openai/openai-agents-python/blob/v0.22.0/src/agents/lifecycle.py)
- [items.py v0.22.0](https://github.com/openai/openai-agents-python/blob/v0.22.0/src/agents/items.py)
- [run_loop.py v0.22.0](https://github.com/openai/openai-agents-python/blob/v0.22.0/src/agents/run_internal/run_loop.py)

### ChatLab reference

只借鉴其“每一轮记录实际送给模型的上下文、工具调用/结果和 final response，便于人工顺读”的可读性目标，不复制其日志格式或 runtime。ChatLab 的 LLM context debug hook 位于 `packages/node-runtime/src/ai/agent/core.ts`，Trivae 仍以自己的 normalized event/SQLite projection 为边界。

## Target data flow

```text
OpenAI Agents SDK
  └─ on_llm_start(filtered input_items)
       ↓ safe Trivae-owned item projection
RuntimeEvent(model_visible_context)
  └─ on_llm_end(visible message/function-call output)
       ↓ safe Trivae-owned output projection
RuntimeEvent(observable_output)
       ↓
TraceableAgentRuntime mapper
       ↓ CapturePolicy(secret redaction + profile bounds)
NormalizedQueryEvent
       ↓
SQLiteTraceStore / StoredTrace
       ├─ trace show JSON/projection
       ├─ Execution Transcript projection
       └─ RAW TRACE EVENTS text projection
```

两条 model turn 事实必须分别表达：

1. `turn_started` 保存本轮 hook 看到的真实 `system_prompt + filtered input_items`。
2. `turn_completed` 保存本轮 Provider 返回的可观察 message/tool-call output；只保留应用层可见字段。

这允许 Transcript 同时展示“模型输入”和“模型产生的 action”，并让下一轮的 `function_call_output` 作为模型实际收到的 Tool Result，而不是把一次工具执行的业务 record 当成模型输入。

## Runtime-owned plain projection

在 adapter 内新增小型、白名单式的 Trivae-owned projector，不把 SDK object、`repr(item)`、provider response 原对象带出 adapter：

- 普通 message：保留 `role` 和经过安全文本提取的 `content`。
- content block message：只提取公开文本 block；不把 block 的所有 SDK 字段复制进 Trace。
- `function_call`：保留 `type`、`name`、`arguments`、必要的 `call_id`。
- `function_call_output`：保留 `type`、`call_id`、实际 `output`；不重新读取 Tool Result record。
- 明确跳过 `reasoning` / `reasoning_content` / `chain_of_thought` 等 hidden item/field；不把 hidden item 变成 `[REDACTED]` 正文，也不持久化它的 SDK payload。
- 对当前 SDK/Trivae tool surface 之外的 item，不使用 `repr` 或无界 `model_dump`；要么通过公开 `role/content` 形状安全投影，要么返回可见 limitation，使 Trace 明确知道 capture 不完整。

`CapturePolicy` 仍在 Collector 统一执行 secret redaction、字符串/集合/深度上限。Adapter 只负责“哪些 model-visible facts 可以进入 Trivae-owned plain data”，不实现第二套 secret filter。

`RuntimeEvent` 只做 additive contract 扩展：保留既有 `model_visible_context`，增加可观察 model output 字段（暂定命名 `observable_output`）和必要的 capture limitation；不暴露 SDK 类型。

## Transcript projection

新增 `src/trivae/observability/transcript.py`，只接收 `StoredTrace`，不依赖 Application、Conversation Store、Capability Registry 或 Retrieval：

1. 按 `StoredTrace.events` 的 sequence 一次遍历，建立轻量的 model-turn/Tool Call 关联。
2. 从 `query.received` 读取 query、scope snapshot 和 trace profile。
3. 从 `router.decision` / `planner.completed|failed|skipped` 读取显式诊断事实。
4. 从 `model.turn` started payload 渲染每轮真实 input；message 用 `[SYSTEM]`/`[USER]`/`[ASSISTANT]`，`function_call` 用 `[TOOL CALL]`，`function_call_output` 用 `[TOOL RESULT]`。
5. 从同轮 completed payload 渲染 assistant visible text、tool action、usage、tool round 和 termination/finalization 状态。
6. 从 retrieval/evidence/citation 事件渲染短摘要；candidate IDs、scores、operation IDs 只留 Raw Events。
7. 从 terminal runtime/answer/query event 渲染完整 final answer snapshot；如果 CapturePolicy 产生 limitation，紧邻正文显示 limitation，而不是假装完整。

Tool Result 展示顺序为“正文优先、诊断元数据其次”：先显示 `function_call_output.output` 的实际模型输入文本/结构，再显示 status、returned/total、partial、truncated、coverage 等已经存在于 normalized events 的摘要。不得以 `ToolResultRecord.message_items` 或数据库查询替换 model input；它们只能作为已经存在的当前-run provenance，不是本 Transcript 的事实来源。

## Text log composition

保持 `TraceTextLogWriter` 的职责为文本组合和文件写入：

```text
Trace Metadata
...

====================
EXECUTION TRANSCRIPT
====================
...

=================
RAW TRACE EVENTS
=================
[event 1]
...
```

把 transcript-specific branch 放入新 projection，不把 `text.py` 变成 Router/Planner/Tool 的业务 formatter。增量 sidecar 继续追加 canonical event 的 raw projection；完整 export 从 `StoredTrace` 重建 header、Transcript 和 Raw Events。

## Profile behavior

- `normal` 保持现有 512 字符、16 个集合项、深度 6 的 bounded/redacted contract；日志可以有 Transcript 骨架，但不承诺完整 model context/result，且必须显示 limitations。
- `debug` 提升到与现有 `AnswerArtifact` 上限相容的近完整捕获（实现时以 `MAX_ANSWER_CHARS=20_000` 为 Final Answer 的上限，集合 item 仍有明确 bound），使用深度 10 保存结构化 model-visible Tool Result，保留完整/近完整 model-visible input、Tool Call/Result、assistant visible output 和 final answer；仍受 scope、secret redaction、深度和 retention 限制。
- 任何 profile 都不改变 `ExecutionScope`；Debug 不是授权开关。

## Failure and truncation semantics

- planner failure 仍沿用现有 `planner.failed` + `handling=executed_without_plan`，Transcript 只投影它，不新增 fallback 事实。
- retrieval 的 `returned_messages`、`total_hits`、`truncated`、`partial`、`coverage` 继续来自 canonical retrieval/tool events；Transcript 明确显示 `returned / total`，避免把 20 条误读成完整 77 条。
- capture/truncation limitation 不被静默吞掉；Raw Events 保留完整 limitation 列表，Transcript 在对应 block 附近显示短摘要。
- hidden reasoning 被 projector 白名单排除，CapturePolicy 继续拦截已知 hidden keys；测试必须检查最终 StoredTrace/`.log` 中不存在 hidden reasoning text 或 SDK internal field。

## Planned file boundary

预计修改/新增：

- `src/trivae/query/runtime/openai_adapter.py`：精确 input item 和 observable model output 的安全投影。
- `src/trivae/query/runtime/contracts.py`：只做 additive Trivae-owned runtime event 字段。
- `src/trivae/observability/collector.py`：把 additive runtime facts 映射到 normalized payload，复用现有 CapturePolicy。
- `src/trivae/observability/transcript.py`：纯 StoredTrace -> human-readable transcript projection。
- `src/trivae/observability/text.py`：组合 Trace header + Transcript + Raw Events。
- `tests/test_agent_runtime.py` / `tests/test_observability.py`，必要时新增 `tests/test_transcript.py`：覆盖 SDK item 形态、model-visible 一致性、privacy、Transcript、failure/truncation/profile。
- `.trellis/spec/project/technical-decisions/stage-1-9-trace-observability.md`：amendment/clarification。
- `.trellis/spec/backend/quality-guidelines.md`：同步 Text Log / model-visible contract。

不计划新增 SQLite 表、CLI 重新查询逻辑、Conversation Store 读取、独立日志 writer 或 provider tracing integration。

## Verification evidence

- Unit：直接构造 SDK 风格 input/output item，验证 projector 只留下 plain model-visible facts。
- Runtime integration：用现有 scripted model 运行一轮 tool call + 下一轮 answer，断言 Trace 的下一轮 input 与 model adapter 收到的 output string 相同。
- Projection：用 synthetic StoredTrace 验证各区块、planner failure 和 truncation 摘要。
- Regression：`pytest`、`ruff check src tests`、`mypy src`。
- Real smoke：配置可用时通过现有 Application/CLI Query path 运行真实 DeepSeek，读取返回的 trace id 导出 `.log`；不直接调用 Runtime 或另写 debug log。
