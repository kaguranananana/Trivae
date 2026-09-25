# OpenRouter Jev Router paired evaluation

## Goal

Add an experimental OpenRouter Jev decision provider for only the existing RuleRouter ambiguous branch, retain the current Router LLM baseline, and make the providers comparable on one bounded Router dataset.

## Requirements

- Preserve Stage 1.5 Router scope and deterministic Rule-first behavior.
- Add isolated configuration: `OPENROUTER_API_KEY`, `TRIVIAE_ROUTER_JEV_ENABLED`, `TRIVIAE_ROUTER_JEV_MODEL`, `TRIVIAE_ROUTER_JEV_ENDPOINT`, and `TRIVIAE_ROUTER_JEV_MODE`.
- Keep `TRIVIAE_MODEL_*` unchanged for Planner, Runtime, and answer generation.
- Support `existing_llm`, `jev`, and `shadow`; default to Jev enabled in shadow mode.
- Use OpenRouter's Decisions endpoint, its Choice response, confidence, probabilities, and actual usage/cost fields. Do not add a Jev SDK.
- Keep provider-specific parsing in an adapter and return the Trivae `RouteDecision` domain contract.
- On Jev failures retain the deterministic Rule decision and expose a stable degradation code. Shadow failures cannot alter the primary decision.
- Keep Trace and Evaluation projections bounded; do not persist credentials, provider raw payloads, or source query content in result artifacts.
- Compare LLM and Jev using the same QueryContext projection and case labels; report uncertainty and data provenance without presenting provisional labels as adjudicated ground truth.
- Do not modify Planner, Runtime, Judge, retrieval, Tool selection, or the confirmed route taxonomy.

## Acceptance Criteria

- [ ] Rule-first route behavior and all existing Router tests remain intact.
- [ ] Jev configuration is independent from primary model configuration and missing key does not prevent application startup.
- [ ] Unit tests cover Decisions payload/response mapping, bounded probabilities, failures, shadow isolation, Trace projection, and Evaluation override bypass.
- [ ] A paired Router evaluation command and a versioned case manifest exist; its output contains no raw queries or provider payloads.
- [ ] Report identifies dataset provenance/adjudication and refuses a promotion claim without sufficient human-adjudicated cases.
- [ ] Run targeted checks and the repository test suite; report the actual results.
- [ ] Attempt a real provider evaluation only with a safe, rotated OpenRouter key. If unavailable, leave real provider metrics explicitly blocked and provide the runnable command.
- [ ] Record implementation/evaluation decision separately from the Stage 1.5 Router ADR.
