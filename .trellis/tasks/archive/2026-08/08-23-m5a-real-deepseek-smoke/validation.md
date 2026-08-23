# M5a real DeepSeek smoke validation

## 1. Scope and data preparation

本次验证使用仓库当前已导入的真实 SQLite canonical 数据，不保存完整模型回答、聊天正文或 secret。

- canonical message count：`473236`
- existing Agent capability surface：`search_messages` only
- derived FTS：通过现有 `SQLiteLexicalIndex.rebuild()` 在真实数据快照上重建，`indexed_messages=473236`、`fts5_available=true`
- 原始数据库当时被桌面 DB Browser 占用，直接重建等待写锁；等待事务已中止并通过 `PRAGMA integrity_check` 确认 canonical 数据库为 `ok`。后续 smoke 使用同一真实数据库的快照准备 derived FTS，未改变 canonical message 内容。

## 2. Deterministic retrieval facts

以下是本次 provider smoke 前用本地 Retrieval Core 确认的事实，不是模型推测：

| Case | 查询关键词 | 命中 | 上下文/截断 | 观察 |
| --- | --- | ---: | --- | --- |
| M5A-S1 | `向量` | 1 | 默认上下文返回 5 条，未截断 | 单条明确命中，适合最小 happy path |
| M5A-S2 | `postgres pgvector` | 2 | 默认上下文返回 10 条，未截断 | 同一 session 的少量消息共同支撑一个 finding |
| M5A-S3 | `postgres 向量` | 0 | 无上下文，未截断 | `postgres` 单独命中 3 条、`向量` 单独命中 1 条；组合检索没有同消息命中，不能升级为全局不存在 |
| M5A-S4 | `pgvector` | 7 | 无上下文返回 7 条；默认上下文返回 20 条并标记截断 | 命中跨 4 个 session；真实数据存在扩展性/规模限制性讨论，但不预设模型必须产出 `contradicts` |

## 3. Failure and minimal fix

### Observed failure

修复前的 S2 provider run：

- Runtime `termination=completed`
- `search_messages` tool calls/results：`2 / 2`
- final output 为 plain text，不能解析为 JSON object
- `AnswerArtifact`、Evidence、Citation 均未提交
- `finalization_error=INVALID_ANSWER_ARTIFACT`

### Root cause

这是 DeepSeek final synthesis 的 structured-output composition failure：原 adapter 只有 prompt 约束，模型在多消息查询中没有稳定遵守单一 JSON object contract。既有 Finalizer 正确拒绝了裸文本，没有被改成成功答案。

### Minimal fix

- `OpenAIAgentsRuntimeAdapter` 给 `OpenAIChatCompletionsModel` 配置 `ModelSettings.extra_args.response_format={"type":"json_object"}`。
- final synthesis prompt 明确要求有效 json object，并禁止 markdown fence、前后额外说明和裸文本。
- 没有改 Finalizer、Citation contract、current-run provenance、ExecutionScope 或 trusted hydration。

### Regression protection

新增 `test_agent_requests_provider_json_mode_for_final_synthesis`，确定性验证 Agent 将 provider JSON mode 传给 SDK model settings。

## 4. Real DeepSeek smoke results

四个 case 均在 S1 成功后按顺序执行；表内均为真实 provider run 观察值，不是预期模型行为：

| Case | Query / Router | Tool calls/results | JSON | Evidence / Citation | hydrated MessageSource | Finalization / Query |
| --- | --- | ---: | --- | ---: | ---: | --- |
| M5A-S1 | `群聊里有人提到过“向量”吗？请用找到的消息回答，并给出证据。`；`standard_execution`，无 Planner | 1 / 1 | 是 | 1 / 1 | 5 | `None` / `true` |
| M5A-S2 | `群聊中关于 Postgres 和 pgvector 的讨论，主要提到了哪些内容？请用找到的消息给出一个有证据的简要总结。`；`planned_execution`，实际无 Plan object | 2 / 2 | 是 | 7 / 4 | 9 | `None` / `true` |
| M5A-S3 | `群里是否有人明确说过 PostgreSQL 不适合做向量检索？如果当前检索没有找到，请明确说明证据不足。`；`standard_execution`，无 Planner | 2 / 2 | 是 | 0 / 0，1 条 limitation | 0 | `None` / `true` |
| M5A-S4 | `群聊里关于 pgvector 的讨论，是否既有推荐或支持，也有对扩展性或规模的限制？请分别说明并给出消息证据。`；`standard_execution`，无 Planner | 1 / 1 | 是 | 2 / 2，3 条 limitation | 5 | `None` / `true` |

共同观察：四次 Runtime 均 `termination=completed`，tool status 均为 `ok`，final output 均为可解析 JSON object。S1/S2/S4 的 MessageSource 均完成 trusted hydration；S3 正确形成无 Evidence 的结构化限制性答案。S4 实际 relation 为 `supports=4`、`context=1`，没有真实产生 `contradicts`，因此没有为了覆盖类型而改写结果。

## 5. Quality gates

- `PYTHONPATH=src .venv/bin/python -m pytest -q`：`114 passed`
- `.venv/bin/ruff check src tests`：通过
- `PYTHONPATH=src .venv/bin/mypy src`：`Success: no issues found in 38 source files`
- CLI help：通过
- Trellis task validation：通过
- `git diff --check`：通过

## 6. Boundaries and remaining limitations

- 本次成功证明真实 DeepSeek 能穿过 M5a 的 Runtime → ToolResult → structured AnswerArtifact → Finalizer → trusted hydration 边界；不证明回答的语义正确率或长期 JSON 稳定性。
- 当前 Agent registry 只有 `search_messages`，没有可供 Agent 调用的 structured/aggregate tool，因此没有执行 Structured aggregate citation case。
- S4 真实运行没有 `contradicts` binding；真实数据虽然有支持与限制性讨论，但本次模型选择了 `supports/context` 表达，不能据此宣称冲突引用能力已通过真实 provider 验证。
- 没有新增 retry、fallback、silent citation repair 或裸文本成功路径。
