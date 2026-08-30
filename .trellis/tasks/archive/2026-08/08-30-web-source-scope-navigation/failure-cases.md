# Failure Cases: Web Source Scope conversation navigation

> 记录本任务实施与 E2E 期间发现的真实 Failure Case 与根因处置。区分 `real failure`（产品缺陷）、
> `test defect`（测试/脚本自身问题）与 `anticipated risk`（当前不处理，记录触发条件）。

## FC-1（real failure）Draft 转正后 URL 未写入 conversation_id

- **现象**：E2E Case B 中发送第一条消息后，`POST /api/conversations` 成功、streaming 正常，但 URL 无 `conversation_id`；此时刷新会回到 unselected 状态，丢失当前会话定位。
- **根因**：`chat.send()` 只有 stream 结束后触发的 `onFinished` 回调；`writeConversationIdToUrl` 只在 `openConversation` 调用。draft 经 create 转正的时刻（`renameBufferKey` 之后）UI 层无法得知新 ID，违反 PRD R3「当前 Conversation 写入 URL query」。
- **修复（主链路，最小改动）**：`send()` 增加第 4 个可选回调 `onCreated?: (conversationId: string) => void`，在 create 转正后立即触发；`App.vue` handleSend 传入 `writeConversationIdToUrl`。follow-up 复用同一 conversation，不重复触发。
- **回归**：`chatStore.test.ts` 'notifies onCreated with the new conversation id when the draft is promoted'（含 follow-up 不重复触发断言）；E2E Case B 步骤 12/14 与 Case E 恢复验证。

## FC-2（test defect）E2E 会话选择：贺兰群/识海群历史 conversation 为 0

- **现象**：点击 PRD 示例群「贺兰の计算机技术交流群」后 30s 内 sidebar 未出现 date-group。
- **排查**：API 直查确认该群 selector 返回 0 条（57 条单 session conversation 分布在其他 4 个群）。产品行为正确：显示「该范围下还没有 AI 对话记录」empty state。
- **处置**：E2E 改用有历史数据的 `qq:831907794`（25 条）与 `qq:1028505110`（14 条）；同时把「0 条历史」场景确认为 Case A 语义的合法子状态（empty-list 已有组件测试覆盖）。
- **结论**：非产品缺陷；脚本数据假设错误。

## FC-3（documented observation）「全部范围」与「全部群聊」措辞差异

- **现象**：Source Scope 导航项叫「全部范围」，header 只读摘要对 all scope 显示「全部群聊」（`describeScope`）。
- **评估**：两个语境不同——导航是"选择动作"（与"选择一个聊天范围"引导语一致），header 是"当前 buffer 的 immutable scope 描述"（历史 ADR 语义）。E2E 步骤 22 按产品文案断言通过。
- **结论**：有意保留；若未来统一措辞，改 `utils/scope.ts:83` 与 `SourceScopeSidebar.vue:43` 两处即可（单一来源已保证不会分叉出第三种写法）。

## FC-4（test defect，记录备查）E2E 定位器与浏览器上下文两类脚本坑

- `[data-testid^="conversation-"]` 会匹配 `conversation-sidebar` 容器自身，需要 `:not([data-testid="conversation-sidebar"])`。
- `page.waitForFunction` 的 predicate 在浏览器上下文执行，Node 侧闭包变量必须通过 arg 参数显式传入。
- 两者均为脚本问题，产品无缺陷；留档避免后续 E2E 复踩。

## Anticipated risks（当前不处理，含 reconsideration trigger）

- **JSON1 predicate 无索引**：378 行实测无感知；若 `list_summaries` 延迟随 conversation 增长可测量地劣化（如 >10 万行），先 EXPLAIN QUERY PLAN 再考虑 expression index。
- **A→B race guard 只依赖 generation**：当前 selection 变化的唯一入口 `refresh()` 必然递增 generation，条件充分；若未来增加不经过 `refresh()` 的列表写入路径，需同步引入 scope key 校验。
- **多标签页同时打开**：URL query 是每标签页独立的，store 状态不跨标签同步；单用户本机工具当前无此需求，出现真实 Failure Case 再评估 BroadcastChannel 方案。
