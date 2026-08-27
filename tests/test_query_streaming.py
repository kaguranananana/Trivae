from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecutionScope
from trivae.observability.collector import TraceCollector
from trivae.observability.contracts import FailureInfo, NormalizedQueryEvent, TracePhase, TraceStage
from trivae.query.contracts import QueryRequest
from trivae.query.evidence import ToolMessageItem, ToolResultRecord
from trivae.query.runtime.contracts import RuntimeEvent, RuntimeResult
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter
from trivae.query.streaming import (
    AnswerArtifactDeltaParser,
    AnswerDeltaParseError,
    QueryStreamAdapter,
    QueryStreamEvent,
)
from trivae.retrieval.structured import MessageProjection


class _StreamingAnswerRuntime:
    """输出真实 RuntimeEvent 顺序，验证 Application 不逐 token 提交 Conversation。"""

    _artifact = (
        '{"content_blocks":['
        '{"block_id":"first","text":"第一段"},'
        '{"block_id":"second","text":"第二段"}'
        '],"citation_bindings":[],"evidence_items":[],"limitations":[]}'
    )

    async def stream(self, request):
        """把结构化 artifact 切成多个 provider delta，并只返回一个 terminal result。"""

        yield RuntimeEvent("run_started", "test", "stream-model", 1, run_id="stream-run")
        yield RuntimeEvent("turn_started", "test", "stream-model", 2, run_id="stream-run")
        yield RuntimeEvent("thinking_delta", "test", "stream-model", 3, text="检索证据", run_id="stream-run")
        yield RuntimeEvent("thinking_completed", "test", "stream-model", 4, run_id="stream-run")
        for sequence, chunk in enumerate(
            (self._artifact[:19], self._artifact[19:47], self._artifact[47:]),
            start=5,
        ):
            yield RuntimeEvent(
                "content_delta",
                "test",
                "stream-model",
                sequence,
                text=chunk,
                run_id="stream-run",
            )
        result = RuntimeResult(
            final_answer=self._artifact,
            provider="test",
            model="stream-model",
            termination="completed",
            tool_calls=(),
            run_id="stream-run",
        )
        yield RuntimeEvent("completed", "test", "stream-model", 8, result=result, run_id="stream-run")

    async def run(self, request):
        """非 streaming caller 仍可按同一 Runtime contract 完整消费 terminal。"""

        terminal = None
        async for event in self.stream(request):
            if event.result is not None:
                terminal = event.result
        if terminal is None:
            raise RuntimeError("test runtime ended without terminal result")
        return terminal


class _LongRunOnlyRuntime:
    """不产生 delta 的 runtime，用于验证 normal Trace 截断不污染 authoritative live answer。"""

    answer = "长答案" * 240

    async def run(self, request):
        """返回 Finalizer 可接受的 plain text，正文长度显著超过 normal capture 上限。"""

        return RuntimeResult(
            final_answer=self.answer,
            provider="test",
            model="run-only-model",
            termination="completed",
            tool_calls=(),
            run_id="long-run",
        )


class _SafeFailedRuntime:
    """返回 Runtime-owned 安全错误文案，验证 terminal live event 不丢失信息。"""

    async def run(self, request):
        """错误正文已经过 Runtime adapter 边界归一化，不包含 provider exception body。"""

        from trivae.query.runtime.contracts import RuntimeErrorInfo

        return RuntimeResult(
            final_answer=None,
            provider="test",
            model="failed-model",
            termination="failed",
            tool_calls=(),
            error=RuntimeErrorInfo(
                code="SAFE_RUNTIME_FAILURE",
                message="agent runtime execution failed",
            ),
            run_id="failed-run",
        )


class _BrokenTraceStore:
    """只模拟持久化失败，证明 live observer 不依赖 SQLite polling。"""

    def create_trace(self, trace_id, request_id, profile, started_at):
        raise OSError("create unavailable")

    def append_event(self, event):
        raise OSError("append unavailable")

    def mark_terminal(self, trace_id, terminal_outcome, terminal_at):
        raise OSError("terminal unavailable")

    def read_trace(self, trace_id):
        raise OSError("read unavailable")


def _normalized_event(
    sequence: int,
    operation: str,
    *,
    stage: TraceStage,
    phase: TracePhase,
    payload: dict[str, object],
    operation_id: str | None = None,
    parent_operation_id: str | None = None,
    failure: FailureInfo | None = None,
) -> NormalizedQueryEvent:
    """构造固定 normalized fact，测试 Query adapter 不依赖 Store replay。"""

    return NormalizedQueryEvent(
        schema_version=1,
        event_id=f"event-{sequence}",
        trace_id="trace-stream",
        request_id="request-stream",
        sequence=sequence,
        occurred_at="2026-08-23T00:00:00.000+00:00",
        observed_at="2026-08-23T00:00:00.000+00:00",
        stage=stage,
        operation=operation,
        phase=phase,
        operation_id=operation_id or operation,
        parent_operation_id=parent_operation_id,
        outcome="error" if failure is not None else "ok",
        duration_ms=12.5,
        payload=payload,
        failure=failure,
    )


class ProviderDeltaNormalizationTests(unittest.TestCase):
    """SDK public reasoning/content delta 在 Runtime adapter 边界完成归一化。"""

    def _event(self, event_type: str, delta: object = None) -> object:
        return SimpleNamespace(data=SimpleNamespace(type=event_type, delta=delta))

    def test_reasoning_and_answer_delta_use_provider_neutral_kinds(self) -> None:
        summary = OpenAIAgentsRuntimeAdapter._stream_delta(
            self._event("response.reasoning_summary_text.delta", "分析问题")
        )
        reasoning = OpenAIAgentsRuntimeAdapter._stream_delta(self._event("response.reasoning_text.delta", "继续分析"))
        answer = OpenAIAgentsRuntimeAdapter._stream_delta(
            self._event("response.output_text.delta", '{"content_blocks"')
        )

        self.assertEqual(summary, ("thinking_summary", "分析问题"))
        self.assertIsNone(reasoning)
        self.assertEqual(answer, ("content", '{"content_blocks"'))

    def test_provider_without_or_empty_reasoning_is_ignored(self) -> None:
        self.assertIsNone(OpenAIAgentsRuntimeAdapter._stream_delta(self._event("response.created")))
        self.assertIsNone(
            OpenAIAgentsRuntimeAdapter._stream_delta(self._event("response.reasoning_summary_text.delta", ""))
        )
        self.assertTrue(
            OpenAIAgentsRuntimeAdapter._is_thinking_done(self._event("response.reasoning_summary_text.done"))
        )


class AnswerArtifactDeltaParserTests(unittest.TestCase):
    """结构化正文在任意 chunk 边界都只输出 content_blocks text。"""

    def test_json_escapes_unicode_and_multiple_blocks_match_answer_text(self) -> None:
        raw = (
            '{"ignored":"raw metadata","content_blocks":['
            '{"text":"第一行\\n\\"引用\\"","block_id":"one"},'
            '{"block_id":"two","text":"\\u4e2d\\u6587 \\ud83d\\ude80"}'
            '],"limitations":[]}'
        )
        expected = '第一行\n"引用"\n\n中文 🚀'

        # 逐个 width 覆盖 quote、backslash、unicode escape 和 surrogate pair 的跨 chunk 边界。
        for width in range(1, len(raw) + 1):
            parser = AnswerArtifactDeltaParser()
            fragments = [parser.feed(raw[offset : offset + width]) for offset in range(0, len(raw), width)]
            parser.finish()
            self.assertEqual("".join(fragments), expected, msg=f"chunk width={width}")

    def test_plain_text_preserves_existing_finalizer_semantics(self) -> None:
        parser = AnswerArtifactDeltaParser()
        fragments = [parser.feed("  plain "), parser.feed("answer  ")]
        parser.finish()
        self.assertEqual("".join(fragments), "plain answer")

    def test_malformed_or_incomplete_json_fails_explicitly(self) -> None:
        trailing_comma = AnswerArtifactDeltaParser()
        with self.assertRaises(AnswerDeltaParseError):
            trailing_comma.feed('{"content_blocks":[],}')

        incomplete = AnswerArtifactDeltaParser()
        incomplete.feed('{"content_blocks":[{"text":"partial')
        with self.assertRaises(AnswerDeltaParseError):
            incomplete.finish()


class QueryStreamProjectionTests(unittest.TestCase):
    """Runtime 与 normalized 两个真实来源共享一个 live sequence。"""

    def test_multi_tool_projection_preserves_source_order_and_real_stats(self) -> None:
        events: list[QueryStreamEvent] = []
        adapter = QueryStreamAdapter(events.append, trace_id="trace-stream")
        facts = (
            _normalized_event(
                1,
                "query.received",
                stage="query",
                phase="started",
                payload={"query": "investigate"},
            ),
            _normalized_event(
                2,
                "tool.call.started",
                stage="tool",
                phase="started",
                operation_id="tool:a",
                payload={"tool_name": "tool_a", "request": {"keyword": "alpha"}},
            ),
            _normalized_event(
                3,
                "retrieval.search.completed",
                stage="retrieval",
                phase="completed",
                parent_operation_id="tool:a",
                payload={
                    "candidate_count": 2,
                    "total_hits": 3,
                    "returned_messages": 5,
                    "context_expansion": {"expanded_count": 5},
                    "partial": False,
                    "truncated": False,
                },
            ),
            _normalized_event(
                4,
                "tool.call.completed",
                stage="tool",
                phase="completed",
                operation_id="tool:a",
                payload={"tool_name": "tool_a", "status": "ok"},
            ),
            _normalized_event(
                5,
                "tool.call.started",
                stage="tool",
                phase="started",
                operation_id="tool:b",
                payload={"tool_name": "tool_b", "request": {"keyword": "beta"}},
            ),
            _normalized_event(
                6,
                "tool.call.failed",
                stage="tool",
                phase="failed",
                operation_id="tool:b",
                payload={"tool_name": "tool_b", "error_code": "TOOL_FAILED"},
                failure=FailureInfo(
                    error_code="TOOL_FAILED",
                    origin_stage="tool",
                    observed_stage="tool",
                    category="tool",
                    handling="returned_to_agent",
                ),
            ),
        )
        for fact in facts:
            adapter.handle_normalized_event(fact)
        adapter.handle_runtime_event(RuntimeEvent("thinking_delta", "test", "model", 7, text="综合证据"))

        self.assertEqual(
            [event.type for event in events],
            [
                "query.started",
                "tool.started",
                "retrieval.completed",
                "tool.completed",
                "tool.started",
                "tool.failed",
                "thinking.started",
                "thinking.delta",
            ],
        )
        self.assertEqual([event.sequence for event in events], list(range(1, 9)))
        self.assertEqual(events[2].result_summary["expanded_count"], 5)
        self.assertEqual(events[5].error_code, "TOOL_FAILED")
        self.assertEqual(events[7].thinking_visibility, "public_summary")

    def test_turn_tool_boundaries_form_distinct_thinking_segments(self) -> None:
        """多 Tool 回合必须保留三个独立 Thinking 生命周期，不能回写第一段。"""

        events: list[QueryStreamEvent] = []
        adapter = QueryStreamAdapter(events.append)
        for turn, tool_id in ((1, "tool:a"), (2, "tool:b")):
            adapter.handle_runtime_event(RuntimeEvent("turn_started", "test", "model", turn * 10))
            adapter.handle_runtime_event(
                RuntimeEvent("thinking_delta", "test", "model", turn * 10 + 1, text=f"分析{turn}")
            )
            adapter.handle_normalized_event(
                _normalized_event(
                    turn * 10 + 2,
                    "tool.call.started",
                    stage="tool",
                    phase="started",
                    operation_id=tool_id,
                    payload={"tool_name": f"tool_{turn}"},
                )
            )
            adapter.handle_normalized_event(
                _normalized_event(
                    turn * 10 + 3,
                    "tool.call.completed",
                    stage="tool",
                    phase="completed",
                    operation_id=tool_id,
                    payload={"tool_name": f"tool_{turn}", "status": "ok"},
                )
            )
        adapter.handle_runtime_event(RuntimeEvent("turn_started", "test", "model", 30))
        adapter.handle_runtime_event(RuntimeEvent("thinking_delta", "test", "model", 31, text="综合"))
        adapter.handle_runtime_event(RuntimeEvent("content_delta", "test", "model", 32, text="最终答案"))
        adapter.handle_runtime_event(RuntimeEvent("turn_completed", "test", "model", 33))

        lifecycle = [event.type for event in events]
        self.assertEqual(lifecycle.count("thinking.started"), 3)
        self.assertEqual(lifecycle.count("thinking.completed"), 3)
        engine_order = [event.type for event in events if event.type in {"thinking.started", "tool.started", "answer.delta"}]
        self.assertEqual(
            engine_order,
            ["thinking.started", "tool.started", "thinking.started", "tool.started", "thinking.started", "answer.delta"],
        )

    def test_tool_result_detail_is_bounded_and_separate_from_business_completeness(self) -> None:
        """TUI 省略只影响 result_detail，不伪造 partial/truncated 业务事实。"""

        message_items = tuple(
            ToolMessageItem(
                result_item_id=f"result-{index}",
                message=MessageProjection(
                    internal_message_id=f"internal-{index}",
                    session_id="session-1",
                    source_message_id=None,
                    sender_user_id=f"user-{index}",
                    sender_platform_id=None,
                    sender_uin=None,
                    sender_name=f"成员{index}",
                    timestamp=1_700_000_000 + index,
                    seq=index,
                    message_type="text",
                    normalized_content="正文" * 450,
                    reply_to_source_message_id=None,
                    recalled=False,
                    system=False,
                    session_display="测试群",
                ),
            )
            for index in range(25)
        )
        record = ToolResultRecord(
            run_id="run-1",
            tool_call_id="tool:a",
            tool_result_id="tool:a/result",
            tool_name="search_messages",
            status="ok",
            scope_snapshot={},
            query_scope_snapshot={},
            message_items=message_items,
        )
        events: list[QueryStreamEvent] = []
        QueryStreamAdapter(events.append).handle_runtime_event(
            RuntimeEvent(
                "tool_completed",
                "test",
                "model",
                1,
                tool_name="search_messages",
                tool_call_id="tool:a",
                tool_result=record,
            )
        )

        detail = events[0].result_detail or ""
        self.assertLessEqual(len(detail), 16_000)
        self.assertIn("仅显示", detail)
        self.assertIn("25 条", detail)
        self.assertIsNone(events[0].result_summary)

    def test_empty_record_detail_states_no_displayable_body(self) -> None:
        """message_items/structured_items 双空的 record 展开后必须有明确的"无可展示正文"文案。

        背景（handoff A2）：聚合型工具可能产出双空 record；expanded 视图不能留空白，
        至少要让用户看到状态事实与明确的空正文说明。
        """

        record = ToolResultRecord(
            run_id="run-1",
            tool_call_id="tool:a",
            tool_result_id="tool:a/result",
            tool_name="find_members",
            status="ok",
            scope_snapshot={},
            query_scope_snapshot={},
        )
        events: list[QueryStreamEvent] = []
        QueryStreamAdapter(events.append).handle_runtime_event(
            RuntimeEvent(
                "tool_completed",
                "test",
                "model",
                1,
                tool_name="find_members",
                tool_call_id="tool:a",
                tool_result=record,
            )
        )

        detail = events[0].result_detail or ""
        self.assertIn("结果无可展示正文", detail)
        self.assertIn("状态: ok", detail)

    def test_trace_store_failure_still_notifies_same_normalized_event(self) -> None:
        observed: list[NormalizedQueryEvent] = []
        with self.assertLogs("trivae.observability.collector", level="ERROR"):
            collector = TraceCollector(
                _BrokenTraceStore(),
                trace_id="trace-broken",
                request_id="request-broken",
                event_observer=observed.append,
            )
            emitted = collector.emit(
                stage="query",
                operation="query.received",
                phase="started",
                operation_id="query",
                payload={"query": "visible live"},
            )

        self.assertIsNotNone(emitted)
        self.assertEqual(observed, [emitted])
        self.assertTrue(collector.is_degraded)

    def test_application_streaming_keeps_one_complete_conversation_and_ephemeral_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            application = create_application(
                Path(directory) / "streaming.sqlite3",
                agent_runtime=_StreamingAnswerRuntime(),
            )
            events: list[QueryStreamEvent] = []
            result = asyncio.run(
                application.query(
                    QueryRequest("stream this", ExecutionScope()),
                    on_event=events.append,
                )
            )

            self.assertTrue(result.is_successful)
            answer_deltas = "".join(event.content or "" for event in events if event.type == "answer.delta")
            self.assertEqual(answer_deltas, "第一段\n\n第二段")
            completed = [event for event in events if event.type == "answer.completed"]
            self.assertEqual(len(completed), 1)
            self.assertEqual(completed[0].content, result.final_answer)

            conversation = application.read_conversation(result.conversation_id)
            assistant_messages = [message for message in conversation.messages if message.role == "assistant"]
            self.assertEqual(len(assistant_messages), 1)
            self.assertEqual(assistant_messages[0].content, result.final_answer)

            trace = application.read_trace(result.trace_id)
            operations = [event.operation for event in trace.timeline]
            self.assertNotIn("runtime.content_delta", operations)
            self.assertNotIn("runtime.thinking_delta", operations)
            self.assertIn("answer.finalization.completed", operations)
            self.assertIn("answer.commit.completed", operations)
            application.close()

    def test_tool_turn_provisional_text_is_not_projected_as_answer(self) -> None:
        """Tool 前的模型说明不冒充答案，只有无 Tool 的最终 turn 才进入 live answer。"""

        events: list[QueryStreamEvent] = []
        adapter = QueryStreamAdapter(events.append)
        adapter.handle_runtime_event(RuntimeEvent("turn_started", "test", "model", 1))
        adapter.handle_runtime_event(
            RuntimeEvent(
                "content_delta",
                "test",
                "model",
                2,
                text='{"content_blocks":[{"block_id":"draft","text":"先查一下"}]}',
            )
        )
        adapter.handle_runtime_event(RuntimeEvent("tool_started", "test", "model", 3))
        adapter.handle_runtime_event(RuntimeEvent("turn_completed", "test", "model", 4))

        adapter.handle_runtime_event(RuntimeEvent("turn_started", "test", "model", 5))
        adapter.handle_runtime_event(
            RuntimeEvent(
                "content_delta",
                "test",
                "model",
                6,
                text='{"content_blocks":[{"block_id":"final","text":"正式答案"}]}',
            )
        )
        adapter.handle_runtime_event(RuntimeEvent("turn_completed", "test", "model", 7))

        self.assertEqual(
            [event.content for event in events if event.type == "answer.delta"],
            ["正式答案"],
        )

    def test_run_only_authoritative_answer_is_not_truncated_by_normal_trace_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            application = create_application(
                Path(directory) / "long-answer.sqlite3",
                agent_runtime=_LongRunOnlyRuntime(),
            )
            events: list[QueryStreamEvent] = []
            result = asyncio.run(
                application.query(
                    QueryRequest("long answer", ExecutionScope(), trace_profile="normal"),
                    on_event=events.append,
                )
            )

            answer_completed = next(event for event in events if event.type == "answer.completed")
            self.assertEqual(answer_completed.content, _LongRunOnlyRuntime.answer)
            persisted_answer = next(
                event
                for event in application.read_trace(result.trace_id).timeline
                if event.operation == "answer.finalization.completed"
            )
            self.assertLess(len(persisted_answer.payload["answer_text"]), len(_LongRunOnlyRuntime.answer))
            application.close()

    def test_query_failure_event_keeps_runtime_safe_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            application = create_application(
                Path(directory) / "failed-answer.sqlite3",
                agent_runtime=_SafeFailedRuntime(),
            )
            events: list[QueryStreamEvent] = []
            result = asyncio.run(
                application.query(
                    QueryRequest("fail safely", ExecutionScope()),
                    on_event=events.append,
                )
            )

            self.assertFalse(result.is_successful)
            failed = next(event for event in events if event.type == "query.failed")
            self.assertEqual(failed.error_code, "SAFE_RUNTIME_FAILURE")
            self.assertEqual(failed.error_message, "agent runtime execution failed")
            application.close()


if __name__ == "__main__":
    unittest.main()
