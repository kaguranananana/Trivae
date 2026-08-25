# 实现计划

## Planning gate

- [x] 读取 AGENTS.md、Trellis workflow、project/backend specs、Evidence/Citation 与 Trace ADR。
- [x] 读取真实 Trace 的脱敏事件链，确认 `STRUCTURED_VALUE_MISMATCH` 是 citation owner 的主失败。
- [x] 建立 baseline：291 tests passed。
- [x] 明确 change boundary：evidence/finalizer、stream visibility、CLI projection、codec、tests。
- [x] `task.py start` 后进入实现阶段。
- [x] 按跨层变更回写 `agent-runtime-guidelines.md` 与 `product-experience-guidelines.md` 的可执行契约。

## Checkpoint A — Structured citation contract

1. 先添加失败回归：identity-only structured source 成功、wrong identity/locator/value 失败、
   FinalizationError path 具体化。
2. 为 ToolStructuredItem 增加稳定 source identity，并在 model provenance 中输出短 locator。
3. 让 parser 接受 identity-only candidate；Finalizer 仍从 current-run record 精确 hydrate value，
   legacy explicit value 继续严格比较。
4. 更新 prompt，禁止模型复制不必要的大型 value，并要求资源类回答保留 URL 与观察/解释边界。

验证：已通过；相关聚焦回归覆盖 identity-only、错误值和 source path。

## Checkpoint B — Trusted URL 与 Evidence projection

1. 添加 URL extractor 和 MessageDisplaySnapshot bounded URL 字段；从 full canonical message content
   提取后再截断 excerpt。
2. 扩展 Answer Artifact JSON codec，保留旧 payload 读取能力。
3. CLI 成功答案增加 Evidence block：claim binding、finding、criterion、sufficiency、source
   indices、limitations；Sources 增加 URLs、structured value 和 locator。
4. 保持 `/source n` 复用现有 Application facade，不新增 Query/SQLite 访问。

验证：已通过；CLI、Product Experience、Conversation codec 回归均通过。

## Checkpoint C — Public process summary

1. 保留 `QueryStreamEvent` 的 reasoning 顺序消费能力，但不把 provider reasoning 文本投影到 CLI。
2. Renderer 只展示真实 Route/Plan/Tool/Retrieval facts 和最终 Evidence；不根据 provider 字段名
   推断 reasoning 安全性。
3. 添加 provider reasoning、空 reasoning 和 failure preview 回归。

验证：已通过；provider reasoning 隔离与 Tool-turn provisional 文本回归均通过。

## Checkpoint D — Full quality gate

- [x] `PYTHONPATH=src .venv/bin/pytest -q`（304 passed）
- [x] `PYTHONPATH=src .venv/bin/ruff check src tests`
- [x] `PYTHONPATH=src .venv/bin/mypy src`
- [x] `PYTHONPATH=src .venv/bin/python -m compileall -q src tests`
- [x] `PYTHONPATH=src .venv/bin/python -m trivae chat --help`
- [x] `python3 ./.trellis/scripts/task.py validate .trellis/tasks/08-25-trace-evidence-answer-quality`
- [x] `git diff --check`
- [x] 使用当前 Trace 的脱敏 Failure Case 做一次真实回归；最终 Trace
  `trace-2e3aaaacee2246ee991e2c2d7c143b34` 成功完成；早期 provider 输出预算失败已被修复并保留
  在本地 Trace 日志中。

## Checkpoint E — Retrieval result bound and final-answer budget

1. 复现真实 `total_hits=31 / returned=20`，确认 20 同时来自 Scope、Capability、Retrieval 和
   Provider schema 的默认值，而不是数据缺失。
2. 新增 `DEFAULT_RESULT_LIMIT=100`，让 lexical 默认 limit、trusted scope、Function Tool schema 和
   Evidence transport 使用同一个 bounded contract；保留显式 scope enforcement 和 truncation facts。
3. 更新资源清单 prompt：宽检索使用最大可信 limit 与零上下文窗口；最终 JSON 优先输出 evidence/citation
   和闭合结构，只列代表性 URL。
4. 用 31 条 fixture 做默认检索回归，再用真实 provider 重跑原始问题。

验证结果：31 条 fixture 全部返回；真实 Trace
`trace-b5f6b74d8abe4f779078f1e1791a7d1e` 为 `completed`，`retrieval_partial_events=0`、
`retrieval_truncated_events=0`、citation unresolved 为 0，终端展示了 31/31 命中、具体 URL 和
Sources。

## 回滚点

- A：只回滚 structured candidate/source identity 与 prompt/finalizer 诊断，不改变已持久化 Artifact。
- B：只回滚 URL/Evidence CLI projection；Message/Structured source identity 和 strict Finalizer 保留。
- C：只回滚 public process display；Trace、Runtime 和 Answer Artifact contract 保留。
