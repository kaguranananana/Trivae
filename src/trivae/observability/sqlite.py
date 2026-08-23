"""Trace Store 与 Import diagnostics 的 SQLite 读写边界。"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Mapping, cast

from trivae.observability.contracts import (
    FailureInfo,
    ImportBatchDiagnostic,
    ImportDiagnosticsProjection,
    ImportErrorDiagnostic,
    NormalizedQueryEvent,
    StoredTrace,
    TraceContractError,
    TraceOutcome,
    TracePhase,
    TraceProfile,
    TraceStage,
    TraceStore,
)


class TraceStoreError(RuntimeError):
    """Trace SQLite 读写失败；Collector 会把它作为显式 TRACE diagnostic。"""


class ImportDiagnosticsError(RuntimeError):
    """Import diagnostics 读取失败。"""


TRACE_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    profile TEXT NOT NULL CHECK (profile IN ('normal', 'debug')),
    started_at TEXT NOT NULL,
    terminal_at TEXT,
    terminal_outcome TEXT
);

CREATE TABLE IF NOT EXISTS trace_events (
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

CREATE INDEX IF NOT EXISTS idx_trace_events_trace_sequence
    ON trace_events(trace_id, sequence);
CREATE INDEX IF NOT EXISTS idx_trace_events_trace_operation
    ON trace_events(trace_id, operation_id);
CREATE INDEX IF NOT EXISTS idx_traces_request
    ON traces(request_id, started_at);
"""


def _json_dumps(value: object) -> str:
    """统一 JSON 编码，确保 projection 在重启后不会受字典顺序影响。"""

    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise TraceStoreError("trace payload is not JSON serializable") from exc


def _json_loads(value: str, field_name: str) -> object:
    """统一 JSON 解码并对损坏的 append-only row 显式报错。"""

    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TraceStoreError(f"invalid JSON in trace field: {field_name}") from exc


def _row_text(row: sqlite3.Row, field_name: str) -> str:
    """从 SQLite row 读取必需文本，避免损坏数据悄悄变成 None。"""

    value = row[field_name]
    if not isinstance(value, str) or not value:
        raise TraceStoreError(f"trace row field is invalid: {field_name}")
    return value


def _failure_from_json(value: object) -> FailureInfo | None:
    """把 failure JSON 恢复为领域对象，保留归因字段而不是只还原文案。"""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TraceStoreError("trace failure JSON must be an object")
    try:
        return FailureInfo(
            error_code=cast(str, value["error_code"]),
            origin_stage=cast(TraceStage, value["origin_stage"]),
            observed_stage=cast(TraceStage, value["observed_stage"]),
            category=cast(str, value["category"]),
            handling=cast(str, value["handling"]),
            cause_event_id=cast(str | None, value.get("cause_event_id")),
            cause_operation_id=cast(str | None, value.get("cause_operation_id")),
            retry_count=cast(int | None, value.get("retry_count")),
            diagnostic_reference=cast(str | None, value.get("diagnostic_reference")),
        )
    except (KeyError, TypeError, TraceContractError) as exc:
        raise TraceStoreError("trace failure JSON does not match FailureInfo") from exc


class SQLiteTraceStore(TraceStore):
    """拥有独立 SQLite connection 的 append-only Trace Store。"""

    def __init__(self, database_path: Path) -> None:
        # Trace 连接独立于 Canonical、Retrieval read 和 Conversation connection。
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = database_path
        self.connection = sqlite3.connect(str(database_path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(TRACE_SCHEMA_SQL)
        self.connection.commit()
        self._closed = False

    def create_trace(
        self,
        trace_id: str,
        request_id: str,
        profile: TraceProfile,
        started_at: str,
    ) -> None:
        """创建 Trace metadata；同一 trace identity 不允许静默复用。"""

        self._ensure_open()
        try:
            self.connection.execute(
                """
                INSERT INTO traces(trace_id, request_id, profile, started_at)
                VALUES (?, ?, ?, ?)
                """,
                (trace_id, request_id, profile, started_at),
            )
            self.connection.commit()
        except sqlite3.Error as exc:
            self.connection.rollback()
            raise TraceStoreError("trace metadata creation failed") from exc

    def append_event(self, event: NormalizedQueryEvent) -> None:
        """只 INSERT event row，不更新或覆盖已有事实。"""

        self._ensure_open()
        row = event.to_row()
        try:
            self.connection.execute(
                """
                INSERT INTO trace_events(
                    event_id, trace_id, sequence, schema_version, occurred_at, observed_at,
                    stage, operation, phase, operation_id, parent_operation_id, outcome,
                    duration_ms, payload_json, limitations_json, failure_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["event_id"],
                    row["trace_id"],
                    row["sequence"],
                    row["schema_version"],
                    row["occurred_at"],
                    row["observed_at"],
                    row["stage"],
                    row["operation"],
                    row["phase"],
                    row["operation_id"],
                    row["parent_operation_id"],
                    row["outcome"],
                    row["duration_ms"],
                    _json_dumps(row["payload"]),
                    _json_dumps(row["limitations"]),
                    None if row["failure"] is None else _json_dumps(row["failure"]),
                ),
            )
            self.connection.commit()
        except sqlite3.Error as exc:
            self.connection.rollback()
            raise TraceStoreError("trace event append failed") from exc

    def mark_terminal(self, trace_id: str, terminal_outcome: str, terminal_at: str) -> None:
        """更新 trace summary convenience columns，不修改任何 event row。"""

        self._ensure_open()
        try:
            cursor = self.connection.execute(
                """
                UPDATE traces
                SET terminal_at = ?, terminal_outcome = ?
                WHERE trace_id = ?
                """,
                (terminal_at, terminal_outcome, trace_id),
            )
            if cursor.rowcount != 1:
                raise TraceStoreError(f"trace not found while marking terminal: {trace_id}")
            self.connection.commit()
        except TraceStoreError:
            self.connection.rollback()
            raise
        except sqlite3.Error as exc:
            self.connection.rollback()
            raise TraceStoreError("trace terminal projection update failed") from exc

    def read_trace(self, trace_id: str) -> StoredTrace:
        """按 sequence 读取 metadata 与 canonical event history。"""

        self._ensure_open()
        try:
            trace_row = self.connection.execute(
                """
                SELECT trace_id, request_id, profile, started_at, terminal_at, terminal_outcome
                FROM traces
                WHERE trace_id = ?
                """,
                (trace_id,),
            ).fetchone()
            if trace_row is None:
                raise TraceStoreError(f"trace not found: {trace_id}")
            event_rows = self.connection.execute(
                """
                SELECT event_id, trace_id, sequence, schema_version, occurred_at, observed_at,
                       stage, operation, phase, operation_id, parent_operation_id, outcome,
                       duration_ms, payload_json, limitations_json, failure_json
                FROM trace_events
                WHERE trace_id = ?
                ORDER BY sequence ASC
                """,
                (trace_id,),
            ).fetchall()
        except TraceStoreError:
            raise
        except sqlite3.Error as exc:
            raise TraceStoreError("trace read failed") from exc

        profile = trace_row["profile"]
        if profile not in ("normal", "debug"):
            raise TraceStoreError("trace row contains an invalid profile")
        events = tuple(
            self._event_from_row(row, request_id=trace_row["request_id"])
            for row in event_rows
        )
        return StoredTrace(
            trace_id=_row_text(trace_row, "trace_id"),
            request_id=_row_text(trace_row, "request_id"),
            profile=cast(TraceProfile, profile),
            started_at=_row_text(trace_row, "started_at"),
            terminal_at=trace_row["terminal_at"],
            terminal_outcome=trace_row["terminal_outcome"],
            events=events,
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row, *, request_id: str) -> NormalizedQueryEvent:
        """将持久化 row 恢复为 normalized event；字段损坏时直接失败。"""

        payload = _json_loads(row["payload_json"], "payload_json")
        limitations = _json_loads(row["limitations_json"], "limitations_json")
        failure_value = None
        if row["failure_json"] is not None:
            failure_value = _json_loads(row["failure_json"], "failure_json")
        if not isinstance(payload, Mapping) or not isinstance(limitations, list):
            raise TraceStoreError("trace event JSON shape is invalid")
        try:
            return NormalizedQueryEvent(
                schema_version=row["schema_version"],
                event_id=_row_text(row, "event_id"),
                trace_id=_row_text(row, "trace_id"),
                request_id=request_id,
                sequence=row["sequence"],
                occurred_at=_row_text(row, "occurred_at"),
                observed_at=_row_text(row, "observed_at"),
                stage=cast(TraceStage, _row_text(row, "stage")),
                operation=_row_text(row, "operation"),
                phase=cast(TracePhase, _row_text(row, "phase")),
                operation_id=_row_text(row, "operation_id"),
                parent_operation_id=row["parent_operation_id"],
                outcome=cast(TraceOutcome | None, row["outcome"]),
                duration_ms=row["duration_ms"],
                payload=payload,
                limitations=tuple(limitations),
                failure=_failure_from_json(failure_value),
            )
        except (TypeError, TraceContractError) as exc:
            raise TraceStoreError("trace event row does not match normalized contract") from exc

    def close(self) -> None:
        """关闭 Trace connection；生命周期由 Application 统一管理。"""

        if self._closed:
            return
        self._closed = True
        self.connection.close()

    def _ensure_open(self) -> None:
        """拒绝在 close 后隐式重建连接，保持 lifecycle 错误透明。"""

        if self._closed:
            raise TraceStoreError("trace store is closed")


class SQLiteImportDiagnosticsReader:
    """使用独立只读连接读取已有 import_batches/import_errors 事实。"""

    def __init__(self, database_path: Path) -> None:
        # 该 reader 不创建、不修改 ingestion schema，只负责 projection 查询。
        self.database_path = database_path
        self.connection = sqlite3.connect(str(database_path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA query_only = ON")
        self._closed = False

    def read(
        self,
        *,
        source_file: str | None = None,
        batch_id: str | None = None,
    ) -> ImportDiagnosticsProjection:
        """按 batch 或 source file 读取 Import diagnostics，不伪装成 Runtime event。"""

        self._ensure_open()
        clauses: list[str] = []
        parameters: list[str] = []
        if source_file is not None:
            clauses.append("source_file = ?")
            parameters.append(source_file)
        if batch_id is not None:
            clauses.append("batch_id = ?")
            parameters.append(batch_id)
        where_clause = "" if not clauses else " WHERE " + " AND ".join(clauses)
        try:
            batch_rows = self.connection.execute(
                """
                SELECT batch_id, source_id, source_file, session_id, started_at, finished_at,
                       received_count, inserted_count, duplicate_count, conflict_count,
                       error_count, status, error_message
                FROM import_batches
                """
                + where_clause
                + " ORDER BY started_at ASC, batch_id ASC",
                parameters,
            ).fetchall()
            batch_ids = [row["batch_id"] for row in batch_rows]
            errors_by_batch: dict[str, list[ImportErrorDiagnostic]] = defaultdict(list)
            if batch_ids:
                placeholders = ",".join("?" for _ in batch_ids)
                error_rows = self.connection.execute(
                    """
                    SELECT error_id, batch_id, error_code, error_message,
                           source_record_index, raw_locator
                    FROM import_errors
                    WHERE batch_id IN ("""
                    + placeholders
                    + ") ORDER BY batch_id ASC, error_id ASC",
                    batch_ids,
                ).fetchall()
                for row in error_rows:
                    errors_by_batch[row["batch_id"]].append(
                        ImportErrorDiagnostic(
                            error_id=row["error_id"],
                            error_code=row["error_code"],
                            error_message=row["error_message"],
                            record_index=row["source_record_index"],
                            raw_locator=row["raw_locator"],
                        )
                    )
        except sqlite3.Error as exc:
            raise ImportDiagnosticsError("import diagnostics read failed") from exc

        batches = tuple(
            ImportBatchDiagnostic(
                batch_id=row["batch_id"],
                source_file=row["source_file"],
                source_id=row["source_id"],
                session_id=row["session_id"],
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                received_count=row["received_count"],
                inserted_count=row["inserted_count"],
                duplicate_count=row["duplicate_count"],
                conflict_count=row["conflict_count"],
                error_count=row["error_count"],
                status=row["status"],
                error_message=row["error_message"],
                errors=tuple(errors_by_batch.get(row["batch_id"], ())),
            )
            for row in batch_rows
        )
        return ImportDiagnosticsProjection(
            source_file=source_file,
            batch_id=batch_id,
            batches=batches,
        )

    def close(self) -> None:
        """关闭只读 connection。"""

        if self._closed:
            return
        self._closed = True
        self.connection.close()

    def _ensure_open(self) -> None:
        """拒绝 close 后继续读取。"""

        if self._closed:
            raise ImportDiagnosticsError("import diagnostics reader is closed")
