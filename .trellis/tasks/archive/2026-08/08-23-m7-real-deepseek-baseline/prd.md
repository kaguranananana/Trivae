# M7 real DeepSeek baseline

## Goal

Run and record the real DeepSeek last-stable baseline on a temporary real-data Snapshot, including per-Run operational facts and Trace-based diagnosis.

## Requirements

- 使用 `.env` 只在当前进程读取 DeepSeek credential；任何输出、Trace、Evaluation Store、文档和 Git diff 都不得包含 key 或完整私有聊天正文。
- 将 Canonical SQLite 复制到临时工作目录，在副本上显式重建 FTS；Canonical DB 不得写入。
- 使用 version-controlled `last-stable-m6` Variant（code `cce944d`、DeepSeek `deepseek-v4-flash`、M6 budget/config）执行真实 Provider baseline。
- 通过 `TrivaeApplication.query()` / `EvaluationRunner` 执行固定 Case；不增加 retry、fallback、clamp 或第二套 Agent 链路。
- 保存每个 Run 的 terminal、Answer Artifact/Finalizer、Trace reference、usage、latency、Tool/Retrieval facts 和 deterministic checks。
- 对真实失败读取 Trace，建立后验 `FailureDiagnosis`；不以 Diagnosis 覆盖 canonical Trace，也不把未 Review 结果当作质量结论。

## Acceptance Criteria

- [x] Provider safe configuration preflight 通过，API key 未被输出。
- [x] 临时 Snapshot 可解析，canonical data 未修改。
- [x] 8 个代表性 Calibration Case 使用生产 QueryOrchestrator 完成真实 DeepSeek Run。
- [x] 每个 Run 均保存到独立 Evaluation Store，并能关联 Trace。
- [x] 真实失败保留为 failed Result，并完成 Trace-based FailureDiagnosis。
- [x] Validation 区分 measured operational facts、quality not reviewed、failure diagnosis 和 limitations。
- [x] 文档、task lifecycle、commit/push 和 clean worktree 完成。

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
