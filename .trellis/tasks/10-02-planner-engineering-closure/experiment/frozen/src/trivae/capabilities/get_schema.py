"""get_schema Capability：读取允许 Agent 使用的 Physical SQLite schema。"""

from __future__ import annotations

from trivae.capabilities.contracts import CapabilityContractError, CapabilityMetadata, ExecutionScope, GetSchemaInput
from trivae.retrieval.sql import SchemaResult, StructuredSQLRepository


class GetSchemaCapability:
    """复用 canonical read adapter 的 schema inspection，不创建 Analysis View。"""

    metadata = CapabilityMetadata(
        name="get_schema",
        description=(
            "Inspect the exposed physical SQLite schema before writing structured SQL. "
            "It returns canonical tables, public columns, and relationships; it does not return rows."
        ),
        bounded=True,
        input_fields=(),
    )

    def __init__(self, repository: StructuredSQLRepository) -> None:
        """只接收 Application 装配的 read port，不在 Capability 内打开连接。"""

        self.repository = repository

    def execute(self, request: GetSchemaInput, scope: ExecutionScope) -> SchemaResult:
        """校验无参数 request 后读取稳定 schema；schema inspection 不扩大 data scope。"""

        if not isinstance(request, GetSchemaInput):
            raise CapabilityContractError("get_schema received an invalid request type")
        # scope 仍作为 Capability contract 的显式输入，确保未来 schema metadata 不绕过 Runtime context。
        if not isinstance(scope, ExecutionScope):
            raise CapabilityContractError("get_schema requires ExecutionScope")
        return self.repository.read_schema()
