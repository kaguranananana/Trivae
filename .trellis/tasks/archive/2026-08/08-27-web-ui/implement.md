# Implementation Plan: ChatLab-style Local Web UI

> 分支：`codex/web-ui`。每个 checkpoint 结束跑一次对应验证命令；提交按 §8 拆分。

## 0. 准备

- [ ] `git checkout -b codex/web-ui`
- [ ] `uv add fastapi uvicorn`（uvicorn 已在 venv 中作为传递依赖，显式声明）
- [ ] 验证：`.venv/bin/python -c "import fastapi, uvicorn"`

## 1. Backend streaming/abort/reasoning 扩展（commit 1）

- [ ] `query/runtime/contracts.py`：`RuntimeEvent` 增加 `thinking_visibility` 字段（默认 `"public_summary"`）
- [ ] `query/runtime/openai_adapter.py`：`_stream_delta` 识别 `response.reasoning_text.delta` → `("reasoning_text", delta)`；`thinking_delta` 事件带 `thinking_visibility="provider_reasoning"`
- [ ] `query/streaming.py`：
  - `QueryStreamEvent.thinking_visibility` 扩展 union
  - `QueryStreamAdapter(thinking_visibility_policy=frozenset("public_summary",))`
  - `project_tool_result_structure(record)` + `tool.completed` 附带 `result_projection`（transport 上限 200）
- [ ] `query/orchestrator.py`：`run(..., abort_event=None)` → `TraceableAgentRuntime(..., abort_event=…)`（collector.py TraceableAgentRuntime.run/_run_stream 透传）
- [ ] `bootstrap/application.py`：`query(..., abort_event=None, thinking_visibility_policy=…)`
- [ ] 验证：`uv run pytest tests/test_query_streaming.py tests/test_query_execution_core.py tests/test_agent_runtime.py -q`、`uv run ruff check src && uv run mypy`

## 2. Conversation Store 扩展（commit 2）

- [ ] `conversation/sqlite.py`：`title_override` / `trace_id` / `process_projection_json` 列 + migration；`rename_conversation` / `delete_conversation`；`list_summaries` preview；`commit_turn(trace_id, process_projection)` 可选参数
- [ ] `conversation/contracts.py`：`ConversationSummary.preview`；`ConversationStore` Protocol 同步
- [ ] `bootstrap/application.py`：facade 方法 `rename_conversation/delete_conversation`
- [ ] 验证：`uv run pytest tests/test_conversation.py tests/test_cli.py -q`（fix 全量回归放 §7）

## 3. Web backend（commit 3）

- [ ] `src/trivae/interfaces/web/{__init__,server,routes,contracts,streaming,projection,conversation,trace_actions}.py`
- [ ] NDJSON streaming：QueryStreamEvent→JSON（含 result_projection）；`stream.started/end` 信封；request_id 归属
- [ ] 取消：per-request asyncio abort_event + disconnect handler + `POST /api/query/stop`
- [ ] scope DTO ↔ ExecutionScope（服务端构造）；conversation scope mismatch → 409
- [ ] trace reveal：resolve/validate/`open -R` 参数数组/local-only/错误码
- [ ] `web/dist` 存在时 StaticFiles 托管 SPA；`trivae web --port --host --no-open --database` CLI 子命令（cli.py 增加，仅参数解析与调用 web.server）
- [ ] 验证：`uv run pytest tests/test_web_server.py -q`（新增：API contract/NDJSON/取消/reveal 安全/scope 校验/conversation CRUD，httpx ASGI 测试）

## 4. Frontend 骨架（commit 4）

- [ ] pnpm create vite (vue-ts) → web/；@nuxt/ui + tailwind 尝试；不兼容则降级纯 tailwind（记录在 commit message）
- [ ] types/contracts.ts + api/client.ts（NDJSON reader + AbortController）
- [ ] stores/chat.ts（buffers 按 conversation、appendEvent 按 request_id）+ stores/conversations.ts
- [ ] 布局：Sidebar + ScopeSelect + ChatView + ChatInput
- [ ] 验证：`pnpm -C web lint && pnpm -C web typecheck && pnpm -C web build`

## 5. Agent Process UI（commit 5）

- [ ] ProcessSegments.ts（timeline/completed 分组，vitest 单测）
- [ ] RouterCard（route/reason/confidence/source/duration）/ PlanCard / ThinkingBlock（多 turn 独立段、折叠+duration、markdown、内部 scroll）
- [ ] ToolBlock（tool_call_id 关联、args JSON、结构化 result items、分页 "20/135 displayed"、partial/truncated/coverage 呈现、Raw JSON secondary view）
- [ ] RetrievalStats / ErrorBlock（失败默认展开 Process Group）
- [ ] Answer streaming + markdown-it + Sources（artifact snapshot；message source 展开上下文经 backend scope 校验接口——第一阶段直接用 artifact snapshot 内容）
- [ ] FollowTail composable +「回到最新」；copy/selection；中文 IME（compositionstart/end 防误发送）

## 6. Conversation 管理 UI + Trace（commit 6）

- [ ] ConversationList（今天/昨天/更早分组、当前高亮、New Chat/Rename/Delete 确认）
- [ ] 历史加载：GET conversation → 消息 + sources + process projection 回放 + trace_id
- [ ] TraceFooter：trace id + Copy ID/Copy Path + Reveal in Finder（错误态显示）
- [ ] 刷新恢复：mount load conversations + last conversation；运行中显示 execution interrupted
- [ ] 验证：`pnpm -C web test && pnpm -C web build`；`trivae web` 手动 smoke

## 7. 质量门（commit 7 前全量）

- [ ] `uv run ruff check src tests && uv run mypy && uv run pytest -q`
- [ ] `pnpm -C web lint && pnpm -C web typecheck && pnpm -C web test && pnpm -C web build`
- [ ] TUI/CLI regression：`uv run pytest tests/test_tui_app.py tests/test_tui_projection.py tests/test_cli_renderer.py tests/test_cli.py -q`

## 8. 真实 smoke + 文档（commit 7/8）

- [ ] 真实 provider smoke：STANDARD 问题（如「最近大家都聊了些什么？」）+ PLAN 问题（多阶段/恢复型），记录 Router reason/confidence、tool 序列、reasoning 字段链路（provider event → RuntimeEvent → QueryStreamEvent → Web block）；拿不到的写 UNAVAILABLE FROM PROVIDER
- [ ] Trace Finder macOS 真机验证 + 非法 id/缺失文件/非 local 拒绝
- [ ] E2E 手动清单（PRD R8 列表 1-26）执行并记录
- [ ] ADR：`technical-decisions/web-primary-interface.md`（含 QueryStreamEvent UI-neutral / Conversation shared capability / Reasoning visibility / Trace Finder / Session≠Conversation 子决策）
- [ ] `interview-defense.md` 增补 web 条目（用户规格 48 的 20 问）
- [ ] commits：feat(web) ×4~5 / test(web) / docs(web)

## 9. 收尾

- [ ] trellis-check 全量；spec 更新（backend/directory-structure web 目录、product-experience web 章节）
- [ ] journal 记录；任务归档
