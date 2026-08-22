"""不依赖 Agent SDK 的 Runtime request/context/result 契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Mapping, Protocol

from trivae.capabilities.contracts import ExecutionScope
from trivae.capabilities.registry import CapabilityRegistry


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
    available_capabilities: tuple[str, ...] = ("search_messages",)
    model_context: tuple[ModelContextMessage, ...] = ()
    plan_guidance: str | None = None
    request_id: str | None = None

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
    provider: str
    model: str
    sequence: int
    text: str | None = None
    tool_call: RuntimeToolCall | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    result: RuntimeResult | None = None
    tool_round: int | None = None
    usage: Mapping[str, int | float] | None = None


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
