# Validation: resume-benchmark-v1 Stage 3

## Completion boundary

- Stage 3 status: **Complete / Ready for Gate 3**。
- Final headline scope: Development only，37 cases × A/B/C/C2/D × 1 repetition = 185 runs。
- calibration 10 cases 已排除 headline denominator；holdout absent，未生成、未查看、未评测。
- 冻结后的 clean execution commit：`7bac9282701bd0c21b58ce8e5a4f5cc52c87da9f`。
- 根因修复后的 post-fix clean execution commit：`f24775099cb2314772c7d409341e8ebceeceac23`。
- Gate 2 freeze execution commit：`b1f7b78ba802f853f9cd1cbf7433fe07b2f895c1`；freeze metadata commit：`e34c6985a734eb2169e0a48e12a512270ca0c353`。

## Gate / dataset validation

- `data/evaluation/benchmark/stage3-freeze-verification.json`：environment gate 4/4、freeze verification 12/12，全部 passed。
- `data/evaluation/benchmark/gt-audit-stage3-final.json`：47 cases、47 adjudicated、0 error、0 warning，passed。
- `trivae eval cases validate evaluation/cases/benchmark/dev`：37 个 versioned Case 全部 valid。
- `trivae eval cases validate evaluation/cases/benchmark/calibration`：10 个 versioned Case 全部 valid。
- `trivae eval benchmark gate ...`：canonical Snapshot、lexical index、semantic identity、Git commit 四项 passed。
- 最终 SQLite Evaluation Store：185 distinct run_id；五个 Variant 各 37 个 case。
- post-fix clean SQLite：185 distinct run_id；五个 Variant 各 37 个 case；对应 Trace 185 条、`context.prepared` 185 条。

## Evaluation artifacts

- 简历与面试事实索引：`evaluation/reports/resume-benchmark-v1-fact-index.md`；该文档只整理已存在的 Development baseline、post-fix measurement-substrate validation、系统 quality failure 与可写数字，不生成新的运行结果。
- Module retrieval：`data/evaluation/benchmark/stage3-module-retrieval.json`，27 个 query，保留 lexical / semantic 的 corpus 与 target scope、Recall@5/10、Hit@K、MRR@10 和 context observation。
- First real run：`data/evaluation/benchmark/stage3-first-real/`，185 条 provisional run 与 112 条 failure artifact。
- Targeted reruns：`data/evaluation/benchmark/stage3-targeted/`，stream A/C、C2 context、D temporal classification 均保留真实 production Query path 的 before/after 证据。
- 冻结后 final clean：`data/evaluation/benchmark/stage3-final-real/` 与 `data/evaluation/benchmark/stage3-final-evaluation.sqlite3`；raw records 185 条、failures 108 条、每个 Variant 37 条。该结果保留为根因修复前的质量基线。
- post-fix root-cause clean：`data/evaluation/benchmark/stage3-root-cause-final-clean-real/` 与 `data/evaluation/benchmark/stage3-root-cause-final-clean-evaluation.sqlite3`；raw / SQLite / Trace 均 185 条，每个 Variant 37 条，failure artifacts 146 条。
- Tier 1：`data/evaluation/benchmark/stage3-final-real/report.json` / `report.md`；包含分子/分母/rate/macro、unavailable reason、operational、paired comparison、failure analysis、freeze/environment identity。
- Tier 2：`data/evaluation/benchmark/stage3-final-judge-d.json`；8 条 LLM-assisted provisional judge，29 条 `judge_failed`，0 条 skipped，0 条 human adjudicated。
- Tier 2 audit queue：`data/evaluation/benchmark/stage3-final-judge-audit-queue.json`，37 条完整覆盖，状态为 pending human adjudication。

## Engineering checks

```text
.venv/bin/pytest -q                         → 576 passed
.venv/bin/ruff check src tests              → All checks passed
.venv/bin/mypy src                          → Success: no issues found in 111 source files
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
- post-fix 185 运行的 C/C2/D 大批量 failure 不是上述两项代码缺陷：C 为 5/37 completed、C2 为 0/37、D 为 0/37；全批次 114 条 terminal provider failure 中 C/C2/D 占 106 条。Trace 显示这些 terminal failures 为 `APITimeoutError`/`APIConnectionError`，并集中出现 `ROUTER_COMPLETION_TIMEOUT`，C2/D failure 没有首个 model turn。独立 recovery smoke 一条 D completed、一条 C2 provider failure，保留该外部 provider availability/timeout 事实，不添加 retry、fallback 或变体特判。
- 其他可观察 failure 保持语义透明：12 条 `retrieval_miss` 是 direct retrieval 中没有 GT relevant hit；7 条 `coverage_error` 是 completed run 但 coverage status 未被产出；4 条 `context_missing` 是 final evidence 缺少 GT required context；2 条 `answer_generation_error` 是 finalization contract failure；3 条 `zero_result_error` 是 GT 要求非空但模型给出 no-result signature。
- 数据完整性审计通过：raw 185 = Evaluation SQLite 185 = Trace 185；failure artifact 与 report 一致；holdout 目录 absent，未生成、未查看、未评测。

## Stop boundary

- Gate 3 review：pending。
- Holdout generation / evaluation：未执行。
- Full benchmark：未执行。
- 本文件和其他文档只记录已完成的 Development Evaluation，不把结果表述为 unseen 或 holdout 结果；post-fix C/C2/D provider failure window 不用作 ablation quality 结论。

## 2026-09-07 收尾工具与 provider check

- 新增 `benchmark/closure.py`：Gate 3 final freeze、冻结后 holdout registration、一次性 `started/completed/failed` claim、sealed report 校验，以及基于 raw records 的 dev/holdout/full 合并。CLI 已接入 `freeze-final`、`seal-holdout`、`run-holdout`、`merge-report`。
- 新增 closure contract 回归：freeze round-trip 与 git drift、holdout 重复 claim、sealed report、同身份 full 与异身份 `identity_mismatch`。Judge 回归覆盖证据 Tool error、provider 原文、损坏 JSON、partial exit code、OpenCode Go session header 和 final output budget。
- 当前工程检查：`.venv/bin/pytest -q` → **593 passed**；`.venv/bin/ruff check src tests` → passed；`.venv/bin/mypy src` → passed（112 source files）；`git diff --check` → passed。
- 换 key 后单条 Judge smoke 使用独立输出 `data/evaluation/benchmark/closure-review/judge-smoke-final-result.json`，1 条 run、9 个 atomic claims，Grounded Claim Rate 0.667、Citation Correctness 0.000，全部仍为 `llm_assisted_provisional`；没有人工升级，也没有覆盖历史 `stage3-final-judge-d.json`。
- 复测确认空 JSON 的直接根因是 Judge 误用 Router/Planner 的 2048 completion budget，返回 `finish_reason=length`；现改用 `max_output_tokens`，输出已完整。精确 provider 余额/配额仍不可从当前兼容 API 读取。
- Gate 3 freeze、holdout 生成/审核、一次正式 holdout 运行和 full 合并仍保持 pending；本批次没有创建 holdout，也没有把 smoke 当作最终质量结论。

## 2026-09-08 Gate 3 candidate preparation

- `environment.py::_git_commit()` 现在先检查 `git status --porcelain --untracked-files=all`，脏 worktree 显式拒绝；被 `.gitignore` 排除的本地 Evaluation artifact 不影响 clean 判定。
- README 的最终 Development 示例改为独立的 `gate3-final-development-real/` 和 `gate3-final-development-evaluation.sqlite3`，并明确历史 `stage3-final-real/`（`7bac928`）不能与新 holdout 合并。
- 当前最新远端代码仍为 `cd973588e0b5e99304770b4a159e21ff20c2baf9`；本次 clean-worktree guard 与文档修复尚未提交。
- 最终候选 Environment、37×5 Development 重跑、最终 Tier 1/Tier 2 报告和 Gate 3 review summary 待本批次修复提交后生成；holdout 仍未生成、未查看、未登记、未运行。
