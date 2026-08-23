# M5 durable conversation persistence finalization — implementation plan

## Phase 1 — context and contract preparation

1. Read this task PRD/design, Stage 1.7/1.8/1.11 ADR, backend database/error/quality/directory guidelines and existing M5a validation.
2. Confirm the working branch, clean baseline and existing full test/lint/type results.
3. Implement the Conversation domain contract, explicit Artifact codec and SQLite schema/store first, with 简体中文 comments explaining each transaction and codec step.

## Phase 2 — deterministic persistence behavior

1. Add unit tests for Conversation/Message invariants and stable ordinal ordering.
2. Add round-trip tests for every Artifact branch: content blocks, citation bindings, Evidence IDs, relation, sufficiency, finding/criterion, limitations, hydrated MessageSource and StructuredSource.
3. Add SQLite restart test using a real temporary database and separate store/application instances.
4. Add transaction rollback test that fails after User insert and verifies no User or Assistant row remains.
5. Add finalization/runtime failure tests proving `commit_turn()` is not called and no completed Assistant row exists.

## Phase 3 — Application integration and historical boundary

1. Add Application create/read facade and optional conversation id to Query request/result without changing existing positional behavior.
2. Wire stored history into the single existing Orchestrator boundary; do not duplicate Router, Planner, Runtime or Finalizer logic.
3. Commit only `QueryResult.is_successful` after Finalizer returns the hydrated Artifact.
4. Add deterministic follow-up tests: persisted historical context is available for reference; old source is rejected by current-run finalization; a new ToolResult/run can be committed as a new Assistant turn.
5. Add a deterministic regenerate-equivalent test only at the Application/query boundary; do not add a product endpoint.

## Phase 4 — documentation and real smoke

1. Run the full deterministic suite before any live provider call.
2. Run the existing M5a real DeepSeek happy-path against real SQLite/canonical data, commit the validated result, close the Application/store, reopen it, and compare the persisted Artifact facts without logging secrets or full chat/model payloads.
3. If a real failure appears, reproduce the smallest path, identify root cause, apply the smallest main-path fix, add regression protection, and rerun. Do not add fallback/retry to conceal it.
4. Record measured facts, real failures versus regression cases, persistence schema, boundary ownership and limitations in task `validation.md`.
5. Update architecture status, Stage 1.8 implementation status, backend/storage/directory guidelines, technical decisions, interview-defense evidence, and journal only after code and checks are complete.

## Required validation commands

```text
PYTHONPATH=src .venv/bin/python -m pytest -q
.venv/bin/ruff check src tests
PYTHONPATH=src .venv/bin/mypy src
PYTHONPATH=src .venv/bin/python -m trivae --help
python3 ./.trellis/scripts/task.py validate 08-23-m5-conversation-persistence-finalization
git diff --check
```

Also run a focused Conversation/SQLite test command during iteration and the real M5 DeepSeek persistence smoke after deterministic checks pass.

## Risky files and rollback points

- `src/trivae/bootstrap/application.py`: composition/lifecycle and atomic commit invocation; rollback by removing only Conversation Store wiring.
- `src/trivae/query/contracts.py`: public request/result extension; preserve existing positional fields and existing manual prior-context behavior.
- `src/trivae/query/evidence.py`: should not change unless the codec exposes a genuine existing contract bug; no semantic redesign planned.
- `src/trivae/data/storage/sqlite.py`: do not alter canonical schema or write semantics unless a real shared-file initialization issue is reproduced.
- `.trellis/spec/*`: update only after implementation evidence; do not claim Trace/Evaluation capabilities that remain pending.

## Completion gate

Do not mark M5 Completed until deterministic tests, real SQLite restart persistence, real DeepSeek persistence smoke, quality gates, Trellis validation, documentation sync, commit and task archive all have recorded evidence.
