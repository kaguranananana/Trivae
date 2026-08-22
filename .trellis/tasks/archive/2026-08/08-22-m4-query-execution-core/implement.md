# M4 Implementation Plan

## Phase 1 — task and contracts

1. Record PRD/design/research and start the Trellis task only after planning validation.
2. Add query contracts, Router, Planner and Orchestrator without importing provider SDK types.
3. Extend runtime contracts additively so M4a callers and tests remain valid.

## Phase 2 — execution core

1. Convert the OpenAI Agents adapter to one streamed execution path.
2. Add safe event projection, tool-round accounting, finalization guidance, absolute max-turn backstop and cancellation.
3. Add provider/model/application async lifecycle and sync lifecycle wrapper.
4. Compose the query entrypoint in the application while preserving provider-free construction and the M4a `run_agent` compatibility surface.

## Phase 3 — tests and docs

1. Add deterministic tests for route/plan/orchestration contracts, event ordering, budget, backstop, cancellation, errors and lifecycle.
2. Run the full existing suite plus lint/type/CLI/Trellis checks; fix implementation root causes.
3. Run optional live smoke only when credentials are already present, without printing secrets.
4. Update backend specs with the implemented contracts, write validation evidence, run Trellis finish checks, commit and archive the task.

## Risk boundaries

- Do not add retries, provider fallback, hidden compatibility branches or SDK session persistence.
- Do not expose trusted scope in model prompts, event payloads or provider error text.
- Do not change existing tool error semantics to make a test green; unknown tool exceptions remain terminal.
- Do not add SQL, retrieval or UI features unrelated to closing the query execution loop.

## Verification commands

```text
PYTHONPATH=src .venv/bin/pytest -q
PYTHONPATH=src .venv/bin/ruff check src tests
PYTHONPATH=src .venv/bin/mypy src
PYTHONPATH=src .venv/bin/python -m trivae --help
PYTHONPATH=src .venv/bin/python .trellis/scripts/task.py validate .trellis/tasks/08-22-m4-query-execution-core
git diff --check
```
