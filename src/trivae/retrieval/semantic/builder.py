"""Canonical message streaming 到 semantic derived index 的 rebuild 编排。"""

from __future__ import annotations

from collections.abc import Sequence
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
    SemanticEmbeddingError,
    SemanticIndexIdentity,
    SemanticIndexStatus,
    SemanticIndexStore,
    SemanticMessage,
)
from trivae.retrieval.structured import CanonicalReadRepository, MessageQuery


@dataclass(frozen=True)
class _ParentBuildStats:
    """单个 Parent 的 bounded embedding/write 事实，只在 builder 内聚合。"""

    chunk_count: int
    skipped_void_chunks: int
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
                    parent_stats = self._index_parent(parent)
                    parent_count += 1
                    chunk_count += parent_stats.chunk_count
                    skipped_void_chunks += parent_stats.skipped_void_chunks
                    embedding_batch_count += parent_stats.embedding_batch_count
                    embedding_elapsed_ms += parent_stats.embedding_elapsed_ms
                    index_write_elapsed_ms += parent_stats.index_write_elapsed_ms
                    processed += len(parent)
                    self.store.update_progress(processed)
                    parent = []
                parent.append(message)

            if parent:
                parent_stats = self._index_parent(parent)
                parent_count += 1
                chunk_count += parent_stats.chunk_count
                skipped_void_chunks += parent_stats.skipped_void_chunks
                embedding_batch_count += parent_stats.embedding_batch_count
                embedding_elapsed_ms += parent_stats.embedding_elapsed_ms
                index_write_elapsed_ms += parent_stats.index_write_elapsed_ms
                processed += len(parent)
                self.store.update_progress(processed)

            status: SemanticIndexStatus = "completed" if processed == canonical_count else "partial"
            self.store.finish(status)
        except Exception as exc:
            # 失败状态只写入异常类型，避免把 provider message/raw input 写入 derived metadata。
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

    def _index_parent(self, parent: Sequence[SemanticMessage]) -> _ParentBuildStats:
        """对单个 bounded parent 切 child、批量 embed，再原子写入 vector store。"""

        result = self.chunker.chunk_parent(parent)
        chunks = result.chunks
        embedding_batch_count = 0
        embedding_elapsed_ms = 0.0
        index_write_elapsed_ms = 0.0
        for offset in range(0, len(chunks), self.provider.document_batch_size):
            batch = chunks[offset : offset + self.provider.document_batch_size]
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
        return _ParentBuildStats(
            chunk_count=len(chunks),
            skipped_void_chunks=result.skipped_void_chunks,
            embedding_batch_count=embedding_batch_count,
            embedding_elapsed_ms=embedding_elapsed_ms,
            index_write_elapsed_ms=index_write_elapsed_ms,
        )
