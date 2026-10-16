"""SQLite 唯一 FTS5 与合并转发 derived projection 的事务重建边界。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from trivae.data.ingestion.qq_forward import FORWARD_PROJECTION_VERSION, _own_content_text
from trivae.data.storage.sqlite_forward import (
    FORWARD_CONTENT_PREDICATE,
    FORWARDED_SCHEMA_SQL,
    ensure_canonical_revision,
)
from trivae.data.storage.sqlite_lexical_text import FTS_TOKENIZER_STRATEGY_ID, normalize_lexical_index_text
from trivae.data.storage.sqlite_read import ORDER_BY_SQL, PROJECTION_COLUMNS, _row_to_forward_tree
from trivae.retrieval.structured import LexicalIndexError


@dataclass(frozen=True)
class LexicalIndexStats:
    """一次 derived rebuild 的摘要；canonical 与内部 occurrence 单独计数。"""

    indexed_messages: int
    rebuild_latency_ms: float
    fts5_available: bool
    canonical_messages: int = 0
    forwarded_messages: int = 0
    unexpanded_forward_nodes: int = 0


class SQLiteLexicalIndex:
    """只拥有 FTS 与转发投影，不向 canonical messages 插入内部子消息。"""

    def __init__(self, database_path: Path) -> None:
        self._connection = sqlite3.connect(str(database_path))
        self._connection.row_factory = sqlite3.Row

    def close(self) -> None:
        """关闭 derived-index connection。"""

        self._connection.close()

    def probe_fts5(self) -> bool:
        """实际探测当前 SQLite runtime，而不是凭版本号猜测能力。"""

        try:
            self._connection.execute("CREATE VIRTUAL TABLE temp.trivae_fts5_probe USING fts5(content)")
            self._connection.execute("DROP TABLE temp.trivae_fts5_probe")
            return True
        except sqlite3.OperationalError:
            return False

    def rebuild(self) -> LexicalIndexStats:
        """在一个事务中替换投影、FTS 和版本；任何解析/写入失败保留旧索引。"""

        if not self.probe_fts5():
            raise LexicalIndexError("Current SQLite runtime does not provide FTS5")
        started = perf_counter()
        self._connection.execute("BEGIN")
        try:
            ensure_canonical_revision(self._connection)
            # writer 事务内读取 revision，期间 canonical 写入无法交叉提交。
            revision_row = self._connection.execute(
                "SELECT value FROM trivae_derived_meta WHERE key = 'canonical_revision'"
            ).fetchone()
            canonical_row = self._connection.execute("SELECT COUNT(*) AS total FROM messages").fetchone()
            if revision_row is None or canonical_row is None:
                raise LexicalIndexError("Canonical revision/count is unavailable")
            canonical_count = int(canonical_row["total"])
            self._connection.execute("DROP TABLE IF EXISTS messages_fts")
            self._connection.execute("DROP TABLE IF EXISTS forwarded_messages")
            self._connection.execute(FORWARDED_SCHEMA_SQL)
            self._connection.execute(
                "CREATE INDEX idx_forwarded_session_time ON forwarded_messages(session_id, timestamp, seq)"
            )
            self._connection.execute(
                """
                CREATE VIRTUAL TABLE messages_fts USING fts5(
                    internal_message_id UNINDEXED,
                    session_id UNINDEXED,
                    source_message_id UNINDEXED,
                    content_text,
                    tokenize = 'unicode61'
                )
                """
            )
            self._connection.create_function("trivae_normalize_lexical_text", 1, normalize_lexical_index_text)
            self._connection.create_function(
                "trivae_forward_own_text", 1, lambda content: _own_content_text(json.loads(content))
            )
            # 普通消息沿用原正文；forward 容器只索引真实 text element，不索引 preview。
            self._connection.execute(
                f"""
                INSERT INTO messages_fts(internal_message_id, session_id, source_message_id, content_text)
                SELECT m.internal_message_id, m.session_id, m.source_message_id,
                       trivae_normalize_lexical_text(
                           CASE WHEN {FORWARD_CONTENT_PREDICATE}
                           THEN trivae_forward_own_text(m.content_json) ELSE m.content_text END
                       )
                FROM messages AS m
                """
            )
            cursor = self._connection.execute(
                f"""
                SELECT {PROJECTION_COLUMNS}
                FROM messages AS m
                INNER JOIN chat_sessions AS s ON s.session_id = m.session_id
                WHERE {FORWARD_CONTENT_PREDICATE}
                ORDER BY m.session_id ASC, {ORDER_BY_SQL}
                """
            )
            forwarded_count = 0
            missing_count = 0
            while rows := cursor.fetchmany(256):
                for row in rows:
                    tree = _row_to_forward_tree(row)
                    missing_count += len(tree.root.unexpanded_forward_paths)
                    for message in tree.messages:
                        provenance = message.forward
                        if provenance is None:
                            raise LexicalIndexError("Forward projection is missing its canonical locator")
                        self._connection.execute(
                            """
                            INSERT INTO forwarded_messages VALUES (
                                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                            )
                            """,
                            (
                                message.internal_message_id, message.session_id, message.source_message_id,
                                message.sender_user_id, message.sender_platform_id, message.sender_uin,
                                message.sender_name, message.timestamp, message.seq, message.message_type,
                                message.normalized_content, message.reply_to_source_message_id,
                                int(message.recalled), int(message.system), provenance.root_message_id,
                                provenance.parent_message_id, provenance.path, provenance.original_timestamp,
                                provenance.source_file, provenance.source_record_index,
                                json.dumps(message.unexpanded_forward_paths, ensure_ascii=False),
                            ),
                        )
                        self._connection.execute(
                            "INSERT INTO messages_fts VALUES (?, ?, ?, ?)",
                            (
                                message.internal_message_id, message.session_id, message.source_message_id,
                                normalize_lexical_index_text(message.normalized_content),
                            ),
                        )
                        forwarded_count += 1
            indexed_row = self._connection.execute("SELECT COUNT(*) AS total FROM messages_fts").fetchone()
            if indexed_row is None or int(indexed_row["total"]) != canonical_count + forwarded_count:
                raise LexicalIndexError("FTS5 rebuild count does not match canonical plus forward occurrences")
            # 索引版本与精确 revision 必须一起提交，不能让读取端接受半完成的新投影。
            self._connection.executemany(
                """
                INSERT INTO trivae_derived_meta(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (
                    ("lexical_tokenizer_strategy", FTS_TOKENIZER_STRATEGY_ID),
                    ("lexical_forward_projection", FORWARD_PROJECTION_VERSION),
                    ("lexical_canonical_revision", str(revision_row["value"])),
                    ("lexical_canonical_count", str(canonical_count)),
                    ("lexical_forwarded_count", str(forwarded_count)),
                    ("lexical_unexpanded_forward_nodes", str(missing_count)),
                ),
            )
            self._connection.commit()
        except Exception:
            # DROP/CREATE、投影与 FTS 内容都受同一事务保护，失败不损坏原来的可用索引。
            self._connection.rollback()
            raise
        return LexicalIndexStats(
            indexed_messages=canonical_count + forwarded_count,
            rebuild_latency_ms=(perf_counter() - started) * 1000,
            fts5_available=True,
            canonical_messages=canonical_count,
            forwarded_messages=forwarded_count,
            unexpanded_forward_nodes=missing_count,
        )

    def drop(self) -> None:
        """只删除可重建的数据，保留单调 canonical revision 及其触发器。"""

        self._connection.execute("DROP TABLE IF EXISTS messages_fts")
        self._connection.execute("DROP TABLE IF EXISTS forwarded_messages")
        self._connection.execute("DELETE FROM trivae_derived_meta WHERE key LIKE 'lexical_%'")
        self._connection.commit()
