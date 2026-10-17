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
    # 首次安装记录当前水位；旧索引若早于此水位，必须显式重建，不能猜测缺失历史。
    connection.execute(
        """INSERT OR IGNORE INTO trivae_derived_meta(key, value)
           SELECT 'semantic_changes_baseline_revision', value FROM trivae_derived_meta
           WHERE key = 'canonical_revision'"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS canonical_message_changes (
            revision INTEGER PRIMARY KEY,
            old_session_id TEXT,
            old_timestamp INTEGER,
            new_session_id TEXT,
            new_timestamp INTEGER
        )"""
    )
    # UPDATE 只有字段真实变化才推进版本，避免幂等写入制造无用索引义务。
    columns = [str(row[1]) for row in connection.execute("PRAGMA table_info(messages)")]
    changed = " OR ".join(f'OLD."{column}" IS NOT NEW."{column}"' for column in columns)
    locations = {
        "INSERT": "NULL, NULL, NEW.session_id, NEW.timestamp",
        "UPDATE": "OLD.session_id, OLD.timestamp, NEW.session_id, NEW.timestamp",
        "DELETE": "OLD.session_id, OLD.timestamp, NULL, NULL",
    }
    for operation, location in locations.items():
        # 替换旧版仅计数 trigger；修订与位置记录始终由同一个 trigger 原子推进。
        trigger = f"trivae_canonical_revision_{operation.lower()}"
        connection.execute(f"DROP TRIGGER IF EXISTS {trigger}")
        condition = f"WHEN {changed}" if operation == "UPDATE" else ""
        connection.execute(
            f"""
            CREATE TRIGGER {trigger}
            AFTER {operation} ON messages
            {condition}
            BEGIN
                UPDATE trivae_derived_meta SET value = CAST(value AS INTEGER) + 1
                WHERE key = 'canonical_revision';
                INSERT INTO canonical_message_changes
                SELECT CAST(value AS INTEGER), {location}
                FROM trivae_derived_meta WHERE key = 'canonical_revision';
            END
            """
        )
    # 群名进入 embedding header；时间摘要或相同群名的重复 upsert 不属于语义变更。
    connection.execute(
        """CREATE TRIGGER IF NOT EXISTS trivae_canonical_session_name
        AFTER UPDATE OF name ON chat_sessions
        WHEN OLD.name IS NOT NEW.name
        BEGIN
            UPDATE trivae_derived_meta SET value = CAST(value AS INTEGER) + 1
            WHERE key = 'canonical_revision';
            INSERT INTO canonical_message_changes
            SELECT CAST(value AS INTEGER), OLD.session_id, NULL, NEW.session_id, NULL
            FROM trivae_derived_meta WHERE key = 'canonical_revision';
        END"""
    )
