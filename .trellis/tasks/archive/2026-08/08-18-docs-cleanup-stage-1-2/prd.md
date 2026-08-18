# Docs cleanup before Stage 1.2

## Goal

清理 Stage 1.1 完成后的文档状态、术语和规则歧义，不改变架构方向，不生成业务代码

## Requirements

- 将 architecture.md、overview.md、workflow.md 统一为 `Stage 1.1 completed; Stage 1.2 Data Model + Ingestion pending / next`。
- 清理 backend spec 中的 Stage 0 残留，不改变未确认的 package/module boundary 或工具链选型。
- 统一 Retrieval 与 Evidence 术语：明确 `Retrieval Query`、`Retrieval Candidates / Results`、`Evidence Selection`、`Final Evidence` 的阶段差异。
- 将 Evidence 的“选中 / 排除 / 不确定”等具体状态模型重新标记为 Pending，仅保留需要独立 Evidence 模型的方向性决策。
- 简化 Query Plane 图，表达 Router 后可选 Planner、单一 Agent Runtime 与 Tool Layer 的关系，不暗示三个独立执行流水线。
- 放宽测试修改规则：禁止仅为让错误实现通过而修改测试；契约或正式架构变化、或测试本身错误时允许同步更新并记录原因。
- 放宽技术决策证据规则：参考设计不得直接视为最终结论，但证据来源可包括项目约束、Prototype、Test、Benchmark、Evaluation 或真实 Failure Case。
- 本任务只修改文档与 Trellis task 记录，不生成业务代码、不安装依赖、不推进 Stage 1.2 实现。

## Acceptance Criteria

- [x] 所有相关文档不再把当前阶段写成进行中的 Stage 1.1。
- [x] `architecture.md` 仍保持 Draft / In Progress，但明确 Stage 1.1 已完成、Stage 1.2 待开始。
- [x] Retrieval Result 与 Evidence 的术语在 engineering-principles.md、logging-guidelines.md、architecture.md 中不冲突。
- [x] `technical-decisions.md` 不再同时声称“无已确认决策”和“Stage 1.1 已确认架构方向”。
- [x] Evidence 状态模型、Router 具体执行分支和其他未确认内容仍明确标记 Pending。
- [x] `quality-guidelines.md` 与 `technical-decisions.md` 的规则允许正式契约变化时更新测试或采用非 Failure Case 类型的决策证据。
- [x] `git diff --check`、Trellis task validation 和文档占位符检查通过。

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
