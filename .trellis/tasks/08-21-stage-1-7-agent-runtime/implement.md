# Implement: Stage 1.7 Agent Runtime 架构决策沉淀

> 文档沉淀任务的执行计划。无业务代码。

## 目标文件

1. 新建 `.trellis/spec/project/technical-decisions/stage-1-7-agent-runtime.md`（ADR，Confirmed）
2. 更新 `.trellis/spec/project/technical-decisions.md`（索引）
3. 更新 `.trellis/spec/project/architecture.md`（架构文档）

## 步骤

### 1. 新建 ADR `stage-1-7-agent-runtime.md`

参照 `stage-1-6-planner.md` 的结构与文风，但内容来自 `prd.md` 16 项决策 + `research/stage-1-7-user-proposal.md`。

结构（对齐 Stage 1.6 ADR）：

- 头部：`# Stage 1.7: Agent Runtime Decisions`，状态 **Confirmed（Stage 1.7）**，说明已沉淀未实现。
- `## 0. Architecture Governance`：引用 ChatLab Reference Implementation 原则；说明与 ChatLab 的关系（继承 Thin Agent Core 架构，SDK 从 `@earendil-works/pi-agent-core` 换为 OpenAI Agents SDK，属于技术实现差异而非架构翻案）；参数可直接继承但标注来源 + Evaluation 校准。
- `## 1. Initial Design / Context`：Stage 1.6 遗留边界（Planner→Runtime adapter、Session/Streaming/Abort、Conversation Context）；Evidence / Rationale；Candidate Solutions。
- `## 2.~N.` 逐条 Decision（每条含 Decision / Why / Trade-off / Failure Case 或 Result），覆盖：
  1. Thin Agent Runtime + SDK 承载通用 Loop（含 OpenAI Agents SDK 选型与薄适配层、替换面）
  2. Runtime 职责边界（不吞 Router/Planner/Retrieval/Evidence；单 Agent；same runtime both routes）
  3. Query Execution Orchestration 与 Agent Runtime 的区分
  4. RuntimeContext（local）与 Agent Model Context（LLM-visible）分离；Data Access Scope 硬执行
  5. Conversation History：Trivae Store 为 source of truth；v1 不用 SDK Session；Context Compiler 链路
  6. 预运行 Context 压缩（不做 mid-run compaction；数字不冻结）
  7. 终止条件两层（Trivae Tool Investigation Budget + graceful final synthesis；SDK max_turns 兜底 → 显式 Failure）
  8. Tool Error ≠ Runtime Failure（error envelope 回传 Agent；terminal failure 列表；Error Code 留 Stage 1.9）
  9. Abort 生命周期（terminal intent；immediate cancel；COMPLETED 以 SDK Run 完成为准）
  10. Streaming canonical path（SDK StreamEvent → adapter → Trivae Runtime Event；禁止直出 SDK 类型）
  11. Runtime lifecycle 状态机（CONTEXT_PREPARING → ROUTING → PLANNING → AGENT_PREPARING → RUNNING → FINALIZING → COMPLETED；任意阶段 ABORTED/FAILED）
  12. Planner→Runtime adapter（Validated Plan → Plan Guidance Renderer → soft instructions；effective_system_prompt）
  13. SDK built-in Trace 不当正式 Trace（external tracing 默认关闭；→ Trivae normalized events → Stage 1.9）
  14. 明确不引入清单（15 项）
  15. ChatLab 继承范围 + 参数继承口径（可直接继承、标注来源、Evaluation 校准；max_tool_rounds / max_turns / history window 等具体数字 Pending）
- `## Confirmed Architecture Decisions` 表。
- `## Pending Decisions`（按 Implementation / Stage 1.8 / 1.9 / 1.10 归属）。
- `## Validation / Regression`（实现阶段应验证的语义契约清单）。
- `## Result、Trade-off 与 Reopen Conditions`。

### 2. 更新 `technical-decisions.md`

- 顶部状态说明行：追加 Stage 1.7 指向。
- ADR 列表表格：新增 Stage 1.7 行（Confirmed / Agent Loop · SDK · Runtime lifecycle / stage-1-7-agent-runtime.md）。
- 底部 `## 当前记录`：新增 `### Stage 1.7：Agent Runtime` 小节（状态、内容摘要、记录位置、后续 Stage 1.8 / 1.9 / 1.10）。
- 更新 Stage 1.6 小节"后续"行：Stage 1.7 已确认 Agent Loop / SDK / Runtime lifecycle（其余指向保持不变）。

### 3. 更新 `architecture.md`

- 头部状态块与 Status 表：Stage 1.6 completed 后追加 Stage 1.7 Agent Runtime completed（架构已沉淀，尚未实现）。
- High-Level / Query Plane 概念流：确认 Agent Runtime 下接 OpenAI Agents SDK Runner；可小幅补充 RuntimeContext / Model Context 分离提示（不改 Stage 1.5/1.6 内容）。
- 新增 `## Stage 1.7: Agent Runtime` 章节（稳定契约摘要 + Confirmed 摘要 + Pending 归属）。
- Module Boundaries 的 Agent Runtime 小节：更新为 OpenAI Agents SDK 薄适配、RuntimeContext / Model Context 分离、生命周期状态、budget / abort、streaming / event normalization；标注 SDK 具体版本、adapter 契约、Session、Streaming、Abort 与 Run Lifecycle 细节仍 Pending。
- `## Confirmed Decisions`：追加 `### Stage 1.7：Agent Runtime` 列表（15 项左右）。
- `## Pending Decisions`：更新"Agent Runtime 的具体 SDK 版本、Adapter 契约、Session、Streaming、Abort 与 Run Lifecycle 细节"行（已确认架构、具体实现 Pending）；把 `max_tool_rounds`、SDK `max_turns`、history window、compression threshold、tool-result token budget、tool 并发策略、Runtime Event Schema（Stage 1.9）等列入。
- ChatLab 继承偏离段：新增 OpenAI Agents SDK 映射方向确认（替换面 runtime/tools adapter）、参数可直接继承但标注来源。

### 4. 校验

- `python3 ./.trellis/scripts/task.py validate 08-21-stage-1-7-agent-runtime`
- 用 `grep` 交叉检查三份文档间链接、术语、Stage 编号一致；确认 Stage 1.2–1.6 已确认内容未被改动（`git diff` 只应包含三个目标文件）。
- 无业务代码、无伪造参数数字。

## 验收 / 检查门

- 三份文档均含 Stage 1.7 且状态一致。
- ADR 覆盖 16 项决策 + 参数继承口径。
- `git diff` 仅涉及三个目标文件。
- 交给用户 review 后提交（docs 前缀，中文 commit message）。
