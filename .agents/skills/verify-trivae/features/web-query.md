# Web 查询 API

用户提交问题后收到流式响应，可以继续追问同一会话。会话范围在续问时受服务端约束。

## Sub-features

- `web-readiness` 确认数据库已初始化并能列出会话来源。
- `web-stream` 验证查询流的事件、终态和持久化。
- `web-follow-up` 验证同一会话的续问以及范围变更拒绝。

## How to get to it (user POV)

Web 界面提交问题和续问时调用 `POST /api/query/stream`，会话列表来自 `GET /api/conversations`。服务就绪与聊天来源由 `GET /api/readiness` 和 `GET /api/source-sessions` 提供。

## Driving it with pytest and ASGI

前提是已完成 Skill 的 Launch。用 `tests/test_web_server.py::WebApiTests` 中的三个用例向真实 ASGI 路由发送 HTTP 请求。

- `test_readiness_and_source_sessions` 检查数据库为 `ready`，空库返回空来源列表。
- `test_stream_query_completes_with_sources_and_end` 检查 NDJSON 流中有答案片段，最终 `stream.end` 为 `completed`，携带 conversation ID 与 Trace ID。再从会话列表确认已持久化两条消息。
- `test_stream_follow_up_reuses_conversation_and_rejects_scope_change` 检查续问沿用同一 conversation ID，更改范围被拒绝。

## Gotchas

- Web 测试注入固定 Runtime，核验 HTTP 路由、流协议和会话持久化。SDK 检索与来源绑定走各自的查询用例。
- 浏览器渲染、前端交互和真实监听端口均需要独立运行。
