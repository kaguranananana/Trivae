"""Agent Runtime 公共契约与 OpenAI Agents SDK 适配入口。"""

from trivae.query.runtime.contracts import (
    AgentRunRequest,
    AgentRuntime,
    RuntimeContext,
    RuntimeErrorInfo,
    RuntimeResult,
    RuntimeToolCall,
)

__all__ = [
    "AgentRunRequest",
    "AgentRuntime",
    "RuntimeContext",
    "RuntimeErrorInfo",
    "RuntimeResult",
    "RuntimeToolCall",
]
