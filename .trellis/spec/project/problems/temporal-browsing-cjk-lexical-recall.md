# Problem: Temporal Browsing 缺失 与 中文 Lexical 0-hit

> Task: `.trellis/tasks/08-27-recent-messages-lexical-recall` · 真实 Failure Case 驱动修复记录。

## Problem

同一真实用户问题 `最近一两天大家都在讨论什么有价值的内容`：

1. Trivae 无法稳定回答（terminal failed），Agent 行为是"猜测主题 → semantic/lexical 检索猜测"；
2. `lexical_search("推荐")` 在 canonical 存在 `真心推荐 值得看一看` 的时间窗内返回 0 hits（coverage complete）。

## Evidence

- Trace `trace-87060c18023e46988f4df09a98a27f9f`（2026-08-27 11:28）：
  - semantic ×3 + lexical("推荐") + get_schema，0 命中；terminal failed / 5 tool calls / ~75s / final_answer not available。
- 同题 ChatLab 对照：单次 `get_recent_messages(2026-08-15~16, limit=200)` 返回 108 条消息后一次总结成功。
- 真实库诊断脚本（本任务目录 / 会话记录执行）：
  - `LIKE '%推荐%'` 全库 1596 hits；窗口内 14 hits；
  - FTS MATCH `"推荐"` 全库 258、窗口内 **0**；
  - 目标消息 `qq:1039179741:7674201141965536638` FTS row 存在；index count 473236==473236 非 stale；
  - fts5vocab 实测 unicode61 tokens：`真心推荐`、`值得看一看` 为整 run 单 token；`推荐这个repo` 混合串亦为单 token；
  - trigram tokenizer 探针：对 2 字查询 MATCH=0（trigram 最小 3 字符）。

## Root Cause

- Failure A（架构层）：Stage 1.4 Tool Surface 没有 temporal browsing 能力，prompt 引导把时间窗问题推向 keyword/concept retrieval；"猜测最近内容再搜索"必然 miss。空结果又被答案契约拒绝为 fatal → terminal failed。
- Failure B（派生索引层）：FTS5 unicode61 tokenizer 把连续 Han 字符 run 归并为一个 token，子串查询无任何 token 级匹配机会；与 session/scope/timestamp/freshness/escaping 无关（已逐一排除）。

## Options（Failure B）

| 方案 | 结论 |
| --- | --- |
| A. trigram tokenizer | rejected（measured）：2 字查询 0 命中，中文双字词占主导；ASCII substring 语义同时被破坏 |
| B. rebuild+query 双侧 CJK bigram 归一化 | selected |
| C. dual index | rejected：维护/一致性成本高，B 单索引即可同时覆盖 |
| D. query-time LIKE fallback | permanently rejected：silent fallback + 性能差 + 破坏 failure attribution |

## Decision

- A：新增 `get_recent_messages`（ADR Stage 1.4 §19 reopen 记录），复用 Structured Retrieval，selection latest-N→chronological return，limit 复用 structured bound。
- B：`sqlite_lexical_text.py` 纯函数归一化（Han run ≥2 → 重叠 bigram）；rebuild 经 SQLite 自定义函数应用；query 侧 `_fts_match_expression` 同函数归一化为保序短语；strategy id `unicode61+cjk-bigram-v1` 写入 `trivae_derived_meta`，read 侧不匹配即显式 stale。

## Validation

- 单元/回归：`tests/test_chinese_lexical_regression.py`（14）、`tests/test_recent_messages.py`（9）、全量 404 passed、ruff/mypy clean。
- 真实库：rebuild 473236 msgs / 9.0s；Smoke B 同窗口 total 157（此前 0），目标消息命中；Smoke A 连续多轮以 `get_recent_messages` 作为首个且唯一数据读取 Tool 完成（trace-3c348e06…、trace-e3b18400…、trace-41c05fb2…，1 tool call / 1 round / 23–36s / citations 3–5）。其中一次 provider runtime error（opencode-go）为模型服务侧故障，与本修复无关。

## Observability

- tool.call.started/completed 携带 request 与 result summary（returned/total/truncated/selection/resolved_time_range/latency_ms）；
- lexical 路径保留 strategy=lexical、coverage、returned/total、index diagnostics；strategy 不一致 → CAPABILITY_UNAVAILABLE + stale 提示，不静默降级。

## Scale

- measured：47.3 万消息 rebuild ≈9s（M2 MacBook）；窗口浏览 SELECT 单位毫秒级；bigram 仅作用于 Han run，非 Han 规模不变。
