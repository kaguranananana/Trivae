"""真实SDK回归：长消息要能读到尾部，并让引用仍对应读取过的原文段。"""

from __future__ import annotations

import asyncio
import json

from agents.tool_context import ToolContext

from tests.test_ingestion import make_message, write_export
from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecutionScope, GetMessageContextInput
from trivae.conversation.serialization import deserialize_answer_artifact, serialize_answer_artifact
from trivae.query.evidence import build_tool_result_record, finalize_answer, project_tool_result_for_model
from trivae.query.runtime.contracts import RuntimeContext
from trivae.query.runtime.openai_tools import GetMessageContextSDKToolAdapter


def application_with_text(tmp_path, text):
    """走正式导入和Canonical读取，不用手写检索投影替代主链路。"""
    raw = tmp_path / "raw"
    raw.mkdir()
    write_export(raw, "long(100).json", [make_message("long", 1, 1000, text)],
                 chat_name="长消息实验", peer_uid=None, version="5.5.64")
    app = create_application(tmp_path / "long.sqlite3")
    app.import_directory(raw)
    return app


async def read_page(app, context, **arguments):
    """每页仍使用同一运行账本与来源解析，禁止逐页重置预算。"""
    call_id = f"read-{len(context.tool_results) + 1}"
    context.allocate_tool_call_id(call_id)
    wrapper = ToolContext(context=context, tool_name="get_message_context", tool_call_id=call_id,
                          tool_arguments="{}")
    tool = GetMessageContextSDKToolAdapter(app.capability_registry).as_sdk_tool()
    return await tool.on_invoke_tool(wrapper, json.dumps({"message_id": "qq:100:long",
        "context_before": 0, "context_after": 0, **arguments}))


def test_explicit_read_recovers_useful_tail_after_1000_characters(tmp_path):
    """复现1103字面经：有用问题在原1000字引用摘录之外。"""
    text = "前面是项目背景和面试官提问。" * 90 + "\n最后的提问：岗位偏全栈还是前端？目前有哪些强需求？"
    app = application_with_text(tmp_path, text)
    try:
        context = RuntimeContext(scope=ExecutionScope(max_results=10), capability_registry=app.capability_registry,
                                 available_capabilities=("get_message_context",), run_id="full-anchor")
        payload = asyncio.run(read_page(app, context))
        message = payload["data"]["messages"][0]
        assert message["content"] == text
        assert not message.get("content_truncated", False)
        assert message["next_content_offset"] is None
    finally:
        app.close()


def test_content_pages_reassemble_exact_text_and_persist_tail_citation(tmp_path):
    """连续分页不能重复或跳过字符；尾页引用摘录不能又变回原消息开头。"""
    text = "不同问题要看上下文。\n" * 770 + "尾部唯一建议：确认未来三个月的交付目标。"
    app = application_with_text(tmp_path, text)
    try:
        context = RuntimeContext(scope=ExecutionScope(max_results=10), capability_registry=app.capability_registry,
                                 available_capabilities=("get_message_context",), run_id="pages")

        async def check():
            offset = 0
            parts = []
            while True:
                payload = await read_page(app, context, content_offset=offset, content_limit=8000)
                message = payload["data"]["messages"][0]
                assert message["content_offset"] == offset
                assert message["content_total_chars"] == len(text)
                parts.append(message["content"])
                next_offset = message["next_content_offset"]
                if next_offset is None:
                    assert "".join(parts) == text
                    return message
                assert next_offset > offset
                offset = next_offset

        tail = asyncio.run(check())
        assert "".join(context.tool_results[i].message_items[0].message.normalized_content
                       for i in range(len(context.tool_results))) == text
        candidate = json.dumps({"claims": [{"text": "确认未来三个月的交付目标。", "finding": "交付目标",
            "criterion": "原文尾段明确列出", "sufficiency": "sufficient", "sources": [tail["source_id"]],
            "limitations": []}], "limitations": []})
        artifact = finalize_answer(candidate, run_id=context.run_id, tool_results=tuple(context.tool_results),
                                   scope=context.scope)
        snapshot = artifact.evidence_items[0].sources[0].reference.snapshot
        assert "尾部唯一建议" in snapshot.excerpt
        assert snapshot.excerpt_offset == tail["content_offset"]
        restored = deserialize_answer_artifact(serialize_answer_artifact(artifact))
        assert restored == artifact
    finally:
        app.close()


def test_budget_shortening_continues_at_actual_visible_end(tmp_path):
    """当页抓取成功但投影被预算压缩，续读不能按原请求页长跳过未读正文。"""
    text = "中文和🙂字符都按原文位置读取。" * 300
    app = application_with_text(tmp_path, text)
    try:
        scope = ExecutionScope(max_results=10)
        envelope = app.invoke_tool("get_message_context",
            GetMessageContextInput("qq:100:long", 0, 0), scope)
        record = build_tool_result_record(run_id="trimmed", tool_call_id="trimmed/tool-call/1",
            tool_result_id="trimmed/tool-call/1/result", tool_name="get_message_context", envelope=envelope, scope=scope)
        projected = project_tool_result_for_model(envelope, record, token_budget=1_000)
        first = projected["data"]["messages"][0]
        offset = first["next_content_offset"]
        assert 0 < offset < len(text)
        assert first["content"] == text[:offset] + "…"
        assert projected["model_projection"]["estimated_tokens"] <= 1_000
        context = RuntimeContext(scope=scope, capability_registry=app.capability_registry,
                                 available_capabilities=("get_message_context",), run_id="continue")
        second = asyncio.run(read_page(app, context, content_offset=offset))["data"]["messages"][0]
        assert first["content"][:-1] + second["content"] == text
        assert second["next_content_offset"] is None
    finally:
        app.close()
