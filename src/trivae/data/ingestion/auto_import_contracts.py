"""自动导入的文件版本、结果及索引交接契约。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol

from trivae.data.model import ImportBatchSummary, ImportRunSummary, IngestionError

IndexKind = Literal["lexical", "semantic"]


class FileStillChanging(IngestionError):
    """源文件尚未达到稳定观察条件，留待后续执行补偿。"""

    error_code = "SOURCE_STILL_CHANGING"


class ImportAlreadyRunning(IngestionError):
    """同一数据库已有 import-once 持有进程锁。"""

    error_code = "IMPORT_ALREADY_RUNNING"


@dataclass(frozen=True)
class FileVersion:
    """使用文件系统事实识别版本，避免为大文件计算内容摘要。"""

    device: int
    inode: int
    size: int
    modified_ns: int
    changed_ns: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> FileVersion:
        """同时用于路径 stat 和已打开文件 fstat，检测替换及写入。"""

        return cls(value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    @classmethod
    def read(cls, path: Path) -> FileVersion:
        """读取当前版本，不打开或解析 JSON。"""

        return cls.from_stat(path.stat())

    def serialized(self) -> str:
        """持久化可解释的原始文件属性。"""

        return json.dumps(asdict(self), sort_keys=True)


@dataclass(frozen=True)
class IndexWork:
    """一个已提交批次对一种索引产生的补偿工作。"""

    batch_id: str
    index_kind: IndexKind
    source_file: str
    source_id: str | None
    session_id: str | None
    inserted_count: int
    status: str
    attempts: int
    last_error: str | None


class IncrementalIndexUpdater(Protocol):
    """集成时实现此接口；成功返回表示这些批次已经可检索。"""

    def update(self, index_kind: IndexKind, work: tuple[IndexWork, ...]) -> None:
        """增量更新并提交索引；提交后中断可能重放，因此实现必须幂等。"""

        ...


@dataclass(frozen=True)
class FileOutcome:
    """每个文件本次处理的可观测结果。"""

    path: str
    status: str
    reason: str | None = None
    batch_id: str | None = None


@dataclass(frozen=True)
class AutoImportReport:
    """区分 Canonical 提交结果与尚未完成的检索索引工作。"""

    run_id: str
    files: tuple[FileOutcome, ...]
    batches: tuple[ImportBatchSummary, ...]
    pending_indexes: tuple[IndexWork, ...]
    updater_connected: bool

    @property
    def exit_code(self) -> int:
        """失败、待稳定及待集成均明确非零，供 launchd 失败重试。"""

        if any(item.status in {"failed", "partial"} for item in self.files):
            return 1
        if any(item.status == "failed" for item in self.pending_indexes):
            return 1
        if any(item.status == "deferred" for item in self.files):
            return 75
        if self.pending_indexes:
            return 2
        return 0

    @property
    def status(self) -> str:
        """状态与退出码保持同源。"""

        return {0: "completed", 1: "failed", 2: "index_pending", 75: "deferred"}[self.exit_code]

    def to_dict(self) -> dict[str, object]:
        """只报告当前工作覆盖，不把队列为空等同于全库检索已验收。"""

        return {
            "run_id": self.run_id,
            "status": self.status,
            "exit_code": self.exit_code,
            "files": [asdict(item) for item in self.files],
            "import": ImportRunSummary(self.batches).to_dict(),
            "indexes": {
                "updater": "connected" if self.updater_connected else "integration_required",
                "pending": [asdict(item) for item in self.pending_indexes],
                "retrieval_readiness": "pending" if self.pending_indexes else "not_verified",
            },
        }
