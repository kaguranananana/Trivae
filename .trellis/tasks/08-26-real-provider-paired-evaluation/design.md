# Technical design: real Provider paired evaluation

## 1. Boundary

本轮的唯一实现面是评测 harness 和评测证据投影。现有 `src/trivae` budget/runtime 链路保持不变；如果新实验只显示“时间不够”或“Provider runtime failure”，runner 记录失败并停止在评测层处理，不改产品行为。只有 completed Trace 中出现已实现契约违反，才进入单独的根因修复。

## 2. Baseline inherited from archive

归档任务中的 4 个 prompt、36-cell 设计和 `fixed-16k` / `dynamic-run-128k` / `dynamic-run-256k` variant 作为基线。本轮保留 prompt、case、scope、repetition 和 Provider 环境，只将第三个 variant 改为不设置 run-level override 的 `dynamic-default-250k`，以验证真实默认路径。

历史 30 秒 harness 的限制是 parent 在单 cell 上杀死隔离 worker，不是回答质量失败。因此新 inventory 把 `cell_timeout`、`experiment_timeout`、`runtime_failed`、`completed` 分开，并只从 `completed` 样本建立质量 paired set。

## 3. Execution flow

```text
parent runner
  ├─ establish absolute experiment deadline
  ├─ for variant/case/repetition: spawn isolated worker with remaining timeout
  │    ├─ load the same provider/env configuration
  │    ├─ Application.query(existing prompt and scope)
  │    ├─ read Trace and call existing operational_measurements/query snapshot
  │    ├─ write bounded answer/source ReviewPacket material outside git
  │    └─ return bounded row (never raw answer text in summary JSONL)
  ├─ mark cells after deadline as experiment_timeout
  ├─ map request_id → Trace ID from SQLite for audit, including open timeout traces
  └─ emit inventory, operational table and human review packet index
```

Worker isolation remains process-based because a timed-out Provider call must not leave the parent event loop or Provider client in an unknown state. The parent passes the smaller of the per-cell timeout and remaining experiment time to `subprocess.run`; no retry is added.

## 4. Time limits

- Default per-cell limit: 120 seconds. This is four times the old 30-second harness limit and covers the previously completed 20–28 second samples while still bounding a stuck Provider call.
- Default experiment deadline: 75 minutes. The maximum nominal runtime of 36 cells at 120 seconds is 72 minutes; the extra margin covers process startup and Trace reads while keeping the run finite.
- Both values are overrideable only for controlled local experiments through explicit CLI flags/env, and the effective values are emitted in the report. The committed validation uses the defaults unless the real Provider environment requires a documented change.

## 5. Variant configuration

All variants keep the archived per-call settings (`TRIVAE_TOOL_RESULT_BUDGET_PERCENT=0.125`, cap `128000`) and 1M context registry verification. The runner changes only:

| Variant | Mode | Run-level env | Expected run pool |
| --- | --- | --- | --- |
| `fixed-16k` | `fixed` | unset | not applicable |
| `dynamic-run-128k` | `dynamic` | `TRIVAE_RUN_TOOL_EVIDENCE_BUDGET=128000` | 128k |
| `dynamic-default-250k` | `dynamic` | unset | 250k from current 1M default |

Before the run, the runner verifies the resolved budget facts from Trace rather than trusting the variant label.

## 6. Trace/Evaluation projection

The runner uses the existing `operational_measurements(result, trace)` and `query_result_snapshot(result)` functions. It additionally derives only bounded counts needed for the requested chain:

- Retriever: sum/retain each `retrieval.search.completed` event's `total_hits`, `candidate_count`, `returned_messages`, `partial`, `truncated`, coverage and latency.
- Canonical: count `ToolResultRecord.message_items` and `structured_items` from the returned `QueryResult`.
- Model projection: for each `runtime.tool.completed` call, subtract the Trace-recorded `omitted_context_messages` and `omitted_hit_messages` from canonical message count; structured items remain visible. This is a projection of existing runtime facts, not a second budget calculation.
- Omission/truncation: preserve the existing budget snapshot and retrieval flags; do not infer omission from missing text.
- Calls/rounds, latency, usage, citations and finalization: reuse Trace and `operational_measurements`. A runtime failure has finalization state `not_run`, even if a default result field happens to contain `valid`.

The summary row contains identifiers and bounded metrics only. Raw `answer_text` and bounded source snapshots are written to a local quality-material directory ignored by git, through the existing `ReviewPacket` shape, so a human can audit claims without putting provider responses in the committed operational report.

## 7. Quality review

No automatic quality score is introduced. For completed samples, the report groups the local ReviewPacket materials by `(case_id, repetition)` and records human-review columns:

- enumeration completeness: `complete` / `partial` / `unknown` against the evidence visible in the paired packet;
- evidence coverage: `complete` / `partial` / `unknown` based on actual citation bindings and source support;
- obvious omission: `none` / `observed` / `unknown`, only when a relevant retrieved/canonical item is visibly absent.

If a case has no completed pair or the packet cannot establish an exhaustive reference universe, the conclusion is `unknown`; operational projection gains are reported separately and are not converted into quality gains.

## 8. Failure and rollback

Timeout and runtime failure rows are retained with request IDs and, where available, Trace IDs. The parent must not synthesize an answer, retry the cell, or classify an incomplete run as a quality sample. Since this change is isolated to task-local evaluation code/docs, rollback is deleting the task-local runner changes; no production migration is required.
