# TLS 诊断补丁最终源码检查

按 Trellis 2.2 对当前任务受影响源码范围检查：已读当前 PRD/design/implement/check context、后端与项目规范索引、质量/错误/日志及 ChatGPT Provider 合同。`get_context.py --mode packages` 返回单仓库、无独立 packages，spec 层为 backend/project。复核包含前轮已审 SSE typed metadata 路径及本轮 TLS 异常链增量，没有涉及模板或平台配置同步点。

独立 Codex Agent 模型复核，不是人工裁决；未向 Trivae 被测 Provider 发送 Judge 或实验请求，未提交代码。仅新增本记录，保留其它任务改动。

## Findings (fixed)

无。Ruff、mypy 与相关回归均通过，未发现需要机械自修的源码问题。

## Findings (not fixed)

- `chatgpt-plan-guidelines.md` 尚未记录新 `transport_exception_chain` 的诊断合同。建议主任务收尾补充：仅 TransportError 展开真实 cause/context，逐项只保留脱敏类型/短消息；不改变错误分类、重试或成功语义，并引用本轮真实 SSLEOF failure 与新回归。属于本次新观测行为的文档同步，不应宣称网络修复。
- `implement.md` 的历史执行状态仍写 52/120、未执行最后四条等旧停止点。后续真实阶段正在推进，应由主任务统一更新当前报告/状态，保留旧阶段历史，不能把旧数字当当前总量。本 Agent 不修改并行维护的实验记录或状态。
- 既有工具投影小余量失败/SDK UserError 分类缺口仍在，详见 `tls-quality-review.md`；本轮 TLS 诊断只针对 `httpx.TransportError`，没有声称解决该独立问题，也没有越界修改工具预算或 finalization 行为。

## 源码合同核对

- 新增逻辑仅在已有 `except Exception` 内，对 `httpx.TransportError` 增加结构化诊断；非 TransportError 不展开业务/SDK/工具上下文。
- 异常链优先走显式 cause，否则读取真实 context，因此能保留 AnyIO `from None` 隐藏的 SSL EOF。只保存类型和 `auth.redact(str(current))[:500]`，脱敏发生在截断之前；没有复制 Request、headers、body、traceback、隐藏 Reasoning 或凭据对象。
- Auth 的既有 Bearer、授权 URL、已记住 OAuth 秘密等脱敏仍在同一边界。新测试在最底层 SSL message 注入 token，断言整个安全观测中不存在原秘密，observer 也收到相同脱敏链。
- 错误仍为原 `PROVIDER_ERROR` 或 `REQUEST_TIMEOUT`；取消、ChatGPTAuthError、已分类 Responses 错误均保留原分支。未改 endpoint、TLS 校验、代理选择、payload、High、SDK 版本或错误恢复行为。
- 没有新增请求或重试。新回归通过同一 `ProviderCallBudget` 证明第一次失败只占一个原账本名额；第二次调用仍在实际 transport 前拒绝，未再发送，也不伪造 transport 根因链。
- SSE typed metadata、未知事件拒绝、failed/incomplete、completed status、断流、工具 done-name 关联、Usage 与 Reasoning replay 均保持原实现，相关真实 SDK 回归继续通过。

## 时间 A 只读质量补核

`tls-time-zero-validation` 的时间 A 为 completed，C 第三 HTTP 失败且无答案，因此本节只有 A 单边裁决，不能形成候选质量方向。

A 实际按 archive_latest 的相对7天读取，后续原样 continuation cursor 再取下一页。Host UTC 半开范围与答案一致，独立 Canonical 同区间 COUNT=15221；Artifact 为 retrieved/covered=200、has_more=true、partial。第一工具模型投影100条完整，第二工具因剩余预算只投影26/100，因此不能说模型完整看过200条。

答案明确“靠近窗口末尾的讨论摘选、非完整周报”，Artifact 也说明200条中部分未完整展示、远不足以概括全周，没有将 partial 覆盖写成 complete 或按全周频次/共识排序。5项讨论的全部21条最终来源，逐条作者/UTC/原文与 Canonical 相等，并在实际 Provider 输入中存在完整可见文本，均在目标范围内。

归纳保留个人体验/担忧与官方政策的区别、实际使用自述与效果未验证的区别、排查猜测与确定原因的区别、计划与已实施的区别，未发现新增事实或强否定问题。此 Case 的覆盖约束通过，但不能因此接受未完成的 C 或推广为全周完整主题召回。Agent 复核不替代原人工 ReviewPolicy。

## Verification

- Packages/full-scope：单仓库 backend/project，已加载受影响规范。
- Lint：`uv run ruff check src tests` 通过。
- TypeCheck：`uv run mypy src` 通过，128 个源文件。
- Diff whitespace：`git diff --check` 通过。
- Tests：`test_chatgpt_responses.py`、`test_chatgpt_auth.py`、`test_chatgpt_query.py`、`test_chatgpt_settings.py`、`test_completion_transport.py`、`test_prompt_screening.py`，**122 passed，6.00秒**。
- 全量 pytest 由主任务运行；本 Agent 没有把旧全量数字写成本轮重新运行结果。
