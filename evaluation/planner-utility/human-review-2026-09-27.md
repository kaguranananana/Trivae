# Planner Utility：15 道人工裁决汇总（2026-09-27）

本记录来自用户完成的 15 道盲审及揭盲裁决。当前 v2 的 6 道结果已按 Snapshot、Standard/Planned Variant 和真实 run ID 写入 `adjudication-v1.json`；另外 9 道仅有 2026-09-25 的历史运行，只保留为**历史人工判断**，不绑定当前 v2，也不计入当前 v2 的正式 Router Utility 结果。原始答案与揭盲表见本地 `data/evaluation/planner-router-utility/2026-09-26/manual-review-packet.md`。

## 当前 v2：正式裁决

| Case | 标签 | 人工理由摘要 |
| --- | --- | --- |
| `dev-zero-empty-3` | `indifferent` | 两轮两路均正确回答 2025-08-26 UTC 为 0 消息。 |
| `pu-dependent-mattpocock` | `standard_preferable` | Standard 找到明确亲自使用的正面证据；Planned 漏掉，还把疑问当成反馈。两路均未命中指定 required context。 |
| `dev-context-archify` | `standard_preferable` | r1 Standard 找到群友反馈，Planned 错报没有评价；r2 两路均漏掉。Standard 的安装推断过强，但不改变相对裁决。 |
| `pu-count-utc-day` | `indifferent` | 两路均准确得到 883。 |
| `pu-rank-utc-session` | `indifferent` | 两路均准确得到 `qq:677019167`、224 条。 |
| `pu-aggregate-utc-types` | `indifferent` | 两路均准确得到 `text=814`、`reply=17`，其他类型一致。 |

当前 v2 合计：`planned_beneficial=0`、`standard_preferable=2`、`indifferent=4`、`uncertain=0`。`pu-dependent-mattpocock` 的指定 target / required context 仅是人工检查点；其集合未证明 corpus-exhaustive，因此漏掉指定消息不能单独推出答案错误。本题两路的 context recovery 都未命中指定上下文，Standard 的优势来自最终答案恢复了更强的亲自使用证据，并避免把疑问当反馈。

## 2026-09-25：历史人工判断

下表对应旧 Variant 的答案，不能填入当前 v2 的 `adjudication-v1.json` 正式 run 绑定。

| Case | 标签 | 人工理由 |
| --- | --- | --- |
| `dev-context-mattpocock-1` | `indifferent` | 两路都找到仓库、`/teach` 用法、正面反馈、joye 对 teach 的负面评价，并区分“尚未体验”；无稳定 treatment 优势。 |
| `dev-context-mattpocock-2` | `indifferent` | 两路均表达整体有正面推荐、直接使用反馈有限、teach 存在负面意见；Planned 展开更多，但无可验证任务收益。 |
| `dev-cite-archify` | `indifferent` | 两路都恢复 7k → 9.5k、赞助及 DeepSeek Harness 插件；Planned 的泛 star 检索没有改善核心答案。 |
| `dev-lexical-forge` | `indifferent` | 多次观察里两路都稳定找到 `AnHuoZhe/forge`，并说明需求澄清、架构文档、拆任务、实现与验收；无稳定胜负。 |
| `dev-para-ai-interest` | `indifferent` | 两路均找到“对 agent/ai 不感兴趣，每天只是为了工作而工作”的目标原话，且能区别其他泛化的“提不起兴趣”。 |
| `dev-temporal-7d` | `standard_preferable` | Standard 披露 15,221 条里只覆盖 300 条且集中在窗口末端；Planned 以“过去一周主要讨论”组织答案，未披露 `partial + truncated`，形成 coverage overclaim。 |
| `dev-temporal-30d` | `indifferent` | **双方共同失败**：都把 `partial + truncated` 的局部结果包装为最近 30 天主要话题，未充分披露覆盖限制。相对 treatment 打平，不代表绝对质量合格。 |
| `dev-zero-empty-1` | `standard_preferable` | 两路都有成功和失败运行，可靠性无明显胜负；Planned 曾由相邻日期有消息推断“更像存档缺口”，缺乏证据。 |
| `dev-zero-empty-2` | `indifferent` | 两路都正确回答 2025-08-23 无消息；Planned 增加的库覆盖细节未改变任务完成度。 |

历史 9 道合计：`planned_beneficial=0`、`standard_preferable=2`、`indifferent=7`、`uncertain=0`。15 道人工判断合计：`0 / 4 / 11 / 0`（依次为上述四类标签）。这个跨版本合计仅描述人工审阅的全部材料，**不是**单一当前 v2 run 的正式统计。

## GT 适用性与后续判断

四个新增 `pu-*` Case 的 GT applicability 均为 **Accept**，CaseBundle 的 GT 事实保持不变。`pu-dependent-mattpocock` 的 `gt.relevant`、`gt.required_context` 仍为 `partial`；其 `gt.relevant` 已知限制“target 集合未证明 corpus-exhaustive”继续有效。

现有审阅材料没有一题证明当前 Planner treatment 带来稳定的用户答案质量收益。尤其依赖式多阶段的 `pu-dependent-mattpocock` 中，Standard 找到了更强的一手使用证据。因此，不能由“问题复杂”直接推出“应走 Planned”。下一步应读取 Plan、Tool 调用、检索候选、Evidence Selection 与最终答案的 Trace，定位关键上下文在何处丢失；先归因，再决定是否需要改 Planner、检索或其他主链路。

`pu-dependent-mattpocock` 的现有 Trace 提供了一个具体排查入口：两路都先用 `mattpocock` 检索，返回 8 条且覆盖完整；Standard 接着检索 `matt`，返回 23 条且覆盖完整；Planned 接着检索更宽泛的 `skills`，触及 100 条上限，结果为 `partial + truncated`，之后又扩展两处上下文。Planned 的 Plan 文本确实要求核查亲自使用依据，但没有把这项要求稳定落实为有区分力的后续检索。这里只能确认工具路径和输出覆盖的差异；强证据究竟在候选生成、上下文选择还是最终 Evidence Selection 阶段丢失，仍需逐条对照 Trace 与消息 ID，不能仅凭本次结果断定 Planner 是唯一根因。
