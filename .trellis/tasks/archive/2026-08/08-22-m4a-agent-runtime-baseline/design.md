# M4a Agent Runtime Baseline — Technical Design

## Change boundary

M4a adds one runtime composition layer above the existing M1-M3 application. It does not change the storage schema, ingestion, retrieval algorithms, capability semantics, or the existing `ExecutionScope` boundary. The new layer owns provider configuration, SDK construction, model-visible instructions, SDK tool registration, lifecycle/result mapping, and explicit bounded termination.

The intended ownership split is:

| Concern | Owner |
| --- | --- |
| Model provider configuration and client construction | `config` plus runtime adapter |
| Generic agent loop, tool-call protocol, turn accounting | OpenAI Agents SDK |
| Runtime lifecycle and Trivae result contract | Trivae `AgentRuntime` / adapter |
| Trusted scope and capability dispatch | existing Application/Capability layer |
| Search/filter/context behavior | existing `SearchMessagesTool` and Retrieval layer |
| Storage and FTS | existing Data layer |
| Normalized trace backend | deferred; tracing is explicitly disabled when unsupported |

## Runtime contracts

Add SDK-independent contracts under `src/trivae/query/runtime/`:

- `AgentRunRequest`: query text, trusted `ExecutionScope`, and the names of capabilities explicitly allowed for this run.
- `RuntimeContext`: process-local scope, capability registry, and small execution bookkeeping. This object is supplied as SDK local context and is never serialized into the prompt.
- `RuntimeResult`: final answer or explicit terminal error, provider/model identity, termination reason, tool count/statuses, and optional usage metadata projected into plain Python values.
- `AgentRuntime` protocol: one asynchronous `run(request)` operation.

The exact dataclass field names may be refined after checking the installed SDK version, but the public boundary must remain free of `Agent`, `Runner`, `RunContextWrapper`, `ModelSettings`, or other SDK types. Invalid request values fail at the contract boundary with a typed, visible error.

## Provider construction

`src/trivae/config/settings.py` reads environment variables at call time through a small settings loader; it must not create clients at import time. The baseline provider path is:

1. Read `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `TRIVAE_MODEL_PROVIDER`, and `TRIVAE_MODEL_NAME`.
2. Validate required values and supported provider selection.
3. Construct `AsyncOpenAI(api_key=..., base_url=...)`.
4. Construct `OpenAIChatCompletionsModel(model=..., openai_client=...)`.
5. Construct an SDK `Agent` with the short Trivae system prompt and the one registered tool.
6. Run it through the SDK `Runner` with an explicit `max_turns`.

Use the Chat Completions model path because DeepSeek documents an OpenAI-compatible Chat Completions endpoint and the Agents SDK documents `OpenAIChatCompletionsModel` for providers that do not expose the Responses API. The runtime must not silently switch to another provider or endpoint.

Provider metadata may be returned in `RuntimeResult`, but the API key must never be included in results, logs, prompts, exceptions, or test snapshots. If tracing is enabled by the SDK by default, disable hosted tracing explicitly for this provider unless a supported tracing credential is intentionally configured; M4a has no Trivae Trace backend.

## SDK tool adapter

`openai_tools.py` contains the only model-facing tool for M4a, `search_messages`:

1. The SDK validates/decodes the model's JSON arguments into the adapter's typed input.
2. The adapter converts only the search fields into existing `SearchMessagesInput`.
3. It calls `CapabilityRegistry.invoke("search_messages", input, trusted_scope)`.
4. It projects the returned `ToolEnvelope` through `to_dict()` and returns only safe bounded fields.
5. Established capability errors are represented by the existing envelope contract. Unknown tool names, scope bypass attempts, and unexpected exceptions are allowed to fail visibly; they are not swallowed into a generic successful response.

The adapter receives trusted scope and registry through SDK local context. The model cannot choose session scope, timestamps outside the request, a different registry, SQL, FTS syntax, or context limits. `available_tools` is checked by Trivae before registration; the model cannot widen it.

## Prompt

Use a short system prompt with these rules:

- answer the user's question using available Trivae messages;
- call `search_messages` when evidence from messages is needed;
- do not claim a search result that the tool did not return;
- do not expose internal scope, SQL, registry, runtime, or trace details;
- if the tool reports no results or an error, state that plainly.

The prompt is guidance, not a security boundary; the real boundary remains typed input, trusted local context, capability enforcement, and safe projection.

## Execution and termination

The adapter calls the SDK runner once. It does not contain a manual model/tool loop. The SDK's `max_turns` is the M4a backstop and must be a configured, positive value. The adapter maps normal completion and the SDK's max-turn exception to explicit `RuntimeResult.termination` values. Unexpected provider or adapter errors remain explicit runtime errors with no fallback answer.

M4a deliberately does not implement the later Trivae investigation-budget/graceful-final-synthesis policy. That policy is captured as a deferred design item so the baseline does not create a second loop or pretend to have the stronger contract.

## Application composition and lifecycle

Keep `create_application(database_path)` usable by existing retrieval-only tests and callers. Construct the store/read/retrieval/capability graph as today; instantiate settings, provider client, SDK agent, and runtime only when `run_agent` is invoked or when a test/runtime is explicitly injected. This is a lifecycle/compatibility choice, not a provider fallback: a real run still fails clearly when its required key/model configuration is absent.

The application owns the runtime reference and closes existing database/index resources as it already does. If the SDK client exposes no required close hook, do not invent one; avoid retaining a client after application close. Do not introduce import-time global clients or databases.

## Test seams

- Settings tests use isolated environment mappings and assert defaults, required fields, provider selection, and secret redaction.
- Tool adapter tests use a real `CapabilityRegistry` with a fake/in-memory retrieval seam or the existing test database, and assert scope propagation, safe output, typed error projection, and no SDK types in the capability boundary.
- Runtime tests use the OpenAI Agents SDK deterministic testing model (`ScriptedModel`) or the version-correct equivalent to exercise the real SDK tool pipeline without network access.
- Integration tests script a tool call followed by a final assistant message and assert the existing SQLite/retrieval path is reached exactly through the capability registry.
- Bound tests script a model that does not terminate and assert the SDK max-turn result is explicit.
- Existing M1-M3 tests must continue to construct the application without provider configuration.

## Trade-offs and rollback

The first version keeps provider configuration narrow and DeepSeek-specific because the requested vertical slice needs one real provider, not a speculative provider framework. `TRIVAE_MODEL_PROVIDER` still exists as a validated selector so the boundary is explicit and future providers can be added without leaking SDK details into lower layers.

If the SDK version changes its test-model or Chat Completions APIs, update only the runtime adapter/test seam after checking the pinned dependency's public API. Rollback is limited to removing the new config/query-runtime files and the application runtime entry point; M1-M3 data, retrieval, and capability code remain unchanged.
