# PRD: Stage 1.8 Evidence / Citation 架构决策

> 本任务只沉淀 Evidence / Citation 架构，不实现业务代码，也不提前冻结 Stage 1.9 Trace 或 Stage 1.10 Evaluation 的具体 Schema、指标与参数。

## Goal

确定 Trivae 第一版 Evidence / Citation 的职责边界、数据流、核心语义与用户可见引用方式，使所有基于聊天记录或结构化查询形成的结论都能够追溯到当前 Run 实际取得的 Tool Result，并进一步定位 Canonical Message、结构化结果与原始聊天来源。

用户价值是：LLM 给出总结时直接展示引用；用户认为总结不充分或不准确时，可以看到确定的会话、作者和精确来源时间，打开有限原始上下文复核，或回到原社交平台查看完整聊天。

## Background / Confirmed Constraints

- Stage 1.2 已确认 Canonical Message Store 是聊天事实源；Message 同时区分 Trivae internal ID 与 platform/source message ID，Evidence 沿 `Evidence → Message → source message id → 原始聊天` 追溯。
- Stage 1.3 已确认 Retrieval 只返回 Candidate Data；Evidence Selection / Organization 不属于 Retrieval，Evidence 判断必须使用 question-specific criteria。
- Stage 1.4 已确认第一版只有 6 个 Agent-facing Tool，不提供 `retrieve_evidence`；Message Search 返回稳定 `message_id`，Tool Envelope 显式区分 `ok / partial / error` 与 `truncated`。
- Stage 1.6 的 `evidence_needed` 只是调查需求，不是 Evidence Object。
- Stage 1.7 已确认 Thin Agent Runtime、Conversation Store 作为 AI 历史事实源和结构化 Tool Call / Tool Result 回放；不引入 Runtime-owned Evidence State Machine。
- ChatLab baseline 为 commit `f9b87c00ee886997c3f82d35dbcec9b1aa5e1264`。继承与偏离证据见 `research/chatlab-evidence-citation-analysis.md`。

## Requirements

1. 明确 Evidence Source、Evidence Item、Citation 与 Answer Claim 的概念边界及最小契约。
2. 数据流固定为 `Retrieval / Structured Result → Evidence Selection / Organization → Final Evidence → Citation-bound Answer`；Answer 不得绕过 Final Evidence 直接把候选文本当已验证事实。
3. Final Evidence 按 claim / finding 组织；一个 Evidence Item 可以包含一条或多条 Source，以表达多消息共同支撑、反驳或补充同一结论。
4. 最终 Answer 对所有来自聊天记录、统计或数据库概览的实质性事实与推断展示 claim-level Citation；一般性解释、交互性文字或不依赖聊天数据的内容不强制引用。
5. 正文 Citation 与可展开 Evidence Panel 共用同一份结构化 Evidence；显示用 `[1]` 等编号不是 source identity。
6. Citation 只能引用当前 Run 中实际可见且通过 Data Access Scope 的 Tool Result；禁止引用模型自造 ID、旧 AI 回复或压缩摘要中的“事实”。
7. Citation 必须同时覆盖 Message Source 与 Structured Result Source；不能强迫聚合结果伪装成单条消息。
8. Message Source 使用显式 `session_id + internal message_id` 作为应用内定位锚点，并保留取得该来源的 Tool Call / Result provenance；应用可继续解析 platform/source message ID。
9. Message Source 必须持久化面向人工复核的生成时快照：ChatSession 可读标识、作者、精确 Canonical Timestamp（含明确 timezone / offset 语义）与未经 LLM 改写的安全 excerpt。
10. Semantic Chunk 只承担 Retrieval provenance；最终 Citation 必须解析到 Canonical Message 或明确 Message Range，不能把 embedding chunk 或纯文本 snippet 当原始事实源。
11. Structured Result Source 通过当前 Run 的 Tool Result identity 与结果位置定位，并持久化引用值、查询范围等最小快照；具体 row / value locator 序列化留给实现设计。
12. Question-specific criterion 与 Evidence Item 一同持久化；不得使用固定词表跨问题决定 `included / excluded / uncertain`。
13. Source 相对 finding 的关系表达为 `supports / contradicts / context`；Evidence Item 的证据充足度表达为 `sufficient / partial / insufficient`，不引入无校准依据的数值 confidence。
14. Tool 的 `partial / coverage / truncated / unavailable` 属于 Retrieval / execution completeness，必须作为 limitations 保留；它与 Evidence sufficiency 是两个独立维度。
15. Citation Validator 确定性检查引用 ID、当前 Run provenance、Source 可解析性、Session / Message 一致性、Structured Result locator 与 Data Access Scope；它不声称能够证明自然语言 claim 与 Evidence 的语义一致。
16. invalid / unresolved Citation 不得被静默删除或降级成无引用回答；第一版显式使 Answer Finalization 失败，不增加未经 Evaluation 证明必要的自动修复 / retry。
17. Evidence / Citation 随最终 Assistant Message 持久化，只有通过验证的 Answer Artifact 才能按 Stage 1.7 的完成边界提交；历史 Evidence 可查看，但后续事实问题必须重新通过当前数据库 Tool 获取证据。
18. Citation excerpt 只是回答侧预览，不替代原始聊天。用户可从 Citation 打开以被引消息为锚点的 bounded surrounding context，查看未经 LLM 改写的 Canonical Message；全量上下文由用户回到原社交平台查看。
19. Source 支持平台 deep link / native locator 时可提供直接入口；不支持时仍展示足够的会话、作者、精确时间等人工定位信息，deep link 可用性不影响 Citation 是否成立。
20. 第一版不新增 Agent-facing Evidence Tool、Evidence Agent、Workflow Engine、固定关键词 Judge、固定时间聚类或 Runtime-owned Evidence State Machine。
21. Evidence-aware stopping 第一版只作为 Agent 的完成指导：证据充分时可自然结束调查；Tool Budget 耗尽时基于已取得 Evidence final synthesis 并显式标记 partial / insufficient。machine-enforced completion gate 与参数留给 Stage 1.10 Evaluation。

## In Scope

- Evidence / Citation 领域边界、数据流与 conceptual contract
- Message Source 与 Structured Result Source
- claim-level Citation、Evidence Panel 与 bounded original-context viewer
- question-specific criteria、source relation、evidence sufficiency 与 execution completeness
- Citation validation、failure、persistence 与 replay 边界
- Evidence-aware stopping 的第一版职责边界
- ChatLab 继承项、偏离项及理由
- 同步 Stage 1.8 ADR、Architecture、Technical Decisions 与项目阶段状态

## Out of Scope

- 业务代码、数据库表、Python 类型、JSON 序列化或 API endpoint
- Stage 1.9 Runtime Event / Trace Schema、指标名、存储和采集实现
- Stage 1.10 Evaluation Set、阈值、自动停止参数与语义 Judge 校准
- 前端视觉稿、具体组件或 bounded context 的消息数量
- Reranker、Fusion、Embedding、Chunk 参数或其他 Retrieval 选型
- Canonical Message edit / delete / mutation 的完整历史版本策略
- 原社交平台不支持时人为构造 deep link

## Acceptance Criteria

- [x] 新增 Stage 1.8 ADR，逐项记录 Context / Decision / Reason / Trade-off / Failure Case / Reopen Condition。
- [x] ADR 明确 `Retrieval / Structured Result → Evidence Selection / Organization → Final Evidence → Citation-bound Answer` 的数据流和 ownership。
- [x] Final Evidence 按 claim / finding 组织并允许多个 Source；Message 与 Structured Result 使用不同 Source Reference 语义。
- [x] 正文 claim-level Citation 与 Evidence Panel 共用同一结构，不把显示编号、Chunk 或 snippet 当 source identity。
- [x] Message Citation 展示可人工识别的 ChatSession、作者和精确来源时间，并可进入 bounded original-context viewer；全量聊天留在原社交平台。
- [x] 明确 criterion、`supports / contradicts / context`、`sufficient / partial / insufficient` 及 Tool completeness limitations 的独立语义。
- [x] 明确 Citation Validator 能验证与不能验证的范围；invalid / unresolved Citation 显式导致 Answer Finalization 失败且不静默删除。
- [x] 明确 Evidence / Citation 的 Assistant Message 持久化与 replay 边界，不把旧 AI 历史或摘要当当前聊天事实证据。
- [x] 明确第一版不新增 `retrieve_evidence` Tool、固定关键词 Judge、Evidence Agent、自动 citation repair 或 Runtime-owned Evidence State Machine。
- [x] ChatLab 的继承与偏离逐项有代码证据；不机械复制其固定词表、时间聚类、retrieval status 或隐式单 Session 假设。
- [x] `architecture.md`、`technical-decisions.md`、`overview.md`、`workflow.md` 与 Stage 1.8 ADR 的状态、术语和 Pending 列表一致。
- [x] `task.py validate`、文档链接 / 术语检查与 Trellis 一致性检查通过。

## Risks / Deferred Items

- LLM 对 Evidence 与 claim 的语义匹配仍可能错误；Stage 1.8 只保证结构可追溯，语义质量由 Prompt 与 Stage 1.10 Evaluation 验证。
- Structured Result 的 locator 需要与未来 Tool Result Schema 联动；Stage 1.8 冻结语义，不冻结 JSON Pointer 或数据库字段。
- Message 后续编辑、撤回或删除时，生成时 snapshot 与当前 Canonical Message 的关系留给 Data Schema / mutation semantics 决定；不得因此阻塞第一版来源快照与定位。
- bounded context 数量、Citation 密度、自动修复 / retry、Evidence-aware stopping 阈值均需真实 workload 校准。
