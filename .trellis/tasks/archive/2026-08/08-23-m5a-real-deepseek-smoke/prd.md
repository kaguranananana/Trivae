# M5a real DeepSeek smoke stabilization

## Goal

在不改变 Stage 1.8 Evidence / Citation 语义的前提下，让真实 DeepSeek 至少完成一条：

```text
Query → Router / Runtime → search_messages → current-run ToolResult
→ structured final synthesis → Citation Finalizer → trusted hydration
→ QueryResult.is_successful == true
```

优先使用上一轮确认的 M5A-S1 真实聊天问题；S1 成功后再按 S2、S3、S4 顺序执行代表性 smoke。

## Requirements

- 使用当前已导入的真实聊天数据；`messages_fts` 作为可重建 derived data 准备，不改变 canonical messages。
- 使用真实 DeepSeek provider；不把 deterministic fixture 结果冒充真实 provider 结果。
- 对每个失败先复现、定位 root cause，再做最小修复、deterministic regression test 和重跑。
- 可以修复 M5a prompt、provider adapter、smoke harness、derived-index preparation 和明确的小型接线问题。
- 不得把 Tool 后裸文本变成成功答案，不得移除/替换 invalid citation，不得放宽 current-run provenance、ExecutionScope 或 trusted hydration。
- 不新增 Evidence Agent、Judge、`retrieve_evidence`、Runtime Evidence State Machine、无依据 retry/fallback。
- 不记录 API key、完整聊天正文或无界 provider payload。

## Acceptance Criteria

- [x] S1 真实运行至少完成一次 `termination=completed`。
- [x] S1 至少调用一次 `search_messages`，并产生至少一个 current-run `ToolResultRecord`。
- [x] S1 DeepSeek final synthesis 可解析为 Answer Artifact，至少包含一个 Evidence Item、Citation Binding 和 MessageSource。
- [x] S1 provenance、scope、locator validation 和 trusted message hydration 全部通过，`finalization_error is None` 且 `QueryResult.is_successful is True`。
- [x] S1 失败若发生，根因、最小修复和 regression protection 有可复核记录。
- [x] S1 成功后尝试 S2、S3、S4，并分别记录成功、失败根因和 execution/evidence limitations。
- [x] deterministic pytest、ruff、mypy 与 Trellis validation 通过，或明确记录真实阻塞。

## Scope Boundary

- M5b Conversation / Assistant Message persistence 不在本任务内。
- 不把真实 smoke 结果写成 semantic correctness 或稳定质量 baseline；semantic evaluation 留待后续 Evaluation。
