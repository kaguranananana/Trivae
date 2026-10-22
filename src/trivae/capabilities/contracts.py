"""Capability / Tool 的最小业务 contract。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Literal, Mapping, Sequence

from trivae.config.limits import (
    DEFAULT_LEXICAL_RESULT_LIMIT,
    DEFAULT_MEMBER_RESULT_LIMIT,
    DEFAULT_RECENT_MESSAGES_LIMIT,
    DEFAULT_SEMANTIC_RESULT_LIMIT,
    DEFAULT_TRUSTED_RESULT_LIMIT,
    MAX_RECENT_MESSAGES_LIMIT,
    MAX_TRUSTED_RESULT_LIMIT,
    RECENT_MESSAGES_DEFAULT_AMOUNT,
)
from trivae.retrieval.context import MAX_CONTEXT_EXPANSION_MESSAGES, MessageContextResult
from trivae.retrieval.identity import FindMembersResult
from trivae.retrieval.semantic.contracts import SemanticRetrievalResult
from trivae.retrieval.sql import SchemaResult, SQLQueryResult
from trivae.retrieval.structured import (
    InvalidRetrievalQuery,
    RecentMessagesCursor,
    RetrievalResult,
    StructuredAggregateResult,
    StructuredMessageResult,
)

ToolData = (
    RetrievalResult
    | SemanticRetrievalResult
    | StructuredMessageResult
    | StructuredAggregateResult
    | MessageContextResult
    | FindMembersResult
    | SchemaResult
    | SQLQueryResult
)


class CapabilityContractError(Exception):
    """调用输入或 trusted execution scope 违反 Capability contract。"""

    error_code = "INVALID_ARGUMENT"


class CapabilityScopeError(CapabilityContractError):
    """调用方试图读取 trusted data access scope 之外的数据。"""

    error_code = "SCOPE_VIOLATION"


RelativeTimeUnit = Literal["hour", "day", "week", "month"]


@dataclass(frozen=True)
class RelativeTimeRange:
    """模型只表达相对时间意图，绝对时间由 Host 根据 archive latest 计算。"""

    kind: Literal["relative"]
    amount: int
    unit: RelativeTimeUnit
    anchor: Literal["archive_latest"]

    def __post_init__(self) -> None:
        # kind 和 anchor 都是固定 contract，避免模型把 machine now 偷换成 archive 事实。
        if self.kind != "relative":
            raise CapabilityContractError("relative time kind must be relative")
        if isinstance(self.amount, bool) or not isinstance(self.amount, int) or self.amount <= 0:
            raise CapabilityContractError("relative time amount must be a positive integer")
        if self.unit not in ("hour", "day", "week", "month"):
            raise CapabilityContractError("relative time unit is invalid")
        if self.anchor != "archive_latest":
            raise CapabilityContractError("relative time anchor must be archive_latest")

    @classmethod
    def from_value(cls, value: object) -> RelativeTimeRange | None:
        """把 SDK 的普通 JSON object 解析为严格的相对时间 contract。"""

        if value is None:
            return None
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise CapabilityContractError("time_range must be a relative time object or None")
        try:
            return cls(
                kind=value["kind"],
                amount=value["amount"],
                unit=value["unit"],
                anchor=value["anchor"],
            )
        except KeyError as exc:
            raise CapabilityContractError(f"time_range is missing {exc.args[0]}") from exc
        except (TypeError, ValueError) as exc:
            raise CapabilityContractError("time_range has invalid fields") from exc

    def to_dict(self) -> dict[str, object]:
        """返回模型提出的相对 contract，不包含 Host 计算的绝对边界。"""

        return {
            "kind": self.kind,
            "amount": self.amount,
            "unit": self.unit,
            "anchor": self.anchor,
        }

    def resolve(
        self,
        *,
        anchor_timestamp: int,
        scope_start: int | None,
        scope_end: int | None,
    ) -> ResolvedTimeRange:
        """用 archive latest 计算半开时间区间，并把结果裁剪在 trusted scope 内。"""

        durations = {
            "hour": 60 * 60 * 1_000,
            "day": 24 * 60 * 60 * 1_000,
            "week": 7 * 24 * 60 * 60 * 1_000,
            # 产品 contract 将“一个月”固定定义为 30 个 canonical day，避免时区漂移。
            "month": 30 * 24 * 60 * 60 * 1_000,
        }
        start_timestamp = anchor_timestamp - self.amount * durations[self.unit]
        if scope_start is not None:
            start_timestamp = max(start_timestamp, scope_start)
        # end 是 exclusive；加一毫秒让 archive latest 这条消息仍在窗口内。
        end_timestamp = anchor_timestamp + 1
        if scope_end is not None:
            end_timestamp = min(end_timestamp, scope_end)
        if start_timestamp > end_timestamp:
            raise CapabilityContractError("resolved relative time range is empty")
        return ResolvedTimeRange(
            requested=self,
            anchor_timestamp=anchor_timestamp,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )


@dataclass(frozen=True)
class ResolvedTimeRange:
    """可写入 Trace/query snapshot 的 Host-owned 相对时间解析结果。"""

    requested: RelativeTimeRange
    anchor_timestamp: int
    start_timestamp: int
    end_timestamp: int

    def to_dict(self) -> dict[str, object]:
        """同时保留毫秒边界和 Host 生成的 UTC 文本，避免模型自行换算日期。"""

        return {
            **self.requested.to_dict(),
            "anchor_timestamp": self.anchor_timestamp,
            "resolved_start_timestamp": self.start_timestamp,
            "resolved_end_timestamp": self.end_timestamp,
            "anchor_utc": format_timestamp_utc(self.anchor_timestamp),
            "resolved_start_utc": format_timestamp_utc(self.start_timestamp),
            "resolved_end_utc": format_timestamp_utc(self.end_timestamp),
            "resolved_interval_utc": (
                f"[{format_timestamp_utc(self.start_timestamp)}, "
                f"{format_timestamp_utc(self.end_timestamp)})"
            ),
        }


def format_timestamp_utc(timestamp: int) -> str:
    """把 canonical 整数毫秒格式化为唯一的 UTC ISO-8601 文本。"""

    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        raise CapabilityContractError("canonical timestamp must be an integer")
    return datetime.fromtimestamp(timestamp / 1_000, tz=timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def _normalize_non_empty_strings(
    name: str,
    values: Sequence[str] | None,
) -> tuple[str, ...] | None:
    """统一校验非空字符串序列，避免错误字段延迟到 Retrieval 才暴露。"""

    if values is None:
        return None
    if isinstance(values, str):
        raise CapabilityContractError(f"{name} must be a sequence of non-empty strings")
    normalized = tuple(values)
    if not normalized or any(not isinstance(value, str) or not value for value in normalized):
        raise CapabilityContractError(f"{name} must contain non-empty strings")
    return normalized


def _normalize_scope_sessions(values: Sequence[str] | None) -> tuple[str, ...] | None:
    """把 trusted session scope 归一化，避免后续集合比较依赖输入容器类型。"""

    return _normalize_non_empty_strings("session scope", values)


def _validate_optional_timestamp(name: str, value: int | None) -> None:
    """Capability scope 与 input 都沿用 canonical integer timestamp。"""

    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise CapabilityContractError(f"{name} must be an integer timestamp or None")


def _normalize_optional_identifier(name: str, value: str | None) -> str | None:
    """校验 semantic source/reply locator，避免非字符串值延迟到 SQL 层。"""

    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise CapabilityContractError(f"{name} must be a non-empty string or None")
    return value.strip()


@dataclass(frozen=True)
class ExecutionScope:
    """由 Application/Runtime 派生的 trusted data access scope。"""

    allowed_session_ids: tuple[str, ...] | None = None
    start_timestamp: int | None = None
    end_timestamp: int | None = None
    max_results: int = DEFAULT_TRUSTED_RESULT_LIMIT

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_session_ids", _normalize_scope_sessions(self.allowed_session_ids))
        _validate_optional_timestamp("start_timestamp", self.start_timestamp)
        _validate_optional_timestamp("end_timestamp", self.end_timestamp)
        if self.start_timestamp is not None and self.end_timestamp is not None:
            if self.start_timestamp > self.end_timestamp:
                raise CapabilityContractError("trusted time scope is reversed")
        if isinstance(self.max_results, bool) or not isinstance(self.max_results, int) or self.max_results <= 0:
            raise CapabilityContractError("trusted max_results must be positive")
        if self.max_results > MAX_TRUSTED_RESULT_LIMIT:
            raise CapabilityContractError(
                f"trusted max_results must not exceed {MAX_TRUSTED_RESULT_LIMIT}"
            )


@dataclass(frozen=True)
class SearchMessagesInput:
    """search_messages 的输入字段；sender_user_ids 必须是 canonical users.user_id。"""

    keyword: str
    session_ids: tuple[str, ...] | None = None
    start_timestamp: int | None = None
    end_timestamp: int | None = None
    sender_user_ids: tuple[str, ...] | None = None
    message_types: tuple[str, ...] | None = None
    limit: int = DEFAULT_LEXICAL_RESULT_LIMIT
    context_before: int = 2
    context_after: int = 2
    time_range: RelativeTimeRange | Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.keyword, str):
            raise CapabilityContractError("keyword must be a string")
        object.__setattr__(self, "session_ids", _normalize_scope_sessions(self.session_ids))
        # sender/message filters 与 session filter 共享同一严格的非空字符串语义。
        object.__setattr__(self, "sender_user_ids", _normalize_non_empty_strings("sender_user_ids", self.sender_user_ids))
        object.__setattr__(self, "message_types", _normalize_non_empty_strings("message_types", self.message_types))
        _validate_optional_timestamp("start_timestamp", self.start_timestamp)
        _validate_optional_timestamp("end_timestamp", self.end_timestamp)
        normalized_time_range = RelativeTimeRange.from_value(self.time_range)
        object.__setattr__(self, "time_range", normalized_time_range)
        if normalized_time_range is not None and (self.start_timestamp is not None or self.end_timestamp is not None):
            raise CapabilityContractError("time_range cannot be combined with absolute timestamps")
        if self.start_timestamp is not None and self.end_timestamp is not None:
            if self.start_timestamp > self.end_timestamp:
                raise CapabilityContractError("query time scope is reversed")
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or self.limit <= 0:
            raise CapabilityContractError("limit must be positive")
        for name, value in (("context_before", self.context_before), ("context_after", self.context_after)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CapabilityContractError(f"{name} must be non-negative")


@dataclass(frozen=True)
class GetRecentMessagesInput:
    """get_recent_messages 的 temporal browsing 输入；时间窗决定候选集合。

    无任何时间参数时契约等价于 relative recent 2 days（anchor=archive_latest），
    与 SDK schema 全参数可选的形状保持一致；不允许 machine current time 参与。
    sender_user_ids 是 find_members 返回的 canonical users.user_id 过滤器。
    """

    time_range: RelativeTimeRange | Mapping[str, object] | None = None
    start_timestamp: int | None = None
    end_timestamp: int | None = None
    session_ids: tuple[str, ...] | None = None
    limit: int = DEFAULT_RECENT_MESSAGES_LIMIT
    cursor: RecentMessagesCursor | Mapping[str, object] | None = None
    # 追加在旧 positional 参数之后，保持既有 GetRecentMessagesInput 调用签名稳定。
    sender_user_ids: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_ids", _normalize_scope_sessions(self.session_ids))
        # 成员过滤只接受 find_members 返回的 canonical users.user_id，保持与其他检索输入一致。
        object.__setattr__(self, "sender_user_ids", _normalize_non_empty_strings("sender_user_ids", self.sender_user_ids))
        _validate_optional_timestamp("start_timestamp", self.start_timestamp)
        _validate_optional_timestamp("end_timestamp", self.end_timestamp)
        normalized_time_range = RelativeTimeRange.from_value(self.time_range)
        try:
            normalized_cursor = (
                None if self.cursor is None else RecentMessagesCursor.from_value(self.cursor)
            )
        except (InvalidRetrievalQuery, TypeError, ValueError) as exc:
            raise CapabilityContractError(f"cursor has invalid fields: {exc}") from exc
        if normalized_cursor is not None:
            # continuation 使用上一批 Host 已解析的 absolute window，禁止重新锚定 archive_latest。
            if normalized_time_range is not None:
                raise CapabilityContractError("cursor cannot be combined with time_range")
            for name in ("start_timestamp", "end_timestamp"):
                requested_value = getattr(self, name)
                cursor_value = getattr(normalized_cursor, name)
                if requested_value is not None and requested_value != cursor_value:
                    raise CapabilityContractError(f"cursor {name} does not match the request")
                object.__setattr__(self, name, cursor_value)
            if self.session_ids is not None and self.session_ids != normalized_cursor.session_ids:
                raise CapabilityContractError("cursor session_ids do not match the request")
            # cursor 已经固定了上一页的成员范围；继续请求不能借机切换或扩大 sender filter。
            if self.sender_user_ids is not None and self.sender_user_ids != normalized_cursor.sender_user_ids:
                raise CapabilityContractError("cursor sender_user_ids do not match the request")
            object.__setattr__(self, "session_ids", normalized_cursor.session_ids)
            # 未传 sender filter 时，从 cursor 恢复第一页的 canonical 成员范围；旧 cursor 没有该字段时保持 None。
            object.__setattr__(self, "sender_user_ids", normalized_cursor.sender_user_ids)
            normalized_time_range = None
        elif normalized_time_range is None and self.start_timestamp is None and self.end_timestamp is None:
            # SDK schema 与 Capability contract 的统一缺省：最近两天，archive_latest 锚定。
            normalized_time_range = RelativeTimeRange(
                kind="relative",
                amount=RECENT_MESSAGES_DEFAULT_AMOUNT,
                unit="day",
                anchor="archive_latest",
            )
        object.__setattr__(self, "time_range", normalized_time_range)
        object.__setattr__(self, "cursor", normalized_cursor)
        if normalized_time_range is not None and (self.start_timestamp is not None or self.end_timestamp is not None):
            raise CapabilityContractError("time_range cannot be combined with absolute timestamps")
        if self.start_timestamp is not None and self.end_timestamp is not None:
            if self.start_timestamp > self.end_timestamp:
                raise CapabilityContractError("query time scope is reversed")
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or self.limit <= 0:
            raise CapabilityContractError("limit must be positive")
        if self.limit > MAX_RECENT_MESSAGES_LIMIT:
            raise CapabilityContractError(
                f"limit must not exceed {MAX_RECENT_MESSAGES_LIMIT}"
            )


@dataclass(frozen=True)
class SemanticSearchInput:
    """semantic_search 的独立输入；sender_user_ids 必须是 canonical users.user_id。"""

    query: str
    session_ids: tuple[str, ...] | None = None
    start_timestamp: int | None = None
    end_timestamp: int | None = None
    sender_user_ids: tuple[str, ...] | None = None
    message_types: tuple[str, ...] | None = None
    source_message_id: str | None = None
    reply_to_source_message_id: str | None = None
    limit: int = DEFAULT_SEMANTIC_RESULT_LIMIT
    context_before: int = 2
    context_after: int = 2
    dense_top_k: int = 40
    time_range: RelativeTimeRange | Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.query, str) or not self.query.strip():
            raise CapabilityContractError("query must be a non-empty string")
        object.__setattr__(self, "query", self.query.strip())
        object.__setattr__(self, "session_ids", _normalize_scope_sessions(self.session_ids))
        object.__setattr__(self, "sender_user_ids", _normalize_non_empty_strings("sender_user_ids", self.sender_user_ids))
        object.__setattr__(self, "message_types", _normalize_non_empty_strings("message_types", self.message_types))
        _validate_optional_timestamp("start_timestamp", self.start_timestamp)
        _validate_optional_timestamp("end_timestamp", self.end_timestamp)
        normalized_time_range = RelativeTimeRange.from_value(self.time_range)
        object.__setattr__(self, "time_range", normalized_time_range)
        if normalized_time_range is not None and (self.start_timestamp is not None or self.end_timestamp is not None):
            raise CapabilityContractError("time_range cannot be combined with absolute timestamps")
        if self.start_timestamp is not None and self.end_timestamp is not None:
            if self.start_timestamp > self.end_timestamp:
                raise CapabilityContractError("query time scope is reversed")
        object.__setattr__(
            self,
            "source_message_id",
            _normalize_optional_identifier("source_message_id", self.source_message_id),
        )
        object.__setattr__(
            self,
            "reply_to_source_message_id",
            _normalize_optional_identifier("reply_to_source_message_id", self.reply_to_source_message_id),
        )
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or self.limit <= 0:
            raise CapabilityContractError("limit must be positive")
        for name, value in (
            ("context_before", self.context_before),
            ("context_after", self.context_after),
            ("dense_top_k", self.dense_top_k),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CapabilityContractError(f"{name} must be non-negative")
        if self.dense_top_k == 0:
            raise CapabilityContractError("dense_top_k must be positive")


@dataclass(frozen=True)
class GetMessageContextInput:
    """get_message_context 的稳定 message locator 与 bounded 窗口字段。"""

    message_id: str
    context_before: int = 8
    context_after: int = 8
    include_replies: bool = False

    def __post_init__(self) -> None:
        """拒绝空 locator、负窗口和超过 transport bound 的请求。"""

        object.__setattr__(self, "message_id", _normalize_required_identifier("message_id", self.message_id))
        # 回复关系查询必须显式开启，不能把普通邻居窗口悄悄变成另一种检索。
        if not isinstance(self.include_replies, bool):
            raise CapabilityContractError("include_replies must be a boolean")
        for name, value in (
            ("context_before", self.context_before),
            ("context_after", self.context_after),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CapabilityContractError(f"{name} must be non-negative")
        if self.context_before + self.context_after + 1 > MAX_CONTEXT_EXPANSION_MESSAGES:
            raise CapabilityContractError(
                f"requested context exceeds {MAX_CONTEXT_EXPANSION_MESSAGES} message bound"
            )


@dataclass(frozen=True)
class FindMembersInput:
    """find_members 的名称/身份查询与可选 session filter。"""

    query: str
    session_ids: tuple[str, ...] | None = None
    limit: int = DEFAULT_MEMBER_RESULT_LIMIT

    def __post_init__(self) -> None:
        """在 Tool contract 层规范化查询文本、session filter 和候选上限。"""

        object.__setattr__(self, "query", _normalize_required_identifier("query", self.query))
        object.__setattr__(self, "session_ids", _normalize_scope_sessions(self.session_ids))
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or self.limit <= 0:
            raise CapabilityContractError("limit must be positive")


@dataclass(frozen=True)
class GetSchemaInput:
    """get_schema 的无参数 typed request，保持 Tool Registry 统一入口。"""


@dataclass(frozen=True)
class ExecuteSQLInput:
    """execute_sql 的原始 read-only SQL 与可选返回行上限。"""

    sql: str
    max_rows: int | None = None

    def __post_init__(self) -> None:
        """只校验输入形状；权限和最终 bound 由 Capability 结合 trusted scope 决定。"""

        object.__setattr__(self, "sql", _normalize_required_identifier("sql", self.sql))
        if self.max_rows is not None and (
            isinstance(self.max_rows, bool) or not isinstance(self.max_rows, int) or self.max_rows <= 0
        ):
            raise CapabilityContractError("max_rows must be a positive integer or None")


def _normalize_required_identifier(name: str, value: object) -> str:
    """统一校验 Agent 提供的稳定 locator 或身份查询文本。"""

    if not isinstance(value, str) or not value.strip():
        raise CapabilityContractError(f"{name} must be a non-empty string")
    return value.strip()


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
    data: ToolData | None
    meta: Mapping[str, object]
    error: ToolError | None

    def to_dict(self) -> dict[str, object]:
        """为测试/接口适配提供普通字典，不把 SQLite 对象带入结果。"""

        data: object | None
        if self.data is None:
            data = None
        elif isinstance(self.data, RetrievalResult):
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
                "coverage": self.data.coverage.to_dict(),
                "partial": self.data.partial,
                "truncated": self.data.truncated,
                "metadata": {
                    "filters": dict(self.data.metadata.filters),
                    "ordering": self.data.metadata.ordering,
                    "latency_ms": self.data.metadata.latency_ms,
                    "details": dict(self.data.metadata.details),
                },
            }
        elif isinstance(self.data, SemanticRetrievalResult):
            data = {
                "strategy": self.data.strategy,
                "query": self.data.query.to_dict(),
                "filters": dict(self.data.filters),
                "hits": [
                    {
                        "chunk_id": hit.chunk_id,
                        "parent_id": hit.parent_id,
                        "session_id": hit.session_id,
                        "parent_start_message_id": hit.parent_start_message_id,
                        "parent_end_message_id": hit.parent_end_message_id,
                        "start_message_id": hit.start_message_id,
                        "end_message_id": hit.end_message_id,
                        "score": hit.score,
                        "score_type": hit.score_type,
                        "dense_rank": hit.dense_rank,
                        "index_identity": hit.index_identity,
                    }
                    for hit in self.data.hits
                ],
                "expanded_messages": [asdict(message) for message in self.data.expanded_messages],
                "total_hits": self.data.total_hits,
                "returned_messages": self.data.returned_messages,
                "coverage": self.data.coverage.to_dict(),
                "partial": self.data.partial,
                "truncated": self.data.truncated,
                "metadata": {
                    "filters": dict(self.data.metadata.filters),
                    "ordering": self.data.metadata.ordering,
                    "latency_ms": self.data.metadata.latency_ms,
                    "details": dict(self.data.metadata.details),
                },
            }
        elif isinstance(self.data, StructuredMessageResult):
            data = {
                "strategy": self.data.strategy,
                "query": self.data.query.to_dict(),
                "messages": [asdict(message) for message in self.data.messages],
                "total_hits": self.data.total_hits,
                "returned_count": self.data.returned_count,
                "coverage": self.data.coverage.to_dict(),
                "partial": self.data.partial,
                "truncated": self.data.truncated,
                "metadata": {
                    "filters": dict(self.data.metadata.filters),
                    "ordering": self.data.metadata.ordering,
                    "latency_ms": self.data.metadata.latency_ms,
                    "details": dict(self.data.metadata.details),
                },
            }
        elif isinstance(self.data, MessageContextResult):
            # Explicit context 使用自己的 strategy/result fields，避免误报为 Structured Retrieval。
            data = self.data.to_dict()
        elif isinstance(self.data, FindMembersResult):
            # 成员候选包含 UserIdentity、Membership 和 match reasons，全部来自 bounded projection。
            data = self.data.to_dict()
        elif isinstance(self.data, SchemaResult):
            # Schema 只投影允许 Agent 使用的 public tables/columns/relationships。
            data = self.data.to_dict()
        elif isinstance(self.data, SQLQueryResult):
            # SQL rows 是当前 Tool Result 的 structured evidence，保留 query 与 truncation 事实。
            data = self.data.to_dict()
        else:
            # Aggregate 结果拥有自己的 locator/value 语义，不能套成 MessageHit。
            data = {
                "strategy": self.data.strategy,
                "query": self.data.query.to_dict(),
                "total_count": self.data.total_count,
                "buckets": [asdict(bucket) for bucket in self.data.buckets],
                "coverage": self.data.coverage.to_dict(),
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
