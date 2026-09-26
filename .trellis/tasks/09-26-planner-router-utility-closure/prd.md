# Planner Utility → Jev Router Utility 工程收口

## 目标

在既有两路共享 Agent Runtime、SoftPlanner 只给软指导、Jev 生产保持 shadow 的边界内，建立可复核的 Planner treatment utility 与 Router utility 链路，并处理已知 zero-result 回归。

## 需求与约束

- 先复用已封存的 Development、repeat、Trace、Evaluation DB 与 review packet，定位 `dev-zero-empty-3` 首次实质偏离，并区分 `dev-zero-empty-1/2` 的原因。
- 若可证明安全，修复最小主链路错误并加入确定性回归；不得降低 verified-zero 的完整检索正证明要求，不以 Case ID 或 Query 文本特判。
- 建立小型、版本化 Planner utility Suite，保留已有 CaseBundle、Snapshot、GT 与暴露历史；增加人工 treatment utility 裁决契约，区分路线分类与实际效用。
- 实现 Jev 预测路线对照两路实际质量、故障、延迟、usage 和 Provider 返回 cost 的分析；两种误路由方向分别报告。
- 为 paired benchmark 增加确定性顺序平衡，写入实验 manifest，旧默认与历史运行不变。
- 对齐项目状态文档并通过 pytest、Ruff、mypy、diff check；本地提交，不 push，最终工作树干净。
- Phase A 不调用付费 Provider；Phase B 正常目标约 30～40 次、Phase C 仅针对明确不稳定或链路故障追加，总上限 60 次。每次请求入 ledger，失败也计数，不自动重试。

## 验收

- [x] zero-result Failure Case 有逐层证据、边界结论、最小修复或明确未修原因。
- [x] Suite、人工裁决模板、Router utility runner/analysis 与 preflight 可本地运行，旧 GT/holdout 未改。
- [x] 顺序平衡与身份契约有确定性测试。
- [x] 付费调用前静态估算最坏请求数，逐次 ledger；只有 Phase A 通过才执行有限真实验证。
- [x] 报告区分 measured、人工待裁决、假设和仅准备未运行，Jev 仍 shadow。
