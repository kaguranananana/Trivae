# Stage 1.11：Application Boundary 与 Python 工程结构架构决策

> 状态：**Confirmed / Completed（Stage 1.11，架构边界）**
>
> 本 ADR 将 Stage 1.1–1.10 已确认的内部架构映射到 Python 工程的 package ownership、Application Boundary、入口适配器与生命周期。它确认代码如何组织、CLI / HTTP API / Evaluation 如何进入同一套 execution core，以及跨层契约由哪一层拥有。
>
> 本 ADR 不创建业务代码，不冻结 Python / JSON / Database Schema、CLI / HTTP 框架版本、真实 Evaluation runner、真实 baseline 或产品 UI。架构已沉淀不等于业务实现已完成。

---

## 0. Architecture Governance 与承接边界

本阶段遵循项目级 [ChatLab as Reference Implementation](../architecture.md#architecture-principle-chatlab-as-reference-implementation) 原则，并承接 Stage 1.1–1.10 已确认的边界：

- Data Plane 与 Query Plane 分离；Query Plane 通过 Tool / Capability Layer 使用 Data Plane 能力。
- Router 只判断 standard_execution / planned_execution 的执行复杂度；两条路径使用同一个 Agent Runtime。
- Planner 是进入 Runtime 前一次性的 bounded、soft guidance，不拥有 Workflow、Step Executor 或执行状态。
- Agent Runtime 由 Trivae-owned adapter 接入 OpenAI Agents SDK；SDK 类型不能向上泄漏为产品或公共业务 contract。
- Retrieval Candidate 不等于 Final Evidence；Evidence、Citation、Answer Finalization 与 Citation validation 是独立边界。
- Stage 1.9 的 Normalized Query Event 是 Stream Projection 与 Trace Collector 的共同语义边界；Trace 是 append-only 运行事实。
- Stage 1.10 的 Evaluation Case Bundle、Snapshot、Scope、Controlled Variant、forced-path Planner Utility 与 paired comparison 必须复用生产执行语义。

Stage 1.11 只回答“系统从哪里进入、如何装配、哪些契约在入口之间共享、代码如何保持边界”。它不重新设计 Router、Planner、Runtime、Retrieval、Evidence / Citation、Trace 或 Evaluation 的内部决策。

## 1. Context：为什么需要 Application Boundary

Stage 1.1–1.10 已经确定了 Query 内部主链路，但如果没有工程入口和装配边界，以下 Failure Case 很容易出现：

```
CLI 自己创建 Router / Runtime
API 使用另一套 Config / Store
Evaluation 复制一套 eval_runtime / eval_retrieval
SDK raw event 直接进入 CLI / API
Trace / Error 在不同入口重新定义
```

这些问题不一定在单个模块的 Unit Test 中暴露，却会使 CLI、HTTP API 与 Evaluation 的结果不再具有相同语义，破坏 Stage 1.10 的 paired comparison，也让 Stage 1.9 的 Failure Attribution 失去完整链路。

Trivae v1 当前只有一个 Python Runtime、SQLite、Retrieval、OpenAI Agents SDK、CLI、HTTP API 与 Evaluation 需求，没有 ChatLab 同时处理 Desktop、Electron、Browser Runtime、Node Runtime、WASM、MCP 和 resident service 的物理拆分压力。因此应继承 ChatLab 的 ownership 原则，适配其仓库物理结构。

## 2. Decision 1：v1 使用单 Python distribution，内部按架构 ownership 分包

### Decision

Trivae v1 采用：

```
distribution: trivae
package root: src/trivae
```

第一版不拆成多个可独立发布的 Python distribution，不直接复制多 workspace monorepo。单 distribution 只决定 packaging 物理承载方式，不取消内部模块边界。

### Conceptual Package Layout

```
Trivae/
├── pyproject.toml
├── README.md
├── src/
│   └── trivae/
│       ├── __init__.py
│       ├── __main__.py
│       ├── config/
│       ├── bootstrap/
│       ├── data/
│       │   ├── model/
│       │   ├── ingestion/
│       │   ├── storage/
│       │   └── indexing/
│       ├── retrieval/
│       │   ├── lexical/
│       │   ├── semantic/
│       │   ├── structured/
│       │   └── context_expansion/
│       ├── capabilities/
│       ├── query/
│       │   ├── context/
│       │   ├── router/
│       │   ├── planner/
│       │   ├── runtime/
│       │   ├── evidence/
│       │   ├── citation/
│       │   └── finalization/
│       ├── conversation/
│       ├── observability/
│       │   └── projections/
│       ├── evaluation/
│       │   ├── cases/
│       │   └── review/
│       └── interfaces/
│           ├── cli/
│           └── api/
└── tests/
    ├── unit/
    ├── contract/
    ├── integration/
    ├── e2e/
    └── fixtures/
```

上图是概念边界与推荐 ownership，不是要求一次性创建的文件清单。具体小文件、class 数量、测试工具、数据库表与 Schema 属于 Implementation Pending。

### Package Ownership

| Package | Responsibility | Explicitly does not own |
| --- | --- | --- |
| config | Settings、PathProvider、配置解析语义 | 业务装配、入口私有路径 |
| bootstrap | Composition Root、Trivae Application Factory、core resource lifecycle | Query 规则、协议展示、HTTP server listener |
| data | Canonical Model、Ingestion、Store、Indexing | Agent Loop、API route |
| retrieval | Structured / Lexical / Semantic / Context Expansion | CLI、HTTP、Final Evidence 判断 |
| capabilities | Capability Contract、Tool Registry、Agent-facing Tool | SDK-specific Runtime loop |
| query | Context、Router、Planner、Runtime Adapter、Evidence / Citation、Orchestrator | CLI / HTTP 协议 |
| conversation | Conversation / Assistant Message boundary | SDK 私有持久化状态 |
| observability | Normalized Event、Trace、Stream / Trace Projection | 重新定义业务结果 |
| evaluation | Case、Variant、Runner orchestration、Review / Comparison | 第二套 Runtime / Retrieval / Tool 主链路 |
| interfaces/cli | 参数解析、Application 调用、CLI presentation、HTTP server 启动编排 | Router、Tool、SDK 逻辑、core resource ownership |
| interfaces/api | HTTP ASGI / Server App Factory、dependencies、routes、协议 projection | 业务执行与错误语义、core application lifecycle |
| __main__.py | 转发到 CLI app | Bootstrap、连接、全局初始化 |

### Reason 与 Trade-off

单 distribution 降低当前空仓库的跨 package dependency、editable install、版本同步与循环依赖成本；内部 package ownership 保留未来拆分的边界。代价是第一版模块依赖必须靠约定、检查和 Contract Test 维护，而不是由多个 distribution 的 packaging boundary 强制隔离。

## 3. Decision 2：入口分层与 Application facade

### Application Boundary

```
CLI ─────────────┐
HTTP API ────────┼──> Application / Request Orchestrator
Evaluation ──────┘             │
                               │
                       Context Assembly
                               ↓
                             Router
                         ↙            ↘
                 standard_execution  planned_execution
                                         ↓
                                      Planner
                                         ↓
                                soft execution guidance
                         ↘            ↓            ↙
                          Agent Runtime Adapter
                                  ↕
                         Tool / Capability Layer
                                  ↓
                         Retrieval / Structured Result
                                  ↓
                         Evidence / Citation / Finalization
                                  ↓
                           Answer Artifact / Result
```

CLI 与 HTTP API 是薄 Interface Adapter，只负责协议解析、认证上下文传递、Application 调用和结果 / 事件 presentation。它们不拥有 Router、Planner、Runtime、Retrieval、Evidence 或 Trace 的业务语义。

Evaluation 是独立评测子系统，负责 Case、Variant、Runner、Judge、Review、Comparison 与 Regression 等评测语义；它进入生产 Query execution core 的 execution adapter 必须保持薄，不复制第二套 production execution semantics。

TrivaeApplication 是产品边界，概念 facade 包含：

```text
TrivaeApplication
├── query
├── ingestion
├── conversations
├── evaluation
├── traces
└── lifecycle
```

Conversation、Import、Trace 等产品路径均先进入对应 Application facade，再进入 application service 或其拥有的 Store；路由层不得直接读取 Store、Index 或 Provider。

### QueryOrchestrator 是唯一 Query Application Entry

正确入口为：

```
CLI / API / Evaluation
        ↓
    QueryRequest
        ↓
  QueryOrchestrator
        ↓
Context → Router → Planner? → Runtime → Evidence → Result
```

以下路径禁止作为共享核心：

```
CLI → AgentRuntime.run()
CLI → localhost HTTP → API → QueryOrchestrator
Evaluation → eval_router → eval_runtime → eval_retrieval
```

共享的是 Application Service 与内部 contract，不是 HTTP 协议。CLI、Evaluation 和本地开发不应因为复用业务逻辑而引入端口、HTTP 序列化或网络错误。

## 4. Decision 3：Composition Root 统一装配与生命周期

Composition Root 的职责由 bootstrap 持有的 Trivae Application Factory 承担，例如 create_application(settings)。它负责集中装配核心依赖、Application facade 与 core resource lifecycle。

interfaces/api 另有独立的 HTTP ASGI / Server App Factory，例如 create_http_app(application)，负责创建 ASGI app、注册 routes、协议 middleware 与 response projection。它不重新创建 Application、Store 或 Runtime。

CLI serve 通过 bootstrap 创建 Application，再启动 HTTP interface；CLI 不复制 API 组装逻辑。

系统必须存在一个明确的 Composition Root，负责集中装配：

```
Settings / PathProvider
        ↓
Data Directory / Lifecycle Context
        ↓
Canonical Store / SQLite Stores / Derived Indexes
        ↓
Retrieval Services
        ↓
Capabilities / Tool Registry
        ↓
Router / Planner
        ↓
OpenAI Agents Runtime Adapter
        ↓
Evidence / Citation / Finalization
        ↓
Trace Collector / Event Projection
        ↓
QueryOrchestrator
        ↓
TrivaeApplication
```

Application 对象概念上提供：

```
TrivaeApplication
├── query
├── ingestion
├── conversations
├── evaluation
├── traces
└── lifecycle
```

具体属性名称、依赖注入机制和 class 形态留给 Implementation。必须保持以下不变量：

- CLI、API、Evaluation 使用同一个 Application factory / composition path；
- Store、Index、Provider、Runtime、Trace Store、Conversation Store 等 core resource 的创建与关闭由 Application lifecycle 明确管理；
- HTTP server lifecycle 只管理 ASGI app、server、listener、socket 与连接，不把 Uvicorn 或 listener 归入 core Application；
- server 停止接收新请求并完成在途请求后，再调用 application.close 释放 core resource；
- __main__.py 只转发到 CLI，不执行 bootstrap、连接或模型初始化；
- API 使用 HTTP ASGI / Server App Factory 语义，不在 import 时创建全局 Store、Runtime 或 Provider；
- 入口和模块 import 不产生不可控的全局副作用。

如果三个入口分别实例化依赖，最终会出现：

```
CLI Runtime configuration
≠ API Runtime configuration
≠ Evaluation Runtime configuration
```

集中装配增加了一个 Composition Root 的维护责任，但将配置一致性、生命周期和 Trace correlation 的责任放在可定位的 owner 上。

## 5. Decision 4：CLI、API、Evaluation 共享 Application-level Query Contract

三类入口的协议 DTO 必须映射到同一 Application-level QueryRequest 语义：

```
QueryRequest
├── request_id
├── conversation_id?
├── chat_session_id
├── query
├── locale
├── data_access_scope
├── execution_overrides?
└── trace_profile?
```

以上是概念字段，不冻结最终类型、nullable 规则、序列化名称与 Schema。入口可以有协议层独有字段，但在进入 Application 前必须完成转换；Query 核心不能读取 Typer、FastAPI 或 Evaluation-specific DTO。

Protocol input 不等于 trusted Application context。data_access_scope、特权 execution_overrides 与 trace_profile 等字段如果进入 QueryRequest，表示已由认证、本地授权策略或 Evaluation harness 派生并校验的可信上下文，不表示普通客户端可以自由提交这些值。

普通 HTTP / CLI 调用者不能通过 wire 字段扩大 Data Access Scope、强制 privileged route、注入特权 execution override 或启用 debug trace profile。后续实现可以分别设计 wire schema 与内部 QueryRequest；本 ADR 不提前锁定认证框架或授权策略。

Evaluation 的 forced_route、Controlled Variant identity 与其他 execution override 必须显式声明、进入 Query Trace 与 Evaluation Result，并保持与 Production Query 相同的 Context、Router / Planner / Runtime / Tool / Retrieval / Evidence execution core。它们只改变被实验契约允许改变的条件，并可由 Stage 1.10 的 Case、Snapshot、Scope 和 paired comparison 重建。

Evaluation 不得复制 eval_router、eval_agent、eval_tools 或 eval_retrieval。这不是禁止 Evaluation 拥有 runner orchestration，而是禁止它拥有第二套 Query execution semantics。

## 6. Decision 5：Streaming、Trace、SDK Event 与 Error 共享同一语义边界

### Event Projection

```
OpenAI Agents SDK Event
        ↓
OpenAIAgentsRuntimeAdapter
        ↓
Trivae Runtime Event
        ↓
Normalized Query Event
      ↙                  ↘
Stream Projection       Trace Collector
   CLI / API             append-only Trace
```

SDK raw event 不得直接成为 CLI、HTTP API、UI 或正式 Trace 的公共 contract。Runtime Adapter 负责把 SDK event 转换为 Trivae-owned Runtime Event；Normalized Query Event 再同时服务 Stream Projection 与 Trace Collector。

### Request / Trace Correlation

入口从开始就必须保留 request_id、trace_id、event_id、operation_id、parent_operation_id 与 sequence。具体 envelope、字段类型与 ID 编码由 Stage 1.9 Implementation Pending 决定；Stage 1.11 只确认入口到 Application、Stream 与 Trace 的 correlation 必须贯通。

### Canonical Error Projection

Domain / Application Error 至少具有 canonical error_code、origin_stage、category、safe_message 与 trace correlation。CLI 与 HTTP 只做 projection，例如 CLI 展示 safe message，HTTP 映射 status 与 JSON error body；错误代码、来源阶段和 Failure Attribution 不属于 HTTP 或 CLI。错误不能被统一包装成通用字符串，也不能在入口静默吞掉。

## 7. Decision 6：HTTP API 与 CLI 的第一版边界

### CLI

第一版 CLI surface 控制在：

```
trivae query
trivae import
trivae serve
trivae eval
trivae trace
trivae config
```

trivae query 必须进入 QueryRequest → QueryOrchestrator，不能直接进入 AgentRuntime.run()。CLI 不暴露 Agent Tool Surface 的全部底层操作，不因为内部存在 lexical_search、semantic_search、execute_sql 就自动创建同名产品命令。

python -m trivae 是 CLI 的等价启动入口；__main__.py 只负责转发。

### HTTP API

第一版 API 从第一天保留版本边界：

```
/api/v1/status
/api/v1/query
/api/v1/conversations
/api/v1/conversations/{id}
/api/v1/imports
/api/v1/traces/{trace_id}
```

以上是资源边界，不冻结最终 REST naming、Schema、鉴权和 status mapping。HTTP Route 与 Server Lifecycle 分离；API application 使用 factory 语义。

### Streaming

第一版查询流是：

```
Client sends query
        ↓
Server executes one Query
        ↓
Server streams Normalized Event Projection
        ↓
Execution completes
```

因此优先使用 SSE-like 单向 server-to-client streaming，不在当前阶段引入 WebSocket 的双向 connection lifecycle。普通响应与流式响应必须来自同一 Application Result / Normalized Event 语义。

## 8. Decision 7：Config、Paths 与 Trivae Home 命名空间

Trivae Home 的概念边界为一个逻辑命名空间与 storage ownership，不是强制的物理目录映射：

```
Trivae Home
├── config
├── data
│   ├── database
│   └── indexes
├── conversations
├── traces
├── evaluations
└── logs
```

具体目录名称、文件格式、环境变量、迁移和 retention 仍 Pending。重要的是 PathProvider / Settings 只有一个 owner：

上图的 config、data、conversations、traces、evaluations 与 logs 是逻辑 namespace；它们不要求一一对应物理目录、文件或数据库表。

- CLI、API、Evaluation 不得各自使用用户 Home 下的固定目录表达式；
- Data、Trace、Evaluation Artifact 使用同一配置解析与授权语义；
- 启动、关闭、resource failure 与 Trace correlation 必须可观察；
- Graceful shutdown 是生命周期契约，不通过 silent cleanup 隐藏异常。

## 9. Decision 8：运行时调用流与源码依赖规则分离

### Runtime Call Flow

运行时调用流描述请求如何进入共享 execution core：

```text
CLI / HTTP / Evaluation execution adapter
  -> TrivaeApplication
  -> QueryOrchestrator
  -> Context / Router / Planner / Runtime
  -> Capability / Retrieval
  -> Data
```

这条箭头描述运行时调用顺序，不等价于 Python import 方向。Conversation、Import、Trace 等产品路径同样先进入 TrivaeApplication 的对应 facade，再进入 application service。

### Source Dependency Rule

源码依赖描述可导入关系：

```text
interfaces / evaluation adapters
  -> application / query contracts
  -> Trivae-owned business contracts

concrete infrastructure adapters
  -> Trivae-owned business contracts

bootstrap / composition root
  -> contracts + concrete implementations
```

规则如下：

- Trivae-owned business contracts 不导入 SQLite、FastAPI、Typer 或具体 provider SDK。
- concrete infrastructure adapters 可以实现或依赖 Trivae-owned business contracts。
- interfaces 依赖 Application facade，不直接读取 Store、Index 或 provider。
- bootstrap 是允许组装契约和具体实现的 Composition Root。
- 不新增 ports、adapters、domain、usecases 等层级；当前 package layout 不改造成多层 Clean Architecture。

必须禁止以下方向：

```text
Trivae-owned business contracts ✗ import SQLite / FastAPI / Typer / provider SDK
retrieval                    ✗ import CLI / FastAPI
runtime                      ✗ import Typer / FastAPI
router                       ✗ import CLI parser
capabilities                 ✗ expose OpenAI Agents SDK types
data                         ✗ import Agent Runtime
interfaces                   ✗ read Store / Index / provider directly
evaluation                   ✗ implement its own Retrieval / Tool / Runtime chain
CLI                          ✗ force local HTTP to reuse Application logic
```

Stage 1.7 已确认未来替换 SDK 主要替换 Runtime Adapter 与 Function Tool Adapter，而不是 Retrieval、SQLite、Context Expansion、Identity 等业务系统。Stage 1.11 将这个承诺落到 package ownership：公共业务契约属于 Trivae，SDK 只存在于 adapter / infrastructure 接触面。

## 10. Decision 9：Tool Surface、CLI Surface、HTTP API Surface 分离

三个 surface 服务不同消费者：

| Surface | 消费者 | Owner |
| --- | --- | --- |
| Agent Tool Surface | Agent Runtime | capabilities / Tool Contract |
| CLI Surface | 人类与本地脚本 | interfaces/cli |
| HTTP API Surface | 外部客户端 / UI | interfaces/api |

例如 Agent 可以使用 lexical_search、semantic_search、get_schema、execute_sql。这不代表必须提供 trivae lexical-search、trivae semantic-search、trivae execute-sql。

复用 Application Service，不等于复用每个协议 surface。新增公共 Tool、CLI 命令或 API endpoint 都需要自己的需求、契约、Trace / Error projection 和验证。

## 11. Decision 10：ChatLab 继承、适配与暂不继承

| ChatLab 设计 | Trivae v1 | Reason |
| --- | --- | --- |
| CLI 是薄入口 | **继承** | CLI 不拥有业务逻辑 |
| HTTP 与 Server Lifecycle / Routes 分离 | **继承** | HTTP framework 不污染核心 |
| Runtime / Manager 集中初始化 | **继承为 Composition Root** | 避免多入口配置漂移 |
| Config / Paths 集中管理 | **继承** | Local-first、Trace、Data 目录需要统一 owner |
| Streaming 是一等路径 | **继承** | Stage 1.7 / 1.9 已确认 normalized event boundary |
| CLI 与 HTTP 共享核心模块 | **继承** | 保持执行语义一致 |
| apps/cli + packages/* monorepo | **适配为单 distribution + 内部 packages** | v1 只有一个 Python Runtime |
| Commander / Fastify | **替换为 Python 生态实现选择** | 语言不同；具体框架版本仍 Pending |
| Pi Agent Core | **替换为 OpenAI Agents SDK adapter** | Stage 1.7 已确认 Runtime 选择 |
| Electron / CLI-Web / Browser Runtime | **暂不继承** | 当前没有对应产品需求 |
| Daemon / resident service | **暂不继承** | 当前没有常驻服务需求 |
| MCP server | **暂不继承** | 当前 Tool Layer 不要求对外 MCP |
| self-update | **暂不继承** | 属于发布产品问题，不是当前核心架构 |

Trivae 继承的是“入口薄、装配集中、核心复用、Runtime 与入口解耦”的已验证组织原则，不继承 ChatLab 未被当前约束要求的物理拆分、产品表面或经验参数。

## 12. Failure Cases 与 Validation Contract

### 重要 Failure Cases

- CLI、API、Evaluation 使用不同 Settings、Path、Store 或 Runtime 配置；
- CLI 直接调用 Agent Runtime，绕过 Router / Planner；
- Evaluation 复制一套 Agent、Retrieval 或 Tool 逻辑，导致 offline 结果与生产执行不一致；
- API 或 CLI 直接暴露 OpenAI Agents SDK Event / Error 类型；
- CLI 与 API 分别从 SDK stream 发明不同的 event semantics；
- 不同入口为同一失败生成不同 error code，或用通用字符串遮蔽 origin stage；
- trace_id 在入口丢失，Evaluation Result 无法关联 canonical Trace；
- import 时打开数据库、模型或 Trace Store，导致测试与 worker lifecycle 不可控；
- 每个入口自行拼接用户目录，造成 Data、Trace、Evaluation Artifact 漂移；
- 为了复用方便把 Agent Tool Surface 暴露为全部 CLI / HTTP Surface；
- 单 distribution 仍退化为 common / utils 大杂烩，无法定位模块 ownership。
- 普通 HTTP / CLI 客户端通过 wire 字段扩大 Data Access Scope、强制 privileged route 或启用 debug trace profile；
- bootstrap 的 Trivae Application Factory 与 interfaces/api 的 HTTP ASGI / Server App Factory 合并，导致 server transport 反向拥有 core resource；
- core Application 试图直接管理 Uvicorn、listener 或 socket，或 server 在 core resource 关闭前继续接收新请求；

### Validation Contract

实施阶段至少需要为下列契约补充 Contract / Integration Test；当前 ADR 不伪造测试结果：

1. CLI、API、Evaluation 对等价输入生成等价 QueryRequest 语义；
2. 三个入口使用同一 Composition Root，不出现私有 Router / Runtime / Retrieval 主链路；
3. query 不绕过 Router / Planner 直接进入 Agent Runtime；
4. Evaluation forced standard / forced planned 在相同 Case / Snapshot / Scope 下复用同一 execution core；
5. SDK Event 不穿透接口层，Normalized Event 同时支持 Stream Projection 与 Trace Collector；
6. request_id、trace_id、canonical error 与 origin stage 在不同入口可关联；
7. import 不产生基础设施全局副作用，Application lifecycle 能显式关闭资源；
8. 依赖检查阻止底层模块反向依赖接口框架；
9. /api/v1 的版本边界不会改变 Application-level Query semantics；
10. Tool Surface、CLI Surface 与 HTTP API Surface 可以独立演进而不复制业务主链路。
11. Protocol input 不会绕过认证 / 本地授权策略直接成为 trusted Application context；特权 override 与 trace profile 的来源可追踪。
12. Trivae Application Factory、HTTP ASGI / Server App Factory、core application lifecycle 与 HTTP server lifecycle 的 owner 可以分别验证。

## 13. Confirmed Decision Summary

1. Trivae v1 使用一个 Python distribution，内部按架构 ownership 采用 src/trivae package layout。
2. CLI 与 HTTP API 是薄 Interface Adapter；Evaluation 是独立评测子系统，但其进入共享 execution core 的 execution adapter 保持薄；Application / Query Orchestrator 是唯一 Query execution entry。
3. bootstrap 的 Trivae Application Factory 集中创建 Settings、Paths、Store、Index、Retrieval、Capability、Tool Registry、Router、Planner、Runtime Adapter、Evidence / Citation、Trace、Conversation resource 与 core Application lifecycle。
4. CLI、HTTP API、Evaluation 都映射到同一个 Application-level QueryRequest；协议输入先经过认证 / 本地授权策略或 Evaluation harness 派生 trusted context，Evaluation 再通过显式 Controlled Variant / execution override 复用生产 execution core。
5. trivae query 进入 QueryOrchestrator，不直接调用 Agent Runtime；CLI 不通过本地 HTTP 强制复用 API。
6. OpenAI Agents SDK Event 先经 Runtime Adapter 转换为 Trivae-owned Runtime Event，再进入 Normalized Query Event；Stream 与 Trace 从同一语义边界投影。
7. request_id、trace_id 与 canonical Error 从入口开始保留；CLI / HTTP 只做错误 projection。
8. Config、Paths、core Application lifecycle 集中管理；HTTP server lifecycle 由 interfaces/api 与 CLI serve 编排；不允许 import-time 全局资源副作用。
9. Runtime Call Flow 与 Source Dependency Rule 分开记录；源码契约不依赖具体 infrastructure，concrete adapter 可依赖 Trivae contract，bootstrap 可组装两者；不新增 ports、adapters、domain、usecases 层级。
10. Tool Surface、CLI Surface、HTTP API Surface 分离；不将 Agent 能力自动变成产品入口。
11. HTTP 第一版保留 /api/v1 版本边界，查询 Streaming 优先采用单向 SSE-like projection；WebSocket、UI、MCP、Daemon、self-update 暂不继承。
12. ChatLab 的物理 monorepo 结构适配为单 distribution，但薄入口、集中装配、共享核心、Runtime 解耦、core/server lifecycle 分离与 logical namespace ownership 原则继续继承。

## 14. Deferred

### Implementation Pending

- pyproject.toml 的 Python 版本、distribution metadata、console script 与依赖锁定；
- Python / JSON / Database Schema、真实 package 文件、class / interface signature、DI 方式；
- QueryRequest、QueryResult、Normalized Event、canonical Error 的最终字段类型、序列化与 migration；
- Typer / FastAPI / SSE library / OpenAI Agents SDK 的具体版本与 adapter 实现；
- Settings 文件格式、环境变量、PathProvider 目录名称、ID 编码与 HTTP status mapping；
- create_application、create_http_app、core/server lifecycle、Trace Store、Conversation Store、Evaluation runner、Review workflow 的具体实现；
- wire schema 到 trusted Application context 的认证、授权、override 与 trace profile 派生实现；
- API auth、permission、redaction、retention 与删除传播实现；
- CLI 输出格式、API wire schema、SSE event fields 与 UI 交互。

### Stage 1.10 Implementation / Real-run Calibration Pending

- Evaluation Case authoring、Dataset / Snapshot 构建、runner、Review、真实 stable baseline；
- 重复 Run 次数、统计方法、质量 / latency / token / Tool Call / cost threshold；
- Router / Planner、Runtime、Retrieval、Evidence / Citation 与 Application 生命周期的真实参数校准；
- 是否需要额外 worker、resident service、WebSocket、多 distribution 或部署拓扑；必须由真实 workload、Failure Case 或新产品需求触发。

## 15. Reopen Conditions

只有以下证据可以重新打开本 ADR 的 Confirmed 边界：

- 单 distribution 在真实依赖隔离、部署或运行时上产生可复现且不可接受的故障；
- CLI、API、Evaluation 无法在同一 execution core 上保持一致语义或可接受性能；
- Composition Root 无法提供必要的 lifecycle、Trace、privacy 或 Data Access Scope 隔离；
- 新产品需求明确需要 Desktop、Daemon、MCP、WebSocket、多 Runtime 或多 distribution；
- 真实 Evaluation 证明当前 Application Boundary 造成系统性质量 / diagnosability 退化。

“多 package 看起来更专业”“目录更漂亮”“框架通常这样做”或“可以先复制一套 Evaluation 逻辑”不构成 Reopen Reason。重新打开时必须记录新的 Failure Case、技术约束、Evaluation 结果或业务需求，并说明兼容与迁移方案。

## 16. M5a/M5b Implementation Status

M5a/M5b 已按本 ADR 的单 Composition Root / shared Query execution boundary 落地：`TrivaeApplication.query()` 仍只进入 `QueryOrchestrator`，由 Orchestrator 在同一 RuntimeResult 之后调用 `query/evidence.py` 的 Answer Finalizer；接口层没有自行组装 Evidence。M5b 再由 Application 从 Conversation Store 读取历史，并仅在 `QueryResult.is_successful` 且 Artifact 非空时调用 Store 的 atomic `commit_turn()`。

Conversation Store 的 create/read/commit/close lifecycle 由 Application factory 统一装配；Runtime、Router、Planner、Tool 与 Finalizer 不直接执行 SQL，也不拥有 Conversation transaction。Conversation Store 独立维护自己的 SQLite connection 与表，replay 只恢复持久化 Artifact，不重新调用 LLM、Retrieval 或 hydration；历史 Evidence 仍不属于后续 Run 的 fresh provenance。Trace backend、Evaluation adapter、HTTP/API wire contract 与 UI 仍待后续 implementation task。

## 17. Interactive CLI streaming implementation status（2026-08-23）

`TrivaeApplication.query(request, on_event=...)` 以 keyword-only optional handler 暴露同一 Query 主链路的实时投影；不传 handler 的 API、Evaluation 与测试调用保持完成后返回 `QueryResult` 的语义。Application 建立 `QueryStreamAdapter`，分别订阅 Runtime Event 与 TraceCollector 已归一化的 domain event；CLI 不直接调用 Runtime、Tool、Retrieval 或 SQLite Trace Store。

`interfaces/cli_renderer.py` 集中拥有普通终端展示：

- normal：真实 Thinking、Route、Plan、Tool 主要参数、Tool/ Retrieval 真实摘要、Answer token streaming、错误与 trace/log identity；
- verbose：选择可信 `trace_profile=debug`，额外显示 route diagnostics、plan details、bounded Tool arguments、coverage/partial/truncated/duration、usage 与 normalized source metadata；仍不 dump 聊天正文、secret 或 hidden reasoning；
- Renderer 只维护 presentation segment（thinking/answer/none），不维护或推断 Agent state。完成、failure、abort 与 Ctrl+C 都先关闭开放文本行，下一轮 prompt 不与前一轮粘连。

最终 `AnswerArtifact` 与 Conversation commit contract 不变：streaming 只改变传输与展示，不能逐 token 写 Conversation Store；若 finalization 或 commit 失败，已显示 preview 会以明确 terminal error 结束，不能被当作正式已提交答案。
