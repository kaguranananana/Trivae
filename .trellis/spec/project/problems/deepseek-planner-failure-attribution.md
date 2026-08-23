# DeepSeek Planner failure attribution

## Problem

真实 DeepSeek 的 `planned_execution` Query 中，Planner 持续出现
`PLANNER_INVALID_OUTPUT` 和 `PLANNER_TIMEOUT`。Query 最终经常仍能完成，但那是
Planner soft degradation 后 Runtime 无 plan 继续执行，不能证明 Planner 成功。

## Evidence

- 在修复前，使用正式 `Application.query`、`ExecutionOverride(forced_route="planned_execution")`
  和当前 `.env` 连续运行 10 次；10 次 Query 均完成，但 Planner 为 2 次 timeout、8 次
  invalid output。timeout 耗时为约 `10003.3ms` 和 `10003.8ms`，其余 invalid output
  耗时分布约 `5051.6–9648.1ms`。
- 增强 Debug Trace 后，3 次真实 invalid output 都是 Provider `deepseek`、模型
  `deepseek-v4-flash`、`max_tokens=2048`、JSON mode 开启、`finish_reason=stop`；没有
  `length` 截断。3 次都在 `intent_validation` 被拒绝，返回文本长度分别为 724、555、1834。
- 真实 Trace `trace-8ee55a4d2d5f491eb841164faf2a8de2` 的安全摘要为：Provider 返回了
  合法 JSON，`output_tokens=432`，但 `intent` 是自然语言句子而不是现有七值枚举；Parser
  记录 `failure_detail_code=invalid_intent`、`parse_stage=intent_validation`。同批另一条
  响应还把数组字段表达成字符串，说明 JSON mode 没有替代字段 contract 指令。
- 在不改变 Provider、模型、2048 token budget 或生产 Query 链路的前提下，把临时 Planner
  timeout 设为 15 秒，5 次请求全部收到 `finish_reason=stop` 的 Provider response；其中
  3 次耗时约 14.58、14.71、14.73 秒。它们仍因旧 Prompt 的 `intent` contract 失败，证明
  原 10 秒 timeout 确实会在 Provider response 之前由 `asyncio.wait_for` 取消请求。
- 修复后同一正式路径连续 10 次，Planner `10/10` 为 `planner.completed`、
  `parse_stage=plan_validation`、`finish_reason=stop`，耗时约 `3928–15810ms`；Query
  `9/10` completed，另 1 次 Planner 已成功但后续 Runtime 独立返回 `RUNTIME_ERROR`。

## Root Cause

这是两个独立的 Provider boundary 问题：

1. Planner Prompt 只列出字段名，没有明确 `intent` 的允许枚举，也没有明确 steps 和
   success criteria 的数组约束。DeepSeek 可以生成合法 JSON，但 JSON 中的值仍违反
   Trivae Plan contract，于是在 `intent_validation` 失败。
2. Planner 的独立 completion timeout 硬编码为 10 秒。真实 DeepSeek 在相同请求配置下
   存在 14–16 秒的正常返回；`asyncio.wait_for` 在 Provider response 产生前取消请求，
   所以没有 `finish_reason`、usage 或 response content。

不是 JSON mode 未开启，也不是本批次的 `finish_reason=length` 截断。

## Options

- 增加 Planner retry、第二个 Planner、自动修复 JSON 或 fallback：会改变现有 soft
  Planner 事实并隐藏原始失败，不符合 Stage 1.6 的 no-retry contract。
- 放宽 Plan parser：会把自然语言 intent 或错误数组形状误当作合法 Plan，扩大 Runtime
  guidance contract。
- 只调整最终 Runtime synthesis budget：不触及 Planner 的独立 failure boundary。
- 在现有 Planner boundary 内补全 contract Prompt、增加安全阶段化 observation，并把
  timeout 调整到已测量延迟之上：不改变 Router、Planner、Runtime 的职责和降级路径。

## Decision

选择最后一个方案：

- Prompt 显式列出七个合法 `intent` 值，明确 steps、suggested tools、evidence 和
  success criteria 的 JSON array 形状，禁止 Markdown fence、null 和自然语言 intent。
- 保留现有 deterministic parser 和 Plan bounds，不增加 normalization、retry 或 silent
  repair；补充 JSON decode、Provider response、字段 validation 的细分类。
- Planner 默认独立 completion timeout 从 10 秒调整为 20 秒。20 秒不是 Provider SLA，
  而是针对实测最高约 15.81 秒响应保留有限余量的最小运行时校准。
- Adapter 只投影 provider/model、request budget/JSON mode、latency、finish_reason、
  usage、response text；不持久化 SDK 对象、Authorization 或 API key。response/prompt
  正文只在现有 Debug Capture Policy 下进入 Debug Trace。

## Why

这是在现有 ChatLab 基线和 Trivae ADR 内的最小修复：Planner 仍只生成一次 bounded
soft guidance，失败仍记录 coarse `PLANNER_*` diagnostic 并继续同一个 Agent Runtime；
只有 Prompt contract、timeout 校准和 observability attribution 发生变化。

## Result

- Debug Transcript 现在可直接显示 Provider/model、Planner/Provider latency、request
  max tokens、JSON mode、finish reason、usage、output length、parse stage、detail code
  和 safe diagnostic；Debug profile 还保留实际 prompt/response 文本。
- 真实修复后 10 次 forced planned run 的 Planner failure rate 从基线 `10/10` 降至
  `0/10`。其中一次 Query 的后续 Runtime error 被独立保留，没有计作 Planner failure。
- 旧 coarse `PLANNER_INVALID_OUTPUT` / `PLANNER_TIMEOUT` 业务 diagnostic contract
  保持不变，Runtime degraded execution 仍存在。

## Trade-off

Planner 在 Provider 真正无响应时最多等待 20 秒，最坏 degraded latency 比原来增加 10
秒；更长的等待不等于 Provider SLA。真实 Provider 仍可能出现新的 stochastic failure，
因此本次 10 次验证不能宣称长期 failure rate 为零。

## Regression

- `tests/test_query_execution_core.py` 覆盖合法 Plan、非法 JSON、非法 intent、缺失/null
  steps、空 success criteria、空 Provider content、timeout、`finish_reason=length`、
  阶段化 Trace，以及 Planner failure 后 Runtime 继续执行。
- `tests/test_agent_runtime.py` 覆盖真实 adapter 的 JSON mode、max tokens、finish reason、
  usage 投影和空 content。
- `evaluation/regressions/deepseek-planner-failure-attribution.json` 固化本次 failure
  identity、证据边界和真实验证结果。
