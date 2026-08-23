"""把安全投影后的 Trace 事件保存为可直接阅读的纯文本日志。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from trivae.observability.contracts import NormalizedQueryEvent, StoredTrace
from trivae.observability.transcript import format_execution_transcript, format_trace_summary

TraceTextView = Literal["transcript", "raw"]


class TraceTextLogError(RuntimeError):
    """Trace 文本日志生成或写入失败。"""


class TraceTextLogWriter:
    """拥有 Trace 日志目录并负责增量写入与完整重导出。"""

    def __init__(self, directory: Path) -> None:
        # 目录只保存 Trace 的 derived 文本 projection，SQLite 仍是事实来源。
        self.directory = directory

    def log_path(self, trace_id: str) -> Path:
        """返回 Trace 默认日志路径，并拒绝把 identity 当成目录片段。"""

        if not isinstance(trace_id, str) or not trace_id.strip():
            raise TraceTextLogError("trace_id must be a non-empty string")
        normalized = trace_id.strip()
        # 默认文件名来自数据库 identity，不能允许路径分隔符改变输出目录。
        if Path(normalized).name != normalized or normalized in {".", ".."}:
            raise TraceTextLogError("trace_id cannot contain a path separator")
        return self.directory / f"{normalized}.log"

    def create_trace(
        self,
        trace_id: str,
        request_id: str,
        profile: str,
        started_at: str,
    ) -> None:
        """创建日志头；使用 exclusive create 避免静默覆盖旧 projection。"""

        path = self.log_path(trace_id)
        content = "\n".join(
            (
                "Trivae Trace Log",
                "================",
                f"trace_id: {trace_id}",
                f"request_id: {request_id}",
                f"profile: {profile}",
                f"started_at: {started_at}",
                "terminal_at: -",
                "terminal_outcome: -",
                "",
            )
        )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as handle:
                handle.write(content)
        except OSError as exc:
            raise TraceTextLogError(f"trace text log creation failed: {path}") from exc

    def append_event(self, event: NormalizedQueryEvent) -> None:
        """追加一条已经经过 CapturePolicy 的 normalized event。"""

        path = self.log_path(event.trace_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(_format_event(event))
        except (OSError, TypeError, ValueError) as exc:
            raise TraceTextLogError(f"trace text log event append failed: {path}") from exc

    def append_terminal(self, trace_id: str, terminal_outcome: str, terminal_at: str) -> None:
        """追加 terminal projection，便于用户直接阅读 Trace 是否结束。"""

        path = self.log_path(trace_id)
        content = "\n".join(
            (
                "",
                "[terminal]",
                f"terminal_at: {terminal_at}",
                f"terminal_outcome: {terminal_outcome}",
                "",
            )
        )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(content)
        except OSError as exc:
            raise TraceTextLogError(f"trace text log terminal append failed: {path}") from exc

    def export(
        self,
        trace: StoredTrace,
        *,
        output_path: Path | None = None,
        view: TraceTextView = "transcript",
        context_mode: Literal["delta", "full"] = "delta",
    ) -> Path:
        """从完整 StoredTrace 重建文本文件，并返回可直接定位的绝对路径。"""

        target = self.log_path(trace.trace_id) if output_path is None else output_path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                format_trace_text(trace, view=view, context_mode=context_mode),
                encoding="utf-8",
            )
        except (OSError, TypeError, ValueError) as exc:
            raise TraceTextLogError(f"trace text log export failed: {target}") from exc
        return target.resolve()


def format_trace_text(
    trace: StoredTrace,
    *,
    view: TraceTextView = "transcript",
    context_mode: Literal["delta", "full"] = "delta",
) -> str:
    """从同一 StoredTrace 生成 transcript 或显式 raw 文本视图。"""

    if view not in {"transcript", "raw"}:
        raise ValueError(f"unsupported trace text view: {view!r}")
    if context_mode not in {"delta", "full"}:
        raise ValueError(f"unsupported transcript context mode: {context_mode!r}")
    if view == "raw" and context_mode != "delta":
        # Raw projection 没有 model turn context；显式拒绝无效组合，避免用户误以为参数生效。
        raise ValueError("--context applies only to the transcript view")

    lines = [
        "Trivae Trace Log",
        "================",
        "Trace Metadata",
        f"trace_id: {trace.trace_id}",
        f"request_id: {trace.request_id}",
        f"profile: {trace.profile}",
        f"started_at: {trace.started_at}",
        f"terminal_at: {trace.terminal_at or '-'}",
        f"terminal_outcome: {trace.terminal_outcome or '-'}",
        f"event_count: {len(trace.events)}",
        "",
    ]
    if view == "transcript":
        # 默认日志只保留人工排障主线；canonical raw events 仍在 SQLite 中。
        lines.extend(
            (
                format_trace_summary(trace).rstrip(),
                "",
                format_execution_transcript(trace, context_mode=context_mode).rstrip(),
            )
        )
    else:
        # raw 是显式的工程诊断视图，不与默认 Transcript 混合，避免重复复制大 payload。
        lines.extend(("=================", "RAW TRACE EVENTS", "================="))
        for event in trace.events:
            lines.extend(("", *_format_event_lines(event)))
    return "\n".join(lines) + "\n"


def _format_event(event: NormalizedQueryEvent) -> str:
    """渲染增量 event，并保留与完整导出相同的字段顺序。"""

    return "\n".join(("", *_format_event_lines(event))) + "\n"


def _format_event_lines(event: NormalizedQueryEvent) -> list[str]:
    """把单条 normalized event 展开为易读的 key/value 文本块。"""

    failure = None if event.failure is None else event.failure.to_dict()
    return [
        f"[event {event.sequence}] {event.occurred_at}",
        f"event_id: {event.event_id}",
        f"stage: {event.stage}",
        f"operation: {event.operation}",
        f"phase: {event.phase}",
        f"operation_id: {event.operation_id}",
        f"parent_operation_id: {event.parent_operation_id or '-'}",
        f"outcome: {event.outcome or '-'}",
        f"duration_ms: {event.duration_ms if event.duration_ms is not None else '-'}",
        f"limitations: {', '.join(event.limitations) if event.limitations else '-'}",
        "payload:",
        _json_text(dict(event.payload), indent=2),
        "failure:",
        _json_text(failure, indent=2) if failure is not None else "-",
    ]


def _json_text(value: object, *, indent: int) -> str:
    """把安全 payload 编码成 UTF-8 文本，序列化失败时显式报告。"""

    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent)
    except (TypeError, ValueError) as exc:
        raise TraceTextLogError("trace payload cannot be rendered as text") from exc
