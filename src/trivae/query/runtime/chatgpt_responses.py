"""ChatGPT 订阅推理的受限 Responses 边界；Agent loop 仍由 SDK Runner 拥有。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Mapping
from contextlib import aclosing
from typing import Annotated, Any, Protocol, cast

import httpx
from agents.agent_output import AgentOutputSchemaBase
from agents.handoffs import Handoff
from agents.items import ItemHelpers, ModelResponse, TResponseInputItem
from agents.model_settings import ModelSettings
from agents.models.interface import Model, ModelTracing
from agents.models.openai_responses import Converter
from agents.tool import Tool
from agents.usage import Usage
from openai.types.responses import Response, ResponseStreamEvent
from openai.types.responses.response_prompt_param import ResponsePromptParam
from pydantic import Field, TypeAdapter, ValidationError

from trivae.auth import ChatGPTAuthError
from trivae.auth.chatgpt import TERMINAL_REFRESH_ERRORS
from trivae.config.model_capabilities import CHATGPT_REASONING_EFFORTS
from trivae.query.completion import CompletionProviderError

RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses"
_EVENT_ADAPTER: TypeAdapter[Any] = TypeAdapter(Annotated[ResponseStreamEvent, Field(discriminator="type")])

# 真实 HTTP 400 证明 JSON mode 的关键字必须在 input 内，instructions 不满足服务端校验。
JSON_MODE_DEVELOPER_INSTRUCTION = "JSON output is required. Follow the instructions for the required schema."


def json_mode_input(items: list[TResponseInputItem]) -> list[TResponseInputItem]:
    """为 JSON mode 增加协议所需 developer 前缀，保留原始用户问题与完整本地历史。"""

    # 返回新列表，不修改 Runner 保存的上下文，下一回合不会重复累计协议前缀。
    return [{"role": "developer", "content": JSON_MODE_DEVELOPER_INSTRUCTION}, *items]


class ChatGPTAuth(Protocol):
    """认证只向请求边界提供短期凭证，不进入 Settings 或 Trace。"""

    async def access_token(self) -> str: ...
    async def list_models(self) -> list[dict[str, object]]: ...
    async def aclose(self) -> None: ...
    def redact(self, message: str) -> str: ...


class ChatGPTResponsesError(CompletionProviderError):
    """携带已经脱敏的 Provider 根因和传输事实。"""

    def __init__(self, code: str, message: str, observation: Mapping[str, object]) -> None:
        self.code = code
        self.safe_observation = dict(observation)
        # 官方额度/资格/权限错误需要暂停新推理，不能让 Router/Planner 继续调用 Runtime。
        stops = (
            observation.get("status_code") in {401, 403, 429}
            or code
            in {
                "quota_exceeded",
                "insufficient_quota",
                "usage_limit_reached",
                "not_eligible",
                "eligibility_error",
                "subscription_required",
                "MODEL_NOT_AUTHORIZED",
                "subscription_sharing_usage_limit_exceeded",
                "subscription_sharing_usage_unavailable",
                "subscription_sharing_user_not_eligible",
                "chatpass_v2_scope_not_authorized",
                "AUTH_RESPONSE",
                "AUTH_REQUIRED",
                "AUTH_SCOPE",
                "AUTH_OIDC",
                "AUTH_IDENTITY",
                "AUTH_STORAGE",
            }
            or code in TERMINAL_REFRESH_ERRORS
            or observation.get("oauth_code") in TERMINAL_REFRESH_ERRORS
        )
        super().__init__(f"{code}: {message}", stops_inference=stops)


def project_response_usage(response: Response) -> dict[str, int | float] | None:
    """只投影 Provider 实际返回的 usage，不把 unknown 填成零。"""

    if response.usage is None:
        return None
    usage = response.usage
    return {
        "requests": 1,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "cached_input_tokens": usage.input_tokens_details.cached_tokens,
        "reasoning_tokens": usage.output_tokens_details.reasoning_tokens,
    }


class ChatGPTResponsesModel(Model):
    """最小 SDK Model：复用官方工具转换，只控制 HTTP/SSE 和终态。"""

    def __init__(
        self,
        model: str,
        auth: ChatGPTAuth,
        *,
        client: httpx.AsyncClient | None = None,
        observer: Callable[[Mapping[str, object]], None] | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        # Model 也可直接注入 SDK；同一能力表保证该入口不会绕过配置校验。
        if reasoning_effort is not None and reasoning_effort not in CHATGPT_REASONING_EFFORTS.get(
            ("chatgpt-plan", model), frozenset(),
        ):
            raise ValueError("unsupported chatgpt reasoning effort for the configured model")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.auth = auth
        # HTTP client 无隐式重试；取消、超时和额度不足都显式交给上层。
        self._client = client or httpx.AsyncClient(timeout=60.0)
        self._observer = observer
        self._validated = False
        self._validation_lock = asyncio.Lock()

    async def _validate_model(self) -> None:
        """首个请求前使用实际账号目录校验模型；并发首调用只读取一次目录。"""

        async with self._validation_lock:
            if self._validated:
                return
            # 模型名称完全来自账号目录，不能按 GPT 名字猜测授权。
            catalog = await self.auth.list_models()
            if self.model not in {item.get("slug") for item in catalog}:
                raise ChatGPTResponsesError(
                    "MODEL_NOT_AUTHORIZED",
                    "configured model is absent from the account catalog",
                    {"model": self.model, "stream_completed": False},
                )
            self._validated = True

    def request_projection(self) -> dict[str, object]:
        """公开的实际请求参数；不包括凭证和模型上下文正文。"""

        return {
            "provider": "chatgpt-plan",
            "model": self.model,
            "endpoint": RESPONSES_ENDPOINT,
            "store": False,
            "stream": True,
            "text": {"format": {"type": "json_object"}},
            "reasoning": self._reasoning_parameters(),
            "include": ["reasoning.encrypted_content"],
        }

    def _reasoning_parameters(self) -> dict[str, str]:
        """实际 payload 与安全投影同源，Runtime/Router/Planner 不各自设档。"""

        parameters = {"summary": "auto"}
        # 只在显式配置时发送 effort，不更改未配置账号的历史请求。
        if self.reasoning_effort is not None:
            parameters["effort"] = self.reasoning_effort
        return parameters

    def _payload(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
    ) -> dict[str, Any]:
        """从允许字段构造请求，禁止 extra_args 把旧 Chat Completions 参数带入。"""

        # ItemHelpers 保留本地历史、call_id、namespace 和 encrypted reasoning replay。
        items = ItemHelpers.input_to_new_input_list(input)
        # SDK Converter 负责 namespace 结构；Runner 使用同一工具身份完成 dispatch。
        converted = Converter.convert_tools(tools, handoffs, model=self.model)
        if any(tool.get("type") != "namespace" for tool in converted.tools):
            raise ChatGPTResponsesError("UNSUPPORTED_TOOL", "function tools must use tool_namespace", {})
        payload: dict[str, Any] = {
            "model": self.model,
            "input": items,
            "store": False,
            "stream": True,
            "include": ["reasoning.encrypted_content"],
            "reasoning": self._reasoning_parameters(),
            "text": {"format": {"type": "json_object"}},
        }
        if system_instructions:
            payload["instructions"] = system_instructions
        if output_schema is not None and not output_schema.is_plain_text():
            payload["text"] = Converter.get_response_format(output_schema)
        if payload["text"]["format"]["type"] == "json_object":
            # 所有 JSON object 请求统一满足公开 API 契约，不能修改 user query 来规避校验。
            payload["input"] = json_mode_input(items)
        if converted.tools:
            payload["tools"] = converted.tools
        if model_settings.tool_choice is not None:
            payload["tool_choice"] = Converter.convert_tool_choice(model_settings.tool_choice, tools=tools)
        if model_settings.parallel_tool_calls is not None:
            payload["parallel_tool_calls"] = model_settings.parallel_tool_calls
        return payload

    def _error(
        self, code: str, message: str, observation: dict[str, object], body: str | None = None
    ) -> ChatGPTResponsesError:
        """认证模块统一脱敏；保留状态、request ID 和有界错误正文。"""

        code = self.auth.redact(code)
        observation["error_code"] = code
        if body is not None:
            observation["body"] = self.auth.redact(body)[:4000]
        return ChatGPTResponsesError(code, self.auth.redact(message), observation)

    async def _stream(
        self,
        payload: dict[str, Any],
        observer: Callable[[Mapping[str, object]], None] | None = None,
    ) -> AsyncGenerator[ResponseStreamEvent, None]:
        """解析 SSE；只有明确 response.completed 才算成功，任何出口都关闭连接。"""

        # 名称只来自本次流已验证的 added item，不能按工具列表或字符串规则猜测。
        function_names: dict[str, str] = {}
        normalizations = {"function_call_arguments_done_name": 0}
        observation: dict[str, object] = {
            "event_normalizations": normalizations,
            "transport": "responses_stream",
            "provider": "chatgpt-plan",
            "model": self.model,
            "status_code": None,
            "request_id": None,
            "response_id": None,
            "terminal_event": None,
            "stream_completed": False,
            "chunk_count": 0,
            "request": self.request_projection(),
        }
        try:
            await self._validate_model()
            # access token 在真正发送前读取，轮换后的 token 不缓存进 runtime settings。
            access_token = await self.auth.access_token()
            async with self._client.stream(
                "POST",
                RESPONSES_ENDPOINT,
                json=payload,
                headers={"Authorization": f"Bearer {access_token}", "Accept": "text/event-stream"},
            ) as response:
                observation["status_code"] = response.status_code
                observation["request_id"] = response.headers.get("x-request-id")
                if response.is_error:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    # Provider error code 是诊断事实；不按状态猜测欠费或认证失败。
                    try:
                        error_body = json.loads(body)
                    except ValueError:
                        error_body = None
                    raw_error = error_body.get("error") if isinstance(error_body, Mapping) else None
                    error = raw_error if isinstance(raw_error, Mapping) else {}
                    code = str(error.get("code") or f"HTTP_{response.status_code}")
                    raise self._error(code, str(error.get("message") or response.reason_phrase), observation, body)
                content_type = response.headers.get("content-type")
                # 真实订阅响应可能省略 Content-Type；显式非 SSE 才拒绝，缺失仍校验事件与终态。
                if content_type is not None and "text/event-stream" not in content_type:
                    raise self._error("INVALID_STREAM", "expected text/event-stream response", observation)
                # SSE 允许多行 data，空行才表示一个完整事件；注释和 event/id 行不参与 JSON。
                data_lines: list[str] = []
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip(" "))
                    if line != "" or not data_lines:
                        continue
                    data = "\n".join(data_lines)
                    data_lines.clear()
                    if data == "[DONE]":
                        break
                    observation["chunk_count"] = cast(int, observation["chunk_count"]) + 1
                    try:
                        raw = json.loads(data)
                        event_type = raw.get("type")
                        observation["terminal_event"] = (
                            event_type
                            if event_type
                            in {
                                "response.completed",
                                "response.failed",
                                "response.incomplete",
                                "error",
                                "response.error",
                            }
                            else observation["terminal_event"]
                        )
                        if event_type in {"response.failed", "response.incomplete", "error", "response.error"}:
                            terminal = raw.get("response", raw)
                            # failed Response 的 output 是模型内部 replay 数据，永远不能当作错误详情。
                            raw_error = (
                                terminal.get("error") or terminal.get("incomplete_details")
                                if event_type in {"response.failed", "response.incomplete"}
                                else raw
                            )
                            error = raw_error if isinstance(raw_error, Mapping) else {}
                            code = str(error.get("code") or error.get("reason") or event_type)
                            observation["response_id"] = terminal.get("id")
                            # 终态正文只保留错误字段，不能把 encrypted reasoning 输出写进 Trace。
                            body = json.dumps({"error": error, "status": terminal.get("status")})
                            raise self._error(code, str(error.get("message") or event_type), observation, body)
                        if event_type == "response.function_call_arguments.done" and "name" not in raw:
                            # 真实官方 SSE 的 done 只有 item_id/arguments；SDK 0.22.0 schema 额外要求 name。
                            name = function_names.get(raw.get("item_id"))
                            if name is None:
                                observation["event_type"] = event_type
                                raise self._error(
                                    "UNASSOCIATED_TOOL_CALL",
                                    "function arguments done has no prior function item",
                                    observation,
                                )
                            # 补充同一 item 的真实函数名，原 arguments、call_id 与用户输入保持原样。
                            raw = {**raw, "name": name}
                            normalizations["function_call_arguments_done_name"] += 1
                        event = _EVENT_ADAPTER.validate_python(raw)
                        if event_type == "response.output_item.added" and event.item.type == "function_call":
                            # added item 完成 schema 验证后才建立关联；不同并行函数使用不同 item_id。
                            function_names[event.item.id] = event.item.name
                    except ValidationError as exc:
                        # 只捕获字段级 schema 诊断，排除原始 input/context，不能复制 encrypted/private 数据。
                        observation["event_type"] = event_type
                        field_errors = exc.errors(include_input=False, include_context=False, include_url=False)
                        observation["validation_errors"] = [
                            {
                                "loc": list(error["loc"]),
                                "type": error["type"],
                                "msg": self.auth.redact(error["msg"])[:500],
                            }
                            for error in field_errors[:8]
                        ]
                        raise self._error(
                            "MALFORMED_STREAM",
                            f"invalid Responses SSE event: {event_type} schema validation failed",
                            observation,
                        ) from None
                    except (ValueError, AttributeError) as exc:
                        raise self._error(
                            "MALFORMED_STREAM", f"invalid Responses SSE event: {type(exc).__name__}", observation
                        ) from None
                    if event_type == "response.completed":
                        final = event.response
                        # SDK Runner 从 terminal Response 读取 request ID，与 transport 使用同一事实。
                        object.__setattr__(final, "_request_id", observation["request_id"])
                        if final.status != "completed":
                            raise self._error(
                                "INVALID_TERMINAL", "completed event has a non-completed response", observation
                            )
                        observation.update(
                            {
                                "stream_completed": True,
                                "response_id": final.id,
                                "actual_model": final.model,
                                "finish_reason": "stop",
                                "usage": project_response_usage(final),
                            }
                        )
                        # 在把 completed 交给 Runner 前发布事实，避免 on_llm_end 早于诊断记录。
                        if observer is not None:
                            observer(dict(observation))
                        if self._observer is not None:
                            self._observer(dict(observation))
                        yield event
                        return
                    # 隐藏 reasoning 文本不能经 Runtime 的公开 thinking 事件进入 Trace。
                    if not str(event_type).startswith("response.reasoning_text."):
                        yield event
                raise self._error("STREAM_INTERRUPTED", "stream ended without response.completed", observation)
        except ChatGPTResponsesError as exc:
            observation.update(exc.safe_observation)
            observation["error_code"] = exc.code
            exc.safe_observation = dict(observation)
            raise
        except asyncio.CancelledError:
            observation["error_code"] = "REQUEST_CANCELLED"
            raise
        except ChatGPTAuthError as exc:
            # 认证错误也保留已脱敏的实际 HTTP/OAuth 根因，不能伪装成未知网络失败。
            observation.update(
                {"status_code": exc.status_code, "request_id": exc.request_id, "oauth_code": exc.oauth_code}
            )
            raise self._error(exc.code, str(exc), observation) from None
        except Exception as exc:
            # 某些 transport 异常正文为空，仍保留真实类型供主链路定位，不能变成空错误。
            observation["exception_type"] = type(exc).__name__
            code = "REQUEST_TIMEOUT" if isinstance(exc, httpx.TimeoutException) else "PROVIDER_ERROR"
            raise self._error(code, f"{type(exc).__name__}: {exc}", observation) from None
        finally:
            # 完成已在 yield 前上报；失败/取消也必须保留实际观察到的 transport facts。
            if not observation["stream_completed"]:
                if observer is not None:
                    observer(dict(observation))
                if self._observer is not None:
                    self._observer(dict(observation))

    async def stream_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: ResponsePromptParam | None,
    ) -> AsyncIterator[ResponseStreamEvent]:
        """忽略服务器历史 ID，始终完整重放 Runner 给出的本地上下文。"""

        payload = self._payload(system_instructions, input, model_settings, tools, output_schema, handoffs)
        # Runner 可能在某个 delta 后主动关闭生成器；显式关闭内部 HTTP 流，避免等待 GC。
        async with aclosing(self._stream(payload)) as events:
            async for event in events:
                yield event

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: ResponsePromptParam | None,
    ) -> ModelResponse:
        """非流式 Runner 入口也消费受限 SSE，不发送 stream=false。"""

        payload = self._payload(system_instructions, input, model_settings, tools, output_schema, handoffs)
        response, observation = await self.collect_response(payload)
        usage = response.usage
        sdk_usage = Usage(requests=1)
        if usage is not None:
            # SDK 接口必须使用 Usage，但数值和明细直接来自 Provider 的实际报告。
            sdk_usage = Usage(
                requests=1,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
                input_tokens_details=usage.input_tokens_details,
                output_tokens_details=usage.output_tokens_details,
            )
        return ModelResponse(
            output=response.output,
            response_id=response.id,
            request_id=cast(str | None, observation.get("request_id")),
            usage=sdk_usage,
        )

    async def collect_response(self, payload: dict[str, Any]) -> tuple[Response, dict[str, object]]:
        """Completion 与 Runtime 共用同一 SSE 边界，收集公开输出和传输元数据。"""

        observations: list[Mapping[str, object]] = []
        final: Response | None = None
        async for event in self._stream(payload, observations.append):
            if event.type == "response.completed":
                final = event.response
        if final is None:
            raise ChatGPTResponsesError("STREAM_INTERRUPTED", "missing completed response", {})
        return final, dict(observations[-1])

    async def close(self) -> None:
        """关闭推理与认证连接；凭证持久化由认证模块负责。"""

        await self._client.aclose()
        await self.auth.aclose()
