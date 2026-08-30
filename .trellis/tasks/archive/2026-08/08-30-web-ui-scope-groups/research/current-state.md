# Local Web UI Scope：当前实现与 ChatLab 基线

## Trivae 当前实现

- `App.vue` 在 mounted 时并行加载 Conversation summary 与 Source Session catalog，然后打开最近 Conversation；Header 直接展示 `scopeStore.describe()`，没有把打开后 `ConversationBuffer.scope` 同步回 selector。
- `scope.ts` 只维护 `mode/selectedSessionIds`；`mode=sessions` 且空列表时 `scope()` 静默投影为 `all`，可能让 selector 文案与实际 draft scope 不一致。
- `chat.ts` 已具备正确的 immutable scope 主链路：每个 buffer 保存 `scope`；正式 Conversation 与 selector 的可表达字段不一致时，`send()` 转入 draft；相同 scope follow-up 继续发送 buffer 的后端完整 snapshot。
- `chat.ts` 已具备 ChatLab 风格的 draft rename 和 request owner buffer；本任务不需要改变 stream 路由。
- `conversations.ts` 使用 `/api/conversations?limit=100` 的 summary list，只按“今天 / 昨天 / 更早”投影。
- `ConversationSidebar.vue` 的 New Chat 与删除当前项都从 `scopeStore.scope()` 建 draft；打开历史 Conversation 只调用 `chat.openConversation()`，没有恢复 selector。
- `ConversationSummaryDTO.scope` 与 `ConversationDTO.scope` 都已存在；后端 `project_scope()` 对 legacy scope 返回 `null`，对正式 scope 返回 `mode/session_ids/start/end/max_results`。
- `/api/source-sessions` 已返回 `session_id/name` catalog；不存在后端 grouping 信息缺口。

## 已确认 Failure Case

1. 打开一个 `sessions=[A]` 的历史 Conversation 后，selector 仍可能停留在 `all`；Header 会显示“全部聊天”，但当前消息区实际绑定 A。
2. 用户改变 selector 后，在下一次发送前仍停留在旧 Conversation 消息区；Header 已显示新 selector，视觉上像旧 Conversation scope 被修改。
3. `mode=sessions` 且 IDs 为空时，UI 文案可保持“指定会话”，而 `scope()` 实际返回 `all`。
4. 当前 Sidebar 无法根据已有 summary scope 判断历史 Conversation 属于哪个 Source Session set。

## ChatLab 基线

- `../ChatLab/src/components/AIChat/ChatExplorer.vue` 接收明确的 `sessionId/sessionName`，Conversation 列表与 AI 输入都绑定该页面 Source Session；Source Session 范围由上层页面 Header 明示。
- `../ChatLab/src/components/AIChat/chat/ConversationList.vue` 按日期分组并保持日期组展开；active Conversation 使用轻量背景，整个 Sidebar 可折叠，但分组自身没有额外折叠状态。
- `../ChatLab/src/stores/aiChat.ts` 使用 session-keyed state、draft buffer rename 和 background task owner buffer；`bindDisplayedBuffer()` 只切换显示，不改变后台任务归属。

## 适配结论

Trivae 继承 Header 明示、日期组常开、active 轻量强调、draft rename 和 owner buffer。由于 Trivae 支持 `all`、单 Session 和多 Session，不能照搬 ChatLab 的“一个页面一个 session + 后端按 session 过滤列表”，而应在现有 summary computed projection 中增加 canonical Scope Group。

第一版不增加 Scope Group 折叠或持久化；该复杂度不是正确展示 scope 所必需，ChatLab 也没有对应的 group-level 状态。Header Current Scope 与 selector change 的显式 draft 切换共同解决视觉歧义。
