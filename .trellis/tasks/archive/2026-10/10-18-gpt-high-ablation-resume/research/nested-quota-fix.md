# HTTP 200 SSE 嵌套额度错误分类修复

## 真实失败与根因

2026-10-19 00:31:16 UTC 的 `user-node-book-b01` A 请求收到 HTTP 200，在合法 `response.metadata` 后出现 SSE：外层 `type=error`、`sequence_number=3`，内层 `error` 包含 `type=invalid_request_error`、`code=subscription_sharing_usage_limit_exceeded`、Provider 的共享额度耗尽消息和 `param=null`。没有 `response.completed` 或 Usage。

原适配器对 `response.failed/incomplete` 读取内层错误，但对 `type=error` 直接把整个外层事件当作错误叶子，因而找不到实际 `code/message`，错误被归成 `error: error`。尽管旧安全 body 保留了嵌套原文，`ChatGPTResponsesError.stops_inference` 接收到的代码仍为 `error`，未触发现有共享额度硬停合同。问题属于 Provider envelope 解析及错误分类，不是 Prompt 质量或 HTTP 成功。

本次只本地回放，不再次发送真实 Provider 请求。此旧请求距最新授权已数小时，不能据旧额度错误宣称当前额度一定未恢复；额度恢复的真实验证由主 Agent 在原共享总账本和明确新预算上限下另行执行。本修复不推测额度重置时间，也不将 Codex Agent 限额当作 Subscription Sharing 限额。

## 最小实现

- `chatgpt_responses.py` 增加 `_NestedResponseErrorEvent` 和 `_NestedResponseErrorDetail` 两个严格 Pydantic 模型。外层只允许 `type=error`、非负严格整数序号和错误叶子；叶子只允许非空字符串 `type/code/message` 以及字符串或 null 的 `param`，所有字段必需，额外字段拒绝。
- 仅对 `type=error` 且显式存在 `error` 字段的已证实 envelope 使用该模型。先严格验证，再读取叶子，将真实 `code/message` 交回原错误构造器。未知 code 不被改名为额度错误；已知 `subscription_sharing_usage_limit_exceeded` 自然命中既有 `stops_inference=True`。
- 旧平铺 error、`response.error`、`response.failed/incomplete` 的既有语义保持原分支，未知事件继续 SDK 判别联合拒绝。畸形嵌套字段进入既有 `MALFORMED_STREAM`，不按不完整字段猜额度。
- metadata 仍只作旁路观测。错误流保留 HTTP 200、request ID、metadata 和真实 terminal error，但不制造 completed、Usage、工具结果、最终答案或成功状态。错误消息/body 继续走现有认证脱敏边界。

没有改生产 Prompt、工具、SDK、OAuth、TLS、重试、网络配置、预算账本或 Runtime/Router/Planner 策略。它们已有的终止语义通过正确的错误代码恢复工作，未增加新降级或恢复路径。

## 回归证据

先本地回放真实 envelope：adapter 五项测试全部红灯，其中合法额度被错误归成 `error`，四种畸形 envelope 也没有被协议拒绝；Application 三阶段回归同样红灯，Runtime 错误代码为 `error`，Router/Planner 没有抛出应硬停的异常。

修复后的测试覆盖：

- metadata → 嵌套额度 → 无 completed，提取真实叶子代码/消息、`stops_inference=True`、HTTP 200 保留、Usage 未知、错误脱敏、原 ledger 恰计一次 HTTP。
- 非对象错误叶子、缺少必需 code、布尔序号、额外外层输出字段均 `MALFORMED_STREAM`，不复制未经验证的 body。
- 正式 `Application.query` → Runtime、Planner、Router 三个入口使用同一 Mock HTTP 边界；每个入口始终只有一次发送及一次预算记录。Router/Planner 错误直接传播、不继续 Runtime；Runtime 失败且无工具、最终答案或 answer artifact。
- 同时执行既有平铺错误、failed/incomplete、metadata、工具多轮、Reasoning replay、Usage、取消及 Completion 回归。

检查命令与结果：

```
uv run --all-extras pytest -q tests/test_chatgpt_responses.py tests/test_chatgpt_query.py tests/test_prompt_screening.py tests/test_completion_transport.py
77 passed in 1.56s

uv run --all-extras ruff check src/trivae/query/runtime/chatgpt_responses.py tests/test_chatgpt_responses.py tests/test_chatgpt_query.py
All checks passed!

uv run --all-extras mypy src
Success: no issues found in 128 source files

git diff --check
通过
```

子任务未提交，由主 Agent 统一更新规范、执行真实额度恢复验证、记录实际版本与预算、审查并提交。以上测试证明错误解析和主链路硬停正确，不能冒充真实额度已经恢复或 A/B/C 质量门禁已经通过。
