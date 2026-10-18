"""公开 Responses 协议和真实 SDK Runner 的回归测试，不使用用户凭证。"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from agents import Agent, RunConfig, Runner, function_tool, tool_namespace
from agents.model_settings import ModelSettings as SDKModelSettings
from agents.models.interface import ModelTracing

from trivae.config.settings import ModelSettings
from trivae.query.runtime.chatgpt_responses import (
    JSON_MODE_DEVELOPER_INSTRUCTION,
    RESPONSES_ENDPOINT,
    ChatGPTResponsesError,
    ChatGPTResponsesModel,
)
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter

MODEL = "account-catalog-model"
TOKEN = "test-oauth-secret"


class FakeAuth:
    """模型目录和短期凭证的本地 fake，模拟刷新后读取新 token。"""

    def __init__(self, models=None):
        self.models = [{"slug": MODEL}] if models is None else models
        self.closed = False
        self.catalog_calls = 0

    async def access_token(self):
        return TOKEN

    async def list_models(self):
        self.catalog_calls += 1
        return self.models

    def redact(self, message):
        return message.replace(TOKEN, "[REDACTED]")

    async def aclose(self):
        self.closed = True


def completed(output, *, status="completed", event_type="response.completed"):
    """生成真实 OpenAI typed SSE 可验证的 terminal envelope。"""

    return {
        "type": event_type,
        "sequence_number": 1,
        "response": {
            "id": "resp-test",
            "created_at": 1000,
            "model": MODEL,
            "object": "response",
            "status": status,
            "output": output,
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": [],
            "usage": {
                "input_tokens": 12,
                "output_tokens": 5,
                "total_tokens": 17,
                "input_tokens_details": {"cached_tokens": 2, "cache_write_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 1},
            },
        },
    }


def message(text):
    return {
        "type": "message",
        "id": "msg-test",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def function(name, arguments, *, call_id="call-test"):
    return {
        "type": "function_call",
        "id": "fc-test",
        "name": name,
        "namespace": "trivae",
        "arguments": json.dumps(arguments),
        "call_id": call_id,
        "status": "completed",
    }


def sse(*events):
    return "".join("data: " + json.dumps(event) + "\n\n" for event in events)


def settings():
    return ModelSettings(
        api_key="",
        base_url="https://api.openai.com/v1",
        provider="chatgpt-plan",
        model_name=MODEL,
        max_turns=5,
        max_tool_rounds=1,
        tool_result_budget_mode="fixed",
    )


def sdk_args():
    return {
        "system_instructions": "Return JSON.",
        "input": [{"role": "user", "content": "test"}],
        "model_settings": SDKModelSettings(max_tokens=99, temperature=0.5, metadata={"a": "b"}),
        "tools": [],
        "output_schema": None,
        "handoffs": [],
        "tracing": ModelTracing.DISABLED,
        "previous_response_id": "forbidden",
        "conversation_id": "forbidden",
        "prompt": None,
    }


def test_actual_sdk_runner_dispatches_namespaced_tool_and_replays_full_input():
    requests = []
    invocations = []

    @function_tool
    def read_evidence(query: str) -> str:
        """读取测试证据。"""
        invocations.append(query)
        return "canonical evidence"

    def handler(request):
        assert str(request.url) == RESPONSES_ENDPOINT
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            reasoning = {
                "id": "rs-test",
                "type": "reasoning",
                "summary": [],
                "encrypted_content": "opaque-encrypted-state",
            }
            event = completed([reasoning, function("read_evidence", {"query": "alpha"})])
        else:
            event = completed([message('{"answer":"alpha"}')])
        return httpx.Response(
            200, headers={"content-type": "text/event-stream", "x-request-id": "request-test"}, text=sse(event)
        )

    async def run():
        auth = FakeAuth()
        model = ChatGPTResponsesModel(MODEL, auth, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        agent = Agent(
            name="test",
            model=model,
            instructions="Return JSON.",
            tools=tool_namespace(name="trivae", description="local evidence", tools=[read_evidence]),
        )
        result = await Runner.run(
            agent,
            [
                {"role": "user", "content": "prior question"},
                {"role": "assistant", "content": "prior answer"},
                {"role": "user", "content": "alpha"},
            ],
            run_config=RunConfig(tracing_disabled=True),
        )
        assert result.final_output == '{"answer":"alpha"}'
        assert auth.catalog_calls == 1
        await model.close()
        assert auth.closed

    asyncio.run(run())
    assert invocations == ["alpha"]
    assert len(requests) == 2
    assert requests[0]["tools"][0]["type"] == "namespace"
    assert requests[0]["tools"][0]["name"] == "trivae"
    assert requests[0]["tools"][0]["tools"][0]["name"] == "read_evidence"
    replay = requests[1]["input"]
    # 协议前缀包含在真实请求中；完整旧历史仍必须逐项相同。
    assert replay[: len(requests[0]["input"])] == requests[0]["input"]
    assert requests[0]["input"][0] == {"role": "developer", "content": JSON_MODE_DEVELOPER_INSTRUCTION}
    assert [item["content"] for item in requests[0]["input"][1:]] == ["prior question", "prior answer", "alpha"]
    assert sum(item.get("role") == "developer" for item in replay) == 1
    assert next(item for item in replay if item.get("type") == "function_call_output")["call_id"] == "call-test"
    assert next(item for item in replay if item.get("type") == "function_call_output")["output"] == "canonical evidence"
    assert (
        next(item for item in replay if item.get("type") == "reasoning")["encrypted_content"]
        == "opaque-encrypted-state"
    )
    for payload in requests:
        assert payload["store"] is False and payload["stream"] is True
        assert payload["include"] == ["reasoning.encrypted_content"]
        assert (
            not {"max_output_tokens", "temperature", "top_p", "metadata", "previous_response_id", "conversation"}
            & payload.keys()
        )


def test_get_response_and_completions_use_same_stream_json_transport():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream", "x-request-id": "req-json"},
            text=sse(completed([message('{"route":"standard_execution"}')])),
        )

    async def run():
        model = ChatGPTResponsesModel(
            MODEL, FakeAuth(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        response = await model.get_response(**sdk_args())
        assert response.request_id == "req-json"
        runtime = OpenAIAgentsRuntimeAdapter(model=model, settings=settings())
        result = await runtime.complete_text_with_observation("route JSON")
        assert result.observation.model == MODEL
        assert result.observation.usage["reasoning_tokens"] == 1
        assert result.observation.transport["terminal_event"] == "response.completed"
        assert result.observation.transport["stream_completed"] is True
        assert result.observation.transport["request_id"] == "req-json"
        assert result.observation.request["store"] is False
        assert runtime.safe_configuration()["protocol"]["auth_mode"] == "chatgpt_oauth"
        await runtime.aclose()

    asyncio.run(run())
    for payload in requests:
        assert payload["text"] == {"format": {"type": "json_object"}}
        assert "max_output_tokens" not in payload
        assert "previous_response_id" not in payload
        assert "temperature" not in payload


@pytest.mark.parametrize(
    "body,code",
    [
        (sse({"type": "error", "code": "quota_exceeded", "message": "quota"}), "quota_exceeded"),
        (sse(completed([], status="failed", event_type="response.failed")), "response.failed"),
        (sse(completed([], status="incomplete", event_type="response.incomplete")), "response.incomplete"),
        ("data: {}\n\n", "MALFORMED_STREAM"),
        ("data: broken-json\n\n", "MALFORMED_STREAM"),
        ("data: [DONE]\n\n", "STREAM_INTERRUPTED"),
        ("", "STREAM_INTERRUPTED"),
    ],
)
def test_terminal_failures_and_malformed_or_interrupted_stream_are_explicit(body, code):
    observations = []

    async def run():
        model = ChatGPTResponsesModel(
            MODEL,
            FakeAuth(),
            observer=observations.append,
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(
                        200, headers={"content-type": "text/event-stream", "x-request-id": "req-failed"}, text=body
                    )
                )
            ),
        )
        with pytest.raises(ChatGPTResponsesError) as failure:
            await model.get_response(**sdk_args())
        assert failure.value.code == code
        assert failure.value.safe_observation["request_id"] == "req-failed"
        await model.close()

    asyncio.run(run())
    assert len(observations) == 1
    assert observations[0]["stream_completed"] is False
    assert observations[0]["error_code"] == code


def test_http_quota_error_retains_safe_body_request_id_and_completion_observation():
    async def run():
        body = {"error": {"code": "quota_exceeded", "message": f"quota denied {TOKEN}"}}
        model = ChatGPTResponsesModel(
            MODEL,
            FakeAuth(),
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(429, headers={"x-request-id": "req-quota"}, json=body)
                )
            ),
        )
        runtime = OpenAIAgentsRuntimeAdapter(model=model, settings=settings())
        with pytest.raises(ChatGPTResponsesError) as failure:
            await runtime.complete_text_with_observation("test JSON")
        error = failure.value
        assert TOKEN not in str(error)
        assert TOKEN not in str(error.safe_observation)
        assert error.safe_observation["status_code"] == 429
        assert error.safe_observation["request_id"] == "req-quota"
        assert "quota denied" in error.safe_observation["body"]
        assert error.completion_observation.transport == error.safe_observation
        await runtime.aclose()

    asyncio.run(run())


def test_unauthorized_model_rejected_before_inference():
    async def run():
        requests = []
        model = ChatGPTResponsesModel(
            MODEL,
            FakeAuth(models=[{"slug": "different-account-model"}]),
            client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: requests.append(request))),
        )
        with pytest.raises(ChatGPTResponsesError, match="MODEL_NOT_AUTHORIZED"):
            await model.get_response(**sdk_args())
        assert requests == []
        await model.close()

    asyncio.run(run())


class BlockingStream(httpx.AsyncByteStream):
    """模拟网络仍连接但 Provider 不发送终态；关闭事实可被直接断言。"""

    def __init__(self):
        self.started = asyncio.Event()
        self.closed = False

    async def __aiter__(self):
        self.started.set()
        await asyncio.Event().wait()
        yield b""

    async def aclose(self):
        self.closed = True


def test_cancel_closes_http_stream_and_reports_incomplete_transport():
    async def run():
        stream = BlockingStream()
        observations = []
        model = ChatGPTResponsesModel(
            MODEL,
            FakeAuth(),
            observer=observations.append,
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)
                )
            ),
        )
        task = asyncio.create_task(model.get_response(**sdk_args()))
        await stream.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.closed
        assert observations[0]["error_code"] == "REQUEST_CANCELLED"
        assert observations[0]["stream_completed"] is False
        await model.close()

    asyncio.run(run())


def test_read_timeout_has_explicit_safe_diagnostics():
    async def handler(request):
        raise httpx.ReadTimeout(f"upstream stalled {TOKEN}", request=request)

    async def run():
        model = ChatGPTResponsesModel(
            MODEL, FakeAuth(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        with pytest.raises(ChatGPTResponsesError) as failure:
            await model.get_response(**sdk_args())
        assert failure.value.code == "REQUEST_TIMEOUT"
        assert TOKEN not in str(failure.value)
        assert failure.value.safe_observation["stream_completed"] is False
        await model.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "error", [None, "quota reached", ["quota"], {"code": "subscription_sharing_usage_limit_exceeded"}]
)
def test_http_429_body_shapes_pause_inference_and_keep_safe_body(error):
    async def run():
        model = ChatGPTResponsesModel(
            MODEL,
            FakeAuth(),
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(429, headers={"x-request-id": "req-body-shape"}, json={"error": error})
                )
            ),
        )
        with pytest.raises(ChatGPTResponsesError) as failure:
            await model.get_response(**sdk_args())
        assert failure.value.stops_inference is True
        assert failure.value.safe_observation["status_code"] == 429
        assert failure.value.safe_observation["request_id"] == "req-body-shape"
        assert json.loads(failure.value.safe_observation["body"])["error"] == error
        await model.close()

    asyncio.run(run())


def test_failed_terminal_never_copies_encrypted_reasoning_to_error_body():
    async def run():
        event = completed(
            [
                {
                    "type": "reasoning",
                    "id": "hidden-state",
                    "summary": [],
                    "encrypted_content": "opaque-private-encrypted-state",
                }
            ],
            status="failed",
            event_type="response.failed",
        )
        model = ChatGPTResponsesModel(
            MODEL,
            FakeAuth(),
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(200, headers={"content-type": "text/event-stream"}, text=sse(event))
                )
            ),
        )
        with pytest.raises(ChatGPTResponsesError) as failure:
            await model.get_response(**sdk_args())
        assert "opaque-private-encrypted-state" not in str(failure.value.safe_observation)
        assert "encrypted_content" not in failure.value.safe_observation["body"]
        assert failure.value.safe_observation["response_id"] == "resp-test"
        await model.close()

    asyncio.run(run())


def test_auth_scope_failure_preserves_structured_root_cause_and_stops_inference():
    from trivae.auth import ChatGPTAuthError

    class RevokedAuth(FakeAuth):
        async def list_models(self):
            raise ChatGPTAuthError(
                "AUTH_SCOPE",
                "scope revoked",
                status_code=403,
                oauth_code="chatpass_v2_scope_not_authorized",
                request_id="auth-scope-request",
            )

    async def run():
        model = ChatGPTResponsesModel(MODEL, RevokedAuth())
        runtime = OpenAIAgentsRuntimeAdapter(model=model, settings=settings())
        with pytest.raises(ChatGPTResponsesError) as failure:
            await runtime.complete_text_with_observation("test JSON")
        assert failure.value.code == "AUTH_SCOPE"
        assert failure.value.stops_inference is True
        transport = failure.value.completion_observation.transport
        assert transport["oauth_code"] == "chatpass_v2_scope_not_authorized"
        assert transport["request_id"] == "auth-scope-request"
        assert transport["status_code"] == 403
        await runtime.aclose()

    asyncio.run(run())


def test_real_failure_case_missing_content_type_is_validated_by_sse_terminal():
    async def run():
        model = ChatGPTResponsesModel(
            MODEL,
            FakeAuth(),
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(200, content=sse(completed([message("{}")])).encode())
                )
            ),
        )
        response = await model.get_response(**sdk_args())
        assert response.output[0].content[0].text == "{}"
        assert response.request_id is None
        await model.close()

    asyncio.run(run())


def test_empty_transport_exception_keeps_original_type_in_safe_diagnostics():
    async def handler(_):
        raise AssertionError()

    async def run():
        model = ChatGPTResponsesModel(
            MODEL, FakeAuth(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        with pytest.raises(ChatGPTResponsesError) as failure:
            await model.get_response(**sdk_args())
        assert failure.value.code == "PROVIDER_ERROR"
        assert "AssertionError" in str(failure.value)
        assert failure.value.safe_observation["exception_type"] == "AssertionError"
        await model.close()

    asyncio.run(run())


def test_explicit_non_sse_content_type_remains_an_explicit_protocol_error():
    async def run():
        model = ChatGPTResponsesModel(
            MODEL,
            FakeAuth(),
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(
                        200,
                        headers={"content-type": "application/json"},
                        content=sse(completed([message("{}")])).encode(),
                    )
                )
            ),
        )
        with pytest.raises(ChatGPTResponsesError) as failure:
            await model.get_response(**sdk_args())
        assert failure.value.code == "INVALID_STREAM"
        assert failure.value.safe_observation["stream_completed"] is False
        await model.close()

    asyncio.run(run())


def test_real_json_mode_failure_case_adds_developer_input_without_changing_user_query():
    user_query = "找出一条具体消息并引用原消息。"
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        # HTTP400的原始FailureCase只检查input中的json，不检查instructions。
        assert payload["text"]["format"]["type"] == "json_object"
        assert any("json" in str(item.get("content", "")).lower() for item in payload["input"])
        return httpx.Response(200, content=sse(completed([message("{}")])).encode())

    async def run():
        model = ChatGPTResponsesModel(
            MODEL, FakeAuth(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        arguments = sdk_args()
        arguments["system_instructions"] = "业务 SYSTEM_PROMPT 保留原 JSON 答案契约。"
        arguments["input"] = [{"role": "user", "content": user_query}]
        await model.get_response(**arguments)
        assert arguments["input"] == [{"role": "user", "content": user_query}]
        assert requests[0]["instructions"] == arguments["system_instructions"]
        assert requests[0]["input"] == [
            {"role": "developer", "content": JSON_MODE_DEVELOPER_INSTRUCTION},
            {"role": "user", "content": user_query},
        ]
        await model.close()

    asyncio.run(run())


def test_sdk_event_validation_diagnostic_keeps_field_locations_without_private_input():
    async def run():
        event = completed([message("{}")])
        del event["response"]["id"]
        # 非 schema 字段含 replay 秘密；字段诊断不得复制完整 provider input。
        event["private_replay"] = {"encrypted_content": "opaque-private-encrypted-state", "secret": TOKEN}
        model = ChatGPTResponsesModel(
            MODEL,
            FakeAuth(),
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(lambda _: httpx.Response(200, content=sse(event).encode()))
            ),
        )
        with pytest.raises(ChatGPTResponsesError) as failure:
            await model.get_response(**sdk_args())
        observation = failure.value.safe_observation
        assert observation["event_type"] == "response.completed"
        assert any(
            error["loc"][-2:] == ["response", "id"] and error["type"] == "missing"
            for error in observation["validation_errors"]
        )
        assert all(set(error) == {"loc", "type", "msg"} for error in observation["validation_errors"])
        assert "opaque-private-encrypted-state" not in str(observation)
        assert TOKEN not in str(observation)
        await model.close()

    asyncio.run(run())


def test_real_arguments_done_shape_maps_names_by_distinct_added_item_ids():
    first = function("read_evidence", {"query": "alpha"}, call_id="call-alpha")
    first["id"] = "item-alpha"
    second = function("count_messages", {"session": "beta"}, call_id="call-beta")
    second["id"] = "item-beta"
    # done 事件顺序与 added 不同，证明按 item_id 关联，而不是使用最近的函数名。
    events = [
        {"type": "response.output_item.added", "item": first, "output_index": 0, "sequence_number": 1},
        {"type": "response.output_item.added", "item": second, "output_index": 1, "sequence_number": 2},
        {
            "type": "response.function_call_arguments.done",
            "arguments": first["arguments"],
            "item_id": "item-alpha",
            "output_index": 0,
            "sequence_number": 3,
        },
        {
            "type": "response.function_call_arguments.done",
            "arguments": second["arguments"],
            "item_id": "item-beta",
            "output_index": 1,
            "sequence_number": 4,
        },
        completed([first, second]),
    ]

    async def run():
        observations = []
        model = ChatGPTResponsesModel(
            MODEL,
            FakeAuth(),
            observer=observations.append,
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(lambda _: httpx.Response(200, content=sse(*events).encode()))
            ),
        )
        parsed = [event async for event in model.stream_response(**sdk_args())]
        done = [event for event in parsed if event.type == "response.function_call_arguments.done"]
        assert [(event.item_id, event.name, event.arguments) for event in done] == [
            ("item-alpha", "read_evidence", first["arguments"]),
            ("item-beta", "count_messages", second["arguments"]),
        ]
        assert parsed[-1].response.output[0].call_id == "call-alpha"
        assert parsed[-1].response.output[1].call_id == "call-beta"
        assert observations[0]["event_normalizations"] == {"function_call_arguments_done_name": 2}
        assert "query" not in str(observations[0]["event_normalizations"])
        await model.close()

    asyncio.run(run())


def test_arguments_done_without_associated_added_function_is_explicit_failure():
    event = {
        "type": "response.function_call_arguments.done",
        "arguments": '{"query":"alpha"}',
        "item_id": "unknown-item",
        "output_index": 0,
        "sequence_number": 1,
    }

    async def run():
        model = ChatGPTResponsesModel(
            MODEL,
            FakeAuth(),
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(lambda _: httpx.Response(200, content=sse(event).encode()))
            ),
        )
        with pytest.raises(ChatGPTResponsesError) as failure:
            await model.get_response(**sdk_args())
        assert failure.value.code == "UNASSOCIATED_TOOL_CALL"
        assert failure.value.safe_observation["stream_completed"] is False
        assert failure.value.safe_observation["event_normalizations"] == {"function_call_arguments_done_name": 0}
        await model.close()

    asyncio.run(run())


def test_high_serialization_is_shared_by_runtime_router_and_planner():
    """真实 HTTP body 证明三条路径同为 High，失败请求也计入同一预算。"""
    from dataclasses import replace

    from trivae.evaluation.prompt_screening import ProviderCallBudget, ScreeningRuntime

    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        if len(sent) == 3:
            return httpx.Response(400, json={"error": {"code": "test_failure", "message": "explicit failure"}})
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              text=sse(completed([message('{"ok":true}')])))

    async def run():
        runtime = ScreeningRuntime(settings=replace(settings(), model_name="gpt-6.1-sol",
                                                    chatgpt_reasoning_effort="high"),
                                   chatgpt_auth=FakeAuth(models=[{"slug": "gpt-6.1-sol"}]))
        await runtime._model._client.aclose()
        runtime._model._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        budget = ProviderCallBudget(3)
        runtime.install_provider_budget(budget)
        try:
            # Runtime SDK Model 与 completion 共用同一序列化入口。
            await runtime._model.get_response(**sdk_args())
            await runtime.complete_text_with_observation("Return JSON.")
            with pytest.raises(ChatGPTResponsesError, match="test_failure"):
                await runtime.complete_planner_text_with_observation("Return JSON.")
            assert len(sent) == len(budget.requests) == 3
            assert all(body["reasoning"] == {"effort": "high", "summary": "auto"} for body in sent)
            assert runtime.safe_configuration()["protocol"]["reasoning_effort"] == "high"
            assert runtime.completion_request_projection()["reasoning"] == sent[0]["reasoning"]
            assert runtime.planner_completion_request_projection()["reasoning"] == sent[0]["reasoning"]
        finally:
            await runtime.aclose()
    asyncio.run(run())
