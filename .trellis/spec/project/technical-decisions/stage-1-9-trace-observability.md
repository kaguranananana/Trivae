# Stage 1.9：Trace / Observability 架构决策

> 状态：**Confirmed / Completed（Stage 1.9）**
>
> 本 ADR 只确认 Query Plane 的跨切面 Trace / Observability 语义：归一化事件边界、因果关联、Failure Attribution、query-scope coverage、Error Code ownership、隐私与保留边界、Trace storage 原则和 operational metrics 维度。它不实现代码，不冻结 Python / JSON / Database Schema、日志产品或部署拓扑，也不提前设计 Stage 1.10 的 Evaluation Dataset、质量指标阈值、gate 或参数校准。

---

## 0. Architecture Governance 与承接边界

本阶段遵循项目级 [ChatLab as Reference Implementation](../architecture.md#architecture-principle-chatlab-as-reference-implementation) 原则，并承接以下 Confirmed contract：

- Stage 1.3：Retrieval 必须保留 query、strategy、filters、primitive result、context expansion、final candidates、provenance、coverage / partial / truncated，并能区分 Retrieval failure families；
- Stage 1.5：Router 输出 `route / confidence / reason / source`；Router degradation 必须保留原始失败与最终 Route，不能伪装成正常判断；
- Stage 1.6：Planner failure 分为 `generation_error / timeout / invalid_output / unavailable / aborted`；Planner failure 不重写已经发生的 Route Decision，也不维护 step execution state；
- Stage 1.7：Query lifecycle 横跨 Context、Router、Planner、Agent Runtime、Tool、Finalization；SDK Event 必须先归一化为 Trivae-owned Event；Tool Contract Error 与 Runtime Failure 分离；SDK built-in external tracing 显式关闭；
- Stage 1.8：Evidence Selection、Citation Validation、Answer Finalization 是独立边界；Evidence sufficiency 与 execution completeness 分轴；invalid / unresolved Citation 显式阻止提交。

Stage 1.9 不重新设计上述模块，也不把 Trace Collector 变成新的业务编排层、Workflow Engine、Evidence State Machine 或 Evaluation Judge。

## 1. Context：为什么需要项目自有 Trace

一个最终回答错误，可能来自完全不同的根因：

```text
Router under-routing
Planner invalid output
Tool argument error
Semantic index coverage incomplete
Relevant candidate ranked too low
Agent retrieved evidence but did not use it
Citation locator invalid
Answer generation misrepresented valid evidence
```

如果只保存最终回答和一条 generic error，系统无法区分“没有召回”“召回后没有使用”“执行被截断”或“Citation 提交失败”。反过来，若直接把 SDK 内部 Trace、原始 Tool Result 和聊天正文全部外发，又会让 Trivae 的产品契约绑定 SDK 类型并扩大隐私边界。

因此第一版需要一个 Trivae-owned、cross-cutting、可回放的事实边界，同时保持实现和存储技术可替换。

## 2. Decision 1：一个跨 Query Execution 的归一化事件边界

### Decision

所有 Query Plane 组件先发布 **Trivae Normalized Query Event**，再由下游做不同投影：

```text
Router / Planner / Runtime / Tool / Retrieval / Evidence / Citation
                              │
                              ▼
                 Trivae Normalized Query Event
                       ┌──────┴──────┐
                       ▼             ▼
              Stream Projection   Trace Collector
              (CLI / API / UI)    (recordable projection)
```

OpenAI Agents SDK 只是一类上游事件来源：

```text
SDK Hook / StreamEvent
        ↓
OpenAIAgentsRuntimeAdapter
        ↓
Trivae normalized runtime event
        ↓
Normalized Query Event boundary
```

Stage 1.7 的 `Trivae Runtime Event` 是这个全链路事件边界中的 Runtime family，不是另一套互不相干的事实模型。Router、Planner、Retrieval 与 Finalization 不需要伪装成 SDK Runtime Event。

### Boundary Rules

1. 组件拥有自己的 domain payload；Trace Collector 不重新解释业务语义。
2. 统一 envelope、事件身份、Query correlation、顺序号与持久化策略由 Observability boundary 拥有。
3. CLI / API / UI 不直接解析 SDK Event 或 Trace storage record。
4. Trace Collector 不驱动 Router、Planner、Agent、Tool 或 Evidence 行为；业务执行不能依赖 Trace replay 才能继续。
5. Streaming token / text delta 可以进入实时 Stream Projection，但默认不逐 token 持久化为 Trace Event；模型轮次与最终内容引用已经足够定位第一版运行边界。

### Reason

单一归一化边界避免每个消费者私自解析 SDK payload 或定义不同的 Router / Tool / Evidence 事件；不同投影又允许产品 streaming 与内部 observability 使用不同的数据最小化策略。

## 3. Decision 2：冻结 conceptual event envelope，不冻结序列化 Schema

每个可记录事件在语义上至少包含：

```text
Normalized Query Event
├── schema_version
├── event_id
├── trace_id                    # 一次 Query Execution
├── request_id                  # ingress correlation；regenerate / explicit rerun 可形成新 trace
├── sequence                    # Trace Collector 在单 trace 内分配
├── occurred_at
├── observed_at
├── stage                       # context / router / planner / runtime / model / tool /
│                               # retrieval / evidence / citation / answer / trace
├── operation
├── phase                       # started / completed / failed / degraded / aborted / observed
├── operation_id
├── parent_operation_id?
├── outcome?                    # ok / partial / error / aborted；只在适用边界出现
├── duration?
├── payload                     # 由 stage owner 定义的 bounded domain facts
├── limitations?                # coverage / truncated / unavailable 等，不折叠成 evidence sufficiency
└── failure?                    # 结构化归因，见 Decision 5
```

语义约束：

- `trace_id` 对应一次 Query Execution；Regenerate、显式重新运行或应用级新尝试使用新的 `trace_id`，通过 `request_id` 或业务关联字段表达关系，不覆盖旧 Trace；
- `event_id` 是事件身份；`operation_id / parent_operation_id` 表达跨组件因果关系，例如 Agent Tool Call → Tool Execution → Retrieval Operation；
- `sequence` 用于单 Trace 确定性回放，`occurred_at` 表达源组件发生时间，`observed_at` 表达 Collector 接收时间；不能只依赖 wall-clock timestamp 排序；
- `phase` 表达真实发生的边界事实。不能因为最终请求成功，就把先前 `planner.failed` 改写为 `planner.completed`；
- `payload` 只包含定位当前边界所需事实，不能放 Chain-of-Thought；Router `reason` 仍是短诊断说明，不是隐藏推理；
- 具体字段命名、类型、nullable 规则、serialization、event version migration 和 package layout 属于 Implementation Pending。

## 4. Decision 3：跨阶段 normalized event families

第一版必须能够表达以下稳定边界；表中的名称是语义 family，不要求实现逐字使用同名字符串：

| Stage | 必须可观察的边界 | 关键事实 |
| --- | --- | --- |
| Query / Context | received、context prepared / failed、terminal completed / failed / aborted | request / conversation identity reference、effective data scope reference、terminal outcome、total latency |
| Router | decision、degraded、failed invocation | `route / confidence / reason / source`、Rule / LLM path、原始 failure、最终 Route |
| Planner | started、validated / sanitized、completed、failed、skipped | invocation reason、Plan identity / version、validation facts、failure category、`executed_without_plan` |
| Runtime / Model | runtime started、model turn completed / failed、budget reached、final synthesis started、runtime terminal | model、prompt version、usage、Tool Round、budget reason、lifecycle transition |
| Tool | call started、completed、partial、contract error、aborted | tool name、bounded argument projection、result identity、status、latency、error code |
| Retrieval | operation started / completed / partial / failed、context expansion | query / rewrite projection、strategy、filters、index / model version、candidate counts / ids / ranks、query-scope coverage、truncated / unavailable |
| Evidence | selection completed / failed | criterion identity / bounded snapshot、selected Evidence / Source identities、sufficiency、limitations |
| Citation | validation completed / failed | validated / unresolved binding counts、locator / scope validation outcome、owned error code |
| Answer | finalization completed / failed、commit completed / failed | Answer Artifact identity、Assistant Message identity、commit boundary；不重复保存完整 Artifact |
| Trace | collector degraded / incomplete | missing sequence / operation、collector or storage error、trace completeness status |

以下不建立为第一版事实边界：

- Planner `steps[]` 的 running / done / failed 状态；Planner 没有 step executor，也不拥有执行状态；
- 对每个 token 的永久事件；
- Runtime 在线自动判断 `Lexical Miss / Ranking Error / Answer Correctness` 等需要 counterfactual 或人工标注的质量结论；
- 独立 Evidence Agent、Judge 或 Evaluation gate event。

## 5. Decision 4：事件表示事实，Projection 表示状态

Trace 是 append-only event history。Lifecycle summary、时间线、错误列表、latency breakdown 和 metrics 都是事件的 derived projection：

```text
Normalized Events (source of truth for Trace)
        ├── Query Timeline Projection
        ├── Failure Attribution Projection
        ├── Operational Metrics
        └── Debug / UI View
```

规则：

- 已持久化事件不原地改写为另一结果；更正通过后续事件表达；
- terminal event 只能在对应业务提交边界真正完成后产生；最后一个 token 不等于 Query completed；
- 若进程中止导致没有 terminal event，读取端将 Trace 标为 `incomplete`，不得推断为 completed 或 failed；
- projection / metrics 可从保留期内的 canonical Trace Event 重建，不成为第二份互相冲突的执行事实源。

## 6. Decision 5：Failure Attribution 使用 origin、observation 与 handling 三个维度

### Failure Record

失败语义至少表达：

```text
Failure
├── error_code
├── origin_stage                 # 首个违反本层 contract 的 owner
├── observed_stage               # 错误实际暴露或被捕获的位置
├── cause_event_id / operation_id?
├── category                     # invalid_input / invalid_output / timeout / unavailable /
│                                # scope_violation / budget / cancelled / invariant / external ...
├── handling                     # returned_to_agent / degraded / terminal / aborted
├── retry_count?                 # 只记录真实发生的 provider / transport retry
└── diagnostic_reference?        # 指向受控日志 / exception，不复制敏感 stack payload
```

### Attribution Rules

1. **首个破坏 contract 的层拥有 origin**。Tool Adapter 捕获 Retrieval exception 时，`observed_stage = tool`，但若根因来自 Retrieval contract，`origin_stage = retrieval`；Wrapper 不夺取 ownership。
2. **Recovery 不抹掉 failure**。Router / Planner 明确降级后 Query 可以 `COMPLETED`，同时保留 `degraded` event 和原始 error code。
3. **Tool failure 不自动等于 Runtime failure**。已知 Tool Contract Error 可以 `returned_to_agent`；未知 Tool / Adapter exception 归为 terminal Runtime / Orchestration failure，并保留原始 owner。
4. **Abort 与 failure 分开**。用户取消产生 `aborted`，不能归类为 timeout 或 runtime error；Planner invocation 因上层 abort 中止时仍可记录 Planner `aborted`，Query terminal 为 `ABORTED`。
5. **Budget exhaustion 不是异常**。命中已确认 hard bound 时记录 `budget` limitation / finalization reason；只有 absolute backstop 或 invariant failure 才成为错误。
6. **Online Trace 不伪造质量 Root Cause**。Under-routing、Lexical Miss、Semantic Miss、Chunk Boundary Error、Ranking Error、Evidence Selection Error、Answer Generation Error 等可能需要已知正确来源、人工复核或 Stage 1.10 Evaluation 才能确诊。运行时 Trace 保存诊断事实；后续 Failure Case 可以追加或关联 diagnosis，但不能回写伪造原始事件。

### Stage Ownership

| Failure domain | Primary owner |
| --- | --- |
| Context compile、Query lifecycle、terminal outcome | Query Orchestrator |
| Route Decision / Router degradation | Router |
| Plan generation、parse、validation、sanitization | Planner |
| Model turn、loop、streaming、cancellation、absolute backstop | Agent Runtime / Provider Adapter |
| Tool arguments、Tool Contract mapping、Data Access Scope enforcement | Tool Layer；底层 capability 保留 origin |
| Retrieval strategy execution、index availability、candidate / rank / expansion facts、coverage | Retrieval |
| criterion application、Evidence Selection、finding / sufficiency | Agent Final Synthesis |
| binding、locator、provenance、scope 与 trusted hydration validation | Citation Validator / Finalizer |
| Assistant Message / Answer Artifact commit | Conversation Store boundary |
| Event normalization、sequence、Trace persistence / completeness | Trace Collector / Trace Store |

## 7. Decision 6：Query-scope coverage 使用明确 basis，不使用全局百分比代替

### Definition

Coverage 必须相对于本次 capability 实际被要求检查的范围表达：

```text
requested_query_scope
        ∩ Data Access Scope
        ↓
effective_query_scope
        ↓
coverage of this capability / index within that scope
```

`Data Access Scope` 是授权边界；用户 query filter 不是授权。Trace 可以引用受控的 scope identity，但任何 model-visible、user-visible 或外部导出投影都不得暴露未授权范围的存在与细节。

`effective_query_scope` 的 denominator 不能因为索引缺失而缩小，否则未索引数据会被错误报告为 100% coverage。对于 Semantic Index，coverage 表达当前 index version 对授权查询范围内 canonical eligible data 的可检索覆盖；它不自动证明外部社交平台的数据已经完整导入。

### Coverage Descriptor

每个适用的 Retrieval / Tool Result 在语义上表达：

```text
QueryScopeCoverage
├── scope_reference              # normalized requested/effective session/time/member scope
├── basis                        # canonical store / lexical index / semantic index / result set ...
├── basis_version?
├── as_of
├── status                       # complete / partial / none / unknown / not_applicable
├── covered_units?               # 仅在可可靠计算时存在
├── eligible_units?
├── unit?                        # message / chunk / partition / row scope 等明确单位
└── known_gaps?                  # bounded、可定位的缺口描述
```

表达规则：

- 只有 `covered_units / eligible_units / unit` 有可靠且同口径的来源时才给 ratio；不能用估算值冒充精确 coverage；
- denominator 或 mapping 不可知时使用 `unknown`，不能默认 `complete`；
- `none` 表示 capability 对有效查询范围没有覆盖，不表示事实不存在；
- `not_applicable` 表示该操作没有 coverage 语义，不是 0%；
- `coverage.status`、`truncated`、`unavailable` 和 Tool `status = ok / partial / error` 分字段保留，不合并成一个模糊 `partial`；
- 多个 Retrieval primitive 的 coverage 不求未经定义的平均数。每个 operation 保留自身 descriptor，组合层只传播适用 limitation；
- zero hits 只有在有效 scope、basis、coverage、truncation 与 availability 一起可见时才可解释；即使 capability coverage 为 complete，也只说明对 Canonical Store 当前已知数据的执行完整性，不证明外部世界不存在该事实。

### Reason

全局索引 80% 对“查询某个群在某一周”没有诊断价值。Query-scope coverage 使 0 result、partial result 和 Evidence limitation 能沿当前查询链路解释，同时不把 Stage 1.10 的 quality threshold 偷渡进运行时契约。

## 8. Decision 7：Error Code 由 contract owner 命名，跨层传播不改名

### Namespace Ownership

Error Code 使用稳定的 owner namespace；具体枚举在实现对应 contract 时补全：

```text
QUERY.*
CONTEXT.*
ROUTER.*
PLANNER.*
RUNTIME.*
PROVIDER.*
TOOL.*
RETRIEVAL.*
EVIDENCE.*
CITATION.*
CONVERSATION_STORE.*
TRACE.*
```

规则：

1. Error Code 描述 machine-readable failure contract，不承载动态文本、Exception message 或用户内容。
2. Contract owner 负责 code 的语义、触发条件和兼容性；调用方只传播，不用自己的 namespace 包装成“同一个新错误”。
3. Query terminal event 可以有 orchestration outcome，但必须引用 underlying failure；不能用 `QUERY.FAILED` 覆盖 `CITATION.UNRESOLVED_SOURCE` 等根因。
4. 已知 Tool Contract Error 使用 Stage 1.4 / 1.7 的 model-visible Tool Result，同时 Trace 记录同一 code；未知 exception 不映射成 generic `TOOL.ERROR` 来隐藏程序缺陷。
5. Router / Planner degradation 使用各自 namespace，最终 Route / Runtime outcome 单独记录。
6. HTTP status、SDK exception type、数据库错误号属于 adapter diagnostic，不作为 Trivae domain error code 的所有者。
7. 本 ADR 冻结 ownership 与传播原则，不提前枚举所有 code，也不定义 Stage 1.10 quality label。

## 9. Decision 8：Trace 数据最小化与隐私边界

Trace 的目标是定位，不是复制一份完整聊天数据库、Conversation Store 或模型上下文。

### Default Record Policy

默认记录：

- identity reference、stage / operation / phase、latency、counts、status、Error Code；
- Route / Plan / Tool / Retrieval / Evidence / Citation 的 bounded structural facts；
- model、prompt version、index version、Tool / Result / Evidence / Answer Artifact identity；
- query scope reference、coverage descriptor 与 execution limitations。

默认不记录：

- Chain-of-Thought、hidden reasoning 或 provider internal trace；
- 逐 token stream；
- 完整聊天正文、完整 Tool Result、完整 SQL result、完整 Model Context、完整 Prompt / Response 副本；
- credentials、connection strings、access tokens 或未授权 scope；
- 为了调试方便而无限期保留的原始 user query / final answer 副本。

User Query、Final Answer 与 validated Answer Artifact 已有 Conversation Store ownership时，Trace 优先保存其稳定 reference 与必要的 bounded / redacted diagnostic projection，不复制 canonical payload。失败发生在提交之前时，允许在明确策略下保存最小受控 snapshot，但仍受相同访问、脱敏与保留规则约束。

Tool argument / result、Retrieval candidate 与 Message Source 可能包含聊天正文。Trace 默认保存 identifiers、counts、range、rank、score、version 与 limitation；只有真实 Failure Case 需要内容级诊断时，才可由显式配置开启 bounded sensitive snapshot。该快照必须保持未授权数据不可见，并具有比 metadata 更严格的访问与保留边界。

### Access / Export Boundary

- Trace 读取权限不能扩大原始数据的 Data Access Scope；查看 Message / Result 内容时仍按当前授权解析 reference；
- model-visible / user-visible projection、内部 operator view 与外部 exporter 是不同数据面，必须分别 allowlist；
- OpenAI Agents SDK built-in external tracing 继续显式关闭；第一版不把完整 normalized event 自动发送到第三方；
- 未来 exporter 只能消费经过 privacy projection 的 Trivae Event，不能绕过 Collector 直接订阅 SDK raw event。

## 10. Decision 9：Retention 分层，Answer Artifact 不跟随 Trace 到期

Retention 采用数据类别分层，而不是“一条 Trace 永久保存全部内容”：

| Data class | Retention principle |
| --- | --- |
| Trace metadata / lifecycle events | 有限、可配置；用于运行定位与 operational trend，不得默认永久保留 |
| Sensitive diagnostic snapshot | 显式开启、更严格访问、短于或不长于 metadata retention |
| Aggregated operational metrics | 不携带聊天正文和不必要的高基数身份；可独立保留 |
| Validated Answer Artifact / Assistant Message | 服从 Conversation Store 生命周期，不因 Trace 到期被删除 |
| Canonical Message / Raw Source | 服从 Data Plane 与原平台策略，不由 Trace Store 取得 ownership |
| Failure Case / future Evaluation artifact | 必须经过独立选择与治理；不能通过延长全部 Trace retention 自动生成 |

生产环境启用前必须配置 retention、访问和删除策略；具体天数、合规地区、角色矩阵与 legal policy 属于部署 / 产品隐私决策，不在本 ADR 猜测。

Source / Conversation / Message 被授权删除或访问范围变化时，Trace 中的 sensitive snapshot 与 reference resolution 必须服从相应删除 / 不可见语义；具体 propagation mechanism 属于 Implementation Pending。

## 11. Decision 10：Trace Storage 是独立 append-only 事实存储，技术选型 Pending

### Storage Principles

1. **独立 ownership**：Trace Store 不等于 Canonical Message Store、Conversation Store、SDK Trace backend 或业务日志文件。
2. **Append-only within retention**：事件写入后不原地重写；顺序和因果关系由 envelope 表达。
3. **Schema versioned**：每个事件有 schema version；读取 / projection 必须显式处理支持的版本，不能 silent drop unknown event。
4. **Reference over duplication**：引用 Tool Result、Message、Evidence、Answer Artifact identity；只保存允许的 bounded snapshot。
5. **Derived indexes / metrics rebuildable**：查询索引、timeline projection 与 operational aggregates 可从事件重建，不反向成为 canonical event。
6. **Incomplete trace visible**：sequence gap、Collector failure、process crash 或 storage failure 导致的缺口必须标记，不能补造正常 completion。
7. **Business commit separation**：Trace persistence 不与 Conversation Store / Answer Artifact 强行组成分布式事务；业务 terminal event 必须在业务提交结果明确后记录。
8. **Backend replaceable**：Stage 1.9 不选择 SQLite table、JSONL、OpenTelemetry backend、vendor platform 或消息队列；选择必须满足本 ADR 的顺序、版本、隐私、retention 与 replay contract。

### Trace Collector Failure

Trace / metrics 是 observability dependency，不是 Query correctness dependency。Collector 或 Trace Store failure 不得把本来成功的 Answer Artifact 回滚，也不得伪装成业务模块失败；请求可以继续，但必须通过独立的本地 operational error / health signal 显式暴露 `TRACE.*` failure，并在仍可记录的地方标明 Trace incomplete。

这是一条范围明确的 availability contract，不允许 silent loss。若未来业务进入必须审计每次执行的模式，需要以新合规需求重开本决策，而不是在第一版假设 audit-grade distributed transaction。

## 12. Decision 11：Operational metrics 从 Trace 派生，质量 Evaluation 留给 Stage 1.10

Stage 1.9 只确认无阈值的 operational dimensions：

- Query / stage latency 与 terminal outcome；
- Route source、Router degradation count；
- Planner invocation / validation / failure category；
- model、prompt version、token usage；
- Tool call / Tool Round count、Tool status、Tool Error Code；
- Retrieval strategy、candidate count、index / model version、query-scope coverage status、truncated / unavailable；
- Evidence / Citation / Answer Finalization structural outcome；
- abort、budget finalization、unknown exception 与 Trace incomplete count；
- 真实发生的 provider / transport retry count（若底层明确存在），不因此新增应用级 retry policy。

Stage 1.9 不定义：

- Router accuracy、planned precision / recall 或 Planner Utility threshold；
- Retrieval Recall@K / Precision@K、citation precision / recall、semantic entailment 或 answer correctness；
- Evaluation Dataset、labels、sampling rubric、pass / fail gate；
- latency / token / coverage / citation minimum threshold；
- model、prompt、budget、top-k、chunk、rerank 或 stopping 参数。

这些属于 Stage 1.10。Operational metric 可以成为未来 Evaluation 的输入，但不能在本阶段被描述为质量证明。

## 13. ChatLab Baseline 与 Trivae 边界

### 继承

依据 Stage 1.7 已确认的参考实现核验，Trivae 继承 ChatLab 的以下架构方向：

- Core / SDK event 先转换成项目自有 normalized event；
- Event Handler / Collector 再驱动 UI state、stream 与内部日志；
- Tool start / update / end、turn end、usage 等关键边界可观察；
- 项目自己掌握 logging / event contract，而不是让 Agent SDK 类型成为产品接口。

### 不直接继承 / 明确化

- Trivae 的正式 Trace 横跨 Router、Planner、Retrieval、Evidence 与 Citation，不只记录 Agent Core；
- 不默认把完整 Query、聊天正文、Tool Result 或模型输入输出发送到外部 tracing backend；
- 不把 ChatLab 的实现字段、日志文件格式、默认保留期或 UI event 名直接冻结为 Trivae Schema；
- Query-scope coverage、Data Access Scope、claim-level Citation 和 Answer Artifact 是 Trivae 已确认 contract，必须进入自己的 normalized event / reference 语义。

## 14. Ownership Summary

| Owner | Owns | Does not own |
| --- | --- | --- |
| Domain component | 本层 operation、payload、outcome、Error Code 语义 | 全局 sequence、Trace retention、其他层 Root Cause |
| Runtime / SDK Adapter | SDK → Trivae runtime event normalization | 项目正式 Trace storage、直接外发 SDK raw trace |
| Query Orchestrator | `trace_id` 关联、全 Query lifecycle、terminal business outcome | 改写下游组件 error ownership |
| Trace Collector | envelope validation、event identity、sequence、privacy projection、persistence / completeness | 业务控制流、质量 Judge、自动 recovery |
| Trace Store | append-only event persistence、retention / deletion enforcement | Canonical Message、Conversation 或 Answer Artifact ownership |
| Projection / Metrics | timeline、summary、operational aggregate | 创造不存在的事件或覆盖 canonical Trace |
| Stage 1.10 Evaluation | 未来的质量标签、数据集、threshold 与 gate | 改写原始运行事实 |

## 15. Confirmed Decisions

1. Query Plane 使用一个 Trivae-owned normalized event boundary；Runtime Event 是其中一个 family。
2. Stream Projection 与 recordable Trace Projection 从同一语义边界派生，但采用不同数据最小化策略。
3. Conceptual envelope 包含 version、identity、correlation、sequence、time、stage、operation、phase、causality、bounded payload / limitation / failure。
4. Trace 事件 append-only；状态、timeline 与 metrics 是可重建 projection。
5. Failure Attribution 区分 origin stage、observed stage、handling 与 terminal query outcome。
6. Recovery / degradation 不抹掉原始错误；Tool failure、Runtime failure、Abort 与 Budget 分开。
7. 在线 Trace 保存诊断事实，不伪造需要人工或 Evaluation 才能确定的质量 Root Cause。
8. Query-scope coverage 以 `requested scope ∩ Data Access Scope` 后的 effective scope 为基准；索引缺口不能缩小 denominator。
9. Coverage 使用 `complete / partial / none / unknown / not_applicable`，只有口径可靠时才提供 numerator / denominator / unit；不平均不同 capability coverage。
10. coverage、truncated、unavailable、Tool status 与 Evidence sufficiency 分轴表达。
11. Error Code 由稳定 owner namespace 拥有；跨层传播保留 underlying code，不用 wrapper code 覆盖根因。
12. Trace 默认 data minimization：不保存 Chain-of-Thought、逐 token stream 或完整聊天 / Tool / Model payload 副本。
13. Trace access / export 不扩大 Data Access Scope；SDK built-in external tracing 保持关闭。
14. Retention 按 metadata、sensitive snapshot、aggregate、Answer Artifact 与 canonical source 分层；具体时长不提前猜测。
15. Trace Store 独立、append-only、versioned、reference-first；backend 技术选型 Pending。
16. Trace failure 不回滚成功业务结果，但必须显式暴露并标记 incomplete，禁止 silent loss。
17. Stage 1.9 只定义 operational metric dimensions，不定义 Stage 1.10 Evaluation Dataset、quality threshold 或 gate。

## 16. Deferred

### Implementation Pending

- Normalized Event、Failure、Coverage Descriptor 的具体 Python / JSON Schema；
- event name 字符串、nullable / enum 类型、schema migration 与 compatibility policy；
- Trace Collector / Store / projector 的 package layout、API 与 transaction implementation；
- Trace backend、query index、partition、batch / flush、buffering 与 deployment topology；
- Error Code 完整枚举、Exception mapping 与 user-facing error message；
- sensitive snapshot 的 redaction / allowlist 实现、角色权限、retention 具体时长与删除传播机制；
- operational dashboard、alert channel、sampling 与 production capacity planning；
- Data Plane ingestion / indexing rebuild 的细粒度 event taxonomy；Stage 1.2 `ImportBatch` 语义保持有效；
- OpenTelemetry 或其他 exporter 是否接入；若接入必须位于 privacy projection 之后。

### Stage 1.10 Pending

- Evaluation Dataset、Failure Case labels、人工标注与 review rubric；
- Router / Planner / Retrieval / Evidence / Citation / Answer quality metrics；
- accuracy、precision / recall、semantic entailment、sufficiency、Planner Utility；
- latency、token、coverage、citation、budget、stopping 的 threshold / gate；
- model / prompt / chunk / top-k / rerank / Tool Budget 参数校准；
- bounded repair、automatic retry、Evidence-aware stopping 的 Evaluation 与进入条件。

### Stage 1.11 Pending

- CLI / API / UI 对 Trace identity、terminal status、error 与 source review 的具体 exposure；
- public / operator-facing Trace 查询接口与返回 Schema；
- streaming transport 与 replay API。

## 17. Failure Cases

| Failure Case | 第一版架构处理 |
| --- | --- |
| Planner failure 后 Query 成功 | 保留 `planner.failed / degraded`，Route 仍为 planned，Runtime 记录 without-plan execution；Query 可 completed |
| Semantic index 只覆盖查询时间范围的一部分 | Retrieval event / Tool Result 记录 query-scope `partial` 与 gaps；Evidence limitation 原样传播 |
| Global coverage 很高但当前群未建索引 | 当前 effective scope 为 `none / partial`，禁止用 global ratio 代替 |
| denominator 无可靠来源 | `unknown`，不伪造百分比 |
| Tool known contract error 后 Agent 改用其他 Tool | 保留原 Tool code 与 `returned_to_agent`；后续 Tool operation 建立独立因果链接 |
| Unknown Tool Adapter exception | 不变成 generic model-visible Tool error；保留 origin 并使 Runtime terminal failed |
| Citation 引用不存在 locator | `CITATION.*` owner 记录 validation failure；Answer 不提交；Query terminal 引用该根因 |
| 最后 token 已发送但 Conversation commit 失败 | 不产生 completed；记录 Answer / Store failure，Trace terminal failed |
| Trace Store 暂时失败但 Answer 已成功提交 | 不回滚 Answer；显式 `TRACE.*` operational failure，Trace 标为 incomplete |
| SDK 内部 event 字段升级 | Adapter 负责归一化；CLI / Trace Store 不直接依赖 SDK raw type |
| Trace 中保存完整聊天和 Tool Result | 违反 default data minimization；只保留 reference / bounded approved snapshot |
| 为 Stage 1.10 方便而永久保留所有原始 Trace | 禁止；Failure Case / Evaluation artifact 需要独立选择与治理 |

## 18. Validation / Regression Contract

当前仓库无业务代码，本阶段不伪造实现测试。实现阶段至少验证：

```text
同一次 Query 的跨 Router / Planner / Runtime / Tool / Retrieval / Evidence / Citation 事件共享 trace_id
单 Trace sequence 可确定性回放，跨并发 operation 通过 operation_id / parent_operation_id 关联
SDK raw event 不泄漏到 CLI / API / Trace storage contract
Planner failure + Runtime success 同时可表达，不改写 Route Decision
已知 Tool Contract Error 与未知 Adapter exception 进入不同路径
Abort、Budget、degradation、terminal failure 不互相混用
Citation validation failure 保留 CITATION ownership 并阻止 completed / commit
query-scope coverage 的 denominator 不因 index gap 缩小
unknown coverage 不输出伪造 ratio，coverage / truncated / unavailable / sufficiency 分轴
Trace projection 不包含 Chain-of-Thought、逐 token stream、credential 或默认完整聊天 / Tool payload
Trace access 与 sensitive reference resolution 不扩大 Data Access Scope
Answer Artifact 通过 identity 引用，不随 Trace retention 到期
sequence gap / collector failure / crash 产生 incomplete，而不是伪造 completion
unknown event version 显式失败或隔离，不 silent drop
SDK built-in external tracing 保持显式关闭
operational metrics 可从 sanitized events 派生，且不包含 Stage 1.10 quality threshold
```

## 19. Result、Trade-off 与 Reopen Conditions

### Result

Stage 1.9 将 Stage 1.3–1.8 分散的观察需求统一为 Trivae-owned Query Trace：既能沿因果链定位 Route、Plan、Tool、Retrieval、Evidence、Citation 与提交失败，也不把 SDK raw trace、聊天正文或 Evaluation 判断混入正式事件契约。

### Trade-off

- 归一化 boundary 与 versioned event 增加实现工作；换取 SDK 可替换、跨层一致与 Failure Attribution。
- 默认不保存完整内容使部分调查需要受控地回到 canonical source 或临时开启 bounded snapshot；换取更小的隐私、保留与外部导出风险。
- Trace persistence 不与业务提交组成分布式事务，因此 crash 时可能出现 incomplete Trace；换取第一版不引入未经证明的强一致基础设施，并明确暴露缺口。
- 不在运行时自动判定质量 Root Cause，定位需要结合 Failure Case / Stage 1.10 Evaluation；换取不把猜测写成事实。

### Reopen Conditions

只有以下新证据可以重开本 ADR，并必须记录 Reopen Reason：

- 合规或审计需求证明每次 Query 必须具有强一致、不可缺失的 audit trail；
- 真实 Failure Case 证明 reference-first / bounded snapshot 无法定位主导故障；
- Trace volume 或 latency 证明每事件 append 模型无法满足实际运行约束；
- SDK / provider 只能通过其 built-in tracing 暴露 Trivae 必需且无法从 Hook / StreamEvent 获得的事实，并且隐私评估通过；
- 多进程 / 分布式执行使当前 `trace_id + operation causality + sequence` 语义不足；
- 数据删除、访问控制或跨地区合规要求改变 retention / storage boundary；
- Stage 1.10 证明某类在线 quality attribution 可以确定性、低误报地完成，并确实改善 Failure Attribution。

“常见 observability 平台都有”“以后可能需要”“多存一些方便调试”或“先定义 Evaluation threshold 比较完整”不构成 Reopen Reason。
