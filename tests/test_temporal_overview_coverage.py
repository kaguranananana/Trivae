"""Temporal overview 的容量、分页、覆盖、时间事实与模型投影回归。"""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.test_ingestion import make_message, write_export
from trivae.capabilities.contracts import (
    CapabilityContractError,
    CapabilityScopeError,
    ExecutionScope,
    GetRecentMessagesInput,
    ToolEnvelope,
    format_timestamp_utc,
)
from trivae.capabilities.recent_messages import RecentMessagesCapability
from trivae.capabilities.registry import CapabilityRegistry
from trivae.capabilities.tools import RecentMessagesTool
from trivae.config.limits import (
    DEFAULT_RECENT_MESSAGES_LIMIT,
    DEFAULT_STRUCTURED_RESULT_LIMIT,
    DEFAULT_TOOL_RESULT_TOKEN_BUDGET,
    MAX_RECENT_MESSAGES_LIMIT,
)
from trivae.conversation.serialization import deserialize_answer_artifact, serialize_answer_artifact
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.observability.collector import TraceCollector
from trivae.observability.projection import project_trace
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.evidence import (
    AnswerFinalizationError,
    build_tool_result_record,
    finalize_answer,
    has_verified_zero_result_evidence,
    project_tool_result_for_model,
    validate_answer_artifact,
)
from trivae.query.runtime.openai_tools import GetRecentMessagesSDKToolAdapter
from trivae.query.streaming import project_tool_result_detail, project_tool_result_structure
from trivae.retrieval.structured import (
    Coverage,
    InvalidRetrievalQuery,
    MessageProjection,
    RecentMessagesQuery,
    RetrievalMetadata,
    StructuredMessageResult,
    StructuredRetrieval,
)

SESSION = "qq:941"
BASE_TIMESTAMP = 1_786_700_000_000
WINDOW_END = BASE_TIMESTAMP + 20_000


def _bulk_message(index: int, content: str) -> MessageProjection:
    """构造 bounded canonical projection，专门验证大批次模型投影。"""

    return MessageProjection(
        internal_message_id=f"{SESSION}:bulk-{index}",
        session_id=SESSION,
        source_message_id=f"bulk-{index}",
        sender_user_id="u_bulk",
        sender_platform_id=None,
        sender_uin=None,
        sender_name="Bulk Sender",
        timestamp=BASE_TIMESTAMP + index,
        seq=index,
        message_type="text",
        normalized_content=content,
        reply_to_source_message_id=None,
        recalled=False,
        system=False,
        session_display="Temporal Fixture",
    )


class TemporalOverviewContractTests(unittest.TestCase):
    """验证 recent retrieval 不再复用 structured 100 条边界。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.database_path = directory / "temporal.sqlite3"
        messages = [
            make_message("m01", 1, BASE_TIMESTAMP + 1_000, "第一条", sender_uid="u_a"),
            make_message("m02", 2, BASE_TIMESTAMP + 1_000, "第二条", sender_uid="u_b"),
            make_message("null-a", None, BASE_TIMESTAMP + 1_000, "无序号 A", sender_uid="u_a"),
            make_message("null-b", None, BASE_TIMESTAMP + 1_000, "无序号 B", sender_uid="u_b"),
            make_message("m05", 5, BASE_TIMESTAMP + 2_000, "第五条", sender_uid="u_a"),
            make_message("m06", 6, BASE_TIMESTAMP + 3_000, "第六条", sender_uid="u_b"),
            make_message("m07", 7, BASE_TIMESTAMP + 4_000, "第七条", sender_uid="u_a"),
            make_message("m08", 8, BASE_TIMESTAMP + 5_000, "第八条", sender_uid="u_b"),
            make_message("m09", 9, BASE_TIMESTAMP + 6_000, "第九条", sender_uid="u_a"),
            make_message("m10", 10, BASE_TIMESTAMP + 7_000, "第十条", sender_uid="u_b"),
            make_message("m11", 11, BASE_TIMESTAMP + 8_000, "第十一条", sender_uid="u_a"),
            make_message("m12", 12, BASE_TIMESTAMP + 9_000, "第十二条", sender_uid="u_b"),
        ]
        export = write_export(
            directory,
            "Temporal(941).json",
            messages,
            chat_name="Temporal Fixture",
            peer_uid=None,
            version="5.5.64",
        )
        self.store = SQLiteCanonicalStore(self.database_path)
        SharedImporter(self.store).import_paths([export])
        self.repository = SQLiteCanonicalReadRepository(self.database_path)
        self.capability = RecentMessagesCapability(StructuredRetrieval(self.repository))
        self.tool = RecentMessagesTool(self.capability)
        self.scope = ExecutionScope(allowed_session_ids=(SESSION,))

    def tearDown(self) -> None:
        self.repository.close()
        self.store.close()
        self.temporary.cleanup()

    def _first_request(self, limit: int = 3) -> GetRecentMessagesInput:
        """构造固定 absolute 窗口，避免分页测试重新解析 archive_latest。"""

        return GetRecentMessagesInput(
            start_timestamp=BASE_TIMESTAMP,
            end_timestamp=WINDOW_END,
            limit=limit,
        )

    def _page(self, cursor: object | None, limit: int = 3):
        """执行一页 recent 请求，并让后续页只从 Host-issued cursor 继续。"""

        request = (
            self._first_request(limit)
            if cursor is None
            else GetRecentMessagesInput(cursor=cursor, limit=limit)
        )
        return self.capability.execute(request, self.scope)

    def test_get_recent_messages_default_limit(self) -> None:
        self.assertEqual(DEFAULT_RECENT_MESSAGES_LIMIT, 1_000)
        self.assertEqual(GetRecentMessagesInput().limit, DEFAULT_RECENT_MESSAGES_LIMIT)

    def test_get_recent_messages_hard_cap(self) -> None:
        self.assertEqual(MAX_RECENT_MESSAGES_LIMIT, 5_000)
        GetRecentMessagesInput(limit=MAX_RECENT_MESSAGES_LIMIT)
        with self.assertRaises(CapabilityContractError):
            GetRecentMessagesInput(limit=MAX_RECENT_MESSAGES_LIMIT + 1)

    def test_recent_messages_respects_trusted_max_results(self) -> None:
        with self.assertRaises(CapabilityContractError):
            self.capability.execute(
                self._first_request(limit=3),
                ExecutionScope(allowed_session_ids=(SESSION,), max_results=2),
            )

    def test_recent_messages_does_not_reuse_structured_limit(self) -> None:
        self.assertEqual(DEFAULT_STRUCTURED_RESULT_LIMIT, 100)
        self.assertEqual(RecentMessagesQuery(limit=DEFAULT_STRUCTURED_RESULT_LIMIT + 1).limit, 101)
        with self.assertRaises(InvalidRetrievalQuery):
            from trivae.retrieval.structured import MessageQuery

            MessageQuery(limit=DEFAULT_STRUCTURED_RESULT_LIMIT + 1)

    def test_recent_messages_schema_exposes_its_own_capacity(self) -> None:
        tool = GetRecentMessagesSDKToolAdapter(CapabilityRegistry()).as_sdk_tool(
            trusted_max_results=MAX_RECENT_MESSAGES_LIMIT
        )
        limit_schema = tool.params_json_schema["properties"]["limit"]
        self.assertEqual(limit_schema["default"], DEFAULT_RECENT_MESSAGES_LIMIT)
        self.assertEqual(limit_schema["maximum"], MAX_RECENT_MESSAGES_LIMIT)
        self.assertIn("sender_user_ids", tool.params_json_schema["properties"])
        self.assertIn("sender_user_ids", RecentMessagesCapability.metadata.input_fields)

    def test_recent_messages_large_window(self) -> None:
        result = self._page(None, limit=3)
        self.assertEqual(result.total_hits, 12)
        self.assertEqual(result.returned_count, 3)
        self.assertEqual(result.coverage.status, "partial")
        self.assertEqual(result.coverage.covered_units, 3)
        self.assertEqual(result.coverage.eligible_units, 12)
        self.assertIsNotNone(result.metadata.details["next_cursor"])

    def test_recent_messages_total_hits_and_returned(self) -> None:
        result = self._page(None, limit=3)
        self.assertNotEqual(result.total_hits, result.returned_count)
        self.assertEqual(result.metadata.details["retrieved_count"], result.returned_count)
        self.assertTrue(result.metadata.details["has_more"])

    def test_recent_messages_partial_coverage(self) -> None:
        result = self._page(None, limit=3)
        self.assertTrue(result.partial)
        self.assertTrue(result.truncated)
        self.assertEqual(result.coverage.to_dict()["status"], "partial")

    def test_recent_messages_complete_coverage(self) -> None:
        result = self._page(None, limit=1_000)
        self.assertEqual(result.total_hits, result.returned_count)
        self.assertFalse(result.partial)
        self.assertFalse(result.truncated)
        self.assertEqual(result.coverage.status, "complete")
        self.assertEqual(result.coverage.covered_units, result.coverage.eligible_units)
        self.assertIsNone(result.metadata.details["next_cursor"])

    def test_recent_messages_cursor_no_overlap(self) -> None:
        expected = self._page(None, limit=1_000)
        cursor = None
        seen: list[str] = []
        while True:
            page = self._page(cursor, limit=3)
            page_ids = [message.internal_message_id for message in page.messages]
            self.assertTrue(set(seen).isdisjoint(page_ids))
            seen.extend(page_ids)
            cursor = page.metadata.details["next_cursor"]
            if cursor is None:
                self.assertEqual(page.coverage.status, "complete")
                break
        self.assertEqual(len(seen), expected.total_hits)
        self.assertEqual(set(seen), {message.internal_message_id for message in expected.messages})

    def test_recent_messages_cursor_no_gap(self) -> None:
        cursor = None
        covered = 0
        while True:
            page = self._page(cursor, limit=3)
            covered += page.returned_count
            self.assertEqual(page.coverage.covered_units, covered)
            cursor = page.metadata.details["next_cursor"]
            if cursor is None:
                self.assertEqual(page.coverage.eligible_units, covered)
                break

    def test_recent_messages_cursor_preserves_single_sided_absolute_scope(self) -> None:
        first = self.capability.execute(
            GetRecentMessagesInput(end_timestamp=WINDOW_END, limit=3),
            self.scope,
        )
        cursor = first.metadata.details["next_cursor"]
        self.assertIsNotNone(cursor)
        assert isinstance(cursor, dict)
        self.assertIsNone(cursor["start_timestamp"])
        second = self.capability.execute(GetRecentMessagesInput(cursor=cursor, limit=3), self.scope)
        self.assertIsNone(second.query.start_timestamp)
        self.assertEqual(second.query.end_timestamp, WINDOW_END)
        self.assertTrue(
            {
                message.internal_message_id for message in first.messages
            }.isdisjoint(message.internal_message_id for message in second.messages)
        )

    def test_recent_messages_sender_filter_is_preserved_by_cursor(self) -> None:
        """成员分页必须继续使用第一页的 canonical sender scope。"""

        first = self.capability.execute(
            GetRecentMessagesInput(
                start_timestamp=BASE_TIMESTAMP,
                end_timestamp=WINDOW_END,
                sender_user_ids=("qq:uid:u_a",),
                limit=2,
            ),
            self.scope,
        )
        cursor = first.metadata.details["next_cursor"]
        self.assertIsNotNone(cursor)
        assert isinstance(cursor, dict)
        self.assertEqual(cursor["sender_user_ids"], ("qq:uid:u_a",))

        # continuation 不重复传 sender filter 时，Host 从 cursor 恢复原成员范围。
        second = self.capability.execute(GetRecentMessagesInput(cursor=cursor, limit=2), self.scope)
        self.assertEqual(second.query.sender_user_ids, ("qq:uid:u_a",))
        self.assertTrue(all(message.sender_user_id == "qq:uid:u_a" for message in second.messages))

        # 显式切换成员必须在输入 contract 层失败，不能改变 cursor 的分页集合。
        with self.assertRaises(CapabilityContractError):
            GetRecentMessagesInput(cursor=cursor, sender_user_ids=("qq:uid:u_b",), limit=2)

    def test_legacy_cursor_without_sender_scope_remains_unfiltered(self) -> None:
        """旧版不含 sender scope 的 cursor 仍按原有全成员窗口继续。"""

        first = self._page(None, limit=3)
        cursor = first.metadata.details["next_cursor"]
        self.assertIsNotNone(cursor)
        assert isinstance(cursor, dict)
        legacy_cursor = dict(cursor)
        legacy_cursor.pop("sender_user_ids", None)

        second = self.capability.execute(GetRecentMessagesInput(cursor=legacy_cursor, limit=3), self.scope)
        self.assertIsNone(second.query.sender_user_ids)
        self.assertTrue(any(message.sender_user_id == "qq:uid:u_a" for message in second.messages))
        self.assertTrue(any(message.sender_user_id == "qq:uid:u_b" for message in second.messages))

    def test_recent_messages_same_timestamp_deterministic_order(self) -> None:
        request = GetRecentMessagesInput(
            start_timestamp=BASE_TIMESTAMP + 1_000,
            end_timestamp=BASE_TIMESTAMP + 1_001,
            limit=100,
        )
        first = self.capability.execute(request, self.scope)
        second = self.capability.execute(request, self.scope)
        first_ids = [message.internal_message_id for message in first.messages]
        second_ids = [message.internal_message_id for message in second.messages]
        self.assertEqual(first_ids, second_ids)
        self.assertEqual(
            first_ids,
            [
                f"{SESSION}:m01",
                f"{SESSION}:m02",
                f"{SESSION}:null-a",
                f"{SESSION}:null-b",
            ],
        )

    def test_recent_messages_scope_enforcement(self) -> None:
        cursor = self._page(None, limit=3).metadata.details["next_cursor"]
        self.assertIsNotNone(cursor)
        with self.assertRaises(CapabilityContractError):
            GetRecentMessagesInput(cursor=cursor, session_ids=("qq:other",), limit=3)
        with self.assertRaises(CapabilityContractError):
            GetRecentMessagesInput(cursor=cursor, start_timestamp=BASE_TIMESTAMP - 1, limit=3)
        with self.assertRaises(CapabilityContractError):
            GetRecentMessagesInput(
                cursor=cursor,
                time_range={"kind": "relative", "amount": 1, "unit": "day", "anchor": "archive_latest"},
                limit=3,
            )
        with self.assertRaises(CapabilityScopeError):
            self.capability.execute(
                GetRecentMessagesInput(cursor=cursor, limit=3),
                ExecutionScope(allowed_session_ids=("qq:other",)),
            )

    def test_recent_messages_time_range_archive_latest(self) -> None:
        request = GetRecentMessagesInput(
            time_range={"kind": "relative", "amount": 2, "unit": "day", "anchor": "archive_latest"},
            limit=1_000,
        )
        result = self.capability.execute(request, self.scope)
        details = result.metadata.details["resolved_time_range"]
        self.assertIsInstance(details, dict)
        assert isinstance(details, dict)
        latest = BASE_TIMESTAMP + 9_000
        self.assertEqual(details["anchor_timestamp"], latest)
        self.assertEqual(details["resolved_end_timestamp"], latest + 1)
        self.assertEqual(result.query.start_timestamp, details["resolved_start_timestamp"])
        self.assertEqual(result.query.end_timestamp, details["resolved_end_timestamp"])
        self.assertEqual(details["anchor_utc"], format_timestamp_utc(latest))
        self.assertEqual(details["resolved_end_utc"], format_timestamp_utc(latest + 1))

    def test_recent_messages_timestamp_unit(self) -> None:
        result = self.capability.execute(self._first_request(limit=100), self.scope)
        details = result.metadata.details["resolved_time_range"]
        assert isinstance(details, dict)
        for name in (
            "resolved_start_timestamp",
            "resolved_end_timestamp",
        ):
            value = details[name]
            self.assertIsInstance(value, int)
            self.assertGreater(value, 1_000_000_000_000)
        self.assertEqual(details["anchor"], "request")
        self.assertTrue(details["resolved_start_utc"].endswith("Z"))
        self.assertTrue(details["resolved_end_utc"].endswith("Z"))

    def test_recent_messages_time_range_matches_evidence(self) -> None:
        envelope = self.tool.invoke(self._first_request(limit=3), self.scope)
        self.assertEqual(envelope.status, "partial")
        record = build_tool_result_record(
            run_id="run-temporal",
            tool_call_id="run-temporal/tool/1",
            tool_result_id="run-temporal/tool/1/result",
            tool_name="get_recent_messages",
            envelope=envelope,
            scope=self.scope,
        )
        source_id = record.message_source_handle(record.message_items[0])
        output = json.dumps(
            {
                "claims": [
                    {
                        "text": "窗口内有消息",
                        "finding": "窗口内存在可引用消息",
                        "criterion": "消息来自 Host 解析的窗口",
                        "sufficiency": "sufficient",
                        "sources": [source_id],
                        "limitations": [],
                    }
                ],
                "limitations": [],
            },
            ensure_ascii=False,
        )
        artifact = finalize_answer(
            output,
            run_id="run-temporal",
            tool_results=(record,),
            scope=self.scope,
        )
        expected_range = record.query_scope_snapshot["resolved_time_range"]
        self.assertEqual(artifact.resolved_time_range, expected_range)
        self.assertEqual(
            artifact.retrieval_coverage,
            {
                **record.query_scope_snapshot["coverage"],
                "retrieved_count": 3,
                "has_more": True,
            },
        )
        self.assertEqual(
            deserialize_answer_artifact(serialize_answer_artifact(artifact)).retrieval_coverage,
            artifact.retrieval_coverage,
        )
        source = artifact.evidence_items[0].sources[0].reference
        self.assertIsNotNone(getattr(source, "snapshot", None))
        snapshot = source.snapshot
        assert snapshot is not None
        self.assertGreaterEqual(snapshot.timestamp_ms, BASE_TIMESTAMP)
        self.assertLess(snapshot.timestamp_ms, WINDOW_END)

        wrong_range = dict(artifact.resolved_time_range or {})
        wrong_range["resolved_start_timestamp"] = BASE_TIMESTAMP - 1
        wrong_range["resolved_start_utc"] = format_timestamp_utc(BASE_TIMESTAMP - 1)
        wrong_range["resolved_interval_utc"] = (
            f"[{format_timestamp_utc(BASE_TIMESTAMP - 1)}, "
            f"{wrong_range['resolved_end_utc']})"
        )
        mismatched_artifact = replace(artifact, resolved_time_range=wrong_range)
        with self.assertRaises(AnswerFinalizationError) as raised:
            validate_answer_artifact(
                mismatched_artifact,
                run_id="run-temporal",
                tool_results=(record,),
                scope=self.scope,
            )
        self.assertEqual(raised.exception.code, "TIME_RANGE_MISMATCH")

        wrong_coverage = dict(artifact.retrieval_coverage or {})
        wrong_coverage["status"] = "complete"
        wrong_coverage["covered_units"] = wrong_coverage["eligible_units"]
        wrong_coverage["has_more"] = False
        mismatched_coverage_artifact = replace(artifact, retrieval_coverage=wrong_coverage)
        with self.assertRaises(AnswerFinalizationError) as raised:
            validate_answer_artifact(
                mismatched_coverage_artifact,
                run_id="run-temporal",
                tool_results=(record,),
                scope=self.scope,
            )
        self.assertEqual(raised.exception.code, "COVERAGE_MISMATCH")

    def test_independent_smaller_root_query_does_not_reduce_complete_coverage(self) -> None:
        """同窗独立 root 查询只能补充事实，不能覆盖更强的 complete 证明。"""

        complete_envelope = self.tool.invoke(self._first_request(limit=1_000), self.scope)
        smaller_envelope = self.tool.invoke(self._first_request(limit=3), self.scope)
        complete_record = build_tool_result_record(
            run_id="run-independent-root",
            tool_call_id="run-independent-root/tool/1",
            tool_result_id="run-independent-root/tool/1/result",
            tool_name="get_recent_messages",
            envelope=complete_envelope,
            scope=self.scope,
        )
        smaller_record = build_tool_result_record(
            run_id="run-independent-root",
            tool_call_id="run-independent-root/tool/2",
            tool_result_id="run-independent-root/tool/2/result",
            tool_name="get_recent_messages",
            envelope=smaller_envelope,
            scope=self.scope,
        )
        source_id = complete_record.message_source_handle(complete_record.message_items[0])
        output = json.dumps(
            {
                "claims": [
                    {
                        "text": "窗口内有消息",
                        "finding": "完整 root 查询覆盖同一 Host 时间窗",
                        "criterion": "引用来自已经完整读取的 canonical window",
                        "sufficiency": "sufficient",
                        "sources": [source_id],
                        "limitations": [],
                    }
                ],
                "limitations": [],
            },
            ensure_ascii=False,
        )

        artifact = finalize_answer(
            output,
            run_id="run-independent-root",
            tool_results=(complete_record, smaller_record),
            scope=self.scope,
        )

        self.assertEqual(
            artifact.retrieval_coverage,
            {
                "status": "complete",
                "basis": "canonical_store",
                "covered_units": 12,
                "eligible_units": 12,
                "unit": "message",
                "retrieved_count": 12,
                "has_more": False,
            },
        )

        # 最大 coverage 只解决独立 root 的调用顺序问题；Host scope 事实冲突仍必须显式失败。
        conflicting_coverage = dict(smaller_record.query_scope_snapshot["coverage"])
        conflicting_coverage["eligible_units"] = 13
        conflicting_snapshot = {
            **smaller_record.query_scope_snapshot,
            "total_hits": 13,
            "coverage": conflicting_coverage,
        }
        conflicting_record = replace(
            smaller_record,
            query_scope_snapshot=conflicting_snapshot,
        )
        with self.assertRaises(AnswerFinalizationError) as raised:
            finalize_answer(
                output,
                run_id="run-independent-root",
                tool_results=(complete_record, conflicting_record),
                scope=self.scope,
            )
        self.assertEqual(raised.exception.code, "COVERAGE_MISMATCH")

        conflicting_range = dict(smaller_record.query_scope_snapshot["resolved_time_range"])
        conflicting_range["resolved_start_timestamp"] = BASE_TIMESTAMP + 1
        conflicting_record = replace(
            smaller_record,
            query_scope_snapshot={
                **smaller_record.query_scope_snapshot,
                "resolved_time_range": conflicting_range,
            },
        )
        with self.assertRaises(AnswerFinalizationError) as raised:
            finalize_answer(
                output,
                run_id="run-independent-root",
                tool_results=(complete_record, conflicting_record),
                scope=self.scope,
            )
        self.assertEqual(raised.exception.code, "TIME_RANGE_MISMATCH")

    def test_recent_messages_cursor_rejects_modified_host_time_fact(self) -> None:
        cursor = self._page(None, limit=3).metadata.details["next_cursor"]
        assert isinstance(cursor, dict)
        modified = dict(cursor)
        modified_range = dict(modified["resolved_time_range"])
        modified_range["resolved_start_utc"] = "2026-06-13T00:00:00.000Z"
        modified["resolved_time_range"] = modified_range
        with self.assertRaises(CapabilityContractError):
            self.capability.execute(GetRecentMessagesInput(cursor=modified, limit=3), self.scope)

    def test_recent_messages_tool_projection_truncation(self) -> None:
        messages = tuple(_bulk_message(index, f"message {index} " + ("内容 " * 60)) for index in range(500))
        query = RecentMessagesQuery(
            session_ids=(SESSION,),
            start_timestamp=BASE_TIMESTAMP,
            end_timestamp=WINDOW_END,
            limit=500,
        )
        result = StructuredMessageResult(
            query=query,
            strategy="structured",
            messages=messages,
            total_hits=500,
            returned_count=500,
            coverage=Coverage("complete", "canonical_store", 500, 500, "message"),
            partial=False,
            truncated=False,
            metadata=RetrievalMetadata(
                filters=query.to_dict(),
                ordering="test",
                latency_ms=0.0,
                details={"retrieved_count": 500, "has_more": False},
            ),
        )
        envelope = ToolEnvelope("ok", result, {"truncated": False}, None)
        record = build_tool_result_record(
            run_id="run-projection",
            tool_call_id="run-projection/tool/1",
            tool_result_id="run-projection/tool/1/result",
            tool_name="get_recent_messages",
            envelope=envelope,
            scope=ExecutionScope(allowed_session_ids=(SESSION,), max_results=500),
        )
        projected = project_tool_result_for_model(
            envelope,
            record,
            token_budget=DEFAULT_TOOL_RESULT_TOKEN_BUDGET,
        )
        metrics = projected["model_projection"]
        data = projected["data"]
        self.assertEqual(data["total_hits"], 500)
        self.assertEqual(data["returned_count"], 500)
        self.assertEqual(data["metadata"]["details"]["retrieved_count"], 500)
        self.assertTrue(metrics["truncated"])
        self.assertGreater(metrics["omitted_messages"], 0)
        self.assertEqual(
            metrics["projected_count"] + metrics["omitted_messages"],
            500,
        )
        self.assertEqual(len(data["messages"]), metrics["projected_count"])
        self.assertLessEqual(metrics["estimated_tokens"], DEFAULT_TOOL_RESULT_TOKEN_BUDGET)

    def test_recent_messages_ui_projection_preserves_window_facts(self) -> None:
        envelope = self.tool.invoke(self._first_request(limit=3), self.scope)
        record = build_tool_result_record(
            run_id="run-ui",
            tool_call_id="run-ui/tool/1",
            tool_result_id="run-ui/tool/1/result",
            tool_name="get_recent_messages",
            envelope=envelope,
            scope=self.scope,
        )
        detail = project_tool_result_detail(record)
        structure = project_tool_result_structure(record)
        self.assertIn("total_hits: 12", detail)
        self.assertIn("returned: 3", detail)
        result = structure["result"]
        self.assertEqual(result["total_hits"], 12)
        self.assertEqual(result["retrieved_count"], 3)
        self.assertTrue(result["has_more"])
        self.assertEqual(result["resolved_time_range"]["resolved_start_timestamp"], BASE_TIMESTAMP)

    def test_recent_messages_empty_window_complete(self) -> None:
        request = GetRecentMessagesInput(
            start_timestamp=BASE_TIMESTAMP - 100_000,
            end_timestamp=BASE_TIMESTAMP - 50_000,
            limit=100,
        )
        envelope = self.tool.invoke(request, self.scope)
        self.assertEqual(envelope.status, "ok")
        self.assertIsNotNone(envelope.data)
        assert envelope.data is not None
        self.assertEqual(envelope.data.total_hits, 0)
        self.assertEqual(envelope.data.returned_count, 0)
        self.assertEqual(envelope.data.coverage.status, "complete")
        self.assertFalse(envelope.data.partial)
        record = build_tool_result_record(
            run_id="run-empty",
            tool_call_id="run-empty/tool/1",
            tool_result_id="run-empty/tool/1/result",
            tool_name="get_recent_messages",
            envelope=envelope,
            scope=self.scope,
        )
        self.assertTrue(has_verified_zero_result_evidence((record,)))
        artifact = finalize_answer(
            json.dumps({"kind": "no_result", "summary": "窗口内没有消息", "limitations": []}),
            run_id="run-empty",
            tool_results=(record,),
            scope=self.scope,
        )
        self.assertEqual(
            artifact.retrieval_coverage,
            {
                "status": "complete",
                "basis": "canonical_store",
                "covered_units": 0,
                "eligible_units": 0,
                "unit": "message",
                "retrieved_count": 0,
                "has_more": False,
            },
        )

    def test_recent_messages_trace_records_page_coverage_and_time_range(self) -> None:
        trace_store = SQLiteTraceStore(Path(self.temporary.name) / "temporal-trace.sqlite3")
        try:
            collector = TraceCollector(
                trace_store,
                trace_id="trace-temporal",
                request_id="request-temporal",
            )
            envelope = self.tool.invoke_with_trace(
                GetRecentMessagesInput(
                    start_timestamp=BASE_TIMESTAMP,
                    end_timestamp=WINDOW_END,
                    sender_user_ids=("qq:uid:u_a",),
                    limit=3,
                ),
                self.scope,
                collector.operation_context("query").child("tool:temporal-1"),
            )
            self.assertEqual(envelope.status, "partial")
            projection = project_trace(trace_store.read_trace("trace-temporal"))
            started_event = next(
                event
                for event in projection.timeline
                if event.operation == "tool.call.started"
            )
            self.assertEqual(started_event.payload["request"]["sender_user_ids"], ["qq:uid:u_a"])
            retrieval_event = next(
                event
                for event in projection.timeline
                if event.operation == "structured.browse.completed"
            )
            self.assertEqual(retrieval_event.payload["total_hits"], 6)
            self.assertEqual(retrieval_event.payload["retrieved_count"], 3)
            self.assertTrue(retrieval_event.payload["has_more"])
            self.assertEqual(retrieval_event.payload["coverage"]["status"], "partial")
            self.assertEqual(
                retrieval_event.payload["resolved_time_range"]["resolved_start_timestamp"],
                BASE_TIMESTAMP,
            )
        finally:
            trace_store.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
