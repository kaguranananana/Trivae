"""Regression for a selected high-ranked semantic range disappearing at the item bound."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.test_semantic_retrieval import _DeterministicProvider
from trivae.retrieval.semantic.contracts import SemanticIndexCandidate, SemanticQuery
from trivae.retrieval.semantic.retrieval import SemanticRetrieval
from trivae.retrieval.structured import MessageProjection


@pytest.mark.parametrize("literal_in_oldest", [False, True])
def test_semantic_capacity_preserves_rank_before_chronological_display(literal_in_oldest):
    messages = tuple(MessageProjection(
        internal_message_id=f"s:m{i}", session_id="s", source_message_id=f"m{i}",
        sender_user_id="u", sender_platform_id=None, sender_uin=None, sender_name="User",
        timestamp=i, seq=i, message_type="text", normalized_content="related evidence",
        reply_to_source_message_id=None, recalled=False, system=False, session_display="Session",
    ) for i in range(120))
    if literal_in_oldest:
        messages = (replace(messages[0], normalized_content="question"), *messages[1:])

    class Repository:
        def count_messages(self, query):
            return len(messages)

        def canonical_revision(self):
            return 0

        def forward_content_gaps(self, scope):
            return ()

        def read_message_range(self, session_id, start_message_id, end_message_id, limit):
            start = next(i for i, m in enumerate(messages) if m.internal_message_id == start_message_id)
            end = next(i for i, m in enumerate(messages) if m.internal_message_id == end_message_id)
            return messages[start:end + 1][:limit]

    class Store:
        def state(self):
            return SimpleNamespace(
                identity=retrieval.identity, status="completed", canonical_message_count=120,
                indexed_message_count=120, chunk_count=12, last_error=None, canonical_revision=0,
                forwarded_message_count=0, indexed_forwarded_message_count=0,
            )

        def dense_search(self, identity, vector, limit, **filters):
            return tuple(SemanticIndexCandidate(
                chunk_id=f"chunk-{rank}", parent_id=f"parent-{rank}", session_id="s",
                start_message_id=f"s:m{110 - (rank - 1) * 10}",
                end_message_id=f"s:m{119 - (rank - 1) * 10}",
                parent_start_message_id=f"s:m{110 - (rank - 1) * 10}",
                parent_end_message_id=f"s:m{119 - (rank - 1) * 10}",
                start_timestamp=110 - (rank - 1) * 10, end_timestamp=119 - (rank - 1) * 10,
                message_count=10, effective_chars=160, distance=rank / 100, dense_rank=rank,
            ) for rank in range(1, 13))

    retrieval = SemanticRetrieval(Repository(), Store(), _DeterministicProvider(), database_identity="test")
    result = retrieval.search(SemanticQuery(query="question", limit=12, context_before=0, context_after=0))
    ids = {m.internal_message_id for m in result.expanded_messages}
    assert len(ids) == 100
    assert {f"s:m{i}" for i in range(110, 120)} <= ids
    assert result.partial and result.truncated
    assert len(result.hits) == 12
    assert list(result.expanded_messages) == sorted(result.expanded_messages, key=lambda m: m.timestamp)
    if literal_in_oldest:
        assert "s:m0" in ids
        assert result.hits[0].dense_rank == 12
    else:
        assert "s:m0" not in ids
