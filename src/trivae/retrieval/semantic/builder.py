"""Canonical message streaming 到 semantic derived index 的 rebuild 编排。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import perf_counter

from trivae.retrieval.semantic.chunking import (
    DEFAULT_SEMANTIC_CHUNK_CONFIG,
    SEMANTIC_CHUNKER_VERSION,
    SemanticChunker,
    is_semantic_void,
)
from trivae.retrieval.semantic.contracts import (
    EmbeddingProvider,
    SemanticBuildStats,
    SemanticChunk,
    SemanticEmbeddingError,
    SemanticIndexIdentity,
    SemanticIndexStatus,
    SemanticIndexStore,
    SemanticMessage,
)
from trivae.retrieval.structured import CanonicalReadRepository, MessageQuery


@dataclass
class _PendingParent:
    """尚未全部写入的 Parent 进度；只保存计数，不缓存 canonical 正文。"""

    message_count: int
    remaining_chunk_count: int


@dataclass(frozen=True)
class _PendingBuildStats:
    """一次有界 pending flush 的 embedding/write 与进度事实。"""

    processed_message_count: int
    embedding_batch_count: int
    embedding_elapsed_ms: float
    index_write_elapsed_ms: float


class SemanticIndexBuilder:
    """按 bounded parent 处理 canonical stream，并显式记录 rebuild 终态。"""

    def __init__(
        self,
        repository: CanonicalReadRepository,
        store: SemanticIndexStore,
        provider: EmbeddingProvider,
        *,
        database_identity: str,
        chunker: SemanticChunker | None = None,
        read_batch_size: int = 256,
    ) -> None:
        if isinstance(read_batch_size, bool) or not isinstance(read_batch_size, int) or read_batch_size <= 0:
            raise ValueError("semantic read_batch_size must be positive")
        self.repository = repository
        self.store = store
        self.provider = provider
        self.database_identity = database_identity
        self.chunker = chunker or SemanticChunker(DEFAULT_SEMANTIC_CHUNK_CONFIG, SEMANTIC_CHUNKER_VERSION)
        self.read_batch_size = read_batch_size

    @property
    def identity(self) -> SemanticIndexIdentity:
        """由 database、embedding 和完整 chunker config 组成可比较 identity。"""

        return SemanticIndexIdentity(
            database_identity=self.database_identity,
            embedding=self.provider.identity,
            chunker_version=self.chunker.version,
            chunker_config=self.chunker.config.to_dict(),
        )

    def rebuild(self) -> SemanticBuildStats:
        """重建整个 derived index；任何 provider/store 错误都会留下 failed 状态并继续抛出。"""

        started = perf_counter()
        identity = self.identity
        canonical_count = self.repository.count_messages(MessageQuery(limit=1))
        self.store.start_rebuild(identity, canonical_count)
        processed = 0
        eligible_messages = 0
        semantic_void_messages = 0
        parent_count = 0
        chunk_count = 0
        skipped_void_chunks = 0
        embedding_batch_count = 0
        embedding_elapsed_ms = 0.0
        index_write_elapsed_ms = 0.0
        model_load_elapsed_ms = 0.0
        parent: list[SemanticMessage] = []
        pending_chunks: list[SemanticChunk] = []
        pending_parents: deque[_PendingParent] = deque()
        try:
            # 模型加载在 building 状态内显式发生，失败时 derived state 会保留 provider-owned 终态。
            model_load_started = perf_counter()
            self.provider.preload()
            model_load_elapsed_ms = (perf_counter() - model_load_started) * 1000
            for projection in self.repository.iter_semantic_messages(self.read_batch_size):
                message = SemanticMessage.from_projection(projection)
                if is_semantic_void(message):
                    semantic_void_messages += 1
                else:
                    eligible_messages += 1
                if parent and self.chunker.starts_new_parent(parent[-1], message, parent):
                    parent_result = self.chunker.chunk_parent(parent)
                    parent_count += 1
                    chunk_count += len(parent_result.chunks)
                    skipped_void_chunks += parent_result.skipped_void_chunks
                    # 相邻 Parent 共用同一个有界队列，避免大量不足 batch_size 的模型调用。
                    pending_chunks.extend(parent_result.chunks)
                    pending_parents.append(
                        _PendingParent(
                            message_count=len(parent),
                            remaining_chunk_count=len(parent_result.chunks),
                        )
                    )
                    pending_stats = self._flush_pending(
                        pending_chunks,
                        pending_parents,
                        flush_all=False,
                    )
                    processed += pending_stats.processed_message_count
                    embedding_batch_count += pending_stats.embedding_batch_count
                    embedding_elapsed_ms += pending_stats.embedding_elapsed_ms
                    index_write_elapsed_ms += pending_stats.index_write_elapsed_ms
                    if pending_stats.processed_message_count:
                        self.store.update_progress(processed)
                    parent = []
                parent.append(message)

            if parent:
                parent_result = self.chunker.chunk_parent(parent)
                parent_count += 1
                chunk_count += len(parent_result.chunks)
                skipped_void_chunks += parent_result.skipped_void_chunks
                pending_chunks.extend(parent_result.chunks)
                pending_parents.append(
                    _PendingParent(
                        message_count=len(parent),
                        remaining_chunk_count=len(parent_result.chunks),
                    )
                )

            # 最后一批允许不足 batch_size；成功写入后再推进 canonical watermark。
            pending_stats = self._flush_pending(
                pending_chunks,
                pending_parents,
                flush_all=True,
            )
            processed += pending_stats.processed_message_count
            embedding_batch_count += pending_stats.embedding_batch_count
            embedding_elapsed_ms += pending_stats.embedding_elapsed_ms
            index_write_elapsed_ms += pending_stats.index_write_elapsed_ms
            if pending_stats.processed_message_count:
                self.store.update_progress(processed)

            status: SemanticIndexStatus = "completed" if processed == canonical_count else "partial"
            self.store.finish(status)
        except BaseException as exc:
            # Ctrl+C 也必须结束 building 状态；这里只保存类型，随后原样重新抛出中断/异常。
            self.store.finish("failed", f"{type(exc).__name__}")
            raise

        return SemanticBuildStats(
            status=status,
            canonical_message_count=canonical_count,
            indexed_message_count=processed,
            eligible_message_count=eligible_messages,
            semantic_void_message_count=semantic_void_messages,
            parent_count=parent_count,
            chunk_count=chunk_count,
            skipped_void_chunks=skipped_void_chunks,
            embedding_count=chunk_count,
            embedding_batch_size=self.provider.document_batch_size,
            embedding_batch_count=embedding_batch_count,
            model_load_elapsed_ms=model_load_elapsed_ms,
            embedding_elapsed_ms=embedding_elapsed_ms,
            index_write_elapsed_ms=index_write_elapsed_ms,
            elapsed_ms=(perf_counter() - started) * 1000,
            index_size_bytes=self.store.size_bytes(),
            identity=identity,
        )

    def _flush_pending(
        self,
        chunks: list[SemanticChunk],
        parents: deque[_PendingParent],
        *,
        flush_all: bool,
    ) -> _PendingBuildStats:
        """按 provider batch 上限写入跨 Parent chunks，并只提交已完整覆盖的 Parent 进度。"""

        processed_message_count = self._consume_completed_parents(parents)
        embedding_batch_count = 0
        embedding_elapsed_ms = 0.0
        index_write_elapsed_ms = 0.0
        batch_size = self.provider.document_batch_size
        while len(chunks) >= batch_size or (flush_all and chunks):
            current_size = min(batch_size, len(chunks))
            batch = tuple(chunks[:current_size])
            embedding_started = perf_counter()
            vectors = self.provider.embed_documents(tuple(chunk.embedding_input for chunk in batch))
            embedding_elapsed_ms += (perf_counter() - embedding_started) * 1000
            embedding_batch_count += 1
            if len(vectors) != len(batch):
                raise SemanticEmbeddingError(
                    f"embedding output count mismatch: expected {len(batch)}, got {len(vectors)}"
                )
            write_started = perf_counter()
            self.store.insert_chunks(tuple(zip(batch, vectors, strict=True)))
            index_write_elapsed_ms += (perf_counter() - write_started) * 1000
            # 只有向量和 metadata 同事务成功后，才从 pending 队列消费对应范围。
            del chunks[:current_size]
            remaining = current_size
            while remaining:
                current_parent = parents[0]
                consumed = min(remaining, current_parent.remaining_chunk_count)
                current_parent.remaining_chunk_count -= consumed
                remaining -= consumed
                processed_message_count += self._consume_completed_parents(parents)

        if flush_all and (chunks or parents):
            raise SemanticEmbeddingError("semantic pending batches did not drain completely")
        return _PendingBuildStats(
            processed_message_count=processed_message_count,
            embedding_batch_count=embedding_batch_count,
            embedding_elapsed_ms=embedding_elapsed_ms,
            index_write_elapsed_ms=index_write_elapsed_ms,
        )

    @staticmethod
    def _consume_completed_parents(parents: deque[_PendingParent]) -> int:
        """按原始顺序推进已无待写 chunk 的 Parent，包括 semantic-void-only Parent。"""

        processed = 0
        while parents and parents[0].remaining_chunk_count == 0:
            processed += parents.popleft().message_count
        return processed
