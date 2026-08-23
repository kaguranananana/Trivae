"""Human-readable Execution Transcript 的 canonical projection 回归。"""

from __future__ import annotations

import unittest

from trivae.observability.contracts import FailureInfo, NormalizedQueryEvent, StoredTrace
from trivae.observability.text import format_trace_text
from trivae.observability.transcript import format_execution_transcript


def _event(
    sequence: int,
    operation: str,
    *,
    stage: str,
    phase: str,
    operation_id: str,
    payload: dict[str, object] | None = None,
    outcome: str | None = None,
    limitations: tuple[str, ...] = (),
    failure: FailureInfo | None = None,
) -> NormalizedQueryEvent:
    """构造固定 sequence 的 synthetic canonical event，避免从其他 Store 补数据。"""

    return NormalizedQueryEvent(
        schema_version=1,
        event_id=f"event-{sequence}",
        trace_id="trace-transcript",
        request_id="request-transcript",
        sequence=sequence,
        occurred_at="2026-08-23T00:00:00.000+00:00",
        observed_at="2026-08-23T00:00:00.000+00:00",
        stage=stage,  # type: ignore[arg-type]
        operation=operation,
        phase=phase,  # type: ignore[arg-type]
        operation_id=operation_id,
        outcome=outcome,  # type: ignore[arg-type]
        payload={} if payload is None else payload,
        limitations=limitations,
        failure=failure,
    )


def _build_trace() -> StoredTrace:
    """构造包含 planner failure、tool round 和 truncation 的完整 Trace。"""

    tool_output = str(
        {
            "status": "partial",
            "data": {
                "messages": [
                    {
                        "internal_message_id": "internal-message-1",
                        "session_id": "session-internal",
                        "session_display": "资料群",
                        "sender_name": "find",
                        "timestamp": 1786729140000,
                        "normalized_content": "Archify 现在可以直接装进 DeepSeek Harness 了",
                    }
                ],
                "total_hits": 77,
                "returned_messages": 20,
                "coverage": {"status": "partial", "basis": "indexed_messages"},
                "partial": True,
                "truncated": True,
            },
            "meta": {"total_hits": 77, "returned_messages": 20, "truncated": True},
            "error": None,
            "provenance": {"tool_call_id": "internal-tool-call-must-stay-raw-only"},
        }
    )
    tool_output_projection = {
        "status": "partial",
        "data": {
            "messages": [
                {
                    "internal_message_id": "internal-message-1",
                    "session_id": "session-internal",
                    "session_display": "资料群",
                    "sender_name": "find",
                    "timestamp": 1786729140000,
                    "normalized_content": "Archify 现在可以直接装进 DeepSeek Harness 了",
                }
            ],
            "total_hits": 77,
            "returned_messages": 20,
            "coverage": {"status": "partial", "basis": "indexed_messages"},
            "partial": True,
            "truncated": True,
        },
    }
    return StoredTrace(
        trace_id="trace-transcript",
        request_id="request-transcript",
        profile="debug",
        started_at="2026-08-23T00:00:00+00:00",
        terminal_at="2026-08-23T00:00:05+00:00",
        terminal_outcome="completed",
        events=(
            _event(
                1,
                "query.received",
                stage="query",
                phase="started",
                operation_id="query",
                payload={
                    "query": "整理一下最近十几天群里推荐的资料……",
                    "conversation_id": "conversation-internal",
                    "scope": {
                        "allowed_session_ids": ["session-internal"],
                        "start_timestamp": 1785600000000,
                        "end_timestamp": 1786900000000,
                        "max_results": 20,
                    },
                    "trace_profile": "debug",
                },
            ),
            _event(
                2,
                "router.decision",
                stage="router",
                phase="completed",
                operation_id="router",
                outcome="ok",
                payload={
                    "route": "planned_execution",
                    "confidence": 0.9,
                    "source": "llm",
                    "reason": "Query requires bounded retrieval and evidence.",
                    "degraded": False,
                },
            ),
            _event(
                3,
                "planner.failed",
                stage="planner",
                phase="failed",
                operation_id="planner",
                outcome="partial",
                payload={"error_code": "PLANNER_INVALID_OUTPUT", "failure_category": "invalid_output"},
                limitations=("executed_without_plan",),
                failure=FailureInfo(
                    error_code="PLANNER_INVALID_OUTPUT",
                    origin_stage="planner",
                    observed_stage="planner",
                    category="planner_failure",
                    handling="executed_without_plan",
                    cause_operation_id="planner",
                ),
            ),
            _event(
                4,
                "model.turn",
                stage="model",
                phase="started",
                operation_id="runtime:turn:1",
                payload={
                    "tool_round": 1,
                    "model_visible_context": [
                        {"role": "system", "content": "You answer the user's question."},
                        {"role": "user", "content": "整理一下最近十几天……"},
                    ],
                },
            ),
            _event(
                5,
                "model.output",
                stage="model",
                phase="completed",
                operation_id="runtime:turn:1",
                outcome="ok",
                payload={
                    "observable_output": [
                        {
                            "type": "function_call",
                            "name": "search_messages",
                            "arguments": '{"keyword":"GitHub","limit":20}',
                            "call_id": "provider-call-1",
                        }
                    ]
                },
            ),
            _event(
                6,
                "retrieval.search.completed",
                stage="retrieval",
                phase="completed",
                operation_id="tool-1:retrieval",
                outcome="partial",
                payload={
                    "strategy": "lexical",
                    "query": {"keyword": "GitHub"},
                    "returned_messages": 20,
                    "total_hits": 77,
                    "partial": True,
                    "truncated": True,
                    "coverage": {"status": "partial", "basis": "indexed_messages"},
                },
            ),
            _event(
                7,
                "runtime.tool.completed",
                stage="runtime",
                phase="completed",
                operation_id="runtime-tool-1",
                outcome="partial",
                payload={"tool_name": "search_messages", "tool_status": "partial"},
            ),
            _event(
                8,
                "model.turn",
                stage="model",
                phase="started",
                operation_id="runtime:turn:2",
                payload={
                    "tool_round": 2,
                    "model_visible_context": [
                        {"role": "system", "content": "You answer the user's question."},
                        {"role": "user", "content": "整理一下最近十几天……"},
                        {
                            "type": "function_call",
                            "name": "search_messages",
                            "arguments": '{"keyword":"GitHub","limit":20}',
                            "call_id": "provider-call-1",
                        },
                        {
                            "type": "function_call_output",
                            "call_id": "provider-call-1",
                            "output": tool_output,
                            # 模拟 Debug 字符串被 bounded capture 截断后仍可用的同源结构化投影。
                            "output_projection": tool_output_projection,
                        },
                    ],
                },
            ),
            _event(
                9,
                "model.output",
                stage="model",
                phase="completed",
                operation_id="runtime:turn:2",
                outcome="ok",
                payload={"observable_output": [{"role": "assistant", "content": "整理完成"}]},
            ),
            _event(
                10,
                "evidence.prepare.completed",
                stage="evidence",
                phase="completed",
                operation_id="evidence.prepare",
                outcome="ok",
                payload={"selected_source_count": 23, "evidence_count": 4, "limitations": []},
            ),
            _event(
                11,
                "citation.validation.completed",
                stage="citation",
                phase="completed",
                operation_id="citation.validation",
                outcome="ok",
                payload={"binding_count": 4, "unresolved_count": 0},
            ),
            _event(
                12,
                "answer.finalization.completed",
                stage="answer",
                phase="completed",
                operation_id="answer.finalization",
                outcome="ok",
                payload={"answer_length": 8, "answer_text": "整理完成：共找到 20 条资料。"},
            ),
            _event(
                13,
                "query.completed",
                stage="query",
                phase="completed",
                operation_id="query",
                outcome="ok",
                payload={},
            ),
        ),
    )


class TranscriptTests(unittest.TestCase):
    """验证 Transcript 只从 StoredTrace 派生并保留人工定位所需事实。"""

    def test_transcript_contains_execution_chain_and_model_visible_tool_result(self) -> None:
        trace = _build_trace()
        transcript = format_execution_transcript(trace)

        for marker in (
            "[USER]",
            "[ROUTER]",
            "[PLANNER]",
            "[MODEL TURN 1]",
            "[MODEL TURN 2]",
            "[TOOL CALL] search_messages",
            "[TOOL RESULT: search_messages]",
            "[RETRIEVAL]",
            "[EVIDENCE]",
            "[CITATION]",
            "[FINAL ANSWER]",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, transcript)
        self.assertIn("handling: executed_without_plan", transcript)
        self.assertIn("returned / total: 20 / 77", transcript)
        self.assertIn("truncated: true", transcript)
        self.assertIn("Archify 现在可以直接装进 DeepSeek Harness 了", transcript)
        self.assertIn("整理完成：共找到 20 条资料。", transcript)
        self.assertNotIn("internal-tool-call-must-stay-raw-only", transcript)

    def test_trace_text_contains_transcript_before_raw_events(self) -> None:
        text = format_trace_text(_build_trace())

        self.assertIn("EXECUTION TRANSCRIPT", text)
        self.assertIn("RAW TRACE EVENTS", text)
        self.assertLess(text.index("EXECUTION TRANSCRIPT"), text.index("RAW TRACE EVENTS"))
        self.assertIn("operation: planner.failed", text)
        self.assertIn("payload:", text)


if __name__ == "__main__":
    unittest.main()
