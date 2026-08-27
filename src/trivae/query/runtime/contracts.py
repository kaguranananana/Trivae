"""不依赖 Agent SDK 的 Runtime request/context/result 契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Mapping, Protocol

from trivae.capabilities.contracts import ExecutionScope
from trivae.capabilities.registry import CapabilityRegistry
from trivae.query.evidence import ToolResultRecord
from trivae.query.runtime.budget import ToolResultBudgetConfig, ToolResultBudgetPolicy, ToolResultBudgetSnapshot


class AgentRuntimeContractError(ValueError):
    """Runtime 请求违反公开契约。"""


@dataclass(frozen=True)
class ModelContextMessage:
    """模型可见的有限历史消息；trusted scope 不允许通过这个类型传入。"""

    role: Literal["user", "assistant"]
    content: str

    def __post_init__(self) -> None:
        """在 runtime 边界拒绝空内容，避免把无效上下文送给 provider。"""

        if self.role not in ("user", "assistant"):
            raise AgentRuntimeContractError("model context role must be user or assistant")
        if not isinstance(self.content, str) or not self.content.strip():
            raise AgentRuntimeContractError("model context content must be a non-empty string")
        object.__setattr__(self, "content", self.content.strip())


@dataclass(frozen=True)
class AgentRunRequest:
    """一次 Agent 执行所需的用户问题、trusted scope 和显式工具白名单。"""

    query: str
    scope: ExecutionScope
    # Application 的 QueryRequest 会显式编译 canonical surface；低层直接 caller 默认保留 legacy contract。
    available_capabilities: tuple[str, ...] = ("search_messages",)
    model_context: tuple[ModelContextMessage, ...] = ()
    plan_guidance: str | None = None
    request_id: str | None = None
    # Query 只通过本地对象传递 Trace operation，不把 collector 序列化到 provider input。
    trace_context: object | None = None

    def __post_init__(self) -> None:
        """在 Runtime 边界一次性校验用户 query 与 capability 名称。"""

        if not isinstance(self.query, str) or not self.query.strip():
            raise AgentRuntimeContractError("query must be a non-empty string")
        object.__setattr__(self, "query", self.query.strip())
        if not isinstance(self.scope, ExecutionScope):
            raise AgentRuntimeContractError("scope must be an ExecutionScope")
        if not isinstance(self.available_capabilities, tuple):
            raise AgentRuntimeContractError("available_capabilities must be a tuple")
        if any(not isinstance(name, str) or not name for name in self.available_capabilities):
            raise AgentRuntimeContractError("available_capabilities must contain non-empty names")
        if len(set(self.available_capabilities)) != len(self.available_capabilities):
            raise AgentRuntimeContractError("available_capabilities must not contain duplicates")
        if not isinstance(self.model_context, tuple):
            raise AgentRuntimeContractError("model_context must be a tuple")
        if any(not isinstance(message, ModelContextMessage) for message in self.model_context):
            raise AgentRuntimeContractError("model_context must contain ModelContextMessage values")
        if self.plan_guidance is not None:
            if not isinstance(self.plan_guidance, str) or not self.plan_guidance.strip():
                raise AgentRuntimeContractError("plan_guidance must be a non-empty string when provided")
            object.__setattr__(self, "plan_guidance", self.plan_guidance.strip())
        if self.request_id is not None:
            if not isinstance(self.request_id, str) or not self.request_id.strip():
                raise AgentRuntimeContractError("request_id must be a non-empty string when provided")
            object.__setattr__(self, "request_id", self.request_id.strip())


@dataclass(frozen=True)
class RuntimeToolCall:
    """Tool 调用的安全状态投影，不保留 SDK item 或原始参数。"""

    name: str
    status: Literal["ok", "partial", "error", "failed"]
    error_code: str | None = None
    tool_call_id: str | None = None
    round: int | None = None
    # M5 provenance 扩展放在原有字段之后，保留 M4 positional projection 的顺序。
    tool_result_id: str | None = None
    # model projection 只记录 Host 的 bounded estimate；provider 原始 tool-result token 可能 unavailable。
    model_result_estimated_tokens: int | None = None
    model_result_truncated: bool | None = None
    model_result_omitted_hit_messages: int | None = None
    model_result_omitted_context_messages: int | None = None
    tool_result_budget: ToolResultBudgetSnapshot | None = None

    @property
    def tool_round(self) -> int | None:
        """提供语义化读取名，内部仍保持最小 round 投影字段。"""

        return self.round


@dataclass
class RuntimeContext:
    """进程内 local context；不会自动序列化到模型 prompt。"""

    scope: ExecutionScope
    capability_registry: CapabilityRegistry
    available_capabilities: tuple[str, ...]
    tool_calls: list[RuntimeToolCall] = field(default_factory=list)
    tool_rounds: int = 0
    aborted: bool = False
    abort_event: object | None = None
    current_tool_round: int = 1
    # run_id 是当前执行的本地关联键，不把 provider call ID 当成公共身份。
    run_id: str = "run-unknown"
    # M5 的 tool locator 曾以 request_id 为前缀；保留该已验证的 locator 形状，
    # 但 run_id 本身仍由 Runtime 独立生成，二者不再混用为同一个 identity。
    tool_identity_prefix: str | None = None
    tool_results: list[ToolResultRecord] = field(default_factory=list)
    current_tool_call_id: str | None = None
    # observability operation context 只存在进程内，Tool adapter 可选地消费它。
    trace_context: object | None = None
    # 每次 RuntimeContext 都拥有独立账本；直接构造 context 也遵循 dynamic unknown 的 16k shared fallback。
    tool_result_budget_policy: ToolResultBudgetPolicy = field(
        default_factory=lambda: ToolResultBudgetConfig().new_policy()
    )
    # provider call ID 只存在 adapter local context，用于把 SDK hook 对回 Trivae-owned identity。
    _provider_tool_call_ids: dict[str, str] = field(default_factory=dict, repr=False)
    _next_tool_call_number: int = field(default=0, repr=False)

    def resolve_tool_call_id(self, provider_tool_call_id: str | None) -> str:
        """为一次 SDK tool call 分配稳定的 Trivae-owned identity。"""

        if provider_tool_call_id is None and self.current_tool_call_id is not None:
            return self.current_tool_call_id
        if provider_tool_call_id is not None:
            existing = self._provider_tool_call_ids.get(provider_tool_call_id)
            if existing is not None:
                self.current_tool_call_id = existing
                return existing
        self._next_tool_call_number += 1
        identity_prefix = self.tool_identity_prefix or self.run_id
        local_id = f"{identity_prefix}/tool-call/{self._next_tool_call_number}"
        if provider_tool_call_id is not None:
            self._provider_tool_call_ids[provider_tool_call_id] = local_id
        self.current_tool_call_id = local_id
        return local_id

    def allocate_tool_call_id(self, provider_tool_call_id: str | None) -> str:
        """在 tool-start 边界为缺少 provider ID 的调用强制分配新 identity。"""

        if provider_tool_call_id is not None:
            return self.resolve_tool_call_id(provider_tool_call_id)
        self._next_tool_call_number += 1
        identity_prefix = self.tool_identity_prefix or self.run_id
        local_id = f"{identity_prefix}/tool-call/{self._next_tool_call_number}"
        self.current_tool_call_id = local_id
        return local_id

    def resolve_message_source_handle(self, source_id: str) -> str:
        """将模型 source handle 解析为 context tool 所需的 canonical message ID。"""

        matches: list[str] = []
        for record in self.tool_results:
            resolved = record.resolve_source_handle(source_id)
            if resolved is None:
                continue
            if resolved[0] != "message":
                raise AgentRuntimeContractError("source handle does not identify a message")
            message = getattr(resolved[1], "message", None)
            internal_message_id = getattr(message, "internal_message_id", None)
            if not isinstance(internal_message_id, str) or not internal_message_id:
                raise AgentRuntimeContractError("source handle resolved to an invalid message projection")
            matches.append(internal_message_id)
        if not matches:
            raise AgentRuntimeContractError("source handle does not identify a current message")
        if len(matches) > 1:
            raise AgentRuntimeContractError("source handle identifies multiple current messages")
        return matches[0]


@dataclass(frozen=True)
class RuntimeErrorInfo:
    """Runtime terminal error 的可见、非敏感投影。"""

    code: str
    message: str
    stage: str = "runtime"
    category: str | None = None
    diagnostic_type: str | None = None


@dataclass(frozen=True)
class RuntimeResult:
    """Agent Runtime 的稳定输出；不暴露 SDK result、exception 或 client。"""

    final_answer: str | None
    provider: str
    model: str
    termination: Literal["completed", "max_turns_exceeded", "failed", "aborted"]
    tool_calls: tuple[RuntimeToolCall, ...]
    error: RuntimeErrorInfo | None = None
    usage: Mapping[str, int | float] | None = None
    tool_rounds: int = 0
    # M5 只携带 bounded provenance projection，不携带 SDK raw result。
    run_id: str | None = None
    tool_results: tuple[ToolResultRecord, ...] = ()

    @property
    def answer(self) -> str | None:
        """提供简短只读别名，仍返回同一个 Trivae-owned answer。"""

        return self.final_answer

    @property
    def termination_reason(self) -> str:
        """返回供接口层使用的终止原因字符串。"""

        return self.termination

    @property
    def tool_count(self) -> int:
        """返回已进入本地 tool adapter 的调用数量。"""

        return len(self.tool_calls)

    @property
    def is_terminal(self) -> bool:
        """返回执行是否已经进入不可继续的 terminal state。"""

        return self.termination in {"completed", "max_turns_exceeded", "failed", "aborted"}


@dataclass(frozen=True)
class RuntimeEvent:
    """跨 Runtime adapter 的稳定事件；payload 只允许安全的普通值。"""

    type: Literal[
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
    provider: str
    model: str
    sequence: int
    text: str | None = None
    # thinking_delta 的可见性来源：public_summary 是 provider 公开 summary；
    # provider_reasoning 是 provider/SDK 实际下发且应用层合法获得的 reasoning text。
    # 两者都只透传 provider 真实返回的内容，不反推、不伪造 hidden CoT。
    thinking_visibility: Literal["public_summary", "provider_reasoning"] = "public_summary"
    tool_call: RuntimeToolCall | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    # Tool 完成事件携带同一调用的 canonical bounded record，供接口层生成安全明细。
    tool_result: ToolResultRecord | None = None
    result: RuntimeResult | None = None
    tool_round: int | None = None
    usage: Mapping[str, int | float] | None = None
    # 下面三个字段是 additive，供 Trace mapper 关联 run identity 与 model-visible facts。
    run_id: str | None = None
    model_visible_context: tuple[Mapping[str, object], ...] | None = None
    # 这是模型公开产生的 message/tool action，不包含 provider 内部 reasoning 或 SDK raw object。
    observable_output: tuple[Mapping[str, object], ...] | None = None


RuntimeStream = AsyncIterator[RuntimeEvent]


class AgentRuntime(Protocol):
    """Trivae-owned 的异步 Runtime 边界。"""

    async def run(self, request: AgentRunRequest) -> RuntimeResult:
        """执行一次 bounded Agent run。"""


class AgentRuntimeStreaming(AgentRuntime, Protocol):
    """支持事件流和取消的 runtime 扩展协议。"""

    def stream(
        self,
        request: AgentRunRequest,
        abort_event: object | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """启动一次 stream；abort_event 由 adapter 解释为异步取消信号。"""


# 语义别名让 Application/未来接口可以使用 execution terminology，仍共用同一个契约。
AgentExecutionInput = AgentRunRequest
