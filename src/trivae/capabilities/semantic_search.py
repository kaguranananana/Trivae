"""semantic_search Capability：trusted scope 校验后委托 Semantic Retrieval。"""

from __future__ import annotations

from trivae.capabilities.contracts import (
    CapabilityContractError,
    CapabilityMetadata,
    ExecutionScope,
    SemanticSearchInput,
)
from trivae.capabilities.scope import effective_end, effective_sessions, effective_start
from trivae.retrieval.semantic.contracts import SemanticQuery, SemanticRetrievalResult
from trivae.retrieval.semantic.retrieval import SemanticRetrieval


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
        ),
    )

    def __init__(self, retrieval: SemanticRetrieval) -> None:
        self.retrieval = retrieval

    def execute(self, request: SemanticSearchInput, scope: ExecutionScope) -> SemanticRetrievalResult:
        """继承 trusted scope，并让 SemanticQuery 保留完整可追踪字段。"""

        if request.limit > scope.max_results:
            raise CapabilityContractError("requested limit exceeds trusted max_results")
        query = SemanticQuery(
            query=request.query,
            session_ids=effective_sessions(request, scope),
            start_timestamp=effective_start(request, scope),
            end_timestamp=effective_end(request, scope),
            sender_user_ids=request.sender_user_ids,
            message_types=request.message_types,
            source_message_id=request.source_message_id,
            reply_to_source_message_id=request.reply_to_source_message_id,
            limit=request.limit,
            context_before=request.context_before,
            context_after=request.context_after,
            dense_top_k=request.dense_top_k,
        )
        return self.retrieval.search(query)
