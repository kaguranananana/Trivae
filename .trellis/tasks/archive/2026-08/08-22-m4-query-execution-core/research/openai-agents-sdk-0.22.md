# OpenAI Agents SDK 0.22 Research

## Measured local version

The repository virtual environment reports `openai-agents 0.22.0` and `openai 3.3.1`. The implementation uses the installed API rather than assuming a newer SDK.

## Relevant API behavior

- `Runner.run_streamed(...)` returns `RunResultStreaming`; `stream_events()` must be fully consumed before treating a run as settled.
- `RunResultStreaming.cancel("immediate")` cancels the active run and its tasks; callers still need to complete stream cleanup.
- `RunHooks` provides async LLM/tool lifecycle hooks. Hooks can observe a tool result and mutate the agent tool list before the next model turn.
- Dynamic agent instructions can read runtime context, which permits finalization guidance without implementing a second model loop.
- `RunConfig(tracing_disabled=True)` is available and is passed explicitly to keep tests and provider runs deterministic with respect to tracing.
- `AsyncOpenAI.close()` is asynchronous. `OpenAIChatCompletionsModel.close()` is asynchronous and may be a no-op, so the adapter owns and closes both where applicable.

## Implementation consequence

Trivae will use the SDK runner as the canonical loop, project raw text deltas and hook observations into its own `RuntimeEvent`, and distinguish normal Trivae budget finalization from `MaxTurnsExceeded`. No SDK raw event, exception body or provider secret crosses the runtime contract.
