# M6 Trace / Observability Implementation Plan

## Phase 1 — task activation and contracts

1. Review this PRD/design with the user, then create branch `codex/m6-trace-observability` and activate the Trellis task.
2. Add `src/trivae/observability/` package with normalized event, failure, profile, collector warning and projection contracts.
3. Add SQLite Trace Store schema/connection/read/write contracts and Import diagnostics read projection without touching Canonical facts.
4. Add additive `QueryRequest.trace_profile`, `QueryResult.trace_id` and Runtime safe event fields; preserve existing positional/low-level M4/M5 interfaces.

## Phase 2 — collector, mapper and persistence

1. Implement capture policy: bounded recursive projection, key-based secret redaction, JSON-safe ordinary values, explicit truncation limitations, and no persistent `content_delta`.
2. Implement Collector identity/sequence/persistence/completeness handling and Trace Store failure warning. Add append-only and unique-sequence tests before application wiring.
3. Implement `RuntimeEvent → NormalizedQueryEvent` mapper and `TraceableAgentRuntime`; ensure real streamed runtime events retain run/tool/usage/finalizing/terminal semantics and injected run-only runtimes remain testable.
4. Add per-run trace context propagation through RuntimeContext and the optional built-in Tool trace hook; instrument Tool execution and Retrieval child operation with existing RetrievalResult/coverage facts and correct failure ownership.

## Phase 3 — Query/Application vertical slice

1. Instrument Application ingress/context and create/read/close Trace resource in Composition Root.
2. Instrument Router and Planner at the Orchestrator boundary, retaining degradation/failure facts and `executed_without_plan` without adding an executor or second workflow.
3. Instrument Runtime/Tool/Retrieval through the mapper and hook; instrument Evidence/Citation/Answer Finalization around the existing `finalize_answer()` contract.
4. Instrument Conversation commit start/completion/failure and emit Query terminal only after the actual business commit result. Preserve existing exception/rollback behavior.
5. Expose `Application.read_trace()` and `read_import_diagnostics()`; add thin `trivae trace show` and `trivae import diagnostics` only if the existing CLI parser can accept them without new protocol semantics.

## Phase 4 — Tests and failure-case loop

Add tests in a focused `tests/test_observability.py` (and extend existing boundary tests only where the behavior belongs there):

- event validation, identity, schema version, invalid stage/phase/outcome;
- sequence, append-only, causality and close/reopen replay;
- Router degraded + completed query;
- Planner failed + executed without plan + completed runtime;
- Runtime failed, Tool Contract Error returned-to-agent, Retrieval partial/truncated and Abort;
- invalid Citation/finalization failure and Conversation commit failure;
- incomplete trace with no terminal event;
- normal bounds/redaction and debug fuller model-visible facts without secret/CoT/scope leakage;
- Trace Store failure does not change a successful business result and emits diagnostic warning;
- Application `trace_id` facade, import batch/error projection and CLI projection boundary.

For each failure case, first reproduce and identify the owner, then fix the main path, preserve the failure fact, and add regression protection. Do not change tests to hide an implementation error.

## Phase 5 — validation, smoke and documentation

Run, in order:

```bash
PYTHONPATH=src .venv/bin/pytest -q
PYTHONPATH=src .venv/bin/ruff check src tests
PYTHONPATH=src .venv/bin/mypy src
PYTHONPATH=src .venv/bin/python -m trivae --help
PYTHONPATH=src .venv/bin/python .trellis/scripts/task.py validate .trellis/tasks/08-23-m6-trace-observability
git diff --check
```

Then use a copied/temporary real SQLite working database to run one complete Query path and print only safe facts: trace ID, event count/sequence range, route, planner outcome, tool/retrieval counts, citation/finalization, commit and terminal status. If `DEEPSEEK_API_KEY` is present, run the existing real provider smoke path with no key/raw chat output; otherwise record the explicit reason it was not run.

Update only the existing guideline/architecture documents with an implementation record, physical schema, package ownership, measured validation and real/regression/anticipated Failure Case distinctions. Create `validation.md`, run the Trellis finish/quality workflow, commit and push the branch; do not merge `main`.

## Risk and rollback points

- Runtime stream mapping risk: verify existing M4 event ordering and terminal semantics before changing adapter fields. If a field is not needed for Trace, keep it optional rather than changing the event family.
- Application commit risk: run existing M5b transaction tests after every commit-boundary change; never write `query.completed` before `commit_turn()` returns.
- Trace store failure risk: inject a failing store and verify query/business execution continues while logger/collector diagnostics are visible; never use a silent catch.
- Privacy risk: test secret keys and bearer values at the capture boundary in both profiles; do not broaden redaction into an unbounded secret-detection framework.
- If implementation reveals a real conflict with a Confirmed ADR, stop that path, record Reopen Reason/Evidence/Decision in the task validation and do not paper over it with fallback/compatibility branches.
