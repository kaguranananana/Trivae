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
