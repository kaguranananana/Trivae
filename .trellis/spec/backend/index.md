# Backend Development Guidelines（历史）

> 这里索引旧后端规范和设计记录。阶段状态、默认配置和约束以各记录当时的背景理解。当前开发约定见 [AGENTS.md](../../../AGENTS.md)，实现入口见 [系统架构](../../../docs/architecture.md) 与 [配置指南](../../../docs/configuration.md)。

| Guide | 内容 |
| --- | --- |
| [Directory Structure](./directory-structure.md) | 历史目录与文件组织 |
| [Error Handling](./error-handling.md) | 错误处理原则 |
| [Logging Guidelines](./logging-guidelines.md) | 日志与可观测性原则 |
| [Quality Guidelines](./quality-guidelines.md) | 测试与质量要求 |
| [Agent Runtime Guidelines](./agent-runtime-guidelines.md) | M4 Query、Router/Planner、DeepSeek、SDK Tool、streaming、source identity / temporal evidence 与工程收口契约 |
| [ChatGPT Plan Guidelines](./chatgpt-plan-guidelines.md) | 官方 OAuth、账号隔离、受限 Responses、额度终止与 Provider 观测契约 |
| [Temporal Overview Guidelines](./temporal-overview-guidelines.md) | `get_recent_messages` 容量、keyset continuation、coverage、projection 与 Host 时间事实 |
| [Database Guidelines](./database-guidelines.md) | 数据库相关规范 |
| [Forwarded Message Guidelines](./forwarded-message-guidelines.md) | QQ 合并转发的派生检索、容器范围、双时间与 Citation 来源 |
| [Semantic Incremental](./semantic-incremental-guidelines.md) | 位置日志、安全重切、精确向量复用及 SQLite-vec 原子发布 |
| [QCE Auto Import](./auto-import-guidelines.md) | 稳定快照、持久增量、失败补偿、CLI 与 launchd 日历调度 |
| [Product Experience Guidelines](./product-experience-guidelines.md) | CLI/Application source、scope、readiness、feedback、history 与 renderer contract |
