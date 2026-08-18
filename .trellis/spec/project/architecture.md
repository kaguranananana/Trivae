# Architecture

> 状态：**Draft / In Progress**
>
> 本文件记录已完成的 Stage 1.1 整体架构骨架与 Stage 1.2 Data Model + Ingestion 确认内容，不是完整且最终的 Architecture Specification。
> 当前状态为：Stage 1.1 completed；Stage 1.2 Data Model + Ingestion completed；Stage 1.3 Retrieval Architecture pending / next。
> 未明确列出的实现细节继续标记为 `Pending architecture specification`，不得自行补全。

---

## Status

| 项      | 状态                                                         |
| ------ | ---------------------------------------------------------- |
| 当前阶段   | Stage 1.1 completed；Stage 1.2 Data Model + Ingestion completed；Stage 1.3 Retrieval Architecture pending / next |
| 文档成熟度  | Draft / In Progress                                        |
| 业务实现   | 当前无业务代码；后续按已确认架构与 Trellis task 实施                          |
| 最终架构评审 | 等待 Stage 1.1-1.11 全部完成                                     |

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

Canonical Data Model 与 Ingestion 概念管线已在 Stage 1.2 确认（见 [Stage 1.2: Data Model + Ingestion](#stage-12-data-model--ingestion)），但持久化方式、Database Schema、字段类型与具体索引、Vector Store、Chunking、Embedding 模型与 Indexing Pipeline 的具体执行方式仍待后续阶段确定。

### Query Plane

#### Responsibility

回答“用户提出自然语言问题后，系统如何找到证据并形成回答”。Query Plane 负责查询路径、调查执行、工具使用、检索与证据组织的协作。

#### Conceptual Flow

```text
User Query + Query Context
    -> Router
    -> [Planner] (complex requests only; soft guidance)
    -> Agent Runtime
       <-> Tool Layer
           -> Retrieval / Analysis
           -> Evidence
           -> Answer Generation
           -> Evidence + Citation
```

Router 的具体路径名称、分类规则、置信度和边界条件仍属于 Pending 项。`direct_response`、`tool_assisted`、`planned_execution` 仅作为 ChatLab 的参考词汇，不表示 Trivae 已确定三个独立执行流水线或固定的绕行关系。

## Stage 1.2: Data Model + Ingestion

> 本节为 Stage 1.2 已确认内容：只定义逻辑数据模型与概念管线边界，不包含数据库表设计、字段类型或任何技术选型。

### Canonical Data Model

所有外部聊天来源都先经过 Adapter / Parser，统一转换为 Trivae 的 Canonical Model；后续 Importer、Storage、Retrieval 不感知具体源格式（NapCat、QQ Export 或未来其他来源）。

当前确认的逻辑实体：

- `Source`
- `ChatSession`
- `UserIdentity`
- `Membership`
- `Message`
- `ImportBatch`

> 注意：这些是**逻辑数据模型**，不等同于最终数据库表设计；表数量、字段与索引待 Storage Architecture 阶段决定。

### Entity Responsibilities

#### ChatSession

表示一个逻辑聊天空间。无论数据从哪个源、哪个批次进入，同一个群只对应一个 ChatSession。

稳定身份优先使用：

```text
platform + external_chat_id
```

群名等可变字段不能作为主要身份判断依据：名称会变化，平台 ID 才是稳定身份。仅使用群名匹配会导致"同一个群被重复创建"这一类问题。

#### UserIdentity

表示跨聊天空间稳定的平台用户身份（支持后续跨群人物分析）。

优先使用：

```text
platform + platform_user_id
```

#### Membership

表示 UserIdentity 在某个 ChatSession 中的局部身份，例如群昵称、角色、alias 等。

平台用户身份（UserIdentity）与群内显示身份（Membership）必须分离：同一个人在群 A、群 B、群 C 可能使用不同昵称。

#### Message

逻辑层至少表达：

```text
internal id
session
author
source / platform message id
timestamp
message type
normalized content
reply relationship
```

必须明确区分两个 ID：

```text
Trivae Internal Message ID（Trivae 内部 ID）
Platform / Source Message ID（平台原始 ID，如 QQ message_id）
```

Canonicalization 必须保持查询、证据追溯和未来重新处理所需的信息，不应因为 normalization 丢失关键原始语义（如 URL、代码、@mention、图片 / 文件、reply / forward、富文本 message segments）。具体 structured content / raw payload / source locator 表示在后续 Data Schema 阶段确定，当前 Pending。

Canonical timestamp 必须能够表达一个确定的时间点，且不因 Source 的 timezone、timestamp precision 或转换规则导致跨 Source 时间语义不一致。具体数据库类型与存储格式（UTC datetime / Unix 毫秒 / TIMESTAMPTZ 等）保持 Pending。

后续 Evidence / Citation 应能够通过 Message 追溯到原始聊天记录：

```text
Evidence
  → Message (internal id)
  → source / platform message id
  → 原始聊天
```

因此 Message Identity 从项目第一天起就必须认真设计，不能在 Evidence / Citation 阶段再补。

#### Source

记录聊天数据的来源与 provenance，例如：

- NapCat
- QQ Export
- 其他未来 Adapter

Source 主要服务于数据来源追踪、问题定位和可观测性。正常 Retrieval 不需要关心它；但当某批数据出现问题（例如时间戳错误）时，通过 Source 可以定位到应排查的 Parser / Adapter 层。

#### ImportBatch

记录一次 ingestion 行为，逻辑层至少考虑：

```text
source
session
start / finish
received count
inserted count
duplicate count
error count
status
```

用于观测一次数据导入到底发生了什么，符合 Stage 0 的 Observable / Failure Attribution 原则（例如收到 1000 条、插入 823、重复 175、错误 2）。

### Unified Ingestion Pipeline

```text
Raw Source
→ Adapter / Parser
→ Normalizer
→ Canonical Model
→ Validator
→ Deduplicator
→ Canonical Store
→ Indexing Pipeline
```

职责边界：

| 层           | 职责                     |
| ----------- | ---------------------- |
| Parser      | 理解外部源格式（字段含义、原始结构）     |
| Normalizer  | 转换成 Trivae Canonical Model |
| Validator   | 验证规范化数据是否合法             |
| Deduplicator | 判断数据是否已经存在              |
| Store       | 保存 canonical data        |
| Indexing    | 构建可重建的搜索派生数据            |

Parser 负责"读懂源格式"（例如 `sender.uin` → `senderPlatformId`），Normalizer 之后的 Importer 不应再出现 `if qq_exporter:` 之类的源格式分支。

### Shared Importer

所有数据源共享统一 Importer。禁止每个 Adapter / Parser 各自实现独立的：

- 去重逻辑
- 数据库写入逻辑
- 成员更新逻辑
- 索引写入逻辑

数据源差异应在 Adapter / Parser 层被消化；新增**能够映射到现有 Canonical Model**的数据源不应要求下游增加 source-specific branches。

### Identity & Deduplication

#### Message Identity

Deduplication 优先级：

- Priority 1：稳定的 platform / source message id（如 `platform + session + source_message_id`）
- Priority 2：Canonical Message Fingerprint
- 否则：视为新消息

Stable Message ID 用于识别**同一逻辑消息**；当相同 identity 对应的 canonical payload 发生变化（编辑、撤回 / 状态变化、Source 数据纠正、Parser 版本变化、数据冲突）时，其 update / mutation / conflict resolution semantics 当前保持 Pending，不应直接等同于 duplicate skip。

Fingerprint 不能只使用 content hash，应基于 canonicalized stable attributes 构造；session、sender、timestamp、message type、normalized content、reply relationship（如适用）是**候选组成字段**：

```text
session
sender
timestamp
message type
normalized content
reply relationship（如适用）
```

具体字段组合、时间精度、canonicalization 与 hash algorithm 保持 Pending，并通过真实重复数据验证（例如"哈哈""好的"等高频重复文本不得误去重）。

#### Chat Identity

稳定平台 ID 优先于群名、标题等可变字段：

```text
platform + external_chat_id
```

#### User Identity

稳定平台用户 ID 优先于昵称：

```text
platform + platform_user_id
```

### Source of Truth

Canonical Message Store 是聊天数据的 Source of Truth。

以下内容属于 **Derived Data**：

```text
Keyword Index
Embedding
Vector Index
Chunk
Topic / Summary Index
其他未来搜索索引
```

Derived Data 必须可以基于 Canonical Store 重建（例如更换 Embedding 模型时只需重建派生数据，不需要重新导入原始聊天数据）。不要让搜索索引成为原始事实来源。

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

概念边界保持为：

```text
Retrieval Query
    -> Retrieval Candidates / Results
    -> Evidence Selection / Organization
    -> Final Evidence
    -> Answer
```

### Evidence

**Responsibility**：将检索和分析结果组织成可支撑回答结论的证据，并连接原始聊天消息与最终引用。

- Evidence 是 Trivae 的业务核心之一。
- Evidence 不等同于原始 Retrieval Result；需要独立表达证据来源、选择结果和完整性等语义（具体状态模型待定）。
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

以下是已完成的 Stage 1.1 所确认的架构方向：

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

### Stage 1.2：Data Model + Ingestion

1. **Canonical Model 隔离**：所有数据源先经 Adapter / Parser 统一转换为 Canonical Model，Importer / Storage / Retrieval 不感知具体源格式。
2. **Stable Platform Identity 优先**：ChatSession 用 `platform + external_chat_id`，UserIdentity 用 `platform + platform_user_id`；群名、昵称等可变字段不作为身份判断依据。
3. **Platform Identity 与 Session Membership 分离**：UserIdentity（跨群稳定身份）与 Membership（群内局部身份）是两个概念。
4. **Shared Importer**：所有数据源共用同一套 Importer；去重、写入、成员更新、索引写入逻辑不按数据源重复实现。
5. **Stable Message ID 优先、Fingerprint fallback**：去重先按稳定 platform/source message id，缺失时用结合 session / sender / timestamp / type / content / reply 的 fingerprint，不能只做 content hash。
6. **Canonical Store 为 Source of Truth**：搜索索引是 Derived Data，必须可基于 Canonical Store 重建。
7. **Ingestion Observability**：ImportBatch 记录一次导入的 received / inserted / duplicate / error 与状态。

这些决策只定义逻辑数据模型与概念边界；Database Schema、技术选型与实现细节仍待后续阶段确认。

## Reference Designs, Not Final Decisions

- ChatLab 的 `direct_response / tool_assisted / planned_execution` 路径和 Planner 行为是参考设计；Trivae 的路由名称与策略仍待确认。
- ChatLab 的 Planner 步骤上限等实现细节不自动继承到 Trivae。
- OpenAI Agents SDK 是当前 Python Agent Runtime 的映射方向；具体版本、集成方式和适配契约仍需在 Stage 1.7 验证。

## Pending Decisions

以下事项仍为 **Pending architecture specification**，不得在本阶段自行补齐或实现：

- 最终 Database Schema、表数量、字段类型与具体索引，SQLite / PostgreSQL 具体实现
- Vector Store 实现、Chunking 策略、Embedding 模型、Indexing Pipeline 具体执行方式
- Ingestion 具体实现细节：Deduplicator 的 fingerprint 算法、失败处理与幂等执行方式
- ChatSession / UserIdentity 缺少 authoritative stable ID 时的 fallback identity / matching strategy
- 相同 stable message identity 对应 canonical payload 变化时的 update / mutation / conflict resolution semantics
- Canonical Message Fingerprint 的具体字段组合、时间精度、canonicalization 与 hash algorithm
- raw payload / source locator / structured content 的具体表示
- Canonical timestamp 的 timezone / precision / 存储类型与转换实现
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
