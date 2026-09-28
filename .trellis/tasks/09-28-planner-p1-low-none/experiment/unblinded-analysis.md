# P1 canonical `low` vs `none`：Planner-only 单变量实验结论

## 实验身份与边界

- 8 条已暴露 Development Case，每条 `low` 和 `none` 各一次，共 16 次真实 Planner Provider 请求。`attempts.jsonl` 与 `runs.jsonl` 各 16 条；没有 retry、补跑、Router/Jev、Runtime Tool Loop、E2E 或 Holdout 调用。
- 请求前保存交错的 `schedule.json`：奇数 Case 为 `low → none`，偶数 Case 为 `none → low`。两侧都用当前生产 `SoftPlanner`、相同的 P1 canonical prompt、Capability metadata/guidance、Case/Snapshot、七 Tool allowlist、Parser、20 秒 timeout 和同一个 Provider client。
- 首次请求前逐 Case 验证生产 builder 的 prompt 与冻结 P1 fixture 全文相等；逐字段验证两侧请求投影仅 `reasoning_effort` 不同。共同参数为官方 DeepSeek `deepseek-flash`、`max_tokens=2048`、`temperature=0`、JSON object mode。底层 client `max_retries=0`。
- 生成阶段结束后才创建随机 A/B 盲包和独立映射。独立 reviewer 只读取盲包，完成全部 8 组判断并保存 `blind-judgments.md` 后，才读取 `blind-key.json` 揭盲。以下是揭盲分析；原始盲判保持原文。

## Completion reliability

| Treatment | 有效 Plan | `provider_length` | parse failure | 其他 failure |
| --- | ---: | ---: | ---: | ---: |
| `low` | 6/8 | 2/8 | 0/8 | 0/8 |
| `none` | 8/8 | 0/8 | 0/8 | 0/8 |

`low` 的 `dev-zero-empty-3` 和 `dev-temporal-30d` 均收到 `finish_reason=length`，在 Provider response 阶段归为 `provider_length`；两条原始可见输出分别为 186 和 311 字符，未形成有效 Plan。两次失败保留在正式分母，没有补跑。`none` 在这两个 Case 有有效 Plan，但不能自动记作语义质量胜利。

本轮观察到 `none` 的 Planner completion 更稳定（8/8 对 6/8，截断 0 对 2）；8 次单次样本不能证明长期失败率为零或精确估计改进幅度。

## 盲判与揭盲

| Case | 盲判 | A / B | 揭盲结果与具体原因 |
| --- | --- | --- | --- |
| `pu-dependent-mattpocock` | B better | low / none | **none better**：两侧都以 `mattpocock skills` 为锚，定位分享再查后续反馈。`low` 把同一 `get_message_context` 用途拆成两步；`none` 一步已覆盖反馈和亲自使用依据，减少重复取上下文。 |
| `dev-context-archify` | A better | none / low | **none better**：`none` 明确先定位 archify 的直接分享、推荐或使用讨论，再沿该命中取上下文，并排除兴趣/想尝试；`low` 首步偏一般提及与声称反馈，direct hit 关系较弱。 |
| `pu-aggregate-utc-types` | same | low / none | **same**：两侧都是 schema 确认后用单条 SQL 做 UTC 当日 text/reply 聚合；时间边界措辞的差异不足以改变证据路径。 |
| `dev-zero-empty-3` | unjudgeable | low / none | **unjudgeable**：`low` 截断，无双边语义比较；`none` 有效 Plan 先用 `get_recent_messages` 读取完整 UTC 日窗口，符合空窗判断路径。 |
| `dev-temporal-30d` | unjudgeable | none / low | **unjudgeable**：`low` 截断，无双边语义比较；`none` 有效 Plan 先读取 30 天时间窗，再建议语义补充，不能据此断言其相对质量更高。 |
| `dev-lexical-forge` | A better | low / none | **low better**：两侧都保留 Forge 实体词并读 direct hit 上下文；`low` 仅在精确路径不足时，补充概念召回并要求重新关联 Forge，覆盖可能未写项目名的描述。`none` 缺少这一有条件的补充路径。 |
| `dev-cite-archify` | A better | low / none | **low better**：`low` 分别处理 archify 近期进展与 star 提及，语义召回只在精确措辞不足时补充；`none` 首步机械并列 lexical + semantic，增加无明确增量的检索。 |
| `pu-rank-utc-session` | A better | low / none | **low better**：两侧都用 schema + SQL 计算 UTC 当日最高会话；`low` 额外明确并列最高时应列出或说明并列，`none` 未覆盖。这是较窄的结果完整性差异，不应被放大成普遍 SQL 规划失败。 |

仅统计双方都有有效 Plan 的 6 组：**low better 3，none better 2，same 1，unjudgeable 2**。后两组不计入语义胜负分母。盲判没有因为 Plan 更长、步骤或 Tool 更多就判胜；较长的 `low` Plan 也因重复 context 在 dependent Case 失分。

## 质量模式与关键风险

- **Entity anchored retrieval / firsthand relation**：`none` 在 `dev-context-archify` 对 direct share→context 的关系更明确，在 dependent Case 更紧凑；没有出现关闭 reasoning 后反复丢失实体锚或 firsthand 限制的模式。
- **Cite-archify / context recovery**：`none` 能保持 archify 与 star 两条信息需求，但首步自动并列 lexical + semantic；这是本轮一条可定位的检索纪律退化。`low` 的更多步骤也不能直接视为收益，胜因是条件化召回和分开定位 star 证据。
- **Zero-result / 30 天时间窗**：`low` 两次 `provider_length` 是 completion reliability failure，不是正常双边 semantic comparison。`none` 的有效 Plan 含适当的时间窗读取；Planner-only 记录不能证明 Runtime 真正完成空窗证明或话题覆盖。
- **Deterministic SQL**：聚合 Case 两侧等价；排名 Case 的差异集中在并列结果的 success criterion，`none` 没有遗漏 SQL 主链路。单个并列条件不能推断为系统性 SQL 回退。
- `none` 在 3 组低于 `low`，但问题分别是受条件约束的召回缺失、机械双检索和并列结果说明；它们没有在多个不同 Case 上重复成同一种方向明确的质量缺陷。同时 `none` 在 2 组更好、1 组相同，另 2 组无法双边比较。因此**未观察到明确的系统性 Plan 质量回退**，也**不能声称质量等价**。

## 效率（Provider 返回的真实字段）

| Treatment | 平均 / 中位 latency | input tokens | completion tokens | reasoning tokens |
| --- | ---: | ---: | ---: | ---: |
| `low` | 6.700 / 5.988 秒 | 9,994（8/8 返回） | 10,808（8/8 返回） | 9,107（8/8 返回） |
| `none` | 1.301 / 1.309 秒 | 9,794（8/8 返回） | 1,308（8/8 返回） | unknown（0/8 返回） |

latency 为每 treatment 全部 8 次调用的 Planner 总耗时，包含失败。`none` 未返回 `reasoning_tokens`，不能记成零。Provider 未返回真实 monetary cost：**monetary cost unavailable**，不估算。

## 工程决策

**B. 当前证据不足，需要保留不确定性。** `none` 本轮明显减少 completion failure，且没有跨多个 Case 重复的同向重大语义退化；但 6 组有效双边比较只有 1 组判 same，`low` 在 3 组胜出，其中 cite-archify 的机械双检索值得关注。8 Case × 单次运行不足以证明长期质量等价或统计显著性。

**建议进入下一阶段有界 E2E 验证，定位为验证而非质量冻结或生产收益声明。** 下一阶段应重点观察 cite-archify 的实际检索路径、Forge 条件召回、zero-result 完整空窗证据和 SQL 排名答案；本轮未执行 E2E，也不基于 Planner-only Plan 宣称最终答案质量。
