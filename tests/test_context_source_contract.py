"""Frozen Plan 4/4 参数失败的 provider-free 生产 SDK 回归。"""

from __future__ import annotations

import asyncio
import json

from agents.tool_context import ToolContext

from tests import test_stage_b_tools as fixtures
from trivae.capabilities import ExecutionScope
from trivae.observability.collector import TraceCollector
from trivae.query.runtime.contracts import RuntimeContext
from trivae.query.runtime.openai_tools import GetMessageContextSDKToolAdapter, LexicalSearchSDKToolAdapter
from trivae.query.runtime.prompt import SYSTEM_PROMPT


def test_generated_context_schema_explains_both_identities():
    """检查实际 SDK/Pydantic schema，而不是独立手写的示例。"""
    fixture = fixtures.StageBToolsTests()
    fixture.setUp()
    try:
        tool = GetMessageContextSDKToolAdapter(fixture.application.capability_registry).as_sdk_tool()
        fields = tool.params_json_schema["properties"]
        assert list(fields)[:2] == ["source_id", "message_id"]
        assert "run-local" in fields["source_id"]["description"]
        assert "mN-K" in fields["source_id"]["description"]
        assert "m1-1" in fields["source_id"]["description"]
        assert "canonical internal message ID" in fields["message_id"]["description"]
        assert "Do not put" in fields["message_id"]["description"]
        assert "mN-K" in tool.description
        assert 'source_id="m1-1"' in SYSTEM_PROMPT
        assert "canonical internal message ID" in SYSTEM_PROMPT
    finally:
        fixture.tearDown()


def test_projection_resolution_canonical_and_wrong_parameter_remain_distinct():
    """同一真实 ToolResult：handle 成功、canonical 成功、错误字段显式 MESSAGE_NOT_FOUND。"""
    fixture = fixtures.StageBToolsTests()
    fixture.setUp()
    try:
        fixture.application.rebuild_lexical_index()
        registry = fixture.application.capability_registry
        collector = TraceCollector(fixture.application._trace_store, trace_id="context-contract", request_id="request")
        context = RuntimeContext(scope=ExecutionScope(max_results=10), capability_registry=registry,
            available_capabilities=("lexical_search", "get_message_context"), run_id="source-contract",
            trace_context=collector.operation_context("runtime"))
        wrapper = ToolContext(context=context, tool_name="lexical_search", tool_call_id="search", tool_arguments="{}")
        search = LexicalSearchSDKToolAdapter(registry).as_sdk_tool(trusted_max_results=10)
        tool = GetMessageContextSDKToolAdapter(registry).as_sdk_tool()

        async def check():
            # 搜索投影只公开 source handle；resolver 的 canonical identity 留在 Host。
            context.allocate_tool_call_id("search")
            projection = await search.on_invoke_tool(wrapper,
                json.dumps({"keyword": "anchor context", "limit": 10, "context_before": 0, "context_after": 0}))
            assert projection["provenance"]["message_sources"][0]["source_id"] == "m1-1"
            assert context.resolve_message_source_handle("m1-1") == "qq:100:a2"
            provider_arguments = [{"source_id": "m1-1"}, {"message_id": "qq:100:a2"}, {"message_id": "m1-1"}]
            results = []
            for index, arguments in enumerate(provider_arguments):
                context.allocate_tool_call_id(f"context-{index}")
                wrapper.tool_name = "get_message_context"
                wrapper.tool_call_id = f"context-{index}"
                wrapper.tool_arguments = json.dumps(arguments)
                results.append(await tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
            assert [r["status"] for r in results] == ["ok", "ok", "error"]
            assert results[-1]["error"]["code"] == "MESSAGE_NOT_FOUND"
            # 原始 arguments 保持 source_id；capability Trace 必须使用解析后的 canonical 参数。
            assert provider_arguments[0] == {"source_id": "m1-1"}
            events = fixture.application._trace_store.read_trace("context-contract").events
            starts = [e for e in events if e.operation == "tool.call.started" and e.payload.get("tool_name") == "get_message_context"]
            assert len(starts) == 3
            assert starts[0].payload["request"]["message_id"] == "qq:100:a2"
            assert starts[2].payload["request"]["message_id"] == "m1-1"
        asyncio.run(check())
    finally:
        fixture.tearDown()


def test_runtime_observation_keeps_raw_handle_while_capability_trace_uses_canonical():
    """实际 SDK loop 的 model_output 原始参数与 normalized Trace 保持不同 ownership。"""
    from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

    from trivae.query.runtime.contracts import AgentRunRequest
    from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter

    fixture = fixtures.StageBToolsTests()
    fixture.setUp()
    try:
        fixture.application.rebuild_lexical_index()
        collector = TraceCollector(fixture.application._trace_store, trace_id="raw-context-contract", request_id="request")
        model = ScriptedModel([
            ModelStep(output=[function_call("lexical_search", {"keyword": "anchor context", "limit": 10,
                "context_before": 0, "context_after": 0}, call_id="search")]),
            ModelStep(output=[function_call("get_message_context", {"source_id": "m1-1"}, call_id="context")]),
            ModelStep(output=[assistant_message("finished")]),
        ])
        runtime = OpenAIAgentsRuntimeAdapter(fixture.application.capability_registry, model=model, max_turns=4)
        request = AgentRunRequest("检索并扩展", ExecutionScope(max_results=10),
            available_capabilities=("lexical_search", "get_message_context"), request_id="raw-context",
            trace_context=collector.operation_context("runtime"))
        events = []
        async def collect():
            async for event in runtime.stream(request):
                events.append(event)
        asyncio.run(collect())
        result = events[-1].result
        assert result.termination == "completed"
        outputs = [e for e in events if e.type == "model_output"]
        raw = outputs[1].observable_output[0]
        assert raw["name"] == "get_message_context"
        assert json.loads(raw["arguments"]) == {"source_id": "m1-1"}
        stored = fixture.application._trace_store.read_trace("raw-context-contract")
        normalized = next(e for e in stored.events if e.operation == "tool.call.started"
            and e.payload.get("tool_name") == "get_message_context")
        assert normalized.payload["request"]["message_id"] == "qq:100:a2"
        assert "source_id" not in normalized.payload["request"]
    finally:
        fixture.tearDown()
