"""公开 Responses 协议和真实 SDK Runner 的回归测试，不使用用户凭证。"""

from __future__ import annotations

import asyncio
import json
import ssl

import anyio
import httpcore
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
        assert failure.value.safe_observation["transport_exception_chain"] == [
            {"type": "ReadTimeout", "message": "upstream stalled [REDACTED]"}]
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


def test_tls_eof_context_is_visible_redacted_and_keeps_original_http_budget(tmp_path):
    """复现 AnyIO 隐藏 EOF 上下文的实际异常形状；不能只遍历显式 cause。"""
    from trivae.evaluation.prompt_screening import ProviderCallBudget, read_artifact

    sent = []

    async def handler(request):
        sent.append(request)
        try:
            raise ssl.SSLEOFError(8, f"UNEXPECTED_EOF_WHILE_READING {TOKEN}")
        except ssl.SSLEOFError:
            try:
                # 对应 AnyIO standard_compatible=False，故意隐藏 traceback 上下文。
                raise anyio.EndOfStream from None
            except anyio.EndOfStream as stream_error:
                try:
                    raise httpcore.ConnectError from stream_error
                except httpcore.ConnectError as core_error:
                    raise httpx.ConnectError("", request=request) from core_error

    async def run():
        budget = ProviderCallBudget(1, total_ledger=tmp_path / "total.json", total_maximum=1)
        observations = []
        model = ChatGPTResponsesModel(MODEL, FakeAuth(), observer=observations.append,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler),
                event_hooks={"request": [budget.before_request]}))
        try:
            with pytest.raises(ChatGPTResponsesError) as failure:
                await model.get_response(**sdk_args())
            observation = failure.value.safe_observation
            assert failure.value.code == "PROVIDER_ERROR"
            assert observation["exception_type"] == "ConnectError"
            assert observation["status_code"] is None and observation["stream_completed"] is False
            chain = observation["transport_exception_chain"]
            assert [item["type"] for item in chain] == ["ConnectError", "ConnectError", "EndOfStream", "SSLEOFError"]
            assert "UNEXPECTED_EOF_WHILE_READING" in chain[-1]["message"]
            assert "[REDACTED]" in chain[-1]["message"]
            assert TOKEN not in json.dumps(observation)
            assert "Authorization" not in json.dumps(chain)
            assert observations[0]["transport_exception_chain"] == chain
            assert len(sent) == len(budget.requests) == 1
            assert read_artifact(tmp_path / "total.json") == {"maximum": 1, "provider_calls": 1}
            # 诊断记录不得引入重试；预算耗尽仍在下一次实际发送前拒绝。
            with pytest.raises(ChatGPTResponsesError, match="maximum provider calls exhausted"):
                await model.get_response(**sdk_args())
            assert len(sent) == len(budget.requests) == 1
            assert "transport_exception_chain" not in observations[-1]
        finally:
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
        assert "transport_exception_chain" not in failure.value.safe_observation
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


@pytest.mark.parametrize("effort", ["medium", "high"])
def test_effort_serialization_is_shared_by_runtime_router_and_planner(effort):
    """真实 HTTP body 证明三条路径使用同一显式档位，失败请求也计入同一预算。"""
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
                                                    chatgpt_reasoning_effort=effort),
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
            assert all(body["reasoning"] == {"effort": effort, "summary": "auto"} for body in sent)
            assert runtime.safe_configuration()["protocol"]["reasoning_effort"] == effort
            assert runtime.completion_request_projection()["reasoning"] == sent[0]["reasoning"]
            assert runtime.planner_completion_request_projection()["reasoning"] == sent[0]["reasoning"]
        finally:
            await runtime.aclose()
    asyncio.run(run())


def test_incomplete_metadata_event_remains_explicit_without_protocol_bypass():
    """旧最小反例缺响应身份/metadata，新增已知类型后仍必须拒绝。"""
    from dataclasses import replace

    async def run():
        runtime = OpenAIAgentsRuntimeAdapter(
            settings=replace(settings(), model_name="gpt-6.1-sol", chatgpt_reasoning_effort="high"),
            chatgpt_auth=FakeAuth(models=[{"slug": "gpt-6.1-sol"}]),
        )
        await runtime._model._client.aclose()
        runtime._model._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, headers={"content-type": "text/event-stream"},
            text=sse({"type": "response.metadata", "sequence_number": 1}),
        )))
        try:
            with pytest.raises(ChatGPTResponsesError, match="response.metadata") as error:
                await runtime.complete_text_with_observation("Return JSON.")
            assert error.value.code == "MALFORMED_STREAM"
            assert error.value.safe_observation["stream_completed"] is False
            assert error.value.safe_observation["validation_errors"][0]["type"] == "missing"
            assert error.value.safe_observation["request"]["reasoning"]["effort"] == "high"
        finally:
            await runtime.aclose()
    asyncio.run(run())


def metadata_event(**updates):
    """脱敏复现实际 envelope：审核旁路元数据，不是模型输出或终态。"""
    event = {"type": "response.metadata", "response_id": "resp-test", "sequence_number": 28,
             "metadata": {"openai_chatgpt_moderation_metadata": {
                 "prompt": {"omnimod": {"protection_type": "omnimod", "outputs": [{
                     "results": [{"category_flags": {"A1": False}}], "is_blocked": False}]}},
                 "generation": {}, "tool_call": {}, "tool_response": {}}}}
    return {**event, **updates}


def nested_quota_event():
    """回放真实 HTTP 200 SSE 的订阅额度错误 envelope，不含用户输出。"""
    return {"type": "error", "sequence_number": 3, "error": {
        "type": "invalid_request_error", "code": "subscription_sharing_usage_limit_exceeded",
        "message": "The ChatGPT user has reached their Subscription Sharing usage limit. "
                   "Ask the user to try again after their usage limit resets or use an API key instead.",
        "param": None}}


def test_metadata_then_nested_quota_preserves_leaf_code_and_stops_without_usage(tmp_path):
    """HTTP 200 和 metadata 不是成功；嵌套叶子额度必须触发既有推理硬停。"""
    from trivae.evaluation.prompt_screening import ProviderCallBudget, read_artifact

    async def run():
        event = nested_quota_event()
        event["error"]["message"] += f" {TOKEN}"
        sent = []
        observed = []
        budget = ProviderCallBudget(2, total_ledger=tmp_path / "total.json", total_maximum=2)

        def handler(request):
            sent.append(request)
            return httpx.Response(200, headers={"content-type": "text/event-stream", "x-request-id": "nested-quota"},
                text=sse(metadata_event(sequence_number=1), event))

        model = ChatGPTResponsesModel(MODEL, FakeAuth(), observer=observed.append,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler),
                event_hooks={"request": [budget.before_request]}))
        try:
            with pytest.raises(ChatGPTResponsesError) as failure:
                await model.get_response(**sdk_args())
            error = failure.value
            assert error.code == "subscription_sharing_usage_limit_exceeded"
            assert error.stops_inference is True
            assert "Subscription Sharing usage limit" in str(error)
            observation = error.safe_observation
            assert observation["status_code"] == 200 and observation["terminal_event"] == "error"
            assert observation["stream_completed"] is False and observation.get("usage") is None
            assert len(observation["metadata_events"]) == 1
            assert json.loads(observation["body"])["error"]["code"] == error.code
            assert TOKEN not in str(error) and TOKEN not in json.dumps(observed)
            assert len(sent) == len(budget.requests) == 1
            assert read_artifact(tmp_path / "total.json")["provider_calls"] == 1
        finally:
            await model.close()

    asyncio.run(run())


@pytest.mark.parametrize("override", [
    {"error": "invalid nested error"},
    {"error": {"type": "invalid_request_error", "message": "missing code", "param": None}},
    {"sequence_number": True},
    {"extra_output": "must not be accepted"},
])
def test_nested_error_malformed_envelope_is_rejected_instead_of_classifying_quota(override):
    """严格验证已证实的嵌套 envelope，不能凭模糊字段猜额度或放行额外输出。"""
    async def run():
        event = {**nested_quota_event(), **override}
        model = ChatGPTResponsesModel(MODEL, FakeAuth(), client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200,
                headers={"content-type": "text/event-stream"}, text=sse(metadata_event(), event)))))
        try:
            with pytest.raises(ChatGPTResponsesError) as failure:
                await model.get_response(**sdk_args())
            assert failure.value.code == "MALFORMED_STREAM"
            assert failure.value.safe_observation["event_type"] == "error"
            assert failure.value.safe_observation["stream_completed"] is False
            assert failure.value.safe_observation.get("usage") is None
            assert "body" not in failure.value.safe_observation
        finally:
            await model.close()

    asyncio.run(run())


def test_metadata_is_validated_and_observed_without_replacing_completion_or_usage():
    """接受已知扩展但仍等待SDK终态，元数据不进入模型内容/隐藏推理/Usage。"""
    async def run():
        terminal = completed([message('{"ok":true}')])
        terminal['sequence_number'] = 29
        model = ChatGPTResponsesModel(MODEL, FakeAuth(), client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200,
                headers={"content-type": "text/event-stream"}, text=sse(metadata_event(), terminal)))))
        try:
            response, observation = await model.collect_response(model._payload(
                "Return JSON.", "test", SDKModelSettings(), [], None, []))
            assert response.output_text == '{"ok":true}'
            assert observation['stream_completed'] is True
            assert observation['usage']['input_tokens'] == 12
            assert observation['usage']['reasoning_tokens'] == 1
            assert observation['metadata_events'] == [{"response_id": "resp-test", "sequence_number": 28,
                "keys": ["openai_chatgpt_moderation_metadata"]}]
            assert "category_flags" not in json.dumps(observation)
        finally:
            await model.close()
    asyncio.run(run())


@pytest.mark.parametrize('event,code', [
    (metadata_event(metadata=[]), 'MALFORMED_STREAM'),
    (metadata_event(sequence_number='28'), 'MALFORMED_STREAM'),
    (metadata_event(response_id=5), 'MALFORMED_STREAM'),
    (metadata_event(extra_output='not allowed'), 'MALFORMED_STREAM'),
    (metadata_event(type='response.unknown_metadata'), 'MALFORMED_STREAM'),
    (metadata_event(), 'STREAM_INTERRUPTED'),
])
def test_metadata_invalid_unknown_and_without_terminal_remain_explicit(event, code):
    """新增已知类型不放宽未知类型、字段形状或终态要求。"""
    async def run():
        model = ChatGPTResponsesModel(MODEL, FakeAuth(), client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200,
                headers={"content-type": "text/event-stream"}, text=sse(event)))))
        try:
            with pytest.raises(ChatGPTResponsesError) as error:
                await model.get_response(**sdk_args())
            assert error.value.code == code
            assert error.value.safe_observation['stream_completed'] is False
        finally:
            await model.close()
    asyncio.run(run())


def test_metadata_sdk_tool_loop_keeps_reasoning_replay_and_each_turn_usage():
    """真实SDK两轮工具调用，每轮均有metadata，隐藏replay和Usage仍来自原终态。"""
    requests = []
    observations = []
    invocations = []

    @function_tool
    def evidence(query: str) -> str:
        """只提供无私有内容的测试证据。"""
        invocations.append(query)
        return "canonical evidence"

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        output = ([{"id": "rs-1", "type": "reasoning", "summary": [],
                    "encrypted_content": "opaque-replay"}, function('evidence', {'query': 'alpha'})]
                  if len(requests) == 1 else [message('{"answer":"alpha"}')])
        terminal = completed(output)
        terminal['sequence_number'] = 29
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                              text=sse(metadata_event(), terminal))

    async def run():
        model = ChatGPTResponsesModel(MODEL, FakeAuth(), observer=observations.append,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        agent = Agent(name='test', model=model, instructions='Return JSON.',
                      tools=tool_namespace(name='trivae', description='test', tools=[evidence]))
        try:
            result = await Runner.run(agent, 'alpha', run_config=RunConfig(tracing_disabled=True))
            assert invocations == ['alpha']
            assert len(requests) == 2
            assert any(item.get('encrypted_content') == 'opaque-replay' for item in requests[1]['input'])
            assert any(item.get('type') == 'function_call_output' for item in requests[1]['input'])
            assert not any(item.get('type') == 'response.metadata' for item in requests[1]['input'])
            assert result.final_output == '{"answer":"alpha"}'
            assert result.context_wrapper.usage.input_tokens == 24
            assert result.context_wrapper.usage.output_tokens == 10
            assert len(observations) == 2
            assert all(o['metadata_events'][0]['response_id'] == 'resp-test' for o in observations)
        finally:
            await model.close()
    asyncio.run(run())


@pytest.mark.parametrize('terminal,expected', [
    (completed([], status='incomplete', event_type='response.incomplete'), 'response.incomplete'),
    (completed([], status='failed', event_type='response.failed'), 'response.failed'),
    ({**completed([]), 'response': {**completed([])['response'], 'id': 'resp-other'}},
     'METADATA_RESPONSE_MISMATCH'),
])
def test_metadata_does_not_hide_failure_or_wrong_response_identity(terminal, expected):
    """metadata不是成功信号，之后的失败/关联错误继续显式上报。"""
    async def run():
        model = ChatGPTResponsesModel(MODEL, FakeAuth(), client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200,
                headers={'content-type': 'text/event-stream'}, text=sse(metadata_event(), terminal)))))
        try:
            with pytest.raises(ChatGPTResponsesError) as error:
                await model.get_response(**sdk_args())
            assert error.value.code == expected
            assert error.value.safe_observation['stream_completed'] is False
            assert len(error.value.safe_observation['metadata_events']) == 1
        finally:
            await model.close()
    asyncio.run(run())
