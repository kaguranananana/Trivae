# Planner Quality Calibration PRD

## Problem

Plan structural validity 已基本成立，但 Plan semantic utility / incremental value 未建立。已暴露 Development Trace 包含实体被类别词稀释、上下文锚点关系不清、无关工具建议及确定性问题过度规划。旧 v2 dependent Trace 的首个 `mattpocock` 检索完整，后续 Runtime 的 `skills` 检索变成 100/244 partial；这首先是 Runtime 查询决策失败，不能倒推 Planner 是唯一根因。另有 Planner r2 文本本身允许 `mattpocock 或 skills`，本任务单独校准这类软指导质量。

## Goal

提高 Planner guidance quality，并建立 Planner-only Evaluation，判断 P1 是否更稳定地产生高信息量、低误导、工具相关、符合证据关系的 Soft Plan。

## Requirements

- 保持 Stage 1.6 的单次 SoftPlanner、现有 Plan schema、bounded parsing、未知工具过滤、失败 graceful skip、同一 Runtime。
- Planner 使用真实已注册 Tool 的 canonical purpose，并提供简短、独立且只用于规划的选用约束；`available_capabilities` 始终是可用性和合法性来源，Router contract 不扩充。
- Prompt 明确实体保留、direct hit 与后续反馈的证据关系、每步信息增量、工具选择纪律、简单/确定性问题少规划，以及 zero-result 已有规则。
- Provider-free tests 锁定上述输入与 prompt contract、过滤/边界/失败行为；不锁模型的自然语言输出。
- 对已暴露 Development Case 运行 P0/P1 多次 Planner-only 实验；保存每次的 prompt 版本、Provider 观测、完整 Plan 或失败和盲审包。成本未返回时记录 unavailable。
- 人工 adjudication 与 assistant provisional analysis 分开；不把 Planner-only 结果当最终答案收益。

## Acceptance criteria

1. 至少六个真实 Development Case，包含 dependent、archify、aggregation、zero-result、long-range/trend、simple lexical；逐 Case 记录来源。
2. P0/P1 对每个 Case 至少重复运行，记录 run ID、provider/model、latency、token、finish_reason、parse/failure、Plan JSON 和 cost availability；没有 Runtime Tool Loop。
3. Rubric 分别覆盖 entity preservation、scope discipline、tool relevance、incremental value、evidence alignment、context relation、redundancy、overplanning、failure rate；不机械压成总分。
4. 盲审包按 Case 随机 A/B，不泄露版本映射，允许 A better/B better/indifferent/uncertain 与理由。
5. `pytest -q`、`ruff check src tests`、`mypy src`、`git diff --check` 通过；新增代码关键逻辑有简体中文注释。

## Non-goals

- 不证明 Planned treatment 提高最终答案，不运行 Standard/Planned E2E、Router Utility、新 Holdout 或 sealed 数据。
- 不修改 Router/Jev、Runtime Tool Loop、Retrieval、Evidence/Citation、zero-result proof、任何自动重试/continuation/replan。
- 不生成工具参数、SQL、message ID、分支/依赖/状态或任何可执行 workflow 字段。

## Sources

- Stage 1.6/1.10 ADR、engineering principles、planner utility Development manifest、v2/v3 Trace 归因和 human review。
- ChatLab `3e0e0fbbfb2b80051d261d34bf8349d64ab4c6e8` 的 Planner、types、tests、router 和 capability guidance 接线。
