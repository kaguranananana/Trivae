# Failure Case：trace-68a55539c21f4b7f9b7f9a3bee045068

## 复现事实

- Query 主题：最近一个月内群聊中是否讨论过有价值的 GitHub 仓库、Skills 和资源。
- Trace profile：normal。
- Runtime terminal：`completed`；工具调用数为 7；SQL 执行数为 5。
- Final answer capture 中出现了分组后的仓库、Skill 和学习资源摘要，但 normal capture 对最终
  JSON 做了 bounded truncation。
- Citation validation 随后失败，Trace sequence 69/70/71 的根因错误码均为
  `STRUCTURED_VALUE_MISMATCH`；原始错误路径为 `null`。

## 影响

Runtime 的 provisional answer 已经流式显示，但没有 validated AnswerArtifact、Evidence 展示或
Conversation commit。用户只能看到概括性文字，无法从答案层定位原始消息和链接。

## Root cause boundary

当前 structured citation 要求模型把 Tool Result 中完整 `value_snapshot` 原样复制到最终 JSON，
随后 Finalizer 做 Python value equality。这个 contract 对大型 SQL row/聚合结果过于脆弱；同时
Finalizer 没有把 source 下标传入错误，因此 Trace 无法指出具体坏引用。

本任务的修复是缩小模型复制边界、保留 locator/scope/value 的确定性校验，并增加字段路径诊断；
不是接受不匹配值，也不是自动替换来源。

## 修复后真实回归

- 使用同一会话和同一问题重新执行，最终 Trace 为 `trace-2e3aaaacee2246ee991e2c2d7c143b34`，terminal outcome 为 completed。
- 终端只展示 Route、Plan/Tool/Retrieval facts 和最终 Answer；provider reasoning（包括字段名为
  summary 的内容）没有进入用户输出。
- 最终答案包含 4 个 claim→evidence 绑定、17 个可信 Sources，并展示了 GitHub/Skill URL、消息作者、
  时间、摘录、sufficiency 和 limitations。
- 相对时间窗口由 scoped SQL 返回 `2026-07-17 02:21:58` 至 `2026-08-16 02:21:58 UTC`；后续复现发现
  旧默认 `limit=20` 才是 `31` 条命中中只返回 `20` 条的直接原因，并非数据缺失。
- 早期真实 smoke 暴露的 provider 输出预算耗尽和 async generator cleanup 二次异常已分别通过 low
  reasoning budget、Tool-turn provisional text suppression 和显式 stream close 修复；未增加 retry、
  citation repair 或静默降级。

## Follow-up：31 命中被默认 20 截断

### 复现与根因

在真实会话 scope `qq:831907794` 和同一月度窗口中，默认 lexical 查询得到：

- `total_hits=31`
- `returned_messages=20`
- `truncated=true`

代码检索确认 20 不是单一 UI 展示限制，而是多个层的独立默认：trusted `ExecutionScope.max_results`、
`SearchMessagesInput.limit`、`LexicalQuery.limit`、SDK Function Tool schema，以及 Evidence transport
容量。只提高其中一层会导致模型 schema、Capability enforcement 或 provenance record 不一致。

### 修复与真实回归

- 抽出共用的有界 `DEFAULT_RESULT_LIMIT=100`，同步上述边界；不改成无界查询。
- 资源清单 prompt 使用 `limit` 最大可信值和 `context_before/context_after=0`，避免 31 个命中被邻近
  上下文消息消耗结果预算。
- 最终答案 prompt 强制 evidence/citation/闭合 JSON 优先，避免长链接清单再次造成 `MISSING_EVIDENCE`。
- 新增 31 条默认 lexical 回归；真实 Trace `trace-b5f6b74d8abe4f779078f1e1791a7d1e` 完成，检索没有
  partial/truncated，最终 1 个 citation binding、0 个 unresolved，并在终端展示 31/31 命中、具体链接
  和 Sources。

## Privacy boundary

本记录不保存完整群聊正文、provider payload、API key 或 hidden reasoning，只保存 Trace identity、
错误码、执行计数和失败归属。
