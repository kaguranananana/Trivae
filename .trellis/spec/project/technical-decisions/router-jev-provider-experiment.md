# Router Jev provider experiment

> 状态：**Experimental / Not promoted**（2026-09-25）。实现采用 OpenRouter Decisions API；默认配置为 enabled + shadow。真实配对评测和 16 Case 人工裁决均已完成，原 route hypothesis 16/16 全部确认；本诊断集结果不构成生产切换或 Planner utility 证据。

## Decision

- 保留 Stage 1.5 的两路 taxonomy、Rule-first gating、Planner 边界和单一 Agent Runtime。
- Jev 只判断 ambiguous Router decision，不接管 Planner、Runtime、Retrieval、Tool 或 Answer Generation。
- `OPENROUTER_API_KEY`、`TRIVIAE_ROUTER_JEV_ENABLED`、`TRIVIAE_ROUTER_JEV_MODEL`、`TRIVIAE_ROUTER_JEV_ENDPOINT`、`TRIVIAE_ROUTER_JEV_MODE` 是 Router 专用设置；不读取或覆盖 `TRIVIAE_MODEL_*`。
- 默认模型为 `typesafe/jev-1.13`，endpoint 为 `https://openrouter.ai/api/alpha/decisions`，mode 为 `shadow`。
- `existing_llm` 保持原 LLM Router；`jev` 让 Jev 作为 ambiguous decision provider；`shadow` 保持现有 LLM/static Rule 决定主 route，同时单独记录 Jev observation。Shadow 的失败和 route 分歧都不改写主 route、Answer 或执行路径。
- 显式 `jev` 模式下若 Jev 请求失败，保留当前 static Rule route 并标记稳定 degradation code。高置信 Rule 不请求任一 Provider。

## API mapping

使用 OpenRouter Alpha Decisions 的 typed Choice：`choice → route`、`confidence → confidence`、两个 Route label 的 `probabilities → probabilities`。`confidence` 表示分布集中程度，不能被 winning probability 替代。只投影 Router 已使用的 query、locale、prior model context 和 data snapshot；不发送 trusted scope 或 capability inventory。Provider 的原始响应和错误正文不进入 Trace/Evaluation；实际返回的 token 和 `usage.cost` 才进入测量。

## Evaluation and rollout

`evaluation/router-jev/cases-v1.json` 是小型诊断集，不是正式 benchmark：16 个 Case 中，13 个为 ambiguous，3 个由确定性 Rule 处理。初次运行时 route hypothesis 标记为 provisional；运行后用户按“请求是否值得在进入 Agent Runtime 前额外调用 Planner”这一 Stage 1.5 标准逐条裁决，16/16 全部确认，8 standard / 8 planned，0 项变更。最终标签与理由记录在 `evaluation/router-jev/adjudication-v1.json`。原 case manifest 保留为运行时输入，原始 artifact 保持不变。配对 runner 对同一 context 运行现有 LLM 与 Jev，仅调用 ambiguous 分支，并记录分歧、confusion、route metrics、confidence 描述区间、latency、失败率和真实 usage/cost。artifact 不包含 query 或原始 Provider response。

2026-09-25 首轮真实配对运行：16 Case × 3 repetitions；两路各调用 39 次并全部成功。LLM/Jev 在全部 48 个投影上的 agreement 为 42/48（87.5%）；只看 ambiguous decisions 为 33/39（84.6%），6 次分歧均来自 RJV-008 与 RJV-013。按最终人工标签，Existing LLM 为 39/48（81.25%，13/16 个 Case），Jev 为 45/48（93.75%，15/16 个 Case）；LLM 错误为 RJV-004/008/013，Jev 错误仅 RJV-004。Jev 平均 route-call latency 为 278.893 ms，LLM 为 2164.128 ms；Jev 的 39 次真实 `usage.cost` 合计 0.000746802，baseline cost unavailable。详细分析见[实验报告](../../../tasks/09-25-openrouter-jev-router/experiment-report.md)。

本轮按用户明确指示使用现有 `.env` 凭据，没有轮换；CLI 先移除继承的 `OPENROUTER_API_KEY`，再由 `--env-file .env` 加载，凭据值没有输出。artifact 保存在被 Git 忽略的 `data/evaluation/router-jev/paired-v1-2026-09-25.json`；对 artifact 的隐私扫描未发现 query、context、key 或 raw response。

人工裁决已完成。RJV-004 的最终标签为 standard：长时间跨度和趋势总结本身不要求 Planner；只有请求进一步追踪关键转折、原因及其证据链时才满足 planned 条件。RJV-008 的 prior context 限定了单一理由摘要，判 standard；RJV-007 的上下文则要求完整决策演变和测试证据，判 planned。RJV-013 是单一语义查找，“分析”措辞不构成 Planner 信号。生产运行时仍保持 `shadow`。两个 Provider 在 8 个 adjudicated planned Case 的 24 次重复中均未发生 `planned_execution → standard_execution`，但样本不足以排除该风险。

下一步先通过 forced-standard / forced-planned 实验测量 Planner utility，即额外 Planner 调用是否改善最终结果；同时扩充代表性诊断集并复核 planned-to-standard 风险、availability、latency 和 cost。完成这些验证前不切换到 `jev`。

Stage 1.5 的 Router architecture decision 不因该实验而重写。升级或替换实验结论必须给出人工标签、完整对照和可复核的 failure cases。
