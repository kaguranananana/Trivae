# 任务：为 Trivae 接入 Sign in with ChatGPT，使用 ChatGPT Plus 订阅额度运行 Agent

## 一、背景与目标

当前项目为 Trivae，高噪声群聊分析 Agent。

仓库：https://github.com/kaguranananana/Trivae

目前使用 Python、OpenAI Agents SDK，通过 DeepSeek / OpenCode Go 等 OpenAI-compatible API 驱动 Router、Planner 和 Agent Runtime。

我希望新增 OpenAI 官方的 **Sign in with ChatGPT（ChatGPT plan usage）** 接入方式。

目标：

1. 在本地通过浏览器登录自己的 ChatGPT Plus 账号，完成 OAuth 授权。
2. 使用 ChatGPT 订阅额度调用账号有权访问的 GPT 模型，不需要额外购买常规 OpenAI API Token。
3. 让 Trivae 的完整查询链路使用 GPT 模型，包括 Router、Planner、Agent Runtime、Tool Calling 和最终答案生成。
4. 保留原有 DeepSeek、OpenCode Go Provider 和独立的 OpenRouter Jev Router。
5. 支持通过配置切换 Provider，保留现有 Evaluation 和 Trace 能力。
6. 完成自动化测试以及在有有效授权时的真实端到端验证。

本任务要求完成实际工程接入，不能仅停留在调研、PRD 或示例代码。

## 二、必须遵循官方接入方式

实施之前，请先阅读并核对以下 OpenAI 官方文档：

- https://developers.openai.com/siwc/token-sharing-open-source
- https://developers.openai.com/siwc/token-sharing-open-source/sign-in
- https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions
- https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference
- https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations
- https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery

以执行时官方文档为准，不要自行猜测 OAuth 参数、API Endpoint 或模型名称。

只使用官方公开且允许的认证与推理接口。不要使用 ChatGPT 私有 backend-api、浏览器 Cookie 提取、第三方逆向代理、非官方 Token 复用方案，也不要依赖 Pi Agent 的非公开实现。

特别注意，ChatGPT plan usage 走官方 Responses API，并存在以下限制：

- 推理请求必须设置 `store=false`、`stream=true`。
- 使用 OAuth access token 作为 Bearer 凭证。
- 不允许直接把现有 Chat Completions 请求结构原样转发到 Responses。
- 不能发送官方明确禁止的参数，例如当前预览限制中的 `max_output_tokens`、`temperature` 等。
- 系统提示词需要使用官方允许的 instructions/developer 消息表示。
- 必须正确处理 Responses 的流式事件以及工具调用协议。
- 只允许使用实际授权账号返回的模型列表，不能硬编码猜测可使用的 GPT 模型。

如果官方能力和 Trivae 当前实现存在冲突，优先遵守官方接口契约，并在本项目的 Provider Adapter 中解决兼容性。

## 三、先审计当前架构

请先阅读仓库最新代码、相关设计文档、测试和最近提交，确认实际调用链。

重点检查：

- `src/trivae/config/settings.py`
- `src/trivae/config/model_capabilities.py`
- `src/trivae/bootstrap/application.py`
- `src/trivae/query/runtime/openai_adapter.py`
- `src/trivae/query/router.py`
- `src/trivae/query/planner.py`
- `src/trivae/query/completion.py`
- `src/trivae/evaluation/`
- `src/trivae/observability/`
- `src/trivae/interfaces/`
- `pyproject.toml`

识别当前主模型 Provider 的创建、配置读取、生命周期和流式输出方式。

明确 Router、Planner 和 Runtime 如何共享或分别调用模型。

特别关注现有的 JSON 输出约束、工具注册、工具结果回传、Thinking 事件、取消机制、Runtime Budget 和证据校验。

以 ChatLab 已有适用的架构思想为参考，但不要为了增加 Provider 重新设计整套 Agent。

先形成简短的实现方案，然后直接继续实施，不需要等待我确认。

## 四、实现 OAuth 登录与凭证管理

为 Trivae 新增独立的 ChatGPT OAuth 认证能力。

按照官方开源应用文档完成动态客户端注册、Authorization Code + PKCE、state/nonce 校验、OIDC ID Token 验证以及授权 scope 校验。

必须校验 `chatgpt.tokens.use.direct` 是否实际获得授权。

首次注册使用官方规定的 `dynamic_agent_client`，保存授权后签发的 client_id。为本地主机生成并持久化稳定的 `ext_agent_host_id`，重新登录时复用已有注册信息。

实现安全的本地凭证存储，包括：

- Access Token
- Refresh Token
- ID Token
- 授权作用域
- 到期时间
- 已签发的 Client ID
- 经过验证的账号标识

提供 Access Token 自动刷新以及 Refresh Token 轮换处理。

凭证只能保存在本地受保护的位置，不能写入 Git 仓库、Trace、日志、Evaluation 结果或 Web 前端持久化存储。

建议增加 CLI 认证入口，命令名称可以遵循现有 CLI 结构，例如：

`trivae auth login --provider chatgpt`

`trivae auth status`

`trivae auth logout`

如果项目已有更合适的 CLI 结构，可以沿用。

登录时打开系统浏览器，由我本人手动完成授权。不要要求我把密码或 Token 粘贴到聊天中。

## 五、新增 ChatGPT 模型 Provider

为主模型配置新增明确的 Provider 类型，例如：

`TRIVIAE_MODEL_PROVIDER=chatgpt-plan`

模型名称通过授权账号的 `/v1/models` 查询结果选择，并提供明确的本地配置方式。

不要改变原有 DeepSeek 和 OpenCode Go 的默认兼容行为。

新增独立的 Responses API 适配器，并尽可能复用项目现有的 Provider-neutral 模型调用边界。

请评估以下两条技术路径：

A. 在当前 OpenAI Agents SDK 中接入 Responses 模型，并通过兼容适配满足 ChatGPT plan usage 限制。

B. 独立实现最小的 Responses Provider Adapter，将其映射到 Trivae 现有 Runtime 契约。

优先选择改动范围小、行为可验证、长期维护成本低的方案。

特别注意当前 `openai-agents` 版本及其 SDK 行为。若必须升级依赖，需要分析兼容性影响并完成回归测试。

接入后必须支持：

- Router 的模型判断（包括现有规则优先与降级行为）
- Planner 的规划请求
- Agent Runtime 多轮推理
- Function Calling 及本地工具执行
- 工具执行结果重新提供给模型
- SSE 流式输出
- 请求取消、超时与失败处理
- Token Usage 和 Trace 记录
- 最终结构化答案和来源引用

处理 Responses API 与现有 Chat Completions 的消息结构差异。

重点验证官方工具命名空间要求、工具调用 ID 关联、多轮上下文传递和 JSON 结构化输出约束。

不能通过删除工具、跳过证据验证或放宽最终答案契约的方式让新 Provider 表面上通过测试。

## 六、兼容现有业务与 Evaluation

保持以下能力不变：

- Canonical SQLite 数据存储
- FTS5 / Semantic / Structured Retrieval
- Capability Registry 及工具权限边界
- Agent Runtime 最大轮次与工具调用预算
- Evidence、Citation 和 Provenance 校验
- Trace 与 Web UI 流式事件
- Session 多轮上下文管理
- Evaluation 使用真实生产 Query 链路的原则

Jev Router 仍然保留独立的 OpenRouter 凭证与配置，不能将 ChatGPT OAuth Token 用于 Jev，也不要自动修改 Jev 的实验模式。

Evaluation 需要能够记录：

- Provider
- Model
- 当前模型配置
- 模型调用结果与 Usage
- 错误原因

不同模型的 Evaluation 结果必须能够区分，不要覆盖历史 DeepSeek Baseline，也不要把切换 Provider 后的结果直接视为检索优化效果。

如果遇到 ChatGPT 额度限制，不允许静默切换到产生额外费用的 OpenAI API 或 DeepSeek。必须明确报错，让我自行选择其他 Provider。

## 七、测试要求

实现完成后，请自动运行相关单元测试、集成测试和回归测试。

至少覆盖以下场景：

1. 首次 OAuth 登录及凭证保存。
2. 已有账号重新登录。
3. Access Token 到期后自动刷新。
4. OAuth 授权失败、Token 撤销或作用域不足。
5. 查询当前账号支持的模型。
6. Responses 流式文本生成。
7. 模型发起工具调用、本地工具执行、结果回传并继续生成答案。
8. 多轮对话与上下文恢复。
9. Router、Planner 和 Runtime 的新 Provider 路径。
10. 额度耗尽、请求超时、流中断以及非法响应。
11. Trace 和日志中的 Token 泄露检查。
12. DeepSeek、OpenCode Go 与 Jev 的兼容性回归。

对于 OAuth 和 Provider 错误场景，使用可控 Mock 测试，不要求通过真实账户制造额度耗尽等故障。

随后进行真实端到端验证。

如果环境已有我明确授权的有效 ChatGPT 凭证，就使用它完成真实测试。

如果还没有授权，则实现并启动正常的登录流程，提供需要我在浏览器中完成的授权步骤。不能代替我登录，也不能伪造真实测试结果。

真实测试至少包括：

- 简单群聊事实检索。
- 需要工具调用的复杂群聊分析。
- 一次多轮追问。
- 一次需要结构化最终答案及来源引用的查询。

所有真实调用都需要验证实际结果、工具执行轨迹、流式事件和 Trace。

不要仅以 HTTP 200 作为成功标准，必须确认最终收到成功结束事件并通过 Trivae 原有答案契约。

## 八、文档、提交与最终交付

更新 `.env.example`、README 或项目现有配置文档。

给出从零开始的用户操作说明，包括：

- 如何安装或更新依赖。
- 如何启动 ChatGPT 登录。
- 如何查询可用 GPT 模型。
- 如何在 `.env` 切换模型 Provider。
- 如何启动 Trivae Web UI 并实际提问。
- 如何退出登录或切换回 DeepSeek。
- 如何查看 ChatGPT 订阅额度使用情况。

完成修改后，运行全部相关质量检查和测试，将改动提交到当前任务分支。遵循仓库现有 Git 工作流，不覆盖无关的未提交改动。

最后汇报：

1. 最终选择的接入架构及原因。
2. 修改了哪些核心文件。
3. OAuth 登录、Token 刷新和模型调用是否真正完成。
4. 真实 GPT 模型是否成功完成 Trivae 的工具调用和最终答案生成。
5. 自动化测试结果以及真实测试证据。
6. 未解决的兼容问题与官方能力限制。
7. 我在本地需要执行的准确命令。

**执行原则：**

不要只输出设计方案或 TODO。请持续实施、测试和修复，直到能够交付可运行的接入方案。

除 OAuth 浏览器授权等必须由用户执行的操作外，尽量自行完成全部开发工作。

如果真实账号授权尚未完成，应明确区分“代码及模拟测试已完成”和“真实账号调用尚未验证”，不能把两者混为一谈。

最终目标是在保留 Trivae 现有架构和业务行为的前提下，通过官方 ChatGPT 登录方式使用订阅额度，让 GPT 模型真正运行完整 Agent 查询链路。