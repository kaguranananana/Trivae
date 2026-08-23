# Stage 1.7: Agent Runtime Decisions

> 状态：**Confirmed（Stage 1.7）**
>
> 本文记录 Stage 1.7 Agent Runtime 的架构定位、SDK 选型、Agent Loop 承载方式、Context 与 Conversation History 归属、生命周期语义、终止条件、Abort / Streaming 契约、Planner→Runtime adapter，以及 SDK 与 Capability 的解耦边界。Stage 1.7 已完成架构设计沉淀；具体 SDK 版本、Adapter 契约、参数数字、Runtime Event Schema 与 Trace 字段以实现规范和验证记录为准。
>
> 实现状态补充（M4/M5a/M5b）：`QueryRequest → persisted history → Router → optional Planner → shared AgentRuntime`、SDK 0.22.0 streamed adapter、tool-round finalization、RuntimeEvent、cancellation、Application lifecycle、current-run Tool Result provenance 与 validated Artifact 的 Conversation commit 已落地；Trace backend 和 Evaluation 仍按各自 Implementation task 保持 Pending。

---

## 0. Architecture Governance

Stage 1.7 遵循项目级 [Architecture Principle: ChatLab as Reference Implementation](../architecture.md#architecture-principle-chatlab-as-reference-implementation)。

ChatLab 当前的 runtime 架构是主要 baseline。Trivae 继承的是 ChatLab 的 **runtime architecture**（Thin Agent Core、`runAgentCore()` 之前的上下文准备与 Router / Planner 编排、budget-exhausted graceful final synthesis、事件归一化等），不是必须照搬它使用的具体 Agent Core library（ChatLab 用 `@earendil-works/pi-agent-core`，Trivae 第一版用 OpenAI Agents SDK）。

### 参数继承口径

ChatLab 的 `max_tool_rounds`、history window、compression threshold 等属于**经验参数**。Trivae 允许把这些经验参数**直接继承作为 v1 baseline**，但必须同时满足：

1. 在文档 / 实现中标注**继承来源**（来自 ChatLab 经验参数，而非 Trivae 自研或凭空设定）；
2. 保留 Evaluation 校准路径：数字不视为冻结常量，Stage 1.10 依据真实 Trivae workload 校准；
3. 不把"可直接继承"理解成"无条件照抄"或"拒绝继承"——两者都错误。继承的是经过实际运行验证的参数值；若 Trivae 的约束（数据规模、模型、Tool Surface、成本）明显不同，才需要偏离，且偏离必须有证据。

任何偏离 ChatLab 基线的架构变化仍按架构治理规则记录：范围、触发 Failure Case / 技术约束、收益、新增复杂度、验证方法。

### 参考实现核验快照

Stage 1.7 的参考事实按以下快照核验，避免“ChatLab 当前实现”或“SDK 当前行为”随上游演进而失去具体含义：

- 核验日期：2026-08-21。
- ChatLab baseline：commit [`f9b87c00`](https://github.com/ChatLab/ChatLab/commit/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264)；其 Agent Core 在一次包含 Tool Result 的 `turn_end` 后增加一个 Tool Round，同一轮并行多个 Tool 仍计为一轮，并在达到上限后禁用 Tool、注入 final-answer steer message。
- OpenAI Agents SDK baseline：本阶段按 `openai-agents` 0.22.0 的能力面核验；[OpenAI Agents SDK 官方文档](https://developers.openai.com/api/docs/guides/agents/running-agents)用于确认 Runner / Agent Loop 的产品边界，[OpenAI Conversation API](https://developers.openai.com/api/reference/python/resources/conversations/methods/create)用于确认 Provider 侧也可能持有 Conversation Items。
- 实现阶段必须锁定实际 SDK 版本，并用本 ADR 的 Validation / Regression 契约重新验证 Tool Error、Tool visibility、turn accounting、stream completion、cancellation 与 tracing 行为；上游默认行为不自动成为 Trivae 契约。

该快照用于说明证据来源，不把 ChatLab 参数值或 SDK 版本冻结成 Trivae 长期常量。

Stage 1.7 不重新设计 Stage 1.1～1.6 已 Confirmed 的 Data Plane、Retrieval、Tool / Capability Layer、Router 或 Planner 边界。

## 1. Initial Design / Context：Agent Runtime 要解决的问题

### 1.1 承接的遗留边界

Stage 1.6 明确把以下内容留给 Stage 1.7：

```text
Agent Loop / SDK / Runtime lifecycle
Planner 与 Agent Runtime 的具体 adapter 契约
Session、Streaming、Abort 的生命周期语义
Conversation Context 的 history window / summarization / compression / token 控制
```

Stage 1.5 已确认两种 Route（`standard_execution` / `planned_execution`）最终进入**同一个 Agent Runtime**；Stage 1.6 已确认 Planner 是 pre-execution investigation planner，输出 soft guidance。Stage 1.4 已确认 Capability 不依赖具体 Agent Runtime，且 Tool 层使用统一 `ok / partial / error` Envelope 并禁止 silent fallback。

Stage 1.7 需要回答的核心问题是：

> 在复用成熟 Agent SDK 承载通用 Agent Loop 的前提下，Trivae 自己拥有哪部分执行语义？哪些必须留在 Trivae 侧、哪些可以下沉到 SDK？

### 1.2 ChatLab 实际做法

ChatLab 并没有手写一整套复杂 Agent Runtime。真正的 Agent Loop 被压缩在一个很薄的 `runAgentCore()` 里：

```text
Agent Core
  构建 Agent
  → 历史转换
  → 事件订阅
  → abort 转发
  → prompt 执行
  → usage 收集
```

真正负责 `LLM → Tool Call?（yes → execute tools → append results → LLM / no → final answer）` 的是 `PiAgentCore`。而 Router、Planner、Context Compression、History Loading、Tool Assembly 都在 `runAgentCore()` 外面。CLI 的真实路径为：

```text
build system prompt
        ↓
context compression
        ↓
load history
        ↓
assemble tools
        ↓
Router
        ↓
optional Planner
        ↓
append Plan Guidance
        ↓
runAgentCore()
```

这一点直接回答了 Stage 1.7 最容易设计错的地方：

> **Agent Runtime 不应该重新吞掉 Router、Planner、Retrieval、Evidence 等职责。**

### Evidence / Rationale

- ChatLab 已用实际运行验证了 Thin Agent Core + 外层编排的结构：通用 Loop 由核心库承载，领域职责留在外面。
- Stage 1.5 / 1.6 已确认 Router、Planner 与 Agent Runtime 的职责边界，Stage 1.7 只是继续让 Runtime 尊重该边界。
- OpenAI Agents SDK 的 `Runner` 已提供通用 Loop、`run_streamed()`、`max_turns`、Run Context、生命周期 Hooks；自行重写 `while true → call model → parse tool call → execute → append → call model` 在 Trivae 这里收益很低。
- Stage 1.4 已确认 Capability 不绑定具体 Runtime；Stage 1.7 把该约束推广到 Runtime 与 SDK 的整个接触面。

### Candidate Solutions

1. 自行手写完整 Agent Loop（while-loop + tool parsing + context append），不依赖 Agent SDK。
2. 直接使用 Agent SDK，但让 Trivae 业务代码到处依赖 SDK 类型（Agent、RunContextWrapper、SDK Item、Session）。
3. 复用成熟 Agent SDK 承载通用 Loop，通过薄适配层隔离：`Trivae AgentRuntime interface → OpenAIAgentsRuntimeAdapter → SDK`。

方案 1 重复造轮子且丧失 SDK 的 streaming / cancellation / tracing 能力；方案 2 会把整个业务系统绑死到某个 SDK；方案 3 继承 ChatLab 已验证的架构，并保持 Trivae 对 Context、Conversation、Tool、事件契约的 ownership。

## 2. Decision 1：Thin Agent Runtime + SDK 承载通用 Agent Loop

### Decision

Trivae 的 Agent Runtime 定义为：

> **Single-agent execution runtime，负责驱动模型与 Tool 之间的 bounded Agent Loop，并提供稳定的 streaming、cancellation、termination 和 result boundary。**

通用 Agent Loop 由成熟 Agent SDK（第一版：OpenAI Agents SDK）承载，Trivae **不自行重写通用 Agent Loop**。Trivae 自己拥有外层执行编排、Context、Conversation History、Tool Adapter、生命周期语义和事件契约。

第一版只引入**单 Agent**，不引入 handoff / multi-agent。

### Runtime 职责明细

| 项目 | Stage 1.7 决策 |
| --- | --- |
| Agent Loop | 由成熟 Agent SDK 承载，不自行重写通用 Loop |
| Runtime 数量 | `standard_execution` / `planned_execution` 使用完全相同的 Runtime |
| Agent 数量 | 第一版单 Agent，不引入 handoff / multi-agent |
| Tool Selection | Runtime 中的 Agent 根据当前状态自主决定 |
| Tool Arguments | Runtime 中的 Agent 自主生成 |
| Retrieval Strategy | Agent 自主组合 Lexical / Semantic / Structured |
| Plan | 只作为 soft guidance 注入，不做 Step Executor |
| Tool Result | 回到 Agent Loop，由模型决定下一步 |
| Streaming | 作为第一等执行路径 |
| Abort | Runtime 必须完整向 SDK 和正在运行的 Tool 转发 |
| Loop Bounds | 必须 bounded，但具体数字由 Evaluation 校准（可继承 ChatLab 经验参数） |
| Context | Trivae 管理并编译后交给 SDK |
| Conversation History | Trivae 是 source of truth，不交给 SDK 私有 Session 做唯一持久化 |
| SDK Events | 转换成 Trivae-owned Runtime Events，不向上暴露 SDK 类型 |
| Retry / Model Fallback | v1 不增加 Trivae-specific 自动 retry / fallback |
| Trace | Runtime 暴露观察点；Stage 1.9 已确认正式 normalized event / Trace conceptual boundary，具体 Schema / 实现 Pending |

### Why

继续 Stage 1.6 已冻结的边界：是否调用 Tool、调用哪个 Tool、SQL 怎么写、Search Query 怎么改、是否继续调查、什么时候停止、是否偏离 Plan，全部属于 Agent Runtime。SDK 只提供通用循环机制，不承担 Trivae 领域决策。

### Trade-off

- 复用 SDK 意味着 Trivae 接受 SDK 对 Agent Loop、流式、取消机制的实现方式；Trivae 通过适配层保留替换能力。
- 不自行写 Loop 换取可靠性、维护成本与 streaming / cancellation 能力；代价是 Trivae 对 Loop 内部细节的控制力弱于自研。

### 明确不引入

Stage 1.7 v1 **不引入**：

```text
Custom hand-written general Agent Loop
Multi-Agent Runtime
Agent Handoff architecture
Planner Agent Loop
Plan-and-Execute / Step Executor
Workflow Engine
Automatic Replanning
Runtime-owned Evidence State Machine
SDK Session as canonical conversation storage
SDK-specific types leaking into Capability Layer
Mid-run automatic context summarization
Application-level automatic model fallback
Application-level retry loop
Custom Tool orchestration scheduler
Hard-coded Retrieval workflow
```

其中 Automatic Replanning、Planner-owned State、Workflow Engine 已被 Stage 1.6 排除；Stage 1.7 的 Runtime 继续尊重该决定，不绕过。

## 3. Decision 2：SDK 选型——OpenAI Agents SDK + 薄适配层

### Decision

第一版 Python Agent Runtime 的 SDK 选定为 **OpenAI Agents SDK**，通过薄适配层接入：

```text
Trivae AgentRuntime interface
             │
             ▼
OpenAIAgentsRuntimeAdapter
             │
             ▼
OpenAI Agents SDK
```

OpenAI Agents SDK 的 `Runner` 已直接提供通用 Loop：

```text
LLM invocation
    ↓
final_output → stop

tool calls
    ↓
execute tools
    ↓
append results
    ↓
next LLM invocation
```

并支持 `run_streamed()`、`max_turns`、Run Context、生命周期 Hooks 等。

### 不这样用

```text
Trivae business code
    ↓
到处直接 import agents.Agent
到处直接 import RunContextWrapper
Tool 直接写死 SDK 类型
History 直接存 SDK Item
```

### 替换面

未来真的需要换掉 OpenAI Agents SDK 时，主要替换：

```text
OpenAI Agents Runtime Adapter
OpenAI Function Tool Adapter
```

而不是 Retrieval、SQLite、Context Expansion、Identity 等整个业务系统。这里确认的是 SDK 的概念替换面；Stage 1.11 已确认单 distribution 与概念 package ownership，但不冻结具体文件名、class 或 adapter 实现。Stage 1.4 已要求 Capability 不能绑定具体 Runtime，Stage 1.7 把该约束扩展到 Runtime 与 Tool 的 SDK 接触面。

### Why

继承 ChatLab 的 runtime architecture，但 Trivae 是 Python 项目，ChatLab 的 `@earendil-works/pi-agent-core`（TS）不是直接可用的库。OpenAI Agents SDK 提供 Trivae 需要的通用 Loop、streaming 与 cancellation 能力，且不与 Trivae 领域业务耦合。

### Trade-off

依赖第三方 SDK 引入版本演进与外部行为变化的风险；由适配层与版本锁定管理。换取的是通用 Loop、streaming、cancellation、Hooks 等成熟能力。

## 4. Decision 3：Query Execution Orchestration 与 Agent Runtime 的区分

### Decision

明确两个概念，消除既有文档中的表面矛盾（"Runtime 给 Router / Planner 注入 Context" 与 "Router / Planner 在 Agent Runtime 之前"）：

```text
Request Orchestrator
    负责整个 Query 生命周期（Context Assembly → Router → Planner → Runtime → Result）

Agent Runtime
    从 Agent Loop 启动开始负责执行核心
```

`Query Execution Orchestration` 第一版只是一个 service/function，不需要成为新的重"架构层"。

### 整体结构

```text
                    Query Execution Orchestration
                              │
            ┌─────────────────┴──────────────────┐
            │                                    │
      Context Assembly                     Runtime Context
            │                                    │
            └─────────────────┬──────────────────┘
                              ▼
                           Router
                              │
               ┌──────────────┴──────────────┐
               │                             │
        standard_execution            planned_execution
               │                             │
               │                         Planner
               │                             │
               │                    validate / sanitize
               │                             │
               │                      soft guidance
               └──────────────┬──────────────┘
                              ▼
                    AgentExecutionInput
                              │
                              ▼
                 ┌────────────────────────┐
                 │     Agent Runtime      │
                 │     OpenAI Agents SDK  │
                 │        Runner          │
                 │          │             │
                 │     Agent Loop         │
                 └──────────┬─────────────┘
                            │
                    Function Tool Adapter
                            │
                            ▼
                Trivae Agent-facing Tools
                            │
                            ▼
                     Capability Layer
                            │
                            ▼
                Retrieval / SQLite / Index
```

## 5. Decision 4：两种 Context 分离（RuntimeContext 与 Agent Model Context）

### Decision

Stage 1.7 作为 Confirmed Decision：

```text
Local Context      ≠      LLM-visible Context
```

OpenAI Agents SDK 本身也区分两者：`RunContextWrapper.context` 只存在于本地代码里，会传给 Tool、Hook 等，**不会发给 LLM**。这正好落实 Trivae 已确认的 `Data Access Scope ≠ Query Context`。

### RuntimeContext（不直接给 LLM）

```text
RuntimeContext
├── run / request identity
├── conversation identity
├── data_access_scope              # 硬权限
├── capability dependencies
├── database / retrieval handles
├── cancellation state
└── runtime budgets
```

### Agent Model Context（LLM 实际看到）

```text
Agent Model Context
├── system instructions
├── bounded conversation context
├── current user request
├── relevant query-context projection
├── compact session/data metadata
└── validated plan guidance?       # planned_execution only
```

### Data Access Scope 硬执行

```text
Data Access Scope
    ↓
必须在 Tool / Capability 执行路径中强制执行
```

不能：

```text
Data Access Scope
    ↓
写进 system prompt
    ↓
"希望模型记得别越界"
```

这正是 Stage 1.4 已确认的硬授权边界在 Runtime 层的落地：权限判断不依赖模型自觉，而由 Tool / Capability 执行路径强制执行。

## 6. Decision 5：Conversation History 由 Trivae 持有，v1 不用 SDK Session 作为 source of truth

### Decision

OpenAI Agents SDK 有 `Session`、`SQLiteSession`，可自动保存 / 恢复 Agent history。但 Trivae 第一版**不用它作为 canonical conversation storage**。

Trivae 采用：

```text
Trivae Conversation Store          # source of truth
        │
        ▼
Conversation Context Compiler
        │
        ▼
SDK-compatible input items
        │
        ▼
Runner
```

ChatLab 也是同样做法：自己维护 AI Conversation History，进入 `PiAgentCore` 前执行 `Persisted Chat History → history adapter → Pi Agent Messages`，并把历史中的 Tool Call / Tool Result 恢复成结构化消息，而不是把所有内容 flatten 成纯文本。Trivae 继承该语义。

### SDK / Provider 状态边界

不仅 SDK `Session` 不能成为 source of truth，SDK / Provider 提供的 `conversation_id`、`previous_response_id` 或其他 server-managed conversation state 也只能作为可替换的传输优化或关联标识：

```text
Trivae Conversation Store
    = canonical source of truth

SDK Session / Provider Conversation / previous_response_id
    = optional adapter state
    ≠ canonical history
```

任何优化都必须能够仅根据 Trivae Conversation Store 重建有效模型输入；不能出现一部分历史只存在于 Provider、导致 replay / migration / evaluation 无法复现的状态。

### Conversation 提交语义

Stage 1.7 冻结最小提交边界，具体表结构与 transaction 实现保持 Pending：

- Streaming delta 是临时展示事件，不直接作为 canonical assistant message 持久化。
- Tool Call / Tool Result 必须保持结构化关联，不能 flatten 成无法 replay 的纯文本。
- `COMPLETED` 仅在 SDK Run 真正完成后提交完整 assistant message。
- `ABORTED` / `FAILED` 可以保留 partial output 与已发生 Tool 记录用于诊断或恢复，但必须携带非完成状态，默认不能作为一个完整 assistant turn 参与后续 Conversation replay。
- request / run identity 必须让 canonical conversation item、Runtime Event 与 Trace 能够关联；Stage 1.9 已确认 `request_id / trace_id / event_id / operation causality` 的概念语义，具体字段类型与存储 Schema 留给实现。

### Why

未来需要 conversation branching、edit / regenerate、context compression、debug replay、prompt migration、更换 Agent SDK、Evidence / Citation 回放、Evaluation replay 时，都不会被某个 SDK 的 Session 表示绑住。

### 判断

> SDK Session 可以以后作为 adapter / optimization 重新评估，但 v1 不把它作为 Trivae Conversation 的 source of truth。

## 7. Decision 6：Context 压缩发生在 Agent Runtime 之前

### Decision

ChatLab 把 Context Compression 放在 Agent Core 之前，而不是 Agent Loop 中途突然压缩。Trivae 继承：

```text
Conversation Store
        ↓
Context Compiler
        ↓
token budget check
        ↓
必要时 compression / summarization
        ↓
bounded Agent Context
        ↓
开始 Agent Runtime
```

第一版**不做 mid-run compaction**：

```text
Agent 已经执行了一半
    ↓
突然达到 token limit
    ↓
Runtime 自己调用一个 summary agent
    ↓
把当前状态压缩
    ↓
继续
```

mid-run compaction 会显著增加状态复杂度和 Failure Attribution 难度。Stage 1.4 已把所有大结果 Tool 设计成 bounded，第一版本来就尽量避免"一次 Tool Result 把上下文撑爆"。

### 不冻结的数字

`history window`、`summary threshold`、`summary token budget`、`tool-result retention`、`compression model` 这些数字和算法交给实现和 Evaluation 校准，不在架构层冻结。可继承 ChatLab 经验参数作为 v1 baseline，但标注来源并保留校准路径。

## 8. Decision 7：终止条件两层——Tool Investigation Budget + SDK max_turns 兜底

### Decision

ChatLab 到达 Tool Round 上限后不是直接报错，而是：

```text
达到 Tool Round Budget
        ↓
禁用所有 Tool
        ↓
向 Agent 注入"基于已收集信息给出最终回答"
        ↓
最后一次 synthesis
        ↓
结束
```

Trivae **原样继承**该 graceful final synthesis 语义。因此 Loop 为：

```text
                  ┌──────────────────────┐
                  │      LLM Turn        │
                  └──────────┬───────────┘
                             │
                   ┌─────────┴──────────┐
                   │                    │
              final answer          tool calls
                   │                    │
                   ▼                    ▼
              COMPLETED           execute tools
                                        │
                                        ▼
                                  tool result
                                        │
                              budget remaining?
                                  /          \
                                yes           no
                                │             │
                                └── loop      ▼
                                         disable tools
                                              │
                                              ▼
                                         final synthesis
                                              │
                                              ▼
                                           COMPLETED
```

OpenAI Agents SDK 的 `max_turns` 超限会抛 `MaxTurnsExceeded`，不能简单地说"直接依赖 SDK 的 max_turns 就结束了"。因此是两层：

```text
Trivae Tool Investigation Budget
    → 达到上限后 graceful final synthesis

SDK max_turns
    → absolute safety backstop
    → 如果真的撞到，显式 Runtime Failure
```

SDK 支持运行时动态隐藏 Tool，"进入 finalizing 后让 Tool 对 LLM 不再可见"可以比较干净地实现。

### Tool Round 计数语义

Trivae 继承 ChatLab 的计数单位：

```text
一次模型轮次产生一个或多个 Tool Call
        ↓
该轮 Tool Call 全部完成并形成 Tool Result
        ↓
计为 1 个 Tool Round
```

同一模型轮次内并行或顺序执行多个 Tool，都只计一个 Tool Round；只有不包含 Tool Call 的最终回答轮次不计入 Tool Round。计数在该轮 Tool Result 已形成后增加，随后判断是否进入 `FINALIZING`。

### 两层 Budget 的关系约束

具体数字保持 Pending，但实现必须满足以下关系：

- SDK `max_turns` 按模型调用计数，必须严格覆盖允许发生的全部 Tool-bearing turns，并至少为 graceful final synthesis 预留一次额外模型调用。
- Trivae Tool Investigation Budget 必须先于 SDK absolute backstop 触发正常 `FINALIZING`；正常预算耗尽不能被误记为 `MaxTurnsExceeded`。
- `FINALIZING` 期间所有 Tool 对模型不可见；如果 final synthesis 本身发生 fatal model / provider / adapter failure，则显式进入 `FAILED`，不增加隐藏 retry 或 fallback。
- Tool 并发策略可以在实现阶段决定，但不能改变上述 Round 计数和 final synthesis 预留语义。

### 不冻结的数字

`max_tool_rounds` 与 SDK `max_turns` 的具体数字不冻结：前者需要真实 Agent workload，后者与 Tool Round / finalization 联动需要测试。可继承 ChatLab 经验参数作为 v1 baseline，标注来源并保留校准路径。

## 9. Decision 8：Tool Error ≠ Agent Run Error

### Decision

例如：

```text
semantic_search
    → CAPABILITY_UNAVAILABLE
```

合理行为不是 Runtime 整体 crash，而是：

```text
Tool Result
status = error
error.code = CAPABILITY_UNAVAILABLE
        ↓
返回 Agent
        ↓
Agent 根据错误决定：
    换 lexical_search
    / 使用 SQL
    / 明确告诉用户能力不可用
    / 基于现有证据回答
```

Stage 1.4 已确认 Tool 有统一 `ok / partial / error` 语义，且禁止 Tool 层 silent fallback。ChatLab Core Test 专门覆盖了"Tool 抛异常后产生 error Tool Result，但 Agent Loop 仍能恢复并给出答案"。

```text
Tool failure
≠
Runtime failure
```

### 可恢复 Tool Error 与 Runtime Failure 的边界

只有**已知、已分类、属于 Tool Contract 的失败**才能转换成 `status=error` Tool Result，例如 capability unavailable、明确的 invalid argument、scope violation 或 bounded execution failure。Agent 可以基于这种结构化错误调整调查路径。

以下属于 terminal runtime / orchestration failure 的典型情况：

```text
model/provider request fatal failure
SDK runtime invariant failure
无法构造有效模型输入
absolute loop limit exceeded
unrecoverable context overflow
未分类的 Tool / Capability 异常
Tool Adapter / Event Adapter / History Adapter invariant failure
final synthesis fatal failure
```

OpenAI Agents SDK 自身可能把 Function Tool 异常格式化成模型可见的 generic error。Trivae Tool Adapter 必须显式接管该边界：只映射已知 Tool Contract Error；未知异常继续抛出并使 Run `FAILED`，保留原始错误与 Trace，不能用 generic Tool Result 静默吞掉程序缺陷。

Stage 1.9 已确认 Error Code 由 contract owner namespace 拥有、跨层传播不改名；具体 Error Code 枚举与 Exception mapping 仍留给实现，Stage 1.7 不抢 Trace Schema 的工作。

## 10. Decision 9：Abort 生命周期

### Decision

```text
User Abort
    = terminal intent
```

具体语义：

```text
abort before Runtime
    → 不启动 Agent

abort during model streaming
    → cancel model run

abort during Tool
    → cancellation signal 继续向 Tool / Capability 传播

abort after tool result but before next turn
    → 不再开始下一轮

abort
    → ABORTED
    → 不执行 final synthesis
```

### 与 Tool Budget 耗尽的区别

```text
Tool Budget exhausted
    → 用户没取消
    → final synthesis

User Abort
    → 用户明确要求停止
    → 立即停止
```

OpenAI Agents SDK 的 streamed run 支持 `cancel()`，默认 immediate，也支持 `after_turn`。用户主动停止这一语义，v1 使用 **immediate**。

这里的 immediate 表示“立即接受终止意图并停止启动新的模型轮次 / Tool 工作”，不承诺任意同步阻塞调用都能被物理瞬时打断。Runtime Adapter 必须取消 SDK Run 并传播 cancellation signal；Tool / Capability 必须采用协作式 cancellation。`ABORTED` 在取消传播与必要清理完成后成为终态，晚到的 Tool Result 不得重新启动 Agent Loop，也不得触发 final synthesis。

### 易踩坑点

最后一个 token 出来 ≠ streamed run 已经结束。SDK 要求继续消费 `stream_events()` 到 iterator 完成，因为清理、Session 等收尾可能发生在最后一个可见 token 之后。因此 Runtime 的 `COMPLETED` 以 **SDK Run 真正完成**为准，而不是 UI 看见最后一个文字 token。

## 11. Decision 10：Streaming 是 canonical path

### Decision

ChatLab 是 Core Event → Event Handler → UI / CLI Stream 的结构，业务层不直接依赖 `PiAgentEvent`，而是转成自己的事件（`content / tool_start / tool_update / tool_end / turn_end / usage_update ...`），外面再由 `AgentEventHandler` 转成应用状态与 stream chunk。

Trivae 完全继承：

```text
OpenAI SDK StreamEvent
        ↓
OpenAIAgentsRuntimeAdapter
        ↓
Trivae Runtime Event
        ↓
CLI / API / future UI
```

绝对不要：

```text
FastAPI
    ↓
直接返回 SDK StreamEvent
```

否则 Stage 1.11 API 和正式 Trace 都会被 SDK 类型绑定。Stage 1.7 先冻结**事件边界存在**；Stage 1.9 已将 Runtime Event 纳入全 Query normalized event family，并确认 conceptual envelope，具体 Schema / 实现仍 Pending。

## 12. Decision 11：Runtime lifecycle 状态机

### Decision

```text
Request Received
      │
      ▼
CONTEXT_PREPARING
      │
      ├── compile conversation context
      ├── build local RuntimeContext
      └── determine available capabilities
      │
      ▼
ROUTING
      │
      ├── standard ───────────────────────────┐
      │                                      │
      └── planned                            │
             │                               │
          PLANNING                           │
             │                               │
       validate / sanitize                   │
             │                               │
             └──────────────┬────────────────┘
                            ▼
                     AGENT_PREPARING
                            │
                            ▼
                         RUNNING
                            │
                     ┌──────┴──────┐
                     │             │
                 RESPONDING    TOOL_RUNNING
                     │             │
                     │        Tool Result
                     │             │
                     └──────┬──────┘
                            │
                      continue / finish
                            │
                  ┌─────────┴──────────┐
                  │                    │
             normal finish       budget reached
                  │                    │
                  │               FINALIZING
                  │                    │
                  └──────────┬─────────┘
                             ▼
                         COMPLETED

任何阶段：
User Abort ───────────────→ ABORTED
Fatal Runtime Error ──────→ FAILED
```

注意 `ROUTING / PLANNING` 属于整个 Query Execution lifecycle，但不属于内部 Agent Loop。Stage 1.9 的 end-to-end normalized event boundary 保留了这一层级，不把 Router / Planner 伪装成 Runtime 内部事件。

## 13. Decision 12：Planner→Runtime Adapter 契约

### Decision

Stage 1.6 已把 Plan 定成（`version / title / intent / steps[goal / suggested_tools / evidence_needed] / success_criteria[]`），且 `suggested_tools` 只是 advisory。

Runtime **不应该**读取 Plan 后写这种代码：

```python
for step in plan.steps:
    execute(step.suggested_tools)
```

正确 adapter：

```text
Validated Plan
      ↓
Plan Guidance Renderer
      ↓
LLM-visible soft instructions
      ↓
Agent Runtime
```

类似 ChatLab 当前：

```text
effective_system_prompt
    =
system_prompt
+
buildPlanGuidance(plan)
```

Runtime 不维护 `step 1 done / step 2 running / step 3 pending`（Stage 1.6 已明确禁止）。

## 14. Decision 13：SDK built-in Trace 不当正式 Trace

### Decision

OpenAI Agents SDK 默认开启 built-in tracing（记录 generation、tool call、handoff 等）。Trivae 第一版：

> **不要把 OpenAI SDK 自带 Trace 当成项目正式 Trace，也不要默认向其外部 Trace 后端导出完整运行数据。**

原因不是"不需要 Trace"。Stage 1.7 当时尚未决定：

```text
Trace Schema
哪些 Tool Result 可以记录
聊天正文是否记录
数据如何脱敏
存在哪里
保留多久
```

Stage 1.7 的接法：

```text
SDK Hooks / Stream Events
        ↓
Trivae normalized events
        ↓
Trivae Trace Collector
```

Stage 1.9 已确认 Trivae 配置继续显式关闭 SDK built-in external tracing，不能依赖 SDK 版本默认值；未来 exporter 只能消费 privacy-projected Trivae Event，不能绕过 Collector 直接导出 SDK raw event。这也更接近 ChatLab 自己维护 `aiLogger + AgentEventHandler` 的方式，而不是让 SDK 内部状态成为产品观测契约。

## 15. ChatLab Baseline 与 Trivae 差异

### 15.1 继承 ChatLab 的部分

```text
Thin Agent Core 架构（通用 Loop 由核心库承载，领域职责留在外面）
pre-run context compression
Trivae-owned conversation history + history adapter
Router / Planner 在 Agent Runtime 之前编排
budget-exhausted → disable tools → graceful final synthesis
Tool Error 可恢复（error Tool Result 回传 Agent）
Core Event → Event Handler → UI / CLI Stream 的事件归一化
```

### 15.2 与 ChatLab 的实现技术差异

| 项 | ChatLab | Trivae v1 |
| --- | --- | --- |
| Agent Core 承载方 | `@earendil-works/pi-agent-core`（TS） | OpenAI Agents SDK（Python） |
| SDK 接入方式 | 包一层 adapter | `Trivae AgentRuntime interface → OpenAIAgentsRuntimeAdapter → SDK` |

继承的是 runtime architecture，不是必须照搬 ChatLab 的 TS Agent Core library。

### 15.3 参数继承

见 [Section 0 参数继承口径](#0-architecture-governance)：ChatLab 经验参数可直接继承作为 v1 baseline，标注来源，保留 Evaluation 校准路径。

## 16. Confirmed Architecture Decisions

| # | Decision | Confirmed 语义 |
| --- | --- | --- |
| 1 | **Thin Agent Runtime** | 继承 ChatLab 架构；通用 Agent Loop 由 OpenAI Agents SDK 承载，Trivae 不自行重写通用 Loop。 |
| 2 | **Single Agent（v1）** | 第一版单 Agent，不引入 handoff / multi-agent。 |
| 3 | **Same Runtime both routes** | `standard_execution` 与 `planned_execution` 使用完全相同的 Agent Runtime。 |
| 4 | **SDK 选型 OpenAI Agents SDK** | Python 侧以 OpenAI Agents SDK 为映射方向；通过薄适配层接入，业务代码不直接 import SDK 类型。 |
| 5 | **SDK / Capability 解耦** | 未来替换 SDK 主要替换 Runtime Adapter 与 Function Tool Adapter；具体文件布局保持 Pending。 |
| 6 | **Runtime 职责边界** | Runtime 不重新吞掉 Router / Planner / Retrieval / Evidence；只负责 bounded Agent Loop、streaming、cancellation、termination、result boundary。 |
| 7 | **Orchestrator / Runtime 区分** | Request Orchestrator 负责整个 Query 生命周期；Agent Runtime 从 Agent Loop 启动开始负责执行核心；第一版 Orchestrator 可为 service/function。 |
| 8 | **RuntimeContext 与 Model Context 分离** | RuntimeContext（local）不发给 LLM；Agent Model Context 才是 LLM-visible。 |
| 9 | **Data Access Scope 硬执行** | 在 Tool / Capability 执行路径强制执行，不写进 system prompt 靠模型自觉。 |
| 10 | **Conversation History 归 Trivae** | Trivae Conversation Store 是 source of truth；SDK Session / Provider Conversation 等只可作可重建的 adapter state；Streaming delta 不直接成为 canonical message，完成 / 中止 / 失败记录有明确提交边界。 |
| 11 | **Pre-run Context 压缩** | 压缩发生在 Agent Runtime 之前；v1 不做 mid-run compaction。 |
| 12 | **终止条件两层** | Tool Round 按“一个包含 Tool Result 的模型轮次”计数；Trivae Budget 耗尽后 graceful final synthesis，SDK `max_turns` 必须预留最终调用并仅作 absolute backstop。 |
| 13 | **Tool Error 可恢复** | 仅已知 Tool Contract Error 返回 Agent；未知 Tool / Adapter 异常显式使 Runtime `FAILED`，不能由 SDK generic error handler 吞掉。 |
| 14 | **Abort = terminal intent** | abort 各阶段语义已定义；v1 immediate cancel；`ABORTED` 不执行 final synthesis；`COMPLETED` 以 SDK Run 真正完成为准。 |
| 15 | **Streaming canonical path** | `SDK StreamEvent → adapter → Trivae Runtime Event → CLI / API / UI`；禁止直接返回 SDK StreamEvent。 |
| 16 | **Runtime lifecycle 状态机** | `CONTEXT_PREPARING → ROUTING → (PLANNING) → AGENT_PREPARING → RUNNING → (FINALIZING) → COMPLETED`；任意阶段 `ABORTED` / `FAILED`。 |
| 17 | **Planner soft guidance 注入** | `Validated Plan → Plan Guidance Renderer → LLM-visible soft instructions → Agent Runtime`；Runtime 不读取 plan.steps 逐条执行。 |
| 18 | **SDK built-in Trace 不当正式 Trace** | Trivae 显式关闭 SDK external tracing；`SDK Hooks / Stream Events → Trivae normalized runtime events → Normalized Query Event boundary → Trace Collector`。 |
| 19 | **ChatLab 经验参数可直接继承** | 作为 v1 baseline 直接继承，标注继承来源，保留 Evaluation 校准路径；不无条件照抄，也不拒绝继承。 |
| 20 | **明确不引入清单** | 见 [Section 2 明确不引入](#2-decision-1thin-agent-runtime--sdk-承载通用-agent-loop)：手写 Loop、Multi-Agent、Handoff、Step Executor、Workflow Engine、Replanning、Runtime-owned Evidence State Machine、SDK Session canonical、SDK 类型泄漏、mid-run 压缩、应用级 retry / fallback 等。 |

## 17. Pending Decisions

以下事项不在 Stage 1.7 提前解决：

### Implementation Pending

```text
具体 SDK 版本与依赖锁定
OpenAI Agents Runtime Adapter 的具体接口与实现
OpenAI Function Tool Adapter 的具体接口与实现
RuntimeContext 的具体 Python 类型
Agent Model Context 的具体组装与序列化
Conversation transaction / commit Schema
Tool 并发策略
Agent Model 选型
Prompt 文案
```

### Pending Evaluation（可继承 ChatLab 经验参数，标注来源）

```text
max_tool_rounds 具体数字
SDK max_turns 具体数字
Conversation history window
Compression threshold
Tool Result token budget
Runtime budgets 的具体默认值
```

### Stage 1.8 已解除的 Pending

```text
Evidence-aware stopping 第一版仅作 Agent guidance
machine-enforced gate 与具体参数仍由 Stage 1.10 Evaluation 决定
```

### Stage 1.9 已解除的 Pending

```text
Runtime Event / Trace conceptual envelope、event family 与 operation causality 已确认
Failure Attribution 与 Error Code ownership 已确认
Trace storage / privacy / retention 原则已确认
SDK built-in external tracing 继续显式关闭
具体 Python / JSON Schema、Error Code 枚举、Collector / Store backend 与 exporter 实现保持 Implementation Pending
```

### Stage 1.10 Implementation / Real-run Calibration Pending

```text
Agent correctness benchmark
budget / threshold 参数校准
Tool 并发策略的验证
```

Stage 1.10 已确认 Run 必须绑定完整 Controlled Variant，并以 Case / Snapshot / Scope 做 paired comparison；上述 Runtime correctness、budget、并发与参数仍需真实运行校准。

以上 Pending 项不能因为 Stage 1.7 已 Confirmed 就被默认补全。除非新 Failure Case、技术约束、Evaluation 结果或业务需求触发 Reopen Reason，否则本 ADR 的 Confirmed 决策保持冻结。

## 18. Validation / Regression

当前仓库没有业务代码，因此本阶段不添加 Agent Runtime 实现测试，也不伪造 Evaluation 结果。实现阶段至少应围绕以下语义契约建立可验证检查：

```text
standard_execution 与 planned_execution 进入同一个 Runtime
RuntimeContext 不进入 LLM-visible 内容
Data Access Scope 在 Tool / Capability 执行路径被强制检查（不依赖 system prompt）
Conversation History 由 Trivae Store 编译为 SDK-compatible items
SDK Session / Provider Conversation 不成为 canonical source，且模型输入可由 Trivae Store 独立重建
Streaming delta 不直接提交为 canonical assistant message；COMPLETED / ABORTED / FAILED 提交语义正确
pre-run context compression 生效，无 mid-run compaction
一个包含一个或多个 Tool Call / Result 的模型轮次只计一个 Tool Round
Tool Investigation Budget 耗尽后进入 graceful final synthesis（禁用 Tool → 注入最终回答指引 → 完成）
SDK max_turns 为 final synthesis 预留模型调用，正常预算耗尽不会先撞 absolute backstop
SDK max_turns 撞到后显式 Runtime Failure
已知 Tool Contract Error（如 CAPABILITY_UNAVAILABLE）不导致 Runtime 整体失败，Agent 可恢复
未知 Tool / Adapter 异常不会被 generic Tool Result 吞掉，而是显式 Runtime Failure
User Abort 在各阶段立即生效且不执行 final synthesis
Tool cancellation 采用协作式传播，晚到结果不会重新启动 Loop
COMPLETED 以 SDK Run 真正完成为准（消费完 stream iterator）
Streaming 事件归一化为 Trivae Runtime Event，不暴露 SDK 类型
Plan 只作为 soft guidance 注入，Runtime 不逐条执行 plan.steps
Trivae 显式关闭 SDK built-in external tracing
```

### Interactive CLI streaming implementation amendment（2026-08-23）

本次实现把既有 canonical stream 继续向 Application Surface 投影，没有增加第二套 Agent Loop：

```text
DeepSeek reasoning_content
  → OpenAI Agents SDK public reasoning delta
  → RuntimeEvent(thinking_delta)
  → QueryStreamEvent(thinking.delta)
  → CLI Renderer

RuntimeEvent(content_delta: Answer Artifact JSON)
  → content_blocks[*].text incremental projection
  → QueryStreamEvent(answer.delta)
  → CLI Renderer
```

reasoning 仅在 Provider 确实返回非空内容时出现；CLI 不读取 Provider-specific 字段，也不根据阶段生成伪 thinking。Answer delta 只作实时 preview，完整输出仍由 Citation Finalizer 验证，并在 Query 真正完成后一次性提交 Conversation。`thinking_delta`、`thinking_completed` 与 token delta 不进入持久化 Trace，保持 Stage 1.9 的 hidden reasoning / Chain-of-Thought 隐私边界。

## 19. Result、Trade-off 与 Reopen Conditions

### Result

Stage 1.7 将 Agent Runtime 固定为：**继承 ChatLab 的 Thin Agent Core 架构，由 OpenAI Agents SDK 承载通用 Agent Loop；Trivae 自己拥有外层执行编排、Context、Conversation History、Tool Adapter、生命周期语义和事件契约。**

```text
Context Compiler
        ↓
Router
     /        \
standard    planned
     │         │
     │      Planner
     │         │
     │   soft guidance
     └────┬─────┘
          ▼
   Trivae AgentRuntime
          │
          ▼
   OpenAI Agents SDK Runner
          │
      Agent Loop
          │
     Trivae Tool Layer
          │
     Capability Layer
```

### Trade-off

- 复用 OpenAI Agents SDK 换取通用 Loop、streaming、cancellation、Hooks 的成熟能力；代价是 Trivae 接受 SDK 对 Loop 内部行为的实现，并通过适配层保留替换能力。
- Trivae 持有 Conversation History 与 Context 编译换取迁移自由与领域可控；代价是实现量略大于直接使用 SDK Session。
- 第一版大量参数不冻结、以 ChatLab 经验参数为 baseline：换取真实 workload 校准空间；代价是参数在 Evaluation 之前不保证最优。

### Reopen Conditions

以下情况可以重新打开本 ADR，但必须记录 Reopen Reason：

- Evaluation 证明某类 Query 频繁撞到 Tool Budget 且 final synthesis 质量显著劣于正常完成，说明 budget 语义或最终化时机需要调整；
- 真实 Failure Case 证明 Data Access Scope 仅在执行路径强制仍存在缺口（例如 SDK 自身某条路径绕过 Trivae Tool 层）；
- OpenAI Agents SDK 的版本行为变化导致 Trivae 无法维持薄适配层，或出现不可接受的 streaming / cancellation 缺陷；
- Evaluation 证明 mid-run compaction 对 Trivae workload 有不可替代的价值，且 Failure Attribution 代价可控；
- 真实业务需求确实需要当前明确排除的 multi-agent、handoff、replanning 或 mid-run compaction 语义；
- 新技术约束证明正式 Trace 必须直接接入 SDK built-in tracing 才能取得不可替代的诊断事实，且 Stage 1.9 的 privacy / retention / export 边界评估通过。

单纯因为"标准 Agent 架构通常更复杂""未来可能有 UI"或"以后可能有用"不能重新打开 Confirmed 决策。
