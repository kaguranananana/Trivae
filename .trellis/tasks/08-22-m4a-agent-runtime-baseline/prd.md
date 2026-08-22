# M4a Agent Runtime Baseline

## Goal

Deliver the smallest real Agent Runtime vertical slice for Trivae:

`user query -> Trivae AgentRuntime -> OpenAI Agents SDK -> DeepSeek -> search_messages SDK tool -> existing Capability/Retrieval/SQLite -> Tool Result -> LLM -> final answer`.

The slice must prove that the existing M1-M3 retrieval and capability layers can be driven by a model through a Trivae-owned runtime boundary. It is a baseline, not the complete future Router/Planner/Orchestrator architecture.

## In scope

- Add a Trivae-owned, SDK-independent `AgentRuntime` contract and runtime result contract.
- Add configuration for DeepSeek through its OpenAI-compatible Chat Completions endpoint.
- Add an `OpenAIAgentsRuntimeAdapter` that constructs and runs an OpenAI Agents SDK agent.
- Let the SDK own the generic model/tool loop; use an explicit SDK turn limit for bounded execution.
- Expose only the existing `search_messages` capability through a thin SDK tool adapter.
- Preserve the existing `ExecutionScope`, `CapabilityRegistry`, `SearchMessagesTool`, lexical retrieval, context expansion, and SQLite boundaries.
- Keep runtime context local to the process; do not send scope, registry, SQL, FTS, or internal trace data to the model.
- Project tool output as the existing safe `ToolEnvelope` shape and make tool failures explicit.
- Provide deterministic tests for configuration, runtime construction, SDK-tool-to-capability mapping, bounded execution, and the end-to-end path without a real API key.
- Keep application construction compatible with existing retrieval-only callers by making model/runtime creation lazy or explicitly injectable.
- Add the requested quality-gate commands and a validation record. A live smoke check is optional and must never record a secret.

## Configuration contract

- `DEEPSEEK_API_KEY` is required when the real provider is invoked and must never be hardcoded or logged.
- `DEEPSEEK_BASE_URL` defaults to `https://api.deepseek.com`.
- `TRIVAE_MODEL_PROVIDER` selects the provider and defaults to `deepseek` for this baseline.
- `TRIVAE_MODEL_NAME` selects the model and is required unless the implementation documents a non-secret, tested default; no model name may be hardcoded in runtime logic.
- Hosted OpenAI tracing must be disabled when no OpenAI tracing key is configured. No import-time client, database, or runtime construction is allowed.

## Architecture constraints

- The adapter may use SDK types internally, but SDK types must not leak into Retrieval, Capability, or Application contracts.
- Do not implement a second hand-written `while model -> parse -> execute tool` loop.
- Do not add M4b Router, M4c Planner, a full QueryOrchestrator, Evidence/Citation, Trace backend, Eval runner, semantic/hybrid/vector retrieval, multi-agent handoff/workflow/replanning, HTTP/SSE, or a full query CLI.
- Do not add fallback providers, silent error swallowing, scope widening, SQL/FTS construction in the adapter, or app-level retry/degradation logic.
- Unknown tools and unexpected adapter exceptions must remain terminal and observable; only established capability errors may become typed tool results.
- Generated product code must include Simplified Chinese comments, with line-level explanation around key logic.

## Acceptance criteria

- [ ] A configured DeepSeek run can follow the OpenAI-compatible Chat Completions path and return a final answer after `search_messages` (live validation pending because no local key is available).
- [x] The runtime contract is owned by Trivae and has no SDK types in its public boundary.
- [x] The only exposed SDK tool maps typed input to `SearchMessagesTool` through `CapabilityRegistry` with the caller's trusted `ExecutionScope`.
- [x] Tool output is a safe, bounded `ToolEnvelope`; scope violations, invalid input, unavailable retrieval, and execution errors are explicit.
- [x] The SDK owns the loop and an explicit max-turn boundary produces a deterministic, visible termination result.
- [x] Runtime context and scope are not model-visible prompt/tool arguments except for the capability's typed search input.
- [x] Existing M1-M3 tests remain green without requiring a provider key during application construction.
- [x] New tests cover settings, adapter construction, tool mapping, bounded execution, and no-network integration using the SDK's test model or an equivalent deterministic seam.
- [x] `pytest`, `ruff check src tests`, `mypy src`, `python -m trivae --help`, and `python .trellis/scripts/task.py validate` pass; any pre-existing unrelated repository-wide lint issue is recorded separately.
- [x] `validation.md` records measured results, live-smoke status (`not measured / waiting for live validation` when no local key is available), and explicit out-of-scope items.

## Deferred boundary

This baseline uses the SDK's bounded run/turn limit as the first termination guard. The richer Stage 1.7 policy of a Trivae-owned investigation budget followed by graceful final synthesis is documented as a follow-up boundary and must not be faked with a second loop in M4a.
