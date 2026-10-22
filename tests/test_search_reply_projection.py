"""锁定真实遗漏形态：搜索已取得回复，投影不能把它与全部普通邻居一起删除。"""

from dataclasses import replace

from tests.test_tool_result_budget import _message
from trivae.capabilities import ExecutionScope, ToolEnvelope
from trivae.query.evidence import build_tool_result_record, project_tool_result_for_model
from trivae.retrieval.structured import Coverage, LexicalQuery, MessageHit, RetrievalMetadata, RetrievalResult


def search_record(hits, neighbors):
    """保留真实 hit/context 角色，不把回复伪装成关键词命中。"""
    result = RetrievalResult(query=LexicalQuery(keyword="project"), filters={}, strategy="lexical",
        hits=tuple(MessageHit(message, ("project",), 1.0, "test") for message in hits),
        expanded_messages=tuple(neighbors), total_hits=len(hits), returned_messages=len(hits)+len(neighbors),
        coverage=Coverage("complete", "canonical_store"), partial=False, truncated=False,
        metadata=RetrievalMetadata(filters={}, ordering="test", latency_ms=0.0))
    envelope = ToolEnvelope("ok", result, {}, None)
    record = build_tool_result_record(run_id="reply-search", tool_call_id="reply-search/tool-call/1",
        tool_result_id="reply-search/tool-call/1/result", tool_name="lexical_search", envelope=envelope,
        scope=ExecutionScope())
    return envelope, record


def test_search_keeps_direct_reply_before_unrelated_neighbors():
    """回复关联到已命中的原消息，预算不足时先让普通邻居和冗长摘录让位。"""
    hits = [_message(index, "project " + "项目背景说明 " * 160) for index in range(8)]
    reply = replace(_message(20, "实际使用后觉得好用"), reply_to_source_message_id=hits[0].source_message_id)
    neighbors = [reply, *(_message(index, "无关讨论 " * 80) for index in range(21, 33))]
    envelope, record = search_record(hits, neighbors)
    payload = project_tool_result_for_model(envelope, record, token_budget=4_000)
    visible = payload["data"]["expanded_messages"]
    assert any(message["content"] == "实际使用后觉得好用" for message in visible)
    returned_reply = next(message for message in visible if message["content"] == "实际使用后觉得好用")
    assert returned_reply["hit"] is False
    assert returned_reply["reply_to_source_id"] == "m1-1"
    assert payload["model_projection"]["estimated_tokens"] <= 4_000


def test_search_only_omits_as_much_ordinary_context_as_needed():
    """只差一点容量时，不允许整批删除仍能装下的普通上下文。"""
    hits = [_message(0, "project 分享")]
    neighbors = [_message(index, "有用的讨论内容 " * 12) for index in range(1, 11)]
    envelope, record = search_record(hits, neighbors)
    full = project_tool_result_for_model(envelope, record, token_budget=16_000)
    budget = full["model_projection"]["estimated_tokens"] - 100
    payload = project_tool_result_for_model(envelope, record, token_budget=budget)
    assert 0 < len(payload["data"]["expanded_messages"]) < len(neighbors)
    assert payload["model_projection"]["estimated_tokens"] <= budget
