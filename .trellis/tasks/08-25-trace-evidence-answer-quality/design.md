# 真实 Trace 的证据答案与交互展示设计

## 1. Failure Case 与最小行为缺口

真实 Trace 的事实边界：

- Runtime 已完成，实际执行了 7 次 Tool Call；
- Finalizer 在 `citation.validation` 阶段失败，错误码为 `STRUCTURED_VALUE_MISMATCH`；
- `answer.finalization.failed` 和 `query.failed` 已记录，但普通 Trace 的 capture 已截断最终
  JSON，原错误路径为 `null`；
- CLI 在收到 `answer.delta` 时已经显示了模型的 provisional 文本，但 Finalizer 失败后没有
  AnswerArtifact、Evidence Panel 或可点击 URL；
- Tool Result 中实际存在 URL 证据，但 Source projection 只显示消息摘要，没有 URL 字段，也
  没有 claim → evidence 关系。

最小行为缺口不是“放宽引用校验”，而是：

1. 模型不应被迫复制完整 structured value 才能选择一个已知来源；
2. Finalizer 必须用具体字段路径报告严格校验失败；
3. validated Artifact 的 Evidence 必须由 CLI 直接投影到答案层；
4. live stream 必须区分公开过程摘要、provisional answer 和已提交答案。

## 2. 责任边界与预期改动文件

### 结构化引用与诊断

- `src/trivae/query/evidence.py`
  - 为 `ToolStructuredItem` 生成稳定 source identity；
  - 支持模型只提交 source identity + locator 的 structured candidate；
  - Finalizer 从 current-run record hydrate exact value；若模型同时提交 value，仍严格比较；
  - 为 source 校验传入 `evidence_items[i].sources[j].source` 路径；
  - 从可信 Message projection 提取 bounded URLs。
- `src/trivae/query/runtime/prompt.py`
  - 让模型引用短 source identity，不复制大型 structured value；
  - 资源/仓库问题要求具体 URL、观察事实与解释分离；
  - 保留“只使用 current-run provenance”的严格要求。
- `src/trivae/conversation/serialization.py`
  - 编解码 Message snapshot URL；旧 Artifact 缺失 URL 时按空 tuple 读取；
  - 编解码可选 structured source identity，旧 Artifact 继续可读。

### 实时过程与答案展示

- `src/trivae/query/streaming.py`
  - 保留 reasoning event 的 provider-neutral 顺序消费契约；
  - 不把任何 reasoning 文本交给 CLI 作为用户内容。
- `src/trivae/interfaces/cli_renderer.py`
  - 不渲染任何 provider reasoning 文本；
  - 通过真实 Route/Plan/Tool/Retrieval 行和最终 Evidence block 提供可审计过程；
  - 保持 hidden CoT 和 raw provider payload 不可见。
- `src/trivae/interfaces/cli.py`
  - 在成功 Answer 后输出 claim → evidence → source 的 Evidence block；
  - 输出 trusted URL、structured value 和 limitations；
  - 增加 citation/finalization 失败的友好投影，不改变错误归属。

### Regression 与文档

- `tests/test_evidence.py`：identity-only structured source、错误路径、显式值严格比较、URL 提取。
- `tests/test_cli_renderer.py`：公开摘要显示、未标记 thinking 不显示。
- `tests/test_cli.py`：Evidence/URL 投影和 provisional failure 行为。
- `tests/test_conversation.py`：URL round-trip 与旧 payload compatibility。
- 本任务的 `research/failure-case.md`：保存真实 Trace 的脱敏诊断事实，不保存完整聊天正文。

明确不做：

- 不公开 hidden chain of thought；
- 不新增 Evidence Tool、第二套 Runtime、citation repair、retry、fallback 或 query-specific
  仓库规则；
- 不让 CLI 直接读 SQLite、重新检索或从模型正文猜 URL；
- 不把“群聊提及”自动升级为“资源价值已验证”；
- 不修改 Data Access Scope、Retrieval ranking 或 Answer Artifact 的 claim-level 语义。

## 3. 数据流

```text
Tool Result
  ├─ message provenance → trusted canonical MessageSnapshot + URLs
  └─ structured provenance → source_id + locator + value
                         ↓
Model Answer Candidate
  ├─ message source locator
  └─ structured source_id/locator（可选旧式 value_snapshot）
                         ↓
Strict Finalizer
  ├─ source identity / locator / scope validation
  ├─ exact value hydration
  └─ concrete artifact path on failure
                         ↓
Validated AnswerArtifact
  ├─ answer content
  ├─ claim bindings
  ├─ evidence criterion/status/limitations
  └─ trusted source metadata/URLs
                         ↓
CLI projection
  ├─ live route/plan/tool/retrieval facts
  ├─ answer
  ├─ Evidence block
  └─ Sources / URL / /source drill-down
```

`source_id` 只是当前 Tool Result 内的确定性 locator alias，不是新的事实来源。Finalizer 仍以
`run_id/tool_call_id/tool_result_id/locator_kind/locator` 定位真实 item，并把 Tool Result 的
value 写入最终 Artifact；模型提交错误 source_id、错误 locator 或显式错误 value 都失败。

## 4. 关键取舍

### 结构化值：identity-first，value strict when supplied

完整 SQL row 或成员 candidate 可能包含多个字段。要求模型原样复制会把格式复制错误误判为证据
不存在，也会消耗 final synthesis 输出预算。允许模型只引用当前 Tool Result 的 source identity
和 locator，可以减少复制边界；但不放宽 locator、run、tool result、scope 校验，且显式提供的
value 仍逐值严格比较。

### URL：由 trusted snapshot 提取

模型可以在回答里提到 URL，但最终 Sources 不能依赖模型再次抄写 URL。URL 从已通过 scope 和
current-run 校验的消息正文或 structured value 中提取，并以 bounded tuple 保存；因此用户可以
定位资源，而不会把模型臆造的链接当成来源。

### 过程：真实执行事实而不是 provider reasoning

Runtime adapter 可以保留 provider-neutral reasoning event 以维持生命周期和顺序，但 CLI 永远不
渲染 reasoning 文本。真实 smoke 已证明 provider 把长内部推理放在 `reasoning_summary_text` 字段
中，因此字段名不能作为可见性证明。Tool/Plan/Route/Retrieval/Evidence 继续按真实 normalized
facts 展示，不能由 Renderer 拼造“我正在思考……”的假过程。

### 失败后的流式正文

Runtime 的正文 parser 仍消费 delta 以验证 JSON lexical contract，但 QueryStreamAdapter 会暂存
当前 model turn 的正文：如果该 turn 发起了 Tool，说明文字在 `turn_completed` 时丢弃；只有无 Tool
的最终 turn 才投影为 `answer.delta`。只有 `answer.finalization.completed` 后才显示 Evidence 和
正式成功结果；失败时不显示未提交的中间答案并显示 owner error，QueryResult 仍没有正式答案或
feedback target。这样不会把模型的工具前说明或 provisional 文本当成 Conversation 事实。

### 结果上限：有界但不再默认为 20

用户的真实复现显示，`total_hits=31` 但默认 `limit=20`，导致检索结果只带回 20 条。这个默认值在
多个边界分别存在：`ExecutionScope.max_results`、`SearchMessagesInput.limit`、`LexicalQuery.limit`、
Provider Function Tool schema，以及 Tool Result Evidence transport。只修改其中一层会造成 schema、
scope 或 evidence 容量不一致，因此统一抽出 `DEFAULT_RESULT_LIMIT=100`，并让这些边界共用它。

不移除上限：当前数据库包含数十万条消息，无界读取会把上下文、模型输入、输出和 Evidence transport
同时变成不可预测的成本。100 足以覆盖本次 31 条命中，也仍然让显式 partial/truncated 状态可审计。
宽范围资源清单额外使用 `context_before=0/context_after=0`，避免邻近消息占用同一个结果预算；需要解释
单个命中时才打开局部上下文。

最终 JSON 也采用证据优先预算：宽范围资源问题按一个 grouped claim/evidence/binding 汇总，列代表性
链接并报告剩余数量，必须保留 `evidence_items`、`citation_bindings` 和闭合 JSON，不能用穷举链接挤掉
可验证来源。

## 5. 可观测性

- `FinalizationErrorInfo.path` 进入 `citation.validation.failed`、`answer.finalization.failed`；
- Trace 的 `query.failed` 继续传播原始 `CITATION` owner error，不改成泛化 Query error；
- Normal/Debug capture 仍不保存 hidden CoT；最终答案和 Evidence 只有 validated boundary 后才可
  作为业务事实；
- Evidence/URL 是 AnswerArtifact 的纯 projection，不重新读取数据库，不创建第二条查询链。
