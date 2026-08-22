"""search_messages Capability：scope 校验后委托 Retrieval Core。"""

from __future__ import annotations

from trivae.capabilities.contracts import (
    CapabilityContractError,
    CapabilityMetadata,
    CapabilityScopeError,
    ExecutionScope,
    SearchMessagesInput,
)
from trivae.retrieval.lexical import LexicalRetrieval
from trivae.retrieval.structured import LexicalQuery, RetrievalResult


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
        ),
    )

    def __init__(self, retrieval: LexicalRetrieval) -> None:
        self.retrieval = retrieval

    def execute(self, request: SearchMessagesInput, scope: ExecutionScope) -> RetrievalResult:
        """继承 trusted scope；显式拒绝越权 filter，而不是静默取交集。"""

        effective_sessions = self._effective_sessions(request, scope)
        effective_start = self._effective_start(request, scope)
        effective_end = self._effective_end(request, scope)
        if request.limit > scope.max_results:
            raise CapabilityContractError("requested limit exceeds trusted max_results")

        query = LexicalQuery(
            keyword=request.keyword,
            session_ids=effective_sessions,
            start_timestamp=effective_start,
            end_timestamp=effective_end,
            sender_user_ids=request.sender_user_ids,
            message_types=request.message_types,
            limit=request.limit,
            context_before=request.context_before,
            context_after=request.context_after,
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
