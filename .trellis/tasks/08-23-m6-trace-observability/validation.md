# M6 Trace / Observability Validation

## Measured facts

- 项目环境：`.venv` 中的 Python 3.14、pytest、ruff、mypy 可用；系统 Python 没有 pytest，测试命令因此显式使用 `.venv/bin` 和 `PYTHONPATH=src`。
- `PYTHONPATH=src ./.venv/bin/pytest -q`：131 passed。
- `PYTHONPATH=src ./.venv/bin/pytest -q tests/test_observability.py`：10 passed。
- `./.venv/bin/ruff check src tests`：passed。
- `./.venv/bin/mypy`：passed，47 source files。
- Temporary SQLite close/reopen smoke：Trace metadata、ordered events、terminal projection 和 Application `read_trace()` 均可恢复。
- Real-data copy smoke：从一个真实 QQ export 复制到 temporary raw directory，导入 73,014 条消息后完成 Query；安全输出为 14 events、sequence 1–14、terminal=`completed`、completeness=`complete`、tool/retrieval count=0；没有修改仓库内 canonical database。
- Trace Store failure smoke：业务 Query 仍返回成功，collector 产生 `TRACE.*` error log；没有把 Store exception 伪装成业务失败。
- 本轮没有调用真实 DeepSeek Provider；测试不依赖网络，也没有读取或打印 key。

## Regression cases

| Case | Root cause / owner | Trace evidence | Protection |
| --- | --- | --- | --- |
| Router optional completion degraded | Router | `router.degraded`，保留 `ROUTER_*` code，handling=`static_route_retained` | `test_router_degradation_and_planner_failure_keep_ownership` |
| Planner failure with runtime continuation | Planner | `planner.failed` + `planner.skipped`，limitation=`executed_without_plan` | 同上 |
| Tool Contract Error | Tool contract boundary | tool-owned failure，`returned_to_agent`；retrieval 以 skipped 结尾 | capability and observability tests |
| Retrieval invalid/unavailable/partial | Retrieval observed by Tool | `retrieval.search.failed/completed`，保留 result partial/truncated/coverage | `test_tool_retrieval_parent_child_and_import_projection` + existing capability tests |
| Citation/provenance failure | Citation/Answer finalization | `citation.validation.failed`、`answer.finalization.failed`、`query.failed`，不 commit | existing evidence/conversation tests + Query trace path |
| Conversation commit failure | Conversation Store | `answer.commit.failed` → `query.failed`，没有 `query.completed` | `test_conversation_commit_failure_has_trace_without_query_completed` |
| Abort / budget terminal | Runtime | runtime terminal 与 query aborted/failed 分开，budget limitation 不伪装 completion | existing runtime/conversation tests |
| Missing terminal event | Collector/stream boundary | projection terminal=`incomplete`，不猜测 completed/failed | `test_trace_store_append_only_and_reopen_projection` |
| Trace Store failure | Trace ownership | safe `TRACE.*` log，业务结果保持原语义 | `test_trace_store_failure_does_not_control_business` |
| Normal/Debug privacy | Capture boundary | bounded strings/collections、credential redaction、hidden reasoning redaction、visible limitations | `test_capture_profiles_bound_redact_and_block_hidden_reasoning` |

## Anticipated risks

- SQLite append 采用每 event 独立提交，极端高频 Trace 会增加写放大；M6 保持 local-first 简单实现，若真实容量测量证明不够，再按 ADR Reopen 条件讨论 batch/queue。
- Trace Store 与 Conversation Store 不组成分布式事务，因此 crash 仍可能留下 incomplete Trace；这是显式 projection 状态，不会被猜测为成功。
- M5 历史模型输出可能把 request_id 嵌入 tool locator。M6 保持独立 fresh `run_id`，仅对同一 request_id 的旧 locator 做明确前缀映射，避免破坏既有 validated provenance regression。
- Debug payload 上限比 Normal 更大，但仍受 capture boundary、Data Access Scope、credential redaction 和 hidden reasoning redaction 约束；本阶段未引入 retention scheduler。

## Smoke commands

```bash
PYTHONPATH=src ./.venv/bin/pytest -q
./.venv/bin/ruff check src tests
./.venv/bin/mypy
```
