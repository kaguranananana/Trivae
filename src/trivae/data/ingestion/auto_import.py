"""稳定文件发现、共享导入器编排及持久补偿；不实现第二套 QQ 解析。"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from trivae.data.ingestion.auto_import_contracts import (
    AutoImportReport,
    FileOutcome,
    FileStillChanging,
    FileVersion,
    IncrementalIndexUpdater,
)
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.ingestion.qq_export import QQExportParser
from trivae.data.model import CanonicalMessage, ImportBatchSummary, IngestionError, ParsedExport
from trivae.data.storage.sqlite_auto_import import SQLiteAutoImportState

logger = logging.getLogger(__name__)


class _ParsedSnapshotParser(QQExportParser):
    """只缓存当前不可变快照的解析结果，规范化仍委托同一个原 Parser。"""

    def __init__(self, parser: QQExportParser, result: ParsedExport | IngestionError) -> None:
        self.parser = parser
        self.result = result

    def parse(self, path: Path) -> ParsedExport:
        """核验失败转入 import_paths 时，不再次读取或解码同一个 JSON。"""

        if isinstance(self.result, IngestionError):
            # 已分类的格式错误仍交给 SharedImporter 记录原有 failed batch。
            raise self.result
        return self.result

    def iter_normalized_messages(
        self, parsed: ParsedExport, record_index_offset: int = 0
    ) -> Iterable[tuple[int, CanonicalMessage]]:
        """保留原 Parser 的消息、转发、record index 和错误语义。"""

        return self.parser.iter_normalized_messages(parsed, record_index_offset)


class IncrementalImporter:
    """只负责待办选择与重启恢复，所有消息语义仍属于 SharedImporter。"""

    def __init__(
        self,
        importer: SharedImporter,
        *,
        index_updater: IncrementalIndexUpdater | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self.importer = importer
        self.state = SQLiteAutoImportState(importer.store.connection)
        self.index_updater = index_updater
        self.sleep = sleep
        self.now_ns = now_ns

    def run(self, raw_directory: Path, *, settle_seconds: float = 5, min_age_seconds: float = 60) -> AutoImportReport:
        """每次检查全部未完成文件，时间窗只用于稳定判断而不用于发现。"""

        run_id = self.state.start_run()
        try:
            report = self._run(run_id, raw_directory.resolve(), settle_seconds, min_age_seconds)
        except Exception as exc:
            # 未知运行级异常保留原始 traceback，状态不能成为成功。
            self.state.finish_run(run_id, error=f"{type(exc).__name__}: {exc}")
            raise
        self.state.finish_run(run_id, summary=report.to_dict())
        return report

    def _run(self, run_id: str, raw_directory: Path, settle_seconds: float, min_age_seconds: float) -> AutoImportReport:
        """先恢复 durable batch，再扫描积压，最后独立补偿索引。"""

        files: list[FileOutcome] = []
        batches: list[ImportBatchSummary] = []
        for path, _, batch in self.state.recover():
            if batch is not None:
                # 提交后中断不必再次解析，索引义务也在恢复时补齐。
                batches.append(batch)
                files.append(FileOutcome(str(path), "recovered", batch_id=batch.batch_id))

        if not raw_directory.is_dir():
            raise IngestionError(f"Raw directory does not exist or is not a directory: {raw_directory}")

        candidates: list[tuple[Path, FileVersion]] = []
        for path in sorted(raw_directory.iterdir()):
            if path.suffix != ".json" or not path.is_file():
                continue
            version = FileVersion.read(path)
            previous = self.state.file(path)
            if (
                previous is not None
                and previous["status"] == "completed"
                and previous["version"] == version.serialized()
            ):
                files.append(FileOutcome(str(path), "unchanged", batch_id=previous["batch_id"]))
                continue
            # 过新的文件不打开，避免读到 QCE 当前正写入的内容。
            if self.now_ns() - max(version.modified_ns, version.changed_ns) < min_age_seconds * 1_000_000_000:
                reason = "File was modified too recently; retry after the quiet period"
                self.state.observe(path, version.serialized(), "deferred", reason)
                files.append(FileOutcome(str(path), "deferred", reason))
                continue
            candidates.append((path, version))

        if candidates:
            # 所有候选共用一次观察等待，耗时不会按历史文件数倍增。
            self.sleep(settle_seconds)
        for path, version in candidates:
            try:
                self._check_version(path, version)
                # 没有既有运维记录时才尝试历史接管，失败/partial 永远不能靠历史成功掩盖。
                historical = self.state.historical_candidate(path, version) if self.state.file(path) is None else None
                # 保留 basename，确保 source_id / raw locator 与直接导入完全一致。
                with tempfile.TemporaryDirectory(prefix="trivae-import-") as temporary:
                    snapshot = Path(temporary) / path.name
                    self._snapshot(path, snapshot, version)
                    original_parser = self.importer.parser
                    cached_parser: QQExportParser = original_parser
                    if historical is not None:
                        parsed_result: ParsedExport | IngestionError
                        try:
                            # 首次历史核验只解码一次；旧批次时间不能替代输入内容的证明。
                            parsed_result = original_parser.parse(snapshot)
                        except IngestionError as exc:
                            parsed_result = exc
                        if isinstance(parsed_result, ParsedExport) and self.state.matches_historical_export(
                            parsed_result, historical
                        ):
                            self.state.finish_file(path, version.serialized(), historical, enqueue=False)
                            files.append(FileOutcome(str(path), "adopted", batch_id=historical.batch_id))
                            continue
                        cached_parser = _ParsedSnapshotParser(original_parser, parsed_result)
                    self.state.prepare(path, version)
                    # 仅为这一个快照缓存 Parser 结果，不改变 SharedImporter 的任何导入逻辑。
                    self.importer.parser = cached_parser
                    try:
                        # JSON 格式校验由原 Parser 完成，只解析一次快照后进入原文件级事务。
                        batch = self.importer.import_paths((snapshot,)).batches[0]
                    except Exception as exc:
                        # importer 已回滚未知文件级异常；其余文件仍可独立完成。
                        reason = f"{type(exc).__name__}: {exc}"
                        self.state.observe(path, version.serialized(), "failed", reason)
                        files.append(FileOutcome(str(path), "failed", reason))
                        logger.exception("QCE import failed: file=%s", path)
                        continue
                    finally:
                        # 无论成功、失败或中断，都恢复注入的 Parser 实例。
                        self.importer.parser = original_parser
                    # 故意放在 importer 异常捕获之外：此处失败必须保留 importing 供下次恢复。
                    self.state.finish_file(path, version.serialized(), batch)
                    batches.append(batch)
                    files.append(FileOutcome(str(path), batch.status, batch.error_message, batch.batch_id))
            except FileStillChanging as exc:
                self.state.observe(path, version.serialized(), "deferred", str(exc))
                files.append(FileOutcome(str(path), "deferred", str(exc)))
            except OSError as exc:
                reason = f"{type(exc).__name__}: {exc}"
                self.state.observe(path, version.serialized(), "failed", reason)
                files.append(FileOutcome(str(path), "failed", reason))
                logger.exception("QCE file snapshot failed: file=%s", path)

        self._update_indexes()
        return AutoImportReport(
            run_id, tuple(files), tuple(batches), self.state.pending_indexes(), self.index_updater is not None
        )

    @staticmethod
    def _check_version(path: Path, expected: FileVersion) -> None:
        """第二次采样与复制后均检查，文件原地追加和原子替换都会被发现。"""

        if FileVersion.read(path) != expected:
            raise FileStillChanging(f"File changed during stability check: {path.name}")

    @classmethod
    def _snapshot(cls, path: Path, snapshot: Path, expected: FileVersion) -> None:
        """复制稳定输入，不把可变的 QCE 文件直接交给导入事务。"""

        with path.open("rb") as source, snapshot.open("wb") as target:
            # 校验实际打开的 inode，避免采样后文件被 QCE 替换。
            if FileVersion.from_stat(os.fstat(source.fileno())) != expected:
                raise FileStillChanging(f"File changed before snapshot: {path.name}")
            # 二进制复制不解释消息，解析/验证完全交给共享导入器。
            shutil.copyfileobj(source, target)
            # 已打开文件也必须未变，不能只检查可能已指向另一 inode 的路径。
            if FileVersion.from_stat(os.fstat(source.fileno())) != expected:
                raise FileStillChanging(f"File changed while copying snapshot: {path.name}")
        # 复制后确认原路径仍是同一稳定版本；之后的写入会在下次扫描形成新版本。
        cls._check_version(path, expected)

    def _update_indexes(self) -> None:
        """只处理持久新增义务；无 updater 时显式待集成，绝不调用全量 rebuild。"""

        if self.index_updater is None:
            return
        for kind in ("lexical", "semantic"):
            work = self.state.pending_indexes(kind)
            if not work:
                continue
            self.state.mark_indexes(work, "running")
            try:
                # updater 拥有最终增量算法及提交边界；本层只确认其成功返回。
                self.index_updater.update(kind, work)
            except Exception as exc:
                reason = f"{type(exc).__name__}: {exc}"
                self.state.mark_indexes(work, "failed", reason)
                logger.exception("QCE index update failed: kind=%s", kind)
            else:
                # 索引提交后才确认，进程中断留下 running 会在下次重放。
                self.state.mark_indexes(work, "completed")
