# P1 low vs none Planner-only single-variable experiment

## 目标

在相同 P1 canonical prompt 与 8 条已暴露 Development Case 下，只改变 DeepSeek Flash Planner 的 `reasoning_effort`，判断 `none` 相比 `low` 是否有明显 Plan 质量下降。

## 要求

- 每条 Case 各运行一次 `low` 和 `none`，总 Provider 请求最多 16 次；运行前固定交错顺序，失败保留在分母，不重试或补跑。
- 首次请求前完成 provider-free 配置、prompt、Case、schema、allowlist、预算与 runner 检查。
- 保存逐次请求参数、原始输出、解析结果、Plan、失败、耗时和真实 usage；缺失 usage 标记 `unknown`，不估算金额。
- 生成不暴露 treatment 和运行元数据的盲包，独立保存映射；全部盲审判断完成后揭盲。
- 分别分析可靠性、有效双边 Plan 的语义质量和效率，给出 A/B/C 工程结论及是否建议进入 E2E。
- 不修改生产 Prompt 或 reasoning 配置，不触碰 Holdout，不调用 Router、Jev、Runtime Tool Loop，不运行 E2E。

## 验收标准

- [x] 固定并保存 8 组 16 次交错运行顺序，Provider 请求数不超过 16。
- [x] 两路请求除了 `reasoning_effort` 外的输入和 Provider 参数完全相同。
- [x] 16 条原始记录、8 组盲包、映射、盲审、揭盲与结论均可审计。
- [x] 完成 provider-free 检查，报告任何真实失败与证据边界。
