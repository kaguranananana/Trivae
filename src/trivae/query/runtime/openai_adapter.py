"""OpenAI Agents SDK 的 DeepSeek Chat Completions 运行时适配器。"""

from __future__ import annotations

from typing import Any

from agents import Agent, MaxTurnsExceeded, Runner, set_tracing_disabled
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from trivae.capabilities.registry import CapabilityRegistry
from trivae.config.settings import DeepSeekSettings, load_settings
from trivae.query.runtime.contracts import (
    AgentRunRequest,
    AgentRuntime,
    RuntimeContext,
    RuntimeErrorInfo,
    RuntimeResult,
)
from trivae.query.runtime.openai_tools import SearchMessagesSDKToolAdapter
from trivae.query.runtime.prompt import SYSTEM_PROMPT


class OpenAIAgentsRuntimeAdapter(AgentRuntime):
    """把 Trivae Runtime contract 接到 SDK Agent/Runner，且只调用 Runner 一次。"""

    def __init__(
        self,
        capability_registry: CapabilityRegistry | None = None,
        *,
        model: Any | None = None,
        settings: DeepSeekSettings | None = None,
        provider_name: str | None = None,
        model_name: str | None = None,
        max_turns: int | None = None,
    ) -> None:
        self.capability_registry = capability_registry
        if model is None:
            # 只有真实 runtime 被显式构造时才读取密钥并创建外部 client。
            resolved_settings = settings or load_settings()
            self._model = self._build_deepseek_model(resolved_settings)
            self._provider_name = resolved_settings.provider
            self._model_name = resolved_settings.model_name
            self._secret = resolved_settings.api_key
            configured_max_turns = resolved_settings.max_turns
        else:
            # ScriptedModel 等测试模型通过注入进入，不需要 provider key 或网络。
            self._model = model
            self._provider_name = provider_name or (settings.provider if settings is not None else "injected")
            self._model_name = model_name or (settings.model_name if settings is not None else "injected-model")
            self._secret = settings.api_key if settings is not None else ""
            configured_max_turns = settings.max_turns if settings is not None else 8

        self.max_turns = configured_max_turns if max_turns is None else max_turns
        if isinstance(self.max_turns, bool) or not isinstance(self.max_turns, int) or self.max_turns <= 0:
            raise ValueError("max_turns must be a positive integer")

    @staticmethod
    def _build_deepseek_model(settings: DeepSeekSettings) -> Any:
        """构造 DeepSeek 专用 Chat Completions model，不切换 provider 或 endpoint。"""

        # M4a 没有 Trivae Trace backend；显式关闭 SDK hosted tracing，避免未配置 key 的副作用。
        set_tracing_disabled(True)
        client = AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url)
        return OpenAIChatCompletionsModel(
            model=settings.model_name,
            openai_client=client,
        )

    async def run(self, request: AgentRunRequest) -> RuntimeResult:
        """执行单次 bounded SDK run，并将 SDK terminal state 投影成 Trivae result。"""

        try:
            context = self._build_context(request)
            agent = self._build_agent(request, context)
            # SDK Runner 独占通用 model/tool loop；适配器不再手写第二层 while loop。
            set_tracing_disabled(True)
            result = await Runner.run(
                agent,
                request.query,
                context=context,
                max_turns=self.max_turns,
            )
        except MaxTurnsExceeded as exc:
            return RuntimeResult(
                final_answer=None,
                provider=self._provider_name,
                model=self._model_name,
                termination="max_turns_exceeded",
                tool_calls=tuple(context.tool_calls) if "context" in locals() else (),
                error=RuntimeErrorInfo("MAX_TURNS_EXCEEDED", str(exc)),
                usage=None,
            )
        except Exception as exc:
            # 失败仍返回 terminal error；消息经密钥替换后保留根因类型和诊断文本。
            context_calls = tuple(context.tool_calls) if "context" in locals() else ()
            return RuntimeResult(
                final_answer=None,
                provider=self._provider_name,
                model=self._model_name,
                termination="failed",
                tool_calls=context_calls,
                error=RuntimeErrorInfo(
                    "RUNTIME_ERROR",
                    self._redact(f"{type(exc).__name__}: {exc}"),
                ),
                usage=None,
            )

        if not isinstance(result.final_output, str):
            return RuntimeResult(
                final_answer=None,
                provider=self._provider_name,
                model=self._model_name,
                termination="failed",
                tool_calls=tuple(context.tool_calls),
                error=RuntimeErrorInfo("INVALID_FINAL_OUTPUT", "SDK final output was not text"),
                usage=self._project_usage(result),
            )

        return RuntimeResult(
            final_answer=result.final_output,
            provider=self._provider_name,
            model=self._model_name,
            termination="completed",
            tool_calls=tuple(context.tool_calls),
            usage=self._project_usage(result),
        )

    def _build_context(self, request: AgentRunRequest) -> RuntimeContext:
        """把 trusted registry/scope 放入 SDK local context，而不是 prompt/tool 参数。"""

        if self.capability_registry is None:
            raise RuntimeError("capability_registry is required to run the Trivae agent")
        registered = set(self.capability_registry.names())
        unknown = set(request.available_capabilities) - registered
        if unknown:
            raise ValueError(f"requested capability is not registered: {sorted(unknown)!r}")
        return RuntimeContext(
            scope=request.scope,
            capability_registry=self.capability_registry,
            available_capabilities=request.available_capabilities,
        )

    def _build_agent(self, request: AgentRunRequest, context: RuntimeContext) -> Any:
        """按 request 白名单注册工具；M4a 只允许现有 search_messages。"""

        tools: list[Any] = []
        if "search_messages" in context.available_capabilities:
            tools.append(SearchMessagesSDKToolAdapter(context.capability_registry).as_sdk_tool())
        return Agent(
            name="Trivae Agent",
            instructions=SYSTEM_PROMPT,
            model=self._model,
            tools=tools,
        )

    def _redact(self, message: str) -> str:
        """从 terminal error 投影中移除 provider key，防止 secret 泄漏。"""

        return message.replace(self._secret, "[REDACTED]") if self._secret else message

    @staticmethod
    def _project_usage(result: Any) -> dict[str, int | float] | None:
        """将 SDK usage 聚合为普通数字；SDK usage 类型不越过 runtime boundary。"""

        if not result.raw_responses:
            return None
        totals: dict[str, int | float] = {}
        for response in result.raw_responses:
            usage = response.usage
            for field in ("requests", "input_tokens", "output_tokens", "total_tokens"):
                value = getattr(usage, field, None)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    totals[field] = totals.get(field, 0) + value
        return totals or None
