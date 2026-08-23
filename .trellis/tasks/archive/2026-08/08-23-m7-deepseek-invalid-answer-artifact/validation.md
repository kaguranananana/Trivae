# M7 DeepSeek invalid Answer Artifact 修复验证

## Measured Facts

- 真实校准使用临时 Canonical 副本和同一 Snapshot：473236 条消息、14 个 source、Lexical index present；Snapshot identity 为 `snapshot-v1:messages=473236:first=1753011800000:last=1786847688000:sources=14`。Canonical raw data 未修改。
- 修复前 `last-stable-m6` 真实 baseline 为 8 个 Case：8 个 Query terminal 为 `completed`，Trace 8/8 `complete`，Finalizer 7/8 通过，`real-context-expansion-v1` 失败为 `INVALID_ANSWER_ARTIFACT`。Provider usage 为 input 88474 / output 31657 / total 120131 tokens，19 requests，17 tool calls，11 tool rounds，总 latency 229609 ms；该结果没有被 Evaluation 包装为成功。
- Provider capture 确认修复前最终 synthesis 已带 JSON mode，但没有显式 `max_tokens`；多轮真实失败的请求形态为 4 tool calls / 2 tool rounds，最终 Finalizer 仍返回 `INVALID_ANSWER_ARTIFACT`。同一 capture 还确认 Router/Planner 旧请求使用 `max_tokens=512` 且没有 JSON mode，出现 `finish_reason=length`、空 content 的 `PLANNER_GENERATION_ERROR`。
- 修复后的 `deepseek-json-budget-m7-v2` 在同一 Snapshot 的 8 个 latest Case Run 均为 successful，Finalizer error 0，Trace 8/8 `complete`；routes 为 planned 4、standard 4；15 tool calls、11 tool rounds、19 provider requests、109395 total tokens，latency 6812–54785 ms。Planner degraded 仍作为事实保留：`PLANNER_INVALID_OUTPUT` 3 次、`PLANNER_TIMEOUT` 1 次。
- 重复回归直接覆盖旧失败形态：`deepseek-json-budget-m7-v2-repeat` 的 `real-planner-utility-v1` 真实 Run 在 4 tool calls / 2 tool rounds / 3 requests 下 successful，Finalizer error 为空，Trace `complete`。

## Deterministic Validation

- `tests/test_agent_runtime.py` 验证默认及非法预算、Agent `response_format`/`max_tokens`、Router/Planner completion 的 JSON mode/预算和 secret-safe settings。
- `tests/test_evidence.py::RuntimeEvidenceIntegrationTests::test_orchestrator_keeps_malformed_json_as_finalization_failure` 验证非法 JSON 仍由生产 Finalizer 返回 `INVALID_ANSWER_ARTIFACT`，不被修补成成功。
- 生产链路仍为 `EvaluationRunner → QueryOrchestrator → Router/Planner → AgentRuntime → Tool/Retrieval → Finalizer → Trace`；没有新增 EvalRuntime、EvalOrchestrator、retry 或 JSON repair。
- M6 failure regression 继续覆盖 trusted limit、mixed provenance、Planner degraded、partial/truncated、citation failure、Trace terminal、Trace Store 和 privacy mapping；`m7-limitation-preservation-payload-mapping` 保持原 Trace payload 事实而只修正后验 mapping。

## Real-data Calibration

- 使用同一临时 Snapshot 完成 8-Case DeepSeek candidate suite、重复 Run smoke，以及 forced standard / forced planned paired experiment；不提交聊天正文、secret 或完整 Trace。
- Paired comparison `comparison:real-planner-utility-v1:v1:28eaf359e9834dceb0478137f5efe33e` 两边均为真实 successful Run：forced standard 为 2 tool calls / 1 round / 39096 ms / 16235 tokens，forced planned 为 2 tool calls / 1 round / 50670 ms / 16996 tokens，并且 planned Run 的 Planner 诊断为 `PLANNER_TIMEOUT`。质量 Review 状态为 `pending_review`，因此没有宣称质量提升或生成总分。
- 另有 `real-context-expansion-v1` 的 forced standard / forced planned pair，状态同样为 `pending_review`；两组比较均保留 baseline/candidate variant、blind order、randomization seed、Run、Answer、Trace reference 和 operational facts。

## Known Limitations

- DeepSeek 仍是 stochastic provider；8/8 是本次实测窗口，不是稳定性或质量保证。必须继续保留单次 Run 和重复 Run。
- Planner 的 `PLANNER_INVALID_OUTPUT` / `PLANNER_TIMEOUT` 仍是真实 degraded facts；修复没有把 Planner failure 改写成 Planner success，也没有把 planned path 的最终质量假设为更好。
- 质量轴尚未完成 Human Review，paired comparison 保持 `pending_review`，不生成单一总分；token cost 也未在当前 provider contract 中可靠获得。
- 历史 M6 baseline 使用修复前 provider-default output boundary；candidate 使用显式 `max_output_tokens=16384`、`completion_max_tokens=2048`。两者的差异已写入 Variant identity，不能当作只改 Prompt 的实验。

## Deferred Work

- Human review packet 的实际标注、更多 repetitions 和基于方差的 promotion threshold。
- 对残留 Planner degraded 的独立根因修复与 regression；当前任务只修复 provider structured-completion boundary，不增加 Planner fallback。
- 在线 Judge、Dashboard、分布式执行、自动 Prompt 优化和统计显著性平台。
