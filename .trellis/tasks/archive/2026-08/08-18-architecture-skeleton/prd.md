# Stage 1.1: Architecture Skeleton

## Goal

将 Stage 1.1 已确认的整体架构骨架沉淀到
`.trellis/spec/project/architecture.md`，形成可供后续 Stage 1.2-1.11 继续扩展的
Draft / In Progress 文档。

## Requirements

- 只进行文档映射与工程化整理，不创建业务代码。
- 将架构状态从纯 Pending 更新为 `Draft / In Progress`。
- 记录一级分层：`Data Plane` 与 `Query Plane`。
- 记录 Query Plane 主链路：`Router → Planner（复杂请求）→ Agent Runtime → Tools → Retrieval/Analysis → Evidence → Answer`。
- 记录 Data Plane 的职责与数据流：原始群聊数据 → Ingestion → Normalizer → Canonical Message Store → Indexes。
- 记录 Query Plane 的职责与数据流：用户问题 / 查询上下文 → 路由与调查执行 → 证据型回答。
- 固化已确认职责边界：Router 管执行复杂度；Planner 管复杂问题拆解；Agent 通过 Tool Layer 访问 Data Plane；Trivae 自有业务核心包括 Retrieval、Evidence、Evaluation；Agent Runtime 采用成熟 SDK 能力并保留薄适配层。
- 明确 Retrieval 与 Evidence 的概念边界，但不定义其具体数据模型或算法。
- 保留未讨论内容为 `Pending architecture specification`，不自行补齐方案。

## Acceptance Criteria

- [x] `architecture.md` 状态为 Draft / In Progress，而非 Completed。
- [x] 文档包含 Data Plane、Query Plane、模块职责边界和数据流图。
- [x] 文档包含 Confirmed Decisions 与 Pending Decisions 两个清晰部分。
- [x] Pending 清单覆盖 Data Model、Ingestion、Retrieval、Tool Layer、Router 策略、Planner Schema、Evidence/Citation、Trace、Evaluation、CLI/API、Package Layout 等未确认事项。
- [x] 本任务不产生业务代码、不安装业务依赖、不改变 package/module boundary。
- [x] 文档没有把 ChatLab 参考实现或未验证假设写成 Trivae 的最终决策。

## Notes

- 本任务是轻量文档任务，`prd.md` 足够，不创建 `design.md` 或 `implement.md`。
- Stage 1.1 完成后，继续进入 Stage 1.2：Data Model + Ingestion；不在本任务中实现。
