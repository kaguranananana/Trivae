"""One-shot JSON completions for independent evaluators, using the configured provider."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from agents.model_settings import ModelSettings as AgentModelSettings
from openai import AsyncOpenAI, OpenAIError

from trivae.auth import ChatGPTAuthManager
from trivae.config.model_capabilities import resolve_reasoning_effort
from trivae.config.settings import ModelSettings
from trivae.query.runtime.chatgpt_responses import (
    ChatGPTResponsesError,
    ChatGPTResponsesModel,
    project_response_usage,
)


class ModelCompletionError(RuntimeError):
    """A sanitized one-shot completion failure with provider diagnostics."""

    def __init__(self, message: str, observation: dict[str, object]) -> None:
        super().__init__(message)
        self.observation = observation


@dataclass(frozen=True)
class ModelCompletion:
    """Completed JSON text plus the observed provider response and safe request settings."""

    content: str
    provider: str
    model: str
    request: dict[str, object]
    finish_reason: str | None
    usage: dict[str, object] | None
    latency_ms: float
    transport: dict[str, object] | None = None
    request_id: str | None = None
    response_id: str | None = None


async def complete_json(
    settings: ModelSettings,
    *,
    system_prompt: str,
    user_prompt: str,
    session_id: str,
) -> ModelCompletion:
    """Request one JSON object; subscription models use OAuth and the official Responses stream."""

    if settings.provider == "chatgpt-plan":
        return await _complete_chatgpt(settings, system_prompt=system_prompt, user_prompt=user_prompt)
    return await _complete_api_key(
        settings,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        session_id=session_id,
    )


async def _complete_chatgpt(settings: ModelSettings, *, system_prompt: str, user_prompt: str) -> ModelCompletion:
    auth = ChatGPTAuthManager()
    model = ChatGPTResponsesModel(
        model=settings.model_name,
        auth=auth,
        reasoning_effort=settings.chatgpt_reasoning_effort,
    )
    request = model.request_projection()
    payload = model._payload(
        system_prompt,
        [{"role": "user", "content": user_prompt}],
        AgentModelSettings(),
        [],
        None,
        [],
    )
    started = perf_counter()
    try:
        response, transport = await model.collect_response(payload)
    except ChatGPTResponsesError:
        raise
    finally:
        await model.close()
    content = response.output_text
    if not isinstance(content, str) or not content.strip():
        raise ModelCompletionError(
            "ChatGPT Plan Judge returned no JSON content",
            {
                "provider": settings.provider,
                "model": settings.model_name,
                "response_id": response.id,
                "status": response.status,
                "transport": _safe_transport(transport),
            },
        )
    usage = project_response_usage(response)
    return ModelCompletion(
        content=content,
        provider=settings.provider,
        model=response.model,
        request=request,
        finish_reason=response.status,
        usage=None if usage is None else dict(usage),
        latency_ms=(perf_counter() - started) * 1000,
        transport=_safe_transport(transport),
        request_id=_optional_string(transport.get("request_id")),
        response_id=response.id,
    )


async def _complete_api_key(
    settings: ModelSettings,
    *,
    system_prompt: str,
    user_prompt: str,
    session_id: str,
) -> ModelCompletion:
    reasoning_effort = resolve_reasoning_effort(provider=settings.provider, model_name=settings.model_name)
    headers = (
        {"x-opencode-session": session_id, "User-Agent": "trivae/0.1.0"}
        if settings.provider == "opencode-go"
        else None
    )
    request: dict[str, object] = {
        "provider": settings.provider,
        "model": settings.model_name,
        "endpoint": settings.base_url.rstrip("/") + "/chat/completions",
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": settings.max_output_tokens,
        "reasoning_effort": reasoning_effort,
    }
    started = perf_counter()
    async with AsyncOpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
        default_headers=headers,
        max_retries=0,
    ) as client:
        try:
            response = await client.chat.completions.create(
                model=settings.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=settings.max_output_tokens,
                reasoning_effort=reasoning_effort,
            )
        except OpenAIError as exc:
            message = str(exc)
            if settings.api_key:
                message = message.replace(settings.api_key, "[REDACTED]")
            observation = {
                "provider": settings.provider,
                "model": settings.model_name,
                "error_type": type(exc).__name__,
                "error_message": message,
                "status_code": getattr(exc, "status_code", None),
                "request_id": getattr(exc, "request_id", None),
            }
            raise ModelCompletionError(f"{settings.provider} Judge request failed: {type(exc).__name__}",
                                       observation) from exc

    choices = getattr(response, "choices", None)
    choice = choices[0] if isinstance(choices, (list, tuple)) and choices else None
    response_message = None if choice is None else getattr(choice, "message", None)
    content = None if response_message is None else getattr(response_message, "content", None)
    if not isinstance(content, str) or not content.strip():
        raise ModelCompletionError(
            "API-key Judge response has no JSON content",
            {
                "provider": settings.provider,
                "model": getattr(response, "model", settings.model_name),
                "finish_reason": None if choice is None else getattr(choice, "finish_reason", None),
            },
        )
    usage_value = getattr(response, "usage", None)
    usage: dict[str, object] | None = None
    if usage_value is not None:
        dump = getattr(usage_value, "model_dump", None)
        if callable(dump):
            value = dump(exclude_none=True)
            if isinstance(value, dict):
                usage = value
    return ModelCompletion(
        content=content,
        provider=settings.provider,
        model=getattr(response, "model", settings.model_name),
        request=request,
        finish_reason=_optional_string(getattr(choice, "finish_reason", None)),
        usage=usage,
        latency_ms=(perf_counter() - started) * 1000,
        request_id=_optional_string(getattr(response, "_request_id", None)),
    )


def completion_record(completion: ModelCompletion) -> dict[str, object]:
    """Project the saved response fields without any authorization header or credential."""

    return {
        "provider": completion.provider,
        "model": completion.model,
        "request": completion.request,
        "finish_reason": completion.finish_reason,
        "usage": completion.usage,
        "latency_ms": completion.latency_ms,
        "request_id": completion.request_id,
        "response_id": completion.response_id,
        "transport": completion.transport,
        "content": completion.content,
    }


def _safe_transport(value: dict[str, object]) -> dict[str, object]:
    """Keep only non-secret transport facts from the existing OAuth Responses boundary."""

    allowed = {"status_code", "request_id", "response_id", "terminal_event", "stream_completed", "chunk_count"}
    return {key: item for key, item in value.items() if key in allowed}


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None
