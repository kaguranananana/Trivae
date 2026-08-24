# Stage 1.9：Trace / Observability 架构决策

> 状态：**Confirmed / Completed（Stage 1.9，修订版）**
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

### Reopen Record（本次修订）

- **Reopen Reason**：补充的 ChatLab 实现证据显示，其 Agent Debug Mode 会扩大记录详细度，并保留用于解释一次模型执行的完整或近完整上下文；ChatLab 官方变更日志也明确记录了 Debug Mode 的原始数据查看和完整 LLM Context 记录能力（见 [ChatLab changelog](https://github.com/ChatLab/ChatLab/blob/main/changelogs/cn.md)）。Trivae 是 Local-first、当前处于开发和 Failure Case 定位阶段；原先把 reference-first 作为几乎唯一默认路径，可能无法解释“模型当时实际看到了什么”。
- **修订范围**：只重开 Decision 8（Trace data minimization）与 Decision 9（Retention），以及对应的 privacy projection / guidance；Normalized Event、Failure Attribution、Coverage、Error Code ownership、append-only storage 与 Stage 1.10 boundary 不变。
- **修订结果**：`normal` 与 `debug` 成为正式 Trace Profile。Normal 允许 bounded / redacted actual content；Debug 在授权范围内允许完整或近完整的 model-visible / system-visible execution facts，但仍禁止 secrets、越权数据和 hidden Chain-of-Thought。

### Amendment（2026-08-23）：Debug model-visible execution facts 与 Transcript

本次实现确认了一个具体 Observability Gap：OpenAI Agents SDK 的 `on_llm_start` 会在 input filter/deduplication 之后收到本次 Provider 调用的实际 `input_items`，其中除了 `{role, content}` 消息，还包括 `function_call` 与 `function_call_output`。原先只投影字符串 `role/content`，因此第二轮模型输入中的 previous assistant tool action 和 Tool Result 会从 Trace 消失。

修订后的实现契约是：

- adapter 在 `on_llm_start` 捕获当时真正传入 Provider 的 model-visible input；在 `on_llm_end` 捕获公开的 assistant message / function-call action；二者先转换为 Trivae-owned plain data，再进入既有 Collector、CapturePolicy、NormalizedQueryEvent 与 SQLite Trace Store。
- Transcript 中的 Tool Result 正文必须来自后续 model turn 的 `function_call_output.output`，不能从 Conversation Store、Retrieval 或 `ToolResultRecord` 重新查询/拼装出更完整的内容。Retrieval 的 returned/total、partial、truncated、coverage 作为独立诊断事实保留。
- 如果 SDK 已将结构化 Tool Result 序列化成超长字符串，adapter 可以从同一 `function_call_output.output` 生成 bounded `output_projection`，帮助 formatter 在原文截断时展示正文；它不是第二份运行事实，也不能脱离该 model input 或通过数据库查询生成。
- `.log` 的 `EXECUTION TRANSCRIPT` 与 `RAW TRACE EVENTS` 都是同一份 `StoredTrace` 的 derived projection；Transcript 不建立第二套 runtime logging pipeline，也不改变 canonical event boundary。
- 人工可读 `.log` 的默认 projection 只输出 `Trace Summary -> EXECUTION TRANSCRIPT` 并在 `[FINAL ANSWER]` 后结束；`RAW TRACE EVENTS` 保留为 SQLite / `trace show` 的 canonical detail，并可通过 `trace export --view raw` 显式投影。Transcript 默认按已捕获 model-visible context 的稳定前缀显示 delta，需要逐轮核对完整 request 时使用 `--context full`。这只是 presentation projection，不改变 StoredTrace、CapturePolicy 或事件事实。
- Debug capture 继续允许 scope 内完整或近完整的 model-visible/system-visible execution facts，并将 `AnswerArtifact.answer_text` 在 finalization 成功后作为 Debug execution snapshot 进入 Trace；Conversation Store / Answer Artifact 仍是业务事实源。
- 当前 CapturePolicy 上限为 Normal `512` 字符/`16` 个集合项/深度 `6`，Debug `20,000` 字符/`128` 个集合项/深度 `10`，均保留 secret redaction 和可见 limitation。

本 amendment 不改变 hidden reasoning 决策：`reasoning` item、provider internal reasoning、SDK scratchpad、Chain-of-Thought 和未经 allowlist 的 SDK raw fields 不进入 Trace。完整 model-visible execution facts **不等于** hidden Chain-of-Thought；任何未来 provider reasoning summary 若要支持，仍必须是 optional provider-specific output，不能成为 execution ground truth 或 Evaluation label。

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
├── payload                     # 由 stage owner 定义；详细度受 Trace Profile / capture policy 控制
├── limitations?                # coverage / truncated / unavailable 等，不折叠成 evidence sufficiency
└── failure?                    # 结构化归因，见 Decision 5
```

语义约束：

- `trace_id` 对应一次 Query Execution；Regenerate、显式重新运行或应用级新尝试使用新的 `trace_id`，通过 `request_id` 或业务关联字段表达关系，不覆盖旧 Trace；
- `event_id` 是事件身份；`operation_id / parent_operation_id` 表达跨组件因果关系，例如 Agent Tool Call → Tool Execution → Retrieval Operation；
- `sequence` 用于单 Trace 确定性回放，`occurred_at` 表达源组件发生时间，`observed_at` 表达 Collector 接收时间；不能只依赖 wall-clock timestamp 排序；
- `phase` 表达真实发生的边界事实。不能因为最终请求成功，就把先前 `planner.failed` 改写为 `planner.completed`；
- `payload` 由 stage owner 定义当前边界所需的 domain facts；实际记录详细度受 Trace Profile / capture policy 控制，不能放 Chain-of-Thought；Router `reason` 仍是短诊断说明，不是隐藏推理；
- 具体字段命名、类型、nullable 规则、serialization、event version migration 和 package layout 属于 Implementation Pending。

## 4. Decision 3：跨阶段 normalized event families

第一版必须能够表达以下稳定边界；表中的名称是语义 family，不要求实现逐字使用同名字符串：

| Stage | 必须可观察的边界 | 关键事实 |
| --- | --- | --- |
| Query / Context | received、context prepared / failed、terminal completed / failed / aborted | request / conversation identity reference、effective data scope reference、terminal outcome、total latency |
| Router | decision、degraded、failed invocation | `route / confidence / reason / source`、Rule / LLM path、原始 failure、最终 Route |
| Planner | started、validated / sanitized、completed、failed、skipped | invocation reason、Plan identity / version、validation facts、failure category、`executed_without_plan` |
| Runtime / Model | runtime started、model turn completed / failed、budget reached、final synthesis started、runtime terminal | model、prompt version、usage、Tool Round、budget reason、lifecycle transition |
| Tool | call started、completed、partial、contract error、aborted | tool name、argument / result diagnostic projection（profile-governed）、result identity、status、latency、error code |
| Retrieval | operation started / completed / partial / failed、context expansion | query / rewrite projection、strategy、filters、index / model version、candidate counts / ids / ranks、query-scope coverage、truncated / unavailable |
| Evidence | selection completed / failed | criterion / selected Evidence diagnostic facts（profile-governed）、selected Evidence / Source identities、sufficiency、limitations |
| Citation | validation completed / failed | validated / unresolved binding counts、locator / scope validation outcome、owned error code |
| Answer | finalization completed / failed、commit completed / failed | Answer Artifact identity、Assistant Message identity、commit boundary；commit event 不复制 canonical Answer Artifact，Debug capture 可按 Profile 保存当次 Final Answer 内容 |
| Trace | collector degraded / incomplete | missing sequence / operation、collector or storage error、trace completeness status |

表中的 `projection`、`diagnostic facts` 与 `snapshot` 描述的是 Event Family 的语义内容，不是所有 Profile 的固定截断规则。具体保存多少由 `normal / debug` Profile 与 capture policy 决定；Answer 的 commit ownership 仍归 Conversation Store / Answer Artifact，和 Debug 为解释执行而保存当次 Final Answer 内容是两件事。

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

## 9. Decision 8：Trace Profile 控制记录详细度，而不是永远 reference-only

### Decision

Trace 采用两个正式的一等 Profile：`normal` 与 `debug`。Profile 可以由 deployment / local run configuration 选择，也可以按一次 Query 显式选择；Profile identity 与 capture policy 必须写入 Trace metadata。Debug 不是错误发生后的隐式 fallback，而是为了在执行前就捕获可诊断事实的明确运行模式。

```text
Trace Profile
├── normal
│   ├── 完整结构化事件与 lifecycle
│   ├── latency / usage / failure / coverage / identity
│   └── 对有诊断价值的实际内容做 bounded / redacted capture
└── debug
    ├── normal 的全部内容
    └── 在授权范围内保留完整或近完整的 model-visible / system-visible facts
```

### Normal Profile

Normal 仍然以低噪声结构化事实为主，但不再规定“默认只能保存 reference / count / rank”。在安全和体积策略允许时，可以保存：

- User Query、Router input / output、Planner input / output 的 bounded / redacted projection；
- System Prompt、Rendered Plan Guidance、Model-visible Context 的 bounded / redacted projection；
- Tool arguments、Tool results、Retrieval candidates、Context Expansion result 的 bounded / redacted content；
- Evidence Selection、Citation Validation、Final Answer 的 bounded / redacted content；
- identity、latency、counts、status、versions、Error Code、coverage 与 execution limitations。

如果发生截断，必须显式记录 `truncated`、capture policy 和可定位的原因，不能让“内容被截断”看起来像“模型本来就没看到”。

### Debug Profile

Debug 的目标是保留**能够重现和解释一次执行的 model-visible / system-visible facts**，而不是只留下可重新查询的 Message ID。只要数据在本次 Run 的 Data Access Scope 内，且通过 secret / privacy projection，Debug 可以保存完整或近完整的：

- User Query、Runtime Context 的安全诊断投影、Router / Planner 实际输入与输出；
- 最终 System Prompt、Plan Guidance、实际发送给模型的 Model-visible Context；
- Tool arguments、Tool results、Retrieval results、Context Expansion 内容；
- Evidence Selection、Citation Validation 中间结果和 Final Answer；
- provider request / response diagnostic、模型 / prompt / index version、exception 与受控 stack diagnostic。

Debug 仍然明确禁止：

- credentials、API keys、access tokens、connection strings 等 secrets；
- 超出当前 Run Data Access Scope 的数据；
- provider hidden reasoning、hidden Chain-of-Thought 或把它们变成 Trivae contract；
- 未经 privacy projection 的 SDK raw external trace。

Debug 允许完整内容，不等于允许无限内容：实现可以因安全或明确的 storage cap 截断，但必须产生可观察的 `truncated` / Trace completeness 事实。Debug 内容是本地受控诊断数据，不自动获得更高的业务数据权限。

### Access / Export Boundary

- Trace Profile 不改变 Data Access Scope；Debug 只能记录该 Run 本来已经能看到的内容；
- model-visible / user-visible projection、内部 operator view 与外部 exporter 是不同数据面，必须分别 allowlist；
- OpenAI Agents SDK built-in external tracing 继续显式关闭；Debug 不等于把完整 Trace 自动发送到第三方；
- 未来 exporter 只能消费经过 privacy projection 的 Trivae Event，不能绕过 Collector 直接订阅 SDK raw event；
- Debug profile 的启用、操作者 / deployment identity、capture policy 与是否发生截断必须进入 Trace metadata，便于审计“为什么这次保存了更多内容”。

## 10. Decision 9：Retention 随 Profile 与部署环境配置，不能假定 Debug 必须更短

Retention 仍按数据类别分层，但 Stage 1.9 不再规定 sensitive debug data 必须短于普通 Trace。Profile 和 retention 是两个正交配置：Debug 可以更详细，但不自动意味着某个固定 TTL；部署环境决定是否允许、谁能读、何时清理。

| Data class | Retention principle |
| --- | --- |
| Trace metadata / lifecycle events | 可配置，用于运行定位与 operational trend |
| Normal content-bearing payload | 随 Normal capture policy 配置，截断 / 脱敏状态必须可见 |
| Debug content-bearing payload | Local-first 开发环境可以按显式配置保留到人工清理；生产环境必须由部署策略明确 retention、访问和删除边界；本 ADR 不强制比 Normal 更短 |
| Aggregated operational metrics | 不携带聊天正文和不必要的高基数身份；可独立保留 |
| Validated Answer Artifact / Assistant Message | 服从 Conversation Store 生命周期，不因 Trace 到期被删除 |
| Canonical Message / Raw Source | 服从 Data Plane 与原平台策略，不由 Trace Store 取得 ownership |
| Failure Case / future Evaluation artifact | 必须经过独立选择与治理；不能通过延长全部 Trace retention 自动生成 |

生产环境启用前必须配置 profile、retention、访问和删除策略；具体天数、合规地区、角色矩阵与 legal policy 属于部署 / 产品隐私决策，不在本 ADR 猜测。Local-first 不等于无治理：实现必须提供显式启用、查看和清理 Debug 数据的能力。

Source / Conversation / Message 被授权删除或访问范围变化时，Trace 中的 content-bearing payload 与 reference resolution 必须服从相应删除 / 不可见语义；具体 propagation mechanism 属于 Implementation Pending。

## 11. Decision 10：Trace Storage 是独立 append-only 事实存储，技术选型 Pending

### Storage Principles

1. **独立 ownership**：Trace Store 不等于 Canonical Message Store、Conversation Store、SDK Trace backend 或业务日志文件。
2. **Append-only within retention**：事件写入后不原地重写；顺序和因果关系由 envelope 表达。
3. **Schema versioned**：每个事件有 schema version；读取 / projection 必须显式处理支持的版本，不能 silent drop unknown event。
4. **Profile-governed capture**：引用 Tool Result、Message、Evidence、Answer Artifact identity 作为稳定关联；Normal / Debug 按各自 capture policy 保存 bounded、完整或近完整的允许内容，不把 reference-first 当成唯一合法形态。
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

依据 Stage 1.7 已确认的参考实现核验与本次补充的 ChatLab evidence，Trivae 继承 ChatLab 的以下架构方向：

- Core / SDK event 先转换成项目自有 normalized event；
- Event Handler / Collector 再驱动 UI state、stream 与内部日志；
- Tool start / update / end、turn end、usage 等关键边界可观察；
- Normal / Debug 是不同记录详细度的显式运行模式；Debug 可以保留实际 Model-visible Context、Tool Call / Result、Final Response 等诊断事实；
- 项目自己掌握 logging / event contract，而不是让 Agent SDK 类型成为产品接口。

### 不直接继承 / 明确化

- Trivae 的正式 Trace 横跨 Router、Planner、Retrieval、Evidence 与 Citation，不只记录 Agent Core；
- 不把完整 Query、聊天正文、Tool Result 或模型输入输出默认发送到外部 tracing backend；Debug 内容仍留在 Trivae 的本地受控 Trace boundary 内，除非经过独立 privacy projection；
- 不把 ChatLab 的 2000 字符截断、日志文件格式、数据库字段、默认保留期或 UI event 名直接冻结为 Trivae Schema；
- ChatLab 的 Debug Mode 证明“详细内容对 Failure Attribution 有价值”，但不自动决定 Trivae 的 retention 天数、权限模型或 storage backend；
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
3. Conceptual envelope 包含 version、identity、correlation、sequence、time、stage、operation、phase、causality、profile-governed payload、limitation 与 failure。
4. Trace 事件 append-only；状态、timeline 与 metrics 是可重建 projection。
5. Failure Attribution 区分 origin stage、observed stage、handling 与 terminal query outcome。
6. Recovery / degradation 不抹掉原始错误；Tool failure、Runtime failure、Abort 与 Budget 分开。
7. 在线 Trace 保存诊断事实，不伪造需要人工或 Evaluation 才能确定的质量 Root Cause；`normal` / `debug` capture level 必须明确记录。
8. Query-scope coverage 以 `requested scope ∩ Data Access Scope` 后的 effective scope 为基准；索引缺口不能缩小 denominator。
9. Coverage 使用 `complete / partial / none / unknown / not_applicable`，只有口径可靠时才提供 numerator / denominator / unit；不平均不同 capability coverage。
10. coverage、truncated、unavailable、Tool status 与 Evidence sufficiency 分轴表达。
11. Error Code 由稳定 owner namespace 拥有；跨层传播保留 underlying code，不用 wrapper code 覆盖根因。
12. Trace 采用 `normal` / `debug` Profile；Normal 允许 bounded / redacted actual content，Debug 在授权范围内允许完整或近完整的 model-visible / system-visible facts；两者都不保存 hidden Chain-of-Thought、secrets 或越权数据。
13. Trace access / export 不扩大 Data Access Scope；SDK built-in external tracing 保持关闭。
14. Retention 按 metadata、Normal payload、Debug payload、aggregate、Answer Artifact 与 canonical source 分层；Stage 1.9 不强制 Debug 比 Normal 更短，具体时长、权限与清理由部署 / 实现配置。
15. Trace Store 独立、append-only、versioned；reference 是稳定关联方式，Normal / Debug capture policy 决定允许内容的保存详细度；backend 技术选型 Pending。
16. Trace failure 不回滚成功业务结果，但必须显式暴露并标记 incomplete，禁止 silent loss。
17. Stage 1.9 只定义 operational metric dimensions，不定义 Stage 1.10 Evaluation Dataset、quality threshold 或 gate。
18. 本次 Reopen 只调整 Data Minimization、Trace Profile、Sensitive Content Capture 与 Retention；其他 Stage 1.9 决策保持不变。

## 16. Deferred

### Implementation Follow-ups

M6 已在 `src/trivae/observability/` 落地 Normalized Event、Failure、Trace Collector、SQLite Store 和 projector；具体可执行契约见本节末的 M6 implementation record。仍待后续任务决定：

- event schema migration 的多版本升级工具和部署迁移窗口；
- Trace backend、query index、partition、batch / flush、buffering 与 deployment topology；
- Error Code 完整枚举、Exception mapping 与 user-facing error message；
- Trace Profile 的配置来源 / 启用边界、Normal / Debug capture policy、redaction / secret stripping、角色权限、retention 具体时长与删除传播机制；
- operational dashboard、alert channel、sampling 与 production capacity planning；
- Data Plane ingestion / indexing rebuild 的细粒度 event taxonomy；Stage 1.2 `ImportBatch` 语义保持有效；
- OpenTelemetry 或其他 exporter 是否接入；若接入必须位于 privacy projection 之后。

### Stage 1.10 Implementation / Real-run Calibration Pending

- Evaluation Dataset、Failure Case labels、人工标注与 review rubric；
- Router / Planner / Retrieval / Evidence / Citation / Answer quality metrics；
- accuracy、precision / recall、semantic entailment、sufficiency、Planner Utility；
- latency、token、coverage、citation、budget、stopping 的 threshold / gate；
- model / prompt / chunk / top-k / rerank / Tool Budget 参数校准；
- bounded repair、automatic retry、Evidence-aware stopping 的 Evaluation 与进入条件。

Stage 1.10 已确认 Evaluation 只引用 Stage 1.9 canonical Trace，不改写 Trace；Run / Review / Diagnosis 的具体 artifact、runner、quality rubric、真实 baseline、数值 gate 与 stopping 校准仍 Pending。

### Stage 1.11 Application Boundary 已确认；实现 Pending

- CLI / API / UI 对 Trace identity、terminal status、error 与 source review 的具体 exposure；
- public / operator-facing Trace 查询接口与返回 Schema；
- streaming transport 与 replay API；入口必须复用 Stage 1.11 的 Application、Normalized Event 与 Trace correlation 边界。

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
| Normal Trace 内容过大 | 按 Normal capture policy 做 bounded / redacted capture，并显式记录 `truncated`；不能静默丢弃 |
| Debug Trace 需要解释模型为何做出错误结论 | 在 Data Access Scope 内保留实际 Model-visible Context、Tool arguments / results、Retrieval / Evidence 中间事实和 Final Answer；不依赖 reference 重建猜测 |
| Debug Profile 被误当成授权开关 | Profile 不改变 Data Access Scope；越权内容、secrets、hidden Chain-of-Thought 仍禁止记录 |
| Debug Trace 保留多久没有统一答案 | 由 local / production deployment policy 配置；Stage 1.9 不假定 Debug 必须短于 Normal，但必须显式可查和可清理 |
| Trace 中保存完整聊天和 Tool Result | Normal 不默认无限保存；Debug 在显式 profile 与 privacy policy 允许时可以保存完整或近完整内容 |
| 为 Stage 1.10 方便而永久保留所有原始 Trace | 禁止；Failure Case / Evaluation artifact 需要独立选择与治理 |

## 18. Validation / Regression Contract

M6 的实测命令、回归矩阵和已知风险记录在 `.trellis/tasks/08-23-m6-trace-observability/validation.md`；后续实现必须保持以下 contract：

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
Trace profile 明确记录为 normal / debug，且 Normal / Debug capture policy 可回放
Normal profile 对实际 Query / Prompt / Tool / Retrieval / Evidence / Answer 内容按 policy bounded / redacted，并显式记录 truncation
Debug profile 在 Data Access Scope 内可回放实际 Model-visible Context、Tool arguments / results、Retrieval / Evidence 中间事实与 Final Answer
任何 profile 都不包含 Chain-of-Thought、hidden reasoning、credential、secret 或越权数据
Trace access 与 sensitive reference resolution 不扩大 Data Access Scope
Answer Artifact 通过 identity 引用，不因 Trace retention 到期而被错误删除
Normal / Debug retention、启用者、capture policy 与清理行为可追踪
sequence gap / collector failure / crash 产生 incomplete，而不是伪造 completion
unknown event version 显式失败或隔离，不 silent drop
SDK built-in external tracing 保持显式关闭
operational metrics 可从 sanitized events 派生，且不包含 Stage 1.10 quality threshold
```

## 19. Result、Trade-off 与 Reopen Conditions

### Result

Stage 1.9 将 Stage 1.3–1.8 分散的观察需求统一为 Trivae-owned Query Trace：既能沿因果链定位 Route、Plan、Tool、Retrieval、Evidence、Citation 与提交失败，又能通过显式 Normal / Debug Profile 在本地受控地保留解释执行所需的实际 model-visible / system-visible facts，同时不把 SDK raw trace、hidden reasoning 或 Evaluation 判断混入正式事件契约。

### Trade-off

- 归一化 boundary 与 versioned event 增加实现工作；换取 SDK 可替换、跨层一致与 Failure Attribution。
- Normal / Debug 双 Profile 增加 capture policy、隐私投影、体积控制与 retention 配置复杂度；换取在 Failure Case 中直接看到实际 Context、Tool Result 与最终输入输出，不必依赖 reference 重建猜测。
- Debug 允许更完整内容会扩大本地诊断数据的敏感面；换取 Local-first 开发阶段更高的 Failure Attribution 价值，前提是 secrets、越权数据和 hidden reasoning 仍被硬排除。
- Trace persistence 不与业务提交组成分布式事务，因此 crash 时可能出现 incomplete Trace；换取第一版不引入未经证明的强一致基础设施，并明确暴露缺口。
- 不在运行时自动判定质量 Root Cause，定位需要结合 Failure Case / Stage 1.10 Evaluation；换取不把猜测写成事实。

### Reopen Conditions

只有以下新证据可以重开本 ADR，并必须记录 Reopen Reason：

- 合规或审计需求证明每次 Query 必须具有强一致、不可缺失的 audit trail；
- 真实 Failure Case 证明 Normal / Debug Profile 仍无法定位主导故障，或 Debug capture 的 privacy / storage cost 已经超过诊断收益；
- Trace volume 或 latency 证明每事件 append 模型无法满足实际运行约束；
- SDK / provider 只能通过其 built-in tracing 暴露 Trivae 必需且无法从 Hook / StreamEvent 获得的事实，并且隐私评估通过；
- 多进程 / 分布式执行使当前 `trace_id + operation causality + sequence` 语义不足；
- 数据删除、访问控制或跨地区合规要求改变 retention / storage boundary；
- Stage 1.10 证明某类在线 quality attribution 可以确定性、低误报地完成，并确实改善 Failure Attribution。

“常见 observability 平台都有”“以后可能需要”“多存一些方便调试”或“先定义 Evaluation threshold 比较完整”不构成 Reopen Reason。

## 20. M6 Implementation Record

### 1. Scope / Trigger

- Trigger：M0–M5b 已有 Query、Runtime、Tool、Retrieval、Evidence/Citation 和 Conversation commit boundary，需要一条 Trivae-owned、local-first、可回放的诊断事实链。
- Ownership：`src/trivae/observability/` 拥有 normalized event、capture、SQLite Trace Store 和 projection；既有层只在真实 boundary 发出事实。
- Non-goal：不引入外部 tracing SaaS、HTTP/UI/SSE、vector/hybrid retrieval、Evaluation quality judgment、CoT 或逐 token 永久存储。

### 2. Signatures

- `TraceCollector(store, trace_id, request_id, profile="normal")`：创建 metadata，`emit(...) -> NormalizedQueryEvent | None`；Store/capture failure 生成 `TRACE.*` diagnostic 并让业务继续。
- `SQLiteTraceStore.create_trace(...)`、`append_event(NormalizedQueryEvent)`、`mark_terminal(...)`、`read_trace(...) -> StoredTrace`；使用独立 SQLite connection。
- `TrivaeApplication.read_trace(trace_id) -> TraceProjection`。
- `TrivaeApplication.read_import_diagnostics(source_file=None, batch_id=None) -> ImportDiagnosticsProjection`。
- `QueryRequest.trace_profile: Literal["normal", "debug"]`；`QueryResult.trace_id: str | None`。
- `AgentRunRequest.trace_context`、`RuntimeContext.trace_context` 和 `RuntimeEvent.run_id/model_visible_context` 都是进程内 additive 字段。

Trace tables are `traces` and append-only `trace_events`; `trace_events` enforces `UNIQUE(trace_id, sequence)`, stores `schema_version`, serialized bounded payload/limitations/failure, and orders replay by `sequence`.

### 3. Contracts

- Normalized event 必须包含 schema_version、event/request/trace identity、sequence、occurred/observed timestamps、stage、operation、phase、operation identity、outcome、duration、bounded payload、limitations 和 FailureInfo。
- `FailureInfo` 保存 `error_code`、`origin_stage`、`observed_stage`、category、handling、cause event/operation、retry count 和 safe diagnostic reference。
- Normal capture 上限为 512 字符/16 个集合项；Debug 为 20,000 字符/128 个集合项；两者都递归 redacted，且 `chain_of_thought/cot/hidden_reasoning/reasoning_content` 不落明文。
- `RuntimeEvent.model_visible_context` 保存 SDK hook 在 Provider 调用前实际收到的安全 input item projection；`RuntimeEvent.observable_output` 保存 assistant visible message/function-call projection；`RuntimeEvent.content_delta` 仍只通过 stream、不持久化。Runtime 的 local run_id 每次 execution 新建，不等同 request_id；M5 旧 tool locator 的显式 request-id alias 仅用于 validated provenance compatibility。
- `query.completed` 只在 `ConversationStore.commit_turn()` 返回后写入；finalization/runtime/commit failure 不产生 completed。
- Import diagnostics 只读取既有 `import_batches` / `import_errors`，不新建第二套 ingestion facts，也不伪装为 RuntimeEvent。

### 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| Empty identity / invalid sequence / invalid event contract | `TraceContractError`，不写入 event |
| Unsupported payload object / unsupported key | `TRACE.PAYLOAD_INVALID`，collector degraded，业务异常不被替换 |
| Trace SQLite create/append/terminal failure | `TRACE.CREATE_FAILED` / `TRACE.APPEND_FAILED` / `TRACE.TERMINAL_UPDATE_FAILED` log，业务结果保持原语义 |
| Router optional failure | Router decision retained，`ROUTER_*` origin=router，handling=`static_route_retained` |
| Planner failure | `PLANNER_*` origin=planner，handling=`executed_without_plan`，Runtime continues |
| Tool contract error | origin=tool，observed=tool/runtime，handling=`returned_to_agent` |
| Retrieval exception/partial | origin=retrieval，wrapper observed=tool，Tool envelope status/coverage retained |
| Citation failure | origin=citation，observed=answer/query，no artifact commit |
| Missing query terminal event | projection `incomplete`，不猜测 terminal status |

### 5. Good / Base / Bad Cases

- Good：同一 trace 的 sequence 从 1 单调递增；`tool.call` 的 child `retrieval.search` 通过 parent operation 可回放；commit 完成后才有 query.completed。
- Base：run-only injected runtime 没有 stream 时只补 runtime start/terminal；真实 SDK runtime 仍映射非 delta RuntimeEvent。
- Bad：把 request_id 当 run_id、把 Retrieval failure 改写成 Tool generic failure、用 trace summary column 替代 event history、或把 Trace exception 静默吞掉，均违反本 contract。

### 6. Tests Required

- Contract/Privacy：event identity、sequence、unique constraint、normal/debug bound、credential/CoT redaction、visible limitations。
- Persistence/Replay：temporary SQLite close/reopen、append-only、missing terminal/incomplete、projection metrics。
- Vertical integration：Application QueryResult.trace_id、Router/Planner/Runtime/Tool/Retrieval/Evidence/Citation/commit timeline、Tool→Retrieval parent identity。
- Failure attribution：Router degradation、Planner fallback、Tool contract、Retrieval error/partial、Citation failure、commit failure、abort/budget、Trace Store failure。
- Import boundary：source/batch filter、counts、error code、record index/locator/detail；不创建 Query events。

### 7. Wrong vs Correct

Wrong：

```python
request_id = run_id
trace_events.append("raw SDK event")
conversation_store.commit_turn(...)
write_query_completed()
```

Correct：

```python
request_id = request.request_id or new_request_id()
run_id = new_runtime_run_id()
collector.emit(stage="runtime", operation="runtime.run", phase="completed", ...)
conversation_store.commit_turn(...)
collector.emit(stage="query", operation="query.completed", phase="completed", ...)
```

The correct path keeps identity semantics separate, normalizes at the SDK boundary, and makes the Conversation commit the explicit completion boundary.

## 21. Interactive streaming projection implementation record（2026-08-23）

实时 CLI 与 M6 Trace 现在共享同一批运行事实，但使用两个生命周期不同的投影：

```text
Runtime / normalized domain event
        ├── Trace Collector → CapturePolicy → SQLite Trace Store
        └── in-memory observer → QueryStreamAdapter → CLI Renderer
```

- `TraceCollector` 在 normalized event 构造成功后可通知进程内 observer；CLI 不读取或轮询 Trace Store，Trace Store failure 也不把它变成消息队列。
- Runtime token / reasoning delta 通过同一个 `TraceableAgentRuntime` stream 通知 live adapter；persistent mapper继续忽略它们。Normal/Debug Trace 都不保存 Provider reasoning 或 Answer token events。
- Router、Planner、Tool、Retrieval、Finalization、Conversation commit 与 Query terminal 仍由各自真实 M6 boundary 发出；CLI 只消费其适合人读的 projection，不保存终端文本作为核心 Trace payload。
- live `QueryStreamEvent.sequence` 只负责一次实时投影的确定顺序；M6 `NormalizedQueryEvent.sequence` 仍是持久化 Trace 的 canonical replay sequence，两者通过 `source_sequence/source_operation/trace_id` 关联而不混用身份。

## CLI projection addendum（2026-08-25）

live CLI 仍从 `QueryStreamAdapter` 接收同一次 Query 的 normalized facts；normal/verbose renderer
不输出 raw event sequence、operation identity、JSON artifact、provider raw payload 或 hidden
CoT。Trace Store 不是实时队列，`/status`、`/source`、`/history`、`/resume` 和 feedback 不轮询
Trace Store。unknown exception 由 logging 保留 root cause，CLI 只投影 bounded diagnostic；Trace
identity 仍可用于后续 `trace` 查看。
