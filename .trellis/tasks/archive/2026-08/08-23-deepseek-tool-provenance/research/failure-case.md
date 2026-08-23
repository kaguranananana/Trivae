# 真实 DeepSeek Failure Case 证据

## Baseline

- 分支：`codex/m6-trace-observability`
- 业务代码修改前 deterministic 基线：相关 Runtime / Evidence / Trace / Capability 测试 `64 passed`。
- Agents SDK：`0.22.0`。
- 所有 smoke 使用临时 SQLite 和复制的真实 raw 文件；canonical 数据库未写入。

## Failure A：`INVALID_ARGUMENT`

### 真实 Trace 事实

- 模型收到的 `keyword` 是 string；`session_ids`、时间范围、sender/message filters 为 `null`；context window 为非负整数。
- `SearchMessagesInput` 构造成功，因此不是 SDK schema decoding，也不是字段类型校验失败。
- 多次真实调用产生 `limit=20`，另一次产生 `limit=10`；本次 trusted `ExecutionScope.max_results=5`。
- `SearchMessagesCapability` 在进入 Retrieval 前拒绝 `request.limit > scope.max_results`，对应静态错误信息为 `requested limit exceeds trusted max_results`，外层 error code 为 `INVALID_ARGUMENT`。
- 模型收到 Tool Error 后会把 limit 改为 5；改正后的 Tool Call 能进入 Retrieval，说明 SQLite / FTS / Retrieval 基础设施可用。

### 归因

这是 Tool/Capability scope-boundary 的已知错误被模型触发，不是 provider transport、鉴权、SQLite 或 Retrieval 错误。根因是 provider-facing schema 只展示了业务默认 `limit=20`，没有表达本次 trusted scope 的动态上限；模型无法从 `SearchMessagesInput` 静态 schema 得知 `max_results=5`。

## Failure B：`UNRESOLVED_MESSAGE_SOURCE`

### 真实 Trace 事实

一次三次重复 smoke 中，某次 Query 的 Tool Result 关系为：

```text
Tool Call 5: status=ok，但 message_items=0
Tool Call 6: status=partial，message_items=5
```

模型最终提交的一个 `message` source：

- `run_id` 属于当前 run；
- `tool_call_id/tool_result_id` 指向 Tool Call 5；
- `result_item_id/session_id/internal_message_id` 指向 Tool Call 6 返回的其中一条消息；
- 该六元组不属于任何一个 current-run `ToolResultRecord`。

Finalizer 先按 Tool Call 5 找到 record，再找不到该 record 内的 `result_item_id`，返回 `UNRESOLVED_MESSAGE_SOURCE`。这证明不是 expanded message 缺少 provenance：Tool Call 6 的 5 条消息均已进入 current-run provenance 集合。

### 归因

这是模型把两个 Tool Result 的 provenance 字段拼接成一个 locator。当前 M5 Finalizer 的拒绝行为正确，不能放宽为相似匹配或自动选择 Tool Call 6。

同一真实 Query 还观察到一个更早的变体：无 message source 的 Tool Result 仍被模型构造成 `message` source，但缺少 `result_item_id/session_id/internal_message_id`，Finalizer 返回 `INVALID_SOURCE`。该变体同样属于模型没有遵守“只能复制一个完整 message source”的输出约束。

## 当前候选方向

- 对 `limit`：在 provider-facing schema 中加入本次 trusted result 上限和字段说明；Capability contract 继续保留并继续拒绝越界值。
- 对 provenance：让每个 `message_sources` entry 自带完整 current-run locator，并在 prompt 中明确“一个 source 只能复制同一个 entry；`message_sources=[]` 时禁止生成 message source”。
- 不修改 `SearchMessagesInput`、`ExecutionScope`、Finalizer 的校验语义；先不引入 `source_ref`，因为当前证据可以由 provider-facing projection 消除父子 ID 的跨结果拼接。
