# Router / Evaluation audit

## Router behavior and insertion point

- `RuleRouter` is rule-first. Structured queries without planning signals return `standard_execution` at `0.95`; explicit recovery or at least two structural signals return `planned_execution` at `0.92`; all other requests conservatively return `standard_execution` at `0.45`.
- An injected completion is invoked only when the static confidence is below `0.8`.
- The LLM prompt contains query, locale, prior model context, and data snapshot. It does not serialize `ExecutionScope`; available capabilities are not included in this prompt.
- The LLM response is strict JSON containing route/confidence/reason; reason is truncated to 240 characters. Timeout maps to `ROUTER_COMPLETION_TIMEOUT`; invalid output and provider exceptions map to `ROUTER_COMPLETION_INVALID`; the static Rule route remains selected.
- The Application obtains completion from the configured Runtime and injects it into RuleRouter. Main `ModelSettings` are from `TRIVIAE_MODEL_*` and provider-specific key variables. No Router-specific provider settings existed.

## Trace and Evaluation

- QueryOrchestrator emits `router.started`, `router.decision`, and `router.degraded`. The selected decision projection contains route, confidence, source, reason, degradation, and usage. Its event duration currently covers the full Router call.
- Evaluation's `query_result_snapshot()` stores route, route source, degraded state, degradation code, Planner/runtime summaries, but not Router confidence, provider latency, probability distribution, or a secondary/shadow observation.
- Router unit tests are in `tests/test_query_execution_core.py`. They cover obvious Rule paths, LLM JSON mapping, invalid output, and provider exception.
- Evaluation CaseBundle JSON contains query, locale, scope, findings, and general provenance but no Router GT field. Existing seed cases and Stage 1.10 design seeds are not a validated Router benchmark; Stage 1.10 says route accuracy alone does not establish Planner Utility.

## Provider/API audit

- The only current generic model settings are `ModelSettings` for the main Runtime/Planner/Router LLM provider; there is no OpenRouter provider configuration.
- The Runtime already uses `openai.AsyncOpenAI`. Its public async `.post(path, cast_to=..., body=...)` method can carry the Decisions payload without adding a separate SDK or changing the main model client.
- Current OpenRouter docs identify `POST https://openrouter.ai/api/alpha/decisions`, with `{model,state,questions}` request and typed `answers`, Choice probabilities/confidence, and optional usage token/cost values. This is not the OpenAI Chat Completions request/response shape.
- Model page at audit time lists `typesafe/jev-1.13`, text decisions, 32K context, and `$0.042/M input, $0/M output`; evaluation will use only actual response cost and will not estimate from that listed rate.

## Sources checked

- `.trellis/spec/project/technical-decisions/stage-1-5-router.md`
- `.trellis/spec/project/technical-decisions/stage-1-10-evaluation.md`
- `src/trivae/query/router.py`, `contracts.py`, `orchestrator.py`, `completion.py`
- `src/trivae/config/settings.py`, `src/trivae/query/runtime/openai_adapter.py`
- `src/trivae/bootstrap/application.py`, `src/trivae/evaluation/checks.py`
- `tests/test_query_execution_core.py`, `tests/test_evaluation.py`
- OpenRouter Decisions API reference and Jev 1.13 model page (see final report links)

## Data limitation

No existing case set contains human-adjudicated Router labels. New Router labels must therefore retain explicit provenance and `pending_human_adjudication` status. Any pre-adjudication score is a provisional diagnostic and cannot qualify for promotion.
