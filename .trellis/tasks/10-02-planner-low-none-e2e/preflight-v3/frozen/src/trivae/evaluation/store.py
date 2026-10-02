"""独立 SQLite Evaluation Store。

Store 只持久化 Evaluation metadata/result/review/reference，不复制 Canonical Chat 或 Trace event。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Callable, Protocol, TypeVar

from .contracts import (
    EvaluationContractError,
    EvaluationResult,
    EvaluationReview,
    EvaluationRun,
    FailureDiagnosis,
    PairedComparison,
)

_Decoded = TypeVar("_Decoded")


class EvaluationStoreError(RuntimeError):
    """Evaluation Store 读写或 lifecycle 失败。"""


class EvaluationStore(Protocol):
    """Runner 需要的最小持久化边界。"""

    def save_run(self, run: EvaluationRun) -> None:
        """保存单次 Run。"""

    def save_result(self, result: EvaluationResult) -> None:
        """保存 Run Result。"""

    def save_review(self, review: EvaluationReview) -> None:
        """保存 Review。"""

    def save_comparison(self, comparison: PairedComparison) -> None:
        """保存 Paired Comparison。"""

    def save_diagnosis(self, diagnosis: FailureDiagnosis) -> None:
        """保存 Failure Diagnosis。"""


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS evaluation_runs (
    run_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    case_version INTEGER NOT NULL CHECK (case_version > 0),
    suite_id TEXT NOT NULL,
    suite_version INTEGER NOT NULL CHECK (suite_version > 0),
    snapshot_id TEXT NOT NULL,
    scope_identity TEXT NOT NULL,
    variant_id TEXT NOT NULL,
    query_request_id TEXT NOT NULL,
    trace_id TEXT,
    answer_artifact_reference TEXT,
    terminal_status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evaluation_runs_case
    ON evaluation_runs(case_id, case_version, started_at);
CREATE INDEX IF NOT EXISTS idx_evaluation_runs_variant
    ON evaluation_runs(variant_id, started_at);

CREATE TABLE IF NOT EXISTS evaluation_results (
    result_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES evaluation_runs(run_id)
);

CREATE TABLE IF NOT EXISTS evaluation_reviews (
    review_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    comparison_id TEXT,
    reviewer_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES evaluation_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_evaluation_reviews_run
    ON evaluation_reviews(run_id, created_at);

CREATE TABLE IF NOT EXISTS evaluation_comparisons (
    comparison_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    case_version INTEGER NOT NULL CHECK (case_version > 0),
    snapshot_id TEXT NOT NULL,
    scope_identity TEXT NOT NULL,
    baseline_variant_id TEXT NOT NULL,
    candidate_variant_id TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluation_diagnoses (
    diagnosis_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    primary_cause TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES evaluation_runs(run_id)
);
"""


def _json_dumps(value: object) -> str:
    """只将已通过 contract 的普通值写入 JSON；编码失败必须显式暴露。"""

    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise EvaluationStoreError("evaluation payload is not JSON serializable") from exc


def _json_loads(value: str, field_name: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise EvaluationStoreError(f"evaluation {field_name} JSON is invalid") from exc


class SQLiteEvaluationStore:
    """拥有独立 SQLite connection 的 local-first Evaluation Store。"""

    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = database_path
        self.connection = sqlite3.connect(str(database_path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        try:
            self.connection.executescript(SCHEMA_SQL)
            self.connection.commit()
        except sqlite3.Error as exc:
            self.connection.close()
            raise EvaluationStoreError("evaluation schema initialization failed") from exc
        self._closed = False

    def close(self) -> None:
        """关闭连接；close 后不会偷偷重建 Store。"""

        if self._closed:
            return
        self._closed = True
        self.connection.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise EvaluationStoreError("evaluation store is closed")

    def save_run(self, run: EvaluationRun) -> None:
        self._ensure_open()
        payload = _json_dumps(run.to_dict())
        try:
            self.connection.execute(
                """
                INSERT INTO evaluation_runs(
                    run_id, case_id, case_version, suite_id, suite_version, snapshot_id,
                    scope_identity, variant_id, query_request_id, trace_id,
                    answer_artifact_reference, terminal_status, started_at, completed_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    trace_id=excluded.trace_id,
                    answer_artifact_reference=excluded.answer_artifact_reference,
                    terminal_status=excluded.terminal_status,
                    completed_at=excluded.completed_at
                """,
                (
                    run.run_id,
                    run.case_id,
                    run.case_version,
                    run.suite_id,
                    run.suite_version,
                    run.snapshot_id,
                    run.scope_identity,
                    run.variant_id,
                    run.query_request_id,
                    run.trace_id,
                    run.answer_artifact_reference,
                    run.terminal_status,
                    run.started_at,
                    run.completed_at,
                    payload,
                ),
            )
            self.connection.commit()
        except sqlite3.Error as exc:
            self.connection.rollback()
            raise EvaluationStoreError(f"evaluation run save failed: {run.run_id}") from exc

    def save_result(self, result: EvaluationResult) -> None:
        self._ensure_open()
        payload = _json_dumps(result.to_dict())
        try:
            self.connection.execute(
                """
                INSERT INTO evaluation_results(result_id, run_id, status, payload_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(result_id) DO UPDATE SET
                    run_id=excluded.run_id, status=excluded.status, payload_json=excluded.payload_json
                """,
                (result.result_id, result.run_id, result.status, payload),
            )
            self.connection.commit()
        except sqlite3.Error as exc:
            self.connection.rollback()
            raise EvaluationStoreError(f"evaluation result save failed: {result.result_id}") from exc

    def save_review(self, review: EvaluationReview) -> None:
        self._ensure_open()
        payload = _json_dumps(review.to_dict())
        try:
            self.connection.execute(
                """
                INSERT INTO evaluation_reviews(review_id, run_id, comparison_id, reviewer_type, created_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(review_id) DO UPDATE SET
                    run_id=excluded.run_id,
                    comparison_id=excluded.comparison_id,
                    reviewer_type=excluded.reviewer_type,
                    created_at=excluded.created_at,
                    payload_json=excluded.payload_json
                """,
                (review.review_id, review.run_id, review.comparison_id, review.reviewer_type, review.created_at, payload),
            )
            self.connection.commit()
        except sqlite3.Error as exc:
            self.connection.rollback()
            raise EvaluationStoreError(f"evaluation review save failed: {review.review_id}") from exc

    def save_comparison(self, comparison: PairedComparison) -> None:
        self._ensure_open()
        payload = _json_dumps(comparison.to_dict())
        try:
            self.connection.execute(
                """
                INSERT INTO evaluation_comparisons(
                    comparison_id, case_id, case_version, snapshot_id, scope_identity,
                    baseline_variant_id, candidate_variant_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(comparison_id) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    snapshot_id=excluded.snapshot_id,
                    scope_identity=excluded.scope_identity,
                    baseline_variant_id=excluded.baseline_variant_id,
                    candidate_variant_id=excluded.candidate_variant_id
                """,
                (
                    comparison.comparison_id,
                    comparison.case_id,
                    comparison.case_version,
                    comparison.snapshot_id,
                    comparison.scope_identity,
                    comparison.baseline_variant_id,
                    comparison.candidate_variant_id,
                    payload,
                ),
            )
            self.connection.commit()
        except sqlite3.Error as exc:
            self.connection.rollback()
            raise EvaluationStoreError(f"evaluation comparison save failed: {comparison.comparison_id}") from exc

    def save_diagnosis(self, diagnosis: FailureDiagnosis) -> None:
        self._ensure_open()
        payload = _json_dumps(diagnosis.to_dict())
        try:
            self.connection.execute(
                """
                INSERT INTO evaluation_diagnoses(diagnosis_id, run_id, primary_cause, status, payload_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(diagnosis_id) DO UPDATE SET
                    run_id=excluded.run_id,
                    primary_cause=excluded.primary_cause,
                    status=excluded.status,
                    payload_json=excluded.payload_json
                """,
                (diagnosis.diagnosis_id, diagnosis.run_id, diagnosis.primary_cause, diagnosis.status, payload),
            )
            self.connection.commit()
        except sqlite3.Error as exc:
            self.connection.rollback()
            raise EvaluationStoreError(f"evaluation diagnosis save failed: {diagnosis.diagnosis_id}") from exc

    def get_run(self, run_id: str) -> EvaluationRun:
        self._ensure_open()
        row = self.connection.execute(
            "SELECT payload_json FROM evaluation_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise EvaluationStoreError(f"evaluation run not found: {run_id}")
        return self._decode(EvaluationRun.from_dict, row["payload_json"], "run")

    def get_result(self, result_id: str) -> EvaluationResult:
        self._ensure_open()
        row = self.connection.execute(
            "SELECT payload_json FROM evaluation_results WHERE result_id = ?", (result_id,)
        ).fetchone()
        if row is None:
            raise EvaluationStoreError(f"evaluation result not found: {result_id}")
        return self._decode(EvaluationResult.from_dict, row["payload_json"], "result")

    def get_review(self, review_id: str) -> EvaluationReview:
        self._ensure_open()
        row = self.connection.execute(
            "SELECT payload_json FROM evaluation_reviews WHERE review_id = ?", (review_id,)
        ).fetchone()
        if row is None:
            raise EvaluationStoreError(f"evaluation review not found: {review_id}")
        return self._decode(EvaluationReview.from_dict, row["payload_json"], "review")

    def get_comparison(self, comparison_id: str) -> PairedComparison:
        self._ensure_open()
        row = self.connection.execute(
            "SELECT payload_json FROM evaluation_comparisons WHERE comparison_id = ?", (comparison_id,)
        ).fetchone()
        if row is None:
            raise EvaluationStoreError(f"evaluation comparison not found: {comparison_id}")
        return self._decode(PairedComparison.from_dict, row["payload_json"], "comparison")

    def get_diagnosis(self, diagnosis_id: str) -> FailureDiagnosis:
        self._ensure_open()
        row = self.connection.execute(
            "SELECT payload_json FROM evaluation_diagnoses WHERE diagnosis_id = ?", (diagnosis_id,)
        ).fetchone()
        if row is None:
            raise EvaluationStoreError(f"evaluation diagnosis not found: {diagnosis_id}")
        return self._decode(FailureDiagnosis.from_dict, row["payload_json"], "diagnosis")

    def list_runs(self, *, case_id: str | None = None) -> tuple[EvaluationRun, ...]:
        """按 started_at 返回单次 Run，便于 CLI 回溯而不是只看 aggregate。"""

        self._ensure_open()
        if case_id is None:
            rows = self.connection.execute(
                "SELECT payload_json FROM evaluation_runs ORDER BY started_at, run_id"
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT payload_json FROM evaluation_runs WHERE case_id = ? ORDER BY started_at, run_id",
                (case_id,),
            ).fetchall()
        return tuple(self._decode(EvaluationRun.from_dict, row["payload_json"], "run") for row in rows)

    @staticmethod
    def _decode(factory: Callable[[object], _Decoded], payload: str, field_name: str) -> _Decoded:
        value = _json_loads(payload, field_name)
        try:
            return factory(value)
        except (EvaluationContractError, TypeError, KeyError) as exc:
            raise EvaluationStoreError(f"stored evaluation {field_name} does not match its contract") from exc
