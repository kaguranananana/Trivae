from __future__ import annotations

import json
import unittest

from trivae.capabilities import (
    CapabilityContractError,
    CapabilityRegistry,
    ExecutionScope,
    FindMembersCapability,
    FindMembersInput,
    SearchMessagesCapability,
    SearchMessagesInput,
    SemanticSearchCapability,
    SemanticSearchInput,
    ToolEnvelope,
)
from trivae.config.limits import (
    DEFAULT_LEXICAL_RESULT_LIMIT,
    DEFAULT_SEMANTIC_RESULT_LIMIT,
    DEFAULT_TOOL_RESULT_TOKEN_BUDGET,
    MAX_AUTOMATIC_CONTEXT_SOURCE_HITS,
    MAX_LEXICAL_RESULT_LIMIT,
    MAX_SEMANTIC_RESULT_LIMIT,
    MAX_STRUCTURED_RESULT_ITEMS,
    MAX_TRUSTED_RESULT_LIMIT,
)
from trivae.evaluation.contracts import ReviewPolicy
from trivae.evaluation.quality import FAILURE_LABELS, QUALITY_AXES
from trivae.query.evidence import (
    build_tool_result_record,
    project_tool_result_for_model,
)
from trivae.query.runtime.openai_tools import (
    ExecuteSQLSDKToolAdapter,
    FindMembersSDKToolAdapter,
    LexicalSearchSDKToolAdapter,
    SemanticSearchSDKToolAdapter,
)
from trivae.query.runtime.prompt import SYSTEM_PROMPT
from trivae.retrieval.context import ContextExpander
from trivae.retrieval.semantic.contracts import SemanticQuery, SemanticQueryError
from trivae.retrieval.structured import (
    Coverage,
    InvalidRetrievalQuery,
    LexicalQuery,
    MessageHit,
    MessageProjection,
    RetrievalMetadata,
    RetrievalResult,
)


def _message(index: int, content: str | None = None) -> MessageProjection:
    """构造可复用的 canonical message projection，避免测试直接依赖 SQLite row。"""

    return MessageProjection(
        internal_message_id=f"qq:budget:m{index}",
        session_id="qq:budget",
        source_message_id=f"source-{index}",
        sender_user_id="user-1",
        sender_platform_id=None,
        sender_uin=None,
        sender_name="Alice",
        timestamp=1_700_000_000_000 + index,
        seq=index,
        message_type="text",
        normalized_content=content or f"resource {index}",
        reply_to_source_message_id=None,
        recalled=False,
        system=False,
        session_display="Budget Fixture",
    )


class _LexicalStub:
    """只用于验证 Capability 在检索调用前拒绝越界 limit。"""

    def search(self, query):
        raise AssertionError("越界 lexical request must be rejected before retrieval")


class _SemanticStub:
    """只用于验证 semantic hard cap，不触碰 embedding 或 index。"""

    def search(self, query):
        raise AssertionError("越界 semantic request must be rejected before retrieval")


class _MemberStub:
    """只用于验证 member hard cap，不触碰身份存储。"""

    def read_member_candidates(self, query):
        raise AssertionError("越界 member request must be rejected before retrieval")


class _ContextRepository:
    """记录自动 context 读取次数，验证 direct-hit 与 source-hit budget。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def read_message_context(self, session_id, internal_message_id, before, after):
        self.calls.append(internal_message_id)
        return (_message(int(internal_message_id.rsplit("m", 1)[1])),)


class RetrievalBudgetTests(unittest.TestCase):
    """覆盖候选、扩展、transport 和模型投影之间的独立预算 contract。"""

    def test_budget_defaults_are_independent(self) -> None:
        self.assertEqual(DEFAULT_LEXICAL_RESULT_LIMIT, 1000)
        self.assertEqual(MAX_LEXICAL_RESULT_LIMIT, 5000)
        self.assertEqual(DEFAULT_SEMANTIC_RESULT_LIMIT, 10)
        self.assertEqual(MAX_SEMANTIC_RESULT_LIMIT, 20)
        self.assertEqual(MAX_TRUSTED_RESULT_LIMIT, 5000)
        self.assertEqual(MAX_STRUCTURED_RESULT_ITEMS, 100)
        self.assertEqual(MAX_AUTOMATIC_CONTEXT_SOURCE_HITS, 20)
        self.assertEqual(DEFAULT_TOOL_RESULT_TOKEN_BUDGET, 16_000)
        self.assertEqual(ExecutionScope().max_results, MAX_TRUSTED_RESULT_LIMIT)
        with self.assertRaises(CapabilityContractError):
            ExecutionScope(max_results=MAX_TRUSTED_RESULT_LIMIT + 1)
        self.assertEqual(SearchMessagesInput(keyword="inventory").limit, DEFAULT_LEXICAL_RESULT_LIMIT)
        self.assertEqual(LexicalQuery(keyword="inventory").limit, DEFAULT_LEXICAL_RESULT_LIMIT)
        self.assertEqual(SemanticSearchInput(query="inventory").limit, DEFAULT_SEMANTIC_RESULT_LIMIT)
        self.assertEqual(SemanticSearchInput(query="inventory").dense_top_k, 40)
        with self.assertRaises(InvalidRetrievalQuery):
            LexicalQuery(keyword="inventory", limit=MAX_LEXICAL_RESULT_LIMIT + 1)
        with self.assertRaises(SemanticQueryError):
            SemanticQuery(query="inventory", limit=MAX_SEMANTIC_RESULT_LIMIT + 1)

    def test_capability_hard_caps_are_independent_of_trusted_umbrella(self) -> None:
        scope = ExecutionScope()
        with self.assertRaises(CapabilityContractError):
            SearchMessagesCapability(_LexicalStub()).execute(
                SearchMessagesInput(keyword="inventory", limit=MAX_LEXICAL_RESULT_LIMIT + 1), scope
            )
        with self.assertRaises(CapabilityContractError):
            SemanticSearchCapability(_SemanticStub()).execute(
                SemanticSearchInput(query="inventory", limit=MAX_SEMANTIC_RESULT_LIMIT + 1), scope
            )
        with self.assertRaises(CapabilityContractError):
            FindMembersCapability(_MemberStub()).execute(
                FindMembersInput(query="Alice", limit=MAX_STRUCTURED_RESULT_ITEMS + 1), scope
            )

    def test_provider_schemas_expose_tool_specific_maximums(self) -> None:
        registry = CapabilityRegistry()
        lexical = LexicalSearchSDKToolAdapter(registry).as_sdk_tool(trusted_max_results=MAX_TRUSTED_RESULT_LIMIT)
        semantic = SemanticSearchSDKToolAdapter(registry).as_sdk_tool(trusted_max_results=MAX_TRUSTED_RESULT_LIMIT)
        member = FindMembersSDKToolAdapter(registry).as_sdk_tool(trusted_max_results=MAX_TRUSTED_RESULT_LIMIT)
        sql = ExecuteSQLSDKToolAdapter(registry).as_sdk_tool(trusted_max_results=MAX_TRUSTED_RESULT_LIMIT)

        self.assertEqual(lexical.params_json_schema["properties"]["limit"]["maximum"], 5000)
        self.assertEqual(lexical.params_json_schema["properties"]["limit"]["default"], 1000)
        self.assertEqual(semantic.params_json_schema["properties"]["limit"]["maximum"], 20)
        self.assertEqual(semantic.params_json_schema["properties"]["limit"]["default"], 10)
        self.assertEqual(member.params_json_schema["properties"]["limit"]["maximum"], 100)
        self.assertEqual(member.params_json_schema["properties"]["limit"]["default"], 20)
        self.assertEqual(sql.params_json_schema["properties"]["max_rows"]["maximum"], 100)

    def test_direct_hits_fill_capacity_without_neighbor_reads(self) -> None:
        repository = _ContextRepository()
        # 100 条 direct hit 是真实 inventory 边界；邻居不能把任何一条挤出最终容量。
        hits = tuple(MessageHit(_message(index), ("inventory",), 1.0, "test") for index in range(100))

        result = ContextExpander(repository).expand(hits, before=2, after=2, limit=100)

        self.assertEqual(repository.calls, [])
        self.assertEqual(
            [message.internal_message_id for message in result.messages],
            [message.message.internal_message_id for message in hits],
        )
        self.assertEqual(result.primary_message_ids, tuple(message.message.internal_message_id for message in hits))

    def test_automatic_context_reads_only_bounded_source_hits(self) -> None:
        repository = _ContextRepository()
        hits = tuple(MessageHit(_message(index), ("inventory",), 1.0, "test") for index in range(30))

        result = ContextExpander(repository).expand(hits, before=1, after=1, limit=100)

        self.assertEqual(len(repository.calls), MAX_AUTOMATIC_CONTEXT_SOURCE_HITS)
        self.assertEqual(len(result.messages), len(hits))
        self.assertEqual(result.candidate_count, len(hits))

    def test_canonical_record_accepts_large_message_candidate_set(self) -> None:
        messages = tuple(_message(index, "resource " + ("detail " * 20)) for index in range(150))
        retrieval = RetrievalResult(
            query=LexicalQuery(keyword="resource", limit=150, context_before=0, context_after=0),
            filters={},
            strategy="lexical",
            hits=tuple(MessageHit(message, ("resource",), 1.0, "test") for message in messages),
            expanded_messages=(),
            total_hits=len(messages),
            returned_messages=len(messages),
            coverage=Coverage("complete", "canonical_plus_lexical_index"),
            partial=False,
            truncated=False,
            metadata=RetrievalMetadata(filters={}, ordering="test", latency_ms=0.0),
        )

        record = build_tool_result_record(
            run_id="run-budget",
            tool_call_id="run-budget/tool-call/1",
            tool_result_id="run-budget/tool-call/1/result",
            tool_name="lexical_search",
            envelope=ToolEnvelope("ok", retrieval, {}, None),
            scope=ExecutionScope(max_results=150),
        )

        self.assertEqual(len(record.message_items), 150)
        self.assertEqual(len(record.structured_items), 0)

    def test_model_projection_omits_tail_hits_explicitly_when_16k_is_exceeded(self) -> None:
        messages = tuple(
            _message(index, f"resource {index} " + ("long evidence " * 120))
            for index in range(500)
        )
        retrieval = RetrievalResult(
            query=LexicalQuery(keyword="resource", limit=500, context_before=0, context_after=0),
            filters={},
            strategy="lexical",
            hits=tuple(MessageHit(message, ("resource",), 1.0, "test") for message in messages),
            expanded_messages=(),
            total_hits=len(messages),
            returned_messages=len(messages),
            coverage=Coverage("complete", "canonical_plus_lexical_index"),
            partial=False,
            truncated=False,
            metadata=RetrievalMetadata(filters={}, ordering="test", latency_ms=0.0),
        )
        envelope = ToolEnvelope("ok", retrieval, {}, None)
        record = build_tool_result_record(
            run_id="run-projection",
            tool_call_id="run-projection/tool-call/1",
            tool_result_id="run-projection/tool-call/1/result",
            tool_name="lexical_search",
            envelope=envelope,
            scope=ExecutionScope(max_results=500),
        )

        projected = project_tool_result_for_model(envelope, record)
        metrics = projected["model_projection"]

        self.assertTrue(metrics["truncated"])
        self.assertGreater(metrics["omitted_hit_messages"], 0)
        self.assertLessEqual(metrics["estimated_tokens"], DEFAULT_TOOL_RESULT_TOKEN_BUDGET)
        self.assertEqual(
            len(projected["provenance"]["message_sources"]),
            len(projected["data"]["hits"]),
        )
        self.assertNotIn("internal_message_id", json.dumps(projected, ensure_ascii=False))

    def test_answer_safety_and_review_taxonomy_are_explicit_contracts(self) -> None:
        for phrase in (
            "mention does not mean recommendation",
            "intent to test does not prove actual use",
            "reviewing output does not prove personal installation or use",
            "hit count does not equal unique entity count",
            "partial or truncated",
        ):
            self.assertIn(phrase, SYSTEM_PROMPT)

        self.assertEqual(
            set(QUALITY_AXES),
            {
                "retrieval_recall",
                "evidence_coverage",
                "citation_validity",
                "claim_evidence_entailment",
                "enumeration_completeness",
                "overclaim_unsupported_inference",
                "user_facing_readability",
            },
        )
        self.assertEqual(
            set(ReviewPolicy().quality_axes),
            set(QUALITY_AXES),
        )
        self.assertEqual(
            set(FAILURE_LABELS),
            {
                "MENTION_TO_RECOMMENDATION",
                "INTENT_TO_ACTUAL_USE",
                "REVIEW_TO_PERSONAL_USAGE",
                "HIT_COUNT_TO_UNIQUE_ENTITY_COUNT",
                "PARTIAL_TO_NEGATIVE_ASSERTION",
                "MISSING_EXPLICIT_RESOURCE",
                "ENUMERATION_INCOMPLETE",
            },
        )


if __name__ == "__main__":
    unittest.main()
