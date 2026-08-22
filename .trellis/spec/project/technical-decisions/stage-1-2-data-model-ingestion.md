# Stage 1.2: Data Model + Ingestion Decisions

> 状态：**Confirmed（Stage 1.2）**
> 记录 Stage 1.2 真正形成的架构决策及 rationale；仅覆盖逻辑数据模型与概念边界，不涉及 Database Schema 与技术选型。

---

## 1. Canonical Model 隔离外部数据源格式

**Decision**：所有外部聊天来源先经 Adapter / Parser 统一转换为 Canonical Model；Importer、Storage、Retrieval 不感知具体源格式。

**Reason**：NapCat、QQ Export、ChatLab Export 等来源字段名与结构各不相同；若后续层直接依赖源格式，每新增一个数据源都要改动去重、存储、索引、检索全链路。Parser 只负责"读懂源格式"，格式差异在入口处消化。

**Trade-off**：新增一个概念层（Canonical Model 的字段设计需要前期投入），换取新增**能够映射到现有 Canonical Model**的数据源时，下游无需增加 source-specific branches。

## 2. Stable Platform Identity 优先

**Decision**：ChatSession 稳定身份用 `platform + external_chat_id`；UserIdentity 用 `platform + platform_user_id`。群名、昵称等可变字段不作为身份判断依据。

**Reason**：群名会变化，平台 ID 才是稳定身份；仅用群名匹配是"同一个群被重复创建"这类问题的根因。用户昵称同理可能跨群不同。

**Trade-off**：依赖平台提供稳定的 ID。对于缺少 authoritative stable ID 的 ChatSession / UserIdentity，其 fallback identity / matching strategy 当前保持 Pending，不得复用 Message Fingerprint 作为身份匹配方案（Message Fingerprint 只用于消息去重，不解决身份匹配）。

## 3. Platform Identity 与 Session Membership 分离

**Decision**：UserIdentity 表示跨群稳定平台用户身份；Membership 表示该用户在某个 ChatSession 中的局部身份（群昵称、角色、alias 等），两者分离。

**Reason**：同一个人在群 A / 群 B / 群 C 的显示名可以不同；只有身份与显示分离，才能支持跨群人物分析与正确归属消息作者。

**Trade-off**：比"用户只有昵称"的模型多一个概念，换取跨群一致性。

## 4. Shared Importer

**Decision**：所有数据源共用同一套 Importer；去重、数据库写入、成员更新、索引写入逻辑不按数据源重复实现。

**Reason**：若每个 Adapter / Parser 各自操作数据库，会演化出多套字段转换、去重、成员更新逻辑，同一条消息从不同入口进入时行为不一致。统一 Importer 保证行为一致、问题易定位。

**Trade-off**：Importer 必须只依赖 Canonical Model，禁止源格式分支（`if qq_exporter:`）。

## 5. Stable Message ID 优先、Fingerprint fallback

**Decision**：去重 Priority 1 用稳定的 platform / source message id（如 `platform + session + source_message_id`）；Priority 2 用 Canonical Message Fingerprint；否则视为新消息。Stable Message ID 用于识别**同一逻辑消息**；当相同 identity 对应的 canonical payload 发生变化（编辑、撤回 / 状态变化、Source 数据纠正、Parser 版本变化、数据冲突）时，其 update / mutation / conflict resolution semantics 当前保持 Pending，不应直接等同于 duplicate skip。Fingerprint 基于 canonicalized stable attributes 构造；session、sender、timestamp、message type、normalized content、reply relationship（如适用）是候选组成字段，具体字段组合、时间精度、canonicalization 与 hash algorithm 保持 Pending，并通过真实重复数据验证。

**Reason**：content hash 对"哈哈""好的"等高频重复文本必然误去重；组合字段的 fingerprint 重复概率足够低。部分导出格式不提供稳定消息 ID，需要 fallback。不同 Source 对 timestamp 精度、timezone、空格换行、mention、emoji 的 normalization 可能不同，因此 fingerprint 的具体构成必须通过真实数据验证，不能提前固定。

**Trade-off**：fingerprint 需要定义并维护稳定的组合规则；不组合 timestamp / sender 的纯内容 hash 不可用；组合规则过早固定会导致跨 Source 重复数据无法命中。

## 6. Canonical Store 为 Source of Truth

**Decision**：Canonical Message Store 是聊天数据的 Source of Truth；Keyword Index、Embedding、Vector Index、Chunk、Topic / Summary Index 等均为 Derived Data，必须可基于 Canonical Store 重建。

**Reason**：索引（尤其 Embedding）会随模型升级而变更；若索引是唯一事实来源，换模型必须重新导入原始数据。Canonical Store 保持原始事实，派生数据随时可重建。

**Trade-off**：两份数据（canonical + derived）需要重建机制，换取模型升级成本可控。

## 7. Ingestion Observability（ImportBatch）

**Decision**：ImportBatch 记录一次 ingestion 的 source、session、start / finish、received / inserted / duplicate / error count 与 status。

**Reason**：符合 Observable / Failure Attribution 原则——一次导入"到底发生了什么"可直接观测，问题可定位到具体来源批次。

**Trade-off**：少量额外写入成本，换取故障定位能力。

## 8. Canonicalization 保真

**Decision**：Canonicalization 必须保持查询、证据追溯和未来重新处理所需的信息，不应因为 normalization 丢失关键原始语义（如 URL、代码、@mention、图片 / 文件、reply / forward、富文本 message segments）。具体 structured content / raw payload / source locator 表示在后续 Data Schema 阶段确定，当前 Pending。

**Reason**：若 Normalizer 只保留精简后的文本，Canonical Store 名义上是 Source of Truth，实际上已经丢信息，无法支撑后续的证据追溯与重新处理。

**Trade-off**：保留更多原始语义会增加 Canonical Model 的复杂度和存储成本，但避免不可逆的信息丢失。

## 9. Canonical Timestamp 语义

**Decision**：Canonical timestamp 必须能够表达一个确定的时间点，且不因 Source 的 timezone、timestamp precision 或转换规则导致跨 Source 时间语义不一致。具体数据库类型与存储格式（UTC datetime / Unix 毫秒 / TIMESTAMPTZ 等）保持 Pending。

**Reason**：大量查询依赖时间语义（最近三个月、半年内观点变化、8 月以后讨论）；不同 Source 的 timezone / 精度差异若不做统一约束，会导致时间范围查询结果不一致。

**Trade-off**：需要定义统一的 canonical timestamp 语义，换取跨 Source 时间查询的一致性；具体存储格式留给 Schema 阶段。

## 10. M1 落地校准：seq 是可缺省的排序提示

**Decision**：M1 将 `seq` 作为 optional ordering hint，而不是必需消息字段。缺失、`null` 或空字符串允许进入 Canonical Model 并规范化为 `None`；非空但无法解析为整数仍是记录级验证错误。`timestamp` 继续是必需的有效整数。

**Reason**：当前 QQ 导出数据的 `seq` 虽然全部存在，但上游导出模型允许空序号；M1 的 identity 与写入链路不依赖 `seq` 必须存在，缺失时可以用 `timestamp + internal_message_id` 提供确定性排序。将“当前样本全有”误写成 source contract 会把上游合法空值变成不必要的失败。

**Validation**：真实 14 文件全量导入的 `received=494628`、`inserted=473236`、`duplicate=21392`、`conflict=2775`、`error=0` 保持不变；新增测试覆盖缺省 `seq` 接受、非法非空 `seq` 拒绝和非法 `timestamp` 拒绝。

---

## Pending（本阶段不决策）

以下事项保持 Pending，不随本文档解除：

- 最终数据库选型、Database Schema、表数量、字段类型与具体索引
- SQLite / PostgreSQL 具体实现
- Vector Store 实现、Chunking 策略、Embedding 模型、Indexing Pipeline 具体执行方式
- Ingestion 具体实现细节（fingerprint 字段组合 / 时间精度 / canonicalization / hash algorithm、失败处理、幂等执行）
- ChatSession / UserIdentity 缺少 authoritative stable ID 时的 fallback identity / matching strategy
- 相同 stable message identity 对应 canonical payload 变化时的 update / mutation / conflict resolution semantics
- raw payload / source locator / structured content 的具体表示
- Canonical timestamp 的 timezone / precision / 存储类型与转换实现
- Retrieval Architecture、Rerank
- Evidence / Citation Schema、Trace Schema
