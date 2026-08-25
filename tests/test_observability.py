"""M6 Trace / Observability 契约、持久化和 Application boundary 回归。"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import unittest
from pathlib import Path

from trivae.bootstrap.application import create_application
from trivae.capabilities.contracts import ExecutionScope, SearchMessagesInput
from trivae.conversation import ConversationMessage, SQLiteConversationStore
from trivae.observability.collector import CapturePolicy, TraceableAgentRuntime, TraceCollector
from trivae.observability.contracts import NormalizedQueryEvent, TraceContractError
from trivae.observability.projection import project_trace
from trivae.observability.sqlite import SQLiteTraceStore, TraceStoreError
from trivae.query.contracts import QueryRequest
from trivae.query.planner import PlannerFailure, PlannerResult
from trivae.query.router import RouteDecision
from trivae.query.runtime.contracts import AgentRunRequest, RuntimeErrorInfo, RuntimeEvent, RuntimeResult


class _CompletedRuntime:
    """只返回普通文本的 run-only runtime，覆盖 M6 的 minimal injected runtime path。"""

    async def run(self, request):
        """返回带独立 run_id 的 terminal result。"""

        return RuntimeResult(
            final_answer="Trace smoke answer",
            provider="test-provider",
            model="test-model",
            termination="completed",
            tool_calls=(),
            run_id="runtime-run-1",
        )


class _FailedRuntime:
    """返回显式 Runtime failure，验证 Query terminal 不会伪装成成功。"""

    async def run(self, request):
        """返回 runtime-owned failure。"""

        return RuntimeResult(
            final_answer=None,
            provider="test-provider",
            model="test-model",
            termination="failed",
            tool_calls=(),
            error=RuntimeErrorInfo(
                code="RUNTIME_TEST_FAILURE",
                message="test runtime failure",
                category="test",
            ),
            run_id="runtime-failed-1",
        )


class _StreamingRuntime:
    """生成包含 delta、turn、usage 和 terminal 的 SDK-independent RuntimeEvent stream。"""

    async def stream(self, request):
        """提供 mapper 所需的最小真实事件顺序。"""

        yield RuntimeEvent("run_started", "stream-provider", "stream-model", 1, run_id="stream-run")
        yield RuntimeEvent(
            "turn_started",
            "stream-provider",
            "stream-model",
            2,
            tool_round=1,
            run_id="stream-run",
            model_visible_context=(
                {"role": "system", "content": "system"},
                {"role": "user", "content": "question"},
            ),
        )
        yield RuntimeEvent(
            "model_output",
            "stream-provider",
            "stream-model",
            3,
            tool_round=1,
            run_id="stream-run",
            observable_output=(
                {
                    "type": "function_call",
                    "name": "search_messages",
                    "arguments": '{"keyword":"question"}',
                    "call_id": "provider-call-1",
                },
            ),
        )
        yield RuntimeEvent("content_delta", "stream-provider", "stream-model", 4, text="hidden delta")
        yield RuntimeEvent(
            "usage_update",
            "stream-provider",
            "stream-model",
            5,
            tool_round=1,
            usage={"total_tokens": 7},
            run_id="stream-run",
        )
        result = RuntimeResult(
            final_answer="stream answer",
            provider="stream-provider",
            model="stream-model",
            termination="completed",
            tool_calls=(),
            usage={"total_tokens": 7},
            run_id="stream-run",
        )
        yield RuntimeEvent(
            "completed",
            "stream-provider",
            "stream-model",
            6,
            result=result,
            run_id="stream-run",
        )


class _ClosableRuntime:
    """用于验证 live observer 失败时 async generator 仍会显式关闭。"""

    def __init__(self) -> None:
        self.closed = False

    def stream(self, request):
        """返回带 finally 标记的最小 runtime stream。"""

        async def generate():
            try:
                yield RuntimeEvent("run_started", "test-provider", "test-model", 1)
            finally:
                # 只有 TraceableAgentRuntime 主动调用 aclose 才能在 observer 异常路径稳定执行这里。
                self.closed = True

        return generate()


class _DegradedRouter:
    """返回保留 static route 的 degraded decision。"""

    async def route(self, context):
        """模拟可恢复的 Router optional completion failure。"""

        return RouteDecision(
            route="planned_execution",
            confidence=0.4,
            source="rule",
            reason="test degraded route",
            degraded=True,
            degradation_code="ROUTER_TEST_DEGRADED",
        )


class _FailedPlanner:
    """返回 Planner failure，让 Orchestrator 继续执行 Runtime。"""

    async def plan(self, context):
        """模拟 Planner timeout。"""

        return PlannerResult(None, PlannerFailure("timeout", "test planner timeout"))


class _BrokenTraceStore:
    """每个 Trace 写入动作都失败，验证业务链路仍显式继续并留下日志。"""

    def create_trace(self, trace_id, request_id, profile, started_at):
        """模拟 Trace metadata connection failure。"""

        raise OSError("trace connection unavailable")

    def append_event(self, event):
        """模拟 append failure。"""

        raise OSError("trace append unavailable")

    def mark_terminal(self, trace_id, terminal_outcome, terminal_at):
        """模拟 terminal projection failure。"""

        raise OSError("trace terminal unavailable")

    def read_trace(self, trace_id):
        """该 fake 不提供可读取 Trace。"""

        raise TraceStoreError("trace is unavailable")


class _FailingConversationStore(SQLiteConversationStore):
    """在 assistant insert 边界失败，验证 commit failure Trace 仍可读取。"""

    def _insert_message(self, message: ConversationMessage, artifact_json: str | None) -> None:
        """让 atomic transaction 暴露真实 persistence exception。"""

        if message.role == "assistant":
            raise RuntimeError("injected conversation commit failure")
        super()._insert_message(message, artifact_json)


def _event(
    sequence: int,
    operation: str,
    *,
    trace_id: str = "trace-fixed",
    phase: str = "observed",
    stage: str = "query",
    operation_id: str = "query",
    parent_operation_id: str | None = None,
    outcome: str | None = None,
    payload: dict[str, object] | None = None,
) -> NormalizedQueryEvent:
    """构造固定时间戳 event，避免 replay 测试依赖 wall-clock。"""

    return NormalizedQueryEvent(
        schema_version=1,
        event_id=f"event-{sequence}",
        trace_id=trace_id,
        request_id="request-fixed",
        sequence=sequence,
        occurred_at="2026-08-23T00:00:00.000+00:00",
        observed_at="2026-08-23T00:00:00.000+00:00",
        stage=stage,  # type: ignore[arg-type]
        operation=operation,
        phase=phase,  # type: ignore[arg-type]
        operation_id=operation_id,
        parent_operation_id=parent_operation_id,
        outcome=outcome,  # type: ignore[arg-type]
        payload={"provider": "test-provider", "model": "test-model"} if payload is None else payload,
    )


class ObservabilityTests(unittest.TestCase):
    """覆盖 M6 最小 vertical slice。"""

    def test_trace_store_append_only_and_reopen_projection(self) -> None:
        """sequence 唯一、按 sequence replay，缺 terminal 不猜测为 completed。"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.sqlite3"
            store = SQLiteTraceStore(path)
            store.create_trace("trace-fixed", "request-fixed", "normal", "2026-08-23T00:00:00+00:00")
            store.append_event(_event(1, "query.received", phase="started"))
            incomplete = project_trace(store.read_trace("trace-fixed"))
            self.assertEqual(incomplete.terminal_status, "incomplete")
            self.assertEqual(incomplete.completeness, "incomplete")
            store.close()

            reopened = SQLiteTraceStore(path)
            reopened.append_event(_event(2, "query.completed", phase="completed", outcome="ok"))
            reopened.mark_terminal("trace-fixed", "completed", "2026-08-23T00:00:01+00:00")
            projection = project_trace(reopened.read_trace("trace-fixed"))
            self.assertEqual(projection.terminal_status, "completed")
            self.assertEqual([item.sequence for item in projection.timeline], [1, 2])
            self.assertEqual(projection.metrics.providers, ("test-provider",))
            log_path = path.parent / "traces" / "trace-fixed.log"
            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("operation: query.completed", log_text)
            self.assertIn("terminal_outcome: completed", log_text)
            with self.assertRaises(TraceStoreError):
                reopened.append_event(_event(2, "query.duplicate"))
            reopened.close()

    def test_trace_metrics_expose_tool_result_projection_budget(self) -> None:
        """Trace 公开 Host projection estimate 与 truncation 事实，不冒充 provider usage。"""

        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteTraceStore(Path(directory) / "projection.sqlite3")
            store.create_trace("trace-projection", "request-projection", "normal", "2026-08-23T00:00:00+00:00")
            store.append_event(
                _event(
                    1,
                    "runtime.run",
                    trace_id="trace-projection",
                    phase="completed",
                    stage="runtime",
                    operation_id="runtime",
                    outcome="ok",
                    payload={
                        "provider": "test-provider",
                        "model": "test-model",
                        "tool_result_estimated_tokens": 1234,
                        "tool_result_projection_truncated_count": 2,
                    },
                )
            )
            store.mark_terminal("trace-projection", "completed", "2026-08-23T00:00:01+00:00")

            projection = project_trace(store.read_trace("trace-projection"))
            self.assertEqual(projection.metrics.tool_result_estimated_tokens, 1234)
            self.assertEqual(projection.metrics.tool_result_projection_truncated_count, 2)
            self.assertNotIn("tool_result_estimated_tokens", projection.metrics.usage)
            store.close()

    def test_capture_profiles_bound_redact_and_block_hidden_reasoning(self) -> None:
        """normal/debug 都有界，secret 和 hidden reasoning 不进入 persisted payload。"""

        normal = CapturePolicy.for_profile("normal", secret_values=("secret-value",))
        payload, limitations = normal.capture(
            {
                "query": "x" * 700,
                "DEEPSEEK_API_KEY": "secret-value",
                "authorization": "Bearer abc123",
                "chain_of_thought": "private reasoning",
            }
        )
        self.assertEqual(payload["DEEPSEEK_API_KEY"], "[REDACTED]")
        self.assertEqual(payload["authorization"], "[REDACTED]")
        self.assertEqual(payload["chain_of_thought"], "[REDACTED]")
        self.assertEqual(len(payload["query"]), 512)
        self.assertIn("payload.query.truncated", limitations)
        self.assertIn("payload.chain_of_thought.hidden_reasoning_redacted", limitations)

        debug = CapturePolicy.for_profile("debug")
        debug_payload, debug_limitations = debug.capture({"query": "x" * 12_000, "answer_text": "a" * 12_000})
        self.assertEqual(len(debug_payload["query"]), 12_000)
        self.assertEqual(len(debug_payload["answer_text"]), 12_000)
        self.assertEqual(debug_limitations, ())

    def test_normalized_event_rejects_unknown_enum_values(self) -> None:
        """stage/phase/outcome 是显式 contract，不让未知字符串进入 Store。"""

        with self.assertRaises(TraceContractError):
            _event(1, "query.received", stage="unknown")

    def test_application_query_exposes_trace_and_replays_after_reopen(self) -> None:
        """QueryResult trace_id、commit 顺序和 close/reopen read facade 可恢复。"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "application.sqlite3"
            application = create_application(path, agent_runtime=_CompletedRuntime())
            result = asyncio.run(
                application.query(
                    QueryRequest("trace this", ExecutionScope(), request_id="request-visible")
                )
            )
            self.assertTrue(result.is_successful)
            self.assertIsNotNone(result.trace_id)
            self.assertNotEqual(result.trace_id, "request-visible")
            projection = application.read_trace(result.trace_id)
            operations = [item.operation for item in projection.timeline]
            self.assertLess(operations.index("answer.commit.completed"), operations.index("query.completed"))
            self.assertEqual(projection.request_id, "request-visible")
            self.assertEqual(projection.terminal_status, "completed")
            exported_path = application.export_trace_log(
                result.trace_id,
                output_path=path.parent / "manual-export.log",
            )
            self.assertEqual(exported_path, (path.parent / "manual-export.log").resolve())
            exported_text = exported_path.read_text(encoding="utf-8")
            self.assertIn("event_count:", exported_text)
            self.assertIn("Trace Summary", exported_text)
            self.assertIn("EXECUTION TRANSCRIPT", exported_text)
            self.assertIn("[FINAL ANSWER]", exported_text)
            self.assertNotIn("RAW TRACE EVENTS", exported_text)
            self.assertTrue(exported_text.rstrip().endswith("Trace smoke answer"))
            raw_path = application.export_trace_log(
                result.trace_id,
                output_path=path.parent / "manual-export.raw.log",
                view="raw",
            )
            raw_text = raw_path.read_text(encoding="utf-8")
            self.assertIn("RAW TRACE EVENTS", raw_text)
            self.assertIn("operation: answer.finalization.completed", raw_text)
            answer_event = next(
                item for item in projection.timeline if item.operation == "answer.finalization.completed"
            )
            self.assertEqual(answer_event.payload["answer_text"], "Trace smoke answer")
            application.close()

            reopened = create_application(path, agent_runtime=_CompletedRuntime())
            replayed = reopened.read_trace(result.trace_id)
            self.assertEqual(replayed.terminal_status, "completed")
            self.assertEqual(replayed.timeline, projection.timeline)
            reopened.close()

    def test_runtime_event_mapper_drops_delta_and_keeps_model_context(self) -> None:
        """RuntimeEvent mapper 不永久保存 token delta，但保留 model-visible boundary。"""

        with tempfile.TemporaryDirectory() as directory:
            application = create_application(
                Path(directory) / "stream.sqlite3",
                agent_runtime=_StreamingRuntime(),
            )
            result = asyncio.run(application.query(QueryRequest("stream", ExecutionScope())))
            projection = application.read_trace(result.trace_id)
            operations = [item.operation for item in projection.timeline]
            self.assertNotIn("runtime.content_delta", operations)
            turn = next(item for item in projection.timeline if item.operation == "model.turn")
            self.assertEqual(turn.payload["model_visible_context"][0]["role"], "system")
            model_output = next(item for item in projection.timeline if item.operation == "model.output")
            self.assertEqual(model_output.payload["observable_output"][0]["type"], "function_call")
            self.assertEqual(projection.metrics.usage["total_tokens"], 7)
            self.assertEqual(projection.terminal_status, "completed")
            application.close()

    def test_runtime_stream_closes_when_live_observer_fails(self) -> None:
        """observer 抛错时先关闭底层 async generator，避免 event loop shutdown 二次异常。"""

        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteTraceStore(Path(directory) / "stream-close.sqlite3")
            collector = TraceCollector(
                store,
                trace_id="trace-stream-close",
                request_id="request-stream-close",
            )
            runtime = _ClosableRuntime()

            def fail_observer(event: RuntimeEvent) -> None:
                raise RuntimeError("live observer failed")

            traced = TraceableAgentRuntime(
                runtime,
                collector,
                runtime_event_observer=fail_observer,
            )
            try:
                with self.assertRaises(RuntimeError):
                    asyncio.run(
                        traced.run(
                            AgentRunRequest(
                                "close the stream",
                                ExecutionScope(),
                            )
                        )
                    )
                self.assertTrue(runtime.closed)
            finally:
                store.close()

    def test_runtime_failure_is_attributed_and_not_committed(self) -> None:
        """Runtime failure 产生 failed terminal，Conversation 不写 assistant。"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "failed.sqlite3"
            application = create_application(path, agent_runtime=_FailedRuntime())
            result = asyncio.run(application.query(QueryRequest("fail", ExecutionScope())))
            self.assertFalse(result.is_successful)
            projection = application.read_trace(result.trace_id)
            self.assertEqual(projection.terminal_status, "failed")
            self.assertTrue(any(item.failure.error_code == "RUNTIME_TEST_FAILURE" for item in projection.failures))
            self.assertEqual(len(application.read_conversation(result.conversation_id).messages), 0)
            application.close()

    def test_router_degradation_and_planner_failure_keep_ownership(self) -> None:
        """Router degraded 与 Planner fallback 可观测，但不阻断标准 Runtime。"""

        with tempfile.TemporaryDirectory() as directory:
            application = create_application(
                Path(directory) / "degraded-query.sqlite3",
                agent_runtime=_CompletedRuntime(),
                router=_DegradedRouter(),
                planner=_FailedPlanner(),
            )
            result = asyncio.run(application.query(QueryRequest("planned", ExecutionScope())))
            projection = application.read_trace(result.trace_id)
            failures = {failure.failure.error_code: failure.failure for failure in projection.failures}
            self.assertIn("ROUTER_TEST_DEGRADED", failures)
            self.assertIn("PLANNER_TIMEOUT", failures)
            self.assertEqual(failures["PLANNER_TIMEOUT"].handling, "executed_without_plan")
            self.assertEqual(projection.terminal_status, "completed")
            self.assertTrue(result.is_successful)
            application.close()

    def test_trace_store_failure_does_not_control_business(self) -> None:
        """Trace Store failure 有 TRACE log，但成功 Query 仍返回业务结果。"""

        with tempfile.TemporaryDirectory() as directory, self.assertLogs(
            "trivae.observability.collector", level=logging.ERROR
        ) as captured:
            application = create_application(
                Path(directory) / "degraded.sqlite3",
                agent_runtime=_CompletedRuntime(),
                trace_store=_BrokenTraceStore(),
            )
            result = asyncio.run(application.query(QueryRequest("continue", ExecutionScope())))
            self.assertTrue(result.is_successful)
            self.assertTrue(any("TRACE." in message for message in captured.output))
            application.close()

    def test_conversation_commit_failure_has_trace_without_query_completed(self) -> None:
        """Conversation failure 显式上抛，Trace 只有 commit.failed/query.failed。"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commit-failure.sqlite3"
            failing_store = _FailingConversationStore(path)
            application = create_application(
                path,
                agent_runtime=_CompletedRuntime(),
                conversation_store=failing_store,
            )
            with self.assertRaises(RuntimeError) as raised:
                asyncio.run(application.query(QueryRequest("commit failure", ExecutionScope())))
            trace_id = getattr(raised.exception, "trace_id")
            projection = application.read_trace(trace_id)
            operations = [item.operation for item in projection.timeline]
            self.assertIn("answer.commit.failed", operations)
            self.assertIn("query.failed", operations)
            self.assertNotIn("query.completed", operations)
            self.assertEqual(projection.terminal_status, "failed")
            application.close()

    def test_tool_retrieval_parent_child_and_import_projection(self) -> None:
        """Tool→Retrieval operation 因果和现有 Import diagnostics projection 可读。"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "facts.sqlite3"
            application = create_application(path)
            application.store.begin()
            batch_id = application.store.create_batch("chat.json", None, None)
            application.store.record_error(
                batch_id=batch_id,
                source_id=None,
                record_index=3,
                error_code="INVALID_RECORD",
                error_message="record is invalid",
                raw_locator="chat.json#messages[3]",
            )
            application.store.finish_batch(
                batch_id=batch_id,
                received_count=4,
                inserted_count=3,
                duplicate_count=0,
                conflict_count=0,
                error_count=1,
                status="partial",
                error_message="one invalid record",
            )
            application.store.commit()
            application.rebuild_lexical_index()

            collector = TraceCollector(
                application._trace_store,
                trace_id="trace-tool",
                request_id="request-tool",
            )
            context = collector.operation_context("query")
            envelope = application.capability_registry.invoke(
                "search_messages",
                SearchMessagesInput(keyword="missing", limit=1),
                ExecutionScope(max_results=1),
                trace_context=context.child("tool:tool-1"),
            )
            self.assertEqual(envelope.status, "ok")
            projection = project_trace(application._trace_store.read_trace("trace-tool"))
            tool_events = [item for item in projection.timeline if item.stage == "tool"]
            retrieval_events = [item for item in projection.timeline if item.stage == "retrieval"]
            self.assertTrue(tool_events)
            self.assertTrue(retrieval_events)
            self.assertEqual(retrieval_events[0].parent_operation_id, tool_events[0].operation_id)

            diagnostics = application.read_import_diagnostics(batch_id=batch_id)
            self.assertEqual(len(diagnostics.batches), 1)
            self.assertEqual(diagnostics.batches[0].status, "partial")
            self.assertEqual(diagnostics.batches[0].errors[0].record_index, 3)
            application.close()


if __name__ == "__main__":
    unittest.main()
