# Design: ChatLab-style Local Web UI

## 1. 现状审计结论（Architecture Audit）

### 1.1 Trivae 既有链路

```
QueryRequest(query, scope, conversation_id)
  → TrivaeApplication.query(on_event=QueryStreamEventHandler)
      ├─ ConversationStore.get/create + scope 校验（scope mismatch 显式拒绝）
      ├─ TraceCollector(trace_id) ── event_observer → QueryStreamAdapter.handle_normalized_event
      └─ QueryOrchestrator.run(trace, runtime_event_observer)
            ├─ RuleRouter.route → RouteDecision(route, confidence, source, reason, degraded)  → trace "router.decision"
            ├─ SoftPlanner.plan → Plan(steps/success_criteria)                                → trace "planner.completed/failed"
            └─ TraceableAgentRuntime.run
                  └─ OpenAIAgentsRuntimeAdapter.stream(request, abort_event=None)
                        ├─ RuntimeEvent(thinking_delta[public_summary], content_delta, tool_started/completed+ToolResultRecord, usage…)
                        └─ Finalizer → AnswerArtifact(content_blocks/citations/evidence/limitations)
  → QueryResult(runtime_result, route_decision, plan, answer_artifact, conversation_id, trace_id)
  → conversation_store.commit_turn(user, artifact)
```

关键事实：

- `QueryStreamEvent`（query/streaming.py:43）已是 UI-neutral：type/sequence/content/thinking_visibility/route/plan/tool_name/tool_call_id/arguments/result_summary/result_detail/usage/metadata。
- `project_tool_result_detail()`（streaming.py:72）是 TUI 专用 bounded 文本（20 items/16k chars）；结构化数据在 `RuntimeEvent.tool_result: ToolResultRecord` 中已经存在，Web 需要自己的 projection。
- Router reason/confidence 已被 capture（orchestrator.py:116-135 `router.decision` payload + adapter metadata 复制 reason/confidence/source）。
- Thinking：adapter 只转发 `response.reasoning_summary_text.delta`（public summary），丢弃 `response.reasoning_text.delta`（hidden reasoning text，openai 兼容 provider 会真实下发）；`thinking_visibility` 硬编码 "public_summary"。
- Stop 现状：TUI 直接 cancel worker（asyncio cancellation），trace 无 terminal event；adapter 已支持 `stream(request, abort_event)` 优雅取消（termination="aborted" + 完整清理），但 `application.query()/orchestrator.run()` 没有把 abort_event 传下去。
- Conversation Store：`conversations + conversation_messages(ordinal, role, content, answer_artifact_json, created_at)`；title 从首条 user message 派生；无 rename/delete/preview/trace_id。
- Trace 文本日志：`TraceTextLogWriter(store.database_path.parent / "traces")`，路径规则 `traces/{trace_id}.log`，trace_id 已拒绝路径分隔符。

### 1.2 ChatLab 参考实现（实际阅读的文件）

| 文件 | 继承的设计 |
| --- | --- |
| `src/stores/aiChat.ts`（2141 行） | `aiChatBuffers: Record<convId, AIChatBuffer>` 每 conversation 独立 buffer；stream 写入 send 时捕获的 `targetBuffer`（不是 current buffer）→ 切换不串线；`bindDisplayedBuffer` 只切显示；`aiChatSelectionGenerations` 防陈旧异步加载；draft buffer `__draft__` 创建后 rename 为真实 id；ContentBlock{type:text/think/tool/plan/error}；`updateToolBlockStatus` 按 toolCallId 精确匹配（fallback name）；processDurationMs 记录；persisted contentBlocks 回放 |
| `chatMessageProcessSegments.ts` | `ProcessSegment = {process, blocks[]} | {visible, block}`；timeline 模式（streaming 中 think/tool 连续块成组，text 切段）；completed 模式（过程块+中间文本合并为单个 process group，最终 answer 可见）；active segment 显示当前活动（tool 名/thinking）；错误组默认展开 |
| `ChatMessage.vue` | markdown-it（html:false）+ LRU 缓存；think 块折叠+duration；tool 块 args/result 展开；LiveFollowText；process header（已思考 Xs · N steps） |
| `liveFollowText.ts` / `useChatScroll.ts` | follow-tail：底部自动跟随，上滚暂停，回到最新按钮（真实 scroll state） |
| `ConversationList.vue` | conversation 分组列表（今天/昨天/更早） |

不继承：Electron/IPC 边界、session-scoped AIChatKey（Trivae 用 conversation_id 直接索引 buffer）、saveAIChatMessages 前端持久化（Trivae 由 backend commit_turn 持久化）。

## 2. 目标架构

```
Browser (Vue3 + Pinia + Nuxt UI/Tailwind, web/)
  │  HTTP JSON + NDJSON stream (fetch ReadableStream)
  ▼
src/trivae/interfaces/web/   (FastAPI + uvicorn, 127.0.0.1)
  ├─ server.py        create_web_app(application) + StaticFiles(web/dist) + 启动/自动开浏览器
  ├─ routes.py        /api/readiness /api/source-sessions /api/conversations[...] /api/query/stream /api/traces[...]
  ├─ contracts.py     请求/响应 DTO（scope 快照 ↔ ExecutionScope 转换，服务端构造，不信任前端任意 scope 字段）
  ├─ streaming.py     QueryStreamEvent → NDJSON encoder + abort_event lifecycle + disconnect 取消
  ├─ projection.py    WebToolResultProjection(record) 结构化投影（新增，additive）
  ├─ conversation.py  list/open/create/rename/delete 路由实现（复用 conversation store 扩展）
  └─ trace_actions.py trace log resolve + local-only reveal
  ▼
TrivaeApplication.query(request, on_event=web_handler, abort_event=…, thinking_visibility_policy=…)
  → QueryOrchestrator → Router/Planner/Runtime（唯一执行链路，无第二套）
QueryStreamEvent（UI-neutral）
  ├─ Plain CLI (cli_renderer.py，不变)
  ├─ TUI (tui/models.py TuiProjectionEngine，不变)
  └─ Web (streaming.py NDJSON) → Pinia store buffer → Vue components
```

## 3. Backend 变更（全部 additive）

### 3.1 Streaming / Runtime 契约扩展

- `RuntimeEvent`：`thinking_delta` 携带 `thinking_visibility: "public_summary" | "provider_reasoning"`（默认 public_summary）。`_stream_delta` 将 `response.reasoning_text.delta` 映射为 `("reasoning_text", delta)`，runtime yield `thinking_delta(visibility="provider_reasoning")`——这是 provider/SDK 实际下发且应用层合法获得的内容，不反推、不伪造。
- `QueryStreamEvent.thinking_visibility` 扩展为同 union。
- `QueryStreamAdapter(handler, trace_id, thinking_visibility_policy=("public_summary",))`：policy 决定哪些 delta 通过（默认保守，CLI/TUI 不变；Web 传 `("public_summary","provider_reasoning")`）。
- `TrivaeApplication.query(..., abort_event=None, thinking_visibility_policy=…)`：abort_event 透传 `QueryOrchestrator.run` → `TraceableAgentRuntime` → `runtime.stream(request, abort_event)`。取消语义 = 优雅 abort（termination="aborted"、provider task 清理、trace `query.aborted` terminal）。
- 结构化 Tool Result：`QueryStreamAdapter` 在 `tool.completed` 时附带 `result_projection: Mapping | None`（由 `project_tool_result_structure(record)` 生成；CLI 忽略该字段）。`project_tool_result_structure` 位于 streaming.py，输出：

```json
{
  "tool_call_id": "...", "tool_name": "semantic_search", "status": "ok",
  "arguments": {...},
  "result": {
    "items": [ {"source_handle": "m3-1", "sender": "张三", "timestamp": "...",
                "session": "27届群", "content": "...", "hit": true, "urls": []} ],
    "item_kind": "messages|structured|none",
    "total_items": 135, "hit_items": 12, "expanded_items": 6,
    "limitations": [...], "partial": false, "truncated": false, "coverage": "complete"
  },
  "transport_max_items": 200
}
```

  transport 上限 200 items（超过则 `transport_truncated=true`，完整数据仍在 ToolResultRecord/Trace）；UI 折叠默认 20 条并显示 `20 / 135 displayed`。

### 3.2 Conversation Store 扩展（additive，向后兼容）

- `conversations` 加 `title_override TEXT` 列（migration 同 `_ensure_scope_column` 模式）；summary title = override or 首条 user message。
- `conversation_messages` 加 `trace_id TEXT` 列；`commit_turn` 增加可选 `trace_id` 与 `process_projection_json`（bounded 过程摘要 JSON：router decision、plan steps、tool calls(name/args/status/counts)、retrieval stats、duration）。
- 新增 `rename_conversation(id, title)` / `delete_conversation(id)`（只删 conversations+conversation_messages 两张表，canonical chat 表不受影响）/ `list_summaries` 增加 last-message preview 字段。
- Application facade 增加对应方法。

### 3.3 Web API contract

| Method | Path | 说明 |
| --- | --- | --- |
| GET | /api/readiness | application.readiness() |
| GET | /api/source-sessions | list_sessions() 投影（session_id/name） |
| GET | /api/conversations?limit= | summaries + scope display + preview，按 updated_at |
| POST | /api/conversations | {scope} → Conversation（New Chat 先建后问） |
| GET | /api/conversations/{id} | 全量：messages（user/assistant+sources+trace_id+process projection） |
| PATCH | /api/conversations/{id} | {title} rename |
| DELETE | /api/conversations/{id} | 删 AI conversation |
| POST | /api/query/stream | {query, scope, conversation_id, request_id} → NDJSON stream；响应头带 X-Request-Id/X-Trace-Id |
| GET | /api/traces/{trace_id} | trace projection（replay 面板数据源） |
| POST | /api/traces/{trace_id}/reveal | local-only；resolve→canonicalize→校验在 traces 目录内→subprocess.run(["open","-R",path]) |

Scope DTO：`{"mode":"all"}` 或 `{"mode":"sessions","session_ids":[...]}` + 可选时间窗；服务端构造 `ExecutionScope`（默认 max_results），禁止前端传任意字段。follow-up 校验：请求 scope 必须等于 conversation.scope，否则 409（与 application 层双保险）。

Streaming 协议（NDJSON，每行一个 JSON 对象）：

```
{"type":"stream.started","request_id":…,"conversation_id":…,"trace_id":…}
{"type":"<QueryStreamEventType>", "request_id":…, ...QueryStreamEvent 字段（含 result_projection）}
…
{"type":"stream.end","request_id":…,"status":"completed|failed|aborted","conversation_id":…,"trace_id":…,"error_code":…}
```

- 事件按 `request_id` 归属；前端 store 按 request_id 写 buffer。
- 取消：客户端 `AbortController.abort()`（fetch 断连 → uvicorn 断连检测 → server task cancel + abort_event.set()）与 `POST /api/query/stop {request_id}`（显式 Stop 按钮备用路径，双通道都 set abort_event）双通道；最终以 `query.aborted` / `stream.end(status=aborted)` 收尾。

### 3.4 Trace reveal 安全边界

- 只接受 `trace_id`；`TraceTextLogWriter.log_path()` 已拒绝分隔符；再 `resolve()` 后校验 `path.parent == traces_dir.resolve()` 且文件存在；非 127.0.0.1 绑定（`--host` 显式非 local）时 endpoint 返回 403 `REVEAL_LOCAL_ONLY`。macOS `open -R` 用参数数组；其他平台返回 `REVEAL_UNSUPPORTED_PLATFORM`。

## 4. Frontend 设计（web/）

```
web/
├── package.json / vite.config.ts / tsconfig.json / pnpm
├── index.html
└── src/
    ├── main.ts / App.vue / style.css (tailwind + @nuxt/ui theme)
    ├── api/client.ts            # fetch 封装 + NDJSON reader
    ├── types/contracts.ts       # QueryStreamEvent/Conversation/Scope/ToolResultProjection TS 类型
    ├── stores/
    │   ├── conversations.ts     # list/create/open/rename/delete + scope picker
    │   └── chat.ts              # ChatLab 模式：buffers: Record<convId, ConversationBuffer>；
    │                            # streams: Map<requestId, {abort}>；appendEvent(requestId, event)
    │                            # 按 event.request_id 写 owner buffer；切换 conversation 仅改 currentId
    └── components/
        ├── chat/ ChatMessage.vue / ProcessGroup.vue / ProcessSegments.ts (timeline/completed 分组，含单测)
        │        RouterCard.vue / PlanCard.vue / ThinkingBlock.vue / ToolBlock.vue (args JSON + result items 分页)
        │        RetrievalStats.vue / ErrorBlock.vue / SourcesBlock.vue / TraceFooter.vue
        ├── sidebar/ ConversationList.vue / ScopeSelect.vue
        └── composer/ ChatInput.vue (Send/Stop、IME 组合、Enter 发送)
```

- `ChatMessage.vue` 复刻 ChatMessage.vue 的 block 分段逻辑（timeline/completed 双模式；错误默认展开；Answer 在组外）。
- Follow tail：scroll container 监听 scroll；距底 <40px 时跟随；上滚暂停并显示「回到最新」。
- Markdown：`markdown-it`（html:false, linkify, target=_blank）+ LRU 缓存（同 ChatLab）。
- History replay：GET conversation → user/assistant messages；assistant 附带 sources（artifact snapshot）+ trace_id + process projection → ProcessGroup 静态回放；「Trace 详情」经 GET /api/traces/{id} 展开。
- 刷新恢复：mount 时 load conversations + 打开最近 conversation；运行中 request 无法 re-attach → 该轮显示 execution interrupted（第一阶段明确允许）。

## 5. 权衡与备选

- NDJSON vs SSE：POST body + fetch ReadableStream 下 NDJSON 无 SSE 的 POST 限制，语义一致；保留升级空间。
- @nuxt/ui：v4 支持 Vite+Vue；若与 Node 26/pnpm 冲突则降级纯 Tailwind 自研 Collapsible/Tooltip（组件少，风险可控）。
- process projection 持久化：选择 bounded JSON 列而非整份 ToolResultRecord 复制（大 raw result 留在 Trace/canonical，conversation 只存引用与摘要）。
- 前端不做 SQLite/localStorage 历史副本。

## 6. 回滚

- 全部后端变更为 additive（新参数带默认值、新列 nullable、新文件独立）；revert web 相关 commits 即回到 main 行为；conversation 新列不破坏旧 Store 读取。
