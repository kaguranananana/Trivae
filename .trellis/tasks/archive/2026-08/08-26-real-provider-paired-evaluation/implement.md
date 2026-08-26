# Implementation plan

## Phase A — planning and audit

- [x] Read the archived benchmark, `real_ab.py`, experiment report, validation and Trace schema/data.
- [x] Confirm existing Evaluation projection (`operational_measurements`, `query_result_snapshot`, `ReviewPacket`) and package specs.
- [x] Record the boundary: no budget/prompt/case/rubric product changes unless a completed Trace proves a bug.
- [x] Run `task.py validate`, then `task.py start` after the planning artifacts are complete.

## Phase B — runner

- [x] Add a task-local real Provider runner derived from the archived experiment design.
- [x] Add explicit per-cell timeout and absolute experiment deadline; record every planned cell exactly once.
- [x] Add `dynamic-default-250k` without a run-pool override and assert the resolved budget facts from Trace.
- [x] Reuse existing Evaluation/Trace projections and write bounded operational rows.
- [x] Write local ReviewPacket-style materials for completed samples without putting answer正文 in committed summary data.

## Phase C — real experiment and analysis

- [x] Preflight provider env without printing credentials.
- [x] Run all 36 cells unless the total deadline is reached; preserve stdout summary and local review materials.
- [x] Map all new request IDs to Trace IDs and classify completed, runtime failure, cell timeout and experiment timeout.
- [x] Build same-case/repetition paired sets; manually inspect available materials and mark unknown where evidence is insufficient.
- [x] Write report with effective limits, per-variant counts, chain metrics, quality conclusion, failure cases, Trace IDs and next steps.

## Phase D — verification and handoff

- [x] Run related Evaluation regressions.
- [x] Run full pytest, Ruff, Mypy and compileall.
- [x] Run Trellis check and inspect diff/status on the current branch only.
- [x] Commit implementation/docs, archive the task, record the session journal, and report commit IDs.

## Validation commands

```bash
python3 ./.trellis/scripts/task.py validate
python3 -m pytest -q
ruff check .
mypy src tests
python3 -m compileall -q src tests
```

Real Provider commands and output paths will be recorded in the experiment report; secrets must remain in the local environment and never in git.
