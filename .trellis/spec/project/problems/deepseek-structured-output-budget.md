# DeepSeek structured output budget failure

## Problem

M7 真实 DeepSeek baseline 的 `real-context-expansion-v1` 在 Query terminal 为 `completed`、Trace 为 `complete` 时，最终 Answer Artifact 仍被生产 Finalizer 判定为 `INVALID_ANSWER_ARTIFACT`。另一条真实多轮 Run 复现了 4 个 Tool call、2 个 Tool round 后的相同失败形态。

## Evidence

- 同一临时 Snapshot：473236 条消息、14 个 source、Lexical index present。
- Provider capture 显示修复前最终 synthesis 请求带 `response_format={"type":"json_object"}`，但没有显式 `max_tokens`；最终失败事实由 QueryResult、Finalizer 和 append-only Trace 同时保留。
- 修复前 8 个真实 Case 中 7 个 Finalizer 通过、1 个 `INVALID_ANSWER_ARTIFACT`，Trace 8/8 `complete`。
- 同一 capture 发现 Router/Planner completion 旧请求使用 `max_tokens=512` 且没有 JSON mode；真实 Planner 曾以 `finish_reason=length` 和空 content 结束，形成既有 `PLANNER_GENERATION_ERROR` degraded。

## Root Cause

Provider structured completion 的最终输出边界没有被 Variant/Settings 显式固定；对真实多轮 Evidence-backed artifact，Provider 默认边界和重复的 artifact 内容可能使最终 JSON 无法满足严格 Answer Artifact contract。该证据定位到 provider completion boundary，但不证明每一次 stochastic failure 都只有单一原因。

## Options

- 放宽或自动修补 Finalizer：会把非法 Answer/Citation 伪装成成功，违反 M5/M6 contract。
- 增加 retry、fallback 或自动减少 Tool/Retrieval 内容：会改变真实 Query 事实并隐藏诊断。
- 只扩大最终 synthesis 预算：不能解决 Router/Planner completion 没有 JSON mode 的独立问题。
- 在同一生产 Runtime 的 Provider boundary 同时固定 JSON mode、显式有界预算，并要求 artifact 保持紧凑：保持现有 Finalizer、Trace 和 QueryOrchestrator ownership。

## Decision

选择最后一个方案：最终 Agent synthesis 使用 `max_output_tokens=16384` 和 JSON mode；Router/Planner completion 使用 `completion_max_tokens=2048` 和 JSON mode；Prompt 约束每个 distinct claim 使用最少 content/evidence，避免重复复制 message。所有预算进入 safe settings 和 versioned Candidate Variant，不记录 secret。

## Why

这是不复制 Runtime、不放宽 Finalizer 的最小 Provider-boundary 修复。真实 v2 suite 在同一 Snapshot 的 8 个 latest Case 均 Finalizer successful，且直接覆盖旧 4-call/2-round 形态的 repeated Run 通过；Planner timeout/invalid output 仍保留为后验诊断，而不是被包装成成功。

## Result

- `deepseek-json-budget-m7-v2`：8/8 successful，Trace 8/8 complete，Finalizer error 0；真实 Planner degraded 仍记录为 `PLANNER_INVALID_OUTPUT` 3 次、`PLANNER_TIMEOUT` 1 次。
- forced standard / forced planned paired comparison 两边均成功，但 quality review 仍为 `pending_review`；未声明 planned 更好，也未生成总分。

## Trade-off

显式输出预算增加了可能的 token 和 latency；Planner 仍可能 stochastic degraded；Candidate 与历史 `last-stable-m6` 的 provider boundary 不同，因此不能把结果解释成只修改 Prompt 的实验。

## Regression

- `tests/test_agent_runtime.py` 检查 settings、JSON mode 和两个 provider budget 的 request projection。
- `tests/test_evidence.py::RuntimeEvidenceIntegrationTests::test_orchestrator_keeps_malformed_json_as_finalization_failure` 确保非法 JSON 仍返回 `INVALID_ANSWER_ARTIFACT`。
- `evaluation/regressions/m7-provider-output-contract.json` 记录 failure identity、owner、回归命令和真实验证边界。

## Follow-up resolution: graceful finalization（2026-08-26）

上面的 M7 记录保留为历史事实：严格 `finalize_answer()` 仍会把 malformed JSON、跨 run provenance
和可信 scope/canonical 边界错误报告为 failure。本轮没有把这些错误改写为成功，也没有增加二次 LLM
repair。

新增的 Application-facing `finalize_answer_gracefully()` 只对已经存在的可读答案执行 bounded
deterministic recovery：`limitations` 字符串可规范化为单元素数组；局部 invalid/unresolved citation
可丢弃并记录 `degraded`；全部 citation 失效时仍不生成 fake binding。Trace/Evaluation 保留 strict
error code/path、丢弃数量和 normalization facts，Conversation 只提交有 Artifact 的 valid/degraded
结果。空答案、不可读输出和 trusted provenance/scope failure 仍不提交。

对应回归：`tests/test_evidence.py` 覆盖 legal、limitations normalization、缺失 metadata、单个/全部
invalid citation、empty answer、trusted provenance failure 与 secret-safe diagnostics；
`tests/test_conversation.py` 验证 degraded answer 可提交而 runtime failure 不可提交。
