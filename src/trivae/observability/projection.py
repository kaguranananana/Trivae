"""Trace 与 Import diagnostics 的确定性只读投影。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Mapping

from trivae.observability.contracts import (
    ImportDiagnosticsProjection,
    StoredTrace,
    TraceFailure,
    TraceMetrics,
    TraceProjection,
    TraceTimelineItem,
)

_TERMINAL_OPERATIONS = {
    "query.completed": "completed",
    "query.failed": "failed",
    "query.aborted": "aborted",
}


def project_trace(stored: StoredTrace) -> TraceProjection:
    """从 ordered event history 派生 summary，绝不依赖 terminal summary columns。"""

    timeline = tuple(
        TraceTimelineItem(
            sequence=event.sequence,
            stage=event.stage,
            operation=event.operation,
            phase=event.phase,
            operation_id=event.operation_id,
            parent_operation_id=event.parent_operation_id,
            outcome=event.outcome,
            duration_ms=event.duration_ms,
            limitations=event.limitations,
            payload=dict(event.payload),
        )
        for event in stored.events
    )
    failures = tuple(
        TraceFailure(
            sequence=event.sequence,
            event_id=event.event_id,
            operation=event.operation,
            failure=event.failure,
        )
        for event in stored.events
        if event.failure is not None
    )
    terminal_status = "incomplete"
    terminal_sequence: int | None = None
    for event in stored.events:
        if event.stage != "query":
            continue
        status = _TERMINAL_OPERATIONS.get(event.operation)
        if status is not None:
            terminal_status = status
            terminal_sequence = event.sequence
    collector_degraded = any(
        limitation == "trace_collector_degraded"
        for event in stored.events
        for limitation in event.limitations
    )
    completeness: Literal["complete", "incomplete", "collector_degraded"]
    if terminal_status != "incomplete" and collector_degraded:
        completeness = "collector_degraded"
    elif terminal_status == "incomplete":
        completeness = "collector_degraded" if collector_degraded else "incomplete"
    else:
        completeness = "complete"

    metrics = _build_metrics(stored)
    # terminal_sequence 只用于强调 terminal 是事件历史推导的，防止未来误用 metadata 列。
    _ = terminal_sequence
    return TraceProjection(
        trace_id=stored.trace_id,
        request_id=stored.request_id,
        profile=stored.profile,
        started_at=stored.started_at,
        terminal_at=stored.terminal_at,
        terminal_status=terminal_status,
        completeness=completeness,
        timeline=timeline,
        failures=failures,
        metrics=metrics,
    )


def _build_metrics(stored: StoredTrace) -> TraceMetrics:
    """从 event payload 聚合 latency/provider/usage 等 operational facts。"""

    stage_durations: dict[str, float] = {}
    providers: set[str] = set()
    models: set[str] = set()
    usage: dict[str, int | float] = {}
    tool_count = 0
    retrieval_count = 0
    tool_result_estimated_tokens: int | Literal["unavailable"] = "unavailable"
    tool_result_projection_truncated_count = 0
    tool_result_projection_omitted_context_messages = 0
    tool_result_projection_omitted_hit_messages = 0

    for event in stored.events:
        if event.duration_ms is not None:
            stage_durations[event.stage] = stage_durations.get(event.stage, 0.0) + event.duration_ms
        provider = event.payload.get("provider")
        if isinstance(provider, str) and provider:
            providers.add(provider)
        model = event.payload.get("model")
        if isinstance(model, str) and model:
            models.add(model)
        raw_usage = event.payload.get("usage")
        if isinstance(raw_usage, Mapping):
            for key, value in raw_usage.items():
                if isinstance(key, str) and isinstance(value, (int, float)) and not isinstance(value, bool):
                    usage[key] = usage.get(key, 0) + value
        # 只有公开的 tool.call terminal event 代表一次 Agent tool round；
        # capability 内部的 member.lookup/context.expansion event 不能重复计数。
        if event.operation in {"tool.call.completed", "tool.call.failed"}:
            tool_count += 1
        if event.stage == "retrieval" and event.phase in {"completed", "failed"}:
            retrieval_count += 1
        if event.operation == "runtime.run" and event.phase in {"completed", "failed", "aborted"}:
            raw_estimated_tokens = event.payload.get("tool_result_estimated_tokens")
            if isinstance(raw_estimated_tokens, int) and not isinstance(raw_estimated_tokens, bool):
                tool_result_estimated_tokens = raw_estimated_tokens
            elif raw_estimated_tokens == "unavailable":
                tool_result_estimated_tokens = "unavailable"
            raw_truncated_count = event.payload.get("tool_result_projection_truncated_count")
            if isinstance(raw_truncated_count, int) and not isinstance(raw_truncated_count, bool):
                tool_result_projection_truncated_count = raw_truncated_count
            raw_omitted_context = event.payload.get("tool_result_projection_omitted_context_messages")
            if isinstance(raw_omitted_context, int) and not isinstance(raw_omitted_context, bool):
                tool_result_projection_omitted_context_messages = raw_omitted_context
            raw_omitted_hits = event.payload.get("tool_result_projection_omitted_hit_messages")
            if isinstance(raw_omitted_hits, int) and not isinstance(raw_omitted_hits, bool):
                tool_result_projection_omitted_hit_messages = raw_omitted_hits

    total_duration_ms = _duration_between(stored.started_at, stored.terminal_at)
    if total_duration_ms is None:
        # 缺少 terminal 时仍可返回已观测阶段的 operational duration，不猜测总耗时。
        total_duration_ms = None
    return TraceMetrics(
        total_duration_ms=total_duration_ms,
        stage_durations_ms=dict(sorted(stage_durations.items())),
        providers=tuple(sorted(providers)),
        models=tuple(sorted(models)),
        usage=dict(sorted(usage.items())),
        tool_count=tool_count,
        retrieval_count=retrieval_count,
        tool_result_estimated_tokens=tool_result_estimated_tokens,
        tool_result_projection_truncated_count=tool_result_projection_truncated_count,
        tool_result_projection_omitted_context_messages=tool_result_projection_omitted_context_messages,
        tool_result_projection_omitted_hit_messages=tool_result_projection_omitted_hit_messages,
    )


def _duration_between(started_at: str, terminal_at: str | None) -> float | None:
    """仅在两个时间戳都能解析时计算真实 wall-clock duration。"""

    if terminal_at is None:
        return None
    try:
        started = datetime.fromisoformat(started_at)
        terminal = datetime.fromisoformat(terminal_at)
    except ValueError:
        return None
    duration = (terminal - started).total_seconds() * 1000
    return duration if duration >= 0 else None


def project_import_diagnostics(
    projection: ImportDiagnosticsProjection,
) -> ImportDiagnosticsProjection:
    """保持 Import read model 的稳定入口，明确 projection 不重写 ingestion 事实。"""

    return projection
