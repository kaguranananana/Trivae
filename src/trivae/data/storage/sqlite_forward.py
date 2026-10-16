"""合并转发派生投影的 schema 与 canonical 变更版本，不拥有原始消息事实。"""

from __future__ import annotations

import sqlite3

# Canonical parser 固定采用紧凑 JSON；按 element type 扫描，不能依赖外层 message_type。
FORWARD_CONTENT_PREDICATE = """instr(m.content_json, '"type":"forward"') > 0"""

FORWARDED_SCHEMA_SQL = """
CREATE TABLE forwarded_messages (
    internal_message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    source_message_id TEXT,
    sender_user_id TEXT,
    sender_platform_id TEXT,
    sender_uin TEXT,
    sender_name TEXT,
    timestamp INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    message_type TEXT NOT NULL,
    content_text TEXT NOT NULL,
    reply_to_source_message_id TEXT,
    recalled INTEGER NOT NULL,
    system INTEGER NOT NULL,
    root_message_id TEXT NOT NULL,
    parent_message_id TEXT NOT NULL,
    path TEXT NOT NULL,
    original_timestamp INTEGER,
    source_file TEXT,
    source_record_index INTEGER,
    unexpanded_forward_paths_json TEXT NOT NULL
)
"""


def ensure_canonical_revision(connection: sqlite3.Connection) -> None:
    """安装单调版本追踪；相同消息数量的正文或来源修改也必须使索引失效。"""

    connection.execute(
        "CREATE TABLE IF NOT EXISTS trivae_derived_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    # 只在首次初始化写 0；删除派生索引、重新打开数据库或 rebuild 都不能重置版本。
    connection.execute("INSERT OR IGNORE INTO trivae_derived_meta(key, value) VALUES ('canonical_revision', '0')")
    for operation in ("INSERT", "UPDATE", "DELETE"):
        # operation 是固定内部枚举；版本和实际 canonical mutation 在同一 SQLite 事务提交。
        connection.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS trivae_canonical_revision_{operation.lower()}
            AFTER {operation} ON messages
            BEGIN
                UPDATE trivae_derived_meta SET value = CAST(value AS INTEGER) + 1
                WHERE key = 'canonical_revision';
            END
            """
        )
