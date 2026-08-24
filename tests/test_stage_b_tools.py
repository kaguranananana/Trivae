from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from tests.test_ingestion import make_message, write_export
from trivae.bootstrap.application import create_application
from trivae.capabilities import (
    CapabilityContractError,
    ExecutionScope,
    FindMembersInput,
    GetMessageContextInput,
)
from trivae.capabilities.contracts import CapabilityScopeError
from trivae.observability.collector import TraceCollector
from trivae.observability.projection import project_trace
from trivae.observability.transcript import format_execution_transcript, format_trace_summary
from trivae.query.evidence import (
    AnswerArtifact,
    AnswerContentBlock,
    CitationBinding,
    EvidenceItem,
    EvidenceSource,
    StructuredSource,
    build_tool_result_record,
    validate_answer_artifact,
)
from trivae.query.runtime.contracts import AgentRunRequest
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter
from trivae.retrieval.context import MessageContextResult
from trivae.retrieval.identity import FindMembersResult


class StageBToolsTests(unittest.TestCase):
    """验证 Stage B 的 context/member Tool 共享既有 canonical、Runtime 和 evidence 边界。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        raw = root / "raw"
        raw.mkdir()

        session_a = [
            self._message("a1", 1_000, "before context", "u1", "Alice", "same-nick", "Blue", "alice-alias"),
            self._message("a2", 2_000, "anchor context", "u1", "Alice", "same-nick", "Blue", "alice-alias"),
            self._message("a3", 3_000, "same nickname second person", "u2", "Bob", "same-nick", "Green", "bob-alias"),
            self._message("a4", 4_000, "after context", "u2", "Bob", "same-nick", "Green", "bob-alias"),
        ]
        session_b = [
            self._message("b1", 1_000, "same identity in another session", "u1", "Alice", "session-b", "Yellow", "alice-alias"),
            self._message("b2", 2_000, "another session message", "u3", "Carol", "carol-nick", "Red", "carol-alias"),
        ]
        write_export(
            raw,
            "stage-b-a(100).json",
            session_a,
            chat_name="Stage B A",
            peer_uid=None,
            version="5.5.64",
        )
        write_export(
            raw,
            "stage-b-b(200).json",
            session_b,
            chat_name="Stage B B",
            peer_uid=None,
            version="5.5.64",
        )

        self.application = create_application(root / "stage-b.sqlite3")
        self.application.import_directory(raw)

    def tearDown(self) -> None:
        self.application.close()
        self.temporary.cleanup()

    @staticmethod
    def _message(
        source_id: str,
        timestamp: int,
        text: str,
        user_id: str,
        display_name: str,
        nickname: str,
        group_card: str,
        remark: str,
    ) -> dict:
        """构造具有不同 UserIdentity/Membership 字段的 canonical import fixture。"""

        message = make_message(source_id, timestamp, timestamp, text, sender_uid=user_id)
        message["sender"].update(
            {
                "uin": f"uin-{user_id}",
                "name": display_name,
                "nickname": nickname,
                "groupCard": group_card,
                "remark": remark,
            }
        )
        return message

    def test_get_message_context_reuses_bounded_context_and_marks_explicit_deepening(self) -> None:
        """显式 context 保留 anchor、同 conversation 边界和 truncation 事实。"""

        envelope = self.application.invoke_tool(
            "get_message_context",
            GetMessageContextInput("qq:100:a2", context_before=3, context_after=3),
            ExecutionScope(allowed_session_ids=("qq:100",), max_results=3),
        )

        self.assertEqual(envelope.status, "ok")
        self.assertIsInstance(envelope.data, MessageContextResult)
        assert isinstance(envelope.data, MessageContextResult)
        self.assertIn("qq:100:a2", {message.internal_message_id for message in envelope.data.messages})
        self.assertLessEqual(len(envelope.data.messages), 3)
        self.assertTrue(envelope.data.truncated)
        self.assertEqual({message.session_id for message in envelope.data.messages}, {"qq:100"})
        self.assertTrue(envelope.data.metadata.details["explicit_deepening"])
        self.assertFalse(envelope.data.metadata.details["automatic_search_context"])

    def test_get_message_context_enforces_message_and_time_scope(self) -> None:
        """anchor 越权、时间越界和 context 邻居都必须在 Capability/SQL 边界显式失败或裁剪。"""

        outside_session = self.application.invoke_tool(
            "get_message_context",
            GetMessageContextInput("qq:200:b1"),
            ExecutionScope(allowed_session_ids=("qq:100",), max_results=10),
        )
        self.assertEqual(outside_session.status, "error")
        self.assertEqual(outside_session.error.code, CapabilityScopeError.error_code)

        outside_time = self.application.invoke_tool(
            "get_message_context",
            GetMessageContextInput("qq:100:a1", context_before=2, context_after=2),
            ExecutionScope(
                allowed_session_ids=("qq:100",),
                start_timestamp=2_000,
                end_timestamp=4_000,
                max_results=10,
            ),
        )
        self.assertEqual(outside_time.status, "error")
        self.assertEqual(outside_time.error.code, CapabilityScopeError.error_code)

        clipped = self.application.invoke_tool(
            "get_message_context",
            GetMessageContextInput("qq:100:a2", context_before=5, context_after=5),
            ExecutionScope(
                allowed_session_ids=("qq:100",),
                start_timestamp=2_000,
                end_timestamp=4_000,
                max_results=10,
            ),
        )
        self.assertEqual(clipped.status, "ok")
        assert isinstance(clipped.data, MessageContextResult)
        self.assertEqual(
            [message.internal_message_id for message in clipped.data.messages],
            ["qq:100:a2", "qq:100:a3"],
        )

    def test_get_message_context_invalid_locator_and_input_bound_are_explicit(self) -> None:
        """不存在的 message_id 与过大的窗口不能被 fallback 成搜索结果。"""

        missing = self.application.invoke_tool(
            "get_message_context",
            GetMessageContextInput("qq:100:missing"),
            ExecutionScope(max_results=10),
        )
        self.assertEqual(missing.status, "error")
        self.assertEqual(missing.error.code, "MESSAGE_NOT_FOUND")

        with self.assertRaises(CapabilityContractError):
            GetMessageContextInput("qq:100:a2", context_before=100, context_after=1)

    def test_find_members_returns_ambiguous_candidates_and_match_reasons(self) -> None:
        """同昵称返回多个 stable UserIdentity，不强行 resolve 为唯一人物。"""

        envelope = self.application.invoke_tool(
            "find_members",
            FindMembersInput("same-nick", limit=10),
            ExecutionScope(max_results=10),
        )

        self.assertEqual(envelope.status, "ok")
        self.assertIsInstance(envelope.data, FindMembersResult)
        assert isinstance(envelope.data, FindMembersResult)
        self.assertEqual(envelope.data.total_candidates, 2)
        self.assertEqual(len(envelope.data.candidates), 2)
        self.assertTrue(envelope.data.metadata.details["ambiguous"])
        self.assertEqual(
            {match.kind for candidate in envelope.data.candidates for match in candidate.matches},
            {"exact"},
        )
        self.assertTrue(
            all(
                any(match.field == "nickname" and match.owner in {"user", "membership"} for match in candidate.matches)
                for candidate in envelope.data.candidates
            )
        )

    def test_find_members_supports_alias_multiple_sessions_and_no_result(self) -> None:
        """remark 作为当前 schema 的 alias-like 字段返回依据，稳定用户可关联多个 session。"""

        alias = self.application.invoke_tool(
            "find_members",
            FindMembersInput("alice-alias", limit=10),
            ExecutionScope(max_results=10),
        )
        self.assertEqual(alias.status, "ok")
        assert isinstance(alias.data, FindMembersResult)
        self.assertEqual(len(alias.data.candidates), 1)
        candidate = alias.data.candidates[0]
        self.assertEqual(candidate.alias, "alice-alias")
        self.assertTrue(any(match.to_dict()["label"] == "alias/remark" for match in candidate.matches))
        self.assertEqual({membership.session_id for membership in candidate.memberships}, {"qq:100", "qq:200"})

        no_result = self.application.invoke_tool(
            "find_members",
            FindMembersInput("nobody-known", limit=10),
            ExecutionScope(max_results=10),
        )
        self.assertEqual(no_result.status, "ok")
        assert isinstance(no_result.data, FindMembersResult)
        self.assertEqual(no_result.data.candidates, ())
        self.assertEqual(no_result.data.total_candidates, 0)

    def test_find_members_scope_and_result_bound_are_explicit(self) -> None:
        """成员查询只能看到 trusted session，模型不能通过 session_ids 扩大范围。"""

        scoped = self.application.invoke_tool(
            "find_members",
            FindMembersInput("Alice", session_ids=("qq:100",), limit=10),
            ExecutionScope(allowed_session_ids=("qq:100",), max_results=10),
        )
        self.assertEqual(scoped.status, "ok")
        assert isinstance(scoped.data, FindMembersResult)
        self.assertEqual(len(scoped.data.candidates), 1)
        self.assertEqual(
            {membership.session_id for membership in scoped.data.candidates[0].memberships},
            {"qq:100"},
        )

        outside = self.application.invoke_tool(
            "find_members",
            FindMembersInput("Alice", session_ids=("qq:200",), limit=10),
            ExecutionScope(allowed_session_ids=("qq:100",), max_results=10),
        )
        self.assertEqual(outside.status, "error")
        self.assertEqual(outside.error.code, CapabilityScopeError.error_code)

        over_bound = self.application.invoke_tool(
            "find_members",
            FindMembersInput("Alice", limit=4),
            ExecutionScope(max_results=3),
        )
        self.assertEqual(over_bound.status, "error")
        self.assertEqual(over_bound.error.code, "INVALID_ARGUMENT")

    def test_stage_b_trace_distinguishes_context_member_and_counts_public_tool_calls_once(self) -> None:
        """Trace 同时记录内部 attribution 与公开 tool count，避免内部 event 重复计数。"""

        collector = TraceCollector(
            self.application._trace_store,
            trace_id="trace-stage-b",
            request_id="request-stage-b",
        )
        context_envelope = self.application.capability_registry.invoke(
            "get_message_context",
            GetMessageContextInput("qq:100:a2", context_before=1, context_after=1),
            ExecutionScope(allowed_session_ids=("qq:100",), max_results=10),
            trace_context=collector.operation_context("tool:context-call"),
        )
        member_envelope = self.application.capability_registry.invoke(
            "find_members",
            FindMembersInput("same-nick", limit=10),
            ExecutionScope(max_results=10),
            trace_context=collector.operation_context("tool:member-call"),
        )
        projection = project_trace(self.application._trace_store.read_trace("trace-stage-b"))

        self.assertEqual(context_envelope.status, "ok")
        self.assertEqual(member_envelope.status, "ok")
        operations = [item.operation for item in projection.timeline]
        self.assertIn("context.expansion.completed", operations)
        self.assertIn("member.lookup.completed", operations)
        self.assertEqual(projection.metrics.tool_count, 2)
        context_event = next(item for item in projection.timeline if item.operation == "context.expansion.completed")
        self.assertTrue(context_event.payload["explicit_deepening"])
        self.assertFalse(context_event.payload["automatic_search_context"])
        stored = self.application._trace_store.read_trace("trace-stage-b")
        summary = format_trace_summary(stored)
        transcript = format_execution_transcript(stored)
        self.assertIn("explicit_context_calls: 1", summary)
        self.assertIn("member_lookups: 1", summary)
        self.assertIn("[CONTEXT EXPANSION]", transcript)
        self.assertIn("[MEMBER LOOKUP]", transcript)

    def test_stage_b_results_enter_existing_evidence_record(self) -> None:
        """context 使用 message provenance，member 使用可验证 structured row provenance。"""

        context = self.application.invoke_tool(
            "get_message_context",
            GetMessageContextInput("qq:100:a2", context_before=1, context_after=1),
            ExecutionScope(allowed_session_ids=("qq:100",), max_results=10),
        )
        member = self.application.invoke_tool(
            "find_members",
            FindMembersInput("same-nick", limit=10),
            ExecutionScope(max_results=10),
        )
        context_record = build_tool_result_record(
            run_id="stage-b-run",
            tool_call_id="stage-b-run/tool-call/1",
            tool_result_id="stage-b-run/tool-call/1/result",
            tool_name="get_message_context",
            envelope=context,
            scope=ExecutionScope(allowed_session_ids=("qq:100",), max_results=10),
        )
        member_record = build_tool_result_record(
            run_id="stage-b-run",
            tool_call_id="stage-b-run/tool-call/2",
            tool_result_id="stage-b-run/tool-call/2/result",
            tool_name="find_members",
            envelope=member,
            scope=ExecutionScope(max_results=10),
        )

        self.assertGreaterEqual(len(context_record.message_items), 1)
        self.assertEqual(member_record.structured_items[0].locator, "candidates[0]")
        self.assertEqual(member_record.structured_items[0].locator_kind, "row")
        self.assertIn("matches", member_record.structured_items[0].value_snapshot)
        provenance = member_record.to_model_provenance()
        self.assertEqual(provenance["structured_sources"][0]["locator"], "candidates[0]")

    def test_member_structured_source_passes_existing_finalizer_contract(self) -> None:
        """成员候选 row 使用 structured locator/value_snapshot，而不是伪装成 message source。"""

        envelope = self.application.invoke_tool(
            "find_members",
            FindMembersInput("same-nick", limit=10),
            ExecutionScope(max_results=10),
        )
        record = build_tool_result_record(
            run_id="stage-b-finalizer",
            tool_call_id="stage-b-finalizer/tool-call/1",
            tool_result_id="stage-b-finalizer/tool-call/1/result",
            tool_name="find_members",
            envelope=envelope,
            scope=ExecutionScope(max_results=10),
        )
        item = record.structured_items[0]
        artifact = AnswerArtifact(
            content_blocks=(AnswerContentBlock("claim-1", "候选成员结果已返回。"),),
            citation_bindings=(CitationBinding("claim-1", ("e1",)),),
            evidence_items=(
                EvidenceItem(
                    evidence_id="e1",
                    finding="成员候选已被 identity lookup 返回。",
                    criterion="structured candidate row exists in the current tool result",
                    sufficiency="sufficient",
                    sources=(
                        EvidenceSource(
                            "supports",
                            StructuredSource(
                                run_id=record.run_id,
                                tool_call_id=record.tool_call_id,
                                tool_result_id=record.tool_result_id,
                                locator_kind=item.locator_kind,
                                locator=item.locator,
                                value_snapshot=item.value_snapshot,
                            ),
                        ),
                    ),
                ),
            ),
        )

        validated = validate_answer_artifact(
            artifact,
            run_id=record.run_id,
            tool_results=(record,),
            scope=ExecutionScope(max_results=10),
        )

        self.assertIsInstance(validated.evidence_items[0].sources[0].reference, StructuredSource)

    def test_runtime_registers_stage_b_surface_and_keeps_same_runtime_for_member_then_search(self) -> None:
        """SDK adapter 只做参数/record 投影，成员查询后可在同一 Runtime 继续 lexical。"""

        self.application.rebuild_lexical_index()
        runtime = OpenAIAgentsRuntimeAdapter(
            self.application.capability_registry,
            model=ScriptedModel(
                [
                    ModelStep(
                        output=[
                            function_call(
                                "find_members",
                                {"query": "same-nick"},
                                call_id="member-call",
                            )
                        ]
                    ),
                    ModelStep(
                        output=[
                            function_call(
                                "lexical_search",
                                {"keyword": "anchor context", "limit": 2, "context_before": 0, "context_after": 0},
                                call_id="lexical-call",
                            )
                        ]
                    ),
                    ModelStep(output=[assistant_message("member lookup and retrieval completed")]),
                ]
            ),
            max_turns=4,
        )
        request = AgentRunRequest(
            "先确认成员，再检索消息",
            ExecutionScope(allowed_session_ids=("qq:100",), max_results=2),
            available_capabilities=("lexical_search", "get_message_context", "find_members"),
            request_id="stage-b-runtime",
        )
        context = runtime._build_context(request)
        agent = runtime._build_agent(request, context, object())
        visible_tools = {tool.name: tool for tool in agent.tools}
        result = asyncio.run(runtime.run(request))

        self.assertEqual(set(visible_tools), {"lexical_search", "get_message_context", "find_members"})
        self.assertIn("multiple candidates", visible_tools["find_members"].description)
        self.assertIn("only when the search result's local context is insufficient", visible_tools["get_message_context"].description)
        self.assertEqual(result.termination, "completed")
        self.assertEqual([call.name for call in result.tool_calls], ["find_members", "lexical_search"])
        self.assertEqual([record.tool_name for record in result.tool_results], ["find_members", "lexical_search"])
        self.assertEqual({record.run_id for record in result.tool_results}, {result.run_id})


if __name__ == "__main__":
    unittest.main()
