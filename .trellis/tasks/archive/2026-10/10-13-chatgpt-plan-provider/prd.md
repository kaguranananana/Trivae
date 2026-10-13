# ChatGPT plan Provider

## 目标
通过官方 Sign in with ChatGPT OAuth 和公开 Responses API，让授权账号的 GPT 模型执行生产 Query 完整链路。原始需求见 request.md，全部条目纳入本任务。

## 已确认事实
SDK 固定 openai-agents 0.22.0；主模型 Runtime 提供 Router/Planner completion，Application 复用同一 Runtime。Jev 使用独立 OpenRouter 配置。当前分支 main，有无关 .opencode/package.json 修改。

## 要求与验收
- 官方动态注册、PKCE/state/nonce/OIDC/JWKS、scope、稳定 host ID；受保护仓库外存储、串行刷新轮换、重登录和 logout。
- chatgpt-plan 配置；账号模型目录选择，不猜模型、不采用 API key 计费。
- Responses store=false/stream=true、允许参数、namespace function tools、完整历史、终态确认；保留 SDK loop/tool budgets/Finalizer。
- Router/Planner/Runtime、取消/超时/故障、Usage/Trace 和 Evaluation identity 可观测；原 DeepSeek/OpenCode Go/Jev 行为不变。
- Mock 验证 OAuth 与 Provider 故障、生产查询工具执行、结构化答案与多轮上下文；完整质量检查。
- 启动浏览器 OAuth；授权后执行真实四类 Query 并核对 Trace。授权未完成必须标明真实调用未验证。
- 操作文档、工作提交与收尾提交后统一 push。

## 边界
不改变检索、证据契约或 Agent 架构；不使用私有 backend-api、Cookies 或非官方 token；不静默切换计费。PKCE 使用标准库实现的官方 S256 方法，仅用于协议所要求的 challenge；不新增业务摘要/哈希。

## 授权
用户明确要求简短方案后直接实施、不等待确认，覆盖技能默认的阶段二次确认。浏览器授权必须由本人完成。
