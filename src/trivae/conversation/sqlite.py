"""SQLite-backed Conversation Store。

该 Store 只拥有 Conversation tables，不修改 Canonical Chat Store，也不向
Retrieval read repository 暴露写入能力。
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from trivae.data.storage.sqlite import utc_now
from trivae.query.evidence import AnswerArtifact

from .contracts import (
    Conversation,
    ConversationMessage,
    ConversationNotFoundError,
    ConversationPersistenceError,
)
from .serialization import deserialize_answer_artifact, serialize_answer_artifact

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
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
        self.connection.commit()
        self._closed = False

    def close(self) -> None:
        """关闭 Conversation connection；重复 close 不产生额外副作用。"""

        if self._closed:
            return
        self._closed = True
        self.connection.close()

    def create_conversation(self) -> Conversation:
        """创建并立即提交一个空 conversation。"""

        self._ensure_open()
        conversation_id = uuid.uuid4().hex
        timestamp = utc_now()
        try:
            self.connection.execute(
                "INSERT INTO conversations(conversation_id, created_at, updated_at) VALUES (?, ?, ?)",
                (conversation_id, timestamp, timestamp),
            )
            self.connection.commit()
        except sqlite3.Error as exc:
            self.connection.rollback()
            raise ConversationPersistenceError("conversation creation failed") from exc
        return Conversation(conversation_id, timestamp, timestamp)

    def get_conversation(self, conversation_id: str) -> Conversation:
        """按稳定 ordinal 读取 conversation，不重新 hydrate 历史 Evidence。"""

        self._ensure_open()
        return self._load_conversation(conversation_id)

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
            "SELECT conversation_id, created_at, updated_at FROM conversations WHERE conversation_id = ?",
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
        )

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
