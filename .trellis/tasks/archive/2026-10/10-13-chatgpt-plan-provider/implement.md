# 实施

1. OAuth/受保护凭证/CLI 模块与 mock 测试。
2. Responses SDK Model、Runtime 分支、completion/观测、mock SDK/Query integration。
3. Settings/readiness/Evaluation safe identity、文档和兼容测试。
4. ruff、mypy、pytest 全集；修复主链路。
5. 启动 OAuth，等待用户浏览器授权；授权后 models 和四类生产 Query/Trace 核验。
6. 更新可执行 spec 与验证记录，提交工作；按真实完成状态 journal/归档；统一推送。

三份实施模块由 Trellis 要求的工作代理分别负责，主代理负责集成、检查和真实验证。修改范围：auth 新模块/cli auth，query/runtime Responses 新模块和原 Adapter 接入点，settings/readiness/Evaluation identity，测试及配置文档。既有 retrieval/finalizer/session schema 不变。

检查命令：uv run ruff check src tests；uv run mypy src；uv run pytest。OAuth credential 和实际请求只留本地受保护目录，测试 mock 不使用用户 token。
