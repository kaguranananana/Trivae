# 设计边界

最小行为缺口在 `has_verified_zero_result_evidence` 将零计数 SQL aggregate row 当成存在候选消息，拒绝了同一 run 已获得的完整零条时间窗证明；另有 Planned 路未调用时间窗检索的独立风险。前者在 Evidence finalizer 修复并锁住正、反例；后者先审计 Trace，再决定是否需要通用 Runtime guidance 调整。Planner 不成为执行器。

Planner utility Suite 复用现有 Development CaseBundle 的 query、scope、Snapshot 和 GT；新增 manifest 只列 case reference、workload hypothesis、历史暴露来源，不伪造 positive label。人工 treatment 裁决引用成对 Evaluation run、具体质量轴及证据；unknown 保留，不由 route 标签反推。

Router utility 接受经人工裁决的 treatment record 与真实 Jev decision observation，按 case、repeat、variant identity 联接，分开计算 Rule gate、Provider 决策、availability、两种错误方向和 downstream quality impact。未裁决不得进入收益分母。Runner 不改生产 Router mode。

Paired 顺序采用 opt-in 的按 Case 奇偶反转两个 Variant 的 deterministic 规则；原 `--paired-by-case` 顺序不变。顺序策略写入输出报告的 experiment identity/manifest，不写入 Suite 或 Case identity。

本轮真实运行只选已知回归、一个 context recovery 和必要的控制例；每次发起前按最大 Runtime turns 与 Planner/Jev 次数估算，并使用可记录请求开始和结果的本地 ledger。无法在剩余 60 次内完成整对时不发起。
