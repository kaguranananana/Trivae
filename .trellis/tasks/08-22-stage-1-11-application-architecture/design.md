# Technical Design: Stage 1.11 应用边界与工程结构

## 1. Design Objective

将 Stage 1.1–1.10 的内部架构决策映射到 Python 工程的 ownership、入口与生命周期边界。设计产物是架构文档，不是业务代码；最终权威记录为 `.trellis/spec/project/technical-decisions/stage-1-11-application-architecture.md`。

## 2. Design Boundary

### In Scope

- 单 Python distribution 与 `src/trivae` 的概念 package layout；
- `interfaces`、`evaluation`、`application / query`、domain 与 infrastructure 的责任方向；
- Composition Root、Application 对象与 graceful lifecycle 的概念职责；
- CLI、HTTP API、Evaluation 到同一 `QueryOrchestrator` 的执行路径；
- `QueryRequest`、Normalized Event Projection、canonical Error 与 request / trace correlation 的跨层 ownership；
- ChatLab 方案在 Trivae v1 中的继承、适配与暂不继承；
- Implementation Pending、Real-run Calibration Pending、Reopen Conditions 与可验证的架构契约。

### Out of Scope

- 业务类、Python / JSON / Database Schema、真实 CLI / API / Evaluation runner；
- Typer、FastAPI、OpenAI Agents SDK 或 DI library 的具体版本与最终配置；
- HTTP wire schema、SSE event field、ID 编码、数据库连接池、timeout 与目录最终名称；
- UI、MCP、Daemon、WebSocket、分布式服务和部署拓扑；
- 重新打开 Stage 1.1–1.10 的 Confirmed 决策。

## 3. Architecture and Data Flow

### 3.1 Application Boundary

```text
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
                                  │
               ┌──────────────────┴──────────────────┐
               ↓                                     ↓
       Stream Projection                       Trace Collector
          CLI / API                            Normalized Events
```

CLI、HTTP API 与 Evaluation 都是协议或调度适配器，不是 Query 主链路的 owner。`QueryOrchestrator` 是 Application-level 的唯一查询入口，负责组织整个 Query 生命周期；Agent Runtime 只负责进入 Agent Loop 后的执行。

### 3.2 Composition Root

```text
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
Agent Runtime Adapter
        ↓
Evidence / Citation / Finalization
        ↓
Trace Collector / Event Projection
        ↓
QueryOrchestrator
        ↓
TrivaeApplication
```

Composition Root 是唯一负责跨模块组装的地方。CLI、API 和 Evaluation 只请求同一个 Application factory / constructor，不自行创建 Router、Planner、Runtime 或 Store。Application 对象概念上暴露 `query`、`ingestion`、`evaluation`、`trace` 与 `lifecycle` 能力；具体属性名与注入方式留给实现。

所有需要打开的 Store、Index、Provider、Trace Store 与 Server resource 都由 Application lifecycle 管理。模块 import 不执行连接、模型初始化或其他不可控的全局副作用。

### 3.3 Query Contract Reuse

```text
CLI arguments ────────┐
HTTP JSON ────────────┼──> QueryRequest ──> QueryOrchestrator.execute
Evaluation Case ─────┘
```

`QueryRequest` 是 Application-level contract。它统一表达 query、conversation / session identity、locale、Data Access Scope、execution override 与 Trace profile 等语义。入口 DTO 可以包含协议层字段，但在调用 Application 前必须转换为该 contract；业务核心不读取 Typer、FastAPI 或 Evaluation-specific DTO。

Evaluation 的 `forced_route`、Variant identity 和其他 override 必须是显式实验条件，并进入 Trace / Result；它们不能通过另一个 `eval_*` 执行链路暗中改变生产逻辑。

### 3.4 Event, Trace and Error Projection

```text
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

上层只依赖 Trivae-owned event contract，不依赖 SDK 类型。CLI 负责将事件投影为文本 / 进度，HTTP API 负责将事件投影为版本化单向流；两者不能分别从 SDK stream 发明语义。

`request_id`、`trace_id` 从入口生成或接收并持续传递。Domain / Application Error 保留 canonical `error_code`、origin stage、category、safe message 与可诊断关联；HTTP status、CLI 文案等只是 projection。

## 4. Package Ownership

概念布局采用标准 `src` layout，并保持一个 Python distribution：

```text
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
│       ├── retrieval/
│       ├── capabilities/
│       ├── query/
│       ├── conversation/
│       ├── observability/
│       ├── evaluation/
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

第一版概念 ownership：

| Package | Ownership | 不负责 |
| --- | --- | --- |
| `config` | Settings、PathProvider、配置解析语义 | 业务装配、入口私有路径 |
| `bootstrap` | Composition Root、Application factory、resource lifecycle | Query 规则、协议展示 |
| `data` | Canonical Model、Ingestion、Store、Indexing | Agent Loop、API route |
| `retrieval` | Structured / Lexical / Semantic / Context Expansion | CLI、HTTP、Final Evidence 判定 |
| `capabilities` | Capability Contract、Tool Registry、Agent-facing Tools | SDK-specific Runtime loop |
| `query` | Context、Router、Planner、Runtime adapter、Evidence / Citation、Orchestrator | CLI / FastAPI protocol |
| `conversation` | Conversation / Assistant Message boundary | Agent SDK 私有持久化假设 |
| `observability` | Normalized Events、Trace、Stream / Trace Projections | 重新定义业务结果 |
| `evaluation` | Case、Variant、Runner orchestration、Review / Comparison contract | 第二套 Runtime / Retrieval / Tool 主链路 |
| `interfaces/cli` | 参数解析、调用 Application、结果展示 | Router、Tool、SDK 逻辑 |
| `interfaces/api` | App factory、dependencies、routes、协议投影 | 业务执行与错误语义 owner |
| `__main__.py` | 转发到 CLI app | Bootstrap、连接、全局初始化 |

具体是否拆成上述全部目录、每个目录中的文件数量与实现类名，属于 Implementation Pending；但新增代码必须保持同一 ownership 方向，若需偏离需先记录原因。

## 5. Dependency Direction

```text
interfaces/cli ───┐
interfaces/api ───┼──> Application / Query Orchestrator
evaluation ───────┘              │
                                 ▼
                         Router / Planner / Runtime
                                 │
                         Capabilities / Retrieval
                                 │
                                 ▼
                           Data / Infrastructure

All execution stages ──> Normalized Event Boundary ──> Observability
```

禁止的直接依赖包括：

- `retrieval` import CLI 或 HTTP framework；
- `runtime` import FastAPI / Typer；
- `router` import CLI parser；
- `capabilities` 将 OpenAI Agents SDK 类型作为公共 contract 向上传播；
- `data` import Agent Runtime；
- `evaluation` 复制生产 Retrieval、Tool 或 Runtime；
- CLI 通过本地 HTTP 强制调用 API 以获得共享逻辑。

共享的是 Application Service 与内部 contract，不是 HTTP 协议本身。

## 6. Interface Scope

第一版 CLI 概念入口为 `query`、`import`、`serve`、`eval`、`trace`、`config`。`query` 必须进入 `QueryRequest → QueryOrchestrator`，不能直接进入 `AgentRuntime.run()`；Evaluation 也必须进入相同 execution core。

HTTP 使用 `/api/v1` 作为第一版版本边界，第一批资源概念包括 status、query、conversations、imports 与 traces。普通查询返回 Application Result；流式查询返回同一执行产生的 Normalized Event Projection。第一版优先 SSE-like 单向 server-to-client streaming，不冻结具体 wire fields，也不引入 WebSocket。

Agent Tool Surface、CLI Surface 与 HTTP API Surface 三者独立治理。Agent 可以拥有 `lexical_search`、`semantic_search`、`get_schema`、`execute_sql` 等能力，不代表这些能力都要变成公共 CLI 命令或 HTTP endpoint。

## 7. ChatLab Adaptation

| ChatLab 方案 | Trivae v1 处理 | 原因 |
| --- | --- | --- |
| CLI 为薄入口 | 继承 | 避免入口拥有业务逻辑 |
| HTTP 与 lifecycle / routes 分离 | 继承 | 避免 HTTP framework 污染核心 |
| Runtime / manager 集中初始化 | 继承为 Composition Root | 避免 CLI、API、Evaluation 配置漂移 |
| Config / paths 集中管理 | 继承 | Local-first 与 Trace / Data 目录需要统一 owner |
| Streaming 是一等输出 | 继承 | Stage 1.7 / 1.9 已确认 normalized event boundary |
| `apps/cli + packages/*` monorepo | 适配为单 distribution + 内部 packages | v1 没有 Desktop / Browser / Node 多 runtime 压力 |
| Commander / Fastify / Pi Agent Core | 替换为 Python 生态的实现选择 | 语言与 Stage 1.7 SDK 约束不同；具体库版本仍 Pending |
| Electron、CLI-Web、Daemon、MCP、self-update | 暂不继承 | 当前没有对应产品需求或架构契约 |

适配的是物理承载方式，不改变 ChatLab 已被 Trivae 继承的“入口薄、装配集中、核心复用、Runtime 与入口解耦”原则。

## 8. Compatibility and Lifecycle Notes

- `python -m trivae` 只作为 CLI 转发入口；不得把 bootstrap、数据库连接或 Runtime 初始化塞进 `__main__.py`。
- API application 使用 factory 语义，避免 import 时创建全局 Store、Provider 或 Runtime。
- CLI、API 和 Evaluation 必须共享 Settings、PathProvider、Application factory 与 QueryRequest 转换语义。
- `request_id` / `trace_id`、canonical error、Normalized Event 与 QueryResult 是跨入口兼容边界；新增入口必须做 projection，而不是另建语义。
- `pyproject.toml` 的 distribution 名称、console script 的最终配置、Python 版本、框架和依赖锁定留给实施任务；本 ADR 只确认“一个 distribution + `src/trivae` + 可执行 `trivae` / `python -m trivae`”的方向。

## 9. Verification and Failure Cases

实施阶段至少应通过 Contract / Integration Test 验证以下行为：

1. CLI、API、Evaluation 对等价输入生成等价 `QueryRequest` 语义；
2. 三个入口使用同一 Composition Root，不出现私有 Router / Runtime / Retrieval 链路；
3. `query` 不绕过 Router / Planner 直接调用 Agent Runtime；
4. Evaluation forced standard / forced planned 能在同一 Case / Snapshot / Scope 下复用生产 execution core；
5. SDK Event 不穿透到接口层，Normalized Event 同时支持 Stream Projection 与 Trace Collector；
6. `request_id`、`trace_id` 和 canonical error 在 CLI / API / Evaluation 中保持可关联；
7. import 不产生基础设施全局副作用，Application lifecycle 能显式关闭资源；
8. 依赖检查能阻止底层模块反向 import 接口框架。

应重点保留的 Failure Case：入口配置漂移、Evaluation 复制执行链路、CLI 绕过 Router、API 暴露 SDK 类型、Trace / stream 语义分叉、越权 error projection、路径解析重复以及 import-time resource leak。发现真实 Failure 后按项目 Failure-Case 流程修复并增加 Regression。

## 10. Deferred and Reopen Conditions

### Implementation Pending

- Python / JSON / Database Schema、实际模块文件、Application class、DI 方式、`QueryRequest` 最终字段类型；
- Typer / FastAPI / SSE library / OpenAI Agents SDK 的版本与适配细节；
- Settings 文件格式、目录名称、ID 编码、HTTP status mapping、SSE wire schema；
- CLI output、API auth、Conversation store、Evaluation runner、Review workflow 与 Trace backend。

### Real-run Calibration Pending

- Application 启动耗时、资源生命周期 timeout、stream buffer、并发与 cost 参数；
- Evaluation runner 调度、重复 Run、Baseline、threshold、性能与质量校准；
- 是否需要额外的 worker / service、WebSocket 或多 distribution；必须由真实 workload、Failure Case 或产品需求触发。

### Reopen Conditions

只有以下证据可以重新打开 Stage 1.11 的 Confirmed 边界：单 distribution 在真实部署或依赖隔离上产生可复现且不可接受的故障；共享 Query execution core 无法同时满足 CLI、API、Evaluation 的语义或性能契约；Application / Composition Root 无法提供必要的 lifecycle / Trace / privacy 隔离；新产品需求明确需要 Desktop、Daemon、MCP、WebSocket 或多 runtime；或 Evaluation 证明当前边界造成系统性退化。仅凭“目录更漂亮”“多 package 更专业”不构成 Reopen Reason。
