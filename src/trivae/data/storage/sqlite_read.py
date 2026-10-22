"""SQLite Canonical Store 的 Retrieval read adapter。"""

from __future__ import annotations

import json
import sqlite3
from bisect import bisect_left, bisect_right
from collections.abc import Iterator
from heapq import merge
from pathlib import Path
from time import perf_counter
from typing import Literal

from trivae.data.ingestion.qq_forward import (
    FORWARD_PROJECTION_VERSION,
    ForwardMessageTree,
    project_forward_tree,
    split_forward_message_id,
)
from trivae.data.model import ChatSession
from trivae.data.storage.sqlite_forward import FORWARD_CONTENT_PREDICATE
from trivae.data.storage.sqlite_lexical_text import FTS_TOKENIZER_STRATEGY_ID, normalize_lexical_query_term
from trivae.retrieval.identity import (
    FindMembersResult,
    MemberCandidate,
    MemberMatch,
    MemberMatchField,
    MemberMatchKind,
    MemberQuery,
    MemberSession,
)
from trivae.retrieval.sql import (
    SchemaColumn,
    SchemaForeignKey,
    SchemaResult,
    SchemaTable,
    SQLMalformedError,
    SQLQuery,
    SQLQueryResult,
    SQLReadOnlyViolation,
    SQLSchemaViolation,
    SQLScopeViolation,
    StructuredSQLError,
)
from trivae.retrieval.structured import (
    AggregateBucket,
    AggregateData,
    AggregateQuery,
    CanonicalReadRepository,
    Coverage,
    LexicalIndexError,
    LexicalQuery,
    MessageHit,
    MessageProjection,
    MessageQuery,
    RetrievalError,
    RetrievalMetadata,
    ScopeFilters,
    message_sort_key,
)

# 只允许这些 canonical 列穿过 data/storage 到 Retrieval projection。
PROJECTION_COLUMNS = f"""
    m.internal_message_id,
    m.session_id,
    s.name AS session_display,
    m.source_message_id,
    m.sender_user_id,
    m.sender_platform_id,
    m.sender_uin,
    m.sender_name,
    m.timestamp,
    m.seq,
    m.message_type,
    m.content_text,
    m.reply_to_source_message_id,
    m.recalled,
    m.system,
    CASE WHEN {FORWARD_CONTENT_PREDICATE} THEN m.content_json END AS forward_content_json,
    CASE WHEN {FORWARD_CONTENT_PREDICATE} THEN (
        SELECT file_name FROM sources WHERE source_id = m.canonical_source_id
    ) END AS forward_source_file,
    m.canonical_source_record_index AS forward_source_record_index
"""

# 显式把 NULL seq 分到有 seq 之后；不能依赖 SQLite 的默认 NULL 排序。
ORDER_BY_SQL = """
    m.timestamp ASC,
    CASE WHEN m.seq IS NULL THEN 1 ELSE 0 END ASC,
    COALESCE(m.seq, 0) ASC,
    m.internal_message_id ASC
"""
ORDER_BY_SQL_DESC = """
    m.timestamp DESC,
    CASE WHEN m.seq IS NULL THEN 1 ELSE 0 END DESC,
    COALESCE(m.seq, 0) DESC,
    m.internal_message_id DESC
"""

# Agent-facing SQL 只暴露 canonical 的公共表和列；raw payload、导入诊断、source provenance
# 以及 lexical/semantic derived tables 继续留在内部 read boundary 之外。
PUBLIC_SQL_COLUMNS: dict[str, tuple[str, ...]] = {
    "chat_sessions": (
        "session_id",
        "platform",
        "external_chat_id",
        "name",
        "chat_type",
        "first_message_timestamp",
        "last_message_timestamp",
    ),
    "users": (
        "user_id",
        "platform",
        "platform_user_id",
        "platform_uin",
        "display_name",
        "nickname",
        "remark",
        "last_seen_timestamp",
    ),
    "memberships": (
        "session_id",
        "user_id",
        "display_name",
        "nickname",
        "group_card",
        "remark",
        "first_seen_timestamp",
        "last_seen_timestamp",
    ),
    "messages": (
        "internal_message_id",
        "session_id",
        "platform",
        "source_message_id",
        "seq",
        "timestamp",
        "message_type",
        "content_text",
        "sender_user_id",
        "sender_platform_id",
        "sender_uin",
        "sender_name",
        "reply_to_source_message_id",
        "recalled",
        "system",
    ),
}
PUBLIC_SQL_TABLES = tuple(PUBLIC_SQL_COLUMNS)


def _sql_scope_clause(scope: ScopeFilters, alias: str) -> tuple[str, list[object]]:
    """为 SQL scoped materialization 生成只包含 trusted session/time 边界的 predicate。"""

    clauses: list[str] = []
    parameters: list[object] = []
    if scope.session_ids is not None:
        placeholders = ", ".join("?" for _ in scope.session_ids)
        clauses.append(f"{alias}.session_id IN ({placeholders})")
        parameters.extend(scope.session_ids)
    if scope.start_timestamp is not None:
        clauses.append(f"{alias}.timestamp >= ?")
        parameters.append(scope.start_timestamp)
    if scope.end_timestamp is not None:
        clauses.append(f"{alias}.timestamp < ?")
        parameters.append(scope.end_timestamp)
    return (" AND ".join(clauses) if clauses else "1 = 1"), parameters


def _membership_scope_clause(scope: ScopeFilters, alias: str) -> tuple[str, list[object]]:
    """按 Membership 的观察区间裁剪 scope table，避免身份查询暴露越界群聊。"""

    clauses: list[str] = []
    parameters: list[object] = []
    if scope.session_ids is not None:
        placeholders = ", ".join("?" for _ in scope.session_ids)
        clauses.append(f"{alias}.session_id IN ({placeholders})")
        parameters.extend(scope.session_ids)
    if scope.start_timestamp is not None:
        clauses.append(f"({alias}.last_seen_timestamp IS NULL OR {alias}.last_seen_timestamp >= ?)")
        parameters.append(scope.start_timestamp)
    if scope.end_timestamp is not None:
        clauses.append(f"({alias}.first_seen_timestamp IS NULL OR {alias}.first_seen_timestamp < ?)")
        parameters.append(scope.end_timestamp)
    return (" AND ".join(clauses) if clauses else "1 = 1"), parameters


def _qualified_columns(table: str, alias: str) -> str:
    """只从静态 public column map 生成 SELECT 列表，不接受模型 SQL 片段。"""

    return ", ".join(f"{alias}.{column}" for column in PUBLIC_SQL_COLUMNS[table])


def _requires_scoped_materialization(scope: ScopeFilters) -> bool:
    """只有非全量 session/time scope 才需要建立隔离的 temporary public tables。"""

    return scope.session_ids is not None or scope.start_timestamp is not None or scope.end_timestamp is not None


def _unique_column_names(description: tuple[object, ...] | None) -> tuple[str, ...]:
    """为 JOIN 中重复列名建立稳定后缀，避免 dict 覆盖结果列。"""

    names: list[str] = []
    counts: dict[str, int] = {}
    for index, item in enumerate(description or ()):
        raw_name = item[0] if isinstance(item, tuple) and item else None
        base = str(raw_name) if isinstance(raw_name, str) and raw_name else f"column_{index + 1}"
        count = counts.get(base, 0) + 1
        counts[base] = count
        names.append(base if count == 1 else f"{base}_{count}")
    return tuple(names)


def _sql_scalar(value: object) -> bool | float | int | str | None:
    """将 SQLite scalar 投影为 Evidence/JSON 可承载的有限值。"""

    if value is None or isinstance(value, (bool, float, int, str)):
        return value
    # 当前 public canonical projection 没有 BLOB；不把未知二进制值偷偷转换成 Evidence 文本。
    raise SQLSchemaViolation(f"SQL returned unsupported value type: {type(value).__name__}")


def _sql_authorizer(
    action: int,
    first: str | None,
    second: str | None,
    database: str | None,
    _source: str | None,
    state: dict[str, str],
    allow_main: bool,
) -> int:
    """在 SQLite driver 层阻止写操作、内部表访问和 scoped data escape。"""

    write_actions = {
        sqlite3.SQLITE_ALTER_TABLE,
        sqlite3.SQLITE_ANALYZE,
        sqlite3.SQLITE_ATTACH,
        sqlite3.SQLITE_CREATE_INDEX,
        sqlite3.SQLITE_CREATE_TABLE,
        sqlite3.SQLITE_CREATE_TEMP_INDEX,
        sqlite3.SQLITE_CREATE_TEMP_TABLE,
        sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
        sqlite3.SQLITE_CREATE_TEMP_VIEW,
        sqlite3.SQLITE_CREATE_TRIGGER,
        sqlite3.SQLITE_CREATE_VIEW,
        sqlite3.SQLITE_CREATE_VTABLE,
        sqlite3.SQLITE_DELETE,
        sqlite3.SQLITE_DETACH,
        sqlite3.SQLITE_DROP_INDEX,
        sqlite3.SQLITE_DROP_TABLE,
        sqlite3.SQLITE_DROP_TEMP_INDEX,
        sqlite3.SQLITE_DROP_TEMP_TABLE,
        sqlite3.SQLITE_DROP_TEMP_TRIGGER,
        sqlite3.SQLITE_DROP_TEMP_VIEW,
        sqlite3.SQLITE_DROP_TRIGGER,
        sqlite3.SQLITE_DROP_VIEW,
        sqlite3.SQLITE_DROP_VTABLE,
        sqlite3.SQLITE_INSERT,
        sqlite3.SQLITE_REINDEX,
        sqlite3.SQLITE_SAVEPOINT,
        sqlite3.SQLITE_TRANSACTION,
        sqlite3.SQLITE_UPDATE,
    }
    if action in write_actions:
        state["code"] = SQLReadOnlyViolation.error_code
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_PRAGMA:
        state["code"] = SQLSchemaViolation.error_code
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION:
        function_name = (second or first or "").lower()
        if function_name in {"eval", "load_extension", "writefile"} or function_name.startswith("pragma_"):
            state["code"] = SQLSchemaViolation.error_code
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE}:
        return sqlite3.SQLITE_OK
    if action != sqlite3.SQLITE_READ:
        return sqlite3.SQLITE_OK

    table = first or ""
    column = second or ""
    allowed_columns = PUBLIC_SQL_COLUMNS.get(table)
    # SQLite 用空列名表示 COUNT(*)/EXISTS 等只需要读取表行的操作；仍要求表本身 public。
    if allowed_columns is None or (column and column not in allowed_columns):
        state["code"] = SQLSchemaViolation.error_code
        return sqlite3.SQLITE_DENY
    # SQLite 对未限定表名的 READ callback 在当前 driver 返回 None；partial scope 已为全部 public
    # 表建立同名 temp shadow，因此 None 在该分支只会命中 scoped temp table。
    if database == "main" and not allow_main:
        state["code"] = SQLScopeViolation.error_code
        return sqlite3.SQLITE_DENY
    if database not in {"main", "temp", None}:
        state["code"] = SQLScopeViolation.error_code
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _readonly_uri(database_path: Path) -> str:
    """使用 SQLite mode=ro，避免 Retrieval 意外创建/修改 canonical 文件。"""

    return f"{database_path.resolve().as_uri()}?mode=ro"


def _where_clause(scope: ScopeFilters, alias: str = "m") -> tuple[str, list[object]]:
    """集中生成 scope predicates；所有外部值都进入 parameter binding。"""

    clauses: list[str] = []
    parameters: list[object] = []

    if scope.session_ids is not None:
        placeholders = ", ".join("?" for _ in scope.session_ids)
        clauses.append(f"{alias}.session_id IN ({placeholders})")
        parameters.extend(scope.session_ids)
    if scope.start_timestamp is not None:
        clauses.append(f"{alias}.timestamp >= ?")
        parameters.append(scope.start_timestamp)
    if scope.end_timestamp is not None:
        clauses.append(f"{alias}.timestamp < ?")
        parameters.append(scope.end_timestamp)
    before_cursor = getattr(scope, "before_cursor", None)
    if before_cursor is not None:
        # 复用 canonical ordering 的四元组做严格小于比较，保证同 timestamp/NULL seq 不重不漏。
        cursor_seq_present = 1 if before_cursor.seq is None else 0
        cursor_seq = before_cursor.seq if before_cursor.seq is not None else 0
        clauses.append(
            f"({alias}.timestamp, "
            f"CASE WHEN {alias}.seq IS NULL THEN 1 ELSE 0 END, "
            f"COALESCE({alias}.seq, 0), {alias}.internal_message_id) "
            "< (?, ?, ?, ?)"
        )
        parameters.extend(
            (
                before_cursor.timestamp,
                cursor_seq_present,
                cursor_seq,
                before_cursor.internal_message_id,
            )
        )
    if scope.sender_user_ids is not None:
        placeholders = ", ".join("?" for _ in scope.sender_user_ids)
        clauses.append(f"{alias}.sender_user_id IN ({placeholders})")
        parameters.extend(scope.sender_user_ids)
    if scope.message_types is not None:
        placeholders = ", ".join("?" for _ in scope.message_types)
        clauses.append(f"{alias}.message_type IN ({placeholders})")
        parameters.extend(scope.message_types)
    if scope.source_message_id is not None:
        clauses.append(f"{alias}.source_message_id = ?")
        parameters.append(scope.source_message_id)
    if scope.reply_to_source_message_id is not None:
        clauses.append(f"{alias}.reply_to_source_message_id = ?")
        parameters.append(scope.reply_to_source_message_id)

    return (" AND ".join(clauses) if clauses else "1 = 1"), parameters


def _row_to_forward_tree(row: sqlite3.Row) -> ForwardMessageTree:
    """canonical root 是唯一事实来源；JSON 只在 storage 边界内参与子消息恢复。"""

    projection = MessageProjection(
        internal_message_id=str(row["internal_message_id"]),
        session_id=str(row["session_id"]),
        session_display=str(row["session_display"] or ""),
        source_message_id=row["source_message_id"],
        sender_user_id=row["sender_user_id"],
        sender_platform_id=row["sender_platform_id"],
        sender_uin=row["sender_uin"],
        sender_name=row["sender_name"],
        timestamp=int(row["timestamp"]),
        seq=None if row["seq"] is None else int(row["seq"]),
        message_type=str(row["message_type"]),
        normalized_content=str(row["content_text"]),
        reply_to_source_message_id=row["reply_to_source_message_id"],
        recalled=bool(row["recalled"]),
        system=bool(row["system"]),
    )
    if row["forward_content_json"] is None:
        return ForwardMessageTree(root=projection, messages=())
    return project_forward_tree(
        projection,
        json.loads(row["forward_content_json"]),
        source_file=row["forward_source_file"],
        source_record_index=int(row["forward_source_record_index"]),
    )


def _row_to_projection(row: sqlite3.Row) -> MessageProjection:
    """把限定列转换为 retrieval-owned projection，不返回 sqlite3.Row 或 raw JSON。"""

    return _row_to_forward_tree(row).root


def _fts_match_expression(query: LexicalQuery) -> str:
    """把关键词转换为 literal AND 查询，禁止用户输入改变 SQL 结构。

    每个 term 先经过与 rebuild 一致的 CJK bigram 归一化，再把归一化结果整体
    作为单个 quoted phrase：多个 bigram token 保序匹配等价于 Han run 子串
    命中；纯 ASCII term 归一化后不变，unicode61 exact 语义保持原样。
    """

    # FTS5 的 MATCH 文本仍作为参数绑定；双引号只用于 literal token 语义。
    return " AND ".join(
        f'"{normalize_lexical_query_term(term).replace(chr(34), chr(34) * 2)}"'
        for term in query.terms
    )


def _member_where_clause(scope: ScopeFilters) -> tuple[str, list[object]]:
    """生成 Membership scope predicates，不让模型输入改变 SQL 结构。"""

    clauses: list[str] = []
    parameters: list[object] = []
    if scope.session_ids is not None:
        placeholders = ", ".join("?" for _ in scope.session_ids)
        clauses.append(f"m.session_id IN ({placeholders})")
        parameters.extend(scope.session_ids)
    if scope.start_timestamp is not None:
        # Membership 的观察区间与查询范围有交集时，才把候选暴露给 Agent。
        clauses.append("(m.last_seen_timestamp IS NULL OR m.last_seen_timestamp >= ?)")
        parameters.append(scope.start_timestamp)
    if scope.end_timestamp is not None:
        clauses.append("(m.first_seen_timestamp IS NULL OR m.first_seen_timestamp < ?)")
        parameters.append(scope.end_timestamp)
    return (" AND ".join(clauses) if clauses else "1 = 1"), parameters


def _escape_like(value: str) -> str:
    """把身份查询中的通配符当作普通字符，避免模型改变 LIKE 语义。"""

    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _member_match_clause(query: str) -> tuple[str, list[object]]:
    """在稳定 UserIdentity 与局部 Membership 字段上执行 exact/contains 候选筛选。"""

    fields = (
        "u.platform_user_id",
        "u.platform_uin",
        "u.display_name",
        "u.nickname",
        "u.remark",
        "m.display_name",
        "m.nickname",
        "m.group_card",
        "m.remark",
    )
    escaped = _escape_like(query)
    clauses: list[str] = []
    parameters: list[object] = []
    for field in fields:
        # exact 命中优先由 Python 侧排序，SQL 同时保留 contains 以支持局部昵称查询。
        clauses.append(
            f"(lower(COALESCE({field}, '')) = lower(?) "
            f"OR lower(COALESCE({field}, '')) LIKE lower(?) ESCAPE '\\')"
        )
        parameters.extend((query, f"%{escaped}%"))
    return " OR ".join(clauses), parameters


def _member_match(value: object, query: str) -> tuple[MemberMatchKind, str] | None:
    """计算单个显示字段的 exact/partial 匹配种类。"""

    if not isinstance(value, str) or not value:
        return None
    normalized_value = value.casefold()
    normalized_query = query.casefold()
    if normalized_value == normalized_query:
        return "exact", value
    if normalized_query in normalized_value:
        return "partial", value
    return None


def _member_candidates_from_rows(
    rows: list[sqlite3.Row],
    query: str,
) -> tuple[MemberCandidate, ...]:
    """将多条 session membership row 合并成稳定 UserIdentity 候选。"""

    candidates: dict[str, dict[str, object]] = {}
    field_specs: tuple[tuple[MemberMatchField, Literal["user", "membership"], str], ...] = (
        ("platform_user_id", "user", "platform_user_id"),
        ("platform_uin", "user", "platform_uin"),
        ("display_name", "user", "user_display_name"),
        ("nickname", "user", "user_nickname"),
        ("remark", "user", "user_remark"),
        ("display_name", "membership", "membership_display_name"),
        ("nickname", "membership", "membership_nickname"),
        ("group_card", "membership", "group_card"),
        ("remark", "membership", "membership_remark"),
    )
    for row in rows:
        user_id = str(row["user_id"])
        state = candidates.setdefault(
            user_id,
            {
                "user_id": user_id,
                "platform": str(row["platform"]),
                "platform_user_id": str(row["platform_user_id"]),
                "platform_uin": row["platform_uin"],
                "display_name": row["user_display_name"],
                "nickname": row["user_nickname"],
                "remark": row["user_remark"],
                "memberships": [],
                "matches": [],
            },
        )
        memberships = state["memberships"]
        if not isinstance(memberships, list):
            raise RetrievalError("Member candidate membership projection is invalid")
        memberships.append(
            MemberSession(
                session_id=str(row["session_id"]),
                session_display=str(row["session_display"] or ""),
                display_name=row["membership_display_name"],
                nickname=row["membership_nickname"],
                group_card=row["group_card"],
                remark=row["membership_remark"],
                first_seen_timestamp=(
                    None if row["first_seen_timestamp"] is None else int(row["first_seen_timestamp"])
                ),
                last_seen_timestamp=(
                    None if row["last_seen_timestamp"] is None else int(row["last_seen_timestamp"])
                ),
            )
        )
        matches = state["matches"]
        if not isinstance(matches, list):
            raise RetrievalError("Member candidate match projection is invalid")
        for field, owner, column in field_specs:
            matched = _member_match(row[column], query)
            if matched is None:
                continue
            kind, value = matched
            match = MemberMatch(field=field, owner=owner, kind=kind, value=value)
            if not any(
                existing.field == match.field
                and existing.owner == match.owner
                and existing.kind == match.kind
                and existing.value == match.value
                for existing in matches
            ):
                matches.append(match)

    output: list[MemberCandidate] = []
    for state in candidates.values():
        memberships = state["memberships"]
        matches = state["matches"]
        if not isinstance(memberships, list) or not isinstance(matches, list):
            raise RetrievalError("Member candidate projection cannot be materialized")
        output.append(
            MemberCandidate(
                user_id=str(state["user_id"]),
                platform=str(state["platform"]),
                platform_user_id=str(state["platform_user_id"]),
                platform_uin=state["platform_uin"] if isinstance(state["platform_uin"], str) else None,
                display_name=state["display_name"] if isinstance(state["display_name"], str) else None,
                nickname=state["nickname"] if isinstance(state["nickname"], str) else None,
                remark=state["remark"] if isinstance(state["remark"], str) else None,
                memberships=tuple(memberships),
                matches=tuple(matches),
            )
        )
    return tuple(output)


class SQLiteCanonicalReadRepository(CanonicalReadRepository):
    """只读读取 adapter，集中承载 Structured、Lexical 和 Context SQL。"""

    def __init__(self, database_path: Path) -> None:
        # 保存 resolved path，execute_sql 为每次 scope 建立隔离 read connection。
        self._database_path = database_path.resolve()
        self._connection = sqlite3.connect(_readonly_uri(self._database_path), uri=True)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA query_only = ON")
        self._connection.execute("PRAGMA foreign_keys = ON")
        # 只缓存缺失路径与计数，不缓存消息正文；canonical revision 改变即整批失效。
        self._forward_inventory: tuple[int, int, tuple[tuple[str, int, str], ...]] | None = None

    def close(self) -> None:
        """释放独立 read connection；Application 负责调用此生命周期方法。"""

        self._connection.close()

    def list_sessions(self) -> tuple[ChatSession, ...]:
        """读取 Canonical Store 中实际存在的 session metadata。"""

        # 只读取群聊选择所需的 canonical 字段，不把 sqlite row 暴露给上层。
        rows = self._connection.execute(
            """
            SELECT session_id, platform, external_chat_id, name, chat_type, self_uid, self_uin
            FROM chat_sessions
            ORDER BY name COLLATE NOCASE ASC, session_id ASC
            """
        ).fetchall()
        # 复用 Canonical ChatSession 模型，保证展示用名称和 Query scope 使用同一 session identity。
        return tuple(
            ChatSession(
                platform=str(row["platform"]),
                external_chat_id=str(row["external_chat_id"]),
                name=str(row["name"]),
                chat_type=str(row["chat_type"]),
                self_uid=row["self_uid"],
                self_uin=row["self_uin"],
            )
            for row in rows
        )

    def read_schema(self) -> SchemaResult:
        """读取 public Physical SQLite schema，不把内部 ingestion/derived 表交给 Agent。"""

        started = perf_counter()
        tables: list[SchemaTable] = []
        for table_name in PUBLIC_SQL_TABLES:
            # 表名来自静态 public map，不接受模型提供的 identifier，PRAGMA 只读物理 schema metadata。
            table_info = self._connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
            if not table_info:
                raise RetrievalError(f"public SQL table is missing: {table_name}")
            allowed_columns = set(PUBLIC_SQL_COLUMNS[table_name])
            columns = tuple(
                SchemaColumn(
                    name=str(row["name"]),
                    data_type=str(row["type"] or ""),
                    nullable=not bool(row["notnull"]),
                    primary_key=bool(row["pk"]),
                    default_value=None if row["dflt_value"] is None else str(row["dflt_value"]),
                )
                for row in table_info
                if str(row["name"]) in allowed_columns
            )
            foreign_keys = tuple(
                SchemaForeignKey(
                    column=str(row["from"]),
                    referenced_table=str(row["table"]),
                    referenced_column=str(row["to"]),
                )
                for row in self._connection.execute(f'PRAGMA foreign_key_list("{table_name}")').fetchall()
                if str(row["from"]) in allowed_columns and str(row["table"]) in PUBLIC_SQL_COLUMNS
            )
            tables.append(SchemaTable(table_name, columns, foreign_keys))
        return SchemaResult(
            strategy="schema",
            tables=tuple(tables),
            coverage=Coverage(status="complete", basis="canonical_physical_schema_public_projection"),
            partial=False,
            truncated=False,
            metadata=RetrievalMetadata(
                filters={"tables": PUBLIC_SQL_TABLES},
                ordering="public table declaration order, physical column order",
                latency_ms=(perf_counter() - started) * 1000,
                details={
                    "exposed_tables": PUBLIC_SQL_TABLES,
                    "hidden_table_policy": "canonical_public_tables_only",
                },
            ),
        )

    def execute_readonly_sql(self, query: SQLQuery, scope: ScopeFilters) -> SQLQueryResult:
        """在隔离 SQLite connection 上执行原始 SQL，并用 driver authorizer enforcement scope。"""

        started = perf_counter()
        connection = sqlite3.connect(_readonly_uri(self._database_path), uri=True)
        connection.row_factory = sqlite3.Row
        state: dict[str, str] = {}
        allow_main = not _requires_scoped_materialization(scope)
        try:
            # bootstrap 阶段只做 adapter 自己的 temp-table materialization，不执行模型 SQL。
            if not allow_main:
                self._prepare_scoped_sql_connection(connection, scope)
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA query_only = ON")
            connection.set_authorizer(
                lambda action, first, second, database, source: _sql_authorizer(
                    action,
                    first,
                    second,
                    database,
                    source,
                    state,
                    allow_main,
                )
            )
            cursor = connection.execute(query.sql)
            columns = _unique_column_names(cursor.description)
            raw_rows = cursor.fetchmany(query.max_rows + 1)
            truncated = len(raw_rows) > query.max_rows
            selected_rows = raw_rows[: query.max_rows]
            rows = tuple(
                {
                    column: _sql_scalar(row[index])
                    for index, column in enumerate(columns)
                }
                for row in selected_rows
            )
            return SQLQueryResult(
                query=query,
                strategy="sql",
                columns=columns,
                rows=rows,
                returned_rows=len(rows),
                coverage=Coverage(status="complete", basis="canonical_store_execution_scope"),
                partial=False,
                truncated=truncated,
                metadata=RetrievalMetadata(
                    filters={"scope": scope.scope_dict()},
                    ordering="SQLite statement ordering",
                    latency_ms=(perf_counter() - started) * 1000,
                    details={
                        "result_bound": query.max_rows,
                        "rows_observed": len(raw_rows),
                        "scope_enforcement": (
                            "scope_filtered_temp_tables_and_sqlite_authorizer"
                            if not allow_main
                            else "sqlite_authorizer_full_canonical_scope"
                        ),
                        "sql_rewritten": False,
                    },
                ),
            )
        except sqlite3.Error as exc:
            self._raise_sql_error(exc, state)
            raise AssertionError("_raise_sql_error must always raise")
        finally:
            connection.close()

    def _prepare_scoped_sql_connection(self, connection: sqlite3.Connection, scope: ScopeFilters) -> None:
        """在 authorizer 安装前建立只含 trusted scope 的 public temporary tables。"""

        message_scope, message_parameters = _sql_scope_clause(scope, "m")
        connection.execute(
            f"CREATE TEMP TABLE messages AS SELECT {_qualified_columns('messages', 'm')} "
            f"FROM main.messages AS m WHERE {message_scope}",
            message_parameters,
        )
        connection.execute(
            f"CREATE TEMP TABLE chat_sessions AS "
            f"SELECT {_qualified_columns('chat_sessions', 's')} FROM main.chat_sessions AS s "
            f"WHERE EXISTS (SELECT 1 FROM main.messages AS m WHERE m.session_id = s.session_id AND {message_scope})",
            message_parameters,
        )
        membership_scope, membership_parameters = _membership_scope_clause(scope, "m")
        connection.execute(
            f"CREATE TEMP TABLE memberships AS SELECT {_qualified_columns('memberships', 'm')} "
            f"FROM main.memberships AS m WHERE {membership_scope}",
            membership_parameters,
        )
        connection.execute(
            f"CREATE TEMP TABLE users AS SELECT {_qualified_columns('users', 'u')} FROM main.users AS u "
            f"WHERE EXISTS (SELECT 1 FROM main.memberships AS m WHERE m.user_id = u.user_id AND {membership_scope})",
            membership_parameters,
        )

    @staticmethod
    def _raise_sql_error(exc: sqlite3.Error, state: dict[str, str]) -> None:
        """把 SQLite driver failure 映射为稳定 SQL owner error，不返回原始 connection/path。"""

        code = state.get("code")
        message = str(exc).strip() or "SQLite rejected the statement"
        if code == SQLReadOnlyViolation.error_code:
            raise SQLReadOnlyViolation("read-only SQL statement was rejected") from exc
        if code == SQLScopeViolation.error_code:
            raise SQLScopeViolation("SQL attempted to access data outside the trusted scope") from exc
        if code == SQLSchemaViolation.error_code:
            raise SQLSchemaViolation("SQL accessed a table, column, function, or pragma outside the public schema") from exc
        # SQLite compilation errors are actionable model input errors; preserve only the bounded driver message.
        if isinstance(exc, (sqlite3.OperationalError, sqlite3.ProgrammingError)):
            # SQLite 对不存在的列/表可能在 authorizer 回调前就失败，无法依赖 state 中的 schema code。
            # 这些解析错误属于 public schema contract，而不是 SQL 语法本身错误。
            schema_error_prefixes = ("no such table:", "no such column:", "no such function:")
            if message.lower().startswith(schema_error_prefixes):
                raise SQLSchemaViolation("SQL referenced a table, column, or function outside the public schema") from exc
            raise SQLMalformedError(message) from exc
        raise StructuredSQLError("read-only SQL execution failed") from exc

    def count_messages(self, query: MessageQuery) -> int:
        """统计同一 scope 的所有 canonical message。"""

        where_sql, parameters = _where_clause(query)
        row = self._connection.execute(
            f"SELECT COUNT(*) AS total FROM messages AS m WHERE {where_sql}",
            parameters,
        ).fetchone()
        if row is None:
            raise RetrievalError("Structured count returned no scalar row")
        return int(row["total"])

    def latest_message_timestamp(self, scope: ScopeFilters) -> int | None:
        """只在 trusted scope 内求 archive latest，不使用 machine current time。"""

        where_sql, parameters = _where_clause(scope)
        row = self._connection.execute(
            f"SELECT MAX(m.timestamp) AS latest_timestamp FROM messages AS m WHERE {where_sql}",
            parameters,
        ).fetchone()
        if row is None:
            raise RetrievalError("Archive latest query returned no scalar row")
        value = row["latest_timestamp"]
        return None if value is None else int(value)

    def read_messages(self, query: MessageQuery) -> tuple[MessageProjection, ...]:
        """读取限定列，并使用显式 NULL seq ordering 和 bounded LIMIT。"""

        where_sql, parameters = _where_clause(query)
        rows = self._connection.execute(
            f"""
            SELECT {PROJECTION_COLUMNS}
            FROM messages AS m
            INNER JOIN chat_sessions AS s ON s.session_id = m.session_id
            WHERE {where_sql}
            ORDER BY {ORDER_BY_SQL}
            LIMIT ?
            """,
            [*parameters, query.limit],
        ).fetchall()
        return tuple(_row_to_projection(row) for row in rows)

    def read_recent_messages(self, query: MessageQuery) -> tuple[MessageProjection, ...]:
        """先从时间范围选取最新 limit 条，再按自然聊天阅读顺序返回。

        selection 使用与 canonical ordering 完全镜像的 DESC 语义取窗口尾部，
        随后在 Python 端反转；模型看到的仍是 chronological ASC 阅读顺序。
        """

        where_sql, parameters = _where_clause(query)
        rows = self._connection.execute(
            f"""
            SELECT {PROJECTION_COLUMNS}
            FROM messages AS m
            INNER JOIN chat_sessions AS s ON s.session_id = m.session_id
            WHERE {where_sql}
            ORDER BY {ORDER_BY_SQL_DESC}
            LIMIT ?
            """,
            [*parameters, query.limit],
        ).fetchall()
        return tuple(_row_to_projection(row) for row in reversed(rows))

    def read_message_by_id(self, internal_message_id: str) -> MessageProjection | None:
        """按全局稳定 internal message ID 读取限定 canonical projection。"""

        if not isinstance(internal_message_id, str) or not internal_message_id:
            raise ValueError("internal_message_id must be a non-empty string")
        locator = split_forward_message_id(internal_message_id)
        root_id = internal_message_id if locator is None else locator[0]
        row = self._connection.execute(
            f"""
            SELECT {PROJECTION_COLUMNS}
            FROM messages AS m
            INNER JOIN chat_sessions AS s ON s.session_id = m.session_id
            WHERE m.internal_message_id = ?
            """,
            (root_id,),
        ).fetchone()
        if row is None:
            return None
        tree = _row_to_forward_tree(row)
        if locator is None:
            return tree.root
        # 不查询 forwarded_messages 正文；由 root 的原始 JSON 逐条恢复并核对 occurrence。
        return next((message for message in tree.messages if message.internal_message_id == internal_message_id), None)

    def canonical_revision(self) -> int:
        """动态读取单调版本，索引不能接受缺少变更追踪的数据库。"""

        try:
            row = self._connection.execute(
                "SELECT value FROM trivae_derived_meta WHERE key = 'canonical_revision'"
            ).fetchone()
        except sqlite3.OperationalError as exc:
            raise RetrievalError("Canonical revision is unavailable; initialize the canonical store first") from exc
        if row is None:
            raise RetrievalError("Canonical revision is unavailable; initialize the canonical store first")
        return int(row["value"])

    def semantic_change_ranges(
        self, since_revision: int, gap_seconds: int
    ) -> tuple[tuple[str, int | None, int | None], ...]:
        """用持久旧、新位置与当前消息合并连通段，只扫描受影响时间邻域。"""

        if isinstance(since_revision, bool) or not isinstance(since_revision, int) or since_revision < 0:
            raise ValueError("since_revision must be non-negative")
        if isinstance(gap_seconds, bool) or not isinstance(gap_seconds, int) or gap_seconds < 0:
            raise ValueError("gap_seconds must be non-negative")
        revision = self.canonical_revision()
        try:
            baseline = self._connection.execute(
                "SELECT value FROM trivae_derived_meta WHERE key = 'semantic_changes_baseline_revision'"
            ).fetchone()
            rows = self._connection.execute(
                "SELECT * FROM canonical_message_changes WHERE revision > ? AND revision <= ? ORDER BY revision",
                (since_revision, revision),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            raise RetrievalError(f"Semantic mutation history is unavailable; rebuild the index: {exc}") from exc
        # 修订必须逐条连续覆盖，旧库迁移水位之前的变更不能作为安全增量输入。
        if (
            baseline is None
            or since_revision < int(baseline["value"])
            or since_revision > revision
            or len(rows) != revision - since_revision
        ):
            raise RetrievalError("Semantic mutation history does not cover the indexed revision; rebuild the index")
        dirty: dict[str, set[int]] = {}
        whole_sessions: set[str] = set()
        for row in rows:
            for prefix in ("old", "new"):
                session = row[f"{prefix}_session_id"]
                timestamp = row[f"{prefix}_timestamp"]
                if session is None:
                    continue
                if timestamp is None:
                    whole_sessions.add(str(session))
                else:
                    dirty.setdefault(str(session), set()).add(int(timestamp))
        ranges: list[tuple[str, int | None, int | None]] = []
        for session in sorted(dirty.keys() | whole_sessions):
            if session in whole_sessions:
                ranges.append((session, None, None))
                continue
            timestamps = sorted(dirty[session])
            covered_end: int | None = None
            for timestamp in timestamps:
                # 前一连通段已包含此 mutation 时不重复扫描，也不生成重叠发布范围。
                if covered_end is not None and timestamp <= covered_end:
                    continue
                start = self._semantic_connected_boundary(session, timestamp, timestamps, gap_seconds, reverse=True)
                end = self._semantic_connected_boundary(session, timestamp, timestamps, gap_seconds, reverse=False)
                ranges.append((session, start, end))
                covered_end = end
        # 多条只读语句期间发生写入时，范围不再属于同一个 canonical snapshot。
        if self.canonical_revision() != revision:
            raise RetrievalError("Canonical messages changed while reading semantic mutation ranges")
        return tuple(ranges)

    def _semantic_connected_boundary(
        self, session_id: str, anchor: int, mutations: list[int], gap_seconds: int, *, reverse: bool
    ) -> int:
        """将已删除的旧时间戳作为虚拟连接点，避免删除桥接消息后漏掉原 parent 的另一半。"""

        operator, ordering = ("<=", "DESC") if reverse else (">=", "ASC")
        cursor = self._connection.execute(
            f"""SELECT DISTINCT timestamp FROM messages
                WHERE session_id = ? AND timestamp {operator} ? ORDER BY timestamp {ordering}""",
            (session_id, anchor),
        )
        # 两个有序流共同决定连通性；只读取时间，不读取正文或遍历其他会话。
        virtual = (
            reversed(mutations[:bisect_right(mutations, anchor)])
            if reverse else iter(mutations[bisect_left(mutations, anchor):])
        )
        boundary = anchor
        try:
            for timestamp in merge((int(row[0]) for row in cursor), virtual, reverse=reverse):
                # canonical timestamp 使用毫秒；与 chunker 的 gap_seconds × 1000 保持一致。
                if abs(timestamp - boundary) > gap_seconds * 1000:
                    break
                boundary = timestamp
        finally:
            # 在连通段边界提前停止后立即释放 SQLite statement。
            cursor.close()
        return boundary

    def _iter_forward_trees(
        self,
        batch_size: int,
        scope: ScopeFilters | None = None,
    ) -> Iterator[ForwardMessageTree]:
        """只读取包含 forward element 的 canonical roots，并保留 first-wins 来源。"""

        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
            raise ValueError("forward batch_size must be positive")
        where_sql, parameters = _where_clause(scope or ScopeFilters())
        cursor = self._connection.execute(
            f"""
            SELECT {PROJECTION_COLUMNS}
            FROM messages AS m
            INNER JOIN chat_sessions AS s ON s.session_id = m.session_id
            WHERE {FORWARD_CONTENT_PREDICATE} AND {where_sql}
            ORDER BY m.session_id ASC, {ORDER_BY_SQL}
            """,
            parameters,
        )
        while rows := cursor.fetchmany(batch_size):
            for row in rows:
                yield _row_to_forward_tree(row)

    def iter_forwarded_messages(
        self, batch_size: int, *, scope: ScopeFilters | None = None
    ) -> Iterator[MessageProjection]:
        """semantic 使用独立 DFS 流；无需先建立 FTS 或信任派生正文。"""

        for tree in self._iter_forward_trees(batch_size, scope):
            yield from tree.messages

    def count_forwarded_messages(self) -> int:
        """统计转发 occurrence；不把它混入普通消息数量与成员事实。"""

        return self._read_forward_inventory()[1]

    def _read_forward_inventory(self) -> tuple[int, int, tuple[tuple[str, int, str], ...]]:
        """一次遍历建立轻量覆盖清单，避免每次检索重新解析全库 JSON。"""

        revision = self.canonical_revision()
        if self._forward_inventory is not None and self._forward_inventory[0] == revision:
            return self._forward_inventory
        count = 0
        gaps: list[tuple[str, int, str]] = []
        for tree in self._iter_forward_trees(256):
            count += len(tree.messages)
            gaps.extend(
                (tree.root.session_id, tree.root.timestamp, f"{tree.root.internal_message_id}:{path}")
                for path in tree.root.unexpanded_forward_paths
            )
        # 版本跨遍历变化意味着无法给出一致覆盖事实，必须让调用方看到失败。
        if self.canonical_revision() != revision:
            raise RetrievalError("Canonical messages changed while reading forward coverage")
        self._forward_inventory = (revision, count, tuple(gaps))
        return self._forward_inventory

    def forward_content_gaps(self, scope: ScopeFilters) -> tuple[str, ...]:
        """按当前群和转发时间表达导出缺失，即使查询零命中也不宣称完整覆盖。"""

        # 缺失正文无法证明发送者或类型，覆盖事实只受已知的外层群聊/时间范围约束。
        return tuple(
            locator
            for session_id, timestamp, locator in self._read_forward_inventory()[2]
            if (scope.session_ids is None or session_id in scope.session_ids)
            and (scope.start_timestamp is None or timestamp >= scope.start_timestamp)
            and (scope.end_timestamp is None or timestamp < scope.end_timestamp)
        )

    def iter_semantic_messages(
        self, batch_size: int, *, scope: ScopeFilters | None = None
    ) -> Iterator[MessageProjection]:
        """以 cursor/fetchmany 流式读取全量 canonical projection，避免 build 一次性载入消息。"""

        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
            raise ValueError("semantic batch_size must be positive")
        where_sql, parameters = _where_clause(scope or ScopeFilters())
        cursor = self._connection.execute(
            f"""
            SELECT {PROJECTION_COLUMNS}
            FROM messages AS m
            INNER JOIN chat_sessions AS s ON s.session_id = m.session_id
            WHERE {where_sql}
            ORDER BY m.session_id ASC, {ORDER_BY_SQL}
            """,
            parameters,
        )
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                return
            for row in rows:
                yield _row_to_projection(row)

    def aggregate_messages(self, query: AggregateQuery) -> AggregateData:
        """执行固定 group mapping；group 名不会作为 SQL 片段拼接。"""

        where_sql, parameters = _where_clause(query)
        total_row = self._connection.execute(
            f"SELECT COUNT(*) AS total FROM messages AS m WHERE {where_sql}",
            parameters,
        ).fetchone()
        if total_row is None:
            raise RetrievalError("Aggregate count returned no scalar row")
        total_count = int(total_row["total"])

        if query.group_by is None:
            return AggregateData(total_count=total_count, buckets=())

        group_expression = {
            "session": "m.session_id",
            "sender": "m.sender_user_id",
            "month": "strftime('%Y-%m', m.timestamp / 1000, 'unixepoch')",
        }[query.group_by]
        rows = self._connection.execute(
            f"""
            SELECT {group_expression} AS group_key, COUNT(*) AS item_count
            FROM messages AS m
            WHERE {where_sql}
            GROUP BY {group_expression}
            ORDER BY group_key IS NOT NULL ASC, group_key ASC
            """,
            parameters,
        ).fetchall()
        buckets = tuple(
            AggregateBucket(
                group_key=None if row["group_key"] is None else str(row["group_key"]),
                count=int(row["item_count"]),
            )
            for row in rows
        )
        return AggregateData(total_count=total_count, buckets=buckets)

    def _ensure_lexical_ready(self) -> None:
        """显式区分 index 缺失、stale 与 canonical data 问题，不做 LIKE 降级。"""

        table = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'messages_fts'"
        ).fetchone()
        if table is None:
            raise LexicalIndexError("messages_fts is unavailable; rebuild the derived index first")

        # rebuild 归一化 strategy 必须与 read 侧完全一致；不一致说明索引是旧策略
        # 产物（例如未做 CJK bigram 的 unicode61 原文索引），必须显式要求 rebuild。
        meta_table = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'trivae_derived_meta'"
        ).fetchone()
        if meta_table is None:
            raise LexicalIndexError(
                "messages_fts tokenizer strategy is unrecorded; rebuild the derived index"
            )
        strategy_row = self._connection.execute(
            "SELECT value FROM trivae_derived_meta WHERE key = 'lexical_tokenizer_strategy'"
        ).fetchone()
        if strategy_row is None or strategy_row["value"] != FTS_TOKENIZER_STRATEGY_ID:
            observed = None if strategy_row is None else str(strategy_row["value"])
            raise LexicalIndexError(
                "messages_fts tokenizer strategy is stale; rebuild the derived index"
                f" (expected {FTS_TOKENIZER_STRATEGY_ID}, found {observed})"
            )

        metadata = {
            str(row["key"]): str(row["value"])
            for row in self._connection.execute(
                "SELECT key, value FROM trivae_derived_meta WHERE key LIKE 'lexical_%'"
            ).fetchall()
        }
        if metadata.get("lexical_forward_projection") != FORWARD_PROJECTION_VERSION:
            raise LexicalIndexError("messages_fts forward projection is stale; rebuild the derived index")
        projection_table = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'forwarded_messages'"
        ).fetchone()
        if projection_table is None:
            raise LexicalIndexError("Forward occurrence projection is unavailable; rebuild the derived index")
        if metadata.get("lexical_canonical_revision") != str(self.canonical_revision()):
            raise LexicalIndexError("messages_fts canonical revision is stale; rebuild the derived index")
        fts_count_row = self._connection.execute("SELECT COUNT(*) AS total FROM messages_fts").fetchone()
        canonical_count_row = self._connection.execute("SELECT COUNT(*) AS total FROM messages").fetchone()
        forward_count_row = self._connection.execute("SELECT COUNT(*) AS total FROM forwarded_messages").fetchone()
        if fts_count_row is None or canonical_count_row is None or forward_count_row is None:
            raise RetrievalError("Lexical readiness check returned no scalar row")
        canonical_count = int(canonical_count_row["total"])
        forward_count = int(forward_count_row["total"])
        if (
            metadata.get("lexical_canonical_count") != str(canonical_count)
            or metadata.get("lexical_forwarded_count") != str(forward_count)
            or int(fts_count_row["total"]) != canonical_count + forward_count
        ):
            raise LexicalIndexError("messages_fts is stale; rebuild the derived index")

    def _lexical_match_union(self, query: LexicalQuery, *, scored: bool) -> tuple[str, list[object]]:
        """普通与转发 occurrence 共用唯一 FTS；SQL scope 分别绑定到对应事实投影。"""

        where_sql, parameters = _where_clause(query)
        columns = "m.internal_message_id AS internal_message_id, m.session_id AS session_id"
        if scored:
            columns += (
                ", m.timestamp, CASE WHEN m.seq IS NULL THEN 1 ELSE 0 END AS missing_seq, "
                "COALESCE(m.seq, 0) AS order_seq, bm25(messages_fts) AS lexical_score"
            )
        branches = []
        for table in ("messages", "forwarded_messages"):
            # 表名来自内部固定枚举；query、scope 和 ID 始终使用参数绑定。
            branches.append(
                f"""
                SELECT {columns}
                FROM messages_fts AS f
                INNER JOIN {table} AS m
                  ON m.internal_message_id = f.internal_message_id AND m.session_id = f.session_id
                WHERE messages_fts MATCH ? AND {where_sql}
                """
            )
        bound = [_fts_match_expression(query), *parameters]
        return " UNION ALL ".join(branches), [*bound, *bound]

    def count_lexical_hits(self, query: LexicalQuery) -> int:
        """统计普通消息与各转发位置的命中，重复转发不会被正文或 source ID 合并。"""

        self._ensure_lexical_ready()
        union_sql, parameters = self._lexical_match_union(query, scored=False)
        row = self._connection.execute(f"SELECT COUNT(*) AS total FROM ({union_sql})", parameters).fetchone()
        if row is None:
            raise RetrievalError("Lexical count returned no scalar row")
        return int(row["total"])

    def read_lexical_hits(self, query: LexicalQuery) -> tuple[MessageHit, ...]:
        """FTS 只提供候选 ID/score，所有证据正文重新从 canonical root JSON 恢复。"""

        self._ensure_lexical_ready()
        union_sql, parameters = self._lexical_match_union(query, scored=True)
        rows = self._connection.execute(
            f"""
            {union_sql}
            ORDER BY lexical_score ASC, timestamp ASC, missing_seq ASC, order_seq ASC, internal_message_id ASC
            LIMIT ?
            """,
            [*parameters, query.limit],
        ).fetchall()
        hits: list[MessageHit] = []
        for row in rows:
            message = self.read_message_by_id(str(row["internal_message_id"]))
            if message is None or message.session_id != row["session_id"]:
                raise LexicalIndexError("Lexical candidate cannot be recovered from its canonical source")
            hits.append(
                MessageHit(
                    message=message,
                    matched_terms=query.terms,
                    score=float(row["lexical_score"]),
                    score_type="fts5_bm25",
                )
            )
        return tuple(hits)

    def read_message_context(
        self,
        session_id: str,
        internal_message_id: str,
        before: int,
        after: int,
    ) -> tuple[MessageProjection, ...]:
        """使用同 session 的显式 order boundary 读取 anchor 前后消息。"""

        return self._read_message_context(
            session_id=session_id,
            internal_message_id=internal_message_id,
            before=before,
            after=after,
            scope=None,
        )

    def read_message_context_scoped(
        self,
        session_id: str,
        internal_message_id: str,
        before: int,
        after: int,
        scope: ScopeFilters,
    ) -> tuple[MessageProjection, ...]:
        """只读取 trusted Scope 内的同 session context，阻止时间边界外消息进入 Tool。"""

        return self._read_message_context(
            session_id=session_id,
            internal_message_id=internal_message_id,
            before=before,
            after=after,
            scope=scope,
        )

    def _read_message_context(
        self,
        *,
        session_id: str,
        internal_message_id: str,
        before: int,
        after: int,
        scope: ScopeFilters | None,
    ) -> tuple[MessageProjection, ...]:
        """复用同一排序边界实现普通 context 与 scope-bound context。"""

        if isinstance(before, bool) or not isinstance(before, int) or before < 0:
            raise ValueError("context before must be non-negative")
        if isinstance(after, bool) or not isinstance(after, int) or after < 0:
            raise ValueError("context after must be non-negative")

        if split_forward_message_id(internal_message_id) is not None:
            tree, anchor = self._read_forward_anchor(session_id, internal_message_id)
            peers = tuple(
                message
                for message in tree.messages
                if message.forward is not None
                and anchor.forward is not None
                and message.forward.parent_message_id == anchor.forward.parent_message_id
                and message.forward.container_path == anchor.forward.container_path
                and self._projection_in_scope(message, scope)
            )
            if anchor not in peers:
                raise RetrievalError(f"Context anchor is outside scope: {session_id}/{internal_message_id}")
            position = peers.index(anchor)
            # 窗口只在同一个直接转发容器内移动，不把原始群普通邻居混成内部讨论。
            return peers[max(0, position - before):position + after + 1]

        scope_sql = "1 = 1"
        scope_parameters: list[object] = []
        if scope is not None:
            scope_sql, scope_parameters = _where_clause(scope)

        anchor_row = self._connection.execute(
            f"""
            SELECT timestamp, seq
            FROM messages AS m
            WHERE m.session_id = ? AND m.internal_message_id = ? AND {scope_sql}
            """,
            [session_id, internal_message_id, *scope_parameters],
        ).fetchone()
        if anchor_row is None:
            raise RetrievalError(f"Context anchor not found: {session_id}/{internal_message_id}")

        anchor_timestamp = int(anchor_row["timestamp"])
        anchor_missing_seq = 1 if anchor_row["seq"] is None else 0
        anchor_seq = 0 if anchor_row["seq"] is None else int(anchor_row["seq"])
        anchor = self._read_message_by_id(session_id, internal_message_id)

        before_messages: tuple[MessageProjection, ...] = ()
        if before:
            boundary_sql, boundary_parameters = self._order_boundary(
                alias="m",
                operator="<",
                timestamp=anchor_timestamp,
                missing_seq=anchor_missing_seq,
                seq=anchor_seq,
                internal_message_id=internal_message_id,
            )
            before_rows = self._connection.execute(
                f"""
                SELECT {PROJECTION_COLUMNS}
                FROM messages AS m
                INNER JOIN chat_sessions AS s ON s.session_id = m.session_id
                WHERE m.session_id = ? AND {scope_sql} AND {boundary_sql}
                ORDER BY {ORDER_BY_SQL_DESC}
                LIMIT ?
                """,
                [session_id, *scope_parameters, *boundary_parameters, before],
            ).fetchall()
            before_messages = tuple(_row_to_projection(row) for row in reversed(before_rows))

        after_messages: tuple[MessageProjection, ...] = ()
        if after:
            boundary_sql, boundary_parameters = self._order_boundary(
                alias="m",
                operator=">",
                timestamp=anchor_timestamp,
                missing_seq=anchor_missing_seq,
                seq=anchor_seq,
                internal_message_id=internal_message_id,
            )
            after_rows = self._connection.execute(
                f"""
                SELECT {PROJECTION_COLUMNS}
                FROM messages AS m
                INNER JOIN chat_sessions AS s ON s.session_id = m.session_id
                WHERE m.session_id = ? AND {scope_sql} AND {boundary_sql}
                ORDER BY {ORDER_BY_SQL}
                LIMIT ?
                """,
                [session_id, *scope_parameters, *boundary_parameters, after],
            ).fetchall()
            after_messages = tuple(_row_to_projection(row) for row in after_rows)

        return (*before_messages, anchor, *after_messages)

    def read_message_replies_scoped(
        self,
        anchor: MessageProjection,
        scope: ScopeFilters,
        limit: int,
    ) -> tuple[MessageProjection, ...]:
        """直接查回复边，不让中间消息数量限制回复恢复距离。"""

        return self.read_message_replies_for_anchors((anchor,), scope, limit)

    def read_message_replies_for_anchors(
        self, anchors: tuple[MessageProjection, ...], scope: ScopeFilters, limit: int,
    ) -> tuple[MessageProjection, ...]:
        """批量按真实回复边查找，只返回当前原消息集合之外的新增回复。"""

        anchor_ids = {anchor.internal_message_id for anchor in anchors}
        ordinary = sorted({(anchor.session_id, anchor.source_message_id) for anchor in anchors
            if anchor.forward is None and anchor.source_message_id is not None})
        replies: list[MessageProjection] = []
        if ordinary:
            # 一次索引连接完成全部普通消息的关系查询，避免 N 个原消息产生 N 次群聊扫描。
            values = ", ".join("(?, ?)" for _ in ordinary)
            parameters = [value for pair in ordinary for value in pair]
            excluded = ", ".join("?" for _ in anchor_ids)
            scope_sql, scope_parameters = _where_clause(scope)
            rows = self._connection.execute(
                f"""
                WITH reply_targets(session_id, source_message_id) AS (VALUES {values})
                SELECT {PROJECTION_COLUMNS}
                FROM reply_targets AS target
                INNER JOIN messages AS m ON m.session_id = target.session_id
                    AND m.reply_to_source_message_id = target.source_message_id
                INNER JOIN chat_sessions AS s ON s.session_id = m.session_id
                WHERE {scope_sql} AND m.internal_message_id NOT IN ({excluded})
                ORDER BY {ORDER_BY_SQL}
                LIMIT ?
                """,
                [*parameters, *scope_parameters, *sorted(anchor_ids), limit],
            ).fetchall()
            replies.extend(_row_to_projection(row) for row in rows)

        forward_roots: dict[tuple[str, str], list[MessageProjection]] = {}
        for anchor in anchors:
            if anchor.forward is not None and anchor.source_message_id is not None:
                forward_roots.setdefault((anchor.session_id, anchor.forward.root_message_id), []).append(anchor)
        for (session_id, _root), root_anchors in forward_roots.items():
            # 同一个 root 只解析一次；原始平台 ID 仍严格在直接 parent/container 内解释。
            tree, _ = self._read_forward_anchor(session_id, root_anchors[0].internal_message_id)
            targets = {(anchor.forward.parent_message_id, anchor.forward.container_path, anchor.source_message_id)
                for anchor in root_anchors if anchor.forward is not None}
            replies.extend(message for message in tree.messages
                if message.forward is not None and message.internal_message_id not in anchor_ids
                and (message.forward.parent_message_id, message.forward.container_path,
                    message.reply_to_source_message_id) in targets
                and self._projection_in_scope(message, scope))
        # 普通消息与转发 occurrence 使用统一稳定排序和同一返回容量。
        return tuple(sorted(replies, key=message_sort_key))[:limit]

    def read_member_candidates(self, query: MemberQuery) -> FindMembersResult:
        """读取 UserIdentity 与 scope 内 Membership，并保留每个候选的匹配依据。"""

        started = perf_counter()
        where_sql, parameters = _member_where_clause(query.scope)
        match_sql, match_parameters = _member_match_clause(query.query)
        total_row = self._connection.execute(
            f"""
            SELECT COUNT(DISTINCT u.user_id) AS total
            FROM users AS u
            INNER JOIN memberships AS m ON m.user_id = u.user_id
            WHERE {where_sql} AND ({match_sql})
            """,
            [*parameters, *match_parameters],
        ).fetchone()
        if total_row is None:
            raise RetrievalError("Member lookup count returned no scalar row")
        total_candidates = int(total_row["total"])

        rows = self._connection.execute(
            f"""
            WITH matched_users AS (
                SELECT u.user_id
                FROM users AS u
                INNER JOIN memberships AS m ON m.user_id = u.user_id
                WHERE {where_sql} AND ({match_sql})
                GROUP BY u.user_id
                ORDER BY u.user_id ASC
                LIMIT ?
            )
            SELECT
                u.user_id,
                u.platform,
                u.platform_user_id,
                u.platform_uin,
                u.display_name AS user_display_name,
                u.nickname AS user_nickname,
                u.remark AS user_remark,
                m.session_id,
                s.name AS session_display,
                m.display_name AS membership_display_name,
                m.nickname AS membership_nickname,
                m.group_card,
                m.remark AS membership_remark,
                m.first_seen_timestamp,
                m.last_seen_timestamp
            FROM matched_users AS selected
            INNER JOIN users AS u ON u.user_id = selected.user_id
            INNER JOIN memberships AS m ON m.user_id = u.user_id
            INNER JOIN chat_sessions AS s ON s.session_id = m.session_id
            WHERE {where_sql}
            ORDER BY u.user_id ASC, m.session_id ASC
            """,
            [*parameters, *match_parameters, query.limit, *parameters],
        ).fetchall()

        candidates = _member_candidates_from_rows(rows, query.query)
        truncated = total_candidates > len(candidates)
        latency_ms = (perf_counter() - started) * 1000
        return FindMembersResult(
            query=query,
            strategy="identity",
            candidates=candidates,
            total_candidates=total_candidates,
            coverage=Coverage(status="complete", basis="canonical_users_and_memberships"),
            partial=False,
            truncated=truncated,
            metadata=RetrievalMetadata(
                filters=query.to_dict(),
                ordering="user_id ASC, session_id ASC",
                latency_ms=latency_ms,
                details={
                    "returned_candidates": len(candidates),
                    "total_candidates": total_candidates,
                    "ambiguous": len(candidates) > 1,
                },
            ),
        )

    def read_message_range(
        self,
        session_id: str,
        start_message_id: str,
        end_message_id: str,
        limit: int,
    ) -> tuple[MessageProjection, ...]:
        """按 canonical ordering 恢复 child/parent range，并严格限制返回数量。"""

        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("message range limit must be positive")
        if split_forward_message_id(start_message_id) is not None or split_forward_message_id(end_message_id) is not None:
            tree, start_message = self._read_forward_anchor(session_id, start_message_id)
            end_message = next(
                (message for message in tree.messages if message.internal_message_id == end_message_id), None
            )
            if (
                end_message is None
                or start_message.forward is None
                or end_message.forward is None
                or start_message.forward.parent_message_id != end_message.forward.parent_message_id
                or start_message.forward.container_path != end_message.forward.container_path
            ):
                raise RetrievalError("Forward range must stay within one root, direct parent, and forward container")
            if start_message.seq is None or end_message.seq is None or start_message.seq > end_message.seq:
                raise RetrievalError(f"Forward range is reversed: {start_message_id}:{end_message_id}")
            # 子消息的 ordinal 属于转发树；不能用相同 timestamp 混入外层 canonical 消息。
            return tuple(
                message
                for message in tree.messages
                if message.forward is not None
                and message.forward.parent_message_id == start_message.forward.parent_message_id
                and message.forward.container_path == start_message.forward.container_path
                and message.seq is not None
                and start_message.seq <= message.seq <= end_message.seq
            )[:limit]
        start = self._read_message_order(session_id, start_message_id, "range start")
        end = self._read_message_order(session_id, end_message_id, "range end")
        if self._order_key(start) > self._order_key(end):
            raise RetrievalError(f"Message range is reversed: {session_id}/{start_message_id}:{end_message_id}")

        start_sql, start_parameters = self._order_boundary(
            alias="m",
            operator=">=",
            timestamp=start[0],
            missing_seq=start[1],
            seq=start[2],
            internal_message_id=start[3],
        )
        end_sql, end_parameters = self._order_boundary(
            alias="m",
            operator="<=",
            timestamp=end[0],
            missing_seq=end[1],
            seq=end[2],
            internal_message_id=end[3],
        )
        rows = self._connection.execute(
            f"""
            SELECT {PROJECTION_COLUMNS}
            FROM messages AS m
            INNER JOIN chat_sessions AS s ON s.session_id = m.session_id
            WHERE m.session_id = ? AND {start_sql} AND {end_sql}
            ORDER BY {ORDER_BY_SQL}
            LIMIT ?
            """,
            [session_id, *start_parameters, *end_parameters, limit],
        ).fetchall()
        return tuple(_row_to_projection(row) for row in rows)

    def _read_forward_anchor(
        self,
        session_id: str,
        internal_message_id: str,
    ) -> tuple[ForwardMessageTree, MessageProjection]:
        """根据 occurrence locator 恢复同群 canonical root，派生表不能提供证据正文。"""

        locator = split_forward_message_id(internal_message_id)
        if locator is None:
            raise RetrievalError(f"Not a forward occurrence: {internal_message_id}")
        row = self._connection.execute(
            f"""
            SELECT {PROJECTION_COLUMNS}
            FROM messages AS m
            INNER JOIN chat_sessions AS s ON s.session_id = m.session_id
            WHERE m.session_id = ? AND m.internal_message_id = ?
            """,
            (session_id, locator[0]),
        ).fetchone()
        if row is None:
            raise RetrievalError(f"Forward root not found: {session_id}/{locator[0]}")
        tree = _row_to_forward_tree(row)
        anchor = next(
            (message for message in tree.messages if message.internal_message_id == internal_message_id), None
        )
        if anchor is None:
            raise RetrievalError(f"Forward occurrence not found: {session_id}/{internal_message_id}")
        return tree, anchor

    @staticmethod
    def _projection_in_scope(message: MessageProjection, scope: ScopeFilters | None) -> bool:
        """forward scope 只比较恢复后的可信字段，时间明确使用外层转发时间。"""

        if scope is None:
            return True
        return (
            (scope.session_ids is None or message.session_id in scope.session_ids)
            and (scope.start_timestamp is None or message.timestamp >= scope.start_timestamp)
            and (scope.end_timestamp is None or message.timestamp < scope.end_timestamp)
            and (scope.sender_user_ids is None or message.sender_user_id in scope.sender_user_ids)
            and (scope.message_types is None or message.message_type in scope.message_types)
            and (scope.source_message_id is None or message.source_message_id == scope.source_message_id)
            and (
                scope.reply_to_source_message_id is None
                or message.reply_to_source_message_id == scope.reply_to_source_message_id
            )
        )

    def _read_message_by_id(self, session_id: str, internal_message_id: str) -> MessageProjection:
        """读取 context anchor 的限定 projection。"""

        row = self._connection.execute(
            f"""
            SELECT {PROJECTION_COLUMNS}
            FROM messages AS m
            INNER JOIN chat_sessions AS s ON s.session_id = m.session_id
            WHERE m.session_id = ? AND m.internal_message_id = ?
            """,
            (session_id, internal_message_id),
        ).fetchone()
        if row is None:
            raise RetrievalError(f"Context anchor disappeared: {session_id}/{internal_message_id}")
        return _row_to_projection(row)

    def _read_message_order(
        self,
        session_id: str,
        internal_message_id: str,
        label: str,
    ) -> tuple[int, int, int, str]:
        """读取 range 边界所需的排序 tuple，不把 raw row 继续向上泄漏。"""

        row = self._connection.execute(
            """
            SELECT timestamp, seq
            FROM messages
            WHERE session_id = ? AND internal_message_id = ?
            """,
            (session_id, internal_message_id),
        ).fetchone()
        if row is None:
            raise RetrievalError(f"{label} not found: {session_id}/{internal_message_id}")
        timestamp = int(row["timestamp"])
        missing_seq = 1 if row["seq"] is None else 0
        seq = 0 if row["seq"] is None else int(row["seq"])
        return timestamp, missing_seq, seq, internal_message_id

    @staticmethod
    def _order_key(value: tuple[int, int, int, str]) -> tuple[int, int, int, str]:
        """为 start/end 比较提供与 SQL ORDER BY 完全一致的 Python key。"""

        return value

    @staticmethod
    def _order_boundary(
        alias: str,
        operator: str,
        timestamp: int,
        missing_seq: int,
        seq: int,
        internal_message_id: str,
    ) -> tuple[str, list[object]]:
        """生成同一排序 tuple 的严格前后边界，避免 Python 全表扫描。"""

        if operator not in ("<", ">", "<=", ">="):
            raise ValueError(f"Unsupported order boundary operator: {operator}")
        # 只有最后一个排序字段使用调用方的包含/不包含比较符。
        # timestamp、missing_seq、seq 是更高优先级字段，必须永远使用严格方向。
        prefix_operator = ">" if operator in (">", ">=") else "<"
        missing_expression = f"CASE WHEN {alias}.seq IS NULL THEN 1 ELSE 0 END"
        seq_expression = f"COALESCE({alias}.seq, 0)"
        boundary = f"""
        (
            {alias}.timestamp {prefix_operator} ?
            OR ({alias}.timestamp = ? AND {missing_expression} {prefix_operator} ?)
            OR ({alias}.timestamp = ? AND {missing_expression} = ? AND {seq_expression} {prefix_operator} ?)
            OR (
                {alias}.timestamp = ? AND {missing_expression} = ? AND {seq_expression} = ?
                AND {alias}.internal_message_id {operator} ?
            )
        )
        """
        parameters: list[object] = [
            timestamp,
            timestamp,
            missing_seq,
            timestamp,
            missing_seq,
            seq,
            timestamp,
            missing_seq,
            seq,
            internal_message_id,
        ]
        return boundary, parameters
