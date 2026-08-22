# Agent Runtime Guidelines

M4a Agent Runtime 的可执行边界。该规范只覆盖单 Agent、`search_messages`、DeepSeek OpenAI-compatible Chat Completions 和 SDK-owned bounded loop；Router、Planner、Evidence、Trace backend、multi-agent 与 HTTP 均不在本规范范围内。

## 1. Scope / Trigger

- Trigger: M4a 将用户 query、OpenAI Agents SDK、DeepSeek provider、CapabilityRegistry、Retrieval 和 SQLite 串成一个跨层 vertical slice。
- Scope: `config`、`query/runtime`、Application 的 runtime 注入与对应 contract/integration tests。
- Out of scope: storage schema、ingestion、retrieval algorithm、capability semantics、Router/Planner/QueryOrchestrator、Trace backend、Evidence/Citation、semantic/vector retrieval、HTTP/SSE 和 app-level retry/fallback。

## 2. Signatures

### Runtime contract

```python
@dataclass(frozen=True)
class AgentRunRequest:
    query: str
    scope: ExecutionScope
    available_capabilities: tuple[str, ...] = ("search_messages",)

class AgentRuntime(Protocol):
    async def run(self, request: AgentRunRequest) -> RuntimeResult: ...
```

### Application composition

```python
def create_application(
    database_path: Path,
    agent_runtime: AgentRuntime | None = None,
) -> TrivaeApplication: ...

class TrivaeApplication:
    async def run_agent(self, request: AgentRunRequest) -> RuntimeResult: ...
```

The runtime is lazy or explicitly injected. `create_application` must remain usable by retrieval-only callers without provider configuration.

## 3. Contracts

### Environment

| Key | Required | Contract |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | real provider run | Non-empty secret; never logged, returned, or placed in a prompt |
| `DEEPSEEK_BASE_URL` | no | Defaults to `https://api.deepseek.com`; empty is invalid |
| `TRIVAE_MODEL_PROVIDER` | no | Defaults to `deepseek`; unsupported values fail explicitly |
| `TRIVAE_MODEL_NAME` | real provider run | Non-empty model name; no runtime hardcoded default |
| `TRIVAE_MAX_TURNS` | no | Positive integer; defaults to 8 |

### Provider path

The real provider path constructs `AsyncOpenAI(api_key, base_url)` and `OpenAIChatCompletionsModel(model, openai_client)`. Hosted SDK tracing is explicitly disabled because M4a has no Trivae Trace backend.

### Runtime result

`RuntimeResult` contains only plain Trivae-owned values: `final_answer`, `provider`, `model`, `termination`, projected `RuntimeToolCall` values, optional `RuntimeErrorInfo`, and optional numeric usage. SDK Agent/Runner/RunContext/item objects must not cross this boundary.

### Local context and tool

`RuntimeContext` carries trusted `ExecutionScope`, `CapabilityRegistry`, allowed capability names, and tool status bookkeeping. It is supplied as SDK local context and is not model-visible. The only M4a model-facing tool is `search_messages`; it maps typed arguments to `SearchMessagesInput`, calls `CapabilityRegistry.invoke`, and returns `ToolEnvelope.to_dict()`.

## 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| Blank query | `AgentRuntimeContractError`; no SDK run |
| Missing API key/model on real provider construction | `SettingsError`; no network request |
| Unsupported provider or non-positive max turns | `SettingsError`/`ValueError`; no fallback provider |
| Requested capability not registered | Explicit runtime failure; do not widen or guess capability set |
| Capability input/scope violation | Existing typed `ToolEnvelope(status="error")` with established code |
| Retrieval unavailable/invalid/failed | Existing `ToolEnvelope` error code; no silent success |
| Unknown tool or unexpected tool exception | Terminal SDK/runtime failure; never generic successful tool result |
| SDK max turns exceeded | `RuntimeResult.termination == "max_turns_exceeded"` and `MAX_TURNS_EXCEEDED` |
| Non-text final SDK output | Explicit `INVALID_FINAL_OUTPUT` runtime failure |
| Provider/network error | Explicit `RUNTIME_ERROR` with secret redaction; no retry/fallback |

The SDK owns the generic model/tool loop. Trivae must not add a second `while model -> parse -> execute` loop.

## 5. Good / Base / Bad Cases

- Good: a scripted model calls `search_messages` with a typed keyword, trusted scope reaches `CapabilityRegistry`, bounded `ToolEnvelope` returns, and the next SDK turn produces a text answer.
- Base: an application is created for import/retrieval only with no model env; construction succeeds because runtime creation is lazy.
- Bad: model-provided session/time filters exceed `ExecutionScope`; the existing capability returns `SCOPE_VIOLATION` and the runtime does not widen scope.
- Bad: an unregistered capability is requested; the runtime fails visibly rather than silently exposing another tool.
- Bad: a tool keeps requesting turns; SDK max-turn termination is visible and no manual loop synthesizes an unverified answer.
- Bad: a provider exception includes the API key; the returned error redacts the exact configured key.

## 6. Tests Required

- Settings: assert defaults, required env keys, provider/model validation, positive max turns, and secret absence from `repr`/safe projection.
- Provider construction: with a fake key and model, assert `OpenAIChatCompletionsModel` construction without a network call.
- Tool adapter: assert typed argument mapping, trusted scope identity, safe envelope projection, capability error code, and terminal propagation of unknown exceptions.
- SDK integration: use `ScriptedModel` to assert tool call → existing registry/retrieval/SQLite → tool result → final assistant output.
- Bound: script repeated tool calls and assert `max_turns_exceeded`, `MAX_TURNS_EXCEEDED`, and recorded tool calls.
- Compatibility: construct the Application and run existing M1-M3 tests without provider configuration.
- Static gates: `pytest`, `ruff check src tests`, `mypy src`, CLI help, task validation, and `git diff --check`.

## 7. Wrong vs Correct

### Wrong

```python
while not done:
    response = model(...)
    tool_args = parse(response)
    result = registry.invoke(tool_args["name"], ...)
```

This duplicates the SDK loop, risks losing SDK turn semantics, and makes provider-specific behavior part of Application logic.

### Correct

```python
result = await Runner.run(
    agent,
    request.query,
    context=runtime_context,
    max_turns=max_turns,
)
return project_to_runtime_result(result)
```

The adapter owns the Trivae boundary and projection; the SDK owns generic loop/tool protocol; the Capability layer owns scope and retrieval behavior.
