# Temporal overview coverage：技术设计

## 1. 根因与证据

旧链路把 `DEFAULT_RECENT_MESSAGES_LIMIT` 和 `MAX_RECENT_MESSAGES_LIMIT` 直接绑定到通用 structured 的 100。这个 100 是 Retrieval/Capability 的行数 hard cap，不是 Tool Result token budget，也不是 provider model context 上限。SQLite 只执行一次 latest-limit 查询，没有 cursor、offset、before_timestamp、时间分桶或自动 continuation；`total_hits=2699` 只作为 metadata 返回，Agent 没有可靠的下一批协议。

旧的 `StructuredRetrieval.retrieve_recent_messages` 在 `total_hits > len(messages)` 时仍生成 `coverage=complete`、`partial=False`，只把 `truncated=True` 单独放在结果中，因而把尾部样本误当成完整窗口。

真实 Trace `trace-3ca9975108534180b73ce7f518d7c1c4` 已证明 Tool Result projection 不是根因：数据库检索返回 100 条，模型投影估算约 9185 tokens，budget `truncated=False` 且没有省略消息。Trace 中的绝对边界实际上是 UTC 2026-08-14 至 2026-08-16；最终答案写成六月，是因为模型只收到原始毫秒和受深度限制的诊断投影，而 finalizer 只验证 provenance/scope，不验证自然语言中的日期。

## 2. ChatLab 基线核验

当前 ChatLab 代码的分层是：

- `recent-messages` schema 的 default 为 100；handler 用 `resolveMessageLimit` 结合运行时 `maxMessagesLimit` 执行并封顶。
- CLI/Runtime context 单独传递 `maxMessagesLimit`；event handler 对 recent/search/conversation 的 limit 做运行时归一化。
- Tool adapter 另有 `DEFAULT_MAX_TOOL_RESULT_TOKENS=8000`，再通过 preprocessing/truncation strategy（recent 为 `keep_last`）控制模型可见结果。
- 全局设置 `maxMessagesPerRequest` 默认约 1000，UI 允许更高。

因此 ChatLab 的关键经验是“消息数量上限”和“模型结果 token 上限”分离。Trivae 保留自己的 dynamic Tool Result budget（未知 context 时 16000 fallback、已知 context 按配置动态计算），只把 recent retrieval 容量独立提高，并不把所有消息无条件塞进模型。

## 3. 结果与 continuation contract

新增 `RecentMessagesQuery`，不放宽通用 `MessageQuery` 的 100 上限。recent query 默认 1000、最大 5000，且仍受 trusted `max_results` 硬约束；超限时显式报错，不静默裁剪。

cursor 使用 canonical ordering 的 keyset 边界：

`(timestamp ASC, present-seq ASC, missing-seq after present-seq, seq ASC, internal_message_id ASC)`。

返回批次按阅读顺序升序排列；`next_cursor` 指向当前批次最早消息，下一次只读取该 cursor 之前的 rows。cursor 同时携带已解析的 `start_timestamp/end_timestamp` 和 session filter，后续请求缺省时继承它；Capability 会再次检查它们是否落在 trusted scope 内。SQL 使用严格小于的复合排序键，不使用 offset，因此同 timestamp、NULL seq 和新消息插入都不会造成页内重复。

每批事实：

- `total_hits`：不带 cursor 的完整 requested window count。
- `returned_count` / `retrieved_count`：本批实际从 canonical store 读取的消息数。
- `has_more`、`next_cursor`：是否仍有更早批次。
- `coverage.status`：仍有下一批时为 `partial`，没有下一批时为 `complete`；`covered_units/eligible_units/unit` 提供可计算的数量关系。
- `truncated` 与 `partial`：都由真实的 remaining rows 决定，不再把 latest-limit 截断误报为 complete。

Agent instructions 要求：首次 broad overview 使用约 1000 条；看到 `has_more=true` 或 `coverage=partial` 时原样传回 `next_cursor` 继续，保持相同 window/session；直到 `has_more=false`，或 runtime/tool budget 终止并明确声明 partial。不能用相同 cursor 重复调用，也不能把 cursor 自己改成另一个 scope。

## 4. Host / projection / evidence / answer

`ResolvedTimeRange.to_dict()` 增加由 Host 统一生成的 UTC ISO 文本和 half-open interval，同时继续保留 canonical integer milliseconds。recent envelope meta、retrieval Trace payload、model-visible data 和 record query snapshot 都保存该对象。

Tool Result projection 不改 canonical record，不把 5000 条正文复制到 Trace；它只在独立 token budget 内投影 slim message entries，并公开：

- canonical `retrieved_count`；
- model-visible `projected_count`；
- `omitted_messages`，以及原有 context/hit omission；
- `model_projection.truncated`。

最终 Answer Artifact 增加 Host-owned `resolved_time_range` 与 `retrieval_coverage`，从 current-run recent records 派生并验证所有批次边界一致；同时自动保留 retrieval partial/truncated/coverage limitation。CLI/TUI/Web 和 conversation codec 展示/持久化这个 canonical metadata。citation 时间仍只从 canonical `MessageProjection` hydrate，绝不采纳模型生成的日期。

## 5. 不做的事情

- 不修改通用 structured、semantic、lexical、SQL 行数边界。
- 不取消或放宽 Tool Result token budget。
- 不引入 offset、复杂时间桶、跨 run 的分页状态或模型自算时间。
- 不对自然语言正文写针对六月/八月的替换规则；canonical window 由 Host metadata 和 UI/Artifact contract 提供，模型只负责引用它。

## 6. 可观测性与失败归因

每个 `structured.browse.completed` 记录 query window、当前 batch cursor、total/returned/covered、has_more、next_cursor、coverage 和 latency；runtime terminal 记录各 Tool Result projection 的 projected/omitted 总量。非法 cursor、越权 session/time、复合排序键不匹配都显式返回 contract/retrieval error，不静默回退到第一页。
