"""共享 ingestion pipeline。

所有输入文件都经过同一个 SharedImporter；source-specific 逻辑停留在
QQExportParser，去重、membership 更新、Store 写入和 ImportBatch 统计不按
文件版本复制实现。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from trivae.data.ingestion.qq_export import QQExportParser
from trivae.data.model import (
    ImportBatchSummary,
    ImportRunSummary,
    IngestionError,
    ParsedExport,
    RecordValidationError,
)
from trivae.data.storage.sqlite import SQLiteCanonicalStore


class SharedImporter:
    """把多个 Parser 结果导入同一个 Canonical Store。"""

    def __init__(self, store: SQLiteCanonicalStore, parser: QQExportParser | None = None) -> None:
        self.store = store
        self.parser = parser or QQExportParser()

    def import_directory(self, raw_directory: Path) -> ImportRunSummary:
        """按文件名稳定排序导入目录中的 JSON 文件。"""

        if not raw_directory.exists():
            raise IngestionError(f"Raw directory does not exist: {raw_directory}")
        if not raw_directory.is_dir():
            raise IngestionError(f"Raw path is not a directory: {raw_directory}")

        # 排序让冲突时的 canonical first-wins 选择可重复，且不依赖文件系统遍历顺序。
        paths = sorted(path for path in raw_directory.iterdir() if path.is_file() and path.suffix == ".json")
        if not paths:
            raise IngestionError(f"Raw directory contains no JSON files: {raw_directory}")

        batches: list[ImportBatchSummary] = []
        for path in paths:
            # 已分类的文件级错误会形成 failed batch 后继续处理其他文件；错误仍会让 CLI 非零退出。
            try:
                parsed = self.parser.parse(path)
            except IngestionError as exc:
                batches.append(
                    self.store.record_file_failure(
                        source_file=path.name,
                        error_code=self._error_code(exc),
                        error_message=str(exc),
                    )
                )
                continue

            batches.append(self._import_parsed_export(parsed))

        return ImportRunSummary(batches=tuple(batches))

    def import_paths(self, paths: Iterable[Path]) -> ImportRunSummary:
        """为测试和上层调用提供显式文件列表入口。"""

        batches: list[ImportBatchSummary] = []
        for path in sorted(paths):
            try:
                parsed = self.parser.parse(path)
            except IngestionError as exc:
                batches.append(
                    self.store.record_file_failure(
                        source_file=path.name,
                        error_code=self._error_code(exc),
                        error_message=str(exc),
                    )
                )
                continue
            batches.append(self._import_parsed_export(parsed))
        return ImportRunSummary(batches=tuple(batches))

    def _import_parsed_export(self, parsed: ParsedExport) -> ImportBatchSummary:
        """以一个文件为 transaction，处理该文件的所有 normalized messages。"""

        self.store.begin()
        batch_id: str | None = None
        received_count = 0
        inserted_count = 0
        enriched_count = 0
        duplicate_count = 0
        conflict_count = 0
        error_count = 0
        try:
            # 先登记 source/session，再处理消息，保证外键和 provenance 有归属。
            self.store.upsert_source(parsed.source)
            self.store.upsert_session(parsed.source, parsed.session)
            batch_id = self.store.create_batch(
                source_file=parsed.source.file_name,
                session_id=parsed.session.session_id,
                source_id=parsed.source.source_id,
            )

            # 每条消息都保留原始 record index，错误和冲突可以回到源文件定位。
            for record_index, raw_message in enumerate(parsed.messages):
                received_count += 1
                try:
                    normalized_items = self.parser.iter_normalized_messages(
                        ParsedExport(
                            source=parsed.source,
                            session=parsed.session,
                            messages=[raw_message],
                        ),
                        record_index_offset=record_index,
                    )
                    _, message = next(iter(normalized_items))
                except RecordValidationError as exc:
                    error_count += 1
                    self.store.record_error(
                        batch_id=batch_id,
                        source_id=parsed.source.source_id,
                        record_index=record_index,
                        error_code=exc.error_code,
                        error_message=str(exc),
                        raw_locator=f"{parsed.source.file_name}#messages[{record_index}]",
                    )
                    continue

                # 先更新身份和时间范围，再尝试写 message；重复消息也可能带来最新 membership 展示名。
                self.store.observe_message_metadata(message, chat_name=parsed.source.chat_name)
                result = self.store.write_message(message)
                if result.inserted:
                    inserted_count += 1
                elif result.enriched:
                    enriched_count += 1
                else:
                    duplicate_count += 1
                if result.conflict:
                    conflict_count += 1

            status = "completed" if error_count == 0 else "partial"
            summary = self.store.finish_batch(
                batch_id=batch_id,
                received_count=received_count,
                inserted_count=inserted_count,
                enriched_count=enriched_count,
                duplicate_count=duplicate_count,
                conflict_count=conflict_count,
                error_count=error_count,
                status=status,
                error_message=None if error_count == 0 else "One or more records could not be normalized",
            )
            self.store.commit()
            return summary
        except Exception:
            # 未知异常不能伪装成部分成功；先回滚文件 transaction，再原样抛出根因。
            self.store.rollback()
            raise

    @staticmethod
    def _error_code(error: IngestionError) -> str:
        """把已知导入异常投影成稳定、可检索的 batch error code。"""

        # 只读取异常类型声明的 code，避免文案改动导致错误分类漂移。
        return error.error_code
