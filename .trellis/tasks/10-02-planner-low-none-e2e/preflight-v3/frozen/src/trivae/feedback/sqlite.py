"""独立 SQLite 用户体验反馈 Store。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from trivae.data.storage.sqlite import utc_now

from .contracts import FeedbackPersistenceError, FeedbackRecord

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS user_feedback (
    feedback_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    scope_snapshot_json TEXT NOT NULL,
    rating TEXT NOT NULL CHECK (rating IN ('good', 'bad')),
    note TEXT,
    feedback_kind TEXT NOT NULL CHECK (feedback_kind = 'user_experiential'),
    UNIQUE(conversation_id, trace_id)
);

CREATE INDEX IF NOT EXISTS idx_user_feedback_updated
    ON user_feedback(updated_at DESC, feedback_id ASC);
"""


class SQLiteFeedbackStore:
    """拥有独立反馈数据库，不把用户评价写入 Conversation/Evaluation Store。"""

    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = database_path
        self.connection = sqlite3.connect(str(database_path))
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA_SQL)
        self.connection.commit()
        self._closed = False

    def save(self, record: FeedbackRecord) -> FeedbackRecord:
        """按一轮 conversation/trace 更新评价，保留首次创建时间和 feedback id。"""

        self._ensure_open()
        if not isinstance(record, FeedbackRecord):
            raise FeedbackPersistenceError("only a FeedbackRecord can be persisted")
        scope_json = json.dumps(record.scope_snapshot, ensure_ascii=False, sort_keys=True)
        timestamp = utc_now()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            existing = self.connection.execute(
                """
                SELECT feedback_id, created_at
                FROM user_feedback
                WHERE conversation_id = ? AND trace_id = ?
                """,
                (record.conversation_id, record.trace_id),
            ).fetchone()
            if existing is None:
                persisted = FeedbackRecord(
                    feedback_id=uuid.uuid4().hex,
                    created_at=timestamp,
                    updated_at=timestamp,
                    conversation_id=record.conversation_id,
                    trace_id=record.trace_id,
                    run_id=record.run_id,
                    scope_snapshot=record.scope_snapshot,
                    rating=record.rating,
                    note=record.note,
                )
                self.connection.execute(
                    """
                    INSERT INTO user_feedback(
                        feedback_id, created_at, updated_at, conversation_id, trace_id,
                        run_id, scope_snapshot_json, rating, note, feedback_kind
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        persisted.feedback_id,
                        persisted.created_at,
                        persisted.updated_at,
                        persisted.conversation_id,
                        persisted.trace_id,
                        persisted.run_id,
                        scope_json,
                        persisted.rating,
                        persisted.note,
                        persisted.feedback_kind,
                    ),
                )
            else:
                persisted = FeedbackRecord(
                    feedback_id=existing["feedback_id"],
                    created_at=existing["created_at"],
                    updated_at=timestamp,
                    conversation_id=record.conversation_id,
                    trace_id=record.trace_id,
                    run_id=record.run_id,
                    scope_snapshot=record.scope_snapshot,
                    rating=record.rating,
                    note=record.note,
                )
                self.connection.execute(
                    """
                    UPDATE user_feedback
                    SET updated_at = ?, run_id = ?, scope_snapshot_json = ?, rating = ?, note = ?
                    WHERE feedback_id = ?
                    """,
                    (
                        persisted.updated_at,
                        persisted.run_id,
                        scope_json,
                        persisted.rating,
                        persisted.note,
                        persisted.feedback_id,
                    ),
                )
            self.connection.commit()
            return persisted
        except sqlite3.Error as exc:
            self.connection.rollback()
            raise FeedbackPersistenceError("feedback persistence failed") from exc

    def get(self, conversation_id: str, trace_id: str) -> FeedbackRecord | None:
        """读取指定 Query 的最新用户体验评价。"""

        self._ensure_open()
        row = self.connection.execute(
            "SELECT * FROM user_feedback WHERE conversation_id = ? AND trace_id = ?",
            (conversation_id, trace_id),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def close(self) -> None:
        """关闭反馈连接；重复 close 安全。"""

        if self._closed:
            return
        self._closed = True
        self.connection.close()

    def _row_to_record(self, row: sqlite3.Row) -> FeedbackRecord:
        """把持久化 JSON 恢复为 bounded feedback projection。"""

        try:
            scope = json.loads(row["scope_snapshot_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise FeedbackPersistenceError("stored feedback scope is invalid JSON") from exc
        if not isinstance(scope, dict):
            raise FeedbackPersistenceError("stored feedback scope must be an object")
        allowed = scope.get("allowed_session_ids")
        if allowed is not None:
            if not isinstance(allowed, list) or any(not isinstance(item, str) for item in allowed):
                raise FeedbackPersistenceError("stored feedback session scope is invalid")
            scope["allowed_session_ids"] = tuple(allowed)
        try:
            return FeedbackRecord(
                feedback_id=row["feedback_id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                conversation_id=row["conversation_id"],
                trace_id=row["trace_id"],
                run_id=row["run_id"],
                scope_snapshot=scope,
                rating=row["rating"],
                note=row["note"],
                feedback_kind=row["feedback_kind"],
            )
        except (TypeError, ValueError) as exc:
            raise FeedbackPersistenceError("stored feedback violates its contract") from exc

    def _ensure_open(self) -> None:
        """关闭后拒绝隐式重建反馈连接。"""

        if self._closed:
            raise FeedbackPersistenceError("feedback store is closed")
