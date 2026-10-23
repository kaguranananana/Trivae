"""SQLite Canonical Store。

SQLite 只负责保存已经规范化的 Canonical Model，不理解 QQ V5/0.1.0 的
source-specific 字段。所有重复、冲突和错误都写入可查询的记录，避免一次
导入结束后只剩一个“成功/失败”布尔值。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from trivae.data.ingestion.qq_forward import classify_forward_change
from trivae.data.model import (
    CanonicalMessage,
    ChatSession,
    ImportBatchSummary,
    IngestionError,
    SourceDescriptor,
)
from trivae.data.storage.sqlite_forward import ensure_canonical_revision

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    file_name TEXT NOT NULL UNIQUE,
    adapter TEXT NOT NULL,
    format_version TEXT NOT NULL,
    platform TEXT NOT NULL,
    external_chat_id TEXT NOT NULL,
    chat_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    external_chat_id TEXT NOT NULL,
    name TEXT NOT NULL,
    chat_type TEXT NOT NULL,
    self_uid TEXT,
    self_uin TEXT,
    first_message_timestamp INTEGER,
    last_message_timestamp INTEGER,
    UNIQUE(platform, external_chat_id)
);

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    platform_user_id TEXT NOT NULL,
    platform_uin TEXT,
    display_name TEXT,
    nickname TEXT,
    remark TEXT,
    last_seen_timestamp INTEGER,
    UNIQUE(platform, platform_user_id)
);

CREATE TABLE IF NOT EXISTS memberships (
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    display_name TEXT,
    nickname TEXT,
    group_card TEXT,
    remark TEXT,
    first_seen_timestamp INTEGER,
    last_seen_timestamp INTEGER,
    PRIMARY KEY(session_id, user_id),
    FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id),
    FOREIGN KEY(user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS import_batches (
    batch_id TEXT PRIMARY KEY,
    source_id TEXT,
    session_id TEXT,
    source_file TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    received_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    enriched_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    conflict_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    error_message TEXT,
    FOREIGN KEY(source_id) REFERENCES sources(source_id),
    FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id)
);

CREATE TABLE IF NOT EXISTS messages (
    internal_message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    source_message_id TEXT,
    fallback_identity_key TEXT,
    seq INTEGER,
    timestamp INTEGER NOT NULL,
    message_type TEXT NOT NULL,
    content_text TEXT NOT NULL,
    content_json TEXT NOT NULL,
    raw_payload_json TEXT NOT NULL,
    canonical_projection_json TEXT NOT NULL,
    sender_user_id TEXT,
    sender_platform_id TEXT,
    sender_uin TEXT,
    sender_name TEXT,
    sender_nickname TEXT,
    sender_group_card TEXT,
    sender_remark TEXT,
    reply_to_source_message_id TEXT,
    recalled INTEGER NOT NULL,
    system INTEGER NOT NULL,
    canonical_source_id TEXT NOT NULL,
    canonical_source_record_index INTEGER NOT NULL,
    UNIQUE(session_id, source_message_id),
    FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id),
    FOREIGN KEY(sender_user_id) REFERENCES users(user_id),
    FOREIGN KEY(canonical_source_id) REFERENCES sources(source_id)
);

CREATE TABLE IF NOT EXISTS message_sources (
    occurrence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    internal_message_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_record_index INTEGER NOT NULL,
    is_canonical INTEGER NOT NULL,
    FOREIGN KEY(internal_message_id) REFERENCES messages(internal_message_id),
    FOREIGN KEY(source_id) REFERENCES sources(source_id),
    UNIQUE(internal_message_id, source_id, source_record_index)
);

CREATE TABLE IF NOT EXISTS message_variants (
    variant_id INTEGER PRIMARY KEY AUTOINCREMENT,
    internal_message_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_record_index INTEGER NOT NULL,
    variant_kind TEXT NOT NULL,
    canonical_projection_json TEXT NOT NULL,
    raw_payload_json TEXT,
    FOREIGN KEY(internal_message_id) REFERENCES messages(internal_message_id),
    FOREIGN KEY(source_id) REFERENCES sources(source_id),
    UNIQUE(internal_message_id, source_id, source_record_index)
);

CREATE TABLE IF NOT EXISTS import_errors (
    error_id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    source_id TEXT,
    source_record_index INTEGER,
    error_code TEXT NOT NULL,
    error_message TEXT NOT NULL,
    raw_locator TEXT,
    FOREIGN KEY(batch_id) REFERENCES import_batches(batch_id),
    FOREIGN KEY(source_id) REFERENCES sources(source_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_session_time
    ON messages(session_id, timestamp, seq, internal_message_id);
CREATE INDEX IF NOT EXISTS idx_messages_session_source_id
    ON messages(session_id, source_message_id);
-- 回复关系补查按会话和回复目标定位，避免每个候选都扫描整段群聊。
CREATE INDEX IF NOT EXISTS idx_messages_session_reply
    ON messages(session_id, reply_to_source_message_id, timestamp, seq, internal_message_id);
CREATE INDEX IF NOT EXISTS idx_message_sources_message
    ON message_sources(internal_message_id);
CREATE INDEX IF NOT EXISTS idx_import_batches_source
    ON import_batches(source_file, started_at);
"""


@dataclass(frozen=True)
class MessageWriteResult:
    """单条消息写入后返回给 Shared Importer 的结果。"""

    inserted: bool
    conflict: bool
    enriched: bool = False


def utc_now() -> str:
    """统一用带 offset 的 UTC 文本记录 ingestion 生命周期。"""

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class SQLiteCanonicalStore:
    """管理 Canonical Store 连接、schema 和 ingestion 写入事务。"""

    def __init__(self, database_path: Path) -> None:
        # 只让 Composition Root 创建 Store；Store 本身不在 import 时创建全局连接。
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = database_path
        self.connection = sqlite3.connect(str(database_path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA_SQL)
        # 新批次指标需要同步升级已有数据库；历史版本未做正文补齐，旧行的真实值为零。
        batch_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(import_batches)")}
        if "enriched_count" not in batch_columns:
            self.connection.execute("ALTER TABLE import_batches ADD COLUMN enriched_count INTEGER NOT NULL DEFAULT 0")
        # 单调派生版本与消息写入同事务推进，不修改 canonical payload 或身份语义。
        ensure_canonical_revision(self.connection)
        self.connection.commit()

    def __enter__(self) -> SQLiteCanonicalStore:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        """显式关闭 SQLite 资源，交由 Application lifecycle 调用。"""

        self.connection.close()

    def begin(self) -> None:
        """开始一个文件级 transaction。"""

        self.connection.execute("BEGIN")

    def commit(self) -> None:
        """提交一个文件级 transaction。"""

        self.connection.commit()

    def rollback(self) -> None:
        """回滚当前文件 transaction，不删除其他已提交批次。"""

        self.connection.rollback()

    def create_batch(
        self,
        source_file: str,
        session_id: str | None,
        source_id: str | None,
        status: str = "running",
        error_message: str | None = None,
    ) -> str:
        """创建 ImportBatch，并返回不依赖消息内容的 batch identity。"""

        batch_id = uuid.uuid4().hex
        self.connection.execute(
            """
            INSERT INTO import_batches(
                batch_id, source_id, session_id, source_file, started_at, status, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (batch_id, source_id, session_id, source_file, utc_now(), status, error_message),
        )
        return batch_id

    def finish_batch(
        self,
        batch_id: str,
        received_count: int,
        inserted_count: int,
        duplicate_count: int,
        conflict_count: int,
        error_count: int,
        status: str,
        error_message: str | None = None,
        enriched_count: int = 0,
    ) -> ImportBatchSummary:
        """保存 batch 终态，并从同一条记录返回可序列化摘要。"""

        self.connection.execute(
            """
            UPDATE import_batches
            SET finished_at = ?, received_count = ?, inserted_count = ?, duplicate_count = ?,
                conflict_count = ?, error_count = ?, status = ?, error_message = ?, enriched_count = ?
            WHERE batch_id = ?
            """,
            (
                utc_now(),
                received_count,
                inserted_count,
                duplicate_count,
                conflict_count,
                error_count,
                status,
                error_message,
                enriched_count,
                batch_id,
            ),
        )
        row = self.connection.execute(
            """
            SELECT batch_id, source_file, session_id, received_count, inserted_count,
                   duplicate_count, conflict_count, error_count, status, error_message, enriched_count
            FROM import_batches
            WHERE batch_id = ?
            """,
            (batch_id,),
        ).fetchone()
        if row is None:
            raise IngestionError(f"ImportBatch disappeared before completion: {batch_id}")
        return ImportBatchSummary(
            batch_id=row["batch_id"],
            source_file=row["source_file"],
            session_id=row["session_id"],
            received_count=row["received_count"],
            inserted_count=row["inserted_count"],
            duplicate_count=row["duplicate_count"],
            conflict_count=row["conflict_count"],
            error_count=row["error_count"],
            status=row["status"],
            error_message=row["error_message"],
            enriched_count=row["enriched_count"],
        )

    def record_file_failure(
        self,
        source_file: str,
        error_code: str,
        error_message: str,
    ) -> ImportBatchSummary:
        """为文件级解析失败建立显式 failed batch，而不是静默跳过文件。"""

        self.begin()
        try:
            batch_id = self.create_batch(
                source_file=source_file,
                session_id=None,
                source_id=None,
                status="failed",
                error_message=error_message,
            )
            self.connection.execute(
                """
                INSERT INTO import_errors(
                    batch_id, source_id, source_record_index, error_code, error_message, raw_locator
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (batch_id, None, None, error_code, error_message, source_file),
            )
            summary = self.finish_batch(
                batch_id=batch_id,
                received_count=0,
                inserted_count=0,
                duplicate_count=0,
                conflict_count=0,
                error_count=1,
                status="failed",
                error_message=error_message,
            )
            self.commit()
            return summary
        except Exception:
            # failed batch 自身写入失败时保留原始异常，不伪造失败摘要。
            self.rollback()
            raise

    def upsert_source(self, source: SourceDescriptor) -> None:
        """登记来源文件，并阻止同名文件悄悄映射到另一个群。"""

        existing = self.connection.execute(
            "SELECT * FROM sources WHERE file_name = ?",
            (source.file_name,),
        ).fetchone()
        if existing is not None:
            immutable_fields = (
                ("source_id", source.source_id, existing["source_id"]),
                ("platform", source.platform, existing["platform"]),
                ("external_chat_id", source.external_chat_id, existing["external_chat_id"]),
                ("format_version", source.format_version, existing["format_version"]),
            )
            for field_name, incoming, stored in immutable_fields:
                if incoming != stored:
                    raise IngestionError(
                        f"Source file identity changed for {source.file_name}: "
                        f"{field_name}={stored!r} -> {incoming!r}"
                    )
            return

        self.connection.execute(
            """
            INSERT INTO sources(
                source_id, file_name, adapter, format_version, platform,
                external_chat_id, chat_name, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.source_id,
                source.file_name,
                source.adapter,
                source.format_version,
                source.platform,
                source.external_chat_id,
                source.chat_name,
                utc_now(),
            ),
        )

    def upsert_session(self, source: SourceDescriptor, session: ChatSession) -> None:
        """按稳定群身份创建 session，并保留可变名称的最新观察值。"""

        existing = self.connection.execute(
            "SELECT * FROM chat_sessions WHERE session_id = ?",
            (session.session_id,),
        ).fetchone()
        if existing is None:
            self.connection.execute(
                """
                INSERT INTO chat_sessions(
                    session_id, platform, external_chat_id, name, chat_type, self_uid, self_uin
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    session.platform,
                    session.external_chat_id,
                    session.name,
                    session.chat_type,
                    session.self_uid,
                    session.self_uin,
                ),
            )
            return

        # session identity 已由主键保证；这里检查平台/群号不被同名错误覆盖。
        if (
            existing["platform"] != session.platform
            or existing["external_chat_id"] != session.external_chat_id
        ):
            raise IngestionError(f"Session identity conflict: {session.session_id}")

    def observe_message_metadata(self, message: CanonicalMessage, chat_name: str | None = None) -> None:
        """用消息时间更新 session、user 和群内 membership 的可变观察字段。"""

        session_row = self.connection.execute(
            "SELECT * FROM chat_sessions WHERE session_id = ?",
            (message.session_id,),
        ).fetchone()
        if session_row is None:
            raise IngestionError(f"Message references missing session: {message.session_id}")

        first_timestamp = session_row["first_message_timestamp"]
        last_timestamp = session_row["last_message_timestamp"]
        is_newest_observation = last_timestamp is None or message.timestamp >= last_timestamp
        next_first = message.timestamp if first_timestamp is None else min(first_timestamp, message.timestamp)
        next_last = message.timestamp if last_timestamp is None else max(last_timestamp, message.timestamp)
        self.connection.execute(
            """
            UPDATE chat_sessions
            SET name = CASE WHEN ? THEN COALESCE(?, name) ELSE name END,
                first_message_timestamp = ?, last_message_timestamp = ?
            WHERE session_id = ?
            """,
            (int(is_newest_observation), chat_name, next_first, next_last, message.session_id),
        )

        if message.sender_user_id is None:
            # 系统消息没有稳定作者身份，只保留 message.sender_name snapshot。
            return

        platform_user_id = message.sender_platform_id or f"uin:{message.sender_uin}"
        user_row = self.connection.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (message.sender_user_id,),
        ).fetchone()
        if user_row is None:
            self.connection.execute(
                """
                INSERT INTO users(
                    user_id, platform, platform_user_id, platform_uin,
                    display_name, nickname, remark, last_seen_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.sender_user_id,
                    message.platform,
                    platform_user_id,
                    message.sender_uin,
                    message.sender_name,
                    message.sender_nickname,
                    message.sender_remark,
                    message.timestamp,
                ),
            )
        elif user_row["last_seen_timestamp"] is None or message.timestamp >= user_row["last_seen_timestamp"]:
            self.connection.execute(
                """
                UPDATE users
                SET platform_user_id = ?, platform_uin = ?, display_name = ?,
                    nickname = ?, remark = ?, last_seen_timestamp = ?
                WHERE user_id = ?
                """,
                (
                    platform_user_id,
                    message.sender_uin,
                    message.sender_name,
                    message.sender_nickname,
                    message.sender_remark,
                    message.timestamp,
                    message.sender_user_id,
                ),
            )

        membership = self.connection.execute(
            """
            SELECT * FROM memberships
            WHERE session_id = ? AND user_id = ?
            """,
            (message.session_id, message.sender_user_id),
        ).fetchone()
        if membership is None:
            self.connection.execute(
                """
                INSERT INTO memberships(
                    session_id, user_id, display_name, nickname, group_card, remark,
                    first_seen_timestamp, last_seen_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.session_id,
                    message.sender_user_id,
                    message.sender_name,
                    message.sender_nickname,
                    message.sender_group_card,
                    message.sender_remark,
                    message.timestamp,
                    message.timestamp,
                ),
            )
        else:
            first_seen = membership["first_seen_timestamp"]
            last_seen = membership["last_seen_timestamp"]
            next_first_seen = message.timestamp if first_seen is None else min(first_seen, message.timestamp)
            next_last_seen = message.timestamp if last_seen is None else max(last_seen, message.timestamp)
            if last_seen is None or message.timestamp >= last_seen:
                self.connection.execute(
                    """
                    UPDATE memberships
                    SET display_name = ?, nickname = ?, group_card = ?, remark = ?,
                        first_seen_timestamp = ?, last_seen_timestamp = ?
                    WHERE session_id = ? AND user_id = ?
                    """,
                    (
                        message.sender_name,
                        message.sender_nickname,
                        message.sender_group_card,
                        message.sender_remark,
                        next_first_seen,
                        next_last_seen,
                        message.session_id,
                        message.sender_user_id,
                    ),
                )
            else:
                self.connection.execute(
                    """
                    UPDATE memberships
                    SET first_seen_timestamp = ?
                    WHERE session_id = ? AND user_id = ?
                    """,
                    (next_first_seen, message.session_id, message.sender_user_id),
                )

    def write_message(self, message: CanonicalMessage) -> MessageWriteResult:
        """按 session + stable source ID 写入或归并一条 Canonical Message。"""

        projection_json = json.dumps(
            message.canonical_projection(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        existing = self._find_existing_message(message)
        if existing is None:
            self.connection.execute(
                """
                INSERT INTO messages(
                    internal_message_id, session_id, platform, source_message_id,
                    fallback_identity_key, seq, timestamp, message_type, content_text,
                    content_json, raw_payload_json, canonical_projection_json,
                    sender_user_id, sender_platform_id, sender_uin, sender_name,
                    sender_nickname, sender_group_card, sender_remark,
                    reply_to_source_message_id, recalled, system,
                    canonical_source_id, canonical_source_record_index
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.internal_message_id,
                    message.session_id,
                    message.platform,
                    message.source_message_id,
                    message.fallback_identity_key,
                    message.seq,
                    message.timestamp,
                    message.message_type,
                    message.content_text,
                    message.content_json,
                    message.raw_payload_json,
                    projection_json,
                    message.sender_user_id,
                    message.sender_platform_id,
                    message.sender_uin,
                    message.sender_name,
                    message.sender_nickname,
                    message.sender_group_card,
                    message.sender_remark,
                    message.reply_to_source_message_id,
                    int(message.recalled),
                    int(message.system),
                    message.canonical_source_id,
                    message.canonical_source_record_index,
                ),
            )
            self._record_message_source(
                message_internal_id=message.internal_message_id,
                source_id=message.canonical_source_id,
                source_record_index=message.canonical_source_record_index,
                is_canonical=True,
            )
            return MessageWriteResult(inserted=True, conflict=False)

        # 先记录每次输入出现的位置，即使它最终被识别为重复消息。
        existing_message_id = existing["internal_message_id"]
        self._record_message_source(
            message_internal_id=existing_message_id,
            source_id=message.canonical_source_id,
            source_record_index=message.canonical_source_record_index,
            is_canonical=False,
        )
        conflict = existing["canonical_projection_json"] != projection_json
        forward_change = "equal"
        if existing["content_json"] != message.content_json and (
            '"type":"forward"' in existing["content_json"] or '"type":"forward"' in message.content_json
        ):
            # 根消息稳定事实先一致，再比较真实转发正文；预览变化不能阻止已知空节点补齐。
            previous_core, incoming_core = json.loads(existing["canonical_projection_json"]), message.canonical_projection()
            previous_core.pop("content_text")
            incoming_core.pop("content_text")
            if previous_core == incoming_core:
                forward_change = classify_forward_change(
                    message, json.loads(existing["content_json"]), json.loads(message.content_json),
                )
        if forward_change == "enriched":
            # 覆盖前保存旧 Canonical 的原始来源，之后仍可追溯首次不完整导出。
            self._record_message_variant(
                existing_message_id, existing["canonical_source_id"], existing["canonical_source_record_index"],
                "superseded_forward", existing["canonical_projection_json"], existing["raw_payload_json"],
            )
            # 整份 incoming 保留全部已知事实，来源可以准确指向这一次完整度更高的导出。
            self.connection.execute(
                """UPDATE messages SET content_text=?, content_json=?, raw_payload_json=?,
                   canonical_projection_json=?, canonical_source_id=?, canonical_source_record_index=?
                   WHERE internal_message_id=?""",
                (message.content_text, message.content_json, message.raw_payload_json, projection_json,
                 message.canonical_source_id, message.canonical_source_record_index, existing_message_id),
            )
            # 真实 UPDATE 在原事务内推进 revision，既有索引队列据此发布转发和语义增量。
            self.connection.execute("UPDATE message_sources SET is_canonical=0 WHERE internal_message_id=?",
                                    (existing_message_id,))
            self.connection.execute(
                "UPDATE message_sources SET is_canonical=1 WHERE internal_message_id=? AND source_id=? "
                "AND source_record_index=?",
                (existing_message_id, message.canonical_source_id, message.canonical_source_record_index),
            )
            return MessageWriteResult(inserted=False, conflict=False, enriched=True)
        conflict = conflict or forward_change == "conflict"
        is_same_canonical_occurrence = (
            existing["canonical_source_id"] == message.canonical_source_id
            and existing["canonical_source_record_index"] == message.canonical_source_record_index
        )
        if not is_same_canonical_occurrence or forward_change == "conflict":
            if conflict:
                # 冲突 variant 保留 incoming raw，便于定位旧/新版 exporter 的真实差异。
                self._record_message_variant(
                    message_internal_id=existing_message_id,
                    source_id=message.canonical_source_id,
                    source_record_index=message.canonical_source_record_index,
                    variant_kind="conflict",
                    canonical_projection_json=projection_json,
                    raw_payload_json=message.raw_payload_json,
                )
            else:
                # 完全相同的重复仍保留 variant provenance，但不重复存 raw payload。
                self._record_message_variant(
                    message_internal_id=existing_message_id,
                    source_id=message.canonical_source_id,
                    source_record_index=message.canonical_source_record_index,
                    variant_kind="duplicate_equal",
                    canonical_projection_json=projection_json,
                    raw_payload_json=None,
                )
        return MessageWriteResult(inserted=False, conflict=conflict)

    def record_error(
        self,
        batch_id: str,
        source_id: str | None,
        record_index: int,
        error_code: str,
        error_message: str,
        raw_locator: str,
    ) -> None:
        """保存单条 record 的错误定位信息。"""

        self.connection.execute(
            """
            INSERT INTO import_errors(
                batch_id, source_id, source_record_index, error_code, error_message, raw_locator
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (batch_id, source_id, record_index, error_code, error_message, raw_locator),
        )

    def count(self, table_name: str) -> int:
        """为测试和真实导入核验提供有限的表计数读取。"""

        allowed_tables = {
            "sources",
            "chat_sessions",
            "users",
            "memberships",
            "messages",
            "message_sources",
            "message_variants",
            "import_batches",
            "import_errors",
        }
        if table_name not in allowed_tables:
            raise ValueError(f"Unsupported count table: {table_name}")
        row = self.connection.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
        return int(row["count"])

    def batch_rows(self) -> list[sqlite3.Row]:
        """返回按开始时间排序的批次，供 CLI/测试复核。"""

        return list(
            self.connection.execute(
                "SELECT * FROM import_batches ORDER BY started_at, source_file, batch_id"
            ).fetchall()
        )

    def _find_existing_message(self, message: CanonicalMessage) -> sqlite3.Row | None:
        """稳定 ID 优先，fallback internal ID 作为缺失 source ID 的查找路径。"""

        if message.source_message_id is not None:
            row = self.connection.execute(
                """
                SELECT * FROM messages
                WHERE session_id = ? AND source_message_id = ?
                """,
                (message.session_id, message.source_message_id),
            ).fetchone()
            if row is not None:
                return row
        return self.connection.execute(
            "SELECT * FROM messages WHERE internal_message_id = ?",
            (message.internal_message_id,),
        ).fetchone()

    def _record_message_source(
        self,
        message_internal_id: str,
        source_id: str,
        source_record_index: int,
        is_canonical: bool,
    ) -> None:
        """以来源文件+记录索引建立幂等 provenance occurrence。"""

        self.connection.execute(
            """
            INSERT OR IGNORE INTO message_sources(
                internal_message_id, source_id, source_record_index, is_canonical
            ) VALUES (?, ?, ?, ?)
            """,
            (message_internal_id, source_id, source_record_index, int(is_canonical)),
        )

    def _record_message_variant(
        self,
        message_internal_id: str,
        source_id: str,
        source_record_index: int,
        variant_kind: str,
        canonical_projection_json: str,
        raw_payload_json: str | None,
    ) -> None:
        """记录重复或冲突 variant；同一来源位置重跑时不膨胀数据库。"""

        self.connection.execute(
            """
            INSERT INTO message_variants(
                internal_message_id, source_id, source_record_index, variant_kind,
                canonical_projection_json, raw_payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(internal_message_id, source_id, source_record_index) DO UPDATE SET
                variant_kind=excluded.variant_kind,
                canonical_projection_json=excluded.canonical_projection_json,
                raw_payload_json=excluded.raw_payload_json
            WHERE message_variants.raw_payload_json IS NULL AND excluded.raw_payload_json IS NOT NULL
            """,
            (
                message_internal_id,
                source_id,
                source_record_index,
                variant_kind,
                canonical_projection_json,
                raw_payload_json,
            ),
        )
