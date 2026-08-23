# M6 Trace / Observability Design

## 1. Boundary and data flow

```text
TrivaeApplication.query()
  ├─ request_id / trace_id / TraceCollector
  ├─ query.received
  ├─ Conversation read + context.prepared
  └─ QueryOrchestrator.run(trace sink)
       ├─ Router / Planner events
       ├─ Traceable AgentRuntime
       │    └─ RuntimeEvent → normalized runtime event
       │         └─ Tool adapter → Tool → Retrieval events
       ├─ Evidence/Citation/Answer finalization events
       └─ return QueryResult(trace_id)
            └─ answer.commit.started → commit_turn()
                 ├─ answer.commit.completed → query.completed
                 └─ answer.commit.failed → query.failed

Normalized Event
  → TraceCollector (identity, sequence, capture, persistence)
  → SQLiteTraceStore (append-only events)
  → TraceProjection (derived replay/metrics)
```

Business components emit facts at their actual boundaries. Collector only validates/normalizes the envelope, allocates event identity and sequence, applies capture policy, and persists; it does not decide route, execute a plan, rank retrieval, validate citations, or recover failures.

## 2. Physical package ownership

新增最小 package：

```text
src/trivae/observability/
  __init__.py       # public contracts/facade exports
  contracts.py      # normalized event, failure, profile, trace/read projection contracts
  collector.py      # per-query collector, RuntimeEvent mapper, capture/redaction boundary
  sqlite.py         # independent Trace SQLite connection and import diagnostic read adapter
  projection.py     # deterministic trace/import derived projections
```

Existing owners remain responsible for their facts:

- `query/runtime/contracts.py` keeps `RuntimeEvent`; it gains only additive safe fields needed to carry Trivae `run_id` and model-visible ordinary-value projection.
- `query/runtime/openai_adapter.py` maps SDK hooks to `RuntimeEvent` and does not import Trace SQLite or SDK types into normalized contracts.
- `query/orchestrator.py` owns Router/Planner/Finalization event timing and failure attribution.
- `capabilities/tools.py` and `query/runtime/openai_tools.py` own Tool Contract mapping; Retrieval remains in `retrieval/` and its existing result/coverage semantics are not changed.
- `bootstrap/application.py` owns request/trace lifecycle, Conversation commit ordering, resource lifecycle and facade methods.
- `data/` keeps ImportBatch/ImportError storage facts; observability only reads and projects them.
- `interfaces/cli.py` only formats Application projections.

## 3. Contract shape

### 3.1 Normalized event

Use frozen dataclasses with explicit `Literal` values for supported stage/phase/outcome/profile. A `NormalizedQueryEvent` contains:

```text
schema_version: int
event_id: str
trace_id: str
request_id: str
sequence: int
occurred_at: str
observed_at: str
stage: context | query | router | planner | runtime | model | tool |
        retrieval | evidence | citation | answer | conversation | trace
operation: stable diagnostic operation name
phase: started | completed | failed | degraded | skipped | aborted | observed
operation_id: str
parent_operation_id: str | None
outcome: ok | partial | error | aborted | None
duration_ms: float | None
payload: Mapping[str, object]
limitations: tuple[str, ...]
failure: FailureInfo | None
```

`event_id` is generated for each event, while operation IDs are stable within the execution so a replay can reconstruct causality. `sequence` is assigned only by the collector. `occurred_at` comes from the emitting boundary; `observed_at` is assigned by the collector. All event payloads are ordinary Python values and are serialized by the Trace package, never as SDK objects.

`FailureInfo` owns `error_code`, `origin_stage`, `observed_stage`, optional cause event/operation references, `category`, `handling`, optional retry count and optional safe diagnostic reference. The error code is propagated from the contract owner; query-level terminal events reference the underlying code rather than replacing it with a generic code.

### 3.2 Profile and capture policy

`TraceProfile = Literal["normal", "debug"]`. A small `CapturePolicy` is selected at collector construction:

- Normal: bounded strings/collections and safe structural facts; query/context/tool/retrieval/final answer content uses a small cap and records `truncated` when clipped.
- Debug: larger, still bounded caps; accepts model-visible context and fuller tool/retrieval/final-answer facts within the trusted run scope.

The collector recursively projects mappings/sequences, redacts allowlisted secret keys (`api_key`, `authorization`, `bearer`, `access_token`, `client_secret`, provider credential names and `.env` secret names), and clips strings/collections. Values that cannot be projected are rejected with a visible `TRACE.PAYLOAD_INVALID` collector diagnostic rather than silently serializing arbitrary objects. Runtime `content_delta` events are intentionally not persisted. Hidden reasoning is never a normalized payload field.

### 3.3 Trace summary/projection

`TraceProjection` is derived from a `TraceRecord` plus ordered events and exposes:

```text
trace_id, request_id, profile
started_at, terminal_at, terminal_status
completeness: complete | incomplete | collector_degraded
timeline: ordered event summaries with sequence/stage/operation/phase/outcome
failures: origin/observed/handling/error_code records
metrics: total/stage latency, model/provider, token usage, tool count, retrieval count
```

Terminal status is taken only from `query` terminal events. If none exists, it is `incomplete`, regardless of runtime or wall-clock data. A collector warning can make completeness `collector_degraded` without turning a successful business result into a failed Query.

## 4. SQLite schema and connection ownership

`SQLiteTraceStore` opens its own connection to the same database path used by Canonical/Conversation stores. It creates only these tables and indexes:

```sql
CREATE TABLE traces (
    trace_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    profile TEXT NOT NULL CHECK (profile IN ('normal', 'debug')),
    started_at TEXT NOT NULL,
    terminal_at TEXT,
    terminal_outcome TEXT
);

CREATE TABLE trace_events (
    event_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    occurred_at TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    stage TEXT NOT NULL,
    operation TEXT NOT NULL,
    phase TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    parent_operation_id TEXT,
    outcome TEXT,
    duration_ms REAL,
    payload_json TEXT NOT NULL,
    limitations_json TEXT NOT NULL,
    failure_json TEXT,
    FOREIGN KEY(trace_id) REFERENCES traces(trace_id),
    UNIQUE(trace_id, sequence)
);

CREATE INDEX idx_trace_events_trace_sequence
    ON trace_events(trace_id, sequence);
CREATE INDEX idx_trace_events_trace_operation
    ON trace_events(trace_id, operation_id);
CREATE INDEX idx_traces_request
    ON traces(request_id, started_at);
```

`trace_events` is the canonical persisted fact history. Its rows are inserted only; later lifecycle facts are new rows. `traces.terminal_*` is a convenience metadata projection updated after a terminal event, never a replacement for or mutation of an event row. Projection can always rebuild terminal state from `trace_events`.

The import diagnostic reader uses a separate read connection and selects existing `import_batches` and `import_errors`; it does not create a second import fact table and does not make ImportBatch a RuntimeEvent.

## 5. Instrumentation details

### Application

At ingress, normalize the provided `request_id` or generate a Trivae-owned ID. Always generate a new `trace_id` for the call, create a collector and emit `query.received`. Emit `context.prepared` after Conversation history has been loaded/compiled. The request's `trace_profile` is trusted Application input, not a future wire-level privilege.

The Application passes the collector to the Orchestrator and wraps the Runtime in a `TraceableAgentRuntime` at composition time or per query. `QueryResult.trace_id` is set for all returned results. Runtime/finalizer failures remain the existing non-success `QueryResult` behavior. A Conversation commit exception remains explicit (not converted into a false success) after emitting `answer.commit.failed` and `query.failed`; the exception carries or is accompanied by the trace identity through the Application diagnostic boundary.

### Router and Planner

The Orchestrator emits `router.started` before `route()`, then `router.decision` with the bounded `RouteDecision`. If `decision.degraded`, it also appends a `router.degraded` event with the original degradation code; the final decision remains present. Planner emits `planner.started`; a usable plan emits `planner.completed` with title/version/intent/step and criterion counts plus a bounded plan projection. A `PlannerResult` with failure emits `planner.failed` and `planner.skipped`/`executed_without_plan` facts while the existing runtime fallback continues. No planner step state machine is added.

### Runtime and SDK boundary

`TraceableAgentRuntime` calls the underlying `stream()` when available, maps every non-delta `RuntimeEvent`, and returns the same terminal `RuntimeResult`; for minimal injected runtimes that expose only `run()`, it emits synthesized runtime start/terminal boundaries without changing runtime behavior. The mapper maps run/turn/tool/usage/finalizing/completed/failed/aborted families. It ignores `content_delta` for persistent Trace.

`RuntimeEvent` receives additive `run_id` and safe model-visible context fields. The OpenAI adapter creates a fresh local `run_id` independent of `request_id`, includes it in all events, and projects only ordinary model input values at turn boundaries. It keeps SDK raw event types local and keeps external SDK tracing disabled.

### Tool and Retrieval causality

The per-run trace context is carried through local RuntimeContext only. The SDK tool adapter passes it to the registered Tool through an additive optional trace hook; existing third-party/test Tool handlers that do not implement the hook keep their original two-argument `invoke()` contract.

The built-in SearchMessages Tool emits a Tool execution event and a child Retrieval operation. Retrieval success records existing strategy/query/filters/result counts/candidate IDs/ranks/coverage/partial/truncated/expansion facts; known retrieval exceptions produce `origin_stage=retrieval, observed_stage=tool, handling=returned_to_agent`. Capability/input errors remain Tool-origin failures. Tool Contract Error remains a Tool Result and does not automatically fail Runtime.

### Evidence, Citation and commit

The Orchestrator emits an evidence/finalization start before `finalize_answer()`. Success emits selected bounded evidence/source identities, citation validation completed, and answer finalization completed. `AnswerFinalizationError` emits citation validation failed and answer finalization failed with its owned code and unresolved/path diagnostics; no source is deleted or repaired.

The Application emits `answer.commit.started` only after a validated artifact exists. It emits `answer.commit.completed` after `commit_turn()` returns, then emits `query.completed`. Commit exceptions emit `answer.commit.failed` and `query.failed`; no `query.completed` event is written.

## 6. Collector failure contract

`TraceCollector.emit()` catches only failures from Trace Store/capture persistence, marks the collector degraded, reports a safe `TRACE.*` operational error through the standard Python logger, and returns control to the business caller. It does not catch Router/Planner/Runtime/Retrieval/Citation/Conversation exceptions. The collector exposes a warning/completeness property for tests and Application health diagnostics. There is no `except Exception: pass` path and no business fallback hidden by the collector.

## 7. Import diagnostic projection

The projection joins `import_batches` to `import_errors` and returns a stable read model:

```text
ImportDiagnosticsProjection
  └─ batches[
       batch_id, source_file, session_id,
       received/inserted/duplicate/conflict/error counts,
       status, error_message,
       errors[error_code, record_index, raw_locator, detail]
     ]
```

It reuses the existing M1 facts and preserves source file/record locator; it does not replay ingestion or alter import status.

## 8. Trade-offs and non-goals

- SQLite is selected for the M6 local-first implementation because the project already owns the database path and needs close/reopen tests; the normalized event contract remains backend-independent.
- A small per-query wrapper/callback boundary is preferred over changing all Tool handlers or introducing an event bus/workflow layer. The fallback for run-only injected runtimes is a testability adapter, not a hidden business fallback; the real SDK runtime still maps its existing RuntimeEvent stream.
- Projection is computed on read to avoid a second source of truth. Trace summary terminal columns are only an index-like convenience.
- No OpenTelemetry/LangSmith/Langfuse, no vector retrieval, no quality judgment, no token-by-token persistence, no HTTP/UI.

## 9. Compatibility and rollback

All existing contracts are extended additively: `QueryResult.trace_id` and `QueryRequest.trace_profile` have defaults/optional behavior; `RuntimeEvent` context fields are optional; Tool tracing hooks are optional. If a runtime/tool integration exposes an actual contract conflict, stop and record the evidence rather than adding a silent compatibility branch. The rollback point is the last M5b commit: remove the observability package and Application wiring while leaving Canonical, Retrieval, Runtime, Evidence and Conversation schemas untouched.
