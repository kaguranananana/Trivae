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

## 当前阶段约束（Stage 0 → 等待架构）

- 不编写业务代码，不创建未经确认的业务模块结构，不安装业务依赖。
- 基础设施只建立当前阶段真实需要的内容。