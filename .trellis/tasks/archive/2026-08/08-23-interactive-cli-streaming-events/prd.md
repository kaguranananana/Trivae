# Interactive CLI streaming events

## Goal

在不复制 Query/Agent 执行链、不改变 Retrieval、Router、Planner、Tool、Citation、Conversation、Evaluation 与最终 Provider 输出语义的前提下，让 `trivae chat` 实时消费同一次真实执行产生的事件，连续展示 Provider reasoning、Route/Plan、Tool/Retrieval、最终 Answer delta、失败与完成状态，降低长耗时检索期间的不可见等待。

## Background and Confirmed Facts

- 当前 `trivae chat` 只调用 `TrivaeApplication.query()`，等待完整 Query、Finalizer 与 Conversation commit 后一次性打印 `QueryResult.final_answer`。
- `OpenAIAgentsRuntimeAdapter.stream()` 已是唯一真实 SDK Agent loop；`run()` 只是完整消费该 stream。现有事件已覆盖 run/turn/content/tool/usage/finalizing/terminal，但缺少 reasoning 归一化。
- M6 `TraceableAgentRuntime` 已从同一个 `RuntimeEvent` 流生成 normalized Trace，并明确不持久化 `content_delta`。
- Router、Planner、Tool、Retrieval、Finalization、Conversation 与 Query 生命周期已经在各自真实边界调用 `TraceCollector.emit()`，其中 Tool request 与 Retrieval 的真实计数、context expansion、partial/truncated、latency 等事实已经存在。
- OpenAI Agents SDK 0.22.0 会把 DeepSeek `reasoning_content` 转成 `response.reasoning_summary_text.delta`，也支持 `response.reasoning_text.delta`；CLI 不需要也不允许读取 provider-specific 字段。
- Provider 最终输出是项目自有的 JSON `AnswerArtifact`，用户可见正文位于 `content_blocks[*].text`；最终 `AnswerArtifact.answer_text` 只有通过现有 Finalizer 后才是正式答案。
- `.env` 中已配置真实 DeepSeek key 与 `deepseek-v4-flash`，`data/trivae.sqlite3` 存在，因此实现完成后具备真实 smoke 前提。
- 变更前基线：178 tests passed；ruff 与 mypy 均通过。

## Requirements

### R1. 单一执行链和事件来源

- CLI 必须继续只通过 Application Query path 执行请求，不得直接调用 Runtime、Tool、Retrieval 或轮询 SQLite Trace Store。
- Router/Planner/Tool/Retrieval/Query/Conversation 事件应由同一次 `TraceCollector.emit()` 生成的 normalized event 同时投影给 Trace Store 与实时 consumer。
- Runtime reasoning/answer delta 应由同一次 `RuntimeEvent` 流同时投影给 Trace adapter 与实时 consumer；不得增加第二次 Provider 请求。
- 允许增加薄的 query streaming event projection，但它只能适配已有 runtime/normalized event，不得成为第二套业务状态机。

### R2. Provider reasoning normalization

- 将 SDK 已归一化的 reasoning summary/text delta 转成 provider-neutral `thinking.delta`，非空 delta 按真实顺序实时传给 CLI。
- reasoning 结束事件转成 `thinking.completed`，空 delta 不产生重复 `Thinking...`。
- 不支持 reasoning 或不返回 reasoning 的 Provider 必须正常完成 Tool/Answer 流。
- CLI 不读取 `reasoning_content`，也不根据阶段伪造 thinking。
- reasoning 只作为短生命周期实时事件；遵守 M6 隐私契约，不进入 normal/debug persistent Trace。

### R3. Route and Plan

- Router decision 完成后展示真实 route；normal 至少展示 route 名，verbose 可增加 source/confidence/reason/duration。
- Planner 继续使用当前非 streaming completion；只有真实 `planner.completed` 时展示 bounded steps，失败/跳过按现有 normalized failure 表达。
- 不为了 UI 重跑 Router/Planner，也不伪造 `plan.delta`。

### R4. Tool and Retrieval

- Tool 开始使用真实 `tool.call.started`，显示 tool name 与 typed request 中对用户有意义的非空参数。
- normal 对参数做可读格式化和有界截断；verbose 显示 capture policy 内更完整的参数与 event metadata。
- Retrieval 使用真实 `retrieval.search.started/completed/failed`；完成时只显示底层存在的 candidate count、total hits、expanded count、partial/truncated 等事实。
- Tool completion/failure 使用真实 `tool.call.completed/failed`；默认不 dump 聊天正文或完整 Tool Result。
- 多 Tool 调用必须保持真实事件顺序，不按 tool name 重新排序。

### R5. Answer streaming and finalization

- Provider `content_delta` 必须实时进入项目契约级增量解析器，只输出 `AnswerArtifact.content_blocks[*].text`，normal 不得打印原始 JSON artifact。
- 多 content block 的用户可见文本以与 `AnswerArtifact.answer_text` 相同的双换行连接。
- `answer.completed` 必须携带 Finalizer 已验证的完整 `answer_text`；Renderer 在没有 delta 的 run-only 测试路径仍能显示正式答案。
- Provider delta 只传输/展示，不逐 token 写 Conversation；现有 Finalizer 与 `commit_turn()` 仍对完整 Artifact 一次提交。
- 若 Provider/Finalizer/commit 在已显示部分 delta 后失败，Renderer 必须结束当前行并明确显示失败，不伪装成 completed。

### R6. CLI Renderer and modes

- 新增独立 CLI event renderer；Router、Planner、Runtime、Tool、Retrieval、Provider 内不得出现终端 `print()`。
- `trivae chat` 默认模式展示持续反馈、真实 reasoning、route/plan、Tool/Retrieval 摘要、Answer streaming、错误/完成与 trace/log identity。
- 新增 `trivae chat --verbose`，并复用 `QueryRequest.trace_profile="debug"`；可额外显示完整 bounded Tool args、route/plan 细节、真实 timing/usage 与 normalized metadata，但不显示 secret、hidden fields 或巨大聊天正文。
- delta 输出不得每 token 自动换行；thinking/tool/answer 段切换、空 delta、Unicode、多轮 Tool、下一轮 prompt 都必须保持终端结构完整。

### R7. Cancellation and failures

- Ctrl+C/任务取消必须停止当前异步 Query/Provider stream，Renderer 用 `finally` 恢复行边界，随后沿用当前短退出行为。
- Provider stream failure、Tool failure、Retrieval 0 result、Planner failure、Finalizer failure均使用真实事件/正式错误投影；不得新增 retry/fallback/silent catch。
- Tool known error若 Agent 能继续，Renderer 显示失败后继续后续真实事件。

### R8. Documentation, verification and delivery

- 更新现有 Agent Runtime、Trace/Observability 与 Application/CLI 架构文档，记录 live vs persisted projection、reasoning capability boundary、Renderer 职责、normal/verbose、failure cases与不伪造 thinking 的原因。
- 新增 normalization、Renderer、provider-without-reasoning、multi-tool/error、Conversation regression、Trace regression 测试。
- 运行全量 pytest、ruff、mypy、CLI help/task validation 与 git diff check。
- 使用真实 `deepseek-v4-flash` 和真实聊天数据库运行一个需要检索的问题；核对终端事件、Trace 与 Conversation 完整提交，不用 mock 输出替代。
- 创建 `codex/interactive-cli-streaming-events` 分支，完成实现、测试、文档、Trellis 收尾并提交；最终报告 commit SHA 与工作树 clean 状态。

## Acceptance Criteria

- [ ] `trivae chat` 在 Router/Planner/Tool/Retrieval/Provider 执行期间持续输出，不再只在 Query 返回后一次性显示答案。
- [ ] DeepSeek `reasoning_content` 经 SDK/Provider Adapter 归一化为非空 `thinking.delta`，CLI 不包含 provider-specific 判断；无 reasoning 时仍正常。
- [ ] Tool start/result/failure 和 Retrieval stats 来自同一次真实执行的 normalized events，normal 不 dump 大 JSON/聊天正文。
- [ ] 最终用户正文按 delta 流式显示，原始 JSON AnswerArtifact 不泄漏到 normal CLI；最终 persisted Assistant Answer 与 validated `AnswerArtifact.answer_text` 完全一致。
- [ ] Router/Plan、多 Tool、0 result、Tool failure、Provider failure、Ctrl+C/取消后的事件顺序与终端换行正确。
- [ ] M6 Trace 仍保存同一 Query 的 route/plan/tool/retrieval/finalization/commit 事实；不保存 token delta 或 reasoning，且不通过 SQLite polling 驱动 CLI。
- [ ] `--verbose` 使用 debug trace profile 并展示更详细但仍 bounded/redacted 的真实 metadata；默认模式保持可读。
- [ ] 新增测试覆盖提示要求，全部既有/新增测试、ruff、mypy 通过。
- [ ] 真实 DeepSeek smoke 能证明 reasoning（若该模型实际返回）、Tool、Retrieval、Answer delta、Trace 与 Conversation；模型不返回 reasoning 时如实记录 capability 结果而不伪造。
- [ ] 文档、分支、commit、Trellis task 与工作树状态完成并在最终报告逐项列出。

## Out of Scope

- 重写 Agent Runtime、增加第二个 Agent loop、引入 Agent framework 或复杂 TUI。
- 修改 Retrieval ranking/context expansion、Router decision、Planner logic、Tool semantics、Citation/Finalizer、Conversation/Evaluation contract 或 Provider 最终 artifact schema。
- Web UI、HTTP streaming transport、Trace backend/retention 重做、OpenTelemetry/vendor tracing。
- 为 reasoning 再调用一次模型、由 CLI/Runtime 生成伪 reasoning、把 reasoning 落盘。
- 以应用级 retry、fallback、兼容分支或单样例特判掩盖 provider/parser/renderer 错误。

## Blocking Open Questions

无。用户体验、scope、兼容、失败语义与验收条件已由原始需求和仓库现有 contract 明确。
