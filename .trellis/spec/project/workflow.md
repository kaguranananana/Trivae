# Development Workflow

> 本项目开发工作流：以 Trellis 标准工作流（`.trellis/workflow.md`，Phase 1 Plan / Phase 2 Execute / Phase 3 Finish）为骨架，叠加以下项目规则。

---

## 标准流程（Trellis）

- **新任务**：先经 `task.py create` 进入 planning，产出 `prd.md`（复杂任务还需 `design.md` + `implement.md`），评审后 `task.py start` 进入实施。
- **实施**：`trellis-implement`（或 inline 模式直接实现）→ `trellis-check` 质量检查 → lint / type-check / tests 全绿。
- **收尾**：`trellis-update-spec` 沉淀新知 → 批量 commit → `/trellis:finish-work` 归档并记录会话。

## 项目规则

### 1. 架构未定时禁止自行决定

- 涉及 architecture.md 中 Pending 清单的任何决策：标记 `Pending architecture specification`，不实现、不补全。
- 发现架构问题：记录 `Problem / Evidence / Impact / Possible Options`，停止改动，等待决策。

### 2. 关键模块开发前置检查

开发 Router / Retrieval / Tool / Agent Runtime / Context / Evidence / Evaluation 等关键模块前，先回答 engineering-principles.md 第 6 节的 7 问，并把结论写入任务文档。

### 3. 重要改动必须验证

- 优先用 Test / Evaluation / Metric / Regression 证明改善，避免主观判断。
- 修复重要 Failure Case 后：保存 Failure Case → 加入测试集 → Regression Test。

### 4. 文档沉淀规则

- 重要问题 / 决策：按 problem-records.md 与 technical-decisions.md 沉淀。
- 普通小 Bug：不制造文档。
- 新约定 / 教训：`trellis-update-spec` 写入对应 spec。

### 5. 提交规范

- 按 Trellis Phase 3.4：工作 commit 在前，归档 + journal 等 bookkeeping commit 在后。
- 不 amend、不 push（除非用户明确要求）。
- commit message 与仓库既有风格保持一致。

## 当前阶段约束（Stage 1.10 Evaluation 与 Stage 1.11 Application Boundary 架构 completed；Implementation / Calibration pending）

- Stage 1.1 架构骨架、Stage 1.2 Data Model + Ingestion、Stage 1.3 Retrieval Architecture、Stage 1.4 Tool / Capability Layer、Stage 1.5 Router、Stage 1.6 Planner、Stage 1.7 Agent Runtime、Stage 1.8 Evidence / Citation 与 Stage 1.9 Trace / Observability 已完成；各阶段未冻结的具体参数仍由后续 Evaluation 校准。
- Stage 1.9 已完成 normalized event、Failure Attribution、query-scope coverage、Error Code ownership、`normal / debug` Trace Profile、model-visible content capture、retention / privacy 与 Trace storage 原则沉淀但尚未实现；具体 Python / JSON Schema、Error Code 枚举、capture policy、Collector / Store backend 与 retention 时长保持 Implementation Pending。
- Stage 1.10 已确认 Case Bundle、Finding-level Reference completeness / provenance、versioned Suite、pinned Baseline、除 Planner 变量外其余条件相同的 forced-path Planner Utility、blind paired review、Failure Regression 与可重建 Snapshot 的架构契约，但尚未实现 Dataset / Snapshot、runner、Review workflow、具体 Schema、真实 stable baseline、numerical threshold 或参数校准。
- Stage 1.11 已确认单 Python distribution、`src/trivae` 概念 package ownership、Composition Root、统一 Application / QueryOrchestrator、CLI / API / Evaluation 薄入口、Application-level QueryRequest、Normalized Event / Error projection 与 `/api/v1` 边界；尚未实现业务 package、具体 Schema、框架版本、runner、API wire contract 或产品交互。
- 当前不把 Design Seed、ChatLab-derived seed、静态结构测试或 operational metric 当作真实质量 baseline；不提前填充数值 gate、重复次数、统计方法或最终参数。
- Evidence 实现必须保持 `Candidate Data → Final Evidence → Citation-bound Answer` 边界；不得新增 `retrieve_evidence` Tool、固定关键词 Judge、Evidence Agent、Runtime-owned Evidence State Machine、silent citation drop 或无依据 repair / retry。
- 在对应架构细节确认前不编写业务代码、不创建未经确认的业务模块结构、不安装业务依赖；Stage 1.11 已确认概念 package 边界，但实际 `src/trivae` 文件仍须在实施任务中按 ADR 落地。
- `architecture.md` 保持 `Draft / In Progress`；未确认内容必须标记 `Pending architecture specification`。
- Stage 1.10 的 Implementation / Real-run Calibration 与 Stage 1.11 Implementation / Product Interaction 按主题逐层推进，不提前填充其他架构细节；Stage 1.11 Application Boundary 的确认内容见对应 ADR。
- 基础设施只建立当前阶段真实需要的内容。
