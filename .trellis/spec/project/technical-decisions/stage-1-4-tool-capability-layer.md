# Stage 1.4: Tool / Capability Layer Decisions

> 状态：**Confirmed（Stage 1.4）**
> 记录 Stage 1.4 真正形成的 Tool / Capability Layer 架构决策及 rationale。仅覆盖已确认的架构原则；尚未定稿的 Tool 列表、Structured Query 设计、具体参数等不在此文档内决定。
> 参考 ChatLab 但不机械复制：所有参考仅作为 initial hypothesis / reference design，以 Trivae 的业务目标（高噪声群聊分析的垂直 Agent）与 Evaluation 为准。

---

## 1. Tool 与 Capability 分离

**Context**：Agent Runtime 与底层 Retrieval / Data Layer 之间需要一个边界层：既要向 Agent 暴露少量、语义清晰、容易调用的工具，又要隔离 Agent SDK 与底层业务实现，使 Retrieval、Context、Identity 等核心能力不依赖具体 Agent Runtime。

**Problem**：如果把底层每一步能力直接暴露为 Agent Tool，或让业务逻辑直接依赖 OpenAI Agents SDK 等 Runtime，会导致 Agent 面对几十个 Tool 选择混乱，且核心能力被绑定到具体 SDK。

**Decision**：区分两个概念：

- **Capability**：项目自身提供的业务能力（Lexical Retrieval / Semantic Retrieval / Context Expansion / Structured Retrieval / Identity Resolution 等），**不依赖具体 Agent Runtime**。
- **Tool**：提供给 LLM / Agent 的调用接口（如 `lexical_search` / `semantic_search`），负责参数验证 → 调用一个或多个 Capability → 标准化返回结果。

**Reason**：Capability 保持 SDK 无关，业务能力可复用、可测试；Tool 面向 Agent 的调用习惯，负责适配层职责。

**Result**：`Agent Runtime → Tool Layer → Capability Layer → Retrieval / Canonical Data / Index`。

**Trade-off**：多一层适配（Tool → Capability 映射），换取核心能力与 Agent Runtime 的解耦。

## 2. 一个 Tool 可组合多个 Capability

**Context**：Trivae 是面向高噪声群聊分析的垂直 Agent，不需要把底层 Retrieval 的每一步都暴露给模型。

**Problem**：为了模块边界纯粹而把每个内部步骤都暴露成独立 Tool，会导致 Agent 出现 `search → 裸 hit → expand → 阅读 → search → expand → 阅读` 的大量机械调用，增加 Token 与延迟，且 Agent 难以正确编排。

**Decision**：**一个 Agent-facing Tool 可以在内部组合多个 Capability。** 设计 Tool 时优先考虑 Agent 是否容易理解、容易正确调用、是否减少机械 Tool Call、是否能直接获得足够信息进行判断。

**Reason**：Agent 易用性优先于模块边界的展示纯度；模块边界在内部保持清晰，Agent-facing API 合并高频步骤。

**Result**：内部保持 `Lexical Retrieval` 与 `Context Expansion` 等独立能力，Agent 看到的是合并后的 `lexical_search → hit + context`。

**Trade-off**：Agent-facing API 不再与内部模块一一对应，需要靠 Tool 层维护组合逻辑与可观测性。

**Failure Case**：若每个能力都暴露为独立 Tool，Agent 需要自己组合底层步骤，大量机械 Tool Call 抬高延迟与成本，且组合错误难以归因。

## 3. Search 默认自动补充 bounded context

**Context**：高噪声群聊中单条消息往往缺少足够语义。例如 `10:29 A：用了 LangGraph` 单独看价值很低；加入邻近上下文（`10:28 B：导演 Agent 最后用什么写的？` `10:30 A：后来换掉了` `10:32 A：状态复杂之后排查特别麻烦`）后，Agent 才能判断该命中是否值得继续调查。

**Problem**：若 Search 只返回裸命中，Agent 每次都要显式扩展上下文才能判断命中价值，属于高频重复步骤。

**Decision**：**Search 默认自动补充 bounded context，Local context 是 Search Result 的默认组成部分。** 对于 Lexical Search：`lexical_search → Lexical Retrieval → message hits → automatic bounded context expansion → hits + local context → Agent`。Agent 不需要在每次关键词命中后再显式调用 Context Expansion。（参考 ChatLab `search_messages`。）

**Reason**：在群聊场景中，小范围邻近上下文具有很高的信息增益，且这是绝大多数 Search Hit 都需要执行的高频步骤，合并进 Search 降低 Agent 的执行复杂度。

**Result**：Search Result 默认包含 hit + local context。

**Trade-off**：Search 返回内容变多（token 成本上升），换取 Agent 判断效率与正确性。

**Failure Case**：只返回裸命中 → Agent 缺乏上下文 → 误判命中价值，或被迫反复 expand 造成机械调用。

## 4. 自动 Expand 必须是 bounded expansion

**Context**：Search 自动补充上下文不意味着返回任意大的聊天范围。

**Problem**：若自动扩展无界，`keyword hit → 整个 conversation` 或 `keyword hit → 很长时间范围全部聊天` 会带来 token 爆炸、上下文噪声、注意力稀释。

**Decision**：正常 Search 的目标是"找到候选 + 给 Agent 足够的信息判断候选价值"，**不是一次性还原完整讨论**。默认只进行有限范围的 Context Expansion，例如未来可能采用：命中消息附近若干条消息 / 有限 token budget / 有限时间窗口 / Conversation Parent 的局部内容。具体策略暂不固定。

**Reason**：bounded 才可预测成本与结果规模，避免无限扩大。

**Trade-off**：bounded 可能牺牲部分长程上下文，换取可控的 token / latency / 噪声。

## 5. 内部 Capability 保持独立可观测

**Context**：Agent 看到的是合并后的 Tool（`lexical_search → hit + context`），内部依然保持 Lexical Retrieval 与 Context Expansion 两个独立能力。

**Decision**：

```text
lexical_search Tool
        │
        ├── LexicalRetriever.search()
        └── ContextExpander.expand()
```

一次 Tool Call 内部仍可观察：`lexical retrieval（raw_hit_count）` 与 `context expansion（expanded_hit_count / returned_messages）`。

**Reason**：既减少 Agent Tool Call，也保留工程可观测性，从而能区分三种 Failure：Retrieval 没找到正确消息 / Retrieval 找到了但 Context Expansion 范围不合适 / 上下文正确但 Agent 最终分析错误。

**Trade-off**：Tool 内部需要暴露分段状态（不能只返回合并结果），换取失败归因能力。

## 6. Semantic Search 采用同样原则

**Context**：Semantic Retrieval 已在 Stage 1.3 确定以 Child Chunk 作为主要召回单元。

**Decision**：Agent-facing 设计不暴露完整内部两阶段过程（`child hit → Agent 再调用 expand`），第一版形式为：`semantic_search → Semantic Retrieval → Child Chunk hits → automatic bounded context recovery → candidate + context → Agent`。返回结果保留 Retrieval provenance：matched chunk / similarity or retrieval score / 对应 message range / context。

**Reason**：与 Lexical 一致地降低机械调用；保留 provenance 以便 Evaluation 确认"到底是什么内容触发了召回"。

**Trade-off**：Agent 无法看到原始 child hit 与扩展后结果的边界，换取调用简单；provenance 字段补足这一信息需求。

## 7. 不把"大上下文窗口"作为主要设计依据

**Context**：当前模型拥有较大的 context window，降低了适量补充聊天上下文的成本压力。

**Problem**：不能据此无限增加 Search Result。

**Decision**：仍需考虑 token cost、latency、上下文中的噪声、模型注意力稀释、一次搜索返回过多结果。自动 bounded expansion 的主要理由是"小范围邻近上下文信息增益高且是高频步骤"，而不是"窗口够大"。

**Reason**：把大窗口当作设计依据会让 Search Result 规模失控，稀释注意力、抬高成本。

**Trade-off**：放弃"尽量多塞上下文"的便利，换取结果可控。

## 8. 参数先不写死，由 Evaluation 决定

**Context**：ChatLab 存在类似 `before = 2 / after = 2` 的默认上下文窗口。

**Decision**：第一版只冻结"Search 默认带 bounded local context"；具体参数（前后多少条消息 / 最大 token 数 / 最大时间跨度 / 是否基于 reply chain / 是否使用 conversation parent）全部通过真实群聊 Evaluation 调整，不复制 ChatLab 默认值。

**Reason**：遵循此前确定的原则——先确定架构与职责，再通过 Evaluation 决定经验参数。

**Result**：架构确定，参数 Pending Evaluation。

**Regression**：若现在固定参数，会重复"从参考项目抄默认值而无依据"的错误（与 Stage 1.3 决策 6 相同的回归风险）。

## 9. Tool 内部不能使用 silent fallback 隐藏错误

**Context**：Tool 可以组合 Capability，但不能因为组合而失去 Failure Attribution。

**Problem**：例如 Semantic Retrieval 不可用时，若 silently run lexical search 后返回普通结果，Agent 和 Evaluation 都无法知道 Semantic Retrieval 实际已失败。

**Decision**：**禁止 silent fallback。** 需明确区分：`zero hits` / `index unavailable` / `invalid arguments` / `execution failure` / `partial / truncated result`。Tool 可以简化 Agent 的调用方式，但内部执行状态必须保持可观测。

**Reason**：符合 Stage 0 的 Observable / Failure Attribution 原则——错误必须显式暴露，不能因封装组合而被吞掉。

**Trade-off**：Agent 需要处理更明确的错误/状态信号，换取失败可定位。

**Failure Case**：Semantic 索引未完成时 silent 回退 Lexical → 用户得到"貌似正常"的结果 → 实际覆盖不足 → 答案错误且无法归因。

## 10. 第一版不引入复杂 Candidate State 设计

**Context**：此前讨论过 `RetrievalCandidate / candidate_ref / expand_context(candidate_ref) / runtime candidate state` 这类候选引用状态机制。

**Problem**：Search 已默认返回足够的 bounded context，普通 Retrieval 不再需要 `Search → 保存 Candidate → Agent 引用 Candidate → Expand Candidate` 的额外状态机制。

**Decision**：**第一版暂不采用 Candidate State 设计**，优先保持 Tool API 简单。若后续真实 Evaluation 证明复杂调查需要稳定 Candidate Reference，再单独设计。

**Reason**：无需求证据的状态机制是无依据的复杂度（Stage 0 原则）。

**Trade-off**：暂不具备"跨调用稳定引用某条候选并增量扩展"的能力，换取第一版 API 简单。

---

## Pending（Stage 1.4 后续讨论，本阶段不定稿）

- Agent 最终暴露多少个 Tool，以及完整 Tool Registry
- 是否独立暴露 `get_message_context` / `expand_context` 供深度调查
- `get_scope_info` 是否独立存在
- Member / Identity Resolution 应该如何暴露
- Structured Retrieval 应采用 declarative query 还是 read-only SQL
- Lexical Search 的具体上下文窗口参数（Pending Evaluation）
- Semantic Parent / Context Recovery 具体策略（Pending Evaluation）
- Search Result 的最终 Schema
- Tool Result Envelope 的具体字段
- 是否以及何时需要更高级的 Hybrid Search / Evidence Retrieval Tool
