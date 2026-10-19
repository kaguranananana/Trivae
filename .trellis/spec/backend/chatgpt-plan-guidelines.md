# ChatGPT plan 接入契约

## 适用边界

`TRIVAE_MODEL_PROVIDER=chatgpt-plan` 使用 Trivae 独立 OAuth 注册与公开 Responses API；DeepSeek、OpenCode Go 与独立 Jev 的现有请求路径不变。标准流程见 [官方注册](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)、[会话管理](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions) 与 [预览限制](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)。

## 认证与本机生命周期

- `ChatGPTAuthStore` 默认位于本机用户配置目录下的 `trivae/chatgpt`，目录 0700、文件 0600，原子保存；不允许 Git 仓库内存储。
- 初次使用 `dynamic_agent_client` 和 `agent_name_hint=Trivae`；签发 client ID 与经过 OIDC 签名、issuer、audience、expiry、nonce 验证的 subject 共同保存。注册按 issued client ID 分离；同 email/subject 不表示同工作区。
- 主机 ID 使用持久化 `urn:uuid:`；callback 固定 `127.0.0.1` 与 `/auth/callback`，每次授权生成独立 state、nonce、PKCE。PKCE 只调用 Authlib 标准实现。
- 缺 `chatgpt.tokens.use.direct` / `resource.invoke` 时保留身份但禁止推理；不得把 ID token 当作权限证明。
- 旋转刷新在跨进程排他锁中重读凭证、执行 refresh、原子替换整组 Token。成功响应缺 replacement refresh token 是明确失败。终态刷新错误清除 Token 并保留注册，网络/5xx 不删除会话。
- `status()` 只读原子快照，不等刷新排他锁；否则同一 event loop 的 readiness 会阻塞持锁网络请求。
- 每个 Auth Manager 首次读取后绑定同一 issued client ID；CLI 切换注册后重新启动 Runtime，保证目录与推理凭证来自同一注册。
- logout 尝试官方 discovery 中的 revocation endpoint；清除本机 Token 并保留 host/registration。撤销未确认须明确告知，不能报告远端撤销成功。

## 推理与业务主链路

- `ChatGPTResponsesModel` 实现 SDK `Model` 边界；Runner、Capability、预算、Finalizer 和 Conversation 仍由既有生产链路拥有。无需升级 `openai-agents==0.22.0`。
- 账号模型目录来自公开 `GET /v1/models` 的 `models[].slug`，只提供 `visibility=list` 选项；不硬编码 GPT entitlement/context/reasoning 档位。
- 每次 HTTP 推理发送 `store=false`、`stream=true`、数组 `input` 与完整本地历史。使用 `instructions`，不转发 Chat Completions 的 system/response_format 或 max_tokens。
- 独立白名单 payload 不发送预览禁止的 max_output_tokens、temperature、metadata、conversation、previous_response_id 等字段；本地 turns/tool budgets 继续生效。
- function tools 使用公开 SDK `tool_namespace` 与 Converter；Runner 负责 namespace dispatch、call_id 与本地执行，下一轮保留 function_call_output。encrypted reasoning 仅在请求重放中存在，不进入 Trace/日志。
- Router/Planner completion 也收集同一 SSE 流。成功要求 `response.completed` 且 response status 为 completed；failed/incomplete/error、非法事件、断流、超时与取消明确暴露。
- 真实服务出现有效 SSE 但缺 Content-Type：缺失时继续按事件协议验证，显式错误 Content-Type 仍拒绝；不能仅依据 HTTP 200 宣布成功。
- JSON mode 的真实 HTTP 400 证明服务检查 `input` 中的 JSON 提示，`instructions` 中已有 JSON 不足以满足检查。Adapter 为全部 JSON 请求添加固定 developer 前缀，保留原 user query、业务 instructions 与完整历史；Trace 同源记录该协议前缀。
- 真实 `response.function_call_arguments.done` 缺 SDK schema 要求的 `name`。仅按 `item_id` 关联本次已验证的 `output_item.added.function_call.name`，不猜工具名、不修改 arguments/call_id；关联缺失明确 `UNASSOCIATED_TOOL_CALL`。Trace 记录该映射次数，不能改用全面宽松事件验证掩盖差异。
- 已知额度/资格/权限故障通过 `CompletionProviderError.stops_inference` 中止 Query，禁止 Planner skip 后再调用 Runtime。其它 Provider 与普通 JSON/timeout 的既有规则恢复语义不变。

## 观测与 Evaluation

- Token 不进入 ModelSettings、repr、日志、Trace、Evaluation 或浏览器存储。认证/推理错误在边界脱敏后才构造安全异常。
- 成功与失败均保留可用的 status、request ID、终态、Usage 与公开错误形状；Usage 缺失是 unknown。失败 Response 不复制 output/reasoning/encrypted_content。
- `runtime.configuration` 是实际配置的同源 Trace 快照；Evaluation 保存实际 Provider/model、配置、Usage、安全错误原因，与冻结 ControlledVariant 声明分开。新增结果不覆盖历史 Baseline。
- 独立 Chat Completions judge/annotator 明确拒绝 chatgpt-plan；生产 Query Evaluation 继续通过 Application.query 执行。

## 必须验证的行为

`test_chatgpt_auth.py` 覆盖首次/重登、OIDC/state/nonce/scope、刷新轮换与终态错误、账号隔离、锁、撤销、目录与脱敏。`test_chatgpt_responses.py` 覆盖真实 SDK namespace 工具循环、完整输入重放、SSE 终态/错误/取消/超时。`test_chatgpt_query.py` 覆盖 SQLite 工具、Finalizer、Session、Trace 和额度提前终止。配置与阶段观测分别见 `test_chatgpt_settings.py`、`test_completion_transport.py`。

真实验证使用 `scripts/verify_chatgpt_plan.py`，证据落在新的 ignored `data/evaluation/chatgpt-plan/` 目录；不能将 Mock 测试或 HTTP 200 宣称为真实 Agent 成功。具体运行事实记录在 task 验证文件中。

## GPT High 与 Prompt Screening（2026-10-18）

### 1. Scope / Trigger

显式设置 GPT reasoning effort、执行 Prompt frozen/candidate/paired 实验时适用。历史首条请求在
`response.metadata` 遇到 `MALFORMED_STREAM`；后续已按真实wire和官方Codex源码扩展严格类型。
真实High三轮completed已验证协议，工具索引不就绪的该次结果不能当作质量Baseline。
独立索引就绪后的真实答案验证见[续跑报告](../../tasks/10-18-gpt-high-ablation-resume/experiment-report.md)；
后续TLS连接失败与未完成门禁不能记作metadata修复失败或Prompt质量通过。
本轮报告见 `10-18-gpt-high-prompt-ablation/report.md`（任务归档后位于 archive）。

### 2. Signatures

- `ModelSettings.chatgpt_reasoning_effort: str | None`；环境键 `TRIVAE_CHATGPT_REASONING_EFFORT`。
- `ChatGPTResponsesModel(..., reasoning_effort=None)`；`_reasoning_parameters()` 同源构造 payload/projection。
- `ScreeningRuntime.install_provider_budget(budget)`；`ProviderCallBudget.before_request(request)`。
- `verify_frozen_baseline(artifact, conditions, baseline_prompt)`。

### 3. Contracts

- 只允许精确 `chatgpt-plan / gpt-6.1-sol / high`；不猜其它模型能力或 context，未知档位显式失败。
  未设置时保留既有 Provider 默认语义。此白名单只控制请求参数，不代表账号授权/完整实测通过。
- Runtime/Router/Planner 的 GPT 请求共用同一个 Model 的 `reasoning={effort:high,summary:auto}`；
  completion 的 SDK ModelSettings 不覆盖该配置；safe settings/Trace/projection 保留公开 effort。
- GPT 模型没有传统 `_provider_client`；实验门禁安装于 Responses 自有 httpx client，传统路径
  安装于 OpenAI client 的 HTTP 层；保留已有 hooks，不替换 OAuth/SSE/工具/Finalizer 语义。
- 每次 inference HTTP 发送前占用本轮与总量计数，含失败及后续工具轮次；总 ledger 顺序复用，
  不支持多进程并发计数。目录读取/认证不冒充推理次数，真实实验不得绕过安装门禁的 client。
- 请求 artifact 保留公开 effort/summary、instructions、tools 和可见 input；过滤 replay 中
  type=reasoning item（包括 encrypted_content），不保存鉴权 header/隐藏推理。
- Frozen conditions 保存实际 Provider projection、SDK contract/settings、canonical snapshot 和
  semantic_index_status 的实际身份/状态；不同 effort/chunker/状态拒绝复用。canonical count
  相同不等于派生索引相同。失败文件保留但标记 failed_baseline；旧 frozen 标签下实际失败也拒绝。

### 4. Validation & Error Matrix

| 输入/状态 | 行为 |
|---|---|
| 该精确 GPT 组合 + high | payload 和 projection 一致；真实终态仍需单独验证 |
| medium/low/未知模型或其它 Provider 搭配该配置 | SettingsError，不静默忽略或改档 |
| 预算用尽 | request hook 在 transport 前拒绝；失败仍留 ledger |
| response.metadata | 严格要求type/response_id/非负int sequence_number/JSON object metadata，禁止额外顶层字段；记录安全旁路身份并继续等待终态 |
| 未知事件类型、畸形metadata、缺必需字段 | MALFORMED_STREAM，绝不泛化跳过未知事件 |
| metadata响应身份变化或与completed不符 | METADATA_RESPONSE_MISMATCH，禁止将旁路与另一响应拼接 |
| 失败 Baseline / effort / semantic identity 漂移 | candidate-only 在新推理前拒绝 |

### 5. Good / Base / Bad Cases

Good：先静态、真实4条 smoke、同条件逐组候选；工程失败即停。Base：未配置 effort 的历史账号
路径保留原请求。Bad：HTTP200就宣布 High 完整验证；将 stale v1 index 冒充当前 v2；重置 ledger
或将失败 frozen artifact 用作有效语义对照。

### 6. Tests Required

`test_chatgpt_settings.py` 覆盖精确配置与错误组合；`test_chatgpt_responses.py` 覆盖三条路径实际
HTTP序列化、失败计数、已知metadata校验/观测及未知或畸形metadata明确失败；`test_prompt_screening.py` 覆盖真实 SDK 两轮、
发送前拒绝、跨实例总量、隐藏 replay 排除、失败 baseline/effort/index 漂移。static 入口包括这些
相关 Provider/OAuth/query/completion 回归。Mock 不代表真实模型质量。

### 7. Wrong vs Correct

Wrong：只在 Python settings 写 high、只给传统 `_provider_client` 装 hook、忽略 reasoning 配置
身份、为继续实验跳过未知 SSE。Correct：仅对实测且有官方源码依据的订阅旁路事件增加显式typed
envelope和安全观测，SDK标准事件/终态/工具/Usage/Reasoning继续原链路，再以真实High验证。

订阅扩展依据：[官方Codex SSE实现](https://github.com/openai/codex/blob/8c076942cb70fba8e5c4732c23f1faabc4aed484/codex-rs/codex-api/src/sse/responses.rs)。
Python SDK的ResponseStreamEvent（已安装3.5.0与核对的新版main）没有该tag，盲升依赖不解决
联合类型缺失；因此保留已验证SDK版本。metadata只投影response_id、sequence_number、顶层metadata
键，不保存审核正文，不作为assistant输出、隐藏reasoning、Usage或完成信号。

## TLS 空异常诊断（2026-10-19）

### 1. Scope / Trigger

真实失败在收到 HTTP 状态前表现为空 `ConnectError`。AnyIO 的 `raise EndOfStream from None`
会隐藏底层 `SSLEOFError`；仅看 message 或 `__cause__` 会丢失握手 EOF。

### 2. Signatures

已有 `ChatGPTResponsesError.safe_observation` 在 `httpx.TransportError` 时增加
`transport_exception_chain: list[dict[str, str]]`，每项仅 `type` 和 `message`。

### 3. Contracts

优先遍历显式 cause，否则读取 context（包括 suppressed context）；每项 message 先经过
`auth.redact()`，再限制为500字符。不保存 Request、header、body、traceback 或隐藏 Reasoning。
此字段只补诊断，不新增连接策略、重试、降级或请求，不代表外部 TLS 已修复。

### 4. Validation & Error Matrix

|输入|行为|
|---|---|
|ConnectError → EndOfStream → suppressed SSL EOF|原 `PROVIDER_ERROR`，安全链保留 EOF 类型和脱敏消息|
|ReadTimeout|原 `REQUEST_TIMEOUT`，增加同形安全链|
|预算发送前拒绝、普通 SDK/业务错误|不展开传输链，保留原处理|

### 5. Good / Base / Bad Cases

Good：用真实失败形状复现，记录可见原因，并单独验证真实网络恢复。
Base：成功 SSE、Usage、终态、工具和取消语义不变。
Bad：将空 ConnectError 猜成证书错误，关闭 TLS 校验，或把一次401探测成功称为多轮稳定。

### 6. Tests Required

`test_tls_eof_context_is_visible_redacted_and_keeps_original_http_budget` 断言隐藏 EOF、底层秘密脱敏、
observer 同源观测、一次失败占账和下一次发送前阻止；timeout 与普通业务错误分类回归保持。
真实网络诊断须区分 HTTP CONNECT 与 TUN：macOS 的 `NO_PROXY`/`AsyncConnectionPool` 不能证明绕过系统 TUN。

### 7. Wrong vs Correct

Wrong：仅输出 `str(exc)` 或只查显式 cause；用强制 IPv4 掩盖已经在两地址族复现的 EOF。
Correct：保留可验证的 cause/context 安全事实，冻结实际连接条件；网络变化后新建同条件 A/B，
不复用失败 Baseline，也不重置120次推理账本。
