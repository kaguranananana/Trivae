"""Capability / Tool Layer 的最小实现。"""

from trivae.capabilities.contracts import (
    CapabilityContractError,
    CapabilityMetadata,
    CapabilityScopeError,
    ExecutionScope,
    SearchMessagesInput,
    SemanticSearchInput,
    ToolEnvelope,
    ToolError,
)
from trivae.capabilities.registry import CapabilityRegistry
from trivae.capabilities.search_messages import LexicalSearchCapability, SearchMessagesCapability
from trivae.capabilities.semantic_search import SemanticSearchCapability
from trivae.capabilities.tools import LexicalSearchTool, SearchMessagesTool, SemanticSearchTool

__all__ = [
    "CapabilityContractError",
    "CapabilityMetadata",
    "CapabilityRegistry",
    "CapabilityScopeError",
    "ExecutionScope",
    "LexicalSearchCapability",
    "LexicalSearchTool",
    "SearchMessagesCapability",
    "SearchMessagesInput",
    "SearchMessagesTool",
    "SemanticSearchCapability",
    "SemanticSearchInput",
    "SemanticSearchTool",
    "ToolEnvelope",
    "ToolError",
]
