# Agent Runtime and Query Execution Guidelines

## Planner capability summary contract (2026-09-27)

### 1. Scope / Trigger

当新增或调整 Agent-facing Tool 时，Planner 必须知道该 Tool 的 canonical purpose 和规划选用关系，但不能获得执行参数控制权。

### 2. Signatures

```python
CapabilityRegistry.metadata() -> tuple[CapabilityMetadata, ...]
SoftPlanner(..., capability_metadata: tuple[CapabilityMetadata, ...] = ())
SoftPlanner.plan(context: QueryContext) -> PlannerResult
```

### 3. Contracts

`CapabilityMetadata.name/description` 由已注册 Tool 的 Capability 拥有；`SoftPlanner` 只拥有 Tool 选用关系的 `planning_guidance`。生产 prompt 直接采用 `68286d569025718c88029b66bc028e89a5a10c72` 的 P1 文字和 capability guidance。Application 构造默认 Planner 时注入 metadata，Router 继续只接收既有 `QueryContext`。Prompt 仅包含当前 `available_capabilities` 中的 summary；该 allowlist 仍是 Plan suggested tools 的合法性源。Plan 是一次性、bounded soft guidance，Runtime 保留实际 Tool 选择、参数和停止决策。

### 4. Validation & Error Matrix

| 条件 | 行为 |
| --- | --- |
| 已注册 Tool 缺少匹配 `CapabilityMetadata` | `CapabilityRegistry.metadata()` 显式 `ValueError`，不按名称伪造 purpose |
| 新 Tool 尚无 Planner 选用约束 | 构造 summary 时显式失败，要求补齐而非静默空 guidance |
| LLM 建议未在 allowlist 的 Tool | 原 Plan parser 过滤该名称 |
| Provider length / invalid JSON / empty output | 保留已有 Planner failure 分类与 graceful skip；不自动重试 |

### 5. Good / Base / Bad Cases

- Good：实体反馈问题用 lexical 主锚找到 direct share，再沿相关 discussion context 核查 firsthand feedback。
- Base：简单 SQL count/rank 由 schema+SQL 完整回答，Plan 不增加 recent/context 复核。
- Bad：`mattpocock 或 skills` 允许泛类别词独立替换实体，或把 `find_members` 用于“谁说过/谁用过”的消息内容问题。

### 6. Tests Required

Provider-free 测试断言 canonical purpose 注入、allowlist 过滤、通用实体/context/overplanning prompt 约束、未知 Tool 过滤、Plan bounds 和 failure classification。模型是否遵从软指导必须由重复 Planner-only Development 实验审阅，不能从 prompt 断言推出。

### 7. Wrong vs Correct

Wrong：把 SDK Tool 参数说明复制成第二份 Planner 文档，或给 `QueryContext` 增加 Router 不需要的 Planner 字段。Correct：Registry 读取已注册 Capability 的 metadata，Planner 只补选用关系，生产 allowlist 和 Runtime 自治边界不变。

## Planner completion stability contract (2026-09-27)

### 1. Scope / Trigger

DeepSeek `deepseek-flash` 的 Planner-only 实测表明，`finish_reason=length` 时隐藏 reasoning token 可以耗尽 2048 completion 上限，让可见 JSON 为空或不完整。当前生产组合是 **P1 canonical prompt + Planner 专属 non-thinking**；后者只改变一次 Planner completion 的思考档位，不改变 Router、Agent Tool Loop 或 Plan schema。历史 P2 同时改 prompt 和 thinking，不能作为这个组合的单变量质量证据。

### 2. Signatures

```python
OpenAIAgentsRuntimeAdapter.completion_request_projection(*, reasoning_effort_override=None) -> dict[str, object]
OpenAIAgentsRuntimeAdapter.complete_text_with_observation(prompt, *, reasoning_effort_override=None) -> CompletionResult
OpenAIAgentsRuntimeAdapter.planner_completion_request_projection() -> dict[str, object]
OpenAIAgentsRuntimeAdapter.complete_planner_text_with_observation(prompt) -> CompletionResult
```

### 3. Contracts

- Application 默认 Router 仍注入 `complete_text_with_observation`；默认 `SoftPlanner` 注入 `complete_planner_text_with_observation`。两者复用同一 Provider client，Plan 仍经原 parser 和同一 Agent Runtime 的 soft guidance 路径。
- 只有精确 `provider=deepseek`、`model=deepseek-flash` 的 Planner 请求指定 `reasoning_effort=none`；已有 `ablation-p1-nonthinking/` 用原 P1 prompt、2048 completion 上限实测 24/24 有效、0 次 `provider_length`。其它 Provider/模型维持 registry 的原档位。该 Development 观察不证明失败率为零，也不证明 Plan 质量完全保持。
- `temperature=0`、JSON mode、`completion_max_tokens=2048`、Plan 5/5 bounds、allowlist 和失败 skip 都不变。Router request projection 仍是 registry `low`。
- completion usage 仅在 Provider 返回时包含 `reasoning_tokens`（来自 `completion_tokens_details.reasoning_tokens`）；缺失是 unknown，不是 0。`finish_reason=length` 仍先于 JSON parser 归为 `provider_length`，不 retry。

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| 官方 DeepSeek Flash Planner | request/Trace projection 都标 `reasoning_effort=none`；Provider 调用也必须为 none |
| 同一 model 的 Router | request 继续为 `low`，不受 Planner treatment 影响 |
| 未经实测的 Provider/model | Planner 使用原 registry 档位，不推断支持 none |
| Provider 返回 reasoning token 明细 | usage 保存数值；缺失则省略字段 |
| `finish_reason=length` 或空 response | Planner 显式分类并 skip，不扩大 token ceiling 或自动重试 |

### 5. Good / Base / Bad Cases

- Good：Planner 对精确 DeepSeek Flash 请求 `none`，Provider 成功返回 JSON 后仍由 Runtime 自行处理 Tool 结果。
- Base：普通 Router 请求继续使用 `low` 与 2048 completion bound。
- Bad：把 Planner 非思考结论套到未测试 Provider、把 `reasoning_tokens` 缺失当零、或通过 retry/增大 2048 隐藏 `provider_length`。

### 6. Tests Required

Provider-free 测试需断言 P1 prompt 关键规则、Planner request 与实际 Provider 参数均为 none、Router 仍为 low、usage 只投影实际 reasoning 明细、Plan parser/allowlist/失败 skip 不变。已有消融中原 P1 prompt + none 虽 24/24 有效，zero-result 与 cite-archify 的 Plan 质量仍有疑点；不能从 prompt 字符串或这 24 次 Development 调用推断模型一定遵从所有规划规则。

### 7. Wrong vs Correct

Wrong：看到 P1 输入 token 变多就提高共享 `TRIVAE_COMPLETION_MAX_TOKENS` 或给 Planner 加重试。Correct：先保存 `finish_reason`、raw content、reasoning usage 和配对输出；仅为已验证的 Planner/model 使用独立 completion mode，同时保持 Router 与 Runtime contract。

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

OpenCode Go 的 OpenAI-compatible client 必须在构造时携带稳定 `x-opencode-session` 和
`User-Agent: trivae/0.1.0`；runtime 使用固定的本地 runtime session，Evaluation Judge 使用当前
Run 的 session。缺少该 header 会得到 provider 的 `MissingSessionID`，必须在 client 边界修复，不能在
调用方吞错或重试。

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
  `total_tokens`，以及 Provider 明确返回时的 `cached_input_tokens` 与 `reasoning_tokens`。
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

### User-visible answer depth boundary（2026-08-28）

- `ModelAnswerClaim.text` 是用户可见的完整回答正文，并由 Host 原样编译为
  `AnswerContentBlock.text`；它不是只能放一句话的 finding label。
- Final Synthesis 应按问题复杂度自适应：简单事实问题可以简洁，宽泛概览、比较、观点、时间线和
  资源清单应覆盖证据支持的独立 finding、代表性细节、参与者/顺序/名称/URL 与必要限制；不得为
  追求 claim 数少而合并独立 finding，也不得用无证据背景填充正文。
- `finding`、`criterion`、`limitation`、source handle 与 citation bookkeeping 仍保持 bounded；
  “artifact compact” 只约束这些内部 metadata，不约束用户正文的充分程度。Trace 只记录有界的
  candidate/content-block 数量与文本长度诊断，不复制 candidate 正文。
- `AnswerArtifact` 的 current-run provenance、scope、partial/coverage、trusted hydration、
  citation binding 和 invalid-candidate failure contract 不因回答展开而放宽；简单事实回归必须仍可
  保持单一短内容块。

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

## 13. Resource inventory tool-selection boundary（2026-08-29）

### 1. Scope / Trigger

- Trigger：真实 AQ3 Web dogfooding 已证明，在 `lexical_search("github.com")` 返回完整 URL 证据后，模型仍可能调用宽范围 `get_recent_messages`，或重复发送失败的近似 SQL；这会增加 projection 成本、引入无关内容，甚至使 Run 失败。
- Scope：资源清单与学习资料的 final synthesis prompt、`lexical_search`、`semantic_search`、`get_recent_messages`、`execute_sql` 的 tool guidance，以及 SQLite public schema error taxonomy。
- Boundary：只约束证据发现路径和错误透明度；不改变 current-run provenance、scope enforcement、evidence sufficiency、partial coverage、trusted hydration 或 citation binding。

### 2. Contracts

- URL / repository / Skill / link inventory 必须优先使用有界 `lexical_search`；URL 证据的标准形态是 `keyword="github.com"`、trusted 最大 `limit`、`context_before=0`、`context_after=0`，并保留必要的时间范围。
- 非空的 URL lexical 结果已经足以支持 URL-bearing resource recall；不得再用 `get_recent_messages` 或 `execute_sql` 发现、枚举或重算同一批资源。需要解释上下文时，只能基于已有命中按问题需要补充。
- 独立的学习资料清单（博客、文档、论文、课程、视频等）可以在 URL lexical 结果之外使用一次有界 `semantic_search` 补充非 URL 证据；若问题主要询问谁问了什么、对应回复与建议，应优先按讨论锚点调查，不因出现“材料”或链接就套用 GitHub 清单规则。不能因为问题宽泛就自动读取整段 recent archive。
- `get_recent_messages` 只用于时间窗口本身是问题语义的 overview；它不是资源清单的默认扩展器。`execute_sql` 只用于结构化事实，不能用于重算检索结果；SQL 失败后不得重复相同或近似语句。
- SQLite 对公开但不存在的 table/column/function 的解析错误必须映射为 `SQL_SCHEMA_VIOLATION`，不能因为 authorizer 尚未建立状态而误报为 `SQL_MALFORMED`；真正语法错误仍保持原有错误分类。
- 这些边界通过 prompt/tool guidance 与 deterministic regression 固化，不通过 query-string 特判、retry、fallback、静默降级或放宽结果上限实现。

### 3. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| URL lexical 返回非空且未截断 | 结束 URL 证据发现；不得出现同资源的 broad recent / SQL recount |
| 泛化学习资料需要非 URL 证据 | 可追加有界 semantic；保留 partial/truncated 事实并在回答中反映限制 |
| recent overview 是用户明确问题 | 才调用 bounded recent，并记录返回量、omitted/truncated 与 scope |
| execute_sql 返回 schema 解析错误 | 返回 `SQL_SCHEMA_VIOLATION`；模型不得重复相同或近似 SQL |
| Provider TLS/transport 在首个模型请求前失败 | Run 显式失败并保留 Trace；不添加盲目重试掩盖环境或 provider 根因 |

### 4. Tests Required

- `test_resource_inventory_guidance_separates_url_and_non_url_evidence` 必须验证 URL lexical 足够、generic learning 可 semantic 补充、recent/SQL 不承担资源枚举，以及 SQL 错误不重复。
- Stage C schema tests 必须覆盖不存在的 public table/column/function 到 `SQL_SCHEMA_VIOLATION` 的映射，同时保留真实 malformed SQL 的原分类。
- Real Web smoke 必须记录 Trace ID、router/tool sequence、retrieval returned/projected/omitted/truncated、provider outcome、final claims/citations、Sources DOM 与 browser errors；至少一个 URL inventory 和一个 generic learning inventory 需要有可审计结果。
- Regression 不以回答字数单独判定；应检查独立资源/主题 finding、资源名称或 URL、limitation、citation provenance，以及不存在 broad recent / repeated SQL 的工具序列。

### 5. Good / Base / Bad

| Case | Expected behavior |
| --- | --- |
| Good：`github.com` lexical 非空、93/93、projection 无 omission | 直接 synthesis 具体项目/链接；不再补 recent 或 recount |
| Base：学习资料同时命中 GitHub 与语义资料 | lexical + bounded semantic；区分仓库、文档、论文等类型并保留证据限制 |
| Bad：lexical 已完整却读取 5000 条 recent，或 SQL 失败后原样重发 | 判定为 tool-selection / error-loop failure，依据 Trace 修 prompt/tool guidance，不扩大 token 或加 retry |

### 6. Wrong vs Correct

Wrong：收到非空 GitHub URL 结果后，为了“更完整”继续调用 `get_recent_messages(limit=5000)`，或用没有验证 schema 的 SQL 重新统计 URL。

Correct：使用有界 URL lexical 结果完成资源回答；只有泛化学习资料缺少非 URL 证据时，补一次有界 semantic，并把 retrieval partial、scope 和 citation binding 交给 Host 保持。

## 14. Planner effort targeted production E2E experiment contract（2026-10-02）

### 1. Scope / Trigger

Planner-only semantic 差异需要验证是否进入生产 Tool/Evidence/Answer 时，使用 experiment-only runner；不得由实验改生产 Prompt、Retrieval、Router 或 Answer contract。

### 2. Signatures

- `run_p1_e2e.py --output PATH --seed INTEGER --attempt {1,2} [--preflight-only]`：固定 8 exposed Development Cases、每 treatment 一次。
- `create_application(..., planner=...)` + `complete_text_with_observation(..., reasoning_effort_override=...)` 是已有注入边界。
- `HTTPRecorder` 保存 `provider_requests.jsonl` / `provider_responses.jsonl`；request-start 才是实际 HTTP attempt 计数。

### 3. Contracts

两侧实际 Planner serialized request 必须只有 effort 不同；下游初始 request config/schema 相同，Plan guidance 与后续 Tool history 是中介变量。生产 Planner failure 的显式 skip 必须保留：有效最终 Answer 不等于 Planner 成功。独立 AI blind review 必须注明非 human adjudication，全部判断完成后才能揭盲；揭盲后的 reviewer error 核验另存，不覆盖原判断。

当前锁定 OpenAI SDK 使用 httpx2，观测与 provider-free MockTransport 必须和真实 client 采用同一 HTTP 类型。预检临时 transport 必须同时隔离 proxy mounts，避免 mock 请求绕到真实网络。正式 client `max_retries=0`；模型收到错误结果后主动发出的另一次 Tool call 不计作 transport retry，但必须保存为真实失败调用。

各 usage 字段保存 `total: number|null`、`observed_sum`、`observed_requests`、`requests`：任何请求缺失该字段时 overall total 为 null。`observed_sum=0, observed_requests=0` 不表示测得零 reasoning。隐藏 reasoning 正文不归档；visible output、finish reason 和 reasoning token 数保留。Semantic dependency/preload 必须在首个真实 attempt 前检查；每 run 新 conversation，共用预热后的生产 embedding，不改 caching semantics。

### 4. Validation & Error Matrix

| 条件 | 处理 |
| --- | --- |
| code/snapshot/case drift 或额外 treatment 字段 | 停止，保留已有 attempts，禁止混入不同代码结果 |
| Planner length | 归档 usage/finish/raw output 和既有生产 skip，单列 Planner reliability |
| tool alias 用作 canonical message_id | 保留 MESSAGE_NOT_FOUND 与后续调用，不伪装成 retry 或静默成功 |
| incomplete SSE / timeout | 完整 frame 保留，尾部标明 incomplete，不补造 usage |
| reviewer 称 hallucination，但全文 ToolResult 中有事实 | 区分事实存在与所选 Citation 支持，不修改 blind judgment |

### 5. Good / Base / Bad Cases

Good：正式完整空窗支持 zero-result；partial 被如实说明。Base：相同事实可来自不同 SQL row order。Bad：仅凭更多 Tool calls 判 redundant，或把 SQL 全窗计数当作全文主题覆盖。

### 6. Tests Required

Provider-free 断言 deterministic AB/BA、唯一 serialization diff、unknown usage、HTTP failure ledger、stream bytes 无改动、hidden reasoning 正文移除、blind metadata 隔离与 incomplete SSE。真实执行后核对 logical runs / Evaluation runs / results / terminal Traces，以及 HTTP requests / responses / model turns；逐字核对冻结代码和数据。

### 7. Wrong vs Correct

Wrong：看到 Finalizer validated 就宣布 citation precision=1，或把作者昵称当 normalized message content。Correct：provenance validation 与语义 entailment 分层记录；复核原始 ToolResult 的 content、author、session、时间与 citation binding。

## 15. Frozen Plan Runtime replay contract（2026-10-02）

### 1. Scope / Trigger

需要区分已保存 Plan 的 guidance 与下游运行方差时，只重放固定有效 Plan，不重新请求 Planner，不在实验中修复生产行为。

### 2. Signatures

`run_frozen_plan_replay.py --output PATH [--source PATH] [--seed INTEGER] [--preflight-only]` 固定 Archify 两份 Plan 各两次。`FrozenPlanner.plan(QueryContext) -> PlannerResult` 返回原 Plan，observation=None，不伪造历史 Provider usage 或 latency。

### 3. Contracts

通过生产 parser 读取 Plan 后逐字段保持原样；生产 renderer 生成 guidance。两侧首个实际 HTTP body 剥离精确 guidance 后必须相等；同 guidance 的原始 body 也核对相等。Runtime reasoning 固定生产 low，low/none 标签仅表示来源。Snapshot 的 created_at 是 materialize 观测时间，不属于数据变化，其余完整字段比较；SDK ModelSettings 使用 to_json_dict() 保存可序列化语义。

`get_message_context(message_id="m1-1")` 把 alias 交给 canonical lookup，产生 MESSAGE_NOT_FOUND；`get_message_context(source_id="m1-1")` 经既有 SDK resolver 生成 canonical message_id。normalized Trace 的 canonical arguments 不能冒充模型原始 arguments，归因须连接 HTTP function arguments 与 Tool Trace。

### 4. Validation & Error Matrix

源 Plan 失败/解析改变 → 拒绝；源码/快照/初始 body 污染 → 保留已落盘 attempt 并停止；真实 Tool error → 记录并继续既有 Runtime，不新增自动重试或 message_id alias 兼容；semantic 判断 → 与 machine facts 分开，并标明是否盲审。

### 5. Good / Base / Bad Cases

Good：同一 guidance 下观察到不同 context 参数后，分别归因检索遗漏与合成错误。Base：Provider cache 保留生产语义。Bad：4 次结果宣布质量等价，或把未固定 ToolResult 的重放当作纯 Answerer 方差实验。

### 6. Tests Required

四次 AB/BA、有效 Plan 原样与无 Provider 注入、production Orchestrator guidance 透传、初始输入/schema/settings 隔离、materialize 时间变化不隐藏消息数变化。真实工件复核 HTTP / normalized model-turn / Tool sequence 数量与公开原始参数。

### 7. Wrong vs Correct

Wrong：看到恢复后的 Trace canonical ID，声称模型已自行选择 canonical ID。Correct：保存 Provider `source_id` 与 adapter 归一化后的 `message_id`，明确映射 ownership。


## 16. Context source identity 与 temporal evidence regression（2026-10-02）

### 1. Scope / Trigger

Frozen replay 4/4 runs 把短handle填入canonical字段；low-r2正确取回日期却写成同日。修复模型可见SDK schema/prompt及既有Judge输入，保持resolver/Finalizer架构。

### 2. Signatures

SDK `get_message_context(context, source_id: str | None = None, message_id: str | None = None, context_before: int = 8, context_after: int = 8)`；归一化为`GetMessageContextInput(message_id=<canonical>, ...)`。Judge `canonical_message_excerpt(*, timestamp_ms: int, content: str) -> str`。

### 3. Contracts

`source_id`只指当前run-local `mN-K`，如`m1-1`；`message_id`只指canonical internal ID，如`qq:1039179741:7670742957499269309`，两者互斥。真实Pydantic/SDK字段description分别说明，不合并成模糊身份。ToolResult projection公开source_id；resolver负责映射，raw HTTP/model_output保存Provider原参数，normalized Tool Trace保存canonical参数。Judge excerpt先写`timestamp_utc`，再写`message_content`；日期不可被正文截断隐藏。sender_name不作消息正文，邻接不证明reply。

### 4. Validation & Error Matrix

| 输入/事实 | 既有行为 |
| --- | --- |
| 当前run已公开的source_id | 显式resolve canonical并调用Capability |
| canonical message_id | 保留直接context查询 |
| 两字段同时给出/均缺失 | 显式contract error，不猜测身份 |
| message_id="m1-1" | canonical查询的MESSAGE_NOT_FOUND；不silent alias |
| 日期相隔多天但Claim/finding称同日 | 保存失败、供既有Judge/source review判断；结构Citation通过不代表语义成立 |

### 5. Good / Base / Bad Cases

Good：raw `source_id=m1-1` 与normalized canonical ID同时保留。Base：canonical直接查询能力不变。Bad：从normalized Trace宣称模型自行生成canonical ID，或以finding自证Claim时间关系。

### 6. Tests Required

`test_context_source_contract.py`验证真实schema/projection/resolver/canonical/错误字段和stream raw/normalized ownership；`test_temporal_relation_regression.py`验证原fixture、2026-07-23→2026-08-06的1185297秒差、日期不同及Judge bounded输入/parser；`test_benchmark_judge.py`验证实际orchestrator日期投影。mock不能证明真实Judge准确率；没有通用自然语言temporal checker。

### 7. Wrong vs Correct

Wrong：`get_message_context(message_id="m1-1")`；两条来源可解析就认定“同日”有支持。Correct：`get_message_context(source_id="m1-1")`；以canonical timestamps判定关系。真实旧错误保留于`evaluation/regressions/archify-temporal-relation.json`，不改原artifact/GT。

## 17. Planner Evaluation final engineering closure（2026-10-03）

当前Router low、P1 Planner none、共享Runtime low。none是completion reliability/latency选择，不证明最终质量优于low。保留架构、限制使用，production routing继续保守、Jev shadow不变。

`run_engineering_closure.py --output <new-directory> [--preflight-only]`固定八Case×两路×一次、AB/BA；create-only、无repeats开关。正式前preflight必须落盘execution commit、Snapshot/Case/GT逐字身份、实际SDKschema/settings、credential configured boolean；失败0attempts/0HTTP，不写key。Standard Planner=0，Planned=1，实际首次Runtime HTTP只差生产guidance。raw/normalized参数与完整证据链分开保留。

正式16次/54HTTP完成后停止，0targeted repeats；11次context参数正确不等于答案全对。两路required-context仍漏取，Planned cite遗漏7k，temporal样本跨度仍写错；mean E2E 8.169→10.266秒、token285065→296703。low/none研究与Standard/Planned validation closed，不安排新付费实验。只有新的真实严重生产Failure Case影响明确工程决策才重新评估。完整判断见[report.md](../../tasks/10-02-planner-engineering-closure/report.md)。

## 18. 讨论调查与模型可见事实（2026-10-05）

### 1. Scope / Trigger

真实使用中已命中教程提问但未追踪后续推荐，答案误称未回答，并出现发言者与日期错误。修改边界为 Runtime 指导、SDK 工具说明与统一消息投影；检索、Planner、默认三轮与最终校验继续使用既有主链路。

### 2. Signatures

`_model_message_projection(record, item, source_id)` 同时公开 canonical `timestamp` 与 `timestamp_utc = format_timestamp_utc(timestamp)`。`get_message_context` 的 before/after 仍默认 8/8。动态 `instructions` 从 `_RunState.tool_rounds` 和 `max_tool_rounds` 编译已耗/剩余轮数。

### 3. Contracts

讨论中的提问、回复、后续评价与材料用关键 source_id 调查，回复缺口优先于近似宽搜；已知独立锚点可在同一轮查询。上下文参数是消息条数，不是分钟；20/40 是可选示例，不能作为全局默认或每个 hit 的固定规则。邻接不能证明直接回复关系。工具完整返回请求窗口不代表话题完整，不据此声称无人回答。

消息投影裁剪仅缩短正文时必须保留 source_id、author、timestamp 和 timestamp_utc；日期使用 Host UTC 字段，原话归给对应消息作者，群友表述与模型归纳分清。储存、canonical provenance 与引用解析不增加日期字段。

每个产生 Tool Result 的模型回合只计一轮；多工具并行不按调用数量减轮数。预算提示只读取已有 state，不另建计数器。达到原上限仍移除工具并进行无工具综合，不增加隐藏轮次。

### 4. Validation & Error Matrix

| 事实 | 要求 |
| --- | --- |
| 命中提问，回复未覆盖 | 优先显式 context，局部未见不能推导无人回复 |
| 完整返回 8 条上下文 | 仅证明该窗口已返回，不证明讨论穷尽 |
| 正文触发预算裁剪 | 留下的消息保留来源、作者与 UTC 字段 |
| 并行多个工具完成 | 下一次模型提示只减少一轮 |
| Provider 失败 | 显式保留错误和 Trace；不追加 retry/fallback |

### 5. Good / Base / Bad Cases

Good：找到提问后读后续推荐并按具体作者引用。Base：纯 GitHub 清单保持 URL lexical-first；简单事实无需深挖。Bad：为了“更全”统一读取 40 条、以引用合法证明回答正确、把投影成功当自然语言遵从。

### 6. Tests Required

SDK 真实 schema 验证 before/after 单位与默认值；ScriptedModel 验证初始、并行、耗尽预算和最终综合提示；统一 projection 与预算裁剪验证日期、作者、来源绑定。正式工具重放与重复真实配对分别证明证据送达和模型使用，质量判断须逐项回查 canonical 消息。

### 7. Wrong vs Correct

Wrong：窗口没看到回复就写“未解决”，连续对话都归于一个人，把毫秒自行换算成月份。Correct：写明已查范围的未确认项，按消息作者归属并读取 timestamp_utc；完整性与具体语义质量仍待真实回归，不承诺每次全面。


## 19. Runtime Prompt 职责分层与回归边界（2026-10-06）

分层候选使用 Core、Retrieval、Time/constraints、Evidence、Output 的 Markdown 层级，稳定策略各有一个主位置；本轮真实回归未通过，运行 `prompt.py` 保留原版。讨论/清单意图先于通用精确/概念查找默认。讨论锚点与选窗、清单 lexical 最大值、证据强度和完整正文仍是模型决策，不能因 Schema 已有参数类型或上界而删掉。

当前 Provider 使用 JSON mode，未提供完整 Structured Output Schema。claims/no_result 生成形状及尚未由工具 Schema 表述的必要参数指导继续保留。Host 校验负责输入合法性和 trusted scope；Finalizer 通过只证明形状、来源与既有证据契约，不证明作者、日期、回复关系或穷尽性正确。

Prompt 修改须保留原 Policy 映射；纯措辞断言可同步，参数、来源与结果断言不能放宽。真实配对固定快照、query/scope、模型、预算和路由，保存完整实际请求，核对首次 HTTP body 除 system 外一致。重构后再次出现已知漏召回或错误关系时如实记录，不因 Prompt 更短或 Finalizer valid 就宣布质量等价。版本修订的重复实验与原样重复须分别标明，不能合并为同一候选的成功率。

候选已出现原版取到推荐而候选遗漏的配对时，不按结构完成率放行；保留候选与所有失败，恢复原版，再评审更小的去重范围或措辞保留方案。

## 20. Prompt持续优化的低成本开发契约（2026-10-06）

- 每轮只改一个policy scope，先记录作用位置、确定性owner、必要tier与Provider预计/最大HTTP请求数。production是唯一baseline，旧失败大候选不能替代它；Discussion/Negative/Temporal/Stop/Routing不得附带改写。
- 参数职责迁移须验证真实SDK解析与Host执行，不能只看Schema。lexical/legacy limit现用`Annotated[int, Field(strict=True, ge=1)]`拒绝SDK隐式转换，trusted upper bound仍由Capability执行；其它字段不能因此推断已strict/有minimum。清单选最大limit是语义指导，保留。
- `run_prompt_screening.py --mode static`不读密钥或构造Provider；targeted用现有suite_tags，candidate-only在付费前验证冻结Prompt原文、scope/snapshot/model/budget/实物tool contract等条件。默认repeat=1/预算0，真实HTTP attempts由hook硬约束；明确regression停止，只有单case人工borderline可追加candidate，不重跑baseline/probe/full suite。
- first-tool实验复用Application.query和生产builder，在SDK已记录模型输出/usage后拦截工具callable；没有Host工具执行，FirstToolProbeStop不能算完整答案成功。full-gate显式fresh pairs/AB或BA与人工review，不自动发布production或把Finalizer状态当质量分。
- 历史real_pair的production记录可由显式导入器零API冻结，保留未知GT/checks和原失败；私有原文/请求/Trace/答案只在ignored data/evaluation。精确原文+commit使用既有文本身份，不新增摘要算法。synthetic只证明证据送达/确定性边界，真实语义仍走成本漏斗与release gate。


### P0参数迁移补充与审计定位（2026-10-06）

- lexical/legacy context现以strict int/ge=0在真实SDK拒绝；默认2不变，讨论20/40选窗仍由模型决定。semantic dense_top_k以strict/ge=1执行，默认40不变；semantic/member query以minLength=1公开，空白串仍由typed input拒绝。
- lexical三种filter与member session_ids以minItems=1公开且在SDK执行；omit/null沿用原scope继承。Host仍校验非空项/授权，不把选择unused filter的模型判断当成机械约束迁移。
- get_schema strict空Schema与SDK入口共同落实无参数；SDK空串/空对象合法形式不变。额外字段在SDK忽略之前显式拒绝，JSON失败保留异常链。Schema单独禁止additionalProperties不能证明函数执行已拒绝。
- 每条迁移除全文精确删除测试，还须验证删除片段属于对应matrix规则的当前原文。旧审计行号不能直接承接；相邻规则共用一行时用精确片段和最小行范围。组合候选按已声明片段顺序重建，不靠总行覆盖推断语义归属。
- 完整相同句子才属于literal dedup；大小写/主语/范围不同的近似重复保持敏感策略标签。新SDK合同与历史frozen不同必须显式拒绝或进入单独审计，不自动修改历史artifact条件、不默认为同条件配对。L0候选不能直接替换production。

- recent.limit、显式get_message_context窗口、SQL max_rows现在也以strict整数/minimum执行，nullable SQL cap仍允许省略/null。显式context保持8/8默认，Host限制before+anchor+after共享总量，不额外限制单侧或替模型选择20/40。
- get_message_context身份互斥实际由SDK函数体Host guard执行，Schema仍无oneOf；不能把optional字段误称为互斥Schema。SQLite execute/authorizer执行单语句及写入/DDL拒绝，Tool错误透明；Base删除仅在开发候选，production原文保留至语义发布gate。
- 冻结结果仍须精确匹配全部非Prompt条件；当前SDK修改与旧frozen tool_contract不相等。失败信息列出漂移顶层字段，不允许为了复用旧记录重绑或忽略新Schema。H04只改善诊断，不放宽门禁。

- first-tool拦截可能让streamed Runner在model hook事件排空前终止；实验artifact从SDK ToolContext.usage按原数字投影保存probe_usage，不依赖失败Run汇总，不回填canonical Trace。同轮多tool不能重复累加；缺失旧观测保持unknown，不为补统计付费重跑。

- first-tool记录选择必须先保存原始参数，再解析JSON；坏调用不能因同轮另一合法call留有probe而视为成功。CLI只接受实际FirstToolProbeStop且Host零调用；其他工程异常保存失败artifact/Trace后停止后续case，不重试。SDK包装后的真实异常类型保持原样。

- semantic context双字段现在与原typed input共用非负整数契约，SDK strict/ge=0阻止bool/string/float转换。默认2/2、合法0/20/40与原evaluation-only clamp不变；新增Schema minimum造成冻结条件漂移须显式处理，不能外推真实模型选窗等价。

- SDK并行首工具可能先返回正常FirstToolProbeStop而另一call解析失败；实验完成须同时核对每个已观测call有解析arguments。缺失解析时保存raw/真实Trace并停止后case，不能按返回异常顺序猜测完整成功。

- semantic三种可选filter以minItems=1公开并由SDK执行已有非空数组契约，omit/null仍原样继承scope。只约束数组形状，不推断canonical ID或授权；Base无对应semantic句，不能虚报Prompt迁移。

- recent双可选数组以minItems=1公开并执行原Host/Args非空形状约束；omit/null及archive_latest两天/default/cursor不变，unused filter选择仍由模型决定。

- 首工具实验choice与usage在ScreeningRuntime新run构造入口共同重置，CLI不重复管理；顺序复用同一Runtime的Application.query不能跨run积累choice。实验仍按case顺序执行，此修复不建立并行run支持。

- 连续Prompt实验可在原ProviderCallBudget hook指定shared ledger与总上限。顺序跨脚本在发送前读取/占用并持久记录，禁止清零/扩大已有上限；local上限同时生效。用户本批授权80新增HTTP，历史观测不重算；此机制仅实验，不改变生产Query预算或Provider重试。

- lexical keyword仍为一个字符串；空白分隔term由LexicalQuery.terms和FTS literal AND执行，不要求不同term相邻或同顺序。共享SDK字段说明公开该已有语义，四消息fixture验证非相邻/逆序命中与单词排除。不要用语义结果的partial/basis标签推断index缺失，核对metadata.index_status和实际index state。
