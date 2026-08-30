# Implementation and Validation Record

## 1. Problem / Root Cause

- `real failure`：Header 原先直接展示 `scopeStore` selector，打开历史 Conversation 时 `chat.openConversation()` 没有恢复 selector；因此 Header 可能显示 `all`，当前 buffer 实际却绑定单一 Source Session。
- `real failure`：selector 变化只在下一次 `chat.send()` 时触发 immutable-scope mismatch 保护。发送前 Header 已变化、消息区仍显示旧 Conversation，形成“旧 Conversation scope 被原地修改”的视觉歧义。
- `real failure`：Sidebar 只按日期投影，虽然 summary 已包含 `scope`，用户仍无法按 Source Session set 查找历史 Conversation。
- `real failure`：初版组件把多选 selector 的 `select.value` 直接绑定为 Session ID 数组；原生 select value 只能表达单项，打开双群/多群历史 Conversation 时只恢复了一个可见选项。
- Root Cause 位于前端状态权威来源和显式 UI 生命周期，不是 backend contract、SQLite 或 Retrieval 执行链缺少数据。

## 2. Implementation / Design Rationale

- 新增统一 scope helper，集中负责 session ID 去重/稳定排序、canonical key、selector 可表达字段比较、compact label 与完整 tooltip。chat、scope、conversations 三个 store 不再各自维护集合语义。
- Header 当前范围直接读取 `ConversationBuffer.scope`；只有尚无 buffer 的初始化阶段才读取合法 selector scope。`scope=null` 保持“未标记范围”，不伪装成 `all`。
- 打开正式 Conversation 后由 App/Sidebar action 显式恢复 selector；selector mode/session change 立即创建或复用相应 draft。没有双向 watch，也没有改变正式 Conversation 的完整 scope 快照。
- 多选 selector 使用带 setter 的 computed `v-model`：getter 投影完整规范化集合，setter 统一调用 `selectSessions()` 后进入对应 draft，避免组件另建数组同步语义。
- Sidebar 在已有 summary computed projection 内完成 `Scope Group → Date Group`，并用现有 Session catalog 解析名称。没有 grouping endpoint、detail N+1 请求或冗余 session name。
- `Why not`：没有修改 backend immutable scope contract，因为现有 DTO 已提供完整输入；没有从消息内容推断 scope；没有新增折叠状态，因为本任务只需要明确分类和当前范围。

## 3. Failure Cases and Regression Coverage

- `regression test case`：`null`、`all`、单 session、双 session、三个 session、未知 ID 分别验证 label/tooltip，确保 legacy null 不误报。
- `regression test case`：重复和乱序 session IDs 产生同一 key，并继续让 chat same-scope follow-up 使用正式 buffer 的完整时间/容量快照。
- `regression test case`：conversations store 验证 `all → sessions → unmarked` 稳定 Scope 顺序及“今天/昨天/更早”第二层顺序。
- `regression test case`：App 验证历史打开后 Header 与 selector 同步；selector change 立即进入 draft，旧 buffer scope 不变。
- `regression test case`：App 额外验证双 Session 历史 scope 会同时恢复两个可见选项，并覆盖从单 Session 追加选择后立即进入多 Session draft。
- `regression test case`：Sidebar 验证 active Scope Group、open、New Chat、rename、delete-current，并确认新 draft 继承同步后的合法 scope。

## 4. Evaluation / Evidence

| Command | Measured result |
| --- | --- |
| `pnpm exec vitest run tests/scope.test.ts tests/scopeStore.test.ts tests/conversationsStore.test.ts tests/App.test.ts tests/ConversationSidebar.test.ts tests/chatStore.test.ts` | 6 files / 19 tests passed |
| `pnpm test` | 10 files / 35 tests passed |
| `pnpm typecheck` | passed |
| `pnpm lint` | passed |
| `pnpm build` | passed；Vite transformed 124 modules |
| `uv run pytest tests/test_web_server.py tests/test_web_streaming_contract.py -q` | 27 passed |
| `git diff --check` | passed |
| `python3 ./.trellis/scripts/task.py validate web-ui-scope-groups` | passed；implement/check manifests 各 3 entries |

以上均为本分支实际命令结果。production build 证明新增 Vue template/Tailwind class 可编译；Python 定向回归证明 conversation/Web streaming contract 未被前端调整破坏。

## 5. Observability / Ownership / Scale

- UI scope 偏差可直接由 Header 当前范围、selector 和 Sidebar 当前组对照定位；identity/label 是纯函数，可用输入 scope 与 catalog 独立复现。
- Ownership 保持：backend Conversation 保存 immutable scope；chat buffer 保存当前实际 scope；scope store 只拥有合法 selector 与 catalog；conversations store 只做 summary projection；组件只协调明确用户事件。
- `measured fact`：当前列表 API 上限是 100，projection 只遍历 summary 并在每组内分日期；未增加 HTTP 请求。
- `engineering expectation`：若未来列表改为大规模分页，应在已有 summary 分页边界上重新评估跨页 group 顺序；当前没有真实 Failure Case 支持新增 backend grouping 或持久化索引。
- 没有新增 retry、fallback、降级、兼容分支或静默吞错；rename 请求失败会显式交给 Vue error handler并保持编辑态。

## 6. Evolution / Interview Defense Notes

- 事实索引：scope helper 单测证明 identity/display；store 测试证明 projection；组件测试证明显式生命周期；Web ADR 记录 Source Session 与 AI Conversation 的 ownership。
- `currently unnecessary / waiting for failure evidence`：Scope Group 折叠持久化、backend grouping endpoint、按 session 名称搜索和大列表虚拟化。只有真实使用量或性能证据表明 computed projection/常开列表不足时再重开。
- `permanently rejected`：把 selector 当正式 Conversation scope 权威来源、从消息正文猜 scope、把 legacy null 当 all；这些方案直接违反 immutable scope 与错误透明契约。

## 7. Independent Check

最终全范围 `trellis-check` 已完成。检查器发现并修复原生多选 selector 无法完整恢复多 Session
DOM 选中状态的根因，补充 App 组件回归后重新运行全部门禁；未发现设计级问题、范围外改动或遗留 finding。
最终提交、任务归档由主会话继续执行。
