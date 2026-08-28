# 修复 Web Scope、Coverage 与失败 Trace 恢复：技术设计

## 1. 边界与数据流

本任务只修改两个主链路：

1. Web `scopeStore.scope()` → `chat.send()` → draft/new conversation → `/api/query/stream`。
2. current-run `ToolResultRecord[]` → recent coverage 汇总 → Answer finalization。

Trace Store、Conversation Store schema、HTTP scope validation 和 Retrieval cursor contract 保持不变。

## 2. Scope 修复

`send(query, requestedScope)` 在选定 target buffer 前比较 `requestedScope` 与当前 buffer 的绑定 scope：

- 相同：继续使用当前 buffer，保持 follow-up 语义。
- 不同：调用既有 `ensureDraft(requestedScope)`，让第一次发送通过既有 `createConversation()` 建立新 scope snapshot。

比较只覆盖当前 selector 可表达的 `mode` 与 session IDs；session IDs 按集合语义规范化后比较，避免仅因选择顺序不同创建新对话。conversation DTO 中的 start/end timestamp 与 max_results 是后端投影的完整不可变快照，selector 当前不能编辑这些字段，因此同一选择的 follow-up 继续发送 `buffer.scope` 原值，而不是用省略默认字段的 selector 请求覆盖它。该逻辑不修改旧 conversation，也不依赖后端拒绝后再重试；未来 selector 若开放时间或容量编辑，必须同步扩展比较字段和回归测试。

## 3. Coverage 修复

当前算法把 `observed[-1]` 当最终 coverage，并额外要求调用顺序单调。这个假设不成立：模型可以在同一 window 内发起多个独立 root 查询，每条记录自身仍是有效 Host 事实。

新算法：

1. 继续校验所有记录的 `basis`、`unit`、`eligible_units` 一致。
2. 从有效记录中选择 `covered_units` 最大的记录作为 canonical coverage 状态。
3. `retrieved_count` 继续使用 current-run 唯一 message ID union，保持可复核计数。
4. coverage 相同则使用后出现的记录，不改变正确 continuation 的结果。

这样合法 continuation 的最大 coverage 仍是最后一页；独立小 root 查询不能覆盖此前更强的完整事实。时间窗冲突、eligible units 冲突和单记录内部不一致仍显式失败。

## 4. 失败 Trace 修复

`stream.end` 是权威终态信封。处理它时不能要求 assistant 仍为 `running`，因为 `query.failed/query.aborted` live event 已可能先改变状态。

增加“取 owner buffer 最新 assistant”的小 helper：

- 普通 live event 仍只写入 running assistant。
- `stream.end` 写入最新 assistant，并统一覆盖终态字段；已有 live terminal error 时更新同一错误块，
  避免 failed 重复显示，同时让 aborted 的终态错误字段不丢失。

当前 store 使用 request owner buffer 且全局 busy 阻止同一时刻再次发送，因此最新 assistant 就是该 request 的 assistant；不新增 assistant/request 映射或兼容分支。

## 5. 兼容性与风险

- Scope：行为变化仅发生在 selector scope 与 conversation scope 不一致时；同 scope follow-up 不变。
- Coverage：删除错误的顺序假设，不放松单条 record、scope、time-range 或 eligible-units 校验。
- Trace：只修复已存在 `stream.end.trace_id` 的 UI 关联；没有 Trace ID 时仍不展示。
- 不做数据库迁移，回滚只需恢复相关 store/evidence 逻辑及新增测试。

## 6. 验证策略

- 前端 store 单测覆盖 scope mismatch/new conversation、same-scope follow-up、failed/aborted event →
  stream.end Trace 与终态错误。
- 后端 temporal coverage 单测覆盖真实 Failure Case 形状与合法 continuation 回归。
- 运行定向测试后执行 Web 全量 test/typecheck/lint 与相关 Python 回归。
