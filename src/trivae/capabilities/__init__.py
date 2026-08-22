"""Capability / Tool Layer 的最小实现。"""

from trivae.capabilities.contracts import (
    CapabilityContractError,
    CapabilityMetadata,
    CapabilityScopeError,
    ExecutionScope,
    SearchMessagesInput,
    ToolEnvelope,
    ToolError,
)
from trivae.capabilities.registry import CapabilityRegistry
from trivae.capabilities.search_messages import SearchMessagesCapability
from trivae.capabilities.tools import SearchMessagesTool

__all__ = [
    "CapabilityContractError",
    "CapabilityMetadata",
    "CapabilityRegistry",
    "CapabilityScopeError",
    "ExecutionScope",
    "SearchMessagesCapability",
    "SearchMessagesInput",
    "SearchMessagesTool",
    "ToolEnvelope",
    "ToolError",
]
