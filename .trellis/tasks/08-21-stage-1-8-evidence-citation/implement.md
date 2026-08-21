# Implementation Plan: Stage 1.8 Evidence / Citation 架构文档沉淀

> 本任务只修改项目架构文档，不实现业务代码。

## 1. 新增 Stage 1.8 ADR

- 新建 `technical-decisions/stage-1-8-evidence-citation.md`。
- 按既有 ADR 风格记录 Architecture Governance、Context、逐项 Decision、Reason、Trade-off、Failure Case、Confirmed Decisions、Deferred、Reopen Conditions 与 Validation。
- 引用 ChatLab commit `f9b87c00` 的具体文件证据，明确继承与偏离。
- 覆盖 `design.md` 的全部语义，但不把 conceptual field name 伪装成已冻结 Python / JSON Schema。

## 2. 更新 Architecture

- 更新头部阶段状态为 Stage 1.1–1.8 已确认、Stage 1.9–1.11 Pending。
- 扩写 `Evidence` 与 `Answer Generation` 模块边界。
- 将主链路更新为 `Retrieval / Structured Result → Evidence Selection / Organization → Final Evidence → Citation-bound Answer`。
- 写入 Answer Artifact、claim Citation、Evidence Item、Message / Structured Result Source、validation、persistence、bounded source review 与 evidence-aware stopping。
- 更新 Confirmed Decisions、Pending Decisions、ChatLab inheritance / deviation 与 Stage 1.7 pending 引用。
- 不改写 Stage 1.2–1.7 已确认决策；只消除已由 Stage 1.8 解除的 Pending 描述。

## 3. 更新 Technical Decisions 索引

- 在 `technical-decisions.md` 新增 Stage 1.8 ADR 链接和摘要。
- 把顶部状态、当前记录、Stage 1.7 后续项与 Stage 1.8 / 1.9 边界同步。
- 保留具体 Schema / Trace / Evaluation / 参数为 Pending。

## 4. 更新项目状态文档

- `overview.md`：状态更新为 Stage 1.8 完成、下一阶段 Stage 1.9 Trace / Observability。
- `workflow.md`：当前阶段约束更新为 Stage 1.8 completed、Stage 1.9 pending，继续禁止提前实现业务功能。
- 必要时同步 `engineering-principles.md` / `logging-guidelines.md` 中 Evidence Selection、Final Evidence、Citation-bound Answer 的术语；只改存在冲突或缺口的行，不扩写 Stage 1.9 Trace Schema。
- 核对 `database-guidelines.md` 的 Message Identity / source tracing 表述是否已足够；无真实缺口则不改。

## 5. Consistency Review

- 检查 `Retrieval Candidate`、`Final Evidence`、`Evidence Item`、`Citation`、`Source Locator`、`sufficiency`、`partial / coverage / truncated` 的跨文档语义一致。
- 检查 Planner `evidence_needed` 仍只是 requirement，Runtime 仍无 Evidence State Machine，Tool Layer 仍无 `retrieve_evidence`。
- 检查 Message Source 显式 session identity，Structured Result 不伪装成 Message Source。
- 检查 Citation validation 没有被描述为 semantic correctness validator。
- 检查应用内只展示 bounded context，全量上下文留给原社交平台。
- 检查无固定关键词 Judge、固定时间聚类、silent citation drop、自动 fallback / repair。

## 6. Validation Commands

```bash
python3 ./.trellis/scripts/task.py validate 08-21-stage-1-8-evidence-citation
git diff --check
rg -n "Stage 1\.8|Evidence Item|Citation|Source Locator|evidence-aware" .trellis/spec/project
rg -n "retrieve_evidence|included / excluded / uncertain|Runtime-owned Evidence" .trellis/spec/project
```

文档任务无需运行应用测试；若项目已有 Markdown link / lint 命令，按仓库实际可用命令补充执行。最终使用 `trellis-check` 做规格一致性审查。

## 7. Risk / Rollback Points

- 最大风险是把 conceptual contract 写成过早冻结的实现 Schema；审查时逐项保留“语义冻结、字段名与序列化 Pending”的口径。
- 第二风险是 Stage 1.8 反向修改 Stage 1.4 / 1.7 边界；任何 `retrieve_evidence` Tool、Evidence Agent 或 Runtime Evidence State Machine 表述都必须阻止。
- 若正式文档更新出现冲突，回到本任务 `prd.md` / `design.md` 的 confirmed requirement 逐条比对，不用兼容段落同时保留互斥设计。

## 8. Completion Gate

- 所有验收项逐条映射到正式文档位置。
- PRD、Design、ADR、Architecture、Technical Decisions 与状态文档无冲突。
- ChatLab 继承 / 偏离均有 commit 与代码路径证据。
- `task.py validate`、diff check、链接 / 术语检查与 `trellis-check` 通过。
- 质量审查完成后再进入 spec update、commit 与 `trellis-finish-work`。
