# Implementation and validation plan

1. Add Router-only settings and safe defaults; add a credential-free `.env.example` template.
2. Add an OpenRouter Decisions adapter using the installed OpenAI async client transport; project and validate Choice response values.
3. Extend `RuleRouter` with `existing_llm`, `jev`, and `shadow` behavior while preserving default constructor compatibility and static Rule-first behavior.
4. Inject the adapter and metadata-aware baseline callback from the Application; close the Jev client with Application lifecycle.
5. Add separate primary/shadow observations to Router Trace and Evaluation projections.
6. Add a paired Router evaluation module, privacy-safe versioned case manifest, and `trivae eval router-jev` command. The command must not persist query text or provider payload.
7. Add/update tests for settings, mapping, confidence/probabilities, timeout/error classes, static retention, bypass, shadow isolation, and metrics.
8. Run focused tests, full project tests, Ruff, mypy, and `git diff --check`; do not modify tests to mask implementation failures.
9. Attempt live evaluation only after a rotated credential is available to the process. If not available, record that live metrics are blocked without substituting synthetic results.
10. Write the implementation/evaluation decision and actual evidence into this task's report; keep Stage 1.5 unchanged.

## Expected change boundary

- `src/trivae/config/settings.py`: independent Router Jev settings.
- `src/trivae/query/jev_provider.py`: OpenRouter Decisions transport and response adapter.
- `src/trivae/query/router.py`: provider selection, mappings, and shadow observation.
- `src/trivae/bootstrap/application.py`: provider injection and lifecycle.
- `src/trivae/query/orchestrator.py`, `src/trivae/evaluation/checks.py`: bounded branch telemetry.
- `src/trivae/evaluation/router_jev.py`, `src/trivae/interfaces/cli.py`, `evaluation/router-jev/cases-v1.json`: paired evaluation path.
- `tests/test_query_execution_core.py` plus focused settings/evaluation tests; `.env.example`; evaluation documentation/report.

Planner, Runtime's main model configuration, Judge, retrieval, tools, and Stage 1.5 taxonomy are not targets.
