# Implementation Plan

## Phase 1 — Activation and baseline

1. 用户批准本规划后创建 `codex/interactive-cli-streaming-events`，运行 `task.py start`，加载 Phase 2.1 与 `trellis-before-dev`。
2. 完整阅读 backend/project relevant spec checklist、cross-layer/reuse guides 与当前 task artifacts。
3. 重新确认 clean baseline、178 tests、ruff、mypy 与 DeepSeek/database smoke prerequisites；不读取或输出 secret。

## Phase 2 — Runtime normalization and query event projection

1. 在 Runtime contract additive 增加 `thinking_delta`、`thinking_completed`；更新 event type alias和构造路径。
2. 先写 normalization tests：SDK `reasoning_content` 对应的 reasoning summary delta、reasoning text delta、empty/no reasoning、reasoning done、answer content delta。
3. 修改 OpenAI adapter，只识别 SDK public normalized event types；保持 provider-specific fields 在 SDK/adapter 下方。
4. 新增 `query/streaming.py`：`QueryStreamEvent`、global sequence adapter、NormalizedQueryEvent/RuntimeEvent 映射。
5. 在 TraceCollector 增加 optional normalized observer，在 TraceableAgentRuntime 增加 optional runtime observer；listener只消费同一事实，不改变 persistent mapper 对 delta/reasoning 的忽略策略。
6. 将 optional handler 从 Application 透传到 Orchestrator/wrapper；不传 handler 的旧路径保持同一结果和 Trace。

## Phase 3 — Answer text streaming

1. 为 JSON lexical parser 先写 chunk-boundary tests：普通中文、escaped quote/backslash/newline、`\uXXXX` 跨 chunk、多 content block、非 text 字段、malformed/incomplete stream。
2. 实现只提取 `content_blocks[*].text` 的增量 parser，关键状态转换使用简体中文注释逐行解释。
3. 在 QueryStreamAdapter 将 Runtime `content_delta` 转成 `answer.delta`；将 finalizer normalized event 转成 authoritative `answer.completed`。
4. 加 Conversation regression：streamed preview 与最终 `AnswerArtifact.answer_text` 相同，Store 仍只出现一个完整 Assistant message；finalization/provider failure 不 commit。

## Phase 4 — CLI renderer and modes

1. 新增独立 `CliEventRenderer`，先写 renderer order tests：thinking → tool A → result A → thinking → tool B → result B → answer；验证 fragment 不逐 token 换行。
2. 增加 normal parameter/result formatting、bounded truncation、0 result、partial/truncated、failure/abort/interruption line recovery。
3. 增加 verbose metadata/timing/usage projection；不得读取 provider-specific字段或 raw Tool Result。
4. 给 `chat` parser 增加 `--verbose`；normal 使用 `trace_profile=normal`，verbose 使用 `debug`。
5. CLI 通过 `application.query(..., on_event=renderer.handle)` 进入同一 Query path；保留 session picker、conversation reuse、trace log export、`/new` 与退出命令。
6. 调整最终结果 projection，避免 streamed answer/error 被重复打印；run-only fake 仍显示正式完整答案。

## Phase 5 — Regression and failure cases

新增/扩展测试：

- provider reasoning normalization、answer delta、provider without/empty reasoning；
- normalized Trace event 与 Runtime delta 的单 sequence mapping；
- Renderer normal/verbose、Unicode、段切换、multi-tool、Tool/Provider failure、0 result、interrupt；
- Application event callback仍只执行一次 Runtime/Router/Planner；
- streaming/non-streaming Conversation final Answer一致且单次 commit；
- persistent Trace 继续包含 route/plan/tool/retrieval/finalization/commit，且不包含 reasoning/token delta；
- existing CLI parser/scope/conversation/trace export behavior；
- blocked/cancelled stream 结束后无 completed/commit，terminal行恢复。

失败时先复现并修实现主链路；不修改测试掩盖实现错误，不加 retry/fallback/单样例分支。

## Phase 6 — Documentation and quality gate

更新最少的现有文档：

- Stage 1.7 / backend Agent Runtime：reasoning normalization 与 structured answer delta。
- Stage 1.9 Trace/Observability：同源 live/persistent projection、reasoning不落盘、Trace Store非队列。
- Stage 1.11 Application/CLI：Application event handler、Renderer normal/verbose、failure/cancellation boundary。
- Interview defense/task validation：事实证据、alternatives、trade-off、failure/observability/scale/evolution。

运行：

```bash
PYTHONPATH=src .venv/bin/pytest -q
PYTHONPATH=src .venv/bin/ruff check src tests
PYTHONPATH=src .venv/bin/mypy src
PYTHONPATH=src .venv/bin/python -m trivae chat --help
python3 ./.trellis/scripts/task.py validate .trellis/tasks/08-23-interactive-cli-streaming-events
git diff --check
```

然后按 `trellis-check` 做全范围 spec/diff/quality review。

## Phase 7 — Real DeepSeek smoke

1. 在系统临时目录复制真实 SQLite 数据库，必要时只在副本重建 derived FTS；不修改用户原始数据库。
2. 用生产 `create_application()` / `trivae chat --verbose` 执行一个真实、需要检索群聊数据的问题。
3. 保存不含 API key/完整私聊正文的验证证据：事件类型/顺序、是否实际存在 thinking、Tool args、真实 retrieval counts、answer delta 数、trace ID、Trace operations、Conversation assistant count 与完整答案一致性。
4. 若 `deepseek-v4-flash` 本次不返回 reasoning，记录“provider/model capability 未返回”而不是伪造；Tool/Retrieval/Answer/Trace/Conversation仍必须验证。
5. Provider/API 失败时记录稳定 error/trace，定位根因；不使用 mock漂亮输出替代 smoke。

## Phase 8 — Finish and commit

1. 更新 task validation/journal/spec implementation record，执行 `trellis-finish-work`/归档要求。
2. 审查 `git diff --stat`、`git diff --check`、secret/raw-data泄漏和中文注释要求。
3. 提交实现与必要的 Trellis 收尾记录，确认 `git status --short` 为空。
4. 最终按用户要求报告文件、事件链、reasoning/tool/answer/Trace、modes、tests、全量结果、真实 smoke、限制、branch/SHA/clean。

## Risk and Rollback Points

- SDK reasoning type：只依赖 0.22.0 public normalized response event；若真实 smoke 与已安装 SDK行为不一致，先保存 failure evidence，再修 adapter主链路。
- JSON delta parser：用 exhaustive chunk-boundary tests 与 final authoritative answer 对照；不承担 citation validation 或 repair。
- Observer wiring：callback 不得成为 Trace Store队列或改变 Collector business availability；用 broken Trace Store regression验证。
- Commit boundary：最后 delta 可先显示，但 `query.completed` 只能在 `commit_turn()` 成功后；沿用 M6 failure attribution。
- 任何 confirmed ADR冲突都回到 planning记录 reopen，不通过兼容/fallback分支绕过。
