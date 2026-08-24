"""SQLite Canonical Store 的 Retrieval read adapter。"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from trivae.data.model import ChatSession
from trivae.retrieval.structured import (
    AggregateBucket,
    AggregateData,
    AggregateQuery,
    CanonicalReadRepository,
    LexicalIndexError,
    LexicalQuery,
    MessageHit,
    MessageProjection,
    MessageQuery,
    RetrievalError,
    ScopeFilters,
)

# 只允许这些 canonical 列穿过 data/storage 到 Retrieval projection。
PROJECTION_COLUMNS = """
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
    m.system
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


def _row_to_projection(row: sqlite3.Row) -> MessageProjection:
    """把限定列转换为 retrieval-owned projection，不返回 sqlite3.Row。"""

    return MessageProjection(
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


def _fts_match_expression(query: LexicalQuery) -> str:
    """把关键词转换为 literal AND 查询，禁止用户输入改变 SQL 结构。"""

    # FTS5 的 MATCH 文本仍作为参数绑定；双引号只用于 literal token 语义。
    return " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in query.terms)


class SQLiteCanonicalReadRepository(CanonicalReadRepository):
    """只读读取 adapter，集中承载 Structured、Lexical 和 Context SQL。"""

    def __init__(self, database_path: Path) -> None:
        self._connection = sqlite3.connect(_readonly_uri(database_path), uri=True)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA query_only = ON")
        self._connection.execute("PRAGMA foreign_keys = ON")

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

    def iter_semantic_messages(self, batch_size: int) -> Iterator[MessageProjection]:
        """以 cursor/fetchmany 流式读取全量 canonical projection，避免 build 一次性载入消息。"""

        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
            raise ValueError("semantic batch_size must be positive")
        cursor = self._connection.execute(
            f"""
            SELECT {PROJECTION_COLUMNS}
            FROM messages AS m
            INNER JOIN chat_sessions AS s ON s.session_id = m.session_id
            ORDER BY m.session_id ASC, {ORDER_BY_SQL}
            """
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

        fts_count_row = self._connection.execute("SELECT COUNT(*) AS total FROM messages_fts").fetchone()
        canonical_count_row = self._connection.execute("SELECT COUNT(*) AS total FROM messages").fetchone()
        if fts_count_row is None or canonical_count_row is None:
            raise RetrievalError("Lexical readiness check returned no scalar row")
        if int(fts_count_row["total"]) != int(canonical_count_row["total"]):
            raise LexicalIndexError("messages_fts is stale; rebuild the derived index")

    def count_lexical_hits(self, query: LexicalQuery) -> int:
        """统计 FTS 命中；scope 仍由 canonical messages predicate 约束。"""

        self._ensure_lexical_ready()
        where_sql, parameters = _where_clause(query)
        match_expression = _fts_match_expression(query)
        row = self._connection.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM messages_fts AS f
            INNER JOIN messages AS m
              ON m.internal_message_id = f.internal_message_id
             AND m.session_id = f.session_id
            WHERE messages_fts MATCH ? AND {where_sql}
            """,
            [match_expression, *parameters],
        ).fetchone()
        if row is None:
            raise RetrievalError("Lexical count returned no scalar row")
        return int(row["total"])

    def read_lexical_hits(self, query: LexicalQuery) -> tuple[MessageHit, ...]:
        """从 FTS 取 score，从 canonical messages hydrate retrieval projection。"""

        self._ensure_lexical_ready()
        where_sql, parameters = _where_clause(query)
        match_expression = _fts_match_expression(query)
        rows = self._connection.execute(
            f"""
            SELECT {PROJECTION_COLUMNS}, bm25(messages_fts) AS lexical_score
            FROM messages_fts AS f
            INNER JOIN messages AS m
              ON m.internal_message_id = f.internal_message_id
             AND m.session_id = f.session_id
            INNER JOIN chat_sessions AS s ON s.session_id = m.session_id
            WHERE messages_fts MATCH ? AND {where_sql}
            ORDER BY lexical_score ASC, {ORDER_BY_SQL}
            LIMIT ?
            """,
            [match_expression, *parameters, query.limit],
        ).fetchall()
        return tuple(
            MessageHit(
                message=_row_to_projection(row),
                matched_terms=query.terms,
                score=float(row["lexical_score"]),
                score_type="fts5_bm25",
            )
            for row in rows
        )

    def read_message_context(
        self,
        session_id: str,
        internal_message_id: str,
        before: int,
        after: int,
    ) -> tuple[MessageProjection, ...]:
        """使用同 session 的显式 order boundary 读取 anchor 前后消息。"""

        anchor_row = self._connection.execute(
            """
            SELECT timestamp, seq
            FROM messages
            WHERE session_id = ? AND internal_message_id = ?
            """,
            (session_id, internal_message_id),
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
                WHERE m.session_id = ? AND {boundary_sql}
                ORDER BY {ORDER_BY_SQL_DESC}
                LIMIT ?
                """,
                [session_id, *boundary_parameters, before],
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
                WHERE m.session_id = ? AND {boundary_sql}
                ORDER BY {ORDER_BY_SQL}
                LIMIT ?
                """,
                [session_id, *boundary_parameters, after],
            ).fetchall()
            after_messages = tuple(_row_to_projection(row) for row in after_rows)

        return (*before_messages, anchor, *after_messages)

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
