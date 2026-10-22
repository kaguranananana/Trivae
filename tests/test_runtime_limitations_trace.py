"""Runtime 的 canonical ToolResult 限制必须进入同一 Trace 事件，不能仅留在 Artifact。"""
from __future__ import annotations

import asyncio

import pytest

from trivae.capabilities import ExecutionScope
from trivae.observability.collector import TraceableAgentRuntime, TraceCollector
from trivae.observability.projection import project_trace
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.evidence import ToolResultRecord
from trivae.query.runtime.contracts import AgentRunRequest, RuntimeEvent, RuntimeResult, RuntimeToolCall


@pytest.mark.parametrize("status,limitations", [
    ("ok", ("coverage:partial", "unexpanded_forward_content")),
    ("error", ("tool_error:TOOL_RESULT_BUDGET_EXHAUSTED",)),
])
def test_runtime_tool_completion_preserves_canonical_limitations(tmp_path, status, limitations):
    """复现真实 Case 的遗漏，也覆盖此前预算退出新增的错误结果。"""
    record = ToolResultRecord(
        run_id="run", tool_call_id="run/tool-call/1", tool_result_id="run/tool-call/1/result",
        tool_name="lexical_search", status=status, scope_snapshot={}, query_scope_snapshot={},
        limitations=limitations,
    )
    call = RuntimeToolCall("lexical_search", status, tool_call_id=record.tool_call_id, round=1,
                           tool_result_id=record.tool_result_id)

    class Runtime:
        async def stream(self, request):
            yield RuntimeEvent("tool_completed", "fixture", "fixture", 1, tool_call=call,
                               tool_call_id=call.tool_call_id, tool_result=record, tool_round=1, run_id="run")
            result = RuntimeResult("answer", "fixture", "fixture", "completed", (call,),
                                   tool_rounds=1, run_id="run", tool_results=(record,))
            yield RuntimeEvent("completed", "fixture", "fixture", 2, result=result, run_id="run")

    store = SQLiteTraceStore(tmp_path / "trace.sqlite3")
    collector = TraceCollector(store, trace_id="trace", request_id="request")
    runtime = TraceableAgentRuntime(Runtime(), collector)
    asyncio.run(runtime.run(AgentRunRequest("question", ExecutionScope())))
    trace = project_trace(store.read_trace("trace"))
    event = next(item for item in trace.timeline if item.operation == "runtime.tool.completed")
    assert event.limitations == limitations
    assert set(limitations) <= {value for item in trace.timeline for value in item.limitations}
    store.close()
