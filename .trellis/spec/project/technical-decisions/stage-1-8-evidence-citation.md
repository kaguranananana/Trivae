# Stage 1.8：Evidence / Citation 架构决策

> 状态：**Confirmed / Completed（Stage 1.8）**
>
> 本 ADR 冻结 Evidence / Citation 的领域语义、职责边界与失败语义，不冻结 Python class、数据库表、JSON 字段名、SDK structured output、API endpoint 或 UI 组件。业务实现与 Evaluation 参数不属于本阶段；Evidence / Citation Trace 的 conceptual boundary 后由 Stage 1.9 确认，具体 Schema / 实现仍 Pending。

## 0. Architecture Governance

本阶段以 ChatLab commit [`f9b87c00`](https://github.com/ChatLab/ChatLab/commit/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264) 为核验基线。

Trivae 继承 ChatLab 已验证的结构化 Evidence Content Block、稳定消息锚点、随 Assistant Message 持久化、安全 snippet、可点击追溯与显式 incomplete 状态；同时基于 Trivae 已确认的跨 Session 调查、6 个 Tool 边界和用户人工复核需求，明确偏离以下设计：

- 不新增 `retrieve_chat_evidence` / `retrieve_evidence` Tool；
- 不用固定中文计划词、发生词充当 Evidence Judge；
- 不以固定两小时时间聚类定义 Evidence Group；
- 不依赖隐式 CURRENT conversation；
- 不让独立 Evidence Block 与回答中的具体 claim 脱节；
- 不把 Retrieval path 的 `complete / partial / empty / unavailable` 直接当作结论的证据充足度。

代码证据：

- ChatLab Evidence payload 定义见 [`evidence-types.ts`](https://github.com/ChatLab/ChatLab/blob/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264/packages/core/src/ai/evidence-types.ts#L10-L86)；
- Evidence 随 Assistant Message 持久化见 [`chats.ts`](https://github.com/ChatLab/ChatLab/blob/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264/packages/node-runtime/src/ai/chats.ts#L29-L58)；
- Evidence Panel 与消息点击追溯见 [`EvidenceBlock.vue`](https://github.com/ChatLab/ChatLab/blob/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264/src/components/AIChat/chat/EvidenceBlock.vue#L45-L47) 和 [`EvidenceBlock.vue`](https://github.com/ChatLab/ChatLab/blob/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264/src/components/AIChat/chat/EvidenceBlock.vue#L115-L151)；
- 专用 Evidence Tool、固定 Judge、时间分组与 path status 见 [`retrieve-chat-evidence.ts`](https://github.com/ChatLab/ChatLab/blob/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264/packages/tools/src/definitions/retrieve-chat-evidence.ts#L30-L39)、[`retrieve-chat-evidence.ts`](https://github.com/ChatLab/ChatLab/blob/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264/packages/tools/src/definitions/retrieve-chat-evidence.ts#L221-L335) 和 [`retrieve-chat-evidence.ts`](https://github.com/ChatLab/ChatLab/blob/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264/packages/tools/src/definitions/retrieve-chat-evidence.ts#L420-L466)；
- CLI 可读消息标记见 [`chatlab-analyze/SKILL.md`](https://github.com/ChatLab/ChatLab/blob/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264/skills/chatlab-analyze/SKILL.md#L70-L76)。

## 1. Context 与问题定义

Trivae 的目标不是把 Tool Result 原样附在回答后，而是保证：

> 最终回答中的每个聊天事实、结构化统计或证据性推断，都能指向当前 Run 实际取得的 Final Evidence；用户不认可 LLM 总结时，可以通过确定的会话、作者与精确时间打开有限原始上下文，或回到原社交平台查看完整聊天。

必须同时处理五个不同问题：

1. Retrieval Candidate 只是候选，不能自动升级为事实；
2. 一个 finding 可能由多条消息共同支持，也可能同时存在反证；
3. `[1]` 是显示编号，不是稳定来源身份；
4. 消息与统计结果有不同的定位语义，不能互相伪装；
5. 结构可追溯不等于语义正确，Validator 不能冒充自然语言 Judge。

## 2. Decision 1：固定 Evidence 到 Answer 的主数据流

### Decision

第一版主链路固定为：

```text
Current Run Retrieval / Structured Result
        ↓
Evidence Selection / Organization
        ↓
Final Evidence
        ↓
Citation-bound Answer
        ↓
Citation Validation / Trusted Metadata Hydration
        ↓
Validated Answer Artifact
        ↓
Conversation Store commit
```

Retrieval / Tool 负责 Candidate Data、结构化值、取得 provenance 与 execution completeness；Agent Final Synthesis 负责 question-specific criterion、Evidence Selection、finding 组织和回答措辞；Citation Finalizer 负责确定性结构校验、来源解析、Scope 检查和可信展示快照 hydration；UI 只负责渲染与来源复核。

### Reason

该链路延续 Stage 1.3 的 `Candidate Data != Final Evidence` 与 Stage 1.7 的 Thin Runtime 边界。Answer 不得绕过 Final Evidence，直接把候选文本当作已经成立的事实。

### Trade-off

增加一个确定性的 finalization 边界和结构化 Answer Artifact；换取来源真实性、提交原子性与清晰的 Failure Attribution。

### Failure Case

若 LLM 直接引用 Retrieval snippet，chunk 边界、重复候选和缺失上下文会被隐藏，用户无法区分“召回了文本”与“证据足以支持结论”。

## 3. Decision 2：Answer Artifact 是单一结构化事实载体

### Decision

Answer Artifact 在语义上包含：

```text
Answer Artifact
├── Answer Content
├── Claim Citation Bindings
├── Evidence Items[]
│   ├── finding
│   ├── criterion
│   ├── sufficiency
│   ├── sources[]
│   └── limitations[]
└── Answer-level limitations[]
```

以上是 conceptual contract，不冻结字段名、序列化格式或存储 Schema。

### Reason

正文 Citation 与 Evidence Panel 必须共用同一份 Evidence 数据。Renderer 可以把 binding 显示为 `[1]`、脚注或可点击角标，但显示字符串不参与 source identity。

### Trade-off

结构化输出比纯文本复杂；但避免正文编号与 Evidence Panel 分别生成、漂移或失配。

### Failure Case

ChatLab 应用内 Evidence Block 与 CLI `[#message_id]` 是两套局部机制；若 Trivae 继续分开维护，用户仍无法确定哪条证据支撑哪一句结论。

## 4. Decision 3：Citation 是 claim 到 Evidence Item 的绑定

### Decision

Citation 表达 Answer Content 中某个 claim / content unit 到一个或多个 `evidence_id` 的结构化绑定。架构不把脆弱的字符 offset 规定为唯一实现；content block、inline reference token 或 structured output 均可，只要序列化、持久化和渲染后仍保留绑定语义。

所有来自聊天记录、统计或数据库概览的实质性事实与推断必须引用；一般性解释、交互性过渡文字和明确标为建议的方法内容不强制引用。推断必须在措辞上与直接事实区分。

### Reason

Citation 回答“这句话依据哪项 Evidence”，Evidence Item 回答“证据是什么、为何相关、来源在哪、有哪些限制”。二者职责不同但共享数据。

### Trade-off

需要 Answer renderer 理解结构化 binding；换取 claim-level 可审查性，且不会为了“每句都有编号”重复堆叠来源。

### Failure Case

若回答只有底部 Evidence Panel 而没有 claim binding，多结论回答会失去“哪条证据支撑哪句话”的确定关系；若只保存正文 `[1]` 文本，序列化或编辑后又无法可靠解析真正的 Evidence 身份。

## 5. Decision 4：Evidence Item 按 claim / finding 组织

### Decision

一个 Evidence Item 对应一个 claim / finding，可以包含一条或多条 Source。每条 Source 独立标注相对 finding 的关系：

```text
supports      直接支持 finding
contradicts   与 finding 冲突或构成反证
context       提供解释上下文，但单独不足以支持 finding
```

### Reason

技术情报经常形成 `准备尝试 → 实际接入 → 线上反馈 → 回滚 / 保留` 的状态链。一条消息一个 Evidence Item 会打散 criterion 和推理关系；固定时间聚类又会把时间接近误当成语义一致。

### Trade-off

Agent 需要显式组织 finding 与多 Source 关系；换取对多来源、反证和状态变化的准确表达。

### Failure Case

早期消息说“准备采用”，后续消息说“已经回滚”。若只保存 included 消息或按时间组分别展示，最终结论可能忽略关键反证。

## 6. Decision 5：Message Source 使用三层定位语义

### Decision

Message Source 同时保留三类语义：

```text
acquisition provenance
    当前 Run 的 tool_call identity + tool result location / match identity

target locator
    session_id + internal message_id + optional message range

generated-at display snapshot
    ChatSession 可读标识 + 作者 + 精确 Canonical Timestamp
    + 明确 timezone / offset 语义 + 未经 LLM 改写的安全 excerpt
```

平台支持时可保留 platform/source message ID 或 deep-link metadata。Deep link 不可用不影响 Citation 成立，仍须展示足够的人工 Source Locator。

### Reason

provenance 证明模型在当前 Run 实际见过来源；`session_id + message_id` 负责应用内稳定解析；snapshot 负责历史可读与人工查找。三者不能相互替代。

### Trade-off

持久化少量可信展示快照会产生重复数据；但能应对会话名称变化、历史回答回放与平台无法 deep link 的情况。完整的 Message edit / delete / mutation 版本语义仍 Pending。

### Failure Case

只保存 message ID 时，用户无法手工定位；只保存时间和 excerpt 时，系统无法稳定解析；只保存 Tool Result 位置时，历史 Run 的结果可能不可长期访问。

## 7. Decision 6：Semantic Chunk 只作 acquisition provenance

### Decision

Semantic Chunk、embedding score 与 snippet 可以保留为取得路径，但 Final Citation 必须解析到 Canonical Message 或明确 Message Range。Chunk、纯文本 snippet 和显示编号均不是最终事实源。

### Reason

Chunk 是可重建的 Derived Data，边界受索引参数影响；Canonical Message 才是 Stage 1.2 已确认的聊天事实源。

### Failure Case

索引重建后 chunk ID 或文本边界变化，若 Citation 只指向 chunk，历史回答将失去稳定的原始消息锚点。

### Trade-off

Finalizer 需要把 chunk 命中解析到一条或多条 Canonical Message；换取索引重建后仍稳定、且能进入原始聊天复核的 Source Locator。

## 8. Decision 7：Structured Result 使用独立 Source Reference

### Decision

count、aggregate、row、database overview 等结果使用 Structured Result Source：当前 Run 的 Tool Call / Tool Result identity、结果语义位置、value snapshot、已生效 query scope snapshot 与 execution limitations。

具体 locator 是 JSON Pointer、row key、field path 还是其他表达保持 Implementation Pending；Stage 1.8 只冻结“必须能定位当前 Tool Result 中真实存在的值 / row / field”。

### Reason

聚合值可能没有单条消息 lineage。强迫它伪装成 Message Source 会制造虚假的可追溯性。

### Trade-off

UI 和 Validator 需要处理两种 Source 语义；换取统计引用的真实性与未来 row lineage 扩展空间。

### Failure Case

如果把“过去一个月共有 37 条消息”强行绑定到任意一条聊天消息，用户看到的是并不支撑该聚合值的伪来源；如果只保存回答中的数字，未来又无法核对计算范围和 Tool Result。

## 9. Decision 8：criterion 必须 question-specific

### Decision

每个 Evidence Item 持久化 question-specific criterion，描述什么事实足以支持当前 finding。criterion 可以受用户请求、Planner `evidence_needed` 和调查上下文启发，但由 Final Synthesis 针对实际 finding 表达。

第一版不新增 Evidence Agent、独立 LLM Judge、固定关键词 Judge 或跨问题通用 included/excluded 规则。Planner 的 `evidence_needed` 仍只是调查需求，不是 Evidence Object。

### Reason

“准备试试”“实际接入”“上线稳定”“最终回滚”在不同问题中的意义不同，固定词表无法表达采用、反对、条件性建议和状态变化。

### Trade-off

语义质量依赖 Prompt 与 Stage 1.10 Evaluation；但不会用机械规则制造虚假的确定性。

### Failure Case

固定“准备 / 已发生”词表会把技术讨论中的否定、回滚、条件性采用和非中文表达错误分类，并把 Judge 的领域局限隐藏成确定结论。

## 10. Decision 9：Evidence sufficiency 与 execution completeness 分轴表达

### Decision

Evidence Item 的充足度为：

```text
sufficient    当前来源足以按 criterion 支撑 finding
partial       有相关支持，但仍有明确缺口或限制
insufficient  当前来源不足以建立 finding
```

不引入未经校准的数值 confidence。Tool 的 `partial / coverage / truncated / unavailable` 原样保留为 limitations，不折叠进 sufficiency。

### Reason

Retrieval 可以完整执行但证据不足；也可以 partial，但已取得来源足以支持一个窄 claim。两者回答的是不同问题。

### Failure Case

zero hits 只证明当前查询无命中，不自动证明事实不存在；Semantic Index 全局 coverage 也不能替代具体 query scope 的完整性。

### Trade-off

Answer Artifact 与 UI 需要同时呈现两种状态；换取用户能够区分“查询执行不完整”和“当前证据不足”，避免用一个模糊的 `partial` 掩盖根因。

## 11. Decision 10：Citation Validator 是确定性提交边界

### Decision

Citation Validator / Finalizer 至少验证：

1. binding 引用的 `evidence_id` 存在且唯一；
2. 所有 Source 来自当前 Run 实际可见的 Tool Result；
3. Message Source 的 Session / Message locator 与 Tool Result 一致，并可在 Data Access Scope 内解析；
4. Structured Result locator 指向当前 Tool Result 中真实存在的值 / row / field；
5. 会话、作者、时间和 excerpt 等必需 snapshot 从可信 Tool Result / Canonical projection hydrate，而不是接受模型自造元数据；
6. Answer Artifact 满足 bounded conceptual contract。

Validator **不验证**自然语言 claim 是否被来源语义蕴含、criterion 是否最佳，也不证明 Retrieval 召回了全部真实来源。

### Reason

确定性检查适合阻止虚构 ID、越权来源和不可解析 locator；语义蕴含必须交给 Prompt、人工复核与 Stage 1.10 Evaluation，不能伪装成结构校验能力。

### Trade-off

结构正确的错误总结仍可能通过；但错误可追溯到 Evidence Selection / Answer Generation，而不会被错误归因给 Validator。

### Failure Case

若把结构 Validator 描述为语义正确性 Judge，一个真实存在但与 claim 无关的消息也会被错误宣称“已验证”；反过来，若完全不做确定性校验，模型自造 ID 和越权 locator 会进入持久化历史。

## 12. Decision 11：invalid Citation 显式终止 Finalization

### Decision

invalid / unresolved Citation 使 Answer Finalization 显式失败。第一版不静默删除编号、不提交无引用版本、不自动改引“最相似”的其他消息，也不新增 citation repair retry。

### Reason

静默丢引用会把“可追溯回答生成失败”伪装成正常无引用回答；自动换来源可能改变结论依据，属于新的语义决策而非格式修复。

### Trade-off

格式错误会降低单次回答可用性；换取错误透明与不提交伪证据。若 Stage 1.10 证明某类格式性错误高频、可恢复且 bounded correction 可靠，再以真实 Failure Case 重开。

### Failure Case

模型引用不存在的 message，系统若静默移除 `[1]` 并继续提交，用户会得到一条看似完整、实际已失去依据的回答，而且 Citation 生成故障不会进入可观测的失败路径。

## 13. Decision 12：验证通过后与 Assistant Message 原子持久化

### Decision

Answer Content、Citation Bindings、Evidence Items、Source snapshots 与 limitations 随最终 Assistant Message 一起持久化。只有验证通过的 Answer Artifact 才能按 Stage 1.7 的 `COMPLETED` 边界提交。

历史 Evidence 是“当时回答依据”的可回放记录，不是未来 Run 的 fresh evidence。Follow-up 询问聊天事实时必须重新通过当前数据库 Tool 取得来源；旧 AI Reply、旧 Evidence Panel 与压缩摘要只用于理解对话意图。Regenerate 生成新的 Answer Artifact，不直接复用旧 Citation 作为当前事实源。

### Reason

Conversation Store 是 AI 历史事实源，但 Canonical Message Store 才是聊天事实源。把二者混为一谈会让旧总结在后续回答中循环自证。

### Failure Case

若后续 Run 引用旧 AI summary 而不重新查询，消息已更正、索引覆盖变化或原结论错误都无法被发现。

### Trade-off

Follow-up 事实问题需要重新调用 Tool，产生额外 latency / token；换取当前数据库事实与旧回答记录之间的清晰边界，避免旧总结循环自证。

## 14. Decision 13：应用内只提供 bounded original-context review

### Decision

点击 Message Citation 后：

1. 通过 `session_id + message_id` 打开 Canonical Chat Record；
2. 将被引消息居中并高亮；
3. 只加载有限前后原始上下文；
4. 展示未经 LLM 改写、且遵循授权与隐私策略的 Canonical Message；
5. 平台支持时提供 deep link；否则展示会话、作者和精确时间供人工定位。

Trivae 不在该视图加载全量聊天。完整上下文由用户回到原社交平台查看。bounded context 的具体消息数量保持 Pending Evaluation / UI design。

### Reason

用户明确需要在不认可总结时复核原样聊天，但全量会话已有原社交平台承载。有限上下文同时降低断章取义与重复构建完整聊天浏览器的成本。

### Trade-off

有限窗口可能仍不足以解释长链讨论；用户可继续使用平台定位查看完整记录，窗口大小由真实 workload 校准。

### Failure Case

只显示孤立被引消息容易断章取义；在 Trivae 内加载整场聊天又会复制原平台能力并扩大数据、性能和隐私边界，因此第一版明确选择有限上下文与平台定位的组合。

## 15. Decision 14：Evidence-aware stopping 只作 Agent guidance

### Decision

第一版不增加 Runtime-owned Evidence State Machine 或 machine-enforced completion gate：

- criterion 与 success criteria 可以作为 Agent 调查指导；
- 主要 finding 达到 sufficient 时，Agent 可以自然结束 Tool 调查；
- Stage 1.7 Tool Budget 仍是唯一 Trivae-owned hard investigation bound；
- Budget 耗尽后只使用已取得的 Evidence 进行 graceful final synthesis，并显式标记 partial / insufficient；
- SDK absolute limit 仍是 Runtime Failure，不伪装成 Evidence partial。

### Reason

当前没有标注数据证明 minimum-citation gate、coverage gate 或自动继续调查能提高正确性且不会制造无效 Tool 循环。

### Trade-off

第一版停止时机主要依赖 Agent 判断；换取不提前引入未经验证的状态机和参数复杂度。

### Failure Case

若 Runtime 仅因 Citation 数量不足就机械继续调用 Tool，可能在证据已经充分时制造无效循环；若把 SDK absolute limit 当作 `partial`，又会掩盖真实 Runtime Failure。

## 16. Ownership Summary

| Layer | Owns | Does not own |
| --- | --- | --- |
| Retrieval / Tool | Candidate Data、Structured Result、provenance、execution completeness | Final Evidence 判断、claim binding |
| Agent Final Synthesis | criterion 应用、Evidence Selection、finding 组织、回答措辞 | 可信 locator hydration、来源存在性和 Scope 校验 |
| Citation Validator / Finalizer | 结构有效性、current-run provenance、locator resolution、Data Access Scope、可信 snapshot hydration | semantic entailment、LLM truth judgment |
| Conversation Store | validated Answer Artifact 持久化与历史回放 | 把旧 Evidence 当作当前数据库的新鲜证据 |
| UI / Renderer | inline numbering、Evidence Panel、bounded source review、可选平台入口 | 重定义 Evidence / Citation identity |

Citation Finalizer 属于 Answer Generation 的确定性提交边界，不是 Agent-facing Tool、Evidence Agent、Judge 或 Runtime-owned Evidence State Machine。

## 17. Confirmed Decisions

| # | Decision | Confirmed 语义 |
| --- | --- | --- |
| 1 | Evidence 主链路 | `Retrieval / Structured Result → Evidence Selection / Organization → Final Evidence → Citation-bound Answer` |
| 2 | 单一 Answer Artifact | 正文 Citation 与 Evidence Panel 共用结构化 Evidence |
| 3 | Claim-level Citation | claim / content unit 绑定一个或多个 Evidence Item；显示编号不是身份 |
| 4 | Finding-oriented Evidence | Evidence Item 按 claim / finding 组织，可包含多 Source |
| 5 | Source relation | `supports / contradicts / context` |
| 6 | Message Source | current-run provenance + `session_id / message_id` locator + 可信人工复核 snapshot |
| 7 | Chunk 边界 | Semantic Chunk 只作 acquisition provenance，最终定位 Canonical Message / Range |
| 8 | Structured Result Source | 独立 locator / value / query scope snapshot，不伪装成 Message Source |
| 9 | Question-specific criterion | 与 Evidence Item 持久化，不采用固定关键词 Judge |
| 10 | 双轴状态 | `sufficient / partial / insufficient` 与 Tool completeness limitations 分开 |
| 11 | Deterministic Validator | 校验引用真实性、可解析性和 Scope，不宣称语义正确性 |
| 12 | Failure transparency | invalid / unresolved Citation 使 Finalization 失败，不 silent drop / auto repair |
| 13 | Persistence / replay | validated Artifact 随 Assistant Message 提交；旧 Evidence 不作 fresh evidence |
| 14 | Bounded source review | 应用内只看有限原始上下文，全量聊天回原平台 |
| 15 | Evidence-aware stopping | 仅 Agent guidance；hard bound 仍是 Tool Budget |
| 16 | 明确不引入 | `retrieve_evidence` Tool、Evidence Agent、固定关键词 Judge、固定时间 Evidence 分组、Runtime Evidence State Machine、无依据 retry / fallback |

## 18. Deferred

### Implementation Pending

- Python / JSON Schema、数据库表、SDK structured output 与 package layout；
- Claim binding 的具体 token / content block 序列化；
- Structured Result row / value locator 的具体表达；
- Canonical timestamp 的存储类型与 UI timezone formatting；
- Conversation transaction / Answer Artifact commit Schema；
- bounded context 的消息数量、Citation 密度与 Evidence Item 上限；
- Message edit / delete / mutation 后 snapshot 与 current value 的 diff 体验；
- 平台 deep link 的具体支持矩阵。

### Stage 1.9 已解除的 Pending

- Evidence Selection、Citation validation、Answer finalization 的 Trace family、Failure Attribution、Error Code ownership、storage / privacy / retention 原则与 operational metric 维度已确认；
- Tool completeness / query-scope coverage 已确认以授权 effective scope 为基准，并与 truncation / availability / Evidence sufficiency 分轴；
- 具体 Python / JSON Schema、事件名、Error Code 枚举、Collector / Store backend 与采集实现保持 Implementation Pending。

### Stage 1.10 Pending

- semantic entailment、criterion quality、sufficiency、citation precision / recall 的 Evaluation；
- minimum-citation gate、coverage gate、citation repair 与 Evidence-aware stopping 参数；
- bounded context、Citation 密度和 Answer Correctness 的 workload 校准。

## 19. Failure Cases

| Failure Case | 第一版处理 |
| --- | --- |
| LLM 引用不存在的 message / result | Citation validation 失败，Answer 不提交 |
| Semantic coverage partial 但找到相关消息 | limitation 原样保留，sufficiency 单独判断 |
| Tool zero hits | 只说明当前查询无命中，结合 scope / coverage 保守作答 |
| 只有“准备采用”，没有实际采用 | 按 question-specific criterion 标为 partial / insufficient，不硬编码词表 |
| 后续消息推翻早期结论 | 同一 Evidence Item 同时保留 supports / contradicts |
| 用户不认可 LLM 总结 | 通过会话、作者、精确时间和 bounded Canonical context 人工复核 |
| 原平台不支持 deep link | 展示人工 Source Locator，不构造虚假链接 |
| Aggregate 无单条消息 lineage | 引用 Structured Result snapshot，不伪装成 Message Source |
| Citation locator 不可解析或越权 | Finalization 显式失败，不静默删除或自动替换 |
| Tool Budget 耗尽 | 仅基于已取得来源 final synthesis，并标明 partial / insufficient |

## 20. Reopen Conditions

只有以下新证据可以触发重开，并必须记录 Reopen Reason：

- Evaluation 证明 claim-level binding 成本显著高于可追溯收益；
- invalid Citation 高频出现，且某种 bounded correction 能稳定恢复而不改变来源语义；
- 真实业务必须引用附件、图片、forward chain 等非 Message Source；
- Structured Result 必须提供 row lineage 才能满足审计需求；
- 用户实际需要应用内全量聊天，原平台定位无法满足复核；
- machine-enforced Evidence gate 明显改善 correctness，且不会制造无效 Tool 循环；
- Canonical Message mutation 使当前 snapshot / locator 语义无法满足审计。

“通常 Citation 系统更复杂”“以后可能有用”“可以多加一个 Agent / Tool”不构成 Reopen Reason。

## 21. Validation / Regression Contract

当前仓库没有业务代码，本阶段不伪造实现测试。实现阶段至少应验证：

```text
所有数据性 claim 均能解析到存在的 Evidence Item
inline Citation 与 Evidence Panel 渲染同一份 Artifact
Message Source 来自 current Run，并在 Data Access Scope 内解析到正确 Session / Message
Structured Result locator 指向真实 Tool Result 值，且不会伪装成 Message Source
可信 hydration 覆盖会话、作者、精确时间与未改写 excerpt
Semantic Chunk Citation 最终解析到 Canonical Message / Range
supports / contradicts / context 与 sufficiency / completeness 两轴不会混用
invalid / unresolved Citation 阻止 Assistant Message 提交
历史 Evidence 可回放，但 follow-up 事实问题重新调用当前数据库 Tool
bounded source viewer 高亮被引消息且不加载全量会话
Tool Budget 耗尽后的 final synthesis 只使用已取得来源并显式标记限制
不存在 retrieve_evidence Tool、固定关键词 Judge、Evidence Agent 或 Runtime Evidence State Machine
```
