# Dynamic Tool Result Budget / Quality Regression

## Goal

在不改变既有检索召回预算与 Evidence 语义的前提下，让一次 Agent run 的 model-visible Tool Result 预算能够根据已验证的 context window 动态计算，并对同一 run 内的多次 Tool 调用做累计记账。通过可观测的 Trace 字段和固定/动态 A/B 验证，确认大 context model 不再被固定 16k 投影上限过早截断，同时避免多工具调用无界地累积模型可见上下文。

本任务只处理“Tool Result 投影到模型输入之前”的预算边界。它不重新实现上一轮 retrieval budget，也不把质量、相关性或最终答案正确性偷偷推导成运行时指标。

## Requirements

### 1. 既有契约必须保持

- lexical 默认 1000、上限 5000；semantic 默认 10、上限 20；dense top-k 40；trusted scope 5000；structured/value 100；automatic context source cap 20；expanded final cap 100。
- direct hits 优先于邻居 context；canonical Tool Result 保持完整；model projection 的 source handle 必须只来自本轮实际可见数据。
- fixed 模式继续使用 16,000 estimated tokens；现有 retrieval budget、prompt safety、canonical Evidence 和 fixed projection 测试必须继续通过。

### 2. Tool Result Budget Policy

实现一个小型、typed、runtime-owned 的 policy/resolver：

- 支持 `fixed` 与 `dynamic` 两种模式，默认 `fixed`。
- dynamic 模式支持显式 `context_window_tokens`、`max_tool_result_percent`（默认 50）和绝对上限 `max_tool_result_tokens`（默认 128,000）。
- 已知 context window 时，run-level pool 为：

  `run_tool_evidence_budget = min(floor(context_window_tokens * max_tool_result_percent / 100), max_tool_result_tokens)`。

- 每次 Tool 调用的 effective budget 不得超过 per-call ceiling，也不得超过 run-level pool 的剩余值；投影完成后按实际 estimated tokens 扣减。
- 多个 Tool 调用必须共享同一个 run-level pool；不能因为每次调用都重新获得一个完整预算而导致累计模型可见 Tool Result 无界增长。
- context window 未被显式配置或 verified metadata 证明时，不根据 model string 猜测；使用已有安全固定预算 16,000，并在 Trace 标明 fallback 来源。
- 预算耗尽、配置非法、投影无法满足声明预算时必须显式报错，不能静默吞错、降级或为单个样例加特殊规则。

### 3. 配置

通过项目现有 settings/env 边界读取：

- `TRIVAE_TOOL_RESULT_BUDGET_MODE=fixed|dynamic`
- `TRIVAE_MODEL_CONTEXT_WINDOW_TOKENS`（可选，正整数）
- `TRIVAE_MAX_TOOL_RESULT_PERCENT=50`（1–100 的整数）
- `TRIVAE_MAX_TOOL_RESULT_TOKENS=128000`（正整数）

显式非法值必须在 settings 层返回 typed 配置错误；secret-safe settings 输出可包含这些非敏感值。token 估算继续使用当前有界的 byte/character estimate，不伪装成 provider 精确 usage，也不新增 tokenizer 依赖。

### 4. Observability

每个 Tool completed Trace 事件必须能解释本次结果为什么是 16k/32k/64k/128k 或更小，并至少包含：

- `budget_mode`
- context window 与 `context_window_source`
- percentage 与 absolute cap
- run pool
- 本次调用前剩余预算
- per-call ceiling 与 effective budget
- 投影后的 estimated tokens
- 本次调用后剩余预算
- `truncated`
- omitted context/hit counts

terminal Trace 需要保留 run-level 汇总，且不得丢失每次调用的预算归因。Trace 仍只记录执行事实，不得把“截断”自动等同于答案质量下降。

### 5. 回归与评估

自动化测试必须覆盖：

- 32k→16k、64k→32k、128k→64k、256k→128k cap、未知→16k fallback。
- 同一 run 的多次调用累计扣减、不能超池、direct hit 优先、truncation metadata 和 source handles。
- canonical record 完整且不被 model projection 修改。
- fixed mode compatibility、已有 retrieval budgets 未改变、常见多工具路径不出现 O(n²) 预算/投影逻辑。

增加 deterministic synthetic benchmark，至少覆盖 Agent/HTTP 两类入口在 100/300/1000 规模和 fixed vs dynamic 128k→64k 对比，记录 latency、tool call 数、projected tokens、truncation、omitted context/hits。质量标签与 operational cost 分开。

如果本地存在 provider credential，用上一轮四个真实 prompt 做固定/动态 A/B，每个条件至少 3 次，并保留 Trace ID：

- 最近一个月的 GitHub/Skills/资源讨论
- 最近一个月的 Agent 学习资料
- taste-skill 的群内评价和实际使用情况
- 最近两周的 DeepSeek 相关项目

真实 A/B 必须同一 commit、只切换预算相关环境变量；无 credential 时明确记录阻塞证据，不伪造质量结论。

## Acceptance Criteria

- [x] PRD、design、implement 完成并与实际实现一致。
- [x] 动态 policy 在显式 context window 下按公式计算，跨 Tool 调用共享并扣减 run pool；未知 context 使用可观测的 16k fallback。
- [x] 配置、Runtime、Tool Result projection、Trace 和 evaluation operational facts 端到端贯通。
- [x] canonical Tool Result、source handles、direct-hit 优先级和既有 retrieval budgets 未被改变。
- [x] 新增单元/集成回归覆盖计算、累计、截断、错误透明和 fixed compatibility。
- [x] synthetic benchmark 有可复现输入和事实结果；真实 A/B 有结果则报告结果，无 credential 则明确标记 blocked。
- [x] `pytest -q`、`ruff check src tests`、`mypy src`、compileall、CLI help、Trellis validation、`git diff --check` 通过，或逐项记录根因与阻塞。
- [x] validation 记录 design rationale、failure cases、observability、scale、ownership、evolution 和 interview evidence，不虚构性能/质量事实。

## Constraints / Non-goals

- 不改 retrieval limit、semantic candidate acquisition、prompt contract、Conversation Store、SDK loop 或 provider model registry。
- 不根据 model 名称维护猜测 context window 表；context window 只有显式配置或未来 verified metadata 才能进入 dynamic 计算。
- 不引入 retry、fallback、silent truncation repair、hash/SHA256 或针对单个真实 prompt 的特殊分支。
- 不合并 `main`，不 force push；完成时报告最终 branch 和 commit。
