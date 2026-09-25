# Router Jev provider experiment

> 状态：**Experimental / Not promoted**（2026-09-25）。实现采用 OpenRouter Decisions API；默认配置为 enabled + shadow。真实线上 A/B 尚未运行，不能将当前候选 Case 的 provisional route accuracy 当作质量结论。

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

`evaluation/router-jev/cases-v1.json` 是小型诊断集，不是正式 benchmark：16 个候选 Case 中，13 个为 ambiguous，3 个由确定性 Rule 处理；所有 16 个 route hypothesis 均待人工 adjudication。配对 runner 对同一 context 运行现有 LLM 与 Jev，仅调用 ambiguous 分支，并记录分歧、confusion、route metrics、confidence 描述区间、latency、失败率和真实 usage/cost。artifact 不包含 query 或原始 Provider response。

正式线上配对评估当前为 **not run**。此前一次配置审查意外将本地 API key 暴露在工具输出中；随后首次全仓测试也未隔离默认 shadow 配置，现有 Application 集成测试尝试了 Jev 请求，服务是否接收或计费无法确认。受影响 key 必须先撤销/轮换；密钥值没有写入源码、测试、Trace、Evaluation artifact 或 Git，本记录也不包含其值。没有生成或猜测线上 accuracy、latency、availability 或 cost。

当前 rollout 建议固定为 `continue_shadow`，不 promote。重新评估前需：

1. 用已轮换的 key 运行配对 Router Evaluation，并保存独立、create-only 的本地产物；
2. 对 Case route hypothesis 做人工裁决并扩充代表性样本；
3. 通过 forced-standard / forced-planned 实验测量 Planner utility 后再讨论 Router utility；
4. 检查 `planned_execution → standard_execution` 误判、Provider availability、p50/p95 latency 和 OpenRouter 实际 cost。

Stage 1.5 的 Router architecture decision 不因该实验而重写。升级或替换实验结论必须给出人工标签、完整对照和可复核的 failure cases。
