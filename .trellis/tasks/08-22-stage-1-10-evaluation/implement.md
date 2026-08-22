# Implementation Plan: Stage 1.10 Evaluation 架构文档

## Scope

本任务只修改架构与工程规范文档，不创建业务代码、Evaluation runner、Schema、Dataset 或真实 baseline。

## Ordered Checklist

1. 新增 `stage-1-10-evaluation.md`：
   - 按既有 ADR 风格写 Architecture Governance、Context、Decision、Reason、Result、Trade-off、Failure Case、Confirmed Decisions、Deferred、Validation 与 Reopen Conditions；
   - 以 `design.md` 的 32 项 Decision Set 为主线；
   - 写清 forced standard / forced planned → Planner Utility → Router Utility 的两阶段 counterfactual evaluation；
   - 写清 Reference completeness / provenance、pinned Baseline、blind pairwise review、Core Set refresh 与非字节级 reproducibility；
   - 纳入 11 个 Trivae-specific Design Seed，并明确不产生 gate；
   - 明确 ChatLab inherit / adapt / do-not-inherit；
   - 明确当前无真实 baseline，不写 numerical threshold、最优参数或虚假评测结果。
2. 更新 `technical-decisions.md`：
   - 顶部状态改为 Stage 1.2–1.10 已确认、Stage 1.11 Pending；
   - ADR 列表和当前记录新增 Stage 1.10；
   - Stage 1.3–1.9 的 Evaluation 后续统一指向 Stage 1.10 已确认架构，实际数字保持 Implementation / Real-run Calibration Pending。
3. 更新 `architecture.md`：
   - 新增 Stage 1.10 稳定架构章节；
   - 更新 Evaluation / Regression 横切章节；
   - 更新 Confirmed Decisions、Pending Decisions、ChatLab 继承 / 偏离和阶段顺序；
   - 区分已确认的 Evaluation contract 与尚未执行的 Dataset / baseline / thresholds / parameter calibration。
4. 回写旧 ADR 的 Pending 路由：
   - `stage-1-3-retrieval-architecture.md`：明确参数校准方法已由 Stage 1.10 确认，具体结果仍 Pending；
   - `stage-1-4-tool-capability-layer.md`：同步 Tool / Context 参数与 Specialized Tool 的 Evaluation 进入条件；
   - `stage-1-5-router.md`：同步 Case Bundle、paired comparison 与 Planner Utility；
   - `stage-1-6-planner.md`：同步 forced-path Planner Utility、bounds / intent / replan 的校准边界；
   - `stage-1-7-agent-runtime.md`：同步 budget / threshold、Tool concurrency 与 stochastic runs；
   - `stage-1-8-evidence-citation.md`：同步 entailment、sufficiency、Citation coverage、Judge 与 stopping / repair 进入条件；
   - `stage-1-9-trace-observability.md`：同步 Evaluation Artifact、post-run Diagnosis 和 Trace 不可改写边界。
5. 更新项目阶段状态：
   - `overview.md`；
   - `project/workflow.md`；
   - `engineering-principles.md`；
   - `backend/index.md`；
   - `backend/directory-structure.md`；
   - `backend/quality-guidelines.md`；
   - `backend/logging-guidelines.md` 中对 Stage 1.10 的历史 pending 表述。
6. 做全局一致性复核：
   - Stage 编号、状态和链接一致；
   - 旧 ADR 的历史 Context 不被误删，但当前 Pending 路由不再声称 Stage 1.10 尚未设计；
   - `Evaluation Case Bundle`、`Evaluation Suite`、`Controlled Variant`、`Evaluation Run / Review / Result`、`Failure Diagnosis`、`Regression Case` 术语一致；
   - Reference completeness / provenance、Baseline identity、Suite version 与 Snapshot reproducibility 语义一致；
   - 不把 operational metric 写成 quality proof；
   - 不把 ChatLab 经验数字写成 Trivae confirmed default。

## Validation Commands

```bash
python3 ./.trellis/scripts/task.py validate 08-22-stage-1-10-evaluation
rg -n "Stage 1\.10.*(pending|Pending|待开始)|Stage 1\.1–1\.9|Stage 1\.10-1\.11" .trellis/spec
rg -n "stage-1-10-evaluation" .trellis/spec/project
rg -n "Forced Standard|exhaustive|partial|unknown|blind pairwise|T-EVAL-0" .trellis/spec/project
git diff --check
git diff -- .trellis/spec .trellis/tasks/08-22-stage-1-10-evaluation
```

`rg` 命中需要逐条判断：旧 ADR 描述“当时尚未设计”的历史语句可以保留；当前状态、Deferred 与后续路由必须更新。

## Risky Areas

- **历史与当前状态混淆**：不能为了消灭搜索结果而改写旧 ADR 当时的决策背景；只更新当前状态和 Pending 路由。
- **虚假完成**：Stage 1.10 架构完成不等于 Dataset、runner、baseline、threshold 或参数校准已经完成。
- **指标越界**：不能让 Trace operational metric 自动变成 quality label，也不能让 Judge 成为在线业务依赖。
- **归因混淆**：不能用 Router 实际路径直接声称 Planner Utility；必须先用 forced-path 解耦。
- **Reference 假完整**：partial / unknown 标注不能机械用于强 Precision / Recall 结论。
- **Baseline 漂移**：不得使用 `main / current defaults` 作为长期 Baseline identity。
- **复现过度承诺**：外部模型只承诺条件可重建与统计可比较，不声称字节级重放。
- **旧决策重开**：Evaluation contract 不自动重开 Reranker、Message-level index、Replan、Specialized Tool 或 machine stopping；必须满足各自 Reopen Condition。
- **ChatLab 误继承**：三路 Router、固定关键词 Evidence Judge、固定时间 Evidence grouping 和具体参数数字不得进入 Trivae Confirmed Decisions。

## Rollback Points

- 新 ADR 是本次新增的权威入口；若交叉文档同步出现矛盾，先回到 ADR Decision Set 校正，再更新索引和汇总文档。
- 所有改动都是文档，可按文件逐一回退；不得用批量覆盖破坏 Stage 1.2–1.9 已确认内容。

## Pre-start Gate

- `prd.md` 完成收敛且无 blocking open question；
- `design.md` 覆盖 Evaluation 架构、ChatLab 继承边界、Failure Cases 与 Deferred；
- `implement.md` 列出全部同步文件与验证命令；
- `implement.jsonl` / `check.jsonl` 包含真实 spec / research 条目；
- 用户在最终规划摘要之后明确批准开始文档实现。
