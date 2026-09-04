# `resume-benchmark-v1` Evaluation 事实索引

> 更新日期：2026-09-04。本文是脱敏的文档型索引，只引用仓库已有的 Evaluation、Trace、SQLite 和 Git 证据；不包含聊天正文，也不产生新的 benchmark 运行。

## 0. 结论先行

- 当前边界是 **Stage 3 Complete / Ready for Gate 3**。
- 可作为 Development quality baseline 的是冻结后的 `7bac928` clean run：Development 37 cases × A/B/C/C2/D 五个 Variant × 1 repetition = **185 次真实运行**。
- `f247750` 之后的 clean run 只用于验证两个 **Evaluation / measurement substrate bug** 的修复和 failure attribution 的可解释性；其中 C/C2/D 出现 provider timeout/connection window，不能替代 baseline，也不能重新推导 ablation quality。
- Human GT 为 **47/47 adjudicated**：Accept 26、Modify 21、Reject 0；其中 Development 37，Calibration 10。Calibration 不进入 headline denominator。
- Holdout 当前不存在：未生成、未查看、未评测。因此本文不声称 unseen、holdout 或 generalization result。

## 1. 证据地图与审计结果

| 事实 | 证据 | 审计结论 |
| --- | --- | --- |
| GT 人工裁决 | `data/evaluation/benchmark/gt-audit-stage3-final.json` | 47 cases、47 adjudicated、0 error、0 warning，passed |
| Gate / freeze | `data/evaluation/benchmark/stage3-freeze-verification.json`、`evaluation/snapshots/resume-benchmark-v1-freeze.json` | freeze verification 12/12 passed；environment gate 4/4 passed |
| Development baseline | `data/evaluation/benchmark/stage3-final-real/report.json`、`report.md` | 以 `7bac928` 为 execution commit，185 runs，作为冻结后的质量 baseline |
| Post-fix validation | `data/evaluation/benchmark/stage3-root-cause-final-clean-real/report.json`、`report.md` | 185 runs，主要验证 failure attribution 和 Application lifecycle；不作为 ablation quality 结论 |
| Module retrieval | `data/evaluation/benchmark/stage3-module-retrieval.json` | 27 个 Development retrieval query；exhaustive 使用 corpus scope，partial 使用 target scope |
| Failure root cause | `.trellis/spec/project/problems/benchmark-root-cause-closure.md`、`43d282e`、`f247750` | 两个测量层缺陷已修复；系统 quality failure 仍保持可见 |
| Regression / engineering checks | `tests/test_benchmark.py`、`tests/test_cli.py`、任务 `validation.md` | 全量 pytest 576 passed；ruff、mypy、diff check passed |

Environment 的 canonical Snapshot 为 `snapshot-v1:messages=473236:first=1753011800000:last=1786847688000:sources=14`；lexical FTS 为 473236 rows；semantic index 为 Qwen/Qwen3-Embedding-0.6B、1024d、last-token、normalized、chunker v1。五个 Variant 使用相同 provider/model/prompt 条件，差异由可用工具和 context override 明确表达。

## 2. Dataset / Variant / 可追溯性

### 2.1 Dataset 与 freeze

| 项目 | 已验证事实 | 简历边界 |
| --- | --- | --- |
| Human GT | 47/47 adjudicated；Accept 26 / Modify 21 / Reject 0 | 可以写“建立并人工裁决 47 条 GT”；不能省略其中 Development/Calibration 划分 |
| Development | 37 cases，六类覆盖：exact_lexical 10、citation_evidence 6、semantic_paraphrase 8、context_recovery 3、temporal_overview 6、zero_result 4 | 必须写 Development；不能写 unseen/holdout |
| Calibration | 10 cases，作为 schema/measurement substrate 校准 slice | 不进入 headline denominator |
| Holdout | 目录不存在，未生成、未查看、未评测 | 不能声称 generalization 或 holdout 结果 |
| 冻结 | Gate 2 freeze record 已提交；环境 gate 4/4、freeze verification 12/12 | 可以写可复现的 Snapshot/Environment freeze 机制 |

### 2.2 五个 Variant

| Variant | 配置差异 | Ablation 解释 |
| --- | --- | --- |
| A `bench-lexical-only-v1` | lexical_search；`context_window_limit=0` | minimal control |
| B `bench-lexical-semantic-v1` | A + semantic_search；`context_window_limit=0` | B−A 是 semantic surface 的单变量对照 |
| C `bench-semantic-ctx-v1` | B + production default auto context expansion | C−B 是自动 context expansion 的单变量对照 |
| C2 `bench-semantic-ctx-tool-v1` | C + `get_message_context` | C2−C 是显式 context tool 的单变量对照 |
| D `bench-full-system-v1` | 七个 Agent-facing tools | 与 A/B/C/C2 的差异是多变量 full-system 差异，不用于单组件归因 |

每个 Variant 37 cases；A/B/C/C2/D 合计 185 runs。运行经过 production `TrivaeApplication.query()` path，使用真实 `opencode-go / deepseek-v4-flash` provider，不是 mock。

可追溯性复核结果：post-fix raw records 为 185 条；post-fix Evaluation SQLite 的 `evaluation_runs` 和 `evaluation_results` 均为 185 条，每个 Variant 37 条；canonical Trace Store 中与 raw record 对应的 Trace 为 185 条，`context.prepared` 为 185 条。对应证据为 `data/evaluation/benchmark/stage3-root-cause-final-clean-real/raw-records.json`、`data/evaluation/benchmark/stage3-root-cause-final-clean-evaluation.sqlite3` 和本地 `data/trivae.sqlite3`。

## 3. 冻结后的 Development quality baseline

### 3.1 Tier 1 指标总表

来源统一为 `data/evaluation/benchmark/stage3-final-real/report.json` / `report.md`。格式为 `加权 rate (numerator/denominator；case-macro；n)`：加权 rate 保留事实条目分母，case-macro 是 case 等权均值，`n` 是该指标可用的 case 数。Provider/runtime 未完成的条件指标不会被放入条件分母，原因保留为 unavailable。

| Variant | execution completed | valid answer | evidence recall | context recovery | expected fact answer coverage | false-zero guard | verified zero |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A lexical-only | .811 (30/37；.811；n=37) | .757 (28/37；.757；n=37) | .800 (44/55；.733；n=20) | .000 (0/3；.000；n=3) | 1.000 (14/14；1.000；n=14) | 1.000 (26/26) | .000 (0/4) |
| B lexical+semantic | .973 (36/37；.973；n=37) | .919 (34/37；.919；n=37) | .738 (48/65；.641；n=26) | .000 (0/2；.000；n=2) | .875 (14/16；.875；n=16) | 1.000 (32/32) | 1.000 (4/4) |
| C + auto context | .973 (36/37；.973；n=37) | .946 (35/37；.946；n=37) | .742 (49/66；.638；n=26) | .333 (1/3；.333；n=3) | .938 (15/16；.938；n=16) | .969 (31/32) | 1.000 (4/4) |
| C2 + explicit context tool | 1.000 (37/37；1.000；n=37) | .973 (36/37；.973；n=37) | .642 (43/67；.574；n=27) | .000 (0/3；.000；n=3) | .750 (12/16；.750；n=16) | .970 (32/33) | 1.000 (4/4) |
| D full-system | 1.000 (37/37；1.000；n=37) | 1.000 (37/37；1.000；n=37) | .731 (49/67；.694；n=27) | .000 (0/3；.000；n=3) | .938 (15/16；.938；n=16) | 1.000 (33/33) | 1.000 (4/4) |

指标释义：

- `false-zero guard` 的 1.000 表示非空 GT case 没有输出 false no-result；它不是“错误率 100%”。`verified zero` 的 1.000 表示真实空结果 case 输出了可验证的 no-result。
- `evidence recall` 是最终 evidence 对 GT target 的命中率，不等于 corpus recall；partial/target GT 使用 target scope。
- `expected fact answer coverage` 只统计有明确 alias、且 alias 命中 `answer_text` 的 extractive fact；evidence 中出现但答案没有写出不算命中。
- `coverage_status_accuracy` 在 A/B/C/C2 因 Host-owned coverage artifact 有 6 条 unavailable；D 为 4/6 = .667。`truncation_accuracy` 分别为 A 2/6 = .333、B 3/6 = .500、C 3/6 = .500、C2 3/6 = .500、D 4/6 = .667。

### 3.2 单变量 paired comparison

来源为同一 baseline report 的 `cross_variant.comparisons`。这些结果用于解释实验边界，不作为“稳定提升百分比”的简历数字。

| 对照 | 可引用的真实结果 | 解读 | 简历 |
| --- | --- | --- | --- |
| B−A semantic | execution completed +.162（36/37 vs 30/37）；valid answer +.162（34/37 vs 28/37）；evidence recall paired rate −.075、macro −.079，paired n=19 | semantic 与 lexical 互补，但不是所有 Development query 的全面质量提升 | 不推荐写 uplift 百分比 |
| C−B auto context | context recovery +.500，paired n=2；evidence recall rate +.000、macro −.023，paired n=25；valid answer +.027 | context recovery 样本太小，收益不稳定 | 不应写“显著提升” |
| C2−C explicit context tool | context recovery −.333，paired n=3；evidence recall rate −.091、macro −.042，paired n=26；valid answer +.027 | 本轮没有支持显式 context tool 的稳定 uplift | 不推荐写提升比例 |
| D vs others | D 是七工具 full-system，多变量差异 | 只能报告绝对结果，不能把 D−A 归因给某一个组件 | 不写单组件因果结论 |

### 3.3 Module-level retrieval

来源为 `data/evaluation/benchmark/stage3-module-retrieval.json`，共 27 个 query：10 个 exhaustive/corpus、17 个 partial/target。MRR 的 numerator 是 reciprocal-rank 之和，不是消息数量。

| Strategy | GT scope | Recall@10 | Hit@10 | MRR@10 | 是否适合简历 |
| --- | --- | ---: | ---: | ---: | --- |
| lexical | corpus（10 queries；33 relevant items） | 1.000（33/33；macro 1.000） | 1.000（10/10） | 1.000（10/10） | 有条件：必须写 exhaustive/corpus predicate |
| semantic | corpus（10 queries；33 relevant items） | .364（12/33；macro .327） | .600（6/10） | .550（5.5/10） | 不作为全面质量提升证据 |
| lexical | target（17 queries；31 target items） | .742（23/31；macro .529） | .529（9/17） | .426（7.25/17） | 面试诊断可用，简历慎用 |
| semantic | target（17 queries；31 target items） | .323（10/31；macro .284） | .412（7/17） | .281（4.778/17） | 面试诊断可用，简历慎用 |

因此更准确的面试表述是：lexical 对可确定枚举的精确谓词表现稳定，semantic 为互补检索通道；不能把 semantic 写成全面优于 lexical。Module packet 的 context-expansion observation 为 lexical 0/3、semantic 0/3 positive recovery，样本不足且不代表完整 production context uplift。

### 3.4 运维诊断轴

D baseline 的 measured facts 为：latency mean 31,942.757 ms、P50 26,691 ms、P95 68,299 ms；tool calls mean 2.108、P50 2、P95 5；tool rounds mean 1.568、P50 1、P95 3；input tokens total 1,602,065、output tokens total 55,714、total tokens 1,657,779。它们只描述本地 Snapshot、当前 provider/model 和本次 Development run，不是生产 SLA，不建议放入简历主 bullet。

## 4. Post-fix validation：只验证 measurement substrate

### 4.1 目的与运行完整性

post-fix clean artifact 为 `data/evaluation/benchmark/stage3-root-cause-final-clean-real/`，execution commit 为 `f247750`；独立 Evaluation SQLite 为 `data/evaluation/benchmark/stage3-root-cause-final-clean-evaluation.sqlite3`。它验证 failure attribution 与 Application/provider lifecycle 修复，不能覆盖冻结 baseline。

| Variant | completed | 说明 |
| --- | ---: | --- |
| A | 31/37 | 仍有 provider failure，但可用于观察分类链 |
| B | 35/37 | 仍有 provider failure，但可用于观察分类链 |
| C | 5/37 | provider timeout/connection window，不能作为 C quality 结果 |
| C2 | 0/37 | provider timeout/connection window，不能作为 C2 quality 结果 |
| D | 0/37 | provider timeout/connection window，不能作为 D quality 结果 |

114 条 `provider_failure` 中有 106 条来自 C/C2/D；Trace 中集中出现 `APITimeoutError`、`APIConnectionError` 和 `ROUTER_COMPLETION_TIMEOUT`，且 C2/D 没有首个 model turn。独立 recovery smoke 中 D 曾完成、C2 仍有一次 provider failure，因此应表述为 provider availability observation，不增加 retry、fallback 或 Variant 特判。

### 4.2 Failure attribution 结果

post-fix failure artifact 共 146 条。下表是 observation 分类，不是一个可以直接换算成系统质量成功率的分母：

| Category | Count | 归因与解释 |
| --- | ---: | --- |
| provider_failure | 114 | provider/runtime terminal failure；本批次主要是外部 availability window |
| retrieval_miss | 12 | completed direct retrieval 中没有 GT relevant hit；召回能力问题 |
| coverage_error | 7 | completed run 未产出 GT 要求的 Host-owned coverage status；coverage/行为问题 |
| context_missing | 4 | final evidence 缺少 GT required context；证据保留/上下文使用问题 |
| ranking_failure | 4 | GT relevant hit 已被 direct search 观察到，但全部 rank > Hit@10；排序问题 |
| answer_generation_error | 2 | finalization contract 未生成有效 AnswerArtifact |
| zero_result_error | 3 | GT 要求非空，但答案输出 no-result signature |
| `not_observed_within_recorded_depth` | 0 | post-fix 没有把记录深度不足误报成 ranking/retrieval 结论 |
| `evaluation_infrastructure` | 0 | 本批次未观察到 Evaluation infrastructure failure artifact |
| `router_tool_selection_error` | 0 | 本批次未观察到该分类 |

4 个 `ranking_failure` 的 direct relevant ranks 为：

| Case | Observed rank | 共同事实 |
| --- | --- | --- |
| `dev-lexical-deepseek-harness` | 15–17 | direct lexical call；`hit_at_k_observable=true` |
| `dev-lexical-nanobot-wiki` | 23、26、29 | direct lexical call；`hit_at_k_observable=true` |
| `dev-lexical-resume-miner` | 18–26 | direct lexical call；`hit_at_k_observable=true` |
| `dev-lexical-vibe-game` | 14、20、22 | direct lexical call；`hit_at_k_observable=true` |

### 4.3 两个 Evaluation / measurement substrate bug

#### Bug A：Failure Attribution

旧 classifier 把多个 retrieval call 的 direct hit 全局混合后排序，丢失单次调用内部 rank；context expansion call 也可能被当成 direct ranking observation，于是 `retrieval_miss`、`ranking_failure` 和 `not_observed_within_recorded_depth` 的边界不可靠。

修复后，per retrieval call 保留 `rank`、`tool_call_id`、`strategy` 和 `message_id`；`strategy=context` 被排除出 direct ranking；只有 GT relevant hit 已被观察到且 rank 超过 10 才记为 `ranking_failure`；真正没有 relevant hit 才记为 `retrieval_miss`；记录深度不足才记为 `not_observed_within_recorded_depth`。`43d282e` 与 `tests/test_benchmark.py` 提供 regression；post-fix 真实结果为 4 个 ranking failure、rank 14–29、not observed 0。

#### Bug B：Benchmark Provider Lifecycle

旧 CLI 在同步 Application context 内对每个 Variant 分别 `asyncio.run`，同一个 async provider client 因此跨 event loop 使用，Application close 也可能在不同 loop 中发生，最终触发 `Event loop is closed`。

修复后，benchmark 主入口 async 化；所有 Variant 在同一个 event loop 内完成 Application enter、provider request、run projection 和 Application exit；保留同步 wrapper，但由 CLI 使用 async Application context。`f247750` 与 `tests/test_cli.py` 的 lifecycle regression 提供证据；全量 pytest 为 576 passed，ruff、mypy、diff check 均通过。

这两项应定义为 **Evaluation / measurement substrate bug**，不是 `Trivae retrieval algorithm bug`。它们修复的是“如何测量和归因”，没有修改 GT、Variant 或 Retrieval quality behavior。

## 5. Trivae 自身仍存在的 quality failure

以下问题不能因 measurement substrate 修复而被宣称已经解决。它们是当前下一阶段优化空间；本轮不调参、不加 reranker/query rewrite/fusion，也不重新跑 Development benchmark。

| Failure | 准确定义 | 当前证据 | 下一步边界 |
| --- | --- | --- | --- |
| `retrieval_miss` | GT relevant message 在 recorded direct retrieval 中没有出现 | post-fix 观察到 12 条；baseline 仍有 3 条明确 retrieval miss | 召回能力问题；不要与排序失败混称 |
| `ranking_failure` | GT relevant message 已被 direct retrieval 召回，但落在 Hit@10 之后 | post-fix 观察到 4 条，rank 14–29 | 排序质量问题；不要写成“没有召回” |
| `context_missing` | final evidence 没有包含 GT required context | baseline 13 条；post-fix 4 条，但 post-fix 受 provider window 影响 | context selection / evidence preservation 问题 |
| `coverage_error` | GT 声明 coverage expectation，但 Artifact 没有匹配的 Host-owned coverage status | baseline 18 条；post-fix 7 条 | temporal coverage / projection 行为问题 |
| `zero_result_error` | GT 要求非空，但模型输出 no-result signature | baseline 2 条；post-fix 3 条 | no-result calibration / answer behavior 问题 |
| `answer_generation_error` | runtime completed 但 finalization contract 没有有效 AnswerArtifact | baseline 6 条；post-fix 2 条 | Answer/Citation finalization 问题 |

baseline 中的 `not_observed_within_recorded_depth=57` 属于旧分类时代的 recorded-depth 结果，不能直接改名为 retrieval miss 或 ranking failure；post-fix 的 per-call projection 才提供了上述 12/4 的可解释 attribution。反过来，post-fix 的 114 条 provider failure 也不能计入 Trivae quality failure。

## 6. 简历可写数字清单

| 数字/事实 | 是否推荐写简历 | 推荐表达 | 证据路径 | 风险/限制 |
| --- | --- | --- | --- | --- |
| 47 条人工 GT | 推荐 | “整理并完成 47 条人工裁决 GT（Development 37、Calibration 10）” | `data/evaluation/benchmark/gt-audit-stage3-final.json` | Calibration 不进入 headline denominator；不是 47 条 holdout |
| 37 条 Development case | 推荐 | “在 37 条 Development case 上建立固定评测集” | `data/evaluation/benchmark/stage3-final-real/report.json` | 必须保留 Development 标签 |
| A/B/C/C2/D 五个 Variant | 推荐 | “设计 lexical/semantic/context/full-system 五 Variant ablation” | `evaluation/variants/`、baseline report | D 是多变量 full-system |
| 185 次真实 production-path evaluation | 推荐 | “通过 production `TrivaeApplication.query()` 完成 37×5=185 次真实 provider 运行” | baseline raw/report、Evaluation SQLite | 1 repetition；不是 holdout/generalization |
| Gate/freeze 机制 | 推荐 | “用 Snapshot/Environment gate 固定数据、索引和运行版本，并通过 freeze verification 12/12、environment gate 4/4” | `stage3-freeze-verification.json`、`resume-benchmark-v1-freeze.json` | 是可复现性证据，不是质量准确率 |
| raw / SQLite / Trace 对齐 185 条 | 推荐 | “保留 run→Evaluation Store→Trace 的 185 条可追溯链路” | post-fix raw、Evaluation SQLite、`data/trivae.sqlite3` | Trace 正文不进入仓库；强调可追溯而非业务收益 |
| lexical corpus Recall@10 = 33/33 | 有条件推荐 | “在 10 个 exhaustive/corpus predicate query 上，lexical Recall@10 为 33/33” | `data/evaluation/benchmark/stage3-module-retrieval.json` | 只限 corpus/exhaustive scope；不能泛化为全系统 Recall |
| 4 个 ranking failure，rank 14–29 | 推荐用于诊断型 bullet | “可将排序失败定位到具体 direct rank（14–29）” | post-fix `failures.json`、`benchmark-root-cause-closure.md` | 这是可定位性证据，不是“质量提升 4%” |
| 全量 pytest 576 passed | 推荐 | “补充 lifecycle/attribution regression 后全量 pytest 576 passed，ruff/mypy/diff check 通过” | 任务 `validation.md`、`tests/test_benchmark.py`、`tests/test_cli.py` | 工程质量事实，不是线上 SLA |
| D baseline valid answer 37/37 | 有条件，不单独写 | 只能写成“Development delivery baseline 中 D 为 37/37 valid AnswerArtifact” | `stage3-final-real/report.json` | valid answer 是交付/契约指标，不等于回答事实正确；不能省略 Development |
| D baseline false-zero guard 33/33 | 有条件，面试优先 | “在 33 个可用非空 case 中没有 false no-result” | baseline report | 不覆盖所有 case；不是 general accuracy |
| B−A evidence recall −.075、C−B context +.500、C2−C −.333 | 不推荐 | 面试中说明“对照评估显示收益不稳定” | baseline report `cross_variant` | paired n 分别为 19、2、3；不能包装成稳定 uplift |
| post-fix provider_failure 114 | 不推荐作为质量数字 | 只能说明“出现 provider availability window，未被归因到系统质量” | post-fix report、Trace | C/C2/D 占 106 条；不能写成 Trivae 质量下降 |
| Tier 2 grounded/citation judge | 不推荐 | “Tier 2 保持 provisional，等待人工 adjudication” | `stage3-final-judge-d.json`、audit queue | 仅 8 条 judged、29 条 judge_failed、0 条人工确认 |
| Holdout / generalization | 不应写 | “本轮未测量” | freeze/report metadata | Holdout 未生成、未查看、未评测 |

## 7. 简历项目描述候选

1. **建立高噪声群聊 Agent 的可复现 Evaluation Harness**：固定 Snapshot、Environment 和人工 GT，设计 A/B/C/C2/D 五个 Variant，在 37 条 Development case 上完成 185 次真实 production-path evaluation，并把运行结果、Evaluation Store、Trace 与 failure artifact 关联起来。
   **Evidence:** `data/evaluation/benchmark/stage3-final-real/report.json`、`data/evaluation/benchmark/stage3-freeze-verification.json`、`evaluation/snapshots/resume-benchmark-v1-freeze.json`

2. **构建 failure-driven diagnosis 链路**：保留每次 retrieval call 的 rank、tool_call_id、strategy 和 message_id，排除 context call 对 direct ranking 的干扰，将“未召回”与“已召回但 rank 14–29”拆分；post-fix 真实运行定位出 4 个 ranking failure，且 `not_observed_within_recorded_depth=0`。
   **Evidence:** `43d282e`、`src/trivae/evaluation/benchmark/failures.py`、`tests/test_benchmark.py`、`data/evaluation/benchmark/stage3-root-cause-final-clean-real/failures/failures.json`

3. **修复 Evaluation provider lifecycle**：将 benchmark runner async 化，让五个 Variant 在同一 event loop 内完成 Application enter、provider request 和 exit，并加入 lifecycle regression；post-fix raw/Evaluation/Trace 均保持 185 条可对齐记录，全量 pytest 576 passed。
   **Evidence:** `f247750`、`src/trivae/evaluation/benchmark/orchestrator.py`、`src/trivae/interfaces/cli.py`、`tests/test_cli.py`、`data/evaluation/benchmark/stage3-root-cause-final-clean-evaluation.sqlite3`

4. **用分层 GT scope 做 lexical/semantic 对照评估**：对 27 个 retrieval query 按 exhaustive/corpus 与 partial/target 分开统计 Recall@10、Hit@10、MRR@10；结果显示 lexical 在 10 个 exhaustive/corpus predicate query 上达到 Recall@10 33/33，semantic 作为互补通道而非全面替代。
   **Evidence:** `data/evaluation/benchmark/stage3-module-retrieval.json`、`data/evaluation/benchmark/stage3-final-real/report.json`

## 8. Interview Defense（16 个事实型追问）

1. **为什么要自己做 Evaluation Harness？** 高噪声群聊 Agent 的最终答案同时受检索、上下文保留、模型输出、provider 和运行时影响；只看最终答案无法定位问题。Harness 将固定 Snapshot/GT/Variant、EvaluationRun、Trace、failure attribution 和可比指标串成可复现证据链。
2. **47 条 GT 是怎么来的？** 当前仓库保留的是人工 adjudication 后的 versioned GT suite：47/47 已裁决，其中 Accept 26、Modify 21、Reject 0；Development 37，Calibration 10。具体 case identity 和要求以 `gt-audit-stage3-final.json` 及冻结 artifact 为准，不把未留存的过程细节补写成事实。
3. **为什么 Calibration 不计入正式结果？** Calibration 用来校准 schema 和 measurement substrate，不代表正式 Development 质量样本；把它混入 headline denominator 会把校准数据和被测结果混在一起。因此正式 baseline 只用 37 条 Development case。
4. **为什么需要 Gate 2 Freeze？** 它锁定 Snapshot、索引、GT、Environment、Variant configuration 和运行身份，使 A/B/C/C2/D 的差异可解释；本轮 freeze verification 为 12/12，environment gate 为 4/4。
5. **5 个 Variant 分别比较什么？** A 是 lexical control；B 在 A 上加入 semantic search；C 再加入 production default auto context expansion；C2 再加入 `get_message_context`；D 是七个 Agent-facing tools 的 full-system candidate。D 与前四者是多变量差异，不能做单组件因果归因。
6. **为什么不能只看最终答案正确率？** completion/valid answer 只能说明运行和输出契约是否完成，不能区分 relevant message 没召回、召回后排名过低、context 没保留、coverage artifact 缺失、provider 失败或答案生成失败，所以还要看 evidence、context、zero-result、Trace 和 failure category。
7. **Recall@K、MRR、Evidence Recall 分别说明什么？** module Recall@K 衡量 GT relevant item 是否进入前 K；Hit@K 衡量 query 是否至少命中一个；MRR 还反映第一个命中的位置；Evidence Recall 衡量最终答案保留的 evidence 对 GT target 的命中。后者不是 corpus retrieval Recall，partial/target scope 不能和 exhaustive/corpus 混算。
8. **Semantic 有没有稳定提升？** 没有足够证据支持全面提升。Module-level lexical 在 exhaustive/corpus predicate query 上 Recall@10 为 33/33，semantic 为 12/33；端到端 B−A 虽然 completion/valid answer 各上升 .162，但 paired evidence recall 为 −.075（n=19）。更准确的结论是 semantic 是互补通道。
9. **Context expansion 有没有稳定提升？** 没有。C−B 的 context recovery 只在 paired n=2 上为 +.500，C2−C 在 paired n=3 上为 −.333，evidence recall 方向也不稳定；只能说完成了对照评估并保留限制。
10. **Failure-driven analysis 发现了什么？** 先发现 failure attribution 把多个 retrieval call 全局混合，无法保留单次 rank；修复后 post-fix 真实运行出现 4 个可定位的 ranking failure，rank 为 14–29，`not_observed_within_recorded_depth=0`，并保留 retrieval/context/coverage/answer/zero-result 等剩余问题。
11. **`retrieval_miss` 和 `ranking_failure` 有什么区别？** `retrieval_miss` 是 GT relevant message 没出现在 recorded direct retrieval；`ranking_failure` 是 relevant message 已经被 direct retrieval 观察到，但 rank 超过 Hit@10。本轮不能把后者笼统称为“没召回”。
12. **这轮为什么修 Evaluation Bug，而不是 Retrieval Bug？** 本轮目标是先让测量和归因可信。Bug A 修复 per-call rank 与 context 排除，Bug B 修复跨 event loop 的 provider lifecycle；这些修复没有改变 GT、Variant 或 Retrieval behavior，剩余 retrieval/ranking/context 问题被显式保留下来供下一阶段处理。
13. **provider timeout 为什么不能算 Variant 质量下降？** post-fix 的 114 条 `provider_failure` 中 106 条集中在 C/C2/D，Trace 记录 `APITimeoutError`、`APIConnectionError` 和 `ROUTER_COMPLETION_TIMEOUT`，C2/D 没有首个 model turn；这是 availability window，不能重新推导 ablation quality。
14. **为什么现在没有 Holdout？** 用户范围明确要求本轮停止 Evaluation 扩展；当前 Holdout 未生成、未查看、未评测，Stage 3 只收口 Development 并保持 Ready for Gate 3。
15. **没有 Holdout，这些数据能证明什么、不能证明什么？** 它能证明在冻结 Snapshot/Environment/GT 下，37 条 Development case 的可复现 baseline、Variant 对照边界、运行可追溯性和 failure diagnosis；不能证明 unseen、holdout、generalization 或线上 SLA。
16. **如果之后继续做，Holdout 的作用是什么？** 在 Development 调整结束后，用独立 case、独立 GT 和固定评测协议测量未参与调参的数据，检查泛化与回归；Holdout 结果应单独报告，不能回填或替代本轮 Development baseline。
