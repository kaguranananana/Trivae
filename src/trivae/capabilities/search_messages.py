"""search_messages Capability：scope 校验后委托 Retrieval Core。"""

from __future__ import annotations

from trivae.capabilities.contracts import (
    CapabilityContractError,
    CapabilityMetadata,
    CapabilityScopeError,
    ExecutionScope,
    SearchMessagesInput,
)
from trivae.capabilities.scope import (
    effective_end,
    effective_sessions,
    effective_start,
    resolve_relative_time_range,
)
from trivae.retrieval.lexical import LexicalRetrieval
from trivae.retrieval.structured import LexicalQuery, RetrievalResult, ScopeFilters


class SearchMessagesCapability:
    """把 trusted scope 继承和 lexical/context Retrieval 组合成业务能力。"""

    metadata = CapabilityMetadata(
        name="search_messages",
        description="Search canonical messages with bounded automatic local context.",
        bounded=True,
        input_fields=(
            "keyword",
            "session_ids",
            "start_timestamp",
            "end_timestamp",
            "sender_user_ids",
            "message_types",
            "limit",
            "context_before",
            "context_after",
            "time_range",
        ),
    )

    def __init__(self, retrieval: LexicalRetrieval) -> None:
        self.retrieval = retrieval

    def execute(self, request: SearchMessagesInput, scope: ExecutionScope) -> RetrievalResult:
        """继承 trusted scope；显式拒绝越权 filter，而不是静默取交集。"""

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
        if request.limit > scope.max_results:
            raise CapabilityContractError("requested limit exceeds trusted max_results")

        query = LexicalQuery(
            keyword=request.keyword,
            session_ids=scoped_sessions,
            start_timestamp=scoped_start,
            end_timestamp=scoped_end,
            sender_user_ids=request.sender_user_ids,
            message_types=request.message_types,
            limit=request.limit,
            context_before=request.context_before,
            context_after=request.context_after,
            resolved_time_range=None if resolved_time_range is None else resolved_time_range.to_dict(),
        )
        return self.retrieval.search(query)

    @staticmethod
    def _effective_sessions(request: SearchMessagesInput, scope: ExecutionScope) -> tuple[str, ...] | None:
        """显式 session filter 必须是 trusted scope 的子集。"""

        if scope.allowed_session_ids is None:
            return request.session_ids
        if request.session_ids is None:
            return scope.allowed_session_ids
        allowed = set(scope.allowed_session_ids)
        if not set(request.session_ids).issubset(allowed):
            raise CapabilityScopeError("requested session is outside trusted data access scope")
        return request.session_ids

    @staticmethod
    def _effective_start(request: SearchMessagesInput, scope: ExecutionScope) -> int | None:
        """输入时间范围不能向 trusted scope 之前扩展。"""

        start = request.start_timestamp if request.start_timestamp is not None else scope.start_timestamp
        if scope.start_timestamp is not None and (start is None or start < scope.start_timestamp):
            raise CapabilityScopeError("requested start timestamp is outside trusted scope")
        return start

    @staticmethod
    def _effective_end(request: SearchMessagesInput, scope: ExecutionScope) -> int | None:
        """输入时间范围不能向 trusted scope 之后扩展。"""

        end = request.end_timestamp if request.end_timestamp is not None else scope.end_timestamp
        if scope.end_timestamp is not None and (end is None or end > scope.end_timestamp):
            raise CapabilityScopeError("requested end timestamp is outside trusted scope")
        return end


class LexicalSearchCapability(SearchMessagesCapability):
    """canonical lexical_search metadata；实现仍唯一复用 SearchMessagesCapability。"""

    metadata = CapabilityMetadata(
        name="lexical_search",
        description="Search canonical messages by exact words with bounded local context.",
        bounded=True,
        input_fields=SearchMessagesCapability.metadata.input_fields,
    )
