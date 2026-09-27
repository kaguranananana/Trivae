# Design

## Boundary

问题首先发生在 `SoftPlanner.plan` 的单次 Provider completion：`finish_reason=length` 在 JSON parser 前被归类为 `provider_length`。保留这一失败路径和同一 Runtime soft-guidance 架构。代码范围预计限于 Planner prompt/summary、直接相关的 Provider usage 投影、Planner-only 实验 runner 与 provider-free 测试。

## Attribution before mutation

先分析旧实验五次截断与 P0 同轮输出，按 prompt 区段和可见输出结构拆分。四次空正文说明不能把 2048 输出耗尽直接等同于 Plan 文本过长。官方 DeepSeek Chat Completions 文档确认 thinking 默认开启，usage 可给 `completion_tokens_details.reasoning_tokens`；当前适配器未投影该字段。新实验保存这个数值（若 Provider 真正提供），不保存 reasoning 正文。

## Candidate strategy

P2 只压缩重复的 Planner 全局规则与 capability 选择说明，不删除由旧实验支持的实体锚、direct-hit→context 关系、非机械双检索、聚合止于 SQL 和 zero-result 契约。canonical purpose 仍从 Registry metadata 读取，selection guidance 不维护第二份 Tool 说明。保持 2048 output ceiling、Plan schema、JSON mode、model、temperature、allowlist 与 parser 相同，以隔离 prompt 改动。若重复实验显示该压缩不足，则保留 negative result，不用加大 token 或重试冒充成功。

## Experiment and review

沿用固定 Development Case 与 P0 模板；P1 要冻结上一轮提交对应的 prompt，避免 P2 的代码变动污染对照。每 Case/repeat 对 P0/P1/P2 交错 counterbalance。每次调用实时写 JSONL，之后生成指标和随机盲包。盲包只显示 A/B/C，key 单独落盘。assistant provisional review 与 human adjudication 分开。

## Compatibility

QueryContext、Plan schema、Router、Runtime 的数据契约不变。usage 投影只增加 Provider 实际返回的可选数值字段。无数据库、API 或历史实验数据迁移。若 P2 gate 未通过，保留代码与数据为实验候选，禁止 E2E promotion。
