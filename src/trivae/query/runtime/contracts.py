"""不依赖 Agent SDK 的 Runtime request/context/result 契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Protocol

from trivae.capabilities.contracts import ExecutionScope
from trivae.capabilities.registry import CapabilityRegistry


class AgentRuntimeContractError(ValueError):
    """Runtime 请求违反公开契约。"""


@dataclass(frozen=True)
class AgentRunRequest:
    """一次 Agent 执行所需的用户问题、trusted scope 和显式工具白名单。"""

    query: str
    scope: ExecutionScope
    available_capabilities: tuple[str, ...] = ("search_messages",)

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


@dataclass(frozen=True)
class RuntimeToolCall:
    """Tool 调用的安全状态投影，不保留 SDK item 或原始参数。"""

    name: str
    status: Literal["ok", "partial", "error", "failed"]
    error_code: str | None = None


@dataclass
class RuntimeContext:
    """进程内 local context；不会自动序列化到模型 prompt。"""

    scope: ExecutionScope
    capability_registry: CapabilityRegistry
    available_capabilities: tuple[str, ...]
    tool_calls: list[RuntimeToolCall] = field(default_factory=list)


@dataclass(frozen=True)
class RuntimeErrorInfo:
    """Runtime terminal error 的可见、非敏感投影。"""

    code: str
    message: str


@dataclass(frozen=True)
class RuntimeResult:
    """Agent Runtime 的稳定输出；不暴露 SDK result、exception 或 client。"""

    final_answer: str | None
    provider: str
    model: str
    termination: Literal["completed", "max_turns_exceeded", "failed"]
    tool_calls: tuple[RuntimeToolCall, ...]
    error: RuntimeErrorInfo | None = None
    usage: Mapping[str, int | float] | None = None

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


class AgentRuntime(Protocol):
    """Trivae-owned 的异步 Runtime 边界。"""

    async def run(self, request: AgentRunRequest) -> RuntimeResult:
        """执行一次 bounded Agent run。"""
