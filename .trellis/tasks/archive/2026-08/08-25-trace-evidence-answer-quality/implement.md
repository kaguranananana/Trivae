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

## Checkpoint F — Agent Harness / Context Engineering hardening

### 设计边界

- [x] 先完成 JSON mover audit；模型保留语义字段，Host 接管确定性 identity、URL、scope、
  相对时间和结果 bookkeeping。
- [x] 保留旧 `AnswerArtifact` serialization 和显式 full source locator codec；新
  `ModelAnswerCandidate` 只在当前 finalization 内存中存在。
- [x] source handle 只在当前 Run/Tool Result scope 有效；不做跨 run 猜测、source repair 或
  静默 citation drop。

### 实现顺序

1. 在 Evidence 层新增 source handle、候选答案和 Host compiler/finalizer path。
2. 让 Tool Result 走 canonical host record + slim model projection；加独立 model token budget，
   当前默认 16,000，且 trimming 先保护真实 hit。
3. 增加 Host-owned relative time contract、archive latest 聚合和 resolved query snapshot。
4. 更新 prompt、Agent Runtime/Evidence/Context Engineering contract 与 interview defense。
5. 添加 JSON mover、source scope、relative time、hit preservation、旧 codec regression。

### Checkpoint F 验证

- [x] `pytest -q`：311 passed。
- [x] `ruff check src tests`：通过。
- [x] `mypy src`：通过。
- [x] `python -m compileall src`：通过。
- [x] `git diff --check`：通过。
- [x] Trellis validation、CLI smoke 和三条新增真实问题 smoke；provider 原始 tool-result token
  未直接提供，Trace 同时记录 Host projection estimate 与 unavailable 边界。

### Checkpoint F smoke metrics

| Case | Trace | terminal | model turns / tool calls | retrieval partial / truncated | citation unresolved | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| 31-hit GitHub/resources | `trace-0f20c501badd495f8cc9064439ae6327` | completed | 2 / 2 | 0 / 0 | 0 | lexical 31/31；Evidence 1 |
| Agent 学习资料 | `trace-0b2409b0c5104cf78b57004ac949b8be` | completed | 2 / 2 | 1 / 1 | 0 | semantic partial；GitHub lexical 31/31 |
| taste-skill | `trace-621002d125374e90910c2b8283927698` | completed | 2 / 2 | 0 / 0 | 0 | context 解释与使用边界保留 |
| DeepSeek | `trace-c0b77d168967490babe7130402050bbf` | completed | 2 / 2 | 0 / 0 | 0 | relative range 已进入 query/Trace |

provider `usage` 可从 Trace 读取；provider 原始 tool-result token 没有独立上报，因此该指标
不伪造为真实 usage。当前 Trace projection 已提供 Host-side estimate 和 projection
truncation count。

### Checkpoint F before/after observation

同一数据库 snapshot、同一语义问题的历史成功 Trace `trace-b5f6b74d8abe4f779078f1e1791a7d1e`
与本轮 `trace-0f20c501badd495f8cc9064439ae6327` 可作方向性对照，但不是严格控制变量的
benchmark（模型决定的 tool sequence 与 query 文本空格略有差异）：

| 指标 | Before | After |
| --- | ---: | ---: |
| terminal | completed | completed |
| tool calls / retrievals | 4 / 4 | 2 / 2 |
| provider input tokens | 51,341 | 24,546 |
| provider output tokens | 5,695 | 2,064 |
| provider total tokens | 57,036 | 26,610 |
| wall-clock latency | 269,636 ms | 174,492 ms |
| retrieval partial / truncated | 0 / 0 | 0 / 0 |
| citation unresolved | 0 | 0 |
| tool-result token metric | unavailable | Host estimate 14,396；projection truncation 0 |

这些数值说明本轮 boundary 变更在该重跑上减少了模型回合和 provider usage，但不宣称固定
收益百分比；provider 原始 tool-result token 的 Before 值仍是 unavailable。
