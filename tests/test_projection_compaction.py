"""投影精简必须保留原有消息事实，非默认值不能被公共声明覆盖。"""

from __future__ import annotations

from dataclasses import replace

from scripts.audit_projection_compaction import legacy_projection, restored_messages
from tests.test_tool_result_budget import _message
from trivae.capabilities import ExecutionScope, ToolEnvelope
from trivae.query.evidence import build_tool_result_record, project_tool_result_for_model
from trivae.retrieval.structured import Coverage, LexicalQuery, MessageHit, RetrievalMetadata, RetrievalResult


def test_compaction_preserves_all_message_facts_and_reduces_overhead():
    """正文、时间、作者、URL和特殊类型可无损恢复，引用身份及数量不变。"""
    messages = tuple(_message(index, "长正文" * 300 if index == 0 else "项目反馈的完整正文") for index in range(30))
    messages = (*messages, replace(_message(31, "图片资料 https://example.test/figure"), message_type="image"))
    data = RetrievalResult(query=LexicalQuery(keyword="项目", limit=100, context_before=0, context_after=0),
        filters={}, strategy="lexical", hits=tuple(MessageHit(message, ("项目",), 1.0, "test") for message in messages),
        expanded_messages=(), total_hits=len(messages), returned_messages=len(messages),
        coverage=Coverage("complete", "canonical_plus_lexical_index"), partial=False, truncated=False,
        metadata=RetrievalMetadata(filters={}, ordering="test", latency_ms=0))
    envelope = ToolEnvelope("ok", data, {}, None)
    record = build_tool_result_record(run_id="run", tool_call_id="run/tool-call/1", tool_result_id="result",
                                      tool_name="lexical_search", envelope=envelope, scope=ExecutionScope())
    with legacy_projection():
        baseline = project_tool_result_for_model(envelope, record)
    candidate = project_tool_result_for_model(envelope, record)
    assert restored_messages(candidate) == restored_messages(baseline)
    assert candidate["model_projection"]["estimated_tokens"] < baseline["model_projection"]["estimated_tokens"]
    last = candidate["data"]["hits"][-1]["message"]
    assert last["message_type"] == "image"
    assert last["urls"] == ("https://example.test/figure",)
    assert candidate["data"]["hits"][0]["message"]["content_truncated"] is True
    assert candidate["provenance"] == baseline["provenance"]
    assert record.message_items[-1].message.message_type == "image"
