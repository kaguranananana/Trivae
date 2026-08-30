# Optimize Web Source Scope conversation navigation

## Goal

把 Trivae Web 的主导航调整为 `Source Scope → AI Conversation → Turns`，让用户只有在选择合法
Source Scope 后才看到、创建和继续该范围的 AI Conversation；列表数据必须由后端在 scope 过滤后再排序、
limit，不能依赖前端对全局最近 100 条做过滤。

## Background

- Source Session（微信群 / 私聊）决定 Retrieval 的 ExecutionScope；AI Conversation 保存多轮
  User / Assistant Turns。两者是不同领域概念。
- Conversation 创建后保存 immutable scope snapshot；切换导航不能修改已有 Conversation 的 scope。
- 当前 `App.vue:52-72` 在 mount 时并行加载全局 Conversation 列表，并自动打开全局最新一条。
- 当前 `conversations.ts:39-78` 先读取全部最近 Conversation，再在 Pinia 内按 scope 分组；
  `client.ts:44` 请求 `/api/conversations?limit=100`。
- 当前 `sqlite.py:117-176` 直接 `ORDER BY ... LIMIT ?`，没有 scope predicate；因此前端过滤会漏掉排在
  全局 limit 之后、但属于当前 scope 的历史。
- 真实 `data/trivae.sqlite3` 在 2026-08-30 的只读审计结果：378 个 Conversation，其中 `all=243`、
  单 session=57、legacy `scope=NULL`=78、multi-session=0；单 session 历史中有 1 个 ID 已不在当前
  Source Session catalog。
- ChatLab 当前主分支 `f8e482e2a9bd536848eb39a7f99d91692ccf8584` 使用一级 Source Session Sidebar，
  `ConversationList` 接收 `sessionId`，服务端 `getAIChats(sessionId)` 返回该 session 的列表，New Chat
  调用 `createAIChat(sessionId, ...)`；`aiChatId` URL query 恢复历史，Store 的 session-scoped buffer
  让显示切换不改变后台任务 owner。

## Requirements

### R1. 一级 Source Scope 导航

- 左侧新增独立 Source Scope 区域，数据只来自 `GET /api/source-sessions`。
- 显示“全部范围”和每个真实 Source Session，并明确高亮当前选择。
- 初始 `selectedSourceScope=null`；它只是 Web navigation state，不进入后端 ExecutionScope contract。
- Header 不再保留第二套可写 selector，只显示当前 Scope 的只读摘要。

### R2. Scope-scoped Conversation 列表

- 未选择 Scope 时不请求、不展示 Conversation，显示“选择一个聊天范围以查看 AI 对话”。
- 选择 `all` 只展示创建时 `scope.mode=all` 的 Conversation。
- 选择 session A 只展示 scope identity 精确为单 session A 的 Conversation。
- `sessions:[A,B]` 不得归入 A 或 B；legacy `scope=null` 不得归入 `all`；未知历史 session ID
  不得伪装成当前真实 Source Session。
- 保留 today / yesterday / earlier、current highlight、preview、rename、delete、open/resume。

### R3. Scope navigation lifecycle

- A → B 时列表立即清空并加载 B，主区域进入 B 的空状态，不自动打开 B 最近 Conversation。
- New Chat 只有已选择合法 Scope 时可用，并把当前 navigation selection 编译为 ScopeRequest。
- unselected 时 New Chat 与 Composer 禁用；Store send 也必须拒绝执行，禁止 fallback 到 `all`。
- 打开列表或 URL 指向的 Conversation 时，navigation selection 根据 immutable scope 恢复；`all` 与
  已存在的单 session 可恢复为主导航高亮。
- 直接打开 legacy null、multi-session 或未知 session 历史时保持只读兼容：内容可回放，但不映射为
  合法 primary navigation scope，Composer 禁用，不修改历史 scope。
- 当前 Conversation 写入 URL query；reload 先读取 detail、恢复合法 Scope，再读取对应列表。

### R4. Backend filter-before-limit contract

- 正式 API 使用 bounded selector：
  - `GET /api/conversations?scope_mode=all&limit=100`
  - `GET /api/conversations?scope_mode=sessions&session_id=<id>&limit=100`
- selector 缺失、组合非法或 mode 非法返回稳定错误信封；不存在的 session 返回稳定错误信封。
- Web query params 不能穿透 start/end/max_results 等 ExecutionScope 字段。
- Application / Conversation Store 接收正式 scope identity selector；SQLite `WHERE` 精确匹配
  `allowed_session_ids` 后，仍按 `updated_at DESC, conversation_id ASC` 排序，最后才 `LIMIT`。
- 不新增数据源或第二套 Conversation / Retrieval 系统。

### R5. Buffer 与 streaming invariants

- `request_id → owner buffer` 仍是唯一 stream 写入路径。
- draft 按 scope identity 隔离，避免 A draft 在 Conversation create await 期间被 B 导航覆写 scope。
- 切换 Source Scope 只改变 displayed buffer；A 的后台 stream 继续写 A buffer，不能出现在 B。
- Stop、Router / Plan / Thinking / Tool / Retrieval / Answer、structured Tool Result、Sources collapsed、
  trusted URL、Trace Finder 与 history replay 不回归。

### R6. 文档与证据

- 更新 `web-primary-interface.md`，记录 primary Source Scope navigation、filter-before-limit、
  unselected state、精确 identity 与兼容边界。
- 任务目录补齐 Design、Implementation、Validation、Failure Cases 与实际浏览器证据。

## Out of Scope

- 不把 multi-session selection 做成 primary UI 多选器。
- 不修改 ExecutionScope 的时间、容量或 Retrieval 语义。
- 不迁移或重写历史 Conversation scope snapshot。
- 不改变 CLI / TUI 的入口、交互或 query contract。
- 不复制 Source Session catalog，不引入新的前端持久化数据库或后端 Conversation 表。
- 不机械复刻 ChatLab 视觉细节、全局 AI taxonomy、assistant/skill 系统或其他非本任务功能。

## Acceptance Criteria

- [ ] 首次打开且 URL 无 Conversation 时，Source Scope 未选择、Conversation 列表为空、主区与 Composer
      明确要求先选择范围。
- [ ] 选择 `all` 后只发出 `scope_mode=all` 请求，只显示 all scope Conversation。
- [ ] 选择 session A 后只发出该 A 的 selector 请求，只显示精确单 session A Conversation。
- [ ] A → B 立即清掉 A 列表与主区；延迟到达的 A response 不能覆盖 B。
- [ ] all / A / B 的 Conversation 彼此隔离，rename/delete/new/open 仍正常。
- [ ] New Chat 在 all 与 session A 下分别创建正确 ScopeRequest；unselected 不产生 create/query 请求。
- [ ] Conversation URL/reload 恢复合法 Source Scope 与历史 Answer / Process / Sources / Trace。
- [ ] legacy null、未知 session、`sessions:[A,B]` 不被错误归入 all 或单 session。
- [ ] Backend 单元/API 测试证明 scope filter 先于 limit，非法 selector 与不存在 session 错误稳定。
- [ ] Frontend store/component 测试覆盖初始、all、session、A→B、New Chat、历史恢复、stream owner isolation、
      today/yesterday/earlier、rename/delete 与 disabled state。
- [ ] 真实 `trivae web` + `data/trivae.sqlite3` 浏览器 E2E 完成用户要求 Case A-F；发现的主链路问题修复并回归。
- [ ] Python tests、frontend test/lint/typecheck/build、CLI/TUI 回归均通过，ADR/Validation/Failure Cases 完整。
- [ ] 产出工作 commit 与 Trellis 收尾 commit，并报告最终 commit SHA。
