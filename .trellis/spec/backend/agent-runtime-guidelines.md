# Agent Runtime and Query Execution Guidelines

M4 Query Execution Core 的可执行边界。Router、Planner、QueryOrchestrator 是 Trivae-owned application layer；OpenAI Agents SDK 只允许出现在 runtime adapter。当前实现按本地验证的 `openai-agents==0.22.0` 编写，后续升级必须重新验证本文件的行为契约。

## 1. Scope / Trigger

- Trigger: M4a baseline 需要补齐两路 query orchestration、bounded soft planning、streaming/cancellation、tool-round finalization 和 provider/application lifecycle。
- Scope: `config`、`query`、runtime adapter、Application composition root、Capability tool adapter 及其 deterministic tests。
- Out of scope: storage schema、semantic/vector/hybrid retrieval、Evidence/Citation、Trace Store、Evaluation runner、HTTP/SSE、UI、multi-agent、workflow/step executor、automatic replan、app-level retry/fallback。

## 2. Signatures

### Query application

```python
@dataclass(frozen=True)
class QueryRequest:
    query: str
    scope: ExecutionScope
    request_id: str | None = None
    locale: str = "zh-CN"
    prior_context: tuple[ModelContextMessage, ...] = ()
    data_snapshot: Mapping[str, object] = field(default_factory=dict)
    available_capabilities: tuple[str, ...] = ("search_messages",)

class QueryOrchestrator:
    async def run(self, request: QueryRequest) -> QueryResult: ...

class TrivaeApplication:
    async def query(self, request: QueryRequest) -> QueryResult: ...
    async def aclose(self) -> None: ...
    def close(self) -> None: ...
```

### Router and Planner

```python
class Router(Protocol):
    async def route(self, context: QueryContext) -> RouteDecision: ...

class Planner(Protocol):
    async def plan(self, context: QueryContext) -> PlannerResult: ...
```

`RouteDecision.route` 只能是 `standard_execution` 或 `planned_execution`。`Plan` 是 bounded soft guidance；`PlanStep.suggested_tools` 只作 advisory，不能被 Orchestrator 直接执行。

### Runtime

```python
@dataclass(frozen=True)
class AgentRunRequest:
    query: str
    scope: ExecutionScope
    available_capabilities: tuple[str, ...] = ("search_messages",)
    model_context: tuple[ModelContextMessage, ...] = ()
    plan_guidance: str | None = None
    request_id: str | None = None

class AgentRuntime(Protocol):
    async def run(self, request: AgentRunRequest) -> RuntimeResult: ...

class AgentRuntimeStreaming(AgentRuntime, Protocol):
    def stream(
        self, request: AgentRunRequest, abort_event: object | None = None
    ) -> AsyncIterator[RuntimeEvent]: ...
```

`RuntimeEvent.type` 至少覆盖 `run_started`、`turn_started`、`content_delta`、`tool_started`、`tool_completed`、`turn_completed`、`usage_update`、`finalizing`、`completed`、`failed`、`aborted`。SDK raw event 不得越过 adapter。

## 3. Contracts

### Environment

| Key | Required | Contract |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | real provider run | Non-empty secret；不得进入 prompt、事件、结果或普通日志 |
| `DEEPSEEK_BASE_URL` | no | Defaults to `https://api.deepseek.com`；空值显式失败 |
| `TRIVAE_MODEL_PROVIDER` | no | Defaults to `deepseek`；不支持的 provider 显式失败 |
| `TRIVAE_MODEL_NAME` | real provider run | Non-empty model name；不在代码中假造默认模型 |
| `TRIVAE_MAX_TURNS` | no | Positive integer；默认 8；SDK absolute backstop |
| `TRIVAE_MAX_TOOL_ROUNDS` | no | Positive integer；默认 3；Trivae investigation budget |

### Query boundary

- `QueryRequest.scope` 是可信本地对象，只在 `RuntimeContext` / Capability tool path 中进行 identity/enforcement。
- `prior_context` 只允许 bounded `user` / `assistant` plain messages；`data_snapshot` 是显式的 compact model context。
- Runtime input 可以包含 prior messages、query 和 validated plan guidance，但不得拼接 `ExecutionScope`、registry object、SQLite object 或 provider secret。
- standard 和 planned 必须共享同一个 `AgentRuntime` 实例与同一个 `CapabilityRegistry`；planned path 唯一额外行为是 `Plan` 转成 soft instruction。

### Router boundary

- Rule-first；无法证明 planning value 时 conservative 到 `standard_execution`。
- 结构信号包括 multi-goal dependency、temporal/state transition、cross-stage evidence、dependent semantic investigation、explicit recovery/reformulation。
- 单个“分析/总结/比较/最近一年/证据”不得独立触发 planned；数据范围大小和 tool call 数也不是 planning complexity。
- LLM fallback 只解析 strict JSON `route/confidence/reason`；invalid JSON、unknown route、timeout、provider error 都保留静态判断并设置 degraded code。

### Planner boundary

- Planner 只运行一次；最大 5 个 step、最大 5 个 success criterion，字段有限长。
- unknown `suggested_tools` filter out，重复 tool hint / evidence criterion dedupe；空或结构无效 plan 返回 `PlannerFailure`。
- Planner failure (`unavailable`、`timeout`、`generation_error`、`invalid_output`、`aborted`) 不阻塞同一 Runtime；必须留下 degraded diagnostic。
- `render_plan_guidance(plan)` 是文字提示，禁止 `for step in plan.steps: execute(...)`、replan、DAG 或 planner-owned state。

### Runtime and lifecycle

- SDK `Runner.run_streamed` 是唯一通用 Agent loop；`run()` 只是完整消费 `stream()`。
- 同一模型 turn 产生一个或多个 Tool Call 并形成 Tool Result，计为一个 `tool_round`。达到 `max_tool_rounds` 后进入 `finalizing`，清空 agent tools，允许额外一次无工具 final synthesis；正常结果为 `completed`。
- `max_turns` 只作 SDK absolute backstop；撞上时 `termination == "max_turns_exceeded"`、error code `MAX_TURNS_EXCEEDED`、category `absolute_backstop`。
- `completed` 只能在 SDK `stream_events()` 完整消费和 cleanup 后发出。abort 是 terminal intent：不启动新 model/tool work，不做 final synthesis，不发 `completed`；最终 termination 为 `aborted`。
- Runtime 持有 model/provider client；`aclose()` 必须真实 await `model.close()` 和 `AsyncOpenAI.close()`（若存在），且幂等。Application `aclose()` 还要释放 lexical/read/store；同步 `close()` 在 running loop 中必须显式报错并要求调用 `await aclose()`。

### Error projection

`RuntimeErrorInfo` 只允许 Trivae-owned `code/message/stage/category/diagnostic_type`。对外 message 不使用原始 provider exception body；最多保留稳定异常 type 供定位。已知 `CapabilityContractError` 仍返回 `ToolEnvelope(status="error")` 供 Agent 恢复；未知 Tool/Adapter exception 继续 terminal failure。

## 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| Blank query / invalid scope / duplicate capability | Contract error；不启动 SDK |
| Missing provider key/model | `SettingsError`；不网络请求、不切 provider |
| Invalid route completion | 保留 rule decision；`degraded=True`，不让 Query 失败 |
| Planner unavailable/timeout/invalid output | `plan=None` + degraded diagnostic；仍调用同一 Runtime |
| Capability not registered | 显式 runtime/orchestrator failure；不扩大 whitelist |
| Scope/input violation | 既有 typed `ToolEnvelope` error code；不把 scope 放进 prompt |
| Known Tool contract/retrieval error | Agent 收到 `status=error` envelope，可决定恢复 |
| Unknown Tool/adapter exception | terminal `RUNTIME_ERROR`；不伪装 successful tool result |
| Product tool budget exhausted | `finalizing` + tools hidden + extra final call + `completed` |
| SDK absolute max turns | `max_turns_exceeded` + `MAX_TURNS_EXCEEDED` + `absolute_backstop` |
| Non-text final output | `failed` + `INVALID_FINAL_OUTPUT` |
| Provider/network exception | `failed` + secret-safe `RUNTIME_ERROR`；无 retry/fallback |
| User abort before/during run | `aborted`；无 final synthesis、无 completed，等待 SDK cleanup |
| Closed runtime/application reused | 显式 lifecycle error；不得静默重建 provider/resource |

## 5. Good / Base / Bad Cases

- Good: 一个模型 turn 发出两个 `search_messages` call，两个结果完成后只计一轮，达到预算进入 finalizing，第二个 model call 没有 tools 并返回 completed。
- Good: planned 查询获得 validated plan guidance，但 runtime 仍使用同一 registry 和同一实例；scope identity 在 tool invoke 中保持不变。
- Base: 没有 provider env 时创建 retrieval-only Application 成功；只有 query/runtime invocation 才读取 provider settings。
- Bad: 因为 query 含“分析”而把“分析谁发言最多”路由为 planned。
- Bad: 把 `ExecutionScope` 拼进 system prompt 或作为模型 tool 参数，试图用软提示代替本地 enforcement。
- Bad: Planner step 逐条调用 tool、遇到失败自动 replan，或把 SDK raw event 直接返回接口层。
- Bad: 正常 tool budget exhaustion 被误报成 `MAX_TURNS_EXCEEDED`，或 provider exception 全文进入 `RuntimeErrorInfo.message`。

## 6. Tests Required

- Router：standard/planned、ambiguous injected completion、valid/invalid/unknown/exception、conservative degraded、单关键词不 over-route。
- Planner：valid bounded、unknown filter、dedupe、oversized 5/5、malformed/structural failure、unavailable skip、guidance 不含 executable state。
- Orchestrator：两路共享 runtime、scope identity、whitelist、router/planner degraded 仍执行、scope 不进入 model input。
- Runtime：既有 SQLite/tool pipeline、known error recovery、unknown terminal error、multiple calls one round、budget finalization/tool invisibility、SDK backstop、invalid final、secret-safe provider failure、stream/content/tool/usage events、abort before/during/late result、completed-after-cleanup、idempotent close。
- Application：无 provider 的 retrieval-only construction、query 进入 Orchestrator、async/sync lifecycle 和所有已创建 resources close。
- Static gates：`pytest -q`、`ruff check src tests`、`mypy src`、CLI help、Trellis validation、`git diff --check`；live DeepSeek smoke 只能 opt-in，不进入默认 suite。

## 7. Wrong vs Correct

### Wrong

```python
for step in plan.steps:
    registry.invoke(step.suggested_tools[0], step.args)
```

这会把 advisory plan 变成第二套 workflow/step executor，绕过 SDK Agent Loop、Scope enforcement 与真实 tool selection。

### Correct

```python
plan_guidance = render_plan_guidance(validated_plan)
runtime_request = request.to_runtime_request(plan_guidance)
result = await same_runtime.run(runtime_request)
```

Orchestrator 只编译 context 与 guidance；SDK loop、tool choice、typed arguments 和 Capability execution 继续由各自 ownership 负责。
