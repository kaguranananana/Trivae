# Implementation Plan: Stage 1.11 应用边界与工程结构架构文档

## Scope

本任务只修改 Trellis 项目规范与架构文档，不创建业务代码、Python distribution、CLI / API、Evaluation runner、Schema 或测试实现。

## Ordered Checklist

1. 新增 Stage 1.11 ADR：
   - 冻结单 Python distribution、`src/trivae` 概念布局和 package ownership；
   - 明确 CLI、HTTP API、Evaluation、Composition Root、Application Service 与 QueryOrchestrator 的关系；
   - 写清统一 `QueryRequest`、Normalized Event Projection、Trace / Error correlation；
   - 写清依赖方向、SDK 隔离、Tool / CLI / API surface 分离；
   - 写清 ChatLab inherit / adapt / do-not-inherit；
   - 写清 Failure Cases、Validation、Implementation Pending、Real-run Calibration Pending 与 Reopen Conditions。 [x]
2. 更新 `technical-decisions.md`：
   - 新增 Stage 1.11 ADR 索引；
   - 将当前 Stage 1.11 状态从 Pending 更新为 Confirmed / Completed（架构已沉淀，尚未实现）；
   - 保留 Stage 1.10 Implementation / Real-run Calibration 与各模块具体 Schema / 参数的 Pending 语义。 [x]
3. 更新 `architecture.md`：
   - 在高层架构中补充 External Interface / Application Boundary；
   - 新增 Stage 1.11 汇总章节与 Confirmed Decisions；
   - 将 Module Boundaries、Cross-Cutting Concerns、Pending Decisions 与阶段状态同步到新的 ADR；
   - 明确架构完成不等于业务代码实现完成。 [x]
4. 更新阶段状态与目录规范：
   - `overview.md`：补充 Stage 1.11 架构已确认及实现仍 Pending；
   - `project/workflow.md`：更新当前阶段约束、允许落地的 package boundary 与尚未实现项；
   - `backend/index.md`、`backend/directory-structure.md`：记录概念 layout 已由 Stage 1.11 定义，但业务目录尚未创建；
   - `backend/logging-guidelines.md`、`backend/quality-guidelines.md`：同步 Application / Trace / Evaluation 的职责与 Pending 路由（仅在现有表述需要时修改）。 [x]
5. 全局一致性复核：
   - 搜索 Stage 1.11、Stage 1.1–1.10、Application Boundary、QueryOrchestrator、QueryRequest、Composition Root、Evaluation runner 等表述；
   - 保留旧 ADR 的历史背景，但不让当前状态继续声称 Stage 1.11 尚未设计；
   - 确保所有新链接可解析、Stage 状态一致、术语一致；
   - 确保没有把 Typer / FastAPI 具体版本、真实 baseline、数值 threshold、ChatLab 参数或业务实现写成 Confirmed。 [x]
6. 质量检查：
   - `git diff --check`；
   - 运行文档链接 / Stage 状态 / 关键术语的 `rg` 检查；
   - 读取新增 ADR 和同步后的索引、架构状态文件，确认没有重复或相互矛盾的 Pending 清单。 [x]

## Validation Commands

```bash
python3 ./.trellis/scripts/task.py validate 08-22-stage-1-11-application-architecture
rg -n "Stage 1\.11|Application Boundary|QueryOrchestrator|Composition Root|QueryRequest|single Python distribution|src/trivae" .trellis/spec
rg -n "Stage 1\.1–1\.10|Stage 1\.1-1\.10|Stage 1\.11.*(pending|Pending|待推进|未设计)" .trellis/spec
rg -n "Typer|FastAPI|OpenAI Agents SDK|WebSocket|MCP|Daemon|self-update" .trellis/spec/project/technical-decisions/stage-1-11-application-architecture.md .trellis/spec/project/architecture.md
git diff --check
git diff -- .trellis/spec .trellis/tasks/08-22-stage-1-11-application-architecture
```

`rg` 命中需要逐条判断：旧文档的历史 Context 可以保留；当前状态、Confirmed Summary、Deferred 与后续路由必须指向 Stage 1.11 ADR。

## Risky Areas

- **架构完成与实现完成混淆**：Stage 1.11 只确认边界和 ownership，不代表 `src/trivae`、CLI、API 或 Evaluation 已存在。
- **把推荐实现写成硬约束**：Typer / FastAPI / SSE 只能作为实现方向，具体版本、wire schema 和依赖选择保持 Pending。
- **重复定义跨层 contract**：CLI、API、Evaluation 不能各自拥有独立 Query Schema、Stream Event 或 Error semantics。
- **Evaluation 旁路生产核心**：必须明确 forced path / Variant 是 Application-level override，而不是第二套 Agent。
- **ChatLab 物理结构误继承**：单 distribution 是对当前 v1 约束的适配；不应引入无证据的多 workspace packaging。
- **同步文件过度扩张**：只更新当前状态、路由和确有必要的概念摘要，不重写前序 ADR 的历史决策。

## Rollback Points

- 先以 Stage 1.11 ADR 作为唯一新决策源；如果汇总文档出现矛盾，回到 ADR 的 Decision / Deferred 校正索引和状态文件。
- 所有改动均为文档，可按文件回退；不得批量覆盖 Stage 1.1–1.10 既有决策内容。
- 若发现某项实际属于 Stage 1.10 Implementation / Real-run Calibration，应从 Stage 1.11 Confirmed 移回 Deferred，而不是扩大本任务范围。

## Pre-start Gate

- [x] 用户已同意按 Trellis 创建任务并进入规划；
- [x] 已读取项目架构、技术决策索引、Stage 1.2–1.10 相关 ADR、工程原则与 Thinking Guides；
- [x] PRD 已明确 Goal、In Scope、Out of Scope、Acceptance Criteria 与无阻塞 Open Questions；
- [x] `design.md` 已明确 data flow、package ownership、依赖方向、适配边界与 Deferred；
- [x] 已准备 `implement.md`、`implement.jsonl`、`check.jsonl`；
- [x] 用户批准本规划摘要后，已执行 `task.py start` 并修改正式架构文档。
