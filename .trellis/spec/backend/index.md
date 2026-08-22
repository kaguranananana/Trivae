# Backend Development Guidelines

> Python 后端工程规范（Stage 1.1–1.11 架构决策已完成；Stage 1.10 Implementation / Real-run Calibration 与 Stage 1.11 Implementation / Product Interaction 仍待推进；当前仍无业务代码）。
> 具体代码模式在正式架构与首份业务代码落地后补充。

---

## 工程原则（必读）

- 项目级长期原则：[../project/engineering-principles.md](../project/engineering-principles.md)
- 架构状态（哪些不能自行决定）：[../project/architecture.md](../project/architecture.md)

## 指南索引

| Guide | 内容 | 状态 |
|-------|------|------|
| [Directory Structure](./directory-structure.md) | 目录与文件组织（当前阶段） | 已填（Stage 1.11 概念 layout；业务实现前） |
| [Error Handling](./error-handling.md) | 错误处理原则 | 已填 |
| [Logging Guidelines](./logging-guidelines.md) | 日志与可观测性原则 | 已填 |
| [Quality Guidelines](./quality-guidelines.md) | 测试与质量要求 | 已填 |
| [Database Guidelines](./database-guidelines.md) | 数据库相关规范 | 部分已填（数据库无关原则）；选型 / Schema / 表设计仍 Pending architecture specification |

---

## 语言约定

- 项目规范文档：中文；代码、命令、标识符：英文原文。
- 所有后续代码遵循本层各指南文件。
