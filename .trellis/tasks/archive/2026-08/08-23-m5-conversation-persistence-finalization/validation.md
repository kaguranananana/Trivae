# M5 durable conversation persistence finalization — validation

## 1. Scope and implementation result

本任务完成 M5b 的最小 durable vertical slice：

```text
QueryRequest
→ persisted Conversation history
→ Router / optional Planner / shared AgentRuntime
→ current-run ToolResult provenance
→ Evidence/Citation Finalizer
→ validated AnswerArtifact
→ atomic User + completed Assistant commit
→ close/reopen replay
```

实现落点：

- `src/trivae/conversation/contracts.py`：Conversation、completed ConversationMessage、Store Protocol 与历史 model-context 编译。
- `src/trivae/conversation/serialization.py`：显式 AnswerArtifact JSON codec，覆盖 content blocks、CitationBinding、Evidence、MessageSource trusted snapshot、StructuredSource value/query scope snapshot 与 limitations。
- `src/trivae/conversation/sqlite.py`：独立 SQLite Conversation Store、两张表、稳定 ordinal replay 和 `BEGIN IMMEDIATE` atomic commit。
- `src/trivae/bootstrap/application.py`：create/read/query/lifecycle 接线；只有 validated successful Query 才能提交 turn。
- `src/trivae/query/contracts.py`：增加可选 `conversation_id` 和结果中的实际 conversation id，保留既有 positional 参数顺序。
- `tests/test_conversation.py`：codec、restart、transaction、Application success/failure 和 fresh provenance 回归覆盖。

## 2. Measured quality gates

以下命令在 2026-08-23 通过：

| Check | Result |
| --- | --- |
| `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_conversation.py` | `7 passed in 0.09s` |
| `PYTHONPATH=src .venv/bin/python -m pytest -q` | `121 passed in 1.40s` |
| `.venv/bin/ruff check src tests` | `All checks passed!` |
| `PYTHONPATH=src .venv/bin/mypy src` | `Success: no issues found in 42 source files` |
| `PYTHONPATH=src .venv/bin/python -m trivae --help` | exit 0，CLI usage 正常输出 |
| `python3 ./.trellis/scripts/task.py validate 08-23-m5-conversation-persistence-finalization` | `All validations passed` |
| `git diff --check` | exit 0，无 whitespace error |

## 3. Real SQLite + DeepSeek smoke

烟测使用真实 SQLite 数据库的临时副本；没有打印 secret、完整回答、完整聊天内容或 provider payload。

### Dataset / setup facts

- 原始 Canonical SQLite 直接检查得到 `messages=473236`。
- 原始文件当时没有 `messages_fts`；这被记录为 derived-index smoke 前置条件，不被包装成生产故障。
- 按既有“显式 rebuild derived FTS、禁止静默 LIKE 降级”的契约，在临时副本执行 `rebuild_lexical_index()`：`indexed_messages=473236`、`fts5_available=true`。

### Query facts

真实 DeepSeek 查询成功，secret-safe 摘要为：

- `is_successful=true`、termination=`completed`；
- `tool_call_count=1`、`tool_result_count=1`；
- `finalization_error=null`；
- `evidence_count=1`、`citation_binding_count=1`；
- `hydrated_message_source_count=5`、`structured_source_count=0`；
- 返回了 conversation id 与 run id，但没有记录其原始值。

### Restart facts

close/reopen 后直接读取 Conversation Store：

- message roles 为 `user`、`assistant`，顺序稳定；
- `replay_artifact_present=true`；
- `replay_evidence_count=1`、`replay_citation_binding_count=1`；
- `replay_hydrated_snapshot_count=5`；
- replayed answer text 与成功 Query 的 answer text 一致。

这条 replay 路径直接 decode 持久化 `answer_artifact_json`，没有重新调用 LLM、Retrieval 或 hydration。

## 4. Failure and regression classification

### Development defect found and fixed

- 初次静态检查发现测试文件存在未使用的 `ConversationPersistenceError` import；根因是测试重构后残留 import，已删除并重新运行 Ruff、focused tests 与全量 tests。
- 这不是产品运行时 Failure；没有为了通过检查增加兼容分支、fallback 或静默吞错。

### Environment setup observation

- 原始数据库缺少 derived `messages_fts`，因此烟测先在临时副本显式重建索引；Canonical 原文件未被改写。
- 这是既有 derived-index contract 要求的 setup observation，不新增自动同步或 LIKE fallback。

### Regression tests

- Assistant insert 被注入失败：User insert 已发生时整个 transaction rollback，不留下 User 或 Assistant 半个 turn。
- Finalizer failure、runtime failure / incomplete runtime：不调用 `commit_turn()`，没有 completed Assistant row。
- 历史 Evidence 使用旧 locator 配合新 run：Finalizer 返回 `INVALID_PROVENANCE`；历史 Artifact 只能作为 context/replay，不能成为新 ToolResult provenance。
- 成功 follow-up 使用新的 scripted run/tool/result：可以形成新的 completed turn，两个 Artifact 的 provenance 不同。

没有真实 DeepSeek provider failure 或 Conversation Store production failure 在本轮发生；不能虚构为 Failure Case。

## 5. Design rationale and trade-offs

- 选择独立 `conversation/` package、独立 Store connection 和两张 Conversation 表，保留 Canonical Message Store、Retrieval read repository 与 Conversation lifecycle 的 ownership。
- 选择显式 JSON codec，而不是 `pickle`、`asdict()` 或重新 hydration：持久化格式可检查，恢复复用现有领域构造函数，损坏/未知 discriminator/content mismatch 会显式失败。
- 选择 `BEGIN IMMEDIATE` 的单 transaction 追加 User + Assistant；成功定义为一个完整 turn，任何 insert、约束或 codec 错误都 rollback。
- 选择 Application 作为唯一 commit gate；Runtime、Router、Planner、Tool、Finalizer 不写 SQL，避免复制 Query execution 或把业务回答写入 Canonical Chat source of truth。
- 不引入 SDK/provider Session 作为 history source of truth；不引入 Trace backend、Evaluation judge、normalized Artifact tables、retry/fallback、regenerate endpoint 或 history compression，因为本轮没有对应真实 Failure Case 或已完成架构实现。

## 6. Boundary, limitations and evolution

```text
Application：拥有 Conversation lifecycle、历史编译和 validated commit gate。
Conversation Store：拥有 conversations/conversation_messages SQL 与 Artifact codec boundary。
Canonical Store：拥有导入后的聊天事实；Retrieval read repository：拥有只读 projection/FTS。
Runtime/Router/Planner/Tool/Finalizer：产生或校验 Query 数据，不执行 Conversation SQL。
```

当前限制：

- Trace backend、Evaluation semantic quality、citation precision/recall、HTTP/API、UI、mutation UX、branching/regenerate、history window/compression 和长期 migration 仍未实现。
- 当前 replay 直接恢复单个 Conversation 的完整持久化消息；是否需要窗口化、压缩或分支必须由真实 workload / Evaluation 触发。
- 真实 smoke 证明的是 SQLite/DeepSeek persistence facts，不等于回答语义质量 baseline。

未来只有出现可复现的历史规模、mutation/audit、schema migration、branching 或 semantic-quality Failure Case，并有对应 regression/evaluation，才重新评估上述 deferred 能力。

## 7. Completion checklist

- [x] Conversation create/read 与 User/Assistant 稳定顺序。
- [x] AnswerArtifact serialize → SQLite → close/reopen → deserialize round-trip。
- [x] MessageSource snapshot、StructuredSource、CitationBinding、Evidence、relation、sufficiency、limitations round-trip。
- [x] Finalization success 后才 atomic commit User + completed Assistant。
- [x] Runtime/finalization failure 与 transaction mid-failure 不留下半个 completed turn。
- [x] Restart replay 不重新搜索、hydrate 或调用 LLM。
- [x] Fresh follow-up 使用新 run/tool/result provenance，old Evidence 显式失败。
- [x] 真实 SQLite + DeepSeek persistence smoke。
- [x] Deterministic tests、pytest、ruff、mypy、CLI help、Trellis validation、`git diff --check`。
- [x] 相关 backend/project specs 与 interview-defense evidence 已同步。
