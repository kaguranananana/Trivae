# Design: OpenRouter Jev as an experimental ambiguous Router provider

## Confirmed architecture retained

```text
QueryRequest → RuleRouter
  ├─ confidence >= 0.8 → RouteDecision
  └─ ambiguous → selected decision provider → RouteDecision → QueryOrchestrator
```

Router remains an execution-complexity classifier / Planner gate with only `standard_execution` and `planned_execution`. No Tool, Retrieval, Evidence, SQL, or Plan-step decision moves into Router.

## Current-state audit

1. `RuleRouter._rule_decision()` directly returns high-confidence standard for structured lookup/aggregation without a planning signal, high-confidence planned for explicit recovery or at least two independent structure signals, and a conservative standard decision at confidence `0.45` otherwise. Only the latter enters a provider when one is injected.
2. The current provider is `runtime.complete_text`, built on the Runtime's configured OpenAI-compatible client. Its JSON prompt carries query, locale, prior model context, and `data_snapshot`; it excludes trusted `ExecutionScope` and currently excludes `available_capabilities`.
3. Baseline JSON requires route, confidence, and reason. Invalid JSON/shape and provider exceptions currently share `ROUTER_COMPLETION_INVALID`; `asyncio.wait_for` timeout maps to `ROUTER_COMPLETION_TIMEOUT`. Both retain the static Rule route.
4. `QueryOrchestrator` emits `router.started`, `router.decision`, and `router.degraded`; decision Trace already includes route/source/confidence/reason/degradation/usage and a total duration. Evaluation's `query_result_snapshot` keeps route/source/degradation but not confidence, provider latency, or probabilities.
5. Existing tests in `tests/test_query_execution_core.py` cover direct rules, ambiguous LLM mapping, malformed output, and provider exceptions. Evaluation CaseBundle has no Router ground-truth field. Stage 1.10 explicitly treats Router Utility as a later, evidence-driven comparison; Design Seeds are not a benchmark.
6. `load_settings()` owns only `TRIVIAE_MODEL_*` and the current provider credentials. The Application injects a metadata-aware completion from the same Runtime into Planner and a text completion into Router; no Router-specific provider registry or OpenRouter configuration exists.
7. The smallest insertion point is the existing ambiguous branch in `RuleRouter.route()`. The Jev adapter will use `openai.AsyncOpenAI.post()` as the HTTP transport, with its own Router-only key/model/endpoint settings and without adding dependencies.

## Provider boundary and settings

- A new `RouterJevSettings` loader owns the five user-specified variables. Defaults are Jev enabled, model `typesafe/jev-1.13`, endpoint `https://openrouter.ai/api/alpha/decisions`, mode `shadow`.
- Missing `OPENROUTER_API_KEY` is not an application-construction error. An attempted Jev decision returns `JEV_ROUTER_API_KEY_MISSING` and the static route.
- The adapter posts `model`, a projected `state`, and one `choice` question to the configured Alpha Decisions endpoint. It accepts only the two current route labels.
- State is the exact allowed Router projection: query, locale, prior model context, and current `data_snapshot`; it excludes scope, credentials, capability inventory, and other internal state.
- The adapter returns plain Trivae-owned route/confidence/probability/usage values. It does not expose OpenAI SDK or OpenRouter response types.
- Choice confidence maps to `RouteDecision.confidence`; `choice` maps to `route`; the two bounded `probabilities` map is retained. OpenRouter usage tokens and `usage.cost` are kept only when actually present.

## Modes and failures

| Mode | Primary decision | Jev behavior |
| --- | --- | --- |
| `existing_llm` | Current LLM fallback | Not called |
| `jev` | Jev | A failure retains static Rule decision and marks it degraded |
| `shadow` | Current LLM fallback/static Rule | Jev result is diagnostic only and cannot change route |

The adapter classifies missing key, authentication, rate limit, timeout, network, model unavailable, provider unavailable, and malformed Decisions responses with stable `JEV_ROUTER_*` codes. It never stores the raw provider error body. Shadow records its own latency/degradation; primary route and primary latency remain distinct.

## Evaluation

- Add a narrow Router paired runner under the existing `trivae eval` entry point rather than changing the end-to-end Evaluation CaseBundle schema.
- Use a versioned, small, privacy-safe Router case set that covers clear rules and ambiguous boundaries required by the request. Each label records provenance and human-adjudication status. Agent-authored labels remain provisional until a person adjudicates them.
- Invoke LLM and Jev only for cases where the same deterministic Rule is ambiguous. Both receive the same QueryContext projection and route criteria.
- Result artifacts store case IDs/slices, route/confidence/probability/usage/latency/degradation and aggregate metrics only; no query text, API key, or provider payload.
- Report accuracy, class precision/recall, both false-route directions, confusion/disagreement, confidence slices, p50/p95/mean latency, timeouts/errors, usage/cost, availability, and degradation. Missing provider cost remains unavailable; Jev cost is OpenRouter's returned `usage.cost` only.
- No promotion threshold is invented. Promotion is blocked until representative Router labels are human-adjudicated and the asymmetric planned→standard risk, latency, cost, and failure rates are reviewed.

## Explicitly out of scope

No TypeSafe SDK, no `TYPESAFE_API_KEY`, no main-model provider change, no Chat Completions/Responses assumptions for Jev, no Router taxonomy change, no Planner/Runtime/Judge/Retrieval/Tool changes, and no promotion based on an unadjudicated small sample.
