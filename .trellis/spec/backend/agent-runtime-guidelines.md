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
| `TRIVAE_TOOL_RESULT_BUDGET_MODE` | no | `fixed` / `dynamic`；默认 `dynamic` |
| `TRIVAE_MODEL_CONTEXT_WINDOW_TOKENS` | dynamic 可选 | 显式正整数；未提供时不从 model name 猜测 |
| `TRIVAE_PER_CALL_TOOL_RESULT_PERCENT` | no | 1–100 整数；默认 50；只参与 per-call ceiling |
| `TRIVAE_PER_CALL_TOOL_RESULT_CAP` | no | 正整数；默认 128000；per-call absolute cap |
| `TRIVAE_RUN_TOOL_EVIDENCE_PERCENT` | no | 1–100 整数；默认 25；只参与 run-level pool |
| `TRIVAE_RUN_TOOL_EVIDENCE_CAP` | no | 正整数；默认 256000；run-level absolute cap |
| `TRIVAE_RUN_TOOL_EVIDENCE_BUDGET` | dynamic 可选 | 已解析 context 下的实验/校准 pool override |

新 `TRIVAE_MODEL_*` 字段优先于 legacy 字段；变量显式存在但为空时必须报错，不能静默
回退。legacy-only DeepSeek 继续保留 `https://api.deepseek.com` 默认 URL，以兼容已有
smoke/evaluation 配置；OpenCode Go 不读取任何 `DEEPSEEK_*` 字段。`trivae chat` CLI
入口默认读取当前工作目录下存在的 `.env`，也可用 `--env-file PATH` 指定文件；进程环境
变量（包括显式空值）优先于文件值。dotenv 缺失的默认文件保持旧的环境变量启动语义，显式
文件缺失或格式错误必须在 Application 创建前报错。`load_settings()` 及其 mapping 注入
接口仍不得隐式读取工作区 credential，非 CLI 库调用不产生文件系统副作用。

Tool Result projection 是独立于 retrieval 与 answer 的预算。fixed 模式继续按每次 Tool 16000
estimated tokens；dynamic 按 explicit context → verified model registry → 16k fallback 解析 context。
per-call ceiling 使用 `min(floor(context_window_tokens * 50 / 100), 128000)`，run-level pool 使用独立的
`min(floor(context_window_tokens * 25 / 100), 256000)`。每次 Tool 从同一个 Runtime run pool 预留并在
projection 后按实际 estimate 结算；dynamic context 未知时 per-call 和 shared run pool 都是 16000，
不为每次调用重新发放一份预算。非法配置和 pool 耗尽均显式失败，不通过 provider/model name 猜测、retry
或静默降级掩盖。

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
- `RuntimeEvent(tool_completed)` additive 携带同一 `tool_call_id` 的 `ToolResultRecord`；hook 找不到
  call 或 result record 时显式失败。接口层只从该 canonical bounded record 生成 UI-safe detail，
  不读取 provider raw result、Trace Store、数据库或 Capability。
- Tool Result projection 的 dynamic budget 由一个 Runtime run policy 共享；Trace 必须同时保留 per-call effective/actual/remaining 与 terminal pool summary，不能把固定 retrieval limit 或一次调用上限当作累计预算。
- 只有 `termination == "completed"` 的 RuntimeResult 才进入 QueryOrchestrator 的 Answer Finalizer；valid/degraded Answer Artifact 才能作为 Query 的正式 `final_answer`，trusted provenance/scope/canonical failure 仍显式失败。
- Runtime 持有 model/provider client；`aclose()` 必须真实 await `model.close()` 和 `AsyncOpenAI.close()`（若存在），且幂等。Application `aclose()` 还要释放 lexical/read/store；同步 `close()` 在 running loop 中必须显式报错并要求调用 `await aclose()`。

### Error projection

`RuntimeErrorInfo` 只允许 Trivae-owned `code/message/stage/category/diagnostic_type`。对外 message 不使用原始 provider exception body；最多保留稳定异常 type 供定位。已知 `CapabilityContractError` 仍返回 `ToolEnvelope(status="error")` 供 Agent 恢复；未知 Tool/Adapter exception 继续 terminal failure。

### Interactive streaming projection

- Provider reasoning 只允许在 SDK / Runtime adapter 边界从公开 stream event 归一化为 `thinking_delta` / `thinking_completed`；接口层不识别 `reasoning_content` 或 provider name。`turn_started` 作为真实生命周期可投影无正文 `thinking.started`；没有 public summary 时不得产生推理文字。
- Reasoning 可见性由 `QueryStreamAdapter` 单点裁决（2026-08-27 起）：只有 adapter 显式附加
  `thinking_visibility="public_summary"` 的 delta 才可视，默认交互界面（Textual TUI）按此标记
  渲染思考正文；未标记的 reasoning 是私密 CoT，连 UI state 都不进入。`CliEventRenderer`
  （`--plain`/非 TTY）继续静默，避免平铺推理污染 CI 与日志重定向。
- `content_delta` 承载的是 Answer Artifact JSON。实时投影只能增量提取 `content_blocks[*].text`；Finalizer 仍以完整 JSON 为唯一验证边界，Conversation 只提交一次完整 Assistant message。
- Runtime event 与 Router / Planner / Tool / Retrieval 的 normalized event 由同一个进程内 `QueryStreamAdapter` 投影为 `QueryStreamEvent`；Trace Store 不是实时队列，CLI 不轮询 SQLite。
- QueryStreamAdapter 为每个模型 turn 开闭独立 Thinking 段；Tool、Answer、turn terminal 都是幂等
  关闭边界。Tool detail 与 normalized summary 可乱序到达，但必须按 `tool_call_id` 合并同一块。
- normalized retrieval 的 `parent_operation_id` 是唯一 Tool correlation；缺关联时独立展示，禁止按
  当前运行 Tool、事件相邻性或 tool name 猜测。
- reasoning 与 answer token delta 是 ephemeral stream facts，不能写入 Normal/Debug Trace；Trace 继续排除 hidden reasoning / Chain-of-Thought。Tool、Retrieval、Route 与 Plan 只显示真实结构化 event facts。
- Renderer 归 `interfaces` 所有，只负责 normal/verbose 格式、bounded 参数摘要、文本段换行和 terminal 恢复；Runtime、Tool、Retrieval、Router、Planner 内部不得加入 CLI print。

### CLI Product Experience boundary（2026-08-25）

- `CliEventRenderer` 继续消费 `QueryStreamEvent`，不创建第二个 Runtime、Query 或 Trace reader。
- Runtime reasoning event 仍可作为 live ordering fact 传递；默认 TUI 只渲染 adapter 标记为
  `public_summary` 的正文，hidden CoT 对任何界面都不渲染。终端也不显示 raw event sequence、
  operation identity、JSON artifact 或 provider-specific fields。
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
| Dynamic Tool Result run pool exhausted | explicit `TOOL_RESULT_BUDGET_EXHAUSTED` runtime failure；不发放新的 Tool Result budget |
| Invalid Tool Result budget configuration/accounting | explicit `TOOL_RESULT_BUDGET_ERROR`；不静默改用另一预算 |
| SDK absolute max turns | `max_turns_exceeded` + `MAX_TURNS_EXCEEDED` + `absolute_backstop` |
| Non-text final output | `failed` + `INVALID_FINAL_OUTPUT` |
| Provider/network exception | `failed` + secret-safe `RUNTIME_ERROR`；无 retry/fallback |
| User abort before/during run | `aborted`；无 final synthesis、无 completed，等待 SDK cleanup |
| Local invalid citation/metadata after completed runtime | 保留可读答案，丢弃局部 citation/字段并返回 `degraded`；不伪造 binding |
| Trusted provenance/scope/canonical citation failure | Query 返回 `finalization_error`；不返回 Artifact、不自动修复 |
| Closed runtime/application reused | 显式 lifecycle error；不得静默重建 provider/resource |
| Provider 没有/返回空 reasoning | 可显示无正文 model-turn activity；不产生推理文字，Tool、Answer 与 terminal 正常继续 |
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
- Runtime：既有 SQLite/tool pipeline、known error recovery、unknown terminal error、multiple calls one round、Tool Result dynamic/fixed budget accounting、budget finalization/tool invisibility、SDK backstop、invalid final、secret-safe provider failure、stream/content/tool/usage events、abort before/during/late result、completed-after-cleanup、idempotent close。
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

## 9. Evidence-backed finalization and provider process boundary（2026-08-25）

### 1. Scope / Trigger

- Trigger：真实 Trace 暴露 structured citation 复制大型 `value_snapshot` 易失败、答案缺少
  URL/Evidence、provider `reasoning_summary_text` 可能仍是 hidden scratchpad，以及最终 JSON 在
  推理预算耗尽时未闭合的问题。
- Scope：`query/evidence.py`、`query/runtime/prompt.py`、`query/runtime/openai_adapter.py`、
  `query/streaming.py`、`observability/collector.py` 与 CLI projection。
- Boundary：不放宽 current-run provenance、scope、locator 或 explicit value equality；不公开
  hidden CoT，不新增 retry、citation repair 或第二套检索链。

### 2. Signatures

```python
def validate_answer_artifact(
    artifact: AnswerArtifact,
    *,
    run_id: str | None,
    tool_results: tuple[ToolResultRecord, ...],
    scope: ExecutionScope,
    accepted_run_ids: tuple[str, ...] = (),
) -> AnswerArtifact: ...

def extract_urls(value: object) -> tuple[str, ...]: ...

class QueryStreamAdapter:
    def handle_runtime_event(self, event: RuntimeEvent) -> None: ...
    def handle_normalized_event(self, event: NormalizedQueryEvent) -> None: ...
```

新的 model source 最小提交字段是当前 Tool Result projection 返回的短 `source_id` handle；
handle 只在当前 Run/Tool Result scope 有效。Host record 才保留 `run_id`、`tool_call_id`、
`tool_result_id`、`result_item_id`、`session_id`、`internal_message_id`，Finalizer 解析 handle
后写入 validated Artifact。旧 Artifact 的完整 source locator 仍可显式读取和校验，不能把旧
字段猜测成新 handle。`MessageDisplaySnapshot.urls` 是 bounded trusted URL tuple；CLI 只消费
finalized Artifact。

### 3. Contracts

- `ToolStructuredItem.source_id == f"{locator_kind}:{locator}"` 仍是 structured item 的
  canonical locator identity；对模型另生成 `s<tool-call-ordinal>-<item-index>` 短 handle，避免
  每条 source 重复父级 provenance。Finalizer 只在 current run 的 Tool Result record 内解析 handle。
- 模型可以只提交 structured source handle；如果显式提供 `value_snapshot`，必须与 trusted value
  严格相等，不一致返回 `STRUCTURED_VALUE_MISMATCH`，错误 path 为 candidate source path。
- Tool-backed candidate 的 finding 必须有非空 source handles；Host 编译出的 Artifact 必须同时有
  非空 `evidence_items` 和 `citation_bindings`，否则返回 `MISSING_EVIDENCE`，不生成 validated
  Artifact、不 commit Conversation。
- message URL 必须在 excerpt 截断前从 canonical content 提取，并受 `MAX_SOURCE_URLS` 与
  `MAX_SOURCE_URL_CHARS` 限制；模型正文中自行抄写的 URL 不是 trusted Source URL。
- QueryStreamAdapter 暂存当前 model turn 的 content delta；如果该 turn 发起 Tool，则在
  `turn_completed` 丢弃中间说明；只有无 Tool 的最终 turn 才投影为 `answer.delta`。
- 默认（CLI/TUI）保持上述保守 flush 语义。`provisional_answer_streaming=True`（Local Web）改为：
  content delta 立即投影为 `answer.delta(provisional=True)`；Tool 边界显式发
  `answer.superseded`，由消费方把已显示文本降级为过程叙述（Web 折进过程组），不再静默蒸发。
  `answer.completed` 始终携带 finalizer 权威文本，消费方以它覆盖流式累积。两种模式下
  Tool-turn prose 都不得进入持久化 Answer / Conversation。
- provider 字段名不能证明可见性：`reasoning_text` 与 `reasoning_summary_text` 不因字段名进入
  UI，只有 adapter 归一化时显式附加的 `public_summary` 标记才可视；
  OpenCode Go 的 DeepSeek V4 Flash 使用 `reasoning.effort="low"`，为必须闭合的 JSON 留预算。
- 相对时间只提交 `{kind: "relative", amount, unit, anchor: "archive_latest"}`；Capability 在
  trusted scope 内用 read-only `MAX(timestamp)` 求 archive latest，Host 计算半开 absolute range
  并把原始意图、anchor、resolved start/end 写入 query snapshot/Trace。禁止模型用 SQL 计算并复制
  timestamp，禁止使用 machine current time、`MIN(timestamp)` 或手工心算日期。
- `ToolEnvelope.to_dict()` 是 host/API canonical projection，不直接作为 model context。Runtime
  通过独立 slim projection 向模型发送语义正文、时间、作者、必要 metadata 和短 handle；model
  projection 有独立 `DEFAULT_TOOL_RESULT_TOKEN_BUDGET`，超限先省略 context、再显式标记正文截断，
  永远保留真实 hit，无法满足 contract 时显式失败。
- `AnswerArtifact` 与 `ModelAnswerCandidate` 分离。模型提交 claim/finding/criterion/
  sufficiency/limitations/source handles；Host 确定性生成 block ID、evidence ID、citation binding、
  source dedupe/order 和 trusted URL/value。validated Artifact 之前不得提交 Conversation。

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| structured source identity/locator 不在当前 Tool Result | `UNRESOLVED_STRUCTURED_SOURCE` / `STRUCTURED_SOURCE_ID_MISMATCH`，带 source path |
| structured explicit value 不一致 | `STRUCTURED_VALUE_MISMATCH`，不替换模型值、不删除 citation |
| source run/result scope 不匹配 | 原有 `INVALID_PROVENANCE` / `SCOPE_VIOLATION`，不 hydrate |
| source handle 缺失、跨 scope 或歧义 | `UNRESOLVED_SOURCE_HANDLE` / `AMBIGUOUS_SOURCE_HANDLE`，带 claim evidence source path |
| Tool Result 存在但 Artifact 无 Evidence/binding | `MISSING_EVIDENCE`，不提交答案 |
| Tool-backed candidate 有 finding 但没有 source handle | `MISSING_EVIDENCE`，不静默生成无依据 Artifact |
| model projection 超出独立 token budget | context/正文 trimming facts 显式返回；仍无法满足时 `ToolResultProjectionError` |
| relative anchor 不在 trusted archive | Capability contract error，保留失败 owner，不使用 machine now |
| message source 正文超长 | excerpt bounded，但 URL 从完整 canonical content 提取 |
| Tool turn 产生 provider prose | 不发 `answer.delta`；保留真实 Tool/Retrieval normalized facts |
| provider reasoning summary 到达 | 无 `public_summary` 标记：只消费生命周期顺序，不进入 UI；有标记：默认 TUI 渲染思考正文（plain renderer 仍静默） |
| stream observer 在 delta 中抛错 | 显式 `aclose()` 底层 async generator，原错误继续传播 |

### 5. Good / Base / Bad Cases

- Good：模型提交 `source_id="s1-1"`，Finalizer 在当前 Tool Result 内解析 structured item，hydrate
  数值 182，最终 Sources 显示 canonical locator/value 和 scope limitation。
- Base：消息 excerpt 只保留 1,000 字符，但 URL 位于后半段；Sources 仍显示该 URL，旧 Artifact
  缺少 `urls` 字段时按空 tuple 读取。
- Bad：复制一整行 SQL row 的 value，因字段顺序/类型漂移失败后自动替换为 Tool Result 的值。
- Bad：把无 `public_summary` 标记的 hidden reasoning 当成用户可见 CoT，或把 Tool turn 的“我去搜索”当成正式 Answer。
- Bad：Tool-backed JSON 返回没有 source handle 的 Evidence，或让模型复制 full provenance/大型
  row；也不能用 `MIN(timestamp)` 或 machine now 把相对窗口扩成不可信时间段。

### 6. Tests Required

- Evidence：identity-only hydration、错误 identity/locator/value、source error path、
  `MISSING_EVIDENCE`、trusted URL before excerpt truncation、URL dedupe、旧/new codec round-trip。
- Streaming/Runtime：reasoning visibility gate（无标记 delta 不进 UI state）、public_summary 由
  默认 TUI 渲染、Tool-turn provisional suppression、provider low-effort settings、observer failure
  后 async generator close。
- CLI/Application：Evidence claim binding、finding/criterion/sufficiency/limitations、trusted URL、
  structured value/locator、失败不 commit 与 Trace terminal identity。
- Quality：全量 `pytest -q`、`ruff check src tests`、`mypy src`、`compileall`、CLI help、Trellis
  validation、`git diff --check`，以及 opt-in 真实 provider smoke。

### 7. Wrong vs Correct

#### Wrong

```json
{
  "source": {
    "type": "structured",
    "locator": "total_count",
    "value_snapshot": {"copied": "large row"}
  }
}
```

这会把模型复制格式当成来源 identity，并在大型 row/aggregate 上制造无意义的 mismatch。

#### Correct

```json
{
  "claims": [{
    "text": "共有 182 条。",
    "finding": "current result contains the aggregate",
    "criterion": "short handle resolves in the current Tool Result",
    "sufficiency": "sufficient",
    "sources": ["s1-1"],
    "limitations": []
  }]
}
```

应用层严格解析 handle 并验证 locator/scope，再从 current Tool Result hydrate exact value；Host
生成 Artifact 的 claim→evidence→source bookkeeping，CLI 不读取 SQLite 或重新检索。

## 10. Bounded retrieval result contract（2026-08-25）

### 1. Scope / Trigger

- Trigger：真实 lexical 查询在 `total_hits=31` 时因默认 `limit=20` 只返回 20 条，且相同默认值散落
  在 Scope、Capability、Retrieval、Provider schema 和 Evidence transport。
- Scope：`config/limits.py`、`capabilities/contracts.py`、`retrieval/structured.py`、
  `query/runtime/openai_tools.py`、`query/evidence.py` 和资源清单 prompt。
- Boundary：结果保持有界，不允许无界读取；显式 scope enforcement、partial/truncated 事实和错误透明
  语义不变。

### 2. Contracts

- `DEFAULT_RESULT_LIMIT=100` 是 lexical 默认结果上限，并由 trusted `ExecutionScope.max_results`、
  `SearchMessagesInput.limit`、`LexicalQuery.limit`、Provider Function Tool schema 和 Tool Result
  Evidence capacity 共同使用。
- 任何一层不得保留 lexical 默认 20；提高一个边界时必须同步所有承载同一结果的边界，避免 schema
  允许值超过 Capability 或 Evidence transport 容量。
- 宽范围仓库/Skill/资源清单使用最大可信 `limit`，并将 `context_before/context_after` 设为 0；
  局部上下文只为解释特定命中而开启，不能让邻近消息消耗清单命中预算。
- 无界检索不属于默认行为：超出 100 的数据必须通过显式更高 scope/config 设计，而不是删除上限或
  静默放宽当前 contract。
- Tool-backed model JSON 必须先闭合 `claims` 和 JSON 结构，再列有限代表性 URL；Host 随后生成
  `evidence_items`/`citation_bindings`，长资源清单不得挤掉可验证证据。

### 3. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| 默认 lexical 查询命中不超过 100 | 返回全部命中，不标记由默认 limit 导致的 truncation |
| 命中超过 trusted limit | 保留 `total_hits`、`returned_hits` 和 `truncated/partial`，不得伪称穷尽 |
| context expansion 超出 bounded result | 保留命中统计和截断事实；宽清单由 prompt 使用零上下文避免该成本 |
| Provider schema 与 Capability bound 不一致 | 测试失败并修正共享常量，不添加运行时静默恢复 |
| Tool-backed final answer 缺少 evidence/binding | `MISSING_EVIDENCE`，不生成 validated Artifact、不 commit |

### 4. Tests Required

- Capability：31 条 fixture 的默认 lexical 查询必须返回 31 个 hit，且没有默认 20 截断。
- Runtime：Provider lexical schema 的 default/maximum 使用 trusted scope 的共享上限；资源清单 prompt
  包含最大 limit、零上下文和证据优先要求。
- Real smoke（opt-in）：Trace 的 retrieval partial/truncated 为 0，citation unresolved 为 0，终端
  同时显示 31/31 命中、具体 URL 和 Sources。
- Quality gates：全量 `pytest -q`、`ruff`、`mypy`、`compileall`、Trellis validation 和
  `git diff --check`。

### 5. Wrong vs Correct

#### Wrong

```python
# 只提高某一个层，其他边界仍然截断或无法承载结果。
scope.max_results = 100
SearchMessagesInput.limit = 20
```

#### Correct

```python
# 所有 lexical 结果边界共享同一个有界默认，仍由 Scope 做最终 enforcement。
DEFAULT_RESULT_LIMIT = 100
```

这条 contract 固化“完整命中优先、结果有界、截断可审计”的检索行为；它不把数据库全量内容直接
送入模型，也不使用无依据的 fallback 或静默降级。

## 11. Context Engineering / semantic vs bookkeeping boundary（2026-08-25）

### Principle

`LLM decides semantics; Host code owns deterministic bookkeeping.` 模型可以判断 claim、finding、
criterion、sufficiency、source relation 和 limitation；它不负责复制父级 Tool identity、生成
artifact IDs、排序/去重 URL、计算 archive-relative timestamp、决定 scope，或把多条 Tool Result
拼成一个 provenance locator。

### Host-owned records

- canonical `ToolEnvelope` 和 `ToolResultRecord` 留在 Runtime local；模型只收到 slim projection。
- message/structured handle 是 current scope 的短索引；最终 full provenance 只在 validated Artifact
  和 Trace 需要时保留，旧 serialization codec 不被新 transient candidate 污染。
- `requested result limit`、trusted `max_results`、retrieval hard cap、context expansion bound、
  model Tool Result token budget、answer/evidence budget 是不同预算，任何一层超限都要显式暴露。
- Host projection 记录 `estimated_tokens` 只是 bounded byte-based estimate；provider input/tool-result/
  output token 没有返回时写 `unavailable`，不能把 estimate 冒充 provider usage。

### Explicit non-decisions

本轮不引入 Code Mode、不删除 Tool Calling、不公开 hidden CoT、不新增 retry/fallback/citation
repair，不把完整 provenance 删除出 Trace/Artifact，也不为了让样例通过而增加 query-specific 分支。

## 12. 1M context 与分离式 Tool Evidence budget（2026-08-26）

### Contract

- `opencode-go / deepseek-v4-flash` 的 verified context window 为 `1_000_000` tokens；解析优先级是
  explicit `TRIVAE_MODEL_CONTEXT_WINDOW_TOKENS`、verified model registry、unknown fallback。Runtime
  不允许按 model name 散落猜测。
- `TRIVAE_TOOL_RESULT_BUDGET_MODE` 默认是 `dynamic`；显式 `fixed` 继续作为 regression/debug/evaluation
  baseline，并保持单次 `16_000` tokens。
- 单次 Tool Result ceiling 与整个 Run 的 Evidence pool 是两个独立参数：per-call 默认
  `min(floor(context * 50%), 128000)`，run-level 默认候选 `min(floor(context * 25%), 256000)`；
  `TRIVAE_RUN_TOOL_EVIDENCE_BUDGET` 只用于明确的实验 candidate。1M、128k、run pool candidate
  不能互相改名或互相代替。
- unknown dynamic context 的 per-call 和 shared run pool 都是 `16_000`；每次调用从同一 policy 账本
  reserve/settle，不能让每个 Tool 重置一份 fallback。

### Runtime / Trace boundary

`ToolResultBudgetSnapshot` 必须同时保存 context source、per-call ceiling/effective budget、run pool、
remaining before/after、actual projected estimate、truncated 和 omitted hit/context。`128000` 是单次
Tool 的 safety ceiling，不代表整个 Run 只能累计 `128000`；Run-level candidate 必须通过 synthetic
和 real paired evidence 校准后再决定默认值。
