# Backend Development Guidelines

> Python 后端工程规范（M1 ingestion、M2/M3 retrieval/capability、M4a runtime baseline、M4 Query Execution Core、M5 Evidence/Citation、M5b Conversation persistence 与 M6 Trace/Observability 已落地；Stage 1.10 Implementation / Real-run Calibration 与 HTTP Product Interaction 仍待推进）。
> M1 的 SQLite、导入和目录可执行契约见各专题规范；M4 Query/Runtime、M5 Evidence、M5b Conversation、M6 Trace 与 CLI Product Experience 的具体代码模式见对应指南/Stage 1.9 record，其余 Evaluation/Product Plane 仍按后续任务补充。

---

## 工程原则（必读）

- 项目级长期原则：[../project/engineering-principles.md](../project/engineering-principles.md)
- 架构状态（哪些不能自行决定）：[../project/architecture.md](../project/architecture.md)

## 指南索引

| Guide | 内容 | 状态 |
|-------|------|------|
| [Directory Structure](./directory-structure.md) | 目录与文件组织（当前阶段） | 已填（Stage 1.11 概念 layout 与 M1 实际 ingestion layout） |
| [Error Handling](./error-handling.md) | 错误处理原则 | 已填 |
| [Logging Guidelines](./logging-guidelines.md) | 日志与可观测性原则 | 已填 |
| [Quality Guidelines](./quality-guidelines.md) | 测试与质量要求 | 已填 |
| [Agent Runtime Guidelines](./agent-runtime-guidelines.md) | M4 Query、Router/Planner、DeepSeek、SDK Tool、streaming 与 lifecycle 契约 | 已填 M4 |
| [Temporal Overview Guidelines](./temporal-overview-guidelines.md) | `get_recent_messages` 容量、keyset continuation、coverage、projection 与 Host 时间事实 | 已填 2026-08-28 |
| [Database Guidelines](./database-guidelines.md) | 数据库相关规范 | 已填 M1 SQLite、M2 Retrieval/FTS5 与 M5b Conversation Store contract；Semantic/Vector 与 migration/deployment 仍 Pending |
| [Product Experience Guidelines](./product-experience-guidelines.md) | CLI/Application source、scope、readiness、feedback、history 与 renderer contract | 已填 2026-08-25 |

---

## 语言约定

- 项目规范文档：中文；代码、命令、标识符：英文原文。
- 所有后续代码遵循本层各指南文件。
