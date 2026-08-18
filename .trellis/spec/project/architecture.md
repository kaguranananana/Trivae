# Architecture

> 状态：**Draft / In Progress**
>
> 本文件记录 Stage 1.1 已确认的整体架构骨架，不是完整且最终的 Architecture Specification。
> 未明确列出的实现细节继续标记为 `Pending architecture specification`，不得自行补全。

---

## Status

| 项 | 状态 |
|----|------|
| 当前阶段 | Stage 1.1：整体架构骨架 |
| 文档成熟度 | Draft / In Progress |
| 业务实现 | 禁止（本任务仅做文档映射） |
| 最终架构评审 | 等待 Stage 1.1-1.11 全部完成 |

## Goals

- 将高噪声群聊数据转化为可靠、可搜索的数据底座。
- 根据自然语言问题完成查询、调查与分析。
- 生成能够追溯到原始聊天消息的证据型回答。
- 将 Data Plane 与 Query Plane 解耦，避免 Agent 直接依赖原始数据格式或存储细节。
- 为后续 Trace、Evaluation 和 Failure Attribution 保留清晰的阶段边界。

## High-Level Architecture

Trivae 由两个一级平面组成：

```text
Trivae
|-- Data Plane
|   Raw Chat / Export
|       -> Ingestion
|       -> Normalizer
|       -> Canonical Message Store
|       -> Search Indexes
|
`-- Query Plane
    User Query + Query Context
        -> Router
        -> Planner (complex requests only)
        -> Agent Runtime
        -> Tool Layer
        -> Retrieval / Analysis
        -> Evidence
        -> Answer Generation
        -> Answer + Citation
```

Search index 的具体类型、数据模型和存储方式尚未确定；上图中的名称表示概念边界，不表示技术选型。

### Data Plane

#### Responsibility

回答“聊天数据如何变成可靠、可搜索的数据底座”：

```text
Raw QQ / Export Data
    -> Ingestion
    -> Normalizer
    -> Canonical Message Store
    -> Search Indexes
```

#### Boundary

- 负责接收、标准化、保存和建立索引的概念流程。
- 不包含 Agent Runtime、Router、Planner 或 Answer Generation。
- 不要求 Query Plane 了解 QQ 导出格式、NapCat 字段或底层存储实现。
- Query Plane 只能通过 Tool Layer 访问 Data Plane 能力。

#### Pending

Data Model、Canonical Message 字段、持久化方式、Database Schema、导入协议、幂等性、索引实现和错误处理策略均待后续阶段确定。

### Query Plane

#### Responsibility

回答“用户提出自然语言问题后，系统如何找到证据并形成回答”。Query Plane 负责查询路径、调查执行、工具使用、检索与证据组织的协作。

#### Conceptual Flow

```text
User Query + Query Context
    -> Router
       |-- direct / simple path       (exact behavior pending)
       |-- tool-assisted path         (exact behavior pending)
       `-- planned path
              -> Planner
              -> Agent Runtime
    -> Agent Runtime
    -> Tool Layer
    -> Retrieval / Analysis
    -> Evidence
    -> Answer Generation
    -> Evidence + Citation
```

`direct_response`、`tool_assisted`、`planned_execution` 是当前参考架构中的路径词汇；Trivae 是否采用这些名称、分类规则、置信度和边界条件，仍属于 Router 具体策略的 Pending 项。

## Module Boundaries

### Router

**Responsibility**：决定请求需要的执行复杂度和查询路径。

**Does**：

- 接收 User Query 与 Query Context。
- 将请求分为直接处理、工具辅助或需要计划的复杂执行路径（具体策略待定）。
- 为复杂请求选择 Planner 路径。

**Does not**：

- 不决定 Keyword / Semantic / Hybrid Retrieval。
- 不决定 SQL、Top-K、Rerank 或具体 Tool 参数。
- 不负责底层数据访问和证据选择。

结论：**Router 决定“走哪种执行路径”，Retrieval 决定“怎样找数据”。**

### Planner

**Responsibility**：将复杂请求拆分为调查目标，为 Agent 提供软指导。

**Does**：

- 仅在复杂请求路径中参与。
- 输出调查目标、阶段性问题或高层计划。
- 计划作为 Agent 的 soft guidance，而非强制执行图。

**Does not**：

- 不编排底层 Tool 调用流程。
- 不输出固定的 `vector_search`、`rerank`、SQL 等低层执行步骤。
- 不替代 Agent Runtime 的执行与状态管理。

Planner schema、步骤上限、suggested tools 校验和失败处理待后续确定。

### Agent Runtime

**Responsibility**：承载查询执行循环，并协调 Planner 指导与 Tool Layer。

- 通用 Agent Loop、Tool Execution、Streaming、Run Lifecycle 和基础 Tracing 优先复用成熟 Agent SDK。
- Trivae 保留薄适配层，负责 Trivae 领域契约与 SDK 之间的映射。
- Router、Planner、Retrieval、Evidence 等业务逻辑不下沉到 SDK，也不隐藏在 Runtime 适配层中。
- Python 侧当前以 OpenAI Agents SDK 作为映射方向；具体依赖版本、适配契约和生命周期边界在 Stage 1.7 确认。

### Tool Layer

**Responsibility**：提供 Agent 可调用的受控数据与分析能力，是 Query Plane 访问 Data Plane 的边界。

概念上可包含 Search、Analysis、Evidence 等能力类别，但当前不定义具体 Tool 清单。

- Agent 不直接读取原始文件、Canonical Store 或索引。
- Data Plane 能力通过明确的 Tool 接口暴露给 Agent。
- Tool 的签名、参数校验、权限、执行错误和结果契约待 Stage 1.4 确定。

### Retrieval

**Responsibility**：根据查询和约束从数据底座召回候选信息，并支持后续分析。

- Retrieval 是 Trivae 的业务核心之一。
- Retrieval Result 与 Evidence 分离：召回候选不等同于最终引用证据。
- Keyword、Semantic、Hybrid、时间/成员过滤、上下文扩展、Rerank 和召回策略均未定。

### Evidence

**Responsibility**：将检索和分析结果组织成可支撑回答结论的证据，并连接原始聊天消息与最终引用。

- Evidence 是 Trivae 的业务核心之一。
- Evidence 不等同于原始 Retrieval Result；需要独立表达选中、排除或不确定的证据语义（具体状态模型待定）。
- Evidence / Citation 数据模型、完整性状态、来源字段和引用格式待 Stage 1.8 确定。

### Answer Generation

**Responsibility**：基于分析结果与 Evidence 生成回答，并返回可追溯的 Evidence / Citation。

- 回答生成必须以 Evidence 为依据，而不是绕过证据直接读取底层数据。
- Prompt、模型、输出 schema、引用格式和失败处理不在 Stage 1.1 决定。

## Cross-Cutting Concerns

### Observability / Trace

Observability 与 Trace 横切 Query Plane，目标是支持 Failure Attribution。一次查询最终应能区分 Router、Planner、Agent、Tool、Retrieval、Evidence 和 Answer 等阶段的中间状态与结果。

当前只确认逻辑覆盖范围，不确认具体 Trace Schema、存储、采集方式或指标命名。

### Evaluation / Regression

Evaluation 与 Regression 横切 Data Plane 和 Query Plane：

- 用固定 Evaluation Set 验证真实问题和真实改动。
- 重要 Failure Case 应进入 Regression Test。
- 指标应服务于质量、可靠性、延迟、Token、成本或可维护性判断。

Evaluation Set、指标口径、评测执行方式和框架均待 Stage 1.10 确定。

## Confirmed Decisions

以下是 Stage 1.1 已确认的架构方向：

1. **Two-plane architecture**：系统一级划分为 Data Plane 与 Query Plane。
2. **Data / Agent decoupling**：Data Plane 不包含 Agent；Agent 只能通过 Tool Layer 访问数据能力。
3. **Query main chain**：Query Plane 的主链路为 `Router -> Planner (complex requests only) -> Agent Runtime -> Tools -> Retrieval / Analysis -> Evidence -> Answer`。
4. **Router boundary**：Router 管执行复杂度和路径，不管具体检索算法或底层查询参数。
5. **Thin Planner**：Planner 管复杂问题拆解，计划是 Agent 的 soft guidance，不接管底层 Tool 编排。
6. **SDK reuse with thin adapter**：Agent Runtime 复用成熟 SDK 的通用能力，Trivae 保留薄适配层。
7. **Trivae business core**：Retrieval、Evidence、Evaluation 是 Trivae 需要重点设计和验证的业务能力。
8. **Retrieval / Evidence separation**：Retrieval Result 与最终 Evidence 分离，不能把候选召回直接视为引用证据。
9. **Cross-cutting verification**：Trace / Observability 用于 Failure Attribution，Evaluation / Regression 用于验证真实改善。

这些决策只描述一级边界和方向，不等同于最终模块接口、数据模型或依赖锁定。

## Reference Designs, Not Final Decisions

- ChatLab 的 `direct_response / tool_assisted / planned_execution` 路径和 Planner 行为是参考设计；Trivae 的路由名称与策略仍待确认。
- ChatLab 的 Planner 步骤上限等实现细节不自动继承到 Trivae。
- OpenAI Agents SDK 是当前 Python Agent Runtime 的映射方向；具体版本、集成方式和适配契约仍需在 Stage 1.7 验证。

## Pending Decisions

以下事项仍为 **Pending architecture specification**，不得在本阶段自行补齐或实现：

- Data Model 与 Canonical Message 字段
- Ingestion architecture、输入格式、Normalizer、幂等性与失败处理
- Database / 持久化 / Snapshot / Schema / Migration 设计
- Retrieval architecture
- Keyword / Semantic / Hybrid Retrieval 选型
- 时间过滤、成员过滤、上下文扩展、Rerank 与召回策略
- Tool Layer 的具体 Tool、签名、参数校验、权限与结果契约
- Router 具体策略、分类规则、置信度、阈值与失败处理
- Planner Schema、步骤上限、校验和执行约束
- Agent Runtime 的具体 SDK 版本、Adapter 契约、Session、Streaming、Abort 与 Run Lifecycle 细节
- Evidence / Citation model、证据状态、来源字段与引用格式
- Trace Schema、事件模型、存储、指标与采集方式
- Evaluation Set、指标口径、Evaluation architecture 与 Regression 执行方式
- Context architecture 与上下文规模控制
- Answer Generation 的模型、Prompt、输出契约与失败处理
- CLI / API 边界
- Python package / module layout
- Retry / Fallback 策略
- 会明显改变系统复杂度的新依赖或基础设施

## Evolution Rule

- Stage 1.2-1.11 每次只更新对应的架构章节，不提前填充其他 Pending 项。
- 每个新决策应保留问题、证据、候选方案、决定、原因、trade-off 和验证方式；必要时同步到 [technical-decisions.md](./technical-decisions.md)。
- Stage 1.1-1.11 全部完成后，统一审查本文件，才可将状态从 Draft / In Progress 升级为最终 Architecture Specification。

## Architecture Problem Handling

如果后续发现已确认架构存在重大问题：

1. 记录 `Problem / Evidence / Impact / Possible Options`。
2. 停止对应架构改动，不用兼容分支或临时实现掩盖问题。
3. 等待新的设计决策，并在 [problem-records.md](./problem-records.md) 或对应 task 中沉淀结果。
