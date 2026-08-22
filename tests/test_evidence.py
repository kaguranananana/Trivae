from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
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
    StructuredSource,
    ToolMessageItem,
    ToolResultRecord,
    ToolStructuredItem,
    build_tool_result_record,
    finalize_answer,
    scope_snapshot,
    validate_answer_artifact,
)
from trivae.query.orchestrator import QueryOrchestrator
from trivae.query.planner import SoftPlanner
from trivae.query.router import RuleRouter
from trivae.query.runtime.contracts import RuntimeResult
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter
from trivae.retrieval.structured import (
    Coverage,
    MessageProjection,
    MessageQuery,
    RetrievalMetadata,
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
            ).run(QueryRequest("investigate", ExecutionScope(), request_id=record.run_id))
        )
        self.assertIsNone(result.answer_artifact)
        self.assertIsNone(result.final_answer)
        self.assertEqual(result.runtime_answer, "plain answer after a tool call")
        self.assertEqual(result.finalization_error.code, "INVALID_ANSWER_ARTIFACT")


if __name__ == "__main__":
    unittest.main()
