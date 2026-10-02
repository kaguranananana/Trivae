"""execute_sql Capability：在 trusted scope 内执行 bounded read-only SQL。"""

from __future__ import annotations

from trivae.capabilities.contracts import CapabilityContractError, CapabilityMetadata, ExecuteSQLInput, ExecutionScope
from trivae.retrieval.sql import (
    MAX_SQL_RESULT_ROWS,
    SQLQuery,
    SQLQueryResult,
    StructuredSQLError,
    StructuredSQLRepository,
)
from trivae.retrieval.structured import ScopeFilters


class SQLCapabilityError(CapabilityContractError):
    """把 SQL adapter 的稳定 owner error code 传回 Tool Envelope。"""

    def __init__(self, error_code: str, message: str) -> None:
        """保留原始 SQL contract owner code，不用 generic capability error 覆盖根因。"""

        self.error_code = error_code
        super().__init__(message)


class ExecuteSQLCapability:
    """把 model SQL 交给 scope-bound read adapter，不解析或改写 SQL 文本。"""

    metadata = CapabilityMetadata(
        name="execute_sql",
        description=(
            "Execute one bounded read-only SQL statement against the exposed canonical SQLite tables. "
            "The trusted ExecutionScope is enforced outside the SQL; no LIMIT is required in the statement."
        ),
        bounded=True,
        input_fields=("sql", "max_rows"),
    )

    def __init__(self, repository: StructuredSQLRepository) -> None:
        """复用同一个 canonical scoped SQL adapter。"""

        self.repository = repository

    def execute(self, request: ExecuteSQLInput, scope: ExecutionScope) -> SQLQueryResult:
        """先确定 trusted result bound，再执行不被改写的 SQL。"""

        if not isinstance(request, ExecuteSQLInput):
            raise CapabilityContractError("execute_sql received an invalid request type")
        # ToolResultRecord 的 100 item bound 同时是 SQL rows 的硬 transport 上限。
        trusted_limit = min(scope.max_results, MAX_SQL_RESULT_ROWS)
        effective_limit = trusted_limit if request.max_rows is None else request.max_rows
        if effective_limit > trusted_limit:
            raise CapabilityContractError("requested SQL max_rows exceeds trusted result bound")

        try:
            return self.repository.execute_readonly_sql(
                SQLQuery(sql=request.sql, max_rows=effective_limit),
                ScopeFilters(
                    session_ids=scope.allowed_session_ids,
                    start_timestamp=scope.start_timestamp,
                    end_timestamp=scope.end_timestamp,
                ),
            )
        except StructuredSQLError as exc:
            # 已知 SQL 错误交给 Agent 作为显式可恢复结果；不切换到 Retrieval 或改写 query。
            raise SQLCapabilityError(exc.error_code, str(exc)) from exc
