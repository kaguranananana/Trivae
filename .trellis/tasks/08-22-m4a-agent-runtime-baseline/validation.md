# M4a Agent Runtime Baseline Validation

## Measured checks

- `PYTHONPATH=src .venv/bin/pytest -q`: **80 passed**.
- `PYTHONPATH=src .venv/bin/ruff check src tests`: **passed**.
- `PYTHONPATH=src .venv/bin/mypy src`: **passed; no issues in 32 source files**.
- `PYTHONPATH=src .venv/bin/python -m trivae --help`: **passed**.
- `PYTHONPATH=src .venv/bin/python .trellis/scripts/task.py validate .trellis/tasks/08-22-m4a-agent-runtime-baseline`: **passed**. The validator emitted only existing context-size warnings for large spec files.

The repository did not previously package `src/` for direct system-Python imports, so the checks use the existing `PYTHONPATH=src` source-layout convention. No `uv.lock` was retained.

## Runtime coverage

- Settings defaults, required values, provider selection, positive `max_turns`, and secret-safe projections are covered.
- DeepSeek `OpenAIChatCompletionsModel` construction is covered with a fake key and no network request.
- Runtime requests reject invalid scope and capability-container types at the public boundary.
- `ScriptedModel` tests exercise the real SDK function-tool pipeline without network access.
- The end-to-end test reaches the existing SQLite import, lexical index, `CapabilityRegistry`, and `SearchMessagesTool` before returning a scripted final answer.
- SDK `MaxTurnsExceeded` is mapped to an explicit `MAX_TURNS_EXCEEDED` result.
- Known capability errors remain typed tool envelopes; unclassified tool exceptions remain terminal runtime failures.
- Application construction remains provider-key independent; runtime construction is lazy or explicitly injectable.

## Live smoke

Not measured / waiting for live validation. No local DeepSeek API key was used, logged, or recorded.

## Explicitly out of scope

Router, Planner, full QueryOrchestrator, Trace backend, Evidence/Citation, vector or semantic/hybrid retrieval, multi-agent handoff/workflow/replanning, HTTP/SSE, query CLI, retries, fallback providers, and application-level degradation are not implemented.

## Interview defense evidence index

- Problem and ownership boundary: `prd.md`, `design.md`.
- SDK/API evidence: `research/openai-agents-sdk-deepseek.md`.
- Implementation and regression evidence: `tests/test_agent_runtime.py`, `src/trivae/query/runtime/`, and the measured commands above.
