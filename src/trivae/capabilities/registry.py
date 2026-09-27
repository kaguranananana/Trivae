"""最小显式 Tool registry。"""

from __future__ import annotations

from typing import Any, Protocol

from trivae.capabilities.contracts import (
    CapabilityMetadata,
    ExecuteSQLInput,
    ExecutionScope,
    FindMembersInput,
    GetMessageContextInput,
    GetRecentMessagesInput,
    GetSchemaInput,
    SearchMessagesInput,
    SemanticSearchInput,
    ToolEnvelope,
)

ToolRequest = (
    SearchMessagesInput
    | SemanticSearchInput
    | GetRecentMessagesInput
    | GetMessageContextInput
    | FindMembersInput
    | GetSchemaInput
    | ExecuteSQLInput
)


class ToolHandler(Protocol):
    """registry 中可被 Application 调用的 agent-facing handler。"""

    name: str

    def invoke(self, request: Any, scope: ExecutionScope) -> ToolEnvelope:
        """执行 typed tool call。"""


class CapabilityRegistry:
    """只注册已经实现的 Tool，不动态猜测或生成未定义能力。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolHandler] = {}

    def register(self, tool: ToolHandler) -> None:
        """拒绝同名覆盖，防止 registry 语义在运行时漂移。"""

        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def invoke(
        self,
        name: str,
        request: ToolRequest,
        scope: ExecutionScope,
        *,
        trace_context: object | None = None,
    ) -> ToolEnvelope:
        """按稳定名称查找并调用 Tool；Trace hook 是可选 additive 边界。"""

        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"Unknown tool: {name}")
        traced_invoke = getattr(tool, "invoke_with_trace", None)
        if callable(traced_invoke) and trace_context is not None:
            # 只有实现明确 hook 的 Trivae-owned tool 才接收 trace context，旧 handler 继续使用两参契约。
            return traced_invoke(request, scope, trace_context)
        return tool.invoke(request, scope)

    def names(self) -> tuple[str, ...]:
        """返回确定性 registry 名称列表。"""

        return tuple(sorted(self._tools))

    def metadata(self) -> tuple[CapabilityMetadata, ...]:
        """从已注册 Tool 所持 Capability 读取 canonical 描述。"""

        summaries = []
        for name, tool in sorted(self._tools.items()):
            # 每条描述必须来自当前注册的 Capability，不能按名字猜测另一套文档。
            capability = getattr(tool, "capability", None)
            metadata = getattr(capability, "metadata", None)
            if not isinstance(metadata, CapabilityMetadata) or metadata.name != name:
                raise ValueError(f"registered tool lacks matching capability metadata: {name}")
            summaries.append(metadata)
        return tuple(summaries)
