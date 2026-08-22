"""Agent Runtime 公共契约与 OpenAI Agents SDK 适配入口。"""

from trivae.query.runtime.contracts import (
    AgentExecutionInput,
    AgentRunRequest,
    AgentRuntime,
    AgentRuntimeStreaming,
    ModelContextMessage,
    RuntimeContext,
    RuntimeErrorInfo,
    RuntimeEvent,
    RuntimeResult,
    RuntimeStream,
    RuntimeToolCall,
)

__all__ = [
    "AgentRunRequest",
    "AgentExecutionInput",
    "AgentRuntime",
    "AgentRuntimeStreaming",
    "RuntimeContext",
    "RuntimeErrorInfo",
    "RuntimeEvent",
    "RuntimeResult",
    "RuntimeStream",
    "RuntimeToolCall",
    "ModelContextMessage",
]
