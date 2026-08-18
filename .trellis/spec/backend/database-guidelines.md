# Database Guidelines

> 状态：**Partial：已确认数据库无关原则；Database Architecture 整体仍 Pending**
> 数据库选型、Schema、表设计与具体实现属于不可自行决定的架构事项（见 ../project/architecture.md），继续保持 Pending 状态。

---

## 当前结论

- 本阶段不设计 Database schema，不选择数据库技术；SQLite / PostgreSQL、Vector Store、字段类型、具体索引与迁移方案等待 Architecture Specification。
- 以下为 Stage 1.2 已确认的**数据库无关原则**，后续任何存储实现都必须满足：

### 已确认的数据库无关原则

- **Canonical Message Store 是聊天数据的 Source of Truth**；Keyword Index、Embedding、Vector Index、Chunk、Topic / Summary Index 等均为 Derived Data，必须可基于 Canonical Store 重建，搜索索引不得成为原始事实来源。
- **Message Identity 区分两个 ID**：Trivae Internal Message ID 与 Platform / Source Message ID 是两个概念，Message 需能通过 source message id 追溯到原始聊天记录（Evidence / Citation 依赖此能力）。
- **逻辑实体**：`Source`、`ChatSession`、`UserIdentity`、`Membership`、`Message`、`ImportBatch` 是已确认的逻辑数据模型，不等同于最终表设计；表数量、字段与索引待 Storage Architecture 阶段决定。
- **稳定身份优先**：ChatSession 以 `platform + external_chat_id` 为稳定身份，UserIdentity 以 `platform + platform_user_id` 为稳定身份；群名、昵称等可变字段不能作为身份判断依据。
- **去重优先级**：stable platform/source message id 优先，Canonical Message Fingerprint fallback；fingerprint 不能只使用 content hash。

## 未来填写内容（架构到达后）

- ORM / 驱动选型
- 数据库选型与迁移策略
- Schema / 表数量 / 字段类型 / 具体索引
- 查询模式与命名约定
- 数据保留策略
