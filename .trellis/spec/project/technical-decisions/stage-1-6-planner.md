# Stage 1.6: Planner Decisions

> 状态：**Confirmed（Stage 1.6）**
>
> 本文记录 Stage 1.6 Planner 的架构定位、输入语义、Plan Schema、校验边界、失败契约、ChatLab 基线继承与 Trivae-specific 差异。Stage 1.6 已完成架构设计沉淀，但尚未实现；具体 Python 类型、模型、Prompt、参数、Trace Schema、Evaluation Dataset 与 Agent Runtime 生命周期仍保持 Pending。

---

## 0. Architecture Governance

Stage 1.6 遵循项目级 [Architecture Principle: ChatLab as Reference Implementation](../architecture.md#architecture-principle-chatlab-as-reference-implementation)。ChatLab 当前 Planner 架构是主要 baseline：适用于 Trivae 的 pre-execution planner、structured plan、bounded plan、available Tool filtering、invalid plan graceful skip、soft guidance injection 与 same Agent Runtime 默认继承。

默认继承 ChatLab 的架构不等于逐字复制 ChatLab 的 Prompt、Tool-specific heuristic 或经验参数。任何偏离都必须由 Trivae 的 Failure Case、Evaluation 结果、技术约束或新业务需求驱动，并记录 Reopen Reason。

Stage 1.6 不重新设计 Stage 1.1～1.5 已 Confirmed 的 Data Plane、Retrieval、Tool / Capability Layer 或 Router 边界。

## 1. Initial Design / Context：Planner 要解决的问题

Stage 1.5 已确认 Router 只负责判断是否值得在进入 Agent Runtime 前增加 Planner：

```text
standard_execution
    → Agent Runtime

planned_execution
    → Planner
    → soft guidance
    → same Agent Runtime
```

ChatLab 当前 Planner 的实际核心链路为：

```text
User Query
    ↓
Router
    ↓ planned_execution
Planner LLM
    ↓
Structured Plan
    ↓
Validation / Sanitization
    ↓
Plan Guidance
    ↓
追加进入 Agent System Prompt
    ↓
原有 Agent Core
    ↓
Agent 自主调用 Tools
```

Trivae 的问题不是要建立一个 Workflow Engine，而是希望复杂调查在 Runtime 开始前先得到少量高层调查指导，减少遗漏调查维度和过早收敛的风险，同时保留 Agent Runtime 根据真实 Tool Result 自主调整的能力。

### Evidence / Rationale

- ChatLab 当前实际执行链路已经验证了 pre-execution Planner、structured plan、validation / sanitization、soft guidance injection 与原有 Agent Core 的组合方式。
- Stage 1.5 已确认两种 Route 最终进入同一个 Agent Runtime，Planner 只能是 planned path 的额外 guidance 阶段。
- Stage 1.3～1.4 已确认 Retrieval Strategy、Tool Selection、Tool Arguments 与 Evidence Selection 的职责不属于 Router 或 Planner。
- 当前没有 Trivae Failure Case 或 Evaluation 证明需要 Workflow Engine、Step Executor、Planner Loop、State Machine 或 Automatic Replanning。

### Candidate Solutions

1. 引入 Workflow / DAG / Plan-and-Execute 框架，让 Planner 生成并驱动可执行步骤。
2. 让 Planner 只输出高层计划，但额外建立 Planner-owned State、Step Executor 或 Replanning Loop。
3. 采用 ChatLab-style 的 Thin pre-execution investigation planner，只生成经过 deterministic validation 的 soft guidance，由同一个 Agent Runtime 自主执行。

方案 1、2 都会把 Planner 推向执行编排层；方案 3 保留 ChatLab 已验证的核心结构，并与 Stage 1.5、Stage 1.4 的既有边界一致。

## 2. Decision 1：Thin pre-execution investigation planner

### Decision

Trivae Planner 定义为：

> **Thin pre-execution investigation planner**

Planner 只在 `planned_execution` 路径进入 Agent Runtime 前运行一次，负责复杂问题的高层调查拆解，不拥有独立 Agent Loop、Step Executor 或 Tool Calling 能力。

Planner 主要帮助 Runtime 理解：

```text
复杂问题的高层调查拆解
需要调查哪些子问题
调查的大致顺序
每个子问题需要什么类型的证据
哪些当前能力可能有帮助
整个调查达到什么程度可以认为足够完整
```

Planner 的定位是：

```text
Planner = Investigation Decomposition

NOT

Planner = Tool Execution Planner
```

### Explicitly Not Introduced

Stage 1.6 不引入：

```text
Workflow Engine
DAG Planner
Plan-and-Execute Framework
Step Executor
Planner Agent Loop
Automatic Replanner
Planner-owned State Machine
Planner Tool Calling
Planner-specific Retry Loop
```

### Why

Planner 的收益是给复杂调查提供结构，而不是把 Agent Runtime 的自治拆成另一套执行系统。把执行器、状态机和 Tool Loop 放进 Planner 会复制 Runtime 职责，扩大 Failure Surface，并使 `planned_execution` 变成与 `standard_execution` 不同的 Agent Runtime。

### Trade-off

Thin Planner 不能保证每一步都被执行，也不能强制复杂调查按照初始结构完成；换取较低耦合、较清晰的 Failure Attribution，以及保留 Runtime 对新证据和 Tool Result 的适应能力。

## 3. Decision 2：Same Agent Runtime + soft guidance

### Decision

`standard_execution` 与 `planned_execution` 最终进入同一个 Agent Runtime。`planned_execution` 的唯一区别是在 Runtime 前生成并注入 Plan Guidance：

```text
planned_execution
    → Planner LLM
    → Parse / Validate / Sanitize
    → Plan Guidance
    → same Agent Runtime
```

Plan 是：

```text
soft execution / investigation guidance
```

不是 mandatory workflow、execution contract 或必须逐步满足的状态图。Agent Runtime 可以参考 Plan，也可以在实际证据、Tool Result 或执行状态表明 Plan 不合适时偏离 Plan。

### Runtime Responsibility

Agent Runtime 继续负责当前状态下的具体执行，包括：

```text
是否调用 Tool
调用哪个 Tool
Tool 参数
Lexical / Semantic / Structured Retrieval 如何组合
SQL 怎么写
Search Query 怎么改写
是否调用 get_message_context
是否继续调查
什么时候停止 Tool Calling
证据不足时如何调整执行方式
是否偏离原 Plan
```

Planner 不能抢占上述自治边界。

### Result

两条 Route 的稳定关系为：

```text
User Query
    ↓
Router
    ├── standard_execution ──────────────┐
    └── planned_execution → Planner       │
                              ↓          │
                         soft guidance   │
                                          ▼
                                   Agent Runtime
                                          ↓
                                        Tools
```

## 4. Planner Responsibility Boundary

### Planner Does

Planner 负责：

```text
用户有哪些复杂调查目标
复杂问题如何拆成少量高层 investigation steps
每一步想解决什么问题
每一步需要哪类证据
哪些 Tool / Capability 可能有帮助
整个调查的 success criteria
```

### Planner Does Not

Planner 不负责：

```text
Tool execution
具体 Tool 参数
Lexical / Semantic / Structured Retrieval 的实时选择
Search Query 编写
SQL 编写
filters
top_k
rerank
Context Expansion 参数
具体 Evidence Selection
Citation
Step 状态执行
Retry
Fallback Workflow
Runtime Loop
Automatic Replanning
```

因此，Planner 只表达调查目标和 capability hint，不输出可直接执行的低层指令。

## 5. Planner Input：Runtime 注入的语义契约

### Decision

第一版 Planner Input 在概念层统一为：

```text
PlannerInput
├── user_query
├── query_context
├── data_snapshot
└── capability_summary
```

Input 由 Runtime 提供。Planner 不主动调用 Tool 获取上下文，也不通过 Tool Result 逐步完善自己的计划。

具体 Python class、字段类型、Pydantic Model、序列化格式和 package layout 保持 Pending。

### 5.1 `user_query`

Planner 必须理解当前用户请求的真实会话语义，不能假设每条输入都是 standalone query。

例如：

```text
上一轮：分析过去一年大家对 Cursor 的讨论变化。
当前：那 Claude Code 呢？
```

Planner 需要获得足够理解当前请求的：

> contextualized request / conversation context

Stage 1.6 只确认语义要求，不冻结以下 Context 设计：

```text
完整 history 注入
history window
conversation summarization
context compression
context token limit
```

### 5.2 `query_context`

`query_context` 表达：

> 当前用户请求要求系统在哪个查询范围内工作。

概念上可能包括：

```text
当前 ChatSession
用户指定的 session / sessions
明确时间范围
明确成员约束
当前群 / 跨群范围
timezone / current time 等与查询语义直接相关的信息
```

Query Context 必须继续遵守 Stage 1.4 的边界：

```text
Query Context
≠
Data Access Scope
```

Query Context 是用户请求的查询条件；Data Access Scope 是所有 Tool 都不得突破的硬授权边界。Planner 可以理解 Query Context，但不能扩大、重写或替代 Runtime / Tool Layer 的 Data Access Scope，也不能把 Query-specific filter 误解为底层数据实际上只有这些内容。

### 5.3 Compact `data_snapshot`

Planner 接收由 Runtime 注入的 **Compact Data Snapshot**。它的目的不是提前完成群聊分析，而是让 Planner 知道：

```text
有哪些数据
数据覆盖哪里
数据大概多大
哪些能力当前可用
```

第一版概念上可以包括：

```text
session identity / metadata

data coverage
    first_message_time
    last_message_time

scale
    message_count
    member_count

capability / index availability
```

例如语义索引当前不可用时，Planner 可以避免把 `semantic_search` 作为主要 suggested tool。

Data Snapshot 必须保持 Compact。第一版不默认注入：

```text
热门成员排名
热门关键词
主题统计
大量 segment summaries
大量聊天正文
预计算影响力判断
预计算语义结论
```

这些信息可能造成 Planning Anchoring，例如 Planner 看到某人发言最多后过早围绕该成员规划调查。是否加入更多 analytical hints 保持：

```text
Pending Evaluation
```

不要在 Stage 1.6 永久禁止，也不要默认加入。

### 5.4 `capability_summary`

Planner 需要知道当前能力的：

```text
name
purpose
important constraints
availability
```

结合 Stage 1.4 第一版 Tool Surface，概念上的高层 capability knowledge 为：

```text
lexical_search
    适合明确关键词、实体、术语查找
    Search Result 默认带 bounded local context

semantic_search
    适合语义相关讨论召回
    基于 conversation-oriented semantic retrieval
    Search Result 默认带 bounded local context

get_message_context
    对已知稳定 message_id 做进一步上下文恢复

find_members
    返回成员候选与匹配依据
    不保证唯一解析

get_schema
    获取真实 SQLite Physical Query Schema

execute_sql
    bounded read-only deterministic query / aggregation
    不承担 semantic classification
```

Planner 不需要完整 Tool JSON Schema、全部参数说明、SQL Manual 或完整错误码。完整 Tool Contract 留给 Agent Runtime。

### 5.5 Planner 不应该获得的输入

第一版以下内容不属于 Planner Input：

```text
Router diagnostic reason
大量聊天正文
Retrieval Result
Tool Result
Agent intermediate state
Evidence Object
Citation State
```

Router 的 `route`、`confidence`、`reason`、`source` 是 Router Decision 的诊断 / Trace 信息。Planner 被调用时只需通过 Runtime invocation boundary 知道自己处于 planned path；不要把 `reason` 当成业务输入继续喂给 Planner，避免 Router 对 Planner 产生不必要的 semantic anchoring。

Planner 第一版不能调用 Tool，也不能观察 Tool Result；否则会逐渐演变为 planning agent 或 planner-executor loop。

## 6. Plan Schema：轻量、静态、面向调查

### Decision

第一版 Plan Schema 在概念上定义为：

```text
Plan
├── version
├── title
├── intent
├── steps[]
│   ├── goal
│   ├── suggested_tools[]
│   └── evidence_needed
└── success_criteria[]
```

这只冻结语义结构，不冻结 Python / JSON 具体实现格式。

### 6.1 `version`

保留 Plan Schema version，用于未来 Schema Evolution。第一版概念版本可以为：

```text
version = 1
```

不因此设计 migration framework。

### 6.2 `title`

保留简短 Plan Title，主要用于：

```text
理解
Debug
Trace
未来可能的 UI
```

`title` 不参与执行决策。

### 6.3 `intent`

第一版保留 ChatLab-style intent taxonomy，作为 Trivae v1 的 baseline metadata vocabulary：

```text
summary
trend
relationship
search
comparison
evidence
mixed
```

该列表是 ChatLab 经验的第一版继承与实现 seed，不代表 Trivae 的长期 taxonomy 已冻结。是否长期保留、增加 Trivae-specific intent 或调整分类边界，保持 Pending Evaluation；在没有真实 Failure Case / Evaluation 证据前，不自行扩展。

`intent` 是 descriptive metadata，不是执行 Router。它可以用于 Trace、Evaluation、Debug 和 Plan explanation，但不能直接绑定 Tool 或 Retrieval：

```text
intent = trend   → semantic_search
intent = evidence → 某固定 Tool
```

均不是合法架构语义。若后续 Evaluation 证明 taxonomy 不适合 Trivae，再通过 Reopen Reason 调整。

### 6.4 Step `goal`

`goal` 描述：

> 该阶段需要解决的调查子问题或需要获得的认知结果。

好的例子：

```text
识别过去一年主要技术主题的阶段性变化
```

不好的例子：

```text
调用 semantic_search 搜索“AI 工具”
```

因此：

> `goal` MUST be outcome-oriented / investigation-oriented，不能是 Tool Invocation 描述。

### 6.5 Step `suggested_tools`

保留 `suggested_tools[]`，但它只是：

```text
advisory metadata / capability hint
```

它不是：

```text
required_tools
selected_tools
tool_calls
```

Agent Runtime 可以完全偏离建议。例如：

```text
Plan:
suggested_tools = semantic_search

Runtime:
semantic_search 不够
    → lexical_search
    → get_message_context
```

这是合法执行。一个典型 Failure Case 是用户要求精确定位并引用某条消息：Planner 可能建议 semantic_search，但 Runtime 根据实际证据需求改用 lexical_search 与 get_message_context。此时：

```text
Plan deviation ≠ Planner failure
```

Planner 可以建议 available Tool / Capability，但不得生成：

```text
semantic_search(
    query=...,
    top_k=...,
    filters=...
)
```

即：

```text
suggested_tools  可以
tool arguments   不可以
```

### 6.6 Step `evidence_needed`

`evidence_needed` 描述：

> 该调查 Step 要形成可靠判断，需要获得什么类型的支撑材料。

例如：

```text
能够体现两个成员在同一主题上观点差异的直接发言和局部上下文
```

它必须和 Stage 1.8 Evidence Model 区分：

```text
Planner evidence_needed
    = evidence requirement / guidance

Stage 1.8 Evidence
    = 实际被选中、验证和用于 Citation 的证据对象
```

Stage 1.6 不定义：

```text
evidence_id
evidence_status
confidence
citation_status
source locator schema
```

### 6.7 `success_criteria`

`success_criteria[]` 为 Agent Runtime 提供轻量的调查完成标准，例如：

```text
覆盖用户要求的实际可用时间范围
主要阶段变化都有证据支持
用户要求比较的主要对象均被覆盖
```

它仍然是自然语言 soft guidance。第一版不做 machine-enforced hard predicate，例如：

```text
必须找到 5 条 Evidence
confidence > 0.8
每季度必须 3 条消息
```

## 7. 第一版不增加 Workflow Fields

### Decision

第一版不加入以下字段：

```text
step_id
depends_on
condition
branch
status
priority
expected_output
intermediate_result
step_result
tool_arguments
search_query
SQL
filters
top_k
rerank parameters
retry
timeout
fallback
replan_policy
```

### 7.1 为什么不加入 `depends_on`

即使复杂请求存在依赖，第一版也通过 `steps` 顺序和 `goal` 自然语言表达：

```text
Step 1
判断群里是否真的出现过明显的工具迁移现象

Step 2
如果该变化得到数据支持，调查变化主要发生在哪些阶段

Step 3
围绕已识别阶段寻找原因和代表性讨论
```

这允许 LLM Agent Runtime 理解高层依赖，同时不需要定义 `step done`、`step result`、`partial success`、`condition evaluation` 或 `state transition`。加入机器可执行 dependency 会把 Planner 推向 declarative workflow engine。

### 7.2 Planner 不拥有 Execution State

Plan 是静态 guidance。Planner 不维护：

```text
pending
executing
done
failed
skipped
```

某 Step 是否执行、是否跳过、Agent 是否偏离 Plan，未来由 Stage 1.9 Trace / Observability 观察；不在 Stage 1.6 把 Planner 做成 State Machine。

## 8. Automatic Replanning

### Decision

第一版：

```text
No automatic replanning.
```

Planner 只在进入 Agent Runtime 前执行一次。如果执行过程中出现：

```text
原 Plan 假设错误
某个调查方向没有数据
某个 suggested tool 不适合
新的证据改变调查方向
```

Agent Runtime 可以直接偏离 Plan，不需要重新调用 Planner。理由是：

```text
Plan 是 soft guidance
不是 execution contract
```

只有未来 Evaluation 明确证明 Agent 被 Initial Plan anchoring 导致稳定遗漏新方向，且影响足够大，才重新评估 Replanning。

## 9. Planner Validation：Deterministic Parse / Validate / Sanitize

### Decision

LLM 输出不能直接进入 Agent Runtime。正确链路为：

```text
Planner LLM Raw Output
        ↓
Parse
        ↓
Structural Validation
        ↓
Sanitization / Bounding
        ↓
Validated Plan
        ↓
Plan Guidance
        ↓
Agent Runtime
```

Validation 必须保持 deterministic。第一版不增加第二个 LLM Plan Validator。

### 9.1 Structural Validation

概念上至少保证：

```text
version 合法
title 有效
intent 属于允许 taxonomy
steps 是非空集合
每个有效 step 存在 goal
每个有效 step 存在 evidence_needed
suggested_tools 结构合法
success_criteria 存在有效内容
```

具体实现 Schema、validator library、字段类型和错误表示保持 Implementation Pending。

### 9.2 Sanitization / Bounding

允许做确定性、轻量且不会改变调查语义的修正，例如：

```text
过滤不存在 / 不可用 Tool
去重 suggested_tools
限制 Steps 数量
限制 Success Criteria 数量
限制字段大小
```

原则为：

```text
符合 Contract
    → accept

可安全 deterministic sanitize
    → sanitize + accept

核心结构错误
    → invalid
```

不要设计复杂的“修复模型错误输出”兼容逻辑。Plan size 必须 bounded，但具体的 steps、criteria 和字段长度 limit 不在 Stage 1.6 冻结，保持：

```text
Pending Evaluation / Implementation calibration
```

### 9.3 Unavailable / Hallucinated Tool

如果 Planner 输出：

```text
suggested_tools:
    semantic_search
    nonexistent_tool
```

而当前只有 `semantic_search`，校验后保留 `semantic_search`，删除 hallucinated Tool。不存在或不可用的 suggested tool 被过滤本身不导致整个 Plan 失败。

如果某 Step 的所有 suggested tools 都被过滤：

```text
suggested_tools = []
```

只要 `goal` 与 `evidence_needed` 仍然合法，该 Step 仍可以有效存在，因为 Tool 只是 suggestion。

### 9.4 No Online LLM Plan Validator

第一版不采用：

```text
Planner LLM
    ↓
Validator LLM
    ↓
Agent Runtime
```

Schema、Tool availability、bounds 等由 deterministic validator 负责；Plan Quality 留给 Stage 1.10 Evaluation，通过 planned vs standard、with planner vs without planner、Answer Correctness、Evidence Completeness、Missed Dimensions、Latency、Tokens 与 Tool Calls 等实际结果判断。

### 9.5 Validator 不验证 Plan 的事实正确性

Deterministic Validator 只负责：

```text
结构是否合法
Tool 是否存在且可用
规模是否 bounded
```

它不负责判断：

```text
调查假设是否正确
某个时间段实际上有没有聊天
某个人是不是主要影响者
某个 Tool 是否最终真的能找到证据
```

Compact Data Snapshot 可以帮助 Planner 减少明显错误，但不能保证 epistemic correctness。若 Plan 的调查方向不符合实际证据，Agent Runtime 可以偏离 Plan。

## 10. Planner Failure Contract

### Decision

Planner 是：

```text
execution optimization / guidance layer
```

不是：

```text
request availability dependency
```

只要用户没有 abort、Agent Runtime 本身可用，无论 Planner 是否成功，都必须继续进入 Agent Runtime：

```text
planned_execution
        ↓
     Planner
     /     \
 success   failure
    |         |
 guidance    |
    |         |
    └────┬────┘
         ↓
    Agent Runtime
```

Planner failure 不允许让整个请求失败，也不允许被静默压成没有诊断意义的 `no plan`。未来 Trace 必须能做 Failure Attribution；Stage 1.6 只确认语义类别，不冻结 Stage 1.9 Trace Schema。

### 10.1 Failure Categories

第一版需要在语义上区分：

```text
generation_error
timeout
invalid_output
unavailable
aborted
```

`aborted` 表示 Planner invocation 被取消或中止；如果用户明确 abort 整个请求，则遵循更高层 Runtime 生命周期，不能为了继续执行而绕过用户 abort。

### 10.2 不重写 Router Decision

例如：

```text
Router:
route = planned_execution

Planner:
failed

Runtime:
executed_without_plan
```

Router Decision 是已经发生的事实。Planner Failure 是后续阶段的 degradation，不能把最终 Route 伪装成正常的 `standard_execution`。

## 11. No Planner-specific Retry / Regeneration

### Decision

第一版：

```text
No planner-specific retry contract.
```

Planner 失败或 Plan invalid 时直接 skip plan，进入 Agent Runtime：

```text
invalid plan
    → skip plan
    → Agent Runtime
```

不要在 Online Runtime 中增加：

```text
Planner failed
    → retry planner
    → fallback smaller model
    → regenerate
```

如果未来 SDK / Provider 层存在通用 transient retry，它属于 Agent Runtime / Provider 层的通用机制，不属于 Stage 1.6 Planner-specific policy；Stage 1.6 不提前定义其参数或适用边界。

### Reason

在线重试或二次生成会隐藏 Planner 输出可靠性问题，使 Stage 1.10 无法真实观察 `planner_invalid_output_rate` 及对应 Failure Attribution。应通过 Prompt、Structured Output 或模型选择改善，而不是在本阶段添加补救 Loop。

## 12. ChatLab Baseline 与 Trivae 差异

### 12.1 继承 ChatLab 的部分

Trivae 第一版继续继承 ChatLab Planner 的主要架构：

```text
pre-execution planner
structured plan
bounded plan
available tool filtering
invalid plan graceful skip
soft guidance injection
same Agent Runtime
```

这些继承都与 Stage 1.5 已确认的 `planned_execution → Planner → soft guidance → same Agent Runtime` 一致。

### 12.2 不机械继承的部分

ChatLab 当前 Planner Prompt 中可能存在 ChatLab-specific 业务 heuristic，例如：

```text
retrieve_chat_evidence
segment summaries
chart generation
specific specialized analysis tools
ChatLab-specific evidence planning heuristics
```

Trivae 不机械复制这些 Prompt / Tool-specific heuristic。原因不是否定 ChatLab Planner 架构，而是 Stage 1.4 已确认 Trivae 第一版 Tool Surface 为：

```text
lexical_search
semantic_search
get_message_context
find_members
get_schema
execute_sql
```

因此：

```text
继承 Planner architecture
≠
复制 ChatLab Planner Prompt 的全部业务经验
```

Trivae-specific Planner heuristic 必须由真实 workload、Failure Case 或 Evaluation 驱动；没有证据时保持：

```text
Pending architecture specification
```

## 13. Confirmed Architecture Decisions

| # | Decision | Confirmed 语义 |
| --- | --- | --- |
| 1 | **Thin pre-execution Planner** | Planner 仅在 `planned_execution` 进入 Agent Runtime 前执行一次，不拥有 Agent Loop 或执行器。 |
| 2 | **Same Agent Runtime** | `standard_execution` 与 `planned_execution` 最终进入同一个 Agent Runtime。 |
| 3 | **Soft guidance** | Plan 是 investigation guidance，不是 mandatory workflow；Runtime 可以根据实际证据偏离。 |
| 4 | **Runtime-injected Planner Input** | Input 由 Runtime 提供：`user_query`、`query_context`、compact `data_snapshot`、`capability_summary`。 |
| 5 | **Compact Data Snapshot** | 主要表达 coverage、scale、availability、basic environment metadata；更多 analytical hints 保持 Pending Evaluation。 |
| 6 | **Capability Summary instead of full Tool Manual** | Planner 获取 purpose、重要 constraint、availability；完整 Tool Schema 留给 Runtime。 |
| 7 | **Lightweight Plan Schema** | 概念字段为 `version`、`title`、`intent`、`steps[].goal`、`steps[].suggested_tools`、`steps[].evidence_needed`、`success_criteria`。 |
| 8 | **Intent is descriptive metadata** | 保留 `summary / trend / relationship / search / comparison / evidence / mixed`，不绑定 Route、Tool 或 Retrieval。 |
| 9 | **Outcome-oriented Plan Step** | `goal` 描述调查问题或认知结果，不描述 Tool Invocation。 |
| 10 | **suggested_tools is advisory** | 只是 capability hint；Runtime 不受约束；不生成 Tool Arguments。 |
| 11 | **evidence_needed is requirement, not Evidence Object** | 只描述所需证据类型；实际 Evidence / Citation 留给 Stage 1.8。 |
| 12 | **No workflow fields in v1** | 不增加 `step_id`、`depends_on`、`condition`、`branch`、`status`、`expected_output`、`intermediate_result`、`retry`、`fallback`、`tool_arguments` 等字段。 |
| 13 | **No Planner-owned execution state** | Planner 不维护 step status 或 state machine；执行与偏离由未来 Trace 观察。 |
| 14 | **No automatic replanning in v1** | Planner 只运行一次；执行中由 Agent Runtime 自主调整。 |
| 15 | **Deterministic validation** | LLM Plan 必须经过 parse、structural validation、bounded sanitization 后才能注入 Runtime。 |
| 16 | **Hallucinated Tool filtering** | 不存在或不可用的 suggested tool 被过滤，不因此让整个 Plan 失败。 |
| 17 | **Bounded Plan** | Steps、Criteria 与字段规模必须 bounded；具体 limit 保持 Pending Evaluation / Implementation calibration。 |
| 18 | **No online LLM Plan Validator** | 不增加第二个 LLM Validator；Plan Quality 留给 Stage 1.10 Evaluation。 |
| 19 | **Planner failure graceful degradation** | generation error、timeout、invalid output、unavailable 等不阻塞 Runtime；用户未 abort 且 Runtime 可用时无 Plan 继续执行。 |
| 20 | **Do not rewrite Router Decision after Planner failure** | 保留 `route = planned_execution`、`planner = failed`、`runtime = executed_without_plan` 的语义。 |
| 21 | **No Planner-specific retry / regeneration in v1** | Planner 失败或 Plan invalid 时直接 skip；是否未来增加机制必须由真实 Evaluation 重新评估。 |

## 14. Pending Decisions

以下事项不在 Stage 1.6 提前解决：

### Implementation Pending

```text
Planner 具体 Python class / package layout
具体 Planner Model
具体 Prompt
Structured Output 技术
temperature
max tokens
timeout
Plan 的具体 Python / JSON serialization
具体 validator library
具体 max steps
具体 max success criteria
具体字段长度 limit
Compact DataSnapshot 的完整 schema
Planner Guidance 的具体注入实现
```

### Stage 1.7 Pending

```text
Agent Loop / SDK / Runtime lifecycle
Planner 与 Agent Runtime 的具体 adapter 契约
Session、Streaming、Abort 的生命周期语义
Conversation Context 的 history window / summarization / compression / token 控制
```

### Stage 1.8 Pending

```text
Evidence / Citation model
Evidence Object 的 status、confidence、citation state 与 source locator schema
```

### Stage 1.9 Pending

```text
Planner Trace Schema
Planner failure event names / fields / storage
Planner metrics
是否需要 step-level execution trace
```

### Stage 1.10 Pending

```text
Planner Evaluation Dataset
planned vs standard、with planner vs without planner 的评测方法
Planner latency threshold
Planner cost budget
Planner latency budget / invocation policy
具体 bounds 的参数校准
是否需要更多 intent 类型
是否未来需要 replan
```

以上 Pending 项不能因为 Stage 1.6 已 Confirmed 就被默认补全。除非新 Failure Case、技术约束、Evaluation 结果或业务需求触发 Reopen Reason，否则本 ADR 的 Confirmed 决策保持冻结。

## 15. Validation / Regression

当前仓库没有业务代码，因此本阶段不添加 Planner 实现测试，也不伪造 Planner Evaluation 结果。实现阶段至少应围绕以下语义契约建立可验证检查：

```text
valid Plan 能通过 parse / validation / sanitization
intent 非法时 Plan 不直接进入 Runtime
核心结构 invalid 时 skip plan 并继续 Runtime
hallucinated Tool 被过滤
所有 suggested_tools 被过滤时，合法 Step 仍可保留
Plan size 被 bounded
Planner failure 不阻塞 Agent Runtime
Planner failure 不重写 Router Decision
Planner 不观察 Tool Result、不拥有执行 state、不触发 automatic replanning
```

Stage 1.10 应通过真实 workload 比较 planned 与 standard 路径，至少观察 Answer Correctness、Evidence Completeness、Missed Dimensions、Latency、Tokens 与 Tool Calls；不能只通过“Plan 看起来合理”判断 Planner Quality。

## 16. Result、Trade-off 与 Reopen Conditions

### Result

Stage 1.6 将 Planner 固定为一个轻量的、一次性的 pre-execution investigation guidance layer：

```text
planned_execution
    → contextualized Planner Input
    → structured Plan
    → deterministic validation / sanitization
    → soft Plan Guidance
    → same Agent Runtime
```

Plan 只能帮助 Runtime 组织调查，不能把 Runtime 变成强制 Workflow，也不能改变 Router 已经做出的 Route Decision。

### Trade-off

该设计保留了 ChatLab Planner 的主要架构收益，且适配 Trivae 当前 6 个 Tool 的 capability surface；代价是 Plan 不保证执行完整性，具体调查质量仍依赖 Agent Runtime、Retrieval、Evidence 与 Evaluation。少量结构字段换取较低的 Planner 复杂度，但不提供机器可执行 dependency、state、retry 或 replan。

### Reopen Conditions

以下情况可以重新打开本 ADR，但必须记录 Reopen Reason：

- Evaluation 证明 Initial Plan anchoring 稳定导致 Agent 遗漏新方向，且 Runtime 自主偏离不足以恢复；
- 可复现的 Planner Failure 违反“继续进入 Runtime”的可用性契约；
- invalid output、timeout 或 unavailable 成为显著质量 / 延迟问题，且基础 Prompt、Structured Output 或模型调整无法解决；
- Trivae 新业务需求确实需要当前明确排除的 workflow、state、replan 或 Tool 参数语义；
- 真实 Evaluation 证明 ChatLab 继承的 Planner architecture 不适用于 Trivae 当前 workload。

单纯因为“标准 Agent 架构通常更复杂”“未来可能有 UI”或“以后可能有用”不能重新打开 Confirmed 决策。
