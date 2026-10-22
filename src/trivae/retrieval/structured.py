"""Retrieval Core 的读取契约与 Structured/Lexical 结果类型。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from time import perf_counter
from typing import Iterator, Literal, Mapping, Protocol, Sequence

from trivae.config.limits import (
    DEFAULT_LEXICAL_RESULT_LIMIT,
    DEFAULT_RECENT_MESSAGES_LIMIT,
    DEFAULT_STRUCTURED_RESULT_LIMIT,
    MAX_LEXICAL_RESULT_LIMIT,
    MAX_RECENT_MESSAGES_LIMIT,
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
    """Structured 与 Lexical 共用的 canonical scope 过滤字段。sender_user_ids 是 UserIdentity ID。"""

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
class RecentMessagesCursor:
    """recent browsing 的稳定 keyset 边界与原始查询窗口/成员过滤。"""

    # 这四个字段共同表达 canonical ordering 的一个严格位置，不依赖 offset 或时间唯一性。
    timestamp: int
    seq: int | None
    internal_message_id: str
    # continuation 必须沿用第一页的绝对 window/session，避免重新解析 archive_latest 产生漂移。
    start_timestamp: int | None
    end_timestamp: int | None
    session_ids: tuple[str, ...] | None = None
    resolved_time_range: Mapping[str, object] | None = None
    sender_user_ids: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        """校验 cursor 只携带 canonical ordering 和 bounded scope 字段。"""

        if isinstance(self.timestamp, bool) or not isinstance(self.timestamp, int):
            raise InvalidRetrievalQuery("recent cursor timestamp must be an integer")
        if self.seq is not None and (isinstance(self.seq, bool) or not isinstance(self.seq, int)):
            raise InvalidRetrievalQuery("recent cursor seq must be an integer or None")
        if not isinstance(self.internal_message_id, str) or not self.internal_message_id:
            raise InvalidRetrievalQuery("recent cursor internal_message_id must be non-empty")
        for name, value in (("start_timestamp", self.start_timestamp), ("end_timestamp", self.end_timestamp)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                raise InvalidRetrievalQuery(f"recent cursor {name} must be an integer")
        if (
            self.start_timestamp is not None
            and self.end_timestamp is not None
            and self.start_timestamp > self.end_timestamp
        ):
            raise InvalidRetrievalQuery("recent cursor window is reversed")
        if self.session_ids is not None:
            if (
                isinstance(self.session_ids, str)
                or not self.session_ids
                or any(not isinstance(value, str) or not value for value in self.session_ids)
            ):
                raise InvalidRetrievalQuery("recent cursor session_ids must contain non-empty strings")
            object.__setattr__(self, "session_ids", tuple(self.session_ids))
        # sender scope 与 session scope 一样属于 continuation identity，旧 cursor 缺失时保留 None。
        object.__setattr__(self, "sender_user_ids", _normalize_filter("sender_user_ids", self.sender_user_ids))
        if self.resolved_time_range is not None and not isinstance(self.resolved_time_range, Mapping):
            raise InvalidRetrievalQuery("recent cursor resolved_time_range must be a mapping or None")

    @classmethod
    def from_value(cls, value: object) -> "RecentMessagesCursor":
        """把 Tool 输入的普通 object 转成严格 cursor，禁止模型拼接半个位置。"""

        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise InvalidRetrievalQuery("recent cursor must be an object")
        try:
            session_ids = value.get("session_ids")
            if session_ids is not None:
                if isinstance(session_ids, str):
                    raise InvalidRetrievalQuery("recent cursor session_ids must be an array")
                session_ids = tuple(session_ids)
            return cls(
                timestamp=value["timestamp"],
                seq=value.get("seq"),
                internal_message_id=value["internal_message_id"],
                start_timestamp=value["start_timestamp"],
                end_timestamp=value["end_timestamp"],
                session_ids=session_ids,
                resolved_time_range=value.get("resolved_time_range"),
                sender_user_ids=value.get("sender_user_ids"),
            )
        except KeyError as exc:
            raise InvalidRetrievalQuery(f"recent cursor is missing {exc.args[0]}") from exc
        except (TypeError, ValueError) as exc:
            raise InvalidRetrievalQuery("recent cursor has invalid fields") from exc

    @classmethod
    def from_message(
        cls,
        message: "MessageProjection",
        *,
        start_timestamp: int | None,
        end_timestamp: int | None,
        session_ids: tuple[str, ...] | None,
        sender_user_ids: tuple[str, ...] | None = None,
        resolved_time_range: Mapping[str, object] | None = None,
    ) -> "RecentMessagesCursor":
        """从本批最早消息生成下一批所需的稳定位置。"""

        return cls(
            timestamp=message.timestamp,
            seq=message.seq,
            internal_message_id=message.internal_message_id,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            session_ids=session_ids,
            resolved_time_range=resolved_time_range,
            sender_user_ids=sender_user_ids,
        )

    def with_resolved_time_range(
        self,
        resolved_time_range: Mapping[str, object] | None,
    ) -> "RecentMessagesCursor":
        """把 Capability 解析出的 Host 时间事实补到已生成的 cursor。"""

        return replace(self, resolved_time_range=resolved_time_range)

    def to_dict(self) -> dict[str, object]:
        """输出模型可原样回传的 bounded cursor。"""

        return {
            "timestamp": self.timestamp,
            "seq": self.seq,
            "internal_message_id": self.internal_message_id,
            "start_timestamp": self.start_timestamp,
            "end_timestamp": self.end_timestamp,
            "session_ids": self.session_ids,
            "sender_user_ids": self.sender_user_ids,
            "resolved_time_range": (
                None if self.resolved_time_range is None else dict(self.resolved_time_range)
            ),
        }


@dataclass(frozen=True)
class RecentMessagesQuery(MessageQuery):
    """只供 temporal browsing 使用的高容量 MessageQuery。"""

    limit: int | None = DEFAULT_RECENT_MESSAGES_LIMIT
    before_cursor: RecentMessagesCursor | None = None

    def __post_init__(self) -> None:
        # 不调用 MessageQuery.__post_init__，避免 recent query 被通用 structured 的 100 封顶。
        ScopeFilters.__post_init__(self)
        _validate_limit("limit", self.limit)
        if self.limit is not None and self.limit > MAX_RECENT_MESSAGES_LIMIT:
            raise InvalidRetrievalQuery(
                f"recent message limit must not exceed {MAX_RECENT_MESSAGES_LIMIT}"
            )
        if self.before_cursor is not None and not isinstance(self.before_cursor, RecentMessagesCursor):
            raise InvalidRetrievalQuery("before_cursor must be a RecentMessagesCursor or None")
        if (
            self.before_cursor is not None
            and self.before_cursor.sender_user_ids != self.sender_user_ids
        ):
            # Retrieval 层再次锁定 continuation sender scope，避免绕过 Capability 直接改变分页集合。
            raise InvalidRetrievalQuery("recent cursor sender_user_ids do not match query")

    def to_dict(self) -> dict[str, object]:
        """保存 recent scope、容量和 cursor，供 Trace/Evidence 重放。"""

        return {
            **self.scope_dict(),
            "limit": self.limit,
            "before_cursor": None if self.before_cursor is None else self.before_cursor.to_dict(),
        }


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
class ForwardProvenance:
    """子消息在当前群的转发 occurrence；原始时间不替代外层 scope 时间。"""

    root_message_id: str
    parent_message_id: str
    path: str
    original_timestamp: int | None
    root_source_message_id: str | None
    source_file: str | None = None
    source_record_index: int | None = None

    @property
    def container_path(self) -> str:
        """同一父消息的不同 forward elements 也属于不同内部讨论窗口。"""

        return self.path.rpartition(".data.messages[")[0]

    def to_dict(self) -> dict[str, object]:
        """统一跨 Tool、Evidence 和历史记录的来源字段。"""

        return {
            "root_message_id": self.root_message_id,
            "parent_message_id": self.parent_message_id,
            "path": self.path,
            "original_timestamp": self.original_timestamp,
            "root_source_message_id": self.root_source_message_id,
            "source_file": self.source_file,
            "source_record_index": self.source_record_index,
        }


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
    # 转发 occurrence 不进入 canonical messages，证据仍由 root + path 恢复。
    forward: ForwardProvenance | None = None
    # 保留未展开节点的完整 JSON 路径，明确说明导出内容缺失。
    unexpanded_forward_paths: tuple[str, ...] = ()


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
    covered_units: int | None = None
    eligible_units: int | None = None
    unit: str | None = None
    known_gaps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """校验可选的覆盖数量，避免把 page count 当成完整窗口事实。"""

        if self.status not in {"complete", "partial", "none", "unknown", "not_applicable"}:
            raise InvalidRetrievalQuery("coverage status is invalid")
        if not isinstance(self.basis, str) or not self.basis:
            raise InvalidRetrievalQuery("coverage basis must be non-empty")
        for name in ("covered_units", "eligible_units"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise InvalidRetrievalQuery(f"coverage {name} must be a non-negative integer or None")
        if self.covered_units is not None and self.eligible_units is not None:
            if self.covered_units > self.eligible_units:
                raise InvalidRetrievalQuery("coverage covered_units cannot exceed eligible_units")
        if self.unit is not None and (not isinstance(self.unit, str) or not self.unit):
            raise InvalidRetrievalQuery("coverage unit must be non-empty or None")
        if not isinstance(self.known_gaps, tuple) or any(
            not isinstance(value, str) or not value for value in self.known_gaps
        ):
            raise InvalidRetrievalQuery("coverage known_gaps must be a tuple of non-empty strings")

    def to_dict(self) -> dict[str, object]:
        """输出兼容旧 coverage 字段且包含 recent 数量事实的普通字典。"""

        payload: dict[str, object] = {"status": self.status, "basis": self.basis}
        if self.covered_units is not None:
            payload["covered_units"] = self.covered_units
        if self.eligible_units is not None:
            payload["eligible_units"] = self.eligible_units
        if self.unit is not None:
            payload["unit"] = self.unit
        if self.known_gaps:
            payload["known_gaps"] = list(self.known_gaps)
        return payload


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

    def read_recent_messages(self, query: MessageQuery) -> tuple[MessageProjection, ...]:
        """从时间范围选取最新 limit 条并按 chronological 顺序返回。"""

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

    def read_message_replies_scoped(
        self,
        anchor: MessageProjection,
        scope: ScopeFilters,
        limit: int,
    ) -> tuple[MessageProjection, ...]:
        """按明确回复关系读取同会话、同转发容器内的 bounded 回复。"""

    def iter_semantic_messages(
        self, batch_size: int, *, scope: ScopeFilters | None = None
    ) -> "Iterator[MessageProjection]":
        """按 canonical ordering 流式读取 semantic builder 所需的最小 projection。"""

    def iter_forwarded_messages(
        self, batch_size: int, *, scope: ScopeFilters | None = None
    ) -> "Iterator[MessageProjection]":
        """从 canonical JSON 流式恢复转发 occurrence，独立于 FTS 是否已构建。"""

    def count_forwarded_messages(self) -> int:
        """统计可恢复子消息，不改变普通群消息统计口径。"""

    def canonical_revision(self) -> int:
        """读取持久化的 canonical 变更版本，索引不得缓存该事实。"""

    def semantic_change_ranges(
        self, since_revision: int, gap_seconds: int
    ) -> tuple[tuple[str, int | None, int | None], ...]:
        """读取旧、新位置连接的闭区间；会话改名以双空时间表示整个会话。"""

    def forward_content_gaps(self, scope: ScopeFilters) -> tuple[str, ...]:
        """返回当前群聊/转发时间范围内已知缺失节点的 root + path。"""

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

    def retrieve_recent_messages(self, query: MessageQuery) -> StructuredMessageResult:
        """Temporal browsing 按 keyset cursor 分页：窗口尾部批次按阅读顺序返回。"""

        started = perf_counter()
        recent_query = (
            query
            if isinstance(query, RecentMessagesQuery)
            else RecentMessagesQuery(
                session_ids=query.session_ids,
                start_timestamp=query.start_timestamp,
                end_timestamp=query.end_timestamp,
                sender_user_ids=query.sender_user_ids,
                message_types=query.message_types,
                source_message_id=query.source_message_id,
                reply_to_source_message_id=query.reply_to_source_message_id,
                limit=query.limit,
            )
        )
        # total 永远在不带 cursor 的同一 requested scope 上统计，不能把剩余页误报成总量。
        total_query = replace(recent_query, before_cursor=None)
        total_hits = self.repository.count_messages(total_query)
        remaining_hits = (
            total_hits
            if recent_query.before_cursor is None
            else self.repository.count_messages(recent_query)
        )
        messages = self.repository.read_recent_messages(recent_query)
        if len(messages) > remaining_hits:
            # Repository 违反 count/read 一致性时直接暴露实现错误，不用 partial 掩盖数据竞争。
            raise RetrievalError("recent message page returned more rows than its remaining count")
        has_more = remaining_hits > len(messages)
        covered_units = total_hits - remaining_hits + len(messages)
        next_cursor = None
        if has_more:
            if not messages:
                raise RetrievalError("recent message page reports more rows but returned no messages")
            # 单侧 absolute window 也必须能继续；cursor 直接保存 None 边界，不能丢掉原始 scope。
            next_cursor = RecentMessagesCursor.from_message(
                messages[0],
                start_timestamp=recent_query.start_timestamp,
                end_timestamp=recent_query.end_timestamp,
                session_ids=recent_query.session_ids,
                sender_user_ids=recent_query.sender_user_ids,
            ).to_dict()
        latency_ms = (perf_counter() - started) * 1000
        return StructuredMessageResult(
            query=recent_query,
            strategy="structured",
            messages=messages,
            total_hits=total_hits,
            returned_count=len(messages),
            coverage=Coverage(
                status="partial" if has_more else "complete",
                basis="canonical_store",
                covered_units=covered_units,
                eligible_units=total_hits,
                unit="message",
            ),
            partial=has_more,
            truncated=has_more,
            metadata=RetrievalMetadata(
                filters=recent_query.to_dict(),
                ordering="latest-limit selection (timestamp DESC), returned chronologically; " + ORDERING_DESCRIPTION,
                latency_ms=latency_ms,
                details={
                    "selection": "latest_limit",
                    "has_more": has_more,
                    "retrieved_count": len(messages),
                    "covered_units": covered_units,
                    "eligible_units": total_hits,
                    "before_cursor": (
                        None
                        if recent_query.before_cursor is None
                        else recent_query.before_cursor.to_dict()
                    ),
                    "next_cursor": next_cursor,
                },
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
