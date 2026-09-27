# Design

## Boundary

问题首先发生在 `SoftPlanner.plan` 的单次 Provider completion：`finish_reason=length` 在 JSON parser 前被归类为 `provider_length`。保留这一失败路径和同一 Runtime soft-guidance 架构。代码范围预计限于 Planner prompt/summary、直接相关的 Provider usage 投影、Planner-only 实验 runner 与 provider-free 测试。

## Attribution before mutation

先分析旧实验五次截断与 P0 同轮输出，按 prompt 区段和可见输出结构拆分。四次空正文说明不能把 2048 输出耗尽直接等同于 Plan 文本过长。官方 DeepSeek Chat Completions 文档确认 thinking 默认开启，usage 可给 `completion_tokens_details.reasoning_tokens`；当前适配器未投影该字段。新实验保存这个数值（若 Provider 真正提供），不保存 reasoning 正文。

## Candidate strategy

归因实验表明只压缩 prompt 的 P1-B 仍有 5/24 次 `provider_length`；失败时 Provider 明细显示隐藏 reasoning token 消耗接近或达到 2048。压缩且关闭 thinking 的 P2-v1 为 24/24，但简单查询过度规划，不能 promotion。原 P1 prompt + 非思考也 24/24，却保留同类质量回退。P1 + 3072 budget 的 24/24 调用最高只消耗 2020 token，不能证明加预算是成功原因；因此不选直接提高上限。

最终候选 P2-v3 保留 metadata canonical purpose，压缩重复的 Planner guidance，并用跨 Case 的通用质量约束明确必要证据关系、非机械双检索、无假设分支及 schema→SQL 顺序。它在探索性 3 repeats 中 24/24 有效，zero-result/aggregation/direct-lookup 的主要回退消失；需再经交错正式实验验证。Provider treatment 对已实测的官方 DeepSeek `deepseek-flash` Planner completion 指定 `reasoning_effort=none`，仍保留 2048、JSON mode、同一 parser/allowlist。其它 Provider 没有对应实测，不改其原 completion 档位。Router 继续原 `low`，Agent Runtime Tool Loop 与最终回答路径不变。

## Experiment and review

沿用固定 Development Case 与 P0 模板；P1 从上一轮真实请求冻结，避免 P2 的代码变动污染对照。最终每 Case/repeat 对 P0/P1/P2 交错 counterbalance，计划 5 repeats。每次调用实时写 JSONL，之后生成指标和随机盲包。盲包只显示 A/B/C，key 单独落盘。assistant provisional review 与 human adjudication 分开。

## Compatibility

QueryContext、Plan schema、Router、Runtime 的数据契约不变。usage 投影只增加 Provider 实际返回的可选数值字段。无数据库、API 或历史实验数据迁移。若 P2 gate 未通过，保留代码与数据为实验候选，禁止 E2E promotion。
