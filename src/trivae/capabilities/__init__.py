"""Capability / Tool Layer 的最小实现。"""

from trivae.capabilities.contracts import (
    CapabilityContractError,
    CapabilityMetadata,
    CapabilityScopeError,
    ExecuteSQLInput,
    ExecutionScope,
    FindMembersInput,
    GetMessageContextInput,
    GetSchemaInput,
    SearchMessagesInput,
    SemanticSearchInput,
    ToolEnvelope,
    ToolError,
)
from trivae.capabilities.execute_sql import ExecuteSQLCapability, SQLCapabilityError
from trivae.capabilities.find_members import FindMembersCapability
from trivae.capabilities.get_message_context import GetMessageContextCapability, MessageContextNotFound
from trivae.capabilities.get_schema import GetSchemaCapability
from trivae.capabilities.registry import CapabilityRegistry, ToolRequest
from trivae.capabilities.search_messages import LexicalSearchCapability, SearchMessagesCapability
from trivae.capabilities.semantic_search import SemanticSearchCapability
from trivae.capabilities.tools import (
    ExecuteSQLTool,
    FindMembersTool,
    GetMessageContextTool,
    GetSchemaTool,
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
    "ExecuteSQLCapability",
    "ExecuteSQLInput",
    "ExecuteSQLTool",
    "FindMembersCapability",
    "FindMembersTool",
    "FindMembersInput",
    "GetMessageContextInput",
    "GetMessageContextCapability",
    "GetMessageContextTool",
    "GetSchemaCapability",
    "GetSchemaInput",
    "GetSchemaTool",
    "MessageContextNotFound",
    "LexicalSearchCapability",
    "LexicalSearchTool",
    "SearchMessagesCapability",
    "SearchMessagesInput",
    "SearchMessagesTool",
    "SemanticSearchCapability",
    "SemanticSearchInput",
    "SemanticSearchTool",
    "SQLCapabilityError",
    "ToolEnvelope",
    "ToolError",
    "ToolRequest",
]
