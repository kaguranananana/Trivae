# Local Web UI Scope 展示与会话分组：技术设计

## 1. 设计目标与边界

本任务只调整 Local Web UI 的 Scope 投影和 Conversation 导航，不改变后端 contract、SQLite schema 或 Query 执行链。

核心状态关系保持为：

```text
Source Session selector（用户选择下一条合法 scope）
        ↓ 显式 UI action
ConversationBuffer.scope（当前正式会话或 draft 的实际 immutable scope）
        ↓
Header Current Scope + Sidebar active Scope Group
```

正式 Conversation 的 `ConversationBuffer.scope` 是 Header 的权威来源；draft 的 buffer scope 是 draft 的权威来源。selector 只表示用户可选择的 `mode/session_ids`，不能反向改写正式 Conversation。

## 2. ChatLab 基线与 Trivae 差异

ChatLab 的 `ChatExplorer.vue` 由页面 `sessionId/sessionName` 明确绑定单一 Source Session，`ConversationList.vue` 只加载该 session 下的 AI Conversation，并在其内按日期分组；日期组保持展开，当前 Conversation 使用轻量背景强调。`aiChat.ts` 使用 session-keyed state、draft buffer rename 和 request-owner buffer，切换显示不影响后台 stream。

Trivae 继续继承以下交互：

- Header 明示当前数据范围；
- 日期分组常开；
- 当前 Conversation/Scope 使用轻量背景强调；
- draft 首次发送转正、后台 stream owner buffer 与切换显示解耦。

Trivae 必须偏离的部分是：一个 Local Web UI 同时浏览 `all`、单 Session 和多 Session 的 Conversation，因此 Sidebar 在日期分组上增加 Scope Group 第一层。第一版不增加 Scope Group 折叠状态，避免额外 UI 状态与持久化；所有组保持展开，当前组强调。

## 3. Canonical Scope helper

新增前端纯函数模块，统一承担：

1. `sessions` 的 `session_ids` 去重并按稳定字符串顺序排序；
2. 构造集合语义 identity：`all`、`sessions:<sorted ids>`、`unmarked`；
3. 使用 `SessionDTO` catalog 生成 compact label 与完整 tooltip；
4. 比较 selector 可表达的 scope（仅 `mode/session_ids`）。

显示规则固定为：

- `scope=null` → `未标记范围`；
- `mode=all` → `全部群聊`；
- 1 个 session → catalog 名称；
- 2 个 sessions → `A + B`；
- 3 个及以上 → `N 个群聊`，tooltip 仍列出全部解析后名称；
- catalog 中不存在的 ID → 原 session ID。

时间边界与 `max_results` 不参与 Sidebar identity，因为本次 UI 的 Source Scope selector 只表达 `mode/session_ids`，并且用户明确要求按 Source Session set 分类。同 scope follow-up 仍由 chat store 保留并发送后端返回的完整 immutable snapshot。

## 4. Scope store 与显式生命周期协调

`scope.ts` 保持 Source Session catalog 与 selector 的唯一数据源，并增加：

- 从非空 Conversation scope 恢复 selector 的 action；
- 规范化 selector session IDs 的 action；
- 生成当前合法 selector scope 的 action；
- 基于统一 helper 的 label/tooltip 投影。

不使用双向 watch。生命周期由现有 UI 事件显式协调：

- 页面恢复最近 Conversation：`openConversation()` 完成后，把非空 buffer scope 恢复到 selector；
- Sidebar 打开历史 Conversation：同样在完成后恢复 selector；
- 用户切换 mode 或 sessions：先让 scope store 形成合法 scope，再立即调用 `chat.newChat(scope)`，因此 Header 和消息区一起进入对应 draft；
- 点击 New Chat：使用 selector 当前合法 scope 创建/复用 draft；
- 删除当前 Conversation：selector 已与该 Conversation 同步，因此关闭 buffer 后用同一合法 selector scope 创建 draft。

legacy `scope=null` 无法由合法 selector 表达。打开它时不把 selector伪装成 `all`；Header 明确显示“未标记范围”，selector 保留最近合法选择。用户改变 selector 或点击 New Chat 后进入该合法 scope 的 draft。

当用户选择 `sessions` 而尚未选 ID 时，使用 catalog 的第一个真实 Session 形成合法 scope；catalog 为空则保持 `all`。session 多选清空时回到 `all`，不产生 `mode=sessions + empty IDs` 的误导状态。

## 5. Header Current Scope

`App.vue` 增加独立的“当前范围”展示：

- 有 current buffer 时读取 `currentBuffer.scope`，包括保留 `null`；
- 尚无 buffer 的短暂初始化阶段才读取 selector 的合法 scope；
- compact label 直接显示，完整名称写入 `title`；
- selector 文案改为“切换范围”，明确它是导航动作，不是对已打开正式 Conversation 的原地修改。

selector change 立即进入 draft，而不是等到发送时才由 `chat.send()` 纠正。`send()` 现有 scope mismatch 保护继续保留，作为 immutable contract 的主链路校验，而不是 UI 同步的替代品。

## 6. Sidebar projection

`conversations.ts` 使用现有 `ConversationSummaryDTO.scope` 和 scope store 的 `SessionDTO` catalog 计算：

```text
ScopeConversationGroup
  key
  label
  title
  dateGroups[]
    label
    conversations[]
```

构造过程：

1. 按 canonical Scope key 聚合 summary；
2. 在每个 Scope bucket 内按现有“今天 / 昨天 / 更早”规则分组；
3. 保持 API 已给出的 Conversation 更新时间倒序；
4. Scope Group 顺序为 `全部群聊` 在前、session groups 按可读 label/key 稳定排序、`未标记范围` 在后。

`ConversationSidebar.vue` 渲染双层标题，使用 current buffer 的 canonical key 判断当前 Scope Group，而不是 selector 的临时状态。组保持展开；当前组标题使用轻量 primary 背景/文字。Conversation item 的 open、rename、delete、preview 与 active class 保持原事件边界。

## 7. Contract 与兼容性

- `ConversationSummaryDTO.scope`、`ConversationDTO.scope`、`SessionDTO` 已包含全部所需字段；不修改 TypeScript/Python contract。
- 不调用每个 Conversation detail 来分组；只有用户实际打开 Conversation 时沿用现有 detail API。
- 不新增后端 route、数据库字段或 session name 冗余。
- 不触碰 Retrieval、Evidence、Trace、Citation、stream owner routing。
- `scope=null` 仅作为 legacy display category，不被转换为 `all`。

## 8. 风险与回滚

- 风险：selector 同步时丢失后端完整时间/容量 snapshot。控制方式：只同步 selector 可表达字段；正式 follow-up 仍发送 buffer 原 scope。
- 风险：session ID 顺序/重复导致重复分组。控制方式：所有 identity、比较和显示都经过同一 normalization helper。
- 风险：删除当前项或 New Chat 回到 `all`。控制方式：组件生命周期测试锁定 selector 同步后的 draft scope。
- 风险：Sidebar 双层列表破坏 item 操作。控制方式：组件测试覆盖 open/rename/delete，store 测试覆盖 projection。

没有 schema migration；若回滚，恢复前端 helper/store/component 与新增测试即可，后端数据不受影响。

## 9. 验证策略

- 纯函数测试：normalization、identity、label、tooltip、unknown ID、null。
- Pinia store 测试：Scope selector 合法化、conversation Scope/日期双层 projection。
- 组件测试：打开历史 Conversation 后同步 selector、selector change 进入 draft、Header 权威 scope、New Chat 与删除当前项继承 scope、Sidebar active group 与既有操作。
- 全量前端：Vitest、Vue typecheck、ESLint、production build。
- 后端 contract 未变，但运行 Web server/conversation 定向测试确认现有 API 与 immutable scope 回归。

