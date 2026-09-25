# Planner Utility Evaluation：Development forced-path 配对实验

> 2026-09-25；本报告是 Development 证据，不是 fresh Holdout。主实验为 37 Case × 2 Variant × 1 repetition；targeted repeat 与 smoke 独立。生产 Router 保持 `shadow`。

## 结论与决策

**当前证据不支持把 SoftPlanner 作为普遍有益的独立执行阶段。** 它在少数 context recovery / evidence Case 上有条件收益，同时在确认的空结果 Case 上有明显回归，且增加平均 8.54 秒和 33.62% 实测 token。对真正 dependent multi-stage Query 的价值仍未判定，因为现有 Development GT 没有可靠的逐 Case Router route 标签，16 条 Router 诊断 Case 又没有答案级 GT。保留现有两路架构供后续验证，不调整 Planner prompt，不把生产 `shadow` 改为 `jev`。

这不是“Planner 永远无用”的结论。当前可证伪的判断是：**在本次 37 条 Development workload 上，额外调用 Planner 的可观测收益不足以抵消它在空结果和答案完成上的风险与开销；若要将它用于特定 Query，须先有人类核验的 utility 标签与针对该类的重复验证。**

| 决策情形 | 本轮证据 | 处置 |
| --- | --- | --- |
| Conditional utility | context recovery 主实验 2/3 改善，`dev-context-archify` 三次为 better/better/same | 保留为研究假设；补充真正多阶段、证据依赖 Case 的答案 GT 和人工裁决 |
| Broad no utility | 26/37 个配对在可比较自动质量维度上 same；36/37 答案文本不同，same 不是语义等价 | 不将 route classification 准确率当业务收益 |
| Regression | 主实验 verified zero 3/4→0/4、valid answer 36/37→34/37；`dev-zero-empty-3` 三次均变差 | 冻结本次 baseline 与 review packet，后续优化另开实验 |
| Evidence insufficient | 多阶段 Query 的 route/utility 对应关系和答案语义仍待人工裁决 | 不能据此关闭 Planner 或批准 Jev rollout |

## 预注册边界、身份和执行

运行前的 [PRD](./prd.md) 已冻结三项假设：Planner 在多阶段/证据依赖/时间演变/recovery Query 上应改善结果；在直接查找、计数、排序、聚合和普通摘要上若质量相同则开销是纯 overhead；错误 guidance 可能造成 regression。[Design](./design.md) 固定：两路都调用生产 `TrivaeApplication.query()`；`execution_override.forced_route` 绕过 Router 决策；planned 仅多一次当前 `SoftPlanner` 调用，将合法 Plan 作为 soft guidance 注入同一 Agent Runtime。Planner 不执行 Tool；Planner 失败按既有降级契约记录，不能冒充 Runtime 成功。

| 身份 | 冻结值 |
| --- | --- |
| Start commit / execution commit | `6fd7e93b8c73439069a5457980e2d31f2d42f880` / `f94fffb4d050d9c5b506480f6fce2a48a1921e96` |
| Dataset / Suite | 人工 GT 裁决的 `resume-benchmark-dev@v2`，37 Development Case，六个现有类别；Calibration 10 和已暴露 Holdout 不参与 |
| Snapshot | `snapshot-v1:messages=473236:first=1753011800000:last=1786847688000:sources=14:lexical={'present': True, 'message_count': 473236}`；FTS 473236 条；semantic `Qwen/Qwen3-Embedding-0.6B`、1024 维，完整 index identity 存于 local Environment manifest 和 Variant |
| Provider / Model | 官方 DeepSeek `deepseek/deepseek-flash`，base URL `https://api.deepseek.com`；主 Runtime 和 Planner 同一 Provider/Model，Jev Router 保持 `shadow` 且被 forced route 绕过 |
| Variant | [forced standard](../../../../../evaluation/variants/planner-utility-standard-20260925.json) / [forced planned](../../../../../evaluation/variants/planner-utility-planned-20260925.json)，配置仅 `execution_override.forced_route` 不同 |
| Runtime / Tool | `max_turns=8`、`max_tool_rounds=3`、`max_output_tokens=16384`、dynamic tool-result budget；7 个生产 Tool；相同 Retrieval、Evidence/Citation、context expansion 与 Evaluation identity |
| Planner 实际请求 | `temperature=0`、`max_tokens=2048`、JSON object mode、`reasoning_effort=low`；Trace 记录真实请求身份，Variant pin 生产实现与关键参数 |
| 本地 artifact | `data/evaluation/planner-utility/2026-09-25/final/` 下 Environment、preflight、独立 smoke/main/repeat raw 与 Evaluation SQLite、analysis；canonical Trace 保存在本地 SQLite；目录被 Git 忽略，不含版本控制的私有正文 |

从冻结 worktree 明确传入主仓库 `.env` 的绝对路径。正式第一条 Case 前，preflight 确认主模型/Planner Provider、数据库、Snapshot、lexical/semantic index、ExecutionScope、七个 Tool、37 条 GT、Variant 唯一差异、输出及 Evaluation DB create-only。`environment gate=4/4`；旧 `forced-standard.json` / `forced-planned.json` pin 旧 M6 身份，未复用。Provider 凭据只被检查为 configured，没有写入报告或 Git。初次仪表 smoke 曾遇连续连接错误；原始记录保留，独立 fresh-client 探针成功，但根因无法进一步确证。最终冻结代码的独立 4 Case × 2 路 smoke 为 8/8 completed，路径和 Planner Trace 符合预期；smoke 不计入主实验。

正式运行按 Case 交替 standard→planned，一次尝试，无覆盖重跑。`raw=74`、`Evaluation runs=74`、`Evaluation results=74`、`Trace=74`，37 个完整 pair；forced route、Planner invocation、Provider/Model、Snapshot 身份违例均为 **0**。74 条均有 `router.bypassed` 和 `router.decision`；planned 有 37 次 `planner.started/completed`，standard 为 0 次 Planner 调用；Router Provider 不参与。Trace、raw 与 Evaluation 均按 run/trace ID 一一对齐。

## 主实验：答案质量、可靠性和配对差异

`completed` 是 Query 终态，不能代替正式答案合法性：两路都 37/37 completed，但 finalization / citation 仍可能失败。下面的 `valid_answer` 是既有 AnswerArtifact 有效性指标，**不是事实正确率**。`evidence_recall` 只对有 GT evidence 的 27 Case、67 个目标/部分 reference 有效，**不是 corpus 全面 Recall**。

| 指标 | forced standard | forced planned | 边界 |
| --- | ---: | ---: | --- |
| Query completed | 37/37 | 37/37 | exception、Provider/Planner/Retrieval terminal failure 均为 0 |
| Finalization completed | 36/37 | 34/37 | failed 为 1 / 3 |
| Citation passed / degraded / failed | 34 / 2 / 1 | 33 / 1 / 3 | 与正式答案结果并列观察 |
| Valid Answer | 36/37 | 34/37 | 有效结构与 finalization，非语义正确性 |
| Evidence Recall | 48/67，27 Case | 57/67，27 Case | GT target/partial scope |
| Context Recovery | 0/3 | 2/3 | 极小样本 |
| Expected Fact coverage | 14/16 | 15/16 | 既有确定性 GT |
| Verified Zero Result | 3/4 | 0/4 | 四条为 GT 确认的真实空结果 |
| False Zero Result | 33/33 | 33/33 | 两路相同 |
| Temporal coverage status | 4/6 | 3/5 available | 分母不同，不直接相减 |
| Truncation accuracy | 4/6 | 4/6 | 两路相同 |

逐 Case 判定只对同一 Case 两侧均 available 的既有 GT 指标做 Pareto 比较：所有变化为正记 `better`，所有变化为负记 `worse`，全部相同记 `same`；相反方向混合须记 `mixed`，Provider 故障另记 `provider_confounded`。本次结果 **better 6 / same 26 / worse 5 / mixed 0 / unavailable 0**。`same` 仅表示这些可比较维度相同，不能把答案文字或真实任务完成判为等价；36/37 个 pair 的答案文本不同，差异已进入本地审阅包。

| 既有 GT 类别 | better / same / worse | 已观察解释 |
| --- | --- | --- |
| citation/evidence（6） | 1 / 5 / 0 | 个别 evidence recall 增加 |
| context recovery（3） | 2 / 1 / 0 | 小样本可能有条件收益 |
| exact lexical（10） | 3 / 7 / 0 | 多为 evidence target 变化，未必由 plan 导致 |
| semantic paraphrase（8） | 0 / 7 / 1 | 一例 evidence loss |
| temporal overview（6） | 0 / 5 / 1 | 一例 finalization failure |
| zero result（4） | 0 / 1 / 3 | 已确认空结果上的显著反向信号 |

具体 better：`dev-cite-comment-render`、`dev-context-archify`、`dev-context-mattpocock-2`、`dev-lexical-forge`、`dev-lexical-nanobot-wiki`、`dev-lexical-resume-miner`。具体 worse：`dev-para-written-test`、`dev-temporal-14d`、`dev-zero-empty-1/2/3`。按单项成对指标：evidence recall 6 better / 20 same / 1 worse（n=27）；valid answer 35 same / 2 worse；context recovery 2 better / 1 same；verified zero 3 worse / 1 same。不可用指标未被当作 0。

## Planner 行为、开销与 failure attribution

planned 路 Planner **37/37 成功，0 timeout、invalid output、Provider failure**，平均 4.05 steps；suggested tools 次数：lexical 37、semantic 36、recent 29、SQL 34、context 37、schema 25、members 11。Plan 是建议：其存在不等于 Runtime 使用了每一步。两路 first Tool 有 5/37 改变，完整 Tool sequence 有 27/37 改变，context Tool 次数有 9/37 改变，evidence count 有 25/37 改变；Tool rounds 均值 1.973→2.243，Tool calls 2.865→3.892，retrieval calls 2.595→3.216。这些是行为相关性，单次随机生成下不能把每个差异归因为 plan 的必然效果。

| 耗时与 Provider usage | standard | planned | paired / 边界 |
| --- | ---: | ---: | --- |
| 端到端 latency（ms，n=37） | mean 11,177；p50 10,322；p95 25,697 | mean 19,718；p50 19,188；p95 31,746 | B−A mean +8,541，p50 +7,552，p95 +17,874；all-attempted 与 completed-only 分母相同 |
| Planner call latency（ms） | 无 | mean 4,991；p50 4,701；p95 7,397 | 37/37；p50/p95 用 nearest rank |
| Runtime requests | 110 | 120 | 实际请求计数 |
| Runtime input / output / total tokens | 1,879,095 / 63,129 / 1,942,224 | 2,460,979 / 82,358 / 2,543,337 | Provider 返回字段，含 cached input |
| Planner input / output / total tokens | 无 | 16,144 / 35,759 / 51,903 | 37 次额外请求 |
| 合计 total tokens | 1,942,224 | 2,595,240 | +653,016（+33.62%）；cost 字段两路均 `unavailable`，不反推货币开销 |

平均端到端 latency 的 planned 增幅为 76.42%，超过单独 Planner call 平均时间；它还伴随更多 Runtime Tool 与 token。单次时序受 Provider 波动影响，不将差额全部归因于 Planner call 自身。

主实验没有 Planner generation failure；三例 planned 正式答案失败不能记成 Planner Provider 失败。`dev-temporal-14d` 的 planned finalization 为 `TIME_RANGE_MISMATCH`，额外使用 recent/SQL；两次 targeted repeat 双路均有效，故该回归不稳定。`dev-zero-empty-1/2` 的 GT 是指定 UTC 日期的真实空结果；主实验 standard 给出 no-result signature，planned 使用 SQL row evidence 并输出 claims，verified-zero 未通过。`dev-zero-empty-3` 的 planned 是 `INVALID_FINAL_OUTPUT`，standard 有效；它在三次配对中均为 worse。`dev-para-written-test` 主实验 planned evidence target 减少、first Tool 从 semantic 变 lexical，重复时方向消失。共同失败 `dev-zero-excalidraw` 两路 AnswerArtifact 均无效，不能归因给 Planner。其余 failure artifact 计数是 Evaluation 首个接受条件失败，不等于 run exception：standard context_missing 3、ranking_failure 5、retrieval_miss 8、coverage_error 2、answer_generation_error 1；planned 依次为 1、3、8、2、3。未观察到 terminal provider、retrieval 或 Planner failure。

## 独立 targeted repeat 与人工审阅

主结果后按预先保存的选择清单挑 6 个有方向差异、行为变化或潜在回归的 Case，每路再跑 2 次，共 **24 个额外 run**；raw / Evaluation runs / Evaluation results / Trace 均为 24。它们只用于局部稳定性，**不并入主 74-run 分母**。

| Case | main / repeat 1 / repeat 2 | 可支持的判断 |
| --- | --- | --- |
| `dev-context-archify` | better / better / same | context target 2/3 仅 planned 恢复；提示有条件价值，样本 1 Case |
| `dev-lexical-forge` | better / worse / same | evidence 收益不稳定，主实验 Tool sequence 甚至相同 |
| `dev-para-written-test` | worse / same / same | 单次 evidence regression 不稳定 |
| `dev-temporal-14d` | worse / same / same | 主实验 finalization regression 未复现 |
| `dev-zero-empty-1` | worse / better / worse | overall 方向受 standard 一次失败影响；planned verified-zero 三次均 0，standard 为 2/3 |
| `dev-zero-empty-3` | worse / worse / worse | standard valid + verified-zero 3/3，planned 两项均 0/3；稳定的局部 Failure Case |

只有 1/6 个选中 Case 在三次运行中保持同一 overall 方向；这是定向选择，不能估总体稳定率。主分析的本地 ignored `analysis/review-packet.json` 含 query、GT、两路答案、Evidence/Citation、Tool sequence、Planner 摘要及指标，供人工逐 claim 裁决；没有运行 Tier 2 Judge。自动建立的事实是上述 GT 指标、路径、行为、失败和开销；答案语义正确性、Planner 指导的逐步因果和 Judge-human agreement 均待人工审阅。

## Jev Router：两层证据与后续门槛

Layer 1 是已有 Jev route classification diagnostic：16 Case 经人工标为 8 standard / 8 planned，Jev 与 Existing LLM 的分类、延迟和 usage 已记录在 [Jev 实验报告](../09-25-openrouter-jev-router/experiment-report.md)。Layer 2 是本次 forced-path Planner treatment 的答案级 utility。Router 的 16 Case 只有 route-level contract，`data_snapshot={}`，没有绑定当前 Snapshot 的 CaseBundle final-answer GT；Development 37 Case 有答案 GT，却没有可信的逐 Case planned-worthy route 标签。因此不能将那 8 条 route 标签一一映射到本次 37 Case 的答案收益，也不能把 Jev 的 route accuracy 当成 Planner utility。

当前 Jev 继续 `shadow`。讨论切换之前，需要对真正 dependent multi-stage、证据依赖、时间演变和 recovery Query 建立独立人工答案 GT 与 utility 审阅，复核 Planner 回归（尤其 confirmed zero）、再测 Router 是否能识别**有实际收益**的 Query，并满足原 Router rollout 的误路由、availability、latency、usage/cost 门槛。

## Evidence boundary 与 artifact policy

**可声称**：在冻结代码、当前 Snapshot、官方 DeepSeek 和 37 条人工 GT Development Case 上，forced planned 提高了若干 evidence/context 自动指标，同时降低 valid-answer/verified-zero 指标并增加真实 latency/token；37×2 raw/Evaluation/Trace 对齐，Planner 37/37 调用成功。**不可声称**：fresh/blind/unseen 泛化、v1 sealed Holdout quality、v2 reused Holdout 的 blind quality、Router 的 8 个 planned Case 已证实答案受益、LLM Judge 人工事实准确率、所有 same Case 答案等价、Planner step 被 Runtime 执行或货币实测 cost。

本次所有 Provider raw、答案正文、Review packet 与 Trace 只在本地 ignored `data/evaluation/planner-utility/` 和 canonical DB；versioned 文件只有代码、Variant、协议和汇总统计，不包含密钥或私有正文。旧 benchmark 与 v1 Holdout artifact 未修改。
