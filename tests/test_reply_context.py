"""用真实导入、SDK 工具和模型投影复现远距离回复丢失。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from unittest.mock import patch

import pytest
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call
from agents.tool_context import ToolContext

from tests.test_forward_retrieval import make_forward_message
from tests.test_ingestion import make_message, write_export
from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecutionScope, GetMessageContextInput, ToolEnvelope
from trivae.query.contracts import ExecutionOverride, QueryRequest
from trivae.query.evidence import build_tool_result_record, project_tool_result_for_model
from trivae.query.runtime.contracts import RuntimeContext
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter
from trivae.query.runtime.openai_tools import GetMessageContextSDKToolAdapter


@pytest.fixture
def reply_application(tmp_path):
    """让简短评价与原分享之间隔着 143 条无关消息。"""
    raw = tmp_path / "raw"
    raw.mkdir()
    messages = [make_message("anchor", 0, 1_000, "分享一个技术项目")]
    messages.extend(make_message(f"noise-{i}", i, 1_000 + i, "无关讨论") for i in range(1, 144))
    messages.append(make_message("reply", 144, 2_000, "实际用过，值得推荐", reply_to="anchor"))
    messages.append(make_message("future", 145, 3_000, "时间范围外回复", reply_to="anchor"))
    # 两个转发容器重复使用平台 ID，关系查找必须按当前 occurrence 的直接容器隔离。
    children = [make_message("anchor", 0, 100, "转发分享"),
        make_message("reply", 1, 200, "转发内部评价", reply_to="anchor"),
        make_forward_message("nested", 250, [make_message("reply", 0, 260, "另一容器回复", reply_to="anchor")])]
    messages.extend([make_forward_message("forward-a", 1_500, children),
        make_forward_message("forward-b", 1_600, children)])
    write_export(raw, "reply(100).json", messages, chat_name="回复实验", peer_uid=None, version="5.5.64")
    write_export(raw, "reply(200).json", [make_message("reply", 0, 2_000, "另一群回复", reply_to="anchor")],
        chat_name="另一群", peer_uid=None, version="5.5.64")
    application = create_application(tmp_path / "reply.sqlite3")
    application.import_directory(raw)
    try:
        yield application
    finally:
        application.close()


def invoke_context(application, *, scope=None, return_context=False, **arguments):
    """经过生产 SDK、Capability 和投影，检查模型实际拿到的消息。"""
    registry = application.capability_registry
    context = RuntimeContext(scope=scope or ExecutionScope(end_timestamp=2_500, max_results=10), capability_registry=registry,
        available_capabilities=("get_message_context",), run_id="reply-test")
    context.allocate_tool_call_id("context")
    wrapper = ToolContext(context=context, tool_name="get_message_context", tool_call_id="context",
        tool_arguments=json.dumps({"message_id": "qq:100:anchor", **arguments}))
    tool = GetMessageContextSDKToolAdapter(registry).as_sdk_tool()
    payload = asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    return (payload, context) if return_context else payload


def test_explicit_reply_context_delivers_distant_reply_to_model(reply_application):
    """关系补查必须找回窗口之外的真实回复，且不带回中间 143 条噪声。"""
    payload = invoke_context(reply_application, context_before=0, context_after=0, include_replies=True)
    assert payload["status"] == "ok"
    contents = [message["content"] for message in payload["data"]["messages"]]
    assert contents == ["分享一个技术项目", "实际用过，值得推荐"]
    assert payload["data"]["messages"][1]["reply_to_source_id"] == payload["data"]["messages"][0]["source_id"]
    assert payload["data"]["metadata"]["details"]["returned_replies"] == 1
    assert payload["data"]["metadata"]["details"]["has_more_replies"] is False


def test_model_projection_preserves_reply_relationship(reply_application):
    """已取回的回复必须在模型输入中明确标识回复对象。"""
    payload = invoke_context(reply_application, message_id="qq:100:reply", context_before=0, context_after=0)
    message = payload["data"]["messages"][0]
    assert message["reply_to_source_message_id"] == "anchor"


def test_default_context_remains_local(reply_application):
    """默认窗口不暗中追加关系查询，显式开关区分两种读取意图。"""
    payload = invoke_context(reply_application, context_before=0, context_after=0)
    assert [message["content"] for message in payload["data"]["messages"]] == ["分享一个技术项目"]


@pytest.mark.parametrize("capacity", [1, 2])
def test_reply_overflow_is_disclosed_and_anchor_retained(reply_application, capacity):
    """总容量同时约束 anchor 和回复，未返回的回复必须显式披露。"""
    payload = invoke_context(reply_application, scope=ExecutionScope(max_results=capacity),
        context_before=0, context_after=0, include_replies=True)
    messages = payload["data"]["messages"]
    assert len(messages) == capacity
    assert messages[0]["content"] == "分享一个技术项目"
    assert payload["data"]["truncated"] is True
    assert payload["data"]["metadata"]["details"]["has_more_replies"] is True


def test_reply_lookup_obeys_half_open_time_scope(reply_application):
    """回复恰好位于结束边界时不能返回；其他群同名回复也不能混入。"""
    payload = invoke_context(reply_application, scope=ExecutionScope(end_timestamp=2_000, max_results=10),
        context_before=0, context_after=0, include_replies=True)
    assert [message["content"] for message in payload["data"]["messages"]] == ["分享一个技术项目"]
    assert payload["data"]["metadata"]["details"]["returned_replies"] == 0


def test_reply_lookup_does_not_cross_forward_container(reply_application):
    """同群、跨转发和嵌套容器中重复的原始 ID 都不构成当前回复边。"""
    payload = invoke_context(reply_application, message_id="qq:100:forward-a#forward:0.0",
        context_before=0, context_after=0, include_replies=True)
    assert [message["content"] for message in payload["data"]["messages"]] == ["转发分享", "转发内部评价"]
    assert all(message["forward"]["root_message_id"] == "qq:100:forward-a"
        for message in payload["data"]["messages"])


def test_missing_source_identity_is_an_explicit_error(reply_application):
    """不能建立回复关系时返回错误，而不是制造零回复的结论。"""
    repository = reply_application.read_repository
    anchor = repository.read_message_by_id("qq:100:anchor")
    with patch.object(repository, "read_message_by_id", return_value=replace(anchor, source_message_id=None)):
        payload = invoke_context(reply_application, include_replies=True)
    assert payload["status"] == "error"
    assert "source_message_id" in payload["error"]["message"]


def test_reply_and_anchor_survive_neighbor_omission_under_token_budget(reply_application):
    """在有容量返回噪声时，投影预算应先省略普通邻居，再省略显式请求的回复。"""
    scope = ExecutionScope(allowed_session_ids=("qq:100",), end_timestamp=2_500, max_results=30)
    envelope = reply_application.invoke_tool("get_message_context",
        GetMessageContextInput("qq:100:anchor", context_before=0, context_after=20, include_replies=True), scope)
    record = build_tool_result_record(run_id="reply-budget", tool_call_id="reply-budget/tool-call/1",
        tool_result_id="reply-budget/tool-call/1/result", tool_name="get_message_context", envelope=envelope, scope=scope)
    payload = project_tool_result_for_model(envelope, record, token_budget=2_000)
    assert payload["model_projection"]["omitted_hit_messages"] > 0
    contents = {message["content"] for message in payload["data"]["messages"]}
    assert {"分享一个技术项目", "实际用过，值得推荐"} <= contents
    assert payload["model_projection"]["estimated_tokens"] <= 2_000


def test_sdk_loop_source_handle_reply_citation_and_trace(reply_application):
    """生产链路贯通搜索 handle、关系补查、最终 Citation 与 Trace 参数。"""
    reply_application.rebuild_lexical_index()
    answer = json.dumps({"claims": [{"text": "有人实际使用并推荐。", "finding": "有人实际使用并推荐。",
        "criterion": "直接回复原分享", "sufficiency": "sufficient", "sources": ["m2-2"], "limitations": []}],
        "limitations": []})
    model = ScriptedModel([
        ModelStep(output=[function_call("lexical_search", {"keyword": "分享一个技术项目", "limit": 1,
            "context_before": 0, "context_after": 0}, call_id="search")]),
        ModelStep(output=[function_call("get_message_context", {"source_id": "m1-1", "context_before": 0,
            "context_after": 0, "include_replies": True}, call_id="context")]),
        ModelStep(output=[assistant_message(answer)]),
    ])
    reply_application._agent_runtime = OpenAIAgentsRuntimeAdapter(reply_application.capability_registry,
        model=model, max_turns=4)
    result = asyncio.run(reply_application.query(QueryRequest("这个项目有没有实际使用反馈？",
        ExecutionScope(allowed_session_ids=("qq:100",), end_timestamp=2_500, max_results=10),
        available_capabilities=("lexical_search", "get_message_context"),
        execution_override=ExecutionOverride(forced_route="standard_execution"))))
    assert result.is_successful, result.finalization_error
    assert len(result.runtime_result.tool_results) == 2
    reference = result.answer_artifact.evidence_items[0].sources[0].reference
    assert reference.internal_message_id == "qq:100:reply"
    trace = reply_application._trace_store.read_trace(result.trace_id)
    starts = [event for event in trace.events if event.operation == "tool.call.started"
        and event.payload.get("tool_name") == "get_message_context"]
    assert starts[0].payload["request"]["include_replies"] is True


def test_source_cap_discloses_unexpanded_hits():
    """没有发生最终列表裁剪时，锚点上限仍必须披露未扩展的来源。"""
    from tests.test_retrieval_budget import _ContextRepository, _message
    from trivae.retrieval.context import ContextExpander
    from trivae.retrieval.structured import MessageHit

    hits = tuple(MessageHit(_message(index), ("inventory",), 1.0, "test") for index in range(30))
    result = ContextExpander(_ContextRepository()).expand(hits, before=1, after=1, limit=100)
    assert result.context_source_hits == 20
    assert result.truncated is True


def test_reply_handle_does_not_point_to_omitted_neighbor():
    """搜索保留回复命中、裁掉原消息时，只能保留原始关系，不能公开悬空 handle。"""
    from tests.test_tool_result_budget import _message
    from trivae.retrieval.structured import Coverage, LexicalQuery, MessageHit, RetrievalMetadata, RetrievalResult

    anchor = replace(_message(0, "分享正文" * 1_000), source_message_id="anchor")
    reply = replace(_message(1, "实际使用反馈"), reply_to_source_message_id="anchor")
    result = RetrievalResult(query=LexicalQuery(keyword="反馈"), filters={}, strategy="lexical",
        hits=(MessageHit(reply, ("反馈",), 1.0, "test"),), expanded_messages=(anchor,), total_hits=1,
        returned_messages=2, coverage=Coverage(status="complete", basis="canonical_store"), partial=False,
        truncated=False, metadata=RetrievalMetadata(filters={}, ordering="test", latency_ms=0.0))
    scope = ExecutionScope()
    envelope = ToolEnvelope("ok", result, {}, None)
    record = build_tool_result_record(run_id="reply-budget", tool_call_id="reply-budget/tool-call/1",
        tool_result_id="reply-budget/tool-call/1/result", tool_name="lexical_search", envelope=envelope, scope=scope)
    full = project_tool_result_for_model(envelope, record, token_budget=16_000)
    assert full["data"]["hits"][0]["message"]["reply_to_source_id"] == "m1-2"
    bounded = project_tool_result_for_model(envelope, record, token_budget=1_100)
    assert bounded["model_projection"]["omitted_context_messages"] == 1
    message = bounded["data"]["hits"][0]["message"]
    assert "reply_to_source_id" not in message
    assert message["reply_to_source_message_id"] == "anchor"
