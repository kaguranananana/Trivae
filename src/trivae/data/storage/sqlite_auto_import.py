"""自动导入状态与索引补偿队列；只添加运维表，不修改 Canonical Schema。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from itertools import groupby
from pathlib import Path
from typing import cast

from trivae.data.ingestion.auto_import_contracts import FileVersion, IndexKind, IndexWork
from trivae.data.model import ImportBatchSummary, ParsedExport
from trivae.data.storage.sqlite import utc_now

AUTO_IMPORT_SCHEMA = """
CREATE TABLE IF NOT EXISTS auto_import_files (
    path TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    status TEXT NOT NULL,
    batch_id TEXT,
    baseline_rowid INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS auto_import_index_work (
    batch_id TEXT NOT NULL,
    index_kind TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_id TEXT,
    session_id TEXT,
    inserted_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    last_error TEXT,
    PRIMARY KEY(batch_id, index_kind),
    FOREIGN KEY(batch_id) REFERENCES import_batches(batch_id)
);
CREATE TABLE IF NOT EXISTS auto_import_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    summary_json TEXT,
    last_error TEXT
);
"""


class SQLiteAutoImportState:
    """与 SharedImporter 共用连接，恢复依据始终是已提交的 ImportBatch。"""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.executescript(AUTO_IMPORT_SCHEMA)
        self.connection.commit()

    def start_run(self) -> str:
        """锁已取得；上一进程留下的 running 因而可明确标记为中断。"""

        run_id = uuid.uuid4().hex
        with self.connection:
            self.connection.execute(
                """UPDATE auto_import_runs SET status = 'interrupted', finished_at = ?,
                   last_error = 'Process exited before finishing the run' WHERE status = 'running'""",
                (utc_now(),),
            )
            self.connection.execute(
                "INSERT INTO auto_import_runs(run_id, started_at, status) VALUES (?, ?, 'running')",
                (run_id, utc_now()),
            )
        return run_id

    def finish_run(self, run_id: str, *, summary: dict[str, object] | None = None, error: str | None = None) -> None:
        """保留每次调用的终态，空目录执行也有调度证据。"""

        with self.connection:
            self.connection.execute(
                """UPDATE auto_import_runs SET finished_at = ?, status = ?, summary_json = ?,
                   last_error = ? WHERE run_id = ?""",
                (
                    utc_now(),
                    summary["status"] if summary is not None else "failed",
                    json.dumps(summary, ensure_ascii=False) if summary is not None else None,
                    error,
                    run_id,
                ),
            )

    def file(self, path: Path) -> sqlite3.Row | None:
        """按绝对输入路径读取最后一次观察结果。"""

        return self.connection.execute("SELECT * FROM auto_import_files WHERE path = ?", (str(path),)).fetchone()

    def observe(self, path: Path, version: str, status: str, error: str | None = None) -> None:
        """保存 deferred / failed 等非成功状态，下次执行仍须检查。"""

        with self.connection:
            self.connection.execute(
                """INSERT INTO auto_import_files(path, version, status, updated_at, last_error)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(path) DO UPDATE SET version = excluded.version, status = excluded.status,
                   updated_at = excluded.updated_at, last_error = excluded.last_error""",
                (str(path), version, status, utc_now(), error),
            )

    def prepare(self, path: Path, version: FileVersion) -> None:
        """先提交处理意图，填补 Canonical 提交与文件状态更新之间的中断窗口。"""

        # 只观察当前文件的批次，不扫描 messages 大表。
        row = self.connection.execute(
            "SELECT COALESCE(MAX(rowid), 0) FROM import_batches WHERE source_file = ?", (path.name,)
        ).fetchone()
        # 此时尚未调用 importer，水位后的首个批次才可能是本次提交。
        baseline = int(row[0])
        with self.connection:
            self.connection.execute(
                """INSERT INTO auto_import_files(
                       path, version, status, baseline_rowid, attempts, updated_at
                   ) VALUES (?, ?, 'importing', ?, 1, ?)
                   ON CONFLICT(path) DO UPDATE SET version = excluded.version, status = 'importing',
                   batch_id = NULL, baseline_rowid = excluded.baseline_rowid,
                   attempts = auto_import_files.attempts + 1, updated_at = excluded.updated_at, last_error = NULL""",
                (str(path), version.serialized(), baseline, utc_now()),
            )

    def finish_file(self, path: Path, version: str, batch: ImportBatchSummary, *, enqueue: bool = True) -> None:
        """仅消费 importer 已提交的批次；状态与索引义务在同一事务中保存。"""

        with self.connection:
            # importer 返回之前已经完成文件级 commit，此处不会提前宣称成功。
            self.connection.execute(
                """INSERT INTO auto_import_files(path, version, status, batch_id, updated_at, last_error)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(path) DO UPDATE SET version = excluded.version, status = excluded.status,
                   batch_id = excluded.batch_id, updated_at = excluded.updated_at, last_error = excluded.last_error""",
                (str(path), version, batch.status, batch.batch_id, utc_now(), batch.error_message),
            )
            # 历史接管不是本次新增；duplicate-only 批次也不会制造索引工作。
            if enqueue and batch.inserted_count > 0:
                source_id = self.connection.execute(
                    "SELECT source_id FROM import_batches WHERE batch_id = ?", (batch.batch_id,)
                ).fetchone()[0]
                for kind in ("lexical", "semantic"):
                    # 恢复可重复运行，不能把已成功的索引工作重置为 pending。
                    self.connection.execute(
                        """INSERT OR IGNORE INTO auto_import_index_work(
                               batch_id, index_kind, source_file, source_id, session_id,
                               inserted_count, status, updated_at
                           ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
                        (
                            batch.batch_id,
                            kind,
                            batch.source_file,
                            source_id,
                            batch.session_id,
                            batch.inserted_count,
                            utc_now(),
                        ),
                    )

    def recover(self) -> tuple[tuple[Path, str, ImportBatchSummary | None], ...]:
        """将遗留 importing 意图与 durable batch 对照，避免中断后重复解析。"""

        rows = self.connection.execute(
            "SELECT * FROM auto_import_files WHERE status = 'importing' ORDER BY path"
        ).fetchall()
        recovered: list[tuple[Path, str, ImportBatchSummary | None]] = []
        for row in rows:
            path = Path(row["path"])
            # 不按 finished_at 猜测事务是否成功；未提交的行在 SQLite 重启后不存在。
            batch_row = self.connection.execute(
                """SELECT * FROM import_batches WHERE source_file = ? AND rowid > ?
                   ORDER BY rowid LIMIT 1""",
                (path.name, row["baseline_rowid"]),
            ).fetchone()
            batch = self._batch(batch_row) if batch_row is not None else None
            if batch is None:
                self.observe(path, row["version"], "pending", "Interrupted before a batch committed; retry required")
            else:
                self.finish_file(path, row["version"], batch)
            recovered.append((path, row["version"], batch))
        return tuple(recovered)

    def historical_candidate(self, path: Path, version: FileVersion) -> ImportBatchSummary | None:
        """时间仅用于筛选候选；历史接管还必须逐条核对已有原始记录。"""

        row = self.connection.execute(
            """SELECT b.*, s.adapter, s.file_name FROM import_batches b
               LEFT JOIN sources s ON s.source_id = b.source_id
               WHERE b.source_file = ? ORDER BY b.rowid DESC LIMIT 1""",
            (path.name,),
        ).fetchone()
        if row is None or row["status"] != "completed" or row["adapter"] != "qq_chat_exporter":
            return None
        if row["file_name"] != path.name:
            return None
        # 两个时间只能排除明确变过的文件，不能证明 Parser 当时读取了当前内容。
        started_ns = int(datetime.fromisoformat(row["started_at"]).timestamp() * 1_000_000_000)
        if max(version.modified_ns, version.changed_ns) >= started_ns:
            return None
        return self._batch(row)

    def matches_historical_export(self, parsed: ParsedExport, batch: ImportBatchSummary) -> bool:
        """核验旧来源记录是否完整覆盖当前快照，不做规范化或重复写入。"""

        # 旧批次未保存解析前的文件版本；记录数不符时必须交回共享导入器补齐。
        if batch.received_count != len(parsed.messages):
            return False
        source = self.connection.execute(
            """SELECT s.*, c.chat_type, c.self_uid, c.self_uin FROM sources s
               JOIN chat_sessions c ON c.platform = s.platform AND c.external_chat_id = s.external_chat_id
               WHERE s.source_id = ?""",
            (parsed.source.source_id,),
        ).fetchone()
        # 不允许用已有消息掩盖当前文件的来源身份或格式变化。
        if source is None or any(source[key] != value for key, value in asdict(parsed.source).items()):
            return False
        rows = self.connection.execute(
            """SELECT occurrence.source_record_index, message.raw_payload_json AS canonical_raw,
                      variant.raw_payload_json AS variant_raw
               FROM message_sources occurrence
               JOIN messages message ON message.internal_message_id = occurrence.internal_message_id
               LEFT JOIN message_variants variant
                 ON variant.internal_message_id = occurrence.internal_message_id
                AND variant.source_id = occurrence.source_id
                AND variant.source_record_index = occurrence.source_record_index
               WHERE occurrence.source_id = ? ORDER BY occurrence.source_record_index""",
            (parsed.source.source_id,),
        )
        verified = 0
        for index, occurrences in groupby(rows, key=lambda row: row["source_record_index"]):
            # 同一位置可能留有旧版本 occurrence；当前每一条记录都必须找到精确原始证据。
            if index >= len(parsed.messages):
                break
            if index != verified:
                return False
            expected = json.dumps(parsed.messages[index], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            # duplicate_equal 未保存 incoming raw 时不能猜测等价，仍走原幂等导入主链路。
            if not any(expected in (row["canonical_raw"], row["variant_raw"]) for row in occurrences):
                return False
            verified += 1
        return verified == len(parsed.messages)

    def pending_indexes(self, kind: IndexKind | None = None) -> tuple[IndexWork, ...]:
        """running 也需要重放，覆盖索引已提交但确认状态前进程退出的情形。"""

        rows = self.connection.execute(
            """SELECT * FROM auto_import_index_work WHERE status != 'completed'
               AND (? IS NULL OR index_kind = ?) ORDER BY updated_at, batch_id, index_kind""",
            (kind, kind),
        ).fetchall()
        return tuple(
            IndexWork(
                batch_id=row["batch_id"],
                index_kind=cast(IndexKind, row["index_kind"]),
                source_file=row["source_file"],
                source_id=row["source_id"],
                session_id=row["session_id"],
                inserted_count=row["inserted_count"],
                status=row["status"],
                attempts=row["attempts"],
                last_error=row["last_error"],
            )
            for row in rows
        )

    def mark_indexes(self, work: tuple[IndexWork, ...], status: str, error: str | None = None) -> None:
        """索引尝试与错误显式持久化；仅 updater 成功返回后标 completed。"""

        with self.connection:
            self.connection.executemany(
                """UPDATE auto_import_index_work SET status = ?, last_error = ?, updated_at = ?,
                   attempts = attempts + ? WHERE batch_id = ? AND index_kind = ?""",
                [(status, error, utc_now(), int(status == "running"), item.batch_id, item.index_kind) for item in work],
            )

    @staticmethod
    def _batch(row: sqlite3.Row) -> ImportBatchSummary:
        """复用既有批次契约，不在调度层重新推导导入统计。"""

        return ImportBatchSummary(**{field: row[field] for field in ImportBatchSummary.__dataclass_fields__})

    @staticmethod
    def read_status(database_path: Path) -> dict[str, object]:
        """只读状态入口；查看状态不会初始化或迁移生产数据库。"""

        if not database_path.exists():
            return {"status": "not_initialized", "database": str(database_path)}
        with closing(sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            if connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'auto_import_runs'").fetchone() is None:
                return {"status": "not_initialized", "database": str(database_path)}
            latest = connection.execute("SELECT * FROM auto_import_runs ORDER BY rowid DESC LIMIT 1").fetchone()
            files = connection.execute(
                "SELECT status, COUNT(*) AS count FROM auto_import_files GROUP BY status"
            ).fetchall()
            pending = connection.execute(
                """SELECT * FROM auto_import_index_work WHERE status != 'completed'
                   ORDER BY updated_at, batch_id, index_kind"""
            ).fetchall()
            unfinished = connection.execute(
                "SELECT * FROM auto_import_files WHERE status != 'completed' ORDER BY path"
            ).fetchall()
            return {
                "status": "initialized",
                "database": str(database_path.resolve()),
                "last_run": dict(latest) if latest is not None else None,
                "files": {row["status"]: row["count"] for row in files},
                "unfinished_files": [dict(row) for row in unfinished],
                "pending_indexes": [dict(row) for row in pending],
                "retrieval_readiness": "pending" if pending else "not_verified",
            }
