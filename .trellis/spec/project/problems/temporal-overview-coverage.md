# Temporal overview coverage and time-range consistency

## Problem

`get_recent_messages` 服务 broad temporal browsing（例如“最近两天聊了什么”），但旧实现把
通用 structured 的 `100` 行 hard cap 当成 recent 的容量。真实窗口有 `2699` 条消息时，Tool
只返回最后 `100` 条，最终答案却没有声明只覆盖尾部样本。同时，Host 的毫秒窗口对应 UTC
2026-08-14 至 2026-08-16，回答文本出现 2026-06-13 至 2026-06-15，时间事实没有跨层锁定。

## Evidence

- Trace：`trace-3ca9975108534180b73ce7f518d7c1c4`。
- 旧 Trace：`total_hits=2699`、`returned=100`、Tool Result token projection 未超预算；根因在
  canonical retrieval cap，不是模型 projection。
- 旧边界 `[1786674888000,1786847688001)` 的 UTC 含义为
  `[2026-08-14T02:34:48.000Z, 2026-08-16T02:34:48.001Z)`；旧回答月份与引用消息时间不一致。
- 当前 canonical DB：`473236` 条消息，archive latest `1786847688000`，两天窗口 `2699` 条。

## Root Cause

1. `DEFAULT_RECENT_MESSAGES_LIMIT` / `MAX_RECENT_MESSAGES_LIMIT` 直接复用了 structured `100`，
   broad temporal browsing 没有独立 capacity。
2. Retrieval 只有一次 latest-limit 查询；`total_hits` 是诊断字段，没有 cursor/continuation
   协议，Agent 无法读取剩余窗口。
3. `total_hits > returned_count` 时旧结果仍为 `coverage=complete`，把 page sample 当成完整 scope。
4. Tool/Trace 传播了原始毫秒，但没有要求模型只复制 Host UTC 文本；finalization 校验 citation
   provenance，却没有保存/校验统一的 resolved range。

## Options

- 仅把 recent hard cap 提到 5000：不能处理超过模型 Tool Result budget 的正文，也不能让 2699
  条在默认 1000 下完整遍历，因此不足。
- 使用 offset/time bucket：offset 在新消息和 same-timestamp 边界下不稳定；时间桶会新增跨桶边界
  与状态管理，当前 Failure Case 没有证明其必要性。
- 选择独立 recent capacity + keyset cursor + 独立 model projection：满足 recall、稳定继续和
  预算分层，且复用现有 Structured Retrieval/Tool/Evidence 主链路。

## Decision

- recent default `1000`、hard cap `5000`；structured default/max 保持 `100`，lexical/semantic
  和 Tool Result token budget 保持各自 contract。
- cursor 使用 `(timestamp, present-seq, missing-seq, seq, internal_message_id)` 的严格 keyset
  边界，携带原始 session/time scope 和 Host-resolved range；继续请求不能改 scope、改窗口或
  重新锚定 `archive_latest`。
- 每页表达 `total_hits`、`returned_count/retrieved_count`、`coverage`、`partial`、`truncated`、
  `has_more`、`next_cursor`；Agent 继续到 `has_more=false`，否则最终答案必须保留 partial limitation。
- `AnswerArtifact` 保存 Host-owned `resolved_time_range` 与 `retrieval_coverage`；
  `TIME_RANGE_MISMATCH` / `COVERAGE_MISMATCH` 是可信边界失败，不走局部 recovery。

## Why

该方案只增加 broad temporal browsing 缺失的能力，不放宽其他 Retrieval contract，不把几千条
正文强行复制进模型，也不引入没有 Failure Case 支撑的 offset、bucket、retry 或 fallback。
keyset 使用现有 canonical ordering，Continuation 的 identity 和 scope 可在 Capability/SQLite
边界确定性校验；Host metadata 使日期和 coverage 不再依赖模型心算。

## Result

修复后真实 DB 验证：

| Case | Window / scope | total | returned | coverage | projection | range |
| --- | --- | ---: | ---: | --- | ---: | --- |
| A | 默认 relative 2 day | 2699 | 1000 | partial | 164 | Host archive latest |
| B | relative 1 day | 911 | 911 | complete | 170 | Host archive latest |
| C | 两天高密度 continuation | 2699 | 1000/1000/699 | partial/partial/complete | 165/160/169 | 同一 absolute window |
| D | 低密度一小时 | 1 | 1 | complete | 1 | explicit absolute |
| E | future empty window | 0 | 0 | complete | 0 | explicit absolute |

Case C 三页 union 为 `2699`，overlap 为 `0`。两天窗口的 Host range 为
`[2026-08-14T02:34:48.000Z, 2026-08-16T02:34:48.001Z)`；所有 citation canonical timestamp
均按 `[start,end)` 校验。

稳定性能样本（同一只只读连接预热后，当前本地数据库）：

| limit | retrieve median | record median | projection median | retrieved/projected | model omitted | Trace result payload |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 28.51 ms | 0.15 ms | 2.07 ms | 100/100 | 0 | 1143 B |
| 1000 | 33.56 ms | 1.57 ms | 125.20 ms | 1000/165 | 835 | 1146 B |
| 5000 | 39.43 ms | 4.71 ms | 513.51 ms | 2699/175 | 2524 | 663 B |

独立 tracemalloc 诊断峰值约为 `0.44/4.08/11.39 MB`（100/1000/5000）；启用 tracing 会影响
耗时，因此不把该次 tracing 的 latency 当作生产性能结论。`16000` token projection budget
保持有效，Trace payload 未复制完整消息正文。

## Trade-off

- 1000/5000 提高 canonical read 和 Tool Result record 的内存占用；当前真实测量在 5000 请求、
  实际 2699 条下约 11.39 MB traced peak，且 projection/Trace 仍 bounded。
- keyset cursor 的外部 payload 比单个 limit 参数复杂；换取页间 deterministic ordering 和 scope
  不漂移。
- `AnswerArtifact` 增加跨层 metadata 与 codec 字段；换取历史 replay 可以知道答案是 complete
  还是 partial，而不是依赖旧 Tool Result。

## Regression

- `tests/test_temporal_overview_coverage.py` 覆盖 capacity、structured independence、large/low/
  empty coverage、cursor overlap/gap/same-timestamp/scope tampering、archive_latest、UTC/
  millisecond、projection truncation、Trace、Artifact coverage codec 和 no-result。
- 现有 lexical、semantic、structured、SQL、context、evidence、runtime、Trace、CLI/TUI/Web、
  Conversation 测试继续作为全量回归。
- `temporal-overview-guidelines.md`、Stage 1.3/1.4/1.7/1.8/1.9 ADR amendment 和
  `interview-defense.md` 固化预算、coverage、时间 owner、错误矩阵与实测证据。

## Boundary / Ownership

```text
Canonical Store / SQLite read adapter: message facts, ordering, keyset predicate.
Capability: trusted session/time scope and archive_latest resolution.
Tool / Runtime: envelope, continuation visibility, independent model projection budget.
Evidence / Answer Artifact: current-run citation validation and persisted coverage/time facts.
Trace / UI: bounded diagnostic projection; never a second canonical message source.
Agent: topic semantics and final wording; never trusted scope, dates, or coverage bookkeeping.
```

## 2026-08-28 independent root aggregation amendment

真实 Trace `trace-5e2ed5cddf674a6ebc3fc1d6f0a7c084` 先执行同窗 `2699/2699 complete`
root recent 查询，随后又执行 `60/2699 partial` 的独立 root 查询。旧 finalizer 把全部 recent
records 当作单一 continuation 顺序，因 `2699 → 60` 抛出虚假的 `COVERAGE_MISMATCH`。

同一 Host-resolved window 的多个 root 查询现在按最大已证明 `covered_units` 汇总；后来的小样本
不覆盖先前 complete 事实。时间窗、basis、unit、eligible units、单记录 count/status 与 current-run
唯一 message ID union 校验保持不变，因此真实 coverage 冲突仍显式失败。回归用例位于
`test_temporal_overview_coverage.py`，覆盖 complete root 后独立 smaller root 的真实调用形状。
