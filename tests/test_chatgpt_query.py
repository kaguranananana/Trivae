"""ChatGPT Responses → SDK Tools → SQLite → Finalizer/Trace/Session 的生产主链。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from tests.test_chatgpt_responses import (
    TOKEN,
    BlockingStream,
    FakeAuth,
    completed,
    function,
    message,
    settings,
    sse,
)
from tests.test_ingestion import make_message, write_export
from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecutionScope
from trivae.query.contracts import ExecutionOverride, QueryRequest
from trivae.query.evidence import MessageSource
from trivae.query.runtime.chatgpt_responses import JSON_MODE_DEVELOPER_INSTRUCTION
from trivae.query.runtime.contracts import AgentRunRequest
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter


def application_with_message(root: Path):
    """真实导入 canonical 数据；不通过 fake 工具绕过检索与证据归属。"""

    raw = root / "raw"
    raw.mkdir()
    write_export(
        raw,
        "ChatGPT(100).json",
        [make_message("m1", 1, 1_000, "Alpha was deployed")],
        chat_name="ChatGPT evidence",
        peer_uid=None,
        version="5.5.64",
    )
    application = create_application(root / "query.sqlite3")
    application.import_directory(raw)
    application.rebuild_lexical_index()
    return application


async def install_runtime(application, handler):
    """走生产 Provider 构造路径，只把 HTTP 连接替换成 MockTransport。"""

    runtime = OpenAIAgentsRuntimeAdapter(application.capability_registry, settings=settings(), chatgpt_auth=FakeAuth())
    await runtime._model._client.aclose()
    runtime._model._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    application._agent_runtime = runtime
    return runtime


def claim_payload():
    return json.dumps(
        {
            "claims": [
                {
                    "text": "Alpha 已部署。",
                    "finding": "部署信息存在于返回消息",
                    "criterion": "canonical 消息包含 Alpha deployed",
                    "sufficiency": "sufficient",
                    "sources": ["m1-1"],
                    "limitations": [],
                }
            ],
            "limitations": [],
        },
        ensure_ascii=False,
    )


def test_production_query_planner_tools_finalizer_trace_and_conversation_replay(tmp_path):
    requests = []
    tool_turns = 0

    def handler(request):
        nonlocal tool_turns
        payload = json.loads(request.content)
        requests.append(payload)
        # 复现真实服务的 JSON mode input 校验：instructions 的 JSON 不计入检查。
        assert any("json" in str(item.get("content", "")).lower() for item in payload["input"])
        assert payload["input"][0] == {"role": "developer", "content": JSON_MODE_DEVELOPER_INSTRUCTION}
        if payload["instructions"] == "Return only the requested JSON.":
            # Planner 使用同一个 OAuth 模型与同一个 Responses SSE 边界。
            output = json.dumps(
                {
                    "version": 1,
                    "title": "Evidence",
                    "intent": "evidence",
                    "steps": [{"goal": "read messages", "suggested_tools": ["get_recent_messages"]}],
                    "success_criteria": ["answer with evidence"],
                }
            )
            event = completed([message(output)])
        elif payload.get("tools"):
            tool_turns += 1
            event = completed([function("get_recent_messages", {"limit": 5}, call_id=f"call-{tool_turns}")])
        else:
            event = completed([message(claim_payload())])
        summaries = (
            [
                {
                    "type": "response.reasoning_summary_text.delta",
                    "sequence_number": 0,
                    "item_id": "summary-test",
                    "output_index": 0,
                    "summary_index": 0,
                    "delta": "核对公开证据",
                },
                {
                    "type": "response.reasoning_summary_text.done",
                    "sequence_number": 1,
                    "item_id": "summary-test",
                    "output_index": 0,
                    "summary_index": 0,
                    "text": "核对公开证据",
                },
            ]
            if payload["instructions"] != "Return only the requested JSON."
            else []
        )
        if not payload.get("tools") and summaries:
            summaries.append(
                {
                    "type": "response.output_text.delta",
                    "sequence_number": 2,
                    "item_id": "msg-test",
                    "output_index": 0,
                    "content_index": 0,
                    "logprobs": [],
                    "delta": claim_payload(),
                }
            )
        if payload.get("tools"):
            # 真实服务先发送 added，再发送不含 name 的 arguments.done，最后进入 completed。
            call = event["response"]["output"][0]
            summaries.extend(
                [
                    {"type": "response.output_item.added", "item": call, "output_index": 1, "sequence_number": 2},
                    {
                        "type": "response.function_call_arguments.done",
                        "arguments": call["arguments"],
                        "item_id": call["id"],
                        "output_index": 1,
                        "sequence_number": 3,
                    },
                ]
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream", "x-request-id": f"req-{len(requests)}"},
            text=sse(*summaries, event),
        )

    async def run():
        application = application_with_message(tmp_path)
        runtime = await install_runtime(application, handler)
        events = []
        try:
            scope = ExecutionScope(allowed_session_ids=("qq:100",), max_results=5)
            first = await application.query(
                QueryRequest(
                    "查看 Alpha 部署信息",
                    scope,
                    available_capabilities=("get_recent_messages",),
                    trace_profile="debug",
                    request_id="chatgpt-query-first",
                    execution_override=ExecutionOverride(forced_route="planned_execution"),
                ),
                on_event=events.append,
            )
            assert first.is_successful, first
            assert any(
                event.type == "thinking.delta"
                and event.thinking_visibility == "public_summary"
                and event.content == "核对公开证据"
                for event in events
            )
            assert any(event.type == "answer.delta" for event in events)
            assert first.answer_artifact.citation_bindings
            reference = first.answer_artifact.evidence_items[0].sources[0].reference
            assert isinstance(reference, MessageSource)
            assert reference.snapshot.excerpt == "Alpha was deployed"
            assert reference.internal_message_id == "qq:100:m1"
            trace = application.read_trace(first.trace_id)
            model_turns = [
                event for event in trace.timeline if event.operation == "model.turn" and event.phase == "started"
            ]
            assert model_turns[0].payload["model_visible_context"][1:] == requests[1]["input"]
            assert all(
                any(
                    item.get("role") == "developer" and item.get("content") == JSON_MODE_DEVELOPER_INSTRUCTION
                    for item in event.payload["model_visible_context"]
                )
                for event in model_turns
            )
            provider_events = [event for event in trace.timeline if event.operation == "model.output"]
            assert provider_events
            transports = [
                attempt
                for event in provider_events
                for attempt in event.payload["provider_observation"]["transport_attempts"]
            ]
            assert all(item["stream_completed"] is True for item in transports)
            assert all(item["terminal_event"] == "response.completed" for item in transports)
            assert transports[0]["event_normalizations"]["function_call_arguments_done_name"] == 1
            assert transports[1]["event_normalizations"]["function_call_arguments_done_name"] == 0
            assert TOKEN not in str(trace)
            second = await application.query(
                QueryRequest(
                    "继续核对 Alpha",
                    scope,
                    conversation_id=first.conversation_id,
                    available_capabilities=("get_recent_messages",),
                    trace_profile="debug",
                    execution_override=ExecutionOverride(forced_route="standard_execution"),
                )
            )
            assert second.is_successful, second
            stored = application.read_conversation(second.conversation_id)
            assert len(stored.messages) == 4
            assert stored.messages[-1].answer_artifact == second.answer_artifact
            assert second.runtime_result.tool_calls[0].name == "get_recent_messages"
            assert len(second.runtime_result.tool_results) == 1
            assert second.runtime_result.usage["input_tokens"] == 24
        finally:
            await runtime.aclose()
            await application.aclose()

    asyncio.run(run())
    planner = requests[0]
    assert "tools" not in planner
    runtime_requests = requests[1:]
    assert len(runtime_requests) == 4
    assert "Alpha was deployed" in str(runtime_requests[1]["input"])
    # 第一次合成耗尽产品工具轮预算；下一轮还使用真实历史而不是服务器 conversation ID。
    assert not runtime_requests[1].get("tools")
    history = runtime_requests[2]["input"]
    assert [item["role"] for item in history] == ["developer", "user", "assistant", "user"]
    assert "Alpha" in history[2]["content"]
    assert all(payload["store"] is False and payload["stream"] is True for payload in requests)


def test_runtime_quota_failure_keeps_provider_diagnostics_in_terminal_trace(tmp_path):
    def handler(_):
        return httpx.Response(
            429,
            headers={"x-request-id": "quota-request"},
            json={"error": {"code": "quota_exceeded", "message": f"plan exhausted {TOKEN}"}},
        )

    async def run():
        application = application_with_message(tmp_path)
        runtime = await install_runtime(application, handler)
        try:
            result = await application.query(
                QueryRequest(
                    "查看 Alpha",
                    ExecutionScope(allowed_session_ids=("qq:100",)),
                    available_capabilities=("get_recent_messages",),
                    trace_profile="debug",
                    execution_override=ExecutionOverride(forced_route="standard_execution"),
                )
            )
            assert not result.is_successful
            assert result.runtime_result.error.code == "quota_exceeded"
            assert "plan exhausted" in result.runtime_result.error.message
            assert TOKEN not in result.runtime_result.error.message
            trace = application.read_trace(result.trace_id)
            serialized = str(trace)
            assert "quota-request" in serialized
            assert "429" in serialized
            assert "quota_exceeded" in serialized
            assert TOKEN not in serialized
        finally:
            await runtime.aclose()
            await application.aclose()

    asyncio.run(run())


def test_runtime_abort_cancels_provider_and_closes_connection(tmp_path):
    async def run():
        application = application_with_message(tmp_path)
        stream = BlockingStream()
        runtime = await install_runtime(
            application, lambda _: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)
        )
        abort = asyncio.Event()
        try:
            events_task = asyncio.create_task(_collect_abort_events(runtime, abort))
            await stream.started.wait()
            abort.set()
            events = await asyncio.wait_for(events_task, 2)
            assert events[-1].type == "aborted"
            assert events[-1].result.termination == "aborted"
            assert stream.closed
        finally:
            await runtime.aclose()
            await application.aclose()

    asyncio.run(run())


async def _collect_abort_events(runtime, abort):
    return [
        event
        async for event in runtime.stream(
            AgentRunRequest(
                "查看 Alpha",
                ExecutionScope(allowed_session_ids=("qq:100",)),
                available_capabilities=("get_recent_messages",),
            ),
            abort_event=abort,
        )
    ]
