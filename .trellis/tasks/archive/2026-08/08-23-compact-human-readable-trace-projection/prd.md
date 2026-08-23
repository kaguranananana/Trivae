# Compact human-readable Trace projection

## Goal

让默认 `.log` 成为适合人工排障的 execution mainline：打开后从 Trace Summary、User、Context、Router、Planner、Model Turn、Tool、Retrieval、Evidence/Citation 一直读到 Final Answer；Raw normalized events 继续由 SQLite canonical Trace 和 `trace show` 提供，不在默认文本日志中重复复制。

## Requirements

- 保持 SQLite `StoredTrace` / `NormalizedQueryEvent` 为唯一 execution source of truth；只调整 `StoredTrace -> text projection` 与 CLI export view。
- 默认 human-readable export 在 `[FINAL ANSWER]` 后结束，不再追加 `RAW TRACE EVENTS`。
- 在 Transcript 顶部加入 Trace Summary，至少显示 terminal outcome、duration、model turn count、tool call count、planner failure count、retrieval truncation/partial 和 final answer availability。
- 默认 Model Turn 使用增量 context：首轮显示完整 model-visible input，后续只显示相对上一轮新增/变化的 items；必须明确写出 `New input since previous turn`。
- 保留完整 model-visible context 详细视图，由同一 `StoredTrace` 投影生成，可通过 `trace export --context full` 选择；不能重新查询数据库或 Runtime。
- 保留 raw text projection 能力作为显式 `trace export --view raw`，但不作为默认 `.log`；默认仍输出 transcript。
- `normal/debug` capture contract、hidden Chain-of-Thought 禁止规则、secret filter 和 scope boundary 不变。
- 兼容旧 Trace：没有完整 model context 或没有 answer snapshot 时，必须显式显示 limitation/不可用，而不是猜测。

## Acceptance Criteria

- [ ] 默认 `.log` 不含 `RAW TRACE EVENTS`，并在 `[FINAL ANSWER]` 后结束。
- [ ] 同一真实 Trace 的默认日志体积显著小于 baseline，且仍保留 User、Router、Planner、Model Turn、Tool Call/Result、Retrieval、Evidence/Citation、Final Answer。
- [ ] Trace Summary 能让人工快速看到 terminal、turn/tool 数量、planner failure 和 retrieval truncation。
- [ ] 后续 Model Turn 默认只展示相对上一轮新增 items；`--context full` 可恢复完整每轮 model-visible context。
- [ ] `trace export --view raw` 可显式导出原始 event projection；默认 export 与 raw view 由同一 StoredTrace 派生。
- [ ] 现有 `trace export`、Application facade、CLI chat、历史 Trace 重建和 failure-on-export contract 无回归。
- [ ] 完成 `pytest`、`ruff check src tests`、`mypy src`、`git diff --check`，并用现有真实 DeepSeek Trace 验证输出。

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
