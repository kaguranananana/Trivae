# Stage 1.7 用户提案（原始记录）

> 本文件原样记录用户在会话中提供的 Stage 1.7 架构提案，作为本任务实现 ADR 的事实来源。
> 实现阶段以本文件 + `prd.md` 为准，把内容按既有 ADR 结构（Decision / Why / Trade-off / Failure Case / Reopen Condition）沉淀为正式文档。

---

## 核心方向

> **继承 ChatLab 的 Thin Agent Core 架构，由 OpenAI Agents SDK 承载通用 Agent Loop；Trivae 自己拥有外层执行编排、Context、Conversation History、Tool Adapter、生命周期语义和事件契约。**

与 Stage 1.4–1.6 已冻结的边界吻合，不需要推翻任何已有设计。

## 1. ChatLab 实际做法

ChatLab 没有手写一整套复杂 Agent Runtime，把真正的 Agent Loop 压缩到很薄的 `runAgentCore()`：

```text
Agent Core
  构建 Agent
  → 历史转换
  → 事件订阅
  → abort 转发
  → prompt 执行
  → usage 收集
```

负责 `LLM → Tool Call?（yes → execute tools → append results → LLM / no → final answer）` 的是 `PiAgentCore`。Router、Planner、Context Compression、History Loading、Tool Assembly 都在 `runAgentCore()` 外面。CLI 真实路径：

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

关键结论：**Agent Runtime 不应该重新吞掉 Router、Planner、Retrieval、Evidence 等职责。**

## 2. 整体结构

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

`Query Execution Orchestration` 第一版可以只是一个 service/function，不必要成为新"架构层"。明确命名是为了消除文档混淆点：

- "Runtime 给 Router / Planner 注入 Context"
- "Router / Planner 在 Agent Runtime 之前"

实现理解：**Request Orchestrator** 负责整个 Query 生命周期；**Agent Runtime** 专指真正开始 Agent Loop 之后的执行核心。

## 3. Agent Runtime 只负责什么

> **Single-agent execution runtime，负责驱动模型与 Tool 之间的 bounded Agent Loop，并提供稳定的 streaming、cancellation、termination 和 result boundary。**

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
| Loop Bounds | 必须 bounded，具体数字由 Evaluation 校准 |
| Context | Trivae 管理并编译后交给 SDK |
| Conversation History | Trivae 是 source of truth，不交给 SDK 私有 Session 做唯一持久化 |
| SDK Events | 转换成 Trivae-owned Runtime Events，不向上暴露 SDK 类型 |
| Retry / Model Fallback | v1 不增加 Trivae-specific 自动 retry / fallback |
| Trace | Runtime 暴露观察点，正式 Trace Schema 留到 Stage 1.9 |

继续 Stage 1.6 已冻结的边界：是否调用 Tool、调用哪个 Tool、SQL 怎么写、Search Query 怎么改、是否继续调查、什么时候停止、是否偏离 Plan，全部属于 Agent Runtime。

## 4. SDK：OpenAI Agents SDK

ChatLab 当前用 `@earendil-works/pi-agent-core`；Trivae 第一版建议 **OpenAI Agents SDK**。继承的是 runtime architecture，不是必须照搬它的 TS Agent Core library。

OpenAI Agents SDK `Runner` 已直接提供通用 Loop（`LLM invocation → final_output → stop` / `tool calls → execute tools → append results → next LLM invocation`），并支持 `run_streamed()`、`max_turns`、Run Context、生命周期 Hooks。再手写 `while true → call model → parse tool call → execute → append → call model` 收益很低。

不要这样（业务代码到处直接 import SDK 类型）：
```text
Trivae business code → 到处直接 import agents.Agent / RunContextWrapper / SDK Item
```

应该这样：
```text
Trivae AgentRuntime interface
             │
             ▼
OpenAIAgentsRuntimeAdapter
             │
             ▼
OpenAI Agents SDK
```

Stage 1.4 要求 Capability 不能绑定具体 Runtime，Stage 1.7 继续保留。未来想换掉 OpenAI Agents SDK，主要替换：
```text
runtime/openai_agents_adapter.py
tools/openai_tool_adapter.py
```
而不是 Retrieval、SQLite、Context Expansion、Identity 等整个业务系统。

## 5. Context 分成两种（Confirmed）

OpenAI Agents SDK 明确区分 Local Context 与 LLM-visible Context：`RunContextWrapper.context` 只存在于本地代码里，会传给 Tool、Hook 等，**不会发给 LLM**。这恰好适合 Trivae 已确定的 `Data Access Scope ≠ Query Context`。

```text
RuntimeContext                     # 不直接给 LLM
├── run / request identity
├── conversation identity
├── data_access_scope              # 硬权限
├── capability dependencies
├── database / retrieval handles
├── cancellation state
└── runtime budgets
```

```text
Agent Model Context
├── system instructions
├── bounded conversation context
├── current user request
├── relevant query-context projection
├── compact session/data metadata
└── validated plan guidance?       # planned_execution only
```

最关键：
```text
Data Access Scope
    ↓
必须在 Tool / Capability 执行路径中强制执行

不能：
Data Access Scope → 写进 system prompt → "希望模型记得别越界"
```
落实 Stage 1.4 的硬授权边界。

## 6. Conversation History 不交给 SDK Session 当 source of truth

OpenAI Agents SDK 有 `Session`、`SQLiteSession`，可自动保存恢复 history；但 Trivae 第一版**不用它作为 canonical conversation storage**。原因来自 ChatLab：ChatLab 自己维护 AI Conversation History，进入 `PiAgentCore` 前执行 `Persisted Chat History → history adapter → Pi Agent Messages`，并把历史中的 Tool Call / Tool Result 恢复成结构化消息，而不是 flatten 成纯文本。

Trivae 采用：
```text
Trivae Conversation Store（source of truth）
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

好处：conversation branching、edit / regenerate、context compression、debug replay、prompt migration、更换 Agent SDK、Evidence / Citation 回放、Evaluation replay 都不被 SDK Session 表示绑住。

判断：**SDK Session 可以以后作为 adapter / optimization 重新评估，但 v1 不把它作为 Trivae Conversation 的 source of truth。**

## 7. Context 长了怎么办

ChatLab 把 Context Compression 放在 Agent Core 之前，而不是 Agent Loop 中途突然压缩。Trivae 继承该语义：

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

第一版不做 mid-run compaction（Agent 执行一半突然到 token limit，Runtime 自己调 summary agent 压缩当前状态再继续）——显著增加状态复杂度和 Failure Attribution 难度。Stage 1.4 已把所有大结果 Tool 设计成 bounded。

`history window`、`summary threshold`、`summary token budget`、`tool-result retention`、`compression model` 这些数字和算法交给实现和 Evaluation，不在架构层冻结。

## 8. Agent Loop 终止条件（最应认真确定的一项）

ChatLab 不仅有 Tool Round 上限，到达上限后不是直接报 "Too many tool calls"，而是：
```text
达到 Tool Round Budget
        ↓
禁用所有 Tool
        ↓
注入"基于已收集信息给出最终回答"
        ↓
最后一次 synthesis
        ↓
结束
```
对应测试明确验证该行为。Trivae **原样继承**。

Loop：
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

OpenAI Agents SDK `max_turns` 超限抛 `MaxTurnsExceeded`，不能简单说"直接依赖 SDK 的 max_turns 就结束"。两层：

```text
Trivae Tool Investigation Budget
    → 达到上限后 graceful final synthesis

SDK max_turns
    → absolute safety backstop
    → 如果真的撞到，显式 Runtime Failure
```

SDK 支持运行时动态隐藏 Tool，"进入 finalizing 后让 Tool 对 LLM 不再可见"能干净实现。

## 9. Tool Error ≠ Agent Run Error

例如 `semantic_search → CAPABILITY_UNAVAILABLE`，合理行为不是 Runtime 整体 crash，而是：
```text
Tool Result
status = error
error.code = CAPABILITY_UNAVAILABLE
        ↓
返回 Agent
        ↓
Agent 根据错误决定：
    换 lexical_search / 使用 SQL / 明确告诉用户能力不可用 / 基于现有证据回答
```

Stage 1.4 已确认 Tool 统一 `ok / partial / error` 语义，禁止 Tool 层 silent fallback。ChatLab Core Test 覆盖"Tool 抛异常后产生 error Tool Result，但 Agent Loop 仍能恢复并给出答案"。

```text
Tool failure ≠ Runtime failure
```

只有以下才是 Agent Runtime 的 terminal failure：
```text
model/provider request fatal failure
SDK runtime invariant failure
无法构造有效模型输入
absolute loop limit exceeded
unrecoverable context overflow
```
具体 Error Code 名字留给 Stage 1.9，不在 Stage 1.7 抢 Trace Schema 工作。

## 10. Abort 生命周期

语义：**User Abort = terminal intent**。

```text
abort before Runtime        → 不启动 Agent
abort during model streaming → cancel model run
abort during Tool           → cancellation 继续向 Tool / Capability 传播
abort after tool result before next turn → 不再开始下一轮
abort                       → ABORTED，不执行 final synthesis
```

区别于 Tool Budget 用完：
```text
Tool Budget exhausted → 用户没取消 → final synthesis
User Abort            → 用户明确要求停止 → 立即停止
```

SDK streamed run 支持 `cancel()`，默认 immediate，也支持 `after_turn`。用户主动停止 v1 用 immediate。

踩坑点：最后一个 token 出来 ≠ streamed run 已结束。SDK 要求继续消费 `stream_events()` 到 iterator 完成（清理、Session 收尾可能发生在最后一个可见 token 之后）。所以 Runtime `COMPLETED` 以 **SDK Run 真正完成**为准，不是 UI 看见最后一个文字 token。

## 11. Streaming 是 canonical path

ChatLab 是 Core Event → Event Handler → UI / CLI Stream，业务层不直接依赖 `PiAgentEvent`，转成自己的 `content / tool_start / tool_update / tool_end / turn_end / usage_update ...`，外面由 `AgentEventHandler` 转成应用状态与 stream chunk。

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

绝对不要 `FastAPI → 直接返回 SDK StreamEvent`（否则 Stage 1.11 API 和 Stage 1.9 Trace 被 SDK 类型绑定）。Stage 1.7 只冻结**事件边界存在**，不抢先定义最终 Trace Schema。

## 12. Runtime lifecycle

```text
Request Received
      │
      ▼
CONTEXT_PREPARING
      │  compile conversation context / build local RuntimeContext / determine available capabilities
      ▼
ROUTING
      │  standard ───────────────────────────┐
      │                                     │
      └── planned                           │
             │  PLANNING                     │
             │  validate / sanitize          │
             └──────────────┬────────────────┘
                            ▼
                     AGENT_PREPARING
                            ▼
                         RUNNING
                     ┌──────┴──────┐
                 RESPONDING    TOOL_RUNNING
                     │             │
                     │        Tool Result
                     └──────┬──────┘
                      continue / finish
                  ┌─────────┴──────────┐
             normal finish       budget reached
                  │                    │
                  │               FINALIZING
                  └──────────┬─────────┘
                             ▼
                         COMPLETED

任何阶段：User Abort ────→ ABORTED；Fatal Runtime Error ────→ FAILED
```

注意 `ROUTING / PLANNING` 属于整个 Query Execution lifecycle，不属于内部 Agent Loop。既方便 Stage 1.9 做 end-to-end Trace，也不破坏 Stage 1.5 / 1.6 模块边界。

## 13. Planner ↔ Runtime adapter 契约

Plan Schema（Stage 1.6）：version / title / intent / steps[goal / suggested_tools / evidence_needed] / success_criteria[]，`suggested_tools` 只是 advisory。

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

类似 ChatLab 当前 `effective_system_prompt = system_prompt + buildPlanGuidance(plan)`。Runtime 不维护 `step 1 done / step 2 running / step 3 pending`（Stage 1.6 已明确禁止）。

## 14. SDK Trace 决策

OpenAI Agents SDK 默认开启 built-in tracing（记录 generation、tool call、handoff 等）。Trivae 第一版：

> **不要把 OpenAI SDK 自带 Trace 当成项目正式 Trace，也不要默认向其外部 Trace 后端导出完整运行数据。**

原因不是不需要 Trace，而是 Stage 1.9 还没决定 Trace Schema、哪些 Tool Result 可记录、聊天正文是否记录、数据如何脱敏、存在哪里、保留多久。

Stage 1.7 应：
```text
SDK Hooks / Stream Events
        ↓
Trivae normalized events
        ↓
Stage 1.9 Trace Collector
```
SDK built-in external tracing 默认关闭，等 Stage 1.9 明确数据策略后再决定是否接入。这也接近 ChatLab 自己维护 `aiLogger + AgentEventHandler` 的方式。

## 15. 明确不做什么（v1 DOES NOT introduce）

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

其中 Automatic Replanning、Planner State、Workflow Engine 已被 Stage 1.6 排除，Runtime 继续尊重该决定。

## 16. 这次不要拍死（Pending）

| 项目 | 为什么现在不冻结 |
| --- | --- |
| `max_tool_rounds` 具体数字 | 需要真实 Agent workload |
| SDK `max_turns` 数字 | 与 Tool Round / finalization 联动，需要测试 |
| Conversation history window | Token / correctness Evaluation |
| Compression threshold | 取决于实际模型 Context 和聊天长度 |
| Tool Result token budget | Stage 1.4 已要求 bounded，具体值需校准 |
| Tool 并发策略 | 还涉及 SQLite / Capability concurrency 实现 |
| Agent Model | 独立于 Runtime architecture |
| Prompt 文案 | Implementation + Evaluation |
| Runtime Event 最终 Schema | Stage 1.9 |
| Trace 字段 / storage | Stage 1.9 |
| Agent correctness benchmark | Stage 1.10 |
| Evidence-aware stopping | Stage 1.8 / 1.10 联动 |

## 压缩图（最终架构冻结）

```text
                  Trivae Query Execution
                          │
                  Context Compiler
                          │
                        Router
                     /           \
                standard        planned
                    │               │
                    │            Planner
                    │               │
                    │         soft guidance
                    └───────┬───────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │   Trivae AgentRuntime│
                 │ RuntimeContext       │
                 │ History Adapter      │
                 │ Tool Adapters        │
                 │ Event Adapter        │
                 │ Budget / Abort       │
                 │        │             │
                 │        ▼             │
                 │ OpenAI Agents SDK    │
                 │      Runner          │
                 │        │             │
                 │    Agent Loop        │
                 └────────┬─────────────┘
                          │
                 ┌────────┴────────┐
                 │                 │
             model turn        tool calls
                                   │
                                   ▼
                         Trivae Tool Layer
                                   │
                                   ▼
                         Capability Layer
                                   │
                     ┌─────────────┼────────────┐
                     ▼             ▼            ▼
                 Retrieval       SQLite       Identity
```

## Confirmed 判断汇总

**ChatLab-style Thin Agent Runtime、OpenAI Agents SDK 承载通用 Loop、Single Agent、Same Runtime for both routes、Trivae-owned Context & Conversation History、local RuntimeContext 与 LLM Context 分离、streaming-first、explicit Abort、bounded Agent Loop + graceful final synthesis、Tool Error 可恢复、SDK Event normalization、no automatic replanning、no runtime-specific retry/fallback、SDK 与 Capability 解耦。**

## 用户补充要求（实现必须遵守）

- 不要把参数卡的那么死；也不能说完全不能照抄 ChatLab——它是经验参数，可以**直接继承**。
- 继承时必须**标注来源（ChatLab 经验参数）**，并保留 Evaluation 校准路径。
- 沉淀成 `stage-1-7-agent-runtime.md` 时，重点写各 Decision 的 rationale、Failure Case 和 Reopen Condition，而不是先开始定义 `max_turns=多少` 之类的参数。

## 参考链接（OpenAI Agents SDK 文档）

- Running agents: https://openai.github.io/openai-agents-python/running_agents/
- Context management: https://openai.github.io/openai-agents-python/context/
- Sessions: https://openai.github.io/openai-agents-python/sessions/
- Tools: https://openai.github.io/openai-agents-python/tools/
- Streaming: https://openai.github.io/openai-agents-python/streaming/
- Tracing: https://openai.github.io/openai-agents-python/tracing/
