# Assistant blind adjudication：揭盲结果

审阅日期：2026-09-27。审阅者在提交 `assistant-blind-review-reviewed.md` 中的 40 组 `Ranking` 和 `Rubric observations` 时没有查阅 A/B/C 映射；文件自标为 `ChatGPT assistant blind adjudication`。本报告随后使用原先独立保存的 `blind-key.json` 揭盲。**这是 assistant blind adjudication，不是 human adjudication。**

## 来源和校验

- 已审文件的 Reviewer、Ranking、Rubric observations 以外的逐行正文，与原 `blind-review-packet.md` 完全一致；Plan 和 User Query 未被改动。
- 40 个 review ID 与 key 一一对应；每组均有非空观察和不并列的 A/B/C 完整排序。
- `runs.jsonl` 独立核对 9 次 `provider_length`：P0 5 次、P1 4 次、P2 0 次。硬失败在审阅排序中均置于有效 Plan 之后。
- 名次统计直接计数，不把 8 个 Case 的 5 次重复当成 40 个独立题目；没有把排序当成 Runtime 或最终答案的质量分数。

## 总体排序

| 版本 | 第一 | 第二 | 第三 | 两者都有效时的对比 |
| --- | ---: | ---: | ---: | --- |
| P0 | 0 | 6 | 34 | 对 P2：2 胜、33 负（35 组） |
| P1 | **30** | 6 | 4 | 对 P2：**30 胜、6 负**（36 组） |
| P2 | 10 | **28** | 2 | 对 P0：33 胜、2 负（35 组） |

P2 的 10 次第一中，4 次对应 P1 `provider_length`，其余 6 次是两个有效 Plan 的质量比较。P1 的 30 次第一均是与有效 P2 Plan 比较。P2 的 2 次第三分别是 `dev-context-archify-r1` 与 `pu-rank-utc-session-r4`。所以 P2 的 **40/40 有效**是真实可靠性收益，但不能据此说其有效 Plan 质量与 P1 持平。

## 按 Case 的名次

每格依次为第一／第二／第三，共 5 次重复。

| Case | P1 | P2 | 观察 |
| --- | --- | --- | --- |
| dependent / mattpocock | 4／1／0 | 1／4／0 | 两者均保留实体→原讨论 context；P1 多数在 firsthand 判别和证据要求上更完整。 |
| archify 使用反馈 | 5／0／0 | 0／4／1 | P2 r1 成功条件预设找到 firsthand，未明确允许“没有亲历使用证据”。 |
| UTC count / types | 5／0／0 | 0／5／0 | 两者通常都是 schema→SQL；P1 的 UTC 半开边界与单次确定性聚合表述更精确。 |
| 空日期窗口 | 5／0／0 | 0／5／0 | 两者都保留一次完整窗口 recent 后停止；P1 对空窗口结论和时间边界更明确。 |
| 最近 30 天话题 | 2／2／1 | 3／2／0 | P2 的 recent→按需 context 更常被选为优；P1 r4 硬失败。 |
| Forge | 3／2／0 | 2／3／0 | P2 保留实体 lexical first；是否设置有条件 semantic fallback 影响排序。P0 两次硬失败。 |
| archify 最近发展／star | 2／0／3 | 3／2／0 | P2 三次第一均遇到 P1 硬失败；两者都有效的 r1/r2，P1 更优。P2 的 broad recent 范围仍是疑点。 |
| UTC 会话排名 | 4／1／0 | 1／3／1 | P2 r4 额外规划第二次 SQL；P1 多数更明确半开边界与统计口径。 |

## 40 组映射后的排序

表内从左至右为 r1、r2、r3、r4、r5。

| Case | 揭盲排序 |
| --- | --- |
| `pu-dependent-mattpocock` | P1>P2>P0；P1>P2>P0；P2>P1>P0；P1>P2>P0；P1>P2>P0 |
| `dev-context-archify` | P1>P0>P2；P1>P2>P0；P1>P2>P0；P1>P2>P0；P1>P2>P0 |
| `pu-aggregate-utc-types` | P1>P2>P0；P1>P2>P0；P1>P2>P0；P1>P2>P0；P1>P2>P0 |
| `dev-zero-empty-3` | P1>P2>P0；P1>P2>P0；P1>P2>P0；P1>P2>P0；P1>P2>P0 |
| `dev-temporal-30d` | P2>P1>P0；P1>P2>P0；P1>P2>P0；P2>P0>P1；P2>P1>P0 |
| `dev-lexical-forge` | P1>P2>P0；P2>P1>P0；P1>P2>P0；P2>P1>P0；P1>P2>P0 |
| `dev-cite-archify` | P1>P2>P0；P1>P2>P0；P2>P0>P1；P2>P0>P1；P2>P0>P1 |
| `pu-rank-utc-session` | P2>P1>P0；P1>P2>P0；P1>P2>P0；P1>P0>P2；P1>P2>P0 |

## 判断及边界

盲审排序显示 P2 相比 P1 有**系统性的相对 Plan 质量回退**：两个版本都有效的 36 组中，P1 优于 P2 的有 30 组。部分差距是证据条件、UTC 边界表达等细节，但 archify r1 的 firsthand 预设与排名 r4 的重复 SQL 是具体可定位的回退。P2 仍明显优于 P0：两个版本都有效的 35 组中，P2 优于 P0 的有 33 组；实体锚点、scope、工具增量和停止条件的主要方向并未整体消失。

正式 P2 同时改变了 prompt 与 DeepSeek Planner thinking 配置；此盲审**不能把质量回退因果归于其中某一项**。排序由 assistant 完成，未经人类复核，且只涉及已暴露的 Development Case；不代表真实 Tool Loop、最终答案、Holdout、Router label 或 production gate。

先前 `final-conclusion.md` 的 `PASS` 基于揭盲后的 provisional review，早于这份独立填写的盲审。按本任务“P1 主要 Plan 质量收益无明显回退”的原门槛，现将 **P2 promotion gate 修订为 `FAIL`**：可靠性子项通过，质量保持子项不通过。保留 P2 为诊断和后续通用优化基线；暂不进入三路 E2E。
