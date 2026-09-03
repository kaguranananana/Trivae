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
- Evolution（2026-08-23 当时判断；已被 08-27 TUI 任务实际推翻）：只有真实 workload 证明普通终端 reasoning 过长、需要跨进程消费者或 HTTP/UI 产品需求时，才评估折叠、SSE/backpressure 或异步 event transport；当时不引入 TUI、queue 或第二套日志链。后续真实 workload 确实证明了折叠 TUI 的价值，见「Textual TUI projection 事实索引」。

## Stage A Agent-facing retrieval surface 事实索引

- Problem / boundary：正常 Application `QueryRequest` 默认 visible capabilities 已切换为
  `lexical_search` + `semantic_search`；`search_messages` 仍是显式 legacy compatibility
  entry point。低层直接构造 `AgentRunRequest` 的默认未被强行改写，避免破坏旧 caller；正常
  Query/CLI 编译路径的行为由 `tests/test_agent_tool_surface.py` 覆盖。
- Tool vs Capability：Tool adapter 只负责模型可见 contract、arguments 和 result envelope；
  CapabilityRegistry 仍负责 scope-aware lexical/semantic execution。Stage A 没有创建第二个
  Runtime、Query pipeline、Evidence 或 Trace 系统。
- Selection rationale：prompt 和 Tool descriptions 对 exact URL/repo/code/error/nickname/
  phrase 与 paraphrase/concept/vague memory 给出首选 guidance；模型仍自行选择，弱结果时
  可以切换另一条 path。额外明确禁止同一意图的翻译/同义词/标点变体 multi-query expansion，
  但不在 Runtime 中硬拦截 Agent。没有固定 hybrid、RRF、reranker、query rewrite 或 silent
  lexical fallback。
- Context/Evidence boundary：现有 retrieval Tool 继续返回 bounded local context；同一 Runtime
  内的第二个 retrieval call 共享 run/scope/ToolResult provenance，最终 Evidence/Citation
  仍由现有 Finalizer 验证。
- Evaluation：新增 behavior projection 只记录 first selected tool、实际 sequence、call count、
  rounds、errors 和 final evidence/citation state；它是 diagnostic observation，不是
  `human_verified` judgment。原 paired lexical-only / semantic-only benchmark 与
  `llm_assisted_provisional` labels 保持不变。
- Real Provider evidence：在 473,236 条 canonical messages 与已构建 semantic index 的临时
  snapshot 上，最终四 case acceptance 全部 `completed/complete`：lexical-dominant 首选
  lexical（2 calls / 1 Evidence / 1 citation），semantic-dominant 首选 semantic（3 calls /
  3 Evidence / 3 citations），multi-search 为复合问题（5 calls / 2 Evidence / 2 citations），
  no-result 只调用 lexical（1 call / 0 Evidence / 0 citations）。真实运行也暴露了 Router
  timeout degradation、一次 Provider `SSLError`→`RUNTIME_ERROR` 和一次 invalid answer artifact；
  前两次失败均有成功复跑或显式 compatibility repair，但仍作为 Failure Case 记录，不能包装
  成质量结论或 production SLA。
- Provider compatibility evidence：真实 `opencode-go` 还命中过一次
  `provider_compatibility/json_finalization_repaired`；repair 只移除 tool 参数、保留 JSON mode，
  不解析或提交第一次非 JSON 文本。semantic context 的 100-item transport bound 也由真实
  `tool result items exceeds 100` Failure Case 驱动，并通过 `partial/truncated` 保持边界可见。
- Debugging evidence：Trace 可区分 Router degradation、Tool `ok`/`partial`/error、semantic
  unavailable、retrieval empty、citation validation 和 query terminal failure，因此可以定位
  “选错工具”“工具返回弱/空结果”“Provider/runtime error”“答案 artifact 无效”不同层级。
- Interview evidence map：
  - Q: 为什么分批增加 Tool？ Evidence: Stage A 仅增加双 retrieval surface，Evaluation
    先记录 selection/cost/evidence，再以 Stage B/C checkpoint 继续扩展，避免一次性扩大
    surface 后无法归因 selection regression。
  - Q: 为什么 Search 已经带 bounded context 还要保留 `get_message_context`？ Evidence: Stage A
    只验证 bounded local context；更大但仍 bounded 的 explicit deepening 属于后续 Stage B，
    不是让 Agent 每次机械调用的隐式步骤。
  - Q: 如何定位“选错工具”和“工具搜错”？ Evidence: Trace 先看 first model Tool action 和
    arguments，再看 Tool `ok/partial/empty` 与 retrieval summary；Evidence/Citation/answer
    finalization 位于更后层，不能把 Runtime/provider error 误归为 retrieval quality。
  - Q: 为什么不把 semantic unavailable 改成 lexical 结果？ Evidence: explicit semantic
    failure test、Trace failure projection 和 Stage A validation FC-A6。
- Q: 什么证据会让你重新评估？ Evidence: 重复且可定位的 Provider transport failure、
  Agent selection regression 或 verified quality dataset；在此之前不改变 Qwen、dimension、
  chunking 或 dense bounds。

## Stage B Agent-facing context/member surface 事实索引

- `get_message_context` 复用既有 `ContextExpander` 与 Canonical Read，不把 Search 的内部 context
  步骤拆成 Agent 必须机械调用的流程；只有已知 message locator 且局部上下文不足时才显式
  deepening。证据：`tests/test_stage_b_tools.py` 的 bounded same-session/time-scope、truncation、
  invalid locator 和 explicit Trace assertions。
- Search 自动带 bounded local context 与 explicit `get_message_context` 的边界不同：前者是
  Retrieval result 的局部 acquisition，后者是 Agent 可解释的更大 bounded context request。
  Trace 的 `context.expansion.completed` payload 明确标记 `explicit_deepening`，Transcript 也将
  它单独渲染为 `[CONTEXT EXPANSION]`。
- `find_members` 复用现有 `users` / `memberships`；返回 stable UserIdentity 候选、Membership
  session 关联和 exact/partial match reasons，不新增 `resolve_member` 或 candidate state。多
  昵称候选是需要呈现的 ambiguity，不是必须被模型猜成唯一人物；当前 physical schema 的
  alias-like 值由 `remark` 承载，并通过 `alias` 投影说明这一边界。
- Member candidate 是 Structured row provenance，必须从 `provenance.structured_sources` 使用
  `locator_kind/locator/value_snapshot`；不能套用 message source 的
  `session_id/internal_message_id`。FC-B2 证明了这类 citation shape 不清晰时，生产 Finalizer
  会正确返回 `INVALID_SOURCE`；修复是补充 model-visible contract，不是放宽 validator。
- `ExecutionScope` 由 Runtime 本地对象持有，member session filter、context anchor 和 scoped
  context SQL 都在 Capability/read adapter 边界 enforcing；模型参数不能自行扩大 scope。成员
  limit 的 provider 默认也绑定 trusted max，FC-B1 的真实 `INVALID_ARGUMENT` 已由动态 adapter
  default 和 omitted-limit regression 覆盖。
- Evaluation behavior projection 现在同时保存 `retrieval_tool_sequence`、
  `context_tool_sequence`、`member_tool_sequence`、tool count/round/error；这些是 Agent behavior
  observation，不是 preferred sequence 的 `human_verified` 结论。真实 smoke 的
  `member → lexical` 与 `lexical → semantic → context` 均通过 current-run Evidence/Citation，
  但 latency/usage 仍只是当前 Provider/index 的 measured facts，不是 SLA。
- Q: 为什么 Search 已经有 bounded context 还需要 `get_message_context`？
  Evidence: Stage 1.4 design、`ContextExpander` reuse、explicit Trace mode 和 required-context
  Provider smoke；它让 Agent 在找到关键消息后有一个公开、可追踪的 deepening action。
- Q: 为什么 `find_members` 不叫 `resolve_member`？
  Evidence: Stage 1.2 identity/membership model、same nickname multi-candidate test 和真实
  ambiguity smoke；名称查询证据不足时强行唯一 resolve 会把 ambiguity 变成未经证实的事实。
- Q: 如何区分成员 Tool、Retrieval 和答案错误？
  Evidence: Trace 依次展示 `member.lookup.*`、`retrieval.search.*`、
  `context.expansion.*`、Evidence/Citation finalization；FC-B1 属于 Tool contract，FC-B2 属于
  model-facing citation shape，FC-B3 是 Agent selection observation。
- Q: 为什么 Stage B 不同时加入 SQL？
  Evidence: checkpoint 分批策略、Stage B focused/full/real smoke gate；先验证 context/member
  的 identity 和 context boundary，再用独立 Stage C 验证 structured SQL，避免一次扩展六个工具
  后无法归因 selection regression。

## Stage C Agent-facing structured SQL surface 事实索引

- `get_schema` 复用同一个 `SQLiteCanonicalReadRepository`，只投影现有 physical canonical schema
  的 public tables/columns/relationships；没有引入 Analysis View，也没有把 ingestion、raw
  payload 或 lexical/semantic derived implementation tables交给模型。证据：`PUBLIC_SQL_COLUMNS`、
  `SchemaResult` 和 Stage C schema inspection regression。
- `execute_sql` 是 Tool/Capability 分离的具体例子：SDK adapter 负责模型参数和 Tool Envelope，
  `ExecuteSQLCapability` 负责 trusted result bound，SQLite read adapter 负责 driver-level
  read-only、public schema 和 scope enforcement。Agent SQL 不能通过自己的 `WHERE` 决定权限。
- 为什么不只用 denylist？只拦几个关键词不能覆盖 SQLite 写操作、DDL、ATTACH、PRAGMA、内部表/列
  和 qualified database escape；实现使用 mode=ro connection、SQLite authorizer 和 partial-scope
  temporary public projection。它仍保持原 SQL，不通过拼接 LIMIT 或重写来伪造安全。
- 为什么要 bounded result？`max_rows` 由 Capability 与 trusted `ExecutionScope.max_results`
  共同确定，并与现有 `ToolResultRecord` 100-item transport bound 对齐；zero rows 是正常
  `ok` result，超 bound 则公开 `truncated`，不是静默截断后宣称完整。
- 为什么结构化统计使用 SQL？COUNT、GROUP BY、time range、sender/session aggregation 是由
  canonical rows 确定的结构化问题；让 Agent 用 retrieval 扫大量消息自己计数会增加 token/cost
  并引入可避免的计数错误。`get_schema → execute_sql` 是可观测的公开 sequence，已进入同一
  Runtime/Trace/Evidence。
- SQL Evidence 不伪装成 message citation：schema table 与 SQL row 使用 existing
  `StructuredSource` 的 `row` locator/value snapshot，Finalizer 按 current-run ToolResult
  和 scope exact match；没有放宽 message provenance contract。
- Trace 现在可以区分 schema inspection、SQL execution、返回 rows/columns/truncation/coverage、
  explicit SQL error、Evidence/Citation 和 final answer；它不保存 hidden chain-of-thought。Evaluation
  新增 structured count/aggregation/time/scope diagnostic cases，preferred tool 只是
  `diagnostic_contract_expectation`，不自动生成 `human_verified`。
- 为什么分批增加 Tool？Stage A 先验证双 retrieval selection，Stage B 再验证 context/member
  identity，Stage C 才加入 structured SQL；每批都有 focused/full/real smoke、Trace、Failure
  Case 和独立 checkpoint，避免六个工具同时变化后无法归因 selection regression。
- Stage C 目前已验证的 Failure Case 包括 SQLite unqualified READ callback 的 database=None
  误判，以及 canonical sender identity normalization 导致的测试预期错误。修复分别位于
  authorizer boundary 和测试 fixture expectation，没有新增 silent fallback 或第二套 pipeline。
- 真实 Provider smoke 使用 473,236 条 Canonical 消息和已完成 semantic index，schema→count、
  aggregation、time range、zero-result、scoped-count 均完成 `completed/complete`，Trace 能看见
  `get_schema → execute_sql` 以及部分 case 的第二次 SQL call；首次 schema→count 因 Artifact
  citation binding identity 不一致失败，补充 exact identity prompt 后重跑成功。这里的
  latency/usage 和 sequence 是当前 Provider 的 diagnostic facts，不是 SLA，也不是
  `human_verified` answer-quality 结论。

## Six-tool comprehensive Agent diagnostic 事实索引

### Problem / Boundary

Stage A/B/C 已分别证明六个 Tool 的 capability、adapter、scope、Evidence/Citation 和 Trace contract，
但分别验证不能回答“六个 Tool 同时可见时，Agent 是否会在 retrieval、context、member 和 SQL 之间
合理切换”。本轮只补综合 diagnostic，不新增 Tool、Runtime、Planner、Evidence 或 Trace 系统。

### Why 分批后还要做综合 suite

- Stage A 先只暴露 lexical/semantic，能够把 retrieval selection、semantic unavailable 和 no-result
  Failure Case 单独归因；
- Stage B 加入 context/member 后，新增 identity ambiguity 和 explicit deepening 的行为轴；
- Stage C 加入 schema/SQL 后，结构化统计与 retrieval 的路径选择、scope 和 citation 形状又增加了
  新的交互；
- 因此最终需要一个同时暴露六个 canonical Tool 的 diagnostic catalog，才能发现跨 category 的
  重复调用、过早终止和 Finalizer contract failure。`evaluation/diagnostics/agent-tool-selection-
  comprehensive-v1.json` 的 14 个 case 保存了这个版本化问题集。

### Deterministic contract vs quality judgement

- Deterministic：六个 Tool 是否完整且不重复注册、legacy 是否没有进入默认 surface、实际 sequence/
  rounds/status/error、ToolResult current-run provenance、returned rows/messages、partial/truncated、
  coverage、scope enforcement、Evidence/Citation/Finalizer 状态、termination、latency、usage。
- Quality judgement：preferred first Tool 是否合理、第二次 Tool 是否必要、自然语言答案是否正确、
  证据是否充分。它们继续标记为 diagnostic expectation，交给 LLM-assisted 或人工 review，不自动
  变成 `human_verified`。
- 现有 paired lexical-vs-semantic retrieval benchmark 和 `llm_assisted_provisional` labels 未被
  删除或升级成 ground truth。

### Observability / Failure Attribution

综合 Trace 的公开链路是：

```text
query.received
  → visible capabilities / model tool action
  → tool.call.* + retrieval/context/member/schema/sql result summary
  → optional next Tool category
  → evidence.prepare / citation.validation
  → answer.finalization / query terminal
```

`operational_measurements` 通过同一 `TraceProjection` 派生 `tool_result_facts`，不重查数据库、不
保存 raw SQL rows 或 hidden chain-of-thought。真实运行中可以区分：

- 选错或重复 Tool：F2 的 `semantic → semantic`、F6 的 member query 却走 `schema → sql ×4`；
- Tool 成功但任务组合不完整：F10 首次/重跑分别出现 Finalizer provenance failure 和停止在 schema
  前未执行 SQL；
- Tool/Scope 正确但 Provider/Artifact 错误：F13 SQL `returned_rows=0` 后 Provider 仍提交不可解析的
  structured citation，Finalizer 返回 `UNRESOLVED_STRUCTURED_SOURCE`；
- external Provider failure：F5/F14 的 `SSLError` 在 Trace 中归属 `runtime`，不被改写成 Tool
  error 或 silent fallback；
- 不必要成本：F14 rerun 的第二次 SQL 在同一 scope、same Trace/Evidence 链内可见，当前只是 cost
  observation，不足以增加 execution timeout/progress handler。

### Design Defense

- Q：为什么 Search 已带 bounded context 仍保留 `get_message_context`？
  Evidence：F3 使用 `lexical → semantic → context`，F4 对照只调用 lexical；deterministic Trace
  能区分自动 search context 与 explicit deepening，说明 context Tool 不是机械必选步骤。
- Q：为什么 lexical/semantic 仍是两个 Tool，而不是固定 hybrid？
  Evidence：F1/F2/F3/F12 的实际序列有 lexical-first、semantic-first 和交替补查；catalog 允许
  多种序列，Runtime 不加入 fixed hybrid/RRF/reranker/query rewrite。
- Q：为什么成员查询返回 candidate 而不是唯一 resolve？
  Evidence：Stage B ambiguity contract、F6 的 diagnostic expectation 和 existing multi-candidate
  tests；F6 走错 SQL 也能通过 Trace 暴露为 selection failure，而不是把 SQL 结果包装成身份结论。
- Q：为什么统计交给 SQL？
  Evidence：F8/F9 真实 Agent 使用 `get_schema → execute_sql`，返回 bounded structured rows，且
  SQL scope enforcement 可直接观察；这比让模型扫描大量 retrieval message 自己计数更容易做
  provenance 和 scope 诊断。
- Q：为什么 SQL 允许模型写，权限却不能由模型决定？
  Evidence：F14 rerun 在不依赖模型完整过滤条件时仍使用
  `scope_filtered_temp_tables_and_sqlite_authorizer`；模型 SQL 是查询意图，trusted
  `ExecutionScope` 才是授权边界。
- Q：为什么 Finalizer 不能为了 smoke 通过而放宽？
  Evidence：F10 `INVALID_PROVENANCE`、F13 `UNRESOLVED_STRUCTURED_SOURCE`；两次 SQL/Runtime 都
  有成功事实，但不合法 citation 被拒绝，避免把 Tool success 伪装成 grounded answer。
- Q：如何用综合 Evaluation 防止 Tool 增加后 selection 退化？
  Evidence：catalog 固定 category 与 deterministic observation fields；projection 保存实际
  first/sequence/call/round/error/result/finalization/cost，preferred sequence 不作为唯一脚本，
  后续以重复 Failure Case 和 answer-quality review 决定是否调整 guidance。

### Current measured boundary

本轮 deterministic 全量为 `275 passed`，ruff、mypy、compileall 通过；真实 Provider 运行 14 个
综合 case，并对 F5/F10/F13/F14 做 targeted rerun。结果证明 Trace/Evaluation 能定位跨 Tool 行为、
scope 和 Finalizer hard boundary；没有证明 Agent selection accuracy、自然语言答案 correctness、
production latency SLA 或 provisional retrieval quality。下一轮只有在这些 Failure Case 重复且有
paired Evaluation 证据时，才考虑 prompt/Planner/cost guidance 的最小调整。

### CLI Product Experience hardening evidence（2026-08-25）

- Q：为什么 `/source` 不直接把 AnswerArtifact 里的 excerpt 当作最终正文？
  Evidence：`TrivaeApplication.inspect_message_source()` 复用 scoped canonical read；
  `tests/test_product_experience.py` 锁定 source locator 的确定性去重，来源展示字段仍来自
  Finalizer trusted snapshot，避免模型正文成为 metadata authority。
- Q：为什么 legacy Conversation 不允许直接 resume？
  Evidence：`conversations.scope_snapshot_json` 是 additive nullable migration；NULL scope
  只能 history display，`ConversationScopeError` 拒绝猜测权限，避免跨 scope history injection。
- Q：为什么用户反馈不写 Evaluation 或 Trace？
  Evidence：独立 `SQLiteFeedbackStore` 的 `user_experiential` record 按
  `(conversation_id, trace_id)` upsert；反馈测试断言后一次 rating/note 更新同一 identity。
- Q：如何证明 readiness 不会暗中修复 semantic index？
  Evidence：`ApplicationReadiness` 只调用现有 status facade、canonical count 和
  `load_settings()`；product regression 断言空数据库保留 `semantic=missing`，没有 rebuild path。
- Q：如何处理 CoT、raw event 和未知异常？
  Evidence：renderer regression 断言 normal/verbose 不出现 reasoning text、stream sequence、
  trace event identity 或 JSON；unknown exception 由 Python logging 保留 root cause，CLI 只输出
  bounded type diagnostic。

本轮新增 product regression 后 deterministic 全量为 `282 passed`；单次本地 smoke 读取临时
Canonical 数据的同 session context，返回 `before / anchor / after` 三条 bounded projection，
未触发第二套 Query、Provider 或 Retrieval。该事实不证明真实 provider latency、答案质量或网络
健康状态。真实 Canonical DB 的 metadata-only startup smoke 显示 database/semantic ready 与
provider `not_configured`；因此没有虚构 provider Query 结果。

## Context Engineering hardening 事实索引（2026-08-25）

### Problem / Failure

- `ToolEnvelope.to_dict()` 同时承载完整 provenance、内部 identity、检索命中和 expanded context；
  直接作为 model context 会把 bookkeeping 噪声与语义混在一起，并让模型复制不稳定 ID。
- 旧 final JSON 让模型提交 claim、evidence、source、binding 以及 deterministic ID；这把 source
  hydration、去重、排序和 artifact identity 变成脆弱的 JSON 复述任务。
- 相对时间如果由模型使用 machine now、`MIN(timestamp)` 或手工计算，会把“最近”解释成不可信的
  时间段；没有独立 tool-result budget 时，expanded context 也可能挤掉真实 hits。

这些是本轮的 regression contracts / anticipated boundary，不把未发生的 provider token overflow
写成真实线上 Failure。

### Decision / Ownership

`LLM decides semantics; Host code owns deterministic bookkeeping.` `ModelAnswerCandidate` 只包含
claim/finding/criterion/sufficiency/limitations 与短 source handles；Host 保留完整 canonical
ToolEnvelope/ToolResultRecord，生成 artifact/evidence/citation/binding IDs，解析 current-run
handle，校验 scope，hydrate trusted URL/value，并编译成旧 CLI/Conversation 可消费的 `AnswerArtifact`。

模型 projection 有独立 `DEFAULT_TOOL_RESULT_TOKEN_BUDGET`：保留所有真实 hits，先移除非命中 context，
再显式缩短正文；仍不满足时返回 `ToolResultProjectionError`。retrieval limit、scope max、context
bound、projection budget 和 answer/evidence budget 不互相冒充。Code Mode、citation repair、retry、
fallback 与 hidden CoT 不在本轮范围。

### Evidence / Observability

- 短 handle 只在当前 Tool Result scope 有效；缺失、歧义、跨 scope 和未知 handle 都显式失败，
  不借用历史 Tool Result。
- `archive_latest` 由 trusted canonical read 的 `MAX(timestamp)` 得到，Host 计算 half-open
  absolute range，并在 query/Trace 保存 raw intent、anchor、resolved start/end。
- Host 记录 projection estimate/truncated/omitted context；没有 provider usage 时写
  `unavailable`，不把 estimate 或零值包装成 token measurement。

### Interview defense mapping

- Q：为什么不让模型复制完整 provenance？
  Evidence：candidate parser、handle regression 和 current-run resolution；模型输入是 semantic
  projection，Host record 才保留 full IDs，避免 JSON mover 破坏 identity。
- Q：为什么不让模型自己计算“最近一个月”？
  Evidence：relative-time capability tests；`archive_latest` 与 resolved half-open range 由
  canonical read/Host 产生，machine clock 不进入 contract。
- Q：为什么不直接把 Tool Result 截断到一个全局 token 数？
  Evidence：独立 model projection budget；真实 hits、context omission、正文 truncation 和
  unavailable provider usage 分开记录，超限不能静默丢命中。
- Q：为什么不引入 Code Mode 或 fallback？
  Evidence：当前 Tool Calling 已有 scope、Trace、Evidence hard boundary；没有 Failure Case 或
  paired Evaluation 证明需要另一执行通道，新增 fallback 只会隐藏根因。

## Retrieval Budget / Tool Result Budget 事实索引（2026-08-26）

### Problem / Root Cause

旧的 `DEFAULT_RESULT_LIMIT=100` 同时约束 lexical candidate、trusted umbrella、context expansion、
Evidence message transport 和 provider schema。它曾修复 `31 hits / 20 messages / truncated`，但也把
inventory query 的 recall 固定在 100。若把同一个常量全局改成 1000，semantic、structured/member/SQL、
context 和 Evidence value budget 会被错误放大。根因是不同资源共享一个名字，而不是单个数字不够大。

### Design Decision / Trade-off

- lexical candidate：default 1000、hard cap 5000；服务“有哪些/全部/完整清单”类 broad recall。
- semantic direct evidence：default 10、hard cap 20；`dense_top_k=40` 仍是独立 ANN candidate 参数。
- trusted `ExecutionScope.max_results`：5000 umbrella；每个 Capability/provider 再做自身 hard cap。
- context：最终 expanded message 100；direct hit 已填满容量时不读取邻居，有空间时最多 20 个 source hit。
- Tool Result：canonical message 5000、structured/value 100；model-visible projection 固定 16k estimated tokens。

Evidence：`config/limits.py`、各 typed query/capability、`query/runtime/openai_tools.py`、
`query/evidence.py`、`tests/test_retrieval_budget.py` 与任务 `validation.md`。真实 archive 的
`https` 1000 candidate retrieval median 131.7ms、projection 151.0ms；`Agent` 1000 因 20 个真实
context source hit 为 2,215.8ms。初版 projection 的 O(n²) 尾部删除已复现并用二分省略修复，不能
通过回退 lexical budget 隐藏实现瓶颈。

### Failure Classification

- Retrieval Coverage Failure：A 从 31 扩到 93 lexical hits；B 找回明确 joye URL；D 保留
  `deepseek helan` name-only 项，但 dsh-web-ui/整合包仍未完整列出，标记 `ENUMERATION_INCOMPLETE`。
- Claim Grounding Failure：recall 增大不能证明“提及=推荐”“测试意图=实际使用”“看过产出=个人安装”；
  taste-skill After 明确拒绝这些推断。`citation unresolved=0` 只证明 locator/provenance 可解析，
  不证明 claim 的事实蕴含或唯一实体计数正确。

### Interview Defense Mapping

- Q：为什么不能用一个 `DEFAULT_RESULT_LIMIT`？
  Evidence：旧 `31/20` 回归、预算审计表、独立 1000/10/20/100 contracts 与 schema/Capability 双重测试。
- Q：candidate budget 和 Tool Result token budget 有什么区别？
  Evidence：canonical 可保留 689/1000 lexical candidates，而 model projection 仍在 16k 内，
  显式报告 `truncated`、`omitted_hit_messages` 和 visible source handles。
- Q：为什么 semantic Top-K 不能跟着 lexical 变大？
  Evidence：provider schema/CAP hard cap 20、`dense_top_k=40` 保持独立；semantic recall 与
  lexical inventory 的目标不同。
- Q：什么证据会触发下一阶段？
  Evidence：复现带人工实体/claim 标注的 `ENUMERATION_INCOMPLETE` 或 mention/use/review
  entailment failure；在此之前不增加 lexical hard cap、不加四题特例、不重构 Evidence。

### Executable contract

1. **Scope / Trigger**：当 Retrieval candidate、Tool Result transport、context expansion 或
   model projection 的边界发生跨层变化时，必须同时检查 Provider schema、typed Capability、
   Retrieval Core、Evidence record、Trace 和 Evaluation。
2. **Signatures**：`LexicalQuery.limit` 默认 1000/上限 5000；`SemanticQuery.limit` 默认 10/上限
   20；`ExecutionScope.max_results` 是 5000 umbrella；`ToolResultRecord` message/structured
   item 上限分别为 5000/100；model projection payload 必须含 `estimated_tokens`、`truncated`、
   `omitted_context_messages`、`omitted_hit_messages`。
3. **Contracts**：Provider schema 只展示 tool-specific maximum；Capability 必须再次验证
   trusted scope；semantic `dense_top_k=40` 不等于最终 limit；Trace terminal payload 记录
   retrieval counts、partial/truncated、projection estimate/omitted 和 provider usage。当前没有
   context-window registry，`DEFAULT_TOOL_RESULT_TOKEN_BUDGET=16_000` 是固定边界。
4. **Validation & Error Matrix**：lexical >5000、semantic >20、structured/member/SQL >100、
   trusted scope >5000、context range source >20 或最小 model projection 仍超 16k 时，分别在
   Query/Capability/Projection boundary 显式抛错；不得依赖 Prompt、silent fallback 或静默截断。
5. **Good / Base / Bad Cases**：Good 是 lexical 1000 命中且 context=0、semantic 10/20 + dense40、
   model projection 在 16k 内；Base 是超预算后记录 truncated/omitted 并保留 direct hit 优先；
   Bad 是用 1000 放大 semantic/SQL、让 context 挤掉 hit、或把 `citation unresolved=0` 当作事实正确。
6. **Tests Required**：`tests/test_retrieval_budget.py` 锁定 defaults/hard caps/schema、150 条
   lexical、100 direct hits、20 source-hit budget、canonical >100、16k omission、Prompt safety
   和七轴/七标签；全量 pytest、ruff、mypy 与真实 100/300/1000 archive benchmark 必须通过。
7. **Wrong vs Correct**：
   - Wrong：`DEFAULT_RESULT_LIMIT=1000` 被 lexical、semantic、context、structured 和 Tool Result
     共用，或者只相信 provider JSON schema。
   - Correct：各层使用独立常量和二次 Host enforcement；canonical 保留 bounded candidate，
     model projection 独立 16k，超限明确 `truncated/omitted`，最终把 recall failure 与 claim
     grounding failure 分开记录。

## Textual TUI projection 事实索引（2026-08-27）

- Problem / root cause：上一阶段的 stdout streaming 解决了「实时可见」，但 `Route:/Plan:/Action:/✓`
  平铺让用户分不清思考/计划/工具/回答边界，长 run 十几行过程淹没最终答案，且无回看/折叠能力。
  根因是 presentation 层只有一个线性 Renderer，而不是事件链路缺事实。
- Why projection layer：新增 `TuiProjectionEngine`（纯 reducer：QueryStreamEvent → 最小
  state diff）后，Textual 只是「快照渲染器」。Runtime 不知道 Textual、TUI 不重跑 Agent/不订阅
  SDK；同一个 Query 只执行一次，plain renderer 与 TUI 消费同一事实源。面试可讲清这层为什么
  不是"第二套状态机"——它没有 Agent 语义，只有 UI 呈现语义（status/title/metrics/expanded）。
- Two-phase segments（来自 ChatLab `buildProcessSegments`）：运行中按 timeline 逐块出现；
  terminal 后把 route/thinking/plan/tool/retrieval 冻结成单行「执行过程 · N 步 · 总时长」折叠组，
  answer/error 留在外层。终端版差异：不照搬 web 的 CSS disclosure，用 focus + Enter/Space +
  click 三通道等价交互（Textual widget 原生能力）。
- Compact tool rows（Beautiful UI Task Rows 参考）：完成后工具默认严格单行
  `✓ 名称 · hits/msgs chips · duration`，详情（参数/结果摘要/partial-truncated ⚠）只在展开出现；
  progressive disclosure 以两级实现而非大块 Collapsible 默认铺开。设计张力点：早期需求写过
  "running tool 自动展开"，最终以「collapsed 行内联错误码 + 展开态完整 code/message」折中，
  保持纵向空间最少化。
- Tool identity & aggregation：start/complete 用 `tool_call_id` 关联同一 block，乱序完成不影响
  正确行；`retrieval.completed` 在存在 running tool 时 deterministic 合并进该行 metrics，
  消除 ChatLab 式重复 Retrieval 卡片——真实 smoke #2 验证事件链 4 个 retrieval 相关事件只呈现 1 行。
- CoT boundary（第一版实现，已被下方 Owner decision reversal 更新）：第一版 thinking block 只投影
  真实事件的时长/状态元数据；现行为为 public_summary 正文进入 UI state 并渲染，
  无标记的私密 reasoning 依旧连 engine 都不存。
- Streaming state management：answer delta 累积进同一 AnswerBlock，Markdown 以最新全文重建渲染；
  authoritative `answer.completed` 整体替换 preview 防 finalizer 漂移；compose 未完成时更新降级为
  登记文本（真实缺陷修复：首个 delta 同时产出 created+appended 两个 change 才能保证挂载顺序）。
- Failure UX：Ctrl+C → cancel worker → engine.finalize_interrupted 生成中断 error row；
  query.failed/provider 失败由事件驱动 error row + 组默认展开；两种路径都恢复输入焦点。
  真实 smoke 里 provider 偶发失败被完整承接（历史保留、✓/✗ 同屏）。
- Textual vs Rich Live 取舍：Rich Live 是单刷新区，无组件树/focus/键鼠/Pilot 测试；用它做可折叠
  多块交互等于手写半个框架并违反"不做 ANSI 手术"约束。Textual 换来 message pump、focus 系统、
  Collapsible/Markdown 与确定性 headless 测试。
- Measured evidence：370 tests / ruff / mypy 全绿；4 类真实 DeepSeek run
  （5.76s 简单、63.97s 单工具、46s 多工具含失败、76s 15 步）全程有 UI 反馈且无静默期；
  SVG 截图取证三层结构 You > / 折叠组 / 回答。

- Owner decision reversal（2026-08-27）：早期「终端一概不渲染 reasoning」被产品 owner 显式推翻为
  「public_summary 标记即展示」。边界从"标记不可信所以全禁"改为"按 boundary 标记执行"：
  QueryStreamAdapter 是唯一判定点（无标记的 delta 直接丢弃），TUI 只消费已裁决事实。
  面试角度：可见性策略变更只动 projection 两层中的一处 gate，Runtime/Trace 的 data minimization
  （reasoning 不落盘）保持不变——分层使安全策略可以独立演进。
- Copy/export UX：全屏 TUI 接管鼠标导致原生选中失效（终端 Shift+拖拽可绕过）；
  追加 `/export` 命令把会话 block 快照导出纯文本。选 alternate screen 放弃 inline scrollback
  也是同类取舍：渲染可靠性 > 退出后内容残留。

## Temporal browsing 与 CJK lexical recall 事实索引（2026-08-27）

- Real failure before/after：`最近一两天大家都在讨论什么有价值的内容` 在 trace `trace-87060c18023e46988f4df09a98a27f9f`
  中为 semantic×3+lexical 猜测→failed ~75s；修复后 trace-3c348e06… / e3b18400… / 41c05fb2…
  均以 `get_recent_messages` 为首个且唯一数据读取 Tool，1 tool call、1 round、23–36s、finalization valid、3–5 citations。
- 为什么 retrieval 工具已存在还需要 recent messages：候选集合由时间范围决定时，"猜测主题再检索猜测"
  对 embedding/BM25 都不构成 query-document 相关性；ChatLab 同题一次 browse 成功是外部对照，
  Trivae 自己的证据是 ADR §11 预设 reopen trigger 被真实 trace 触发（见 `.trellis/spec/project/problems/temporal-browsing-cjk-lexical-recall.md`）。
- Agent-facing tool ergonomics：execute_sql 理论可行（ORDER BY DESC LIMIT），但真实 trace 证明模型
  在第 4 轮拿到 schema 后仍放弃——能力存在于 API 不等于 Agent 会稳定使用；新 Tool 的 description
  直接绑定 question shape（overview/recent/topic discovery），把选择问题从"推理规划"降为"模式匹配"。
- Specialized Tool 何时值得增加：沿用 ADR §11 标准——高频 + 机械/易错 + 明显收益；本轮新增工具内部
  零新数据读取代码（复用 StructuredRetrieval.retrieve_recent_messages → repository read_recent_messages）。
- Candidate data vs LLM judgment 分离：get_recent_messages 只做 latest-N selection，返回值里没有
  "有价值"字段；价值判定/citation 归 Agent final artifact，Host finalizer 负责 scope 重校验与 grounding。
- 中文 FTS recall 根因证据链：先排除 canonical 存在/session scope/timestamp/index freshness（count 一致）
  /MATCH escape，再用 fts5vocab 拿到实测 tokens（真心推荐=单 token；推荐这个repo 也是单 token）才归因
  tokenizer——不是从经验直接断言。
- Tokenizer 影响：trigram 探针证明其对 2 字查询 MATCH=0 且破坏 ASCII exact contract；
  bigram 归一化只改写 Han run（重叠 bigram 保序短语 ⇔ 子串命中），URL/repo/code/error matrix 测试锁定不退化。
- 为什么不做 silent LIKE fallback：改变成本曲线（全表扫）、隐藏 strategy 不一致这类配置漂移故障、
  让 coverage/provenance 变成假话；替代方案是把 strategy id 写进 derived meta 并在 read 侧显式 stale。
- 用 Trace 区分"选错工具"与"检索错误"：tool.call payload 记录 request/result summary 与 error code 所在层
  （tool contract / retrieval execution / runtime terminal 分开）；trace-87060c 里每个 0-hit 都是
  `status ok + total 0` 的正常结果，失败归属在 Agent 决策与最终契约，而非 retrieval 执行异常。
- Remaining honest gap（anticipated risk）：答案契约对 limitations-only 空 claims 仍是 fatal；本次通过
  保证浏览路径有真实内容不再触发，但窗口确无消息时应回答空的场景仍未开放该出口（未改动契约，留待独立 Failure Case）。

## Interview ln mapping

Q1 已有两类检索为何还要 recent messages → 本节第 2 条 + ADR §19；
Q2 execute_sql 理论即可为何不够 → 第 3 条 + trace 对照；
Q3 tool ergonomics 定义 → 第 3 条；
Q4 specialized tool 增加标准 → 第 4 条 + ADR §11；
Q5 如何用真实 Failure Case reopen 旧 ADR → ADR §11→§19 + problem record；
Q6 candidate/judgment 分离 → 第 6 条 + recent_messages.py 边界注释；
Q7 中文 FTS 为何 0-hit → 第 7 条诊断链 + sqlite_lexical_text.py；
Q8 tokenizer 取舍 → 第 8 条 trigram/bigram 实测矩阵；
Q9 silent LIKE 为何被拒 → 第 9 条 + problem record Options 表；
Q10 Trace 定位方法论 → 第 10 条。

## Mixed-script lexical v2 与 no-result contract 事实索引（2026-08-27 第二轮收口）

- FTS5 中文 recall failure 双层根因：①unicode61 把连续 Han run 归一个 token；②mixed-script（`abc推荐`）
  在 ASCII/Han 边界粘连成单 token。v1 bigram 只解决①；v2 用空格包裹每个 maximal Han run（含单字）建立
  显式边界，ASCII token 内部语义不动。修改前 8 案例矩阵与修复后全部命中见 problem record 表。
- 为什么不用 LIKE：LIKE 可作 oracle 但作为查询路径是全表扫、破坏 strategy/versioned index 的
  failure attribution，且属于 silent-fallback 家族——项目原则禁止。
- Derived index versioning 防语义漂移：rebuild 写 `trivae_derived_meta.lexical_tokenizer_strategy`
  （现 `unicode61+cjk-bigram-v2`），read 侧 mismatch 即 `LexicalIndexError stale`；真实库 rebuild 前实测
  v1 索引被拒、rebuild 后恢复——index/reader 任何一方单独升级都会显式暴露而不是静默误召回。
- Agent 为何需要 temporal browsing capability：真实 trace 证明"能力存在（SQL）≠Agent 会用"；
  tool description 绑定 question shape（overview/recent/topic discovery）+ Do-NOT-guess 提示后，
  E1/E2 单工具完成。这是 ergonomics 决策而非新检索原语。
- "0 rows 不能当执行失败"的三层依据：FTS/canonical 层 zero hit 本就 status ok（§15/14）；Capability 层
  空 trusted scope 不再报 anchor 错误而是合法空结果；finalization 层新增 `kind=no_result` 显式形态。
  系统错误（malformed/reversed/scope/stale/runtime）仍逐层 fatal——失败类别保持分离。
- no-result contract 如何不变成 hallucination loophole：放行条件不是"模型声明"，而是 Host 从
  ToolResultRecord 可验证的无事实状态（无 message_items、无非 tables[] structured rows）。冲突时
  strict `INVALID_FINAL_OUTPUT` 立即 failed；no_result 与 claims 字段互斥。真实 provider 故意输出
  placeholder no_result 被 guard 拒绝（trace-f3fc2a1d…）是该护栏的实证。
- SDK schema 与 Capability contract 一致性：可选参数必须有定义完好的缺省语义，否则模型合法调用会
  撞非法输入；`{}`≡recent-2d(anchor archive_latest) 的选择理由是 ChatLab baseline 语义 + archive
  时间观（库尾即"最近"，绝不用 wall clock 推出必然为空的窗口）。

## Interview ln mapping（第二轮）

Q1 FTS5 中文 recall 根因 → 第 1 条 + 复现表；
Q2 LIKE 为何被排除 → 第 2 条；
Q3 index version 防 drift → 第 3 条 + test_v1_index_is_rejected_by_v2_reader；
Q4 temporal capability 必要性 → 第 4 条 + before/after trace 对照；
Q5 zero-result 非失败的分层论证 → 第 5 条 + tests/test_recent_messages.py;
Q6 no-result 防滥用设计 → 第 6 条 + tests/test_no_result_finalization.py::test_no_result_conflicting_with_real_results_is_fatal。

- bigram 契约精确边界：≥2 字 Han 子串 = 完整召回；单字 query 是 known limitation（doc token 全为
  bigram，"荐"命中不了"心推/推荐"内部），不是 bug 也不是 silent-fallback 场景——作为契约写进模块
  docstring 与 problem record，未来出现单字检索真实需求再触发重评估。

## Local Web UI 事实索引（2026-08-27，branch codex/web-ui）

> 完整决策链见 [web-primary-interface.md](./technical-decisions/web-primary-interface.md)。
> 实现证据：src/trivae/interfaces/web/*、web/*（Vue SPA）、tests/test_web_server.py、
> tests/test_web_streaming_contract.py、web/tests/*。以下每条均可基于真实代码/trace 回答。

### Problem / Motivation

- **为什么从 TUI 增加 Web**：终端无法富展示结构化 Tool Result（20 items/16k 纯文本上限）、
  Router reason/Plan/Retrieval coverage 诊断与历史过程回放；ChatLab 证明 Web 是 AI Chat 的
  primary surface。TUI 工作未浪费：QueryStreamAdapter/TuiProjectionEngine 与全部契约原样保留，
  Web 是第三个消费者（feat commit 395af4a/1405673/fbf0b32）。

### Design Rationale / Why not

- **Runtime 不直接输出 Vue event**：RuntimeEvent 是 SDK 边界的稳定事实流；Web 需要的是与
  Trace/CLI 同源的 UI-neutral 事件 + 归属信息。直接输出 Vue event 会把展示状态机焊进 Runtime，
  CLI/TUI/Evaluation 无法共享。
- **QueryStreamEvent 为什么 UI-neutral**：三个接口消费同一事件流 = 同一执行语义；扩展
  （thinking_visibility/result_projection/abort_event）全部 additive 带默认值，CLI/TUI 零改动
  （tests/test_query_streaming.py 全量通过验证）。
- **Tool 用 tool_call_id**：同轮可并行调用同名工具；ChatLab updateToolBlockStatus 先按
  toolCallId 精确匹配再 fallback name，Trivae 前端 store 只按 tool_call_id 匹配。
- **Retrieval 用 parent_operation_id**：retrieval.search.* 的 parent 是具体 tool call；
  无 parent 的 retrieval 独立展示——禁止按"相邻事件"猜归属。
- **Router reason 来自 Router contract**：RouteDecision(route/confidence/source/reason) 是
  Router 自身的契约输出，经 router.decision payload → QueryStreamEvent metadata 透传；
  前端只渲染不生成（真实 smoke：source=llm reason="查询仅要求获取最近的讨论话题…" conf=0.95）。
- **Tool Result 为什么不能只传字符串**：TUI 的 project_tool_result_detail 是有界展示投影；
  Web 需要结构化 items（sender/timestamp/session/content/hit/urls/score）才能做"真实看到了什么"。
  新增 project_tool_result_structure（transport ≤200 items + 截断标志），canonical 语义不变。
- **大量 Tool Result 如何避免 DOM 爆炸**：transport 上限（200）与 UI 折叠（默认 20 条）是两个
  独立预算，UI 显示 "显示 20 / 100 条" + transport_truncated 显式标志；完整数据归 Trace。
- **为什么使用 SSE/HTTP streaming（NDJSON）**：POST body + 单向事件流；fetch ReadableStream
  原生支持 AbortController；无 WebSocket 的连接生命周期/代理复杂度。
- **browser disconnect 如何 cancel**：服务端 event generator 每 0.2s 轮询
  `request.is_disconnected()`，断连即 set abort_event → runtime 优雅取消 → query.aborted
  terminal → stream.end(status=aborted)；streaming response 自身被取消时 also cancel task。
- **conversation 如何恢复**：message 级 trace_id 引用 + TurnProcessCollector 的 bounded 过程
  摘要（router/plan/tool/steps）随 commit_turn 持久化；重新打开 = User/Answer/Sources/过程组
  全部还原 + 原 conversation_id 继续 follow-up（真实 smoke：两问同 conv，指代解析成功）。
- **切换 conversation 为什么 stream 不串**：store 维持 streamOwners(request_id→buffer) 映射，
  appendEvent 按 owner 写；ChatLab 同构（targetBuffer 捕获 + bindDisplayedBuffer 只切显示）。
  单测 chatStore.test.ts 覆盖 owner isolation。

### Failure Cases（真实发生并修复）

- **claims schema 答案流为空**：DeepSeek 经 json_finalization_repaired 路径输出
  `{"claims":[...]}`（非 content_blocks），delta parser 只认 content_blocks[*].text →
  answer.delta=0，CLI 靠 final_answer 兜底而 Web 无正文。修复：parser 同源提取
  claims[*].text（回归测试 AnswerDeltaClaimsSchemaTests）。
- **流式过程不显示**：过程组完成后默认折叠被错误套用到 streaming；ChatLab 行为是活动段实时
  展开。修复 isOpen = isActive || hasError。
- **Stop 后 Send 不恢复**：streams 用普通 Map，computed 不失效 → 按钮状态卡死。修复：reactive Map。
- **tool.completed 双源覆盖**：runtime（带 result_projection）与 normalized（带 summary）各发
  一次；store 用 additive merge 而非整体覆盖。

### Evidence

- 真实 provider smoke：STANDARD（route reason/conf=0.95、get_recent_messages 100 items、
  18 sources、trace-f7649b27…）与 PLAN（5 步 plan、3 thinking 段、5 tool calls、retrieval
  partial/truncated stats、145 answer deltas、16 sources、trace-ccb9e07d…）。
- macOS Finder 真机：open -R 参数数组打开并选中 data/traces/trace-*.log；非法 id 404、
  路径穿越拒绝、非 localhost 403 REVEAL_LOCAL_ONLY。
- Playwright E2E 22/22（历史回放/Router/Reason/Confidence/Tool arguments/Result/20-100 displayed/
  Sources/Trace/follow-tail/回到最新/新对话/刷新恢复）+ Stop 流程 3 项。
- 质量门：ruff/mypy 干净；pytest 472 全绿（TUI/CLI 回归在内）；web vitest 7、tsc/build 干净。

## Temporal Overview Coverage 事实索引（2026-08-28）

### Problem / Motivation

- 真实 Trace `trace-3ca9975108534180b73ce7f518d7c1c4` 的两天窗口有 `2699` 条消息，旧
  `get_recent_messages` 只返回 `100` 条，却把尾部样本用于全窗口概览。
- 同一 Trace 的 Host 毫秒边界对应 UTC 2026-08-14 至 2026-08-16，最终文字写成六月；根因是
  时间事实没有成为跨 Tool/Trace/Artifact 的强制 metadata，模型把原始数字自行换算了日期。

### Design Rationale / Why not

- 选择 recent 独立 `default=1000 / max=5000`，因为 broad temporal browsing 需要 recall；保留
  structured `100`、lexical/semantic 自己的预算和独立 Tool Result token budget，因为它们解决
  的不是同一个资源/语义问题。
- 选择 keyset cursor 而不是 offset：canonical ordering 的复合边界能处理 same timestamp、NULL
  seq 和新消息插入；cursor 同时锁定 session/time scope，越权或篡改显式失败。
- 不选择“只提高 max 到 5000”：2699 条仍可能超过模型 token budget，所以 canonical retrieval
  与 model projection 必须记录两套数量；Trace 不复制全量正文。

### Failure / Regression Evidence

- `real failure`：旧窗口 `total_hits=2699, returned=100`；修复后真实 DB 以 `1000+1000+699`
  完成 continuation，union `2699`、overlap `0`。
- `regression test case`：`tests/test_temporal_overview_coverage.py` 覆盖默认/硬上限、partial/
  complete、cursor no-overlap/no-gap、same-timestamp deterministic、scope/window tampering、
  projection truncation、empty no-result、Trace facts 与 Artifact codec。
- `anticipated risk`：5000 canonical messages 在未来更长正文上可能使 projection 频繁达到预算；
  当前用 measured omission 保留事实，只有 paired Evaluation 证明质量不足时才调整 budget 或
  引入摘要/分桶。

### Evaluation / Evidence

- `measured fact`：archive latest `1786847688000` = `2026-08-16T02:34:48.000Z`；two-day
  half-open `[1786674888000, 1786847688001)` count `2699`；one-day count `911`；低密度一小时
  count `1`；future empty count `0`。
- `measured fact`：two-day 1000-page projection `projected≈165, omitted≈835`；5000 request
  canonical `2699`、projection `≈175`、omitted `≈2524`；两者均受 `16000` estimate budget。
- `measured fact`：稳定样本中 SQLite retrieve median 约 `28.5/33.6/39.4ms`（100/1000/5000），
  projection median 约 `2.1/125.2/513.5ms`；tracemalloc diagnostic peak 约 `0.44/4.08/11.39MB`。
  这些数字只代表当前本地数据库/实现，不能表述为生产 SLA。

### Observability / Debugging

`structured.browse.completed` 能按 page 复核 `total/returned/covered/eligible/coverage/has_more/
next_cursor/range/latency`；Runtime terminal 能复核 `projected/omitted/token estimate`。因此可以
区分 canonical retrieval 不完整、model projection 预算截断、scope/time contract error 和
Evidence citation 越界，而不是把它们都归为“模型总结不好”。

### Boundary / Ownership

```text
Canonical Store / SQLite read adapter owns message facts and keyset predicate.
Capability owns trusted scope and archive_latest resolution.
Tool/Runtime owns envelope and model projection budgets.
Evidence/Answer Artifact owns current-run validation and persisted coverage/time facts.
Trace owns append-only execution projection; Agent owns topic semantics, not timestamps.
```

### Evolution / Interview Evidence Map

- Q：为什么最近两天不能直接把几千条塞进模型？
  Evidence：backend temporal-overview spec、real DB projection metrics、Stage 1.7/1.9 amendments。
- Q：怎么证明 summary 覆盖整个时间窗口？
  Evidence：keyset continuation contract、`2699 → 1000+1000+699` smoke、no-gap/no-overlap tests、
  final `retrieval_coverage`。
- Q：partial retrieval 如何避免误导？
  Evidence：`coverage=partial`/`has_more`/`next_cursor`、Artifact limitations、
  `COVERAGE_MISMATCH` fatal boundary 和 Trace per-page facts。
- Q：时间错配如何定位？
  Evidence：`archive_latest` Host resolution、UTC/millisecond assertions、`TIME_RANGE_MISMATCH`
  regression、Artifact/Conversation round-trip。

## resume-benchmark-v1 Measurement Substrate 事实索引（2026-08-30）

> 本节保留 2026-08-30 的 Measurement Substrate / GT-freeze 前 provisional 记录。其
> 185-run 数字、旧版 pair 结果和旧 Failure 描述不代表 Stage 3 final；最终 Development
> Evaluation 只见下一节的 final clean 37×5 结果。

### Recorded facts（所有数字来自真实运行，可由 Evaluation Store + Trace 复查）

- **固定 Snapshot + Environment Lock**：canonical snapshot `snapshot-v1:messages=473236:first=1753011800000:last=1786847688000:sources=14`；`BenchmarkEnvironmentManifest` pin canonical snapshot_id + lexical（unicode61+cjk-bigram-v2, 473236 rows）+ semantic `SemanticIndexIdentity`（Qwen3-Embedding-0.6B/1024d/last_token/normalized + chunker v1 config）；pre-run gate 三查不过整体失败。DatasetSnapshot 契约零改动——同一数据不同 embedding 模型的比较属于 per-variant index identity，v1 不解决。
- **数据集（当前状态）**：calibration 10 case + development 37 case，六类覆盖（exact_lexical 10 / citation_evidence 6 / semantic_paraphrase 8 / context_recovery 3 / temporal_overview 6 / zero_result 4）；**47/47 人工裁决完成（2026-08-31，Accept 26 / Modify 21 / Reject 0），全部 gt finding 与 evidence `provenance.adjudicated=true`**；deterministic audit green（47 cases / 47 adjudicated / 0 error / 0 warning）。exhaustive 声明均由确定性 LIKE 全库扫描/SQL COUNT 证明并机器重扫等值复核；paraphrase/context 如实标 partial（target 集合）。holdout 在系统冻结后才生成（构造时序隔离），当前不存在。
- **Ablation Matrix**：A lexical-only（context_window_limit=0）/ B +semantic（0）/ C +自动 expansion（唯一差异轴）/ C2 +get_message_context / D 七工具 full-system。context 关闭经 `ExecutionOverride.context_window_limit` 在 runtime 工具输入构造点钳制，`context_expansion_override` hard check 验证 Trace 中执行值 ≤ limit。
- **Tier 1 dev 结果（37 case × 5 variant = 185 真实 LLM run，1 rep）**：
  - execution_completed：A 0.595 / B 0.784 / C 0.757 / C2 0.784 / D 0.838（无条件指标；provider_failure 是最大失败源，A=15、D=6）
  - valid_answer：A 0.459 / B 0.730 / C 0.703 / C2 0.784 / D 0.811
  - evidence_recall（条件指标，分母=双方完成的同 case 配对才可比）：B−A paired mean +0.227（11 common，5 up/1 down/5 tie）；C−B −0.017；C2−C −0.046；D−A +0.139（9 common）
  - false_zero_result：A 1.0 / B 1.0 / C 0.963 / C2 1.0 / D 1.0——no_result positive-proof contract 在真实运行中基本杜绝了"没拿到结果就说没有"
  - expected_fact_answer_coverage（answer_text 命中）：B/C 0.93-1.0，A 0.889
  - context_recovery：全线 ≤0.5（n 极小）——回复语境恢复是真实系统性弱点
- **Module-level（确定性，不调 LLM）**：exact_lexical 类 lexical Recall@10=1.0/MRR=1.0（corpus scope），semantic 0.14-0.52；semantic_paraphrase 类 semantic MRR@10 0.25 vs lexical 0.0——semantic 的收益在 paraphrase 类显现，URL 精确谓词 lexical 完胜。semantic 命中按 range（anchor+恢复范围）判定——anchor 精确匹配会系统性低估 semantic。
- **Tier 2（D 系统，llm_assisted_provisional，29 judged/7 skipped）**：Grounded Claim Rate（atomic claim 单位）0.750；Citation Correctness 0.610。citation 存在≠citation 正确：finalizer 只保证可解析，蕴含判定靠 judge+人工抽查升级。
- **Benchmark 抓到的真实 Bug（before/after）**：
  1. `trace_limitations` 收集逐条目 projection-path 标记（628-hit run 产生 511 个"不同"字符串）突破 200 上限 → 归一化下标 + 有界截断（commit eb96e16）。
  2. `AnswerDeltaParseError` 未分类异常逃逸 query 边界 → problem record 记录，benchmark 编排层 per-case 隔离（commit b74c7c3）；生产修复排入 v2。
  3. `eval` CLI 缺 dotenv 加载，真实 provider 无法认证 → 补 `--env-file`（commit eb96e16）。

### GT 人工裁决确立的 contract（2026-08-31，47/47 adjudicated）

- **target URL exhaustive ≠ query corpus exhaustive**：query 问语义类（"这类工具/资源/项目"）而 GT 只是某个 repo URL 的出现集合时，`gt.relevant` 必须标 partial/target——LIKE 只证明该 repo 出现集合完整，不证明语义类 corpus 穷举。6 个 broad-query case（dev-cite-meimei、dev-lexical-agentic-zh/mcp-switch/nanobot-wiki/resume-miner/vibe-game）由 exhaustive 改 partial。audit 同步修正：exact_lexical/citation_evidence 允许 partial（unknown 仍拒绝），且 occurrence set 重扫等值校验不豁免 partial（target 集合仍要求 == alias 全库出现集合）；5 个 regression 锁定。
- **UTC 是全系统唯一正式日历语义**：canonical timestamp 为无时区 epoch 毫秒；Host `format_timestamp_utc`、CLI/TUI 显示、prompt 指引全部只产 UTC 文本；不存在本地时区解释与裸日期解析器（`grep localtime/ZoneInfo` 为空）。因此带日历日期的 zero-result query 必须显式写"按 UTC 时间算"（4 个空窗 case 改写）；audit 对裸日期 zero-result query 出 warning（`zero_result_bare_date_without_utc`），ISO 与年月日两种日期格式都做 UTC 日窗口重扫。
- **temporal behavior contract（人工裁定）**：窗口消息数 ≤ trusted capacity 5000 → 系统应通过 continuation 完整读取窗口后才有资格声明 `complete`（1d=911、2d=2699 → complete/truncated=false）；>5000 → 无法全读时必须如实 `partial`+`truncated=true`（3d/7d/14d/30d）。`coverage=complete` 描述 evidence coverage，不描述"答案听起来够不够像总结"。
- **query↔GT 一致性硬规则**：query 不得引入 GT 消息没有的事实（dev-para-ai-interest 去掉"为了谋生"推断）；exact lexical case 不混入 sender 提取维度（hello-agents/chatlog-alpha/siclaw 改写）；URL occurrence set ≠ sharer set（zenith 改写为"被分享或讨论过"）；"昨天"≠trailing 24h（dev-temporal-1d 改"最近24小时"）、"一个月"≠固定 30d（dev-temporal-30d 改"最近30天"）；context_recovery 的角色方向以"谁直接回答 query"为准（cal-context-ts-docs 的 relevant/required_context 互换：reply 直接回答提问，parent 恢复"这个"=Vercel AI SDK）；required_context 必须真是必要 evidence（ui-skill/mattpocock-1 的 query 改写让另一位群友的回复成为回答所必需）；zero-token 证明不得外推概念类（excalidraw query 收窄为显式提及，token 重扫入 audit）。
- **identity 纪律**：21 个 Modify case `version→2`（run_id 含 case version，旧 185 次 provisional run 保持 v1 身份不被覆盖/删除），两个 suite `version→2` 且 case 引用同步（v1/v2 混合引用经 suite 解析校验无 unresolved）；应用脚本 `scripts/apply_gt_adjudication.py` 幂等且内置落库前复核（reply 链接、零窗口、token 零命中、temporal 计数、出现集合）。

### Interview Defense Notes

- Q：为什么需要固定 Snapshot？→ 相对时间锚 archive_latest（非机器时钟）；Runner 每 case 重解析拒绝漂移；2699/100 的回归固定进 dev set。
- Q：Ground Truth 怎么保证不是编的？→ 只有确定性 predicate（URL/精确 token/窗口 COUNT）可 exhaustive；语义类 query 的 repo-target GT 如实标 partial（target URL exhaustive ≠ corpus exhaustive）；47/47 已人工裁决（2026-08-31，Accept 26 / Modify 21 / Reject 0），review pack 逐条列出验证方式与裁决记录，audit 机器重扫 occurrence set / 窗口计数 / token 零命中。
- Q：人工裁决修改了 GT，旧的 185 次 dev 结果还算数吗？→ 不算最终数字：21 个 Modify case version→2、suite version→2，旧 run 保持 v1 provisional 身份（不删除不覆盖）；正式 dev 数字只能来自 Gate 2/3 freeze 后同 commit 的新鲜 rerun。
- Q：Semantic 到底有没有用？→ 分类型回答：URL 精确谓词 lexical 完胜（Recall@10 1.0 vs ≤0.52）；paraphrase 类 semantic MRR 0.25 vs lexical 0.0；系统级 B−A evidence_recall 配对 +0.227。semantic 不是全面优于 lexical，是互补。
- Q：Context Expansion 有没有用？→ module 层 expansion 能恢复 reply（ui-skill case recovery=1.0）但 bounded 窗口够不着远距离回复；end-to-end context_recovery 全线≤0.5——显式 deepening tool 的使用是当前短板，这是 benchmark 暴露的产品迭代方向，不是遮掩项。
- Q：怎么防止 Evaluation Overfit？→ dev/holdout 时序隔离（holdout 冻结后才存在）；dev 修复全部走通用机制（两个 substrate bug 修复即证据）；holdout 一次定稿不换题。
- Q：数字会不会是调出来的？→ 每个数字可复查：Evaluation Store runs（run_id/trace_id）→ Trace → 逐层 retrieval_calls/evidence_sources 投影；报告 JSON 带 unavailable reasons 与分母；provider_failure 不进条件分母但无条件完成率并列呈现。

## resume-benchmark-v1 Stage 3 Development Evaluation 事实索引（2026-09-04）

### Scope / identity

- **Measured fact**：Human GT 为 47/47 adjudicated（Accept 26 / Modify 21 / Reject 0）；其中 Development 37、calibration 10。calibration 不进入 headline 分母，holdout 未生成、未查看、未评测。
- **Measured fact**：最终 clean rerun 为 `resume-benchmark-dev@v2` 的 37 cases × A/B/C/C2/D 五个 Variant × 1 repetition = **185 runs**；每个 Variant 都有 37 条 EvaluationRun，运行使用真实 `opencode-go / deepseek-v4-flash` provider 和 production `TrivaeApplication.query()` path。
- **Identity**：Gate 2 freeze record 为 `evaluation/snapshots/resume-benchmark-v1-freeze.json`；freeze execution commit 为 `b1f7b78ba802f853f9cd1cbf7433fe07b2f895c1`，freeze metadata commit 为 `e34c6985a734eb2169e0a48e12a512270ca0c353`，冻结后的 quality baseline execution commit 为 `7bac9282701bd0c21b58ce8e5a4f5cc52c87da9f`，根因修复后的 post-fix validation execution commit 为 `f24775099cb2314772c7d409341e8ebceeceac23`。Case identity 使用 ordered versioned Case identities，Variant identity 使用 canonical configuration text；本仓库不使用 cryptographic digest。
- **Environment**：canonical Snapshot 为 `snapshot-v1:messages=473236:first=1753011800000:last=1786847688000:sources=14`，lexical FTS 为 473236 rows，semantic 为 Qwen/Qwen3-Embedding-0.6B、1024d、last_token、normalized、chunker v1。freeze verification 12/12、environment gate 4/4、GT audit 47/47 且 0 error / 0 warning。
- **Evidence**：冻结后的 Tier 1 quality baseline 为 `data/evaluation/benchmark/stage3-final-real/report.json` / `report.md`；post-fix validation 为 `data/evaluation/benchmark/stage3-root-cause-final-clean-real/report.json` / `report.md`，对应独立 Evaluation SQLite。两批 raw records、failures、module packet、freeze verification 和 evaluation database 均保留在 `data/evaluation/benchmark/` 下的对应 artifact。

### Tier 1 final clean results

下表中的 `rate (numerator/denominator; macro; n)` 同时保留加权事实条目 rate 与 case 等权 macro；`n` 是该指标可用的 case 数。`unavailable` 不进入分母，原因保留在机器报告中。

| Variant | completion | valid answer | evidence recall | context recovery | expected fact coverage | false zero / verified zero | coverage / truncation |
|---|---:|---:|---:|---:|---:|---:|---:|
| A lexical-only | .811 (30/37; 0.811; n=37) | .757 (28/37; 0.757; n=37) | .800 (44/55; macro .733; n=20) | .000 (0/3; .000; n=3) | 1.000 (14/14; 1.000; n=14) | 1.000 (26/26) / .000 (0/4) | unavailable（6）；.333 (2/6) |
| B lexical+semantic | .973 (36/37; 0.973; n=37) | .919 (34/37; 0.919; n=37) | .738 (48/65; macro .641; n=26) | .000 (0/2; .000; n=2) | .875 (14/16; .875; n=16) | 1.000 (32/32) / 1.000 (4/4) | unavailable（6）；.500 (3/6) |
| C + auto context | .973 (36/37; 0.973; n=37) | .946 (35/37; .946; n=37) | .742 (49/66; macro .638; n=26) | .333 (1/3; .333; n=3) | .938 (15/16; .938; n=16) | .969 (31/32) / 1.000 (4/4) | unavailable（6）；.500 (3/6) |
| C2 + explicit context tool | 1.000 (37/37; 1.000; n=37) | .973 (36/37; .973; n=37) | .642 (43/67; macro .574; n=27) | .000 (0/3; .000; n=3) | .750 (12/16; .750; n=16) | .970 (32/33) / 1.000 (4/4) | unavailable（6）；.500 (3/6) |
| D full-system | 1.000 (37/37; 1.000; n=37) | 1.000 (37/37; 1.000; n=37) | .731 (49/67; macro .694; n=27) | .000 (0/3; .000; n=3) | .938 (15/16; .938; n=16) | 1.000 (33/33) / 1.000 (4/4) | .667 (4/6)；.667 (4/6) |

`coverage_status_accuracy` 在 A/B/C/C2 因 `get_recent_messages` coverage artifact unavailable 而为 unavailable（各 6 条）；D 有 4/6。Temporal GT 的 1d/2d 是 complete，3d/7d/14d/30d 是 partial；系统保留实际 coverage mismatch，不把它改写为通过。

### Module-level retrieval

- `stage3-module-retrieval.json` 包含 27 个 Development retrieval query，并按 exhaustive→corpus、partial→target 分开报告。
- **Lexical**：corpus Recall@10 = **1.000 (33/33; macro 1.000; n=10)**、Hit@10 = 1.000 (10/10)、MRR@10 = 1.000 (10/10)；target Recall@10 = **.742 (23/31; macro .529; n=17)**、Hit@10 = .529 (9/17)、MRR@10 = .426 (7.25/17)。
- **Semantic**：corpus Recall@10 = **.364 (12/33; macro .327; n=10)**、Hit@10 = .600 (6/10)、MRR@10 = .550 (5.5/10)；target Recall@10 = **.323 (10/31; macro .284; n=17)**、Hit@10 = .412 (7/17)、MRR@10 = .281 (4.778/17)。
- Module packet 的 context-expansion observation 为 0/3 positive recovery for lexical 和 semantic；没有 required context 的 query 仍按 not applicable 处理，不能从该 packet 推导 production context uplift。

### Ablation comparison

- **B−A（semantic uplift）**：execution completion +.162（36/37 vs 30/37）；valid answer +.162（34/37 vs 28/37）；evidence recall paired rate **−.075**、macro **−.079**（paired n=19）。因此 semantic 是互补通道，不是对所有 Development query 的全面提升。
- **C−B（auto context expansion）**：context recovery paired rate **+.500**（paired n=2）；valid answer +.027（35/37 vs 34/37）；evidence recall paired rate 0.000、macro −.023（paired n=25）。样本很小，不能外推总体 uplift。
- **C2−C（explicit `get_message_context`）**：valid answer +.027（36/37 vs 35/37）；context recovery paired rate **−.333**（paired n=3）；evidence recall paired rate **−.091**、macro −.042（paired n=26）。本轮数据没有支持显式 context tool 的稳定 uplift。
- **D** 是 full-system candidate；D 与 A/B/C/C2 的差异是多变量 full-system 差异，不能把 D−A 归因给单个组件。

### Operational measurements

- D latency：mean 23,597 ms，P50 **18,658 ms**，P95 **58,174 ms**；tool calls mean 1.84，P50 2，P95 5；tool rounds mean 1.35，P50 1，P95 3。
- D token usage：input total 961,413（P50 20,150 / P95 91,147），output total 47,215（P50 1,205 / P95 2,144），total tokens 1,008,628（P50 20,821 / P95 92,934）。这些是本地 Snapshot、当前 provider/model 和本次 Development run 的 measured facts，不是生产 SLA。

### Failure-driven iteration and remaining limits

- 首轮真实 185 runs 的 failure artifact 为 112 条：provider_failure 19、coverage_error 17、context_missing 12、zero_result_error 6、retrieval_miss 4、not_observed_within_recorded_depth 54。冻结后的 quality baseline failure artifact 为 108 条：provider_failure 9、coverage_error 18、context_missing 13、answer_generation_error 6、retrieval_miss 3、zero_result_error 2、not_observed_within_recorded_depth 57。post-fix validation 的 failure artifact 为 146 条：provider_failure 114、retrieval_miss 12、coverage_error 7、context_missing 4、ranking_failure 4、answer_generation_error 2、zero_result_error 3。
- 通用修复包含：stream parse/provider transport observation 的终止投影与 `ModelBehaviorError` 边界（`70e1b473...` / `7bac928...`，`tests/test_agent_runtime.py`）；finalization failure 的显式状态/分类及 report 的 denominator、operational、paired comparison 保留（`7bac928...`，`tests/test_benchmark.py`）。targeted artifacts 对 stream A/C 回归通过，对 context/temporal 剩余限制保持显式。
- baseline 的剩余 Failure 主要是 provider/model stochastic output、required context 未被最终 evidence 保留、temporal pagination/coverage 未完整结束，以及 recorded depth 内未观察到 GT relevance。post-fix validation 中 `not_observed_within_recorded_depth=0`；4 个 `ranking_failure` 均有 direct relevant hit 且 rank 14–29，说明分类修复已生效。全批次 114 条 terminal provider failure 中 C/C2/D 占 106 条，集中发生在 `APITimeoutError`/`APIConnectionError` 与 `ROUTER_COMPLETION_TIMEOUT` 时间窗口，C2/D 没有首个 model turn；它们不作为 ablation quality 结论。低 Recall/MRR 本身仍是质量结果，不自动归类为 infrastructure failure；两批均未观察到 `router_tool_selection_error` 或 `evaluation_infrastructure` artifact。

### Tier 2 judge boundary

- D 的 37 条 final run 完成 Tier 2 judge：8 条得到 `benchmark-judge-v1` 的 atomic claim / citation 判定，29 条为显式 `judge_failed`（`EvaluationContractError`），0 条 skipped，0 条人工 adjudicated。
- 8 条 provisional 的 Grounded Claim Rate：case-macro **.278**；事实条目加权 **32/70 = .457**。Citation Correctness：case-macro **.167**；citation 条目加权 **2/10 = .200**。这些数字全部是 **LLM-assisted provisional**，不是 human verified。
- Judge artifact 为 `data/evaluation/benchmark/stage3-final-judge-d.json`，人工复核队列为 `data/evaluation/benchmark/stage3-final-judge-audit-queue.json`。严格 JSON contract 的失败项被保留，未引入宽松 parser、fallback 或静默降级。

### Interview Defense Notes

- Q：为什么 final 只用这 185 条？→ 因为 first run 是 provisional，targeted run 只用于定位；冻结后的 quality baseline 和 post-fix validation 都各自明确为 `resume-benchmark-dev@v2:37x5:repeat=1`，每个 Variant 37 条。前者保留质量 baseline，后者只验证分类与生命周期修复；两份 report metadata 都固定 execution commit、Snapshot、semantic identity 和 Variant configuration。
- Q：为什么 post-fix C2/D 的 completion 很低，是否是新增代码回归？→ Trace 显示失败在 C 后集中出现，错误是 provider `APITimeoutError`/`APIConnectionError`，router 也有 `ROUTER_COMPLETION_TIMEOUT`，C2/D 连首个 model turn 都没有开始；独立 recovery smoke 中 D 可完成而 C2 仍会失败，不能归因到 context tool。benchmark 没有添加 retry/fallback，而是把这段外部 availability window 原样记录。
- Q：这轮真正修了什么？→ 两个可复现的测量层缺陷：旧 failure classifier 把不同 retrieval call 全局合并并把 context call当 direct rank；旧 benchmark CLI 对每个 Variant 分别 `asyncio.run`，导致 provider client 跨 loop 并在退出时触发 `Event loop is closed`。现在按单 call 保留 rank、排除 context，并用同一 async Application context 运行/关闭全套 Variant；576 个测试通过。
- Q：Semantic 是否提升？→ Module 结果显示 lexical 在 exact/corpus predicate 上 Recall@10=1.0，semantic corpus Recall@10=.364；最终 B−A completion/valid answer 上升，但 paired evidence recall 下降，所以结论是互补而非全面提升。
- Q：Context tool 是否已证明有效？→ 没有。C−B 只在 paired n=2 的 context recovery 上出现 +.500，C2−C 为 −.333；样本小且 final evidence 仍有 context missing，不能包装为稳定收益。
- Q：为什么不把 Tier 2 数字写成 citation quality？→ 当前仅 8/37 成功得到 LLM-assisted provisional 判定，且 0 item 人工确认；报告与 audit queue 直接保留未判定和 adjudication 边界。
- Q：Stage 3 是否等于最终 benchmark？→ 不是。本节是 Development benchmark result；Gate 3、holdout generation/evaluation 和 full benchmark 都未执行。
