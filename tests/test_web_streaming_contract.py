"""Web UI 契约扩展测试：reasoning visibility、abort 链路、结构化 Tool Result、Conversation 管理。"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any

from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecutionScope
from trivae.conversation import (
    ConversationNotFoundError,
    SQLiteConversationStore,
    TurnProcessCollector,
)
from trivae.query.contracts import QueryContractError, QueryRequest
from trivae.query.evidence import (
    AnswerArtifact,
    AnswerContentBlock,
    ToolMessageItem,
    ToolResultRecord,
)
from trivae.query.orchestrator import QueryOrchestrator
from trivae.query.planner import SoftPlanner
from trivae.query.router import RuleRouter
from trivae.query.runtime.contracts import AgentRunRequest, RuntimeEvent, RuntimeResult
from trivae.query.streaming import (
    WEB_TOOL_RESULT_MAX_ITEMS,
    QueryStreamAdapter,
    project_tool_result_structure,
)
from trivae.retrieval.structured import MessageProjection


def _message(index: int, content: str) -> MessageProjection:
    return MessageProjection(
        internal_message_id=f"m{index}",
        session_id="qq:100",
        source_message_id=f"src-{index}",
        sender_user_id="u1",
        sender_platform_id="qq",
        sender_uin="10001",
        sender_name=f"发送者{index}",
        timestamp=1_768_435_200_000 + index,
        seq=index,
        message_type="text",
        normalized_content=content,
        reply_to_source_message_id=None,
        recalled=False,
        system=False,
        session_display="测试群",
    )


def _record(message_count: int = 2) -> ToolResultRecord:
    items = tuple(
        ToolMessageItem(
            f"message/m{i}",
            _message(i, f"内容 {i}"),
            False,
            (),
            True,
        )
        for i in range(message_count)
    )
    return ToolResultRecord(
        run_id="run-1",
        tool_call_id="run-1/tool-call/1",
        tool_result_id="run-1/tool-result/1",
        tool_name="semantic_search",
        status="ok",
        scope_snapshot={},
        query_scope_snapshot={},
        message_items=items,
    )


def _runtime_event(event_type: str, **kwargs: object) -> RuntimeEvent:
    values: dict[str, object] = {"provider": "test", "model": "test-model", "sequence": 1}
    values.update(kwargs)
    return RuntimeEvent(type=event_type, **values)  # type: ignore[arg-type]


def _normalized(
    operation: str,
    payload: dict[str, object],
    *,
    stage: str = "query",
    operation_id: str | None = None,
) -> Any:
    from trivae.observability.contracts import NormalizedQueryEvent

    return NormalizedQueryEvent(
        schema_version=1,
        event_id="event-1",
        trace_id="trace-1",
        request_id="request-1",
        sequence=1,
        occurred_at="2026-08-27T00:00:00.000+00:00",
        observed_at="2026-08-27T00:00:00.000+00:00",
        stage=stage,
        operation=operation,
        phase="completed",
        operation_id=operation_id or operation,
        outcome="ok",
        duration_ms=12.5,
        payload=payload,
    )


class _EventSink:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def __call__(self, event: Any) -> None:
        self.events.append(event)


class ThinkingVisibilityPolicyTests(unittest.TestCase):
    """provider reasoning delta 按 visibility policy 决定是否进入 live stream。"""

    def test_default_policy_keeps_public_summary_only(self) -> None:
        sink = _EventSink()
        adapter = QueryStreamAdapter(sink)
        adapter.handle_runtime_event(_runtime_event("turn_started"))
        adapter.handle_runtime_event(
            _runtime_event("thinking_delta", text="raw CoT", thinking_visibility="provider_reasoning")
        )
        adapter.handle_runtime_event(
            _runtime_event("thinking_delta", text="公开摘要", thinking_visibility="public_summary")
        )

        deltas = [event for event in sink.events if event.type == "thinking.delta"]
        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].content, "公开摘要")
        self.assertEqual(deltas[0].thinking_visibility, "public_summary")

    def test_web_policy_passes_provider_reasoning_and_splits_segments(self) -> None:
        sink = _EventSink()
        adapter = QueryStreamAdapter(
            sink,
            thinking_visibility_policy=frozenset({"public_summary", "provider_reasoning"}),
        )
        adapter.handle_runtime_event(_runtime_event("turn_started"))
        adapter.handle_runtime_event(
            _runtime_event("thinking_delta", text="raw CoT", thinking_visibility="provider_reasoning")
        )
        adapter.handle_runtime_event(
            _runtime_event("thinking_delta", text="公开摘要", thinking_visibility="public_summary")
        )
        adapter.handle_runtime_event(_runtime_event("tool_started", tool_name="semantic_search"))

        started = [event for event in sink.events if event.type == "thinking.started"]
        completed = [event for event in sink.events if event.type == "thinking.completed"]
        deltas = [event for event in sink.events if event.type == "thinking.delta"]
        # turn_started 开启第一段；visibility 切换把 summary 与 raw reasoning 分成两个段。
        self.assertEqual(len(started), 2)
        self.assertEqual(len(completed), 2)
        self.assertEqual([(event.content, event.thinking_visibility) for event in deltas],
                         [("raw CoT", "provider_reasoning"), ("公开摘要", "public_summary")])

    def test_invalid_policy_value_is_rejected_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with create_application(Path(directory) / "app.sqlite3") as application:
                request = QueryRequest(query="问题", scope=ExecutionScope())
                with self.assertRaises(QueryContractError):
                    asyncio.run(
                        application.query(
                            request,
                            on_event=lambda event: None,
                            thinking_visibility_policy={"hiddEn_reasoning"},
                        )
                    )


class StructuredToolResultProjectionTests(unittest.TestCase):
    """tool.completed 携带结构化 result projection，TUI 文本投影保持不变。"""

    def test_projection_contains_real_message_fields(self) -> None:
        projection = project_tool_result_structure(_record(2))
        self.assertEqual(projection["tool_name"], "semantic_search")
        result = projection["result"]
        assert isinstance(result, dict)
        items = result["items"]
        assert isinstance(items, list)
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first["kind"], "message")
        self.assertEqual(first["sender"], "发送者0")
        self.assertEqual(first["session"], "测试群")
        self.assertEqual(first["content"], "内容 0")
        self.assertEqual(first["source_handle"], "m1-1")
        self.assertFalse(result["transport_truncated"])

    def test_transport_truncation_is_explicit(self) -> None:
        projection = project_tool_result_structure(_record(WEB_TOOL_RESULT_MAX_ITEMS + 5))
        result = projection["result"]
        assert isinstance(result, dict)
        self.assertEqual(len(result["items"]), WEB_TOOL_RESULT_MAX_ITEMS)
        self.assertEqual(result["total_items"], WEB_TOOL_RESULT_MAX_ITEMS + 5)
        self.assertTrue(result["transport_truncated"])

    def test_adapter_emits_projection_on_tool_completed(self) -> None:
        sink = _EventSink()
        adapter = QueryStreamAdapter(sink)
        record = _record(2)
        adapter.handle_runtime_event(
            _runtime_event("tool_completed", tool_name="semantic_search", tool_call_id="run-1/tool-call/1", tool_result=record)
        )
        completed = [event for event in sink.events if event.type == "tool.completed"]
        self.assertEqual(len(completed), 1)
        self.assertIsNotNone(completed[0].result_projection)
        self.assertIsNotNone(completed[0].result_detail)


class _AbortedStreamRuntime:
    """支持 stream(request, abort_event) 的 fake runtime；abort 立即返回 aborted 终态。"""

    def __init__(self) -> None:
        self.seen_abort_events: list[object] = []

    def stream(self, request: AgentRunRequest, abort_event: object | None = None) -> Any:
        self.seen_abort_events.append(abort_event)

        async def _iterator() -> Any:
            if abort_event is not None and getattr(abort_event, "is_set", lambda: False)():
                yield _runtime_event("aborted", result=self._aborted())
                return
            yield _runtime_event("run_started")
            yield _runtime_event("content_delta", text="partial")
            yield _runtime_event("aborted", result=self._aborted())

        return _iterator()

    def _aborted(self) -> RuntimeResult:
        return RuntimeResult(
            final_answer=None,
            provider="test",
            model="test-model",
            termination="aborted",
            tool_calls=(),
        )

    async def run(self, request: AgentRunRequest) -> RuntimeResult:
        return self._aborted()


class ProvisionalAnswerStreamingTests(unittest.TestCase):
    """provisional_answer_streaming=True 时正文即时流出；Tool 边界显式降级。"""

    def _adapter(self, sink: _EventSink) -> QueryStreamAdapter:
        return QueryStreamAdapter(sink, provisional_answer_streaming=True)

    def test_default_mode_keeps_buffered_flush(self) -> None:
        sink = _EventSink()
        adapter = QueryStreamAdapter(sink)
        adapter.handle_runtime_event(_runtime_event("turn_started"))
        adapter.handle_runtime_event(_runtime_event("content_delta", text="第一段"))
        # turn 未结束前不产生 answer.delta（既有保守语义）。
        self.assertEqual([event.type for event in sink.events if event.type == "answer.delta"], [])
        adapter.handle_runtime_event(_runtime_event("turn_completed"))
        deltas = [event for event in sink.events if event.type == "answer.delta"]
        self.assertEqual([event.content for event in deltas], ["第一段"])
        self.assertFalse(deltas[0].provisional)

    def test_provisional_deltas_stream_immediately(self) -> None:
        sink = _EventSink()
        adapter = self._adapter(sink)
        adapter.handle_runtime_event(_runtime_event("turn_started"))
        adapter.handle_runtime_event(_runtime_event("content_delta", text='{"claims":[{"text":"你'))
        adapter.handle_runtime_event(_runtime_event("content_delta", text='好"}]}'))
        deltas = [event for event in sink.events if event.type == "answer.delta"]
        # delta 到达即流出，不等 turn 边界。
        self.assertEqual([event.content for event in deltas], ["你", "好"])
        self.assertTrue(all(event.provisional for event in deltas))
        adapter.handle_runtime_event(_runtime_event("turn_completed"))
        # turn 边界不重复 flush。
        self.assertEqual(len([event for event in sink.events if event.type == "answer.delta"]), 2)

    def test_tool_boundary_supersedes_provisional_text(self) -> None:
        sink = _EventSink()
        adapter = self._adapter(sink)
        adapter.handle_runtime_event(_runtime_event("turn_started"))
        adapter.handle_runtime_event(_runtime_event("content_delta", text="先说明一下，我需要先查数据"))
        adapter.handle_runtime_event(_runtime_event("tool_started", tool_name="semantic_search", tool_call_id="run/t/1"))
        superseded = [event for event in sink.events if event.type == "answer.superseded"]
        self.assertEqual(len(superseded), 1)
        self.assertEqual(superseded[0].content, "先说明一下，我需要先查数据")
        # 后续最终 turn 正文不再被降级。
        adapter.handle_runtime_event(_runtime_event("turn_completed"))
        adapter.handle_runtime_event(_runtime_event("turn_started"))
        adapter.handle_runtime_event(_runtime_event("content_delta", text="最终答案"))
        adapter.handle_runtime_event(_runtime_event("turn_completed"))
        self.assertEqual(len([event for event in sink.events if event.type == "answer.superseded"]), 1)
        final_deltas = [event for event in sink.events if event.type == "answer.delta"]
        self.assertEqual([event.content for event in final_deltas], ["先说明一下，我需要先查数据", "最终答案"])


class GracefulAbortChainTests(unittest.TestCase):
    """abort_event 从 Application 一路透传到 runtime stream，终态为 aborted。"""

    def test_application_query_abort_produces_aborted_terminal_without_commit(self) -> None:
        class _EventRuntime(asyncio.Event):
            pass

        with tempfile.TemporaryDirectory() as directory:
            runtime = _AbortedStreamRuntime()
            with create_application(Path(directory) / "app.sqlite3", agent_runtime=runtime) as application:
                abort_event = _EventRuntime()
                abort_event.set()
                sink = _EventSink()
                request = QueryRequest(query="测试问题", scope=ExecutionScope())
                result = asyncio.run(
                    application.query(request, on_event=sink, abort_event=abort_event)
                )
                self.assertEqual(result.termination, "aborted")
                self.assertEqual(len(runtime.seen_abort_events), 1)
                self.assertIs(runtime.seen_abort_events[0], abort_event)
                # aborted 不是成功回答；conversation 不得提交 user/assistant turn。
                summaries = application.list_conversations()
                self.assertEqual(summaries[0].message_count, 0)
                terminal = [event for event in sink.events if event.type == "query.aborted"]
                self.assertEqual(len(terminal), 1)

    def test_orchestrator_without_trace_still_honors_abort(self) -> None:
        runtime = _AbortedStreamRuntime()
        orchestrator = QueryOrchestrator(runtime, RuleRouter(), SoftPlanner())
        request = QueryRequest(query="测试问题", scope=ExecutionScope())
        abort_event = asyncio.Event()
        abort_event.set()
        result = asyncio.run(orchestrator.run(request, abort_event=abort_event))
        self.assertEqual(result.termination, "aborted")

    def test_abort_without_streaming_runtime_fails_explicitly(self) -> None:
        class _RunOnlyRuntime:
            async def run(self, request: AgentRunRequest) -> RuntimeResult:
                return RuntimeResult(
                    final_answer="ok",
                    provider="test",
                    model="test-model",
                    termination="completed",
                    tool_calls=(),
                )

        from trivae.observability.collector import TraceableAgentRuntime, TraceCollector
        from trivae.observability.sqlite import SQLiteTraceStore

        with tempfile.TemporaryDirectory() as directory:
            trace_store = SQLiteTraceStore(Path(directory) / "trace.sqlite3")
            collector = TraceCollector(trace_store, trace_id="trace-1", request_id="request-1")
            traceable = TraceableAgentRuntime(_RunOnlyRuntime(), collector, abort_event=asyncio.Event())
            with self.assertRaises(ValueError):
                asyncio.run(traceable.run(AgentRunRequest(query="问题", scope=ExecutionScope())))


class TurnProcessCollectorTests(unittest.TestCase):
    """过程摘要只收集真实事件，输出可持久化 bounded mapping。"""

    def _collect(self) -> dict[str, object]:
        collector = TurnProcessCollector()
        adapter = QueryStreamAdapter(
            collector.handle,
            thinking_visibility_policy=frozenset({"public_summary", "provider_reasoning"}),
        )
        for event in (
            _runtime_event("turn_started"),
            _runtime_event("thinking_delta", text="分析问题", thinking_visibility="public_summary"),
            _runtime_event("thinking_completed"),
        ):
            adapter.handle_runtime_event(event)
        # tool arguments 通过 normalized tool.call.started 事件进入 live stream；
        # 随后 runtime tool_completed 携带 canonical ToolResultRecord。
        adapter.handle_normalized_event(
            _normalized(
                "tool.call.started",
                {"tool_name": "get_recent_messages", "request": {"limit": 20}},
                stage="tool",
                operation_id="run-1/tool-call/1",
            )
        )
        adapter.handle_runtime_event(
            _runtime_event(
                "tool_completed",
                tool_name="get_recent_messages",
                tool_call_id="run-1/tool-call/1",
                tool_result=_record(2),
            ),
        )
        return collector.to_projection()

    def test_projection_has_router_plan_steps(self) -> None:
        projection = self._collect()
        self.assertEqual(projection["status"], None)
        steps = projection["steps"]
        assert isinstance(steps, list)
        kinds = [step["kind"] for step in steps]
        self.assertEqual(kinds, ["thinking", "tool"])
        tool_step = steps[1]
        self.assertEqual(tool_step["tool_name"], "get_recent_messages")
        self.assertEqual(tool_step["status"], "completed")
        self.assertEqual(tool_step["total_items"], 2)

    def test_router_and_terminal_facts_are_captured(self) -> None:
        sink = _EventSink()
        collector = TurnProcessCollector()
        adapter = QueryStreamAdapter(lambda event: (collector.handle(event), sink(event)))

        adapter.handle_normalized_event(_normalized("router.decision", {
            "route": "planned_execution",
            "confidence": 0.92,
            "source": "rule",
            "reason": "dependent investigation",
            "degraded": False,
            "degradation_code": None,
        }, stage="router", operation_id="router"))
        adapter.handle_normalized_event(_normalized("query.failed", {"error_code": "X", "error_message": "失败"}))
        projection = collector.to_projection()
        router = projection["router"]
        assert isinstance(router, dict)
        self.assertEqual(router["route"], "planned_execution")
        self.assertEqual(router["reason"], "dependent investigation")
        self.assertEqual(projection["status"], "failed")
        error = projection["error"]
        assert isinstance(error, dict)
        self.assertEqual(error["code"], "X")


class ConversationManagementTests(unittest.TestCase):
    """rename/delete/preview/process projection 的持久化契约。"""

    def test_rename_overrides_title_and_delete_removes_only_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteConversationStore(Path(directory) / "conversation.sqlite3")
            conversation = store.create_conversation()
            store.commit_turn(
                conversation.conversation_id,
                "第一条问题",
                AnswerArtifact(content_blocks=(AnswerContentBlock("answer", "回答"),)),
                trace_id="trace-123",
                process_projection={"schema_version": 1, "router": {"route": "standard_execution"}},
            )
            renamed = store.rename_conversation(conversation.conversation_id, "自定义标题")
            self.assertEqual(renamed.conversation_id, conversation.conversation_id)
            summaries = store.list_summaries()
            self.assertEqual(summaries[0].title, "自定义标题")
            self.assertIsNotNone(summaries[0].preview)

            restored = store.get_conversation(conversation.conversation_id)
            self.assertEqual(restored.messages[1].trace_id, "trace-123")
            projection = restored.messages[1].process_projection
            assert projection is not None
            router = projection["router"]
            assert isinstance(router, dict)
            self.assertEqual(router["route"], "standard_execution")

            store.delete_conversation(conversation.conversation_id)
            with self.assertRaises(ConversationNotFoundError):
                store.get_conversation(conversation.conversation_id)
            self.assertEqual(store.list_summaries(), ())
            with self.assertRaises(ConversationNotFoundError):
                store.rename_conversation(conversation.conversation_id, "不存在")
            store.close()

    def test_oversized_process_projection_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteConversationStore(Path(directory) / "conversation.sqlite3")
            conversation = store.create_conversation()
            with self.assertRaises(Exception) as raised:
                store.commit_turn(
                    conversation.conversation_id,
                    "问题",
                    AnswerArtifact(content_blocks=(AnswerContentBlock("answer", "回答"),)),
                    process_projection={"blob": "x" * 40_000},
                )
            self.assertIn("process projection", str(raised.exception))
            store.close()

    def test_application_facade_rename_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with create_application(Path(directory) / "app.sqlite3") as application:
                conversation = application.create_conversation()
                application.rename_conversation(conversation.conversation_id, "新名字")
                summaries = application.list_conversations()
                self.assertEqual(summaries[0].title, "新名字")
                application.delete_conversation(conversation.conversation_id)
                self.assertEqual(application.list_conversations(), ())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
