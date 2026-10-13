# 实现与验证记录

## 架构
选择 B：独立受限 Responses SDK Model，沿用 openai-agents 0.22.0 Runner、生产 Application.query 和现有检索/证据/Session。OAuth 完全独立于 ModelSettings；原 Provider 与 Jev 默认行为保持。

## 自动化与质量门禁
- uv run ruff check src tests scripts/verify_chatgpt_plan.py：通过。
- uv run mypy src scripts/verify_chatgpt_plan.py：121 个源码文件通过。
- uv run pytest -q：1006 passed，24.10s（最终冻结版本）。
- pnpm -C web build：vue-tsc 与 Vite 生产构建通过。
- git diff --check：通过。
- 新覆盖 OAuth、scope/OIDC、refresh/rotation、账号绑定、SDK namespace、SSE、JSON、取消/超时/错误、生产 SQLite/Finalizer/Session、Trace/Evaluation 与旧 Provider/Jev 回归。

## 真实账号
本人完成系统浏览器 OAuth，验证账号身份与 direct scope；实际模型目录返回七个 slug，从服务器排序选择 gpt-6.1-sol。未复用 Codex 或私有 backend 凭证，也未使用普通 OpenAI API key。自动刷新/轮换与logout只通过 Mock，未等待自然过期或撤销实际会话。

## 真实主链路
20261013-sol-06 四类查询全部成功且Finalizer valid。fact/analysis/followup/structured 的Citation bindings为1/5/4/2，分别使用lexical_search、消息上下文、get_schema/execute_sql。追问与analysis共用持久化Conversation，所有Provider attempts确认response.completed，Query/Answer/Tool终态齐全。人工抽查事实原文、分析证据归属、追问上下文和SQL口径。

Web真实HTTP NDJSON流返回100事件、stream.end completed和来源；Provider两次SSE completed。Trace：trace-f61a4f5636ab4c5fbbad3b098c121487。127.0.0.1:8711已启动并打开；readiness呈现chatgpt-plan/gpt-6.1-sol/ready。Jev真实模型仍独立出现typesafe/jev-1.13-20260917，配置未修改。

完整本机证据：ignored data/evaluation/chatgpt-plan/20261013-sol-06/；此前失败sol-01至05保留。最终凭证泄漏检查包含json/log/ndjson，共19文件，零命中，凭证权限0600。

## Failure Case 与取舍
真实修复：有效SSE缺header、JSON input提示必要条件、SDK args.done.name与实际SSE的差异；精确适配并保留验证，不删工具/放宽最终证据契约。可控集成修复：scope/terminal quota中止Query、账号目录与Token绑定、encrypted错误正文泄漏、readiness与refresh同loop锁阻塞。连接失败保留错误端点和类型，无计费fallback、无推理重试。

实际配置由runtime.configuration同源Trace进入Evaluation，不用冻结Variant声明替代执行事实。独立ChatCompletions Judge/Annotator明确拒绝订阅Provider。未知模型不猜context，不证明长期可用性或质量收益。

## Interview Defense Notes
可核验Problem/Motivation、Options/Rationale、Failure/Debugging、Evidence、Scale、Ownership和Evolution见interview-docs/事实核验-ChatGPT接入.md。私有原始消息不纳入Git。
