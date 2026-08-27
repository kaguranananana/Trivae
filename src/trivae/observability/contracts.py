"""Trivae-owned Trace 契约与只读投影。

本模块只保存普通 Python 值，不依赖 OpenAI Agents SDK，也不拥有 SQLite 连接。
这样 Runtime、Trace Store 和未来的其他采集后端都可以围绕同一份契约协作。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Protocol


class TraceContractError(ValueError):
    """Trace 公开契约不合法。"""


TraceProfile = Literal["normal", "debug"]
TraceStage = Literal[
    "context",
    "query",
    "router",
    "planner",
    "runtime",
    "model",
    "tool",
    "retrieval",
    "evidence",
    "citation",
    "answer",
    "conversation",
    "trace",
]
TracePhase = Literal[
    "started",
    "completed",
    "failed",
    "degraded",
    "skipped",
    "aborted",
    "observed",
]
TraceOutcome = Literal["ok", "partial", "error", "aborted"]

_TRACE_STAGES = {
    "context",
    "query",
    "router",
    "planner",
    "runtime",
    "model",
    "tool",
    "retrieval",
    "evidence",
    "citation",
    "answer",
    "conversation",
    "trace",
}
_TRACE_PHASES = {"started", "completed", "failed", "degraded", "skipped", "aborted", "observed"}
_TRACE_OUTCOMES = {"ok", "partial", "error", "aborted"}


def _require_text(value: object, field_name: str) -> str:
    """统一校验 identity 和枚举文本，避免每个数据类重复隐式转换。"""

    if not isinstance(value, str) or not value.strip():
        raise TraceContractError(f"{field_name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class FailureInfo:
    """一次失败的根因归属、观察层和处理方式。"""

    error_code: str
    origin_stage: TraceStage
    observed_stage: TraceStage
    category: str
    handling: str
    cause_event_id: str | None = None
    cause_operation_id: str | None = None
    retry_count: int | None = None
    diagnostic_reference: str | None = None

    def __post_init__(self) -> None:
        """拒绝空错误码和负重试次数，确保失败投影能被稳定消费。"""

        object.__setattr__(self, "error_code", _require_text(self.error_code, "error_code"))
        object.__setattr__(self, "category", _require_text(self.category, "category"))
        object.__setattr__(self, "handling", _require_text(self.handling, "handling"))
        if self.origin_stage not in _TRACE_STAGES or self.observed_stage not in _TRACE_STAGES:
            raise TraceContractError("FailureInfo stage is not supported")
        if self.retry_count is not None:
            if isinstance(self.retry_count, bool) or not isinstance(self.retry_count, int):
                raise TraceContractError("retry_count must be an integer when provided")
            if self.retry_count < 0:
                raise TraceContractError("retry_count must not be negative")
        for field_name in ("cause_event_id", "cause_operation_id", "diagnostic_reference"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, _require_text(value, field_name))

    def to_dict(self) -> dict[str, object]:
        """生成 SQLite JSON 所需的普通字典。"""

        return {
            "error_code": self.error_code,
            "origin_stage": self.origin_stage,
            "observed_stage": self.observed_stage,
            "category": self.category,
            "handling": self.handling,
            "cause_event_id": self.cause_event_id,
            "cause_operation_id": self.cause_operation_id,
            "retry_count": self.retry_count,
            "diagnostic_reference": self.diagnostic_reference,
        }


@dataclass(frozen=True)
class NormalizedQueryEvent:
    """单条 append-only Trivae Trace 事实。"""

    schema_version: int
    event_id: str
    trace_id: str
    request_id: str
    sequence: int
    occurred_at: str
    observed_at: str
    stage: TraceStage
    operation: str
    phase: TracePhase
    operation_id: str
    parent_operation_id: str | None = None
    outcome: TraceOutcome | None = None
    duration_ms: float | None = None
    payload: Mapping[str, object] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()
    failure: FailureInfo | None = None

    def __post_init__(self) -> None:
        """在 normalized boundary 校验 identity、sequence 和 payload 类型。"""

        if isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int):
            raise TraceContractError("schema_version must be an integer")
        if self.schema_version <= 0:
            raise TraceContractError("schema_version must be positive")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise TraceContractError("sequence must be an integer")
        if self.sequence <= 0:
            raise TraceContractError("sequence must be positive")
        for field_name in (
            "event_id",
            "trace_id",
            "request_id",
            "occurred_at",
            "observed_at",
            "operation",
            "operation_id",
        ):
            object.__setattr__(self, field_name, _require_text(getattr(self, field_name), field_name))
        if self.parent_operation_id is not None:
            object.__setattr__(
                self,
                "parent_operation_id",
                _require_text(self.parent_operation_id, "parent_operation_id"),
            )
        if self.stage not in _TRACE_STAGES:
            raise TraceContractError(f"stage is not supported: {self.stage!r}")
        if self.phase not in _TRACE_PHASES:
            raise TraceContractError(f"phase is not supported: {self.phase!r}")
        if self.outcome is not None and self.outcome not in _TRACE_OUTCOMES:
            raise TraceContractError(f"outcome is not supported: {self.outcome!r}")
        if not isinstance(self.payload, Mapping):
            raise TraceContractError("payload must be a mapping")
        if not isinstance(self.limitations, tuple):
            raise TraceContractError("limitations must be a tuple")
        if any(not isinstance(value, str) or not value.strip() for value in self.limitations):
            raise TraceContractError("limitations must contain non-empty strings")
        if self.duration_ms is not None:
            if isinstance(self.duration_ms, bool) or not isinstance(self.duration_ms, (int, float)):
                raise TraceContractError("duration_ms must be numeric when provided")
            if self.duration_ms < 0:
                raise TraceContractError("duration_ms must not be negative")

    def to_row(self) -> dict[str, object]:
        """返回 Store 可使用的字段，不让 Store 重新解释业务语义。"""

        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "sequence": self.sequence,
            "occurred_at": self.occurred_at,
            "observed_at": self.observed_at,
            "stage": self.stage,
            "operation": self.operation,
            "phase": self.phase,
            "operation_id": self.operation_id,
            "parent_operation_id": self.parent_operation_id,
            "outcome": self.outcome,
            "duration_ms": self.duration_ms,
            "payload": dict(self.payload),
            "limitations": list(self.limitations),
            "failure": None if self.failure is None else self.failure.to_dict(),
        }


@dataclass(frozen=True)
class StoredTrace:
    """Trace Store 读取出的 metadata 与 canonical ordered events。"""

    trace_id: str
    request_id: str
    profile: TraceProfile
    started_at: str
    terminal_at: str | None
    terminal_outcome: str | None
    events: tuple[NormalizedQueryEvent, ...]


@dataclass(frozen=True)
class TraceTimelineItem:
    """面向诊断 UI/CLI 的轻量时间线行。"""

    sequence: int
    stage: TraceStage
    operation: str
    phase: TracePhase
    operation_id: str
    parent_operation_id: str | None
    outcome: TraceOutcome | None
    duration_ms: float | None
    limitations: tuple[str, ...]
    payload: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TraceFailure:
    """带事件位置的失败归因记录。"""

    sequence: int
    event_id: str
    operation: str
    failure: FailureInfo


@dataclass(frozen=True)
class TraceMetrics:
    """只表达执行事实，不表达回答质量。"""

    total_duration_ms: float | None
    stage_durations_ms: Mapping[str, float]
    providers: tuple[str, ...]
    models: tuple[str, ...]
    usage: Mapping[str, int | float]
    tool_count: int
    retrieval_count: int
    # Tool Result token 仅在 Host projection 可估算时提供；provider 原始 usage 仍单独记录。
    tool_result_estimated_tokens: int | Literal["unavailable"] = "unavailable"
    tool_result_projection_truncated_count: int = 0
    tool_result_projection_omitted_context_messages: int = 0
    tool_result_projection_omitted_hit_messages: int = 0
    tool_result_projection_projected_messages: int = 0
    tool_result_projection_omitted_messages: int = 0


@dataclass(frozen=True)
class TraceProjection:
    """由 canonical events 确定性派生的可回放 Trace。"""

    trace_id: str
    request_id: str
    profile: TraceProfile
    started_at: str
    terminal_at: str | None
    terminal_status: str
    completeness: Literal["complete", "incomplete", "collector_degraded"]
    timeline: tuple[TraceTimelineItem, ...]
    failures: tuple[TraceFailure, ...]
    metrics: TraceMetrics


@dataclass(frozen=True)
class ImportErrorDiagnostic:
    """现有 import_errors 表的一条稳定读取投影。"""

    error_id: int
    error_code: str
    error_message: str
    record_index: int | None
    raw_locator: str | None


@dataclass(frozen=True)
class ImportBatchDiagnostic:
    """现有 import_batches 表与其 errors 的聚合投影。"""

    batch_id: str
    source_file: str
    source_id: str | None
    session_id: str | None
    started_at: str
    finished_at: str | None
    received_count: int
    inserted_count: int
    duplicate_count: int
    conflict_count: int
    error_count: int
    status: str
    error_message: str | None
    errors: tuple[ImportErrorDiagnostic, ...]


@dataclass(frozen=True)
class ImportDiagnosticsProjection:
    """Application facade 返回的 Import diagnostics read model。"""

    source_file: str | None
    batch_id: str | None
    batches: tuple[ImportBatchDiagnostic, ...]


class TraceStore(Protocol):
    """Collector 依赖的最小 Store 端口。"""

    def create_trace(
        self,
        trace_id: str,
        request_id: str,
        profile: TraceProfile,
        started_at: str,
    ) -> None:
        """创建 Trace metadata。"""

    def append_event(self, event: NormalizedQueryEvent) -> None:
        """追加一条不可变 Trace event。"""

    def mark_terminal(self, trace_id: str, terminal_outcome: str, terminal_at: str) -> None:
        """更新 convenience terminal projection。"""

    def read_trace(self, trace_id: str) -> StoredTrace:
        """读取 Trace metadata 和有序事件。"""
