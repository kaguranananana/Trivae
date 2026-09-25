# Planner Utility Evaluation

## Goal

在当前生产 Query 链路上，隔离 `SoftPlanner` 的额外调用与 soft guidance，测量其对最终任务结果、可靠性、行为、延迟和实际 Provider usage 的影响。生产 Router 保持 `shadow`。

## 运行前冻结的假设

1. 对 dependent multi-stage investigation、evidence-dependent investigation、temporal evolution reasoning 或 recovery Query，forced planned 应改善最终任务完成质量。
2. 对 direct lookup、count、ranking、aggregation 和普通 summary Query，Planner 不应带来稳定质量收益；质量相同且增加调用、延迟或 token 属于 overhead。
3. Planner 的错误 guidance、无效 tool suggestion、生成失败或上下文噪声可能使 standard 能完成的 Query regression。

以上是假设而非标签或结果；运行后不按观测修改定义。

## Requirements

- 复用 37 条人工 GT 裁决的 `resume-benchmark-dev-v1` Development Case；Calibration 和已暴露 Holdout 均不进入主分母。Router Jev 的 16 条诊断 Case 仅辅助解释 taxonomy，缺少答案 GT 时不参与答案质量结论。
- 对相同 Query、Snapshot、代码、主 Provider/Model、Retrieval、Runtime、Tool、Evidence/Citation 与 Answer Generation 执行 37×2×1；Variant 的唯一处理差异是 `execution_override.forced_route`。
- 正式运行前做 Provider/Planner、数据库、索引、ExecutionScope、Variant、输出 create-only 和独立 Evaluation Store preflight；先做独立 smoke。
- 保留每次尝试的 raw/Evaluation/Trace 对齐、失败归因和 Provider 实际返回的 usage。单次失败不得覆盖或隐藏。只从实际 Provider 字段报告 cost，缺失时标 `unavailable`。
- 按 Case 配对分析现有 deterministic/GT 指标、完成率、Planner 调用与失败、Tool 行为、端到端及 Planner 延迟、usage。无法由自动指标判定的答案差异生成 review packet，并保持待人工裁决状态；Tier 2 Judge 若使用，仅为 `llm_assisted_provisional`。
- 主 74 run 完成后，只对少量信息量高的 Case 做独立 3-repetition stability；不并入主分母。
- 将 Planner utility 与 Jev route classification 分层解释；不改变生产 Router mode，不覆盖任何历史 benchmark artifact。

## Acceptance Criteria

- [ ] Task/design 与 Variant 在正式运行前冻结；两个 Variant 的配置差异仅为 forced route。
- [ ] Smoke 证明两条路径均经过 `TrivaeApplication.query()`，planned 有 Planner Trace、standard 无 Planner 调用，其他身份相同。
- [ ] 完整 Development 运行或明确记录阻断事实；expected/raw/Evaluation/Trace 逐项核验，保留失败。
- [ ] 以可复核的 paired 判定规则报告 better/same/worse 与不可判定，并分开报告 targeted repeat。
- [ ] 报告条件收益、无收益、regression、成本和 taxonomy 证据边界；明确不能声称 fresh Holdout 或 Judge 人工准确率。
- [ ] 相关 ADR/Evaluation 文档更新；执行 Trellis validate、pytest、Ruff、mypy、diff check；提交并归档，最终 worktree clean，不 push。
