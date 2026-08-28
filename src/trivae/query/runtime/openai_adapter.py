"""OpenAI Agents SDK 的 OpenAI-compatible Chat Completions 流式运行时适配器。"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass, field, replace
from time import perf_counter
from typing import Any, Literal, cast

from agents import Agent, MaxTurnsExceeded, RunConfig, RunHooks, Runner, set_tracing_disabled
from agents.model_settings import ModelSettings as SDKModelSettings
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from trivae.capabilities.registry import CapabilityRegistry
from trivae.config.model_capabilities import resolve_context_window
from trivae.config.settings import ModelSettings, load_settings
from trivae.query.completion import CompletionObservation, CompletionResult
from trivae.query.evidence import ToolResultRecord
from trivae.query.runtime.budget import (
    ToolResultBudgetConfig,
    ToolResultBudgetError,
    ToolResultBudgetExhausted,
)
from trivae.query.runtime.contracts import (
    AgentRunRequest,
    AgentRuntime,
    RuntimeContext,
    RuntimeErrorInfo,
    RuntimeEvent,
    RuntimeResult,
    RuntimeToolCall,
)
from trivae.query.runtime.openai_tools import (
    ExecuteSQLSDKToolAdapter,
    FindMembersSDKToolAdapter,
    GetMessageContextSDKToolAdapter,
    GetRecentMessagesSDKToolAdapter,
    GetSchemaSDKToolAdapter,
    LexicalSearchSDKToolAdapter,
    SearchMessagesSDKToolAdapter,
    SemanticSearchSDKToolAdapter,
)
from trivae.query.runtime.prompt import SYSTEM_PROMPT

RuntimeEventType = Literal[
    "run_started",
    "turn_started",
    "thinking_delta",
    "thinking_completed",
    "content_delta",
    "tool_started",
    "tool_completed",
    "model_output",
    "turn_completed",
    "usage_update",
    "finalizing",
    "completed",
    "failed",
    "aborted",
]

# Provider 的 Chat Completions JSON mode 只约束最终文本形状，不改变 Trivae 的
# AnswerArtifact、Citation 或 current-run provenance contract。
_FINAL_SYNTHESIS_RESPONSE_FORMAT = {"type": "json_object"}
_DEFAULT_MAX_OUTPUT_TOKENS = 16384
_DEFAULT_COMPLETION_MAX_TOKENS = 2048
# 真实 smoke 证明 OpenCode Go 的 Chat Completions 不兼容 tools + JSON mode 组合。
_PROVIDERS_WITHOUT_TOOL_JSON_MODE = frozenset({"opencode-go"})
# DeepSeek V4 Flash 默认开启 high thinking；reasoning token 与最终 JSON 共用
# max_output_tokens，真实长证据查询会在 JSON 闭合前耗尽 provider 输出预算。
_LOW_REASONING_MODELS = frozenset({"deepseek-v4-flash"})
_JSON_REPAIR_OBSERVER: ContextVar[Callable[[], None] | None] = ContextVar(
    "trivae_json_repair_observer",
    default=None,
)


class _OpenCodeGoChatCompletionsModel(OpenAIChatCompletionsModel):
    """处理 OpenCode Go 的 tool-turn JSON mode 限制，并保持 finalizer 可验证。"""

    async def get_response(self, *args: Any, **kwargs: Any) -> Any:
        """保留 SDK response path，必要时用无工具回合完成一次 JSON finalization。"""

        adjusted_args, adjusted_kwargs = self._adjust_model_call(args, kwargs)
        response = await super().get_response(*adjusted_args, **adjusted_kwargs)
        if not _response_needs_json_repair(
            response,
            _tools_from_model_call(adjusted_args, adjusted_kwargs),
        ):
            return response

        # 真实 Failure Case 表明普通 tool turn 可能返回 prose/Markdown；这里不是静默解析，
        # 而是在同一 provider、同一 Runtime、同一 model-visible input 上显式完成一次 JSON 回合。
        observer = _JSON_REPAIR_OBSERVER.get()
        if observer is not None:
            observer()
        no_tools_args, no_tools_kwargs = _replace_model_call_tools(args, kwargs, [])
        return await super().get_response(*no_tools_args, **no_tools_kwargs)

    def stream_response(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        """保持 SDK streaming generator，并对无工具最终文本做一次有界 JSON 回合。"""

        adjusted_args, adjusted_kwargs = self._adjust_model_call(args, kwargs)
        return self._stream_with_json_repair(
            args,
            kwargs,
            adjusted_args,
            adjusted_kwargs,
        )

    async def _stream_with_json_repair(
        self,
        original_args: tuple[Any, ...],
        original_kwargs: dict[str, Any],
        adjusted_args: tuple[Any, ...],
        adjusted_kwargs: dict[str, Any],
    ) -> AsyncIterator[Any]:
        """只在最终响应不是 JSON object 时重发无工具请求，避免吞掉真实 provider 错误。"""

        buffered_events: list[Any] = []
        saw_tool_call = False
        async for event in super().stream_response(*adjusted_args, **adjusted_kwargs):
            buffered_events.append(event)
            # 一旦观察到 function call，就把本轮事件正常交给 SDK；该回合仍需保留工具。
            if _stream_event_has_tool_call(event):
                saw_tool_call = True
                for buffered_event in buffered_events:
                    yield buffered_event
                buffered_events.clear()

            if _stream_event_type(event) != "response.completed":
                continue
            response = _stream_event_response(event)
            if not saw_tool_call and _response_needs_json_repair(
                response,
                _tools_from_model_call(adjusted_args, adjusted_kwargs),
            ):
                # 不把第一次不合约的文本交给 Runner；只记录一次公开的 compatibility observation。
                observer = _JSON_REPAIR_OBSERVER.get()
                if observer is not None:
                    observer()
                no_tools_args, no_tools_kwargs = _replace_model_call_tools(
                    original_args,
                    original_kwargs,
                    [],
                )
                async for repaired_event in super().stream_response(
                    *no_tools_args,
                    **no_tools_kwargs,
                ):
                    yield repaired_event
                return

            for buffered_event in buffered_events:
                yield buffered_event
            return

        # SDK 正常情况下总会发送 response.completed；若 Provider 违反该约定，
        # 不猜测结果，保留已经观察到的事件并让 Runner 继续暴露真实 stream failure。
        for buffered_event in buffered_events:
            yield buffered_event

    @staticmethod
    def _adjust_model_call(
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        """有工具时移除 JSON mode；无工具时保留 Finalizer 所需的 structured-output 约束。"""

        adjusted_args = list(args)
        adjusted_kwargs = dict(kwargs)
        settings = adjusted_kwargs.get("model_settings")
        tools = adjusted_kwargs.get("tools")
        settings_index = 2
        tools_index = 3
        if settings is None and len(adjusted_args) > settings_index:
            settings = adjusted_args[settings_index]
        if tools is None and len(adjusted_args) > tools_index:
            tools = adjusted_args[tools_index]
        if not isinstance(settings, SDKModelSettings) or not tools:
            return tuple(adjusted_args), adjusted_kwargs
        if not settings.extra_args or "response_format" not in settings.extra_args:
            return tuple(adjusted_args), adjusted_kwargs

        # 只删除冲突字段，保留 max_tokens 和其他已配置的 provider 参数。
        extra_args = {
            key: value for key, value in settings.extra_args.items() if key != "response_format"
        }
        adjusted_settings = replace(settings, extra_args=extra_args)
        if "model_settings" in adjusted_kwargs:
            adjusted_kwargs["model_settings"] = adjusted_settings
        elif len(adjusted_args) > settings_index:
            adjusted_args[settings_index] = adjusted_settings
        return tuple(adjusted_args), adjusted_kwargs


def _tools_from_model_call(
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
) -> list[Any]:
    """读取 SDK model call 的工具列表，不修改调用方传入的对象。"""

    tools = kwargs.get("tools")
    if tools is None and len(args) > 3:
        tools = args[3]
    return tools if isinstance(tools, list) else []


def _replace_model_call_tools(
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
    tools: list[Any],
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """只替换 SDK call 的 tools 参数，保留原始 JSON mode 和其他设置。"""

    adjusted_args = list(args)
    adjusted_kwargs = dict(kwargs)
    if "tools" in adjusted_kwargs:
        adjusted_kwargs["tools"] = tools
    elif len(adjusted_args) > 3:
        adjusted_args[3] = tools
    else:
        adjusted_kwargs["tools"] = tools
    return tuple(adjusted_args), adjusted_kwargs


def _stream_event_type(event: Any) -> str | None:
    """读取 Chat Completions 转换后的公开 event type。"""

    event_type = getattr(event, "type", None)
    if isinstance(event_type, str):
        return event_type
    data = getattr(event, "data", None)
    data_type = getattr(data, "type", None)
    return data_type if isinstance(data_type, str) else None


def _stream_event_response(event: Any) -> Any:
    """从 response.completed event 读取公开 response，不保留 SDK 对象。"""

    response = getattr(event, "response", None)
    if response is not None:
        return response
    data = getattr(event, "data", None)
    return getattr(data, "response", None)


def _stream_event_has_tool_call(event: Any) -> bool:
    """识别公开 function call event，避免把正常工具回合误判为最终文本。"""

    if _stream_event_type(event) not in {
        "response.output_item.added",
        "response.output_item.done",
    }:
        return False
    item = getattr(event, "item", None)
    if item is None:
        data = getattr(event, "data", None)
        item = getattr(data, "item", None)
    return _item_type(item) in _MODEL_ACTION_ITEM_TYPES


def _response_text(response: Any) -> str | None:
    """提取 assistant 公开文本，供 JSON object 形状判断，不做业务解析。"""

    if response is None:
        return None
    projected = _project_model_output(getattr(response, "output", ()))
    if projected is None:
        return None
    parts: list[str] = []
    for item in projected:
        content = item.get("content")
        if isinstance(content, str):
            parts.append(content)
            continue
        if not isinstance(content, (list, tuple)):
            continue
        for block in content:
            if isinstance(block, Mapping) and isinstance(block.get("text"), str):
                parts.append(block["text"])
    text = "".join(parts).strip()
    return text or None


def _response_needs_json_repair(response: Any, tools: list[Any]) -> bool:
    """仅当有工具且最终响应不是 JSON object 时触发一次显式 finalization。"""

    if not tools or _response_has_tool_call(response):
        return False
    text = _response_text(response)
    if text is None:
        return True
    try:
        return not isinstance(json.loads(text), Mapping)
    except (TypeError, ValueError):
        return True


def _response_has_tool_call(response: Any) -> bool:
    """检查已完成 response 的公开 output item 类型。"""

    output = getattr(response, "output", ())
    if not isinstance(output, (list, tuple)):
        return False
    return any(_item_type(item) in _MODEL_ACTION_ITEM_TYPES for item in output)


@dataclass
class _PendingEvent:
    """SDK hook 不能直接 yield，因此先在本地队列保存安全事件。"""

    type: RuntimeEventType
    text: str | None = None
    tool_call: RuntimeToolCall | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_result: ToolResultRecord | None = None
    tool_round: int | None = None
    usage: dict[str, int | float] | None = None
    model_visible_context: tuple[dict[str, object], ...] | None = None
    observable_output: tuple[dict[str, object], ...] | None = None


@dataclass
class _RunState:
    """一次执行的可变状态；不与下一次 run 共享。"""

    provider: str
    model: str
    # run_id 是每次 Runtime execution 新建的本地 identity，与 request_id 明确分离。
    run_id: str = field(default_factory=lambda: f"run-{uuid.uuid4().hex}")
    pending: list[_PendingEvent] = field(default_factory=list)
    sequence: int = 0
    turn: int = 0
    expected_tool_results: int = 0
    completed_tool_results: int = 0
    tool_rounds: int = 0
    finalizing: bool = False
    aborted: bool = False
    settled: bool = False
    # reasoning 只在当前 SDK stream 中短暂存在；该标记仅用于产生一次 completed 边界。
    thinking_active: bool = False


_HIDDEN_ITEM_TYPES = frozenset({"reasoning", "reasoning_item"})
_MODEL_ACTION_ITEM_TYPES = frozenset({"function_call", "custom_tool_call"})
_MODEL_RESULT_ITEM_TYPES = frozenset({"function_call_output", "custom_tool_call_output"})


def _item_mapping(item: Any) -> Mapping[str, object] | None:
    """只从公开 mapping/model_dump 读取 SDK item，不把对象 repr 带入 Trace。"""

    if isinstance(item, Mapping):
        # SDK 当前通常已经把 Pydantic item 转成 dict；这里保留其普通 mapping 形态。
        return item
    model_dump = getattr(item, "model_dump", None)
    if callable(model_dump):
        # typed SDK item 只在 adapter 内转换为普通值，后续只读取白名单字段。
        dumped = model_dump(exclude_unset=True)
        if isinstance(dumped, Mapping):
            return dumped
    return None


def _item_type(item: Any) -> str | None:
    """读取 item type 供生命周期判断，优先使用公开 type 字段。"""

    direct_type = getattr(item, "type", None)
    if isinstance(direct_type, str):
        return direct_type
    mapping = _item_mapping(item)
    item_type = None if mapping is None else mapping.get("type")
    return item_type if isinstance(item_type, str) else None


def _project_plain_value(value: object) -> object:
    """递归保留 SDK 允许的 JSON-like 值，拒绝用 repr 猜测未知对象。"""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        projected: dict[str, object] = {}
        for key, nested in value.items():
            if not isinstance(key, str) or not key:
                raise TypeError("model-visible value contains a non-string key")
            projected[key] = _project_plain_value(nested)
        return projected
    if isinstance(value, (list, tuple)):
        return [_project_plain_value(item) for item in value]
    raise TypeError(f"model-visible value contains unsupported type: {type(value).__name__}")


def _parse_serialized_output(value: str) -> object | None:
    """解析 SDK 为模型准备的 JSON/Python 文本，失败时不猜测其业务含义。"""

    try:
        return json.loads(value)
    except (TypeError, ValueError):
        pass
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return None


def _project_content(content: object) -> object | None:
    """只保留 message content 的公开文本 block，跳过 reasoning block。"""

    if isinstance(content, str):
        return content
    if not isinstance(content, (list, tuple)):
        return None

    blocks: list[object] = []
    for block in content:
        if isinstance(block, str):
            blocks.append(block)
            continue
        block_mapping = _item_mapping(block)
        if block_mapping is None:
            # 未知 content object 没有安全字段可投影，不能用 repr 伪造正文。
            continue
        block_type = block_mapping.get("type")
        if isinstance(block_type, str) and block_type in _HIDDEN_ITEM_TYPES:
            continue
        text = block_mapping.get("text")
        if not isinstance(text, str):
            text = block_mapping.get("refusal")
        if isinstance(text, str):
            blocks.append(
                {
                    "type": block_type if isinstance(block_type, str) else "text",
                    "text": text,
                }
            )
        elif isinstance(block_type, str):
            # image/audio 等公开 block 只保留类型标记，不复制 provider-specific payload。
            blocks.append({"type": block_type})
    return blocks or None


def _project_model_item(item: Any) -> dict[str, object] | None:
    """将一个 SDK input/output item 转成可持久化的 Trivae-owned plain item。"""

    item_mapping = _item_mapping(item)
    item_type = _item_type(item)
    if item_type in _HIDDEN_ITEM_TYPES:
        # hidden reasoning item 直接丢弃，既不保存正文，也不保留 SDK 内部字段。
        return None
    if item_mapping is None:
        # 对不可观察的未知对象保留明确的 capture 状态，而不是静默把它当成普通消息。
        return {"type": "unsupported_visible_item", "item_type": item_type or "unknown"}

    if item_type in _MODEL_ACTION_ITEM_TYPES:
        projected_action: dict[str, object] = {"type": item_type}
        name = item_mapping.get("name")
        if isinstance(name, str):
            projected_action["name"] = name
        if "arguments" in item_mapping:
            projected_action["arguments"] = _project_plain_value(item_mapping["arguments"])
        call_id = item_mapping.get("call_id")
        if isinstance(call_id, str):
            projected_action["call_id"] = call_id
        return projected_action

    if item_type in _MODEL_RESULT_ITEM_TYPES:
        # output 是 SDK 已经准备发送给下一轮模型的内容，不能从 DB 或 ToolResultRecord 重建。
        projected_result: dict[str, object] = {"type": item_type}
        call_id = item_mapping.get("call_id")
        if isinstance(call_id, str):
            projected_result["call_id"] = call_id
        output = _project_plain_value(item_mapping.get("output"))
        projected_result["output"] = output
        if isinstance(output, str):
            # SDK 当前会把普通 dict tool output 转成 Python 文本；保留同一文本的结构化投影，
            # 让 CapturePolicy 截断长字符串后，Transcript 仍能读取模型实际收到的消息正文。
            parsed_output = _parse_serialized_output(output)
            if isinstance(parsed_output, (Mapping, list, tuple)):
                projected_result["output_projection"] = _project_plain_value(parsed_output)
        return projected_result

    role = item_mapping.get("role")
    content = _project_content(item_mapping.get("content"))
    if isinstance(role, str) and content is not None:
        # 保持既有 role/content 形状，避免破坏已消费 model_visible_context 的调用方。
        return {"role": role, "content": content}

    if item_type is None:
        return None
    # 当前 Trivae 只启用 function tool；其他公开 item 不复制 raw payload，只标记投影边界。
    return {"type": "unsupported_visible_item", "item_type": item_type}


def _project_model_output(output: object) -> tuple[dict[str, object], ...] | None:
    """从 ModelResponse.output 提取 assistant visible text/tool action。"""

    if not isinstance(output, (list, tuple)):
        return None
    projected = []
    for item in output:
        item_projection = _project_model_item(item)
        if item_projection is not None:
            projected.append(item_projection)
    return tuple(projected) if projected else None


class _RuntimeHooks(RunHooks[RuntimeContext]):
    """把 SDK lifecycle hook 转成不含 SDK payload 的内部事件。"""

    def __init__(self, state: _RunState, max_tool_rounds: int) -> None:
        super().__init__()
        self._state = state
        self._max_tool_rounds = max_tool_rounds

    async def on_llm_start(
        self,
        context: Any,
        agent: Any,
        system_prompt: str | None,
        input_items: list[Any],
    ) -> None:
        """在 Provider 调用前捕获 SDK 已过滤的真实 model-visible input。"""

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
            _PendingEvent(
                "turn_started",
                tool_round=self._state.tool_rounds + 1,
                model_visible_context=self._project_model_visible_context(system_prompt, input_items),
            )
        )

    @staticmethod
    def _project_model_visible_context(
        system_prompt: str | None,
        input_items: list[Any],
    ) -> tuple[dict[str, object], ...] | None:
        """将 SDK input item 转成 Trivae-owned plain facts，不保存 SDK raw object。"""

        projected: list[dict[str, object]] = []
        if isinstance(system_prompt, str) and system_prompt:
            projected.append({"role": "system", "content": system_prompt})
        for item in input_items:
            item_projection = _project_model_item(item)
            if item_projection is not None:
                projected.append(item_projection)
        return tuple(projected) if projected else None

    async def on_llm_end(self, context: Any, agent: Any, response: Any) -> None:
        """捕获可观察模型输出，并根据 function call 数量推进回合状态。"""

        output = getattr(response, "output", ())
        function_call_count = sum(1 for item in output if _item_type(item) in _MODEL_ACTION_ITEM_TYPES)
        self._state.expected_tool_results = function_call_count
        observable_output = _project_model_output(output)
        if observable_output is not None:
            self._state.pending.append(
                _PendingEvent(
                    "model_output",
                    tool_round=self._state.tool_rounds + 1,
                    observable_output=observable_output,
                )
            )
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
        projected = _project_usage_mapping(usage)
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
        tool_result = self._find_tool_result(runtime_context.tool_results, tool_call_id, tool_name)
        if tool_result is None:
            # Tool adapter 必须先落 canonical result；缺失时不能发出没有明细来源的成功事件。
            raise RuntimeError("SDK tool completed without a Trivae tool result record")

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
                tool_result=tool_result,
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

    @staticmethod
    def _find_tool_result(
        records: list[ToolResultRecord],
        tool_call_id: str | None,
        tool_name: str,
    ) -> ToolResultRecord | None:
        """按同一 Trivae call identity 取得 canonical bounded Tool Result。"""

        for record in reversed(records):
            if record.tool_name == tool_name and (tool_call_id is None or record.tool_call_id == tool_call_id):
                return record
        return None


class OpenAIAgentsRuntimeAdapter(AgentRuntime):
    """把 Trivae Runtime contract 接到 SDK 的唯一 streamed Agent loop。"""

    def __init__(
        self,
        capability_registry: CapabilityRegistry | None = None,
        *,
        model: Any | None = None,
        settings: ModelSettings | None = None,
        provider_name: str | None = None,
        model_name: str | None = None,
        max_turns: int | None = None,
        max_tool_rounds: int | None = None,
    ) -> None:
        """真实 provider 延迟到 runtime 构造时创建；注入模型不需要密钥。"""

        self.capability_registry = capability_registry
        self._provider_client: AsyncOpenAI | None = None
        self._closed = False
        runtime_settings = settings
        if model is None:
            # 只有显式创建真实 runtime 时才读取密钥并创建外部 client。
            resolved_settings = settings or load_settings()
            runtime_settings = resolved_settings
            self._model, self._provider_client = self._build_openai_compatible_model(resolved_settings)
            self._provider_name = resolved_settings.provider
            self._model_name = resolved_settings.model_name
            self._secret = resolved_settings.api_key
            configured_max_turns = resolved_settings.max_turns
            configured_max_tool_rounds = resolved_settings.max_tool_rounds
            configured_max_output_tokens = resolved_settings.max_output_tokens
            configured_completion_max_tokens = resolved_settings.completion_max_tokens
        else:
            # ScriptedModel 等测试模型通过注入进入，不需要 provider key 或网络。
            self._model = model
            self._provider_name = provider_name or (settings.provider if settings is not None else "injected")
            self._model_name = model_name or (settings.model_name if settings is not None else "injected-model")
            self._secret = settings.api_key if settings is not None else ""
            configured_max_turns = settings.max_turns if settings is not None else 8
            configured_max_tool_rounds = settings.max_tool_rounds if settings is not None else 3
            configured_max_output_tokens = (
                settings.max_output_tokens if settings is not None else _DEFAULT_MAX_OUTPUT_TOKENS
            )
            configured_completion_max_tokens = (
                settings.completion_max_tokens
                if settings is not None
                else _DEFAULT_COMPLETION_MAX_TOKENS
            )

        # 统一在 adapter 这一处解析 context，避免 Runtime 各处按 model name 写特判。
        configured_mode = (
            runtime_settings.tool_result_budget_mode if runtime_settings is not None else "dynamic"
        )
        if configured_mode == "fixed":
            # fixed 是显式回归基线，不消费 context，也不把 registry 能力伪装进 Trace。
            context_resolution = None
        else:
            context_resolution = resolve_context_window(
                explicit_context_window_tokens=(
                    runtime_settings.model_context_window_tokens if runtime_settings is not None else None
                ),
                provider=self._provider_name,
                model_name=self._model_name,
            )
        self._tool_result_budget_config = ToolResultBudgetConfig(
            mode=configured_mode,
            context_window_tokens=(
                None if context_resolution is None else context_resolution.context_window_tokens
            ),
            context_window_source=(
                "not_used" if context_resolution is None else context_resolution.source
            ),
            per_call_tool_result_percent=(
                runtime_settings.per_call_tool_result_percent
                if runtime_settings is not None
                else ToolResultBudgetConfig().per_call_tool_result_percent
            ),
            per_call_tool_result_cap=(
                runtime_settings.per_call_tool_result_cap
                if runtime_settings is not None
                else ToolResultBudgetConfig().per_call_tool_result_cap
            ),
            run_tool_evidence_percent=(
                runtime_settings.run_tool_evidence_percent
                if runtime_settings is not None
                else ToolResultBudgetConfig().run_tool_evidence_percent
            ),
            run_tool_evidence_cap=(
                runtime_settings.run_tool_evidence_cap
                if runtime_settings is not None
                else ToolResultBudgetConfig().run_tool_evidence_cap
            ),
            run_tool_evidence_budget_override=(
                runtime_settings.run_tool_evidence_budget if runtime_settings is not None else None
            ),
        )

        self.max_turns = configured_max_turns if max_turns is None else max_turns
        self.max_tool_rounds = (
            configured_max_tool_rounds if max_tool_rounds is None else max_tool_rounds
        )
        self.max_output_tokens = configured_max_output_tokens
        self.completion_max_tokens = configured_completion_max_tokens
        if isinstance(self.max_turns, bool) or not isinstance(self.max_turns, int) or self.max_turns <= 0:
            raise ValueError("max_turns must be a positive integer")
        if (
            isinstance(self.max_tool_rounds, bool)
            or not isinstance(self.max_tool_rounds, int)
            or self.max_tool_rounds <= 0
        ):
            raise ValueError("max_tool_rounds must be a positive integer")
        if (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens <= 0
        ):
            raise ValueError("max_output_tokens must be a positive integer")
        if (
            isinstance(self.completion_max_tokens, bool)
            or not isinstance(self.completion_max_tokens, int)
            or self.completion_max_tokens <= 0
        ):
            raise ValueError("completion_max_tokens must be a positive integer")

    def _build_openai_compatible_model(self, settings: ModelSettings) -> tuple[Any, AsyncOpenAI]:
        """构造并保留兼容 Chat Completions 的 client，供 runtime 和 aclose 共用。"""

        # M4 没有 Trivae Trace backend；显式关闭 hosted tracing，避免产生额外外部依赖。
        set_tracing_disabled(True)
        client = AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url)
        # OpenCode Go 只在有工具的请求上需要动态移除 JSON mode，其他 Provider 保持原模型。
        model_type = (
            _OpenCodeGoChatCompletionsModel
            if settings.provider in _PROVIDERS_WITHOUT_TOOL_JSON_MODE
            else OpenAIChatCompletionsModel
        )
        model = model_type(
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
        repair_observer_token: Token[Callable[[], None] | None] | None = None

        yield self._event(state, "run_started")
        if self._abort_is_set(abort_event):
            state.aborted = True
            result = self._aborted_result((), 0, state.run_id, ())
            yield self._event(state, "aborted", result=result)
            return

        try:
            context = self._build_context(request, abort_event, state.run_id)
            agent = self._build_agent(request, context, state)
            # RunConfig 与全局 tracing 设置同时显式关闭，保证本地运行不依赖 tracing key。
            set_tracing_disabled(True)

            def observe_json_repair() -> None:
                """把 Provider compatibility repair 投影为公开 model observation。"""

                state.pending.append(
                    _PendingEvent(
                        "model_output",
                        tool_round=state.tool_rounds + 1,
                        observable_output=(
                            {
                                "type": "provider_compatibility",
                                "action": "json_finalization_repaired",
                                "reason": "non_json_final_output_after_tool_turn",
                                "tools_removed_for_finalization": True,
                            },
                        ),
                    )
                )

            # ContextVar 避免 Application 复用同一个 Runtime 时，不同 Query 之间串联 observer。
            repair_observer_token = _JSON_REPAIR_OBSERVER.set(observe_json_repair)
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
                    # Tool/model lifecycle 到达时，先关闭仍开放的 reasoning 段，避免跨阶段粘连。
                    if state.thinking_active and pending.type != "usage_update":
                        yield self._event(state, "thinking_completed")
                        state.thinking_active = False
                    yield self._event(
                        state,
                        pending.type,
                        text=pending.text,
                        tool_call=pending.tool_call,
                        tool_name=pending.tool_name,
                        tool_call_id=pending.tool_call_id,
                        tool_result=pending.tool_result,
                        tool_round=pending.tool_round,
                        usage=pending.usage,
                        model_visible_context=pending.model_visible_context,
                        observable_output=pending.observable_output,
                    )
                if state.aborted:
                    continue
                stream_delta = self._stream_delta(sdk_event)
                if stream_delta is not None:
                    delta_type, delta = stream_delta
                    if delta_type == "thinking_summary":
                        # 只有 provider 明确给出的 summary 才开启公开 Process 段。
                        state.thinking_active = True
                        yield self._event(
                            state,
                            "thinking_delta",
                            text=delta,
                            thinking_visibility="public_summary",
                        )
                    elif delta_type == "reasoning_text":
                        # provider 实际下发的 raw reasoning text 按 provider_reasoning 可见性透传；
                        # adapter 不解释内容，下游按各自的 visibility policy 决定展示。
                        state.thinking_active = True
                        yield self._event(
                            state,
                            "thinking_delta",
                            text=delta,
                            thinking_visibility="provider_reasoning",
                        )
                    else:
                        # SDK 没有显式 reasoning done 时，正文首 token 仍是可靠的段落边界。
                        if state.thinking_active:
                            yield self._event(state, "thinking_completed")
                            state.thinking_active = False
                        yield self._event(state, "content_delta", text=delta)
                elif self._is_thinking_done(sdk_event) and state.thinking_active:
                    yield self._event(state, "thinking_completed")
                    state.thinking_active = False

            # SDK stream iterator 完整结束后，再清空最后一批 hook 事件。
            for pending in self._drain_pending(state):
                if state.aborted and pending.type in {"finalizing", "turn_completed"}:
                    continue
                if state.thinking_active and pending.type != "usage_update":
                    yield self._event(state, "thinking_completed")
                    state.thinking_active = False
                yield self._event(
                    state,
                    pending.type,
                    text=pending.text,
                    tool_call=pending.tool_call,
                    tool_name=pending.tool_name,
                    tool_call_id=pending.tool_call_id,
                    tool_result=pending.tool_result,
                    tool_round=pending.tool_round,
                    usage=pending.usage,
                    model_visible_context=pending.model_visible_context,
                    observable_output=pending.observable_output,
                )

            # reasoning 后若没有正文或 hook 事件，SDK stream 结束本身就是最后的真实边界。
            if state.thinking_active:
                yield self._event(state, "thinking_completed")
                state.thinking_active = False

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
            if not isinstance(final_output, str) or not final_output.strip():
                # Provider/compatibility repair 返回空正文时，必须在 Runtime 层标成失败；
                # 不能把“completed + 空字符串”交给 Finalizer 再伪装成正常完成。
                empty_output = isinstance(final_output, str)
                result = self._failed_result(
                    context,
                    state,
                    "INVALID_FINAL_OUTPUT",
                    "SDK final output was empty" if empty_output else "SDK final output was not text",
                    diagnostic_type="empty_final_output" if empty_output else "invalid_final_output",
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
        except ToolResultBudgetExhausted as exc:
            # dynamic pool 耗尽是预算契约错误，使用稳定 code 暴露根因，不把异常正文送给 provider。
            result = self._failed_result(
                context,
                state,
                "TOOL_RESULT_BUDGET_EXHAUSTED",
                "dynamic Tool Result run budget exhausted",
                category="budget",
                diagnostic_type=type(exc).__name__,
                usage=self._project_usage(streamed_result),
            )
            yield self._event(state, "failed", result=result)
        except ToolResultBudgetError as exc:
            # 配置/结算契约错误必须与普通 provider runtime failure 区分，便于 Trace 定位。
            result = self._failed_result(
                context,
                state,
                "TOOL_RESULT_BUDGET_ERROR",
                "Tool Result budget contract failed",
                category="budget",
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
            if repair_observer_token is not None:
                _JSON_REPAIR_OBSERVER.reset(repair_observer_token)
            if abort_task is not None:
                abort_task.cancel()
                await asyncio.gather(abort_task, return_exceptions=True)

    def _build_context(
        self,
        request: AgentRunRequest,
        abort_event: object | None = None,
        run_id: str | None = None,
    ) -> RuntimeContext:
        """把 trusted registry/scope 放入 SDK local context，而不是 prompt/tool 参数。"""

        if self.capability_registry is None:
            raise RuntimeError("capability_registry is required to run the Trivae agent")
        registered = set(self.capability_registry.names())
        unknown = set(request.available_capabilities) - registered
        if unknown:
            raise ValueError(f"requested capability is not registered: {sorted(unknown)!r}")
        return RuntimeContext(
            run_id=run_id or f"run-{uuid.uuid4().hex}",
            tool_identity_prefix=request.request_id,
            scope=request.scope,
            capability_registry=self.capability_registry,
            available_capabilities=request.available_capabilities,
            abort_event=abort_event,
            trace_context=request.trace_context,
            tool_result_budget_policy=self._tool_result_budget_config.new_policy(),
        )

    def _build_agent(self, request: AgentRunRequest, context: RuntimeContext, state: _RunState) -> Any:
        """按 request 白名单注册工具，并动态追加 soft plan/final synthesis instructions。"""

        tools: list[Any] = []
        if "search_messages" in context.available_capabilities:
            # 只把当前结果数量上限投影到 provider schema；完整 scope 仍保留在 RuntimeContext 内执行。
            tools.append(
                SearchMessagesSDKToolAdapter(context.capability_registry).as_sdk_tool(
                    trusted_max_results=context.scope.max_results
                )
            )
        if "lexical_search" in context.available_capabilities:
            tools.append(
                LexicalSearchSDKToolAdapter(context.capability_registry).as_sdk_tool(
                    trusted_max_results=context.scope.max_results
                )
            )
        if "semantic_search" in context.available_capabilities:
            tools.append(
                SemanticSearchSDKToolAdapter(context.capability_registry).as_sdk_tool(
                    trusted_max_results=context.scope.max_results
                )
            )
        if "get_recent_messages" in context.available_capabilities:
            tools.append(
                GetRecentMessagesSDKToolAdapter(context.capability_registry).as_sdk_tool(
                    trusted_max_results=context.scope.max_results
                )
            )
        if "get_message_context" in context.available_capabilities:
            tools.append(GetMessageContextSDKToolAdapter(context.capability_registry).as_sdk_tool())
        if "find_members" in context.available_capabilities:
            tools.append(
                FindMembersSDKToolAdapter(context.capability_registry).as_sdk_tool(
                    trusted_max_results=context.scope.max_results
                )
            )
        if "get_schema" in context.available_capabilities:
            tools.append(GetSchemaSDKToolAdapter(context.capability_registry).as_sdk_tool())
        if "execute_sql" in context.available_capabilities:
            tools.append(
                ExecuteSQLSDKToolAdapter(context.capability_registry).as_sdk_tool(
                    trusted_max_results=context.scope.max_results
                )
            )

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

        # 只对已验证支持 low effort 的 OpenCode Go DeepSeek V4 Flash 降低内部推理预算；
        # 这样保留模型的思考能力，同时把 token 预算留给必须闭合的 Answer Artifact JSON。
        reasoning = (
            {"effort": "low"}
            if self._provider_name == "opencode-go"
            and self._model_name.lower() in _LOW_REASONING_MODELS
            else None
        )

        return Agent(
            name="Trivae Agent",
            instructions=instructions,
            model=self._model,
            # 让兼容 Provider 透传已验证的 JSON mode；最终文本仍由 M5 finalizer 解析和验证。
            model_settings=SDKModelSettings(
                # JSON Output 需要显式预算；否则 provider 默认边界可能在 JSON 中间结束。
                max_tokens=self.max_output_tokens,
                reasoning=reasoning,
                extra_args={"response_format": _FINAL_SYNTHESIS_RESPONSE_FORMAT},
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
    def _stream_delta(event: Any) -> tuple[Literal["thinking_summary", "reasoning_text", "content"], str] | None:
        """只把 provider 实际下发的 reasoning 与 answer text 归一化，不做业务猜测。

        - ``response.output_text.delta``：最终 answer 正文。
        - ``response.reasoning_summary_text.delta``：provider 公开 reasoning summary。
        - ``response.reasoning_text.delta``：兼容 provider 实际下发的 raw reasoning text；
          该事件由 SDK 公开 stream 传递，属于应用层合法可获得的内容，按
          ``provider_reasoning`` 可见性透传。provider 没有给出时不存在该事件，
          Runtime 不反推、不模拟 hidden CoT。
        """

        data = getattr(event, "data", None)
        event_type = getattr(data, "type", None)
        if event_type == "response.output_text.delta":
            delta_type: Literal["thinking_summary", "reasoning_text", "content"] = "content"
        elif event_type == "response.reasoning_summary_text.delta":
            delta_type = "thinking_summary"
        elif event_type == "response.reasoning_text.delta":
            delta_type = "reasoning_text"
        else:
            return None
        delta = getattr(data, "delta", None)
        if not isinstance(delta, str) or not delta:
            return None
        return delta_type, delta

    @staticmethod
    def _is_thinking_done(event: Any) -> bool:
        """识别 SDK public reasoning done，不依赖 provider-specific response 字段。"""

        data = getattr(event, "data", None)
        return getattr(data, "type", None) == "response.reasoning_summary_text.done"

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
        thinking_visibility: Literal["public_summary", "provider_reasoning"] = "public_summary",
        tool_call: RuntimeToolCall | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        tool_result: ToolResultRecord | None = None,
        result: RuntimeResult | None = None,
        tool_round: int | None = None,
        usage: dict[str, int | float] | None = None,
        model_visible_context: tuple[dict[str, object], ...] | None = None,
        observable_output: tuple[dict[str, object], ...] | None = None,
    ) -> RuntimeEvent:
        """为每个事件分配进程内 sequence，不暴露 provider 原始 sequence。"""

        state.sequence += 1
        return RuntimeEvent(
            type=event_type,
            provider=state.provider,
            model=state.model,
            sequence=state.sequence,
            text=text,
            thinking_visibility=thinking_visibility,
            tool_call=tool_call,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_result=tool_result,
            result=result,
            tool_round=tool_round,
            usage=usage,
            run_id=state.run_id,
            model_visible_context=model_visible_context,
            observable_output=observable_output,
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

        # 兼容 Router 等只需要文本的调用者，同时让 Planner 使用下方 metadata-aware 方法。
        result = await self.complete_text_with_observation(prompt)
        # Provider 空 content 继续显式失败，避免把空字符串交给 JSON parser 猜测。
        if not isinstance(result.content, str) or not result.content.strip():
            raise RuntimeError("provider completion returned no text")
        return result.content.strip()

    def completion_request_projection(self) -> dict[str, object]:
        """返回 Router/Planner completion 的 provider-facing 安全请求投影。"""

        # 这些字段是实际发送给 Chat Completions 的非敏感参数，不包含 API key/header。
        return {
            "provider": self._provider_name,
            "model": self._model_name,
            "temperature": 0,
            "max_tokens": self.completion_max_tokens,
            "json_mode": True,
            "response_format": dict(_FINAL_SYNTHESIS_RESPONSE_FORMAT),
        }

    async def complete_text_with_observation(self, prompt: str) -> CompletionResult:
        """执行一次 JSON completion，并返回安全的 request/response/usage/finish 投影。"""

        if self._closed:
            raise RuntimeError("runtime is closed")
        if self._provider_client is None:
            raise RuntimeError("injected runtime model has no provider completion client")
        request_projection = self.completion_request_projection()
        started = perf_counter()
        response = await self._provider_client.chat.completions.create(
            model=self._model_name,
            messages=[
                {"role": "system", "content": "Return only the requested JSON or concise text."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            # Router/Planner 都要求 JSON；显式 JSON mode 让 provider 不依赖裸 prompt 约束。
            response_format=cast(Any, _FINAL_SYNTHESIS_RESPONSE_FORMAT),
            max_tokens=self.completion_max_tokens,
        )
        # 只读取公开 choices/message 字段；不保存 SDK response 或 raw repr。
        choices = getattr(response, "choices", None)
        choice = choices[0] if isinstance(choices, (list, tuple)) and choices else None
        message = None if choice is None else getattr(choice, "message", None)
        content = None if message is None else getattr(message, "content", None)
        # finish_reason 是判断 Provider length 截断的关键事实，缺失时保持 None。
        finish_reason = None if choice is None else getattr(choice, "finish_reason", None)
        if not isinstance(finish_reason, str):
            finish_reason = None
        # usage 只投影常见的数字字段，不跨 boundary 传递 SDK Usage 对象。
        usage = self._project_completion_usage(response)
        observation = CompletionObservation(
            provider=self._provider_name,
            model=self._model_name,
            request=request_projection,
            latency_ms=(perf_counter() - started) * 1000,
            finish_reason=finish_reason,
            usage=usage,
            response_content=content if isinstance(content, str) else None,
        )
        # content 非字符串时返回 None，让 SoftPlanner 将其归为 provider response 阶段失败。
        return CompletionResult(content if isinstance(content, str) else None, observation)

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
            for field_name, value in _project_usage_mapping(usage).items():
                totals[field_name] = totals.get(field_name, 0) + value
        return totals or None

    @staticmethod
    def _project_completion_usage(response: Any) -> dict[str, int | float] | None:
        """把 Chat Completion usage 转成普通数字，保留 output token 诊断。"""

        usage = getattr(response, "usage", None)
        projected = _project_usage_mapping(usage)
        return projected or None


def _project_usage_mapping(usage: Any) -> dict[str, int | float]:
    """在 adapter 边界归一化常见 usage 字段，不为未知字段伪造数值。"""

    if usage is None:
        return {}

    projected: dict[str, int | float] = {}
    # Agents SDK 和 Chat Completions 对输入/输出字段使用过两组命名，统一成 Trivae key。
    for target_name, source_names in (
        ("requests", ("requests",)),
        ("input_tokens", ("input_tokens", "prompt_tokens")),
        ("output_tokens", ("output_tokens", "completion_tokens")),
        ("total_tokens", ("total_tokens",)),
    ):
        value = _first_numeric(usage, source_names)
        if value is not None:
            projected[target_name] = value

    # cached input/cache read 只在 Provider 真实返回时写入，缺失时保持 unknown。
    cached_input_tokens = _cached_input_tokens(usage)
    if cached_input_tokens is not None:
        projected["cached_input_tokens"] = cached_input_tokens
    return projected


def _cached_input_tokens(usage: Any) -> int | float | None:
    """读取 flat 或 token-details 形式的 cache-read usage 字段。"""

    # 先检查已经归一化或部分 Provider 直接返回的 flat 字段。
    direct = _first_numeric(
        usage,
        ("cached_input_tokens", "cache_read_input_tokens", "cache_read_tokens", "cached_tokens"),
    )
    if direct is not None:
        return direct

    # OpenAI-compatible Chat Completions 常把 cached_tokens 放在 prompt/input details 中。
    for details_name in ("prompt_tokens_details", "input_tokens_details"):
        details = _public_value(usage, details_name)
        cached = _first_numeric(
            details,
            ("cached_tokens", "cache_read_input_tokens", "cache_read_tokens"),
        )
        if cached is not None:
            return cached
    return None


def _first_numeric(container: Any, names: tuple[str, ...]) -> int | float | None:
    """从 mapping 或 SDK 普通对象读取第一个真实数字字段。"""

    for name in names:
        value = _public_value(container, name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    return None


def _public_value(container: Any, name: str) -> object | None:
    """只读取公开 mapping/属性，不把 SDK 对象 repr 或异常正文带入 projection。"""

    if isinstance(container, Mapping):
        return container.get(name)
    return getattr(container, name, None)
