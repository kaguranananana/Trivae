# Validation: resume-benchmark-v1 Stage 3

## Completion boundary

- Stage 3 status: **Complete / Ready for Gate 3**。
- Final headline scope: Development only，37 cases × A/B/C/C2/D × 1 repetition = 185 runs。
- calibration 10 cases 已排除 headline denominator；holdout absent，未生成、未查看、未评测。
- 最终 clean execution commit：`7bac9282701bd0c21b58ce8e5a4f5cc52c87da9f`。
- Gate 2 freeze execution commit：`b1f7b78ba802f853f9cd1cbf7433fe07b2f895c1`；freeze metadata commit：`e34c6985a734eb2169e0a48e12a512270ca0c353`。

## Gate / dataset validation

- `data/evaluation/benchmark/stage3-freeze-verification.json`：environment gate 4/4、freeze verification 12/12，全部 passed。
- `data/evaluation/benchmark/gt-audit-stage3-final.json`：47 cases、47 adjudicated、0 error、0 warning，passed。
- `trivae eval cases validate evaluation/cases/benchmark/dev`：37 个 versioned Case 全部 valid。
- `trivae eval cases validate evaluation/cases/benchmark/calibration`：10 个 versioned Case 全部 valid。
- `trivae eval benchmark gate ...`：canonical Snapshot、lexical index、semantic identity、Git commit 四项 passed。
- 最终 SQLite Evaluation Store：185 distinct run_id；五个 Variant 各 37 个 case。

## Evaluation artifacts

- Module retrieval：`data/evaluation/benchmark/stage3-module-retrieval.json`，27 个 query，保留 lexical / semantic 的 corpus 与 target scope、Recall@5/10、Hit@K、MRR@10 和 context observation。
- First real run：`data/evaluation/benchmark/stage3-first-real/`，185 条 provisional run 与 112 条 failure artifact。
- Targeted reruns：`data/evaluation/benchmark/stage3-targeted/`，stream A/C、C2 context、D temporal classification 均保留真实 production Query path 的 before/after 证据。
- Final clean：`data/evaluation/benchmark/stage3-final-real/` 与 `data/evaluation/benchmark/stage3-final-evaluation.sqlite3`；raw records 185 条、failures 108 条、每个 Variant 37 条。
- Tier 1：`data/evaluation/benchmark/stage3-final-real/report.json` / `report.md`；包含分子/分母/rate/macro、unavailable reason、operational、paired comparison、failure analysis、freeze/environment identity。
- Tier 2：`data/evaluation/benchmark/stage3-final-judge-d.json`；8 条 LLM-assisted provisional judge，29 条 `judge_failed`，0 条 skipped，0 条 human adjudicated。
- Tier 2 audit queue：`data/evaluation/benchmark/stage3-final-judge-audit-queue.json`，37 条完整覆盖，状态为 pending human adjudication。

## Engineering checks

```text
.venv/bin/pytest -q                         → 572 passed
.venv/bin/ruff check src tests              → All checks passed
.venv/bin/mypy src                          → Success: no issues found in 111 source files
git diff --check                            → passed
```

## Failure-driven iteration result

- 已修复通用 streaming/model-behavior terminal projection、provider observation preservation、finalization failure classification、report denominator/operational/paired aggregation；regression 位于 `tests/test_agent_runtime.py` 与 `tests/test_benchmark.py`。
- targeted stream A/C 无 failure artifact；context recovery 和 temporal partial coverage 的剩余限制未被隐藏，仍在 final report 中按真实状态分类。
- final failure categories：provider_failure 9、coverage_error 18、context_missing 13、answer_generation_error 6、retrieval_miss 3、zero_result_error 2、not_observed_within_recorded_depth 57；未观察到 ranking_failure、router_tool_selection_error、evaluation_infrastructure artifact。

## Stop boundary

- Gate 3 review：pending。
- Holdout generation / evaluation：未执行。
- Full benchmark：未执行。
- 本文件和其他文档只记录已完成的 Development Evaluation，不把结果表述为 unseen 或 holdout 结果。
