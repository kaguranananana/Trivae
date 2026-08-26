"""Semantic ANN candidate retrieval、canonical range recovery 与 bounded context expansion。"""

from __future__ import annotations

from collections.abc import Sequence
from time import perf_counter

from trivae.config.limits import MAX_AUTOMATIC_CONTEXT_SOURCE_HITS
from trivae.retrieval.context import (
    MAX_CONTEXT_EXPANSION_MESSAGES,
    ContextExpander,
    ContextRange,
)
from trivae.retrieval.semantic.chunking import (
    DEFAULT_SEMANTIC_CHUNK_CONFIG,
    SEMANTIC_CHUNKER_VERSION,
    SemanticChunker,
)
from trivae.retrieval.semantic.contracts import (
    EmbeddingProvider,
    SemanticContextRecoveryError,
    SemanticHit,
    SemanticIndexCandidate,
    SemanticIndexIdentity,
    SemanticIndexStale,
    SemanticIndexStore,
    SemanticIndexUnavailable,
    SemanticQuery,
    SemanticRetrievalResult,
)
from trivae.retrieval.structured import (
    ORDERING_DESCRIPTION,
    CanonicalReadRepository,
    Coverage,
    MessageProjection,
    MessageQuery,
    RetrievalError,
    RetrievalMetadata,
)


class SemanticRetrieval:
    """只消费独立 vector store 与 canonical read port，不实现 lexical/hybrid fallback。"""

    def __init__(
        self,
        repository: CanonicalReadRepository,
        store: SemanticIndexStore,
        provider: EmbeddingProvider,
        *,
        database_identity: str,
        chunker: SemanticChunker | None = None,
        context_expander: ContextExpander | None = None,
    ) -> None:
        self.repository = repository
        self.store = store
        self.provider = provider
        self.database_identity = database_identity
        self.chunker = chunker or SemanticChunker(DEFAULT_SEMANTIC_CHUNK_CONFIG, SEMANTIC_CHUNKER_VERSION)
        self.context_expander = context_expander or ContextExpander(repository)

    @property
    def identity(self) -> SemanticIndexIdentity:
        """使用与 Builder 完全相同的 identity 组合规则。"""

        return SemanticIndexIdentity(
            database_identity=self.database_identity,
            embedding=self.provider.identity,
            chunker_version=self.chunker.version,
            chunker_config=self.chunker.config.to_dict(),
        )

    def search(self, query: SemanticQuery) -> SemanticRetrievalResult:
        """执行 dense candidate → canonical filters → range/context recovery 主链路。"""

        started = perf_counter()
        identity = self.identity
        state = self.store.state()
        if state is None:
            raise SemanticIndexUnavailable("semantic index is unavailable; build it first")
        if state.identity.serialized != identity.serialized:
            raise SemanticIndexStale("semantic index identity is stale; rebuild it")
        # 在 query embedding 前拒绝不可查询终态，避免 building/failed 状态仍加载模型。
        if state.status == "building":
            raise SemanticIndexUnavailable("semantic index is building")
        if state.status == "failed":
            raise SemanticIndexUnavailable(state.last_error or "semantic index build failed")
        if state.chunk_count <= 0:
            raise SemanticIndexUnavailable("semantic index has no vector chunks")

        canonical_count = self.repository.count_messages(MessageQuery(limit=1))
        if canonical_count != state.canonical_message_count:
            raise SemanticIndexStale("canonical message count changed; rebuild semantic index")

        limit = query.limit
        if limit is None:
            raise ValueError("semantic query limit must be present after validation")
        query_vector = self.provider.embed_query(query.query)
        # ANN k 是 bounded candidate pool，不将它误称为全局精确 total hits。
        candidate_pool = min(max(query.dense_top_k, limit * 4), 1000)
        candidates = self.store.dense_search(
            identity,
            query_vector,
            candidate_pool,
            session_ids=query.session_ids,
            start_timestamp=query.start_timestamp,
            end_timestamp=query.end_timestamp,
        )

        accepted: list[tuple[SemanticHit, int]] = []
        recovered_ranges: list[ContextRange] = []
        for candidate in candidates:
            messages = self._read_candidate_messages(candidate)
            if not self._matches_query_filters(messages, query):
                continue
            hit = SemanticHit(
                chunk_id=candidate.chunk_id,
                parent_id=candidate.parent_id,
                session_id=candidate.session_id,
                parent_start_message_id=candidate.parent_start_message_id,
                parent_end_message_id=candidate.parent_end_message_id,
                start_message_id=candidate.start_message_id,
                end_message_id=candidate.end_message_id,
                score=1.0 - candidate.distance,
                score_type="cosine_similarity",
                dense_rank=candidate.dense_rank,
                index_identity=identity.serialized,
            )
            accepted.append((hit, candidate.message_count))
            recovered_ranges.append(
                ContextRange(
                    session_id=candidate.session_id,
                    start_message_id=candidate.start_message_id,
                    end_message_id=candidate.end_message_id,
                    message_limit=candidate.message_count,
                )
            )
            if len(accepted) >= limit:
                break

        ranges = tuple(recovered_ranges)
        expansion = self.context_expander.expand_ranges(
            ranges,
            before=query.context_before,
            after=query.context_after,
            # 保留 semantic 的 bounded context 语义，同时不越过 ToolResultRecord 的 item bound。
            limit=min(max(limit, limit * 32), MAX_CONTEXT_EXPANSION_MESSAGES),
        )
        pool_exhausted = len(candidates) >= candidate_pool
        partial = state.status == "partial" or pool_exhausted or expansion.partial
        truncated = pool_exhausted or expansion.truncated
        latency_ms = (perf_counter() - started) * 1000
        return SemanticRetrievalResult(
            query=query,
            filters=query.to_dict(),
            strategy="semantic",
            hits=tuple(hit for hit, _ in accepted),
            expanded_messages=expansion.messages,
            total_hits=len(accepted),
            returned_messages=len(expansion.messages),
            coverage=Coverage(
                status="partial" if partial else "complete",
                basis="canonical_plus_partial_semantic_index" if partial else "canonical_plus_semantic_index",
            ),
            partial=partial,
            truncated=truncated,
            metadata=RetrievalMetadata(
                filters=query.to_dict(),
                ordering="cosine distance ASC, " + ORDERING_DESCRIPTION,
                latency_ms=latency_ms,
                details={
                    "index_identity": identity.to_dict(),
                    "index_status": state.status,
                    "canonical_message_count": canonical_count,
                    "indexed_message_count": state.indexed_message_count,
                    "indexed_chunk_count": state.chunk_count,
                    "dense_candidate_pool": candidate_pool,
                    "dense_candidates_returned": len(candidates),
                    "accepted_candidates": len(accepted),
                    "candidate_chunk_ids": [hit.chunk_id for hit, _ in accepted],
                    "candidate_parent_ids": [hit.parent_id for hit, _ in accepted],
                    "candidate_scores": [hit.score for hit, _ in accepted],
                    "score_type": "cosine_similarity",
                    "context_before": query.context_before,
                    "context_after": query.context_after,
                    "expanded_candidate_messages": expansion.candidate_count,
                    "context_source_hits": expansion.context_source_hits,
                    "context_source_budget": MAX_AUTOMATIC_CONTEXT_SOURCE_HITS,
                    "known_gaps": ("ann_candidate_pool",) if pool_exhausted else (),
                },
            ),
            primary_message_ids=expansion.primary_message_ids,
        )

    def _read_candidate_messages(self, candidate: SemanticIndexCandidate) -> tuple[MessageProjection, ...]:
        """从 semantic range 恢复 canonical projection，拒绝把 chunk 当 citation source。"""

        try:
            session_id = candidate.session_id
            start_message_id = candidate.start_message_id
            end_message_id = candidate.end_message_id
            message_count = candidate.message_count
            messages = self.repository.read_message_range(
                session_id,
                start_message_id,
                end_message_id,
                max(1, int(message_count)),
            )
        except (AttributeError, RetrievalError, ValueError, TypeError) as exc:
            raise SemanticContextRecoveryError("semantic candidate range could not be recovered") from exc
        if len(messages) != int(message_count):
            raise SemanticContextRecoveryError(
                f"semantic candidate range count mismatch: expected {message_count}, got {len(messages)}"
            )
        if any(message.session_id != session_id for message in messages):
            raise SemanticContextRecoveryError("semantic candidate range crossed session boundary")
        return messages

    @staticmethod
    def _matches_query_filters(messages: Sequence[MessageProjection], query: SemanticQuery) -> bool:
        """对无法安全下推到 vec0 的 canonical filters 做显式 any-message 约束。"""

        if not messages:
            return False
        for message in messages:
            if query.sender_user_ids is not None and message.sender_user_id not in query.sender_user_ids:
                continue
            if query.message_types is not None and message.message_type not in query.message_types:
                continue
            if query.source_message_id is not None and message.source_message_id != query.source_message_id:
                continue
            if (
                query.reply_to_source_message_id is not None
                and message.reply_to_source_message_id != query.reply_to_source_message_id
            ):
                continue
            return True
        return False
