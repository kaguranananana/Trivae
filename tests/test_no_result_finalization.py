"""no-result finalization contract：合法空窗放行与 hallucination bypass 防护。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_ingestion import make_message, write_export
from trivae.capabilities.contracts import ExecutionScope, GetRecentMessagesInput
from trivae.capabilities.recent_messages import RecentMessagesCapability
from trivae.capabilities.tools import RecentMessagesTool
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.query.evidence import (
    AnswerArtifact,
    ToolResultRecord,
    build_tool_result_record,
    finalize_answer,
    finalize_answer_gracefully,
    scope_snapshot,
    tool_results_have_result_facts,
)
from trivae.retrieval.structured import StructuredRetrieval

SESSION = "qq:930"

HONEST_NO_RESULT = (
    '{"kind": "no_result",'
    ' "summary": "在解析的时间范围 1786671390000–1786844190001 内没有找到任何消息，'
    '覆盖状态为 complete，因此没有可引用的正面主题结论。",'
    ' "limitations": ["该时间窗内无消息，主题总结不适用。"]}'
)

BYPASS_NO_RESULT = '{"kind": "no_result", "summary": "最近大家在讨论 Agent 和 RAG。", "limitations": []}'


class NoResultFinalizationTests(unittest.TestCase):
    """zero-result 是合法 query outcome，但必须 Host 可验证且不可成为 citation bypass。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.database_path = directory / "no-result.sqlite3"
        base = 1_786_700_000_000
        messages = [make_message("r1", 1, base, "第一条", sender_uid="u_a")]
        export = write_export(
            directory,
            "NoResult Window(930).json",
            messages,
            chat_name="NoResult Window",
            peer_uid=None,
            version="5.5.64",
        )
        self.store = SQLiteCanonicalStore(self.database_path)
        SharedImporter(self.store).import_paths([export])
        self.repository = SQLiteCanonicalReadRepository(self.database_path)
        self.tool = RecentMessagesTool(RecentMessagesCapability(StructuredRetrieval(self.repository)))
        self.scope = ExecutionScope(allowed_session_ids=(SESSION,), start_timestamp=None, end_timestamp=None)

    def tearDown(self) -> None:
        self.repository.close()
        self.store.close()
        self.temporary.cleanup()

    def _record(self, *, empty_window: bool, tool_call_id: str) -> ToolResultRecord:
        if empty_window:
            request = GetRecentMessagesInput(start_timestamp=1_000_000, end_timestamp=1_000_500, limit=10)
        else:
            request = GetRecentMessagesInput(limit=5)
        envelope = self.tool.invoke(request, self.scope)
        return build_tool_result_record(
            run_id="run-x",
            tool_call_id=tool_call_id,
            tool_result_id=f"{tool_call_id}/result",
            tool_name="get_recent_messages",
            envelope=envelope,
            scope=self.scope,
        )

    def test_empty_window_record_has_no_result_facts(self) -> None:
        record = self._record(empty_window=True, tool_call_id="tc-e")
        self.assertFalse(tool_results_have_result_facts((record,)))

    def test_non_empty_record_has_result_facts(self) -> None:
        record = self._record(empty_window=False, tool_call_id="tc-f")
        self.assertTrue(tool_results_have_result_facts((record,)))

    def test_honest_empty_window_finalize_is_valid_without_citations(self) -> None:
        record = self._record(empty_window=True, tool_call_id="tc-v")
        result = finalize_answer_gracefully(
            HONEST_NO_RESULT, run_id="run-x", tool_results=(record,), scope=self.scope
        )
        self.assertIsNone(result.error)
        self.assertIsNotNone(result.artifact)
        if result.artifact is not None:
            self.assertEqual(len(result.artifact.content_blocks), 1)
            self.assertEqual(result.artifact.evidence_items, ())
            self.assertEqual(result.artifact.citation_bindings, ())
            self.assertIn("没有找到任何消息", result.artifact.answer_text or "")

    def test_strict_finalize_accepts_honest_empty_window(self) -> None:
        record = self._record(empty_window=True, tool_call_id="tc-s")
        artifact = finalize_answer(HONEST_NO_RESULT, run_id="run-x", tool_results=(record,), scope=self.scope)
        self.assertIsInstance(artifact, AnswerArtifact)

    def test_no_result_conflicting_with_real_results_is_fatal(self) -> None:
        # 防 bypass：tool results 确实携带消息时，no_result 候选必须 fatal 拒绝。
        record = self._record(empty_window=False, tool_call_id="tc-b")
        result = finalize_answer_gracefully(
            BYPASS_NO_RESULT, run_id="run-x", tool_results=(record,), scope=self.scope
        )
        self.assertIsNone(result.artifact)
        self.assertIsNotNone(result.error)
        if result.error is not None:
            self.assertEqual(result.error.code, "INVALID_FINAL_OUTPUT")

    def test_no_result_cannot_carry_claims(self) -> None:
        record = self._record(empty_window=True, tool_call_id="tc-m")
        with_claims_array = '{"kind": "no_result", "claims": [], "summary": "s", "limitations": []}'
        with_positive_claim = (
            '{"kind": "no_result",'
            ' "claims": [{"text":"x","finding":"f","criterion":"c","sufficiency":"sufficient",'
            '"sources":[],"limitations":[]}],'
            ' "summary": "s"}'
        )
        for payload in (with_claims_array, with_positive_claim):
            with self.subTest(payload=payload[:40]):
                with self.assertRaises(Exception):
                    finalize_answer(payload, run_id="run-x", tool_results=(record,), scope=self.scope)

    def test_no_result_without_any_tool_results_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            finalize_answer(HONEST_NO_RESULT, run_id="run-x", tool_results=(), scope=self.scope)

    def test_schema_only_records_do_not_block_no_result(self) -> None:
        # schema inspection tables[] 只是 metadata：不算检索事实，也不阻塞 no_result 放行。
        from trivae.query.evidence import ToolStructuredItem

        record = ToolResultRecord(
            run_id="run-x",
            tool_call_id="tc-schema",
            tool_result_id="tc-schema/result",
            tool_name="get_schema",
            status="ok",
            scope_snapshot=scope_snapshot(self.scope),
            query_scope_snapshot={},
            message_items=(),
            structured_items=(ToolStructuredItem("row", "tables[0]", {"name": "messages"}),),
            limitations=(),
        )
        self.assertFalse(tool_results_have_result_facts((record,)))
        result = finalize_answer_gracefully(
            HONEST_NO_RESULT, run_id="run-x", tool_results=(record,), scope=self.scope
        )
        self.assertIsNone(result.error)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
