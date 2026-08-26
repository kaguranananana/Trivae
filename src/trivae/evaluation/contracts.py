"""Evaluation 的稳定事实契约。

本模块只定义 Case、Snapshot、Variant 关联的可序列化事实，不执行 Query。
运行逻辑由 ``runner.py`` 调用生产 Application，避免 Evaluation 形成第二套 Agent。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence, cast

from trivae.capabilities.contracts import ExecutionScope
from trivae.query.evidence import scope_snapshot

from .quality import QUALITY_AXES


class EvaluationContractError(ValueError):
    """Evaluation 输入或持久化对象违反公开契约。"""


class EvaluationSnapshotError(EvaluationContractError):
    """Canonical Dataset Snapshot 无法被可靠解析。"""


AnnotationCompleteness = Literal["exhaustive", "partial", "unknown"]
SnapshotStatus = Literal["available", "invalid", "restricted", "unavailable"]
ReferenceRelation = Literal["supports", "contradicts", "context"]
ReferenceSourceType = Literal["message", "structured"]
SuiteKind = Literal["design_seed", "core", "failure_regression", "calibration_slice"]
CheckStatus = Literal["passed", "failed", "not_applicable", "unknown"]
CheckSeverity = Literal["hard", "diagnostic"]
ReviewType = Literal["human", "model_assisted"]
ReviewLabel = Literal["pass", "fail", "mixed", "unknown", "not_reviewed"]
ComparisonStatus = Literal["pending_review", "reviewed", "inconclusive", "invalid"]
DiagnosisStatus = Literal["confirmed", "likely", "unresolved"]

MAX_EVALUATION_TEXT_CHARS = 4_000
MAX_EVALUATION_ITEMS = 200
DiagnosisOwner = Literal[
    "router",
    "planner",
    "runtime",
    "tool_contract",
    "retrieval",
    "context_expansion",
    "evidence",
    "citation",
    "conversation_commit",
    "provider",
    "evaluation_infrastructure",
    "unknown",
]


class _JSONMapping(dict[str, Any]):
    """JSON 解析边界的有界映射；具体字段仍由每个 contract 做运行时校验。"""

    def get(self, key: str, default: Any = None) -> Any:
        """避免把缺失字段的 None 类型误传入 dataclass，最终校验仍在 contract 内完成。"""

        return super().get(key, default)


def utc_now() -> str:
    """生成带时区的稳定文本时间；Evaluation 不依赖本地时区。"""

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _text(value: object, field_name: str) -> str:
    """统一拒绝空字符串，不把非法值隐式转成字符串。"""

    if not isinstance(value, str) or not value.strip():
        raise EvaluationContractError(f"{field_name} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > MAX_EVALUATION_TEXT_CHARS:
        raise EvaluationContractError(f"{field_name} exceeds {MAX_EVALUATION_TEXT_CHARS} characters")
    return normalized


def _optional_text(value: object, field_name: str) -> str | None:
    """规范化可选文本。"""

    if value is None:
        return None
    return _text(value, field_name)


def _texts(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    """把可序列化文本列表归一化为去重后的 tuple。"""

    if isinstance(values, str) or not isinstance(values, (tuple, list)):
        raise EvaluationContractError(f"{field_name} must be an array of strings")
    normalized: list[str] = []
    for value in values:
        text = _text(value, field_name)
        if text not in normalized:
            normalized.append(text)
    return tuple(normalized)


def _json_safe(value: object, field_name: str = "value", depth: int = 0) -> None:
    """验证 Evaluation metadata 是 bounded JSON 值，不存 SDK/DB 对象。"""

    if depth > 8:
        raise EvaluationContractError(f"{field_name} exceeds JSON nesting bound")
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, str) and len(value) > MAX_EVALUATION_TEXT_CHARS:
            raise EvaluationContractError(f"{field_name} exceeds {MAX_EVALUATION_TEXT_CHARS} characters")
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise EvaluationContractError(f"{field_name} must contain finite numbers")
        return
    if isinstance(value, Mapping):
        if len(value) > MAX_EVALUATION_ITEMS:
            raise EvaluationContractError(f"{field_name} contains too many object fields")
        for key, nested in value.items():
            if not isinstance(key, str) or not key:
                raise EvaluationContractError(f"{field_name} contains an invalid object key")
            _json_safe(nested, f"{field_name}.{key}", depth + 1)
        return
    if isinstance(value, (tuple, list)):
        if len(value) > MAX_EVALUATION_ITEMS:
            raise EvaluationContractError(f"{field_name} contains too many array items")
        for index, nested in enumerate(value):
            _json_safe(nested, f"{field_name}[{index}]", depth + 1)
        return
    raise EvaluationContractError(f"{field_name} contains unsupported value type {type(value).__name__}")


def _mapping(value: object, field_name: str) -> _JSONMapping:
    """复制并校验一个 JSON object。解析边界由各 contract 的 __post_init__ 再次收紧类型。"""

    if not isinstance(value, Mapping):
        raise EvaluationContractError(f"{field_name} must be an object")
    _json_safe(value, field_name)
    return _JSONMapping(value)


def scope_identity(scope: ExecutionScope) -> str:
    """为可信 Scope 生成稳定、可比较但不依赖对象地址的 identity。"""

    if not isinstance(scope, ExecutionScope):
        raise EvaluationContractError("scope must be an ExecutionScope")
    return json.dumps(scope_snapshot(scope), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def scope_from_dict(value: object) -> ExecutionScope:
    """从 Case JSON 恢复生产使用的 ExecutionScope。"""

    payload = _mapping(value, "data_access_scope")
    sessions = payload.get("allowed_session_ids")
    if sessions is not None and not isinstance(sessions, (list, tuple)):
        raise EvaluationContractError("data_access_scope.allowed_session_ids must be an array or null")
    return ExecutionScope(
        allowed_session_ids=None if sessions is None else tuple(sessions),
        start_timestamp=payload.get("start_timestamp"),
        end_timestamp=payload.get("end_timestamp"),
        max_results=payload.get("max_results", 20),
    )


@dataclass(frozen=True)
class ReferenceProvenance:
    """说明 Reference 如何在指定 Snapshot/Scope 内建立。"""

    source: str
    created_at: str
    method: str
    snapshot_id: str
    scope_identity: str
    adjudicated: bool = False
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _text(self.source, "reference provenance source"))
        object.__setattr__(self, "created_at", _text(self.created_at, "reference provenance created_at"))
        object.__setattr__(self, "method", _text(self.method, "reference provenance method"))
        object.__setattr__(self, "snapshot_id", _text(self.snapshot_id, "reference provenance snapshot_id"))
        object.__setattr__(self, "scope_identity", _text(self.scope_identity, "reference provenance scope_identity"))
        if not isinstance(self.adjudicated, bool):
            raise EvaluationContractError("reference provenance adjudicated must be boolean")
        object.__setattr__(self, "limitations", _texts(self.limitations, "reference provenance limitations"))

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "created_at": self.created_at,
            "method": self.method,
            "snapshot_id": self.snapshot_id,
            "scope_identity": self.scope_identity,
            "adjudicated": self.adjudicated,
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: object) -> ReferenceProvenance:
        payload = _mapping(value, "reference_provenance")
        return cls(
            source=payload.get("source"),
            created_at=payload.get("created_at"),
            method=payload.get("method"),
            snapshot_id=payload.get("snapshot_id"),
            scope_identity=payload.get("scope_identity"),
            adjudicated=payload.get("adjudicated", False),
            limitations=tuple(payload.get("limitations", ())),
        )


@dataclass(frozen=True)
class ReferenceEvidence:
    """Finding 的一条语义化参考 Evidence，不只保存裸 message ID。"""

    evidence_id: str
    relation: ReferenceRelation
    source_type: ReferenceSourceType
    locator: Mapping[str, object]
    why_relevant: str
    provenance: ReferenceProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _text(self.evidence_id, "reference evidence_id"))
        if self.relation not in ("supports", "contradicts", "context"):
            raise EvaluationContractError("reference evidence relation is invalid")
        if self.source_type not in ("message", "structured"):
            raise EvaluationContractError("reference evidence source_type is invalid")
        locator = _mapping(self.locator, "reference evidence locator")
        if not locator:
            raise EvaluationContractError("reference evidence locator must not be empty")
        object.__setattr__(self, "locator", locator)
        object.__setattr__(self, "why_relevant", _text(self.why_relevant, "reference evidence why_relevant"))
        if not isinstance(self.provenance, ReferenceProvenance):
            raise EvaluationContractError("reference evidence provenance is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "relation": self.relation,
            "source_type": self.source_type,
            "locator": dict(self.locator),
            "why_relevant": self.why_relevant,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> ReferenceEvidence:
        payload = _mapping(value, "reference_evidence")
        return cls(
            evidence_id=payload.get("evidence_id"),
            relation=payload.get("relation"),
            source_type=payload.get("source_type"),
            locator=payload.get("locator"),
            why_relevant=payload.get("why_relevant"),
            provenance=ReferenceProvenance.from_dict(payload.get("provenance")),
        )


@dataclass(frozen=True)
class ReferenceFinding:
    """一个 Case 内可独立评审的 finding 及其完整度边界。"""

    finding_id: str
    criterion: str
    expected_semantics: str
    reference_evidence: tuple[ReferenceEvidence, ...]
    annotation_completeness: AnnotationCompleteness
    provenance: ReferenceProvenance
    known_limitations: tuple[str, ...] = ()
    critical: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "finding_id", _text(self.finding_id, "finding_id"))
        object.__setattr__(self, "criterion", _text(self.criterion, "finding criterion"))
        object.__setattr__(self, "expected_semantics", _text(self.expected_semantics, "expected_semantics"))
        if self.annotation_completeness not in ("exhaustive", "partial", "unknown"):
            raise EvaluationContractError("annotation_completeness must be exhaustive, partial, or unknown")
        if not isinstance(self.reference_evidence, tuple):
            raise EvaluationContractError("reference_evidence must be a tuple")
        if any(not isinstance(item, ReferenceEvidence) for item in self.reference_evidence):
            raise EvaluationContractError("reference_evidence contains an invalid item")
        evidence_ids = [item.evidence_id for item in self.reference_evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise EvaluationContractError("reference evidence IDs must be unique within a finding")
        if not isinstance(self.provenance, ReferenceProvenance):
            raise EvaluationContractError("finding provenance is invalid")
        for evidence in self.reference_evidence:
            if evidence.provenance.snapshot_id != self.provenance.snapshot_id:
                raise EvaluationContractError("reference evidence Snapshot differs from its Finding provenance")
            if evidence.provenance.scope_identity != self.provenance.scope_identity:
                raise EvaluationContractError("reference evidence Scope differs from its Finding provenance")
        if not isinstance(self.critical, bool):
            raise EvaluationContractError("finding critical must be boolean")
        object.__setattr__(self, "known_limitations", _texts(self.known_limitations, "known_limitations"))

    def to_dict(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "criterion": self.criterion,
            "expected_semantics": self.expected_semantics,
            "reference_evidence": [item.to_dict() for item in self.reference_evidence],
            "annotation_completeness": self.annotation_completeness,
            "provenance": self.provenance.to_dict(),
            "known_limitations": list(self.known_limitations),
            "critical": self.critical,
        }

    @classmethod
    def from_dict(cls, value: object) -> ReferenceFinding:
        payload = _mapping(value, "reference_finding")
        evidence = payload.get("reference_evidence", ())
        if not isinstance(evidence, (list, tuple)):
            raise EvaluationContractError("reference_finding.reference_evidence must be an array")
        return cls(
            finding_id=payload.get("finding_id"),
            criterion=payload.get("criterion"),
            expected_semantics=payload.get("expected_semantics"),
            reference_evidence=tuple(ReferenceEvidence.from_dict(item) for item in evidence),
            annotation_completeness=payload.get("annotation_completeness"),
            provenance=ReferenceProvenance.from_dict(payload.get("provenance")),
            known_limitations=tuple(payload.get("known_limitations", ())),
            critical=payload.get("critical", False),
        )


@dataclass(frozen=True)
class DatasetSnapshot:
    """描述一次 Evaluation 所依据的数据条件，不复制 Canonical 正文。"""

    snapshot_id: str
    canonical_database_identity: str
    schema_version: str
    source_identity: str
    message_count: int
    relevant_time_range: tuple[int | None, int | None]
    deterministic_fingerprint: str
    created_at: str
    status: SnapshotStatus = "available"
    manifest: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "snapshot_id",
            "canonical_database_identity",
            "schema_version",
            "source_identity",
            "deterministic_fingerprint",
            "created_at",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        if isinstance(self.message_count, bool) or not isinstance(self.message_count, int) or self.message_count < 0:
            raise EvaluationContractError("snapshot message_count must be a non-negative integer")
        if (
            not isinstance(self.relevant_time_range, tuple)
            or len(self.relevant_time_range) != 2
            or any(item is not None and (isinstance(item, bool) or not isinstance(item, int)) for item in self.relevant_time_range)
        ):
            raise EvaluationContractError("snapshot relevant_time_range must contain two integer values or nulls")
        start, end = self.relevant_time_range
        if start is not None and end is not None and start > end:
            raise EvaluationContractError("snapshot relevant_time_range is reversed")
        if self.status not in ("available", "invalid", "restricted", "unavailable"):
            raise EvaluationContractError("snapshot status is invalid")
        object.__setattr__(self, "manifest", _mapping(self.manifest, "snapshot manifest"))

    @classmethod
    def from_database(
        cls,
        database_path: Path,
        *,
        status: SnapshotStatus = "available",
        created_at: str | None = None,
    ) -> DatasetSnapshot:
        """从 Canonical SQLite 建立不含正文的 deterministic manifest。"""

        if status != "available":
            raise EvaluationSnapshotError("database snapshot inspection requires status=available")
        resolved = database_path.resolve()
        if not resolved.exists():
            raise EvaluationSnapshotError(f"canonical database is unavailable: {database_path}")
        try:
            connection = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            raise EvaluationSnapshotError("canonical database cannot be opened read-only") from exc
        try:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
                ).fetchall()
            }
            required = {"sources", "messages", "import_batches"}
            if not required.issubset(tables):
                missing = sorted(required - tables)
                raise EvaluationSnapshotError(f"canonical schema is incomplete: missing {missing!r}")
            source_rows = connection.execute(
                """
                SELECT source_id, file_name, adapter, format_version, platform, external_chat_id
                FROM sources
                ORDER BY source_id
                """
            ).fetchall()
            sources = [
                {
                    "source_id": row["source_id"],
                    "file_name": row["file_name"],
                    "adapter": row["adapter"],
                    "format_version": row["format_version"],
                    "platform": row["platform"],
                    "external_chat_id": row["external_chat_id"],
                }
                for row in source_rows
            ]
            count_row = connection.execute(
                "SELECT COUNT(*) AS message_count, MIN(timestamp) AS first_timestamp, MAX(timestamp) AS last_timestamp FROM messages"
            ).fetchone()
            if count_row is None:
                raise EvaluationSnapshotError("canonical message aggregate returned no row")
            lexical_row = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'messages_fts'"
            ).fetchone()
            lexical_present = lexical_row is not None
            lexical_count = None
            if lexical_present:
                lexical_count_row = connection.execute("SELECT COUNT(*) AS count FROM messages_fts").fetchone()
                if lexical_count_row is None:
                    raise EvaluationSnapshotError("lexical index count returned no row")
                lexical_count = int(lexical_count_row["count"])
            manifest: dict[str, object] = {
                "schema_version": "canonical-m1-v1",
                "sources": sources,
                "message_count": int(count_row["message_count"]),
                "first_timestamp": count_row["first_timestamp"],
                "last_timestamp": count_row["last_timestamp"],
                "lexical_index": {"present": lexical_present, "message_count": lexical_count},
            }
        except sqlite3.Error as exc:
            raise EvaluationSnapshotError("canonical snapshot query failed") from exc
        finally:
            connection.close()

        source_identity = json.dumps(sources, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        canonical_identity = f"sqlite-canonical-v1:sources={source_identity}"
        deterministic_fingerprint = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        first_timestamp = cast(int | None, manifest["first_timestamp"])
        last_timestamp = cast(int | None, manifest["last_timestamp"])
        snapshot_id = (
            "snapshot-v1:"
            f"messages={manifest['message_count']}:first={first_timestamp}:last={last_timestamp}:"
            f"sources={len(sources)}:lexical={manifest['lexical_index']}"
        )
        return cls(
            snapshot_id=snapshot_id,
            canonical_database_identity=canonical_identity,
            schema_version="canonical-m1-v1",
            source_identity=source_identity,
            message_count=cast(int, manifest["message_count"]),
            relevant_time_range=(
                None if first_timestamp is None else int(first_timestamp),
                None if last_timestamp is None else int(last_timestamp),
            ),
            deterministic_fingerprint=deterministic_fingerprint,
            created_at=created_at or utc_now(),
            status="available",
            manifest=manifest,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "canonical_database_identity": self.canonical_database_identity,
            "schema_version": self.schema_version,
            "source_identity": self.source_identity,
            "message_count": self.message_count,
            "relevant_time_range": list(self.relevant_time_range),
            "deterministic_fingerprint": self.deterministic_fingerprint,
            "created_at": self.created_at,
            "status": self.status,
            "manifest": dict(self.manifest),
        }

    @classmethod
    def from_dict(cls, value: object) -> DatasetSnapshot:
        payload = _mapping(value, "dataset_snapshot")
        time_range = payload.get("relevant_time_range")
        if not isinstance(time_range, (list, tuple)):
            raise EvaluationContractError("dataset_snapshot.relevant_time_range must be an array")
        return cls(
            snapshot_id=payload.get("snapshot_id"),
            canonical_database_identity=payload.get("canonical_database_identity"),
            schema_version=payload.get("schema_version"),
            source_identity=payload.get("source_identity"),
            message_count=payload.get("message_count"),
            relevant_time_range=tuple(time_range),
            deterministic_fingerprint=payload.get("deterministic_fingerprint"),
            created_at=payload.get("created_at"),
            status=payload.get("status", "available"),
            manifest=payload.get("manifest", {}),
        )


@dataclass(frozen=True)
class ReviewPolicy:
    """规定质量轴和人工复核边界，不给出总分。"""

    rubric_version: str = "m7-v1"
    reviewer_types: tuple[ReviewType, ...] = ("human",)
    quality_axes: tuple[str, ...] = QUALITY_AXES
    blind_pairwise: bool = True
    human_adjudication_on_disagreement: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "rubric_version", _text(self.rubric_version, "review rubric_version"))
        reviewers = _texts(self.reviewer_types, "review reviewer_types")
        if any(item not in ("human", "model_assisted") for item in reviewers):
            raise EvaluationContractError("review reviewer_types contains an unsupported type")
        if "human" not in reviewers:
            raise EvaluationContractError("review policy must support human review")
        object.__setattr__(self, "reviewer_types", reviewers)
        object.__setattr__(self, "quality_axes", _texts(self.quality_axes, "review quality_axes"))
        if not self.quality_axes:
            raise EvaluationContractError("review quality_axes must not be empty")
        if not isinstance(self.blind_pairwise, bool) or not isinstance(self.human_adjudication_on_disagreement, bool):
            raise EvaluationContractError("review policy boolean fields must be boolean")

    def to_dict(self) -> dict[str, object]:
        return {
            "rubric_version": self.rubric_version,
            "reviewer_types": list(self.reviewer_types),
            "quality_axes": list(self.quality_axes),
            "blind_pairwise": self.blind_pairwise,
            "human_adjudication_on_disagreement": self.human_adjudication_on_disagreement,
        }

    @classmethod
    def from_dict(cls, value: object) -> ReviewPolicy:
        payload = _mapping(value, "review_policy")
        return cls(
            rubric_version=payload.get("rubric_version", "m7-v1"),
            reviewer_types=tuple(payload.get("reviewer_types", ("human",))),
            quality_axes=tuple(payload.get("quality_axes", cls().quality_axes)),
            blind_pairwise=payload.get("blind_pairwise", True),
            human_adjudication_on_disagreement=payload.get("human_adjudication_on_disagreement", True),
        )


@dataclass(frozen=True)
class CaseProvenance:
    """记录 Case 由何种可靠流程建立。"""

    source: str
    method: str
    created_at: str
    notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _text(self.source, "case provenance source"))
        object.__setattr__(self, "method", _text(self.method, "case provenance method"))
        object.__setattr__(self, "created_at", _text(self.created_at, "case provenance created_at"))
        object.__setattr__(self, "notes", _optional_text(self.notes, "case provenance notes"))

    def to_dict(self) -> dict[str, object]:
        return {"source": self.source, "method": self.method, "created_at": self.created_at, "notes": self.notes}

    @classmethod
    def from_dict(cls, value: object) -> CaseProvenance:
        payload = _mapping(value, "case provenance")
        return cls(
            source=payload.get("source"),
            method=payload.get("method"),
            created_at=payload.get("created_at"),
            notes=payload.get("notes"),
        )


@dataclass(frozen=True)
class EvaluationCaseBundle:
    """Evaluation 的 canonical truth；不以唯一 expected answer 作为 Ground Truth。"""

    case_id: str
    version: int
    suite_tags: tuple[str, ...]
    dataset_snapshot: DatasetSnapshot
    data_access_scope: ExecutionScope
    query: str
    locale: str = "zh-CN"
    time_context: Mapping[str, object] | None = None
    reference_findings: tuple[ReferenceFinding, ...] = ()
    uncertainty_constraints: tuple[str, ...] = ()
    negative_constraints: tuple[str, ...] = ()
    critical_requirements: tuple[str, ...] = ()
    diagnostic_expectations: Mapping[str, object] | None = None
    review_policy: ReviewPolicy = field(default_factory=ReviewPolicy)
    provenance: CaseProvenance = field(
        default_factory=lambda: CaseProvenance("unknown", "unknown", utc_now())
    )

    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _text(self.case_id, "case_id"))
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version <= 0:
            raise EvaluationContractError("case version must be a positive integer")
        if isinstance(self.schema_version, bool) or self.schema_version != 1:
            raise EvaluationContractError("unsupported evaluation case schema_version")
        object.__setattr__(self, "suite_tags", _texts(self.suite_tags, "suite_tags"))
        if not isinstance(self.dataset_snapshot, DatasetSnapshot):
            raise EvaluationContractError("dataset_snapshot is invalid")
        if not isinstance(self.data_access_scope, ExecutionScope):
            raise EvaluationContractError("data_access_scope is invalid")
        object.__setattr__(self, "query", _text(self.query, "case query"))
        object.__setattr__(self, "locale", _text(self.locale, "case locale"))
        if self.time_context is not None:
            object.__setattr__(self, "time_context", _mapping(self.time_context, "time_context"))
        if not isinstance(self.reference_findings, tuple):
            raise EvaluationContractError("reference_findings must be a tuple")
        if any(not isinstance(item, ReferenceFinding) for item in self.reference_findings):
            raise EvaluationContractError("reference_findings contains an invalid item")
        finding_ids = [item.finding_id for item in self.reference_findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise EvaluationContractError("finding IDs must be unique within a Case version")
        expected_scope_identity = scope_identity(self.data_access_scope)
        for finding in self.reference_findings:
            if finding.provenance.snapshot_id != self.dataset_snapshot.snapshot_id:
                raise EvaluationContractError("Finding provenance Snapshot does not match the Case Snapshot")
            if finding.provenance.scope_identity != expected_scope_identity:
                raise EvaluationContractError("Finding provenance Scope does not match the Case Scope")
        object.__setattr__(self, "uncertainty_constraints", _texts(self.uncertainty_constraints, "uncertainty_constraints"))
        object.__setattr__(self, "negative_constraints", _texts(self.negative_constraints, "negative_constraints"))
        object.__setattr__(self, "critical_requirements", _texts(self.critical_requirements, "critical_requirements"))
        if self.diagnostic_expectations is not None:
            object.__setattr__(self, "diagnostic_expectations", _mapping(self.diagnostic_expectations, "diagnostic_expectations"))
        if not isinstance(self.review_policy, ReviewPolicy):
            raise EvaluationContractError("review_policy is invalid")
        if not isinstance(self.provenance, CaseProvenance):
            raise EvaluationContractError("case provenance is invalid")

    @property
    def identity(self) -> str:
        """返回不会随 query 文本或文件路径漂移的 Case identity。"""

        return f"{self.case_id}@v{self.version}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "version": self.version,
            "suite_tags": list(self.suite_tags),
            "dataset_snapshot": self.dataset_snapshot.to_dict(),
            "data_access_scope": scope_snapshot(self.data_access_scope),
            "query": self.query,
            "locale": self.locale,
            "time_context": None if self.time_context is None else dict(self.time_context),
            "reference_findings": [item.to_dict() for item in self.reference_findings],
            "uncertainty_constraints": list(self.uncertainty_constraints),
            "negative_constraints": list(self.negative_constraints),
            "critical_requirements": list(self.critical_requirements),
            "diagnostic_expectations": None
            if self.diagnostic_expectations is None
            else dict(self.diagnostic_expectations),
            "review_policy": self.review_policy.to_dict(),
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> EvaluationCaseBundle:
        payload = _mapping(value, "evaluation_case")
        findings = payload.get("reference_findings", ())
        if not isinstance(findings, (list, tuple)):
            raise EvaluationContractError("reference_findings must be an array")
        return cls(
            schema_version=payload.get("schema_version", 1),
            case_id=payload.get("case_id"),
            version=payload.get("version"),
            suite_tags=tuple(payload.get("suite_tags", ())),
            dataset_snapshot=DatasetSnapshot.from_dict(payload.get("dataset_snapshot")),
            data_access_scope=scope_from_dict(payload.get("data_access_scope")),
            query=payload.get("query"),
            locale=payload.get("locale", "zh-CN"),
            time_context=payload.get("time_context"),
            reference_findings=tuple(ReferenceFinding.from_dict(item) for item in findings),
            uncertainty_constraints=tuple(payload.get("uncertainty_constraints", ())),
            negative_constraints=tuple(payload.get("negative_constraints", ())),
            critical_requirements=tuple(payload.get("critical_requirements", ())),
            diagnostic_expectations=payload.get("diagnostic_expectations"),
            review_policy=ReviewPolicy.from_dict(payload.get("review_policy", {})),
            provenance=CaseProvenance.from_dict(payload.get("provenance")),
        )

    @classmethod
    def from_json(cls, path: Path) -> EvaluationCaseBundle:
        """从 version-controlled JSON 读取 Case，并让 contract 负责拒绝非法版本。"""

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvaluationContractError(f"case JSON cannot be read: {path}") from exc
        return cls.from_dict(payload)

    def to_json(self, path: Path) -> None:
        """以稳定缩进格式保存 Case，不包含任何运行时结果。"""

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )


@dataclass(frozen=True)
class CaseReference:
    """Suite 对 Case 的 versioned reference，不复制 Case truth。"""

    case_id: str
    case_version: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _text(self.case_id, "suite case_id"))
        if isinstance(self.case_version, bool) or not isinstance(self.case_version, int) or self.case_version <= 0:
            raise EvaluationContractError("suite case_version must be a positive integer")

    @property
    def identity(self) -> str:
        return f"{self.case_id}@v{self.case_version}"

    def to_dict(self) -> dict[str, object]:
        return {"case_id": self.case_id, "version": self.case_version}

    @classmethod
    def from_dict(cls, value: object) -> CaseReference:
        payload = _mapping(value, "suite case reference")
        return cls(payload.get("case_id"), payload.get("version"))


@dataclass(frozen=True)
class EvaluationSuite:
    """版本化 Case 清单；Suite 不承载独立的 Truth。"""

    suite_id: str
    version: int
    kind: SuiteKind
    case_references: tuple[CaseReference, ...]
    description: str
    created_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "suite_id", _text(self.suite_id, "suite_id"))
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version <= 0:
            raise EvaluationContractError("suite version must be a positive integer")
        if self.kind not in ("design_seed", "core", "failure_regression", "calibration_slice"):
            raise EvaluationContractError("suite kind is invalid")
        if not isinstance(self.case_references, tuple) or not self.case_references:
            raise EvaluationContractError("suite must contain at least one Case reference")
        if any(not isinstance(item, CaseReference) for item in self.case_references):
            raise EvaluationContractError("suite case_references contains an invalid item")
        identities = [item.identity for item in self.case_references]
        if len(identities) != len(set(identities)):
            raise EvaluationContractError("suite Case references must be unique")
        object.__setattr__(self, "description", _text(self.description, "suite description"))
        object.__setattr__(self, "created_at", _text(self.created_at, "suite created_at"))

    @property
    def identity(self) -> str:
        return f"{self.suite_id}@v{self.version}"

    def to_dict(self) -> dict[str, object]:
        return {
            "suite_id": self.suite_id,
            "version": self.version,
            "kind": self.kind,
            "description": self.description,
            "created_at": self.created_at,
            "cases": [item.to_dict() for item in self.case_references],
        }

    @classmethod
    def from_dict(cls, value: object) -> EvaluationSuite:
        payload = _mapping(value, "evaluation_suite")
        cases = payload.get("cases", ())
        if not isinstance(cases, (list, tuple)):
            raise EvaluationContractError("suite cases must be an array")
        return cls(
            suite_id=payload.get("suite_id"),
            version=payload.get("version"),
            kind=payload.get("kind"),
            case_references=tuple(CaseReference.from_dict(item) for item in cases),
            description=payload.get("description"),
            created_at=payload.get("created_at"),
        )

    @classmethod
    def from_json(cls, path: Path) -> EvaluationSuite:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvaluationContractError(f"suite JSON cannot be read: {path}") from exc
        return cls.from_dict(payload)


@dataclass(frozen=True)
class DeterministicCheck:
    """一条自动检查事实；质量判断不混入这里。"""

    name: str
    status: CheckStatus
    severity: CheckSeverity
    message: str
    evidence_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "check name"))
        if self.status not in ("passed", "failed", "not_applicable", "unknown"):
            raise EvaluationContractError("check status is invalid")
        if self.severity not in ("hard", "diagnostic"):
            raise EvaluationContractError("check severity is invalid")
        object.__setattr__(self, "message", _text(self.message, "check message"))
        object.__setattr__(self, "evidence_references", _texts(self.evidence_references, "check evidence_references"))

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "severity": self.severity,
            "message": self.message,
            "evidence_references": list(self.evidence_references),
        }

    @classmethod
    def from_dict(cls, value: object) -> DeterministicCheck:
        payload = _mapping(value, "deterministic_check")
        return cls(
            name=payload.get("name"),
            status=payload.get("status"),
            severity=payload.get("severity"),
            message=payload.get("message"),
            evidence_references=tuple(payload.get("evidence_references", ())),
        )


@dataclass(frozen=True)
class EvaluationRun:
    """一次不可合并的真实执行记录；Trace 只保存 reference。"""

    run_id: str
    case_id: str
    case_version: int
    suite_id: str
    suite_version: int
    snapshot_id: str
    scope_identity: str
    variant_id: str
    query_request_id: str
    query_request: Mapping[str, object]
    terminal_status: str
    query_result: Mapping[str, object] | None
    answer_artifact_reference: str | None
    trace_id: str | None
    deterministic_checks: tuple[DeterministicCheck, ...]
    operational_measurements: Mapping[str, object]
    started_at: str
    completed_at: str
    execution_override: Mapping[str, object]
    exception_type: str | None = None
    exception_message: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "run_id",
            "case_id",
            "suite_id",
            "snapshot_id",
            "scope_identity",
            "variant_id",
            "query_request_id",
            "terminal_status",
            "started_at",
            "completed_at",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        for field_name in ("case_version", "suite_version"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise EvaluationContractError(f"{field_name} must be a positive integer")
        object.__setattr__(self, "query_request", _mapping(self.query_request, "query_request"))
        if self.query_result is not None:
            object.__setattr__(self, "query_result", _mapping(self.query_result, "query_result"))
        object.__setattr__(self, "answer_artifact_reference", _optional_text(self.answer_artifact_reference, "answer_artifact_reference"))
        object.__setattr__(self, "trace_id", _optional_text(self.trace_id, "trace_id"))
        if not isinstance(self.deterministic_checks, tuple) or any(
            not isinstance(item, DeterministicCheck) for item in self.deterministic_checks
        ):
            raise EvaluationContractError("deterministic_checks contains an invalid item")
        object.__setattr__(self, "operational_measurements", _mapping(self.operational_measurements, "operational_measurements"))
        object.__setattr__(self, "execution_override", _mapping(self.execution_override, "execution_override"))
        object.__setattr__(self, "exception_type", _optional_text(self.exception_type, "exception_type"))
        object.__setattr__(self, "exception_message", _optional_text(self.exception_message, "exception_message"))

    @property
    def has_hard_failure(self) -> bool:
        """只把显式 hard check failure 当作 contract gate，不把 unknown 当失败。"""

        return any(item.severity == "hard" and item.status == "failed" for item in self.deterministic_checks)

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "case_id": self.case_id,
            "case_version": self.case_version,
            "suite_id": self.suite_id,
            "suite_version": self.suite_version,
            "snapshot_id": self.snapshot_id,
            "scope_identity": self.scope_identity,
            "variant_id": self.variant_id,
            "query_request_id": self.query_request_id,
            "query_request": dict(self.query_request),
            "terminal_status": self.terminal_status,
            "query_result": None if self.query_result is None else dict(self.query_result),
            "answer_artifact_reference": self.answer_artifact_reference,
            "trace_id": self.trace_id,
            "deterministic_checks": [item.to_dict() for item in self.deterministic_checks],
            "operational_measurements": dict(self.operational_measurements),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "execution_override": dict(self.execution_override),
            "exception_type": self.exception_type,
            "exception_message": self.exception_message,
        }

    @classmethod
    def from_dict(cls, value: object) -> EvaluationRun:
        payload = _mapping(value, "evaluation_run")
        checks = payload.get("deterministic_checks", ())
        if not isinstance(checks, (list, tuple)):
            raise EvaluationContractError("evaluation_run.deterministic_checks must be an array")
        return cls(
            run_id=payload.get("run_id"),
            case_id=payload.get("case_id"),
            case_version=payload.get("case_version"),
            suite_id=payload.get("suite_id"),
            suite_version=payload.get("suite_version"),
            snapshot_id=payload.get("snapshot_id"),
            scope_identity=payload.get("scope_identity"),
            variant_id=payload.get("variant_id"),
            query_request_id=payload.get("query_request_id"),
            query_request=payload.get("query_request"),
            terminal_status=payload.get("terminal_status"),
            query_result=payload.get("query_result"),
            answer_artifact_reference=payload.get("answer_artifact_reference"),
            trace_id=payload.get("trace_id"),
            deterministic_checks=tuple(DeterministicCheck.from_dict(item) for item in checks),
            operational_measurements=payload.get("operational_measurements", {}),
            started_at=payload.get("started_at"),
            completed_at=payload.get("completed_at"),
            execution_override=payload.get("execution_override", {}),
            exception_type=payload.get("exception_type"),
            exception_message=payload.get("exception_message"),
        )


@dataclass(frozen=True)
class EvaluationResult:
    """Run 的结果投影；质量轴和 diagnosability 分开保存。"""

    result_id: str
    run_id: str
    status: Literal["passed", "failed", "blocked", "not_reviewed"]
    quality_axes: Mapping[str, object]
    diagnosability: Mapping[str, object]
    operational_measurements: Mapping[str, object]
    review_ids: tuple[str, ...] = ()
    notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "result_id", _text(self.result_id, "result_id"))
        object.__setattr__(self, "run_id", _text(self.run_id, "result run_id"))
        if self.status not in ("passed", "failed", "blocked", "not_reviewed"):
            raise EvaluationContractError("evaluation result status is invalid")
        object.__setattr__(self, "quality_axes", _mapping(self.quality_axes, "quality_axes"))
        object.__setattr__(self, "diagnosability", _mapping(self.diagnosability, "diagnosability"))
        object.__setattr__(self, "operational_measurements", _mapping(self.operational_measurements, "result operational_measurements"))
        object.__setattr__(self, "review_ids", _texts(self.review_ids, "result review_ids"))
        object.__setattr__(self, "notes", _optional_text(self.notes, "result notes"))

    def to_dict(self) -> dict[str, object]:
        return {
            "result_id": self.result_id,
            "run_id": self.run_id,
            "status": self.status,
            "quality_axes": dict(self.quality_axes),
            "diagnosability": dict(self.diagnosability),
            "operational_measurements": dict(self.operational_measurements),
            "review_ids": list(self.review_ids),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: object) -> EvaluationResult:
        payload = _mapping(value, "evaluation_result")
        return cls(
            result_id=payload.get("result_id"),
            run_id=payload.get("run_id"),
            status=payload.get("status"),
            quality_axes=payload.get("quality_axes", {}),
            diagnosability=payload.get("diagnosability", {}),
            operational_measurements=payload.get("operational_measurements", {}),
            review_ids=tuple(payload.get("review_ids", ())),
            notes=payload.get("notes"),
        )


@dataclass(frozen=True)
class EvaluationReview:
    """人工或辅助 Judge 的结构化质量轴评审。"""

    review_id: str
    run_id: str
    reviewer_type: ReviewType
    rubric_version: str
    quality_axes: Mapping[str, Mapping[str, object]]
    confidence: float | None
    notes: str | None
    disagreement: str | None
    needs_adjudication: bool
    created_at: str
    comparison_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("review_id", "run_id", "rubric_version", "created_at"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        if self.reviewer_type not in ("human", "model_assisted"):
            raise EvaluationContractError("reviewer_type is invalid")
        if not isinstance(self.quality_axes, Mapping) or not self.quality_axes:
            raise EvaluationContractError("review quality_axes must not be empty")
        for axis, assessment in self.quality_axes.items():
            _text(axis, "quality axis")
            _mapping(assessment, f"quality_axes.{axis}")
        if self.confidence is not None:
            if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)) or not 0 <= self.confidence <= 1:
                raise EvaluationContractError("review confidence must be between 0 and 1")
        if not isinstance(self.needs_adjudication, bool):
            raise EvaluationContractError("needs_adjudication must be boolean")
        object.__setattr__(self, "notes", _optional_text(self.notes, "review notes"))
        object.__setattr__(self, "disagreement", _optional_text(self.disagreement, "review disagreement"))
        object.__setattr__(self, "comparison_id", _optional_text(self.comparison_id, "review comparison_id"))

    def to_dict(self) -> dict[str, object]:
        return {
            "review_id": self.review_id,
            "run_id": self.run_id,
            "reviewer_type": self.reviewer_type,
            "rubric_version": self.rubric_version,
            "quality_axes": {key: dict(value) for key, value in self.quality_axes.items()},
            "confidence": self.confidence,
            "notes": self.notes,
            "disagreement": self.disagreement,
            "needs_adjudication": self.needs_adjudication,
            "created_at": self.created_at,
            "comparison_id": self.comparison_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> EvaluationReview:
        payload = _mapping(value, "evaluation_review")
        axes = payload.get("quality_axes", {})
        if not isinstance(axes, Mapping):
            raise EvaluationContractError("review quality_axes must be an object")
        return cls(
            review_id=payload.get("review_id"),
            run_id=payload.get("run_id"),
            reviewer_type=payload.get("reviewer_type"),
            rubric_version=payload.get("rubric_version"),
            quality_axes={str(key): _mapping(value, f"quality_axes.{key}") for key, value in axes.items()},
            confidence=payload.get("confidence"),
            notes=payload.get("notes"),
            disagreement=payload.get("disagreement"),
            needs_adjudication=payload.get("needs_adjudication", False),
            created_at=payload.get("created_at"),
            comparison_id=payload.get("comparison_id"),
        )


@dataclass(frozen=True)
class ReviewPacket:
    """供 Human/Judge 使用的最小必要输入，不携带完整 Trace。"""

    packet_id: str
    run_id: str
    query: str
    answer_text: str | None
    selected_sources: tuple[Mapping[str, object], ...]
    rubric_version: str
    visible_limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "packet_id", _text(self.packet_id, "packet_id"))
        object.__setattr__(self, "run_id", _text(self.run_id, "packet run_id"))
        object.__setattr__(self, "query", _text(self.query, "packet query"))
        object.__setattr__(self, "answer_text", _optional_text(self.answer_text, "packet answer_text"))
        if not isinstance(self.selected_sources, tuple):
            raise EvaluationContractError("packet selected_sources must be a tuple")
        for index, source in enumerate(self.selected_sources):
            _mapping(source, f"packet selected_sources[{index}]")
        object.__setattr__(self, "rubric_version", _text(self.rubric_version, "packet rubric_version"))
        object.__setattr__(self, "visible_limitations", _texts(self.visible_limitations, "packet visible_limitations"))

    def to_dict(self) -> dict[str, object]:
        return {
            "packet_id": self.packet_id,
            "run_id": self.run_id,
            "query": self.query,
            "answer_text": self.answer_text,
            "selected_sources": [dict(item) for item in self.selected_sources],
            "rubric_version": self.rubric_version,
            "visible_limitations": list(self.visible_limitations),
        }

    @classmethod
    def from_dict(cls, value: object) -> ReviewPacket:
        payload = _mapping(value, "review_packet")
        sources = payload.get("selected_sources", ())
        if not isinstance(sources, (list, tuple)):
            raise EvaluationContractError("review_packet.selected_sources must be an array")
        return cls(
            packet_id=payload.get("packet_id"),
            run_id=payload.get("run_id"),
            query=payload.get("query"),
            answer_text=payload.get("answer_text"),
            selected_sources=tuple(_mapping(item, "selected_source") for item in sources),
            rubric_version=payload.get("rubric_version"),
            visible_limitations=tuple(payload.get("visible_limitations", ())),
        )


@dataclass(frozen=True)
class PairedComparison:
    """同 Case/Snapshot/Scope 下 Baseline 与 Candidate 的配对事实。"""

    comparison_id: str
    case_id: str
    case_version: int
    snapshot_id: str
    scope_identity: str
    baseline_variant_id: str
    candidate_variant_id: str
    baseline_run_ids: tuple[str, ...]
    candidate_run_ids: tuple[str, ...]
    variant_diff: Mapping[str, object]
    randomization_seed: str
    blind_order: tuple[Literal["A", "B"], ...]
    blind_assignment: Mapping[str, str] = field(default_factory=dict)
    status: ComparisonStatus = "pending_review"
    operational_diff: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "comparison_id",
            "case_id",
            "snapshot_id",
            "scope_identity",
            "baseline_variant_id",
            "candidate_variant_id",
            "randomization_seed",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        if self.baseline_variant_id == self.candidate_variant_id:
            raise EvaluationContractError("baseline and candidate variants must differ")
        if isinstance(self.case_version, bool) or not isinstance(self.case_version, int) or self.case_version <= 0:
            raise EvaluationContractError("comparison case_version must be a positive integer")
        for field_name in ("baseline_run_ids", "candidate_run_ids"):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or not values or any(not isinstance(item, str) or not item for item in values):
                raise EvaluationContractError(f"comparison {field_name} must contain run IDs")
        object.__setattr__(self, "variant_diff", _mapping(self.variant_diff, "comparison variant_diff"))
        if len(self.blind_order) != 2 or set(self.blind_order) != {"A", "B"}:
            raise EvaluationContractError("blind_order must contain A and B exactly once")
        assignment = _mapping(self.blind_assignment, "comparison blind_assignment")
        if assignment and assignment != {
            "A": self.baseline_variant_id,
            "B": self.candidate_variant_id,
        } and assignment != {
            "A": self.candidate_variant_id,
            "B": self.baseline_variant_id,
        }:
            raise EvaluationContractError("blind_assignment must map A/B to baseline and candidate variants")
        object.__setattr__(self, "blind_assignment", assignment)
        if self.status not in ("pending_review", "reviewed", "inconclusive", "invalid"):
            raise EvaluationContractError("comparison status is invalid")
        object.__setattr__(self, "operational_diff", _mapping(self.operational_diff, "comparison operational_diff"))

    def to_dict(self) -> dict[str, object]:
        return {
            "comparison_id": self.comparison_id,
            "case_id": self.case_id,
            "case_version": self.case_version,
            "snapshot_id": self.snapshot_id,
            "scope_identity": self.scope_identity,
            "baseline_variant_id": self.baseline_variant_id,
            "candidate_variant_id": self.candidate_variant_id,
            "baseline_run_ids": list(self.baseline_run_ids),
            "candidate_run_ids": list(self.candidate_run_ids),
            "variant_diff": dict(self.variant_diff),
            "randomization_seed": self.randomization_seed,
            "blind_order": list(self.blind_order),
            "blind_assignment": dict(self.blind_assignment),
            "status": self.status,
            "operational_diff": dict(self.operational_diff),
        }

    @classmethod
    def from_dict(cls, value: object) -> PairedComparison:
        payload = _mapping(value, "paired_comparison")
        order = payload.get("blind_order", ())
        if not isinstance(order, (list, tuple)):
            raise EvaluationContractError("paired_comparison.blind_order must be an array")
        return cls(
            comparison_id=payload.get("comparison_id"),
            case_id=payload.get("case_id"),
            case_version=payload.get("case_version"),
            snapshot_id=payload.get("snapshot_id"),
            scope_identity=payload.get("scope_identity"),
            baseline_variant_id=payload.get("baseline_variant_id"),
            candidate_variant_id=payload.get("candidate_variant_id"),
            baseline_run_ids=tuple(payload.get("baseline_run_ids", ())),
            candidate_run_ids=tuple(payload.get("candidate_run_ids", ())),
            variant_diff=payload.get("variant_diff", {}),
            randomization_seed=payload.get("randomization_seed"),
            blind_order=tuple(order),
            blind_assignment=payload.get("blind_assignment", {}),
            status=payload.get("status", "pending_review"),
            operational_diff=payload.get("operational_diff", {}),
        )


@dataclass(frozen=True)
class FailureDiagnosis:
    """Run 之后追加的后验解释；不修改 canonical Trace。"""

    diagnosis_id: str
    run_id: str
    primary_cause: DiagnosisOwner
    contributing_factors: tuple[str, ...]
    evidence_references: tuple[str, ...]
    trace_event_references: tuple[str, ...]
    confidence: float | None
    status: DiagnosisStatus
    notes: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("diagnosis_id", "run_id"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        if self.primary_cause not in {
            "router",
            "planner",
            "runtime",
            "tool_contract",
            "retrieval",
            "context_expansion",
            "evidence",
            "citation",
            "conversation_commit",
            "provider",
            "evaluation_infrastructure",
            "unknown",
        }:
            raise EvaluationContractError("diagnosis primary_cause is invalid")
        if self.status not in ("confirmed", "likely", "unresolved"):
            raise EvaluationContractError("diagnosis status is invalid")
        object.__setattr__(self, "contributing_factors", _texts(self.contributing_factors, "contributing_factors"))
        object.__setattr__(self, "evidence_references", _texts(self.evidence_references, "diagnosis evidence_references"))
        object.__setattr__(self, "trace_event_references", _texts(self.trace_event_references, "trace_event_references"))
        if self.confidence is not None:
            if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)) or not 0 <= self.confidence <= 1:
                raise EvaluationContractError("diagnosis confidence must be between 0 and 1")
        object.__setattr__(self, "notes", _optional_text(self.notes, "diagnosis notes"))

    def to_dict(self) -> dict[str, object]:
        return {
            "diagnosis_id": self.diagnosis_id,
            "run_id": self.run_id,
            "primary_cause": self.primary_cause,
            "contributing_factors": list(self.contributing_factors),
            "evidence_references": list(self.evidence_references),
            "trace_event_references": list(self.trace_event_references),
            "confidence": self.confidence,
            "status": self.status,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: object) -> FailureDiagnosis:
        payload = _mapping(value, "failure_diagnosis")
        return cls(
            diagnosis_id=payload.get("diagnosis_id"),
            run_id=payload.get("run_id"),
            primary_cause=payload.get("primary_cause"),
            contributing_factors=tuple(payload.get("contributing_factors", ())),
            evidence_references=tuple(payload.get("evidence_references", ())),
            trace_event_references=tuple(payload.get("trace_event_references", ())),
            confidence=payload.get("confidence"),
            status=payload.get("status"),
            notes=payload.get("notes"),
        )
