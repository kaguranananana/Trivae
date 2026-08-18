# Stage 1.2: Data Model + Ingestion Decisions

> 状态：**Confirmed（Stage 1.2）**
> 记录 Stage 1.2 真正形成的架构决策及 rationale；仅覆盖逻辑数据模型与概念边界，不涉及 Database Schema 与技术选型。

---

## 1. Canonical Model 隔离外部数据源格式

**Decision**：所有外部聊天来源先经 Adapter / Parser 统一转换为 Canonical Model；Importer、Storage、Retrieval 不感知具体源格式。

**Reason**：NapCat、QQ Export、ChatLab Export 等来源字段名与结构各不相同；若后续层直接依赖源格式，每新增一个数据源都要改动去重、存储、索引、检索全链路。Parser 只负责"读懂源格式"，格式差异在入口处消化。

**Trade-off**：新增一个概念层（Canonical Model 的字段设计需要前期投入），换取新增数据源时下游零改动。

## 2. Stable Platform Identity 优先

**Decision**：ChatSession 稳定身份用 `platform + external_chat_id`；UserIdentity 用 `platform + platform_user_id`。群名、昵称等可变字段不作为身份判断依据。

**Reason**：群名会变化，平台 ID 才是稳定身份；仅用群名匹配是"同一个群被重复创建"这类问题的根因。用户昵称同理可能跨群不同。

**Trade-off**：依赖平台提供稳定的 ID；对完全缺少稳定 ID 的来源需要 fallback（见决策 5 的消息级处理思路）。

## 3. Platform Identity 与 Session Membership 分离

**Decision**：UserIdentity 表示跨群稳定平台用户身份；Membership 表示该用户在某个 ChatSession 中的局部身份（群昵称、角色、alias 等），两者分离。

**Reason**：同一个人在群 A / 群 B / 群 C 的显示名可以不同；只有身份与显示分离，才能支持跨群人物分析与正确归属消息作者。

**Trade-off**：比"用户只有昵称"的模型多一个概念，换取跨群一致性。

## 4. Shared Importer

**Decision**：所有数据源共用同一套 Importer；去重、数据库写入、成员更新、索引写入逻辑不按数据源重复实现。

**Reason**：若每个 Adapter / Parser 各自操作数据库，会演化出多套字段转换、去重、成员更新逻辑，同一条消息从不同入口进入时行为不一致。统一 Importer 保证行为一致、问题易定位。

**Trade-off**：Importer 必须只依赖 Canonical Model，禁止源格式分支（`if qq_exporter:`）。

## 5. Stable Message ID 优先、Fingerprint fallback

**Decision**：去重 Priority 1 用稳定的 platform / source message id（如 `platform + session + source_message_id`）；Priority 2 用 Canonical Message Fingerprint；否则视为新消息。Fingerprint 必须结合 session、sender、timestamp、message type、normalized content、reply relationship（如适用），不能只做 content hash。

**Reason**：content hash 对"哈哈""好的"等高频重复文本必然误去重；组合字段的 fingerprint 重复概率足够低。部分导出格式不提供稳定消息 ID，需要 fallback。

**Trade-off**：fingerprint 需要定义并维护稳定的组合规则；不组合 timestamp / sender 的纯内容 hash 不可用。

## 6. Canonical Store 为 Source of Truth

**Decision**：Canonical Message Store 是聊天数据的 Source of Truth；Keyword Index、Embedding、Vector Index、Chunk、Topic / Summary Index 等均为 Derived Data，必须可基于 Canonical Store 重建。

**Reason**：索引（尤其 Embedding）会随模型升级而变更；若索引是唯一事实来源，换模型必须重新导入原始数据。Canonical Store 保持原始事实，派生数据随时可重建。

**Trade-off**：两份数据（canonical + derived）需要重建机制，换取模型升级成本可控。

## 7. Ingestion Observability（ImportBatch）

**Decision**：ImportBatch 记录一次 ingestion 的 source、session、start / finish、received / inserted / duplicate / error count 与 status。

**Reason**：符合 Observable / Failure Attribution 原则——一次导入"到底发生了什么"可直接观测，问题可定位到具体来源批次。

**Trade-off**：少量额外写入成本，换取故障定位能力。

---

## Pending（本阶段不决策）

以下事项保持 Pending，不随本文档解除：

- 最终数据库选型、Database Schema、表数量、字段类型与具体索引
- SQLite / PostgreSQL 具体实现
- Vector Store 实现、Chunking 策略、Embedding 模型、Indexing Pipeline 具体执行方式
- Ingestion 具体实现细节（fingerprint 算法、失败处理、幂等执行）
- Retrieval Architecture、Rerank
- Evidence / Citation Schema、Trace Schema
