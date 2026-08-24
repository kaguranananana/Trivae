# Product Experience Hardening Validation

## Scope

本记录只覆盖 CLI/Application hardening：source review、scope/readiness、feedback/history、
renderer/failure projection。没有修改 QueryOrchestrator、Runtime、六个 Tool、Retrieval ranking、
Evidence Finalizer、Trace event taxonomy 或 Evaluation label semantics。

## Failure cases and handling

| 分类 | 场景 | 根因/owner | 当前处理 | 回归证据 |
| --- | --- | --- | --- | --- |
| regression test case | 同一 source 被多个 Evidence 引用 | source display index 需要稳定且不重复 | 按 finalized locator 顺序去重并聚合 evidence/relation | `test_source_summaries_are_deterministic_and_deduplicated` |
| regression test case | `/source` 读取越过 session/time scope | canonical context read 必须重新服从 trusted scope | Application 调用 `read_message_context_scoped()`，anchor/context 边界失败显式抛出 | `inspect_message_source()` contract + local smoke |
| regression test case | 旧 Conversation 没有 scope | 历史 row 无法证明授权范围 | 保留 history display，resume/query 显式拒绝，不猜 scope | `test_conversation_scope_round_trips_and_legacy_scope_is_null` |
| regression test case | 同一 Query 重复 `/good`/`/bad` | 用户体验反馈不是多条 ground truth | 独立 feedback DB 按 `(conversation_id, trace_id)` upsert | `test_feedback_is_separate_and_upserts_one_query` |
| regression test case | 空数据库启动 | semantic derived index 尚未建立 | readiness 显示 `messages=0` 与 semantic `missing`，不 rebuild | `test_application_readiness_is_local_and_does_not_rebuild` |
| regression test case | provider reasoning/raw event/JSON 进入终端 | renderer 误把 debug facts 当产品正文 | 同源事件仍消费，但 normal/verbose 不渲染 hidden CoT/raw identity/JSON | `tests/test_cli_renderer.py` |
| anticipated risk | real provider 不返回 reasoning、网络失败或语义索引状态变化 | external state 不属于 deterministic CLI contract | 保留已有 normalized failure/status；真实 smoke 按 failure category 记录 | 未伪造 provider success |

## Commands and results

- `PYTHONPATH=src .venv/bin/pytest -q` → `282 passed`。
- `PYTHONPATH=src .venv/bin/ruff check src tests` → passed。
- `PYTHONPATH=src .venv/bin/mypy src` → passed。
- `PYTHONPATH=src .venv/bin/python -m compileall -q src tests` → passed。
- `PYTHONPATH=src .venv/bin/python -m trivae chat --help` → passed；chat parser 保留 database/
  verbose inputs，slash commands 在 interactive loop 内处理，`/help` 可重复显示命令清单。
- `python3 ./.trellis/scripts/task.py validate .trellis/tasks/08-25-product-experience-hardening`
  → passed。

## Local smoke evidence

使用临时 canonical SQLite 导入三条测试消息，Application source inspection 返回同 session 的
`before / anchor / after` 三条 bounded projection并高亮 anchor；readiness 对空 semantic index
返回 `missing`。没有提交聊天正文、`.env`、secret、provider raw payload 或 hidden CoT。

当前真实 `data/trivae.sqlite3`/semantic index 的只读状态已在 planning baseline 记录；本轮没有对
真实 Canonical 数据执行 Query、rebuild 或网络 provider 调用，因此没有虚构 latency/usage/answer
quality smoke 结论。

补充执行了 metadata-only startup smoke：
`printf '0\\n/exit\\n' | PYTHONPATH=src .venv/bin/python -m trivae chat --database data/trivae.sqlite3`
正常退出；显示 database ready（7 sessions、473236 messages）、semantic completed 和
provider `not_configured`。由于当前进程没有足够的 provider 配置，真实 Query smoke 的失败类别为
`provider_not_configured`，没有用 mock 成功替代，也没有发起 Query/provider 请求。

## Boundary evidence

CLI 只调用 `TrivaeApplication` facade；Conversation scope migration 是 additive nullable column；
feedback 是独立 SQLite；live stream 仍由 `QueryStreamAdapter` 提供，Trace Store 不被轮询。
