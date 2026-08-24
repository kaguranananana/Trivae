"""SQLite-backed Conversation Store。

该 Store 只拥有 Conversation tables，不修改 Canonical Chat Store，也不向
Retrieval read repository 暴露写入能力。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from trivae.capabilities.contracts import CapabilityContractError, ExecutionScope
from trivae.data.storage.sqlite import utc_now
from trivae.query.evidence import AnswerArtifact, scope_snapshot

from .contracts import (
    Conversation,
    ConversationMessage,
    ConversationNotFoundError,
    ConversationPersistenceError,
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
        self._ensure_scope_column()
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

    def list_summaries(self, limit: int = 20) -> tuple[ConversationSummary, ...]:
        """读取最近 conversation 的 bounded title/count/scope metadata。"""

        self._ensure_open()
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0 or limit > 100:
            raise ConversationPersistenceError("conversation history limit must be between 1 and 100")
        rows = self.connection.execute(
            """
            SELECT conversation_id, created_at, updated_at, scope_snapshot_json
            FROM conversations
            ORDER BY updated_at DESC, conversation_id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        summaries: list[ConversationSummary] = []
        for row in rows:
            message_row = self.connection.execute(
                """
                SELECT
                    COUNT(*) AS message_count,
                    MIN(CASE WHEN role = 'user' THEN ordinal END) AS first_user_ordinal
                FROM conversation_messages
                WHERE conversation_id = ?
                """,
                (row["conversation_id"],),
            ).fetchone()
            count = 0 if message_row is None else int(message_row["message_count"])
            first_user_ordinal = None if message_row is None else message_row["first_user_ordinal"]
            title = "New conversation"
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
            summaries.append(
                ConversationSummary(
                    conversation_id=row["conversation_id"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    title=title,
                    message_count=count,
                    scope=self._decode_scope(row["scope_snapshot_json"]),
                )
            )
        return tuple(summaries)

    def commit_turn(
        self,
        conversation_id: str,
        user_content: str,
        answer_artifact: AnswerArtifact,
    ) -> Conversation:
        """在同一 transaction 中追加 User 与 validated Assistant message。"""

        self._ensure_open()
        if not isinstance(answer_artifact, AnswerArtifact):
            raise ConversationPersistenceError("only an AnswerArtifact can be committed")

        # 先完成 JSON 编码和领域对象检查，避免 transaction 中途才发现 Artifact 不可持久化。
        artifact_json = serialize_answer_artifact(answer_artifact)
        normalized_user_content = self._normalize_content(user_content)

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
            self._insert_message(user_message, None)
            self._insert_message(assistant_message, artifact_json)
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

    def _insert_message(self, message: ConversationMessage, artifact_json: str | None) -> None:
        """集中持久化 message，保留可测试的 transaction 中间边界。"""

        self.connection.execute(
            """
            INSERT INTO conversation_messages(
                message_id, conversation_id, ordinal, role, content, created_at, answer_artifact_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.message_id,
                message.conversation_id,
                message.ordinal,
                message.role,
                message.content,
                message.created_at,
                artifact_json,
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
            SELECT message_id, conversation_id, ordinal, role, content, created_at, answer_artifact_json
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

    def _ensure_scope_column(self) -> None:
        """为旧版 Conversation 表执行一次 additive nullable migration。"""

        columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(conversations)").fetchall()
        }
        if "scope_snapshot_json" not in columns:
            self.connection.execute(
                "ALTER TABLE conversations ADD COLUMN scope_snapshot_json TEXT"
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

        try:
            return ConversationMessage(
                message_id=row["message_id"],
                conversation_id=row["conversation_id"],
                ordinal=row["ordinal"],
                role=role,
                content=row["content"],
                created_at=row["created_at"],
                answer_artifact=artifact,
            )
        except (TypeError, ValueError) as exc:
            raise ConversationPersistenceError("conversation message violates its domain contract") from exc

    @staticmethod
    def _normalize_identity(value: str, name: str) -> str:
        """Store 入口只接受非空 identity，不把空值映射成默认 conversation。"""

        if not isinstance(value, str) or not value.strip():
            raise ConversationPersistenceError(f"{name} must be a non-empty string")
        return value.strip()

    @classmethod
    def _normalize_content(cls, value: str) -> str:
        """User content 采用与 Query contract 相同的非空文本语义。"""

        return cls._normalize_identity(value, "user_content")

    def _ensure_open(self) -> None:
        """关闭后拒绝静默重建连接，保持 Application lifecycle 显式。"""

        if self._closed:
            raise ConversationPersistenceError("conversation store is closed")
