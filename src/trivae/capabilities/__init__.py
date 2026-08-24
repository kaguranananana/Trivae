"""Capability / Tool Layer 的最小实现。"""

from trivae.capabilities.contracts import (
    CapabilityContractError,
    CapabilityMetadata,
    CapabilityScopeError,
    ExecutionScope,
    FindMembersInput,
    GetMessageContextInput,
    SearchMessagesInput,
    SemanticSearchInput,
    ToolEnvelope,
    ToolError,
)
from trivae.capabilities.find_members import FindMembersCapability
from trivae.capabilities.get_message_context import GetMessageContextCapability, MessageContextNotFound
from trivae.capabilities.registry import CapabilityRegistry, ToolRequest
from trivae.capabilities.search_messages import LexicalSearchCapability, SearchMessagesCapability
from trivae.capabilities.semantic_search import SemanticSearchCapability
from trivae.capabilities.tools import (
    FindMembersTool,
    GetMessageContextTool,
    LexicalSearchTool,
    SearchMessagesTool,
    SemanticSearchTool,
)

__all__ = [
    "CapabilityContractError",
    "CapabilityMetadata",
    "CapabilityRegistry",
    "CapabilityScopeError",
    "ExecutionScope",
    "FindMembersCapability",
    "FindMembersTool",
    "FindMembersInput",
    "GetMessageContextInput",
    "GetMessageContextCapability",
    "GetMessageContextTool",
    "MessageContextNotFound",
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
    "ToolRequest",
]
