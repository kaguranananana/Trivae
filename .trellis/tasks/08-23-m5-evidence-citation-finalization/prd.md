# PRD: M5 Evidence / Citation + Answer Finalization

## Goal

在不改变 M4 Router、Planner、单一 Agent Runtime、Tool budget、cancellation 和 lifecycle 语义的前提下，完成一条可验证的：

```text
current-run Tool Result
    → Evidence / Answer contract
    → deterministic Citation validation
    → trusted Message / Structured Source hydration
    → Validated Answer Artifact
```

最终 Query result 不再只能表达裸回答字符串；它必须能够表达回答内容、claim-level citation binding、按 finding 组织的 Evidence、来源限制和 Answer-level limitations。

## Confirmed constraints

- Stage 1.8 ADR 与 ChatLab `f9b87c00ee886997c3f82d35dbcec9b1aa5e1264` 研究是冻结基线，不重新设计 Evidence 语义。
- Retrieval Candidate 不等于 Final Evidence；不增加 `retrieve_evidence`、Evidence Agent、Judge、Workflow 或第二套 Agent Loop。
- Source relation 只使用 `supports`、`contradicts`、`context`；Evidence sufficiency 只使用 `sufficient`、`partial`、`insufficient`。
- Tool/execution completeness 与 Evidence sufficiency 分开表达。
- Message Source 必须同时有 current-run provenance、`session_id + internal_message_id` locator 和 trusted display snapshot。
- Structured Result Source 不伪装成 Message Source；必须定位到当前 Tool Result 的真实 locator/value。
- invalid citation 显式 Finalization Failure；不静默删除、自动换来源、自动 retry 或 fallback。
- SDK raw item、provider payload、ExecutionScope 对象不进入 Answer Artifact。

## Scope

### In scope

1. Trivae-owned Evidence、Citation Binding、Message Source、Structured Source、Answer Artifact contract。
2. Runtime Tool Result 的最小 current-run provenance extension：run/tool-call/tool-result/result-item identity，以及 bounded safe result projection。
3. Citation Validator / Finalizer：结构、ID、provenance、scope、locator、trusted metadata hydration 和 bounded contract 校验。
4. QueryOrchestrator/Application 接线：只有 Runtime completed 且 finalization 成功时才暴露 Validated Answer Artifact。
5. Agent final synthesis 的结构化 JSON contract 与 deterministic tests。
6. 必要的 retrieval projection 扩展，使 session display 能从可信 Canonical Store hydrate。
7. Trellis validation、backend guideline、architecture status、Failure Case 与 interview evidence 记录。

### Explicitly out of scope

- SQLite Conversation / Assistant Message durable schema；本任务实现 validated commit boundary，并把 durable Conversation Store 作为 M5b pending，不把当前结果宣传成完整持久化 vertical slice。
- Semantic entailment Judge、LLM-as-Judge、Evaluation runner、threshold/calibration。
- M6 Trace Store/backend、retention、debug profile implementation。
- Semantic/vector/hybrid retrieval、embedding、reranker、fusion。
- HTTP/FastAPI/SSE、Web UI、Evidence Panel 和社交平台 deep-link product integration。
- Automatic citation repair/retry、model retry、fallback、model fallback。

## Acceptance criteria

- [x] Answer Artifact 包含 answer content、claim citation bindings、Evidence Items 和 limitations。
- [x] Evidence Item 按 finding/criterion 组织，并支持多 Source、三种 relation、三种 sufficiency。
- [x] Message Source 能从 current-run Tool Result 定位到 session/message，并由可信侧 hydrate author、timestamp、session display、safe excerpt。
- [x] Structured Source 有独立 locator/value/scope snapshot contract，并能拒绝 fabricated locator/value。
- [x] fabricated run/tool-call/tool-result/result-item/message/structured locator 会产生稳定 Finalization Failure。
- [x] duplicate evidence ID、dangling citation、invalid relation/sufficiency、oversized fields 被显式拒绝。
- [x] invalid citation 不会变成无引用成功回答，也不会自动替换来源。
- [x] M4 runtime failure、max_turns_exceeded、aborted 不进入 successful finalization；tool budget/finalizing 语义保持不变。
- [x] deterministic tests 覆盖 contract、provenance、message/structured source、finalizer、runtime/application integration。
- [x] 默认质量门禁和 Trellis validation 有真实结果；DeepSeek smoke 已 opt-in 执行，结构化输出失败已显式记录。

## Current M4 reusable contracts

- `QueryRequest → Router → optional Planner → shared AgentRuntime`。
- `ExecutionScope` 在 local RuntimeContext/Capability path 硬执行，不进入模型 prompt。
- `ToolEnvelope` 的 `ok/partial/error`、retrieval `coverage/truncated` 和 typed contract errors。
- `RuntimeToolCall`、`RuntimeEvent`、`RuntimeResult`、tool-round budget、finalizing、abort、max-turns 和 secret-safe error projection。
- `MessageProjection`、`RetrievalResult`、`StructuredMessageResult`、`StructuredAggregateResult` 与 Canonical Store read adapter。

## Design evidence expected

任务验证文档必须区分 measured fact、regression test case 和 anticipated risk，并记录：问题、根因、候选方案、取舍、Failure Attribution、验证结果、为什么不引入更复杂能力、以及 M5b/M6/M7 的 reconsideration trigger。
