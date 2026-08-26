# Interview Defense Notes

## 为什么要拆 per-call 和 run-level budget？

单次 Tool Result 的 128k 是防止一次 evidence 倾倒过多；run-level pool 是防止多个 Tool call 累计无界。一个参数同时表达两层语义会让 1M context 被错误地压成 128k 总池，也无法解释 Trace。

## 为什么 dynamic 默认而不是 fixed 默认？

当前已有 verified capability，dynamic 可以按真实 context 计算；未知模型仍使用显式 fallback 16k。fixed 保留给回归、debug、rollback 和 evaluation，因此默认行为不会依赖模型字符串猜测。

## 为什么 1M 模型的 per-call 不是 500k？

产品 safety ceiling 独立于模型原始 context：`min(floor(1M×50%),128k)=128k`。1M 只参与预算解析，不等于允许单次 Tool Result 占满一半 context。

## 为什么 run pool 公式是 25%？

这是一次 Run 的 Evidence safety pool 候选公式，并有 256k hard cap；1M 的计算值是 250k。128k/256k 是实验 override，用来校准多 Tool call，不把 per-call cap 和 run pool 混名。

## 为什么不在未知模型上“猜” context？

模型名不是能力证明。未知组合返回 `fallback`，per-call/run 都是 16k，并在 Trace 保留 source；错误透明比伪精确预算更容易运维和回归。

## graceful finalization 会不会掩盖错误？

只恢复 bounded local metadata：规范化 string limitation、丢失无效 citation，并明确 `degraded`。空答案、trusted provenance、scope 和 canonical source 失败仍是 `failed`；Runtime 未完成也不进入 finalizer。

## 为什么没有 retry 或第二次 LLM 修复？

这轮问题是 typed boundary 和可交付性，不是通过重试改变 provider 输出。第二次 LLM 会增加成本和不可重复性；恢复逻辑只使用 deterministic 本地规则，并在 diagnostics 中记录丢弃/规范化事实。

## 如何证明 run pool 是 run-local？

`RuntimeContext` 每次 run 新建 `ToolResultBudgetPolicy`；reserve 先锁定当前余额，projection 完成后按实际 estimate settle，下一次 Tool call 读取同一余额，下一次 run 从新 pool 开始。

## 真实 A/B 没有 completed 样本怎么办？

不把 timeout 当质量结果。Synthetic/archive 已验证 visible/omission/truncation 与 预算归因；真实 provider 的 36 个 cell 只在取得 terminal 后用于质量/成本/延迟结论，否则报告明确 blocked，而不是填造 Trace ID。
