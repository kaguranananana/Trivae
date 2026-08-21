# Design: Stage 1.8 Evidence / Citation

## 0. Architecture Governance

本设计遵循项目级 ChatLab Reference Implementation 原则。ChatLab `f9b87c00` 是已核验 baseline：继承其结构化 Evidence Block、消息锚点、持久化、可点击追溯和显式 incomplete 状态；偏离其专用 `retrieve_chat_evidence` Tool、固定中文关键词 Judge、固定两小时时间聚类、隐式当前 Session、正文与 Evidence Block 脱节等设计。

Stage 1.8 冻结领域语义与职责边界，不冻结 Python class、数据库表、JSON 字段名、SDK output type 或 UI 组件。

## 1. Problem Restatement

Evidence / Citation 要解决的不是“把 Tool Result 显示出来”，而是：

> 最终回答中的每个聊天事实或证据性推断，都能指出它依据的 Final Evidence；用户能够检查该 Evidence，并从确定的位置回到未经 LLM 改写的原始聊天。

基本事实：

1. Retrieval Candidate 不等于可支撑结论的 Final Evidence。
2. 一条结论可能需要多条消息或结构化结果共同支持。
3. 显示编号不是来源身份；稳定 Message / Tool Result provenance 才是。
4. 结构校验可以阻止虚构引用 ID，不能替代语义判断。
5. “检索执行完整”与“证据足以支持结论”是不同问题。
6. 用户需要有限应用内复核，但全量上下文继续由原社交平台承载。

## 2. Ownership 与数据流

```text
Current Run Tool Calls / Tool Results
        │
        ├── Message Candidates + bounded context
        └── Structured Results
        │
        ▼
Agent Final Synthesis
        ├── define / apply question-specific criteria
        ├── select Final Evidence
        ├── organize Evidence Items by claim / finding
        └── produce Answer + Citation bindings
        │
        ▼
Citation Validation / Trusted Metadata Hydration
        ├── validate current-run provenance
        ├── validate source locators and scope
        └── hydrate source time / author / session snapshot
        │
        ▼
Validated Answer Artifact
        ├── answer content + claim citations
        ├── evidence items
        └── limitations
        │
        ▼
Conversation Store commit
        │
        ├── inline Citation rendering
        ├── Evidence Panel
        └── bounded original-context viewer / platform locator
```

### Ownership

| Layer | Owns | Does not own |
| --- | --- | --- |
| Retrieval / Tool | candidates, structured values, provenance, execution completeness | Final Evidence judgment, claim binding |
| Agent Final Synthesis | criteria application, evidence selection, finding organization, answer wording | trusted locator hydration, source existence validation |
| Citation Validator / Finalizer | structural validity, current-run provenance, locator resolution, scope enforcement, trusted snapshot hydration | semantic entailment or LLM truth judgment |
| Conversation Store | validated Answer Artifact persistence and replay | treating old Evidence as fresh current-database evidence |
| UI / Renderer | inline numbering, panel, source viewer, optional platform link | redefining Evidence or Citation identity |

Citation Finalizer 是 Answer Generation 的确定性提交边界，不是新的 Agent、Tool、Judge 或 Runtime-owned Evidence State Machine。

## 3. Conceptual Domain Model

以下名称表达语义角色，不冻结实现字段名。

```text
Answer Artifact
├── Answer Content
│   ├── text / content blocks
│   └── Claim Citation Bindings
├── Evidence Items[]
│   ├── evidence_id                 # Assistant Message 内稳定
│   ├── finding                     # 被支撑 / 反驳 / 无法确认的结论
│   ├── criterion                   # question-specific 判定标准
│   ├── sufficiency                 # sufficient | partial | insufficient
│   ├── sources[]
│   │   ├── relation                # supports | contradicts | context
│   │   └── source_ref              # Message | Structured Result
│   └── limitations[]               # 与本 finding 有关的 partial / coverage / truncated 等
└── Answer-level limitations[]      # 跨 finding 的数据范围或能力限制
```

### 3.1 Claim Citation Binding

Citation 是 Answer Content 中某个 claim / span 到一个或多个 `evidence_id` 的结构化绑定。Renderer 可显示为 `[1]`、脚注或可点击角标；显示字符串不进入 source identity。

不使用脆弱的“字符 offset 是唯一身份”作为架构契约。实现可采用 content block / inline reference token / structured output，只要编辑、序列化和渲染后仍保留绑定语义。

### 3.2 Evidence Item

Evidence Item 对应一个 claim / finding，而不是一条原始消息。原因是许多技术情报结论由状态链形成：

```text
准备尝试 → 实际接入 → 线上反馈 → 回滚 / 保留
```

一个 Evidence Item 可以包含多条 Source；每条 Source 独立记录 relation 与 locator。时间接近可以帮助 Retrieval，但不定义 Evidence Item 的语义边界。

### 3.3 Message Source Reference

```text
Message Source
├── acquisition provenance
│   ├── tool_call identity
│   └── tool result location / match identity
├── target locator
│   ├── session_id
│   ├── internal message_id
│   └── optional message range
├── generated-at display snapshot
│   ├── session display
│   ├── author display
│   ├── exact canonical timestamp + timezone / offset semantics
│   └── safe, non-LLM-rewritten excerpt
└── optional platform locator
    └── platform/source message id or supported deep link metadata
```

`tool_call identity` 证明模型在当前 Run 确实取得过该来源；`session_id + message_id` 负责应用内稳定解析；display snapshot 负责历史可读和人工定位。三者职责不同，不能只保留其中一个。

Semantic Chunk / embedding score 可保留为 acquisition provenance，但不能成为最终 source target。最终引用必须落到 Canonical Message / Message Range。

### 3.4 Structured Result Source Reference

```text
Structured Result Source
├── tool_call / tool_result identity
├── result locator               # scalar / row / field 的语义位置
├── value snapshot
├── query scope snapshot         # session / time / member 等已生效范围
└── execution limitations
```

Structured Result 适用于 count、aggregate、records、database overview 等确定性结果。它不伪装成 Message Source；若 Tool 未来提供 row lineage，可追加 message provenance，但不作为 v1 架构前提。

## 4. Criteria、Relation 与 Status

### 4.1 Question-specific Criterion

criterion 描述“什么事实足以支持当前 finding”。它可以受用户请求、Planner `evidence_needed` 与当前调查上下文启发，但由 Final Synthesis 针对实际 finding 表达并持久化。

第一版不新增独立 Evidence Judge 调用，也不使用固定关键词或跨问题通用状态规则。

### 4.2 Source Relation

```text
supports      直接支持 finding
contradicts   与 finding 冲突或构成反证
context       提供解释上下文，但单独不足以支持 finding
```

这比 ChatLab 的 `included / excluded / uncertain` 更适合技术情报；“反对”“回滚”“条件性采用”等消息不是应被简单 excluded 的噪声，而可能是关键反证。

### 4.3 Evidence Sufficiency

```text
sufficient    当前可用来源足以按 criterion 支撑该 finding
partial       有相关支持，但仍存在明确缺口或限制
insufficient  当前来源不足以建立该 finding
```

不引入数值 confidence。没有真实标注与校准时，`0.82` 不比定性状态更可靠。

### 4.4 Retrieval / Execution Completeness

Tool 的 `partial / coverage / truncated / unavailable` 原样保留为 limitations，不折叠进 sufficiency：

- Retrieval 可以完整执行，但证据仍不足；
- Retrieval 可以 partial，但已取得来源仍足以支持一个窄 claim；
- zero hits 是一次查询结果，不自动证明事实不存在；
- structured count 在明确完整 scope 上可能是充分证据，但不能借用 Semantic Index 的全局 coverage。

## 5. Answer Citation Policy

必须 Citation：

- 聊天中谁说过什么、何时发生、是否出现某话题；
- 统计、排行、数量、趋势、关系或观点变化；
- 基于聊天消息形成的事实判断与推断；
- 对“无法确认”的数据性说明所依据的查询范围与限制。

不强制 Citation：

- 不依赖聊天数据的一般解释；
- 交互性过渡文字；
- 明确标为建议、方法或后续操作的内容。

推断必须绑定 Evidence 并在措辞上与直接事实区分。Citation 数量保持代表性与可审查性，不为了“每句都有编号”重复引用同一 Evidence。

## 6. Validation 与 Failure Semantics

Citation Validator / Finalizer 至少验证：

1. Answer 中所有 citation binding 引用的 `evidence_id` 存在且唯一；
2. Evidence Source 来自当前 Run 的实际 Tool Result；
3. Message Source 的 session / message locator 与 Tool Result 一致并可在当前 Data Access Scope 解析；
4. Structured Result locator 指向当前 Tool Result 中真实存在的值 / row / field；
5. 必需 display snapshot 由可信 Tool Result / Canonical projection hydrate，而不是接受模型虚构的时间、作者或会话；
6. Citation / Evidence 结构满足 bounded contract。

Validator 不验证：

- 自然语言 claim 是否被 source 语义蕴含；
- criterion 是否是最佳业务判定标准；
- Retrieval 是否召回了所有真实来源。

上述语义质量进入 Stage 1.10 Evaluation 与 Failure Attribution。

第一版 invalid / unresolved Citation 使 Answer Finalization 显式失败；不静默删除编号、不提交无引用版本、不自动引用“最相似”的其他消息，也不新增 citation repair retry。若 Evaluation 证明格式性 invalid citation 是高频可恢复 Failure Case，再带触发条件和测试重开 bounded correction。

## 7. Persistence 与 Replay

- Answer Content、Citation Bindings、Evidence Items、Source snapshot 与 limitations 随 Assistant Message 一起持久化。
- 只有 Citation validation 通过后，Assistant Message 才按 Stage 1.7 `COMPLETED` 提交边界持久化。
- 历史 Evidence 可继续渲染和点击；它是“当时回答依据”的记录，不是后续 Run 的 fresh evidence。
- Follow-up 若询问聊天事实，必须重新通过当前数据库 Tool 获取；旧 AI Reply、旧 Evidence Panel 和压缩摘要只用于理解对话意图。
- Regenerate 生成新的 Answer Artifact 与 Evidence binding，不直接复用旧 Citation 作为当前事实来源。

## 8. User Experience / Source Review

正文示例：

```text
团队在 8 月中旬已经把 OpenAI Agents SDK 接入项目，随后反馈运行稳定。[1]
```

Evidence Panel 示例：

```text
[1] 实际采用 OpenAI Agents SDK
Criterion: 必须有实际接入 / 运行证据，不能只出现“准备试试”
Sufficiency: sufficient

Sources
├── supports · 技术群 · 张三 · 2026-08-18 14:32:18 +08:00
│   “SDK 已经接进项目，今天把主链路跑通了。”
└── supports · 技术群 · 李四 · 2026-08-25 10:16:04 +08:00
    “线上跑了一周，目前比之前的方案好排查。”

查看有限原始上下文 / 在原平台中定位
```

点击 Message Source：

1. 通过 `session_id + message_id` 打开 Canonical Chat Record；
2. 被引消息居中并明确高亮；
3. 只加载 bounded surrounding context；
4. 展示未经 LLM 改写、但仍遵循授权与隐私策略的 Canonical Message；
5. 平台支持时提供 deep link；不支持时提供会话、作者、精确时间等人工 locator。

不在 Trivae 中加载全量聊天。用户需要完整上下文时回到原社交平台。

## 9. Evidence-aware Stopping

第一版不增加 machine-enforced Evidence State Machine：

- Agent instructions / validated plan guidance 可以描述 criterion 与 success criteria；
- Agent 在认为主要 finding 已达到 sufficient 时自然结束 Tool 调查；
- Stage 1.7 Tool Budget 仍是唯一 Trivae-owned hard investigation bound；
- Budget 耗尽后进入 graceful final synthesis，只使用已取得来源，并把相关 finding 标为 partial / insufficient；
- SDK absolute limit 撞到仍是 Runtime Failure，不伪装成 Evidence partial。

是否需要 minimum-citation gate、coverage gate、自动继续调查或 bounded repair，由 Stage 1.10 真实 workload 与 Evaluation 决定。

## 10. ChatLab Inheritance / Deviation

| ChatLab 设计 | Trivae 决策 |
| --- | --- |
| 结构化 Evidence Content Block | 继承；作为 Answer Artifact 的 Evidence Panel 视图 |
| messageId 点击回原消息 | 继承并扩展为显式 session + message locator、精确时间和 bounded context |
| 保存安全 snippet，不保存 raw dump | 继承；excerpt 不是 source identity |
| `complete / partial / empty / unavailable` | 保留显式 incomplete 原则，但拆分 Tool completeness 与 Evidence sufficiency |
| 独立 `retrieve_chat_evidence` Tool | 不继承；违反 Stage 1.4 Tool / Capability 边界 |
| 固定中文计划词 / 发生词 Judge | 不继承；采用 question-specific criterion |
| `included / excluded / uncertain` | 不继承为通用模型；采用 source relation + finding sufficiency |
| 固定两小时时间聚类、每组最多 5 条 | 不继承；Evidence Item 按 claim / finding 组织 |
| Evidence Block 与正文无 claim binding | 改进为同一结构的 inline Citation + Evidence Panel |
| CURRENT conversation 隐式 session | 不继承；Source locator 显式 session identity |
| CLI `[#id]` marker | 继承“可读短标记”体验，不把显示编号当 source identity |

## 11. Failure Cases 与 Reopen Conditions

| Failure Case | 第一版处理 |
| --- | --- |
| LLM 引用不存在的 message / result | Citation validation 失败，Answer 不提交 |
| 找到若干消息但 Semantic coverage partial | 保留 limitation；sufficiency 单独判断 |
| Tool zero hits | 只证明当前查询无命中；结合 scope / coverage 保守作答 |
| 只有“准备采用”，没有“已经采用” | criterion 下通常 partial / insufficient，不硬编码关键词 |
| 后续消息推翻早期结论 | 同一 Evidence Item 可同时包含 supports / contradicts |
| 用户不认可 LLM 总结 | 通过精确时间、会话、作者与 bounded raw context 人工复核 |
| 原平台不支持 deep link | 展示人工 Source Locator，不伪造链接 |
| Structured aggregate 无单条消息 lineage | Citation 指向 Structured Result snapshot，不伪装成 Message Source |

以下证据可触发 Reopen：

- Evaluation 证明 claim-level binding 成本显著高于可追溯收益；
- invalid citation 成为高频且可通过 bounded correction 可靠恢复；
- 真实业务必须引用附件、图片、forward chain 等非 Message Source；
- Structured Result 需要 row lineage 才能满足审计；
- 用户确实需要应用内全量聊天，而原平台定位不足；
- machine-enforced evidence gate 显著改善 correctness 且不会制造无效 Tool 循环。

## 12. Deferred

- 最终 Python / JSON Schema、SDK structured output 与 package layout
- Citation inline token / content block 的具体序列化
- Structured Result row / value locator 的具体表达
- Canonical timestamp 数据库类型与 UI timezone formatting
- bounded context 消息数、Citation 密度与 Evidence Item 数量上限
- Message edit / delete / mutation 后的 snapshot/current diff UX
- Trace Event / metrics / storage（Stage 1.9）
- semantic entailment、sufficiency、citation precision / recall Evaluation（Stage 1.10）
- citation repair、minimum-citation gate 与 Evidence-aware stopping 参数（Stage 1.10）
