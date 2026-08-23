# Fix real DeepSeek invalid answer artifact

## Goal

Reproduce the real DeepSeek baseline finalization failure, repair the production seam without fallback or retry, add regression coverage, and re-run the real calibration.

## Requirements

- 复现并记录真实 DeepSeek `INVALID_ANSWER_ARTIFACT`，保留 QueryResult 与 canonical Trace 的失败事实。
- 修复真实 provider completion boundary：最终 JSON synthesis 使用显式、可配置且可纳入 Variant identity 的输出预算；Router/Planner JSON completion 使用同一 provider 的显式 JSON mode 和有界预算。
- 不修改 Answer Finalizer 的严格校验，不增加 retry、fallback、clamp、自动修复 JSON 或第二套 Runtime/Retrieval/Tool 链路。
- 不让 secret、完整 private chat、hidden reasoning 或无限长 provider payload 进入 Trace、Evaluation Store、review artifact 或文档。
- 增加 deterministic regression，验证实际 provider request 带有 JSON mode 和预算，非法 JSON 仍由 Finalizer 显式失败。
- 在同一临时真实 Dataset Snapshot 上重新运行 DeepSeek baseline/repeated smoke，并记录修复前后可测事实、残留 Planner degraded 和已知限制。

## Acceptance Criteria

- [x] 真实失败的 Trace diagnosis 已固定为可回归的 provider-output contract failure。
- [x] Runtime 和可选 Router/Planner completion 的生产请求包含显式 JSON/budget 配置，配置不包含 secret。
- [x] Existing QueryOrchestrator、Finalizer、Trace append-only 和 Evaluation Store ownership 未被复制或绕过。
- [x] 新增测试覆盖 settings、provider request projection、strict finalization 和真实 Failure regression。
- [x] 同一 Snapshot 的真实 DeepSeek re-run、repeated-run smoke 和 failure regression 完成；任何残留失败原样报告。
- [ ] pytest、ruff、mypy、diff-check 与 Trellis validation 通过，task 文档完成并提交推送。

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
