"""语义候选池内的真实字面证据必须通过排序、容量裁剪和 Host 投影。"""

from __future__ import annotations

import unittest
from dataclasses import replace

from tests.test_semantic_retrieval import _DeterministicProvider
from trivae.capabilities import ExecutionScope, ToolEnvelope
from trivae.query.evidence import build_tool_result_record, project_tool_result_for_model
from trivae.retrieval.semantic.contracts import (
    SemanticIndexCandidate,
    SemanticIndexState,
    SemanticQuery,
)
from trivae.retrieval.semantic.retrieval import SemanticRetrieval
from trivae.retrieval.structured import ForwardProvenance, MessageProjection


def _message(index: int, text: str, *, forwarded: bool = False) -> MessageProjection:
    """生成有确定时间顺序的真实消息形状，转发位置拥有独立 occurrence。"""

    root_id = f"session:outer-{index}"
    return MessageProjection(
        internal_message_id=f"{root_id}#forward:0.0" if forwarded else f"session:m{index}",
        session_id="session",
        source_message_id="original",
        sender_user_id="author",
        sender_platform_id=None,
        sender_uin=None,
        sender_name="Author",
        timestamp=1000 + index,
        seq=index,
        message_type="text",
        normalized_content=text,
        reply_to_source_message_id="reply",
        recalled=False,
        system=False,
        session_display="Ranking Fixture",
        forward=(
            ForwardProvenance(root_id, root_id, "content.elements[0].data.messages[0]", 100, f"outer-{index}")
            if forwarded
            else None
        ),
    )


class _RankingRepository:
    """仅实现本回归使用的 canonical range 读取，不运行模型或访问真实数据库。"""

    def __init__(self, groups: list[tuple[MessageProjection, ...]]) -> None:
        self.ranges = {
            (group[0].session_id, group[0].internal_message_id, group[-1].internal_message_id): group
            for group in groups
        }
        self.messages = {message.internal_message_id: message for group in groups for message in group}

    def count_messages(self, query) -> int:
        # 父消息统计是独立 canonical 事实，不把本 fixture 的转发正文当作普通群消息计数。
        return 1000

    def canonical_revision(self) -> int:
        return 1

    def forward_content_gaps(self, scope) -> tuple[str, ...]:
        return ()

    def read_message_range(self, session_id, start_message_id, end_message_id, limit):
        return self.ranges[(session_id, start_message_id, end_message_id)][:limit]


class _RankingStore:
    """返回已知 dense 排名，完整复现排序与 limit 边界而不伪称 embedding 质量评测。"""

    def __init__(self, groups: list[tuple[MessageProjection, ...]]) -> None:
        self.index_state = None
        self.search_limits: list[int] = []
        self.candidates = tuple(
            SemanticIndexCandidate(
                chunk_id=f"chunk-{rank}",
                parent_id=f"parent-{rank}",
                session_id=group[0].session_id,
                parent_start_message_id=group[0].internal_message_id,
                parent_end_message_id=group[-1].internal_message_id,
                start_message_id=group[0].internal_message_id,
                end_message_id=group[-1].internal_message_id,
                start_timestamp=group[0].timestamp,
                end_timestamp=group[-1].timestamp,
                message_count=len(group),
                effective_chars=sum(len(message.normalized_content) for message in group),
                distance=rank / 100,
                dense_rank=rank,
            )
            for rank, group in enumerate(groups, start=1)
        )

    def state(self):
        return self.index_state

    def dense_search(self, identity, query_vector, limit, **kwargs):
        # 只返回原有池允许的候选；测试可直接证明没有扩 k 或额外检索调用。
        self.search_limits.append(limit)
        return self.candidates[:limit]


def _retrieval(groups: list[tuple[MessageProjection, ...]]):
    """连接真实 Retrieval 和 ContextExpander，候选与正文由可核验 fixture 提供。"""

    repository = _RankingRepository(groups)
    store = _RankingStore(groups)
    provider = _DeterministicProvider()
    retrieval = SemanticRetrieval(repository, store, provider, database_identity="ranking-fixture")
    store.index_state = SemanticIndexState(
        identity=retrieval.identity,
        status="completed",
        canonical_message_count=1000,
        indexed_message_count=1000,
        chunk_count=len(groups),
        last_error=None,
        updated_at=1,
        canonical_revision=1,
    )
    return retrieval, store, provider


def _query(text: str, *, limit: int = 20, **filters) -> SemanticQuery:
    """关闭邻居以隔离本回归检查的候选正文与核心容量。"""

    return SemanticQuery(query=text, limit=limit, context_before=0, context_after=0, **filters)


class SemanticLiteralRankingTests(unittest.TestCase):
    """完整查询串是通用重排信号，只能作用于原有池中通过硬过滤的真实正文。"""

    def test_rank_28_literal_is_promoted_before_limit_without_changing_the_pool(self) -> None:
        """真实失败形状：目标已在 80 池中，不能先截前 20 再检查正文。"""

        groups = [(_message(rank, "Conceptually related discussion"),) for rank in range(1, 31)]
        target = _message(28, "A MiXeD Needle in the actual body", forwarded=True)
        groups[27] = (target,)
        retrieval, store, provider = _retrieval(groups)
        result = retrieval.search(_query("mixed needle"))
        self.assertEqual(result.hits[0].dense_rank, 28)
        self.assertAlmostEqual(result.hits[0].score, 0.72)
        self.assertEqual(result.hits[0].score_type, "cosine_similarity")
        self.assertEqual(len(result.hits), 20)
        self.assertEqual(result.primary_message_ids[0], target.internal_message_id)
        self.assertEqual(result.metadata.details["literal_candidate_count"], 1)
        self.assertEqual(result.metadata.details["literal_message_ids"], (target.internal_message_id,))
        self.assertEqual(result.metadata.details["ranking_strategy"], "literal_then_dense_v1")
        self.assertEqual(store.search_limits, [80])
        self.assertEqual(provider.query_texts, ["mixed needle"])

    def test_no_literal_preserves_dense_rank_and_existing_message_order(self) -> None:
        """无字面匹配时仍按 dense 排名选候选，消息展示保持既有时间顺序。"""

        groups = [(_message(rank, "Related conceptual discussion"),) for rank in (30, 20, 10)]
        retrieval, store, _ = _retrieval(groups)
        result = retrieval.search(_query("different wording", limit=2))
        self.assertEqual([hit.dense_rank for hit in result.hits], [1, 2])
        self.assertEqual([message.seq for message in result.expanded_messages], [20, 30])
        self.assertEqual(result.metadata.details["literal_candidate_count"], 0)
        self.assertEqual(result.metadata.details["literal_message_ids"], ())
        self.assertEqual(store.search_limits, [40])

    def test_literal_match_never_bypasses_any_hard_filter(self) -> None:
        """群、转发时间、发送者、类型和 source/reply 条件都必须在重排前执行。"""

        cases = (
            ({"session_id": "outside"}, {"session_ids": ("session",)}),
            ({"timestamp": 10}, {"start_timestamp": 1000}),
            ({"timestamp": 2000}, {"end_timestamp": 2000}),
            ({"sender_user_id": "outside"}, {"sender_user_ids": ("author",)}),
            ({"message_type": "image"}, {"message_types": ("text",)}),
            ({"source_message_id": "outside"}, {"session_ids": ("session",), "source_message_id": "original"}),
            ({"reply_to_source_message_id": "outside"}, {"session_ids": ("session",), "reply_to_source_message_id": "reply"}),
        )
        for changed_fields, filters in cases:
            with self.subTest(changed_fields=changed_fields):
                disallowed = replace(_message(1, "Exact Query", forwarded=True), **changed_fields)
                allowed = _message(2, "Related conceptual wording", forwarded=True)
                retrieval, _, _ = _retrieval([(disallowed,), (allowed,)])
                result = retrieval.search(_query("Exact Query", limit=1, **filters))
                self.assertEqual([hit.dense_rank for hit in result.hits], [2])
                self.assertEqual(result.metadata.details["literal_candidate_count"], 0)
                self.assertEqual(result.metadata.details["literal_message_ids"], ())

    def test_literal_only_in_a_filtered_out_child_does_not_boost_its_chunk(self) -> None:
        """同 chunk 中其他发送者的字面内容不能给当前发送者的候选虚增优先级。"""

        outside = replace(_message(1, "Exact Query"), sender_user_id="outside")
        allowed_context = _message(2, "Conceptually related text")
        target = _message(3, "Exact Query", forwarded=True)
        retrieval, _, _ = _retrieval([(outside, allowed_context), (target,)])
        result = retrieval.search(_query("Exact Query", limit=1, sender_user_ids=("author",)))
        self.assertEqual([hit.dense_rank for hit in result.hits], [2])
        self.assertEqual(result.metadata.details["literal_candidate_count"], 1)
        self.assertEqual(result.primary_message_ids, (target.internal_message_id,))

    def test_overlapping_chunks_deduplicate_occurrences_without_collapsing_reposts(self) -> None:
        """重叠候选复用同一来源，另一个转发父消息的相同正文仍是独立证据。"""

        first = _message(1, "Exact Query", forwarded=True)
        context = _message(2, "Other content")
        repost = _message(3, "Exact Query", forwarded=True)
        retrieval, _, _ = _retrieval([(first, context), (first,), (repost,)])
        result = retrieval.search(_query("Exact Query", limit=3))
        self.assertEqual([hit.dense_rank for hit in result.hits], [1, 3])
        self.assertEqual(len(result.expanded_messages), 3)
        self.assertEqual(result.primary_message_ids[:2], (first.internal_message_id, repost.internal_message_id))
        self.assertEqual(result.metadata.details["literal_candidate_count"], 3)

    def test_literal_outside_the_existing_dense_pool_is_not_silently_added(self) -> None:
        """本修复只重排现有候选，不借助 FTS、重试或扩池补入未召回消息。"""

        groups = [(_message(rank, "Related meaning"),) for rank in range(1, 91)]
        groups[89] = (_message(90, "Exact Query", forwarded=True),)
        retrieval, store, _ = _retrieval(groups)
        result = retrieval.search(_query("Exact Query"))
        self.assertEqual(store.search_limits, [80])
        self.assertEqual(result.metadata.details["literal_candidate_count"], 0)
        self.assertNotIn(groups[89][0].internal_message_id, result.primary_message_ids)

    def test_late_literal_survives_100_message_capacity_and_host_projection(self) -> None:
        """更早的非字面核心填满容量后，晚期具体子消息仍必须交给回答模型引用。"""

        groups = [
            tuple(_message(rank * 10 + offset, "Related discussion " * 30) for offset in range(10))
            for rank in range(1, 31)
        ]
        target = _message(10_000, "Exact Query " + "evidence details " * 60, forwarded=True)
        groups[27] = (target,)
        retrieval, _, _ = _retrieval(groups)
        result = retrieval.search(_query("Exact Query"))
        self.assertEqual(len(result.expanded_messages), 100)
        self.assertTrue(result.partial)
        self.assertTrue(result.truncated)
        self.assertEqual(result.expanded_messages[-1].internal_message_id, target.internal_message_id)
        self.assertEqual(result.primary_message_ids[0], target.internal_message_id)
        envelope = ToolEnvelope("partial", result, {"truncated": True}, None)
        record = build_tool_result_record(
            run_id="literal-run",
            tool_call_id="literal-run/tool-call/1",
            tool_result_id="literal-run/tool-call/1/result",
            tool_name="semantic_search",
            envelope=envelope,
            scope=ExecutionScope(allowed_session_ids=("session",), max_results=20),
        )
        # Host 保留来源优先序；对外的 canonical expanded_messages 仍按时间展示。
        self.assertEqual(record.message_items[0].message.internal_message_id, target.internal_message_id)
        payload = project_tool_result_for_model(envelope, record, token_budget=3000)
        visible = payload["data"]["expanded_messages"]
        self.assertGreater(payload["model_projection"]["omitted_hit_messages"], 0)
        self.assertEqual(visible[0]["source_id"], record.message_source_handle(record.message_items[0]))
        self.assertIn("Exact Query", visible[0]["content"])
        self.assertNotIn("literal_message_ids", payload["data"]["metadata"]["details"])


if __name__ == "__main__":
    unittest.main()
