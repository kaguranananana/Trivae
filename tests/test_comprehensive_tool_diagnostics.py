"""六工具综合 diagnostic catalog、Runtime 组合和 Evaluation projection 回归。"""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path

from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from trivae.capabilities import CapabilityRegistry, ExecutionScope
from trivae.capabilities.contracts import ToolEnvelope
from trivae.evaluation.checks import operational_measurements
from trivae.observability.contracts import TraceMetrics, TraceProjection, TraceTimelineItem
from trivae.query.contracts import QueryRequest, QueryResult
from trivae.query.router import RouteDecision
from trivae.query.runtime.contracts import AgentRunRequest, RuntimeResult
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter

CANONICAL_TOOLS = (
    "lexical_search",
    "semantic_search",
    "get_recent_messages",
    "get_message_context",
    "find_members",
    "get_schema",
    "execute_sql",
)


class _RecordingTool:
    """用最小 Tool double 验证六个公开 Tool 共用同一 Runtime。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[object, ExecutionScope]] = []

    def invoke(self, request: object, scope: ExecutionScope) -> ToolEnvelope:
        # 记录真实 adapter 传入的 request/scope；不在测试 Tool 中复制 Capability 行为。
        self.calls.append((request, scope))
        return ToolEnvelope(status="ok", data=None, meta={"truncated": False}, error=None)


def _timeline_item(
    sequence: int,
    *,
    stage: str,
    operation: str,
    operation_id: str,
    parent_operation_id: str | None = None,
    outcome: str | None = "ok",
    payload: dict[str, object] | None = None,
) -> TraceTimelineItem:
    """构造只包含公开 bounded facts 的 Trace timeline item。"""

    return TraceTimelineItem(
        sequence=sequence,
        stage=stage,  # type: ignore[arg-type]
        operation=operation,
        phase="failed" if outcome == "error" else "completed",  # type: ignore[arg-type]
        operation_id=operation_id,
        parent_operation_id=parent_operation_id,
        outcome=outcome,  # type: ignore[arg-type]
        duration_ms=1.0,
        limitations=(),
        payload={} if payload is None else payload,
    )


class ComprehensiveToolDiagnosticsTests(unittest.TestCase):
    """锁定完整 surface 的 deterministic contract，不替质量判断伪造 ground truth。"""

    @staticmethod
    def _catalog() -> dict[str, object]:
        path = Path(__file__).parents[1] / "evaluation" / "diagnostics" / "agent-tool-selection-comprehensive-v1.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_catalog_covers_six_tool_categories_without_legacy_default(self) -> None:
        """catalog 必须覆盖综合问题类型，并明确 preferred sequence 只是诊断期望。"""

        catalog = self._catalog()
        self.assertEqual(catalog["label_status"], "diagnostic_contract_expectation")
        self.assertEqual(tuple(catalog["available_tools"]), CANONICAL_TOOLS)
        self.assertEqual(catalog["legacy_compatibility_tools"], ["search_messages"])
        cases = catalog["cases"]
        self.assertIsInstance(cases, list)
        assert isinstance(cases, list)
        self.assertGreaterEqual(len(cases), 12)
        categories = {case["category"] for case in cases}
        self.assertTrue(
            {
                "lexical_dominant",
                "semantic_dominant",
                "context_deepening",
                "member_ambiguity",
                "structured_count",
                "structured_aggregation",
                "mixed_retrieval_sql",
                "lexical_no_result",
                "semantic_weak_or_no_result",
                "structured_zero_rows",
                "scope_sensitive_mixed",
            }.issubset(categories)
        )
        self.assertNotIn('"human_verified": true', json.dumps(catalog, ensure_ascii=False))
        self.assertEqual(
            set(catalog["recorded_observations"]),
            {
                "case_id",
                "category",
                "available_tools",
                "first_selected_tool",
                "tool_sequence",
                "retrieval_tool_sequence",
                "context_tool_sequence",
                "member_tool_sequence",
                "schema_tool_sequence",
                "sql_tool_sequence",
                "tool_call_count",
                "tool_rounds",
                "tool_errors",
                "tool_result_facts",
                "returned_messages",
                "returned_rows",
                "partial",
                "truncated",
                "coverage_statuses",
                "evidence_count",
                "citation_count",
                "citation_state",
                "finalization_state",
                "termination",
                "latency_ms",
                "usage",
                "scope_enforcement",
            },
        )

    def test_full_surface_runs_in_one_runtime_with_one_run_and_no_duplicate_tools(self) -> None:
        """六个 Tool 的组合调用共享 run_id 和 trusted scope，legacy 不会混入 visible surface。"""

        registry = CapabilityRegistry()
        recordings = {name: _RecordingTool(name) for name in CANONICAL_TOOLS}
        for tool in recordings.values():
            registry.register(tool)
        runtime = OpenAIAgentsRuntimeAdapter(
            registry,
            model=ScriptedModel(
                [
                    ModelStep(output=[function_call("lexical_search", {"keyword": "sqlite-vec"}, call_id="f1")]),
                    ModelStep(output=[function_call("semantic_search", {"query": "Agent 框架过重"}, call_id="f2")]),
                    ModelStep(output=[function_call(
                        "get_recent_messages",
                        {"time_range": {"kind": "relative", "amount": 2, "unit": "day", "anchor": "archive_latest"}, "limit": 50},
                        call_id="f3",
                    )]),
                    ModelStep(output=[function_call("get_message_context", {"message_id": "message:test"}, call_id="f4")]),
                    ModelStep(output=[function_call("find_members", {"query": "same-nick"}, call_id="f5")]),
                    ModelStep(output=[function_call("get_schema", {}, call_id="f6")]),
                    ModelStep(
                        output=[
                            function_call(
                                "execute_sql",
                                {"sql": "SELECT COUNT(*) AS total FROM messages"},
                                call_id="f7",
                            )
                        ]
                    ),
                    ModelStep(output=[assistant_message("综合调查已完成")]),
                ]
            ),
            max_turns=9,
            max_tool_rounds=7,
        )
        scope = ExecutionScope(allowed_session_ids=("session:test",), max_results=5)
        request = AgentRunRequest(
            "综合调查",
            scope,
            available_capabilities=CANONICAL_TOOLS,
            request_id="comprehensive-runtime",
        )
        agent = runtime._build_agent(request, runtime._build_context(request), object())
        result = asyncio.run(runtime.run(request))

        self.assertEqual({tool.name for tool in agent.tools}, set(CANONICAL_TOOLS))
        self.assertNotIn("search_messages", {tool.name for tool in agent.tools})
        self.assertEqual([call.name for call in result.tool_calls], list(CANONICAL_TOOLS))
        self.assertEqual(len(result.tool_calls), 7)
        self.assertEqual(len(result.tool_results), 7)
        self.assertEqual({record.run_id for record in result.tool_results}, {result.run_id})
        self.assertEqual({record.tool_name for record in result.tool_results}, set(CANONICAL_TOOLS))
        self.assertTrue(all(recording.calls[0][1] is scope for recording in recordings.values()))

        query_request = QueryRequest("综合调查", scope)
        self.assertEqual(query_request.available_capabilities, CANONICAL_TOOLS)
        self.assertNotIn("search_messages", query_request.available_capabilities)

    def test_evaluation_projection_keeps_tool_categories_and_finalization_facts(self) -> None:
        """Evaluation 从同一 Trace 投影结果计数、coverage、scope 和 Finalizer 状态。"""

        timeline = (
            _timeline_item(
                1,
                stage="tool",
                operation="tool.call.started",
                operation_id="tool:lexical",
                payload={"tool_name": "lexical_search"},
            ),
            _timeline_item(
                2,
                stage="retrieval",
                operation="retrieval.search.completed",
                operation_id="tool:lexical:retrieval.search",
                parent_operation_id="tool:lexical",
                outcome="partial",
                payload={
                    "returned_messages": 2,
                    "candidate_count": 2,
                    "partial": True,
                    "truncated": False,
                    "coverage": {"status": "partial", "basis": "test"},
                },
            ),
            _timeline_item(
                3,
                stage="tool",
                operation="tool.call.completed",
                operation_id="tool:lexical",
                payload={"tool_name": "lexical_search", "status": "partial"},
            ),
            _timeline_item(
                4,
                stage="tool",
                operation="tool.call.started",
                operation_id="tool:member",
                payload={"tool_name": "find_members"},
            ),
            _timeline_item(
                5,
                stage="tool",
                operation="member.lookup.completed",
                operation_id="tool:member:member.lookup",
                parent_operation_id="tool:member",
                payload={"tool_name": "find_members", "returned_candidates": 2, "partial": False, "truncated": False},
            ),
            _timeline_item(
                6,
                stage="tool",
                operation="tool.call.completed",
                operation_id="tool:member",
                payload={"tool_name": "find_members", "status": "ok"},
            ),
            _timeline_item(
                7,
                stage="tool",
                operation="tool.call.started",
                operation_id="tool:schema",
                payload={"tool_name": "get_schema"},
            ),
            _timeline_item(
                8,
                stage="retrieval",
                operation="schema.inspect.completed",
                operation_id="tool:schema:schema.inspect",
                parent_operation_id="tool:schema",
                payload={"tool_name": "get_schema", "returned_tables": 4, "partial": False, "truncated": False},
            ),
            _timeline_item(
                9,
                stage="tool",
                operation="tool.call.completed",
                operation_id="tool:schema",
                payload={"tool_name": "get_schema", "status": "ok"},
            ),
            _timeline_item(
                10,
                stage="tool",
                operation="tool.call.started",
                operation_id="tool:sql",
                payload={"tool_name": "execute_sql"},
            ),
            _timeline_item(
                11,
                stage="retrieval",
                operation="sql.execute.completed",
                operation_id="tool:sql:sql.execute",
                parent_operation_id="tool:sql",
                payload={
                    "tool_name": "execute_sql",
                    "returned_rows": 1,
                    "partial": False,
                    "truncated": False,
                    "coverage": {"status": "complete", "basis": "test"},
                    "scope_enforcement": "test_scope",
                    "result_bound": 5,
                    "sql_rewritten": False,
                },
            ),
            _timeline_item(
                12,
                stage="tool",
                operation="tool.call.completed",
                operation_id="tool:sql",
                payload={"tool_name": "execute_sql", "status": "ok"},
            ),
            _timeline_item(
                13,
                stage="evidence",
                operation="evidence.prepare.completed",
                operation_id="evidence.prepare",
                payload={"evidence_count": 1},
            ),
            _timeline_item(
                14,
                stage="citation",
                operation="citation.validation.completed",
                operation_id="citation.validation",
                payload={"binding_count": 1, "unresolved_count": 0},
            ),
            _timeline_item(
                15,
                stage="answer",
                operation="answer.finalization.completed",
                operation_id="answer.finalization",
                payload={"answer_length": 8},
            ),
        )
        trace = TraceProjection(
            trace_id="trace:comprehensive",
            request_id="request:comprehensive",
            profile="normal",
            started_at="2026-08-23T00:00:00+00:00",
            terminal_at="2026-08-23T00:00:01+00:00",
            terminal_status="completed",
            completeness="complete",
            timeline=timeline,
            failures=(),
            metrics=TraceMetrics(1000.0, {}, ("test-provider",), ("test-model",), {"total_tokens": 12}, 4, 1),
        )

        result = QueryResult(
            runtime_result=RuntimeResult(
                final_answer=None,
                provider="test-provider",
                model="test-model",
                termination="completed",
                tool_calls=(),
                usage={"total_tokens": 12},
            ),
            route_decision=RouteDecision("standard_execution", 1.0, "rule", "test"),
        )
        measurements = operational_measurements(result, trace)
        facts = measurements["tool_result_facts"]
        assert isinstance(facts, tuple)
        self.assertEqual([fact["tool_name"] for fact in facts], ["lexical_search", "find_members", "get_schema", "execute_sql"])
        self.assertEqual(facts[0]["returned_messages"], 2)
        self.assertEqual(facts[-1]["returned_rows"], 1)
        self.assertEqual(measurements["coverage_statuses"], ("complete", "partial"))
        self.assertEqual(measurements["scope_enforcement"], ("test_scope",))
        self.assertEqual(measurements["evidence_count"], 1)
        self.assertEqual(measurements["citation_count"], 1)
        self.assertEqual(measurements["citation_state"], "passed")
        self.assertEqual(measurements["finalization_state"], "completed")
        self.assertEqual(measurements["latency_ms"], 1000.0)
        self.assertEqual(measurements["usage"], {"total_tokens": 12})


if __name__ == "__main__":
    unittest.main()
