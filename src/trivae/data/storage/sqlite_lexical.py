"""SQLite FTS5 derived index 的 rebuild boundary。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from trivae.data.storage.sqlite_lexical_text import FTS_TOKENIZER_STRATEGY_ID, normalize_lexical_index_text
from trivae.retrieval.structured import LexicalIndexError


@dataclass(frozen=True)
class LexicalIndexStats:
    """一次 derived index rebuild 的可验证摘要。"""

    indexed_messages: int
    rebuild_latency_ms: float
    fts5_available: bool


class SQLiteLexicalIndex:
    """只拥有 FTS derived data，不拥有 canonical message 事实。"""

    def __init__(self, database_path: Path) -> None:
        self._connection = sqlite3.connect(str(database_path))
        self._connection.row_factory = sqlite3.Row

    def close(self) -> None:
        """关闭 derived-index connection。"""

        self._connection.close()

    def probe_fts5(self) -> bool:
        """实际探测当前 SQLite runtime，而不是凭版本号猜测能力。"""

        try:
            self._connection.execute(
                "CREATE VIRTUAL TABLE temp.trivae_fts5_probe USING fts5(content)"
            )
            self._connection.execute("DROP TABLE temp.trivae_fts5_probe")
            return True
        except sqlite3.OperationalError:
            return False

    def rebuild(self) -> LexicalIndexStats:
        """从 canonical messages 全量重建 FTS；失败时回滚 derived 事务并原样抛错。"""

        if not self.probe_fts5():
            raise LexicalIndexError("Current SQLite runtime does not provide FTS5")

        started = perf_counter()
        self._connection.execute("BEGIN")
        try:
            # 先删除旧 derived index，再从 canonical source 生成，避免旧数据残留。
            self._connection.execute("DROP TABLE IF EXISTS messages_fts")
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
            # content_text 在入索引前做确定性 CJK bigram 归一化；unicode61 语义对
            # 非 Han 文本保持不变。strategy 标识写入 derived meta，供 read 侧校验 stale。
            self._connection.create_function(
                "trivae_normalize_lexical_text",
                1,
                normalize_lexical_index_text,
            )
            self._connection.execute(
                """
                INSERT INTO messages_fts(
                    internal_message_id, session_id, source_message_id, content_text
                )
                SELECT internal_message_id, session_id, source_message_id,
                       trivae_normalize_lexical_text(content_text)
                FROM messages
                """
            )
            row = self._connection.execute("SELECT COUNT(*) AS total FROM messages_fts").fetchone()
            canonical_row = self._connection.execute("SELECT COUNT(*) AS total FROM messages").fetchone()
            if row is None or canonical_row is None or int(row["total"]) != int(canonical_row["total"]):
                raise LexicalIndexError("FTS5 rebuild count does not match canonical messages")
            # 记录 rebuild 使用的归一化 strategy；read 侧据此显式拒绝旧索引而不是静默误召回。
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trivae_derived_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                INSERT INTO trivae_derived_meta(key, value) VALUES ('lexical_tokenizer_strategy', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (FTS_TOKENIZER_STRATEGY_ID,),
            )
            self._connection.commit()
        except Exception:
            # derived rebuild 失败不能留下半完成索引；canonical 表不在这个事务中被修改。
            self._connection.rollback()
            raise

        return LexicalIndexStats(
            indexed_messages=int(row["total"]),
            rebuild_latency_ms=(perf_counter() - started) * 1000,
            fts5_available=True,
        )

    def drop(self) -> None:
        """删除 derived index 以验证 canonical facts 不依赖 FTS。"""

        self._connection.execute("DROP TABLE IF EXISTS messages_fts")
        self._connection.execute("DROP TABLE IF EXISTS trivae_derived_meta")
        self._connection.commit()
