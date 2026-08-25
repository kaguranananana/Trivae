from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from tests.test_ingestion import make_message, write_export
from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecutionScope
from trivae.capabilities.contracts import ToolEnvelope
from trivae.query.contracts import QueryRequest
from trivae.query.evidence import (
    MAX_FIELD_CHARS,
    AnswerArtifact,
    AnswerContentBlock,
    AnswerContractError,
    AnswerFinalizationError,
    CitationBinding,
    EvidenceItem,
    EvidenceSource,
    MessageDisplaySnapshot,
    MessageSource,
    ModelAnswerCandidate,
    ModelAnswerClaim,
    SourceHandleReference,
    StructuredSource,
    ToolMessageItem,
    ToolResultRecord,
    ToolStructuredItem,
    build_tool_result_record,
    extract_urls,
    finalize_answer,
    parse_model_answer_candidate,
    project_tool_result_for_model,
    scope_snapshot,
    validate_answer_artifact,
)
from trivae.query.orchestrator import QueryOrchestrator
from trivae.query.planner import SoftPlanner
from trivae.query.router import RuleRouter
from trivae.query.runtime.contracts import RuntimeResult
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter
from trivae.retrieval.semantic.contracts import SemanticHit, SemanticQuery, SemanticRetrievalResult
from trivae.retrieval.structured import (
    Coverage,
    LexicalQuery,
    MessageHit,
    MessageProjection,
    MessageQuery,
    RetrievalMetadata,
    RetrievalResult,
    StructuredMessageResult,
)


def _message(
    *,
    internal_message_id: str = "qq:100:m1",
    session_id: str = "qq:100",
    timestamp: int = 1_000,
    content: str = "canonical content",
    session_display: str = "Trusted Session",
) -> MessageProjection:
    """构造只包含 Retrieval projection 的 deterministic message。"""

    return MessageProjection(
        internal_message_id=internal_message_id,
        session_id=session_id,
        source_message_id="m1",
        sender_user_id="qq:u1",
        sender_platform_id="u1",
        sender_uin="10001",
        sender_name="Trusted Author",
        timestamp=timestamp,
        seq=1,
        message_type="text",
        normalized_content=content,
        reply_to_source_message_id=None,
        recalled=False,
        system=False,
        session_display=session_display,
    )


def _record(
    *,
    run_id: str = "run-current",
    scope: ExecutionScope | None = None,
    message: MessageProjection | None = None,
    status: str = "ok",
) -> ToolResultRecord:
    """创建包含 message 与 aggregate locator 的 current-run Tool Result。"""

    effective_scope = scope or ExecutionScope(allowed_session_ids=("qq:100",), start_timestamp=900, end_timestamp=1_100)
    effective_message = message or _message()
    return ToolResultRecord(
        run_id=run_id,
        tool_call_id=f"{run_id}/tool-call/1",
        tool_result_id=f"{run_id}/tool-call/1/result",
        tool_name="search_messages",
        status=status,  # type: ignore[arg-type]
        scope_snapshot=scope_snapshot(effective_scope),
        query_scope_snapshot={"session_ids": ("qq:100",), "keyword": "alpha"},
        message_items=(ToolMessageItem("message/qq:100:m1", effective_message),),
        structured_items=(ToolStructuredItem("aggregate", "total_count", 182),),
        limitations=("tool_result_partial",) if status == "partial" else (),
    )


def _message_source(record: ToolResultRecord, *, snapshot: MessageDisplaySnapshot | None = None) -> MessageSource:
    """只使用 Tool Result 给模型的 locator，snapshot 仅用于验证会被 trusted hydrate 覆盖。"""

    return MessageSource(
        run_id=record.run_id,
        tool_call_id=record.tool_call_id,
        tool_result_id=record.tool_result_id,
        result_item_id="message/qq:100:m1",
        session_id="qq:100",
        internal_message_id="qq:100:m1",
        snapshot=snapshot,
    )


def _artifact(source: MessageSource | StructuredSource, *, sufficiency: str = "sufficient") -> AnswerArtifact:
    """构造一个 claim→Evidence→Source 的最小 Artifact。"""

    return AnswerArtifact(
        content_blocks=(AnswerContentBlock("claim-1", "The finding is grounded."),),
        citation_bindings=(CitationBinding("claim-1", ("e1",)),),
        evidence_items=(
            EvidenceItem(
                evidence_id="e1",
                finding="The finding is grounded.",
                criterion="The current result contains a matching source.",
                sufficiency=sufficiency,  # type: ignore[arg-type]
                sources=(EvidenceSource("supports", source),),
            ),
        ),
    )


class EvidenceContractTests(unittest.TestCase):
    """验证 Evidence/Citation domain contract 的 good/base/bad cases。"""

    def test_model_provenance_entries_use_short_handles(self) -> None:
        """模型只拿到短 handle；full current-run locator 继续留在 Host record。"""

        record = _record()
        provenance = record.to_model_provenance()

        message_source = provenance["message_sources"][0]
        self.assertEqual(provenance["tool_result_scope"], "1")
        self.assertEqual(message_source, {"type": "message", "source_id": "m1-1"})

        structured_source = provenance["structured_sources"][0]
        self.assertEqual(
            structured_source,
            {
                "type": "structured",
                "source_id": "s1-1",
                "locator_kind": "aggregate",
                "locator": "total_count",
            },
        )
        self.assertNotIn("run_id", provenance)
        self.assertNotIn("internal_message_id", message_source)

    def test_identity_only_structured_source_hydrates_exact_tool_value(self) -> None:
        """模型只引用 source identity 时，Finalizer 仍从 current Tool Result 取可信值。"""

        record = _record()
        payload = {
            "content_blocks": [{"block_id": "claim-1", "text": "共有 182 条。"}],
            "citation_bindings": [{"content_block_id": "claim-1", "evidence_ids": ["e1"]}],
            "evidence_items": [
                {
                    "evidence_id": "e1",
                    "finding": "当前结构化结果返回总数。",
                    "criterion": "aggregate source identity 存在于当前 Tool Result。",
                    "sufficiency": "sufficient",
                    "sources": [
                        {
                            "relation": "supports",
                            "source": {
                                "type": "structured",
                                "run_id": record.run_id,
                                "tool_call_id": record.tool_call_id,
                                "tool_result_id": record.tool_result_id,
                                "source_id": "aggregate:total_count",
                                "locator_kind": "aggregate",
                                "locator": "total_count",
                            },
                        }
                    ],
                    "limitations": [],
                }
            ],
            "limitations": [],
        }

        finalized = finalize_answer(
            json.dumps(payload),
            run_id=record.run_id,
            tool_results=(record,),
            scope=ExecutionScope(allowed_session_ids=("qq:100",), start_timestamp=900, end_timestamp=1_100),
        )

        reference = finalized.evidence_items[0].sources[0].reference
        self.assertIsInstance(reference, StructuredSource)
        assert isinstance(reference, StructuredSource)
        self.assertEqual(reference.value_snapshot, 182)
        self.assertEqual(reference.source_id, "aggregate:total_count")

    def test_model_candidate_host_generates_artifact_identity_and_resolves_message_handle(self) -> None:
        """模型只表达 claim/handle，Host 生成 Artifact IDs 并 hydrate 完整消息来源。"""

        record = _record()
        output = json.dumps(
            {
                "claims": [
                    {
                        "text": "当前结果包含该消息。",
                        "finding": "canonical message is present",
                        "criterion": "the source handle resolves in the current result",
                        "sufficiency": "sufficient",
                        "sources": ["m1-1"],
                        "limitations": [],
                    }
                ],
                "limitations": [],
            },
            ensure_ascii=False,
        )

        parsed = parse_model_answer_candidate(output)
        self.assertIsInstance(parsed, ModelAnswerCandidate)
        self.assertIsInstance(parsed.claims[0], ModelAnswerClaim)
        finalized = finalize_answer(
            output,
            run_id=record.run_id,
            tool_results=(record,),
            scope=ExecutionScope(allowed_session_ids=("qq:100",), start_timestamp=900, end_timestamp=1_100),
        )

        self.assertEqual(finalized.content_blocks[0].block_id, "claim-1")
        self.assertEqual(finalized.evidence_items[0].evidence_id, "e1")
        reference = finalized.evidence_items[0].sources[0].reference
        self.assertNotIsInstance(reference, SourceHandleReference)
        self.assertIsInstance(reference, MessageSource)
        assert isinstance(reference, MessageSource)
        self.assertEqual(reference.tool_result_id, record.tool_result_id)
        self.assertEqual(reference.internal_message_id, "qq:100:m1")
        self.assertIsNotNone(reference.snapshot)

    def test_model_candidate_unknown_handle_fails_with_source_path(self) -> None:
        """未知 handle 必须显式失败，不能被 Host 删除或猜测成另一条来源。"""

        record = _record()
        output = json.dumps(
            {
                "claims": [
                    {
                        "text": "unsupported",
                        "finding": "missing source",
                        "criterion": "source must be current",
                        "sufficiency": "insufficient",
                        "sources": ["m99-1"],
                        "limitations": [],
                    }
                ],
                "limitations": [],
            }
        )

        with self.assertRaises(AnswerFinalizationError) as context:
            finalize_answer(
                output,
                run_id=record.run_id,
                tool_results=(record,),
                scope=ExecutionScope(allowed_session_ids=("qq:100",), start_timestamp=900, end_timestamp=1_100),
            )
        self.assertEqual(context.exception.code, "UNRESOLVED_SOURCE_HANDLE")
        self.assertEqual(context.exception.path, "evidence_items[0].sources[0].source")

    def test_model_tool_projection_does_not_copy_full_message_provenance(self) -> None:
        """Tool Result model projection保留语义字段和 handle，但不搬运内部 IDs。"""

        record = _record()
        envelope = ToolEnvelope("ok", None, {}, None)
        projected = project_tool_result_for_model(envelope, record, token_budget=8_000)
        serialized = json.dumps(projected, ensure_ascii=False)

        self.assertEqual(projected["provenance"]["message_sources"], [])
        self.assertNotIn("internal_message_id", serialized)
        self.assertNotIn(record.tool_call_id, serialized)
        self.assertIn("model_projection", projected)

    def test_expanded_messages_receive_current_run_provenance(self) -> None:
        """命中消息和 bounded context 都必须成为可验证的 source entry。"""

        hit = _message(internal_message_id="qq:100:hit", content="alpha hit")
        expanded = _message(internal_message_id="qq:100:context", content="nearby context")
        retrieval = RetrievalResult(
            query=LexicalQuery(keyword="alpha", limit=2),
            filters={},
            strategy="lexical",
            hits=(MessageHit(hit, ("alpha",), 1.0, "test"),),
            expanded_messages=(expanded,),
            total_hits=1,
            returned_messages=2,
            coverage=Coverage("complete", "canonical_plus_lexical_index"),
            partial=False,
            truncated=False,
            metadata=RetrievalMetadata(filters={}, ordering="test", latency_ms=0.0),
        )
        record = build_tool_result_record(
            run_id="run-expanded",
            tool_call_id="run-expanded/tool-call/1",
            tool_result_id="run-expanded/tool-call/1/result",
            tool_name="search_messages",
            envelope=ToolEnvelope("ok", retrieval, {}, None),
            scope=ExecutionScope(),
        )

        source_ids = {source["source_id"] for source in record.to_model_provenance()["message_sources"]}
        self.assertEqual(source_ids, {"m1-1", "m1-2"})

        projected = project_tool_result_for_model(ToolEnvelope("ok", retrieval, {}, None), record)
        serialized = json.dumps(projected, ensure_ascii=False)
        hit_message = projected["data"]["hits"][0]["message"]
        context_message = projected["data"]["expanded_messages"][0]
        self.assertEqual(hit_message["source_id"], "m1-1")
        self.assertEqual(context_message["source_id"], "m1-2")
        self.assertNotIn("internal_message_id", serialized)
        self.assertNotIn("run-expanded/tool-call/1", serialized)

    def test_semantic_projection_preserves_core_and_omits_context(self) -> None:
        """semantic range 核心是命中，邻近消息只能作为可省略 context。"""

        messages = tuple(
            _message(
                internal_message_id=f"qq:100:semantic-{index}",
                timestamp=1_000 + index,
                content=f"semantic message {index} " + ("with enough context to exercise trimming " * 24),
            )
            for index in range(40)
        )
        semantic = SemanticRetrievalResult(
            query=SemanticQuery(query="meaning", limit=1),
            filters={},
            strategy="semantic",
            hits=(
                SemanticHit(
                    chunk_id="chunk-id-1",
                    parent_id="parent-id-1",
                    session_id="qq:100",
                    parent_start_message_id=messages[0].internal_message_id,
                    parent_end_message_id=messages[1].internal_message_id,
                    start_message_id=messages[0].internal_message_id,
                    end_message_id=messages[1].internal_message_id,
                    score=0.91,
                    score_type="cosine_similarity",
                    dense_rank=1,
                    index_identity="index-identity-must-stay-host-side",
                ),
            ),
            expanded_messages=messages,
            total_hits=1,
            returned_messages=len(messages),
            coverage=Coverage("complete", "canonical_plus_semantic_index"),
            partial=False,
            truncated=False,
            metadata=RetrievalMetadata(
                filters={},
                ordering="cosine distance ASC",
                latency_ms=0.0,
                details={
                    "index_identity": "index-identity-must-stay-host-side",
                    "candidate_chunk_ids": ["chunk-id-1"],
                    "candidate_parent_ids": ["parent-id-1"],
                    "candidate_scores": [0.91],
                },
            ),
            primary_message_ids=tuple(message.internal_message_id for message in messages[:2]),
        )
        envelope = ToolEnvelope("ok", semantic, {}, None)
        record = build_tool_result_record(
            run_id="run-semantic",
            tool_call_id="run-semantic/tool-call/1",
            tool_result_id="run-semantic/tool-call/1/result",
            tool_name="semantic_search",
            envelope=envelope,
            scope=ExecutionScope(),
        )

        projected = project_tool_result_for_model(envelope, record, token_budget=8_000)
        serialized = json.dumps(projected, ensure_ascii=False)
        projected_messages = projected["data"]["expanded_messages"]

        self.assertEqual(len(projected_messages), 2)
        self.assertEqual([item["hit"] for item in projected_messages], [True, True])
        self.assertEqual(projected["model_projection"]["omitted_context_messages"], 38)
        self.assertTrue(projected["model_projection"]["truncated"])
        self.assertEqual(len(projected["provenance"]["message_sources"]), 2)
        self.assertNotIn("m1-40", {item["source_id"] for item in projected["provenance"]["message_sources"]})
        self.assertNotIn("internal_message_id", serialized)
        self.assertNotIn("chunk-id-1", serialized)
        self.assertNotIn("index-identity-must-stay-host-side", serialized)

    def test_mixed_tool_result_locator_remains_unresolved(self) -> None:
        """不同 Tool Result 的父级 identity 与 message item 不得被拼成合法引用。"""

        base_record = _record(run_id="run-mixed")
        empty_record = replace(
            base_record,
            tool_call_id="run-mixed/tool-call/1",
            tool_result_id="run-mixed/tool-call/1/result",
            message_items=(),
        )
        message_record = replace(
            base_record,
            tool_call_id="run-mixed/tool-call/2",
            tool_result_id="run-mixed/tool-call/2/result",
        )
        mixed_source = replace_source(
            _message_source(message_record),
            tool_call_id=empty_record.tool_call_id,
            tool_result_id=empty_record.tool_result_id,
        )

        with self.assertRaises(AnswerFinalizationError) as raised:
            validate_answer_artifact(
                _artifact(mixed_source),
                run_id="run-mixed",
                tool_results=(empty_record, message_record),
                scope=ExecutionScope(allowed_session_ids=("qq:100",), start_timestamp=900, end_timestamp=1_100),
            )
        self.assertEqual(raised.exception.code, "UNRESOLVED_MESSAGE_SOURCE")

    def test_valid_artifact_has_claim_binding_and_three_state_semantics(self) -> None:
        record = _record()
        artifact = _artifact(_message_source(record))
        validated = validate_answer_artifact(
            artifact,
            run_id=record.run_id,
            tool_results=(record,),
            scope=ExecutionScope(allowed_session_ids=("qq:100",), start_timestamp=900, end_timestamp=1_100),
        )

        self.assertEqual(validated.citation_bindings[0].evidence_ids, ("e1",))
        self.assertEqual(validated.evidence_items[0].sources[0].relation, "supports")
        self.assertEqual(validated.evidence_items[0].sufficiency, "sufficient")
        self.assertEqual(validated.evidence_items[0].sources[0].reference.snapshot.session_display, "Trusted Session")

    def test_duplicate_ids_invalid_relation_and_invalid_sufficiency_are_explicit(self) -> None:
        source = EvidenceSource("supports", _message_source(_record()))
        item = EvidenceItem("e1", "finding", "criterion", "partial", (source,))
        self.assertEqual(
            {EvidenceSource(relation, _message_source(_record())).relation for relation in ("supports", "contradicts", "context")},
            {"supports", "contradicts", "context"},
        )
        self.assertEqual(
            {EvidenceItem("e1", "finding", "criterion", sufficiency).sufficiency for sufficiency in ("sufficient", "partial", "insufficient")},
            {"sufficient", "partial", "insufficient"},
        )
        with self.assertRaises(AnswerContractError):
            AnswerArtifact(
                (AnswerContentBlock("claim", "text"),),
                evidence_items=(item, item),
            )
        with self.assertRaises(AnswerContractError):
            EvidenceSource("included", _message_source(_record()))  # type: ignore[arg-type]
        with self.assertRaises(AnswerContractError):
            EvidenceItem("e1", "finding", "criterion", "unknown")  # type: ignore[arg-type]
        with self.assertRaises(AnswerContractError):
            EvidenceItem("e1", "", "criterion", "insufficient")
        with self.assertRaises(AnswerContractError):
            EvidenceItem("e1", "finding", "", "insufficient")
        with self.assertRaises(AnswerContractError):
            EvidenceSource("supports", object())  # type: ignore[arg-type]

    def test_dangling_binding_and_oversized_text_are_rejected(self) -> None:
        with self.assertRaises(AnswerContractError):
            AnswerArtifact(
                (AnswerContentBlock("claim", "text"),),
                citation_bindings=(CitationBinding("claim", ("missing",)),),
            )
        with self.assertRaises(AnswerContractError):
            AnswerContentBlock("claim", "x" * (MAX_FIELD_CHARS + 1))

    def test_plain_non_data_answer_is_still_a_structured_artifact(self) -> None:
        artifact = finalize_answer(
            "A general explanation that uses no chat facts.",
            run_id=None,
            tool_results=(),
            scope=ExecutionScope(),
        )
        self.assertEqual(artifact.answer_text, "A general explanation that uses no chat facts.")
        self.assertEqual(artifact.citation_bindings, ())

    def test_tool_execution_requires_structured_final_answer(self) -> None:
        record = _record()
        with self.assertRaises(AnswerFinalizationError) as raised:
            finalize_answer(
                "The tool result says Alpha was found.",
                run_id=record.run_id,
                tool_results=(record,),
                scope=ExecutionScope(),
            )
        self.assertEqual(raised.exception.code, "INVALID_ANSWER_ARTIFACT")

    def test_tool_backed_json_answer_requires_claim_evidence(self) -> None:
        record = _record()
        output = json.dumps(
            {
                "content_blocks": [{"block_id": "claim", "text": "工具返回了结果。"}],
                "citation_bindings": [],
                "evidence_items": [],
                "limitations": [],
            }
        )

        with self.assertRaises(AnswerFinalizationError) as raised:
            finalize_answer(
                output,
                run_id=record.run_id,
                tool_results=(record,),
                scope=ExecutionScope(),
            )

        self.assertEqual(raised.exception.code, "MISSING_EVIDENCE")
        self.assertEqual(raised.exception.path, "evidence_items")

    def test_malformed_citation_array_and_structured_value_are_rejected(self) -> None:
        malformed_binding = json.dumps(
            {
                "content_blocks": [{"block_id": "claim", "text": "text"}],
                "citation_bindings": [{"content_block_id": "claim", "evidence_ids": "e1"}],
                "evidence_items": [],
            }
        )
        with self.assertRaises(AnswerFinalizationError) as binding_error:
            finalize_answer(malformed_binding, run_id=None, tool_results=(), scope=ExecutionScope())
        self.assertEqual(binding_error.exception.code, "INVALID_CITATION_BINDING")

        with self.assertRaises(AnswerContractError):
            ToolStructuredItem("scalar", "value", object())


class ProvenanceValidationTests(unittest.TestCase):
    """验证 current-run provenance、scope、locator 与 trusted hydration。"""

    def setUp(self) -> None:
        self.scope = ExecutionScope(allowed_session_ids=("qq:100",), start_timestamp=900, end_timestamp=1_100)
        self.record = _record(scope=self.scope)

    def test_model_metadata_is_replaced_by_trusted_projection(self) -> None:
        fake_snapshot = MessageDisplaySnapshot(
            session_display="model-invented-session",
            author_display="model-invented-author",
            timestamp_ms=9,
            timezone="PST",
            excerpt="model-invented-excerpt",
            excerpt_truncated=False,
            source_message_id="fake",
        )
        result = validate_answer_artifact(
            _artifact(_message_source(self.record, snapshot=fake_snapshot)),
            run_id=self.record.run_id,
            tool_results=(self.record,),
            scope=self.scope,
        )
        snapshot = result.evidence_items[0].sources[0].reference.snapshot
        self.assertEqual(snapshot.session_display, "Trusted Session")
        self.assertEqual(snapshot.author_display, "Trusted Author")
        self.assertEqual(snapshot.timestamp_ms, 1_000)
        self.assertEqual(snapshot.timezone, "UTC")
        self.assertEqual(snapshot.excerpt, "canonical content")

    def test_tool_record_bounds_long_message_and_preserves_truncation_fact(self) -> None:
        scope = self.scope
        result = StructuredMessageResult(
            query=MessageQuery(session_ids=("qq:100",), limit=1),
            strategy="structured",
            messages=(_message(content="x" * 1_500),),
            total_hits=1,
            returned_count=1,
            coverage=Coverage("complete", "canonical_store"),
            partial=False,
            truncated=False,
            metadata=RetrievalMetadata(filters={}, ordering="timestamp ASC", latency_ms=0.0),
        )
        record = build_tool_result_record(
            run_id="run-current",
            tool_call_id="run-current/tool-call/1",
            tool_result_id="run-current/tool-call/1/result",
            tool_name="retrieve_messages",
            envelope=ToolEnvelope("ok", result, {}, None),
            scope=scope,
        )
        self.assertTrue(record.message_items[0].content_truncated)
        self.assertEqual(len(record.message_items[0].message.normalized_content), 1_000)
        validated = validate_answer_artifact(
            _artifact(_message_source(record)),
            run_id=record.run_id,
            tool_results=(record,),
            scope=scope,
        )
        snapshot = validated.evidence_items[0].sources[0].reference.snapshot
        self.assertTrue(snapshot.excerpt_truncated)

    def test_fabricated_run_tool_result_item_and_old_run_fail(self) -> None:
        cases = (
            ("run_id", "INVALID_PROVENANCE", replace_source(_message_source(self.record), run_id="old")),
            ("tool_result_id", "INVALID_PROVENANCE", replace_source(_message_source(self.record), tool_result_id="fake-result")),
            ("result_item_id", "UNRESOLVED_MESSAGE_SOURCE", replace_source(_message_source(self.record), result_item_id="message/fake")),
            ("message_id", "MESSAGE_SOURCE_MISMATCH", replace_source(_message_source(self.record), internal_message_id="qq:100:fake")),
        )
        for name, expected_code, source in cases:
            with self.subTest(name=name):
                with self.assertRaises(AnswerFinalizationError) as raised:
                    validate_answer_artifact(
                        _artifact(source),
                        run_id=self.record.run_id,
                        tool_results=(self.record,),
                        scope=self.scope,
                    )
                self.assertEqual(raised.exception.code, expected_code)

    def test_source_outside_execution_scope_fails_even_if_context_was_returned(self) -> None:
        out_of_scope = _record(scope=self.scope, message=_message(timestamp=2_000))
        with self.assertRaises(AnswerFinalizationError) as raised:
            validate_answer_artifact(
                _artifact(_message_source(out_of_scope)),
                run_id=out_of_scope.run_id,
                tool_results=(out_of_scope,),
                scope=self.scope,
            )
        self.assertEqual(raised.exception.code, "SCOPE_VIOLATION")

    def test_structured_source_has_independent_locator_and_trusted_scope(self) -> None:
        source = StructuredSource(
            run_id=self.record.run_id,
            tool_call_id=self.record.tool_call_id,
            tool_result_id=self.record.tool_result_id,
            locator_kind="aggregate",
            locator="total_count",
            value_snapshot=182,
            query_scope_snapshot={"fake": True},
        )
        artifact = _artifact(source)
        validated = validate_answer_artifact(
            artifact,
            run_id=self.record.run_id,
            tool_results=(self.record,),
            scope=self.scope,
        )
        hydrated = validated.evidence_items[0].sources[0].reference
        self.assertIsInstance(hydrated, StructuredSource)
        self.assertEqual(hydrated.value_snapshot, 182)
        self.assertEqual(hydrated.query_scope_snapshot, self.record.query_scope_snapshot)
        self.assertNotEqual(hydrated.query_scope_snapshot, {"fake": True})

        with self.assertRaises(AnswerFinalizationError) as mismatch:
            validate_answer_artifact(
                _artifact(
                    StructuredSource(
                        run_id=self.record.run_id,
                        tool_call_id=self.record.tool_call_id,
                        tool_result_id=self.record.tool_result_id,
                        locator_kind="aggregate",
                        locator="total_count",
                        value_snapshot=183,
                    )
                ),
                run_id=self.record.run_id,
                tool_results=(self.record,),
                scope=self.scope,
            )
        self.assertEqual(mismatch.exception.code, "STRUCTURED_VALUE_MISMATCH")
        self.assertEqual(mismatch.exception.path, "evidence_items[0].sources[0].source.value_snapshot")

        with self.assertRaises(AnswerFinalizationError) as raised:
            validate_answer_artifact(
                _artifact(
                    StructuredSource(
                        run_id=self.record.run_id,
                        tool_call_id=self.record.tool_call_id,
                        tool_result_id=self.record.tool_result_id,
                        locator_kind="aggregate",
                        locator="missing",
                        value_snapshot=182,
                    )
                ),
                run_id=self.record.run_id,
                tool_results=(self.record,),
                scope=self.scope,
            )
        self.assertEqual(raised.exception.code, "UNRESOLVED_STRUCTURED_SOURCE")

    def test_message_snapshot_keeps_trusted_urls_before_excerpt_truncation(self) -> None:
        """URL 从完整 canonical message 提取，不能因 excerpt bound 被截掉。"""

        message = _message(
            content=(
                "资源 https://github.com/example/project，后面有很长的上下文。"
                + ("x" * 1_200)
            )
        )
        result = StructuredMessageResult(
            query=MessageQuery(session_ids=("qq:100",), limit=1),
            strategy="structured",
            messages=(message,),
            total_hits=1,
            returned_count=1,
            coverage=Coverage("complete", "canonical_store"),
            partial=False,
            truncated=False,
            metadata=RetrievalMetadata(filters={}, ordering="timestamp ASC", latency_ms=0.0),
        )
        record = build_tool_result_record(
            run_id="run-current",
            tool_call_id="run-current/tool-call/1",
            tool_result_id="run-current/tool-call/1/result",
            tool_name="retrieve_messages",
            envelope=ToolEnvelope("ok", result, {}, None),
            scope=self.scope,
        )
        validated = validate_answer_artifact(
            _artifact(_message_source(record)),
            run_id=record.run_id,
            tool_results=(record,),
            scope=self.scope,
        )
        reference = validated.evidence_items[0].sources[0].reference
        self.assertIsInstance(reference, MessageSource)
        assert isinstance(reference, MessageSource)
        assert reference.snapshot is not None
        self.assertEqual(reference.snapshot.urls, ("https://github.com/example/project",))
        self.assertTrue(reference.snapshot.excerpt_truncated)

    def test_extract_urls_deduplicates_and_strips_sentence_punctuation(self) -> None:
        self.assertEqual(
            extract_urls("https://example.com/a, https://example.com/a。 https://github.com/a/b"),
            ("https://example.com/a", "https://github.com/a/b"),
        )

    def test_tool_partial_and_evidence_sufficiency_remain_independent(self) -> None:
        partial_record = _record(scope=self.scope, status="partial")
        result = validate_answer_artifact(
            _artifact(_message_source(partial_record)),
            run_id=partial_record.run_id,
            tool_results=(partial_record,),
            scope=self.scope,
        )
        self.assertEqual(result.evidence_items[0].sufficiency, "sufficient")
        self.assertEqual(partial_record.limitations, ("tool_result_partial",))


def replace_source(source: MessageSource, **changes: str) -> MessageSource:
    """测试只替换一个 locator，避免为 bad case 复制整份 source。"""

    values = {
        "run_id": source.run_id,
        "tool_call_id": source.tool_call_id,
        "tool_result_id": source.tool_result_id,
        "result_item_id": source.result_item_id,
        "session_id": source.session_id,
        "internal_message_id": source.internal_message_id,
        "snapshot": source.snapshot,
    }
    values.update(changes)
    return MessageSource(**values)


class RuntimeEvidenceIntegrationTests(unittest.TestCase):
    """验证 SQLite search_messages 到 Validated Answer Artifact 的完整 M5 主链。"""

    def test_search_result_provenance_reaches_validated_query_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw"
            raw.mkdir()
            write_export(
                raw,
                "runtime(100).json",
                [make_message("m1", 1, 1_000, "Alpha was deployed")],
                chat_name="Runtime Session",
                peer_uid=None,
                version="5.5.64",
            )
            application = create_application(root / "runtime.sqlite3")
            try:
                application.import_directory(raw)
                application.rebuild_lexical_index()
                payload = {
                    "content_blocks": [{"block_id": "claim-1", "text": "Alpha was found."}],
                    "citation_bindings": [{"content_block_id": "claim-1", "evidence_ids": ["e1"]}],
                    "evidence_items": [
                        {
                            "evidence_id": "e1",
                            "finding": "Alpha appears in the current result.",
                            "criterion": "A returned canonical message contains the finding.",
                            "sufficiency": "sufficient",
                            "sources": [
                                {
                                    "relation": "supports",
                                    "source": {
                                        "type": "message",
                                        "run_id": "m5-run",
                                        "tool_call_id": "m5-run/tool-call/1",
                                        "tool_result_id": "m5-run/tool-call/1/result",
                                        "result_item_id": "message/qq:100:m1",
                                        "session_id": "qq:100",
                                        "internal_message_id": "qq:100:m1",
                                    },
                                }
                            ],
                        }
                    ],
                    "limitations": [],
                }
                model = ScriptedModel(
                    [
                        ModelStep(
                            output=[
                                function_call(
                                    "search_messages",
                                    {"keyword": "Alpha", "limit": 5},
                                    call_id="provider-call-1",
                                )
                            ]
                        ),
                        ModelStep(output=[assistant_message(json.dumps(payload))]),
                    ]
                )
                runtime = OpenAIAgentsRuntimeAdapter(
                    application.capability_registry,
                    model=model,
                    max_turns=4,
                )
                application._agent_runtime = runtime
                result = asyncio.run(
                    application.query(
                        QueryRequest(
                            "Where is Alpha?",
                            ExecutionScope(allowed_session_ids=("qq:100",), max_results=5),
                            request_id="m5-run",
                            available_capabilities=("search_messages",),
                        )
                    )
                )

                self.assertTrue(result.is_successful)
                self.assertIsNotNone(result.answer_artifact)
                assert result.answer_artifact is not None
                reference = result.answer_artifact.evidence_items[0].sources[0].reference
                self.assertIsInstance(reference, MessageSource)
                assert isinstance(reference, MessageSource)
                self.assertEqual(reference.snapshot.session_display, "Runtime Session")
                self.assertEqual(reference.snapshot.author_display, "Sender")
                self.assertEqual(reference.snapshot.timestamp_ms, 1_000)
                self.assertEqual(result.runtime_result.tool_results[0].tool_result_id, "m5-run/tool-call/1/result")
            finally:
                application.close()

    def test_orchestrator_exposes_finalization_failure_without_success_artifact(self) -> None:
        record = _record()

        class InvalidCitationRuntime:
            async def run(self, request: object) -> RuntimeResult:
                return RuntimeResult(
                    final_answer="plain answer after a tool call",
                    provider="test",
                    model="test-model",
                    termination="completed",
                    tool_calls=(),
                    run_id=record.run_id,
                    tool_results=(record,),
                )

        result = asyncio.run(
            QueryOrchestrator(
                InvalidCitationRuntime(),  # type: ignore[arg-type]
                RuleRouter(),
                SoftPlanner(),
                capability_names=("search_messages",),
            ).run(
                QueryRequest(
                    "investigate",
                    ExecutionScope(),
                    request_id=record.run_id,
                    available_capabilities=("search_messages",),
                )
            )
        )
        self.assertIsNone(result.answer_artifact)
        self.assertIsNone(result.final_answer)
        self.assertEqual(result.runtime_answer, "plain answer after a tool call")
        self.assertEqual(result.finalization_error.code, "INVALID_ANSWER_ARTIFACT")

    def test_orchestrator_keeps_malformed_json_as_finalization_failure(self) -> None:
        """Provider 非法 JSON 不能被 Evaluation 或 Finalizer 修补成成功。"""

        record = _record()

        class MalformedJsonRuntime:
            async def run(self, request: object) -> RuntimeResult:
                return RuntimeResult(
                    final_answer='{"content_blocks":[',
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    termination="completed",
                    tool_calls=(),
                    run_id=record.run_id,
                    tool_results=(record,),
                )

        result = asyncio.run(
            QueryOrchestrator(
                MalformedJsonRuntime(),  # type: ignore[arg-type]
                RuleRouter(),
                SoftPlanner(),
                capability_names=("search_messages",),
            ).run(
                QueryRequest(
                    "investigate",
                    ExecutionScope(),
                    request_id=record.run_id,
                    available_capabilities=("search_messages",),
                )
            )
        )

        self.assertFalse(result.is_successful)
        self.assertIsNone(result.answer_artifact)
        self.assertEqual(result.finalization_error.code, "INVALID_ANSWER_ARTIFACT")

    def test_real_query_trace_keeps_structured_failure_path_and_no_commit(self) -> None:
        """真实 Application 主链保留 citation path，并且失败不产生 answer commit。"""

        scope = ExecutionScope(allowed_session_ids=("qq:100",), start_timestamp=900, end_timestamp=1_100)
        record = _record(scope=scope)
        payload = {
            "content_blocks": [{"block_id": "claim-1", "text": "共有 183 条。"}],
            "citation_bindings": [{"content_block_id": "claim-1", "evidence_ids": ["e1"]}],
            "evidence_items": [
                {
                    "evidence_id": "e1",
                    "finding": "错误结构化值。",
                    "criterion": "用于重现真实 citation failure。",
                    "sufficiency": "sufficient",
                    "sources": [
                        {
                            "relation": "supports",
                            "source": {
                                "type": "structured",
                                "run_id": record.run_id,
                                "tool_call_id": record.tool_call_id,
                                "tool_result_id": record.tool_result_id,
                                "source_id": "aggregate:total_count",
                                "locator_kind": "aggregate",
                                "locator": "total_count",
                                "value_snapshot": 183,
                            },
                        }
                    ],
                    "limitations": [],
                }
            ],
            "limitations": [],
        }

        class InvalidStructuredCitationRuntime:
            async def run(self, request: object) -> RuntimeResult:
                return RuntimeResult(
                    final_answer=json.dumps(payload),
                    provider="test",
                    model="test-model",
                    termination="completed",
                    tool_calls=(),
                    run_id=record.run_id,
                    tool_results=(record,),
                )

        with tempfile.TemporaryDirectory() as directory:
            application = create_application(
                Path(directory) / "structured-failure.sqlite3",
                agent_runtime=InvalidStructuredCitationRuntime(),
            )
            try:
                result = asyncio.run(
                    application.query(
                        QueryRequest("重现结构化引用失败", scope),
                    )
                )
                self.assertFalse(result.is_successful)
                self.assertIsNone(result.answer_artifact)
                self.assertEqual(result.finalization_error.code, "STRUCTURED_VALUE_MISMATCH")
                self.assertEqual(
                    result.finalization_error.path,
                    "evidence_items[0].sources[0].source.value_snapshot",
                )
                operations = [event.operation for event in application.read_trace(result.trace_id).timeline]
                self.assertNotIn("answer.commit.completed", operations)
                failed = next(event for event in application.read_trace(result.trace_id).timeline if event.operation == "citation.validation.failed")
                self.assertEqual(
                    failed.payload["path"],
                    "evidence_items[0].sources[0].source.value_snapshot",
                )
            finally:
                application.close()


if __name__ == "__main__":
    unittest.main()
