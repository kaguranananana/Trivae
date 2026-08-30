# Current State and ChatLab Baseline Research

## Trivae current behavior

- `App.vue:52-72` mount 时请求全局 Conversation + source sessions，并自动打开全局最新 Conversation。
- `conversations.ts:39-78` 对全局最近 100 条按 scope/date 做客户端分组。
- `client.ts:44` 没有发送 scope selector。
- `routes.py:47-50` 只接受 limit；`conversation.py:38-45` 直接调用 Application 全局 list。
- `sqlite.py:117-176` `ORDER BY updated_at DESC ... LIMIT ?`，无 scope filter。
- `scope.ts:9-26` selector 初始为 all，不能表达 navigation-only unselected。
- `chat.ts:157-188` 所有 scope 共用一个 draft key；`chat.ts:316-337` create await 期间存在 scope switch
  覆写同一 draft 的风险。
- `chat.ts` 已正确保留 `request_id → owner buffer`，本任务必须继承，不改成写 current buffer。

## Recent Trivae commits reviewed

- `395af4ad`：UI-neutral thinking visibility、structured Tool Result、graceful abort。
- `60f1dd90`：Conversation rename/delete/preview/process projection。
- `14056732`：Web API、NDJSON stream、scope mismatch、Trace reveal。
- `fbf0b321`：Vue UI、conversation buffer、request owner isolation、date groups。
- `fb9bcdc4`：live process rendering、reactive streams、Tool Result additive merge。
- `ac74b7b5`：provisional answer token streaming / superseded narration。
- `58b99258`：trusted URL 与 Sources collapsed。
- `407d526`（当前分支前序）：canonical scope key、Header scope、全局列表按 scope 分组；仍未解决一级导航与
  server filter-before-limit。

## Real database audit (read-only)

Database: `data/trivae.sqlite3`, 2026-08-30.

| Scope kind | Count |
| --- | ---: |
| all | 243 |
| exact single session | 57 |
| legacy NULL | 78 |
| multi-session | 0 |

Catalog 有 7 个真实 Source Session。单 session snapshot 中有 1 个历史 ID 不在 catalog。结论：primary UI
只需要 all + 7 个真实 session；legacy/unknown 不能伪装为合法导航；multi-session 仍需 exact matcher regression。

## ChatLab current baseline

Inspected repository: `ChatLab/ChatLab`, commit
`f8e482e2a9bd536848eb39a7f99d91692ccf8584` (2026-08-29).

- `src/components/common/Sidebar.vue`：Source Session 一级列表，通过 route params 高亮和切换。
- `src/components/AIChat/chat/ConversationList.vue:30-79`：Conversation list 接收 `sessionId`，watch session
  后调用 `getAIChats(sessionId)`，不是全局列表前端过滤。
- `packages/http-routes/src/routes/web/ai-chats.ts:14-37`：session chats 与 global chats 是明确分开的 API；
  New Chat create 继承 sessionId。
- `src/components/AIChat/ChatExplorer.vue:42-120`：从 `aiChatId` URL query 恢复历史，并同步当前 ID。
- `src/stores/aiChat.ts:401-443`：bind displayed buffer 只切换显示，不影响后台推理 buffer。
- `src/stores/aiChat.ts:646-683`：优先恢复 URL Conversation，否则打开当前 session 最新项；Trivae 选择更清晰的
  scope-switch empty state，不自动打开最近项。

## Baseline validation

- `uv run pytest tests/test_conversation.py tests/test_web_server.py -q` → 19 passed。
- `pnpm test -- --run` → 10 files / 35 tests passed。
- `pnpm typecheck` → passed。
- Agent Reach update check 因 GitHub API rate limit 在 3 次重试后未能确认版本；不影响 GitHub repository audit。
