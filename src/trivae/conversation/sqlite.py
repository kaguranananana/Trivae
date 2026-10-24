"""SQLite-backed Conversation Store。

该 Store 只拥有 Conversation tables，不修改 Canonical Chat Store，也不向
Retrieval read repository 暴露写入能力。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Mapping
from pathlib import Path

from trivae.capabilities.contracts import CapabilityContractError, ExecutionScope
from trivae.data.storage.sqlite import utc_now
from trivae.query.evidence import AnswerArtifact, scope_snapshot

from .contracts import (
    Conversation,
    ConversationMessage,
    ConversationNotFoundError,
    ConversationPersistenceError,
    ConversationScopeSelector,
    ConversationSummary,
)
from .serialization import deserialize_answer_artifact, serialize_answer_artifact

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    scope_snapshot_json TEXT
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    answer_artifact_json TEXT,
    UNIQUE(conversation_id, ordinal),
    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id),
    CHECK (
        (role = 'user' AND answer_artifact_json IS NULL)
        OR (role = 'assistant' AND answer_artifact_json IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_order
    ON conversation_messages(conversation_id, ordinal);
"""

# Web/replay 需要的 additive 列；旧数据库按 nullable migration 逐个补齐。
MAX_TITLE_OVERRIDE_CHARS = 120
MAX_PROCESS_PROJECTION_CHARS = 32_000
MAX_PREVIEW_CHARS = 160


class SQLiteConversationStore:
    """拥有 Conversation SQLite connection、schema 和 atomic turn transaction。"""

    def __init__(self, database_path: Path) -> None:
        # Conversation Store 自己打开连接，避免把 Canonical Store 的写权限传播到上层组件。
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = database_path
        self.connection = sqlite3.connect(str(database_path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA_SQL)
        self._ensure_additive_columns()
        self.connection.commit()
        self._closed = False

    def close(self) -> None:
        """关闭 Conversation connection；重复 close 不产生额外副作用。"""

        if self._closed:
            return
        self._closed = True
        self.connection.close()

    def create_conversation(self, scope: ExecutionScope | None = None) -> Conversation:
        """创建并立即提交一个带可选 scope 快照的空 conversation。"""

        self._ensure_open()
        if scope is not None and not isinstance(scope, ExecutionScope):
            raise ConversationPersistenceError("conversation scope must be an ExecutionScope or None")
        conversation_id = uuid.uuid4().hex
        timestamp = utc_now()
        scope_json = self._encode_scope(scope)
        try:
            self.connection.execute(
                """
                INSERT INTO conversations(
                    conversation_id, created_at, updated_at, scope_snapshot_json
                ) VALUES (?, ?, ?, ?)
                """,
                (conversation_id, timestamp, timestamp, scope_json),
            )
            self.connection.commit()
        except sqlite3.Error as exc:
            self.connection.rollback()
            raise ConversationPersistenceError("conversation creation failed") from exc
        return Conversation(conversation_id, timestamp, timestamp, scope=scope)

    def get_conversation(self, conversation_id: str) -> Conversation:
        """按稳定 ordinal 读取 conversation，不重新 hydrate 历史 Evidence。"""

        self._ensure_open()
        return self._load_conversation(conversation_id)

    def list_summaries(
        self,
        limit: int = 20,
        selector: ConversationScopeSelector | None = None,
        *,
        query: str = "",
        offset: int = 0,
    ) -> tuple[ConversationSummary, ...]:
        """读取最近 conversation 的 bounded title/count/scope metadata。

        ``selector`` 是正式 scope identity selector：scope 过滤必须在 SQL ``WHERE``
        中先于 ``ORDER BY``/``LIMIT`` 完成，否则属于当前 scope、但排在全局 limit
        之后的历史会被错误丢给客户端。``selector=None`` 保留既有全局列表行为。
        query搜索标题和全部消息正文；offset在过滤后分页，不改变范围身份。
        """

        self._ensure_open()
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0 or limit > 100:
            raise ConversationPersistenceError("conversation history limit must be between 1 and 100")
        if selector is not None and not isinstance(selector, ConversationScopeSelector):
            raise ConversationPersistenceError("conversation scope selector has an unexpected type")
        if offset < 0:
            raise ConversationPersistenceError("conversation history offset must be non-negative")
        where_clause, selector_params = self._scope_identity_predicate(selector)
        # 全文搜索在范围过滤后、排序与分页前完成；参数绑定保持搜索词为字面文本。
        if query.strip():
            conjunction = " AND " if where_clause else "WHERE "
            where_clause += conjunction + """(
                instr(lower(coalesce(title_override, '')), lower(?)) > 0
                OR EXISTS (
                    SELECT 1 FROM conversation_messages AS message
                    WHERE message.conversation_id = conversations.conversation_id
                    AND instr(lower(message.content), lower(?)) > 0
                )
            )"""
            selector_params = (*selector_params, query.strip(), query.strip())
        rows = self.connection.execute(
            f"""
            SELECT conversation_id, created_at, updated_at, scope_snapshot_json, title_override
            FROM conversations
            {where_clause}
            -- 同一毫秒内按实际插入顺序显示新会话，不能让随机UUID决定最近一页。
            ORDER BY updated_at DESC, rowid DESC
            LIMIT ? OFFSET ?
            """,
            (*selector_params, limit, offset),
        ).fetchall()
        summaries: list[ConversationSummary] = []
        for row in rows:
            message_row = self.connection.execute(
                """
                SELECT
                    COUNT(*) AS message_count,
                    MIN(CASE WHEN role = 'user' THEN ordinal END) AS first_user_ordinal,
                    MAX(ordinal) AS last_ordinal
                FROM conversation_messages
                WHERE conversation_id = ?
                """,
                (row["conversation_id"],),
            ).fetchone()
            count = 0 if message_row is None else int(message_row["message_count"])
            first_user_ordinal = None if message_row is None else message_row["first_user_ordinal"]
            last_ordinal = None if message_row is None else message_row["last_ordinal"]
            title = "新对话"
            if first_user_ordinal is not None:
                title_row = self.connection.execute(
                    """
                    SELECT content
                    FROM conversation_messages
                    WHERE conversation_id = ? AND ordinal = ? AND role = 'user'
                    """,
                    (row["conversation_id"], first_user_ordinal),
                ).fetchone()
                if title_row is not None and isinstance(title_row["content"], str):
                    title = title_row["content"].strip()[:120] or title
            override = row["title_override"]
            if isinstance(override, str) and override.strip():
                # 显式 rename 拥有最高 title 优先级；空 override 回退到首条 user query。
                title = override.strip()[:MAX_TITLE_OVERRIDE_CHARS]
            preview = self._load_preview(row["conversation_id"], last_ordinal)
            summaries.append(
                ConversationSummary(
                    conversation_id=row["conversation_id"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    title=title,
                    message_count=count,
                    scope=self._decode_scope(row["scope_snapshot_json"]),
                    preview=preview,
                )
            )
        return tuple(summaries)

    @staticmethod
    def _scope_identity_predicate(
        selector: ConversationScopeSelector | None,
    ) -> tuple[str, tuple[object, ...]]:
        """构造 exact scope identity predicate。

        - all：snapshot 存在且 ``allowed_session_ids`` 是 JSON null（legacy SQL NULL
          的 scope_snapshot_json 被排除，不会伪装成 all）。
        - session 集合：snapshot 数组长度与 selector 集合大小相等，且不含集合之外
          的元素。对单 session 这等价于“array 长度恰为 1 且 [0] == session id”，
          因此 multi-session ``[A,B]`` 不会被归入 A 或 B 的 selector。
        """

        if selector is None:
            return "", ()
        sessions = selector.allowed_session_ids
        if sessions is None:
            return (
                "WHERE scope_snapshot_json IS NOT NULL "
                "AND json_type(scope_snapshot_json, '$.allowed_session_ids') = 'null'",
                (),
            )
        placeholders = ", ".join("?" for _ in sessions)
        return (
            "WHERE scope_snapshot_json IS NOT NULL "
            "AND json_type(scope_snapshot_json, '$.allowed_session_ids') = 'array' "
            "AND (SELECT COUNT(*) FROM json_each(scope_snapshot_json, '$.allowed_session_ids')) = ? "
            "AND NOT EXISTS ("
            "SELECT 1 FROM json_each(scope_snapshot_json, '$.allowed_session_ids') "
            f"WHERE value NOT IN ({placeholders})"
            ")",
            (len(sessions), *sessions),
        )

    def _load_preview(self, conversation_id: str, last_ordinal: int | None) -> str | None:
        """读取最后一条 message 的 bounded preview，空 conversation 无 preview。"""

        if last_ordinal is None:
            return None
        row = self.connection.execute(
            """
            SELECT role, content
            FROM conversation_messages
            WHERE conversation_id = ? AND ordinal = ?
            """,
            (conversation_id, last_ordinal),
        ).fetchone()
        if row is None or not isinstance(row["content"], str):
            return None
        role = "You" if row["role"] == "user" else "Assistant"
        text = " ".join(row["content"].split())
        if len(text) > MAX_PREVIEW_CHARS:
            text = text[: MAX_PREVIEW_CHARS - 1] + "…"
        return f"{role}: {text}" if text else None

    def commit_turn(
        self,
        conversation_id: str,
        user_content: str,
        answer_artifact: AnswerArtifact,
        *,
        trace_id: str | None = None,
        process_projection: Mapping[str, object] | None = None,
    ) -> Conversation:
        """在同一 transaction 中追加 User 与 validated Assistant message。

        ``trace_id`` 与 ``process_projection`` 是面向 replay 的可选引用：
        conversation 只保存 bounded 引用与摘要，大 payload 仍归 Trace/Tool 记录所有。
        """

        self._ensure_open()
        if not isinstance(answer_artifact, AnswerArtifact):
            raise ConversationPersistenceError("only an AnswerArtifact can be committed")

        # 先完成 JSON 编码和领域对象检查，避免 transaction 中途才发现 Artifact 不可持久化。
        artifact_json = serialize_answer_artifact(answer_artifact)
        normalized_user_content = self._normalize_content(user_content)
        normalized_trace_id = self._normalize_trace_id(trace_id)
        projection_json = self._encode_process_projection(process_projection)

        try:
            # BEGIN IMMEDIATE 让 ordinal 分配和两个 message insert 在同一写锁内完成。
            self.connection.execute("BEGIN IMMEDIATE")
            conversation_row = self.connection.execute(
                "SELECT conversation_id, created_at, updated_at FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if conversation_row is None:
                raise ConversationNotFoundError(f"conversation not found: {conversation_id}")

            next_ordinal = self._next_ordinal(conversation_id)
            timestamp = utc_now()
            user_message = ConversationMessage(
                message_id=uuid.uuid4().hex,
                conversation_id=conversation_id,
                ordinal=next_ordinal,
                role="user",
                content=normalized_user_content,
                created_at=timestamp,
            )
            assistant_message = ConversationMessage(
                message_id=uuid.uuid4().hex,
                conversation_id=conversation_id,
                ordinal=next_ordinal + 1,
                role="assistant",
                content=answer_artifact.answer_text,
                created_at=timestamp,
                answer_artifact=answer_artifact,
            )

            # User insert 成功不等于 turn 成功；assistant 或 update 失败时外层 except 会整体 rollback。
            self._insert_message(user_message, None, trace_id=None, projection_json=None)
            self._insert_message(
                assistant_message,
                artifact_json,
                trace_id=normalized_trace_id,
                projection_json=projection_json,
            )
            self.connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                (timestamp, conversation_id),
            )
            self.connection.commit()
        except ConversationNotFoundError:
            self.connection.rollback()
            raise
        except sqlite3.Error as exc:
            self.connection.rollback()
            raise ConversationPersistenceError("conversation turn transaction failed") from exc
        except Exception:
            # 测试注入或领域异常也必须回滚，且不能被静默转换成成功结果。
            self.connection.rollback()
            raise

        return self._load_conversation(conversation_id)

    def rename_conversation(self, conversation_id: str, title: str) -> Conversation:
        """显式 rename 覆盖 title；不触碰消息、scope 或 updated_at 排序事实。"""

        self._ensure_open()
        normalized_id = self._normalize_identity(conversation_id, "conversation_id")
        if not isinstance(title, str) or not title.strip():
            raise ConversationPersistenceError("conversation title must be a non-empty string")
        normalized_title = title.strip()[:MAX_TITLE_OVERRIDE_CHARS]
        try:
            cursor = self.connection.execute(
                "UPDATE conversations SET title_override = ? WHERE conversation_id = ?",
                (normalized_title, normalized_id),
            )
            self.connection.commit()
        except sqlite3.Error as exc:
            self.connection.rollback()
            raise ConversationPersistenceError("conversation rename failed") from exc
        if cursor.rowcount == 0:
            raise ConversationNotFoundError(f"conversation not found: {normalized_id}")
        return self._load_conversation(normalized_id)

    def delete_conversation(self, conversation_id: str) -> None:
        """只删除 AI conversation 聚合；canonical chat 表不属于本 Store 的 ownership。"""

        self._ensure_open()
        normalized_id = self._normalize_identity(conversation_id, "conversation_id")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            cursor = self.connection.execute(
                "SELECT conversation_id FROM conversations WHERE conversation_id = ?",
                (normalized_id,),
            ).fetchone()
            if cursor is None:
                self.connection.rollback()
                raise ConversationNotFoundError(f"conversation not found: {normalized_id}")
            # 先删子行再删父行；FK 开启且无 cascade，顺序颠倒会违反约束。
            self.connection.execute(
                "DELETE FROM conversation_messages WHERE conversation_id = ?",
                (normalized_id,),
            )
            self.connection.execute(
                "DELETE FROM conversations WHERE conversation_id = ?",
                (normalized_id,),
            )
            self.connection.commit()
        except ConversationNotFoundError:
            raise
        except sqlite3.Error as exc:
            self.connection.rollback()
            raise ConversationPersistenceError("conversation deletion failed") from exc

    def _insert_message(
        self,
        message: ConversationMessage,
        artifact_json: str | None,
        *,
        trace_id: str | None,
        projection_json: str | None,
    ) -> None:
        """集中持久化 message，保留可测试的 transaction 中间边界。"""

        self.connection.execute(
            """
            INSERT INTO conversation_messages(
                message_id, conversation_id, ordinal, role, content, created_at,
                answer_artifact_json, trace_id, process_projection_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.message_id,
                message.conversation_id,
                message.ordinal,
                message.role,
                message.content,
                message.created_at,
                artifact_json,
                trace_id,
                projection_json,
            ),
        )

    def _next_ordinal(self, conversation_id: str) -> int:
        """在已持有写锁时读取下一个 conversation-local ordinal。"""

        row = self.connection.execute(
            "SELECT COALESCE(MAX(ordinal), -1) + 1 AS next_ordinal "
            "FROM conversation_messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None or not isinstance(row["next_ordinal"], int):
            raise ConversationPersistenceError("conversation ordinal could not be allocated")
        return row["next_ordinal"]

    def _load_conversation(self, conversation_id: str) -> Conversation:
        """在 Store 内部按聚合结构读取 rows，并通过领域构造函数校验一致性。"""

        normalized_id = self._normalize_identity(conversation_id, "conversation_id")
        row = self.connection.execute(
            """
            SELECT conversation_id, created_at, updated_at, scope_snapshot_json
            FROM conversations
            WHERE conversation_id = ?
            """,
            (normalized_id,),
        ).fetchone()
        if row is None:
            raise ConversationNotFoundError(f"conversation not found: {normalized_id}")

        message_rows = self.connection.execute(
            """
            SELECT message_id, conversation_id, ordinal, role, content, created_at,
                   answer_artifact_json, trace_id, process_projection_json
            FROM conversation_messages
            WHERE conversation_id = ?
            ORDER BY ordinal ASC
            """,
            (normalized_id,),
        ).fetchall()
        messages = tuple(self._row_to_message(message_row) for message_row in message_rows)
        return Conversation(
            conversation_id=row["conversation_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            messages=messages,
            scope=self._decode_scope(row["scope_snapshot_json"]),
        )

    def _ensure_additive_columns(self) -> None:
        """为旧版 Conversation 表执行 nullable additive migration。"""

        conversation_columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(conversations)").fetchall()
        }
        if "scope_snapshot_json" not in conversation_columns:
            self.connection.execute("ALTER TABLE conversations ADD COLUMN scope_snapshot_json TEXT")
        if "title_override" not in conversation_columns:
            self.connection.execute("ALTER TABLE conversations ADD COLUMN title_override TEXT")
        message_columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(conversation_messages)").fetchall()
        }
        if "trace_id" not in message_columns:
            self.connection.execute("ALTER TABLE conversation_messages ADD COLUMN trace_id TEXT")
        if "process_projection_json" not in message_columns:
            self.connection.execute(
                "ALTER TABLE conversation_messages ADD COLUMN process_projection_json TEXT"
            )

    @staticmethod
    def _encode_scope(scope: ExecutionScope | None) -> str | None:
        """将 trusted scope 编码为可审计 JSON；旧 conversation 保留 NULL。"""

        if scope is None:
            return None
        return json.dumps(scope_snapshot(scope), ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _decode_scope(value: object) -> ExecutionScope | None:
        """严格恢复 scope 快照，损坏数据不猜测默认权限。"""

        if value is None:
            return None
        if not isinstance(value, str):
            raise ConversationPersistenceError("conversation scope snapshot is not text")
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ConversationPersistenceError("conversation scope snapshot is invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ConversationPersistenceError("conversation scope snapshot must be an object")
        allowed = payload.get("allowed_session_ids")
        if allowed is not None:
            if not isinstance(allowed, list) or any(not isinstance(item, str) for item in allowed):
                raise ConversationPersistenceError("conversation scope session snapshot is invalid")
            allowed_sessions = tuple(allowed)
        else:
            allowed_sessions = None
        max_results = payload.get("max_results")
        if isinstance(max_results, bool) or not isinstance(max_results, int):
            raise ConversationPersistenceError("conversation scope max_results snapshot is invalid")
        try:
            return ExecutionScope(
                allowed_session_ids=allowed_sessions,
                start_timestamp=payload.get("start_timestamp"),
                end_timestamp=payload.get("end_timestamp"),
                max_results=max_results,
            )
        except (CapabilityContractError, TypeError, ValueError) as exc:
            raise ConversationPersistenceError("conversation scope snapshot violates its contract") from exc

    def _row_to_message(self, row: sqlite3.Row) -> ConversationMessage:
        """把 SQL row 解码为领域 message，损坏数据显式失败。"""

        role = row["role"]
        artifact_json = row["answer_artifact_json"]
        trace_id = row["trace_id"] if "trace_id" in row.keys() else None
        projection_json = row["process_projection_json"] if "process_projection_json" in row.keys() else None
        if role == "user":
            if artifact_json is not None:
                raise ConversationPersistenceError("user message unexpectedly contains an artifact")
            artifact = None
        elif role == "assistant":
            if not isinstance(artifact_json, str):
                raise ConversationPersistenceError("assistant message is missing its artifact JSON")
            try:
                artifact = deserialize_answer_artifact(artifact_json)
            except ConversationPersistenceError:
                raise
            except Exception as exc:
                raise ConversationPersistenceError("assistant artifact could not be restored") from exc
        else:
            raise ConversationPersistenceError("conversation message has an invalid role")
        process_projection = None
        if projection_json is not None:
            try:
                decoded_projection = json.loads(projection_json)
            except json.JSONDecodeError as exc:
                raise ConversationPersistenceError("process projection is invalid JSON") from exc
            if not isinstance(decoded_projection, dict):
                raise ConversationPersistenceError("process projection must be a JSON object")
            process_projection = decoded_projection

        try:
            return ConversationMessage(
                message_id=row["message_id"],
                conversation_id=row["conversation_id"],
                ordinal=row["ordinal"],
                role=role,
                content=row["content"],
                created_at=row["created_at"],
                answer_artifact=artifact,
                trace_id=trace_id if isinstance(trace_id, str) and trace_id else None,
                process_projection=process_projection,
            )
        except (TypeError, ValueError) as exc:
            raise ConversationPersistenceError("conversation message violates its domain contract") from exc

    @staticmethod
    def _normalize_identity(value: str, name: str) -> str:
        """Store 入口只接受非空 identity，不把空值映射成默认 conversation。"""

        if not isinstance(value, str) or not value.strip():
            raise ConversationPersistenceError(f"{name} must be a non-empty string")
        return value.strip()

    @staticmethod
    def _normalize_trace_id(trace_id: str | None) -> str | None:
        """可选 trace 引用；非空时必须是纯 identity 文本。"""

        if trace_id is None:
            return None
        normalized = SQLiteConversationStore._normalize_identity(trace_id, "trace_id")
        return normalized

    @staticmethod
    def _encode_process_projection(process_projection: Mapping[str, object] | None) -> str | None:
        """把 bounded 过程摘要编码为 JSON；超限显式失败，不静默截断回放数据。"""

        if process_projection is None:
            return None
        if not isinstance(process_projection, Mapping):
            raise ConversationPersistenceError("process projection must be a mapping")
        try:
            encoded = json.dumps(process_projection, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ConversationPersistenceError(f"process projection is not JSON serializable: {exc}") from exc
        if len(encoded) > MAX_PROCESS_PROJECTION_CHARS:
            raise ConversationPersistenceError(
                f"process projection exceeds {MAX_PROCESS_PROJECTION_CHARS} characters"
            )
        return encoded

    @classmethod
    def _normalize_content(cls, value: str) -> str:
        """User content 采用与 Query contract 相同的非空文本语义。"""

        return cls._normalize_identity(value, "user_content")

    def _ensure_open(self) -> None:
        """关闭后拒绝静默重建连接，保持 Application lifecycle 显式。"""

        if self._closed:
            raise ConversationPersistenceError("conversation store is closed")
