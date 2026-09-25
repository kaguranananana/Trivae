# `resume-benchmark-v1` 最终 Evaluation 事实索引

> 更新日期：2026-09-25。只汇总已有报告、raw records、Evaluation SQLite、Trace、冻结记录与人工 review；本次没有重跑 benchmark 或重算历史结果。

## 0. Gate 4 结论

- `resume-benchmark-v1` 的 Gate 4 文档与证据收口通过；Task 按 Trellis workflow 归档。
- 历史 Development quality baseline 仍是 clean execution commit `7bac9282701bd0c21b58ce8e5a4f5cc52c87da9f` 的 **37 cases × 5 variants × 1 repetition = 185 runs**。
- Gate 3 candidate execution commit `8805aa2bf58fcb2702817d54afe96bd819645db2` 的 185 条 Development run 是冻结前人工核验输入；它没有取代 `7bac928` baseline。
- v1 Holdout 是一次性 sealed run：**90/90 `SettingsError`，quality unavailable**。合并报告的 `full_available=true` 只证明 split identity 一致，不表示 Holdout quality 可用。
- v2 recovery 使用已暴露的同一组 Holdout Case/GT：**90 runs，52 completed、38 failed**。它属于 known/reused holdout recovery validation，不是 blind、unseen 或 fresh generalization。
- Tier 2 Judge 输出未人工逐条 adjudicate，所有成功判定仍为 `llm_assisted_provisional`；本索引不把它写成事实正确率。

## 1. Benchmark 生命周期

```text
47 条人工裁决 GT
├── Calibration 10（schema / measurement substrate 校准；不进 headline）
└── Development 37
    └── Gate 2 frozen Development baseline：7bac928，37×5=185 runs
        └── measurement substrate post-fix validation：f247750，独立验证，不改写 baseline

Gate 3 candidate Development：8805aa2，37×5=185，完成 review 与 final freeze
↓
freeze 后生成 Holdout 18，18/18 人工确认并登记
↓
v1 Holdout：18×5=90 SettingsError → sealed；quality unavailable
↓
独立 v2 recovery：复用同一已暴露 Holdout；90 runs，52 completed / 38 failed
↓
Gate 4：结果边界、面试证据、问题记录核对完成；Task archive
```

## 2. Dataset / Freeze / Variant

| Split | Case 数 | 状态与作用 |
|---|---:|---|
| Human GT 总数 | 47 | 47/47 adjudicated；Accept 26、Modify 21、Reject 0 |
| Development | 37 | 六类：exact_lexical 10、citation_evidence 6、semantic_paraphrase 8、context_recovery 3、temporal_overview 6、zero_result 4 |
| Calibration | 10 | 用于 schema / measurement substrate 校准，不计入正式 Development headline denominator |
| v1 Holdout | 18 | Gate 3 freeze 后生成；六类各 3；18/18 人工确认并登记。Case/GT 后续已被流程看过 |

Snapshot / Environment identity：canonical Snapshot 为 `snapshot-v1:messages=473236:first=1753011800000:last=1786847688000:sources=14`；lexical FTS 有 473236 rows；semantic identity 为 Qwen/Qwen3-Embedding-0.6B、1024d、last-token pooling、normalized、chunker v1。Gate 2 freeze verification 为 12/12 passed，environment gate 为 4/4 passed。`DatasetSnapshot` 描述 canonical data；index identity、execution commit 与 benchmark metadata 由 Environment/freeze artifact 承载。

五个 Variant 的含义：

| Variant | 控制差异 | 可归因对照 |
|---|---|---|
| A `bench-lexical-only-v1` | lexical；context limit 0 | minimal control |
| B `bench-lexical-semantic-v1` | A + semantic；context limit 0 | B−A：semantic surface |
| C `bench-semantic-ctx-v1` | B + production auto context | C−B：自动 context expansion |
| C2 `bench-semantic-ctx-tool-v1` | C + `get_message_context` | C2−C：显式 context tool |
| D `bench-full-system-v1` | 七个 Agent-facing tools | 与 A/B/C/C2 是多变量比较 |

正式运行经过 production `TrivaeApplication.query()` path，使用真实 Provider。baseline 的历史 Provider 是 `opencode-go / deepseek-v4-flash`；2026-09-11 的 Provider migration 不改写旧 Environment 或结果。

## 3. Development baseline：可追溯实测结果

来源：`data/evaluation/benchmark/stage3-final-real/report.json` 与 `report.md`。表中指标为 weighted rate（numerator/denominator；case-macro；可用 case n）。这是 `7bac928` 的冻结 Development baseline，不是 Holdout。

| Variant | Execution completed | Valid answer | Evidence recall | Context recovery | Expected fact answer coverage | False-zero guard | Verified zero |
|---|---:|---:|---:|---:|---:|---:|---:|
| A lexical-only | .811 (30/37; .811; n=37) | .757 (28/37; .757; n=37) | .800 (44/55; .733; n=20) | .000 (0/3; .000; n=3) | 1.000 (14/14; 1.000; n=14) | 1.000 (26/26) | .000 (0/4) |
| B lexical+semantic | .973 (36/37; .973; n=37) | .919 (34/37; .919; n=37) | .738 (48/65; .641; n=26) | .000 (0/2; .000; n=2) | .875 (14/16; .875; n=16) | 1.000 (32/32) | 1.000 (4/4) |
| C + auto context | .973 (36/37; .973; n=37) | .946 (35/37; .946; n=37) | .742 (49/66; .638; n=26) | .333 (1/3; .333; n=3) | .938 (15/16; .938; n=16) | .969 (31/32) | 1.000 (4/4) |
| C2 + explicit context tool | 1.000 (37/37; 1.000; n=37) | .973 (36/37; .973; n=37) | .642 (43/67; .574; n=27) | .000 (0/3; .000; n=3) | .750 (12/16; .750; n=16) | .970 (32/33) | 1.000 (4/4) |
| D full-system | 1.000 (37/37; 1.000; n=37) | 1.000 (37/37; 1.000; n=37) | .731 (49/67; .694; n=27) | .000 (0/3; .000; n=3) | .938 (15/16; .938; n=16) | 1.000 (33/33) | 1.000 (4/4) |

- False-zero guard 的 1.000 表示可用的非空 GT cases 没有输出 false no-result；它不是错误率。
- Verified zero 的 1.000 表示真实空结果 case 输出了可验证 no-result。
- Evidence Recall 使用 GT target，不等于 corpus retrieval Recall；partial GT 只按 target/pool scope 解释。
- Expected Fact Answer Coverage 只数规范化 alias 命中 `answer_text` 的 extractive facts。
- Coverage status 在 A/B/C/C2 有 6 条 unavailable；D 为 4/6=.667。Truncation accuracy 依次为 A .333 (2/6)、B .500 (3/6)、C .500 (3/6)、C2 .500 (3/6)、D .667 (4/6)。

### 3.1 Ablation 结果边界

- **B−A**：completion 和 valid answer 均增加 .162；paired evidence recall rate −.075、macro −.079，paired n=19。semantic 是互补通道，没有全面质量 uplift 证据。
- **C−B**：context recovery +.500，但 paired n=2；evidence recall rate +.000、macro −.023，paired n=25。样本小，不支持稳定 context uplift。
- **C2−C**：context recovery −.333，paired n=3；evidence recall rate −.091、macro −.042，paired n=26。没有显式 context tool 的稳定 uplift 证据。
- D 是多变量 full-system variant；D−A 不能归因给某一个组件。

### 3.2 Module retrieval

来源：`data/evaluation/benchmark/stage3-module-retrieval.json`，27 个 Development query：10 个 exhaustive/corpus，17 个 partial/target。

| Strategy | Scope | Recall@10 | Hit@10 | MRR@10 |
|---|---|---:|---:|---:|
| lexical | corpus，10 exhaustive queries / 33 relevant items | 1.000 (33/33; macro 1.000) | 1.000 (10/10) | 1.000 (10/10) |
| semantic | corpus，10 exhaustive queries / 33 relevant items | .364 (12/33; macro .327) | .600 (6/10) | .550 (5.5/10) |
| lexical | target，17 partial queries / 31 target items | .742 (23/31; macro .529) | .529 (9/17) | .426 (7.25/17) |
| semantic | target，17 partial queries / 31 target items | .323 (10/31; macro .284) | .412 (7/17) | .281 (4.778/17) |

Lexical 的 33/33 只支持这 10 个可枚举 predicate query 的 corpus Recall@10，不外推到任意问题。该结果不证明 semantic 全面优于 lexical；module packet 的 context expansion positive recovery 为 lexical 0/3、semantic 0/3，样本不足以证明 production context uplift。

## 4. v1 sealed Holdout

| 项目 | 已核验事实 |
|---|---|
| Registration | Gate 3 freeze 后登记 18 个 ordered Case identity 与 canonical config；18/18 人工确认 |
| Raw records | 90；五 Variant 各 18；90/90 status=`exception` |
| Evaluation Store | `holdout-evaluation.sqlite3`：90 `evaluation_runs`、90 `evaluation_results` |
| Trace | 90 个 trace_id，90 个对应 Trace 文件存在 |
| Failure artifact | 90；分类值均为 `provider_failure`，底层异常为 `SettingsError` |
| Quality result | unavailable：没有 Provider request、Answer 或可评分 Holdout quality value |
| Sealed state | claim=`completed`；final report raw 275（Development 185 + Holdout 90）；五 Variant 各 55 |

根因：正式命令从冻结临时 worktree 启动；CLI 默认只从当前目录读取 `.env`，worktree 缺少主仓库 `.env`，因此 `TRIVAE_MODEL_API_KEY` 在 Query settings validation 时缺失。它是 execution/configuration failure，不是 retrieval quality regression，也不是 Provider timeout/connection window。

后续入口已在创建 Application/claim 前预检 settings；冻结 worktree 执行时显式使用 `--env-file PATH`。v1 claim 和产物不删除、不换目录、不补配置重跑。Final report 的 `full_available=true` 只表示 Development/Holdout environment 与 variant identity 可合并；Holdout quality matrix 仍为空。

## 5. v2 recovery validation（known/reused Holdout）

- Identity 使用独立 recovery freeze、registration、claim、raw output 与 Evaluation SQLite；执行 commit 仍是 `8805aa2`。
- 复用 v1 的 18 条 Case、GT 和已完成的 18/18 人工核验，按 5 variants 共执行 90 runs；raw / Evaluation SQLite / Trace 均为 90。
- 实测：52 completed、38 failed。58 个 failure artifacts：provider_failure 38、retrieval_miss 8、answer_generation_error 4、coverage_error 3、zero_result_error 3、context_missing 1、ranking_failure 1。
- `full_available=true` 仍仅表示 split identity 合并。Case/GT 已暴露，所以不能称为 blind、unseen、fresh holdout 或 independent generalization benchmark。

## 6. Gate 3 candidate 与 Tier 2 记录

Gate 3 candidate Development 来源：`gate3-final-development-real/report.json`。commit 为 `8805aa2`；raw / Evaluation SQLite / Trace 各 185；138 completed、47 failed，failure artifacts 126。这个 provider run/window 与 `7bac928` 不同，不能与历史 baseline 宣称质量改善。

D-only Tier 2 Judge 来源：`gate3-final-development-judge-d.json`，37 条中 21 judged、5 skipped、11 failed，batch `partial`。所有成功判定与 239 个 atomic claims 保持 `llm_assisted_provisional`；0 个 claim 标为人工 adjudicated。Gate 3 的 12 条人工答案 review 不等于 claim-level Judge review，也没有生成 judge-human agreement / audit pass rate。

Gate 3 `packet.json` 的 `pending_human_review` 与 `review.md` 内已记录的人工核验结果不一致。该元数据产物未被改写；本索引以人工 review 文档和 Task validation 的记录说明答案 review 已发生，同时明确它没有升级 Judge 状态。

## 7. Failure attribution / substrate evidence

post-fix clean run (`f247750`) 的 raw / Evaluation SQLite / Trace 均为 185，failure artifacts 146：provider_failure 114、retrieval_miss 12、coverage_error 7、context_missing 4、ranking_failure 4、answer_generation_error 2、zero_result_error 3。114 条 provider failure 中 106 条集中在 C/C2/D，Trace 记录 `APITimeoutError` / `APIConnectionError` 与 `ROUTER_COMPLETION_TIMEOUT`；不用于这些 variant 的 retrieval/answer quality 结论。

四个 `ranking_failure` 已在 direct retrieval 内观察到 GT relevant hits，但 rank 为 14–29；`not_observed_within_recorded_depth=0`。根因修复分别是保留 per-call direct rank 并排除 context call，以及让 benchmark Application/provider request/close 在同一 event loop。证据见 `benchmark-root-cause-closure.md` 与 `tests/test_benchmark.py` / `tests/test_cli.py`。

## 8. Benchmark 能证明什么 / 不能证明什么

**有证据支持：**

- 建立并人工裁决 versioned GT / Case / Suite；明确 Development、Calibration、冻结后 Holdout 的身份与分母。
- 将 Snapshot 与 Environment 分开冻结，检查 canonical count、lexical index、semantic identity 和 execution commit。
- 在相同快照下对 A/B/C/C2/D 做 production `TrivaeApplication.query()` ablation；把 single-variable 对照与 full-system multi-variable 差异分开。
- 关联 raw run、Evaluation Store、Trace 和 failure artifacts；v1 Holdout 的 90 条记录，以及 Development/post-fix 的 185 条记录均有对应链路。
- 将 evaluation measurement substrate 问题与 Retrieval/Answer quality 问题拆分；保留 provider/configuration failure 的真实语义。
- 执行一次性 sealed Holdout，并保留失败事实；v2 recovery 独立于 v1 claim。

**没有证据支持：**

- 线上 SLA、跨数据分布 generalization 或独立 fresh holdout 质量结论。
- v1 Holdout quality rate（90/90 SettingsError）；`full_available=true` 不能替代它。
- v2 recovery 是 blind/unseen/fresh holdout。
- Semantic retrieval 全面优于 lexical；auto context 或 explicit context tool 有稳定 uplift。
- Provider timeout 等同于 Retrieval regression，或 SettingsError 等同于系统回答错误。
- D 的 valid AnswerArtifact rate 等同于 factual correctness；Tier 2 provisional Judge 等同于人工验证。

## 9. 简历可用的 measured facts（推荐 3 条）

1. **Production-path Evaluation 可追溯性**
   - Metric：raw / Evaluation runs / Evaluation results / 对应 Trace 各 **185/185**；37 Development cases × 5 variants × 1 repetition。
   - Split / identity：Gate 3 candidate Development acceptance；execution identity `gate3-final-development`。历史 Development quality baseline 仍单独固定为 `7bac928`，不由 candidate 替换。
   - Execution commit：`8805aa2bf58fcb2702817d54afe96bd819645db2`。
   - GT completeness：47/47 adjudicated（Development 37、Calibration 10）；本 candidate 只跑 Development，Calibration 不进分母。
   - Scope / limitation：单一 canonical Snapshot 下的真实 `TrivaeApplication.query()` runs；证明 candidate 的运行与审计链，不代表 Holdout、线上 SLA 或事实正确率。
   - Evidence：`gate3-final-development-real/report.json`、raw records、`gate3-final-development-evaluation.sqlite3`、对应 Trace、`gt-audit-stage3-final.json`。历史 baseline quality source 是 `stage3-final-real/report.json`，execution commit `7bac9282701bd0c21b58ce8e5a4f5cc52c87da9f`。

2. **Freeze / Environment identity gate**
   - Metric：Environment gate **4/4** passed；Gate 2 freeze verification **12/12** passed。
   - Split / identity：`resume-benchmark-v1` Gate 2 frozen Development identity；随后用于固定 37-case Development baseline。
   - Execution commit：freeze verification identity `b1f7b78ba802f853f9cd1cbf7433fe07b2f895c1`；baseline quality run commit `7bac9282701bd0c21b58ce8e5a4f5cc52c87da9f`。
   - GT completeness：47/47 adjudicated；37 Development cases 被 baseline 测量，10 Calibration cases 排除。
   - Scope / limitation：这是冻结前置条件核验，不是质量分数；只证明记录的 Snapshot、索引、GT、Environment 与 Variant 身份通过检查。
   - Evidence：`stage3-freeze-verification.json`、`resume-benchmark-v1-freeze.json`、baseline `report.json`、`gt-audit-stage3-final.json`。

3. **Failure diagnosis 可定位性**
   - Metric：post-fix **4/185 runs** 出现已观察到 relevant hit 但 rank 超出 Hit@10 的 `ranking_failure`；rank 14–29，`not_observed_within_recorded_depth=0`；raw / Evaluation / Trace 各 185 条。
   - Split / identity：37-case Development 的 post-fix measurement-substrate / failure-attribution validation，不是 baseline quality replacement。
   - Execution commit：`f24775099cb2314772c7d409341e8ebceeceac23`。
   - GT completeness：47/47 adjudicated；本次 failure audit 使用 37 Development cases 的 acceptance conditions。
   - Scope / limitation：展示 failure classification 与 Trace 可定位性，不是 Retrieval quality uplift；同批次另有 114 个 Provider failures，不据此推导系统质量回退。
   - Evidence：`stage3-root-cause-final-clean-real/report.json`、`failures/failures.json`、对应 Evaluation SQLite / Trace、`benchmark-root-cause-closure.md`。

**面试中可解释但不推荐做简历 headline：** lexical 在 `stage3-module-retrieval.json` 的 10 个 exhaustive/corpus query 上 Recall@10 为 33/33；artifact 保存了 Snapshot、QuerySet 与 Variant identity，但没有保存 execution commit，因此不把它作为 commit-pinned headline。该范围不外推到任意自然语言 query。

**不能写的 claim：** v1 Holdout quality rate；v2 blind/unseen/fresh generalization；semantic 全面提升；context 稳定收益；“185 次 Holdout run”；`D 37/37 valid answer` 等同于事实正确；任何未人工 adjudicate 的 Judge rate 是 human-verified。

## 10. Interview defense

20 个追问与事实证据映射见 [interview-defense.md 的 `resume-benchmark-v1` Gate 4 章节](../../.trellis/spec/project/interview-defense.md)。其中必须保持的边界：Calibration 不进入 headline；GT completeness 决定 corpus/target scope；v1 是 sealed SettingsError；v2 是 known/reused recovery；semantic/context uplift 不稳定；provider/configuration failure 不归成回答质量；Judge 保持 provisional。
