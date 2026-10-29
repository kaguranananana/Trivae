"""Eval v1 Case 14：流建立前的 HTTP 错误也必须保留在正式 Trace。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
from openai import APIStatusError

from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecutionScope
from trivae.config.settings import load_settings
from trivae.query.contracts import QueryRequest


def test_http_rejection_before_stream_keeps_router_and_runtime_transport(tmp_path):
    """走真实 SDK 请求构造和 Application 持久化，HTTP 边界使用固定失败响应。"""

    settings = load_settings({
        "TRIVAE_MODEL_PROVIDER": "deepseek",
        "TRIVAE_MODEL_API_KEY": "test-provider-key",
        "TRIVAE_MODEL_BASE_URL": "https://api.deepseek.com",
        "TRIVAE_MODEL_NAME": "deepseek-flash",
    })
    application = create_application(tmp_path / "failure.sqlite3", agent_settings=settings)
    runtime = application._get_agent_runtime()
    response = httpx.Response(
        503,
        headers={"x-request-id": "req-rejected"},
        request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"),
    )
    errors = [
        APIStatusError(
            "upstream unavailable",
            response=response,
            body={"code": "server_unavailable", "type": "server_error", "message": "private response body"},
        )
        for _ in range(2)
    ]
    create = AsyncMock(side_effect=errors)
    try:
        with patch.object(runtime._provider_client.chat.completions, "create", create):
            result = asyncio.run(application.query(QueryRequest(
                "AI Agent 项目面试一般会问什么？有什么准备建议？", ExecutionScope(),
            )))

        assert not result.is_successful
        assert result.runtime_result.error.exception_type == "APIStatusError"
        assert create.await_count == 2
        # SDK 实际发送 JSON mode；答案格式错误不能误诊为漏配 response_format。
        assert create.call_args.kwargs["response_format"] == {"type": "json_object"}
        assert create.call_args.kwargs["stream"] is True
        trace = application.read_trace(result.trace_id)
        assert trace.profile == "normal"
        assert trace.terminal_status == "failed"
        router = next(event for event in trace.timeline if event.operation == "router.decision")
        failed = next(event for event in trace.timeline if event.operation == "runtime.run" and event.phase == "failed")
        for transport in (
            router.payload["provider_observation"],
            failed.payload["provider_observation"]["transport_attempts"][0],
        ):
            assert transport["status_code"] == 503
            assert transport["request_id"] == "req-rejected"
            assert transport["exception_type"] == "APIStatusError"
            assert transport["error_code"] == "server_unavailable"
            assert transport["error_type"] == "server_error"
            assert transport["chunk_count"] == 0
            assert transport["stream_completed"] is False
        assert "private response body" not in str(trace.timeline)
        assert len(application.read_conversation(result.conversation_id).messages) == 0
    finally:
        application.close()
