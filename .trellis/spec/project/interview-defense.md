# Interview Defense Evidence

> 这是 Trivae 所有实现任务的长期质量门槛。目标是形成事实索引，不是编写背诵式面试答案。

## 适用范围

每个实现任务完成时适用，尤其适用于 Retrieval、Tool、Agent Runtime、Context、Evidence、Evaluation、Storage、Application Boundary 等关键模块。纯问答、纯状态查询或不产生实现结果的工作不需要强行创建本记录。

## 记录原则

只记录能够由以下来源证明的内容：

- architecture decision；
- implementation；
- test / regression test；
- 真实数据运行；
- benchmark / evaluation；
- 真实 Failure Case 的复现与定位。

禁止为了面试制造不存在的复杂度、虚构 Failure Case、虚构性能数字或包装不存在的设计过程。没有证据的内容必须明确标为未知、`anticipated risk`、`engineering expectation` 或 `waiting for evaluation evidence`。

## 面试回答的来源边界

Interview Defense Notes 的默认回答应从 Trivae 自己的 Problem、Constraint、Design Decision、Implementation、Test、真实数据运行和 Failure Case 出发：

- 不把 ChatLab、参考实现或“参考某个成熟开源项目”作为设计理由、技术结论或答案主线；
- 不在没有必要时主动引出 ChatLab 或外部参考来源；
- 不把外部项目的存在当作“为什么当前实现正确”的证据，当前项目的测试、测量和真实 Failure Case 才是证据；
- 内部架构文档可以保留真实的参考来源，不为了面试表达而篡改项目历史；
- 如果面试官直接询问参考来源，必须如实说明，再把重点转回 Trivae 的边界适配、取舍、实现和验证，不能声称不存在外部参考。

因此，回答“为什么这样设计”时优先使用：

```text
Trivae 的具体问题 / 约束
→ 考虑过的方案
→ 当前选择与 trade-off
→ 代码 / 测试 / benchmark / Failure Case 证据
```

## 必须覆盖的内容

实现/验证/评审记录至少包含以下章节。可以放在任务目录的 `validation.md`，也可以放在项目已有的 implementation / review 文档中，但必须能回指具体证据位置。

### 1. Problem / Motivation

- 解决的具体问题是什么；
- 没有该模块时会出现什么 Failure Case；
- 为什么问题归属当前层，而不是其他层。

### 2. Design Rationale

对重要设计记录：

```text
problem
→ considered options
→ selected option
→ reason
→ trade-off
```

只写真实存在或被正式架构 / 实现证据支持的 alternatives。

### 3. Why not

对容易被追问的未采用方案，明确标记：

- `permanently rejected`；或
- `currently unnecessary / waiting for evaluation evidence`。

第二类必须记录未来的 reconsideration trigger。等待证据不等于永久否定。

### 4. Failure Cases

每条记录明确分类：

- `real failure`：真实运行中发生并被复现的问题；
- `regression test case`：为契约或已知边界建立的回归保护；
- `anticipated risk`：尚未发生、但基于设计可解释的风险。

推荐字段：

```text
input / scenario
observed failure
root cause
how it was located
fix / current handling
validation
regression protection
```

### 5. Evaluation / Evidence

记录能支撑技术判断的真实证据，包括适用时的 dataset size、canonical count、query type、hit / returned count、latency、truncation、correctness observation 和对比结果。

必须区分：

- `measured fact`：实际运行测得或测试直接断言的结果；
- `engineering expectation`：尚未由当前项目运行证明的推测或扩展判断。

### 6. Observability / Debugging

至少说明：能看到什么信号、错误在哪一层分类、如何定位到具体输入 / batch / query / entity、如何区分 retrieval miss、filter error、truncation、data problem 或其他层错误。不要把尚未实现的 Trace / logging 写成现有能力。

### 7. Scale / Performance

记录当前真实规模、查询量级、实测瓶颈、代表性耗时，以及数据扩大后的工程预期。没有 benchmark 或真实数据证据时，不写成性能事实；没有真实 Failure Case 时，不以“可能慢”为理由擅自增加复杂索引或基础设施。

### 8. Boundary / Ownership

明确写出：

```text
what it owns
what it explicitly does not own
upstream
downstream
dependency direction
```

重点区分 Application、Interface Adapter、Storage、Derived Data、Retrieval、Tool、Agent Runtime、Router、Planner 等边界。

### 9. Evolution

对暂缓能力写出证据化演进路径：当前 baseline、触发 Failure Case 或 Evaluation、需要的 regression / paired evaluation、再决定是否引入新能力。没有触发证据时保持当前最小实现。

### 10. Interview Defense Notes

只建立问题到事实来源的映射，不生成标准答案：

```text
Q: 为什么这么设计？
Evidence: architecture / decision / code / test / benchmark / failure case
```

## 完成质量门禁

任务完成 review 时，连续追问以下问题必须能从仓库找到证据：

```text
为什么这么设计？
有哪些真实替代方案？
失败过吗，如何定位？
怎么证明改动有效？
规模上去后最先担心什么？
这个模块拥有和不拥有什么？
未来什么证据会让你重新评估？
```

如果答案只能是“代码就是这么写的”，记录不合格；如果必须虚构项目经历才能补齐，记录方式不合格。

## M5a Evidence / Citation 事实索引

M5a 的事实来源集中在归档的 [task PRD](../../tasks/archive/2026-08/08-23-m5-evidence-citation-finalization/prd.md)、[design](../../tasks/archive/2026-08/08-23-m5-evidence-citation-finalization/design.md)、[implementation](../../tasks/archive/2026-08/08-23-m5-evidence-citation-finalization/implement.md) 与 [validation](../../tasks/archive/2026-08/08-23-m5-evidence-citation-finalization/validation.md)：

- 为什么不能只返回 `[1]`：`QueryResult.answer_artifact` 保存 claim-level binding，`query/evidence.py` 再确定性解析 source identity；显示编号不承担 provenance。
- 为什么需要 current-run provenance：测试覆盖 fabricated run/tool/result/item ID、old run 和 scope violation；source 必须命中本轮 Tool Result，不能从 prior assistant context 借用。
- 为什么 Retrieval Candidate 不等于 Final Evidence：Retrieval 只提供 bounded candidate / structured result，Agent final synthesis 组织 question-specific finding，validator 只验证结构、locator、scope 和可信 hydration。
- 为什么不引入 Evidence Agent / Judge：Stage 1.8 ownership 与当前实现都把 semantic entailment 留给 M7 Evaluation；M5 没有第二套 Agent Loop。
- 为什么 invalid citation 不 silent fallback：finalizer 通过 `finalization_error` 阻止正式 `final_answer`，不会删 binding、换来源或 retry；对应 bad cases 在 `tests/test_evidence.py`。
- 当前限制：M5b 已完成第一版 Conversation / Assistant Message durable persistence；Trace backend 与 semantic vertical slice 已落地。Qwen 已完成真实 Snapshot baseline 与 LLM-assisted provisional paired evaluation，但 human-verified quality、corpus-exhaustive reference、chunk/ANN 长期 bounds calibration 仍待后续证据。

## Semantic Retrieval Vertical Slice 事实索引

- 为什么 primary unit 不是 message：高噪声群聊里“对”“哈哈”“这个可以”等消息缺少独立语义；当前实现以 Time-aware Parent + Small Child 建立向量候选，再由 canonical range 恢复消息。
- 为什么向量库必须独立：Embedding、chunker 或模型改变时只重建 derived sqlite-vec database；Canonical Store 仍是事实源，identity mismatch 直接报告 stale，不回退 lexical。
- 为什么 query instruction 不能加到 document：`SentenceTransformerEmbeddingProvider` 分离 `embed_documents()` 与 `embed_query()`，只有 query 进入 `Instruct: ...\nQuery: ...`；dimension、normalized、pooling、instruction 与 chunker config 都进入 readable index identity。
- 为什么 chunk 不能直接引用：semantic candidate 的 chunk/parent/range 只用于 acquisition provenance；`ToolResultRecord` 只保存恢复后的 canonical `MessageProjection`，Finalizer 的 `MessageSource` 指向 message identity。
- 如何区分失败：未构建/构建中/failed 是 unavailable，identity 或 canonical count 漂移是 stale，partial/truncated 是结果完整性状态；Semantic Tool 不把这些状态改写成 lexical success。
- 当前未宣称的事实：官方 `sentence-transformers` provider 已在本地对 473,236 条 canonical messages 完成 `Qwen/Qwen3-Embedding-0.6B`、1024-d normalized full rebuild，且 12-query/173-candidate report 已生成；这些 annotation 与 Recall/Precision/MRR/Top-k 数字全部是 `llm_assisted_provisional`，`ground_truth_claim=false`，不能推出 human ground truth、corpus Recall、质量提升或生产 SLA。下一步是人工抽查 audit queue，并在 verified labels 后重跑 metrics。

- Real-run failure evidence：Qwen3 的 bfloat16 Normalize 输出在 Python float projection 中观察到约 `1.002`–`1.003` 的范数；provider 在官方 encode 后做确定性 float normalization，再以严格阈值校验并写入 vec0。放宽 normalized 校验不是可接受修复；对应 regression 在 `tests/test_semantic_retrieval.py`。

## M5b Conversation persistence 事实索引

### Problem / Motivation

- M5a 已能产出 validated `AnswerArtifact`，但进程重启后没有 Trivae-owned 的 Conversation / Assistant Message durable source；如果直接依赖 SDK/provider session，历史也无法保证与 Trivae 的 current-run provenance 语义一致。
- M5b 的目标是把 validated Artifact 作为 completed Assistant Message 的结构化 snapshot 持久化，同时让历史上下文帮助 follow-up 理解指代，但不把旧 Evidence 冒充为新一轮事实。

### Design Rationale / Why not

- 选择独立 `conversation/` package 和独立 SQLite Store connection：保留 Canonical Message Store、Retrieval read repository 与 Conversation lifecycle 的 ownership，避免 Runtime / Tool / Finalizer 直接写 SQL。
- 选择显式 JSON codec + 两张 Conversation 表：Artifact 是可回放的业务快照，需要通过领域构造函数恢复；当前没有证据要求把 Evidence 的每个字段拆成另一套可查询事实模型，因此暂不引入 normalized Artifact tables 或 migration framework。
- 不采用 SDK/provider Session 作为 source of truth；Stage 1.7 已把 Trivae Conversation Store 定义为 canonical history。也不加入 retry、fallback 或 silent citation repair；失败必须停在 QueryResult / Store error 边界。

### Failure / Regression Evidence

- `regression test case`：注入 Assistant insert 失败，断言 User 与 Assistant 都不留存，证明 transaction rollback 覆盖整个 turn。
- `regression test case`：Finalizer failure、Runtime failure 与 incomplete runtime 不产生 completed Assistant row；成功提交只发生在 `QueryResult.is_successful` 且 Artifact 非空时。
- `regression test case`：使用旧 run 的 Evidence locator 配合新 run id 提交，Finalizer 返回 `INVALID_PROVENANCE`；历史 Artifact 可以 replay，但不能成为新 Runtime 的 ToolResult record。
- `environment setup observation`：原始 SQLite 文件包含 `messages=473236`，直接检查时没有 `messages_fts`；按既有 derived-index contract，在临时副本上显式 rebuild 后得到 `indexed_messages=473236`、`fts5_available=true`。这是 smoke 前置条件记录，不是伪造的生产故障，也没有改写原始数据库。

### Evaluation / Evidence

- `measured fact`：`tests/test_conversation.py` focused suite 为 7 passed；全量 pytest、ruff、mypy、CLI help、Trellis validation 与 diff check 的最终结果记录在本任务 `validation.md`。
- `measured fact`：真实 DeepSeek + SQLite smoke 在 `messages=473236` 的临时副本上成功完成 1 次 tool-assisted query；结果包含 1 个 ToolResult、1 个 Evidence、1 个 CitationBinding、5 个 hydrated MessageSource snapshots，close/reopen 后 Artifact、Evidence、CitationBinding、snapshot 与 answer text 均可 replay。
- `engineering expectation`：数据量继续增长时，Conversation replay 的主要成本会随单个 Conversation 历史长度增长；是否需要 history window、压缩或 branching 必须由真实 workload / Evaluation 触发，当前不提前增加复杂度。

### Observability / Debugging

- 当前可通过 `QueryResult.finalization_error`、runtime termination/error、Conversation Store typed error、SQLite constraint/codec error、Trace normalized failure projection 与测试断言定位失败层；Trace backend 已实现，但 Trace 仍只记录执行事实，不自动诊断 semantic miss 或 answer correctness。
- Store decode 失败会显式暴露损坏 JSON、未知 source type、缺失字段或 content mismatch；不会静默丢弃历史消息或重新搜索补全。

### Boundary / Ownership

```text
Application owns lifecycle, history compilation and validated commit gate.
Conversation Store owns conversations/conversation_messages SQL and Artifact codec boundary.
Canonical Store owns imported chat facts; Retrieval read repository owns read-only projections/FTS.
Runtime/Router/Planner/Tool/Finalizer produce or validate query data but do not write Conversation SQL.
```

### Evolution / Interview Evidence Map

- Q: 为什么只提交 completed Assistant？
  Evidence: `TrivaeApplication.query()`、`QueryResult.is_successful`、`tests/test_conversation.py` 的 success/failure boundary。
- Q: 为什么历史 Evidence 不能直接支持 follow-up？
  Evidence: `ConversationMessage.to_model_context()` 不编译 old locators 为 ToolResult，fresh-boundary regression 返回 `INVALID_PROVENANCE`。
- Q: 如何证明重启后没有重新搜索？
  Evidence: SQLite Store 直接 decode `answer_artifact_json`；restart test 只 close/reopen/load，真实 smoke 断言 Artifact/snapshot/citation replay。
- Q: 未来什么证据会让你重新评估？
  Evidence: 单个 Conversation 的真实历史窗口、mutation/audit、branching 或 evaluation 需求出现可复现 Failure Case 后，再评估压缩、版本化 migration 或 mutation UX。

## Interactive CLI streaming 事实索引

- Problem / root cause：Runtime 本来已有 canonical SDK stream，M6 也已有 Router/Planner/Tool/Retrieval normalized facts；阻塞体验来自 Application 只在完成后返回 `QueryResult`，不是 Agent Loop 缺失。对应 task 的 `design.md` 与 `validation.md` 保存了 ChatLab mapping、代码证据和真实 smoke。
- Why this design：`QueryStreamAdapter` 同时消费 Runtime delta 和 TraceCollector 的 pre-capture live event；Trace 使用同 identity 的 CapturePolicy projection。这样 CLI 不轮询 SQLite、不解析 SDK、不复制 Router/Planner/Tool 执行链，Trace 也不持久化 reasoning/token。
- Provider boundary：DeepSeek `reasoning_content` 由 OpenAI Agents SDK 0.22.0 转成 public reasoning event，再由 Runtime adapter 转为 `thinking_delta`。Provider 不返回时不显示；禁止 CLI 根据 Tool 状态生成伪 reasoning。
- Structured answer trade-off：Provider content 是 Citation-aware JSON，不能像 ChatLab 一样直接打印。增量 parser 只提取 `content_blocks[*].text`，Finalizer 仍验证完整 Artifact；parser failure/Finalizer failure 显式终止，不 repair 或提交 preview。
- Failure evidence：测试覆盖空 reasoning、malformed stream、Tool failure recovery、Provider/Query failure、0 result、Trace Store failure、normal Trace truncation、Ctrl+C line recovery 和单次 Conversation commit。第一次真实 smoke 因进程未导出 API key 按 Settings contract 失败并留下 Trace；导出既有 `.env` 后成功，没有用 mock 替代。
- Measured fact：真实 DeepSeek verbose run 产生 8 次 `search_messages`、8 次 Retrieval completion、1 次 finalization/Conversation commit/query completion；Trace complete，0 reasoning/content-delta persistence，Conversation 只有一个 560 字符 Assistant message并与最终 snapshot 相同。
- Ownership：Runtime adapter 拥有 SDK → Runtime normalization；QueryStreamAdapter 拥有接口无关 live projection；TraceCollector 拥有持久化 data minimization；CLI Renderer 只拥有 terminal presentation；Conversation/Finalizer 语义未改变。
- Evolution：只有真实 workload 证明普通终端 reasoning 过长、需要跨进程消费者或 HTTP/UI 产品需求时，才评估折叠、SSE/backpressure 或异步 event transport；当前不引入 TUI、queue 或第二套日志链。
