"""日报的只读数据选择及独立交付状态，不修改 Canonical 表。"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from trivae.data.storage.sqlite_read import ORDER_BY_SQL, PROJECTION_COLUMNS, _row_to_forward_tree
from trivae.digest.contracts import DigestSnapshot
from trivae.retrieval.structured import MessageProjection


def read_digest_snapshot(
    database: Path, *, start_timestamp: int, end_timestamp: int, after_revision: int | None = None,
) -> DigestSnapshot:
    """首期按明确时间窗读取；后续复用变更日志补上迟到消息及转发正文补齐。"""

    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        # 修订水位、根消息及回复必须来自同一个读快照；读完就释放事务，不占用模型等待时间。
        connection.execute("BEGIN")
        revision = int(connection.execute(
            "SELECT value FROM trivae_derived_meta WHERE key = 'canonical_revision'"
        ).fetchone()[0])
        if after_revision is not None and after_revision > revision:
            raise ValueError("日报水位高于当前数据库修订，不能复用另一个数据库的日报状态")
        if after_revision is None:
            change_join = ""
            where = "m.timestamp >= ? AND m.timestamp < ?"
            parameters = (start_timestamp, end_timestamp)
        else:
            # 用日志中的群与消息时间定位变化，不能用发言时间过滤掉刚入库的旧消息。
            change_join = """JOIN (
                SELECT DISTINCT new_session_id, new_timestamp FROM canonical_message_changes
                WHERE revision > ? AND revision <= ? AND new_timestamp IS NOT NULL
            ) AS changed ON changed.new_session_id = m.session_id AND changed.new_timestamp = m.timestamp """
            where = "1 = 1"
            parameters = (after_revision, revision)
        rows = connection.execute(
            f"SELECT {PROJECTION_COLUMNS} FROM messages AS m JOIN chat_sessions AS s USING(session_id) "
            f"{change_join}WHERE {where} ORDER BY m.session_id, {ORDER_BY_SQL}", parameters,
        ).fetchall()
        root_count = len(rows)
        roots = {str(row["internal_message_id"]) for row in rows}
        # 明确的直接回复可引用上一期发言；额外读入的父消息只作为上下文。
        targets = {(str(row["session_id"]), str(row["reply_to_source_message_id"]))
                   for row in rows if row["reply_to_source_message_id"] is not None}
        context_ids: set[str] = set()
        for session_id, source_id in sorted(targets):
            parent = connection.execute(
                f"SELECT {PROJECTION_COLUMNS} FROM messages AS m JOIN chat_sessions AS s USING(session_id) "
                "WHERE m.session_id = ? AND m.source_message_id = ?", (session_id, source_id),
            ).fetchone()
            if parent is not None and str(parent["internal_message_id"]) not in roots:
                context_ids.add(str(parent["internal_message_id"]))
                roots.add(str(parent["internal_message_id"]))
                rows.append(parent)
        messages: list[MessageProjection] = []
        missing: list[str] = []
        for row in rows:
            # 复用正式转发树投影，预览文字不会被冒充为转发内部正文。
            tree = _row_to_forward_tree(row)
            messages.extend((tree.root, *tree.messages))
            missing.extend(f"{tree.root.internal_message_id}/{path}" for path in tree.root.unexpanded_forward_paths)
            if tree.root.internal_message_id in context_ids:
                context_ids.update(item.internal_message_id for item in tree.messages)
        messages.sort(key=lambda item: (item.session_id, item.timestamp, item.seq or 0, item.internal_message_id))
        return DigestSnapshot(revision, start_timestamp, end_timestamp, root_count,
                              tuple(messages), frozenset(context_ids), tuple(missing))


class SQLiteDigestState:
    """只保存日报运行和发送结果，成功发送后才推进下一期的读取水位。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("""CREATE TABLE IF NOT EXISTS digest_runs (
            run_id TEXT PRIMARY KEY, day TEXT NOT NULL, status TEXT NOT NULL,
            start_timestamp INTEGER NOT NULL, end_timestamp INTEGER NOT NULL,
            through_revision INTEGER, report_directory TEXT NOT NULL,
            created_at TEXT NOT NULL, sent_at TEXT, last_error TEXT
        )""")
        self.connection.commit()

    def last_sent(self) -> dict[str, Any] | None:
        """只有服务端已接受的邮件参与水位计算，生成成功不代表已发送。"""

        row = self.connection.execute(
            "SELECT * FROM digest_runs WHERE status = 'sent' ORDER BY through_revision DESC, sent_at DESC LIMIT 1"
        ).fetchone()
        return None if row is None else dict(row)

    def latest(self, day: str | None = None) -> dict[str, Any] | None:
        """读取指定日期或最近一次运行，供命令和运维检查使用。"""

        where, parameters = ("", ()) if day is None else ("WHERE day = ?", (day,))
        row = self.connection.execute(
            f"SELECT * FROM digest_runs {where} ORDER BY created_at DESC LIMIT 1", parameters,
        ).fetchone()
        return None if row is None else dict(row)

    def first_window_start(self) -> int | None:
        """首封成功邮件之前保留最早尝试的起点，跨日失败不能缩掉原来待读的消息。"""

        value = self.connection.execute("SELECT MIN(start_timestamp) FROM digest_runs").fetchone()[0]
        return None if value is None else int(value)

    def pending_delivery(self) -> dict[str, Any] | None:
        """发件结果未确认的日报跨日仍须显式处理，不能被下一期覆盖。"""

        row = self.connection.execute(
            "SELECT * FROM digest_runs WHERE status IN ('ready', 'sending', 'send_failed', 'send_not_submitted') "
            "ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        return None if row is None else dict(row)

    def get(self, run_id: str) -> dict[str, Any]:
        """显式选择已生成的邮件，避免发送失败后重新消耗模型生成。"""

        row = self.connection.execute("SELECT * FROM digest_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise ValueError(f"日报运行不存在：{run_id}")
        return dict(row)

    def create(self, run_id: str, day: str, start: int, end: int, directory: Path, created_at: str) -> None:
        """在调用模型之前记录运行，进程中断仍有可检查的状态。"""

        self.connection.execute(
            "INSERT INTO digest_runs VALUES (?, ?, 'generating', ?, ?, NULL, ?, ?, NULL, NULL)",
            (run_id, day, start, end, str(directory.resolve()), created_at),
        )
        self.connection.commit()

    def update(self, run_id: str, status: str, *, revision: int | None = None,
               sent_at: str | None = None, error: str | None = None) -> None:
        """状态、错误及水位在一个事务提交，失败时不伪装为完成。"""

        self.connection.execute(
            "UPDATE digest_runs SET status = ?, through_revision = COALESCE(?, through_revision), "
            "sent_at = ?, last_error = ? WHERE run_id = ?", (status, revision, sent_at, error, run_id),
        )
        self.connection.commit()

    def close(self) -> None:
        """交付结束后释放独立状态连接。"""

        self.connection.close()
