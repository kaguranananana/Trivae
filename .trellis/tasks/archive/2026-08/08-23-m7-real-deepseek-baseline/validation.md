# M7 Real DeepSeek Baseline Validation

## Measured Facts

- Variant：`last-stable-m6`，code `cce944d`，provider/model `deepseek/deepseek-v4-flash`。
- 数据仅使用临时 SQLite 副本；Canonical DB 未修改，完整聊天正文未进入 Git 或报告。
- Snapshot：473,236 messages、14 sources、FTS5 index 473,236 messages；identity 为 `snapshot-v1:messages=473236:first=1753011800000:last=1786847688000:sources=14:lexical={'present': True, 'message_count': 473236}`。
- Case count：8；repetition：1；Evaluation Store 保存 8 个单次 Run。
- Query terminal：8/8 `completed`；Trace completeness：8/8 `complete`。
- Route distribution：5 `standard_execution`、3 `planned_execution`；其中 normal route 的 source 由生产 Router 记录。
- Tool calls：17；Tool rounds：11；Provider requests：19。
- Token usage：input 88,474、output 31,657、total 120,131。Cost 未配置，不能由 token 自动推导费用。
- Latency：min 5,703 ms、median 19,994.5 ms、max 104,998 ms、sum 229,609 ms。

## Per-run outcome

| Case | Terminal | Artifact/Finalizer | Checks | Trace | Operational note |
| --- | --- | --- | --- | --- | --- |
| simple keyword | completed | passed | passed | complete | 1 tool call / 1 round |
| trusted session filter | completed | passed | passed | complete | 1 tool call / 1 round |
| context expansion | completed | failed: `INVALID_ANSWER_ARTIFACT` | 3 hard checks failed | complete | Planner failed, partial retrieval |
| no result | completed | passed | passed | complete | 1 tool call / 1 round |
| insufficient evidence | completed | passed | passed | complete | Planner degraded; partial preserved |
| partial/truncated retrieval | completed | passed | passed | complete | truncation/partial preserved |
| evidence-backed answer | completed | passed | passed | complete | 3 tool calls / 2 rounds |
| Planner utility | completed | passed | passed | complete | 8 tool calls / 3 rounds; budget limitation retained |

Quality axes remain `not_reviewed`: no Finding Correctness、Evidence Completeness、Groundedness、Uncertainty Calibration 或 Relevance 结论被宣称。

## Trace-based Failure Diagnosis

失败 Run：`real-context-expansion-v1`。

- Trace terminal：`failed`，completeness `complete`。
- Primary cause：`citation`，status `likely`，confidence `0.85`。
- Evidence：production Finalizer 返回 `INVALID_ANSWER_ARTIFACT`，并触发 `answer_artifact_contract`、`finalization_state`、`citation_provenance` hard failures。
- Contributing factors：Planner `PLANNER_GENERATION_ERROR` 后按既有 contract `executed_without_plan`；Retrieval 返回 partial coverage；Trace 没有记录完整 raw provider payload 或 hidden reasoning。
- 已保存 `FailureDiagnosis` 到临时 Evaluation Store；没有修改 Trace，没有 retry 或 fallback。

## Known limitations

- 这是真实 Provider baseline，但没有人工 Review，所以不能用结果 status 推导语义质量。
- `last-stable-m6` 的业务 Variant identity pin 到 M6 `cce944d`；本次 Evaluation harness 运行在 M7 HEAD `94334ff`，其中包含 Evaluation/Trace metadata 装配改动。若要对整个 checkout 做字节级 baseline/candidate replay，需要在隔离 worktree 中分别装配对应 Evaluation harness。
- `INVALID_ANSWER_ARTIFACT` 的 Trace 证据足以定位 Finalizer boundary failure，但不足以确认 hidden model cause；应保持 `likely`。
- 本轮只执行 1 repetition，不能估计 DeepSeek stochastic variance。
- Token usage 可测，cost 未可靠获得；不能直接宣称成本。
- 临时 Evaluation Store/Trace/Conversation 数据不提交到仓库；如需长期比较，应在相同 Snapshot 上重新建立受控 Run。
