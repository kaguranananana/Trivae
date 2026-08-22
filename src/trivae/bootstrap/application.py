"""M0/M1 Composition Root 与 Application facade。"""

from __future__ import annotations

from pathlib import Path

from trivae.data.ingestion.importer import SharedImporter
from trivae.data.model import ImportRunSummary
from trivae.data.storage.sqlite import SQLiteCanonicalStore


class TrivaeApplication:
    """第一版只暴露 ingestion facade，未来 Query/Evaluation 在此扩展。"""

    def __init__(self, store: SQLiteCanonicalStore, importer: SharedImporter) -> None:
        self.store = store
        self.importer = importer

    def import_directory(self, raw_directory: Path) -> ImportRunSummary:
        """让 CLI 通过 Application 进入 data ingestion，而不是直接读 Store。"""

        return self.importer.import_directory(raw_directory)

    def close(self) -> None:
        """集中关闭 core resource；不在模块 import 时创建全局资源。"""

        self.store.close()

    def __enter__(self) -> TrivaeApplication:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()


def create_application(database_path: Path) -> TrivaeApplication:
    """Composition Root 统一装配 SQLite Store、Parser 和 Shared Importer。"""

    store = SQLiteCanonicalStore(database_path)
    importer = SharedImporter(store)
    return TrivaeApplication(store=store, importer=importer)
