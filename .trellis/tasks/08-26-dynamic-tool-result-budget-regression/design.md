# Dynamic Tool Result Budget / Quality Regression Design

## 1. Problem and boundary

当前 `project_tool_result_for_model()` 已经能接受显式 token budget，也能生成截断/省略/provenance metadata；但 runtime 中的各 Tool adapter 没有传入 per-call budget，始终依赖固定 16,000 默认值。与此同时，settings 不保存 context window，RuntimeContext 也没有 run-level 的累计账本，因此 64k/128k context 的模型不能获得可解释的更大 Tool Result，多个 Tool 调用也无法共享上限。

问题归属 Agent Runtime 到 Evidence projection 的边界：检索层决定 candidate 的数量和 canonical 完整性，projection 层决定模型可见字节/token 上限，runtime 才知道一次 run 中哪些调用需要从同一个池子扣减。最小修复是补齐这条已经存在的预算传递链，不改变 retrieval acquisition。

## 2. Ownership and data flow

```text
env/settings
    ↓ immutable budget config
OpenAIAgentsRuntimeAdapter
    ↓ fresh policy per run
RuntimeContext
    ↓ reserve effective budget before each tool call
SDK Tool adapter → canonical ToolEnvelope/ToolResultRecord
    ↓ project with reserved budget
project_tool_result_for_model()
    ↓ actual projected estimated tokens
policy.complete_call()
    ↓ snapshot on RuntimeToolCall
TraceCollector → tool.completed timeline + terminal run summary
```

- `config/settings.py` owns parsing and validation of user configuration。
- `query/runtime/budget.py` owns typed policy resolution, reservations, and run-level accounting。
- `RuntimeContext` owns one policy instance per run, but does not own Evidence state。
- `openai_tools.py` owns the adapter boundary that reserves, projects, completes accounting, and stores the immutable snapshot。
- `query/evidence.py` continues to own canonical/model projection mechanics and provenance synchronization。
- `observability/collector.py` owns normalized Trace serialization of facts。
- retrieval modules continue to own result limits; they do not import or calculate runtime model budgets。

## 3. Policy model

### 3.1 Types

Use a small typed module with no provider-specific model registry:

- `ToolResultBudgetMode = Literal["fixed", "dynamic"]`。
- `ContextWindowSource = Literal["explicit_config", "fallback", "not_used"]`。
- immutable `ToolResultBudgetConfig` stores mode, optional context window, percent, absolute cap, and fixed fallback。
- mutable per-run `ToolResultBudgetPolicy` stores remaining pool and outstanding reservations。
- immutable `ToolResultBudgetCall` identifies a reserved call。
- immutable `ToolResultBudgetSnapshot` is the Trace/Runtime record after projection。

### 3.2 Resolution

For `fixed`:

- each call receives 16,000;
- no run pool is exposed because fixed mode preserves the existing per-call contract;
- source is `not_used` and resolution is `configured`。

For `dynamic` with explicit positive context window:

- `run_pool = min((context * percent) // 100, absolute_cap)`;
- per-call ceiling is the absolute cap;
- `begin_call()` reserves `min(per_call_ceiling, remaining)` before invoking the tool;
- `complete_call()` measures actual projected tokens and returns unused reservation to the pool before subtracting the actual amount;
- the remaining value is never negative and the sum of completed actual projections cannot exceed the run pool。

For `dynamic` without explicit context window:

- source is `fallback`;
- resolution is `fallback_fixed`;
- the run-level pool is 16,000 and the per-call ceiling is also 16,000, the known safe baseline;
- this fallback still uses the same shared accounting path, so multiple calls cannot each receive an independent 16,000;
- no guessed context and no pseudo-precise run pool is emitted。

The policy is synchronous and lives in one RuntimeContext, so sequential and same-turn parallel Tool calls cannot independently reset the budget. If a dynamic pool is exhausted, `begin_call()` raises a typed runtime error; this is an explicit operational failure rather than a hidden new budget.

### 3.3 Estimation and projection

The existing bounded estimate in `evidence.py` remains the measurement source. The policy does not claim provider token precision. The adapter passes the reserved effective budget into the existing projection function, then calls `complete_call()` with the projection's measured estimate. Existing binary-search/direct-hit trimming remains unchanged, preserving its linear/bounded behavior and source-handle synchronization.

## 4. Configuration and runtime integration

Add four settings fields with safe defaults. Parse them using the same settings error boundary as existing provider settings. The adapter constructs a config from `ModelSettings` and creates a fresh policy inside `_build_context()` for every run. Direct test construction of `RuntimeContext` gets a fixed default policy so existing SDK-independent callers keep the original contract.

The adapter and Tool adapters must not infer context from a model string. A future verified provider metadata source can populate the same explicit field; this task does not add that registry.

## 5. Trace contract

`RuntimeToolCall` carries the final `ToolResultBudgetSnapshot` in addition to existing projection fields. A `tool.completed` event serializes the snapshot as a bounded nested object. The terminal runtime event keeps:

- aggregate projected tokens, truncation count, omitted context count, and omitted hit count;
- the configured run-level mode/source/pool;
- the final remaining pool;
- bounded per-call snapshots for attribution.

This gives both “why this call was truncated” and “how much of the run pool remains” without storing model hidden reasoning or duplicating the full Tool Result body.

## 6. Evaluation and benchmark design

Operational extraction adds budget facts to the existing evaluation measurement, while quality labels remain independent. Synthetic cases use deterministic envelopes with controlled message sizes and run the policy at 100/300/1000 candidate scales through Agent and HTTP entry points where those adapters are available. The benchmark reports measured latency, calls, estimated projected tokens, truncation, and omissions; it does not report answer correctness without labels.

Real A/B, when credentials are available, replays the exact four recovered prompts under the same code revision. The only experimental variable is budget mode/context configuration. Each case has fixed and dynamic runs (at least three each), and the final report includes trace identifiers, per-case attribution, aggregate deltas, and any unchanged/missed evidence. If credentials are unavailable, the validation report records the environment check and marks real A/B blocked.

## 7. Alternatives and trade-offs

| Option | Decision | Reason |
| --- | --- | --- |
| Keep fixed 16k everywhere | Not selected | It is compatible but cannot test or use explicit larger context windows, and leaves the multi-call accounting gap unresolved。 |
| Guess context from model name | Permanently rejected | Model strings are not verified capacity metadata; the result would be pseudo-precision and an unstable hidden registry。 |
| Add a tokenizer/provider usage dependency | Currently unnecessary | Existing projection already has a bounded estimate and provider usage is not available before the next model turn; revisit only if measured evaluation needs token-level billing precision。 |
| Give every Tool call a fresh dynamic pool | Permanently rejected | It defeats the run-level cap and can accumulate unbounded model-visible evidence across multi-tool runs。 |
| Rewrite retrieval budgets or prompt guidance | Permanently rejected for this task | The previous retrieval contract is an independent ownership boundary; changing it would confound the A/B experiment。 |

## 8. Failure handling

- Invalid env values fail at settings load with an explicit typed error。
- Invalid policy inputs fail at policy construction/reservation with an explicit error。
- Projection failure remains terminal and is not replaced with a smaller hidden budget。
- A real provider/API transient failure remains governed by the existing runtime/provider boundary; this task adds no retry or compatibility branch。
- Trace records the resolved source and projection outcome even when a Tool call completes with truncation; truncation is not silently converted to a quality verdict。

## 9. Verification questions

1. Does the same policy instance account for every Tool call in one run?
2. Can a Trace explain both configured context and actual per-call projection?
3. Does canonical data remain complete after model projection?
4. Do direct hits and current-run source handles remain unchanged?
5. Do fixed-mode and existing retrieval tests prove compatibility?
6. Does the synthetic benchmark show measured cost without conflating quality?
7. What evidence would justify a verified metadata resolver or tokenizer later?
