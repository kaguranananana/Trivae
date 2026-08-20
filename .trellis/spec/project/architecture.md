# Architecture

> 状态：**Draft / In Progress**
>
> 本文件记录已完成的 Stage 1.1 整体架构骨架、Stage 1.2 Data Model + Ingestion、Stage 1.3 Retrieval Architecture 与 Stage 1.4 Tool / Capability Layer 确认内容，不是完整且最终的 Architecture Specification。
> 当前状态为：Stage 1.1 completed；Stage 1.2 Data Model + Ingestion completed；Stage 1.3 Retrieval Architecture completed；Stage 1.4 Tool / Capability Layer completed；Stage 1.5 pending（尚未开始）。
> 未明确列出的实现细节继续标记为 `Pending architecture specification`，不得自行补全。

---

## Status

| 项      | 状态                                                                                                                                                                                                             |
| ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 当前阶段   | Stage 1.1 completed；Stage 1.2 Data Model + Ingestion completed；Stage 1.3 Retrieval Architecture completed；Stage 1.4 Tool / Capability Layer completed；Stage 1.5 pending（尚未开始） |
| 文档成熟度  | Draft / In Progress                                                                                                                                                                                            |
| 业务实现   | 当前无业务代码；后续按已确认架构与 Trellis task 实施                                                                                                                                                                              |
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
- Query Plane 不依赖 QQ 导出格式、NapCat 字段等 Source-specific 原始实现。
- Query Plane 只能通过 Tool Layer 访问 Data Plane 能力；第一版 Structured Retrieval 通过 `get_schema / execute_sql` 有意暴露 SQLite Physical Query Schema，Agent 对数据库的依赖仍被限制在 Tool Contract 与 Data Access Scope 内。

#### Pending

Canonical Data Model 与 Ingestion 概念管线已在 Stage 1.2 确认（见 [Stage 1.2: Data Model + Ingestion](#stage-12-data-model--ingestion)），Retrieval 架构已在 Stage 1.3 确认（见 [Stage 1.3: Retrieval Architecture](#stage-13-retrieval-architecture)，其中 Semantic 索引单位为 Conversation Chunk，且 Semantic / Lexical Index 均属 Derived Data）。Stage 1.4 已进一步确认第一版 structured / canonical persistent store 采用 SQLite。仍待后续阶段确定的是 SQLite Physical Schema、表结构、字段类型、索引、migration、transaction、具体持久化实现，以及 Vector Storage 是否独立、Chunk 具体切分参数、Embedding 模型与 Indexing Pipeline 的具体执行方式。

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

（Stage 1.4 已确认第一版由 Agent 组合调用 `lexical_search` / `semantic_search`；具体策略指导机制与失败处理留给 Stage 1.10 Evaluation 验证。）

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
index coverage = 63%
+
partial = true
```

结论只能是：当前检索没有找到，但数据覆盖不足，无法确认不存在。因此 Semantic Retrieval 必须能显式暴露 coverage / partial / truncated 等完整性信息。

> Coverage 的语义需要在后续阶段（Stage 1.9）进一步明确为 **query-scope coverage**：当查询限定在某个 session / time range 时，有意义的是"请求范围内的覆盖率"（requested scope coverage），而不是全局索引覆盖率（例如用户只查 2026 年 7 月某个群，全局索引覆盖 80% 没有意义，重要的是该范围内的覆盖 = 100%）。当前仅确认"必须显式暴露 coverage / partial / truncated"，具体口径与字段 Pending。

### Retrieval Trace（观察需求，非 Schema）

本阶段只确定 **Retrieval 需要观察哪些信息及其目的**，**不实现具体存储格式或 Trace Schema**（Trace Schema、事件模型、存储与采集方式仍为 Pending 项）。

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

不复制 ChatLab 用固定关键词（计划词 / 实际发生词）判断 `included / excluded / uncertain` 的方案。Trivae 面向技术情报，不同问题的"证据成立条件"完全不同（例如"最终有没有人真的把 OpenAI Agents SDK 用到项目里"可能出现"准备试一下""已经接进去了""昨天上线了""最后还是换回自己写"）。Evidence Judge 应围绕 **Question-specific Criteria** 设计，留到 Stage 1.8 Evidence / Citation 决定。

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
| Partial / Coverage | 必须显式暴露（口径在 Stage 1.9 细化为 query-scope coverage） |
| Evidence 判断 | 不在 Retrieval 层硬编码（Question-specific Criteria，Stage 1.8） |
| Retrieval Trace | 观察需求已确认；存储格式 / Schema 不提前实现 |

#### Tunable / Pending Evaluation（由 Evaluation Set 决定）

| 项目 | 状态 |
| --- | --- |
| Reranker | Pending Evaluation（第一版不引入） |
| Fusion 权重 | Pending Evaluation（第一版不设计加权打分） |
| Chunk 具体参数（时间 gap / 字符数 / 消息数 / token 上限 / overlap） | Pending Evaluation（不复制 ChatLab 默认数字） |
| Message-level 辅助语义索引 | Pending Evaluation（第一版默认不建立；Evaluation 证明其对特定 Failure Case 有价值后再引入） |
| 组合 / 选择具体算法（merge / dedup / candidate selection） | Pending Evaluation |
| Query-specific strategy 的具体指导机制与失败处理 | Pending（Stage 1.10 Evaluation） |

#### Pending（后续阶段 / 架构实现前不决策）

| 项目 | 状态 |
| --- | --- |
| Vector Store 实现、Embedding 模型、Indexing Pipeline 具体执行方式 | Pending architecture specification |
| Semantic / Lexical Index 的具体存储与版本管理 | Pending architecture specification |
| Retrieval Trace Schema、事件模型、存储与采集方式 | Pending（本阶段仅确认观察需求） |
| Tool / Capability Layer（Agent 看到哪些 Tool、如何命名） | Confirmed（Stage 1.4） |
| Evidence Judge 设计 | Pending（Stage 1.8） |
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
- 仍未确定：Reranker、Fusion 权重、Chunk 具体参数、merge / dedup / candidate selection 的具体算法、Message-level 辅助语义索引（Pending Evaluation）；Vector Store、Embedding 模型、Indexing Pipeline 具体实现（Pending architecture specification）；Retrieval Trace Schema（Pending）。

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

Stage 1.4 补充了 Tool 层内部可观测性要求：Tool 可以组合多个 Capability，但组合不得隐藏执行状态——一次 Tool Call 内部应能区分 Retrieval 未召回、Context Expansion 范围不合适、Agent 分析错误；Semantic 不可用时不得 silent fallback 为 Lexical 并返回普通结果。统一 Envelope 明确区分 zero hits / capability unavailable / invalid arguments / execution failure / partial / truncated，其中 Truncation 与 Partial Execution 保持独立。

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

### Stage 1.3：Retrieval Architecture

1. **Multi-strategy Retrieval**：Retrieval 由 Retrieval Composition、三个 Retrieval Primitives（Structured / Lexical / Semantic）与 Post-Retrieval Operator（Context Expansion）组成；Context Expansion 与前三个不在同一层，`retrieve` 与 `expand context` 是两个动作。
2. **Hybrid 是组合策略**：Hybrid 属于 Retrieval Composition 层，不单独成为底层搜索引擎，不演化出"什么问题都往里面塞"的 `hybrid_search()`。
3. **集合确定后的确定性查询优先**：当目标数据集合可由结构化条件确定时优先使用 Structured Retrieval；集合本身需要语义判断时先经 Lexical / Semantic 确定候选集合再做确定性聚合；LLM 负责解释结果，不负责数数。
4. **Semantic 第一版 primary indexing unit 为 Conversation Chunk**：默认不建立逐 Message 向量索引；采用 Time-aware Parent + Small Child 架构，命中 Child → 定位所属 Parent → Context Expansion。若 Evaluation 证明 Message-level retrieval 对特定 Failure Case 有价值，再作为辅助索引引入（Pending Evaluation）。
5. **Query-specific strategy**：Retrieval Strategy 由任务决定，不默认所有查询执行固定 Hybrid Pipeline。
6. **Retrieval Result provenance 保留**：Retrieval Result 分 Message Candidates（lexical / semantic）与 Structured Results（scalar / aggregate / records），共同保留 provenance 与 trace metadata；不把所有结果压成单一 Candidate 类型。
7. **Partial / Coverage 显式暴露**：不能"搜不到 = 不存在"；Semantic Retrieval 必须能表达 coverage / partial / truncated 等完整性信息（口径在 Stage 1.9 细化为 query-scope coverage）。
8. **Reranker 与 Fusion 权重不提前设计**：先建立 baseline，出现 Failure Case 并证明排序问题后再评估；Chunk 具体参数同样保持 Tunable。
9. **Evidence 判断不在 Retrieval 层硬编码**：不复制 ChatLab 固定关键词判断 Evidence Status 的方案；Evidence Judge 围绕 Question-specific Criteria 设计（Stage 1.8）。
10. **Retrieval Trace 观察需求确定、Schema 不提前实现**：记录需要观察的检索信息（query / strategy / filters / lexical / semantic / context_expansion / final_candidates）及其目的；具体存储格式与 Trace Schema 保持 Pending。

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

## ChatLab Baseline and Recorded Differences

ChatLab 是主要参考基线：已存在且适用于 Trivae 的设计默认采用。以下仅记录尚未确认的领域，或已有明确业务差异 / Evaluation 约束的偏离；不能把“参考设计”理解为可以无证据重新设计。

- ChatLab 的 `direct_response / tool_assisted / planned_execution` 路径和 Planner 行为是参考设计；Trivae 的路由名称与策略仍待确认。
- ChatLab 的 Planner 步骤上限等实现细节不自动继承到 Trivae。
- ChatLab 的 Parent / Child Chunk 思路（Time-aware Parent + Small Child）是 Trivae Semantic 索引架构的参考；其具体切分参数（30 min / 360 chars / 消息数 / overlap 等）不自动继承，由 Trivae 的 Evaluation Set 决定。
- Stage 1.4 已沿用 ChatLab 的消息搜索自动 bounded context、Physical SQLite Schema + read-only SQL 等设计，并确认 Trivae 第一版 6 个 Tool 的 Agent-facing Surface。Trivae 不机械复制 ChatLab 的大量 Specialized Analysis Tools；该偏离以 `get_schema + execute_sql` 可覆盖确定性分析为当前约束，是否新增由 Evaluation 验证。
- ChatLab 的 `search_messages` 命中后自动扩展前后 context 是 Trivae "Search 默认带 bounded context" 决策的参考；其默认窗口参数（如 `before = 2 / after = 2`）不自动继承，由 Trivae 的 Evaluation Set 决定。
- ChatLab 的固定关键词 Evidence 判断方案（计划词 / 实际发生词 → included / excluded / uncertain）不复制到 Trivae；Evidence Judge 围绕 Question-specific Criteria 设计。
- OpenAI Agents SDK 是当前 Python Agent Runtime 的映射方向；具体版本、集成方式和适配契约仍需在 Stage 1.7 验证。

## Pending Decisions

以下事项仍为 **Pending architecture specification**，不得在本阶段自行补齐或实现：

- 第一版 SQLite Physical Schema 的表数量、字段类型、具体索引与持久化实现
- Data Access Scope 对 `execute_sql` 的具体 enforcement 机制（物理隔离、connection scope、SQL validation 或其他实现）
- `execute_sql` 的具体 bounded execution mechanism（result fetching、cursor、adapter-level max rows 或其他实现）
- Vector Store 实现、Chunk 具体切分参数、Embedding 模型、Indexing Pipeline 具体执行方式
- Reranker 是否引入、Fusion 权重、merge / dedup / candidate selection 的具体算法（Pending Evaluation，由 Evaluation Set 决定）
- Semantic / Lexical Index 的具体存储、版本管理与重建执行方式（Derived Data 语义已确认，实现 Pending）
- Retrieval Trace Schema、事件模型、存储与采集方式（仅观察需求已确认）
- Ingestion 具体实现细节：Deduplicator 的 fingerprint 算法、失败处理与幂等执行方式
- ChatSession / UserIdentity 缺少 authoritative stable ID 时的 fallback identity / matching strategy
- 相同 stable message identity 对应 canonical payload 变化时的 update / mutation / conflict resolution semantics
- Canonical Message Fingerprint 的具体字段组合、时间精度、canonicalization 与 hash algorithm
- raw payload / source locator / structured content 的具体表示
- Canonical timestamp 的 timezone / precision / 存储类型与转换实现
- Query-specific strategy 的具体指导机制与失败处理（Stage 1.10 Evaluation 边界）
- Router 具体策略、分类规则、置信度、阈值与失败处理
- Planner Schema、步骤上限、校验和执行约束
- Agent Runtime 的具体 SDK 版本、Adapter 契约、Session、Streaming、Abort 与 Run Lifecycle 细节
- Evidence / Citation model、证据状态、来源字段与引用格式（Stage 1.8）
- Evaluation Set、指标口径、Evaluation architecture 与 Regression 执行方式
- Context architecture 与上下文规模控制
- Answer Generation 的模型、Prompt、输出契约与失败处理
- CLI / API 边界
- Python package / module layout
- Retry / Fallback 策略
- 会明显改变系统复杂度的新依赖或基础设施

## Evolution Rule

- Stage 1.5-1.11 每次只更新对应的架构章节，不提前填充其他 Pending 项。
- 每个新决策应保留问题、证据、候选方案、决定、原因、trade-off 和验证方式；必要时同步到 [technical-decisions.md](./technical-decisions.md)。
- Stage 1.1-1.11 全部完成后，统一审查本文件，才可将状态从 Draft / In Progress 升级为最终 Architecture Specification。

## Architecture Problem Handling

如果后续发现已确认架构存在重大问题：

1. 记录 `Problem / Evidence / Impact / Possible Options`。
2. 停止对应架构改动，不用兼容分支或临时实现掩盖问题。
3. 等待新的设计决策，并在 [problem-records.md](./problem-records.md) 或对应 task 中沉淀结果。
