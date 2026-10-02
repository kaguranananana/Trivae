"""semantic_search Capability：trusted scope 校验后委托 Semantic Retrieval。"""

from __future__ import annotations

from trivae.capabilities.contracts import (
    CapabilityContractError,
    CapabilityMetadata,
    ExecutionScope,
    SemanticSearchInput,
)
from trivae.capabilities.scope import (
    effective_end,
    effective_sessions,
    effective_start,
    resolve_relative_time_range,
)
from trivae.config.limits import MAX_SEMANTIC_RESULT_LIMIT
from trivae.retrieval.semantic.contracts import SemanticQuery, SemanticRetrievalResult
from trivae.retrieval.semantic.retrieval import SemanticRetrieval
from trivae.retrieval.structured import ScopeFilters


class SemanticSearchCapability:
    """让 Agent 明确选择 conceptual semantic retrieval，不把策略塞进旧工具参数。"""

    metadata = CapabilityMetadata(
        name="semantic_search",
        description=(
            "Search conversation meaning with local semantic embeddings. "
            "Use when wording differs from the question; use lexical_search for exact terms."
        ),
        bounded=True,
        input_fields=(
            "query",
            "session_ids",
            "start_timestamp",
            "end_timestamp",
            "sender_user_ids",
            "message_types",
            "source_message_id",
            "reply_to_source_message_id",
            "limit",
            "context_before",
            "context_after",
            "dense_top_k",
            "time_range",
        ),
    )

    def __init__(self, retrieval: SemanticRetrieval) -> None:
        self.retrieval = retrieval

    def execute(self, request: SemanticSearchInput, scope: ExecutionScope) -> SemanticRetrievalResult:
        """继承 trusted scope，并让 SemanticQuery 保留完整可追踪字段。"""

        effective_maximum = min(scope.max_results, MAX_SEMANTIC_RESULT_LIMIT)
        if request.limit > effective_maximum:
            raise CapabilityContractError(
                f"requested semantic limit exceeds trusted maximum {effective_maximum}"
            )
        scoped_sessions = effective_sessions(request, scope)
        if request.time_range is None:
            resolved_time_range = None
            scoped_start = effective_start(request, scope)
            scoped_end = effective_end(request, scope)
        else:
            # semantic 与 lexical 共享相同的 archive latest 解析规则，避免两套时间语义。
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
        query = SemanticQuery(
            query=request.query,
            session_ids=scoped_sessions,
            start_timestamp=scoped_start,
            end_timestamp=scoped_end,
            sender_user_ids=request.sender_user_ids,
            message_types=request.message_types,
            source_message_id=request.source_message_id,
            reply_to_source_message_id=request.reply_to_source_message_id,
            limit=request.limit,
            context_before=request.context_before,
            context_after=request.context_after,
            dense_top_k=request.dense_top_k,
            resolved_time_range=None if resolved_time_range is None else resolved_time_range.to_dict(),
        )
        return self.retrieval.search(query)
