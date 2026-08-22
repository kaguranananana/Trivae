# M4a Agent Runtime Baseline — Implementation Plan

## Phase A — dependency and contract preparation

- [x] Inspect the pinned/current OpenAI Agents SDK public API and choose the version-compatible Chat Completions and deterministic test-model interfaces.
- [x] Add the minimal runtime dependencies and development test dependency required by the requested quality gates.
- [x] Add `config` settings types/loader with explicit validation, DeepSeek defaults, and secret-safe representations.
- [x] Add SDK-independent runtime request/context/result contracts and the `AgentRuntime` protocol.
- [x] Add the short Chinese-commented system prompt and keep model-visible text separate from process-local context.
- [x] Update the project directory-structure spec only if the actual new package layout needs a documented addition.

## Phase B — SDK and capability adapters

- [x] Implement the `search_messages` SDK tool adapter as a thin typed mapping to `CapabilityRegistry` and `SearchMessagesTool`.
- [x] Implement DeepSeek `AsyncOpenAI`/Chat Completions model construction without import-time clients, hardcoded secrets, or fallback providers.
- [x] Disable hosted OpenAI tracing for the baseline path and keep provider exceptions observable.
- [x] Implement `OpenAIAgentsRuntimeAdapter` with one SDK runner invocation, the allowed tool set, trusted local context, and explicit `max_turns`.
- [x] Map normal completion, max-turn termination, capability envelopes, and unexpected errors into the Trivae-owned runtime result contract.

## Phase C — application composition and tests

- [x] Add lazy or explicitly injectable runtime composition to the application while preserving retrieval-only construction.
- [x] Add settings tests for defaults, missing values, provider/model validation, and secret redaction.
- [x] Add tool adapter tests for typed input mapping, trusted scope propagation, safe envelope projection, and explicit error behavior.
- [x] Add deterministic SDK integration tests for tool call -> existing capability/retrieval/SQLite -> tool result -> final answer.
- [x] Add a bounded-run test proving SDK max-turn termination is explicit and no hand-written loop exists.
- [x] Keep all existing M1-M3 tests unchanged unless a public contract genuinely requires a narrowly justified update.

## Phase D — validation and handoff

- [x] Run `pytest`.
- [x] Run `ruff check src tests`.
- [x] Run `mypy src`.
- [x] Run `python -m trivae --help`.
- [x] Run `python .trellis/scripts/task.py validate`.
- [x] Check for a local DeepSeek key without exposing it; live smoke remains not measured because no key is available.
- [x] Write `validation.md` with measured commands, results, known pre-existing issues, and live-smoke status.
- [ ] Run the Trellis quality/finish workflow, archive the task, record the journal, and commit the M4a changes with a concise message.

## Explicit non-actions

- Do not start implementation or create product files before the planning summary is approved.
- Do not implement Router, Planner, full QueryOrchestrator, evidence/citation, tracing backend, eval runner, semantic/vector retrieval, multi-agent workflows, HTTP/SSE, or a full query CLI.
- Do not add retries, fallbacks, silent catches, scope widening, SQL/FTS logic in the adapter, or test-only special cases.
