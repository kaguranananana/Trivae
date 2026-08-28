"""get_recent_messages Capability：temporal selection，scope 校验后委托 Structured Retrieval。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from trivae.capabilities.contracts import (
    CapabilityContractError,
    CapabilityMetadata,
    ExecutionScope,
    GetRecentMessagesInput,
    RelativeTimeRange,
    format_timestamp_utc,
)
from trivae.capabilities.scope import (
    effective_end,
    effective_sessions,
    effective_start,
    resolve_relative_time_range,
)
from trivae.config.limits import MAX_RECENT_MESSAGES_LIMIT
from trivae.retrieval.structured import (
    RecentMessagesCursor,
    RecentMessagesQuery,
    ScopeFilters,
    StructuredMessageResult,
    StructuredRetrieval,
)


def _absolute_time_range(
    start_timestamp: int | None,
    end_timestamp: int | None,
) -> dict[str, object]:
    """把显式 absolute scope 统一投影为 Host-owned 时间事实。"""

    result: dict[str, object] = {
        "kind": "absolute",
        "anchor": "request",
        "resolved_start_timestamp": start_timestamp,
        "resolved_end_timestamp": end_timestamp,
    }
    if start_timestamp is not None:
        result["resolved_start_utc"] = format_timestamp_utc(start_timestamp)
    if end_timestamp is not None:
        result["resolved_end_utc"] = format_timestamp_utc(end_timestamp)
    if start_timestamp is not None and end_timestamp is not None:
        result["resolved_interval_utc"] = (
            f"[{format_timestamp_utc(start_timestamp)}, "
            f"{format_timestamp_utc(end_timestamp)})"
        )
    return result


def _canonical_cursor_time_range(
    value: Mapping[str, object] | None,
    *,
    start_timestamp: int | None,
    end_timestamp: int | None,
) -> dict[str, object]:
    """校验并重建 cursor 的 Host 时间事实，拒绝模型篡改 UTC 文本。"""

    if value is None:
        # 没有旧版时间描述时仍以 cursor 的绝对边界生成可审计的 Host 事实。
        return _absolute_time_range(start_timestamp, end_timestamp)
    raw = dict(value)
    if raw.get("kind") == "absolute":
        # absolute cursor 的所有字段都能由受信边界确定，逐字段比较可显式暴露篡改。
        expected = _absolute_time_range(start_timestamp, end_timestamp)
    elif raw.get("kind") == "relative":
        try:
            requested = RelativeTimeRange.from_value(raw)
        except CapabilityContractError as exc:
            raise CapabilityContractError("cursor relative time range is invalid") from exc
        if requested is None:
            raise CapabilityContractError("cursor relative time range is invalid")
        anchor_timestamp = raw.get("anchor_timestamp")
        if isinstance(anchor_timestamp, bool) or not isinstance(anchor_timestamp, int):
            raise CapabilityContractError("cursor relative time range anchor is invalid")
        # 相对意图来自第一批 Host resolution；边界和三份 UTC 文本必须由本批 cursor 重建。
        expected = {
            **requested.to_dict(),
            "anchor_timestamp": anchor_timestamp,
            "resolved_start_timestamp": start_timestamp,
            "resolved_end_timestamp": end_timestamp,
            "anchor_utc": format_timestamp_utc(anchor_timestamp),
            "resolved_start_utc": (
                None if start_timestamp is None else format_timestamp_utc(start_timestamp)
            ),
            "resolved_end_utc": None if end_timestamp is None else format_timestamp_utc(end_timestamp),
            "resolved_interval_utc": (
                None
                if start_timestamp is None or end_timestamp is None
                else f"[{format_timestamp_utc(start_timestamp)}, {format_timestamp_utc(end_timestamp)})"
            ),
        }
    else:
        raise CapabilityContractError("cursor resolved time range kind is invalid")
    if raw != expected:
        raise CapabilityContractError("cursor resolved time range was modified")
    return expected


class RecentMessagesCapability:
    """只做时间窗内的 latest-N canonical candidate 读取；价值判断属于 Agent synthesis。"""

    metadata = CapabilityMetadata(
        name="get_recent_messages",
        description=(
            "Read the most recent canonical messages inside a time range for temporal browsing; "
            "sender_user_ids optionally restricts the query to canonical users.user_id values."
        ),
        bounded=True,
        input_fields=(
            "time_range",
            "start_timestamp",
            "end_timestamp",
            "session_ids",
            "sender_user_ids",
            "limit",
            "cursor",
        ),
    )

    def __init__(self, retrieval: StructuredRetrieval) -> None:
        self.retrieval = retrieval

    def execute(self, request: GetRecentMessagesInput, scope: ExecutionScope) -> StructuredMessageResult:
        """继承 trusted scope；显式拒绝越权 filter，并把相对时间锚定 archive_latest。"""

        effective_maximum = min(scope.max_results, MAX_RECENT_MESSAGES_LIMIT)
        if request.limit > effective_maximum:
            # 与 lexical/semantic Capability 一致：trusted max 是硬边界，不能静默把请求裁剪后继续执行。
            raise CapabilityContractError(
                f"recent message limit must not exceed trusted maximum {effective_maximum}"
            )
        scoped_sessions = effective_sessions(request, scope)
        cursor = request.cursor
        if cursor is not None and not isinstance(cursor, RecentMessagesCursor):
            # Input contract 已完成归一化；这里是跨层 invariant，失败时不能继续读第一页。
            raise RuntimeError("GetRecentMessagesInput cursor was not normalized")
        resolved_time_range_details: dict[str, object] | None = None
        if cursor is not None:
            # continuation 的 absolute window 已由 input contract 锁定，不能再次读取 archive_latest。
            scoped_start = effective_start(request, scope)
            scoped_end = effective_end(request, scope)
            resolved_time_range_details = _canonical_cursor_time_range(
                cursor.resolved_time_range,
                start_timestamp=scoped_start,
                end_timestamp=scoped_end,
            )
        elif request.time_range is None:
            # 只有显式 absolute 输入会落入这里；无参数输入已在 Input contract 中归一化为 relative。
            scoped_start = effective_start(request, scope)
            scoped_end = effective_end(request, scope)
            if request.start_timestamp is not None or request.end_timestamp is not None:
                resolved_time_range_details = _absolute_time_range(scoped_start, scoped_end)
        else:
            # anchor 只看当前 session/trusted scope 的 archive，不受机器当前时间影响。
            anchor_scope = ScopeFilters(
                session_ids=scoped_sessions,
                start_timestamp=scope.start_timestamp,
                end_timestamp=scope.end_timestamp,
                sender_user_ids=request.sender_user_ids,
            )
            latest_timestamp = self.retrieval.repository.latest_message_timestamp(anchor_scope)
            if latest_timestamp is None:
                # trusted scope（session+time 界定）内没有任何消息：recent 查询的合法空结果，
                # 而不是参数错误；模型将以 no-result contract 收尾。必须继承 trusted 边界，
                # 不能退化为全 session 浏览，否则会把范围外消息当作空窗答案的依据。
                empty_window_result = self.retrieval.retrieve_recent_messages(
                    RecentMessagesQuery(
                        session_ids=scoped_sessions,
                        start_timestamp=scope.start_timestamp,
                        end_timestamp=scope.end_timestamp,
                        sender_user_ids=request.sender_user_ids,
                        limit=request.limit,
                    )
                )
                return replace(
                    empty_window_result,
                    metadata=replace(
                        empty_window_result.metadata,
                        details={
                            **empty_window_result.metadata.details,
                            "resolved_time_range": None,
                            "zero_result_note": "trusted scope contains no messages; archive_latest unavailable",
                        },
                    ),
                )
            resolved_time_range = resolve_relative_time_range(
                request,
                scope,
                latest_timestamp=latest_timestamp,
            )
            if resolved_time_range is None:
                raise CapabilityContractError("relative time range did not resolve")
            scoped_start = resolved_time_range.start_timestamp
            scoped_end = resolved_time_range.end_timestamp
            resolved_time_range_details = resolved_time_range.to_dict()

        query = RecentMessagesQuery(
            session_ids=scoped_sessions,
            start_timestamp=scoped_start,
            end_timestamp=scoped_end,
            sender_user_ids=request.sender_user_ids,
            limit=request.limit,
            before_cursor=cursor,
        )
        result = self.retrieval.retrieve_recent_messages(query)
        if resolved_time_range_details is not None:
            # Host-resolved 绝对边界进入 Trace/retrieval diagnostics，供 Failure Attribution 复核。
            details = {
                **result.metadata.details,
                "resolved_time_range": resolved_time_range_details,
            }
            next_cursor_value = details.get("next_cursor")
            if next_cursor_value is not None:
                # 下一页必须携带同一时间事实，避免模型手工复制时改变窗口。
                next_cursor = RecentMessagesCursor.from_value(next_cursor_value).with_resolved_time_range(
                    resolved_time_range_details
                )
                details["next_cursor"] = next_cursor.to_dict()
            result = replace(
                result,
                metadata=replace(
                    result.metadata,
                    details=details,
                ),
            )
        return result
