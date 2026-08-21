# PRD: Stage 1.7 Agent Runtime 架构决策沉淀

> 本文定义本次文档沉淀任务的需求与验收标准，不包含技术设计细节（设计见 `research/stage-1-7-user-proposal.md` 与最终 ADR）。

## 背景

Trivae 现有 Stage 1.1–1.6 文档与 ChatLab 当前实现已对齐。Stage 1.7 需要确定 **Agent Loop / SDK / Runtime lifecycle**，并承接 Stage 1.6 遗留的 Planner→Runtime adapter、Session / Streaming / Abort、Conversation Context 控制边界。

核心方向：**继承 ChatLab 的 Thin Agent Core 架构，由 OpenAI Agents SDK 承载通用 Agent Loop；Trivae 自己拥有外层执行编排、Context、Conversation History、Tool Adapter、生命周期语义和事件契约。**

用户已提供完整架构提案（见 `research/stage-1-7-user-proposal.md`），本任务把它沉淀为正式项目文档。

## 交付物

1. **新建 ADR**：`.trellis/spec/project/technical-decisions/stage-1-7-agent-runtime.md`，按 Stage 1.6 ADR 的结构与风格（Architecture Governance → Initial Design / Context → 逐条 Decision 的 Decision / Why / Trade-off / Failure Case → Confirmed Decisions 表 → Pending Decisions → Reopen Conditions → Validation）编写，状态标记 **Confirmed（Stage 1.7）**。
2. **更新索引**：`.trellis/spec/project/technical-decisions.md`——顶部状态说明行、ADR 列表、当前记录新增 Stage 1.7 条目，并更新 Stage 1.6 的"后续"指向。
3. **更新架构文档**：`.trellis/spec/project/architecture.md`——头部状态、新增 Stage 1.7 章节、更新 Agent Runtime 模块边界、Confirmed Decisions、Pending Decisions、ChatLab 继承 / 偏离说明。

## 必须反映的已确认决策（16 项）

1. **Thin Agent Runtime**：继承 ChatLab 架构，不自行重写通用 Agent Loop；Agent Loop 由 OpenAI Agents SDK 承载。
2. **Runtime 职责边界**：Runtime 不重新吞掉 Router / Planner / Retrieval / Evidence；`standard_execution` 与 `planned_execution` 使用同一个 Runtime。
3. **Query Execution Orchestration vs Agent Runtime**：外层编排负责整个 Query 生命周期（Context Assembly → Router → Planner → Runtime）；Agent Runtime 专指 Agent Loop 之后的执行核心。
4. **Runtime 只负责**：驱动模型与 Tool 之间的 bounded Agent Loop，提供稳定 streaming / cancellation / termination / result boundary；单 Agent，第一版不引入 handoff / multi-agent。
5. **SDK 选型**：OpenAI Agents SDK（Python），通过 `Trivae AgentRuntime interface → OpenAIAgentsRuntimeAdapter → SDK` 薄适配层使用；业务代码不直接 import SDK 类型；未来替换只涉及 runtime adapter 与 tool adapter。
6. **两种 Context 分离**：`RuntimeContext`（local，不发给 LLM：run/request identity、conversation identity、data_access_scope、capability dependencies、database/retrieval handles、cancellation state、runtime budgets）与 `Agent Model Context`（LLM-visible：system instructions、bounded conversation context、current request、query-context projection、compact session/data metadata、validated plan guidance）。**Data Access Scope 必须在 Tool / Capability 执行路径强制执行，不能只写进 system prompt 靠模型自觉。**
7. **Conversation History**：Trivae Conversation Store 是 source of truth；v1 不用 SDK Session 作为 canonical 存储；`Conversation Store → Context Compiler → SDK-compatible items → Runner`。
8. **Context 压缩在 Run 之前**：不引入 mid-run compaction；机制确定（history window / summary threshold / summary budget / tool-result retention / compression model），数字不冻结。
9. **终止条件两层**：Trivae Tool Investigation Budget（耗尽 → 禁用 Tool → 注入"基于已收集信息给出最终回答" → final synthesis）+ SDK `max_turns`（absolute safety backstop → 撞到则显式 Runtime Failure）。继承 ChatLab 的 graceful final synthesis 语义。
10. **Tool Error ≠ Runtime Failure**：Tool 返回 `status=error` + `error.code`（如 `CAPABILITY_UNAVAILABLE`），Agent 自行决定恢复；只有 model/provider fatal、SDK invariant、无法构造有效模型输入、absolute loop limit、unrecoverable context overflow 才是 terminal failure；Error Code 具体命名留给 Stage 1.9。
11. **Abort = terminal intent**：abort 前不启动 / 流式中取消模型运行 / Tool 中继续传播 / 轮间不再开始下一轮 → `ABORTED`，不执行 final synthesis；区别于 Tool Budget 耗尽；v1 用 immediate cancel；`COMPLETED` 以 SDK Run 真正完成为准。
12. **Streaming 为 canonical path**：`SDK StreamEvent → OpenAIAgentsRuntimeAdapter → Trivae Runtime Event → CLI / API / UI`；禁止 FastAPI 直接返回 SDK StreamEvent。
13. **Runtime lifecycle**：`CONTEXT_PREPARING → ROUTING → (PLANNING) → AGENT_PREPARING → RUNNING(RESPONDING / TOOL_RUNNING) → (FINALIZING) → COMPLETED`；任意阶段 `ABORTED` / `FAILED`。ROUTING / PLANNING 属于 Query 生命周期，不属于内部 Agent Loop。
14. **Planner→Runtime adapter**：`Validated Plan → Plan Guidance Renderer → LLM-visible soft instructions → Agent Runtime`；Runtime 不读取 plan.steps 逐条执行；`effective_system_prompt = system_prompt + buildPlanGuidance(plan)`。
15. **SDK built-in Trace 不当正式 Trace**：SDK external tracing 默认关闭；`SDK Hooks / Stream Events → Trivae normalized events → Stage 1.9 Trace Collector`；Trace Schema 留给 Stage 1.9。
16. **明确不引入**：hand-written 通用 Agent Loop、Multi-Agent、Agent Handoff、Planner Agent Loop、Plan-and-Execute / Step Executor、Workflow Engine、Automatic Replanning、Runtime-owned Evidence State Machine、SDK Session 作 canonical 存储、SDK 类型泄漏进 Capability Layer、mid-run 自动压缩、应用级自动 model fallback、应用级 retry loop、自定义 Tool orchestration scheduler、硬编码 Retrieval workflow。

## 参数口径（用户明确要求）

- 参数不卡死：`max_tool_rounds`、SDK `max_turns`、history window、compression threshold、tool-result token budget、tool 并发策略、agent model、prompt 文案等不冻结为具体数字，标注为 Pending Evaluation。
- **ChatLab 经验参数可直接继承**：作为 v1 baseline 直接继承是允许的（它是经验参数），但必须在文档中标注**继承来源**，并保留 Evaluation 校准路径；不是无条件"抄死"，也不是"拒绝继承"。

## 验收标准

- [ ] `stage-1-7-agent-runtime.md` 存在，状态 **Confirmed（Stage 1.7）**，结构与既有 ADR 一致，覆盖上述 16 项决策与参数口径。
- [ ] `technical-decisions.md` 的顶部状态说明、ADR 列表、当前记录三处与 Stage 1.7 同步，Stage 1.6 后续指向 Stage 1.7 已确认内容。
- [ ] `architecture.md` 头部状态更新为包含 Stage 1.7；新增 Stage 1.7 章节；Agent Runtime 模块边界更新（含 OpenAI Agents SDK 薄适配、RuntimeContext / Model Context 分离、生命周期）；Confirmed Decisions / Pending Decisions / ChatLab 继承偏离说明同步。
- [ ] 文档间链接、术语、阶段编号一致；不改动 Stage 1.2–1.6 已确认内容。
- [ ] 不引入任何业务代码；不伪造 Evaluation 参数数字。
- [ ] `task.py validate <name>` 通过；`trellis-check` 完成一致性检查。
