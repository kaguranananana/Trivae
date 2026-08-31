"""Agent Runtime 公共契约与 OpenAI Agents SDK 适配入口。"""

from trivae.query.evidence import ToolResultRecord
from trivae.query.runtime.budget import (
    ToolResultBudgetCall,
    ToolResultBudgetConfig,
    ToolResultBudgetError,
    ToolResultBudgetExhausted,
    ToolResultBudgetPolicy,
    ToolResultBudgetSnapshot,
)
from trivae.query.runtime.contracts import (
    AgentExecutionInput,
    AgentRunRequest,
    AgentRuntime,
    AgentRuntimeStreaming,
    ModelBehaviorError,
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
    "ToolResultRecord",
    "ModelContextMessage",
    "ModelBehaviorError",
    "ToolResultBudgetCall",
    "ToolResultBudgetConfig",
    "ToolResultBudgetError",
    "ToolResultBudgetExhausted",
    "ToolResultBudgetPolicy",
    "ToolResultBudgetSnapshot",
]
