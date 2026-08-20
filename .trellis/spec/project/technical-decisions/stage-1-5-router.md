# Stage 1.5: Router Decisions

> 状态：**Confirmed（Stage 1.5）**
>
> 本文记录 Stage 1.5 Router 的取舍、理由、边界、Failure Case 与重新打开条件。Router 已完成架构设计沉淀，但尚未实现；具体规则、模型参数、Trace Schema 与 Evaluation Benchmark 不在本 ADR 中提前冻结。

---

## 0. Architecture Governance

Stage 1.5 遵循项目级 [Architecture Principle: ChatLab as Reference Implementation](../architecture.md#architecture-principle-chatlab-as-reference-implementation)。ChatLab 的 Router / Planner 设计是参考基线；本 ADR 只记录 Trivae 在 Route taxonomy、职责边界、决策策略与失败可用性上的具体选择，不把 ChatLab 的实现参数自动继承为 Trivae 契约。

## 1. Context：Router 要解决的问题

Trivae 的 Query Plane 需要在 Agent Runtime 之前决定：当前请求是否值得先经过 Planner。这个判断的价值在于控制执行复杂度，而不是预先决定数据访问方式。

Trivae 的典型任务从明确的统计、查找，延伸到跨时间、多目标、多证据的技术情报调查。两类请求最终都需要由同一个 Agent Runtime 根据当前状态推进；真正改变执行路径的因素是是否增加 Planner 这一额外阶段。

因此，Stage 1.5 将 Router 定义为：

> **轻量的 execution-complexity classifier / Planner gate。**

Router 的核心问题只有一个：

> 当前请求是否值得在进入 Agent Runtime 之前，先通过 Planner 生成显式的高层执行 guidance？

Router 不承担 Tool Selection、Retrieval Routing、Query Planning、Workflow Execution 或 Evidence Selection。

## 2. Decision A：将 ChatLab 三路 taxonomy 简化为两路

### Initial Design / Context

ChatLab 的参考 taxonomy 为：

```text
direct_response
tool_assisted
planned_execution
```

其中 `direct_response` 与 `tool_assisted` 在当前 Runtime 结构中最终进入同一个 Agent Core；真正额外增加执行阶段的是 `planned_execution`，因为它会先经过 Planner，再进入同一个 Agent Core。

Trivae 是面向高噪声群聊调查与分析的垂直 Agent，正常请求主要围绕群聊历史、成员、时间变化、话题、行为模式、数据统计和证据型调查，而不是把“是否调用 Tool”作为产品层级的主要执行分类。

### Candidate Solutions

1. 保留 ChatLab 的三路 taxonomy；
2. 合并为两路，但使用 `direct_response` 与 `planned_execution`；
3. 合并为两路，使用 `standard_execution` 与 `planned_execution`。

### Decision

Trivae 第一版只保留：

```text
standard_execution
planned_execution
```

`standard_execution` 吸收 ChatLab 的 `direct_response` 与 `tool_assisted` 语义；`planned_execution` 保留“在 Agent Runtime 前增加 Planner”这一真正有执行意义的差异。

### Why

- `direct_response` 与 `tool_assisted` 没有足够的 Runtime 行为差异，不值得成为独立 Route；
- `standard_execution` 不预设是否使用 Tool，准确表达了 Router 不替 Agent Runtime 做 Tool 决策的边界；
- Trivae 的核心产品任务是调查、分析和证据组织，三路 taxonomy 会增加 classification ambiguity、evaluation cost、maintenance cost 与 failure surface；
- `planned_execution` 仍然保留清晰的 Planner gating 语义，不会丢失真正重要的路径差异。

### Result

Trivae 的 Route 判断关注“是否需要额外 Planning”，而不是“是否需要 Tool”。标准路径可以调用零个、一个或多个 Tool：

```text
standard_execution
    → Agent Runtime
    → 0 / 1 / multiple Tool Calls（由 Runtime 自主决定）
```

### Trade-off

Route taxonomy 更小、语义更清晰，但不能再依靠 Route 名称推断 Tool 使用情况。若未来确实出现独立的 Runtime 行为差异，必须由真实 Failure Case、业务需求或 Evaluation 触发 Reopen，而不能仅因 ChatLab 保留三路就恢复第三路。

## 3. Decision B：Router 只负责 Planner gating

### Problem / Constraint

Stage 1.3 已确认 Retrieval 由 Retrieval Composition、Structured / Lexical / Semantic Primitives 与 Context Expansion 组成；Stage 1.4 已确认 Agent-facing Tool Surface 与 Tool / Capability 边界。若 Router 同时决定 Retrieval 或 Tool，Route 将逐渐演化为另一个 Query Planner，破坏既有阶段边界。

### Candidate Solutions

1. 让 Router 同时选择 Planner、Tool、Retrieval Strategy 和 SQL 路径；
2. 让 Router 只输出一个高层任务类型，再由其他层解释；
3. 将 Router 限定为是否需要 Planner 的 execution-complexity classifier。

### Decision

选择方案 3。Router 只输出是否进入 `standard_execution` 或 `planned_execution`，并以 `planned_execution` 作为 Planner gate。

明确拒绝 Router 输出或决定：

```text
selected_tools
retrieval_strategy
lexical / semantic / hybrid route
keywords
semantic queries
SQL / filters / top_k / rerank
plan steps
evidence requirements
```

### Why

职责边界保持为：

```text
Router
    → 是否需要 Planning
Planner
    → 复杂任务的高层调查 guidance
Agent Runtime
    → 当前状态下具体怎么做
Tools / Retrieval
    → 执行具体数据访问与候选召回
```

这使 Router 可以在不理解底层检索实现、不绑定 Tool 参数的情况下独立评估和演进。

### Trade-off

Agent Runtime 可能需要自行组合多个 Tool 或调整 Retrieval Strategy，某些复杂任务不会在 Router 阶段得到低层提示；这是有意保留的自治边界，换取 Router 的低复杂度、低耦合和清晰归因。

## 4. Decision C：基于任务结构判断 Planning Value，不基于单一关键词

### Context

`分析`、`总结`、`比较`、`过去一年`、`证据`、`趋势` 等词语既可能出现在复杂调查中，也可能出现在单次明确查询中。例如“分析一下谁发言最多”可以直接转化为结构化聚合；“总结昨天聊天”可能只需一次检索和总结。

### Decision

Router 以任务结构和 Planning Value 为判断依据。可以关注以下复杂度维度：

```text
Multi-goal
Dependency
Temporal reasoning
Multi-source evidence
Semantic judgment
Recovery / query reformulation
```

这些维度是概念模型，不在 Stage 1.5 固化成固定整数公式、regex 集合、权重或 threshold。通常应由多个维度共同表明 Planning 有价值，而不是由某个词触发。

### Result

以下两类误判会进入后续 Evaluation：

- Keyword false positive：因为出现复杂词汇就错误进入 Planner；
- Keyword false negative：复杂调查使用自然表达，没有明显关键词而被规则漏掉。

Tool Call 数量同样不是 Route 信号。一个 `standard_execution` 可以连续调用 `find_members → get_schema → execute_sql`，一个复杂请求也可能在 Runtime 中先调用很少的 Tool。

### Trade-off

结构判断比关键词规则更难校准，需要真实 Query Set；但它避免把词汇表误当成任务语义，也避免复制造成长期维护成本的规则堆积。

## 5. Decision D：Rule-first + LLM fallback

### Candidate Solutions

1. 所有请求都先调用 LLM Router；
2. 只使用固定规则；
3. 先用确定性规则处理高置信请求，ambiguous case 再交给 LLM Router。

### Decision

选择方案 3：

```text
Query + Runtime Context
        ↓
    Rule Router
        ↓
  high confidence?
      ├── yes → use rule decision
      └── no  → LLM Router → decision
```

明显简单或明显复杂的请求不额外消耗模型调用；只有规则无法可靠判断的 ambiguous case 才使用 LLM Router。

### Why

规则适合处理可明确识别的低复杂度 / 高复杂度结构，LLM 适合处理短、隐含或自然表达的复杂意图。两者组合可以控制 latency、token 和外部模型依赖，同时保留对非模板化请求的覆盖能力。

### LLM Failure Contract

LLM Router 出现 invalid JSON、unknown route、timeout、API error 或 parsing failure 时，不能让整个用户请求失败：

1. 若存在合理的 Rule Decision，使用该决定；
2. 否则使用保守的 `standard_execution`；
3. 记录原始失败和最终降级 Route，供后续 Trace / Evaluation 归因。

这不是对所有模块开放的静默 fallback，而是 Router 作为 execution optimization layer 的明确可用性契约。Tool / Retrieval 仍遵循 Stage 1.4 的错误透明与禁止 silent fallback 原则。

### Trade-off

Rule-first 会漏掉没有显式结构信号的复杂请求，LLM fallback 会增加 ambiguous case 的延迟和成本；换取明显请求的低成本路径与复杂自然表达的覆盖能力。具体模型、prompt、timeout 和 threshold 留待 Implementation / Evaluation。

## 6. Decision E：Conservative Routing，Planner 必须证明其价值

### Decision

默认 Route 为：

```text
无法明确证明 Planning 有价值
    → standard_execution
```

`planned_execution` 必须由足够明确的多目标、依赖、跨阶段证据、时间演变、语义判断或恢复需求支撑，而不是因为请求“听起来很深入”。

### Why

Under-routing 与 Over-routing 的代价不对称：

```text
complex → standard
    Agent 仍可能调用多个 Tool、调整查询并继续调查

simple → planned
    稳定增加 Planner model call、latency、token 和 plan-induced bias
```

第一版优先控制高频简单请求的额外成本，同时保留 Agent Runtime 的执行恢复能力。

### Trade-off

部分边界复杂请求可能先走标准路径，执行效率不一定最优；这是以较低的常规成本换取更小的 over-routing surface。若真实 Evaluation 证明某类 under-routing 已成为主导 Failure Case，再调整判定机制。

## 7. Decision F：Router failure 不得成为请求可用性的单点故障

### Decision

Router 是 execution optimization layer，不是 request availability dependency。Router 自身异常时，请求仍应继续进入 Agent Runtime：

```text
Router failure
    → Rule Decision（若可用）
    → 否则 standard_execution
    → Agent Runtime
```

降级必须显式、可观测，不得把 Router 错误伪装成正常高置信判断。具体日志字段、Trace Event Schema 和指标由 Stage 1.9 确定。

### Failure Cases

| Failure | 影响 | Stage 1.5 处理原则 |
| --- | --- | --- |
| Under-routing | 复杂请求遗漏调查维度、过早下结论、证据覆盖不足 | 记录 Route，交由 Evaluation 归因与校准 |
| Over-routing | 简单请求产生无意义 Planning 成本与约束 | 保守默认，统计 over-routing |
| Keyword false positive | 简单词汇触发 Planner | 不允许单词单独决定 Route |
| Keyword false negative | 隐含复杂请求进入标准路径 | 保留 LLM fallback，并纳入 Query Set |
| LLM malformed output | 无法生成合法 Route Decision | Rule Decision 或 `standard_execution` |
| Router unavailable | 请求被错误阻断 | 继续进入 `standard_execution` |

### Reason

请求可用性是 Router 之外的主链路约束。Router 的收益主要是效率和组织性，不足以证明它应成为整个 Agent Request 的硬依赖。

### Trade-off

失败降级可能让复杂请求少经过一次 Planning，质量或效率可能下降；但系统仍可返回由 Agent Runtime 自主执行的结果，并能通过 Trace 识别“Router 失败”而不是把它误判成“用户请求失败”。

## 8. RouterInput 与 RouteDecision 的语义契约

### RouterInput

Router 读取由 Runtime 注入的轻量输入：

```text
RouterInput
├── user_query
├── query_context
├── compact_data_snapshot
│   ├── chat type
│   ├── message count
│   ├── member count
│   ├── available data time range
│   └── other lightweight availability hints
└── capability_summary
```

Router 不通过普通业务 Tool 查询 Chat Metadata、Data Scope 或数据可用性，也不接收大量聊天正文。`compact_data_snapshot` 只提供轻量 metadata；Data Access Scope 仍由 Runtime 负责并作为 Tool Layer 的硬边界。

### RouteDecision

第一版只冻结语义，不冻结 Python class、序列化或文件布局：

```text
RouteDecision
├── route       standard_execution | planned_execution
├── confidence  0..1
├── reason      short diagnostic reason
└── source      rule | llm
```

`reason` 只用于 Debug、Evaluation、Trace 和 Failure Attribution，不承载 Chain-of-Thought；`RouteDecision` 不携带 Tool、Retrieval、SQL、Plan 或 Evidence 细节。Stage 1.5 不增加第三个 `fallback` source；降级触发的原始错误由独立诊断 / Trace 记录。

## 9. Verification、Regression 与 Reopen 条件

Stage 1.5 不提前完成 Stage 1.10，但必须为后续验证保留 Route、Confidence、Reason 和 Source。

未来 Query Set 至少覆盖：

- obvious standard；
- obvious planned；
- ambiguous；
- keyword traps；
- long-time-range but simple；
- multi-tool but simple；
- short wording but complex；
- evidence-heavy investigation。

推荐验证顺序：

```text
定义 Route 语义
    → 建立人工标注 Query Set
    → 实现 Rule Router
    → Evaluation
    → 调整规则与参数
```

当前无业务代码，因此本阶段不添加实现测试或伪造回归结果。Router 实现后，under-routing、over-routing、keyword trap、LLM malformed output 与 degradation 记录应进入对应 Regression / Evaluation Set。

以下情况可以重新打开本 ADR：

- Evaluation 证明 `standard_execution` 与 `planned_execution` 之外确实存在独立且稳定的 Runtime 行为差异；
- 真实 Failure Case 证明 conservative default 导致某类复杂任务持续失败，且 Agent Runtime 无法恢复；
- Rule-first 的维护成本或 LLM fallback 成本明显超过收益；
- Router failure degradation 造成可复现的质量、合规或可用性问题；
- 新业务需求要求 Router 输出当前明确禁止的低层执行信息。

重新打开时必须记录 Reopen Reason，并以 Failure Case、技术约束、Evaluation 结果或业务需求为依据。

## 10. Explicitly Out of Scope

本 ADR 不设计以下内容：

- Planner 的完整 Input、Plan Schema、步骤类型、步骤上限、retry、replan、state machine 或 execution semantics（Stage 1.6）；
- Agent Runtime 的 Loop、Session、Streaming、Abort、SDK 版本与 Run Lifecycle（Stage 1.7）；
- Evidence / Citation model 与证据选择（Stage 1.8）；
- Router Trace Event Schema、存储、采集和完整指标命名（Stage 1.9）；
- Router Evaluation Benchmark、标注平台、最终 accuracy / error rate 口径与参数校准（Stage 1.10）；
- 具体 regex、复杂度权重、confidence threshold、LLM model、prompt、timeout、Python class 与文件布局。
