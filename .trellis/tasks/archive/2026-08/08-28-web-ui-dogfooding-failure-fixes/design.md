# Design: real Web dogfooding and evidence-driven fixes

## 1. 设计目标

本任务先建立可复现的真实 Failure，再决定是否改代码。目标是修复用户从 Web 页面观察到的主链路缺陷，而不是用一次性的测试脚本、fixture 或 UI 文案掩盖后端事实。

## 2. 现有单一执行链

```text
浏览器
  -> Web API /api/query/stream
  -> ScopeRequest 编译为 trusted ExecutionScope
  -> TrivaeApplication.query
  -> Router / Planner / Agent Runtime / Tools / Retrieval
  -> QueryStreamEvent
  -> NDJSON stream
  -> chat store 的 request_id owner buffer
  -> Process / Answer / Sources / Trace UI
```

- Web route 只负责 HTTP、DTO 验证和 NDJSON，不复制 Query 或 Retrieval。
- `stream.started` 和 `stream.end` 是 Web 信封；中间事件仍使用统一 `QueryStreamEvent`。
- `stream.end` 的 status、trace、sources、limitations 是确定性终态；前端不从模型文本猜来源。
- Conversation scope 是 immutable contract；selector 变化只能影响新草稿，不能改写已有 Conversation。
- Trace 只作为可审计事实和本次运行的 provenance，不承担“让答案看起来成功”的职责。

## 3. 探索与归因策略

每次真实查询在浏览器端同时观察四层事实：

1. UI：当前 Conversation、Scope、过程块、回答、Sources、限制、终态。
2. HTTP：status、`X-Request-Id`、stream 是否正常结束、query stop 的响应。
3. NDJSON：事件类型/序号/owner 关联、`partial`/`truncated`/`coverage`、error 和 `stream.end`。
4. Trace/Conversation：最终 artifact、trace status、scope snapshot、持久化消息与 UI 是否一致。

只有这四层中的事实能相互对应时才判定为产品 Failure。若 Provider 本身返回显式失败，则记录为环境/Provider Failure，除非 Web 错误投影或生命周期又产生了额外产品错误。

### 根因分类

- `browser-ui`：DOM 交互、键盘/IME、渲染、折叠、滚动、复制或按钮状态。
- `web-contract`：DTO、scope、NDJSON parser/encoder、HTTP status 或终态映射。
- `stream-lifecycle`：request owner、Stop、断连、切换、刷新、后台流归属。
- `application-projection`：Conversation、Answer Artifact、Sources、Trace 或 process projection 不一致。
- `retrieval-data`：真实 canonical/derived index 的可证明召回、排序、coverage 或 bounded transport 问题。
- `provider-environment`：当前 Provider、模型、网络或配置本身失败；不通过前端特殊分支掩盖。

## 4. 可能的修复边界

当前已知的高风险边界只作为检查点，不预设它们一定是 Failure：

- 前端流式事件结束顺序与 `stream.end` 权威终态是否会丢失最终 trace/error。
- Conversation scope 变化、draft rename 与后台 stream owner 是否串线。
- Tool 结构化结果的 `total_items`、transport truncation、partial/coverage 是否被 UI 正确显示。
- no-result 的 complete proof 是否在回答和工具过程里保持一致。
- Sources 上下文 drill-down、Trace path/reveal 是否正确处理真实 unavailable/错误状态。
- 刷新、切换和 Stop 时是否把运行中状态误报为成功或静默失败。

只有浏览器和 Trace 证据命中某一边界，才在相应最小文件中修复；不提前引入新缓存、重试、fallback、分页或兼容层。

## 5. 测试设计

- 前端 store/组件契约：锁定实际事件序列、scope 变化、owner buffer、终态和 UI 可见状态。
- Python Web/Application 契约：锁定 HTTP status、NDJSON 事件、Stop、Conversation/Trace provenance。
- 若根因位于 Retrieval/Runtime：补到对应已有测试层，确保真实 scope、coverage、partial 和 finalization 不被 Web 适配层改变。
- 真实浏览器复测使用当前同一 server、数据库、Provider 和浏览器入口；不以 fake 测试替代最终证据。

## 6. 错误与日志原则

- 错误显式暴露并保留 `request_id`/`trace_id`/error code 等 bounded 诊断。
- 任务文档只记录元数据和少量必要片段，不提交完整真实聊天记录、Provider secret 或 `.env`。
- 不在新代码中添加无证据的 catch-and-ignore；现有静默 catch 只有在真实 Failure 证明它阻碍用户定位时才处理。

## 7. 回滚边界

每个修复保持单一可回滚变更，先补回归测试再改实现；真实查询生成的 Conversation/Trace 数据不作为代码回滚依据。若一次修改同时改变多层契约，先拆分或停止并重新确认设计，不扩大范围。

## 8. Answer Quality / Depth Failure Case

### 8.1 目标分离

本 Case 将两个目标分开审计：

```text
Evidence Artifact / Tool Result
  bounded、可审计、可引用、保留 partial/truncated/coverage

Answer Content
  由问题复杂度决定表达深度，覆盖证据支持的独立 finding、代表性细节和必要限制

Citation Binding
  将 Answer Content 与当前 run 的 Evidence Item 绑定
```

当前实现中 `ModelAnswerClaim.text` 同时作为用户可见正文，Host 又从同一 claim 生成 Evidence Item 和 Citation Binding。这个耦合已经在代码结构上确认，但在真实 Failure 发生前不预先重构；先确认压缩指令是否让模型把正文也当作 bookkeeping 字段处理。

### 8.2 真实复现与对照

七类复杂问题按真实证据量选择 Case。每个 Case 从 Web UI 取得 Trace ID，再沿以下链路核对同一事实：

```text
retriever result
  -> canonical Tool Result
  -> model-visible projection
  -> final synthesis context
  -> provider JSON candidate
  -> Host compile/finalize
  -> answer.completed
  -> Web DOM
```

ChatLab 配对运行使用同一问题、同一数据范围和尽可能相同的证据任务。比较主题、参与者、代表观点、上下文、资源/URL、时间关系、限制和来源覆盖；不把更长本身当作更好。

### 8.3 根因决策顺序

1. 先看 canonical retrieval 是否已经缺少独立 finding，排除或确认 A。
2. 再看 projection metrics 和最终回合上下文，确认 B 是否省略相关 hit/context。
3. 若 evidence 仍充分，再检查 Prompt 的 compact/grouped/concise 指令是否与模型 candidate 的合并行为一致，验证 C。
4. 检查 `claim.text -> AnswerContentBlock.text` 是否在 contract 或 claim 数/字段上限处限制正文，验证 D。
5. 对比 provider raw candidate、finalizer artifact、`answer.completed` 和 DOM，分别排除 E、F。
6. 最后用 provider finish reason、completion usage 和同条件重复观察区分 G。

只有命中证据的层才修改；不因为短答案单独提高 max tokens、降低 temperature 或添加通用 verbose 分支。

### 8.4 修复候选的约束

- 保留 Tool Result 和 Evidence metadata 的 bounded 上限及公开 truncation metrics。
- 若证实 C/D，优先将“证据选择/引用数量受限”与“用户可见 prose 需充分解释”分离；是否增加独立 answer prose 字段，须由实际 candidate/finalizer 证据决定。
- 允许一个内容块绑定多个 Evidence Item，或允许多个内容块共享同一证据，仅在现有 contract 证明必要时调整；不得通过复制 source 或放宽 scope/provenance 来换长度。
- 回归锁定语义覆盖：多主题、多方比较、资源 URL、讨论时间线、partial limitation、current-run citation 和简单事实问题的自然简洁性。
