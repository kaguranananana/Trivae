# ChatGPT 接入事实记录

日期：2026-10-13。本文只记录本次实现和验证能证明的事实，不推断个人职责或业务收益。

## 问题、选择与边界

Trivae 原主模型使用 Chat Completions；ChatGPT 订阅协议要求 OAuth、公开 Responses、SSE、完整本地历史和 namespace 工具。选择独立白名单 Responses SDK Model，继续由固定版本的 Agents SDK Runner 执行 Agent 循环。原检索、Scope、工具预算、证据 Finalizer、Conversation 与 Jev 配置沿用现有契约；不升级 SDK、不增加第二套 Agent Loop。

考虑过直接使用 SDK 默认 Responses 模型：其请求构造、非流式 get_response 与本任务协议边界需要额外控制。因此选最小 Provider 边界，代价是必须维护真实 SSE 与 SDK 类型之间的精确映射。未来 SDK 升级或服务事件改变时，应重跑该协议测试，而非全面放宽解析。

## 已测事实

- 官方动态注册、本人浏览器授权、OIDC 验证和 direct scope 成功；查询实际账号模型目录后使用 `gpt-6.1-sol`。
- 四类生产 Application.query 查询均通过原答案契约，Finalization 全部 `valid`。

| 查询 | 实际工具 | Citation binding | Trace |
| --- | --- | ---: | --- |
| 事实检索 | lexical_search | 1 | trace-ff53644b12d04d6aab5ce59a6921f302 |
| 复杂分析 | lexical_search、两次 get_message_context | 5 | trace-831a31725c6f4af0b98d3e1acaa43afc |
| 多轮追问 | lexical_search、get_message_context | 4 | trace-d6cc03451bc64bb28386ce6842c2cddb |
| 结构化统计 | get_schema、execute_sql | 2 | trace-74dd5571d4e54756ab62584f2286a530 |

- 追问与复杂分析复用同一持久化 Conversation；实际检索来源与引用经 Finalizer 绑定。抽查了事实原文、分析的证据归属、追问上下文和统计口径。
- 额外 Web 查询产生 100 个 NDJSON 事件，终态 completed、1 个可打开来源；对应 Provider 两次 SSE 均确认 completed。Trace：`trace-f61a4f5636ab4c5fbbad3b098c121487`。Web 的 Jev 仍使用独立 OpenRouter 配置。
- 全仓 1006 项测试通过；Ruff、Mypy（含真实验证脚本）、前端 build 与 diff 检查通过。
- OAuth 本机文件为 0600；本机真实结果/Trace 日志检查未发现 access/refresh/ID token 泄漏。

真实原文、完整请求上下文、答案、Usage 和日志仅在 ignored `data/evaluation/chatgpt-plan/20261013-sol-06/`。这组查询证明工程链路可运行，不是独立质量评测；未改变历史 DeepSeek Baseline，也不能解释成检索优化收益。

## 失败与定位证据

可控回归发现并修复：动态切账号造成目录/Token 混用、额度错误后 Planner 继续进入 Runtime、失败 Response 把 encrypted replay 复制到诊断。对应代码与测试分别位于 `chatgpt.py`、`completion.py` / `planner.py`、`chatgpt_responses.py`。

真实服务暴露三项协议差异：有效 SSE 缺 Content-Type；JSON mode 只检查 input 中的 JSON 提示；function_call_arguments.done 缺 SDK 所要求的 name。修复限定在 Provider 边界：按实际事件确认终态、统一 developer 提示、按 item_id 关联本次已验证函数名。未知关联仍明确失败，工具与证据契约未放宽。

早期还发生模型目录连接失败，保留失败记录和端点/类型诊断；没有添加推理重试或静默切换。历史尝试保存在 sol-01 至 sol-05 目录，不能从后续成功推断外部网络永久稳定。

## 限制、扩展与口径

- 自然过期后的真实 refresh / logout 撤销未执行；这些行为由可控 Mock 验证。授权范围不足、Quota、超时、撤销等错误没有用真实账户制造。
- 凭证锁使用 POSIX flock，当前 macOS 已测试；没有验证 Windows。
- 独立 Chat Completions judge / retrieval annotator 不使用该订阅 Provider；生产 Query Evaluation 支持并记录实际配置。
- 本地最大回合、工具轮次和证据预算仍生效；官方协议不允许发送 server max tokens。没有测量高并发、长期额度或模型质量收益。
- 规模扩大时首先观察现有 Trace 的 HTTP 时延、Usage、工具预算与 Scope，而非预先增加重试、缓存或多 Agent 架构。

Interview Defense Notes：为什么选边界 Adapter → SDK 默认参数与订阅协议不同；失败怎么发现 → 安全状态/错误码、事件字段诊断与原始 Trace；如何证明 → 真实 SDK Mock 和五次完整生产/Web 查询；何时演进 → SDK/官方事件改变，或真实部署暴露新的可复现 Failure Case。
