# Stream final answer token-by-token via provisional answer events

## Goal

修复 Web UI 最终回答"整块蹦出"的问题：answer 应与 thinking 一样逐 token 流式，同时不破坏"模型在 Tool 前的中间叙述不得冒充最终答案"的既有边界（CLI/TUI 行为不变）。

## Root Cause

`QueryStreamAdapter.handle_runtime_event` 把 `content_delta` 解析结果攒进 `pending_answer_fragments`，直到 `turn_completed` 才 `_flush_answer_turn` 一次性发 `answer.delta`。原因：无法预知本回合是否还会调 Tool——若回合内有 Tool，先前的正文只是叙述，不是答案。这导致最终答案在回合结束时整块到达。

## Requirements

- R1 `QueryStreamEvent` 新增 provisional 流式语义（additive、UI-neutral）：
  - content delta 到达时**立即**发 `answer.delta`（新增 `provisional: bool` 字段，默认 False 保持兼容）
  - 回合确认无 Tool（turn_completed / terminal completed）：无需补发，正文继续保留为最终答案
  - 回合确认有 Tool（tool 边界后 turn 完成）：对已发出的该回合 provisional 正文发 `answer.superseded` 事件，携带被降级的文本
- R2 Web store：
  - provisional delta 照常追加到 answer（用户立即看到流式）
  - 收到 `answer.superseded` 时，把当前 answer 文本转为一个过程叙述块（text block，进过程组），answer 清空继续等下一回合
  - `answer.completed`（finalizer 权威文本）到达时，用权威文本覆盖 answer（修正 parser/finalizer 差异）
- R3 CLI/TUI 不受影响：cli_renderer 忽略 superseded/provisional 语义（渲染不变）；TuiProjectionEngine 不依赖该字段
- R4 NDJSON 层透传新字段/新事件类型

## Acceptance Criteria

- [ ] 单测：content delta 即时产生 answer.delta；带 Tool 回合触发 superseded；无 Tool 回合文本保留
- [ ] `uv run pytest tests/ -q` 全绿；ruff/mypy 干净
- [ ] web vitest/tsc/build 通过；store 单测覆盖 provisional→superseded→text block 转换与 completed 覆盖
- [ ] 真实 provider smoke：answer.delta 按时间分散到达（非同一秒内 145 条）
- [ ] 真实浏览器可见逐字流式
- [ ] commit 到 codex/web-ui 并归档任务

## Notes

- 设计对齐 ChatLab：文本先流式显示，出 Tool 后 UI 把中间叙述折进过程组（buildCompletedSegments 的 text-before-tool 吸收语义）。
- 不改 Finalizer/canonical 语义；provisional 只是 live 展示边界，conversation 持久化仍只认 validated artifact。
