"""Capability / Tool 的最小业务 contract。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, Mapping, Sequence

from trivae.retrieval.structured import RetrievalResult


class CapabilityContractError(Exception):
    """调用输入或 trusted execution scope 违反 Capability contract。"""

    error_code = "INVALID_ARGUMENT"


class CapabilityScopeError(CapabilityContractError):
    """调用方试图读取 trusted data access scope 之外的数据。"""

    error_code = "SCOPE_VIOLATION"


def _normalize_scope_sessions(values: Sequence[str] | None) -> tuple[str, ...] | None:
    """把 trusted session scope 归一化，避免后续集合比较依赖输入容器类型。"""

    if values is None:
        return None
    if isinstance(values, str):
        raise CapabilityContractError("session scope must be a sequence")
    normalized = tuple(values)
    if not normalized or any(not isinstance(value, str) or not value for value in normalized):
        raise CapabilityContractError("session scope must contain non-empty session IDs")
    return normalized


def _validate_optional_timestamp(name: str, value: int | None) -> None:
    """Capability scope 与 input 都沿用 canonical integer timestamp。"""

    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise CapabilityContractError(f"{name} must be an integer timestamp or None")


@dataclass(frozen=True)
class ExecutionScope:
    """由 Application/Runtime 派生的 trusted data access scope。"""

    allowed_session_ids: tuple[str, ...] | None = None
    start_timestamp: int | None = None
    end_timestamp: int | None = None
    max_results: int = 20

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_session_ids", _normalize_scope_sessions(self.allowed_session_ids))
        _validate_optional_timestamp("start_timestamp", self.start_timestamp)
        _validate_optional_timestamp("end_timestamp", self.end_timestamp)
        if self.start_timestamp is not None and self.end_timestamp is not None:
            if self.start_timestamp > self.end_timestamp:
                raise CapabilityContractError("trusted time scope is reversed")
        if isinstance(self.max_results, bool) or not isinstance(self.max_results, int) or self.max_results <= 0:
            raise CapabilityContractError("trusted max_results must be positive")


@dataclass(frozen=True)
class SearchMessagesInput:
    """search_messages 的输入字段；scope enforcement 不由普通参数自行完成。"""

    keyword: str
    session_ids: tuple[str, ...] | None = None
    start_timestamp: int | None = None
    end_timestamp: int | None = None
    sender_user_ids: tuple[str, ...] | None = None
    message_types: tuple[str, ...] | None = None
    limit: int = 20
    context_before: int = 2
    context_after: int = 2

    def __post_init__(self) -> None:
        if not isinstance(self.keyword, str):
            raise CapabilityContractError("keyword must be a string")
        object.__setattr__(self, "session_ids", _normalize_scope_sessions(self.session_ids))
        _validate_optional_timestamp("start_timestamp", self.start_timestamp)
        _validate_optional_timestamp("end_timestamp", self.end_timestamp)
        if self.start_timestamp is not None and self.end_timestamp is not None:
            if self.start_timestamp > self.end_timestamp:
                raise CapabilityContractError("query time scope is reversed")
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or self.limit <= 0:
            raise CapabilityContractError("limit must be positive")
        for name, value in (("context_before", self.context_before), ("context_after", self.context_after)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CapabilityContractError(f"{name} must be non-negative")


@dataclass(frozen=True)
class CapabilityMetadata:
    """Agent-facing capability metadata，不绑定 SDK 类型。"""

    name: str
    description: str
    bounded: bool
    input_fields: tuple[str, ...]


@dataclass(frozen=True)
class ToolError:
    """统一 Tool envelope 的可见错误。"""

    code: str
    message: str


@dataclass(frozen=True)
class ToolEnvelope:
    """统一表达 ok/partial/error 与 truncation 的薄 envelope。"""

    status: Literal["ok", "partial", "error"]
    data: RetrievalResult | None
    meta: Mapping[str, object]
    error: ToolError | None

    def to_dict(self) -> dict[str, object]:
        """为测试/接口适配提供普通字典，不把 SQLite 对象带入结果。"""

        data: object | None
        if self.data is None:
            data = None
        else:
            data = {
                "strategy": self.data.strategy,
                "query": self.data.query.to_dict(),
                "filters": dict(self.data.filters),
                "hits": [
                    {
                        "message": asdict(hit.message),
                        "matched_terms": hit.matched_terms,
                        "score": hit.score,
                        "score_type": hit.score_type,
                    }
                    for hit in self.data.hits
                ],
                "expanded_messages": [asdict(message) for message in self.data.expanded_messages],
                "total_hits": self.data.total_hits,
                "returned_messages": self.data.returned_messages,
                "coverage": asdict(self.data.coverage),
                "partial": self.data.partial,
                "truncated": self.data.truncated,
                "metadata": {
                    "filters": dict(self.data.metadata.filters),
                    "ordering": self.data.metadata.ordering,
                    "latency_ms": self.data.metadata.latency_ms,
                    "details": dict(self.data.metadata.details),
                },
            }
        return {
            "status": self.status,
            "data": data,
            "meta": dict(self.meta),
            "error": None if self.error is None else asdict(self.error),
        }
