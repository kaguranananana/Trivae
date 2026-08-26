"""Lexical Retrieval 与自动 Context Expansion 的业务编排。"""

from __future__ import annotations

from time import perf_counter

from trivae.config.limits import MAX_AUTOMATIC_CONTEXT_SOURCE_HITS
from trivae.retrieval.context import ContextExpander
from trivae.retrieval.structured import (
    ORDERING_DESCRIPTION,
    CanonicalReadRepository,
    Coverage,
    LexicalQuery,
    RetrievalMetadata,
    RetrievalResult,
)


class LexicalRetrieval:
    """调用 derived lexical read adapter，再自动执行 bounded context expansion。"""

    def __init__(self, repository: CanonicalReadRepository, context_expander: ContextExpander | None = None) -> None:
        self.repository = repository
        self.context_expander = context_expander or ContextExpander(repository)

    def search(self, query: LexicalQuery) -> RetrievalResult:
        """返回 lexical hits 和合并后的 bounded messages。"""

        started = perf_counter()
        total_hits = self.repository.count_lexical_hits(query)
        hits = self.repository.read_lexical_hits(query)
        expansion = self.context_expander.expand(
            hits=hits,
            before=query.context_before,
            after=query.context_after,
            limit=query.limit if query.limit is not None else 0,
        )
        latency_ms = (perf_counter() - started) * 1000

        # total_hits 超过本次 bounded hit fetch 时，不能声称所有真实 hit 都已返回。
        partial = total_hits > len(hits) or expansion.partial
        truncated = total_hits > len(hits) or expansion.truncated
        return RetrievalResult(
            query=query,
            filters=query.to_dict(),
            strategy="lexical",
            hits=hits,
            expanded_messages=expansion.messages,
            total_hits=total_hits,
            returned_messages=len(expansion.messages),
            coverage=Coverage(status="complete", basis="canonical_plus_lexical_index"),
            partial=partial,
            truncated=truncated,
            metadata=RetrievalMetadata(
                filters=query.to_dict(),
                ordering="FTS5 score ASC, " + ORDERING_DESCRIPTION,
                latency_ms=latency_ms,
                details={
                    "returned_hits": len(hits),
                    "expanded_candidate_messages": expansion.candidate_count,
                    "context_before": query.context_before,
                    "context_after": query.context_after,
                    "context_source_hits": expansion.context_source_hits,
                    "context_source_budget": MAX_AUTOMATIC_CONTEXT_SOURCE_HITS,
                },
            ),
        )
