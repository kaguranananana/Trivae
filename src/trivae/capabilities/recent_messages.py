"""get_recent_messages Capability：temporal selection，scope 校验后委托 Structured Retrieval。"""

from __future__ import annotations

from dataclasses import replace

from trivae.capabilities.contracts import (
    CapabilityContractError,
    CapabilityMetadata,
    ExecutionScope,
    GetRecentMessagesInput,
)
from trivae.capabilities.scope import (
    effective_end,
    effective_sessions,
    effective_start,
    resolve_relative_time_range,
)
from trivae.retrieval.structured import (
    MessageQuery,
    ScopeFilters,
    StructuredMessageResult,
    StructuredRetrieval,
)


class RecentMessagesCapability:
    """只做时间窗内的 latest-N canonical candidate 读取；价值判断属于 Agent synthesis。"""

    metadata = CapabilityMetadata(
        name="get_recent_messages",
        description="Read the most recent canonical messages inside a time range for temporal browsing.",
        bounded=True,
        input_fields=(
            "time_range",
            "start_timestamp",
            "end_timestamp",
            "session_ids",
            "limit",
        ),
    )

    def __init__(self, retrieval: StructuredRetrieval) -> None:
        self.retrieval = retrieval

    def execute(self, request: GetRecentMessagesInput, scope: ExecutionScope) -> StructuredMessageResult:
        """继承 trusted scope；显式拒绝越权 filter，并把相对时间锚定 archive_latest。"""

        scoped_sessions = effective_sessions(request, scope)
        if request.time_range is None:
            resolved_time_range = None
            scoped_start = effective_start(request, scope)
            scoped_end = effective_end(request, scope)
        else:
            # anchor 只看当前 session/trusted scope 的 archive，不受机器当前时间影响。
            anchor_scope = ScopeFilters(
                session_ids=scoped_sessions,
                start_timestamp=scope.start_timestamp,
                end_timestamp=scope.end_timestamp,
            )
            latest_timestamp = self.retrieval.repository.latest_message_timestamp(anchor_scope)
            resolved_time_range = resolve_relative_time_range(
                request,
                scope,
                latest_timestamp=latest_timestamp,
            )
            if resolved_time_range is None:
                raise CapabilityContractError("relative time range did not resolve")
            scoped_start = resolved_time_range.start_timestamp
            scoped_end = resolved_time_range.end_timestamp

        query = MessageQuery(
            session_ids=scoped_sessions,
            start_timestamp=scoped_start,
            end_timestamp=scoped_end,
            limit=request.limit,
        )
        result = self.retrieval.retrieve_recent_messages(query)
        if resolved_time_range is not None:
            # Host-resolved 绝对边界进入 Trace/retrieval diagnostics，供 Failure Attribution 复核。
            result = replace(
                result,
                metadata=replace(
                    result.metadata,
                    details={
                        **result.metadata.details,
                        "resolved_time_range": resolved_time_range.to_dict(),
                    },
                ),
            )
        return result
