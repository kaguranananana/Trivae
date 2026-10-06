"""小型 synthetic ground truth 验证证据送达；不替代真实 Prompt 语义评测。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call
from agents.tool_context import ToolContext

from tests.test_ingestion import make_message, write_export
from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecutionScope, GetMessageContextInput, SearchMessagesInput
from trivae.query.contracts import ExecutionOverride, QueryRequest
from trivae.query.runtime.contracts import RuntimeContext
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter
from trivae.query.runtime.openai_tools import GetMessageContextSDKToolAdapter, LexicalSearchSDKToolAdapter

FIXTURE_PATH = Path(__file__).parent / "fixtures/prompt/discussion.json"


@pytest.fixture
def discussion_app(tmp_path):
    """fixture 走正式 importer、canonical DB、lexical index，不手写检索结果。"""
    document = json.loads(FIXTURE_PATH.read_text())
    raw = tmp_path / "raw"
    raw.mkdir()
    messages = []
    for index, item in enumerate(document["messages"], start=1):
        # 确定作者身份，防止测试把邻近作者当作推荐者。
        message = make_message(item["id"], index, item["timestamp"], item["text"], sender_uid=item["author"])
        message["sender"]["name"] = item["author"]
        messages.append(message)
    write_export(raw, "discussion(100).json", messages, chat_name="Synthetic Discussion", peer_uid=None, version="5.5.64")
    application = create_application(tmp_path / "discussion.sqlite3")
    application.import_directory(raw)
    application.rebuild_lexical_index()
    try:
        yield application
    finally:
        application.close()


@pytest.mark.parametrize("after,expected,absent", [
    (8, set(), {"M12", "M13", "M33"}),
    (20, {"M12", "M13"}, {"M33"}),
    (40, {"M12", "M13", "M33"}, set()),
])
def test_discussion_window_delivers_ground_truth_through_real_sdk_projection(discussion_app, after, expected, absent):
    """窗口验证同时检查 canonical 与实际模型投影，避免只验证 DB 有推荐。"""
    app = discussion_app
    scope = ExecutionScope(allowed_session_ids=("qq:100",), max_results=100)
    canonical = app.invoke_tool("get_message_context", GetMessageContextInput("qq:100:M1", 0, after), scope)
    ids = {message.source_message_id for message in canonical.data.messages}
    assert expected <= ids
    assert not absent & ids

    async def check():
        context = RuntimeContext(scope=scope, capability_registry=app.capability_registry,
                                 available_capabilities=("lexical_search", "get_message_context"), run_id="synthetic")
        wrapper = ToolContext(context=context, tool_name="lexical_search", tool_call_id="anchor", tool_arguments="{}")
        search = LexicalSearchSDKToolAdapter(app.capability_registry).as_sdk_tool(trusted_max_results=100)
        context.allocate_tool_call_id("anchor")
        await search.on_invoke_tool(wrapper, json.dumps({"keyword": "Agent 后训练", "limit": 100,
                                                       "context_before": 0, "context_after": 0}))
        wrapper.tool_name = "get_message_context"
        wrapper.tool_call_id = "context"
        context.allocate_tool_call_id("context")
        tool = GetMessageContextSDKToolAdapter(app.capability_registry).as_sdk_tool()
        visible = await tool.on_invoke_tool(wrapper, json.dumps({"source_id": "m1-1", "context_before": 0,
                                                                "context_after": after}))
        body = json.dumps(visible, ensure_ascii=False)
        assert ("Build a LLM from Scratch" in body) == ("M12" in expected)
        assert ("PyTorch" in body) == ("M33" in expected)
        if "M12" in expected:
            assert "用户A" in body and "用户B" in body
    asyncio.run(check())


@pytest.mark.parametrize("case_id", ["exact-fact", "resource-inventory", "no-result"])
def test_small_exact_inventory_and_no_result_ground_truth(discussion_app, case_id):
    """使用相同小快照覆盖精确事实、URL inventory 与空检索。"""
    case = next(item for item in json.loads(FIXTURE_PATH.read_text())["cases"] if item["id"] == case_id)
    envelope = discussion_app.invoke_tool("lexical_search", SearchMessagesInput(
        keyword=case["keyword"], limit=100, context_before=0, context_after=0), ExecutionScope(max_results=100))
    assert envelope.status == "ok"
    assert [hit.message.source_message_id for hit in envelope.data.hits] == case["direct_hits"]
    assert not envelope.data.partial
    if case_id == "exact-fact":
        assert envelope.data.hits[0].message.sender_name == case["author"]


def test_temporal_fixture_has_next_day_relation(discussion_app):
    """真实 canonical timestamp 跨日；相邻顺序不能被说成同日。"""
    scope = ExecutionScope(max_results=100)
    early = discussion_app.invoke_tool("get_message_context", GetMessageContextInput("qq:100:M35", 0, 0), scope).data.messages[0]
    late = discussion_app.invoke_tool("get_message_context", GetMessageContextInput("qq:100:M38", 0, 0), scope).data.messages[0]
    assert early.timestamp < late.timestamp
    assert early.timestamp // 86_400_000 != late.timestamp // 86_400_000


def test_small_window_cannot_pass_as_no_result_in_production_finalizer(discussion_app):
    """找到提问但没展开推荐时，有消息证据必须拒绝 no_result；不伪造负面证明。"""
    app = discussion_app
    model = ScriptedModel([
        ModelStep(output=[function_call("lexical_search", {"keyword": "Agent 后训练", "limit": 100,
                          "context_before": 0, "context_after": 0}, call_id="anchor")]),
        ModelStep(output=[function_call("get_message_context", {"source_id": "m1-1",
                          "context_before": 0, "context_after": 8}, call_id="context")]),
        ModelStep(output=[assistant_message(json.dumps({"kind": "no_result", "summary": "没有推荐。", "limitations": []}))]),
    ])
    runtime = OpenAIAgentsRuntimeAdapter(app.capability_registry, model=model)
    app._agent_runtime = runtime
    async def check():
        result = await app.query(QueryRequest("Agent后训练有教程推荐吗？", ExecutionScope(max_results=100),
            available_capabilities=("lexical_search", "get_message_context"), trace_profile="debug",
            execution_override=ExecutionOverride(forced_route="standard_execution")))
        assert result.runtime_result.termination == "completed"
        assert not result.is_successful
        assert result.finalization_status == "failed"
        assert result.finalization_error is not None
    asyncio.run(check())
