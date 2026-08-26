"""Retrieval Core 的读取契约与 Structured/Lexical 结果类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Iterator, Literal, Mapping, Protocol, Sequence

from trivae.config.limits import (
    DEFAULT_LEXICAL_RESULT_LIMIT,
    DEFAULT_STRUCTURED_RESULT_LIMIT,
    MAX_LEXICAL_RESULT_LIMIT,
    MAX_STRUCTURED_RESULT_ITEMS,
)


class RetrievalError(Exception):
    """Retrieval 层能够向上层明确投影的错误基类。"""

    error_code = "RETRIEVAL_ERROR"


class InvalidRetrievalQuery(RetrievalError, ValueError):
    """查询字段违反 Retrieval Contract。"""

    error_code = "RETRIEVAL_INVALID_QUERY"


class LexicalIndexError(RetrievalError):
    """Lexical derived index 不可用或与 canonical facts 不一致。"""

    error_code = "RETRIEVAL_LEXICAL_INDEX"


CoverageStatus = Literal["complete", "partial", "none", "unknown", "not_applicable"]
Strategy = Literal["structured", "lexical", "semantic"]
GroupBy = Literal["session", "sender", "month"]

ORDERING_DESCRIPTION = (
    "timestamp ASC, present seq ASC, missing seq after present seq, internal_message_id ASC"
)


def _normalize_filter(name: str, values: Sequence[str] | None) -> tuple[str, ...] | None:
    """把查询过滤归一化为可重复使用的 tuple，并拒绝无意义的空值。"""

    if values is None:
        return None
    if isinstance(values, str):
        raise InvalidRetrievalQuery(f"{name} must be a sequence of non-empty strings")
    normalized = tuple(values)
    if not normalized or any(not isinstance(value, str) or not value for value in normalized):
        raise InvalidRetrievalQuery(f"{name} must contain non-empty strings")
    return normalized


def _validate_timestamp(name: str, value: int | None) -> None:
    """时间过滤必须继续使用 M1 canonical 的整数毫秒语义。"""

    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise InvalidRetrievalQuery(f"{name} must be an integer timestamp or None")


def _validate_limit(name: str, value: int | None) -> None:
    """列表结果必须有正整数上限，避免无界读取 canonical store。"""

    if value is None:
        raise InvalidRetrievalQuery(f"{name} must be a positive bounded integer")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRetrievalQuery(f"{name} must be a positive bounded integer")


@dataclass(frozen=True)
class ScopeFilters:
    """Structured 与 Lexical 共用的 canonical scope 过滤字段。"""

    session_ids: tuple[str, ...] | None = None
    start_timestamp: int | None = None
    end_timestamp: int | None = None
    sender_user_ids: tuple[str, ...] | None = None
    message_types: tuple[str, ...] | None = None
    source_message_id: str | None = None
    reply_to_source_message_id: str | None = None

    def __post_init__(self) -> None:
        # 先归一化所有集合，确保相同查询对象产生相同 SQL 参数顺序。
        object.__setattr__(self, "session_ids", _normalize_filter("session_ids", self.session_ids))
        object.__setattr__(self, "sender_user_ids", _normalize_filter("sender_user_ids", self.sender_user_ids))
        object.__setattr__(self, "message_types", _normalize_filter("message_types", self.message_types))
        _validate_timestamp("start_timestamp", self.start_timestamp)
        _validate_timestamp("end_timestamp", self.end_timestamp)

        # 半开区间允许 start == end；只有反向区间才是调用方错误。
        if (
            self.start_timestamp is not None
            and self.end_timestamp is not None
            and self.start_timestamp > self.end_timestamp
        ):
            raise InvalidRetrievalQuery("start_timestamp must be <= end_timestamp")

        # source/reply ID 在 M1 中只在 session 内唯一，禁止构造全库查找。
        if (
            (self.source_message_id is not None or self.reply_to_source_message_id is not None)
            and not self.session_ids
        ):
            raise InvalidRetrievalQuery("source/reply message IDs require session_ids")
        if self.source_message_id == "" or self.reply_to_source_message_id == "":
            raise InvalidRetrievalQuery("source/reply message IDs must be non-empty")

    def scope_dict(self) -> dict[str, object]:
        """返回不含数据库对象的可观测 scope 投影。"""

        return {
            "session_ids": self.session_ids,
            "start_timestamp": self.start_timestamp,
            "end_timestamp": self.end_timestamp,
            "sender_user_ids": self.sender_user_ids,
            "message_types": self.message_types,
            "source_message_id": self.source_message_id,
            "reply_to_source_message_id": self.reply_to_source_message_id,
        }


@dataclass(frozen=True)
class MessageQuery(ScopeFilters):
    """有界的 Structured message query。"""

    limit: int | None = DEFAULT_STRUCTURED_RESULT_LIMIT

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_limit("limit", self.limit)
        if self.limit is not None and self.limit > MAX_STRUCTURED_RESULT_ITEMS:
            raise InvalidRetrievalQuery(
                f"structured message limit must not exceed {MAX_STRUCTURED_RESULT_ITEMS}"
            )

    def to_dict(self) -> dict[str, object]:
        """保留 query scope 和 limit，供结果 metadata 与测试复核。"""

        return {**self.scope_dict(), "limit": self.limit}


@dataclass(frozen=True)
class AggregateQuery(ScopeFilters):
    """Structured count/group query；聚合本身不读取消息列表。"""

    group_by: GroupBy | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.group_by not in (None, "session", "sender", "month"):
            raise InvalidRetrievalQuery("group_by must be session, sender, month, or None")

    def to_dict(self) -> dict[str, object]:
        """返回聚合 scope 与固定分组名，不接受任意 SQL 片段。"""

        return {**self.scope_dict(), "group_by": self.group_by}


@dataclass(frozen=True)
class LexicalQuery(ScopeFilters):
    """有界的关键词 query，默认在 Retrieval Core 内自动扩展局部上下文。"""

    keyword: str = ""
    limit: int | None = DEFAULT_LEXICAL_RESULT_LIMIT
    context_before: int = 2
    context_after: int = 2
    resolved_time_range: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        normalized_keyword = self.keyword.strip() if isinstance(self.keyword, str) else ""
        if not normalized_keyword:
            raise InvalidRetrievalQuery("keyword must be non-empty")
        object.__setattr__(self, "keyword", normalized_keyword)
        _validate_limit("limit", self.limit)
        if self.limit is not None and self.limit > MAX_LEXICAL_RESULT_LIMIT:
            raise InvalidRetrievalQuery(
                f"lexical limit must not exceed {MAX_LEXICAL_RESULT_LIMIT}"
            )
        for name, value in (("context_before", self.context_before), ("context_after", self.context_after)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise InvalidRetrievalQuery(f"{name} must be a non-negative integer")
        if self.resolved_time_range is not None and not isinstance(self.resolved_time_range, Mapping):
            raise InvalidRetrievalQuery("resolved_time_range must be a mapping or None")

    @property
    def terms(self) -> tuple[str, ...]:
        """按空白拆分多关键词；FTS 表达式会在 data/storage 中安全引用这些词。"""

        return tuple(part for part in self.keyword.split() if part)

    def to_dict(self) -> dict[str, object]:
        """返回 lexical filters 与 bounded context 参数。"""

        result = {
            **self.scope_dict(),
            "keyword": self.keyword,
            "limit": self.limit,
            "context_before": self.context_before,
            "context_after": self.context_after,
        }
        if self.resolved_time_range is not None:
            result["resolved_time_range"] = dict(self.resolved_time_range)
        return result


@dataclass(frozen=True)
class MessageProjection:
    """Retrieval-facing message，不暴露 SQLite row 或 raw/canonical JSON。"""

    internal_message_id: str
    session_id: str
    source_message_id: str | None
    sender_user_id: str | None
    sender_platform_id: str | None
    sender_uin: str | None
    sender_name: str | None
    timestamp: int
    seq: int | None
    message_type: str
    normalized_content: str
    reply_to_source_message_id: str | None
    recalled: bool
    system: bool
    # session display 是可信 canonical projection 的一部分，供 Citation finalizer hydrate 快照。
    session_display: str = ""


@dataclass(frozen=True)
class MessageHit:
    """Lexical hit 与 canonical projection 分离表达，保留 score provenance。"""

    message: MessageProjection
    matched_terms: tuple[str, ...]
    score: float
    score_type: str


@dataclass(frozen=True)
class Coverage:
    """query-scope coverage descriptor。"""

    status: CoverageStatus
    basis: str


@dataclass(frozen=True)
class RetrievalMetadata:
    """不引入完整 Trace 的轻量查询诊断信息。"""

    filters: Mapping[str, object]
    ordering: str
    latency_ms: float
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AggregateBucket:
    """一个确定性聚合分组。group_key=None 表示真实 SQL NULL 桶。"""

    group_key: str | None
    count: int


@dataclass(frozen=True)
class AggregateData:
    """Repository 返回的 typed aggregate data。"""

    total_count: int
    buckets: tuple[AggregateBucket, ...]


@dataclass(frozen=True)
class StructuredMessageResult:
    """Structured message result，与 lexical candidate result 类型分离。"""

    query: MessageQuery
    strategy: Literal["structured"]
    messages: tuple[MessageProjection, ...]
    total_hits: int
    returned_count: int
    coverage: Coverage
    partial: bool
    truncated: bool
    metadata: RetrievalMetadata


@dataclass(frozen=True)
class StructuredAggregateResult:
    """Structured aggregate result，不强行套用 MessageHit。"""

    query: AggregateQuery
    strategy: Literal["structured"]
    total_count: int
    buckets: tuple[AggregateBucket, ...]
    coverage: Coverage
    partial: bool
    truncated: bool
    metadata: RetrievalMetadata


@dataclass(frozen=True)
class RetrievalResult:
    """Retrieval Core 统一外层结果，区分 lexical hits 与 expanded messages。"""

    query: LexicalQuery
    filters: Mapping[str, object]
    strategy: Literal["lexical"]
    hits: tuple[MessageHit, ...]
    expanded_messages: tuple[MessageProjection, ...]
    total_hits: int
    returned_messages: int
    coverage: Coverage
    partial: bool
    truncated: bool
    metadata: RetrievalMetadata


class CanonicalReadRepository(Protocol):
    """Retrieval 只依赖业务读取能力，不依赖具体 SQLite 连接。"""

    def count_messages(self, query: MessageQuery) -> int:
        """统计 Structured scope 的全部 canonical hits。"""

    def latest_message_timestamp(self, scope: ScopeFilters) -> int | None:
        """读取 trusted scope 内 archive latest 的 canonical timestamp。"""

    def read_messages(self, query: MessageQuery) -> tuple[MessageProjection, ...]:
        """读取有界且已排序的 canonical projections。"""

    def read_message_by_id(self, internal_message_id: str) -> MessageProjection | None:
        """按稳定 internal message ID 读取 canonical projection。"""

    def aggregate_messages(self, query: AggregateQuery) -> AggregateData:
        """执行 count/group aggregate。"""

    def count_lexical_hits(self, query: LexicalQuery) -> int:
        """统计 lexical derived index 中的全部 hits。"""

    def read_lexical_hits(self, query: LexicalQuery) -> tuple[MessageHit, ...]:
        """读取有界 lexical hits，并从 canonical 表 hydrate projection。"""

    def read_message_context(
        self,
        session_id: str,
        internal_message_id: str,
        before: int,
        after: int,
    ) -> tuple[MessageProjection, ...]:
        """读取同 session 的 bounded surrounding context。"""

    def read_message_context_scoped(
        self,
        session_id: str,
        internal_message_id: str,
        before: int,
        after: int,
        scope: ScopeFilters,
    ) -> tuple[MessageProjection, ...]:
        """读取 trusted Scope 内的同 session surrounding context。"""

    def iter_semantic_messages(self, batch_size: int) -> "Iterator[MessageProjection]":
        """按 canonical ordering 流式读取 semantic builder 所需的最小 projection。"""

    def read_message_range(
        self,
        session_id: str,
        start_message_id: str,
        end_message_id: str,
        limit: int,
    ) -> tuple[MessageProjection, ...]:
        """按同一 session 的 canonical ordering 恢复一个 bounded message range。"""


def message_sort_key(message: MessageProjection) -> tuple[int, int, int, str]:
    """复用 repository 的确定性排序语义来合并上下文窗口。"""

    # missing seq 明确排在有 seq 之后；这里的稳定顺序不等于平台真实顺序。
    missing_seq = 1 if message.seq is None else 0
    return (message.timestamp, missing_seq, message.seq if message.seq is not None else 0, message.internal_message_id)


class StructuredRetrieval:
    """Structured query 的业务编排，不直接执行 SQL。"""

    def __init__(self, repository: CanonicalReadRepository) -> None:
        self.repository = repository

    def retrieve_messages(self, query: MessageQuery) -> StructuredMessageResult:
        """先统计 total，再读取 bounded rows，避免把 returned 当成 total。"""

        started = perf_counter()
        total_hits = self.repository.count_messages(query)
        messages = self.repository.read_messages(query)
        latency_ms = (perf_counter() - started) * 1000
        return StructuredMessageResult(
            query=query,
            strategy="structured",
            messages=messages,
            total_hits=total_hits,
            returned_count=len(messages),
            coverage=Coverage(status="complete", basis="canonical_store"),
            partial=False,
            truncated=total_hits > len(messages),
            metadata=RetrievalMetadata(
                filters=query.to_dict(),
                ordering=ORDERING_DESCRIPTION,
                latency_ms=latency_ms,
            ),
        )

    def aggregate_messages(self, query: AggregateQuery) -> StructuredAggregateResult:
        """聚合结果使用独立类型，并保留完整 canonical coverage。"""

        started = perf_counter()
        data = self.repository.aggregate_messages(query)
        latency_ms = (perf_counter() - started) * 1000
        return StructuredAggregateResult(
            query=query,
            strategy="structured",
            total_count=data.total_count,
            buckets=data.buckets,
            coverage=Coverage(status="complete", basis="canonical_store"),
            partial=False,
            truncated=False,
            metadata=RetrievalMetadata(
                filters=query.to_dict(),
                ordering="group key ASC",
                latency_ms=latency_ms,
            ),
        )
