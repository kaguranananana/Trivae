# Validation Record

## Baseline and scope

- Branch：`codex/dynamic-tool-result-budget-regression`。
- 本轮开始 HEAD：`3e173c7`。
- 未创建新分支，未切换或 merge `main`。
- 产品代码 `src/` 未修改；变更范围为 task-local runner、评测报告、validation、Trellis project decision amendment 和 session metadata。
- 真实实验：Provider `opencode-go`、model `deepseek-v4-flash`、1M context、4 prompt、3 repetition、3 variant。

## Evaluation contracts checked

- `fixed-16k` 的 Trace 为 `budget_mode=fixed`、`effective_per_call_tool_result_budget=16000`，不读取 context window。
- 两个 dynamic variant 的 Trace 均为 `context_window_tokens=1000000`、`context_window_source=verified_model_registry`、per-call ceiling `128000`。
- `dynamic-run-128k` 的 run pool 为 `128000`；`dynamic-default-250k` 不注入 run override，解析为当前默认 `250000`。
- 当前修正版 runner 对 27 个 completed sample 逐行复算 budget facts，27/27 为 `passed`；原始运行文件中旧 checker 产生的 eligibility 字段未用于结论。
- canonical/model projection 来自现有 `ToolResultRecord` 和 runtime omission facts；runner 没有复制或重新实现产品预算算法。
- `operational_measurements`、`query_result_snapshot`、`ReviewPacket` 均复用现有 Evaluation 基础设施。
- timeout/runtime failure 没有质量材料，不进入 paired quality 分母；completed degraded 保留在质量材料中并单独标注 finalization 状态。

## Real experiment validation

- 36 planned cells：27 completed、7 `cell_timeout`、2 `runtime_failed`。
- 每 cell timeout：120 秒；总实验上限：4500 秒；实际在总上限前结束。
- completed quality-eligible：27/27。
- pairwise completed comparisons：21；完整三 variant triads：6。
- dynamic-128 completed 中 projection omission/truncation：0/11；default-250：0/6；fixed projection truncation：3/10。
- 最大累计 projection：fixed 33,114、dynamic-128 46,697、default-250 15,037；两套 dynamic run pool 均没有绑定。
- Provider usage：27 个 completed sample 均可用；没有用 projection estimate 代替真实 usage。

## Failure handling validation

- 7 个 cell timeout 保留 request identity 和 Trace ID；没有伪造 terminal 或 AnswerArtifact。
- 2 个 default Provider `SSLError` 保留为 runtime failure；finalization 为未运行，不被标为 degraded answer。
- 1 个 dynamic-128 completed degraded sample 保留用户回答和 citation/finalization diagnostics；没有把 graceful degradation 静默转为 valid。
- 没有新增 retry、fallback、compatibility branch 或产品层临时补丁。

## Automated gates

定稿时执行以下命令，并把实际结果写入本节：

```text
.venv/bin/pytest -q
.venv/bin/ruff check src tests .trellis/tasks/08-26-real-provider-paired-evaluation/real_ab.py
.venv/bin/mypy src
MYPYPATH=src .venv/bin/mypy --ignore-missing-imports .trellis/tasks/08-26-real-provider-paired-evaluation/real_ab.py
.venv/bin/python -m compileall -q src tests .trellis/tasks/08-26-real-provider-paired-evaluation/real_ab.py
.venv/bin/pytest -q tests/test_evaluation.py tests/test_tool_result_budget.py tests/test_observability.py tests/test_comprehensive_tool_diagnostics.py
.venv/bin/pytest -q .trellis/tasks/08-26-real-provider-paired-evaluation/test_real_ab.py
python3 ./.trellis/scripts/task.py validate .trellis/tasks/08-26-real-provider-paired-evaluation
git diff --check
```

<!-- FINAL_GATE_RESULTS_START -->

- `.venv/bin/pytest -q` → `348 passed in 3.98s`
- `.venv/bin/pytest -q tests/test_evaluation.py tests/test_tool_result_budget.py tests/test_observability.py tests/test_comprehensive_tool_diagnostics.py` → `53 passed in 1.54s`
- `.venv/bin/ruff check src tests .trellis/tasks/08-26-real-provider-paired-evaluation/real_ab.py` → passed
- `.venv/bin/mypy src` → passed，84 source files
- `MYPYPATH=src .venv/bin/mypy --ignore-missing-imports .trellis/tasks/08-26-real-provider-paired-evaluation/real_ab.py` → passed
- `.venv/bin/python -m compileall -q src tests .trellis/tasks/08-26-real-provider-paired-evaluation/real_ab.py` → passed
- `.venv/bin/pytest -q .trellis/tasks/08-26-real-provider-paired-evaluation/test_real_ab.py` → 3 passed
- `.venv/bin/trivae --help` → passed
- runner `0.01s cell / 0.02s experiment` smoke → 36 cells 均显式记录为 `cell_timeout` 或 `experiment_timeout`，没有质量资格样本
- `python3 ./.trellis/scripts/task.py validate .trellis/tasks/08-26-real-provider-paired-evaluation` → passed；仅有既有 `interview-defense.md` context injection 超过 32KiB 的 warning
- `git diff --check` → passed

额外执行的裸 `.venv/bin/ruff check .` 和 `.venv/bin/mypy src tests` 不作为本轮 gate：前者命中 62 个未改动的 `.codex/hooks`、`.trellis/scripts` 和归档脚本 lint 问题；后者命中 340 个未改动测试文件的既有 typing diagnostics。项目原有 validation scope 是 `ruff src/tests` 与 `mypy src`，本轮新增 runner 另行通过了 scoped Ruff/Mypy；没有为了消除无关基线噪声修改这些文件。

<!-- FINAL_GATE_RESULTS_END -->

## Decision

本轮没有足够的 exhaustive Reference 和稳定 paired semantic result 证明最终回答质量提升；报告只确认 dynamic 预算改善了本轮 fixed 的 model projection 可见性，并确认 250k pool 没有在这些 completed samples 中绑定。后续质量 Gate 必须继续沿用现有 Evaluation 的 Case/Reference/Trace 分轴，不把 operational improvement 直接等同于用户质量。
