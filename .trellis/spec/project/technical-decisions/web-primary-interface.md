# Web becomes primary interaction interface（Local Web UI 架构决策）

> 状态：**Confirmed / Implemented（2026-08-27，branch codex/web-ui）**
>
> 本 ADR 记录把 ChatLab 风格 Local Web UI 建成 Trivae primary interaction surface 的完整决策链，
> 覆盖七个子决策：Web primary interface、QueryStreamEvent 保持 UI-neutral、Conversation history
> 作为共享领域能力、provider reasoning visibility、local Trace Finder integration、Source Session ≠ AI Conversation、
> trusted URL rendering 与 Sources collapsed presentation。
> 所有决策均以真实实现与真实 provider smoke 为证据，不含未验证的设想。

---

## 1. Context：为什么从 TUI 增加 Web

Trivae 此前已有 Plain CLI 与 Textual TUI 两个入口，均消费同一 `QueryStreamEvent` 流。TUI 已完成 streaming/thinking/tool/retrieval/follow-tail/selection/IME 等交互工程，但终端存在天然上限：

- Tool Result 只能以 bounded 纯文本（`project_tool_result_detail`：20 items / 16k chars）展示，用户无法直接查看真实检索到的消息结构化数据。
- Router decision reason、Plan steps、Retrieval coverage/partial 等 diagnostics 在终端只能一行摘要。
- 历史 conversation 的过程信息无法富回放；长文本浏览、点击展开、Finder/OS 集成都不是终端擅长的形态。

ChatLab（本地优先聊天分析产品）把 Web UI 作为 AI Chat 的 primary surface，其 `aiChat.ts` store 与 process segments 模型验证了该形态。因此 Trivae 产品定位调整为：

```
Plain CLI      = script / CI / fallback
Textual TUI    = developer / lightweight interface
Web UI (local) = primary user interaction surface
```

### Why not Electron/Tauri / 远程 Web

- 第一阶段产品是单用户本机工具；`trivae web` 启动 Python backend + 静态托管已构建 SPA + 自动打开浏览器即可覆盖全部需求。
- Electron 会引入打包/更新/双 runtime 成本，而 Web 需要的只是本机浏览器。
- 绑定 `127.0.0.1` 保持本地信任边界；未来 remote 部署需另行设计认证与 OS 能力裁剪（reveal 已按 host 判定禁用）。

## 2. QueryStreamEvent remains UI-neutral

### Decision

Web 流式层**只消费既有 `QueryStreamAdapter` / `QueryStreamEvent`**，不依赖 `TuiProjectionEngine`，不在 Web route 建立第二套执行链：

```
Runtime/Normalized Events → QueryStreamAdapter → QueryStreamEvent
  ├─ Plain CLI (cli_renderer)
  ├─ Textual TUI (TuiProjectionEngine)
  └─ Web (interfaces/web/streaming.py → NDJSON → Vue store)
```

本任务对契约做了三类 **additive** 扩展（全部带默认值，CLI/TUI 行为不变）：

1. `thinking_visibility: "public_summary" | "provider_reasoning"`（RuntimeEvent / QueryStreamEvent）。
2. `QueryStreamAdapter(thinking_visibility_policy=…)`：消费端选择放行哪些 reasoning；默认仅 `public_summary`。
3. `tool.completed` 附带 `result_projection`（`project_tool_result_structure`，结构化 Tool Result 投影，transport bound 200 items）；TUI 继续用 `result_detail` 文本。
4. `application.query(..., abort_event=None)`：优雅取消信号沿 Application → Orchestrator → TraceableAgentRuntime → `runtime.stream(request, abort_event)` 透传。

### Why not

- **Web 直接调 SDK/provider**：违反唯一执行链（Stage 1.11），Trace/Evidence/Scope 语义会立刻分叉。
- **QueryStreamEvent → TuiProjectionEngine → Web**：把 Web 绑到终端投影模型，结构化 Tool Result 无法表达。
- **WebSocket**：POST query + 单向事件流用 HTTP streaming（fetch ReadableStream + NDJSON）已足够，WebSocket 增加连接生命周期/重连/代理复杂度，无对应需求。
- **前端自己拼 Tool Result 文本**：interface-owned projection 必须由拥有 canonical 数据的层生成。

## 3. Conversation history is shared domain capability

### Decision

Conversation 管理建立在正式 `ConversationStore`（SQLite）之上并做 additive 扩展：

- `conversations.title_override`（rename）、`conversation_messages.trace_id`（trace 引用）、`process_projection_json`（bounded 过程摘要，≤32k chars）。
- `rename_conversation / delete_conversation`（只删 AI conversation 聚合，canonical chat 表不可触碰）；`list_summaries` 增加 last-message `preview`。
- `TurnProcessCollector`（conversation/process.py，UI-neutral）：从 QueryStreamEvent 流收集 router decision / plan / thinking（有界，截断显式标记）/ tool calls（tool_call_id + arguments + item counts）/ retrieval stats / usage / error，随 `commit_turn` 持久化。

Web 前端复刻 ChatLab `aiChat.ts` buffer 架构：每个 conversation 独立 buffer；stream 事件按 `request_id → owner buffer` 写回（`streamOwners` map），与"当前显示哪个 conversation"完全解耦；draft buffer 在首次发送时经 `POST /api/conversations` 转正。

### Why not

- **web_conversations.json / localStorage / 前端 SQLite**：建立第二套 conversation 数据源，TUI/API 无法复用，且与 Application scope 契约冲突。
- **把整份 ToolResultRecord 复制进 conversation**：canonical 大 payload 重复存储；正确形态是 conversation 保存引用与 bounded 摘要，完整过程事实归 Trace。

### Stream 归属与取消

- 每个请求由 `request_id + conversation_id` 确定 owner；前端绝不依据 `currentConversation` 决定事件落点。
- Stop 按钮 → `POST /api/query/stop` → backend abort_event → runtime 优雅取消 → `query.aborted` terminal → `stream.end(status=aborted)`；浏览器断连由服务端轮询 `is_disconnected()` 同样触发 abort。

## 4. Provider reasoning visibility

### Decision

推翻"所有 provider reasoning 一律压缩为 public_summary"的旧口径，改为显式可见性契约：

| 值 | 来源 | 消费方 |
| --- | --- | --- |
| `public_summary` | provider 公开 reasoning summary（`response.reasoning_summary_text.delta`） | CLI / TUI / Web（默认） |
| `provider_reasoning` | provider/SDK 实际下发的 raw reasoning text（`response.reasoning_text.delta`） | Web（policy 显式开启） |

边界（不可协商）：

- 只透传 provider 真实返回的内容；provider 未给 hidden CoT 时**不反推、不模拟、不从答案反向生成、不绕过 SDK 访问限制**。
- CLI/TUI 维持原 public_summary 保守策略（policy 默认值保证）；Web 由 `WEB_THINKING_VISIBILITY_POLICY` 放行两类。
- Secrets/credentials 过滤边界不变：visibility 提升不豁免 secret redaction。

真实 provider 证据（DeepSeek V4 Flash via opencode-go，2026-08-27 smoke）：provider 仅下发 reasoning **summary** delta；`response.reasoning_text.delta` 在该 provider/model 上未出现 → **UNAVAILABLE FROM PROVIDER**（adapter 链路已就绪并有单测覆盖，provider 暴露即可透传）。

## 5. Local Trace Finder integration

### Decision

`POST /api/traces/{trace_id}/reveal` 由 backend 实现：

1. `application.read_trace(trace_id)` 验证 canonical trace 存在；
2. `TraceTextLogWriter.log_path()` resolve 文件（trace_id 已拒绝路径分隔符）；文件缺失时按同样规则 `export_trace_log` 补建；
3. `resolve()` 后校验 `path.parent == traces 目录`（defense-in-depth）；
4. macOS 以**参数数组**调用 `subprocess.run(["open", "-R", path])`，`shell=False`，超时 10s。

安全边界：前端只能传 trace_id，永远不传路径；`REVEAL_LOCAL_ONLY`（非回环 host 绑定 → 403）、`TRACE_NOT_FOUND`/`TRACE_FILE_NOT_FOUND`（404）、`TRACE_ID_INVALID`/`TRACE_PATH_OUTSIDE_ALLOWED_DIRECTORY`（400）、`REVEAL_UNSUPPORTED_PLATFORM`（501）。

### Why not

- 浏览器不能（也不应）直接驱动 Finder。
- 接受路径参数 → 任意路径打开漏洞；因此 identity-only + backend resolve + 目录边界校验三层防御。

## 6. Source Session ≠ AI Conversation

### Decision

UI 与 API 显式区分两个概念：

- **Source Session**（微信群/私聊）决定 Retrieval 数据范围 = `ExecutionScope`；Scope 选择器只允许 `all` / 指定 session_ids，由**后端**编译为 trusted `ExecutionScope`，不接受前端任意字段。
- **AI Conversation**（多轮问答）= `conversation_id`；左侧 Sidebar 列出 Conversations，顶部展示 Scope。

conversation scope 是不可变的完整快照，follow-up 的 scope 必须与 conversation.scope 严格相等：
Web route 预检返回 409 `SCOPE_MISMATCH`，Application 层 `_conversation_for_request` 双保险再次校验。
顶部 selector 当前只表达 `mode/session_ids`；它与当前 conversation 的可表达部分相同时，前端继续发送
conversation 保存的完整时间/容量快照；用户改变选择时，下一次发送转入绑定新 scope 的 draft/new
conversation，不修改旧 conversation，也不等待后端拒绝后重试。Source Session 与 AI Conversation 仍是两个
概念，但不可变 scope 要求不同选择使用不同 AI Conversation。

## 7. Trusted URL rendering 与 Sources 展示

### Decision

Web 正文的链接信任边界由最终 `SourceItem.snapshot.urls` 决定：`AssistantTurn` 只把每个来源
snapshot 中的 URL 去重后传给 Markdown renderer；renderer 在 Markdown token 层对自动 URL、autolink
和显式 `[label](href)` 做 HTTP(S) 与完整字符串匹配。没有对应 canonical snapshot URL 的正文 URL、
相似 URL 或模型重新抄写的 URL 只作为普通文本显示，不生成 `<a href>`。renderer 不使用最终 HTML
正则替换，也不读取 excerpt 或重新检索来源。

`SourcesBlock` 默认显示 `▶ Sources · N`，使用当前组件实例内的真实 button 控制展开；展开后继续
展示既有完整 source detail，空列表不渲染 block。展开状态不进入 Pinia、conversation payload 或
backend artifact，因此多个 Assistant Turn 和历史 replay 互不共享状态，重新挂载默认折叠。

### Source semantics

Sources 是 Finalizer 通过 Evidence claim/source 绑定、current Tool Result provenance/scope/locator
与 canonical metadata 校验后，经 `answer_source_summaries()` 按 Evidence 顺序投影并按 canonical
identity 去重的可审计来源列表。它不是 Retrieval Top N、最近消息、excerpt 相似度或随机挑选。

Host 校验确认“这个 source 是否来自当前 run 的可信结果、是否在 scope 内、是否能定位到 canonical
metadata”；`validate_answer_artifact()` 不承担完整自然语言 semantic entailment judge。`supports`、
`context`、`contradicts` 是 Evidence 与 finding 的语义关系标签，Web Sources 不宣称经过独立 LLM
Judge 对回答做了强相关性认证。

## 8. Failure Cases 与验证证据

| Failure Case | 验证 |
| --- | --- |
| 切换 conversation 后 stream 串线 | store 单测 `keeps stream writes in owner buffer…`；事件按 request_id 落 owner buffer |
| Stop 只是前端停止渲染 | 真实 smoke：stop → `query.aborted` + `stream.end(status=aborted, RUN_ABORTED)`；conversation 0 commit；E2E 点击 Stop → 已停止 → Send 恢复 |
| provider reasoning 被伪造 | adapter 只透传真实事件；policy 单测（默认过滤 provider_reasoning；开启后切段展示） |
| answer 流为空（生产 bug） | 发现 DeepSeek 走 claims schema 时 delta parser 取不到正文 → 修复 parser 支持 `claims[*].text` + 回归测试 |
| Tool Result 撑爆 DOM/transport | transport 200 items 上限 + UI 默认 20 条 + `显示 20 / 100 条` 显式标记 + transport 截断标志 |
| scope mismatch follow-up | 409 SCOPE_MISMATCH（web 预检）+ Application 层校验 |
| 打开旧 conversation 后改变 Scope selector，Query 仍发送旧 scope | 发送入口比较 selector 可表达字段；不一致时创建新 scope conversation，同 scope follow-up 继续复用 |
| `query.failed/query.aborted` 先关闭 assistant，`stream.end.trace_id` 消失 | 终态信封按 request owner buffer 更新最新 assistant，并更新而非重复追加终态错误块 |
| 非法 trace_id / 路径穿越 | 404 TRACE_NOT_FOUND；URL 编码穿越被路由与 log_path 分隔符校验双重拒绝 |
| 刷新丢历史 | mount 时 load conversations + 最近 conversation；运行中断显式标 `执行中断` |
| 正文中的相似或被模型扩展的 URL 被错误变成外链 | `tests/test_evidence.py`、`web/tests/markdown.test.ts`、`web/tests/AssistantTurn.test.ts` 与真实 Trace `trace-012be0958f9a404eb6c1aea943694e73`；只渲染最终 Source snapshot 中完全一致的 URL |
| Sources 长列表默认撑开正文、多个回答共享展开状态 | `web/tests/SourcesBlock.test.ts` 与真实 Trace `trace-e9e15f4d3d2f499291271f011a18edd4`；每个实例默认 collapsed、展开后保留完整详情 |
| TUI 回归 | test_tui_app/test_tui_projection/test_cli_renderer/test_cli 全绿（472 tests 全量通过） |
