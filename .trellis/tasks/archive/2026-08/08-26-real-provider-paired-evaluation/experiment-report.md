# Real Provider paired answer quality evaluation

## 1. 实验身份与继承关系

- Branch：`codex/dynamic-tool-result-budget-regression`。
- 本轮开始时产品代码 HEAD：`3e173c7`；没有创建分支、没有切换到 `main`、没有修改 `src/`。
- 继承归档任务：`.trellis/tasks/archive/2026-08/08-26-1m-context-budget-finalization/`。
- 继承文件：`benchmark.py`、`real_ab.py`、`experiment-report.md`、`validation.md` 和既有 SQLite Trace schema/data。
- Provider/model：`opencode-go / deepseek-v4-flash`。
- context：`1,000,000`，source=`verified_model_registry`。
- prompt、Scope、case 顺序和 3 次 repetition 完全沿用归档实验，共 4 prompt × 3 variant × 3 repetition = 36 cells。
- 本轮只把归档中的 `dynamic-run-256k` 改为不设置 override 的 `dynamic-default-250k`，验证产品默认路径。

原始 prompt 为：

1. `最近的这一个月之内，有没有讨论过一些有价值的 GitHub 仓库、Skills、有价值的一些资源之类的东西`
2. `最近一个月群里推荐过哪些 Agent 学习资料？`
3. `群里对 taste-skill 的评价是什么？有没有人实际用过？`
4. `最近两周讨论过哪些 DeepSeek 相关项目？`

## 2. Harness 修复与执行边界

归档 runner 的每个 cell 只有 30 秒，首轮 36 个 cell 中 32 个被 harness 截断；这描述的是观察窗口，不是 Provider 的回答质量。新 runner `real_ab.py` 使用：

- 每 cell `120s` OS-isolated worker timeout；
- 整个实验 `4500s`（75 分钟）absolute wall-clock deadline；
- parent 给 worker 的 timeout 是 cell limit 与剩余总预算的较小值；
- deadline 到达后剩余 cell 显式写为 `experiment_timeout`；
- timeout、Provider/runtime failure、completed 分开记录，不 retry、不合成 QueryResult、不生成质量样本。

实际运行命令：

```bash
.venv/bin/python .trellis/tasks/08-26-real-provider-paired-evaluation/real_ab.py \
  --summary-output /tmp/trivae-real-paired-v2-20260826.jsonl \
  --quality-dir /tmp/trivae-real-paired-v2-quality-20260826
```

实际运行在总 deadline 前结束；实验没有出现 `experiment_timeout`，但仍有 Provider/worker-level failures。原始 bounded summary 保留在 `/tmp/trivae-real-paired-v2-20260826.jsonl`，按当前 runner 的修正版 budget checker 从 Trace facts 复算后的本地摘要为 `/tmp/trivae-real-paired-v2-20260826-normalized.jsonl`；后者的 `quality_eligible` 才是本报告使用的字段。原始运行在 checker 修正前完成，因此原始 JSONL 中部分 completed 行的 eligibility 字段为旧逻辑结果；回答正文只保存在 `/tmp/trivae-real-paired-v2-quality-20260826/` 的 ReviewPacket 材料中，没有写入 git。

## 3. Cell inventory

| variant | planned | completed | cell timeout | runtime failed | quality-eligible completed |
| --- | ---: | ---: | ---: | ---: | ---: |
| `fixed-16k` | 12 | 10 | 2 | 0 | 10 |
| `dynamic-run-128k` | 12 | 11 | 1 | 0 | 11 |
| `dynamic-default-250k` | 12 | 6 | 4 | 2 | 6 |
| **total** | **36** | **27** | **7** | **2** | **27** |

所有 27 个 completed sample 都有完整 Trace、ReviewPacket 和当前 checker `budget_resolution_status=passed`。7 个 cell timeout、2 个 runtime failure 不进入回答质量分母。

## 4. 三个 variant 的 Trace-backed operational 结果

以下是 completed sample 的均值；`canonical / visible` 是 source/message item 数量，不是 token，也不是质量分数。Provider 提供 usage，因此 token 为实际 Trace usage；如果某 Provider 不提供 usage，runner 保持 `unavailable`，不会从 projection estimate 反推计费量。

| variant（n） | Retriever hits / returned messages | canonical / model-visible sources | omission（hit/context） | projection trunc. | calls / rounds | latency | total tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `fixed-16k` (10) | 61.4 / 115.1 | 122.3 / 115.4 | 6.9 / 0 | 3/10 | 2.2 / 1.4 | 58.5s | 34,901.8 |
| `dynamic-run-128k` (11) | 78.4 / 155.5 | 160.7 / 160.7 | 0 / 0 | 0/11 | 2.2 / 1.2 | 72.8s | 36,119.4 |
| `dynamic-default-250k` (6) | 22.5 / 65.5 | 72.7 / 72.7 | 0 / 0 | 0/6 | 2.0 / 1.3 | 36.6s | 25,046.5 |

补充事实：

- fixed 的 10 个 completed 中，6 个 Retrieval event 仍有 `partial/truncated`；3 个 sample 的 runtime projection 发生 truncation，其中 `agent_learning_materials/r2` 的 69 个 hit message 被省略。
- dynamic-128 的 11 个 completed 中，8 个 Retrieval event 标记为 partial/truncated，但 canonical 内容没有被 budget projection 省略；这说明本轮可见性收益不能被错误归因成 Retriever 已经完整。
- default-250 的 6 个 completed 中，3 个 Retrieval event 标记为 partial/truncated；同样没有 projection omission。
- citation binding 均值分别为 fixed `2.1`、dynamic-128 `1.2`、default `1.3`；validated citation 均值分别为 `9.9`、`7.7`、`5.3`。这两个字段的语义不同，不能合并为“引用质量分”。
- finalization：fixed `valid 10/10`；dynamic-128 `valid 10/11`、`degraded 1/11`；default `valid 6/6`。dynamic-128 的 degraded sample 仍保留用户回答，但出现一个 `UNRESOLVED_SOURCE_HANDLE`，丢弃 1 个 citation/field；这是 graceful finalization 的已记录行为，不足以证明新的产品 bug。
- route diagnostics：dynamic-128 有 3 个 completed sample、default 有 1 个 completed sample 带 `ROUTER_COMPLETION_TIMEOUT`，但仍产生 AnswerArtifact；这是 delivery/availability 事实，不作为回答质量优劣结论。

## 5. Run-level pool 是否实际绑定

本轮没有 completed sample 消耗到 run pool 上限：

| variant | completed 中最大累计 tool-result projection | 最小 observed remaining pool | 是否绑定 |
| --- | ---: | ---: | --- |
| fixed-16k | 33,114 | 不适用 | per-call fixed，不使用 run pool |
| dynamic-run-128k | 46,697 | 81,303 | 否 |
| dynamic-default-250k | 15,037 | 234,963 | 否 |

因此，`128k → 250k` 在这 27 个 completed sample 中没有触发可观察的 run-level 预算差异；更大的 pool 既没有减少 omission，也没有增加 model projection。default 的 6/12 完成率不能归因于 250k budget，因为未完成样本分别是 Provider runtime SSL error 或 cell timeout。

## 6. Paired completed samples 与人工质量材料

按同一 `case/repetition` 配对，得到：

- fixed vs dynamic-128：9 个 pair；
- dynamic-128 vs default-250：6 个 pair；
- fixed vs default-250：6 个 pair；
- 三个 variant 都完成的完整 triad：6 个（`agent_learning_materials/r2`、`deepseek_projects/r1-r3`、`taste_skill/r1-r2`）。

runner 复用了现有 `operational_measurements`、`query_result_snapshot` 和 `build_review_packet`。人工材料保留 answer artifact、citation bindings 和 bounded source snapshots；报告不把未建立 exhaustive Reference 的观察伪装成自动分数。

### 人工复核记录

对 6 个完整 triad 采用现有 Evaluation/ADR 的分轴语义：

| 质量轴 | 本轮结论 | 原因 |
| --- | --- | --- |
| enumeration completeness | `unknown` | 当前 case 没有 exhaustive Reference Findings；partial semantic index 也不能证明集合穷尽。 |
| evidence coverage | `partial` | 各答案都有可回查 source/citation，但 Retrieved/semantic coverage 本身多次标记 partial/truncated。 |
| obvious final-answer omission | `unknown` | 可以识别 projection 层 omission，不能仅凭当前 partial Reference 判定最终答案遗漏全集。 |

按 case 的材料观察：

- `agent_learning_materials`：dynamic-128 在 `r1/r2` 展开了更多学习资料；fixed `r2` 则出现 69 个 hit message 的 projection omission。不同 repetition 的 Retriever 结果差异很大，不能把这两组回答直接当成只由 budget 引起的稳定质量提升。
- `taste_skill`：dynamic/default 的材料更明确呈现了实际使用反馈与输出批评；fixed 的一轮更谨慎地区分“有人表达使用意图”和“确认完成测试”。这属于答案选择/证据可得性的可复核差异，但没有 exhaustive reference 来判定哪一项遗漏了完整讨论。
- `deepseek_projects`：三种预算在多次 repetition 都覆盖 DeepSeek Harness、V4 Pro、codex-deepseek-subagent/API 等核心项目；不同 repetition 的项目集合和回答组织方式变化，没有稳定的 variant winner。
- `github_skills_resources`：default 没有 completed pair；fixed/dynamic-128 都给出代表性仓库、Skills 或资源，但侧重点不同，无法据此判定枚举完整度。

这些结论是人工可复核材料的定性记录，不是自动 Judge 分数；本轮不创建第二套评分框架，也不为了显示 dynamic 优势修改 prompt、case 或 rubric。

## 7. Failure / Trace inventory

关键 completed Trace：

| 场景 | Trace ID | 观察 |
| --- | --- | --- |
| fixed `agent_learning_materials/r2` | `trace-7a53daa930ef42a48326d7111b8e29ec` | 69 hit messages omitted，projection truncation；可用于 fixed 基线 omission 复核。 |
| fixed `github_skills_resources/r3` | `trace-0c6da3f8b8024b05a98c89591b5e4696f` | 4 calls / 2 rounds，fixed per-call projection truncation。 |
| dynamic-128 `github_skills_resources/r2` | `trace-241e8641adfb4cd6850d6cd20f490aa2` | canonical/model-visible 均 193，budget omission 为 0。 |
| dynamic-128 `agent_learning_materials/r3` | `trace-cc991785e7cd4ef59b0c604014ba109d` | `completed_degraded`，`UNRESOLVED_SOURCE_HANDLE`，用户回答保留。 |
| default-250 `agent_learning_materials/r2` | `trace-8c203dcf39904f99b5c0016de8919f9f` | default dynamic completed，projection omission 为 0。 |
| default-250 `agent_learning_materials/r1` | `trace-d2e5efbbf0af48c1a764526cc91c92e6` | Provider `SSLError` runtime failure，finalization 未运行，不是质量样本。 |

timeout/open Trace：

- fixed：`trace-8c31233df4514a6897df0dc9ea6829eb`（github/r1）、`trace-106932d3f5d946c685ec5d14d73cec78`（agent/r3）。
- dynamic-128：`trace-6e6a06377b71454b9d8d450eb80f3005`（taste/r3）。
- default-250：`trace-233dd7e49a5842aca07a951c7451e99a`、`trace-81ba79995f3b4d3fb8250866c9ba74ea`、`trace-8be2e12b72ec4c429e2a408e458b7dd8`（github/r1-r3）、`trace-37d94704d08c4fe9bc75f7d768a88c36`（taste/r3）。

另一个 default Provider failure 是 `trace-5546764a2d844b8cac64606fbd3c620f`（`agent_learning_materials/r3`，同为 `SSLError`）。两个 runtime failure 均没有 AnswerArtifact/finalization，不进入质量分母。

## 8. 结论

### 16k → dynamic 128k

本轮确认了真实的 operational projection 改善：fixed 样本出现 3/10 projection truncation，且有一个样本省略 69 个 hit message；dynamic-128 的 11 个 completed sample 没有 budget omission/truncation，并且 canonical 内容全部保持 model-visible。可是，最终回答质量的提升尚未被证明：只有 9 个 fixed/dynamic-128 pairs、6 个完整 triad，Retriever coverage 是随机且经常 partial，缺少 exhaustive Reference，人工材料没有显示跨 repetition 的一致 winner。

结论：**dynamic 128k 带来可观测的证据可见性改善，但本轮不能据此声称最终用户回答质量已经稳定提升。**

### dynamic 128k → 当前默认 250k

本轮 128k 和 250k run pool 都没有绑定；完成样本中没有 omission/truncation 差异，也没有形成更大 pool 带来答案质量收益的证据。default-250 的样本量更小，且缺少 github completed pair，不能用它的较低均值 latency/token 推断质量或效率优势。

结论：**更大的 run pool 在本轮 workload 上没有继续产生可证明收益。**

### 当前默认预算是否合理

1M context 下 `dynamic-default-250k` 的 Trace 解析正确，per-call ceiling 仍为 128k；250k 是有明确上限的 headroom，当前没有证据要求下调，也没有证据把它宣传成质量提升来源。**当前默认预算合理地保留，但只应视为待压力场景验证的 operational 配置，不是已校准的质量最优值。**

## 9. Remaining failure cases 与下一步

1. 单独处理 Provider/harness 可用性：default 的两个 `SSLError` 和 7 个 cell timeout 需要从 Provider transport、请求耗时分布和 runner 资源隔离继续定位；不能把它们改写成回答质量失败，也不应无依据添加 retry/fallback。
2. 增加真实的多-call、大 projection case，使 dynamic run pool 实际累计接近并超过 128k；只有 pool 真的绑定后，才能评估 128k→250k 的边际价值。
3. 为 4 个既有 Case 建立 versioned `Reference Finding` / `Case Bundle`，明确 exhaustive、partial 或 unknown provenance，再进行 blind paired review；在此之前继续保持 `unknown/partial`，不伪造 completeness score。
4. 保留 fixed-16k 作为 regression/debug control；后续重点关注 `UNRESOLVED_SOURCE_HANDLE` 等 graceful-finalization degraded 样本，并将其按现有 Failure Diagnosis 生命周期判断是否需要产品修复。本轮没有 completed Trace 证明预算产品代码违反契约，因此没有修改 `src/`。
