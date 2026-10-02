"""Structured SQLite schema 与只读 SQL 的 Retrieval-facing contract。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, Protocol

from trivae.config.limits import MAX_STRUCTURED_RESULT_ITEMS
from trivae.retrieval.structured import Coverage, RetrievalError, RetrievalMetadata, ScopeFilters

SQLScalar = bool | float | int | str | None

# ToolResultRecord 当前最多承载 100 个 structured item；SQL row bound 与该 transport contract 对齐。
MAX_SQL_RESULT_ROWS = MAX_STRUCTURED_RESULT_ITEMS


class StructuredSQLError(RetrievalError):
    """SQLite structured read 可以向 Tool 层明确投影的错误基类。"""

    error_code = "SQL_EXECUTION_ERROR"


class SQLMalformedError(StructuredSQLError):
    """SQL 语句无法被 SQLite 编译或不是单条可执行 statement。"""

    error_code = "SQL_MALFORMED"


class SQLReadOnlyViolation(StructuredSQLError):
    """SQL 试图写入、修改事务或改变 SQLite 连接状态。"""

    error_code = "SQL_READ_ONLY_VIOLATION"


class SQLScopeViolation(StructuredSQLError):
    """SQL 试图绕过当前 ExecutionScope 或访问未公开的 database。"""

    error_code = "SQL_SCOPE_VIOLATION"


class SQLSchemaViolation(StructuredSQLError):
    """SQL 访问了 Agent-facing schema 之外的表、列或 pragma。"""

    error_code = "SQL_SCHEMA_VIOLATION"


@dataclass(frozen=True)
class SQLQuery:
    """一次不改写原文、且带 adapter-level result bound 的 SQL 请求。"""

    sql: str
    max_rows: int

    def __post_init__(self) -> None:
        """在 Retrieval boundary 固定非空 SQL 与正的返回上限。"""

        if not isinstance(self.sql, str) or not self.sql.strip():
            raise ValueError("sql must be a non-empty string")
        object.__setattr__(self, "sql", self.sql.strip())
        if isinstance(self.max_rows, bool) or not isinstance(self.max_rows, int) or self.max_rows <= 0:
            raise ValueError("sql max_rows must be positive")
        if self.max_rows > MAX_SQL_RESULT_ROWS:
            raise ValueError(f"sql max_rows must not exceed {MAX_SQL_RESULT_ROWS}")

    def to_dict(self) -> dict[str, object]:
        """返回可进入 Tool Result metadata 的 query snapshot。"""

        return {"sql": self.sql, "max_rows": self.max_rows}


@dataclass(frozen=True)
class SchemaColumn:
    """Physical SQLite public column 的 bounded 描述。"""

    name: str
    data_type: str
    nullable: bool
    primary_key: bool
    default_value: str | None

    def to_dict(self) -> dict[str, object]:
        """投影模型理解 schema 所需的列约束。"""

        return {
            "name": self.name,
            "data_type": self.data_type,
            "nullable": self.nullable,
            "primary_key": self.primary_key,
            "default_value": self.default_value,
        }


@dataclass(frozen=True)
class SchemaForeignKey:
    """允许 Agent 连接的 public table relationship。"""

    column: str
    referenced_table: str
    referenced_column: str

    def to_dict(self) -> dict[str, str]:
        """返回稳定的关系投影，不暴露 SQLite pragma row。"""

        return {
            "column": self.column,
            "referenced_table": self.referenced_table,
            "referenced_column": self.referenced_column,
        }


@dataclass(frozen=True)
class SchemaTable:
    """一个 Agent-facing Physical SQLite table。"""

    name: str
    columns: tuple[SchemaColumn, ...]
    foreign_keys: tuple[SchemaForeignKey, ...]

    def to_dict(self) -> dict[str, object]:
        """将表、列和关系转换为 bounded plain values。"""

        return {
            "name": self.name,
            "columns": [column.to_dict() for column in self.columns],
            "foreign_keys": [foreign_key.to_dict() for foreign_key in self.foreign_keys],
        }


@dataclass(frozen=True)
class SchemaResult:
    """get_schema 的 schema-only structured result，不包含数据行。"""

    strategy: Literal["schema"]
    tables: tuple[SchemaTable, ...]
    coverage: Coverage
    partial: bool
    truncated: bool
    metadata: RetrievalMetadata

    def __post_init__(self) -> None:
        """固定 schema strategy，避免其他 SQL result 冒充 schema inspection。"""

        if self.strategy != "schema":
            raise ValueError("schema result strategy must be schema")

    def to_dict(self) -> dict[str, object]:
        """返回 Agent 可读的 schema 结构和执行事实。"""

        return {
            "strategy": self.strategy,
            "tables": [table.to_dict() for table in self.tables],
            "returned_tables": len(self.tables),
            "coverage": {"status": self.coverage.status, "basis": self.coverage.basis},
            "partial": self.partial,
            "truncated": self.truncated,
            "metadata": {
                "filters": dict(self.metadata.filters),
                "ordering": self.metadata.ordering,
                "latency_ms": self.metadata.latency_ms,
                "details": dict(self.metadata.details),
            },
        }


@dataclass(frozen=True)
class SQLQueryResult:
    """execute_sql 的 bounded structured rows。"""

    query: SQLQuery
    strategy: Literal["sql"]
    columns: tuple[str, ...]
    rows: tuple[Mapping[str, SQLScalar], ...]
    returned_rows: int
    coverage: Coverage
    partial: bool
    truncated: bool
    metadata: RetrievalMetadata

    def __post_init__(self) -> None:
        """保证 rows、columns 和返回计数在 Tool Result 中保持一致。"""

        if self.strategy != "sql":
            raise ValueError("SQL result strategy must be sql")
        if self.returned_rows != len(self.rows):
            raise ValueError("SQL returned_rows must match rows length")
        if any(tuple(row.keys()) != self.columns for row in self.rows):
            raise ValueError("SQL row columns must match result columns")

    def to_dict(self) -> dict[str, object]:
        """转换成 JSON-compatible SQL result，不追加 LIMIT 或改写 query。"""

        return {
            "strategy": self.strategy,
            "query": self.query.to_dict(),
            "columns": list(self.columns),
            "rows": [dict(row) for row in self.rows],
            "returned_rows": self.returned_rows,
            "coverage": {"status": self.coverage.status, "basis": self.coverage.basis},
            "partial": self.partial,
            "truncated": self.truncated,
            "metadata": {
                "filters": dict(self.metadata.filters),
                "ordering": self.metadata.ordering,
                "latency_ms": self.metadata.latency_ms,
                "details": dict(self.metadata.details),
            },
        }


class StructuredSQLRepository(Protocol):
    """Structured Capability 依赖的 schema/read-only SQL port。"""

    def read_schema(self) -> SchemaResult:
        """读取允许 Agent 理解的 Physical SQLite schema。"""

    def execute_readonly_sql(self, query: SQLQuery, scope: ScopeFilters) -> SQLQueryResult:
        """在给定 trusted scope 的隔离 read connection 上执行 SQL。"""
