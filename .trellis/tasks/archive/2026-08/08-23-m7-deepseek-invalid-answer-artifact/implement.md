# M7 DeepSeek invalid Answer Artifact 修复实施

## 计划

- [x] 阅读 M1–M7 ADR、M6 failure records、Baseline task 与 backend coding guides。
- [x] 在临时真实 Snapshot 上复现，capture provider request 的 JSON mode、finish reason、输出结构摘要。
- [x] 增加 settings 与 Runtime provider boundary 的最小实现。
- [x] 先加入能在修复前失败的 deterministic regression，再实现修复。
- [x] 运行 full quality gates 与 Trellis validation。
- [x] 在同一临时 Snapshot 上重跑真实 DeepSeek baseline/repetition/paired smoke。
- [x] 更新 validation、归档 task，commit/push，确认 clean worktree。

## 不做

- 不增加 retry/fallback/JSON repair。
- 不放宽 provenance、citation 或 Finalizer contract。
- 不创建 EvalRuntime、EvalOrchestrator 或新的 provider chain。
- 不提交真实聊天正文、secret、完整 Trace payload 或临时数据库。
