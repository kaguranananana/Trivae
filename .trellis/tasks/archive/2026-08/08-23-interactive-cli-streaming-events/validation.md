# Interactive CLI Streaming Validation

## Automated quality gate

- Baseline before implementation：178 tests passed；ruff、mypy passed。
- Targeted streaming/CLI suite：33 tests passed。
- Full suite after implementation：197 tests passed。
- `ruff check src tests`：passed。
- `mypy src`：58 source files passed。
- `python -m trivae chat --help`：显示 `--verbose`。
- `git diff --check`：passed。
- Trellis task validation：passed。

## Contract evidence

- OpenAI Agents SDK public `response.reasoning_summary_text.delta` / `response.reasoning_text.delta` 被归一化为 `RuntimeEvent(thinking_delta)`；empty/no reasoning 不产生 delta。
- `response.output_text.delta` 进入 Answer Artifact 增量 parser，只输出 `content_blocks[*].text`；逐字符 chunk-boundary 测试覆盖中文、escape、Unicode surrogate pair、多 block、plain text、malformed/incomplete JSON。
- `QueryStreamAdapter` 合并 Runtime delta 与 Router/Planner/Tool/Retrieval/Finalizer/Query normalized facts，并为单次 live projection 分配单调 sequence。
- TraceCollector 以同 event identity/sequence 构造 pre-capture live projection 和 CapturePolicy 后的 persisted projection；normal 512 字符上限不会截断 live authoritative answer，Trace Store failure 也不需要 CLI polling。
- Renderer 测试覆盖 Thinking → Tool A → Result A → Thinking → Tool B → Result B → Answer、连续 token 不逐行、0 result、Tool failure recovery、Provider/Query failure、无 reasoning、verbose metadata 与 terminal line recovery。
- Application regression 证明 streaming/non-streaming 共用同一个 Query 主链路；Conversation 只保存一个完整 Assistant message，Trace 不保存 thinking/content token delta。

## Real DeepSeek interactive CLI smoke

- 日期：2026-08-23；provider/model：DeepSeek / `deepseek-v4-flash`。
- 数据：只复制 `data/trivae.sqlite3` 到系统临时目录后运行；原始数据库未修改，临时副本不提交。
- 命令：真实 `python -m trivae chat --verbose --database <temporary-copy>`，选择 `All chats`，问题要求检索聊天记录中有明确消息证据的 GitHub 项目。
- 第一次启动没有把 `.env` 导出到进程，真实得到 `DEEPSEEK_API_KEY is required` 和 failed Trace；没有用 mock 替代。按当前 Settings contract 显式导出 `.env` 后重新执行成功。
- 终端真实顺序：`query.started → route.completed → Thinking → Tool/Retrieval × 8 → Thinking → Answer fragments → usage → answer.finalization.completed → query.completed → next prompt`。
- reasoning：DeepSeek 本次确实返回非空 reasoning；`Thinking...` 后内容在首个 Tool Call 前持续输出，来源是 SDK public reasoning delta，不是 Trivae 生成。
- Tool / Retrieval：8 次真实 `search_messages`；8 次 retrieval started/completed；终端显示真实 keyword、limit、context window、candidate/total/expanded/returned、coverage、partial、truncated 和 measured latency。示例首轮为 20 candidates / 464 total / 20 expanded / 20 returned。
- Answer：`Answer:` 正文先于 finalization/query completion 出现在终端，并跨多个终端读取周期连续增长；未输出 raw Answer Artifact JSON。
- 成功 Trace：`trace-8fd98e990287459ebc0738b581ddf6b7`，terminal/completeness 都为 `completed/complete`。
- Trace 核验：8 `tool.call.started`、8 `tool.call.completed`、8 `retrieval.search.started`、8 `retrieval.search.completed`、1 finalization、1 Conversation commit、1 query completed；0 persisted thinking event、0 persisted content delta event。
- Conversation 核验：1 个 Assistant message，正文长度 560；与 Debug Trace 的 validated final answer snapshot 完全一致。
- Ctrl+C 未用于真实 Provider run，以避免丢弃已完成的证据链；中途 cancellation/terminal restoration 由 deterministic CLI test 覆盖。

## Known limitations

- Provider reasoning 是 optional capability；本次 DeepSeek 返回了 reasoning，但其他 Provider/Model 不返回时只展示其余事件。
- reasoning 内容与长度由 Provider 决定；verbose 真实 smoke 显示其可能很长。当前普通终端按需求原样流式展示，不提供复杂 TUI、折叠或速率控制。
- `plan.delta` 未实现，因为当前 Planner 是一次性 completion 并没有真实 streaming delta；CLI 只展示已有 `planner.completed/failed`。
- 当前 CLI 是同步 event callback + 普通 terminal write；HTTP/SSE、Web UI、重放 live stream 与跨进程消息队列均不在本任务范围。
- `.env` 不由 Settings 自动加载；运行真实 Provider 前仍需按现有项目 contract 将变量导出到进程环境。
