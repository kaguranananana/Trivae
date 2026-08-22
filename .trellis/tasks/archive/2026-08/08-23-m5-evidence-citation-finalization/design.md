# Design: M5 Evidence / Citation + Answer Finalization

## Boundary and data flow

```text
Agent Runtime tool adapter
    → RuntimeToolCall + ToolResultRecord (Trivae-owned, bounded)
    → RuntimeResult
    → QueryOrchestrator final synthesis parser
    → AnswerArtifact candidate
    → CitationValidator / trusted hydration
    → QueryResult.answer_artifact
```

Runtime 继续只驱动 SDK Agent Loop；它不选择 Evidence、不判断 claim 语义、不增加 Evidence State Machine。`query/evidence.py` 拥有 Evidence/Answer contract 和 finalizer，`retrieval` 只提供可信 canonical projection，Application 只负责装配与提交边界。

## Contract shape

### Answer Artifact

- `AnswerContentBlock(block_id, text)` 是结构化回答内容。
- `CitationBinding(content_block_id, evidence_ids)` 表达 claim/content block 到 Evidence Item 的绑定。
- `EvidenceItem(evidence_id, finding, criterion, sufficiency, sources, limitations)` 围绕 finding，而非单条消息组织。
- `AnswerArtifact(content_blocks, citation_bindings, evidence_items, limitations)` 是 Query 层最终产品 contract。
- Renderer 可将 binding 显示为 `[1]`，但 ID 只使用 stable `evidence_id`。

### Source references

`MessageSource` 保存 `run_id/tool_call_id/tool_result_id/result_item_id/session_id/internal_message_id`；最终输出另外带上 trusted `MessageDisplaySnapshot`。模型不能提供有效 snapshot。

`StructuredSource` 保存 `run_id/tool_call_id/tool_result_id/locator_kind/locator/value_snapshot`；finalizer 从对应 ToolResultRecord 重建 value、scope snapshot 和 execution limitations。

`ToolResultRecord` 只保存 bounded `MessageProjection` / structured value snapshot、tool identities、query scope snapshot、execution limitations；不保存 SDK raw object、SQLite connection 或 raw database dump。

## Provenance design

1. 每次 Runtime 生成一个 run-local `run_id`。
2. 每个已完成 Tool call 分配 Trivae-owned `tool_call_id` 和 `tool_result_id`；provider call ID 只用于 adapter 内部匹配，不进入公共 contract。
3. `search_messages` 结果按 bounded message projection 建立 `result_item_id`，并把这些 ID 作为 Tool Result 的安全 provenance projection 返回给模型。
4. Known Tool error 也建立没有 source items 的 ToolResultRecord；unknown exception 只形成 failed RuntimeToolCall，不伪装成 Tool Result。
5. `RuntimeResult` 携带当前 run 的 `tool_results`，Orchestrator 只把同一个结果交给 Finalizer；prior context、旧 Assistant Message 和外部结果没有进入 current-run index 的路径。

## Finalization rules

- JSON structured final synthesis 解析为候选 Artifact；没有 Tool execution 时普通纯文本仅表示没有 citation 的回答内容；发生 Tool execution 后裸文本显式失败，避免把 citation contract 丢掉。
- `evidence_id`、content block、binding、relation、sufficiency 和字段 bounds 在 contract 层验证。
- Finalizer 建立当前 Run 的 `tool_result_id`/`result_item_id` 索引，并逐个验证 source identity、scope 和 locator。
- Message source 必须在结果 record 中找到完全一致的 session/message；随后从 trusted `MessageProjection` hydrate snapshot。
- Structured source 必须找到完全一致 locator，并比较 model value 与 trusted result value；scope/value/limitations 使用 record 侧数据覆盖模型元数据。
- Finalizer 不判断自然语言 entailment，也不对 retrieval recall 作结论。
- 任一 citation/source 失败都返回 `FinalizationErrorInfo`；不删除 binding、不替换来源、不提交成功 Artifact。

## Commit boundary

M5 实现 Application/Orchestrator 的 validated commit boundary：`QueryResult.answer_artifact` 只有 finalizer 成功后才非空；runtime failed/max-turn/aborted 或 finalization failed 均没有 successful Artifact。SQLite Conversation/Assistant Message durable store 尚未有冻结 schema，留给 M5b；当前不伪造“已持久化”。

## Bounds baseline

第一版使用显式 conservative bounds，并在 validation 中标为 calibration pending：content block 40、Evidence 20、source 20、binding 40、limitation 20；文本字段 4,000 字符，safe excerpt 1,000 字符，answer content 总长度 20,000 字符。超限的模型 contract 显式失败；trusted message excerpt 以带 `truncated` 标记的 bounded snapshot 保存。

## Why not

- 不把 provenance 放在 Retrieval 中：Retrieval 不知道当前 Agent Run，也不拥有最终 Evidence。
- 不新增 `retrieve_evidence`：Stage 1.8 已冻结 Evidence Selection 属于 final synthesis。
- 不使用固定关键词/time grouping：无法表达技术情报的采用、反对、回滚和状态变化。
- 不用结构 Validator 证明语义 entailment：能力边界属于 M7 Evaluation。
- 不实现 Conversation SQLite schema：当前 ADR 尚未冻结 persistence schema；先完成可验证 finalization boundary，M5b 以真实 persistence 需求继续。
