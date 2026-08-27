# Fix temporal overview coverage and time-range consistency

## Goal

修复 `get_recent_messages` 在 broad temporal browsing 中只返回 100 条消息、却被模型用于概括整个时间窗口的问题；同时让相对时间窗口从解析到最终回答始终使用同一份 Host-owned canonical 时间事实。

## Requirements

- 为 temporal browsing 建立独立于通用 structured、lexical、semantic 和 Tool Result token budget 的消息容量：默认 1000，硬上限 5000；实际值仍受 trusted scope 的 `max_results` 限制。
- 支持有界、稳定的 continuation：按 canonical ordering 使用 keyset cursor 读取更早批次；cursor 必须保持原 session/time scope，不能扩大 trusted scope；相同 timestamp 的消息不得重复或遗漏。
- 每次 recent retrieval 都明确表达 `total_hits`、当前 `returned_count/retrieved_count`、`coverage`、`truncated`、是否还有下一批和 `next_cursor`；不能把截断结果标成 complete。
- 保留现有独立 Tool Result token projection。数据库 canonical retrieval 容量和模型可见 projection 容量必须分别记录；projection 省略消息时显式记录 `projected_count`、`omitted_messages` 及 budget truncation。
- relative `time_range` 只能由 Host 根据 scoped `archive_latest` 解析；Tool Result、Trace、Evidence 和最终 Answer Artifact 必须携带同一 resolved half-open UTC window。模型不得根据毫秒值自行换算时间。
- partial/截断 retrieval 不得支持无条件的完整概览或 complete zero-result 结论；最终 Artifact 必须保留机器可读 coverage/time-range 和执行限制。
- 空窗口继续是合法的 complete zero-result outcome；不得破坏既有 positive-proof no-result contract。

## Acceptance Criteria

- [x] 默认 recent limit 不再是 100，且 `get_recent_messages` 不复用通用 structured limit 常量。
- [x] 1000、5000 及超限输入分别得到正确的 bounded 行为；semantic/structured/lexical 上限不被改动。
- [x] 大窗口可用 cursor 完成多批读取；多批 union 无 overlap、无 gap，same-timestamp ordering deterministic，cursor 不能越过 trusted session/time scope。
- [x] 2699 条真实窗口不再只读取最后 100 条；单批/多批的 total、retrieved、projected、coverage、truncated 和 latency 可在 Trace 中复核。
- [x] 低密度和空窗口 coverage 为 complete；高密度未遍历完时为 partial，且最终回答可见 limitation。
- [x] resolved window 的毫秒、UTC 文本、citation canonical timestamp 和最终 Artifact metadata 一致；不再出现 Trace 中的六月/八月错配。
- [x] recent、structured、lexical、semantic、SQL、context、evidence、no-result、runtime、Trace、CLI/TUI/Web 回归通过。
- [x] 完成真实数据库 Case A-E 和 100/1000/5000 性能 smoke，并记录结果。

## Notes

- 真实 Failure Case：窗口 `2026-08-14T02:34:48Z` 至 `2026-08-16T02:34:48.001Z`，`total_hits=2699`，旧实现 `returned=100`。
- ChatLab 当前基线实际区分 schema default、运行时 `maxMessagesLimit` 和 Tool Result token/preprocessing budget；Trivae 只借鉴边界分层，不复制其实现。
