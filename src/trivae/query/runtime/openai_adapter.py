"""OpenAI Agents SDK 的 DeepSeek Chat Completions 流式运行时适配器。"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from agents import Agent, MaxTurnsExceeded, RunConfig, RunHooks, Runner, set_tracing_disabled
from agents.model_settings import ModelSettings
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from trivae.capabilities.registry import CapabilityRegistry
from trivae.config.settings import DeepSeekSettings, load_settings
from trivae.query.runtime.contracts import (
    AgentRunRequest,
    AgentRuntime,
    RuntimeContext,
    RuntimeErrorInfo,
    RuntimeEvent,
    RuntimeResult,
    RuntimeToolCall,
)
from trivae.query.runtime.openai_tools import SearchMessagesSDKToolAdapter
from trivae.query.runtime.prompt import SYSTEM_PROMPT

RuntimeEventType = Literal[
    "run_started",
    "turn_started",
    "content_delta",
    "tool_started",
    "tool_completed",
    "turn_completed",
    "usage_update",
    "finalizing",
    "completed",
    "failed",
    "aborted",
]

# DeepSeek 的 Chat Completions JSON mode 只约束最终文本形状，不改变 Trivae 的
# AnswerArtifact、Citation 或 current-run provenance contract。
_FINAL_SYNTHESIS_RESPONSE_FORMAT = {"type": "json_object"}


@dataclass
class _PendingEvent:
    """SDK hook 不能直接 yield，因此先在本地队列保存安全事件。"""

    type: RuntimeEventType
    text: str | None = None
    tool_call: RuntimeToolCall | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_round: int | None = None
    usage: dict[str, int | float] | None = None


@dataclass
class _RunState:
    """一次执行的可变状态；不与下一次 run 共享。"""

    provider: str
    model: str
    pending: list[_PendingEvent] = field(default_factory=list)
    sequence: int = 0
    turn: int = 0
    expected_tool_results: int = 0
    completed_tool_results: int = 0
    tool_rounds: int = 0
    finalizing: bool = False
    aborted: bool = False
    settled: bool = False


class _RuntimeHooks(RunHooks[RuntimeContext]):
    """把 SDK lifecycle hook 转成不含 SDK payload 的内部事件。"""

    def __init__(self, state: _RunState, max_tool_rounds: int) -> None:
        super().__init__()
        self._state = state
        self._max_tool_rounds = max_tool_rounds

    async def on_llm_start(self, context: Any, agent: Any, system_prompt: str | None, input_items: list[Any]) -> None:
        """每次模型调用开始时建立一个新的 tool-result 计数窗口。"""

        self._state.turn += 1
        self._state.expected_tool_results = 0
        self._state.completed_tool_results = 0
        runtime_context = getattr(context, "context", None)
        if isinstance(runtime_context, RuntimeContext):
            # 先固定本 turn 的编号，避免并发/顺序执行的多个 tool call 被误计成不同 round。
            runtime_context.current_tool_round = self._state.tool_rounds + 1
            # 新模型轮次开始时清掉缺少 provider call ID 的旧 local mapping。
            runtime_context.current_tool_call_id = None
        # 达到产品预算后，下一次模型调用必须保持无工具状态。
        if self._state.finalizing:
            agent.tools.clear()
        self._state.pending.append(
            _PendingEvent("turn_started", tool_round=self._state.tool_rounds + 1)
        )

    async def on_llm_end(self, context: Any, agent: Any, response: Any) -> None:
        """从模型输出只读取 function-call 数量，决定何时结束本轮事件。"""

        output = getattr(response, "output", ())
        function_call_count = sum(
            1 for item in output if getattr(item, "type", None) == "function_call"
        )
        self._state.expected_tool_results = function_call_count
        usage = self._project_model_usage(response)
        if usage is not None:
            self._state.pending.append(_PendingEvent("usage_update", usage=usage))
        if function_call_count == 0:
            self._state.pending.append(
                _PendingEvent("turn_completed", tool_round=self._state.tool_rounds)
            )

    @staticmethod
    def _project_model_usage(response: Any) -> dict[str, int | float] | None:
        """将 hook 中可得的 usage 变成普通数字，不传播 SDK Usage 对象。"""

        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        projected: dict[str, int | float] = {}
        for field_name in ("requests", "input_tokens", "output_tokens", "total_tokens"):
            value = getattr(usage, field_name, None)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                projected[field_name] = value
        return projected or None

    async def on_tool_start(self, context: Any, agent: Any, tool: Any) -> None:
        """tool 开始事件只保留名称和 SDK 提供的 call id。"""

        runtime_context = getattr(context, "context", None)
        if not isinstance(runtime_context, RuntimeContext):
            raise RuntimeError("SDK tool start did not contain Trivae RuntimeContext")
        tool_name = getattr(context, "tool_name", None) or getattr(tool, "name", None)
        provider_tool_call_id = getattr(context, "tool_call_id", None)
        if not isinstance(tool_name, str) or not tool_name:
            raise RuntimeError("SDK tool start did not provide a stable tool name")
        if not isinstance(provider_tool_call_id, str) or not provider_tool_call_id:
            provider_tool_call_id = None
        # hook 只在 local context 建立 provider→Trivae ID 映射，不把 provider ID 向上暴露。
        tool_call_id = runtime_context.allocate_tool_call_id(provider_tool_call_id)
        self._state.pending.append(
            _PendingEvent(
                "tool_started",
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                tool_round=self._state.tool_rounds + 1,
            )
        )

    async def on_tool_end(self, context: Any, agent: Any, tool: Any, result: object) -> None:
        """tool 返回后只计一次 round，并在预算到达时切换 finalization。"""

        runtime_context = getattr(context, "context", None)
        if not isinstance(runtime_context, RuntimeContext):
            raise RuntimeError("SDK tool context did not contain Trivae RuntimeContext")
        tool_name = getattr(context, "tool_name", None) or getattr(tool, "name", None)
        provider_tool_call_id = getattr(context, "tool_call_id", None)
        if not isinstance(tool_name, str) or not tool_name:
            raise RuntimeError("SDK tool end did not provide a stable tool name")
        if not isinstance(provider_tool_call_id, str) or not provider_tool_call_id:
            provider_tool_call_id = None
        # 工具 adapter 已经记录 Trivae-owned call；这里用同一映射找到它。
        tool_call_id = runtime_context.resolve_tool_call_id(provider_tool_call_id)

        tool_call = self._find_tool_call(runtime_context.tool_calls, tool_call_id, tool_name)
        if tool_call is None:
            # adapter contract 应该已经记录调用；缺失时显式失败而不是伪造成功状态。
            raise RuntimeError("SDK tool completed without a Trivae tool call record")

        self._state.completed_tool_results += 1
        first_result_in_turn = self._state.completed_tool_results == 1
        if first_result_in_turn:
            # 同一模型响应中的多个 tool call 只消耗一个产品 tool round。
            self._state.tool_rounds += 1
            runtime_context.tool_rounds = self._state.tool_rounds
        self._state.pending.append(
            _PendingEvent(
                "tool_completed",
                tool_call=tool_call,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                tool_round=self._state.tool_rounds,
            )
        )

        if (
            first_result_in_turn
            and self._state.tool_rounds >= self._max_tool_rounds
            and not self._state.finalizing
            and not self._state.aborted
        ):
            self._state.finalizing = True
            # 当前 response 中已经产生的 calls 会完成；后续模型回合不再暴露工具。
            agent.tools.clear()

        if self._state.completed_tool_results >= self._state.expected_tool_results:
            if self._state.finalizing:
                # 等同一模型回合的所有 tool calls 都完成后再广播 finalizing，事件顺序更准确。
                self._state.pending.append(
                    _PendingEvent("finalizing", tool_round=self._state.tool_rounds)
                )
            self._state.pending.append(
                _PendingEvent("turn_completed", tool_round=self._state.tool_rounds)
            )

    @staticmethod
    def _find_tool_call(
        calls: list[RuntimeToolCall],
        tool_call_id: str | None,
        tool_name: str,
    ) -> RuntimeToolCall | None:
        """按 call id 找到 adapter 已记录的安全投影。"""

        for call in reversed(calls):
            if call.name == tool_name and (tool_call_id is None or call.tool_call_id == tool_call_id):
                return call
        return None


class OpenAIAgentsRuntimeAdapter(AgentRuntime):
    """把 Trivae Runtime contract 接到 SDK 的唯一 streamed Agent loop。"""

    def __init__(
        self,
        capability_registry: CapabilityRegistry | None = None,
        *,
        model: Any | None = None,
        settings: DeepSeekSettings | None = None,
        provider_name: str | None = None,
        model_name: str | None = None,
        max_turns: int | None = None,
        max_tool_rounds: int | None = None,
    ) -> None:
        """真实 provider 延迟到 runtime 构造时创建；注入模型不需要密钥。"""

        self.capability_registry = capability_registry
        self._provider_client: AsyncOpenAI | None = None
        self._closed = False
        if model is None:
            # 只有显式创建真实 runtime 时才读取密钥并创建外部 client。
            resolved_settings = settings or load_settings()
            self._model, self._provider_client = self._build_deepseek_model(resolved_settings)
            self._provider_name = resolved_settings.provider
            self._model_name = resolved_settings.model_name
            self._secret = resolved_settings.api_key
            configured_max_turns = resolved_settings.max_turns
            configured_max_tool_rounds = resolved_settings.max_tool_rounds
        else:
            # ScriptedModel 等测试模型通过注入进入，不需要 provider key 或网络。
            self._model = model
            self._provider_name = provider_name or (settings.provider if settings is not None else "injected")
            self._model_name = model_name or (settings.model_name if settings is not None else "injected-model")
            self._secret = settings.api_key if settings is not None else ""
            configured_max_turns = settings.max_turns if settings is not None else 8
            configured_max_tool_rounds = settings.max_tool_rounds if settings is not None else 3

        self.max_turns = configured_max_turns if max_turns is None else max_turns
        self.max_tool_rounds = (
            configured_max_tool_rounds if max_tool_rounds is None else max_tool_rounds
        )
        if isinstance(self.max_turns, bool) or not isinstance(self.max_turns, int) or self.max_turns <= 0:
            raise ValueError("max_turns must be a positive integer")
        if (
            isinstance(self.max_tool_rounds, bool)
            or not isinstance(self.max_tool_rounds, int)
            or self.max_tool_rounds <= 0
        ):
            raise ValueError("max_tool_rounds must be a positive integer")

    def _build_deepseek_model(self, settings: DeepSeekSettings) -> tuple[Any, AsyncOpenAI]:
        """构造并保留 DeepSeek client，供 runtime 和 aclose 共用。"""

        # M4 没有 Trivae Trace backend；显式关闭 hosted tracing，避免产生额外外部依赖。
        set_tracing_disabled(True)
        client = AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url)
        model = OpenAIChatCompletionsModel(
            model=settings.model_name,
            openai_client=client,
        )
        return model, client

    async def run(self, request: AgentRunRequest) -> RuntimeResult:
        """完整消费 stream，并返回其中最后一个 terminal result。"""

        terminal: RuntimeResult | None = None
        async for event in self.stream(request):
            if event.result is not None and event.type in {"completed", "failed", "aborted"}:
                terminal = event.result
        if terminal is None:
            raise RuntimeError("runtime stream ended without a terminal result")
        return terminal

    def stream(
        self,
        request: AgentRunRequest,
        abort_event: object | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """启动一次 streamed run；只有完整消费 SDK stream 后才产生 completed。"""

        return self._stream(request, abort_event)

    async def _stream(
        self,
        request: AgentRunRequest,
        abort_event: object | None,
    ) -> AsyncIterator[RuntimeEvent]:
        """流式主链路：SDK loop、hook queue、取消和 terminal projection。"""

        if self._closed:
            raise RuntimeError("runtime is closed; create a new runtime before running")
        state = _RunState(self._provider_name, self._model_name)
        context: RuntimeContext | None = None
        streamed_result: Any | None = None
        abort_task: asyncio.Task[None] | None = None

        yield self._event(state, "run_started")
        if self._abort_is_set(abort_event):
            state.aborted = True
            result = self._aborted_result((), 0, None, ())
            yield self._event(state, "aborted", result=result)
            return

        try:
            context = self._build_context(request, abort_event)
            agent = self._build_agent(request, context, state)
            # RunConfig 与全局 tracing 设置同时显式关闭，保证本地运行不依赖 tracing key。
            set_tracing_disabled(True)
            streamed_result = Runner.run_streamed(
                agent,
                cast(Any, self._build_input(request)),
                context=context,
                max_turns=self.max_turns,
                hooks=_RuntimeHooks(state, self.max_tool_rounds),
                run_config=RunConfig(tracing_disabled=True),
            )
            abort_task = self._start_abort_watcher(abort_event, streamed_result, state)

            async for sdk_event in streamed_result.stream_events():
                # hook 事件先进入稳定队列，按 SDK 观察到的顺序投影出去。
                for pending in self._drain_pending(state):
                    yield self._event(
                        state,
                        pending.type,
                        text=pending.text,
                        tool_call=pending.tool_call,
                        tool_name=pending.tool_name,
                        tool_call_id=pending.tool_call_id,
                        tool_round=pending.tool_round,
                        usage=pending.usage,
                    )
                if state.aborted:
                    continue
                delta = self._text_delta(sdk_event)
                if delta:
                    yield self._event(state, "content_delta", text=delta)

            # SDK stream iterator 完整结束后，再清空最后一批 hook 事件。
            for pending in self._drain_pending(state):
                if state.aborted and pending.type in {"finalizing", "turn_completed"}:
                    continue
                yield self._event(
                    state,
                    pending.type,
                    text=pending.text,
                    tool_call=pending.tool_call,
                    tool_name=pending.tool_name,
                    tool_call_id=pending.tool_call_id,
                    tool_round=pending.tool_round,
                    usage=pending.usage,
                )

            if state.aborted:
                result = self._aborted_result(
                    tuple(context.tool_calls) if context is not None else (),
                    state.tool_rounds,
                    context.run_id if context is not None else None,
                    tuple(context.tool_results) if context is not None else (),
                )
                yield self._event(state, "aborted", result=result)
                return

            final_output = getattr(streamed_result, "final_output", None)
            usage = self._project_usage(streamed_result)
            if not isinstance(final_output, str):
                result = self._failed_result(
                    context,
                    state,
                    "INVALID_FINAL_OUTPUT",
                    "SDK final output was not text",
                    diagnostic_type="invalid_final_output",
                    usage=usage,
                )
                yield self._event(state, "failed", result=result)
                return

            result = RuntimeResult(
                final_answer=final_output,
                provider=self._provider_name,
                model=self._model_name,
                termination="completed",
                tool_calls=tuple(context.tool_calls) if context is not None else (),
                usage=usage,
                tool_rounds=state.tool_rounds,
                run_id=context.run_id if context is not None else None,
                tool_results=tuple(context.tool_results) if context is not None else (),
            )
            state.settled = True
            yield self._event(state, "completed", result=result)
        except MaxTurnsExceeded as exc:
            if state.aborted:
                result = self._aborted_result(
                    tuple(context.tool_calls) if context is not None else (),
                    state.tool_rounds,
                    context.run_id if context is not None else None,
                    tuple(context.tool_results) if context is not None else (),
                )
                yield self._event(state, "aborted", result=result)
                return
            # SDK absolute backstop 是显式失败，不与产品 tool budget finalization 混淆。
            result = self._failed_result(
                context,
                state,
                "MAX_TURNS_EXCEEDED",
                "agent absolute turn limit reached",
                termination="max_turns_exceeded",
                category="absolute_backstop",
                diagnostic_type=type(exc).__name__,
                usage=self._project_usage(streamed_result),
            )
            yield self._event(state, "failed", result=result)
        except Exception as exc:
            if state.aborted:
                result = self._aborted_result(
                    tuple(context.tool_calls) if context is not None else (),
                    state.tool_rounds,
                    context.run_id if context is not None else None,
                    tuple(context.tool_results) if context is not None else (),
                )
                yield self._event(state, "aborted", result=result)
                return
            # 对外只保留稳定 code/type；原始异常正文可能含 key、请求体或 provider 敏感内容。
            result = self._failed_result(
                context,
                state,
                "RUNTIME_ERROR",
                "agent runtime execution failed",
                category="terminal",
                diagnostic_type=type(exc).__name__,
                usage=self._project_usage(streamed_result),
            )
            yield self._event(state, "failed", result=result)
        finally:
            if abort_task is not None:
                abort_task.cancel()
                await asyncio.gather(abort_task, return_exceptions=True)

    def _build_context(self, request: AgentRunRequest, abort_event: object | None = None) -> RuntimeContext:
        """把 trusted registry/scope 放入 SDK local context，而不是 prompt/tool 参数。"""

        if self.capability_registry is None:
            raise RuntimeError("capability_registry is required to run the Trivae agent")
        registered = set(self.capability_registry.names())
        unknown = set(request.available_capabilities) - registered
        if unknown:
            raise ValueError(f"requested capability is not registered: {sorted(unknown)!r}")
        return RuntimeContext(
            run_id=request.request_id or f"run-{uuid.uuid4().hex}",
            scope=request.scope,
            capability_registry=self.capability_registry,
            available_capabilities=request.available_capabilities,
            abort_event=abort_event,
        )

    def _build_agent(self, request: AgentRunRequest, context: RuntimeContext, state: _RunState) -> Any:
        """按 request 白名单注册工具，并动态追加 soft plan/final synthesis instructions。"""

        tools: list[Any] = []
        if "search_messages" in context.available_capabilities:
            tools.append(SearchMessagesSDKToolAdapter(context.capability_registry).as_sdk_tool())

        def instructions(_wrapper: Any, _agent: Any) -> str:
            # 计划只作为模型提示；finalizing 时明确要求停止调用工具并综合已有结果。
            parts = [SYSTEM_PROMPT]
            if request.plan_guidance:
                parts.append("\n" + request.plan_guidance)
            if state.finalizing:
                parts.append(
                    "\nTool budget is exhausted. Do not call any tool. Synthesize the final answer "
                    "from the evidence already returned, and state limitations plainly."
                )
            return "".join(parts)

        return Agent(
            name="Trivae Agent",
            instructions=instructions,
            model=self._model,
            # 让 OpenAI-compatible adapter 把 JSON mode 透传给 DeepSeek，避免只依赖
            # prompt 约束；最终文本仍由 M5 finalizer 解析和验证。
            model_settings=ModelSettings(
                extra_args={"response_format": _FINAL_SYNTHESIS_RESPONSE_FORMAT}
            ),
            tools=tools,
        )

    @staticmethod
    def _build_input(request: AgentRunRequest) -> list[dict[str, str]]:
        """把有限历史和 query 编译成普通消息；scope 永远不在该列表中。"""

        items = [{"role": message.role, "content": message.content} for message in request.model_context]
        items.append({"role": "user", "content": request.query})
        return items

    @staticmethod
    def _text_delta(event: Any) -> str | None:
        """只投影 Responses text delta，忽略 SDK raw tool/metadata payload。"""

        data = getattr(event, "data", None)
        if getattr(data, "type", None) != "response.output_text.delta":
            return None
        delta = getattr(data, "delta", None)
        return delta if isinstance(delta, str) and delta else None

    @staticmethod
    def _drain_pending(state: _RunState) -> list[_PendingEvent]:
        """原子取出 hook 队列，避免同一事件重复投影。"""

        pending = state.pending
        state.pending = []
        return pending

    def _event(
        self,
        state: _RunState,
        event_type: RuntimeEventType,
        *,
        text: str | None = None,
        tool_call: RuntimeToolCall | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        result: RuntimeResult | None = None,
        tool_round: int | None = None,
        usage: dict[str, int | float] | None = None,
    ) -> RuntimeEvent:
        """为每个事件分配进程内 sequence，不暴露 provider 原始 sequence。"""

        state.sequence += 1
        return RuntimeEvent(
            type=event_type,
            provider=state.provider,
            model=state.model,
            sequence=state.sequence,
            text=text,
            tool_call=tool_call,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            result=result,
            tool_round=tool_round,
            usage=usage,
        )

    def _failed_result(
        self,
        context: RuntimeContext | None,
        state: _RunState,
        code: str,
        message: str,
        *,
        termination: Literal["failed", "max_turns_exceeded"] = "failed",
        category: str | None = None,
        diagnostic_type: str | None = None,
        usage: dict[str, int | float] | None = None,
    ) -> RuntimeResult:
        """构造不含原始异常正文的 terminal result。"""

        state.settled = True
        return RuntimeResult(
            final_answer=None,
            provider=self._provider_name,
            model=self._model_name,
            termination=termination,
            tool_calls=tuple(context.tool_calls) if context is not None else (),
            error=RuntimeErrorInfo(
                code=code,
                message=message,
                category=category,
                diagnostic_type=diagnostic_type,
            ),
            usage=usage,
            tool_rounds=state.tool_rounds,
            run_id=context.run_id if context is not None else None,
            tool_results=tuple(context.tool_results) if context is not None else (),
        )

    def _aborted_result(
        self,
        tool_calls: tuple[RuntimeToolCall, ...],
        tool_rounds: int,
        run_id: str | None,
        tool_results: tuple[Any, ...],
    ) -> RuntimeResult:
        """构造 cancellation terminal result；取消不伪装成完成。"""

        return RuntimeResult(
            final_answer=None,
            provider=self._provider_name,
            model=self._model_name,
            termination="aborted",
            tool_calls=tool_calls,
            error=RuntimeErrorInfo(
                code="RUN_ABORTED",
                message="agent run was cancelled",
                category="cancellation",
                diagnostic_type="abort_event",
            ),
            tool_rounds=tool_rounds,
            run_id=run_id,
            tool_results=tool_results,
        )

    @staticmethod
    def _abort_is_set(abort_event: object | None) -> bool:
        """读取 asyncio.Event 风格信号；未提供信号时不引入隐式取消源。"""

        if abort_event is None:
            return False
        is_set = getattr(abort_event, "is_set", None)
        if not callable(is_set):
            raise TypeError("abort_event must provide is_set() and wait()")
        return bool(is_set())

    @staticmethod
    def _start_abort_watcher(
        abort_event: object | None,
        streamed_result: Any,
        state: _RunState,
    ) -> asyncio.Task[None] | None:
        """监听 cancellation event，并使用 SDK immediate cancel 结束当前 stream。"""

        if abort_event is None:
            return None
        wait = getattr(abort_event, "wait", None)
        if not callable(wait):
            raise TypeError("abort_event must provide is_set() and wait()")

        async def watch() -> None:
            await wait()
            if not state.settled:
                state.aborted = True
                streamed_result.cancel("immediate")

        return asyncio.create_task(watch())

    async def complete_text(self, prompt: str) -> str:
        """为 Router/Planner 提供同一 provider client 的纯文本 completion。"""

        if self._closed:
            raise RuntimeError("runtime is closed")
        if self._provider_client is None:
            raise RuntimeError("injected runtime model has no provider completion client")
        response = await self._provider_client.chat.completions.create(
            model=self._model_name,
            messages=[
                {"role": "system", "content": "Return only the requested JSON or concise text."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=512,
        )
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("provider completion returned no text")
        return content.strip()

    async def aclose(self) -> None:
        """幂等关闭 model 和 provider client，确保连接不会跨越 Application。"""

        if self._closed:
            return
        self._closed = True
        model_close = getattr(self._model, "close", None)
        if callable(model_close):
            value = model_close()
            if inspect.isawaitable(value):
                await value
        if self._provider_client is not None:
            await self._provider_client.close()
            self._provider_client = None

    def _redact(self, message: str) -> str:
        """保留兼容的本地 secret replacement helper，不把原始异常用于对外消息。"""

        return message.replace(self._secret, "[REDACTED]") if self._secret else message

    @staticmethod
    def _project_usage(result: Any) -> dict[str, int | float] | None:
        """将 SDK usage 聚合为普通数字；SDK usage 类型不越过 runtime boundary。"""

        if result is None or not getattr(result, "raw_responses", None):
            return None
        totals: dict[str, int | float] = {}
        for response in result.raw_responses:
            usage = getattr(response, "usage", None)
            if usage is None:
                continue
            for field_name in ("requests", "input_tokens", "output_tokens", "total_tokens"):
                value = getattr(usage, field_name, None)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    totals[field_name] = totals.get(field_name, 0) + value
        return totals or None
