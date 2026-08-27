# ChatLab-style Local Web UI

## Goal

把 Trivae 既有的 Agent Runtime / Router / Planner / Tool / Retrieval / Thinking / Streaming / Evidence / Conversation / Trace 完整投影成 ChatLab 风格的 Local Web UI，作为 primary user interaction surface（第一阶段 Local only，不做 Electron/Tauri）。Web 只是 interface：所有执行仍通过 `TrivaeApplication.query()` 唯一主链路，`QueryStreamEvent` 保持 UI-neutral。

## Product Positioning

- Plain CLI = script / CI / fallback
- Textual TUI = developer / lightweight interface（保留，不删除、不回归）
- Web UI = primary user interaction surface（本任务）

`trivae web` 启动 Python backend + 已构建的 Web frontend 并自动打开浏览器，默认 `127.0.0.1`。

## Requirements

### R1 单一执行入口

- Web route 禁止直接调模型 / Retrieval / Tool / sqlite3 / 自建 conversation memory；一切经 `TrivaeApplication`。
- 前端禁止直接访问 SQLite 或 provider raw SDK。

### R2 Streaming contract

- 复用 `QueryStreamAdapter` / `QueryStreamEvent`，Web 不依赖 `TuiProjectionEngine`。
- HTTP POST + NDJSON streaming（fetch ReadableStream），不引入 WebSocket。
- Router decision（route/reason/confidence/source/degraded）、Plan、Thinking、Tool（tool_call_id 关联）、Retrieval stats、Answer、Usage、Failure 全部真实投影；不伪造过程。
- Stop 必须真正取消 backend query：通过新增的 graceful abort_event 链路（additive，CLI/TUI 行为不变），终态 `query.aborted`；浏览器断连同样触发取消。
- Reasoning visibility 扩展为 `public_summary | provider_reasoning`：Runtime adapter 将 provider 实际返回的 reasoning（如 `response.reasoning_summary_text.delta` 与兼容 provider 的 `reasoning_text.delta`）标准化保留，Web 展示；CLI/TUI 保持原 public_summary 保守策略。provider 未提供的 hidden CoT 不伪造、不反推。

### R3 Agent Process 展示（ChatLab 风格）

- 每轮 assistant 回答由 content blocks 组成：router / plan / thinking（多 turn 各自成段）/ tool（arguments + 结构化 result + status + duration）/ retrieval stats / answer / error。
- 流式时 timeline 模式实时出现；完成后收拢为「执行过程 · N steps · Xs」，错误时默认展开；Answer 永远在 Process Group 外。
- Tool 关联必须用 `tool_call_id`，retrieval 归并用 `parent_operation_id`。
- Tool Result 使用结构化 `WebToolResultProjection`（不再以 TUI bounded 文本为正式数据层）：默认展示前 N 条 + `X / Y displayed` 标记；transport 截断与 UI 折叠显式区分；partial/truncated/coverage 如实展示。

### R4 Conversation 管理

- 明确区分 Source Session（=ExecutionScope，决定 Retrieval 范围）与 AI Conversation（=conversation_id）；UI 左侧 Conversations + 顶部 Scope。
- 至少实现 New Chat / List / Open / Resume / Rename / Delete（仅删 AI conversation，绝不触碰 canonical chat messages）。
- 历史来自正式 Conversation Store（扩展 rename/title override/delete/preview，additive）；assistant 历史带 sources（artifact）与 trace_id 引用；重新打开后可见 User / Answer / Sources / 执行过程（trace 回放 + 持久化的 bounded process projection），并可沿用原 conversation_id 继续 follow-up。
- Conversation buffer 模式（参考 ChatLab aiChat.ts）：每个 conversation 独立 buffer，stream 写回 owner buffer（request_id + conversation_id 归属），切换 conversation 不串线、不丢运行状态；刷新后 reload conversations/history（运行中 query 允许显示 execution interrupted）。

### R5 Sources / Evidence

- Answer 下方展示 Sources（来自 AnswerArtifact/canonical evidence，不从答案文本猜 [1]），可展开完整 message（sender/timestamp/session/content）。

### R6 Trace Finder integration（local only）

- 每轮 answer 底部 Trace ID + Copy ID/Path + Reveal in Finder。
- `POST /api/traces/{trace_id}/reveal`：backend resolve trace log file、canonicalize、验证位于 traces 目录内、`subprocess.run(["open","-R",path])`（参数数组，无 shell）；非法/不存在 trace 返回 `TRACE_FILE_NOT_FOUND`；仅 localhost 绑定启用。

### R7 UI / UX

- Vue 3 + TypeScript + Vite + Pinia + Tailwind + @nuxt/ui（若构建不兼容则降级纯 Tailwind 自研组件），pnpm。
- 布局：左侧 Conversations sidebar（今天/昨天/更早分组、当前高亮），顶部 Scope 选择，主区 ChatLab 风格消息流，底部输入框（Send/Stop 切换）。
- Follow tail：底部自动跟随；上滚即暂停并显示「回到最新」；使用浏览器真实 scroll state。
- Markdown 渲染 answer（code/table/link/inline code，XSS 安全）；thinking 内部可滚动；copy/中文 IME 正常。

### R8 质量门

- Python：ruff + mypy + pytest 全绿；现有 TUI/CLI/query streaming 测试不回归。
- Frontend：lint + typecheck + build 通过；核心 store/process-segments 单测。
- 真实 provider smoke：真实问题验证 STANDARD 与 PLAN 两条路由、真实 tool sequence、真实 reasoning 字段链路（provider event → RuntimeEvent → QueryStreamEvent → Web block），拿不到的如实标注 UNAVAILABLE FROM PROVIDER。
- macOS Finder 真机验证 reveal；非法 trace_id/文件缺失/非 local 拒绝。
- 文档：ADR（Web primary interface / QueryStreamEvent UI-neutral / Conversation shared capability / Reasoning visibility / Trace Finder / Session≠Conversation）+ interview-defense 更新。

## Acceptance Criteria

- [ ] `trivae web` 启动并自动打开浏览器；左侧列出历史 AI Conversations
- [ ] 打开旧 conversation 可见 User / Answer / Sources / Trace，可继续 follow-up（沿用原 conversation_id 与 scope）
- [ ] 新建 conversation 提问可实时看到 Router(PLAN/STANDARD+reason) / Plan / Thinking(provider reasoning) / Tool(arguments+结构化 result) / Retrieval stats / Answer streaming / Sources / Trace
- [ ] Reveal in Finder 在 macOS 打开并选中 trace 文件；非法 id 显式报错
- [ ] Stop 真正取消（终态 query.aborted）；切换 conversation stream 不串线；上滚不抢回底部
- [ ] TUI/CLI 测试全绿；ruff/mypy/pytest、web lint/typecheck/build 全绿
- [ ] 独立 branch `codex/web-ui`，按 feat/test/docs 拆分 commit

## Notes

- 需求编号 1-50 对应用户原始规格；本 PRD 为其收敛版。
- 技术决策：FastAPI+uvicorn（后端）、@nuxt/ui+Tailwind（前端，降级预案：纯 Tailwind 自研）、graceful abort_event 链路（additive 扩展）。
