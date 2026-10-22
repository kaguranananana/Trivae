"""预算失败、SDK 协议闭合及 Collector 中断的确定性回归；不发送真实请求。"""

from __future__ import annotations

import ast
import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from agents.exceptions import UserError
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call
from agents.tool_context import ToolContext
from agents.usage import Usage

from tests.test_tool_result_budget import _dynamic_settings, _message
from trivae.capabilities import CapabilityRegistry, ExecutionScope, ToolEnvelope
from trivae.evaluation.checks import operational_measurements
from trivae.observability.collector import TraceableAgentRuntime, TraceCollector
from trivae.observability.projection import project_trace
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.contracts import QueryResult
from trivae.query.evidence import (
    MODEL_TOKEN_CHAR_RATIO,
    AnswerFinalizationError,
    ToolResultProjectionError,
    build_tool_result_record,
    finalize_answer,
    has_verified_zero_result_evidence,
    project_tool_result_for_model,
)
from trivae.query.router import RouteDecision
from trivae.query.runtime.budget import ToolResultBudgetConfig, ToolResultBudgetExhausted
from trivae.query.runtime.contracts import (
    AgentRunRequest,
    ModelBehaviorError,
    RuntimeContext,
    RuntimeEvent,
    RuntimeResult,
    RuntimeToolCall,
)
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter
from trivae.query.runtime.openai_tools import SearchMessagesSDKToolAdapter
from trivae.query.runtime.usage import aggregate_usage
from trivae.retrieval.structured import Coverage, LexicalQuery, MessageHit, RetrievalMetadata, RetrievalResult


class SearchFixture:
    """第二次返回无法裁剪的元数据，隔离真实失败形态中的结构性开销。"""

    name = "search_messages"

    def __init__(self):
        self.executions = []

    def invoke(self, request, scope):
        self.executions.append(request.keyword)
        if request.keyword == "oversize":
            return ToolEnvelope("ok", None, {"required_metadata": "证据结构" * 4_000}, None)
        message = _message(1, "已核实的证据正文")
        data = RetrievalResult(
            query=LexicalQuery(keyword="evidence", limit=1, context_before=0, context_after=0),
            filters={}, strategy="lexical", hits=(MessageHit(message, ("evidence",), 1.0, "test"),),
            expanded_messages=(), total_hits=1, returned_messages=1,
            coverage=Coverage("complete", "canonical_plus_lexical_index"), partial=False, truncated=False,
            metadata=RetrievalMetadata(filters={}, ordering="test", latency_ms=0.0),
        )
        return ToolEnvelope("ok", data, {}, None)


def _request():
    """工具与可信 scope 固定，不调用 Router/Planner。"""
    return AgentRunRequest("读取证据", ExecutionScope(max_results=5), available_capabilities=("search_messages",))


def test_projection_accounting_includes_its_own_metrics():
    """公开估算必须等于完整 UTF-8 payload 的 byte/ratio，而不是少计 metrics。"""
    envelope = ToolEnvelope("ok", None, {}, None)
    record = build_tool_result_record(run_id="run", tool_call_id="run/tool-call/1",
                                     tool_result_id="run/tool-call/1/result", tool_name="search_messages",
                                     envelope=envelope, scope=ExecutionScope())
    payload = project_tool_result_for_model(envelope, record)
    size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
    assert payload["model_projection"]["estimated_tokens"] == (size + MODEL_TOKEN_CHAR_RATIO - 1) // MODEL_TOKEN_CHAR_RATIO


def test_134_tokens_rejected_before_capability_executes():
    """严格对应旧故障余额：预留虽非零，但不足以返回合法结构。"""
    tool = SearchFixture()
    registry = CapabilityRegistry()
    registry.register(tool)
    policy = ToolResultBudgetConfig().new_policy()
    reservation = policy.begin_call()
    policy.complete_call(reservation, projected_tool_result_tokens=15_866, truncated=False,
                         omitted_context_messages=0, omitted_hit_messages=0)
    context = RuntimeContext(scope=ExecutionScope(), capability_registry=registry,
                             available_capabilities=("search_messages",), tool_result_budget_policy=policy)
    wrapper = ToolContext(context=context, tool_name="search_messages", tool_call_id="call-1",
                          tool_arguments='{"keyword":"evidence"}')
    with pytest.raises(ToolResultBudgetExhausted, match="available 134"):
        asyncio.run(SearchMessagesSDKToolAdapter(registry).as_sdk_tool().on_invoke_tool(
            wrapper, wrapper.tool_arguments))
    assert tool.executions == []
    assert policy.remaining_run_tool_evidence_budget == 134


def test_exact_reservation_limit_and_parallel_release():
    """准入边界允许刚好放下，多个在途预留不会超卖或漏退。"""
    policy = ToolResultBudgetConfig(fallback_run_tool_evidence_budget=600).new_policy()
    first = policy.begin_call(minimum_budget=200, maximum_budget=200)
    second = policy.begin_call(minimum_budget=400)
    with pytest.raises(ToolResultBudgetExhausted):
        policy.begin_call()
    policy.cancel_call(first)
    snapshot = policy.complete_call(second, projected_tool_result_tokens=400, truncated=False,
                                    omitted_context_messages=0, omitted_hit_messages=0)
    assert snapshot.remaining_run_tool_evidence_budget_after_call == 200
    exact = policy.begin_call(minimum_budget=200)
    policy.complete_call(exact, projected_tool_result_tokens=200, truncated=False,
                         omitted_context_messages=0, omitted_hit_messages=0)
    assert policy.remaining_run_tool_evidence_budget == 0


@pytest.mark.parametrize("traced", [False, True])
def test_same_round_budget_stop_closes_all_calls_and_preserves_citations(tmp_path, traced):
    """本轮发生真实投影失败后，后续能力不执行，但每个 Tool Call 都有 SDK 响应。"""
    tool = SearchFixture()
    registry = CapabilityRegistry()
    registry.register(tool)
    final = json.dumps({"claims": [{"text": "已核实的证据正文", "finding": "证据存在",
                                   "criterion": "原消息", "sufficiency": "sufficient",
                                   "sources": ["m1-1"], "limitations": []}], "limitations": []})
    model = ScriptedModel([
        ModelStep(output=[function_call("search_messages", {"keyword": keyword}, call_id=f"call-{index}")
                          for index, keyword in enumerate(("evidence", "oversize", "skip"))]),
        ModelStep(output=[assistant_message(final)]),
    ])
    runtime = OpenAIAgentsRuntimeAdapter(registry, model=model,
                                        settings=replace(_dynamic_settings(), run_tool_evidence_budget=3_000))

    async def run():
        return [event async for event in runtime.stream(_request())]

    if traced:
        store = SQLiteTraceStore(tmp_path / "budget-trace.sqlite3")
        collector = TraceCollector(store, trace_id="budget-trace", request_id="request")
        events = []
        result = asyncio.run(TraceableAgentRuntime(runtime, collector, runtime_event_observer=events.append).run(_request()))
        trace = project_trace(store.read_trace("budget-trace"))
        stops = [item for item in trace.timeline if item.operation == "runtime.tool.budget_stopped"]
        assert [item.payload["capability_executed"] for item in stops] == [True, False]
        assert next(item for item in trace.timeline if item.operation == "runtime.finalizing").limitations == (
            "tool_result_budget_exhausted",)
        store.close()
    else:
        events = asyncio.run(run())
        result = events[-1].result
    assert result.termination == "completed"
    assert result.tool_rounds == 1
    assert tool.executions == ["evidence", "oversize"]
    assert len(result.tool_calls) == len(result.tool_results) == 3
    assert [call.error_code for call in result.tool_calls] == [None, "TOOL_RESULT_BUDGET_EXHAUSTED",
                                                             "TOOL_RESULT_BUDGET_EXHAUSTED"]
    assert [event.type for event in events].count("finalizing") == 1
    assert next(event for event in events if event.type == "finalizing").budget_kind == "tool_result_tokens"
    # SDK 下一轮真实输入必须包含全部三个调用结果，并且不再提供工具。
    assert len(model.calls) == 2
    assert not model.calls[-1].tools
    assert "Tool Result token budget is exhausted" in model.calls[-1].system_instructions
    outputs = [item for item in model.calls[-1].input if item.get("type") == "function_call_output"]
    assert len(outputs) == 3
    failure = ast.literal_eval(outputs[1]["output"])
    assert failure["meta"]["budget_failure_type"] == "ToolResultProjectionError"
    assert not has_verified_zero_result_evidence(result.tool_results[1:])
    with pytest.raises(AnswerFinalizationError, match="verified complete-and-empty"):
        finalize_answer('{"kind":"no_result","summary":"没有结果"}', run_id=result.run_id,
                        tool_results=result.tool_results[1:], scope=_request().scope)
    artifact = finalize_answer(result.final_answer, run_id=result.run_id, tool_results=result.tool_results,
                               scope=_request().scope)
    assert artifact.citation_bindings
    assert artifact.evidence_items[0].sources[0].reference.internal_message_id == _message(1, "").internal_message_id
    assert "tool_error:TOOL_RESULT_BUDGET_EXHAUSTED" in artifact.limitations
    assert sum(call.model_result_estimated_tokens for call in result.tool_calls) <= 3_000
    assert result.tool_calls[-1].tool_result_budget.remaining_run_tool_evidence_budget_after_call == (
        3_000 - sum(call.model_result_estimated_tokens for call in result.tool_calls))


def test_insufficient_whole_batch_fails_before_any_capability():
    """控制结果也装不下时拒绝整轮，禁止发送缺少结果的下一轮模型请求。"""
    tool = SearchFixture()
    registry = CapabilityRegistry()
    registry.register(tool)
    model = ScriptedModel([ModelStep(output=[
        function_call("search_messages", {"keyword": "evidence"}, call_id=f"call-{i}") for i in range(3)
    ], usage=Usage(requests=1, input_tokens=10, output_tokens=5, total_tokens=15))])
    runtime = OpenAIAgentsRuntimeAdapter(registry, model=model,
                                        settings=replace(_dynamic_settings(), run_tool_evidence_budget=300))
    result = asyncio.run(runtime.run(_request()))
    assert result.error.code == "TOOL_RESULT_BUDGET_EXHAUSTED"
    assert tool.executions == []
    assert len(model.calls) == 1
    assert result.usage["input_tokens"] == 10
    assert result.usage["total_tokens"] == 15


@pytest.mark.parametrize("cause,code", [(ToolResultProjectionError("minimum cannot fit"), "TOOL_RESULT_PROJECTION_ERROR"),
                                      (ToolResultBudgetExhausted("pool empty"), "TOOL_RESULT_BUDGET_EXHAUSTED")])
def test_sdk_user_error_retains_budget_cause(monkeypatch, cause, code):
    """真实 SDK 的 UserError 包装形态仍归入 budget，保留包装类型与根因类型。"""
    wrapped = UserError("SDK tool failed")
    wrapped.__cause__ = cause

    def fail(*args, **kwargs):
        raise wrapped

    monkeypatch.setattr("trivae.query.runtime.openai_adapter.Runner.run_streamed", fail)
    registry = CapabilityRegistry()
    registry.register(SearchFixture())
    runtime = OpenAIAgentsRuntimeAdapter(registry, model=ScriptedModel([]), settings=_dynamic_settings())
    result = asyncio.run(runtime.run(_request()))
    assert result.error.code == code
    assert result.error.category == "budget"
    assert result.error.exception_type == "UserError"
    assert result.error.diagnostic_type == type(cause).__name__


def test_usage_aggregate_preserves_unknown_fields():
    """某响应/字段未知时保留已知下界，不把 unknown 当零加入总量。"""
    assert aggregate_usage([{"input_tokens": 10}, {"input_tokens": 20}]) == {"input_tokens": 30}
    assert aggregate_usage([{"input_tokens": 10}, None]) == {
        "known_input_tokens": 10, "responses_without_usage": 1}
    assert aggregate_usage([{"input_tokens": 10, "output_tokens": 2}, {"input_tokens": 20}]) == {
        "input_tokens": 30, "known_output_tokens": 2}
    assert aggregate_usage([None, None]) is None
    raw = SimpleNamespace(raw_responses=[SimpleNamespace(usage={"input_tokens": 10}), SimpleNamespace(usage=None)])
    assert OpenAIAgentsRuntimeAdapter._project_usage(raw)["known_input_tokens"] == 10


@pytest.mark.parametrize("interrupted", [False, True])
@pytest.mark.parametrize("missing", [False, True])
def test_collector_counts_completed_tools_and_aggregates_usage(tmp_path, interrupted, missing):
    """真实两工具轮、同轮两调用、最终综合第三模型轮；同时覆盖中断与缺失 Usage。"""
    calls = tuple(RuntimeToolCall("search_messages", "ok", tool_call_id=f"tool-{i}", round=round_number)
                  for i, round_number in enumerate((1, 1, 2)))
    usage = aggregate_usage([{"input_tokens": 10}, None if missing else {"input_tokens": 20},
                             None if interrupted else {"input_tokens": 30}])

    class Runtime:
        async def stream(self, request):
            sequence = 0
            for model_round in (1, 2, 3):
                sequence += 1
                yield RuntimeEvent("turn_started", "test", "fixture", sequence, tool_round=model_round, run_id="run")
                if model_round == 3 and interrupted:
                    sequence += 1
                    yield RuntimeEvent("content_delta", "test", "fixture", sequence, text="bad JSON", run_id="run")
                sequence += 1
                yield RuntimeEvent("model_output", "test", "fixture", sequence, tool_round=model_round, run_id="run")
                if not (model_round == 2 and missing):
                    sequence += 1
                    yield RuntimeEvent("usage_update", "test", "fixture", sequence,
                                       usage={"input_tokens": model_round * 10}, run_id="run")
                for call in calls:
                    if call.round == model_round:
                        sequence += 1
                        yield RuntimeEvent("tool_completed", "test", "fixture", sequence,
                                           tool_round=model_round, tool_call=call, run_id="run")
            result = RuntimeResult("answer", "test", "fixture", "completed", calls, usage=usage,
                                   tool_rounds=2, run_id="run")
            yield RuntimeEvent("completed", "test", "fixture", sequence + 1, result=result, run_id="run")

    def observe(event):
        if event.type == "content_delta":
            raise ModelBehaviorError("parser interrupted")

    store = SQLiteTraceStore(tmp_path / "trace.sqlite3")
    collector = TraceCollector(store, trace_id="trace", request_id="request")
    result = asyncio.run(TraceableAgentRuntime(Runtime(), collector, runtime_event_observer=observe).run(_request()))
    assert result.tool_rounds == 2
    assert len(result.tool_calls) == 3
    assert result.usage == usage
    trace = project_trace(store.read_trace("trace"))
    assert trace.metrics.usage == usage
    query = QueryResult(runtime_result=result, route_decision=RouteDecision("standard_execution", 1.0, "rule", "test"))
    measurements = operational_measurements(query, trace)
    assert measurements["usage"] == result.usage
    assert measurements["tool_rounds"] == 2
    store.close()


def test_control_only_batch_skips_all_capabilities_and_cannot_claim_zero_results():
    """预算只能返回控制结构时完全不检索，缺少证据的 no_result 不能通过 Finalizer。"""
    tool = SearchFixture()
    registry = CapabilityRegistry()
    registry.register(tool)
    model = ScriptedModel([
        ModelStep(output=[function_call("search_messages", {"keyword": "evidence"}, call_id=f"call-{i}")
                          for i in range(3)]),
        ModelStep(output=[assistant_message('{"kind":"no_result","summary":"没有结果"}')]),
    ])
    runtime = OpenAIAgentsRuntimeAdapter(registry, model=model,
                                        settings=replace(_dynamic_settings(), run_tool_evidence_budget=600))
    result = asyncio.run(runtime.run(_request()))
    assert result.termination == "completed"
    assert tool.executions == []
    assert len(result.tool_results) == 3
    assert all(call.error_code == "TOOL_RESULT_BUDGET_EXHAUSTED" for call in result.tool_calls)
    with pytest.raises(AnswerFinalizationError, match="verified complete-and-empty"):
        finalize_answer(result.final_answer, run_id=result.run_id, tool_results=result.tool_results, scope=_request().scope)


def test_observer_failure_at_terminal_uses_authoritative_usage_once(tmp_path):
    """observer 在终态出错也保留底层累计用量，不再把 per-response usage 加第二遍。"""
    class Runtime:
        async def stream(self, request):
            yield RuntimeEvent("turn_started", "test", "fixture", 1, tool_round=3, run_id="run")
            yield RuntimeEvent("usage_update", "test", "fixture", 2, usage={"input_tokens": 30}, run_id="run")
            result = RuntimeResult("answer", "test", "fixture", "completed", (),
                                   usage={"input_tokens": 60}, tool_rounds=2, run_id="run")
            yield RuntimeEvent("completed", "test", "fixture", 3, result=result, run_id="run")

    def observe(event):
        if event.type == "completed":
            raise ModelBehaviorError("terminal observer interrupted")

    store = SQLiteTraceStore(tmp_path / "terminal.sqlite3")
    collector = TraceCollector(store, trace_id="trace", request_id="request")
    result = asyncio.run(TraceableAgentRuntime(Runtime(), collector, runtime_event_observer=observe).run(_request()))
    assert result.usage == {"input_tokens": 60}
    assert result.tool_rounds == 2
    assert project_trace(store.read_trace("trace")).metrics.usage == {"input_tokens": 60}
    store.close()


def test_sdk_incomplete_response_preserves_known_usage_lower_bound():
    """SDK 第二响应未完成时，第一响应的用量仍保留，但不冒充整个 Run 总量。"""
    registry = CapabilityRegistry()
    registry.register(SearchFixture())
    model = ScriptedModel([
        ModelStep(output=[function_call("search_messages", {"keyword": "evidence"}, call_id="call-1")],
                  usage=Usage(requests=1, input_tokens=10, output_tokens=5, total_tokens=15)),
        ModelStep(error=RuntimeError("explicit interrupted response")),
    ])
    runtime = OpenAIAgentsRuntimeAdapter(registry, model=model, settings=_dynamic_settings())
    result = asyncio.run(runtime.run(_request()))
    assert result.termination == "failed"
    assert result.usage["known_input_tokens"] == 10
    assert result.usage["known_output_tokens"] == 5
    assert result.usage["responses_without_usage"] == 1
    assert "input_tokens" not in result.usage
    assert result.tool_rounds == 1
