# M7 Real DeepSeek Baseline Implementation

## Execution checklist

- [x] 检查 branch、clean worktree、`.env` safe configuration；不输出 credential。
- [x] 创建临时 Canonical SQLite 副本并重建 FTS5。
- [x] 构造 8 个 typed Case 和 `real-deepseek-baseline@v1` Calibration Suite。
- [x] 通过 `EvaluationRunner` 调用生产 `TrivaeApplication.query()`，使用 `last-stable-m6`，每 Case 1 repetition。
- [x] 将每次 Run、Result、Trace reference 写入临时 Evaluation Store。
- [x] 读取失败 Run Trace，保存 `FailureDiagnosis(status=likely)`。
- [x] 写入 Measured Facts、质量边界、Failure Diagnosis 和 Known Limitations。
- [ ] 若要宣称质量变化，补齐人工 Review；本任务不以未 Review 的 baseline 推导质量分数。

## Implementation facts

- Provider safe projection：DeepSeek API base、`deepseek-v4-flash`、8 max turns、3 max tool rounds；key 未进入输出。
- Snapshot：473,236 messages、14 sources、FTS5 473,236 indexed messages。
- 8 个真实 Run 均 terminal `completed`、Trace `complete`；7 个 Answer Artifact/Finalizer 通过，1 个 `context-expansion` Run 为 `INVALID_ANSWER_ARTIFACT`。
- 失败 Trace 同时记录 `PLANNER_GENERATION_ERROR` / `executed_without_plan`、partial retrieval、citation validation failure 和 query terminal failure。
