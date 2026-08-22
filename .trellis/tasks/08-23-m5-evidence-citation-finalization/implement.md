# Implementation Plan: M5 Evidence / Citation + Answer Finalization

## Phase 1 — contracts and provenance

1. Add `query/evidence.py` with bounded Answer/Evidence/Citation/Source contracts, parser, validator and finalizer.
2. Extend retrieval message projection with trusted session display; add safe serialization for structured result data.
3. Add Trivae-owned `ToolResultRecord` and run-local IDs to runtime contracts without exposing SDK objects.

## Phase 2 — runtime and query integration

1. Make the search tool adapter record current-run provenance for known Tool results and expose bounded source locators to the model.
2. Carry tool result records through completed/failed/aborted RuntimeResult paths.
3. Update final synthesis prompt with the structured Answer Artifact contract.
4. Have QueryOrchestrator finalize only completed Runtime results and return `AnswerArtifact` or explicit `FinalizationErrorInfo`.
5. Keep `run_agent()` low-level M4 behavior and Application lifecycle intact; `query()` is the validated Answer Artifact entry.

## Phase 3 — deterministic verification

1. Add contract tests for valid/invalid Evidence, citation bindings and bounds.
2. Add provenance tests for current/fabricated/old run, result item, scope and message/structured locator behavior.
3. Add trusted hydration tests proving model metadata cannot replace canonical author/timestamp/session/excerpt.
4. Add runtime integration test for `search_messages → ToolResultRecord → structured final synthesis → finalizer → AnswerArtifact`.
5. Add failure tests for invalid citation, runtime failure, max turns, abort and no silent repair.

## Phase 4 — quality, docs, smoke and finish

1. Run the full deterministic suite and reproduce/fix root causes for any failures.
2. Run ruff, mypy, CLI help, Trellis validation and `git diff --check`.
3. Run an independent opt-in DeepSeek smoke only if existing credentials are available; never log secrets or raw chat.
4. Write `validation.md`, update backend/architecture/interview evidence docs, archive the task, record session journal and leave the worktree clean.

## Rollback points

- If structured final synthesis breaks low-level M4 runtime tests, keep `RuntimeResult.final_answer` provider-neutral and confine parsing/validation to QueryOrchestrator.
- If trusted hydration cannot be completed without a new persistence schema, stop at explicit M5b boundary rather than inventing a durable Conversation contract.
- Never fix malformed model citations by deleting, replacing or retrying them.

## Validation commands

```bash
PYTHONPATH=src .venv/bin/pytest -q
PYTHONPATH=src .venv/bin/ruff check src tests
PYTHONPATH=src .venv/bin/mypy src
PYTHONPATH=src .venv/bin/python -m trivae --help
PYTHONPATH=src .venv/bin/python .trellis/scripts/task.py validate 08-23-m5-evidence-citation-finalization
git diff --check
```
