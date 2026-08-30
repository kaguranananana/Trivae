# Local Web UI Scope 展示与会话分组

## Goal

让用户在 Local Web UI 中始终能明确识别当前 AI Conversation 实际绑定的 Source Session 范围，并在左侧按不可变 Scope 快照查找历史 Conversation，消除 selector 临时状态与当前 Conversation 实际范围之间的歧义。

## Background

- Source Session（微信群/私聊）与 AI Conversation 是两个不同概念；Source Session 决定 Retrieval 的 `ExecutionScope`。
- AI Conversation 的 scope 是不可变快照，切换 Scope 不得修改已有 Conversation。
- `ConversationSummaryDTO.scope` 已提供 Sidebar 分类所需数据，应复用现有 API contract 与 Source Session catalog。
- 当前 Header 展示的是 `scopeStore` selector 状态；打开历史 Conversation 后没有显式同步 selector，可能与 `ConversationBuffer.scope` 不一致。
- 当前 Sidebar 仅按日期分组，尚未按 Source Session Scope 分类。
- ChatLab 的 AI Conversation 列表由单个页面 Source Session 约束，日期分组保持展开，当前 Conversation 以轻量背景强调；Trivae 因支持 `all` 与多 Session scope，需要在其日期层上增加 Scope Group。

## Requirements

### R1 当前 Scope 明确展示

- Header 必须展示“当前范围”，数据源为当前实际工作的 scope：正式 Conversation 使用当前 `ConversationBuffer.scope`，draft 使用 draft scope。
- 单个 Source Session 显示真实群聊名称；多个显示名称组合，数量较多时可显示“`N 个群聊`”，并通过 `title`/tooltip 保留完整名称。
- `mode=all` 显示“全部群聊”；`scope=null` 显示“未标记范围”，不得误报为全部群聊。
- 打开历史 Conversation 后，selector 应恢复到该 Conversation 的不可变 scope，避免视觉歧义。
- 用户切换到另一个合法 scope 时，应进入该 scope 的 draft/new Conversation，不得修改当前正式 Conversation 的 scope。
- 状态同步不得依赖容易形成循环的双向 watch。

### R2 Conversation 按 Scope 与日期分组

- Sidebar 分组层级调整为 `Scope Group → Date Group → Conversation`，保留“今天 / 昨天 / 更早”日期分组。
- Scope identity 必须基于 canonical scope，而不是群名称：`all` 单独成组；`sessions` 对 `session_ids` 去重、排序后按稳定集合语义构造 key。
- session ID 顺序不同但集合相同的 Conversation 必须进入同一分组。
- Scope label 使用现有 `/api/source-sessions` 返回的 `SessionDTO` catalog 解析。
- 未知历史 session ID 不得导致渲染失败；以原 session ID 作为有界回退，不伪造名称。
- legacy `scope=null` 必须单独归入“未标记范围”。
- Scope Group 与日期组保持展开，不新增折叠状态或持久化；当前正在使用的 Scope Group 使用轻量视觉强调。

### R3 保持现有 Conversation 交互

- 分类不得破坏 open、rename、delete、active highlighting、preview、background stream owner buffer、draft、refresh。
- 删除当前 Conversation 后创建的新 draft 必须继承当前合法 Scope。
- `+ New Chat` 必须使用 Header 当前展示、用户当前选定的合法 Source Scope；打开历史 Conversation 后其语义必须与 Header 一致，不能意外回到 `all`。

### R4 架构边界

- 不建立第二套 conversation/session 数据源，前端不直接访问 SQLite。
- 不修改现有 Retrieval、Evidence、Trace、Citation 执行链。
- 优先在 Pinia computed projection 中使用 `ConversationSummaryDTO.scope` 完成分组。
- 不新增 Sidebar grouping 后端 endpoint、SQLite 表、Conversation Store 冗余 session name、逐 Conversation detail 请求，也不从消息内容推断 scope。
- 除非代码证据证明 canonical 信息缺失，否则不扩展后端能力。

## Acceptance Criteria

- [ ] AC1 打开正式 Conversation 时，Header“当前范围”严格来自该 Conversation 的 immutable scope，并以可读群名称展示。
- [ ] AC2 draft 的 Header“当前范围”严格来自 draft scope；selector 切换会进入相应 scope 的 draft，而不会修改已有正式 Conversation。
- [ ] AC3 `all`、单 session、多 session、较多 sessions、未知 session ID 与 `scope=null` 均有稳定且不误导的显示。
- [ ] AC4 Sidebar 以 canonical Scope Group 为第一层、日期为第二层；session ID 顺序变化或重复不产生重复 Scope Group。
- [ ] AC5 Scope Group 与日期组保持展开，当前 Scope Group 有轻量强调；Conversation active highlighting 与各项既有操作保持正常。
- [ ] AC6 从历史 Conversation 点击 `+ New Chat`，新 draft 继承 Header 当前展示的合法 Scope；删除当前 Conversation 后同样保持该 Scope。
- [ ] AC7 实现复用现有 conversation summary 与 source-session catalog，不增加后端 grouping API、数据库结构或逐项 detail 查询。
- [ ] AC8 相关单元/组件测试覆盖 scope normalization、label、分组、selector 同步、New Chat 与 delete-current 生命周期，现有测试继续通过。

## Out of Scope

- 修改 Retrieval、Evidence、Trace、Citation 的执行语义或协议。
- 修改 Conversation scope 的后端不可变契约。
- 新增后端 Sidebar grouping endpoint 或持久化模型。
- 复杂折叠动画、全新 Sidebar 信息架构或从消息内容猜测 scope。
- Scope Group 折叠状态及其跨刷新持久化。
