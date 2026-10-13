# 设计

## 边界与数据流
新增 auth/chatgpt 模块负责本机 host 与账号注册、loopback OAuth、ID 验证、凭证和 refresh。CLI 薄命令层提供 login/status/logout/models/account selection，凭证不进入 Settings/Trace。

主模型新增 chatgpt-plan identity。使用现有 SDK Model 边界实现独立 Responses Adapter，复用 SDK message/tool 转换与 Runner 的 function dispatch，同时显式控制公开请求允许字段、namespace 和 terminal validation。Router/Planner 用相同模型完成流收集。

## 技术路径
评估 A：原 SDK Responses 模型直接使用会发送不支持的参数、平铺 tools，并存在 nonstream get_response。因此采用 B：最小 SDK Model 实现独立受限 HTTP/SSE boundary；Agent Runtime 仍复用 SDK Runner，不另建 loop。无 SDK 升级。

## 兼容与失败
保留既有 Chat Completions Provider 原路径。OAuth session 只存在独立存储；跨进程锁串行刷新，原子保存轮换凭证。标准错误保留 code/status/request ID，敏感凭证脱敏。禁止欠费 fallback；取消关闭 stream，缺少 response.completed 为错误。

## 验证与回退
Mock 通过真实 SDK Runner 与 Application.Query 断言 tool call/result、JSON 答案、Citation、Trace、Session；真实授权只使用 Trivae 自己注册的凭证。不改当前 .env，默认 Provider 不变，切回 deepseek 即回退。
