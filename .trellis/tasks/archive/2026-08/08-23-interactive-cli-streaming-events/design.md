# Technical Design

## 1. Smallest Behavior Gap

现有 `OpenAIAgentsRuntimeAdapter.stream()` 已经实时产生正文、Tool 和 lifecycle 事件，M6 也已经在同一 stream 上做 Trace mapping；CLI 卡住的根因是 Application/Orchestrator 只暴露完成后的 `QueryResult`，且 Runtime 未转发 reasoning。最小修复是补一个跨 Query 的实时 projection，并让 Trace normalizer 与 Runtime event mapper各自向同一个实时 adapter 分发事实，而不是建立第二套执行器。

## 2. Change Boundary

行为真正位于四个边界：SDK stream normalization、Query/Trace live projection、structured Answer delta extraction、CLI rendering。预计修改：

- `query/runtime/contracts.py`：additive 增加 `thinking_delta/thinking_completed` Runtime event family。
- `query/runtime/openai_adapter.py`：识别 SDK `response.reasoning_summary_text.delta`、`response.reasoning_text.delta` 与对应 done event，转成 provider-neutral RuntimeEvent；不读 CLI。
- `observability/collector.py`：让已经构造的 normalized event 可选地同时通知 live observer；`TraceableAgentRuntime` 可选地把同一 RuntimeEvent 通知 live adapter；persistent mapper继续忽略 answer/thinking delta。
- `query/streaming.py`（新）：定义 CLI/UI-neutral `QueryStreamEvent`、双源 adapter 与项目 AnswerArtifact JSON 增量文本解析器。
- `query/orchestrator.py`：只透传可选 live runtime observer，仍调用一次同一 Runtime。
- `bootstrap/application.py`：`query()` 增加可选 event handler，建立同一 TraceCollector/live adapter，保持无 handler 调用完全兼容。
- `interfaces/cli_renderer.py`（新）：集中 terminal state、formatting、normal/verbose 与 fragment/newline 行为。
- `interfaces/cli.py`：增加 `--verbose`，传入 event handler，保留 picker/conversation/trace export，并用 Renderer 收尾。
- 相关测试与现有 Stage 1.7/1.9/1.11/backend runtime 文档。

明确不修改 Retrieval、Tool、Router、Planner、Evidence/Citation、Conversation Store、Evaluation 或 Provider prompt/artifact schema。局部 refactor 通过现有 178 tests、Conversation/Trace regression 与真实 DeepSeek smoke 证明核心行为未改变。

## 3. Event Data Flow

```text
DeepSeek Chat Completions
  reasoning_content
      ↓ OpenAI Agents SDK 0.22 normalization
  response.reasoning_summary_text.delta
      ↓ OpenAIAgentsRuntimeAdapter
  RuntimeEvent(thinking_delta)
      ├── TraceableAgentRuntime → persistent mapper ignores ephemeral reasoning
      └── QueryStreamAdapter → QueryStreamEvent(thinking.delta) → CliEventRenderer

RuntimeEvent(content_delta with JSON AnswerArtifact)
      ├── persistent mapper ignores token delta
      └── AnswerArtifactDeltaParser
            → QueryStreamEvent(answer.delta, content_blocks text only)
            → CliEventRenderer

Router / Planner / Tool / Retrieval / Finalizer / Conversation
      ↓ existing TraceCollector.emit at actual boundary
NormalizedQueryEvent
      ├── SQLiteTraceStore
      └── QueryStreamAdapter
            → route/plan/tool/retrieval/answer/query event
            → CliEventRenderer
```

Trace Store 不是队列。live observer 在 canonical event 构造后直接接收同一内存对象；即使 Trace Store append 退化，已成功 normalize 的 live event 仍可投影，Trace failure 继续按当前 `TRACE.*` contract 暴露。

## 4. QueryStreamEvent Contract

`QueryStreamEvent` 使用全局单调 sequence（由单次 QueryStreamAdapter 分配），表达：

```text
query.started
route.completed
plan.completed | plan.failed
thinking.delta | thinking.completed
tool.started | tool.completed | tool.failed
retrieval.started | retrieval.completed | retrieval.failed
answer.delta | answer.completed
query.completed | query.failed | query.aborted
```

字段只保留 provider-neutral 普通值：`content`、`route`、`plan`、`tool_name`、`arguments`、`result_summary`、`error`、`duration_ms`、`usage`、`trace_id`、`source_operation` 和 bounded metadata。Adapter 只做确定性映射：

- Runtime reasoning/text delta → thinking/answer delta；
- `router.decision` → route.completed；
- `planner.completed/failed` → plan completed/failed；
- `tool.call.*` → tool events；
- `retrieval.search.*` → retrieval events；
- `answer.finalization.completed` → authoritative answer.completed；
- `query.*` → query terminal。

不从 event 顺序猜测 stage，不从 Tool name 猜测结果数量，不从文本推断失败。

## 5. AnswerArtifact Delta Parser

Provider 的 raw `content_delta` 是 JSON，而不是可直接展示的回答。增量解析器只理解 Trivae 自有 schema 中 `content_blocks` 数组内每个对象的 `text` JSON string：

1. 按 chunk 顺序维护最小 JSON lexical state（object/array/string/escape/unicode escape）。
2. 只在当前路径等于 `content_blocks[*].text` 时输出已完整解码的字符。
3. JSON escape 或 `\uXXXX` 跨 chunk 时继续缓存，绝不输出半个 escape。
4. 第二个及后续 block 的首个正文字符前输出 `\n\n`，与 `AnswerArtifact.answer_text` 完全一致。
5. 其他字段、citation/evidence/source metadata 全部跳过，normal CLI 不看到 raw artifact。
6. `answer.finalization.completed` 提供 authoritative full answer；Renderer 用其完成无-delta路径和最终收尾。Finalizer failure 不提交 Conversation，并显式结束已显示的 preview。

Parser 是传输 projection，不是第二个 Finalizer：不验证 citation、source、sufficiency 或 artifact 完整性，也不修复 malformed JSON。完整 provider output 仍只由 `finalize_answer()` 决定能否成为正式 Answer。

## 6. Tool and Retrieval Projection

Tool start 不依赖 SDK hook 中缺失的 raw args，而消费当前 `SearchMessagesTool.invoke_with_trace()` 在 typed `SearchMessagesInput` 建立后产生的 `tool.call.started`。因此显示的参数已经越过 provider-specific JSON，但仍不含 trusted `ExecutionScope`。

Retrieval completion 使用现有 payload：

- `candidate_count`：本次 lexical hits 数量；
- `total_hits`：底层真实总 hit 数；
- `context_expansion.expanded_count` / `returned_messages`：真实 expanded context 数；
- `partial/truncated/coverage/latency_ms`：只在真实存在时显示。

normal 只显示关键非空参数与计数；verbose 可显示 capture policy 内完整 request、coverage、partial/truncated、duration 与 source operation。Tool Result聊天正文、provenance 数组和巨大 output 不直接打印。

## 7. Renderer State Machine

Renderer 只维护展示状态，不维护 Agent 状态：当前 segment（none/thinking/answer）、是否已打印 label、是否在行首、已显示 answer 文本、terminal/error 状态。规则：

- 首个非空 thinking delta 打印一次 `Thinking...\n`，随后 fragment 原样连续写；空 delta忽略。
- 状态/Tool/Plan 到达前先结束开放的 thinking/answer 行，防止文本与状态粘连。
- Tool/Result 用完整行；多 Tool 依事件 sequence 展示。
- 首个 answer delta 打印 `Answer:\n`，随后不自动换行地写 fragment。
- answer.completed 在无 delta 时输出完整正式答案；有 delta 时只收尾，不重复正文。
- failed/aborted/interrupt 先恢复换行，再打印稳定错误；下一轮 `You >` 前保证行已闭合。
- 输出使用 `write()` + `flush()`；不引入 Rich/Textual，不按 token 调用 `print()`。

## 8. Normal and Verbose

Normal：真实 Thinking、Route name、Plan steps、Tool name + 精简 args、Retrieval counts/0 result/partial、Tool status、Answer streaming、错误、trace/log。

Verbose：在 normal 基础上使用 `trace_profile=debug`，增加 route source/confidence/reason、plan intent/criteria、bounded full Tool args、retrieval coverage/partial/truncated/actual duration、usage 与 normalized source operation/sequence。Secret/hidden reasoning persistence、越权数据与聊天正文 dump 仍禁止。

## 9. Failure Semantics

- Provider without reasoning：无 thinking event，其他事件不变。
- Empty reasoning：Adapter 不 emit delta；Renderer 不重复 label。
- Tool known failure：显示 tool.failed；若 Agent 继续，后续事件照常。
- Retrieval zero result：显示真实 0 hits/0 expanded，不生成“找到若干条”。
- Provider stream failure：Runtime failed → query.failed；Renderer 关闭 segment 并显示 secret-safe error。
- Finalizer failure：可能已经显示 provider preview，但 answer.completed 不产生、Conversation 不 commit；Renderer 明确 error。
- Ctrl+C/task cancellation：async cancellation 关闭 SDK stream；CLI `finally` 恢复换行并沿用 `Bye.`，不新增 retry。
- Trace Store failure：不回滚业务或阻塞 live event；保留当前 `TRACE.*` 日志/collector degradation。

## 10. Compatibility and Rollback

`TrivaeApplication.query()` 的 event handler 为 keyword-only optional 参数；所有 Evaluation、测试和非 CLI caller 不传时保持当前同步完成语义。Runtime event Literal 只 additive；Trace schema不迁移，reasoning/delta 不持久化。回滚可删除 streaming adapter/renderer 与 optional observer wiring，现有 Query/Trace/Conversation 数据无需迁移。

## 11. ChatLab Mapping

本次对照基于 ChatLab commit `a6557608c6df372e25a130f64f3a28f8e396b1f3`（2026-08-23），重点读取 `apps/cli/src/ai/agent.ts`、`agent-stream-runner.ts`、`chat-command.ts`、`packages/node-runtime/src/ai/agent/core.ts`、`types.ts`、`event-handler.ts` 与 `llm-stream.ts`。

- ChatLab `runAgentCore` ↔ Trivae existing `OpenAIAgentsRuntimeAdapter.stream()`；均为唯一 Agent loop。
- ChatLab `AgentCoreEvent` ↔ Trivae `RuntimeEvent`；均隔离 SDK raw types。
- ChatLab `AgentEventHandler` ↔ Trivae `QueryStreamAdapter` + `CliEventRenderer`；Trivae 额外复用 M6 normalized Query events。
- ChatLab `think/content/tool_*` ↔ Trivae `thinking.delta/answer.delta/tool.*`。
- ChatLab CLI 累积 answer 后一次 persistence ↔ Trivae 继续累积完整 JSON artifact，经 Finalizer 后一次 `commit_turn()`。
- Trivae 的偏离：最终 provider content 是 citation-aware JSON，因此 normal renderer 增量提取 project-owned answer text，不能照搬 ChatLab 直接打印 `content`。
