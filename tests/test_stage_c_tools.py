from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from tests.test_ingestion import make_message, write_export
from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecutionScope
from trivae.capabilities.contracts import ExecuteSQLInput, GetSchemaInput
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
from trivae.retrieval.sql import SchemaResult, SQLQueryResult


class StageCToolsTests(unittest.TestCase):
    """验证 Stage C schema/SQL Tool 的 public schema、scope、Evidence 和 Runtime 链路。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        raw = root / "raw"
        raw.mkdir()
        write_export(
            raw,
            "stage-c-a(100).json",
            [
                self._message("a1", 1_000, "first", "u1", "Alice"),
                self._message("a2", 2_000, "second", "u1", "Alice"),
                self._message("a3", 3_000, "third", "u2", "Bob"),
                self._message("a4", 4_000, "fourth", "u1", "Alice"),
                self._message("a5", 5_000, "fifth", "u2", "Bob"),
            ],
            chat_name="Stage C A",
            peer_uid=None,
            version="5.5.64",
        )
        write_export(
            raw,
            "stage-c-b(200).json",
            [
                self._message("b1", 1_000, "sixth", "u3", "Carol"),
                self._message("b2", 2_000, "seventh", "u3", "Carol"),
                self._message("b3", 3_000, "eighth", "u1", "Alice"),
            ],
            chat_name="Stage C B",
            peer_uid=None,
            version="5.5.64",
        )
        self.application = create_application(root / "stage-c.sqlite3")
        self.application.import_directory(raw)

    def tearDown(self) -> None:
        self.application.close()
        self.temporary.cleanup()

    @staticmethod
    def _message(source_id: str, timestamp: int, text: str, user_id: str, name: str) -> dict:
        """构造含稳定 sender identity 的 SQL fixture。"""

        message = make_message(source_id, timestamp, timestamp, text, sender_uid=user_id)
        message["sender"].update(
            {
                "uin": f"uin-{user_id}",
                "name": name,
                "nickname": name.lower(),
                "groupCard": name,
                "remark": f"{name}-remark",
            }
        )
        return message

    def _execute(self, sql: str, *, scope: ExecutionScope | None = None, max_rows: int | None = None):
        """通过 Application 的正式 Tool facade 执行 SQL，不直接访问底层 connection。"""

        return self.application.invoke_tool(
            "execute_sql",
            ExecuteSQLInput(sql, max_rows=max_rows),
            scope or ExecutionScope(max_results=20),
        )

    def test_get_schema_exposes_only_public_physical_projection(self) -> None:
        """schema 返回 canonical public 表，并隐藏 ingestion/raw/derived implementation 表。"""

        envelope = self.application.invoke_tool(
            "get_schema",
            GetSchemaInput(),
            ExecutionScope(max_results=10),
        )

        self.assertEqual(envelope.status, "ok")
        self.assertIsInstance(envelope.data, SchemaResult)
        assert isinstance(envelope.data, SchemaResult)
        table_names = tuple(table.name for table in envelope.data.tables)
        self.assertEqual(table_names, ("chat_sessions", "users", "memberships", "messages"))
        self.assertNotIn("sources", table_names)
        self.assertNotIn("import_batches", table_names)
        self.assertNotIn("messages_fts", table_names)
        messages = next(table for table in envelope.data.tables if table.name == "messages")
        columns = {column.name for column in messages.columns}
        self.assertIn("content_text", columns)
        self.assertNotIn("raw_payload_json", columns)
        self.assertNotIn("canonical_projection_json", columns)

    def test_execute_sql_supports_count_group_time_sender_session_and_join(self) -> None:
        """结构化统计由 SQL 完成，覆盖 count、分组、时间半开区间和 public JOIN。"""

        count = self._execute("SELECT COUNT(*) AS total FROM messages")
        self.assertEqual(count.status, "ok")
        self.assertIsInstance(count.data, SQLQueryResult)
        assert isinstance(count.data, SQLQueryResult)
        self.assertEqual(count.data.rows, ({"total": 8},))

        sender = self._execute(
            "SELECT sender_user_id, COUNT(*) AS total FROM messages "
            "GROUP BY sender_user_id ORDER BY sender_user_id"
        )
        self.assertEqual(
            sender.data.rows if isinstance(sender.data, SQLQueryResult) else (),
            (
                {"sender_user_id": "qq:uid:u1", "total": 4},
                {"sender_user_id": "qq:uid:u2", "total": 2},
                {"sender_user_id": "qq:uid:u3", "total": 2},
            ),
        )

        time_range = self._execute(
            "SELECT COUNT(*) AS total FROM messages "
            "WHERE timestamp >= 2000 AND timestamp < 5000"
        )
        self.assertIsInstance(time_range.data, SQLQueryResult)
        assert isinstance(time_range.data, SQLQueryResult)
        self.assertEqual(time_range.data.rows, ({"total": 5},))

        sessions = self._execute(
            "SELECT s.name AS session_name, COUNT(m.internal_message_id) AS total "
            "FROM messages AS m JOIN chat_sessions AS s ON s.session_id = m.session_id "
            "GROUP BY s.name ORDER BY s.name"
        )
        self.assertIsInstance(sessions.data, SQLQueryResult)
        assert isinstance(sessions.data, SQLQueryResult)
        self.assertEqual(
            sessions.data.rows,
            (
                {"session_name": "Stage C A", "total": 5},
                {"session_name": "Stage C B", "total": 3},
            ),
        )

    def test_execute_sql_no_rows_and_result_bound_are_explicit(self) -> None:
        """零行是成功结果，超过 bound 只记录 truncation，不改变 SQL。"""

        empty = self._execute(
            "SELECT internal_message_id FROM messages WHERE internal_message_id = 'missing'"
        )
        self.assertEqual(empty.status, "ok")
        self.assertIsInstance(empty.data, SQLQueryResult)
        assert isinstance(empty.data, SQLQueryResult)
        self.assertEqual(empty.data.returned_rows, 0)
        self.assertEqual(empty.data.rows, ())
        self.assertFalse(empty.data.truncated)

        bounded = self._execute(
            "SELECT internal_message_id FROM messages ORDER BY timestamp",
            max_rows=2,
        )
        self.assertEqual(bounded.status, "ok")
        self.assertIsInstance(bounded.data, SQLQueryResult)
        assert isinstance(bounded.data, SQLQueryResult)
        self.assertEqual(bounded.data.returned_rows, 2)
        self.assertTrue(bounded.data.truncated)
        self.assertFalse(bounded.data.partial)
        self.assertEqual(bounded.meta["truncated"], True)

        over_bound = self._execute(
            "SELECT COUNT(*) AS total FROM messages",
            scope=ExecutionScope(max_results=2),
            max_rows=3,
        )
        self.assertEqual(over_bound.status, "error")
        self.assertEqual(over_bound.error.code, "INVALID_ARGUMENT")

    def test_execute_sql_blocks_write_ddl_internal_schema_and_pragma(self) -> None:
        """read-only、public schema 和内部实现边界由 driver/adapter 显式拒绝。"""

        statements = (
            ("INSERT INTO messages(internal_message_id) VALUES ('x')", "SQL_READ_ONLY_VIOLATION"),
            ("UPDATE messages SET content_text = 'x'", "SQL_READ_ONLY_VIOLATION"),
            ("DELETE FROM messages", "SQL_READ_ONLY_VIOLATION"),
            ("CREATE TABLE injected(value TEXT)", "SQL_READ_ONLY_VIOLATION"),
            ("DROP TABLE messages", "SQL_READ_ONLY_VIOLATION"),
            ("ATTACH DATABASE ':memory:' AS other", "SQL_READ_ONLY_VIOLATION"),
            ("PRAGMA table_info(messages)", "SQL_SCHEMA_VIOLATION"),
            ("SELECT raw_payload_json FROM messages", "SQL_SCHEMA_VIOLATION"),
            ("SELECT * FROM sources", "SQL_SCHEMA_VIOLATION"),
        )
        for sql, expected_code in statements:
            with self.subTest(sql=sql):
                envelope = self._execute(sql)
                self.assertEqual(envelope.status, "error")
                self.assertEqual(envelope.error.code, expected_code)

        malformed = self._execute("SELECT FROM messages")
        self.assertEqual(malformed.status, "error")
        self.assertEqual(malformed.error.code, "SQL_MALFORMED")

    def test_scope_is_hard_boundary_even_when_sql_omits_where(self) -> None:
        """模型不写 WHERE 也不能看到 scope 外数据，显式 main escape 继续失败。"""

        scope = ExecutionScope(allowed_session_ids=("qq:100",), max_results=20)
        scoped_count = self._execute("SELECT COUNT(*) AS total FROM messages", scope=scope)
        self.assertIsInstance(scoped_count.data, SQLQueryResult)
        assert isinstance(scoped_count.data, SQLQueryResult)
        self.assertEqual(scoped_count.data.rows, ({"total": 5},))
        self.assertIn("scope_filtered_temp_tables", scoped_count.data.metadata.details["scope_enforcement"])

        scoped_join = self._execute(
            "SELECT s.name AS session_name, COUNT(*) AS total "
            "FROM messages AS m JOIN chat_sessions AS s ON s.session_id = m.session_id "
            "GROUP BY s.name",
            scope=scope,
        )
        self.assertIsInstance(scoped_join.data, SQLQueryResult)
        assert isinstance(scoped_join.data, SQLQueryResult)
        self.assertEqual(scoped_join.data.rows, ({"session_name": "Stage C A", "total": 5},))

        escape = self._execute("SELECT COUNT(*) AS total FROM main.messages", scope=scope)
        self.assertEqual(escape.status, "error")
        self.assertEqual(escape.error.code, "SQL_SCOPE_VIOLATION")

        time_scoped = self._execute(
            "SELECT COUNT(*) AS total FROM messages",
            scope=ExecutionScope(
                allowed_session_ids=("qq:100",),
                start_timestamp=2_000,
                end_timestamp=5_000,
                max_results=20,
            ),
        )
        self.assertIsInstance(time_scoped.data, SQLQueryResult)
        assert isinstance(time_scoped.data, SQLQueryResult)
        self.assertEqual(time_scoped.data.rows, ({"total": 3},))

    def test_sql_rows_use_existing_structured_evidence_and_trace(self) -> None:
        """SQL row citation、schema/SQL Trace 和 transcript 都沿用现有正式链路。"""

        scope = ExecutionScope(max_results=10)
        envelope = self._execute("SELECT COUNT(*) AS total FROM messages", scope=scope)
        self.assertIsInstance(envelope.data, SQLQueryResult)
        assert isinstance(envelope.data, SQLQueryResult)
        record = build_tool_result_record(
            run_id="stage-c-run",
            tool_call_id="stage-c-run/tool-call/1",
            tool_result_id="stage-c-run/tool-call/1/result",
            tool_name="execute_sql",
            envelope=envelope,
            scope=scope,
        )
        self.assertEqual(record.structured_items[0].locator, "rows[0]")
        self.assertEqual(record.structured_items[0].value_snapshot, {"total": 8})
        item = record.structured_items[0]
        artifact = AnswerArtifact(
            content_blocks=(AnswerContentBlock("claim-1", "消息总数为 8。"),),
            citation_bindings=(CitationBinding("claim-1", ("e1",)),),
            evidence_items=(
                EvidenceItem(
                    evidence_id="e1",
                    finding="SQL 返回消息总数。",
                    criterion="当前 SQL Tool Result 的 rows[0]。",
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
        finalized = validate_answer_artifact(
            artifact,
            run_id=record.run_id,
            tool_results=(record,),
            scope=scope,
        )
        self.assertEqual(finalized.evidence_items[0].sources[0].reference.value_snapshot, {"total": 8})

        collector = TraceCollector(
            self.application._trace_store,
            trace_id="trace-stage-c",
            request_id="request-stage-c",
        )
        schema = self.application.capability_registry.invoke(
            "get_schema",
            GetSchemaInput(),
            scope,
            trace_context=collector.operation_context("tool:schema-call"),
        )
        sql = self.application.capability_registry.invoke(
            "execute_sql",
            ExecuteSQLInput("SELECT COUNT(*) AS total FROM messages"),
            scope,
            trace_context=collector.operation_context("tool:sql-call"),
        )
        self.assertEqual(schema.status, "ok")
        self.assertEqual(sql.status, "ok")
        projection = project_trace(self.application._trace_store.read_trace("trace-stage-c"))
        operations = [event.operation for event in projection.timeline]
        self.assertIn("schema.inspect.completed", operations)
        self.assertIn("sql.execute.completed", operations)
        self.assertEqual(projection.metrics.tool_count, 2)
        summary = format_trace_summary(self.application._trace_store.read_trace("trace-stage-c"))
        transcript = format_execution_transcript(self.application._trace_store.read_trace("trace-stage-c"))
        self.assertIn("schema_inspections: 1", summary)
        self.assertIn("sql_executions: 1", summary)
        self.assertIn("[SCHEMA INSPECTION]", transcript)
        self.assertIn("[SQL EXECUTION]", transcript)

    def test_schema_then_sql_uses_one_runtime_and_default_agent_has_all_six_tools(self) -> None:
        """schema→SQL 由同一 Runtime 完成，生产 Query 默认 surface 包含六个 canonical tools。"""

        runtime = OpenAIAgentsRuntimeAdapter(
            self.application.capability_registry,
            model=ScriptedModel(
                [
                    ModelStep(
                        output=[
                            function_call("get_schema", {}, call_id="schema-call"),
                        ]
                    ),
                    ModelStep(
                        output=[
                            function_call(
                                "execute_sql",
                                {"sql": "SELECT COUNT(*) AS total FROM messages"},
                                call_id="sql-call",
                            ),
                        ]
                    ),
                    ModelStep(output=[assistant_message("SQL 已返回结构化结果")]),
                ]
            ),
            max_turns=4,
        )
        result = asyncio.run(
            runtime.run(
                AgentRunRequest(
                    "统计消息总数",
                    ExecutionScope(max_results=10),
                    available_capabilities=("get_schema", "execute_sql"),
                    request_id="stage-c-runtime",
                )
            )
        )
        self.assertEqual(result.termination, "completed")
        self.assertEqual([call.name for call in result.tool_calls], ["get_schema", "execute_sql"])
        self.assertEqual(len(result.tool_results), 2)
        self.assertEqual({record.run_id for record in result.tool_results}, {result.run_id})

        full_request = AgentRunRequest(
            "综合查询",
            ExecutionScope(max_results=10),
            available_capabilities=(
                "lexical_search",
                "semantic_search",
                "get_message_context",
                "find_members",
                "get_schema",
                "execute_sql",
            ),
        )
        agent = runtime._build_agent(full_request, runtime._build_context(full_request), object())
        self.assertEqual(
            {tool.name for tool in agent.tools},
            {
                "lexical_search",
                "semantic_search",
                "get_message_context",
                "find_members",
                "get_schema",
                "execute_sql",
            },
        )
        self.assertIn("get_schema", next(tool for tool in agent.tools if tool.name == "execute_sql").description)


if __name__ == "__main__":
    unittest.main()
