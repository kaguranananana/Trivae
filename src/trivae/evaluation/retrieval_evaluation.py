"""Lexical/Semantic retrieval 的盲标 packet、provisional 标签与配对指标。"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from trivae.capabilities.contracts import (
    ExecutionScope,
    SearchMessagesInput,
    SemanticSearchInput,
    ToolEnvelope,
)
from trivae.retrieval.semantic.chunking import is_semantic_void
from trivae.retrieval.semantic.contracts import SemanticMessage, SemanticRetrievalResult
from trivae.retrieval.structured import MessageProjection, RetrievalResult, message_sort_key

from .contracts import (
    DatasetSnapshot,
    EvaluationContractError,
    _mapping,
    _text,
    scope_from_dict,
    utc_now,
)
from .variant import ControlledVariant

RetrievalStrategy = Literal["lexical", "semantic"]
RelevanceLabel = Literal["relevant", "partially_relevant", "not_relevant", "uncertain"]
VerificationStatus = Literal["llm_assisted_provisional", "human_verified"]
MetricAvailability = Literal["available", "partial", "unavailable"]

RETRIEVAL_PACKET_SCHEMA_VERSION = "retrieval-annotation-v1"
RETRIEVAL_RUBRIC_VERSION = "retrieval-relevance-v1"
_RESOLVED_LABELS = frozenset({"relevant", "partially_relevant", "not_relevant"})
_MESSAGE_CONTENT_LIMIT = 700
_CONTEXT_MESSAGE_LIMIT = 10


def _positive_integer(value: object, field_name: str) -> int:
    """统一校验 query/packet 中的正整数边界。"""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EvaluationContractError(f"{field_name} must be a positive integer")
    return value


def _non_negative_integer(value: object, field_name: str) -> int:
    """统一校验 context 等允许为零的整数边界。"""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvaluationContractError(f"{field_name} must be a non-negative integer")
    return value


def _finite_number(value: object, field_name: str) -> float:
    """拒绝 bool、NaN 与 infinity，避免 confidence/score 进入不可比较状态。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationContractError(f"{field_name} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise EvaluationContractError(f"{field_name} must be a finite number")
    return normalized


def _scope_to_dict(scope: ExecutionScope) -> dict[str, object]:
    """使用现有 ExecutionScope 语义输出 query-set JSON。"""

    return {
        "allowed_session_ids": None
        if scope.allowed_session_ids is None
        else list(scope.allowed_session_ids),
        "start_timestamp": scope.start_timestamp,
        "end_timestamp": scope.end_timestamp,
        "max_results": scope.max_results,
    }


def _read_json(path: Path, field_name: str) -> object:
    """读取本地 Evaluation artifact，并把 I/O/JSON 错误保留在 Evaluation 边界。"""

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvaluationContractError(f"{field_name} cannot be read: {path}") from exc
    except json.JSONDecodeError as exc:
        raise EvaluationContractError(f"{field_name} is not valid JSON: {path}") from exc


@dataclass(frozen=True)
class RetrievalEvaluationQuery:
    """同一自然语言问题的 lexical control 与 semantic candidate 输入。"""

    query_id: str
    query: str
    lexical_query: str
    query_types: tuple[str, ...]
    scope: ExecutionScope
    candidate_limit: int = 8
    context_before: int = 2
    context_after: int = 2
    dense_top_k: int = 40
    diagnostic: bool = True
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_id", _text(self.query_id, "query_id"))
        object.__setattr__(self, "query", _text(self.query, "query"))
        object.__setattr__(self, "lexical_query", _text(self.lexical_query, "lexical_query"))
        if not isinstance(self.query_types, tuple) or not self.query_types:
            raise EvaluationContractError("query_types must be a non-empty tuple")
        normalized_types = tuple(_text(item, "query_types") for item in self.query_types)
        if len(set(normalized_types)) != len(normalized_types):
            raise EvaluationContractError("query_types must not contain duplicates")
        object.__setattr__(self, "query_types", normalized_types)
        if not isinstance(self.scope, ExecutionScope):
            raise EvaluationContractError("scope must be an ExecutionScope")
        _positive_integer(self.candidate_limit, "candidate_limit")
        _non_negative_integer(self.context_before, "context_before")
        _non_negative_integer(self.context_after, "context_after")
        _positive_integer(self.dense_top_k, "dense_top_k")
        if self.candidate_limit > self.scope.max_results:
            raise EvaluationContractError("candidate_limit must not exceed scope.max_results")
        if not isinstance(self.diagnostic, bool):
            raise EvaluationContractError("diagnostic must be a boolean")
        if not isinstance(self.notes, str):
            raise EvaluationContractError("notes must be a string")

    def to_dict(self) -> dict[str, object]:
        """返回不含聊天正文的 version-controlled query metadata。"""

        return {
            "query_id": self.query_id,
            "query": self.query,
            "lexical_query": self.lexical_query,
            "query_types": list(self.query_types),
            "scope": _scope_to_dict(self.scope),
            "candidate_limit": self.candidate_limit,
            "context_before": self.context_before,
            "context_after": self.context_after,
            "dense_top_k": self.dense_top_k,
            "diagnostic": self.diagnostic,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: object) -> RetrievalEvaluationQuery:
        """从 query-set JSON 恢复并复用同一边界校验。"""

        payload = _mapping(value, "retrieval_query")
        query_types = payload.get("query_types")
        if not isinstance(query_types, Sequence) or isinstance(query_types, (str, bytes)):
            raise EvaluationContractError("retrieval_query.query_types must be an array")
        scope = scope_from_dict(payload.get("scope", {}))
        return cls(
            query_id=payload.get("query_id"),
            query=payload.get("query"),
            lexical_query=payload.get("lexical_query"),
            query_types=tuple(query_types),
            scope=scope,
            candidate_limit=payload.get("candidate_limit", 8),
            context_before=payload.get("context_before", 2),
            context_after=payload.get("context_after", 2),
            dense_top_k=payload.get("dense_top_k", 40),
            diagnostic=payload.get("diagnostic", True),
            notes=payload.get("notes", ""),
        )


@dataclass(frozen=True)
class RetrievalQuerySet:
    """绑定固定 Snapshot 的 retrieval module evaluation Case 集。"""

    query_set_id: str
    version: int
    snapshot_id: str
    queries: tuple[RetrievalEvaluationQuery, ...]
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_set_id", _text(self.query_set_id, "query_set_id"))
        _positive_integer(self.version, "query_set version")
        object.__setattr__(self, "snapshot_id", _text(self.snapshot_id, "snapshot_id"))
        if not isinstance(self.queries, tuple) or not self.queries:
            raise EvaluationContractError("retrieval query set must contain queries")
        if any(not isinstance(item, RetrievalEvaluationQuery) for item in self.queries):
            raise EvaluationContractError("retrieval query set contains an invalid query")
        identities = [item.query_id for item in self.queries]
        if len(set(identities)) != len(identities):
            raise EvaluationContractError("retrieval query IDs must be unique")
        if not isinstance(self.description, str):
            raise EvaluationContractError("retrieval query-set description must be a string")

    @property
    def identity(self) -> str:
        return f"{self.query_set_id}:v{self.version}:{self.snapshot_id}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": RETRIEVAL_PACKET_SCHEMA_VERSION,
            "query_set_id": self.query_set_id,
            "version": self.version,
            "snapshot_id": self.snapshot_id,
            "description": self.description,
            "queries": [item.to_dict() for item in self.queries],
        }

    @classmethod
    def from_dict(cls, value: object) -> RetrievalQuerySet:
        payload = _mapping(value, "retrieval_query_set")
        queries = payload.get("queries")
        if not isinstance(queries, Sequence) or isinstance(queries, (str, bytes)):
            raise EvaluationContractError("retrieval_query_set.queries must be an array")
        return cls(
            query_set_id=payload.get("query_set_id"),
            version=payload.get("version"),
            snapshot_id=payload.get("snapshot_id"),
            description=payload.get("description", ""),
            queries=tuple(RetrievalEvaluationQuery.from_dict(item) for item in queries),
        )

    @classmethod
    def from_json(cls, path: Path) -> RetrievalQuerySet:
        return cls.from_dict(_read_json(path, "retrieval query set"))


@dataclass(frozen=True)
class RetrievalAppearance:
    """候选在一种检索方法中的 sealed rank/score provenance。"""

    strategy: RetrievalStrategy
    rank: int
    source_rank: int
    score: float
    score_type: str
    hit_identity: str

    def __post_init__(self) -> None:
        if self.strategy not in ("lexical", "semantic"):
            raise EvaluationContractError("retrieval appearance strategy is invalid")
        _positive_integer(self.rank, "retrieval appearance rank")
        _positive_integer(self.source_rank, "retrieval appearance source_rank")
        _finite_number(self.score, "retrieval appearance score")
        object.__setattr__(self, "score_type", _text(self.score_type, "score_type"))
        object.__setattr__(self, "hit_identity", _text(self.hit_identity, "hit_identity"))

    def to_dict(self) -> dict[str, object]:
        return {
            "strategy": self.strategy,
            "rank": self.rank,
            "source_rank": self.source_rank,
            "score": self.score,
            "score_type": self.score_type,
            "hit_identity": self.hit_identity,
        }

    @classmethod
    def from_dict(cls, value: object) -> RetrievalAppearance:
        payload = _mapping(value, "retrieval_appearance")
        return cls(
            strategy=payload.get("strategy"),
            rank=payload.get("rank"),
            source_rank=payload.get("source_rank"),
            score=payload.get("score"),
            score_type=payload.get("score_type"),
            hit_identity=payload.get("hit_identity"),
        )


@dataclass(frozen=True)
class SealedCandidate:
    """盲标结束后才合并的 canonical identity 与 retrieval provenance。"""

    blind_id: str
    query_id: str
    canonical_message_id: str
    session_id: str
    source_message_id: str | None
    timestamp: int
    appearances: tuple[RetrievalAppearance, ...]
    context_message_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("blind_id", "query_id", "canonical_message_id", "session_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.source_message_id is not None:
            object.__setattr__(
                self,
                "source_message_id",
                _text(self.source_message_id, "source_message_id"),
            )
        if isinstance(self.timestamp, bool) or not isinstance(self.timestamp, int):
            raise EvaluationContractError("sealed candidate timestamp must be an integer")
        if not isinstance(self.appearances, tuple) or not self.appearances:
            raise EvaluationContractError("sealed candidate must have retrieval appearances")
        strategies = [item.strategy for item in self.appearances]
        if len(set(strategies)) != len(strategies):
            raise EvaluationContractError("sealed candidate has duplicate strategy appearances")
        if not isinstance(self.context_message_ids, tuple) or not self.context_message_ids:
            raise EvaluationContractError("sealed candidate context IDs must be non-empty")
        if any(not isinstance(item, str) or not item for item in self.context_message_ids):
            raise EvaluationContractError("sealed candidate context IDs are invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "blind_id": self.blind_id,
            "query_id": self.query_id,
            "canonical_message_id": self.canonical_message_id,
            "session_id": self.session_id,
            "source_message_id": self.source_message_id,
            "timestamp": self.timestamp,
            "appearances": [item.to_dict() for item in self.appearances],
            "context_message_ids": list(self.context_message_ids),
        }

    @classmethod
    def from_dict(cls, value: object) -> SealedCandidate:
        payload = _mapping(value, "sealed_candidate")
        appearances = payload.get("appearances")
        context_ids = payload.get("context_message_ids")
        if not isinstance(appearances, Sequence) or isinstance(appearances, (str, bytes)):
            raise EvaluationContractError("sealed_candidate.appearances must be an array")
        if not isinstance(context_ids, Sequence) or isinstance(context_ids, (str, bytes)):
            raise EvaluationContractError("sealed_candidate.context_message_ids must be an array")
        return cls(
            blind_id=payload.get("blind_id"),
            query_id=payload.get("query_id"),
            canonical_message_id=payload.get("canonical_message_id"),
            session_id=payload.get("session_id"),
            source_message_id=payload.get("source_message_id"),
            timestamp=payload.get("timestamp"),
            appearances=tuple(RetrievalAppearance.from_dict(item) for item in appearances),
            context_message_ids=tuple(context_ids),
        )


@dataclass(frozen=True)
class RetrievalRunRecord:
    """一种策略在一个 query 上的 bounded module-run 事实。"""

    query_id: str
    strategy: RetrievalStrategy
    variant_id: str
    variant_identity: str
    ranked_candidate_ids: tuple[str, ...]
    expanded_message_ids: tuple[str, ...]
    total_hits: int
    latency_ms: float
    coverage_status: str
    coverage_basis: str
    partial: bool
    truncated: bool
    parameters: Mapping[str, object]
    index_identity: str

    def __post_init__(self) -> None:
        for name in (
            "query_id",
            "variant_id",
            "variant_identity",
            "coverage_status",
            "coverage_basis",
            "index_identity",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.strategy not in ("lexical", "semantic"):
            raise EvaluationContractError("retrieval run strategy is invalid")
        if not isinstance(self.ranked_candidate_ids, tuple):
            raise EvaluationContractError("ranked_candidate_ids must be a tuple")
        if any(not isinstance(item, str) or not item for item in self.ranked_candidate_ids):
            raise EvaluationContractError("ranked_candidate_ids contain invalid IDs")
        if not isinstance(self.expanded_message_ids, tuple):
            raise EvaluationContractError("expanded_message_ids must be a tuple")
        if any(not isinstance(item, str) or not item for item in self.expanded_message_ids):
            raise EvaluationContractError("expanded_message_ids contain invalid IDs")
        if isinstance(self.total_hits, bool) or not isinstance(self.total_hits, int) or self.total_hits < 0:
            raise EvaluationContractError("retrieval run total_hits must be non-negative")
        _finite_number(self.latency_ms, "retrieval run latency_ms")
        if not isinstance(self.partial, bool) or not isinstance(self.truncated, bool):
            raise EvaluationContractError("retrieval run partial/truncated must be booleans")
        if not isinstance(self.parameters, Mapping):
            raise EvaluationContractError("retrieval run parameters must be a mapping")

    def to_dict(self) -> dict[str, object]:
        return {
            "query_id": self.query_id,
            "strategy": self.strategy,
            "variant_id": self.variant_id,
            "variant_identity": self.variant_identity,
            "ranked_candidate_ids": list(self.ranked_candidate_ids),
            "expanded_message_ids": list(self.expanded_message_ids),
            "total_hits": self.total_hits,
            "latency_ms": self.latency_ms,
            "coverage_status": self.coverage_status,
            "coverage_basis": self.coverage_basis,
            "partial": self.partial,
            "truncated": self.truncated,
            "parameters": dict(self.parameters),
            "index_identity": self.index_identity,
        }

    @classmethod
    def from_dict(cls, value: object) -> RetrievalRunRecord:
        payload = _mapping(value, "retrieval_run")
        ranked_ids = payload.get("ranked_candidate_ids")
        expanded_ids = payload.get("expanded_message_ids")
        if not isinstance(ranked_ids, Sequence) or isinstance(ranked_ids, (str, bytes)):
            raise EvaluationContractError("retrieval_run.ranked_candidate_ids must be an array")
        if not isinstance(expanded_ids, Sequence) or isinstance(expanded_ids, (str, bytes)):
            raise EvaluationContractError("retrieval_run.expanded_message_ids must be an array")
        return cls(
            query_id=payload.get("query_id"),
            strategy=payload.get("strategy"),
            variant_id=payload.get("variant_id"),
            variant_identity=payload.get("variant_identity"),
            ranked_candidate_ids=tuple(ranked_ids),
            expanded_message_ids=tuple(expanded_ids),
            total_hits=payload.get("total_hits"),
            latency_ms=payload.get("latency_ms"),
            coverage_status=payload.get("coverage_status"),
            coverage_basis=payload.get("coverage_basis"),
            partial=payload.get("partial"),
            truncated=payload.get("truncated"),
            parameters=payload.get("parameters", {}),
            index_identity=payload.get("index_identity"),
        )


@dataclass(frozen=True)
class BlindCandidate:
    """Labeler 可见的 query/candidate/context；刻意不含 strategy/rank/score。"""

    blind_id: str
    query_id: str
    query: str
    candidate: Mapping[str, object]
    context: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        for name in ("blind_id", "query_id", "query"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.candidate, Mapping):
            raise EvaluationContractError("blind candidate message must be a mapping")
        if not isinstance(self.context, tuple) or not self.context:
            raise EvaluationContractError("blind candidate context must be non-empty")
        if any(not isinstance(item, Mapping) for item in self.context):
            raise EvaluationContractError("blind candidate context item must be a mapping")

    def to_dict(self) -> dict[str, object]:
        return {
            "blind_id": self.blind_id,
            "query_id": self.query_id,
            "query": self.query,
            "candidate": dict(self.candidate),
            "context": [dict(item) for item in self.context],
            "annotation": {"label": None, "confidence": None, "notes": ""},
        }

    @classmethod
    def from_dict(cls, value: object) -> BlindCandidate:
        payload = _mapping(value, "blind_candidate")
        context = payload.get("context")
        if not isinstance(context, Sequence) or isinstance(context, (str, bytes)):
            raise EvaluationContractError("blind_candidate.context must be an array")
        candidate = payload.get("candidate")
        if not isinstance(candidate, Mapping):
            raise EvaluationContractError("blind_candidate.candidate must be an object")
        return cls(
            blind_id=payload.get("blind_id"),
            query_id=payload.get("query_id"),
            query=payload.get("query"),
            candidate=candidate,
            context=tuple(_mapping(item, "blind_candidate.context item") for item in context),
        )


@dataclass(frozen=True)
class BlindAnnotationPacket:
    """可直接给人工或 LLM 的 local-only relevance 标注包。"""

    packet_id: str
    query_set_id: str
    query_set_version: int
    snapshot_id: str
    rubric_version: str
    created_at: str
    candidates: tuple[BlindCandidate, ...]

    def __post_init__(self) -> None:
        for name in ("packet_id", "query_set_id", "snapshot_id", "rubric_version", "created_at"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        _positive_integer(self.query_set_version, "query_set_version")
        if not isinstance(self.candidates, tuple):
            raise EvaluationContractError("blind packet candidates must be a tuple")
        identities = [item.blind_id for item in self.candidates]
        if len(set(identities)) != len(identities):
            raise EvaluationContractError("blind packet candidate IDs must be unique")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": RETRIEVAL_PACKET_SCHEMA_VERSION,
            "packet_id": self.packet_id,
            "query_set_id": self.query_set_id,
            "query_set_version": self.query_set_version,
            "snapshot_id": self.snapshot_id,
            "rubric_version": self.rubric_version,
            "created_at": self.created_at,
            "blindness": {
                "retrieval_source_hidden": True,
                "rank_hidden": True,
                "score_hidden": True,
                "variant_identity_hidden": True,
            },
            "labels": ["relevant", "partially_relevant", "not_relevant", "uncertain"],
            "candidates": [item.to_dict() for item in self.candidates],
        }

    @classmethod
    def from_dict(cls, value: object) -> BlindAnnotationPacket:
        payload = _mapping(value, "blind_annotation_packet")
        candidates = payload.get("candidates")
        if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
            raise EvaluationContractError("blind_annotation_packet.candidates must be an array")
        return cls(
            packet_id=payload.get("packet_id"),
            query_set_id=payload.get("query_set_id"),
            query_set_version=payload.get("query_set_version"),
            snapshot_id=payload.get("snapshot_id"),
            rubric_version=payload.get("rubric_version"),
            created_at=payload.get("created_at"),
            candidates=tuple(BlindCandidate.from_dict(item) for item in candidates),
        )

    @classmethod
    def from_json(cls, path: Path) -> BlindAnnotationPacket:
        return cls.from_dict(_read_json(path, "blind annotation packet"))


@dataclass(frozen=True)
class SealedRetrievalPacket:
    """本地保存的 method/rank/score 映射；盲标前不能交给 labeler。"""

    packet_id: str
    query_set: RetrievalQuerySet
    snapshot: DatasetSnapshot
    lexical_variant: ControlledVariant
    semantic_variant: ControlledVariant
    created_at: str
    runs: tuple[RetrievalRunRecord, ...]
    candidates: tuple[SealedCandidate, ...]
    diagnostics: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "packet_id", _text(self.packet_id, "packet_id"))
        object.__setattr__(self, "created_at", _text(self.created_at, "created_at"))
        if not isinstance(self.query_set, RetrievalQuerySet):
            raise EvaluationContractError("sealed packet query_set is invalid")
        if not isinstance(self.snapshot, DatasetSnapshot):
            raise EvaluationContractError("sealed packet snapshot is invalid")
        if self.query_set.snapshot_id != self.snapshot.snapshot_id:
            raise EvaluationContractError("sealed packet Snapshot does not match query set")
        if not isinstance(self.lexical_variant, ControlledVariant) or not isinstance(
            self.semantic_variant, ControlledVariant
        ):
            raise EvaluationContractError("sealed packet variants are invalid")
        if not isinstance(self.runs, tuple) or not isinstance(self.candidates, tuple):
            raise EvaluationContractError("sealed packet runs/candidates must be tuples")
        run_keys = [(item.query_id, item.strategy) for item in self.runs]
        if len(set(run_keys)) != len(run_keys):
            raise EvaluationContractError("sealed packet has duplicate strategy runs")
        blind_ids = [item.blind_id for item in self.candidates]
        if len(set(blind_ids)) != len(blind_ids):
            raise EvaluationContractError("sealed packet blind IDs must be unique")
        candidate_keys = [(item.query_id, item.canonical_message_id) for item in self.candidates]
        if len(set(candidate_keys)) != len(candidate_keys):
            raise EvaluationContractError("sealed packet candidates must be query-local unique")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": RETRIEVAL_PACKET_SCHEMA_VERSION,
            "packet_id": self.packet_id,
            "query_set": self.query_set.to_dict(),
            "snapshot": self.snapshot.to_dict(),
            "lexical_variant": self.lexical_variant.to_dict(),
            "semantic_variant": self.semantic_variant.to_dict(),
            "created_at": self.created_at,
            "runs": [item.to_dict() for item in self.runs],
            "candidates": [item.to_dict() for item in self.candidates],
            "diagnostics": [dict(item) for item in self.diagnostics],
        }

    @classmethod
    def from_dict(cls, value: object) -> SealedRetrievalPacket:
        payload = _mapping(value, "sealed_retrieval_packet")
        runs = payload.get("runs")
        candidates = payload.get("candidates")
        diagnostics = payload.get("diagnostics", ())
        for field_name, field_value in (
            ("runs", runs),
            ("candidates", candidates),
            ("diagnostics", diagnostics),
        ):
            if not isinstance(field_value, Sequence) or isinstance(field_value, (str, bytes)):
                raise EvaluationContractError(f"sealed_retrieval_packet.{field_name} must be an array")
        return cls(
            packet_id=payload.get("packet_id"),
            query_set=RetrievalQuerySet.from_dict(payload.get("query_set")),
            snapshot=DatasetSnapshot.from_dict(payload.get("snapshot")),
            lexical_variant=ControlledVariant.from_dict(payload.get("lexical_variant")),
            semantic_variant=ControlledVariant.from_dict(payload.get("semantic_variant")),
            created_at=payload.get("created_at"),
            runs=tuple(RetrievalRunRecord.from_dict(item) for item in runs),
            candidates=tuple(SealedCandidate.from_dict(item) for item in candidates),
            diagnostics=tuple(_mapping(item, "sealed diagnostic") for item in diagnostics),
        )

    @classmethod
    def from_json(cls, path: Path) -> SealedRetrievalPacket:
        return cls.from_dict(_read_json(path, "sealed retrieval packet"))


@dataclass(frozen=True)
class RelevanceAnnotation:
    """一个候选的可审计 relevance 标签；confidence 不等于人工一致率。"""

    blind_id: str
    label: RelevanceLabel
    confidence: float
    notes: str
    verification_status: VerificationStatus

    def __post_init__(self) -> None:
        object.__setattr__(self, "blind_id", _text(self.blind_id, "blind_id"))
        if self.label not in (
            "relevant",
            "partially_relevant",
            "not_relevant",
            "uncertain",
        ):
            raise EvaluationContractError("relevance label is invalid")
        confidence = _finite_number(self.confidence, "annotation confidence")
        if confidence < 0.0 or confidence > 1.0:
            raise EvaluationContractError("annotation confidence must be between 0 and 1")
        object.__setattr__(self, "confidence", confidence)
        if not isinstance(self.notes, str):
            raise EvaluationContractError("annotation notes must be a string")
        if self.verification_status not in ("llm_assisted_provisional", "human_verified"):
            raise EvaluationContractError("annotation verification status is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "blind_id": self.blind_id,
            "label": self.label,
            "confidence": self.confidence,
            "notes": self.notes,
            "verification_status": self.verification_status,
        }

    @classmethod
    def from_dict(cls, value: object) -> RelevanceAnnotation:
        payload = _mapping(value, "relevance_annotation")
        return cls(
            blind_id=payload.get("blind_id"),
            label=payload.get("label"),
            confidence=payload.get("confidence"),
            notes=payload.get("notes", ""),
            verification_status=payload.get("verification_status"),
        )


@dataclass(frozen=True)
class RelevanceAnnotationSet:
    """一个 blind packet 的完整标签集合及安全 annotator provenance。"""

    packet_id: str
    snapshot_id: str
    rubric_version: str
    annotator_type: Literal["llm_assisted", "human"]
    annotator_identity: str
    created_at: str
    annotations: tuple[RelevanceAnnotation, ...]

    def __post_init__(self) -> None:
        for name in (
            "packet_id",
            "snapshot_id",
            "rubric_version",
            "annotator_identity",
            "created_at",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.annotator_type not in ("llm_assisted", "human"):
            raise EvaluationContractError("annotator_type is invalid")
        if not isinstance(self.annotations, tuple):
            raise EvaluationContractError("annotations must be a tuple")
        identities = [item.blind_id for item in self.annotations]
        if len(set(identities)) != len(identities):
            raise EvaluationContractError("annotation blind IDs must be unique")
        if self.annotator_type == "llm_assisted" and any(
            item.verification_status != "llm_assisted_provisional" for item in self.annotations
        ):
            raise EvaluationContractError("LLM annotations cannot claim human_verified status")

    @property
    def reference_status(self) -> Literal[
        "llm_assisted_provisional", "human_verified", "mixed"
    ]:
        statuses = {item.verification_status for item in self.annotations}
        if statuses == {"llm_assisted_provisional"}:
            return "llm_assisted_provisional"
        if statuses == {"human_verified"}:
            return "human_verified"
        return "mixed"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": RETRIEVAL_PACKET_SCHEMA_VERSION,
            "packet_id": self.packet_id,
            "snapshot_id": self.snapshot_id,
            "rubric_version": self.rubric_version,
            "annotator_type": self.annotator_type,
            "annotator_identity": self.annotator_identity,
            "created_at": self.created_at,
            "reference_status": self.reference_status,
            "ground_truth_claim": False,
            "annotations": [item.to_dict() for item in self.annotations],
        }

    @classmethod
    def from_dict(cls, value: object) -> RelevanceAnnotationSet:
        payload = _mapping(value, "relevance_annotation_set")
        annotations = payload.get("annotations")
        if not isinstance(annotations, Sequence) or isinstance(annotations, (str, bytes)):
            raise EvaluationContractError("relevance_annotation_set.annotations must be an array")
        return cls(
            packet_id=payload.get("packet_id"),
            snapshot_id=payload.get("snapshot_id"),
            rubric_version=payload.get("rubric_version"),
            annotator_type=payload.get("annotator_type"),
            annotator_identity=payload.get("annotator_identity"),
            created_at=payload.get("created_at"),
            annotations=tuple(RelevanceAnnotation.from_dict(item) for item in annotations),
        )

    @classmethod
    def from_json(cls, path: Path) -> RelevanceAnnotationSet:
        return cls.from_dict(_read_json(path, "relevance annotation set"))


@dataclass(frozen=True)
class RetrievalMetric:
    """一个数值或显式 unavailable reason，missing label 永远不是零。"""

    name: str
    availability: MetricAvailability
    value: float | None
    reason: str | None
    k: int | None
    scope: str
    reference_status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "availability": self.availability,
            "value": self.value,
            "reason": self.reason,
            "k": self.k,
            "scope": self.scope,
            "reference_status": self.reference_status,
        }


ToolInvoker = Callable[
    [str, SearchMessagesInput | SemanticSearchInput, ExecutionScope],
    ToolEnvelope,
]
ContextReader = Callable[[str, str, int, int], tuple[MessageProjection, ...]]
RangeReader = Callable[[str, str, str, int], tuple[MessageProjection, ...]]
SnapshotResolver = Callable[[], DatasetSnapshot]


@dataclass
class _CandidateBuild:
    """生成 packet 时合并两种方法的同一 canonical anchor。"""

    message: MessageProjection
    contexts: dict[str, MessageProjection]
    appearances: list[RetrievalAppearance]


class RetrievalAnnotationWorkflow:
    """复用 Application Tool facade 生成盲标包，不复制 Retrieval 实现。"""

    def __init__(
        self,
        *,
        snapshot_resolver: SnapshotResolver,
        tool_invoker: ToolInvoker,
        context_reader: ContextReader,
        range_reader: RangeReader,
    ) -> None:
        for value in (snapshot_resolver, tool_invoker, context_reader, range_reader):
            if not callable(value):
                raise EvaluationContractError("retrieval annotation workflow requires callables")
        self._snapshot_resolver = snapshot_resolver
        self._tool_invoker = tool_invoker
        self._context_reader = context_reader
        self._range_reader = range_reader

    def generate(
        self,
        query_set: RetrievalQuerySet,
        lexical_variant: ControlledVariant,
        semantic_variant: ControlledVariant,
    ) -> tuple[BlindAnnotationPacket, SealedRetrievalPacket]:
        """在同一 Snapshot 运行两种检索，按 canonical anchor 去重后分离盲标数据。"""

        if not isinstance(query_set, RetrievalQuerySet):
            raise EvaluationContractError("generate requires a RetrievalQuerySet")
        if "lexical_search" not in lexical_variant.available_tools:
            raise EvaluationContractError("lexical variant must expose lexical_search")
        if "semantic_search" not in semantic_variant.available_tools:
            raise EvaluationContractError("semantic variant must expose semantic_search")
        snapshot = self._snapshot_resolver()
        if snapshot.status != "available":
            raise EvaluationContractError(f"retrieval Snapshot is {snapshot.status}")
        if snapshot.snapshot_id != query_set.snapshot_id:
            raise EvaluationContractError(
                "resolved Snapshot does not match retrieval query set; create a new query-set version"
            )

        packet_id = (
            f"retrieval-packet:{query_set.query_set_id}:v{query_set.version}:"
            f"messages={snapshot.message_count}:first={snapshot.relevant_time_range[0]}:"
            f"last={snapshot.relevant_time_range[1]}"
        )
        created_at = utc_now()
        runs: list[RetrievalRunRecord] = []
        diagnostics: list[Mapping[str, object]] = []
        candidates_by_key: dict[tuple[str, str], _CandidateBuild] = {}

        for query in query_set.queries:
            lexical_run = self._run_lexical(
                query,
                lexical_variant,
                candidates_by_key,
            )
            semantic_run = self._run_semantic(
                query,
                semantic_variant,
                candidates_by_key,
            )
            runs.extend((lexical_run, semantic_run))
            diagnostics.append(self._diagnostic(query, lexical_run, semantic_run))

        blind_candidates: list[BlindCandidate] = []
        sealed_candidates: list[SealedCandidate] = []
        grouped_keys: dict[str, list[tuple[str, str]]] = {query.query_id: [] for query in query_set.queries}
        for key in candidates_by_key:
            grouped_keys[key[0]].append(key)
        query_lookup = {item.query_id: item for item in query_set.queries}
        for query in query_set.queries:
            # 时间/identity 排序与检索方法、rank、score 无关，避免 blind ID 暗示来源。
            ordered_keys = sorted(
                grouped_keys[query.query_id],
                key=lambda key: (
                    candidates_by_key[key].message.timestamp,
                    candidates_by_key[key].message.session_id,
                    candidates_by_key[key].message.internal_message_id,
                ),
            )
            for index, key in enumerate(ordered_keys, start=1):
                item = candidates_by_key[key]
                blind_id = f"{query.query_id}:candidate-{index:03d}"
                context = self._bounded_context(tuple(item.contexts.values()), item.message)
                blind_candidates.append(
                    BlindCandidate(
                        blind_id=blind_id,
                        query_id=query.query_id,
                        query=query_lookup[query.query_id].query,
                        candidate=self._message_projection(item.message, candidate=True),
                        context=tuple(
                            self._message_projection(
                                message,
                                candidate=message.internal_message_id
                                == item.message.internal_message_id,
                            )
                            for message in context
                        ),
                    )
                )
                sealed_candidates.append(
                    SealedCandidate(
                        blind_id=blind_id,
                        query_id=query.query_id,
                        canonical_message_id=item.message.internal_message_id,
                        session_id=item.message.session_id,
                        source_message_id=item.message.source_message_id,
                        timestamp=item.message.timestamp,
                        appearances=tuple(sorted(item.appearances, key=lambda value: value.strategy)),
                        context_message_ids=tuple(
                            message.internal_message_id for message in context
                        ),
                    )
                )

        blind = BlindAnnotationPacket(
            packet_id=packet_id,
            query_set_id=query_set.query_set_id,
            query_set_version=query_set.version,
            snapshot_id=snapshot.snapshot_id,
            rubric_version=RETRIEVAL_RUBRIC_VERSION,
            created_at=created_at,
            candidates=tuple(blind_candidates),
        )
        sealed = SealedRetrievalPacket(
            packet_id=packet_id,
            query_set=query_set,
            snapshot=snapshot,
            lexical_variant=lexical_variant,
            semantic_variant=semantic_variant,
            created_at=created_at,
            runs=tuple(runs),
            candidates=tuple(sealed_candidates),
            diagnostics=tuple(diagnostics),
        )
        return blind, sealed

    def _run_lexical(
        self,
        query: RetrievalEvaluationQuery,
        variant: ControlledVariant,
        candidates: dict[tuple[str, str], _CandidateBuild],
    ) -> RetrievalRunRecord:
        """运行 lexical control，并把 FTS hit message 作为 canonical candidate。"""

        request = SearchMessagesInput(
            keyword=query.lexical_query,
            session_ids=query.scope.allowed_session_ids,
            start_timestamp=query.scope.start_timestamp,
            end_timestamp=query.scope.end_timestamp,
            limit=query.candidate_limit,
            context_before=query.context_before,
            context_after=query.context_after,
        )
        envelope = self._tool_invoker("lexical_search", request, query.scope)
        result = self._require_result(envelope, query.query_id, "lexical")
        if not isinstance(result, RetrievalResult):
            raise EvaluationContractError("lexical_search returned a non-lexical result")

        ranked: list[str] = []
        for source_rank, hit in enumerate(result.hits, start=1):
            message = hit.message
            if message.internal_message_id in ranked:
                continue
            ranked.append(message.internal_message_id)
            context = self._context_reader(
                message.session_id,
                message.internal_message_id,
                query.context_before,
                query.context_after,
            )
            self._merge_candidate(
                candidates,
                query.query_id,
                message,
                context,
                RetrievalAppearance(
                    strategy="lexical",
                    rank=len(ranked),
                    source_rank=source_rank,
                    score=hit.score,
                    score_type=hit.score_type,
                    hit_identity=message.internal_message_id,
                ),
            )
        return RetrievalRunRecord(
            query_id=query.query_id,
            strategy="lexical",
            variant_id=variant.variant_id,
            variant_identity=variant.identity,
            ranked_candidate_ids=tuple(ranked),
            expanded_message_ids=self._unique_message_ids(result.expanded_messages),
            total_hits=result.total_hits,
            latency_ms=result.metadata.latency_ms,
            coverage_status=result.coverage.status,
            coverage_basis=result.coverage.basis,
            partial=result.partial,
            truncated=result.truncated,
            parameters=request.__dict__,
            index_identity=variant.index_identity,
        )

    def _run_semantic(
        self,
        query: RetrievalEvaluationQuery,
        variant: ControlledVariant,
        candidates: dict[tuple[str, str], _CandidateBuild],
    ) -> RetrievalRunRecord:
        """运行 semantic candidate；每个 child 选首个非 void canonical message 作盲标 anchor。"""

        request = SemanticSearchInput(
            query=query.query,
            session_ids=query.scope.allowed_session_ids,
            start_timestamp=query.scope.start_timestamp,
            end_timestamp=query.scope.end_timestamp,
            limit=query.candidate_limit,
            context_before=query.context_before,
            context_after=query.context_after,
            dense_top_k=query.dense_top_k,
        )
        envelope = self._tool_invoker("semantic_search", request, query.scope)
        result = self._require_result(envelope, query.query_id, "semantic")
        if not isinstance(result, SemanticRetrievalResult):
            raise EvaluationContractError("semantic_search returned a non-semantic result")

        ranked: list[str] = []
        for hit in result.hits:
            core = self._range_reader(
                hit.session_id,
                hit.start_message_id,
                hit.end_message_id,
                64,
            )
            if (
                not core
                or core[0].internal_message_id != hit.start_message_id
                or core[-1].internal_message_id != hit.end_message_id
            ):
                raise EvaluationContractError(
                    f"semantic range could not be recovered for query {query.query_id}"
                )
            anchor = next(
                (
                    message
                    for message in core
                    if not is_semantic_void(SemanticMessage.from_projection(message))
                ),
                core[0],
            )
            if anchor.internal_message_id in ranked:
                continue
            ranked.append(anchor.internal_message_id)
            context = self._semantic_context(core, query.context_before, query.context_after)
            self._merge_candidate(
                candidates,
                query.query_id,
                anchor,
                context,
                RetrievalAppearance(
                    strategy="semantic",
                    rank=len(ranked),
                    source_rank=hit.dense_rank,
                    score=hit.score,
                    score_type=hit.score_type,
                    hit_identity=hit.chunk_id,
                ),
            )
        index_identity = (
            result.hits[0].index_identity if result.hits else variant.index_identity
        )
        return RetrievalRunRecord(
            query_id=query.query_id,
            strategy="semantic",
            variant_id=variant.variant_id,
            variant_identity=variant.identity,
            ranked_candidate_ids=tuple(ranked),
            expanded_message_ids=self._unique_message_ids(result.expanded_messages),
            total_hits=result.total_hits,
            latency_ms=result.metadata.latency_ms,
            coverage_status=result.coverage.status,
            coverage_basis=result.coverage.basis,
            partial=result.partial,
            truncated=result.truncated,
            parameters=request.__dict__,
            index_identity=index_identity,
        )

    @staticmethod
    def _require_result(
        envelope: ToolEnvelope,
        query_id: str,
        strategy: RetrievalStrategy,
    ) -> RetrievalResult | SemanticRetrievalResult:
        """把 Tool error 保留为 Evaluation failure，不跳到另一种检索方法。"""

        if envelope.error is not None:
            raise EvaluationContractError(
                f"{strategy} retrieval failed for {query_id}: {envelope.error.code}"
            )
        if envelope.data is None:
            raise EvaluationContractError(
                f"{strategy} retrieval returned no result for {query_id}"
            )
        if not isinstance(envelope.data, (RetrievalResult, SemanticRetrievalResult)):
            raise EvaluationContractError(
                f"{strategy} retrieval returned an unsupported result for {query_id}"
            )
        return envelope.data

    @staticmethod
    def _merge_candidate(
        candidates: dict[tuple[str, str], _CandidateBuild],
        query_id: str,
        message: MessageProjection,
        context: Sequence[MessageProjection],
        appearance: RetrievalAppearance,
    ) -> None:
        """同 query/canonical ID 只标一次，同时保留两种 sealed appearance。"""

        key = (query_id, message.internal_message_id)
        item = candidates.get(key)
        if item is None:
            item = _CandidateBuild(message=message, contexts={}, appearances=[])
            candidates[key] = item
        if item.message != message:
            raise EvaluationContractError("canonical candidate projection changed within one packet")
        if any(existing.strategy == appearance.strategy for existing in item.appearances):
            raise EvaluationContractError("one candidate appeared twice in the same strategy ranking")
        item.appearances.append(appearance)
        for context_message in context:
            if context_message.session_id != message.session_id:
                raise EvaluationContractError("candidate context crossed session boundary")
            item.contexts[context_message.internal_message_id] = context_message
        item.contexts[message.internal_message_id] = message

    def _semantic_context(
        self,
        core: Sequence[MessageProjection],
        before: int,
        after: int,
    ) -> tuple[MessageProjection, ...]:
        """保留完整 child core，并只从两端读取 bounded surrounding context。"""

        merged = {message.internal_message_id: message for message in core}
        if before:
            for message in self._context_reader(
                core[0].session_id,
                core[0].internal_message_id,
                before,
                0,
            ):
                merged[message.internal_message_id] = message
        if after:
            for message in self._context_reader(
                core[-1].session_id,
                core[-1].internal_message_id,
                0,
                after,
            ):
                merged[message.internal_message_id] = message
        return tuple(sorted(merged.values(), key=message_sort_key))

    @staticmethod
    def _bounded_context(
        messages: Sequence[MessageProjection],
        candidate: MessageProjection,
    ) -> tuple[MessageProjection, ...]:
        """优先保留首尾跨度与 candidate 邻域，把单个盲标输入限制为十条消息。"""

        ordered = tuple(sorted({item.internal_message_id: item for item in messages}.values(), key=message_sort_key))
        if len(ordered) <= _CONTEXT_MESSAGE_LIMIT:
            return ordered
        candidate_index = next(
            index
            for index, item in enumerate(ordered)
            if item.internal_message_id == candidate.internal_message_id
        )
        selected_ids = {
            item.internal_message_id for item in (*ordered[:3], *ordered[-3:])
        }
        neighborhood_start = max(0, candidate_index - 2)
        neighborhood_end = min(len(ordered), candidate_index + 3)
        selected_ids.update(
            item.internal_message_id for item in ordered[neighborhood_start:neighborhood_end]
        )
        selected = [item for item in ordered if item.internal_message_id in selected_ids]
        if len(selected) > _CONTEXT_MESSAGE_LIMIT:
            selected = selected[: _CONTEXT_MESSAGE_LIMIT - 1]
            if candidate not in selected:
                selected.append(candidate)
        return tuple(sorted(selected, key=message_sort_key))

    @staticmethod
    def _message_projection(
        message: MessageProjection,
        *,
        candidate: bool,
    ) -> dict[str, object]:
        """输出 local-only bounded 正文，并显式标出是否发生内容截断。"""

        content = message.normalized_content
        return {
            "canonical_message_id": message.internal_message_id,
            "session_id": message.session_id,
            "session_display": message.session_display,
            "source_message_id": message.source_message_id,
            "sender_name": message.sender_name,
            "timestamp": message.timestamp,
            "message_type": message.message_type,
            "content": content[:_MESSAGE_CONTENT_LIMIT],
            "content_truncated": len(content) > _MESSAGE_CONTENT_LIMIT,
            "is_candidate": candidate,
        }

    @staticmethod
    def _unique_message_ids(messages: Sequence[MessageProjection]) -> tuple[str, ...]:
        """按首次出现顺序去重 expanded context IDs。"""

        seen: set[str] = set()
        output: list[str] = []
        for item in messages:
            if item.internal_message_id in seen:
                continue
            seen.add(item.internal_message_id)
            output.append(item.internal_message_id)
        return tuple(output)

    @staticmethod
    def _diagnostic(
        query: RetrievalEvaluationQuery,
        lexical: RetrievalRunRecord,
        semantic: RetrievalRunRecord,
    ) -> Mapping[str, object]:
        """计算无需 relevance label 的 overlap/rank/latency 诊断，不输出质量判断。"""

        lexical_ids = set(lexical.ranked_candidate_ids)
        semantic_ids = set(semantic.ranked_candidate_ids)
        overlap = lexical_ids & semantic_ids
        lexical_rank = {
            message_id: rank
            for rank, message_id in enumerate(lexical.ranked_candidate_ids, start=1)
        }
        semantic_rank = {
            message_id: rank
            for rank, message_id in enumerate(semantic.ranked_candidate_ids, start=1)
        }
        displacements = [
            abs(lexical_rank[message_id] - semantic_rank[message_id])
            for message_id in overlap
        ]
        return {
            "query_id": query.query_id,
            "diagnostic_only": True,
            "lexical_result_count": len(lexical.ranked_candidate_ids),
            "semantic_result_count": len(semantic.ranked_candidate_ids),
            "overlap_count": len(overlap),
            "lexical_unique_count": len(lexical_ids - semantic_ids),
            "semantic_unique_count": len(semantic_ids - lexical_ids),
            "mean_rank_displacement": (
                None if not displacements else sum(displacements) / len(displacements)
            ),
            "lexical_latency_ms": lexical.latency_ms,
            "semantic_latency_ms": semantic.latency_ms,
            "lexical_partial": lexical.partial,
            "semantic_partial": semantic.partial,
            "lexical_truncated": lexical.truncated,
            "semantic_truncated": semantic.truncated,
            "lexical_expanded_message_count": len(lexical.expanded_message_ids),
            "semantic_expanded_message_count": len(semantic.expanded_message_ids),
        }


def _available_metric(
    name: str,
    value: float,
    *,
    k: int | None,
    scope: str,
    reference_status: str,
) -> RetrievalMetric:
    """构造可用数值，并统一保留标签 provenance。"""

    return RetrievalMetric(
        name=name,
        availability="available",
        value=value,
        reason=None,
        k=k,
        scope=scope,
        reference_status=reference_status,
    )


def _unavailable_metric(
    name: str,
    reason: str,
    *,
    k: int | None,
    scope: str,
    reference_status: str,
) -> RetrievalMetric:
    """缺标签或 denominator 不成立时显式 unavailable，绝不返回伪零。"""

    return RetrievalMetric(
        name=name,
        availability="unavailable",
        value=None,
        reason=reason,
        k=k,
        scope=scope,
        reference_status=reference_status,
    )


def _deduplicate_ranked(values: Sequence[str]) -> tuple[tuple[str, ...], int]:
    """只保留首次出现位置，duplicate 不得重复贡献 Precision/Recall。"""

    seen: set[str] = set()
    output: list[str] = []
    duplicates = 0
    for value in values:
        if value in seen:
            duplicates += 1
            continue
        seen.add(value)
        output.append(value)
    return tuple(output), duplicates


def _resolved_annotation(
    label_by_message: Mapping[str, RelevanceAnnotation | None],
    message_id: str,
) -> bool:
    annotation = label_by_message.get(message_id)
    return annotation is not None and annotation.label in _RESOLVED_LABELS


def _has_label(
    label_by_message: Mapping[str, RelevanceAnnotation | None],
    message_id: str,
    label: RelevanceLabel,
) -> bool:
    """在一个局部变量内完成 None narrowing，供指标计数复用。"""

    annotation = label_by_message.get(message_id)
    return annotation is not None and annotation.label == label


def _strategy_query_metrics(
    run: RetrievalRunRecord,
    label_by_message: Mapping[str, RelevanceAnnotation | None],
    *,
    pool_complete: bool,
    relevant_total: int,
    partial_total: int,
    ks: Sequence[int],
    reference_status: str,
) -> tuple[list[RetrievalMetric], dict[str, object]]:
    """按保守语义计算单 query/strategy 指标。"""

    ranked, duplicate_count = _deduplicate_ranked(run.ranked_candidate_ids)
    metrics: list[RetrievalMetric] = []
    for k in ks:
        top = ranked[:k]
        top_resolved = all(_resolved_annotation(label_by_message, item) for item in top)
        if top_resolved:
            relevant_hits = sum(
                1
                for item in top
                if _has_label(label_by_message, item, "relevant")
            )
            metrics.append(
                _available_metric(
                    "precision_at_k",
                    relevant_hits / k,
                    k=k,
                    scope="retrieved_top_k",
                    reference_status=reference_status,
                )
            )
        else:
            metrics.append(
                _unavailable_metric(
                    "precision_at_k",
                    "top_k_contains_missing_or_uncertain_label",
                    k=k,
                    scope="retrieved_top_k",
                    reference_status=reference_status,
                )
            )

        if not pool_complete:
            recall = _unavailable_metric(
                "recall_at_k",
                "merged_candidate_pool_has_missing_or_uncertain_label",
                k=k,
                scope="merged_candidate_pool",
                reference_status=reference_status,
            )
            hit = _unavailable_metric(
                "top_k_hit_success",
                "merged_candidate_pool_has_missing_or_uncertain_label",
                k=k,
                scope="merged_candidate_pool",
                reference_status=reference_status,
            )
        elif relevant_total == 0:
            recall = _unavailable_metric(
                "recall_at_k",
                "no_relevant_candidate_in_annotated_pool",
                k=k,
                scope="merged_candidate_pool",
                reference_status=reference_status,
            )
            hit = _unavailable_metric(
                "top_k_hit_success",
                "no_relevant_candidate_in_annotated_pool",
                k=k,
                scope="merged_candidate_pool",
                reference_status=reference_status,
            )
        else:
            relevant_hits = sum(
                1
                for item in top
                if _has_label(label_by_message, item, "relevant")
            )
            recall = _available_metric(
                "recall_at_k",
                relevant_hits / relevant_total,
                k=k,
                scope="merged_candidate_pool",
                reference_status=reference_status,
            )
            hit = _available_metric(
                "top_k_hit_success",
                1.0 if relevant_hits else 0.0,
                k=k,
                scope="merged_candidate_pool",
                reference_status=reference_status,
            )
        metrics.extend((recall, hit))

    ranked_resolved = all(_resolved_annotation(label_by_message, item) for item in ranked)
    if not pool_complete:
        metrics.append(
            _unavailable_metric(
                "mrr",
                "merged_candidate_pool_has_missing_or_uncertain_label",
                k=None,
                scope="retrieved_ranking",
                reference_status=reference_status,
            )
        )
    elif relevant_total == 0:
        metrics.append(
            _unavailable_metric(
                "mrr",
                "no_relevant_candidate_in_annotated_pool",
                k=None,
                scope="retrieved_ranking",
                reference_status=reference_status,
            )
        )
    elif not ranked_resolved:
        metrics.append(
            _unavailable_metric(
                "mrr",
                "retrieved_ranking_contains_missing_or_uncertain_label",
                k=None,
                scope="retrieved_ranking",
                reference_status=reference_status,
            )
        )
    else:
        reciprocal_rank = 0.0
        for rank, message_id in enumerate(ranked, start=1):
            annotation = label_by_message[message_id]
            if annotation is not None and annotation.label == "relevant":
                reciprocal_rank = 1.0 / rank
                break
        metrics.append(
            _available_metric(
                "mrr",
                reciprocal_rank,
                k=None,
                scope="retrieved_ranking",
                reference_status=reference_status,
            )
        )

    if not pool_complete:
        relevant_coverage = _unavailable_metric(
            "relevant_message_coverage",
            "merged_candidate_pool_has_missing_or_uncertain_label",
            k=None,
            scope="merged_candidate_pool",
            reference_status=reference_status,
        )
        partial_coverage = _unavailable_metric(
            "partial_relevant_coverage",
            "merged_candidate_pool_has_missing_or_uncertain_label",
            k=None,
            scope="merged_candidate_pool",
            reference_status=reference_status,
        )
    else:
        retrieved_relevant = sum(
            1
            for item in ranked
            if _has_label(label_by_message, item, "relevant")
        )
        relevant_coverage = (
            _unavailable_metric(
                "relevant_message_coverage",
                "no_relevant_candidate_in_annotated_pool",
                k=None,
                scope="merged_candidate_pool",
                reference_status=reference_status,
            )
            if relevant_total == 0
            else _available_metric(
                "relevant_message_coverage",
                retrieved_relevant / relevant_total,
                k=None,
                scope="merged_candidate_pool",
                reference_status=reference_status,
            )
        )
        retrieved_partial = sum(
            1
            for item in ranked
            if _has_label(label_by_message, item, "partially_relevant")
        )
        partial_coverage = (
            _unavailable_metric(
                "partial_relevant_coverage",
                "no_partially_relevant_candidate_in_annotated_pool",
                k=None,
                scope="merged_candidate_pool",
                reference_status=reference_status,
            )
            if partial_total == 0
            else _available_metric(
                "partial_relevant_coverage",
                retrieved_partial / partial_total,
                k=None,
                scope="merged_candidate_pool",
                reference_status=reference_status,
            )
        )
    metrics.extend((relevant_coverage, partial_coverage))
    diagnostics = {
        "retrieved_unique_candidates": len(ranked),
        "duplicate_candidate_count": duplicate_count,
        "latency_ms": run.latency_ms,
        "partial": run.partial,
        "truncated": run.truncated,
        "coverage_status": run.coverage_status,
    }
    return metrics, diagnostics


def _aggregate_metrics(
    query_results: Sequence[Mapping[str, object]],
    strategy: RetrievalStrategy,
) -> list[dict[str, object]]:
    """对同名可用指标做 macro average，并显示可评测 query 数。"""

    grouped: dict[tuple[str, int | None, str], list[RetrievalMetric]] = {}
    for query_result in query_results:
        strategies = query_result["strategies"]
        if not isinstance(strategies, Mapping):
            raise EvaluationContractError("query metric strategies are invalid")
        strategy_result = strategies[strategy]
        if not isinstance(strategy_result, Mapping):
            raise EvaluationContractError("query strategy metrics are invalid")
        values = strategy_result["metrics"]
        if not isinstance(values, Sequence):
            raise EvaluationContractError("query strategy metric list is invalid")
        for metric in values:
            if not isinstance(metric, RetrievalMetric):
                raise EvaluationContractError("query strategy metric item is invalid")
            grouped.setdefault((metric.name, metric.k, metric.scope), []).append(metric)

    output: list[dict[str, object]] = []
    total_queries = len(query_results)
    for key in sorted(grouped, key=lambda item: (item[0], -1 if item[1] is None else item[1], item[2])):
        values = grouped[key]
        available = [item.value for item in values if item.availability == "available"]
        numeric = [item for item in available if item is not None]
        if len(numeric) == total_queries:
            availability: MetricAvailability = "available"
        elif numeric:
            availability = "partial"
        else:
            availability = "unavailable"
        output.append(
            {
                "name": key[0],
                "k": key[1],
                "scope": key[2],
                "availability": availability,
                "macro_value": None if not numeric else sum(numeric) / len(numeric),
                "evaluable_queries": len(numeric),
                "total_queries": total_queries,
                "unavailable_reasons": sorted(
                    {
                        item.reason
                        for item in values
                        if item.availability == "unavailable" and item.reason is not None
                    }
                ),
            }
        )
    return output


def build_retrieval_metrics(
    sealed: SealedRetrievalPacket,
    annotations: RelevanceAnnotationSet,
    *,
    ks: Sequence[int] = (1, 3, 5, 8),
) -> dict[str, object]:
    """基于完整盲标映射计算 paired metrics；corpus Recall 始终单独声明。"""

    if sealed.packet_id != annotations.packet_id:
        raise EvaluationContractError("annotation packet identity does not match sealed metadata")
    if sealed.snapshot.snapshot_id != annotations.snapshot_id:
        raise EvaluationContractError("annotation Snapshot does not match sealed metadata")
    if annotations.rubric_version != RETRIEVAL_RUBRIC_VERSION:
        raise EvaluationContractError("annotation rubric version does not match retrieval evaluator")
    normalized_ks = tuple(_positive_integer(value, "metric k") for value in ks)
    if len(set(normalized_ks)) != len(normalized_ks):
        raise EvaluationContractError("metric k values must be unique")

    annotations_by_blind = {item.blind_id: item for item in annotations.annotations}
    sealed_blind_ids = {item.blind_id for item in sealed.candidates}
    extra_labels = set(annotations_by_blind) - sealed_blind_ids
    if extra_labels:
        raise EvaluationContractError("annotation set contains IDs outside the sealed packet")
    candidate_keys = {
        (item.query_id, item.canonical_message_id): item for item in sealed.candidates
    }
    for run in sealed.runs:
        missing_candidates = {
            message_id
            for message_id in run.ranked_candidate_ids
            if (run.query_id, message_id) not in candidate_keys
        }
        if missing_candidates:
            raise EvaluationContractError("retrieval run references a candidate outside sealed metadata")

    query_results: list[Mapping[str, object]] = []
    for query in sealed.query_set.queries:
        query_candidates = [item for item in sealed.candidates if item.query_id == query.query_id]
        label_by_message: dict[str, RelevanceAnnotation | None] = {
            item.canonical_message_id: annotations_by_blind.get(item.blind_id)
            for item in query_candidates
        }
        pool_complete = all(
            annotation is not None and annotation.label in _RESOLVED_LABELS
            for annotation in label_by_message.values()
        )
        relevant_total = sum(
            1
            for annotation in label_by_message.values()
            if annotation is not None and annotation.label == "relevant"
        )
        partial_total = sum(
            1
            for annotation in label_by_message.values()
            if annotation is not None and annotation.label == "partially_relevant"
        )
        unresolved_count = sum(
            1
            for annotation in label_by_message.values()
            if annotation is None or annotation.label == "uncertain"
        )
        strategies: dict[str, object] = {}
        for strategy in ("lexical", "semantic"):
            selected_run = next(
                (
                    item
                    for item in sealed.runs
                    if item.query_id == query.query_id and item.strategy == strategy
                ),
                None,
            )
            if selected_run is None:
                raise EvaluationContractError(
                    f"sealed packet is missing {strategy} run for {query.query_id}"
                )
            metrics, diagnostic = _strategy_query_metrics(
                selected_run,
                label_by_message,
                pool_complete=pool_complete,
                relevant_total=relevant_total,
                partial_total=partial_total,
                ks=normalized_ks,
                reference_status=annotations.reference_status,
            )
            strategies[strategy] = {"metrics": metrics, "diagnostics": diagnostic}
        query_results.append(
            {
                "query_id": query.query_id,
                "query_types": list(query.query_types),
                "diagnostic_query": query.diagnostic,
                "annotated_candidate_count": len(query_candidates),
                "relevant_candidate_count": relevant_total,
                "partially_relevant_candidate_count": partial_total,
                "unresolved_candidate_count": unresolved_count,
                "pool_complete": pool_complete,
                "strategies": strategies,
            }
        )

    serialized_queries: list[dict[str, object]] = []
    for item in query_results:
        strategy_payload: dict[str, object] = {}
        strategy_values = item["strategies"]
        if not isinstance(strategy_values, Mapping):
            raise EvaluationContractError("query strategies are invalid")
        for strategy, value in strategy_values.items():
            if not isinstance(value, Mapping):
                raise EvaluationContractError("query strategy value is invalid")
            metric_values = value["metrics"]
            if not isinstance(metric_values, Sequence):
                raise EvaluationContractError("query metrics are invalid")
            strategy_payload[str(strategy)] = {
                "metrics": [metric.to_dict() for metric in metric_values],
                "diagnostics": dict(value["diagnostics"]),
            }
        serialized_queries.append(
            {
                key: value
                for key, value in item.items()
                if key != "strategies"
            }
            | {"strategies": strategy_payload}
        )

    # 安全报告只聚合标签与 confidence，不带 notes、正文或 canonical message IDs。
    label_counts = {
        label: sum(1 for item in annotations.annotations if item.label == label)
        for label in ("relevant", "partially_relevant", "not_relevant", "uncertain")
    }
    verification_counts = {
        status: sum(
            1 for item in annotations.annotations if item.verification_status == status
        )
        for status in ("llm_assisted_provisional", "human_verified")
    }
    confidences = [item.confidence for item in annotations.annotations]

    return {
        "schema_version": RETRIEVAL_PACKET_SCHEMA_VERSION,
        "report_id": f"retrieval-metrics:{sealed.query_set.query_set_id}:v{sealed.query_set.version}",
        "created_at": utc_now(),
        "query_set_id": sealed.query_set.query_set_id,
        "query_set_version": sealed.query_set.version,
        "snapshot_id": sealed.snapshot.snapshot_id,
        "reference_status": annotations.reference_status,
        "metric_status": annotations.reference_status,
        "ground_truth_claim": False,
        "annotation_provenance": {
            "annotator_type": annotations.annotator_type,
            "annotator_identity": annotations.annotator_identity,
            "rubric_version": annotations.rubric_version,
            "annotation_count": len(annotations.annotations),
            "label_counts": label_counts,
            "verification_counts": verification_counts,
            "confidence": {
                "minimum": min(confidences) if confidences else None,
                "mean": (
                    sum(confidences) / len(confidences) if confidences else None
                ),
                "maximum": max(confidences) if confidences else None,
            },
        },
        "warning": (
            "These are LLM-assisted provisional metrics, not human ground truth."
            if annotations.reference_status != "human_verified"
            else "Metrics use human-verified labels."
        ),
        "recall_scope": "merged lexical+semantic candidate pool at the configured depth",
        "corpus_recall": {
            "availability": "unavailable",
            "reason": "reference is not corpus-exhaustive",
        },
        "lexical_variant_id": sealed.lexical_variant.variant_id,
        "semantic_variant_id": sealed.semantic_variant.variant_id,
        "queries": serialized_queries,
        "aggregate": {
            "lexical": _aggregate_metrics(query_results, "lexical"),
            "semantic": _aggregate_metrics(query_results, "semantic"),
        },
        "retrieval_diagnostics": [dict(item) for item in sealed.diagnostics],
    }


def build_retrieval_audit_queue(
    sealed: SealedRetrievalPacket,
    annotations: RelevanceAnnotationSet,
    *,
    confidence_threshold: float = 0.8,
) -> dict[str, object]:
    """按不确定性和指标影响生成 local-only 人工抽查队列。"""

    threshold = _finite_number(confidence_threshold, "audit confidence threshold")
    if threshold <= 0.0 or threshold > 1.0:
        raise EvaluationContractError("audit confidence threshold must be in (0, 1]")
    if sealed.packet_id != annotations.packet_id:
        raise EvaluationContractError("audit annotation packet does not match sealed metadata")
    annotation_by_id = {item.blind_id: item for item in annotations.annotations}
    items: list[dict[str, object]] = []
    for candidate in sealed.candidates:
        annotation = annotation_by_id.get(candidate.blind_id)
        reasons: list[str] = []
        if annotation is None:
            reasons.append("missing_annotation")
            label = None
            confidence = None
        else:
            label = annotation.label
            confidence = annotation.confidence
            if annotation.confidence < threshold:
                reasons.append("low_confidence")
            if annotation.label == "uncertain":
                reasons.append("uncertain_label")
            if annotation.label == "partially_relevant":
                reasons.append("partial_relevance_boundary")
            if annotation.label == "relevant":
                reasons.append("positive_metric_impact")
        ranks = {item.strategy: item.rank for item in candidate.appearances}
        if len(ranks) == 1 and min(ranks.values()) <= 3:
            reasons.append("top_rank_unique_to_one_strategy")
        if len(ranks) == 2 and abs(ranks["lexical"] - ranks["semantic"]) >= 4:
            reasons.append("large_rank_displacement")
        if not reasons:
            continue
        high_priority = (
            "missing_annotation" in reasons
            or "uncertain_label" in reasons
            or (confidence is not None and confidence < 0.6)
            or (
                label == "relevant"
                and any(item.rank <= 3 for item in candidate.appearances)
            )
        )
        medium_priority = (
            "low_confidence" in reasons
            or "partial_relevance_boundary" in reasons
            or "top_rank_unique_to_one_strategy" in reasons
        )
        priority = "high" if high_priority else "medium" if medium_priority else "low"
        items.append(
            {
                "blind_id": candidate.blind_id,
                "query_id": candidate.query_id,
                "canonical_message_id": candidate.canonical_message_id,
                "label": label,
                "confidence": confidence,
                "priority": priority,
                "reasons": reasons,
                "review_status": "pending_human_review",
            }
        )
    priority_order = {"high": 0, "medium": 1, "low": 2}
    items.sort(
        key=lambda item: (
            priority_order[str(item["priority"])],
            str(item["query_id"]),
            str(item["blind_id"]),
        )
    )
    return {
        "schema_version": RETRIEVAL_PACKET_SCHEMA_VERSION,
        "packet_id": sealed.packet_id,
        "snapshot_id": sealed.snapshot.snapshot_id,
        "reference_status": annotations.reference_status,
        "annotator_identity": annotations.annotator_identity,
        "rubric_version": annotations.rubric_version,
        "created_at": utc_now(),
        "confidence_threshold": threshold,
        "queue_count": len(items),
        "priority_counts": {
            priority: sum(1 for item in items if item["priority"] == priority)
            for priority in ("high", "medium", "low")
        },
        "items": items,
    }
