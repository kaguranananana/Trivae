# Agent Runtime and Query Execution Guidelines

M4 Query Execution Core 与 M5 Evidence Finalization 的可执行边界。Router、Planner、QueryOrchestrator 和 Answer Finalizer 是 Trivae-owned application layer；OpenAI Agents SDK 只允许出现在 runtime adapter。当前实现按本地验证的 `openai-agents==0.22.0` 编写，后续升级必须重新验证本文件的行为契约。

## 1. Scope / Trigger

- Trigger: M4a baseline 需要补齐两路 query orchestration、bounded soft planning、streaming/cancellation、tool-round finalization 和 provider/application lifecycle。
- Scope: `config`、`query`、runtime adapter、Application composition root、Capability tool adapter 及其 deterministic tests。
- Out of scope: Conversation / Assistant Message storage schema、semantic/vector/hybrid retrieval、Trace Store、Evaluation runner、HTTP/SSE、UI、multi-agent、workflow/step executor、automatic replan、app-level retry/fallback。

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
| `TRIVAE_MODEL_PROVIDER` | no | Defaults to `deepseek`；只支持 `deepseek` / `opencode-go` |
| `TRIVAE_MODEL_API_KEY` | real provider run | Non-empty secret；不得进入 prompt、事件、结果或普通日志 |
| `TRIVAE_MODEL_BASE_URL` | generic config | Non-empty OpenAI-compatible endpoint；空值显式失败 |
| `TRIVAE_MODEL_NAME` | real provider run | Non-empty model name；不在代码中假造默认模型 |
| `DEEPSEEK_API_KEY` | legacy DeepSeek only | 仅当 provider 为 `deepseek` 且 generic key 不存在时读取 |
| `DEEPSEEK_BASE_URL` | legacy DeepSeek only | 仅当 provider 为 `deepseek` 且 generic URL 不存在时读取 |
| `TRIVAE_MAX_TURNS` | no | Positive integer；默认 8；SDK absolute backstop |
| `TRIVAE_MAX_TOOL_ROUNDS` | no | Positive integer；默认 3；Trivae investigation budget |
| `TRIVAE_MAX_OUTPUT_TOKENS` | no | Positive integer；默认 16384；final synthesis bound |
| `TRIVAE_COMPLETION_MAX_TOKENS` | no | Positive integer；默认 2048；Router/Planner completion bound |

新 `TRIVAE_MODEL_*` 字段优先于 legacy 字段；变量显式存在但为空时必须报错，不能静默
回退。legacy-only DeepSeek 继续保留 `https://api.deepseek.com` 默认 URL，以兼容已有
smoke/evaluation 配置；OpenCode Go 不读取任何 `DEEPSEEK_*` 字段。`trivae chat` CLI
入口默认读取当前工作目录下存在的 `.env`，也可用 `--env-file PATH` 指定文件；进程环境
变量（包括显式空值）优先于文件值。dotenv 缺失的默认文件保持旧的环境变量启动语义，显式
文件缺失或格式错误必须在 Application 创建前报错。`load_settings()` 及其 mapping 注入
接口仍不得隐式读取工作区 credential，非 CLI 库调用不产生文件系统副作用。

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
- M5 Tool Result 额外携带 Trivae-owned `run_id`、`tool_call_id`、`tool_result_id` 和 bounded source projections；Runtime 只传递 provenance，不选择 Evidence、不拥有 Citation State Machine。
- 只有 `termination == "completed"` 的 RuntimeResult 才进入 QueryOrchestrator 的 Answer Finalizer；validated Answer Artifact 才能作为 Query 的正式 `final_answer`，invalid citation 显式失败。
- Runtime 持有 model/provider client；`aclose()` 必须真实 await `model.close()` 和 `AsyncOpenAI.close()`（若存在），且幂等。Application `aclose()` 还要释放 lexical/read/store；同步 `close()` 在 running loop 中必须显式报错并要求调用 `await aclose()`。

### Error projection

`RuntimeErrorInfo` 只允许 Trivae-owned `code/message/stage/category/diagnostic_type`。对外 message 不使用原始 provider exception body；最多保留稳定异常 type 供定位。已知 `CapabilityContractError` 仍返回 `ToolEnvelope(status="error")` 供 Agent 恢复；未知 Tool/Adapter exception 继续 terminal failure。

### Interactive streaming projection

- Provider reasoning 只允许在 SDK / Runtime adapter 边界从公开 stream event 归一化为 `thinking_delta` / `thinking_completed`；CLI 不识别 `reasoning_content` 或 provider name。没有或为空时不产生 Thinking 输出，禁止按执行状态伪造推理文字。
- `content_delta` 承载的是 Answer Artifact JSON。实时投影只能增量提取 `content_blocks[*].text`；Finalizer 仍以完整 JSON 为唯一验证边界，Conversation 只提交一次完整 Assistant message。
- Runtime event 与 Router / Planner / Tool / Retrieval 的 normalized event 由同一个进程内 `QueryStreamAdapter` 投影为 `QueryStreamEvent`；Trace Store 不是实时队列，CLI 不轮询 SQLite。
- reasoning 与 answer token delta 是 ephemeral stream facts，不能写入 Normal/Debug Trace；Trace 继续排除 hidden reasoning / Chain-of-Thought。Tool、Retrieval、Route 与 Plan 只显示真实结构化 event facts。
- Renderer 归 `interfaces` 所有，只负责 normal/verbose 格式、bounded 参数摘要、文本段换行和 terminal 恢复；Runtime、Tool、Retrieval、Router、Planner 内部不得加入 CLI print。

### CLI Product Experience boundary（2026-08-25）

- `CliEventRenderer` 继续消费 `QueryStreamEvent`，不创建第二个 Runtime、Query 或 Trace reader。
- Runtime reasoning event 仍可作为 live ordering fact 传递，但终端 normal/verbose 不渲染 hidden
  CoT；终端也不显示 raw event sequence、operation identity、JSON artifact 或 provider-specific fields。
- Source review、scope/readiness、feedback 和 history/resume 均由 `TrivaeApplication` facade
  拥有；CLI 不直接读取 SQLite、不从 prompt 推断 trusted scope。

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
| Invalid / unresolved citation after completed runtime | Query 返回 `finalization_error`；不返回 validated answer、不删除 binding、不自动修复 |
| Closed runtime/application reused | 显式 lifecycle error；不得静默重建 provider/resource |
| Provider 没有/返回空 reasoning | 不产生 Thinking；Tool、Answer 与 terminal event 正常继续 |
| Provider stream 在 answer delta 后失败 | 关闭开放文本段、显示 normalized failure；不产生 answer.completed，不提交 Conversation |
| 多轮 Tool Call | 按 Runtime/normalized event sequence 展示，不由 Renderer 推断或重排 |

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
- M5 Evidence：Answer Artifact、claim binding、finding/source contract、current-run provenance、scope/locator validation、trusted message hydration、structured result resolution、invalid citation failure。
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

## 8. OpenAI-compatible Model Provider configuration

### 1. Scope / Trigger

- Trigger：需要在不改变 Query 业务代码的情况下切换 DeepSeek 官方 API 与 OpenCode Go。
- Scope：`config/settings.py`、`OpenAIAgentsRuntimeAdapter`、provider-facing usage
  normalization 和其 deterministic/live validation。
- Boundary：Router、Planner、Tool、Retrieval、Evidence/Citation、Trace projection 和
  Evaluation 只消费 provider-neutral Runtime contract。

### 2. Signatures

```python
@dataclass(frozen=True)
class ModelSettings:
    api_key: str
    base_url: str
    provider: str
    model_name: str
    max_turns: int
    max_tool_rounds: int
    max_output_tokens: int
    completion_max_tokens: int

def load_settings(environ: Mapping[str, str] | None = None) -> ModelSettings: ...
```

Runtime 继续通过同一条构造路径创建 `AsyncOpenAI(api_key, base_url)` 和
`OpenAIChatCompletionsModel(model, openai_client)`；OpenCode Go 的 provider-facing
model value 是 `deepseek-v4-flash`，不是 `opencode-go/deepseek-v4-flash`。

### 3. Contracts

- Supported providers：`deepseek`、`opencode-go`。
- Generic env：`TRIVAE_MODEL_PROVIDER`、`TRIVAE_MODEL_API_KEY`、
  `TRIVAE_MODEL_BASE_URL`、`TRIVAE_MODEL_NAME`。
- Legacy env：只对 `deepseek` 按字段 fallback 到 `DEEPSEEK_API_KEY`、
  `DEEPSEEK_BASE_URL`。
- Safe settings projection：只暴露 `api_key_configured: bool`，不暴露 key；Trace
  记录 provider/model/normalized usage，不记录 API key 或当前 base URL。
- Usage canonical fields：`requests`、`input_tokens`、`output_tokens`、
  `total_tokens`，以及 Provider 明确返回 cache-read 时的 `cached_input_tokens`。
  缺失字段保持 absent/unknown，不写 `0`。
- OpenCode Go compatibility：当 Agent 请求包含 tools 时，Runtime adapter 移除与其
  不兼容的 `response_format=json_object`；无 tools 时保留 structured-output 请求。
  这只属于 provider normalization，不改变 Answer Finalizer contract。

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| unsupported provider | `SettingsError`，不构造 client |
| missing generic API key | `SettingsError`；只有 `provider=deepseek` 且 generic key 不存在时才读取 `DEEPSEEK_API_KEY`；`opencode-go` 永不读取 |
| missing generic base URL | `SettingsError`；legacy-only DeepSeek 才可使用旧默认 URL |
| missing model name | `SettingsError`，不发网络请求 |
| new and legacy values both set | new value wins；new empty value 显式失败 |
| provider `opencode-go` with only `DEEPSEEK_*` | `SettingsError`，不误用 legacy credential/URL |
| Provider has no cache usage field | omit `cached_input_tokens`，不能补零 |
| OpenCode Go tools + JSON mode | adapter removes `response_format` for that tool turn；不 retry/repair |
| Provider/adapter exception | secret-safe Runtime failure；不把原始 exception body 投影到业务层 |

### 5. Good / Base / Bad Cases

- Good：`.env` 选择 `opencode-go`、`deepseek-v4-flash` 和 OpenCode Go URL，CLI/Evaluation
  通过同一个 Application/Runtime path 执行。
- Good：DeepSeek legacy-only 配置仍使用旧 key/base URL；新 generic 配置覆盖同名旧值。
- Base：没有 cache details 时 usage 仍有 input/output/total，但没有
  `cached_input_tokens`。
- Bad：把 `opencode-go/deepseek-v4-flash` 传给 API，或在 Router/Planner 中复制一套
  OpenCode Go adapter。
- Bad：为 OpenCode Go tool calling 失败添加业务层 retry、citation repair 或静默降级。

### 6. Tests Required

- Settings：两个 provider load、new-first precedence、legacy fallback、empty-new
  rejection、unsupported provider、missing key/base/model、safe repr/dict。
- Adapter：same Chat Completions construction、OpenCode Go exact model/base URL、
  tool-turn JSON mode projection、DeepSeek JSON mode regression。
- Usage：flat/nested cache-read projection、缺失 cache field 不补零。
- Runtime integration：tool result、final answer、stream events、citation/finalization、
  Trace provider/model/usage 和 secret absence。
- Quality gates：`pytest -q`、`ruff check src tests`、`mypy src`、CLI help、`git diff --check`。

### 7. Wrong vs Correct

#### Wrong

```python
# 把 Provider 名称扩散到 Query/Planner，并为 OpenCode Go 复制一套 loop。
if settings.provider == "opencode-go":
    return run_opencode_specific_agent_loop(request)
```

#### Correct

```python
# 配置选择 endpoint/model；兼容差异只在同一个 Runtime adapter 归一化。
settings = load_settings()
client = AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url)
model = OpenAIChatCompletionsModel(model=settings.model_name, openai_client=client)
```

这条 contract 固化的架构原则是：Trivae Agent Runtime 依赖模型协议能力，而不依赖
具体模型厂商；支持 OpenAI-compatible Chat Completions 的 Provider 通过配置和
Runtime Adapter 接入，差异不得泄漏到业务层。
