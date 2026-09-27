# Assistant provisional Planner-only review

**assistant provisional review != human adjudication**。本审阅在生成并校验 `experiment-final/blind-review-packet.md` 与单独 `blind-key.json` 后，对正式 8 Case × 5 repeats 的 Plan artifact 揭盲阅读。没有运行 Runtime Tool Loop，没有最终答案、证据命中或用户效用结论；本文件不成为 Router label 或 production gate。人工审阅仍可改变判断。

## Rubric 逐轴观察

| Axis | Provisional comparison |
| --- | --- |
| Entity preservation | P2 的 dependent 5/5 以 `mattpocock skills` 原始分享为起点，archify/Forge 也保持具体实体。P0 常并列泛化检索；P1 大体已改善，P2 没有明显回退。 |
| Scope discipline | P2 不自动给 dependent/archify/Forge 加 category、recent 或 identity 扩展。`dev-cite-archify` 的 3/5 次含额外 recent 浏览，虽问题询问“最近发展”，仍有选用过宽的局部风险。 |
| Tool relevance | P2 的 40 个有效 Plan 没有 lexical+semantic 同 Step（P0 有 32 个此类 Step）；没有 `find_members` 用于消息内容，也没有聚合后额外 retrieval。步数及工具组合只作结构证据，不自动代表答案质量。 |
| Incremental value | dependent 的 direct share→same-discussion feedback、archify 的相关使用讨论→回复、schema→SQL 都是有序关系。P2 没有无工具的独立“归纳/输出” Step；P1 有 4 个，P0 有 22 个。 |
| Evidence alignment | dependent 的 5/5 Plan 在 `evidence_needed` 和 criteria 中要求区分推荐/用法与后续亲自使用依据；archify 5/5 区分 firsthand 与兴趣/二手；SQL 题需要数值、会话 ID 与 UTC 范围。 |
| Context/relation quality | dependent 5/5 指向原始分享的同一讨论；archify 使用“最相关使用讨论”的回复。cite-archify 仍未获得实际 direct hit，不能证明 Runtime 会选择正确 message anchor。 |
| Redundancy | P2 没有同 Step 多工具或无工具总结；cite-archify 某些 Plan 用两次 lexical 分别回答项目进展与 star 数，是两个需求面，但 r2 的额外 recent 可能重复。 |
| Overplanning | P2 zero-result 5/5 仅规划完整 UTC 日窗口 `get_recent_messages`；aggregation/rank 5/5 都仅 schema→SQL；trend 有 4/5 次在 recent 后规划 context，可解释为代表性话题复核，仍待人审其必要性。 |

## Case 回归与比较

| Case | P0 / P1 / P2 valid | P2 provisional judgment |
| --- | --- | --- |
| dependent / `mattpocock` | 5 / 5 / 5 | P2 的实体原锚与 direct share→feedback 关系稳定；无裸 generic category 替代。与 P1 相近，P1 有个别额外总结或条件性 semantic。 |
| archify context | 5 / 5 / 5 | P2 5/5 先 direct mention/share/use，再读最相关回复，区分 firsthand 与兴趣；与 P1 相近。 |
| aggregation | 5 / 5 / 5 | P2 5/5 schema→SQL 后停止；P0 5 个有效 Plan 均含多余 retrieval/校验。 |
| verified zero-result | 4 / 5 / 5 | P2 5/5 单步读完整 UTC 日窗口、无 SQL 再证；P1 有 2 个额外 Step。这里只检验规划契约，不声称实际空窗已由 Runtime 证明。 |
| 30-day topic | 5 / 4 / 5 | P2 1 次 recent 单步、4 次 recent→代表性 context，未机械并列 lexical/semantic。context 的必要性需要人工判断；未见明确质量回退。 |
| Forge direct lookup | 3 / 5 / 5 | P2 5/5 以 Forge lexical 为锚，context 用于确认直接分享；没有脱离实体的 generic-category 检索。简单问法是否连 context 都不需要，保留审阅余地。 |
| archify recent/star | 4 / 2 / 5 | P2 5/5 分别寻找近期项目动态与 star 提及；3 次使用 recent，r2 的第三 Step 可能过宽或重复。P1 仅 2 次完成，不能从有效 Plan 数直接证明 P2 语义全面更优。 |
| UTC session rank | 4 / 5 / 5 | P2 5/5 先 schema 后 SQL，取会话 ID 和消息数，无额外校验。 |

## Review conclusion and limits

P2 在本套已暴露 Development Case 中保留 P1 的主要实体、关系、确定性 SQL 和 zero-result 收益，并解决 2048 thinking token 耗尽造成的可见 JSON 截断；没有针对 Case 字面量的 prompt patch。局部疑点是 cite-archify 的 recent 范围和趋势题的 context 必要性。它们不构成本轮 assistant 观察下的明显整体回退，但需要 human adjudication；不据此推断实际检索、引用或最终答案改善。盲包供人工在不知 P0/P1/P2 映射时重审；assistant 判断不得改写正式 label。
