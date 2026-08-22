# Stage 1.10 正式评审反馈收敛

## 评审结论

现有 Evaluation 架构约七八成可直接保留，但正式落 ADR 前需要补齐七个容易影响结论解释力或长期维护的边界。

## 必须吸收的高优先级调整

1. **Planner Utility 使用 forced-path / counterfactual evaluation**：先绕过 Router，对同一 Case 强制执行 standard 与 planned 两条路径，测出 Planner 本身的实际 Utility；再评价 Router 能否识别“Planner 确实有收益”的 Case，避免 Router 与 Planner 效果混淆。
2. **Reference annotation completeness / provenance**：Reference Evidence 必须表达 `exhaustive / partial / unknown` 的完整度语义，并记录建立流程、时间、人工 adjudication 与适用 Scope。只有在 Reference 足够完整时，Precision / Recall 才能被强解释。
3. **Trivae-specific Design Seed Cases**：新增约 8–12 个不产生 gate 的设计样例，用来证明 Case Bundle 能表达事实查找、趋势、多阶段调查、身份歧义、证据不足、absence、冲突证据、Chunk Boundary、Planner 正/负收益、权限限制和 Reference 外新 Evidence。
4. **Baseline identity**：Baseline 必须是完整 pin 住的 Controlled Variant，而不是 `main`、`current defaults` 或模糊的生产状态；Candidate 必须声明相对 Baseline 的显式差异。

## 必须吸收的中优先级调整

5. **Snapshot reproducibility 语义**：Evaluation 保证输入、Dataset、Scope、Variant 和条件可重建，不承诺远程模型输出的字节级重放；删除、权限变化与 Snapshot 的未来可运行性必须遵守数据治理。
6. **Core Set workload refresh / drift**：Core Set 应按真实 workload 与新场景定期审视，通过 Suite versioning 更新并保留历史结果，不覆盖旧 Suite；本阶段不规定周期与比例。
7. **Blind pairwise review**：baseline / candidate 的质量比较尽量使用 blind、随机顺序、同 rubric、同 Evidence visibility；成本指标在质量判断之后合并，降低 evaluator bias。

## 明确继续 Deferred

- Case JSON / Python Schema；
- Database table 与 runner package layout；
- 具体 Case 数量、development / holdout 比例；
- 每个 Case 的重复 Run 次数；
- 统计显著性算法与 Judge agreement threshold；
- Recall@K、Answer score、latency / token 等数值 gate；
- Dashboard。

## 对原方案的影响

- 保留端到端 Case Bundle、Reference Findings / Evidence、paired comparison、分层 review、immutable Trace、Regression lifecycle、非单一总分与 ChatLab baseline seed 等主要架构。
- 强化 Planner / Router 解耦、Reference 可解释性、Baseline 可复现性、真实 Trivae 表达能力、长期 workload 代表性与 Judge 公平性。
- 不扩大到实现 Schema、基础设施或未经运行的数值结论。
