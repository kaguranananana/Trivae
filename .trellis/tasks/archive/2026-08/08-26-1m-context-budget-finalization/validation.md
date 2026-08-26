# Validation Record

## Baseline

- Branch confirmed: `codex/dynamic-tool-result-budget-regression`
- Starting HEAD: `e5d406c`
- Baseline before this task: `.venv/bin/pytest -q` → `333 passed`
- Existing changes were audited and preserved before implementation.

## Contract checks

- `opencode-go / deepseek-v4-flash` resolves to `1,000,000` with source `verified_model_registry`.
- Explicit `TRIVAE_MODEL_CONTEXT_WINDOW_TOKENS` wins with source `explicit_config`.
- Unknown dynamic model uses source `fallback`, per-call 16k and shared run pool 16k.
- `fixed` does not consume context and retains fixed 16k per-call behavior.
- Known dynamic model uses per-call `min(floor(context×50%),128k)` and run pool `min(floor(context×25%),256k)` unless an explicit experiment override is supplied.
- Trace/Evaluation use explicit per-call/run-level fields; no ambiguous `max_tool_result_tokens` field is used in current product code.

## Graceful finalization checks

- valid artifact passes through unchanged.
- string `limitations` normalizes to one bounded limitation and yields `degraded`.
- invalid local citation/source is dropped once, valid citation survives, and answer remains readable.
- all citations invalid still preserve the answer with no fake binding and `degraded` status.
- empty/unusable answer, trusted provenance failure, scope violation and canonical trust failure remain `failed`.
- Runtime failure is never converted into a finalization degradation.
- no second LLM repair was added to finalization.

## Automated gates

定稿前执行并记录实际输出：

```text
.venv/bin/pytest -q
.venv/bin/ruff check src tests
.venv/bin/mypy src
.venv/bin/python -m compileall -q src tests
.venv/bin/python -m trivae.interfaces.cli --help
git diff --check
```

<!-- FINAL_GATE_RESULTS_START -->

定稿门禁已全部通过：

- `.venv/bin/pytest -q` → `348 passed in 3.67s`
- `.venv/bin/ruff check src tests .trellis/tasks/08-26-1m-context-budget-finalization/real_ab.py` → passed
- `.venv/bin/mypy src` → passed，84 source files
- `MYPYPATH=src .venv/bin/mypy --ignore-missing-imports .trellis/tasks/08-26-1m-context-budget-finalization/real_ab.py` → passed
- `python3 -m compileall -q src tests .trellis/tasks/08-26-1m-context-budget-finalization/real_ab.py` → passed
- `.venv/bin/trivae --help` → passed，16 lines
- `python3 ./.trellis/scripts/task.py validate .trellis/tasks/08-26-1m-context-budget-finalization` → passed
- `git diff --check` → passed

<!-- FINAL_GATE_RESULTS_END -->

## Real A/B status

目标为 36 个真实 cell（4 prompt × 3 variant × 3 repetition）。实验 harness 修复后若 provider 在 timebox 内没有 terminal，记录 `timeout` 并保留原因；不伪造 Trace ID，不把 timeout 当作 completed/degraded。

最终记录：36/36 已执行；`fixed-16k` 为 12 timeout，`dynamic-run-128k` 为 2 completed valid + 10 timeout，`dynamic-run-256k` 为 1 completed valid + 1 runtime failed + 10 timeout。timeout 的 worker 使用 30 秒硬时限并被终止，Trace 已创建但没有 terminal event；3 个 completed valid 均解析到 `1,000,000 / verified_model_registry`、128k per-call 且 omission/truncation 为 0。完整 Trace ID 与 bounded 结果见 [experiment-report.md](experiment-report.md)。
