"""无人值守导入的轻量 Composition Root，不创建 Query / Evaluation / 模型资源。"""

from __future__ import annotations

import fcntl
import math
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from trivae.data.ingestion.auto_import import IncrementalImporter
from trivae.data.ingestion.auto_import_contracts import (
    AutoImportReport,
    ImportAlreadyRunning,
    IncrementalIndexUpdater,
)
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.data.storage.sqlite_auto_import import SQLiteAutoImportState


@contextmanager
def import_lock(database_path: Path) -> Iterator[None]:
    """按数据库绝对路径互斥；锁由内核随进程退出释放，不依赖删除锁文件。"""

    database_path = database_path.resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    # 进程锁文件必须保持同一 inode，退出时不 unlink，否则会产生两把独立锁。
    with database_path.with_name(database_path.name + ".import-once.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ImportAlreadyRunning(f"import-once already running for {database_path}") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def run_import_once(
    database_path: Path,
    raw_directory: Path,
    *,
    settle_seconds: float = 5,
    min_age_seconds: float = 60,
    index_updater: IncrementalIndexUpdater | None = None,
) -> AutoImportReport:
    """在拿锁后才打开 Canonical Store，始终复用既有 SharedImporter。"""

    if any(not math.isfinite(value) or value < 0 for value in (settle_seconds, min_age_seconds)):
        raise ValueError("settle_seconds and min_age_seconds must be finite and non-negative")
    # 互斥覆盖建表、恢复、快照、导入和索引确认的完整生命周期。
    with import_lock(database_path):
        with SQLiteCanonicalStore(database_path.resolve()) as store:
            # 没有另一套 Parser 或 Store；轻量入口仅省去与导入无关的 Query 资源。
            return IncrementalImporter(SharedImporter(store), index_updater=index_updater).run(
                raw_directory, settle_seconds=settle_seconds, min_age_seconds=min_age_seconds
            )


def read_import_status(database_path: Path) -> dict[str, object]:
    """状态检查只读，不取得写入连接或创建数据库。"""

    return SQLiteAutoImportState.read_status(database_path)
