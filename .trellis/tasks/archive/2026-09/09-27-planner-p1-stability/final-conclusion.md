# Final conclusion

> 2026-09-27 补充：下文 `PASS` 是原始 provisional review 时点的历史判断；assistant blind adjudication 揭盲后，P2 promotion gate 修订为 `FAIL`。最新证据及 40 组映射见 `experiment-final/assistant-blind-adjudication-unblinded.md`。

## Confirmed root cause and remaining uncertainty

本次新实验 Provider 明细证实：`deepseek-flash` 的 thinking token 在 `max_tokens=2048` 内累计，`provider_length` 发生时占用 1821–2048 token，常在可见 JSON 生成前耗尽。原 P1 五次失败虽未保存 reasoning 明细，但四次空正文与同一近端机制一致；不能倒填其具体 reasoning 数值。输入 prompt 长度增加是否直接提高失败概率仍未证明。第一轮 P1-B 缩短输入仍 5/24 截断，单纯 prompt compression 不是可靠修复；3072 预算探针的最大实际输出 2020，不能证明上限增加有效。

## Final P2 candidate

P2-v3 合并重复规划规则、缩短 selection guidance，保留 Registry canonical purpose、entity anchor、direct-hit→context、anti-overplanning 与 zero-result。仅已实测的官方 DeepSeek Flash Planner completion 使用非思考模式；Router 继续 low，同一 Agent Runtime 和 Plan schema 不变。正式 5 repeats 的 P0/P1/P2 valid 分别为 35/40、36/40、40/40，`provider_length` 分别为 5、4、0。P2 总 token 52,834、平均 latency 1.36 s，对比 P1 的 100,722、6.70 s。全部 120 次和 40 组盲包可复核，金额成本不可得。

## Decision

Planner-only Development gate：`PASS`；可准备 `Standard vs Planned-P0 vs Planned-P2` 的后续设计，**本轮不执行三路 E2E**。human adjudication 与真实 Runtime 效用仍待下一阶段；局部疑点是 cite-archify 的 recent 浏览。未访问 Holdout；没有 Case 字面量 patch、自动 retry、Router/Runtime Tool Loop 或 Retrieval 改动。Development 观测不能作为 generalization 或生产收益证据。

## Post-adjudication update（2026-09-27）

审阅者在不知道 A/B/C 对应版本的情况下填完 40 组排序和观察，随后才用预存 key 揭盲；原盲包的 Plan 正文逐行保持一致。审阅者标识为 `ChatGPT assistant blind adjudication`，**不是 human adjudication**。P0／P1／P2 第一名分别为 0／30／10 次；P2 第二名 28 次、第三名 2 次。P2 的 10 次第一有 4 次来自 P1 `provider_length`；两者都生成有效 Plan 的 36 组里，P1 30 胜、P2 6 胜。P2 对 P0 的有效 Plan 对比为 33 胜、2 负（35 组）。

据此，P2 的可靠性收益成立，但“有效 Plan 质量不明显低于 P1”不能维持。archify r1 的 firsthand 预设、UTC 排名 r4 的重复 SQL 是具体回退；多数其他差距在证据要求与时间边界精度上。正式 P2 同时改变 prompt 与 thinking 配置，现有证据不能把质量差异归因于单一变化。按照原质量保持门槛，**P2 promotion gate：`FAIL`**。不运行三路 E2E；后续如继续优化，应以通用规则修复质量，并重新做盲审。原 Development 结果、未访问 Holdout 及未运行 Runtime 的边界不变。
