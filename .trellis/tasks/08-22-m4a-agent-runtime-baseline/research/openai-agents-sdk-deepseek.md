# M4a Research Notes — OpenAI Agents SDK and DeepSeek

## Sources checked

- OpenAI Agents SDK configuration: https://openai.github.io/openai-agents-python/config/
- OpenAI Agents SDK model/provider integration: https://openai.github.io/openai-agents-python/models/
- OpenAI Agents SDK running agents and `max_turns`: https://openai.github.io/openai-agents-python/running_agents/
- OpenAI Agents SDK local context boundary: https://openai.github.io/openai-agents-python/context/
- OpenAI Agents SDK deterministic testing: https://openai.github.io/openai-agents-python/testing/
- DeepSeek function calling guide: https://api-docs.deepseek.com/guides/function_calling/
- DeepSeek Chat Completions API: https://api-docs.deepseek.com/api/create-chat-completion
- Python package release metadata: https://pypi.org/project/openai-agents/

## Findings

1. The Agents SDK provides an `AsyncOpenAI` client path and supports a custom `OpenAIChatCompletionsModel`. The model documentation describes Chat Completions as the compatibility path for providers that do not expose the Responses API.
2. The SDK `Runner` owns the generic agent loop and exposes a bounded `max_turns` control. M4a should call the runner once and map the SDK's terminal result/exception instead of duplicating the loop.
3. SDK local context is supplied to tools and the runner but is not automatically sent to the model. This fits Trivae's trusted `ExecutionScope` and capability-registry boundary.
4. The SDK testing support includes a deterministic scripted model that can exercise assistant messages and function calls without a live API request. This is the preferred integration seam for M4a tests.
5. The SDK configuration documentation says tracing is enabled by default in some paths and exposes an explicit disable operation. M4a has no normalized Trace backend, so hosted tracing must be disabled for the baseline unless intentionally configured.
6. DeepSeek documents an OpenAI-compatible API with base URL `https://api.deepseek.com` and function/tool calling through Chat Completions. The baseline therefore uses `DEEPSEEK_BASE_URL` with that default and never hardcodes a key.
7. The current package page lists `openai-agents` 0.22.0 as the latest release at planning time. Pinning a tested compatible range is preferable to allowing an unbounded SDK API change during this task.

## Decisions

- Use `AsyncOpenAI` plus `OpenAIChatCompletionsModel` for DeepSeek.
- Keep SDK imports confined to `query/runtime` adapter modules and tests.
- Use `max_turns` as the M4a termination backstop; defer the richer Trivae-owned graceful-final-synthesis policy.
- Use the SDK scripted test model for no-key integration tests.
- Disable hosted tracing and do not add a Trace backend in M4a.

## Verification caveat

The exact import names and exception/result shapes must be checked against the dependency version installed by the implementation environment. Any adjustment should stay inside the adapter/test seam and must not leak SDK types into lower-layer contracts.
