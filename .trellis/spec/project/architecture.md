# Architecture

> 状态：**Draft / In Progress**
>
> 本文件记录已完成的 Stage 1.1 整体架构骨架、Stage 1.2 Data Model + Ingestion、Stage 1.3 Retrieval Architecture、Stage 1.4 Tool / Capability Layer、Stage 1.5 Router、Stage 1.6 Planner、Stage 1.7 Agent Runtime、Stage 1.8 Evidence / Citation、Stage 1.9 Trace / Observability、Stage 1.10 Evaluation 与 Stage 1.11 Application Boundary 架构确认内容，不是完整且最终的 Architecture Specification。
> 当前状态为：Stage 1.1–1.11 completed；M1 Data Plane ingestion vertical slice 已实现并完成真实数据校准；Stage 1.10 Evaluation / Real-run Calibration 与 Stage 1.11 Product Interaction 仍 Pending。
> 未明确列出的实现细节继续标记为 `Pending architecture specification`，不得自行补全。

---

## Status

| 项      | 状态                                                                                                                                                                                                             |
| ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 当前阶段   | Stage 1.1–1.11 completed；M1 ingestion 已实现；下一阶段为 Retrieval、Stage 1.10 Evaluation / Real-run Calibration 与 Stage 1.11 Product Interaction |
| 文档成熟度  | Draft / In Progress                                                                                                                                                                                            |
| 业务实现   | M1 `src/trivae` ingestion、SQLite Canonical Store、Application facade 与 thin CLI 已实现；Query Plane 与产品交互按后续 Trellis task 实施 |
| 最终架构评审 | 等待 Stage 1.1-1.11 全部完成                                                                                                                                                                                         |

## Goals

- 将高噪声群聊数据转化为可靠、可搜索的数据底座。
- 根据自然语言问题完成查询、调查与分析。
- 生成能够追溯到原始聊天消息的证据型回答。
- 将 Data Plane 与 Query Plane 解耦：Query Plane 不绕过 Tool Layer 访问 Data Plane，也不依赖 Source-specific 原始格式。第一版 Structured Retrieval 是明确例外——`get_schema / execute_sql` 在 Tool Contract 内有意暴露 SQLite Physical Query Schema。
- 为后续 Trace、Evaluation 和 Failure Attribution 保留清晰的阶段边界。

## Architecture Governance

### Architecture Principle: ChatLab as Reference Implementation

ChatLab 是 Trivae 的主要 reference implementation（参考实现）。本原则适用于整个项目、所有架构层级和后续各 Stage，不只适用于 Tool / Capability Layer。对于 ChatLab 已有、经过实际运行验证且适用于 Trivae 的设计，默认继承原方案，而不是重新设计。

这里的“默认继承”是架构治理规则，不是对 ChatLab 的逐字复制，也不意味着自动继承未经验证的参数、实现细节或与 Trivae 约束无关的行为。首先应判断 ChatLab 设计是否真的适用于当前问题；若适用，重新设计必须有证据，而不是从偏好出发。

任何偏离 ChatLab 基线的架构变化，都必须在决策记录中说明：

1. ChatLab 方案的具体范围，以及它为什么不适用于 Trivae；
2. 触发偏离的具体 Failure Case、技术约束或 Evaluation 结果（必要时包括新的业务需求）；
3. 新方案相对原方案带来的收益；
4. 新增的复杂度、维护成本和风险；
5. 验证新方案有效性的 Test / Evaluation 方法、指标和退出条件。

“更简单”“更优雅”“感觉可以重新抽象”“LLM 能力更强”“可以少一个 Tool”等主观判断，不足以推翻已有设计。

该原则不认为 ChatLab 永远正确，也不禁止基于证据的架构变化。当 ChatLab 方案与 Trivae 的真实 Failure Case、技术约束、Evaluation 结果或业务需求冲突时，可以偏离或重新打开已有决策；但变化必须由可观察、可复现、可验证的证据驱动，而不是由个人偏好驱动。

架构决策分为三种状态：

- **Confirmed**：已经完成决策，默认冻结；解释性讨论不直接重新设计。
- **Pending**：尚未决定，可以继续比较方案。
- **Experimental**：明确偏离已有方案，必须通过实验或 Evaluation 验证。

重新打开 Confirmed 决策必须记录 Reopen Reason，并由新 Failure Case、新技术约束、新 Evaluation 结果或新业务需求触发。仅凭“感觉更简单”“可以少一个 Tool”“LLM 能力更强”“可以封装”或“代码更优雅”不足以改变确认设计。

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
    User Query + Runtime Context
        -> Router
           ├── standard_execution ──────────────┐
           └── planned_execution                 │
                  -> Planner -> validate / sanitize -> soft guidance ──┘
                                                  ▼
                                           Agent Runtime
                                               <-> Tool Layer
                                                   -> Retrieval / Structured Result
                                                   -> Evidence Selection / Organization
                                                   -> Final Evidence
                                                   -> Citation-bound Answer
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
- Query Plane 不依赖 QQ 导出格式、NapCat 字段等 Source-specific 原始实现。
- Query Plane 只能通过 Tool Layer 访问 Data Plane 能力；第一版 Structured Retrieval 通过 `get_schema / execute_sql` 有意暴露 SQLite Physical Query Schema，Agent 对数据库的依赖仍被限制在 Tool Contract 与 Data Access Scope 内。

#### Pending

Canonical Data Model 与 Ingestion 概念管线已在 Stage 1.2 确认（见 [Stage 1.2: Data Model + Ingestion](#stage-12-data-model--ingestion)），Retrieval 架构已在 Stage 1.3 确认（见 [Stage 1.3: Retrieval Architecture](#stage-13-retrieval-architecture)，其中 Semantic 索引单位为 Conversation Chunk，且 Semantic / Lexical Index 均属 Derived Data）。Stage 1.4 已确认第一版 structured / canonical persistent store 采用 SQLite；M1 已按单独 backend database contract 落地 ingestion 所需 physical schema、transaction 和幂等 provenance。仍待后续阶段确定的是 Retrieval/Vector Storage、Chunk 参数、Embedding 模型与 Indexing Pipeline，以及跨环境 migration/deployment 策略。

### Query Plane

#### Responsibility

回答“用户提出自然语言问题后，系统如何找到证据并形成回答”。Query Plane 负责查询路径、调查执行、工具使用、检索与证据组织的协作。

#### Conceptual Flow

```text
User Query + Runtime-injected Context
    -> Router
       ├── standard_execution ──────────────┐
       └── planned_execution                │
              -> Planner                    │
              -> validate / sanitize       │
              -> soft execution guidance ──┘
                                             ▼
                                      Agent Runtime
                                          <-> Tool Layer
                                              -> Retrieval / Structured Result
                                              -> Evidence Selection / Organization
                                              -> Final Evidence
                                              -> Citation-bound Answer
```

Stage 1.5 已确认 Router 的两种 Route 为 `standard_execution` 与 `planned_execution`。两种 Route 最终都进入同一个 Agent Runtime；只有 `planned_execution` 在进入 Agent Runtime 前额外经过 Planner，且 Planner 输出的是 soft execution guidance，不是另一套 Agent Runtime 或强制 Workflow。

`direct_response`、`tool_assisted`、`planned_execution` 是 ChatLab 的参考 taxonomy，不表示 Trivae 当前保留三个 Route。

### Application Boundary

Stage 1.11 将外部入口划分为两类：CLI 与 HTTP API 是薄 Interface Adapter；Evaluation 是拥有 Case / Variant / Runner / Review / Regression 语义的独立评测子系统。三者都通过统一 Composition Root 进入同一个 Application / Query execution core：

```text
CLI ─────────────┐
HTTP API ────────┼──> Application / QueryOrchestrator
Evaluation ──────┘             │
                               ↓
                  Context → Router → Planner? → Agent Runtime
                               ↓
                    Tool / Capability → Retrieval
                               ↓
                    Evidence / Citation → Answer Artifact
                               │
                    ┌──────────┴──────────┐
                    ↓                     ↓
             Stream Projection       Trace Collector
                 CLI / API            Normalized Events
```

CLI 与 HTTP API 不拥有 Router、Planner、Runtime、Retrieval、Evidence 或 Trace 的业务语义；Evaluation 只要求其进入生产 execution core 的 execution adapter 保持薄，不复制第二套 execution semantics。共享的是 Application Service、QueryRequest 与 Normalized Event Boundary，不是让 CLI 通过本地 HTTP 调用 API。

TrivaeApplication facade 包含 query、ingestion、conversations、evaluation、traces 与 lifecycle；Conversation、Import、Trace 等产品路径均通过对应 Application service 进入，不直接读取 Store。

bootstrap 持有 Trivae Application Factory；interfaces/api 持有 HTTP ASGI / Server App Factory。core Application lifecycle 管理核心 Store、Index、Provider、Runtime 与 Trace / Conversation resource，HTTP server lifecycle 管理 ASGI、listener、socket 与连接；server 完成在途请求后再调用 application.close。

Protocol input 不等于 trusted Application context。data_access_scope、特权 execution_overrides 与 trace_profile 必须由认证、本地授权策略或 Evaluation harness 派生，普通客户端不能通过 wire 字段自行扩权或启用特权模式。

Composition Root 集中创建 Settings / Paths、Store、Index、Retrieval、Capability、Tool Registry、Router、Planner、Runtime Adapter、Evidence / Citation、Trace Collector 与 QueryOrchestrator，并把它们交给可管理生命周期的 Application 对象。具体 Python class、依赖注入方式与 Schema 属于 Implementation Pending。

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

M1 落地校准：`seq` 是可缺省的排序提示，不是 Canonical Message 的必需事实；缺失时由 `timestamp` 与 `internal_message_id` 提供确定性排序，非空非法值仍按记录错误处理。M1 对 `canonical_projection()` 的字段保持最小集合：真实 14 文件的 duplicate/conflict 样本尚未证明 structured content 存在 false equal，因此不因表示层差异扩大 projection；未来若出现 mention、reply 或附件 identity 的真实 false equal，再由 Failure Case 驱动最小扩展。

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

## Stage 1.3: Retrieval Architecture

> 本节为 Stage 1.3 已确认内容。Retrieval 连接 Data Plane 与 Query Plane：根据当前任务，从大量高噪声聊天数据中找到**足够相关、足够完整、能够继续追溯**的候选信息。本节只定义 Retrieval 内部能力；Agent-facing Tool 暴露已由 Stage 1.4 Tool / Capability Layer 确认。

### 职责定义

Retrieval 的核心职责：

> **根据当前任务，从大量高噪声聊天数据中找到足够相关、足够完整、能够继续追溯的候选信息。**

- Retrieval 输出的是 Candidate Data（候选集合），**不是最终 Evidence**；候选仍需经过 Evidence Selection / Organization（Stage 1.8）才能成为引用证据。
- Retrieval 上承 Query Plane（Agent 发起检索请求），下接 Data Plane（Canonical Message Store + Derived Indexes）。

### 整体结构：Retrieval Composition + Retrieval Primitives + Post-Retrieval Operator

Trivae 的 Retrieval 由一层 **Retrieval Composition**、三个 **Retrieval Primitives**（Structured / Lexical / Semantic）与一个 **Post-Retrieval Operator**（Context Expansion）组成，分为两类能力：

```text
                 Retrieval Request
                        │
                        ▼
              Retrieval Composition
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
     Structured      Lexical       Semantic
     Retrieval       Retrieval      Retrieval
      (Primitive)    (Primitive)    (Primitive)
          │             │             │
          └─────────────┼─────────────┘
                        ▼
                 Candidate Set
                        │
                        ▼
      Post-Retrieval Operator
            Context Expansion
                        │
                        ▼
               Retrieval Result
```

对应的能力分层：

```text
Retrieval
├── Retrieval Composition        选择并组合原语
├── Retrieval Primitives         召回候选（find candidates）
│   ├── Structured
│   ├── Lexical
│   └── Semantic
└── Post-Retrieval Operator      恢复上下文（recover surrounding context）
    └── Context Expansion
```

**Context Expansion 与前三个 Primitives 不在同一层**：前三个负责"找出候选"，Context Expansion 负责"拿已有命中，恢复其所在上下文"。这个区别对 Stage 1.4 Tool Layer 有直接影响——`search something` 与 `expand this known hit` 天然属于两类 capability。这里指**内部 Capability 边界**，不意味着必须分别暴露为两个 Agent-facing Tool；Stage 1.4 已确认 message search 自动组合 bounded expand，同时保留独立 `get_message_context(message_id)`。

#### Retrieval Composition

- 位于 Retrieval Primitives 之上，根据当前任务选择并组合底层原语，输出候选集合；可选地在候选集上应用 Post-Retrieval Operator。
- **Hybrid 属于组合策略，不单独成为一种底层搜索引擎**：不会演化出一个"什么问题都往里面塞"的 `hybrid_search()`。
- 具体组合规则（merge / dedup / candidate selection 的实现方式）与 Fusion 权重保持 Pending Evaluation，由 Trivae 自己的 Evaluation Set 决定。

#### 三个 Retrieval Primitives

| Primitive | 解决的问题 | 触发场景示例 |
| --- | --- | --- |
| Structured Retrieval | 目标集合已由结构化条件确定时的确定性计算 | 谁发言最多；8 月有多少条消息；每月讨论量变化 |
| Lexical Retrieval | 已经大概知道自己在找什么字面内容 | 有没有人提过 "LangGraph"；谁讨论过 DeepSeek V4；8 月 15 日有没有说过 "MCP" |
| Semantic Retrieval | 用户表达的是一个意思，聊天记录使用完全不同的措辞 | 大家对重型 Agent 框架有什么意见 |

### 通用原则：集合确定后的确定性查询优先

> **当目标数据集合可以由结构化条件确定时，优先使用 Structured Retrieval；当集合本身需要语义判断时，先通过 Lexical / Semantic Retrieval 确定候选集合，再进行确定性统计或聚合。**

把"哪些消息属于某类讨论"这类需要语义判定的集合问题强行 Embedding → vector search → LLM 猜结论，可靠性差、成本高、无法追溯。Structured Retrieval 的前提是目标集合已由结构化条件确定；对集合的确定性聚合（count / group by 等）直接由 Canonical Store 执行；**LLM 负责解释结果，不负责数数**。

### Structured Retrieval

职责：在**目标数据集合已由结构化条件确定**的前提下，直接对 Canonical Store 执行 filter / aggregate / 确定性查询。Stage 1.4 已确认第一版由 `get_schema` 暴露 Physical SQLite Schema，并由 `execute_sql` 执行 bounded read-only SQL；最终表结构仍由后续 Data Schema 设计决定。Structured Retrieval 解决的是"集合确定之后的确定性计算"，**不负责"哪些消息属于某类讨论"的语义判定**。

- 纯结构化（集合可直接由条件确定）：`哪个成员发言最多？` `8 月有多少条消息？` `A 和 B 回复彼此多少次？` `过去三个月活跃成员数量怎么变化？` `每个月讨论量如何变化？`
- 需要先定义集合再聚合：`过去半年有多少次关于 AI Agent 的有效技术讨论？` 应先由 Lexical / Semantic Retrieval 确定"属于 AI Agent 讨论"的候选集合，再对集合做确定性聚合。
- Failure Case：把"集合本身需要语义判定"的问题交给 Embedding + LLM 看几十条消息后猜一个统计结论，无法保证准确，也无法追溯计算过程。

### Lexical Retrieval

职责：目标词明确时的关键词检索。目标词明确 → 关键词检索精确、便宜、可解释，命中原因非常清楚（`match = "LangGraph"`）。

- 触发场景：`有没有人提过 "LangGraph"？` `找一下 "OpenAI Agents SDK"。` `8 月 15 日有没有说过 "MCP"？`
- 局限（不能只靠 Keyword Search 的原因）：群聊语言随意。用户问"Agent 框架太重的问题"，聊天记录可能全是"封装太多了""排查起来是真麻烦""langchain 这一坨看得头疼"，一次都不出现"Agent 框架太重"。此时 Keyword Recall = 0，但语义高度相关。因此必须保留第二条主召回路径 Semantic Retrieval。

### Semantic Retrieval

职责：用户表达的是一个意思，而聊天记录使用完全不同措辞时的语义召回。例如 Query "大家对重型 Agent 框架有什么意见？" 可召回 "封装太厚""调试困难""LangGraph 太重""自己写 loop 反而简单" 等。

**第一版 primary indexing unit 为 Conversation Chunk；默认不建立逐 Message 向量索引。**

不采用 `Message → embedding` 作为主索引的原因：群聊里大量消息语义残缺（"对""确实""哈哈哈""这个可以""我也是""？"），真正的信息分布在多轮对话中：

```text
A：我觉得 LangGraph 现在封装太厚了
B：确实
A：出了问题很难定位
C：我现在都直接用 SDK
B：简单一点反而好维护
```

因此第一版 semantic unit 以 **Conversation Chunk** 为 primary。这不封死 Message-level 语义检索的未来可能性：某些信息完整的长单条技术消息本身就是好的 semantic unit；若后续 Evaluation 证明 Message-level retrieval 对特定 Failure Case 有价值，再作为辅助索引引入（当前默认不建立，Pending Evaluation）。

采用 **Time-aware Parent + Small Child** 架构（参考 ChatLab 的 Parent / Child 思路）：

```text
Conversation Parent（一个相对连续的讨论区域）
│
├── Child Chunk 1
├── Child Chunk 2
├── Child Chunk 3
└── Child Chunk 4

Child Chunk → Vector（小 Chunk → 定位准确）
Query → 命中 Child → 定位所属 Parent → Context Expansion（大 Parent → 上下文完整）
```

- 具体切分参数（时间 gap、有效字符数、消息数、token 上限、overlap 等）**保持 Tunable，由 Trivae 自己的 Evaluation Set 决定**，不复制 ChatLab 的默认数字（30 min / 360 chars / 消息数 / overlap 等均不自动继承）。

### Context Expansion（Post-Retrieval Operator）

Context Expansion 是 **Post-Retrieval Operator**，与前三个 Retrieval Primitives 不在同一层：前三个负责"找出候选"（find candidates），Context Expansion 负责"拿已有命中，恢复其所在上下文"（recover surrounding context）。因此 **`retrieve` 与 `expand context` 是两个动作**。

- Failure Case：Semantic Search 命中张三一句"我现在觉得 LangGraph 真有点重"，只把这一条交给 LLM 信息远远不够；真正重要的是附近李四的追问、张三对状态和调试的解释、王五换 SDK 的后续。命中的关键句必须扩展为其所在 Evidence Window。
- 通过扩展命中附近消息（如前后多轮、回复链、同 Parent 范围内的消息）得到足够完整的上下文。
- Stage 1.4 已据此确认：`search something` 与 `expand this known hit` 是两类内部 capability；Agent-facing message search 自动组合高频 bounded expand，同时保留 `get_message_context(message_id)`（见 [Stage 1.4](#stage-14-tool--capability-layer)）。

### Hybrid 的定位

Hybrid 不是"更高级的 Vector Search"，而是：

```text
Lexical Candidates
        +
Semantic Candidates
        ↓
      Merge
        ↓
     Dedup
        ↓
  Candidate Selection
```

例如"最近半年群里对于 LangChain 是否适合做校招项目有什么看法？"：Keyword 命中 `LangChain / LangGraph / langchain`，Semantic 命中 `框架封装太重 / 简历里别堆框架 / 自己写 agent 更能体现能力`，二者互补。

### Query-specific strategy（不默认所有问题 Hybrid）

固定流水线（`query → BM25 + Vector → RRF → Reranker → LLM`）会让 Agent 失去根据任务选择信息获取方式的能力。Trivae 的策略：

| 问题示例 | 策略 |
| --- | --- |
| 有没有说过 LangGraph？ | Lexical |
| 大家为什么觉得一些 Agent 框架太重？ | Semantic |
| 过去半年 Agent 框架讨论发生了什么变化？ | 多轮 Semantic + Lexical verification + Structured 时间统计 |
| 今年到底有几次明确提到面试 OC？ | Lexical recall → dedup / verification → deterministic count |

"明确提到面试 OC" 是字面条件，直接用 Lexical 定义集合再确定性计数；只有当"拿 OC / 拿 offer / 过面 / 收到意向"等语义表达也要纳入时，Semantic 才有意义。**不能把"计数题"默认等同于 Hybrid。**

> **Retrieval Strategy 应该由任务决定，而不是所有 Query 固定执行同一个 Pipeline。**

（Stage 1.4 已确认第一版由 Agent 组合调用 `lexical_search` / `semantic_search`；具体策略指导机制与失败处理由 Stage 1.10 Case / Variant 契约在真实运行中校准。）

### Reranker 与 Fusion 权重（第一版不提前设计）

遵循 Stage 0 原则：**先建立 baseline → 出现 Failure Case → 证明排序有问题 → 再评估 Reranker**。当前没有证据证明 Trivae 需要 `Embedding + BM25 + RRF + Cross-Encoder Reranker` 的完整流水线。

第一版不把"所有 Retrieval 结果压成同一个 Candidate 类型"。Retrieval Result 概念上分两类：

```text
Retrieval Result
├── Message Candidates            # source: lexical | semantic
│       score / message_range / timestamp / matched_terms
└── Structured Results            # 标量 / 聚合 / 记录
        count = 372
        month × count 分组
```

Message Candidates 与 Structured Results 共同保留 provenance 与 trace metadata。Structured 结果（scalar / aggregate / records）不一定有 `score` / `message_range` / `matched_terms`，不能强行套入 Message Candidate 结构。Stage 1.4 已确认 Message Search Result 与 Tool Envelope 的概念契约；具体实现类型及 Structured Result 的 data schema 仍与后续 Data Schema 联动。

等 Evaluation 指出具体问题（例如 Ranking Error 成为主导 Failure Case）后再决定是否引入 Reranker 与 Fusion 权重。

### Retrieval Failure Attribution

一次检索至少应能区分以下错误类型，这是 Retrieval 可观测性的基础：

| Failure | 含义 |
| --- | --- |
| Lexical Miss | 关键词没有覆盖真实表达 |
| Semantic Miss | 向量没有召回相关讨论 |
| Chunk Boundary Error | 关键上下文被切开 |
| Filter Error | 时间 / 成员过滤错误 |
| Context Expansion Error | 命中了关键句，但上下文不完整 |
| Ranking Error | 召回了，但正确结果排得太后 |
| Coverage Error | Semantic Index 本身未完成 |
| Retrieval Budget Error | 候选太多被截断 |

关键可观测性约定：**不能"搜不到 = 不存在"。** 必须能够表达：

```text
0 results
+
query-scope coverage = partial
+
known gap = part of requested time range is not indexed
```

结论只能是：当前检索没有找到，但数据覆盖不足，无法确认不存在。因此 Semantic Retrieval 必须能显式暴露 coverage / partial / truncated 等完整性信息。

> Stage 1.9 已将 Coverage 明确为 **query-scope coverage**：以 `requested query scope ∩ Data Access Scope` 后的 effective scope 为基准，索引缺失不能缩小 denominator；状态为 `complete / partial / none / unknown / not_applicable`，只有 numerator / denominator / unit 可靠且同口径时才提供 ratio。全局索引覆盖率不能替代当前 session / time range 的 coverage。

### Retrieval Trace（观察需求，非 Schema）

Stage 1.3 先确定 Retrieval 需要观察哪些信息及其目的；Stage 1.9 已将这些观察项纳入全 Query normalized event boundary，并确认 query-scope coverage、Failure Attribution 与 storage 原则。具体 Python / JSON Schema 与采集实现仍 Pending。

目的：答案错误时，能够回答"到底是没召回，还是召回了但 Agent 没用？"——这两个 Failure Case 的根因完全不同。

| 观察项 | 目的 |
| --- | --- |
| `query`、`strategy` | 知道本次检索任务与所选策略（校验 Query-specific strategy 是否按预期执行） |
| `filters`（session / time_range / member） | 过滤条件是否正确应用（定位 Filter Error） |
| `lexical`（keywords / hit_count / latency） | 关键词召回情况（定位 Lexical Miss） |
| `semantic`（rewritten_query / index_version / model / coverage / candidate_count / top_scores / latency） | 语义召回与索引覆盖情况（定位 Semantic Miss / Coverage Error） |
| `context_expansion`（source_hits / expanded_ranges） | 上下文扩展是否正确（定位 Context Expansion Error） |
| `final_candidates`（ids / source / rank） | 最终候选集合、来源与排序（核对 provenance / 定位 Ranking Error） |

### Evidence 判断不在 Retrieval 层硬编码

不复制 ChatLab 用固定关键词（计划词 / 实际发生词）判断 `included / excluded / uncertain` 的方案。Trivae 面向技术情报，不同问题的“证据成立条件”完全不同（例如“最终有没有人真的把 OpenAI Agents SDK 用到项目里”可能出现“准备试一下”“已经接进去了”“昨天上线了”“最后还是换回自己写”）。Stage 1.8 已确认由 Agent Final Synthesis 针对 finding 表达并应用 **question-specific criterion**；不新增固定关键词 Judge 或独立 Evidence Agent。Retrieval 仍只产出 Candidate Data，不拥有 Final Evidence 判断。

### Stage 1.3 决策状态分类

#### Confirmed Architecture Decisions

| 项目 | 决策 |
| --- | --- |
| Retrieval 总体 | Multi-strategy Retrieval（Retrieval Composition + 三个 Primitives + Post-Retrieval Operator） |
| Structured Retrieval | 保留；目标集合确定后的确定性查询 / 聚合优先 |
| Lexical Retrieval | 保留 |
| Semantic Retrieval | 保留 |
| Semantic 索引单位 | 第一版 primary unit 为 Conversation Chunk（不默认建立 Message 级向量索引） |
| Chunk 架构 | Time-aware Parent + Small Child |
| Context Expansion | Post-Retrieval Operator（`retrieve` 与 `expand context` 是两个动作） |
| Hybrid | Composition Strategy，非底层搜索引擎 |
| 所有问题默认 Hybrid | 否 |
| Query-specific strategy | 是（由任务决定，不固定流水线） |
| Semantic Index | Derived Data，可重建 |
| Retrieval Result provenance | 必须保留（Message Candidates 与 Structured Results 共有） |
| Partial / Coverage | 必须显式暴露；Stage 1.9 已细化为 query-scope coverage |
| Evidence 判断 | 不在 Retrieval 层硬编码；Stage 1.8 已确认使用 question-specific criterion |
| Retrieval Trace | 观察需求与 Stage 1.9 normalized event / storage 语义已确认；具体 Schema / 实现 Pending |

#### Tunable / Pending Evaluation（由 Evaluation Set 决定）

| 项目 | 状态 |
| --- | --- |
| Reranker | Pending Evaluation（第一版不引入） |
| Fusion 权重 | Pending Evaluation（第一版不设计加权打分） |
| Chunk 具体参数（时间 gap / 字符数 / 消息数 / token 上限 / overlap） | Pending Evaluation（不复制 ChatLab 默认数字） |
| Message-level 辅助语义索引 | Pending Evaluation（第一版默认不建立；Evaluation 证明其对特定 Failure Case 有价值后再引入） |
| 组合 / 选择具体算法（merge / dedup / candidate selection） | Pending Evaluation |
| Query-specific strategy 的具体指导机制与失败处理 | Pending（Stage 1.10 Implementation / Real-run Calibration） |

#### Pending（后续阶段 / 架构实现前不决策）

| 项目 | 状态 |
| --- | --- |
| Vector Store 实现、Embedding 模型、Indexing Pipeline 具体执行方式 | Pending architecture specification |
| Semantic / Lexical Index 的具体存储与版本管理 | Pending architecture specification |
| Retrieval Trace 的具体 Python / JSON Schema、事件名与采集实现 | Pending Implementation；conceptual boundary 已由 Stage 1.9 确认 |
| Tool / Capability Layer（Agent 看到哪些 Tool、如何命名） | Confirmed（Stage 1.4） |
| Evidence / Citation | Confirmed（Stage 1.8）；具体 Python / JSON Schema 保持 Implementation Pending |
| Candidate / Retrieval Result 具体数据结构 | Pending（与 Storage / Data Schema 联动） |

## Stage 1.4: Tool / Capability Layer

> 本节为 Stage 1.4 已确认内容。Tool / Capability Layer 位于 Agent Runtime 与底层 Retrieval / Data Layer 之间，向 Agent 暴露**少量、语义清晰、容易调用**的工具，并隔离 Agent SDK 与底层业务实现。Stage 1.4 已完成；详细 rationale、trade-off、Failure Case 与重新打开条件见对应 ADR。

### 职责与位置

```text
Agent Runtime
     │ Tool Calling
     ▼
Agent-facing Tool Layer
     │
     ▼
Capability Layer
     │
     ▼
Retrieval / Canonical Data / Index
```

这一层解决两个问题：

1. 向 Agent 暴露少量、语义清晰、容易调用的工具。
2. 隔离 Agent SDK 与底层业务实现，使 Retrieval、Context、Identity 等核心能力不依赖具体 Agent Runtime。

### 核心职责边界

- **Capability** 是 Trivae 自身的业务能力，不依赖具体 Agent Runtime / SDK；**Tool** 是 Agent-facing 接口，负责参数校验、Capability 调用与结果标准化。
- 一个 Tool 可以组合多个 Capability。Tool Surface 优先模型易理解与减少机械调用，内部 Capability 仍保持独立可观测。
- `lexical_search` 与 `semantic_search` 默认组合 Retrieval + bounded Context Expansion；Local context 是 Search Result 的默认组成部分，但具体窗口参数由 Evaluation 决定。
- bounded context 用于判断候选价值，不以模型 Context Window 较大为由无限扩大结果；深度调查由 `get_message_context(message_id)` 承担。
- Tool 组合不得隐藏错误或执行状态，禁止 silent fallback。

### 第一版 Agent-facing Tool Surface

第一版暴露 6 个核心 Tool：

```text
Agent Runtime
│
├── lexical_search
│      ├── Lexical Retrieval
│      └── bounded Context Expansion
│
├── semantic_search
│      ├── Semantic Retrieval
│      └── bounded Context Recovery
│
├── get_message_context
│      └── Context Expansion
│
├── find_members
│      └── Identity / Membership Lookup
│
├── get_schema
│      └── SQLite Schema Inspection
│
└── execute_sql
       └── Read-only Structured Retrieval
```

新增 Tool 必须由真实 Evaluation 或 Failure Case 驱动，不以能力完整度为由扩大第一版 Tool Surface。

### Context、Scope 与 Identity 边界

- Search 自动附带的 bounded local context 用于候选判断；`get_message_context(message_id)` 用于 Agent 已识别重要消息后的深度上下文恢复。
- **Data Access Scope** 是硬授权边界，例如当前允许访问的 ChatSession、数据源或用户选定数据集合；所有 Tool（包括 `execute_sql`）都不得读取该边界之外的数据。
- **Query Context / Query-specific Filters** 是本次任务的查询条件，例如 time range、member、keyword。它们不自动等同于权限边界；是否必须由某个 Tool 强制应用，取决于对应 Tool Contract 与参数来源。
- Data Access Scope 与 Query Context 由 Agent Runtime 提供给 Tool Layer；第一版不提供 `get_scope_info`。`execute_sql` 不能仅依赖模型自行在 SQL 中加入 Data Access Scope 过滤条件。具体 enforcement 机制（物理数据库隔离、connection scope、SQL validation 或其他方式）留给后续 Storage / Runtime Implementation 决定。
- 人物查询使用 `find_members`，返回 `UserIdentity / Membership` 候选与匹配依据，不使用暗示唯一解析的 `resolve_member`。

### Structured Retrieval：Physical SQLite Schema + read-only SQL

第一版 structured / canonical persistent store 采用 SQLite，并沿用 ChatLab 已落地的查询结构：`get_schema` 读取真实 Physical SQLite Schema，`execute_sql` 直接对当前 SQLite 数据库执行只读 SQL；不增加 Analysis Schema / Analysis View 隔离层。

```text
SQLite
   ├── get_schema   → Physical SQLite Schema
   └── execute_sql  → bounded read-only SQL
```

`execute_sql` 至少满足以下边界：

- 安全约束是 statement 必须被确认是 read-only；`INSERT / UPDATE / DELETE / DROP / ALTER / CREATE` 等仅为非只读语句示例，不构成完整 denylist；
- 使用 `max_rows` 或等价机制限制结果规模，达到返回边界时显式暴露 Truncation；
- 不要求 Agent SQL 自身包含 `LIMIT`；Tool 可在不修改 SQL 文本语义的前提下，通过 result fetching、cursor、adapter-level max rows 等 Tool-level execution boundary 限制返回规模；具体机制留给 Implementation；
- 优先利用 SQLite Driver 的 readonly statement 判断；Driver 不支持时再设计明确的只读 SQL 校验；
- 不 silently 修改 Agent SQL，也不在执行失败后自动切换其他 Retrieval。

SQL 只处理目标集合已能由结构化条件确定的问题；需要 Semantic Classification 的集合，先由 Lexical / Semantic Retrieval 确定候选，再执行确定性统计或聚合。

若未来出现 Agent 经常选错内部表、Physical Schema 重构导致 SQL 大量失效、内部实现表持续污染 Tool 使用等 Failure Case，再评估 Stable Analysis Views。

### Search Result 与 Tool Result 契约

Lexical / Semantic Search 共享统一外层 Search Result 语义结构，但保留各自 provenance：strategy、matched message identities、lexical matched terms、semantic matched chunk identity，以及 retrieval-specific score。若暴露 numeric score，必须同时说明 `score_type`，禁止直接比较 BM25、FTS rank、cosine similarity 等不同体系的数字。

Context Message 必须保留稳定 message identity、session identity、稳定作者身份、可读作者显示信息、timestamp、content、reply 与 match 标记，不得只返回拼接聊天文本。本阶段确认的是必要信息及其语义关系，不冻结最终 Python type、JSON serialization、字段命名或数据库字段映射；作者身份究竟映射 `UserIdentity` 还是 `Membership`、显示信息采用何种历史语义，留给 Data Schema / Implementation 阶段确定。

所有 Tool 使用统一薄 Envelope：

```text
{
  status: "ok" | "partial" | "error",
  data: ...,
  meta: { truncated: true | false },
  error: { code, message } | null
}
```

- Zero Hits：`status = ok`，空结果；
- Invalid Argument：`INVALID_ARGUMENT`；
- Capability Unavailable：`CAPABILITY_UNAVAILABLE`；
- Execution Failure：`EXECUTION_ERROR`；
- Partial Result：`status = partial`；
- Truncation：`meta.truncated = true`，与 Partial Execution 保持区分。

所有可能返回大量数据的 Tool 必须 bounded；Message-based Retrieval 必须返回稳定 `message_id`；Retrieval Tool 返回 Candidate Data，不在 Tool 内硬编码 Final Evidence 判断。

上述 Search Result 与 Tool Result Envelope 均为语义契约，不是最终实现 Schema；具体类型、序列化形式与字段名留给 Data Schema / Implementation 阶段确定。

### 第一版不增加的 Tool 与抽象

第一版不引入 `Analysis Schema / Analysis View`、`candidate_ref / Candidate State`、`get_scope_info`、`resolve_member`、`hybrid_search`、`universal_search`、`retrieve_evidence`、大量 Specialized Analysis Tools 或复杂 Tool orchestration framework。

Hybrid 仍是 Stage 1.3 的 Retrieval Composition Strategy。确定性分析优先通过 `get_schema + execute_sql` 完成；只有 Evaluation 证明某类分析高频、SQL 经常出错或过于机械，且专用 Tool 明显提高可靠性或降低成本时，才考虑新增 Tool。

### 冻结的整体方向

```text
Agent Runtime + injected Query Context
        │
        ▼
Agent-facing Tools (6)
        │
        ├── lexical_search ─────┐
        ├── semantic_search ────┼── Retrieval + bounded Context Expansion
        ├── get_message_context ─── Context Expansion by message_id
        ├── find_members ────────── Identity / Membership Lookup
        ├── get_schema ──────────── Physical SQLite Schema
        └── execute_sql ─────────── bounded read-only Structured Retrieval
                                  │
                                  ▼
                         Capability Layer
                                  │
                                  ▼
             Canonical Store / Lexical Index / Vector Index
```

对于 Search（仅指 Lexical / Semantic 这类**面向消息候选**的 Search Tool）：

```text
Agent-facing message search tool:
Lexical / Semantic Search = Retrieval + bounded context recovery
Internal architecture:
Retrieval 与 Context Expansion 保持独立可观测的 capability
```

> 该约定**不推广到所有 Retrieval Tool**：Structured Retrieval 等返回聚合 / 标量结果的能力没有可扩展的"上下文"，不适用自动 Context Expansion；未来组合型 Retrieval 是否扩展由各自 Tool 契约决定。

概括为：**Tool 合并高频操作，Capability 保持清晰边界。**

### Stage 1.4 决策状态分类

#### Confirmed Architecture Decisions

| 项目 | 决策 |
| --- | --- |
| Tool / Capability 分离 | 是（Capability 不依赖 Agent Runtime；Tool 面向 Agent） |
| Tool 组合 Capability | 允许（一个 Tool 内部可组合多个 Capability） |
| Tool Surface 优先 Agent 易用性 | 是（减少机械 Tool Call，不把每步都暴露成 Tool） |
| Message Search 默认补充 context | 是（Lexical / Semantic message search；Local context 是 Search Result 默认组成部分，不推广到 Structured 等非消息候选能力） |
| 自动 Expand 范围 | bounded（有限消息数 / token / 时间窗口 / Parent 局部） |
| 内部 Capability 独立可观测 | 是（Retrieval 与 Context Expansion 仍是两个独立能力） |
| Semantic Search | 默认自动 bounded context recovery；返回保留 provenance |
| 大上下文窗口作为设计依据 | 否（仍考虑 token / latency / 噪声 / 注意力稀释 / 结果过多） |
| 参数冻结范围 | 仅冻结"Message Search 默认带 bounded context"；具体参数 Evaluation 决定 |
| Silent Fallback | 禁止（Failure Attribution 不可被组合隐藏） |
| 第一版 Tool Surface | `lexical_search`、`semantic_search`、`get_message_context`、`find_members`、`get_schema`、`execute_sql` |
| 深度上下文恢复 | 保留 `get_message_context(message_id)`；不引入复杂 Candidate State |
| Data Access Scope | 硬授权边界；所有 Tool（包括 `execute_sql`）不得读取边界外数据；enforcement 机制后续确定 |
| Query Context / Query-specific Filters | time range、member、keyword 等任务查询条件；不自动等同于权限边界，是否强制应用由 Tool Contract 与参数来源决定；不提供 `get_scope_info` |
| Member Lookup | `find_members` 返回候选与匹配依据；不使用 `resolve_member` |
| Structured Retrieval | 第一版 structured / canonical persistent store 采用 SQLite；直接暴露 Physical SQLite Schema + bounded read-only SQL；不增加 Analysis View |
| SQL 执行 | statement 必须确认 read-only；关键字仅为示例而非完整规则；bounded 但不要求 SQL 自带 `LIMIT`；不改写 Agent SQL；Truncation 显式暴露；失败后不自动切换 Retrieval |
| Search Result | 确认统一外层语义、strategy-specific provenance、score type 与结构化 Message Identity；不冻结实现 Schema |
| Tool Result Envelope | 确认 `ok / partial / error` 等状态语义；不冻结实现 Schema；Zero Hits 正常，Truncation 与 Partial 分离 |
| Hybrid / Specialized Tools | 第一版不暴露；新增由 Evaluation / Failure Case 驱动 |

#### Pending Evaluation（不影响 Stage 1.4 completed）

> 以下仅为经验参数或未来新增能力的 Evaluation，不重新打开已确认的架构方向。

| 项目 | 状态 |
| --- | --- |
| Lexical Search 具体上下文窗口参数 | Pending Evaluation |
| Semantic Parent / Context Recovery 具体策略 | Pending Evaluation |
| 各 bounded Tool 的具体默认上限 | Pending Evaluation |
| Specialized Analysis Tool / 高级组合 Tool 是否满足新增条件 | Pending Evaluation |

当前没有已批准的 **Experimental** 偏离。重新打开任何 Confirmed 决策必须记录 Reopen Reason（新 Failure Case、新技术约束、新 Evaluation 结果或新业务需求）。

## Stage 1.5: Router

> 本节为 Stage 1.5 已确认内容。Router 只负责 execution complexity classification 与 Planner gating，不负责 Tool Selection、Retrieval Strategy、Query Planning 或 Evidence Selection。具体实现参数与代码布局仍保持 Pending。

### 核心定位

Trivae Router 第一版是一个轻量的 **execution-complexity classifier / Planner gate**。它只回答一个问题：

> 当前请求是否值得在进入 Agent Runtime 之前，先通过 Planner 生成显式的高层执行 guidance？

Router 不是第二个 Agent，也不是低层执行编排器。它判断是否需要提前增加 Planning 这一个执行阶段；请求进入 Agent Runtime 后，具体 Tool、Retrieval 和下一步行为仍由 Agent Runtime 自主决定。

稳定职责链为：

```text
Router
    ↓
判断是否需要 Planning

Planner（仅 planned_execution）
    ↓
生成高层调查 / 执行 guidance

Agent Runtime
    ↓
根据当前状态自主决定具体下一步行为

Tool / Capability Layer
    ↓
执行数据访问、搜索、SQL 等具体能力
```

### Route Taxonomy

Trivae 第一版只保留两种 Route：

```text
standard_execution
planned_execution
```

#### `standard_execution`

请求目标足够明确，Agent 可以在执行过程中直接选择合适的 Tool，并根据结果自然推进，不需要在 Agent Loop 之前额外生成显式计划。

这一 Route 可以覆盖：

- 明确的计数、聚合或排序问题；
- 单个主题、成员或时间范围的查找；
- 一次检索后即可总结的请求；
- 需要多个 Tool，但步骤之间不需要预先拆解的请求。

例如“谁发言最多”“过去三个月有多少条消息”“找一下有没有讨论 LangGraph”“张三最近说过什么”“A 和 B 互相回复了多少次”都可能是 `standard_execution`。

`standard_execution` 不等于“不使用 Tool”。标准路径可以调用零个、一个或多个 Tool，例如：

```text
find_members → get_schema → execute_sql

lexical_search → semantic_search → get_message_context
```

Tool Call 数量不能单独决定是否进入 Planner；关键是任务是否需要在执行前形成高层调查结构。

#### `planned_execution`

请求包含多个需要协调的相互依赖调查目标，或最终结论需要跨阶段证据验证、且语义判断会改变下一步调查方向，显式 Planning 能够显著降低遗漏、过早下结论、单一路径失败和证据覆盖不足的风险。

典型任务结构包括：

- **Multi-goal / Multi-dimensional analysis**：同时分析话题变化与核心成员变化；
- **Temporal evolution**：划分时间阶段、寻找代表性讨论并判断 turning points；
- **Relationship / behavioral pattern analysis**：跨多组互动与技术议题比较成员关系；
- **Multi-factor judgment**：综合发言量、被回复情况、话题和影响力判断成员；
- **Evidence-dependent investigation**：区分“准备尝试”与“后来实际落地”，后续状态核验依赖前一阶段证据；
- **Explicit recovery / iterative investigation**：请求明确要求在证据不足时改写查询、尝试替代关键词或继续调查。

`planned_execution` 只表示“需要额外经过 Planner”，不表示 Planner 会接管后续执行，也不表示系统进入另一套 Agent Runtime。

### Planning Value 与任务结构

Router 关注任务结构，而不是复杂词汇。可观察的复杂度维度包括：

```text
Task Complexity
├── Multi-goal                         是否存在需要协调的独立调查目标，而非多个返回条目
├── Dependency                         后续调查是否依赖前一步结果
├── Temporal reasoning                 是否需要纵向状态变化、阶段演变或 turning point
├── Evidence dependency / cross-stage  后一阶段结论是否要等前一阶段证据成立后才能继续验证
├── Dependent semantic investigation   语义判断是否会改变下一步调查方向，而非只做候选归纳
└── Recovery                          是否明确需要证据不足处理并改写或替代调查路径
```

这些维度是 Router 的概念判断依据，不在 Stage 1.5 冻结为固定整数公式、权重或 threshold。通常应由多个复杂度信号共同表明 Planning 有价值，而不是由单个关键词触发。

`Multi-source evidence` 与 `Semantic judgment` 本身过于宽泛，不能直接视为 `planned_execution` 信号。需要阅读很多消息、收集多条 Evidence、跨多个群、做 Semantic Clustering / Synthesis，仍可能只是标准路径中的：

```text
retrieve → inspect → collect → synthesize → answer
```

只有当 Evidence 之间存在跨阶段验证依赖，或语义判断会决定下一步调查路线时，才更接近 Planning Value。

以下词语不能单独触发 `planned_execution`：

```text
分析、总结、过去一年、比较、关系、证据、趋势
```

例如“分析一下谁发言最多”仍可能只是明确的 Structured Retrieval；“总结昨天聊天”也可能只需要一次检索和总结。

以下因素本身也不是 Planning Signal：

```text
- 时间范围长
- 最近 / 过去半年 / 过去一年
- 跨群聊
- 候选消息很多
- 需要多次 Tool Call
- 同时使用 Lexical + Semantic Retrieval
- 需要 Context Expansion
- 需要对多条消息做主题归纳
- 需要整理多个实体 / 链接 / 资源
- 需要 member filter
- 最终答案包含很多条目
```

应明确区分：

```text
Data Scope Size ≠ Planning Complexity
Retrieval Volume ≠ Planning Complexity
Tool Call Count ≠ Planning Complexity
```

### Router、Planner 与 Agent Runtime 的关系

```text
User Query
+ Query Context
+ Compact Data Snapshot
+ Capability Summary
        │
        ▼
      Router
        │
        ├── standard_execution
        │          │
        │          ▼
        │      Agent Runtime
        │
        └── planned_execution
                   │
                   ▼
                Planner
                   │
                   ▼
          Soft Execution Guidance
                   │
                   ▼
              Agent Runtime
                   │
                   ▼
                 Tools
```

两种 Route 最终都进入同一个 Agent Runtime。Planner 输出的是高层、可被 Agent 参考的 soft guidance，而不是必须机械执行的 Workflow；Stage 1.6 已确认 Planner Input、Plan Schema、步骤类型、重规划和执行语义的概念边界，具体实现参数仍 Pending。

### Router Input

Architecture 层只冻结以下概念结构，不冻结 Python 类型、字段名称或实现文件：

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

`query_context`、`compact_data_snapshot` 与 `capability_summary` 由 Runtime 在进入 Router 前注入。Router 不通过 `get_chat_info()`、`get_scope_info()` 或其他普通业务 Tool 主动获取这些信息，也不接收大量聊天正文；`compact_data_snapshot` 只是轻量可用性元数据。

这与 Stage 1.4 的 Context / Scope 边界一致：Data Access Scope 仍由 Runtime 作为硬授权上下文提供给 Tool Layer，Router 不负责重新解释或扩大该边界。

### Route Decision

第一版冻结 Route Decision 的语义字段：

```text
RouteDecision
├── route
│   ├── standard_execution
│   └── planned_execution
├── confidence       0..1
├── reason           short diagnostic reason
└── source           rule | llm
```

- `route` 是唯一直接影响 Planner gating 的字段；
- `confidence` 用于诊断、后续 fallback 和 Evaluation，不在本阶段冻结阈值；
- `reason` 只提供简短、结构化、可诊断的原因，例如 `multi-dimensional temporal analysis with evidence requirements`，不承载 Chain-of-Thought；
- `source` 记录最终判断来自 Rule Router 还是 LLM Router；Stage 1.5 不增加第三个 `fallback` source，降级触发的原始错误由独立诊断 / Trace 记录。

Route Decision 不得包含以下内容：

```text
selected_tools
retrieval_strategy
keywords
semantic_queries
sql
filters
top_k
rerank_strategy
plan_steps
evidence_requirements
```

### Rule-first 与 Conservative Routing

第一版采用 Rule-first + LLM fallback：

```text
Query + Runtime Context
        ↓
    Rule Router
        ↓
  high confidence?
      ├── yes → use decision
      └── no  → LLM Router → decision
```

明显简单或明显复杂的请求由便宜、确定性的规则直接处理；只有规则无法可靠判断的 ambiguous case 才使用 LLM Router。具体规则、regex、LLM 模型、prompt、timeout 与 confidence threshold 保持 Pending。

Rule Surface 应保持小而结构化：识别任务结构，不把 GitHub、Skills、求职、模型降智等业务词汇分别扩展成固定 Route 规则。新增规则需要真实 Failure Case 或 Evaluation 证明，而不是围绕每个主题关键词持续加分支。

默认策略偏向 `standard_execution`：Planner invocation must earn its invocation。若无法明确证明显式 Planning 能够带来足够价值，不进入 Planner。

原因在于两类错误的代价不对称：复杂请求误判为 standard 时，Agent 仍可在 Runtime 中连续调用 Tool、调整查询和继续调查；简单请求误判为 planned 时，则稳定增加不必要的 latency、token、model call 和 plan-induced bias。

### Failure Cases 与降级原则

Router 需要在 Trace / Evaluation 中能够区分以下 Failure Case：

| Failure Case | 典型表现 |
| --- | --- |
| Under-routing | 复杂请求走 `standard_execution`，遗漏调查维度、过早下结论或证据覆盖不足 |
| Over-routing | 简单请求走 `planned_execution`，增加无意义的 Planning 成本与约束 |
| Keyword false positive | 仅因出现“分析”“过去一年”“证据”等词而错误进入 Planner |
| Keyword false negative | 复杂调查使用短或隐含表达，规则未识别其任务结构 |
| LLM Router malformed output | invalid JSON、unknown route、timeout、API error 或 parsing failure |

Router 是 **execution optimization layer，而不是 request availability dependency**。Router 本身异常时，请求不能因此整体失败；决策应降级到可用的 Rule Decision，若没有合理 Rule Decision 则采用保守的 `standard_execution`，再由 Agent Runtime 继续处理。

该降级是 Router 可用性契约要求的、范围明确且可观测的恢复路径，不等于允许 Tool / Retrieval 静默 fallback。降级原因、原始错误与最终 Route 必须能够被诊断记录；Stage 1.9 已确认 `router` event family、failure ownership 与跨层传播语义，具体 Schema / 实现仍 Pending。

### Router 与 Tool / Retrieval 的边界

Router 只决定执行复杂度，不决定数据访问方式：

| 模块 | 决定什么 | 不决定什么 |
| --- | --- | --- |
| Router | 是否值得先经过 Planner | Tool、Retrieval、SQL、关键词、Top-K、rerank、evidence |
| Planner | 复杂任务的高层调查 guidance（Stage 1.6） | 具体 Tool Call 顺序与底层查询参数 |
| Agent Runtime | 当前状态下下一步行为与是否调用 Tool | 不改变 Router 的 Route 语义 |
| Retrieval | 如何从数据底座召回候选 | 是否需要 Planner |
| Tool / Capability Layer | 执行搜索、SQL、上下文恢复等具体能力 | Route 分类与高层计划 |

因此不引入以下 Router taxonomy：

```text
lexical_route
semantic_route
sql_route
hybrid_route
```

这些属于 Retrieval / Agent Runtime 的执行选择。`standard_execution` 也不等于 `tool_assisted`：标准路径可以不调用 Tool，也可以调用一个或多个 Tool；是否调用 Tool 不是 Router 的职责。

### Trace 与 Evaluation 要求

Stage 1.5 先确认 Router 必须留下可追踪、可评估的决策信息；Stage 1.9 已将 Route Decision、degradation 与 failure 纳入 normalized Trace。本节不实现 Evaluation Benchmark；Case / Reference、forced-path Utility、pinned Variant 与 paired Review 的语义见 Stage 1.10 ADR，具体运行仍 Pending。

未来 Router Evaluation 应包含：

- obvious standard；
- obvious planned；
- ambiguous；
- keyword traps；
- long-time-range but simple；
- multi-tool but simple；
- short wording but complex；
- evidence-dependent / cross-stage investigation。

这些是 workload slice，不是要求每条 Case 预先填写 `expectedRoute` 的标签表。没有明显 Planner Utility 的 Case 可以不设路径假设，先通过 Stage 1.10 forced-path 结果建立后验诊断。

正确顺序为：

```text
定义 Route 语义
    → 建立带标签 Query Set
    → 实现 Rule Router
    → Evaluation
    → 调整规则与参数
```

具体 Trace Python / JSON Schema 与采集实现保持 Implementation Pending；accuracy、error rate、threshold calibration 和回归执行方式留待 Stage 1.10 Implementation / Real-run Calibration。

Router Evaluation 的最终目标不是得到漂亮的 Route Classification Accuracy，而是验证 Planner Invocation 是否带来实际下游收益。Stage 1.10 可以对同一个 Query 比较两条受控路径：

```text
A: standard_execution → Agent Runtime
B: planned_execution  → Planner → Agent Runtime
```

至少比较 Answer Correctness、Evidence Completeness、Missed Dimensions、Tool Calls、Tokens 与 Latency。若 planned path 没有明显质量收益却稳定增加 latency / token，则该类 Query 应归入 `standard_execution`，即使抽象复杂度分类器认为它“很复杂”。

在真实 workload 可能明显偏向 standard 的情况下，Stage 1.10 不能只看 Aggregate Accuracy；至少还要分别观察 `planned_execution` precision / recall 与 Planner 的实际收益。

### Stage 1.5 决策状态

#### Confirmed Architecture Decisions

| 项目 | 决策 |
| --- | --- |
| Router 定位 | 轻量 execution-complexity classifier / Planner gate |
| Route taxonomy | 仅 `standard_execution` 与 `planned_execution` |
| Planner 触发 | 仅 `planned_execution` 额外经过 Planner |
| Agent Runtime | 两种 Route 最终进入同一个 Agent Runtime |
| Planner 输出 | soft execution guidance，不是强制 Workflow |
| Router Input | Runtime 注入 User Query、Query Context、Compact Data Snapshot、Capability Summary |
| Route Decision | `route`、`confidence`、`reason`、`source` 的语义契约 |
| 分类依据 | 任务结构与 Planning Value，不是单个关键词、数据规模、检索量或 Tool Call 数量 |
| 路由策略 | Rule-first，ambiguous case 使用 LLM Router |
| Rule Surface | 小而结构化，不发展成按业务关键词扩展的分类器 |
| 默认策略 | Conservative，无法证明 Planning 有价值时使用 `standard_execution` |
| 失败原则 | Router 失败不得阻断请求；无可用规则时保守降级到 `standard_execution` |
| Evaluation 目标 | Planner Invocation 的实际下游收益，不是单独追求 Route Classification Accuracy |
| 职责边界 | Router 不选择 Tool、Retrieval、SQL、查询参数、Plan 或 Evidence |

#### Pending（实现 / Evaluation / 后续 Stage）

| 项目 | 状态 |
| --- | --- |
| 具体规则、regex、复杂度权重与固定公式 | Pending Evaluation / Implementation |
| Confidence threshold 与 LLM 触发 threshold | Pending Evaluation |
| LLM Router 的模型、prompt、timeout 与调用适配 | Pending Implementation |
| RouteDecision 的具体 Python 类型、序列化与文件布局 | Pending Implementation |
| Router Trace 的具体 Schema、事件名与采集实现 | Pending Implementation；event family / ownership 已由 Stage 1.9 确认 |
| Router Query Set、Finding / Utility review 与校准方法 | Pending（Stage 1.10 Implementation / Real-run Calibration；不要求每条 Case 预填 expectedRoute） |
| Planner 的 Python / JSON 实现、模型参数、具体 bounds 与 Runtime adapter | Pending（Stage 1.6 Implementation / Evaluation）；Planner 的概念 Input、Plan Schema、重规划与执行语义已确认 |

## Stage 1.6: Planner

> 本节只保留 Stage 1.6 Planner 的稳定架构契约。Planner 是 **Thin pre-execution investigation planner**：仅在 planned_execution 进入 Agent Runtime 前运行一次，输出 soft investigation guidance，不拥有独立 Agent Loop、Tool Executor、Execution State 或 Automatic Replanning。Planner 的详细 rationale、Input 语义、Plan Schema、Validation、Failure Case、Trade-off 与 Reopen Conditions 见 [Stage 1.6 Planner ADR](./technical-decisions/stage-1-6-planner.md)。

### 核心定位与执行链路

~~~text
standard_execution
    → Agent Runtime

planned_execution
    → Planner
    → deterministic validation / sanitization
    → soft guidance
    → same Agent Runtime
~~~

Planner = Investigation Decomposition，不是 Tool Execution Planner。两条 Route 最终进入同一个 Agent Runtime；Planner 不执行 Plan Step、不逐步驱动 Tool Calls、不维护 Step Execution State、不拥有 Planner Tool Calling，也不在执行中自动重新规划。

### Planner / Agent Runtime 稳定边界

| 模块 | 稳定职责 | 不越界到 |
| --- | --- | --- |
| Planner | 复杂调查目标、少量高层 investigation steps、调查问题、证据类型、可能有帮助的 capability、success criteria | Tool execution、具体 Tool 参数、实时 Retrieval Strategy、Search Query、SQL、filters、top_k、rerank、Evidence Selection、Citation、Retry、Fallback、Runtime Loop |
| Agent Runtime | 当前状态下的 Tool Selection、Tool 参数、Retrieval 组合、Query / SQL、Context 获取、继续或停止调查、证据不足时的调整、是否偏离 Plan | 不把 Plan 当 mandatory workflow；不改变已发生的 Router Decision |
| Tool / Capability Layer | 执行 Stage 1.4 已确认的六个 Tool / Capability | 不接受 Planner 对 Tool Arguments、执行顺序或底层 Retrieval 参数的绑定 |

### 稳定架构契约摘要

- Planner Input 由 Runtime 在概念层注入：user_query、query_context、compact data_snapshot、capability_summary。user_query 必须足够表达当前会话语义；query_context 与 Data Access Scope 保持分离；Data Snapshot 主要表达 coverage、scale、availability 与 basic environment metadata；Capability Summary 只提供高层 purpose、important constraints 与 availability。
- Router diagnostic reason、大量聊天正文、Retrieval Result、Tool Result、Agent intermediate state、Evidence Object 与 Citation State 不属于第一版 Planner Input。Planner 不主动调用 Tool，也不观察 Tool Result。
- Plan 采用轻量概念字段：version、title、intent、steps.goal、steps.suggested_tools、steps.evidence_needed、success_criteria。Python / JSON 具体格式留给 ADR 后续 Implementation。
- intent 继承 ChatLab 的 summary / trend / relationship / search / comparison / evidence / mixed 作为 v1 baseline metadata，不是第二个 Router，也不绑定 Route、Tool 或 Retrieval；长期 taxonomy 是否保留或扩展由 Evaluation 决定。
- goal 必须 outcome-oriented / investigation-oriented；suggested_tools 只是 advisory capability hint，不生成 Tool Arguments；evidence_needed 是需求描述，不是 Stage 1.8 Evidence Object；success_criteria 是自然语言 soft completion guidance。
- 第一版不加入 Workflow / Execution 字段、Planner-owned state、automatic replanning、Planner-specific retry / regeneration 或在线 LLM Plan Validator。Plan 的具体 bounds 保持 Pending Evaluation / Implementation calibration。
- LLM Plan 必须经过 parse、structural validation 与 bounded sanitization；不存在或不可用的 suggested Tool 被过滤；核心结构 invalid 时 skip Plan 并继续 Runtime。
- Planner failure / timeout / invalid output / unavailable / aborted 不得阻塞可用 Agent Runtime，也不重写 Router Decision；允许 Runtime 偏离 Plan，Plan deviation 不等于 Planner failure。
- ChatLab 继承范围是 pre-execution planner、structured plan、bounded plan、available Tool filtering、invalid plan graceful skip、soft guidance injection 与 same Agent Runtime；ChatLab-specific Prompt / Tool heuristic 不机械复制，Trivae-specific heuristic 需要真实 workload、Failure Case 或 Evaluation 支撑。

### Stage 1.6 Confirmed Architecture Summary

1. Thin pre-execution Planner，只在 planned_execution 进入 Runtime 前运行一次。
2. standard_execution 与 planned_execution 最终进入同一个 Agent Runtime。
3. Plan 是 investigation soft guidance，Runtime 保留 Tool Selection、Evidence Investigation 与执行自治。
4. Planner Input 由 Runtime 注入，且 Data Snapshot 保持 compact。
5. Plan Schema 轻量；intent 是 descriptive baseline metadata；goal、suggested_tools、evidence_needed 与 success_criteria 各自保持既定边界。
6. 不引入 Workflow Engine、Step Executor、Planner-owned execution state、automatic replanning、Planner Tool Calling 或 Planner-specific retry。
7. Deterministic validation、Hallucinated Tool filtering、Bounded Plan 与 graceful degradation 已确认。
8. ChatLab 作为架构 baseline，Trivae-specific heuristic 由 Evaluation 驱动。

### Stage 1.6 Pending 路由

详细 Pending 项见 ADR；Architecture 层只保留归属：

- Python class / package layout、Model、Prompt、Structured Output、具体 Schema、字段类型、bounds、DataSnapshot schema 与 Context 压缩：Implementation / Stage 1.7。
- Planner latency budget 与 invocation policy、Evaluation Dataset、质量 / latency / token / Tool Call 指标、参数校准、是否增加 intent 类型、是否未来需要 replan：Stage 1.10 Implementation / Real-run Calibration（Case / Reference / forced-path 语义已确认）。
- Planner Trace family、failure ownership 与 operational metric 维度已由 Stage 1.9 确认；具体 Schema / 事件名 / 采集实现 Pending。第一版不建立 Planner step execution state 或 step-level execution trace。
- Evidence / Citation：Confirmed（Stage 1.8）；Planner `evidence_needed` 仍只表达 requirement。

完整的 21 项 Confirmed Decisions、详细 Failure Case 与 Reopen Conditions 见 [Stage 1.6 Planner ADR](./technical-decisions/stage-1-6-planner.md)。

## Stage 1.7: Agent Runtime

> 本节只保留 Stage 1.7 Agent Runtime 的稳定架构契约。核心方向：**继承 ChatLab 的 Thin Agent Core 架构，由 OpenAI Agents SDK 承载通用 Agent Loop；Trivae 自己拥有外层执行编排、Context、Conversation History、Tool Adapter、生命周期语义和事件契约。** 详细 rationale、Trade-off、Failure Case 与 Reopen Conditions 见 [Stage 1.7 Agent Runtime ADR](./technical-decisions/stage-1-7-agent-runtime.md)。

### 核心定位与执行链路

```text
standard_execution
    → Agent Runtime

planned_execution
    → Planner
    → deterministic validation / sanitization
    → soft guidance
    → same Agent Runtime
```

Agent Runtime 定义为 **Single-agent execution runtime**：驱动模型与 Tool 之间的 bounded Agent Loop，并提供稳定的 streaming、cancellation、termination 和 result boundary。通用 Agent Loop 由 OpenAI Agents SDK 承载，Trivae 不自行重写通用 Loop；第一版单 Agent，不引入 handoff / multi-agent。

### Query Execution Orchestration 与 Agent Runtime

明确区分两个概念：

```text
Request Orchestrator
    负责整个 Query 生命周期（Context Assembly → Router → Planner → Runtime → Result）

Agent Runtime
    从 Agent Loop 启动开始负责执行核心
```

第一版 `Query Execution Orchestration` 可以只是一个 service/function，不需要成为新的重"架构层"。ROUTING / PLANNING 属于整个 Query Execution lifecycle，但不属于内部 Agent Loop。

### SDK 接入方式

```text
Trivae AgentRuntime interface
             │
             ▼
OpenAIAgentsRuntimeAdapter
             │
             ▼
OpenAI Agents SDK
```

未来替换 SDK 主要替换 **OpenAI Agents Runtime Adapter** 与 **OpenAI Function Tool Adapter**，而不是 Retrieval、SQLite、Context Expansion、Identity 等业务系统。这里确认的是 SDK 的概念替换面；Stage 1.11 已确认单 distribution 与概念 package ownership，但不冻结具体文件名、class 或 adapter 实现。Capability 不绑定具体 Runtime（Stage 1.4）的约束在 Stage 1.7 继续保留并扩展到 Runtime / Tool 的 SDK 接触面。

### Context 两种分离

- **RuntimeContext（local）**：不发给 LLM，承载 run / request identity、conversation identity、`data_access_scope`（硬权限）、capability dependencies、database / retrieval handles、cancellation state、runtime budgets。
- **Agent Model Context（LLM-visible）**：system instructions、bounded conversation context、current user request、relevant query-context projection、compact session/data metadata、validated plan guidance（仅 planned_execution）。
- **Data Access Scope 硬执行**：必须在 Tool / Capability 执行路径中强制执行，不写进 system prompt 靠模型自觉。

### Conversation History 归属

Trivae Conversation Store 是 source of truth，v1 不用 SDK Session 作为 canonical storage：

```text
Trivae Conversation Store
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

SDK / Provider 提供的 `Session`、`conversation_id`、`previous_response_id` 或其他 server-managed conversation state 只能作为可替换、可由 Trivae Store 重建的 adapter state，不能成为 canonical history。Streaming delta 只用于临时展示；Tool Call / Tool Result 保持结构化关联；完整 assistant message 仅在 SDK Run 真正完成后以 `COMPLETED` 提交。`ABORTED` / `FAILED` 的 partial output 与已发生 Tool 记录可以保留用于诊断，但必须带非完成状态，默认不作为完整 assistant turn 参与后续 replay。具体 transaction 与存储 Schema 保持 Pending。

### 终止条件、Tool Error、Abort、Streaming

- **终止条件两层**：一个模型轮次产生一个或多个 Tool Call，且该轮 Tool Result 全部形成后，计为一个 Tool Round；同轮并行多个 Tool 仍只计一轮。Trivae Tool Investigation Budget 耗尽后禁用 Tool 并执行 graceful final synthesis；SDK `max_turns` 必须覆盖全部 Tool-bearing turns，并至少预留一次 final synthesis 模型调用，仅作 absolute safety backstop。final synthesis fatal 时显式 `FAILED`。
- **Tool Error ≠ Runtime Failure**：只有已知、已分类的 Tool Contract Error（如 capability unavailable、invalid argument、scope violation、bounded execution failure）转换成 `status=error` + `error.code` 交给 Agent 恢复；未分类 Tool / Capability 异常、Adapter invariant、SDK generic error handler 试图吞掉的程序缺陷以及其他 fatal failure 必须显式进入 `FAILED`。
- **Abort = terminal intent**：`ABORTED` 不执行 final synthesis；v1 immediate 接受终止意图，取消 SDK Run 并向 Tool / Capability 协作式传播 cancellation。它不承诺同步阻塞调用能物理瞬时中断；晚到 Tool Result 不得重启 Loop 或触发 final synthesis。`COMPLETED` 以 SDK Run 真正完成为准（不是最后一个可见 token）。
- **Streaming canonical path**：`SDK StreamEvent → OpenAIAgentsRuntimeAdapter → Trivae Runtime Event → CLI / API / UI`；禁止直接返回 SDK StreamEvent。

### Runtime lifecycle 状态机

```text
CONTEXT_PREPARING → ROUTING → (PLANNING) → AGENT_PREPARING
    → RUNNING (RESPONDING / TOOL_RUNNING) → (FINALIZING) → COMPLETED
任何阶段：User Abort → ABORTED；Fatal Runtime Error → FAILED
```

### Planner→Runtime Adapter

`Validated Plan → Plan Guidance Renderer → LLM-visible soft instructions → Agent Runtime`；Runtime 不读取 plan.steps 逐条执行；`effective_system_prompt = system_prompt + buildPlanGuidance(plan)`（仅 planned_execution）。

### SDK built-in Trace 不当正式 Trace

Trivae 配置必须显式关闭 SDK built-in external tracing，不能依赖 SDK 版本默认值；`SDK Hooks / Stream Events → Trivae normalized runtime events → Normalized Query Event boundary → Trace Collector`。Stage 1.9 已确认正式 Trace 的语义边界，具体 Python / JSON Schema 与 Collector 实现仍 Pending。

### Stage 1.7 Confirmed Architecture Summary

1. Thin Agent Runtime，由 OpenAI Agents SDK 承载通用 Agent Loop；Trivae 拥有外层编排、Context、Conversation History、Tool Adapter、生命周期与事件契约。
2. 单 Agent；`standard_execution` 与 `planned_execution` 使用同一个 Runtime。
3. Runtime 不重新吞掉 Router / Planner / Retrieval / Evidence。
4. OpenAI Agents SDK 通过薄适配层接入，业务代码不直接依赖 SDK 类型；替换面为 runtime / tools adapter。
5. RuntimeContext（local）与 Agent Model Context（LLM-visible）分离；Data Access Scope 硬执行。
6. Trivae Conversation Store 为 source of truth；SDK / Provider conversation state 只作可重建 adapter state；streaming、完成、中止与失败记录有明确提交边界。
7. Pre-run Context 压缩，不做 mid-run compaction。
8. Tool Round 按“一个包含 Tool Result 的模型轮次”计数；Trivae Budget 先触发 graceful final synthesis，SDK max_turns 为其预留一次最终调用并只作兜底。
9. 仅已知 Tool Contract Error 可恢复；未知 Tool / Adapter 异常必须显式 `FAILED`，不能由 SDK generic error handler 吞掉。
10. Abort = terminal intent，采用协作式 cancellation，晚到结果不能重启执行；Streaming 为 canonical path。
11. Runtime lifecycle 状态机已定义；ROUTING / PLANNING 属于 Query 生命周期。
12. Plan 只作 soft guidance 注入，Runtime 不逐条执行。
13. SDK built-in Trace 不当正式 Trace；Trivae 显式关闭 external tracing，不依赖 SDK 默认值。
14. ChatLab 经验参数可直接继承作为 v1 baseline，标注来源，保留 Evaluation 校准。

### Stage 1.7 Pending 路由

- 具体 package 文件、SDK 版本、Adapter 契约与实现、RuntimeContext / Agent Model Context 类型、Tool 并发策略、Agent Model、Prompt 文案：Implementation；概念 package ownership 已由 Stage 1.11 确认。
- `max_tool_rounds`、SDK `max_turns`、history window、compression threshold、Tool Result token budget 等具体数字：Pending Evaluation（可继承 ChatLab 经验参数，标注来源）。
- Runtime Event / Trace 的 conceptual envelope、Error Code ownership、storage 与 SDK tracing 边界已由 Stage 1.9 确认；具体 Python / JSON Schema、Error Code 枚举、Collector / Store backend 与 exporter 实现保持 Implementation Pending。
- Agent correctness benchmark、budget / threshold 参数校准：Stage 1.10 Implementation / Real-run Calibration。
- Evidence-aware stopping：Stage 1.8 已确认第一版只作 Agent guidance；machine-enforced gate 与参数留给 Stage 1.10 Implementation / Real-run Calibration。

完整的 20 项 Confirmed Decisions、详细 Failure Case 与 Reopen Conditions 见 [Stage 1.7 Agent Runtime ADR](./technical-decisions/stage-1-7-agent-runtime.md)。

## Stage 1.8: Evidence / Citation

> 本节只保留 Stage 1.8 的稳定架构契约。核心方向：**一份结构化 Answer Artifact 同时驱动 claim-level Citation 与 Evidence Panel；所有数据性结论都可追溯到当前 Run 实际取得的 Message Source 或 Structured Result Source，并允许用户通过精确时间与 bounded 原始上下文人工复核。**

### 数据流与提交边界

```text
Current Run Tool Calls / Tool Results
        ↓
Agent Final Synthesis
        ├── apply question-specific criteria
        ├── select Final Evidence
        ├── organize Evidence Items by finding
        └── produce Answer + Citation bindings
        ↓
Citation Validation / Trusted Metadata Hydration
        ↓
Validated Answer Artifact
        ↓
Conversation Store commit
```

Citation Finalizer 是 Answer Generation 的确定性提交边界，不是新的 Tool、Agent、Judge 或 Runtime-owned Evidence State Machine。它验证引用真实性、可解析性与 Data Access Scope，不宣称能够验证自然语言语义正确性。

### Stage 1.8 Confirmed Architecture Summary

1. Final Evidence 按 claim / finding 组织，一个 Evidence Item 可以包含多条 `supports / contradicts / context` Source。
2. Answer 中的数据性事实与推断使用 claim-level Citation；正文显示与 Evidence Panel 共用同一 Answer Artifact。
3. Message Source 由 current-run provenance、显式 Session / Message locator 和可信人工复核 snapshot 共同构成。
4. Structured Result 使用独立 Source Reference；Semantic Chunk 只作 acquisition provenance。
5. question-specific criterion 与 Evidence Item 一起持久化；不使用固定关键词 Judge。
6. `sufficient / partial / insufficient` 与 Tool `partial / coverage / truncated / unavailable` 分轴表达。
7. invalid / unresolved Citation 阻止 Answer 提交，不 silent drop 或自动 repair。
8. 历史 Evidence 可查看但不是后续 Run 的 fresh evidence；事实问题必须重新调用当前数据库 Tool。
9. 应用内只展示被引消息及 bounded 原始上下文；全量聊天由原社交平台承载。
10. Evidence-aware stopping 仅作 Agent guidance；Stage 1.7 Tool Budget 仍是 hard investigation bound。

### Stage 1.8 后续实现与阶段路由

- Python / JSON / Database Schema、Claim binding 序列化、Structured Result locator、Conversation commit Schema：Implementation。
- bounded context 数量、Citation 密度、Evidence Item 上限、Message mutation 后的 diff UX：Implementation / Evaluation。
- Evidence / Citation Trace family、Error Code ownership、storage 与 operational metric 边界已由 Stage 1.9 确认；具体 Schema、Error Code 枚举与实现保持 Implementation Pending。
- semantic entailment、sufficiency、citation precision / recall、repair 与 machine-enforced stopping gate：Stage 1.10 Implementation / Real-run Calibration（quality axes、Review 与进入条件语义已确认）。

完整的 16 项 Confirmed Decisions、ChatLab 代码证据、Failure Case 与 Reopen Conditions 见 [Stage 1.8 Evidence / Citation ADR](./technical-decisions/stage-1-8-evidence-citation.md)。

## Stage 1.9: Trace / Observability

> 本节只保留 Stage 1.9 的稳定架构契约。核心方向：**整个 Query Execution 使用 Trivae-owned normalized event boundary；Trace 保存跨 Router、Planner、Runtime、Tool、Retrieval、Evidence、Citation 与 Answer commit 的可回放事实，同时通过 data minimization、query-scope coverage 与明确 ownership 支持 Failure Attribution。**

### Normalized Event Boundary

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

Stage 1.7 的 `Trivae Runtime Event` 是全链路 normalized event 的 Runtime family。SDK Hook / StreamEvent 必须先经 Runtime Adapter 转换；Router、Planner、Retrieval 与 Finalization 保留自己的 domain payload，不伪装成 SDK event。Trace Collector 只负责 envelope、correlation、sequence、privacy projection、persistence 与 completeness，不驱动业务执行。

Conceptual event envelope 至少表达 version、`event_id / trace_id / request_id`、单 Trace `sequence`、发生 / 观测时间、stage、operation、phase、`operation_id / parent_operation_id`、由 Trace Profile / capture policy 控制详细度的 payload、limitations 与 failure。它冻结语义，不冻结 Python / JSON / Database Schema。

### Stable Event Families

- Query / Context：received、context prepared / failed、terminal completed / failed / aborted；
- Router：decision、degraded、failed invocation，并同时保留原始 failure 与最终 Route；
- Planner：started、validated / sanitized、completed、failed、skipped；不创建 `steps[]` 的 execution state；
- Runtime / Model：model turn、Tool Round、budget finalization、stream / cancellation 与 lifecycle terminal；
- Tool / Retrieval：call / operation identity、status、arguments / query 的 bounded projection、result / candidate identity、latency、coverage / truncated / unavailable；
- Evidence / Citation / Answer：selection、validation、finalization 与 Conversation Store commit 的成功 / 失败边界；
- Trace：Collector / Store failure、sequence gap 与 incomplete 状态。

逐 token stream 默认不永久记录；Normal 与 Debug 都排除 Chain-of-Thought、provider hidden reasoning 与 secrets。完整聊天 / Tool / Model payload 不是 Normal 的默认形态，但在 Debug capture policy 与当前 Data Access Scope 允许时可保存完整或近完整的 model-visible / system-visible facts。

### Failure Attribution 与 Error Ownership

Failure 同时表达 `origin_stage`、`observed_stage`、`error_code`、category、cause operation 与 handling。首个破坏 contract 的层拥有 Error Code；Wrapper 只传播，不以自己的 generic code 覆盖根因。Query terminal outcome 可以引用 underlying failure，但不能用 `QUERY.FAILED` 抹掉 `CITATION.*`、`RETRIEVAL.*` 或其他 owner code。

Recovery / degradation 不抹掉已经发生的错误：Router / Planner failure 后 Query 可以完成；已知 Tool Contract Error 可以返回 Agent；未知 Tool / Adapter exception 显式使 Runtime failed。Abort、Budget exhaustion、degradation 与 terminal failure 分开。

Online Trace 记录诊断事实，不自动宣称 Under-routing、Lexical Miss、Ranking Error、Evidence Selection Error 或 Answer Correctness 等需要人工复核 / Stage 1.10 Evaluation 才能确诊的质量 Root Cause。

### Query-scope Coverage

```text
requested_query_scope ∩ Data Access Scope
        ↓
effective_query_scope
        ↓
coverage of this capability / index within that scope
```

Coverage 相对于当前授权查询范围表达，不能用全局索引百分比替代，也不能因为索引缺失而缩小 denominator。每个适用 operation 保留 `scope_reference / basis / basis_version / as_of / status / covered_units / eligible_units / unit / known_gaps` 的概念语义；只有 numerator、denominator 与 unit 可靠且同口径时才给 ratio。

状态为 `complete / partial / none / unknown / not_applicable`。`unknown` 不得伪装成 `complete`；不同 Retrieval primitive 不做未经定义的 coverage 平均。Coverage、truncated、unavailable、Tool status 与 Evidence `sufficient / partial / insufficient` 保持分轴。

即使 capability coverage 为 complete，也只说明对 Canonical Store 当前已知数据的执行完整性，不自动证明外部社交平台导入完整或现实中不存在该事实。

### Privacy、Retention 与 Storage

- Trace 使用两个正式 Profile：`normal` 与 `debug`。Normal 以结构化事实为主，但允许对 User Query、Prompt / Context、Tool、Retrieval、Evidence、Citation 和 Answer 保存有诊断价值的 bounded / redacted actual content；不再规定默认永远 reference-only。
- Debug 在本次 Run 的 Data Access Scope 内，允许保存完整或近完整的 model-visible / system-visible execution facts，包括实际 Model Context、Tool arguments / results、Retrieval / Context Expansion、Evidence / Citation 中间结果和 Final Answer；Profile identity、capture policy 与 truncation 必须可回放。
- 任何 Profile 都不得保存 credentials / API keys / access tokens / connection strings、越权数据、provider hidden reasoning 或 hidden Chain-of-Thought；Debug 不改变 Data Access Scope。
- Trace 读取 / 外部导出不能扩大 Data Access Scope。OpenAI Agents SDK built-in external tracing 继续显式关闭；未来 exporter 只能消费 privacy-projected Trivae Event。
- Retention 按 metadata、Normal payload、Debug payload、aggregate metrics、Answer Artifact 与 canonical source 分层。Stage 1.9 不强制 Debug 比 Normal 更短；Local-first 开发环境可以按显式配置保留到人工清理，生产环境必须由部署策略明确 retention、访问和删除边界。
- Trace Store 是独立、append-only、versioned 的事实存储；reference 是稳定关联方式，但 Normal / Debug capture policy 可以保存允许的 bounded、完整或近完整内容。具体 backend、partition、buffering 与部署拓扑保持 Implementation Pending。
- Trace persistence 不与 Answer Artifact commit 强行组成分布式事务。Trace failure 不回滚成功业务结果，但必须通过 `TRACE.*` operational error / health signal 显式暴露并标记 incomplete，禁止 silent loss。

### Operational Metrics 与 Stage 1.10 边界

Stage 1.9 只确认可以从 sanitized Trace 派生 Query / stage latency、terminal outcome、Router degradation、Planner failure category、model / prompt / token usage、Tool / Tool Round count、Tool status / Error Code、Retrieval strategy / candidate count / coverage、Evidence / Citation / Finalization structural outcome、abort / budget / trace incomplete 等 operational dimensions，不设 threshold。

Router / Planner / Retrieval / Evidence / Citation / Answer 的质量数据集、标签、accuracy / precision / recall、semantic entailment、Planner Utility、threshold、gate 与参数校准全部属于 Stage 1.10；本阶段不实现这些内容，治理语义已在 Stage 1.10 ADR 确认。

### Stage 1.9 Confirmed Architecture Summary

1. 一个 Trivae-owned normalized event boundary 横跨完整 Query Execution；Stream 与 Trace 是不同投影。
2. Trace 以 versioned event、单 Trace sequence 和 operation causality 表达事实；状态与 metrics 是 derived projection。
3. Failure Attribution 区分 origin、observation、handling 与 terminal outcome；恢复不抹掉失败。
4. Error Code 由稳定 stage / contract owner namespace 拥有，跨层传播不改名。
5. Query-scope coverage 基于授权 effective scope，支持 `complete / partial / none / unknown / not_applicable`，只在口径可靠时给 ratio。
6. coverage / truncation / availability / Tool status / Evidence sufficiency 分轴表达。
7. Trace Profile 为 `normal / debug`；Normal 可保存 bounded / redacted actual content，Debug 可在授权范围内保存完整或近完整的 model-visible / system-visible facts；两者都不保存 Chain-of-Thought、secrets 或越权数据。
8. Trace access / export 不扩大 Data Access Scope；SDK external tracing 保持关闭。
9. Retention 按 metadata、Normal payload、Debug payload、aggregate、Answer Artifact 与 canonical source 分层；Stage 1.9 不强制 Debug 更短，Answer Artifact 与 Canonical Source 不归 Trace Store 所有。
10. Trace Store 独立、append-only、versioned；reference 是稳定关联方式，Normal / Debug capture policy 决定允许内容的保存详细度，backend 选型 Pending。
11. Collector failure 显式产生 incomplete / operational failure，但不回滚成功业务结果。
12. Operational metrics 无阈值；Stage 1.10 已确认 Evaluation Dataset / quality metric / threshold / gate 的治理语义，具体 Case、数值与实现仍 Pending。

完整 rationale、Failure Case、Validation Contract、Deferred 与 Reopen Conditions 见 [Stage 1.9 Trace / Observability ADR](./technical-decisions/stage-1-9-trace-observability.md)。


## Stage 1.11: Application Boundary 与 Python 工程结构

### Responsibility

Stage 1.11 负责把 Stage 1.1–1.10 已确认的内部边界映射到 Python 工程的 package ownership、外部入口和生命周期。它不实现业务代码，也不重新设计前序 Stage 的内部执行语义。

### Confirmed Architecture

- v1 使用一个 Python distribution，package root 采用 `src/trivae`；内部按架构 ownership 划分 `config`、`bootstrap`、`data`、`retrieval`、`capabilities`、`query`、`conversation`、`observability`、`evaluation` 与 `interfaces` 等概念包。
- CLI 与 HTTP API 是薄 Interface Adapter；Evaluation 是独立评测子系统，但其进入共享 execution core 的 execution adapter 保持薄。三者都通过 Composition Root 获取同一 Application，并将各自输入转换为 Application-level `QueryRequest`。
- `TrivaeApplication` facade 包含 query、ingestion、conversations、evaluation、traces 与 lifecycle；Conversation、Import、Trace 等产品路径均通过对应 Application service 进入，不直接读取 Store。
- bootstrap 持有 Trivae Application Factory；interfaces/api 持有 HTTP ASGI / Server App Factory。core Application lifecycle 与 HTTP server lifecycle 分离，server 完成在途请求后再调用 application.close。
- Protocol input 不等于 trusted Application context；data_access_scope、特权 execution_overrides 与 trace_profile 必须由认证、本地授权策略或 Evaluation harness 派生，普通客户端不能自行扩权。
- `QueryOrchestrator` 是 Query 的唯一 Application entry，统一组织 Context → Router → 可选 Planner → Agent Runtime → Tool / Retrieval → Evidence / Citation → Finalization。
- Evaluation 通过显式 Controlled Variant、forced route 或 execution override 复用同一 Query execution core，不复制 eval-specific Router、Runtime、Tool 或 Retrieval 主链路；Case、Variant、Runner、Review、Comparison 与 Regression 仍属于 Evaluation 自身语义。
- CLI / API / Evaluation 共享 Settings、PathProvider、core Application lifecycle、request / trace correlation、canonical Error semantics 与 Normalized Event Projection；HTTP server lifecycle 单独由 HTTP interface / CLI serve 管理。
- OpenAI Agents SDK Event 只能经过 Runtime Adapter 转为 Trivae-owned Runtime Event；CLI / API / UI 与 Trace Collector 不直接依赖 SDK event 类型。
- HTTP 第一版保留 `/api/v1` 版本边界；查询 Streaming 优先使用 Normalized Event 的单向 SSE-like projection，不在当前阶段引入 WebSocket。
- Tool Surface、CLI Surface、HTTP API Surface 分开治理；Agent Tool 不自动成为公共命令或 endpoint。

### Dependency Direction

#### Runtime Call Flow

```text
CLI / HTTP / Evaluation execution adapter
  -> TrivaeApplication
  -> QueryOrchestrator
  -> Context / Router / Planner / Runtime
  -> Capability / Retrieval
  -> Data
```

这条箭头描述运行时调用顺序，不等价于 Python import 方向。所有产品路径先进入 TrivaeApplication 的对应 facade，再进入 application service。

#### Source Dependency Rule

```text
interfaces / evaluation adapters
  -> application / query contracts
  -> Trivae-owned business contracts

concrete infrastructure adapters
  -> Trivae-owned business contracts

bootstrap / composition root
  -> contracts + concrete implementations
```

Trivae-owned business contracts 不导入 SQLite、FastAPI、Typer 或具体 provider SDK；concrete infrastructure adapters 可以实现或依赖 Trivae-owned contracts；interfaces 依赖 Application facade，不直接读取 Store、Index 或 provider；bootstrap 可以组装契约和具体实现。本规则不新增 ports、adapters、domain、usecases 等层级。

具体 module file、class、依赖版本、Schema 与 DI 方式保持 Implementation Pending。

### Stage 1.11 Deferred

业务 package 尚未创建。`pyproject.toml`、Python / JSON / Database Schema、Typer / FastAPI / SSE / SDK 版本、create_application / create_http_app 实现、API wire schema、CLI 输出、Evaluation runner、trusted context 派生策略、真实 baseline、数值 threshold 与 lifecycle 参数仍属于 Implementation / Real-run Calibration Pending。

完整 rationale、Package Layout、Composition Root、Failure Cases、ChatLab 继承 / 适配 / 暂不继承与 Reopen Conditions 见 [Stage 1.11 Application Architecture ADR](./technical-decisions/stage-1-11-application-architecture.md)。

## Module Boundaries

### Router

**Responsibility**：作为轻量 execution-complexity classifier / Planner gate，判断当前请求是否值得在进入 Agent Runtime 前先经过 Planner。

**Does**：

- 接收 Runtime 注入的 User Query、Query Context、Compact Data Snapshot 与 Capability Summary。
- 根据任务结构与 Planning Value 将请求分为 `standard_execution` 或 `planned_execution`。
- 输出可 Trace / Evaluate 的 Route Decision：`route`、`confidence`、`reason`、`source`。
- 对 `planned_execution` 触发 Planner；两种 Route 最终都进入同一个 Agent Runtime。
- 在自身或 LLM Router 失败时，按已确认的可观测降级原则继续使用 Rule Decision 或 `standard_execution`。

**Does not**：

- 不区分 `direct_response` 与 `tool_assisted`，也不提前决定是否调用 Tool。
- 不决定 Lexical / Semantic / Hybrid Retrieval、SQL、Top-K、Rerank、关键词、filters 或具体 Tool 参数。
- 不生成多步 Plan，不决定 Evidence Requirements，不负责底层数据访问和证据选择。

结论：**Router 决定是否需要 Planning，Agent Runtime 决定当前怎么执行，Retrieval 决定怎样找数据。**

### Planner

**Responsibility**：作为 **Thin pre-execution investigation planner**，将复杂请求拆分为少量高层调查目标，为同一个 Agent Runtime 提供 soft execution / investigation guidance。

**Does**：

- 仅在 `planned_execution` 进入 Agent Runtime 前运行一次。
- 接收 Runtime 注入的 `user_query`、`query_context`、compact `data_snapshot` 与 `capability_summary`。
- 输出 outcome-oriented 的调查目标、阶段性问题、evidence requirement、advisory `suggested_tools` 与自然语言 `success_criteria`。
- 对 LLM Plan 执行 deterministic parse、structural validation、bounded sanitization 与 hallucinated Tool filtering。
- 在 Plan 有效时追加 soft Plan Guidance；在失败时让 Agent Runtime 无 Plan 继续执行。

**Does not**：

- 不拥有 Agent Loop、Step Executor、Planner Tool Calling 或 Planner-owned State Machine。
- 不编排底层 Tool 调用流程，不输出 Tool Arguments、Search Query、SQL、filters、top_k、rerank 或 Context Expansion 参数。
- 不选择实时 Retrieval Strategy，不执行 Evidence Selection / Citation。
- 不维护 Step Execution State，不 Retry，不 Automatic Replanning。
- 不把 `suggested_tools` 变成 Runtime 的 required tools；Agent 可以完全偏离 Plan。

Plan 的概念 Schema、失败类别与执行边界见 [Stage 1.6 Planner](#stage-16-planner)；Trace family 与 failure ownership 已由 Stage 1.9 确认，Python class、模型、Prompt、具体 bounds、事件序列化实现与 Evaluation runner / real-run calibration 仍 Pending（Evaluation contract 已由 Stage 1.10 确认）。

### Agent Runtime

**Responsibility**：作为 Single-agent execution runtime 承载查询执行循环（bounded Agent Loop），并在可用时参考 Planner guidance，继续拥有 Tool Selection 与执行自治。通用 Agent Loop 由 OpenAI Agents SDK 承载，Trivae 不自行重写通用 Loop。

- 通用 Agent Loop、Tool Execution、Streaming、Cancellation、Run Lifecycle 和基础 Tracing 优先复用成熟 Agent SDK（第一版：OpenAI Agents SDK）。
- Trivae 保留薄适配层（`Trivae AgentRuntime interface → OpenAIAgentsRuntimeAdapter → SDK`），负责 Trivae 领域契约与 SDK 之间的映射；业务代码不直接依赖 SDK 类型；未来替换 SDK 主要涉及 runtime / tools adapter。
- Runtime 决定是否调用 Tool、调用哪个 Tool、Tool 参数、Retrieval 组合、Search Query / SQL、Context 恢复、是否继续调查、何时停止，以及是否偏离 Plan。
- Planner failure、invalid Plan 或 unavailable Planner 不得阻断 Runtime；planned route 的 Router Decision 仍保留为已发生事实。
- Router、Planner、Retrieval、Evidence 等业务逻辑不下沉到 SDK，也不隐藏在 Runtime 适配层中。
- RuntimeContext（local，不发给 LLM）与 Agent Model Context（LLM-visible）分离；Data Access Scope 在 Tool / Capability 执行路径硬执行，不写进 system prompt 靠模型自觉。
- Trivae Conversation Store 是 Conversation History 的 source of truth，经 Context Compiler 生成 SDK-compatible items；SDK / Provider conversation state 只作可重建 adapter state；streaming、完成、中止与失败记录遵守明确提交边界。
- Tool Round 按一个包含 Tool Result 的模型轮次计数，同轮多个 Tool 仍为一轮；Trivae Budget 耗尽后 graceful final synthesis，SDK `max_turns` 为最终调用预留空间并仅作兜底。只有已知 Tool Contract Error 可恢复，未知 Tool / Adapter 异常显式 `FAILED`；Abort 采用协作式 cancellation，晚到结果不得重启执行；Streaming 为 canonical path（SDK StreamEvent → adapter → Trivae Runtime Event）。
- Runtime lifecycle 状态机为 `CONTEXT_PREPARING → ROUTING → (PLANNING) → AGENT_PREPARING → RUNNING → (FINALIZING) → COMPLETED`；任意阶段 `ABORTED` / `FAILED`；ROUTING / PLANNING 属于 Query 生命周期而非内部 Agent Loop。
- Trivae 配置显式关闭 SDK built-in external tracing，不依赖 SDK 默认值；`SDK Hooks / Stream Events → Trivae normalized runtime events → Normalized Query Event boundary → Trace Collector`。
- Stage 1.9 已确认 Runtime Event / Trace 的 conceptual envelope 与 ownership；具体 SDK 版本、Adapter 契约、参数数字、Python / JSON Schema 与 Trace 实现仍保持 Pending（见 [Stage 1.7 ADR](./technical-decisions/stage-1-7-agent-runtime.md) 与 [Stage 1.9 ADR](./technical-decisions/stage-1-9-trace-observability.md)）。

### Tool Layer

**Responsibility**：向 Agent 暴露少量、语义清晰、容易调用的工具，是 Query Plane 访问 Data Plane 的边界；同时隔离 Agent SDK 与底层业务实现，使 Retrieval、Context、Identity 等核心能力不依赖具体 Agent Runtime。

- Stage 1.4 已确认 Tool 与 Capability 分离：Capability 是项目自身的业务能力（不依赖 Agent Runtime），Tool 是面向 Agent 的调用接口，一个 Tool 可在内部组合多个 Capability。
- 第一版固定暴露 `lexical_search`、`semantic_search`、`get_message_context`、`find_members`、`get_schema`、`execute_sql`。
- Search（lexical / semantic）默认自动补充 bounded local context；内部 Retrieval 与 Context Expansion 仍保持独立可观测。深度调查通过稳定 `message_id` 调用 `get_message_context`，不引入 Candidate State。
- Data Access Scope 是 Agent Runtime 提供给 Tool Layer 的硬授权边界；所有 Tool（包括 `execute_sql`）都不得读取边界外数据，具体 enforcement 机制留给 Storage / Runtime Implementation。time range、member、keyword 等 Query Context / Query-specific Filters 不自动等同于权限边界，是否强制应用由 Tool Contract 与参数来源决定；第一版不提供 `get_scope_info`。Identity / Membership 查询使用 `find_members`，显式返回可能有歧义的候选。
- 第一版 structured / canonical persistent store 采用 SQLite；Structured Retrieval 直接使用 Physical SQLite Schema + bounded read-only SQL，不增加 Analysis View。Statement 必须被确认是 read-only；bounded 不要求 Agent SQL 自带 `LIMIT`，Tool-level execution boundary 的具体机制留给 Implementation；SQL 静默改写和执行失败后的 Retrieval 自动切换均被禁止。
- Tool 使用统一薄 Envelope，明确区分 zero hits / invalid arguments / capability unavailable / execution failure / partial / truncated；Truncation 与 Partial Execution 是不同概念。
- Agent 不直接读取原始文件、Canonical Store 或索引。
- 第一版不暴露 `hybrid_search`、`universal_search`、`retrieve_evidence` 或大量 Specialized Analysis Tools；新增能力由真实 Evaluation 或 Failure Case 驱动。

### Retrieval

**Responsibility**：根据查询和约束从数据底座召回候选信息，并支持后续分析。

- Retrieval 是 Trivae 的业务核心之一。
- Retrieval Result 与 Evidence 分离：召回候选不等同于最终引用证据。
- Stage 1.3 已确认：Retrieval 由 Retrieval Composition、三个 Retrieval Primitives（Structured / Lexical / Semantic）与 Post-Retrieval Operator（Context Expansion）组成；Hybrid 是组合策略而非底层搜索引擎；Semantic 第一版 primary indexing unit 为 Conversation Chunk（Time-aware Parent + Small Child）；Retrieval Strategy 由任务决定，不默认所有查询执行固定 Hybrid Pipeline；Retrieval Result 的 provenance 与 Partial / Coverage 必须显式暴露。
- Stage 1.9 已确认 Retrieval Trace family、query-scope coverage 与 Failure Attribution 语义；具体 Python / JSON Schema 与采集实现 Pending。仍未确定：Reranker、Fusion 权重、Chunk 具体参数、merge / dedup / candidate selection 的具体算法、Message-level 辅助语义索引（Pending Evaluation）；Vector Store、Embedding 模型、Indexing Pipeline 具体实现（Pending architecture specification）。

概念边界保持为：

```text
Retrieval Query
    -> Retrieval Candidates / Results
    -> Evidence Selection / Organization
    -> Final Evidence
    -> Citation-bound Answer
```

### Evidence

**Responsibility**：将检索和分析结果组织成可支撑回答结论的证据，并连接原始聊天消息与最终引用。

- Evidence 是 Trivae 的业务核心之一。
- Retrieval / Tool 只提供 Candidate Data、Structured Result、current-run provenance 与 execution completeness；Agent Final Synthesis 依据 question-specific criterion 选择 Final Evidence，并按 claim / finding 组织 Evidence Item。
- 一个 Evidence Item 可以包含多条 Source；每条 Source 相对 finding 的关系为 `supports / contradicts / context`。Evidence Item 的 sufficiency 为 `sufficient / partial / insufficient`，不引入未经校准的数值 confidence。
- Tool 的 `partial / coverage / truncated / unavailable` 是 Retrieval / execution completeness，必须保留为 limitation；它与 Evidence sufficiency 是独立维度。
- Message Source 同时保留 current-run Tool provenance、`session_id + internal message_id`（可选 Message Range）定位与生成时可信展示快照。快照包括 ChatSession 可读标识、作者、精确 Canonical Timestamp（含明确 timezone / offset 语义）和未经 LLM 改写的安全 excerpt。
- Semantic Chunk、embedding score 与 snippet 只作 acquisition provenance；最终 Source 必须解析到 Canonical Message / Message Range。显示编号、Chunk 和 snippet 均不是 source identity。
- Structured Result Source 独立保留 Tool Call / Result identity、结果位置、value snapshot、query scope snapshot 与 execution limitations，不伪装成 Message Source。具体 row / value locator 序列化保持 Implementation Pending。
- Planner 的 `evidence_needed` 仍只是调查需求；第一版不新增 `retrieve_evidence` Tool、Evidence Agent、固定关键词 Judge、固定时间聚类或 Runtime-owned Evidence State Machine。

### Answer Generation

**Responsibility**：基于 Final Evidence 生成 Citation-bound Answer，并在提交前形成可确定性验证的 Answer Artifact。

- Answer Artifact 在语义上包含 Answer Content、Claim Citation Bindings、Evidence Items 与 limitations；这是 conceptual contract，不冻结 Python / JSON Schema。
- 来自聊天记录、统计或数据库概览的实质性事实与推断必须使用 claim-level Citation；一般性解释、交互性文字与明确标为建议的方法内容不强制引用。
- Citation 将 claim / content unit 绑定到一个或多个 Evidence Item。正文 `[1]` 等显示编号与可展开 Evidence Panel 共用同一份结构化 Evidence，编号不构成来源身份。
- Citation Validator / Finalizer 确定性验证 Evidence ID、current-run Tool provenance、Source locator、Session / Message 一致性、Structured Result 位置与 Data Access Scope，并从可信 Tool Result / Canonical projection hydrate 会话、作者、精确时间与 excerpt。
- Validator 不证明自然语言 claim 与 Source 的语义蕴含，也不判断 criterion 是否最佳或 Retrieval 是否召回全部来源；这些质量问题属于 Stage 1.10 Evaluation。
- invalid / unresolved Citation 显式使 Answer Finalization 失败；不 silent drop、不提交无引用版本、不自动替换来源或增加无依据 repair / retry。
- 只有验证通过的 Answer Artifact 才随最终 Assistant Message 按 Stage 1.7 `COMPLETED` 边界提交。历史 Evidence 可回放，但后续事实问题必须重新通过当前数据库 Tool 取得 fresh evidence。
- 点击 Message Citation 后，应用以被引消息为中心展示 bounded、未经 LLM 改写的 Canonical context；全量聊天留给原社交平台。平台不支持 deep link 时仍展示会话、作者和精确时间等人工 Source Locator。
- Evidence-aware stopping 第一版只作 Agent guidance：主要 finding 达到 sufficient 时可自然结束；Tool Budget 耗尽后只基于已取得来源 final synthesis 并显式标记 partial / insufficient。machine-enforced gate 与参数留给 Stage 1.10。
- Prompt、模型、Claim binding 序列化、Structured Result locator、bounded context 数量和具体 UI 组件保持 Pending。

完整 rationale、Failure Case、ChatLab 继承 / 偏离与 Reopen Conditions 见 [Stage 1.8 Evidence / Citation ADR](./technical-decisions/stage-1-8-evidence-citation.md)。

## Cross-Cutting Concerns

### Observability / Trace

Observability 与 Trace 横切 Query Plane，目标是支持 Failure Attribution。Stage 1.9 已确认：Router、Planner、Runtime、Tool、Retrieval、Evidence、Citation 与 Answer commit 共用 Trivae-owned normalized event boundary；Stream Projection 与 recordable Trace Projection 从同一语义边界派生。

Trace 使用 versioned append-only event、单 Trace sequence 与 operation causality 保存事实。Failure Attribution 区分 origin、observation、handling 和 terminal outcome；恢复 / degradation 不抹掉原始 failure。Error Code 由 contract owner namespace 拥有，Wrapper 不改名覆盖根因。

Retrieval coverage 按 `requested query scope ∩ Data Access Scope` 后的 effective scope 表达；`complete / partial / none / unknown / not_applicable`、truncated、unavailable、Tool status 与 Evidence sufficiency 分轴保留。没有可靠 denominator 时必须是 `unknown`，不能用全局 coverage 或估算百分比伪装当前查询完整性。

Trace 使用 `normal / debug` 两个显式 Profile：Normal 以结构化事实和 bounded / redacted actual content 为主，Debug 在本次 Run 的 Data Access Scope 内允许完整或近完整记录 model-visible / system-visible execution facts。任何 Profile 都排除 Chain-of-Thought、secrets 与越权数据；读取与外部导出不得扩大 Data Access Scope。Trace Store 独立、append-only、versioned，retention 按 metadata / Normal payload / Debug payload / aggregate / Answer Artifact / canonical source 分层；Stage 1.9 不强制 Debug 比 Normal 更短，具体 backend、Schema、时长与部署实现仍 Pending。

Trace failure 不回滚成功业务结果，但必须显式暴露并将 Trace 标为 incomplete。完整事件 family、storage / privacy 原则、Failure Case 与 Reopen Conditions 见 [Stage 1.9 ADR](./technical-decisions/stage-1-9-trace-observability.md)。

### Evaluation / Regression

Evaluation 与 Regression 横切 Data Plane 和 Query Plane：

- 端到端以 Evaluation Case Bundle 为 canonical truth，绑定 Dataset Snapshot、Data Access Scope、Reference Findings / Evidence 与 Review Policy。
- Reference 必须针对具体 Finding 表达 `exhaustive / partial / unknown` completeness 与 provenance；不使用唯一答案文本，也不把 partial / unknown Finding 外的真实 Evidence 机械判错。Case 级完整度只能是 Finding 状态的派生摘要。
- Design Seed、Core、Failure Regression 与 Calibration Slice 分层；Core 通过 versioned Suite 刷新并保留历史 composition / results。
- Baseline 必须是 pinned Controlled Variant，Candidate 通过显式 diff；相同 Case 先做 forced standard / forced planned 的 Planner Utility，再评价 Router Utility。
- quality、diagnosability、module diagnostics、latency、Token、Tool Call 与 cost 分轴报告；质量比较优先 blind、随机 A/B、同 rubric、同 Evidence visibility，不合成单一总分。
- 重要 Failure Case 提升为 versioned Regression Case；Failure Diagnosis 只能引用 Stage 1.9 canonical Trace，不能改写 Trace。

Case authoring、Snapshot / Dataset 构建、runner、具体 Schema、真实 stable baseline、重复次数、统计方法、numerical threshold 与参数校准仍为 Stage 1.10 Implementation / Real-run Calibration Pending；CLI / API / UI 的具体触发、结果展示与交互承接 Stage 1.11 ADR，但实现仍 Pending。完整 rationale、11 个 Trivae-specific Design Seed 与 ChatLab 继承 / 偏离见 [Stage 1.10 ADR](./technical-decisions/stage-1-10-evaluation.md)。

### Stage 1.10: Evaluation / Regression

本阶段确认的是评测事实与治理契约，不是评测产品或执行器。架构主链路为：

```text
Evaluation Suite
  → Case Bundle (Snapshot + Scope + Query + Reference + Review Policy)
  → pinned Controlled Variant
  → Evaluation Run (Answer + Trace reference + checks + operational facts)
  → Review (deterministic / human / model-assisted)
  → blind paired Comparison
  → Failure Diagnosis
  → versioned Failure Regression Set
```

#### Case、Reference 与 Suite

- Case Bundle 是所有端到端与模块诊断的共同事实源；纯模块 Fixture 不能冒充端到端质量 Case。
- Reference 按 Finding 组织：每个 Finding 有自己的 criterion、Evidence、relation、annotation completeness（`exhaustive / partial / unknown`）和 provenance；同一 Case 允许不同 Finding 使用不同完整度，Case 级摘要不得覆盖 Finding 级语义。
- `route_hypothesis` 是可选诊断信息，不是必须填写的 `expectedRoute`；没有明显 Planner 收益的 Case 可以不标注路径。
- Core Set 要随真实 workload 和新 Failure 通过新 Suite version 演进，历史清单与结果不可被覆盖；Seed 不产生 Gate。

#### Baseline、Planner Utility 与 Router Utility

- Baseline 是 pinned 的完整 Controlled Variant；`last_stable`、`minimal_control` 与 `chatlab_derived_seed` 用途分开，Candidate 必须显式声明 diff。
- Planner Utility 采用强制路径：同一 Case 分别走 `Case → Agent Runtime` 与 `Case → Planner → Agent Runtime`；除 Planner 是否介入及其 guidance 外，Runtime、Model、Prompt、Tool、Retrieval、Evidence、Budget、Snapshot、Scope 与运行条件必须相同；先比较质量 / 成本，再恢复 Router。
- Router Utility 只评价 Router 是否把“当前 Planner 确实有收益”的 Case 送入 planned path，不能用 Aggregate Route Accuracy 替代。

#### Review、随机性与治理

- deterministic checks 先行；人工负责 Ground Truth、争议 Case、关键 Gate 与 Judge 校准；model-assisted Judge 不是唯一真相源。
- Baseline / Candidate 质量比较隐藏身份、随机 A/B 顺序、使用同一 rubric 与 Evidence visibility；先做质量判断，再合并成本指标。
- stochastic path 保留重复 Run、分布和不可用原因；可复现承诺是输入 / Snapshot / Scope / Variant / 条件可重建并可统计比较，不是远程模型 bit-for-bit 重放。

#### Hard Contract 与 Deferred

- 当前确认 Scope violation、越权或 invalid / unresolved Citation、已修复 critical Regression 复发、以及无证据 Root Cause 声明均不可接受。
- numerical threshold、重复次数、真实 stable baseline、Schema、runner、Judge workflow、参数和 machine-enforced stopping 留给 Implementation / Real-run Calibration；删除和权限变化优先于复现便利。

完整 Decision Set、Failure Case、Reopen Conditions 与 T-EVAL-001–011 见 [Stage 1.10 Evaluation ADR](./technical-decisions/stage-1-10-evaluation.md)。

## Confirmed Decisions

以下按阶段汇总当前已确认的架构方向：

1. **Two-plane architecture**：系统一级划分为 Data Plane 与 Query Plane。
2. **Data / Agent decoupling**：Data Plane 不包含 Agent；Agent 只能通过 Tool Layer 访问数据能力。
3. **Query main chain**：Query Plane 的主链路为 `Router → standard_execution | planned_execution → [Planner for planned path] → Agent Runtime ↔ Tools → Retrieval / Structured Result → Evidence Selection / Organization → Final Evidence → Citation-bound Answer`。
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

### Stage 1.3：Retrieval Architecture

1. **Multi-strategy Retrieval**：Retrieval 由 Retrieval Composition、三个 Retrieval Primitives（Structured / Lexical / Semantic）与 Post-Retrieval Operator（Context Expansion）组成；Context Expansion 与前三个不在同一层，`retrieve` 与 `expand context` 是两个动作。
2. **Hybrid 是组合策略**：Hybrid 属于 Retrieval Composition 层，不单独成为底层搜索引擎，不演化出"什么问题都往里面塞"的 `hybrid_search()`。
3. **集合确定后的确定性查询优先**：当目标数据集合可由结构化条件确定时优先使用 Structured Retrieval；集合本身需要语义判断时先经 Lexical / Semantic 确定候选集合再做确定性聚合；LLM 负责解释结果，不负责数数。
4. **Semantic 第一版 primary indexing unit 为 Conversation Chunk**：默认不建立逐 Message 向量索引；采用 Time-aware Parent + Small Child 架构，命中 Child → 定位所属 Parent → Context Expansion。若 Evaluation 证明 Message-level retrieval 对特定 Failure Case 有价值，再作为辅助索引引入（Pending Evaluation）。
5. **Query-specific strategy**：Retrieval Strategy 由任务决定，不默认所有查询执行固定 Hybrid Pipeline。
6. **Retrieval Result provenance 保留**：Retrieval Result 分 Message Candidates（lexical / semantic）与 Structured Results（scalar / aggregate / records），共同保留 provenance 与 trace metadata；不把所有结果压成单一 Candidate 类型。
7. **Partial / Coverage 显式暴露**：不能"搜不到 = 不存在"；Stage 1.9 已将 coverage 细化为基于授权 effective scope 的 query-scope coverage，并与 partial / truncated / unavailable 分轴表达。
8. **Reranker 与 Fusion 权重不提前设计**：先建立 baseline，出现 Failure Case 并证明排序问题后再评估；Chunk 具体参数同样保持 Tunable。
9. **Evidence 判断不在 Retrieval 层硬编码**：不复制 ChatLab 固定关键词判断 Evidence Status 的方案；Stage 1.8 已确认由 Final Synthesis 使用 question-specific criterion 选择和组织 Final Evidence。
10. **Retrieval Trace 纳入全链路 normalized event**：记录 query / strategy / filters / lexical / semantic / context_expansion / final_candidates 及 query-scope coverage；Stage 1.9 已确认 envelope、Failure Attribution 与 storage 原则，具体 Python / JSON Schema 和实现保持 Pending。

详细 rationale 与 trade-off 见 [technical-decisions/stage-1-3-retrieval-architecture.md](./technical-decisions/stage-1-3-retrieval-architecture.md)。

### Stage 1.4：Tool / Capability Layer

1. **Tool / Capability 分离**：Capability 是项目自身的业务能力且不依赖 Agent Runtime；Tool 是面向 Agent 的调用接口，负责参数验证 → 调用一个或多个 Capability → 标准化返回结果。
2. **一个 Tool 可组合多个 Capability**：Agent-facing API 允许合并高频步骤，不把每个内部步骤都暴露成独立 Tool；Tool Surface 优先 Agent 易用性。
3. **Message Search 默认自动补充 bounded local context**：仅指 Lexical / Semantic 这类面向消息候选的 Search Tool；Local context 是 Search Result 的默认组成部分；自动扩展必须 bounded，避免一次性还原完整讨论。不推广到 Structured Retrieval 等返回聚合 / 标量结果的能力。
4. **内部 Capability 保持独立可观测**：Retrieval 与 Context Expansion 仍是两个独立能力；一次 Tool Call 内部可区分"没召回 / 召回但上下文范围不合适 / 上下文正确但 Agent 分析错误"。
5. **Semantic Search 采用同样原则**：默认自动 bounded context recovery，返回结果保留 provenance（matched chunk / score / message range / context）。
6. **不把大上下文窗口作为主要设计依据**：仍需考虑 token / latency / 噪声 / 注意力稀释 / 一次返回过多结果。
7. **参数不写死，由 Evaluation 决定**：只冻结"Message Search 默认带 bounded local context"，具体窗口参数（消息数 / token / 时间跨度 / reply chain / conversation parent）Evaluation 校准。
8. **禁止 silent fallback**：Tool 可以组合 Capability，但不能隐藏执行状态；需明确区分 zero hits / capability unavailable / invalid arguments / execution failure / partial / truncated。
9. **第一版 Tool Surface 固定为 6 个 Tool**：`lexical_search`、`semantic_search`、`get_message_context`、`find_members`、`get_schema`、`execute_sql`；新增 Tool 由真实 Evaluation 或 Failure Case 驱动。
10. **深度 Context 通过稳定 Message Identity 恢复**：保留 `get_message_context(message_id)`；第一版不采用 `candidate_ref / Candidate State`。
11. **区分 Data Access Scope 与 Query-specific Filters**：Data Access Scope 是所有 Tool（包括 `execute_sql`）都不得越过的硬授权边界；time range、member、keyword 等 Query Context / Query-specific Filters 不自动等同于权限边界，是否强制应用由 Tool Contract 与参数来源决定；不提供 `get_scope_info`，Data Access Scope 的具体 enforcement 机制后续确定。
12. **Member Lookup 返回候选**：使用 `find_members`，保留身份歧义与匹配依据，不使用暗示唯一解析的 `resolve_member`。
13. **第一版持久化与 Structured Retrieval 采用 SQLite**：structured / canonical persistent store 为 SQLite；`get_schema` 读取真实 Schema，`execute_sql` 执行 bounded read-only SQL；第一版不增加 Analysis View。
14. **SQL 错误透明且 bounded**：statement 必须确认 read-only，非只读关键字列表仅为示例；不要求 Agent SQL 自带 `LIMIT`，Tool 可通过不修改 SQL 文本语义的 execution boundary 限制返回规模并显式暴露 Truncation，具体机制 Pending Implementation；不 silently 改写 SQL，不在执行失败后自动切换 Retrieval；SQL 不承担 Semantic Classification。
15. **Search Result 保留检索差异**：Lexical / Semantic 共享统一外层语义结构，同时保留 strategy-specific provenance；numeric score 必须说明 `score_type`，Context Message 保留稳定结构化身份；不冻结实现 Schema。
16. **统一 Tool Result Envelope 语义**：使用 `ok / partial / error`；Zero Hits 是正常结果；Invalid Argument、Capability Unavailable、Execution Error 可区分；Truncation 与 Partial Execution 分离；不冻结实现 Schema。
17. **第一版不暴露万能或大量专用 Tool**：不增加 `hybrid_search`、`universal_search`、`retrieve_evidence` 或大量 Specialized Analysis Tools。

详细 rationale 与 trade-off 见 [technical-decisions/stage-1-4-tool-capability-layer.md](./technical-decisions/stage-1-4-tool-capability-layer.md)。

### Stage 1.5：Router

1. **Router 是 execution-complexity classifier / Planner gate**：只判断当前请求是否值得在进入 Agent Runtime 前先经过 Planner。
2. **两路 Route taxonomy**：Trivae 只保留 `standard_execution` 与 `planned_execution`；ChatLab 的 `direct_response` 与 `tool_assisted` 不作为 Trivae 独立 Route。
3. **同一个 Agent Runtime**：两种 Route 最终都进入同一个 Agent Runtime；只有 `planned_execution` 额外经过 Planner。
4. **Planner 是 soft guidance**：Planner 不接管 Agent Loop，不生成必须机械执行的 Workflow；Stage 1.6 已确认 Planner Contract 的概念边界，具体实现仍 Pending。
5. **任务结构优先**：Route 判断关注 Multi-goal、Dependency、Temporal reasoning、Evidence dependency / cross-stage validation、Dependent semantic investigation、Recovery 等 Planning Value 维度；多条 Evidence、Semantic Synthesis、长时间范围、跨群或 Tool Call 数量本身不决定 Route。
6. **Rule-first + LLM fallback**：明显请求由规则处理，ambiguous case 才使用 LLM Router；具体规则、模型、prompt、timeout 与阈值保持 Pending。
7. **Conservative default**：无法明确证明 Planner 有价值时使用 `standard_execution`；Planner invocation must earn its invocation。
8. **Router failure graceful degradation**：Router 是 execution optimization layer，不是 request availability dependency；失败时使用可用 Rule Decision，否则保守降级到 `standard_execution`，并保留可诊断信息。
9. **Runtime 注入 Router Context**：Router 使用 User Query、Query Context、Compact Data Snapshot、Capability Summary；不通过普通业务 Tool 查询 Chat Metadata / Scope / Data Availability，不接收大量聊天正文。
10. **Route Decision 可 Trace / Evaluate**：语义字段为 `route`、`confidence`、`reason`、`source`；`reason` 不承载 Chain-of-Thought。
11. **Router 不越界**：不选择 Tool、Lexical / Semantic / Hybrid Retrieval、SQL、filters、Top-K、Rerank、Plan Steps 或 Evidence Requirements。

### Stage 1.6：Planner

1. **Thin pre-execution Planner**：Planner 仅在 planned_execution 路径进入 Agent Runtime 前执行一次，不拥有 Agent Loop、Step Executor 或 Tool Calling。
2. **Same Agent Runtime**：standard_execution 与 planned_execution 最终进入同一个 Agent Runtime。
3. **Soft guidance**：Plan 是 investigation guidance，不是 mandatory workflow；Runtime 可以根据实际证据和 Tool Result 偏离。
4. **Runtime-injected Planner Input**：PlannerInput 概念上为 user_query、query_context、data_snapshot、capability_summary。
5. **Contextualized request**：user_query 必须足够表达当前会话语义；history window、summarization、compression 与 token limit 保持 Pending。
6. **Query Context / Data Access Scope 分离**：query_context 是查询条件，Data Access Scope 仍是 Tool Layer 的硬授权边界。
7. **Compact Data Snapshot**：主要表达 coverage、scale、availability 与 basic environment metadata；更多 analytical hints Pending Evaluation。
8. **Capability Summary**：提供 6 个 Tool / Capability 的 purpose、重要 constraint 与 availability，不复制完整 Tool Manual。
9. **Planner Input exclusions**：不注入 Router diagnostic reason、大量聊天正文、Retrieval Result、Tool Result、Agent intermediate state、Evidence Object 或 Citation State。
10. **Lightweight Plan Schema**：概念字段为 version、title、intent、steps[].goal、steps[].suggested_tools、steps[].evidence_needed、success_criteria。
11. **Intent is descriptive metadata**：保留 ChatLab taxonomy summary / trend / relationship / search / comparison / evidence / mixed，不绑定 Route、Tool 或 Retrieval。
12. **Outcome-oriented Plan Step**：goal 描述调查问题或认知结果，不描述 Tool Invocation。
13. **suggested_tools is advisory**：只是 capability hint，Runtime 不受约束，Planner 不生成 Tool Arguments。
14. **evidence_needed is requirement**：描述所需证据类型，不定义 Stage 1.8 Evidence Object、Status 或 Citation。
15. **Soft success criteria**：success_criteria 是自然语言完成指导，不是 machine-enforced hard predicate。
16. **No workflow fields / execution state**：不增加 step_id、depends_on、condition、branch、status、retry、fallback、Tool Arguments 等字段；Planner 不拥有 state machine。
17. **No automatic replanning**：Planner 只运行一次，Runtime 自主偏离或调整。
18. **Deterministic validation**：LLM 输出必须经过 parse、structural validation、bounded sanitization 后才能注入 Runtime。
19. **Hallucinated Tool filtering**：不存在或不可用的 suggested Tool 被过滤，不使整个 Plan 失败；所有建议被过滤时，合法 Step 仍可保留。
20. **Bounded Plan / no LLM validator**：Plan 必须 bounded；具体 limit Pending Evaluation / Implementation，Plan Quality 留给 Stage 1.10，不增加第二个 LLM Validator。
21. **Planner failure graceful degradation**：Planner failure、timeout、invalid output、unavailable、aborted 等不阻塞可用 Agent Runtime；不重试、不再生成、不重写原 Router Decision。

详细 rationale 与 trade-off 见 [technical-decisions/stage-1-6-planner.md](./technical-decisions/stage-1-6-planner.md)。

### Stage 1.7：Agent Runtime

1. **Thin Agent Runtime + SDK 承载通用 Loop**：继承 ChatLab 的 Thin Agent Core 架构；通用 Agent Loop 由 OpenAI Agents SDK 承载，Trivae 不自行重写通用 Loop。
2. **Single Agent（v1）**：第一版单 Agent，不引入 handoff / multi-agent。
3. **Same Runtime both routes**：`standard_execution` 与 `planned_execution` 使用完全相同的 Agent Runtime。
4. **SDK 选型 OpenAI Agents SDK + 薄适配层**：`Trivae AgentRuntime interface → OpenAIAgentsRuntimeAdapter → SDK`；业务代码不直接依赖 SDK 类型；替换面为 runtime / tools adapter。
5. **Runtime 职责边界**：Runtime 不重新吞掉 Router / Planner / Retrieval / Evidence；只负责 bounded Agent Loop、streaming、cancellation、termination、result boundary。
6. **Orchestrator / Runtime 区分**：Request Orchestrator 负责整个 Query 生命周期；Agent Runtime 从 Agent Loop 启动开始负责执行核心；第一版 Orchestrator 可为 service/function。
7. **RuntimeContext 与 Agent Model Context 分离**：RuntimeContext（local，不发给 LLM）与 Agent Model Context（LLM-visible）是两个边界；Data Access Scope 在 Tool / Capability 执行路径硬执行，不写进 system prompt 靠模型自觉。
8. **Conversation History 归 Trivae**：Trivae Conversation Store 是 source of truth；SDK Session / Provider Conversation 只作可重建 adapter state；streaming、完成、中止与失败记录有明确提交边界。
9. **Pre-run Context 压缩**：压缩发生在 Agent Runtime 之前；v1 不做 mid-run compaction。
10. **终止条件两层**：Tool Round 按一个包含 Tool Result 的模型轮次计数；Trivae Budget 先触发 graceful final synthesis，SDK `max_turns` 必须预留最终模型调用并仅作 absolute backstop。
11. **Tool Error / Runtime Failure 分界**：仅已知 Tool Contract Error 以结构化错误交给 Agent 恢复；未知 Tool / Adapter 异常显式 `FAILED`，不能由 SDK generic error handler 吞掉。
12. **Abort = terminal intent**：v1 immediate 接受终止意图并协作式传播 cancellation；`ABORTED` 不执行 final synthesis，晚到 Tool Result 不得重启执行；`COMPLETED` 以 SDK Run 真正完成为准。
13. **Streaming canonical path**：`SDK StreamEvent → adapter → Trivae Runtime Event → CLI / API / UI`；禁止直接返回 SDK StreamEvent。
14. **Runtime lifecycle 状态机**：`CONTEXT_PREPARING → ROUTING → (PLANNING) → AGENT_PREPARING → RUNNING → (FINALIZING) → COMPLETED`；任意阶段 `ABORTED` / `FAILED`；ROUTING / PLANNING 属于 Query 生命周期。
15. **Planner soft guidance 注入**：`Validated Plan → Plan Guidance Renderer → LLM-visible soft instructions → Agent Runtime`；Runtime 不读取 plan.steps 逐条执行。
16. **SDK built-in Trace 不当正式 Trace**：Trivae 显式关闭 SDK external tracing，不依赖 SDK 默认值；`SDK Hooks / Stream Events → Trivae normalized runtime events → Normalized Query Event boundary → Trace Collector`。
17. **ChatLab 经验参数可直接继承**：作为 v1 baseline 直接继承，标注继承来源，保留 Evaluation 校准路径；不无条件照抄，也不拒绝继承。
18. **明确不引入**：手写通用 Loop、Multi-Agent、Handoff、Planner Agent Loop、Step Executor、Workflow Engine、Replanning、Runtime-owned Evidence State Machine、SDK Session canonical、SDK 类型泄漏、mid-run 压缩、应用级 retry / fallback、自定义 Tool orchestration scheduler、硬编码 Retrieval workflow。

详细 rationale 与 trade-off 见 [technical-decisions/stage-1-7-agent-runtime.md](./technical-decisions/stage-1-7-agent-runtime.md)。

### Stage 1.8：Evidence / Citation

1. **主链路**：`Retrieval / Structured Result → Evidence Selection / Organization → Final Evidence → Citation-bound Answer`。
2. **单一 Answer Artifact**：正文 claim-level Citation 与 Evidence Panel 共用同一份结构化 Evidence；显示编号不是 source identity。
3. **Finding-oriented Evidence**：Evidence Item 按 claim / finding 组织，可包含多条 Source；relation 为 `supports / contradicts / context`。
4. **Message Source**：current-run Tool provenance、显式 `session_id + internal message_id` locator 与可信人工复核 snapshot 缺一不可；Semantic Chunk 只作 acquisition provenance。
5. **Structured Result Source**：通过当前 Tool Result identity 与结果位置定位，保存 value / query scope snapshot，不伪装成 Message Source。
6. **Question-specific criterion**：criterion 与 Evidence Item 持久化；Planner `evidence_needed` 仍只是 requirement，不是 Evidence Object。
7. **双轴状态**：Evidence sufficiency 使用 `sufficient / partial / insufficient`；Tool `partial / coverage / truncated / unavailable` 作为独立 limitations 保留。
8. **Deterministic validation**：Citation Finalizer 检查 ID、current-run provenance、locator、Data Access Scope 与可信 metadata hydration；不声称验证 semantic entailment。
9. **Failure transparency**：invalid / unresolved Citation 使 Answer Finalization 失败；不 silent drop、不自动替换来源或 repair / retry。
10. **Persistence / replay**：validated Answer Artifact 随 Assistant Message 提交；旧 Evidence 只记录当时依据，后续事实问题重新调用当前数据库 Tool。
11. **Bounded source review**：应用内展示被引消息与有限原始上下文；全量聊天由原社交平台承载，deep link 不可用时展示人工 locator。
12. **Evidence-aware stopping**：第一版仅作 Agent guidance；Tool Budget 仍是 hard bound，machine-enforced gate 留给 Stage 1.10。
13. **明确不引入**：`retrieve_evidence` Tool、Evidence Agent、固定关键词 Judge、固定时间 Evidence Group、Runtime-owned Evidence State Machine 或无依据 citation retry / fallback。

详细 rationale、ChatLab 代码证据与 Reopen Conditions 见 [technical-decisions/stage-1-8-evidence-citation.md](./technical-decisions/stage-1-8-evidence-citation.md)。

### Stage 1.9：Trace / Observability

1. **Trivae-owned normalized event boundary**：完整 Query Execution 使用统一语义边界；Runtime Event 是其中一个 family，SDK raw event 不泄漏到产品或 Trace contract。
2. **Stream / Trace projection 分离**：CLI / API / UI 与 Trace Collector 从同一语义事件派生不同投影，采用各自的数据最小化策略。
3. **Version / identity / causality / sequence**：Conceptual envelope 表达 schema version、event / trace / request identity、单 Trace sequence、stage / operation / phase 与 parent operation。
4. **Append-only facts**：事件是 Trace source of truth；timeline、状态与 metrics 是可重建 projection；缺少 terminal event 时标记 incomplete。
5. **Failure Attribution**：区分 origin stage、observed stage、handling 与 Query terminal outcome；恢复 / degradation 不抹掉原始 failure。
6. **Error Code ownership**：稳定 owner namespace 拥有 error semantics；跨层传播不改名，Query wrapper 不覆盖 underlying root code。
7. **Query-scope coverage**：基于 `requested scope ∩ Data Access Scope` 后的 effective scope；索引缺口不能缩小 denominator，只有口径可靠时才给 ratio。
8. **Coverage states / orthogonal axes**：`complete / partial / none / unknown / not_applicable` 与 truncated、unavailable、Tool status、Evidence sufficiency 分轴。
9. **No online quality guess**：Trace 保存运行事实，不自动确诊需要人工复核或 Stage 1.10 Evaluation 的 quality Root Cause。
10. **Privacy by profile**：Normal 以结构化事实和 bounded / redacted actual content 为主；Debug 在当前 Data Access Scope 与 capture policy 允许时可保存完整或近完整的 model-visible / system-visible facts。两者都不记录 Chain-of-Thought、provider hidden reasoning、secrets 或越权数据。
11. **Retention / access boundaries**：Trace 不扩大 Data Access Scope；metadata、Normal payload、Debug payload、aggregate、Answer Artifact 与 canonical source 分层保留，且 Stage 1.9 不强制 Debug 比 Normal 更短。
12. **Independent Trace Store**：append-only、versioned；reference 是稳定关联方式，但不再作为唯一内容保存形态；backend 与实现 Pending；Trace failure 显式产生 incomplete，但不回滚成功业务结果。
13. **Operational metrics only**：Stage 1.9 只确认无阈值运行维度；Stage 1.10 负责 Evaluation 的 Case、质量轴、比较和 Gate 治理，具体实现与数值校准另行 Pending。

详细 rationale、Failure Case 与 Reopen Conditions 见 [technical-decisions/stage-1-9-trace-observability.md](./technical-decisions/stage-1-9-trace-observability.md)。

### Stage 1.10：Evaluation / Regression

1. **Case Bundle canonical truth**：端到端 Case 绑定 Dataset Snapshot、Data Access Scope、Query、Reference Findings / Evidence、uncertainty constraints 与 Review Policy；模块评测从同一 Case 派生。
2. **Finding-level Reference completeness / provenance**：Reference 不使用唯一答案文本；每个 Finding 的完整度为 `exhaustive / partial / unknown`，并保存建立流程、时间、Scope、adjudication 与限制；Case 级完整度只能由 Finding 状态派生。
3. **Versioned Suite**：Design Seed、Core、Failure Regression 与 Calibration Slice 分层；Core 通过新 Suite version 刷新，历史 composition / result 不覆盖。
4. **Pinned Controlled Variant**：Baseline 是完整、稳定、可定位的 Controlled Variant；Candidate 必须声明显式 diff；ChatLab-derived seed 不自动是 stable baseline。
5. **Forced Planner Utility**：同一 Case 先比较 `Case → Agent Runtime` 与 `Case → Planner → Agent Runtime`；除 Planner 是否介入及其 guidance 外，其余 Runtime、Model、Prompt、Tool、Retrieval、Evidence、Budget、Snapshot、Scope 与运行条件必须相同，再恢复 Router 判断 Router Utility。
6. **Layered quality / diagnostics**：Finding Correctness、Evidence Completeness、Groundedness、Uncertainty Calibration、Relevance 与 Trace / retrieval / runtime / citation / cost diagnostics 分轴，不合成单一总分。
7. **Blind paired review**：Baseline / Candidate 质量判断隐藏身份、随机 A/B 顺序、使用同一 rubric / Evidence visibility，先质量、后成本；Judge 不成为唯一真相源。
8. **Stochastic comparison**：固定 Case / Snapshot / Scope / Variant 条件并保留重复 Run、分布和 provider / permission / Trace 不可用原因。
9. **Failure Diagnosis boundary**：Diagnosis 只能关联 Stage 1.9 canonical Trace，不改写 Trace；修复后的真实 Failure 提升为 versioned Regression Case。
10. **Governed reproducibility**：保证输入、Dataset、Scope、Variant 与条件可重建并可统计比较，不承诺外部模型 bit-for-bit；删除和权限变化优先于复现便利。
11. **Deferred numbers**：没有真实 baseline、方差、review agreement 与 Failure Cost 前，不冻结 numerical threshold、重复次数、最终参数或 machine stopping。

完整 rationale、Failure Case、T-EVAL-001–011 与 Reopen Conditions 见 [Stage 1.10 Evaluation ADR](./technical-decisions/stage-1-10-evaluation.md)。

### Stage 1.11：Application Boundary 与 Python 工程结构

1. **Single Python distribution**：v1 使用一个 Python distribution，内部采用 `src/trivae` 与按架构 ownership 划分的概念 package；不直接复制 ChatLab 的多 workspace monorepo。
2. **Surface separation**：CLI 与 HTTP API 是薄 Interface Adapter；Evaluation 是独立评测子系统，但其进入生产 execution core 的 execution adapter 保持薄，不复制第二套 execution semantics。
3. **Single application entry**：bootstrap 的 Trivae Application Factory 创建统一的 Application；CLI、API、Evaluation 都将输入转换为 Application-level `QueryRequest`，进入同一个 `QueryOrchestrator`。
4. **Evaluation reuses execution core**：Evaluation 的 Case / Variant / Runner / Review / Regression 属于独立评测语义；其 forced route、Controlled Variant 与 execution override 必须显式可 Trace，并通过薄 execution adapter 复用生产 Query execution core，不复制 eval-specific Runtime、Retrieval 或 Tool 链路。
5. **Separated lifecycle**：Settings、PathProvider、Store、Index、Capability、Tool Registry、Router、Planner、Runtime Adapter、Evidence / Citation、Trace Collector 与 core Application lifecycle 由 bootstrap 统一装配；HTTP ASGI、listener、socket 与 server lifecycle 由 interfaces/api / CLI serve 管理；不允许 import-time 全局资源副作用。
6. **Trivae-owned event boundary**：SDK Event 先经 Runtime Adapter 转换为 Trivae Runtime Event，再进入 Normalized Query Event；Stream Projection 与 Trace Collector 从同一语义边界派生。
7. **Cross-entry correlation**：`request_id`、`trace_id` 与 canonical Error 从入口开始保留；CLI / HTTP 只做 presentation / protocol projection，不重新定义错误语义。
8. **Two dependency rules**：Runtime Call Flow 与 Source Dependency Rule 分开记录；业务 contract 不依赖具体 infrastructure，concrete adapter 可以依赖 Trivae contract，bootstrap 可以组装两者；不新增 ports、adapters、domain、usecases 层级。
9. **Separate surfaces**：Tool Surface、CLI Surface、HTTP API Surface 独立治理；Agent Tool 不自动成为公共命令或 endpoint。
10. **Versioned HTTP boundary**：第一版保留 `/api/v1`；Streaming 优先使用 Normalized Event 的单向 SSE-like projection，WebSocket、UI、MCP、Daemon 与 self-update 暂不继承。
11. **Deferred implementation**：Conversation / Assistant Message persistence schema、Trace implementation、package 细节的长期演进、API wire schema、Evaluation runner、真实 baseline 与数值参数仍为 Implementation / Real-run Calibration Pending；M5a 已落地 Evidence / Citation finalization 的第一版 Python contract。

完整 rationale、Package Layout、Composition Root、Failure Case、ChatLab 继承 / 适配 / 暂不继承与 Reopen Conditions 见 [Stage 1.11 Application Architecture ADR](./technical-decisions/stage-1-11-application-architecture.md)。

### M5a：Evidence / Citation implementation status

M5a 保持 Stage 1.8 已确认的 ownership 与主链路，在 Query Plane 形成以下实现边界：

```text
Runtime Tool Result
  → bounded current-run provenance
  → Agent final synthesis JSON
  → query/evidence.py parser + deterministic finalizer
  → QueryResult.answer_artifact 或 finalization_error
```

`query/evidence.py` 是 Trivae-owned contract，定义 Answer Artifact、claim binding、finding-oriented Evidence、Message / Structured Source、Tool Result record 和 trusted metadata hydration；`query/runtime/` 只产生并传递 provenance，`retrieval/` 仍只返回 candidates / structured results，Application facade 不自行拼装 Evidence。M5a 的 durable Conversation / Assistant Message commit 尚未实现，validated Artifact 以 QueryResult 字段作为可验证的提交前边界，后续 M5b 才接入持久化。

ChatLab 是主要参考基线：已存在且适用于 Trivae 的设计默认采用。以下仅记录尚未确认的领域，或已有明确业务差异 / Evaluation 约束的偏离；不能把“参考设计”理解为可以无证据重新设计。

- ChatLab 的 `direct_response / tool_assisted / planned_execution` 是参考 taxonomy；Trivae 已确认将前两者合并为 `standard_execution`，并保留 `planned_execution` 作为唯一额外 Planner 路径。
- ChatLab 的 `direct_response` 与 `tool_assisted` 区分不作为 Trivae Route：是否调用 Tool 由 Agent Runtime 决定，`standard_execution` 可以调用零个、一个或多个 Tool。
- Trivae 的 Router 只负责 Planner gating，不负责 Lexical / Semantic / Hybrid Retrieval、SQL、具体 Tool 参数或 Plan Steps；这些边界分别由 Agent Runtime、Tool / Capability Layer 与后续 Planner 设计负责。
- ChatLab 的 Planner 步骤上限等实现细节不自动继承到 Trivae。
- ChatLab 的 Parent / Child Chunk 思路（Time-aware Parent + Small Child）是 Trivae Semantic 索引架构的参考；其具体切分参数（30 min / 360 chars / 消息数 / overlap 等）不自动继承，由 Trivae 的 Evaluation Set 决定。
- Stage 1.4 已沿用 ChatLab 的消息搜索自动 bounded context、Physical SQLite Schema + read-only SQL 等设计，并确认 Trivae 第一版 6 个 Tool 的 Agent-facing Surface。Trivae 不机械复制 ChatLab 的大量 Specialized Analysis Tools；该偏离以 `get_schema + execute_sql` 可覆盖确定性分析为当前约束，是否新增由 Evaluation 验证。
- ChatLab 的 `search_messages` 命中后自动扩展前后 context 是 Trivae "Search 默认带 bounded context" 决策的参考；其默认窗口参数（如 `before = 2 / after = 2`）不自动继承，由 Trivae 的 Evaluation Set 决定。
- Stage 1.8 继承 ChatLab 的结构化 Evidence Block、消息锚点、Assistant Message 持久化、安全 snippet、点击追溯和显式 incomplete 原则；正文 Citation 与 Evidence Panel 在 Trivae 中统一为同一 Answer Artifact。
- ChatLab 的固定关键词 Evidence 判断方案（计划词 / 实际发生词 → included / excluded / uncertain）不复制到 Trivae；Final Synthesis 使用 question-specific criterion，并以 `supports / contradicts / context` 与 finding sufficiency 表达语义。
- ChatLab 的固定两小时时间聚类不定义 Trivae Evidence Item；Evidence 按 claim / finding 组织，时间接近只可作为 Retrieval 线索。
- ChatLab 的 implicit CURRENT conversation 不适合 Trivae 跨 Session 调查；Message Source 显式包含 Session / Message locator、精确时间和 current-run Tool provenance。
- ChatLab 的 retrieval path status 不直接作为 Answer sufficiency；Trivae 将 Tool completeness limitations 与 `sufficient / partial / insufficient` 分轴表达。
- Stage 1.6 继承 ChatLab Planner 的 pre-execution planner、structured plan、bounded plan、available Tool filtering、invalid plan graceful skip、soft guidance injection 与 same Agent Runtime 架构。
- ChatLab Planner 的具体步骤上限、字段长度、模型参数与 Prompt 不自动继承到 Trivae；Plan size exact limits 保持 Pending Evaluation / Implementation calibration。
- ChatLab Prompt 中的 `retrieve_chat_evidence`、segment summaries、chart generation、specific specialized analysis tools 与 ChatLab-specific evidence planning heuristics 不机械复制；Trivae 只按 Stage 1.4 已确认的 6 个 Tool / Capability 设计高层 summary。
- 继承 Planner architecture 不等于复制 ChatLab Planner Prompt 的全部业务经验；Trivae-specific heuristic 必须由真实 workload、Failure Case 或 Evaluation 驱动。
- Stage 1.7 继承 ChatLab 的 Thin Agent Core 架构（通用 Loop 由核心库承载、pre-run context compression、Trivae-owned conversation history、budget-exhausted graceful final synthesis、Tool Error 可恢复、事件归一化）；第一版由 OpenAI Agents SDK（Python）承载通用 Loop，替换 ChatLab 使用的 `@earendil-works/pi-agent-core`（TS），继承的是 runtime architecture 而非具体 library。
- Stage 1.7 允许把 ChatLab 的 `max_tool_rounds`、history window、compression threshold 等**经验参数直接继承**作为 v1 baseline，但必须标注继承来源并保留 Evaluation 校准路径；不无条件照抄，也不拒绝继承。
- OpenAI Agents SDK 是当前 Python Agent Runtime 的映射方向（Stage 1.7 已确认架构）；具体版本、集成方式与适配契约保持 Implementation Pending。
- Stage 1.9 继承 ChatLab 的“Core / SDK Event 先转换成项目自有事件，再由 handler 驱动 stream / state / logging”与 Normal / Debug 记录详细度分离方向；Trivae 将该边界扩展到 Router、Planner、Retrieval、Evidence 与 Citation，并增加 query-scope coverage、Data Access Scope、privacy projection 与 retention contract。不复制 ChatLab 的 2000 字符截断、日志文件 / 数据库字段、具体格式或默认保留期；ChatLab 的 Debug 证据只支持“详细 model-visible facts 对 Failure Attribution 有价值”，不自动决定 Trivae 的权限和 retention。
- Stage 1.10 继承 ChatLab evaluation-set 的稳定 Case identity、locale / chat type / scenario slice、按具体 Finding 表达的 expected evidence coverage、Route / Plan / Tool / usage / budget 可观察性与“baseline 在真实环境运行前保持 Pending”的治理方向；Trivae 将其扩展为 Snapshot / Scope / Reference Findings / Evidence / Review 的 Case Bundle、forced-path Planner Utility、blind paired comparison 和 versioned Regression。ChatLab 的 24 个 Case、expected route 标签、静态结构测试与经验参数不自动成为 Trivae Benchmark、stable baseline 或最优值。
- ChatLab 的固定关键词 Evidence Judge、固定时间聚类与 specialized Evidence Tool 不继承；Trivae 使用 question-specific criterion、`supports / contradicts / context`、`exhaustive / partial / unknown` Reference completeness 和人工复核。

## Pending Decisions

以下事项仍为 **Pending architecture specification**，不得在本阶段自行补齐或实现：

- M1 SQLite ingestion schema 已在 `.trellis/spec/backend/database-guidelines.md` 固化；后续 schema migration、部署/备份策略和 Retrieval derived store 仍 Pending
- Data Access Scope 对 `execute_sql` 的具体 enforcement 机制（物理隔离、connection scope、SQL validation 或其他实现）
- `execute_sql` 的具体 bounded execution mechanism（result fetching、cursor、adapter-level max rows 或其他实现）
- Vector Store 实现、Chunk 具体切分参数、Embedding 模型、Indexing Pipeline 具体执行方式
- Reranker 是否引入、Fusion 权重、merge / dedup / candidate selection 的具体算法（Pending Evaluation，由 Evaluation Set 决定）
- Semantic / Lexical Index 的具体存储、版本管理与重建执行方式（Derived Data 语义已确认，实现 Pending）
- Retrieval Trace family、query-scope coverage 与 Failure Attribution 已由 Stage 1.9 确认；具体 Python / JSON Schema、事件名与采集实现 Pending
- M1 ingestion 已确定并测试：结构化 fallback identity、文件级 transaction/record-level partial、source occurrence 幂等和 canonical first-wins + variant/conflict；后续规模化 Deduplicator、migration 与重处理策略仍 Pending
- M1 已使用 `peerUid` / 文件明确群号作为 authoritative ChatSession identity；未来其他来源缺少 stable ID 时的 matching strategy 仍 Pending
- M1 已将 raw payload、source locator、structured content 以 SQLite JSON/text 字段保存；跨来源 schema 演进仍 Pending
- M1 canonical timestamp 使用 Unix 毫秒整数；其他来源的 timezone/precision 转换策略仍 Pending
- Query-specific strategy 的具体指导机制与失败处理（由 Stage 1.10 Evaluation 在真实运行中校准，具体实现 Pending）
- Router 具体规则 / regex、复杂度权重、confidence threshold、LLM 模型 / prompt / timeout、Python 类型与文件布局（Stage 1.5 已确认语义，具体实现保持 Pending）
- Router Trace family、degradation / Error Code ownership 与 operational metric 维度已由 Stage 1.9 确认；具体 Schema、事件名与实现 Pending
- Router Query Set、标签流程、forced-path Planner Utility / Router Utility 的具体执行与参数校准（Stage 1.10 Implementation / Real-run Calibration）
- Planner 的具体 Python class / package layout、Model、Prompt、Structured Output 技术、temperature、max tokens、timeout
- Plan 的具体 Python / JSON Schema、validator library、字段类型与序列化；概念字段与语义已由 Stage 1.6 确认
- Plan 的具体 max steps、max success criteria、字段长度 limit 与其他 bounded 参数（Pending Evaluation / Implementation calibration）
- Compact DataSnapshot 的完整 Schema、Conversation Context 的 history window / summarization / compression / token 控制（Stage 1.7 已确认 pre-run compression 机制，具体参数 Pending Evaluation）
- Planner Trace family、failure attribution 与 operational metric 维度已由 Stage 1.9 确认；具体 Schema、事件名与实现 Pending
- Planner Evaluation Dataset、Planner Utility review、latency threshold、latency budget / invocation policy、cost budget、bounds calibration、是否需要更多 intent 类型与未来是否需要 replan（Stage 1.10 Implementation / Real-run Calibration）
- Agent Runtime 的具体 SDK 版本、Adapter 契约与实现、RuntimeContext / Agent Model Context 具体类型、Conversation transaction / commit Schema、Tool 并发策略（Stage 1.7 已确认架构边界，具体实现保持 Pending Implementation）
- Agent Runtime 的 `max_tool_rounds`、SDK `max_turns`、history window、compression threshold、Tool Result token budget 等具体数字（Pending Evaluation；可继承 ChatLab 经验参数作为 v1 baseline，标注来源）
- Runtime / Trace conceptual envelope 与 Error Code ownership 已由 Stage 1.9 确认；具体 Python / JSON Schema、完整 Error Code 枚举、Exception mapping 与 event version migration Pending
- Trace Collector / Store / projector 的 package layout、API、transaction、backend、query index、partition、buffering 与 deployment topology
- Trace Profile 的配置来源 / 启用边界、Normal / Debug capture policy、redaction / secret stripping、角色权限、retention 具体时长、删除传播与 production capacity planning
- OpenTelemetry 或其他 exporter 是否接入；若接入只能消费 privacy-projected Trivae Event，SDK built-in external tracing 当前继续显式关闭
- Agent correctness benchmark、quality axes、budget / threshold 与参数校准（Stage 1.10 Implementation / Real-run Calibration；Case / Reference / Review 语义已由 ADR 确认）
- Evidence-aware stopping 的 machine-enforced gate、minimum-citation / coverage gate 与参数（Stage 1.10 Implementation / Real-run Calibration；Stage 1.8 已确认第一版仅作 Agent guidance）
- Answer Artifact 的 Durable Database Schema、Conversation commit / replay、Message mutation 后的 snapshot / current diff UX 与长期 Claim binding migration 仍 Pending；M5a 已落地第一版 Python / JSON finalization contract、Structured Result locator 与 calibrated bounded source limits，具体参数仍待 Evaluation 校准
- Evidence / Citation Trace family、Error Code ownership、storage 与 operational metric 原则已由 Stage 1.9 确认；具体 Schema、枚举与实现 Pending
- semantic entailment、criterion quality、sufficiency、citation precision / recall 与 bounded repair Evaluation 的具体 rubric / runner（Stage 1.10 Implementation / Real-run Calibration）
- Evaluation Case authoring、Dataset / Snapshot 构建、Review workflow、result storage、quality metric 实现、threshold / gate、Evaluation runner 与 Regression 执行细节（Stage 1.10 Implementation / Real-run Calibration；总体 Evaluation architecture 已由 [Stage 1.10 ADR](./technical-decisions/stage-1-10-evaluation.md) 确认）
- Context architecture 与上下文规模控制（Stage 1.7 已确认 RuntimeContext / Model Context 分离与 pre-run compression 机制，实现 Pending）
- Answer Generation 的长期模型、Prompt 演进与版本化输出 Schema 仍 Pending；M5a 已实现第一版结构化 final synthesis prompt / parser，invalid / unresolved Citation 阻止 Finalization 的失败语义已由 Stage 1.8 确认
- CLI / API / Evaluation 的具体协议 Schema、状态 / 结果展示、鉴权与产品交互（Stage 1.11 已确认 Application Boundary，具体实现 Pending）
- Python package 的具体文件、class / interface signature、DI 方式与依赖锁定（Stage 1.11 已确认概念 package ownership，具体实现 Pending）
- 其他模块的 Retry / Fallback 策略（Stage 1.5 Router 的显式可用性降级契约除外）
- 会明显改变系统复杂度的新依赖或基础设施

## Evolution Rule

- Stage 1.10 Implementation / Real-run Calibration 与 Stage 1.11 Implementation / Product Interaction 每次只更新对应的架构章节，不提前填充其他 Pending 项；Stage 1.11 的 Application Boundary 已由本文件与 ADR 确认。
- 每个新决策应保留问题、证据、候选方案、决定、原因、trade-off 和验证方式；必要时同步到 [technical-decisions.md](./technical-decisions.md)。
- Stage 1.1-1.11 全部完成后，统一审查本文件，才可将状态从 Draft / In Progress 升级为最终 Architecture Specification。

## Architecture Problem Handling

如果后续发现已确认架构存在重大问题：

1. 记录 `Problem / Evidence / Impact / Possible Options`。
2. 停止对应架构改动，不用兼容分支或临时实现掩盖问题。
3. 等待新的设计决策，并在 [problem-records.md](./problem-records.md) 或对应 task 中沉淀结果。
