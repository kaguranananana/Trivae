# Validation: resume-benchmark-v1 Stage 3

## Completion boundary

- Stage 3 status: **Complete / Gate 3 review complete / final freeze complete**；v1 Stage 4 registration、一次性 holdout run 和 final merge complete；复用 GT 的 v2 recovery validation 也已完成；当前等待 Gate 4 review。
- Final headline scope: Development only，37 cases × A/B/C/C2/D × 1 repetition = 185 runs。
- v2 recovery scope：复用原 18 条 holdout Case、GT 和 18/18 人工核验；结果单独报告，不冒充全新 blind holdout 或 v1 headline。
- calibration 10 cases 已排除 headline denominator；18 条 holdout 已全部人工确认并登记。正式 holdout 已运行一次并封存，但 90/90 run 均在设置校验阶段以 `SettingsError` exception 结束，没有可用答案或 holdout 质量指标；不得重跑 v1。
- 冻结后的 clean execution commit：`7bac9282701bd0c21b58ce8e5a4f5cc52c87da9f`。
- 根因修复后的 post-fix clean execution commit：`f24775099cb2314772c7d409341e8ebceeceac23`。
- Gate 2 freeze execution commit：`b1f7b78ba802f853f9cd1cbf7433fe07b2f895c1`；freeze metadata commit：`e34c6985a734eb2169e0a48e12a512270ca0c353`。
- Gate 3 candidate execution commit：`8805aa2bf58fcb2702817d54afe96bd819645db2`；候选结果只作为本轮人工 review 输入，不替换历史 baseline。
- Gate 3 final freeze：`data/evaluation/benchmark/gate3-final-freeze.json`；冻结 `execution_commit=8805aa2bf58fcb2702817d54afe96bd819645db2`，Development 37×5=185 pairs 完整。

## Gate / dataset validation

- `data/evaluation/benchmark/stage3-freeze-verification.json`：environment gate 4/4、freeze verification 12/12，全部 passed。
- `data/evaluation/benchmark/gt-audit-stage3-final.json`：47 cases、47 adjudicated、0 error、0 warning，passed。
- `trivae eval cases validate evaluation/cases/benchmark/dev`：37 个 versioned Case 全部 valid。
- `trivae eval cases validate evaluation/cases/benchmark/calibration`：10 个 versioned Case 全部 valid。
- `trivae eval benchmark gate ...`：canonical Snapshot、lexical index、semantic identity、Git commit 四项 passed。
- 最终 SQLite Evaluation Store：185 distinct run_id；五个 Variant 各 37 个 case。
- post-fix clean SQLite：185 distinct run_id；五个 Variant 各 37 个 case；对应 Trace 185 条、`context.prepared` 185 条。
- candidate Environment：`data/evaluation/benchmark/gate3-candidate-environment.json`；environment gate 4/4、Gate 2 freeze verification 12/12，全部 passed。
- candidate Development：`gate3-final-development-real/` 与独立 `gate3-final-development-evaluation.sqlite3`；raw / Evaluation SQLite / Trace 各 185 条，五个 Variant 各 37 条，Case×Variant coverage 185/185。
- Gate 3 人工 review：`data/evaluation/benchmark/gate3-review/review.md` 已完成 12 条核验（6 条 confirmed/confirmed_with_notes、2 条内容 fail、4 条无答案系统失败）；不将诊断抽样当总体质量率。
- Stage 4.0 holdout candidate：`scripts/generate_holdout_candidates.py` 生成 `data/evaluation/benchmark/holdout/` 下 18 条 Case、Suite、retrieval query 和本地 review packet；六类各 3 条，消息级 GT 不复用 dev/calibration，Case contract 全部 valid。
- Stage 4.0 人工 adjudication：`data/evaluation/benchmark/holdout/review.md` 的 18/18 条均为 `confirmed`；确定性复算覆盖 lexical/cite、zero、temporal、context、para，且 37 条 target/parent 消息与 Development packet 零重叠。Sea-BreakTheWaves 的额外纯文本消息不含 `Sea-Go/`，按 GT 原谓词正确排除。
- Holdout registration：`data/evaluation/benchmark/holdout-registration.json` 已生成，18 个有序 Case identity、完整 canonical configuration 与 adjudication provenance 均绑定到 Gate 3 freeze。
- Holdout final run：`data/evaluation/benchmark/holdout-run/` 与 `data/evaluation/benchmark/gate3-final-freeze-holdout-run.json` 已封存；raw 90、Evaluation SQLite 90、Trace 90，90 条均为 `exception`，异常类型为 `SettingsError`，failure artifact 90 条均为 `provider_failure`。
- Final merge：`data/evaluation/benchmark/final-report/` 已生成；raw 275（Development 185 + holdout 90），五 Variant 各 55，`full_available=true`。该字段只证明冻结 Environment/Variant identity 一致；holdout 质量矩阵为空，不产生 holdout headline。

## Evaluation artifacts

- 简历与面试事实索引：`evaluation/reports/resume-benchmark-v1-fact-index.md`；该文档只整理已存在的 Development baseline、post-fix measurement-substrate validation、系统 quality failure 与可写数字，不生成新的运行结果。
- Module retrieval：`data/evaluation/benchmark/stage3-module-retrieval.json`，27 个 query，保留 lexical / semantic 的 corpus 与 target scope、Recall@5/10、Hit@K、MRR@10 和 context observation。
- First real run：`data/evaluation/benchmark/stage3-first-real/`，185 条 provisional run 与 112 条 failure artifact。
- Targeted reruns：`data/evaluation/benchmark/stage3-targeted/`，stream A/C、C2 context、D temporal classification 均保留真实 production Query path 的 before/after 证据。
- 冻结后 final clean：`data/evaluation/benchmark/stage3-final-real/` 与 `data/evaluation/benchmark/stage3-final-evaluation.sqlite3`；raw records 185 条、failures 108 条、每个 Variant 37 条。该结果保留为根因修复前的质量基线。
- post-fix root-cause clean：`data/evaluation/benchmark/stage3-root-cause-final-clean-real/` 与 `data/evaluation/benchmark/stage3-root-cause-final-clean-evaluation.sqlite3`；raw / SQLite / Trace 均 185 条，每个 Variant 37 条，failure artifacts 146 条。
- Gate 3 candidate final Development：`data/evaluation/benchmark/gate3-final-development-real/` 与 `data/evaluation/benchmark/gate3-final-development-evaluation.sqlite3`；raw 185 条，138 条 completed、47 条 failed，failure artifacts 126 条；结果已完成人工 review 并绑定 final freeze。
- Gate 3 candidate Tier 2：`data/evaluation/benchmark/gate3-review/gate3-final-development-judge-d.json`；D 变体 37 条中 21 judged、5 skipped、11 failed，状态 `partial`；人工 packet 为 `data/evaluation/benchmark/gate3-review/review.md`，12 条已完成核验。
- Gate 3 holdout/final：`holdout-run/` 的 90 条 run 全部为 Query executor 的 `SettingsError` exception；`final-report/report.md` 保留 Development 指标、holdout 空质量矩阵和 90 条 provider failure，不把配置错误写成系统质量下降。
- Tier 1：`data/evaluation/benchmark/stage3-final-real/report.json` / `report.md`；包含分子/分母/rate/macro、unavailable reason、operational、paired comparison、failure analysis、freeze/environment identity。
- Tier 2：`data/evaluation/benchmark/stage3-final-judge-d.json`；8 条 LLM-assisted provisional judge，29 条 `judge_failed`，0 条 skipped，0 条 human adjudicated。
- Tier 2 audit queue：`data/evaluation/benchmark/stage3-final-judge-audit-queue.json`，37 条完整覆盖，状态为 pending human adjudication。

## Engineering checks

```text
.venv/bin/pytest -q                         → 596 passed
.venv/bin/ruff check src tests              → All checks passed
.venv/bin/mypy src                          → Success: no issues found in 112 source files
git diff --check                            → passed
```

## Failure-driven iteration result

- 已修复通用 streaming/model-behavior terminal projection、provider observation preservation、finalization failure classification、report denominator/operational/paired aggregation；regression 位于 `tests/test_agent_runtime.py` 与 `tests/test_benchmark.py`。
- targeted stream A/C 无 failure artifact；context recovery 和 temporal partial coverage 的剩余限制未被隐藏，仍在 final report 中按真实状态分类。
- 冻结后 baseline failure categories：provider_failure 9、coverage_error 18、context_missing 13、answer_generation_error 6、retrieval_miss 3、zero_result_error 2、not_observed_within_recorded_depth 57；未观察到 ranking_failure、router_tool_selection_error、evaluation_infrastructure artifact。
- post-fix clean failure categories：provider_failure 114、retrieval_miss 12、coverage_error 7、context_missing 4、ranking_failure 4、answer_generation_error 2、zero_result_error 3；`not_observed_within_recorded_depth=0`、`evaluation_infrastructure=0`、`router_tool_selection_error=0`。4 个 ranking failure 的 direct relevant hits 均在 rank 14–29，且 `hit_at_k_observable=true`，没有把 context expansion call 当作排名观测。

## Root-cause closure

- 评估分类缺陷已修复：旧 classifier 把多个 retrieval call 的 hit 全局合并排序，并把 context call 当 direct ranking；post-fix classifier 按单 call 保留 rank、排除 context，并区分 `ranking_failure` / `retrieval_miss` / `not_observed_within_recorded_depth`。
- benchmark lifecycle 缺陷已修复：旧 CLI 在同步 `Application` context 内对每个 Variant 分别 `asyncio.run`，provider client 在不同 loop 间使用并在关闭阶段触发 `Event loop is closed`；现在 CLI 使用 async Application context，所有 Variant 在同一 loop 运行并关闭。
- Holdout 运行根因：正式命令从冻结临时 worktree 启动；CLI 的默认 dotenv 只查当前目录，而该 worktree 没有 `.env`，所以所有 Query 在 `TRIVAE_MODEL_API_KEY` 校验阶段终止为 `SettingsError`。主仓库 `.env` 的配置可读，但一次性 claim 已完成，不能删除 claim、换输出目录或补配置重跑 v1；后续若继续实验，应创建新的冻结身份并在执行 worktree 显式传入 `--env-file`。
- 配置加载防复发修复：benchmark `run` 与 `run-holdout` 现在在创建 Application、写入 holdout claim 或遍历 Case 之前调用 `load_settings()`；缺少配置会只产生一次明确 `SettingsError`，不会再生成一批逐 Case 的伪 Provider failure。回归覆盖位于 `tests/test_cli.py`，并用无 `.env` 的 worktree 实际复现了“无 benchmark 输出目录、无 Evaluation SQLite”的 fail-fast 行为；显式 `--env-file` 的 CLI Case 校验已通过。
- post-fix 185 运行的 C/C2/D 大批量 failure 不是上述两项代码缺陷：C 为 5/37 completed、C2 为 0/37、D 为 0/37；全批次 114 条 terminal provider failure 中 C/C2/D 占 106 条。Trace 显示这些 terminal failures 为 `APITimeoutError`/`APIConnectionError`，并集中出现 `ROUTER_COMPLETION_TIMEOUT`，C2/D failure 没有首个 model turn。独立 recovery smoke 一条 D completed、一条 C2 provider failure，保留该外部 provider availability/timeout 事实，不添加 retry、fallback 或变体特判。
- 其他可观察 failure 保持语义透明：12 条 `retrieval_miss` 是 direct retrieval 中没有 GT relevant hit；7 条 `coverage_error` 是 completed run 但 coverage status 未被产出；4 条 `context_missing` 是 final evidence 缺少 GT required context；2 条 `answer_generation_error` 是 finalization contract failure；3 条 `zero_result_error` 是 GT 要求非空但模型给出 no-result signature。
- 数据完整性审计通过：candidate raw 185 = Evaluation SQLite 185 = Trace 185；failure artifact 与 report 一致。holdout raw 90 = Evaluation SQLite 90 = Trace 90，90/90 为同一设置异常；final merge raw 275，failure artifact 216 与两个 split 的报告保持一致。
- candidate 数据完整性审计通过：raw 185 = Evaluation SQLite 185 = Trace 185；distinct run_id 185；每条都有 `context.prepared`；failure artifact 126 条与报告分类一致。candidate 与历史 baseline 的 provider window 不同，不直接宣称质量改进。

## Stop boundary

- Gate 3 review：complete；6 条 confirmed/confirmed_with_notes、2 条内容 fail、4 条系统失败。
- candidate Development machine acceptance：complete；Gate 3 诊断 packet 已逐条核验，holdout candidate packet 18/18 confirmed。
- Holdout candidate generation / adjudication / registration：complete，Registration 已绑定 freeze。
- Holdout evaluation：complete as a sealed one-time run；90/90 `SettingsError` exception，holdout 质量指标 unavailable。
- Full benchmark merge：complete structurally；Development 185 + holdout 90 已合并，`full_available=true`，但不能从中抽取 holdout 质量数字。
- 本文件和其他文档不把本轮配置失败表述为 Trivae 质量下降；也不把结构性 full merge 当作 holdout 质量结论。后续修复配置后必须以新的 v2/fresh freeze 为起点。

## 2026-09-07 收尾工具与 provider check

- 新增 `benchmark/closure.py`：Gate 3 final freeze、冻结后 holdout registration、一次性 `started/completed/failed` claim、sealed report 校验，以及基于 raw records 的 dev/holdout/full 合并。CLI 已接入 `freeze-final`、`seal-holdout`、`run-holdout`、`merge-report`。
- 新增 closure contract 回归：freeze round-trip 与 git drift、holdout 重复 claim、sealed report、同身份 full 与异身份 `identity_mismatch`。Judge 回归覆盖证据 Tool error、provider 原文、损坏 JSON、partial exit code、OpenCode Go session header 和 final output budget。
- 当前工程检查：`.venv/bin/pytest -q` → **593 passed**；`.venv/bin/ruff check src tests` → passed；`.venv/bin/mypy src` → passed（112 source files）；`git diff --check` → passed。
- 换 key 后单条 Judge smoke 使用独立输出 `data/evaluation/benchmark/closure-review/judge-smoke-final-result.json`，1 条 run、9 个 atomic claims，Grounded Claim Rate 0.667、Citation Correctness 0.000，全部仍为 `llm_assisted_provisional`；没有人工升级，也没有覆盖历史 `stage3-final-judge-d.json`。
- 复测确认空 JSON 的直接根因是 Judge 误用 Router/Planner 的 2048 completion budget，返回 `finish_reason=length`；现改用 `max_output_tokens`，输出已完整。精确 provider 余额/配额仍不可从当前兼容 API 读取。
- （历史状态，已由下方 `2026-09-08 Holdout closure` supersede）Gate 3 freeze、holdout 生成/审核、一次正式 holdout 运行和 full 合并当时仍保持 pending；该历史段不作为当前状态。

## 2026-09-08 Gate 3 candidate preparation and completion

- `environment.py::_git_commit()` 现在先检查 `git status --porcelain --untracked-files=all`，脏 worktree 显式拒绝；被 `.gitignore` 排除的本地 Evaluation artifact 不影响 clean 判定。
- README 的最终 Development 示例改为独立的 `gate3-final-development-real/` 和 `gate3-final-development-evaluation.sqlite3`，并明确历史 `stage3-final-real/`（`7bac928`）不能与新 holdout 合并。
- 当前候选远端代码为 `8805aa2bf58fcb2702817d54afe96bd819645db2`；clean-worktree guard、独立 final-development 目录口径和 `freeze-final` 完整覆盖校验已提交。
- 候选 Environment 已在该 commit 的干净 worktree 捕获；environment gate 4/4、Gate 2 freeze verification 12/12 均 passed。
- 完整 Development 已完成：37 cases × 5 variants = 185 runs，raw / Evaluation SQLite / Trace 各 185 条；138 条 completed、47 条 failed，126 条 failure artifact 全部保留在报告与本地输出。
- D-only Tier 2 Judge 已完成 provisional 批次：21 judged、5 skipped、11 failed，输出 `status=partial`；人工 packet 已生成 12 条诊断抽样并完成核验。
- 当前停止点是 Stage 4 holdout closure 后的 Gate 4 review；registration、一次性运行和 final merge 已完成，90 条 holdout run 均为 `SettingsError` exception，v1 不重跑。

## 2026-09-08 Holdout closure

- 用户完成 18 条 holdout 的人工核验，全部 `confirmed`；确定性复算与消息隔离通过，GT 无需替换。
- `seal-holdout` 生成 registration；随后一次性 `run-holdout` 在冻结 commit `8805aa2` 上写出 90 条 raw / Evaluation SQLite / Trace，但所有 run 都因执行 worktree 未加载主仓库 `.env` 而成为 `SettingsError` exception。
- `merge-report` 已生成 `data/evaluation/benchmark/final-report/`；full 的 identity merge 可用，holdout 的质量矩阵和 Tier 2 答案不可用。claim、failure artifacts 和报告均不覆盖、不删除、不重跑。

## 2026-09-08 Holdout v2 recovery validation

- 用户明确要求复用原 18 条 holdout Case、GT 和人工核验；本轮不重新构造 Case、不修改 GT、不重新 adjudicate。
- 新建独立 `data/evaluation/benchmark/gate3-final-freeze-v2-recovery.json` 和 `data/evaluation/benchmark/holdout-registration-v2-recovery.json`；freeze 仍绑定同一 execution commit `8805aa2bf58fcb2702817d54afe96bd819645db2`，因此无需重跑 185 条 Development。
- 使用主工作区 `.env` 的显式 `--env-file` 启动 recovery run；`data/evaluation/benchmark/holdout-v2-recovery-run/` 的 90 条 raw、`holdout-v2-recovery-evaluation.sqlite3` 的 90 条 Evaluation run、Canonical Trace Store 的 90 条 Trace 完整对齐。
- 运行结果：90/90 run 已完成 claim；52 条 `completed`、38 条 `failed`；failure artifact 58 条，分类为 `provider_failure` 38、`retrieval_miss` 8、`answer_generation_error` 4、`coverage_error` 3、`zero_result_error` 3、`context_missing` 1、`ranking_failure` 1。
- `data/evaluation/benchmark/final-report-v2-recovery/` 已完成合并，`full_available=true`；该字段只表示 split identity 一致。由于 18 条 Case/GT/裁决已被用户和开发流程看到，本轮必须称为 **recovery validation / known holdout**，不能称为 unseen、blind 或独立 generalization 结果。
- v1 的 `holdout-run/`、claim 和 `final-report/` 保持原样；本轮没有 retry、补跑失败项或覆盖旧输出。
