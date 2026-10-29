# Eval v1 两次运行失败排查 · 2026-10-29

本次核对 2026-10-28 原始 Run、Trace JSON 和文本日志，以保存记录为准。原 Baseline 仍是 16 次尝试、14 次成功、2 次运行失败；没有补跑或覆盖结果，没有调用 Agent/Judge。下列时间均为 UTC+08:00。

| Case | 原问题 | 失败位置 | 可确认的原因 |
| --- | --- | --- | --- |
| 03 `cap1-03-task-progress` | 怎么让 Agent 在长任务里记住进度，换个会话也能接着做？ | 16:56:39–16:57:32；一轮工具成功后，第二次模型调用的答案正文 | JSON 字符串内出现未转义英文双引号，后续汉字被当成字符串之外的非法内容。 |
| 14 `cap1-14-agent-interview` | AI Agent 项目面试一般会问什么？有什么准备建议？ | 17:13:05–17:13:06；Router 请求和后续 Runtime 请求均失败，未调用工具 | 两个请求均为 `APIStatusError`；原记录缺少 HTTP 状态、错误分类与请求 ID，不能继续区分具体 Provider 原因。 |

## Case 03：非法正文已复现，解析器没有误判

原 Trace 的 `answer.parse.failed` 保存了正文起始处的诊断。故障片段为：

```text
{"claims": [{"text": "群里的共识是：跨会话续做的关键不是"不断
```

`不是` 后的英文双引号提前结束了 `text` 字符串；紧随其后的 `不` 位于 Unicode 偏移 40（从零计数），解析器此时需要逗号或右花括号。Python `json.loads` 在相同位置报 `Expecting ',' delimiter`；当前增量解析器按 1、2、7 和整段 42 字符四种切片重放，全部在偏移 40 报同一错误。正确转义相同形状的引号后，增量预览正常保留正文引号。

第一轮 `semantic_search`、`lexical_search` 均完成，没有工具错误；第二轮在首条 claim 的字符串内失败，并非输出长度耗尽或工具轮数到顶。原 Trace 的 HTTP 200 属于已完成的第一轮工具调用，不能把它说成第二轮完整响应的传输事实。失败正文只保存了局部窗口，未保存整个答案。

旧运行版本和当前实现均已请求 `response_format={"type":"json_object"}`，Prompt 也已有 JSON 形状示例。新增 SDK 请求构造回归确认当前实际调用确实带上该参数，不能将本次故障诊断为漏开 JSON mode。[DeepSeek 官方说明](https://api-docs.deepseek.com/guides/json_mode/)要求这一参数、JSON 提示和适当输出上限；本次记录表明应用收到的公开正文仍违反 JSON 契约。

可采取的后续修复是保留严格解析，将故障片段、请求配置及可获得的 Provider 请求 ID 用于上游问题定位；若要调整模型或 Prompt，应单独对照复验，包括引号、反斜线和换行的正常正文。本轮未修改 Prompt、未放宽解析、未自动补齐引号或重试，因此不宣称已经解决 Provider 的非法输出。

## Case 14：Provider 拒绝请求，原始具体原因不可恢复

Router 在约 421ms 后记录 `ROUTER_COMPLETION_PROVIDER_ERROR` / `APIStatusError`，沿既有路由契约进入 Standard 路径；后续 Agent 请求再次报 `APIStatusError`，整个 Query 约 855ms 后失败。Runtime 为零工具调用、零工具轮，没有最终答案，且无可用 Token 用量。这里是两个阶段各自的一次请求，不是产品自动重试；后续 Judge 的 OAuth 连接错误也不是这次 Agent 失败。

当前根因定位缺口位于两个 HTTP 边界：

- `_ObservedChatCompletionsModel._fetch_response` 原先只有成功拿到响应后才安装流观测；HTTP 直接被拒绝时尚未创建流，因此状态和请求 ID 丢失。
- Router/Planner 的非流式 completion 原先直接抛 SDK 异常，现有 provider-neutral 观测通路没有收到安全的 HTTP 元数据。

已在 [openai_adapter.py](../src/trivae/query/runtime/openai_adapter.py) 补齐两条路径：保存 HTTP 状态、请求 ID、SDK 异常类型、可用错误 code/type，并明确零 chunk、未完成；Runtime 原异常继续抛出，completion 通过现有 `CompletionProviderError` 携带观测。没有保存完整错误响应，也未新增重试、fallback 或更换模型。

这些修改解决今后同类失败的诊断缺口，不能找回昨天丢失的 HTTP 事实。若需要追查昨天的具体 Provider 原因，应核对 10-28 17:13（UTC+08:00）的服务商后台记录；对新失败按实际状态处理。[官方错误码说明](https://api-docs.deepseek.com/quick_start/error_codes/)区分 401 凭证、402 余额、429 速率/并发限制及 500/503 服务端问题。本次没有证据把旧失败指定为其中一种。

## 验证与记录

- 原始片段重放与诊断提取保存在 ignored `data/evaluation/eval-v1-failure-audit-20261029/diagnosis.json`；原始证据位于 `eval-v1-baseline-20261028/full-record/`，未改写。
- 新增真实 SDK 请求构造 → Application → normal Trace 的 HTTP 503 注入回归，先复现缺少 `provider_observation`，再验证 Router、Runtime 均保存状态和错误分类，Query 仍失败且不写入 assistant 答案。503 是测试值，不是对旧错误状态的推断。
- 新增未转义引号与标准 JSON 解析器的同位置失败回归及合法转义对照。相关 77 项测试通过；全量验证结果见本次 [开发日志](DEVLOG.md)。
- 校正面试校准文档中将 Case 03 误写成“笔试经历”的标题；原 Case、题面、质量分数与 Baseline 分母均未改变。
