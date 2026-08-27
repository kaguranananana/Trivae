# Stage 1.4: Tool / Capability Layer Decisions

> 状态：**Confirmed（Stage 1.4）**
>
> 本文记录 Stage 1.4 已确认的 Tool / Capability Layer 架构决策、理由、边界与重新打开条件。Stage 1.4 已完成；具体经验参数仍由 Evaluation 校准，但不影响本阶段架构状态。

---

## 0. Architecture Governance

Stage 1.4 遵循项目级 [Architecture Principle: ChatLab as Reference Implementation](../architecture.md#architecture-principle-chatlab-as-reference-implementation)。该原则适用于整个 Trivae 架构；本 ADR 从下一节开始记录 Tool / Capability Layer 的具体决策、理由、边界、Trade-off、Failure Case 与重新打开条件，不在此重复定义项目级治理原则。

## 1. Tool 与 Capability 分离

**Context**：Agent Runtime 与底层 Retrieval / Data Layer 之间需要一个稳定边界。核心业务能力不能绑定 OpenAI Agents SDK 等具体 Runtime，Agent 也不应直接操作底层实现。

**Decision**：

- **Capability** 是 Trivae 自身的业务能力，例如 Lexical Retrieval、Semantic Retrieval、Context Expansion、Structured Retrieval、Identity / Membership Lookup；不依赖具体 Agent Runtime / SDK。
- **Tool** 是 Agent-facing 接口，负责参数校验、调用一个或多个 Capability，并将结果标准化为统一契约。

**Result**：

```text
Agent Runtime → Tool Layer → Capability Layer → Retrieval / Canonical Data / Index
```

**Reason**：Capability 可以独立测试、复用和演进；Tool 专注于模型易理解的交互契约以及 Runtime 适配。

**Trade-off**：增加一层 Tool → Capability 映射，换取业务能力与 Agent Runtime 解耦。

## 2. 一个 Tool 可以组合多个 Capability

**Context**：Agent-facing API 的目标是让模型容易选择和正确调用，不是逐一展示内部模块边界。

**Problem**：若把每个内部步骤都暴露成 Tool，Agent 会反复执行 `search → 裸 hit → expand → 阅读`，产生机械 Tool Call、额外延迟和编排错误。

**Decision**：一个 Tool 可以组合多个 Capability，不要求 Tool 与 Capability 一一对应。Agent-facing API 优先考虑模型是否容易理解、是否容易正确调用、是否能减少机械 Tool Call。

**Result**：`lexical_search` 和 `semantic_search` 均可在一次调用中组合 Retrieval 与 bounded Context Expansion。

**Trade-off**：Tool 封装需要维护组合逻辑；内部 Capability 仍必须独立可观测，不能因组合而失去 Failure Attribution。

## 3. 第一版 Agent-facing Tool Surface

**Decision**：第一版暴露以下 6 个核心 Tool：

```text
lexical_search
semantic_search
get_message_context
find_members
get_schema
execute_sql
```

整体映射：

```text
Agent Runtime
│
├── lexical_search
│      ├── Lexical Retrieval
│      └── bounded Context Expansion
│
├── semantic_search
│      ├── Semantic Retrieval
│      └── bounded Context Recovery
│
├── get_message_context
│      └── Context Expansion
│
├── find_members
│      └── Identity / Membership Lookup
│
├── get_schema
│      └── SQLite Schema Inspection
│
└── execute_sql
       └── Read-only Structured Retrieval
```

**Reason**：这组 Tool 覆盖字面检索、语义检索、深度上下文恢复、成员查询和确定性结构化查询，同时保持 Tool Surface 足够小。

**Trade-off**：第一版不追求把每个内部 Capability 或每类分析动作都独立暴露；新增 Tool 必须由真实 Evaluation 或 Failure Case 驱动。

## 4. Message Search 默认自动补充 bounded context

**Context**：高噪声群聊中的单条消息通常语义不完整。裸命中不足以让 Agent 判断该候选是否值得继续调查。

**Decision**：`lexical_search` 与 `semantic_search` 默认进行 bounded context expansion / recovery，Search Result 默认包含命中与有限局部上下文。

```text
message retrieval
      ↓
raw hit / child chunk hit
      ↓
automatic bounded context expansion
      ↓
hit + local context
```

自动扩展必须 bounded，不得演变为命中后返回整个 conversation 或很长时间范围内的全部聊天。具体前后消息数、token budget、时间窗口、reply chain 与 Parent 范围由 Evaluation 决定，不写成当前架构事实。

**Reason**：小范围邻近上下文在群聊中信息增益高，并且几乎每个候选判断都需要；合并该高频步骤可以减少机械 Tool Call。

**Trade-off**：Search Result 体积增加，换取候选判断的正确性和执行效率；bounded 限制控制 token、latency、噪声和注意力稀释。

**Failure Case**：只返回裸命中会导致 Agent 误判候选价值，或被迫对每个结果追加一次 Context Tool Call。

### 4.1 内部 Capability 保持独立可观测

Agent 看到的是合并后的 Search Tool，内部仍保持 Retrieval 与 Context Expansion 两个独立 Capability。一次调用至少应能够分别观察 raw hit、扩展范围与返回消息规模，从而区分：Retrieval 没有找到正确消息、Retrieval 已命中但 Context Expansion 范围不合适、上下文正确但 Agent 最终分析错误。

**Trade-off**：Tool 内部需要保留分段状态和 Trace，换取准确的 Failure Attribution。

### 4.2 Semantic Search 保留 Retrieval provenance

Semantic Retrieval 以 Stage 1.3 的 Child Chunk 为主要召回单元；`semantic_search` 自动执行 bounded context recovery，但结果仍保留 matched chunk、retrieval-specific score / score type、对应 message range 与 context，使 Evaluation 能确认具体召回来源。

**Trade-off**：Agent-facing 调用隐藏内部两阶段编排，换取更少的机械调用；provenance 字段保留诊断所需边界。

### 4.3 不以大 Context Window 取消边界

模型 Context Window 较大不是无限扩大 Search Result 的理由。设计仍需考虑 token cost、latency、噪声、注意力稀释与一次返回过多结果。当前只冻结“Message Search 默认带 bounded local context”；具体消息数、token、时间跨度、reply chain 和 Parent 范围全部保持 Tunable，由 Evaluation 决定。

## 5. 保留独立的 `get_message_context`

**Context**：Search 自动附带的局部上下文只服务于“该命中是否值得继续调查”的候选判断，并不保证足以恢复完整讨论。

**Decision**：保留独立的 `get_message_context`。它以稳定 `message_id` 为锚点，供 Agent 对已识别的重要消息继续恢复更大的上下文范围。

```text
lexical_search / semantic_search
        ↓
hit + bounded local context
        ↓
Agent 判断该命中重要
        ↓
get_message_context(message_id)
        ↓
获取更大的上下文范围
```

第一版不为此引入 `candidate_ref` 或 Runtime Candidate State。

**Reason**：Search 的自动上下文与深度调查的上下文恢复职责不同；使用已有稳定 `message_id` 即可完成跨调用锚定。

**Trade-off**：Tool Surface 多保留一个上下文 Tool，换取对长程讨论、完整排错过程和观点变化的显式调查能力。

**Failure Case**：若移除独立上下文 Tool，Agent 只能反复扩大所有 Search Result 或重新检索；前者造成结果膨胀，后者不能稳定恢复已确认命中的讨论范围。

## 6. 不独立设计 `get_scope_info`，并区分 Access Scope 与 Query Filters

**Decision**：Agent Runtime 向 Tool Layer 提供两类不同信息，第一版不增加 `get_scope_info`：

- **Data Access Scope**：硬授权边界，例如当前允许访问的 ChatSession、数据源或用户选定数据集合。包括 `execute_sql` 在内，任何 Tool 都不得读取该边界之外的数据。
- **Query Context / Query-specific Filters**：本次任务的查询条件，例如 time range、member、keyword。它们不自动等同于权限边界；是否必须由某个 Tool 强制应用，取决于对应 Tool Contract 与参数来源。

`execute_sql` 不能仅依赖模型自行在 SQL 中加入 Data Access Scope 过滤条件。具体 enforcement 机制——物理数据库隔离、connection scope、SQL validation 或其他方式——由后续 Storage / Runtime Implementation 决定，本阶段不提前设计。

**Reason**：Data Access Scope 与 Query-specific Filters 的约束强度不同，不能因二者都来自 Runtime Context 就混为同一个权限概念；这些信息也不需要 Agent 在每次任务开始前进行机械 Tool Call。

**Trade-off**：第一版不支持 Agent 通过 Tool 主动探索动态数据源或 Data Access Scope；同时需要后续实现一个可验证的 access enforcement 边界。各 Tool 是否强制应用某个 Query-specific Filter，仍需由其 Contract 与参数来源明确。若未来出现真实业务需求，再以新 Failure Case 或业务需求重新评估 `get_scope_info`。

**Failure Case**：Data Access Scope 仅授权 `session A` 时，Agent 提交无 session filter 的 `SELECT * FROM message`。若 `execute_sql` 直接访问包含 A / B / C 的数据库，就会越过授权边界；因此 Data Access Scope 不能只是 soft context。反之，用户询问“8 月消息”时，time range 是 Query-specific Filter；它是否由参数或 SQL 表达，应遵循 `execute_sql` Contract，而不是被误写成数据访问权限。

## 7. 人物查询采用 `find_members`

**Context**：Stage 1.2 已将稳定平台身份 `UserIdentity` 与 ChatSession 内的局部身份 `Membership` 分离。群聊中的“老王”可能同时匹配群昵称、账号名、历史 alias、平台 ID 或不同 ChatSession 的 Membership。

**Decision**：第一版使用 `find_members`，不使用 `resolve_member`。Tool 返回候选身份与匹配依据，由 Agent 根据 Query Context 判断。

**Reason**：`resolve_member` 暗示一定能够唯一解析，而群聊身份查询天然可能有歧义；`find_members` 更准确地表达候选查找语义。

**Trade-off**：Agent 需要处理多个候选，换取身份歧义的显式暴露，不制造虚假的唯一性。

**Failure Case**：同名或 alias 冲突时强行 resolve 会把查询过滤到错误成员，且后续统计和证据都可能看似正常但对象错误。

## 8. Structured Retrieval 直接采用 ChatLab 风格的 SQLite SQL

**Context**：ChatLab 的 `get_schema` 读取 SQLite `sqlite_master` 中的真实表结构，`execute_sql` 直接对当前 SQLite 数据库执行只读 SQL；不存在额外的 Analysis Schema / Analysis View 层。

**Decision**：Trivae 第一版 structured / canonical persistent store 采用 SQLite，并采用以下查询结构：

```text
SQLite
   │
   ├── get_schema
   │      └── Physical SQLite Schema
   │
   └── execute_sql
          └── Read-only SQL against Physical SQLite Database
```

第一版不增加：

```text
Physical Schema → Analysis Views → Agent-facing Schema
```

SQLite vs PostgreSQL 的第一版技术选型已经确认；仍 Pending 的是 Physical Schema、表结构、字段类型、索引、migration、transaction、具体持久化实现，以及 Vector Storage 是否独立。

**Reason**：当前没有 Failure Case 证明需要独立 Analysis Schema；如果 Physical Schema 足够清晰，直接暴露实现成本最低，也与 ChatLab 已落地的设计一致。Analysis View 会增加额外 Schema 设计、同步与维护成本。

**Trade-off**：Agent SQL 会依赖 Physical Schema，未来 Schema 重构可能影响已有查询；当前以最低实现复杂度换取第一版可用性。

**Reopen Trigger**：只有出现以下真实问题时，才重新评估 Stable Analysis Views：

- 内部表数量显著增加，Agent 经常选错表；
- Physical Schema 经常重构，Agent SQL 大量失效；
- Embedding / Chunk / Import / Sync 等内部实现表暴露后，Agent 经常错误查询内部数据；
- 数据库实现细节开始严重污染 Tool 使用。

若触发重新设计，应以 Evaluation 比较直接 Physical Schema 与 Stable Analysis Views 的正确率、维护成本和复杂度。

## 9. `execute_sql` 的安全与执行边界

**Decision**：`execute_sql` 只允许被确认是 read-only 的 statement，并通过 `max_rows` 或等价 Tool-level execution boundary 限制最大返回规模。`INSERT`、`UPDATE`、`DELETE`、`DROP`、`ALTER`、`CREATE` 等只是非只读语句示例，不构成完整 denylist，也不能被实现为完整安全规则。

bounded 不要求 Agent SQL 自身包含 `LIMIT`。Tool 可以在不修改 SQL 文本语义的前提下，通过 result fetching、cursor、adapter-level max rows 等方式限制返回规模；Truncation 必须显式暴露。具体 bounded execution mechanism 留给 Implementation，本阶段不冻结。

只读判断优先使用 SQLite Driver 提供的 readonly statement metadata；只有 Driver 不具备该能力时，才在实现阶段设计完整的只读 SQL validator。

Tool 不得 silently 修改 Agent 提交的 SQL，也不得在 SQL 执行失败后自动切换为另一套 Retrieval。

**Reason**：结构化查询只承担数据读取和确定性计算；写入不属于 Query Plane 权限。显式拒绝可保留原始错误与 Failure Attribution。

**Trade-off**：复杂的多语句或非只读 SQL 会被拒绝，换取数据完整性、结果规模可控和错误透明。

### 与 ChatLab 的有意差异：不自动改写 SQL

ChatLab 会在 SQL 缺少 `LIMIT` 时自动追加限制。Trivae 选择不 silently 修改 Agent 提交的 SQL，而是在 Tool Contract / execution boundary 中控制最大返回规模。无 `LIMIT` 本身不是 Invalid Argument，也不要求报错；只有 statement 非 read-only、参数无效或违反其他明确 Contract 时才按对应错误语义返回。

- **为什么偏离**：自动改写会让 Trace 中的提交 SQL 与实际执行语义不一致，削弱错误透明和 Failure Attribution。
- **收益**：Agent 提交内容、实际执行行为与错误信息保持一致。
- **复杂度与风险**：Tool 需要以不改写 SQL 文本语义的方式实施结果上限，并准确暴露 Truncation；具体执行机制仍需在 Implementation 中确定。
- **验证方式**：在 Tool Evaluation 中比较 SQL 执行成功率、越界结果率、Truncation 准确性、返回规模与 Agent 修正成本；若该偏离成为主导 Failure Case，再按 Reopen Reason 重新评估。

## 10. Structured Retrieval 的职责边界

**Decision**：`execute_sql` 适用于目标集合能由结构化条件明确确定的问题，例如：

- 8 月一共有多少条消息；
- 哪个成员发言最多；
- 某个成员每天的发言量；
- 最近 100 条消息。

当集合本身需要语义判断时，先通过 Lexical / Semantic Retrieval 确定候选集合，再进行确定性统计或聚合：

```text
Lexical / Semantic Retrieval
        ↓
确定语义候选集合
        ↓
需要时执行确定性统计 / 聚合
```

SQL Tool 不承担 Semantic Classification。

**Failure Case**：`过去半年有多少次关于 AI Agent 的有效技术讨论？` 中“哪些消息属于有效技术讨论”不是 SQL 可以独立决定的结构化条件。直接交给 SQL 会把语义判定错误地隐藏为确定性查询。

## 11. 暂不增加大量 Specialized Analysis Tools

**Context**：ChatLab 还提供 `get_chat_overview`、`get_member_stats`、`get_time_stats`、`keyword_frequency`、`get_recent_messages` 等专用分析 Tool。

**Decision**：Trivae 第一版不机械复制这些 Tool。能够可靠地通过 `get_schema + execute_sql` 完成的确定性分析，默认不提升为独立 Tool。

只有 Evaluation 证明某类分析高频出现、Agent 经常写错 SQL、SQL 过程过于机械，且专用 Tool 能明显提高可靠性或降低成本时，才新增 Specialized Analysis Tool。

**Trade-off**：Agent 需要自行生成部分 SQL，换取更小、更稳定的 Tool Surface；高频错误由 Evaluation 驱动后再封装。

## 12. 第一版不暴露 `hybrid_search`

**Context**：Stage 1.3 已确认 Hybrid 是 `Lexical Candidates + Semantic Candidates + Merge / Dedup / Selection` 的 Retrieval Composition Strategy，而不是新的 Retrieval Primitive。

**Decision**：第一版继续分别暴露 `lexical_search` 与 `semantic_search`，由 Agent 针对复杂任务组合调用。不增加 `hybrid_search`、`universal_search` 或 `retrieve_evidence`。

**Reason**：保持每条召回路径的语义与 provenance 清晰，避免把不同策略藏进万能 Tool。

**Trade-off**：复杂任务可能需要多次 Tool Call；若 Evaluation 发现大量任务稳定重复完全相同的 lexical + semantic + merge 流程，再基于真实证据设计高级组合 Tool。

## 13. Search Result Schema 原则

**Decision**：Lexical Search 与 Semantic Search 共享统一外层结构，但保留各自 Retrieval provenance：

```text
SearchResult
├── query
├── hits[]
│   ├── match
│   │   ├── strategy
│   │   ├── matched_message_ids
│   │   ├── matched_terms?        # lexical
│   │   ├── matched_chunk_id?     # semantic
│   │   ├── score?                # retrieval specific
│   │   └── score_type?
│   │
│   └── context
│       └── messages[]
│           ├── message_id
│           ├── session_id
│           ├── stable_author_identity
│           ├── readable_author_display
│           ├── timestamp
│           ├── content
│           ├── reply_to?
│           └── is_match
│
└── meta
```

以上名称用于表达语义角色，不是最终字段名。BM25、FTS rank、cosine similarity 等 score 不能直接比较；若暴露 numeric score，必须同时说明 score type。Context Message 必须保留稳定 message identity、session identity、稳定作者身份、可读作者显示信息、timestamp、content 等必要信息，不得只返回拼接聊天文本。

本阶段确认的是 Result 的语义结构与必要信息，不冻结最终 Python type、JSON serialization、字段命名或数据库字段映射。稳定作者身份最终映射 `UserIdentity` 还是 `Membership`、可读显示信息采用消息当时昵称还是其他 display semantics，留给 Data Schema / Implementation 阶段确定。

**Reason**：统一外层降低 Agent 理解成本；strategy-specific provenance 保留召回归因；结构化消息为后续 Evidence / Citation 提供稳定路径。

**Trade-off**：不同检索策略无法被压成完全相同的 match 字段，换取语义正确与可观测性。

## 14. 统一 Tool Result Envelope

**Decision**：第一版所有 Tool 使用统一薄 Envelope：

```text
{
  status: "ok" | "partial" | "error",
  data: ...,
  meta: {
    truncated: true | false
  },
  error: {
    code,
    message
  } | null
}
```

状态语义：

| 场景 | 表达 |
| --- | --- |
| Zero Hits | `status = ok`，`hits = []` |
| Invalid Argument | `status = error`，`error.code = INVALID_ARGUMENT` |
| Capability Unavailable | `status = error`，`error.code = CAPABILITY_UNAVAILABLE` |
| Execution Failure | `status = error`，`error.code = EXECUTION_ERROR` |
| Partial Result | `status = partial` |
| Truncation | `meta.truncated = true` |

Truncation 表示结果因规模上限被截断；Partial 表示只有部分内部步骤完成。两者不得混为同一概念。Capability Unavailable 不得 silent fallback 到其他 Capability。

**Reason**：统一 Envelope 让 Agent 可以稳定处理正常结果、部分结果和错误；明确状态保留 Failure Attribution。

该 Envelope 同样是语义契约：本阶段冻结状态与错误语义，不冻结最终 Python type、JSON serialization、字段命名或与内部异常类型的映射。

## 15. 第一版统一 Tool Contract

以下契约全部 Confirmed：

1. Tool 参数必须有明确类型与边界。
2. 所有可能返回大量数据的 Tool 都必须 bounded。
3. Zero Hit 不属于 Error。
4. Invalid Argument、Capability Unavailable、Execution Error 必须区分。
5. 禁止 silent fallback。
6. Data Access Scope 是所有 Tool 的硬授权边界；包括 `execute_sql` 在内，Tool 不得读取边界之外的数据。time range、member、keyword 等 Query Context / Query-specific Filters 不自动等同于权限边界，是否强制应用由 Tool Contract 与参数来源决定；Data Access Scope 的具体 enforcement 机制由后续 Storage / Runtime Implementation 决定。
7. Message-based Retrieval 必须返回稳定 `message_id`。
8. Truncation 必须显式暴露。
9. Tool 内部组合多个 Capability 时，各 Capability 仍保持独立可观测。
10. Retrieval Tool 返回 Candidate Data，不在 Tool 内硬编码 Final Evidence 判断。
11. 经验参数保持 Tunable，由 Evaluation 决定，不把当前默认值写成架构事实。
12. Agent-facing API 保持简单；新增抽象和 Tool 需要真实 Failure Case 或 Evaluation 证据。

## 16. 第一版明确不做

第一版不引入：

```text
Analysis Schema / Analysis View 隔离层
candidate_ref / Candidate State
get_scope_info
resolve_member
hybrid_search
universal_search
retrieve_evidence
大量 specialized analytics tools
复杂的 Tool orchestration framework
```

其中 Analysis View、Hybrid Tool、Specialized Analysis Tool 等可以在满足 Reopen Reason 后重新评估，但不能因为“以后可能有用”提前加入。

## 17. Stage 1.4 决策状态汇总

### Confirmed

| 项目 | 决策 |
| --- | --- |
| 架构治理 | 遵循项目级 ChatLab Reference Implementation Architecture Principle；偏离按项目级原则记录证据与验证要求 |
| Tool / Capability | 分离；Tool 可以组合多个 Capability |
| 第一版 Tool Surface | `lexical_search`、`semantic_search`、`get_message_context`、`find_members`、`get_schema`、`execute_sql` |
| Message Search | 默认附带 bounded local context；内部 Retrieval / Expansion 独立可观测 |
| 深度上下文恢复 | 保留 `get_message_context(message_id)`，不引入 Candidate State |
| Data Access Scope | Runtime 提供，不提供 `get_scope_info`；所有 Tool（包括 `execute_sql`）不得读取硬授权边界外数据；enforcement 机制后续决定 |
| Query Context / Query-specific Filters | time range、member、keyword 等不自动等同于权限边界；是否强制应用由 Tool Contract 与参数来源决定 |
| Member Lookup | 使用 `find_members` 返回候选与匹配依据 |
| Persistent Store / Structured Retrieval | 第一版 structured / canonical persistent store 采用 SQLite；`get_schema` 暴露 Physical Schema；`execute_sql` 直接执行只读 SQL |
| SQL 边界 | statement 必须确认 read-only；关键字仅为示例；bounded 但不要求 SQL 自带 `LIMIT`；不改写 SQL、不自动切换 Retrieval；Truncation 显式暴露 |
| Hybrid / Specialized Tools | 第一版不暴露；后续由 Evaluation / Failure Case 驱动 |
| Search Result | 确认统一外层语义、strategy provenance 与结构化 Message Identity；不冻结实现 Schema |
| Tool Envelope | 确认 `ok / partial / error` 等状态语义；不冻结实现 Schema；Truncation 与 Partial 分离 |

### Pending Implementation / Real-run Calibration（不重新打开架构方向）

- Lexical Search 的具体上下文窗口；
- Semantic Parent / Context Recovery 的具体范围策略；
- 各 bounded Tool 的具体默认上限；
- Data Access Scope 对 `execute_sql` 的具体 enforcement 机制；
- `execute_sql` 的具体 bounded execution mechanism；
- Search Result / Tool Envelope 的最终 Python type、JSON serialization、字段命名与数据映射；
- Specialized Analysis Tool 或高级组合 Tool 是否满足新增条件。

Stage 1.10 已确认上述校准必须绑定 Case Bundle、Snapshot、Scope、pinned Baseline / Candidate 与 paired quality result；当前仍无 runner、Tool Evaluation Schema 或真实参数结论。

### Experimental

当前没有已批准的 Experimental 偏离。任何未来偏离 ChatLab 或上述 Confirmed 决策的实验，都必须先记录 Reopen Reason、验证方法与退出条件。

## 18. M3 Implementation Slice: `search_messages`

M2/M3 implementation task 已落地第一条 Retrieval-facing capability：registry 名称为 `search_messages`，其内部组合 Lexical Retrieval 与 bounded automatic Context Expansion，再投影为 Stage 1.4 统一 Tool Envelope。它是本轮对 Stage 1.4 概念 `lexical_search` surface 的 Trivae implementation adaptation，不代表增加 Hybrid、Semantic 或 Runtime orchestration。

已验证的实现边界：

- Capability 继承 trusted session/time scope，并拒绝越权 filter 和超过 trusted max result 的输入。
- Retrieval Core 拥有 FTS query、canonical projection hydration、context merge/dedup/order/trim；Tool handler 不导入 SQLite。
- `ok`、`partial`、`error` 与 `meta.truncated` 分离；zero hit 是正常结果；invalid argument、capability unavailable、execution error 分开投影。
- 经验窗口默认值仍属于 implementation baseline，而不是 Evaluation-confirmed optimal parameter；下一轮以真实 Case Bundle 重新校准。

M3 本轮不实现 `semantic_search`、`get_message_context`、`find_members`、`get_schema`、`execute_sql` 的 Tool surface，也不进入 Router/Planner/Runtime；这些保持下一条 vertical slice 的 scope。

## 19. Reopen（Stage 1.10）：新增 `get_recent_messages`

**Reopen Trigger（真实 Failure Case）**：用户真实询问 `最近一两天大家都在讨论什么有价值的内容`，Trace `trace-87060c18023e46988f4df09a98a27f9f` 记录了完整失败链路：

```text
semantic_search（猜测主题）→ 0 hits
lexical_search("推荐")       → 0 hits（中文 recall 问题，见 Problem Record）
semantic_search ×2           → 0 hits
get_schema                   → 未执行 SQL 即放弃
terminal: failed, 5 tool calls, ~75s, final_answer unavailable
```

§11 的预设 reopen 条件被满足："SQL 过程过于机械 / Agent 并不稳定走 SQL 路径 / 高频问题类型"。Agent 面对 temporal overview 问题的实际行为是"猜测最近可能聊了什么，再检索自己的猜测"，该访问模式对 lexical/semantic retrieval 天然不匹配。

**Decision**：新增第 7 个 Agent-facing Tool `get_recent_messages`，作为 Temporal Browsing primitive：

- 内部完全复用 StructuredRetrieval / Canonical Read Repository，不复制数据读取；
- 输入沿用 RelativeTimeRange（anchor=archive_latest）或显式时间戳；trusted scope 由 Capability 强制继承；
- 排序语义固定为"窗口内先选最新 limit 条，再按自然阅读顺序返回"（selection DESC → return ASC）；
- 结果复用 `StructuredMessageResult` 与统一 Envelope/Evidence/Citation/Trace 主链路，不建第二套 provenance；
- limit 复用 structured bound（default/max = 100），truncation 显式；
- 不在 Tool 内做价值判断；主题发现与总结是 Agent synthesis 的职责。

**Tool Selection Boundary**（写入 prompt 与 tool description）：

```text
候选集合由时间范围决定 + overview/summary/topic discovery → get_recent_messages
精确 lexical target（URL/repo/code/error/nickname/exact phrase）→ lexical_search
概念转述无精确词                                               → semantic_search
结构化统计 counts/GROUP BY                                      → execute_sql
```

Router 保持 LLM 路由不变；本轮依赖 tool description + prompt 保证选择正确性。真实 smoke 显示同题查询稳定以 `get_recent_messages` 为首个且唯一的数据读取 Tool（1 tool call, 1 tool round）完成并产出可解析 citations。若后续 Evaluation 发现模型仍频繁错选，才考虑 Rule Router 特判（不允许 keyword hardcode 如 `if "最近" in query`）。

**Rejected alternatives**：
- 仅修改 prompt 引导多尝试 synonyms：继续制造 multi-query guessing（permanently rejected by 真实 trace）；
- 直接用 execute_sql 替代新 Tool：ADR §11 预设的 reopen trigger 已被真实 Failure Case 触发，execute_sql ergonomics 已被证明不足；
- silent LIKE fallback：违反本项目 no-silent-fallback 原则。

### 附带决策：CJK bigram derived-index normalization

Failure B（`lexical_search("推荐")` 对 canonical `真心推荐 值得看一看` 0-hit）经真实库诊断定位为 unicode61 tokenizer 行为：连续 Han run 存成单 token（实测 tokens `[真心推荐] [值得看一看]`）。修复采用 rebuild/query 双侧一致的 CJK bigram 归一化派生索引（strategy id `unicode61+cjk-bigram-v1`，元数据表 `trivae_derived_meta`，read 侧显式 stale 校验）；ASCII/URL/code 的 unicode61 exact 行为不受影响。方案比较（trigram/dual index/LIKE fallback）与证据见 Problem Record `temporal-browsing-cjk-lexical-recall`。

| 项目 | 决策 |
| --- | --- |
| 第一版 Tool Surface | + `get_recent_messages`（Temporal Browsing，复用 Structured Retrieval） |
