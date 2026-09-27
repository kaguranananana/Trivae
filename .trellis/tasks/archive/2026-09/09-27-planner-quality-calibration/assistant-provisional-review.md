# Assistant provisional Planner-only review

本文件是 Codex assistant 对 `experiment/runs.jsonl` 的**揭盲、非正式**逐 Plan 审阅。它不是 human adjudication，也不修改既有 treatment `adjudication-v1.json`。所有判断仅针对 Plan artifact，不涉及 Runtime 检索、Evidence 或最终答案。盲审输入在 `experiment/blind-review-packet.md`，A/B 映射单独在 `experiment/blind-key.json`。

## Review rule

一侧没有有效 Plan 时，另一侧只有“本轮能提供计划”的操作性优势，不因此证明其语义完美。两侧均失败记 uncertain。人工复核仍可改变任何 provisional direction。不要把以下方向变成 Router label 或最终答案质量分数。

| Case | r1 | r2 | r3 | 主要观察 |
| --- | --- | --- | --- | --- |
| `pu-dependent-mattpocock` | P1 better | P1 better | P1 better | P1 始终保留 `mattpocock` 主锚，先原始分享后同讨论反馈；P0 常同时建议 lexical/semantic，拆出重复 context/汇总步骤。 |
| `dev-context-archify` | P1 better | P1 better | P1 better | P1 只建议 lexical→相关 direct hit 的 context，明确实际使用与兴趣/二手推荐区别；P0 额外 semantic、recent、甚至 SQL/member。P1 r1/r3 的“相关消息”仍未充分说明最优锚点。 |
| `pu-aggregate-utc-types` | P1 better | P1 better | P1 better | P0 r1/r2 `provider_length`；r3 在 schema/SQL 前插入 recent。P1 三次都限于 schema→一次 SQL。 |
| `dev-zero-empty-3` | P1 better | P0 better | P1 better | P1 成功时只建议完整 UTC 窗口 `get_recent_messages`；r2 `provider_length`，P0 有有效 Plan。P0 常额外规划条件式 semantic/context/SQL。 |
| `dev-temporal-30d` | P1 better | P0 better | indifferent | P1 成功时强调候选主题合并与代表性 context；r2 `provider_length`。r3 两路都有多工具扩展，难以证明 P1 有足够增量。 |
| `dev-lexical-forge` | P1 better | P1 better | P1 better | P1 精确锚定 Forge，只有命中不足时才语义补充；P0 建议机械 lexical+semantic、成员解析或无关 recent。 |
| `dev-cite-archify` | P1 better | P0 better | P0 better | P1 r1 避免 recent 全窗并聚焦 archify；r2/r3 均 `provider_length`。P0 虽冗余但有 Plan。 |
| `pu-rank-utc-session` | P1 better | P1 better | uncertain | P1 成功时 schema→SQL 即止；P0 r1 加重复 SQL 核查，r2 加空泛输出步骤。r3 两路均 `provider_length`。 |

合计仅作 assistant provisional 描述：P1 better 18、P0 better 4、indifferent 1、uncertain 1（24 个重复 pair）。其中多个 P1 better 是 P0 failure 对 P1 success；另有多个 P0 better 完全由 P1 failure 决定，故不能从这个合计直接推出总体优劣。

## Rubric 逐轴

1. **Entity preservation**：P1 的 dependent 3/3 有明确 `mattpocock` primary anchor；Forge 3/3 维持项目名。P0 本轮 dependent 成功 Plan 也多次保留实体，故不能声称 P0 三次都发生 entity dilution；历史 v3 r2 的“`mattpocock 或 skills`”仍是真实反例。P1 r2 的补充检索仍带实体，未回到裸 `skills`。
2. **Scope discipline**：P1 主要沿实体 direct hit；P0 在 archify、Forge、aggregation、cite-archify 常把 recent、semantic 或 broad category 放在无必要路径。P1 趋势题 r3 仍同时安排 semantic 与 lexical/context，增量边界不够清晰。
3. **Tool relevance**：P1 dependent/archify/Forge 成功 Plan 基本是 lexical + context，aggregation/rank 是 schema + SQL，zero 是 recent。P0 频繁机械配对 lexical/semantic，且有 `find_members`、recent 或额外 SQL。P1 archify r2 的无工具分类 Step 仍可能由 Runtime 直接完成。
4. **Incremental value**：P1 平均步骤 2.16（成功的 19 条），P0 3.71（成功的 21 条）。P1 常给出“先识别原始分享/邀请，再沿其讨论取 firsthand feedback”的额外关系；P0 常把搜索、context、归纳重复拆步。步数本身不是质量分数。
5. **Evidence alignment**：P1 dependent 明确推荐/用法与后续亲自使用反馈分开；archify 强调实际安装/试用/评价证据；SQL 题只需确定性数值。P0 仍经常有无关身份、热度或空泛正负分类证据。
6. **Context/relation quality**：P1 dependent r1-r3 与 archify r2 指定直接分享/推荐/邀请/使用讨论为 context anchor；P1 archify r1/r3 只说“相关消息”，仍有选错多个 direct hit 的风险。Planner 不知道真实消息，不能生成具体 message ID。
7. **Redundancy**：P1 少见独立“总结/再验证”步骤；P0 dependent、archify、Forge、cite-archify 普遍重复归纳或 context。P1 仍有个别分类步骤，需人工判断是否有新增价值。
8. **Overplanning**：P1 aggregation 三次只 schema→SQL，zero 成功两次一 Step，rank 成功两次 schema→SQL；P0 aggregation r3 先 recent，rank r1 再 SQL，zero 常加条件式额外步骤。
9. **Failure rate**：P0 `provider_length` 3/24，P1 5/24；invalid JSON、timeout、empty response 均 0。P1 的 5 次分布在 zero 1、trend 1、cite-archify 2、rank 1。所有失败保留为无 Plan，没有重试或替换。

## 六个已知输出的对照

- dependent old r1：4 Step，lexical+semantic、context+recent、context+find_members、最后整理；P1 r1 变为明确 `mattpocock` lexical 主锚→原始分享 discussion context，两步。
- dependent old r2：第一步“`mattpocock 或 skills`”；P1 r2 明确“含 mattpocock 与 skills 仓库的原始分享”→同会话后续反馈，只有上下文不足时才继续带实体检索。P1 仍不能保证 Runtime 执行该锚定。
- archify old r1：lexical→semantic→笼统 context+recent→汇总；P1 r1 为提及 archify 且识别直接分享/推荐/使用讨论→相关消息回复中的 firsthand 反馈。后者仍偏泛。
- archify old r2：lexical+semantic→笼统取 context→分类；P1 r2 更具体地优先直接分享/推荐/邀请/实际使用讨论，再检查回复，区分实际使用与兴趣/二手推荐。
- aggregation old：schema→SQL→“必要时 recent/context 校验”；P1 三次均 schema→SQL，无无意义 retrieval。P0 本轮两次在 2048 token 截断。
- zero-result old：历史 v3 `provider_length` 后 graceful skip；本轮 P1 r1/r3 能单步建议完整 UTC 空窗读取，但 r2 仍 `provider_length`。原有 skip contract 未变，Planner-only 实验没有 Runtime，因此没有声称零结果最终回答已改进。

## 结论与下阶段门槛

P1 成功输出的调查价值与工具纪律更好，但 **Provider 完成可靠性没有改善，反而在本小样本更差**；尤其 simple lookup 2/3 无有效 Plan。当前证据不支持立即进入 Standard vs Planned-P0 vs Planned-P1 E2E，也不支持把本分支当成生产收益。保留 P1 candidate、失败记录和 blind packet；下一轮若要推进，应先对通用 prompt/summary 长度与 Provider `length` 归因做 Planner-only 校准，再重复实验并由人审盲包。不要针对 Case 字面量补规则、加自动 retry 或改 Router。
